#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Security Workforce API（安全团队 AI 员工 + AI Agent 注册与管理）
- 启动时做幂等插入：6 个安全/防火墙类 AI 员工 + 4 个 AI Agent
- 所有写操作仅 super_admin；读操作管理员即可
"""
import os, sys, json, time, uuid, sqlite3, hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify, session

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)

AUTH_DB = os.path.join(PROJECT_ROOT, 'split_databases', 'auth.db')
AI_DB = os.path.join(PROJECT_ROOT, 'split_databases', 'ai.db')

ai_security_workforce_api = Blueprint('ai_security_workforce_api', __name__, url_prefix='/api/ai_security/workforce')


def _conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def _current_user():
    if not session.get('username'):
        return None
    uid = session.get('user_id')
    user = {'id': uid, 'username': session.get('username'), 'role': session.get('role'), 'is_admin': False, 'is_super_admin': False}
    try:
        if uid and os.path.exists(AUTH_DB):
            with _conn(AUTH_DB) as c:
                row = c.execute("SELECT super_admin_approved, role FROM users WHERE id=? LIMIT 1", (uid,)).fetchone()
                if row:
                    if row['super_admin_approved']:
                        user['is_super_admin'] = True
                        user['is_admin'] = True
                    role = (row['role'] or '').lower()
                    if role in {'admin', 'super_admin', 'school_admin', 'institution_admin', 'teacher_admin', 'sysadmin'}:
                        user['is_admin'] = True
                        if role == 'super_admin':
                            user['is_super_admin'] = True
    except Exception:
        pass
    if str(session.get('role') or '').lower() in {'admin', 'super_admin'}:
        user['is_admin'] = True
    if session.get('super_admin_approved') is True:
        user['is_super_admin'] = True
    return user


def _auth_required(need_super=False):
    def decorator(fn):
        import functools
        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            u = _current_user()
            if not u:
                return jsonify({'success': False, 'message': '需要登录'}), 401
            if not u['is_admin']:
                return jsonify({'success': False, 'message': '需要管理员权限'}), 403
            if need_super and not u['is_super_admin']:
                return jsonify({'success': False, 'message': '需要超级管理员权限'}), 403
            return fn(*args, **kwargs)
        return wrap
    return decorator


# ===================== 种子数据 =====================

DEFAULT_SECURITY_EMPLOYEES = [
    {
        'employee_id': 'ai_fw_waf_engineer_01',
        'name': 'AI防火墙-WAF策略工程师',
        'title': 'WAF规则工程师',
        'description': '负责 AI 防火墙规则撰写、优化与误报/漏报闭环，每日复盘 security_events_log 并自动更新规则优先级与模式匹配正则。',
        'category': 'security_waf',
        'employee_type': 'ai_firewall_waf',
        'capabilities': json.dumps(['waf_rule_design','payload_analysis','false_positive_tuning','regex_engine','threat_intel_mapping'], ensure_ascii=False),
        'level': 10,
        'knowledge_domain': '网络安全,WAF,SQL注入,XSS,SSRF,路径遍历,命令注入,恶意爬虫',
        'personality_type': 'analyst',
        'status': 'active',
        'is_enabled': 1,
        'performance_score': 97.5,
        'efficiency': 95,
        'workload': 40,
    },
    {
        'employee_id': 'ai_fw_security_auditor_01',
        'name': 'AI安全审计师-合规与漏洞',
        'title': '安全审计师',
        'description': '审计系统配置、CI/CD流水线、依赖项、Dockerfile与权限矩阵，每周输出安全审计报告与漏洞修复建议，并与 Dependabot 联动。',
        'category': 'security_audit',
        'employee_type': 'ai_security_auditor',
        'capabilities': json.dumps(['code_audit','config_audit','dependency_scan','cve_mapping','compliance_check','secrets_detection'], ensure_ascii=False),
        'level': 10,
        'knowledge_domain': 'CVE,GHSA,PYSEC,NIST SP 800-63,等级保护2.0,PCI DSS,ISO 27001',
        'personality_type': 'auditor',
        'status': 'active',
        'is_enabled': 1,
        'performance_score': 96.8,
        'efficiency': 94,
        'workload': 35,
    },
    {
        'employee_id': 'ai_fw_threat_intel_01',
        'name': 'AI威胁情报采集员',
        'title': '威胁情报分析员',
        'description': '订阅 CVE/GHSA/CISA/CNVD 公告，自动维护 ip_blacklist / ua_blacklist 与 RATE_PATH_001 规则阈值，每日生成威胁情报简报。',
        'category': 'security_intel',
        'employee_type': 'ai_threat_intelligence',
        'capabilities': json.dumps(['cve_tracking','ioc_collection','ip_blacklist','ua_blacklist','feed_parsing','campaign_correlation'], ensure_ascii=False),
        'level': 9,
        'knowledge_domain': 'CVE,GHSA,OSINT,IOC,TLP,MITRE ATT&CK,STIX/TAXII',
        'personality_type': 'hunter',
        'status': 'active',
        'is_enabled': 1,
        'performance_score': 95.1,
        'efficiency': 92,
        'workload': 45,
    },
    {
        'employee_id': 'ai_fw_incident_responder_01',
        'name': 'AI安全事件响应员',
        'title': '应急响应工程师',
        'description': '安全事件告警触发后，自动按预案执行：封禁 IP/UA、调整速率、联动 AI 防火墙动态规则，并生成 5W 分析报告。',
        'category': 'security_ir',
        'employee_type': 'ai_incident_response',
        'capabilities': json.dumps(['playbook_execution','ip_block','ua_block','rule_tuning','forensics','reporting'], ensure_ascii=False),
        'level': 10,
        'knowledge_domain': 'NIST SP 800-61 事件响应,MITRE ATT&CK,取证分析,日志关联,封控策略',
        'personality_type': 'responder',
        'status': 'active',
        'is_enabled': 1,
        'performance_score': 98.2,
        'efficiency': 97,
        'workload': 50,
    },
    {
        'employee_id': 'ai_fw_vuln_scanner_01',
        'name': 'AI漏洞扫描与修复建议师',
        'title': '漏洞扫描工程师',
        'description': '周期扫描后端/前端代码、依赖、Docker 镜像与主机端口，把漏洞与 ai_security_auditor 输出合并，自动生成修复补丁与回归测试脚本。',
        'category': 'security_vuln',
        'employee_type': 'ai_vulnerability_scanner',
        'capabilities': json.dumps(['sast_scan','dast_scan','container_scan','patch_generation','regression_script','exploit_check'], ensure_ascii=False),
        'level': 9,
        'knowledge_domain': 'SAST/DAST,OWASP Top 10,CWE/SANS 25,容器安全,补丁开发',
        'personality_type': 'engineer',
        'status': 'active',
        'is_enabled': 1,
        'performance_score': 94.7,
        'efficiency': 91,
        'workload': 55,
    },
    {
        'employee_id': 'ai_fw_honeypot_analyst_01',
        'name': 'AI蜜罐与威胁猎手',
        'title': '威胁狩猎分析师',
        'description': '维护应用层蜜罐接口与诱饵路径，记录扫描/爆破/漏洞利用样本，实时投喂防火墙黑名单，支撑 WAF 新型攻击 0day 防护。',
        'category': 'security_hunt',
        'employee_type': 'ai_honeypot_threat_hunter',
        'capabilities': json.dumps(['honeypot_setup','threat_hunting','sample_collection','0day_pattern','ioc_generation','deception'], ensure_ascii=False),
        'level': 10,
        'knowledge_domain': 'MITRE PRE-ATT&CK,APT 技战术,0day 利用链,蜜罐架构,诱饵资产,反侦查',
        'personality_type': 'hunter',
        'status': 'active',
        'is_enabled': 1,
        'performance_score': 95.9,
        'efficiency': 93,
        'workload': 48,
    },
]

DEFAULT_SECURITY_AGENTS = [
    {
        'agent_code': 'WAF_AGENT_01',
        'name': 'MTSCOS WAF Agent',
        'agent_type': 'waf_orchestrator',
        'description': '编排 AI 防火墙 before_request 流程：模式匹配 + 行为评分 + 动态阈值，输出拦截/放行/仅日志动作。',
        'capabilities': json.dumps(['request_inspection','behavioral_scoring','dynamic_threshold','rule_orchestration','block_action'], ensure_ascii=False),
        'config_json': json.dumps({'mode': 'hybrid', 'scoring_weight': 0.6, 'threshold_block': 85}, ensure_ascii=False),
    },
    {
        'agent_code': 'SIEM_AGENT_01',
        'name': 'MTSCOS SIEM Agent',
        'agent_type': 'siem_correlation',
        'description': '读取 security_events_log，按时间/IP/UA/用户做多源关联，自动生成事件、告警与工单，并推送给 incident responder。',
        'capabilities': json.dumps(['event_correlation','alerts','rule_engine','ticketing','anomaly_detection'], ensure_ascii=False),
        'config_json': json.dumps({'correlation_window_sec': 900, 'anomaly_sigma': 3.5}, ensure_ascii=False),
    },
    {
        'agent_code': 'IR_AGENT_01',
        'name': 'MTSCOS Incident Response Agent',
        'agent_type': 'incident_response',
        'description': '接收 SIEM 告警后按 Playbook 自动执行封控（封禁 IP/UA / 调速率 / 强制下线）并生成 5W 报告。',
        'capabilities': json.dumps(['playbook_run','ip_ban','ua_ban','rate_adjust','session_kill','five_w_report'], ensure_ascii=False),
        'config_json': json.dumps({'ban_duration_sec': 3600, 'evidence': 'security_events_log'}, ensure_ascii=False),
    },
    {
        'agent_code': 'OSINT_AGENT_01',
        'name': 'MTSCOS OSINT & Threat Intel Agent',
        'agent_type': 'osint_threat_intel',
        'description': '订阅开源情报，汇总 IOC、CVE、攻击团伙情报，每日更新 IP/UA 黑名单并维护 WAF 规则阈值。',
        'capabilities': json.dumps(['cve_monitor','ioc_sync','feed_parsing','blacklist_sync','campaign_mapping'], ensure_ascii=False),
        'config_json': json.dumps({'sources': ['GHSA','CVE','CISA','CNVD','OSV']}, ensure_ascii=False),
    },
]


def _seed_security_workforce():
    """幂等插入员工表 / agent_registry / ai_agents，避免重复"""
    if not os.path.exists(AI_DB):
        return 0, 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ts = now
    inserted_emps = 0
    inserted_agents = 0
    try:
        with _conn(AI_DB) as conn:
            emp_cols = ['employee_id','name','title','description','category','capabilities',
                        'efficiency','workload','created_at','updated_at','status',
                        'thinking_focus','generation_source','template_key','employee_type',
                        'level','knowledge_domain','personality_type',
                        'total_tasks','successful_tasks','failed_tasks','performance_score','is_enabled']
            for emp in DEFAULT_SECURITY_EMPLOYEES:
                exists = conn.execute(
                    "SELECT employee_id FROM ai_employees WHERE employee_id=?", (emp['employee_id'],)
                ).fetchone()
                if not exists:
                    emp_vals = [
                        emp['employee_id'], emp['name'], emp['title'], emp['description'], emp['category'], emp['capabilities'],
                        emp['efficiency'], emp['workload'], ts, ts, emp['status'],
                        '防火墙与安全团队_初始化', 'security_seed', emp['employee_type'], emp['employee_type'],
                        emp['level'], emp['knowledge_domain'], emp['personality_type'],
                        0, 0, 0, emp['performance_score'], emp['is_enabled']
                    ]
                    conn.execute(
                        f"INSERT INTO ai_employees({','.join(emp_cols)}) VALUES({','.join(['?']*len(emp_cols))})",
                        emp_vals
                    )
                    inserted_emps += 1
            for ag in DEFAULT_SECURITY_AGENTS:
                exists_ag = conn.execute(
                    "SELECT id FROM ai_agents WHERE agent_type=? AND name=?",
                    (ag['agent_type'], ag['name'])
                ).fetchone()
                ag_id = None
                if not exists_ag:
                    conn.execute('''
                        INSERT INTO ai_agents(name,agent_type,description,capabilities,status,is_enabled,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?)
                    ''', (ag['name'], ag['agent_type'], ag['description'], ag['capabilities'], 'running', 1, ts, ts))
                    ag_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                    inserted_agents += 1
                else:
                    ag_id = exists_ag['id']
                reg_exists = conn.execute(
                    "SELECT agent_id FROM agent_registry WHERE agent_id=?", (ag['agent_code'],)
                ).fetchone()
                if not reg_exists:
                    conn.execute('''
                        INSERT INTO agent_registry(agent_id,agent_type,name,config_json,status,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?)
                    ''', (ag['agent_code'], ag['agent_type'], ag['name'], ag['config_json'], 'active', ts, ts))
            for emp in DEFAULT_SECURITY_EMPLOYEES:
                cfg = conn.execute(
                    "SELECT employee_id FROM ai_employee_config WHERE employee_id=?", (emp['employee_id'],)
                ).fetchone()
                if not cfg:
                    conn.execute('''
                        INSERT INTO ai_employee_config(employee_id,employee_type,capabilities,config,assigned_cluster,status,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?)
                    ''', (emp['employee_id'], emp['employee_type'], emp['capabilities'],
                          json.dumps({'team': 'security', 'firewall_bind': True}, ensure_ascii=False),
                          'ai_security_cluster', emp['status'], ts, ts))
            conn.commit()
    except Exception as e:
        print(f"[security_workforce] seed fail: {e}")
    return inserted_emps, inserted_agents


# ================= 启动钩子：模块被 import 时自动 seed 一次（幂等） =================
try:
    _seed_security_workforce()
except Exception:
    pass


# ================== 员工 CRUD ==================

@ai_security_workforce_api.route('/seed', methods=['POST'])
@_auth_required(need_super=True)
def seed_now():
    ie, ia = _seed_security_workforce()
    return jsonify({'success': True, 'message': '已执行种子幂等插入', 'inserted_employees': ie, 'inserted_agents': ia})


@ai_security_workforce_api.route('/employees', methods=['GET'])
@_auth_required(need_super=False)
def list_employees():
    keyword = (request.args.get('keyword') or '').strip()
    enabled = request.args.get('enabled')
    category = (request.args.get('category') or '').strip()
    limit = max(1, min(500, int(request.args.get('limit', 100) or 100)))
    q = "SELECT * FROM ai_employees WHERE 1=1"
    args = []
    if keyword:
        q += " AND (name LIKE ? OR title LIKE ? OR employee_id LIKE ? OR category LIKE ? OR description LIKE ?)"
        args.extend([f'%{keyword}%'] * 5)
    if category:
        q += " AND category=?"
        args.append(category)
    if enabled in ('1', '0'):
        q += " AND is_enabled=?"
        args.append(int(enabled))
    q += " ORDER BY performance_score DESC, level DESC LIMIT ?"
    args.append(limit)
    try:
        with _conn(AI_DB) as c:
            rows = [dict(r) for r in c.execute(q, args).fetchall()]
        return jsonify({'success': True, 'count': len(rows), 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/employees/<employee_id>/toggle', methods=['POST'])
@_auth_required(need_super=True)
def toggle_employee(employee_id):
    data = request.get_json(silent=True) or {}
    status = (data.get('enabled') or request.args.get('enabled') or '').strip()
    if status not in ('1', '0'):
        return jsonify({'success': False, 'message': 'enabled 必须是 1 或 0'}), 400
    try:
        with _conn(AI_DB) as c:
            c.execute("UPDATE ai_employees SET is_enabled=?, updated_at=? WHERE employee_id=?",
                      (int(status), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), employee_id))
            if c.rowcount == 0:
                return jsonify({'success': False, 'message': '员工不存在'}), 404
            c.commit()
        return jsonify({'success': True, 'message': '已更新员工启用状态', 'employee_id': employee_id, 'enabled': int(status)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/employees', methods=['POST'])
@_auth_required(need_super=True)
def create_employee():
    data = request.get_json(silent=True) or {}
    for f in ('employee_id', 'name', 'title'):
        if f not in data or not str(data.get(f) or '').strip():
            return jsonify({'success': False, 'message': f'缺少字段 {f}'}), 400
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cols = ['employee_id','name','title','description','category','capabilities','efficiency','workload',
            'status','created_at','updated_at','is_enabled','employee_type','level','knowledge_domain',
            'personality_type','total_tasks','successful_tasks','failed_tasks','performance_score','generation_source']
    vals = [
        data['employee_id'], data['name'], data['title'],
        data.get('description', ''), data.get('category', 'custom'),
        json.dumps(data.get('capabilities', []), ensure_ascii=False),
        int(data.get('efficiency', 80) or 80),
        int(data.get('workload', 0) or 0),
        data.get('status', 'active'), ts, ts,
        int(data.get('is_enabled', 1) or 1),
        data.get('employee_type', 'general'),
        int(data.get('level', 5) or 5),
        data.get('knowledge_domain', ''),
        data.get('personality_type', 'generalist'),
        0, 0, 0,
        float(data.get('performance_score', 80.0) or 80.0),
        'api_created',
    ]
    try:
        with _conn(AI_DB) as c:
            c.execute(f"INSERT INTO ai_employees({','.join(cols)}) VALUES({','.join(['?']*len(cols))})", vals)
            c.execute('''
                INSERT INTO ai_employee_config(employee_id,employee_type,capabilities,config,assigned_cluster,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
            ''', (data['employee_id'], data.get('employee_type', 'general'),
                  json.dumps(data.get('capabilities', []), ensure_ascii=False),
                  json.dumps(data.get('config', {}), ensure_ascii=False),
                  data.get('assigned_cluster', ''), data.get('status', 'active'), ts, ts))
            c.commit()
        return jsonify({'success': True, 'message': '已创建 AI 员工', 'employee_id': data['employee_id']}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/employees/<employee_id>', methods=['DELETE'])
@_auth_required(need_super=True)
def delete_employee(employee_id):
    # 仅允许删除 category 非系统生成的员工（防误删种子员工）；这里宽松：允许删除，但要确认不存在关联任务历史。
    try:
        with _conn(AI_DB) as c:
            c.execute("DELETE FROM ai_employee_config WHERE employee_id=?", (employee_id,))
            c.execute("DELETE FROM ai_employees WHERE employee_id=?", (employee_id,))
            if c.rowcount == 0:
                return jsonify({'success': False, 'message': '员工不存在'}), 404
            c.commit()
        return jsonify({'success': True, 'message': '已删除 AI 员工'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ================== Agent CRUD ==================

@ai_security_workforce_api.route('/agents', methods=['GET'])
@_auth_required(need_super=False)
def list_agents():
    keyword = (request.args.get('keyword') or '').strip()
    enabled = request.args.get('enabled')
    q = "SELECT * FROM ai_agents WHERE 1=1"
    args = []
    if keyword:
        q += " AND (name LIKE ? OR agent_type LIKE ? OR description LIKE ? OR capabilities LIKE ?)"
        args.extend([f'%{keyword}%'] * 4)
    if enabled in ('1', '0'):
        q += " AND is_enabled=?"
        args.append(int(enabled))
    q += " ORDER BY id DESC"
    try:
        with _conn(AI_DB) as c:
            rows = [dict(r) for r in c.execute(q, args).fetchall()]
        return jsonify({'success': True, 'count': len(rows), 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/registry', methods=['GET'])
@_auth_required(need_super=False)
def list_registry():
    try:
        with _conn(AI_DB) as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM agent_registry ORDER BY agent_id").fetchall()]
        return jsonify({'success': True, 'count': len(rows), 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/agents', methods=['POST'])
@_auth_required(need_super=True)
def create_agent():
    data = request.get_json(silent=True) or {}
    for f in ('name', 'agent_type'):
        if f not in data or not str(data.get(f) or '').strip():
            return jsonify({'success': False, 'message': f'缺少字段 {f}'}), 400
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with _conn(AI_DB) as c:
            c.execute('''
                INSERT INTO ai_agents(name,agent_type,description,capabilities,status,is_enabled,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
            ''', (
                data['name'], data['agent_type'], data.get('description', ''),
                json.dumps(data.get('capabilities', []), ensure_ascii=False),
                data.get('status', 'running'), int(data.get('is_enabled', 1) or 1),
                ts, ts
            ))
            aid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            code = data.get('agent_code') or ('AG_' + hashlib.md5((data['name'] + ts).encode()).hexdigest()[:10].upper())
            c.execute('''
                INSERT INTO agent_registry(agent_id,agent_type,name,config_json,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)
            ''', (code, data['agent_type'], data['name'],
                  json.dumps(data.get('config', {}), ensure_ascii=False),
                  data.get('status', 'active'), ts, ts))
            c.commit()
        return jsonify({'success': True, 'message': '已创建 AI Agent', 'id': aid, 'agent_code': code}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/agents/<int:agent_id>/toggle', methods=['POST'])
@_auth_required(need_super=True)
def toggle_agent(agent_id):
    data = request.get_json(silent=True) or {}
    status = (data.get('enabled') or request.args.get('enabled') or '').strip()
    if status not in ('1', '0'):
        return jsonify({'success': False, 'message': 'enabled 必须是 1 或 0'}), 400
    try:
        with _conn(AI_DB) as c:
            c.execute("UPDATE ai_agents SET is_enabled=?, updated_at=? WHERE id=?",
                      (int(status), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), agent_id))
            if c.rowcount == 0:
                return jsonify({'success': False, 'message': 'Agent 不存在'}), 404
            c.commit()
        return jsonify({'success': True, 'message': '已更新 Agent 启用状态'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/agents/<int:agent_id>', methods=['DELETE'])
@_auth_required(need_super=True)
def delete_agent(agent_id):
    try:
        with _conn(AI_DB) as c:
            c.execute("DELETE FROM ai_agents WHERE id=?", (agent_id,))
            if c.rowcount == 0:
                return jsonify({'success': False, 'message': 'Agent 不存在'}), 404
            c.commit()
        return jsonify({'success': True, 'message': '已删除 AI Agent'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@ai_security_workforce_api.route('/summary', methods=['GET'])
@_auth_required(need_super=False)
def summary():
    try:
        with _conn(AI_DB) as c:
            total_emp = c.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
            enabled_emp = c.execute("SELECT COUNT(*) FROM ai_employees WHERE is_enabled=1").fetchone()[0]
            sec_emp = c.execute(
                "SELECT COUNT(*) FROM ai_employees WHERE category LIKE 'security_%'"
            ).fetchone()[0]
            total_ag = c.execute("SELECT COUNT(*) FROM ai_agents").fetchone()[0]
            enabled_ag = c.execute("SELECT COUNT(*) FROM ai_agents WHERE is_enabled=1").fetchone()[0]
            reg = c.execute("SELECT COUNT(*) FROM agent_registry").fetchone()[0]
        return jsonify({
            'success': True,
            'data': {
                'total_employees': total_emp,
                'enabled_employees': enabled_emp,
                'security_team_employees': sec_emp,
                'total_agents': total_ag,
                'enabled_agents': enabled_ag,
                'registry_entries': reg,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
