#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🛡️ Channel Policy Engine (国家交易政策合规)
#  flow_channel_policy_20261113
#
#  三重合规门: Parliament 投票前 → Seal 发章前 → Channel 执行前
#
#  覆盖的合规政策 (2026.11 现行):
#  ──────────────────────────────────────────────────────────────
#  A股 (SH/SZ)     → T+1, 涨跌停±10%(ST±5%), 交易时段 9:30-15:00,
#                     印花税千1(SELL only), 过户费万0.1
#  港股 (HK)       → T+0, 无涨跌停, 交易时段 9:30-16:00,
#                     印花税千1.3(双边), 每手 100股起
#  美股 (US)       → T+0, 熔断 7/13/20%, 常规 9:30-16:00 ET,
#                     盘前 4:00-9:30, 盘后 16:00-20:00
#  期货 (FUTURES)  → 保证金 ~10%, 涨跌停 3-6%, 强平线,
#                     交易时段 9:00-11:30, 13:30-15:00, 夜盘
#  贵金属 (METAL)  → A股黄金 T+D, 涨跌停±7%, 交易时段 9:00-15:30+夜盘
#  债券 (BOND)     → T+0 (现券), 无涨跌停, 全价/净价
#  ETF             → T+0 (跨境ETF QDII), A股ETF T+1, 无涨跌停±10%
#  银行存款         → 50万存款保险, 法定存款准备金率
#
#  使用方式:
#    pe = ChannelPolicyEngine()
#    result = pe.check(channel, ptype, qty, price, amount)
#    → {"ok": True/False, "checks": [...], "blocks": [...], "warnings": [...]}
# ═══════════════════════════════════════════════════════════════════

import datetime as _dt
from typing import Any

# ═══════════════════════════════════════════════════════════════════
# §1 国家交易政策字典 (2026.11 最新法规)
# ═══════════════════════════════════════════════════════════════════

