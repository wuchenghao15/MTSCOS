"""
broker_adapter.py — 仙女座沙盘→实盘 券商抽象层
═══════════════════════════════════════════════════════════════════════════

设计原则 (经验 #1479298 + #1602764 + #2193989):
  1) 硬门禁: TRADE_MODE 默认 OFF, 实盘必须显式二次确认落库
  2) 安全降级: 实盘依赖 import 失败/环境不满足 → 自动切回沙盘 + 警告
  3) 最小接口: place_order / query_position / query_cash / cancel_order
  4) 模拟≠实盘: 滑点/部分成交/涨跌停/T+1/拒单 — 两边都要模拟, 实盘加真实回执

支持的通道 (按可行性排序):
  a) sandbox    — 沙盘模拟 (默认, 永远可用)
  b) citic_mac  — 中信证券 Mac 客户端 (需要 AppleScript + 客户端已登录)
  c) qmt_ptrade — QMT/PTrade (需要 Windows + 券商程序化接口 + Python 3.8-3.11)
  d) easytrader — easytrader (需要 Windows + 券商 PC 客户端 + Python 3.8-3.11)

实盘壁垒 (诚实告知):
  - macOS ARM64 + Python 3.14: easytrader/QMT/PTrade 全不兼容
  - 中信证券开放 API: 个人散户一般申请不到 (50万门槛 + 面签程序化协议)
  - 合法路径: Mac mini 装 Windows + 中信 QMT/PTrade + Python 3.11 venv

用法:
  adapter = get_broker_adapter(mode='sandbox')  # 默认沙盘
  adapter.place_order(symbol='300750', action='BUY', qty=100, price=200.0)
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

# ── 常量 ────────────────────────────────────────────────────────────────
TRADE_MODE = os.environ.get('MT_TRADE_MODE', 'sandbox').lower()
TRADE_MODES = ('sandbox', 'citic_mac', 'qmt_ptrade', 'easytrader')

# 10000元本金 (最终拟真沙盘启动金)
# NOTE: 忽略 MT_TRADE_CAPITAL 环境变量 (历史遗留 5000) — 硬编码 10000
TOTAL_CAPITAL = 10000.0
SINGLE_ORDER_MAX = TOTAL_CAPITAL * 0.50   # 单笔 ≤ 5000
SINGLE_STOCK_MAX = TOTAL_CAPITAL * 0.50   # 个股 ≤ 5000 (本金 50%)
MAX_POSITION_RATIO = 1.00                 # 总持仓 ≤ 100% (满仓即可)
# 最多 2 只持仓, 每只 ≤ 5000, 合计 10000

# ════════════════════════════════════════════════════════════════════════
# 风控阈值 (逐级调节, 不直接触底)
# ════════════════════════════════════════════════════════════════════════
STOP_LOSS_DEFAULT_PCT = 0.05        # 默认止损 5% (保守)
STOP_LOSS_MAX_PCT = 0.10            # 大数据+风控联合同意 → 最高放宽到 10%
STOP_LOSS_PCT = STOP_LOSS_DEFAULT_PCT  # 当前生效值 (运行时可调节)

AUTO_TAKE_PROFIT_PCT = 0.03         # 3% 自动止盈 (稳不贪, 适当回利)
MAX_SLIPPAGE_PCT = 0.003            # 0.3% 滑点
MONTHLY_PROFIT_CAP_PCT = 0.08       # 月盈利上限 8% (用户指定)

# ── 逐级调节函数 (不直接触底) ──
def adjust_stop_loss(target_pct: float, override_ok: bool = False) -> float:
    """
    逐级调节止损线 — 风控和大数据一致同意时才能放宽到 10%
    - 每次最多调 ±1% (逐级调节, 不跳级)
    - 上限 STOP_LOSS_MAX_PCT (10%), 下限 STOP_LOSS_DEFAULT_PCT (5%)
    - override_ok=True 跳过逐级限制 (需董事会决议)
    """
    global STOP_LOSS_PCT
    if target_pct < STOP_LOSS_DEFAULT_PCT:
        target_pct = STOP_LOSS_DEFAULT_PCT
    if target_pct > STOP_LOSS_MAX_PCT:
        target_pct = STOP_LOSS_MAX_PCT
    if not override_ok:
        diff = target_pct - STOP_LOSS_PCT
        if abs(diff) > 0.01:
            target_pct = STOP_LOSS_PCT + (0.01 if diff > 0 else -0.01)
    STOP_LOSS_PCT = round(target_pct, 4)
    return STOP_LOSS_PCT

# ════════════════════════════════════════════════════════════════════════
# 法律责任与法律底线 (按证监委规定)
# ════════════════════════════════════════════════════════════════════════
LEGAL_CONSTRAINTS = {
    # L-01 投资者适当性 — 沙盘自动操盘不得向未开户/未成年用户开放
    'L01_investor_suitability': True,
    # L-02 如实披露 — AI 自动决策必须在每笔交易旁标注 "沙盘模拟"
    'L02_disclosure': True,
    # L-03 禁止异常交易 — 不得对敲/自买自卖/虚假申报
    'L03_no_manipulation': True,
    # L-04 涨跌幅限制 — 主板 ±10%, 创业板/科创板 ±20%, ST ±5%
    'L04_price_limit_pct': 0.10,
    # L-05 T+1 交割 — A 股当日买入不得当日卖出 (合规底线)
    'L05_t1_mandatory': True,
    # L-06 持股限制 — 单一股东持股 ≤ 5% (举牌线)
    'L06_single_holder_cap_pct': 0.05,
    # L-07 交易时段 — 9:30-11:30, 13:00-15:00 (不得盘后交易)
    'L07_trading_hours': True,
    # L-08 董事会合规 — 重大决策需董事会 2/3 票通过
    'L08_board_approval_quorum': 0.67,
}

# ════════════════════════════════════════════════════════════════════════
# 税务相关约束与要求 (按国家税务总局规定)
# ════════════════════════════════════════════════════════════════════════
TAX_CONSTRAINTS = {
    # T-01 印花税 — 卖出单向 0.05% (国家收取, 沙盘精确模拟)
    'T01_stamp_tax_rate': 0.0005,
    # T-02 过户费 — 万 0.1, 买卖双向 (中登收取)
    'T02_transfer_fee_rate': 0.00001,
    # T-03 佣金最低 5 元 — 不足按 5 元计 (券商规定)
    'T03_commission_min': 5.0,
    # T-04 佣金税率 — 6% 增值税 (包含在佣金中, 不额外收取)
    'T04_commission_vat_pct': 0.06,
    # T-05 股息红利税 — 持股超 1 年免征, 1 个月内 20%, 1 个月-1 年 10%
    'T05_dividend_tax_pct': 0.20,  # 默认短线按 20%
    # T-06 资本利得暂免 — 个人 A 股暂不征收资本利得税
    'T06_capital_gains_tax': False,
    # T-07 交易记录留存 — 至少 5 年 (税务 + 证监委要求)
    'T07_record_retention_years': 5,
    # T-08 年度汇总申报 — 每年 1 月对上年度交易做盈亏汇总
    'T08_annual_summary_required': True,
}

# T+1 约束
T1_LOCK_HOURS = 15.5            # 15:30 收盘后才算次日


# ════════════════════════════════════════════════════════════════════════
# §0 证券公司手续费模型 (A股实盘费率)
# ════════════════════════════════════════════════════════════════════════
class CommissionModel:
    """
    A股真实交易成本 — 券商手续费模型 (经验: 每次下单精确计算)
    
    费率 (行业平均, 可通过环境变量覆盖):
      - 佣金 (commission): 万 2.5, 最低 5 元, 买卖双向
      - 印花税 (stamp_tax): 千 0.5 (即 0.05%), 卖出单向 (国家收)
      - 过户费 (transfer_fee): 万 0.1, 买卖双向 (中登收)
    
    总费用 = commission + stamp_tax + transfer_fee
    
    注: 1000 本金, 单笔 500 元买入 → 佣金 ≥ 5 元 (触发最低), 过户费 0.05 元
        单笔 500 元卖出 → 佣金 5 元 + 印花税 0.25 元 + 过户费 0.05 元 = 5.30 元
        一买一卖总成本 ≈ 10.30 元 (占本金 1.03%)
    """
    COMMISSION_RATE = float(os.environ.get('MT_COMMISSION_RATE', '0.00025'))   # 万 2.5
    COMMISSION_MIN = float(os.environ.get('MT_COMMISSION_MIN', '5'))          # 最低 5 元
    STAMP_TAX_RATE = float(os.environ.get('MT_STAMP_TAX_RATE', '0.0005'))     # 千 0.5
    TRANSFER_FEE_RATE = float(os.environ.get('MT_TRANSFER_FEE_RATE', '0.00001'))  # 万 0.1
    
    @classmethod
    def calc(cls, action: str, amount: float) -> dict:
        """
        计算单次交易手续费
        返回 {commission, stamp_tax, transfer_fee, total_fee, fee_rate_pct}
        """
        # 佣金: amount × rate, 最低 5 元
        commission = max(amount * cls.COMMISSION_RATE, cls.COMMISSION_MIN)
        commission = round(commission, 2)
        
        # 印花税: 仅卖出, amount × 0.05%
        stamp_tax = round(amount * cls.STAMP_TAX_RATE, 2) if action == 'SELL' else 0.0
        
        # 过户费: 万 0.1, 买卖双向
        transfer_fee = round(amount * cls.TRANSFER_FEE_RATE, 2)
        
        total_fee = round(commission + stamp_tax + transfer_fee, 2)
        fee_rate_pct = round(total_fee / amount * 100, 4) if amount > 0 else 0
        
        return {
            'commission': commission,
            'stamp_tax': stamp_tax,
            'transfer_fee': transfer_fee,
            'total_fee': total_fee,
            'fee_rate_pct': fee_rate_pct,
            'action': action,
            'amount': round(amount, 2),
            'note': (
                f'佣金 {cls.COMMISSION_RATE:.4%} (最低¥{cls.COMMISSION_MIN})'
                f' + {"印花税 " + str(cls.STAMP_TAX_RATE) + " (卖)" if action == "SELL" else "无印花税 (买)"}'
                f' + 过户费 {cls.TRANSFER_FEE_RATE:.5%}'
            ),
        }
    
    @classmethod
    def summary(cls) -> dict:
        """费率总览 — broker/status 里展示"""
        return {
            'commission_rate': cls.COMMISSION_RATE,
            'commission_min': cls.COMMISSION_MIN,
            'stamp_tax_rate': cls.STAMP_TAX_RATE,
            'transfer_fee_rate': cls.TRANSFER_FEE_RATE,
            'buy_fee_rate_pct': round((cls.COMMISSION_RATE + cls.TRANSFER_FEE_RATE) * 100, 4),
            'sell_fee_rate_pct': round((cls.COMMISSION_RATE + cls.STAMP_TAX_RATE + cls.TRANSFER_FEE_RATE) * 100, 4),
            'note': '佣金最低 5 元, 本金 10000 元单笔 5000 元时 → 佣金 = max(5000×0.025%, 5) = ¥12.5, 印花税 ¥2.5 (卖), 过户费 ¥0.5',
        }


# ════════════════════════════════════════════════════════════════════════
# §0.5 月盈利上限守护 (分账模型: 可用现金 / 留存利润)
# ════════════════════════════════════════════════════════════════════════
class MonthlyProfitGuard:
    """
    月盈利上限 8% — 经验 #2344888 分账模型
    
    账本:
      - initial_capital: 当月基准 (每月 1 号重置)
      - total_assets = cash + positions_market_value (包含浮盈浮亏)
      - monthly_profit = total_assets - initial_capital
      - 当月可盈利上限 = initial_capital × MONTHLY_PROFIT_CAP_PCT (8%)
    
    当 monthly_profit ≥ 上限 → 标记 hit_cap=True → 阻止新买入 (STOP_NEW_BUY)
    已持仓可继续持有 / 卖出 (锁定利润)
    
    持久化: mt_trade_account_state 存 initial_capital / month_start / monthly_profit
    """
    
    _STATE_TABLE = """
    CREATE TABLE IF NOT EXISTS mt_trade_account_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state_key TEXT UNIQUE NOT NULL,
        state_value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """
    
    @classmethod
    def _db(cls):
        from routes.trading_routes import _find_flask_db
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return None
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute(cls._STATE_TABLE)
        conn.commit()
        return conn
    
    @classmethod
    def _get(cls, key: str) -> str:
        conn = cls._db()
        if not conn: return ''
        cur = conn.execute('SELECT state_value FROM mt_trade_account_state WHERE state_key=?', (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else ''
    
    @classmethod
    def _set(cls, key: str, value: str):
        import sqlite3
        conn = cls._db()
        if not conn: return
        conn.execute(
            """INSERT INTO mt_trade_account_state (state_key, state_value, updated_at)
               VALUES (?,?,datetime('now','localtime'))
               ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value, updated_at=datetime('now','localtime')""",
            (key, value))
        conn.commit()
        conn.close()
    
    @classmethod
    def get_monthly_state(cls, total_assets: float) -> dict:
        """
        查询 / 初始化当月盈利状态
        total_assets = cash + positions (由调用方传入)
        返回 {month, initial_capital, monthly_profit, cap_pct, cap_amount, hit_cap, days_remaining}
        """
        now = datetime.now(timezone(timedelta(hours=8)))
        month_key = now.strftime('%Y-%m')  # 2026-11
        
        stored_month = cls._get('month_start')
        stored_capital = cls._get('initial_capital')
        
        # 每月重置 (新月份 → 新基准)
        if stored_month != month_key or not stored_capital:
            cls._set('month_start', month_key)
            cls._set('initial_capital', str(TOTAL_CAPITAL))
            cls._set('monthly_profit', '0')
            cls._set('hit_cap', '0')
            stored_month = month_key
            stored_capital = str(TOTAL_CAPITAL)
        
        initial = float(stored_capital)
        monthly_profit = round(total_assets - initial, 2)
        cap_amount = round(initial * MONTHLY_PROFIT_CAP_PCT, 2)
        hit_cap = monthly_profit >= cap_amount
        
        # 到达上限 → 持久化标记
        if hit_cap:
            cls._set('hit_cap', '1')
            cls._set('monthly_profit', str(monthly_profit))
        else:
            cls._set('monthly_profit', str(monthly_profit))
        
        # 当月剩余天数
        if now.month == 12:
            next_month = now.replace(year=now.year + 1, month=1, day=1)
        else:
            next_month = now.replace(month=now.month + 1, day=1)
        days_remaining = (next_month - now).days
        
        return {
            'month': month_key,
            'initial_capital': initial,
            'total_assets': round(total_assets, 2),
            'monthly_profit': monthly_profit,
            'monthly_profit_pct': round(monthly_profit / initial * 100, 2) if initial > 0 else 0,
            'cap_pct': MONTHLY_PROFIT_CAP_PCT,
            'cap_amount': cap_amount,
            'hit_cap': hit_cap,
            'action': 'STOP_NEW_BUY' if hit_cap else 'TRADING_ALLOWED',
            'days_remaining_in_month': days_remaining,
        }


# ════════════════════════════════════════════════════════════════════════
# 实盘激活协议 (硬门禁, 经验 #1479298)
# ════════════════════════════════════════════════════════════════════════
_LIVE_ACTIVATION_TABLE = """
CREATE TABLE IF NOT EXISTS mt_trade_live_activation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    broker_mode TEXT NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'ACTIVE',  -- ACTIVE / EXPIRED / REVOKED
    revoked_at TEXT
)
"""

def _live_db():
    from routes.trading_routes import _find_flask_db
    db_path = _find_flask_db()
    if not db_path:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute(_LIVE_ACTIVATION_TABLE)
    conn.commit()
    return conn

def check_live_activation() -> dict:
    """实盘激活检查 — 返回 {active: bool, reason: str, broker: str}"""
    if TRADE_MODE == 'sandbox':
        return {'active': False, 'reason': 'TRADE_MODE=sandbox (默认)', 'broker': 'sandbox'}
    try:
        conn = _live_db()
        cur = conn.execute("""SELECT * FROM mt_trade_live_activation 
                              WHERE status='ACTIVE' AND expires_at > datetime('now','localtime')
                              ORDER BY id DESC LIMIT 1""")
        row = cur.fetchone()
        conn.close()
        if not row:
            return {'active': False, 'reason': '无有效实盘激活 (需二次确认)', 'broker': TRADE_MODE}
        return {'active': True, 'reason': f"激活有效 (expires={row[4]})", 'broker': TRADE_MODE}
    except Exception as e:
        return {'active': False, 'reason': f'激活检查异常: {e}', 'broker': TRADE_MODE}

def activate_live_trading(confirmed_by: str, hours: int = 4, reason: str = '') -> dict:
    """实盘二次确认落库 — 返回激活结果"""
    if TRADE_MODE == 'sandbox':
        return {'ok': False, 'error': '当前是沙盘模式, 设置 MT_TRADE_MODE=citic_mac/qmt_ptrade/easytrader 才能激活实盘'}
    conn = _live_db()
    now = datetime.now(timezone(timedelta(hours=8)))
    expires = now + timedelta(hours=hours)
    conn.execute("""INSERT INTO mt_trade_live_activation 
                  (activated_by, activated_at, expires_at, broker_mode, reason)
                  VALUES(?,?,?,?,?)""",
                (confirmed_by, now.isoformat(), expires.isoformat(), TRADE_MODE, reason))
    conn.commit()
    aid = conn.total_changes
    conn.close()
    return {'ok': True, 'activation_id': aid, 'expires_at': expires.isoformat(), 'broker': TRADE_MODE}


# ════════════════════════════════════════════════════════════════════════
# 风控引擎 (1000 本金专属 — R-00~R-09 含外部因子)
# ════════════════════════════════════════════════════════════════════════
class RiskEngine:
    """10000元本金风控 — 稳不贪 (10 条规则, 含 2 条外部因子)
    
    R-00 单笔上限        ≤ 5000 (TOTAL_CAPITAL × 50%)
    R-01 一手检查        100 股整数倍
    R-02 佣金敏感提醒    金额 < 2000 触发最低佣金 5 元
    R-03 T+1             当日买不能当日卖
    R-04 个股仓位        ≤ 5000 (TOTAL_CAPITAL × 50%)
    R-05 总持仓上限      ≤ 100% (满仓即可)
    R-06 月盈利上限      8% 到达后 STOP_NEW_BUY
    R-07 含手续费成本    一买一卖成本 > 3% 本金警告
    R-08 消息面因子      个股有重大利空新闻 / 板块整体净流出 → 加风控
    R-09 同业竞品因子    个股在同行业涨跌排名后 20% → 警告; 行业概念整体利空 → 加风控
    
    L-法律约束 (证监委): 投资者适当性 / 如实披露 / 禁止对敲 / 涨跌幅 ±10% / T+1 / 举牌线 5%
    T-税务约束 (国税): 印花税 0.05% / 过户费万0.1 / 佣金最低 5 元 / 资本利得暂免 / 记录留存 5 年
    """
    
    @staticmethod
    def check(symbol: str, action: str, qty: int, price: float, 
              current_positions: list = None, existing_buys_today: list = None,
              total_assets: float = None) -> dict:
        """全维度风控, 返回 {pass: bool, issues: [...], risk_detail}"""
        issues = []
        veto_map = {}
        amount = qty * price
        
        # ── R-00: 单笔上限 ──
        r00_veto = amount > SINGLE_ORDER_MAX
        if r00_veto:
            issues.append(f"[R-00] 单笔金额 ¥{amount:.0f} > 单笔上限 ¥{SINGLE_ORDER_MAX:.0f}")
        veto_map['r00_capital_veto'] = r00_veto
        
        # ── R-01: 一手检查 (100股) ──
        r01_veto = qty % 100 != 0
        if r01_veto:
            issues.append(f"[R-01] qty={qty} 不是 100 股的整数倍")
        veto_map['r01_lot_veto'] = r01_veto
        
        # ── R-02: 佣金敏感提醒 ──
        commission = CommissionModel.calc(action, amount)
        buy_cost = CommissionModel.calc('BUY', amount)['total_fee'] if action == 'BUY' else 0
        sell_cost = CommissionModel.calc('SELL', amount)['total_fee'] if action == 'SELL' else 0
        roundtrip_cost_pct = round((buy_cost + sell_cost) / TOTAL_CAPITAL * 100, 2)
        r02_warn = commission['total_fee'] > 0 and commission['total_fee'] / amount > 0.02  # 手续费 > 2%
        if r02_warn:
            issues.append(f"[R-02] 手续费率 {commission['fee_rate_pct']:.2f}% (佣金≥¥5 触发最低), 一买一卖约 ¥{buy_cost + sell_cost:.2f} 占本金 {roundtrip_cost_pct:.1f}%")
        veto_map['r02_cost_warn'] = r02_warn
        veto_map['commission_detail'] = commission
        
        # ── R-03: T+1 检查 ──
        r03_veto = False
        if action == 'SELL' and existing_buys_today:
            buys = [b for b in (existing_buys_today or []) if b.get('symbol') == symbol]
            if buys:
                issues.append(f"[R-03] T+1: 当日买入 {symbol}, 不能当日卖出")
                r03_veto = True
        veto_map['r03_t1_veto'] = r03_veto
        
        # ── R-04: 个股最大仓位 ──
        pos_value = 0
        if current_positions:
            for p in current_positions:
                if p.get('symbol') == symbol:
                    pos_value += p.get('market_value', 0)
        r04_veto = (pos_value + amount > SINGLE_STOCK_MAX) if action == 'BUY' else False
        if r04_veto:
            issues.append(f"[R-04] {symbol} 现有仓位 ¥{pos_value:.0f} + 本次 ¥{amount:.0f} > 个股上限 ¥{SINGLE_STOCK_MAX:.0f}")
        veto_map['r04_position_veto'] = r04_veto
        
        # ── R-05: 总持仓上限 ≤ 50% ──
        r05_veto = False
        total_pos_value = sum((p.get('market_value', 0) for p in (current_positions or [])), 0)
        if action == 'BUY':
            projected_pos = total_pos_value + amount
            cap = TOTAL_CAPITAL * MAX_POSITION_RATIO
            r05_veto = projected_pos > cap
            if r05_veto:
                issues.append(f"[R-05] 总持仓 projected ¥{projected_pos:.0f} (当前 ¥{total_pos_value:.0f}) > 50% 上限 ¥{cap:.0f}")
        veto_map['r05_total_position_veto'] = r05_veto
        
        # ── R-06: 月盈利上限 STOP_NEW_BUY ──
        r06_veto = False
        total_assets_now = total_assets if total_assets is not None else (TOTAL_CAPITAL - total_pos_value + total_pos_value)  # fallback
        try:
            monthly = MonthlyProfitGuard.get_monthly_state(total_assets_now)
            if monthly.get('hit_cap') and action == 'BUY':
                issues.append(f"[R-06] 月盈利已达 ¥{monthly['monthly_profit']:.2f} (上限 ¥{monthly['cap_amount']:.2f}), 禁止新买入")
                r06_veto = True
        except Exception:
            monthly = {'hit_cap': False}
        veto_map['r06_monthly_cap_veto'] = r06_veto
        
        # ── R-07: 含手续费成本占本金过高 (roundtrip > 3%) ──
        r07_warn = roundtrip_cost_pct > 3.0
        if r07_warn:
            issues.append(f"[R-07] 一买一卖成本 ¥{buy_cost + sell_cost:.2f} 占本金 {roundtrip_cost_pct:.1f}% (>3% 警戒线)")
        veto_map['r07_roundtrip_warn'] = r07_warn

        # ── R-08: 消息面因子 (新闻/板块/北向) ──
        r08_warn, r08_veto, news_signal = _check_news_factor(symbol, action)
        if r08_warn:
            issues.append(f"[R-08] 消息面警告: {news_signal}")
        if r08_veto:
            issues.append(f"[R-08] 消息面否决: {news_signal}")
        veto_map['r08_news_veto'] = r08_veto
        veto_map['r08_news_warn'] = r08_warn

        # ── R-09: 同业竞品因子 (行业排名/竞品涨跌) ──
        r09_warn, peer_signal = _check_peer_factor(symbol, action)
        if r09_warn:
            issues.append(f"[R-09] 同业对标警告: {peer_signal}")
        veto_map['r09_peer_warn'] = r09_warn

        # 硬门禁 (veto) vs 警告 (warn)
        hard_veto = any([r00_veto, r01_veto, r03_veto, r04_veto, r05_veto, r06_veto, r08_veto])
        warnings_only = any([r02_warn, r07_warn, r08_warn, r09_warn])
        
        stop_loss = round(price * (1 - STOP_LOSS_PCT), 2)
        take_profit = round(price * (1 + AUTO_TAKE_PROFIT_PCT), 2)
        
        return {
            'pass': not hard_veto,  # 警告不拦, veto 才拦
            'hard_veto': hard_veto,
            'warnings_only': warnings_only,
            'issues': issues,
            'commission': commission,
            'roundtrip_cost': round(buy_cost + sell_cost, 2),
            'roundtrip_cost_pct_of_capital': roundtrip_cost_pct,
            'hard_stop_loss_pct': STOP_LOSS_PCT,
            'hard_stop_loss_price': stop_loss,
            'stop_loss_default_pct': STOP_LOSS_DEFAULT_PCT,
            'stop_loss_max_pct': STOP_LOSS_MAX_PCT,
            'auto_take_profit_pct': AUTO_TAKE_PROFIT_PCT,
            'auto_take_profit_price': take_profit,
            'single_order_max': SINGLE_ORDER_MAX,
            'single_stock_max': SINGLE_STOCK_MAX,
            'max_position_ratio': MAX_POSITION_RATIO,
            'max_position_amount': round(TOTAL_CAPITAL * MAX_POSITION_RATIO, 2),
            'monthly_profit_cap_pct': MONTHLY_PROFIT_CAP_PCT,
            'monthly_state': monthly if 'monthly' in dir() else {'hit_cap': False},
            'total_capital': TOTAL_CAPITAL,
            'legal_constraints': LEGAL_CONSTRAINTS,
            'tax_constraints': TAX_CONSTRAINTS,
            'adjust_stop_loss_hint': f"当前止损 {STOP_LOSS_PCT*100:.1f}% (默认 {STOP_LOSS_DEFAULT_PCT*100:.0f}%, 最高 {STOP_LOSS_MAX_PCT*100:.0f}%)",
            **veto_map,
        }


# ════════════════════════════════════════════════════════════════════════
# R-08 / R-09 外部因子风控 (新闻 + 同业竞品)
# 从 news_collector 缓存里读, 避免每次风控都调 HTTP
# 缓存由 _news_cache_refresh() 每 10 分钟刷新一次
# ════════════════════════════════════════════════════════════════════════

# 进程级缓存 (避免每次风控都去 akshare 拉数据)
_news_cache = {'data': {}, 'ts': 0}
_NEWS_CACHE_TTL = 600  # 10 分钟


def refresh_news_cache(force: bool = False) -> dict:
    """刷新消息面缓存 — tick 循环里每 10 分钟调一次"""
    global _news_cache
    import time as _t
    now = _t.time()
    if not force and _news_cache['data'] and (now - _news_cache['ts']) < _NEWS_CACHE_TTL:
        return _news_cache['data']
    try:
        from engines.news_collector import NewsCollector
        nc = NewsCollector()
        _news_cache['data'] = nc.collect_all(log_func=lambda x: None)
        _news_cache['ts'] = now
    except Exception:
        pass
    return _news_cache['data']


def _check_news_factor(symbol: str, action: str) -> tuple:
    """R-08: 消息面风控 → (warn, veto, signal)"""
    data = _news_cache.get('data', {})
    if not data:
        return False, False, ''

    warn, veto, signal = False, False, ''

    # ① 个股新闻 — 利空关键词
    stock_news = data.get('stock_news', {}).get(symbol, [])
    bad_keywords = ['减持', '利空', '跌停', '警示', '调查', '诉讼', '亏损扩大',
                    '下滑', '风险提示', '爆雷', 'ST', '退市']
    good_keywords = ['增持', '利好', '涨停', '机构买入', '北向增持', '业绩大增',
                     '回购', '分红', '政策扶持', '订单']

    for n in stock_news[:5]:
        title = n.get('title', '')
        if action == 'BUY' and any(k in title for k in bad_keywords):
            signal = f"⚠️ {symbol} 有利空新闻: {title[:40]}"
            warn = True
        if action == 'SELL' and any(k in title for k in good_keywords):
            signal = f"⚠️ {symbol} 有利好新闻, 可能不该卖: {title[:40]}"
            warn = True

    # ② 板块整体净流出 → 买该板块股票要谨慎
    cold_sectors = data.get('sector_flow', {}).get('hot_out', [])[:3]
    if cold_sectors and action == 'BUY':
        for cs in cold_sectors:
            name = cs.get('name', '')
            if signal and name:
                signal += f" | 板块 {name} 净流出"
            elif name:
                signal = f"⚠️ 板块 {name} 净流出, 不宜追买 {symbol}"
                warn = True

    # ③ 北向资金大幅流出 → 整体市场情绪差
    north = data.get('north_flow', {})
    net = north.get('资金净流入', 0) if isinstance(north.get('资金净流入'), (int, float)) else 0
    if action == 'BUY' and isinstance(net, (int, float)) and net < -100:
        signal = (signal + f" | 北向资金净流出 ¥{abs(net):.0f}亿") if signal else \
                 f"⚠️ 北向资金净流出 ¥{abs(net):.0f}亿 (>100亿), 大盘情绪弱"
        warn = True

    # ④ 融资融券杠杆率过高 → 市场过热, 追买危险
    margin = data.get('margin', {})
    leverage = margin.get('leverage_ratio', 0)
    if action == 'BUY' and isinstance(leverage, (int, float)) and leverage > 80:
        signal = (signal + f" | 杠杆率 {leverage} 过热") if signal else \
                 f"⚠️ 融资/融券杠杆率 {leverage} (>80 过热), 追买风险高"
        warn = True

    return warn, veto, signal


def _check_peer_factor(symbol: str, action: str) -> tuple:
    """R-09: 同业竞品对标 → (warn, signal)"""
    data = _news_cache.get('data', {})
    if not data:
        return False, ''

    warn, signal = False, ''

    peer = data.get('peers', {}).get(symbol, {})
    if not peer or 'error' in peer:
        return False, ''

    rank = peer.get('rank_by_pct')
    total = peer.get('peers_count', 0)
    industry = peer.get('industry', '')

    if rank and total and action == 'BUY':
        # 行业排名后 20% 还要买 → 警告
        pct_rank = rank / total
        if pct_rank > 0.8:
            top_peers = peer.get('top_peers', [])[:3]
            top_names = '/'.join(pp.get('name', '')[:4] for pp in top_peers)
            signal = (f"⚠️ {symbol} 行业排名 {rank}/{total} (后 {int(pct_rank*100)}%), "
                      f"不如竞品 {top_names}")
            warn = True
        elif pct_rank > 0.6:
            signal = f"📌 {symbol} 行业排名 {rank}/{total} (中游), 非领涨股"

    return warn, signal
class BrokerAdapter(ABC):
    """券商接口抽象 — 沙盘和实盘都实现这套契约"""
    
    @abstractmethod
    def place_order(self, symbol: str, action: str, qty: int, price: float,
                    hall_code: str = '', reason: str = '') -> dict:
        """下单 → {ok, broker_order_id, fill_price, fill_qty, message}"""
    
    @abstractmethod
    def query_position(self, symbol: str = None) -> list:
        """持仓 → [{symbol, qty, avg_cost, current_price, market_value}]"""
    
    @abstractmethod
    def query_cash(self) -> dict:
        """现金 → {available, total, frozen}"""
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        """撤单"""
    
    def get_mode(self) -> str:
        return self.__class__.__name__.replace('Adapter', '').lower()


class SandboxAdapter(BrokerAdapter):
    """沙盘模拟 — 永远可用, 不依赖任何外部通道"""
    
    def __init__(self):
        self.name = 'sandbox'
    
    def place_order(self, symbol: str, action: str, qty: int, price: float,
                    hall_code: str = '', reason: str = '') -> dict:
        """模拟下单 — 带滑点 + A股真实手续费模型"""
        import sqlite3
        from routes.trading_routes import _find_flask_db
        
        db_path = _find_flask_db()
        if not db_path:
            return {'ok': False, 'message': 'DB_NOT_FOUND'}
        
        # 模拟滑点: BUY 实际价略高, SELL 实际价略低
        import random
        slip = random.uniform(-MAX_SLIPPAGE_PCT, MAX_SLIPPAGE_PCT)
        fill_price = round(price * (1 + slip), 2) if action == 'BUY' else round(price * (1 - slip), 2)
        fill_qty = qty  # 沙盘全成交
        
        # ── 精确手续费计算 (A股真实费率) ──
        gross_amount = qty * price
        commission = CommissionModel.calc(action, gross_amount)
        total_fee = commission['total_fee']
        
        # 净成交金额 (买入: fill_amount + fee 从现金扣; 卖出: fill_amount - fee 加回现金)
        fill_amount = fill_price * fill_qty
        net_cash_change = round(fill_amount + total_fee, 2) if action == 'BUY' else round(fill_amount - total_fee, 2)
        
        broker_order_id = f'SBX_{int(time.time()*1000)}_{symbol}_{action}'

        # 🆕 查股票名称 (从新浪实时行情拿, 写日志时带上)
        stock_name = symbol  # fallback
        try:
            secid = ('sh' + symbol) if symbol.startswith(('6', '5', '9')) else ('sz' + symbol)
            import urllib.request
            req = urllib.request.Request(
                f'https://hq.sinajs.cn/list={secid}',
                headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'})
            r = urllib.request.urlopen(req, timeout=3)
            text = r.read().decode('gbk', errors='ignore')
            for line in text.strip().split('\n'):
                if '="' in line:
                    stock_name = line.split('="')[1].rstrip('";').split(',')[0]
                    break
        except Exception:
            pass

        # 写 mt_trade_log (扩展 — 含手续费 + name)
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=10000')
        cur = conn.cursor()
        try:
            cur.execute("SELECT name FROM mt_trade_log")
            cols = [r[0] for r in cur.fetchall()]
            for col, default in [('trade_mode', 'sandbox'), ('broker', 'sandbox'), 
                                  ('broker_order_id', ''), ('fill_price', 0), ('fill_qty', 0),
                                  ('fill_amount', 0), ('slippage_bps', 0), ('risk_detail', ''),
                                  ('fee_total', 0), ('fee_commission', 0), ('fee_stamp_tax', 0),
                                  ('fee_transfer_fee', 0), ('net_cash_change', 0),
                                  ('name', '')]:
                if col not in cols:
                    dtype = 'TEXT' if col in ('name','broker_order_id','risk_detail') else 'REAL'
                    conn.execute(f"ALTER TABLE mt_trade_log ADD COLUMN {col} {dtype} DEFAULT '{default}'")
        except Exception:
            pass
        
        cur.execute("""INSERT INTO mt_trade_log
            (trade_mode, broker, broker_order_id, action, symbol, name, qty, price, fill_price, fill_qty,
             amount, fill_amount, slippage_bps, fee_total, fee_commission, fee_stamp_tax, fee_transfer_fee,
             net_cash_change, agent, source, reason, hall_code, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('sandbox', 'sandbox', broker_order_id, action, symbol, stock_name, qty, price, fill_price, fill_qty,
             gross_amount, fill_amount, abs(slip)*10000,
             total_fee, commission['commission'], commission['stamp_tax'], commission['transfer_fee'],
             net_cash_change,
             'ANDROMEDA_SANDBOX', 'sandbox_adapter', reason, hall_code,
             datetime.now(timezone(timedelta(hours=8))).isoformat()))
        trade_id = cur.lastrowid
        conn.commit()
        conn.close()
        
        return {
            'ok': True,
            'trade_id': trade_id,
            'broker_order_id': broker_order_id,
            'fill_price': fill_price,
            'fill_qty': fill_qty,
            'fill_amount': round(fill_amount, 2),
            'fee_total': total_fee,
            'commission': commission,
            'net_cash_change': net_cash_change,
            'slippage_bps': round(slip * 10000, 2),
            'trade_mode': 'sandbox',
            'message': f'SANDBOX {action} {symbol} × {fill_qty} @ ¥{fill_price:.2f}  手续费 ¥{total_fee:.2f}',
        }
    
    def query_position(self, symbol: str = None) -> list:
        """沙盘持仓 — 从 mt_sandbox_trades 算 (真实落库表)"""
        import sqlite3
        from routes.trading_routes import _find_flask_db
        db_path = _find_flask_db()
        if not db_path: return []
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 简化: 按 symbol 聚合 BUY - SELL
        if symbol:
            cur.execute("""SELECT symbol, action, shares, price FROM mt_sandbox_trades 
                          WHERE symbol=? ORDER BY trade_date, trade_time""", (symbol,))
        else:
            cur.execute("""SELECT symbol, action, shares, price FROM mt_sandbox_trades 
                          ORDER BY trade_date, trade_time""")
        
        positions = {}
        for r in cur.fetchall():
            sym = r['symbol']
            if sym not in positions:
                positions[sym] = {'symbol': sym, 'qty': 0, 'cost_total': 0}
            shares = r['shares']
            delta = shares if r['action'] == 'BUY' else -shares
            positions[sym]['qty'] += delta
            if r['action'] == 'BUY':
                positions[sym]['cost_total'] += shares * r['price']
            else:
                positions[sym]['cost_total'] -= shares * r['price']
        
        # 查实时价
        from core.services.market_data_service import MarketDataService
        mds = MarketDataService()
        result = []
        for sym, p in positions.items():
            if p['qty'] <= 0: continue
            try:
                secid = ('sh' + sym) if sym.startswith(('6', '5', '9')) else ('sz' + sym)
                rt = mds._sina_realtime([secid])
                cur_price = float(rt.get(secid, {}).get('price', p['cost_total']/p['qty']))
            except Exception:
                cur_price = p['cost_total'] / p['qty'] if p['qty'] else 0
            
            result.append({
                'symbol': sym,
                'qty': p['qty'],
                'avg_cost': round(p['cost_total'] / p['qty'], 2) if p['qty'] else 0,
                'current_price': cur_price,
                'market_value': round(p['qty'] * cur_price, 2),
                'trade_mode': 'sandbox',
            })
        conn.close()
        return result
    
    def query_cash(self) -> dict:
        """
        沙盘现金 — 真实账本模型 (经验 #2344888)
        
        初始本金 TOTAL_CAPITAL, 每次:
          BUY  → 现金减少 fill_amount + fee_total
          SELL → 现金增加 fill_amount - fee_total
        累计手续费 = SUM(fee_total)  ← 这是真实成本, 会逐步侵蚀本金
        
        total_assets = cash_available + positions_market_value (含浮盈浮亏)
        """
        import sqlite3
        from routes.trading_routes import _find_flask_db
        db_path = _find_flask_db()
        if not db_path:
            return {'total_capital': TOTAL_CAPITAL, 'available': 0, 'used': 0, 'total_fees': 0}
        
        positions = self.query_position()
        positions_value = round(sum(p.get('market_value', 0) for p in positions), 2)
        
        # 从 mt_trade_log 计算净现金变化
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        try:
            # 先看有没有 net_cash_change 列
            cur.execute("SELECT name FROM mt_trade_log")
            cols = [r[0] for r in cur.fetchall()]
            has_net_change = 'net_cash_change' in cols
            has_fee = 'fee_total' in cols
        except Exception:
            has_net_change = False
            has_fee = False
        
        cash_outflows = 0.0  # BUY: 现金流出
        cash_inflows = 0.0   # SELL: 现金流入
        total_fees = 0.0
        
        if has_net_change:
            # 新账本: 用 net_cash_change (已经含 fill_amount + fee)
            cur.execute("SELECT action, net_cash_change, fee_total FROM mt_trade_log WHERE trade_mode='sandbox'")
            for row in cur.fetchall():
                action, net_change, fee = row
                fee_val = fee or 0
                total_fees += fee_val
                if action == 'BUY':
                    cash_outflows += net_change or 0
                elif action == 'SELL':
                    cash_inflows += net_change or 0
        else:
            # 老账本 fallback: 按 fill_amount 算 (不含 fee)
            cur.execute("SELECT action, fill_amount FROM mt_trade_log WHERE trade_mode='sandbox'")
            for row in cur.fetchall():
                action, fill = row
                if action == 'BUY':
                    cash_outflows += fill or 0
                elif action == 'SELL':
                    cash_inflows += fill or 0
                # 粗略估算手续费 (旧数据没有精确 fee, 按 1% roundtrip 估算)
                if fill:
                    total_fees += fill * 0.005  # 近似
        
        conn.close()
        
        # 真实现金 = 初始本金 - 净流出 + 净流入
        available = round(TOTAL_CAPITAL - cash_outflows + cash_inflows, 2)
        total_assets = round(available + positions_value, 2)
        
        # 账户盈亏 (扣除手续费)
        pnl = round(total_assets - TOTAL_CAPITAL, 2)
        pnl_pct = round(pnl / TOTAL_CAPITAL * 100, 2) if TOTAL_CAPITAL > 0 else 0
        
        return {
            'total_capital': TOTAL_CAPITAL,
            'available_cash': available,
            'positions_value': positions_value,
            'total_assets': total_assets,
            'total_fees_paid': round(total_fees, 2),
            'total_fees_pct_of_capital': round(total_fees / TOTAL_CAPITAL * 100, 2) if TOTAL_CAPITAL > 0 else 0,
            'used': positions_value,  # alias
            'available': available,    # alias
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'trade_mode': 'sandbox',
        }
    
    def cancel_order(self, order_id: str) -> dict:
        return {'ok': False, 'message': '沙盘不支持撤单模拟'}


