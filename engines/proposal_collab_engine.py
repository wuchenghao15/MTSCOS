#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🧩 Proposal Collaboration Engine (提案智能协作)
#  flow_proposal_collab_20261115
#
#  🧠 核心思维转变:
#    旧: 提案出来 → 议会表决 → 执行 (线性被动)
#    新: 提案出来 → AI 智能拆解 → 能力匹配 → 团队组合 → 多角色介入 → 协同执行 → 纪要沉淀 → 痕迹追踪 → 反推成长
#  ────────────────────────────────────────────────────────────────
#  协作层次 (从小到大):
#  L1 个体 AI 员工     → 单干 (简单提案, MICRO <¥5k)
#  L2 三体小组         → 1决策+1分析+1执行 (STANDARD ¥5k-50k)
#  L3 专业团队         → 3-5人团队 (MAJOR ¥50k-200k)
#  L4 多中心联合作战   → 跨中心组合 (MEGA >¥200k)
#  L5 集团军级         → 全社区动员 (战略级提案)
#
#  介入角色 (按需组合, 动态配比):
#  ┌──────────────┬──────────────────────────────────────────┐
#  │ 角色          │ 能力                                     │
#  ├──────────────┼──────────────────────────────────────────┤
#  │ 🎓 教授       │ 方法论指导, 理论支撑, 反推校正            │
#  │ 💡 顾问       │ 领域专家, 外部视角, 关键洞察              │
#  │ 🧠 三体 AI    │ 决策脑 + 分析眼 + 执行手 (组合体)        │
#  │ 🏛️ 议会       │ 表决 + VETO                               │
#  │ 🔏 印章       │ 合规授权                                   │
#  │ 🛡️ BETA 风险  │ 风险把关 + 熔断                           │
#  │ 🌐 外部外援   │ KnowledgeBridge 全网知识 + 反推 insight   │
#  │ 📋 纪要员     │ 全程记录 → mt_collab_trace                │
#  └──────────────┴──────────────────────────────────────────┘
#
#  权衡配比 (动态计算, 非固定值):
#  每个提案的角色组合和权重 = f(amount, risk, complexity, urgency)
#  ────────────────────────────────────────────────────────────────
#  成长路径:
#    小我 (单一 agent 能做 MICRO)
#    → 中我 (三体小组能做 STANDARD)
#    → 大我 (专业团队能做 MAJOR)
#    → 集团军 (多中心联合作战 MEGA)
#    → AI 自主决策 (整个社区闭环, 零人工)
#  ────────────────────────────────────────────────────────────────
#  运行:
#    python3 engines/proposal_collab_engine.py --analyze <proposal_id>   # 智能分析 + 协作方案
#    python3 engines/proposal_collab_engine.py --dispatch <proposal_id>   # 派单执行
#    python3 engines/proposal_collab_engine.py --trace <proposal_id>      # 协作痕迹查看
#    python3 engines/proposal_collab_engine.py --run-pending              # 批量处理待协作提案
#    python3 engines/proposal_collab_engine.py --daemon                   # 常驻守护
# ═══════════════════════════════════════════════════════════════════

import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import time
import traceback


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_engines_path():
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return parent


def _db():
    _ensure_engines_path()
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "database", "app.db")


def _conn():
    _ensure_engines_path()
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


# ═══════════════════════════════════════════════════════════════════
# §0 Schema — 协作引擎专属表
# ═══════════════════════════════════════════════════════════════════

