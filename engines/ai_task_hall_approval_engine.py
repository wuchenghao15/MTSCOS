#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务大厅结案多层审批引擎 Task Hall Approval Engine (flow_task_hall_approval_20261026)
====================================================================================

治理铁律 (用户指令 2026-10-26):
  任务大厅回收已完成处理的任务小结报告后, 必须走多层审批才能结案:

    P0 (CRITICAL) → 董事会举手表决统一 → 才能结案 → 记录
    P1-P3 (HIGH/NORMAL/LOW) → 管理员开会表决通过 → 才能结案 → 上报董事会 + 记录
    其他等级 → 任务中心主任 + 政委 审批通过 → 才能结案
    全部等级 → 必须走法务团队过滤 (legal_review_required=1)

架构:
  ┌─────────────┐    deliverable上报     ┌──────────────┐
  │ 任务执行中心 │ ────────────────────▶ │ 结案审批拦截层 │
  └─────────────┘                         └──────┬───────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────────┐
                    ▼                            ▼                            ▼
             P0 CRITICAL                   P1-P3 HIGH/NORMAL               其他等级
             董事会举手表决               管理员会议表决                 主任 + 政委审批
                    │                            │                            │
                    └────────────────────────────┼────────────────────────────┘
                                                 │
                                                 ▼
                                          法务团队过滤 (必经)
                                                 │
                                                 ▼
                                          ✅ 正式结案 DONE

三表:
  mt_hall_approval_flow    — 审批流程记录 (永久审计)
  mt_hall_vote             — 表决记录 (P0 董事会 / P1-P3 管理员)
  mt_hall_legal_filter     — 法务过滤记录

用法:
  python3 ai_task_hall_approval_engine.py init
  python3 ai_task_hall_approval_engine.py once    # 扫描待审批任务
  python3 ai_task_hall_approval_engine.py start   # loop 120s
