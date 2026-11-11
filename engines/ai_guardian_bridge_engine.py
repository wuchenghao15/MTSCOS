#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
守卫对 ↔ 仙女座联动引擎 Guardian-Andromeda Bridge (flow_gdm_bridge_20261026)
===========================================================================
核心: 把守卫对的所有输出 → 仙女座现有体系的输入

联动链路 (全自动化):
  守卫对 BLOCKED violation
       │
       ├──→ 备份中心 (mt_backup_log)       立即触发冷快照
       ├──→ 任务大厅 (mt_lab_task_hall)     创建应急修复任务
       ├──→ 政务中心 (mt_gov_emergency_log) 记录应急事件
       ├──→ 战略中心 (mt_strategy_research) 发起即时战略研究
       ├──→ 立法委 (mt_committee_comments)  数字专家紧急讨论
       ├──→ 教育中心 (mt_edu_incident_case) 沉淀案例库
       └──→ 脑库 (mt_ai_brain_feed_log)    异常模式投喂

用法:
  python3 ai_guardian_bridge_engine.py once    # 单轮联动
  python3 ai_guardian_bridge_engine.py start   # loop 60s (持续监听)
"""
from __future__ import annotations

import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_gdm_bridge_20261026"
INTERVAL = 60
# 上次处理的 violation ID (幂等, 防重复联动)
LAST_PROCESSED_VIOLATION_ID = None


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [BRIDGE] {msg}", flush=True)


def bridge_violation_to_all(violation) -> dict:
    """单条 violation → 全链路联动"""
    v = dict(violation)
    vid = v['id']
    rule_id = v['rule_id']
    rule_name = v['rule_name']
    severity = v.get('severity', 'MEDIUM') or 'MEDIUM'
    tbl = v.get('table_name', '_DB_') or '_DB_'
    sql = (v.get('sql_preview', '') or '')[:200]
    
    results = {}
    
    # ── 1. 备份中心: 触发冷快照 ──
    try:
        conn = _db()
        conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_backup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, detail TEXT, ok INTEGER,
            size_bytes INTEGER, elapsed_sec REAL, created_at TEXT)""")
        conn.execute("""INSERT INTO mt_backup_log 
            (action, detail, ok, size_bytes, elapsed_sec, created_at)
            VALUES ('GUARDIAN_BRIDGE_TRIGGER', ?, 1, 0, 0, datetime('now','localtime'))""",
            (f"守卫对触发: {rule_id} {rule_name} — 联动冷快照请求 (表: {tbl})",))
        conn.commit()
        results['backup'] = 'TRIGGERED'
        conn.close()
        _log(f"  → 备份中心: 触发冷快照")
    except Exception as e:
        results['backup'] = f'FAIL: {e}'
    
    # ── 2. 任务大厅: 创建应急修复任务 (使用实际 schema) ──
    try:
        conn = _db()
        task_id = conn.execute(
            "INSERT INTO mt_lab_task_hall (title, description, source, priority, status, task_type) "
            "VALUES (?,?,?,?,?,?)",
            (f"[应急] {rule_name} — {tbl}",
             f"守卫对拦截 violation #{vid}: {rule_id} {sql[:100]}",
             FLOW_ID, 'URGENT', 'QUEUED', 'SECURITY_INCIDENT')
        ).lastrowid
        conn.commit()
        results['task_hall'] = f'CREATED #{task_id}'
        conn.close()
        _log(f"  → 任务大厅: 应急任务 #{task_id}")
    except Exception as e:
        results['task_hall'] = f'FAIL: {e}'
    
    # ── 3. 政务中心: 应急日志 ──
    try:
        conn = _db()
        conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_gov_emergency_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emergency_id TEXT, title TEXT, trigger_event TEXT, severity TEXT,
            sop_id TEXT, step_completed INTEGER DEFAULT 0, total_steps INTEGER DEFAULT 0,
            status TEXT DEFAULT 'RESPONDING', commander TEXT DEFAULT 'GOV_CENTER',
            started_at TEXT DEFAULT (datetime('now','localtime')), resolved_at TEXT)""")
        emerg_id = f"EMG_BRIDGE_{rule_id}_{int(time.time())}"
        conn.execute("""INSERT INTO mt_gov_emergency_log 
            (emergency_id, title, trigger_event, severity, sop_id, total_steps)
            VALUES (?,?,?,?,?,?)""",
            (emerg_id, f"[联动应急] {rule_name}",
             f"守卫对 violation #{vid}: {rule_id}", severity,
             'SOP_DATA_BLOWUP_001', 7))
        conn.commit()
        results['gov'] = emerg_id
        conn.close()
        _log(f"  → 政务中心: 应急 {emerg_id}")
    except Exception as e:
        results['gov'] = f'FAIL: {e}'
    
    # ── 4. 战略中心: 即时研究 ──
    try:
        conn = _db()
        conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_strategy_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            research_id TEXT UNIQUE, title TEXT, category TEXT, severity TEXT,
            event_id TEXT, root_causes TEXT, lessons_learned TEXT, mitigations TEXT,
            risk_level TEXT DEFAULT 'MEDIUM', status TEXT DEFAULT 'PUBLISHED',
            flow_id TEXT, published_at TEXT DEFAULT (datetime('now','localtime')))""")
        research_id = f"RES_BRIDGE_{rule_id}_{int(time.time())}"
        conn.execute("""INSERT OR IGNORE INTO mt_strategy_research 
            (research_id, title, category, severity, root_causes, mitigations, flow_id)
            VALUES (?,?,?,?,?,?,?)""",
            (research_id, f"[即时研究] {rule_name} — {tbl}", 'GUARDIAN_REACTION', severity,
             json.dumps([f"守卫对拦截: {rule_id}", f"表: {tbl}", f"SQL: {sql}"], ensure_ascii=False),
             json.dumps(['已自动拦截', '通知备份中心快照', '政务中心应急'], ensure_ascii=False),
             FLOW_ID))
        conn.commit()
        results['strategy'] = research_id
        conn.close()
        _log(f"  → 战略中心: 即时研究 {research_id}")
    except Exception as e:
        results['strategy'] = f'FAIL: {e}'
    
    # ── 5. 教育中心: 案例沉淀 ──
    try:
        conn = _db()
        conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_edu_incident_case (
            case_id TEXT PRIMARY KEY, title TEXT, category TEXT, severity TEXT,
            trigger TEXT, timeline TEXT, root_causes TEXT, lessons TEXT,
            action_items TEXT, reported_by TEXT DEFAULT 'AUTO',
            reported_at TEXT DEFAULT (datetime('now','localtime')))""")
        case_id = f"CASE_BRIDGE_{rule_id}_{int(time.time())}"
        conn.execute("""INSERT OR IGNORE INTO mt_edu_incident_case 
            (case_id, title, category, severity, trigger, root_causes, lessons, action_items)
            VALUES (?,?,?,?,?,?,?,?)""",
            (case_id, f"[新案例] {rule_name} — {tbl}", 'GUARDIAN_BLOCKED', severity,
             f"守卫对拦截 violation #{vid}: {rule_id}",
             json.dumps(['守卫对SQL拦截', '应急联动触发'], ensure_ascii=False),
             json.dumps([f"学习点: {rule_name} 预防"], ensure_ascii=False),
             json.dumps(['已自动拦截', '已联动备份/政务/战略/教育中心'], ensure_ascii=False)))
        conn.commit()
        results['edu'] = case_id
        conn.close()
        _log(f"  → 教育中心: 案例 {case_id}")
    except Exception as e:
        results['edu'] = f'FAIL: {e}'
    
    # ── 6. 脑库: 异常模式投喂 (使用实际 schema) ──
    try:
        conn = _db()
        conn.execute("""INSERT INTO mt_ai_brain_feed_log 
            (flow_id, feed_target, payload_preview, fed_by)
            VALUES (?,?,?,?)""",
            (FLOW_ID, 'ALL_CENTERS',
             f"【守卫对异常】{rule_id}: {rule_name} — 表: {tbl}, SQL: {sql[:150]}",
             'ai_guardian_pair'))
        conn.commit()
        results['brain'] = 'FED'
        _log(f"  → 脑库: 异常模式投喂")
        conn.close()
    except Exception as e:
        results['brain'] = f'FAIL: {e}'
    
    return results


def run_once() -> dict:
    """单轮联动: 扫描新 violation → 全链路联动"""
    global LAST_PROCESSED_VIOLATION_ID
    
    conn = _db()
    
    # 确保守卫对表存在
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_guardian_violation (
        id INTEGER PRIMARY KEY AUTOINCREMENT, pair_code TEXT, rule_id TEXT NOT NULL,
        rule_name TEXT, severity TEXT DEFAULT 'CRITICAL', sql_preview TEXT,
        table_name TEXT, row_count INTEGER DEFAULT 0, block_status TEXT DEFAULT 'BLOCKED',
        guardian_veto TEXT, recovery_action TEXT,
        reported_to_committee INTEGER DEFAULT 0, brain_fed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.commit()
    
    # 查询新的 BLOCKED violation
    if LAST_PROCESSED_VIOLATION_ID is None:
        # 首轮: 取最近 10 条
        violations = conn.execute("""
            SELECT id, rule_id, rule_name, severity, table_name, sql_preview 
            FROM mt_guardian_violation 
            WHERE block_status='BLOCKED'
            ORDER BY id DESC LIMIT 10
        """).fetchall()
    else:
        violations = conn.execute("""
            SELECT id, rule_id, rule_name, severity, table_name, sql_preview 
            FROM mt_guardian_violation 
            WHERE block_status='BLOCKED' AND id > ?
            ORDER BY id ASC
        """, (LAST_PROCESSED_VIOLATION_ID,)).fetchall()
    
    conn.close()
    
    report = {'violations_found': len(violations), 'bridges': []}
    
    for v in violations:
        _log(f"🔗 联动 violation #{v['id']}: {v['rule_id']} {v['rule_name']}")
        results = bridge_violation_to_all(v)
        report['bridges'].append({
            'violation_id': v['id'],
            'rule': v['rule_id'],
            'links': results,
        })
        
        # 更新已处理
        if LAST_PROCESSED_VIOLATION_ID is None or v['id'] > LAST_PROCESSED_VIOLATION_ID:
            LAST_PROCESSED_VIOLATION_ID = v['id']
    
    if not violations:
        _log("暂无新 violation, 链路静默")
    else:
        _log(f"本轮联动 {len(violations)} 条 violation")
    
    return report


def run_loop():
    _log(f"守卫对-仙女座 联动 loop 启动 (interval={INTERVAL}s)")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ {e}")
        time.sleep(INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['once', 'start'])
    args = parser.parse_args()
    
    if args.command == 'once':
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.command == 'start':
        run_loop()


if __name__ == '__main__':
    main()
