#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finance_risk_engine.py — 古灵阁银行级风控引擎
=====================================================
10 大风控指标, 基于 mt_sandbox_snapshots / trades / portfolios 真数据.

用法:
    from engines.finance_risk_engine import RiskEngine
    re = RiskEngine('database/app.db')
    re.compute_all()   # 计算所有 session
"""

import os
import sys
import math
import json
import uuid
import sqlite3
import logging
from datetime import datetime
from statistics import mean, stdev

logger = logging.getLogger('finance_risk_engine')

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.03  # 3% 年化无风险利率


# ──────────────────────────────────────────────────────────────
# SQL DDL / DML
# ──────────────────────────────────────────────────────────────

DDL_RISK_TABLE = """
CREATE TABLE IF NOT EXISTS mt_vault_risk_snapshot (
    risk_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    snap_date TEXT NOT NULL,
    var_95 REAL,
    cvar_95 REAL,
    sharpe REAL,
    calmar REAL,
    sortino REAL,
    win_rate REAL,
    profit_factor REAL,
    max_drawdown REAL,
    turnover REAL,
    beta REAL,
    risk_score REAL,
    risk_level TEXT,
    total_return REAL,
    annualized_return REAL,
    annualized_volatility REAL,
    trade_count INTEGER,
    up_days INTEGER,
    down_days INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(session_id, snap_date)
);
"""

DDL_RISK_INDEX = [
    "CREATE INDEX IF NOT EXISTS idx_risk_session ON mt_vault_risk_snapshot(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_risk_date ON mt_vault_risk_snapshot(snap_date)",
]


# ──────────────────────────────────────────────────────────────
# RiskEngine 类
# ──────────────────────────────────────────────────────────────

class RiskEngine:
    """银行级 10 维风控引擎."""

    def __init__(self, db_path=None):
        if db_path is None:
            # 自动定位数据库
            candidates = [
                os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
                os.path.join(os.getcwd(), 'database', 'app.db'),
            ]
            db_path = next((p for p in candidates if os.path.exists(p)), candidates[0])
        self.db_path = os.path.abspath(db_path)
        self._ensure_tables()

    # ── DB helpers ──────────────────────────────────────

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_tables(self):
        conn = self._connect()
        try:
            conn.executescript(DDL_RISK_TABLE)
            for idx in DDL_RISK_INDEX:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        finally:
            conn.close()

    # ── 指标计算 ────────────────────────────────────────

    @staticmethod
    def _percentile(data: list, pct: float) -> float:
        """线性插值百分位 (Python 3.8+ 无 numpy 依赖)."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        n = len(sorted_data)
        k = (n - 1) * pct
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    @staticmethod
    def _cagr(start_value: float, end_value: float, days: int) -> float:
        """年化复合收益率 (近似)."""
        if start_value <= 0 or days <= 0:
            return 0.0
        years = days / TRADING_DAYS_PER_YEAR
        return ((end_value / start_value) ** (1 / years)) - 1 if years > 0 else 0.0

    # ── 核心: 单 session 风控计算 ────────────────────────

    def compute_session_risk(self, conn, session_id: str) -> dict:
        """
        计算单 session 的 10 个风控指标 + 综合评分, 并 UPSERT.
        返回结果 dict.
        """
        # 1) 获取 snapshots (按日期排序)
        snaps = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots "
            "WHERE session_id=? ORDER BY snap_date ASC",
            (session_id,)
        ).fetchall()

        if not snaps:
            return {'session_id': session_id, 'error': 'no snapshots', 'risk_score': 0, 'risk_level': 'UNKNOWN'}

        daily_returns = [float(s['daily_return'] or 0.0) for s in snaps]
        total_values = [float(s['total_value'] or 0.0) for s in snaps]
        max_dd_snap = max((float(s['max_drawdown'] or 0.0) for s in snaps), default=0.0)
        trade_counts = [int(s['trade_count'] or 0) for s in snaps]
        snap_dates = [s['snap_date'] for s in snaps]

        # 如果 daily_return 全是 0 (mock 数据), 用相邻 snapshot 的 total_value 变化推断收益率
        if all(abs(r) < 1e-8 for r in daily_returns) and len(total_values) >= 2:
            computed_returns = []
            for i in range(1, len(total_values)):
                if total_values[i-1] > 0:
                    r = total_values[i] / total_values[i-1] - 1
                    computed_returns.append(r)
                else:
                    computed_returns.append(0.0)
            # 第一个用 cumulative_return (如果有的话)
            first_cr = float(snaps[0]['cumulative_return'] or 0.0)
            if first_cr != 0:
                computed_returns.insert(0, first_cr)
            daily_returns = computed_returns if computed_returns else daily_returns

        # 2) 获取 trades
        trades = conn.execute(
            "SELECT * FROM mt_sandbox_trades WHERE session_id=?",
            (session_id,)
        ).fetchall()

        # 3) 获取 portfolio
        portfolio = conn.execute(
            "SELECT * FROM mt_sandbox_portfolio WHERE session_id=?",
            (session_id,)
        ).fetchone()

        # ── 基础统计 ──
        n = len(daily_returns)
        up_days = sum(1 for r in daily_returns if r > 0)
        down_days = sum(1 for r in daily_returns if r < 0)
        total_return = 0.0
        if total_values[0] > 0 and total_values[-1] > 0:
            total_return = (total_values[-1] / total_values[0]) - 1

        # 年化收益
        annualized_return = self._cagr(total_values[0], total_values[-1], n)

        # 年化波动率 (标准差 × sqrt(252))
        annualized_vol = stdev(daily_returns) * math.sqrt(TRADING_DAYS_PER_YEAR) if n > 1 else 0.0

        # ── R01 VaR 95% (历史模拟法) ──
        if daily_returns:
            var_95 = -self._percentile(daily_returns, 0.05) * math.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            var_95 = 0.0
        var_95 = max(0.0, var_95)  # VaR 取非负

        # ── R02 CVaR 95% (Expected Shortfall) ──
        if daily_returns:
            threshold = self._percentile(daily_returns, 0.05)
            tail_returns = [r for r in daily_returns if r <= threshold]
            cvar_95 = -mean(tail_returns) * math.sqrt(TRADING_DAYS_PER_YEAR) if tail_returns else var_95
        else:
            cvar_95 = 0.0
        cvar_95 = max(var_95, cvar_95)  # CVaR >= VaR

        # ── R03 夏普比率 ──
        excess_return = annualized_return - RISK_FREE_RATE
        sharpe = (excess_return / annualized_vol) if annualized_vol > 0 else (excess_return if annualized_vol == 0 and excess_return > 0 else 0.0)

        # ── R04 卡玛比率 ──
        calmar = (annualized_return / max_dd_snap) if max_dd_snap > 0 else 0.0

        # ── R05 索提诺比率 (只算下行波动) ──
        downside_returns = [r for r in daily_returns if r < 0]
        downside_vol = stdev(downside_returns) * math.sqrt(TRADING_DAYS_PER_YEAR) if len(downside_returns) > 1 else 0.0
        sortino = (excess_return / downside_vol) if downside_vol > 0 else (excess_return if downside_vol == 0 and excess_return > 0 else 0.0)

        # ── R06 胜率 / R07 盈亏比 ──
        # 用 trade 的 trade_date → 对应 snapshot 的 pnl 判断盈利
        trade_count = len(trades)
        win_rate = 0.0
        profit_factor = 0.0

        if trades:
            # 分组 buy / sell, 按 symbol 跟踪持仓均价
            avg_cost = {}  # symbol -> (total_cost, total_shares)
            realized_pnls = []
            trade_pnls = []

            for t in trades:
                sym = t['symbol']
                action = t['action'].upper()
                price = float(t['price'] or 0)
                shares = int(t['shares'] or 0)
                amount = float(t['total_amount'] or price * shares)

                if action == 'BUY':
                    prev_cost, prev_shares = avg_cost.get(sym, (0.0, 0))
                    new_cost = prev_cost + amount
                    new_shares = prev_shares + shares
                    avg_cost[sym] = (new_cost, new_shares)
                elif action == 'SELL':
                    prev_cost, prev_shares = avg_cost.get(sym, (0.0, 0))
                    if prev_shares > 0:
                        avg_price = prev_cost / prev_shares
                        realized = (price - avg_price) * min(shares, prev_shares)
                        realized_pnls.append(realized)
                        # 更新持仓
                        if shares >= prev_shares:
                            avg_cost.pop(sym, None)
                        else:
                            new_cost = avg_price * (prev_shares - shares)
                            avg_cost[sym] = (new_cost, prev_shares - shares)

            if realized_pnls:
                wins = [p for p in realized_pnls if p > 0]
                losses = [p for p in realized_pnls if p < 0]
                win_rate = len(wins) / len(realized_pnls) if realized_pnls else 0.0
                avg_win = mean(wins) if wins else 0.0
                avg_loss = abs(mean(losses)) if losses else 0.0
                profit_factor = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        # ── R08 最大回撤 (直接读 + 重算验证) ──
        # 重新计算回撤序列
        computed_dd = 0.0
        peak = total_values[0] if total_values else 0.0
        for v in total_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > computed_dd:
                computed_dd = dd
        max_drawdown = max(max_dd_snap, computed_dd)

        # ── R09 换手率 ──
        avg_total_assets = mean(total_values) if total_values else 1.0
        if avg_total_assets > 0:
            total_turnover = sum(float(t['total_amount'] or 0) for t in trades)
            turnover = total_turnover / avg_total_assets
        else:
            turnover = 0.0

        # ── R10 Beta (相对于沪深300) ──
        # 简化: 由于无沪深300实际数据, 用 1.0 作为基准 beta
        # 可扩展: 若有 market_return 时间序列, 可用 OLS slope 计算
        beta = 1.0

        # ── 综合风险评分 (0-100) ──
        # VaR, Sharpe, MaxDD, WinRate, Turnover 五大维度
        risk_score = self._compute_risk_score(
            var_95=var_95, sharpe=sharpe, max_dd=max_drawdown,
            win_rate=win_rate, turnover=turnover
        )
        risk_level = self._risk_level(risk_score)

        # ── 取最新 snap_date ──
        snap_date = snap_dates[-1] if snap_dates else datetime.now().strftime('%Y-%m-%d')

        # ── 写入 DB ──
        risk_id = f"R-{session_id}-{snap_date.replace('-','')}"
        conn.execute("""
            INSERT INTO mt_vault_risk_snapshot
                (risk_id, session_id, snap_date,
                 var_95, cvar_95, sharpe, calmar, sortino,
                 win_rate, profit_factor, max_drawdown, turnover, beta,
                 risk_score, risk_level,
                 total_return, annualized_return, annualized_volatility,
                 trade_count, up_days, down_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, snap_date) DO UPDATE SET
                var_95=excluded.var_95, cvar_95=excluded.cvar_95,
                sharpe=excluded.sharpe, calmar=excluded.calmar, sortino=excluded.sortino,
                win_rate=excluded.win_rate, profit_factor=excluded.profit_factor,
                max_drawdown=excluded.max_drawdown, turnover=excluded.turnover,
                beta=excluded.beta, risk_score=excluded.risk_score,
                risk_level=excluded.risk_level,
                total_return=excluded.total_return,
                annualized_return=excluded.annualized_return,
                annualized_volatility=excluded.annualized_volatility,
                trade_count=excluded.trade_count,
                up_days=excluded.up_days, down_days=excluded.down_days
        """, (
            risk_id, session_id, snap_date,
            var_95, cvar_95, sharpe, calmar, sortino,
            win_rate, profit_factor, max_drawdown, turnover, beta,
            risk_score, risk_level,
            total_return, annualized_return, annualized_vol,
            trade_count, up_days, down_days,
        ))
        conn.commit()

        return {
            'session_id': session_id,
            'snap_date': snap_date,
            'var_95': var_95, 'cvar_95': cvar_95,
            'sharpe': sharpe, 'calmar': calmar, 'sortino': sortino,
            'win_rate': win_rate, 'profit_factor': profit_factor,
            'max_drawdown': max_drawdown, 'turnover': turnover, 'beta': beta,
            'total_return': total_return,
            'annualized_return': annualized_return,
            'annualized_volatility': annualized_vol,
            'trade_count': trade_count,
            'up_days': up_days, 'down_days': down_days,
            'risk_score': risk_score,
            'risk_level': risk_level,
        }

    # ── 综合评分算法 ──────────────────────────────────

    @staticmethod
    def _compute_risk_score(var_95, sharpe, max_dd, win_rate, turnover):
        """
        综合风险评分 (0-100), 数学加权非任意.

        得分越高 → 风险越低 (越安全).

        归一化权重:
            VaR       30%   低 VaR → 高得分
            Sharpe    20%   高 Sharpe → 高得分
            MaxDD     20%   低 MaxDD → 高得分
            WinRate   15%   高胜率 → 高得分
            Turnover  15%   适度换手率 (0.2-1.0) → 高得分, 过高过低都扣分
        """
        # VaR: 0.00 → 100分, 0.10 (10%) → 0分
        var_score = max(0.0, min(100.0, (0.10 - var_95) / 0.10 * 100))

        # Sharpe: -2 → 0分, 0 → 50分, 2 → 100分
        if sharpe <= -2:
            sharpe_score = 0.0
        elif sharpe <= 0:
            sharpe_score = 50 * (sharpe + 2) / 2
        elif sharpe <= 2:
            sharpe_score = 50 + 50 * sharpe / 2
        else:
            sharpe_score = 100.0

        # MaxDD: 0.00 → 100分, 0.30 (30%) → 0分
        dd_score = max(0.0, min(100.0, (0.30 - max_dd) / 0.30 * 100))

        # WinRate: 0 → 0分, 0.5 → 50分, 0.7 → 100分, >0.7 → 封顶
        wr_score = max(0.0, min(100.0, win_rate * 142.86))  # 0.7 → 100

        # Turnover: 0 → 50分, 0.5 → 100分, 2.0 → 0分 (过高过低都差)
        if turnover <= 0.5:
            to_score = 50 + turnover * 100
        elif turnover <= 2.0:
            to_score = 100 - (turnover - 0.5) * 66.67
        else:
            to_score = 0.0

        # 加权求和
        score = (
            var_score * 0.30 +
            sharpe_score * 0.20 +
            dd_score * 0.20 +
            wr_score * 0.15 +
            to_score * 0.15
        )
        return round(score, 2)

    @staticmethod
    def _risk_level(score: float) -> str:
        """按综合得分划分风险等级."""
        if score >= 75:
            return 'LOW'
        elif score >= 55:
            return 'MEDIUM'
        elif score >= 35:
            return 'HIGH'
        else:
            return 'CRITICAL'

    # ── 批量计算 ────────────────────────────────────────

    def compute_all(self, session_ids=None) -> dict:
        """
        计算所有 session 或指定 session 的风控.
        返回 {session_id: result_dict}.
        """
        conn = self._connect()
        results = {}
        try:
            if session_ids is None:
                rows = conn.execute(
                    "SELECT DISTINCT session_id FROM mt_sandbox_snapshots"
                ).fetchall()
                session_ids = [r['session_id'] for r in rows]

            for sid in session_ids:
                try:
                    r = self.compute_session_risk(conn, sid)
                    results[sid] = r
                    risk_score = r.get('risk_score', 0) or 0
                    risk_level = r.get('risk_level', 'UNKNOWN')
                    logger.info(f"[RISK] {sid[:12]} score={risk_score:.0f} "
                                f"level={risk_level} "
                                f"VaR95={r.get('var_95',0):.2%} Sharpe={r.get('sharpe',0):.2f}")

                    # ── 🎛️ TriggerCoordinator 事件桥接 ──
                    # risk_level ∈ {CRITICAL, HIGH} → emit RISK_BREACH
                    if risk_level in ('CRITICAL', 'HIGH') and risk_score >= 70:
                        try:
                            from engines.trigger_coordinator import TriggerCoordinator
                            TriggerCoordinator().fire(
                                'RISK_BREACH', source='finance_risk_engine',
                                payload={
                                    'session_id': sid,
                                    'risk_score': risk_score,
                                    'risk_level': risk_level,
                                    'var_95': r.get('var_95'),
                                    'max_drawdown': r.get('max_drawdown'),
                                    'sharpe': r.get('sharpe'),
                                    'total_return': r.get('total_return'),
                                },
                                severity='CRITICAL' if risk_level == 'CRITICAL' else 'HIGH',
                            )
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"[RISK] {sid} 计算失败: {e}")
                    results[sid] = {'session_id': sid, 'error': str(e), 'risk_score': 0, 'risk_level': 'ERROR'}
        finally:
            conn.close()

        return results


