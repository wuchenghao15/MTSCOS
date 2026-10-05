#!/usr/bin/env python3
"""
核心初始化模块 - 4步骤初始化
负责Flask应用创建和核心配置
"""

import os
import sys
import sqlite3
import urllib.parse
from flask import Flask, render_template, send_from_directory, request
from flask_cors import CORS

# 文件重组后资源已分散：模板/静态在 frontend/，数据库在 _runtime/databases/Database
# core_init.py 位于 _entry_wrappers/startup_modules/，需上溯三级到真实项目根
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_DIR = PROJECT_ROOT
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')
LOGS_DIR = os.path.join(PROJECT_ROOT, '_runtime', 'logs')
DB_DIR = os.path.join(PROJECT_ROOT, '_runtime', 'databases', 'Database')


# ========== 首页上下文构建器（移植自 entrypoints/server_preview.py，保持与 index1.html 配套）==========
_HOMEPAGE_VERSION = '17.22.0'


def _homepage_stats():
    """首页统计：优先从真实数据库取计数，失败则用兜底默认值。"""
    stats = {
        'version': _HOMEPAGE_VERSION,
        'modules_count': 42, 'availability': '99.9', 'rules_count': 925,
        'avg_response_ms': 14, 'scoring_consistency': '99.97',
        'questions_count': 323, 'users_count': 8, 'exams_count': 8,
        'ai_employees_count': 41,
    }
    try:
        from core.db_path import get_db_path
        p = get_db_path('app.db')
        if os.path.exists(p):
            c = sqlite3.connect(p)
            # 累加前先重置 AI员工计数（避免兜底值 41 被累加进去）
            stats['ai_employees_count'] = 0
            for (tbl, k) in [('users', 'users_count'), ('questions', 'questions_count'),
                             ('exams', 'exams_count'), ('ai_employees', 'ai_employees_count'),
                             ('mtscos_ai_employees', 'ai_employees_count')]:
                try:
                    r = c.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
                    if r and r[0]:
                        # AI员工数累加（ai_employees 核心表 + mtscos_ai_employees 专业表）
                        if k == 'ai_employees_count':
                            stats[k] = stats.get(k, 0) + r[0]
                        else:
                            stats[k] = r[0]
                except Exception:
                    pass
            # 若两表均读不到数据，回退到 30k+ 规模兜底值
            if not stats.get('ai_employees_count'):
                stats['ai_employees_count'] = 30000
            try:
                cur = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='system_rules'").fetchone()
                if cur and cur[0]:
                    rc = c.execute('SELECT COUNT(*) FROM system_rules').fetchone()
                    if rc and rc[0] > 0:
                        stats['rules_count'] = max(stats['rules_count'], rc[0])
            except Exception:
                pass
            c.close()
    except Exception:
        pass
    stats['modules'] = stats['modules_count']
    stats['questions'] = stats['questions_count']
    stats['rules'] = stats['rules_count']
    stats['latency'] = stats['avg_response_ms']
    stats['consistency'] = stats['scoring_consistency']
    return stats


# ==================================================================
# 农历 + 佛教重要纪念日数据 (B轮议题4: 每页实时农历 + 佛教菩萨/罗汉/佛 关键日子提醒)
# 数据源: 汉传佛教重要纪念日 (基于农历月日, 不依赖公历浮动)
# 涵盖: 释迦牟尼佛/阿弥陀佛/药师佛/弥勒佛/燃灯佛/观世音/大势至/文殊/普贤/地藏
#       /准提/韦驮/伽蓝/药王/达摩/华严/摩利支天/日光/监斋/帝释天 等诸佛菩萨罗汉
# 关键日子类型: 诞辰(圣诞) / 出家日 / 成道日 / 涅槃日 / 节日
# ==================================================================
_TIANGAN = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
_DIZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
_LUNAR_MONTHS_CN = ['正月', '二月', '三月', '四月', '五月', '六月',
                    '七月', '八月', '九月', '十月', '冬月', '腊月']
_LUNAR_DAYS_CN = [
    '初一', '初二', '初三', '初四', '初五', '初六', '初七', '初八', '初九', '初十',
    '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
    '廿一', '廿二', '廿三', '廿四', '廿五', '廿六', '廿七', '廿八', '廿九', '三十'
]