COLLAB_TABLES = {
    # ── 协作方案表 (每次提案自动生成) ──
    "mt_collab_plan": """CREATE TABLE IF NOT EXISTS mt_collab_plan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id INTEGER NOT NULL,
        plan_hash TEXT UNIQUE,
        tier TEXT DEFAULT 'L1',              -- L1个体/L2三体/L3团队/L4联合作战/L5集团军
        total_amount REAL DEFAULT 0,
        risk_level TEXT DEFAULT 'MEDIUM',
        complexity REAL DEFAULT 0,            -- 0-1 复杂度评分
        urgency REAL DEFAULT 0,               -- 0-1 紧急度
        recommended_roles TEXT DEFAULT '[]',   -- 推荐介入角色 (JSON)
        role_weights TEXT DEFAULT '{}',        -- 各角色权重配比 (JSON)
        lead_employee TEXT DEFAULT '',         -- 主责 AI 员工
        supporting_employees TEXT DEFAULT '[]', -- 辅助 AI 员工 (JSON)
        external_inputs TEXT DEFAULT '[]',     -- 外部知识来源 (JSON)
        plan_summary TEXT DEFAULT '',          -- 方案摘要
        status TEXT DEFAULT 'DRAFT',           -- DRAFT → DISPATCHED → EXECUTING → DONE / REJECTED
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 协作痕迹流水 (每步操作都记录, 东亚流痕迹) ──
    "mt_collab_trace": """CREATE TABLE IF NOT EXISTS mt_collab_trace (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL,
        proposal_id INTEGER DEFAULT 0,
        step_order INTEGER DEFAULT 0,
        trace_type TEXT DEFAULT '',            -- ANALYZE / DISPATCH / VOTE / EXECUTE / REVIEW / FEEDBACK
        actor_role TEXT DEFAULT '',            -- 介入角色: 教授/顾问/三体/AI员工/印章/BETA/议会
        actor_employee TEXT DEFAULT '',        -- 具体 AI 员工
        action TEXT DEFAULT '',                -- 做了什么
        input_snapshot TEXT DEFAULT '',        -- 输入快照 (JSON)
        output_snapshot TEXT DEFAULT '',       -- 输出快照 (JSON)
        decision_point TEXT DEFAULT '',        -- 关键决策点
        adopted TEXT DEFAULT '',               -- 采纳点 (JSON)
        rejected TEXT DEFAULT '',              -- 放弃点 (JSON)
        reasoning TEXT DEFAULT '',             -- 为什么这么做
        weight_in_plan REAL DEFAULT 0,         -- 在整体方案里的权重
        trace_hash TEXT DEFAULT '',            -- 防篡改 hash
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 纪要员自动记录 (每个提案一份完整纪要) ──
    "mt_collab_minutes": """CREATE TABLE IF NOT EXISTS mt_collab_minutes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL,
        proposal_id INTEGER DEFAULT 0,
        title TEXT DEFAULT '',
        participants TEXT DEFAULT '[]',        -- 参与 AI 员工 (JSON)
        agenda TEXT DEFAULT '[]',              -- 议程 (JSON)
        decisions TEXT DEFAULT '[]',           -- 决策事项 (JSON)
        key_insights TEXT DEFAULT '[]',        -- 关键洞察 (JSON)
        action_items TEXT DEFAULT '[]',        -- 待办事项 (JSON)
        risks_identified TEXT DEFAULT '[]',   -- 发现的风险 (JSON)
        alternatives_considered TEXT DEFAULT '[]', -- 考虑过但放弃的方案 (JSON)
        minutes_markdown TEXT DEFAULT '',      -- Markdown 格式完整纪要
        auto_generated INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(plan_id)
    )""",

    # ── 成长追踪表 (从小我到大我) ──
    "mt_collab_growth": """CREATE TABLE IF NOT EXISTS mt_collab_growth (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        from_tier TEXT DEFAULT 'L1',           -- 起始协作层级
        to_tier TEXT DEFAULT 'L1',             -- 晋升后层级
        proposals_handled INTEGER DEFAULT 0,   -- 独立处理的提案数
        teams_led INTEGER DEFAULT 0,           -- 带领的团队数
        complex_problems_solved INTEGER DEFAULT 0,
        growth_evidence TEXT DEFAULT '[]',     -- 成长证据 (JSON: proposal_ids)
        growth_insight TEXT DEFAULT '',         -- 反推洞察
        calibration_source TEXT DEFAULT 'SELF_REFLECT',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── 角色介入次数统计 (权衡配比的基础数据) ──
    "mt_collab_role_stats": """CREATE TABLE IF NOT EXISTS mt_collab_role_stats (
        role_name TEXT PRIMARY KEY,            -- 教授/顾问/三体/AI员工/BETA/印章/议会/外部外援
        total_interventions INTEGER DEFAULT 0,
        successful INTEGER DEFAULT 0,
        impact_score REAL DEFAULT 0,           -- 平均影响分 0-1
        avg_weight REAL DEFAULT 0,              -- 平均介入权重
        last_used TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
}


def init_tables(conn=None):
    """初始化协作引擎所有表 (幂等)"""
    own = conn is None
    conn = conn or _conn()
    created = []
    for name, ddl in COLLAB_TABLES.items():
        try:
            conn.execute(ddl)
            created.append(name)
        except Exception as e:
            sys.stderr.write(f"[COLLAB] create {name}: {e}\n")
    conn.commit()
    if own: conn.close()
    return created


# ═══════════════════════════════════════════════════════════════════
# §1 智能分析 — 提案 → 协作方案
# ═══════════════════════════════════════════════════════════════════

# 提案量级别名 → 协作层级映射
PROPOSAL_TIER_MAP = {
    "MICRO":   {"tier": "L1", "amount_range": [0, 5000], "risk_default": "LOW"},
    "STANDARD": {"tier": "L2", "amount_range": [5000, 50000], "risk_default": "MEDIUM"},
    "MAJOR":   {"tier": "L3", "amount_range": [50000, 200000], "risk_default": "HIGH"},
    "MEGA":    {"tier": "L4", "amount_range": [200000, 99999999], "risk_default": "CRITICAL"},
}


def analyze_proposal(proposal_id, conn=None, verbose=True):
    """
    🧠 AI 智能分析提案 → 自动生成协作方案
    
    分析维度:
    1. amount → 协作层级 (L1-L4)
    2. channel → 需要哪些专业中心 (STOCK/METAL/FUND...)
    3. 历史类似提案 → 之前是怎么组合的? 成功率多少?
    4. 风险评估 → BETA CHIEF 要不要介入?
    5. 复杂度 → 是单一渠道还是多渠道组合?
    6. 紧急度 → 今天必须做还是可以等?
    """
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)

    # 1. 读提案
    prop = conn.execute(
        "SELECT * FROM mt_investment_proposal WHERE id=?", (proposal_id,)).fetchone()
    if not prop:
        return {"ok": False, "error": f"proposal {proposal_id} not found"}
    prop = dict(prop)

    amount = float(prop.get("amount") or 0)
    channel = prop.get("channel") or prop.get("asset_type") or ""
    prop_type = prop.get("ptype") or prop.get("proposal_type") or "STANDARD"
    status = prop.get("status") or ""

    # ── Step B: 确定协作层级 ──
    tier_info = PROPOSAL_TIER_MAP.get(prop_type, PROPOSAL_TIER_MAP["STANDARD"])
    # 如果 amount 超出类型范围, 以实际金额算
    resolved_tier = tier_info["tier"]
    for tname, tinfo in PROPOSAL_TIER_MAP.items():
        if tinfo["amount_range"][0] <= amount < tinfo["amount_range"][1]:
            resolved_tier = tinfo["tier"]
            break

    # ── Step C: 历史类似提案 (反推: 之前成功的方案是什么样的?) ──
    similar_success = conn.execute("""SELECT c.* FROM mt_collab_plan c
        JOIN mt_investment_proposal p ON c.proposal_id = p.id
        WHERE p.channel LIKE ? AND p.status IN ('APPROVED','EXECUTED','DONE')
        ORDER BY c.created_at DESC LIMIT 5""",
        (f"%{channel}%",)).fetchall()
    similar_success_parsed = [dict(r) for r in similar_success]

    # ── Step D: 动态风险评估 ──
    risk = _assess_risk(prop, conn)
    complexity = _assess_complexity(prop, channel)
    urgency = _assess_urgency(prop, conn)

    # ── Step E: 推荐角色组合 + 权重配比 ──
    roles, weights = _recommend_role_mix(resolved_tier, risk, complexity, urgency, channel)

    # ── Step F: 匹配主责 AI 员工 ──
    lead, supporting = _match_ai_employees(resolved_tier, channel, risk, conn)

    # ── Step G: 外部知识来源 ──
    external_inputs = _fetch_external_knowledge(prop, channel, conn)

    # ── Step H: 生成方案 ──
    plan_hash = hashlib.sha256(
        f"prop:{proposal_id}:tier:{resolved_tier}:roles:{json.dumps(roles)}:{_now()}".encode()
    ).hexdigest()[:16]

    plan_summary = _generate_plan_summary(
        prop, resolved_tier, roles, weights, lead, risk, complexity, urgency, similar_success_parsed
    )

    # 写 plan 表
    existing_plan = conn.execute(
        "SELECT id FROM mt_collab_plan WHERE proposal_id=?", (proposal_id,)).fetchone()
    plan_dict = {
        "proposal_id": proposal_id,
        "plan_hash": plan_hash,
        "tier": resolved_tier,
        "total_amount": amount,
        "risk_level": risk,
        "complexity": complexity,
        "urgency": urgency,
        "recommended_roles": json.dumps(roles, ensure_ascii=False),
        "role_weights": json.dumps(weights, ensure_ascii=False),
        "lead_employee": lead.get("employee_id", "") if lead else "",
        "supporting_employees": json.dumps(supporting, ensure_ascii=False),
        "external_inputs": json.dumps(external_inputs, ensure_ascii=False),
        "plan_summary": plan_summary,
        "status": "ANALYZED",
    }

    cols = ", ".join(plan_dict.keys())
    placeholders = ", ".join(["?"] * len(plan_dict))
    updates = ", ".join(f"{k}=?" for k in plan_dict.keys())
    values = list(plan_dict.values())

    if existing_plan:
        conn.execute(f"UPDATE mt_collab_plan SET {updates}, updated_at=datetime('now','localtime') WHERE id=?",
                     values + [existing_plan["id"]])
        plan_id = existing_plan["id"]
    else:
        conn.execute(f"INSERT INTO mt_collab_plan ({cols}) VALUES ({placeholders})", values)
        plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 🧾 Step I: 写分析痕迹 (东亚流)
    _write_trace(conn, plan_id, proposal_id, step_order=1,
                 trace_type="ANALYZE", actor_role="SELF_DRIVE",
                 actor_employee="SYSTEM",
                 action=f"智能分析提案 → 方案 {resolved_tier}",
                 output_snapshot=json.dumps({
                     "tier": resolved_tier, "risk": risk, "complexity": complexity,
                     "urgency": urgency, "roles": roles, "weights": weights,
                     "lead": lead.get("name") if lead else "",
                 }, ensure_ascii=False),
                 decision_point="协作层级 + 角色配比 + 主责 AI",
                 reasoning=f"amount={amount} channel={channel} risk={risk} complexity={complexity} urgency={urgency}",
                 weight_in_plan=1.0)

    # 📋 Step J: 自动生成纪要
    _generate_minutes(conn, plan_id, proposal_id, prop, roles, weights, lead, supporting)

    conn.commit()

    result = {
        "ok": True,
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "tier": resolved_tier,
        "amount": amount,
        "risk": risk,
        "complexity": complexity,
        "urgency": urgency,
        "roles": roles,
        "weights": weights,
        "lead_employee": lead.get("name", "") if lead else "",
        "lead_employee_id": lead.get("employee_id", "") if lead else "",
        "supporting_count": len(supporting),
        "similar_success_count": len(similar_success_parsed),
        "plan_summary": plan_summary,
    }

    if verbose:
        print(f"\n🧠 提案 #{proposal_id} 智能分析完成:")
        print(f"   协作层级: {resolved_tier} ({'L1个体' if resolved_tier=='L1' else 'L2三体' if resolved_tier=='L2' else 'L3团队' if resolved_tier=='L3' else 'L4联合作战' if resolved_tier=='L4' else 'L5集团军'})")
        print(f"   金额: ¥{amount:,.0f}  风险: {risk}  复杂度: {complexity:.2f}  紧急度: {urgency:.2f}")
        print(f"   推荐角色: {', '.join(roles)}")
        print(f"   主责 AI: {lead.get('name', '') if lead else '—'}")
        print(f"   辅助 AI: {len(supporting)} 人")
        print(f"   历史类似成功: {len(similar_success_parsed)} 条")

    if own: conn.close()
    return result


# ═══════════════════════════════════════════════════════════════════
# §2 智能匹配 — 员工/团队/角色
# ═══════════════════════════════════════════════════════════════════

# 渠道 → 中心 → 角色映射
CHANNEL_ROLE_MAP = {
    "STOCK":      {"centers": ["TECH_CENTER", "FUNDAMENTAL_CENTER", "CHANNEL_STOCK"], "tier_preference": "L2"},
    "A_STOCK":    {"centers": ["TECH_CENTER", "FUNDAMENTAL_CENTER", "CHANNEL_STOCK"], "tier_preference": "L2"},
    "ETF":        {"centers": ["MACRO_CENTER", "QUANT_CENTER", "CHANNEL_STOCK"], "tier_preference": "L2"},
    "FUND":       {"centers": ["MACRO_CENTER", "CHANNEL_FUND"], "tier_preference": "L2"},
    "BANK":       {"centers": ["MACRO_CENTER", "CHANNEL_BANK", "CASH_MANAGER"], "tier_preference": "L3"},
    "DEPOSIT":    {"centers": ["CHANNEL_DEPOSIT", "CASH_MANAGER"], "tier_preference": "L3"},
    "METAL":      {"centers": ["ALTERNATIVE_CENTER", "CHANNEL_METAL"], "tier_preference": "L2"},
    "BUSINESS":   {"centers": ["ALPHA_CENTER", "ALTERNATIVE_CENTER", "CHANNEL_BUSINESS"], "tier_preference": "L1"},
    "INSURANCE":  {"centers": ["BETA_CENTER", "CHANNEL_INSURANCE"], "tier_preference": "L2"},
}


def _assess_risk(prop, conn):
    """动态风险评估"""
    amount = float(prop.get("amount", 0) or 0)
    risk = "LOW"
    if amount > 200000: risk = "CRITICAL"
    elif amount > 50000: risk = "HIGH"
    elif amount > 5000: risk = "MEDIUM"
    # 如果渠道有历史失败, 升级风险
    channel = prop.get("channel", "") or ""
    if channel:
        fail_count = conn.execute("""SELECT COUNT(*) FROM mt_investment_proposal
            WHERE channel LIKE ? AND status IN ('REJECTED','FAILED')
            AND created_at > datetime('now','localtime','-30 days')""",
            (f"%{channel}%",)).fetchone()[0]
        if fail_count > 0 and risk != "CRITICAL":
            risk = "HIGH" if risk == "LOW" or risk == "MEDIUM" else risk
    return risk


def _assess_complexity(prop, channel):
    """复杂度评估 0-1"""
    score = 0.3  # 基础分
    amount = float(prop.get("amount", 0) or 0)
    score += min(amount / 500000, 0.3)  # 越大越复杂
    # 渠道映射覆盖的中心数 = 复杂度
    ch_info = CHANNEL_ROLE_MAP.get(channel, {})
    score += min(len(ch_info.get("centers", [])) * 0.08, 0.24)
    return round(min(score, 1.0), 2)


def _assess_urgency(prop, conn):
    """紧急度评估 0-1"""
    score = 0.3
    channel = prop.get("channel", "") or ""
    # 贵金属有夜盘, 紧急度更高
    if channel == "METAL":
        now = dt.datetime.now()
        # 夜盘 21:00-02:30
        if 21 <= now.hour or now.hour < 3:
            score = 0.8
    # 提案创建时间越久, 越紧急
    created = prop.get("created_at", "")
    if created:
        try:
            created_dt = dt.datetime.strptime(created[:16], "%Y-%m-%d %H:%M")
            hours = (dt.datetime.now() - created_dt).total_seconds() / 3600
            if hours > 48: score = min(score + 0.4, 1.0)
            elif hours > 24: score = min(score + 0.2, 1.0)
        except Exception: pass
    return round(min(score, 1.0), 2)


def _recommend_role_mix(tier, risk, complexity, urgency, channel):
    """
    🎭 动态角色组合推荐 + 权衡配比
    
    配比逻辑:
    - L1 MICRO: 个体 AI + 印章 (最简)
    - L2 STANDARD: 三体小组 (决策+分析+执行) + BETA 风评
    - L3 MAJOR: 专业团队 + 议会表决 + 印章 + BETA + 顾问
    - L4 MEGA: 全社区动员 + 教授 + 议会 + 印章 + BETA + 外部外援 + 纪要员
    """
    roles = []
    if tier == "L1":
        roles = ["AI_EMPLOYEE", "SEAL"]
    elif tier == "L2":
        roles = ["TRIO_DECISION", "TRIO_ANALYST", "TRIO_EXECUTOR", "BETA_RISK", "SEAL"]
    elif tier == "L3":
        roles = ["TEAM_LEAD", "TEAM_ANALYST", "TEAM_EXECUTOR", "PARLIAMENT", "BETA_RISK", "SEAL", "ADVISOR"]
    elif tier == "L4":
        roles = ["COMMANDER", "PARLIAMENT", "BETA_RISK", "SEAL", "PROFESSOR", "ADVISOR", "EXTERNAL", "MINUTES"]
    else:  # L5
        roles = ["COMMANDER", "PARLIAMENT", "BETA_RISK", "SEAL", "PROFESSOR", "ADVISOR", "EXTERNAL", "MINUTES", "ALLIANCE"]

    # 动态加权 (风险越高 BETA 权重越大, 复杂度越高 PROFESSOR/ADVISOR 权重越大)
    weights = {}
    for r in roles:
        w = 1.0
        if r == "BETA_RISK": w = 1.0 + ({"LOW": 0, "MEDIUM": 0.1, "HIGH": 0.3, "CRITICAL": 0.5}.get(risk, 0))
        if r == "PROFESSOR": w = 0.8 + complexity * 0.4
        if r == "ADVISOR": w = 0.8 + complexity * 0.3
        if r == "SEAL": w = 1.2 if risk in ("HIGH", "CRITICAL") else 0.8
        if r == "EXTERNAL": w = 0.6 + urgency * 0.4
        if r == "PARLIAMENT": w = 1.5 if tier in ("L3", "L4", "L5") else 0.8
        if r.startswith("TRIO_") or r.startswith("TEAM_") or r == "COMMANDER" or r == "ALLIANCE":
            w = 1.0  # 核心角色标准权重
        weights[r] = round(w, 2)

    # 归一化
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 3) for k, v in weights.items()}

    return roles, weights


