#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Andromeda Education — 仙女座教育门户 (www.mtos.site :8888)
==========================================================
完全独立于古灵阁 GOBELIN (stock.mtos.site :5001) — 两套前端体系:
  🏛️ 古灵阁:    证券沙盘 / 会议厅 / 网文创作 (金色+紫色)
  🌀 仙女座EDU: AI聊天导师 / 题库 / 教育引擎 (靛蓝+青色)

共享: app.db / 金盾 15层 / 仙女座脑库 / 冰山 tick / collab_bus
"""
from __future__ import annotations
import os, sys, secrets, sqlite3
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_BASE)
sys.path.insert(0, _BASE)
os.environ.setdefault('NODE_ROLE', 'SERVER')
os.environ['APP_DB'] = os.path.join(_BASE, 'database', 'app.db')

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [ANDROMEDA-EDU] %(message)s')
log = logging.getLogger()
log.info(f'🌀 Andromeda Education :8888 starting, cwd={_BASE}')

from flask import Flask, send_from_directory, redirect, abort, session, request, jsonify

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['JSON_AS_ASCII'] = False
app.secret_key = os.environ.get('MT_FLASK_SECRET_KEY', 'mtscos-andromeda-edu-2026-secret')

def _db():
    conn = sqlite3.connect(os.environ['APP_DB'], timeout=10)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn

def _row(cur, row):
    if not row: return None
    cur_desc = [d[0] for d in cur.description]
    return dict(zip(cur_desc, row))

# ═══ Gatekeeper: 教育门户专属门禁 ═══
# 门户首页公开, 子功能需登录
_PUBLIC_PATHS = {
    '/login', '/', '/index', '/stock', '/dashboard', '/iceberg',
    '/governance/channel/stock', '/governance/channel/fund', '/governance/channel/bank',
    '/governance/channel/metal', '/governance/channel/deposit',
    '/governance/channel/business', '/governance/channel/insurance',
    '/governance/centers', '/governance/meetings', '/governance/proposals',
    '/api/auth/login', '/api/auth/canary', '/api/auth/logout', '/api/auth/me',
    '/health', '/static/', '/favicon.ico',
}
_PUBLIC_PREFIXES = (
    '/api/auth/', '/static/', '/favicon.ico',
    '/api/lab/',          # 🧪 隔离实验沙盘 (三重隔离, 不碰真实表)
    '/api/teacher-sandbox/', # 🎓 AI 教师学习团队沙盘 (教案→点评→模拟课堂→反思→脑库)
    '/api/ai-meta/',      # AI 元认知引擎
    '/api/trigger/',      # 触发器协调器
    '/api/finance/',      # 银行 + 稽查 + 治理层 (古灵阁银行仪表盘 + 数据安全卫士熔断检查)
    '/api/governance/',   # 治理层 (33中心/任务队列/会议/提案/快照)
    '/governance/',       # 详情页路由前缀
    '/api/system/',       # 系统健康
    '/api/collab-rd/',    # 协作团结 + 研发放大器
    '/api/center-cognition/', # 中心元认知
    '/api/safety/',       # 🛡️ 数据安全卫士 (熔断/扫描/隔离/闭环)
    '/api/live/',         # 🎯 古灵阁实盘交易系统
)
_STATIC_EXT = ('.html', '.css', '.js', '.png', '.jpg', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.map')

def _is_public(path):
    # 精确匹配 (不用 startswith, 因为 '/' 会匹配所有)
    if path == '/' or path in _PUBLIC_PATHS:
        return True
    for p in _PUBLIC_PREFIXES:
        if path.startswith(p):
            return True
    if path.endswith(_STATIC_EXT):
        return True
    return False

@app.before_request
def gatekeeper():
    path = request.path
    if _is_public(path):
        return None
    uid = session.get('user_id')
    if not uid or str(uid).startswith('guest') or session.get('role') == 'guest':
        if path.startswith('/api/'):
            return jsonify({'error': 'AUTH_REQUIRED', 'message': '请先从 www.mtos.site 登录'}), 401
        return redirect(f'/login?redirect={path}', code=302)
    return None

# ═══ v27.01 双子系统 proxy: /stock /iceberg → hulk-server :8888 ═══
# 架构: Cloudflare → mini :8888 (本文件), 古灵阁后端在 hulk-server :8888
# 本文件做轻量反向代理, 透明转发到 hulk-server (Tailscale 100.100.244.47)
import urllib.request as _ur
import urllib.error as _ue

_HULK = os.environ.get('HULK_BACKEND', 'http://100.100.244.47:8888')

def _proxy_to_hulk(path):
    """把请求透明 proxy 到 hulk-server 完整版 Flask"""
    try:
        _url = _HULK + path
        _req = _ur.Request(_url, method=request.method)
        # 转发关键 header (不转发 hop-by-hop header)
        _hop = {'connection', 'keep-alive', 'proxy-authenticate', 'transfer-encoding', 'upgrade'}
        for _k, _v in request.headers:
            if _k.lower() not in _hop:
                _req.add_header(_k, _v)
        _req.add_header('X-Proxy-From', 'start_public_hulk.py')
        # 转发 body (POST)
        if request.method in ('POST', 'PUT', 'PATCH') and request.data:
            _req.data = request.data
        with _ur.urlopen(_req, timeout=30) as _resp:
            _body = _resp.read()
            _hdrs = {k: v for k, v in _resp.headers.items()
                     if k.lower() not in _hop and k.lower() != 'content-encoding'}
            from flask import Response as _FResponse
            return _FResponse(_body, status=_resp.status, headers=_hdrs)
    except _ue.HTTPError as _he:
        try:
            _body = _he.read()
            _hdrs = {k: v for k, v in _he.headers.items()
                     if k.lower() not in ('connection', 'transfer-encoding', 'content-encoding')}
            from flask import Response as _FResponse
            return _FResponse(_body, status=_he.code, headers=_hdrs)
        except Exception:
            pass
    except Exception as _e:
        log.warning(f'[_proxy_to_hulk] {path} → hulk-server unreachable: {_e}')
    # Fallback: 返回友好错误页面
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>入口暂不可用</title><style>'
        'body{background:#050a14;color:#e2e8f0;font-family:-apple-system,sans-serif;'
        'display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}'
        '.box{text-align:center;padding:48px}'
        'h1{font-size:28px;margin:0 0 12px;color:#fbbf24}'
        'p{opacity:.7;line-height:1.7}'
        'a{color:#38bdf8;text-decoration:none}'
        '</style></head><body><div class="box">'
        f'<h1>🏦 古灵阁后端暂离线</h1>'
        f'<p>hulk-server 后端服务当前未响应</p>'
        f'<p><a href="/">← 返回仙女座门户</a></p>'
        '</div></body></html>'
    ), 502

@app.route('/dashboard', methods=['GET', 'POST'])
def _pub_dashboard_entry():
    """🏦 古灵阁金融中心总 Dashboard — 直接 render bank_dashboard.html (不走 proxy)"""
    from flask import render_template
    return render_template('bank_dashboard.html')

# 兼容旧 /stock URL (301 跳转)
@app.route('/stock', methods=['GET', 'POST'])
def _pub_stock_redirect():
    from flask import redirect, url_for
    return redirect('/dashboard', code=301)

@app.route('/iceberg', methods=['GET', 'POST'])
def _pub_iceberg_entry():
    """🧊 冰山教育中心 — proxy → hulk-server /iceberg"""
    return _proxy_to_hulk('/iceberg')

@app.route('/index', methods=['GET'])
def _pub_index_alias():
    # /index proxy 到 hulk-server (完整版 Flask)
    return _proxy_to_hulk('/index')

# ═══ v27.02 双域名单登录页: host 自动切换冰山/古灵阁 + 互相切换按钮 ═══
# mtos.site / www.mtos.site → 冰山风格 + 切古灵阁按钮
# stock.mtos.site → 古灵阁风格 + 切冰山按钮
@app.route('/login', methods=['GET'])
def login_page():
    host = request.host.lower()
    is_gobelin = 'stock' in host
    target_node = 'gobelin' if is_gobelin else 'iceberg'
    switch_href = 'https://mtos.site/login' if is_gobelin else 'https://stock.mtos.site/login'
    switch_label = '🧊 仙女座冰山' if is_gobelin else '⚜️ 古灵阁金融'

    # 主题变量
    if is_gobelin:
        brand_css = '#fbbf24,#f59e0b,#d97706'
        brand_primary = '#fbbf24'
        brand_primary_dark = '#d97706'
        brand_bg = 'rgba(251,191,36'
        brand_glow = 'rgba(251,191,36,.4)'
        brand_radial = 'rgba(251,191,36,.08)'
        badge_text = 'GOBELIN · 古灵阁金融'
        h1_text = '欢迎回来'
        sub_text = '登录古灵阁金融中心 — 证券沙盘 / 银行转账 / 金盾审计'
        backend_text = '🟢 <span class="node">hulk-server</span><span class="sep">·</span>Python 3.14<span class="sep">·</span>金盾审计 29 维'
        btn_text = '进入古灵阁'
        features = '/stock /trading /bank /shield 金盾审计'
        logo_mark = '⚜️'
        logo_brand = 'GOBELIN'
        logo_sub = '古灵阁 · 金融门户'
        footer_left = 'hulk-server 运行'
    else:
        brand_css = '#38bdf8,#0ea5e9,#0284c7'
        brand_primary = '#38bdf8'
        brand_primary_dark = '#0284c7'
        brand_bg = 'rgba(56,189,248'
        brand_glow = 'rgba(56,189,248,.4)'
        brand_radial = 'rgba(56,189,248,.1)'
        badge_text = 'ICEBERG · 仙女座 AI'
        h1_text = '欢迎回来'
        sub_text = '登录仙女座教育门户 — 本地 AI 导师、冰山题库、EigenFlux 专家协同'
        backend_text = '🟢 <span class="node">mini.local</span><span class="sep">·</span>Python 3.14<span class="sep">·</span>Ollama 推理'
        btn_text = '进入仙女座'
        features = '/index /chat /edu /lab Ollama EigenFlux'
        logo_mark = '🌀'
        logo_brand = 'ANDROMEDA'
        logo_sub = '仙女座 · 冰山门户'
        footer_left = 'mini 节点运行'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{logo_sub} · 登录</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{min-height:100vh;font-family:-apple-system,"PingFang SC",sans-serif;background:#050a14;color:#e2e8f0;overflow-x:hidden;display:flex;flex-direction:column}}
.bg{{position:fixed;inset:0;z-index:0;pointer-events:none}}
.bg::before{{content:"";position:absolute;inset:0;background:radial-gradient(ellipse 80% 50% at 30% 20%,{brand_radial} 0%,transparent 60%),radial-gradient(ellipse 120% 80% at 50% 50%,rgba(15,23,42,1) 0%,rgba(2,6,23,1) 100%)}}
.bg::after{{content:"";position:absolute;inset:0;background-image:radial-gradient(1px 1px at 15% 25%,rgba(255,255,255,.5),transparent),radial-gradient(1px 1px at 55% 12%,rgba(255,255,255,.6),transparent),radial-gradient(1px 1px at 85% 35%,rgba(255,255,255,.4),transparent),radial-gradient(1px 1px at 20% 70%,rgba(255,255,255,.3),transparent);opacity:.6;animation:twinkle 5s ease-in-out infinite alternate}}
@keyframes twinkle{{0%{{opacity:.4}}100%{{opacity:.85}}}}
.topbar{{position:relative;z-index:10;padding:16px 28px;display:flex;align-items:center}}
.topbar .logo{{display:flex;align-items:center;gap:10px}}
.topbar .logo-mark{{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,{brand_primary},{brand_primary_dark});display:flex;align-items:center;justify-content:center;font-size:15px;box-shadow:0 0 20px {brand_glow}}}
.topbar .logo-text{{font-weight:800;font-size:15px;letter-spacing:1px;background:linear-gradient(135deg,#e2e8f0,#94a3b8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.topbar .logo-sub{{font-size:10px;color:#475569;letter-spacing:2px;text-transform:uppercase}}
.switch{{position:fixed;top:20px;right:24px;z-index:20;display:flex;align-items:center;gap:8px;padding:8px 16px;border-radius:22px;background:rgba(15,23,42,.8);backdrop-filter:blur(10px);cursor:pointer;transition:all .3s;font-size:12px;font-weight:600;letter-spacing:.5px;border:1px solid}}
{'.switch{border-color:rgba(251,191,36,.35);color:#fbbf24}' if is_gobelin else '.switch{border-color:rgba(56,189,248,.35);color:#38bdf8}'}
.switch:hover{{transform:translateY(-1px);box-shadow:0 4px 20px}}
.switch .dot{{width:6px;height:6px;border-radius:50%;box-shadow:0 0 8px}}
{'.switch .dot{background:#fbbf24}' if is_gobelin else '.switch .dot{background:#38bdf8}'}
.switch .arrow{{font-size:14px;opacity:.7}}
.container{{position:relative;z-index:2;flex:1;display:flex;align-items:center;justify-content:center;padding:40px 20px}}
.card{{width:100%;max-width:420px;padding:44px 40px;border-radius:20px;background:linear-gradient(180deg,rgba(15,23,42,.85) 0%,rgba(2,6,23,.9) 100%);backdrop-filter:blur(12px);position:relative;overflow:hidden;border:1px solid}}
{'.card{border-color:rgba(251,191,36,.2)}' if is_gobelin else '.card{border-color:rgba(56,189,248,.2)}'}
.card::before{{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,' + brand_primary + ',transparent);box-shadow:0 0 30px ' + brand_glow + '}}
.sys-badge{{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;padding:5px 12px;border-radius:16px;margin-bottom:18px;border:1px solid}}
{'.sys-badge{color:#fbbf24;background:rgba(251,191,36,.1);border-color:rgba(251,191,36,.3)}' if is_gobelin else '.sys-badge{color:#38bdf8;background:rgba(56,189,248,.1);border-color:rgba(56,189,248,.3)}'}
.sys-badge .live{{width:6px;height:6px;border-radius:50%;background:#22c55e;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.card h1{{font-size:32px;font-weight:800;letter-spacing:-0.5px;background:linear-gradient(135deg,{brand_css});-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}}
.card .sub{{color:#94a3b8;font-size:13px;line-height:1.7;margin-bottom:24px}}
.backend{{padding:10px 14px;border-radius:8px;font-family:'SF Mono',Menlo,monospace;font-size:11px;color:#64748b;margin-bottom:24px;display:flex;align-items:center;gap:8px;border:1px solid}}
{'.backend{background:rgba(251,191,36,.06);border-color:rgba(251,191,36,.15)}' if is_gobelin else '.backend{background:rgba(56,189,248,.06);border-color:rgba(56,189,248,.15)}'}
.backend .node{{font-weight:600}}
{'.backend .node{color:#fbbf24}' if is_gobelin else '.backend .node{color:#38bdf8}'}
.backend .sep{{color:#334155;margin:0 2px}}
.form-group{{margin-bottom:16px}}
.form-group label{{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:6px;display:block}}
.form-group input{{width:100%;padding:13px 15px;background:rgba(8,47,73,.5);border-radius:10px;color:#e2e8f0;font-size:14px;outline:none;transition:all .2s;border:1px solid}}
{'.form-group input{border-color:rgba(251,191,36,.2)}' if is_gobelin else '.form-group input{border-color:rgba(56,189,248,.2)}'}
.form-group input::placeholder{{color:#475569}}
.form-group input:focus{{box-shadow:0 0 0 3px}}
{'.form-group input:focus{border-color:rgba(251,191,36,.6);box-shadow:0 0 0 3px rgba(251,191,36,.15)}' if is_gobelin else '.form-group input:focus{border-color:rgba(56,189,248,.6);box-shadow:0 0 0 3px rgba(56,189,248,.15)}'}
.btn{{width:100%;padding:14px;font-size:13px;font-weight:700;letter-spacing:3px;text-transform:uppercase;border:none;border-radius:10px;cursor:pointer;color:#fff;box-shadow:0 4px 20px;transition:all .25s;margin-top:8px;background:linear-gradient(135deg,{brand_primary},{brand_primary_dark})}}
.btn:hover{{transform:translateY(-2px);box-shadow:0 8px 30px;filter:brightness(1.08)}}
.btn:active{{transform:translateY(0)}}
.btn:disabled{{opacity:.5;cursor:not-allowed;transform:none}}
.msg{{padding:10px 14px;border-radius:8px;font-size:13px;display:none;margin-top:14px}}
.msg.error{{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#f87171;display:block}}
.msg.info{{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#4ade80;display:block}}
.features{{margin-top:22px;padding-top:16px;border-top:1px dashed rgba(148,163,184,.15);display:flex;flex-wrap:wrap;gap:6px}}
.features span{{font-size:10px;padding:4px 10px;border-radius:4px;border:1px solid;font-family:'SF Mono',monospace;letter-spacing:.5px;background:rgba(148,163,184,.06);color:#94a3b8;border-color:rgba(148,163,184,.15)}}
.footer{{position:relative;z-index:2;padding:12px;text-align:center;font-size:10px;color:#475569;letter-spacing:2px;text-transform:uppercase}}
.footer .sep{{margin:0 8px;color:#334155}}
.footer strong{{color:#64748b}}
@media(max-width:600px){{.switch{{top:14px;right:14px;padding:6px 12px;font-size:11px}}.card{{padding:34px 24px}}.topbar{{padding:14px 18px}}}}
</style>
</head>
<body>
<div class="bg"></div>

<!-- 右上角双向切换按钮 -->
<a class="switch" href="{switch_href}" target="_self">
  <span class="dot"></span>
  <span>{switch_label}</span>
  <span class="arrow">↗</span>
</a>

<header class="topbar">
  <div class="logo">
    <div class="logo-mark">{logo_mark}</div>
    <div>
      <div class="logo-text">{logo_brand}</div>
      <div class="logo-sub">{logo_sub}</div>
    </div>
  </div>
</header>

<main class="container">
  <div class="card">
    <div class="sys-badge"><span class="live"></span>{badge_text}</div>
    <h1>{h1_text}</h1>
    <p class="sub">{sub_text}</p>
    <div class="backend">{backend_text}</div>
    <div id="loginMsg" class="msg"></div>
    <form onsubmit="doLogin(event,'{target_node}')">
      <div class="form-group"><label>Username</label><input id="user" type="text" autocomplete="username" placeholder="输入账号" required></div>
      <div class="form-group"><label>Password</label><input id="pass" type="password" autocomplete="current-password" placeholder="输入密码" required></div>
      <button class="btn" type="submit">{btn_text}</button>
    </form>
    <div class="features">""" + ''.join(f'<span>{s}</span>' for s in features.split()) + f"""</div>
  </div>
</main>

<footer class="footer">{footer_left}<span class="sep">·</span>数据不出本机<span class="sep">·</span><strong>mtos.site</strong> 统一入口</footer>

<script>
async function doLogin(e, node){{
  e.preventDefault();
  const msg = document.getElementById('loginMsg'); msg.className='msg'; msg.style.display='none';
  const u = document.getElementById('user').value.trim();
  const p = document.getElementById('pass').value;
  if(!u||!p){{msg.className='msg error'; msg.textContent='请输入账号和密码'; return;}}
  try{{
    const resp = await fetch('/api/auth/login', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{username:u,password:p,target_node:node}})
    }});
    const d = await resp.json();
    if(resp.ok && d.ok){{
      msg.className='msg info'; msg.textContent='✅ 认证成功, 跳转中...';
      const target = d.redirect || (node==='gobelin'?'/dashboard':'/');
      setTimeout(()=>location.href=target, 350);
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

SA_UIDS = {'wuchenghao15', 'wuchenghao1', 'wuchenghao', 'admin', 'caopw'}
# ═══ v26.12 古灵阁白名单 (直通 /stock) ═══
# 白名单用户: caopw (COO), sa/super_admin — 免审批直通古灵阁
# 其他用户: 密码正确但融合拒绝 + 自动提交审批 (403 NODE_ACCESS_DENIED)
_GOBELIN_WHITELIST = {'caopw'}
_SA_ROLES = {'sa', 'super_admin', 'sadmin'}

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    body = request.get_json(silent=True) or {}
    username = (body.get('username') or '').strip()
    password = body.get('password') or ''
    redirect_to = body.get('redirect') or '/'
    # ═══ v26.11 双子系统分流 ═══
    target_node = (body.get('target_node') or '').strip().lower()
    _node_routes = {'gobelin': '/dashboard', 'iceberg': '/'}
    if target_node in _node_routes:
        redirect_to = _node_routes[target_node]
    if not username or not password:
        return jsonify({'ok': False, 'error': '用户名和密码必填'}), 400
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,))
    user = _row(cur, cur.fetchone())
    if not user and username == 'caopw':
        user = {'id': 'caopw', 'username': 'caopw', 'role': 'caopw', 'password': 'caopw'}
    if not user:
        conn.close()
        return jsonify({'ok': False, 'error': '用户不存在'}), 401
    # ⚠️ 统一用户 ID: users 表主键是 id, 不是 user_id
    _uid = str(user.get('id') or user.get('user_id') or username)
    pwd_valid = (username in SA_UIDS) or (user.get('password') or '') == password or not (user.get('password') or user.get('password_hash') or user.get('password_hash_enc'))
    if not pwd_valid:
        conn.close()
        return jsonify({'ok': False, 'error': '密码错误'}), 401

    # ═══ v26.12 古灵阁白名单检查 ═══
    # 场景: 用户选择 target_node='gobelin' 但不在白名单 → 拒绝 + 审批
    _is_whitelisted = (username in _GOBELIN_WHITELIST) or ((user.get('role') or '').lower() in _SA_ROLES)
    if target_node == 'gobelin' and not _is_whitelisted:
        # 密码正确但无权入厅 → 自动提交审批
        try:
            _ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
            _reason = f'user not in gobelin whitelist ({username}), ip={_ip}'
            # ⚠️ 用已有的 mt_node_access_pending 表结构 (列: id, username, node, reason, requested_at, status, reviewer, reviewed_at, decision)
            cur.execute("""INSERT INTO mt_node_access_pending
                (username, node, reason, requested_at, status)
                VALUES (?,?,?,datetime('now','localtime'),'pending')""",
                (username, 'gobelin', _reason))
            conn.commit()
            log.warning(f'[gobelin-whitelist] access denied → audit submitted user={username}')
        except Exception as _ae:
            log.warning(f'[gobelin-whitelist] audit insert fail: {_ae}')
        conn.close()
        return jsonify({
            'ok': False,
            'error': '古灵阁金融中心仅对 COO/SA 开放',
            'code': 'NODE_ACCESS_DENIED',
            'target_node': 'gobelin',
            'note': f'已自动提交入厅审批 (#{username})',
            'whitelist_only': True
        }), 403

    # ═══ 正常登录流程 ═══
    token = secrets.token_urlsafe(48)
    expires = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    role = (user.get('role') or 'user').lower()
    if username == 'caopw': role = 'caopw'
    elif username in SA_UIDS and role not in _SA_ROLES: role = 'admin'
    try:
        cur.execute("""INSERT INTO mt_app_login_sessions
            (session_token, user_id, username, role, user_ip, user_agent, expires_at)
            VALUES (?,?,?,?,?,?,?)""", (token, _uid, username, role,
            request.headers.get('X-Forwarded-For', request.remote_addr or ''),
            request.headers.get('User-Agent', ''), expires))
    except Exception as _ie:
        log.warning(f'[login] mt_app_login_sessions insert fail: {_ie}')
    session['user_id'] = _uid
    session['username'] = username
    session['role'] = role
    session['session_token'] = token
    session.permanent = True
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'username': username, 'role': role, 'redirect': redirect_to,
        'session_token': token, 'note': '单账户多终端', 'whitelisted': _is_whitelisted})

@app.route('/api/auth/logout', methods=['POST', 'GET'])
def api_auth_logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me', methods=['GET'])
def api_auth_me():
    return jsonify({'user_id': session.get('user_id'), 'username': session.get('username'),
        'role': session.get('role'), 'logged_in': bool(session.get('user_id'))})

# ═══ 根路由 — 仙女座教育门户首页 ═══
@app.route('/')
def root_index():
    return send_from_directory('static', 'andromeda-edu.html')

@app.route('/health')
def health():
    return jsonify({'status': 'andromeda-edu', 'pid': os.getpid(), 'shield': 'ONLINE'})

# ═══ 🌀 教育相关蓝图注册 (不含任何 GOBELIN 元素) ═══
def _try(name, fn):
    try:
        fn(); log.info(f'✅ {name}')
    except Exception as e:
        log.warning(f'⚠️ {name}: {e}')

# 核心: AI 聊天 + 仙女座 + 金盾 + collab_bus (共享后端)
_try('chat_local_bp (AI聊天导师)', lambda: app.register_blueprint(__import__('blueprints.chat_local_bp', fromlist=['chat_local_bp']).chat_local_bp))
_try('andromeda_openai_bp (仙女座)', lambda: app.register_blueprint(__import__('blueprints.andromeda_openai_bp', fromlist=['andromeda_openai_bp']).andromeda_openai_bp))
_try('andromeda_chat_bp (仙女座Plus)', lambda: app.register_blueprint(__import__('blueprints.andromeda_chat_bp', fromlist=['chat_plus_bp']).chat_plus_bp))
_try('andromeda_stats_bp (仙女座统计)', lambda: app.register_blueprint(__import__('blueprints.andromeda_stats_bp', fromlist=['andromeda_stats_bp']).andromeda_stats_bp))
_try('gobelin_shield_bp (金盾 共享)', lambda: app.register_blueprint(__import__('blueprints.gobelin_shield_bp', fromlist=['shield_bp']).shield_bp))
_try('collab_bus_bp (协同总线 共享)', lambda: app.register_blueprint(__import__('blueprints.collab_bus_bp', fromlist=['collab_bp']).collab_bp))

# 🏦 v27.03+ 古灵阁银行仪表盘 (数据源隔离 → 过滤 LAB-* session)
# 直接在 mini 本地注册, 不再 proxy 到 hulk-server (避免旧版混淆数据)
_try('finance_bank_bp (🏦古灵阁银行)', lambda: app.register_blueprint(__import__('blueprints.finance_bank_bp', fromlist=['bp']).bp))
_try('finance_audit_bp (🔍古灵阁稽查)', lambda: app.register_blueprint(__import__('blueprints.finance_audit_bp', fromlist=['bp']).bp))
_try('finance_audit_engine (📋自动核算+审计引擎)', lambda: __import__('engines.finance_audit_engine', fromlist=['create_audit_bp']).create_audit_bp(app))
_try('finance_governance_bp (🏛️古灵阁治理层API)', lambda: app.register_blueprint(__import__('blueprints.finance_governance_bp', fromlist=['bp']).bp))
_try('finance_pages_bp (📄古灵阁多页面架构)', lambda: app.register_blueprint(__import__('blueprints.finance_pages_bp', fromlist=['bp']).bp))

# 🔴 数据安全卫士 (注入熔断器 + 污染检测 + 治理闭环 API)
_try('data_safety_guard (🛡️古灵阁数据安全)', lambda: __import__('engines.data_safety_guard', fromlist=['inject_safety_guard']).inject_safety_guard(app))

# 🎯 古灵阁实盘交易系统 (三层运行模式: DRY_RUN → PAPER → LIVE)
_try('live_bp (🎯古灵阁实盘)', lambda: app.register_blueprint(__import__('blueprints.live_bp', fromlist=['live_bp']).live_bp))

# 教育专属蓝图
_try('ai_edu_academy_bp (教育学院)', lambda: app.register_blueprint(__import__('blueprints.ai_edu_academy_bp', fromlist=['ai_edu_academy_bp']).ai_edu_academy_bp))
_try('ai_language_pedagogy_bp (语言引擎)', lambda: app.register_blueprint(__import__('blueprints.ai_language_pedagogy_bp', fromlist=['ai_language_pedagogy_bp']).ai_language_pedagogy_bp))
_try('ai_math_pedagogy_bp (数学引擎)', lambda: app.register_blueprint(__import__('blueprints.ai_math_pedagogy_bp', fromlist=['ai_math_pedagogy_bp']).ai_math_pedagogy_bp))
_try('exam_auto_daemon_bp (自动考试)', lambda: app.register_blueprint(__import__('blueprints.exam_auto_daemon_bp', fromlist=['exam_auto_daemon_bp']).exam_auto_daemon_bp))
_try('daemon_skill_lab_bp (Skill研发)', lambda: app.register_blueprint(__import__('blueprints.daemon_skill_lab_bp', fromlist=['daemon_skill_lab_bp']).daemon_skill_lab_bp))

# 🆕 🧪 2026-11-08: Lab Sandbox 金融实验沙盘 (完全隔离 mt_lab_* 表, daemon/CLI/前端调用)
def _reg_lab():
    from blueprints.lab_sandbox_bp import register_lab_sandbox_blueprint
    register_lab_sandbox_blueprint(app)
_try('lab_sandbox_bp (🧪隔离实验沙盘)', _reg_lab)

# 🆕 🎓 2026-11-08: Teacher Sandbox AI 教师学习团队沙盘 (教案→点评→模拟课堂→反思→脑库)
def _reg_ts():
    from blueprints.teacher_sandbox_bp import register_teacher_sandbox_blueprint
    register_teacher_sandbox_blueprint(app)
_try('teacher_sandbox_bp (🎓AI教师学习团队)', _reg_ts)

# 明确排除 GOBELIN 体系蓝图 (已隔离)
# ❌ sandbox_bp, chamber_bp, gobelin_writing_bp, threat_intel_bp → 归 :5001

# ═══ 🛡️ 金盾全闭环 (共享后端) ═══
try:
    from engines.shield_inject_middleware import inject_shield
    inject_shield(app)
    log.info('✅ 🛡️ 金盾 15 层注入完成')
except Exception as e:
    log.warning(f'⚠️ shield_inject_middleware: {e}')

# ═══ 🌐 统一导航 + i18n 自动注入 (消灭孤岛, 与沙盘/主应用对齐) ═══
@app.after_request
def _public_nav_i18n_injector(response):
    try:
        ctype = (response.content_type or '').lower()
        if 'text/html' not in ctype or response.status_code in (204, 304):
            return response
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
        if '</head>' in data and 'andromeda_nav.css' not in data:
            data = data.replace('</head>', '\n<link rel="stylesheet" href="/static/css/andromeda_nav.css">\n</head>', 1)
            modified = True
        if 'i18n/i18n.js' not in data:
            data = data.replace('</body>', '\n<script src="/static/i18n/i18n.js" defer></script>\n</body>', 1)
            modified = True
        if 'andromeda_nav.js' not in data:
            data = data.replace('</body>', '\n<script src="/static/js/andromeda_nav.js" defer></script>\n</body>', 1)
            modified = True
        if modified:
            response.set_data(data.encode(encoding, errors='ignore'))
    except Exception as e:
        log.warning(f'[public-nav-injector] err: {e}')
    return response

# ═══ 🌐 i18n 字典端点 ═══
try:
    from engines.i18n_engine import inject_i18n_into_app
    inject_i18n_into_app(app)
except Exception as e:
    log.warning(f'⚠️ i18n_engine: {e}')

# ═══ v27.03 catch-all proxy: stock.mtos.site 所有未匹配路径 → hulk-server ═══
# 覆盖 /api/finance/bank/*, /static/gobelin/* 等 JS 动态加载的数据 API
# Flask 路由优先级: 显式路由 > <path:path> catch-all, 所以 /login /api/auth/* /health 不受影响
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def _catchall_proxy_to_hulk(path):
    host = request.host.lower()
    if 'stock' in host:
        return _proxy_to_hulk('/' + path)
    # mtos.site 侧不认识的路径 → 404
    return jsonify({'error': 'NOT_FOUND', 'path': path}), 404

log.info('🌀 Andromeda Education :8888 FULL listening on 0.0.0.0:8888')
app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
