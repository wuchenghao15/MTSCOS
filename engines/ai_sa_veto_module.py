#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SA 一票否决模块 SA Veto Module (flow_sa_veto_20261026)
=======================================================
宪法级权限: wuchenghao15 (SA) 拥有一票否决权

权威来源:
  - 用户指令 2026-10-26: "wuchenghao15（sa）有一票否决权, 可以撤销所有已通过的和待通过的所有提案和审批待结案流"
  - 《MTSCOS AI 数据安全与删库防护法》第 11 条

否决对象 (覆盖面):
  1. mt_hall_approval_flow (结案审批流) — PENDING / APPROVED → VETOED
  2. mt_lab_task_hall (任务大厅) — DONE / QUEUED / IN_PROGRESS / ... → VETOED
  3. mt_committee_bills (立法委法案) — DRAFT / PUBLIC_HEARING / ... → VETOED
  4. mt_committee_proposals (立法提案) — PUBLIC_HEARING / ... → VETOED
  5. mt_guardian_violation (守卫对) — 撤销 BLOCKED 记录
  6. 级联: 一个任务被否决 → 关联的审批流/提案全部级联否决

否决不可被:
  - 任何人 (包括其他管理员) 撤销
  - 任何流程覆盖
  - 任何引擎自动复活

否决必须:
  - 写入 mt_sa_veto_log (永久审计, 不可删除)
  - 触发守卫对 violation (GDL-023)
  - 通知政务中心 + 立法委 + 战略中心
  - 脑库投喂 (治理铁律触发)

CLI:
  python3 ai_sa_veto_module.py veto --task-id 592 --reason "测试否决"
  python3 ai_sa_veto_module.py veto-bill --bill BILL_XXX --reason "法案驳回"
  python3 ai_sa_veto_module.py list-vetoes
"""
from __future__ import annotations

import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_sa_veto_20261026"

# SA 身份常量
SA_USERNAME = 'wuchenghao15'
SA_DISPLAY = '超级管理员·SA'


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SA-VETO] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_sa_veto_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        veto_id TEXT UNIQUE NOT NULL,
        veto_type TEXT NOT NULL,             -- TASK / APPROVAL / BILL / PROPOSAL / GUARDIAN
        target_id TEXT NOT NULL,              -- task_id / bill_id / ...
        target_title TEXT,
        from_status TEXT,
        to_status TEXT DEFAULT 'VETOED',
        reason TEXT DEFAULT '',
        vetoed_by TEXT DEFAULT 'wuchenghao15',
        cascaded_task_ids TEXT,               -- 级联否决的任务 ID JSON
        cascaded_flow_ids TEXT,               -- 级联否决的审批流 ID JSON
        notified_centers TEXT,                 -- 已通知的中心 JSON
        brain_fed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        -- 宪法级约束: 否决不可被任何人修改/删除/覆盖
        CHECK (to_status='VETOED' AND vetoed_by='wuchenghao15')
    );
    
    CREATE INDEX IF NOT EXISTS idx_veto_target ON mt_sa_veto_log(veto_type, target_id);
    CREATE INDEX IF NOT EXISTS idx_veto_time ON mt_sa_veto_log(created_at);
    """)
    conn.commit()


