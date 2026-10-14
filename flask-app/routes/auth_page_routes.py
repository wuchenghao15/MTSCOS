"""
auth_page_routes — 认证域页面级路由 (v22.35.0 Phase 4 拆分)
===========================================================
从 server_real_db.py 迁移 auth 域页面级 route。

⚠️ 设计决策: /auth/login POST 核心 (707 行, L9774-10480) + /auth/register POST (554 行)
   留在 server_real_db.py 不动 — 它们的 SA 双硬件认证/AI 风险引擎/EigenFlux 专家表决
   依赖 ~30 个 sdb 内部辅助函数 + 闭包 def，复制风险太高。
   只搬: 页面渲染 handler + 简单 POST handler + admin_app_login redirect。

已迁移:
  /login (GET)                → 渲染 login.html
  /auth/logout (GET+POST)     → session 清理 + remember-me 撤销
  /admin_app/login (GET+POST) → 重定向到首页普通登录 (已废除独立入口)
  /auth/session_health (GET)  → session 健康检查

不动 (留在 server_real_db.py):
  /auth/login (GET+POST)      → 核心认证 707 行
  /auth/register (GET+POST)   → 注册 554 行
  /mobile/login               → 移动端登录 (单独域)

端点命名变更: 搬前 endpoint='login_page' 等, 搬后='auth_page_routes.login_page' 等
  - 全局 url_for 引用需要同步更新 (grep 后确认无引用)
"""
import datetime as _dt

from flask import (
    Blueprint, redirect, render_template, request, session,
    make_response as _make_response, jsonify as _jsonify,
)
from app.middlewares.system_container import system_container


_bp = Blueprint('auth_page_routes', __name__)
auth_page_bp = _bp  # register_all_blueprints 查找


_sdb = None


def _mt_sdb():
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


# ═══════════════════════════════════════════════════════════════════════
# 1. /login GET — 渲染登录页面 (L9762-9770)
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/login', methods=['GET'])
@system_container(require_auth='guest')
def login_page():
    """登录页面 - 已废除独立入口, 统一跳转到 /index#login-card (首页内嵌登录表单)"""
    # v22.39.0: 系统统一入口, /index 已包含完整 bizLoginForm (fetch /auth/login)
    # 保留 302 不断链 (外部书签/深链)
    return redirect('/index#login-card', code=302)


# ═══════════════════════════════════════════════════════════════════════
# 2. /auth/logout GET+POST — 登出 (L11037-11073)
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/auth/logout', methods=['GET', 'POST'])
@system_container(require_auth='login')
def logout():
    ip = request.remote_addr or 'unknown_ip'
    ua = request.headers.get('User-Agent', '')[:200]
    username = session.get('username') or ''
    user_id = session.get('user_id')
    # 撤销该用户 remember-me token（可选择性地全部撤销）
    try:
        if user_id:
            _mt_sdb()._remember_me_revoke_all_for_user(int(user_id), ip=ip, reason='user_logout')
    except Exception:
        pass
    # 清除 session
    session.clear()
    # 清除 remember cookie，同时返回响应
    resp = redirect('/')
    # 清空所有 session cookie（兼容 remember-me token 名）
    for cookie_name in list(request.cookies.keys()):
        if cookie_name.startswith('remember_'):
            resp.delete_cookie(cookie_name, path='/')
    resp.delete_cookie('remember_me', path='/')
    # 审计日志
    try:
        if username:
            sdb = _mt_sdb()
            write_db = sdb._find_writable_user_db()
            if write_db:
                try:
                    with sdb._get_conn(write_db) as c:
                        sdb._ensure_login_logs_schema_any(c)
                        c.execute(
                            "INSERT INTO login_attempts (username, ip_address, success, timestamp) VALUES (?, ?, 0, ?)",
                            (username, ip, _dt.datetime.now().isoformat()))
                        c.commit()
                except Exception:
                    pass
    except Exception:
        pass
    return resp


