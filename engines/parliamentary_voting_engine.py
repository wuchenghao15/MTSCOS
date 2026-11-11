#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🏛️ AI 议会表决引擎
#  flow_parliament_voting_20261112
#
#  设计哲学:
#  ──────────────────────────────────────────────────────────────
#  25 席 AI 议会 → 提案分级 → 加权表决 → BETA VETO
#  每议员独立评估, 互不干扰, 结果可追溯
#
#  议员构成:
#  L1 (3席 × 权重3):   ALPHA(CIO) · BETA(风控,VETO) · GAMMA(资产配置)
#  L2 (8席 × 权重2):   QUANT · MACRO · SENTIMENT · TECH · FUNDAMENTAL
#                      RISK · LIQUIDITY · DIVERSIFICATION
#  L3 (10席 × 权重1):  各渠道专家 (A_STOCK/ETF/FUND/BANK/METAL/FUTURES/BOND/DERIV/CRYPTO/ALGO)
#  L4 (2席 列席):      观察团 (无表决权)
#
#  提案分级:
#  MICRO    < ¥5k      → 直接过 (自动 APPROVED)
#  STANDARD ¥5k-50k    → L2+L3 表决, >50% 加权
#  MAJOR    ¥50k-200k  → L1+L2+L3,   >66% 加权
#  MEGA     > ¥200k    → 全议会,     >75% 加权 + BETA VETO
#
#  BETA VETO (一票否决):
#  - 单笔 > 总资产 10%
#  - 或 现金占比 < 10% 且金额 > ¥10k
#  - 或 风险评分 > 80
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, sys, hashlib, random, time
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT_ROOT, "database", "app.db")

# ── 25 席议员 ──
PARLIAMENT_MEMBERS = [
    # member_code, name, layer, weight, veto_power, role_desc
    ("PARL-ALPHA",       "ALPHA 首席投资官",  "L1", 3, 0, "CIO, 最终投资方向决策者"),
    ("PARL-BETA",        "BETA 风控总监",      "L1", 3, 1, "CRO, 唯一拥有 VETO 权"),
    ("PARL-GAMMA",       "GAMMA 资产配置官",   "L1", 3, 0, "资产配置比例, 再平衡"),

    ("PARL-QUANT",       "QUANT 量化专家",     "L2", 2, 0, "因子模型, 统计套利"),
    ("PARL-MACRO",       "MACRO 宏观分析师",   "L2", 2, 0, "GDP/利率/通胀/汇率"),
    ("PARL-SENTIMENT",   "SENTIMENT 情绪",     "L2", 2, 0, "舆情/北向资金/融资融券"),
    ("PARL-TECH",        "TECH 技术面分析",    "L2", 2, 0, "K线/形态/均线/MACD"),
    ("PARL-FUNDAMENTAL", "FUNDAMENTAL 基本面", "L2", 2, 0, "PE/PB/ROE/增长"),
    ("PARL-RISK",        "RISK 风险评估",      "L2", 2, 0, "VaR/最大回撤/相关性"),
    ("PARL-LIQUIDITY",   "LIQUIDITY 流动性",   "L2", 2, 0, "成交/滑点/冲击成本"),
    ("PARL-DIVERSIFY",   "DIVERSIFY 分散化",   "L2", 2, 0, "相关性/行业集中度"),

    ("PARL-ASTOCK",      "A股专家",            "L3", 1, 0, "沪/深/创业板"),
    ("PARL-ETF",         "ETF 专家",           "L3", 1, 0, "宽基/行业/跨境ETF"),
    ("PARL-FUND",        "基金专家",           "L3", 1, 0, "公募/私募/FOF"),
    ("PARL-BANK",        "银行产品专家",       "L3", 1, 0, "定存/理财/结构性"),
    ("PARL-METAL",       "贵金属专家",         "L3", 1, 0, "黄金/白银/铂金"),
    ("PARL-FUTURES",     "期货专家",           "L3", 1, 0, "商品/金融期货"),
    ("PARL-BOND",        "债券专家",           "L3", 1, 0, "国债/信用债/可转债"),
    ("PARL-DERIV",       "衍生品专家",         "L3", 1, 0, "期权/权证/互换"),
    ("PARL-CRYPTO",      "加密资产专家",       "L3", 1, 0, "BTC/ETH/DeFi"),
    ("PARL-ALGO",        "算法交易专家",       "L3", 1, 0, "做市/高频/执行算法"),

    ("PARL-OBSERVER-1",  "观察团 · 研究员",     "L4", 0, 0, "列席, 无表决权"),
    ("PARL-OBSERVER-2",  "观察团 · 合规官",     "L4", 0, 0, "列席, 无表决权"),
]

