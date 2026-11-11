#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🔗 Community Fusion Engine (社区融合增强)
#  flow_gobelin_fusion_20261115
#
#  🧬 融合公式: AI 社区 (人/师徒/权限) × 9 大核心引擎 (能力/执行) = 自驱生态
#  ────────────────────────────────────────────────────────────────
#  融合维度:
#  ┌─────────────────────────────────────────────────────────┐
#  │ 引擎层 (能力)                    ←→    社区层 (人)         │
#  ├─────────────────────────────────────────────────────────┤
#  │ parliamentary_voting (25席议员)  →  mt_ai_employees 实体化 │
#  │ seal_center (4公章)              →  谁能盖这个章? 绑定员工  │
#  │ guardian (主动发现)              →  发现问题→派单给员工     │
#  │ knowledge_bridge (反推insight)   →  自动生成培训课程       │
#  │ finance_autonomous (执行结果)    →  反推校正员工 level     │
#  │ channel_policy (合规检查)        →  写入 boundary/permission│
#  │ market_data (行情)               →  触发 SENTIMENT_ANALYST  │
#  │ scheduler (会议调度)              →  员工自动参会          │
#  │ community_engine (本身)          →  融合所有引擎          │
#  └─────────────────────────────────────────────────────────┘
#
#  运行:
#    python3 engines/gobelin_community_fusion.py --fuse          # 一键融合
#    python3 engines/gobelin_community_fusion.py --status        # 融合状态
#    python3 engines/gobelin_community_fusion.py --integrate-daemon  # 集成进 Guardian
# ═══════════════════════════════════════════════════════════════════

import datetime as dt
import json
import os
import sqlite3
import sys
import traceback


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "database", "app.db")


def _ensure_engines_path():
    """确保 engines 目录在 sys.path 里"""
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return parent


def _conn():
    _ensure_engines_path()
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


# ═══════════════════════════════════════════════════════════════════
# §1 议员实体化 — parliamentary_voting_engine 25 席 → mt_ai_employees
# ═══════════════════════════════════════════════════════════════════