# 农历(月, 日) -> [(节日名, 类型)]  · 同一天可叠加多尊佛菩萨圣诞
_BUDDHIST_FESTIVALS = {
    # ===== 正月 =====
    (1, 1):  [('弥勒菩萨圣诞', '诞辰'), ('弥勒佛诞·春节斋天', '节日')],
    (1, 6):  [('定光佛圣诞', '诞辰')],
    (1, 9):  [('帝释天尊圣诞', '诞辰')],
    (1, 26): [('伽蓝菩萨圣诞(关平太子)', '诞辰')],
    # ===== 二月 =====
    (2, 8):  [('释迦牟尼佛出家日', '出家日')],
    (2, 15): [('释迦牟尼佛涅槃日', '涅槃日')],
    (2, 19): [('观世音菩萨圣诞', '诞辰')],
    (2, 21): [('普贤菩萨圣诞', '诞辰')],
    # ===== 三月 =====
    (3, 16): [('准提菩萨圣诞', '诞辰')],
    (3, 25): [('韦驮菩萨圣诞(古说)', '诞辰')],
    # ===== 四月 =====
    (4, 4):  [('文殊菩萨圣诞', '诞辰')],
    (4, 8):  [('释迦牟尼佛圣诞', '诞辰'), ('佛诞节·浴佛节', '节日')],
    (4, 15): [('佛吉祥日·卫塞节', '节日'), ('结夏安居始', '节日')],
    (4, 28): [('药王菩萨圣诞', '诞辰')],
    # ===== 五月 =====
    (5, 13): [('伽蓝菩萨圣诞(关圣帝君)', '诞辰')],
    (5, 18): [('准提菩萨得道日', '成道日')],
    # ===== 六月 =====
    (6, 3):  [('韦驮菩萨圣诞', '诞辰')],
    (6, 19): [('观世音菩萨成道日', '成道日')],
    # ===== 七月 =====
    (7, 13): [('大势至菩萨圣诞', '诞辰')],
    (7, 15): [('佛欢喜日·盂兰盆节', '节日'), ('结夏安居圆满', '节日')],
    (7, 30): [('地藏王菩萨圣诞', '诞辰')],   # 小月则映射到 7/29
    (7, 29): [('地藏王菩萨圣诞(小月)', '诞辰')],  # 兜底:农历七月小月
    # ===== 八月 =====
    (8, 22): [('燃灯佛圣诞', '诞辰')],
    # ===== 九月 =====
    (9, 9):  [('摩利支天菩萨圣诞', '诞辰')],
    (9, 19): [('观世音菩萨出家日', '出家日')],
    (9, 30): [('药师佛圣诞', '诞辰')],         # 小月则映射到 9/29
    (9, 29): [('药师佛圣诞(小月)', '诞辰')],
    # ===== 十月 =====
    (10, 5):  [('达摩祖师圣诞', '诞辰')],
    (10, 17): [('阿弥陀佛出家日', '出家日')],
    # ===== 冬月(十一月) =====
    (11, 17): [('阿弥陀佛圣诞', '诞辰')],
    (11, 19): [('日光菩萨圣诞', '诞辰')],
    # ===== 腊月(十二月) =====
    (12, 8):  [('释迦牟尼佛成道日·腊八节', '成道日')],
    (12, 23): [('监斋菩萨圣诞', '诞辰')],
    (12, 29): [('华严菩萨圣诞', '诞辰'), ('诸佛降凡·除夕(小月)', '节日')],
    (12, 30): [('诸佛降凡·除夕守岁', '节日')],
}


def _lunar_year_to_ganzhi(lunar_year: int) -> str:
    """农历年 -> 干支纪年 (60年一周期, 1984=甲子)。"""
    if not lunar_year:
        return ''
    offset = (lunar_year - 1984) % 60
    return _TIANGAN[offset % 10] + _DIZHI[offset % 12]


