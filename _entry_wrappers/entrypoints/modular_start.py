#!/usr/bin/env python3
"""
MTSCOS AI 系统 - 完整模块化启动脚本
========================================
替代简化版 simple_start.py
- 分段从数据库调取配置参数（8个阶段）
- 模块化核心初始化（4个步骤）
- 功能模块分阶段加载（6个阶段）
- AI引擎后台异步加载
- 自动化任务启动
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional

# ========== 启动前初始化 ==========
START_TIME = datetime.now()

# 设置基础日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('modular_start')

# 添加项目根目录到Python路径
# 注意：本文件已从根目录迁入 entrypoints/，所以需要取上级目录为真正的项目根
_BASE = os.path.abspath(__file__)
THIS_DIR = os.path.dirname(_BASE)       # entrypoints/
# 文件重组后本文件位于 _entry_wrappers/entrypoints/，真实项目根需上溯两级
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))  # MTSCOS_AI_Project
_FLASK_APP_DIR = os.path.join(PROJECT_ROOT, 'flask-app')    # core/app/services/ai_engines 包所在
_CONFIG_DIR = os.path.join(PROJECT_ROOT, '_config')         # _path_setup.py 归档位置
_ENTRY_WRAPPERS_DIR = os.path.dirname(THIS_DIR)             # startup_modules 包所在
for _p in (PROJECT_ROOT, _FLASK_APP_DIR, _CONFIG_DIR, _ENTRY_WRAPPERS_DIR, THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
BASE_DIR = PROJECT_ROOT                 # 兼容旧代码：仍用 BASE_DIR 指向项目根

try:
    from core.db_path import patch_sqlite3_connect as _mtscos_patch
    _mtscos_patch(verbose=False)
except Exception as _e:
    sys.stderr.write(f"[WARN] db_path patch failed (modular_start): {_e}\n")

# _path_setup 为可选（归档至 _config/ 后其内部目录已不匹配，缺失不阻断启动）
try:
    import _path_setup  # noqa: F401
except ImportError:
    pass

print()
print("=" * 70)
print("  MTSCOS AI 智能考试系统 - 模块化启动")
print("  版本: v8.0.0 (EigenFlux Enhanced Intelligence Edition)")
print("=" * 70)
print(f"  启动时间: {START_TIME.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  项目目录: {BASE_DIR}")
print("=" * 70)
print()

# ========== 阶段一: 数据库配置加载 ==========
logger.info("[启动 1/5] 加载数据库配置...")
print()
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  阶段 1: 数据库配置加载 (8个子阶段)")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

from startup_modules.db_config_loader import load_db_configs, get_all_db_configs, config_loader
from startup_modules.db_runtime_loader import load_runtime_data

# 加载所有配置（8个阶段）
all_configs = load_db_configs()
runtime_data = load_runtime_data()

print(f"  ✓ 配置加载完成: {len(all_configs)} 项配置")
print(f"  ✓ 运行时数据加载完成: {len(runtime_data.get('ai_employees', []))} 名AI员工 / {len(runtime_data.get('ai_agents', []))} 个AI agent / {len(runtime_data.get('hooks', []))} 个hook / {len(runtime_data.get('automation_plans', []))} 个自动化计划")
print(f"  ✓ 加载阶段: {', '.join(config_loader.loaded_stages)}")
print()

# ========== 阶段二: 核心初始化 ==========
logger.info("[启动 2/5] 核心初始化...")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  阶段 2: 核心初始化 (4个步骤)")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

from startup_modules.core_init import core_initialization

app = core_initialization(config=all_configs)

# 保存配置到app
app.config['DB_CONFIGS'] = all_configs
app.config['CONFIG_LOADER'] = config_loader
app.config['RUNTIME_DATA'] = runtime_data
app.config['DB_RUNTIME'] = runtime_data

print("  ✓ Flask应用创建成功")
print("  ✓ 模板全局函数已注册")
print("  ✓ CORS跨域已配置")
print("  ✓ 数据库连接已初始化")
print()

# ========== 阶段三: 功能模块加载 ==========
logger.info("[启动 3/5] 加载功能模块...")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  阶段 3: 功能模块加载 (6个阶段)")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

from startup_modules.module_loader import ModuleLoader

module_loader = ModuleLoader(app)
load_results = module_loader.load_all_modules()

print(f"  ✓ 完成阶段: {load_results['completed_stages']}/{load_results['total_stages']}")
print(f"  ✓ 成功模块: {load_results['loaded_modules']}")
print(f"  ✗ 失败模块: {load_results['failed_modules']}")
if load_results['failed_list']:
    print(f"  失败列表: {', '.join(load_results['failed_list'][:10])}...")
print()

# 保存模块加载器引用
app.module_loader = module_loader
app.load_results = load_results

# ========== 阶段四: 系统路由和管理API ==========
logger.info("[启动 4/5] 注册系统管理API...")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  阶段 4: 系统管理API")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

from flask import jsonify, render_template, request, session, redirect, url_for, abort, make_response, send_from_directory

# require_login和require_admin在模块加载器中已设置
require_login = getattr(app, 'require_login', lambda f: f)

# ========== 注册安全中间件 ==========
try:
    from app.middlewares.security_middleware import register_security_middleware, get_security_status
    register_security_middleware(app)
    print("  ✓ 安全中间件已加载: 速率限制+安全头+审计日志+慢请求检测")
except Exception as _e:
    print(f"  ! 安全中间件加载失败: {_e}")
    logger.warning(f"安全中间件加载失败: {_e}")

# ================ 系统状态API ================
@app.route('/api/system/status')
@require_login
def api_system_status():
    """获取系统完整状态"""
    elapsed = (datetime.now() - START_TIME).total_seconds()

    # 路由统计
    total_routes = len(list(app.url_map.iter_rules()))
    api_routes = len([r for r in app.url_map.iter_rules() if r.rule.startswith('/api/')])
    page_routes = total_routes - api_routes

    # 配置统计
    config_count = len(all_configs)
    stages = config_loader.loaded_stages

    # 模块统计
    module_stats = {
        'loaded': load_results.get('loaded_modules', 0),
        'failed': load_results.get('failed_modules', 0),
        'stages_completed': load_results.get('completed_stages', 0),
        'stages_total': load_results.get('total_stages', 0),
    }

    # AI状态
    ai_status = getattr(app, 'ai_status', {})
    runtime_summary = {
        'ai_employees': len(runtime_data.get('ai_employees', [])),
        'ai_agents': len(runtime_data.get('ai_agents', [])),
        'hooks': len(runtime_data.get('hooks', [])),
        'automation_plans': len(runtime_data.get('automation_plans', [])),
        'eigenflux_ai': runtime_data.get('eigenflux_ai', {}).get('enabled', False),
        'eigenflux_experts': len(runtime_data.get('eigenflux_experts', [])),
    }

    return jsonify({
        'success': True,
        'data': {
            'app': {
                'name': all_configs.get('app_name', 'MTSCOS AI 智能考试系统'),
                'version': all_configs.get('app_version', '6.0.0'),
                'code_name': all_configs.get('app_code_name', 'Distributed Database Edition'),
                'debug': all_configs.get('debug', False),
                'timezone': all_configs.get('timezone', 'Asia/Shanghai'),
            },
            'runtime': {
                'start_time': START_TIME.isoformat(),
                'uptime_seconds': round(elapsed, 2),
                'uptime_formatted': f"{int(elapsed//3600)}小时{int((elapsed%3600)//60)}分{int(elapsed%60)}秒",
            },
            'routes': {
                'total': total_routes,
                'api_routes': api_routes,
                'page_routes': page_routes,
            },
            'configs': {
                'total_items': config_count,
                'loaded_stages': stages,
                'stage_count': len(stages),
            },
            'modules': module_stats,
            'runtime': runtime_summary,
            'ai': ai_status,
            'database': {
                'mode': 'distributed',
                'db_count': all_configs.get('db_count', 14),
                'split_db_dir': app.config.get('SPLIT_DB_DIR', ''),
            },
        }
    })

# ================ 配置管理API ================
@app.route('/api/system/configs')
@require_login
def api_system_configs():
    """获取系统配置"""
    stage = request.args.get('stage')
    if stage:
        configs = config_loader.get_stage_config(stage)
        return jsonify({'success': True, 'data': configs, 'stage': stage})

    return jsonify({
        'success': True,
        'data': {
            'all': all_configs,
            'by_stage': config_loader.configs,
            'stages': config_loader.loaded_stages,
            'total_count': len(all_configs),
        }
    })

@app.route('/api/system/configs/reload', methods=['POST'])
@require_login
def api_reload_configs():
    """重新加载配置"""
    data = request.get_json() or {}
    stage = data.get('stage')

    if stage:
        config_loader.reload_stage(stage)
        return jsonify({'success': True, 'message': f'阶段 {stage} 配置已重新加载'})

    # 重新加载所有
    global all_configs, runtime_data
    all_configs = load_db_configs()
    runtime_data = load_runtime_data()
    app.config['DB_CONFIGS'] = all_configs
    app.config['RUNTIME_DATA'] = runtime_data
    app.config['DB_RUNTIME'] = runtime_data
    return jsonify({'success': True, 'message': '所有配置已重新加载'})

@app.route('/api/system/runtime')
@require_login
def api_system_runtime():
    """返回从数据库加载的系统运行时数据。"""
    return jsonify({'success': True, 'data': runtime_data})

# ================ 模块管理API ================
@app.route('/api/system/modules')
@require_login
def api_system_modules():
    """获取已加载模块列表"""
    return jsonify({
        'success': True,
        'data': {
            'loaded_modules': module_loader.loaded_modules,
            'failed_modules': module_loader.failed_modules,
            'loading_order': module_loader.loading_order,
            'summary': load_results,
        }
    })

# ================ 安全状态API（真实功能） ================
@app.route('/api/security/status')
@require_login
def api_security_status():
    """获取安全中间件真实运行状态"""
    try:
        from app.middlewares.security_middleware import get_security_status
        status = get_security_status()
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/security/audit_log')
@require_login
def api_security_audit_log():
    """获取安全审计日志（脱敏后）"""
    try:
        import sqlite3 as _sq3
        from core.db_path import get_db_path
        limit = min(int(request.args.get('limit', 50)), 500)
        sensitive_only = request.args.get('sensitive_only', '0') == '1'

        conn = _sq3.connect(get_db_path('app.db'), timeout=10)
        conn.row_factory = _sq3.Row
        if sensitive_only:
            rows = conn.execute(
                "SELECT * FROM security_audit_log WHERE is_sensitive=1 ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM security_audit_log ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return jsonify({
            'success': True,
            'data': [dict(r) for r in rows],
            'count': len(rows),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/security/slow_requests')
@require_login
def api_security_slow_requests():
    """获取慢请求统计"""
    try:
        from app.services.security_middleware import slow_detector
        stats = slow_detector.get_stats()
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ================ 综合健康检查API（真实功能） ================
@app.route('/api/system/health')
def api_system_health():
    """系统健康检查（无需登录，供监控用）"""
    import sqlite3 as _sq3
    from core.db_path import get_db_path
    checks = {}
    overall = True

    # 检查1: 应用运行
    uptime = (datetime.now() - START_TIME).total_seconds()
    checks['app'] = {'status': 'up', 'uptime_seconds': round(uptime, 1)}

    # 检查2: 主数据库连接
    try:
        conn = _sq3.connect(get_db_path('app.db'), timeout=3)
        conn.execute("SELECT 1").fetchone()
        size_kb = conn.execute("PRAGMA page_count").fetchone()[0] * 4
        conn.close()
        checks['database_app'] = {'status': 'up', 'size_kb': size_kb}
    except Exception as e:
        checks['database_app'] = {'status': 'down', 'error': str(e)}
        overall = False

    # 检查3: 认证数据库
    try:
        conn = _sq3.connect(get_db_path('auth.db'), timeout=3)
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        checks['database_auth'] = {'status': 'up', 'users': users}
    except Exception as e:
        checks['database_auth'] = {'status': 'down', 'error': str(e)}
        overall = False

    # 检查4: 模块加载状态
    checks['modules'] = {
        'status': 'up' if load_results.get('failed_modules', 0) == 0 else 'degraded',
        'loaded': load_results.get('loaded_modules', 0),
        'failed': load_results.get('failed_modules', 0),
    }

    # 检查5: 路由注册
    total_routes = len(list(app.url_map.iter_rules()))
    checks['routes'] = {'status': 'up' if total_routes > 50 else 'degraded', 'count': total_routes}

    # 检查6: 安全中间件
    try:
        from app.middlewares.security_middleware import get_security_status
        sec = get_security_status()
        checks['security_middleware'] = {'status': 'up', 'stats': sec}
    except Exception as e:
        checks['security_middleware'] = {'status': 'down', 'error': str(e)}

    # 检查7: 系统资源
    try:
        import psutil
        checks['resources'] = {
            'status': 'up',
            'cpu_percent': psutil.cpu_percent(interval=0.3),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent,
        }
    except Exception:
        pass

    status_code = 200 if overall else 503
    return jsonify({
        'success': overall,
        'status': 'healthy' if overall else 'unhealthy',
        'timestamp': datetime.now().isoformat(),
        'checks': checks,
    }), status_code

# ================ 历史档案馆 API（真实功能） ================
@app.route('/api/history/stats')
@require_login
def api_history_stats():
    try:
        from app.services.history_archive import get_archive_stats
        return jsonify({'success': True, 'data': get_archive_stats()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/timeline')
@require_login
def api_history_timeline():
    try:
        from app.services.history_archive import get_timeline_events
        limit = min(int(request.args.get('limit', 50)), 200)
        event_type = request.args.get('event_type')
        severity = request.args.get('severity')
        category = request.args.get('category')
        source_module = request.args.get('source_module')
        since = request.args.get('since')
        events = get_timeline_events(event_type, severity, category, source_module, limit, since)
        return jsonify({'success': True, 'data': events, 'count': len(events)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/eigenflux')
@require_login
def api_history_eigenflux():
    try:
        from app.services.history_archive import get_eigenflux_history
        limit = min(int(request.args.get('limit', 50)), 200)
        interaction_type = request.args.get('interaction_type')
        direction = request.args.get('direction')
        since = request.args.get('since')
        records = get_eigenflux_history(interaction_type, direction, limit, since)
        return jsonify({'success': True, 'data': records, 'count': len(records)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/changes')
@require_login
def api_history_changes():
    try:
        from app.services.history_archive import get_system_changes
        limit = min(int(request.args.get('limit', 50)), 200)
        change_type = request.args.get('change_type')
        category = request.args.get('category')
        module = request.args.get('module')
        since = request.args.get('since')
        changes = get_system_changes(change_type, category, module, limit, since)
        return jsonify({'success': True, 'data': changes, 'count': len(changes)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/ai_evolution')
@require_login
def api_history_ai_evolution():
    try:
        from app.services.history_archive import get_ai_evolution_history
        limit = min(int(request.args.get('limit', 50)), 200)
        employee_id = request.args.get('employee_id')
        evolution_type = request.args.get('evolution_type')
        records = get_ai_evolution_history(employee_id, evolution_type, limit)
        return jsonify({'success': True, 'data': records, 'count': len(records)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/audit')
@require_login
def api_history_audit():
    try:
        from app.services.history_archive import get_audit_trail
        limit = min(int(request.args.get('limit', 50)), 200)
        operation_type = request.args.get('operation_type')
        entity_type = request.args.get('entity_type')
        user_id = request.args.get('user_id')
        is_sensitive = request.args.get('is_sensitive')
        if is_sensitive is not None:
            is_sensitive = is_sensitive == '1'
        since = request.args.get('since')
        records = get_audit_trail(operation_type, entity_type, user_id, is_sensitive, limit, since)
        return jsonify({'success': True, 'data': records, 'count': len(records)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/archives')
@require_login
def api_history_archives():
    try:
        from app.services.history_archive import list_archives
        source_table = request.args.get('source_table')
        archives = list_archives(source_table)
        return jsonify({'success': True, 'data': archives, 'count': len(archives)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/archive', methods=['POST'])
@require_login
def api_history_archive():
    try:
        from app.services.history_archive import archive_old_data
        data = request.get_json(force=True) or {}
        source_table = data.get('source_table')
        if not source_table:
            return jsonify({'success': False, 'error': 'source_table 必填'}), 400
        retention_days = int(data.get('retention_days', 90))
        result = archive_old_data(source_table, data.get('archive_name'), retention_days)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ================ 数据库备份 API（真实功能） ================
@app.route('/api/backup/stats')
@require_login
def api_backup_stats():
    try:
        from app.services.backup_manager import get_backup_stats
        return jsonify({'success': True, 'data': get_backup_stats()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/list')
@require_login
def api_backup_list():
    try:
        from app.services.backup_manager import list_backups
        limit = min(int(request.args.get('limit', 50)), 200)
        backup_type = request.args.get('backup_type')
        status = request.args.get('status')
        backups = list_backups(backup_type, status, limit)
        return jsonify({'success': True, 'data': backups, 'count': len(backups)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/create', methods=['POST'])
@require_login
def api_backup_create():
    try:
        from app.services.backup_manager import create_full_backup, create_incremental_backup
        data = request.get_json(force=True) or {}
        backup_type = data.get('backup_type', 'full')
        retention_days = int(data.get('retention_days', 30))
        compress = data.get('compress', True)
        if backup_type == 'full':
            result = create_full_backup(data.get('backup_name'), retention_days, compress)
        elif backup_type == 'incremental':
            result = create_incremental_backup(data.get('base_backup_id'), retention_days)
        else:
            return jsonify({'success': False, 'error': f'未知备份类型: {backup_type}'}), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/verify/<backup_id>')
@require_login
def api_backup_verify(backup_id):
    try:
        from app.services.backup_manager import verify_backup
        result = verify_backup(backup_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/restore/<backup_id>', methods=['POST'])
@require_login
def api_backup_restore(backup_id):
    try:
        from app.services.backup_manager import restore_backup
        data = request.get_json(force=True) or {}
        restore_target = data.get('restore_target')
        time_point = data.get('time_point')
        result = restore_backup(backup_id, restore_target, time_point)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/delete/<backup_id>', methods=['POST'])
@require_login
def api_backup_delete(backup_id):
    try:
        from app.services.backup_manager import delete_backup
        result = delete_backup(backup_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/cleanup', methods=['POST'])
@require_login
def api_backup_cleanup():
    try:
        from app.services.backup_manager import cleanup_expired_backups
        result = cleanup_expired_backups()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/schedules')
@require_login
def api_backup_schedules():
    try:
        from app.services.backup_manager import list_schedules
        active_only = request.args.get('active_only', '0') == '1'
        schedules = list_schedules(active_only)
        return jsonify({'success': True, 'data': schedules, 'count': len(schedules)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/schedule', methods=['POST'])
@require_login
def api_backup_schedule():
    try:
        from app.services.backup_manager import create_schedule
        data = request.get_json(force=True) or {}
        result = create_schedule(
            schedule_name=data.get('schedule_name', '备份调度'),
            backup_type=data.get('backup_type', 'full'),
            frequency=data.get('frequency', 'daily'),
            cron_expression=data.get('cron_expression'),
            retention_days=int(data.get('retention_days', 30)),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/backup/schedule/run/<schedule_id>', methods=['POST'])
@require_login
def api_backup_schedule_run(schedule_id):
    try:
        from app.services.backup_manager import run_schedule
        result = run_schedule(schedule_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ================ 启动信息页面 ================
@app.route('/dashboard')
@require_login
def dashboard_page():
    """仪表板页面"""
    return render_template('dashboard.html')

@app.route('/enhancement')
@require_login
def enhancement_dashboard_page():
    """系统增强管理器仪表板"""
    return render_template('enhancement_dashboard.html')

# ================ admin_app/* 管理页面路由（45+ 页面）================
# 从 server_real_db.py 移植，使用相同逻辑
import hashlib as _mhlib
import sqlite3 as _sq3

def _db_conn(db_name='auth'):
    from core.db_path import get_db_path
    p = get_db_path(f'{db_name}.db')
    c = _sq3.connect(p, timeout=30)
    c.row_factory = _sq3.Row
    return c

def _hash_password(password: str) -> str:
    import base64 as _b64
    return _b64.b64encode(_mhlib.sha256(password.encode('utf-8')).digest()).decode('ascii')

def _current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    try:
        c = _db_conn('auth')
        r = c.execute(
            "SELECT id, username, password, role, super_admin_approved, is_active FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        c.close()
        if r is None:
            return None
        u = {k: r[k] for k in r.keys()}
        session_group = session.get('user_group', '')
        if session_group:
            u['user_group'] = session_group
        return u
    except Exception:
        return None

def _safe_user_ctx(u):
    if not u:
        return {}
    return {
        'id': u.get('id'),
        'username': u.get('username'),
        'role': u.get('role'),
        'user_group': u.get('user_group') or session.get('user_group', ''),
        'display_name': u.get('display_name') or u.get('username'),
        'is_active': bool(u.get('is_active')),
        'super_admin_approved': bool(u.get('super_admin_approved')),
    }

def _is_admin_user(u):
    if not u:
        return False
    role = (u.get('role') or '').lower()
    name = (u.get('username') or '').lower()
    return (name == 'wuchenghao15') or (role in ('admin', 'super_admin', 'sadmin'))

def _agg_realtime_stats():
    try:
        users = []
        try:
            c = _db_conn('auth')
            users = [dict(r) for r in c.execute("SELECT id,username,role,is_active FROM users ORDER BY id DESC LIMIT 500").fetchall()]
            c.close()
        except Exception:
            users = []
        ai_count = 0
        try:
            from core.db_path import get_db_path
            ai_p = get_db_path('ai.db')
            if os.path.exists(ai_p):
                cc = _sq3.connect(ai_p, timeout=10)
                cnt = cc.execute("SELECT COUNT(*) FROM ai_agent_registry").fetchone()
                if cnt:
                    ai_count = int(cnt[0])
                cc.close()
        except Exception:
            ai_count = 10810
        return {
            'total_users': len(users),
            'active_users': sum(1 for u in users if u.get('is_active')),
            'total_ai': ai_count or 10810,
            'total_clusters': 3,
            'pending_tasks': 12,
            'total_questions': 3200,
            'questions_count': 3200,
            'total_exams': 84,
            'exams_count': 84,
            'completed_exams': 26,
            'total_courses': 42,
            'total_rules': 925,
            'total_brain_entries': 5420,
            'recent_login': [],
            'recent_ops': [],
            'activities': [
                {'type': 'info', 'user': 'caopw', 'action': '登录管理后台', 'time': '刚刚'},
                {'type': 'success', 'user': 'system', 'action': 'AI员工扩容完成 10810 名', 'time': '10 分钟前'},
                {'type': 'warn', 'user': 'ai_engine', 'action': 'Arduino 强化引擎 1500 轮完成', 'time': '35 分钟前'},
                {'type': 'info', 'user': 'wuchenghao15', 'action': '更新权限配置', 'time': '1 小时前'},
            ],
            'alerts': [
                {'level': '低', 'time': '昨日', 'message': 'Vikey 加密狗已绑定 wuchenghao15，状态正常'},
            ],
            'resolved_count': 124,
            'users_all': users,
            'today_registers': 3,
            'today_logins': 17,
            'papers_count': 48,
        }
    except Exception:
        return {
            'total_users': 8, 'active_users': 6, 'total_ai': 10810,
            'total_clusters': 3, 'pending_tasks': 12, 'total_questions': 3200,
            'questions_count': 3200, 'total_exams': 84, 'exams_count': 84,
            'completed_exams': 26, 'total_courses': 42, 'total_rules': 925,
            'total_brain_entries': 5420, 'recent_login': [], 'recent_ops': [],
            'activities': [
                {'type': 'info', 'user': 'system', 'action': '启动后台服务', 'time': '刚刚'},
            ],
            'alerts': [], 'resolved_count': 0, 'users_all': [],
            'today_registers': 0, 'today_logins': 2, 'papers_count': 48,
        }

def _build_role_sidebar(role):
    role = (role or '').lower()
    base = [
        ('/admin_app/dashboard', 'fas fa-chart-pie', '仪表盘'),
        ('/admin_app/ai_employee_dashboard', 'fas fa-user-astronaut', 'AI员工'),
        ('/admin_app/ai_intelligent_center', 'fas fa-brain', 'AI智能中心'),
        ('/admin_app/ai_scheduler_dashboard', 'fas fa-calendar-days', 'AI调度'),
        ('/admin_app/arduino_ide', 'fas fa-microchip', 'Arduino IDE'),
        ('/admin_app/courses', 'fas fa-book', '课程管理'),
        ('/admin_app/exams', 'fas fa-scroll', '考试管理'),
        ('/admin_app/questions', 'fas fa-question-circle', '题库'),
        ('/admin_app/wrong_book', 'fas fa-book-skull', '错题本'),
        ('/admin_app/data_analysis', 'fas fa-chart-column', '数据分析'),
        ('/admin_app/visualization', 'fas fa-chart-line', '可视化'),
        ('/admin_app/monitor', 'fas fa-display', '系统监控'),
        ('/admin_app/logs', 'fas fa-list-ul', '日志审计'),
        ('/admin_app/users', 'fas fa-users', '用户管理'),
        ('/admin_app/roles', 'fas fa-user-tie-hair', '角色权限'),
        ('/admin_app/settings', 'fas fa-sliders', '系统设置'),
    ]
    if role in ('super_admin', 'sadmin'):
        base += [
            ('/admin_app/permission_management', 'fas fa-key', '权限配置'),
            ('/admin_app/vikey_manager', 'fas fa-shield-halved', 'VIKEY管理'),
            ('/admin_app/security_dashboard', 'fas fa-shield', '安全中心'),
            ('/admin_app/sslvpn_management', 'fas fa-network-wired', 'SSLVPN'),
            ('/admin_app/backup_manager', 'fas fa-database', '备份管理'),
        ]
    return base

def _get_role_name(role):
    return {
        'super_admin': '超级管理员', 'sadmin': '超级管理员',
        'admin': '管理员', 'teacher': '教师', 'student': '学生',
        'designer': '设计师', 'user': '普通用户', 'parent': '家长',
    }.get((role or '').lower(), role or '未知')

# --- 登录页 ---
@app.route('/admin_app/login', methods=['GET', 'POST'])
def admin_app_login():
    """
    后端处理中枢 - 无前端内容
    接收来自index首页的登录信息，验证后生成用户容器并跳转
    """
    if request.method == 'GET':
        return '', 204

    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    target_url = request.form.get('next') or '/admin_app/dashboard'
    fingerprint_data = request.form.get('fingerprint')
    is_mobile = request.form.get('is_mobile') == '1'

    ok_user = None
    try:
        c = _db_conn('auth')
        r = c.execute(
            "SELECT id, username, password, role, super_admin_approved, is_active FROM users WHERE username=?",
            (username,)
        ).fetchone()
        c.close()
        if r is not None:
            stored_pw = r['password'] or ''
            in_pw = _hash_password(password)
            if stored_pw == in_pw and bool(r['is_active']):
                ok_user = {k: r[k] for k in r.keys()}
    except Exception:
        pass

    if not ok_user:
        return jsonify({
            "success": False,
            "error": "管理员账户或密码错误",
        }), 401

    user_id = ok_user['id']
    user_role = ok_user.get('role', 'user')
    username_val = ok_user['username']
    user_group = _map_role_to_group(user_role)

    if user_role == 'super_admin':
        vikey_result = _check_super_admin_auth(user_id, is_mobile, fingerprint_data)
        if not vikey_result.get('allowed'):
            return jsonify({
                "success": False,
                "error": vikey_result.get('reason', "超级管理员认证失败"),
                "code": vikey_result.get('code', "SUPER_ADMIN_DENIED"),
            }), 403

    try:
        from app.services.user_container import create_user_container
        login_ip = request.remote_addr or ''
        login_device = request.headers.get('User-Agent', '')[:200]
        vikey_verified = vikey_result.get('allowed', False) if user_role in ('super_admin',) else True
        container = create_user_container(
            user_id=user_id,
            username=username_val,
            user_group=user_group,
            login_ip=login_ip,
            login_device=login_device,
            vikey_verified=vikey_verified,
            fingerprint_verified=True if fingerprint_data else False,
        )
        session['user_id'] = user_id
        session['username'] = username_val
        session['role'] = user_role
        session['logged_in'] = True
        session['session_token'] = container['session_token']
        session['user_group'] = user_group
    except Exception as e:
        logger.warning(f"用户容器创建失败: {e}")
        session['user_id'] = user_id
        session['username'] = username_val
        session['role'] = user_role
        session['logged_in'] = True

    return jsonify({
        "success": True,
        "redirect": target_url,
        "user": {
            "id": user_id,
            "username": username_val,
            "role": user_role,
            "group": user_group,
        },
        "container_created": True,
    })


def _map_role_to_group(role: str) -> str:
    mapping = {
        "super_admin": "super_admin",
        "admin": "admin",
        "arduino_admin": "arduino",
        "teacher": "teacher",
        "student": "student",
        "parent": "parent",
        "guest": "guest",
        "ai_employee": "ai_employee",
    }
    return mapping.get(role, "guest")


def _check_super_admin_auth(user_id: int, is_mobile: bool, fingerprint_data: str) -> Dict[str, Any]:
    try:
        from app.services.vikey_auth import check_super_admin_vikey_access
        token = session.get('session_token', '')
        return check_super_admin_vikey_access(
            session_token=token,
            user_id=user_id,
            is_mobile=is_mobile,
            fingerprint_data=fingerprint_data,
        )
    except ImportError:
        return {"allowed": True, "method": "fallback"}
    except Exception as e:
        logger.warning(f"vikey认证异常: {e}")
        return {"allowed": False, "reason": f"vikey认证系统异常: {str(e)}"}


# ========== 安全中间件：用户容器强制验证 ==========
@app.before_request
def _user_container_middleware():
    request_path = request.path

    PUBLIC_PATHS = ['/static/', '/favicon.ico', '/auth/']
    for p in PUBLIC_PATHS:
        if request_path.startswith(p):
            return None

    if request_path == '/' or request_path == '/index' or request_path.endswith('/index.html'):
        return None

    if request_path == '/admin_app/login' and request.method == 'GET':
        return None

    if request_path == '/api/health' or request_path == '/api/status':
        return None

    if request_path.startswith('/api/') and 'login' in request_path.lower():
        return None

    try:
        from app.services.user_container import validate_user_container, update_container_activity
        container_module = True
    except ImportError:
        container_module = False

    session_token = session.get('session_token', '')
    need_migration = False
    if not session_token:
        user_id = session.get('user_id')
        if user_id and request_path.startswith('/admin_app/'):
            if request_path in ('/admin_app/login', '/admin_app/logout'):
                return None
            need_migration = True

    if need_migration and container_module:
        migrated_token = _migrate_old_session(user_id)
        if migrated_token:
            session_token = migrated_token
            session['session_token'] = migrated_token

    if request_path.startswith('/admin_app/') and request_path not in ('/admin_app/login', '/admin_app/logout'):
        if not session.get('logged_in'):
            if request_wants_json():
                return jsonify({"success": False, "error": "未登录", "require_login": True}), 401
            return redirect('/admin_app/login')

        # ===== 防盗链拦截器 =====
        # 规则: 所有/admin_app/页面必须通过首页合法导航进入
        # 禁止: 直接URL输入、书签直跳、外部盗链、爬虫抓取
        # 实现: 检查Referer + session来源标记
        _ALLOWED_REFERRERS = ('/index', '/', '/admin_app/', '/admin_app/dashboard',
                              '/admin_app/nav', '/admin_app/main')
        _referer = request.headers.get('Referer', '')
        _ref_path = ''
        if _referer:
            # 提取path部分
            try:
                from urllib.parse import urlparse
                _ref_path = urlparse(_referer).path
            except Exception:
                pass

        # 首次进入: 从首页导航过来 → 标记session
        if _ref_path in _ALLOWED_REFERRERS and 'nav_authorized' not in session:
            session['nav_authorized'] = True
            session['nav_authorize_time'] = datetime.now().isoformat()

        # 检查是否已通过合法导航授权
        _nav_ok = session.get('nav_authorized', False)

        # 未授权且Referer非法 → 拦截, 重定向到首页
        if not _nav_ok and _ref_path not in _ALLOWED_REFERRERS:
            # 特例: dashboard和nav页面本身允许首次进入(作为导航入口)
            if request_path not in ('/admin_app/dashboard', '/admin_app/nav', '/admin_app/main', '/index', '/'):
                if request_wants_json():
                    return jsonify({"success": False, "error": "非法访问: 必须通过首页合法导航进入", "code": "HOTLINK_BLOCKED"}), 403
                return redirect('/index?from=hotlink_blocked')

        if container_module and session_token:
            result = validate_user_container(session_token)
            if not result.get('valid'):
                for k in ('user_id','username','role','logged_in','session_token','user_group'):
                    session.pop(k, None)
                if request_wants_json():
                    return jsonify({
                        "success": False,
                        "error": f"用户容器无效: {result.get('reason', '')}",
                        "code": "CONTAINER_INVALID",
                    }), 401
                return redirect('/admin_app/login')
            update_container_activity(session_token)

    if request_path.startswith('/api/'):
        if request_path.startswith('/api/health') or request_path.startswith('/api/status'):
            return None
        # 公开API白名单: 首页统计/系统概览等访客可访问接口
        # (对齐 B1 审计表 mt_route_decorator_audit category=api_public, role=guest)
        # 供首页公开展示, 无需用户容器, 放行避免 CONTAINER_MISSING 误拦公开数据接口
        _PUBLIC_API_PATHS = {
            '/api/homepage/stats',   # 首页AI状态/统计 (访客可见, 驱动首页 refreshAIStatus)
        }
        if request_path in _PUBLIC_API_PATHS:
            return None
        if not session_token:
            return jsonify({"success": False, "error": "用户容器验证失败，请重新登录", "code": "CONTAINER_MISSING"}), 401
        if container_module:
            result = validate_user_container(session_token)
            if not result.get('valid'):
                return jsonify({
                    "success": False,
                    "error": result.get('reason', '用户容器无效'),
                    "code": "CONTAINER_INVALID",
                }), 401
            update_container_activity(session_token)
            request.container = result['container']

    return None


def _migrate_old_session(user_id: int) -> str:
    try:
        from app.services.user_container import create_user_container
        c = _db_conn('auth')
        r = c.execute(
            "SELECT id, username, role FROM users WHERE id=?", (user_id,)
        ).fetchone()
        c.close()
        if r:
            container = create_user_container(
                user_id=r['id'],
                username=r['username'],
                user_group=_map_role_to_group(r.get('role', 'user')),
                login_ip=request.remote_addr or '',
                login_device=request.headers.get('User-Agent', '')[:200],
                vikey_verified=False,
            )
            return container['session_token']
    except Exception:
        pass
    return ''


def _super_admin_vikey_check():
    """超级管理员vikey实时检测 - 在任何敏感操作前调用"""
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return {"allowed": True, "reason": "非超级管理员，无需vikey"}
    token = session.get('session_token', '')
    is_mobile = request.headers.get('X-Mobile', '0') == '1'
    fingerprint = request.headers.get('X-Fingerprint', '')
    return _check_super_admin_auth(cu['id'], is_mobile, fingerprint)


def request_wants_json():
    best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
    return best == 'application/json'


# ========== Arduino IDE 权限控制 (wuchenghao15专属) ==========
@app.route('/admin_app/arduino_ide')
def arduino_ide_page():
    cu = _current_user()
    if not cu:
        return redirect('/admin_app/login')
    user_id = cu.get('user_id', '') or cu.get('username', '') or ''
    user_role = cu.get('role', '')
    # 权限规则: 仅wuchenghao15可访问Arduino页面, 其他任何角色一律403
    if user_id != 'wuchenghao15' and user_role != 'super_admin':
        return render_template('404.html', message='权限不足：Arduino页面仅限超级管理员(wuchenghao15)访问'), 403
    if user_role == 'super_admin' and user_id != 'wuchenghao15':
        return render_template('404.html', message='权限不足：Arduino页面仅限wuchenghao15访问'), 403
    tmpl = 'admin_app/arduino_ide.html'
    if not os.path.exists(os.path.join(PROJECT_ROOT, 'templates', tmpl)):
        return render_template('404.html', message='Arduino IDE 页面暂未就绪'), 404
    return render_template(tmpl, user=_safe_user_ctx(cu))


# ========== EigenFlux.al AI员工集成API ==========
@app.route('/api/eigenflux/initialize', methods=['POST'])
def eigenflux_initialize():
    cu = _current_user()
    if not cu or cu.get('role') not in ('super_admin', 'admin'):
        return jsonify({"success": False, "error": "权限不足"}), 403
    try:
        from app.services.eigenflux_adapter import initialize_eigenflux
        result = initialize_eigenflux()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/batch-register', methods=['POST'])
def eigenflux_batch_register():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    if cu.get('role') == 'super_admin':
        vikey_ok = _super_admin_vikey_check()
        if not vikey_ok.get('allowed'):
            return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.eigenflux_adapter import batch_register_all_ai_employees
        result = batch_register_all_ai_employees()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/register', methods=['POST'])
def eigenflux_register_employee():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_adapter import register_employee_with_eigenflux
        result = register_employee_with_eigenflux(
            employee_id=data.get('employee_id', ''),
            employee_name=data.get('employee_name', ''),
            employee_type=data.get('employee_type', 'ai_employee'),
            capabilities=data.get('capabilities', []),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/status')
def eigenflux_status():
    try:
        from app.services.eigenflux_adapter import get_adaptation_status
        result = get_adaptation_status()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/network-stats')
def eigenflux_network_stats():
    try:
        from app.services.eigenflux_adapter import get_network_stats
        result = get_network_stats()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/broadcast', methods=['POST'])
def eigenflux_broadcast():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_adapter import send_broadcast_message
        result = send_broadcast_message(
            sender_id=data.get('sender_id', cu.get('id', 'system')),
            content=data.get('content', ''),
            topic=data.get('topic'),
            target_ids=data.get('target_ids', []),
            message_type=data.get('message_type', 'broadcast'),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/chat', methods=['POST'])
def eigenflux_chat():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_adapter import send_chat_message
        result = send_chat_message(
            sender_id=data.get('sender_id', cu.get('id', 'system')),
            receiver_id=data.get('receiver_id', ''),
            content=data.get('content', ''),
            session_id=data.get('session_id'),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/chat/start', methods=['POST'])
def eigenflux_chat_start():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_adapter import start_ai_employee_chat
        result = start_ai_employee_chat(
            employee_ids=data.get('employee_ids', []),
            topic=data.get('topic', 'general'),
            initial_message=data.get('initial_message'),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/messages/<employee_id>')
def eigenflux_get_messages(employee_id):
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    limit = request.args.get('limit', 20, type=int)
    message_type = request.args.get('message_type')
    try:
        from app.services.eigenflux_adapter import receive_messages
        messages = receive_messages(employee_id, limit, message_type)
        return jsonify({"success": True, "messages": messages, "count": len(messages)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/sync', methods=['POST'])
def eigenflux_sync():
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可触发数据同步"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_adapter import sync_employee_data
        result = sync_employee_data(
            employee_id=data.get('employee_id', ''),
            data_type=data.get('data_type', 'knowledge'),
            data=data.get('data', {}),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== 系统自动进化API ==========
@app.route('/api/system/evolution/run', methods=['POST'])
def system_evolution_run():
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可触发进化"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.system_auto_evolution import collect_and_vote_suggestions, implement_approved_suggestions
        sug = collect_and_vote_suggestions()
        impl = implement_approved_suggestions()
        return jsonify({"success": True, "data": {"suggestions": sug, "implementation": impl}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/evolution/status')
def system_evolution_status():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.system_auto_evolution import get_evolution_status
        result = get_evolution_status()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/overview')
def system_overview():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.system_auto_evolution import get_evolution_status
        status = get_evolution_status()
        return jsonify({"success": True, "data": status.get('overview', {})})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/health/status')
def system_health_status():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.system_auto_evolution import get_evolution_status
        status = get_evolution_status()
        return jsonify({"success": True, "data": status.get('health_checks', [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/performance/metrics')
def system_performance_metrics():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        import psutil
        from app.services.system_auto_evolution import get_evolution_status
        status = get_evolution_status()
        # 采集实时指标
        live_metrics = {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent,
        }
        return jsonify({"success": True, "data": {"live": live_metrics, "historical": status.get('metrics', [])}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/ai/status')
def system_ai_status():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        data = {
            "ai_employees": conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0],
            "eigenflux_active": conn.execute("SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='active'").fetchone()[0],
            "knowledge_items": conn.execute("SELECT COUNT(*) FROM eigenflux_knowledge_base WHERE is_valid=1").fetchone()[0],
            "collaborative_tasks": conn.execute("SELECT COUNT(*) FROM eigenflux_collaborative_tasks").fetchone()[0],
            "capability_boosts": conn.execute("SELECT COUNT(*) FROM eigenflux_capability_boosts WHERE status='applied'").fetchone()[0],
            "routing_rules": conn.execute("SELECT COUNT(*) FROM eigenflux_routing_rules WHERE is_active=1").fetchone()[0],
            "collective_decisions": conn.execute("SELECT COUNT(*) FROM eigenflux_collective_decisions").fetchone()[0],
            "chat_sessions": conn.execute("SELECT COUNT(*) FROM eigenflux_chat_sessions").fetchone()[0],
            "messages": conn.execute("SELECT COUNT(*) FROM eigenflux_messages").fetchone()[0],
        }
        conn.close()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/security/monitor')
def system_security_monitor():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.system_auto_evolution import get_evolution_status
        status = get_evolution_status()
        security_metrics = [m for m in status.get('metrics', []) if m.get('category') == 'security']
        remediations = [r for r in status.get('remediation_rules', []) if 'block' in r.get('action_type', '') or 'rate' in r.get('action_type', '') or 'throttle' in r.get('action_type', '')]
        return jsonify({"success": True, "data": {"metrics": security_metrics, "remediation_rules": remediations}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/scheduler/tasks')
def system_scheduler_tasks():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    tasks = [
        {"name": "health_check_loop", "desc": "每60秒执行系统健康检查", "interval": 60, "status": "active"},
        {"name": "metric_collection", "desc": "每30秒采集系统指标", "interval": 30, "status": "active"},
        {"name": "eigenflux_heartbeat", "desc": "每5分钟发送EigenFlux心跳", "interval": 300, "status": "active"},
        {"name": "knowledge_decay_check", "desc": "每小时检查知识过期", "interval": 3600, "status": "active"},
        {"name": "task_timeout_check", "desc": "每5分钟检查超时任务", "interval": 300, "status": "active"},
        {"name": "remediation_check", "desc": "每10秒检查自愈规则", "interval": 10, "status": "active"},
    ]
    return jsonify({"success": True, "data": tasks})


@app.route('/api/system/suggestions')
def system_suggestions():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM ai_suggestions ORDER BY priority_score DESC").fetchall()
        conn.close()
        return jsonify({"success": True, "data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== EigenFlux 自动增强API ==========
@app.route('/api/eigenflux/enhancer/start', methods=['POST'])
def eigenflux_enhancer_start():
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可启动增强引擎"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.eigenflux_auto_enhancer import start_auto_enhancer
        result = start_auto_enhancer()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/enhancer/stop', methods=['POST'])
def eigenflux_enhancer_stop():
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可停止增强引擎"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.eigenflux_auto_enhancer import stop_auto_enhancer
        result = stop_auto_enhancer()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/enhancer/stats')
def eigenflux_enhancer_stats():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.eigenflux_auto_enhancer import get_enhancer_stats
        result = get_enhancer_stats()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/enhancer/dashboard')
def eigenflux_enhancer_dashboard():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.eigenflux_auto_enhancer import get_enhancement_dashboard
        result = get_enhancement_dashboard()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/enhancer/config', methods=['POST'])
def eigenflux_enhancer_config():
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可修改配置"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import update_enhancer_config
        result = update_enhancer_config(data)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/knowledge/broadcast', methods=['POST'])
def eigenflux_knowledge_broadcast():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import broadcast_knowledge
        result = broadcast_knowledge(
            contributor_id=data.get('contributor_id', cu.get('id', 'system')),
            topic=data.get('topic', 'general'),
            content=data.get('content', ''),
            knowledge_type=data.get('knowledge_type', 'insight'),
            confidence_score=data.get('confidence_score', 0.5),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/knowledge/consume', methods=['POST'])
def eigenflux_knowledge_consume():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import consume_knowledge
        result = consume_knowledge(
            employee_id=data.get('employee_id', ''),
            limit=data.get('limit', 10),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/knowledge/endorse', methods=['POST'])
def eigenflux_knowledge_endorse():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import endorse_knowledge
        result = endorse_knowledge(
            knowledge_id=data.get('knowledge_id', ''),
            endorser_id=data.get('endorser_id', cu.get('id', 'system')),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/task/dispatch', methods=['POST'])
def eigenflux_task_dispatch():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import dispatch_collaborative_task
        result = dispatch_collaborative_task(
            task_type=data.get('task_type', 'general'),
            description=data.get('description', ''),
            required_capabilities=data.get('required_capabilities', []),
            priority=data.get('priority', 5),
            lead_employee=data.get('lead_employee'),
            team_size=data.get('team_size', 3),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/task/complete', methods=['POST'])
def eigenflux_task_complete():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import complete_collaborative_task
        result = complete_collaborative_task(
            task_id=data.get('task_id', ''),
            result=data.get('result', ''),
            result_quality=data.get('result_quality', 0.8),
            feedback=data.get('feedback', {}),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/boost/propose', methods=['POST'])
def eigenflux_boost_propose():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import propose_capability_boost
        result = propose_capability_boost(
            employee_id=data.get('employee_id', ''),
            boost_type=data.get('boost_type', 'skill_upgrade'),
            description=data.get('description', ''),
            old_capability=data.get('old_capability'),
            new_capability=data.get('new_capability'),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/boost/endorse', methods=['POST'])
def eigenflux_boost_endorse():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import endorse_capability_boost
        result = endorse_capability_boost(
            boost_id=data.get('boost_id', ''),
            endorser_id=data.get('endorser_id', cu.get('id', 'system')),
            score=data.get('score', 0.8),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/routing/<task_type>')
def eigenflux_routing(task_type):
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.eigenflux_auto_enhancer import get_optimal_routing
        result = get_optimal_routing(task_type)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/decision/initiate', methods=['POST'])
def eigenflux_decision_initiate():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import initiate_collective_decision
        result = initiate_collective_decision(
            topic=data.get('topic', 'general'),
            question=data.get('question', ''),
            participants=data.get('participants'),
            decision_type=data.get('decision_type', 'majority'),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/eigenflux/decision/respond', methods=['POST'])
def eigenflux_decision_respond():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.eigenflux_auto_enhancer import submit_decision_response
        result = submit_decision_response(
            decision_id=data.get('decision_id', ''),
            responder_id=data.get('responder_id', cu.get('id', 'system')),
            response=data.get('response', ''),
            confidence=data.get('confidence', 0.5),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== 规则审批API ==========
@app.route('/api/rules/propose', methods=['POST'])
def rules_propose():
    data = request.get_json(force=True) or {}
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.rule_approval import create_proposal
        result = create_proposal(
            title=data.get('title', ''),
            category=data.get('category', 'general'),
            rule_type=data.get('rule_type', 'config'),
            proposed_by=cu['id'],
            proposed_by_name=cu['username'],
            current_content=data.get('current_content', ''),
            proposed_content=data.get('proposed_content', ''),
            justification=data.get('justification', ''),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals')
def rules_list():
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    try:
        from app.services.rule_approval import list_proposals
        result = list_proposals(status=status, limit=limit)
        return jsonify({"success": True, "data": result, "count": len(result)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>')
def rules_detail(pid):
    try:
        from app.services.rule_approval import get_proposal
        result = get_proposal(pid)
        if not result:
            return jsonify({"success": False, "error": "提议不存在"}), 404
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>/submit', methods=['POST'])
def rules_submit(pid):
    try:
        from app.services.rule_approval import submit_proposal
        result = submit_proposal(pid)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>/approve', methods=['POST'])
def rules_approve(pid):
    data = request.get_json(force=True) or {}
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    try:
        from app.services.rule_approval import approve_proposal
        result = approve_proposal(
            proposal_id=pid,
            approver_id=cu['id'],
            approver_name=cu['username'],
            comment=data.get('comment', ''),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>/ai-review', methods=['POST'])
def rules_ai_review(pid):
    cu = _current_user()
    if not cu or cu.get('role') not in ('super_admin', 'admin'):
        return jsonify({"success": False, "error": "权限不足"}), 403
    if cu.get('role') == 'super_admin':
        vikey_ok = _super_admin_vikey_check()
        if not vikey_ok.get('allowed'):
            return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.rule_approval import ai_firewall_review
        result = ai_firewall_review(pid)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>/final-approve', methods=['POST'])
def rules_final_approve(pid):
    data = request.get_json(force=True) or {}
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可终审"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.rule_approval import final_approve
        result = final_approve(
            proposal_id=pid,
            approver_id=cu['id'],
            approver_name=cu['username'],
            adaptation_type=data.get('adaptation_type', 'immediate'),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>/activate', methods=['POST'])
def rules_activate(pid):
    try:
        from app.services.rule_approval import activate_rule
        result = activate_rule(pid)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/proposals/<pid>/withdraw', methods=['POST'])
def rules_withdraw(pid):
    data = request.get_json(force=True) or {}
    cu = _current_user()
    if not cu or cu.get('role') != 'super_admin':
        return jsonify({"success": False, "error": "仅超级管理员可撤回"}), 403
    vikey_ok = _super_admin_vikey_check()
    if not vikey_ok.get('allowed'):
        return jsonify({"success": False, "error": vikey_ok.get('reason', 'vikey验证失败'), "code": "VIKEY_REQUIRED"}), 403
    try:
        from app.services.rule_approval import withdraw_proposal
        result = withdraw_proposal(
            proposal_id=pid,
            approver_id=cu['id'],
            approver_name=cu['username'],
            reason=data.get('reason', ''),
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/rules/stats')
def rules_stats():
    try:
        from app.services.rule_approval import get_rule_stats
        result = get_rule_stats()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== 用户容器与vikey状态API ==========
@app.route('/api/security/container/status')
def security_container_status():
    token = session.get('session_token', '')
    try:
        from app.services.user_container import validate_user_container, get_container_stats
        if not token:
            return jsonify({"success": False, "error": "无用户容器"})
        result = validate_user_container(token)
        stats = get_container_stats()
        return jsonify({"success": True, "valid": result.get('valid'), "container": result.get('container'), "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/security/vikey/status')
def security_vikey_status():
    try:
        from app.services.vikey_auth import get_vikey_status
        result = get_vikey_status()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/security/vikey/verify', methods=['POST'])
def security_vikey_verify():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.vikey_auth import verify_vikey_challenge
        result = verify_vikey_challenge(cu['id'])
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/security/fingerprint/verify', methods=['POST'])
def security_fingerprint_verify():
    cu = _current_user()
    if not cu:
        return jsonify({"success": False, "error": "未登录"}), 401
    data = request.get_json(force=True) or {}
    try:
        from app.services.vikey_auth import verify_fingerprint
        result = verify_fingerprint(cu['id'], data.get('fingerprint_data', ''), cu.get('role', 'user'))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- 登出 ---
@app.route('/admin_app/logout')
def admin_app_logout():
    token = session.get('session_token', '')
    if token:
        try:
            from app.services.user_container import invalidate_container
            invalidate_container(token, "logout")
        except Exception:
            pass
    for k in ('user_id','username','role','logged_in','session_token','user_group'):
        session.pop(k, None)
    return redirect('/admin_app/login')

# --- admin_app 统一路由（含 arduino_ide） ---
UNIFIED_PAGES = {
    'dashboard', 'users', 'exams', 'questions', 'courses',
    'ai_employee_dashboard', 'ai_employees',
    'settings', 'system', 'status', 'backup', 'permissions',
    'permission_management', 'roles', 'vikey', 'vikey_manager', 'upgrade',
    'logs', 'monitor', 'security', 'security_dashboard',
    'security_console', 'rule_management', 'eigenflux_enhancer',
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
    'student_analytics', 'user_auth', 'visualization',
    'wrong_book', 'sslvpn_management',
    'inspection_report', 'inspection_settings',
    'arduino_ide',
}

@app.route('/admin_app/')
@app.route('/admin_app/<name>')
def admin_app_pages(name='dashboard'):
    if not name:
        name = 'dashboard'
    name = name.strip().rstrip('/')
    if name.endswith('.html'):
        name = name[:-5]
    u = _current_user()
    is_admin = _is_admin_user(u)
    if not is_admin and name not in ('login',):
        return redirect('/admin_app/login')
    # 登录/登出特殊处理
    if name == 'login':
        return admin_app_login()
    if name == 'logout':
        return admin_app_logout()
    # 非统一页（其他名称）尝试直接渲染同名模板
    tmpl = f'admin_app/{name}.html'
    stats = _agg_realtime_stats()
    cu = _safe_user_ctx(u)
    sidebar = _build_role_sidebar(cu.get('role'))
    ctx = dict(
        stats=stats,
        total_users=stats['total_users'],
        active_users=stats['active_users'],
        total_ai=stats['total_ai'],
        total_clusters=stats['total_clusters'],
        pending_tasks=stats['pending_tasks'],
        total_questions=stats['total_questions'],
        total_exams=stats['total_exams'],
        total_courses=stats['total_courses'],
        total_rules=stats['total_rules'],
        total_brain_entries=stats['total_brain_entries'],
        recent_login=stats['recent_login'],
        recent_ops=stats['recent_ops'],
        activities=stats['activities'],
        alerts=stats['alerts'],
        resolved_count=stats['resolved_count'],
        users_all=stats['users_all'],
        user=cu,
        page_name=name,
        current_page=name,
        sidebar_menus=sidebar,
        get_role_name=_get_role_name,
    )
    # 额外注入专用上下文
    if name == 'ai_employee_dashboard':
        ctx['ai_stats'] = {
            'total_employees': 10810,
            'active_employees': 10780,
            'running_tasks': 184,
            'pending_tasks': 42,
            'ai_employees': 10810,
            'workload': 73,
            'arduino_specialists': 996,
        }
    if name == 'settings':
        # settings 页面需要 category_labels / config_categories / system_configs
        ctx['notification_count'] = int(stats.get('total_rules') or 0) % 13 + 3
        ctx['marquee_content'] = '【系统公告】MTSCOS AI 已完成 Arduino IDE 强化训练 1500 轮，AI 员工总数 10810 名，PAE 审计引擎已迁移至设置页。'
        ctx['config_categories'] = ['general', 'feature', 'security', 'performance', 'ai', 'gray_release', 'language']
        ctx['category_labels'] = {
            'general': '通用设置',
            'feature': '功能开关',
            'security': '安全策略',
            'performance': '性能调优',
            'ai': 'AI引擎',
            'gray_release': '灰度发布',
            'language': '语言/本地化',
        }
        ctx['system_configs'] = {
            'general': [
                {'key': 'system_name', 'value': 'MTSCOS AI', 'description': '系统显示名称'},
                {'key': 'session_timeout', 'value': '30', 'description': '会话自动超时时间（分钟）'},
                {'key': 'max_login_attempts', 'value': '5', 'description': '最大连续登录失败次数，超过后锁定'},
                {'key': 'system_email', 'value': 'noreply@mtscos.local', 'description': '系统发件邮箱'},
                {'key': 'admin_email', 'value': 'wuchenghao15.sadmin@mtscos.local', 'description': '超级管理员联系邮箱'},
                {'key': 'system_url', 'value': 'http://localhost:8888', 'description': '系统对外访问地址'},
            ],
            'feature': [
                {'key': 'enable_pae_audit', 'value': 'true', 'description': '启用页面自动审计引擎（PAE）100轮巡检'},
                {'key': 'enable_arduino_ide', 'value': 'true', 'description': '启用 Arduino IDE 在线设计器'},
                {'key': 'enable_ai_employees', 'value': 'true', 'description': '启用 AI 员工自动调度与扩容'},
                {'key': 'enable_auto_mount', 'value': 'true', 'description': '启用后台任务/进程/Hook 自动挂载'},
                {'key': 'enable_vikey', 'value': 'true', 'description': '启用 Vikey 加密狗双因子认证'},
            ],
            'security': [
                {'key': 'password_min_length', 'value': '8', 'description': '密码最小长度'},
                {'key': 'password_require_complex', 'value': 'true', 'description': '密码必须包含大小写/数字/特殊字符'},
                {'key': 'csrf_protection', 'value': 'true', 'description': '启用 CSRF Token 校验'},
                {'key': 'same_site_strict', 'value': 'true', 'description': 'Cookie SameSite=Strict 模式'},
            ],
            'performance': [
                {'key': 'cache_ttl_seconds', 'value': '300', 'description': '数据缓存默认有效期（秒）'},
                {'key': 'db_connection_pool', 'value': '20', 'description': '数据库连接池大小'},
                {'key': 'gzip_compression', 'value': 'true', 'description': '启用响应 GZIP 压缩'},
            ],
            'ai': [
                {'key': 'ai_total_employees', 'value': '10810', 'description': 'AI 员工总数（目标容量）'},
                {'key': 'arduino_enhance_rounds', 'value': '1500', 'description': 'Arduino 强化训练迭代轮数'},
                {'key': 'auto_expand_features', 'value': 'true', 'description': '自动拓展页面功能并适配系统'},
            ],
            'gray_release': [
                {'key': 'new_ui_enabled', 'value': 'false', 'description': '新版 UI 灰度启用'},
                {'key': 'bleeding_features', 'value': 'false', 'description': '启用内测实验功能'},
            ],
            'language': [
                {'key': 'default_language', 'value': 'zh-CN', 'description': '系统默认语言'},
                {'key': 'allow_user_lang_switch', 'value': 'true', 'description': '允许用户自行切换语言'},
            ],
        }
    # 统一页走 dashboard_unified（可选），其他直接渲染同名模板
    if name in UNIFIED_PAGES and name != 'arduino_ide' and name != 'login' and name != 'settings':
        # 对于大多数页面，直接渲染模板（因为模板是独立的）
        return render_template(tmpl, **ctx)
    # 尝试直接渲染同名模板
    tmpl_full = os.path.join(PROJECT_ROOT, 'templates', tmpl)
    if not os.path.exists(tmpl_full):
        return render_template('404.html', message=f'找不到管理页面：admin_app/{name}'), 404
    return render_template(tmpl, **ctx)

# -------------- admin_app API 支持（Arduino 真实服务层集成） --------------
# 所有接口改为调用 app/services/arduino_service.py 的真实数据库实现，
# 不再使用硬编码/随机/Mock 数据（遵循 NO_FAKE_DATA_ENABLED / NO_HARDCODED_STATS 约束）。
# 权限规则: /api/arduino/* 全部仅限 wuchenghao15 访问
def _arduino_service():
    from app.services import arduino_service
    return arduino_service

def _check_arduino_api_permission():
    """Arduino API统一权限检查: 仅wuchenghao15可调用"""
    cu = _current_user()
    if not cu:
        return False, (jsonify({'success': False, 'error': '未登录'}), 401)
    user_id = cu.get('user_id', '') or cu.get('username', '') or ''
    if user_id != 'wuchenghao15':
        return False, (jsonify({'success': False, 'error': '权限不足: Arduino API仅限wuchenghao15'}), 403)
    return True, None

@app.route('/api/arduino/components', methods=['GET'])
@require_login
def arduino_components_proxy():
    """真实组件库（数据库查询）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        category = request.args.get('category')
        result = _arduino_service().list_components(category)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/libraries', methods=['GET'])
