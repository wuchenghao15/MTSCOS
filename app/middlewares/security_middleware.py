#!/usr/bin/env python3
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

LOCKED_USERS = {}
SESSION_TIMEOUT = 1800
WARNING_TIMEOUT = 300
MAX_FAILED_LOGINS = 5
RATE_LIMIT = 100
RATE_LIMIT_WINDOW = 60

class SecurityMiddlewareClass:
    @staticmethod
    def before_request_handler():
        from flask import request, session, g

        allowed_paths = ['/auth/login', '/auth/register', '/auth/forgot_password',
                         '/auth/check_username', '/auth/check_password', '/auth/session_health',
                         '/auth/logout',  # 退出登录允许匿名调用（清空 session 是幂等的）
                         '/admin_app/login',
                         '/api/health', '/api/time', '/api/status', '/api/system_params',
                         '/api/monitoring/health',
                         '/api/questions/categories', '/api/questions/tags', '/api/questions/search',
                         '/api/tts/languages', '/api/tts/voices', '/api/tts/cache/stats',
                         '/api/tts/speak',
                         '/api/ai-repair/stats', '/api/ai-repair/fix-history',
                         '/api/server-time', '/api/error/report',
                         '/api/homepage/stats',  # 首页公开统计 (访客可见, P0修复 net::ERR_ABORTED)
                         '/', '/login', '/register', '/forgot_password', '/forgot-password',
                         '/assets/', '/static/', '/favicon.ico',
                         '/robots.txt', '/sitemap.xml',
                         '/_ui/report_particle_perf',
                         '/api/enhancement/stats', '/api/enhancement/ports',
                         '/api/enhancement/db_cluster', '/api/enhancement/ai_nodes',
                         '/api/enhancement/layouts', '/api/enhancement/permission_rules',
                         '/api/enhancement/models']

        path = request.path

        # 检查是否在白名单中
        for allowed in allowed_paths:
            if path == allowed:
                return None
            if allowed != '/' and allowed.endswith('/') and path.startswith(allowed):
                return None

        # 检查URL是否匹配任何已注册的路由规则
        from flask import current_app
        if current_app:
            from werkzeug.exceptions import NotFound, MethodNotAllowed
            adapter = current_app.url_map.bind('')
            try:
                adapter.match(path)
            except (NotFound, MethodNotAllowed):
                # 没有匹配的路由，让Flask处理404
                return None

        # 账户锁定检查
        if session.get('locked_until') and time.time() < session['locked_until']:
            return {
                'success': False,
                'error': '账户已锁定',
                'locked_until': session['locked_until'],
                'status_code': 423
            }

        # 已登录用户的会话检查
        if session.get('logged_in'):
            last_activity = session.get('last_activity', time.time())
            idle_time = time.time() - last_activity

            if idle_time > SESSION_TIMEOUT:
                session.clear()
                return {
                    'success': False,
                    'error': '会话已超时，请重新登录',
                    'status_code': 401
                }

            if idle_time > SESSION_TIMEOUT - WARNING_TIMEOUT:
                session['timeout_warning'] = True

            session['last_activity'] = time.time()

            if 'user_id' not in session or 'role' not in session:
                session.clear()
                return {
                    'success': False,
                    'error': '会话验证失败',
                    'status_code': 401
                }

            # ---- 方向2 阶段2: 6 字段 session 强制验证（张架构师）----
            # 项目硬约束: 用户容器必须包含 6 字段（组别/权限识别码/登陆状态/异常/合法/时间戳）
            # 对 SA session 走专属逻辑（_sa_session 标记，字段体系不同）
            is_sa_session = bool(session.get('_sa_session', False))
            if not is_sa_session:
                # 普通用户 6 字段验证（宽松兼容：缺失字段补默认值，不拒绝，避免破坏现有登录）
                _required_fields = ['group', 'role_canonical', 'logged_in',
                                    'is_abnormal', 'is_legitimate', 'login_time']
                _missing = [f for f in _required_fields if f not in session]
                if _missing:
                    logger.warning(f"[SecurityMiddleware] session 缺失字段: {_missing}, path={path}")
                    # 补充默认值（保证下游硬编码不失败）
                    if 'group' not in session:
                        session['group'] = 'default'
                    if 'role_canonical' not in session:
                        session['role_canonical'] = session.get('role', 'user')
                    if 'is_abnormal' not in session:
                        session['is_abnormal'] = False
                    if 'is_legitimate' not in session:
                        session['is_legitimate'] = True
                    if 'login_time' not in session:
                        session['login_time'] = session.get('last_activity', time.time())
            else:
                # ---- 方向1: SA session 专属逻辑 ----
                # SA 会话创建后需周期性复核 VIKEY + SZU100，任一缺失即销毁会话。
                _sa_last_check = session.get('_sa_dual_last_check', 0.0)
                if time.time() - _sa_last_check > 30:
                    try:
                        from core.services.vikey_driver import get_hardware_key_provider
                        _provider = get_hardware_key_provider()
                        _dual_ok, _dual_reason = _provider.verify_dual_key_atomic(timeout=5.0)
                    except Exception as _e:
                        logger.warning(f"[SecurityMiddleware] SA 双硬件复核异常: {_e}")
                        _dual_ok, _dual_reason = False, 'provider_error'
                    session['_sa_dual_last_check'] = time.time()
                    session['_sa_dual_reason'] = _dual_reason
                    if not _dual_ok:
                        # 任一硬件拔出或检测失败 → 销毁会话 + 审计告警
                        logger.warning(f"[SecurityMiddleware] SA 双硬件复核失败({_dual_reason})，销毁会话, "
                                      f"ip={request.remote_addr}, ua={request.headers.get('User-Agent', '')[:100]}")
                        session.clear()
                        return {
                            'success': False,
                            'error': 'VIKEY 或 SZU100 认证设备不可用，会话已销毁',
                            'status_code': 401,
                            'sa_dual_hardware_removed': True,
                            'dual_key_reason': _dual_reason,
                        }

            # 基于路径的角色权限检查
            required_role = None
            if '/admin_app/' in path or '/admin_center' in path:
                required_role = ['admin', 'super_admin', 'system_admin']
            elif '/teacher' in path:
                required_role = ['teacher', 'admin', 'super_admin', 'system_admin']
            elif '/designer' in path:
                required_role = ['designer', 'admin', 'super_admin', 'system_admin']

            if required_role:
                user_role = session.get('role')
                if user_role not in required_role:
                    return {
                        'success': False,
                        'error': '权限不足',
                        'status_code': 403
                    }
        else:
            # 未登录用户访问受保护页面 - 重定向到登录页
            # API路径返回JSON错误
            if path.startswith('/api/'):
                return {
                    'success': False,
                    'error': '未登录，请先登录',
                    'status_code': 401
                }
            # 页面路径重定向到首页（首页含登录表单，避免跳到 /auth/login 看到 JSON）
            return {
                'success': False,
                'error': '请先登录',
                'status_code': 302,
                'redirect': '/'
            }

        return None
    
    @staticmethod
    def unlock_user(username):
        if username in LOCKED_USERS:
            del LOCKED_USERS[username]
            return True
        return False
    
    @staticmethod
    def lock_user(username, locked_by='system', duration=900):
        LOCKED_USERS[username] = {
            'locked_at': time.time(),
            'locked_until': time.time() + duration,
            'locked_by': locked_by
        }
        return True
    
    @staticmethod
    def check_user_locked(username):
        if username in LOCKED_USERS:
            lock_info = LOCKED_USERS[username]
            if time.time() < lock_info['locked_until']:
                return lock_info
        return None
    
    @staticmethod
    def record_failed_login(username):
        from app.utils.db import DatabaseManager
        db = DatabaseManager()
        try:
            result = db.fetch_one(
                "SELECT failed_login_count, last_failed_login FROM users WHERE username = ?",
                (username,)
            )
            if result:
                count = result[0] + 1 if result[0] else 1
                db.execute(
                    "UPDATE users SET failed_login_count = ?, last_failed_login = ? WHERE username = ?",
                    (count, datetime.now().isoformat(), username)
                )
                if count >= MAX_FAILED_LOGINS:
                    SecurityMiddlewareClass.lock_user(username, 'failed_logins', 3600)
        except Exception as e:
            logger.error(f"记录登录失败次数失败: {e}")
    
    @staticmethod
    def reset_failed_login(username):
        from app.utils.db import DatabaseManager
        db = DatabaseManager()
        try:
            db.execute(
                "UPDATE users SET failed_login_count = 0, last_failed_login = NULL WHERE username = ?",
                (username,)
            )
            SecurityMiddlewareClass.unlock_user(username)
        except Exception as e:
            logger.error(f"重置登录失败次数失败: {e}")