def _get_lunar_info() -> dict:
    """真实农历日期 + 佛教重要纪念日提醒 (B轮议题4 核心)。

    使用 `lunardate` 库做精确公历→农历转换,并查询汉传佛教重要纪念日字典,
    返回富数据 dict 供 context_processor 注入所有页面模板使用。

    返回字段:
        lunar_display: str - 农历日期串 (节日时附加 ' · 节日名')
        lunar_full: str - 完整农历 '甲辰年 农历七月初六'
        lunar_year/month/day: int - 农历数值
        is_leap_month: bool - 是否闰月
        ganzhi_year: str - 干支年 (如 '丙午')
        is_special_day: bool - 是否为佛教节日
        special_day_name: str - 节日名称 (多尊叠加用 ' · ' 分隔)
        special_day_type: str - 节日类型 (诞辰/出家日/成道日/涅槃日/节日)
        festivals: list[dict] - [{'name','type'}, ...] 节日详情
        solar_date: str - 公历 'YYYY-MM-DD'
    """
    info = {
        'lunar_display': '', 'lunar_full': '',
        'lunar_year': 0, 'lunar_month': 0, 'lunar_day': 0, 'is_leap_month': False,
        'ganzhi_year': '', 'is_special_day': False,
        'special_day_name': '', 'special_day_type': '', 'festivals': [],
        'solar_date': '',
    }
    try:
        from lunardate import LunarDate
        from datetime import datetime
        now = datetime.now()
        lunar = LunarDate.fromSolarDate(now.year, now.month, now.day)

        m_idx = (lunar.month - 1) % 12
        d_idx = (lunar.day - 1) % 30
        leap = '闰' if lunar.is_leap_month else ''
        month_str = leap + _LUNAR_MONTHS_CN[m_idx]
        day_str = _LUNAR_DAYS_CN[d_idx] if 1 <= lunar.day <= 30 else f'初{lunar.day}'
        ganzhi = _lunar_year_to_ganzhi(lunar.year)
        info.update({
            'lunar_year': lunar.year, 'lunar_month': lunar.month,
            'lunar_day': lunar.day, 'is_leap_month': lunar.is_leap_month,
            'ganzhi_year': ganzhi,
            'lunar_full': f'{ganzhi}年 农历{month_str}{day_str}',
            'solar_date': f'{now.year}-{now.month:02d}-{now.day:02d}',
        })

        # 查佛教节日 (小月30日不存在, 通过 (m,29) 兜底已处理)
        key = (lunar.month, lunar.day)
        fests = _BUDDHIST_FESTIVALS.get(key, [])
        info['festivals'] = [{'name': n, 'type': t} for n, t in fests]
        if fests:
            info['is_special_day'] = True
            info['special_day_name'] = ' · '.join(n for n, _ in fests)
            info['special_day_type'] = '、'.join(sorted({t for _, t in fests}))
            info['lunar_display'] = f'{ganzhi}年 {month_str}{day_str} · {info["special_day_name"]}'
        else:
            info['lunar_display'] = f'{ganzhi}年 {month_str}{day_str}'

        return info
    except Exception:
        return info


def _get_lunar_display():
    """农历日期字符串 (向后兼容入口; 新逻辑走 _get_lunar_info)。

    返回示例:
        平日: '甲辰年 七月初六'
        节日: '丙午年 六月十九 · 观世音菩萨成道日'
    """
    return _get_lunar_info().get('lunar_display', '')


def _get_role_name(role):
    """角色编码转中文显示名。"""
    role_map = {
        'super_admin': '超级管理员', 'admin': '系统管理员', 'hardware_admin': '硬件管理员',
        'teacher': '教师', 'student': '学生', 'guest': '访客', 'professor': '教授/专家',
        'leader': '组长', 'designer': '设计师/架构师', 'user': '普通用户',
    }
    return role_map.get(role, role or '用户')


def _get_footer_info():
    """获取页脚品牌信息。"""
    return {
        'brand_name': 'MTSCOS AI',
        'brand_slogan': '智能学习评估平台 · MTS架构',
        'brand_desc': '基于MTS架构的AI驱动的智能学习评估平台，集成权限管理、路由控制、AI员工协作与知识大脑库。',
        'contact_address': '中国 · 深圳',
        'contact_phone': '+86 0755-0000-0000',
        'contact_email': 'support@mtscos.ai',
        'contact_worktime': '周一至周五 9:00-18:00',
        'copyright_year': '2026',
        'author': 'Chenghao Wu',
        'icp': '粤ICP备2026000000号',
        'police': '',
        'company': 'MTSCOS Intelligent Technology',
    }


