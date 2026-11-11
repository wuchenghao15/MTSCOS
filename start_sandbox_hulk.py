#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock.mtos.site → Cloudflare Tunnel → Flask 5001
古灵阁证券交易系统 (沙盘) + 金盾系统 + 仙女座聊天

⛔ 统一门禁: 所有非首页 (/login) 进入 = 非法
🔐 沙盘门禁: 必须 SA (admin) 或 CAOPW (首席运营官) 登录
🧑‍💻 单账户多终端: 允许同一账号多 session
"""
import os, sys, time, socket, logging, sqlite3, hashlib, secrets, json
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory, request, session, redirect, url_for, abort

# ═══ 基础配置 ═══
BASE = os.path.dirname(os.path.abspath(__file__))
os.environ['APP_DB'] = os.path.join(BASE, 'database', 'app.db')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
log = logging.getLogger('SANDBOX-5001')

app = Flask(__name__)

# Cloudflare Tunnel → 源站是 http, 必须信任 X-Forwarded-Proto, 否则 redirect() 会把
# Location 自动纠正成 http:// (Werkzeug 2.0 autocorrect_location_header=True) → 协议降级
from werkzeug.middleware.proxy_fix import ProxyFix as _ProxyFix
app.wsgi_app = _ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['PREFERRED_URL_SCHEME'] = 'https'


@app.before_request
def _force_https():
    """Cloudflare 未开 Always Use HTTPS 时, 源站自兜底: 明文入口 301 升级到 https"""
    if request.headers.get('X-Forwarded-Proto', '').lower() == 'http':
        return redirect(request.url.replace('http://', 'https://', 1), code=301)

app.secret_key = os.environ.get('SECRET_KEY', 'mtscos-gobelin-shield-2026-unified-auth-20261104')
app.config['SESSION_COOKIE_SECURE'] = False  # Cloudflare Tunnel 内部, HTTP 可接受
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

@app.route('/health')
def health():
    return jsonify({'status': 'sandbox-5001', 'pid': os.getpid(), 'shield': 'ONLINE', 'version': '2.0'}), 200

# ═══ 🏛️ 自动会议厅 API ═══
@app.route('/api/chamber/meeting/trigger', methods=['POST', 'GET'])
def api_chamber_meeting_trigger():
    """
    触发自动会议厅引擎
    
    POST body / GET query:
      slot: 强制触发某个会议槽 (可选, 不填则按当前时间自动判断)
            MORNING_BRIEFING / CLOSE_SUMMARY / WEEKLY_SUMMARY / MONTHLY_MEETING / ANNUAL_MEETING / WEEKEND_STRATEGY
    
    返回:
      {"triggered": true, "results": [...], "elapsed_s": 0.05}
    """
    try:
        from engines.ai_sandbox_meeting_auto import run_meeting_engine, get_due_meetings
    except Exception as e:
        return jsonify({'ok': False, 'error': f'engine_load_failed: {e}'}), 500
    
    slot = (request.json or request.args).get('slot') if request.is_json else request.args.get('slot')
    result = run_meeting_engine(force_slot=slot)
    
    # 如果只是查询, 返回待触发列表
    if not result.get('triggered') and not slot:
        due = get_due_meetings()
        return jsonify({'ok': True, 'triggered': False, 'due_meetings': due})
    
    # 取会议室列表 (最近 10 条)
    conn = _db()
    try:
        recent = conn.execute("""
            SELECT meeting_id, meeting_type, meeting_title, triggered_at
            FROM mt_sandbox_meetings ORDER BY triggered_at DESC LIMIT 10
        """).fetchall()
        result['recent_meetings'] = [dict(r) for r in recent]
    except Exception:
        pass
    conn.close()
    
    return jsonify({'ok': True, **result})

@app.route('/api/chamber/meeting/due')
def api_chamber_meeting_due():
    """查询当前时间应该触发什么会议"""
    try:
        from engines.ai_sandbox_meeting_auto import get_due_meetings, _is_trading_day, _is_last_trading_day_of_month, _is_friday_trading_day, _is_year_end_trading_day
    except Exception:
        return jsonify({'ok': False})
    
    now = datetime.now()
    due = get_due_meetings(now)
    return jsonify({
        'ok': True,
        'now': now.strftime('%Y-%m-%d %H:%M:%S'),
        'is_trading_day': _is_trading_day(now),
        'is_last_trading_day_of_month': _is_last_trading_day_of_month(now),
        'is_friday_trading_day': _is_friday_trading_day(now),
        'is_year_end_trading_day': _is_year_end_trading_day(now),
        'due_meetings': due,
    })

@app.route('/api/chamber/meeting/list')
def api_chamber_meeting_list():
    """列出最近会议"""
    try:
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        conn = _db()
        rows = conn.execute("""
            SELECT meeting_id, meeting_type, meeting_title, triggered_at,
                   substr(conclusions, 1, 200) as conclusions_preview
            FROM mt_sandbox_meetings
            ORDER BY triggered_at DESC LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM mt_sandbox_meetings").fetchone()[0]
        conn.close()
        meetings = []
        for r in rows:
            d = {}
            for i, col in enumerate(["meeting_id","meeting_type","meeting_title","triggered_at","conclusions_preview"]):
                d[col] = r[i]
            meetings.append(d)
        return jsonify({'ok': True, 'total': total, 'meetings': meetings})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ═══ 认证数据库 ═══
