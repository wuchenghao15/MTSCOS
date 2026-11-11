#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🤖 Finance Autonomous Engine
#  flow_finance_autonomous_20261113
#
#  自动投资闭环 (全自动, 无人干预):
#  ──────────────────────────────────────────────────────────────
#  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
#  │ 行情扫描 │→│ 自动提案 │→│ 议会表决 │→│ 申请用章 │→│ 渠道执行 │
#  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
#       ↑                                                    │
#       └────────── 审计链 (全链路可追溯) ←──────────────────┘
#
#  核心模块:
#  §1 MarketScanner    — 腾讯/新浪行情 → 信号 (看涨/看跌/避险)
#  §2 ProposalGenerator — 信号 → mt_investment_proposal (去重!)
#  §3 ParliamentVoter   — 调用 ParliamentaryVotingEngine.vote_all_pending
#  §4 SealAutoRequester — APPROVED → SealCenterEngine.auto_grant_all_approved
#  §5 ChannelExecutor   — 验章 → 模拟交易 → 核销 → 审计
#  §6 AutonomousCycle   — 把上面串成一个定时 cycle
#
#  运行方式:
#    python3 engines/finance_autonomous_engine.py --cycle --daemon
#    python3 engines/finance_autonomous_engine.py --once     (单次)
#    python3 engines/finance_autonomous_engine.py --report   (汇总)
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, sys, time, random, hashlib, secrets
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT_ROOT, "database", "app.db")

# 延迟导入 (避免 Flask 启动循环)
_seal = None
_parl = None


def _get_engines():
    global _seal, _parl
    if _seal is None:
        import seal_center_engine as _s
        _seal = _s
    if _parl is None:
        import parliamentary_voting_engine as _p
        _parl = _p
    return _seal, _parl


def _conn():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row_to_dict(row):
    if row is None:
        return {}
    try:
        return dict(row)
    except Exception:
        return row


# ═══════════════════════════════════════════════════════════════════
# §1 MarketScanner — 行情扫描 (新浪/腾讯 + 本地 fallback 模拟)
# ═══════════════════════════════════════════════════════════════════

# 关注标的池 (真实 A 股/ETF + 贵金属)
WATCHLIST = [
    # (channel, asset_code, asset_name, 参考价格)
    ("A_STOCK", "sh601318", "中国平安", 102.0),
    ("A_STOCK", "sz000858", "五粮液", 138.0),
    ("A_STOCK", "sh600519", "贵州茅台", 1680.0),
    ("A_STOCK", "sz300750", "宁德时代", 215.0),
    ("ETF",     "sh510300", "沪深300ETF", 3.95),
    ("ETF",     "sh510050", "上证50ETF", 2.85),
    ("ETF",     "sz159915", "创业板ETF", 2.15),
    ("METAL",   "AU9999",   "黄金9999", 620.0),   # 元/克
    ("METAL",   "AG(T+D)",  "白银T+D",  7200.0),  # 元/千克
    ("BOND",    "CB2025",   "可转换债券", 108.0),
]


def scan_market():
    """
    扫描行情 + 生成信号。
    返回 [{channel, asset_code, asset_name, price, chg_pct, signal, confidence, amount_suggestion, ...}]
    """
    signals = []

    # 尝试真实行情 (新浪/腾讯). 失败就用本地模拟.
    real_quotes = {}
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from services.market_data_service import MarketDataService
        svc = MarketDataService()
        # 只扫 A 股 + ETF (新浪接口)
        codes = [w[1] for w in WATCHLIST if w[0] in ("A_STOCK", "ETF")]
        if codes:
            data = svc.get_all_for_sandbox()
            for code in codes:
                for k, v in (data or {}).items():
                    if code in k.lower():
                        try:
                            real_quotes[code] = {
                                "price": float(v.get("latest", v.get("close", 0))),
                                "chg_pct": float(v.get("chg_pct", v.get("change", 0))),
                            }
                        except Exception:
                            pass
    except Exception as e:
        sys.stderr.write(f"[AUTONOMOUS] 真实行情获取失败, 降级本地模拟: {e}\n")

    for channel, code, name, ref_price in WATCHLIST:
        if code in real_quotes:
            price = real_quotes[code]["price"] or ref_price
            chg_pct = real_quotes[code]["chg_pct"]
        else:
            # 本地模拟: 基于 ref_price 做随机 ±3% 波动
            chg_pct = random.uniform(-0.03, 0.03)
            price = ref_price * (1 + chg_pct)

        # 信号判定 (简化版)
        chg = chg_pct  # e.g. 0.015 = +1.5%
        if chg > 0.015:
            signal = "BUY"
            confidence = min(0.95, 0.5 + chg * 15)
        elif chg < -0.015:
            signal = "SELL"
            confidence = min(0.95, 0.5 + abs(chg) * 15)
        elif -0.005 <= chg <= 0.005:
            signal = "HOLD"
            confidence = 0.3
        elif channel == "METAL" and chg > 0.008:
            signal = "BUY"  # 贵金属避险
            confidence = 0.6
        else:
            signal = "HOLD"
            confidence = 0.4

        # 建议金额 (基于资产类别 + 置信度)
        base = {
            "A_STOCK": 20000, "ETF": 15000, "FUND": 10000,
            "METAL": 12000, "BOND": 20000, "BANK_DEPOSIT": 50000,
        }.get(channel, 10000)
        amount = int(base * confidence * random.uniform(0.8, 1.2))
        amount = max(1000, min(amount, 180000))  # 上限 INVEST_SEAL per_tx_limit=200k

        signals.append({
            "channel": channel, "asset_code": code, "asset_name": name,
            "price": round(price, 2), "chg_pct": round(chg_pct, 4),
            "signal": signal, "confidence": round(confidence, 2),
            "amount_suggestion": amount,
            "qty": round(amount / price, 2) if price > 0 else 0,
        })

    return signals


