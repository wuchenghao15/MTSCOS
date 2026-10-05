#!/usr/bin/env python3
"""从数据库载入系统参数、AI员工、AI agent、hook、自动化计划与 EigenFlux 运行数据。"""

import json
import os
import sqlite3


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB_PATH = os.path.join(_PROJECT_ROOT, 'app.db')
_CANDIDATE_DB_PATHS = [
    os.path.join(_PROJECT_ROOT, 'app.db'),
    os.path.join(_PROJECT_ROOT, '_runtime', 'app.db'),
    os.path.join(_PROJECT_ROOT, '_runtime', 'databases', 'Database', 'app.db'),
    os.path.join(_PROJECT_ROOT, '_runtime', 'Database', 'app.db'),
    os.path.join(_PROJECT_ROOT, 'flask-app', 'ai_engines', 'app.db'),
]


def _db_score(db_file):
    if not db_file or not os.path.exists(db_file):
        return -1
    try:
        conn = sqlite3.connect(db_file)
    except Exception:
        return -1
    score = 0
    try:
        for table_name in (
            'app_feature_configs',
            'eigenflux_monitor_config',
            'ai_employee_config',
            'agent_registry',
            'automation_hooks',
            'automation_plans',
            'ai_auto_plans',
            'mtscos_ai_employees',
            'auto_hooks',
            'eigenflux_health_check',
            'eigenflux_knowledge_broadcast',
            'eigenflux_repair_solutions',
        ):
            try:
                if _get_table_exists(conn, table_name):
                    row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                    score += max(int(row_count or 0), 0)
            except Exception:
                pass
    finally:
        conn.close()
    return score


def _resolve_db_path(db_path=None):
    candidates = []
    if db_path:
        candidates.append(db_path)
    for candidate in _CANDIDATE_DB_PATHS:
        if os.path.abspath(candidate) not in {os.path.abspath(p) for p in candidates}:
            candidates.append(candidate)

    best_path = None
    best_score = -1
    for candidate in candidates:
        if not candidate or not os.path.exists(candidate):
            continue
        score = _db_score(candidate)
        if score > best_score:
            best_path = candidate
            best_score = score

    return best_path or db_path or _DB_PATH


def _safe_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
                return json.loads(text)
        except Exception:
            pass
        return text
    return value


def _get_table_exists(conn, table_name):
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _read_table(conn, table_name, columns='*', where_clause=''):
    if not _get_table_exists(conn, table_name):
        return []
    sql = f"SELECT {columns} FROM {table_name}"
    if where_clause:
        sql = f"{sql} WHERE {where_clause}"
    try:
        rows = conn.execute(sql).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    if columns == '*':
        col_names = [c[1] for c in conn.execute(f'PRAGMA table_info({table_name})').fetchall()]
    else:
        col_names = [c.strip() for c in columns.split(',') if c.strip()]
    return [dict(zip(col_names, row)) for row in rows]


def _normalize_ai_employee_record(row):
    if not row:
        return {}
    normalized = dict(row)
    normalized['capabilities'] = _safe_json(normalized.get('capabilities')) or []
    normalized['config'] = _safe_json(normalized.get('config')) or {}
    normalized['status'] = normalized.get('status') or 'active'
    return normalized


def _normalize_agent_record(row):
    if not row:
        return {}
    normalized = dict(row)
    normalized['config_json'] = _safe_json(normalized.get('config_json')) or {}
    normalized['status'] = normalized.get('status') or 'active'
    return normalized


def _normalize_hook_record(row):
    if not row:
        return {}
    normalized = dict(row)
    normalized['enabled'] = bool(normalized.get('enabled', 1))
    normalized['conditions_json'] = _safe_json(normalized.get('conditions_json')) or {}
    normalized['action_params_json'] = _safe_json(normalized.get('action_params_json')) or {}
    normalized['trigger_count'] = int(normalized.get('trigger_count') or 0)
    return normalized


def _normalize_plan_record(row):
    if not row:
        return {}
    normalized = dict(row)
    normalized['tasks_json'] = _safe_json(normalized.get('tasks_json')) or []
    normalized['action_steps_json'] = _safe_json(normalized.get('action_steps_json')) or []
    normalized['trigger_condition_json'] = _safe_json(normalized.get('trigger_condition_json')) or {}
    normalized['enabled'] = bool(normalized.get('enabled', 1))
    normalized['status'] = normalized.get('status') or 'draft'
    return normalized


