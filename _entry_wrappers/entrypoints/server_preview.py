#!/usr/bin/env python3
"""Minimal Flask server for login page preview - no DB required"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    from app.version import VERSION, VERSION_INFO, get_version_info, get_latest_version
except Exception:
    VERSION = '17.22.0'
    def get_version_info():
        return {
            'version': VERSION,
            'build_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'commit': 'local-preview',
            'branch': 'main',
            'author': 'Chenghao Wu',
        }
    def get_latest_version():
        return VERSION

from flask import Flask, render_template, request, jsonify, redirect, url_for

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), '_entry_wrappers', 'startup_modules'))
    from db_runtime_loader import load_runtime_data
except Exception:
    def load_runtime_data(db_path=None):
        return {
            'system_parameters': {},
            'ai_employees': [],
            'ai_agents': [],
            'hooks': [],
            'automation_plans': [],
            'eigenflux_ai': {'enabled': False},
            'eigenflux_experts': [],
        }

_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), 'frontend')
app = Flask(__name__, template_folder=os.path.join(_FRONTEND_DIR, 'templates'),
            static_folder=os.path.join(_FRONTEND_DIR, 'static'))
app.secret_key = 'mtscos-preview-secret'
app.config['RUNTIME_DATA'] = load_runtime_data()
app.config['DB_RUNTIME'] = app.config['RUNTIME_DATA']

# 禁用Jinja2模板缓存 + 开启模板自动重载（确保首页配色修改立即生效）
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.cache = None

def _clear_template_cache():
    try:
        loader = app.jinja_loader
        if hasattr(loader, 'reset'):
            loader.reset()
    except Exception:
        pass


def _default_homepage_stats():
    stats = {
        'version': VERSION or '17.22.0',
        'modules_count': 42,
        'availability': '99.9',
        'rules_count': 925,
        'avg_response_ms': 14,
        'scoring_consistency': '99.97',
        'questions_count': 323,
        'users_count': 8,
        'exams_count': 8,
        'ai_employees_count': 41,
    }
    try:
        from core.db_path import get_db_path
        import sqlite3
        p = get_db_path('app.db')
        if os.path.exists(p):
            c = sqlite3.connect(p)
            for (tbl, k) in [('users', 'users_count'), ('questions', 'questions_count'),
                             ('exams', 'exams_count'), ('ai_employees', 'ai_employees_count')]:
                try:
                    r = c.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
                    if r: stats[k] = r[0] or stats[k]
                except Exception:
                    pass
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


# ---- 辅助函数：获取农历/佛教节日/角色名/认证状态 ----
def _get_lunar_info():
    """返回真实农历日期与佛教纪念日信息，供所有页面使用。"""
    info = {
        'lunar_display': '',
        'lunar_full': '',
        'lunar_year': 0,
        'lunar_month': 0,
        'lunar_day': 0,
        'is_leap_month': False,
        'ganzhi_year': '',
        'is_special_day': False,
        'special_day_name': '',
        'special_day_type': '',
        'festivals': [],
        'solar_date': '',
    }
    try:
        from datetime import datetime
        try:
            from lunardate import LunarDate
            now = datetime.now()
            lunar = LunarDate.from_solar_date(now.year, now.month, now.day)
            lunar_months = ['正月','二月','三月','四月','五月','六月','七月','八月','九月','十月','冬月','腊月']
            lunar_days = ['初一','初二','初三','初四','初五','初六','初七','初八','初九','初十',
                          '十一','十二','十三','十四','十五','十六','十七','十八','十九','二十',
                          '廿一','廿二','廿三','廿四','廿五','廿六','廿七','廿八','廿九','三十']
            m_idx = (lunar.month - 1) % 12
            d_idx = (lunar.day - 1) % 30
            month_str = ('闰' if lunar.is_leap_month else '') + lunar_months[m_idx]
            day_str = lunar_days[d_idx] if 1 <= lunar.day <= 30 else f'初{lunar.day}'
            info.update({
                'lunar_year': lunar.year,
                'lunar_month': lunar.month,
                'lunar_day': lunar.day,
                'is_leap_month': lunar.is_leap_month,
                'ganzhi_year': '',
                'lunar_full': f'{month_str}{day_str}',
                'solar_date': f'{now.year}-{now.month:02d}-{now.day:02d}',
            })
            festivals = []
            key = (lunar.month, lunar.day)
            buddhist_map = {
                (1, 1): [('弥勒菩萨圣诞', '诞辰')],
                (2, 19): [('观世音菩萨圣诞', '诞辰')],
                (4, 8): [('释迦牟尼佛圣诞', '诞辰')],
                (6, 19): [('观世音菩萨成道日', '成道日')],
                (7, 15): [('佛欢喜日·盂兰盆节', '节日')],
                (9, 30): [('药师佛圣诞', '诞辰')],
                (12, 8): [('释迦牟尼佛成道日·腊八节', '成道日')],
            }
            festivals = buddhist_map.get(key, [])
            if festivals:
                info['is_special_day'] = True
                info['special_day_name'] = ' · '.join(name for name, _ in festivals)
                info['special_day_type'] = '、'.join(sorted({typ for _, typ in festivals}))
                info['lunar_display'] = f'{month_str}{day_str} · {info["special_day_name"]}'
            else:
                info['lunar_display'] = f'{month_str}{day_str}'
            info['festivals'] = [{'name': name, 'type': typ} for name, typ in festivals]
        except Exception:
            now = datetime.now()
            info['solar_date'] = now.strftime('%Y-%m-%d')
            info['lunar_display'] = now.strftime('%Y-%m-%d')
    except Exception:
        pass
    return info


def _get_lunar_display():
    """获取农历日期显示"""
    return _get_lunar_info().get('lunar_display', '')

def _get_role_name(role):
    """角色编码转中文显示名"""
    role_map = {
        'super_admin': '超级管理员',
        'admin': '系统管理员',
        'hardware_admin': '硬件管理员',
        'teacher': '教师',
        'student': '学生',
        'guest': '访客',
        'professor': '教授/专家',
        'leader': '组长',
        'designer': '设计师/架构师',
        'user': '普通用户'
    }
    return role_map.get(role, role or '用户')

def _is_authenticated():
    """检查用户是否已登录（预览模式：基于session）"""
    from flask import session
    return 'user' in session

def _get_footer_info():
    """获取页脚品牌信息"""
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
        'company': 'MTSCOS Intelligent Technology'
    }

def _get_particle_config():
    """获取粒子背景配置"""
    return {
        'count': 60,
        'color': '#3b82f6',
        'opacity': 0.3,
        'speed': 0.5,
        'size': 2,
        'connect_distance': 120,
        'connect_opacity': 0.1
    }

@app.route('/')
def index():
    _clear_template_cache()
    from flask import session
    version_info = get_version_info()
    latest_version = get_latest_version()
    stats = _default_homepage_stats()

    # 检查登录状态
    user = session.get('user')
    is_auth = user is not None
    is_admin = is_auth and user.get('role') in ('admin', 'super_admin')
    is_super = is_auth and user.get('role') == 'super_admin'

    # 构造 current_user 对象
    current_user = type('User', (), {
        'username': user.get('username', '') if user else '',
        'role': user.get('role', 'guest') if user else 'guest',
        'real_name': user.get('real_name', '') if user else '',
        'nickname': user.get('nickname', '') if user else '',
    })() if user else None

    lunar_info = _get_lunar_info()
    return render_template('index1.html',
                           version=VERSION,
                           version_info=version_info,
                           latest_version=latest_version,
                           homepage_stats=stats,
                           _s=stats,
                           # 主题参数
                           theme_key=session.get('theme_key', 'light'),
                           theme_forced_mourning=False,
                           # 权限参数
                           is_admin=is_admin,
                           is_super_admin=is_super,
                           current_user=current_user,
                           is_authenticated=_is_authenticated,
                           get_role_name=_get_role_name,
                           # 农历/特殊日期
                           lunar_display=lunar_info.get('lunar_display', ''),
                           lunar_info=lunar_info,
                           festivals=lunar_info.get('festivals', []),
                           buddhist_festival_count=len(lunar_info.get('festivals', [])),
                           lunar_display_en='',
                           is_special_day=lunar_info.get('is_special_day', False),
                           special_day_name=lunar_info.get('special_day_name', ''),
                           special_day_type=lunar_info.get('special_day_type', ''),
                           # 粒子配置
                           particle_config=_get_particle_config(),
                           # 页脚品牌信息
                           footer_info=_get_footer_info())


@app.route('/api/homepage/stats')
def api_homepage_stats():
    try:
        return jsonify({'success': True, 'stats': _default_homepage_stats()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    from flask import session
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        if not username or not password:
            return jsonify({'success': False, 'message': '请输入用户名和密码'}), 400
        if username == 'admin' and password == 'admin123':
            session['user'] = {'username': username, 'role': 'admin', 'real_name': '管理员', 'nickname': 'Admin'}
            return jsonify({'success': True, 'message': '登录成功', 'redirect': '/dashboard',
                            'user': {'username': username, 'role': 'admin'}})
        if username == 'wuchenghao15' and password == 'admin123':
            session['user'] = {'username': username, 'role': 'super_admin', 'real_name': '吴成浩', 'nickname': 'wch15'}
            return jsonify({'success': True, 'message': '登录成功', 'redirect': '/dashboard',
                            'user': {'username': username, 'role': 'super_admin'}})
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401
    return redirect('/')

@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        if not username or not password:
            return jsonify({'success': False, 'message': '请填写用户名和密码'}), 400
        return jsonify({'success': True, 'message': '注册成功（预览模式，无需写入DB）',
                        'redirect': '/'})
    try:
        return render_template('register.html', version=VERSION)
    except Exception:
        return redirect('/')

@app.route('/auth/logout')
def logout():
    from flask import session
    session.pop('user', None)
    return redirect('/')

@app.route('/dashboard')
def dashboard():
    try:
        return render_template('dashboard.html', version=VERSION)
    except Exception:
        return '<h2 style="font-family:sans-serif;padding:40px;">✅ 登录成功 · Dashboard 占位页（MTSCOS v%s）</h2><p><a href="/">返回登录</a></p>' % VERSION

@app.route('/api/health')
def health():
    return jsonify({'status': 'healthy', 'version': VERSION, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'runtime': {
        'ai_employees': len(app.config.get('RUNTIME_DATA', {}).get('ai_employees', [])),
        'ai_agents': len(app.config.get('RUNTIME_DATA', {}).get('ai_agents', [])),
        'hooks': len(app.config.get('RUNTIME_DATA', {}).get('hooks', [])),
        'automation_plans': len(app.config.get('RUNTIME_DATA', {}).get('automation_plans', [])),
        'eigenflux_enabled': app.config.get('RUNTIME_DATA', {}).get('eigenflux_ai', {}).get('enabled', False),
        'eigenflux_experts': len(app.config.get('RUNTIME_DATA', {}).get('eigenflux_experts', [])),
    }})

@app.route('/api/system/runtime')
def system_runtime():
    return jsonify({'success': True, 'data': app.config.get('RUNTIME_DATA', {})})

if __name__ == '__main__':
    print(f'[MTSCOS Preview] Starting on http://0.0.0.0:8888  version={VERSION}')
    app.run(host='127.0.0.1', port=8888, debug=False, threaded=True)
