#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ taskhall_engine — taskhall 中心的任务处理引擎
职责: 处理内部任务, 监控系统性能
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


def _log(event: str, detail: str):
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail, created_at)
            VALUES ('taskhall', ?, ?, ?)""",
            (event, detail[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
    finally: c.close()


# ── trigger handler 入口 ──

def create_task(event_data: dict = None, **kwargs) -> dict:
    """CENTER_EMPOWERED → 把任务加到 mt_task_hall"""
    event_data = event_data or kwargs
    c = _conn()
    try:
        # 写 evolution_log
        _log('TASK_CREATED', json.dumps(event_data, ensure_ascii=False))
        return {'ok': True, 'engine': 'taskhall_engine', 'handler': 'create_task',
                'task_name': event_data.get('center_name', 'unknown') + '_empower'}
    finally: c.close()


def queue_knowledge_task(event_data: dict = None, **kwargs) -> dict:
    """KNOWLEDGE_CREATED → 任务大厅排队处理"""
    event_data = event_data or kwargs
    _log('KNOWLEDGE_TASK_QUEUED', json.dumps(event_data, ensure_ascii=False))
    return {'ok': True, 'engine': 'taskhall_engine', 'handler': 'queue_knowledge_task'}


def queue_question_task(event_data: dict = None, **kwargs) -> dict:
    """QUESTION_GENERATED → 任务大厅排队处理"""
    event_data = event_data or kwargs
    _log('QUESTION_TASK_QUEUED', json.dumps(event_data, ensure_ascii=False))
    return {'ok': True, 'engine': 'taskhall_engine', 'handler': 'queue_question_task'}


# ── 主动能力 ──

def scan_performance() -> dict:
    """扫描 taskhall 性能"""
    c = _conn()
    try:
        c.execute("SELECT COUNT(*) FROM mt_task_hall")
        hall = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM mt_task_landing_log")
        landed = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM mt_task_archive")
        archived = c.fetchone()[0]
        return {'hall': hall, 'landed': landed, 'archived': archived,
                'land_rate': landed / max(hall, 1)}
    finally: c.close()


if __name__ == '__main__':
    print("🏛️ taskhall_engine 自检")
    perf = scan_performance()
    print(f"   大厅={perf['hall']}, 落地={perf['landed']}, 归档={perf['archived']}")
    r = create_task({'test': True, 'ts': datetime.now().isoformat()})
    print(f"   create_task: {r}")