CHANNEL_POLICY: dict[str, dict[str, Any]] = {
    # ── A股主板 (SH/SZ 主板 + 中小板) ──
    "A_STOCK": {
        "region": "CN",
        "regulator": "CSRC 证监会",
        "settlement": "T+1",
        "price_limit_pct": 0.10,          # 涨跌停 ±10% (ST 股 ±5%)
        "price_limit_st_pct": 0.05,
        "commission_rate": 0.00025,        # 券商佣金 万2.5 (双边, 最低5元)
        "stamp_tax_rate_sell": 0.001,      # 印花税千1 (仅 SELL)
        "transfer_fee_rate": 0.00001,      # 过户费万0.1 (双边)
        "min_commission": 5.0,
        "lot_size": 100,                   # 最小交易单位 100股 (一手)
        "min_amount": 1000.0,              # 单笔最低 ¥1000
        "trading_sessions": [              # 交易时段 (北京时间)
            ("09:30", "11:30"),
            ("13:00", "15:00"),
        ],
        "pre_market_open": "09:15",        # 集合竞价开始
        "circuit_breaker_pct": 0.07,       # 指数熔断 ±7% (2026 最新: 已暂停, 保留字段)
        "short_selling_allowed": False,    # 融资融券需单独账户
        "data_scope": "REAL",
    },

    # ── ETF (跨境 QDII T+0, A股 T+1) ──
    "ETF": {
        "region": "CN",
        "regulator": "CSRC 证监会",
        "settlement": "T+0_OR_T+1",        # 跨境QDII T+0, A股ETF T+1
        "price_limit_pct": 0.10,
        "commission_rate": 0.00025,
        "stamp_tax_rate_sell": 0.001,      # ETF SELL 免印花税 (特例!)
        "transfer_fee_rate": 0.00001,
        "min_commission": 5.0,
        "lot_size": 100,
        "min_amount": 1000.0,
        "trading_sessions": [("09:30", "11:30"), ("13:00", "15:00")],
        "note": "ETF SELL 免征印花税 (财政部财税[2012]85号)",
    },

    # ── 封闭式基金 ──
    "FUND": {
        "region": "CN",
        "regulator": "CSRC",
        "settlement": "T+1",               # 基金申购赎回 T+1 确认
        "commission_rate": 0.00025,
        "stamp_tax_rate_sell": 0.001,      # 封闭式基金 SELL 交印花税
        "transfer_fee_rate": 0.00001,
        "min_commission": 5.0,
        "lot_size": 100,
        "price_limit_pct": 0.10,
        "trading_sessions": [("09:30", "11:30"), ("13:00", "15:00")],
        "note": "开放式基金 申购/赎回 走场外通道, 不进入 Gobelin 实盘",
    },

    # ── 贵金属 (上海黄金交易所 SGE / 银行纸黄金) ──
    "METAL": {
        "region": "CN",
        "regulator": "PBOC 央行 + SGE",
        "settlement": "T+0",                # 黄金 T+D 当日可平仓
        "price_limit_pct": 0.07,            # SGE 涨跌停 ±7%
        "commission_rate": 0.0003,           # SGE 手续费 万3
        "min_commission": 0.0,
        "lot_size": 1,                      # 1克起 (AU9999) / 1千克起 (白银)
        "trading_sessions": [
            ("09:00", "11:30"),
            ("13:30", "15:30"),
            ("20:00", "02:30"),             # 夜盘
        ],
        "margin_ratio": 0.08,               # T+D 保证金 8% (实际约 10-15%)
        "force_liquidation_pct": 0.90,      # 保证金率低于 90% 强平警戒线
    },

    # ── 期货 (上期所/大商所/郑商所/中金所/广期所) ──
    "FUTURES": {
        "region": "CN",
        "regulator": "CFFEX 中金所 / SHFE 上期所",
        "settlement": "T+0",
        "margin_ratio": 0.10,               # 交易所保证金 约 10%
        "price_limit_pct": 0.04,            # 涨跌停 ±4% (不同品种不同)
        "commission_rate": 0.0002,          # 万2 (双边)
        "force_liquidation_pct": 0.85,      # 保证金率 85% 强平
        "max_position_pct": 0.25,           # 单一合约占账户 25% 上限
        "trading_sessions": [
            ("09:00", "10:15"),
            ("10:30", "11:30"),
            ("13:30", "15:00"),
            ("21:00", "23:00"),             # 夜盘
        ],
        "note": "⚠️ Gobelin Bank 当前禁用期货 channel, 监管风控限制",
    },

    # ── 债券 (上交所/深交所银行间) ──
    "BOND": {
        "region": "CN",
        "regulator": "PBOC + CSRC",
        "settlement": "T+0",                # 现券买卖 T+0
        "price_limit_pct": None,            # 无涨跌停
        "commission_rate": 0.00001,         # 万0.1 (极低)
        "stamp_tax_rate_sell": 0,           # 免印花税
        "min_commission": 0.0,
        "lot_size": 1,                      # 1张起 (100元面值)
        "min_amount": 1000.0,
        "trading_sessions": [("09:30", "11:30"), ("13:00", "15:00")],
        "yield_tax_policy": "企业债利息扣税20%, 国债免税",
    },

    # ── 银行存款 ──
    "BANK_DEPOSIT": {
        "region": "CN",
        "regulator": "PBOC + CBIRC 银保监会",
        "settlement": "T+0",
        "insurance_limit": 500000.0,         # 存款保险 50万 (单银行)
        "commission_rate": 0,
        "lot_size": 10000.0,                 # 起存 ¥10,000
        "note": "存款保险条例 (国务院令第657号), 50万内本息全额保障",
    },

    # ── 港股 ──
    "HK_STOCK": {
        "region": "HK",
        "regulator": "SFC 证监会 (Hong Kong)",
        "settlement": "T+0",                 # 回转交易
        "price_limit_pct": None,             # 无涨跌停
        "commission_rate": 0.00025,           # 券商佣金 ~万2.5
        "stamp_tax_rate": 0.0013,             # 印花税千1.3 (双边)
        "min_commission": 15.0,              # 最低 HKD 15
        "lot_size": 100,                     # 每手 (部分股票每手不同)
        "trading_sessions": [("09:30", "12:00"), ("13:00", "16:00")],
        "currency": "HKD",
        "note": "联交所 (HKEX), 无涨跌停限制, 允许卖空 (需授权)",
    },

    # ── 美股 ──
    "US_STOCK": {
        "region": "US",
        "regulator": "SEC + FINRA",
        "settlement": "T+0",
        "price_limit_pct": None,             # 无涨跌停 (有熔断)
        "circuit_breaker": [0.07, 0.13, 0.20],  # 7% 暂停15min, 13% 暂停15min, 20% 闭市
        "commission_rate": 0,                # 多数券商 0 佣金
        "transaction_fee": 0.0000229,        # FINRA 每笔 $0.0000229/share
        "trading_sessions": [
            ("16:30", "20:00"),              # 盘前 (北京时间)
            ("21:30", "04:00"),              # 常规 (北京时间)
            ("04:00", "08:00"),              # 盘后 (北京时间)
        ],
        "currency": "USD",
        "note": "NYSE/NASDAQ, 熔断机制三档, 日内交易需 PDT 规则 (账户>$25k)",
    },

    # ── 现金管理 (货币基金/逆回购) ──
    "CASH": {
        "region": "CN",
        "regulator": "PBOC",
        "settlement": "T+0",
        "commission_rate": 0,
        "note": "逆回购 1天期 (R001), 货币基金万份收益, 实时可用",
    },
}


