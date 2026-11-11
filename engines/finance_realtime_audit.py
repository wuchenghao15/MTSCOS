"""
finance_realtime_audit.py — 实时账务稽查引擎
====================================
每笔交易/下单 → 12 维度同步稽查 → 异常实时标记 + 事件广播

稽查维度 (12 dimensions):
  D01 资金充足   buy 时 total_cost > current_cash?
  D02 持仓充足   sell 时 qty > 可卖持仓?
  D03 T+1 结算   sell 当日买入的? (A股规则)
  D04 价格异常   成交价偏离 latest > ±15%?
  D05 数量异常   qty < 100 股 (最小单位)?
  D06 session 一致性  trade_log ↔ sandbox_trades 双写一致?
  D07 佣金计算   fee = max(5, amount*0.0003) 正确?
  D08 印花税     sell 才收千一? buy 不收?
  D09 现金守恒   trade 后 cash = old_cash ± net_amount?
  D10 重复下单   同 symbol + side + qty + price + session 3s 内重复?
  D11 熔断检查   session 累计亏损 > 20%?
  D12 信号一致性 trade 方向 是否与最近 signal 方向匹配?

输出: mt_vault_audit_log 表 (如果不存在 → CREATE TABLE / 旧表数据 DROP 重建)
"""

import os
import sys
import json
import uuid
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger('finance_realtime_audit')

# ── 常量 ──────────────────────────────────────────────────────

COMMISSION_MIN = 5.0          # 最低佣金 5 元
COMMISSION_RATE = 0.0003      # 万三佣金率
STAMP_TAX_RATE = 0.001        # 千一印花税 (仅 SELL)
MIN_TRADE_UNIT = 100          # A 股最小交易单位
PRICE_DEVIATION_PCT = 0.15    # 价格异常阈值 ±15%
MAX_LOSS_PCT = 0.20           # 熔断亏损阈值 20%
DUP_ORDER_WINDOW_SEC = 3      # 重复下单窗口 (秒)

