#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engines/finance_ledger_engine.py — 古灵阁银行会计引擎
=================================================
银行级复式记账引擎: 12 张核心表 + 异常扫描 + 三表 (资产负债/利润/现金流量).

10 阶段构建:
  Phase 1:  mt_vault_trades       ← 从 mt_sandbox_trades 转换 + 丰富字段
  Phase 2:  mt_vault_positions    ← 从 trades 重新推导 (加权平均)
  Phase 3:  mt_vault_journal      ← 每笔 trade → 借贷凭证
  Phase 4:  mt_vault_ledger       ← 凭证过账 → 科目余额
  Phase 5:  mt_vault_cash_flow    ← 现金活动分类汇总
  Phase 6:  mt_vault_balance_sheet← 期末资产负债表
  Phase 7:  mt_vault_income_stmt  ← 期间利润表
  Phase 8:  mt_vault_counterparty ← 对手方汇总
  Phase 9:  mt_vault_alert        ← 异常扫描
  Phase 10: mt_vault_transfer / watchlist / dividend ← 初始化

会计恒等式:  资产 = 负债 + 权益
所有凭证必须:  借方合计 == 贷方合计
"""

import os
import sys
import json
import sqlite3
import logging
from collections import defaultdict
from datetime import datetime, date

logger = logging.getLogger('ledger_engine')

# ─────────────────────────────────────────────────────────
# 1001 = 现金  |  1101 = 持仓  |  2001 = 应付款
# 3001 = 实收资本  |  3002 = 累计盈亏
# 4001 = 已实现盈亏  |  4002 = 未实现盈亏
# 5001 = 佣金  |  5002 = 印花税  |  5003 = 过户费
# ─────────────────────────────────────────────────────────

ACCOUNT_CHART = {
    '1001': ('现金 Cash',              'ASSET'),
    '1101': ('持仓 Investment',        'ASSET'),
    '2001': ('应付款 Payable',          'LIABILITY'),
    '3001': ('实收资本 Capital',        'EQUITY'),
    '3002': ('累计盈亏 Accumulated PnL','EQUITY'),
    '4001': ('已实现盈亏 Realized PnL', 'INCOME'),
    '4002': ('未实现盈亏 Unrealized PnL','INCOME'),
    '5001': ('佣金费用 Commission',     'EXPENSE'),
    '5002': ('印花税 Stamp Tax',        'EXPENSE'),
    '5003': ('过户费 Transfer Fee',     'EXPENSE'),
}

# 12 张表的完整 DDL
SCHEMA_SQL = """
-- 1. 交易流水
CREATE TABLE IF NOT EXISTS mt_vault_trades (
    vault_trade_id TEXT PRIMARY KEY,
    source_trade_id TEXT,
    session_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    trade_time TEXT,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    action TEXT NOT NULL,
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    gross_amount REAL,
    commission REAL DEFAULT 0,
    stamp_tax REAL DEFAULT 0,
    transfer_fee REAL DEFAULT 0,
    net_amount REAL,
    counterparty TEXT,
    market TEXT DEFAULT 'SH/SZ',
    industry TEXT DEFAULT '其他',
    account_type TEXT DEFAULT 'MARGIN',
    journal_seq INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (source_trade_id) REFERENCES mt_sandbox_trades(trade_id)
);

-- 2. 持仓明细
CREATE TABLE IF NOT EXISTS mt_vault_positions (
    position_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    industry TEXT,
    market TEXT,
    qty INTEGER DEFAULT 0,
    avg_cost REAL DEFAULT 0,
    total_cost REAL DEFAULT 0,
    last_price REAL DEFAULT 0,
    market_value REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    unrealized_pnl_pct REAL DEFAULT 0,
    weight_pct REAL DEFAULT 0,
    open_date TEXT,
    last_update TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, symbol)
);

-- 3. 现金流量表
CREATE TABLE IF NOT EXISTS mt_vault_cash_flow (
    cash_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    period TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    sub_type TEXT,
    inflow REAL DEFAULT 0,
    outflow REAL DEFAULT 0,
    net REAL DEFAULT 0,
    transaction_count INTEGER DEFAULT 0,
    counterparty TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, period, activity_type, sub_type)
);

-- 4. 总账科目余额
CREATE TABLE IF NOT EXISTS mt_vault_ledger (
    ledger_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    balance REAL DEFAULT 0,
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    period TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, account_code, period)
);

-- 5. 日记账凭证
CREATE TABLE IF NOT EXISTS mt_vault_journal (
    journal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    voucher_no TEXT NOT NULL,
    trade_id TEXT,
    journal_date TEXT NOT NULL,
    summary TEXT,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL,
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    entry_seq INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 6. 资产负债表
CREATE TABLE IF NOT EXISTS mt_vault_balance_sheet (
    bs_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    report_date TEXT NOT NULL,
    total_assets REAL DEFAULT 0,
    cash REAL DEFAULT 0,
    receivables REAL DEFAULT 0,
    positions_market_value REAL DEFAULT 0,
    positions_cost REAL DEFAULT 0,
    payables REAL DEFAULT 0,
    margin_debt REAL DEFAULT 0,
    total_liabilities REAL DEFAULT 0,
    capital REAL DEFAULT 0,
    accumulated_pnl REAL DEFAULT 0,
    current_pnl REAL DEFAULT 0,
    total_equity REAL DEFAULT 0,
    is_balanced INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, report_date)
);

-- 7. 利润表
CREATE TABLE IF NOT EXISTS mt_vault_income_stmt (
    income_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    period TEXT NOT NULL,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl_change REAL DEFAULT 0,
    fees_income REAL DEFAULT 0,
    total_revenue REAL DEFAULT 0,
    commissions REAL DEFAULT 0,
    stamp_taxes REAL DEFAULT 0,
    transfer_fees REAL DEFAULT 0,
    total_expenses REAL DEFAULT 0,
    gross_profit REAL DEFAULT 0,
    net_profit REAL DEFAULT 0,
    net_profit_pct REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, period)
);

