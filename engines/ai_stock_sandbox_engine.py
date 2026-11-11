#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股市沙盘模拟投资引擎 (Stock Sandbox Trading Engine)
═══════════════════════════════════════════════════════════════
flow: flow_stock_sandbox_20261102

## 设计原则
1. **真实行情驱动**: 新浪实时行情 (hq.sinajs.cn) + 日线K线回测
2. **可审计交易流水**: 每笔显式记录 date/name/price/fee/source
3. **多策略矩阵**: 超短线(T+0候选→T+1), 短线, 中线, 长线
4. **风控底线**: 亏损 5% 熔断, 单日回撤 3% 暂停交易
5. **团队协作**: 三专家投票 + 风控审查 + 审计归档
6. **自动投喂**: 定时 tick + 协作总线事件触发 → 自动调仓/分析
7. **对接大厅**: 每笔交易 → mt_task_hall 任务闭环

## 配置
- 初始本金: 10,000 元
- 模拟时长: 一周(10个交易日) + 一年(244个交易日)
- 风控底线: 最大亏损 5% (9,500 元强平)
- 佣金: 万 3 (最低 5 元)
- 印花税: 卖出千 1
- 交易规则: A 股 T+1, 涨跌停 ±10%, 最小 100 股

## DB 表
- mt_sandbox_portfolio    — 沙盘组合 (session + 现金 + 持仓)
- mt_sandbox_trades       — 交易流水 (可审计)
- mt_sandbox_snapshots    — 每日快照 (净值曲线)
- mt_sandbox_signals      — 策略信号池 (选股理由)
- mt_sandbox_team_verdicts — 专家/风控/审计投票

## 策略类型
- momentum_breakout   动量突破 (超短线, 1-3天)
- mean_reversion      均值回归 (短线, 3-7天)
- trend_following     趋势跟随 (中线, 1-4周)
- fundamental_value   价值投资 (长线, 1-6月)
- panel_effect        板块联动 (动态轮动)

## 多市场覆盖
- A 股 (sh/sz) — 主力
- 美股 (us) — 辅助判断 (纳指/道指/标普)
- B 股/S 股 — 可选扩展
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
import time
import threading
import hashlib
import random
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
# §0 路径 & DB & 常量
# ═══════════════════════════════════════════════════════════════════
BASE = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get('MTSCOS_DB_PATH') or str(BASE / "database" / "app.db")

# 核心配置
INITIAL_CASH = 10000.0          # 初始本金
RISK_FLOOR_PCT = 5.0            # 底线亏损 5% → 9,500 元熔断
DAILY_RISK_PCT = 3.0            # 单日回撤 3% → 暂停交易
MAX_SINGLE_POSITION_PCT = 60.0  # 单票仓位上限 (原 30%: 1万本金买一手 54 元票即 54%, 会被永久 veto)
COMMISSION_RATE = 0.0003        # 佣金万 3
COMMISSION_MIN = 5.0            # 最低佣金 5 元
STAMP_TAX_RATE = 0.001          # 印花税千 1 (仅卖出)
MIN_LOT = 100                   # A 股最小交易单位 100 股
LIMIT_UP_PCT = 0.10             # 涨停 10%
LIMIT_DOWN_PCT = -0.10          # 跌停 -10%

# 模拟时长（交易日数量）
WEEK_TRADING_DAYS = 10          # 一周 ≈ 10 个交易日
YEAR_TRADING_DAYS = 244         # 一年 ≈ 244 个交易日

# 交易时段 (简化: 全天视为可交易, 实际 A 股 9:30-11:30 + 13:00-15:00)
MARKET_OPEN_HOURS = (9.5, 15.0)  # 9:30 - 15:00 (十进制小时)