# ──────────────────────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    re = RiskEngine(db_path)
    results = re.compute_all()

    print(f"\n✅ 风控引擎完成. {len(results)} sessions.")
    print("-" * 80)
    print(f"{'Session':14s} {'Score':>6s} {'Level':8s} {'VaR95':>8s} {'Sharpe':>8s} {'MaxDD':>8s} {'WinRate':>8s} {'AnnualRet':>10s}")
    print("-" * 80)
    for sid, r in sorted(results.items(), key=lambda x: -x[1].get('risk_score', 0)):
        if 'error' in r:
            print(f"{sid[:12]:14s} ERROR: {r['error']}")
            continue
        print(
            f"{sid[:12]:14s} "
            f"{r['risk_score']:>5.1f} "
            f"{r['risk_level']:8s} "
            f"{r['var_95']:>7.2%} "
            f"{r['sharpe']:>7.2f} "
            f"{r['max_drawdown']:>7.2%} "
            f"{r['win_rate']:>7.1%} "
            f"{r['annualized_return']:>9.2%}"
        )


# ═══════════════════════════════════════════════════════════════════════
# 🎛️ TriggerCoordinator 桥接模块级函数
# ═══════════════════════════════════════════════════════════════════════
def incremental_risk(payload: dict = None):
    """单笔交易触发 → 增量风控重算

    TriggerCoordinator.fire('TRADE_EXECUTED') 时调用.
    """
    payload = payload or {}
    try:
        re = RiskEngine()
        conn = re._connect()
        # 增量: 只重算有 trades 的 session (避免全量)
        session_rows = conn.execute(
            "SELECT DISTINCT session_id FROM mt_sandbox_trades "
            "ORDER BY rowid DESC LIMIT 5"
        ).fetchall()
        conn.close()
        sids = [r['session_id'] for r in session_rows]
        results = {}
        for sid in sids:
            try:
                conn = re._connect()
                results[sid] = re.compute_session_risk(conn, sid)
                conn.close()
            except Exception as e:
                results[sid] = {"error": str(e)}
        return {"ok": True, "sessions_updated": len(sids), "results": {k: {"risk_score": v.get('risk_score'), "risk_level": v.get('risk_level')} for k, v in results.items() if isinstance(v, dict)}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == '__main__':
    main()
