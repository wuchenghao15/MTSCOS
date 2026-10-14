"""v1/invite — EigenFlux 邀请流程 (批量/重试/状态/互推统计)"""
import os, sys
from flask import Blueprint, request, jsonify
from .._helpers import _db_conn, _api_success, _api_error
from .._auth import require_api_key

bp = Blueprint("andromeda_v1_invite", __name__, url_prefix="/invite")

_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engines")


@bp.route("/status", methods=["GET"])
def invite_status():
    """邀请状态跟踪."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        status_dist = {}
        try:
            for r in cur.execute("SELECT invite_status, COUNT(*) FROM mt_eigenflux_invite_log GROUP BY 1"):
                status_dist[r[0]] = r[1]
        except Exception:
            pass
        source_dist = {}
        try:
            for r in cur.execute("SELECT invite_source, COUNT(*) FROM mt_eigenflux_invite_log GROUP BY 1"):
                source_dist[r[0]] = r[1]
        except Exception:
            pass
        recent = []
        try:
            cur.execute("""
                SELECT invite_id, expert_name, expert_domain, invite_source, invite_status,
                       COALESCE(retry_count,0) AS retry_count, last_retry_at, invited_at
                FROM mt_eigenflux_invite_log ORDER BY invited_at DESC LIMIT 20""")
            recent = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
        pending_count = 0
        try:
            pending_count = cur.execute(
                "SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='pending_invite'"
            ).fetchone()[0]
        except Exception:
            pass
        retry_summary = {}
        try:
            for r in cur.execute("""
                SELECT COALESCE(retry_count,0) AS rc, COUNT(*)
                FROM mt_eigenflux_invite_log GROUP BY rc ORDER BY rc"""):
                retry_summary[str(r[0])] = r[1]
        except Exception:
            pass
        conn.close()
        return jsonify(_api_success(
            status_distribution=status_dist, source_distribution=source_dist,
            retry_summary=retry_summary, pending_invite_count=pending_count, recent_invites=recent,
        ))
    except Exception as e:
        return _api_error(str(e))


@bp.route("/batch", methods=["POST"])
@require_api_key
def invite_batch():
    """批量邀请 (同步执行, 纯 INSERT, 秒级)."""
    payload = request.get_json(silent=True) or {}
    count = int(payload.get("count", 5))
    domain = payload.get("domain")
    source = payload.get("source", "SA_BATCH_INVITE")
    try:
        if _ENGINES_DIR not in sys.path: sys.path.insert(0, _ENGINES_DIR)
        from ai_auto_hire_engine import batch_invite
        result = batch_invite(count=count, domain=domain, source=source)
        return jsonify(_api_success(result=result))
    except Exception as e:
        return _api_error(str(e))


@bp.route("/retry", methods=["POST"])
@require_api_key
def invite_retry():
    """邀请重试 (非 ACCEPTED + 未达上限)."""
    payload = request.get_json(silent=True) or {}
    max_retry = int(payload.get("max_retry", 3))
    try:
        if _ENGINES_DIR not in sys.path: sys.path.insert(0, _ENGINES_DIR)
        from ai_auto_hire_engine import retry_pending_invites
        result = retry_pending_invites(max_retry=max_retry)
        return jsonify(_api_success(result=result))
    except Exception as e:
        return _api_error(str(e))


@bp.route("/mutual_stats", methods=["GET"])
def invite_mutual_stats():
    """好友互推统计 + 连接强度."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        total = connected = 0
        try:
            total = cur.execute("SELECT COUNT(*) FROM mt_ai_eigenflux_connections").fetchone()[0]
            connected = cur.execute(
                "SELECT COUNT(*) FROM mt_ai_eigenflux_connections WHERE handshake_state='CONNECTED'"
            ).fetchone()[0]
        except Exception:
            pass
        relation_dist = {}
        try:
            for r in cur.execute(
                "SELECT relation_level, COUNT(*) FROM mt_ai_eigenflux_connections GROUP BY 1"):
                relation_dist[r[0]] = r[1]
        except Exception:
            pass
        friend_rec = 0
        try:
            friend_rec = cur.execute("""
                SELECT COUNT(*) FROM mt_ai_eigenflux_connections
                WHERE shared_topics_json LIKE '%friend_recommendation%'""").fetchone()[0]
        except Exception:
            pass
        recent_24h = 0
        try:
            recent_24h = cur.execute("""
                SELECT COUNT(*) FROM mt_ai_eigenflux_connections
                WHERE created_at >= datetime('now','-1 day')""").fetchone()[0]
        except Exception:
            pass
        avg_strength = 0.0
        try:
            v = cur.execute(
                "SELECT AVG(strength) FROM mt_ai_eigenflux_connections WHERE handshake_state='CONNECTED'"
            ).fetchone()[0]
            avg_strength = round(float(v), 3) if v is not None else 0.0
        except Exception:
            pass
        conn.close()
        return jsonify(_api_success(
            total_connections=total, connected=connected,
            relation_level_distribution=relation_dist, friend_recommended=friend_rec,
            friend_recommendation_ratio=round(friend_rec / total, 3) if total else 0.0,
            new_connections_24h=recent_24h, avg_connected_strength=avg_strength,
        ))
    except Exception as e:
        return _api_error(str(e))
