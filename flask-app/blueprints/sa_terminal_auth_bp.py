# -*- coding: utf-8 -*-
"""
SA 终端认证蓝图 (flow_sa_pc_mobile_20261020)
════════════════════════════════════════════════════════════════
PC 终端: 服务器双钥在位 + 设备信任令牌(30天HttpOnly Cookie) → 即插即用免密进入 SA
移动终端: 三因子 = WebAuthn面部 + WebAuthn指纹 + 蓝牙 Trae AI Passport (GATT 校验)

事实源不变: 服务器侧 VIKEY+SZU100 双钥 (get_hardware_key_provider)
全链审计: mt_sa_dual_key_status (trigger_reason=SA_TERMINAL_*)
"""
import os
import json
import base64
import hashlib
import hmac as _hmac
import sqlite3
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request, session, jsonify, redirect, render_template, current_app

from core.services.vikey_driver import get_hardware_key_provider

sa_terminal_auth_bp = Blueprint('sa_terminal_auth', __name__)

_FLASK_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DB = os.path.join(_FLASK_APP, 'database', 'app.db')

TRUST_COOKIE = 'mt_sa_device'
TRUST_DAYS = 30
_WA_SESSION = {}   # 内存: challenge 传递 (challenge_b64, cred_type, ts) — 单机部署, 重启失效可重注册

_AUDIT_COLS = None


