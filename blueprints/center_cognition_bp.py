"""
🧠 Center Cognition Blueprint — AI 元认知引擎 API
routes:
  GET  /api/center-cognition/portraits          所有中心画像
  GET  /api/center-cognition/portraits/<name>   单个中心画像 (含职责/边界/协作/AI路由)
  POST /api/center-cognition/empower             一键 AI 赋能全部中心
  GET  /api/center-cognition/collab-matrix      协作热力图
  GET  /api/center-cognition/boundaries         能力边界 + 越权历史
  GET  /api/center-cognition/experience/<name>  中心专属经验
  POST /api/center-cognition/ai-route/<name>    为中心 AI 选路由
  GET  /api/center-cognition/violations         越权检测
  GET  /api/center-cognition/health-summary     总览
"""
import functools
import os
import sys
import traceback
import sqlite3

from flask import Blueprint, jsonify, request

center_cognition_bp = Blueprint('center_cognition', __name__,
                                 url_prefix='/api/center-cognition')

_DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', 'database', 'app.db'
))


def _db_conn(readonly=True):
    if readonly:
        return sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    return sqlite3.connect(_DB_PATH)


def _cce():
    from engines.center_cognition_engine import CenterCognitionEngine
    return CenterCognitionEngine(_DB_PATH)