LAYERS = {"L1": [], "L2": [], "L3": [], "L4": []}
for m in PARLIAMENT_MEMBERS:
    LAYERS[m[2]].append(m)

TOTAL_VOTING = sum(1 for m in PARLIAMENT_MEMBERS if m[3] > 0)  # 23 (L4 弃权)
TOTAL_WEIGHT = sum(m[3] for m in PARLIAMENT_MEMBERS if m[3] > 0)  # 3*3 + 8*2 + 10*1 = 9+16+10 = 35

# ── 提案分级阈值 ──
TIER_MICRO    = 5_000
TIER_STANDARD = 50_000
TIER_MAJOR    = 200_000

CHANNEL_SEAL_MAP = {
    "A_STOCK":      "INVEST_SEAL",
    "ETF":          "INVEST_SEAL",
    "FUND":         "INVEST_SEAL",
    "METAL":        "INVEST_SEAL",
    "FUTURES":      "INVEST_SEAL",
    "BOND":         "INVEST_SEAL",
    "BANK_DEPOSIT": "FINANCE_SEAL",
    "CASH":         "FINANCE_SEAL",
}


def _conn():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row_to_dict(row):
    """安全 Row → dict (Python 3.14 Row 对象无 .get() 方法)"""
    if row is None:
        return {}
    return dict(row)


# ═══════════════════════════════════════════════════════════════════
# §1 提案分级
# ═══════════════════════════════════════════════════════════════════

def classify_proposal(amount, channel=None, ptype=None):
    """
    返回 (tier, needs_vote, quorum_layers, threshold_pct, description)
    """
    if amount < TIER_MICRO:
        return ("MICRO",    False, [],                0.00, "单笔 < ¥5k, 自动通过")
    elif amount < TIER_STANDARD:
        return ("STANDARD", True,  ["L2", "L3"],       0.50, "¥5k-50k, L2+L3 表决, >50% 加权")
    elif amount < TIER_MAJOR:
        return ("MAJOR",    True,  ["L1", "L2", "L3"], 0.66, "¥50k-200k, 全议会(L1+L2+L3), >66% 加权")
    else:
        return ("MEGA",     True,  ["L1", "L2", "L3"], 0.75, ">¥200k, 全议会 + BETA VETO, >75% 加权")


# ═══════════════════════════════════════════════════════════════════
# §2 辅助: 获取资产状态 (用于评估器输入)
# ═══════════════════════════════════════════════════════════════════

def _get_portfolio_state(conn):
    """
    组合总览 — 🔒 只读 Gobelin Bank 真实账户, 绝不碰沙盘 mt_sandbox_*
    用于 BETA VETO 风险判断: 单笔占比/现金比例/渠道集中度
    """
    try:
        # 主账户: GOBELIN_MAIN
        acc_row = conn.execute(
            "SELECT * FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'"
        ).fetchone()
        acc = _row_to_dict(acc_row)
        total = acc.get("total_assets", 0) or 0
        cash = acc.get("cash_balance", 0) or 0
        # 各渠道真实市值 (从 Gobelin 持仓)
        channel_rows = conn.execute(
            "SELECT channel, SUM(market_value) as mv FROM mt_gobelin_position WHERE qty>0 GROUP BY channel"
        ).fetchall()
        channel_mv = {dict(r)["channel"]: dict(r)["mv"] or 0 for r in channel_rows}
        if total == 0:
            # 兜底: 初始资金
            total = acc.get("initial_endowment", 500000) or 500000
            cash = total
        return {
            "total_assets": total,
            "cash": cash,
            "cash_pct": round((cash / total), 4) if total > 0 else 1.0,
            "channel_mv": channel_mv,
            "source": "mt_gobelin_account",  # 明确数据来源
            "scope": "REAL_ONLY",            # 明确 scope: 真实, 非沙盘
        }
    except Exception as e:
        sys.stderr.write(f"[PARLIAMENT] _get_portfolio_state fallback (可能 Gobelin 表不存在): {e}\n")
        # 最终兜底: 返回一个合理的默认, 避免 BETA VETO 永远不触发或乱触发
        return {"total_assets": 500000, "cash": 500000, "cash_pct": 1.0,
                "channel_mv": {}, "source": "DEFAULT_FALLBACK", "scope": "REAL_ONLY"}


