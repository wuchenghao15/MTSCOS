#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finance_attribution.py — 古灵阁银行业绩归因引擎
====================================================
L1 Brinson 行业归因: allocation/selection/interaction effect
L2 交易归因: 每笔 trade 对 PnL 的贡献
L3 信号归因: signal_score 与实际收益的 IC (Spearman 秩相关)
L4 时间归因: 按周/月统计收益贡献

用法:
    from engines.finance_attribution import AttributionEngine
    ae = AttributionEngine('database/app.db')
    ae.compute_all()
"""

import os
import sys
import math
import json
import uuid
import sqlite3
import logging
from datetime import datetime
from collections import defaultdict
from statistics import mean

logger = logging.getLogger('finance_attribution')


# ──────────────────────────────────────────────────────────────
# Symbol → 行业映射 (硬编码 Top 100)
# ──────────────────────────────────────────────────────────────

SYMBOL_INDUSTRY = {
    # 白酒
    'sh600519': '白酒', 'sz000858': '白酒', 'sh600568': '白酒', 'sz000568': '白酒',
    'sz000799': '白酒', 'sh603589': '白酒', 'sh600809': '白酒',
    # 保险 / 银行
    'sh601318': '保险', 'sh601628': '保险', 'sh601601': '保险', 'sh601336': '保险',
    'sh601398': '银行', 'sh600036': '银行', 'sz000001': '银行', 'sh601288': '银行',
    'sh601939': '银行', 'sh601988': '银行', 'sh600016': '银行', 'sh601166': '银行',
    'sh600000': '银行', 'sz002142': '银行',
    # 新能源汽车
    'sz002594': '新能源汽车', 'sh601127': '新能源汽车', 'sz300750': '新能源汽车',
    'sz002460': '新能源汽车', 'sh600104': '新能源汽车', 'sz002812': '新能源汽车',
    # 有色金属 / 资源
    'sh601899': '有色金属', 'sh600547': '有色金属', 'sz002415': '半导体',
    'sh601012': '光伏', 'sh600438': '光伏', 'sz002459': '光伏',
    # 医药
    'sh600276': '医药', 'sz300760': '医药', 'sz300015': '医药',
    'sh600196': '医药', 'sz000538': '医药', 'sh600085': '医药', 'sz002007': '医药',
    # 科技 / 半导体 / 软件
    'sz300059': '软件', 'sz300033': '软件', 'sz002230': '软件',
    'sz002415': '半导体', 'sh603986': '半导体', 'sz002049': '半导体',
    'sh600584': '半导体', 'sz300661': '半导体',
    # 消费 / 免税 / 家电
    'sh601888': '免税', 'sz000333': '家电', 'sz000651': '家电',
    'sh600690': '家电', 'sz002508': '家电', 'sh600315': '家电',
    # 电力 / 能源
    'sh600900': '电力', 'sh601985': '电力', 'sh600025': '电力', 'sh600886': '电力',
    'sh601088': '能源', 'sh601857': '能源', 'sh600028': '能源', 'sh601808': '能源',
    # 饲料 / 农业
    'sz002475': '饲料', 'sz000876': '饲料', 'sz002311': '饲料',
    'sh600438': '农业', 'sz002234': '农业',
    # 军工
    'sz000768': '军工', 'sh600893': '军工', 'sz002179': '军工', 'sh600760': '军工',
    # 地产
    'sz000002': '地产', 'sh600048': '地产', 'sz001979': '地产',
    # 建材 / 基建
    'sh600585': '建材', 'sz000401': '建材', 'sh600801': '建材',
    # 汽车
    'sh600104': '汽车', 'sz000625': '汽车', 'sh601127': '汽车',
    # 食品饮料
    'sz000858': '食品饮料', 'sh603288': '食品饮料', 'sz002714': '食品饮料',
    # 金融科技
    'sh601318': '金融科技', 'sz002230': '金融科技',
    # 传媒
    'sz002602': '传媒', 'sh601999': '传媒', 'sz300027': '传媒',
    # 通信
    'sh600050': '通信', 'sz000063': '通信', 'sh600498': '通信',
    # 交通运输
    'sh600029': '航空', 'sh601111': '航空', 'sz000089': '航空',
    'sh601006': '铁路', 'sh600009': '机场',
    # 机械设备
    'sz000157': '机械', 'sh600031': '机械', 'sz002008': '机械',
    # 化工
    'sh600309': '化工', 'sz000792': '化工', 'sh600989': '化工',
}
DEFAULT_INDUSTRY = '其他'


def get_industry(symbol: str) -> str:
    """symbol → 行业."""
    if not symbol:
        return DEFAULT_INDUSTRY
    return SYMBOL_INDUSTRY.get(symbol.lower(), SYMBOL_INDUSTRY.get(symbol, DEFAULT_INDUSTRY))


# ──────────────────────────────────────────────────────────────
# SQL DDL
# ──────────────────────────────────────────────────────────────

DDL_ATTR_TABLE = """
CREATE TABLE IF NOT EXISTS mt_vault_attribution (
    attr_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    attr_type TEXT NOT NULL,
    attr_date TEXT,
    symbol TEXT,
    industry TEXT,
    metric TEXT NOT NULL,
    value REAL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

DDL_ATTR_INDEX = [
    "CREATE INDEX IF NOT EXISTS idx_attr_session ON mt_vault_attribution(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_attr_type ON mt_vault_attribution(attr_type)",
    "CREATE INDEX IF NOT EXISTS idx_attr_date ON mt_vault_attribution(attr_date)",
]


# ──────────────────────────────────────────────────────────────
# AttributionEngine 类
# ──────────────────────────────────────────────────────────────

class AttributionEngine:
    """多维度业绩归因引擎."""

    def __init__(self, db_path=None):
        if db_path is None:
            candidates = [
                os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
                os.path.join(os.getcwd(), 'database', 'app.db'),
            ]
            db_path = next((p for p in candidates if os.path.exists(p)), candidates[0])
        self.db_path = os.path.abspath(db_path)
        self._ensure_tables()

    # ── DB ─────────────────────────────────────────────

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_tables(self):
        conn = self._connect()
        try:
            conn.executescript(DDL_ATTR_TABLE)
            for idx in DDL_ATTR_INDEX:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        finally:
            conn.close()

    def _upsert(self, conn, session_id, attr_type, attr_date, symbol, industry, metric, value, details=None):
        """写入归因记录."""
        attr_id = f"A-{session_id}-{attr_type}-{metric}-{symbol or 'ALL'}-{attr_date or 'ALL'}"
        attr_id = attr_id.replace(' ', '').replace('/', '_')[:120]
        try:
            conn.execute("""
                INSERT INTO mt_vault_attribution
                    (attr_id, session_id, attr_type, attr_date, symbol, industry, metric, value, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attr_id) DO UPDATE SET
                    value=excluded.value, details=excluded.details
            """, (
                attr_id, session_id, attr_type, attr_date, symbol, industry, metric,
                value, json.dumps(details or {}, ensure_ascii=False) if details else None,
            ))
        except Exception as e:
            logger.warning(f"_upsert error: {e}")

    # ── L1 Brinson 行业归因 ────────────────────────────

    def brinson_attribution(self, conn, session_id: str):
        """
        Brinson 行业归因:
            Allocation  Effect = (Wp - Wb) × Rb
            Selection   Effect = Wb × (Rp - Rb)
            Interaction Effect = (Wp - Wb) × (Rp - Rb)
            Rp = portfolio 行业收益率 (用 trades 推断)
            Rb = 基准收益率 (简化: 用 session 总收益作为 Rb)
            Wp = portfolio 行业权重
            Wb = 基准权重 (简化: 平均分配)
        """
        trades = conn.execute(
            "SELECT * FROM mt_sandbox_trades WHERE session_id=?", (session_id,)
        ).fetchall()
        snapshots = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots WHERE session_id=? ORDER BY snap_date", (session_id,)
        ).fetchall()

        if not snapshots:
            return None

        total_return = 0.0
        if len(snapshots) > 1:
            tv0 = float(snapshots[0]['total_value'] or 1)
            tv1 = float(snapshots[-1]['total_value'] or tv0)
            total_return = (tv1 / tv0 - 1) if tv0 > 0 else 0.0

        # 按行业聚合成交金额
        industry_buy = defaultdict(float)
        industry_sell = defaultdict(float)
        industry_symbols = defaultdict(set)

        for t in trades:
            sym = t['symbol']
            ind = get_industry(sym)
            amount = float(t['total_amount'] or 0)
            action = t['action'].upper()
            if action == 'BUY':
                industry_buy[ind] += amount
            elif action == 'SELL':
                industry_sell[ind] += amount
            industry_symbols[ind].add(sym)

        # 计算行业权重和收益贡献
        total_buy = sum(industry_buy.values()) or 1.0
        total_sell = sum(industry_sell.values()) or 1.0
        industry_contributions = {}

        industries = set(list(industry_buy.keys()) + list(industry_sell.keys()))
        n_industries = max(len(industries), 1)

        for ind in industries:
            wp = (industry_buy[ind] / total_buy) if total_buy > 0 else 0.0
            wb = 1.0 / n_industries  # 等权基准

            # Rp: 行业的净交易收益 (近似)
            ind_net = industry_sell[ind] - industry_buy[ind]
            rp = (ind_net / max(industry_buy[ind], 1)) if industry_buy[ind] > 0 else 0.0
            rb = total_return  # session 总收益作基准

            allocation = (wp - wb) * rb
            selection = wb * (rp - rb)
            interaction = (wp - wb) * (rp - rb)
            total_effect = allocation + selection + interaction

            industry_contributions[ind] = {
                'wp': wp, 'wb': wb,
                'rp': rp, 'rb': rb,
                'allocation': allocation,
                'selection': selection,
                'interaction': interaction,
                'total_effect': total_effect,
                'buy_amount': industry_buy[ind],
                'sell_amount': industry_sell[ind],
                'symbols': list(industry_symbols[ind]),
            }

            # 写入 DB
            details = industry_contributions[ind]
            for metric, val in [('allocation', allocation), ('selection', selection),
                                ('interaction', interaction), ('contribution', total_effect)]:
                self._upsert(
                    conn, session_id, 'INDUSTRY',
                    snapshots[-1]['snap_date'] if snapshots else None,
                    None, ind, metric, val, details={k: round(v, 6) if isinstance(v, float) else v
                                                     for k, v in details.items()}
                )

        conn.commit()
        return {
            'session_id': session_id,
            'total_return': total_return,
            'industries': industry_contributions,
        }

    # ── L2 交易归因 ────────────────────────────────────

    def trade_attribution(self, conn, session_id: str):
        """
        每笔 trade 对 PnL 的贡献.
            BUY → 记录成本价 + 数量
            SELL → realized_pnl = (sell_price - avg_cost) × qty
            HOLD (未卖出) → 用最新 snapshot 价格估值 unrealized
        """
        trades = conn.execute(
            "SELECT * FROM mt_sandbox_trades WHERE session_id=? ORDER BY trade_date",
            (session_id,)
        ).fetchall()
        snapshots = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots WHERE session_id=? ORDER BY snap_date",
            (session_id,)
        ).fetchall()

        avg_cost = {}  # symbol -> (total_cost, total_shares, trades_list)
        trade_pnls = []
        realized_total = 0.0

        for t in trades:
            sym = t['symbol']
            ind = get_industry(sym)
            trade_id = t['trade_id']
            action = t['action'].upper()
            price = float(t['price'] or 0)
            shares = int(t['shares'] or 0)
            amount = float(t['total_amount'] or price * shares)
            signal_score = float(t['signal_score'] or 0)
            trade_date = t['trade_date']

            entry = {
                'trade_id': trade_id,
                'symbol': sym,
                'industry': ind,
                'action': action,
                'price': price,
                'shares': shares,
                'amount': amount,
                'signal_score': signal_score,
                'trade_date': trade_date,
            }

            if action == 'BUY':
                prev_cost, prev_shares = avg_cost.get(sym, (0.0, 0))
                new_cost = prev_cost + amount
                new_shares = prev_shares + shares
                avg_cost[sym] = (new_cost, new_shares)
                entry['pnl'] = 0.0  # BUY 不产生 PnL
                entry['pnl_type'] = 'BUY_COST'
                self._upsert(
                    conn, session_id, 'TRADE', trade_date, sym, ind,
                    'contribution', 0.0, details=entry
                )

            elif action == 'SELL':
                prev_cost, prev_shares = avg_cost.get(sym, (0.0, 0))
                if prev_shares > 0 and shares > 0:
                    avg_buy_price = prev_cost / prev_shares
                    sell_shares = min(shares, prev_shares)
                    realized = (price - avg_buy_price) * sell_shares
                    realized_total += realized

                    # 更新持仓
                    if shares >= prev_shares:
                        avg_cost.pop(sym, None)
                    else:
                        new_cost = avg_buy_price * (prev_shares - shares)
                        avg_cost[sym] = (new_cost, prev_shares - shares)

                    entry['avg_buy_price'] = avg_buy_price
                    entry['pnl'] = realized
                    entry['pnl_type'] = 'REALIZED'
                    entry['pnl_pct'] = (price / avg_buy_price - 1) if avg_buy_price > 0 else 0.0
                else:
                    entry['pnl'] = 0.0
                    entry['pnl_type'] = 'NO_POSITION'
                    realized = 0.0

                trade_pnls.append(entry)
                self._upsert(
                    conn, session_id, 'TRADE', trade_date, sym, ind,
                    'contribution', entry['pnl'], details=entry
                )

        conn.commit()
        return {
            'session_id': session_id,
            'total_realized_pnl': realized_total,
            'trade_count': len(trades),
            'trades': trade_pnls,
        }

    # ── L3 信号归因 (IC) ──────────────────────────────

    def signal_attribution(self, conn, session_id: str):
        """
        signal_score 与实际后续收益的 IC (Spearman 秩相关).
        简化: 按 symbol 聚合, 比较信号得分 vs 对应股票交易盈亏.
        """
        signals = conn.execute(
            "SELECT * FROM mt_sandbox_signals WHERE session_id=?", (session_id,)
        ).fetchall()
        trades = conn.execute(
            "SELECT * FROM mt_sandbox_trades WHERE session_id=?", (session_id,)
        ).fetchall()

        if not signals:
            return None

        # 按 symbol 聚合平均信号得分
        symbol_scores = defaultdict(list)
        for s in signals:
            symbol_scores[s['symbol']].append(float(s['score'] or 0))

        symbol_avg_score = {sym: mean(scores) for sym, scores in symbol_scores.items()}

        # 按 symbol 聚合交易 PnL
        avg_cost = {}
        symbol_realized = defaultdict(float)
        for t in trades:
            sym = t['symbol']
            action = t['action'].upper()
            price = float(t['price'] or 0)
            shares = int(t['shares'] or 0)
            amount = float(t['total_amount'] or 0)
            if action == 'BUY':
                prev_cost, prev_shares = avg_cost.get(sym, (0.0, 0))
                avg_cost[sym] = (prev_cost + amount, prev_shares + shares)
            elif action == 'SELL':
                prev_cost, prev_shares = avg_cost.get(sym, (0.0, 0))
                if prev_shares > 0:
                    avg_price = prev_cost / prev_shares
                    realized = (price - avg_price) * min(shares, prev_shares)
                    symbol_realized[sym] += realized
                    if shares >= prev_shares:
                        avg_cost.pop(sym, None)
                    else:
                        avg_cost[sym] = (avg_price * (prev_shares - shares), prev_shares - shares)

        # 准备配对数据: (signal_score, realized_pnl)
        pairs = []
        for sym in set(list(symbol_avg_score.keys()) + list(symbol_realized.keys())):
            score = symbol_avg_score.get(sym, 0)
            pnl = symbol_realized.get(sym, 0)
            pairs.append((sym, score, pnl))

        if len(pairs) < 3:
            return None

        # Spearman 秩相关
        scores_ranked = self._rank([p[1] for p in pairs])
        pnls_ranked = self._rank([p[2] for p in pairs])
        n = len(pairs)
        d_sq_sum = sum((s - p) ** 2 for s, p in zip(scores_ranked, pnls_ranked))
        rho = 1 - (6 * d_sq_sum) / (n * (n ** 2 - 1)) if n > 1 else 0.0

        # 写入 DB
        attr_date = datetime.now().strftime('%Y-%m-%d')
        self._upsert(
            conn, session_id, 'SIGNAL', attr_date, None, None,
            'ic', rho, details={
                'n_pairs': n,
                'd_sq_sum': d_sq_sum,
                'pairs': [{'symbol': p[0], 'score': p[1], 'pnl': round(p[2], 2)} for p in pairs],
            }
        )

        conn.commit()
        return {
            'session_id': session_id,
            'ic': rho,
            'n_pairs': n,
            'pairs': [{'symbol': p[0], 'score': p[1], 'pnl': round(p[2], 2)} for p in pairs],
        }

    @staticmethod
    def _rank(values: list) -> list:
        """计算秩 (处理并列)."""
        n = len(values)
        indexed = sorted(enumerate(values), key=lambda x: x[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j) / 2 + 1  # 平均秩 (从 1 开始)
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    # ── L4 时间归因 (按周/月) ──────────────────────────

    def time_attribution(self, conn, session_id: str):
        """按周/月统计收益贡献."""
        snapshots = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots WHERE session_id=? ORDER BY snap_date",
            (session_id,)
        ).fetchall()

        if not snapshots:
            return None

        weekly = defaultdict(float)
        monthly = defaultdict(float)
        daily_pnl = defaultdict(float)

        for s in snapshots:
            date_str = s['snap_date']
            tv = float(s['total_value'] or 0)
            pnl = float(s['pnl_amount'] or 0)

            # 周: ISO week
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                iso_year, iso_week, _ = dt.isocalendar()
                week_key = f"{iso_year}-W{iso_week:02d}"
                month_key = date_str[:7]
            except Exception:
                week_key = 'Unknown'
                month_key = 'Unknown'

            weekly[week_key] += pnl
            monthly[month_key] += pnl
            daily_pnl[date_str] = tv

        attr_date = snapshots[-1]['snap_date'] if snapshots else datetime.now().strftime('%Y-%m-%d')

        for period, pnl in monthly.items():
            self._upsert(
                conn, session_id, 'TIME', attr_date, None, None,
                'monthly_pnl', pnl, details={'period': period}
            )
        for period, pnl in weekly.items():
            self._upsert(
                conn, session_id, 'TIME', attr_date, None, None,
                'weekly_pnl', pnl, details={'period': period}
            )

        conn.commit()
        return {
            'session_id': session_id,
            'monthly_pnl': dict(monthly),
            'weekly_pnl': dict(weekly),
        }

    # ── 批量计算 ────────────────────────────────────────

    def compute_all(self, session_ids=None) -> dict:
        """对所有 session 执行 4 维归因."""
        conn = self._connect()
        summary = {
            'industry_sessions': 0,
            'trade_count': 0,
            'industry_pnl': defaultdict(float),
            'best_trade': {},
            'worst_trade': {},
            'signal_ics': {},
            'session_count': 0,
        }
        try:
            if session_ids is None:
                rows = conn.execute(
                    "SELECT DISTINCT session_id FROM mt_sandbox_snapshots"
                ).fetchall()
                session_ids = [r['session_id'] for r in rows]

            for sid in session_ids:
                summary['session_count'] += 1
                try:
                    br = self.brinson_attribution(conn, sid)
                    if br:
                        summary['industry_sessions'] += 1
                        for ind, info in br['industries'].items():
                            summary['industry_pnl'][ind] += info.get('total_effect', 0)

                    tr = self.trade_attribution(conn, sid)
                    if tr:
                        summary['trade_count'] += tr['trade_count']
                        for t in tr['trades']:
                            if t.get('pnl_type') == 'REALIZED':
                                best = summary['best_trade']
                                worst = summary['worst_trade']
                                if not best or t['pnl'] > best.get('pnl', -1e18):
                                    summary['best_trade'] = t
                                if not worst or t['pnl'] < worst.get('pnl', 1e18):
                                    summary['worst_trade'] = t

                    sg = self.signal_attribution(conn, sid)
                    if sg:
                        summary['signal_ics'][sid] = sg['ic']

                    tm = self.time_attribution(conn, sid)

                    logger.info(f"[ATTRIBUTION] {sid[:12]} Brinson={br is not None} "
                                f"Trades={tr['trade_count'] if tr else 0} "
                                f"IC={sg['ic'] if sg else 'N/A'}")
                except Exception as e:
                    logger.error(f"[ATTRIBUTION] {sid} 失败: {e}")

        finally:
            conn.close()

        # 把 defaultdict 转普通 dict
        summary['industry_pnl'] = dict(summary['industry_pnl'])
        return summary