# ═══════════════════════════════════════════════════════════════════════
# 3. /admin_app/login GET+POST — 管理员登录 redirect (L16154-16175)
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/admin_app/login', methods=['GET', 'POST'])
@system_container(require_auth='guest')
def admin_app_login():
    """整合到首页普通登录表单：GET/POST 均 302 到首页，避免死链。已废除独立入口。"""
    from urllib.parse import urlencode as _urlenc
    next_url = request.args.get('next') or request.form.get('next') or '/admin_app/dashboard'
    qs = _urlenc({'admin': '1', 'next': next_url})
    try:
        ip = request.remote_addr or 'unknown_ip'
        ua = request.headers.get('User-Agent', '')[:200]
        _mt_sdb()._ef_process_report_anomaly(
            'admin_login_redirected', 'admin_app_login_redirect', 'LOW',
            {'next_url': next_url, 'method': request.method,
             'note': '独立管理员入口已废除，统一跳转到首页普通登录'},
            notify_ai_employees=False, auto_apply_fix=False,
            client_ip=ip, client_ua=ua
        )
    except Exception:
        pass
    return redirect(f'/?{qs}', code=302)


# ═══════════════════════════════════════════════════════════════════════
# 4. /auth/session_health GET — session 健康检查 (vikey driver 检测 SA 双钥状态)
#    从 server_real_db.py L12524-12564 原样恢复 (Phase 4 简化版缺少 vikey 检测)
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/auth/session_health', methods=['GET'])
@system_container(require_auth='login')
def session_health():
    """Dashboard 实时监测: 用户容器登录状态 + 超级管理员额外检查 VIKEY 加密狗插入状态"""
    username = session.get('username')
    if not username:
        return _jsonify({
            'ok': False, 'reason': 'session_expired',
            'username': None, 'role': None,
            'vikey_present': None, 'vikey_bound': None,
        }), 401
    role = session.get('role', 'user')
    is_super_admin = (str(username or '').lower() == 'wuchenghao15')
    result = {
        'ok': True, 'reason': 'ok',
        'username': username, 'role': role,
        'vikey_present': None, 'vikey_bound': None,
    }
    if is_super_admin:
        try:
            from core.services.vikey_driver import get_vikey_manager as _gvkm
            vikey_mgr = _gvkm()
            det = vikey_mgr.detect()
            devs = (det or {}).get('devices') or []
            bound_serial = None
            present_count = 0
            for d in devs:
                if d.get('is_present'):
                    present_count += 1
                binding = d.get('binding') or {}
                if binding.get('username') == 'wuchenghao15' and binding.get('binding_status') == 'bound':
                    bound_serial = d.get('serial') or binding.get('serial')
            result['vikey_present'] = present_count > 0
            result['vikey_bound'] = bool(bound_serial)
            result['vikey_bound_serial'] = bound_serial
            if not bound_serial or present_count == 0:
                result['ok'] = False
                result['reason'] = 'vikey_detached' if present_count == 0 else 'vikey_unbound'
        except Exception as e:
            result['ok'] = False
            result['reason'] = 'vikey_exception:' + str(e)[:60]
    return _jsonify(result), (200 if result.get('ok') else 401)


# ═══════════════════════════════════════════════════════════════════════
# 5. /auth/register GET+POST — 用户注册 (代理模式, v22.38.0 P1 拆分)
#    server_real_db.py 保留 register() 552 行函数体 (内部依赖 _LEGAL_DOCUMENTS /
#    _REQUIRED_TERMS_SLUGS / _find_user_in_db / remember-me 等模块级常量)
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/auth/register', methods=['GET', 'POST'])
@system_container(require_auth='guest')
def register():
    """Phase 9 代理: 转发到 sdb.register() — 函数定义保留在 sdb (552行 GET+POST 逻辑)"""
    return _mt_sdb().register()
