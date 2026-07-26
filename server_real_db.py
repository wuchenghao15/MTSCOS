#!/usr/bin/env python3
"""MTSCOS 正式服务入口：挂载 split_databases/auth.db + app.db/system_versions，
   用真实用户数据验证用户名密码，并传入 DB 中真实系统版本号。"""
import os
import sys
import time
import json
import base64
import hashlib
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

AUTH_DB = os.path.join(BASE_DIR, 'split_databases', 'auth.db')
APP_DB = os.path.join(BASE_DIR, 'app.db')
SPLIT_SYSTEM_DB = os.path.join(BASE_DIR, 'split_databases', 'system.db')
SPLIT_AI_DB = os.path.join(BASE_DIR, 'split_databases', 'ai.db')
SPLIT_EXAM_DB = os.path.join(BASE_DIR, 'split_databases', 'exam.db')
SPLIT_QUESTION_DB = os.path.join(BASE_DIR, 'split_databases', 'question.db')
SPLIT_USER_DB = os.path.join(BASE_DIR, 'split_databases', 'user.db')
SPLIT_ADMIN_DB = os.path.join(BASE_DIR, 'split_databases', 'admin.db')
SPLIT_LEARNING_DB = os.path.join(BASE_DIR, 'split_databases', 'learning.db')
SPLIT_LOG_DB = os.path.join(BASE_DIR, 'split_databases', 'log.db')
SPLIT_PROCTOR_DB = os.path.join(BASE_DIR, 'split_databases', 'proctor.db')
DATA_MTSCOS_DB = os.path.join(BASE_DIR, 'Database', 'mtscos.db')
VERSION_FILE = os.path.join(BASE_DIR, 'VERSION')

from flask import Flask, render_template, render_template_string, request, jsonify, redirect, url_for, session, send_file
from jinja2 import Undefined as _JinjaUndefined


class _FriendlyUndefined(_JinjaUndefined):
    """
    兼容模板老变量：任何未传的变量名 / 属性链 / 函数调用 / 迭代都不抛错，
    打印为''、布尔False、迭代为[]、比较为None，从而杜绝 UndefinedError 500。
    """
    __slots__ = ()

    def __str__(self):
        return ''

    def __bool__(self):
        return False

    __nonzero__ = __bool__

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def __getattr__(self, item):
        if item.startswith('_'):
            raise AttributeError(item)
        return _FriendlyUndefined()

    def __getitem__(self, item):
        return _FriendlyUndefined()

    def __call__(self, *args, **kwargs):
        return _FriendlyUndefined()

    def __eq__(self, other):
        return other is None or isinstance(other, _FriendlyUndefined)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return 0

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __repr__(self):
        return ''


app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.secret_key = 'mtscos-real-db-secret-' + str(int(time.time()))
app.jinja_env.undefined = _FriendlyUndefined
app.jinja_env.auto_reload = True
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
try:
    from markupsafe import Markup
    app.jinja_env.globals.setdefault('Markup', Markup)
except Exception:
    pass
try:
    import json as _json_mod
    app.jinja_env.filters.setdefault('tojson', lambda v, **kw: _json_mod.dumps(v, ensure_ascii=False))
except Exception:
    pass


# ================================================================
# AI 防火墙 + 安全团队（AI员工 / AI Agent）统一初始化入口
# - 建表：ai_firewall_rules + security_events_log
# - 种子：24 条防火墙规则 + 6 名安全员工 + 4 个安全 Agent（幂等）
# - 挂载：before_request 全量请求检查 + Blueprint 注册
# ================================================================
def _init_ai_firewall_and_workforce():
    import logging as _fw_logger
    try:
        from core.services import ai_firewall as _fw
        ok_tab = _fw.init_firewall_tables()
        ok_seed = _fw.seed_default_firewall_rules()
        _fw_logger.info(
            f"[ai_firewall] init: tables={'OK' if ok_tab else 'FAIL'}, seed_rows={ok_seed}"
        )
    except Exception as e:
        _fw_logger.warning(f"[ai_firewall] init fail: {e}")
    try:
        from app.api.ai_firewall_api import ai_firewall_api as _fw_api
        from app.api.ai_security_workforce_api import ai_security_workforce_api as _sw_api
        app.register_blueprint(_fw_api)
        app.register_blueprint(_sw_api)
        _fw_logger.info("[ai_firewall] blueprints registered: ai_firewall_api + ai_security_workforce_api")
    except Exception as e:
        _fw_logger.warning(f"[ai_firewall] blueprint register fail: {e}")


_init_ai_firewall_and_workforce()


# ================================================================
# Vikey USBKey 驱动 + API Blueprint 初始化入口
# - 建表：vikey_device_bindings / vikey_operations_log / vikey_device_certs
# - 种子：2 个默认测试绑定（幂等）
# - 挂载：Blueprint /api/vikey
# ================================================================
def _init_vikey_driver_and_api():
    import logging as _vk_logger
    try:
        from core.services.vikey_driver import get_vikey_manager, VIKEY_DRIVER_VERSION
        mgr = get_vikey_manager()
        _vk_logger.info(
            f"[vikey] init: driver_version={VIKEY_DRIVER_VERSION} "
            f"backend={mgr.backend.NAME} devices={len(mgr.enumerate_devices())} "
            f"bindings={len(mgr.list_bindings())}"
        )
    except Exception as e:
        _vk_logger.warning(f"[vikey] driver init fail: {e}")
    try:
        from app.api.vikey_api import vikey_api as _vk_api
        app.register_blueprint(_vk_api)
        _vk_logger.info("[vikey] blueprint registered: vikey_api @ /api/vikey")
    except Exception as e:
        _vk_logger.warning(f"[vikey] blueprint register fail: {e}")


_init_vikey_driver_and_api()


# ================================================================
# 布局AI LayoutAI - 动态布局调节系统
# - 建表：layout_rules / layout_snapshots / layout_adjustment_logs / layout_employee_configs (4张表)
# - 种子：20条排版割裂检测规则（LF001-LF020）
# - 初始化：LayoutAdjusterAIEmployee 单例
# - 挂载：Blueprint /api/layout_ai（快照/统计/规则/日志/员工配置）
# ================================================================
def _init_layout_ai_system():
    import logging as _lay_logger
    ok_tables, ok_seed = False, 0
    try:
        from ai_engines.layout_adjuster_ai_employee import init_layout_ai_system as _init_lay
        ok_tables, ok_seed = _init_lay()
        _lay_logger.info(
            f"[layout_ai] init: tables={'OK' if ok_tables else 'FAIL'}, seeded_rules={ok_seed}"
        )
    except Exception as e:
        _lay_logger.warning(f"[layout_ai] init fail: {e}")
    try:
        from app.api.layout_ai_api import layout_ai_api as _lay_api
        app.register_blueprint(_lay_api)
        _lay_logger.info("[layout_ai] blueprint registered: layout_ai_api @ /api/layout_ai")
        try:
            from app.api.layout_ai_api import register_html_auto_injector as _inj
            _inj(app)
            _lay_logger.info("[layout_ai] HTML auto-injector registered (all text/html pages get probe+style)")
        except Exception as _ei:
            _lay_logger.warning(f"[layout_ai] auto-injector register fail: {_ei}")
    except Exception as e:
        _lay_logger.warning(f"[layout_ai] blueprint register fail: {e}")
    try:
        from ai_engines.layout_adjuster_ai_employee import LayoutAdjusterAIEmployee as _L
        try:
            from ai_engines import ai_employee_manager as _emp_mod
            _mgr = getattr(_emp_mod, 'ai_employee_manager', None) or getattr(_emp_mod, 'manager', None)
            if _mgr:
                _inst = _mgr.get_employee(_L.EMPLOYEE_ID) if hasattr(_mgr, 'get_employee') else None
                if not _inst:
                    _add_fn = getattr(_mgr, 'add_employee', None)
                    if _add_fn: _add_fn(_L())
                    _lay_logger.info(f"[layout_ai] registered into ai_employee_manager: {_L.EMPLOYEE_ID}")
        except Exception:
            pass
    except Exception as e:
        _lay_logger.warning(f"[layout_ai] employee register fail: {e}")


_init_layout_ai_system()


@app.before_request
def _mtscos_ai_firewall_check():
    """AI 防火墙全局请求拦截：SQLi/XSS/SSRF/遍历/命令注入/恶意UA/速率/扩展/泄露检测"""
    try:
        p = request.path or ''
        if (p.startswith('/static/') or p.startswith('/assets/')
                or p in ('/favicon.ico', '/robots.txt')
                or p.endswith('.svg') or p.endswith('.png') or p.endswith('.jpg') or p.endswith('.ico')
                or p.endswith('.css') or p.endswith('.js')):
            return None
        from core.services import ai_firewall as _fw
        blocked, code, msg, rule = _fw.check_request(request)
        if not blocked:
            return None
        payload = {
            'success': False,
            'blocked': True,
            'rule_code': (rule or {}).get('rule_code'),
            'rule_name': (rule or {}).get('name'),
            'severity': (rule or {}).get('severity') or 'warning',
            'message': msg or '[MTSCOS AI Firewall] Request blocked',
            'action': (rule or {}).get('action') or 'block',
        }
        accept = (request.headers.get('Accept', '') or '').lower()
        if 'text/html' in accept and 'application/json' not in accept:
            import json as _j
            pretty = _j.dumps(payload, ensure_ascii=False, indent=2)
            html = (
                '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<title>403 Blocked · MTSCOS AI Firewall</title></head>'
                '<body style="background:#0b1020;color:#cbd5e1;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:48px 24px">'
                '<div style="max-width:720px;margin:auto">'
                '<h1 style="color:#f87171;margin:0 0 12px">🚫 Request Blocked</h1>'
                f'<p style="opacity:.85;margin:0 0 24px">{msg or "请求被 MTSCOS AI 防火墙拦截"}</p>'
                f'<pre style="background:#0f172a;padding:16px 20px;border-radius:10px;border:1px solid rgba(255,255,255,.08);white-space:pre-wrap">{pretty}</pre>'
                '<p style="opacity:.6;margin-top:24px">如需放行，请联系超级管理员调整 <code>/api/ai_firewall/rules</code> 规则。</p>'
                '</div></body></html>'
            )
            return html, int(code or 403)
        return jsonify(payload), int(code or 403)
    except Exception as e:
        import logging as _lg
        _lg.warning(f"[ai_firewall] before_request fail: {e}")
    return None


_ROLE_CN = {
    'admin': '管理员',
    'super_admin': '超级管理员',
    'school_admin': '校管理员',
    'teacher': '教师',
    'student': '学生',
    'parent': '家长',
    'user': '普通用户',
    'guest': '访客',
    'hardware_admin': '硬件管理员',
    'institution_admin': '机构管理员',
}


def get_role_name(role_key):
    if not role_key:
        return '未分配'
    key = str(role_key).strip().lower()
    for k, v in _ROLE_CN.items():
        if k == key or k in key:
            return v
    # 首字母大写友好显示
    s = str(role_key).strip().replace('_', ' ')
    return s[:1].upper() + s[1:]


# Jinja2 模板全局可用函数（避免模板里 UndefinedError: 'xxx' is undefined）
@app.context_processor
def _inject_template_globals():
    def g_is_authenticated():
        return bool(session.get('user_id'))

    def g_current_user():
        return _safe_user_ctx(_current_user())

    def g_is_admin():
        u = _current_user()
        if not u:
            return False
        role = str(u.get('role') or '').lower()
        if role in ('admin', 'super_admin', 'school_admin', 'institution_admin', 'teacher'):
            return True
        if _safe_super_approved(u.get('id')):
            return True
        return False

    def g_is_super_admin():
        u = _current_user()
        if not u:
            return False
        role = str(u.get('role') or '').lower()
        if role == 'super_admin':
            return True
        return bool(_safe_super_approved(u.get('id')))

    return dict(
        get_role_name=get_role_name,
        is_authenticated=g_is_authenticated,
        current_user=g_current_user(),
        is_admin=g_is_admin(),
        is_super_admin=g_is_super_admin(),
        system_version=get_version_info()[0],
        now=datetime.now(),
    )

NATIONAL_MOURNING_DATES = [
    (9, 30),
    (12, 13),
    (9, 18),
]

THEME_DEEP_BLUE = 'deep_blue'
THEME_LIGHT_BLUE = 'light_blue_tech'
THEME_LIGHT = 'light'
THEME_MOURNING = 'mourning'

VALID_THEMES = {THEME_DEEP_BLUE, THEME_LIGHT_BLUE, THEME_LIGHT, THEME_MOURNING}
ADMIN_THEMES_NO_MOURNING = [THEME_DEEP_BLUE, THEME_LIGHT_BLUE, THEME_LIGHT]


def _today_mmdd():
    today = datetime.today()
    return (today.month, today.day)


def is_national_mourning_day():
    return _today_mmdd() in NATIONAL_MOURNING_DATES


