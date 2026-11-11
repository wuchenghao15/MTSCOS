"""admin_routes — 管理后台 Blueprint
================================================================
源码参考: server_real_db.py L10569-L18974 (~12路由)

当前实现：
  - GET /admin           → 管理后台入口 (重定向到 /admin_app/dashboard)
  - GET /admin/dashboard → 管理员仪表盘 (重定向到 /admin_app/dashboard)
  - GET /admin/center    → 管理中心功能导航矩阵
  - GET /student/home    → 学生主页（Jinja 模板，整合考试/学习/学分/职业/AI 模块）
  - GET /student_portal  → 学生门户兼容入口（重定向到 /student/home）

以下路由已在 server_real_db.py 中实现, 不再需要迁移:
  /admin_dashboard /admin_app/ /admin_app/login /admin_app/process_monitor
  /admin_app/inspection_report /admin_app/inspection_settings
  /admin/student_behavior /admin/tournament
"""
from __future__ import annotations

import html
import os
import sqlite3
import time
from datetime import datetime

from flask import Blueprint, jsonify, jsonify, redirect, render_template, session

from . import admin_bp


# ===== STEP_7 数据绑定类: 管理中心核心数据概览 (数据库为唯一权威源, 实时聚合) =====
def _get_admin_center_stats() -> dict:
    """管理中心 stats-bar 5 项统计 — 从主库实时聚合, 失败返回 0 (禁止假数据).

    供 admin_center.html 模板消费: total_users/total_questions/total_exams/total_courses/total_ai
    """
    stats = {'total_users': 0, 'total_questions': 0, 'total_exams': 0,
             'total_courses': 0, 'total_ai': 0}
    try:
        try:
            from core.db_path import get_db_path
            db_path = get_db_path('app.db')
        except Exception:
            # 回退: admin_routes.py → routes → flask-app → 项目根 → _runtime/databases/Database/app.db
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                '_runtime', 'databases', 'Database', 'app.db')
        if not os.path.exists(db_path):
            return stats
        conn = sqlite3.connect('file:' + db_path + '?mode=ro', uri=True, timeout=3)
        cur = conn.cursor()
        # 用户总数
        try:
            r = cur.execute('SELECT COUNT(*) FROM "users"').fetchone()
            if r and r[0]:
                stats['total_users'] = r[0]
        except Exception:
            pass
        # 题库题目 (多表累加, 覆盖主题库/AI题库/职业考试题库)
        for t in ('questions', 'question_bank_items', 'ai_question_bank',
                  'professional_exam_questions'):
            try:
                r = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
                if r and r[0]:
                    stats['total_questions'] += r[0]
            except Exception:
                pass
        # 考试/测试 (多表累加)
        for t in ('exams', 'teacher_exams', 'exam_sessions'):
            try:
                r = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
                if r and r[0]:
                    stats['total_exams'] += r[0]
            except Exception:
                pass
        # 课程
        for t in ('courses', 'edu_courses'):
            try:
                r = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
                if r and r[0]:
                    stats['total_courses'] += r[0]
            except Exception:
                pass
        # AI员工 (核心表 ai_employees + 专业表 mtscos_ai_employees 累加)
        for t in ('ai_employees', 'mtscos_ai_employees'):
            try:
                r = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
                if r and r[0]:
                    stats['total_ai'] += r[0]
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return stats


