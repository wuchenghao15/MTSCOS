from flask import Blueprint, jsonify, current_app, request
"""ai_routes — AI引擎接口 Blueprint

功能: AI团队枢纽统计/AI员工列表/成长树Top10/集群节点状态
表: ai_employees / ai_employee_growth_tree / ai_cluster_nodes / ai_employee_skill_nodes
权限: 查询需登录
"""
from . import ai_bp
from ._governance_helpers import (
    _check_login, _query, _count, _ok, _fail, _arg_int,
)
import json
from app.middlewares.system_container import system_container


def _runtime_data():
    runtime = current_app.config.get('RUNTIME_DATA') or current_app.config.get('DB_RUNTIME') or {}
    if isinstance(runtime, dict):
        return runtime
    return {}


@ai_bp.route('/team_hub_stats', methods=['GET'])
@system_container()
def team_hub_stats():
    """AI 团队枢纽统计 (AI员工/在线/集群/技能)"""
    ok, u, err = _check_login()
    if not ok:
        return _fail(err[1], err[0])
    runtime = _runtime_data()
    if runtime:
        return _ok({
            'total_ai': len(runtime.get('ai_employees', [])),
            'active_ai': sum(1 for e in runtime.get('ai_employees', []) if str((e or {}).get('status') or '').lower() in ('active', 'online', 'running')),
            'clusters': len(runtime.get('eigenflux_experts', [])) or 1,
            'skills': len(runtime.get('system_parameters', {}).get('features', [])) or 0,
        })
    total_ai = _count('ai_employees')
    active_ai = _count('ai_employees', "status='active' AND is_enabled=1")
    clusters = _count('ai_cluster_nodes')
    skills = _count('ai_employee_skill_nodes')
    return _ok({
        'total_ai': total_ai,
        'active_ai': active_ai,
        'clusters': clusters,
        'skills': skills,
    })


@ai_bp.route('/team_list', methods=['GET'])
@system_container()
def team_list():
    """AI 员工列表 (支持 limit)"""
    ok, u, err = _check_login()
    if not ok:
        return _fail(err[1], err[0])
    limit = _arg_int('limit', 20, 1, 200)
    runtime = _runtime_data()
    if runtime and runtime.get('ai_employees'):
        employees = []
        for idx, emp in enumerate(runtime.get('ai_employees', [])[:limit]):
            capabilities = emp.get('capabilities') or []
            if isinstance(capabilities, str):
                capabilities = [capabilities]
            employees.append({
                'name': emp.get('employee_type') or emp.get('employee_id') or f'AI员工-{idx + 1}',
                'employee_name': emp.get('employee_type') or emp.get('employee_id') or f'AI员工-{idx + 1}',
                'employee_code': emp.get('employee_id'),
                'role': 'AI员工',
                'cluster': emp.get('assigned_cluster') or 'default',
                'level': 1,
                'skills': [str(s) for s in capabilities[:5]],
                'achievements': 0,
                'status': 'online' if str(emp.get('status') or '').lower() in ('active', 'online') else 'idle',
                'total_tasks': 0,
                'accuracy': 0,
            })
        return _ok({'employees': employees, 'count': len(employees)})
    rows = _query(
        "SELECT name, employee_code, description, capabilities, specialties, "
        "status, accuracy, total_tasks, successful_fixes, failed_fixes, "
        "is_enabled, priority, max_concurrent_tasks, skill_level AS level, "
        "knowledge_base_size, model_version, created_at, updated_at "
        "FROM ai_employees ORDER BY total_tasks DESC, skill_level DESC LIMIT ?", [limit])
    employees = []
    for r in rows:
        # 解析 capabilities/specialties 为 skills 数组
        skills = []
        try:
            cap = json.loads(r.get('capabilities') or '[]')
            if isinstance(cap, list):
                skills = [str(c) for c in cap[:5]]
        except Exception:
            pass
        if not skills:
            try:
                sp = json.loads(r.get('specialties') or '[]')
                if isinstance(sp, list):
                    skills = [str(s) for s in sp[:5]]
            except Exception:
                pass
        if not skills and r.get('specialties'):
            skills = [s.strip() for s in str(r.get('specialties')).split(',') if s.strip()][:5]
        # 状态映射: active→online, idle→idle, busy→training, offline→offline
        status_map = {'active': 'online', 'busy': 'training', 'idle': 'idle', 'offline': 'offline'}
        raw_status = (r.get('status') or 'idle').lower()
        employees.append({
            'name': r.get('name'),
            'employee_name': r.get('name'),
            'employee_code': r.get('employee_code'),
            'role': r.get('description', '')[:30] if r.get('description') else 'AI员工',
            'cluster': r.get('model_version', 'v1'),
            'level': r.get('level', 1),
            'skills': skills,
            'achievements': r.get('successful_fixes', 0),
            'status': status_map.get(raw_status, 'idle'),
            'total_tasks': r.get('total_tasks', 0),
            'accuracy': r.get('accuracy', 0),
        })
    return _ok({'employees': employees, 'count': len(employees)})


