"""
admin_subpage_routes — admin_app 子页面路由 (v22.35.0 Phase 3 拆分)
================================================================
从 server_real_db.py 迁移 4 组 admin 域页面路由：

  /admin_app/ + /admin_app/<name> → admin_app_pages() catch-all (~82 unified_pages)
  /process_monitor + /admin_app/process_monitor → process_monitor_page() (委托 admin_app_pages)
  /admin_app/inspection_report[/] → admin_inspection_report_page()
  /admin_app/inspection_settings[/] → admin_inspection_settings_page()

不动：
  /admin_app/login (auth 域)
  /api/admin_app/* (API 域)

延迟绑定: handler 内 _mt_sdb() 获取 server_real_db 引用，访问其内部函数：
  _current_user, _MT_ADMIN_ROLES, _vikey_check_bound_present,
  _agg_realtime_stats, _safe_user_ctx, get_version_info, _build_role_sidebar,
  _maintenance_status, APP_DB, _get_conn

注册顺序 (关键): 具体路由先, catch-all 后。否则 Flask 匹配 catch-all 优先。
"""
import os as _os
import datetime as _dt

from flask import (
    Blueprint, redirect, render_template, request, session,
    jsonify as _jsonify,
)
from app.middlewares.system_container import system_container


# ═══════════════════════════════════════════════════════════════════════
# 蓝图定义 + 懒加载 server_real_db 引用
# ═══════════════════════════════════════════════════════════════════════
_bp = Blueprint('admin_app_children_bp', __name__)
admin_subpage_bp = _bp  # register_all_blueprints 通过 getattr 查找

_sdb = None


def _mt_sdb():
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


# ═══════════════════════════════════════════════════════════════════════
# admin_app_pages — 核心 catch-all handler (从 server_real_db.py L16327 原样迁移)
# ═══════════════════════════════════════════════════════════════════════