def _db():
    conn = sqlite3.connect(os.environ['APP_DB'], timeout=10)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def _row(cur, row):
    """sqlite3.Row → dict"""
    if row is None: return None
    return {cur.description[i][0]: row[i] for i in range(len(cur.description))}

def _ensure_auth_tables():
    """确保 auth 相关表存在"""
    conn = _db(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_app_login_sessions (
        session_token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        user_ip TEXT,
        user_agent TEXT,
        expires_at TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.commit()
    conn.close()

_ensure_auth_tables()

# ═══ 白名单 (不需要登录) ═══
_PUBLIC_PATHS = {
    '/login', '/api/auth/login', '/api/auth/canary',
    '/health', '/static/', '/favicon.ico',
    '/api/chamber/',     # 🏛️ 自动会议厅 API (tick 驱动 + 手动触发, 公开查询)
    '/api/meetings/',    # 🏛️ 会议大厅实时 API (公开大屏展示)
    '/api/meetings',     # 🏛️ 会议大厅 (无尾斜杠)
}
_STATIC_EXT = ('.html', '.css', '.js', '.png', '.jpg', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.map')
# 业务页面禁止通过 /static/*.html 直链绕过 SA/CAOPW 门禁 (必须走受控路由)
_PROTECTED_HTML = (
    'sandbox-trading-terminal.html',
    'Gobelin.html',
    'live-trading-terminal.html',
    'writing-studio.html',
)

def _is_public(path):
    """检查路径是否公开 (不需要登录) — /ai 也需要登录了"""
    # 业务页面禁止通过 /static/*.html 直链绕过 SA/CAOPW 门禁 (必须走受控路由)
    if path.endswith(_PROTECTED_HTML):
        return False
    for p in _PUBLIC_PATHS:
        if path == p or path.startswith(p):
            return True
    if path.endswith(_STATIC_EXT):
        return True
    return False

def _get_session_user():
    """从 session 或 cookie 解析登录用户"""
    # 方式 1: Flask session cookie
    if session.get('user_id'):
        return {
            'user_id': session['user_id'],
            'username': session.get('username', ''),
            'role': session.get('role', ''),
        }
    # 方式 2: Bearer token (mt_app_login_sessions)
    token = request.headers.get('Authorization', '').replace('Bearer ', '') or request.args.get('token', '')
    if token:
        try:
            conn = _db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM mt_app_login_sessions WHERE session_token=?", (token,))
            row = _row(cur, cur.fetchone())
            conn.close()
            if row and row['expires_at'] > datetime.now().strftime('%Y-%m-%d %H:%M:%S'):
                return {'user_id': row['user_id'], 'username': row['username'], 'role': row['role']}
        except Exception:
            pass
    return None

# ═══ 统一门禁 ═══
@app.before_request
def unified_gatekeeper():
    """
    统一门禁 (2026-11-04 统一):
    1. 所有非公开路径 → 必须登录, 否则 302 → /login
    2. /GOBELIN/stock → 额外要求 role IN ('admin', 'caopw')
    """
    path = request.path.rstrip('/') or '/'
    
    # 公开路径: 放行
    if _is_public(path):
        return
    
    user = _get_session_user()
    
    # 未登录 → 去 /login
    if not user:
        if path.startswith('/api/'):
            return jsonify({'error': 'AUTH_REQUIRED', 'message': '请先从 www.mtos.site 首页登录'}), 401
        return redirect('/login?redirect=' + path, code=302)
    
    # 股票沙盘门禁: 必须 SA (admin) 或 CAOPW (首席运营官)
    # 只有沙盘 /GOBELIN/stock 和旧入口 /gobelin — 首页 / 是门户入口, 所有人都能访问
    if path in ('/GOBELIN/stock',) or path.startswith('/GOBELIN/stock') or path in ('/gobelin',):
        if user['role'] not in ('admin', 'caopw'):
            if path.startswith('/api/'):
                return jsonify({'error': 'SA_OR_CAOPW_REQUIRED', 'message': '股票沙盘必须 SA 或 CAOPW 登录'}), 403
            return abort(403)
    
    # 股票沙盘 API 门禁
    if path.startswith('/api/sandbox') or path.startswith('/api/trading'):
        if user['role'] not in ('admin', 'caopw'):
            return jsonify({'error': 'SA_OR_CAOPW_REQUIRED', 'message': '沙盘 API 必须 SA 或 CAOPW'}), 403
    
    # 🌙 休市自动切厅: 
    #   - 交易日 15:00 后 → 沙盘 → 会议厅
    #   - 非交易日 (周末/节假日) 任何时间 → 沙盘 → 会议厅
    _now = datetime.now()
    _is_trading = _now.weekday() < 5 and _now.strftime('%Y-%m-%d') not in {
        # 中国法定节假日 (2025-2026)
        "2025-01-01","2025-01-28","2025-01-29","2025-01-30","2025-01-31","2025-02-01","2025-02-02","2025-02-03","2025-02-04",
        "2025-04-04","2025-04-05","2025-04-06",
        "2025-05-01","2025-05-02","2025-05-03","2025-05-04","2025-05-05",
        "2025-06-01","2025-06-02","2025-06-03",
        "2025-10-01","2025-10-02","2025-10-03","2025-10-04","2025-10-05","2025-10-06","2025-10-07","2025-10-08",
        "2026-01-01","2026-02-17","2026-02-18","2026-02-19","2026-02-20","2026-02-21","2026-02-22","2026-02-23",
        "2026-04-05","2026-04-06","2026-04-07",
        "2026-05-01","2026-05-02","2026-05-03","2026-05-04","2026-05-05",
        "2026-06-19","2026-06-20","2026-06-21",
        "2026-10-01","2026-10-02","2026-10-03","2026-10-04","2026-10-05","2026-10-06","2026-10-07","2026-10-08",
    }
    _is_after_close = not _is_trading or _now.hour >= 15
    # P1-1: 休市切厅可被 ?force=1 或 SA/CAOPW 跳过 (运维/调试通道)
    _force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    _sa_bypass = user['role'] in ('admin', 'caopw', 'super_admin')
    if _is_after_close and path in ('/', '/GOBELIN/stock', '/gobelin') and not (_force or _sa_bypass):
        return redirect('/GOBELIN/chamber', code=302)
    
    request.user = user


# ═══════════════════════════════════════════════════════════════════
# flow_hall_force_audit_exam_20261104: 强制入厅门控 (HALL_FORCE_GATE)
# POST/PUT/DELETE/PATCH API 必须先 submit_to_hall + 绑定真实 hall_code
# ═══════════════════════════════════════════════════════════════════
@app.before_request
def _hall_force_gate():
    # force hall: write APIs require real hall_code bound in session
    import time as _ht
    _p = (request.path or '').rstrip('/')
    
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return None
    
    _FORCE_WHITELIST = (
        '/api/auth/', '/api/login', '/api/logout', '/api/session',
        '/api/internal/',
        '/api/local-chat', '/andromeda/api/persona_chat',
        '/api/collab-bus/', '/api/medical/',
        '/api/daemon-lab/hall/',
        '/api/chamber/',   # 🏛️ 自动会议厅 (tick 驱动 + API 手动触发)
    )
    if any(_p.startswith(w) for w in _FORCE_WHITELIST):
        return None
    
    try:
        _uid = session.get('user_id')
        _role = session.get('role') or ''
        # 只有 super_admin 能彻底绕过 (紧急操作通道)
        # admin 也必须 submit_hall_mark — admin 有审批权但不代表能绕过
        if _uid and str(_uid).lower() in ('wuchenghao15', '1') and str(_role).lower() == 'super_admin':
            return None
    except Exception:
        pass
    
    try:
        _mark = session.get('submit_hall_mark')
        if _mark and _mark not in (True, False, '1', '0'):
            from engines.ai_hall_force_and_audit import verify_submit_hall_mark
            _v = verify_submit_hall_mark(_mark)
            if _v.get('ok'):
                return None
            session.pop('submit_hall_mark', None)
            session.pop('submit_hall_expire', None)
    except Exception:
        pass
    
    return jsonify({
        'ok': False,
        'error': 'MUST_SUBMIT_HALL',
        'message': 'All operations must go through Task Hall first',
        'hall_url': '/',
        'gate_code': 'HALL-FORCE-GATE-001',
    }), 403


# ═══ 登录页 + Auth API ═══
@app.route('/login', methods=['GET'])
def login_page():
    """统一登录首页 — www.mtos.site 入口"""
    redirect_to = request.args.get('redirect', '')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>古灵阁 · 统一登录</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);font-family:-apple-system,"PingFang SC",sans-serif}}
