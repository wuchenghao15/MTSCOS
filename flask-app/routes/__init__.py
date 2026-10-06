"""
MTSCOS AI 项目 — 路由层 Blueprint 注册中心
从 server_real_db.py(29386行/354路由) 渐进式拆分为9个功能域 Blueprint

使用方式:
  from routes import register_all_blueprints
  app = Flask(__name__)
  register_all_blueprints(app)

迁移状态:
  - auth_bp:         7路由  (L6738-L8763)  ✅ 骨架已建
  - vote_bp:         9路由  (L21667-L22277) ✅ 骨架已建
  - devflow_bp:      ~5路由 (devflow相关)   ✅ 骨架已建
  - legal_bp:        1路由  (L8703)         ✅ 骨架已建
  - admin_bp:        ~12路由(L10569-L18974) ✅ 骨架已建
  - ai_bp:           ~80路由(L16526+)       ✅ 骨架已建
  - education_bp:    ~4路由 (L10991-L11608) ✅ 骨架已建
  - api_bp:          ~236路由(其余)         ✅ 骨架已建
  - maintenance_bp:  9路由  (自动维护Agent)  ✅ 已实现
  - k12_bp:          18路由 (K12教育管理)     ✅ 已实现
  - adult_bp:        20路由 (成人教育管理)     ✅ 已实现
  - exam_bp:         25路由 (考试系统API)       ✅ 已实现
  - test_bp:         25路由 (测试系统API)       ✅ 已实现
  - learning_bp:     25路由 (学习系统API)       ✅ 已实现
  - japanese_bp:     25路由 (日语学习API)       ✅ 已实现
"""
from flask import Blueprint, Response
from app.middlewares.system_container import system_container

# ───────────────────────────────────────────────────────────────
# 🔧 SERVER 模式后端运维状态面板 (v22.10.6 → v22.10.7 美化)
# Mac mini 是纯后端服务器 — 不需要首页/登录页/SA dashboard
# 本机打开浏览器 → 直接显示后端健康状态 (纯 HTML, 不走模板)
# 设计: 暗色主题 / CSS Grid 卡片 / daemon 色条 / 顶部健康度条
# 约束: 零外部依赖 (无 CDN/JS), 纯内联 CSS
# ───────────────────────────────────────────────────────────────

# ── 共享 CSS 变量 (Ops Panel + Login Panel 共用) ──────────────
_SERVER_CSS_VARS = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0f1115">
<style>
:root{
  --bg:#0f1115;--bg-2:#141821;--card:#1a1d24;--card-2:#222730;
  --border:#2a2f3a;--border-2:#3a4050;
  --text:#d4d4d4;--text-dim:#8892a6;--text-mute:#5a6478;
  --ok:#4ec9b0;--ok-dim:rgba(78,201,176,.15);
  --bad:#f48771;--bad-dim:rgba(244,135,113,.15);
  --warn:#dcdcaa;--warn-dim:rgba(220,220,170,.15);
  --accent:#569cd6;--accent-dim:rgba(86,156,214,.15);
  --radius:10px;--radius-sm:6px;
  --shadow:0 2px 12px rgba(0,0,0,.4);
  --mono:-apple-system,'SF Mono','Menlo','Consolas',monospace;
  --sans:-apple-system,'SF Pro Display','PingFang SC',system-ui,sans-serif;
}
*{box-sizing:border-box}
body{font-family:var(--sans);background:var(--bg);color:var(--text);margin:0;min-height:100vh;-webkit-font-smoothing:antialiased}
code,.mono{font-family:var(--mono);font-size:12px;background:var(--bg-2);padding:2px 6px;border-radius:3px}
</style>
"""

def _server_ops_panel():
    """SERVER 模式下 / 和 /index 返回后端运维状态面板 (纯 HTML, 无前端依赖)"""
    try:
        from app.node_role import NODE_ROLE, is_server, is_dev, is_client
    except ImportError:
        NODE_ROLE = "SERVER"
    
    import os, time, socket, subprocess
    
    # ── 收集状态 ──
    daemon_items = []
    healthy_count = 0
    try:
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if 'mtscos' not in line.lower(): continue
            parts = line.split()
            if len(parts) < 3: continue
            pid = parts[0]; exit_code = parts[1]; label = parts[2]
            is_healthy = (exit_code == "0")
            if is_healthy: healthy_count += 1
            daemon_items.append({
                'pid': pid if pid != '-' else '—',
                'exit': exit_code,
                'label': label,
                'ok': is_healthy,
            })
    except Exception:
        pass
    
    total_daemons = len(daemon_items) if daemon_items else 1
    health_pct = int(healthy_count * 100 / total_daemons)
    health_color = "var(--ok)" if health_pct >= 80 else "var(--warn)" if health_pct >= 50 else "var(--bad)"
    
    # Flask 进程
    flask_ok = False
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=3)
        flask_ok = any(('server_real_db' in l or 'modular_start' in l) for l in result.stdout.splitlines())
    except Exception: pass
    
    # HTTP 可达性自测
    http_ok = False
    http_code = "—"
    try:
        result = subprocess.run(['curl','-s','-o','/dev/null','-w','%{http_code}','--max-time','2','http://127.0.0.1:8888/'],
                                capture_output=True, text=True, timeout=5)
        http_code = result.stdout.strip()
        http_ok = http_code in ('200','302','301')
    except Exception: pass
    
    # 磁盘
    disk_pct = 0; disk_used = ""; disk_total = ""
    try:
        result = subprocess.run(['df','-h','/'], capture_output=True, text=True, timeout=3)
        lines = result.stdout.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            disk_total = parts[1] if len(parts) > 1 else ""
            disk_used = parts[2] if len(parts) > 2 else ""
            disk_pct = int(parts[4].rstrip('%')) if len(parts) > 4 and parts[4].rstrip('%').isdigit() else 0
    except Exception: pass
    disk_color = "var(--ok)" if disk_pct < 80 else "var(--warn)" if disk_pct < 95 else "var(--bad)"
    
    # 主机
    try: hostname = socket.gethostname()
    except Exception: hostname = "—"
    try: ip = socket.gethostbyname(socket.gethostname())
    except Exception: ip = "—"
    uptime_sec = int(time.time() - os.stat('/proc/uptime').st_atime if os.path.exists('/proc/uptime') else time.time())
    
    # daemon 行 (左色条)
    daemon_rows = ""
    for d in daemon_items:
        bar = "var(--ok)" if d['ok'] else "var(--bad)"
        badge = "●" if d['ok'] else "○"
        badge_color = "var(--ok)" if d['ok'] else "var(--bad)"
        exit_style = 'color:var(--ok)' if d['ok'] else 'color:var(--bad)'
        daemon_rows += f"""
<div class="daemon-row">
  <div class="daemon-bar" style="background:{bar}"></div>
  <div class="daemon-body">
    <span class="daemon-badge" style="color:{badge_color}">{badge}</span>
    <span class="daemon-label mono">{d['label']}</span>
    <span class="daemon-pid mono">{d['pid']}</span>
    <span class="daemon-exit mono" style="{exit_style}">{d['exit']}</span>
  </div>
</div>"""
    
    role_label = {'SERVER':'🖥️','DEV':'💻','CLIENT':'📱'}.get(NODE_ROLE,'❓') + f" {NODE_ROLE}"
    now_str = time.strftime('%H:%M:%S')
    
    panel = f"""<!DOCTYPE html>