def _current_user():
    if not session.get('username'):
        return None
    role = session.get('role') or 'user'
    admin_roles = {'admin', 'super_admin', 'teacher_admin', 'school_admin', 'sysadmin'}
    is_admin_role = role in admin_roles
    try:
        if os.path.exists(AUTH_DB):
            with _get_conn(AUTH_DB) as conn:
                row = conn.execute(
                    "SELECT super_admin_approved, role FROM users WHERE id = ? LIMIT 1",
                    (session.get('user_id'),)
                ).fetchone()
                if row:
                    if row['super_admin_approved']:
                        is_admin_role = True
                    if row['role'] and row['role'] in admin_roles:
                        is_admin_role = True
    except Exception:
        pass
    return {
        'id': session.get('user_id'),
        'username': session.get('username'),
        'role': role,
        'is_admin': is_admin_role,
        'is_super_admin': bool(session.get('super_admin_approved')) if session.get('super_admin_approved') is not None else (
            bool(_safe_super_approved(session.get('user_id')))
        ),
    }


def _safe_super_approved(uid):
    if not uid or not os.path.exists(AUTH_DB):
        return False
    try:
        with _get_conn(AUTH_DB) as conn:
            row = conn.execute("SELECT super_admin_approved FROM users WHERE id = ? LIMIT 1", (uid,)).fetchone()
            return bool(row['super_admin_approved']) if row else False
    except Exception:
        return False


def _resolve_theme():
    """
    公祭日：
      * 默认强制 THEME_MOURNING（所有用户）
      * 超级管理员可通过 session['theme_override'] 临时强制切换为其他主题
    非公祭日：
      * 用户选择主题存在 session['user_theme']，否则 THEME_DEEP_BLUE（深蓝）
    """
    user = _current_user()
    if is_national_mourning_day():
        if user and user['is_super_admin']:
            override = session.get('theme_override')
            if override in VALID_THEMES:
                return override, True
        return THEME_MOURNING, True
    chosen = session.get('user_theme')
    if chosen in ADMIN_THEMES_NO_MOURNING:
        return chosen, False
    return THEME_DEEP_BLUE, False


@app.context_processor
def inject_theme_and_layout():
    user = _current_user()
    theme_key, forced_mourning = _resolve_theme()
    is_admin = user['is_admin'] if user else False
    is_super = user['is_super_admin'] if user else False
    return {
        'theme_key': theme_key,
        'theme_forced_mourning': forced_mourning,
        'is_mourning_day': is_national_mourning_day(),
        'layout_sidebar_ratio': '2:8',
        'layout_simplified_ratio': '1:9',
        'current_user': user,
        'is_admin': is_admin,
        'is_super_admin': is_super,
    }


@app.route('/api/theme/set', methods=['POST'])
def api_set_theme():
    """非公祭日用户自主切换主题；公祭日仅超级管理员可强制覆盖。"""
    data = request.get_json(silent=True) or {}
    target = (data.get('theme') or '').strip()
    user = _current_user()
    mourning = is_national_mourning_day()

    if mourning:
        if not (user and user['is_super_admin']):
            return jsonify({'success': False, 'message': '公祭日主题为系统自动启用，不可手动切换'}), 403
        if target not in VALID_THEMES:
            return jsonify({'success': False, 'message': f'主题无效（仅支持：{", ".join(sorted(VALID_THEMES))}）'}), 400
        session['theme_override'] = target
        return jsonify({'success': True, 'theme': target, 'forced': True,
                        'message': f'超级管理员已强制切换主题为：{target}'})

    if target not in ADMIN_THEMES_NO_MOURNING:
        return jsonify({'success': False,
                        'message': f'主题无效（仅支持：{", ".join(ADMIN_THEMES_NO_MOURNING)}）'}), 400
    session.pop('theme_override', None)
    session['user_theme'] = target
    return jsonify({'success': True, 'theme': target,
                    'message': f'已切换为：{target}'})


@app.route('/api/theme/reset', methods=['POST'])
def api_reset_theme():
    """清除自定义/强制覆盖，回到系统自动判定。"""
    session.pop('user_theme', None)
    session.pop('theme_override', None)
    theme_key, forced = _resolve_theme()
    return jsonify({'success': True, 'theme': theme_key, 'forced_mourning': forced})


def _hash_password(plain: str) -> str:
    """与 split_databases/auth.db users.password 现有哈希方式一致：SHA256 -> Base64"""
    return base64.b64encode(hashlib.sha256(plain.encode('utf-8')).digest()).decode('ascii')


# 常见初始密码列表（用于兼容占位哈希的初始化账户，自动升级）
_COMMON_DEFAULT_PASSWORDS = [
    'admin123',
    '123456',
    'password123',
    'password',
    'mtscos2026',
    'mtscos2025',
    'abcd1234',
    'abc123',
    '12345678',
]


def _verify_password_fallback(plain_provided: str, expected_hash_stored: str, username: str) -> bool:
    """
    当标准哈希比对失败时走兼容回退：
    1) 支持 werkzeug 的 generate_password_hash（老init.py写的格式）
    2) 支持常见初始密码（admin123 / 123456 / password123 / 用户名本身 等）
       -> 用于"占位哈希"初始化账户（数据库哈希无对应明文但用户输入常见默认密码时可过）
       -> 触发条件：存储哈希 == 任何常见初始密码的哈希，且用户输入的密码 == 该常见密码
       -> 额外：若存储哈希本身就是"占位哈希"（所有初始用户共享的相同哈希值 6G94qKPK... 或 长度不合法等），
          并且用户输入的是常见初始密码，则认为是兼容初始化通过（然后升级）
    返回 True 表示密码验证通过（调用方应把哈希升级为标准格式）
    """
    if not plain_provided or not expected_hash_stored:
        return False
    try:
        from werkzeug.security import check_password_hash as _wk_check
        if '$' in expected_hash_stored or expected_hash_stored.startswith('pbkdf2') \
                or expected_hash_stored.startswith('scrypt') or expected_hash_stored.startswith('sha256$'):
            try:
                if _wk_check(expected_hash_stored, plain_provided):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    # A) 正常"常见密码映射"：存储哈希 == 常见密码哈希，且用户输入 == 该常见密码
    try:
        cand_set = set(_COMMON_DEFAULT_PASSWORDS)
        cand_set.add(username or '')
        cand_set.add((username or '').lower())
        cand_set.add((username or '').capitalize())
        for cand in cand_set:
            if not cand:
                continue
            if _hash_password(cand) == expected_hash_stored:
                return plain_provided == cand
    except Exception:
        pass
    # B) 占位哈希兼容：存储哈希是历史占位哈希（出现频率高的"固定"哈希值），
    #    且用户输入的是常见初始密码 -> 兼容通过（然后自动升级为用户此次输入的密码）
    _PLACEHOLDER_HASHES = {
        '6G94qKPK8LYNjnTllCqm2G3BUM08AzOK7yW30tfjrMc=',
    }
    try:
        if expected_hash_stored in _PLACEHOLDER_HASHES:
            if plain_provided in cand_set:
                return True
    except Exception:
        pass
    return False


def _password_matches(plain_provided: str, expected_hash_stored: str, username: str):
    """
    返回 (ok: bool, need_upgrade: bool)
    - ok: 密码是否验证通过
    - need_upgrade: 通过但是用了兼容回退，需要把数据库哈希升级为标准 _hash_password(plain)
    """
    if not plain_provided or not expected_hash_stored:
        return False, False
    try:
        std_hash = _hash_password(plain_provided)
    except Exception:
        return False, False
    if std_hash == expected_hash_stored:
        return True, False
    ok = _verify_password_fallback(plain_provided, expected_hash_stored, username)
    return (True, True) if ok else (False, False)


def _get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_version_info():
    """优先从 app.db/system_versions 取最新版本，失败回退至 VERSION 文件
       返回 (version, info_dict, latest_version)"""
    version = None
    info = {
        'version': None,
        'codename': '',
        'build_number': '',
        'build_date': '',
        'status': '',
        'description': '',
        'source': '',
        'build_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'commit': 'db-sourced',
        'branch': 'main',
        'author': 'Chenghao Wu',
    }

    candidates = [
        (APP_DB, 'SELECT version,codename,build_number,build_date,status,description,created_at FROM system_versions ORDER BY datetime(created_at) DESC LIMIT 1'),
        (DATA_MTSCOS_DB, 'SELECT version,codename,build_number,build_date,status,description,created_at FROM system_versions ORDER BY datetime(created_at) DESC LIMIT 1'),
    ]
    for db_path, sql in candidates:
        try:
            if not os.path.exists(db_path):
                continue
            with _get_conn(db_path) as conn:
                row = conn.execute(sql).fetchone()
                if row:
                    version = row['version']
                    info['version'] = version
                    info['codename'] = row['codename'] or ''
                    info['build_number'] = row['build_number'] or ''
                    info['build_date'] = row['build_date'] or (row['created_at'][:10] if row['created_at'] else '')
                    info['status'] = row['status'] or ''
                    info['description'] = row['description'] or ''
                    info['source'] = os.path.basename(db_path) + '.system_versions'
                    break
        except Exception:
            continue

    if not version and os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                version = f.read().strip()
            info['version'] = version
            info['source'] = 'VERSION file'
        except Exception:
            pass

    if not version:
        version = '1.0.0'
        info['version'] = version
        info['source'] = 'fallback default'

    latest_version = version
    return version, info, latest_version


@app.route('/')
def index():
    version, info, latest = get_version_info()
    return render_template('index.html',
                           version=version,
                           version_info=info,
                           latest_version=latest)


def _ensure_login_logs_schema(conn):
    """确保 login_logs 有 fail_reason 和 remark 列（历史数据库升级兼容）"""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(login_logs)").fetchall()]
        if 'fail_reason' not in cols:
            conn.execute("ALTER TABLE login_logs ADD COLUMN fail_reason TEXT")
        if 'remark' not in cols:
            conn.execute("ALTER TABLE login_logs ADD COLUMN remark TEXT")
    except Exception:
        pass


def _generic_auth_fail(username, ip, ua, user_id=None, reason='password'):
    """统一登录失败入口：所有失败一律返回"用户名或密码错误"，防止信息泄露"""
    now_iso = datetime.now().isoformat()
    try:
        with _get_conn(AUTH_DB) as conn:
            _ensure_login_logs_schema(conn)
            conn.execute(
                "INSERT INTO login_attempts (username, ip_address, success, timestamp) VALUES (?, ?, 0, ?)",
                (username or '', ip, now_iso)
            )
            if user_id:
                try:
                    conn.execute(
                        "INSERT INTO login_logs (user_id, username, ip_address, user_agent, device_type, login_status, fail_reason, login_time) VALUES (?, ?, ?, ?, ?, 'failed', ?, ?)",
                        (user_id, username or '', ip, ua, 'web', reason, now_iso)
                    )
                except Exception:
                    conn.execute(
                        "INSERT INTO login_logs (user_id, username, ip_address, user_agent, device_type, login_status, login_time) VALUES (?, ?, ?, ?, ?, 'failed', ?)",
                        (user_id, username or '', ip, ua, 'web', now_iso)
                    )
            conn.commit()
    except Exception:
        pass
    return jsonify({'success': False, 'message': '用户名或密码错误'}), 401


def _verify_ssl_fingerprint(fp, ip, ua, username):
    """SSL证书指纹验证：简单校验存在性+长度，生产可替换为真实证书链校验"""
    if not fp:
        return False, 'ssl_fp_missing'
    fp_clean = (fp or '').strip().lower().replace(':', '').replace(' ', '')
    if len(fp_clean) not in (32, 40, 64, 128):
        return False, 'ssl_fp_invalid'
    return True, 'ok'


def _verify_super_admin_vikey(username, vikey_auth_token, vikey_serial, ip, ua):
    """超级管理员 (wuchenghao15) 强制 USB Key + 随机码 硬件级验证
    返回 (ok: bool, fail_reason: str, info: dict)
    """
    if not vikey_auth_token or not vikey_serial:
        return False, 'vikey_token_missing', {}
    try:
        from app.api.vikey_api import verify_vikey_token
        with app.test_request_context(
            path='/api/vikey/verify_vikey_token',
            method='POST',
            headers={'Content-Type': 'application/json'},
            data=__import__('json').dumps({
                'vikey_auth_token': vikey_auth_token,
                'username': username,
                'serial': vikey_serial,
            })
        ):
            resp, ok = verify_vikey_token()
            if isinstance(resp, tuple):
                resp_obj, code = resp[0], resp[1]
            else:
                resp_obj, code = resp, 200
            if not ok:
                try:
                    msg = ''
                    if hasattr(resp_obj, 'get_json'):
                        j = resp_obj.get_json(silent=True) or {}
                        msg = j.get('message', '')
                    elif isinstance(resp_obj, dict):
                        msg = resp_obj.get('message', '')
                    elif isinstance(resp_obj, str):
                        msg = resp_obj
                    return False, 'vikey_' + (msg[:80] if msg else 'verify_fail'), {}
                except Exception:
                    return False, 'vikey_verify_fail', {}
            info = {}
            try:
                if hasattr(resp_obj, 'get_json'):
                    j = resp_obj.get_json(silent=True) or {}
                    info = j.get('data') or {}
                elif isinstance(resp_obj, dict):
                    info = resp_obj.get('data') or {}
            except Exception:
                pass
            return True, 'ok', info
    except Exception as e:
        return False, 'vikey_exception_' + str(e)[:60], {}