# ──────────────────────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    ae = AttributionEngine(db_path)
    result = ae.compute_all()

    print(f"\n✅ 归因引擎完成. {result['session_count']} sessions.")
    print(f"\n📊 Brinson 行业归因 ({result['industry_sessions']} sessions):")
    print("-" * 60)
    for ind, val in sorted(result['industry_pnl'].items(), key=lambda x: -abs(x[1]))[:10]:
        sign = '🟢' if val >= 0 else '🔴'
        print(f"  {sign} {ind:12s} {val:+,.0f}")

    print(f"\n📈 交易归因 ({result['trade_count']} trades):")
    bt = result['best_trade']
    wt = result['worst_trade']
    if bt:
        print(f"  🏆 最佳: {bt['symbol']} ({bt.get('industry','')}) "
              f"BUY@{bt.get('avg_buy_price',0):.2f} → SELL@{bt['price']:.2f} "
              f"PnL={bt['pnl']:+,.2f} ({bt.get('pnl_pct',0):+.1%})")
    if wt and wt.get('pnl', 0) != bt.get('pnl', 1):
        print(f"  💀 最差: {wt['symbol']} ({wt.get('industry','')}) "
              f"BUY@{wt.get('avg_buy_price',0):.2f} → SELL@{wt['price']:.2f} "
              f"PnL={wt['pnl']:+,.2f} ({wt.get('pnl_pct',0):+.1%})")

    print(f"\n🎯 信号归因 IC (Spearman):")
    print("-" * 60)
    for sid, ic in sorted(result['signal_ics'].items(), key=lambda x: -x[1]):
        bar = '█' * int(abs(ic) * 20)
        print(f"  {sid[:12]} IC={ic:+.3f} {bar}")


# ═══════════════════════════════════════════════════════════════════════
# 🎛️ TriggerCoordinator 桥接模块级函数
# ═══════════════════════════════════════════════════════════════════════
def incremental_attribution(payload: dict = None):
    """单笔交易触发 → 增量归因重算

    TriggerCoordinator.fire('TRADE_EXECUTED') 时调用.
    """
    payload = payload or {}
    try:
        ae = AttributionEngine()
        conn = ae._connect()
        session_rows = conn.execute(
            "SELECT DISTINCT session_id FROM mt_sandbox_trades "
            "ORDER BY rowid DESC LIMIT 5"
        ).fetchall()
        conn.close()
        sids = [r['session_id'] for r in session_rows]
        results = {}
        for sid in sids:
            try:
                conn = ae._connect()
                results[sid] = ae.trade_attribution(conn, sid)
                conn.close()
            except Exception as e:
                results[sid] = {"error": str(e)}
        return {"ok": True, "sessions_updated": len(sids),
                "symbol": payload.get('symbol', '?')}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == '__main__':
    main()