def _common_page_html(title: str, body_html: str, session_info: dict) -> str:
    """生成通用 HTML 页面（自包含，无外部依赖）"""
    nav_user = html.escape(str(session_info.get('username', '未知')))
    nav_role = html.escape(str(session_info.get('role', '未知')))
    nav_role_canonical = html.escape(str(session_info.get('role_canonical', 'user')))
    nav_login_time = session_info.get('login_time', 0)
    nav_login_str = datetime.fromtimestamp(nav_login_time).strftime('%Y-%m-%d %H:%M:%S') if nav_login_time else '未知'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} - MTSCOS</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; background: #0a0e1a; color: #f8fafc; min-height: 100vh; }}
  .topbar {{ background: linear-gradient(135deg, #1e293b, #0f172a); padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }}
  .topbar h1 {{ font-size: 20px; color: #60a5fa; }}
  .user-box {{ font-size: 14px; color: #cbd5e1; }}
  .user-box span {{ color: #94a3b8; margin-right: 12px; }}
  .container {{ max-width: 1200px; margin: 32px auto; padding: 0 24px; }}
  .card {{ background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(8px); border: 1px solid #334155; border-radius: 12px; padding: 24px; margin-bottom: 20px; }}
  .card h2 {{ font-size: 18px; color: #60a5fa; margin-bottom: 12px; }}
  .card p {{ color: #cbd5e1; line-height: 1.6; margin-bottom: 8px; }}
  .card ul {{ list-style: none; padding: 0; }}
  .card li {{ padding: 8px 0; border-bottom: 1px solid #1e293b; }}
  .card li:last-child {{ border-bottom: none; }}
  .card a {{ color: #60a5fa; text-decoration: none; }}
  .card a:hover {{ text-decoration: underline; }}
  .badge {{ display: inline-block; padding: 2px 8px; background: #1e40af; color: #dbeafe; border-radius: 4px; font-size: 12px; margin-left: 8px; }}
  .logout-form {{ display: inline; }}
  .logout-btn {{ background: #dc2626; color: white; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
  .logout-btn:hover {{ background: #b91c1c; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>MTSCOS AI 系统</h1>
  <div class="user-box">
    <span>👤 {nav_user}</span>
    <span>🎭 {nav_role}<span class="badge">{nav_role_canonical}</span></span>
    <span>🕐 {nav_login_str}</span>
    <form class="logout-form" method="POST" action="/auth/logout">
      <button class="logout-btn" type="submit">退出登录</button>
    </form>
  </div>
</div>
<div class="container">
{body_html}
</div>
</body>
</html>"""


@admin_bp.route('/admin', methods=['GET'])
def admin_entry():
    """管理后台入口 — 重定向到功能完善的管理仪表盘

    - 未登录 → 重定向到首页
    - 已登录但非管理员 → 返回 403
    - 已登录管理员 → 重定向到 /admin_app/dashboard
    """
    if not session.get('logged_in'):
        return redirect('/')

    role_canonical = session.get('role_canonical', 'user')
    if role_canonical not in ('super_admin', 'admin', 'system_admin', 'hardware_admin'):
        body = """
<div class="card">
  <h2>⛔ 权限不足</h2>
  <p>您当前的角色无权访问管理后台。</p>
  <p><a href="/">返回首页</a></p>
</div>"""
        return _common_page_html('管理后台 - 权限不足', body, dict(session)), 403

    return redirect('/admin_app/dashboard')


# ===== STEP_7 路由类修复: 补注册 P0 管理页路由 (原 server_real_db.py L11536 等 TODO 项) =====
# flow_id: flow_full_repair_20260818_001 | 立即适配生效
_ADMIN_ROLES = ('super_admin', 'admin', 'system_admin', 'hardware_admin')


def _admin_user_ctx() -> dict:
    """构建管理端用户上下文 (供 super_admin_base.html 侧边栏渲染)"""
    login_time = session.get('login_time') or time.time()
    return {
        'user_id': session.get('user_id', 0),
        'username': session.get('username', '未知'),
        'role': session.get('role', 'admin'),
        'role_canonical': session.get('role_canonical', 'admin'),
        'login_time': login_time,
        'login_time_str': datetime.fromtimestamp(login_time).strftime('%Y-%m-%d %H:%M:%S'),
        'session_id': session.get('auth_method', 'password'),
        'auth_method': session.get('auth_method', 'password'),
    }


@admin_bp.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    """管理员仪表盘 — 重定向到 /admin_app/dashboard (功能完善的仪表盘模板)

    - 未登录 → 重定向首页
    - 已登录但非管理员 → 403
    - 已登录管理员 → 重定向到 /admin_app/dashboard
    """
    if not session.get('logged_in'):
        return redirect('/')
    if session.get('role_canonical', 'user') not in _ADMIN_ROLES:
        return _common_page_html('仪表盘 - 权限不足',
                                 '<div class="card"><h2>⛔ 权限不足</h2><p>仅管理员可访问仪表盘。</p><p><a href="/">返回首页</a></p></div>',
                                 dict(session)), 403
    return redirect('/admin_app/dashboard')


@admin_bp.route('/admin/center', methods=['GET'])
def admin_center():
    """管理中心 · 功能导航矩阵 — 渲染 admin_center.html (继承 super_admin_base, 已注入 Design Token)

    - 未登录 → 重定向首页
    - 已登录但非管理员 → 403
    - 已登录管理员 → 渲染管理中心模板
    """
    if not session.get('logged_in'):
        return redirect('/')
    if session.get('role_canonical', 'user') not in _ADMIN_ROLES:
        return _common_page_html('管理中心 - 权限不足',
                                 '<div class="card"><h2>⛔ 权限不足</h2><p>仅管理员可访问管理中心。</p><p><a href="/">返回首页</a></p></div>',
                                 dict(session)), 403
    today = datetime.now().strftime('%Y年%m月%d日 %A')
    # STEP_7 数据绑定: 注入管理中心核心数据概览 (5项统计, 数据库实时聚合)
    stats = _get_admin_center_stats()
    return render_template('admin_center.html',
                           user=_admin_user_ctx(), today=today,
                           user_stats=stats,
                           total_users=stats['total_users'],
                           total_questions=stats['total_questions'],
                           total_exams=stats['total_exams'],
                           total_courses=stats['total_courses'],
                           total_ai=stats['total_ai'],
                           sa_proprietary=True,
                           layout_mode='SA_PROPRIETARY')


# ===== STEP_7 路由类: 下划线别名 → 斜杠规范路径 (兼容 super_admin_base 旧菜单href) =====
@admin_bp.route('/admin_center', methods=['GET'])
def admin_center_alias():
    """管理中心 - 下划线别名重定向到 /admin/center (RESTful 规范)"""
    return redirect('/admin/center', code=302)


@admin_bp.route('/admin_dashboard', methods=['GET'])
def admin_dashboard_alias():
    """管理员仪表盘 - 下划线别名重定向到 /admin/dashboard (RESTful 规范)"""
    return redirect('/admin/dashboard', code=302)


@admin_bp.route('/student/home', methods=['GET'])
def student_home():
    """学生主页（Jinja 模板，整合考试/学习/学分/职业/AI 模块）

    - 未登录 → 重定向到首页
    - 已登录但非学生 → 重定向到对应入口（管理员→/admin，其他→/）
    - 已登录学生 → 渲染 student_home.html 模板（含 user 上下文）
    """
    if not session.get('logged_in'):
        return redirect('/')

    role_canonical = session.get('role_canonical', 'user')
    if role_canonical != 'student':
        if role_canonical in ('super_admin', 'admin', 'system_admin'):
            return redirect('/admin')
        return redirect('/')

    login_time = session.get('login_time') or time.time()
    user_ctx = {
        'user_id': session.get('user_id', 0),
        'username': session.get('username', '未知'),
        'role': session.get('role', 'student'),
        'role_canonical': role_canonical,
        'login_time': login_time,
        'login_time_str': datetime.fromtimestamp(login_time).strftime('%Y-%m-%d %H:%M:%S'),
        'session_id': session.get('auth_method', 'password'),
        'auth_method': session.get('auth_method', 'password'),
    }
    today = datetime.now().strftime('%Y年%m月%d日 %A')
    return render_template('student_home.html', user=user_ctx, today=today)


@admin_bp.route('/student_portal', methods=['GET'])
def student_portal():
    """学生门户兼容入口（重定向到 /student/home）

    - 未登录 → 重定向到首页
    - 已登录非学生 → 重定向到对应入口
    - 已登录学生 → 重定向到 /student/home
    """
    if not session.get('logged_in'):
        return redirect('/')

    role_canonical = session.get('role_canonical', 'user')
    if role_canonical != 'student':
        if role_canonical in ('super_admin', 'admin', 'system_admin'):
            return redirect('/admin')
        return redirect('/')

    return redirect('/student/home')


# ===== STEP_7 功能/API类: 仪表盘统计接口 (修复 admin_dashboard.html JS fetch 404) =====
def _dashboard_db_path() -> str:
    """获取主库路径 (复用 core.db_path, 回退到相对路径推算)"""
    try:
        from core.db_path import get_db_path
        return get_db_path('app.db')
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            '_runtime', 'databases', 'Database', 'app.db')


def _get_dashboard_data() -> dict:
    """仪表盘统计实时聚合 (数据库为唯一权威源, 禁止假数据).

    供 admin_dashboard.html JS fetch('/api/admin/dashboard_stats') 消费.
    """
    data = {
        'user_count': 0, 'active_users': 0, 'exams_count': 0,
        'questions_count': 0, 'completed_exams': 0, 'learning_records': 0,
        'today_logins': 0, 'today_registers': 0,
        'system_resources': {'cpu_percent': 0.0, 'memory_percent': 0.0,
                              'disk_percent': 0.0, 'network_percent': 0.0},
        'system_status': '系统正常', 'version': 'v2.6.0',
        'role_distribution': [], 'recent_users': [], 'recent_logs': [],
    }
    db_path = _dashboard_db_path()
    if not os.path.exists(db_path):
        return data
    try:
        conn = sqlite3.connect('file:' + db_path + '?mode=ro', uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 用户统计 (users 表: enabled 字段表示激活)
        try:
            cur.execute('SELECT COUNT(*) FROM users')
            data['user_count'] = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE enabled=1 OR enabled='1' OR enabled IS NULL")
            data['active_users'] = cur.fetchone()[0] or 0
        except Exception:
            pass

        # 今日注册 (created_at LIKE today%)
        try:
            today_prefix = datetime.now().strftime('%Y-%m-%d')
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at LIKE ?", (today_prefix + '%',))
            data['today_registers'] = cur.fetchone()[0] or 0
        except Exception:
            pass

        # 题库题目 (多表累加)
        for t in ('question_bank_items', 'ai_question_bank', 'professional_exam_questions'):
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                r = cur.fetchone()
                if r and r[0]:
                    data['questions_count'] += r[0]
            except Exception:
                pass

        # 考试/测试 + 已完成考试
        for t in ('teacher_exams', 'exam_sessions'):
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                r = cur.fetchone()
                if r and r[0]:
                    data['exams_count'] += r[0]
            except Exception:
                pass
        for t in ('exam_results', 'exam_attempts'):
            try:
                cur.execute(f"SELECT COUNT(*) FROM \"{t}\" WHERE submitted_at IS NOT NULL OR LOWER(status)='completed'")
                r = cur.fetchone()
                if r and r[0]:
                    data['completed_exams'] += r[0]
            except Exception:
                pass

        # 学习记录
        try:
            cur.execute('SELECT COUNT(*) FROM user_learning_data')
            data['learning_records'] = cur.fetchone()[0] or 0
        except Exception:
            pass

        # 今日登录 (login_logs 不存在则 0)
        try:
            today_prefix = datetime.now().strftime('%Y-%m-%d')
            cur.execute("SELECT COUNT(*) FROM login_logs WHERE login_time LIKE ? OR created_at LIKE ?",
                        (today_prefix + '%', today_prefix + '%'))
            data['today_logins'] = cur.fetchone()[0] or 0
        except Exception:
            pass

        # 角色分布 (GROUP BY role)
        try:
            cur.execute("SELECT role, COUNT(*) AS c FROM users GROUP BY role ORDER BY c DESC")
            data['role_distribution'] = [{'role': r['role'] or 'unknown', 'count': r['c']}
                                          for r in cur.fetchall()]
        except Exception:
            pass

        # 近期用户 (按 created_at 倒序)
        try:
            cur.execute("SELECT username, role, created_at FROM users ORDER BY created_at DESC LIMIT 8")
            data['recent_users'] = [{'username': r['username'], 'role': r['role'] or 'user',
                                     'created_at': str(r['created_at'] or '')} for r in cur.fetchall()]
        except Exception:
            pass

        # 近期登录日志 (login_logs 不存在则空)
        try:
            cur.execute("SELECT username, login_time, ip_address FROM login_logs ORDER BY login_time DESC LIMIT 8")
            data['recent_logs'] = [{'username': r['username'], 'time': str(r['login_time'] or ''),
                                    'ip': str(r['ip_address'] or '')} for r in cur.fetchall()]
        except Exception:
            pass

        conn.close()
    except Exception:
        pass

    # 系统资源 (psutil 可选, 不可用则 0.0)
    try:
        import psutil
        data['system_resources'] = {
            'cpu_percent': round(float(psutil.cpu_percent(interval=None) or 0), 1),
            'memory_percent': round(float(psutil.virtual_memory().percent or 0), 1),
            'disk_percent': round(float(psutil.disk_usage('/').percent or 0), 1),
            'network_percent': 0.0,
        }
    except Exception:
        pass

    return data


@admin_bp.route('/api/admin/dashboard_stats', methods=['GET'])
def api_admin_dashboard_stats():
    """仪表盘统计 API — admin_dashboard.html JS fetch 数据源 (真实聚合, 禁止假数据).

    响应格式: {code:0, msg:'ok', data:{user_count, exams_count, questions_count, ...}}
    """
    if not session.get('logged_in'):
        return jsonify({'code': 401, 'msg': '未登录', 'data': {}}), 401
    data = _get_dashboard_data()
    return jsonify({'code': 0, 'msg': 'ok', 'data': data})


bp = Blueprint('admin_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'admin','routes_implemented':1}})