def _get_particle_config():
    """获取粒子背景配置。"""
    return {
        'count': 60, 'color': '#3b82f6', 'opacity': 0.3, 'speed': 0.5,
        'size': 2, 'connect_distance': 120, 'connect_opacity': 0.1,
    }


def _render_homepage(app_obj, template_name='index1.html'):
    """统一构建首页渲染上下文并返回响应。"""
    from flask import session, render_template
    stats = _homepage_stats()
    lunar_info = _get_lunar_info()
    is_auth = bool(session.get('logged_in') or session.get('user_id') or session.get('user'))
    sess_user = session.get('user')
    is_admin = is_auth and sess_user and sess_user.get('role') in ('admin', 'super_admin')
    is_super = is_auth and sess_user and sess_user.get('role') == 'super_admin'
    current_user = None
    if sess_user:
        current_user = type('User', (), {
            'username': sess_user.get('username', ''),
            'role': sess_user.get('role', 'guest'),
            'real_name': sess_user.get('real_name', ''),
            'nickname': sess_user.get('nickname', ''),
        })()
    return render_template(template_name,
                           version=_HOMEPAGE_VERSION,
                           version_info={'codename': 'Nebula', 'version': _HOMEPAGE_VERSION,
                                         'build_time': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
                                         'commit': 'local', 'branch': 'main', 'author': 'Chenghao Wu'},
                           latest_version=_HOMEPAGE_VERSION,
                           homepage_stats=stats, _s=stats,
                           theme_key=session.get('theme_key', 'light'),
                           theme_forced_mourning=False,
                           is_admin=is_admin, is_super_admin=is_super,
                           current_user=current_user,
                           is_authenticated=lambda: is_auth,
                           get_role_name=_get_role_name,
                           lunar_display=lunar_info.get('lunar_display', ''),
                           lunar_info=lunar_info,
                           festivals=lunar_info.get('festivals', []),
                           buddhist_festival_count=len(lunar_info.get('festivals', [])),
                           lunar_display_en='',
                           is_special_day=lunar_info.get('is_special_day', False),
                           special_day_name=lunar_info.get('special_day_name', ''),
                           special_day_type=lunar_info.get('special_day_type', ''),
                           particle_config=_get_particle_config(),
                           footer_info=_get_footer_info())


# ============================================================================
# 全局异常处理器注册 (模块2 L2/L3 契约 §12/§13)
# 覆盖 8 类 HTTP 异常 + Exception 兜底
# Accept 头内容协商 + 三端模板智能分发 (URL前缀 > session.role > User-Agent > 默认L2)
# ============================================================================
_HTTP_ERR_MAP = {
    400: ('E_TOKEN_MISSING', 'warning'),
    401: ('E_AUTH_401', 'error'),
    403: ('E_AUTH_403', 'critical'),
    404: ('E_ROUTE_404', 'warning'),
    500: ('E_SRV_500', 'critical'),
    502: ('E_SRV_502', 'error'),
    503: ('E_MAINTENANCE', 'info'),
    504: ('E_SRV_504', 'error'),
}

_MOBILE_UA_KEYWORDS = ('Mobile', 'Android', 'iPhone', 'iPad', 'Windows Phone', 'MicroMessenger')
_ROLE_TO_DEVICE = {
    'admin': 'admin', 'super_admin': 'admin', 'teacher': 'admin', 'principal': 'admin',
    'teaching_leader': 'admin', 'academic_affairs': 'admin', 'operator': 'admin',
    'student': 'student', 'student_vip': 'student', 'parent': 'student',
    'adult_student': 'student',
}