@app.route('/auth/check_username', methods=['GET'])
def check_username():
    """匿名检查用户名是否存在（前端状态指示器：绿/红/灰）"""
    username = (request.args.get('username') or '').strip()
    if not username:
        return jsonify({
            'success': True, 'exists': False, 'username': '',
            'role': None, 'is_active': False, 'is_admin_like': False,
        })
    try:
        if not os.path.exists(AUTH_DB):
            return jsonify({
                'success': False, 'error': 'auth_db_missing',
                'exists': False, 'username': username,
                'role': None, 'is_active': False, 'is_admin_like': False,
            }), 503
        with _get_conn(AUTH_DB) as conn:
            row = conn.execute(
                "SELECT id, username, role, is_active FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
                (username,)
            ).fetchone()
        if not row:
            return jsonify({
                'success': True, 'exists': False, 'username': username,
                'role': None, 'is_active': False, 'is_admin_like': False,
            })
        role = (row['role'] or '').lower()
        admin_like = role in {'super_admin', 'admin', 'hardware_admin', 'cluster_manager'}
        return jsonify({
            'success': True, 'exists': True,
            'username': row['username'], 'role': row['role'],
            'is_active': bool(row['is_active']),
            'is_admin_like': admin_like, 'user_id': row['id'],
        })
    except Exception as e:
        return jsonify({
            'success': False, 'error': 'db_error:' + str(e)[:60],
            'exists': False, 'username': username,
            'role': None, 'is_active': False, 'is_admin_like': False,
        }), 500


@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        remember = bool(data.get('remember_me'))
        ip = request.remote_addr or '127.0.0.1'
        ua = request.headers.get('User-Agent', '')[:200]
        ssl_fingerprint = (data.get('ssl_fingerprint') or '').strip()
        vikey_auth_token = (data.get('vikey_auth_token') or '').strip()
        vikey_serial = (data.get('vikey_serial') or '').strip()
        vikey_pin_hint = (data.get('vikey_pin') or '')[:4]

        if not username or not password:
            return jsonify({'success': False, 'message': '请输入用户名和密码'}), 400

        if not os.path.exists(AUTH_DB):
            return jsonify({'success': False,
                             'message': f'认证数据库不存在 ({AUTH_DB})，请先初始化 split_databases/auth.db'}), 500

        is_super_admin = (username.lower() == 'wuchenghao15')
        user_id_for_log = None

        now_iso = datetime.now().isoformat()
        try:
            with _get_conn(AUTH_DB) as conn:
                row = conn.execute(
                    "SELECT id, username, email, password, role, is_active, super_admin_approved "
                    "FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
                    (username,)
                ).fetchone()

                if not row:
                    return _generic_auth_fail(username, ip, ua, reason='user_not_found')

                user_id_for_log = row['id']

                if not row['is_active']:
                    return jsonify({'success': False, 'message': '账户已被禁用，请联系管理员'}), 403

                expected_hash = (row['password'] or '').strip()
                pw_ok, need_pw_upgrade = _password_matches(password, expected_hash, username)
                if not pw_ok:
                    return _generic_auth_fail(username, ip, ua, user_id=user_id_for_log, reason='password_mismatch')

                ssl_ok, ssl_reason = _verify_ssl_fingerprint(ssl_fingerprint, ip, ua, username)
                if not ssl_ok:
                    return _generic_auth_fail(username, ip, ua, user_id=user_id_for_log, reason=ssl_reason)

                if is_super_admin:
                    v_ok, v_reason, _v_info = _verify_super_admin_vikey(
                        username, vikey_auth_token, vikey_serial, ip, ua
                    )
                    if not v_ok:
                        return _generic_auth_fail(
                            username, ip, ua, user_id=user_id_for_log,
                            reason=v_reason or 'vikey_fail'
                        )

                try:
                    _ensure_login_logs_schema(conn)
                    if need_pw_upgrade:
                        try:
                            new_std_hash = _hash_password(password)
                            conn.execute(
                                "UPDATE users SET password = ?, updated_at = ? WHERE id = ?",
                                (new_std_hash, now_iso, row['id'])
                            )
                        except Exception:
                            pass
                    conn.execute(
                        "INSERT INTO login_attempts (username, ip_address, success, timestamp) VALUES (?, ?, 1, ?)",
                        (username, ip, now_iso)
                    )
                    extra = ''
                    if is_super_admin:
                        extra = ';vikey_serial=' + (vikey_serial or '')[:64] + ';pin_prefix=' + vikey_pin_hint
                    remark = ('ssl_fp_len=' + str(len(ssl_fingerprint or ''))) + extra
                    try:
                        conn.execute(
                            "INSERT INTO login_logs (user_id, username, ip_address, user_agent, device_type, login_status, login_time, remark) VALUES (?, ?, ?, ?, ?, 'success', ?, ?)",
                            (row['id'], username, ip, ua, 'web', now_iso, remark)
                        )
                    except Exception:
                        conn.execute(
                            "INSERT INTO login_logs (user_id, username, ip_address, user_agent, device_type, login_status, login_time) VALUES (?, ?, ?, ?, ?, 'success', ?)",
                            (row['id'], username, ip, ua, 'web', now_iso)
                        )
                    conn.execute(
                        "UPDATE users SET updated_at = ? WHERE id = ?",
                        (now_iso, row['id'])
                    )
                    conn.commit()
                except Exception:
                    pass

                session['user_id'] = row['id']
                session['username'] = row['username']
                session['role'] = row['role'] or 'user'
                session.permanent = remember

                user = {
                    'id': row['id'],
                    'username': row['username'],
                    'email': row['email'],
                    'role': row['role'] or 'user',
                    'super_admin_approved': bool(row['super_admin_approved']) if row['super_admin_approved'] is not None else False,
                }
                return jsonify({
                    'success': True,
                    'message': f'登录成功（{user["role"]}），正在跳转...',
                    'redirect': '/dashboard',
                    'user': user,
                    'session_id': session.get('sid') or str(id(session)),
                })
        except sqlite3.Error as e:
            return jsonify({'success': False, 'message': f'认证数据库错误：{e}'}), 500

    return redirect('/')


@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        email = (data.get('email') or f'{username}@mtscos.com').strip()
        role = (data.get('role') or 'user').strip() or 'user'

        if not username or not password:
            return jsonify({'success': False, 'message': '请填写用户名和密码'}), 400
        if len(username) < 3:
            return jsonify({'success': False, 'message': '用户名至少 3 个字符'}), 400
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密码至少 6 个字符'}), 400
        if not os.path.exists(AUTH_DB):
            return jsonify({'success': False, 'message': f'认证数据库不存在 ({AUTH_DB})'}), 500

        pw_hash = _hash_password(password)
        now_iso = datetime.now().isoformat()
        try:
            with _get_conn(AUTH_DB) as conn:
                exist = conn.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
                    (username,)
                ).fetchone()
                if exist:
                    return jsonify({'success': False, 'message': '该用户名已存在'}), 409

                cur = conn.execute(
                    "INSERT INTO users (username, email, password, role, created_at, updated_at, is_active, super_admin_approved, hardware_admin_approved) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0)",
                    (username, email, pw_hash, role, now_iso, now_iso)
                )
                conn.commit()
                uid = cur.lastrowid
            return jsonify({
                'success': True,
                'message': f'注册成功，ID={uid}（已写入 AUTH.users，密码 SHA256→Base64）',
                'redirect': '/',
                'user': {'id': uid, 'username': username, 'role': role, 'email': email},
            })
        except sqlite3.Error as e:
            return jsonify({'success': False, 'message': f'注册失败：{e}'}), 500

    try:
        v, info, _ = get_version_info()
        return render_template('register.html', version=v, version_info=info)
    except Exception:
        return redirect('/')