# ═══════════════════════════════════════════════════════════════════
# §2 ProposalGenerator — 信号 → 提案 (去重!)
# ═══════════════════════════════════════════════════════════════════

def _make_proposal_hash(channel, asset_code, amount, ptype):
    """用于去重: 同一 channel+asset+amount+ptype 1h 内不重复"""
    raw = f"{channel}|{asset_code}|{amount}|{ptype}|{datetime.now().strftime('%Y%m%d%H')}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def generate_proposals(signals, max_per_cycle=5, min_confidence=0.5):
    """
    从扫描信号中挑出最值得做的 → 创建提案。
    SELL 前置校验: 必须在 Gobelin Bank 有持仓, 且卖量 ≤ 可卖量
    BUY 前置校验: 检查现金够不够
    返回 [{proposal_id, proposal_no, vote_result, seal_result}]
    """
    parl = _get_engines()[1]
    results = []

    # 预加载 Gobelin Bank 真实持仓 + 现金 (一次查询, 防 N+1)
    conn = _conn()
    try:
        positions = [dict(r) for r in conn.execute("""
            SELECT channel, asset_code, asset_name, qty, available_qty, avg_cost_basis
            FROM mt_gobelin_position WHERE qty > 0""").fetchall()]
        cash_row = conn.execute(
            "SELECT cash_balance FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'"
        ).fetchone()
        cash_available = (dict(cash_row).get("cash_balance", 0) if cash_row else 0) or 0
    finally:
        conn.close()

    pos_key = {(p["channel"], p["asset_code"]): p for p in positions}

    # 过滤: 只做有信心的 + 排序 + SELL 前置校验
    actionable = []
    for s in signals:
        if s["signal"] not in ("BUY", "SELL") or s["confidence"] < min_confidence:
            continue
        ch = s["channel"]
        code = s["asset_code"]
        qty = s["qty"]

        if s["signal"] == "SELL":
            # 🔒 SELL 前置校验: 必须有持仓且可卖量足够
            pos = pos_key.get((ch, code))
            if not pos:
                results.append({
                    "skipped_no_position": True, "asset": s["asset_name"],
                    "ptype": "SELL", "reason": "Gobelin Bank 无此持仓, 不能凭空卖",
                })
                continue
            avail = pos.get("available_qty", 0)
            if avail < qty * 0.95:  # 允许 5% 误差
                # 卖量 > 可卖量 → 自动缩减为可卖量
                qty = avail
                amount = round(qty * s["price"], 2)
                s = dict(s); s["qty"] = qty; s["amount_suggestion"] = amount
                sys.stderr.write(f"[AUTONOMOUS] SELL {s['asset_name']} 卖量超限, 自动缩为 {avail:.1f}\n")
            s["qty"] = qty  # 更新实际可卖量
        elif s["signal"] == "BUY":
            # 🔒 BUY 前置校验: 现金够不够
            if s["amount_suggestion"] > cash_available * 0.9:
                s["amount_suggestion"] = round(cash_available * 0.5, 2)
                s["qty"] = round(s["amount_suggestion"] / s["price"], 2)
                sys.stderr.write(f"[AUTONOMOUS] BUY 现金不足, 自动缩为 ¥{s['amount_suggestion']:,.0f}\n")

        actionable.append(s)

    actionable.sort(key=lambda x: x["confidence"], reverse=True)
    actionable = actionable[:max_per_cycle]

    for s in actionable:
        # 先查重 (1h 内)
        conn = _conn()
        try:
            dup = conn.execute("""SELECT id FROM mt_investment_proposal
                WHERE channel=? AND asset_code=? AND ptype=?
                AND ABS(amount - ?) < 100
                AND created_at > datetime('now','localtime','-1 hour')
                LIMIT 1""",
                (s["channel"], s["asset_code"], s["signal"], s["amount_suggestion"])).fetchone()
            if dup:
                results.append({
                    "skipped_duplicate": True,
                    "proposal_id": dup["id"],
                    "reason": "duplicate_in_1h_window",
                })
                continue
        finally:
            conn.close()

        # 创建提案 (自动触发议会表决)
        title = f"[AUTONOMOUS] {s['signal']} {s['asset_name']} ({s['channel']})"
        try:
            res = parl.create_proposal(
                title=title,
                channel=s["channel"],
                amount=s["amount_suggestion"],
                ptype=s["signal"],  # BUY / SELL
                asset_code=s["asset_code"],
                asset_name=s["asset_name"],
                qty=s["qty"],
                price=s["price"],
                description=f"行情扫描 chg={s['chg_pct']:.1%} confidence={s['confidence']:.0%}",
                operator="FinanceAutonomousEngine",
                source="AUTO",
                risk_score=int(50 - s["confidence"] * 30),  # 高置信度 = 低风险分
            )
            vote = res.get("vote", {})
            results.append({
                "proposal_id": res.get("proposal_id"),
                "proposal_no": res.get("proposal_no"),
                "vote_result": vote.get("result", "?"),
                "tier": vote.get("tier", "?"),
                "veto_by": vote.get("veto_by", ""),
                "skipped_duplicate": False,
            })
        except Exception as e:
            results.append({"error": str(e)[:120], "signal": s["asset_name"]})

    return results