@ai_bp.route('/growth_tree', methods=['GET'])
@system_container()
def growth_tree():
    """AI 成长树 Top N (按 growth_exp 降序)"""
    ok, u, err = _check_login()
    if not ok:
        return _fail(err[1], err[0])
    limit = _arg_int('limit', 10, 1, 100)
    rows = _query(
        "SELECT employee_id, employee_name, growth_level, growth_exp, "
        "evaluation_score, last_evaluation, mentor_name, updated_at "
        "FROM ai_employee_growth_tree "
        "WHERE employee_name IS NOT NULL AND employee_name != '' "
        "ORDER BY growth_exp DESC, growth_level DESC LIMIT ?", [limit])
    growth = []
    for r in rows:
        level = r.get('growth_level', 1) or 1
        exp = r.get('growth_exp', 0) or 0
        # 下一级所需经验: 当前级 * 1000 的近似
        next_level_exp = max(level * 1000, exp + 100)
        growth.append({
            'name': r.get('employee_name'),
            'exp': exp,
            'level': level,
            'next_level_exp': next_level_exp,
            'evaluation_score': r.get('evaluation_score', 0),
            'mentor': r.get('mentor_name', ''),
        })
    return _ok({'growth': growth, 'count': len(growth)})


@ai_bp.route('/cluster_nodes_status', methods=['GET'])
@system_container()
def cluster_nodes_status():
    """AI 集群节点状态"""
    ok, u, err = _check_login()
    if not ok:
        return _fail(err[1], err[0])
    limit = _arg_int('limit', 50, 1, 200)
    runtime = _runtime_data()
    if runtime and runtime.get('eigenflux_ai'):
        nodes = []
        for idx, expert in enumerate(runtime.get('eigenflux_experts', [])[:limit]):
            nodes.append({
                'node_id': expert.get('employee_id') or f'eigenflux-{idx + 1}',
                'id': expert.get('employee_id') or f'eigenflux-{idx + 1}',
                'node_name': expert.get('employee_type') or f'EigenFlux专家-{idx + 1}',
                'node_type': 'EigenFlux',
                'status': 'online' if str(expert.get('status') or '').lower() in ('active', 'online') else 'idle',
                'load': 50,
                'last_heartbeat': expert.get('updated_at') or '',
                'health_score': 100,
                'eigenflux_flag': True,
            })
        if nodes:
            return _ok({'nodes': nodes, 'count': len(nodes)})
    rows = _query(
        "SELECT node_id, node_name, node_type, status, host, port, "
        "cpu_usage_pct, gpu_usage_pct, queue_depth, health_score, "
        "total_inferences, avg_latency_ms, last_heartbeat, eigenflux_flag "
        "FROM ai_cluster_nodes ORDER BY last_heartbeat DESC LIMIT ?", [limit])
    # 状态映射: ONLINE→online, OFFLINE→offline, BUSY→training, IDLE→idle
    status_map = {'ONLINE': 'online', 'OFFLINE': 'offline', 'BUSY': 'training', 'IDLE': 'idle'}
    nodes = []
    for r in rows:
        raw_status = (r.get('status') or 'OFFLINE').upper()
        load = max(
            int(r.get('cpu_usage_pct') or 0),
            int(r.get('gpu_usage_pct') or 0),
            min(100, int(r.get('queue_depth') or 0) * 10),
        )
        nodes.append({
            'node_id': r.get('node_id'),
            'id': r.get('node_id'),
            'node_name': r.get('node_name'),
            'node_type': r.get('node_type'),
            'status': status_map.get(raw_status, 'offline'),
            'load': load,
            'last_heartbeat': r.get('last_heartbeat', ''),
            'health_score': r.get('health_score', 0),
            'eigenflux_flag': bool(r.get('eigenflux_flag')),
        })
    return _ok({'nodes': nodes, 'count': len(nodes)})


