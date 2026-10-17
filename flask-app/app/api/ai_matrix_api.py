#!/usr/bin/env python3
"""
仙女座 §四.2 AI 矩阵体系 API
==============================
矩阵查询 / 成员管理 / 互通拓扑 / 跨域融合
"""
import sqlite3, json, os
from flask import Blueprint, jsonify, request
from app.middlewares.system_container import system_container

ai_matrix_api = Blueprint('ai_matrix_api', __name__)

DB_PATH = None
for p in [os.path.expanduser("~/mtscos/_runtime/databases/Database/app.db"),
          os.path.join(os.path.dirname(__file__), "../..", "_runtime", "databases", "Database", "app.db")]:
    if os.path.exists(p):
        DB_PATH = p; break

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

@ai_matrix_api.route('/api/ai/matrices', methods=['GET'])
@system_container(require_auth='guest')
def list_matrices():
    conn = _db()
    rows = conn.execute("""
        SELECT m.matrix_id, m.matrix_name, m.fusion_level, m.status, m.employee_count,
               m.mission, m.core_capability, m.accuracy_score,
               COUNT(mem.rowid) as real_count,
               m.cross_domain_edges
        FROM mt_ai_matrix m
        LEFT JOIN mt_ai_matrix_members mem ON m.matrix_id = mem.matrix_id
        GROUP BY m.matrix_id
        ORDER BY m.employee_count DESC
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # 加载成员名
        members = conn.execute("""
            SELECT e.name, mem.role_in_matrix, mem.weight
            FROM mt_ai_matrix_members mem
            JOIN ai_employees e ON mem.employee_pk = e.id
            WHERE mem.matrix_id = ?
            ORDER BY mem.weight DESC
        """, (d['matrix_id'],)).fetchall()
        d['members'] = [dict(m) for m in members]
        d['core_capability'] = json.loads(d['core_capability']) if d['core_capability'] else []
        d['cross_domain_edges'] = json.loads(d['cross_domain_edges']) if d['cross_domain_edges'] else []
        result.append(d)
    conn.close()
    return jsonify({"success": True, "data": result, "total": len(result)})

@ai_matrix_api.route('/api/ai/matrix/<matrix_id>', methods=['GET'])
@system_container(require_auth='guest')
def get_matrix(matrix_id):
    conn = _db()
    row = conn.execute("SELECT * FROM mt_ai_matrix WHERE matrix_id=?", (matrix_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "error": "矩阵不存在"}), 404
    m = dict(row)
    m['core_capability'] = json.loads(m['core_capability']) if m.get('core_capability') else []
    m['cross_domain_edges'] = json.loads(m['cross_domain_edges']) if m.get('cross_domain_edges') else []

    # 成员
    members = conn.execute("""
        SELECT e.id as employee_pk, e.name, e.capabilities, mem.role_in_matrix, mem.weight, mem.last_active
        FROM mt_ai_matrix_members mem
        JOIN ai_employees e ON mem.employee_pk = e.id
        WHERE mem.matrix_id = ?
        ORDER BY mem.weight DESC, mem.role_in_matrix
    """, (matrix_id,)).fetchall()
    m['members'] = [dict(x) for x in members]

    # 互通 edge
    edges = conn.execute("""
        SELECT from_matrix, to_matrix, edge_type, description, enabled
        FROM mt_ai_matrix_edge
        WHERE from_matrix = ? OR to_matrix = ?
    """, (matrix_id, matrix_id)).fetchall()
    m['edges'] = [dict(x) for x in edges]

    # 互通统计
    edge_types = {}
    for e in m['edges']:
        t = e['edge_type']
        edge_types[t] = edge_types.get(t, 0) + 1
    m['edge_stats'] = edge_types

    # 健康度
    m['health'] = {
        'member_count': len(m['members']),
        'edge_count': len(m['edges']),
        'avg_weight': sum(x['weight'] for x in m['members']) / max(1, len(m['members'])),
        'fusion_score': {'互通': 1, '互推': 2, '互衍生': 3, '跨域融合': 4}.get(m['fusion_level'], 1),
    }
    conn.close()
    return jsonify({"success": True, "data": m})

@ai_matrix_api.route('/api/ai/matrix/edges', methods=['GET'])
@system_container(require_auth='guest')
def list_edges():
    conn = _db()
    rows = conn.execute("""
        SELECT from_matrix as src, to_matrix as dst, edge_type, description, enabled
        FROM mt_ai_matrix_edge WHERE enabled=1
    """).fetchall()
    conn.close()
    return jsonify({
        "success": True,
        "data": [dict(r) for r in rows],
        "count": len(rows),
        "graph_type": "directed",
        "edge_types": ["互通", "互推", "互衍生", "跨域融合"],
    })

@ai_matrix_api.route('/api/ai/matrix/topology', methods=['GET'])
@system_container(require_auth='guest')
def matrix_topology():
    """拓扑结构：节点 + 边，可用于前端可视化"""
    conn = _db()
    nodes = conn.execute("""
        SELECT matrix_id as id, matrix_name as label, fusion_level, status,
               employee_count as size
        FROM mt_ai_matrix WHERE status='active'
    """).fetchall()
    edges = conn.execute("""
        SELECT from_matrix as source, to_matrix as target, edge_type, description
        FROM mt_ai_matrix_edge WHERE enabled=1
    """).fetchall()
    conn.close()
    return jsonify({
        "success": True,
        "nodes": [dict(n) for n in nodes],
        "edges": [dict(e) for e in edges],
        "meta": {
            "fusion_levels": ["互通", "互推", "互衍生", "跨域融合"],
            "edge_count": len(edges),
            "node_count": len(nodes),
        }
    })

@ai_matrix_api.route('/api/ai/matrix/stats', methods=['GET'])
@system_container(require_auth='guest')
def matrix_stats():
    """全局矩阵统计"""
    conn = _db()
    total_matrices = conn.execute("SELECT COUNT(*) FROM mt_ai_matrix").fetchone()[0]
    total_members = conn.execute("SELECT COUNT(*) FROM mt_ai_matrix_members").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM mt_ai_matrix_edge WHERE enabled=1").fetchone()[0]
    fusion_dist = conn.execute("""
        SELECT fusion_level, COUNT(*) FROM mt_ai_matrix GROUP BY fusion_level
    """).fetchall()
    employee_coverage = conn.execute("""
        SELECT COUNT(DISTINCT employee_pk) FROM mt_ai_matrix_members
    """).fetchone()[0]
    total_employees = conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
    conn.close()
    return jsonify({
        "success": True,
        "total_matrices": total_matrices,
        "total_member_assignments": total_members,
        "total_edges": total_edges,
        "fusion_distribution": {r[0]: r[1] for r in fusion_dist},
        "employee_coverage": f"{employee_coverage}/{total_employees}",
        "coverage_ratio": round(employee_coverage / max(1, total_employees), 2),
    })

@ai_matrix_api.route('/api/ai/matrix/<matrix_id>/members/<employee_pk>', methods=['POST'])
@system_container(require_auth='admin')
def add_member(matrix_id, employee_pk):
    conn = _db()
    now = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute("""INSERT OR IGNORE INTO mt_ai_matrix_members
            (matrix_id, employee_pk, role_in_matrix, last_active)
            VALUES (?,?,?,?)""", (matrix_id, employee_pk, '成员', now))
        conn.execute("UPDATE mt_ai_matrix SET employee_count = employee_count + 1 WHERE matrix_id=?", (matrix_id,))
        conn.commit()
        return jsonify({"success": True, "message": "已添加成员"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    finally:
        conn.close()

@ai_matrix_api.route('/api/ai/matrix/<matrix_id>/members/<employee_pk>', methods=['DELETE'])
@system_container(require_auth='admin')
def remove_member(matrix_id, employee_pk):
    conn = _db()
    conn.execute("DELETE FROM mt_ai_matrix_members WHERE matrix_id=? AND employee_pk=?", (matrix_id, employee_pk))
    conn.execute("UPDATE mt_ai_matrix SET employee_count = employee_count - 1 WHERE matrix_id=?", (matrix_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

print("[AI-MATRIX] Blueprint ai_matrix_api 已注册: 7 个路由")