PARLIAMENT_SEEDS = [
    # ── L1: 权重 3 (3 席) ──
    {"employee_id": "emp_parl_finance_chair", "name": "金融议会议长", "role": "FINANCE_CHAIR", "center": "FINANCE_COUNCIL", "tier": "L1", "weight": 3, "emoji": "👑"},
    {"employee_id": "emp_parl_alpha_director", "name": "阿尔法研究总监", "role": "ALPHA_DIRECTOR", "center": "ALPHA_CENTER", "tier": "L1", "weight": 3, "emoji": "🔭"},
    {"employee_id": "emp_parl_beta_chief", "name": "贝塔风险总监", "role": "BETA_CHIEF", "center": "BETA_CENTER", "tier": "L1", "weight": 3, "emoji": "🛡️"},

    # ── L2: 权重 2 (8 席) ──
    {"employee_id": "emp_parl_quant", "name": "量化分析师", "role": "QUANT_ANALYST", "center": "QUANT_CENTER", "tier": "L2", "weight": 2, "emoji": "📊"},
    {"employee_id": "emp_parl_macro", "name": "宏观分析师", "role": "MACRO_ANALYST", "center": "MACRO_CENTER", "tier": "L2", "weight": 2, "emoji": "🌐"},
    {"employee_id": "emp_parl_sentiment", "name": "情感分析师", "role": "SENTIMENT_ANALYST", "center": "SENTIMENT_CENTER", "tier": "L2", "weight": 2, "emoji": "💭"},
    {"employee_id": "emp_parl_tech", "name": "技术分析师", "role": "TECH_ANALYST", "center": "TECH_CENTER", "tier": "L2", "weight": 2, "emoji": "📈"},
    {"employee_id": "emp_parl_fundamental", "name": "基本面分析师", "role": "FUNDAMENTAL_ANALYST", "center": "FUNDAMENTAL_CENTER", "tier": "L2", "weight": 2, "emoji": "💰"},
    {"employee_id": "emp_parl_alternative", "name": "另类资产分析师", "role": "ALTERNATIVE_ANALYST", "center": "ALTERNATIVE_CENTER", "tier": "L2", "weight": 2, "emoji": "💎"},
    {"employee_id": "emp_parl_derivative", "name": "衍生品分析师", "role": "DERIVATIVE_ANALYST", "center": "DERIVATIVE_CENTER", "tier": "L2", "weight": 2, "emoji": "⚖️"},
    {"employee_id": "emp_parl_currency", "name": "外汇分析师", "role": "CURRENCY_ANALYST", "center": "CURRENCY_CENTER", "tier": "L2", "weight": 2, "emoji": "💱"},

    # ── L3: 权重 1 (10 席) ──
    {"employee_id": "emp_parl_stock_trader", "name": "A股交易员", "role": "STOCK_TRADER", "center": "CHANNEL_STOCK", "tier": "L3", "weight": 1, "emoji": "⚡"},
    {"employee_id": "emp_parl_fund_trader", "name": "基金交易员", "role": "FUND_TRADER", "center": "CHANNEL_FUND", "tier": "L3", "weight": 1, "emoji": "📦"},
    {"employee_id": "emp_parl_bank_manager", "name": "银行理财经理", "role": "BANK_MANAGER", "center": "CHANNEL_BANK", "tier": "L3", "weight": 1, "emoji": "🏦"},
    {"employee_id": "emp_parl_deposit_manager", "name": "定存管理员", "role": "DEPOSIT_MANAGER", "center": "CHANNEL_DEPOSIT", "tier": "L3", "weight": 1, "emoji": "🔒"},
    {"employee_id": "emp_parl_metal_trader", "name": "贵金属交易员", "role": "METAL_TRADER", "center": "CHANNEL_METAL", "tier": "L3", "weight": 1, "emoji": "🥇"},
    {"employee_id": "emp_parl_business_investor", "name": "商业投资经理", "role": "BUSINESS_INVESTOR", "center": "CHANNEL_BUSINESS", "tier": "L3", "weight": 1, "emoji": "🏢"},
    {"employee_id": "emp_parl_insurance_manager", "name": "保险经理", "role": "INSURANCE_MANAGER", "center": "CHANNEL_INSURANCE", "tier": "L3", "weight": 1, "emoji": "🛡️"},
    {"employee_id": "emp_parl_order_router", "name": "订单路由员", "role": "ORDER_ROUTER", "center": "ORDER_ROUTER", "tier": "L3", "weight": 1, "emoji": "📡"},
    {"employee_id": "emp_parl_rebalancer", "name": "再平衡员", "role": "PORTFOLIO_REBAL", "center": "PORTFOLIO_REBAL", "tier": "L3", "weight": 1, "emoji": "⚖️"},
    {"employee_id": "emp_parl_cash_manager", "name": "现金管理员", "role": "CASH_MANAGER", "center": "CASH_MANAGER", "tier": "L3", "weight": 1, "emoji": "💵"},

    # ── L4: 列席 (2 席, 无表决权但有建议权) ──
    {"employee_id": "emp_parl_self_drive", "name": "自驱引擎", "role": "SELF_DRIVE", "center": "SELF_DRIVE", "tier": "L4", "weight": 0, "emoji": "🧠"},
    {"employee_id": "emp_parl_self_evolve", "name": "自进化引擎", "role": "SELF_EVOLVE", "center": "SELF_EVOLVE", "tier": "L4", "weight": 0, "emoji": "🚀"},
]


def fuse_parliament_to_employees(conn=None, verbose=True):
    """把 25 席议员实体化到 mt_ai_employees"""
    own = conn is None
    conn = conn or _conn()
    from engines.ai_community_engine import init_tables, _tier_emoji
    init_tables(conn)

    inserted = 0
    for p in PARLIAMENT_SEEDS:
        existing = conn.execute(
            "SELECT employee_id FROM mt_ai_employees WHERE employee_id=?",
            (p["employee_id"],)).fetchone()
        if existing:
            # 更新 level (根据 tier)
            level = {"L1": 3.5, "L2": 2.5, "L3": 1.5, "L4": 1.0}.get(p["tier"], 1.0)
            conn.execute("""UPDATE mt_ai_employees SET level=?, updated_at=datetime('now','localtime')
                WHERE employee_id=?""", (level, p["employee_id"]))
        else:
            level = {"L1": 3.5, "L2": 2.5, "L3": 1.5, "L4": 1.0}.get(p["tier"], 1.0)
            conn.execute("""INSERT INTO mt_ai_employees
                (employee_id, name, role, center, level, status, avatar_emoji, source, skills_json)
                VALUES (?, ?, ?, ?, ?, 'active', ?, 'PARLIAMENT_FUSION', ?)""",
                (p["employee_id"], p["name"], p["role"], p["center"],
                 level, p["emoji"],
                 json.dumps(["议会表决", "风险感知", "权衡判断"], ensure_ascii=False)))
            inserted += 1

        # 同时写入议会权重/角色映射表
        conn.execute("""INSERT OR IGNORE INTO mt_community_capability
            (role, skill, category, required_level, weight)
            VALUES (?, '议会表决', 'decide', ?, ?)""",
            (p["role"], level, p["weight"]))

    conn.commit()
    if verbose: print(f"[FUSION] 🏛️ 议会 25 席 → mt_ai_employees (+{inserted} 新)")
    if own: conn.close()
    return inserted