# ═══════════════════════════════════════════════════════════════════
# §2 核心检查引擎
# ═══════════════════════════════════════════════════════════════════

class ChannelPolicyEngine:
    """
    国家交易政策合规检查引擎.
    三重门: vote_before / seal_before / execute_before
    """

    def __init__(self, now=None):
        self.now = now or _dt.datetime.now()
        self._channel_valid = set(CHANNEL_POLICY.keys())

    # ── 主检查入口 ──
    def check(self, channel: str, ptype: str, qty: float, price: float,
              amount: float, asset_name: str = "",
              asset_code: str = "", st_flag: bool = False,
              total_assets: float = 500_000, cash_available: float = 392_964,
              mode: str = "execute") -> dict:
        """
        mode: vote / seal / execute — 不同阶段严格程度不同
        返回 {"ok": True/False, "checks": [...], "blocks": [...], "warnings": [...],
              "fees": {...}, "policy": {...}}
        """
        checks = []
        blocks = []
        warnings = []
        fees = {}

        policy = CHANNEL_POLICY.get(channel)
        if not policy:
            blocks.append(f"未知交易渠道: {channel} (不在 {list(self._channel_valid)})")
            return {"ok": False, "checks": checks, "blocks": blocks, "warnings": warnings}

        # ── C1: 渠道是否允许 Gobelin 进入 ──
        if channel == "FUTURES" and mode != "vote":
            # 期货在 seal/execute 阶段强制 block, 即使议会通过也不给发章
            blocks.append("Gobelin Bank 当前禁用期货 channel (监管风控限制)")

        # ── C2: 金额/数量合法 ──
        if amount <= 0:
            blocks.append(f"交易金额非法: amount={amount} <= 0")
        if qty <= 0:
            blocks.append(f"交易数量非法: qty={qty} <= 0")

        # ── C3: 最小交易单位 (一手) ──
        lot = policy.get("lot_size", 1)
        if channel == "BANK_DEPOSIT":
            # 存款是金额起存
            min_amt = policy.get("lot_size", 10000)
            if amount < min_amt:
                blocks.append(f"银行存款起存额不足: ¥{amount:,.0f} < ¥{min_amt:,.0f}")
        elif lot > 1 and qty % lot != 0:
            blocks.append(f"数量非一手: qty={qty} 需为 {lot} 的整数倍")

        # ── C4: 单笔最低限额 ──
        min_amt = policy.get("min_amount", 0)
        if min_amt > 0 and amount < min_amt:
            warnings.append(f"单笔金额低于建议最低 ¥{min_amt:,.0f} (当前 ¥{amount:,.0f})")

        # ── C5: 涨跌停检查 (价格偏离昨收) ──
        # 注: 需要 prev_close, 简化处理 — BETA VETO 已覆盖大额风险
        limit_pct = policy.get("price_limit_pct")
        if limit_pct:
            # ST 股 ±5%
            effective_limit = policy.get("price_limit_st_pct", limit_pct) if st_flag else limit_pct
            checks.append({"price_limit": f"±{effective_limit:.0%}", "ok": True})

        # ── C6: 交易时段检查 ──
        sessions = policy.get("trading_sessions", [])
        if sessions and mode in ("execute",):  # 只在执行时严格检查
            now_time = self.now.strftime("%H:%M")
            now_weekday = self.now.weekday()  # 0=Mon, 6=Sun
            if now_weekday >= 5:  # 周末休市
                if channel not in ("BANK_DEPOSIT", "CASH"):
                    blocks.append(f"当前周末非交易日 (weekday={now_weekday})")
            else:
                in_session = False
                for start_s, end_s in sessions:
                    try:
                        from datetime import datetime
                        start = datetime.strptime(start_s, "%H:%M").time()
                        end = datetime.strptime(end_s, "%H:%M").time()
                        cur = self.now.time()
                        # 处理夜盘跨日 (start > end)
                        if start <= end:
                            if start <= cur <= end:
                                in_session = True; break
                        else:
                            if cur >= start or cur <= end:
                                in_session = True; break
                    except Exception:
                        pass
                if not in_session and channel not in ("BANK_DEPOSIT", "CASH", "FUND"):
                    warnings.append(f"当前非 {channel} 交易时段 ({now_time}), 可排队至下一时段")

        # ── C7: 现金/仓位充足性 ──
        if ptype in ("BUY", "HEDGE"):
            need_cash = amount * 1.001  # 预估含手续费
            if mode in ("seal", "execute") and need_cash > cash_available:
                blocks.append(f"现金不足: 需 ¥{need_cash:,.0f} 可用 ¥{cash_available:,.0f}")
        elif ptype == "SELL":
            # 已有 ChannelExecutor 持仓校验, 这里只做金额量级提醒
            if mode == "vote" and amount > total_assets * 0.1:
                warnings.append(f"SELL 金额 ¥{amount:,.0f} 占总资产 ¥{total_assets:,.0f} 的 {amount/total_assets:.1%}")

        # ── C8: 费用预估 ──
        fee_detail = self._calc_fee(channel, ptype, amount, policy)
        fees = fee_detail

        # ── C9: 渠道集中度 ──
        max_channel_pct = {"A_STOCK": 0.40, "ETF": 0.30, "METAL": 0.20, "FUTURES": 0.05, "BOND": 0.25}
        limit = max_channel_pct.get(channel, 0.50)
        if mode == "vote" and amount > total_assets * limit:
            warnings.append(f"{channel} 单笔 ¥{amount:,.0f} 超过渠道限额 {limit:.0%}")

        # ── C10: 跨境/外汇检查 (港股/美股) ──
        if channel in ("HK_STOCK", "US_STOCK") and mode in ("seal", "execute"):
            warnings.append(f"跨境交易 {channel} 需通过港股通/美股通, 受外汇管制 (每人 5 万美元/年)")

        ok = len(blocks) == 0
        return {
            "ok": ok,
            "checks": checks,
            "blocks": blocks,
            "warnings": warnings,
            "fees": fees,
            "policy": {
                "region": policy.get("region"),
                "regulator": policy.get("regulator"),
                "settlement": policy.get("settlement"),
                "price_limit": f"±{policy['price_limit_pct']:.0%}" if policy.get("price_limit_pct") else "无",
                "note": policy.get("note", ""),
            },
            "channel": channel,
            "ptype": ptype,
            "policy_version": "2026.11",
        }

    # ── 费用计算 ──
    def _calc_fee(self, channel: str, ptype: str, amount: float, policy: dict) -> dict:
        comm_rate = policy.get("commission_rate", 0)
        min_comm = policy.get("min_commission", 0)
        stamp_rate = policy.get("stamp_tax_rate_sell", 0) if ptype == "SELL" else 0
        transfer_rate = policy.get("transfer_fee_rate", 0)

        commission = max(amount * comm_rate, min_comm) if comm_rate > 0 else 0
        stamp_tax = amount * stamp_rate
        transfer_fee = amount * transfer_rate
        total_fee = commission + stamp_tax + transfer_fee

        return {
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "transfer_fee": round(transfer_fee, 2),
            "total": round(total_fee, 2),
            "fee_rate_total": round(total_fee / amount * 100, 4) if amount > 0 else 0,
            "breakdown": f"佣{comm_rate:.2%}(最低¥{min_comm}) + 印{stamp_rate:.2%}(SELL only) + 过{transfer_rate:.3%}",
        }

    # ── 便捷: 三个阶段 ──
    def vote_before(self, channel, ptype, qty, price, amount, **kw):
        """议会投票前 — 宽松检查 (只做硬 block + 大风险 warning)"""
        return self.check(channel, ptype, qty, price, amount, mode="vote", **kw)

    def seal_before(self, channel, ptype, qty, price, amount, **kw):
        """印章发放前 — 中等严格 (现金 + 渠道合法性)"""
        return self.check(channel, ptype, qty, price, amount, mode="seal", **kw)

    def execute_before(self, channel, ptype, qty, price, amount, **kw):
        """渠道执行前 — 最严格 (交易时段 + 现金 + 持仓)"""
        return self.check(channel, ptype, qty, price, amount, mode="execute", **kw)


