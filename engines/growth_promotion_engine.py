#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS · 🚀 Growth Promotion Engine (成长晋升自动触发)
#  flow_growth_promote_20261115
#
#  🧠 自动晋升逻辑 (不等人):
#    L1 个体会员 → 处理 10+ MICRO → 晋升 L2 三体组员
#    L2 三体组员 → 处理 5+ STANDARD → 晋升 L3 团队骨干
#    L3 团队骨干 → 独立带领 3+ MAJOR → 晋升 L4 团队 Leader
#    L4 Leader → 协调 2+ L4 团队联合 → 晋升 L5 集团军
#
#  触发源 (全部自动):
#  - mt_collab_growth.proposals_handled (协作引擎自动+1)
#  - mt_community_calibration (反推校正 level)
#  - mt_community_training (培训通过)
#  - mt_parliament_vote_log (议会投票参与度)
#  - mt_investment_proposal (提案 APPROVED 率)
# ═══════════════════════════════════════════════════════════════════

import datetime as dt
import json
import os
import sqlite3
import sys


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "database", "app.db")


def _conn():
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


TIER_THRESHOLDS = {
    # (from_tier, proposals_handled, lead_teams, complex_solved, training_avg_score) → to_tier
    ("L1", 10, 0, 0, 70): "L2",    # L1→L2: 处理 10+ 提案
    ("L2", 20, 0, 0, 75): "L3",    # L2→L3: 处理 20+ 提案
    ("L3", 30, 3, 1, 80): "L4",    # L3→L4: 带领 3+ 团队
    ("L4", 40, 5, 3, 85): "L5",    # L4→L5: 协调 5+ 联合行动
}


def check_and_promote(conn=None, verbose=True):
    """检查所有 AI 员工成长 → 自动晋升"""
    own = conn is None
    conn = conn or _conn()

    # 从 mt_collab_growth + mt_ai_employees 拉数据
    employees = conn.execute("""SELECT e.*, COALESCE(g.proposals_handled,0) props,
        COALESCE(g.teams_led,0) teams, COALESCE(g.complex_problems_solved,0) complex,
        g.from_tier, g.to_tier
        FROM mt_ai_employees e
        LEFT JOIN mt_collab_growth g ON e.employee_id = g.employee_id
        WHERE e.status='active' AND e.source IN ('PARLIAMENT_FUSION','GOBELIN_COMMUNITY')
        ORDER BY e.level DESC""").fetchall()

    promotions = []
    for emp in employees:
        emp = dict(emp)
        emp_id = emp["employee_id"]
        current_tier = emp.get("to_tier") or emp.get("from_tier") or "L1"
        props = emp.get("props", 0) or 0
        teams = emp.get("teams", 0) or 0
        complex_n = emp.get("complex", 0) or 0
        level = emp.get("level", 1.0) or 1.0

        # 计算培训平均分
        trainings = conn.execute("""SELECT AVG(score) FROM mt_community_training
            WHERE employee_id=? AND score>0""", (emp_id,)).fetchone()[0] or 0
        train_score = trainings

        # 议会参与度
        votes = conn.execute("""SELECT COUNT(*) FROM mt_parliament_vote_log
            WHERE member_code LIKE ?""", (f"%{emp_id.split('_')[-1]}%",)).fetchone()[0] or 0

        # APPROVED 提案率 (作为成功指标)
        success_props = conn.execute("""SELECT COUNT(*) FROM mt_investment_proposal
            WHERE status IN ('APPROVED','EXECUTED')""").fetchone()[0] or 0

        # 检查晋升条件
        for (from_t, need_props, need_teams, need_complex, need_train), to_t in TIER_THRESHOLDS.items():
            if current_tier == from_t:
                if props >= need_props and teams >= need_teams and complex_n >= need_complex and train_score >= need_train:
                    # 晋升!
                    promotions.append({
                        "employee_id": emp_id,
                        "name": emp.get("name", ""),
                        "from_tier": from_t,
                        "to_tier": to_t,
                        "reason": f"提案{props}/{need_props} 团队{teams}/{need_teams} 复杂{complex_n}/{need_complex} 培训分{train_score:.0f}/{need_train} 议会{votes}次",
                    })
                    # 更新成长表
                    conn.execute("""UPDATE mt_collab_growth SET
                        from_tier=?, to_tier=?, updated_at=datetime('now','localtime')
                        WHERE employee_id=?""", (from_t, to_t, emp_id))
                    # 同步更新 level (每次晋升 +0.5)
                    new_level = round(min(5.0, level + 0.5), 2)
                    conn.execute("""UPDATE mt_ai_employees SET level=?, updated_at=datetime('now','localtime')
                        WHERE employee_id=?""", (new_level, emp_id))
                    # 写 calibrate
                    conn.execute("""INSERT INTO mt_community_calibration
                        (employee_id, calibration_type, before_level, after_level, trigger_event, calibration_logic)
                        VALUES (?, 'PROMOTION', ?, ?, ?, ?)""",
                        (emp_id, level, new_level, f"晋升 {from_t}→{to_t}",
                         f"自动晋升引擎: {from_t}→{to_t}, {props}提案+{teams}团队+{train_score:.0f}培训分"))
                    break

    # 反方向: 如果表现差 → 降级 (level < 1.0 且最近 3 次都失败)
    # 当前阶段不降级, 先跑晋升机制

    conn.commit()

    if verbose:
        if promotions:
            print(f"\n🚀 自动晋升引擎 ({_now()})")
            for p in promotions:
                print(f"  🌟 {p['name']}: {p['from_tier']} → {p['to_tier']}")
                print(f"     原因: {p['reason']}")
        else:
            print(f"🚀 晋升引擎扫描完毕 (暂无人达标)")

    if own: conn.close()
    return promotions


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()

    if args.run:
        progs = check_and_promote()
        print(f"\n晋升完成: {len(progs)} 人")
    elif args.daemon:
        print("🚀 Growth Promotion Daemon 启动 (每 10min)")
        while True:
            check_and_promote(verbose=True)
            import time; time.sleep(600)
    else:
        parser.print_help()