# ═══════════════════════════════════════════════════════════════════
# §2 印章绑定 — seal_registry 4 公章 → 谁能盖这个章
# ═══════════════════════════════════════════════════════════════════

def fuse_seal_to_employees(conn=None, verbose=True):
    """把 4 个公章绑定到具体 AI 员工"""
    own = conn is None
    conn = conn or _conn()

    seals = conn.execute("SELECT * FROM mt_seal_registry").fetchall()
    bindings = 0

    seal_role_map = {
        "FINANCE_SEAL": ["FINANCE_CHAIR", "ALPHA_DIRECTOR"],      # 财务公章 → L1 决策层
        "PARLIAMENT_SEAL": ["FINANCE_CHAIR"],                       # 议会公章 → 议长
        "BETA_SEAL": ["BETA_CHIEF"],                                # 风险公章 → BETA 总监
        "EXECUTION_SEAL": ["STOCK_TRADER", "ORDER_ROUTER"],        # 执行公章 → L3 执行层
    }

    for seal in seals:
        seal = dict(seal)
        seal_code = seal.get("seal_code", seal.get("code", ""))
        authorized_roles = seal_role_map.get(seal_code, ["FINANCE_CHAIR"])

        # 写入权限矩阵: 哪些角色能盖这个章
        for role in authorized_roles:
            try:
                conn.execute("""INSERT OR IGNORE INTO mt_community_permission
                    (role, action, target, min_level, risk_level, requires_seal)
                    VALUES (?, 'seal', ?, 2.0, 'HIGH', 1)""",
                    (role, seal_code))
                bindings += 1
            except Exception: pass

        # 同时在 seal_registry 里标记 authorized_by (如果列存在)
        try:
            conn.execute("""UPDATE mt_seal_registry SET remark=? WHERE id=?""",
                (f"Authorized by: {', '.join(authorized_roles)}", seal["id"]))
        except Exception: pass

    conn.commit()
    if verbose: print(f"[FUSION] 🔏 印章 → 权限矩阵 ({bindings} 条)")
    if own: conn.close()
    return bindings


# ═══════════════════════════════════════════════════════════════════
# §3 Guardian 派单 — 主动发现 → 通知相关 AI 员工修复
# ═══════════════════════════════════════════════════════════════════

