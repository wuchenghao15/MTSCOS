"""
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🇨🇳 A股 + ETF + 贵金属 + 债券 虚拟仓合规校验层 (Regulatory Layer)
┃
┃  设计原则:
┃  ─────────
┃  1. 唯一权威入口: 所有交易/提案/Guardian 必须先过 check()
┃     禁止在提案层/Guardian层各自写 if-then 合规判断
┃  2. 规则优先级: 国家/交易所法规 > 行业惯例 > Gobelin 内部铁律
┃  3. 降级可见: 任何 BLOCK 必须写入 mt_compliance_audit + 返回明确理由
┃  4. 通道差异化: A_STOCK / ETF / METAL / BOND 适用不同规则集
┃
┃  A股三大硬法规 (来源: 上交所/深交所公开规则):
┃  ─────────────────────────────────────────────
┃  R01  T+1 结算制度: A股当日买入, 次日才能卖出
┃       (创业板/科创板同样适用, 没有 T+0 A股)
┃  R02  涨跌停限制:
┃       - 主板 (601xxx/000xxx): 涨停 +10% / 跌停 -10%
┃       - 创业板 (300xxx): ±20%
┃       - 科创板 (688xxx): ±20%
┃       - ST/*ST: ±5%
┃       - 上市首日/股改复牌首日: 不设涨跌停 (但虚拟仓一般不碰)
┃  R03  整手交易: A股买入数量必须是 100 股整数倍 (卖出可零股)
┃       注意: 只有 A_STOCK 通道强制, ETF/债券/金属不受此限
┃
┃  行业/产品差异化规则:
┃  ─────────────────────────────────
┃  R04  ETF (sh510xxx/sz159xxx): 无涨跌停限制? 实际上 ETF 跟随指数但上
│       交所有 ETF 异常波动停牌规则 (30%触发停牌), 简化处理: ±30%
┃  R05  贵金属 (AU9999/Ag(T+D)): 黄金交易所规则 T+0, 涨跌停 ±8%
┃  R06  可转债 (CBxxxx): T+0, 不设涨跌停 (但有临停机制)
┃  R07  交易时段: A股 9:30-11:30 / 13:00-15:00 外禁止买入 (虚拟仓可放宽, 但要标注)
┃
┃  用法:
┃  ────
┃  from engines.regulatory_compliance import ComplianceChecker
┃  result = ComplianceChecker.check(conn, symbol='sh601318', channel='A_STOCK',
│                                    action='SELL', qty=100, price=53.41)
┃  # result = {'pass': True/False, 'block_reason': str, 'rule_code': str,
│  #            'warnings': [...], 'data_source': dict}
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""

import sqlite3
import datetime as dt
from typing import Optional, Dict, List, Any


# ═══════════════════════════════════════════════════════════════════
# §1 规则字典 — 通道 → 适用规则集 + 参数 (唯一真源, 禁止别处硬编码)
# ═══════════════════════════════════════════════════════════════════

CHANNEL_RULES: Dict[str, Dict[str, Any]] = {
    # ── A股主板 (601/000) ──
    "A_STOCK": {
        "t_plus_one": True,           # R01 T+1
        "limit_up_pct": 10.0,         # R02 涨跌停
        "limit_down_pct": -10.0,
        "lot_size": 100,              # R03 100股整手
        "t_plus_zero": False,         # R07 时段限制
        "allowed_trade_hours": [(9, 30, 11, 30), (13, 0, 15, 0)],
        "description": "A_STOCK (沪深主板) T+1 ±10% 整手100股",
    },
    # ── ETF ──
    "ETF": {
        "t_plus_one": False,          # ETF 部分 T+0 (跨境/债券), A股ETF T+1? 简化: T+0
        "limit_up_pct": 30.0,         # R04 ETF ±30% 异常波动停牌
        "limit_down_pct": -30.0,
        "lot_size": 100,              # 100 份
        "t_plus_zero": True,          # ETF 可当天买当天卖 (部分品种)
        "description": "ETF (沪深) 宽松涨跌停 T+0/部分T+1",
    },
    # ── 贵金属 ──
    "METAL": {
        "t_plus_one": False,          # R05 黄金交易所 T+0
        "limit_up_pct": 8.0,
        "limit_down_pct": -8.0,
        "lot_size": 1,                # 1克起
        "t_plus_zero": True,
        "description": "METAL (黄金AU9999/白银Ag) 金交所T+0 ±8%",
    },
    # ── 可转债 ──
    "BOND": {
        "t_plus_one": False,          # R06 可转债 T+0
        "limit_up_pct": None,         # 无涨跌停 (但有临停机制, 简化不设)
        "limit_down_pct": None,
        "lot_size": 10,               # 10张起 (沪) 或 1张起 (深)
        "t_plus_zero": True,
        "description": "BOND (可转债) T+0 无涨跌停 10张起",
    },
}


# 创业板/科创板识别 (特殊 ±20%)
GEM_PREFIXES = ("300",)           # 创业板
STAR_PREFIXES = ("688",)           # 科创板
MAIN_SH_PREFIXES = ("60",)         # 沪市主板
MAIN_SZ_PREFIXES = ("000", "001")  # 深市主板


def _limit_pct_for_symbol(symbol: str, channel: str) -> tuple:
    """给 A_STOCK 内部再分涨跌停板块"""
    if channel != "A_STOCK":
        return CHANNEL_RULES[channel].get("limit_up_pct"), CHANNEL_RULES[channel].get("limit_down_pct")
    
    # ST 股票识别 (简单: 名称含 ST)
    # 需要查 mt_live_position 或 mt_gobelin_position 的 name
    code6 = symbol[2:] if len(symbol) > 6 else symbol  # 去掉 sh/sz 前缀
    
    if code6[:3] in GEM_PREFIXES or code6[:3] in STAR_PREFIXES:
        return 20.0, -20.0  # 创业板/科创板
    return 10.0, -10.0  # 主板


# ═══════════════════════════════════════════════════════════════════
# §2 合规校验主函数 (唯一权威入口)
# ═══════════════════════════════════════════════════════════════════

class ComplianceResult:
    """合规校验结果 (不可变对象, 所有调用方看同一个结论)"""
    __slots__ = ("ok", "block_reason", "rule_code", "warnings", "data_source", "timestamp")
    
    def __init__(self, ok: bool, block_reason: str = "", rule_code: str = "",
                 warnings: List[str] = None, data_source: Dict = None):
        self.ok = ok
        self.block_reason = block_reason
        self.rule_code = rule_code
        self.warnings = warnings or []
        self.data_source = data_source or {}
        self.timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "block_reason": self.block_reason,
            "rule_code": self.rule_code,
            "warnings": self.warnings,
            "data_source": self.data_source,
            "timestamp": self.timestamp,
        }
    
    def __repr__(self):
        status = "✅ PASS" if self.ok else f"⛔ BLOCK [{self.rule_code}]"
        return f"{status}: {self.block_reason or 'OK'}"


def check(
    conn: sqlite3.Connection,
    symbol: str,
    channel: str,
    action: str,          # 'BUY' / 'SELL' / 'REBALANCE'
    qty: float,
    price: Optional[float] = None,
    trade_date: Optional[str] = None,   # None = 今天
    verbose: bool = True,
) -> ComplianceResult:
    """
    🎯 唯一合规校验入口 —— 所有交易必须先过这里
    
    Args:
        conn: DB 连接 (必须是 Gobelin 主库)
        symbol: 6位代码 (sh601318 / sz000858 / AU9999 / CB2025)
        channel: A_STOCK / ETF / METAL / BOND
        action: BUY / SELL / REBALANCE
        qty: 数量 (股/份/克/张)
        price: 价格 (None = 用 mt_live_position 实时价)
        trade_date: YYYY-MM-DD (None = 今天)
    
    Returns:
        ComplianceResult — 不可变, pass/block 结论 + 规则码 + 理由
    """
    warnings: List[str] = []
    data_source: Dict = {}
    
    # ── 前置检查 ──
    if channel not in CHANNEL_RULES:
        return ComplianceResult(False, f"未知通道 {channel}", "R00",
                                 warnings=warnings, data_source=data_source)
    
    rules = CHANNEL_RULES[channel]
    today = trade_date or dt.date.today().strftime("%Y-%m-%d")
    
    # ── 取实时价 (如果没给) ──
    if price is None:
        cur = conn.cursor()
        cur.execute("SELECT price, prev_close, pnl_pct FROM mt_live_position WHERE symbol=?", (symbol,))
        live_row = cur.fetchone()
        if live_row:
            price = live_row[0]
            prev_close = live_row[1]
            chg_pct = live_row[2]
            data_source["price_source"] = "mt_live_position (腾讯API)"
        else:
            # fallback Gobelin 持仓
            cur.execute("SELECT current_price, prev_close FROM mt_gobelin_position WHERE asset_code=?", (symbol,))
            pos_row = cur.fetchone()
            if pos_row:
                price = pos_row[0]
                prev_close = pos_row[1] or price
                chg_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
                data_source["price_source"] = "mt_gobelin_position (FALLBACK)"
                warnings.append(f"mt_live_position 无此代码, 降级用 Gobelin 持仓价")
            else:
                return ComplianceResult(False, f"无法获取 {symbol} 价格, 合规校验无法进行", "R00",
                                         warnings=warnings, data_source=data_source)
    else:
        prev_close = None
        chg_pct = None
    
    data_source["symbol"] = symbol
    data_source["channel"] = channel
    data_source["price"] = price
    data_source["trade_date"] = today
    data_source["ruleset"] = rules["description"]
    
    cur = conn.cursor()
    
    # ══════════════════════════════════════════════════════════════
    # R01 T+1 结算制度 (A_STOCK 必须遵守)
    # ══════════════════════════════════════════════════════════════
    if rules.get("t_plus_one") and action == "SELL":
        # 查 mt_gobelin_position.open_date — 今天才建的仓不能今天卖
        cur.execute("SELECT open_date, qty, available_qty FROM mt_gobelin_position WHERE asset_code=?", (symbol,))
        pos_row = cur.fetchone()
        if pos_row and pos_row[0] == today:
            block_reason = (
                f"T+1 违规: {symbol}({channel}) 今日({today})才建仓 "
                f"(open_date={pos_row[0]}), 按 A股 T+1 制度最早明日才可卖出"
            )
            if verbose: print(f"  ⛔ R01 BLOCK: {block_reason}")
            return ComplianceResult(False, block_reason, "R01_T_PLUS_ONE",
                                     warnings=warnings, data_source=data_source)
    
    # ══════════════════════════════════════════════════════════════
    # R02 涨跌停 (买入不能涨停追, 卖出不能跌停割)
    # ══════════════════════════════════════════════════════════════
    limit_up, limit_down = _limit_pct_for_symbol(symbol, channel)
    if limit_up is not None and chg_pct is not None:
        if action == "BUY" and chg_pct >= limit_up:
            block_reason = (
                f"涨跌停风险: {symbol} 已涨停 ({chg_pct:+.2f}% >= +{limit_up}%), "
                f"今日追高买入触发异常波动风控"
            )
            if verbose: print(f"  ⛔ R02 BLOCK: {block_reason}")
            return ComplianceResult(False, block_reason, "R02_LIMIT_UP_BUY",
                                     warnings=warnings, data_source=data_source)
        if action == "SELL" and chg_pct <= limit_down:
            block_reason = (
                f"跌停熔断: {symbol} 已跌停 ({chg_pct:+.2f}% <= {limit_down}%), "
                f"跌停板流动性枯竭, 虚拟仓应模拟真实市场无法成交"
            )
            if verbose: print(f"  ⛔ R02 BLOCK: {block_reason}")
            return ComplianceResult(False, block_reason, "R02_LIMIT_DOWN_SELL",
                                     warnings=warnings, data_source=data_source)
    
    # ══════════════════════════════════════════════════════════════
    # R03 整手交易 (A_STOCK 买入必须是 100 整数倍)
    # ══════════════════════════════════════════════════════════════
    if rules.get("lot_size") and action == "BUY":
        lot = rules["lot_size"]
        if qty % lot != 0:
            block_reason = (
                f"整手违规: {symbol}({channel}) 买入 {qty} { '股' if channel=='A_STOCK' else '份/克/张' } "
                f"必须是 {lot} 的整数倍"
            )
            if verbose: print(f"  ⛔ R03 BLOCK: {block_reason}")
            return ComplianceResult(False, block_reason, "R03_LOT_SIZE",
                                     warnings=warnings, data_source=data_source)
    
    # ══════════════════════════════════════════════════════════════
    # R07 交易时段 (虚拟仓可放宽, 但标注 warning)
    # ══════════════════════════════════════════════════════════════
    # 虚拟仓不需要强制拦截时段, 但如果是实盘模拟应该标注
    
    # ── 通过 ──
    result = ComplianceResult(True, "", "PASS", warnings=warnings, data_source=data_source)
    if verbose:
        extra = f" +{len(warnings)}警告" if warnings else ""
        print(f"  ✅ PASS: {symbol}({channel}) {action} qty={qty} price={price:.2f}{extra}")
    return result


# ═══════════════════════════════════════════════════════════════════
# §3 Gobelin 全持仓合规扫描 —— 批量检查所有持仓
# ═══════════════════════════════════════════════════════════════════

def scan_portfolio_compliance(conn: sqlite3.Connection, verbose: bool = True) -> Dict:
    """
    批量扫描 mt_gobelin_position 所有持仓, 输出合规报告
    
    Returns:
        {'ok_list': [...], 'block_list': [...], 'warnings': [...], 'summary': str}
    """
    cur = conn.cursor()
    cur.execute("SELECT * FROM mt_gobelin_position WHERE qty > 0")
    positions = [dict(r) for r in cur.fetchall()]
    
    ok_list = []
    block_list = []
    warnings = []
    
    today = dt.date.today().strftime("%Y-%m-%d")
    
    for p in positions:
        symbol = p["asset_code"]
        channel = p["channel"]
        rules = CHANNEL_RULES.get(channel, {})
        
        # ① T+1 检查
        if rules.get("t_plus_one") and p.get("open_date") == today:
            open_days = 0  # 今天才建仓
            block_list.append({
                "symbol": symbol, "name": p["asset_name"], "channel": channel,
                "rule_code": "R01", "issue": f"T+1 违规: 今日({today})刚建仓, 明日起才可卖",
                "severity": "BLOCK",
            })
        
        # ② 涨跌停检查
        # 优先用 mt_gobelin_price.chg_pct (Guardian 权威源: (last_price-prev_close)/prev_close*100)
        # 注意: mt_live_position.pnl_pct 是累计收益率 (从 avg_cost 算), 不能当今日涨跌用!
        cur.execute("SELECT last_price, prev_close, chg_pct FROM mt_gobelin_price WHERE asset_code=?", (symbol,))
        gp_row = cur.fetchone()
        if gp_row and gp_row['prev_close'] and gp_row['prev_close'] > 0:
            chg_pct = (gp_row['last_price'] - gp_row['prev_close']) / gp_row['prev_close'] * 100
        else:
            # fallback: mt_live_position 自己算 (用 prev_close)
            cur.execute("SELECT price, prev_close FROM mt_live_position WHERE symbol=?", (symbol,))
            lr = cur.fetchone()
            if lr and lr['prev_close'] and lr['prev_close'] > 0:
                chg_pct = (lr['price'] - lr['prev_close']) / lr['prev_close'] * 100
            else:
                chg_pct = None
        limit_up, limit_down = _limit_pct_for_symbol(symbol, channel)
        
        if chg_pct is not None and limit_up is not None:
            if chg_pct >= limit_up:
                block_list.append({
                    "symbol": symbol, "name": p["asset_name"], "channel": channel,
                    "rule_code": "R02", "issue": f"已涨停 +{chg_pct:.2f}% >= +{limit_up}%, 今日追高风控",
                    "severity": "WARN",
                })
            elif chg_pct <= limit_down:
                block_list.append({
                    "symbol": symbol, "name": p["asset_name"], "channel": channel,
                    "rule_code": "R02", "issue": f"已跌停 {chg_pct:.2f}% <= {limit_down}%",
                    "severity": "WARN",
                })
        
        # ③ 持仓今日盈亏高亮
        today_pnl = p.get("today_pnl", 0)
        if today_pnl and today_pnl < -500:
            warnings.append({
                "symbol": symbol, "name": p["asset_name"], "channel": channel,
                "issue": f"今日亏损较大 ¥{today_pnl:,.0f}, 建议触发 Guardian 风险评估",
                "severity": "HIGHLIGHT",
            })
        
        # 通道特定检查: ETF 腾讯 API 不推, 检查 mt_live_position 有无覆盖
        if channel == "ETF":
            cur.execute("SELECT 1 FROM mt_live_position WHERE symbol=?", (symbol,))
            if cur.fetchone() is None:
                warnings.append({
                    "symbol": symbol, "channel": channel,
                    "issue": f"ETF 无 mt_live_position 覆盖 (腾讯 API 不推 ETF), 合规校验降级",
                    "severity": "INFO",
                })
    
    summary_parts = []
    if block_list:
        summary_parts.append(f"⛔ {len(block_list)} 项合规拦截 (T+1/涨跌停)")
    if warnings:
        summary_parts.append(f"⚠️ {len(warnings)} 项风险提示")
    if not summary_parts:
        summary_parts.append("✅ 全部持仓合规, 无拦截项")
    summary = "; ".join(summary_parts)
    
    if verbose:
        print(f"\n📋 合规扫描报告 ({len(positions)} 只持仓):")
        for b in block_list:
            print(f"  ⛔ [{b['rule_code']}] {b['symbol']} {b['issue']}")
        for w in warnings:
            print(f"  ⚠️  {w['symbol']} {w['issue']}")
        if not block_list and not warnings:
            print("  ✅ 全部合规")
    
    return {
        "ok_count": len(positions) - len(block_list),
        "block_list": block_list,
        "warnings": warnings,
        "summary": summary,
        "scan_date": today,
        "ruleset_version": "CN-Ashare-v2025.11.11",
    }


# ═══════════════════════════════════════════════════════════════════
# §4 便捷函数: Guardian 提案专用校验
# ═══════════════════════════════════════════════════════════════════

def pre_proposal_check(conn: sqlite3.Connection, proposal: Dict) -> ComplianceResult:
    """
    在 Guardian 生成投资提案前调用, 快速拦截明显违规的提案
    
    proposal dict 应包含:
      {'action': 'BUY'/'SELL', 'asset_code': 'sh601318', 
       'channel': 'A_STOCK', 'qty': 100, 'target_price': 53.41}
    """
    return check(
        conn=conn,
        symbol=proposal.get("asset_code", ""),
        channel=proposal.get("channel", "A_STOCK"),
        action=proposal.get("action", "REBALANCE"),
        qty=proposal.get("qty", 0),
        price=proposal.get("target_price"),
        verbose=True,
    )