# ═══════════════════════════════════════════════════════════════════
# §3 SealAutoRequester — 批量给所有 APPROVED 提案发章
# ═══════════════════════════════════════════════════════════════════

def auto_grant_proposals(limit=20):
    """调用 SealCenterEngine.auto_grant_all_approved"""
    seal = _get_engines()[0]
    return seal.auto_grant_all_approved(limit=limit)


# ═══════════════════════════════════════════════════════════════════
# §4 Gobelin Account 汇总 + 价格刷新 (独立于 ChannelExecutor)
# ═══════════════════════════════════════════════════════════════════

def refresh_gobelin_prices():
    """
    刷新 mt_gobelin_position 所有持仓的 current_price → 算 PnL → 更新 mt_gobelin_account。
    优先用真实行情 (腾讯/新浪), 失败用本地模拟。
    """
    conn = _conn()
    try:
        positions = [dict(r) for r in conn.execute("SELECT * FROM mt_gobelin_position WHERE qty>0").fetchall()]
    finally:
        conn.close()

    if not positions:
        return {"positions": 0, "message": "no positions"}

    # 尝试真实行情
    real_prices = {}
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from services.market_data_service import MarketDataService
        svc = MarketDataService()
        codes = [p["asset_code"] for p in positions if p["channel"] in ("A_STOCK", "ETF")]
        if codes:
            data = svc.get_all_for_sandbox() or {}
            for p in positions:
                for k, v in data.items():
                    if p["asset_code"].lower() in k.lower():
                        try:
                            real_prices[p["asset_code"]] = float(v.get("latest", v.get("close", p["current_price"])))
                        except Exception:
                            pass
    except Exception as e:
        sys.stderr.write(f"[PRICE-REFRESH] 真实行情失败, 本地模拟: {e}\n")

    conn = _conn()
    total_mv = 0
    total_cost = 0
    total_pnl = 0
    total_today_pnl = 0

    for p in positions:
        code = p["asset_code"]
        # 价格更新 (真实优先, 否则在原 price 基础上随机 ±1.5%)
        if code in real_prices:
            new_price = real_prices[code]
            source = "TENCENT"
        else:
            base = p["current_price"] or p["avg_cost_basis"]
            # 模拟: 围绕昨收 ±1.5% 波动
            prev = p["prev_close"] or base
            new_price = round(prev * random.uniform(0.985, 1.015), 2)
            source = "SIMULATED"

        qty = p["qty"]
        cost = p["avg_cost_basis"] or 0
        mv = round(qty * new_price, 2)
        pnl = round(mv - cost * qty, 2)
        pnl_pct = round(pnl / (cost * qty) * 100, 2) if cost > 0 else 0
        # 今日盈亏 = (new_price - prev_close) * qty
        today_pnl = round((new_price - (p["prev_close"] or new_price)) * qty, 2)
        prev_close = p["prev_close"] or new_price

        conn.execute("""UPDATE mt_gobelin_position SET
            current_price=?, market_value=?, unrealized_pnl=?, unrealized_pnl_pct=?,
            today_pnl=?, prev_close=?, updated_at=?
            WHERE id=?""",
            (new_price, mv, pnl, pnl_pct, today_pnl, prev_close, _now(), p["id"]))

        total_mv += mv
        total_cost += cost * qty
        total_pnl += pnl
        total_today_pnl += today_pnl

    # 更新 Account 汇总
    cash_row = conn.execute("SELECT cash_balance FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'").fetchone()
    cash = _row_to_dict(cash_row).get("cash_balance", 0) if cash_row else 0
    total_assets = round(cash + total_mv, 2)

    conn.execute("""UPDATE mt_gobelin_account SET
        total_assets=?, position_value=?, unrealized_pnl=?,
        updated_at=? WHERE account_name='GOBELIN_MAIN'""",
        (total_assets, total_mv, total_pnl, _now()))

    conn.commit()
    conn.close()

    return {
        "positions_updated": len(positions),
        "total_mv": round(total_mv, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
        "today_pnl": round(total_today_pnl, 2),
        "cash": round(cash, 2),
        "total_assets": round(total_assets, 2),
    }


def refresh_account_summary():
    """只重新汇总账户数字 (不刷新价格)"""
    conn = _conn()
    try:
        pos_mv = conn.execute("SELECT COALESCE(SUM(market_value),0) FROM mt_gobelin_position").fetchone()[0] or 0
        pos_cost = conn.execute("SELECT COALESCE(SUM(total_cost),0) FROM mt_gobelin_position").fetchone()[0] or 0
        pos_pnl = pos_mv - pos_cost
        cash = conn.execute("SELECT cash_balance FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'").fetchone()[0] or 0
        total = round(cash + pos_mv, 2)
        conn.execute("""UPDATE mt_gobelin_account SET
            position_value=?, unrealized_pnl=?, total_assets=?,
            updated_at=? WHERE account_name='GOBELIN_MAIN'""",
            (pos_mv, pos_pnl, total, _now()))
        conn.commit()
        return {"cash": cash, "position_value": pos_mv, "total_assets": total, "unrealized_pnl": pos_pnl}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §4b ChannelExecutor — 写入 Gobelin Bank 真实表
# ═══════════════════════════════════════════════════════════════════

class ChannelExecutor:
    """
    每笔交易执行时:
    ① verify_token → ② 模拟成交价 (滑点) → ③ consume_token → ④ 写 mt_gobelin_trade
    ⑤ 更新 mt_gobelin_position (BUY 加仓/SELL 减仓 + 算 avg_cost_basis)
    ⑥ 更新 mt_gobelin_account (现金 ± + 汇总 PnL)
    ⑦ 更新 mt_investment_proposal → EXECUTED
    """
    STAMP_TAX_RATE = 0.001   # 卖出千1
    COMMISSION_RATE = 0.00025  # 万2.5

    def _calc_fee(self, ptype, amount):
        """佣金 + 印花税 (SELL 有印花税, BUY 只有佣金)"""
        comm = round(amount * self.COMMISSION_RATE, 2)
        stamp = round(amount * self.STAMP_TAX_RATE, 2) if ptype == "SELL" else 0
        return comm, stamp, comm + stamp

    def _upsert_position(self, conn, channel, asset_code, asset_name, ptype, qty, exec_price):
        """
        更新 mt_gobelin_position:
        - BUY: 加仓, 重算 avg_cost_basis (加权平均)
        - SELL: 减仓, 从持仓里扣 (无持仓则拒绝)
        返回 (position_row_dict, realized_pnl_for_sell)
        """
        row = conn.execute(
            "SELECT * FROM mt_gobelin_position WHERE channel=? AND asset_code=?",
            (channel, asset_code)
        ).fetchone()

        if ptype == "SELL":
            if not row or dict(row).get("qty", 0) < qty:
                return None, 0, "insufficient_position"
            pd = dict(row)
            old_qty = pd["qty"]
            old_cost = pd["total_cost"]
            avg_cost = pd["avg_cost_basis"]
            realized_pnl = round(qty * (exec_price - avg_cost), 2)
            new_qty = round(old_qty - qty, 4)
            new_cost = round(old_cost - qty * avg_cost, 2)
            # SELL 是减仓, avg_cost_basis 不变 (剩余持仓成本基础不变)
            new_mv = round(new_qty * (pd.get("current_price", exec_price) or exec_price), 2)
            new_pnl = round(new_mv - max(0, new_cost), 2)
            conn.execute("""UPDATE mt_gobelin_position SET
                qty=?, available_qty=?, total_cost=?, market_value=?, unrealized_pnl=?,
                last_trade_date=date('now','localtime'), updated_at=?
                WHERE channel=? AND asset_code=?""",
                (new_qty, new_qty, max(0, new_cost), new_mv, new_pnl, _now(), channel, asset_code))
            return pd, realized_pnl, None

        else:  # BUY
            if row:
                pd = dict(row)
                old_qty = pd["qty"]
                old_cost = pd["total_cost"]
                new_qty = round(old_qty + qty, 4)
                add_cost = round(qty * exec_price, 2)
                new_total_cost = round(old_cost + add_cost, 2)
                new_avg_cost = round(new_total_cost / new_qty, 4) if new_qty > 0 else 0
                new_mv = round(new_qty * (pd.get("current_price", exec_price) or exec_price), 2)
                new_pnl = round(new_mv - new_total_cost, 2)
                conn.execute("""UPDATE mt_gobelin_position SET
                    qty=?, available_qty=?, avg_cost_basis=?, total_cost=?,
                    market_value=?, unrealized_pnl=?,
                    open_date=COALESCE(open_date, date('now','localtime')),
                    last_trade_date=date('now','localtime'), updated_at=?
                    WHERE channel=? AND asset_code=?""",
                    (new_qty, new_qty, new_avg_cost, new_total_cost, new_mv, new_pnl,
                     _now(), channel, asset_code))
            else:
                new_qty = round(qty, 4)
                new_avg_cost = round(exec_price, 4)
                new_total_cost = round(qty * exec_price, 2)
                conn.execute("""INSERT INTO mt_gobelin_position
                    (channel, asset_code, asset_name, qty, available_qty, avg_cost_basis,
                     total_cost, current_price, market_value, open_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, round(qty*current_price,2), date('now','localtime'), ?)""",
                    (channel, asset_code, asset_name, new_qty, new_qty, new_avg_cost,
                     new_total_cost, exec_price, _now()))
            return dict(row) if row else {}, 0, None

    def execute_all_pending(self, limit=20):
        """执行所有已 GRANTED 且 UNUSED 的印章 → 写入 Gobelin Bank 真实表"""
        conn = _conn()
        try:
            rows = conn.execute("""
                SELECT t.id as token_id, t.token_hash, t.proposal_id, t.proposal_no,
                       t.seal_code, t.expected_amount, p.channel, p.asset_code,
                       p.asset_name, p.ptype, p.qty, p.price, p.amount,
                       g.id as grant_id
                FROM mt_seal_token t
                JOIN mt_seal_grant g ON t.grant_id = g.id
                JOIN mt_investment_proposal p ON t.proposal_id = p.id
                WHERE t.status='UNUSED'
                  AND g.status='GRANTED'
                  AND (g.expires_at IS NULL OR g.expires_at > datetime('now','localtime'))
                ORDER BY t.id ASC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
        except Exception as e:
            conn.close()
            return {"error": str(e)[:200]}

        seal = _get_engines()[0]
        results = []

        for r in rows:
            td = _row_to_dict(r)
            token_hash = td["token_hash"]
            proposal_id = td["proposal_id"]
            channel = td.get("channel", "")
            ptype = td.get("ptype", "BUY")
            amount = td.get("expected_amount", 0)
            asset_name = td.get("asset_name", "")
            asset_code = td.get("asset_code", "")
            qty = td.get("qty", 0)
            price = td.get("price", 0)

            step_log = {"proposal_id": proposal_id, "channel": channel, "asset": asset_name}

            # ① 验章
            v = seal.verify_token(token_hash, proposal_id=proposal_id,
                                  channel=channel, expected_amount=amount)
            if not v.get("ok"):
                results.append({"proposal_id": proposal_id, "error": "verify_failed",
                                "reason": v.get("reason", "")})
                continue
            step_log["verify"] = "OK"

            # ①.5 🏛️ 国家交易政策合规检查 (最终执行前)
            try:
                from engines.channel_policy_engine import ChannelPolicyEngine
                _pe = ChannelPolicyEngine()
                from engines import finance_autonomous_engine as _fa_mod
                ps = _fa_mod._get_engines()[1]._get_portfolio_state(_fa_mod._conn())
                compl = _pe.execute_before(
                    channel, ptype, qty, price, amount,
                    asset_name=asset_name, asset_code=asset_code,
                    total_assets=ps.get("total_assets", 500000),
                    cash_available=ps.get("cash", 392964),
                )
                if not compl.get("ok"):
                    # 合规硬拦截 (不是失败, 是合规拒绝)
                    conn2 = _fa_mod._conn()
                    try:
                        conn2.execute("UPDATE mt_investment_proposal SET status='REJECTED', updated_at=? WHERE id=?",
                                      (_fa_mod._now(), proposal_id))
                        conn2.commit()
                    finally:
                        conn2.close()
                    step_log.update({"status": "REJECTED_COMPLIANCE",
                                      "compliance_blocks": compl.get("blocks", []),
                                      "compliance_policy": compl.get("policy", {}),
                                      "success": False})
                    # 审计
                    _audit_compliance(_fa_mod._conn(), proposal_id, channel, ptype, amount,
                                      "execute", compl)
                    results.append(step_log)
                    continue
                step_log["compliance"] = "OK"
                step_log["fees_est"] = compl.get("fees", {}).get("total", 0)
                # 合规审计记录
                _audit_compliance(_fa_mod._conn(), proposal_id, channel, ptype, amount,
                                  "execute", compl)
            except Exception as e:
                step_log["compliance_err"] = str(e)[:80]
                # 合规引擎异常不阻塞, 记录 warning 继续执行

            # ② 滑点模拟 (0.5% 内)
            execution_price = round(price * random.uniform(0.995, 1.005), 4) if price else price
            exec_amount = round(qty * execution_price, 2)
            comm, stamp, total_fee = self._calc_fee(ptype, exec_amount)
            trade_id = f"TRADE-{proposal_id}-{int(time.time()*1000)}"

            # ③ 核销
            seal.consume_token(token_hash, related_trade_id=trade_id)

            # ④ ~ ⑥ 写入 Gobelin Bank 真实表 (一个 DB tx)
            conn2 = _conn()
            try:
                # position 变更
                before_pos, realized_pnl, pos_err = self._upsert_position(
                    conn2, channel, asset_code, asset_name, ptype, qty, execution_price)

                if pos_err:
                    # SELL 无持仓 → 失败回滚
                    conn2.execute("UPDATE mt_investment_proposal SET status='FAILED', updated_at=? WHERE id=?",
                                  (_now(), proposal_id))
                    conn2.commit()
                    step_log.update({"status": "FAILED", "error": pos_err, "success": False})
                    results.append(step_log)
                    continue

                avg_cost_before = (before_pos or {}).get("avg_cost_basis", 0) if ptype == "SELL" else 0
                avg_cost_after = execution_price if ptype == "BUY" else (before_pos or {}).get("avg_cost_basis", 0)

                # 写 mt_gobelin_trade
                conn2.execute("""INSERT INTO mt_gobelin_trade
                    (trade_id, proposal_id, channel, asset_code, asset_name, ptype,
                     qty, exec_price, avg_cost_before, avg_cost_after, amount,
                     commission, stamp_tax, total_fee, cash_impact, realized_pnl,
                     seal_code, seal_token_hash, status, trade_date, trade_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FILLED',
                            date('now','localtime'), time('now','localtime'))""",
                    (trade_id, proposal_id, channel, asset_code, asset_name, ptype,
                     qty, execution_price, avg_cost_before, avg_cost_after, exec_amount,
                     comm, stamp, total_fee,
                     round(-exec_amount - total_fee, 2) if ptype in ("BUY", "HEDGE")
                     else round(exec_amount - total_fee, 2),
                     round(realized_pnl, 2),
                     td.get("seal_code", ""), token_hash))

                # 更新 Account 现金
                cash_impact = round(-exec_amount - total_fee, 2) if ptype in ("BUY", "HEDGE") \
                              else round(exec_amount - total_fee, 2)
                conn2.execute("""UPDATE mt_gobelin_account SET
                    cash_balance=cash_balance+?, trade_count=trade_count+1,
                    realized_pnl=realized_pnl+?, updated_at=?
                    WHERE account_name='GOBELIN_MAIN'""",
                    (cash_impact, realized_pnl, _now()))

                # 更新 Proposal → EXECUTED
                conn2.execute("""UPDATE mt_investment_proposal SET
                    status='EXECUTED', seal_status='USED',
                    seal_used_at=?, updated_at=?
                    WHERE id=?""", (_now(), _now(), proposal_id))

                conn2.commit()
            except Exception as e:
                conn2.rollback()
                sys.stderr.write(f"[EXECUTOR] trade write failed: {e}\n")
                step_log.update({"status": "ERROR", "error": str(e)[:80], "success": False})
                results.append(step_log)
                continue
            finally:
                conn2.close()

            step_log.update({
                "status": "EXECUTED", "trade_id": trade_id,
                "execution_price": execution_price, "exec_amount": exec_amount,
                "fee": total_fee, "realized_pnl": round(realized_pnl, 2),
                "cash_impact": cash_impact, "success": True,
            })
            results.append(step_log)

        # 执行完刷新价格 + 汇总
        try:
            refresh_gobelin_prices()
        except Exception as e:
            sys.stderr.write(f"[EXECUTOR] post-refresh failed: {e}\n")

        executed = sum(1 for r in results if r.get("success"))
        failed = sum(1 for r in results if not r.get("success"))
        return {"total": len(results), "executed": executed, "failed": failed, "detail": results}


# ═══════════════════════════════════════════════════════════════════
# §5 AutonomousCycle — 把上面串成一个自动 cycle
# ═══════════════════════════════════════════════════════════════════

def run_cycle(max_signals=5, confidence_min=0.5, execute_limit=20):
    """
    完整自动投资 cycle:
    T1 行情扫描 → T2 自动提案+议会 → T3 批量发章 → T4 渠道执行
    """
    t_cycle_start = time.time()
    report = {"started_at": _now(), "phases": {}}

    # ── Phase 1: 行情扫描 ──
    t0 = time.time()
    try:
        signals = scan_market()
        buy_sigs = [s for s in signals if s["signal"] == "BUY"]
        sell_sigs = [s for s in signals if s["signal"] == "SELL"]
        report["phases"]["market_scan"] = {
            "status": "OK",
            "watchlist_size": len(signals),
            "buy_signals": len(buy_sigs),
            "sell_signals": len(sell_sigs),
            "top_buy": [f"{s['asset_name']} ¥{s['price']} chg={s['chg_pct']:.1%}" for s in buy_sigs[:3]],
            "took_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        report["phases"]["market_scan"] = {"status": "ERROR", "error": str(e)[:200]}
        signals = []

    # ── Phase 2: 自动提案 + 议会表决 ──
    t0 = time.time()
    try:
        proposal_results = generate_proposals(signals, max_per_cycle=max_signals, min_confidence=confidence_min)
        created = [r for r in proposal_results if not r.get("skipped_duplicate") and "error" not in r]
        passed = sum(1 for r in created if r.get("vote_result") == "PASSED")
        vetoed = sum(1 for r in created if r.get("vote_result") == "VETOED")
        failed = sum(1 for r in created if r.get("vote_result") == "FAILED")
        report["phases"]["parliament"] = {
            "status": "OK",
            "proposals_created": len(created),
            "skipped_dup": sum(1 for r in proposal_results if r.get("skipped_duplicate")),
            "passed": passed, "failed": failed, "vetoed": vetoed,
            "detail": proposal_results[:10],
            "took_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        report["phases"]["parliament"] = {"status": "ERROR", "error": str(e)[:200]}

    # ── Phase 3: 批量发章 ──
    t0 = time.time()
    try:
        seal_result = auto_grant_proposals(limit=50)
        report["phases"]["seal_grant"] = {
            "status": "OK",
            "total": seal_result.get("total", 0),
            "granted": seal_result.get("granted", 0),
            "denied": seal_result.get("denied", 0),
            "took_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        report["phases"]["seal_grant"] = {"status": "ERROR", "error": str(e)[:200]}

    # ── Phase 4: 渠道执行 ──
    t0 = time.time()
    try:
        executor = ChannelExecutor()
        exec_result = executor.execute_all_pending(limit=execute_limit)
        report["phases"]["execution"] = {
            "status": "OK",
            "total": exec_result.get("total", 0),
            "executed": exec_result.get("executed", 0),
            "failed": exec_result.get("failed", 0),
            "verify_failed": exec_result.get("verify_failed", 0),
            "took_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        report["phases"]["execution"] = {"status": "ERROR", "error": str(e)[:200]}

    report["finished_at"] = _now()
    report["total_took_ms"] = int((time.time() - t_cycle_start) * 1000)
    return report


# ═══════════════════════════════════════════════════════════════════
# §6 Daemon — 定时运行
# ═══════════════════════════════════════════════════════════════════

def run_daemon(interval_sec=300, max_cycles=0):
    """
    interval_sec=300 → 每 5 分钟一轮
    max_cycles=0 → 无限
    """
    sys.stderr.write(f"[AUTONOMOUS] 🤖 Finance Autonomous Engine 启动 (interval={interval_sec}s)\n")
    cycle = 0
    while True:
        cycle += 1
        sys.stderr.write(f"\n{'='*60}\n")
        sys.stderr.write(f"[AUTONOMOUS] Cycle #{cycle} @ {_now()}\n")
        sys.stderr.write(f"{'='*60}\n")

        try:
            report = run_cycle()
            total_ms = report.get("total_took_ms", 0)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            sys.stderr.write(f"\n[AUTONOMOUS] Cycle #{cycle} 完成 (总耗时 {total_ms}ms)\n")
        except Exception as e:
            sys.stderr.write(f"[AUTONOMOUS] Cycle #{cycle} crashed: {e}\n")

        if max_cycles > 0 and cycle >= max_cycles:
            sys.stderr.write(f"[AUTONOMOUS] 达到 max_cycles={max_cycles}, 退出\n")
            break

        sys.stderr.write(f"[AUTONOMOUS] 休眠 {interval_sec}s 后下一轮...\n")
        try:
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            sys.stderr.write(f"\n[AUTONOMOUS] 收到中断信号, 退出\n")
            break


# ═══════════════════════════════════════════════════════════════════
# §7 汇总报表
# ═══════════════════════════════════════════════════════════════════

def generate_report():
    conn = _conn()
    try:
        total_props = conn.execute("SELECT COUNT(*) FROM mt_investment_proposal").fetchone()[0]
        status_rows = conn.execute("""
            SELECT status, COUNT(*) as cnt FROM mt_investment_proposal
            GROUP BY status ORDER BY cnt DESC""").fetchall()
        by_status = {r["status"]: r["cnt"] for r in status_rows}

        total_passed = by_status.get("APPROVED", 0) + by_status.get("EXECUTED", 0)
        total_amount = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM mt_investment_proposal WHERE status IN ('APPROVED','EXECUTED')"
        ).fetchone()[0]
        executed_amount = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM mt_investment_proposal WHERE status='EXECUTED'"
        ).fetchone()[0]

        grants = conn.execute("SELECT COUNT(*) FROM mt_seal_grant").fetchone()[0]
        active_grants = conn.execute("SELECT COUNT(*) FROM mt_seal_grant WHERE status='GRANTED'").fetchone()[0]
        tokens = conn.execute("SELECT COUNT(*) FROM mt_seal_token").fetchone()[0]
        used_tokens = conn.execute("SELECT COUNT(*) FROM mt_seal_token WHERE status='USED'").fetchone()[0]
        audit = conn.execute("SELECT COUNT(*) FROM mt_seal_audit").fetchone()[0]

        parl_sessions = conn.execute("SELECT COUNT(*) FROM mt_parliament_session").fetchone()[0]
        parl_votes = conn.execute("SELECT COUNT(*) FROM mt_parliament_vote_log").fetchone()[0]

        # 最近 5 条提案
        recent = [_row_to_dict(r) for r in conn.execute("""
            SELECT id, proposal_no, title, channel, amount, status, vote_result, seal_code, seal_status, created_at
            FROM mt_investment_proposal ORDER BY id DESC LIMIT 5""").fetchall()]

        return {
            "timestamp": _now(),
            "proposals": {
                "total": total_props,
                "by_status": by_status,
                "total_amount_passed": round(total_amount, 2),
                "total_amount_executed": round(executed_amount, 2),
            },
            "seal": {
                "registry": 4, "grants": grants, "active_grants": active_grants,
                "tokens": tokens, "used_tokens": used_tokens, "audit_entries": audit,
            },
            "parliament": {
                "sessions": parl_sessions, "vote_logs": parl_votes,
            },
            "recent_proposals": recent,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §7b 合规审计辅助
# ═══════════════════════════════════════════════════════════════════

def _audit_compliance(conn, proposal_id, channel, ptype, amount, stage, result):
    """写 mt_compliance_audit 合规审计记录"""
    import json as _json
    try:
        conn.execute("""INSERT OR IGNORE INTO mt_compliance_audit
            (proposal_id, channel, ptype, amount, stage, ok,
             blocks, warnings, fees, policy_snapshot, data_scope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'REAL')""",
            (proposal_id, channel, ptype, amount, stage,
             1 if result.get("ok") else 0,
             _json.dumps(result.get("blocks", []), ensure_ascii=False),
             _json.dumps(result.get("warnings", []), ensure_ascii=False),
             _json.dumps(result.get("fees", {}), ensure_ascii=False),
             _json.dumps(result.get("policy", {}), ensure_ascii=False)))
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"[COMPLIANCE] audit write failed: {e}\n")


def _ensure_compliance_tables():
    """确保合规审计表存在 (幂等)"""
    conn = _conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_compliance_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id INTEGER, proposal_no TEXT,
            channel TEXT, ptype TEXT, amount REAL, qty REAL, price REAL,
            stage TEXT,
            ok INTEGER DEFAULT 1,
            blocks TEXT, warnings TEXT, fees TEXT, policy_snapshot TEXT,
            operator TEXT, data_scope TEXT DEFAULT 'REAL',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_channel_policy_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT, channel TEXT, policy_json TEXT,
            policy_version TEXT DEFAULT '2026.11',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(channel, snapshot_date)
        )""")
        conn.commit()
    finally:
        conn.close()


# 模块加载时确保合规表存在
_ensure_compliance_tables()


# ═══════════════════════════════════════════════════════════════════
# §7c 供 GobelinScheduler 调用的独立会议函数
# ═══════════════════════════════════════════════════════════════════

def run_pre_market_meeting():
    """盘前策略会 — scheduler 调用"""
    started = datetime.now()
    
    # ① 价格刷新 (盘前基准)
    try:
        refresh_gobelin_prices()
    except Exception as e:
        sys.stderr.write(f"[PRE-MARKET] price_refresh failed: {e}\n")
    
    # ② 扫描 + 议会 (待处理提案快速表决)
    conn = _conn()
    try:
        pending = conn.execute(
            "SELECT id FROM mt_investment_proposal WHERE status='PENDING' ORDER BY id DESC LIMIT 10"
        ).fetchall()
        for r in pending:
            _get_engines()[1].vote(r["id"])
    except Exception as e:
        sys.stderr.write(f"[PRE-MARKET] pre_vote failed: {e}\n")
    finally:
        conn.close()

    return {
        "meeting": "PRE_MARKET_STRATEGY",
        "duration_ms": round((datetime.now() - started).total_seconds() * 1000),
        "steps": ["price_refresh", "risk_check", "pre_vote"],
    }


def run_close_summary():
    """收市总结会 — 收盘价重算 PnL + 合规审计"""
    started = datetime.now()
    
    # ① 用收盘价刷新持仓
    try:
        refresh_gobelin_prices()
    except Exception as e:
        sys.stderr.write(f"[CLOSE] price_refresh failed: {e}\n")
    
    # ② 汇总当日交易
    conn = _conn()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        trades_today = conn.execute(
            "SELECT COUNT(*) cnt, SUM(amount) amt, SUM(realized_pnl) pnl FROM mt_gobelin_trade "
            f"WHERE trade_date='{today}'"
        ).fetchone()
        prop_exec = conn.execute(
            "SELECT COUNT(*) cnt FROM mt_investment_proposal WHERE status='EXECUTED' AND DATE(created_at)=?",
            (today,)
        ).fetchone()
    finally:
        conn.close()

    return {
        "meeting": "CLOSE_SUMMARY",
        "date": today,
        "trades_today": dict(trades_today) if trades_today else {},
        "proposals_executed_today": prop_exec["cnt"] if prop_exec else 0,
        "duration_ms": round((datetime.now() - started).total_seconds() * 1000),
    }


# ═══════════════════════════════════════════════════════════════════
# §8 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gobelin Bank Finance Autonomous Engine")
    parser.add_argument("--cycle", action="store_true", help="运行一轮 cycle")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式 (每 5min 一轮)")
    parser.add_argument("--once", action="store_true", help="同上, 单次")
    parser.add_argument("--report", action="store_true", help="汇总报表")
    parser.add_argument("--scan", action="store_true", help="只扫描行情")
    parser.add_argument("--execute", action="store_true", help="只执行渠道")
    parser.add_argument("--interval", type=int, default=300, help="daemon 间隔 (秒)")
    parser.add_argument("--max-cycles", type=int, default=0, help="daemon 最大 cycles (0=无限)")
    args = parser.parse_args()

    if args.report:
        print(json.dumps(generate_report(), ensure_ascii=False, indent=2))

    if args.scan:
        sigs = scan_market()
        for s in sigs:
            arrow = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(s["signal"], "?")
            print(f"  {arrow} {s['channel']:12s} {s['asset_name']:10s} ¥{s['price']:>8.2f}  "
                  f"chg={s['chg_pct']:>+7.2%} → {s['signal']:5s} conf={s['confidence']:.0%} 建议¥{s['amount_suggestion']:,}")

    if args.execute:
        ex = ChannelExecutor()
        res = ex.execute_all_pending(limit=20)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.cycle or args.once:
        print("=" * 60)
        print("🤖 Gobelin Bank 自动投资 Cycle")
        print("=" * 60)
        report = run_cycle()
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.daemon:
        run_daemon(interval_sec=args.interval, max_cycles=args.max_cycles)