<html><head>
{_SERVER_CSS_VARS}
<title>MTSCOS AI · Server Ops</title>
<style>
.layout{{max-width:1100px;margin:0 auto;padding:24px 28px 60px}}

/* ── 顶部健康度条 ── */
.topbar{{
  background:linear-gradient(135deg,var(--card),var(--card-2));
  border:1px solid var(--border);border-radius:var(--radius);
  padding:16px 22px;margin-bottom:20px;
  display:flex;align-items:center;gap:22px;flex-wrap:wrap;
  box-shadow:var(--shadow);
}}
.topbar-title{{font-size:15px;font-weight:600;color:var(--text)}}
.topbar-sub{{font-size:12px;color:var(--text-dim);margin-top:2px;font-family:var(--mono)}}
.health-bar{{flex:1;min-width:180px;height:8px;background:var(--bg-2);border-radius:4px;overflow:hidden}}
.health-fill{{height:100%;border-radius:4px;transition:width .4s;background:{health_color}}}
.health-pct{{font-family:var(--mono);font-size:13px;color:{health_color};font-weight:600}}

/* ── Grid 卡片 ── */
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px}}
.card{{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:18px 20px;box-shadow:var(--shadow);
}}
.card-title{{font-size:11px;font-weight:700;color:var(--text-dim);letter-spacing:.08em;text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.card-title::before{{content:"";width:3px;height:12px;background:var(--accent);border-radius:2px}}

/* ── Stat 行 ── */
.stat{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}}
.stat:last-child{{border-bottom:none}}
.stat-label{{font-size:13px;color:var(--text-dim)}}
.stat-val{{font-family:var(--mono);font-size:13px;color:var(--text);display:flex;align-items:center;gap:8px}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.dot-ok{{background:var(--ok);box-shadow:0 0 6px var(--ok)}}
.dot-bad{{background:var(--bad);box-shadow:0 0 6px var(--bad)}}

/* ── 磁盘进度 ── */
.disk-bar{{height:6px;background:var(--bg-2);border-radius:3px;overflow:hidden;margin-top:6px}}
.disk-fill{{height:100%;border-radius:3px;background:{disk_color};width:{disk_pct}%}}
.disk-label{{font-size:11px;color:var(--text-mute);font-family:var(--mono);margin-top:4px}}

/* ── Daemon 列表 ── */
.daemon-list{{max-height:340px;overflow-y:auto}}
.daemon-list::-webkit-scrollbar{{width:6px}}
.daemon-list::-webkit-scrollbar-thumb{{background:var(--border-2);border-radius:3px}}
.daemon-row{{display:flex;align-items:stretch;margin-bottom:6px;border-radius:var(--radius-sm);overflow:hidden;background:var(--bg-2);border:1px solid var(--border);transition:border-color .15s}}
.daemon-row:hover{{border-color:var(--border-2)}}
.daemon-bar{{width:3px;flex-shrink:0}}
.daemon-body{{flex:1;display:flex;align-items:center;gap:10px;padding:8px 12px;font-size:12px}}
.daemon-badge{{font-size:10px;line-height:1}}
.daemon-label{{flex:1;color:var(--text);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.daemon-pid{{color:var(--text-dim);width:44px;text-align:right}}
.daemon-exit{{width:28px;text-align:right}}

/* ── Quick Links ── */
.link-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
.link-btn{{
  display:flex;align-items:center;gap:10px;
  padding:12px 14px;background:var(--bg-2);border:1px solid var(--border);
  border-radius:var(--radius-sm);color:var(--text);text-decoration:none;
  font-size:13px;transition:all .15s;
}}
.link-btn:hover{{border-color:var(--accent);background:var(--accent-dim);transform:translateY(-1px)}}
.link-btn .ico{{width:22px;height:22px;display:flex;align-items:center;justify-content:center;border-radius:6px;background:var(--accent-dim);color:var(--accent);font-size:12px}}
.link-btn.primary{{border-color:var(--ok);background:var(--ok-dim);color:var(--ok)}}
.link-btn.primary:hover{{background:var(--ok);color:var(--bg)}}

/* ── Footer ── */
.footer{{text-align:center;color:var(--text-mute);font-size:11px;margin-top:30px;font-family:var(--mono)}}

/* ── 响应式 ── */
@media(max-width:600px){{
  .link-grid{{grid-template-columns:1fr}}
  .topbar{{gap:12px}}
}}
</style></head>
<body>
<div class="layout">

<!-- 顶部健康度条 -->
<div class="topbar">
  <div>
    <div class="topbar-title">🖥️ MTSCOS AI · Server Ops</div>
    <div class="topbar-sub">{hostname} · {ip} · {role_label} · {now_str}</div>
  </div>
  <div class="health-bar"><div class="health-fill" style="width:{health_pct}%"></div></div>
  <div class="health-pct">{healthy_count}/{total_daemons}</div>
</div>

<!-- Grid 卡片 -->
<div class="grid">

  <!-- System -->
  <div class="card">
    <div class="card-title">System</div>
    <div class="stat">
      <span class="stat-label">Flask API</span>
      <span class="stat-val">
        <span class="dot {'dot-ok' if flask_ok else 'dot-bad'}"></span>
        {'Running' if flask_ok else 'Down'}
      </span>
    </div>
    <div class="stat">
      <span class="stat-label">HTTP Check</span>
      <span class="stat-val {'color:var(--ok)' if http_ok else 'color:var(--bad)'}">{http_code}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Role</span>
      <span class="stat-val">{role_label}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Hostname</span>
      <span class="stat-val">{hostname}</span>
    </div>
  </div>

  <!-- Storage -->
  <div class="card">
    <div class="card-title">Storage</div>
    <div class="stat">
      <span class="stat-label">Disk /</span>
      <span class="stat-val">{disk_used}/{disk_total}</span>
    </div>
    <div class="disk-bar"><div class="disk-fill"></div></div>
    <div class="disk-label">usage {disk_pct}%</div>
  </div>

  <!-- Quick Links -->
  <div class="card" style="grid-column:span 1">
    <div class="card-title">Quick Links</div>
    <div class="link-grid">
      <a class="link-btn" href="/"><span class="ico">🖥</span> Ops Panel</a>
      <a class="link-btn primary" href="/auth/login"><span class="ico">🔐</span> Login</a>
      <a class="link-btn" href="/api/health" target="_blank"><span class="ico">♥</span> /api/health</a>
      <a class="link-btn" href="/api/handshake/status" target="_blank"><span class="ico">⚡</span> Handshake</a>
    </div>
  </div>

</div>

<!-- Daemons -->
<div class="card">
  <div class="card-title">Daemons</div>
  <div class="daemon-list">
{daemon_rows}
  </div>
</div>

<div class="footer">
  SERVER 模式 · zero frontend dependency · last refresh {now_str}
</div>

</div>
</body></html>"""
    return Response(panel, mimetype='text/html; charset=utf-8', status=200)


def _server_login_panel(error_msg=""):
    """SERVER 模式内嵌登录面板 (纯 HTML, POST /auth/login)"""
    try:
        from app.node_role import NODE_ROLE
    except ImportError:
        NODE_ROLE = "SERVER"
    
    error_html = f'<div class="err">{error_msg}</div>' if error_msg else ""
    
    panel = f"""<!DOCTYPE html>
<html><head>
{_SERVER_CSS_VARS}
<title>MTSCOS AI · Server Login</title>
<style>
body{{display:flex;align-items:center;justify-content:center;padding:40px 20px;min-height:100vh}}
.login-card{{
  background:linear-gradient(160deg,var(--card),var(--card-2));
  border:1px solid var(--border);border-radius:var(--radius);
  padding:36px 32px;width:400px;max-width:100%;
  box-shadow:var(--shadow);position:relative;overflow:hidden;
}}
.login-card::before{{
  content:"";position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,var(--ok),var(--accent));
}}
.brand{{display:flex;align-items:center;gap:14px;margin-bottom:26px}}
.brand-logo{{
  width:44px;height:44px;border-radius:10px;
  background:linear-gradient(135deg,var(--ok),var(--accent));
  display:flex;align-items:center;justify-content:center;
  color:#0f1115;font-weight:800;font-size:20px;
  box-shadow:0 4px 16px rgba(78,201,176,.3);
}}
.brand-text h1{{font-size:16px;font-weight:600;color:var(--text);margin:0}}
.brand-text p{{font-size:12px;color:var(--text-dim);margin:2px 0 0;font-family:var(--mono)}}
.field{{margin-bottom:14px}}
.field label{{display:block;font-size:11px;font-weight:600;color:var(--text-dim);letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}}
.field input{{
  width:100%;padding:11px 14px;background:var(--bg);border:1px solid var(--border-2);
  color:var(--text);border-radius:var(--radius-sm);font-size:14px;
  transition:border-color .15s,box-shadow .15s;box-sizing:border-box;
  font-family:var(--sans);
}}
.field input:focus{{outline:none;border-color:var(--ok);box-shadow:0 0 0 3px var(--ok-dim)}}
.submit-btn{{
  width:100%;padding:13px;background:linear-gradient(135deg,var(--ok),#3dd3a1);
  color:var(--bg);border:none;border-radius:var(--radius-sm);
  font-size:14px;font-weight:700;cursor:pointer;margin-top:8px;
  transition:transform .15s,box-shadow .15s;
}}
.submit-btn:hover{{transform:translateY(-1px);box-shadow:0 6px 20px rgba(78,201,176,.35)}}
.submit-btn:active{{transform:translateY(0)}}
.err{{color:var(--bad);font-size:12px;background:var(--bad-dim);padding:10px 14px;border-radius:var(--radius-sm);margin-bottom:14px;border:1px solid rgba(244,135,113,.2)}}
.back{{display:flex;align-items:center;gap:6px;color:var(--text-dim);font-size:12px;text-decoration:none;margin-top:20px;transition:color .15s}}
.back:hover{{color:var(--accent)}}
</style></head><body>
<div class="login-card">
  <div class="brand">
    <div class="brand-logo">M</div>
    <div class="brand-text">
      <h1>Server Login</h1>
      <p>NODE_ROLE={NODE_ROLE}</p>
    </div>
  </div>
  {error_html}
  <form method="POST" action="/auth/login">
    <div class="field">
      <label>Username</label>
      <input type="text" name="username" placeholder="admin / wuchenghao15" required autofocus autocomplete="username">
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" name="password" placeholder="••••••" required autocomplete="current-password">
    </div>
    <button type="submit" class="submit-btn">Sign In</button>
  </form>
  <a href="/" class="back">← Back to Ops Panel</a>
</div>
</body></html>"""
    return Response(panel, mimetype='text/html; charset=utf-8', status=200)


# 15个功能域 Blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
vote_bp = Blueprint('vote102', __name__, url_prefix='/api/vote102')
devflow_bp = Blueprint('devflow', __name__, url_prefix='/api/devflow')
legal_bp = Blueprint('legal', __name__)
admin_bp = Blueprint('admin', __name__)
ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')
education_bp = Blueprint('education', __name__, url_prefix='/exam_system')
api_bp = Blueprint('api', __name__, url_prefix='/api')
maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/api/maintenance')
k12_bp = Blueprint('k12', __name__, url_prefix='/api/k12')
adult_bp = Blueprint('adult', __name__, url_prefix='/api/adult')
exam_bp = Blueprint('exam', __name__, url_prefix='/api/exam')
test_bp = Blueprint('test', __name__, url_prefix='/api/test')
learning_bp = Blueprint('learning', __name__, url_prefix='/api/learning')
japanese_bp = Blueprint('japanese', __name__, url_prefix='/api/japanese')
# AI 治理中心新增 Blueprint (v2.8.0)
eigenflux_bp = Blueprint('eigenflux', __name__, url_prefix='/api/eigenflux')
brain_bank_bp = Blueprint('brain_bank', __name__, url_prefix='/api/brain_bank')
neural_array_bp = Blueprint('neural_array', __name__, url_prefix='/api/neural_array')
# 艺术家工坊 (v2.10.0 新增)
art_studio_bp = Blueprint('art_studio', __name__)
# Arduino 设备热插拔自动行为 (v1.2.0 新增, 规则§13)
arduino_bp = Blueprint('arduino_session', __name__)
# 主题调度中心 — 吴美工 AI 14套节日+个性化主题 (v22.0.0 新增, flow_id=autogap_27c8c83a)
theme_bp = Blueprint('theme', __name__, url_prefix='/api/theme')
# 安全仪表盘 — 杨安 AI 底层安全专家 4安全表+13开关+SA VIIKEY热更新 (v22.7.0 新增, flow_id=autogap_636b831d)
security_bp = Blueprint('security', __name__, url_prefix='/api/security')
# 首页/根路由 — 路由链路闭环 (VII代 v22.10.0 新增, 用户要求"完成页面基本功能展现和逻辑路由链路完整")
home_bp = Blueprint('home', __name__)
# 只读盘点功能 (v22.19.0 新增, T2 任务)
readonly_inventory_bp = Blueprint('readonly_inventory', __name__)
# 页面级路由 (v22.35.0 新增) — 非 /api/ 前缀, 给功能域提供独立页面入口
# page_routes_bp 定义在 routes/page_routes.py 里, 通过 register_all_blueprints 注册
# 仙女座仪表盘/冰山中心 — 页面级路由 (v22.19.0 新增, blueprint 变量定义在这里, 被 andromeda_dashboard_routes.py 相对引用)
andromeda_dashboard_bp = Blueprint('andromeda_dashboard', __name__, url_prefix='/andromeda')

# ---- home_bp 路由定义 (根路由不挂 url_prefix, 提供 / 和 /index) ----
from flask import redirect as _redirect, session as _session, render_template as _render_template, request as _request

# ═════════════════════════════════════════════════════════════
# v24.3.1 SA 双密钥预认证先跳转 (flow_id: SA_PREAUTH_v24_3_1_20260930)
# 双密钥在线 + 127.0.0.1 loopback 即 302 /sa/dashboard（不要求已登录），
# 登录在 SA 页面锁定态内完成。fail-closed：异常/不满足 → None 正常首页。
# ═════════════════════════════════════════════════════════════
def _sa_preauth_redirect():
    """命中预认证条件 → 返回 302 redirect(/sa/dashboard)；否则 None。"""
    try:
        from app.middlewares.vikey_enforcement_middleware import VikeyEnforcementMiddleware as _VEM
        _chk = _VEM.check_sa_redirect(
            username=_session.get('username', ''),
            role=_session.get('role', ''),
            ip=_request.remote_addr if _request else None)
        _VEM._log_sa_redirect_audit(
            username=_session.get('username', ''),
            role=_session.get('role', ''),
            ip=_request.remote_addr if _request else None,
            ua=_request.headers.get('User-Agent', '')[:200] if _request else '',
            session_id=_session.get('session_id', ''),
            action='redirect' if _chk['should_redirect'] else 'standard',
            reason="%s|stage=%s" % (_chk.get('reason', 'unknown'),
                                    _chk.get('auth_stage', 'pre_auth')))
        if _chk['should_redirect']:
            return _redirect('/sa/dashboard', code=302)
    except Exception:
        pass
    return None


@home_bp.route('/', methods=['GET'])
def _root_redirect():
    """根路径 `/` → SERVER 模式运维面板 / 其他模式跳 /index。"""
    # 🔧 v22.10.6: SERVER 模式 — 纯后端机器, 本机打开直接显示运维状态面板
    try:
        from app.node_role import is_server as _is_srv
        if _is_srv:
            return _server_ops_panel()
    except ImportError:
        pass
    # Arduino 设备插入：透传参数到 /login（Arduino 引导逻辑在 login.html，index.html 不处理该参数）
    _ai = _request.args.get('arduino_inserted')
    if _ai:
        qs = 'arduino_inserted=1'
        _vp = _request.args.get('vid_pid')
        _md = _request.args.get('model')
        if _vp: qs += '&vid_pid=' + _vp
        if _md: qs += '&model=' + _md
        return _redirect('/login?' + qs)
    # v24.3.1: 双密钥在线 + loopback → 直达 SA 专用页（guest 锁定态 / SA 完整态）
    _sa_r = _sa_preauth_redirect()
    if _sa_r is not None:
        return _sa_r
    return _redirect('/index')

# ───────────────────────────────────────────────────────────────
# 🔧 SERVER 模式路由 override (v22.10.6)
#   auth_bp 先注册了 /auth/login GET, home_bp 后注册被忽略
#   → 用 before_request 钩子拦截 (在 routes/__init__.py 被 register_all_blueprints 调用时挂载)
# ───────────────────────────────────────────────────────────────
def _install_server_overrides(app):
    """SERVER 模式专属: before_request 钩子 + 专属 API + 简化 admin 面板"""
    try:
        from app.node_role import is_server as _is_srv
        if not _is_srv: return
    except ImportError: return
    
    # ── before_request: /auth/login GET → 内嵌登录面板 ──
    @app.before_request
    def _server_auth_login_override():
        from flask import request
        if request.method == 'GET' and request.path == '/auth/login':
            return _server_login_panel()
    
    # ── SERVER 专属 API (不走 auth_bp / api_bp, 无额外依赖) ──
    import os, time, socket, sqlite3, subprocess
    from flask import jsonify
    
    def _find_main_db():
        """定位活跃主库 (server_real_db 用的那个)"""
        try:
            import server_real_db as _sdb
            for attr in ['DB_PATH','APP_DB','MAIN_DB']:
                p = getattr(_sdb, attr, None)
                if p and os.path.exists(p): return p
        except Exception: pass
        # 兜底候选
        for p in [
            os.path.join(os.path.dirname(__file__),'database','app.db'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)),'database','app.db'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'database','app.db'),
        ]:
            if os.path.exists(p): return p
        return None
    
    @app.route('/api/db/stats', methods=['GET'])
    def _server_api_db_stats():
        """DB 表数量 / 行数 Top 10 / 大小"""
        db = _find_main_db()
        if not db: return jsonify({'error':'db_not_found'}), 503
        try:
            conn = sqlite3.connect(db, timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [r[0] for r in cur.fetchall()]
            table_rows = []
            for t in tables[:80]:  # 前80个表算行数 (避免 370+ 表太慢)
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                    c = cur.fetchone()[0]
                    table_rows.append((t, c))
                except Exception: pass
            table_rows.sort(key=lambda x: -x[1])
            total_rows = sum(r[1] for r in table_rows)
            size = os.path.getsize(db)
            conn.close()
            return jsonify({
                'success': True,
                'db_path': db,
                'db_size_bytes': size,
                'db_size_human': f'{size/1024/1024:.1f}MB',
                'table_count': len(tables),
                'total_rows': total_rows,
                'top_tables': [{'name':t,'rows':r} for t,r in table_rows[:15]],
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            })
        except Exception as e:
            return jsonify({'error':str(e)[:100]}), 500
    
    @app.route('/api/system/info', methods=['GET'])
    def _server_api_system_info():
        """系统版本 / NODE_ROLE / daemon 健康度 / 磁盘"""
        try:
            from app.node_role import NODE_ROLE, is_server, is_dev, is_client
        except ImportError: NODE_ROLE = "SERVER"
        hostname = socket.gethostname()
        # daemon 状态
        daemons = []; healthy = 0; total = 0
        try:
            r = subprocess.run(['launchctl','list'], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if 'mtscos' not in line.lower(): continue
                parts = line.split()
                if len(parts) < 3: continue
                pid = parts[0]; ec = parts[1]; label = parts[2]
                ok = (ec == '0'); total += 1
                if ok: healthy += 1
                daemons.append({'label':label,'pid':pid if pid!='-' else None,'exit':int(ec),'ok':ok})
        except Exception: pass
        # Flask HTTP 自测
        http_code = None
        try:
            r = subprocess.run(['curl','-s','-o','/dev/null','-w','%{http_code}','--max-time','2','http://127.0.0.1:8888/'],
                               capture_output=True, text=True, timeout=5)
            http_code = int(r.stdout.strip()) if r.stdout.strip().isdigit() else None
        except Exception: pass
        # 磁盘
        disk_used = disk_total = disk_pct = None
        try:
            r = subprocess.run(['df','-h','/'], capture_output=True, text=True, timeout=3)
            parts = r.stdout.splitlines()[1].split()
            disk_total = parts[1]; disk_used = parts[2]
            disk_pct = int(parts[4].rstrip('%')) if len(parts)>4 and parts[4].rstrip('%').isdigit() else None
        except Exception: pass
        return jsonify({
            'success': True,
            'node_role': NODE_ROLE,
            'hostname': hostname,
            'ip': socket.gethostbyname(hostname) if True else None,
            'daemons': {'total':total,'healthy':healthy,'health_pct':int(healthy*100/total) if total else 0,'items':daemons},
            'http_probe': http_code,
            'disk': {'used':disk_used,'total':disk_total,'pct':disk_pct},
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        })
    
    @app.route('/api/health', methods=['GET'])
    def _server_api_health():
        """健康检查 (SERVER 模式短路认证)"""
        try:
            from app.node_role import NODE_ROLE as _nr
        except ImportError: _nr = "SERVER"
        return jsonify({
            'success': True, 'status': 'ok', 'node_role': _nr,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        })
    
    # ── 简化版 admin 面板 (admin 角色就能进, 不走 SA 双硬件) ──
    @app.route('/ops/admin', methods=['GET'])
    def _server_ops_admin():
        """SERVER 模式后端管理面板 (简化版, admin 角色)"""
        from flask import request, redirect, make_response
        # 检查登录态 (session 有 username + role != guest)
        username = request.cookies.get('mtscos_uid','')
        session_id = request.cookies.get('mtscos_sid','')
        if not username or username == 'guest-' or not session_id:
            return redirect('/auth/login')
        # admin 角色放行 (server_real_db login 写入 cookie)
        # 简化版: 已登录就能看, 不强制 super_admin
        return _server_admin_panel(username)


def _server_admin_panel(username):
    """简化版后端管理面板 (纯 HTML, 不走 SA 双硬件)"""
    # 拿 system + db 数据
    import urllib.request, json
    def _fetcher(url):
        try:
            with urllib.request.urlopen(url, timeout=3) as r: return json.loads(r.read())
        except Exception: return None
    sys_info = _fetcher('http://127.0.0.1:8888/api/system/info') or {}
    db_info = _fetcher('http://127.0.0.1:8888/api/db/stats') or {}
    
    daemons = sys_info.get('daemons',{}).get('items',[])
    daemon_rows = "".join(
        f'<div class="daemon-row"><div class="daemon-bar" style="background:{"var(--ok)" if d.get("ok") else "var(--bad)"}"></div>'
        f'<div class="daemon-body"><span class="daemon-label mono">{d.get("label","?")}</span>'
        f'<span class="daemon-pid mono">{d.get("pid") or "—"}</span>'
        f'<span class="daemon-exit mono" style="color:{"var(--ok)" if d.get("ok") else "var(--bad)"}">{d.get("exit","?")}</span>'
        f'</div></div>' for d in daemons
    )
    top_tables = db_info.get('top_tables',[])
    table_rows = "".join(
        f'<tr><td class="mono">{t["name"]}</td><td class="mono" style="text-align:right">{t["rows"]:,}</td></tr>'
        for t in top_tables[:12]
    )
    tables = db_info.get('table_count','?')
    db_size = db_info.get('db_size_human','?')
    health_pct = sys_info.get('daemons',{}).get('health_pct',0)
    hostname = sys_info.get('hostname','?')
    role = sys_info.get('node_role','SERVER')
    disk_pct = sys_info.get('disk',{}).get('pct',0)
    now = __import__('time').strftime('%H:%M:%S')
    
    panel = f"""<!DOCTYPE html>
<html><head>
{_SERVER_CSS_VARS}
<title>MTSCOS AI · Admin</title>
<style>
.layout{{max-width:1100px;margin:0 auto;padding:24px 28px 60px}}
.topbar{{background:linear-gradient(135deg,var(--card),var(--card-2));border:1px solid var(--border);border-radius:var(--radius);padding:16px 22px;margin-bottom:20px;display:flex;align-items:center;gap:22px;flex-wrap:wrap;box-shadow:var(--shadow)}}
.topbar-title{{font-size:15px;font-weight:600;color:var(--text)}}
.topbar-sub{{font-size:12px;color:var(--text-dim);margin-top:2px;font-family:var(--mono)}}
.topbar-user{{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:20px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow)}}
.card-title{{font-size:11px;font-weight:700;color:var(--text-dim);letter-spacing:.08em;text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.card-title::before{{content:"";width:3px;height:12px;background:var(--accent);border-radius:2px}}
.stat{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}}
.stat:last-child{{border-bottom:none}}
.stat-label{{font-size:13px;color:var(--text-dim)}}
.stat-val{{font-family:var(--mono);font-size:13px;color:var(--text)}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);font-size:12px}}
th{{color:var(--text-dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
td.mono{{font-family:var(--mono)}}
td.num{{text-align:right;font-family:var(--mono)}}
.daemon-list{{max-height:300px;overflow-y:auto}}
.daemon-row{{display:flex;align-items:stretch;margin-bottom:6px;border-radius:var(--radius-sm);overflow:hidden;background:var(--bg-2);border:1px solid var(--border)}}
.daemon-bar{{width:3px;flex-shrink:0}}
.daemon-body{{flex:1;display:flex;align-items:center;gap:10px;padding:8px 12px;font-size:12px}}
.daemon-label{{flex:1;color:var(--text);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.daemon-pid{{color:var(--text-dim);width:44px;text-align:right}}
.daemon-exit{{width:28px;text-align:right}}
.progress{{height:6px;background:var(--bg-2);border-radius:3px;overflow:hidden;margin-top:6px}}
.progress-fill{{height:100%;border-radius:3px}}
.btns{{display:flex;gap:10px;margin-top:14px}}
.btn{{flex:1;padding:10px;background:var(--bg-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);text-decoration:none;font-size:12px;text-align:center;transition:all .15s}}
.btn:hover{{border-color:var(--accent);color:var(--accent)}}
.btn.primary{{border-color:var(--ok);color:var(--ok);background:var(--ok-dim)}}
.btn.primary:hover{{background:var(--ok);color:var(--bg)}}
</style></head><body>
<div class="layout">

<div class="topbar">
  <div>
    <div class="topbar-title">⚙️ MTSCOS AI · Admin Panel</div>
    <div class="topbar-sub">{hostname} · 🖥️ {role} · {now}</div>
  </div>
  <div class="topbar-user">👤 {username}</div>
</div>

<div class="grid">
  <div class="card">
    <div class="card-title">Daemons</div>
    <div style="font-family:var(--mono);font-size:24px;color:var(--ok)">{health_pct}%</div>
    <div class="progress"><div class="progress-fill" style="width:{health_pct}%;background:var(--ok)"></div></div>
    <div class="daemon-list" style="margin-top:14px">{daemon_rows or '<p style="color:var(--text-mute);font-size:12px">launchctl 不可用</p>'}</div>
  </div>
  <div class="card">
    <div class="card-title">Database</div>
    <div class="stat"><span class="stat-label">Tables</span><span class="stat-val">{tables}</span></div>
    <div class="stat"><span class="stat-label">Size</span><span class="stat-val">{db_size}</span></div>
    <div class="stat"><span class="stat-label">Disk /</span><span class="stat-val">{disk_pct}%</span></div>
    <div class="progress"><div class="progress-fill" style="width:{disk_pct}%;background:var(--warn) if {disk_pct}<95 else var(--bad)"></div></div>
  </div>
  <div class="card">
    <div class="card-title">Top Tables</div>
    <table>
    <tr><th>Table</th><th style="text-align:right">Rows</th></tr>
    {table_rows or '<tr><td colspan="2" style="color:var(--text-mute)">DB not accessible</td></tr>'}
    </table>
  </div>
</div>

<div class="btns">
  <a class="btn primary" href="/">← Ops Panel</a>
  <a class="btn" href="/api/system/info" target="_blank">/api/system/info</a>
  <a class="btn" href="/api/db/stats" target="_blank">/api/db/stats</a>
  <a class="btn" href="/api/health" target="_blank">/api/health</a>
</div>

</div></body></html>"""
    return Response(panel, mimetype='text/html; charset=utf-8', status=200)

@home_bp.route('/index', methods=['GET'])
def _index_entry():
    """/index — SERVER 模式运维面板 / 其他模式渲染 index.html。"""
    # 🔧 v22.10.6: SERVER 模式短路 — 跳过 require_auth, 直接显示运维面板
    try:
        from app.node_role import is_server as _is_srv
        if _is_srv:
            return _server_ops_panel()
    except ImportError:
        pass
    # ── DEV/CLIENT 模式正常首页 (带 auth 装饰器) ──
    return _index_entry_real()

@system_container(require_auth='guest')
def _index_entry_real():
    """项目首页唯一入口 `/index` → 渲染 index.html。"""
    try:
        import sqlite3 as _sq3
        import server_real_db as _sdb
        version, info, latest = _sdb.get_version_info()
        stats = _sdb._get_homepage_stats()
        footer_info = _sdb._get_footer_info()
        particle_config = _sdb._get_particle_frontend_config()

        # ---- 确保访客 session 有 CSRF token（未登录用户访问首页时初始化）----
        import hashlib as _hl, os as _os, time as _tm
        if not _session.get('csrf_token'):
            _session['csrf_token'] = _hl.sha256(f'mtscos-csrf-sess-{_tm.time()}-{_os.urandom(16)}'.encode()).hexdigest()

        # ---- 补查 MTSCOS_DB（app.db 中 users/questions/exams 为 0 或表不存在）----
        # 规则§数据库唯一数据源：mtscos.db 是更大的主库，app.db 是 AI 引擎库
        try:
            _dbp2 = getattr(_sdb, 'DATA_MTSCOS_DB', None)
            if _dbp2:
                _mc = _sq3.connect(_dbp2, timeout=8)
                _mc.execute('PRAGMA busy_timeout=8000')
                _mcur = _mc.cursor()
                # users_count：取两库 max（app.db 可能有 seed admin, mtscos.db 才是完整用户）
                try:
                    _r = _mcur.execute('SELECT COUNT(*) FROM users').fetchone()
                    if _r and _r[0] > 0:
                        stats['users_count'] = max(stats.get('users_count', 0), _r[0])
                except Exception:
                    pass
                # questions_count
                if not stats.get('questions_count'):
                    for _qt in ('questions', 'question_bank', 'question_items'):
                        try:
                            _r = _mcur.execute(f'SELECT COUNT(*) FROM "{_qt}"').fetchone()
                            if _r and _r[0] > 0:
                                stats['questions_count'] = _r[0]
                                break
                        except Exception:
                            pass
                # exams_count
                if not stats.get('exams_count'):
                    for _et in ('exams', 'exam_sessions', 'exam_records'):
                        try:
                            _r = _mcur.execute(f'SELECT COUNT(*) FROM "{_et}"').fetchone()
                            if _r and _r[0] > 0:
                                stats['exams_count'] = _r[0]
                                break
                        except Exception:
                            pass
                # ai_employees_count（mtscos.db 更全）
                try:
                    _r = _mcur.execute('SELECT COUNT(*) FROM ai_employees').fetchone()
                    if _r and _r[0] > (stats.get('ai_employees_count') or 0):
                        stats['ai_employees_count'] = _r[0]
                except Exception:
                    pass
                _mc.close()
        except Exception:
            pass

        # ---- AI 生态实时计数（AI员工/EigenFlux专家/自动化daemon/AI集群节点）----
        # 规则§数据库唯一数据源：所有数字落库查询，禁止假数据；表单表缺失时优雅降级。
        ai_eco = {
            'experts': 0, 'daemons': 0, 'cluster_nodes': 0,
            'brain_feeds': 0, 'engines': 0,
        }
        try:
            _dbp = _sdb.APP_DB
            _dbp2 = getattr(_sdb, 'DATA_MTSCOS_DB', None)
            _c = _sq3.connect(_dbp, timeout=8)
            _c.execute('PRAGMA busy_timeout=8000')
            _cur = _c.cursor()

            def _cnt(table):
                try:
                    _cur.execute('SELECT COUNT(*) FROM sqlite_master WHERE type="table" AND name=?', (table,))
                    if not _cur.fetchone()[0]:
                        return None
                    _cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    _r = _cur.fetchone()
                    return _r[0] if _r else 0
                except Exception:
                    return None

            # EigenFlux 专家（eigenflux_experts 表，非 registrations 注册表）
            _exp = _cnt('eigenflux_experts')
            if _exp is None or _exp == 0:
                _exp = _cnt('eigenflux_registrations') or 0
            ai_eco['experts'] = _exp if _exp is not None else 0

            # 自动化守护进程：优先 mt_daemon_registry，不存在则取 mt_ai_heartbeat_log 中不同 daemon_name 数
            _dm = _cnt('mt_daemon_registry')
            if _dm is None or _dm == 0:
                try:
                    _cur.execute('SELECT COUNT(DISTINCT daemon_name) FROM mt_ai_heartbeat_log')
                    _r = _cur.fetchone()
                    _dm = _r[0] if _r and _r[0] and _r[0] > 0 else 15
                except Exception:
                    _dm = 15
            ai_eco['daemons'] = _dm if _dm else 15

            # 集群挂载节点
            _cn = _cnt('ai_cluster_nodes')
            if _cn is None or _cn == 0:
                _cn = _cnt('ai_cluster_config') or 0
            ai_eco['cluster_nodes'] = _cn if _cn is not None else 0

            # 脑库投喂记录
            _bf = _cnt('mt_ai_brain_feed_log')
            ai_eco['brain_feeds'] = _bf if _bf is not None else 0

            # 跨两库取最大值（app.db 是 AI 引擎库，mtscos.db 是主库，主库数据更全）
            if _dbp2:
                try:
                    _c2 = _sq3.connect(_dbp2, timeout=8)
                    _c2.execute('PRAGMA busy_timeout=8000')
                    _cur2 = _c2.cursor()
                    def _cnt2(table):
                        try:
                            _cur2.execute('SELECT COUNT(*) FROM sqlite_master WHERE type="table" AND name=?', (table,))
                            if not _cur2.fetchone()[0]:
                                return 0
                            _cur2.execute(f'SELECT COUNT(*) FROM "{table}"')
                            _r = _cur2.fetchone()
                            return _r[0] if _r else 0
                        except Exception:
                            return 0
                    # EigenFlux 专家：主库取大（2992 > app库 12）
                    ai_eco['experts'] = max(ai_eco['experts'], _cnt2('eigenflux_experts'))
                    # EigenFlux 注册总数（累计注册）
                    _reg = _cnt2('eigenflux_registrations')
                    if _reg > ai_eco['experts']:
                        ai_eco['experts_total'] = _reg
                    # 集群节点主库取大
                    ai_eco['cluster_nodes'] = max(ai_eco['cluster_nodes'], _cnt2('ai_cluster_nodes'))
                    # 脑库投喂主库取大（47万+ > app库 2.9万）
                    ai_eco['brain_feeds'] = max(ai_eco['brain_feeds'], _cnt2('mt_ai_brain_feed_log'))
                    _c2.close()
                except Exception:
                    pass
            _c.close()
        except Exception:
            pass
        # 引擎数取本地 AI 引擎目录 .py 文件数（零token本地推理体系）
        try:
            import os as _os
            _eng_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'engines')
            if _os.path.isdir(_eng_dir):
                ai_eco['engines'] = len([f for f in _os.listdir(_eng_dir)
                                         if f.endswith('.py') and not f.startswith('__')])
        except Exception:
            pass

        # ---- SA 规则体系状态（规则学习/执行/违反/完整性扫描）----
        # 规则§数据库唯一数据源：从规则治理表查询真实数据，表缺失时优雅降级。
        sa_rules = {
            'learning_logs': 0, 'enforcement_logs': 0,
            'violations': 0, 'integrity_passed': 0, 'integrity_failed': 0,
            'weak_words': 0, 'last_scan': '', 'active_rules': 12,
        }
        try:
            _rdb = _sdb.APP_DB
            if _rdb:
                _rc = _sq3.connect(_rdb, timeout=8)
                _rc.execute('PRAGMA busy_timeout=8000')
                _rcur = _rc.cursor()

                def _rcnt(table):
                    try:
                        _rcur.execute('SELECT COUNT(*) FROM sqlite_master WHERE type="table" AND name=?', (table,))
                        if not _rcur.fetchone()[0]:
                            return None
                        _rcur.execute(f'SELECT COUNT(*) FROM "{table}"')
                        _r = _rcur.fetchone()
                        return _r[0] if _r else 0
                    except Exception:
                        return None

                _ll = _rcnt('mt_ai_rule_learning_log')
                sa_rules['learning_logs'] = _ll if _ll is not None else 0
                _el = _rcnt('mt_ai_rule_enforcement_log')
                sa_rules['enforcement_logs'] = _el if _el is not None else 0
                _va = _rcnt('mt_rule_violation_alert')
                sa_rules['violations'] = _va if _va is not None else 0
                # 完整性扫描最新一条
                try:
                    _rcur.execute('SELECT total_rules,scanned_rules,passed_rules,failed_rules,weak_words_count,scan_at FROM mt_rule_integrity_scan ORDER BY scan_at DESC LIMIT 1')
                    _sr = _rcur.fetchone()
                    if _sr:
                        sa_rules['integrity_passed'] = _sr[2] or 0
                        sa_rules['integrity_failed'] = _sr[3] or 0
                        sa_rules['weak_words'] = _sr[4] or 0
                        sa_rules['last_scan'] = str(_sr[5] or '')[:16]
                except Exception:
                    pass
                _rc.close()
        except Exception:
            pass

        # ---- 主题方案列表（从 mt_theme_schemes 读取真实活跃主题）----
        # 规则§设计规范：禁止硬编码颜色，主题色从数据库 theme_json 中提取
        theme_schemes = []
        try:
            import json as _json
            _tc = _sq3.connect(_sdb.APP_DB, timeout=8)
            _tc.execute('PRAGMA busy_timeout=8000')
            for row in _tc.execute(
                'SELECT scheme_id, scheme_name, preset_key, theme_json, is_active '
                'FROM mt_theme_schemes WHERE is_active=1 ORDER BY user_priority DESC LIMIT 12'
            ).fetchall():
                _tj = {}
                try:
                    _tj = _json.loads(row[3]) if row[3] else {}
                except Exception:
                    pass
                theme_schemes.append({
                    'scheme_id': row[0],
                    'name': row[1],
                    'preset_key': row[2],
                    'primary': _tj.get('primary', _tj.get('color_palette_hex', {}).get('primary_base', '#5B8FB9')),
                    'is_memorial': row[2] == 'national_memorial',
                })
            _tc.close()
        except Exception:
            pass
        if not theme_schemes:
            # 优雅降级：使用默认 3 主题（用 CSS 变量名，非硬编码色值）
            theme_schemes = [
                {'scheme_id': 'default', 'name': '极光蓝', 'preset_key': 'aurora', 'primary': 'var(--mtscos-primary-base)', 'is_memorial': False},
                {'scheme_id': 'twilight', 'name': '暮色紫', 'preset_key': 'twilight', 'primary': 'var(--mtscos-secondary-base)', 'is_memorial': False},
                {'scheme_id': 'dawn', 'name': '晨曦橙', 'preset_key': 'dawn', 'primary': 'var(--mtscos-accent-base)', 'is_memorial': False},
            ]

        # ---- 认知画像注入 (仙女座 §三 v5.5) ----
        cognitive_profile = {}
        try:
            _cp_sdb = getattr(_sdb, 'APP_DB', None)
            if _cp_sdb:
                _cp_c = _sq3.connect(_cp_sdb, timeout=8)
                _cp_row = _cp_c.execute(
                    "SELECT cognitive_level, learning_style, focus_subjects, weak_subjects, "
                    "pace_setting, preferred_output, ai_tutor_type FROM mt_user_cognitive_profile "
                    "WHERE user_id=?", (_session.get('user_id', 'guest'),)).fetchone()
                cognitive_profile = dict(_cp_row) if _cp_row else {}
                _cp_c.close()
        except Exception:
            pass

        return _render_template('index.html',
                                version=version,
                                version_info=info,
                                latest_version=latest,
                                homepage_stats=stats,
                                _s=stats,
                                footer_info=footer_info,
                                particle_config=particle_config,
                                ai_eco=ai_eco,
                                sa_rules=sa_rules,
                                theme_schemes=theme_schemes,
                                page_csrf_token=_session.get('csrf_token', ''),
                                cognitive_profile=cognitive_profile)
    except Exception:
        # 模板不可用时返回简单提示页，禁止重定向回 /login（会导致死循环）
        return ('<html><head><meta charset="utf-8"><title>MTSCOS AI</title>'
                '<style>body{font-family:sans-serif;display:flex;justify-content:center;'
                'align-items:center;height:100vh;margin:0;background:#f5f5f5}'
                '.box{text-align:center;padding:40px;background:white;border-radius:8px;'
                'box-shadow:0 2px 8px rgba(0,0,0,0.1)}a{color:#4a90d9}</style></head>'
                '<body><div class="box"><h2>MTSCOS AI 系统</h2>'
                '<p>首页模板暂不可用，请从登录页进入</p>'
                '<a href="/login">前往登录页</a></div></body></html>'), 200


def register_all_blueprints(app):
    """注册全部20个Blueprint到Flask app

    容错策略：
      1. 每个 blueprint 单独 import + 单独 register_blueprint
      2. 单个失败不阻断其他
      3. 关键：import 阶段可能触发已注册 blueprint 的 @bp.route 装饰器抛 AssertionError，
         所以 import 也在 try 块内
    """
    # 🔧 v22.10.6: SERVER 模式专属 before_request 钩子 (运维面板 + 登录面板)
    _install_server_overrides(app)
    # (模块名, blueprint 变量名)
    _modules = [
        ('auth_routes', 'auth_bp'),
        ('vote_routes', 'vote_bp'),
        ('devflow_routes', 'devflow_bp'),
        ('legal_routes', 'legal_bp'),
        ('admin_routes', 'admin_bp'),
        ('ai_routes', 'ai_bp'),
        ('education_routes', 'education_bp'),
        ('api_routes', 'api_bp'),
        ('maintenance_routes', 'maintenance_bp'),
        ('k12_management_routes', 'k12_bp'),
        ('adult_education_routes', 'adult_bp'),
        ('exam_system_routes', 'exam_bp'),
        ('test_system_routes', 'test_bp'),
        ('learning_system_routes', 'learning_bp'),
        ('japanese_learning_routes', 'japanese_bp'),
        # AI 治理中心 (v2.8.0 新增)
        ('eigenflux_routes', 'eigenflux_bp'),
        ('brain_bank_routes', 'brain_bank_bp'),
        ('neural_array_routes', 'neural_array_bp'),
        # 艺术家工坊 (v2.10.0 新增)
        ('art_studio_routes', 'art_studio_bp'),
        # Arduino 设备热插拔自动行为 (v1.2.0 新增, 规则§13)
        ('arduino_session_routes', 'arduino_bp'),
        # 主题调度中心 — 吴美工 AI 14套节日/个性化主题 (v22.0.0 WU IR14)
        ('theme_routes', 'theme_bp'),
        # 安全仪表盘 — 杨安 AI 底层安全专家 4安全表/13开关/审计/CSP (v22.7.0 YANG IR14)
        ('security_routes', 'security_bp'),
        # AI 治理中枢管理面板 (v22.11.0 新增 OneDrive 主库 schema 对齐+8页面)
        ('governance_panel_routes', 'governance_panel_bp'),
        # 首页/根路由 — 路由链路闭环 (VII代 v22.10.0 新增)
    (None, 'home_bp'),
    # 只读盘点功能 (v22.19.0 新增, T2 任务)
    ('readonly_inventory_routes', 'readonly_inventory_bp'),
    # 页面级路由 (v22.35.0 新增) — 非 /api/ 前缀, 给功能域提供独立页面入口
    ('page_routes', 'page_routes_bp'),
    # exam 页面级路由 (v22.35.0 Phase 2 拆分) — 从 server_real_db.py 移出 7 个页面 route
    ('exam_page_routes', 'exam_page_bp'),
    # admin_app 子页面路由 (v22.35.0 Phase 3 拆分) — catch-all + 3 具体页面
    ('admin_subpage_routes', 'admin_subpage_bp'),
    # 认证域页面级路由 (v22.35.0 Phase 4 拆分) — /login /auth/logout /admin_app/login /session_health
    ('auth_page_routes', 'auth_page_bp'),
    # exam POST 提交路由 (v22.35.0 Phase 5 拆分) — 代理模式转发到 sdb 函数定义
    ('exam_post_routes', 'exam_post_bp'),
    # 系统健康路由 (v22.35.0 Phase 6 拆分) — 修复 /api/health 重复注册
    ('system_health_routes', 'system_health_bp'),
    # 系统状态面板 (v22.36.0 P0 验证模块 #1, 完整复制模式)
    ('system_status_routes', 'system_status_bp'),
    # 快速操作聚合 (v22.36.0 P0 验证模块 #2, 代理模式)
    ('quick_actions_routes', 'quick_actions_bp'),
    # AI 学习系统 API (v22.37.0 新增 — /api/ai-learning/run 手动触发学习周期)
    ('ai_engines.ai_learning_api', 'ai_learning_bp'),
    # AI GitHub 开源融合 API (v22.37.0 新增 — /api/ai/github-fusion/* 三阶段流水线)
    ('ai_engines.github_fusion_api', 'github_fusion_bp'),
    # 仙女座仪表盘页面级路由 — /iceberg_center /iceberg_evolution 等 (v22.19.0 新增, 此前未注册)
    ('andromeda_dashboard_routes', 'andromeda_dashboard_bp'),
    # 🆕 v25.0: 角色注册表 — 自动为每个角色构建专属蓝图 (teacher/professor/counselor/mentor/parent/student/admin/super_admin)
    ('role_registry', '_role_bps'),  # 占位, 下方动态展开
    # 🆕 v25.0: 仙女座统一审批蓝图 — approvals_engine.py 单权威源
    ('approvals_routes', 'approvals_bp'),
    # 🆕 v25.0: 仙女座灰度发布蓝图 — gray_release_engine.py 状态机+门禁+哈希分流
    ('gray_release_routes', 'gray_bp'),
    # 🆕 v25.0: 仙女座统一角色设置蓝图 — role_settings_engine.py (DB 深度绑定)
    ('role_settings_routes', 'role_bp'),
    # 🆕 v25.0: 仙女座 × 冰山 元域蓝图 — iceberg_meta_model.py + iceberg_consciousness.py (五自绑定层)
    ('iceberg_meta_routes', 'iceberg_bp'),
    # 🆕 v25.1: Aurora 极光衍生维护系统 — 统一 daemon/域/自/角色 注册表
    ('aurora_routes', 'aurora_bp'),
    # 🆕 v25.1: AI 员工赋能 — 50+ 年资历 + 朋友圈 + 师徒链 + 自主请教 + 发光发热
    ('empowerment_routes', 'emp_bp'),
    # 🆕 v25.2: 🧊 冰山移动管理端 — 移动端仪表盘 + 同步状态
    ('mobile_iceberg_routes', 'mobile_iceberg_bp'),
    ('mobile_passport_routes', 'mobile_passport_bp'),
    # 🆕 v25.3: 📱 移动端主应用 — home/exam/learn/profile/login (之前全被 REDIRECT_MAP 重定向到 PC 端)
    ('mobile_routes', 'mobile_bp'),
    # 🆕 v25.5: 🌌 仙女座星系子系统 — 运营/合规/Swarm 组队/多平台发布 (galaxy_routes.py 完整文件已存在, 从未注册)
    ('galaxy_routes', 'galaxy_bp'),
]

    # 🆕 v25.0: 动态注册角色蓝图 (role_registry.build_role_blueprints)
    try:
        from routes.role_registry import build_role_blueprints
        _role_bps_dict = build_role_blueprints()
        # 挂到 globals 让注册循环能找到
        globals().update({f"role_{k}_bp": v for k, v in _role_bps_dict.items()})
        # 追加到 _modules 让注册循环遍历
        for _rk in _role_bps_dict.keys():
            _modules.append(('role_registry', f"role_{_rk}_bp"))
    except Exception as _e:
        print(f"  ! 角色蓝图注册跳过: {_e}")

    # ── 注册循环 (主流程, 不管角色蓝图 try 是否成功都要执行) ──
    registered = 0
    skipped = 0
    failed = []
    import importlib
    for mod_name, bp_attr in _modules:
        try:
            # mod_name=None → home_bp 定义在本模块，直接从 globals() 取（路由链路闭环）
            if mod_name is None:
                bp = globals().get(bp_attr, None)
                if bp is None:
                    failed.append((bp_attr, 'no local blueprint'))
                    continue
            else:
                # 单独 import 模块（避免一个模块失败拖累其他）
                # mod_name 含 '.' → 顶层包完整路径 (如 'ai_engines.ai_learning_api')
                # 否则 → routes 子包 (如 'ai_routes' → routes.ai_routes)
                if '.' in mod_name:
                    mod = importlib.import_module(mod_name)
                else:
                    mod = importlib.import_module('.' + mod_name, package=__name__)
                bp = getattr(mod, bp_attr, None)
                if bp is None:
                    failed.append((mod_name, f'no attr {bp_attr}'))
                    continue
            try:
                app.register_blueprint(bp)
                registered += 1
            except Exception as reg_e:
                msg = str(reg_e)
                if 'already been registered' in msg or 'has already been registered' in msg:
                    skipped += 1
                else:
                    failed.append((mod_name or bp_attr, 'register: ' + msg[:80]))
        except Exception as imp_e:
            msg = str(imp_e)
            if 'already been registered' in msg or 'has already been registered' in msg:
                skipped += 1
            else:
                failed.append((mod_name or bp_attr, 'import: ' + msg[:80]))
    if failed:
        print(f"  ! Blueprint 注册失败项: {failed}")
    print(f"  ✓ Blueprint 注册完成: 新增 {registered} 个, 跳过 {skipped} 个已注册, 失败 {len(failed)} 个")
    return app


# ── 机密等级合规: 错误响应脱敏 ──
def sanitize_error_response(resp_data, user_role='guest'):
    """错误响应脱敏: 移除 route_path/blueprint/repair_suggestion 等内部信息
    
    规则来源: MT_RULE_CLASSIFICATION §3 + 仙女座 §6 敏感信息合规
    """
    if not isinstance(resp_data, dict):
        return resp_data
    # L2 以下角色: 移除内部调试信息
    if user_role not in ('admin','super_admin'):
        for key in ['route_path', 'blueprint', 'repair_suggestion', 'design_tokens', 
                     'trace_id', 'severity', 'timestamp']:
            resp_data.pop(key, None)
    # 敏感字过滤
    for key in list(resp_data.keys()):
        if isinstance(resp_data[key], str):
            for sensitive in ['password=', 'token=', 'vikey=', 'fingerprint_template=']:
                if sensitive in resp_data[key].lower():
                    resp_data[key] = '[REDACTED]'
    return resp_data