def _admin_app_pages_impl(name='dashboard'):
    """admin_app/<name> 统一页面路由实现（延迟绑定依赖）"""
    sdb = _mt_sdb()
    if not name:
        name = 'dashboard'
    name = name.strip().rstrip('/')
    u = sdb._current_user()
    is_admin = bool(u and (str(u.get('username') or '').lower() == 'wuchenghao15' or u.get('role') in sdb._MT_ADMIN_ROLES))
    if not is_admin and name not in ('login',):
        return redirect('/admin_app/login')

    # VIKEY 强制校验
    if is_admin and str(u.get('username') or '').lower() == 'wuchenghao15' and name not in ('login',):
        v_ok, v_reason, v_dev = sdb._vikey_check_bound_present(username=u.get('username') if u else None)
        if not v_ok:
            reason_map = {
                'no_bound_vikey_present': '请插入已注册绑定的 VIKEY 加密狗后再访问',
                'vikey_not_for_this_user': '当前 VIKEY 未绑定到此账户，请使用对应加密狗',
            }
            msg = reason_map.get(v_reason, f'VIKEY 校验失败：{v_reason}')
            session['_vikey_error_msg'] = msg
            session.pop('user_id', None)
            session.pop('username', None)
            return redirect('/admin_app/login')
    # Arduino 铁律
    if isinstance(name, str) and name.startswith('arduino'):
        if not (u and str(u.get('username') or '').lower() == 'wuchenghao15'):
            return render_template('403.html', message='Arduino 管理功能仅超级管理员 wuchenghao15 可访问（权限合规 § 用户权限.md）'), 403
    # 允许 .html 后缀
    if name.endswith('.html'):
        name = name[:-5]

    # unified_pages 统一整合到 dashboard.html
    unified_pages = [
        'dashboard', 'dashboard_unified', 'users', 'exams', 'questions', 'courses',
        'ai_employee_dashboard', 'ai_employee_health', 'ai_employees',
        'settings', 'system', 'status', 'backup', 'permissions',
        'permission_management', 'roles', 'vikey', 'vikey_manager', 'upgrade',
        'logs', 'monitor', 'security', 'security_dashboard',
        'ai_adaptive_learning', 'ai_auto_learning', 'ai_cognitive_reasoning',
        'ai_emotion', 'ai_evaluation', 'ai_exam_composer',
        'ai_intelligent_center', 'ai_intelligent_qna',
        'ai_knowledge_graph', 'ai_learning_dashboard',
        'ai_learning_planner', 'ai_memory',
        'ai_question_generation', 'ai_question_generator',
        'ai_scheduler_dashboard', 'ai_study_path',
        'ai_tutor', 'ai_tutor_assistant', 'ai_warning_intervention',
        'assignments', 'communication_center', 'data_analysis',
        'education_management', 'enhanced_settings',
        'exam_analysis', 'form_manager', 'health_details',
        'health_monitor', 'learning_paths', 'notifications',
        'personalization', 'resource_manager',
        'student_analytics', 'user_auth',
        'wrong_book', 'sslvpn_management', 'intelligent_question_bank', 'process_monitor',
        'qbank_inspection', 'courseware_manager', 'teaching_aid_alignment',
        'subject_adaptation', 'course_completion', 'teacher_enrichment',
        'qbank_outdated', 'adult_course_dev',
    ]

    def _get_role_name(role):
        role_map = {
            'super_admin': '超级管理员', 'sadmin': '超级管理员',
            'admin': '管理员', 'teacher': '教师',
            'student': '学生', 'designer': '设计师',
            'user': '普通用户', 'parent': '家长',
        }
        return role_map.get((role or '').lower(), role or '未知')

    if name in unified_pages:
        stats = sdb._agg_realtime_stats()
        current_user = sdb._safe_user_ctx(sdb._current_user())

        users = stats.get('users_all', [])
        total = len(users)
        active = sum(1 for x in users if x.get('is_active') or x.get('enabled'))
        inactive = total - active
        admins = sum(1 for x in users if (x.get('role') or '').lower() in ('super_admin', 'admin', 'sadmin'))

        ctx = dict(
            total_users=stats['total_users'], active_users=stats['active_users'],
            total_ai=stats['total_ai'], total_clusters=stats['total_clusters'],
            pending_tasks=stats['pending_tasks'],
            total_questions=stats['total_questions'], total_exams=stats['total_exams'],
            total_courses=stats['total_courses'], total_rules=stats['total_rules'],
            total_brain_entries=stats['total_brain_entries'],
            activities=stats['activities'], alerts=stats['alerts'],
            resolved_count=stats['resolved_count'],
            users=users,
            user_stats={'total_users': total, 'active_users': active,
                        'inactive_users': inactive, 'admin_users': admins},
            user=current_user, page_name='dashboard', current_page=name,
            get_role_name=_get_role_name,
            version=sdb.get_version_info()[0], version_info=sdb.get_version_info()[1],
        )
        # OneDrive FOD 兼容：dashboard.html 可读检测
        tmpl_dash = _os.path.join(sdb.app.template_folder or '', 'admin_app/dashboard.html')
        dash_ok = False
        try:
            with open(tmpl_dash, 'rb') as _tf:
                _s = _tf.read(512)
                if len(_s) >= 20 and (b'{%' in _s or b'<!DOCTYPE' in _s or b'<!doctype' in _s or b'<html' in _s):
                    dash_ok = True
        except (OSError, IOError, TimeoutError):
            dash_ok = False
        if not dash_ok:
            return redirect('/smart_dashboard?fallback=admin_app%2F' + name)
        return render_template('admin_app/dashboard.html', **ctx)

    # 非 unified_pages：渲染独立模板
    tmpl_path = f'admin_app/{name}.html'
    stats = sdb._agg_realtime_stats()
    current_user = sdb._safe_user_ctx(sdb._current_user())
    sidebar_menus = sdb._build_role_sidebar(current_user.get('role'))

    ctx = dict(
        total_users=stats['total_users'], active_users=stats['active_users'],
        total_ai=stats['total_ai'], total_clusters=stats['total_clusters'],
        pending_tasks=stats['pending_tasks'],
        total_questions=stats['total_questions'], total_exams=stats['total_exams'],
        total_courses=stats['total_courses'], total_rules=stats['total_rules'],
        total_brain_entries=stats['total_brain_entries'],
        recent_login=stats['recent_login'], recent_ops=stats['recent_ops'],
        activities=stats['activities'], alerts=stats['alerts'],
        resolved_count=stats['resolved_count'], users_all=stats['users_all'],
        user=current_user, page_name=name, current_page=name,
        sidebar_menus=sidebar_menus,
        get_role_name=_get_role_name,
        version=sdb.get_version_info()[0], version_info=sdb.get_version_info()[1],
    )
    # OneDrive FOD 兼容：独立模板可读检测
    tmpl_full = _os.path.join(sdb.app.template_folder or '', tmpl_path)
    tmpl_readable = False
    try:
        with open(tmpl_full, 'rb') as _tf:
            _sample = _tf.read(512)
            if len(_sample) >= 20 and (b'{%' in _sample or b'<!DOCTYPE' in _sample or b'<!doctype' in _sample or b'<html' in _sample or (_sample and len(_sample) >= 50)):
                tmpl_readable = True
    except (OSError, IOError, TimeoutError):
        tmpl_readable = False

    if not _os.path.exists(tmpl_full) or not tmpl_readable:
        try:
            return redirect('/smart_dashboard?fallback=admin_app%2F' + name)
        except Exception:
            _msg = f'管理页面模板不可用（OneDrive同步中）：admin_app/{name}'
            _h = (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
                  f'<title>404 - MTSCOS AI</title>'
                  f'<style>body{{font-family:sans-serif;background:#f5f5f5;min-height:100vh;'
                  f'display:flex;align-items:center;justify-content:center;margin:0}}'
                  f'.box{{background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.1);'
                  f'text-align:center;max-width:500px}}.code{{font-size:72px;font-weight:800;color:#e74c3c}}'
                  f'.msg{{color:#666;margin:12px 0}}.btn{{display:inline-block;margin-top:16px;'
                  f'padding:8px 24px;background:#3498db;color:#fff;text-decoration:none;border-radius:6px}}'
                  f'</style></head><body><div class="box"><div class="code">404</div>'
                  f'<div class="msg">{_msg}</div>'
                  f'<a href="/" class="btn">返回首页</a></div></body></html>')
            return _h, 404, {'Content-Type': 'text/html; charset=utf-8'}

    if name == 'ai_employee_dashboard':
        running_tasks = 24
        ctx['ai_stats'] = {
            'total_employees': 12, 'active_employees': 8,
            'running_tasks': running_tasks, 'pending_tasks': 8,
            'ai_employees': 12, 'workload': min(100, running_tasks * 10),
        }

    if name == 'users':
        users = stats.get('users_all', [])
        total = len(users)
        active = sum(1 for x in users if x.get('is_active') or x.get('enabled'))
        inactive = total - active
        admins = sum(1 for x in users if (x.get('role') or '').lower() in ('super_admin', 'admin', 'sadmin'))
        ctx['users'] = users
        ctx['user_stats'] = {'total_users': total, 'active_users': active,
                             'inactive_users': inactive, 'admin_users': admins}

    return render_template(tmpl_path, **ctx)