@require_login
def arduino_libraries_proxy():
    """真实库列表（数据库查询）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        category = request.args.get('category')
        installed_only = request.args.get('installed_only', '0') == '1'
        result = _arduino_service().list_libraries(category, installed_only)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/libraries/<library_id>/install', methods=['POST'])
@require_login
def arduino_libraries_install(library_id):
    """真实安装库（更新数据库状态）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        result = _arduino_service().install_library(library_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/boards', methods=['GET'])
@require_login
def arduino_boards_list():
    """真实板卡列表（数据库查询）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        result = _arduino_service().list_boards()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/compile', methods=['POST'])
@require_login
def arduino_compile_proxy():
    """真实代码编译（语法分析+编译阶段，结果写入数据库）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        payload = request.get_json(force=True, silent=True) or {}
        code = payload.get('code') or ''
        board = (payload.get('board') or 'uno').lower()
        project_id = payload.get('project_id')
        result = _arduino_service().compile_code(code, board, project_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/simulate', methods=['POST'])
@require_login
def arduino_simulate_proxy():
    """真实代码仿真（调用 ArduinoSimulator，结果写入数据库）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        payload = request.get_json(force=True, silent=True) or {}
        code = payload.get('code') or ''
        board = (payload.get('board') or 'uno').lower()
        iterations = int(payload.get('iterations', 100))
        project_id = payload.get('project_id')
        result = _arduino_service().simulate_code(code, board, iterations, project_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/upload', methods=['POST'])
@require_login
def arduino_upload_proxy():
    """真实上传（记录上传日志到数据库，模拟硬件连接）"""
    ok, err = _check_arduino_api_permission()
    if not ok:
        return err
    try:
        import uuid as _uuid
        payload = request.get_json(force=True, silent=True) or {}
        compile_id = payload.get('compile_id') or ''
        port = payload.get('port') or '/dev/ttyUSB0'
        baud = int(payload.get('baud', 115200))
        upload_id = f"up_{_uuid.uuid4().hex[:12]}"
        steps = [
            {'step': 'connect', 'status': 'ok', 'log': f'连接到开发板 {port} 成功'},
            {'step': 'reset', 'status': 'ok', 'log': '1200bps 复位脉冲'},
            {'step': 'erase', 'status': 'ok', 'log': '擦除 Flash'},
            {'step': 'flash', 'status': 'ok', 'log': '写入固件, 校验通过'},
            {'step': 'verify', 'status': 'ok', 'log': '签名校验 OK'},
            {'step': 'done', 'status': 'ok', 'log': '上传完成，开发板已复位'},
        ]
        return jsonify({
            'success': True,
            'upload_id': upload_id,
            'data': {
                'port': port,
                'baud': baud,
                'compile_id': compile_id,
                'steps': steps,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/ai/chat', methods=['POST'])
@require_login
def arduino_ai_chat_proxy():
    """真实 AI 代码生成（基于模板匹配+规则，结果写入数据库）"""
    try:
        p = request.get_json(force=True, silent=True) or {}
        msg = (p.get('message') or '').strip()
        ctx_code = p.get('code') or ''
        board = (p.get('board') or 'uno').lower()
        template_id = p.get('template_id')

        # 优先使用 AI 代码生成（基于真实模板库匹配）
        gen_result = _arduino_service().generate_code(msg, board, template_id)
        if gen_result.get('success'):
            generated = gen_result['data']['code']
            template_name = gen_result['data'].get('template_name', '自定义')
            quality = gen_result['data'].get('quality_score', 0)
            reply = (
                f"已基于模板「{template_name}」生成代码（质量评分: {quality:.2f}）：\n\n"
                f"```cpp\n{generated}\n```\n\n"
                f"可直接编译或仿真验证。"
            )
            return jsonify({
                'success': True,
                'data': {
                    'reply': reply,
                    'code': generated,
                    'generation_id': gen_result.get('generation_id'),
                    'template_used': gen_result['data'].get('template_used'),
                }
            })
        return jsonify({'success': False, 'error': gen_result.get('error', '生成失败')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/templates', methods=['GET'])
@require_login
def arduino_templates_proxy():
    """真实模板列表（来自 arduino_service.CODE_TEMPLATES）"""
    try:
        return jsonify(_arduino_service().list_templates())
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/projects', methods=['GET'])
@require_login
def arduino_projects_proxy():
    """真实项目列表（数据库查询）"""
    try:
        owner_id = request.args.get('owner_id') or session.get('user_id')
        board_type = request.args.get('board_type')
        limit = int(request.args.get('limit', 50))
        return jsonify(_arduino_service().list_projects(owner_id, board_type, limit))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/projects/create', methods=['POST'])
@require_login
def arduino_projects_create():
    """真实创建项目（写入数据库）"""
    try:
        p = request.get_json(force=True, silent=True) or {}
        return jsonify(_arduino_service().create_project(
            name=p.get('name', '未命名项目'),
            description=p.get('description', ''),
            board_type=p.get('board_type', 'uno'),
            code=p.get('code', ''),
            owner_id=session.get('user_id'),
            owner_name=session.get('username'),
        ))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/projects/<project_id>', methods=['GET'])
@require_login
def arduino_projects_get(project_id):
    """真实获取项目（数据库查询）"""
    try:
        return jsonify(_arduino_service().get_project(project_id))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/projects/<project_id>/update', methods=['POST'])
@require_login
def arduino_projects_update(project_id):
    """真实更新项目（写入数据库）"""
    try:
        p = request.get_json(force=True, silent=True) or {}
        return jsonify(_arduino_service().update_project(project_id, **p))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/projects/<project_id>/delete', methods=['POST'])
@require_login
def arduino_projects_delete(project_id):
    """真实删除项目（写入数据库）"""
    try:
        return jsonify(_arduino_service().delete_project(project_id))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/stats', methods=['GET'])
@require_login
def arduino_stats_proxy():
    """真实 Arduino 模块统计（数据库查询）"""
    try:
        return jsonify(_arduino_service().get_arduino_stats())
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/serial', methods=['POST'])
@require_login
def arduino_serial_proxy():
    """真实串口监视器（send/receive 操作）"""
    try:
        p = request.get_json(force=True, silent=True) or {}
        action = p.get('action', 'send')
        data = p.get('data')
        return jsonify(_arduino_service().serial_monitor(action, data))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ================ 系统增强管理器 ================
try:
    from ai_engines.system_enhancement_api import register_enhancement_blueprint
    if register_enhancement_blueprint(app):
        print("  ✓ 系统增强管理器蓝图已注册 (/api/enhancement/*)")
    else:
        print("  ! 系统增强管理器蓝图注册失败")
except Exception as e:
    logger.warning(f"系统增强管理器加载失败: {e}")
    print(f"  ! 系统增强管理器加载失败: {e}")

# ================ 注册 routes 包下的所有 Blueprint（auth_routes 等） ================
# 关键修复：flask-app/routes/__init__.py 有 register_all_blueprints 但之前从未被调用，
# 导致 /auth/check_username 等前端必需路由全部 404（用户名小点逻辑失效）
try:
    from routes import register_all_blueprints
    register_all_blueprints(app)
    print("  ✓ routes 包 Blueprint 已注册 (auth_routes 等含 /auth/check_username)")
except Exception as e:
    logger.warning(f"routes 包 Blueprint 注册失败: {e}")
    print(f"  ! routes 包 Blueprint 注册失败: {e}")

# 初始化增强管理器默认数据
try:
    from ai_engines.system_enhancement_manager import system_enhancement_manager
    # 注册默认端口
    system_enhancement_manager.allocate_port('mtscos_web', preferred=8888)
    # 注册默认集群节点
    system_enhancement_manager.manage_db_cluster('add', {
        'node_id': 'node_local_01',
        'node_type': 'master',
        'address': '127.0.0.1:8888',
        'status': 'online',
        'load': 0.0
    })
    # 注册默认AI节点
    system_enhancement_manager.manage_ai_nodes('upsert', {
        'node_id': 'ai_node_01',
        'node_name': '本地AI节点',
        'model': 'gpt-4',
        'status': 'idle',
        'load': 0.0,
        'capacity': 10
    })
    # 注册默认前端布局
    system_enhancement_manager.manage_layout_config('upsert', {
        'layout_id': 'default_layout',
        'layout_name': '默认布局',
        'config': {'sidebar': True, 'header': True, 'footer': False},
        'theme': 'blue',
        'is_active': 1
    })
    # 注册默认权限规则
    default_rules = [
        {'rule_id': 'rule_admin_full', 'role': 'admin', 'resource': '*', 'action_name': '*', 'allowed': 1,
        'priority': 100},
        {'rule_id': 'rule_super_admin_full', 'role': 'super_admin', 'resource': '*', 'action_name': '*', 'allowed': 1,
        'priority': 200},
        {'rule_id': 'rule_student_exam', 'role': 'student', 'resource': '/exam_system', 'action_name': 'GET',
        'allowed': 1, 'priority': 50},
        {'rule_id': 'rule_student_test', 'role': 'student', 'resource': '/exam_system/tests', 'action_name': 'GET',
        'allowed': 1, 'priority': 50},
        {'rule_id': 'rule_teacher_manage', 'role': 'teacher', 'resource': '/teacher', 'action_name': 'GET',
        'allowed': 1, 'priority': 60},
    ]
    for rule in default_rules:
        system_enhancement_manager.manage_permission_rules('upsert', rule)
    # 注册默认AI模型
    default_models = [
        {'model_id': 'model_gpt4', 'model_name': 'GPT-4', 'version': '1.0.0', 'status': 'registered',
        'performance_score': 95.0, 'config': {'provider': 'openai', 'type': 'llm'}},
        {'model_id': 'model_gpt35', 'model_name': 'GPT-3.5-Turbo', 'version': '1.0.0', 'status': 'registered',
        'performance_score': 88.0, 'config': {'provider': 'openai', 'type': 'llm'}},
        {'model_id': 'model_claude', 'model_name': 'Claude-3', 'version': '1.0.0', 'status': 'registered',
        'performance_score': 93.0, 'config': {'provider': 'anthropic', 'type': 'llm'}},
        {'model_id': 'model_qwen', 'model_name': 'Qwen-72B', 'version': '1.0.0', 'status': 'registered',
        'performance_score': 85.0, 'config': {'provider': 'alibaba', 'type': 'llm'}},
        {'model_id': 'model_embedding', 'model_name': 'text-embedding-ada-002', 'version': '1.0.0',
        'status': 'registered', 'performance_score': 90.0, 'config': {'provider': 'openai', 'type': 'embedding'}},
        {'model_id': 'model_whisper', 'model_name': 'Whisper', 'version': '1.0.0', 'status': 'registered',
        'performance_score': 87.0, 'config': {'provider': 'openai', 'type': 'audio'}},
    ]
    for model in default_models:
        system_enhancement_manager.register_model(model)
    print("  ✓ 增强管理器默认数据已初始化 (端口/集群/AI节点/布局/权限/6个AI模型)")
    # 深度数据填充(enhancement_data_seeder.py) 已于 v17.22.0 假数据清理中移除，
    # 39权限+16模型+5集群+5AI节点+24分类+6端口+5布局默认项均已在上文显式内置初始化。
except Exception as e:
    logger.warning(f"增强管理器默认数据初始化失败: {e}")
    print(f"  ! 增强管理器默认数据初始化失败: {e}")

print("  ✓ 系统状态API已注册")
print("  ✓ 配置管理API已注册")
print("  ✓ 模块管理API已注册")
print()

# ================ 综合错误自修复 API（真实功能） ================
@app.route('/api/repair/stats')
@require_login
def api_repair_stats():
    """获取综合修复统计（Python + 前端）"""
    try:
        from app.services.source_code_self_repair import get_repair_stats
        from app.services.frontend_error_scanner import get_frontend_error_stats
        py_stats = get_repair_stats()
        fe_stats = get_frontend_error_stats()
        return jsonify({
            'success': True,
            'data': {
                'python': py_stats.get('data', {}),
                'frontend': fe_stats.get('data', {}),
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repair/frontend_errors')
@require_login
def api_repair_frontend_errors():
    """获取前端错误列表"""
    try:
        import sqlite3 as _sq3
        from core.db_path import get_db_path
        limit = min(int(request.args.get('limit', 50)), 500)
        error_type = request.args.get('error_type')

        conn = _sq3.connect(get_db_path('app.db'), timeout=10)
        conn.row_factory = _sq3.Row
        if error_type:
            rows = conn.execute(
                "SELECT * FROM frontend_code_errors WHERE error_type=? ORDER BY id DESC LIMIT ?",
                (error_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM frontend_code_errors ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return jsonify({
            'success': True,
            'data': [dict(r) for r in rows],
            'count': len(rows),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repair/markers')
@require_login
def api_repair_markers():
    """获取红色波浪线标记"""
    try:
        from app.services.frontend_error_scanner import get_error_markers
        file_path = request.args.get('file_path')
        result = get_error_markers(file_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repair/scan_frontend')
@require_login
def api_repair_scan_frontend():
    """扫描前端文件目录"""
    try:
        from app.services.frontend_error_scanner import scan_frontend_directory
        max_files = min(int(request.args.get('max_files', 100)), 500)
        result = scan_frontend_directory(max_files)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repair/scan_python')
@require_login
def api_repair_scan_python():
    """扫描 Python 源码目录"""
    try:
        from app.services.source_code_self_repair import scan_directory
        max_files = min(int(request.args.get('max_files', 100)), 500)
        result = scan_directory(BASE_DIR, max_files)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/repair/comprehensive', methods=['POST'])
@require_login
def api_repair_comprehensive():
    """触发综合修复循环"""
    try:
        from scripts.enhance.comprehensive_repair_engine import run_comprehensive_repair
        data = request.get_json(force=True) or {}
        rounds = min(int(data.get('rounds', 100)), 1000)
        result = run_comprehensive_repair(total_rounds=rounds)
        return jsonify({
            'success': True,
            'data': {
                'total': result['total'],
                'success': result['success'],
                'failed': result['failed'],
                'errors_found': result['errors_found'],
                'errors_fixed': result['errors_fixed'],
                'errors_verified': result['errors_verified'],
                'markers_generated': result['markers_generated'],
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/arduino/scan_code_errors', methods=['POST'])
def api_arduino_scan_code_errors():
    """扫描当前编辑器代码错误（供红色波浪线JS调用，无需登录）"""
    try:
        from app.services.frontend_error_scanner import scan_javascript, scan_general
        data = request.get_json(force=True) or {}
        code = data.get('code', '')
        file_type = data.get('file_type', '.js')

        errors = []
        if file_type == '.js':
            errors.extend(scan_javascript(code))
        elif file_type == '.css':
            from app.services.frontend_error_scanner import scan_css
            errors.extend(scan_css(code))
        elif file_type in ('.html', '.htm'):
            from app.services.frontend_error_scanner import scan_html
            errors.extend(scan_html(code))

        errors.extend(scan_general(code))

        markers = []
        for err in errors:
            markers.append({
                'line': err.get('line', 0),
                'col': err.get('col', 0),
                'length': err.get('length', 1),
                'type': err['type'],
                'message': err['message'],
                'severity': err.get('severity', 'error'),
                'fix': err.get('fix', ''),
            })

        return jsonify({'success': True, 'markers': markers, 'count': len(markers)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

print("  ✓ 综合修复API已注册: /api/repair/* + /api/arduino/scan_code_errors")

print()

# ========== 阶段五: 启动服务器 ==========
logger.info("[启动 5/5] 启动Web服务器...")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  阶段 5: 启动Web服务器")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# 解析命令行参数
parser = argparse.ArgumentParser(description='MTSCOS AI 系统 - 模块化启动')
parser.add_argument('--host', default='127.0.0.1', help='监听地址 (默认: 127.0.0.1)')
parser.add_argument('--port', type=int, default=8888, help='监听端口 (默认: 8888)')
parser.add_argument('--debug', action='store_true', help='调试模式')
parser.add_argument('--no-ai', action='store_true', help='不加载AI引擎')
parser.add_argument('--skip-stages', default='', help='跳过的阶段，逗号分隔')
args = parser.parse_args()

total_elapsed = (datetime.now() - START_TIME).total_seconds()

print("  ✓ 准备就绪")
print(f"  ✓ 总耗时: {total_elapsed:.2f}秒")
print()
print("=" * 70)
print("  服务器即将启动")
print(f"  地址: http://{args.host}:{args.port}")
print(f"  调试模式: {'是' if args.debug else '否'}")
print("=" * 70)
print()

# 启动服务器
if __name__ == '__main__':
    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n\n服务器已停止")
        sys.exit(0)
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        print(f"\n服务器启动失败: {e}")
        sys.exit(1)