def _match_ai_employees(tier, channel, risk, conn):
    """匹配最合适的 AI 员工 (主责 + 辅助)"""
    ch_info = CHANNEL_ROLE_MAP.get(channel, CHANNEL_ROLE_MAP["A_STOCK"])
    centers = ch_info.get("centers", [])

    # 1. 找主责: 匹配中心 + tier 偏好 + 高 level
    lead = conn.execute("""SELECT * FROM mt_ai_employees
        WHERE center IN ({}) AND status='active'
        ORDER BY level DESC LIMIT 1""".format(
        ",".join("?" * len(centers))), centers).fetchone()
    lead = dict(lead) if lead else None

    # 如果没匹配到, 兜底: 找最高 level 的 Gobelin 员工
    if not lead:
        lead = conn.execute("""SELECT * FROM mt_ai_employees
            WHERE source IN ('PARLIAMENT_FUSION', 'GOBELIN_COMMUNITY') AND status='active'
            ORDER BY level DESC LIMIT 1""").fetchone()
        lead = dict(lead) if lead else None

    # 2. 辅助: 同中心 + 次高 level
    supporting = []
    if tier in ("L2", "L3", "L4", "L5"):
        for center in centers[:3]:  # 最多 3 个中心各拉 1 人
            emps = conn.execute("""SELECT * FROM mt_ai_employees
                WHERE center=? AND status='active'
                ORDER BY level DESC LIMIT 2""", (center,)).fetchall()
            for e in emps:
                e = dict(e)
                if lead and e["employee_id"] != lead["employee_id"] and e not in supporting:
                    supporting.append({
                        "employee_id": e["employee_id"],
                        "name": e["name"],
                        "center": e.get("center", ""),
                        "role": e.get("role", ""),
                        "level": e.get("level", 0),
                    })
                if len(supporting) >= 4: break
            if len(supporting) >= 4: break

    return lead, supporting