# ═══════════════════════════════════════════════════════════════════════
# 路由注册 (顺序关键: 具体路由先, catch-all 后)
# ═══════════════════════════════════════════════════════════════════════

# --- 3 个具体路由 (必须在 catch-all 前) ---

@_bp.route('/admin_app/inspection_report', methods=['GET'], endpoint='admin_inspection_report_page')
@system_container(require_auth='login')
@_bp.route('/admin_app/inspection_report/', methods=['GET'], endpoint='admin_inspection_report_page_slash')
@system_container(require_auth='admin', allowed_roles=['super_admin', 'sadmin', 'admin'])
def admin_inspection_report_page():
    """巡检设计报告 - 管理员可见"""
    try:
        from core.services.ai_inspection_loop import get_inspection_engine
        engine = get_inspection_engine()
        engine_status = engine.get_status()
    except Exception:
        engine_status = {'total_runs': 0, 'total_errors_found': 0,
                         'total_errors_fixed': 0, 'total_knowledge_gained': 0,
                         'last_run_at': None, 'current_status': 'unavailable'}

    sdb = _mt_sdb()
    stats = {
        'engine_status': engine_status,
        'maintenance': {
            'running': sdb._maintenance_status.get('ai_inspection', {}).get('running', False),
            'last_run': sdb._maintenance_status.get('ai_inspection', {}).get('last_run', 0),
            'last_result': sdb._maintenance_status.get('ai_inspection', {}).get('last_result'),
        },
    }
    inspection_modules = [
        {'key': 'structure', 'name': '文件结构巡检', 'icon': 'folder-tree',
         'desc': '扫描项目目录，检测文件缺失/冗余、命名规范、目录结构异常'},
        {'key': 'syntax',    'name': '语法错误巡检', 'icon': 'code',
         'desc': '检测 Python/JS/HTML/CSS/JSON 等各类语法与静态编码错误'},
        {'key': 'console',   'name': '控制台错误巡检', 'icon': 'terminal',
         'desc': '聚合前端 window.onerror / unhandledrejection / fetch 错误'},
        {'key': 'autofix',   'name': '自动修复引擎', 'icon': 'wrench',
         'desc': '基于知识库匹配错误模式，自动修复常见问题并写回文件'},
        {'key': 'db_report', 'name': '数据库上报', 'icon': 'database',
         'desc': '巡检/修复结果写入 ai_inspection_runs/issues/knowledge 三表'},
        {'key': 'logging',   'name': '审计日志记录', 'icon': 'list-ul',
         'desc': '结构化日志输出到 logs/ai_inspection_loop.log 便于回溯排查'},
        {'key': 'learning',  'name': 'AI 自学习升级', 'icon': 'brain',
         'desc': '从成功/失败修复案例中学习，提升下次修复成功率'},
    ]
    return render_template(
        'admin_app/inspection_report.html',
        engine_status=engine_status, stats=stats,
        inspection_modules=inspection_modules,
        generated_at=_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )


@_bp.route('/admin_app/inspection_settings', methods=['GET'], endpoint='admin_inspection_settings_page')
@system_container(require_auth='login')
@_bp.route('/admin_app/inspection_settings/', methods=['GET'], endpoint='admin_inspection_settings_page_slash')
@system_container(require_auth='admin', allowed_roles=['super_admin', 'sadmin', 'admin'])
def admin_inspection_settings_page():
    """巡检设置与操作（admin 及以上可访问）"""
    try:
        from core.services.ai_inspection_loop import get_inspection_engine
        engine = get_inspection_engine()
        engine_status = engine.get_status()
    except Exception:
        engine_status = {'total_runs': 0, 'total_errors_found': 0,
                         'total_errors_fixed': 0, 'total_knowledge_gained': 0,
                         'last_run_at': None, 'current_status': 'unavailable'}

    sdb = _mt_sdb()
    default_config = {
        'interval_seconds': 300,
        'auto_fix_enabled': True,
        'console_error_report_enabled': True,
        'max_issues_per_run': 200,
        'notification_enabled': False,
        'backup_before_fix': True,
    }
    try:
        with sdb._get_conn(sdb.APP_DB) as c:
            for key in list(default_config.keys()):
                rule_key = f'AI_INSPECTION_{key.upper()}'
                try:
                    r = c.execute(
                        "SELECT rule_value FROM system_rules WHERE rule_key = ? LIMIT 1",
                        (rule_key,)).fetchone()
                    if r and r[0] not in (None, ''):
                        v = r[0]
                        if v in ('1', '0'):
                            default_config[key] = (v == '1')
                        else:
                            try:
                                default_config[key] = int(v)
                            except (ValueError, TypeError):
                                default_config[key] = v
                except Exception:
                    pass
    except Exception:
        pass

    stats = {
        'engine_status': engine_status,
        'maintenance': {
            'running': sdb._maintenance_status.get('ai_inspection', {}).get('running', False),
            'last_run': sdb._maintenance_status.get('ai_inspection', {}).get('last_run', 0),
            'last_result': sdb._maintenance_status.get('ai_inspection', {}).get('last_result'),
        },
        'config': default_config,
    }
    return render_template(
        'admin_app/inspection_settings.html',
        stats=stats,
        generated_at=_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )


@_bp.route('/process_monitor', methods=['GET'], endpoint='process_monitor_page_alias')
@system_container(require_auth='login')
@_bp.route('/admin_app/process_monitor', methods=['GET'], endpoint='process_monitor_page')
@system_container(require_auth='admin', allowed_roles=['super_admin', 'sadmin', 'admin'])
def process_monitor_page():
    """进程监控控制台页面 — 委托 admin_app_pages (process_monitor 在 unified_pages 中)"""
    return _admin_app_pages_impl('process_monitor')


# --- catch-all: 必须最后！否则 Flask 会先匹配 /admin_app/<name> 吞掉 inspection_report/settings ---

@_bp.route('/admin_app/', methods=['GET'], endpoint='admin_app_root_fix')
@system_container(require_auth='login')
@_bp.route('/admin_app/<name>', methods=['GET'], endpoint='admin_app_catchall_fix')
@system_container(require_auth='admin')
def admin_app_pages(name='dashboard'):
    """admin_app 统一 catch-all: 82 个 unified_pages → dashboard.html, 其他 → admin_app/{name}.html"""
    return _admin_app_pages_impl(name)