# ============================================================
# AI 员工健康监控 (flow_employee_health_20261024)
# ============================================================

@ai_bp.route('/employee_health', methods=['GET'])
def employee_health_overview():
    """AI 员工健康总览 — 游客友好"""
    try:
        # 总基数
        total = _count('ai_employees')
        enabled = _count('ai_employees', 'is_enabled=1')
        active = _count('ai_employees', "status='active'")

        # 心跳健康分级
        # LIVE: last_heartbeat 在 1h 内
        # WEAK: 1h-24h
        # STALE: >24h 或空
        hb_rows = _query("""
            SELECT CASE
                WHEN IFNULL(last_heartbeat,'')='' THEN 'NO_HB'
                WHEN last_heartbeat >= datetime('now','localtime','-1 hour') THEN 'LIVE'
                WHEN last_heartbeat >= datetime('now','localtime','-24 hours') THEN 'WEAK'
                ELSE 'STALE'
            END as hb_bucket,
            COUNT(*) as n
            FROM ai_employees
            GROUP BY hb_bucket
        """)
        hb_map = {r["hb_bucket"]: r["n"] for r in hb_rows}

        # 任务活跃度
        # NEVER_USED: total_tasks=0
        # HIGH_SUCCESS: successful_fixes/total_tasks >= 0.7
        # LOW_SUCCESS: successful_fixes/total_tasks < 0.3 且 > 0
        # ALL_FAILED: total_tasks>0 且 successful_fixes=0
        task_rows = _query("""
            SELECT
                SUM(CASE WHEN total_tasks=0 THEN 1 ELSE 0 END) as never_used,
                SUM(CASE WHEN total_tasks>0 AND successful_fixes=0 THEN 1 ELSE 0 END) as all_failed,
                SUM(CASE WHEN total_tasks>0
                          AND CAST(successful_fixes AS REAL)/total_tasks<0.3
                          AND successful_fixes>0 THEN 1 ELSE 0 END) as low_success,
                SUM(CASE WHEN total_tasks>0
                          AND CAST(successful_fixes AS REAL)/total_tasks>=0.7
                          AND successful_fixes>0 THEN 1 ELSE 0 END) as high_success
            FROM ai_employees
        """)
        t = task_rows[0] if task_rows else {'never_used': 0, 'all_failed': 0, 'low_success': 0, 'high_success': 0}

        # 知识停滞
        stagnant_knowledge = _count(
            'ai_employees',
            "knowledge_base_size=0 OR last_training<datetime('now','localtime','-30 days')"
        )

        # 退休/退役
        retired = _count('ai_employees', "career_status='退休'")
        advancing = _count('ai_employees', "career_status='进阶中'")

        # 失败率异常员工 Top5（供直接跳转详情）
        failing_top = _query("""
            SELECT name, employee_code, total_tasks, successful_fixes, failed_fixes,
                   CAST(successful_fixes AS REAL)/total_tasks as success_rate
            FROM ai_employees
            WHERE total_tasks>0 AND CAST(successful_fixes AS REAL)/total_tasks<0.3
            ORDER BY failed_fixes DESC LIMIT 5
        """)
        failing_top_list = [
            {'name': r['name'], 'employee_code': r['employee_code'], 'total_tasks': r['total_tasks'],
             'successful_fixes': r['successful_fixes'], 'failed_fixes': r['failed_fixes'],
             'success_rate': round(r['success_rate'] or 0, 3)}
            for r in failing_top
        ]

        # 假死员工 Top5（心跳最久未更新）
        stale_top = _query("""
            SELECT name, employee_code, last_heartbeat, career_status, status
            FROM ai_employees
            WHERE IFNULL(last_heartbeat,'')=''
               OR last_heartbeat<datetime('now','localtime','-24 hours')
            ORDER BY IFNULL(last_heartbeat,'') ASC LIMIT 5
        """)
        stale_top_list = [
            {'name': r['name'], 'employee_code': r['employee_code'], 'last_heartbeat': r['last_heartbeat'] or '从未',
             'career_status': r['career_status'] or '在职', 'status': r['status']}
            for r in stale_top
        ]

        return _ok({
            'total': total,
            'enabled': enabled,
            'active': active,
            'heartbeat': {
                'LIVE': hb_map.get('LIVE', 0),
                'WEAK': hb_map.get('WEAK', 0),
                'STALE': hb_map.get('STALE', 0),
                'NO_HB': hb_map.get('NO_HB', 0),
            },
            'activity': {
                'never_used': t['never_used'],
                'all_failed': t['all_failed'],
                'low_success': t['low_success'],
                'high_success': t['high_success'],
            },
            'career': {
                'retired': retired,
                'advancing': advancing,
                'stagnant_knowledge': stagnant_knowledge,
            },
            'failing_top': failing_top_list,
            'stale_top': stale_top_list,
            'generated_at': _query("SELECT datetime('now','localtime') as now_ts")[0]['now_ts'],
        })
    except Exception as e:
        import traceback as _tb
        _tb.print_exc()
        return _fail(f'健康统计失败: {e}', 500)