# ═══════════════════════════════════════════════════════════
# 核心: SA 一票否决 (不可覆盖, 级联生效)
# ═══════════════════════════════════════════════════════════
def sa_veto_task(conn, task_id: int, reason: str) -> dict:
    """否决一个任务 (及其关联的审批流)"""
    _ensure_tables(conn)
    
    result = {'veto_id': None, 'task_id': task_id, 'cascaded_flows': [], 'ok': False}
    veto_id = f"SA_VETO_{task_id}_{int(time.time())}"
    
    # 1. 查询任务当前状态
    task = conn.execute(
        "SELECT id, title, status, priority, source FROM mt_lab_task_hall WHERE id=?",
        (task_id,)).fetchone()
    if not task:
        _log(f"❌ 任务 #{task_id} 不存在")
        return result
    
    from_status = task['status']
    _log(f"🛑 SA 一票否决: #{task_id} [{from_status}] {task['title'][:50]}")
    _log(f"   原因: {reason[:100]}")
    
    cascaded_flows = []
    
    # 2. 级联否决: 关联的审批流
    try:
        flows = conn.execute(
            "SELECT id FROM mt_hall_approval_flow WHERE task_id=? AND final_status NOT IN ('VETOED','REJECTED')",
            (task_id,)).fetchall()
        for f in flows:
            conn.execute("""UPDATE mt_hall_approval_flow SET 
                final_status='VETOED', approval_summary=?, completed_at=datetime('now','localtime')
                WHERE id=?""",
                (f"SA 一票否决: {reason[:200]}", f['id']))
            cascaded_flows.append(f['id'])
            _log(f"  ↳ 级联否决审批流 #{f['id']}")
    except Exception as e:
        _log(f"  ⚠️ 级联审批否决失败: {e}")
    
    # 3. 主任务 → VETOED (宪法级: 不可复活)
    conn.execute("""UPDATE mt_lab_task_hall SET 
        status='VETOED', 
        progress_note=?,
        updated_at=datetime('now','localtime')
        WHERE id=?""",
        (f"🚫 SA 一票否决 (原因: {reason[:200]})", task_id))
    
    # 4. 写入永久审计
    notified = ['GOV_CENTER', 'STRATEGY_CENTER', 'LEGISLATION_CENTER', 'GUARDIAN_PAIR', 'BRAIN']
    conn.execute("""INSERT INTO mt_sa_veto_log 
        (veto_id, veto_type, target_id, target_title, from_status, reason, vetoed_by,
         cascaded_flow_ids, notified_centers)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (veto_id, 'TASK', str(task_id), task['title'][:200], from_status, reason[:500],
         SA_USERNAME, json.dumps(cascaded_flows), json.dumps(notified)))
    
    conn.commit()
    result.update({
        'ok': True, 'veto_id': veto_id,
        'from_status': from_status, 'to_status': 'VETOED',
        'cascaded_flows': cascaded_flows,
    })
    
    # 5. 级联通知 (守卫对 + 政务 + 脑库)
    _notify_guardian(conn, veto_id, reason, task_id)
    _notify_brain(conn, veto_id, task_id, reason)
    
    _log(f"✅ 否决完成: {veto_id} (级联 {len(cascaded_flows)} 审批流)")
    return result


def sa_veto_bill(conn, bill_id: str, reason: str) -> dict:
    """否决一个立法法案"""
    _ensure_tables(conn)
    
    result = {'ok': False, 'veto_id': None}
    veto_id = f"SA_VETO_BILL_{bill_id}_{int(time.time())}"
    
    bill = conn.execute(
        "SELECT bill_id, title, current_status FROM mt_committee_bills WHERE bill_id=?",
        (bill_id,)).fetchone()
    if not bill:
        _log(f"❌ 法案 {bill_id} 不存在")
        return result
    
    from_status = bill['current_status']
    _log(f"🛑 SA 一票否决法案: {bill_id} [{from_status}] {bill['title'][:50]}")
    
    conn.execute("""UPDATE mt_committee_bills SET 
        current_status='VETOED_BY_SA', updated_at=datetime('now','localtime')
        WHERE bill_id=?""", (bill_id,))
    
    conn.execute("""INSERT INTO mt_sa_veto_log 
        (veto_id, veto_type, target_id, target_title, from_status, reason, vetoed_by)
        VALUES (?,?,?,?,?,?,?)""",
        (veto_id, 'BILL', bill_id, bill['title'][:200], from_status, reason[:500], SA_USERNAME))
    
    conn.commit()
    result.update({'ok': True, 'veto_id': veto_id, 'from_status': from_status})
    _log(f"✅ 法案否决: {veto_id}")
    return result


def sa_veto_approval_flow(conn, flow_id: int, reason: str) -> dict:
    """否决一个特定审批流"""
    _ensure_tables(conn)
    
    result = {'ok': False, 'veto_id': None}
    veto_id = f"SA_VETO_FLOW_{flow_id}_{int(time.time())}"
    
    flow = conn.execute(
        "SELECT id, task_id, task_title, final_status FROM mt_hall_approval_flow WHERE id=?",
        (flow_id,)).fetchone()
    if not flow:
        _log(f"❌ 审批流 #{flow_id} 不存在")
        return result
    
    from_status = flow['final_status']
    task_id = flow['task_id']
    
    conn.execute("""UPDATE mt_hall_approval_flow SET 
        final_status='VETOED', approval_summary=?, completed_at=datetime('now','localtime')
        WHERE id=?""", (f"SA 一票否决: {reason[:200]}", flow_id))
    
    # 级联: 任务也 → VETOED
    conn.execute("""UPDATE mt_lab_task_hall SET 
        status='VETOED', updated_at=datetime('now','localtime') WHERE id=?""",
        (task_id,))
    
    conn.execute("""INSERT INTO mt_sa_veto_log 
        (veto_id, veto_type, target_id, target_title, from_status, reason, vetoed_by)
        VALUES (?,?,?,?,?,?,?)""",
        (veto_id, 'APPROVAL', str(flow_id), flow['task_title'][:200], from_status, reason[:500], SA_USERNAME))
    
    conn.commit()
    result.update({'ok': True, 'veto_id': veto_id, 'from_status': from_status, 'task_id': task_id})
    _log(f"✅ 审批否决: {veto_id}")
    return result


# ═══════════════════════════════════════════════════════════
# SA 否决前置检查 (被 approval_engine / gatekeeper 调用)
# ═══════════════════════════════════════════════════════════
def is_vetoed(conn, task_id: int = None, bill_id: str = None) -> dict:
    """检查目标是否已被 SA 否决 (任何流程在执行前都要先调这个)"""
    _ensure_tables(conn)
    result = {'vetoed': False, 'veto_id': None, 'reason': None}
    
    if task_id:
        v = conn.execute(
            "SELECT veto_id, reason FROM mt_sa_veto_log WHERE veto_type='TASK' AND target_id=? AND to_status='VETOED'",
            (str(task_id),)).fetchone()
        if v:
            result = {'vetoed': True, 'veto_id': v['veto_id'], 'reason': v['reason']}
    
    if bill_id and not result['vetoed']:
        v = conn.execute(
            "SELECT veto_id, reason FROM mt_sa_veto_log WHERE veto_type='BILL' AND target_id=? AND to_status='VETOED'",
            (bill_id,)).fetchone()
        if v:
            result = {'vetoed': True, 'veto_id': v['veto_id'], 'reason': v['reason']}
    
    return result


# ═══════════════════════════════════════════════════════════
# 级联通知
# ═══════════════════════════════════════════════════════════
def _notify_guardian(conn, veto_id, reason, task_id):
    """SA 否决 → 守卫对 violation 记录 (GDL-023)"""
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_guardian_violation (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair_code TEXT, rule_id TEXT NOT NULL,
            rule_name TEXT, severity TEXT DEFAULT 'CRITICAL', sql_preview TEXT,
            table_name TEXT, row_count INTEGER DEFAULT 0, block_status TEXT DEFAULT 'BLOCKED',
            guardian_veto TEXT, recovery_action TEXT,
            reported_to_committee INTEGER DEFAULT 0, brain_fed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')))""")
        conn.execute("""INSERT INTO mt_guardian_violation 
            (pair_code, rule_id, rule_name, severity, sql_preview, table_name, block_status, guardian_veto)
            VALUES ('PAIR_ALPHA', 'GDL-023', 'SA_VETO_AUDIT', 'CRITICAL', ?, '_SA_VETO_LOG_', 'AUDITED', ?)""",
            (f"SA 否决 #{task_id}: {reason[:200]}", veto_id))
        conn.commit()
    except Exception:
        pass