def _get_market_snapshot(conn, channel=None):
    """从 mt_market_radar_cache 或 mt_sandbox_signals 取行情快照"""
    try:
        radar = conn.execute(
            "SELECT key, value, chg_pct FROM mt_market_radar_cache ORDER BY ts DESC LIMIT 20"
        ).fetchall()
        return {dict(r)["key"]: {"value": dict(r)["value"], "chg_pct": dict(r)["chg_pct"]} for r in radar}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════
# §3 议员评估器 (每议员独立打分 0~100)
# ═══════════════════════════════════════════════════════════════════

def _assess_ALPHA(proposal, market=None, portfolio_state=None):
    """首席投资官: 战略方向 + 金额合理性"""
    amount = proposal.get("amount", 0)
    ptype = proposal.get("ptype", "BUY")
    ps = portfolio_state or {}
    total = ps.get("total_assets", 1)
    size_ratio = amount / total if total > 0 else 0
    # 小额倾向 YES, 大额需要更强理由
    if size_ratio > 0.20:
        score = 45
    elif size_ratio > 0.10:
        score = 62
    else:
        score = 75
    if ptype == "HEDGE":
        score += 10  # 对冲加分
    if ptype == "DIVERSIFY":
        score += 8
    return max(0, min(100, score + random.randint(-5, 5)))


def _assess_BETA(proposal, market=None, portfolio_state=None):
    """风控总监: 风险评估 + VETO 判定"""
    amount = proposal.get("amount", 0)
    ps = portfolio_state or {}
    total = ps.get("total_assets", 1)
    cash_pct = ps.get("cash_pct", 1.0)
    risk_score = proposal.get("risk_score", 30)
    # VETO 条件
    size_ratio = amount / total if total > 0 else 0
    reasons = []
    if size_ratio > 0.10:
        reasons.append(f"单笔占总资产 {size_ratio:.1%} > 10%")
    if cash_pct < 0.10 and amount > 10000:
        reasons.append(f"现金占比 {cash_pct:.1%} < 10% 且金额 > ¥10k")
    if risk_score > 80:
        reasons.append(f"风险评分 {risk_score} > 80")
    if reasons:
        return (5, True, reasons)  # (score, should_veto, veto_reasons)
    # 正常评估
    score = 70 - risk_score * 0.5 - size_ratio * 100
    return (max(0, min(100, score + random.randint(-3, 3))), False, [])


def _assess_QUANT(proposal, market=None, portfolio_state=None):
    """量化: 假设 alpha 存在, 但需要信号验证"""
    score = 55 + random.randint(-15, 20)
    return max(0, min(100, score))


def _assess_MACRO(proposal, market=None, portfolio_state=None):
    """宏观: 假设当前环境中性偏多"""
    ch = proposal.get("channel", "")
    if ch in ("BANK_DEPOSIT", "BOND"):
        score = 60  # 利率环境不确定
    elif ch in ("METAL",):
        score = 68  # 贵金属作为避险
    else:
        score = 62
    return max(0, min(100, score + random.randint(-5, 5)))


def _assess_SENTIMENT(proposal, market=None, portfolio_state=None):
    """情绪: 模拟舆情"""
    score = 58 + random.randint(-20, 25)
    return max(0, min(100, score))


def _assess_TECH(proposal, market=None, portfolio_state=None):
    """技术面: 假设中性"""
    score = 55 + random.randint(-15, 15)
    return max(0, min(100, score))


def _assess_FUNDAMENTAL(proposal, market=None, portfolio_state=None):
    """基本面: 模拟 PE/PB 判断"""
    score = 60 + random.randint(-10, 15)
    return max(0, min(100, score))