@ai_bp.route('/employee_health_detail', methods=['GET'])
def employee_health_detail():
    """AI 员工健康详情列表 — 游客友好"""
    level = (request.args.get('level') or 'ALL').upper()
    limit = _arg_int('limit', 50, 1, 500)
    offset = _arg_int('offset', 0, 0, 5000)

    # 不同 level 的 WHERE 条件
    level_where_map = {
        'STALE':     "IFNULL(last_heartbeat,'')='' OR last_heartbeat<datetime('now','localtime','-24 hours')",
        'WEAK':      "last_heartbeat>=datetime('now','localtime','-24 hours') AND last_heartbeat<datetime('now','localtime','-1 hour')",
        'UNUSED':    "total_tasks=0",
        'FAILING':   "total_tasks>0 AND CAST(successful_fixes AS REAL)/total_tasks<0.3",
        'STAGNANT':  "knowledge_base_size=0 OR last_training<datetime('now','localtime','-30 days')",
        'ALL':       "1=1",
    }
    where = level_where_map.get(level, level_where_map['ALL'])
    try:
        total = _query(f"SELECT COUNT(*) as cnt FROM ai_employees WHERE {where}") or [{"cnt":0}][0]["cnt"]
        rows = _query(f"""
            SELECT name, employee_code, status, career_status,
                   last_heartbeat, total_tasks, successful_fixes, failed_fixes,
                   knowledge_base_size, last_training, title, group_tag
            FROM ai_employees
            WHERE {where}
            ORDER BY rowid DESC LIMIT ? OFFSET ?
        """, [limit, offset])
        employees = []
        for r in rows:
            st = (r['status'] or '').lower()
            if st in ('active', 'online', 'running'):
                hb = r['last_heartbeat'] or ''
                if not hb:
                    health = 'STALE'
                elif hb >= _query("SELECT datetime('now','localtime','-1 hour') as now_ts")[0]["now_ts"]:
                    health = 'LIVE'
                elif hb >= _query("SELECT datetime('now','localtime','-24 hours') as now_ts")[0]["now_ts"]:
                    health = 'WEAK'
                else:
                    health = 'STALE'
            else:
                health = 'STALE'
            employees.append({
                'name': r['name'], 'employee_code': r['employee_code'], 'status': r['status'],
                'career_status': r['career_status'], 'last_heartbeat': r['last_heartbeat'] or '从未',
                'total_tasks': r['total_tasks'] or 0, 'successful_fixes': r['successful_fixes'] or 0,
                'failed_fixes': r['failed_fixes'] or 0, 'knowledge_base_size': r['knowledge_base_size'] or 0,
                'last_training': r['last_training'] or '从未', 'title': r['title'] or '',
                'group_tag': r['group_tag'] or '', 'health': health,
            })
        return _ok({'level': level, 'total': total, 'count': len(employees),
                    'employees': employees, 'offset': offset, 'limit': limit})
    except Exception as e:
        return _fail(f'详情查询失败: {e}', 500)


bp = Blueprint('ai_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
@system_container()
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'ai','routes_implemented':1}})

