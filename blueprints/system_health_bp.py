#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Health Blueprint — 三系统统一健康/配置/事件 API
=====================================================
注册到 Flask app 后提供:
  GET /api/system/health          三系统综合健康
  GET /api/system/dashboard       完整仪表板
  GET /api/system/<sys>/health    单系统 drill-down
  GET /api/system/events          事件总线最近事件
  GET /api/system/config          所有配置 key + source
  GET /api/system/daemons         所有 mt_daemon_registry 条目
  GET /api/system/engines         三引擎 health_check
  GET /api/system/status          简洁状态 (单行per system)
  GET /api/system/schema          预定义事件类型表
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint('system_health', __name__, url_prefix='/api/system')


# ── 懒加载 SystemManager / ConfigCenter / EventBus ──────
def _get_manager():
    from engines.system_manager import SystemManager
    return SystemManager()


def _get_cc():
    from engines.centralized_config import ConfigCenter
    return ConfigCenter()


def _get_bus():
    from engines.event_bus_engine import EventBus
    return EventBus()


def _engine_health_all():
    """三个核心引擎的 health_check"""
    results = {}
    # Iceberg
    try:
        from engines.iceberg_consciousness import IcebergConsciousness
        ic = IcebergConsciousness()
        results["iceberg"] = ic.health_check()
    except Exception as e:
        results["iceberg"] = {"error": str(e)[:200]}

    # AutoPilot
    try:
        from engines.andromeda_autopilot_v2 import AutoPilotV2
        ap = AutoPilotV2()
        results["andromeda"] = ap.health_check()
    except Exception as e:
        results["andromeda"] = {"error": str(e)[:200]}

    # Gobelin
    try:
        from engines.gobelin_daily_pnl import GobelinDailyPnl
        gd = GobelinDailyPnl()
        results["gobelin"] = gd.health_check()
    except Exception as e:
        results["gobelin"] = {"error": str(e)[:200]}

    return results


# ═══════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════

@bp.get('/health')
def api_system_health():
    """三个系统综合健康 — HTTP + launchd + DB + daemon_registry"""
    target = request.args.get('system', 'all')
    target = None if target == 'all' else target
    try:
        mgr = _get_manager()
        return jsonify(mgr.health_check(target))
    except Exception as e:
        return jsonify({"error": str(e)[:300], "at": datetime.now().isoformat()}), 500


@bp.get('/dashboard')
def api_system_dashboard():
    """完整仪表板: 聚合三系统 + DB + 事件总线"""
    try:
        mgr = _get_manager()
        return jsonify(mgr.status_dashboard())
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/<system>/health')
def api_single_system_health(system):
    """单系统 drill-down"""
    if system not in ("iceberg", "gobelin", "andromeda"):
        return jsonify({"error": f"unknown system: {system}",
                        "valid": ["iceberg", "gobelin", "andromeda"]}), 400
    try:
        mgr = _get_manager()
        hc = mgr.health_check(system)
        return jsonify(hc)
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/status')
def api_system_status():
    """简洁单行状态 — 快速巡检"""
    try:
        mgr = _get_manager()
        hc = mgr.health_check()
        rows = []
        for k, v in hc["systems"].items():
            rows.append({
                "system": k,
                "name": v["name"],
                "status": v["status"],
                "score": v["score"],
                "http_ok": v["http"].get("ok") if v["http"] else None,
                "daemons_total": len(v["daemons"]),
                "daemons_running": sum(1 for d in v["daemons"] if d.get("running")),
            })
        return jsonify({
            "at": hc["checked_at"],
            "systems": rows,
        })
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/events')
def api_events():
    """事件总线事件历史"""
    source = request.args.get('source')
    target = request.args.get('target')
    since = request.args.get('since')
    event_name = request.args.get('event')
    limit = int(request.args.get('limit', 50))
    limit = min(limit, 200)

    try:
        bus = _get_bus()
        events = bus.list_events(
            source=source, target=target, since=since,
            event_name=event_name, limit=limit
        )
        stats = bus.stats()
        return jsonify({
            "events": events,
            "stats": stats,
        })
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/config')
def api_config():
    """所有配置 key + source (只读, 敏感值脱敏)"""
    try:
        cc = _get_cc()
        all_cfg = cc.list_all()

        # 可选分组
        group = request.args.get('group')
        if group:
            all_cfg = {k: v for k, v in all_cfg.items() if v.get("group") == group}

        # 只展示 source 汇总 (不含敏感 value 细节)
        summary = {}
        for k, v in all_cfg.items():
            summary[k] = {
                "source": v.get("source", "?"),
                "group": v.get("group", "?"),
                "value_preview": str(v.get("value", ""))[:60],
                "description": v.get("description", ""),
            }

        return jsonify({
            "total_keys": len(all_cfg),
            "db_path": cc.get_db(),
            "env_file": str(cc.env_file),
            "keys": summary,
        })
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/daemons')
def api_daemons():
    """mt_daemon_registry 全部条目"""
    try:
        cc = _get_cc()
        daemons = cc.list_daemons()
        # 统计
        running = sum(1 for d in daemons if d.get("status") in ("RUNNING", "ACTIVE"))
        exited = sum(1 for d in daemons if d.get("status") in ("EXITED", "STOPPED", "FAILED"))
        return jsonify({
            "total": len(daemons),
            "running": running,
            "exited": exited,
            "daemons": daemons,
        })
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/engines')
def api_engines():
    """三个核心引擎 health_check"""
    try:
        return jsonify(_engine_health_all())
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/schema')
def api_schema():
    """预定义事件类型 + 系统定义"""
    try:
        from engines.event_bus_engine import PREDEFINED_EVENTS
        from engines.system_manager import SYSTEMS
        return jsonify({
            "events": PREDEFINED_EVENTS,
            "systems": {
                k: {
                    "name": v["name"],
                    "health_endpoint": v["health_endpoint"],
                    "launchd_daemons": v["launchd_daemons"],
                    "core_daemons": v["core_daemons"],
                    "core_engine": v["core_engine"],
                }
                for k, v in SYSTEMS.items()
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 500


@bp.get('/ping')
def api_ping():
    return jsonify({"pong": True, "at": datetime.now().isoformat()})


# ═══════════════════════════════════════════════════════════════════
# 直接运行 (用于 debug)
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(bp)
    print("[system_health_bp] 直接启动测试服务器 http://127.0.0.1:5099")
    app.run(host="127.0.0.1", port=5099, debug=True)