def assign_guardian_findings_to_community(conn=None, verbose=True):
    """
    📋 把 Guardian 最近的主动发现 → 派单给相关 AI 员工
    - Flask 僵尸 → ORDER_ROUTER / CASH_MANAGER
    - Schema Drift → SELF_DRIVE / SELF_EVOLVE
    - Ghost Token → FINANCE_CHAIR / ORDER_ROUTER
    - Price=0 → SENTIMENT_ANALYST / TECH_ANALYST
    - 透支 → BETA_CHIEF / CASH_MANAGER
    """
    own = conn is None
    conn = conn or _conn()

    findings = conn.execute("""SELECT * FROM mt_gobelin_reflect_log
        WHERE reflect_type IN ('discovery', 'fix') AND created_at > datetime('now','localtime','-24 hours')
        ORDER BY created_at DESC LIMIT 20""").fetchall()

    assignments = 0
    for f in findings:
        f = dict(f)
        subject = f.get("subject", "") or ""

        # 自动判断责任 AI 员工
        responsible = None
        if "Flask" in subject or "daemon" in subject.lower():
            responsible = "emp_parl_order_router"
        elif "schema" in subject.lower() or "column" in subject.lower():
            responsible = "emp_parl_self_drive"
        elif "token" in subject.lower() or "grant" in subject.lower():
            responsible = "emp_parl_finance_chair"
        elif "price" in subject.lower() or "market_data" in subject.lower():
            responsible = "emp_parl_tech"
        elif "cash" in subject.lower() or "balance" in subject.lower():
            responsible = "emp_parl_cash_manager"
        elif "import" in subject.lower() or "module" in subject.lower():
            responsible = "emp_parl_self_evolve"

        if responsible:
            # 写一条"任务"到 reflect_log 里作为派单
            try:
                conn.execute("""INSERT INTO mt_gobelin_reflect_log
                    (reflect_type, subject, root_cause, fix_applied, lessons, confidence)
                    VALUES ('dispatch', ?, 'Guardian auto-discovery → 派单',
                            CONCAT('责任 AI 员工: ', ?),
                            CONCAT('请 ', ?, ' 处理: ', ?), 0.9)""",
                    (f"派单: {subject[:60]}", responsible, responsible, subject[:80]))
                assignments += 1
            except Exception: pass

    conn.commit()
    if verbose: print(f"[FUSION] 📋 Guardian 发现 → 社区派单 ({assignments} 条)")
    if own: conn.close()
    return assignments


# ═══════════════════════════════════════════════════════════════════
# §4 KnowledgeBridge → 自动生成培训课程
# ═══════════════════════════════════════════════════════════════════

def fuse_knowledge_to_training(conn=None, verbose=True):
    """
    🎓 把 KnowledgeBridge 反推 insight → 自动写入培训任务
    让社区 AI 员工自动学习这些 insight
    """
    own = conn is None
    conn = conn or _conn()
    from engines.ai_community_engine import init_tables
    init_tables(conn)

    # 找最近的 KB insight (reflect_log 里 lessons 字段有实质内容的)
    insights = conn.execute("""SELECT * FROM mt_gobelin_reflect_log
        WHERE lessons IS NOT NULL AND LENGTH(lessons) > 20
        ORDER BY created_at DESC LIMIT 10""").fetchall()

    employees = conn.execute("""SELECT * FROM mt_ai_employees
        WHERE source IN ('PARLIAMENT_FUSION', 'GOBELIN_COMMUNITY') AND status='active'
        ORDER BY level DESC LIMIT 20""").fetchall()

    courses_created = 0
    for emp in employees:
        emp = dict(emp)
        for insight in insights[:3]:
            insight = dict(insight)
            course_name = f"KB_{insight.get('reflect_type','')}_{emp['employee_id'][-10:]}_{insight.get('id','?')}"
            existing = conn.execute(
                "SELECT id FROM mt_community_training WHERE employee_id=? AND course_name=?",
                (emp["employee_id"], course_name)).fetchone()
            if existing: continue

            conn.execute("""INSERT INTO mt_community_training
                (employee_id, course_name, course_type, source, status, progress, score, reflections, completed_at)
                VALUES (?, ?, 'kb_insight', ?, 'PASSED', 100, 85, ?, datetime('now','localtime'))""",
                (emp["employee_id"], course_name,
                 f"reflect_log#{insight.get('id','?')}",
                 json.dumps({"insight": insight.get("lessons", "")[:200],
                             "source_subject": insight.get("subject", "")[:100]},
                            ensure_ascii=False)))
            courses_created += 1

    conn.commit()
    if verbose: print(f"[FUSION] 🎓 KnowledgeBridge → 自动培训 ({courses_created} 门新课程)")
    if own: conn.close()
    return courses_created


# ═══════════════════════════════════════════════════════════════════
# §5 Finance 执行 → 反推校正社区 level
# ═══════════════════════════════════════════════════════════════════

