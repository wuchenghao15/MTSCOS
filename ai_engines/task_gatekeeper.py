#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务大厅唯一入口校验器 Task Gatekeeper (flow_task_gatekeeper_20261026)
=======================================================================
MTSCOS AI 治理铁律: 所有新要求/新任务/新需求必须先入任务大厅 (mt_lab_task_hall),
否则拒绝执行并落库告警。

机制:
  ┌──────────┐     has_task_in_hall()     ┌───────────────┐
  │ 新要求   │ ──────────────────────────▶ │ YES → 放行执行 │
  └────┬─────┘                              └───────────────┘
       │
       │ NO
       ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │ 自动创建任务  │───▶│ 落库 violation│───▶│ 守卫对告警    │
  │ (status=QUEUED)│   │ mt_gatekeeper │   │ mt_guardian_  │
  └──────────────┘    │ _violation    │   │ violation    │
                       └──────────────┘    └──────────────┘

三表:
  mt_gatekeeper_violation   — 违规执行记录 (永久审计)
  mt_gatekeeper_log         — 正常通过日志
  (复用 mt_lab_task_hall)   — 任务唯一入口

CLI:
  python3 task_gatekeeper.py submit "任务标题" "任务描述"  # 提交新任务到大厅
  python3 task_gatekeeper.py check <task_id>               # 检查任务是否合法
  python3 task_gatekeeper.py stats                          # 统计
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_task_gatekeeper_20261026"

# 允许绕过的来源 (极少数白名单)
_ALLOWED_SOURCES = {'system_repair', 'auto_daemon'}
# 守卫对来源 (自动联动)
_GUARDIAN_SOURCES = {'flow_gdm_bridge_20261026', 'flow_guardian_pair_20261026'}


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [GATE] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_gatekeeper_violation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        violation_type TEXT,          -- 'NO_TASK_ID' / 'STATUS_NOT_QUEUED' / 'BYPASS_ATTEMPT'
        task_id INTEGER,
        title TEXT,
        source TEXT,
        caller TEXT,
        severity TEXT DEFAULT 'HIGH',
        auto_created_task INTEGER DEFAULT 0,
        notified_to_guardian INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_gatekeeper_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        title TEXT,
        source TEXT,
        call_ok INTEGER DEFAULT 1,
        checked_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


# ═══════════════════════════════════════════════════════════
# 核心: 提交新要求 → 任务大厅唯一入口
# ═══════════════════════════════════════════════════════════
def submit_to_hall(title: str, description: str, source: str = 'user_directive',
                   priority: str = 'HIGH', task_type: str = 'GENERAL') -> int:
    """提交新要求 → 任务大厅 (唯一合法入口)"""
    conn = _db()
    _ensure_tables(conn)
    
    # 幂等: 相同标题在 10min 内不重复
    recent = conn.execute("""
        SELECT id FROM mt_lab_task_hall 
        WHERE title=? AND created_at > datetime('now','localtime','-10 minutes')
        LIMIT 1
    """, (title,)).fetchone()
    if recent:
        conn.close()
        _log(f"⏭️ 幂等跳过: 任务 #{recent['id']} 10min 内已存在")
        return recent['id']
    
    cur = conn.execute("""INSERT INTO mt_lab_task_hall 
        (title, description, source, priority, status, task_type, created_at)
        VALUES (?,?,?,?, 'QUEUED', ?, datetime('now','localtime'))""",
        (title, description[:1000], source, priority, task_type))
    task_id = cur.lastrowid
    
    conn.execute("""INSERT INTO mt_gatekeeper_log 
        (task_id, title, source, call_ok) VALUES (?,?,?, 1)""",
        (task_id, title[:200], source))
    conn.commit()
    conn.close()
    
    _log(f"✅ 任务大厅唯一入口: #{task_id} [{priority}] {title[:60]}")
    return task_id


