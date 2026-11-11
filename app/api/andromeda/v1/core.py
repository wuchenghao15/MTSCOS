"""v1/core — 仙女座核心引擎端点"""
import time
import threading
from flask import Blueprint, request, jsonify
from .._helpers import (
    _now_iso, _db_conn, _read_checkpoint, _mini_ping, _ollama_check,
    _is_daemon_alive, _api_success, _api_error, DAEMON_NAMES,
)
from .._auth import require_api_key

bp = Blueprint("andromeda_v1_core", __name__, url_prefix="/core")


@bp.route("/stats", methods=["GET"])
@require_api_key
def core_stats():
    """核心仪表盘全量数据 — 演化 + 7 张 DB 表 + daemon 心跳 + 基础设施."""
    t0 = time.time()
    checkpoint = _read_checkpoint()
    mini = _mini_ping()
    ollama = _ollama_check()

    db_tables = {}
    daemons = {}
    try:
        conn = _db_conn()
        cur = conn.cursor()
        queries = [
            ("eigenflux_messages", "SELECT COUNT(*), substr(MAX(created_at),1,16) FROM eigenflux_comm_messages"),
            ("eigenflux_sessions", "SELECT COUNT(*) FROM eigenflux_comm_sessions"),
            ("brain_enhanced", "SELECT COUNT(*), substr(MAX(created_at),1,16) FROM ai_brain_enhanced_knowledge"),
            ("graph_nodes", "SELECT COUNT(*) FROM knowledge_graph_nodes"),
            ("graph_relations", "SELECT COUNT(*) FROM knowledge_graph_relations"),
            ("employee_registry", "SELECT COUNT(*) FROM mt_andromeda_employee_registry"),
            ("evolution_log", "SELECT COUNT(*), substr(MAX(created_at),1,16) FROM mt_ai_self_evolution_log"),
        ]
        for name, sql in queries:
            row = cur.execute(sql).fetchone()
            db_tables[name] = {"count": row[0], "latest": row[1] if len(row) > 1 else None}

        placeholders = ",".join("?" * len(DAEMON_NAMES))
        hb_rows = cur.execute(
            f"SELECT process_name, last_heartbeat, status, restart_count FROM mt_daemon_registry "
            f"WHERE process_name IN ({placeholders})", DAEMON_NAMES).fetchall()
        for name, hb, status, restart in hb_rows:
            daemons[name] = {
                "heartbeat": hb, "status": status,
                "restart_count": restart or 0,
                "is_alive": _is_daemon_alive(hb),
            }
        conn.close()
    except Exception as e:
        return _api_error(f"DB error: {e}")

    derived_per_cycle = checkpoint["total_derived"] / max(checkpoint["cycle_count"], 1)

    issues = []
    if not mini["alive"]: issues.append({"level": "warn", "msg": "Mac mini 离线"})
    if not ollama["alive"]: issues.append({"level": "fail", "msg": "Ollama 离线"})
    if any(not d.get("is_alive") for d in daemons.values()):
        issues.append({"level": "warn", "msg": "部分 daemon 心跳过期"})
    health = "green" if not issues else ("red" if any(i["level"] == "fail" for i in issues) else "yellow")

    return jsonify(_api_success(
        elapsed_ms=round((time.time() - t0) * 1000),
        evolution={
            "cycle_count": checkpoint["cycle_count"],
            "total_derived": checkpoint["total_derived"],
            "total_reinforced": checkpoint["total_reinforced"],
            "derived_per_cycle": round(derived_per_cycle, 1),
            "last_knowledge_id": checkpoint["last_knowledge_id"],
        },
        db_tables=db_tables,
        daemons={
            "autosync": daemons.get("sys_andromeda_autosync", {"is_alive": False}),
            "evolution": daemons.get("sys_andromeda_auto_evolution", {"is_alive": False}),
        },
        infra={"mini": mini, "ollama": ollama},
        andromeda_status={
            "health": health,
            "issues": issues,
            "score": 100 - len(issues) * 25,
        },
    ))


@bp.route("/health", methods=["GET"])
def core_health():
    """快速健康检查 — Ollama 核心在线即 ok."""
    mini = _mini_ping()
    ollama = _ollama_check()
    db_alive = {}
    try:
        conn = _db_conn()
        for name in DAEMON_NAMES:
            row = conn.execute(
                "SELECT last_heartbeat FROM mt_daemon_registry WHERE process_name=?",
                (name,)).fetchone()
            db_alive[name] = _is_daemon_alive(row[0] if row else None)
        conn.close()
    except Exception:
        pass

    return jsonify(_api_success(
        ok=ollama["alive"],
        ollama_alive=ollama["alive"],
        ollama_port=ollama.get("port"),
        mini_alive=mini["alive"],
        daemon_autosync_alive=db_alive.get("sys_andromeda_autosync", False),
        daemon_evolution_alive=db_alive.get("sys_andromeda_auto_evolution", False),
        all_daemons_alive=all(db_alive.values()) if db_alive else False,
    ))


@bp.route("/trigger", methods=["POST"])
@require_api_key
def core_trigger():
    """手动触发一轮演化 (后台异步)."""
    reason = request.args.get("reason", "api_v1_trigger")

    def _run():
        try:
            from engines.andromeda_auto_evolution import run_cycle
            run_cycle()
        except Exception as e:
            print(f"[ANDROMEDA trigger] error: {e}")

    t = threading.Thread(target=_run, name=f"andromeda_trigger_{int(time.time())}", daemon=True)
    t.start()
    return jsonify(_api_success(
        msg=f"演化已触发 (reason={reason})",
        thread_started=True, estimated_s=120,
    ))


@bp.route("/knowledge", methods=["GET"])
@require_api_key
def core_knowledge():
    """知识量快照 (messages + brain + graph + cycle 24h 增量)."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        result = {}
        queries = {
            "messages_total": "SELECT COUNT(*) FROM eigenflux_comm_messages",
            "messages_24h": "SELECT COUNT(*) FROM eigenflux_comm_messages WHERE created_at > datetime('now','-1 day')",
            "brain_total": "SELECT COUNT(*) FROM ai_brain_enhanced_knowledge",
            "brain_24h": "SELECT COUNT(*) FROM ai_brain_enhanced_knowledge WHERE created_at > datetime('now','-1 day')",
            "graph_nodes": "SELECT COUNT(*) FROM knowledge_graph_nodes",
            "graph_relations": "SELECT COUNT(*) FROM knowledge_graph_relations",
        }
        for k, sql in queries.items():
            try: result[k] = cur.execute(sql).fetchone()[0]
            except Exception: result[k] = None
        conn.close()
        cp = _read_checkpoint()
        result.update({"cycle_count": cp["cycle_count"],
                       "derived": cp["total_derived"], "reinforced": cp["total_reinforced"]})
        return jsonify(_api_success(dev_snapshot=result))
    except Exception as e:
        return _api_error(str(e))