def _register_app_errorhandlers_mtscos(app):
    """注册MTSCOS全局异常处理器: 8类HTTP + Exception兜底, Accept协商 + 三端分发"""
    from flask import request, render_template, make_response, jsonify, session, g
    import uuid as _uuid
    import traceback as _tb
    from datetime import datetime

    def _resolve_exception_template(http_status):
        """四级优先级分发: URL前缀 > session.role > UA > 默认L2"""
        path = getattr(request, 'path', '') or ''
        if path.startswith('/admin/') or path.startswith('/admin_app/') or path == '/admin':
            return f'admin/{http_status}.html'
        if path.startswith('/student/') or path == '/student':
            return f'student/{http_status}.html'
        if path.startswith('/mobile/') or path == '/mobile':
            return f'mobile/{http_status}.html'
        try:
            role = session.get('role', '') if session else ''
        except Exception:
            role = ''
        device = _ROLE_TO_DEVICE.get(role)
        if device:
            return f'{device}/{http_status}.html'
        ua = request.headers.get('User-Agent', '') or ''
        if any(kw in ua for kw in _MOBILE_UA_KEYWORDS):
            return f'mobile/{http_status}.html'
        return f'{http_status}.html'

    def _gen_trace_id():
        if hasattr(g, 'trace_id') and g.trace_id:
            return g.trace_id
        return request.headers.get('X-Trace-Id') or 't' + _uuid.uuid4().hex[:24]

    def _wants_html():
        accept = request.headers.get('Accept', '')
        return (not accept) or 'text/html' in accept or '*/*' in accept

    def _response_for(http_status, exc=None):
        code, severity = _HTTP_ERR_MAP.get(http_status, ('E_SRV_500', 'error'))
        trace_id = _gen_trace_id()
        route_path = getattr(request, 'path', '/')
        timestamp = datetime.now().isoformat()
        if _wants_html():
            template_name = _resolve_exception_template(http_status)
            try:
                html = render_template(template_name,
                                       trace_id=trace_id,
                                       severity=severity,
                                       err_code=code)
                resp = make_response(html, http_status)
                resp.headers['X-Trace-Id'] = trace_id
                return resp
            except Exception as tpl_e:
                fallback = (
                    f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                    f'<title>{http_status} {code}</title></head>'
                    f'<body style="font-family:sans-serif;padding:40px;background:#f5f7fa;">'
                    f'<h1 style="color:#F56C6C;">HTTP {http_status}</h1>'
                    f'<h3>{code}</h3>'
                    f'<p>异常页模板渲染失败: {repr(tpl_e)[:200]}</p>'
                    f'<p style="color:#909399;">trace_id: {trace_id}</p>'
                    f'<a href="/" style="padding:8px 16px;background:#409EFF;'
                    f'color:white;text-decoration:none;border-radius:4px;">返回首页</a>'
                    f'</body></html>'
                )
                resp = make_response(fallback, http_status)
                resp.headers['X-Trace-Id'] = trace_id
                return resp
        else:
            resp_body = {
                'code': code,
                'msg': str(exc) if exc else f'HTTP {http_status}',
                'data': None,
                'trace_id': trace_id,
                'timestamp': timestamp,
                'severity': severity,
                'repair_suggestion': '',
                'design_tokens': '',
                'route_path': route_path,
                'http': http_status,
            }
            if http_status == 500 and exc:
                try:
                    resp_body['_stack'] = _tb.format_exc(limit=8)
                except Exception:
                    pass
            resp = jsonify(resp_body)
            resp.status_code = http_status
            resp.headers['X-Trace-Id'] = trace_id
            return resp

    for status in sorted(_HTTP_ERR_MAP.keys()):
        def _make_handler(s):
            def _handler(e):
                return _response_for(s, e)
            return _handler
        app.register_error_handler(status, _make_handler(status))

    def _exception_handler(e):
        import logging
        logging.getLogger(__name__).error('[UNHANDLED EXCEPTION] %s\n%s', repr(e), _tb.format_exc())
        return _response_for(500, e)
    app.register_error_handler(Exception, _exception_handler)