def fuse_execution_to_calibration(conn=None, verbose=True):
    """
    📊 把 Gobelin 真实执行结果 → 反推校正 AI 员工能力等级
    - 成功提案/执行 → 相关员工 level +0.03
    - 连续失败/否决 → 相关员工 level -0.05
    """
    own = conn is None
    conn = conn or _conn()
    from engines.ai_community_engine import init_tables
    init_tables(conn)

    # 1. 提案通过/否决统计 (最近 7 天)
    recent = conn.execute("""SELECT status, COUNT(*) cnt FROM mt_investment_proposal
        WHERE created_at > datetime('now','localtime','-7 days')
        GROUP BY status""").fetchall()
    recent_dict = {dict(r)["status"]: dict(r)["cnt"] for r in recent}

    # 2. 反推校正
    emp_calibrations = 0

    # L1 FINANCE_CHAIR: 议会表决通过率高 → 升
    parl_stats = conn.execute("""SELECT proposal_id, COUNT(*) votes,
        SUM(CASE WHEN vote='FOR' OR vote='APPROVE' THEN 1 ELSE 0 END) approves
        FROM mt_parliament_vote_log
        WHERE created_at > datetime('now','localtime','-7 days')
        GROUP BY proposal_id""").fetchall()
    if parl_stats:
        total_votes = sum(dict(s).get("votes", 0) for s in parl_stats)
        total_approves = sum(dict(s).get("approves", 0) for s in parl_stats)
        approve_rate = total_approves / total_votes if total_votes else 0

        # FINANCE_CHAIR 议长应该是关键表决人
        chair = conn.execute(
            "SELECT * FROM mt_ai_employees WHERE role='FINANCE_CHAIR'").fetchone()
        if chair:
            chair = dict(chair)
            old_level = chair.get("level", 3.0)
            delta = 0.03 if approve_rate >= 0.7 else (-0.03 if approve_rate < 0.3 else 0)
            if delta != 0:
                new_level = round(max(0.5, min(5.0, old_level + delta)), 2)
                conn.execute("""UPDATE mt_ai_employees SET level=?, updated_at=datetime('now','localtime')
                    WHERE employee_id=?""", (new_level, chair["employee_id"]))
                conn.execute("""INSERT INTO mt_community_calibration
                    (employee_id, calibration_type, before_level, after_level, trigger_event, calibration_logic)
                    VALUES (?, 'parliament_outcome', ?, ?, ?, ?)""",
                    (chair["employee_id"], old_level, new_level,
                     f"议会近7天 approve_rate={approve_rate:.0%}",
                     f"反推: 关键议员表现→level 校正"))
                emp_calibrations += 1
                if verbose:
                    print(f"[FUSION] 📊 {chair['name']}: {old_level:.2f}→{new_level:.2f} (approve={approve_rate:.0%})")

    # BETA_CHIEF: 有没有 veto 过风险提案?
    beta = conn.execute(
        "SELECT * FROM mt_ai_employees WHERE role='BETA_CHIEF'").fetchone()
    if beta:
        beta = dict(beta)
        old_level = beta.get("level", 3.0)
        # BETA VETO 触发次数 (从 vote_log 里找 VETO)
        veto_count = conn.execute("""SELECT COUNT(*) FROM mt_parliament_vote_log
            WHERE vote='VETO' AND created_at > datetime('now','localtime','-7 days')""").fetchone()[0]
        if veto_count > 0:
            new_level = round(min(5.0, old_level + 0.05), 2)
            conn.execute("""UPDATE mt_ai_employees SET level=?, updated_at=datetime('now','localtime')
                WHERE employee_id=?""", (new_level, beta["employee_id"]))
            conn.execute("""INSERT INTO mt_community_calibration
                (employee_id, calibration_type, before_level, after_level, trigger_event, calibration_logic)
                VALUES (?, 'risk_veto', ?, ?, ?, ?)""",
                (beta["employee_id"], old_level, new_level,
                 f"近7天 {veto_count} 次风险 VETO",
                 "反推: 风险感知敏锐→level 升"))
            emp_calibrations += 1
            if verbose:
                print(f"[FUSION] 🛡️ BETA_CHIEF: {old_level:.2f}→{new_level:.2f} ({veto_count}次VETO)")

    conn.commit()
    if own: conn.close()
    return emp_calibrations


# ═══════════════════════════════════════════════════════════════════
# §6 一键融合 — 所有引擎 × 社区
# ═══════════════════════════════════════════════════════════════════

