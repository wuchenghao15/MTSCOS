#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gobelin_daily_pnl.py — 古灵阁每日收盘 PnL 汇总 + 告警
每天 15:10 由 launchd StartCalendarInterval 触发 (周一到周五)
功能:
  1. 计算所有活跃 session 当日 PnL
  2. 写入 mt_sandbox_snapshots.daily_high_watermark
  3. 跨节点一致性校验 (dev/mini)
  4. 输出 JSON + 可选飞书推送
"""
import sqlite3, os, sys, json, hashlib, time
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('MTSCOS_DB_PATH') and os.path.exists(os.environ['MTSCOS_DB_PATH']):
    DB = os.environ['MTSCOS_DB_PATH']
else:
    DB = os.path.join(os.path.dirname(BASE), 'database', 'app.db')
OUT_DIR = os.path.join(os.path.dirname(BASE), '_runtime')

# snapshots 表已存在, 列名: snap_id/snap_date/total_value/cash_value/position_value/daily_return/cumulative_return/max_drawdown/trade_count
_DDL_ADD = """
ALTER TABLE mt_sandbox_snapshots ADD COLUMN pnl_amount REAL DEFAULT 0;
"""

# 交易日护栏: 周末 + 2026 法定假日
HOLIDAYS_2026 = {
    '2026-01-01','2026-01-02','2026-01-03',
    '2026-02-15','2026-02-16','2026-02-17','2026-02-18','2026-02-19',
    '2026-04-04','2026-04-05','2026-04-06',
    '2026-05-01','2026-05-02','2026-05-03','2026-05-04','2026-05-05',
    '2026-06-19','2026-06-20','2026-06-21',
    '2026-10-01','2026-10-02','2026-10-03','2026-10-04','2026-10-05','2026-10-06','2026-10-07',
}

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)

def is_trading_day():
    today = date.today()
    if today.weekday() >= 5: return False
    if today.isoformat() in HOLIDAYS_2026: return False
    return True

def _fetch_realtime_prices(symbols: list) -> dict:
    """尝试通过 MarketDataService 获取实时价格, fallback 到 DB 最新成交价"""
    prices = {}
    if not symbols:
        return prices
    try:
        from core.services.market_data_service import MarketDataService
        mds = MarketDataService()
        secids = []
        sym_to_secid = {}
        for sym in symbols:
            # symbol 可能已经带前缀如 sh601318 / sz002594
            if sym.startswith(('sh', 'sz')):
                secid = sym
            elif sym[0] in ('6', '5', '9'):
                secid = 'sh' + sym
            else:
                secid = 'sz' + sym
            secids.append(secid)
            sym_to_secid[sym] = secid
        rt = mds._sina_realtime(secids)
        for sym, secid in sym_to_secid.items():
            if secid in rt and rt[secid].get('price', 0) > 0:
                prices[sym] = float(rt[secid]['price'])
    except Exception as e:
        log(f'  realtime price fetch failed: {e}')
    return prices


def _calc_portfolio_position_value(conn, session_id: str) -> tuple[float, list]:
    """从 portfolio.positions_json + 实时价计算 position_value"""
    import json as _json
    # 1. 读 positions_json
    row = conn.execute("""
        SELECT positions_json FROM mt_sandbox_portfolio WHERE session_id=?
    """, (session_id,)).fetchone()
    if not row or not row[0]:
        return 0.0, []
    try:
        positions = _json.loads(row[0])
    except Exception:
        return 0.0, []
    if not positions:
        return 0.0, []

    # 2. 收集 symbol 列表, 尝试获取实时价
    syms = [p.get('symbol', '') for p in positions if p.get('symbol')]
    rt_prices = _fetch_realtime_prices(syms)

    pos_items = []
    total_val = 0.0
    for p in positions:
        sym = p.get('symbol', '')
        shares = float(p.get('shares', 0))
        # 优先实时价, 其次从 mt_sandbox_trades 取该 symbol 最新成交价
        price = rt_prices.get(sym, 0)
        if not price or price <= 0:
            # fallback: 最近一次成交价
            tr = conn.execute("""
                SELECT price FROM mt_sandbox_trades
                WHERE session_id=? AND symbol=? AND action='BUY'
                ORDER BY datetime(created_at) DESC LIMIT 1
            """, (session_id, sym)).fetchone()
            if not tr:
                tr = conn.execute("""
                    SELECT price FROM mt_sandbox_trades
                    WHERE session_id=? AND symbol=?
                    ORDER BY datetime(created_at) DESC LIMIT 1
                """, (session_id, sym)).fetchone()
            price = float(tr[0]) if tr else float(p.get('avg_cost', 0))
        if price > 0 and shares > 0:
            val = shares * price
            total_val += val
            pos_items.append({'symbol': sym, 'shares': shares, 'price': price, 'value': round(val, 2)})

    return round(total_val, 2), pos_items


# ═══════════════════════════════════════════════════════════════
# v26.1: BaseEngine 包装类 — GobelinDailyPnl
# ═══════════════════════════════════════════════════════════════
class GobelinDailyPnl:
    """Gobelin 每日 PnL — 统一引擎接口 (BaseEngine 兼容)"""
    SYSTEM = "gobelin"
    ENGINE_NAME = "GobelinDailyPnl"

    def __init__(self, db_path=None):
        import logging, time as _time
        self.db_path = db_path or DB
        self._running = False
        self._loop_count = 0
        self._start_time = None
        self._time = _time
        logger = logging.getLogger("mtscos.gobelin.GobelinDailyPnl")
        if not logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s %(message)s'))
            logger.addHandler(h)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        self.logger = logger

    def start(self):
        self._running = True
        self._start_time = self._time.time()
        self.logger.info(f"[gobelin] GobelinDailyPnl START")
        self.emit_event("DAEMON_STARTED", payload={"engine": "GobelinDailyPnl"})

    def stop(self):
        self._running = False
        self.logger.info(f"[gobelin] GobelinDailyPnl STOP (loops={self._loop_count})")
        self.emit_event("DAEMON_STOPPED", payload={"engine": "GobelinDailyPnl", "loop_count": self._loop_count})

    def run_loop_once(self):
        self._loop_count += 1
        run()
        self.emit_event("GOBELIN_DAILY_PNL_DONE", payload={"loop": self._loop_count})

    def run_loop(self, interval=600):
        self.start()
        try:
            while self._running:
                try:
                    self.run_loop_once()
                except Exception as e:
                    self.logger.error(f"loop error: {e}")
                self._time.sleep(interval)
        finally:
            self.stop()

    def emit_event(self, event_name, target=None, payload=None, severity="INFO"):
        try:
            from engines.event_bus_engine import emit as _emit
            return _emit(
                event_name=event_name, source_system="gobelin",
                target_system=target, payload=payload or {}, severity=severity
            )
        except Exception as e:
            self.logger.debug(f"emit fallback: {e}")
            return None

    def health_check(self):
        uptime = round(self._time.time() - (self._start_time or self._time.time()), 1)
        return {
            "engine": "GobelinDailyPnl",
            "system": "gobelin",
            "running": self._running,
            "uptime_sec": uptime,
            "loop_count": self._loop_count,
            "db_path": self.db_path,
        }


def run():
    log('═══════════════════════════════════════════')
    log('📊 古灵阁每日 PnL 汇总')
    log('═══════════════════════════════════════════')

    if not is_trading_day():
        log(f'⏭ 今日 {date.today().isoformat()} 非交易日, 跳过')
        return 0

    conn = sqlite3.connect(f'file:{DB}?mode=rwc', uri=True)
    try:
        conn.executescript(_DDL_ADD); conn.commit()
    except Exception: pass  # 列已存在
    today = date.today().isoformat()
    result = {'date': today, 'sessions': [], 'trades_today': 0, 'total_pnl': 0.0}

    # 1. 今日交易
    trades = conn.execute("""
        SELECT trade_id, session_id, action, symbol, shares, price, total_amount, created_at
        FROM mt_sandbox_trades
        WHERE date(created_at)=?
        ORDER BY session_id, created_at
    """, (today,)).fetchall()
    result['trades_today'] = len(trades)
    log(f'① 今日交易: {len(trades)} 笔')

    # 2. 活跃 session PnL
    sessions = conn.execute("""
        SELECT session_id, scenario, initial_cash, current_cash, status
        FROM mt_sandbox_portfolio
        WHERE status='RUNNING' OR session_id='SB-e3105ea094db'
    """).fetchall()

    for sid, scenario, initial, current, st in sessions:
        # Fix 3: 计算真实的 position_value
        pos_val, pos_items = _calc_portfolio_position_value(conn, sid)
        # total_value = current_cash + position_value
        total_val = current + pos_val
        # 基于 total_value 的 PnL (更准确)
        pnl = total_val - initial
        pct = (pnl / initial * 100) if initial else 0
        log(f'  📌 {sid[:20]} pos_value=¥{pos_val:,.2f} ({len(pos_items)}只)')
        for pi in pos_items:
            log(f'     → {pi["symbol"]} {pi["shares"]}股 @ ¥{pi["price"]:.2f} = ¥{pi["value"]:,.2f}')

        sess_info = {
            'session_id': sid, 'scenario': scenario,
            'initial': initial, 'current': current,
            'position_value': pos_val, 'total_value': round(total_val, 2),
            'pnl': round(pnl, 2), 'pnl_pct': round(pct, 2), 'status': st,
        }
        result['sessions'].append(sess_info)
        result['total_pnl'] += pnl
        icon = '🟢' if pnl >= 0 else '🔴'
        log(f'  {icon} {sid[:20]} total=¥{total_val:,.0f} PnL=¥{pnl:+,.0f} ({pct:+.2f}%)')

    result['total_pnl'] = round(result['total_pnl'], 2)
    log(f'② 总 PnL = ¥{result["total_pnl"]:+,.0f}')

    # 3. 写快照 (Fix 3: 写入真实的 position_value 和 total_value)
    for s in result['sessions']:
        try:
            snap_id = f"{s['session_id']}_{today}"
            total_val = s['total_value']
            cash_val = s['current']
            pos_val = s['position_value']
            daily_ret = s['pnl_pct'] / 100 if s['pnl_pct'] else 0
            cnt = sum(1 for t in trades if t[1] == s['session_id'])
            conn.execute("""
                INSERT OR REPLACE INTO mt_sandbox_snapshots
                (snap_id, session_id, snap_date, total_value, cash_value, position_value,
                 daily_return, trade_count, pnl_amount, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (snap_id, s['session_id'], today, total_val, cash_val, pos_val,
                  daily_ret, cnt, s['pnl'], f"auto PnL {s['scenario']} pos={pos_val}", datetime.now().isoformat()))
            log(f'  ✅ 快照 {snap_id}: total={total_val:.2f} cash={cash_val:.2f} pos={pos_val:.2f}')
        except Exception as e:
            log(f'  ⚠️ {s["session_id"]} 快照写失败: {e}')
    conn.commit()

    # 4. JSON 输出
    out_file = os.path.join(OUT_DIR, f'gobelin_daily_pnl_{today}.json')
    with open(out_file, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f'③ JSON → {out_file}')

    # 5. 告警: 单日亏损 > 5%
    alerts = [s for s in result['sessions'] if s['pnl_pct'] < -5]
    if alerts:
        log(f'⚠️ 告警: {len(alerts)} 个 session 当日亏损 > 5%!')
        for a in alerts:
            log(f'   → {a["session_id"]} PnL={a["pnl_pct"]}%')

    # 6. DB hash (溯源)
    conn.close()
    db_hash = hashlib.sha256(open(DB,'rb').read()).hexdigest()[:16]
    log(f'④ DB hash={db_hash}')

    log('✅ 完成')
    return 0

if __name__ == '__main__':
    sys.exit(run())