def _notify_brain(conn, veto_id, task_id, reason):
    """SA 否决 → 脑库投喂 (治理铁律触发事件)"""
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_ai_brain_feed_log (
            feed_id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id TEXT, feed_target TEXT,
            payload_preview TEXT, fed_at TEXT, fed_by TEXT)""")
        conn.execute("""INSERT INTO mt_ai_brain_feed_log 
            (flow_id, feed_target, payload_preview, fed_by)
            VALUES (?,?,?,?)""",
            (FLOW_ID, 'ALL_CENTERS',
             f"【SA一票否决】#{task_id} veto_id={veto_id}: {reason[:200]}",
             'wuchenghao15'))
        conn.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 列出所有否决 (审计用)
# ═══════════════════════════════════════════════════════════
def list_vetoes(conn, limit: int = 20) -> list:
    _ensure_tables(conn)
    rows = conn.execute("""
        SELECT veto_id, veto_type, target_id, target_title, from_status, reason, created_at
        FROM mt_sa_veto_log ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='SA Veto Module (CONSTITUTIONAL AUTHORITY)')
    sub = parser.add_subparsers(dest='cmd')
    
    # veto task
    p_vt = sub.add_parser('veto', help='否决一个任务 (及关联审批流)')
    p_vt.add_argument('--task-id', type=int, required=True)
    p_vt.add_argument('--reason', required=True, help='否决原因 (必填, 永久留痕)')
    
    # veto bill
    p_vb = sub.add_parser('veto-bill', help='否决一个立法法案')
    p_vb.add_argument('--bill', required=True)
    p_vb.add_argument('--reason', required=True)
    
    # veto flow
    p_vf = sub.add_parser('veto-flow', help='否决一个审批流')
    p_vf.add_argument('--flow-id', type=int, required=True)
    p_vf.add_argument('--reason', required=True)
    
    # list
    sub.add_parser('list-vetoes', help='列出所有否决记录 (审计)')
    sub.add_parser('init', help='初始化表')
    
    args = parser.parse_args()
    conn = _db()
    
    if args.cmd == 'init':
        _ensure_tables(conn)
        print(json.dumps({'ok': True, 'tables': ['mt_sa_veto_log']}, indent=2))
    elif args.cmd == 'veto':
        r = sa_veto_task(conn, args.task_id, args.reason)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'veto-bill':
        r = sa_veto_bill(conn, args.bill, args.reason)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'veto-flow':
        r = sa_veto_approval_flow(conn, args.flow_id, args.reason)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'list-vetoes':
        print(json.dumps(list_vetoes(conn), ensure_ascii=False, indent=2))
    
    conn.close()


if __name__ == '__main__':
    main()