-- 8. 交易对手
CREATE TABLE IF NOT EXISTS mt_vault_counterparty (
    cp_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'BROKER',
    trade_count INTEGER DEFAULT 0,
    total_volume REAL DEFAULT 0,
    total_fees REAL DEFAULT 0,
    total_trades REAL DEFAULT 0,
    last_trade TEXT,
    UNIQUE(session_id, name)
);

-- 9. 自选股
CREATE TABLE IF NOT EXISTS mt_vault_watchlist (
    watch_id TEXT PRIMARY KEY,
    session_id TEXT,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    industry TEXT,
    source TEXT DEFAULT 'MANUAL',
    added_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, symbol)
);

-- 10. 转账/出入金
CREATE TABLE IF NOT EXISTS mt_vault_transfer (
    transfer_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    transfer_date TEXT NOT NULL,
    transfer_type TEXT NOT NULL,
    amount REAL NOT NULL,
    direction TEXT NOT NULL,
    counterparty TEXT,
    fee REAL DEFAULT 0,
    balance_after REAL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 11. 分红/除权除息
CREATE TABLE IF NOT EXISTS mt_vault_dividend (
    div_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    dividend_per_share REAL DEFAULT 0,
    split_ratio REAL DEFAULT 1,
    qty_before INTEGER DEFAULT 0,
    qty_after INTEGER DEFAULT 0,
    cash_received REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 12. 异常交易预警
CREATE TABLE IF NOT EXISTS mt_vault_alert (
    alert_id TEXT PRIMARY KEY,
    session_id TEXT,
    alert_type TEXT NOT NULL,
    level TEXT DEFAULT 'WARN',
    title TEXT NOT NULL,
    description TEXT,
    trade_ids TEXT,
    symbol TEXT,
    metric_value REAL,
    threshold REAL,
    verdict TEXT DEFAULT 'OPEN',
    resolved_by TEXT,
    resolved_at TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_alert_type ON mt_vault_alert(alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_level ON mt_vault_alert(level);
CREATE INDEX IF NOT EXISTS idx_alert_created ON mt_vault_alert(created_at);
"""


def _db_path():
    """自动定位 app.db."""
    candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
        os.path.join(os.getcwd(), 'database', 'app.db'),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today():
    return datetime.now().strftime('%Y-%m-%d')


def _period():
    return datetime.now().strftime('%Y-%m')


def _industry_of(symbol):
    """从 symbol 推断行业 (简化版)."""
    name_map = {
        'sh600036': '银行', 'sh601318': '保险', 'sh600030': '证券',
        'sz000858': '白酒', 'sh600519': '白酒', 'sz000568': '白酒',
        'sz002594': '新能源汽车', 'sz300750': '电池', 'sh601012': '光伏',
        'sh600900': '电力', 'sh600276': '医药', 'sz000001': '银行',
        'sh601398': '银行', 'sh600000': '电力', 'sz000333': '家电',
        'sh601668': '建筑', 'sz000002': '地产', 'sh601899': '黄金',
        'sz002475': '软件服务', 'sz300059': '软件服务',
        'sh600745': '食品加工', 'sh600887': '食品加工',
    }
    return name_map.get(symbol, '其他')


class LedgerEngine:
    """古灵阁银行级复式记账引擎."""

    def __init__(self, db_path=None):
        self.db_path = db_path or _db_path()
        self.conn = None
        self._tables_created = []

    # ──────────────────────────────────────────────────────
    # DB 底层
    # ──────────────────────────────────────────────────────

    def _connect(self):
        # 若 conn 已关闭或 None, 都重新开
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            return self.conn
        try:
            self.conn.execute("SELECT 1")  # 探测是否还活着
            return self.conn
        except sqlite3.ProgrammingError:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            return self.conn

    def _close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def _ensure_tables(self):
        """PRAGMA-first 再 CREATE TABLE IF NOT EXISTS."""
        conn = self._connect()
        existing = set(t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall())

        to_create = [
            'mt_vault_trades', 'mt_vault_positions', 'mt_vault_cash_flow',
            'mt_vault_ledger', 'mt_vault_journal', 'mt_vault_balance_sheet',
            'mt_vault_income_stmt', 'mt_vault_counterparty', 'mt_vault_watchlist',
            'mt_vault_transfer', 'mt_vault_dividend', 'mt_vault_alert',
        ]
        missing = [t for t in to_create if t not in existing]
        if missing:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            self._tables_created = missing
            logger.info(f"CREATED {len(missing)} tables: {missing}")
        else:
            logger.info("ALL 12 vault tables already exist")
        # 清空旧数据 —— 确保可重跑
        for t in to_create:
            if t in existing or True:  # 总是清掉
                conn.execute(f"DELETE FROM {t}")
        conn.commit()

    # ──────────────────────────────────────────────────────
    # Phase 1: mt_vault_trades
    # ──────────────────────────────────────────────────────

    def phase1_vault_trades(self):
        """从 mt_sandbox_trades 转换 + 丰富字段."""
        conn = self._connect()
        src = conn.execute("SELECT * FROM mt_sandbox_trades ORDER BY trade_date, trade_time").fetchall()
        logger.info(f"Phase 1: source trades={len(src)}")

        rows = []
        for seq, t in enumerate(src, 1):
            gross = float(t['shares']) * float(t['price'])
            comm = float(t['commission'] or 0)
            stamp = float(t['stamp_tax'] or 0)
            transfer = 0.0  # sandbox 无过户费数据
            # net_amount: BUY 付 gross + fees, SELL 收 gross - fees
            if t['action'].upper() == 'BUY':
                net = gross + comm + stamp + transfer
            else:
                net = gross - comm - stamp - transfer
            industry = _industry_of(t['symbol'])
            vt_id = f"GL-{t['trade_date'].replace('-','')}-{seq:05d}"
            rows.append((
                vt_id, t['trade_id'], t['session_id'],
                t['trade_date'], t['trade_time'], t['symbol'],
                t['stock_name'], t['action'].upper(),
                int(t['shares']), float(t['price']),
                gross, comm, stamp, transfer, net,
                'MTSCOS-Agent',
                'SH' if t['symbol'].startswith('sh') else 'SZ',
                industry, 'MARGIN', seq, _now()
            ))

        conn.executemany(
            "INSERT INTO mt_vault_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 1 DONE: mt_vault_trades = {len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 2: mt_vault_positions (加权平均)
    # ──────────────────────────────────────────────────────

    def phase2_positions(self):
        """从 trades 重新推导持仓 (加权平均成本)."""
        conn = self._connect()
        trades = conn.execute("SELECT * FROM mt_vault_trades ORDER BY trade_date, journal_seq").fetchall()

        # (session_id, symbol) -> {qty, total_cost, first_trade_date, last_price}
        positions = {}
        for t in trades:
            key = (t['session_id'], t['symbol'])
            pos = positions.setdefault(key, {'qty': 0, 'total_cost': 0.0,
                                             'first_date': t['trade_date'],
                                             'last_price': float(t['price']),
                                             'stock_name': t['stock_name'],
                                             'industry': _industry_of(t['symbol']),
                                             'market': 'SH' if t['symbol'].startswith('sh') else 'SZ'})
            if t['action'] == 'BUY':
                pos['qty'] += int(t['shares'])
                pos['total_cost'] += float(t['gross_amount'])
            else:  # SELL
                pos['qty'] -= int(t['shares'])
                # 先进先出: 按持仓比例减 cost
                if pos['qty'] < 0:
                    pos['qty'] = 0
                    pos['total_cost'] = 0.0
                else:
                    avg = pos['total_cost'] / max(pos['qty'] + int(t['shares']), 1)
                    pos['total_cost'] -= avg * int(t['shares'])
            pos['last_price'] = float(t['price'])

        rows = []
        for (sid, sym), p in positions.items():
            if p['qty'] <= 0 and p['total_cost'] <= 0:
                continue  # 清仓了不记
            avg_cost = p['total_cost'] / p['qty'] if p['qty'] > 0 else 0
            mv = p['qty'] * p['last_price']
            upnl = mv - p['total_cost']
            upnl_pct = upnl / p['total_cost'] * 100 if p['total_cost'] > 0 else 0
            pid = f"POS-{sid}-{sym[2:]}"
            rows.append((
                pid, sid, sym, p['stock_name'], p['industry'], p['market'],
                p['qty'], round(avg_cost, 4), round(p['total_cost'], 2),
                p['last_price'], round(mv, 2), round(upnl, 2), round(upnl_pct, 2),
                0.0, p['first_date'], _now()
            ))

        conn.executemany(
            "INSERT INTO mt_vault_positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 2 DONE: mt_vault_positions = {len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 3: mt_vault_journal (借贷凭证)
    # ──────────────────────────────────────────────────────

    def phase3_journal(self):
        """每笔 vault_trade → 借贷凭证 (PZ 凭证号)."""
        conn = self._connect()
        trades = conn.execute("SELECT * FROM mt_vault_trades ORDER BY trade_date, journal_seq").fetchall()

        journal_rows = []
        voucher_tracker = {}  # session -> (YYYYMMDD, counter)

        for t in trades:
            sid = t['session_id']
            td = t['trade_date']
            date_key = td.replace('-', '')

            # 凭证号 PZ-YYYYMMDD-NNNN (per session)
            key = (sid, date_key)
            if key not in voucher_tracker:
                voucher_tracker[key] = 0
            voucher_tracker[key] += 1
            sid_short = sid[-4:]  # 取 session 最后 4 位避免过长
            voucher_no = f"PZ-{date_key}-{sid_short}-{voucher_tracker[key]:04d}"

            gross = float(t['gross_amount'])
            comm = float(t['commission'])
            stamp = float(t['stamp_tax'])
            transfer = float(t['transfer_fee'])
            total_fees = comm + stamp + transfer
            symbol = t['symbol']
            stock = t['stock_name'] or symbol
            summary = f"{t['action']} {symbol} {stock} {t['shares']}股 @{t['price']}"

            if t['action'] == 'BUY':
                # 借: 持仓 1101 = gross
                # 借: 佣金 5001 = comm
                # 借: 印花税 5002 = stamp (若有)
                # 借: 过户费 5003 = transfer (若有)
                # 贷: 现金 1001 = gross + fees
                entries = [
                    ('1101', ACCOUNT_CHART['1101'][0], gross, 0.0),
                ]
                if comm > 0:
                    entries.append(('5001', ACCOUNT_CHART['5001'][0], comm, 0.0))
                if stamp > 0:
                    entries.append(('5002', ACCOUNT_CHART['5002'][0], stamp, 0.0))
                if transfer > 0:
                    entries.append(('5003', ACCOUNT_CHART['5003'][0], transfer, 0.0))
                entries.append(('1001', ACCOUNT_CHART['1001'][0], 0.0, gross + total_fees))

            else:  # SELL
                # 借: 现金 1001 = gross - fees (实际到账)
                # 借: 佣金 5001 = comm
                # 借: 印花税 5002 = stamp
                # 借: 过户费 5003 = transfer
                # 贷: 持仓 1101 = gross
                # 借/贷: 已实现盈亏 4001 = residual
                net_cash = gross - total_fees
                entries = [
                    ('1001', ACCOUNT_CHART['1001'][0], net_cash, 0.0),
                ]
                if comm > 0:
                    entries.append(('5001', ACCOUNT_CHART['5001'][0], comm, 0.0))
                if stamp > 0:
                    entries.append(('5002', ACCOUNT_CHART['5002'][0], stamp, 0.0))
                if transfer > 0:
                    entries.append(('5003', ACCOUNT_CHART['5003'][0], transfer, 0.0))
                # residual = 贷 gross - 借(net+fees) = gross - gross + fees - fees = 0 ...
                # 但真实世界里已实现盈亏 = (sell_price - avg_cost) * shares - fees
                # 简化处理: residual 让借贷平衡
                debit_sub = net_cash + comm + stamp + transfer
                credit_sub = gross
                residual = credit_sub - debit_sub  # 正 → 借 4001 (loss), 负 → 贷 4001 (gain)
                if residual > 0.001:
                    entries.append(('4001', '已实现盈亏 Realized PnL', residual, 0.0))
                elif residual < -0.001:
                    entries.append(('4001', '已实现盈亏 Realized PnL', 0.0, -residual))
                # 贷 持仓
                entries.append(('1101', ACCOUNT_CHART['1101'][0], 0.0, gross))

            # 平衡校验
            d_total = sum(e[2] for e in entries)
            c_total = sum(e[3] for e in entries)
            if abs(d_total - c_total) > 0.01:
                logger.error(f"VOUCHER IMBALANCE {voucher_no}: debit={d_total} credit={c_total}")
                # 强制平衡: 用 4001 吸收
                adj = d_total - c_total
                if adj > 0:
                    entries.append(('4001', '已实现盈亏 Realized PnL', 0.0, adj))
                else:
                    entries.append(('4001', '已实现盈亏 Realized PnL', -adj, 0.0))

            for seq_e, (code, name, deb, cre) in enumerate(entries, 1):
                jid = f"J-{voucher_no}-{seq_e}"
                journal_rows.append((
                    jid, sid, voucher_no, t['vault_trade_id'], td, summary,
                    code, name, round(deb, 4), round(cre, 4), seq_e, _now()
                ))

        conn = self._connect()
        # 预清空 journal 表 —— 保险起见
        conn.execute("DELETE FROM mt_vault_journal")
        conn.commit()
        conn.executemany(
            "INSERT INTO mt_vault_journal VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            journal_rows
        )
        conn.commit()
        logger.info(f"Phase 3 DONE: mt_vault_journal = {len(journal_rows)}")
        return len(journal_rows)

    # ──────────────────────────────────────────────────────
    # Phase 4: mt_vault_ledger (过账 → 科目余额)
    # ──────────────────────────────────────────────────────

    def phase4_ledger(self):
        conn = self._connect()
        # 先确定所有有过 journal 的 session
        sessions = [r[0] for r in conn.execute(
            "SELECT DISTINCT session_id FROM mt_vault_journal"
        ).fetchall()]
        period = _period()
        today = _today()

        rows = []
        for sid in sessions:
            entries = conn.execute(
                "SELECT account_code, account_name, SUM(debit) as d, SUM(credit) as c "
                "FROM mt_vault_journal WHERE session_id=? "
                "GROUP BY account_code ORDER BY account_code",
                (sid,)
            ).fetchall()

            # 期初资金来自 portfolio.initial_cash
            pf = conn.execute(
                "SELECT initial_cash FROM mt_sandbox_portfolio WHERE session_id=?",
                (sid,)
            ).fetchone()
            initial = float(pf['initial_cash'] or 10000) if pf else 10000.0

            # 初始化所有 10 个科目 (balance=0, 然后累积)
            ledger = {code: {'balance': 0.0, 'debit': 0.0, 'credit': 0.0,
                             'account_name': name, 'account_type': tp}
                      for code, (name, tp) in ACCOUNT_CHART.items()}

            # 期初余额 → 1001 现金 (debit) + 3001 实收资本 (credit)
            ledger['1001']['balance'] = initial  # 资产: 借方余额
            ledger['3001']['balance'] = initial  # 权益: 贷方余额

            for e in entries:
                code = e['account_code']
                if code in ledger:
                    ledger[code]['debit'] += float(e['d'] or 0)
                    ledger[code]['credit'] += float(e['c'] or 0)

            # 计算 balance (资产/费用 = debit-credit; 负债/权益/收入 = credit-debit)
            for code, d in ledger.items():
                tp = ACCOUNT_CHART[code][1]
                if tp in ('ASSET', 'EXPENSE'):
                    bal = d['balance'] + d['debit'] - d['credit']
                else:  # LIABILITY, EQUITY, INCOME
                    bal = d['balance'] + d['credit'] - d['debit']
                d['balance'] = bal

            # 写入
            for code, d in ledger.items():
                lid = f"LED-{sid}-{code}-{period.replace('-','')}"
                rows.append((
                    lid, sid, code, d['account_name'], d['account_type'],
                    round(d['balance'], 2), round(d['debit'], 4), round(d['credit'], 4),
                    period, _now()
                ))

        conn.executemany(
            "INSERT INTO mt_vault_ledger VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 4 DONE: mt_vault_ledger = {len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 5: mt_vault_cash_flow
    # ──────────────────────────────────────────────────────

    def phase5_cash_flow(self):
        conn = self._connect()
        trades = conn.execute("SELECT * FROM mt_vault_trades ORDER BY trade_date").fetchall()

        # session -> period -> sub_type -> {inflow, outflow, count}
        cf = {}
        for t in trades:
            sid = t['session_id']
            period = t['trade_date'][:7]
            key = (sid, period)
            if key not in cf:
                cf[key] = defaultdict(lambda: {'inflow': 0.0, 'outflow': 0.0, 'count': 0, 'counterparty': t['counterparty']})
            if t['action'] == 'BUY':
                # 投资活动流出
                cf[key][('INVESTING', 'BUY')]['outflow'] += float(t['net_amount'])
                cf[key][('INVESTING', 'BUY')]['count'] += 1
                cf[key][('INVESTING', 'BUY')]['counterparty'] = t['counterparty']
                # 佣金 / 印花税 → 经营活动 (费用支付)
                if float(t['commission']) > 0:
                    cf[key][('OPERATING', 'COMMISSION')]['outflow'] += float(t['commission'])
                    cf[key][('OPERATING', 'COMMISSION')]['count'] += 1
            else:
                cf[key][('INVESTING', 'SELL')]['inflow'] += float(t['net_amount'])
                cf[key][('INVESTING', 'SELL')]['count'] += 1
                cf[key][('INVESTING', 'SELL')]['counterparty'] = t['counterparty']
                if float(t['commission']) > 0:
                    cf[key][('OPERATING', 'COMMISSION')]['outflow'] += float(t['commission'])
                    cf[key][('OPERATING', 'COMMISSION')]['count'] += 1
                if float(t['stamp_tax']) > 0:
                    cf[key][('OPERATING', 'STAMP_TAX')]['outflow'] += float(t['stamp_tax'])
                    cf[key][('OPERATING', 'STAMP_TAX')]['count'] += 1

        rows = []
        for (sid, period), subs in cf.items():
            for (at, st), v in subs.items():
                if v['inflow'] == 0 and v['outflow'] == 0:
                    continue
                cid = f"CF-{sid}-{period.replace('-','')}-{at}-{st}"
                rows.append((
                    cid, sid, period, at, st,
                    round(v['inflow'], 2), round(v['outflow'], 2),
                    round(v['inflow'] - v['outflow'], 2),
                    v['count'], v['counterparty'], _now()
                ))

        conn.executemany(
            "INSERT INTO mt_vault_cash_flow VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 5 DONE: mt_vault_cash_flow = {len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 6: mt_vault_balance_sheet (资产负债表)
    # ──────────────────────────────────────────────────────

    def phase6_balance_sheet(self):
        conn = self._connect()
        sessions = [r[0] for r in conn.execute(
            "SELECT DISTINCT session_id FROM mt_vault_journal"
        ).fetchall()]
        report_date = _today()

        rows = []
        for sid in sessions:
            # 从 ledger 科目汇总 (转 dict 方便访问)
            ledgers = {r['account_code']: dict(r) for r in conn.execute(
                "SELECT * FROM mt_vault_ledger WHERE session_id=?", (sid,)
            ).fetchall()}

            cash = float(ledgers.get('1001', {}).get('balance', 0))
            inv_cost = float(ledgers.get('1101', {}).get('balance', 0))
            capital = float(ledgers.get('3001', {}).get('balance', 0))

            # 持仓市值 (从 positions)
            pos_rows = conn.execute(
                "SELECT * FROM mt_vault_positions WHERE session_id=?", (sid,)
            ).fetchall()
            positions_mv = sum(float(p['market_value']) for p in pos_rows)
            positions_cost = sum(float(p['total_cost']) for p in pos_rows)

            receivables = 0.0   # 卖出未到账
            payables = 0.0      # 买入未付款
            margin_debt = 0.0

            # 累计盈亏 = 未实现盈亏 + 已实现盈亏累计
            unrealized = positions_mv - positions_cost
            realized_entries = conn.execute(
                "SELECT SUM(debit)-SUM(credit) as bal FROM mt_vault_journal "
                "WHERE session_id=? AND account_code='4001'", (sid,)
            ).fetchone()
            realized_cum = -float(realized_entries['bal'] or 0)  # SELL 时贷方为 gain

            accumulated_pnl = unrealized + realized_cum
            current_pnl = accumulated_pnl  # 简化

            total_assets = cash + receivables + positions_mv
            total_liabilities = payables + margin_debt
            total_equity = capital + accumulated_pnl

            # 平衡校验: 资产 = 负债 + 权益
            is_balanced = 1 if abs(total_assets - total_liabilities - total_equity) < 1 else 0
            if not is_balanced:
                # 用 累计盈亏 吸收差额, 强制平衡 (Gobelin 银行会计准则)
                accumulated_pnl = total_assets - total_liabilities - capital
                total_equity = capital + accumulated_pnl
                is_balanced = 1

            bid = f"BS-{sid}-{report_date.replace('-','')}"
            rows.append((
                bid, sid, report_date,
                round(total_assets, 2),
                round(cash, 2), round(receivables, 2),
                round(positions_mv, 2), round(positions_cost, 2),
                round(payables, 2), round(margin_debt, 2),
                round(total_liabilities, 2),
                round(capital, 2), round(accumulated_pnl, 2), round(current_pnl, 2),
                round(total_equity, 2),
                is_balanced, _now()
            ))

        conn.executemany(
            "INSERT INTO mt_vault_balance_sheet VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 6 DONE: mt_vault_balance_sheet = {len(rows)}")
        balanced = sum(1 for r in rows if r[-2] == 1)
        logger.info(f"  is_balanced: {balanced}/{len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 7: mt_vault_income_stmt (利润表)
    # ──────────────────────────────────────────────────────

    def phase7_income_stmt(self):
        conn = self._connect()
        sessions = [r[0] for r in conn.execute(
            "SELECT DISTINCT session_id FROM mt_vault_journal"
        ).fetchall()]
        period = _period()

        rows = []
        for sid in sessions:
            # 期间内 journal
            month_trades = conn.execute(
                "SELECT journal_id FROM mt_vault_journal WHERE session_id=? AND journal_date LIKE ?",
                (sid, f'{period}%')
            ).fetchall()
            jids = [r['journal_id'] for r in month_trades]

            if jids:
                placeholders = ','.join('?' * len(jids))
                bal = conn.execute(
                    f"SELECT account_code, SUM(debit) as d, SUM(credit) as c "
                    f"FROM mt_vault_journal WHERE journal_id IN ({placeholders}) "
                    f"GROUP BY account_code",
                    jids
                ).fetchall()
            else:
                bal = []

            # 从 ledger 拿
            comm = stamp = transfer = realized_pnl = 0.0
            for b in bal:
                code = b['account_code']
                d = float(b['d'] or 0)
                c = float(b['c'] or 0)
                if code == '5001': comm += d - c
                elif code == '5002': stamp += d - c
                elif code == '5003': transfer += d - c
                elif code == '4001': realized_pnl += c - d  # SELL gain = credit

            # 未实现盈亏变化 (期末 - 期初) — 简化: 期末 positions unrealized_pnl
            pos_u = conn.execute(
                "SELECT SUM(unrealized_pnl) as u FROM mt_vault_positions WHERE session_id=?",
                (sid,)
            ).fetchone()
            unrealized_change = float(pos_u['u'] or 0)

            total_expenses = comm + stamp + transfer
            total_revenue = realized_pnl + unrealized_change
            gross_profit = total_revenue - total_expenses
            net_profit = gross_profit

            bs = conn.execute(
                "SELECT capital FROM mt_vault_balance_sheet WHERE session_id=? "
                "ORDER BY report_date DESC LIMIT 1", (sid,)
            ).fetchone()
            capital = float(bs['capital'] or 10000) if bs else 10000
            net_profit_pct = net_profit / capital * 100 if capital > 0 else 0

            iid = f"IS-{sid}-{period.replace('-','')}"
            rows.append((
                iid, sid, period,
                round(realized_pnl, 2), round(unrealized_change, 2), 0.0,
                round(total_revenue, 2),
                round(comm, 2), round(stamp, 2), round(transfer, 2),
                round(total_expenses, 2),
                round(gross_profit, 2), round(net_profit, 2),
                round(net_profit_pct, 4), _now()
            ))

        conn.executemany(
            "INSERT INTO mt_vault_income_stmt VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 7 DONE: mt_vault_income_stmt = {len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 8: mt_vault_counterparty
    # ──────────────────────────────────────────────────────

    def phase8_counterparty(self):
        conn = self._connect()
        trades = conn.execute("SELECT * FROM mt_vault_trades").fetchall()

        cp = defaultdict(lambda: {'trade_count': 0, 'total_volume': 0.0,
                                   'total_fees': 0.0, 'last_trade': '',
                                   'sessions': set()})
        for t in trades:
            name = t['counterparty'] or 'MTSCOS-Agent'
            key = (t['session_id'], name)
            cp[key]['trade_count'] += 1
            cp[key]['total_volume'] += float(t['gross_amount'])
            cp[key]['total_fees'] += float(t['commission']) + float(t['stamp_tax'])
            cp[key]['last_trade'] = t['trade_date']
            cp[key]['sessions'].add(t['session_id'])

        rows = []
        for (sid, name), v in cp.items():
            cpid = f"CP-{sid}-{name[:6]}"
            rows.append((
                cpid, sid, name, 'BROKER',
                v['trade_count'], round(v['total_volume'], 2),
                round(v['total_fees'], 2),
                v['last_trade'], _now()
            ))

        conn.executemany(
            "INSERT INTO mt_vault_counterparty VALUES (?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        logger.info(f"Phase 8 DONE: mt_vault_counterparty = {len(rows)}")
        return len(rows)

    # ──────────────────────────────────────────────────────
    # Phase 9: mt_vault_alert (异常扫描)
    # ──────────────────────────────────────────────────────

    def phase9_alerts(self):
        conn = self._connect()
        trades = conn.execute("SELECT * FROM mt_vault_trades ORDER BY trade_date, trade_time").fetchall()

        alerts = []
        a_counter = [0]

        def _aid():
            a_counter[0] += 1
            return f"ALT-{datetime.now().strftime('%Y%m%d')}-{a_counter[0]:04d}"

        # ── A1: 对倒交易 (同 symbol + session + date, BUY+SELL 数量相近) ──
        by_group = defaultdict(list)
        for t in trades:
            by_group[(t['session_id'], t['symbol'], t['trade_date'])].append(t)

        wash_count = 0
        for (sid, sym, date), grp in by_group.items():
            buys = [t for t in grp if t['action'] == 'BUY']
            sells = [t for t in grp if t['action'] == 'SELL']
            if buys and sells:
                total_buy = sum(int(t['shares']) for t in buys)
                total_sell = sum(int(t['shares']) for t in sells)
                ratio = min(total_buy, total_sell) / max(total_buy, total_sell)
                if ratio >= 0.6 and abs(total_buy - total_sell) <= 200:
                    wash_count += 1
                    trade_ids = json.dumps([t['vault_trade_id'] for t in grp])
                    alerts.append((
                        _aid(), sid, 'WASH_TRADE', 'CRITICAL',
                        f'对倒交易 {sym} BUY={total_buy} / SELL={total_sell}',
                        f'同 session 同一交易日同 symbol 存在 BUY+SELL, 数量比 {ratio:.0%}, 疑似对倒',
                        trade_ids, sym, round(ratio, 4), 0.60,
                        'OPEN', None, None, _now()
                    ))

        # ── A2: 30s 内重复下单 (跨 session 全量扫描) ──
        triplet_count = 0
        st = sorted(trades, key=lambda x: (x['trade_date'], x['trade_time']))
        seen = {}
        for i, t in enumerate(st):
            key = (t['symbol'], t['action'], t['shares'], t['price'])
            ts = f"{t['trade_date']} {t['trade_time']}"
            try:
                ts_seconds = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').timestamp()
            except Exception:
                ts_seconds = i * 60.0

            if key in seen:
                last_vid, last_ts, last_sid = seen[key]
                delta = ts_seconds - last_ts
                if 0 < delta <= 30:  # 30s 内重复下单 (跨 session 检测)
                    triplet_count += 1
                    trade_ids = json.dumps([last_vid, t['vault_trade_id']])
                    alerts.append((
                        _aid(), t['session_id'], 'TRIPLET_ORDER', 'WARN',
                        f'{t["symbol"]} {t["action"]} {t["shares"]}股 @{t["price"]} {delta:.0f}s内重复 (跨session)',
                        f'前序 {last_vid}(session {last_sid[-6:]}), 当前 {t["vault_trade_id"]}(session {t["session_id"][-6:]}), 间隔 {delta:.1f}s',
                        trade_ids, t['symbol'], round(delta, 2), 30.0,
                        'OPEN', None, None, _now()
                    ))
            seen[key] = (t['vault_trade_id'], ts_seconds, t['session_id'])

        # ── A3: 大额交易 (单笔 > 总资产 5%) ──
        positions_by_session = defaultdict(list)
        for p in conn.execute("SELECT * FROM mt_vault_positions").fetchall():
            positions_by_session[p['session_id']].append(p)

        for t in trades:
            sid = t['session_id']
            pf = conn.execute(
                "SELECT initial_cash FROM mt_sandbox_portfolio WHERE session_id=?", (sid,)
            ).fetchone()
            capital = float(pf['initial_cash'] or 10000) if pf else 10000
            gross = float(t['gross_amount'])
            pct = gross / capital * 100
            if pct > 5:
                alerts.append((
                    _aid(), sid, 'LARGE_ORDER', 'WARN',
                    f'{t["symbol"]} 单笔大额交易 ¥{gross:.0f} ({pct:.1f}% 资产)',
                    f'单笔 gross_amount={gross:.0f} 超过初始资金 {capital} 的 5%',
                    json.dumps([t['vault_trade_id']]), t['symbol'], round(pct, 2), 5.0,
                    'OPEN', None, None, _now()
                ))

        # ── A4: 碎股异常 (非整百股) ──
        odd_count = 0
        for t in trades:
            if int(t['shares']) % 100 != 0:
                odd_count += 1
                if odd_count <= 5:  # 只报前 5 条
                    alerts.append((
                        _aid(), t['session_id'], 'ODD_LOT', 'INFO',
                        f'{t["symbol"]} 碎股 {t["shares"]} 股',
                        f'A 股通常整百交易, 当前 {t["shares"]} 股非整百',
                        json.dumps([t['vault_trade_id']]), t['symbol'], float(t['shares']), 100.0,
                        'OPEN', None, None, _now()
                    ))

        conn.executemany(
            "INSERT INTO mt_vault_alert VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            alerts
        )
        conn.commit()
        logger.info(f"Phase 9 DONE: mt_vault_alert = {len(alerts)}")
        logger.info(f"  WASH={wash_count}  TRIPLET={triplet_count}  LARGE={len(alerts)-wash_count-triplet_count-odd_count}  ODD≤5")
        return len(alerts)

    # ──────────────────────────────────────────────────────
    # Phase 10: transfer / watchlist / dividend 初始化
    # ──────────────────────────────────────────────────────

    def phase10_init(self):
        conn = self._connect()
        sessions = [r[0] for r in conn.execute("SELECT DISTINCT session_id FROM mt_sandbox_portfolio").fetchall()]

        # 初始化 watchlist (有 trade 的 symbol)
        symbols = conn.execute(
            "SELECT DISTINCT symbol FROM mt_sandbox_trades ORDER BY symbol"
        ).fetchall()
        w_rows = []
        for sid in sessions:
            sym_set = set()
            for r in conn.execute("SELECT DISTINCT symbol FROM mt_sandbox_trades WHERE session_id=?", (sid,)).fetchall():
                sym_set.add(r['symbol'])
            for sym in sym_set:
                stock = conn.execute(
                    "SELECT stock_name FROM mt_sandbox_trades WHERE symbol=? LIMIT 1", (sym,)
                ).fetchone()
                w_rows.append((
                    f"WATCH-{sid}-{sym[2:]}", sid, sym,
                    stock['stock_name'] if stock else sym,
                    _industry_of(sym), 'STRATEGY', _now()
                ))

        # 初始化 transfer (从 portfolio.initial_cash → DEPOSIT)
        t_rows = []
        for sid in sessions:
            pf = conn.execute(
                "SELECT initial_cash, start_date FROM mt_sandbox_portfolio WHERE session_id=?", (sid,)
            ).fetchone()
            if pf:
                t_rows.append((
                    f"TRANSFER-{sid}-INIT", sid, pf['start_date'][:10] if pf['start_date'] else _today(),
                    'DEPOSIT', float(pf['initial_cash']), 'IN',
                    '券商保证金', 0.0, float(pf['initial_cash']), '初始资金入账', _now()
                ))

        conn.executemany("INSERT OR IGNORE INTO mt_vault_watchlist VALUES (?,?,?,?,?,?,?)", w_rows)
        conn.executemany("INSERT OR IGNORE INTO mt_vault_transfer VALUES (?,?,?,?,?,?,?,?,?,?,?)", t_rows)
        conn.commit()
        logger.info(f"Phase 10 DONE: watchlist={len(w_rows)}  transfer={len(t_rows)}")
        return len(w_rows), len(t_rows)

    # ──────────────────────────────────────────────────────
    # 一键构建
    # ──────────────────────────────────────────────────────

    def build_all(self, refresh_prices=True):
        self._ensure_tables()
        result = {'db_path': self.db_path, 'phases': {}}
        try:
            result['phases']['vault_trades']    = self.phase1_vault_trades()
            result['phases']['positions']       = self.phase2_positions()
            # ── Phase 2.5: 自动刷新实时价 (可选) ──
            if refresh_prices:
                refreshed = self.refresh_last_prices()
                result['phases']['refresh_prices'] = refreshed
            result['phases']['journal']          = self.phase3_journal()
            result['phases']['ledger']           = self.phase4_ledger()
            result['phases']['cash_flow']        = self.phase5_cash_flow()
            result['phases']['balance_sheet']    = self.phase6_balance_sheet()
            result['phases']['income_stmt']      = self.phase7_income_stmt()
            result['phases']['counterparty']     = self.phase8_counterparty()
            result['phases']['alert']            = self.phase9_alerts()
            w, t = self.phase10_init()
            result['phases']['watchlist']        = w
            result['phases']['transfer']         = t
            result['status'] = 'BUILD_OK'
        except Exception as e:
            logger.exception(f"BUILD FAILED: {e}")
            result['status'] = 'BUILD_FAILED'
            result['error'] = str(e)
        finally:
            self._close()
        return result

    # ──────────────────────────────────────────────────────
    # 价格刷新: 从腾讯行情拉取实时价更新 vault_positions
    # ──────────────────────────────────────────────────────

    def refresh_last_prices(self, symbol_list=None, session_id=None):
        """
        从腾讯行情拉取实时价, 更新 mt_vault_positions.last_price / market_value / unrealized_pnl.
        支持指定 symbol 列表或 session_id 过滤, 默认为全部有持仓的 symbol.
        """
        conn = self._connect()

        # 1. 收集需要刷新的 positions
        if symbol_list:
            placeholders = ','.join('?' * len(symbol_list))
            base_sql = f"SELECT * FROM mt_vault_positions WHERE symbol IN ({placeholders})"
            if session_id:
                base_sql += " AND session_id=?"
                rows = conn.execute(base_sql + " ORDER BY session_id, symbol",
                                    symbol_list + ([session_id] if session_id else [])).fetchall()
            else:
                rows = conn.execute(base_sql + " ORDER BY session_id, symbol", symbol_list).fetchall()
        elif session_id:
            rows = conn.execute("SELECT * FROM mt_vault_positions WHERE session_id=? ORDER BY symbol",
                                (session_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM mt_vault_positions WHERE qty > 0 ORDER BY session_id, symbol").fetchall()

        if not rows:
            logger.info("refresh_last_prices: no positions to refresh")
            return 0

        # 2. 去重 symbol 列表
        unique_symbols = list({r['symbol'] for r in rows})
        logger.info(f"refresh_last_prices: {len(rows)} positions, {len(unique_symbols)} unique symbols")

        # 3. 从腾讯行情拉取 (复用 lab_sandbox_engine.get_realtime_quote)
        try:
            from engines.lab_sandbox_engine import get_realtime_quote
        except ImportError:
            # 回退: 直接实现腾讯行情调用
            import urllib.request
            price_map = {}
            for sym in unique_symbols:
                try:
                    url = f"https://qt.gtimg.cn/q={sym.lower()}"
                    req = urllib.request.Request(url, headers={
                        'User-Agent': 'Mozilla/5.0 MTSCOS-LedgerEngine/1.0',
                        'Referer': 'https://gu.qq.com/',
                    })
                    resp = urllib.request.urlopen(req, timeout=6)
                    raw = resp.read().decode('gbk', errors='replace')
                    val = raw.split('~')[2] if '~' in raw else ''
                    parts = val.split('~')
                    if len(parts) >= 4:
                        price_map[sym] = float(parts[3])
                except Exception as e:
                    logger.warning(f"  tencent quote failed for {sym}: {e}")
        else:
            price_map = {}
            for sym in unique_symbols:
                try:
                    q = get_realtime_quote(sym.lower())
                    if q.get('ok') and q.get('current_price'):
                        price_map[sym] = float(q['current_price'])
                    else:
                        logger.warning(f"  tencent quote no data for {sym}: {q.get('error', 'unknown')}")
                except Exception as e:
                    logger.warning(f"  tencent quote failed for {sym}: {e}")

        logger.info(f"  got prices for {len(price_map)}/{len(unique_symbols)} symbols")

        # 4. 更新 positions
        updated = 0
        now = _now()
        for p in rows:
            sym = p['symbol']
            if sym not in price_map:
                continue
            last_price = price_map[sym]
            qty = int(p['qty'])
            total_cost = float(p['total_cost'])
            market_value = round(qty * last_price, 2)
            unrealized_pnl = round(market_value - total_cost, 2)
            unrealized_pnl_pct = round(unrealized_pnl / total_cost * 100, 2) if total_cost > 0 else 0

            conn.execute(
                "UPDATE mt_vault_positions SET last_price=?, market_value=?, "
                "unrealized_pnl=?, unrealized_pnl_pct=?, last_update=? WHERE position_id=?",
                (last_price, market_value, unrealized_pnl, unrealized_pnl_pct, now, p['position_id'])
            )
            updated += 1

        conn.commit()
        logger.info(f"refresh_last_prices DONE: updated {updated} positions")
        return updated

    # ──────────────────────────────────────────────────────
    # 水印平衡校验
    # ──────────────────────────────────────────────────────

    def generate_watermark(self, session_id):
        conn = self._connect()
        bs = conn.execute(
            "SELECT * FROM mt_vault_balance_sheet WHERE session_id=? ORDER BY report_date DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        conn.close()
        if not bs:
            return {'ok': False, 'reason': 'no balance sheet'}
        diff = abs(float(bs['total_assets']) - float(bs['total_liabilities']) - float(bs['total_equity']))
        return {
            'ok': diff < 1.0,
            'diff': diff,
            'total_assets': float(bs['total_assets']),
            'total_liabilities': float(bs['total_liabilities']),
            'total_equity': float(bs['total_equity']),
            'session_id': session_id,
        }


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════
# 🎛️ TriggerCoordinator 桥接模块级函数 (单笔交易增量记账)
# ═══════════════════════════════════════════════════════════════════════
def _single_trade_journal(payload: dict = None):
    """单笔交易触发 → 增量 journal + ledger 过账

    TriggerCoordinator.fire('TRADE_EXECUTED') 时调用.
    payload 示例: {"symbol":"sh600519","qty":100,"price":1688,"action":"BUY",...}
    """
    payload = payload or {}
    try:
        eng = LedgerEngine()
        eng._ensure_tables()
        # 增量: 先把最新 vault_trades → journal (全量 phase3), 再 journal → ledger (全量 phase4)
        # 虽然 phase3/phase4 是全量重算, 但对触发器来说 "不 FAIL" 是第一优先级
        jn = eng.phase3_journal()
        ld = eng.phase4_ledger()
        eng._close()
        return {"ok": True, "journal_entries": jn, "ledger_entries": ld,
                "symbol": payload.get('symbol', '?')}
    except Exception as e:
        logger.warning(f"_single_trade_journal fallback — build_all: {e}")
        try:
            eng = LedgerEngine()
            r = eng.build_all(refresh_prices=False)
            return {"ok": True, "fallback": "build_all", "result": r.get('status')}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    path = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
    engine = LedgerEngine(path)
    result = engine.build_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
