"""v1/hire — 仙女座桥接 → auto_hire → EigenFlux 邀请"""
import os, sys, time, threading
from flask import Blueprint, request, jsonify
from .._helpers import _db_conn, _api_success, _api_error
from .._auth import require_api_key

bp = Blueprint("andromeda_v1_hire", __name__, url_prefix="/hire")

_ENGINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engines")


@bp.route("/trigger", methods=["POST"])
@require_api_key
def hire_trigger():
    """SA 手动触发一轮: 仙女座桥接 → auto_hire → EigenFlux 邀请 (后台异步)."""
    payload = request.get_json(silent=True) or {}
    max_andromeda = int(payload.get("max_andromeda", 30))
    min_level = int(payload.get("min_level", 7))

    def _run():
        try:
            if _ENGINES_DIR not in sys.path:
                sys.path.insert(0, _ENGINES_DIR)
            from ai_auto_hire_engine import run_hire_cycle
            result = run_hire_cycle()
            print(f"[HIRE] done andromeda={result.get('andromeda_bridge',{}).get('bridged',0)} "
                  f"hire={result.get('hire_employees',{}).get('hired',0)} "
                  f"invite={result.get('invite_experts',{}).get('invited',0)}")
        except Exception as e:
            print(f"[HIRE] error: {e}")

    t = threading.Thread(target=_run, name=f"andromeda_hire_{int(time.time())}", daemon=True)
    t.start()
    return jsonify(_api_success(
        msg="Hire 已触发 (仙女座桥接 + auto_hire + EigenFlux 邀请)",
        thread_started=True,
        params={"max_andromeda": max_andromeda, "min_level": min_level},
    ))


@bp.route("/pending", methods=["GET"])
def hire_pending():
    """EigenFlux 待邀请队列 + 最近 1h 消息."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        status_dist = {}
        try:
            for r in cur.execute("""
                SELECT registration_status, COUNT(*) FROM eigenflux_registrations
                GROUP BY registration_status ORDER BY COUNT(*) DESC"""):
                status_dist[r[0]] = r[1]
        except Exception:
            pass
        pending = []
        try:
            cur.execute("""
                SELECT employee_id, employee_name, employee_type, registration_status,
                       created_at, last_heartbeat
                FROM eigenflux_registrations
                WHERE registration_status IN ('pending_invite','inactive','unknown')
                ORDER BY created_at DESC LIMIT 20""")
            pending = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
        recent_1h = 0
        try:
            recent_1h = cur.execute("""
                SELECT COUNT(*) FROM mt_ai_eigenflux_messages
                WHERE created_at >= datetime('now','-1 hour')""").fetchone()[0]
        except Exception:
            pass
        conn.close()
        return jsonify(_api_success(
            status_distribution=status_dist, pending_list=pending,
            recent_eigenflux_messages_1h=recent_1h,
        ))
    except Exception as e:
        return _api_error(str(e))