def _fetch_external_knowledge(prop, channel, conn):
    """从 KnowledgeBridge/行情/合规 引擎拉外部知识"""
    external = []
    channel = channel or ""

    # 1. 行情快照
    if channel in ("A_STOCK", "ETF", "METAL"):
        prices = conn.execute("""SELECT * FROM mt_gobelin_price
            WHERE channel=? ORDER BY fetched_at DESC LIMIT 3""", (channel,)).fetchall()
        for p in prices:
            p = dict(p)
            external.append({
                "source": "MARKET_DATA",
                "asset": p.get("asset_name", ""),
                "last_price": p.get("last_price", 0),
                "chg_pct": p.get("chg_pct", 0),
                "fetched": p.get("fetched_at", ""),
            })

    # 2. 类似提案历史
    sim_count = conn.execute("""SELECT COUNT(*) FROM mt_investment_proposal
        WHERE channel LIKE ? AND status='APPROVED'
        AND created_at > datetime('now','localtime','-90 days')""",
        (f"%{channel}%",)).fetchone()[0]
    external.append({
        "source": "HISTORY",
        "note": f"近 90 天同渠道 APPROVED 提案 {sim_count} 条",
    })

    # 3. 经验库反思
    reflections = conn.execute("""SELECT subject, lessons FROM mt_gobelin_reflect_log
        WHERE lessons LIKE ? OR subject LIKE ?
        ORDER BY created_at DESC LIMIT 2""",
        (f"%{channel}%", f"%{channel}%")).fetchall()
    for r in reflections:
        r = dict(r)
        external.append({
            "source": "REFLECT_LOG",
            "subject": r.get("subject", "")[:80],
            "lessons": (r.get("lessons", "") or "")[:200],
        })

    return external


