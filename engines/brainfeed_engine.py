#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 brainfeed_engine — brainfeed 中心的事件处理引擎
职责: 生成/处理中心系统事件, 维护事件类型和职责画像
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
    c = sqlite3.connect(_db())
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


# ── trigger handler 入口 (被 trigger_coordinator 调用) ──

def process_feed_complete(event_data: dict = None, **kwargs) -> dict:
    """BRAIN_FEED_COMPLETE 事件 → 记录到 evolution_log"""
    event_data = event_data or kwargs
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail, created_at)
            VALUES ('brainfeed', 'BRAIN_FEED_PROCESSED', ?, ?)""",
            (json.dumps(event_data, ensure_ascii=False)[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
        return {'ok': True, 'engine': 'brainfeed_engine', 'handler': 'process_feed_complete'}
    finally: c.close()


def on_health_changed(event_data: dict = None, **kwargs) -> dict:
    """SYSTEM_HEALTH_CHANGED 事件 → brainfeed 记录"""
    event_data = event_data or kwargs
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail, created_at)
            VALUES ('brainfeed', 'HEALTH_RECORDED', ?, ?)""",
            (json.dumps(event_data, ensure_ascii=False)[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
        return {'ok': True, 'engine': 'brainfeed_engine', 'handler': 'on_health_changed'}
    finally: c.close()


def record_center_event(event_data: dict = None, **kwargs) -> dict:
    """CENTER_EMPOWERED 事件 → brainfeed 记录"""
    event_data = event_data or kwargs
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail, created_at)
            VALUES ('brainfeed', 'CENTER_EVENT_RECORDED', ?, ?)""",
            (json.dumps(event_data, ensure_ascii=False)[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
        return {'ok': True, 'engine': 'brainfeed_engine', 'handler': 'record_center_event'}
    finally: c.close()


# ── 主动能力 ──

def list_event_types() -> list:
    """列出 brainfeed 已知的事件类型"""
    c = _conn()
    try:
        c.execute("SELECT DISTINCT trigger_event_type FROM mt_trigger_registry")
        return [r[0] for r in c.fetchall()]
    finally: c.close()


if __name__ == '__main__':
    print("🧠 brainfeed_engine 自检")
    print(f"   已知事件类型: {list_event_types()}")
    r = process_feed_complete({'test': True, 'ts': datetime.now().isoformat()})
    print(f"   process_feed_complete: {r}")