def _assess_RISK(proposal, market=None, portfolio_state=None):
    """风险评估: 集中度 + 回撤"""
    ps = portfolio_state or {}
    amount = proposal.get("amount", 0)
    total = ps.get("total_assets", 1)
    ratio = amount / total if total > 0 else 0
    score = 75 - ratio * 150  # 比例越高分越低
    return max(0, min(100, score + random.randint(-5, 5)))


def _assess_LIQUIDITY(proposal, market=None, portfolio_state=None):
    """流动性"""
    ch = proposal.get("channel", "")
    if ch in ("A_STOCK", "ETF", "FUTURES"):
        base = 70  # 高流动性
    elif ch in ("BANK_DEPOSIT", "BOND"):
        base = 65
    elif ch in ("METAL",):
        base = 55
    else:
        base = 60
    return max(0, min(100, base + random.randint(-8, 8)))


def _assess_DIVERSIFY(proposal, market=None, portfolio_state=None):
    """分散化: 检查是否已有该渠道持仓"""
    ps = portfolio_state or {}
    ch = proposal.get("channel", "")
    channel_mv = ps.get("channel_mv", {})
    existing = channel_mv.get(ch, 0)
    total = ps.get("total_assets", 1)
    existing_pct = existing / total if total > 0 else 0
    if existing_pct > 0.40:
        score = 40  # 过度集中 → 反对
    elif existing_pct > 0.25:
        score = 55
    else:
        score = 72
    return max(0, min(100, score + random.randint(-5, 5)))


def _assess_default(proposal, market=None, portfolio_state=None, member_code=""):
    """L3 渠道专家: 根据 channel 匹配度打分"""
    ch = proposal.get("channel", "")
    channel_map = {
        "PARL-ASTOCK": "A_STOCK",
        "PARL-ETF": "ETF",
        "PARL-FUND": "FUND",
        "PARL-BANK": "BANK_DEPOSIT",
        "PARL-METAL": "METAL",
        "PARL-FUTURES": "FUTURES",
        "PARL-BOND": "BOND",
    }
    my_channel = channel_map.get(member_code, "")
    if my_channel and my_channel == ch:
        score = 72 + random.randint(-8, 12)  # 对口专家, 偏好
    elif my_channel:
        score = 58 + random.randint(-10, 10)  # 非对口, 中性
    else:
        score = 55 + random.randint(-15, 15)
    return max(0, min(100, score))


# 评估器注册表
_ASSESSORS = {
    "PARL-ALPHA":       _assess_ALPHA,
    "PARL-BETA":        _assess_BETA,
    "PARL-GAMMA":       _assess_ALPHA,  # GAMMA 也用类似 ALPHA 逻辑
    "PARL-QUANT":       _assess_QUANT,
    "PARL-MACRO":       _assess_MACRO,
    "PARL-SENTIMENT":   _assess_SENTIMENT,
    "PARL-TECH":        _assess_TECH,
    "PARL-FUNDAMENTAL": _assess_FUNDAMENTAL,
    "PARL-RISK":        _assess_RISK,
    "PARL-LIQUIDITY":   _assess_LIQUIDITY,
    "PARL-DIVERSIFY":   _assess_DIVERSIFY,
}


# ═══════════════════════════════════════════════════════════════════
# §4 核心 vote()
# ═══════════════════════════════════════════════════════════════════

