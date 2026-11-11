#!/usr/bin/env python3
"""
§四.3 AI 员工角色体系 API
========================
角色/员工/daemon 三层查询 + 健康度
"""
import sqlite3, os, json
from flask import Blueprint, jsonify
from app.middlewares.system_container import system_container

ai_roles_api = Blueprint('ai_roles_api', __name__)

def _db():
    for p in [os.path.expanduser("~/mtscos/_runtime/databases/Database/app.db"),
              os.path.join(os.path.dirname(__file__), "../..", "_runtime", "databases", "Database", "app.db")]:
        if os.path.exists(p):
            conn = sqlite3.connect(p); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL")
            return conn

@ai_roles_api.route('/api/ai/employee/roles', methods=['GET'])
def list_roles():
    conn = _db()
    rows = conn.execute("""
        SELECT r.role_code, r.role_name, r.mission, r.core_skills, r.matrix_id, r.priority,
               r.employee_count, r.status,
               m.matrix_name
        FROM mt_ai_employee_roles r
        LEFT JOIN mt_ai_matrix m ON r.matrix_id = m.matrix_id
        WHERE r.status='active'
        ORDER BY r.priority DESC
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['core_skills'] = json.loads(d['core_skills']) if d.get('core_skills') else []
        # 带成员名
        emps = conn.execute("""
            SELECT e.name, b.is_primary FROM mt_ai_employee_role_binding b
            JOIN ai_employees e ON b.employee_pk = e.id
            WHERE b.role_code = ? ORDER BY b.is_primary DESC
        """, (d['role_code'],)).fetchall()
        d['members'] = [dict(e) for e in emps]
        result.append(d)
    conn.close()
    return jsonify({"success": True, "data": result, "total": len(result)})

@ai_roles_api.route('/api/ai/employee/roles/stats', methods=['GET'])
def role_stats():
    conn = _db()
    total_emps = conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
    covered = conn.execute("SELECT COUNT(DISTINCT employee_pk) FROM mt_ai_employee_role_binding").fetchone()[0]
    total_bindings = conn.execute("SELECT COUNT(*) FROM mt_ai_employee_role_binding").fetchone()[0]
    total_daemon_binds = conn.execute("SELECT COUNT(*) FROM mt_daemon_employee_binding").fetchone()[0]
    conn.close()
    return jsonify({
        "success": True,
        "total_employees": total_emps,
        "covered": covered,
        "coverage_pct": round(covered/total_emps*100, 1),
        "total_bindings": total_bindings,
        "total_daemon_bindings": total_daemon_binds,
    })

@ai_roles_api.route('/api/ai/daemon/bindings', methods=['GET'])
def daemon_bindings():
    conn = _db()
    rows = conn.execute("""
        SELECT d.daemon_name, d.status as daemon_status, d.interval_seconds, d.total_runs, d.last_heartbeat,
               e.name as employee_name, b.role_in_daemon
        FROM mt_daemon_registry d
        LEFT JOIN mt_daemon_employee_binding b ON d.daemon_name = b.daemon_name
        LEFT JOIN ai_employees e ON b.employee_pk = e.id
        ORDER BY d.daemon_name
    """).fetchall()
    # 按 daemon 分组
    grouped = {}
    for r in rows:
        d = dict(r)
        dn = d['daemon_name']
        if dn not in grouped:
            grouped[dn] = {
                "daemon_name": dn,
                "status": d['daemon_status'],
                "interval_seconds": d['interval_seconds'],
                "total_runs": d['total_runs'],
                "last_heartbeat": d['last_heartbeat'],
                "employees": [],
            }
        if d['employee_name']:
            grouped[dn]['employees'].append({"name": d['employee_name'], "role": d['role_in_daemon']})
    conn.close()
    return jsonify({"success": True, "data": list(grouped.values()), "total": len(grouped)})

@ai_roles_api.route('/api/ai/employee/<name>/roles', methods=['GET'])
def employee_roles(name):
    conn = _db()
    emp = conn.execute("SELECT * FROM ai_employees WHERE name=?", (name,)).fetchone()
    if not emp:
        conn.close()
        return jsonify({"success": False, "error": "员工不存在"}), 404
    roles = conn.execute("""
        SELECT r.role_name, r.role_code, r.mission, r.matrix_id, b.is_primary
        FROM mt_ai_employee_role_binding b
        JOIN mt_ai_employee_roles r ON b.role_code = r.role_code
        WHERE b.employee_pk = ?
        ORDER BY b.is_primary DESC
    """, (emp['id'],)).fetchall()
    conn.close()
    return jsonify({"success": True, "employee": dict(emp), "roles": [dict(r) for r in roles]})

print("[AI-ROLES] Blueprint ai_roles_api 已注册: 4 路由")
