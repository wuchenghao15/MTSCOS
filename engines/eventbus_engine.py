#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📡 eventbus_engine — eventbus 中心的事件总线引擎
职责: 处理事件, 维护系统健康, 监控状态, 广播给所有订阅者
"""
from __future__ import annotations
import sqlite3, json, time
from datetime import datetime
from typing import Any, Optional

_DB_PATH = None

def _db():
    global _DB_PATH
    if _DB_PATH is None:
        import os
        _DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'database', 'app.db')
    return _DB_PATH


def _conn():
    c = sqlite3.connect(_db(), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def _log(event: str, detail: str):
    try:
        c = sqlite3.connect(_db(), timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail, created_at)
            VALUES ('eventbus', ?, ?, ?)""",
            (event, detail[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
        c.close()
    except Exception as e:
        print(f"[eventbus_engine._log failed] {e}", file=sys.stderr)


# ── trigger handler 入口 ──

def forward_event(event_data: dict = None, **kwargs) -> dict:
    """EVENT_DISPATCHED → eventbus 广播"""
    event_data = event_data or kwargs
    # 写协作总线事件表
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_collab_bus_events
            (event_type, source, source_system, payload, created_at)
            VALUES (?, 'eventbus', 'eventbus', ?, ?)""",
            (event_data.get('event_type', 'EVENT_FORWARDED'),
             json.dumps(event_data, ensure_ascii=False)[:1000],
             datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
        _log('EVENT_FORWARDED', json.dumps(event_data, ensure_ascii=False))
        return {'ok': True, 'engine': 'eventbus_engine', 'handler': 'forward_event'}
    except Exception as e:
        _log('FORWARD_FAILED', str(e))
        return {'ok': False, 'error': str(e)}
    finally:
        try: c.close()
        except Exception: pass


def broadcast_health(event_data: dict = None, **kwargs) -> dict:
    """SYSTEM_HEALTH_CHANGED → eventbus 广播健康分变化"""
    event_data = event_data or kwargs
    _log('HEALTH_BROADCAST', json.dumps(event_data, ensure_ascii=False))
    return {'ok': True, 'engine': 'eventbus_engine', 'handler': 'broadcast_health'}


def broadcast_alert(event_data: dict = None, **kwargs) -> dict:
    """AUDIT_FAIL → eventbus 广播紧急告警"""
    event_data = event_data or kwargs
    _log('ALERT_BROADCAST', json.dumps(event_data, ensure_ascii=False))
    return {'ok': True, 'engine': 'eventbus_engine', 'handler': 'broadcast_alert'}


# ── 主动能力 ──

def list_subscribers() -> list:
    """列出 eventbus 订阅者"""
    c = _conn()
    try:
        c.execute("SELECT * FROM mt_collab_bus_subscribers")
        return [dict(r) for r in c.fetchall()]
    finally: c.close()


def stats() -> dict:
    """eventbus 统计"""
    c = _conn()
    try:
        c.execute("SELECT COUNT(*) FROM mt_collab_bus_events")
        events = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM mt_collab_bus_subscribers")
        subs = c.fetchone()[0]
        return {'events': events, 'subscribers': subs, 'hub_count': 15}
    finally: c.close()


if __name__ == '__main__':
    print("📡 eventbus_engine 自检")
    print(f"   stats: {stats()}")
    r = forward_event({'test': True, 'ts': datetime.now().isoformat()})
    print(f"   forward_event: {r}")