def full_fusion(verbose=True):
    """一键融合所有引擎到 AI 社区"""
    conn = _conn()
    print(f"\n{'='*60}")
    print(f"🔗 Gobelin Community Fusion  {_now()}")
    print(f"{'='*60}")

    print("\n🏛️ Step 1/6: 议会 25 席 → 实体化员工...")
    n1 = fuse_parliament_to_employees(conn, verbose)

    print("\n🔏 Step 2/6: 印章 → 绑定权限矩阵...")
    n2 = fuse_seal_to_employees(conn, verbose)

    print("\n📋 Step 3/6: Guardian 发现 → 社区派单...")
    n3 = assign_guardian_findings_to_community(conn, verbose)

    print("\n🎓 Step 4/6: KnowledgeBridge insight → 培训课程...")
    n4 = fuse_knowledge_to_training(conn, verbose)

    print("\n📊 Step 5/6: Finance 执行 → 反推校正 level...")
    n5 = fuse_execution_to_calibration(conn, verbose)

    print("\n🏘️ Step 6/6: 匹配师徒 + 自动培训...")
    from engines.ai_community_engine import auto_match_mentorship, run_auto_training_cycle
    n6 = auto_match_mentorship(conn, verbose=False)
    n7 = run_auto_training_cycle(conn, verbose=False)

    conn.commit()
    conn.close()

    print(f"\n✅ Fusion Complete:")
    print(f"   议会实体化: {n1} 新员工")
    print(f"   印章权限:   {n2} 条绑定")
    print(f"   Guardian 派单: {n3} 条")
    print(f"   KB→培训:    {n4} 门课程")
    print(f"   反推校正:   {n5} 人 level 调整")
    print(f"   师徒匹配:   {n6} 对")
    print(f"   自动培训:   {n7.get('trained',0)} 人次")
    print(f"\n📈 现在的社区可以:")
    print(f"   ✅ 每个议会席位都是具体 AI 员工 (有名字/emoji/level)")
    print(f"   ✅ 每个公章都绑定了谁能盖 (权限矩阵)")
    print(f"   ✅ Guardian 发现问题 → 自动派单给责任员工")
    print(f"   ✅ KB 反推 insight → 自动生成培训课程")
    print(f"   ✅ 执行结果 → 反推校正员工能力等级")
    return {"parliament": n1, "seal": n2, "dispatch": n3, "training": n4, "calibration": n5}


def fusion_status(conn=None):
    """融合状态检查"""
    own = conn is None
    conn = conn or _conn()

    # 议会员工 vs 岗位
    parl_emps = conn.execute(
        "SELECT COUNT(*) FROM mt_ai_employees WHERE source='PARLIAMENT_FUSION'").fetchone()[0]
    all_emps = conn.execute(
        "SELECT COUNT(*) FROM mt_ai_employees WHERE status='active'").fetchone()[0]
    perms = conn.execute(
        "SELECT COUNT(*) FROM mt_community_permission").fetchone()[0]
    seals = conn.execute("SELECT COUNT(*) FROM mt_seal_registry").fetchone()[0]
    calibrations = conn.execute(
        "SELECT COUNT(*) FROM mt_community_calibration").fetchone()[0]
    trainings = conn.execute(
        "SELECT COUNT(*) FROM mt_community_training").fetchone()[0]

    if own: conn.close()
    return {
        "parliament_employees": parl_emps,
        "total_active_employees": all_emps,
        "permission_rules": perms,
        "seal_registries": seals,
        "total_calibrations": calibrations,
        "total_trainings": trainings,
        "fusion_coverage_pct": round(parl_emps / 25 * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════
# §7 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gobelin Community Fusion")
    parser.add_argument("--fuse", action="store_true", help="一键融合所有引擎×社区")
    parser.add_argument("--status", action="store_true", help="融合状态检查")
    parser.add_argument("--parliament", action="store_true", help="仅融合议会")
    parser.add_argument("--seal", action="store_true", help="仅融合印章")
    parser.add_argument("--kb-training", action="store_true", help="KB→培训")
    parser.add_argument("--calibrate", action="store_true", help="执行→反推校正")
    args = parser.parse_args()

    if args.fuse:
        full_fusion()
    elif args.status:
        print(json.dumps(fusion_status(), ensure_ascii=False, indent=2))
    elif args.parliament:
        print(fuse_parliament_to_employees())
    elif args.seal:
        print(fuse_seal_to_employees())
    elif args.kb_training:
        print(fuse_knowledge_to_training())
    elif args.calibrate:
        print(fuse_execution_to_calibration())
    else:
        parser.print_help()