# ─────────────────────────────────────────────────────────
# 1. 所有中心画像
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/portraits', methods=['GET'])
def api_all_portraits():
    try:
        conn = _db_conn()
        rows = conn.execute("""
            SELECT portrait_id, center_name, galaxy, primary_duty,
                   secondary_duty, health_score, ollama_generated,
                   updated_at
            FROM mt_center_cognition_portrait
            ORDER BY health_score ASC
        """).fetchall()
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM mt_center_cognition_portrait LIMIT 1"
        ).description]
        portraits = []
        for r in rows:
            portraits.append({
                "center_name": r[1],
                "galaxy": r[2],
                "primary_duty": r[3],
                "secondary_duty": r[4],
                "health_score": r[5],
                "ollama_generated": bool(r[6]),
                "updated_at": r[7],
            })
        # 加一个 overview
        overview = {
            "total": len(portraits),
            "avg_health": round(sum(p["health_score"] for p in portraits) / max(len(portraits), 1), 1),
            "healthy_count": sum(1 for p in portraits if p["health_score"] >= 70),
            "unhealthy_count": sum(1 for p in portraits if 0 < p["health_score"] < 70),
            "ollama_count": sum(1 for p in portraits if p["ollama_generated"]),
        }
        conn.close()
        return jsonify({"success": True, "overview": overview, "portraits": portraits})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 2. 单个中心画像 (含职责/边界/协作/AI路由)
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/portraits/<path:center_name>', methods=['GET'])
def api_single_portrait(center_name):
    try:
        conn = _db_conn()
        # Portrait
        row = conn.execute("""
            SELECT center_name, galaxy, primary_duty, secondary_duty,
                   boundaries, ai_route, event_distribution, collab_frequency,
                   health_score, ollama_generated, generated_at, updated_at
            FROM mt_center_cognition_portrait WHERE center_name = ?
        """, (center_name,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "error": f"center {center_name} not found"}), 404

        portrait = {
            "center_name": row[0], "galaxy": row[1],
            "primary_duty": row[2], "secondary_duty": row[3],
            "boundaries": __import__('json').loads(row[4] or '{}'),
            "ai_route": __import__('json').loads(row[5] or '{}'),
            "event_distribution": __import__('json').loads(row[6] or '[]'),
            "collab_frequency": __import__('json').loads(row[7] or '[]'),
            "health_score": row[8], "ollama_generated": bool(row[9]),
            "generated_at": row[10], "updated_at": row[11],
        }

        # Boundary
        b_row = conn.execute("""
            SELECT can_do, cannot_do, recent_violations, last_violation, ollama_reasoning
            FROM mt_center_boundary WHERE center_name = ?
        """, (center_name,)).fetchone()
        if b_row:
            portrait["boundary_detail"] = {
                "can_do": __import__('json').loads(b_row[0] or '[]'),
                "cannot_do": __import__('json').loads(b_row[1] or '[]'),
                "recent_violations": b_row[2],
                "last_violation": b_row[3],
                "ollama_reasoning": b_row[4],
            }

        # Collab partners
        collab_rows = conn.execute("""
            SELECT target_center, event_count, relationship, suggested_upgrade
            FROM mt_center_collab_matrix WHERE source_center = ?
            ORDER BY event_count DESC
        """, (center_name,)).fetchall()
        portrait["collab_targets"] = [{
            "target": r[0], "count": r[1],
            "relationship": r[2], "suggestion": r[3],
        } for r in collab_rows]

        # 也看看谁跟我协作
        collab_from = conn.execute("""
            SELECT source_center, event_count, relationship, suggested_upgrade
            FROM mt_center_collab_matrix WHERE target_center = ?
            ORDER BY event_count DESC
        """, (center_name,)).fetchall()
        portrait["collab_sources"] = [{
            "source": r[0], "count": r[1],
            "relationship": r[2], "suggestion": r[3],
        } for r in collab_from]

        conn.close()
        return jsonify({"success": True, "portrait": portrait})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 3. 一键 AI 赋能全部中心
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/empower', methods=['POST'])
def api_empower():
    try:
        cce = _cce()
        body = request.get_json(silent=True) or {}
        result = cce.empower_all_centers()
        return jsonify({
            "success": True,
            "portrait_count": len(result.get("portraits", {})),
            "collab_pairs": result.get("collab", {}).get("total_pairs", 0),
            "boundary_count": len(result.get("boundaries", {})),
            "experience_count": sum(
                v.get("count", 0) for v in result.get("experiences", {}).values()
            ),
            "ollama_available": result.get("ollama_available", False),
            "duration_ms": result.get("duration_ms", 0),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 4. 协作热力图
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/collab-matrix', methods=['GET'])
def api_collab_matrix():
    try:
        conn = _db_conn()
        rows = conn.execute("""
            SELECT source_center, target_center, event_count, event_types,
                   relationship, suggested_upgrade, last_collab
            FROM mt_center_collab_matrix
            ORDER BY event_count DESC
            LIMIT 50
        """).fetchall()
        pairs = []
        for r in rows:
            pairs.append({
                "source": r[0], "target": r[1], "count": r[2],
                "event_types": __import__('json').loads(r[3] or '{}'),
                "relationship": r[4], "suggestion": r[5],
                "last_collab": r[6],
            })
        # summary
        in_degree = {}
        out_degree = {}
        for p in pairs:
            out_degree[p["source"]] = out_degree.get(p["source"], 0) + p["count"]
            if p["target"] != 'broadcast':
                in_degree[p["target"]] = in_degree.get(p["target"], 0) + p["count"]

        conn.close()
        return jsonify({
            "success": True,
            "total_pairs": len(pairs),
            "pairs": pairs,
            "top_hubs": sorted(in_degree.items(), key=lambda x: -x[1])[:5],
            "top_sources": sorted(out_degree.items(), key=lambda x: -x[1])[:5],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 5. 能力边界 + 越权历史
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/boundaries', methods=['GET'])
def api_boundaries():
    try:
        conn = _db_conn()
        rows = conn.execute("""
            SELECT center_name, can_do, cannot_do, recent_violations,
                   last_violation, ollama_reasoning, updated_at
            FROM mt_center_boundary
            ORDER BY recent_violations DESC, center_name
        """).fetchall()
        boundaries = []
        for r in rows:
            boundaries.append({
                "center_name": r[0],
                "can_do": __import__('json').loads(r[1] or '[]'),
                "cannot_do": __import__('json').loads(r[2] or '[]'),
                "recent_violations": r[3],
                "last_violation": r[4],
                "ollama_reasoning": r[5],
                "updated_at": r[6],
            })
        conn.close()
        return jsonify({
            "success": True,
            "total": len(boundaries),
            "violating_count": sum(1 for b in boundaries if b["recent_violations"] > 0),
            "boundaries": boundaries,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 6. 中心专属经验
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/experience/<path:center_name>', methods=['GET'])
def api_experience(center_name):
    try:
        conn = _db_conn()
        rows = conn.execute("""
            SELECT exp_type, summary, lesson, confidence,
                   source_events, applicable_engines, created_at
            FROM mt_center_experience
            WHERE center_name = ?
            ORDER BY confidence DESC
        """, (center_name,)).fetchall()
        experiences = []
        for r in rows:
            experiences.append({
                "exp_type": r[0], "summary": r[1], "lesson": r[2],
                "confidence": r[3],
                "source_events": __import__('json').loads(r[4] or '[]'),
                "applicable_engines": __import__('json').loads(r[5] or '[]'),
                "created_at": r[6],
            })
        conn.close()
        return jsonify({
            "success": True,
            "center": center_name,
            "count": len(experiences),
            "experiences": experiences,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 7. 为中心 AI 选路由
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/ai-route/<path:center_name>', methods=['POST', 'GET'])
def api_ai_route(center_name):
    try:
        cce = _cce()
        body = request.get_json(silent=True) if request.method == 'POST' else {}
        task = body.get('task') or request.args.get('task')
        route = cce.ai_route_for_center(center_name, task=task)
        return jsonify({"success": True, "route": route})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 8. 越权检测
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/violations', methods=['GET'])
def api_violations():
    try:
        cce = _cce()
        violations = cce.detect_scope_violations()
        return jsonify({
            "success": True,
            "violations": violations,
            "count": len(violations),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────
# 9. 健康总览
# ─────────────────────────────────────────────────────────
@center_cognition_bp.route('/health-summary', methods=['GET'])
def api_health_summary():
    try:
        conn = _db_conn()
        # Portrait stats
        portrait_cnt = conn.execute("SELECT COUNT(*) FROM mt_center_cognition_portrait").fetchone()[0]
        collab_cnt = conn.execute("SELECT COUNT(*) FROM mt_center_collab_matrix").fetchone()[0]
        boundary_cnt = conn.execute("SELECT COUNT(*) FROM mt_center_boundary").fetchone()[0]
        experience_cnt = conn.execute("SELECT COUNT(*) FROM mt_center_experience").fetchone()[0]

        # avg health
        avg_health = conn.execute(
            "SELECT AVG(health_score) FROM mt_center_cognition_portrait WHERE health_score > 0"
        ).fetchone()[0] or 0

        # bottlenecks from health_matrix
        bn_row = conn.execute("""
            SELECT bottlenecks FROM mt_center_health_matrix
            ORDER BY created_at DESC LIMIT 1
        """).fetchone()
        bottlenecks = __import__('json').loads(bn_row[0] or '[]') if bn_row else []

        conn.close()
        return jsonify({
            "success": True,
            "portrait_count": portrait_cnt,
            "collab_pairs": collab_cnt,
            "boundary_count": boundary_cnt,
            "experience_count": experience_cnt,
            "avg_health": round(avg_health, 1),
            "bottlenecks": bottlenecks,
            "ollama_available": _cce().ollama_available,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
