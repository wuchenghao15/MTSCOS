#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协作总线 REST API Blueprint
flow: flow_collab_bus_20261102_bp

所有端点 pass-through 登录检查 (内部基础设施)
"""

from __future__ import annotations

import json
import sys
from flask import Blueprint, jsonify, request

collab_bus_bp = Blueprint(
    'collab_bus',
    __name__,
    url_prefix='/api/collab-bus'
)

# 确保引擎表已初始化 + 强制注册 12 家订阅者 (自修复)
def _ensure_subscribers() -> None:
    """确保 11+1=12 家订阅者已注册, 自修复钩子"""
    try:
        from engines.collab_bus_engine import get_collab_bus, register_standard_subscribers
        bus = get_collab_bus()
        subs = bus.list_subscribers()
        if len(subs) < 10:
            sys.stderr.write(f"[COLLAB-BP] 订阅者只有 {len(subs)} 家! 强制注册...\n")
            register_standard_subscribers()
            sys.stderr.write(f"[COLLAB-BP] ✅ 自修复完成, 当前 {len(get_collab_bus().list_subscribers())} 家\n")
    except Exception as e:
        sys.stderr.write(f"[COLLAB-BP] _ensure_subscribers 失败: {e}\n")

# 启动时先尝试一次
try:
    from engines.collab_bus_engine import ensure_bus_tables
    ensure_bus_tables()
    _ensure_subscribers()
except Exception as e:
    sys.stderr.write(f"[COLLAB-BP] 启动初始化失败 (将自修复): {e}\n")


# ═══════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════

@collab_bus_bp.route('/status', methods=['GET'])
def api_status():
    """协作总线状态概览"""
    try:
        # 🆕 强制自修复: 如果订阅者不够, 立即注册 12 家
        _ensure_subscribers()
        
        from engines.collab_bus_engine import get_collab_bus
        
        bus = get_collab_bus()
        status = bus.get_status()
        
        return jsonify({
            "ok": True,
            "status": status,
            "timestamp": __import__('datetime').datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/events', methods=['GET'])
def api_events():
    """
    获取事件历史
    query params:
    - limit: 默认 50, 最大 200
    - event_type: 可选, 过滤事件类型
    """
    try:
        _ensure_subscribers()
        from engines.collab_bus_engine import get_recent_events
        
        limit = min(int(request.args.get('limit', 50)), 200)
        event_type = request.args.get('event_type', None)
        events = get_recent_events(limit=limit, event_type=event_type)
        
        return jsonify({
            "ok": True,
            "count": len(events),
            "events": events,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/subscribers', methods=['GET'])
def api_subscribers():
    """所有订阅者"""
    sys.stderr.write(f"[COLLAB-BP] ⚡ NEW ROUTE HIT /subscribers! Flask PID={__import__('os').getpid()}\n")
    try:
        # 🆕 强制自修复
        _ensure_subscribers()
        
        from engines.collab_bus_engine import get_collab_bus
        
        bus = get_collab_bus()
        subs = bus.list_subscribers()
        
        # 也从 DB 查一下注册的 (merge, 不覆盖内存)
        import sqlite3
        from pathlib import Path
        BASE = Path(__file__).resolve().parent.parent
        DB_PATH = BASE / "database" / "app.db"
        try:
            conn = sqlite3.connect(str(DB_PATH))
            db_subs = conn.execute(
                "SELECT subscriber_id, subscriber_name, subscribe_events, priority, handler_status, last_heartbeat, registered_at "
                "FROM mt_collab_bus_subscribers ORDER BY priority DESC"
            ).fetchall()
            conn.close()
            # 用内存订阅者为准, DB 里多的 merge 进来 (去重)
            mem_ids = {s.get('subscriber_id', s.get('id', '')) for s in subs}
            for row in db_subs:
                sid = row[0]
                if sid not in mem_ids:
                    subs.append({
                        'subscriber_id': sid, 'subscriber_name': row[1],
                        'subscribe_events': row[2], 'priority': row[3],
                        'handler_status': row[4], 'last_heartbeat': row[5],
                        'registered_at': row[6], 'from_db': True,
                    })
        except Exception:
            pass
        
        return jsonify({
            "ok": True,
            "count": len(subs),
            "subscribers": subs,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/publish', methods=['POST'])
def api_publish():
    """
    发布事件到协作总线
    body JSON:
    {
        "event_type": "MARKET_ANOMALY",
        "source": "manual",
        "severity": "ALERT",
        "symbol": "600519",
        "payload": {"anomaly":"LIMIT_UP","change_pct":9.98}
    }
    """
    try:
        from engines.collab_bus_engine import get_collab_bus
        
        data = request.get_json() or {}
        event_type = data.get('event_type', 'EVENT_CUSTOM')
        source = data.get('source', 'api')
        severity = data.get('severity', 'INFO')
        symbol = data.get('symbol', '')
        payload = data.get('payload', {})
        
        bus = get_collab_bus()
        result = bus.publish(
            event_type=event_type,
            source=source,
            payload=payload,
            severity=severity,
            symbol=symbol,
        )
        
        return jsonify({
            "ok": True,
            "event_id": result['event']['event_id'],
            "matched_subscribers": result['matched_subscribers'],
            "broadcast_ms": result['broadcast_ms'],
            "results": [
                {"subscriber_id": r['subscriber_id'], "status": r['status'], 
                 "response_ms": r['response_ms'], "error": r['error']}
                for r in result['subscriber_results']
            ],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/radar/cache', methods=['GET'])
def api_radar_cache():
    """市场雷达当前缓存"""
    try:
        from engines.collab_bus_engine import get_radar_cache, MarketRadarDaemon
        
        # 先从内存缓存取
        radar = MarketRadarDaemon()
        mem_cache = radar.get_cache()
        
        # 再从 DB 取持久化的
        db_cache = get_radar_cache()
        
        return jsonify({
            "ok": True,
            "memory_cache_count": len(mem_cache),
            "db_cache_count": len(db_cache),
            "db_cache": db_cache[:20],  # 最多 20 条
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/start', methods=['POST'])
def api_start_radar():
    """
    启动市场雷达 daemon
    body JSON: {"cycle": 5}
    """
    try:
        from engines.collab_bus_engine import MarketRadarDaemon
        
        data = request.get_json() or {}
        cycle = int(data.get('cycle', 5))
        
        radar = MarketRadarDaemon()
        radar.start(cycle=cycle)
        
        return jsonify({
            "ok": True,
            "message": f"市场雷达启动指令已发送 (cycle={cycle}s)",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# 版本中心扩展端点 (放在同一 BP 里, 避免多一个文件)
@collab_bus_bp.route('/version/components', methods=['GET'])
def api_version_components():
    """所有组件当前版本"""
    try:
        from engines.ai_version_center_engine import get_components
        comps = get_components()
        return jsonify({"ok": True, "count": len(comps), "components": comps})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/version/history', methods=['GET'])
def api_version_history():
    """
    版本历史
    query params:
    - component: 可选
    - limit: 默认 50
    """
    try:
        from engines.ai_version_center_engine import get_all_versions
        
        component = request.args.get('component', None)
        limit = min(int(request.args.get('limit', 50)), 200)
        versions = get_all_versions(component=component, limit=limit)
        
        return jsonify({"ok": True, "count": len(versions), "versions": versions})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@collab_bus_bp.route('/version/bump', methods=['POST'])
def api_version_bump():
    """
    手动触发版本 bump
    body JSON:
    {"component": "andromeda_core", "bump_type": "PATCH", "reason": "手动触发"}
    """
    try:
        from engines.ai_version_center_engine import manual_bump
        
        data = request.get_json() or {}
        component = data.get('component', 'andromeda_core')
        bump_type = data.get('bump_type', 'PATCH')
        reason = data.get('reason', 'API 手动触发')
        
        if bump_type not in ('PATCH', 'MINOR', 'MAJOR'):
            return jsonify({"ok": False, "error": f"无效 bump_type: {bump_type}"}), 400
        
        result = manual_bump(component, bump_type, reason)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# 导出蓝图
__all__ = ['collab_bus_bp']