security_middleware = SecurityMiddlewareClass()
SecurityMiddleware = SecurityMiddlewareClass


# ========== 兼容 modular_start.py 期望的函数式 API ==========
# 提供 register_security_middleware / get_security_status / slow_detector
# 使 from app.middlewares.security_middleware import ... 可正常工作

class _SlowRequestDetector:
    """慢请求检测器（简化实现，内存统计，进程重启后归零）。"""

    def __init__(self):
        self._stats = {
            'total_requests': 0,
            'slow_requests': 0,
            'threshold_ms': 1000,
            'recent_slow': [],
        }

    def record(self, path, duration_ms):
        self._stats['total_requests'] += 1
        if duration_ms > self._stats['threshold_ms']:
            self._stats['slow_requests'] += 1
            entry = {'path': path, 'duration_ms': round(duration_ms, 2),
                     'time': datetime.now().isoformat()}
            self._stats['recent_slow'].append(entry)
            # 仅保留最近 50 条
            if len(self._stats['recent_slow']) > 50:
                self._stats['recent_slow'] = self._stats['recent_slow'][-50:]

    def get_stats(self):
        return dict(self._stats)


# 全局慢请求检测器实例
slow_detector = _SlowRequestDetector()


def register_security_middleware(app):
    """注册安全中间件到 Flask 应用。

    绑定 before_request 处理器，并注入慢请求计时钩子。
    """
    from flask import request, g, jsonify
    import time as _time

    @app.before_request
    def _security_before_request():
        g._req_start = _time.time()
        # ===== §14 v1.3.0 第4层拦截：开发活动前置检查 (MT_IR_D9) =====
        # 在安全验证和规则拦截器之前执行，检测开发活动未走12步骤则立即阻断
        try:
            from flask import request as _req
            if _req.method in ("POST", "PUT", "PATCH", "DELETE"):
                _flow_id = _req.headers.get("X-Flow-Id") or _req.args.get("flow_id")
                _body = _req.get_json(silent=True) or {}
                from ai_engines.rules_engine.dev_activity_preflight import preflight_for_api_route
                _pf = preflight_for_api_route(_req.path, _req.method, _body, _flow_id)
                if not _pf["allowed"]:
                    return jsonify({
                        "success": False,
                        "error": _pf.get("violation", "开发活动前置拦截"),
                        "code": "DEV-FLOW-VIOLATION-IRON-RULE",
                        "rule": "MT_IR_D9",
                        "prompt": _pf.get("prompt", ""),
                    }), 403
        except ImportError:
            pass  # 模块未就绪时不阻断主流程
        except Exception:
            pass  # 前置检查自身错误不影响主流程
        # ===== /§14 v1.3.0 第4层拦截 =====
        result = SecurityMiddlewareClass.before_request_handler()
        if result and isinstance(result, dict):
            status_code = result.get('status_code', 401)
            if status_code == 302 and result.get('redirect'):
                from flask import redirect as _redirect
                return _redirect(result.get('redirect'))
            return jsonify({
                'success': result.get('success', False),
                'error': result.get('error', '安全验证失败'),
                'code': 'CONTAINER_MISSING',
            }), status_code
        return None

    @app.after_request
    def _security_after_request(response):
        from flask import request as _req
        try:
            start = getattr(g, '_req_start', None)
            if start is not None:
                duration_ms = (_time.time() - start) * 1000
                slow_detector.record(_req.path, duration_ms)
                # 注入基础安全响应头
                response.headers.setdefault('X-Content-Type-Options', 'nosniff')
                response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
                response.headers.setdefault('X-XSS-Protection', '1; mode=block')
            # ===== 杨安 AI 安全响应头加固 v2（增量 · 可热回滚）=====
            try:
                apply_security_headers_v2(response, _req)
            except Exception:
                # 加固自身错误不影响响应
                pass
        except Exception:
            pass
        return response

    # 安装敏感字段日志脱敏过滤器（经验1149526：password/token/secret 不能明文进日志）
    try:
        install_sensitive_data_filter()
    except Exception:
        pass
    return True


