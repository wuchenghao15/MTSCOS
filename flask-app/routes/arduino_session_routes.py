"""arduino_session_routes — Arduino 设备热插拔自动行为规范 API

遵循规则: 系统操作规范.md §13 (v1.2.0) + v2.0 重写路由/三重永久化/AI介入
  - §13.1 设备插入自动跳转 (前端轮询 /api/arduino/events/poll 获取 insert 事件)
  - §13.2 临时用户登录弹窗 (前端根据 session 判断是否弹窗, 后端 /api/arduino/session/temp-login 验证)
  - §13.3 设备拔出自动退出 (前端轮询获取 remove 事件)
  - §13.4 未保存工作保存提示 (前端检测变更, POST /api/arduino/session/save)
  - §13.5 用户使用痕迹持久化 (POST /api/arduino/session/trace)
  - §13.6 自动载入继续编译 (GET /api/arduino/session/load)
  - §13.8 引擎事件队列 (GET /api/arduino/events/poll + POST /api/arduino/events/ack)
  - v2.0 T01a  scope 守卫：ide=SA双密钥 / setup=管理员类 / vault=任意登录用户
  - v2.0 FR-2/FR-3  重写路由 + 管理员IDE→SETUP分流
  - v2.0 FR-4  fail-closed 写接口设备存在性检查
  - v2.0 FR-5  用户专仓 commit 三重永久化
  - v2.0 FR-8  _ensure_device_present 阈值累计 → AI介入T1扫描派单

设计: 采用 SQLite 事件队列替代 WebSocket (与现有架构一致, 零额外依赖)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session

from ._governance_helpers import (
    _check_login, _current_safe_user, _fail, _get_db_path, _ok, _query, _query_one,
)

# 引擎路径 (用于调用 DAO 函数)
_ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engines')
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

import ai_arduino_detect_engine as _detect  # noqa: E402
from app.middlewares.system_container import system_container

arduino_bp = Blueprint('arduino_session', __name__)

_ADMIN_ROLES = {'super_admin', 'admin', 'hardware_admin'}
_AI_T1_FAIL_THRESHOLD = 30
_ai_fail_counter_lock = threading.Lock()
_ai_fail_counter: dict = {}  # key = bound_vid_pid or 'global' → count


def _iso_now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _uuid8() -> str:
    return uuid.uuid4().hex[:8]


def _uid_short() -> str:
    return _uuid8()


def _sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def _current_role_canonical() -> str:
    return (session.get('role_canonical') or '').strip() or 'guest'


def _current_username() -> str:
    return (session.get('username') or '').strip()


def _current_user_id():
    return session.get('user_id')


def _is_sa_username() -> bool:
    return _current_username().lower() == 'wuchenghao15'


def _is_admin_role() -> bool:
    return _current_role_canonical().lower() in _ADMIN_ROLES or _is_sa_username()


def _terminal_bind_dual_status(username: str, role_canonical: str):
    """与原函数一致：获取双密钥状态。失败返回 {both_authenticated:False, reason:[...]}"""
    extra = {
        'ip': request.remote_addr,
        'ua': request.headers.get('User-Agent', '')[:300],
        'session_id': session.sid if getattr(session, 'sid', None) else session.get('_session_id', ''),
    }
    try:
        from app.middlewares.vikey_enforcement_middleware import vikey_enforcement
        dual = vikey_enforcement.get_dual_hardware_status(
            username=username, role=role_canonical,
            ip=extra.get('ip'), ua=extra.get('ua'), session_id=extra.get('session_id'))
    except Exception as e:
        return {
            'both_authenticated': False,
            'reason': [f'双密钥检测异常: {e}'],
            'vikey': {'present': False, 'status': 'EXCEPTION'},
            'szu100': {'present': False, 'auth_status': 'EXCEPTION'},
        }
    if not dual.get('both_authenticated'):
        reason = []
        v = dual.get('vikey') or {}
        s = dual.get('szu100') or {}
        if not v.get('present'): reason.append('未检测到 VIKEY 加密狗')
        elif not v.get('sa_bound_ok'): reason.append('VIKEY 未绑定超级管理员')
        if not s.get('present'): reason.append('未检测到 SZU100 专用U盘')
        elif not s.get('is_authentic'): reason.append('SZU100 正版校验失败（疑似伪造改名U盘）')
        t = dual.get('terminal') or {}
        if t.get('required') and t.get('bound') is not True:
            reason.append('必须从插钥终端(服务器本机)访问')
        if not reason: reason.append('双密钥未同时通过认证')
        dual['reason'] = reason
    return dual


def _write_arduino_audit(severity: str, message: str, **kwargs):
    """轻量审计：写 detect_log（失败兜底）"""
    try:
        extra = {
            'ip': request.remote_addr,
            'ua': request.headers.get('User-Agent', '')[:300],
            'path': request.path,
            'method': request.method,
        }
        try:
            from app.middlewares.vikey_enforcement_middleware import VikeyEnforcementMiddleware as V
            V._log_automation_console(
                'arduino_sa_guard', message, severity=severity,
                extra=dict(extra, **kwargs))
        except Exception:
            _detect.ensure_detect_tables()
            import sqlite3 as _sl3
            DB = _get_db_path('app.db')
            conn = _sl3.connect(DB, timeout=10)
            c = conn.cursor()
            c.execute(
                "INSERT INTO mt_arduino_detect_log(scan_id, ports_scanned, devices_found, new_devices, removed_devices, details_json, scan_status, scanned_at) VALUES (?,?,?,?,?,?,?,?)",
                (f"ARD-AUD-{_uuid8()}", 0, 0, 0, 0,
                 json.dumps(dict(severity=severity, message=message, **kwargs), ensure_ascii=False),
                 severity.upper(), _iso_now()))
            conn.commit()
            conn.close()
    except Exception:
        pass


def _403_perm(msg: str, code: str = 'ARDUINO_PERMISSION_DENIED', **extra):
    body = {'success': False, 'error': msg, 'error_code': code, 'status_code': 403}
    body.update(extra)
    return jsonify(body), 403


def _423_locked(lock_id: str, msg: str = 'Arduino 设备未插入，操作已锁定'):
    body = {'success': False, 'device_status': 'removed',
            'lock_id': lock_id, 'error': msg, 'error_code': 'ARD_DEVICE_LOCKED', 'status_code': 423}
    return jsonify(body), 423


def _409_conflict(msg: str = 'session 绑定的 Arduino 设备与当前插入设备不匹配'):
    body = {'success': False, 'device_status': 'vid_pid_mismatch',
            'error': msg, 'error_code': 'ARD_DEVICE_CONFLICT', 'status_code': 409}
    return jsonify(body), 409


# =================================================================
# T01a 扩展守卫：scope=ide|setup|vault
# =================================================================
def _check_arduino_api_permission(scope: str = 'ide'):
    """v2.0 三态权限守卫。
    scope='ide'   → 仅 username==wuchenghao15 + 双密钥（原行为不变）
    scope='setup' → role∈{super_admin,admin,hardware_admin}；SA 仍需双密钥
    scope='vault' → 任意已登录用户（行级 ACL 由 DAO 负责）
    返回 (allowed:bool, resp_or_None, role_canonical)
    """
    username = _current_username()
    role_canonical = _current_role_canonical()
    is_sa = _is_sa_username() or role_canonical.lower() == 'super_admin'
    login_ok, _, _ = _check_login()
    if not login_ok:
        return False, _403_perm('请先登录后访问 Arduino 相关功能', 'ARD_NOT_LOGGED_IN', terminal_status='need_login'), role_canonical

    if scope == 'vault':
        return True, None, role_canonical

    if scope == 'setup':
        if not (is_sa or role_canonical.lower() in {'admin', 'hardware_admin'}):
            return False, _403_perm('仅管理员可访问 Arduino 管理员设置页', 'ARD_SETUP_ADMIN_ONLY',
                                    terminal_status='denied_role'), role_canonical
        if is_sa:
            # SA 仍需双密钥
            dual = _terminal_bind_dual_status(username, role_canonical)
            if not dual.get('both_authenticated'):
                _write_arduino_audit('critical', 'ARD_SETUP_SA_DUAL_KEY 双密钥未通过',
                                     username=username, role=role_canonical,
                                     reason='; '.join(dual.get('reason', [])))
                return False, _403_perm('Arduino 管理员设置(SA)：需同时插入 VIKEY + SZU100：' +
                                        '; '.join(dual.get('reason', [])),
                                        'ARDUINO_SA_ONLY',
                                        reason='; '.join(dual.get('reason', [])),
                                        vikey_status=(dual.get('vikey') or {}).get('status'),
                                        szu100_status=(dual.get('szu100') or {}).get('auth_status'),
                                        terminal_status='dual_fail'), role_canonical
        # admin/hardware_admin 正常登录即可
        return True, None, role_canonical

    # scope == 'ide'（SA 双密钥，老行为）
    if not is_sa:
        _write_arduino_audit('warning', 'ARDUINO_IDE_SA_ONLY 非SA访问IDE被拒',
                             username=username, role=role_canonical)
        return False, _403_perm('仅超级管理员(wuchenghao15)可进入 Arduino IDE 编程界面',
                                'ARDUINO_IDE_SA_ONLY', terminal_status='not_sa_role'), role_canonical
    dual = _terminal_bind_dual_status(username, role_canonical)
    if not dual.get('both_authenticated'):
        _write_arduino_audit('critical', 'ARDUINO_IDE_SA_DUAL_KEY 双密钥未通过',
                             username=username, role=role_canonical,
                             reason='; '.join(dual.get('reason', [])))
        return False, _403_perm('Arduino IDE 需要同时插入 VIKEY 加密狗 和 SZU100 专用U盘：' +
                                '; '.join(dual.get('reason', [])),
                                'ARDUINO_SA_ONLY',
                                reason='; '.join(dual.get('reason', [])),
                                vikey_status=(dual.get('vikey') or {}).get('status'),
                                szu100_status=(dual.get('szu100') or {}).get('auth_status'),
                                terminal_status='dual_fail'), role_canonical
    _write_arduino_audit('info', 'ARDUINO_IDE_ACCESS 允许',
                         username=username, role=role_canonical)
    return True, None, role_canonical


# =================================================================
# T01b _ensure_device_present：写接口 fail-closed
# =================================================================
def _ensure_device_present(bound_vid_pid):
    """fail-closed 设备检查。
    返回 (ok:bool, resp_or_None, status_or_None)
    同时累计阈值 → 30 次失败触发 AI 介入 T1 扫描（FR-8）。
    """
    try:
        status = _detect.get_status()
    except Exception as e:
        return False, _423_locked(f'ARD-STATUS-{_uuid8()}', f'引擎异常: {e}'), None
    connected = int(status.get('connected') or 0)
    conn_pids = list(status.get('connected_vid_pids') or [])
    lock_id = f'ARD-LCK-{_uuid8()}'
    if connected <= 0:
        # 累计失败阈值 → AI介入 T1（T23b）
        _bump_ai_fail_counter(bound_vid_pid or '_global_', code=423)
        return False, _423_locked(lock_id), None
    if bound_vid_pid and bound_vid_pid not in conn_pids:
        # v2.0: vid_pid 为 0:0 时跳过冲突检查（USB 枚举未获取到 VID:PID 但设备已连接）
        if bound_vid_pid == '0:0' or bound_vid_pid == 'unknown:unknown':
            pass  # 容错：设备在线但 VID:PID 未获取，不拦截
        else:
            _bump_ai_fail_counter(bound_vid_pid, code=409)
            return False, _409_conflict(), None
    return True, None, status


def _bump_ai_fail_counter(key: str, code: int):
    """30 次失败异步派发 T1 扫描（FR-8 T23b）。"""
    with _ai_fail_counter_lock:
        _ai_fail_counter[key] = _ai_fail_counter.get(key, 0) + 1
        count = _ai_fail_counter[key]
        should_fire = count >= _AI_T1_FAIL_THRESHOLD
        if should_fire:
            _ai_fail_counter[key] = 0
    if should_fire:
        try:
            _ENG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engines')
            if _ENG_DIR not in sys.path:
                sys.path.insert(0, _ENG_DIR)
            import ai_arduino_intervention_engine as aie
            threading.Thread(target=aie.t1_scan_route_anomalies, kwargs={'reason': f'threshold@{code}'},
                             daemon=True).start()
        except Exception:
            # 模块可能尚未创建，降级忽略
            pass


_AI_T1_WRITE_INTERVAL_S = 300  # 成功写路径 5 分钟派一次 T1 + discard_ratio
_AI_T1_LAST_TS_LOCK = threading.Lock()
_AI_T1_LAST_TS = 0  # Unix 时间戳


def _trigger_ai_write_success_scan(pipeline: str = 'save_write'):
    """T23b: 成功写接口周期派发 AI T1 扫描（节流）。
    同一进程至少间隔 300 秒派发一次 t1 + t2 组合。"""
    global _AI_T1_LAST_TS
    import time as _time
    now = int(_time.time())
    should_fire = False
    with _AI_T1_LAST_TS_LOCK:
        if now - _AI_T1_LAST_TS >= _AI_T1_WRITE_INTERVAL_S:
            _AI_T1_LAST_TS = now
            should_fire = True
    if not should_fire:
        return

    def _runner():
        try:
            _ENG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engines')
            if _ENG_DIR not in sys.path:
                sys.path.insert(0, _ENG_DIR)
            import ai_arduino_intervention_engine as aie
            aie.t1_scan_route_anomalies(reason=f'success_write@{pipeline}')
            aie.t2_scan_discard_ratio()
        except Exception:
            pass

    try:
        threading.Thread(target=_runner, daemon=True).start()
    except Exception:
        pass


# =================================================================
# T03a / T03b  角色路由拦截：管理员访问 IDE → 302 /admin_app/arduino_admin_setup
# =================================================================
@arduino_bp.before_request
def _arduino_sa_only_guard():
    """路由级守卫 (v2.0)：
    公共轮询 / temp-login 放行；
    /admin_app/arduino_admin_setup 使用 scope=setup；
    /admin_app/arduino_ide 对管理员 302→SETUP；对普通用户 session.arduino_bound 验证；
    /api/arduino/vault/*   scope=vault；
    /api/arduino/admin/*   scope=setup；
    /api/arduino/* others  scope=ide 或 setup（根据具体路径判断）。"""
    path = (request.path or '')
    lpath = path.lower()

    is_route_ide_page = path.rstrip('/') == '/admin_app/arduino_ide'
    is_route_setup_page = path.rstrip('/') == '/admin_app/arduino_admin_setup'
    is_api_arduino = lpath.startswith('/api/arduino/') or lpath == '/api/arduino'

    # 非 Arduino 路由：不管
    if not (is_route_ide_page or is_route_setup_page or is_api_arduino):
        return None

    # 公共白名单
    if lpath.endswith('/session/temp-login') or lpath.endswith('/events/poll'):
        return None
    if lpath.endswith('/session/bind') or lpath.endswith('/session/redirect_target'):
        # bind/redirect 仅需登录
        ok, _, err = _check_login()
        if not ok:
            return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN', terminal_status='need_login')
        return None
    if lpath.endswith('/events/repoll_now'):
        ok, _, err = _check_login()
        if not ok:
            return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN', terminal_status='need_login')
        return None

    # ---------- 路由分派 scope ----------
    # vault API
    if '/api/arduino/vault/' in lpath or lpath.startswith('/api/arduino/vault'):
        allowed, resp, _r = _check_arduino_api_permission(scope='vault')
        if not allowed:
            return resp
        return None

    # admin API / 设置页
    if is_route_setup_page or '/api/arduino/admin/' in lpath:
        allowed, resp, _r = _check_arduino_api_permission(scope='setup')
        if not allowed:
            return resp
        return None

    # 页面：/admin_app/arduino_ide
    if is_route_ide_page:
        login_ok, _, _ = _check_login()
        if not login_ok:
            # 未登录：让页面渲染函数处理弹窗 (保持老行为)
            return None
        if _is_admin_role():
            # 管理员 → 302 设置页（Arduino 特殊路由规则失效）
            _write_route_override(
                user_role=_current_role_canonical(),
                source_path='/admin_app/arduino_ide',
                rewritten_path='/admin_app/arduino_admin_setup',
                rule_reason='admin_role_redirect_setup',
            )
            _write_arduino_audit('info', 'ARD_ROLE_REDIRECT_SETUP 管理员访问IDE被转派设置页',
                                 username=_current_username(), role=_current_role_canonical())
            return redirect('/admin_app/arduino_admin_setup', code=302)
        # 普通用户：必须 bound 且 当前设备存在
        if not session.get('arduino_bound'):
            return redirect('/index?from=arduino_needs_bound', code=302)
        try:
            status = _detect.get_status()
            if int(status.get('connected') or 0) <= 0:
                return redirect('/index?from=arduino_device_removed', code=302)
            bound_pid = session.get('bound_vid_pid')
            if bound_pid and bound_pid not in list(status.get('connected_vid_pids') or []):
                return redirect('/index?from=arduino_device_swap', code=302)
        except Exception as e:
            return redirect(f'/index?from=arduino_engine_err&err={e}', code=302)
        # 通过 → 由视图函数渲染（仍走 scope='ide' 守卫：在本 guard 已过滤 admin，剩下普通用户 ide 守卫默认 SA；
        # 因此对普通用户允许 ide 视图渲染而不调 _check_arduino_api_permission(ide)；
        # 普通用户仅可访问 IDE 页渲染，IDE 内的写入接口仍会按 scope=ide 守卫拦截？
        # — 实际上 IDE 内写入接口走 /api/arduino/session/save 等，它们默认 scope='ide' 即 SA only，
        # 但 v2 spec 明确：普通用户 bound+connected 可进入 IDE 并保存（AC-3）。
        # 所以写入接口不使用 scope='ide'，而改用 vault 等级的登录级守卫（在 API 函数内单独做设备检查）。
        return None

    # 其余 /api/arduino/* 公共写接口
    # 处理规则：按具体接口路径决定（在函数内使用 @requires_login 或显式调用守卫）。
    # 这里默认放行：后续路由函数自己加守卫（更细粒度）；
    # 但为保留老行为 /session/save /compile_upload 等等原 ide scope 接口，
    # 我们在 API 函数内显式加守卫。
    return None


def _write_route_override(user_role, source_path, rewritten_path, rule_reason,
                          ai_agent_id=None, eigenflux_panel_ref=None):
    try:
        _detect.ensure_detect_tables()
        import sqlite3 as _sl3
        conn = _sl3.connect(_get_db_path('app.db'), timeout=10)
        c = conn.cursor()
        c.execute(
            "INSERT INTO mt_arduino_route_override_log(override_id,user_role,source_path,rewritten_path,rule_reason,ai_agent_id,eigenflux_panel_ref,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"ARD-RO-{_uuid8()}", user_role, source_path, rewritten_path, rule_reason,
             ai_agent_id, eigenflux_panel_ref, _iso_now()))
        conn.commit()
        conn.close()
    except Exception:
        pass


# =================================================================
# 公共临时登录（保持原状，仅挪至新守卫后继续）
# =================================================================
@arduino_bp.route('/api/arduino/session/temp-login', methods=['POST'])
@system_container(require_auth='admin')
def arduino_temp_login():
    """Arduino 临时登录验证 (走 @system_container 等价校验, 禁止绕过)

    前端弹窗提交用户名+密码, 后端验证后写入 session, 并触发设备载入流程
    """
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return _fail('用户名和密码不能为空', 400)

    # 复用 server_real_db 的登录校验逻辑 (禁止绕过 @system_container)
    try:
        import server_real_db as _srd
        ok = _srd._verify_user_credentials(username, password)  # type: ignore[attr-defined]
    except AttributeError:
        # 回退: 直接查 users 表
        ok = _verify_user_fallback(username, password)
    except Exception:
        ok = _verify_user_fallback(username, password)

    if not ok:
        return _fail('用户名或密码错误', 401)

    # 写入 session (与主登录流程一致的最小字段集)
    user = _query_one("SELECT id, username, role_canonical FROM users WHERE username=?", (username,))
    if not user:
        return _fail('用户不存在', 404)
    session['logged_in'] = True
    session['username'] = user.get('username', username)
    session['user_id'] = user.get('id')
    session['role_canonical'] = user.get('role_canonical', 'user')
    session.permanent = False  # 临时会话, 浏览器关闭即失效

    return _ok({
        'username': user.get('username', username),
        'user_id': user.get('id'),
        'role': user.get('role_canonical', 'user'),
        'message': '临时登录成功, 即将进入 Arduino 编译系统',
    })


def _verify_user_fallback(username: str, password: str) -> bool:
    """回退密码校验 (pbkdf2/简单hash, 与 users 表一致)"""
    import hashlib
    import hmac
    row = _query_one("SELECT password_hash FROM users WHERE username=?", (username,))
    if not row:
        return False
    stored = row.get('password_hash', '') or ''
    # 兼容 pbkdf2_sha256$... 格式
    if stored.startswith('pbkdf2_sha256$'):
        parts = stored.split('$')
        if len(parts) == 4:
            _, salt, iterations, h = parts
            try:
                dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iterations))
                return hmac.compare_digest(dk.hex(), h)
            except Exception:
                return False
    # 兼容裸 sha256
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)


# ============================================================
# §13.1/§13.3 设备事件轮询 (前端每 2s 调用一次)
# v2.0: 轮询驱动扫描 — 每次轮询检查距上次扫描是否 ≥3s，是则触发一次 scan_devices
#       解决 daemon 未运行时设备插入无事件的问题
# ============================================================
_LAST_SCAN_TS = 0
_LAST_SCAN_LOCK = threading.Lock()
_POLL_SCAN_INTERVAL = 3  # 秒：轮询驱动扫描最小间隔


def _maybe_scan_on_poll():
    """轮询驱动扫描：距上次 scan_devices ≥3s 则触发一次。"""
    global _LAST_SCAN_TS
    import time as _t
    now = _t.time()
    should = False
    with _LAST_SCAN_LOCK:
        if now - _LAST_SCAN_TS >= _POLL_SCAN_INTERVAL:
            _LAST_SCAN_TS = now
            should = True
    if should:
        try:
            _detect.scan_devices()
        except Exception:
            pass


@arduino_bp.route('/api/arduino/events/poll')
@system_container(require_auth='guest')
def arduino_events_poll():
    """轮询设备插入/拔出事件 (替代 WebSocket, 零依赖)

    v2.0: 每次轮询自动触发 scan_devices (≥3s 间隔)，
          确保 daemon 未运行时设备插入仍能生成事件。

    返回: { events: [{ event_id, event_type, device_vid_pid, board_model, serial_port, payload }] }
    """
    _maybe_scan_on_poll()
    ok, u, err = _check_login()
    if not ok:
        # 未登录时也允许轮询 (用于触发登录弹窗), 但不返回敏感数据
        events = _detect.get_pending_events(limit=5)
        return jsonify({'success': True, 'logged_in': False, 'events': events})
    events = _detect.get_pending_events(limit=10)
    return _ok({'events': events, 'logged_in': True})


@arduino_bp.route('/api/arduino/events/ack', methods=['POST'])
@system_container(require_auth='guest')
def arduino_events_ack():
    """确认事件已处理 (前端跳转/退出完成后调用)"""
    data = request.get_json(silent=True) or {}
    event_id = (data.get('event_id') or '').strip()
    if not event_id:
        return _fail('event_id 不能为空', 400)
    ok = _detect.ack_event(event_id)
    return _ok({'acked': ok})


# ============================================================
# §13.6 载入用户上次会话
# ============================================================
@arduino_bp.route('/api/arduino/session/load')
@system_container(require_auth='super_admin')
def arduino_session_load():
    """载入用户上次 Arduino 编译会话 (按 device_vid_pid 精确匹配)"""
    ok, u, err = _check_login()
    if not ok:
        return _fail('未登录', 401)
    user_id = str(u.get('user_id') or u.get('username') or '')
    device_vid_pid = request.args.get('device_vid_pid', '').strip() or None
    sess = _detect.load_user_session(user_id, device_vid_pid)
    if not sess:
        return _ok({'session': None, 'message': '无历史会话, 开始新编译'})
    # 解析 JSON 字段
    try:
        sess['config'] = json.loads(sess.get('config_json') or '{}')
    except Exception:
        sess['config'] = {}
    try:
        sess['usage_trace'] = json.loads(sess.get('usage_trace_json') or '[]')
    except Exception:
        sess['usage_trace'] = []
    try:
        sess['edit_history'] = json.loads(sess.get('edit_history_json') or '[]')
    except Exception:
        sess['edit_history'] = []
    return _ok({'session': sess, 'message': '已恢复上次工作, 继续编译'})


# ============================================================
# §13.4/§13.5 保存用户会话 (手动保存 + 自动保存)
# ============================================================
@arduino_bp.route('/api/arduino/session/save', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_session_save():
    """保存用户 Arduino 编译会话 (代码/配置/痕迹/编辑历史)

    前端调用场景:
      - 用户点击保存按钮 (auto_saved=0)
      - 每60秒自动保存 (auto_saved=1)
      - 设备拔出提示保存 (auto_saved=0, confirm_reason=device_removed)

    v2.0 T08a: 挂 fail-closed 设备存在性检查（confirm_reason=device_removed 例外）。
    """
    ok, u, err = _check_login()
    if not ok:
        return _fail('未登录', 401)
    data = request.get_json(silent=True) or {}
    confirm_reason = data.get('confirm_reason') or ''
    if confirm_reason != 'device_removed':
        bound = session.get('bound_vid_pid') or (data.get('device_vid_pid') or '').strip()
        ok_d, resp_d, _s = _ensure_device_present(bound)
        if not ok_d:
            return resp_d
    user_id = str(u.get('user_id') or u.get('username') or '')
    username = u.get('username') or 'unknown'
    device_vid_pid = (data.get('device_vid_pid') or '').strip() or session.get('bound_vid_pid') or ''
    board_model = (data.get('board_model') or '').strip()
    code_content = data.get('code_content', '')
    code_language = data.get('code_language', 'cpp')
    config_json = data.get('config_json', '{}')
    usage_trace_json = data.get('usage_trace_json', '[]')
    edit_history_json = data.get('edit_history_json', '[]')
    auto_saved = int(data.get('auto_saved', 0))
    session_id = data.get('session_id')  # 可选, 有则更新

    if not device_vid_pid:
        return _fail('device_vid_pid 不能为空', 400)

    sid = _detect.save_user_session(
        user_id=user_id, username=username, device_vid_pid=device_vid_pid,
        board_model=board_model, code_content=code_content,
        code_language=code_language, config_json=config_json,
        usage_trace_json=usage_trace_json, edit_history_json=edit_history_json,
        auto_saved=auto_saved, session_id=session_id,
    )
    # T23b: 成功保存周期触发 AI T1 + T2 扫描
    _trigger_ai_write_success_scan(pipeline='session_save')
    return _ok({'session_id': sid, 'message': '保存成功'})


# ============================================================
# §13.5 追加使用痕迹记录
# ============================================================
@arduino_bp.route('/api/arduino/session/trace', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_session_trace():
    """追加使用痕迹记录 (编译/上传/调试/清除等操作序列)。
    v2.0 T08a: 挂 fail-closed 设备存在性检查。
    """
    ok, u, err = _check_login()
    if not ok:
        return _fail('未登录', 401)
    # T08a: fail-closed 写接口必须设备在线
    ok_d, resp_d, _s = _ensure_device_present(session.get('bound_vid_pid'))
    if not ok_d:
        return resp_d
    data = request.get_json(silent=True) or {}
    session_id = (data.get('session_id') or '').strip()
    if not session_id:
        return _fail('session_id 不能为空', 400)
    trace_entry = {
        'action': data.get('action', 'unknown'),
        'timestamp': datetime.now().isoformat(),
        'details': data.get('details', {}),
    }
    success = _detect.append_usage_trace(session_id, trace_entry)
    return _ok({'appended': success})


# ============================================================
# §13.3 结束会话 (设备拔出时前端调用)
# ============================================================
@arduino_bp.route('/api/arduino/session/end', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_session_end():
    """结束 Arduino 编译会话 (设备拔出时调用)。
    v2.0 T08a: 显式标明 device_removed 可以跳过 fail-closed。"""
    ok, u, err = _check_login()
    if not ok:
        return _fail('未登录', 401)
    data = request.get_json(silent=True) or {}
    confirm_reason = data.get('confirm_reason') or ''
    # T08a: 非 device_removed 结束必须设备在线
    if confirm_reason != 'device_removed':
        ok_d, resp_d, _s = _ensure_device_present(session.get('bound_vid_pid'))
        if not ok_d:
            return resp_d
    session_id = (data.get('session_id') or '').strip()
    if not session_id:
        return _fail('session_id 不能为空', 400)
    success = _detect.end_user_session(session_id)
    # 清理绑定态
    if confirm_reason == 'device_removed':
        session['arduino_bound'] = False
    return _ok({'ended': success})


# ============================================================
# §13.1 Arduino IDE 页面 (登录可访问, 权限遵循 用户权限.md)
# ============================================================
@arduino_bp.route('/admin_app/arduino_ide')
@system_container(require_auth='super_admin')
def arduino_ide_page():
    """Arduino IDE 编译页面

    权限规则 (用户权限.md):
      - 管理页面 (/admin_app/arduino_ide 管理) 仅 wuchenghao15
      - 普通用户: 必须 session.arduino_bound=True 且设备在线（guard 已校验）
      - 管理员: 已在 guard 302 → arduino_admin_setup
    """
    ok, u, err = _check_login()
    if not ok:
        return render_template(
            'admin_app/arduino_ide.html',
            needs_login=True,
            user=None, page_type='fullscreen',
        )

    status = _detect.get_status()
    connected_devices = status.get('devices', [])

    return render_template(
        'admin_app/arduino_ide.html',
        needs_login=False,
        user=u, page_type='fullscreen',
        connected_devices=connected_devices,
        bound_vid_pid=session.get('bound_vid_pid'),
        settings_dict=_detect.load_active_settings_dict(),
    )


# ============================================================
# T02a: 绑定 session → arduino_bound (T02a)
# ============================================================
@arduino_bp.route('/api/arduino/session/bind')
@system_container(require_auth='login')
def arduino_session_bind():
    """登录用户绑定当前设备到 session（用于前端插入检测后）"""
    ok, _, _ = _check_login()
    if not ok:
        return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN', terminal_status='need_login')
    try:
        status = _detect.get_status()
    except Exception as e:
        return jsonify({'success': False, 'bound': False, 'reason': f'引擎异常:{e}'}), 200
    connected = int(status.get('connected') or 0)
    if connected <= 0:
        return jsonify({'success': True, 'bound': False, 'reason': 'device not found'})
    pids = list(status.get('connected_vid_pids') or [])
    if not pids:
        # 从 devices 反推 vid:pid
        for d in (status.get('devices') or []):
            vid = d.get('vid')
            pid = d.get('pid')
            if vid and pid:
                pids.append(f"{vid}:{pid}")
    vid_pid = pids[0] if pids else 'unknown:unknown'
    session['arduino_bound'] = True
    session['bound_vid_pid'] = vid_pid
    session['bound_at'] = _iso_now()
    return jsonify({'success': True, 'bound': True,
                    'vid_pid': vid_pid, 'bound_at': session['bound_at'],
                    'connected_count': connected})


# ============================================================
# T02b: 重写路由目标查询 (前端和T14双保险)
# ============================================================
@arduino_bp.route('/api/arduino/session/redirect_target')
@system_container(require_auth='login')
def arduino_session_redirect_target():
    """根据 bound 状态 + 设备在线 + 角色 计算登录后重定向目标。"""
    ok, _, _ = _check_login()
    if not ok:
        return jsonify({'redirect': None, 'reason': 'not_logged_in'})
    if not session.get('arduino_bound'):
        return jsonify({'redirect': None})
    try:
        status = _detect.get_status()
    except Exception:
        return jsonify({'redirect': None, 'reason': 'engine_error'})
    if int(status.get('connected') or 0) <= 0:
        return jsonify({'redirect': None, 'reason': 'removed'})
    role = _current_role_canonical().lower()
    is_admin = _is_admin_role()
    target = '/admin_app/arduino_admin_setup' if is_admin else '/admin_app/arduino_ide'
    bound_vid_pid = session.get('bound_vid_pid')
    _write_route_override(
        user_role=role,
        source_path='/login_rewrite_check',
        rewritten_path=target,
        rule_reason='redirect_target_api',
    )
    return jsonify({
        'redirect': target,
        'bound_vid_pid': bound_vid_pid,
        'role': role,
        'is_admin': is_admin,
        'connected': int(status.get('connected') or 0),
    })


# ============================================================
# T03c: 管理员设置页渲染路由
# ============================================================
@arduino_bp.route('/admin_app/arduino_admin_setup')
@system_container(require_auth='super_admin')
def arduino_admin_setup_page():
    """Arduino 管理员录入设置页 (FORM page_type)。"""
    allowed, resp, _r = _check_arduino_api_permission(scope='setup')
    if not allowed:
        return resp
    settings_dict = _detect.load_active_settings_dict()
    quota_list = _detect.list_vault_usage_summary()
    quota_mb = float(settings_dict.get('vault_quota_mb') or 100)
    for q in quota_list:
        q['over_quota'] = float(q.get('total_mb') or 0) > quota_mb
    return render_template(
        'admin_app/arduino_admin_setup.html',
        page_type='form',
        settings_dict=settings_dict,
        quota_list=quota_list,
        quota_mb=quota_mb,
        is_super_admin=_is_sa_username(),
        role_chip='管理员录入模式' if not _is_sa_username() else '超级管理员录入模式',
    )


# ============================================================
# T04b / T04c: 设置页 CRUD API
# ============================================================
@arduino_bp.route('/api/arduino/admin/setup')
@system_container(require_auth='super_admin')
def arduino_admin_setup_get():
    allowed, resp, _r = _check_arduino_api_permission(scope='setup')
    if not allowed:
        return resp
    return jsonify({'success': True, 'settings': _detect.load_active_settings_dict()})


@arduino_bp.route('/api/arduino/admin/setup', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_admin_setup_post():
    allowed, resp, _r = _check_arduino_api_permission(scope='setup')
    if not allowed:
        return resp
    data = request.get_json(silent=True) or {}
    body = {k: v for k, v in data.items() if k != 'lock_id'}
    # 非 device_removed 必须设备在线
    confirm_reason = data.get('confirm_reason') or ''
    if confirm_reason != 'device_removed':
        ok_dev, resp_dev, _s = _ensure_device_present(session.get('bound_vid_pid'))
        if not ok_dev:
            return resp_dev

    changed_by = int(_current_user_id() or 0)
    ai_ref = data.get('ai_suggestion_ref')

    valid_keys = {
        'board_whitelist', 'toolchain_path', 'default_upload_port',
        'default_baud_rate', 'autosave_interval_sec',
        'require_device_for_save', 'vault_quota_mb',
        'variant_template_defaults', 'lock_behavior_on_remove',
        'admin_setup_note',
    }

    saved_keys = []
    latest_version = None
    for key in valid_keys:
        if key in body:
            val = body[key]
            val_json = json.dumps(val, ensure_ascii=False)
            latest_version = _detect.save_admin_setting(
                key, val_json, changed_by, ai_suggestion_ref=ai_ref)
            saved_keys.append(key)
    # T23b: 管理员设置写入周期触发 AI T1 + T2 扫描
    _trigger_ai_write_success_scan(pipeline='admin_setup')
    return jsonify({'success': True, 'saved_keys': saved_keys,
                    'latest_version': latest_version,
                    'message': f'已保存 {len(saved_keys)} 项设置'})


# ============================================================
# T08b: 立即重扫 + 锁定释放
# ============================================================
@arduino_bp.route('/api/arduino/events/repoll_now')
@system_container(require_auth='super_admin')
def arduino_events_repoll():
    ok, _, _ = _check_login()
    if not ok:
        return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN', terminal_status='need_login')
    try:
        _detect.scan_devices()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'status': _detect.get_status()})


@arduino_bp.route('/api/arduino/lock/register', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_lock_register():
    """前端锁定时创建 lock_id → 写 mt_arduino_lock_log (fail-closed 审计)。"""
    ok, u, _ = _check_login()
    if not ok:
        return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN')
    data = request.get_json(silent=True) or {}
    lock_id = (data.get('lock_id') or '').strip() or f'ARD-LCK-{_uuid8()}'
    lock_trigger = data.get('lock_trigger') or 'device_removed'
    lock_reason = data.get('lock_reason')
    uid = int(u.get('user_id') or 0)
    sid = data.get('session_id')
    okw = _detect.write_lock_log(lock_id, uid, sid, lock_trigger, lock_reason)
    return jsonify({'success': okw, 'lock_id': lock_id})


@arduino_bp.route('/api/arduino/lock/release', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_lock_release():
    ok, _, _ = _check_login()
    if not ok:
        return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN')
    data = request.get_json(silent=True) or {}
    lock_id = (data.get('lock_id') or '').strip()
    released_by = (data.get('released_by') or 'manual').strip()
    committed_vault_id = data.get('committed_vault_id')
    if not lock_id:
        return jsonify({'success': False, 'message': 'lock_id 缺失'}), 400
    ok = _detect.release_lock_log(lock_id, released_by, committed_vault_id)
    return jsonify({'success': ok, 'lock_id': lock_id, 'released_by': released_by})


# ============================================================
# T10d: 写入用户专仓 (三重永久化 commit API)
# ============================================================
@arduino_bp.route('/api/arduino/session/commit', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_session_commit():
    ok, u, _ = _check_login()
    if not ok:
        return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN')
    data = request.get_json(silent=True) or {}
    confirm_reason = data.get('confirm_reason') or 'manual'
    # 仅 device_removed 例外跳过设备检查
    if confirm_reason != 'device_removed':
        ok_d, resp_d, _s = _ensure_device_present(session.get('bound_vid_pid'))
        if not ok_d:
            return resp_d

    session_id = (data.get('session_id') or '').strip()
    code_content = data.get('code_content', '')
    va = data.get('variant_actions') or data.get('variant_actions_json')
    vp = data.get('variant_params') or data.get('variant_params_json')
    usage_trace = data.get('usage_trace') or []
    edit_history = data.get('edit_history') or []
    label = (data.get('label') or '拔出自动保存').strip()
    lock_id = data.get('lock_id')

    # 兼容 JSON 字符串
    try:
        variant_actions = json.loads(va) if isinstance(va, str) else (va or [])
    except Exception:
        variant_actions = []
    try:
        variant_params = json.loads(vp) if isinstance(vp, str) else (vp or {})
    except Exception:
        variant_params = {}

    uid = int(u.get('user_id') or 0)
    username = u.get('username') or 'unknown'

    # 1) 校验 session 存在且属于本人
    if session_id:
        sess = _detect.load_user_session(str(uid), None)
        if sess and str(sess.get('user_id') or '') != str(uid):
            return jsonify({'success': False, 'message': 'session 不属于当前用户'}), 403

    # 2) T10c: 更新 sessions 表的 variant/committed/vault_id
    vault_id_tmp = f"PENDING-{_uuid8()}"
    _detect.update_session_variants_and_commit(
        session_id,
        json.dumps(variant_actions, ensure_ascii=False),
        json.dumps(variant_params, ensure_ascii=False),
        confirm_reason,
        vault_id_tmp,  # 先占位，稍后再 UPDATE 回正确值
    )

    # 3) T10a: commit_to_user_vault
    vault_row = _detect.commit_to_user_vault(
        user_id=uid, session_id=session_id,
        code_content=code_content,
        variant_actions=variant_actions, variant_params=variant_params,
        usage_trace=usage_trace, edit_history=edit_history,
        label=label,
    )
    real_vault_id = vault_row['vault_id']

    # 修正 sessions 表的占位 vault_id → 真实 vault_id
    try:
        import sqlite3 as _s3
        conn = _s3.connect(_get_db_path('app.db'), timeout=10)
        cur = conn.cursor()
        cur.execute("""UPDATE mt_arduino_user_sessions SET vault_id=?
            WHERE vault_id=? AND session_id=?""", (real_vault_id, vault_id_tmp, session_id))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # 4) T10b: git tag
    tag, commit_sha = _detect._git_tag_vault(real_vault_id, username,
                                              vault_row.get('json_backup_path'))

    # 5) UPDATE vault git refs
    _detect.update_vault_git_refs(real_vault_id,
                                   tag if tag != 'FAILED_DEGRADED' else None,
                                   commit_sha,
                                   vault_row.get('json_backup_path'))

    # 6) 锁定日志关联 vault
    if lock_id:
        _detect.release_lock_log(lock_id, 'commit', real_vault_id)

    # T23b: 成功专仓 commit 周期触发 AI T1 + T2 扫描
    _trigger_ai_write_success_scan(pipeline='vault_commit')

    return jsonify({
        'success': True,
        'vault_id': real_vault_id,
        'snapshot_version': vault_row['snapshot_version'],
        'size_bytes': vault_row['size_bytes'],
        'committed_at': vault_row['committed_at'],
        'json_backup_path': vault_row.get('json_backup_path'),
        'git_tag': tag if tag != 'FAILED_DEGRADED' else None,
        'git_commit_sha': commit_sha,
        'git_status': 'ok' if tag != 'FAILED_DEGRADED' else 'degraded_no_git',
    })


# ============================================================
# T11b: 用户专仓查询 list + get (行级 ACL)
# ============================================================
@arduino_bp.route('/api/arduino/vault/list')
@system_container(require_auth='super_admin')
def arduino_vault_list():
    allowed, resp, _r = _check_arduino_api_permission(scope='vault')
    if not allowed:
        return resp
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    try:
        size = max(1, min(100, int(request.args.get('size', 10))))
    except Exception:
        size = 10
    as_user = request.args.get('as_user')
    is_sa = _is_admin_role() and _current_role_canonical().lower() == 'super_admin'
    as_user_i = None
    if as_user and is_sa:
        try:
            as_user_i = int(as_user)
        except Exception:
            as_user_i = None
    uid = int(_current_user_id() or 0)
    rows = _detect.list_user_vault(uid, is_sa=is_sa, as_user=as_user_i,
                                    page=page, size=size)
    return jsonify({'success': True, 'list': rows,
                    'page': page, 'size': size})


@arduino_bp.route('/api/arduino/vault/<vault_id>')
@system_container(require_auth='super_admin')
def arduino_vault_get(vault_id):
    allowed, resp, _r = _check_arduino_api_permission(scope='vault')
    if not allowed:
        return resp
    row = _detect.get_vault_by_id(vault_id)
    if not row:
        return jsonify({'success': False, 'message': 'vault 不存在'}), 404
    # 行级 ACL: 非 SA 必须 owner
    is_sa = _is_admin_role() and _current_role_canonical().lower() == 'super_admin'
    uid = int(_current_user_id() or 0)
    if not is_sa and int(row.get('bound_user_id') or 0) != uid:
        return _403_perm('无权访问此专仓', 'ARD_VAULT_NOT_OWNER')
    return jsonify({'success': True, 'vault': row})


# ============================================================
# T13a API: 专仓配额统计 (管理员)
# ============================================================
@arduino_bp.route('/api/arduino/admin/vault_usage')
@system_container(require_auth='super_admin')
def arduino_admin_vault_usage():
    allowed, resp, _r = _check_arduino_api_permission(scope='setup')
    if not allowed:
        return resp
    rows = _detect.list_vault_usage_summary()
    settings = _detect.load_active_settings_dict()
    quota_mb = float(settings.get('vault_quota_mb') or 100)
    for r in rows:
        r['quota_mb'] = quota_mb
        r['over_quota'] = float(r.get('total_mb') or 0) > quota_mb
    return jsonify({'success': True, 'quota_mb': quota_mb, 'usage': rows})


# ============================================================
# 编译上传 (stub, 设备检查 fail-closed)
# ============================================================
@arduino_bp.route('/api/arduino/session/compile_upload', methods=['POST'])
@system_container(require_auth='super_admin')
def arduino_session_compile_upload():
    ok, _, _ = _check_login()
    if not ok:
        return _403_perm('请先登录', 'ARD_NOT_LOGGED_IN')
    ok_d, resp_d, _s = _ensure_device_present(session.get('bound_vid_pid'))
    if not ok_d:
        return resp_d
    data = request.get_json(silent=True) or {}
    # 真实编译/上传由 daemon 处理，此处仅做审计占位
    vid_pid = session.get('bound_vid_pid')
    _write_arduino_audit('info', 'ARD_COMPILE_UPLOAD_REQ',
                         username=_current_username(),
                         vid_pid=vid_pid,
                         code_size=len(data.get('code_content', '') or ''))
    return jsonify({'success': True,
                    'message': '编译上传任务已加入本地队列（等待 Arduino CLI daemon 实现）',
                    'queued': True,
                    'status': 'pending_daemon'})