def _generate_plan_summary(prop, tier, roles, weights, lead, risk, complexity, urgency, similar):
    """生成人类可读的方案摘要"""
    ch = prop.get("channel", "")
    amt = float(prop.get("amount", 0) or 0)
    tier_names = {"L1": "个体单兵", "L2": "三体小组", "L3": "专业团队", "L4": "多中心联合作战", "L5": "集团军级"}

    top_roles = sorted(weights.items(), key=lambda x: -x[1])[:3]
    role_str = " → ".join(f"{r}({w:.0%})" for r, w in top_roles)

    lead_str = f"主责 AI: {lead.get('name', '')}" if lead else "自动调配"
    sim_str = f" ({len(similar)} 条历史类似成功)" if similar else ""

    return f"""📋 {tier_names.get(tier, tier)} 协作方案
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 金额: ¥{amt:,.0f}  |  📡 渠道: {ch}
⚠️ 风险: {risk}  |  🧩 复杂度: {complexity:.2f}  |  ⏱️ 紧急度: {urgency:.2f}
🎭 角色组合(Top3权重): {role_str}
👤 {lead_str}
📚 历史经验{sim_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


# ═══════════════════════════════════════════════════════════════════
# §3 痕迹 + 纪要
# ═══════════════════════════════════════════════════════════════════

def _write_trace(conn, plan_id, proposal_id, step_order, trace_type,
                 actor_role, actor_employee, action,
                 input_snapshot="", output_snapshot="",
                 decision_point="", adopted="", rejected="",
                 reasoning="", weight_in_plan=0):
    """写一条东亚流痕迹"""
    try:
        trace_hash = hashlib.sha256(
            f"{plan_id}:{step_order}:{trace_type}:{_now()}:{hash(action) if action else ''}".encode()
        ).hexdigest()[:24]

        # adopted/rejected 如果是 list 就转 JSON
        if isinstance(adopted, (list, dict)): adopted = json.dumps(adopted, ensure_ascii=False)
        if isinstance(rejected, (list, dict)): rejected = json.dumps(rejected, ensure_ascii=False)
        if isinstance(input_snapshot, (list, dict)): input_snapshot = json.dumps(input_snapshot, ensure_ascii=False)
        if isinstance(output_snapshot, (list, dict)): output_snapshot = json.dumps(output_snapshot, ensure_ascii=False)

        conn.execute("""INSERT INTO mt_collab_trace
            (plan_id, proposal_id, step_order, trace_type, actor_role, actor_employee,
             action, input_snapshot, output_snapshot, decision_point,
             adopted, rejected, reasoning, weight_in_plan, trace_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (plan_id, proposal_id, step_order, trace_type, actor_role, actor_employee,
             action, input_snapshot, output_snapshot, decision_point,
             adopted, rejected, reasoning, weight_in_plan, trace_hash))
        return True
    except Exception as e:
        sys.stderr.write(f"[COLLAB] write_trace: {e}\n")
        return False