def get_security_status():
    """获取安全中间件运行状态（用于 /api/security/status）。"""
    return {
        'enabled': True,
        'session_timeout': SESSION_TIMEOUT,
        'warning_timeout': WARNING_TIMEOUT,
        'max_failed_logins': MAX_FAILED_LOGINS,
        'rate_limit': RATE_LIMIT,
        'rate_limit_window': RATE_LIMIT_WINDOW,
        'locked_users_count': len(LOCKED_USERS),
        'slow_requests': slow_detector.get_stats(),
        'hardened_headers_v2': True,
    }


# ======================================================================
# 杨安 AI 安全响应头加固 v2 (GAP3 · YANG-SEC-AUDIT · 对齐 OWASP Secure Headers)
# 6大header全量 + CSP ReportOnly先观察14天 + Permissions-Policy 最小权限 + Cookie 加固
# 经验 1149526：任何安全开关必须可0/1热回滚；生产缺SECURE直接exit(2)
# ======================================================================

# 敏感字段自动脱敏 logging.Filter ：禁止 password/token/secret 以明文进入日志
_SENSITIVE_KEY_PATTERNS = ('password', 'passwd', 'token', 'secret', 'apikey',
                          'api_key', 'private_key', 'vikey', 'authorization', 'cookie')

class SensitiveDataFilter(logging.Filter):
    """
    对 LogRecord 的 msg / args / exc_text 中匹配 SENSITIVE_KEY_PATTERNS 的 key
    将其 value 自动替换为 *** ，避免堆栈或 request log 明文泄漏密钥。
    """
    __slots__ = ("_re",)

    def __init__(self):
        super().__init__()
        import re as _re
        # 匹配形如 key=xxx / "key": "xxx" / key: xxx / key => xxx ，key大小写不敏感
        patterns = '|'.join(_SENSITIVE_KEY_PATTERNS)
        self._re = _re.compile(
            r'(?i)(("?|\')?(' + patterns + r')("?|\')?\s*(?:=>|=|:)\s*)'
            r'("?|\'?)((?:\\.|[^"\',\n}\\])+)("?|\'?)',
        )

    def _mask(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        def _sub(m):
            prefix = m.group(1)
            quote_l = m.group(5)
            value = m.group(6)
            quote_r = m.group(7)
            return prefix + quote_l + ('*' * max(3, min(len(value), 8))) + quote_r
        # safe 最多替换 500 次防ReDoS
        return self._re.sub(_sub, text, count=500)

    def filter(self, record):
        try:
            if isinstance(record.msg, str):
                record.msg = self._mask(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: (self._mask(v) if isinstance(v, str) else v) for k, v in record.args.items()}
                elif isinstance(record.args, (list, tuple)):
                    record.args = type(record.args)(
                        (self._mask(a) if isinstance(a, str) else a) for a in record.args
                    )
            if getattr(record, 'exc_text', None):
                record.exc_text = self._mask(record.exc_text)
            if getattr(record, 'message', None) and isinstance(record.message, str):
                record.message = self._mask(record.message)
        except Exception:
            # Filter 自身异常绝对不能影响业务请求
            pass
        return True


# 模块级一次性安装：对 root logger 与 app.logger 生效（调用方在初始化后再次addFilter也幂等）
def install_sensitive_data_filter():
    """对 root logger / `flask.app` logger / 本模块 logger 安装脱敏过滤器（幂等）。"""
    import logging as _lg
    targets = [_lg.getLogger(), _lg.getLogger('flask.app'), _lg.getLogger(__name__), logger]
    for tgt in targets:
        already = any(isinstance(f, SensitiveDataFilter) for f in tgt.filters)
        if not already:
            tgt.addFilter(SensitiveDataFilter())


def _resolve_header_switch(config_key: str, default_on: bool) -> bool:
    """
    读取 mt_security_switch_config 开关（SA VIIKEY 可热更新），失败时返回 default_on。
    保证：即便 switch 表尚未建，header 也不会崩溃；读取异常使用默认值继续。
    """
    try:
        import sqlite3 as _sq3
        from core.db_path import get_db_path as _gdp
        _conn = _sq3.connect(_gdp("app.db"), timeout=3)
        try:
            row = _conn.execute(
                "SELECT enabled FROM mt_security_switch_config WHERE config_key=?",
                (config_key,)).fetchone()
        finally:
            _conn.close()
        if row is None:
            return bool(default_on)
        return bool(int(row[0]))
    except Exception:
        return bool(default_on)


def apply_security_headers_v2(response, request):
    """
    增量式杨安 AI 安全响应头加固 v2。
    - 所有 header 均使用 response.headers.setdefault，避免重复添加或覆盖业务自定义。
      （如需强制覆盖，可改为 response.headers[xxx]=value）
    - HSTS/CSP/Referrer/XXSS/XContent/XFO/Permissions 7项按开关热生效。
    - Set-Cookie：追加 HttpOnly / SameSite=Lax / Secure(按 request.is_secure 自适应)
    """
    def on(key, default=True): return _resolve_header_switch(key, default)
    try:
        if on('sec_header_xcontenttype', default=True):
            response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        # X-Frame-Options 从 SAMEORIGIN 升级为 DENY（原杨安F1要求：禁止任何iframe嵌入=更安全）
        if on('sec_header_xfo_deny', default=False):
            response.headers['X-Frame-Options'] = 'DENY'
        elif 'X-Frame-Options' not in response.headers:
            response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        if on('sec_header_xxss', default=True):
            response.headers.setdefault('X-XSS-Protection', '1; mode=block')
        if on('sec_header_referrer', default=False):
            response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        # Permissions-Policy 最小权限：摄像头/麦克风/地理位置/支付 默认关（SA/Admin 管理台专用额外禁）
        response.headers.setdefault('Permissions-Policy',
            'camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()')
        # HSTS：仅对 HTTPS(is_secure) 或显式打开开关时生效；HTTP 环境一律跳过以免影响开发
        if on('sec_header_hsts', default=False):
            try:
                secure = bool(getattr(request, 'is_secure', False) or (
                    request.environ.get('HTTP_X_FORWARDED_PROTO', '').lower() == 'https'))
            except Exception:
                secure = False
            if secure:
                response.headers.setdefault('Strict-Transport-Security',
                    'max-age=31536000; includeSubDomains')
        # CSP：ReportOnly 模式先启用 14 天，避免误 CSP 破坏站点；之后再切到强制模式
        if on('sec_header_csp', default=False):
            # nonce 可选（此处预留占位符——若业务端有 per-request nonce 可自行写入）
            response.headers.setdefault('Content-Security-Policy-Report-Only',
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src https: data: blob: 'self'; "
                "font-src data: 'self'; connect-src 'self' https: wss: ws:; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
                "report-uri /api/security/csp-report; report-to csp-endpoint")
        # 追加 X-DNS-Prefetch-Control = off 防 DNS 预取泄露
        response.headers.setdefault('X-DNS-Prefetch-Control', 'off')
        # Set-Cookie SameSite/Lax + HttpOnly + Secure 自适应（对Flask session cookie生效）
        try:
            secure_flag = bool(getattr(request, 'is_secure', False))
            from flask import current_app
            sc = current_app.session_cookie_name if current_app else 'session'
        except Exception:
            secure_flag = False
            sc = 'session'
        cookie_headers = response.headers.getlist('Set-Cookie')
        if cookie_headers:
            try:
                del response.headers['Set-Cookie']
            except Exception:
                pass
            for c in cookie_headers:
                cl = c.lower()
                # SameSite= 已在值上则不重复
                if 'samesite=' not in cl:
                    c = c.rstrip() + '; SameSite=Lax'
                if 'httponly' not in cl and cl.startswith(sc.lower() + '=') is False:
                    # 仅对 session-like 或 flask 写的 token cookie 追加 httponly
                    pass
                # 对任何cookie追加HttpOnly (除非已显式 HttpOnly 不重复)；但 JWT 存 cookie 时也要httpOnly
                if 'httponly' not in cl:
                    c = c.rstrip() + '; HttpOnly'
                if secure_flag and 'secure' not in cl:
                    c = c.rstrip() + '; Secure'
                # Path 缺=/, 追加兼容
                if 'path=' not in cl:
                    c = c.rstrip() + '; Path=/'
                response.headers.add('Set-Cookie', c)
    except Exception:
        # header 加固异常绝对不能干扰响应体；安全中间件应 fail-soft
        pass
    return response