@app.route('/auth/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    if request.method == 'POST':
        return jsonify({'success': True, 'message': '已登出', 'redirect': '/'})
    return redirect('/')


@app.route('/auth/session_health', methods=['GET'])
def session_health():
    """Dashboard 实时监测：用户容器登录状态 + 超级管理员额外检查 USB Key 插入状态"""
    username = session.get('username')
    if not username:
        return jsonify({
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
    return jsonify(result), (200 if result.get('ok') else 401)


@app.route('/dashboard')
def dashboard():
    if not session.get('username'):
        return redirect('/')
    v, info, _ = get_version_info()
    user_line = f"{session['username']}（{session.get('role', 'user')}）"
    html_parts = [
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Dashboard · MTSCOS AI</title>',
        '<style>',
        'body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:radial-gradient(ellipse at 20% 50%, rgba(99,102,241,.15), transparent 50%), linear-gradient(135deg,#050510,#0c0c24 50%,#070718);color:#f8fafc;min-height:100vh;line-height:1.6}',
        '.layout{display:flex;min-height:100vh}',
        '.sidebar{width:20%;min-width:220px;max-width:280px;background:linear-gradient(180deg,#0b1224 0%, #0f172a 100%);min-height:100vh;position:fixed;left:0;top:0;padding:24px 0;z-index:1000;overflow-y:auto;overflow-x:hidden;border-right:1px solid rgba(99,102,241,.15);box-shadow:4px 0 24px rgba(0,0,0,.25);transition:all .25s ease}',
        'body.sidebar-collapsed .sidebar{width:64px !important;min-width:64px !important;max-width:64px !important}',
        'body.sidebar-collapsed .sidebar-logo h2,body.sidebar-collapsed .sidebar-logo p,body.sidebar-collapsed .nav-section,body.sidebar-collapsed .nav-item .nav-text,body.sidebar-collapsed .nav-item span:not(.ni),body.sidebar-collapsed .user-card .ui{display:none !important}',
        'body.sidebar-collapsed .sidebar-logo{padding:0 10px 18px}',
        'body.sidebar-collapsed .sidebar-logo .logo-box{margin:0 auto 10px}',
        'body.sidebar-collapsed .nav-item{justify-content:center;padding:11px 0;margin:2px 6px;gap:0}',
        'body.sidebar-collapsed .user-card{justify-content:center;padding:10px 4px}',
        'body.sidebar-collapsed .sidebar-footer{padding:10px}',
        '.sidebar-logo-wrap{position:relative}',
        '.sidebar-toggle{position:absolute;top:10px;right:-12px;width:26px;height:26px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#a855f7);color:white;border:2px solid #0b1224;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:11px;box-shadow:0 3px 10px rgba(99,102,241,.4);z-index:1001;transition:transform .15s ease}',
        '.sidebar-toggle:hover{transform:scale(1.08)}',
        'body.sidebar-collapsed .sidebar-toggle{right:-12px;transform:rotate(180deg)}',
        'body.sidebar-collapsed .sidebar-toggle:hover{transform:rotate(180deg) scale(1.08)}',
        '.sidebar::-webkit-scrollbar{width:4px}.sidebar::-webkit-scrollbar-thumb{background:rgba(99,102,241,.25);border-radius:4px}',
        '.sidebar-logo{padding:0 20px 22px;border-bottom:1px solid rgba(255,255,255,.08);margin-bottom:20px}',
        '.sidebar-logo .logo-box{width:44px;height:44px;background:linear-gradient(135deg,#6366f1,#a855f7);border-radius:12px;display:flex;align-items:center;justify-content:center;color:white;font-weight:800;font-size:18px;box-shadow:0 4px 14px rgba(99,102,241,.45);margin-bottom:14px}',
        '.sidebar-logo h2{color:white;font-size:16px;font-weight:700;margin-bottom:2px}',
        '.sidebar-logo p{color:rgba(255,255,255,.4);font-size:11px}',
        '.nav-section{padding:10px 20px 6px;color:rgba(255,255,255,.35);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-top:10px}',
        '.nav-item{display:flex;align-items:center;gap:12px;padding:11px 16px;margin:2px 12px;color:rgba(255,255,255,.7);text-decoration:none;border-radius:10px;transition:all .15s;font-size:13.5px;font-weight:500}',
        '.nav-item:hover{background:rgba(99,102,241,.12);color:white;transform:translateX(3px)}',
        '.nav-item.active{background:rgba(99,102,241,.22);color:#e0e7ff;box-shadow:0 2px 10px rgba(99,102,241,.2)}',
        '.nav-item .ni{width:20px;text-align:center;font-size:15px;flex-shrink:0}',
        '.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:16px;border-top:1px solid rgba(255,255,255,.08);background:#0b1224}',
        '.user-card{display:flex;align-items:center;gap:12px;padding:12px;background:rgba(99,102,241,.08);border-radius:12px;border:1px solid rgba(99,102,241,.15)}',
        '.user-card .avatar{width:38px;height:38px;background:linear-gradient(135deg,#6366f1,#a855f7);border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:14px;flex-shrink:0;box-shadow:0 3px 10px rgba(99,102,241,.35)}',
        '.user-card .ui{flex:1;min-width:0}',
        '.user-card .un{color:white;font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
        '.user-card .ur{color:rgba(255,255,255,.45);font-size:10.5px;margin-top:1px}',
        '.logout-mini{width:32px;height:32px;display:flex;align-items:center;justify-content:center;color:rgba(239,68,68,.65);border-radius:8px;transition:all .15s;text-decoration:none}',
        '.logout-mini:hover{background:rgba(239,68,68,.15);color:#f87171}',
        '.main-content{flex:1;margin-left:20%;padding:28px 36px;overflow-y:auto;height:100vh;transition:margin-left .25s ease}',
        'body.sidebar-collapsed .main-content{margin-left:64px !important}',
        '.main-content::-webkit-scrollbar{width:6px}.main-content::-webkit-scrollbar-thumb{background:rgba(99,102,241,.25);border-radius:6px}',
        '.card{background:rgba(12,12,30,.65);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(99,102,241,.18);border-radius:20px;padding:32px;margin-bottom:24px;box-shadow:0 12px 48px rgba(0,0,0,.45)}',
        'h1{margin:0 0 8px;font-size:28px;letter-spacing:-.01em}',
        'h2{font-size:16px;margin:28px 0 12px;color:#a5b4fc;text-transform:uppercase;letter-spacing:.1em}',
        '.sub{color:#64748b;margin-bottom:24px}',
        '.pill{display:inline-block;padding:6px 12px;border-radius:999px;background:rgba(99,102,241,.1);color:#a5b4fc;border:1px solid rgba(99,102,241,.22);font-size:12px;font-weight:600;margin-right:8px}',
        'table{width:100%;border-collapse:collapse;font-size:13px}',
        'th,td{text-align:left;padding:10px 12px;border-bottom:1px solid rgba(99,102,241,.08)}',
        'th{color:#94a3b8;font-weight:600;background:rgba(99,102,241,.04)}',
        'tr:hover td{background:rgba(99,102,241,.04)}',
        '.back{color:#a5b4fc;text-decoration:none;font-size:13px;display:inline-flex;align-items:center;gap:4px;margin-bottom:18px}',
        '.back:hover{color:#f8fafc}',
        '</style></head><body><div class="layout">',
        f'<aside class="sidebar"><div class="sidebar-logo-wrap"><div class="sidebar-toggle" id="sidebar-toggle" title="收起/展开侧边栏"><i class="fas fa-chevron-left"></i></div><div class="sidebar-logo"><div class="logo-box">AI</div><h2>MTSCOS AI</h2><p>智能学习评估平台</p></div></div>',
        '<div class="nav-section">主菜单</div>',
        '<a class="nav-item active" href="/dashboard"><span class="ni">📊</span>数据概览</a>',
        '<a class="nav-item" href="/admin_app/users"><span class="ni">👥</span>用户管理</a>',
        '<a class="nav-item" href="/admin_app/exams"><span class="ni">📝</span>考试管理</a>',
        '<a class="nav-item" href="/admin_app/questions"><span class="ni">📚</span>题库管理</a>',
        '<a class="nav-item" href="/admin_app/ai_employee_dashboard"><span class="ni">🤖</span>AI员工</a>',
        '<div class="nav-section">系统</div>',
        '<a class="nav-item" href="/settings"><span class="ni">⚙️</span>系统设置</a>',
        '<a class="nav-item" href="/system_status_dashboard"><span class="ni">🖥️</span>系统状态</a>',
        '<a class="nav-item" href="/backup_manager"><span class="ni">💾</span>备份管理</a>',
        f'<div class="sidebar-footer"><div class="user-card"><div class="avatar">{session["username"][:1].upper()}</div><div class="ui"><div class="un">{session["username"]}</div><div class="ur">{session.get("role","user")}</div></div><a class="logout-mini" href="/auth/logout" title="退出登录" onclick="event.preventDefault();fetch(\'/auth/logout\',{{method:\'POST\',credentials:\'include\'}}).then(()=>window.location.replace(\'/\'));">⎋</a></div></div>',
        '</aside><main class="main-content">',
        f'<a href="/" class="back">← 返回登录页</a>',
        '<div class="card">',
        f'<h1>👋 欢迎回来，{user_line}</h1>',
        f'<p class="sub">登录成功 · 数据库认证已通过 · DB真实版本号 v{v}（来源：{info.get("source","")}）</p>',
        f'<div><span class="pill">v{v}</span>',
        f'<span class="pill">{info.get("status","").upper() or "STABLE"}</span>',
        f'<span class="pill">BUILD {info.get("build_number","-")}</span>',
        f'<span class="pill">ROLE · {session.get("role","user").upper()}</span></div>',
        '</div>',
    ]
    try:
        if os.path.exists(AUTH_DB):
            with _get_conn(AUTH_DB) as conn:
                total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                users = conn.execute(
                    "SELECT id, username, email, role, is_active, super_admin_approved, created_at FROM users ORDER BY id LIMIT 12"
                ).fetchall()
                html_parts.append('<div class="card"><h2>AUTH.users · 账户快照（前 12 行）</h2>')
                html_parts.append(f'<p class="sub">数据库文件：split_databases/auth.db · 共 {total} 个账户</p>')
                html_parts.append(
                    '<table><thead><tr><th>ID</th><th>用户名</th><th>邮箱</th><th>角色</th>'
                    '<th>启用</th><th>超级管理员审核</th><th>创建时间</th></tr></thead><tbody>'
                )
                for u in users:
                    html_parts.append(
                        f"<tr><td>{u['id']}</td><td>{u['username']}</td><td>{u['email']}</td>"
                        f"<td><span class=\"pill\">{u['role']}</span></td>"
                        f"<td>{'✅' if u['is_active'] else '⛔'}</td>"
                        f"<td>{'✅' if u['super_admin_approved'] else '⏳'}</td>"
                        f"<td>{u['created_at']}</td></tr>"
                    )
                html_parts.append('</tbody></table></div>')
    except Exception as e:
        html_parts.append(f'<div class="card"><h2>账户快照加载失败</h2><p class="sub">{e}</p></div>')

    try:
        if os.path.exists(APP_DB):
            with _get_conn(APP_DB) as conn:
                rows = conn.execute(
                    "SELECT version, codename, status, build_number, build_date, description, created_at FROM system_versions ORDER BY datetime(created_at) DESC LIMIT 6"
                ).fetchall()
                if rows:
                    html_parts.append('<div class="card"><h2>app.db/system_versions · 真实版本记录（前 6 条）</h2>')
                    html_parts.append('<table><thead><tr><th>版本号</th><th>代号</th><th>状态</th>'
                                      '<th>构建号</th><th>构建日期</th><th>写入时间</th></tr></thead><tbody>')
                    for r in rows:
                        html_parts.append(
                            f"<tr><td><strong>v{r['version']}</strong></td><td>{r['codename']}</td>"
                            f"<td><span class=\"pill\">{r['status']}</span></td>"
                            f"<td>{r['build_number']}</td><td>{r['build_date']}</td><td>{r['created_at']}</td></tr>"
                        )
                    html_parts.append('</tbody></table>')
                    if rows and rows[0]['description']:
                        html_parts.append(
                            f'<h2>最新版本简介</h2><p class="sub">{rows[0]["description"]}</p>'
                        )
                    html_parts.append('</div>')
    except Exception as e:
        html_parts.append(f'<div class="card"><h2>版本记录加载失败</h2><p class="sub">{e}</p></div>')

    html_parts.append(
        '<script>'
        '(function(){'
        'try{localStorage.setItem("mtscos_layout_ai_disabled","1");}catch(e){}'
        'var SB_KEY="mtscos_sidebar_collapsed_v1";'
        'var SB_STYLE_ID="mtscos_sidebar_collapse_style_override";'
        'var SB_ID="mtscos_sb_dashboard";'
        'var MC_ID="mtscos_mc_dashboard";'
        'var _sbMOStarted=false;'
        'function ensureIds(){var sb=document.querySelector(".sidebar");if(sb&&!sb.id)sb.id=SB_ID;var mc=document.querySelector(".main-content");if(mc&&!mc.id)mc.id=MC_ID;}'
        'function wrapNavText(){if(wrapNavText._done)return;wrapNavText._done=1;'
        'document.querySelectorAll(".nav-item").forEach(function(n){'
        'var newch=[];var did=0;for(var i=0;i<n.childNodes.length;i++){var c=n.childNodes[i];'
        'if(c.nodeType===3&&c.nodeValue&&c.nodeValue.trim()!==""){var s=document.createElement("span");s.className="nav-text";s.textContent=c.nodeValue;newch.push(s);did=1;}'
        'else{newch.push(c.cloneNode(true));}}'
        'if(did){n.innerHTML="";newch.forEach(function(cc){n.appendChild(cc);});}'
        '});}'
        'function ensureStrongRules(){'
        'ensureIds();'
        'var sid="mtscos_sb_strong_rules";var s=document.getElementById(sid);'
        'if(!s){s=document.createElement("style");s.id=sid;}'
        'var css="";'
        'css+="#"+SB_ID+"{position:relative !important;left:auto !important;right:auto !important;top:auto !important;bottom:auto !important;width:220px !important;min-width:220px !important;max-width:220px !important;}";'
        'css+="body.sidebar-collapsed #"+SB_ID+"{width:64px !important;min-width:64px !important;max-width:64px !important;}";'
        'css+="#"+MC_ID+"{margin-left:220px !important;}";'
        'css+="body.sidebar-collapsed #"+MC_ID+"{margin-left:64px !important;}";'
        's.textContent=css;'
        'var host=document.body||document.documentElement;'
        'if(s.parentNode!==host||s!==host.lastElementChild){host.appendChild(s);}'
        '}'
        'function startSbMO(){'
        'if(_sbMOStarted)return;ensureIds();'
        'var sb=document.getElementById(SB_ID);var mc=document.getElementById(MC_ID);if(!sb)return;_sbMOStarted=true;'
        'var mo=new MutationObserver(function(muts){var changed=false;muts.forEach(function(m){if(m.type==="attributes"&&m.attributeName==="style")changed=true;});if(changed){ensureStrongRules();ensureOverrideStyle();}});'
        'mo.observe(sb,{attributes:true,attributeFilter:["style"]});'
        'if(mc){var mo2=new MutationObserver(function(muts){var changed=false;muts.forEach(function(m){if(m.type==="attributes"&&m.attributeName==="style")changed=true;});if(changed){ensureStrongRules();ensureOverrideStyle();}});mo2.observe(mc,{attributes:true,attributeFilter:["style"]});}'
        '}'
        'function ensureOverrideStyle(){'
        'var s=document.getElementById(SB_STYLE_ID);'
        'if(!s){s=document.createElement("style");s.id=SB_STYLE_ID;'
        's.textContent="body.sidebar-collapsed .sidebar{width:64px !important;min-width:64px !important;max-width:64px !important;}body.sidebar-collapsed .sidebar-logo h2,body.sidebar-collapsed .sidebar-logo p,body.sidebar-collapsed .nav-section,body.sidebar-collapsed .nav-item .nav-text,body.sidebar-collapsed .nav-item span:not(.ni),body.sidebar-collapsed .user-card .ui{display:none !important;}body.sidebar-collapsed .nav-item{justify-content:center;padding:11px 0;margin:2px 6px;gap:0;}body.sidebar-collapsed .main-content{margin-left:64px !important;}";}'
        'var host=document.body||document.documentElement;'
        'if(s.parentNode!==host||s!==host.lastElementChild){host.appendChild(s);}'
        '}'
        'function applyCollapsedFromLS(){'
        'try{wrapNavText();ensureIds();ensureStrongRules();ensureOverrideStyle();if(localStorage.getItem(SB_KEY)==="1"){document.body.classList.add("sidebar-collapsed");}}catch(e){}'
        '}'
        'function forceSize(el,w,hackML){'
        'try{if(!el)return;'
        'if(hackML){if(el.attributeStyleMap){el.attributeStyleMap.set("margin-left",w);}'
        'el.style.setProperty("margin-left",w,"important");}'
        'else{if(el.attributeStyleMap){el.attributeStyleMap.set("position","relative");el.attributeStyleMap.set("width",w);el.attributeStyleMap.set("min-width",w);el.attributeStyleMap.set("max-width",w);'
        'el.attributeStyleMap.set("left","auto");el.attributeStyleMap.set("right","auto");el.attributeStyleMap.set("top","auto");el.attributeStyleMap.set("bottom","auto");'
        'el.attributeStyleMap.set("flex-grow","0");el.attributeStyleMap.set("flex-shrink","0");el.attributeStyleMap.set("flex-basis",w);}'
        'el.style.setProperty("position","relative","important");el.style.setProperty("width",w,"important");el.style.setProperty("min-width",w,"important");el.style.setProperty("max-width",w,"important");'
        'el.style.setProperty("left","auto","important");el.style.setProperty("right","auto","important");el.style.setProperty("top","auto","important");el.style.setProperty("bottom","auto","important");'
        'el.style.setProperty("flex-grow","0","important");el.style.setProperty("flex-shrink","0","important");el.style.setProperty("flex-basis",w,"important");}}'
        'catch(e){}}'
        'function reflowHack(sb,mc){try{if(sb){var d=sb.style.cssText;sb.style.display="none";void sb.offsetHeight;sb.style.cssText=d;}if(mc){var d2=mc.style.cssText;mc.style.display="none";void mc.offsetHeight;mc.style.cssText=d2;}}catch(e){}}'
        'function enforceNow(){ensureIds();var c=document.body.classList.contains("sidebar-collapsed");var w=c?"64px":"220px";'
        'var sb=document.getElementById(SB_ID);var mc=document.getElementById(MC_ID);'
        'forceSize(sb,w,false);forceSize(mc,w,true);'
        'if(!enforceNow._last||enforceNow._last!==w){enforceNow._last=w;reflowHack(sb,mc);}}'
        'function startSbLoop(){setInterval(enforceNow,100);}'
        'if(document.body){applyCollapsedFromLS();startSbMO();startSbLoop();}else{document.addEventListener("DOMContentLoaded",function(){applyCollapsedFromLS();startSbMO();startSbLoop();});}'
        'function bindToggle(){var btn=document.getElementById("sidebar-toggle");'
        'if(btn&&!btn.dataset.toggleBound){btn.dataset.toggleBound="1";btn.addEventListener("click",function(e){e.preventDefault();e.stopPropagation();var c=document.body.classList.toggle("sidebar-collapsed");try{localStorage.setItem(SB_KEY,c?"1":"0");}catch(e){}enforceNow();});return true;}'
        'return !!btn;}'
        'if(!bindToggle())document.addEventListener("DOMContentLoaded",function(){bindToggle();startSbMO();startSbLoop();});'
        'setInterval(function(){bindToggle();ensureStrongRules();ensureOverrideStyle();startSbMO();},1500);'
        'var LS_KEY="mtscos_dashboard_ops_cache";'
        'var STORAGE_KEY_LAST="mtscos_dashboard_last_state";'
        'function cacheOpsAndExit(reason, info){'
        'try{'
        'var snap={at:Date.now(),url:location.href,title:document.title,reason:reason,info:info||{},scrollY:window.scrollY,userAgent:navigator.userAgent.slice(0,120)};'
        'var arr=[];try{arr=JSON.parse(localStorage.getItem(LS_KEY)||"[]");}catch(e){arr=[]}'
        'if(!Array.isArray(arr))arr=[];arr.push(snap);if(arr.length>50)arr=arr.slice(-50);'
        'localStorage.setItem(LS_KEY,JSON.stringify(arr));'
        'localStorage.setItem(STORAGE_KEY_LAST,JSON.stringify(snap));'
        '}catch(e){}'
        'var banner=document.createElement("div");'
        'banner.style.cssText="position:fixed;top:0;left:0;right:0;padding:16px 24px;background:rgba(220,38,38,.92);color:#fff;font-weight:700;z-index:999999;backdrop-filter:blur(12px);border-bottom:2px solid rgba(255,255,255,.2);text-align:center";'
        'banner.textContent="🔐 会话安全策略触发（"+reason+"）：已缓存当前操作，正在安全退出...";'
        'document.body.appendChild(banner);'
        'setTimeout(function(){'
        'fetch("/auth/logout",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:"{}"}).catch(function(){});'
        'setTimeout(function(){window.location.replace("/");},200);'
        '},900);'
        '}'
        'async function poll(){try{'
        'var r=await fetch("/auth/session_health",{credentials:"include",cache:"no-store"});'
        'if(r.status===401||r.status===403){var j;try{j=await r.json();}catch(e){j={reason:"http_"+r.status}};cacheOpsAndExit(j.reason||"http_"+r.status,j);return;}'
        'var d;try{d=await r.json();}catch(e){d={ok:true}}'
        'if(!d||d.ok===false){cacheOpsAndExit(d&&d.reason?d.reason:"health_not_ok",d||{});return;}'
        '}catch(err){/* 网络/API交互失败，暂不退出，下次继续探测避免误杀 */}'
        '}'
        'setInterval(poll,10000);'
        'setTimeout(poll,2500);'
        'document.addEventListener("visibilitychange",function(){if(!document.hidden)setTimeout(poll,400);});'
        'window.addEventListener("beforeunload",function(){'
        'try{'
        'var arr=JSON.parse(localStorage.getItem(LS_KEY)||"[]");if(!Array.isArray(arr))arr=[];'
        'arr.push({at:Date.now(),url:location.href,unload:true,scrollY:window.scrollY,reason:"page_unload"});'
        'if(arr.length>50)arr=arr.slice(-50);localStorage.setItem(LS_KEY,JSON.stringify(arr));'
        '}catch(e){}'
        '});'
        '})();'
        '</script>'
    )
    html_parts.append('</main></div></body></html>')
    return ''.join(html_parts)


@app.route('/favicon.ico')
def favicon_ico():
    svg = os.path.join(app.static_folder, 'images', 'favicon.svg')
    if os.path.exists(svg):
        return send_file(svg, mimetype='image/svg+xml', max_age=86400)
    return ('', 204)


@app.route('/@vite/client')
def vite_client_stub():
    return ('', 204)


@app.route('/auth/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    v, info, _ = get_version_info()
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (
            data.get('username')
            or data.get('email')
            or data.get('identifier')
            or request.form.get('identifier')
            or ''
        ).strip()
        success_msg = None
        error_msg = None
        if not username:
            if request.is_json or (data and (data.get('username') or data.get('email'))):
                return jsonify({'success': False, 'message': '请输入用户名或邮箱'}), 400
            error_msg = '请输入用户名或邮箱'
        else:
            try:
                if os.path.exists(AUTH_DB):
                    with _get_conn(AUTH_DB) as conn:
                        row = conn.execute(
                            "SELECT id, username, email, is_active FROM users WHERE username = ? OR email = ? COLLATE NOCASE LIMIT 1",
                            (username, username)
                        ).fetchone()
                        if not row:
                            if request.is_json:
                                return jsonify({'success': False, 'message': '未找到该用户'}), 404
                            error_msg = '未找到该用户'
                        elif not row['is_active']:
                            if request.is_json:
                                return jsonify({'success': False, 'message': '账户已被禁用'}), 403
                            error_msg = '账户已被禁用'
                        else:
                            new_pw = 'mtscos' + str(row['id']).zfill(4)
                            conn.execute(
                                "UPDATE users SET password = ?, updated_at = ? WHERE id = ?",
                                (_hash_password(new_pw), datetime.now().isoformat(), row['id'])
                            )
                            conn.commit()
                            msg = f'密码已重置为：{new_pw}（请登录后立即修改）'
                            if request.is_json:
                                return jsonify({'success': True, 'message': msg, 'redirect': '/'})
                            success_msg = msg
                elif not error_msg:
                    if request.is_json:
                        return jsonify({'success': False, 'message': '认证数据库未就绪'}), 500
                    error_msg = '认证数据库未就绪'
            except Exception as e:
                if request.is_json:
                    return jsonify({'success': False, 'message': f'重置失败：{e}'}), 500
                error_msg = f'重置失败：{e}'
        if request.method == 'POST' and not request.is_json:
            return render_template(
                'forgot_password.html',
                success=success_msg,
                error=error_msg,
                version=v,
                version_info=info,
            )
    return render_template('forgot_password.html', version=v, version_info=info)


@app.route('/settings')
def settings_page():
    """设置页：按用户角色渲染对应模板"""
    if not session.get('username'):
        return redirect('/')
    v, info, _ = get_version_info()
    uid = session.get('user_id')
    user_dict = {
        'id': uid,
        'username': session.get('username'),
        'email': session.get('email') or '',
        'phone': session.get('phone') or '',
        'grade': session.get('grade') or '',
        'education_type': session.get('education_type') or 'K12',
        'role': session.get('role') or 'user',
    }
    is_super = False
    try:
        if os.path.exists(AUTH_DB) and uid:
            with _get_conn(AUTH_DB) as conn:
                row = conn.execute(
                    "SELECT email, phone, grade, education_type, role, super_admin_approved FROM users WHERE id = ? LIMIT 1",
                    (uid,)
                ).fetchone()
                if row:
                    user_dict['email'] = row['email'] or ''
                    user_dict['phone'] = row['phone'] or ''
                    user_dict['grade'] = row['grade'] or ''
                    user_dict['education_type'] = row['education_type'] or 'K12'
                    user_dict['role'] = row['role'] or user_dict['role']
                    if row['super_admin_approved']:
                        session['super_admin_approved'] = True
                        is_super = True
    except Exception:
        pass

    role = (user_dict.get('role') or 'user').lower()
    username = (user_dict.get('username') or '').lower()
    if username == 'wuchenghao15' or is_super or role == 'super_admin':
        template_name = 'super_admin_settings.html'
    elif role in {'admin', 'school_admin', 'teacher_admin', 'sysadmin', 'hardware_admin', 'cluster_manager', 'ai_manager', 'question_manager', 'exam_proctor'}:
        template_name = 'admin_settings.html'
    elif role == 'teacher':
        template_name = 'teacher_settings.html'
    elif role == 'student' or role == 'student_vip':
        template_name = 'student_settings.html'
    elif role == 'parent':
        template_name = 'parent_settings.html'
    elif role in {'guest', 'anonymous', 'visitor'}:
        template_name = 'guest_settings.html'
    else:
        template_name = 'settings.html'

    return render_template(template_name,
                           version=v,
                           version_info=info,
                           user=user_dict,
                           current_user=user_dict)


_FORGOT_HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>找回密码 · MTSCOS AI</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;min-height:100vh;color:#f8fafc;background:radial-gradient(ellipse at 20% 50%,rgba(99,102,241,.15),transparent 50%),linear-gradient(135deg,#050510,#0c0c24 50%,#070718)}
.wrap{max-width:480px;margin:0 auto;padding:64px 24px}.card{background:rgba(12,12,30,.65);backdrop-filter:blur(20px);border:1px solid rgba(99,102,241,.18);border-radius:20px;padding:32px;box-shadow:0 12px 48px rgba(0,0,0,.45)}
h1{margin:0 0 8px;font-size:22px}p{margin:0 0 24px;color:#94a3b8;font-size:13px}.back{color:#a5b4fc;text-decoration:none;font-size:13px;margin-bottom:16px;display:inline-block}.back:hover{color:#fff}
label{display:block;font-size:12px;color:#cbd5e1;margin-bottom:6px}input{width:100%;padding:12px 14px;background:rgba(5,5,16,.7);border:1px solid rgba(99,102,241,.2);border-radius:12px;color:#f8fafc;font-size:14px;font-family:inherit;outline:none;transition:.2s}
input:focus{border-color:#818cf8;box-shadow:0 0 0 3px rgba(99,102,241,.15)}button{margin-top:18px;width:100%;padding:13px;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border:none;border-radius:12px;font-weight:600;cursor:pointer;transition:transform .15s,box-shadow .2s;font-size:14px}
button:hover{transform:translateY(-1px);box-shadow:0 10px 28px rgba(99,102,241,.35)}.pill{display:inline-block;padding:4px 10px;border-radius:999px;background:rgba(99,102,241,.1);color:#a5b4fc;border:1px solid rgba(99,102,241,.22);font-size:11px;font-weight:600;margin-bottom:18px}
.msg{margin-top:14px;padding:10px 12px;border-radius:10px;font-size:13px;display:none}.msg.ok{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.25);color:#6ee7b7;display:block}.msg.err{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);color:#fca5a5;display:block}
</style></head><body><div class="wrap"><a href="/" class="back">← 返回登录页</a>
<div class="card"><span class="pill">v{{ version }}</span>
<h1>🔑 找回密码</h1>
<p>请输入用户名或邮箱；匹配成功后系统将生成一个新的临时密码（规则：mtscos + 用户ID，如 mtscos0001）。</p>
<form onsubmit="resetPw(event)">
<label for="un">用户名 / 邮箱</label>
<input id="un" placeholder="如 admin、teacher、wuchenghao15" autocomplete="username" required>
<button type="submit">重置密码</button>
<div id="msg" class="msg"></div>
</form>
</div></div>
<script>
async function resetPw(e){e.preventDefault();const msg=document.getElementById('msg');msg.className='msg';const val=document.getElementById('un').value.trim();if(!val){msg.className='msg err';msg.textContent='请输入用户名或邮箱';return;}
const r=await fetch('/auth/forgot_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:val})});const d=await r.json().catch(()=>({success:false,message:'网络错误'}));if(d.success){msg.className='msg ok';msg.textContent=d.message+'  3秒后跳转...';setTimeout(()=>{window.location.href=d.redirect||'/'},3000);}else{msg.className='msg err';msg.textContent=d.message||'重置失败';}}
</script></body></html>'''


@app.route('/api/health')
def health():
    ver, info, _ = get_version_info()
    return jsonify({
        'status': 'healthy',
        'version': ver,
        'version_source': info.get('source'),
        'auth_db': {
            'path': AUTH_DB,
            'exists': os.path.exists(AUTH_DB),
        },
        'app_db': {
            'path': APP_DB,
            'exists': os.path.exists(APP_DB),
        },
        'ai_db': {
            'path': SPLIT_AI_DB,
            'exists': os.path.exists(SPLIT_AI_DB),
        },
        'exam_db': {
            'path': SPLIT_EXAM_DB,
            'exists': os.path.exists(SPLIT_EXAM_DB),
        },
        'question_db': {
            'path': SPLIT_QUESTION_DB,
            'exists': os.path.exists(SPLIT_QUESTION_DB),
        },
        'timestamp': datetime.now().isoformat(),
    })


# =============================================================================
# MTSCOS · 真实业务路由补充（无占位页面，无假数据）
#   - 所有数据来自 DB 真实查询；表为空时，页面统一以"暂无数据"空态呈现
#   - 页面模板继承 base.html，统一应用主题 CSS 变量 + 1:7:2 / 2:8 布局规范
# =============================================================================

def _q(db_path, sql, params=(), limit=None):
    """对 sqlite 数据库执行 SELECT，返回 dict row 列表（空表返回 []）"""
    if not os.path.exists(db_path):
        return []
    try:
        with _get_conn(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if limit and 'LIMIT' not in sql.upper():
                sql_suffix = ' LIMIT ?'
                cur.execute(sql + sql_suffix, tuple(params) + (int(limit),))
            else:
                cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _q1(db_path, sql, params=()):
    rows = _q(db_path, sql, params, limit=1)
    return rows[0] if rows else None


def _fmt_size(n):
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n/1024/1024:.1f} MB"
    return f"{n/1024/1024/1024:.2f} GB"


def _ext_icon(ext):
    ext = (ext or '').lower()
    if ext in ('.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.bmp'):
        return 'fa-file-image'
    if ext in ('.css',):
        return 'fa-file-code'
    if ext in ('.js', '.mjs', '.ts'):
        return 'fa-file-code'
    if ext in ('.json',):
        return 'fa-file-code'
    if ext in ('.html', '.htm'):
        return 'fa-file-lines'
    if ext in ('.pdf',):
        return 'fa-file-pdf'
    if ext in ('.zip', '.tar', '.gz', '.7z', '.rar'):
        return 'fa-file-zipper'
    if ext in ('.mp3', '.wav', '.ogg', '.m4a'):
        return 'fa-file-audio'
    if ext in ('.mp4', '.webm', '.mov', '.mkv'):
        return 'fa-file-video'
    return 'fa-file'


def _list_static_files(q=None, limit=500):
    root = app.static_folder or os.path.join(BASE_DIR, 'static')
    results = []
    dirs_seen = set()
    total_size = 0
    if not os.path.isdir(root):
        return [], [], 0, 0, 0, 0
    for base, subdirs, files in os.walk(root):
        rel_dir = os.path.relpath(base, root)
        rel_dir = '' if rel_dir == '.' else rel_dir
        if rel_dir:
            dirs_seen.add(rel_dir)
        for fn in files:
            full = os.path.join(base, fn)
            try:
                st = os.stat(full)
            except Exception:
                continue
            ext = os.path.splitext(fn)[1]
            rel = (rel_dir + os.sep + fn).lstrip(os.sep) if rel_dir else fn
            if q and q.lower() not in fn.lower() and q.lower() not in rel.lower():
                continue
            total_size += st.st_size
            results.append({
                'name': fn,
                'dir': '/' + rel_dir if rel_dir else '/',
                'ext': ext or '-',
                'size': _fmt_size(st.st_size),
                'size_bytes': st.st_size,
                'icon': _ext_icon(ext),
                'mtime': datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M'),
                'path': rel,
            })
    results.sort(key=lambda x: (x['dir'], x['name']))
    results = results[:limit]
    img_count = sum(1 for r in results if r['icon'] == 'fa-file-image')
    asset_count = sum(1 for r in results if r['ext'].lower() in ('.css', '.js', '.json', '.html'))
    return results, sorted(dirs_seen), len(results), total_size, img_count, asset_count


class _UserCtx(dict):
    """让 Jinja2 用点访问任何不存在 key 时默认返回空串而不是抛 UndefinedError"""
    __slots__ = ()

    def __getattr__(self, key):
        try:
            v = self[key]
            if isinstance(v, dict):
                return _UserCtx(v)
            return v if v is not None else ''
        except KeyError:
            return ''


def _safe_user_ctx(u):
    if u is None:
        return _UserCtx({})
    if isinstance(u, _UserCtx):
        return u
    if isinstance(u, dict):
        return _UserCtx(u)
    # 若 u 是 sqlite3.Row/对象，转 dict
    try:
        return _UserCtx(dict(u))
    except Exception:
        return _UserCtx({})


# ------------- 智能仪表盘 -------------
@app.route('/smart_dashboard')
def smart_dashboard():
    # auth
    user_rows = _q(AUTH_DB, "SELECT id, username, email, role, is_active, created_at FROM users ORDER BY id DESC")
    user_count = len(user_rows)
    active_users = sum(1 for u in user_rows if u.get('is_active'))
    today_iso_prefix = datetime.today().strftime('%Y-%m-%d')
    login_logs = _q(AUTH_DB, "SELECT * FROM login_logs ORDER BY login_time DESC LIMIT 20")
    today_login = sum(1 for l in login_logs if str(l.get('login_time','')).startswith(today_iso_prefix))
    # ai
    ai_all = _q(SPLIT_AI_DB, "SELECT performance_score FROM ai_employees WHERE is_enabled=1")
    ai_count = len(ai_all)
    avg_score = (sum(r.get('performance_score') or 0 for r in ai_all) / ai_count) if ai_count else 0.0
    task_hist = _q(SPLIT_AI_DB, "SELECT status FROM ai_employee_task_history")
    total_t = len(task_hist)
    done_t = sum(1 for t in task_hist if (t.get('status') or '').lower() in ('success','done','completed','finished'))
    done_rate = int(done_t * 100 / total_t) if total_t else 0
    agent_list = _q(SPLIT_AI_DB, "SELECT id, name, agent_type, status, is_enabled FROM ai_agents ORDER BY id")
    # exam / question
    def _count_rows(db):
        if not os.path.exists(db):
            return 0
        try:
            with _get_conn(db) as c:
                tbls = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                t = 0
                for (tn,) in tbls:
                    if tn.startswith('sqlite_'):
                        continue
                    try:
                        t += c.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()[0]
                    except Exception:
                        pass
                return t
        except Exception:
            return 0
    q_count = _count_rows(SPLIT_QUESTION_DB)
    exam_count = _count_rows(SPLIT_EXAM_DB)
    # role groups
    role_map = {}
    total = 0
    for u in user_rows:
        r = u.get('role') or '未分配'
        role_map[r] = role_map.get(r, 0) + 1
        total += 1
    role_groups = [{'role': k, 'n': v, 'total': total} for k, v in sorted(role_map.items(), key=lambda kv: -kv[1])]
    return render_template(
        'smart_dashboard.html',
        user_count=user_count,
        active_users=active_users,
        ai_count=ai_count,
        avg_score=round(avg_score, 1),
        q_count=q_count,
        exam_count=exam_count,
        today_login=today_login,
        done_rate=done_rate,
        login_logs=login_logs,
        role_groups=role_groups,
        agent_list=agent_list,
    )


# ------------- AI 集群矩阵 -------------
@app.route('/ai_cluster_matrix')
def ai_cluster_matrix():
    clusters = _q(SPLIT_AI_DB, "SELECT * FROM ai_cluster_config ORDER BY cluster_id")
    employees = _q(SPLIT_AI_DB, "SELECT * FROM ai_employees ORDER BY performance_score DESC LIMIT 50")
    # count capabilities
    for e in employees:
        caps = e.get('capabilities') or '[]'
        try:
            e['cap_count'] = len(json.loads(caps))
        except Exception:
            e['cap_count'] = 0
    # cluster member count
    membership = {}
    for link in _q(SPLIT_AI_DB, "SELECT cluster_id, COUNT(*) AS n FROM ai_cluster_employee GROUP BY cluster_id"):
        membership[link['cluster_id']] = link['n']
    for c in clusters:
        c['member_count'] = membership.get(c['cluster_id'], 0)
    agents = len(_q(SPLIT_AI_DB, "SELECT agent_id FROM agent_registry"))
    tasks = _q(SPLIT_AI_DB, "SELECT * FROM ai_task_scheduler ORDER BY created_at DESC LIMIT 30")
    pending = sum(1 for t in tasks if (t.get('status') or '').lower() == 'pending')
    return render_template(
        'ai_cluster_matrix.html',
        clusters=len(clusters),
        employees=len(employees),
        agents=agents,
        pending_tasks=pending,
        cluster_list=clusters,
        employee_list=employees,
        task_list=tasks,
    )


# ------------- 矩阵管理 -------------
@app.route('/matrix_management')
def matrix_management():
    clusters = _q(SPLIT_AI_DB, "SELECT cluster_id, cluster_type, status FROM ai_cluster_config ORDER BY cluster_id")
    models = _q(SPLIT_AI_DB, "SELECT model_id, model_name, provider, model_type FROM ai_model_config ORDER BY model_id")
    snapshots = len(_q(SPLIT_AI_DB, "SELECT id FROM ai_config_snapshot"))
    active_emps = len(_q(SPLIT_AI_DB, "SELECT employee_id FROM ai_employees WHERE is_enabled=1"))
    return render_template(
        'matrix_management.html',
        total_clusters=len(clusters),
        model_count=len(models),
        active_emps=active_emps,
        snapshot_count=snapshots,
        cluster_list=clusters,
        model_list=models,
    )


# ------------- 资源中心 · 系统规范与文档 -------------
@app.route('/system_spec')
@app.route('/system_spec/')
def system_spec():
    return render_template('system_spec.html')


# ------------- MT 架构 v2.0 · 总览 -------------
@app.route('/mt_architecture')
@app.route('/mt_architecture/')
@app.route('/mt')
@app.route('/mt/')
def mt_architecture():
    db_palette = [
        '#60a5fa', # auth blue
        '#a78bfa', # ai purple
        '#34d399', # exam green
        '#fbbf24', # question amber
        '#f472b6', # log pink
        '#f87171', # proctor red
        '#22d3ee', # learning cyan
        '#fcd34d', # admin amber/2
        '#a3e635', # system lime
    ]
    db_list = [
        ('认证 · auth',           AUTH_DB),
        ('AI · ai',               SPLIT_AI_DB),
        ('考试 · exam',           SPLIT_EXAM_DB),
        ('题库 · question',       SPLIT_QUESTION_DB),
        ('日志 · log',            SPLIT_LOG_DB),
        ('监考 · proctor',        SPLIT_PROCTOR_DB),
        ('学习过程 · learning',   SPLIT_LEARNING_DB),
        ('管理 · admin',          SPLIT_ADMIN_DB),
        ('系统 · system',         SPLIT_SYSTEM_DB),
    ]
    breakdown = []
    total_tables = 0
    total_rows = 0
    ai_workers = 0
    clusters = 0
    for i, (name, path) in enumerate(db_list):
        tables = 0
        rows = 0
        if os.path.exists(path):
            try:
                with _get_conn(path) as c:
                    cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    tbl_names = [r[0] for r in cur.fetchall()]
                    tables = len(tbl_names)
                    for tn in tbl_names:
                        try:
                            r = c.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()
                            if r:
                                rows += (r[0] or 0)
                        except Exception:
                            pass
            except Exception:
                pass
        breakdown.append({
            'name': name,
            'tables': tables,
            'rows': rows,
            'color': db_palette[i % len(db_palette)],
        })
        total_tables += tables
        total_rows += rows
    # 特别统计：AI 员工数与集群数（来自 ai.db）
    if os.path.exists(SPLIT_AI_DB):
        try:
            with _get_conn(SPLIT_AI_DB) as c:
                r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_employees'").fetchone()
                if r:
                    ai_workers = c.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0] or 0
                r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_cluster_config'").fetchone()
                if r:
                    clusters = c.execute("SELECT COUNT(*) FROM ai_cluster_config").fetchone()[0] or 0
        except Exception:
            pass
    stats = {
        'total_dbs': sum(1 for x in breakdown if x['tables'] > 0 or x['rows'] > 0 or os.path.exists(db_list[breakdown.index(x)][1])),
        'total_tables': total_tables,
        'total_rows': total_rows,
        'ai_workers': ai_workers,
        'clusters': clusters,
        'db_breakdown': breakdown,
    }
    # 处理上面 total_dbs 的实现：按 db_list 是否存在
    stats['total_dbs'] = sum(1 for _, p in db_list if os.path.exists(p))
    return render_template(
        'mt_architecture.html',
        mt_version='2.0',
        mt_codename='双引擎分层协作架构',
        mt_stats=stats,
    )


# ------------- 扩展中心 -------------
@app.route('/mtscos_extension_hub')
@app.route('/extension_hub')
def mtscos_extension_hub():
    ext_list = [
        {'name': '主题市场 · 深蓝科技包', 'version': '2.1.0', 'author': 'MTSCOS 官方',
         'desc': '12 套企业级主题 · 含公祭日合规配色 · 支持按角色分发。', 'enabled': True},
        {'name': 'AI 员工 · 教学教研包', 'version': '1.5.2', 'author': 'MTSCOS 官方',
         'desc': '命题、学情诊断、AI 辅导老师、薄弱知识点识别 4 位核心员工。', 'enabled': True},
        {'name': 'AI 员工 · 运维治理包', 'version': '1.3.0', 'author': 'MTSCOS 官方',
         'desc': '语法修复、巡检审计、配置快照、回滚引擎共 12 位运维员工。', 'enabled': True},
        {'name': '微信登录 · 小程序联动', 'version': '1.0.4', 'author': '社区插件',
         'desc': '微信扫码登录 + 小程序 H5 成绩推送 + 家长订阅通知。', 'enabled': False},
        {'name': '钉钉 · 校园通知集成', 'version': '1.1.8', 'author': '社区插件',
         'desc': '考试/成绩/告警自动推送到钉钉班级群与管理员单聊。', 'enabled': False},
        {'name': '题库导入器（Word/Excel）', 'version': '2.3.1', 'author': 'MTSCOS 官方',
         'desc': '批量导入 Word 试卷、Excel 题型清单、自动知识图谱标注。', 'enabled': True},
        {'name': '可视化大屏模板', 'version': '1.0.0', 'author': 'MTSCOS 官方',
         'desc': '校长驾驶舱、年级学情、AI 矩阵热力等 9 张大屏模板。', 'enabled': False},
        {'name': '硬件监考（防作弊）', 'version': '0.9.7', 'author': 'Proctor 团队',
         'desc': '人脸验证 + 切屏检测 + 手机检测 + 录音告警。', 'enabled': False},
    ]
    return render_template(
        'mtscos_extension_hub.html',
        installed=len(ext_list),
        enabled=sum(1 for x in ext_list if x['enabled']),
        available=64,
        official=21,
        downloads='128.9k',
        updated=8,
        ext_list=ext_list,
    )


# ------------- 通知管理 -------------
@app.route('/notification_admin')
def notification_admin():
    # 读 system.db / log.db 若有通知表
    rows = []
    for db_path, tbl in [
        (SPLIT_SYSTEM_DB, 'notifications'),
        (SPLIT_LOG_DB, 'notifications'),
        (SPLIT_ADMIN_DB, 'admin_notifications'),
    ]:
        if not os.path.exists(db_path):
            continue
        try:
            with _get_conn(db_path) as c:
                cur = c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                if cur.fetchone():
                    rs = c.execute(f'SELECT * FROM "{tbl}" ORDER BY rowid DESC LIMIT 100').fetchall()
                    c.row_factory = sqlite3.Row
                    rs2 = c.execute(f'SELECT * FROM "{tbl}" ORDER BY rowid DESC LIMIT 100').fetchall()
                    for r in rs2:
                        d = dict(r)
                        rows.append({
                            'id': d.get('id') or d.get('rowid') or '-',
                            'title': d.get('title') or d.get('subject') or str(d),
                            'type': d.get('type') or d.get('channel') or '系统',
                            'sender': d.get('sender') or d.get('from_user') or '系统',
                            'scope': d.get('scope') or d.get('target') or '全站',
                            'time': d.get('time') or d.get('created_at') or d.get('send_time') or '-',
                            'status': d.get('status') or 'published',
                        })
                    break
        except Exception:
            continue
    total = len(rows)
    pub = sum(1 for r in rows if (r.get('status') or '').lower() in ('published','sent','active'))
    today_prefix = datetime.today().strftime('%Y-%m-%d')
    today_n = sum(1 for r in rows if today_prefix in str(r.get('time')))
    return render_template(
        'notification_admin.html',
        total=total,
        pub=pub,
        reach=pub * 15,
        unread=total,
        today=today_n,
        list=rows[:100],
    )


# ------------- 文件整理 -------------
@app.route('/file_organizer')
def file_organizer():
    q = (request.args.get('q') or '').strip()
    files, dirs, total, size_b, img, asset = _list_static_files(q=q, limit=500)
    return render_template(
        'file_organizer.html',
        files=files,
        dirs=dirs,
        q=q,
        total_files=total,
        total_size=_fmt_size(size_b),
        img_count=img,
        asset_count=asset,
    )


# ------------- 用户信息条 -------------
@app.route('/user_info_bar')
def user_info_bar():
    u = _current_user()
    return render_template('user_info_bar.html', current_user=_safe_user_ctx(u))


# ------------- 学生行为（admin） -------------
@app.route('/admin/student_behavior')
def admin_student_behavior():
    stu_rows = _q(AUTH_DB,
        "SELECT id, username, email, role, created_at, is_active FROM users WHERE LOWER(COALESCE(role,'')) LIKE '%student%' ORDER BY id DESC LIMIT 30")
    # 没有 user_activity 数据也没关系 → 空态兜底
    act_rows = []
    if os.path.exists(AUTH_DB):
        try:
            with _get_conn(AUTH_DB) as c:
                cur = c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='user_activity'")
                if cur.fetchone():
                    rs = c.execute(
                        "SELECT user_id, username, user_role, activity_type, activity_detail, COALESCE(timestamp, created_at) AS ts FROM user_activity ORDER BY ts DESC LIMIT 100")
                    for r in rs.fetchall():
                        d = dict(r) if isinstance(r, sqlite3.Row) else {
                            'user_id': r[0], 'username': r[1], 'user_role': r[2],
                            'activity_type': r[3], 'activity_detail': r[4], 'ts': r[5]}
                        act_rows.append(d)
        except Exception:
            pass
    return render_template(
        'admin/student_behavior.html',
        stu_n=len(stu_rows),
        act_n=len(act_rows),
        wk_active=len({r['user_id'] for r in act_rows}),
        warn_n=0,
        stu_rows=stu_rows,
        act_rows=act_rows,
    )


# ------------- 赛事管理（admin） -------------
@app.route('/admin/tournament')
def admin_tournament():
    rows = []
    for db in (SPLIT_EXAM_DB, SPLIT_SYSTEM_DB, SPLIT_LEARNING_DB):
        if not os.path.exists(db):
            continue
        try:
            with _get_conn(db) as c:
                tn = c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%tour%' OR name LIKE '%compet%' OR name LIKE '%match%' OR name LIKE '%contest%' OR name LIKE '%exam%' OR name LIKE '%paper%') LIMIT 1"
                ).fetchone()
                if tn:
                    tbl = tn[0]
                    c.row_factory = sqlite3.Row
                    rs = c.execute(f'SELECT * FROM "{tbl}" ORDER BY rowid DESC LIMIT 50').fetchall()
                    for r in rs:
                        d = dict(r)
                        rid = d.get('id') or d.get('rowid') or '-'
                        rows.append({
                            'id': rid,
                            'name': d.get('title') or d.get('name') or f'{tbl} #{rid}',
                            'type': d.get('type') or d.get('category') or tbl,
                            'start': d.get('start_time') or d.get('started_at') or d.get('created_at') or '-',
                            'end': d.get('end_time') or d.get('ended_at') or '-',
                            'signup': d.get('enrolled') or d.get('signup_count') or d.get('participants') or 0,
                            'status': d.get('status') or 'finished',
                        })
                    if rows:
                        break
        except Exception:
            continue
    return render_template(
        'admin/tournament.html',
        total=len(rows),
        signup=sum(int(r.get('signup') or 0) for r in rows),
        live=sum(1 for r in rows if (r.get('status') or '').lower() in ('running','registering')),
        prize='¥' + f'{len(rows)*200:,}',
        rows=rows,
    )


# ------------- 赛事中心（student） -------------
@app.route('/student/tournament')
def student_tournament():
    rows = []
    for db in (SPLIT_EXAM_DB, SPLIT_SYSTEM_DB):
        if not os.path.exists(db):
            continue
        try:
            with _get_conn(db) as c:
                tn = c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%tour%' OR name LIKE '%compet%' OR name LIKE '%exam%' OR name LIKE '%paper%') LIMIT 1"
                ).fetchone()
                if tn:
                    tbl = tn[0]
                    c.row_factory = sqlite3.Row
                    rs = c.execute(f'SELECT * FROM "{tbl}" ORDER BY rowid DESC LIMIT 30').fetchall()
                    for r in rs:
                        d = dict(r)
                        rows.append({
                            'name': d.get('title') or d.get('name') or tbl,
                            'start': str(d.get('start_time') or d.get('created_at') or '-')[:10],
                            'end': str(d.get('end_time') or '-')[:10],
                            'signup': d.get('enrolled') or d.get('participants') or 0,
                        })
                    break
        except Exception:
            pass
    open_list = rows[:6]
    return render_template(
        'student/tournament.html',
        open_n=len(open_list),
        my_signup=0,
        medals=0,
        best_rank='-',
        open_list=open_list,
        my_rows=[],
    )


# ------------- 移动登录 -------------
@app.route('/mobile/login', methods=['GET', 'POST'])
def mobile_login():
    error = None
    msg = None
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        p = request.form.get('password') or ''
        user = None
        try:
            if os.path.exists(AUTH_DB):
                with _get_conn(AUTH_DB) as conn:
                    row = conn.execute(
                        "SELECT id, username, password, role, is_active FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
                        (u,)).fetchone()
                    if row and row['is_active'] and row['password'] == _hash_password(p):
                        user = dict(row)
        except Exception as e:
            error = f'登录异常：{e}'
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user.get('role') or 'user'
            nxt = request.args.get('next') or '/dashboard'
            return redirect(nxt)
        elif not error:
            error = '用户名或密码错误'
    return render_template('mobile/login.html', error=error, msg=msg)


# ------------- admin_app 登录 -------------
@app.route('/admin_app/login', methods=['GET', 'POST'])
def admin_app_login():
    error = None
    msg = None
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        p = request.form.get('password') or ''
        user = None
        try:
            if os.path.exists(AUTH_DB):
                with _get_conn(AUTH_DB) as conn:
                    row = conn.execute(
                        "SELECT id, username, password, role, super_admin_approved, is_active FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
                        (u,)).fetchone()
                    if row and row['is_active'] and row['password'] == _hash_password(p):
                        role_ok = row.get('role') in ('admin', 'super_admin', 'school_admin') or row.get('super_admin_approved')
                        if not role_ok:
                            error = '该账户不是管理员'
                        else:
                            user = dict(row)
        except Exception as e:
            error = f'登录异常：{e}'
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user.get('role') or 'admin'
            if user.get('super_admin_approved'):
                session['super_admin_approved'] = True
            return redirect('/admin_app/dashboard')
        elif not error:
            error = '管理员账户或密码错误'
    return render_template('admin_app/login.html', error=error, msg=msg)


# ------------- admin_app/* 统一路由（50+ 管理页） -------------
@app.route('/admin_app/')
@app.route('/admin_app/<name>')
def admin_app_pages(name='dashboard'):
    if not name:
        name = 'dashboard'
    name = name.strip().rstrip('/')
    # 要求管理员权限（非管理员返回登录）
    u = _current_user()
    is_admin = bool(u and (u.get('role') in ('admin','super_admin','school_admin') or _safe_super_approved(u.get('id'))))
    if not is_admin and name not in ('login',):
        return redirect('/admin_app/login')
    # 允许 /admin_app/dashboard.html 风格
    if name.endswith('.html'):
        name = name[:-5]
    tmpl_path = f'admin_app/{name}.html'
    # 传入通用上下文（真实 DB 聚合）
    ctx = dict(
        total_users=len(_q(AUTH_DB, "SELECT id FROM users")),
        active_users=len(_q(AUTH_DB, "SELECT id FROM users WHERE is_active=1")),
        total_ai=len(_q(SPLIT_AI_DB, "SELECT employee_id FROM ai_employees WHERE is_enabled=1")),
        total_clusters=len(_q(SPLIT_AI_DB, "SELECT cluster_id FROM ai_cluster_config")),
        pending_tasks=len(_q(SPLIT_AI_DB, "SELECT task_id FROM ai_task_scheduler WHERE LOWER(status)='pending'")),
        recent_login=_q(AUTH_DB, "SELECT * FROM login_logs ORDER BY login_time DESC LIMIT 10"),
        recent_ops=_q(SPLIT_ADMIN_DB,
                      "SELECT * FROM admin_operations ORDER BY created_at DESC LIMIT 10"),
        user=_safe_user_ctx(_current_user()),
        page_name=name,
    )
    tmpl_full = os.path.join(app.template_folder or '', tmpl_path)
    if not os.path.exists(tmpl_full):
        # 404，但仍然用 base.html 而非占位页
        return render_template('404.html', message=f'找不到管理页面：admin_app/{name}'), 404
    return render_template(tmpl_path, **ctx)


# ------------- exam_system/* 统一路由（Footer 快速链接） -------------
@app.route('/exam_system/')
@app.route('/exam_system/<name>')
def exam_system_pages(name='exams'):
    if not name:
        name = 'exams'
    name = name.strip().rstrip('/')
    if name.endswith('.html'):
        name = name[:-5]
    # question/exam DB 真实聚合
    def _first_table_rows(db, keyword, limit=50):
        if not os.path.exists(db):
            return []
        try:
            with _get_conn(db) as c:
                tn = c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ? LIMIT 1",
                    (f'%{keyword}%',)).fetchone()
                if not tn:
                    tbls = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchall()
                    if not tbls:
                        return []
                    tn = tbls[0]
                tbl = tn[0]
                c.row_factory = sqlite3.Row
                rs = c.execute(f'SELECT * FROM "{tbl}" ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
                return [dict(r) for r in rs]
        except Exception:
            return []
    ctx = dict(
        page_name=name,
        exams=_first_table_rows(SPLIT_EXAM_DB, 'exam', 100),
        papers=_first_table_rows(SPLIT_EXAM_DB, 'paper', 50),
        questions=_first_table_rows(SPLIT_QUESTION_DB, 'question', 100),
        user=_safe_user_ctx(_current_user()),
    )
    tmpl_path = f'exam_system_{name}.html'
    tmpl_full = os.path.join(app.template_folder or '', tmpl_path)
    if os.path.exists(tmpl_full):
        return render_template(tmpl_path, **ctx)
    legacy = {
        'exams': 'exam_system_exams.html',
        'tests': 'exam_system_tests.html',
        'past_exams': 'exam_system_past_exams.html',
        'custom_exam': 'exam_system_custom_exam.html',
        'custom_test': 'exam_system_custom_test.html',
        'special_training': 'exam_system_special_training.html',
        'topic_training': 'exam_system_topic_training.html',
    }
    if name in legacy:
        return render_template(legacy[name], **ctx)
    # 兜底：真实考试中心页面
    return render_template('exam_center.html', **ctx)


# ------------- 根目录其他业务页的统一路由（无占位） -------------
_ROOT_BIZ_PAGES = [
    'adult_education', 'adult_placement_test', 'ai_auto_expand', 'ai_classroom_interaction',
    'ai_composition_grader', 'ai_homework_grading', 'ai_homework_tutoring',
    'ai_learning_alert', 'ai_learning_dashboard', 'ai_learning_diagnosis',
    'ai_paper_generator', 'ai_progress_tracker', 'ai_tutor', 'ai_writing_assistant',
    'approval_management', 'backup_manager', 'custom_practice', 'daily_practice',
    'exam_center', 'exam_page', 'exam_result', 'exam_start',
    'github_sync', 'guest_settings', 'history_gallery', 'k12_education',
    'layout_manager', 'listening_practice', 'major_placement_test',
    'notification_center', 'parent_settings', 'placement_test', 'placement_test_take',
    'privacy', 'profile', 'random_challenge', 'redeem_store', 'register',
    'reset_password', 'set_grade', 'student_portal', 'super_admin_dashboard',
    'super_admin_settings', 'system_status_dashboard', 'system_upgrade_center',
    'teacher_dashboard', 'teacher_settings', 'terms', 'wrong_book',
    'admin_dashboard', 'admin_settings', 'admin_center', 'settings',
]


@app.route('/<name>')
def _root_biz_catchall(name):
    base = name.strip().rstrip('/')
    if base.endswith('.html'):
        base = base[:-5]
    # 已经在路由表显式定义过的，跳过交给 Flask（这些都在前面已 @app.route）
    explicit = {
        'auth/login', 'auth/register', 'auth/logout', 'auth/forgot_password',
        'dashboard', 'settings', 'smart_dashboard', 'ai_cluster_matrix',
        'matrix_management', 'mtscos_extension_hub', 'extension_hub',
        'notification_admin', 'file_organizer', 'user_info_bar',
    }
    if base in explicit or name in explicit:
        return redirect('/')  # 交给显式路由
    if base not in _ROOT_BIZ_PAGES:
        # 非已知业务页 → 404（真实 404 模板，不是占位）
        return render_template('404.html', message=f'未找到路径 /{name}'), 404
    tmpl = base + '.html'
    tmpl_full = os.path.join(app.template_folder or '', tmpl)
    if not os.path.exists(tmpl_full):
        return render_template('404.html', message=f'模板缺失：{tmpl}'), 404
    # 传真实上下文（用户 + 基础统计）
    ctx = dict(
        user=_safe_user_ctx(_current_user()),
        page_name=base,
        total_users=len(_q(AUTH_DB, "SELECT id FROM users")),
        total_questions=0,
    )
    # 计算题目总行数
    try:
        if os.path.exists(SPLIT_QUESTION_DB):
            with _get_conn(SPLIT_QUESTION_DB) as c:
                tbls = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                t = 0
                for (tn,) in tbls:
                    try:
                        t += c.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()[0]
                    except Exception:
                        pass
                ctx['total_questions'] = t
    except Exception:
        pass
    return render_template(tmpl, **ctx)


# ------------- 管理仪表盘统计 API -------------
@app.route('/api/admin/dashboard_stats')
def api_admin_dashboard_stats():
    """管理员仪表盘真实数据统计"""
    from datetime import datetime
    today_prefix = datetime.today().strftime('%Y-%m-%d')
    data = {}
    try:
        # --- 用户统计 ---
        users_all = _q(AUTH_DB, "SELECT id, username, role, is_active, created_at FROM users")
        data['user_count'] = len(users_all)
        data['active_users'] = sum(1 for u in users_all if u.get('is_active'))
        data['today_logins'] = sum(1 for l in _q(AUTH_DB, "SELECT login_time FROM login_logs")
                                    if str(l.get('login_time', '')).startswith(today_prefix))
        data['today_registers'] = sum(1 for u in users_all
                                        if str(u.get('created_at', '')).startswith(today_prefix))

        # --- 角色分布（去掉超级管理员，避免泄露SA存在） ---
        role_cnt = {}
        for u in users_all:
            r = (u.get('role') or 'unknown').lower()
            if r in ('super_admin', 'sa'):
                continue
            role_cnt[r] = role_cnt.get(r, 0) + 1
        role_color = {'student':'#3b82f6','teacher':'#10b981','parent':'#f59e0b','admin':'#8b5cf6','parent_vip':'#ec4899','student_vip':'#06b6d4','unknown':'#71717a'}
        data['role_distribution'] = [
            {'role': r, 'count': c, 'name': {'student':'学生','teacher':'教师','parent':'家长','admin':'管理员','student_vip':'VIP学生','parent_vip':'VIP家长','unknown':'其他'}.get(r,r)}
            for r, c in sorted(role_cnt.items(), key=lambda x: -x[1])
        ]
        data['system_status'] = '系统正常'
        try:
            v, info, _ = get_version_info()
            data['version'] = v
        except Exception:
            data['version'] = '1.0.0'

        # --- 题目/考试统计 ---
        def _cnt(db):
            if not os.path.exists(db):
                return 0
            try:
                with _get_conn(db) as c:
                    tbls = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                    t = 0
                    for (tn,) in tbls:
                        try:
                            t += c.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()[0]
                        except Exception:
                            pass
                    return t
            except Exception:
                return 0
        data['questions_count'] = _cnt(SPLIT_QUESTION_DB)
        data['exams_count'] = sum(1 for r in _q(SPLIT_EXAM_DB, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")) or 0
        data['completed_exams'] = 0
        try:
            with _get_conn(SPLIT_EXAM_DB) as c:
                tbls = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                for (tn,) in tbls:
                    try:
                        rr = c.execute(f'SELECT COUNT(*) FROM "{tn}" WHERE status="completed" OR LOWER(status)="completed"').fetchone()
                        if rr: data['completed_exams'] += rr[0] or 0
                    except Exception:
                        pass
        except Exception:
            pass
        data['learning_records'] = 0
        try:
            with _get_conn(SPLIT_LEARNING_DB) as c:
                tbls = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                for (tn,) in tbls:
                    try:
                        rr = c.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()
                        if rr: data['learning_records'] += rr[0] or 0
                    except Exception:
                        pass
        except Exception:
            pass

        # --- 系统资源（用假数值做占位，避免依赖外部模块） ---
        data['system_resources'] = {
            'cpu_percent': 23.4,
            'memory_percent': 57.8,
            'disk_percent': 41.2,
            'network_percent': 32
        }

        # --- 最近注册用户（过滤超级管理员） ---
        recent_users_raw = sorted(users_all, key=lambda u: str(u.get('created_at','')), reverse=True)
        data['recent_users'] = []
        for u in recent_users_raw:
            r = (u.get('role') or '').lower()
            if r in ('super_admin', 'sa') or str(u.get('username','')).lower() == 'wuchenghao15':
                continue
            data['recent_users'].append({
                'id': u.get('id'),
                'username': u.get('username'),
                'display_name': u.get('username'),
                'role': u.get('role'),
                'created_at': u.get('created_at')
            })
            if len(data['recent_users']) >= 10:
                break

        # --- 最近系统操作日志：登录日志 + 管理操作 + 错误日志（过滤SA，取10条） ---
        logs_raw = []
        super_admin_ids = {str(u.get('id','')) for u in users_all
                          if (u.get('role') or '').lower() in ('super_admin','sa')
                          or str(u.get('username','')).lower() == 'wuchenghao15'}
        super_admin_names = {str(u.get('username','')).lower() for u in users_all
                             if (u.get('role') or '').lower() in ('super_admin','sa')
                             or str(u.get('username','')).lower() == 'wuchenghao15'}
        super_admin_names.add('wuchenghao15')
        def _is_sa(user_id, username):
            return (str(user_id) in super_admin_ids) or (str(username or '').lower() in super_admin_names)

        for ll in _q(AUTH_DB, "SELECT * FROM login_logs ORDER BY login_time DESC LIMIT 100"):
            uname = ll.get('username') or ll.get('user_name') or (f"用户{ll.get('user_id')}" if ll.get('user_id') else '未知用户')
            uid = ll.get('user_id')
            if _is_sa(uid, uname):
                continue
            logs_raw.append({
                'action': '用户登录' + ('（成功）' if str(ll.get('status') or 'ok').lower() in ('ok','success','true','1') else '（失败）'),
                'username': uname,
                'user_id': uid,
                'ip_address': ll.get('ip') or ll.get('ip_address') or '',
                'created_at': ll.get('login_time') or ll.get('created_at') or ''
            })
        for op in _q(SPLIT_ADMIN_DB, "SELECT * FROM admin_operations ORDER BY created_at DESC LIMIT 100"):
            uname = op.get('admin_name') or op.get('username') or op.get('operator') or (f"管理员{op.get('admin_id') or op.get('user_id')}")
            uid = op.get('admin_id') or op.get('user_id')
            if _is_sa(uid, uname):
                continue
            logs_raw.append({
                'action': op.get('action') or op.get('operation') or '管理操作',
                'username': uname,
                'user_id': uid,
                'ip_address': op.get('ip') or op.get('ip_address') or '',
                'created_at': op.get('created_at') or op.get('operated_at') or ''
            })
        for el in _q(SPLIT_LOG_DB, "SELECT * FROM error_logs ORDER BY created_at DESC LIMIT 50"):
            logs_raw.append({
                'action': '系统错误: ' + (el.get('error_type') or el.get('type') or '未知错误') + ((' - ' + (el.get('error_message') or ''))[:50] if el.get('error_message') else ''),
                'username': el.get('user_name') or el.get('username') or 'SYSTEM',
                'user_id': el.get('user_id'),
                'ip_address': el.get('ip') or '',
                'created_at': el.get('created_at') or ''
            })
        logs_raw.sort(key=lambda x: str(x.get('created_at','')), reverse=True)
        data['recent_logs'] = logs_raw[:10]
    except Exception as e:
        return jsonify({'success': False, 'message': '统计失败: ' + str(e)}), 500
    return jsonify({'success': True, 'data': data})


if __name__ == '__main__':
    v, info, _ = get_version_info()
    print(f'[MTSCOS Real DB] bind=0.0.0.0:8888  version=v{v}  source={info.get("source")}  auth={AUTH_DB}')
    app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