def _generate_minutes(conn, plan_id, proposal_id, prop, roles, weights, lead, supporting):
    """自动生成纪要 (Markdown)"""
    participants = []
    if lead:
        participants.append({"name": lead.get("name", ""), "role": lead.get("role", ""), "center": lead.get("center", ""), "main": True})
    for s in supporting:
        participants.append({"name": s.get("name", ""), "role": s.get("role", ""), "center": s.get("center", ""), "main": False})

    # 按权重排序角色
    sorted_roles = sorted(weights.items(), key=lambda x: -x[1])

    # 决策: 每个角色做什么
    decisions = []
    for r, w in sorted_roles:
        decisions.append({
            "role": r,
            "weight": w,
            "action": _role_action_map(r),
            "expected_output": _role_output_map(r),
        })

    # 考虑过但放弃的方案
    channel = prop.get("channel", "")
    alt_considered = [
        {"option": "直接由个体 AI 执行 (L1)", "rejected_reason": f"金额¥{float(prop.get('amount',0) or 0):,.0f} 超过 L1 阈值", "saved_time": "10min", "risk": "MEDIUM"},
    ]

    # Markdown 纪要
    md_lines = [
        f"# 📋 协作纪要 #{plan_id} (Proposal #{proposal_id})",
        "",
        f"**生成时间**: {_now()}",
        f"**自动纪要员**: MINUTES 角色",
        "",
        "## 📌 提案信息",
        f"- **渠道**: {channel}",
        f"- **金额**: ¥{float(prop.get('amount',0) or 0):,.0f}",
        f"- **类型**: {prop.get('ptype', '') or prop.get('proposal_type', '') or 'STANDARD'}",
        f"- **标题**: {(prop.get('title') or '')[:60]}",
        "",
        "## 🎭 参与角色 (按权重)",
    ]
    for r, w in sorted_roles:
        md_lines.append(f"- **{r}** — 权重 {w:.0%}")

    md_lines += [
        "",
        "## 👥 参与 AI 员工",
    ]
    for p in participants:
        main_tag = " ⭐主责" if p.get("main") else ""
        md_lines.append(f"- {p['name']} ({p['role']}, {p['center']}){main_tag}")

    md_lines += [
        "",
        "## ✅ 决策事项",
    ]
    for d in decisions:
        md_lines.append(f"- **{d['role']}** (权重{d['weight']:.0%}): {d['action']} → 产出 {d['expected_output']}")

    md_lines += [
        "",
        "## ❌ 考虑过但放弃的方案",
    ]
    for a in alt_considered:
        md_lines.append(f"- **{a['option']}**: {a['rejected_reason']} (节省{a['saved_time']}, 风险{a['risk']})")

    md_lines += [
        "",
        "## 🔍 关键洞察",
        "- 协作层级自动匹配 (基于金额 + 渠道 + 风险)",
        "- 角色权重动态计算 (基于风险/复杂度/紧急度)",
        "- 历史成功经验自动检索 (类似 proposal 的历史方案)",
        "",
        "## ⚡ 待办事项",
        "- [ ] 议会表决 (如需)",
        "- [ ] 印章授权 (如需)",
        "- [ ] 执行下单 (APPROVED 后)",
        "- [ ] 结果汇报 (执行完成后)",
    ]

    minutes_md = "\n".join(md_lines)

    try:
        conn.execute("""INSERT OR REPLACE INTO mt_collab_minutes
            (plan_id, proposal_id, title, participants, decisions,
             key_insights, action_items, risks_identified,
             alternatives_considered, minutes_markdown, auto_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (plan_id, proposal_id,
             f"提案 #{proposal_id} 协作纪要",
             json.dumps(participants, ensure_ascii=False),
             json.dumps(decisions, ensure_ascii=False),
             json.dumps(["协作层级自动匹配", "角色权重动态计算", "历史经验检索"], ensure_ascii=False),
             json.dumps(["议会表决", "印章授权", "执行下单", "结果汇报"], ensure_ascii=False),
             json.dumps([r.get("risk", "MEDIUM") for r in alt_considered], ensure_ascii=False),
             json.dumps(alt_considered, ensure_ascii=False),
             minutes_md))
        return True
    except Exception as e:
        sys.stderr.write(f"[COLLAB] minutes: {e}\n")
        return False


# 角色 → 做什么
def _role_action_map(role):
    return {
        "AI_EMPLOYEE": "独立完成分析+执行",
        "TRIO_DECISION": "三体小组的决策脑 — 拍板方向",
        "TRIO_ANALYST": "三体小组的分析眼 — 挖掘机会/风险",
        "TRIO_EXECUTOR": "三体小组的执行手 — 落地操作",
        "TEAM_LEAD": "专业团队 leader — 协调分工",
        "TEAM_ANALYST": "团队分析岗 — 深度研究",
        "TEAM_EXECUTOR": "团队执行岗 — 具体操作",
        "PARLIAMENT": "议会表决 (25席)",
        "BETA_RISK": "风险评估 + VETO 触发",
        "SEAL": "印章授权 (合规门)",
        "ADVISOR": "顾问 — 外部视角关键洞察",
        "PROFESSOR": "教授 — 方法论指导 + 反推校正",
        "EXTERNAL": "外部外援 (KnowledgeBridge 全网知识)",
        "MINUTES": "纪要员 — 全程自动记录",
        "COMMANDER": "集团军总指挥 — 多中心战略协调",
        "ALLIANCE": "AI 社区联盟 — 跨集团军联合",
    }.get(role, "待定义")


def _role_output_map(role):
    return {
        "AI_EMPLOYEE": "完整执行单",
        "TRIO_DECISION": "方向决策 memo",
        "TRIO_ANALYST": "分析报告",
        "TRIO_EXECUTOR": "执行结果",
        "TEAM_LEAD": "团队分工表 + 协调纪要",
        "TEAM_ANALYST": "深度研究报告",
        "TEAM_EXECUTOR": "执行流水",
        "PARLIAMENT": "表决结果 (FOR/AGAINST/VETO)",
        "BETA_RISK": "风险评估报告",
        "SEAL": "印章 token",
        "ADVISOR": "关键 insight",
        "PROFESSOR": "方法论点评 + 反推校正建议",
        "EXTERNAL": "全网知识摘要",
        "MINUTES": "完整协作纪要 (Markdown)",
        "COMMANDER": "战略协调方案",
        "ALLIANCE": "联盟联合作战计划",
    }.get(role, "待定义")


# ═══════════════════════════════════════════════════════════════════
# §4 派单 + 成长追踪
# ═══════════════════════════════════════════════════════════════════

def dispatch_proposal(proposal_id, conn=None, verbose=True):
    """
    📋 派单 — 把协作方案分配给各角色执行
    (当前阶段: 写痕迹 + 标记 DISPATCHED, 执行阶段对接 finance_autonomous_engine)
    """
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)

    # 先确保有分析方案
    plan = conn.execute(
        "SELECT * FROM mt_collab_plan WHERE proposal_id=?", (proposal_id,)).fetchone()
    if not plan:
        analyze_proposal(proposal_id, conn, verbose=False)
        plan = conn.execute(
            "SELECT * FROM mt_collab_plan WHERE proposal_id=?", (proposal_id,)).fetchone()
    if not plan:
        return {"ok": False, "error": "plan generation failed"}
    plan = dict(plan)
    plan_id = plan["id"]

    # 写派单痕迹
    conn.execute("UPDATE mt_collab_plan SET status='DISPATCHED', updated_at=datetime('now','localtime') WHERE id=?",
                 (plan_id,))

    # 为每个角色写派单痕迹 (权重从 role_weights 里取)
    weights = json.loads(plan.get("role_weights", "{}") or "{}")
    roles = json.loads(plan.get("recommended_roles", "[]") or "[]")

    step = 2
    for role in roles:
        w = weights.get(role, 0.1)
        _write_trace(conn, plan_id, proposal_id, step_order=step,
                     trace_type="DISPATCH", actor_role=role,
                     actor_employee="AUTO_ASSIGN",
                     action=f"派单给 {role} — {_role_action_map(role)}",
                     output_snapshot=json.dumps({
                         "weight": w, "expected_output": _role_output_map(role)
                     }, ensure_ascii=False),
                     reasoning=f"方案权重 {w:.0%}, 角色 {role} 职责",
                     weight_in_plan=w)
        step += 1

    # 主责 AI 派单
    lead = plan.get("lead_employee", "")
    if lead:
        _write_trace(conn, plan_id, proposal_id, step_order=step,
                     trace_type="DISPATCH", actor_role="LEAD",
                     actor_employee=lead,
                     action=f"主责员工 {lead} 收到提案 #{proposal_id}",
                     decision_point="主责确认 + 启动执行准备",
                     weight_in_plan=weights.get("LEAD", weights.get("COMMANDER", 0.3)))
        step += 1

    conn.commit()

    if verbose:
        print(f"  📋 方案 #{plan_id} 已 DISPATCHED — {len(roles)} 个角色已派单")

    # 成长追踪: 主责 AI 处理了一个新提案
    if lead:
        try:
            _update_growth(conn, lead, plan.get("tier", "L1"))
        except Exception as e:
            sys.stderr.write(f"[COLLAB] growth update: {e}\n")

    if own: conn.close()
    return {"ok": True, "plan_id": plan_id, "dispatched_roles": len(roles)}


def _update_growth(conn, employee_id, tier):
    """从小我到大我 — 成长追踪"""
    growth = conn.execute(
        "SELECT * FROM mt_collab_growth WHERE employee_id=?", (employee_id,)).fetchone()

    if growth:
        g = dict(growth)
        conn.execute("""UPDATE mt_collab_growth SET
            proposals_handled = proposals_handled + 1,
            teams_led = teams_led + CASE WHEN ? IN ('L3','L4','L5') THEN 1 ELSE 0 END,
            complex_problems_solved = complex_problems_solved + CASE WHEN ? IN ('L4','L5') THEN 1 ELSE 0 END,
            growth_evidence = json_insert(COALESCE(growth_evidence,'[]'), '$[#]', ?),
            created_at = datetime('now','localtime')
            WHERE id=?""",
            (tier, tier, tier, g["id"]))
    else:
        conn.execute("""INSERT INTO mt_collab_growth
            (employee_id, from_tier, to_tier, proposals_handled, growth_evidence)
            VALUES (?, ?, ?, 1, json(?))""",
            (employee_id, tier, tier, json.dumps([tier], ensure_ascii=False)))

    conn.commit()


# ═══════════════════════════════════════════════════════════════════
# §5 批量 + 守护 + Flask
# ═══════════════════════════════════════════════════════════════════

def run_pending_proposals(limit=10, conn=None, verbose=True):
    """批量处理 PENDING/APPROVED 但没协作方案的提案"""
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)

    pending = conn.execute("""SELECT p.* FROM mt_investment_proposal p
        WHERE p.status IN ('APPROVED', 'PENDING', 'OPEN')
        AND p.id NOT IN (SELECT proposal_id FROM mt_collab_plan)
        ORDER BY p.created_at DESC LIMIT ?""", (limit,)).fetchall()

    done = 0
    for p in pending:
        p = dict(p)
        try:
            result = analyze_proposal(p["id"], conn, verbose=verbose)
            if result.get("ok"):
                dispatch_proposal(p["id"], conn, verbose=verbose)
                done += 1
        except Exception as e:
            sys.stderr.write(f"[COLLAB] proposal #{p['id']}: {e}\n")

    conn.commit()
    if own: conn.close()
    return {"analyzed": done, "total_pending": len(pending)}


def trace_proposal(proposal_id, conn=None):
    """查看协作痕迹"""
    own = conn is None
    conn = conn or _conn()

    plan = conn.execute(
        "SELECT * FROM mt_collab_plan WHERE proposal_id=?", (proposal_id,)).fetchone()
    traces = conn.execute("""SELECT * FROM mt_collab_trace WHERE proposal_id=? ORDER BY step_order""",
                          (proposal_id,)).fetchall()
    minutes = conn.execute(
        "SELECT * FROM mt_collab_minutes WHERE proposal_id=?", (proposal_id,)).fetchone()
    growth = conn.execute("""SELECT * FROM mt_collab_growth WHERE employee_id IN
        (SELECT lead_employee FROM mt_collab_plan WHERE proposal_id=?)""",
        (proposal_id,)).fetchall()

    result = {
        "plan": dict(plan) if plan else None,
        "traces": [dict(t) for t in traces],
        "minutes": dict(minutes) if minutes else None,
        "growth": [dict(g) for g in growth],
    }
    if own: conn.close()
    return result


def run_collab_daemon(interval_sec=600):
    """协作守护循环 (默认 10min 一轮)"""
    print(f"\n🧩 Proposal Collaboration Daemon 启动 (interval={interval_sec}s)")
    print(f"   ① 每 {interval_sec}s: 批量处理 PENDING 提案")
    print(f"   ② 自动生成协作方案 + 派单 + 痕迹 + 纪要\n")

    init_tables()
    while True:
        try:
            tick = run_pending_proposals(limit=5, verbose=True)
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n🛑 Collab Daemon 退出")
            break
        except Exception as e:
            traceback.print_exc()
            sys.stderr.write(f"[COLLAB] daemon error: {e}\n")
            time.sleep(interval_sec)


# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Proposal Collaboration Engine")
    parser.add_argument("--analyze", type=int, help="智能分析指定提案")
    parser.add_argument("--dispatch", type=int, help="派单指定提案")
    parser.add_argument("--trace", type=int, help="查看协作痕迹")
    parser.add_argument("--run-pending", action="store_true", help="批量处理待协作提案")
    parser.add_argument("--daemon", action="store_true", help="常驻守护")
    parser.add_argument("--init", action="store_true", help="仅建表")
    args = parser.parse_args()

    if args.init:
        print("Tables:", init_tables())
    elif args.analyze:
        print(json.dumps(analyze_proposal(args.analyze), ensure_ascii=False, indent=2, default=str))
    elif args.dispatch:
        print(json.dumps(dispatch_proposal(args.dispatch), ensure_ascii=False, indent=2, default=str))
    elif args.trace:
        t = trace_proposal(args.trace)
        if t.get("plan"):
            p = t["plan"]
            print(f"\n📋 协作方案 #{p.get('id')} (Proposal #{p.get('proposal_id')})")
            print(f"   层级: {p.get('tier')}  风险: {p.get('risk_level')}  状态: {p.get('status')}")
            print(f"   主责: {p.get('lead_employee')}")
            print(f"   角色配比: {p.get('role_weights')}")
        if t.get("traces"):
            print(f"\n🔍 痕迹流水 ({len(t['traces'])} 步):")
            for tr in t["traces"]:
                print(f"   #{tr.get('step_order')} [{tr.get('trace_type')}] {tr.get('actor_role')} → {tr.get('action')[:60]}")
        if t.get("minutes"):
            print(f"\n📝 纪要: {t['minutes'].get('minutes_markdown', '')[:300]}...")
    elif args.run_pending:
        print(json.dumps(run_pending_proposals(), ensure_ascii=False, indent=2, default=str))
    elif args.daemon:
        run_collab_daemon()
    else:
        parser.print_help()