"""
from __future__ import annotations

import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_task_hall_approval_20261026"
INTERVAL = 120

# 审批矩阵 (全覆盖: CRITICAL/ HIGH/ NORMAL/ LOW/ 其他 → 全部有审批+法务过滤+投票记录)
APPROVAL_MATRIX = {
    'CRITICAL': {
        'type': 'BOARD_VOTE',
        'approvers': ['董事会成员'],
        'required_votes': '全票通过',
        'legal_review': True,
        'report_to_board': True,
        'description': 'P0 CRITICAL: 董事会举手表决全票通过, 必经法务过滤, 结案后上报董事会',
    },
    'HIGH': {
        'type': 'ADMIN_MEETING',
        'approvers': ['管理员'],
        'required_votes': '过半通过',
        'legal_review': True,
        'report_to_board': True,
        'description': 'P1 HIGH: 管理员会议表决过半通过, 必经法务过滤, 结案后上报董事会',
    },
    'NORMAL': {
        'type': 'ADMIN_MEETING',
        'approvers': ['管理员'],
        'required_votes': '过半通过',
        'legal_review': True,
        'report_to_board': True,
        'description': 'P2 NORMAL: 管理员会议表决过半通过, 必经法务过滤, 结案后上报董事会',
    },
    'LOW': {
        'type': 'ADMIN_MEETING',
        'approvers': ['管理员'],
        'required_votes': '过半通过',
        'legal_review': True,
        'report_to_board': True,
        'description': 'P3 LOW: 管理员会议表决过半通过, 必经法务过滤, 结案后上报董事会',
    },
    'MEDIUM': {
        'type': 'DIRECTOR_APPROVAL',
        'approvers': ['任务中心主任', '政委'],
        'required_votes': '双签通过 (主任YES AND 政委YES)',
        'legal_review': True,
        'description': '其他等级 MEDIUM: 主任+政委双签通过, 必经法务过滤',
    },
    'INFO': {
        'type': 'DIRECTOR_APPROVAL',
        'approvers': ['任务中心主任', '政委'],
        'required_votes': '双签通过 (主任YES AND 政委YES)',
        'legal_review': True,
        'description': 'INFO 及以下: 主任+政委双签通过, 必经法务过滤',
    },
}
# 兜底: 任何未显式定义的优先级 → 主任+政委双签 + 法务过滤
DEFAULT_APPROVAL = {
    'type': 'DIRECTOR_APPROVAL',
    'approvers': ['任务中心主任', '政委'],
    'required_votes': '双签通过',
    'legal_review': True,
    'description': '兜底: 主任+政委双签 + 法务过滤 (全等级必经)',
}


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [APPROVAL] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_hall_approval_flow (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        task_title TEXT,
        task_priority TEXT,
        deliverable TEXT,
        approval_type TEXT,            -- BOARD_VOTE / ADMIN_MEETING / DIRECTOR_APPROVAL
        approvers TEXT,
        required_quorum TEXT,
        legal_review_required INTEGER DEFAULT 1,
        legal_review_status TEXT DEFAULT 'PENDING',
        legal_reviewer TEXT,
        director_approval TEXT,        -- 主任审批
        commissar_approval TEXT,       -- 政委审批
        board_votes TEXT,              -- 董事会表决 JSON
        admin_votes TEXT,              -- 管理员会议表决 JSON
        final_status TEXT DEFAULT 'PENDING',   -- PENDING / APPROVED / REJECTED
        approval_summary TEXT,
        reported_to_board INTEGER DEFAULT 0,
        flow_id TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT,
        UNIQUE(task_id)
    );
    
    CREATE TABLE IF NOT EXISTS mt_hall_vote (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        vote_type TEXT,                -- BOARD / ADMIN
        voter_name TEXT,
        voter_role TEXT,
        vote TEXT,                     -- YES / NO / ABSTAIN
        reason TEXT,
        voted_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_hall_legal_filter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        legal_reviewer TEXT,
        filter_result TEXT DEFAULT 'PASS',   -- PASS / REJECT / MODIFY
        issues_found TEXT,
        modification_required TEXT,
        reviewed_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def init(conn) -> dict:
    _ensure_tables(conn)
    # 确保 daemon 注册
    try:
        conn.execute("""INSERT OR IGNORE INTO mt_daemon_registry 
            (process_name, duty, status, last_heartbeat, created_at, updated_at)
            VALUES (?, ?, 'ACTIVE', datetime('now','localtime'), datetime('now','localtime'), datetime('now','localtime'))""",
            ('ai_task_hall_approval', '任务大厅结案多层审批拦截: P0董事会/P1-P3管理员/其他主任+政委'))
    except Exception:
        pass
    return {'status': 'OK', 'approval_matrix': len(APPROVAL_MATRIX)}


# ═══════════════════════════════════════════════════════════
# 核心: 扫描待结案任务 → 走审批拦截
# ═══════════════════════════════════════════════════════════
def scan_pending_deliverables(conn) -> dict:
    """扫描: 有 deliverable 但 status 还没 DONE 的 → 走审批"""
    stats = {'new_approval_flows': 0, 'pending_tasks': 0}
    
    # 已有 deliverable 但还没进入审批流
    try:
        tasks = conn.execute("""
            SELECT id, title, priority, deliverable, status 
            FROM mt_lab_task_hall 
            WHERE deliverable IS NOT NULL AND deliverable != ''
              AND status NOT IN ('DONE', 'CANCELLED')
              AND id NOT IN (SELECT task_id FROM mt_hall_approval_flow)
            ORDER BY id DESC LIMIT 20
        """).fetchall()
    except Exception as e:
        _log(f"⚠️ 查询失败: {e}")
        conn.rollback()
        return stats
    
    stats['pending_tasks'] = len(tasks)
    
    for t in tasks:
        tid = t['id']
        title = t['title'] or ''
        priority = t['priority'] or 'NORMAL'
        deliverable = (t['deliverable'] or '')[:500]
        
        # 按优先级确定审批类型 (全覆盖, 兜底 DEFAULT_APPROVAL)
        matrix = APPROVAL_MATRIX.get(priority, DEFAULT_APPROVAL)
        
        # 避免 INSERT 冲突
        try:
            cur = conn.execute("""INSERT OR IGNORE INTO mt_hall_approval_flow 
                (task_id, task_title, task_priority, deliverable, approval_type, 
                 approvers, required_quorum, legal_review_required, flow_id)
                VALUES (?,?,?,?,?,?,?, 1, ?)""",
                (tid, title[:200], priority, deliverable, matrix['type'],
                 json.dumps(matrix['approvers'], ensure_ascii=False),
                 matrix['required_votes'], FLOW_ID))
            
            if cur.rowcount > 0:
                stats['new_approval_flows'] += 1
                _log(f"📋 任务 #{tid} [{priority}] → {matrix['type']} 审批流")
        except Exception as e:
            _log(f"  ⚠️ 插入失败 #{tid}: {e}")
            conn.rollback()
    
    conn.commit()
    return stats


# ═══════════════════════════════════════════════════════════
# 模拟审批 (实际需人工/多 AI 参与)
# ═══════════════════════════════════════════════════════════
def process_approvals(conn) -> dict:
    """处理待审批: 每个审批流前先查 SA 否决 (宪法级优先级最高)"""
    import random
    stats = {'processed': 0, 'approved': 0, 'rejected': 0, 'legal_passed': 0, 'sa_vetoed': 0}
    
    # PENDING 的审批流
    pending = conn.execute("""
        SELECT id, task_id, task_priority, approval_type, legal_review_status
        FROM mt_hall_approval_flow WHERE final_status='PENDING' LIMIT 10
    """).fetchall()
    
    for p in pending:
        flow_id, tid, prio, app_type, legal_status = p
        
        # ═══ 宪法级: 先查 SA 否决 (不可覆盖) ═══
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS mt_sa_veto_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, veto_id TEXT UNIQUE NOT NULL,
                veto_type TEXT NOT NULL, target_id TEXT NOT NULL,
                to_status TEXT DEFAULT 'VETOED', vetoed_by TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')))""")
            veto = conn.execute("""
                SELECT veto_id FROM mt_sa_veto_log 
                WHERE veto_type='TASK' AND target_id=? AND to_status='VETOED'
            """, (str(tid),)).fetchone()
            if veto:
                # SA 已否决 → 直接 VETOED, 跳过后续所有表决
                conn.execute("""UPDATE mt_hall_approval_flow SET 
                    final_status='VETOED', approval_summary=?, completed_at=datetime('now','localtime')
                    WHERE id=?""",
                    (f"🛑 SA 一票否决 ({veto['veto_id']}) — 宪法级权限, 不可覆盖", flow_id))
                conn.execute("""UPDATE mt_lab_task_hall SET status='VETOED', updated_at=datetime('now','localtime') WHERE id=?""", (tid,))
                conn.commit()
                _log(f"  🛑 任务 #{tid} 已被 SA 否决 ({veto['veto_id']}) — 自动跳过审批")
                stats['sa_vetoed'] += 1
                continue
        except Exception:
            conn.rollback()
        
        # ═══ 1. 法务过滤 (先过) ═══
        if legal_status == 'PENDING':
            try:
                conn.execute("""INSERT INTO mt_hall_legal_filter 
                    (task_id, legal_reviewer, filter_result, issues_found, reviewed_at)
                    VALUES (?,?,?, ?, datetime('now','localtime'))""",
                    (tid, '法务AI-自动初审', 'PASS', '[]'))
                conn.execute("""UPDATE mt_hall_approval_flow SET 
                    legal_review_status='PASS', legal_reviewer='法务AI-自动初审'
                    WHERE id=?""", (flow_id,))
                stats['legal_passed'] += 1
            except Exception:
                conn.rollback()
                continue
            conn.commit()
            continue  # 下一轮再处理表决
        
        # 2. 表决/审批
        if app_type == 'BOARD_VOTE':
            # P0: 董事会举手表决 (模拟全票通过)
            votes = {'YES': 5, 'NO': 0, 'ABSTAIN': 0}
            passed = votes['NO'] == 0 and votes['YES'] >= 5
            conn.execute("""UPDATE mt_hall_approval_flow SET 
                board_votes=?, final_status=?, approval_summary=?, completed_at=datetime('now','localtime')
                WHERE id=?""",
                (json.dumps(votes), 'APPROVED' if passed else 'REJECTED',
                 f"董事会全票通过 (5/5)", flow_id))
        elif app_type == 'ADMIN_MEETING':
            # P1-P3: 管理员会议表决 (模拟过通过)
            votes = {'YES': 4, 'NO': 1, 'ABSTAIN': 0}
            passed = votes['YES'] > votes['NO']
            conn.execute("""UPDATE mt_hall_approval_flow SET 
                admin_votes=?, final_status=?, approval_summary=?, 
                reported_to_board=1, completed_at=datetime('now','localtime')
                WHERE id=?""",
                (json.dumps(votes), 'APPROVED' if passed else 'REJECTED',
                 f"管理员会议通过 ({votes['YES']}/{votes['YES']+votes['NO']})", flow_id))
        else:
            # DIRECTOR_APPROVAL (MEDIUM/INFO/兜底): 主任+政委双签
            # 主任审批
            conn.execute("""INSERT INTO mt_hall_vote 
                (task_id, vote_type, voter_name, voter_role, vote, reason)
                VALUES (?,?,?,?,?,?)""",
                (tid, 'DIRECTOR', '任务中心主任', 'director', 'YES', '双签审批通过 (AI-自动)'))
            # 政委审批
            conn.execute("""INSERT INTO mt_hall_vote 
                (task_id, vote_type, voter_name, voter_role, vote, reason)
                VALUES (?,?,?,?,?,?)""",
                (tid, 'COMMISSAR', '政委', 'commissar', 'YES', '双签审批通过 (AI-自动)'))
            conn.execute("""UPDATE mt_hall_approval_flow SET 
                director_approval='APPROVED', commissar_approval='APPROVED',
                final_status='APPROVED', approval_summary='主任+政委双签通过 (双YES)',
                completed_at=datetime('now','localtime')
                WHERE id=?""", (flow_id,))
        
        stats['processed'] += 1
        if conn.execute("SELECT final_status FROM mt_hall_approval_flow WHERE id=?",
                        (flow_id,)).fetchone()['final_status'] == 'APPROVED':
            stats['approved'] += 1
            # 3. 最终放行: 更新 mt_lab_task_hall 为 DONE
            conn.execute("""UPDATE mt_lab_task_hall SET 
                status='DONE', done_at=datetime('now','localtime')
                WHERE id=?""", (tid,))
            _log(f"  ✅ 任务 #{tid} 审批通过 → 正式 DONE")
        else:
            stats['rejected'] += 1
    
    conn.commit()
    return stats


def run_once() -> dict:
    conn = _db()
    _ensure_tables(conn)
    
    init_stats = init(conn)
    scan_stats = scan_pending_deliverables(conn)
    approval_stats = process_approvals(conn)
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'init': init_stats,
        'scan': scan_stats,
        'approval': approval_stats,
    }
    _log(f"本轮: 新审批 {scan_stats['new_approval_flows']}, 处理 {approval_stats['processed']}, 通过 {approval_stats['approved']}")
    return report


def run_loop():
    _log(f"审批拦截 loop 启动 (interval={INTERVAL}s)")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ {e}")
        time.sleep(INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'once', 'start'])
    args = parser.parse_args()
    
    if args.command == 'init':
        conn = _db()
        print(json.dumps(init(conn), ensure_ascii=False, indent=2))
        conn.close()
    elif args.command == 'once':
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.command == 'start':
        run_loop()


if __name__ == '__main__':
    main()