# 关注的核心标的池
WATCH_LIST_A = [
    ("sh600519", "贵州茅台", "消费白酒", "large_cap"),
    ("sz300750", "宁德时代", "新能源", "large_cap"),
    ("sh601318", "中国平安", "金融保险", "large_cap"),
    ("sz002594", "比亚迪", "新能源汽车", "large_cap"),
    ("sh600036", "招商银行", "银行", "large_cap"),
    ("sz000858", "五粮液", "消费白酒", "large_cap"),
    ("sh000001", "上证指数", "大盘指数", "index"),
    ("sz399006", "创业板指", "成长指数", "index"),
]
WATCH_LIST_US = [
    ("gb_dji", "道琼斯", "美股大盘", "index"),
    ("gb_ixic", "纳斯达克", "美股科技", "index"),
    ("gb_inx", "标普500", "美股大盘", "index"),
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now().isoformat()


def _gen_id(prefix: str) -> str:
    raw = f"{prefix}-{time.time_ns()}-{os.getpid()}-{random.randint(0,9999)}"
    return f"{prefix}-{hashlib.md5(raw.encode()).hexdigest()[:12]}"


# ═══════════════════════════════════════════════════════════════════
# §1 DB 表初始化
# ═══════════════════════════════════════════════════════════════════
def ensure_sandbox_tables() -> None:
    """初始化沙盘 5 张核心表"""
    conn = _conn()
    try:
        # 表 1: 沙盘 session (一个沙盘实例)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_sandbox_portfolio (
                session_id      TEXT PRIMARY KEY,
                scenario        TEXT NOT NULL,       -- WEEK | YEAR | CUSTOM
                scenario_days   INTEGER NOT NULL,
                initial_cash    REAL NOT NULL,
                current_cash    REAL NOT NULL,
                positions_json  TEXT DEFAULT '[]',   -- [{symbol, name, shares, avg_cost, current_price}]
                risk_floor_pct  REAL DEFAULT 5.0,
                daily_risk_pct  REAL DEFAULT 3.0,
                daily_high_watermark REAL DEFAULT 0,
                is_frozen       INTEGER DEFAULT 0,   -- 风控熔断
                status          TEXT DEFAULT 'RUNNING',
                start_date      TEXT NOT NULL,
                current_date    TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # 表 2: 交易流水 (可审计)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_sandbox_trades (
                trade_id        TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                trade_date      TEXT NOT NULL,
                trade_time      TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                stock_name      TEXT NOT NULL,
                action          TEXT NOT NULL,       -- BUY | SELL
                shares          INTEGER NOT NULL,
                price           REAL NOT NULL,
                commission      REAL DEFAULT 0,
                stamp_tax       REAL DEFAULT 0,
                total_amount    REAL NOT NULL,
                strategy        TEXT,                -- 触发策略
                signal_score    REAL DEFAULT 0,      -- 信号强度 0-100
                team_verdict    TEXT DEFAULT 'CONSENSUS', -- 团队投票结果
                risk_ok         INTEGER DEFAULT 1,
                source          TEXT DEFAULT 'simulated', -- real_quote | backtest | manual
                hall_task_id    TEXT,                -- 关联大厅
                notes           TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # 表 3: 每日快照 (净值曲线)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_sandbox_snapshots (
                snap_id         TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                snap_date       TEXT NOT NULL,
                total_value     REAL NOT NULL,       -- 现金 + 持仓市值
                cash_value      REAL NOT NULL,
                position_value  REAL NOT NULL,
                daily_return    REAL DEFAULT 0,      -- 当日收益率 %
                cumulative_return REAL DEFAULT 0,    -- 累计收益率 %
                max_drawdown    REAL DEFAULT 0,      -- 最大回撤 %
                trade_count     INTEGER DEFAULT 0,
                notes           TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # 表 4: 策略信号池
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_sandbox_signals (
                signal_id       TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                signal_date     TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                stock_name      TEXT NOT NULL,
                signal_type     TEXT NOT NULL,       -- BULL | BEAR | HOLD
                strategy        TEXT NOT NULL,
                score           REAL NOT NULL,       -- 0-100
                reason          TEXT,                -- 选股理由
                payload         TEXT DEFAULT '{}',   -- 信号细节 JSON
                team_voted      INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        
        # 表 5: 团队投票
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_sandbox_team_verdicts (
                verdict_id      TEXT PRIMARY KEY,
                signal_id       TEXT NOT NULL,
                session_id      TEXT NOT NULL,
                expert_id       TEXT NOT NULL,       -- expert_1 | expert_2 | expert_3
                expert_role     TEXT NOT NULL,       -- 价值派 | 技术派 | 量化派
                verdict         TEXT NOT NULL,       -- BUY | SELL | HOLD
                confidence      REAL DEFAULT 0,      -- 0-100
                reasoning       TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        
        conn.commit()
        sys.stderr.write(f"[SANDBOX] ✅ 5 张核心表已就绪\n")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §2 行情数据源 (新浪实时 + 模拟行情)
# ═══════════════════════════════════════════════════════════════════
class MarketDataProvider:
    """
    市场数据提供者 (双路: 真实新浪 + 模拟行情兜底)
    
    真实行情: https://hq.sinajs.cn/list=sh600519,sz300750,...
    新浪返回格式 (gbk 编码):
      var hq_str_sh600519="贵州茅台,1688.00,1670.00,1685.50,1690.00,...";
      fields: name, open, prev_close, price, high, low, bid, ask, volume, turnover, ...
    """
    SINA_URL = "https://hq.sinajs.cn/list="
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ts = 0.0
        self._cache_ttl = 3.0  # 3s 缓存
        self._daily_anchor: Dict[str, float] = {}  # 模拟回测的基准价 (首日真实价)
    
    def invalidate_cache(self):
        """清缓存 (回测每天调一次, 强制重新拉/生成行情)"""
        self._cache.clear()
        self._cache_ts = 0.0
    
    def apply_daily_perturbation(self, day: int, volatility: float = 0.02) -> None:
        """
        给缓存里的行情注入日波动 (模拟回测专用)
        - 首日以真实行情为锚点
        - 后续每天基于锚点做 ±2% 随机游走 (板块联动: 大盘±1% 带个股)
        """
        for secid, q in self._cache.items():
            if secid not in self._daily_anchor:
                self._daily_anchor[secid] = q['price']
            
            anchor = self._daily_anchor[secid]
            # 基于 day + secid 的确定性随机 (同一个 day 同一个 secid 波动一致)
            rng = random.Random(f"{secid}_day{day}")
            
            # 大盘/指数波动小 (±0.8%), 个股波动大 (±2%)
            is_index = secid.startswith('sh000') or secid.startswith('sz399')
            daily_vol = 0.008 if is_index else volatility
            
            # 叠加趋势: 用 sin 函数制造微周期 (牛熊交替感)
            trend = math.sin(day / 12.0) * 0.005  # 12 天一个小周期
            noise = rng.gauss(0, daily_vol / 2)   # 高斯噪声
            
            new_change = trend + noise
            new_price = round(anchor * (1 + new_change), 2)
            
            # 更新行情
            q['prev_close'] = anchor
            q['price'] = new_price
            q['open'] = round(anchor * (1 + rng.uniform(-0.005, 0.005)), 2)
            q['high'] = round(max(q['open'], new_price) * (1 + abs(new_change) / 2), 2)
            q['low'] = round(min(q['open'], new_price) * (1 - abs(new_change) / 2), 2)
            q['change_pct'] = round(new_change * 100, 2)
            q['volume'] = int(q.get('volume', 5_000_000) * rng.uniform(0.7, 1.4))
            q['ts'] = _now_iso()
            q['source'] = f"sina_perturbed_day{day}"
            self._cache[secid] = q
    
    def fetch_realtime(self, secids: List[str]) -> Dict[str, Dict[str, Any]]:
        """拉取新浪实时行情 → {secid: {price, prev_close, open, high, low, volume, change_pct}}"""
        now = time.time()
        if now - self._cache_ts < self._cache_ttl and all(s in self._cache for s in secids):
            return {s: self._cache[s] for s in secids if s in self._cache}
        
        result = {}
        secid_list = ','.join(secids)
        url = f"{self.SINA_URL}{secid_list}"
        
        try:
            import urllib.request
            headers = {
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (MTSCOS-Sandbox)",
            }
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=3.0)
            raw = resp.read()
            text = raw.decode('gbk', errors='ignore')
            
            for line in text.strip().split('\n'):
                line = line.strip()
                if not line or '=' not in line:
                    continue
                match = re.match(r'var hq_str_(\w+)="(.+?)";', line)
                if not match:
                    continue
                secid = match.group(1)
                fields = match.group(2).split(',')
                if len(fields) < 32:
                    continue
                
                name = fields[0]
                open_p = float(fields[1]) if fields[1] else 0.0
                prev_close = float(fields[2]) if fields[2] else 0.0
                price = float(fields[3]) if fields[3] else 0.0
                high = float(fields[4]) if fields[4] else 0.0
                low = float(fields[5]) if fields[5] else 0.0
                volume = float(fields[8]) if fields[8] else 0.0
                turnover = float(fields[9]) if fields[9] else 0.0
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
                
                data = {
                    "secid": secid, "name": name,
                    "price": price, "prev_close": prev_close,
                    "open": open_p, "high": high, "low": low,
                    "change_pct": round(change_pct, 2),
                    "volume": volume, "turnover": turnover,
                    "ts": _now_iso(),
                    "source": "sina_realtime",
                }
                result[secid] = data
                self._cache[secid] = data
            
            self._cache_ts = now
            return result
            
        except Exception as e:
            # 网络失败 → 生成模拟行情 (不阻塞沙盘运行)
            sys.stderr.write(f"[SANDBOX] 新浪行情拉取失败, 用模拟行情兜底: {e}\n")
            return self._generate_simulation(secids, seed_based=False)
    
    def _generate_simulation(self, secids: List[str], seed_based: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        模拟行情生成器 (新浪不可用时兜底)
        用随机游走 + 板块联动 + 大盘惯性
        """
        result = {}
        now_str = _now_iso()
        
        # 大盘基准 (上证指数模拟)
        market_trend = random.uniform(-1.0, 1.0)  # -1% ~ +1%
        if any(s.startswith('sh000001') for s in secids):
            result['sh000001'] = {
                "secid": "sh000001", "name": "上证指数",
                "price": 3200.0 * (1 + market_trend/100),
                "prev_close": 3200.0, "open": 3200.0,
                "high": 3200.0 * (1 + abs(market_trend)/100 + 0.3/100),
                "low": 3200.0 * (1 - abs(market_trend)/100 - 0.3/100),
                "change_pct": round(market_trend, 2),
                "volume": 3_500_000_000, "turnover": 400_000_000_000,
                "ts": now_str, "source": "simulated",
            }
        
        for secid in secids:
            if secid in result:
                continue
            
            # 板块系数 (每只股票一个 beta)
            beta = random.uniform(0.7, 1.5)  # 0.7~1.5 倍大盘
            noise = random.uniform(-2.0, 2.0)  # 个股随机波动 ±2%
            change = market_trend * beta + noise
            
            # 基准价格 (根据 secid 类型)
            prev_price = 100.0
            if '519' in secid: prev_price = 1685.0
            elif '300750' in secid: prev_price = 210.0
            elif '1318' in secid: prev_price = 50.0
            elif '2594' in secid: prev_price = 245.0
            elif '036' in secid: prev_price = 35.0
            elif '858' in secid: prev_price = 140.0
            
            price = round(prev_price * (1 + change/100), 2)
            price = max(1.0, price)  # 最小 1 元
            
            # 涨跌停限制
            limit_up = prev_price * (1 + LIMIT_UP_PCT)
            limit_down = prev_price * (1 + LIMIT_DOWN_PCT)
            price = min(price, limit_up)
            price = max(price, limit_down)
            
            # 模拟名称
            name_map = {s[0]: s[1] for s in WATCH_LIST_A}
            name = name_map.get(secid, f"模拟{secid}")
            
            result[secid] = {
                "secid": secid, "name": name,
                "price": price, "prev_close": prev_price,
                "open": round(prev_price * (1 + random.uniform(-0.5, 0.5)/100), 2),
                "high": round(max(price, prev_price) * (1 + abs(change)/200), 2),
                "low": round(min(price, prev_price) * (1 - abs(change)/200), 2),
                "change_pct": round((price - prev_price)/prev_price * 100, 2),
                "volume": random.randint(100_000, 5_000_000),
                "turnover": random.randint(1_000_000, 50_000_000),
                "ts": now_str, "source": "simulated",
            }
        
        return result

    # ═══════════════════════════════════════════════════════════════════
    # 🆕 历史 K 线数据源 (baostock 主源 + AKShare 降级 + 本地 SQLite 缓存)
    # ═══════════════════════════════════════════════════════════════════
    def _ensure_history_cache(self, db_path: str) -> None:
        """确保历史 K 线本地缓存表存在"""
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mt_sandbox_history (
                    cache_key   TEXT PRIMARY KEY,   -- secid_start_end_hash
                    secid       TEXT NOT NULL,
                    start_date  TEXT NOT NULL,
                    end_date    TEXT NOT NULL,
                    data_json   TEXT NOT NULL,       -- [{"date","open","high","low","close","volume","turnover","change_pct"}]
                    source      TEXT NOT NULL,       -- baostock | akshare | fallback
                    fetched_at  TEXT NOT NULL,
                    row_count   INTEGER NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _secid_to_baostock(self, secid: str) -> str:
        """secid 格式转换: sh600519 → sh.600519, sz300750 → sz.300750"""
        if '.' in secid:
            return secid
        # sh600519 / sz300750
        if secid.startswith('sh') or secid.startswith('sz'):
            return f"{secid[:2]}.{secid[2:]}"
        return secid

    def _secid_to_akshare(self, secid: str) -> str:
        """secid → AKShare 格式: sh600519 → 600519"""
        if '.' in secid:
            secid = secid.split('.')[-1]
        if secid.startswith('sh') or secid.startswith('sz'):
            secid = secid[2:]
        return secid

    def fetch_history_baostock(self, secid: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        拉取 baostock 历史日线 (真实数据, 免费无限流, 前复权)
        
        返回: [{"date":"2024-01-02","open":1558.48,"high":1568.00,"low":1540.00,
                "close":1527.68,"volume":3500000,"turnover":5300000000,"change_pct":-2.37}, ...]
        """
        import baostock as bs
        
        lg = bs.login()
        if lg.error_code != '0':
            bs.logout()
            raise RuntimeError(f"baostock login failed: {lg.error_msg}")
        
        try:
            bs_code = self._secid_to_baostock(secid)
            # baostock 日期格式: YYYY-MM-DD
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,pctChg,tradestatus",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"  # 前复权
            )
            
            if rs.error_code != '0':
                raise RuntimeError(f"baostock query failed: {rs.error_msg}")
            
            rows = []
            while rs.next():
                raw = rs.get_row_data()
                if len(raw) < 9:
                    continue
                
                trade_status = raw[8]  # 1=交易, 0=停牌
                if trade_status != '1':
                    continue
                
                date = raw[0]
                open_p = float(raw[1])
                high = float(raw[2])
                low = float(raw[3])
                close = float(raw[4])
                volume = float(raw[5])
                turnover = float(raw[6]) if raw[6] else 0.0
                change_pct = float(raw[7]) if raw[7] else 0.0
                
                if close <= 0:
                    continue
                
                rows.append({
                    "date": date,
                    "open": round(open_p, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": int(volume),
                    "turnover": round(turnover, 2),
                    "change_pct": round(change_pct, 2),
                })
            
            return rows
        finally:
            bs.logout()

    def fetch_history_akshare(self, secid: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        降级: AKShare 历史日线 (非东方财富源, 限流风险较低)
        """
        import akshare as ak
        
        symbol = self._secid_to_akshare(secid)
        # AKShare 日期格式: YYYYMMDD
        start_fmt = start_date.replace('-', '')
        end_fmt = end_date.replace('-', '')
        
        # 判断个股还是指数
        is_index = secid.startswith('sh000') or secid.startswith('sz399')
        
        if is_index:
            # 指数历史
            df = ak.stock_zh_index_daily(symbol=f"{secid}.sh" if secid.startswith('sh') else f"{secid}.sz")
            # 按日期过滤
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
        else:
            # 个股历史 — 用 AKShare 新浪源 (非东方财富)
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=start_fmt, end_date=end_fmt,
                adjust="qfq"
            )
        
        rows = []
        for _, r in df.iterrows():
            date = str(r.get('date', ''))[:10]
            close = float(r.get('close', 0))
            if close <= 0 or not date:
                continue
            prev_close = float(r.get('open', close))
            rows.append({
                "date": date,
                "open": round(float(r.get('open', close)), 2),
                "high": round(float(r.get('high', close)), 2),
                "low": round(float(r.get('low', close)), 2),
                "close": round(close, 2),
                "volume": int(float(r.get('volume', 0))),
                "turnover": round(float(r.get('amount', 0)), 2),
                "change_pct": round(float(r.get('pct_chg', 0)), 2),
            })
        
        return rows

    def fetch_history_batch(self, secids: List[str], start_date: str, end_date: str,
                            cache_db_path: str = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        批量拉取历史日线 (baostock 主源 → AKShare 降级 → 显式 fallback)
        结果自动缓存到本地 SQLite, 避免重复拉取
        
        返回: {secid: [{"date","open","high","low","close","volume",...}, ...]}
        """
        import sqlite3, hashlib
        
        # 确定缓存路径 — NAS 优先 (通过 NASPathRouter)
        if cache_db_path is None:
            from pathlib import Path
            try:
                from engines.nas_path_router import nas_router
                sandbox_dir = nas_router.get("sandbox_cache").path
                # 沙盘历史缓存独立存一个 SQLite (不混主 app.db)
                _nas_cache = sandbox_dir / "sandbox_history.db"
                # 如果 NAS 可用或本地降级目录可写, 就用它
                try:
                    _nas_cache.parent.mkdir(parents=True, exist_ok=True)
                    _nas_cache.touch(exist_ok=True)
                    cache_db_path = str(_nas_cache)
                except Exception:
                    raise  # 触发 fallback
            except Exception:
                # 降级: 原 PROD DB → 项目 DB → 临时文件
                _prod = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
                _dev = Path(__file__).resolve().parent.parent / "database" / "app.db"
                if _prod.exists() and _prod.stat().st_size > 1_000_000:
                    cache_db_path = str(_prod)
                elif _dev.exists():
                    cache_db_path = str(_dev)
                else:
                    import tempfile
                    cache_db_path = str(Path(tempfile.gettempdir()) / "mt_sandbox_history.db")
        self._ensure_history_cache(cache_db_path)
        
        result: Dict[str, List[Dict[str, Any]]] = {}
        conn = sqlite3.connect(cache_db_path)
        
        for secid in secids:
            # 先查缓存
            cache_key = hashlib.md5(f"{secid}_{start_date}_{end_date}".encode()).hexdigest()
            cached = conn.execute(
                "SELECT data_json, source, row_count FROM mt_sandbox_history WHERE cache_key=?",
                (cache_key,)
            ).fetchone()
            
            if cached and cached[2] > 0:
                import json as _json
                result[secid] = _json.loads(cached[0])
                continue
            
            # 缓存未命中 → 拉取
            rows: List[Dict[str, Any]] = []
            source = "baostock"
            
            # 尝试 1: baostock
            try:
                rows = self.fetch_history_baostock(secid, start_date, end_date)
            except Exception as e1:
                sys.stderr.write(f"[SANDBOX-HIST] baostock {secid} 失败: {e1}\n")
                source = "akshare"
                
                # 尝试 2: AKShare
                try:
                    rows = self.fetch_history_akshare(secid, start_date, end_date)
                except Exception as e2:
                    sys.stderr.write(f"[SANDBOX-HIST] AKShare {secid} 也失败: {e2}, 降级为 fallback\n")
                    source = "fallback"
                    # 最终降级: 生成一段无变化的历史 (只用来跑通逻辑, source 显式标记)
                    rows = self._generate_fallback_history(secid, start_date, end_date)
            
            # 缓存写入
            if rows:
                import json as _json
                conn.execute("""
                    INSERT OR REPLACE INTO mt_sandbox_history
                    (cache_key, secid, start_date, end_date, data_json, source, fetched_at, row_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (cache_key, secid, start_date, end_date,
                      _json.dumps(rows, ensure_ascii=False),
                      source, _now_iso(), len(rows)))
                conn.commit()
            
            # 给每行加 source 标记
            for r in rows:
                r['source'] = f"history_{source}"
            
            result[secid] = rows
            sys.stderr.write(f"[SANDBOX-HIST] {secid}: {len(rows)} 天 ({source})\n")
        
        conn.close()
        return result

    def _generate_fallback_history(self, secid: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        最终降级 (所有真实源都不可用时): 生成一段 flat 行情
        ⚠️ 显式 source='fallback', 绝不冒充真实数据
        """
        from datetime import datetime, timedelta
        
        name_map = {s[0]: s[1] for s in WATCH_LIST_A}
        name = name_map.get(secid, secid)
        
        # 基准价
        base_price = 100.0
        for s in WATCH_LIST_A:
            if s[0] == secid:
                break
        
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        rows = []
        cur = start_dt
        day_offset = 0
        while cur <= end_dt:
            # 跳过周末
            if cur.weekday() < 5:
                rng = random.Random(f"{secid}_fb_{day_offset}")
                drift = rng.gauss(0, 0.005)  # 极低波动
                close = round(base_price * (1 + drift), 2)
                base_price = close
                rows.append({
                    "date": cur.strftime("%Y-%m-%d"),
                    "open": round(close * 0.998, 2),
                    "high": round(close * 1.005, 2),
                    "low": round(close * 0.995, 2),
                    "close": close,
                    "volume": rng.randint(500_000, 2_000_000),
                    "turnover": 0.0,
                    "change_pct": round(drift * 100, 2),
                })
                day_offset += 1
            cur += timedelta(days=1)
        
        return rows

    def apply_history_bar_to_cache(self, secid: str, name: str,
                                    open_p: float, high: float, low: float,
                                    close: float, prev_close: float,
                                    volume: int, turnover: float,
                                    date: str, source: str = "history") -> None:
        """
        把某根历史 K 线灌入 self._cache (让 run_tick 内 fetch_realtime 命中)
        这是历史回测的关键桥接
        
        ⚠️ 必须同时更新 _cache_ts 让 fetch_realtime 的 TTL 检查命中,
           否则 fetch_realtime 会绕过缓存去拉新浪实时行情
        """
        change_pct = ((close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        
        self._cache[secid] = {
            "secid": secid, "name": name,
            "price": close, "prev_close": prev_close,
            "open": open_p, "high": high, "low": low,
            "change_pct": round(change_pct, 2),
            "volume": volume, "turnover": turnover,
            "ts": date,
            "source": source,
        }
        # 🆕 关键: 设置有效 cache_ts, 让 fetch_realtime 的 TTL 检查命中
        # 否则 fetch_realtime 会跳过缓存去拉新浪实时行情 (彻底破坏历史回测)
        self._cache_ts = time.time()

    def get_history_trade_dates(self, history_dict: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        """从批量历史里提取所有交易日 (取第一只股票的日期作为基准)"""
        if not history_dict:
            return []
        first_key = next(iter(history_dict))
        dates = sorted({row['date'] for row in history_dict[first_key]})
        return dates


# ═══════════════════════════════════════════════════════════════════
# §3 策略引擎 (5 种策略)
# ═══════════════════════════════════════════════════════════════════
def strategy_momentum_breakout(quote: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    动量突破 (超短线)
    信号: 涨幅 > 2% + 放量 (成交量 > 昨日均量 1.5x)
    """
    change_pct = quote.get('change_pct', 0)
    volume = quote.get('volume', 0)
    
    score = 0
    if change_pct > 5:
        score += 40
    elif change_pct > 2:
        score += 25
    elif change_pct > 0:
        score += 5
    
    # 放量判断 (简化: volume 够大就加分)
    if volume > 1_000_000:
        score += 30
    elif volume > 500_000:
        score += 15
    
    # 涨停附近 = 信号增强
    price = quote.get('price', 0)
    prev = quote.get('prev_close', 1)
    limit_up_price = round(prev * (1 + LIMIT_UP_PCT), 2)
    if price >= limit_up_price * 0.98:
        score += 30
    
    signal_type = "BULL" if score >= 50 else ("BEAR" if change_pct < -3 else "HOLD")
    
    return {
        "strategy": "momentum_breakout",
        "signal_type": signal_type,
        "score": min(100, score),
        "reason": f"动量: 涨幅{change_pct:+.2f}%, 成交{volume:,}",
    }


def strategy_mean_reversion(quote: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    均值回归 (短线)
    信号: 跌幅 > 5% 且超卖 (RSI<30 近似用跌幅判断)
    """
    change_pct = quote.get('change_pct', 0)
    low = quote.get('low', 0)
    high = quote.get('high', 0)
    price = quote.get('price', 0)
    
    score = 0
    # 超跌反弹机会
    if change_pct < -7:
        score += 45
    elif change_pct < -5:
        score += 30
    elif change_pct < -3:
        score += 15
    
    # 价格回到高低点中位线以下 = 超卖
    mid = (high + low) / 2 if high and low else price
    if price < mid * 0.98:
        score += 20
    
    # 反弹迹象 (从日内低点回升)
    if low > 0 and price > low * 1.01:
        score += 15
    
    signal_type = "BULL" if score >= 50 else ("BEAR" if change_pct > 3 else "HOLD")
    
    return {
        "strategy": "mean_reversion",
        "signal_type": signal_type,
        "score": min(100, score),
        "reason": f"超跌: 跌幅{change_pct:+.2f}%, 反弹迹象={'是' if score >= 50 else '否'}",
    }


def strategy_trend_following(quote: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    趋势跟随 (中线)
    信号: 日内强趋势 + 成交量配合
    """
    change_pct = quote.get('change_pct', 0)
    volume = quote.get('volume', 0)
    
    score = 0
    if change_pct > 3:
        score += 35
    elif change_pct < -3:
        score += 25  # 下跌趋势也可跟进 (做空思维, A股融券有限)
    
    # 趋势强度 (高开高走 = 强势)
    open_p = quote.get('open', 0)
    price = quote.get('price', 0)
    if open_p > 0 and price > open_p:
        score += 20
    
    # 量价配合
    if volume > 2_000_000:
        score += 25
    
    # 板块共振 (大盘同向)
    market_trend = kwargs.get('market_trend', 0)
    if (market_trend > 0 and change_pct > 0) or (market_trend < 0 and change_pct < 0):
        score += 20
    
    signal_type = "BULL" if score >= 50 and change_pct > 0 else (
        "BEAR" if score >= 50 and change_pct < 0 else "HOLD")
    
    return {
        "strategy": "trend_following",
        "signal_type": signal_type,
        "score": min(100, score),
        "reason": f"趋势强度={score}, 大盘同步={'是' if market_trend else '否'}",
    }


def strategy_fundamental_value(quote: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    价值投资 (长线) — 日内简化版
    信号: 高安全边际 + 长期基本面 (日内用价格位置代替)
    """
    change_pct = quote.get('change_pct', 0)
    prev = quote.get('prev_close', 1)
    
    score = 0
    # 价格在相对低位 = 价值区
    if change_pct < -5:
        score += 35  # 回调 = 长期买入机会
    elif change_pct < 0:
        score += 15
    
    # 流动性好 = 适合长线进出
    volume = quote.get('volume', 0)
    if volume > 5_000_000:
        score += 30
    elif volume > 1_000_000:
        score += 15
    
    # 大盘不暴跌 = 安全
    market_trend = kwargs.get('market_trend', 0)
    if market_trend > -1:
        score += 20
    
    signal_type = "BULL" if score >= 50 else "HOLD"
    
    return {
        "strategy": "fundamental_value",
        "signal_type": signal_type,
        "score": min(100, score),
        "reason": f"价值区: 回调{change_pct:+.2f}%, 流动性充足度={score}",
    }


def strategy_panel_effect(quote: Dict[str, Any], market_quotes: Dict[str, Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """
    板块联动 — 同板块多只同时异动
    """
    score = 0
    reason_parts = []
    
    if market_quotes:
        # 检查同板块 (简化: 同 market 或同开头)
        secid = quote.get('secid', '')
        sector_peers = [q for s, q in market_quotes.items() 
                       if s != secid and s.startswith(secid[:2])]
        
        if sector_peers:
            # 同板块联动数量
            same_dir = sum(1 for p in sector_peers 
                          if (p.get('change_pct', 0) > 0) == (quote.get('change_pct', 0) > 0))
            if same_dir >= 2:
                score += 40
                reason_parts.append(f"同{same_dir}只同向")
            if same_dir >= len(sector_peers) * 0.6:
                score += 20
                reason_parts.append("板块共振")
    
    signal_type = "BULL" if score >= 40 else "HOLD"
    
    return {
        "strategy": "panel_effect",
        "signal_type": signal_type,
        "score": min(100, score),
        "reason": " + ".join(reason_parts) if reason_parts else "板块效应弱",
    }


ALL_STRATEGIES = [
    strategy_momentum_breakout,
    strategy_mean_reversion,
    strategy_trend_following,
    strategy_fundamental_value,
    strategy_panel_effect,
]


# ═══════════════════════════════════════════════════════════════════
# §4 团队协作模型 (三专家 + 风控 + 审计)
# ═══════════════════════════════════════════════════════════════════
EXPERT_POOL = [
    {"id": "expert_value", "name": "价值派专家", "role": "VALUE_INVESTOR", 
     "style": "中线", "weight": 1.0},
    {"id": "expert_tech", "name": "技术派专家", "role": "TECH_ANALYST",
     "style": "短线", "weight": 1.2},  # 技术派在短线更重
    {"id": "expert_quant", "name": "量化派专家", "role": "QUANT_TRADER",
     "style": "超短线", "weight": 0.9},
]

RISK_OFFICER = {
    "id": "risk_chief", "name": "风控总监", "role": "RISK_MANAGER",
    "power": "VETO",  # 一票否决权
}

AUDITOR = {
    "id": "audit_chief", "name": "审计官", "role": "AUDITOR",
    "power": "REVIEW",  # 事后审计
}


def team_vote(signals: List[Dict[str, Any]], quote: Dict[str, Any],
              portfolio: Dict[str, Any]) -> Dict[str, Any]:
    """
    团队投票 → 最终决策
    signals: [{strategy, signal_type, score, reason}] 来自 5 种策略
    """
    verdicts = []
    buy_score = 0.0
    sell_score = 0.0
    hold_score = 0.0
    
    # 每个专家独立投票 (风格偏好 + 策略信号)
    for expert in EXPERT_POOL:
        # 专家根据自己的风格选对应策略
        style_match = {
            "VALUE_INVESTOR": ["fundamental_value", "mean_reversion"],
            "TECH_ANALYST": ["momentum_breakout", "trend_following", "panel_effect"],
            "QUANT_TRADER": ["momentum_breakout", "trend_following"],
        }.get(expert['role'], [])
        
        # 匹配策略的平均分
        matched_scores = [s['score'] for s in signals if s['strategy'] in style_match]
        avg_score = sum(matched_scores) / max(1, len(matched_scores))
        avg_score = min(100, avg_score * expert['weight'])
        
        # 决定投票 (降低阈值让沙盘活跃交易)
        if avg_score >= 50:
            verdict = "BUY"
        elif avg_score >= 35:
            verdict = "HOLD"
        else:
            verdict = "SELL"
        
        # 置信度: BUY/HOLD 用看多分; SELL 必须用"看空强度"=100-score
        # (用原始低分当 SELL 置信度会把越看空算得越弱 → sell_score 永远到不了阈值, 结构性只买不卖)
        confidence = avg_score if verdict != "SELL" else (100 - avg_score)
        
        verdicts.append({
            "expert_id": expert['id'],
            "expert_name": expert['name'],
            "expert_role": expert['role'],
            "verdict": verdict,
            "confidence": round(confidence, 1),
            "reason": f"匹配策略平均分={avg_score:.1f}, 偏好风格={expert['style']}",
        })
        
        if verdict == "BUY":
            buy_score += confidence * expert['weight']
        elif verdict == "SELL":
            sell_score += confidence * expert['weight']
        else:
            hold_score += confidence * expert['weight']
    
    # 风控审查 (一票否决)
    risk_flags = []
    current_cash = portfolio.get('current_cash', 0)
    positions = portfolio.get('positions', [])
    
    # 风控规则 1: 现金占比不能低于 20%
    total_value = current_cash + sum(
        p.get('shares', 0) * quote.get('price', p.get('current_price', 0))
        for p in positions
    )
    cash_pct = (current_cash / total_value * 100) if total_value > 0 else 100
    
    if cash_pct < 20 and buy_score > sell_score:
        risk_flags.append(f"现金占比 {cash_pct:.1f}% < 20% 最低限")
    
    # 风控规则 2: 单票仓位不能超过 MAX_SINGLE_POSITION_PCT
    if buy_score > sell_score:
        for p in positions:
            pos_value = p.get('shares', 0) * quote.get('price', 0)
            if pos_value / max(1, total_value) > MAX_SINGLE_POSITION_PCT / 100:
                risk_flags.append(f"{p.get('name', p.get('symbol'))} 仓位已超 {MAX_SINGLE_POSITION_PCT:.0f}%")
    
    # 风控规则 3: 底线熔断
    initial_cash = portfolio.get('initial_cash', INITIAL_CASH)
    floor_value = initial_cash * (1 - RISK_FLOOR_PCT / 100)
    if total_value < floor_value:
        risk_flags.append(f"净值 {total_value:.0f} < 底线 {floor_value:.0f}, 强制 HOLD")
    
    # 综合
    if risk_flags:
        final_action = "HOLD"
        risk_veto = True
    else:
        if buy_score > sell_score and buy_score > 40:
            final_action = "BUY"
        elif sell_score > buy_score and sell_score > 40:
            final_action = "SELL"
        else:
            final_action = "HOLD"
        risk_veto = False
    
    return {
        "verdicts": verdicts,
        "buy_score": round(buy_score, 1),
        "sell_score": round(sell_score, 1),
        "hold_score": round(hold_score, 1),
        "final_action": final_action,
        "risk_flags": risk_flags,
        "risk_veto": risk_veto,
        "consensus": final_action == "HOLD" or (
            (buy_score > sell_score) and sum(1 for v in verdicts if v['verdict'] == 'BUY') >= 2
        ),
    }


# ═══════════════════════════════════════════════════════════════════
# §5 沙盘 Portfolio 引擎
# ═══════════════════════════════════════════════════════════════════
class SandboxPortfolio:
    """
    沙盘组合 — 管理现金/持仓/交易/风控
    支持多 session (一周/一年/自定义)
    """
    
    def __init__(self, scenario: str = "WEEK", days: int = None,
                 initial_cash: float = INITIAL_CASH,
                 risk_floor_pct: float = RISK_FLOOR_PCT):
        ensure_sandbox_tables()
        
        self.session_id = _gen_id("SB")
        self.scenario = scenario
        self.days = days or (WEEK_TRADING_DAYS if scenario == "WEEK" else
                            YEAR_TRADING_DAYS if scenario == "YEAR" else 30)
        self.initial_cash = initial_cash
        self.current_cash = initial_cash
        self.risk_floor_pct = risk_floor_pct
        self.positions: List[Dict[str, Any]] = []
        self.high_watermark = initial_cash
        self.is_frozen = False
        self.trade_count = 0
        self.start_date = _now_iso()
        self.current_date = self.start_date
        
        self._save_portfolio()
        sys.stderr.write(
            f"[SANDBOX] 🆕 沙盘 session={self.session_id} "
            f"scenario={scenario}({self.days}天) 本金={initial_cash:,.0f} "
            f"底线亏损={risk_floor_pct}%\n"
        )
    
    @classmethod
    def from_row(cls, row) -> "SandboxPortfolio":
        """从 DB 行恢复组合 — daemon 重启后必须接着原 session 跑, 否则持仓清零永远只 BUY 不 SELL"""
        pf = cls.__new__(cls)
        (pf.session_id, pf.scenario, pf.days, pf.initial_cash, pf.current_cash,
         pos_json, pf.risk_floor_pct, frozen, pf.start_date, pf.current_date,
         pf.high_watermark) = row
        pf.positions = json.loads(pos_json or "[]")
        pf.is_frozen = bool(frozen)
        pf.trade_count = 0
        return pf

    def _save_portfolio(self) -> None:
        conn = _conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO mt_sandbox_portfolio "
                "(session_id, scenario, scenario_days, initial_cash, current_cash, "
                "positions_json, risk_floor_pct, daily_risk_pct, daily_high_watermark, "
                "is_frozen, status, start_date, current_date, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.session_id, self.scenario, self.days,
                 self.initial_cash, self.current_cash,
                 json.dumps(self.positions, ensure_ascii=False),
                 self.risk_floor_pct, DAILY_RISK_PCT, self.high_watermark,
                 1 if self.is_frozen else 0,
                 "FROZEN" if self.is_frozen else "RUNNING",
                 self.start_date, self.current_date, _now_iso())
            )
            conn.commit()
        finally:
            conn.close()
    
    def get_total_value(self, price_map: Dict[str, float]) -> float:
        """当前总净值 = 现金 + 持仓市值"""
        pos_value = sum(
            p.get('shares', 0) * price_map.get(p['symbol'], p.get('avg_cost', 0))
            for p in self.positions
        )
        return self.current_cash + pos_value
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        for p in self.positions:
            if p['symbol'] == symbol:
                return p
        return None
    
    def buy(self, symbol: str, stock_name: str, price: float, signal_score: float = 0,
            team_verdict: str = "CONSENSUS", strategy: str = "",
            risk_ok: bool = True, source: str = "simulated",
            notes: str = "") -> Optional[Dict[str, Any]]:
        """
        买入 — 1/3 仓位分批买入, 最小 100 股
        返回: trade dict 或 None (风控/涨跌停拦截)
        """
        if self.is_frozen:
            sys.stderr.write(f"[SANDBOX] ❌ session 已熔断, 禁止买入\n")
            return None
        
        if price <= 0:
            return None
        
        # T+1 简化: 模拟允许当天买卖 (沙盘宽松模式)
        
        # 风控: 单笔不超过现金 50% 且不超过总资产 40% (沙盘允许更激进)
        total_val = self.get_total_value({symbol: price})
        max_spend = min(
            self.current_cash * 0.50,
            total_val * 0.40,
        )
        # 再受持仓上限约束 (单票 ≤ MAX_SINGLE_POSITION_PCT, 与团队风控同一口径)
        pos_value = self.get_position(symbol)
        if pos_value:
            existing_value = pos_value.get('shares', 0) * price
            max_additional = total_val * (MAX_SINGLE_POSITION_PCT / 100) - existing_value
            max_spend = min(max_spend, max(0, max_additional))
        
        # 最低保证: 如果现金够买一手, 至少买一手
        min_one_lot_cost = MIN_LOT * price + COMMISSION_MIN
        if max_spend < min_one_lot_cost and self.current_cash >= min_one_lot_cost:
            max_spend = min(self.current_cash, min_one_lot_cost * 1.02)
        
        shares = int(max_spend / price / MIN_LOT) * MIN_LOT
        if shares < MIN_LOT:
            return None  # 不够买一手
        
        # 成本计算
        gross = shares * price
        commission = max(COMMISSION_MIN, gross * COMMISSION_RATE)
        total_cost = gross + commission
        
        if total_cost > self.current_cash:
            shares = int((self.current_cash - commission) / price / MIN_LOT) * MIN_LOT
            if shares < MIN_LOT:
                return None
            gross = shares * price
            commission = max(COMMISSION_MIN, gross * COMMISSION_RATE)
            total_cost = gross + commission
        
        # 执行
        self.current_cash -= total_cost
        
        # 更新持仓 (加仓: 加权平均成本)
        pos = self.get_position(symbol)
        if pos:
            total_shares = pos['shares'] + shares
            pos['avg_cost'] = (pos['avg_cost'] * pos['shares'] + price * shares) / total_shares
            pos['shares'] = total_shares
            pos['current_price'] = price
        else:
            self.positions.append({
                "symbol": symbol,
                "name": stock_name,
                "shares": shares,
                "avg_cost": price,
                "current_price": price,
            })
        
        self.trade_count += 1
        self._save_portfolio()
        
        # 记录交易流水
        trade = {
            "trade_id": _gen_id("T"),
            "session_id": self.session_id,
            "trade_date": _now_iso()[:10],
            "trade_time": _now_iso()[11:19],
            "symbol": symbol,
            "stock_name": stock_name,
            "action": "BUY",
            "shares": shares,
            "price": price,
            "commission": round(commission, 2),
            "stamp_tax": 0.0,
            "total_amount": round(total_cost, 2),
            "strategy": strategy,
            "signal_score": signal_score,
            "team_verdict": team_verdict,
            "risk_ok": 1 if risk_ok else 0,
            "source": source,
            "notes": notes,
        }
        self._insert_trade(trade)
        
        return trade
    
    def sell(self, symbol: str, stock_name: str, price: float, shares: int = None,
             signal_score: float = 0, team_verdict: str = "CONSENSUS",
             strategy: str = "", source: str = "simulated",
             notes: str = "") -> Optional[Dict[str, Any]]:
        """卖出 — 全部持仓或指定股数
        
        ⚠️ A 股 T+1 结算规则:
        T 日(交易日) 买入的证券, 只能在 T+1 日或之后卖出
        引擎执行前强制检查: 今日(T日)该 symbol 买入股数是否 ≥ 卖出股数
        如果 ≥, 阻止卖出 (T+1 违规)
        """
        if self.is_frozen:
            return None
        
        # ═══ T+1 结算检查 (A 股强制规则) ═══
        today = _now_iso()[:10]
        try:
            conn_t1 = _conn()
            cur = conn_t1.execute(
                "SELECT COALESCE(SUM(shares),0) FROM mt_sandbox_trades "
                "WHERE session_id=? AND symbol=? AND action='BUY' AND trade_date=?",
                (self.session_id, symbol, today))
            bought_today = cur.fetchone()[0]
            cur2 = conn_t1.execute(
                "SELECT COALESCE(SUM(shares),0) FROM mt_sandbox_trades "
                "WHERE session_id=? AND symbol=? AND action='SELL' AND trade_date=?",
                (self.session_id, symbol, today))
            sold_today = cur2.fetchone()[0]
            conn_t1.close()
            
            # 今日已买入但未转出 T+1 的可卖余额
            sellable_today = bought_today - sold_today
            pos = self.get_position(symbol)
            pos_shares = (pos or {}).get('shares', 0)
            
            # 可卖股数 = 持仓 - 今日已买入的部分 (今日买的不能今日卖)
            sellable = pos_shares - max(sellable_today, 0)
            if sellable <= 0:
                log(f"[T+1 BLOCKED] {self.session_id} {symbol} {stock_name}: "
                    f"今日 BUY {bought_today} 股未到 T+1, 可卖 0 股. 跳过 SELL @¥{price}")
                return None
            # 如果指定 shares, 截断到可卖范围内
            if shares and shares > sellable:
                log(f"[T+1 TRUNCATE] {self.session_id} {symbol}: "
                    f"请求卖 {shares} 股, 可卖 {sellable} 股 (今日买 {bought_today} 股)")
                shares = sellable
        except Exception as e:
            log(f"[T+1 WARN] sell T+1 检查异常: {e}, 继续执行 (允许交易)")
        
        pos = self.get_position(symbol)
        if not pos or pos['shares'] <= 0:
            return None
        
        sell_shares = shares or pos['shares']
        sell_shares = min(sell_shares, pos['shares'])
        if sell_shares <= 0:
            return None
        
        gross = sell_shares * price
        commission = max(COMMISSION_MIN, gross * COMMISSION_RATE)
        stamp_tax = gross * STAMP_TAX_RATE
        total_revenue = gross - commission - stamp_tax
        
        self.current_cash += total_revenue
        
        # 更新持仓
        pos['shares'] -= sell_shares
        if pos['shares'] <= 0:
            self.positions = [p for p in self.positions if p['symbol'] != symbol]
        pos['current_price'] = price
        
        self.trade_count += 1
        self._save_portfolio()
        
        trade = {
            "trade_id": _gen_id("T"),
            "session_id": self.session_id,
            "trade_date": _now_iso()[:10],
            "trade_time": _now_iso()[11:19],
            "symbol": symbol,
            "stock_name": stock_name,
            "action": "SELL",
            "shares": sell_shares,
            "price": price,
            "commission": round(commission, 2),
            "stamp_tax": round(stamp_tax, 2),
            "total_amount": round(total_revenue, 2),
            "strategy": strategy,
            "signal_score": signal_score,
            "team_verdict": team_verdict,
            "risk_ok": 1,
            "source": source,
            "notes": notes,
        }
        self._insert_trade(trade)
        
        return trade
    
    def _insert_trade(self, trade: Dict[str, Any]) -> None:
        """写入 mt_sandbox_trades, 同时双写到 mt_trade_log 保持两表一致."""
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO mt_sandbox_trades "
                "(trade_id, session_id, trade_date, trade_time, symbol, stock_name, "
                "action, shares, price, commission, stamp_tax, total_amount, "
                "strategy, signal_score, team_verdict, risk_ok, source, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trade['trade_id'], trade['session_id'], trade['trade_date'],
                 trade['trade_time'], trade['symbol'], trade['stock_name'],
                 trade['action'], trade['shares'], trade['price'],
                 trade['commission'], trade['stamp_tax'], trade['total_amount'],
                 trade.get('strategy'), trade.get('signal_score', 0),
                 trade.get('team_verdict'), trade.get('risk_ok', 1),
                 trade.get('source', 'simulated'), trade.get('notes', ''))
            )
            # 双写到 mt_trade_log — sandbox_bp / health_api 也会读这张表
            conn.execute("""
                INSERT INTO mt_trade_log (trade_id, action, symbol, name, qty, price, fill_price, fill_qty,
                    fill_amount, amount, fee_total, reason, trade_mode, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sandbox', ?)
            """, (
                trade['trade_id'], trade['action'], trade['symbol'], trade['stock_name'],
                trade['shares'], trade['price'], trade['price'], trade['shares'],
                trade['total_amount'], trade['total_amount'],
                (trade.get('commission') or 0) + (trade.get('stamp_tax') or 0),
                trade.get('strategy') or trade.get('notes') or 'sandbox',
                f"{trade['trade_date']} {trade['trade_time']}"
            ))
            conn.commit()
        finally:
            conn.close()
    
    def check_risk_floor(self, price_map: Dict[str, float]) -> Dict[str, Any]:
        """风控检查 — 每日收盘后调用"""
        total = self.get_total_value(price_map)
        floor_value = self.initial_cash * (1 - self.risk_floor_pct / 100)
        drawdown_from_peak = (self.high_watermark - total) / self.high_watermark * 100 if self.high_watermark > 0 else 0
        
        if total > self.high_watermark:
            self.high_watermark = total
        
        risk_result = {
            "total_value": round(total, 2),
            "cash": round(self.current_cash, 2),
            "position_value": round(total - self.current_cash, 2),
            "floor_value": round(floor_value, 2),
            "drawdown_from_peak_pct": round(drawdown_from_peak, 2),
            "floor_triggered": total < floor_value,
            "daily_risk_triggered": drawdown_from_peak > DAILY_RISK_PCT,
        }
        
        if risk_result["floor_triggered"] and not self.is_frozen:
            self.is_frozen = True
            self._save_portfolio()
            sys.stderr.write(
                f"[SANDBOX] 🚨 风控熔断! 净值 {total:.0f} < 底线 {floor_value:.0f} "
                f"(回撤 {drawdown_from_peak:.1f}%) — 禁止新交易\n"
            )
        
        return risk_result
    
    def take_snapshot(self, price_map: Dict[str, float], notes: str = "") -> None:
        """每日快照"""
        total = self.get_total_value(price_map)
        floor = self.initial_cash * (1 - self.risk_floor_pct/100)
        cum_return = (total - self.initial_cash) / self.initial_cash * 100
        
        snap = {
            "snap_id": _gen_id("S"),
            "session_id": self.session_id,
            "snap_date": _now_iso()[:10],
            "total_value": round(total, 2),
            "cash_value": round(self.current_cash, 2),
            "position_value": round(total - self.current_cash, 2),
            "daily_return": 0,  # 简化: 日度用每日 diff 计算
            "cumulative_return": round(cum_return, 2),
            "max_drawdown": round(
                max(0, (self.high_watermark - total) / self.high_watermark * 100), 2
            ),
            "trade_count": self.trade_count,
            "notes": notes,
        }
        
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO mt_sandbox_snapshots "
                "(snap_id, session_id, snap_date, total_value, cash_value, position_value, "
                "daily_return, cumulative_return, max_drawdown, trade_count, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snap['snap_id'], snap['session_id'], snap['snap_date'],
                 snap['total_value'], snap['cash_value'], snap['position_value'],
                 snap['daily_return'], snap['cumulative_return'], snap['max_drawdown'],
                 snap['trade_count'], snap['notes'])
            )
            conn.commit()
        finally:
            conn.close()
        
        sys.stderr.write(
            f"[SANDBOX] 📊 快照: {snap['snap_date']} 净值={snap['total_value']:.0f} "
            f"累计收益={snap['cumulative_return']:+.1f}% 回撤={snap['max_drawdown']:.1f}%\n"
        )


# ═══════════════════════════════════════════════════════════════════
# §6 沙盘主控 (定时 tick + 事件驱动)
# ═══════════════════════════════════════════════════════════════════
class StockSandboxEngine:
    """
    股市沙盘主控 — 定时 + 事件双驱动
    
    用法:
      python3 -c "
        from engines.ai_stock_sandbox_engine import StockSandboxEngine
        sb = StockSandboxEngine()
        sb.run_tick()           # 手动 tick
        sb.run_daily_cycle()    # 完整一天
        sb.simulate_week()      # 一周模拟
        sb.simulate_year()      # 一年模拟
        sb.start_daemon()       # 守护进程
      "
    """
    
    _instance: Optional['StockSandboxEngine'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'StockSandboxEngine':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        ensure_sandbox_tables()
        self.data_provider = MarketDataProvider()
        self._active_portfolio: Optional[SandboxPortfolio] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def get_active_portfolio(self, scenario: str = "WEEK") -> SandboxPortfolio:
        """获取当前活跃沙盘 (不存在则新建)"""
        if self._active_portfolio and not self._active_portfolio.is_frozen:
            return self._active_portfolio
        
        # 先从 DB 找最近未 frozen 的, 并原样恢复 (持仓/现金/高水位)
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT session_id, scenario, scenario_days, initial_cash, current_cash, "
                "positions_json, risk_floor_pct, is_frozen, start_date, current_date, "
                "daily_high_watermark "
                "FROM mt_sandbox_portfolio "
                "WHERE scenario = ? AND is_frozen = 0 AND status = 'RUNNING' "
                "ORDER BY updated_at DESC LIMIT 1",
                (scenario,)
            ).fetchone()
        finally:
            conn.close()

        if row:
            self._active_portfolio = SandboxPortfolio.from_row(row)
            sys.stderr.write(
                f"[SANDBOX] ♻️ 恢复沙盘 session={row[0]} 现金={row[4]:,.0f} "
                f"持仓={len(self._active_portfolio.positions)}\n"
            )
            return self._active_portfolio

        self._active_portfolio = SandboxPortfolio(scenario=scenario)
        return self._active_portfolio
    
    # ── A股交易日护栏 (周末 + 法定假日跳过 tick) ──
    # 2026 年法定节假日 (国务院发布):
    # 元旦 1/1-1/3, 春节 2/16-2/22, 清明 4/4-4/6, 劳动节 5/1-5/5,
    # 端午 6/19-6/21, 中秋+国庆 10/1-10/7, 国庆后补休 10/10-10/11(若遇周末仍休)
    _CN_HOLIDAYS_2026 = set([
        # 元旦
        (1,1),(1,2),(1,3),
        # 春节 (2026-02-16 是春节)
        (2,16),(2,17),(2,18),(2,19),(2,20),(2,21),(2,22),
        # 清明
        (4,4),(4,5),(4,6),
        # 劳动节
        (5,1),(5,2),(5,3),(5,4),(5,5),
        # 端午
        (6,19),(6,20),(6,21),
        # 中秋+国庆
        (10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,7),
        # 2025 底 (可能跨 tick)
        (12,31),
    ])
    def _is_a_stock_trading_day(self, dt=None):
        """
        判断今天是不是 A 股交易日 (周末 + 法定假日 = False)
        2026 年国务院节假日表硬编码, 跨年后需更新
        """
        from datetime import datetime
        dt = dt or datetime.now()
        weekday = dt.weekday()  # 0=周一, 6=周日
        if weekday >= 5:
            sys.stderr.write(f"[SANDBOX-HOLIDAY] 今天 {dt.strftime('%Y-%m-%d %A')} 是周末, 跳过 tick\n")
            return False
        if (dt.month, dt.day) in self._CN_HOLIDAYS_2026:
            sys.stderr.write(f"[SANDBOX-HOLIDAY] 今天 {dt.strftime('%Y-%m-%d')} 是法定节假日, 跳过 tick\n")
            return False
        # 2025-2026 跨年保险: 年 != 2026 且 != 2025 也暂停 (防止未来跨年继续用旧表)
        if dt.year not in (2025, 2026):
            sys.stderr.write(f"[SANDBOX-HOLIDAY] 节假日表仅覆盖 2025-2026, 当前 {dt.year}, 暂停 tick\n")
            return False
        return True

    # ── 核心 tick: 一次行情扫描 + 信号 + 团队 + 执行 ──
    def run_tick(self) -> Dict[str, Any]:
        """
        一次 tick: 拉行情 → 跑 5 策略 → 团队投票 → 执行
        注意: 周末 + 法定假日自动跳过 (A股护栏)
        """
        if not self._is_a_stock_trading_day():
            return {"holiday_skip": True, "reason": "非A股交易日"}

        pf = self.get_active_portfolio()
        quotes = self.data_provider.fetch_realtime([s[0] for s in WATCH_LIST_A])
        
        if not quotes:
            return {"error": "no_quote", "message": "无行情数据"}
        
        # 大盘趋势
        market_quote = quotes.get('sh000001')
        market_trend = market_quote.get('change_pct', 0) if market_quote else 0
        
        # 对每只非 index 标的跑策略
        results = []
        for secid, quote in quotes.items():
            if secid.startswith('sh000') or secid.startswith('sz399'):
                continue  # 跳过指数, 只分析个股
            
            # 5 种策略并行跑
            signals = []
            for strategy_fn in ALL_STRATEGIES:
                try:
                    sig = strategy_fn(quote, market_trend=market_trend, market_quotes=quotes)
                    signals.append(sig)
                except Exception as e:
                    sys.stderr.write(f"[SANDBOX] 策略 {strategy_fn.__name__} 异常: {e}\n")
            
            # 团队投票
            portfolio_dict = {
                "initial_cash": pf.initial_cash,
                "current_cash": pf.current_cash,
                "positions": pf.positions,
            }
            verdict = team_vote(signals, quote, portfolio_dict)
            
            # 执行决策
            action = verdict['final_action']
            trade_result = None
            
            if pf.is_frozen:
                action = "HOLD"
            
            if action == "BUY" and not verdict['risk_veto']:
                # 计算综合信号强度
                avg_signal = sum(s['score'] for s in signals) / max(1, len(signals))
                trade_result = pf.buy(
                    symbol=secid, stock_name=quote['name'],
                    price=quote['price'], signal_score=round(avg_signal, 1),
                    team_verdict="CONSENSUS" if verdict['consensus'] else "DIVIDED",
                    strategy=",".join(s['strategy'] for s in signals if s['signal_type'] == 'BULL'),
                    source=quote.get('source', 'simulated'),
                    notes=f"团队 BUY {verdict['buy_score']:.0f}/{verdict['sell_score']:.0f}",
                )
            elif action == "SELL":
                avg_signal = sum(s['score'] for s in signals) / max(1, len(signals))
                trade_result = pf.sell(
                    symbol=secid, stock_name=quote['name'],
                    price=quote['price'], signal_score=round(avg_signal, 1),
                    team_verdict="CONSENSUS",
                    strategy=",".join(s['strategy'] for s in signals if s['signal_type'] == 'BEAR'),
                    source=quote.get('source', 'simulated'),
                    notes=f"团队 SELL (持仓={len(pf.positions)})",
                )
            
            # 保存信号
            for sig in signals:
                self._save_signal(pf.session_id, secid, quote['name'], sig, verdict)
            
            results.append({
                "symbol": secid, "name": quote['name'],
                "price": quote['price'], "change_pct": quote['change_pct'],
                "signals": signals, "verdict": verdict,
                "trade": trade_result,
            })
        
        # 风控检查
        price_map = {r['symbol']: r['price'] for r in results}
        price_map.update({s[0]: quotes.get(s[0], {}).get('price', 0)
                         for s in WATCH_LIST_A if s[0] in quotes})
        risk = pf.check_risk_floor(price_map)
        
        total_value = pf.get_total_value(price_map)
        sys.stderr.write(
            f"[SANDBOX] 📈 tick: {len(results)} 只分析, 总净值={total_value:,.0f} "
            f"(现金={pf.current_cash:,.0f}, 持仓={len(pf.positions)}) "
            f"回撤={risk['drawdown_from_peak_pct']:.1f}%"
            f"{' 🚨熔断' if pf.is_frozen else ''}\n"
        )
        
        # 🆕 脑库自动投喂 (所有信号/交易/团队投票/快照 → 脑库)
        self._feed_brain_after_tick(pf.session_id, results, total_value, 
                                      market_trend, pf, risk)
        
        return {
            "session_id": pf.session_id,
            "total_value": round(total_value, 2),
            "cash": pf.current_cash,
            "positions": len(pf.positions),
            "frozen": pf.is_frozen,
            "market_trend": market_trend,
            "results": results,
            "risk": risk,
        }
    
    def _save_signal(self, session_id: str, symbol: str, name: str,
                     sig: Dict[str, Any], verdict: Dict[str, Any]) -> None:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO mt_sandbox_signals "
                "(signal_id, session_id, signal_date, symbol, stock_name, "
                "signal_type, strategy, score, reason, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_gen_id("SG"), session_id, _now_iso()[:10], symbol, name,
                 sig['signal_type'], sig['strategy'], sig['score'],
                 sig.get('reason', ''), json.dumps(verdict, ensure_ascii=False)[:2000])
            )
            conn.commit()
        finally:
            conn.close()
    
    # ── 🆕 tick 后脑库投喂 ──
    def _feed_brain_after_tick(self, session_id: str, results: List[Dict],
                                total_value: float, market_trend: float,
                                pf: Any, risk: Dict[str, Any]) -> None:
        """
        每次 run_tick 后自动把所有有价值的信息喂进脑库
        
        投喂内容:
          1. 每只股票的策略信号 (5 策略并行)
          2. 每只股票的团队投票 (3 专家)
          3. 实际执行的交易 (BUY/SELL)
          4. 每日净值快照 (每天一条 summary)
        """
        try:
            from engines.ai_brain_feed_engine import brain_feed
            
            signals_count = 0
            verdicts_count = 0
            trades_count = 0
            
            for r in results:
                secid = r.get('symbol', '')
                name = r.get('name', secid)
                signals = r.get('signals', [])
                verdict = r.get('verdict', {})
                trade = r.get('trade')
                
                # 1. 策略信号 → 脑库 (每个 BULL/BEAR 信号)
                for sig in signals:
                    if sig.get('signal_type') != 'HOLD':  # 只投喂有方向的
                        brain_feed.feed_sandbox_signal(
                            session_id=session_id,
                            symbol=secid, name=name,
                            strategy=sig.get('strategy', '?'),
                            signal_type=sig.get('signal_type', '?'),
                            score=sig.get('score', 0),
                            reason=sig.get('reason', ''),
                        )
                        signals_count += 1
                
                # 2. 专家投票 → 脑库
                for v in verdict.get('verdicts', []):
                    brain_feed.feed_team_verdict(
                        session_id=session_id,
                        symbol=secid,
                        expert_role=v.get('expert_role', '?'),
                        verdict=v.get('verdict', 'HOLD'),
                        reason=v.get('reason', ''),
                        confidence=v.get('score', 0),
                    )
                    verdicts_count += 1
                
                # 3. 实际交易 → 脑库
                if trade and trade.get('executed'):
                    brain_feed.feed_sandbox_trade(
                        session_id=session_id,
                        symbol=secid, name=name,
                        action=trade.get('action', '?'),
                        shares=trade.get('shares', 0),
                        price=trade.get('price', 0),
                        amount=trade.get('total_amount', 0),
                        team_verdict=verdict.get('final_action', 'HOLD'),
                        notes=trade.get('notes', ''),
                    )
                    trades_count += 1
            
            # 4. 每日快照 (每 tick 一条 summary)
            if results:  # 有行情时才投
                brain_feed.feed_sandbox_summary(
                    session_id=session_id,
                    date=_now_iso()[:10],
                    nav=total_value,
                    daily_return=market_trend,
                    positions=pf.positions if isinstance(pf.positions, list) else [],
                )
            
            if signals_count + verdicts_count + trades_count > 0:
                sys.stderr.write(
                    f"[BRAIN] 📥 本次 tick 投喂: signals={signals_count} "
                    f"verdicts={verdicts_count} trades={trades_count} "
                    f"(→ NAS brain_feed/)\n"
                )
                
        except Exception as e:
            sys.stderr.write(f"[BRAIN] tick 投喂跳过 (非致命): {e}\n")
    
    # ── 模拟指定天数 ──
    def simulate_days(self, days: int, scenario: str = "CUSTOM") -> Dict[str, Any]:
        """
        快速模拟 N 个交易日 (自动 tick + 快照)
        适合回测一周/一年
        """
        pf = self.get_active_portfolio(scenario)
        initial_value = pf.initial_cash
        
        daily_returns = []
        prev_total = None
        for day in range(1, days + 1):
            if pf.is_frozen:
                sys.stderr.write(f"[SANDBOX] 🚨 已熔断, 第 {day} 天跳过\n")
                break
            
            sys.stderr.write(f"\n[SANDBOX] ═══ 第 {day}/{days} 天 ═══\n")
            
            # 🆕 先拉一次真实行情 (填缓存), 然后注入日波动
            # 这样 run_tick 内部 fetch_realtime 会命中带波动的缓存
            secids = [s[0] for s in WATCH_LIST_A]
            self.data_provider.invalidate_cache()
            self.data_provider.fetch_realtime(secids)
            self.data_provider.apply_daily_perturbation(day)
            
            tick_result = self.run_tick()
            
            # 日终快照
            price_map = {}
            for secid, quote in self.data_provider.fetch_realtime([s[0] for s in WATCH_LIST_A]).items():
                price_map[secid] = quote['price']
            
            pf.take_snapshot(price_map, notes=f"Day {day}/{days}")
            
            total = pf.get_total_value(price_map)
            if prev_total is not None and prev_total > 0:
                daily_ret = (total - prev_total) / prev_total * 100
            else:
                daily_ret = 0
            daily_returns.append(daily_ret)
            prev_total = total
        
        # 汇总报告
        final_value = prev_total or pf.get_total_value(
            {s[0]: 0 for s in WATCH_LIST_A}  # 兜底 price_map
        )
        total_return = (final_value - initial_value) / initial_value * 100
        win_days = sum(1 for r in daily_returns if r > 0)
        max_dd = max(0.0, (pf.high_watermark - final_value) / max(0.01, pf.high_watermark) * 100)
        
        report = {
            "session_id": pf.session_id,
            "scenario": scenario,
            "days_simulated": len(daily_returns),
            "initial_value": initial_value,
            "final_value": round(final_value, 2),
            "total_return_pct": round(total_return, 2),
            "annualized_return_pct": round(total_return * 244 / max(1, len(daily_returns)), 1),
            "win_days": win_days,
            "lose_days": len(daily_returns) - win_days,
            "win_rate": round(win_days / max(1, len(daily_returns)) * 100, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": pf.trade_count,
            "frozen": pf.is_frozen,
        }
        
        sys.stderr.write(f"\n{'='*60}\n")
        sys.stderr.write(f"📊 沙盘报告 ({scenario}, {len(daily_returns)} 天)\n")
        sys.stderr.write(f"{'='*60}\n")
        sys.stderr.write(f"  本金:   ¥{initial_value:,.0f}\n")
        sys.stderr.write(f"  终值:   ¥{final_value:,.0f}\n")
        sys.stderr.write(f"  收益:   {total_return:+.2f}% (年化 {report['annualized_return_pct']:+.1f}%)\n")
        sys.stderr.write(f"  胜率:   {report['win_rate']:.1f}% ({win_days}/{len(daily_returns)} 天)\n")
        sys.stderr.write(f"  最大回撤: {report['max_drawdown_pct']:.2f}%\n")
        sys.stderr.write(f"  交易数: {pf.trade_count}\n")
        sys.stderr.write(f"  熔断:   {'是' if pf.is_frozen else '否'}\n")
        sys.stderr.write(f"{'='*60}\n")
        
        return report
    
    def simulate_week(self) -> Dict[str, Any]:
        """一周快速模拟"""
        return self.simulate_days(WEEK_TRADING_DAYS, scenario="WEEK")
    
    def simulate_year(self) -> Dict[str, Any]:
        """一年模拟"""
        return self.simulate_days(YEAR_TRADING_DAYS, scenario="YEAR")
    
    # ── 🆕 真实历史 K 线回测 ──
    def simulate_history(self, secids: List[str] = None,
                          start_date: str = "2024-01-01",
                          end_date: str = "2024-12-31",
                          scenario: str = "HISTORY") -> Dict[str, Any]:
        """
        按真实历史 K 线逐日回放 (baostock 主源)
        
        每一步:
          1. 加载真实历史日线 (baostock → AKShare → fallback)
          2. 逐日循环: 把当天 OHLCV 灌入缓存 → run_tick()
          3. run_tick() 内部: 5 策略 → 3 专家投票 → 风控总监 → 审计归档
          4. 协作总线 publish SANDBOX_HISTORY_DAY → 11 家订阅者响应
        
        ⚠️ 数据源降级链:
          baostock (免费真实) → AKShare (非东方财富) → fallback (显式标记)
          所有降级结果在 source 字段显式标记, 绝不冒充真实
        """
        pf = self.get_active_portfolio(scenario)
        initial_value = pf.initial_cash
        
        if secids is None:
            secids = [s[0] for s in WATCH_LIST_A]
        
        # ── 1. 加载历史 K 线 (带本地 SQLite 缓存) ──
        sys.stderr.write(f"\n📊 [SANDBOX-HIST] 加载历史 K 线: {len(secids)} 只 {start_date} ~ {end_date}\n")
        history = self.data_provider.fetch_history_batch(secids, start_date, end_date)
        
        trade_dates = self.data_provider.get_history_trade_dates(history)
        sys.stderr.write(f"📊 [SANDBOX-HIST] 共 {len(trade_dates)} 个交易日\n")
        
        # 验证数据完整性
        for secid, rows in history.items():
            real_count = sum(1 for r in rows if r.get('source', '').startswith('history_baostock'))
            ak_count = sum(1 for r in rows if r.get('source', '').startswith('history_akshare'))
            fb_count = sum(1 for r in rows if r.get('source', '').startswith('history_fallback'))
            sys.stderr.write(f"  {secid}: {len(rows)} 天 "
                           f"(baostock={real_count}, akshare={ak_count}, fallback={fb_count})\n")
        
        if not trade_dates:
            return {"ok": False, "error": f"无有效交易日 ({start_date}~{end_date})"}
        
        # secid → {date → row} 快速查找
        history_by_date: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for secid, rows in history.items():
            for r in rows:
                d = r['date']
                if d not in history_by_date:
                    history_by_date[d] = {}
                history_by_date[d][secid] = r
        
        # secid → name 映射
        name_map = {s[0]: s[1] for s in WATCH_LIST_A}
        all_secids_in_watch = set(s[0] for s in WATCH_LIST_A)
        
        # ── 2. 逐日回放 ──
        daily_returns = []
        prev_total = None
        day_count = 0
        
        for trade_date in trade_dates:
            if pf.is_frozen:
                sys.stderr.write(f"[SANDBOX-HIST] 🚨 已熔断, {trade_date} 跳过\n")
                break
            
            day_count += 1
            sys.stderr.write(f"\n[SANDBOX-HIST] ═══ {trade_date} ({day_count}/{len(trade_dates)}) ═══\n")
            
            # 清缓存 → 灌入当天所有股票的 OHLCV
            self.data_provider.invalidate_cache()
            day_data = history_by_date.get(trade_date, {})
            
            for secid in secids:
                row = day_data.get(secid)
                if row is None:
                    # 这只股票当天无数据 (停牌) — 保持上一交易日价格
                    continue
                
                prev_rows = history[secid]
                prev_close = row.get('open', row['close'])
                # 找前一天的 close 做 prev_close
                for prev_row in prev_rows:
                    if prev_row['date'] < trade_date:
                        prev_close = prev_row['close']
                        break
                
                self.data_provider.apply_history_bar_to_cache(
                    secid=secid,
                    name=name_map.get(secid, secid),
                    open_p=row['open'],
                    high=row['high'],
                    low=row['low'],
                    close=row['close'],
                    prev_close=prev_close,
                    volume=row['volume'],
                    turnover=row.get('turnover', 0.0),
                    date=trade_date,
                    source=row.get('source', 'history_baostock'),
                )
            
            # run_tick: 5 策略 → 3 专家 → 风控 → 执行
            tick_result = self.run_tick()
            
            # 日终快照
            price_map = {}
            for secid in secids:
                row = day_data.get(secid)
                if row:
                    price_map[secid] = row['close']
            # 指数也进 price_map
            for idx_secid in ['sh000001', 'sz399006']:
                row = day_data.get(idx_secid)
                if row:
                    price_map[idx_secid] = row['close']
            
            pf.take_snapshot(price_map, notes=f"HIST {trade_date}")
            
            total = pf.get_total_value(price_map)
            if prev_total and prev_total > 0:
                daily_ret = (total - prev_total) / prev_total * 100
            else:
                daily_ret = 0
            daily_returns.append(daily_ret)
            prev_total = total
            
            # 协作总线 publish (让 11 家订阅者都响应)
            self._publish_history_day_event(pf.session_id, trade_date, tick_result, daily_ret, pf)
        
        # ── 3. 汇总报告 ──
        final_value = prev_total or pf.get_total_value(
            {s[0]: 0 for s in WATCH_LIST_A}
        )
        total_return = (final_value - initial_value) / initial_value * 100
        win_days = sum(1 for r in daily_returns if r > 0)
        max_dd = max(0.0, (pf.high_watermark - final_value) / max(0.01, pf.high_watermark) * 100)
        
        report = {
            "ok": True,
            "session_id": pf.session_id,
            "scenario": scenario,
            "date_range": f"{start_date} ~ {end_date}",
            "days_simulated": day_count,
            "initial_value": initial_value,
            "final_value": round(final_value, 2),
            "total_return_pct": round(total_return, 2),
            "annualized_return_pct": round(total_return * 244 / max(1, day_count), 1),
            "win_days": win_days,
            "lose_days": day_count - win_days,
            "win_rate": round(win_days / max(1, day_count) * 100, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": pf.trade_count,
            "positions": pf.positions,
            "frozen": pf.is_frozen,
            "data_sources": {secid: history[secid][0].get('source', 'unknown') for secid in secids if history.get(secid)},
        }
        
        # 最终协作总线事件
        self._publish_history_complete_event(report)
        
        sys.stderr.write(f"\n{'='*60}\n")
        sys.stderr.write(f"📊 沙盘历史回测报告 ({scenario})\n")
        sys.stderr.write(f"{'='*60}\n")
        sys.stderr.write(f"  日期范围: {start_date} ~ {end_date} ({day_count} 交易日)\n")
        sys.stderr.write(f"  本金:     ¥{initial_value:,.0f}\n")
        sys.stderr.write(f"  终值:     ¥{final_value:,.0f}\n")
        sys.stderr.write(f"  收益:     {total_return:+.2f}% (年化 {report['annualized_return_pct']:+.1f}%)\n")
        sys.stderr.write(f"  胜率:     {report['win_rate']}% ({win_days}/{day_count} 天)\n")
        sys.stderr.write(f"  最大回撤: {max_dd:.2f}%\n")
        sys.stderr.write(f"  交易数:   {pf.trade_count}\n")
        sys.stderr.write(f"  熔断:     {'是 🚨' if pf.is_frozen else '否 ✅'}\n")
        sys.stderr.write(f"{'='*60}\n")
        
        return report
    
    def _publish_history_day_event(self, session_id: str, trade_date: str,
                                    tick_result: Dict[str, Any], daily_ret: float,
                                    pf: Any) -> None:
        """
        协作总线: 每个历史 tick 后 publish SANDBOX_HISTORY_DAY
        让 11 家订阅者 (战略/医疗/研发/Skill/教育/人事/文案/版本/同步/EigenFlux/复盘脑库) 全部参与
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(BASE))
            from engines.collab_bus_engine import get_collab_bus
            bus = get_collab_bus()
            bus.publish(
                event_type="SANDBOX_HISTORY_DAY",
                source="stock_sandbox",
                payload={
                    "session_id": session_id,
                    "trade_date": trade_date,
                    "nav": round(tick_result.get('total_value', 0), 2),
                    "daily_return_pct": round(daily_ret, 2),
                    "positions": pf.positions,
                    "cash": round(pf.current_cash, 2),
                },
                severity="HIGH",
            )
        except Exception as e:
            sys.stderr.write(f"[SANDBOX-HIST] 协作总线 publish 跳过: {e}\n")
    
    def _publish_history_complete_event(self, report: Dict[str, Any]) -> None:
        """回测完成后 publish 最终报告"""
        try:
            import sys as _sys
            _sys.path.insert(0, str(BASE))
            from engines.collab_bus_engine import get_collab_bus
            bus = get_collab_bus()
            bus.publish(
                event_type="SANDBOX_HISTORY_COMPLETE",
                source="stock_sandbox",
                payload=report,
                severity="NORMAL",
            )
        except Exception:
            pass
    
    # ── 守护进程 (定时 tick + 协作总线事件) ──
    def start_daemon(self, interval: int = 30) -> None:
        """
        守护进程: 每 30s 一次 tick
        同时监听协作总线 MARKET_ANOMALY / MARKET_TICK
        """
        def _loop():
            sys.stderr.write(f"[SANDBOX] 🔄 daemon 启动 (interval={interval}s)\n")
            
            # 注册协作总线订阅
            try:
                sys.path.insert(0, str(BASE))
                from engines.collab_bus_engine import get_collab_bus
                bus = get_collab_bus()
                bus.subscribe(
                    subscriber_id="stock_sandbox",
                    subscriber_name="股市沙盘",
                    subscribe_events=["MARKET_ANOMALY", "MARKET_TICK", "CRITICAL_ALERT"],
                    event_handler=self._on_bus_event,
                    priority=85,
                )
                sys.stderr.write("[SANDBOX] ✅ 协作总线订阅成功\n")
            except Exception as e:
                sys.stderr.write(f"[SANDBOX] 协作总线延迟订阅: {e}\n")
            
            while not self._stop_event.is_set():
                try:
                    self.run_tick()
                except Exception as e:
                    sys.stderr.write(f"[SANDBOX] tick 异常: {e}\n")
                self._stop_event.wait(timeout=interval)
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=_loop, name='stock-sandbox', daemon=True)
        self._thread.start()
    
    def stop_daemon(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
    
    def _on_bus_event(self, event: Dict[str, Any]) -> None:
        """协作总线回调 → 事件驱动 tick"""
        et = event.get('event_type', '')
        sev = event.get('severity', 'INFO')
        
        if et == 'MARKET_ANOMALY' or (et == 'MARKET_TICK' and random.random() < 0.3):
            sys.stderr.write(f"[SANDBOX] 📡 协作总线触发 tick: {et} ({sev})\n")
            try:
                self.run_tick()
            except Exception as e:
                sys.stderr.write(f"[SANDBOX] 事件驱动 tick 异常: {e}\n")


def get_stock_sandbox() -> StockSandboxEngine:
    return StockSandboxEngine()


# ═══════════════════════════════════════════════════════════════════
# §7 CLI 入口
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="股市沙盘模拟投资引擎")
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    sub.add_parser("tick", help="手动 tick 一次")
    p_week = sub.add_parser("week", help="一周快速模拟 (10交易日)")
    p_year = sub.add_parser("year", help="一年模拟 (244交易日)")
    p_days = sub.add_parser("days", help="自定义天数")
    p_days.add_argument("--n", type=int, required=True)
    sub.add_parser("daemon", help="守护进程模式")
    p_stats = sub.add_parser("stats", help="查看沙盘统计")
    
    args = parser.parse_args()
    sb = get_stock_sandbox()
    
    if args.cmd == "tick":
        result = sb.run_tick()
        print(json.dumps({
            "total_value": result.get("total_value"),
            "cash": result.get("cash"),
            "positions": result.get("positions"),
            "frozen": result.get("frozen"),
            "trades": [r.get("trade") for r in result.get("results", []) if r.get("trade")],
        }, indent=2, ensure_ascii=False, default=str))
    
    elif args.cmd == "week":
        sb.simulate_week()
    
    elif args.cmd == "year":
        sb.simulate_year()
    
    elif args.cmd == "days":
        sb.simulate_days(args.n)
    
    elif args.cmd == "daemon":
        sb.start_daemon(interval=30)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            sb.stop_daemon()
    
    elif args.cmd == "stats":
        conn = _conn()
        try:
            print("\n=== 沙盘组合 ===")
            rows = conn.execute(
                "SELECT session_id, scenario, scenario_days, initial_cash, current_cash, "
                "is_frozen, status, created_at FROM mt_sandbox_portfolio ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                print(f"  {r['session_id']} scenario={r['scenario']} cash={r['current_cash']:,.0f} "
                      f"initial={r['initial_cash']:,.0f} frozen={r['is_frozen']}")
            
            print(f"\n=== 交易流水 (最近 20) ===")
            rows = conn.execute(
                "SELECT trade_id, trade_date, symbol, stock_name, action, shares, price, "
                "strategy, team_verdict FROM mt_sandbox_trades ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            for r in rows:
                print(f"  {r['trade_date']} {r['action']:4s} {r['symbol']} {r['stock_name'][:8]:8s} "
                      f"{r['shares']:>6d} × ¥{r['price']:.2f} | {r.get('team_verdict','')}")
            
            print(f"\n=== 信号池 (最近 10) ===")
            rows = conn.execute(
                "SELECT signal_date, symbol, signal_type, strategy, score, reason "
                "FROM mt_sandbox_signals ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                print(f"  {r['signal_date']} {r['symbol']} {r['signal_type']:5s} "
                      f"{r['strategy']:20s} score={r['score']:.0f} {r.get('reason','')[:40]}")
        finally:
            conn.close()