def _db():
    conn = sqlite3.connect(APP_DB, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables():
    conn = _db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS mt_sa_trust_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_hash TEXT UNIQUE NOT NULL,     -- UA+平台 指纹哈希
            token_hash TEXT NOT NULL,             -- 信任令牌哈希 (明文仅存 Cookie)
            label TEXT DEFAULT '',
            issued_at TEXT DEFAULT (datetime('now','localtime')),
            expires_at TEXT,
            last_used_at TEXT,
            use_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mt_sa_mobile_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cred_type TEXT NOT NULL,              -- face / fingerprint
            credential_id TEXT UNIQUE NOT NULL,   -- base64url
            pub_x TEXT, pub_y TEXT,               -- EC2 P-256 公钥坐标 (base64url)
            sign_count INTEGER DEFAULT 0,
            registered_at TEXT DEFAULT (datetime('now','localtime')),
            last_used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mt_sa_bt_passports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial TEXT UNIQUE NOT NULL,          -- Trae AI Passport 蓝牙序列号
            name TEXT DEFAULT 'Trae AI Passport',
            psk TEXT NOT NULL,                    -- GATT HMAC 共享密钥 (可选, v2 生效)
            status TEXT DEFAULT 'ACTIVE',
            registered_at TEXT DEFAULT (datetime('now','localtime')),
            last_verified_at TEXT,
            verify_count INTEGER DEFAULT 0
        );
        """)
        conn.commit()
    finally:
        conn.close()


def _audit(action, detail):
    """审计 → mt_sa_dual_key_status (列名自适应)"""
    try:
        conn = _db()
        cols = [r[1] for r in conn.execute('PRAGMA table_info(mt_sa_dual_key_status)')]
        if not cols:
            conn.close()
            return
        payload = {'check_time': datetime.now().isoformat(),
                   'trigger_reason': f'SA_TERMINAL_{action}',
                   'sa_layout': 'SA_PROPRIETARY',
                   'note': json.dumps(detail, ensure_ascii=False)[:800]}
        row = {c: payload[c] for c in cols if c in payload}
        conn.execute(f"INSERT INTO mt_sa_dual_key_status ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                     list(row.values()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _dual_ok():
    try:
        ok, _ = get_hardware_key_provider().verify_dual_key_atomic(timeout=12.0)
        return bool(ok)
    except Exception:
        return False


def _is_mobile_ua():
    ua = request.headers.get('User-Agent', '')
    return any(k in ua for k in ('iPhone', 'iPad', 'Android', 'Mobile', 'HarmonyOS'))


def _device_hash():
    raw = request.headers.get('User-Agent', '') + '|' + (request.headers.get('Accept-Language', '') or '')
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ════════════════ PC: 设备信任令牌 + 即插即用免密 ════════════════

def issue_trust_token(label='PC'):
    """信任令牌签发/轮换 (SA 完整认证通过后调用)"""
    _ensure_tables()
    token = 'msdt_' + secrets.token_hex(24)
    dh = _device_hash()
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_sa_trust_devices (device_hash, token_hash, label, expires_at) VALUES (?,?,?,?)",
                     (dh, hashlib.sha256(token.encode()).hexdigest(), label,
                      (datetime.now() + timedelta(days=TRUST_DAYS)).isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.execute("UPDATE mt_sa_trust_devices SET token_hash=?, expires_at=?, last_used_at=datetime('now','localtime') WHERE device_hash=?",
                     (hashlib.sha256(token.encode()).hexdigest(),
                      (datetime.now() + timedelta(days=TRUST_DAYS)).isoformat(), dh))
        conn.commit()
    finally:
        conn.close()
    _audit('TRUST_ISSUED', {'device_hash': dh, 'label': label, 'days': TRUST_DAYS})
    return token


def _trust_valid(token):
    """信任令牌校验: 哈希匹配 + 未过期 + 双钥在位由调用方判定"""
    if not token:
        return False
    _ensure_tables()
    conn = _db()
    try:
        r = conn.execute("SELECT id, expires_at FROM mt_sa_trust_devices WHERE device_hash=? AND token_hash=?",
                         (_device_hash(), hashlib.sha256(token.encode()).hexdigest())).fetchone()
        if not r:
            return False
        if str(r['expires_at'] or '') < datetime.now().isoformat():
            conn.execute("DELETE FROM mt_sa_trust_devices WHERE id=?", (r['id'],))
            conn.commit()
            return False
        conn.execute("UPDATE mt_sa_trust_devices SET last_used_at=datetime('now','localtime'), use_count=use_count+1 WHERE id=?", (r['id'],))
        conn.commit()
        return True
    finally:
        conn.close()


def _auto_sa_session():
    """免密建立完整 SA 会话 (仅信任设备+双钥在位时调用)"""
    session.clear()
    session['user_id'] = 15
    session['username'] = 'wuchenghao15'
    session['role'] = 'super_admin'
    session['role_canonical'] = 'super_admin'
    session['logged_in'] = True
    session['remote_dual_verified'] = True
    session['remote_dual_verified_at'] = datetime.now().isoformat()
    session['plug_login'] = True
    session['csrf_token'] = secrets.token_hex(16)
    _audit('PLUG_LOGIN_OK', {'device_hash': _device_hash(), 'ip': request.remote_addr})


@sa_terminal_auth_bp.route('/sa/plug-login', methods=['GET', 'POST'])
def sa_plug_login():
    """PC 即插即用免密入口: 信任令牌 + 服务器双钥在位 → 直接建立 SA 会话"""
    token = request.cookies.get(TRUST_COOKIE)
    if _trust_valid(token) and _dual_ok():
        _auto_sa_session()
        return redirect('/sa/dashboard')
    _audit('PLUG_LOGIN_REJECT', {'reason': 'trust_invalid_or_dual_off',
                                 'trust': bool(token), 'ip': request.remote_addr})
    return redirect('/auth/login')


def plug_login_hook():
    """/sa/dashboard pre_auth 挂钩: 信任设备+双钥在位 → 免密直进 (返回 True 表示已接管)"""
    if session.get('logged_in') and session.get('role') == 'super_admin':
        return False
    token = request.cookies.get(TRUST_COOKIE)
    if _trust_valid(token) and _dual_ok():
        _auto_sa_session()
        return True
    return False


# ════════════════ 移动端: WebAuthn 双生物因子 ════════════════

def _b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64u_dec(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _mini_cbor(data, idx=0):
    """迷你 CBOR 解码器 (仅 authData/COSE 所需: map/int/negint/bytes/str/array)"""
    t = data[idx]; idx += 1
    maj, ai = t >> 5, t & 0x1f
    def _arg():
        nonlocal idx
        if ai < 24: return ai
        n = 1 << (ai - 24)
        v = int.from_bytes(data[idx:idx+n], 'big'); idx += n
        return v
    if maj == 0: return _arg(), idx
    if maj == 1: return -1 - _arg(), idx
    if maj == 2:
        n = _arg(); v = data[idx:idx+n]; idx += n
        return bytes(v), idx
    if maj == 3:
        n = _arg(); v = data[idx:idx+n].decode('utf-8', 'replace'); idx += n
        return v, idx
    if maj == 4:
        n = _arg(); return [None]*n, idx  # 数组不深入 (本流程未用)
    if maj == 5:
        n = _arg(); d = {}
        for _ in range(n):
            k, idx = _mini_cbor(data, idx)
            v, idx = _mini_cbor(data, idx)
            d[k] = v
        return d, idx
    if t in (0xf6, 0xf7): return None, idx
    raise ValueError(f'CBOR maj={maj} ai={ai} 不支持')


def _cose_ec2_xy(cose):
    """COSE EC2/P-256 → (x, y)"""
    if cose.get(1) != 2 or cose.get(3) != -7 or cose.get(-1) != 1:
        raise ValueError('非 EC2/P-256/ES256 公钥')
    return cose[-2], cose[-3]


def _parse_authdata(ad):
    """authData → (rpIdHash, flags, signCount, attestedCredentialData|None)"""
    if len(ad) < 37:
        raise ValueError('authData 过短')
    rp_id_hash = ad[:32]
    flags = ad[32]
    sign_count = int.from_bytes(ad[33:37], 'big')
    cred = None
    if flags & 0x40:  # AT
        p = 37
        aaguid = ad[p:p+16]; p += 16
        l = int.from_bytes(ad[p:p+2], 'big'); p += 2
        cred_id = ad[p:p+l]; p += l
        cose, _ = _mini_cbor(ad, p)
        cred = (aaguid, cred_id, cose)
    return rp_id_hash, flags, sign_count, cred


def _es256_verify(x, y, sig, data):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidSignature
    try:
        pub = ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, 'big'), int.from_bytes(y, 'big'), ec.SECP256R1()).public_key()
        pub.verify(sig, data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


_RP_ID_EXPECT = None  # 注册/断言时用 clientData origin 的 host 校验, 无需预置


def _client_ok(cdj_b64, typ, challenge):
    cd = json.loads(_b64u_dec(cdj_b64))
    if cd.get('type') != typ:
        return None
    if cd.get('challenge') != challenge:
        return None
    host = (cd.get('origin') or '').split('//')[-1].split('/')[0].split(':')[0]
    req_host = request.host.split(':')[0]
    if host and host != req_host and host not in ('localhost', '127.0.0.1'):
        # 局域网 IP / 域名 均要求与请求 host 一致, 防钓鱼域
        return None
    return cd


@sa_terminal_auth_bp.route('/api/sa/mobile/webauthn/options', methods=['POST'])
def wa_options():
    """签发 WebAuthn 挑战: cred_type ∈ {face, fingerprint}"""
    _ensure_tables()
    if not (session.get('logged_in') and session.get('username') == 'wuchenghao15'):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    cred_type = (request.get_json(silent=True) or {}).get('cred_type')
    if cred_type not in ('face', 'fingerprint'):
        return jsonify({'ok': False, 'error': 'cred_type 必须为 face/fingerprint'}), 400
    challenge = _b64u(secrets.token_bytes(32))
    _WA_SESSION[(session.get('user_id'), cred_type)] = (challenge, datetime.now().timestamp())
    conn = _db()
    try:
        creds = [{'id': r['credential_id'], 'type': 'public-key'} for r in conn.execute(
            "SELECT credential_id FROM mt_sa_mobile_credentials WHERE cred_type=?", (cred_type,))]
    finally:
        conn.close()
    rp_name = 'MTSCOS SA'
    if creds:
        return jsonify({'ok': True, 'mode': 'assert', 'cred_type': cred_type, 'challenge': challenge,
                        'allowCredentials': creds,
                        'userVerification': 'required',
                        'timeout': 60000})
    return jsonify({'ok': True, 'mode': 'register', 'cred_type': cred_type, 'challenge': challenge,
                    'rp': {'id': request.host.split(':')[0], 'name': rp_name},
                    'user': {'id': _b64u(b'mtscos-sa-wuchenghao15'), 'name': 'wuchenghao15', 'displayName': 'SA 超级管理员'},
                    'pubKeyCredParams': [{'type': 'public-key', 'alg': -7}],
                    'authenticatorSelection': {'authenticatorAttachment': 'platform',
                                               'userVerification': 'required', 'residentKey': 'preferred'},
                    'timeout': 60000})


@sa_terminal_auth_bp.route('/api/sa/mobile/webauthn/result', methods=['POST'])
def wa_result():
    """WebAuthn 注册/断言统一处理 (ES256 签名链完整校验)"""
    _ensure_tables()
    if not (session.get('logged_in') and session.get('username') == 'wuchenghao15'):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    cred_type = d.get('cred_type')
    key = (session.get('user_id'), cred_type)
    exp = _WA_SESSION.get(key)
    if not exp or datetime.now().timestamp() - exp[1] > 120:
        return jsonify({'ok': False, 'error': '挑战已过期, 重新验证'}), 403
    challenge = exp[0]
    try:
        cd = _client_ok(d.get('clientDataJSON', ''), 'webauthn.create' if d.get('mode') == 'register' else 'webauthn.get', challenge)
        if not cd:
            return jsonify({'ok': False, 'error': 'clientData 校验失败 (type/challenge/origin)'}), 403
        ad = _b64u_dec(d.get('authenticatorData', ''))
        rp_id_hash, flags, sign_count, cred = _parse_authdata(ad)
        if not (flags & 0x01):  # UP (user present)
            return jsonify({'ok': False, 'error': '用户未在场 (UP 未置位)'}), 403
        # UV (userVerified) 生物因子必须置位
        if not (flags & 0x04):
            return jsonify({'ok': False, 'error': '生物验证未通过 (UV 未置位)'}), 403
        conn = _db()
        try:
            if d.get('mode') == 'register':
                if not cred:
                    return jsonify({'ok': False, 'error': '缺少凭据数据'}), 400
                aaguid, cred_id, cose = cred
                x, y = _cose_ec2_xy(cose)
                conn.execute("INSERT OR REPLACE INTO mt_sa_mobile_credentials (cred_type, credential_id, pub_x, pub_y, sign_count) VALUES (?,?,?,?,0)",
                             (cred_type, _b64u(cred_id), _b64u(bytes(x)), _b64u(bytes(y))))
                conn.commit()
                _audit('WA_REGISTERED', {'cred_type': cred_type, 'origin': cd.get('origin')})
                return jsonify({'ok': True, 'action': 'registered', 'cred_type': cred_type})
            # assert
            row = conn.execute("SELECT * FROM mt_sa_mobile_credentials WHERE credential_id=? AND cred_type=?",
                               (d.get('credentialId', ''), cred_type)).fetchone()
            if not row:
                return jsonify({'ok': False, 'error': '凭据未注册'}), 403
            sig = _b64u_dec(d.get('signature', ''))
            # WebAuthn 规范: 签名覆盖 authenticatorData || SHA256(clientDataJSON)
            data = ad + hashlib.sha256(_b64u_dec(d.get('clientDataJSON', ''))).digest()
            if not _es256_verify(_b64u_dec(row['pub_x']), _b64u_dec(row['pub_y']), sig, data):
                return jsonify({'ok': False, 'error': '签名校验失败'}), 403
            conn.execute("UPDATE mt_sa_mobile_credentials SET sign_count=?, last_used_at=datetime('now','localtime') WHERE id=?",
                         (sign_count, row['id']))
            conn.commit()
        finally:
            conn.close()
        _WA_SESSION.pop(key, None)
        done = _mobile_factor_done(cred_type)
        _audit('WA_ASSERT_OK', {'cred_type': cred_type, 'sign_count': sign_count})
        return jsonify({'ok': True, 'action': 'asserted', 'cred_type': cred_type,
                        'all_biometrics_done': done, 'next': _mobile_next_hint()})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'WebAuthn 处理异常: {str(e)[:120]}'}), 400


# ════════════════ 移动端: 蓝牙 Trae AI Passport 因子 ════════════════

@sa_terminal_auth_bp.route('/api/sa/mobile/bt-passport/register', methods=['POST'])
def bt_register():
    """注册蓝牙 Passport 序列号 (SA 已登录后自助绑定)"""
    _ensure_tables()
    if not (session.get('logged_in') and session.get('role') == 'super_admin'):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    serial = (d.get('serial') or '').strip()
    if not (4 <= len(serial) <= 64):
        return jsonify({'ok': False, 'error': 'serial 长度 4-64'}), 400
    psk = d.get('psk') or secrets.token_hex(16)
    conn = _db()
    try:
        conn.execute("INSERT OR REPLACE INTO mt_sa_bt_passports (serial, psk, name, status) VALUES (?,?,?,?)",
                     (serial, _hmac.new(b'[REDACTED]', psk.encode(), hashlib.sha256).hexdigest(),
                      d.get('name') or 'Trae AI Passport', 'ACTIVE'))
        conn.commit()
    finally:
        conn.close()
    _audit('BT_REGISTERED', {'serial': serial})
    return jsonify({'ok': True, 'serial': serial, 'psk_echo': psk,
                    'hint': 'GATT 特征 0xFF01 = HMAC-SHA256(psk, challenge) 4字节 + counter 1字节; 无特征时仅序列号校验(v1)'})


@sa_terminal_auth_bp.route('/api/sa/mobile/bt-passport/verify', methods=['POST'])
def bt_verify():
    """蓝牙因子校验: 注册序列号 + (可选) GATT HMAC 证明"""
    _ensure_tables()
    if not (session.get('logged_in') and session.get('username') == 'wuchenghao15'):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    serial = (d.get('serial') or '').strip()
    nonce = d.get('nonce') or ''
    proof_hex = (d.get('proof') or '').lower()
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM mt_sa_bt_passports WHERE serial=? AND status='ACTIVE'", (serial,)).fetchone()
        if not row:
            _audit('BT_REJECT', {'serial': serial, 'reason': '未注册'})
            return jsonify({'ok': False, 'error': '蓝牙 Passport 未注册'}), 403
    finally:
        conn.close()
    if proof_hex:
        # v2: GATT HMAC-SHA256 证明 (对 nonce)
        if not nonce:
            return jsonify({'ok': False, 'error': '缺少 nonce'}), 400
        for off in (-2, -1, 0, 1, 2):  # 时钟/计数窗口 ±2
            material = f'{serial}|{nonce}|{off}'.encode()
            expect = _hmac.new(row['psk'].encode(), material, hashlib.sha256).hexdigest()[:16]
            if _hmac.compare_digest(expect, proof_hex[:16]):
                break
        else:
            _audit('BT_REJECT', {'serial': serial, 'reason': 'HMAC 证明不匹配'})
            return jsonify({'ok': False, 'error': '蓝牙证明校验失败'}), 403
    conn = _db()
    try:
        conn.execute("UPDATE mt_sa_bt_passports SET last_verified_at=datetime('now','localtime'), verify_count=verify_count+1 WHERE serial=?", (serial,))
        conn.commit()
    finally:
        conn.close()
    done = _mobile_factor_done('bt')
    _audit('BT_OK', {'serial': serial, 'mode': 'hmac' if proof_hex else 'serial_v1'})
    return jsonify({'ok': True, 'factor': 'bt', 'all_factors_done': done, 'next': _mobile_next_hint()})


# ════════════════ 移动端三因子会话闭环 ════════════════

def _mobile_factor_done(kind):
    s = session.get('sa_mobile_factors') or {}
    s[kind] = True
    session['sa_mobile_factors'] = s
    return bool(s.get('face') and s.get('fingerprint') and s.get('bt'))


def _mobile_next_hint():
    s = session.get('sa_mobile_factors') or {}
    order = [('face', '面部'), ('fingerprint', '指纹'), ('bt', '蓝牙 Passport')]
    for k, name in order:
        if not s.get(k):
            return f'待验证: {name}'
    return 'all_done'


@sa_terminal_auth_bp.route('/sa/mobile-verify')
def sa_mobile_verify_page():
    """移动端三因子验证页"""
    if not (session.get('logged_in') and session.get('username') == 'wuchenghao15'):
        return redirect('/auth/login')
    return render_template('sa_mobile_verify.html',
                           terminal_ip=request.remote_addr or '',
                           flow_id='SA_MOBILE_VERIFY_flow_sa_pc_mobile_20261020')


@sa_terminal_auth_bp.route('/api/sa/mobile/complete', methods=['POST'])
def sa_mobile_complete():
    """三因子齐备 → 解除移动会话挂起, 授予完整 SA 权限"""
    s = session.get('sa_mobile_factors') or {}
    if not (s.get('face') and s.get('fingerprint') and s.get('bt')):
        return jsonify({'ok': False, 'error': '三因子未齐备: ' + _mobile_next_hint()}), 403
    if not _dual_ok():
        return jsonify({'ok': False, 'error': '服务器双钥不在位, 认证拒绝'}), 403
    session['sa_mobile_pending'] = False
    session['sa_mobile_factors'] = {}
    session['remote_dual_verified'] = True
    session['remote_dual_verified_at'] = datetime.now().isoformat()
    _audit('MOBILE_3FA_OK', {'ip': request.remote_addr, 'ua': request.headers.get('User-Agent', '')[:80]})
    return jsonify({'ok': True, 'redirect': '/sa/dashboard'})


# ══ SA 会话免密维持 (flow_sa_session_20261020) ══
@sa_terminal_auth_bp.route('/api/sa/session/keepalive', methods=['POST'])
def sa_session_keepalive():
    """SA 在位心跳: 双钥在线 → session.permanent 续期免密维持; 双钥离线 → fail-closed 不续期.

    - 仅已登录 SA (wuchenghao15) 有效, 其他用户 403
    - 双钥校验走聚合缓存 (不强刷), 2s TTL, 开销可忽略
    - 续期 = session.permanent=True + modified 标记, Flask 下次响应重发 cookie
    """
    if not (session.get('logged_in') and str(session.get('username') or '').lower() == 'wuchenghao15'):
        return jsonify({'ok': False, 'error': 'SA_ONLY'}), 403
    dual_ok = _dual_ok()
    if not dual_ok:
        # fail-closed: 双钥离线不续期, 会话自然过期
        _audit('SESSION_KEEPALIVE_REJECT', {'ip': request.remote_addr})
        return jsonify({'ok': False, 'dual_ok': False, 'error': '双钥不在位, 会话不续期'}), 403
    session.permanent = True
    session.modified = True
    lifetime_h = int((current_app.config.get('PERMANENT_SESSION_LIFETIME', 86400 * 7)) / 3600)
    return jsonify({'ok': True, 'dual_ok': True, 'session_permanent': True,
                    'lifetime_hours': lifetime_h, 'ts': datetime.now().isoformat(timespec='seconds')})


@sa_terminal_auth_bp.route('/api/sa/session/status')
def sa_session_status():
    """SA 会话状态: 登录态/permanent/双钥 (供前端心跳首探)"""
    return jsonify({
        'ok': True,
        'logged_in': bool(session.get('logged_in')),
        'is_sa': str(session.get('username') or '').lower() == 'wuchenghao15',
        'session_permanent': bool(session.get('permanent')),
        'dual_ok': _dual_ok(),
    })


@sa_terminal_auth_bp.route('/api/sa/terminal/status')
def sa_terminal_status():
    """终端认证状态总览 (信任设备/生物凭据/蓝牙护照)"""
    _ensure_tables()
    conn = _db()
    try:
        td = conn.execute("SELECT count(*) n, sum(use_count) u FROM mt_sa_trust_devices").fetchone()
        wa = {r['cred_type']: r['n'] for r in conn.execute(
            "SELECT cred_type, count(*) n FROM mt_sa_mobile_credentials GROUP BY cred_type")}
        bt = conn.execute("SELECT count(*) n, sum(verify_count) v FROM mt_sa_bt_passports WHERE status='ACTIVE'").fetchone()
        recent = [dict(r) for r in conn.execute(
            "SELECT trigger_reason, substr(note,1,90) note, check_time FROM mt_sa_dual_key_status "
            "WHERE trigger_reason LIKE 'SA_TERMINAL%' ORDER BY id DESC LIMIT 6")]
        return jsonify({'ok': True, 'dual_key_now': _dual_ok(),
                        'trust_devices': {'count': td['n'] or 0, 'total_use': td['u'] or 0, 'ttl_days': TRUST_DAYS},
                        'webauthn': wa, 'bt_passports': {'count': bt['n'] or 0, 'total_verify': bt['v'] or 0},
                        'recent': recent,
                        'ua_mobile': _is_mobile_ua()})
    finally:
        conn.close()