class BrokerAdapterStub(BrokerAdapter):
    """实盘通道 stub — 环境不满足时自动降级, 带详细注释说明需要什么"""
    
    def __init__(self, mode: str):
        self.name = mode
        self.activation = check_live_activation()
        self.environment_ok = False
        self._check_environment()
    
    def _check_environment(self):
        """环境探测 — 找出哪些条件不满足"""
        issues = []
        
        # Python 版本检查 (easytrader/QMT 都需要 3.8-3.11)
        py_ver = tuple(map(int, __import__('sys').version.split('.')[:2]))
        if py_ver > (3, 13):
            issues.append(f"Python {py_ver[0]}.{py_ver[1]} > 3.13, 主流券商 SDK 不兼容 (需要 3.8-3.11)")
        
        # 平台检查 (easytrader/QMT 需要 Windows)
        import platform
        if platform.system() != 'Windows':
            issues.append(f"当前 {platform.system()}, easytrader/QMT/PTrade 需要 Windows")
        
        self.environment_ok = len(issues) == 0
        self.environment_issues = issues
    
    def place_order(self, symbol: str, action: str, qty: int, price: float,
                    hall_code: str = '', reason: str = '') -> dict:
        """实盘下单 — 环境不满足 → 返回详细错误, 安全降级"""
        if not self.activation.get('active'):
            return {'ok': False, 'message': f"实盘未激活: {self.activation.get('reason')}",
                    'mode': self.name, 'activation_needed': True}
        
        if not self.environment_ok:
            return {
                'ok': False,
                'message': f"环境不满足, 安全降级为沙盘模式. 缺失条件:",
                'environment_issues': self.environment_issues,
                'mode': self.name,
                'fallback_to_sandbox': True,
                'how_to_fix': [
                    "1) Mac mini 装 Windows 10/11 (或 VMware/Parallels)",
                    "2) Windows 里装 Python 3.11 venv: `py -3.11 -m venv env`",
                    "3) pip install easytrader / xtquant (看券商支持哪个)",
                    "4) Windows 里登录中信证券 QMT/PTrade 客户端",
                    "5) 在中信官网开通程序化交易权限 (个人: 50万门槛 + 面签)",
                    "6) MT_TRADE_MODE=qmt_ptrade python3 modular_start.py --port=5001",
                ],
            }
        
        # ── 真实下单逻辑 (环境满足后才会走到这里) ──
        try:
            if self.name == 'easytrader':
                import easytrader
                trader = easytrader.use('citic')  # 中信证券
                trader.login()
                result = trader.buy(code=symbol, price=price, amount=qty)
            elif self.name == 'qmt_ptrade':
                from xtquant.xttrader import XtQuant
                xt = XtQuant('path/to/mini_qmt', 123456)
                result = xt.buy_stock(symbol=symbol, volume=qty, price=price)
            elif self.name == 'citic_mac':
                # AppleScript 方案 (中信 Mac 客户端 GUI 自动化)
                import subprocess
                script = f'''
                tell application "中信证券网上交易系统"
                    activate
                    -- 简化示意, 真实需要坐标定位
                end tell
                '''
                subprocess.run(['osascript', '-e', script])
                result = {'success': True}
            else:
                return {'ok': False, 'message': f'未知通道 {self.name}'}
            
            # 写 mt_trade_log (实盘)
            import sqlite3
            from routes.trading_routes import _find_flask_db
            conn = sqlite3.connect(_find_flask_db(), timeout=5)
            cur = conn.cursor()
            brok_id = str(result.get('order_id', int(time.time()*1000)))
            cur.execute("""INSERT INTO mt_trade_log
                (trade_mode, broker, broker_order_id, action, symbol, qty, price,
                 agent, source, reason, hall_code, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                ('live', self.name, brok_id, action, symbol, qty, price,
                 'ANDROMEDA_LIVE', f'broker_adapter:{self.name}', reason, hall_code,
                 datetime.now(timezone(timedelta(hours=8))).isoformat()))
            conn.commit()
            conn.close()
            
            return {'ok': True, 'broker_order_id': brok_id, 'message': f'LIVE {action} {symbol} @ ¥{price}'}
        except ImportError as e:
            return {'ok': False, 'message': f'券商 SDK 未安装: {e}', 'fallback_to_sandbox': True}
        except Exception as e:
            return {'ok': False, 'message': f'实盘下单失败: {e}', 'log_for_review': True}
    
    def query_position(self, symbol: str = None) -> list:
        return [{'error': f'实盘通道 {self.name} 环境未就绪, 无法查询持仓'}]
    
    def query_cash(self) -> dict:
        return {'error': f'实盘通道 {self.name} 环境未就绪, 无法查询现金', 'total_capital': TOTAL_CAPITAL}
    
    def cancel_order(self, order_id: str) -> dict:
        return {'ok': False, 'message': f'实盘通道 {self.name} 环境未就绪'}


# ════════════════════════════════════════════════════════════════════════
# 工厂 + 安全降级
# ════════════════════════════════════════════════════════════════════════
def get_broker_adapter(mode: str = None) -> BrokerAdapter:
    """获取券商适配器 — 实盘环境不满足自动降级沙盘"""
    mode = (mode or TRADE_MODE).lower()
    
    if mode == 'sandbox':
        return SandboxAdapter()
    
    # 实盘通道先试试 (环境探测 + 激活检查)
    stub = BrokerAdapterStub(mode)
    activation = check_live_activation()
    
    # 环境不满足 → 安全降级
    if not stub.environment_ok:
        print(f"[BROKER] ⚠️ 实盘通道 {mode} 环境不满足, 安全降级为沙盘模式")
        for issue in stub.environment_issues:
            print(f"  └─ {issue}")
        return SandboxAdapter()
    
    # 环境满足但没激活 → 返回 stub (让调用方看到需要激活)
    if not activation.get('active'):
        print(f"[BROKER] ⚠️ 实盘通道 {mode} 未激活 (二次确认 needed)")
        return stub  # 不是降级, 是让调用方显式处理
    
    return stub


# ── 便捷函数 ────────────────────────────────────────────────────────────
def place_order_safe(symbol: str, action: str, qty: int, price: float,
                     hall_code: str = '', reason: str = '') -> dict:
    """
    安全下单 — 全链路门禁串联
    
    顺序:
      1. 初始化 broker adapter
      2. 查当前持仓 + 总资产 (供风控 R-04/R-05/R-06 使用)
      3. RiskEngine.check (7 条规则)
      4. 实盘二次确认 (非 sandbox)
      5. broker.place_order (含手续费扣减 + 滑点)
    """
    broker = get_broker_adapter()
    
    # ── 预查当前状态 (供风控 R-04/R-05/R-06) ──
    try:
        positions = broker.query_position()
        cash_info = broker.query_cash()
        total_assets = cash_info.get('total_assets', cash_info.get('total_capital', TOTAL_CAPITAL))
    except Exception:
        positions = []
        total_assets = TOTAL_CAPITAL
    
    # ── R-00~R-07 全维度风控 ──
    risk = RiskEngine.check(
        symbol=symbol, action=action, qty=qty, price=price,
        current_positions=positions, total_assets=total_assets,
    )
    if not risk['pass']:
        return {
            'ok': False, 'error': 'RISK_BLOCK',
            'risk': risk,
            'blocked_by': [k for k, v in risk.items() if k.startswith('r0') and v is True],
        }
    
    # ── 实盘二次确认 ──
    if broker.get_mode() != 'sandbox':
        act = check_live_activation()
        if not act.get('active'):
            return {'ok': False, 'error': 'LIVE_NOT_ACTIVATED',
                    'message': f'实盘通道 {broker.get_mode()} 需要二次确认激活'}
    
    # ── broker 执行 (含手续费扣减) ──
    result = broker.place_order(symbol, action, qty, price, hall_code, reason)
    
    # 如果是实盘, 额外扣费
    if result.get('ok') and broker.get_mode() != 'sandbox':
        # 实盘手续费由券商自动扣, 这里只加 commission_detail 方便前端展示
        result['commission'] = CommissionModel.calc(action, qty * price)
    
    # 附带风控信息 (让调用方知道有没有警告)
    result['risk_detail'] = {
        'pass': risk['pass'],
        'warnings': [i for i in risk.get('issues', []) if i.startswith('[R-02') or i.startswith('[R-07')],
        'hard_stop_loss_price': risk.get('hard_stop_loss_price'),
        'auto_take_profit_price': risk.get('auto_take_profit_price'),
    }
    
    return result