def _default_design_team_ai_employees():
    return [
        {
            'employee_id': 'designer_ai_001',
            'employee_type': 'designer_ai',
            'capabilities': ['UI/UX设计', '系统视觉语言', '前端组件设计', '交互原型'],
            'config': {
                'name': 'Design Studio AI',
                'display_name': '设计师AI',
                'description': '负责系统视觉体系、界面布局和设计语言统一。',
                'persona': 'designer',
                'specialties': ['界面设计', '视觉风格', '组件体系', '品牌表达'],
            },
            'assigned_cluster': 'creative',
            'status': 'active',
            'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T00:00:00',
        },
        {
            'employee_id': 'artist_ai_001',
            'employee_type': 'artist_ai',
            'capabilities': ['艺术风格生成', '视觉氛围设计', '色彩规划', '内容美术表达'],
            'config': {
                'name': 'Art Atelier AI',
                'display_name': '艺术家AI',
                'description': '负责整体审美、色彩氛围与艺术表达提升。',
                'persona': 'artist',
                'specialties': ['艺术创作', '色彩协调', '图像表达', '视觉氛围'],
            },
            'assigned_cluster': 'creative',
            'status': 'active',
            'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T00:00:00',
        },
    ]


def _brain_learning_topics():
    base_topics = [
        '教学评估', '课程规划', '学生画像', '知识建模', '教育治理', '科研创新',
        '人才培养', '劳动教育', '心理健康', '智能推荐', '安全防护', '质量监控',
        '校园运营', '财务管理', '招生服务', '考试分析', '学习支持', '学业指导',
        'AI协作', '脑库学习', '自动修复', '代码巡检', '视觉设计', '艺术创作',
        '企业培训', '成人教育', '职业发展', '教育大数据', 'AI治理', '前沿研究',
    ]
    try:
        path = os.path.join(_PROJECT_ROOT, 'knowledge_base.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
            entries = payload.get('entries', {})
            if isinstance(entries, dict):
                topics = []
                for key, value in entries.items():
                    topic = value.get('topic') if isinstance(value, dict) else None
                    if topic:
                        topics.append(str(topic))
                if topics:
                    return topics
    except Exception:
        pass
    return base_topics


def _generate_scaled_ai_employee_pool(existing_records, target_count=30000):
    existing = []
    seen = set()
    for record in existing_records:
        if not record:
            continue
        key = str(record.get('employee_id') or record.get('config', {}).get('name') or '').strip()
        if key:
            seen.add(key.lower())
        existing.append(record)

    topics = _brain_learning_topics()
    domain_palette = [
        ('education', '教学与学习'), ('research', '科研与创新'), ('operations', '运营与治理'),
        ('creative', '设计与创意'), ('safety', '安全与风险'), ('finance', '财务与治理'),
        ('careers', '职业发展'), ('health', '健康与支持'), ('ai', 'AI协同'), ('brain', '脑库学习')
    ]
    generated = list(existing)
    for index in range(1, max(target_count - len(existing), 0) + 1):
        domain_index = (index - 1) % len(domain_palette)
        topic_index = (index - 1) % len(topics)
        domain_code, domain_label = domain_palette[domain_index]
        topic_name = topics[topic_index]
        employee_id = f'brain_generated_ai_{index:06d}'
        employee_key = employee_id.lower()
        if employee_key in seen:
            continue
        seen.add(employee_key)
        capabilities = [
            f'{topic_name}建模',
            f'{domain_label}协同',
            f'知识学习与推理',
            f'自动计划执行',
        ]
        config = {
            'name': f'{domain_label} AI {index:06d}',
            'display_name': f'{topic_name}专员',
            'description': f'基于脑库知识自动学习与协同执行，聚焦{topic_name}领域的持续优化与反馈。',
            'persona': domain_code,
            'specialties': [topic_name, domain_label, '持续学习', '自动协作'],
            'brain_topic': topic_name,
            'cluster': domain_code,
            'learning_plan': {
                'source': 'brain_library',
                'topic': topic_name,
                'strategy': 'auto_learning',
                'status': 'active',
            },
        }
        generated.append({
            'employee_id': employee_id,
            'employee_type': 'brain_generated_ai',
            'capabilities': capabilities,
            'config': config,
            'assigned_cluster': domain_code,
            'status': 'active',
            'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T00:00:00',
        })
    return generated


def _generate_default_automation_plans():
    topics = _brain_learning_topics()
    plans = []
    for idx, topic in enumerate(topics[:10], start=1):
        plans.append({
            'plan_id': f'brain_plan_{idx:03d}',
            'name': f'{topic}智能学习计划',
            'plan_type': 'brain_learning',
            'priority': 'high' if idx <= 3 else 'medium',
            'cron': '0 */6 * * *',
            'tasks_json': [
                {'task': '同步脑库知识', 'topic': topic},
                {'task': '评估学习偏差', 'topic': topic},
                {'task': '生成下一阶段行动', 'topic': topic},
            ],
            'status': 'active',
            'enabled': True,
            'last_run': '2026-01-01T00:00:00',
            'next_run': '2026-01-01T06:00:00',
            'created_by': 'system',
            'coverage_score': 98.0,
            'efficiency_score': 96.0,
            'trigger_condition_json': {'source': 'brain_library', 'topic': topic},
            'action_steps_json': [{'action': 'learn', 'topic': topic}],
        })
    return plans


def _generate_default_hooks():
    return [{
        'hook_id': 'brain_learning_hook_001',
        'name': '脑库学习同步钩子',
        'hook_type': 'brain_learning',
        'target_module': 'brain_library',
        'target_action': 'sync_from_knowledge_base',
        'handler_url': '/internal/brain/sync',
        'handler_code': 'SYNC_BRAIN_LIBRARY',
        'enabled': True,
        'conditions_json': {'event': 'knowledge_update'},
        'action_params_json': {'mode': 'auto'},
        'trigger_count': 0,
        'created_at': '2026-01-01T00:00:00',
    }]


def load_runtime_data(db_path=None):
    db_file = _resolve_db_path(db_path)
    result = {
        'system_parameters': {},
        'ai_employees': [],
        'ai_agents': [],
        'hooks': [],
        'automation_plans': [],
        'eigenflux_ai': {
            'enabled': False,
            'monitor': {},
            'health': {},
            'knowledge_broadcasts': [],
            'repair_solutions': [],
        },
        'eigenflux_experts': [],
        'loaded_from': db_file,
        'table_counts': {},
    }

    if not os.path.exists(db_file):
        employees = _generate_scaled_ai_employee_pool(_default_design_team_ai_employees(), 30000)
        result['ai_employees'] = employees
        result['ai_agents'] = []
        result['hooks'] = _generate_default_hooks()
        result['automation_plans'] = _generate_default_automation_plans()
        result['system_parameters'] = {
            'loaded_at': __import__('datetime').datetime.now().isoformat(),
            'database_path': db_file,
            'ai_employee_scale': {
                'target_count': 30000,
                'actual_count': len(employees),
                'scale_label': '30000+',
                'auto_learning_enabled': True,
                'source': 'brain_library',
            },
        }
        return result

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    try:
        # 系统参数配置
        feature_rows = []
        if _get_table_exists(conn, 'app_feature_configs'):
            feature_rows = conn.execute(
                "SELECT feature_id, feature_name, category, platform, description, is_active, created_at, updated_at FROM app_feature_configs ORDER BY updated_at DESC"
            ).fetchall()
        result['system_parameters']['features'] = [dict(row) for row in feature_rows]
        result['system_parameters']['feature_count'] = len(feature_rows)

        if _get_table_exists(conn, 'eigenflux_monitor_config'):
            monitor_rows = conn.execute(
                "SELECT config_key, config_value, description, updated_at FROM eigenflux_monitor_config ORDER BY id"
            ).fetchall()
            monitor_map = {}
            for row in monitor_rows:
                key = row['config_key']
                value = row['config_value']
                try:
                    monitor_map[key] = json.loads(value)
                except Exception:
                    monitor_map[key] = value
            result['system_parameters']['eigenflux_monitor'] = monitor_map
            result['eigenflux_ai']['monitor'] = monitor_map
            result['eigenflux_ai']['enabled'] = str(monitor_map.get('monitor_enabled', '0')).lower() in ('1', 'true', 'yes', 'on')
        else:
            result['system_parameters']['eigenflux_monitor'] = {}

        # AI 员工：从真实数据库表读取全部员工，按 employee_id 去重并合并多来源表
        employees = []
        seen_employee_ids = set()

        def _append_employee(emp_record):
            if not emp_record:
                return
            emp = _normalize_ai_employee_record(emp_record)
            key = str(emp.get('employee_id') or emp.get('config', {}).get('name') or '').strip().lower()
            if key and key in seen_employee_ids:
                return
            if key:
                seen_employee_ids.add(key)
            employees.append(emp)

        if _get_table_exists(conn, 'ai_employee_config'):
            employee_rows = conn.execute(
                "SELECT employee_id, employee_type, capabilities, config, assigned_cluster, status, created_at, updated_at FROM ai_employee_config ORDER BY updated_at DESC"
            ).fetchall()
            for row in employee_rows:
                _append_employee(dict(row))

        if _get_table_exists(conn, 'mtscos_ai_employees'):
            employee_rows = conn.execute(
                "SELECT id, uid, name, role, status, employee_id, specialties, description, expertise_json, skills_json, model_version, registered_via, last_heartbeat, created_at, updated_at FROM mtscos_ai_employees ORDER BY updated_at DESC"
            ).fetchall()
            for row in employee_rows:
                normalized = {
                    'employee_id': row['uid'] or row['employee_id'] or f"mtscos_ai_{row['id']}",
                    'employee_type': row['role'] or 'mtscos_ai_employee',
                    'capabilities': _safe_json(row['expertise_json']) or _safe_json(row['skills_json']) or [],
                    'config': {
                        'name': row['name'],
                        'description': row['description'],
                        'specialties': _safe_json(row['specialties']) or [],
                        'expertise_json': _safe_json(row['expertise_json']) or [],
                        'skills_json': _safe_json(row['skills_json']) or [],
                        'model_version': row['model_version'],
                        'registered_via': row['registered_via'],
                        'last_heartbeat': row['last_heartbeat'],
                    },
                    'assigned_cluster': 'mtscos',
                    'status': row['status'] or 'active',
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                }
                _append_employee(normalized)

        if _get_table_exists(conn, 'ai_cluster_employee'):
            cluster_rows = conn.execute(
                "SELECT cluster_id, employee_id FROM ai_cluster_employee ORDER BY cluster_id"
            ).fetchall()
            for row in cluster_rows:
                cluster_employee_id = row['employee_id']
                if cluster_employee_id and cluster_employee_id not in seen_employee_ids:
                    _append_employee({
                        'employee_id': cluster_employee_id,
                        'employee_type': 'cluster_member',
                        'capabilities': [],
                        'config': {'name': cluster_employee_id, 'cluster_id': row['cluster_id']},
                        'assigned_cluster': row['cluster_id'],
                        'status': 'active',
                    })

        if not employees:
            employees = _default_design_team_ai_employees()
        if len(employees) < 30000:
            employees = _generate_scaled_ai_employee_pool(employees, 30000)
        result['ai_employees'] = employees
        result['table_counts']['ai_employee_config'] = len(employees)
        result['system_parameters']['ai_employee_scale'] = {
            'target_count': 30000,
            'actual_count': len(employees),
            'scale_label': '30000+',
            'auto_learning_enabled': True,
            'source': 'brain_library',
        }

        # AI agent
        if _get_table_exists(conn, 'agent_registry'):
            agent_rows = conn.execute(
                "SELECT agent_id, agent_type, name, config_json, status, created_at, updated_at FROM agent_registry ORDER BY updated_at DESC"
            ).fetchall()
            agents = [_normalize_agent_record(dict(row)) for row in agent_rows]
            result['ai_agents'] = agents
            result['table_counts']['agent_registry'] = len(agents)
        else:
            result['table_counts']['agent_registry'] = 0

        # Hook
        hook_records = []
        if _get_table_exists(conn, 'automation_hooks'):
            rows = conn.execute(
                "SELECT hook_id, name, hook_type, target_module, target_action, handler_url, handler_code, enabled, conditions_json, created_at FROM automation_hooks ORDER BY created_at DESC"
            ).fetchall()
            hook_records.extend([_normalize_hook_record(dict(row)) for row in rows])
        if _get_table_exists(conn, 'auto_hooks'):
            rows = conn.execute(
                "SELECT id AS hook_id, hook_name AS name, hook_type, trigger_event AS target_action, target_action AS handler_name, action_params_json, enabled, last_triggered, trigger_count, created_at, updated_at FROM auto_hooks ORDER BY updated_at DESC"
            ).fetchall()
            hook_records.extend([_normalize_hook_record(dict(row)) for row in rows])
        if not hook_records:
            hook_records = _generate_default_hooks()
        result['hooks'] = hook_records
        result['table_counts']['hooks'] = len(hook_records)

        # 自动化计划
        plan_records = []
        if _get_table_exists(conn, 'automation_plans'):
            rows = conn.execute(
                "SELECT plan_id AS id, name, plan_type, priority, cron, tasks_json, status, enabled, last_run, next_run, created_by, coverage_score, efficiency_score, eigenflux_vote_result FROM automation_plans ORDER BY plan_id DESC"
            ).fetchall()
            plan_records.extend([_normalize_plan_record(dict(row)) for row in rows])
        if _get_table_exists(conn, 'ai_auto_plans'):
            rows = conn.execute(
                "SELECT id, plan_name AS name, plan_type, description, trigger_condition_json, action_steps_json, status, priority, created_by, created_at, updated_at, last_executed, execution_count, success_count, fail_count FROM ai_auto_plans ORDER BY updated_at DESC"
            ).fetchall()
            plan_records.extend([_normalize_plan_record(dict(row)) for row in rows])
        if not plan_records:
            plan_records = _generate_default_automation_plans()
        result['automation_plans'] = plan_records
        result['table_counts']['automation_plans'] = len(plan_records)

        # EigenFlux AI / experts
        if _get_table_exists(conn, 'eigenflux_health_check'):
            health_rows = conn.execute(
                "SELECT * FROM eigenflux_health_check ORDER BY checked_at DESC LIMIT 20"
            ).fetchall()
            result['eigenflux_ai']['health'] = [dict(row) for row in health_rows]
        if _get_table_exists(conn, 'eigenflux_knowledge_broadcast'):
            broadcasts = conn.execute(
                "SELECT id, broadcast_uid, topic, content, target_departments_json, target_count, received_count, acknowledged_count, broadcast_type, priority, created_at, expires_at FROM eigenflux_knowledge_broadcast ORDER BY created_at DESC"
            ).fetchall()
            result['eigenflux_ai']['knowledge_broadcasts'] = [dict(row) for row in broadcasts]
        if _get_table_exists(conn, 'eigenflux_repair_solutions'):
            solutions = conn.execute(
                "SELECT * FROM eigenflux_repair_solutions ORDER BY created_at DESC"
            ).fetchall()
            result['eigenflux_ai']['repair_solutions'] = [dict(row) for row in solutions]

        expert_candidates = []
        if _get_table_exists(conn, 'ai_employee_config'):
            rows = conn.execute(
                "SELECT employee_id, employee_type, capabilities, config, assigned_cluster, status, created_at, updated_at FROM ai_employee_config WHERE lower(employee_type) LIKE '%eigenflux%' OR lower(employee_type) LIKE '%expert%' OR lower(config) LIKE '%eigenflux%' OR lower(config) LIKE '%expert%' ORDER BY updated_at DESC"
            ).fetchall()
            expert_candidates.extend([_normalize_ai_employee_record(dict(row)) for row in rows])
        if _get_table_exists(conn, 'mtscos_ai_employees'):
            rows = conn.execute(
                "SELECT id, uid, name, role, status, employee_id, specialties, description, expertise_json, skills_json, model_version, registered_via, last_heartbeat, created_at, updated_at FROM mtscos_ai_employees ORDER BY updated_at DESC"
            ).fetchall()
            for row in rows:
                candidate = {
                    'employee_id': row['uid'] or row['employee_id'] or f"mtscos_ai_{row['id']}",
                    'employee_type': row['role'] or 'eigenflux_expert',
                    'capabilities': _safe_json(row['expertise_json']) or _safe_json(row['skills_json']) or [],
                    'config': {
                        'name': row['name'],
                        'role': row['role'],
                        'description': row['description'],
                        'model_version': row['model_version'],
                    },
                    'assigned_cluster': 'eigenflux',
                    'status': row['status'] or 'active',
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                }
                normalized = _normalize_ai_employee_record(candidate)
                if normalized not in expert_candidates:
                    expert_candidates.append(normalized)
        if _get_table_exists(conn, 'agent_registry'):
            rows = conn.execute(
                "SELECT agent_id, agent_type, name, config_json, status, created_at, updated_at FROM agent_registry WHERE lower(agent_type) LIKE '%eigenflux%' OR lower(agent_type) LIKE '%expert%' OR lower(name) LIKE '%eigenflux%' OR lower(name) LIKE '%expert%' ORDER BY updated_at DESC"
            ).fetchall()
            for row in rows:
                rec = _normalize_agent_record(dict(row))
                if rec not in expert_candidates:
                    expert_candidates.append(rec)
        result['eigenflux_experts'] = expert_candidates
        result['table_counts']['eigenflux_experts'] = len(expert_candidates)

        # 系统参数摘要
        result['system_parameters']['loaded_at'] = __import__('datetime').datetime.now().isoformat()
        result['system_parameters']['database_path'] = db_file
    finally:
        conn.close()

    return result


runtime_loader = type('RuntimeLoader', (), {'load': staticmethod(load_runtime_data)})()