def vote(proposal_id):
    """
    对指定提案执行议会表决。返回 dict:
      {session_id, result: PASSED/FAILED/VETOED/FILIBUSTER,
       tier, quorum, weighted_yes, weighted_no, threshold,
       veto_by, veto_reasons, duration_ms}
    """
    conn = _conn()
    try:
        # 1. 读提案
        row = conn.execute(
            "SELECT * FROM mt_investment_proposal WHERE id=?", (proposal_id,)
        ).fetchone()
        if not row:
            return {"error": f"proposal #{proposal_id} not found"}
        prop = _row_to_dict(row)

        # 已有 session → 返回已有结果
        existing = conn.execute(
            "SELECT * FROM mt_parliament_session WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
        if existing:
            return _row_to_dict(existing)

        # 2. 分级
        tier, needs_vote, quorum_layers, threshold, desc = classify_proposal(
            prop.get("amount", 0), prop.get("channel"), prop.get("ptype")
        )

        # MICRO 直接过
        if tier == "MICRO":
            session_id = _create_session(conn, proposal_id, prop, tier, 0, threshold, "PASSED")
            conn.execute(
                "UPDATE mt_investment_proposal SET status='APPROVED', parliament_id=?, vote_result='PASSED' WHERE id=?",
                (session_id, proposal_id)
            )
            conn.commit()
            return {"session_id": session_id, "result": "PASSED", "tier": tier, "reason": desc}

        # 3. 收集市场 + 组合状态
        portfolio_state = _get_portfolio_state(conn)
        market = _get_market_snapshot(conn, prop.get("channel"))

        # 4. 确定 quorum 成员
        quorum_members = []
        for layer in quorum_layers:
            quorum_members.extend(LAYERS.get(layer, []))

        t0 = time.time()

        # 5. 逐议员评估 + 投票
        weighted_yes = 0.0
        weighted_no = 0.0
        weighted_abstain = 0.0
        yes_cnt = no_cnt = abstain_cnt = 0
        veto_triggered = False
        veto_by = ""
        veto_reasons = []
        vote_logs = []

        for code, name, layer, weight, veto_pow, role in quorum_members:
            assessor = _ASSESSORS.get(code, _assess_default)
            try:
                if code == "PARL-BETA":
                    # BETA 特殊: 返回 3-tuple (score, should_veto, reasons)
                    result = assessor(prop, market, portfolio_state)
                    if isinstance(result, tuple) and len(result) == 3:
                        score, should_veto, vreasons = result
                    else:
                        score = result
                        should_veto = False
                        vreasons = []
                    if should_veto:
                        veto_triggered = True
                        veto_by = code
                        veto_reasons = vreasons
                else:
                    if assessor is _assess_default:
                        score = assessor(prop, market, portfolio_state, member_code=code)
                    else:
                        score = assessor(prop, market, portfolio_state)
            except Exception as e:
                score = 50  # 评估器异常 → 弃权倾向
                sys.stderr.write(f"[PARLIAMENT] {code} assess error: {e}\n")

            # score → vote
            if score >= 65:
                vote = "YES"
                yes_cnt += 1
                weighted_yes += weight
            elif score <= 35:
                vote = "NO"
                no_cnt += 1
                weighted_no += weight
            else:
                vote = "ABSTAIN"
                abstain_cnt += 1
                weighted_abstain += weight

            vote_logs.append({
                "member_code": code, "member_name": name, "layer": layer,
                "weight": weight, "vote": vote, "confidence": round(score/100, 2),
                "score": score, "veto_power": veto_pow,
            })

        duration_ms = int((time.time() - t0) * 1000)
        quorum = len(quorum_members)

        # 6. 计票 + 判定
        result_status = "VOTING"
        vote_result = ""
        if veto_triggered:
            result_status = "VETOED"
            vote_result = "VETO"
        else:
            total_cast = weighted_yes + weighted_no
            if total_cast == 0:
                result_status = "FILIBUSTER"
                vote_result = "FILIBUSTER"
            else:
                ratio = weighted_yes / total_cast
                if ratio >= threshold:
                    result_status = "PASSED"
                    vote_result = "PASS"
                else:
                    result_status = "FAILED"
                    vote_result = "FAIL"

        # 7. 写 session
        session_id = _create_session(
            conn, proposal_id, prop, tier, quorum, threshold,
            result_status, weighted_yes, weighted_no, yes_cnt, no_cnt, abstain_cnt,
            veto_triggered, veto_by, "; ".join(veto_reasons) if veto_reasons else "",
            duration_ms
        )

        # 8. 写 vote_log
        for v in vote_logs:
            conn.execute("""INSERT INTO mt_parliament_vote_log
                (session_id, proposal_id, member_code, member_name, layer, weight, vote,
                 confidence, score, veto_power)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, proposal_id, v["member_code"], v["member_name"],
                 v["layer"], v["weight"], v["vote"], v["confidence"], v["score"],
                 v["veto_power"]))

        # 9. 更新提案状态
        final_status = {
            "PASSED":   "APPROVED",
            "FAILED":   "REJECTED",
            "VETOED":   "REJECTED",
            "FILIBUSTER": "FILIBUSTER",
        }.get(result_status, prop.get("status", "PENDING"))

        conn.execute("""UPDATE mt_investment_proposal SET
            status=?, parliament_id=?, vote_result=?, veto_by=?,
            quorum=?, yes_votes=?, no_votes=?, abstain_votes=?, updated_at=?
            WHERE id=?""",
            (final_status, session_id, vote_result, veto_by,
             quorum, yes_cnt, no_cnt, abstain_cnt, _now(), proposal_id))

        conn.commit()

        return {
            "session_id": session_id,
            "result": result_status,
            "vote_result": vote_result,
            "tier": tier,
            "quorum": quorum,
            "yes": yes_cnt, "no": no_cnt, "abstain": abstain_cnt,
            "weighted_yes": weighted_yes, "weighted_no": weighted_no,
            "threshold": threshold,
            "veto_by": veto_by, "veto_reasons": veto_reasons,
            "duration_ms": duration_ms,
            "description": desc,
        }
    finally:
        conn.close()


def _create_session(conn, proposal_id, prop, tier, quorum, threshold,
                    status, w_yes=0, w_no=0, yes_cnt=0, no_cnt=0, abstain_cnt=0,
                    veto=False, veto_by="", veto_reason="", duration_ms=0):
    cur = conn.execute("""INSERT INTO mt_parliament_session
        (proposal_id, proposal_no, status, quorum, yes_votes, no_votes, abstain_votes,
         weighted_yes, weighted_no, threshold, veto_triggered, veto_by, veto_reason,
         finished_at, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (proposal_id, prop.get("proposal_no", ""), status, quorum,
         yes_cnt, no_cnt, abstain_cnt, w_yes, w_no, threshold,
         1 if veto else 0, veto_by, veto_reason, _now(), duration_ms))
    return cur.lastrowid


# ═══════════════════════════════════════════════════════════════════
# §5 批量表决: 给所有 PENDING / VOTING 提案投票
# ═══════════════════════════════════════════════════════════════════

def vote_all_pending(limit=50):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, proposal_no, title, amount, channel, ptype, status "
            "FROM mt_investment_proposal WHERE status IN ('PENDING','VOTING','FILIBUSTER') "
            "ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
    except Exception:
        conn.close()
        return {"error": "db read failed"}

    results = []
    for r in rows:
        pid = r["id"]
        no = r["proposal_no"]
        t0 = time.time()
        try:
            res = vote(pid)
            dt = int((time.time() - t0) * 1000)
            results.append({
                "proposal_id": pid, "proposal_no": no,
                "result": res.get("result", "?"),
                "tier": res.get("tier", "?"),
                "veto_by": res.get("veto_by", ""),
                "ms": dt,
            })
        except Exception as e:
            results.append({"proposal_id": pid, "proposal_no": no, "error": str(e)[:80]})

    passed = sum(1 for r in results if r.get("result") == "PASSED")
    failed = sum(1 for r in results if r.get("result") == "FAILED")
    vetoed = sum(1 for r in results if r.get("result") == "VETOED")
    filibuster = sum(1 for r in results if r.get("result") == "FILIBUSTER")
    return {
        "total": len(results),
        "passed": passed, "failed": failed, "vetoed": vetoed,
        "filibuster": filibuster,
        "detail": results,
    }


# ═══════════════════════════════════════════════════════════════════
# §6 快速 API: create_proposal()
# ═══════════════════════════════════════════════════════════════════

def _next_proposal_no(conn):
    """动态查最大编号+1 (防模块级计数器重启导致 UNIQUE 冲突)"""
    now = datetime.now()
    date_prefix = now.strftime('%Y%m%d')
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(proposal_no, -3) AS INTEGER)) FROM mt_investment_proposal "
        "WHERE proposal_no LIKE ?",
        (f"PR-{date_prefix}-%",)
    ).fetchone()
    max_suffix = _row_to_dict(row).get("MAX(CAST(SUBSTR(proposal_no, -3) AS INTEGER))") or 0
    next_suffix = max_suffix + 1
    return f"PR-{date_prefix}-{next_suffix:03d}"