# ═══════════════════════════════════════════════════════════
# 核心: 校验调用方是否在任务大厅有合法任务
# ═══════════════════════════════════════════════════════════
def can_proceed(caller: str, source: str, task_id: int = None,
                required_task_type: str = None) -> dict:
    """
    校验调用方是否可以执行
    
    返回: {'ok': bool, 'reason': str, 'task_id': int}
    """
    conn = _db()
    _ensure_tables(conn)
    
    result = {'ok': False, 'reason': '', 'task_id': None}
    
    # 1. 白名单来源放行
    if source in _ALLOWED_SOURCES:
        result = {'ok': True, 'reason': f'白名单来源: {source}', 'task_id': None}
    # 2. 守卫对联动放行
    elif source in _GUARDIAN_SOURCES:
        result = {'ok': True, 'reason': f'守卫对联动: {source}', 'task_id': None}
    elif task_id:
        task = conn.execute("""
            SELECT id, title, status, source, priority FROM mt_lab_task_hall WHERE id=?
        """, (task_id,)).fetchone()

        # 🔧 P0-3 flow_hall_p0_fix_20261026: 状态机活跃态全部放行 —
        #   任务入厅后由 10 状态机流转 (QUEUED/NEW→...→DISPATCHED), 校验只认"未终局"
        _HALL_ACTIVE_STATUSES = ('QUEUED', 'NEW', 'PEACEKEEPER_REVIEW', 'PEACEKEEPER_APPROVED',
                                 'KEYWORD_SPLIT', 'DISPATCHED', 'CLAIMED', 'ACCEPTED',
                                 'IN_PROGRESS', 'BACK_TO_CENTER')
        if not task:
            result = {'ok': False, 'reason': f'任务 #{task_id} 不存在', 'task_id': task_id}
        elif task['status'] not in _HALL_ACTIVE_STATUSES:
            result = {'ok': False, 'reason': f"任务 #{task_id} 状态={task['status']}, 不可执行", 'task_id': task_id}
        else:
            result = {'ok': True, 'reason': f"任务大厅合法: #{task_id} [{task['status']}]", 'task_id': task_id}
    # 4. 无 task_id → 检查近期已 QUEUED 的同来源任务
    else:
        recent = conn.execute("""
            SELECT id FROM mt_lab_task_hall 
            WHERE source=? AND status IN ('QUEUED','DISPATCHED','ACCEPTED','IN_PROGRESS')
            ORDER BY id DESC LIMIT 1
        """, (source,)).fetchone()
        if recent:
            result = {'ok': True, 'reason': f'同来源有活跃任务 #{recent["id"]}', 'task_id': recent['id']}
        else:
            # ❌ 拦截: 无合法 task_id → 记录违规 + 自动创建任务
            _log(f"🚫 拦截: caller={caller}, source={source} — 无任务大厅记录!")
            
            conn.execute("""INSERT INTO mt_gatekeeper_violation 
                (violation_type, title, source, caller, severity, auto_created_task)
                VALUES (?,?,?,?,?,?)""",
                ('NO_TASK_ID', f'[自动创建] {caller} 要求的新任务', source, caller, 'HIGH', 1))
            
            # 自动创建任务 → 让调用方可以在下一步执行
            cur = conn.execute("""INSERT INTO mt_lab_task_hall 
                (title, description, source, priority, status, task_type)
                VALUES (?,?,?,?, 'QUEUED', 'AUTO_GATEKEEPER')""",
                (f'[Gatekeeper自动创建] {caller} — 无任务大厅入口的执行请求',
                 f'调用方 {caller} 在无合法 task_id 的情况下尝试执行, 被 gatekeeper 拦截后自动创建任务。source={source}',
                 source, 'HIGH'))
            auto_task_id = cur.lastrowid
            conn.commit()
            result = {'ok': False, 
                     'reason': f'🚫 无合法任务大厅入口 → 已自动创建任务 #{auto_task_id}, 请等待任务被认领后再执行',
                     'task_id': auto_task_id}
    
    conn.execute("""INSERT INTO mt_gatekeeper_log 
        (task_id, title, source, call_ok) VALUES (?,?,?,?)""",
        (result.get('task_id'), caller[:100], source, 1 if result['ok'] else 0))
    conn.commit()
    conn.close()
    
    return result