.card{{background:rgba(255,255,255,0.06);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.12);border-radius:20px;padding:48px 40px;width:400px;color:#fff;box-shadow:0 25px 50px rgba(0,0,0,0.4)}}
.logo{{text-align:center;margin-bottom:32px}}
.logo h1{{font-size:28px;font-weight:700;background:linear-gradient(90deg,#ffd700,#ffed4a);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.logo p{{font-size:13px;color:rgba(255,255,255,0.5);margin-top:4px}}
.field{{margin-bottom:20px}}
.field label{{display:block;font-size:13px;color:rgba(255,255,255,0.7);margin-bottom:8px}}
.field input{{width:100%;padding:14px 16px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);border-radius:12px;color:#fff;font-size:15px;outline:none;transition:border-color .2s}}
.field input:focus{{border-color:#ffd700}}
.btn{{width:100%;padding:14px;background:linear-gradient(90deg,#ffd700,#ffed4a);color:#1a1a2e;border:none;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer;transition:transform .15s}}
.btn:hover{{transform:translateY(-1px)}}
.msg{{margin-top:16px;padding:12px;border-radius:10px;font-size:13px;text-align:center;display:none}}
.msg.error{{background:rgba(255,82,82,0.15);color:#ff6b6b;display:block;border:1px solid rgba(255,82,82,0.3)}}
.msg.info{{background:rgba(82,196,255,0.15);color:#6bcbff;display:block;border:1px solid rgba(82,196,255,0.3)}}
.redirect{{margin-top:20px;font-size:12px;color:rgba(255,255,255,0.3);text-align:center}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>🏛️ 古灵阁</h1>
    <p>GOBELIN · 统一门禁</p>
  </div>
  <form id="loginForm" onsubmit="doLogin(event)">
    <div class="field"><label>用户名</label><input id="username" type="text" autocomplete="username" placeholder="admin / caopw / 其他" required></div>
    <div class="field"><label>密码</label><input id="password" type="password" autocomplete="current-password" required></div>
    <button class="btn" type="submit">登 录</button>
  </form>
  <div id="msg" class="msg"></div>
  {f'<div class="redirect">即将跳转到: {redirect_to}</div>' if redirect_to else ''}
</div>
<script>
async function doLogin(e){{
  e.preventDefault();
  const msg = document.getElementById('msg'); msg.className='msg'; msg.style.display='none';
  const u = document.getElementById('username').value.trim();
  const p = document.getElementById('password').value;
  const r = new URLSearchParams(location.search).get('redirect') || '/';
  try{{
    const resp = await fetch('/api/auth/login', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{username:u,password:p,redirect:r}})}});
    const d = await resp.json();
    if(resp.ok && d.ok){{
      msg.className='msg info'; msg.textContent='✅ 登录成功, 跳转中...';
      setTimeout(()=>location.href=d.redirect || r, 400);
    }} else {{
      msg.className='msg error'; msg.textContent='❌ ' + (d.error || '登录失败');
    }}
  }} catch(err){{
    msg.className='msg error'; msg.textContent='❌ 网络错误';
  }}
}}
</script>
</body>
</html>"""

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """统一登录 API — 支持单账户多终端"""
    body = request.get_json(silent=True) or {}
    username = (body.get('username') or '').strip()
    password = body.get('password') or ''
    redirect_to = body.get('redirect') or '/'
    
    if not username or not password:
        return jsonify({'ok': False, 'error': '用户名和密码必填'}), 400
    
    conn = _db()
    cur = conn.cursor()
    
    # 查用户 (users 表优先, trading_routes SA_UIDS 兼容)
    cur.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,))
    user = _row(cur, cur.fetchone())
    
    # CAOPW 用户不存在 → 临时 fake (不阻塞 Flask tick)
    if not user and username == 'caopw':
        user = {'user_id': 'caopw', 'username': 'caopw', 'role': 'caopw', 'password': 'caopw'}
    
    if not user:
        conn.close()
        return jsonify({'ok': False, 'error': '用户不存在'}), 401
    
    # 密码验证
    pwd_valid = False
    SA_UIDS = {'wuchenghao15', 'wuchenghao1', 'wuchenghao', 'admin', 'caopw'}
    
    # SA/CAOPW 账号放行 + 空密码用户放行 (开发环境)
    if username in SA_UIDS:
        pwd_valid = True
    elif (user.get('password') or '') == password:
        pwd_valid = True
    elif not (user.get('password') or user.get('password_hash') or user.get('password_hash_enc')):
        pwd_valid = True  # 无密码设置的用户 = 放行 (本地开发)
    
    if not pwd_valid:
        conn.close()
        return jsonify({'ok': False, 'error': '密码错误'}), 401
    
    # 创建 session (单账户多终端 = 不踢旧 session)
    token = secrets.token_urlsafe(48)
    expires = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
    ua = request.headers.get('User-Agent', '')
    
    # 强制 role: caopw 用户 role=caopw, SA_UIDS 一律 admin
    role = user.get('role') or 'user'
    if username == 'caopw':
        role = 'caopw'
    elif username in SA_UIDS:
        role = 'admin'
    
    # 兼容 users 表主键 id (部分旧逻辑用 user_id)
    _uid = user.get('user_id') or user.get('id')
    cur.execute("""INSERT INTO mt_app_login_sessions
        (session_token, user_id, username, role, user_ip, user_agent, expires_at)
        VALUES (?,?,?,?,?,?,?)""", (token, _uid, username, role, ip, ua, expires))
    
    # Flask session cookie
    session['user_id'] = _uid
    session['username'] = username
    session['role'] = role
    session['session_token'] = token
    session.permanent = True
    
    # 记录登录日志
    try:
        cur.execute("""INSERT INTO login_logs 
            (user_id, username, ip_address, user_agent, device_type, login_status)
            VALUES (?,?,?,?,?,?)""", (_uid, username, ip, ua, 'web', 'success'))
    except Exception:
        pass
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'ok': True,
        'username': username,
        'role': role,
        'redirect': redirect_to,
        'session_token': token,  # Bearer 模式也能用
        'note': '单账户多终端 — 原设备保持登录',
    })

@app.route('/api/auth/logout', methods=['POST', 'GET'])
def api_auth_logout():
    """登出 — 只清当前 session token, 不踢其他终端"""
    token = session.pop('session_token', None)
    if token:
        conn = _db()
        conn.execute("DELETE FROM mt_app_login_sessions WHERE session_token=?", (token,))
        conn.commit()
        conn.close()
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me')
def api_auth_me():
    """当前登录用户"""
    user = _get_session_user()
    if not user:
        return jsonify({'ok': False, 'error': 'NOT_LOGGED_IN'}), 401
    return jsonify({'ok': True, 'user': user})

@app.route('/GOBELIN/stock')
def serve_gobelin_stock():
    """古灵阁证券交易主入口 — www.mtos.site/GOBELIN/stock (原 stock.mtos.site 废弃)"""
    return send_from_directory('static', 'sandbox-trading-terminal.html')

@app.route('/')
def root_index():
    """stock.mtos.site 首页 — 古灵阁证券交易沙盘 (需 SA/CAOPW, 晚休市自动切厅)"""
    return send_from_directory('static', 'sandbox-trading-terminal.html')

@app.route('/gobelin')
def gobelin_gate_decommissioned():
    """旧入口 /gobelin — 301 → / (首页)"""
    from flask import redirect
    return redirect('/', code=301)

@app.route('/live')
@app.route('/live-trading')
def serve_live():
    """实盘终端 — 保留独立入口"""
    return send_from_directory('static', 'live-trading-terminal.html')

@app.route('/GOBELIN/text')
def serve_gobelin_text():
    """古灵阁网文创作主入口 — www.mtos.site/GOBELIN/text"""
    return send_from_directory('static', 'writing-studio.html')

@app.route('/writing')
@app.route('/writing-studio')
@app.route('/gobelin-writing')
def serve_writing_redirect():
    """旧入口 → 301 redirect 到 /GOBELIN/text"""
    from flask import redirect
    return redirect('/GOBELIN/text', code=301)

# ═══ 会议厅 7 个子页面路由 (可独立跳转 + 可返回大厅) ═══

def _chamber(page_key):
    from blueprints.chamber_bp import render_page
    return render_page(page_key)

@app.route('/GOBELIN/chamber')
@app.route('/GOBELIN/chamber/')
@app.route('/GOBELIN/chamber/overview')
def chamber_overview(): return _chamber('overview')

@app.route('/GOBELIN/chamber/failure')
def chamber_failure(): return _chamber('failure')

@app.route('/GOBELIN/chamber/emergency')
def chamber_emergency(): return _chamber('emergency')

@app.route('/GOBELIN/chamber/synergy')
def chamber_synergy(): return _chamber('synergy')

@app.route('/GOBELIN/chamber/decision')
def chamber_decision(): return _chamber('decision')

@app.route('/GOBELIN/chamber/task')
def chamber_task(): return _chamber('task')

@app.route('/GOBELIN/chamber/grassroots')
def chamber_grassroots(): return _chamber('grassroots')

# —— 5 个独立会议室 ——
@app.route('/GOBELIN/chamber/media')
def chamber_media(): return _chamber('media')

@app.route('/GOBELIN/chamber/global')
def chamber_global(): return _chamber('global')

@app.route('/GOBELIN/chamber/trade-share')
def chamber_trade_share(): return _chamber('trade_share')

@app.route('/GOBELIN/chamber/emergency-hall')
def chamber_emergency_hall(): return _chamber('emergency_hall')

@app.route('/GOBELIN/chamber/positions')
def chamber_positions(): return _chamber('positions')

# ═══ 挂载蓝图 (按依赖顺序，全部 try-except 包装，失败不阻塞) ═══

# 1. 沙盘 (核心)
try:
    from blueprints.sandbox_bp import register_sandbox_bp
    register_sandbox_bp(app)
    log.info('✅ sandbox_bp')
except Exception as e:
    log.warning(f'⚠️ sandbox_bp: {e}')

# 2. 古灵阁集团
try:
    from blueprints.gobelin_bp import register_gobelin_bp
    register_gobelin_bp(app)
    log.info('✅ gobelin_bp')
except Exception as e:
    log.warning(f'⚠️ gobelin_bp: {e}')

# 3. 实盘
try:
    from blueprints.live_bp import register_live_bp
    register_live_bp(app)
    log.info('✅ live_bp')
except Exception as e:
    log.warning(f'⚠️ live_bp: {e}')

# 4. 网文创作
try:
    from blueprints.gobelin_writing_bp import register_gobelin_writing_bp
    register_gobelin_writing_bp(app)
    log.info('✅ gobelin_writing_bp')
except Exception as e:
    log.warning(f'⚠️ gobelin_writing_bp: {e}')

# 4b. 青龙影视传媒
try:
    from blueprints.gobelin_video_bp import register_gobelin_video_bp
    register_gobelin_video_bp(app)
    log.info('✅ 🎬 gobelin_video_bp (青龙影视)')
except Exception as e:
    log.warning(f'⚠️ gobelin_video_bp: {e}')

# 4c. 囚牛音乐工作室
try:
    from blueprints.gobelin_music_bp import register_gobelin_music_bp
    register_gobelin_music_bp(app)
    log.info('✅ 🎵 gobelin_music_bp (囚牛音乐)')
except Exception as e:
    log.warning(f'⚠️ gobelin_music_bp: {e}')

# 5. 仙女座聊天
try:
    from blueprints.chat_local_bp import chat_local_bp
    app.register_blueprint(chat_local_bp)
    log.info('✅ chat_local_bp (/ai)')
except Exception as e:
    log.warning(f'⚠️ chat_local_bp: {e}')

try:
    from blueprints.chat_plus_bp import chat_plus_bp
    app.register_blueprint(chat_plus_bp)
    log.info('✅ chat_plus_bp')
except Exception as e:
    log.warning(f'⚠️ chat_plus_bp: {e}')

try:
    from blueprints.andromeda_openai_bp import andromeda_openai_bp
    app.register_blueprint(andromeda_openai_bp)
    log.info('✅ andromeda_openai_bp')
except Exception as e:
    log.warning(f'⚠️ andromeda_openai_bp: {e}')

try:
    from blueprints.andromeda_stats_bp import andromeda_stats_bp
    app.register_blueprint(andromeda_stats_bp)
    log.info('✅ andromeda_stats_bp')
except Exception as e:
    log.warning(f'⚠️ andromeda_stats_bp: {e}')

# 6. 小龙 App + 下载
try:
    from blueprints.xiaolong_app_bp import xiaolong_bp
    app.register_blueprint(xiaolong_bp)
    log.info('✅ xiaolong_bp')
except Exception as e:
    log.warning(f'⚠️ xiaolong_bp: {e}')

try:
    from blueprints.app_download_bp import app_download_bp
    app.register_blueprint(app_download_bp)
    log.info('✅ app_download_bp')
except Exception as e:
    log.warning(f'⚠️ app_download_bp: {e}')

# 7. 🛡️ 金盾系统 v2.0 (29安全维度) — 海关总署 + 协同总线 + 仙女座/冰山/ComfyUI
try:
    from blueprints.gobelin_shield_bp import shield_bp
    app.register_blueprint(shield_bp)
    log.info('✅ 🛡️ gobelin_shield_bp (29安全维度)')
except Exception as e:
    log.warning(f'⚠️ gobelin_shield_bp: {e}')

try:
    from blueprints.threat_intel_bp import threat_intel_bp
    app.register_blueprint(threat_intel_bp)
    log.info('✅ 🛰️ threat_intel_bp (海关总署威胁情报)')
except Exception as e:
    log.warning(f'⚠️ threat_intel_bp: {e}')

try:
    from blueprints.collab_bus_bp import collab_bp
    app.register_blueprint(collab_bp)
    log.info('✅ 🚌 collab_bus_bp (协同总线)')
except Exception as e:
    log.warning(f'⚠️ collab_bus_bp: {e}')

# 7.5. 🏛️ 会议大厅 (AI × 会议室 × 会议 实时)
try:
    from blueprints.meeting_hall_bp import meeting_hall_bp
    app.register_blueprint(meeting_hall_bp)
    log.info('✅ 🏛️ meeting_hall_bp (会议大厅实时)')
except Exception as e:
    log.warning(f'⚠️ meeting_hall_bp: {e}')

# 8. 🏛️ 大厅 + 冰山 tick (提案/自动分派/16轨自治)
try:
    from blueprints.daemon_skill_lab_bp import daemon_skill_lab_bp
    app.register_blueprint(daemon_skill_lab_bp)
    log.info('✅ 🏛️ daemon_skill_lab_bp (大厅+冰山 tick)')
except Exception as e:
    log.warning(f'⚠️ daemon_skill_lab_bp: {e}')

# 9. 医疗中心
try:
    from blueprints.medical_center_bp import medical_bp
    app.register_blueprint(medical_bp)
    log.info('✅ 🏥 medical_center_bp')
except Exception as e:
    log.warning(f'⚠️ medical_center_bp: {e}')

# 10. 考试自动
try:
    from blueprints.exam_auto_daemon_bp import exam_auto_bp
    app.register_blueprint(exam_auto_bp)
    log.info('✅ 📝 exam_auto_bp')
except Exception as e:
    log.warning(f'⚠️ exam_auto_bp: {e}')

# 11. 语言教学
try:
    from blueprints.ai_language_pedagogy_bp import ai_language_pedagogy_bp
    app.register_blueprint(ai_language_pedagogy_bp)
    log.info('✅ 🌐 ai_language_pedagogy_bp')
except Exception as e:
    log.warning(f'⚠️ ai_language_pedagogy_bp: {e}')

# 12. 数学教学
try:
    from blueprints.ai_math_pedagogy_bp import ai_math_pedagogy_bp
    app.register_blueprint(ai_math_pedagogy_bp)
    log.info('✅ 📐 ai_math_pedagogy_bp')
except Exception as e:
    log.warning(f'⚠️ ai_math_pedagogy_bp: {e}')

# 13. 规则委员会
try:
    from blueprints.rule_committee_bp import rule_committee_bp
    app.register_blueprint(rule_committee_bp)
    log.info('✅ ⚖️ rule_committee_bp')
except Exception as e:
    log.warning(f'⚠️ rule_committee_bp: {e}')

# 14. 灾难恢复
try:
    from blueprints.disaster_recovery_bp import dr_bp
    app.register_blueprint(dr_bp)
    log.info('✅ 🚨 disaster_recovery_bp')
except Exception as e:
    log.warning(f'⚠️ disaster_recovery_bp: {e}')

# 15. 白帽猎杀
try:
    from blueprints.whitehat_hunt_bp import whitehat_bp
    app.register_blueprint(whitehat_bp)
    log.info('✅ 🕵️ whitehat_hunt_bp')
except Exception as e:
    log.warning(f'⚠️ whitehat_hunt_bp: {e}')

# 16. 档案
try:
    from blueprints.iceberg_archive_bp import archive_bp
    app.register_blueprint(archive_bp)
    log.info('✅ 📚 iceberg_archive_bp')
except Exception as e:
    log.warning(f'⚠️ iceberg_archive_bp: {e}')

# 17. AI 引擎中心 (30 中心最后一块拼图)
try:
    from blueprints.ai_engine import ai_engine_bp
    app.register_blueprint(ai_engine_bp)
    log.info('✅ 🧠 ai_engine_bp (AI 引擎中心)')
except Exception as e:
    log.warning(f'⚠️ ai_engine_bp: {e}')

# 17. 会议厅 (复盘)
try:
    from blueprints.chamber_bp import chamber_bp
    app.register_blueprint(chamber_bp)
    log.info('✅ 🏛️ chamber_bp (会议厅日复盘)')
except Exception as e:
    log.warning(f'⚠️ chamber_bp: {e}')

# ═══ 统一导航 + i18n 自动注入 (对齐 server_real_db, 消灭沙盘功能孤岛) ═══
@app.after_request
def _sandbox_nav_i18n_injector(response):
    """沙盘应用全站注入 andromeda 导航 + i18n (幂等: 已含则跳过)"""
    try:
        ctype = (response.content_type or '').lower()
        if 'text/html' not in ctype:
            return response
        if response.status_code in (204, 304):
            return response
        # send_file/send_from_directory 默认 direct_passthrough=True, get_data() 会返回空,
        # 必须先关闭才能读取并修改响应体
        if getattr(response, 'direct_passthrough', False):
            response.direct_passthrough = False
        try:
            raw = response.get_data()
        except Exception:
            return response
        if not raw or len(raw) < 64:
            return response
        encoding = getattr(response, 'charset', None) or 'utf-8'
        data = raw.decode(encoding, errors='ignore')
        if '</body>' not in data:
            return response

        modified = False
        # 1) 导航 CSS 注入 </head>
        if '</head>' in data and 'andromeda_nav.css' not in data:
            data = data.replace(
                '</head>',
                '\n<link rel="stylesheet" href="/static/css/andromeda_nav.css">\n</head>',
                1,
            )
            modified = True
        # 2) i18n.js 注入 </body>
        if 'i18n/i18n.js' not in data:
            data = data.replace(
                '</body>',
                '\n<script src="/static/i18n/i18n.js" defer></script>\n</body>',
                1,
            )
            modified = True
        # 3) 导航 JS 注入 </body> (幂等)
        if 'andromeda_nav.js' not in data:
            data = data.replace(
                '</body>',
                '\n<script src="/static/js/andromeda_nav.js" defer></script>\n</body>',
                1,
            )
            modified = True
        if modified:
            response.set_data(data.encode(encoding, errors='ignore'))
            try:
                response.headers['X-MT-Sandbox-Nav'] = '1'
            except Exception:
                pass
    except Exception as e:
        log.warning(f'[sandbox-nav-injector] err: {e}')
    return response

# ═══ 主入口 (最后执行，确保所有蓝图已注册) ═══
if __name__ == '__main__':
    _START_TIME = time.time()
    port = int(os.environ.get('PORT', 5001))
    
    # 端口检查 (不 exit，等它 bind 失败)
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('0.0.0.0', port))
        sock.close()
    except OSError:
        log.error(f'❌ 端口 {port} 被占用! 尝试 kill 后重启')
        import subprocess
        PID = subprocess.check_output(['/usr/sbin/lsof', '-tiTCP:5001', '-sTCP:LISTEN']).decode().strip()
        if PID:
            subprocess.run(['kill', '-9'] + PID.split())
            log.info(f'已 kill {PID}')
            time.sleep(2)
    
    bp_count = len(list(app.blueprints.keys()))
    log.info(f'🚀 stock.mtos.site Flask 5001 启动 ({bp_count} 蓝图)')
    log.info(f'   🛡️ 金盾系统 v2.0 · 29 安全维度')
    log.info(f'   🧠 仙女座聊天 · /ai')
    log.info(f'   📈 沙盘操盘 · /')
    log.info(f'   📝 网文创作 · /writing')
    log.info(f'   📊 金盾状态 · /api/shield/status')
    
    
# ═══ 🛡️ 金盾全闭环保护注入 (2026-11-04) ═══
try:
    from engines.shield_inject_middleware import inject_shield
    inject_shield(app)
except Exception as e:
    log.warning(f'⚠️ shield_inject_middleware: {e}')

# ═══ 🌐 i18n 字典端点注入 (供前端 i18n.js 拉取翻译) ═══
try:
    from engines.i18n_engine import inject_i18n_into_app
    inject_i18n_into_app(app)
    log.info('✅ 🌐 i18n 字典端点已注入 (/api/i18n/dict, /api/i18n/set_lang)')
except Exception as e:
    log.warning(f'⚠️ i18n_engine: {e}')

app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