def create_proposal(title, channel, amount, ptype="BUY", asset_code="",
                    asset_name="", qty=0, price=0, description="",
                    operator="AI_AUTO", source="AUTO", risk_score=30):
    """快速创建提案 (返回 proposal_id)"""
    conn = _conn()
    try:
        proposal_no = _next_proposal_no(conn)

        # 防重: 同 channel + asset_code + amount + ptype 最近 1h 内的重复提案
        dup = conn.execute("""SELECT id FROM mt_investment_proposal
            WHERE channel=? AND asset_code=? AND amount=? AND ptype=?
            AND created_at > datetime('now','localtime','-1 hour')
            LIMIT 1""",
            (channel, asset_code, amount, ptype)).fetchone()
        if dup:
            return {"error": "duplicate_in_last_hour", "proposal_id": dup["id"]}

        cur = conn.execute("""INSERT INTO mt_investment_proposal
            (proposal_no, title, description, channel, ptype, amount,
             asset_code, asset_name, qty, price, operator, source, risk_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proposal_no, title, description, channel, ptype, amount,
             asset_code, asset_name, qty, price, operator, source, risk_score))
        conn.commit()
        pid = cur.lastrowid
        # 自动触发表决
        vote_result = vote(pid)
        return {"proposal_id": pid, "proposal_no": proposal_no, "vote": vote_result}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §7 CLI 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--vote-all", action="store_true", help="表决所有 PENDING 提案")
    parser.add_argument("--vote", type=int, help="表决指定 proposal_id")
    parser.add_argument("--create", action="store_true", help="创建测试提案")
    parser.add_argument("--tier", type=float, help="测试分级: 指定金额")
    args = parser.parse_args()

    if args.tier is not None:
        tier, needs_vote, layers, th, desc = classify_proposal(args.tier)
        print(f"金额 ¥{args.tier:,.0f} → {tier} | needs_vote={needs_vote} | layers={layers} | threshold={th} | {desc}")

    if args.create:
        test_cases = [
            ("小额 ETF 定投",       "ETF",         3000,   "BUY",  "sh510300", "沪深300ETF", 1000, 3.0, "MICRO 测试"),
            ("A股蓝筹加仓",         "A_STOCK",     20000,  "BUY",  "sh601318", "中国平安",   200, 100.0, "STANDARD 测试"),
            ("贵金属避险配置",      "METAL",       120000, "BUY",  "AU9999",   "黄金9999",   20,  6000.0, "MAJOR 测试"),
            ("大额债券买入",        "BOND",        300000, "BUY",  "CB2025",   "可转债2025", 300, 1000.0, "MEGA 测试"),
            ("对冲操作",            "FUTURES",     80000,  "HEDGE", "IF2501",   "股指期货",   10,  8000.0, "MAJOR HEDGE 测试"),
            ("BETA VETO 测试",      "A_STOCK",     1000000,"BUY",  "sz399001", "超大盘股",   10000,100.0, "MEGA (预计 VETO)"),
        ]
        for title, ch, amt, pt, code, name, qty, pr, desc in test_cases:
            print(f"\n📋 创建: {title} ({ch} ¥{amt:,})")
            res = create_proposal(title, ch, amt, pt, code, name, qty, pr, desc)
            if "error" in res:
                print(f"  ⚠️ {res['error']}")
            else:
                v = res["vote"]
                print(f"  ✅ #{res['proposal_id']} {res['proposal_no']} → tier={v.get('tier','?')} result={v.get('result','?')} veto={v.get('veto_by','-')} ({v.get('duration_ms',0)}ms)")

    if args.vote:
        res = vote(args.vote)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.vote_all:
        print("🗳️ 批量表决 PENDING/FILIBUSTER 提案...")
        res = vote_all_pending()
        print(json.dumps(res, ensure_ascii=False, indent=2))
        print(f"\n📊 汇总: {res['total']} 张 → ✅{res['passed']} ❌{res['failed']} 🚫{res['vetoed']} ⏳{res['filibuster']}")