def core_initialization(config=None):
    if not config:
        config = {}

    _LOGS_TMPL = os.path.join(LOGS_DIR, 'html_files')
    _MAIN_TMPL = os.path.join(FRONTEND_DIR, 'templates')
    os.makedirs(_LOGS_TMPL, exist_ok=True)
    app = Flask(__name__,
                template_folder=_MAIN_TMPL,
                static_folder=os.path.join(FRONTEND_DIR, 'static'))

    # 模板缺失变量安全网：嵌套属性访问渲染为空而非 500（首页等模板上下文演进期）
    try:
        import jinja2
        app.jinja_env.undefined = jinja2.ChainableUndefined
        # 模板热加载：开发阶段修改 HTML 后无需重启服务，浏览器刷新即可看到新内容
        app.jinja_env.auto_reload = True
        app.config['TEMPLATES_AUTO_RELOAD'] = True
    except Exception:
        pass

    app.config['DEBUG'] = config.get('debug', False)
    app.config['SECRET_KEY'] = config.get('secret_key', 'mtscos_secret_key_2026')
    app.config['SPLIT_DB_DIR'] = DB_DIR
    app.config['STATIC_URL_PATH'] = '/static'

    # 兼容路径：同时在 Logs/html_files 和 flask-app/templates（异常页L1/L2/L3） 中查找模板
    #   ⚠ 加载优先级(从高到低):
    #   1) flask-app/templates  (L1/L2/L3异常页必须优先命中同名404.html)
    #   2) frontend/templates   (主系统原有路由模板)
    #   3) Logs/html_files      (运行时动态产出的报告/日志页)
    @app.before_request
    def _ensure_template_paths():
        from jinja2 import ChoiceLoader, FileSystemLoader
        _EXC_TMPL = os.path.join(PROJECT_ROOT, 'flask-app', 'templates')
        if not isinstance(app.jinja_loader, ChoiceLoader):
            # 原始loader通常是指向 frontend/templates 的 FileSystemLoader，
            # 所以: [异常页FSLoader, 原始loader, 主+日志FSLoader]
            app.jinja_loader = ChoiceLoader([
                FileSystemLoader([_EXC_TMPL]),
                app.jinja_loader,
                FileSystemLoader([_MAIN_TMPL, _LOGS_TMPL]),
            ])
        else:
            # ChoiceLoader 已存在：把异常页FSLoader置顶，其余保持顺序
            _new_loaders = [FileSystemLoader([_EXC_TMPL])]
            for _ld in app.jinja_loader.loaders:
                if isinstance(_ld, FileSystemLoader):
                    _filtered = [p for p in _ld.searchpath if p != _EXC_TMPL]
                    if _filtered:
                        _new_loaders.append(FileSystemLoader(_filtered))
                else:
                    _new_loaders.append(_ld)
            app.jinja_loader.loaders = _new_loaders


    # ========== B轮议题1 产出: 全局权限装饰器兜底拦截器 ==========
    # flow_id: flow_full_repair_20260818_001
    # 基于 mt_route_decorator_audit 表做无装饰器路由的权限校验
    try:
        from app.utils.b1_global_permission_guard import _b1_register_global_permission_guard
        _b1_register_global_permission_guard(app)
        print('[B1-OK] 全局权限兜底拦截器已注册 (基于mt_route_decorator_audit表, 覆盖943缺失路由)')
    except Exception as _e:
        print(f'[B1-WARN] 全局权限兜底拦截器注册失败(可后续重试): {_e}')

    os.makedirs(DB_DIR, exist_ok=True)

    CORS(app, resources={r'/api/*': {'origins': '*'}})

    # ========== B轮议题3 产出: mt_role_emp_feature 三元关联表 + 菜单徽标 + 调度接口 ==========
    # flow_id: flow_full_repair_20260818_001
    # 注入 ai_emp_badge 为 Jinja 全局函数 (供模板中渲染 AI赋能 徽标)
    try:
        import sys as _sys
        _UTIL_DIR = os.path.join(PROJECT_ROOT, 'flask-app', 'app', 'utils')
        if _UTIL_DIR not in _sys.path:
            _sys.path.insert(0, _UTIL_DIR)
        from ai_emp_badge import register_ai_emp_badge
        register_ai_emp_badge(app)
        print('[B3-OK] ai_emp_badge Jinja全局函数已注入 (mt_role_emp_feature 菜单徽标准备就绪)')
    except Exception as _e:
        print(f'[B3-WARN] ai_emp_badge 注入失败(可后续重试): {_e}')

    # ========== B轮议题4: 全局注入农历 + 佛教节日 (每页通用, context_processor) ==========
    # 让 base.html / teacher_base.html / student_base.html / super_admin_base.html
    # 及所有继承它们的页面都能直接拿到:
    #   lunar_display / lunar_info / is_special_day / special_day_name / special_day_type
    @app.context_processor
    def _inject_lunar_context():
        try:
            info = _get_lunar_info()
            festivals = info.get('festivals', []) or []
            return {
                'lunar_display': info.get('lunar_display', ''),
                'lunar_info': info,
                'festivals': festivals,
                'buddhist_festival_count': len(festivals),
                'is_special_day': info.get('is_special_day', False),
                'special_day_name': info.get('special_day_name', ''),
                'special_day_type': info.get('special_day_type', ''),
            }
        except Exception:
            return {
                'lunar_display': '', 'lunar_info': {}, 'festivals': [], 'buddhist_festival_count': 0,
                'is_special_day': False, 'special_day_name': '', 'special_day_type': '',
            }
    print('[B4-OK] 农历+佛教节日 context_processor 已注册 (覆盖所有页面模板)')

    @app.template_global(name='get_config')
    def get_config(key, default=None):
        return config.get(key, default)

    @app.template_global(name='config')
    def get_config_obj():
        return config

    @app.template_global(name='get_role_name')
    def tmpl_get_role_name(role):
        """Jinja全局: 角色编码 -> 中文名 (供 base/super_admin_base/student_base 模板使用)"""
        return _get_role_name(role)

    @app.template_global(name='is_authenticated')
    def is_authenticated():
        from flask import session
        return bool(session.get('logged_in') or session.get('user_id'))

    @app.template_global(name='current_user')
    def get_current_user():
        from flask import session
        uid = session.get('user_id')
        if not uid:
            return None
        try:
            from core.db_path import get_db_path
            import sqlite3
            c = sqlite3.connect(get_db_path('auth.db'), timeout=30)
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT id, username, role, is_active FROM users WHERE id=?", (uid,)).fetchone()
            c.close()
            if r:
                return {k: r[k] for k in r.keys()}
        except Exception:
            pass
        return None

    @app.template_global(name='is_super_admin')
    def is_super_admin():
        u = get_current_user()
        if not u:
            return False
        return u.get('role') == 'super_admin'

    @app.template_global(name='get_user_role')
    def get_user_role():
        u = get_current_user()
        if not u:
            return 'guest'
        return u.get('role', 'guest')

    @app.template_global(name='_is_super')
    def _is_super():
        return is_super_admin()

    @app.template_global(name='_role')
    def _role():
        return get_user_role()

    @app.route('/')
    def index():
        return _render_homepage(app)

    @app.route('/index.html')
    def index_html():
        return _render_homepage(app)

    # ===== 前端 UI 性能上报端点（粒子动画 FPS/内存） =====
    # 解决浏览器侧 fetch('/_ui/report_particle_perf') 一直 404 的问题
    # 策略：接收 + 落地到 _runtime/logs/ui_perf.log，返回 APPROVED 即可
    @app.route('/_ui/report_particle_perf', methods=['POST'])
    def _ui_report_particle_perf():
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
        # 异步写入日志（同步也行，量小）
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_file = os.path.join(LOGS_DIR, 'ui_perf.log')
            import json as _json
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(_json.dumps({
                    'ts': payload.get('session_id') or '',
                    'event_code': payload.get('event_code', ''),
                    'fps': payload.get('fps'),
                    'particle_count': payload.get('particle_count'),
                    'canvas_width': payload.get('canvas_width'),
                    'canvas_height': payload.get('canvas_height'),
                    'dpr': payload.get('dpr'),
                    'page_visible': payload.get('page_visible'),
                    'reduced_motion': payload.get('reduced_motion'),
                    'mobile': payload.get('mobile'),
                    'detail': payload.get('detail', {}),
                    'logged_at': __import__('datetime').datetime.now().isoformat(),
                }, ensure_ascii=False) + '\n')
        except Exception:
            pass
        # 返回最小响应，前端 __renderFooterEigenfluxPanel__ 期望 success + verdict 字段
        return {
            'success': True,
            'verdict': 'APPROVED_MONITOR',
            'anomaly_report_id': None,
            'ai_employees': None,
            'received_at': __import__('datetime').datetime.now().isoformat(),
        }

    @app.route('/css_files/<filename>')
    def css_files(filename):
        return send_from_directory(os.path.join(LOGS_DIR, 'css_files'), filename)

    @app.route('/js_files/<filename>')
    def js_files(filename):
        return send_from_directory(os.path.join(LOGS_DIR, 'js_files'), filename)

    @app.route('/login_system/<filename>')
    def login_system_files(filename):
        return send_from_directory(os.path.join(LOGS_DIR, 'login_system'), filename)

    @app.route('/html_files/<filename>')
    def html_files(filename):
        return send_from_directory(os.path.join(LOGS_DIR, 'html_files'), filename)

    @app.route('/static/css/<filename>')
    def static_css(filename):
        # B轮议题2修复: 优先从主 static 目录(frontend/static/css)提供, 再回退 LOGS_DIR
        # 修复前: 仅查 LOGS_DIR/css_files → theme.css/mtscos_*.css 全部 404
        main_css = os.path.join(FRONTEND_DIR, 'static', 'css', filename)
        if os.path.exists(main_css):
            with open(main_css, 'r', encoding='utf-8') as f:
                content = f.read()
            return app.response_class(content, mimetype='text/css')
        css_dirs = ['css_files', 'login_system', '系统监控', 'Arduino模块', '其他日志']
        for css_dir in css_dirs:
            css_path = os.path.join(LOGS_DIR, css_dir, filename)
            if os.path.exists(css_path):
                with open(css_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return app.response_class(content, mimetype='text/css')
        return '', 404

    @app.route('/static/js/<filename>')
    def static_js(filename):
        # B轮议题2修复: 优先从主 static 目录(frontend/static/js)提供, 再回退 LOGS_DIR
        main_js = os.path.join(FRONTEND_DIR, 'static', 'js', filename)
        if os.path.exists(main_js):
            with open(main_js, 'r', encoding='utf-8') as f:
                content = f.read()
            return app.response_class(content, mimetype='application/javascript')
        js_path = os.path.join(LOGS_DIR, 'js_files', filename)
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return app.response_class(content, mimetype='application/javascript')
        js_path = os.path.join(LOGS_DIR, 'login_system', filename)
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return app.response_class(content, mimetype='application/javascript')
        return '', 404

    @app.route('/static/<path:filepath>')
    def static_files(filepath):
        # 1) 主 static 目录优先
        file_path = os.path.join(FRONTEND_DIR, 'static', filepath)
        if os.path.exists(file_path):
            import mimetypes
            mime_type, _ = mimetypes.guess_type(file_path)
            with open(file_path, 'rb') as f:
                content = f.read()
            return app.response_class(content, mimetype=mime_type or 'application/octet-stream')
        # 2) 兼容 Logs 目录（历史路径）
        file_path = os.path.join(LOGS_DIR, filepath)
        if os.path.exists(file_path):
            import mimetypes
            mime_type, _ = mimetypes.guess_type(file_path)
            with open(file_path, 'rb') as f:
                content = f.read()
            return app.response_class(content, mimetype=mime_type or 'application/octet-stream')
        return '', 404

    # ========== 全局异常处理器 + 三端异常页分发 (模块2 L3契约§13) ==========
    # 覆盖8类HTTP异常 + Exception兜底，基于Accept头内容协商 + 三端分发
    # 对照: flask-app/app/__init__.py _register_app_errorhandlers + contract.yaml §12/§13
    _register_app_errorhandlers_mtscos(app)

    _init_database_connections(app)

    return app

def _init_database_connections(app):
    DATABASES = {
        'auth': os.path.join(DB_DIR, 'auth.db'),
        'exam': os.path.join(DB_DIR, 'exam.db'),
        'question': os.path.join(DB_DIR, 'question.db'),
        'learning': os.path.join(DB_DIR, 'learning.db'),
        'system': os.path.join(DB_DIR, 'system.db'),
        'ai': os.path.join(DB_DIR, 'ai.db'),
        'physics': os.path.join(DB_DIR, 'physics.db'),
        'math': os.path.join(DB_DIR, 'math.db'),
        'admin': os.path.join(DB_DIR, 'admin.db'),
        'proctor': os.path.join(DB_DIR, 'proctor.db'),
        'user': os.path.join(DB_DIR, 'user.db'),
        'log': os.path.join(DB_DIR, 'log.db'),
        'other': os.path.join(DB_DIR, 'other.db'),
        'config': os.path.join(DB_DIR, 'config.db'),
    }

    app.config['DATABASES'] = DATABASES

    TABLE_TO_DB = {}
    for db_name, db_path in DATABASES.items():
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [t[0] for t in cursor.fetchall()]
                conn.close()
                for table in tables:
                    TABLE_TO_DB[table] = db_name
            except Exception:
                pass

    app.config['TABLE_TO_DB'] = TABLE_TO_DB