# ═══════════════════════════════════════════════════════════
# 违规自动上报守卫对
# ═══════════════════════════════════════════════════════════
def report_to_guardian(violation_type: str, detail: str) -> bool:
    """拦截事件 → 守卫对 violation 表"""
    try:
        conn = _db()
        # 确保守卫对表存在
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_guardian_violation (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair_code TEXT, rule_id TEXT NOT NULL,
            rule_name TEXT, severity TEXT DEFAULT 'CRITICAL', sql_preview TEXT,
            table_name TEXT, row_count INTEGER DEFAULT 0, block_status TEXT DEFAULT 'BLOCKED',
            guardian_veto TEXT, recovery_action TEXT,
            reported_to_committee INTEGER DEFAULT 0, brain_fed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')))""")
        conn.execute("""INSERT INTO mt_guardian_violation 
            (pair_code, rule_id, rule_name, severity, sql_preview, table_name, block_status)
            VALUES ('PAIR_ALPHA', 'GDL-022', ?, 'HIGH', ?, '_GATEKEEPER_', 'BLOCKED')""",
            (f"GATEKEEPER_BYPASS_{violation_type}", detail[:300]))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _log(f"⚠️ 上报守卫对失败: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# 统计
# ═══════════════════════════════════════════════════════════
def get_stats() -> dict:
    conn = _db()
    _ensure_tables(conn)
    stats = {
        'violations': conn.execute("SELECT COUNT(*) c FROM mt_gatekeeper_violation").fetchone()['c'],
        'auto_created': conn.execute("SELECT COUNT(*) c FROM mt_gatekeeper_violation WHERE auto_created_task=1").fetchone()['c'],
        'passes': conn.execute("SELECT COUNT(*) c FROM mt_gatekeeper_log WHERE call_ok=1").fetchone()['c'],
        'blocks': conn.execute("SELECT COUNT(*) c FROM mt_gatekeeper_log WHERE call_ok=0").fetchone()['c'],
        'recent_violations': [],
    }
    rows = conn.execute("""
        SELECT violation_type, title, source, caller, created_at 
        FROM mt_gatekeeper_violation ORDER BY id DESC LIMIT 5
    """).fetchall()
    stats['recent_violations'] = [dict(r) for r in rows]
    conn.close()
    return stats


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='Task Gatekeeper')
    sub = parser.add_subparsers(dest='cmd')
    
    # submit
    p_sub = sub.add_parser('submit', help='提交新要求到任务大厅 (唯一合法入口)')
    p_sub.add_argument('title')
    p_sub.add_argument('--desc', default='', help='任务描述')
    p_sub.add_argument('--source', default='user_directive')
    p_sub.add_argument('--priority', default='HIGH')
    p_sub.add_argument('--type', default='GENERAL')
    
    # check
    p_chk = sub.add_parser('check', help='检查任务是否合法')
    p_chk.add_argument('--task-id', type=int, default=None)
    p_chk.add_argument('--caller', default='unknown')
    p_chk.add_argument('--source', default='unknown')
    
    # stats
    sub.add_parser('stats', help='统计')
    
    args = parser.parse_args()
    
    if args.cmd == 'submit':
        tid = submit_to_hall(args.title, args.desc, args.source, args.priority, args.type)
        print(json.dumps({'task_id': tid, 'ok': True}, indent=2))
    elif args.cmd == 'check':
        r = can_proceed(args.caller, args.source, args.task_id)
        if not r['ok']:
            # 上报守卫对
            report_to_guardian(r['reason'][:50], f'caller={args.caller}, source={args.source}')
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'stats':
        print(json.dumps(get_stats(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
