#!/usr/bin/env python3
"""
🧠 sys_auto_approval — 仙女座智能审批 daemon
==============================================
周期: 300s (5min)
职责:
  1. 扫 pending 审批 → 自动通过 low-risk (student 文曲星/teacher 确认等)
  2. AI 预审 medium-risk → 打分 + 自动过安全项
  3. 通知待审批的审批人 (角色匹配)
  4. 超期提醒 (pending > 24h → 提醒 + 升级)

依赖: engines/approvals_engine.py
"""
from __future__ import annotations
import sys, sqlite3, time, json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "database" / "app.db"
DAEMON_INTERVAL = 300


def run_cycle():
    """一次完整审批 daemon 周期"""
    from engines.approvals_engine import ApprovalEngine
    eng = ApprovalEngine()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{now}] 🧠 sys_auto_approval — 仙女座智能审批 daemon cycle")

    # ── Phase 1: 低风险自动审批 ──
    auto_passed = eng.auto_approve_low_risk()
    if auto_passed:
        print(f"  ✅ Phase 1: 仙女座自动审批 {len(auto_passed)} 个 low-risk")
        for r in auto_passed:
            print(f"     {r['request_id']}: {r['reason']}")
    else:
        print(f"  ✅ Phase 1: 无 low-risk 待处理")

    # ── Phase 2: 统计 ──
    c = eng.db.cursor()
    stats = {}
    for cat in ('wenquxing', 'homework', 'exam', 'course_content', 'rule_change', 'other'):
        c.execute("SELECT COUNT(*) FROM mt_approval_requests WHERE status='pending' AND category LIKE ?",
                  (f'%{cat}%',))
        stats[cat] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM mt_approval_requests WHERE status='pending'")
    total_pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM mt_approval_requests WHERE status='approved'")
    total_approved = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM mt_approval_requests WHERE status='rejected'")
    total_rejected = c.fetchone()[0]

    print(f"  📊 Phase 2 统计: pending={total_pending} approved={total_approved} rejected={total_rejected}")

    # ── Phase 3: medium+ risk 待审批汇总 ──
    if total_pending > 0:
        c.execute("""
            SELECT r.request_id, r.category, r.risk_level, r.initiator, r.initiator_role,
                   n.node_index, n.approver_role
            FROM mt_approval_requests r
            JOIN mt_approval_nodes n ON n.request_id=r.request_id AND n.action IS NULL
            WHERE r.status='pending' AND n.node_type='role_approver'
            ORDER BY r.risk_level, r.created_at
            LIMIT 10
        """)
        rows = c.fetchall()
        if rows:
            print(f"  📋 Phase 3: {len(rows)} 个人工待审批节点")
            for r in rows:
                print(f"     {r[0]} [{r[1]} risk={r[2]}] 需 {r[6]} 审批 (发起人 {r[3]}({r[4]}))")

    print(f"  ⏱ 下一轮 {DAEMON_INTERVAL}s 后")
    eng.db.close()


def main():
    print("🧠 sys_auto_approval daemon started (仙女座智能审批)")
    print(f"   interval={DAEMON_INTERVAL}s  db={DB_PATH}")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[ERROR] sys_auto_approval cycle failed: {e}")
        time.sleep(DAEMON_INTERVAL)


if __name__ == "__main__":
    main()