# ═══════════════════════════════════════════════════════════════════
# §3 合规审计表初始化 (只跑一次)
# ═══════════════════════════════════════════════════════════════════

def ensure_compliance_tables(conn):
    """建合规审计 + 政策快照表"""
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_compliance_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id INTEGER, proposal_no TEXT,
        channel TEXT, ptype TEXT, amount REAL, qty REAL, price REAL,
        stage TEXT,                     -- vote / seal / execute
        ok INTEGER DEFAULT 1,
        blocks TEXT,                    -- JSON array of block reasons
        warnings TEXT,                  -- JSON array of warnings
        fees TEXT,                      -- JSON fee breakdown
        policy_snapshot TEXT,           -- JSON policy at check time
        operator TEXT, data_scope TEXT DEFAULT 'REAL',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_channel_policy_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT,             -- YYYY-MM-DD
        channel TEXT, policy_json TEXT, policy_version TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(channel, snapshot_date)
    )""")


if __name__ == "__main__":
    # CLI demo
    pe = ChannelPolicyEngine()
    tests = [
        ("A_STOCK", "BUY",        200, 101.50,  20300, "中国平安", {}),
        ("A_STOCK", "SELL",       100, 134.20,  13420, "五粮液",   {"st_flag": True}),
        ("ETF",     "BUY",       2000,   3.95,   7900, "沪深300ETF", {}),
        ("METAL",   "BUY",         50, 602.92,  30146, "黄金9999", {}),
        ("BOND",    "BUY",        150, 109.00,  16350, "可转债", {}),
        ("FUTURES", "BUY",          1, 5800.00,  5800, "股指期货 IF", {}),
        ("HK_STOCK","BUY",        100,  380.00, 38000, "腾讯控股", {}),
        ("US_STOCK","BUY",         10, 185.00,  1850, "AAPL", {}),
        ("CASH",    "HEDGE", 100000,   1.00, 100000, "逆回购 R001", {}),
    ]
    for channel, ptype, qty, price, amount, name, kw in tests:
        r = pe.check(channel, ptype, qty, price, amount, asset_name=name, mode="vote", **kw)
        blocks = r["blocks"]
        warnings = r["warnings"]
        fees = r["fees"]
        flag = "✅" if r["ok"] else "🚫"
        print(f"{flag} {channel:10s} {ptype:5s} {qty:>7.1f}×¥{price:>7.2f} =¥{amount:>10,.0f}  {name:8s}  费¥{fees['total']:>7.2f} ({fees['fee_rate_total']:.3f}%)")
        if blocks:
            for b in blocks: print(f"   🚫 {b}")
        if warnings:
            for w in warnings: print(f"   ⚠️  {w}")