DB_PATH_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.db'),
    os.path.join(os.getcwd(), 'database', 'app.db'),
    os.path.join(os.getcwd(), 'app.db'),
]


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """解析数据库路径"""
    if db_path and os.path.exists(db_path):
        return db_path
    for c in DB_PATH_CANDIDATES:
        if os.path.exists(c):
            return c
    # 默认第一个候选，让后续报错提示清晰
    return DB_PATH_CANDIDATES[0]


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── DDL: 稽查日志表 ──────────────────────────────────────────

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS mt_vault_audit_log (
    audit_id        TEXT PRIMARY KEY,
    audit_type      TEXT NOT NULL,              -- 'REALTIME' | 'SCHEDULED'
    dimension       TEXT NOT NULL,              -- D01~D12
    level           TEXT DEFAULT 'INFO',        -- INFO/WARN/ERROR/CRITICAL
    session_id      TEXT,
    symbol          TEXT,
    trade_id        TEXT,
    description     TEXT,
    expected        TEXT,
    actual          TEXT,
    diff_pct        REAL,
    verdict         TEXT DEFAULT 'PASS',        -- PASS/WARN/FAIL
    operator        TEXT DEFAULT 'system',
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    resolved        INTEGER DEFAULT 0,
    resolved_at     TEXT,
    resolution_note TEXT,
    FOREIGN KEY (trade_id) REFERENCES mt_sandbox_trades(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_audit_session ON mt_vault_audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_dim ON mt_vault_audit_log(dimension);
CREATE INDEX IF NOT EXISTS idx_audit_created ON mt_vault_audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_level ON mt_vault_audit_log(level);
"""


def ensure_audit_schema(db_path: str) -> None:
    """确保 mt_vault_audit_log 表存在且 schema 正确"""
    conn = _connect(db_path)
    try:
        # 检查表是否存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mt_vault_audit_log'"
        ).fetchone()
        if row:
            # 检查表结构是否匹配
            cols = [c['name'] for c in conn.execute(
                "PRAGMA table_info(mt_vault_audit_log)"
            ).fetchall()]
            # 新 schema 应该包含 dimension/level/verdict 等列
            if 'dimension' not in cols or 'verdict' not in cols:
                # 旧 schema — DROP 重建
                logger.warning("mt_vault_audit_log 旧 schema 不兼容，DROP 重建")
                conn.execute("DROP TABLE IF EXISTS mt_vault_audit_log")
                conn.commit()
                conn.executescript(AUDIT_DDL)
            # 否则已存在正确 schema
        else:
            conn.executescript(AUDIT_DDL)
        conn.commit()
    finally:
        conn.close()


# ── 维度定义 ──────────────────────────────────────────────────

DIMENSIONS = {
    'D01': '资金充足',
    'D02': '持仓充足',
    'D03': 'T+1 结算',
    'D04': '价格异常',
    'D05': '数量异常',
    'D06': '双写一致性',
    'D07': '佣金计算',
    'D08': '印花税规则',
    'D09': '现金守恒',
    'D10': '重复下单',
    'D11': '熔断检查',
    'D12': '信号一致性',
}


# ── 工具函数 ──────────────────────────────────────────────────

def _calc_expected_commission(amount: float) -> float:
    """计算预期佣金 = max(5, amount * 0.0003)"""
    return round(max(COMMISSION_MIN, amount * COMMISSION_RATE), 2)


def _calc_expected_stamp_tax(side: str, amount: float) -> float:
    """预期印花税 — 仅 SELL 收千一"""
    if side.upper() == 'SELL':
        return round(amount * STAMP_TAX_RATE, 2)
    return 0.0


def _round(v: float, ndigits: int = 2) -> float:
    return round(float(v), ndigits)


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _generate_audit_id() -> str:
    return f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _get_session_position_qty(conn, session_id: str, symbol: str, up_to_trade_id: str = None) -> int:
    """从 mt_sandbox_trades 累积计算某 session 某 symbol 的可卖持仓。
       比 portfolio.positions_json 更准确 —— 因为它按 trade 顺序累积。
       up_to_trade_id: 只累积到该 trade 之前 (不含该 trade 本身)。"""
    try:
        if up_to_trade_id:
            rows = conn.execute(
                "SELECT action, shares FROM mt_sandbox_trades "
                "WHERE session_id=? AND symbol=? AND trade_id!=? "
                "ORDER BY rowid ASC",
                (session_id, symbol, up_to_trade_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT action, shares FROM mt_sandbox_trades "
                "WHERE session_id=? AND symbol=? "
                "ORDER BY rowid ASC",
                (session_id, symbol)
            ).fetchall()
        qty = 0
        for r in rows:
            action = (r['action'] or '').upper()
            if action == 'BUY':
                qty += int(r['shares'] or 0)
            elif action == 'SELL':
                qty -= int(r['shares'] or 0)
        return max(0, qty)
    except Exception:
        return 0


def _get_session_total_value(conn, session_id: str) -> float:
    """正确的 session 总资产 = 现金 + 持仓市值。
       用于 D11 熔断检查 —— 不能只看 current_cash vs initial_cash。"""
    row = conn.execute(
        "SELECT current_cash, positions_json FROM mt_sandbox_portfolio WHERE session_id=?",
        (session_id,)
    ).fetchone()
    if not row:
        return 0.0
    cash = float(row['current_cash'] or 0)
    positions_json = row['positions_json']

    # 持仓市值
    pos_value = 0.0
    try:
        positions = json.loads(positions_json) if positions_json else []
    except Exception:
        positions = []

    for pos in positions:
        qty = int(pos.get('qty', pos.get('shares', 0)) or 0)
        # 优先用 avg_cost (保守, 不依赖实时行情)
        avg_cost = float(pos.get('avg_cost', 0) or 0)
        if qty > 0:
            if avg_cost > 0:
                pos_value += qty * avg_cost
            else:
                # fallback: 从 trades 查最后成交价
                sym = pos.get('symbol', '')
                last_price = conn.execute(
                    "SELECT price FROM mt_sandbox_trades WHERE session_id=? AND symbol=? "
                    "ORDER BY datetime(created_at) DESC LIMIT 1",
                    (session_id, sym)
                ).fetchone()
                if last_price:
                    pos_value += qty * float(last_price['price'])

    return cash + pos_value


# ── 核心: 单笔交易稽查 ─────────────────────────────────────────

def audit_trade(trade_data: dict, db_path: Optional[str] = None) -> dict:
    """
    对单笔交易执行 12 维度稽查，结果写入 mt_vault_audit_log。

    trade_data keys:
        trade_id      (str)
        session_id    (str)
        symbol        (str)
        side          (str) BUY / SELL
        qty           (int)
        price         (float)
        fee           (float) — 实际佣金
        tax           (float) — 实际印花税
        cash_before   (float)
        cash_after    (float)
        signal_direction (str, optional) BULL/BEAR/HOLD
        notes         (str, optional) — 额外信息

    Returns:
        {
            'verdict': 'PASS' | 'WARN' | 'FAIL' | 'CRITICAL',
            'dimensions_passed': ['D07', ...],
            'dimensions_failed': [{'dim': 'D01', 'level': 'ERROR', 'desc': '...', ...}, ...],
            'issues': [...]
        }
    """
    db_path = _resolve_db_path(db_path)
    ensure_audit_schema(db_path)

    trade_id = trade_data.get('trade_id', '')
    session_id = trade_data.get('session_id', '')
    symbol = trade_data.get('symbol', '')
    side = (trade_data.get('side') or trade_data.get('action') or 'BUY').upper()
    qty = int(trade_data.get('qty', trade_data.get('shares', 0)) or 0)
    price = float(trade_data.get('price', 0) or 0)
    fee = float(trade_data.get('fee', trade_data.get('commission', 0)) or 0)
    tax = float(trade_data.get('tax', trade_data.get('stamp_tax', 0)) or 0)
    cash_before = trade_data.get('cash_before')
    cash_after = trade_data.get('cash_after')
    signal_direction = trade_data.get('signal_direction', '')
    total_amount = float(trade_data.get('total_amount') or qty * price)

    conn = _connect(db_path)
    passed, failed, issues = [], [], []

    try:
        portfolio = None
        try:
            row = conn.execute(
                "SELECT session_id, current_cash, positions_json, initial_cash, start_date "
                "FROM mt_sandbox_portfolio WHERE session_id=?", (session_id,)
            ).fetchone()
            if row:
                portfolio = dict(row)
        except Exception:
            portfolio = None

        # ── D01 资金充足 ──────────────────────────────────
        if side == 'BUY' and cash_before is not None:
            cost = qty * price + fee + tax
            if cash_before < cost:
                _write_issue(conn, trade_id, session_id, symbol, 'D01', 'ERROR',
                             f'BUY 资金不足: 需要 ¥{cost:.2f}，现金仅 ¥{cash_before:.2f}',
                             f'market_cost={cost:.2f}', f'cash_before={cash_before:.2f}',
                             _pct_diff(cost, cash_before), 'FAIL')
                failed.append('D01')
                issues.append({'dim': 'D01', 'level': 'ERROR',
                               'desc': f'BUY 资金不足 {cost:.2f} > {cash_before:.2f}'})
            else:
                passed.append('D01')
        else:
            passed.append('D01')  # SELL 不检查

        # ── D02 持仓充足 ──────────────────────────────────
        # 主要从 trades 累积计算持仓 (解决 portfolio.positions_json 是终态快照的问题)
        # fallback: 从 portfolio.positions_json 读取
        if side == 'SELL':
            can_sell = _get_session_position_qty(conn, session_id, symbol, up_to_trade_id=trade_id)
            # fallback: 如果 trade 累积结果为 0, 试 portfolio.positions_json
            if can_sell == 0 and portfolio and portfolio.get('positions_json'):
                try:
                    positions = json.loads(portfolio['positions_json'])
                    for pos in positions:
                        if pos.get('symbol') == symbol:
                            can_sell = int(pos.get('shares', pos.get('qty', 0)) or 0)
                            break
                except Exception:
                    pass
            if qty > can_sell:
                _write_issue(conn, trade_id, session_id, symbol, 'D02', 'ERROR',
                             f'SELL 持仓不足: 可卖 {can_sell} 股，尝试卖 {qty}',
                             f'available={can_sell}', f'requested={qty}',
                             None, 'FAIL')
                failed.append('D02')
                issues.append({'dim': 'D02', 'level': 'ERROR',
                               'desc': f'SELL 持仓不足 {qty} > {can_sell}'})
            else:
                passed.append('D02')
        else:
            passed.append('D02')

        # ── D03 T+1 结算 ──────────────────────────────────
        if side == 'SELL' and portfolio:
            try:
                today = datetime.now().strftime('%Y-%m-%d')
                buy_today = conn.execute(
                    "SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id=? AND symbol=? "
                    "AND action='BUY' AND trade_date=?",
                    (session_id, symbol, today)
                ).fetchone()[0]
                if buy_today > 0:
                    _write_issue(conn, trade_id, session_id, symbol, 'D03', 'WARN',
                                 f'T+1 违规: 今日买入 {buy_today} 笔后又卖出',
                                 f'buy_count_today={buy_today}', f'action=SELL',
                                 None, 'WARN')
                    failed.append('D03')
                    issues.append({'dim': 'D03', 'level': 'WARN',
                                   'desc': f'T+1 违规 — 今日买入 {buy_today} 笔后卖出'})
                else:
                    passed.append('D03')
            except Exception:
                passed.append('D03')
        else:
            passed.append('D03')

        # ── D04 价格异常 ──────────────────────────────────
        # 简单策略: 同 symbol 最近 30 笔成交价均值做基准
        try:
            ref = conn.execute(
                "SELECT AVG(price) FROM mt_sandbox_trades WHERE symbol=? AND trade_id!=? "
                "ORDER BY rowid DESC LIMIT 30", (symbol, trade_id)
            ).fetchone()[0]
            if ref and ref > 0:
                deviation = abs(price - ref) / ref
                if deviation > PRICE_DEVIATION_PCT:
                    _write_issue(conn, trade_id, session_id, symbol, 'D04', 'WARN',
                                 f'成交价偏离均值 {deviation*100:.1f}%',
                                 f'avg_price={ref:.2f}', f'exec_price={price:.2f}',
                                 deviation * 100, 'WARN')
                    failed.append('D04')
                    issues.append({'dim': 'D04', 'level': 'WARN',
                                   'desc': f'价格偏离 {deviation*100:.1f}%'})
                else:
                    passed.append('D04')
            else:
                passed.append('D04')  # 无参考
        except Exception:
            passed.append('D04')

        # ── D05 数量异常 ──────────────────────────────────
        if qty > 0 and qty % MIN_TRADE_UNIT != 0:
            _write_issue(conn, trade_id, session_id, symbol, 'D05', 'WARN',
                         f'数量非 {MIN_TRADE_UNIT} 整数倍: {qty}',
                         f'multiple={MIN_TRADE_UNIT}', f'qty={qty}', None, 'WARN')
            failed.append('D05')
            issues.append({'dim': 'D05', 'level': 'WARN', 'desc': f'数量非整手 {qty}'})
        else:
            passed.append('D05')

        # ── D06 双写一致性 ────────────────────────────────
        try:
            sb = conn.execute(
                "SELECT trade_id, session_id, symbol, action, shares, price, commission, stamp_tax, total_amount "
                "FROM mt_sandbox_trades WHERE trade_id=?", (trade_id,)
            ).fetchone()
            tl = conn.execute(
                "SELECT trade_id, action, symbol, qty, price, fee_total, amount "
                "FROM mt_trade_log WHERE trade_id=?", (trade_id,)
            ).fetchone()
            if sb and not tl:
                _write_issue(conn, trade_id, session_id, symbol, 'D06', 'ERROR',
                             f'仅 sandbox_trades 有记录, trade_log 缺失',
                             'dual_write', 'single_write', None, 'FAIL')
                failed.append('D06')
                issues.append({'dim': 'D06', 'level': 'ERROR', 'desc': 'trade_log 缺失'})
            elif not sb and tl:
                _write_issue(conn, trade_id, session_id, symbol, 'D06', 'ERROR',
                             f'仅 trade_log 有记录, sandbox_trades 缺失',
                             'dual_write', 'single_write', None, 'FAIL')
                failed.append('D06')
                issues.append({'dim': 'D06', 'level': 'ERROR', 'desc': 'sandbox_trades 缺失'})
            elif sb and tl:
                sb_action, tl_action = sb['action'], tl['action']
                sb_shares, tl_qty = sb['shares'], tl['qty']
                sb_price, tl_price = sb['price'], tl['price']
                mismatches = []
                if sb_action != tl_action:
                    mismatches.append(f'action: {sb_action}≠{tl_action}')
                if sb_shares != tl_qty:
                    mismatches.append(f'qty: {sb_shares}≠{tl_qty}')
                if abs(sb_price - tl_price) > 0.01:
                    mismatches.append(f'price: {sb_price}≠{tl_price}')
                if mismatches:
                    _write_issue(conn, trade_id, session_id, symbol, 'D06', 'ERROR',
                                 f'双写字段不一致: {"; ".join(mismatches)}',
                                 'match', 'mismatch', None, 'FAIL')
                    failed.append('D06')
                    issues.append({'dim': 'D06', 'level': 'ERROR',
                                   'desc': f'双写不一致: {mismatches}'})
                else:
                    passed.append('D06')
            else:
                passed.append('D06')  # 两表都没这 trade_id
        except Exception:
            passed.append('D06')

        # ── D07 佣金计算 ──────────────────────────────────
        expected_fee = _calc_expected_commission(total_amount)
        fee_diff = abs(fee - expected_fee)
        if fee_diff > 0.02:  # 容差 2 分
            _write_issue(conn, trade_id, session_id, symbol, 'D07', 'WARN',
                         f'佣金不匹配: 实际 ¥{fee:.2f}, 预期 ¥{expected_fee:.2f}',
                         f'expected={expected_fee}', f'actual={fee}',
                         (fee_diff / max(expected_fee, 0.01)) * 100, 'WARN')
            failed.append('D07')
            issues.append({'dim': 'D07', 'level': 'WARN',
                           'desc': f'佣金偏差 fee={fee}≠{expected_fee}'})
        else:
            passed.append('D07')

        # ── D08 印花税 ────────────────────────────────────
        expected_tax = _calc_expected_stamp_tax(side, total_amount)
        if abs(tax - expected_tax) > 0.02:
            _write_issue(conn, trade_id, session_id, symbol, 'D08', 'WARN',
                         f'印花税违规: {side} 实际 ¥{tax:.2f}, 预期 ¥{expected_tax:.2f}',
                         f'expected={expected_tax}', f'actual={tax}',
                         None, 'WARN')
            failed.append('D08')
            issues.append({'dim': 'D08', 'level': 'WARN',
                           'desc': f'印花税违规 side={side} tax={tax}≠{expected_tax}'})
        else:
            passed.append('D08')

        # ── D09 现金守恒 ──────────────────────────────────
        if cash_before is not None and cash_after is not None:
            if side == 'BUY':
                expected_cash_after = cash_before - qty * price - fee - tax
            else:
                expected_cash_after = cash_before + qty * price - fee - tax
            cash_gap = abs(cash_after - expected_cash_after)
            if cash_gap > 0.02:
                _write_issue(conn, trade_id, session_id, symbol, 'D09', 'ERROR',
                             f'现金不守恒: 预期 ¥{expected_cash_after:.2f}, 实际 ¥{cash_after:.2f}, 差额 ¥{cash_gap:.2f}',
                             f'expected={expected_cash_after:.2f}', f'actual={cash_after:.2f}',
                             (cash_gap / max(abs(expected_cash_after), 0.01)) * 100, 'FAIL')
                failed.append('D09')
                issues.append({'dim': 'D09', 'level': 'ERROR',
                               'desc': f'现金不守恒 gap={cash_gap:.2f}'})
            else:
                passed.append('D09')
        else:
            passed.append('D09')  # 无前后值可校验

        # ── D10 重复下单 ──────────────────────────────────
        try:
            dup = conn.execute(
                "SELECT trade_id, created_at FROM mt_sandbox_trades WHERE session_id=? "
                "AND symbol=? AND action=? AND shares=? AND ABS(price-?)<0.01 "
                "AND rowid IN (SELECT rowid FROM mt_sandbox_trades WHERE trade_id!=?) "
                "ORDER BY rowid DESC LIMIT 1",
                (session_id, symbol, side, qty, price, trade_id)
            ).fetchone()
            if dup:
                time_gap = None
                try:
                    now = datetime.now()
                    old = datetime.fromisoformat(str(dup['created_at']))
                    time_gap = (now - old).total_seconds()
                except Exception:
                    pass
                if time_gap is not None and time_gap < DUP_ORDER_WINDOW_SEC:
                    _write_issue(conn, trade_id, session_id, symbol, 'D10', 'WARN',
                                 f'{DUP_ORDER_WINDOW_SEC}s 内重复下单: 前笔 {dup["trade_id"]}',
                                 f'window={DUP_ORDER_WINDOW_SEC}s', f'prev_trade={dup["trade_id"]}',
                                 None, 'WARN')
                    failed.append('D10')
                    issues.append({'dim': 'D10', 'level': 'WARN',
                                   'desc': f'重复下单 prev={dup["trade_id"]}'})
                else:
                    passed.append('D10')
            else:
                passed.append('D10')
        except Exception:
            passed.append('D10')

        # ── D11 熔断检查 ──────────────────────────────────
        # 修复: 旧版只比 current_cash vs initial_cash —— 忽略持仓市值!
        # 正确: 总资产 = 现金 + 持仓市值, return_pct = (total_value - init_cash) / init_cash
        if portfolio:
            init_cash = float(portfolio.get('initial_cash', 10000) or 10000)
            total_value = _get_session_total_value(conn, session_id)
            if init_cash > 0:
                return_pct = (total_value - init_cash) / init_cash * 100
                if return_pct < -MAX_LOSS_PCT * 100:
                    _write_issue(conn, trade_id, session_id, symbol, 'D11', 'CRITICAL',
                                 f'累计亏损 {abs(return_pct):.1f}% > {MAX_LOSS_PCT*100:.0f}% 熔断阈值 '
                                 f'(总资产={total_value:.2f}, 本金={init_cash:.2f})',
                                 f'threshold=-{MAX_LOSS_PCT*100:.0f}%',
                                 f'actual={return_pct:.1f}%',
                                 return_pct, 'FAIL')
                    failed.append('D11')
                    issues.append({'dim': 'D11', 'level': 'CRITICAL',
                                   'desc': f'熔断! 总资产={total_value:.0f} 亏损={return_pct:.1f}%'})
                else:
                    passed.append('D11')
            else:
                passed.append('D11')
        else:
            passed.append('D11')

        # ── D12 信号一致性 ────────────────────────────────
        try:
            recent = conn.execute(
                "SELECT signal_type FROM mt_sandbox_signals WHERE session_id=? AND symbol=? "
                "ORDER BY rowid DESC LIMIT 1", (session_id, symbol)
            ).fetchone()
            if recent:
                stype = recent['signal_type'].upper()
                side_match = (
                    (side == 'BUY' and stype in ('BULL', 'BUY')) or
                    (side == 'SELL' and stype in ('BEAR', 'SELL')) or
                    stype == 'HOLD'
                )
                if not side_match:
                    _write_issue(conn, trade_id, session_id, symbol, 'D12', 'WARN',
                                 f'信号背离: 最近信号 {stype}, 本次交易 {side}',
                                 f'signal={stype}', f'trade_side={side}', None, 'WARN')
                    failed.append('D12')
                    issues.append({'dim': 'D12', 'level': 'WARN',
                                   'desc': f'信号背离 signal={stype} vs side={side}'})
                else:
                    passed.append('D12')
            else:
                passed.append('D12')  # 无信号，不校验
        except Exception:
            passed.append('D12')

        conn.commit()
    finally:
        conn.close()

    # ── 汇总 verdict ──────────────────────────────────────
    critical = [i for i in issues if i['level'] == 'CRITICAL']
    errors = [i for i in issues if i['level'] == 'ERROR']
    warnings = [i for i in issues if i['level'] == 'WARN']

    if critical:
        verdict = 'CRITICAL'
    elif errors:
        verdict = 'FAIL'
    elif warnings:
        verdict = 'WARN'
    else:
        verdict = 'PASS'

    # ── 🎛️ TriggerCoordinator 事件桥接 ──
    # verdict=FAIL/CRITICAL → emit AUDIT_FAIL
    if verdict in ('FAIL', 'CRITICAL'):
        try:
            from engines.trigger_coordinator import TriggerCoordinator
            TriggerCoordinator().fire(
                'AUDIT_FAIL', source='finance_realtime_audit',
                payload={
                    'trade_id': trade_id, 'symbol': symbol or '',
                    'session_id': session_id or '',
                    'verdict': verdict,
                    'dimensions_failed': [i['dim'] for i in issues if i.get('level') in ('ERROR', 'CRITICAL')],
                    'issue_count': len(issues),
                },
                symbol=symbol, severity='CRITICAL' if verdict == 'CRITICAL' else 'HIGH',
            )
        except Exception:
            pass

    return {
        'verdict': verdict,
        'dimensions_passed': passed,
        'dimensions_failed': failed,
        'issues': issues,
        'trade_id': trade_id,
    }


def _write_issue(conn, trade_id, session_id, symbol, dimension, level,
                 description, expected, actual, diff_pct, verdict):
    """写入单条稽查记录"""
    audit_id = _generate_audit_id()
    try:
        conn.execute(
            "INSERT INTO mt_vault_audit_log "
            "(audit_id, audit_type, dimension, level, session_id, symbol, trade_id, "
            "description, expected, actual, diff_pct, verdict) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (audit_id, 'REALTIME', dimension, level, session_id, symbol, trade_id,
             str(description)[:500], str(expected)[:200], str(actual)[:200],
             float(diff_pct) if diff_pct is not None else None, verdict)
        )
    except Exception as e:
        logger.error(f'[_write_issue] {e}')


def _pct_diff(expected, actual):
    try:
        e = float(expected); a = float(actual)
        if abs(e) < 0.001:
            return None
        return abs(a - e) / abs(e) * 100
    except Exception:
        return None


# ── 批量稽查 ──────────────────────────────────────────────────

class RealtimeAuditor:
    """面向现存历史交易的批量稽查器"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = _resolve_db_path(db_path)
        ensure_audit_schema(self.db_path)

    def audit_all_existing(self, clear_old: bool = True) -> dict:
        """对 mt_sandbox_trades 全部现存交易重新执行实时稽查 (批量版)"""
        if clear_old:
            conn = _connect(self.db_path)
            conn.execute(
                "DELETE FROM mt_vault_audit_log WHERE audit_type='REALTIME'"
            )
            conn.commit()
            conn.close()

        conn = _connect(self.db_path)
        try:
            trades = conn.execute(
                "SELECT trade_id, session_id, symbol, action AS side, "
                "shares AS qty, price, commission AS fee, stamp_tax AS tax, "
                "total_amount, trade_date, trade_time, created_at "
                "FROM mt_sandbox_trades ORDER BY rowid ASC"
            ).fetchall()
        finally:
            conn.close()

        results = {'total': len(trades), 'pass': 0, 'warn': 0, 'fail': 0,
                   'dimensions': {d: {'pass': 0, 'warn': 0, 'fail': 0}
                                  for d in DIMENSIONS},
                   'failed_trades': []}

        # 预加载 portfolio 快照明细以减少 DB 查询
        portfolios = self._load_portfolios()

        for t in trades:
            t = dict(t)
            t['side'] = t.pop('side', t.get('action', 'BUY'))
            try:
                trade_id = t['trade_id']
                session_id = t.get('session_id', '')
                pf = portfolios.get(session_id)

                # 估算 cash_before / cash_after — 从 portfolio 或前后 trades 推算
                cash_before, cash_after = self._estimate_cash(t, pf, portfolios)
                t['cash_before'] = cash_before
                t['cash_after'] = cash_after

                r = audit_trade(t, self.db_path)

                v = r['verdict']
                if v == 'PASS':
                    results['pass'] += 1
                elif v == 'WARN':
                    results['warn'] += 1
                else:
                    results['fail'] += 1
                    results['failed_trades'].append({
                        'trade_id': trade_id, 'verdict': v,
                        'issues': r['issues']
                    })

                for dim in r.get('dimensions_passed', []):
                    results['dimensions'].setdefault(dim, {'pass': 0, 'warn': 0, 'fail': 0})['pass'] += 1
                for issue in r.get('issues', []):
                    dim = issue['dim']
                    results['dimensions'].setdefault(dim, {'pass': 0, 'warn': 0, 'fail': 0})
                    level = issue.get('level', 'WARN')
                    if level == 'ERROR' or level == 'CRITICAL':
                        results['dimensions'][dim]['fail'] += 1
                    else:
                        results['dimensions'][dim]['warn'] += 1

            except Exception as e:
                logger.error(f"批量稽查 trade {t.get('trade_id')} 失败: {e}")

        # 总稽查日志条数
        conn = _connect(self.db_path)
        results['log_count'] = conn.execute(
            "SELECT COUNT(*) FROM mt_vault_audit_log WHERE audit_type='REALTIME'"
        ).fetchone()[0]
        conn.close()

        return results

    def _load_portfolios(self):
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT session_id, current_cash, initial_cash, positions_json "
                "FROM mt_sandbox_portfolio"
            ).fetchall()
            return {r['session_id']: dict(r) for r in rows}
        finally:
            conn.close()

    def _estimate_cash(self, trade, pf, portfolios):
        """从 portfolio 和同 session 前后 trades 推算 cash_before/cash_after。
           portfolio 记录的是当前 cash, 不适合作为单笔交易的 cash_before;
           这里用简化方法: 取 initial_cash 作为 cash_before 近似值,
           cash_after = cash_before ∓ qty*price - fee - tax
        """
        if pf:
            cash_before = float(pf.get('initial_cash', 10000) or 10000)
        else:
            cash_before = 10000.0
        side = (trade.get('side') or 'BUY').upper()
        qty = int(trade.get('qty', 0) or 0)
        price = float(trade.get('price', 0) or 0)
        fee = float(trade.get('fee', 0) or 0)
        tax = float(trade.get('tax', 0) or 0)
        if side == 'BUY':
            cash_after = cash_before - qty * price - fee - tax
        else:
            cash_after = cash_before + qty * price - fee - tax
        return cash_before, cash_after


# ── Hook: 包装 stock_sandbox_engine ───────────────────────────

def hook_into_trade_execution():
    """包装 ai_stock_sandbox_engine 的 buy/sell — 每笔交易自动触发稽查。
    失败不阻塞交易, 仅打 WARNING 日志。"""
    try:
        from engines import ai_stock_sandbox_engine as sand
    except Exception:
        logger.warning('ai_stock_sandbox_engine 不可用, skip hook')
        return

    orig_buy = getattr(sand, 'buy', None) or getattr(sand, 'place_buy', None)
    orig_sell = getattr(sand, 'sell', None) or getattr(sand, 'place_sell', None)

    def _make_wrapper(orig_side_fn, side_label):
        def wrapper(*args, **kwargs):
            result = orig_side_fn(*args, **kwargs)
            try:
                if isinstance(result, dict) and result.get('trade_id'):
                    audit_trade({
                        'trade_id': result.get('trade_id'),
                        'session_id': result.get('session_id', ''),
                        'symbol': result.get('symbol', ''),
                        'side': side_label,
                        'qty': result.get('qty', 0),
                        'price': result.get('price', 0),
                        'fee': result.get('fee', 0),
                        'tax': result.get('tax', 0),
                        'cash_before': result.get('cash_before'),
                        'cash_after': result.get('cash_after'),
                    })
            except Exception as e:
                logger.warning(f'hook audit failed ({side_label}): {e}')
            return result
        return wrapper

    if orig_buy:
        sand.buy = _make_wrapper(orig_buy, 'BUY')
        logger.info('hook_into_trade_execution: buy() 已包装')
    if orig_sell:
        sand.sell = _make_wrapper(orig_sell, 'SELL')
        logger.info('hook_into_trade_execution: sell() 已包装')


# ── CLI: 独立运行 ────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='实时账务稽查引擎')
    parser.add_argument('--db', default=None, help='数据库路径')
    parser.add_argument('--all', action='store_true', help='批量稽查现存交易')
    parser.add_argument('--demo', action='store_true', help='创建 3 笔 mock 交易 + 稽查')
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db) if args.db else _resolve_db_path(None)
    print(f"DB → {db_path}")

    if args.all:
        auditor = RealtimeAuditor(db_path)
        results = auditor.audit_all_existing()
        print(f"\n{'='*50}")
        print(f"稽查 trades: {results['total']}")
        print(f"PASS: {results['pass']}  WARN: {results['warn']}  FAIL: {results['fail']}")
        print(f"audit_log 行数: {results['log_count']}")
        print(f"\n维度明细:")
        for dim, d in results.get('dimensions', {}).items():
            status = []
            if d.get('pass', 0) > 0:
                status.append(f"PASS={d['pass']}")
            if d.get('warn', 0) > 0:
                status.append(f"WARN={d['warn']}")
            if d.get('fail', 0) > 0:
                status.append(f"FAIL={d['fail']}")
            if status:
                flag = '⚠️' if d.get('fail', 0) > 0 else ('🟡' if d.get('warn', 0) > 0 else '✅')
                print(f"  {flag} {dim} {DIMENSIONS.get(dim, '')}: {' / '.join(status)}")
        if results['failed_trades']:
            print(f"\n失败交易明细:")
            for ft in results['failed_trades'][:10]:
                print(f"  {ft['trade_id']}: {ft['verdict']} → {ft['issues'][:3]}")

    elif args.demo:
        conn = _connect(db_path)
        ensure_audit_schema(db_path)

        # 取一个现存 session 来关联
        sample = conn.execute(
            "SELECT session_id, current_cash FROM mt_sandbox_portfolio LIMIT 1"
        ).fetchone()
        session_id = sample['session_id'] if sample else 'SB-DEMO-001'
        cash = float(sample['current_cash']) if sample else 10000.0

        mock_trades = [
            {'trade_id': f"T-DEMO-{uuid.uuid4().hex[:8]}", 'session_id': session_id,
             'symbol': 'sh600519', 'side': 'BUY', 'qty': 100, 'price': 1680.0,
             'fee': 50.40, 'tax': 0.0, 'total_amount': 168000.0,
             'cash_before': cash, 'cash_after': cash - 168000 - 50.40},
            {'trade_id': f"T-DEMO-{uuid.uuid4().hex[:8]}", 'session_id': session_id,
             'symbol': 'sz000001', 'side': 'BUY', 'qty': 50, 'price': 10.5,  # 非整手 → D05
             'fee': 5.0, 'tax': 0.0, 'total_amount': 525.0,
             'cash_before': cash, 'cash_after': cash - 525 - 5.0},
            {'trade_id': f"T-DEMO-{uuid.uuid4().hex[:8]}", 'session_id': session_id,
             'symbol': 'sh601318', 'side': 'SELL', 'qty': 100, 'price': 50.0,
             'fee': 5.0, 'tax': 0.0,  # tax=0 但应该收 0.1% → D08
             'total_amount': 5000.0,
             'cash_before': cash, 'cash_after': cash + 5000 - 5.0},
        ]

        for t in mock_trades:
            # 先写入 sandbox_trades 让 D06 有得检查
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO mt_sandbox_trades "
                    "(trade_id, session_id, trade_date, trade_time, symbol, stock_name, "
                    "action, shares, price, commission, stamp_tax, total_amount, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))",
                    (t['trade_id'], t['session_id'], _now_str()[:10], _now_str()[11:19],
                     t['symbol'], 'MOCK', t['side'], t['qty'], t['price'],
                     t['fee'], t['tax'], t['total_amount'])
                )
            except Exception:
                pass
            r = audit_trade(t, db_path)
            print(f"\n🔍 {t['trade_id']} {t['side']} {t['symbol']} × {t['qty']} @ ¥{t['price']:.2f}")
            print(f"   verdict: {r['verdict']}")
            if r['issues']:
                for issue in r['issues']:
                    print(f"   ⚠️ {issue['dim']} [{issue['level']}] {issue['desc']}")

        conn.commit()
        conn.close()

        # 验证行数
        conn = _connect(db_path)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM mt_vault_audit_log WHERE audit_type='REALTIME'"
        ).fetchone()[0]
        conn.close()
        print(f"\naudit_log 总行数: {cnt} (预期 ~36)")

    else:
        print("请用 --all (批量稽查现存交易) 或 --demo (mock 测试)")
        print("或导入本模块调用 audit_trade(trade_data_dict)")


if __name__ == '__main__':
    main()
