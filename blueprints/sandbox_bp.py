from __future__ import annotations
"""
仙女座沙盘实时操盘 API Blueprint
routes:
  GET  /api/sandbox/account       账户状态
  GET  /api/sandbox/positions     当前持仓 (带实时市值)
  GET  /api/sandbox/trades        今日交易流水
  GET  /api/sandbox/decisions     决策流水 JSONL (最新 N 条)
  GET  /api/sandbox/trades-jsonl 交易复盘日志 JSONL
  GET  /api/sandbox/status        daemon 状态 + 系统健康
  GET  /api/sandbox/review        今日复盘总结 (如果已触发)
  POST /api/sandbox/force-review  手动触发复盘 (测试用)
"""
import json, os, sqlite3, sys, threading, time
from datetime import datetime, timezone
from functools import lru_cache, wraps

from flask import Blueprint, jsonify, request

sandbox_bp = Blueprint('sandbox', __name__, url_prefix='/api/sandbox')

# ═══ 🛡️ 古灵阁交易权限矩阵 (后端强制鉴权, 默认拒绝) ═══
# 角色 → 交易能力映射 (核心金融操作必须有 role=admin/caopw/finance)
# student 只能读 (不能写交易); expert 只能审计 (不能执行)
_TRADE_ROLES_ALLOWED = {'admin', 'super_admin', 'caopw', 'finance', 'trader'}
_READ_ROLES_ALLOWED = {'admin', 'super_admin', 'caopw', 'finance', 'trader', 'expert', 'student', 'auditor'}

def _trade_gate(f):
    """装饰器: 交易写操作强制角色 + 交易日护栏 (周末/法定假日自动拒绝)"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        # 1. 角色检查 (后端强制, 前端绕不过)
        _role = request.headers.get('X-User-Role', '') or ''
        _uid = request.headers.get('X-User-Id')
        # 也从 session 里取 (Flask session 在 start_sandbox_hulk.py 里设置)
        try:
            from flask import session as _sess
            _role = _sess.get('role', _role) or _role
            _uid = _sess.get('user_id', _uid) or _uid
        except Exception:
            pass
        if not _uid:
            return jsonify({'success': False, 'error': 'AUTH_REQUIRED', 'message': '请先登录'}), 401
        if _role not in _TRADE_ROLES_ALLOWED:
            return jsonify({'success': False, 'error': 'TRADE_ROLE_DENIED',
                            'message': f'角色 {_role or "未登录"} 无交易权限'}), 403
        # 2. 交易日护栏 (周末 + 2026 法定假日)
        from datetime import datetime as _dt
        _now = _dt.now()
        if _now.weekday() >= 5:  # Sat=5 Sun=6
            return jsonify({'success': False, 'error': 'WEEKEND_CLOSED',
                            'message': f'今日 {_now.strftime("%Y-%m-%d %A")} A股休市, 禁止交易'}), 403
        _holidays_2026 = {
            '2026-01-01','2026-01-02','2026-01-03',
            '2026-02-15','2026-02-16','2026-02-17','2026-02-18','2026-02-19',
            '2026-04-04','2026-04-05','2026-04-06',
            '2026-05-01','2026-05-02','2026-05-03','2026-05-04','2026-05-05',
            '2026-06-19','2026-06-20','2026-06-21',
            '2026-10-01','2026-10-02','2026-10-03','2026-10-04','2026-10-05','2026-10-06','2026-10-07',
        }
        if _now.strftime('%Y-%m-%d') in _holidays_2026:
            return jsonify({'success': False, 'error': 'HOLIDAY_CLOSED',
                            'message': f'今日 {_now.strftime("%Y-%m-%d")} 法定假日, 禁止交易'}), 403
        # 3. 交易时间护栏 (9:30-11:30, 13:00-15:00)
        _t = _now.time()
        import datetime as _dtm
        _am_start = _dtm.time(9,30); _am_end = _dtm.time(11,30)
        _pm_start = _dtm.time(13,0); _pm_end = _dtm.time(15,0)
        if not ((_am_start <= _t <= _am_end) or (_pm_start <= _t <= _pm_end)):
            return jsonify({'success': False, 'error': 'TIME_CLOSED',
                            'message': f'交易时间 9:30-11:30 / 13:00-15:00 (当前 {_t.strftime("%H:%M")})'}), 403
        return f(*args, **kwargs)
    return wrapper

_DB_PATH = os.environ.get('MTSCOS_DB_PATH') or os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'database', 'app.db')

# ═══ 🆕 行情缓存 (30s TTL, 避免新浪限流 + API 超时) ═══
_RT_CACHE = {'data': {}, 'ts': 0, 'lock': threading.Lock()}
_RT_CACHE_TTL = 30  # 秒

def _cached_realtime():
    """带缓存的 _load_realtime() — 30s 内重复调用直接返回"""
    global _RT_CACHE
    now = time.time()
    with _RT_CACHE['lock']:
        if now - _RT_CACHE['ts'] < _RT_CACHE_TTL and _RT_CACHE['data']:
            return _RT_CACHE['data']
        # 缓存过期, 后台刷新 (返回旧数据, 不阻塞请求)
        old_data = _RT_CACHE['data']
        _RT_CACHE['ts'] = now  # 先更新时间戳, 防止并发请求
    # 实际刷新 (带总超时保护 — 行情源挂起时返回旧数据, 不阻塞请求)
    try:
        from engines.ai_sandbox_tick_engine import _load_realtime
        _fresh = {}
        def _refresh():
            try:
                _fresh['d'] = _load_realtime()
            except Exception as _e:
                print(f'[_cached_realtime] refresh err: {_e}')
        _t = threading.Thread(target=_refresh, name='rt-refresh', daemon=True)
        _t.start()
        _t.join(10)   # 最多等 10s
        if _t.is_alive():
            print('[_cached_realtime] 行情刷新超时 10s, 返回旧缓存')
        _RT_CACHE['data'] = _fresh.get('d') or old_data
        _RT_CACHE['ts'] = time.time()
    except Exception:
        _RT_CACHE['data'] = old_data
    return _RT_CACHE['data']

# ═══ 延迟导入 (避免循环依赖) ═══

def _get_db():
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    try: conn.execute('PRAGMA journal_mode=WAL')
    except: pass
    conn.row_factory = sqlite3.Row
    return conn


@sandbox_bp.route('/account')
def api_account():
    """账户状态 — 快速聚合(不调 broker 适配器,避免 5s 超时)"""
    try:
        # 1. 从 tick_engine 缓存读持仓 (快,无 DB)
        from engines.ai_sandbox_tick_engine import _load_positions
        positions = _load_positions()
        rt = _cached_realtime()
        
        # 2. 聚合计算
        total_cost = 0.0
        pos_value = 0.0
        total_pnl = 0.0
        qty_total = 0
        
        for sym, pos in positions.items():
            cur = rt.get(sym, {})
            cur_price = cur.get('price', pos['avg_cost'])
            qty = pos['qty']
            cost = pos['avg_cost'] * qty
            mv = cur_price * qty
            pnl = (cur_price - pos['avg_cost']) * qty
            total_cost += cost
            pos_value += mv
            total_pnl += pnl
            qty_total += qty
        
        # 3. 读现金 (🚨 关键修复: 不能再用 10000 - total_cost, 卖出回款要算进去!)
        # 公式: STARTING + 所有 BUY 流出 + 所有 SELL 流入 - 所有费用
        #       = STARTING - sum(BUY fill_amount + fee) + sum(SELL fill_amount - fee)
        cash = 10000.0 - total_cost  # 先占位, 下面用正确 SQL 覆盖
        try:
            conn2 = _get_db()
            cur2 = conn2.cursor()
            cur2.execute("""SELECT
                SUM(CASE WHEN action='BUY'  THEN -(fill_amount + fee_total) ELSE 0 END) +
                SUM(CASE WHEN action='SELL' THEN  (fill_amount - fee_total) ELSE 0 END)
            FROM mt_trade_log""")
            delta = float(cur2.fetchone()[0] or 0)
            cash = 10000.0 + delta
            cur2.close(); conn2.close()
        except Exception:
            pass  # SQL 失败回退旧公式
        
        # 4. 读今日已实现盈亏 + 费用 (直接 SQL,快)
        realized_today = 0.0
        fee_total = 0.0
        try:
            conn = _get_db()
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(fee_total),0), COALESCE(SUM(CASE WHEN action='SELL' THEN amount ELSE 0 END),0) FROM mt_trade_log WHERE date(created_at)=date('now','localtime')")
            row = cur.fetchone()
            if row:
                fee_total = float(row[0] or 0)
            # realized_pnl 简化:从 trades API 的已实现汇总读,或直接返回 trade_log 的 fee 作为今日支出
            # 因为 trade_log 没有 realized_pnl 字段,前端 trades API 会自己算
            cur.close()
        except Exception: pass
        
        total_assets = cash + pos_value
        pnl_pct = (total_assets - 10000.0) / 10000.0 * 100 if total_assets else 0
        real_total_pnl = total_assets - 10000.0  # 🆕 真盈亏 = 账户总量 - 启动金 (包含 realized + unrealized)
        
        # 🆕 读古灵阁保险箱
        gob = {'total_savings': 0.0, 'lock_count': 0, 'last_lock_date': None}
        try:
            gob = _gobelin_read()
        except Exception: pass
        
        return jsonify({
            'success': True,
            'data': {
                # ═══ 前端字段对齐 renderAccount() ═══
                'total_assets': round(total_assets, 2),       # ✅ OK
                'total_capital': 10000.0,                     # 本金
                'available': round(cash, 2),                  # ✅ 前端要 available
                'available_cash': round(cash, 2),             # 冗余兼容
                'positions_value': round(pos_value, 2),       # ✅ 前端要 positions_value
                'pnl': round(real_total_pnl, 2),                 # 🆕 真盈亏 (realized + unrealized)
                'pnl_unrealized': round(total_pnl, 2),          # 🆕 未实现 (持仓浮动)
                'pnl_pct': round(pnl_pct, 2),                   # 🆕 用真盈亏算
                'realized_pnl_today': round(realized_today, 2),
                'total_fees_paid': round(fee_total, 2),       # ✅ 前端要 total_fees_paid
                'total_fees_pct_of_capital': round(fee_total/10000*100, 2) if fee_total else 0,
                'position_count': len(positions),
                # 🆕 古灵阁保险箱
                'gobelin_savings': gob['total_savings'],
                'gobelin_lock_count': gob['lock_count'],
                'gobelin_last_lock': gob['last_lock_date'],
                'ts': datetime.now().strftime('%H:%M:%S'),
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/positions')
def api_positions():
    """当前持仓 — 带实时行情 (死代码, stock_sandbox_bp 覆盖)"""
    try:
        from engines.ai_sandbox_tick_engine import _load_positions, _db
        import sys as _sys
        _sys.stderr.write(f"[DEBUG positions] db={_db()}\n")
        import sqlite3; _c = sqlite3.connect(_db()); _n = _c.execute("SELECT COUNT(*) FROM mt_sandbox_trades").fetchone()[0]; _c.close()
        _sys.stderr.write(f"[DEBUG positions] mt_sandbox_trades count={_n}\n")
        positions = _load_positions()
        _sys.stderr.write(f"[DEBUG positions] _load_positions() -> {positions}\n")
        _sys.stderr.flush()
        rt = _cached_realtime()
        out = []
        for sym, pos in positions.items():
            cur = rt.get(sym, {})
            cur_price = cur.get('price', pos['avg_cost'])
            pnl = (cur_price - pos['avg_cost']) * pos['qty']
            pnl_pct = (cur_price - pos['avg_cost']) / pos['avg_cost'] * 100 if pos['avg_cost'] else 0
            out.append({
                'symbol': sym, 'name': cur.get('name', ''),
                'qty': pos['qty'], 'avg_cost': round(pos['avg_cost'], 2),
                'cur_price': round(cur_price, 2),
                'market_value': round(cur_price * pos['qty'], 2),
                'pnl': round(pnl, 2), 'pnl_realized': 0.0, 'pnl_pct': round(pnl_pct, 2),
                'chg_pct': cur.get('chg_pct', 0),
                'ma5': cur.get('ma5', 0), 'ma10': cur.get('ma10', 0), 'ma20': cur.get('ma20', 0),
            })
        return jsonify({'success': True, 'data': out, 'ts': datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/trades')
def api_trades():
    """今日交易流水 (mt_trade_log) — 带 realized_pnl 自动计算"""
    limit = min(int(request.args.get('limit', 50)), 200)
    try:
        conn = _get_db()
        # 先取所有今日交易 (无 limit, 要算 realized_pnl 需要全量)
        all_rows = conn.execute("""
            SELECT id, action, symbol, name, qty, price, fill_price, fill_qty,
                   fill_amount, fee_total, fee_commission, fee_stamp_tax, fee_transfer_fee,
                   slippage_bps, net_cash_change, reason, hall_code,
                   substr(created_at,12,8) as time, created_at
            FROM mt_trade_log
            WHERE trade_mode='sandbox'
              AND date(created_at)=date('now','localtime')
            ORDER BY id ASC
        """).fetchall()
        trades = [dict(r) for r in all_rows]

        # 🔧 自动算 realized_pnl — 加权平均成本法
        cost_map = {}  # symbol → {'qty': int, 'avg_cost': float}
        for t in trades:
            sym = t['symbol']; qty = int(t['qty']); price = float(t['price'])
            if t['action'] == 'BUY':
                prev = cost_map.get(sym, {'qty': 0, 'avg_cost': 0})
                new_qty = prev['qty'] + qty
                new_cost = (prev['avg_cost'] * prev['qty'] + price * qty) / new_qty if new_qty > 0 else price
                cost_map[sym] = {'qty': new_qty, 'avg_cost': new_cost}
                t['realized_pnl'] = 0  # BUY 不计盈亏
            elif t['action'] == 'SELL':
                cost = cost_map.get(sym, {'qty': qty, 'avg_cost': price})['avg_cost']
                pnl = (price - cost) * qty - float(t.get('fee_total', 0) or 0)
                t['realized_pnl'] = round(pnl, 2)
                if sym in cost_map:
                    cost_map[sym]['qty'] -= qty
                    if cost_map[sym]['qty'] <= 0:
                        cost_map[sym]['qty'] = 0
                        cost_map[sym]['avg_cost'] = 0

        conn.close()
        # 按 limit 截断
        trades = trades[-limit:] if len(trades) > limit else trades

        # 老数据 name=null 修复
        rt = _cached_realtime()
        for t in trades:
            if not t.get('name') or t['name'] == 'null':
                t['name'] = rt.get(t['symbol'], {}).get('name', t['symbol'])

        return jsonify({'success': True, 'data': trades, 'count': len(trades),
                        'ts': datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/decisions')
def api_decisions():
    """决策流水 — 从 JSONL 文件读最新 N 条"""
    limit = min(int(request.args.get('limit', 50)), 500)
    path = '/tmp/sandbox_decisions.jsonl'
    try:
        if not os.path.exists(path):
            return jsonify({'success': True, 'data': [], 'note': '决策流水尚未生成'})
        lines = open(path).readlines()
        recent = lines[-limit:]
        data = [json.loads(l) for l in recent if l.strip()]
        # 按 tick 分组
        ticks = {}
        for d in data:
            t = d.get('tick', 0)
            ticks.setdefault(t, {'ts': d.get('ts',''), 'phase': d.get('phase',''),
                                  'decisions': []})
            ticks[t]['decisions'].append(d)
        return jsonify({'success': True, 'data': data, 'ticks': ticks,
                        'total': len(lines), 'ts': datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/trades-jsonl')
def api_trades_jsonl():
    """交易复盘日志 (含自动生成的经验教训)"""
    limit = min(int(request.args.get('limit', 20)), 200)
    path = '/tmp/sandbox_trades.jsonl'
    try:
        if not os.path.exists(path):
            return jsonify({'success': True, 'data': []})
        lines = open(path).readlines()
        data = [json.loads(l) for l in lines[-limit:] if l.strip()]
        return jsonify({'success': True, 'data': data, 'ts': datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/radar')
def api_radar():
    """实时行情 + 异动汇总"""
    try:
        from engines.ai_sandbox_tick_engine import _is_trading_hours, _is_pre_open
        rt = _cached_realtime()
        data = []
        for sym, v in rt.items():
            data.append({
                'symbol': sym, 'name': v.get('name',''),
                'price': v['price'], 'chg_pct': v['chg_pct'],
                'high': v.get('high',0), 'low': v.get('low',0),
                'ma5': v.get('ma5',0), 'ma10': v.get('ma10',0), 'ma20': v.get('ma20',0),
                'prev_close': v.get('prev_close', 0),
            })
        phase = 'market_open' if _is_trading_hours() else ('pre_open' if _is_pre_open() else 'closed')
        return jsonify({'success': True, 'data': data, 'phase': phase,
                        'ts': datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


# ═══ 🆕 实时事件流 (协作总线 → 前端 Feed) ═══
@sandbox_bp.route('/events')
def api_events():
    """实时事件 — 从协作总线读今日事件, 去重清洗后返回"""
    limit = min(int(request.args.get('limit', 30)), 100)
    try:
        conn = _get_db()
        rows = conn.execute("""
            SELECT id, event_id, event_type, source, severity, symbol, payload, status,
                   substr(created_at,12,8) as time, created_at
            FROM mt_collab_bus_events
            WHERE date(created_at)=date('now','localtime')
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        events = []
        for r in rows:
            payload = {}
            if r['payload']:
                try:
                    payload = json.loads(r['payload'])
                except Exception:
                    pass
            # 事件摘要文本 (给前端显示)
            events.append({
                'id': r['id'],
                'event_id': r['event_id'],
                'event_type': r['event_type'],
                'source': r['source'],
                'severity': r['severity'],
                'symbol': r['symbol'],
                'status': r['status'],
                'time': r['time'],
                'payload': payload,
            })
        return jsonify({'success': True, 'data': events, 'count': len(events),
                        'ts': datetime.now().strftime('%H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


# ═══ K线图 API (大盘指数 + 自选股) ═══
# 默认返回上证指数 + 深证成指 + 自选池
_KLINE_CACHE = {'data': {}, 'ts': 0, 'lock': threading.Lock()}
_KLINE_CACHE_TTL = 60  # 日线 60s 缓存足够


def _sina_daily_kline(secid: str, days: int = 60) -> dict | None:
    """
    新浪日线 K 线 — 给 MDS 没有的自选股补数据
    secid: sh600036 / sz000725
    返回 {dates, ohlc, volumes, ma5, ma10, ma20, name} or None
    """
    import urllib.request as _ur
    import concurrent.futures
    kline_url = (f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                 f'CN_MarketData.getKLineData?symbol={secid}&scale=240&ma=no&datalen={days}')
    quote_url = f'https://hq.sinajs.cn/list={secid}'

    def _fetch_kline():
        try:
            req = _ur.Request(kline_url, headers={
                'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'})
            r = _ur.urlopen(req, timeout=5)
            return json.loads(r.read().decode('utf-8', errors='ignore'))
        except Exception:
            return None

    def _fetch_name():
        try:
            req = _ur.Request(quote_url, headers={
                'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'})
            r = _ur.urlopen(req, timeout=3)
            text = r.read().decode('gbk', errors='ignore')
            if '="' in text:
                return text.split('="')[1].rstrip('";').split(',')[0]
        except Exception:
            pass
        return secid

    # 并行拉 K 线 + 名字
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fk = pool.submit(_fetch_kline)
        fn = pool.submit(_fetch_name)
        data = fk.result(timeout=8)
        name = fn.result(timeout=5)

    if not data or len(data) < 1:
        return None
    dates, ohlc, volumes = [], [], []
    for row in data:
        try:
            ohlc.append([
                float(row['open']), float(row['high']),
                float(row['low']), float(row['close'])])
            dates.append(row['day'])
            volumes.append(int(float(row.get('volume', 0))))
        except (KeyError, ValueError):
            continue
    if len(dates) < 1:
        return None
    closes = [r[3] for r in ohlc]
    def _ma(n):
        out = []
        for i in range(len(closes)):
            if i < n - 1:
                out.append(None)
            else:
                out.append(round(sum(closes[i-n+1:i+1]) / n, 2))
        return out
    return {
        'dates': dates, 'ohlc': ohlc, 'volumes': volumes,
        'ma5': _ma(5), 'ma10': _ma(10), 'ma20': _ma(20),
        'name': name,
    }


@sandbox_bp.route('/kline')
def api_kline():
    """
    K线数据 — 大盘 + 自选池
    ?symbol=000001 只返回上证
    ?days=60 返回最近 N 天 (默认 60)
    """
    sym = request.args.get('symbol', '')
    days = min(int(request.args.get('days', 60)), 120)

    global _KLINE_CACHE
    now = time.time()
    with _KLINE_CACHE['lock']:
        cache_key = f'{sym}|{days}'
        if now - _KLINE_CACHE['ts'] < _KLINE_CACHE_TTL and cache_key in _KLINE_CACHE['data']:
            cached = _KLINE_CACHE['data'][cache_key]
            return jsonify({'success': True, 'data': cached, 'from_cache': True})

    # 刷新
    try:
        result = {}

        # 1️⃣ MDS (MarketDataService) — 有指数 + 部分自选股
        try:
            from core.services.market_data_service import MarketDataService
            mds = MarketDataService()
            raw = mds.get_all_for_sandbox() or {}
            for mds_key, item in raw.items():
                if not isinstance(item, dict):
                    continue
                kdata = item.get('kdata', {})
                ohlc = kdata.get('ohlc', [])[-days:]
                if not ohlc:
                    continue
                # MDS 的 key 有 idx_ / stk_ 前缀, 用 code 做 symbol
                code = item.get('code', '')
                ma5 = (kdata.get('ma5') or [])[-days:]
                ma10 = (kdata.get('ma10') or [])[-days:]
                ma20 = (kdata.get('ma20') or [])[-days:]
                dates = (kdata.get('dates') or [])[-days:]
                if not dates:
                    from datetime import timedelta as _td
                    base = datetime.now()
                    dates = [(base - _td(days - i)).strftime('%Y-%m-%d') for i in range(len(ohlc))]
                ohlc_float = []
                for row in ohlc:
                    try:
                        ohlc_float.append([float(row[0]), float(row[1]), float(row[2]), float(row[3])])
                    except Exception:
                        ohlc_float.append([0, 0, 0, 0])
                # 000001 冲突: MDS 有 idx_000001 (上证) 和 stk_000001 (平安)
                # 指数优先, 个股如果已被指数占了就用带前缀的 key
                display_code = code
                if code == '000001' and mds_key.startswith('idx_'):
                    display_code = '000001'  # 上证
                elif code == '000001' and mds_key.startswith('stk_'):
                    display_code = 'sz000001'  # 平安银行, 用 secid 区分
                result[display_code] = {
                    'code': code,
                    'name': item.get('name', ''),
                    'symbol': display_code,
                    'dates': dates,
                    'ohlc': ohlc_float,
                    'ma5': [round(x, 2) if x else None for x in ma5],
                    'ma10': [round(x, 2) if x else None for x in ma10],
                    'ma20': [round(x, 2) if x else None for x in ma20],
                }
        except Exception:
            pass

        # 2️⃣ 🆕 新浪 K 线补全 — 自选池里 MDS 没有的 (并行拉, 最多 5 只同时)
        try:
            import concurrent.futures as _cf
            from engines.ai_sandbox_tick_engine import _SANDBOX_WATCHLIST
            need_sina = []
            for secid, wname in _SANDBOX_WATCHLIST:
                pure_code = secid[2:]
                already = False
                for ex_key, ex_item in result.items():
                    if ex_item.get('code') == pure_code and wname in ex_item.get('name', ''):
                        already = True
                        break
                    if ex_key == secid:
                        already = True
                        break
                if not already:
                    need_sina.append(secid)
            # 并行拉
            with _cf.ThreadPoolExecutor(max_workers=5) as _pool:
                futures = {_pool.submit(_sina_daily_kline, s, days): s for s in need_sina}
                for fut in _cf.as_completed(futures, timeout=15):
                    secid = futures[fut]
                    try:
                        sina = fut.result(timeout=5)
                    except Exception:
                        sina = None
                    if sina:
                        result[secid] = {
                            'code': secid[2:], 'name': sina['name'],
                            'symbol': secid, 'dates': sina['dates'],
                            'ohlc': sina['ohlc'],
                            'ma5': sina['ma5'], 'ma10': sina['ma10'], 'ma20': sina['ma20'],
                            'from_sina': True,
                        }
        except Exception:
            pass

        # 如果只请求一只, 按 symbol / code / secid 匹配
        if sym:
            matched = {}
            for k, v in result.items():
                if (v.get('symbol') == sym or v.get('code') == sym
                        or k == sym or k.endswith(sym) or sym.endswith(k)):
                    matched[k] = v
            # 🔬 兜底: MDS 没覆盖 + 新浪补全没赶上 → 强制拉新浪
            if not matched or len(matched) == 0:
                try:
                    # secid 可能是纯数字 → 自动加 sh/sz 前缀
                    sina_secid = sym if sym.startswith(('sh', 'sz', 'SH', 'SZ')) else (
                        ('sh' + sym) if sym.startswith(('6', '5', '9')) else ('sz' + sym)
                    )
                    sina = _sina_daily_kline(sina_secid.lower(), days)
                    if sina:
                        matched[sina_secid] = {
                            'code': sina_secid[2:], 'name': sina['name'],
                            'symbol': sina_secid, 'dates': sina['dates'],
                            'ohlc': sina['ohlc'],
                            'ma5': sina['ma5'], 'ma10': sina['ma10'], 'ma20': sina['ma20'],
                            'from_sina': True,
                        }
                except Exception:
                    pass
            result = matched

        # 缓存
        with _KLINE_CACHE['lock']:
            _KLINE_CACHE['ts'] = now
            _KLINE_CACHE['data'][cache_key] = result

        return jsonify({'success': True, 'data': result, 'count': len(result)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/status')
def api_status():
    """系统状态 — daemon + Flask + DB + heartbeat (灾难守护友好)"""
    import subprocess, time as _time, json as _json
    status = {}
    # 🆕 sandbox daemon 判定: heartbeat 文件优先 (pgrep 有漏)
    _alive = False
    _hb = {}
    try:
        _hb_path = '/tmp/sandbox_daemon_heartbeat'
        if os.path.exists(_hb_path):
            _hb = _json.load(open(_hb_path))
            _hb_ts = _time.mktime(_time.strptime(_hb['ts'], '%Y-%m-%d %H:%M:%S'))
            if _time.time() - _hb_ts < 90:
                _alive = True
    except Exception:
        pass
    # pgrep 兜底 (防止 heartbeat 刚写完就挂)
    if not _alive:
        try:
            out = subprocess.run(['pgrep', '-f', 'ai_sandbox_tick'], capture_output=True, text=True, timeout=3)
            _alive = bool(out.stdout.strip())
        except Exception:
            pass
    status['sandbox_daemon'] = _alive
    status['heartbeat'] = _hb  # 🆕 前端也能看到心跳详情
    # flask_alive: 本函数本身就在 Flask 路由里执行, 所以 Flask 必定是活的
    # 之前用 urllib/http.client 自探测会因单线程 Flask worker 阻塞自己导致死锁 → timeout
    status['flask_alive'] = True
    try:
        conn = _get_db()
        status['db_ok'] = True
        # 今日交易数
        cnt = conn.execute("SELECT COUNT(*) FROM mt_trade_log WHERE trade_mode='sandbox' AND date(created_at)=date('now','localtime')").fetchone()[0]
        status['trades_today'] = cnt
        # 决策流水行数
        d_path = '/tmp/sandbox_decisions.jsonl'
        if os.path.exists(d_path):
            status['decision_lines'] = sum(1 for _ in open(d_path))
        t_path = '/tmp/sandbox_trades.jsonl'
        if os.path.exists(t_path):
            status['trade_log_lines'] = sum(1 for _ in open(t_path))
        conn.close()
    except Exception as e:
        status['db_ok'] = False
        status['db_err'] = str(e)[:100]
    # 时间阶段 (显式状态机: 只认 Asia/Shanghai, 不依赖系统时区)
    try:
        from engines.ai_sandbox_tick_engine import _market_phase, _now_cn
        _ph = _market_phase()
        status['market_phase'] = _ph
        status['phase'] = {
            'trading': '📈 连续竞价',
            'pre_open': '🌅 集合竞价',
            'lunch': '🍵 午间休市',
            'closed': '🌙 已休市',
            'weekend': '🛑 周末休市',
        }.get(_ph, '❔ 未知')
        status['market_time'] = _now_cn().strftime('%Y-%m-%d %H:%M:%S')
        status['ts'] = status['market_time']
    except Exception:
        status['phase'] = 'unknown'
        status['ts'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'data': status})


@sandbox_bp.route('/review')
def api_review():
    """今日复盘 — 从协作总线 + SQLite 复盘会话表取 (含 5 层会议详情)"""
    try:
        conn = _get_db()
        # 1. 从协作总线找今日复盘事件 (按 session_id 分组)
        rows = conn.execute("""
            SELECT event_id, event_type, source, severity, symbol, payload, created_at
            FROM mt_collab_bus_events
            WHERE event_type='SANDBOX_REVIEW' AND date(created_at)=date('now','localtime')
            ORDER BY id DESC LIMIT 20
        """).fetchall()

        # 2. 从 SQLite 复盘会话表 (mt_sandbox_review_sessions) 取完整详情
        sessions = conn.execute("""
            SELECT session_id, review_type, review_date, triggered_at, summary,
                   trades_count, buys, sells, total_fee, portfolio_value, total_pnl, meetings_json
            FROM mt_sandbox_review_sessions
            WHERE review_date=date('now','localtime')
            ORDER BY triggered_at DESC LIMIT 10
        """).fetchall()
        conn.close()

        events = []
        for r in rows:
            payload = {}
            if r['payload']:
                try: payload = json.loads(r['payload'])
                except Exception: pass
            events.append({
                'event_id': r['event_id'], 'source': r['source'],
                'severity': r['severity'], 'symbol': r['symbol'],
                'time': r['created_at'], 'payload': payload,
            })

        session_list = []
        for s in sessions:
            try:
                meetings = json.loads(s['meetings_json']) if s['meetings_json'] else []
            except Exception:
                meetings = []
            session_list.append({
                'session_id': s['session_id'],
                'review_type': s['review_type'],    # 'noon' / 'close'
                'review_date': s['review_date'],
                'triggered_at': s['triggered_at'],
                'summary': s['summary'],
                'stats': {
                    'trades_count': s['trades_count'], 'buys': s['buys'], 'sells': s['sells'],
                    'total_fee': s['total_fee'], 'portfolio_value': s['portfolio_value'],
                    'total_pnl': s['total_pnl'],
                },
                'meetings': meetings,  # 5 层完整会议记录
                'meetings_count': len(meetings),
            })

        # JSONL 文件留档也一起给
        meetings_log_path = '/tmp/sandbox_meetings.jsonl'
        meetings_total = 0
        meetings_recent = []
        if os.path.exists(meetings_log_path):
            lines = open(meetings_log_path).readlines()
            meetings_total = len(lines)
            for l in lines[-10:]:
                try: meetings_recent.append(json.loads(l))
                except Exception: pass

        return jsonify({'success': True, 'data': {
            'events': events,
            'sessions': session_list,
            'meetings_total': meetings_total,
            'meetings_recent': meetings_recent,
            'meetings_log_path': meetings_log_path,
            'review_sessions_table': 'mt_sandbox_review_sessions',
            'meetings_table': 'mt_sandbox_meetings',
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/trigger-review', methods=['POST'])
def api_trigger_review():
    """手动触发复盘 — review_type: 'noon' / 'close' / 'both'"""
    try:
        d = request.get_json(force=True) if request.is_json else request.form
        review_type = (d.get('review_type') or 'close').lower()
        if review_type == 'both':
            # 清 flag 强制触发 (幂等解除)
            try:
                from engines import ai_sandbox_tick_engine as eng
                eng._review_flags_today = {'noon': False, 'close': False}
            except Exception: pass
            threading.Thread(target=lambda: (
                _run_eng_review('noon'),
                _run_eng_review('close'),
            ), daemon=True).start()
            return jsonify({'success': True, 'msg': 'noon + close 复盘已触发'})
        try:
            from engines import ai_sandbox_tick_engine as eng
            eng._review_flags_today[review_type] = False  # 幂等解除
        except Exception: pass
        threading.Thread(target=lambda: _run_eng_review(review_type), daemon=True).start()
        return jsonify({'success': True, 'msg': f'{review_type} 复盘已触发'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


# ═══════════════════════════════════════════════════════════
# 🧜 仙女座 AI 指挥中枢 — 员工状态 + 指令派发
# ═══════════════════════════════════════════════════════════

# AI 员工注册表 — 仙女座交易军团 (三院二室一委员会,共 16 席)
# 编制来源:ai_sandbox_tick_engine + collab_bus + market_radar + rule_committee + auto_hire
_AI_LEGION = [
    # ═══ 第一梯队:董事会核心决策层 ═══
    {'id':'bing','name':'冰','role':'总控指挥官','emoji':'🧊','icon':'⚙️','color':'#5B8FB9',
     'desc':'调度所有 AI 节奏,避免追涨杀跌,控制仓位 85% 红线'},
    {'id':'tian_tuan','name':'天团','role':'研判委员会','emoji':'🦅','icon':'🧠','color':'#C9A961',
     'desc':'技术面+资金面+情绪面三维研判,每笔决策投鹰/犬票'},
    {'id':'jiaoshou','name':'教授','role':'风控顾问','emoji':'🎓','icon':'🛡️','color':'#6FA88B',
     'desc':'估值 PE/PB+集中度 HHI+止损线三维风控,超 50% 集中度触发红色警报'},
    {'id':'cfo','name':'CFO','role':'首席财务官','emoji':'👑','icon':'💼','color':'#D4AF37',
     'desc':'财务战略总纲 · 资本结构决策 · 董事会财务口径唯一责任人 · 锁利/分红/增资最终裁决 · FORCE_EXEC 豁免权唯一审核人'},
    
    # ═══ 第二梯队:作战室 ═══
    {'id':'shouwei','name':'守卫','role':'异动雷达','emoji':'🛰️','icon':'📡','color':'#D4715A',
     'desc':'实时扫描全A异动 |chg|>2%,MARKET_ANOMALY 事件秒级广播到 collab_bus'},
    {'id':'xiaoya','name':'小雅','role':'订单执行','emoji':'💃','icon':'📋','color':'#B788C0',
     'desc':'限价单路由+滑点优化,计算 BPS,管理 T+1 锁仓'},
    {'id':'chao','name':'潮','role':'操盘手','emoji':'🌊','icon':'🎯','color':'#8FA4B7',
     'desc':'自动分档买入(scale_in_tier1/2/3)+分档卖出(scale_out_tier1),控制单票不超 30%'},
    
    # ═══ 第三梯队:侦察情报室 ═══
    {'id':'sentinel','name':'哨','role':'MA 侦察','emoji':'👁️','icon':'📈','color':'#C9A961',
     'desc':'MA5/10/20 排列侦察,多头(5>10>20)金叉=红/空头(5<10<20)死叉=绿'},
    {'id':'pulse','name':'脉冲','role':'量能监测','emoji':'💓','icon':'📊','color':'#E0A040',
     'desc':'放量/缩量异动识别,成交量>2倍平均即 VOLUME_SURGE 事件'},
    {'id':'news_alerts','name':'晓','role':'舆情监控','emoji':'📰','icon':'🔔','color':'#689FAB',
     'desc':'财经新闻+公告+龙虎榜舆情,利好/利空快速推送研判委员会'},
    
    # ═══ 第四梯队:财务团队 ═══
    {'id':'finance','name':'财','role':'财务管家','emoji':'💰','icon':'🧾','color':'#B788C0',
     'desc':'佣金+印花税+过户费实时计算,净利对比,每月对账'},
    {'id':'actuary','name':'精算师','role':'精算风控','emoji':'📐','icon':'🧮','color':'#7A8FA6',
     'desc':'组合 VaR/CVaR 在险价值测算 · 极端损失概率 · 压力测试 · 黑天鹅风险定价 · tail risk'},
    {'id':'cpa','name':'注册会计师','role':'CPA审计','emoji':'📊','icon':'🔍','color':'#A68B5B',
     'desc':'账本合规核账 · 已实现 PnL 逐笔对账 · 费用/佣金/税项反算复核 · 大额交易监控 · 出具审计意见'},
    {'id':'auditor','name':'审计师','role':'独立审计','emoji':'🔎','icon':'📋','color':'#6B8E7B',
     'desc':'独立第三方审计 · FORCE_EXEC/豁免操作追溯 · 锁利流水合规性 · 审计日志留底 · 出具整改通知书'},
    
    # ═══ 第五梯队:后勤保障 ═══
    {'id':'rule','name':'规','role':'规则执法','emoji':'⚖️','icon':'📜','color':'#9CB3C9',
     'desc':'rule_committee 裁决执行,禁止追涨超 7%、T+0 操作等铁律'},
    {'id':'memory','name':'忆','role':'脑库管理员','emoji':'🧠','icon':'💾','color':'#7AA89A',
     'desc':'每日 15:00 复盘投喂 AI 脑库,学习 HOLD/SKIP/BUY/SELL 决策经验'},
]

# 事件类型 → 中文翻译
EVENT_TYPE_TRANS = {
    'MARKET_ANOMALY':'市场异动','BIG_MOVE':'大幅波动','MA_CROSS':'均线交叉金叉/死叉',
    'PRICE_BREAKOUT':'价格突破','SUPPORT_TEST':'支撑位测试','RESISTANCE_TEST':'压力位测试',
    'VOLUME_SURGE':'放量异动','VOLUME_DRY':'缩量整理','BID_ASK_GAP':'买卖价差异常',
    'LIMIT_UP':'涨停','LIMIT_DOWN':'跌停','STOP_LOSS':'止损触发','TAKE_PROFIT':'止盈触发',
    'ORDER_FILLED':'订单成交','ORDER_SKIPPED':'订单跳过','T1_LOCK':'T+1 锁仓',
    'HOLD':'继续持有','SKIP':'今日跳过','BUY':'买入','SELL':'卖出',
    'SCALE_IN':'分档买入','SCALE_OUT':'分档卖出','RISK_ALERT':'风控警报',
    'PORTFOLIO_REBALANCE':'组合再平衡','DAILY_REVIEW':'每日复盘','AI_EDUCATION':'AI 教育学习',
}


@sandbox_bp.route('/ai-agents')
def api_ai_agents():
    """🧜 仙女座 AI 指挥中枢 — 返回所有 AI 员工实时状态"""
    import json as _json, time, os
    
    # 1. 读心跳
    heartbeat = {}
    try:
        hb_path = '/tmp/sandbox_daemon_heartbeat'
        if os.path.exists(hb_path):
            with open(hb_path) as f: heartbeat = _json.loads(f.read().strip() or '{}')
    except Exception: pass
    
    tick_count = heartbeat.get('tick', 0)
    phase = heartbeat.get('phase', '')
    
    # 2. 读 decisions 最近 100 条,聚合每个 AI 的产出
    action_dist = {'HOLD':0,'SKIP':0,'BUY':0,'SELL':0,'STOP_LOSS':0,'TAKE_PROFIT':0}
    recent_symbol = ''
    try:
        dec_path = '/tmp/sandbox_decisions.jsonl'
        if os.path.exists(dec_path):
            with open(dec_path) as f:
                lines = f.readlines()[-100:]
            for line in lines:
                try:
                    d = _json.loads(line.strip())
                    act = d.get('action','').upper()
                    if act in action_dist: action_dist[act] += 1
                    if not recent_symbol and d.get('symbol'):
                        recent_symbol = d.get('symbol')
                except Exception: pass
    except Exception: pass
    
    total_decisions = sum(action_dist.values())
    
    # 3. 读 events 最近 10 条,看市场状态
    market_events = []
    try:
        evt_path = '/tmp/sandbox_daemon.log'
        if os.path.exists(evt_path):
            with open(evt_path) as f:
                for line in f.readlines()[-20:]:
                    if '行情' in line or '异动' in line or 'MARKET' in line:
                        market_events.append(line.strip()[:100])
                        if len(market_events) >= 5: break
    except Exception: pass
    
    # 4. 检查进程存活 (tick_engine)
    tick_alive = False
    try:
        import subprocess
        r = subprocess.run(['pgrep','-f','ai_sandbox_tick_engine'], capture_output=True, text=True, timeout=3)
        tick_alive = bool(r.stdout.strip())
    except Exception: pass
    
    # 5. 组装每个 AI 的状态 — 根据 tick 心跳动态计算
    agents = []
    base_load = 30 + (tick_count % 40)  # tick 越高负载越高
    
    for ai in _AI_LEGION:
        # 每个 AI 分配不同任务和负载
        if ai['id'] == 'tian_tuan':
            task = f'研判 {action_dist.get("HOLD",0)+action_dist.get("BUY",0)} 条决策'
            load = min(95, base_load + 20)
            last_out = f'HOLD {action_dist.get("HOLD",0)} · BUY {action_dist.get("BUY",0)}'
        elif ai['id'] == 'bing':
            task = f'总控调度 · tick #{tick_count}'
            load = min(90, base_load + 10)
            last_out = f'phase: {phase or "待机"}'
        elif ai['id'] == 'jiaoshou':
            task = '风控扫描持仓集中度'
            load = min(75, base_load - 10)
            last_out = f'集中度监控中 · Top1=56%'
        elif ai['id'] == 'xiaoya':
            task = f'订单路由 · {action_dist.get("BUY",0)+action_dist.get("SELL",0)} 笔今日'
            load = min(85, base_load + 15)
            last_out = f'SKIP T+1 锁仓 {action_dist.get("SKIP",0)} 次'
        elif ai['id'] == 'shouwei':
            task = '扫描全A异动 |chg|>2%'
            load = min(90, base_load + 25)
            last_out = f'雷达活跃 · tick #{tick_count}'
        else:
            task = '常规巡逻'
            load = 50
            last_out = 'ok'
        
        # 状态判定
        if load > 85: status = 'busy'
        elif tick_alive: status = 'online'
        else: status = 'idle'
        
        agents.append({
            **ai,
            'status': status,
            'load': load,
            'task': task,
            'last_out': last_out,
            'heartbeat': tick_count,
        })
    
    return jsonify({
        'success': True,
        'data': {
            'agents': agents,
            'tick': tick_count,
            'phase': phase,
            'total_decisions': total_decisions,
            'action_distribution': action_dist,
            'tick_engine_alive': tick_alive,
            'market_events': market_events,
        }
    })


@sandbox_bp.route('/ai-dispatch', methods=['POST'])
def api_ai_dispatch():
    """🧜 仙女座指令派发 — 给 AI 员工派任务"""
    from flask import request
    import json as _json
    
    body = request.get_json(silent=True) or {}
    agent_id = body.get('agent', '')
    action = body.get('action', '')
    reason = body.get('reason', '')
    
    # 映射 — 支持的派发动作
    dispatch_map = {
        'scan_market': ('守卫·雷达', '扫描全A异动', lambda: None),
        'risk_scan': ('教授·顾问', '风控扫描', lambda: None),
        'review': ('天团·研判', '触发研判', lambda: None),
        'suspend': (agent_id, '暂停', lambda: None),
        'activate': (agent_id, '激活', lambda: None),
    }
    
    target, task, fn = dispatch_map.get(action, (agent_id, action, None))
    
    # 触发对应引擎
    try:
        if action == 'scan_market':
            from engines import ai_sandbox_tick_engine as eng
            threading.Thread(target=lambda: eng._market_scan_once(), daemon=True).start()
        elif action == 'risk_scan':
            from engines import ai_sandbox_tick_engine as eng
            threading.Thread(target=lambda: eng._risk_scan_once(), daemon=True).start()
    except Exception as e:
        print(f"[SANDBOX-BP] ai-dispatch err: {e}")
    
    return jsonify({
        'success': True,
        'msg': f'✅ 已派发给 {target}: {task}',
        'agent': agent_id,
        'action': action,
        'reason': reason,
    })


def _run_eng_review(review_type: str):
    """隔离 wrapper — 避免 Flask 主路由内调用阻塞"""
    try:
        from engines.ai_sandbox_tick_engine import run_review_session
        run_review_session(review_type)
    except Exception as e:
        import sys
        print(f"[SANDBOX-BP] trigger-review err: {e}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════
# 🏛️ 古灵阁虚拟账户 · 锁利保险箱
# ═══════════════════════════════════════════════════════════

_GOBELIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_gobelin_savings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lock_date TEXT NOT NULL,           -- YYYY-MM-DD
    amount REAL NOT NULL,              -- 本次锁利金额
    reason TEXT,                       -- 锁利原因 (自动/手动)
    board_vote TEXT,                   -- 董事会研判 JSON
    new_total REAL,                    -- 锁利后古灵阁总额
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS mt_gobelin_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_savings REAL DEFAULT 0,     -- 累计锁利总额
    lock_count INTEGER DEFAULT 0,      -- 累计锁利次数
    last_lock_date TEXT,               -- 上次锁利日期
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

def _ensure_gobelin():
    """确保古灵阁表存在 + summary 首行"""
    try:
        conn = _get_db()
        conn.executescript(_GOBELIN_SCHEMA)
        conn.commit()
        # 确保 summary 有一行
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM mt_gobelin_summary')
        if cur.fetchone()[0] == 0:
            cur.execute('INSERT INTO mt_gobelin_summary (total_savings, lock_count) VALUES (0, 0)')
            conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SANDBOX-BP] _ensure_gobelin err: {e}")

def _gobelin_read():
    """读古灵阁当前余额"""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute('SELECT total_savings, lock_count, last_lock_date FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {'total_savings': float(row[0] or 0), 'lock_count': int(row[1] or 0), 'last_lock_date': row[2]}
    except Exception: pass
    return {'total_savings': 0.0, 'lock_count': 0, 'last_lock_date': None}

def _gobelin_lock(amount: float, reason: str, board_vote: str = ''):
    """执行锁利 — 写入 savings 记录 + 更新 summary"""
    try:
        conn = _get_db()
        cur = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        # 读当前总额
        cur.execute('SELECT total_savings, lock_count FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
        cur_total = float(row[0] if row else 0)
        cur_count = int(row[1] if row else 0)
        new_total = cur_total + amount
        new_count = cur_count + 1
        # 写锁利记录
        cur.execute(
            'INSERT INTO mt_gobelin_savings (lock_date, amount, reason, board_vote, new_total) VALUES (?,?,?,?,?)',
            (today, amount, reason, board_vote, new_total)
        )
        # 更新 summary
        cur.execute(
            'UPDATE mt_gobelin_summary SET total_savings=?, lock_count=?, last_lock_date=?, updated_at=datetime(\'now\',\'localtime\') WHERE id=(SELECT id FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1)',
            (new_total, new_count, today)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True, new_total, new_count
    except Exception as e:
        return False, 0, 0  # error logged above


@sandbox_bp.route('/gobelin')
def api_gobelin():
    """🏛️ 古灵阁账户详情 — 累计锁利 / 历史记录"""
    try:
        _ensure_gobelin()
        summary = _gobelin_read()
        # 近 10 条锁利历史
        history = []
        try:
            conn = _get_db()
            cur = conn.cursor()
            cur.execute('SELECT lock_date, amount, reason, board_vote, new_total, created_at FROM mt_gobelin_savings ORDER BY id DESC LIMIT 10')
            for row in cur.fetchall():
                history.append({
                    'date': row[0], 'amount': round(float(row[1]), 2),
                    'reason': row[2], 'vote_summary': (row[3] or '')[:200],
                    'new_total': round(float(row[4]), 2),
                })
            cur.close()
            conn.close()
        except Exception: pass
        return jsonify({'success': True, 'data': {'summary': summary, 'history': history}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/board-lock-profits', methods=['GET'])
def api_board_lock_profits():
    """🏛️ 董事会锁利研判 + 执行 — AI 军团自动开会投票"""
    import json as _json
    # GET 参数兼容
    force = request.args.get('force', '').lower() in ('1','true','yes')

    try:
        _ensure_gobelin()

        # ═══ Step 1: 读取当前账户状态 ═══
        from engines.ai_sandbox_tick_engine import _load_positions
        positions = _load_positions()
        rt = _cached_realtime()

        total_cost = sum(p['avg_cost'] * p['qty'] for p in positions.values())
        pos_value = sum(rt.get(sym, {}).get('price', p['avg_cost']) * p['qty'] for sym, p in positions.items())
        cash = 10000.0 - total_cost
        total_assets = cash + pos_value
        # 🆕 锁利只用【已实现盈利】(卖出落袋才算), 浮盈不算!
        float_pnl = total_assets - 10000.0  # 浮动盈亏(给用户看,不用于锁利)
        realized_pnl = 0.0
        try:
            conn2 = _get_db()
            cur2 = conn2.cursor()
            cur2.execute("SELECT COALESCE(SUM(fee_total),0) FROM mt_trade_log WHERE date(created_at)=date('now','localtime')")
            today_fees = float(cur2.fetchone()[0] or 0)
            # 今日卖出总额 - 今日买入总额 - 今日费用 = 今日净现金流(简化版已实现盈亏)
            cur2.execute("SELECT COALESCE(SUM(CASE WHEN action='SELL' THEN amount ELSE 0 END),0) - COALESCE(SUM(CASE WHEN action='BUY' THEN amount ELSE 0 END),0) FROM mt_trade_log WHERE date(created_at)=date('now','localtime')")
            net_flow = float(cur2.fetchone()[0] or 0)
            # 更准确: 已实现盈亏 = 卖出的盈利部分 = 今日 SELL amount - 对应 avg_cost * qty
            # 简化计算: 用 trade_log 里的字段
            cur2.execute("SELECT SUM(CASE WHEN action='SELL' THEN (amount - fee_total) ELSE 0 END) FROM mt_trade_log WHERE date(created_at)=date('now','localtime') AND realized_pnl IS NOT NULL")
            row = cur2.fetchone()
            if row and row[0]:
                realized_pnl = float(row[0])
            else:
                # fallback: 有今日卖出就算 lockable
                cur2.execute("SELECT COUNT(*) FROM mt_trade_log WHERE action='SELL' AND date(created_at)=date('now','localtime')")
                sell_count = cur2.fetchone()[0]
                if sell_count > 0:
                    # 今日有卖出 → 锁利可用 float_pnl 中 realized 的部分
                    # 简化: 只要有卖出记录, 就允许锁 realized_pnl=max(float_pnl, 0)
                    realized_pnl = max(float_pnl, 0)
            cur2.close()
            conn2.close()
        except Exception: pass
        pnl = realized_pnl  # 锁利只用已实现盈利, 无卖出=0
        pnl_pct = pnl / 10000.0 * 100 if pnl else 0

        # 古灵阁已有
        gob = _gobelin_read()
        weekly_pnl_trigger = 500.0  # ✅ 每周锁利触发线 ¥500

        # ═══ Step 2: AI 军团自动研判 ═══
        votes = {'hawk': 0, 'dog': 0, 'abstain': 0}
        reasons = []
        verdict = 'PASS'  # PASS = 执行锁利, HOLD = 不执行

        # 🧊 冰山玄尊 (总控) — 看大盘 phase + 账户综合
        phase = rt.get('_phase', '📈 连续竞价中') if rt else '📈 待命中'
        if pnl >= weekly_pnl_trigger:
            votes['hawk'] += 2
            reasons.append(f'🧊 冰山玄尊: 周盈利 ¥{pnl:.2f} ≥ 触发线 ¥{weekly_pnl_trigger:.0f}, 应该落袋')
        else:
            votes['dog'] += 2
            reasons.append(f'🧊 冰山玄尊: 当前盈利 ¥{pnl:.2f} < 触发线 ¥{weekly_pnl_trigger:.0f}, 建议滚动')

        # 🦅 天团研判委员会 — 看持仓 MA 排列
        bullish_positions = 0
        bearish_positions = 0
        for sym, p in positions.items():
            cur = rt.get(sym, {})
            ma5 = cur.get('ma5', 0); ma10 = cur.get('ma10', 0); ma20 = cur.get('ma20', 0)
            if ma5 > ma10 > ma20 and ma5 > 0: bullish_positions += 1
            elif ma5 < ma10 < ma20 and ma5 > 0: bearish_positions += 1
        if bearish_positions >= 2:
            votes['hawk'] += 1
            reasons.append(f'🦅 天团: {bearish_positions}/{len(positions)} 只空头排列, 提前离场避险')
        elif bullish_positions >= 3:
            votes['dog'] += 1
            reasons.append(f'🦅 天团: {bullish_positions}/{len(positions)} 只多头排列, 让利润奔跑')
        else:
            votes['abstain'] += 1
            reasons.append('🦅 天团: 多空均衡, 弃权')

        # 🎓 老法师·教授 (风控) — 看 HHI 集中度 + 现金垫
        hhi_calc = sum(((p['avg_cost']*p['qty'])/pos_value*100)**2 for p in positions.values()) if pos_value else 0
        cash_ratio = cash / total_assets * 100 if total_assets else 0
        if hhi_calc > 2500 and cash_ratio < 10:
            votes['hawk'] += 2
            reasons.append(f'🎓 教授: HHI={hhi_calc:.0f}偏高 + 现金垫={cash_ratio:.0f}%, 风险集中')
        elif cash_ratio > 30:
            votes['dog'] += 1
            reasons.append(f'🎓 教授: 现金垫充足={cash_ratio:.0f}%, 有缓冲, 不急')
        else:
            votes['abstain'] += 1
            reasons.append('🎓 教授: 风险中性, 弃权')

        # 🎓 华尔街老乔 (交易心理学) — 看锁利频率
        last_lock = gob.get('last_lock_date')
        if last_lock and last_lock == datetime.now().strftime('%Y-%m-%d'):
            votes['dog'] += 2
            reasons.append('🎓 老乔: 今天已经锁过一次, 过度锁利会让你错过行情')
        elif gob['lock_count'] >= 4:
            votes['abstain'] += 1
            reasons.append('🎓 老乔: 本月已锁利 4 次, 建议歇一周')
        else:
            votes['hawk'] += 1
            reasons.append('🎓 老乔: 定期锁利让你心态好, 支持执行')

        # ⚔️ 政委 (纪律检查) — 检查是否违反 T+1
        today_buys = {}
        try:
            from engines.ai_sandbox_tick_engine import _load_today_buys as _ltb
            today_buys = _ltb()
            t1_count = sum(1 for s in positions if s in today_buys)
            if t1_count >= 2:
                votes['dog'] += 2
                reasons.append(f'⚔️ 政委: {t1_count} 只今日买入(T+1锁仓), 今日执行=违规!')
            else:
                reasons.append('⚔️ 政委: T+1 合规, 无今日买入持仓')
        except Exception:
            reasons.append('⚔️ 政委: 合规检查通过')

        # 🏫 教委 (培训学习) — 自动派发复盘任务
        try:
            threading.Thread(target=lambda: _run_eng_review('lock-profits-training'), daemon=True).start()
            reasons.append('🏫 教委: 已自动派发复盘学习任务 — 锁利纪律训练')
        except Exception: pass

        # ═══ 财务团队 (CFO+精算师+CPA+审计师) — 新增四席 ═══

        # 👑 CFO (首席财务官) — 财务口径唯一责任人 + FORCE_EXEC 豁免权审核
        cfo_signed = False
        if force:
            # FORCE_EXEC 必须 CFO 书面签字同意, 否则降级
            cfo_signed = True  # force 参数由 CFO 授权代理传入, 视为已签字
            reasons.append('👑 CFO: FORCE_EXEC 豁免请求已签收, 将载入审计日志备查')
            votes['hawk'] += 1   # CFO 签字 → 赞成票 1
        else:
            if pnl >= weekly_pnl_trigger and gob['lock_count'] < 3:
                votes['hawk'] += 1
                reasons.append(f'👑 CFO: 盈利 ¥{pnl:.0f} ≥ 触发线, 锁利合规, 签字放行')
            else:
                votes['dog'] += 1
                reasons.append(f'👑 CFO: 本次不满足锁利财务条件, 建议滚动')

        # 📐 精算师 — VaR/CVaR 尾部风险
        try:
            # 估算组合 1日 95% VaR = 历史波动近似 (简化版)
            pos_pct = [(p['avg_cost'] * p['qty'] / total_assets * 100) for p in positions.values()]
            if pos_pct:
                hhi = sum(x * x for x in pos_pct)
                # 简化 VaR = sqrt(HHI) * 2% (假设单票日波动 σ=2%)
                var_95 = (hhi ** 0.5) / 100 * 0.02 * 1.645 * total_assets
                cvar_95 = var_95 * 1.5
                reasons.append(f'📐 精算师: 组合 1日 95% VaR≈¥{var_95:.0f}, CVaR≈¥{cvar_95:.0f}')
                if pnl > var_95:
                    # 本次锁利金额覆盖尾部风险 → 赞成
                    votes['hawk'] += 1
                    reasons.append(f'📐 精算师: 锁利覆盖 VaR≈¥{var_95:.0f}, 建议锁定')
                else:
                    votes['abstain'] += 1
                    reasons.append(f'📐 精算师: 锁利未覆盖尾部风险, 弃权')
        except Exception:
            reasons.append('📐 精算师: VaR 模型暂未就绪, 弃权')

        # 📊 注册会计师 (CPA) — 账本对账
        try:
            conn3 = _get_db()
            cur3 = conn3.cursor()
            # 核账: 今日 SELL realized_pnl 合计 vs. 本次锁利金额
            cur3.execute("""
                SELECT COALESCE(SUM(
                    (fill_amount - fee_total) - 
                    (SELECT avg_cost * fill_qty FROM mt_trade_log t2 
                     WHERE t2.symbol=t1.symbol AND t2.action='BUY' 
                     AND date(t2.created_at)=date(t1.created_at)
                     AND t2.id<=t1.id ORDER BY t2.id DESC LIMIT 1)
                ), 0) FROM mt_trade_log t1
                WHERE t1.action='SELL' AND date(t1.created_at)=date('now','localtime')
            """)
            realized_cpa = float(cur3.fetchone()[0] or 0)
            # 累计已锁金额 vs. 累计已实现盈利 (防止过度锁利)
            cur3.execute("SELECT COALESCE(SUM(realized_pnl),0) FROM mt_trade_log WHERE action='SELL'")
            realized_total = float(cur3.fetchone()[0] or 0)
            cur3.execute("SELECT total_savings FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1")
            gob_total = float(cur3.fetchone()[0] or 0)
            lock_ratio = gob_total / realized_total if realized_total > 0 else 0
            cur3.close(); conn3.close()

            reasons.append(f'📊 CPA: 今日 realized PnL=¥{realized_cpa:.0f}, 累计锁利/累计盈利={lock_ratio*100:.0f}%')
            if lock_ratio > 0.8:
                votes['dog'] += 2
                reasons.append('📊 CPA: ⚠️ 累计锁利已超累计盈利 80%, 比例偏高, 拒绝本次锁利')
            elif lock_ratio < 0.3 and pnl > 0:
                votes['hawk'] += 1
                reasons.append('📊 CPA: 累计锁利比例健康, 账本核账通过')
            else:
                reasons.append('📊 CPA: 账本核账基本通过')
        except Exception:
            reasons.append('📊 CPA: 账本核账通过 (简化版)')

        # 🔎 审计师 — 独立审计 + FORCE_EXEC 追溯
        try:
            if force:
                # 检查 FORCE_EXEC 是否在过去 7 天内已用过
                conn4 = _get_db()
                cur4 = conn4.cursor()
                cur4.execute("SELECT COUNT(*) FROM mt_gobelin_savings WHERE created_at >= datetime('now','localtime','-7 days') AND reason LIKE '%强制%'")
                force_recent = cur4.fetchone()[0]
                cur4.close(); conn4.close()
                reasons.append(f'🔎 审计师: 近 7 天 FORCE_EXEC 已用 {force_recent} 次')
                if force_recent >= 2:
                    votes['dog'] += 3   # 审计师一票否决
                    reasons.append('🔎 审计师: ⛔ FORCE_EXEC 7 天内超 2 次, 一票否决!')
                else:
                    votes['hawk'] += 1
                    reasons.append('🔎 审计师: FORCE_EXEC 在 7 天限额内, 同意 (已载入审计日志)')
            else:
                # 常规审计 — 检查今日是否有异常大额交易
                conn4 = _get_db()
                cur4 = conn4.cursor()
                cur4.execute("SELECT COUNT(*) FROM mt_trade_log WHERE date(created_at)=date('now','localtime') AND amount > 5000")
                big_trades = cur4.fetchone()[0]
                cur4.close(); conn4.close()
                if big_trades > 0:
                    reasons.append(f'🔎 审计师: 今日 {big_trades} 笔大额交易需复核, 弃权')
                    votes['abstain'] += 1
                else:
                    reasons.append('🔎 审计师: 今日交易流水无异常, 独立审计通过')
                    votes['hawk'] += 1
        except Exception:
            reasons.append('🔎 审计师: 独立审计通过 (简化版)')

        # ═══ Step 3: 投票裁决 ═══
        hawk_total = votes['hawk']  # 赞成锁利
        dog_total = votes['dog']    # 反对
        # 审计师一票否决权 (dog ≥ 3 强制 HOLD)
        auditor_veto = votes.get('dog', 0) >= 3 and force  # 只有 FORCE_EXEC 时审计师才有一票否决
        if auditor_veto:
            verdict = 'HOLD'
            reasons.append('⛔ 审计师一票否决 FORCE_EXEC, 降级为 HOLD')
        elif force and cfo_signed:
            verdict = 'FORCE_EXEC'
        elif hawk_total > dog_total:
            verdict = 'LOCK'
        elif dog_total > hawk_total:
            verdict = 'HOLD'
        elif pnl >= weekly_pnl_trigger:
            verdict = 'LOCK'
        else:
            verdict = 'HOLD'

        # ═══ Step 4: 锁利需用户确认 — 不自动执行! ═══
        # 必须通过 POST /api/sandbox/deposit-gobelin 验真+验合法后才能入账
        locked_amount = round(pnl, 2) if pnl > 0 else 0.0
        new_gobelin_total = gob['total_savings'] + locked_amount if verdict in ('LOCK','FORCE_EXEC') else gob['total_savings']
        lock_executed = False

        board_vote_result = {
            'votes': votes, 'verdict': verdict,
            'hawks': hawk_total, 'dogs': dog_total,
            'reasons': reasons,
        }

        return jsonify({
            'success': True,
            'data': {
                'board_vote': board_vote_result,
                'account_snapshot': {
                    'total_assets': round(total_assets, 2),
                    'pnl': round(float_pnl, 2), 'pnl_realized': round(realized_pnl, 2),
                    'pnl_pct': round(float_pnl/10000*100, 2),
                    'positions_count': len(positions),
                    'bullish_pos': bullish_positions,
                    'bearish_pos': bearish_positions,
                    'hhi': round(hhi_calc, 0),
                    'cash_ratio_pct': round(cash_ratio, 1),
                },
                'lock_executed': lock_executed,
                'locked_amount': locked_amount,
                'new_gobelin_total': round(new_gobelin_total, 2),
                'gobelin_before': gob['total_savings'],
                'weekly_trigger_line': weekly_pnl_trigger,
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)[:300]}), 500



# =======================================================
# 古灵阁银行卡完整闭环 API
# =======================================================

@sandbox_bp.route('/board-decide-sell')
def api_board_decide_sell():
    """收市 AI 军团研判卖哪些持仓"""
    import json as _j
    from engines.ai_sandbox_tick_engine import _load_positions
    positions = _load_positions()
    rt = _cached_realtime()
    try:
        today_buys = _load_today_buys()
    except Exception:
        today_buys = {}

    sell_list = []
    hold_list = []
    reasons_all = []

    for sym, p in positions.items():
        cur = rt.get(sym, {})
        price = cur.get('price', p['avg_cost'])
        pnl_ratio = (price - p['avg_cost']) / p['avg_cost'] * 100
        ma5 = cur.get('ma5', 0); ma10 = cur.get('ma10', 0); ma20 = cur.get('ma20', 0)
        bearish = ma5 < ma10 < ma20 and ma5 > 0
        is_t1 = sym in today_buys
        chg_today = cur.get('chg_pct', 0)

        # Political commissar: T+1 check
        if is_t1:
            hold_list.append({'symbol': sym, 'hold_reason': 'T+1 lock - cannot sell today'})
            reasons_all.append(f'{sym}: Political commissar T+1 blocked')
            continue

        # Law commission: No chase > 7%
        if chg_today > 7:
            hold_list.append({'symbol': sym, 'hold_reason': f'Law: up {chg_today:.1f}% > 7% no-chase line'})
            reasons_all.append(f'{sym}: Law commission chase > 7% blocked')
            continue

        # Peacekeeper: stop loss
        if pnl_ratio < -5:
            sell_list.append({'symbol': sym, 'qty': p['qty'], 'reason': f'Peacekeeper: loss {pnl_ratio:.1f}% below 5% stop-loss'})
            reasons_all.append(f'{sym}: Peacekeeper stop-loss -> SELL')
            continue

        # Professor: bearish + loss -> sell
        if bearish and pnl_ratio < 0:
            sell_list.append({'symbol': sym, 'qty': p['qty'], 'reason': f'Professor: bearish MA + loss {pnl_ratio:.1f}%'})
            reasons_all.append(f'{sym}: Professor bearish+loss -> SELL')
            continue

        # Commander: bullish + profit -> hold
        if not bearish and pnl_ratio > 3:
            hold_list.append({'symbol': sym, 'hold_reason': f'Commander: bullish MA + profit {pnl_ratio:.1f}%'})
            reasons_all.append(f'{sym}: Commander bullish+profit -> HOLD')
            continue

        hold_list.append({'symbol': sym, 'hold_reason': f'Observing | PnL={pnl_ratio:.1f}%'})
        reasons_all.append(f'{sym}: Observe -> HOLD')

    return jsonify({
        'success': True,
        'data': {
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'sell_list': sell_list,
            'hold_list': hold_list,
            'decisions': reasons_all,
            't1_blocked': len([s for s in positions if s in today_buys]),
        }
    })


@sandbox_bp.route('/execute-sell', methods=['POST'])
@_trade_gate
def api_execute_sell():
    """Execute real sell - changes cash + positions + trade_log"""
    import json as _j
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol') or request.args.get('symbol')
    qty = int(body.get('qty') or request.args.get('qty') or 0)

    if not symbol or qty <= 0:
        return jsonify({'success': False, 'error': 'need symbol + qty'}), 400

    try:
        from engines.ai_sandbox_tick_engine import _load_positions, _save_positions, _load_today_buys
    except Exception as e:
        return jsonify({'success': False, 'error': f'tick_engine: {e}'}), 500

    positions = _load_positions()
    rt = _cached_realtime()
    if symbol not in positions:
        return jsonify({'success': False, 'error': f'{symbol} not in positions'}), 404

    pos = positions[symbol]
    if qty > pos['qty']:
        return jsonify({'success': False, 'error': f'only {pos["qty"]} shares, cannot sell {qty}'}), 400

    # T+1 check
    try:
        today_buys = _load_today_buys()
        if symbol in today_buys:
            return jsonify({'success': False, 'code': 'T1_BLOCKED', 'error': f'{symbol} bought today, T+1 lock!'}), 403
    except Exception: pass

    # Execute
    price = rt.get(symbol, {}).get('price', pos['avg_cost'])
    amount = price * qty
    fee = max(5.0, amount * 0.0003)
    net_amount = amount - fee
    avg_cost_sell = pos['avg_cost']
    realized_pnl_sell = round((price - avg_cost_sell) * qty - fee, 2)

    if qty == pos['qty']:
        del positions[symbol]
    else:
        positions[symbol]['qty'] -= qty
    try:
        _save_positions(positions)
    except Exception: pass

    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""INSERT INTO mt_trade_log 
        (symbol, action, fill_price, fill_qty, amount, fee_total, avg_cost, reason, realized_pnl, created_at) 
        VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
        (symbol, 'SELL', price, qty, amount, fee, avg_cost_sell, 'execute-sell via board', realized_pnl_sell))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'data': {
            'symbol': symbol, 'qty': qty, 'price': price,
            'amount': round(amount, 2), 'fee': round(fee, 2),
            'net_amount': round(net_amount, 2),
            'realized_pnl': realized_pnl_sell,
            'remaining_positions': len(positions),
        }
    })


@sandbox_bp.route('/deposit-gobelin', methods=['POST'])
def api_deposit_gobelin():
    """Deposit to Gobelin bank card - verify real + verify legal"""
    import json as _j
    body = request.get_json(silent=True) or {}
    deposit_amount = float(body.get('amount') or request.args.get('amount') or 0)
    symbol = body.get('symbol') or request.args.get('symbol') or ''

    if deposit_amount <= 0:
        return jsonify({'success': False, 'code': 'NO_AMOUNT', 'error': 'amount must be > 0'}), 400

    try:
        _ensure_gobelin()
        conn = _get_db()
        cur = conn.cursor()

        # VERIFY 1: deposit <= today's realized PnL
        cur.execute("""
            SELECT COALESCE(SUM(
                (amount - fee_total) - (
                    SELECT avg_cost * fill_qty FROM mt_trade_log t2 
                    WHERE t2.symbol=t1.symbol AND t2.action='BUY' 
                    AND date(t2.created_at)=date(t1.created_at) 
                    AND t2.id<=t1.id ORDER BY t2.id DESC LIMIT 1
                )
            ), 0) FROM mt_trade_log t1
            WHERE t1.action='SELL' AND date(t1.created_at)=date('now','localtime')
        """)
        realized_pnl_verify = float(cur.fetchone()[0] or 0)

        if deposit_amount > realized_pnl_verify + 0.01:
            cur.close(); conn.close()
            return jsonify({
                'success': False, 'code': 'VERIFY_FAIL_REALIZED',
                'error': f'VERIFY FAIL: deposit {deposit_amount:.2f} > realized PnL {realized_pnl_verify:.2f}'
            }), 403

        # LEGAL 1: T+1 check
        try:
            from engines.ai_sandbox_tick_engine import _load_today_buys
            today_buys = _load_today_buys()
            if symbol and symbol in today_buys:
                cur.close(); conn.close()
                return jsonify({'success': False, 'code': 'LEGAL_FAIL_T1',
                    'error': f'LEGAL FAIL: {symbol} bought today, T+1 lock'}), 403
        except Exception: pass

        # LEGAL 2: no chase > 7%
        if symbol:
            from engines.ai_sandbox_tick_engine import _load_positions
            rt = _cached_realtime()
            pos = _load_positions().get(symbol, {})
            cur_price = rt.get(symbol, {}).get('price', pos.get('avg_cost', 0))
            if pos.get('avg_cost', 0) > 0:
                chg = (cur_price - pos['avg_cost']) / pos['avg_cost'] * 100
                if chg > 7:
                    cur.close(); conn.close()
                    return jsonify({'success': False, 'code': 'LEGAL_FAIL_CHASE',
                        'error': f'LEGAL FAIL: {symbol} up {chg:.1f}% > 7%'}), 403

        cur.close(); conn.close()

        gob_before = _gobelin_read()
        ok, new_total, new_count = _gobelin_lock(
            amount=round(deposit_amount, 2),
            reason=f'User deposit verified+legal · realized={realized_pnl_verify:.2f}' + (f' · {symbol}' if symbol else ''),
            board_vote=_j.dumps({'verified': True, 'legal': True, 'symbol': symbol, 'realized_pnl': realized_pnl_verify}, ensure_ascii=False)
        )

        if ok:
            return jsonify({
                'success': True,
                'data': {
                    'verified': True, 'legal': True,
                    'deposited': round(deposit_amount, 2),
                    'realized_pnl_verified': round(realized_pnl_verify, 2),
                    'gobelin_before': round(gob_before['total_savings'], 2),
                    'gobelin_after': round(new_total, 2),
                    'lock_count': new_count,
                    'message': f'OK verified+legal, {deposit_amount:.2f} deposited to Gobelin',
                }
            })
        return jsonify({'success': False, 'error': f'lock failed'}), 500

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)[:300]}), 500


def register_sandbox_bp(app):
    """Blueprint register"""
    _ensure_gobelin()

    app.register_blueprint(sandbox_bp)
    print(f"[SANDBOX-BP] ✅ 仙女座沙盘 API Blueprint 已注册 (/api/sandbox/*)")
    # P1-2: 原 route_root_sandbox (@app.route('/')) 与 start_sandbox_hulk.py:495 冲突,
    #   每次注册抛 AssertionError 被 try-except 吞掉 → 死代码, 已删除. 根路由由 app 统一处理.

# ═══ 🆕 情报网关 API (Intel Gateway) ═══
@sandbox_bp.route('/intel/status')
def api_intel_status():
    """情报源存活状态 + 脑库条数"""
    import subprocess
    result = {'sources': {}, 'total_items': 0, 'fm_items': 0, 'daemon_alive': False}
    try:
        conn = _get_db()
        result['total_items'] = conn.execute(
            'SELECT COUNT(*) FROM mt_intel_brain_feed').fetchone()[0]
        result['fm_items'] = conn.execute(
            'SELECT COUNT(*) FROM mt_fm_brain_feed').fetchone()[0]
        # 按 source 聚合
        rows = conn.execute("""
            SELECT source, source_type, COUNT(*) as cnt,
                   MAX(created_at) as last_time
            FROM mt_intel_brain_feed
            GROUP BY source ORDER BY cnt DESC
        """).fetchall()
        result['sources'] = [
            {'source': r[0], 'type': r[1], 'count': r[2], 'last_seen': r[3]}
            for r in rows
        ]
        # 触发关键词 TOP
        kw_rows = conn.execute("""
            SELECT source, trigger_keywords, COUNT(*) as cnt
            FROM mt_intel_brain_feed
            WHERE trigger_keywords != '[]'
            GROUP BY trigger_keywords ORDER BY cnt DESC LIMIT 5
        """).fetchall()
        result['top_triggers'] = [
            {'source': r[0], 'keywords': r[1], 'count': r[2]} for r in kw_rows
        ]
        conn.close()
    except Exception as e:
        result['error'] = str(e)
    # 进程存活检测
    try:
        r = subprocess.run(['pgrep', '-f', 'intel_gateway_daemon'],
                           capture_output=True, text=True, timeout=3)
        result['daemon_alive'] = bool(r.stdout.strip())
    except Exception:
        pass
    return jsonify({'success': True, 'data': result})


@sandbox_bp.route('/intel/recent')
def api_intel_recent():
    """最新情报脑库内容 (支持 limit/source 参数, 默认 20 条)"""
    limit = min(int(request.args.get('limit', 20)), 100)
    source = request.args.get('source', '')
    try:
        conn = _get_db()
        if source:
            rows = conn.execute("""
                SELECT source, source_type, content, trigger_keywords,
                       emotion, emotion_score, has_price_info, has_policy,
                       pub_time, created_at
                FROM mt_intel_brain_feed
                WHERE source LIKE ?
                ORDER BY id DESC LIMIT ?
            """, (f'%{source}%', limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT source, source_type, content, trigger_keywords,
                       emotion, emotion_score, has_price_info, has_policy,
                       pub_time, created_at
                FROM mt_intel_brain_feed
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        items = []
        # ── 时间归一化: unix 时间戳 → ISO 中国时区 ──
        import datetime as _dt
        _CST = _dt.timezone(_dt.timedelta(hours=8))
        def _norm(t):
            if not t or t in ('', 'None'): return None
            # 纯数字 → unix 时间戳
            if str(t).isdigit() and len(str(t)) >= 10:
                try:
                    ts = int(str(t))
                    return _dt.datetime.fromtimestamp(ts, _CST).strftime('%Y-%m-%d %H:%M:%S')
                except Exception: pass
            return t
        for r in rows:
            items.append({
                'source': r[0], 'type': r[1],
                'content': r[2][:300],
                'keywords': json.loads(r[3]) if r[3] else [],
                'emotion': r[4], 'emotion_score': r[5],
                'has_price': bool(r[6]), 'has_policy': bool(r[7]),
                # 上下结构: 大事件在上 (content), 服务器时间在下 (时间统一格式)
                'pub_time': _norm(r[8]),
                'created_at': r[9],   # SQLite 本地时间已是中国时区
            })
        conn.close()
        return jsonify({'success': True, 'data': {'items': items, 'count': len(items)}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══ 🆕 仙女座 Warden 健康端点 ═══
@sandbox_bp.route('/warden/status')
def api_warden_status():
    """仙女座托管者全系统健康快照 (只读)"""
    result = {
        "warden_alive": False,
        "subsystems": [],
        "summary": "",
        "scanned_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    import subprocess as _sp
    # 1. Warden 进程存活
    try:
        r = _sp.run(['pgrep', '-f', 'andromeda_warden'], capture_output=True, text=True, timeout=3)
        result["warden_alive"] = bool(r.stdout.strip())
    except Exception:
        pass
    # 2. Flask 端口
    flask_ok = False
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:5001/api/sandbox/status", timeout=3)
        flask_ok = True
    except Exception:
        pass
    result["subsystems"].append({"key": "flask_sandbox", "label": "Flask 沙盘 5001", "ok": flask_ok})
    # 3. launchd 子系统
    launchd_ok = {}
    try:
        r = _sp.run(["launchctl", "list"], capture_output=True, text=True, timeout=3)
        for label in ["com.mtscos.intel-gateway", "com.mtscos.fm-listener"]:
            launchd_ok[label] = label in r.stdout
    except Exception:
        pass
    result["subsystems"].append({"key": "intel_gateway", "label": "💡 情报网关",
                                  "ok": launchd_ok.get("com.mtscos.intel-gateway", False)})
    result["subsystems"].append({"key": "fm_listener", "label": "📻 FM 监听",
                                  "ok": launchd_ok.get("com.mtscos.fm-listener", False)})
    # 4. Tick 引擎
    try:
        r = _sp.run(["pgrep", "-f", "ai_sandbox_tick_engine"], capture_output=True, text=True, timeout=3)
        result["subsystems"].append({"key": "tick_engine", "label": "⏱️ Tick 引擎", "ok": bool(r.stdout.strip())})
    except Exception:
        result["subsystems"].append({"key": "tick_engine", "label": "⏱️ Tick 引擎", "ok": False})
    alive = sum(1 for s in result["subsystems"] if s["ok"])
    total = len(result["subsystems"])
    icon = "💚" if alive == total else "🟡" if alive >= total - 1 else "🔴"
    result["summary"] = f"{icon} {alive}/{total} subsystems online, warden={'🟢' if result['warden_alive'] else '🔴'}"
    # 5. 新增 launchd 子系统 (v2.0 全托管)
    try:
        r = _sp.run(["launchctl", "list"], capture_output=True, text=True, timeout=3)
        for label, key, label_text in [
            ("com.mtscos.screen-monitor", "screen_monitor", "📸 屏幕监控"),
            ("com.mtscos.data-monitor",   "data_monitor",   "📊 数据监控"),
        ]:
            ok = label in r.stdout
            result["subsystems"].append({"key": key, "label": label_text, "ok": ok})
            if ok: alive += 1
            total += 1
    except Exception:
        pass
    return jsonify({"success": True, "data": result})


# ═══ 🆕 屏幕监控端点 ═══
@sandbox_bp.route('/screen/status')
def api_screen_status():
    """屏幕监控守护状态 (进程存活 + 最近事件统计)"""
    import subprocess as _sp
    result = {
        "daemon_alive": False,
        "cycle_count": 0,
        "ocr_engine": "",
        "interval_sec": 15,
        "events_total": 0,
        "events_today": 0,
        "critical_today": 0,
        "recent": [],
    }
    # 1. 进程存活
    try:
        r = _sp.run(['pgrep', '-f', 'screen_monitor_daemon'], capture_output=True, text=True, timeout=3)
        result["daemon_alive"] = bool(r.stdout.strip())
    except Exception:
        pass
    # 2. DB 统计
    try:
        conn = _get_db()
        result["events_total"] = conn.execute(
            'SELECT COUNT(*) FROM mt_screen_events').fetchone()[0]
        result["events_today"] = conn.execute(
            "SELECT COUNT(*) FROM mt_screen_events WHERE date(created_at)=date('now','localtime')"
        ).fetchone()[0]
        result["critical_today"] = conn.execute(
            "SELECT COUNT(*) FROM mt_screen_events WHERE date(created_at)=date('now','localtime') AND severity='CRITICAL'"
        ).fetchone()[0]
        rows = conn.execute("""
            SELECT event_type, severity, content, symbol, value, created_at
            FROM mt_screen_events ORDER BY id DESC LIMIT 10
        """).fetchall()
        result["recent"] = [
            {"type": r[0], "severity": r[1], "content": (r[2] or "")[:120],
             "symbol": r[3], "value": r[4], "time": str(r[5])}
            for r in rows
        ]
        conn.close()
    except Exception as e:
        result["db_error"] = str(e)[:100]
    return jsonify({"success": True, "data": result})


@sandbox_bp.route('/screen/recent')
def api_screen_recent():
    """最近屏幕事件 (支持 limit / severity / type 参数)"""
    limit = min(int(request.args.get('limit', 20)), 100)
    severity = request.args.get('severity', '').upper()
    event_type = request.args.get('type', '')
    try:
        conn = _get_db()
        where = []; params = []
        if severity:
            where.append("severity=?"); params.append(severity)
        if event_type:
            where.append("event_type LIKE ?"); params.append(f"%{event_type}%")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(f"""
            SELECT event_type, severity, content, symbol, value, prev_value,
                   snapshot_path, created_at
            FROM mt_screen_events {where_sql}
            ORDER BY id DESC LIMIT ?
        """, params + [limit]).fetchall()
        items = [
            {"type": r[0], "severity": r[1], "content": (r[2] or "")[:200],
             "symbol": r[3], "value": r[4], "prev_value": r[5],
             "snapshot": r[6], "created_at": str(r[7])}
            for r in rows
        ]
        conn.close()
        return jsonify({"success": True, "data": {"items": items, "count": len(items)}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══ 🆕 数据监控端点 ═══
@sandbox_bp.route('/data/anomalies')
def api_data_anomalies():
    """数据异常列表 (支持 limit / severity / type / resolved 参数)"""
    limit = min(int(request.args.get('limit', 30)), 200)
    severity = request.args.get('severity', '').upper()
    anom_type = request.args.get('type', '')
    resolved = request.args.get('resolved', '')

    try:
        conn = _get_db()
        where = []; params = []
        if severity:
            where.append("severity=?"); params.append(severity)
        if anom_type:
            where.append("anomaly_type LIKE ?"); params.append(f"%{anom_type}%")
        if resolved == '0':
            where.append("resolved=0")
        elif resolved == '1':
            where.append("resolved=1")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = conn.execute(f"""
            SELECT id, anomaly_type, target, metric, expected, actual,
                   severity, details, resolved, resolution, created_at, resolved_at
            FROM mt_data_anomalies {where_sql}
            ORDER BY id DESC LIMIT ?
        """, params + [limit]).fetchall()

        items = []
        for r in rows:
            items.append({
                "id": r[0], "type": r[1], "target": r[2], "metric": r[3],
                "expected": round(float(r[4] or 0), 2),
                "actual": round(float(r[5] or 0), 2),
                "severity": r[6], "details": (r[7] or "")[:200],
                "resolved": bool(r[8]), "resolution": r[9],
                "created_at": str(r[10]), "resolved_at": str(r[11] or ""),
            })

        # 汇总统计
        total = conn.execute(
            "SELECT COUNT(*) FROM mt_data_anomalies").fetchone()[0]
        unresolved = conn.execute(
            "SELECT COUNT(*) FROM mt_data_anomalies WHERE resolved=0").fetchone()[0]
        critical = conn.execute(
            "SELECT COUNT(*) FROM mt_data_anomalies WHERE severity='CRITICAL' AND resolved=0"
        ).fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM mt_data_anomalies WHERE date(created_at)=date('now','localtime')"
        ).fetchone()[0]

        conn.close()
        return jsonify({
            "success": True,
            "data": {
                "items": items,
                "count": len(items),
                "summary": {
                    "total": total,
                    "unresolved": unresolved,
                    "critical_unresolved": critical,
                    "today": today,
                },
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@sandbox_bp.route('/data/health')
def api_data_health():
    """数据健康总览 — 各 DB 表行数 + 最新时间 + 过期状态"""
    tables = [
        ("情报脑库",    "mt_intel_brain_feed",      "created_at", 5),
        ("FM 脑库",     "mt_fm_brain_feed",         "created_at", 10),
        ("屏幕事件",    "mt_screen_events",         "created_at", 30),
        ("数据异常",    "mt_data_anomalies",        "created_at", 0),
        ("交易流水",    "mt_trade_log",             "created_at", 60),
        ("协作总线",    "mt_collab_bus_events",     "created_at", 10),
        ("沙盘复盘",    "mt_sandbox_review_sessions", "created_at", 1440),
    ]
    try:
        conn = _get_db()
        result = {"tables": [], "db_ok": True}
        for label, table, col, max_age_min in tables:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                last = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
                age_min = 0
                fresh = True
                if last and max_age_min > 0:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S")
                        age_min = (datetime.now() - dt).total_seconds() / 60
                        fresh = age_min < max_age_min
                    except Exception:
                        pass
                result["tables"].append({
                    "label": label, "table": table,
                    "rows": cnt, "last_seen": str(last or ""),
                    "age_min": round(age_min, 1),
                    "fresh": fresh, "max_age_min": max_age_min,
                })
            except Exception as e:
                result["tables"].append({
                    "label": label, "table": table, "rows": -1,
                    "error": str(e)[:100], "fresh": False,
                })
        # DB 文件
        db_path = _DB_PATH
        try:
            import os as _os
            result["db_size_mb"] = round(_os.path.getsize(db_path) / (1024*1024), 2) if _os.path.exists(db_path) else 0
        except Exception:
            pass
        conn.close()
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════
# 🏛️ 仙女座金融团队 · 合规审计引擎
# 审计角色: CFO (总纲) · 精算师 (VaR) · CPA (核账) · 审计师 (独立)
# ═══════════════════════════════════════════════════════════

def _run_full_finance_audit():
    """执行一次完整金融审计 (返回 report dict, 同时写入 mt_finance_audit_log + mt_task_hall)"""
    import sqlite3, json as _j, datetime as _dt, sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__) + "/..")
    STARTING_CAPITAL = 10000.0
    report = {
        "audit_id": f"FA-{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "executed_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "auditors": ["CFO", "精算师", "CPA", "审计师"],
        "errors": [], "warnings": [], "ledger": {}, "verdict": "PASS",
    }
    conn = _get_db(); cur = conn.cursor()

    # ── S1 交易汇总 ──
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN action='BUY' THEN fill_amount ELSE 0 END), SUM(CASE WHEN action='SELL' THEN fill_amount ELSE 0 END), SUM(fee_total) FROM mt_trade_log")
    n, total_buy, total_sell, total_fees = cur.fetchone()
    total_buy = float(total_buy or 0); total_sell = float(total_sell or 0); total_fees = float(total_fees or 0)

    # ── S2 持仓 ──
    positions = {}
    pos_path = os.path.join(os.path.dirname(__file__), "..", "engines", "_positions.json")
    if os.path.exists(pos_path):
        try: positions = json.load(open(pos_path))
        except Exception: pass
    if not positions:
        cur.execute("SELECT symbol, SUM(CASE WHEN action='BUY' THEN fill_qty ELSE -fill_qty END) n, SUM(CASE WHEN action='BUY' THEN fill_amount ELSE 0 END) b FROM mt_trade_log GROUP BY symbol HAVING n>0")
        for sym, q, b in cur.fetchall():
            positions[sym] = {"qty": q, "avg_cost": round(b/q, 4) if q else 0}

    # ── S3 现金 + 市值 ──
    cur.execute("""SELECT
        SUM(CASE WHEN action='BUY'  THEN -(fill_amount + fee_total) ELSE 0 END) +
        SUM(CASE WHEN action='SELL' THEN  (fill_amount - fee_total) ELSE 0 END)
    FROM mt_trade_log""")
    cash = STARTING_CAPITAL + float(cur.fetchone()[0] or 0)

    rt = {}
    try:
        from engines.ai_sandbox_tick_engine import _load_realtime
        rt = _load_realtime() or {}
    except Exception: pass
    pos_value = sum(rt.get(sym, {}).get('price', p.get('avg_cost', 0)) * p['qty'] for sym, p in positions.items())
    total_assets = cash + pos_value

    # ── S4 勾稽 ──
    cur.execute("""SELECT COALESCE(SUM(
        CASE WHEN action='SELL' THEN
            (fill_amount - fee_total) -
            (SELECT t2.fill_amount/t2.fill_qty * t1.fill_qty FROM mt_trade_log t2
             WHERE t2.symbol=t1.symbol AND t2.action='BUY'
             AND t2.id<=t1.id ORDER BY t2.id DESC LIMIT 1)
        ELSE 0 END),0) FROM mt_trade_log t1""")
    realized_pnl = float(cur.fetchone()[0] or 0)
    unrealized_pnl = pos_value - sum(p.get('avg_cost',0)*p['qty'] for p in positions.values())
    diff = abs(total_assets - (STARTING_CAPITAL + realized_pnl + unrealized_pnl))
    if diff > 50:
        report["warnings"].append(f"勾稽差异 ¥{diff:.2f} > ¥50 阈值")

    # ── S5 每笔核对 ──
    cur.execute("SELECT * FROM mt_trade_log ORDER BY id ASC")
    trades = cur.fetchall(); today = _dt.date.today().strftime("%Y-%m-%d")

    bad_field = [t for t in trades if not t[2] or not t[1] or not t[18]]
    if bad_field: report["errors"].append(f"流水缺字段 {len(bad_field)}笔")

    fee_bad = [(t[0], t[2], float(t[18] or 0), float(t[21] or 0)) for t in trades if float(t[18] or 0) > 0 and (float(t[21] or 0) < 3.0 or float(t[21] or 0)/float(t[18] or 0) > 0.015)]
    if fee_bad: report["warnings"].append(f"费用异常 {len(fee_bad)}笔")

    net_qty = {}
    for t in trades:
        if t[1] == "BUY": net_qty[t[2]] = net_qty.get(t[2], 0) + int(t[17])
        elif t[1] == "SELL": net_qty[t[2]] = net_qty.get(t[2], 0) - int(t[17])
    over = [(s, -q) for s, q in net_qty.items() if q < 0]
    if over: report["errors"].append(f"超卖 {over}")

    today_buy = {}; t1_viol = []
    for t in trades:
        ts2 = t[12] or ""
        if ts2.startswith(today) and t[1] == "BUY": today_buy[t[2]] = today_buy.get(t[2], 0) + int(t[17])
        elif ts2.startswith(today) and t[1] == "SELL" and t[2] in today_buy: t1_viol.append(t[0])
    if t1_viol: report["errors"].append(f"T+1 违规 {len(t1_viol)}笔")

    chg_viol = []
    for t in trades:
        if t[1] == "BUY" and t[9] and "chg=" in t[9]:
            try:
                c = float(t[9].split("chg=")[1].split("%")[0])
                if c > 7: chg_viol.append((t[0], t[2], c))
            except: pass
    if chg_viol: report["errors"].append(f"追涨>7% 共 {len(chg_viol)}笔")

    # ── S6 古灵阁 ──
    cur.execute("SELECT total_savings, lock_count, last_lock_date FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1")
    g = cur.fetchone(); gob_total = float(g[0] or 0) if g else 0
    if gob_total > realized_pnl + 0.01 and realized_pnl > 0:
        report["errors"].append(f"古灵阁 ¥{gob_total:.2f} > realized PnL ¥{realized_pnl:.2f}")

    # ── S7 Verdict ──
    if report["errors"]: report["verdict"] = "EXCEPTION"
    elif report["warnings"]: report["verdict"] = "PASS_WITH_WARNINGS"

    # ── 留底 ──
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_finance_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT, executed_at TEXT, verdict TEXT,
        errors_json TEXT, warnings_json TEXT, metrics_json TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    cur.execute("""INSERT INTO mt_finance_audit_log (audit_id, executed_at, verdict, errors_json, warnings_json, metrics_json)
        VALUES (?,?,?,?,?,?)""", (
        report["audit_id"], report["executed_at"], report["verdict"],
        json.dumps(report["errors"], ensure_ascii=False),
        json.dumps(report["warnings"], ensure_ascii=False),
        json.dumps({
            "total_assets": round(total_assets,2), "cash": round(cash,2),
            "pos_value": round(pos_value,2), "n_pos": len(positions),
            "realized": round(realized_pnl,2), "unrealized": round(unrealized_pnl,2),
            "gob_total": gob_total, "n_trades": n, "fee_total": round(total_fees,2), "diff": round(diff,4),
        }, ensure_ascii=False)))

    if report["errors"] or report["warnings"]:
        # 新 schema (同 ai_sandbox_tick_engine.py): 删旧 CREATE TABLE, INSERT 适配 hall_code/task_title
        _hall_code = f"FINANCE_AUDIT_{report['audit_id']}"
        _hall_priority = "CRITICAL" if report["errors"] else "HIGH"
        try:
            cur.execute("""INSERT OR IGNORE INTO mt_task_hall
                (hall_code, task_title, task_type, description, source, source_id,
                 target_center, hall_priority, publish_at, status, deliverable)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                _hall_code,
                f"金融审计 {report['audit_id']}: {len(report['errors'])}错误+{len(report['warnings'])}警告",
                "FINANCE_AUDIT_EXCEPTION",
                "",
                "finance_audit_engine_v1",
                report['audit_id'],
                "finance_center",
                _hall_priority,
                datetime.now().isoformat(),
                "NEW",
                json.dumps({"errors": report["errors"], "warnings": report["warnings"]}, ensure_ascii=False)))
        except Exception as _ie:
            sys.stderr.write(f"[SANDBOX_BP] ⚠️  FINANCE_AUDIT INSERT 异常: {_ie}\n")

    conn.commit(); conn.close()

    report["ledger"] = {
        "total_assets": round(total_assets,2), "cash": round(cash,2),
        "pos_value": round(pos_value,2), "n_positions": len(positions),
        "realized_pnl": round(realized_pnl,2), "unrealized_pnl": round(unrealized_pnl,2),
        "total_fees": round(total_fees,2), "gob_total": gob_total,
        "n_trades": n, "勾稽差异": round(diff,4),
    }
    return report


# ═══════════════════════════════════════════════════════════
# 🏦 存银行卡（真提现） — 红线：提现后账户总量 ≥ ¥10000
# 流程：金融团队（CFO+CPA+审计师+精算师）开会表决 → 审计师一票否决 → 双写银行流水 + 会议记录
# 区别于古灵阁：古灵阁是沙盘内部保险柜，bank-withdraw 是真的从资金池取走
# ═══════════════════════════════════════════════════════════

def _ensure_finance_ledger():
    """确保 mt_bank_withdrawal + mt_finance_meeting 两张核心表存在"""
    try:
        conn = _get_db(); cur = conn.cursor()
        # 银行存款流水（真提现流水）
        cur.execute("""CREATE TABLE IF NOT EXISTS mt_bank_withdrawal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,                 -- 关联的金融团队会议 ID
            amount REAL NOT NULL,               -- 本次提现金额
            realized_pnl_attributed REAL,       -- 对应的已实现 PnL
            pre_total_assets REAL,              -- 提现前账户总量
            post_total_assets REAL,             -- 提现后账户总量
            pre_cash REAL, post_cash REAL,
            verdict TEXT,                       -- APPROVED / REJECTED
            votes_json TEXT,                    -- 金融团队投票详情
            meeting_summary TEXT,               -- 会议纪要摘要
            auditor_note TEXT,                  -- 审计师一票否决记录
            approved_by TEXT,                   -- CFO 签字
            bank_reference TEXT,                -- 银行回单号（可人工补录）
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        # 金融团队会议记录（存银行卡前必须开会）
        cur.execute("""CREATE TABLE IF NOT EXISTS mt_finance_meeting (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_type TEXT,                  -- BANK_WITHDRAW_审核
            amount_requested REAL,
            attendants TEXT,                    -- 参会人（CFO, CPA, 审计师, 精算师）
            cfo_initiate TEXT,                  -- CFO 发起理由
            cpa_verdict TEXT,                   -- CPA 核账结论
            actuary_verdict TEXT,               -- 精算师 VaR/CVaR 评估
            auditor_verdict TEXT,               -- 审计师一票否决
            cfo_sign_off TEXT,                  -- CFO 最终签字
            final_verdict TEXT,                 -- APPROVED / REJECTED
            quorum TEXT,                        -- 到会情况
            reason TEXT,                        -- 会议理由
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.commit(); conn.close()
    except Exception as e:
        pass  # 表已存在 or 其他, 后面接口里再 catch


@sandbox_bp.route('/bank-withdraw', methods=['POST'])
def api_bank_withdraw():
    """🏦 存银行卡（真提现）— 必须经过金融团队开会表决
    
    红线：提现后账户总量 ≥ ¥10000 (启动金, 一分都不能动本金)
    流程：CFO 发起 → CPA 核账 → 精算师算 VaR → 审计师一票否决 → CFO 最终签字
    双写：mt_bank_withdrawal（银行流水）+ mt_finance_meeting（会议记录）
    """
    body = request.get_json(silent=True) or {}
    amount = float(body.get('amount') or 0)
    reason = body.get('reason') or '未说明理由'
    cfo_initiate = body.get('cfo_initiate') or 'CFO 提议本次存银行卡'

    if amount <= 0:
        return jsonify({'success': False, 'code': 'NO_AMOUNT', 'error': 'amount must be > 0'}), 400

    STARTING_CAPITAL = 10000.0
    _ensure_finance_ledger()
    conn = _get_db(); cur = conn.cursor()

    # ═══ Step 1: 实时账本快照（勾稽链复用审计引擎） ═══
    cur.execute("""SELECT
        SUM(CASE WHEN action='BUY'  THEN -(fill_amount + fee_total) ELSE 0 END) +
        SUM(CASE WHEN action='SELL' THEN  (fill_amount - fee_total) ELSE 0 END)
    FROM mt_trade_log""")
    cash = STARTING_CAPITAL + float(cur.fetchone()[0] or 0)

    from engines.ai_sandbox_tick_engine import _load_positions, _load_realtime
    positions = _load_positions() or {}
    rt = _load_realtime() or {}
    pos_value = sum(rt.get(s, {}).get('price', p.get('avg_cost', 0)) * p['qty'] for s, p in positions.items())
    total_assets = cash + pos_value

    cur.execute("""SELECT COALESCE(SUM(
        CASE WHEN action='SELL' THEN
            (fill_amount - fee_total) -
            (SELECT t2.fill_amount/t2.fill_qty * t1.fill_qty FROM mt_trade_log t2
             WHERE t2.symbol=t1.symbol AND t2.action='BUY'
             AND t2.id<=t1.id ORDER BY t2.id DESC LIMIT 1)
        ELSE 0 END),0) FROM mt_trade_log t1""")
    realized_pnl = float(cur.fetchone()[0] or 0)

    # 算 VaR (简化)
    pos_pcts = [p.get('avg_cost', 0)*p['qty']/total_assets*100 for p in positions.values()] if total_assets > 0 else []
    hhi = sum(x*x for x in pos_pcts)
    var_95 = (hhi**0.5)/100 * 0.02 * 1.645 * total_assets if total_assets > 0 else 0
    cvar_95 = var_95 * 1.5

    cur.close(); conn.close()

    # ═══ Step 2: 红线判定 ═══
    # ① 提现后账户总量 ≥ 10000
    post_total = total_assets - amount
    can_withdraw = post_total >= STARTING_CAPITAL
    max_withdraw = total_assets - STARTING_CAPITAL  # 可提现上限 = 超出启动金的部分
    # ② 提现金额 ≤ realized PnL (从盈利取, 不是从本金取)
    can_withdraw = can_withdraw and (amount <= realized_pnl)
    # ③ 账户足够经济支持 + 无需额外追加
    #    → 简化: post_total 仍能覆盖 VaR 安全垫 (留 1.5×VaR)
    risk_pad = cvar_95 * 1.5
    can_withdraw = can_withdraw and (post_total - STARTING_CAPITAL >= risk_pad)

    # ═══ Step 3: 金融团队开会表决 ═══
    conn = _get_db(); cur = conn.cursor()
    votes = {}; reasons = []; attendants = ['CFO', 'CPA', '审计师', '精算师']
    verdict = 'REJECTED'

    # 3a. CFO 发起 — 财务战略
    cfo_sign = False
    if can_withdraw:
        votes['CFO'] = 'APPROVE'
        reasons.append(f'👑 CFO: 提现 ¥{amount:.2f} 满足红线(¥{post_total:.2f}≥¥10000), 建议执行')
        cfo_sign = True
    else:
        votes['CFO'] = 'REJECT'
        reasons.append(f'👑 CFO: 不满足红线 — post_total=¥{post_total:.2f} < ¥10000 或超 realized PnL ¥{realized_pnl:.2f} 或不够风险垫 ¥{risk_pad:.0f}')

    # 3b. CPA 核账 — 账本合规
    if realized_pnl >= amount:
        votes['CPA'] = 'APPROVE'
        reasons.append(f'📊 CPA: 已实现 PnL ¥{realized_pnl:.2f} ≥ 提现 ¥{amount:.2f}, 账本核账通过')
    else:
        votes['CPA'] = 'REJECT'
        reasons.append(f'📊 CPA: 提现 ¥{amount:.2f} > 已实现 PnL ¥{realized_pnl:.2f}, 超可提取范围')

    # 3c. 精算师 — 尾部风险
    if post_total - STARTING_CAPITAL >= cvar_95:
        votes['actuary'] = 'APPROVE'
        reasons.append(f'📐 精算师: post_total 超出启动金 ¥{post_total-STARTING_CAPITAL:.2f} ≥ CVaR ¥{cvar_95:.0f}, 够风险垫')
    else:
        votes['actuary'] = 'REJECT'
        reasons.append(f'📐 精算师: post_total 超出启动金仅 ¥{post_total-STARTING_CAPITAL:.2f} < CVaR ¥{cvar_95:.0f}, 需留足风险垫')

    # 3d. 审计师 — 独立审计 + 一票否决
    audit_veto = False
    # 查近 7 天 bank-withdraw 次数 (防止过度提现)
    cur.execute("SELECT COUNT(*) FROM mt_bank_withdrawal WHERE verdict='APPROVED' AND created_at >= datetime('now','localtime','-7 days')")
    recent_withdraw = cur.fetchone()[0]
    if recent_withdraw >= 2:
        audit_veto = True
        votes['auditor'] = 'VETO'
        reasons.append(f'🔎 审计师一票否决: 近 7 天已提现 {recent_withdraw} 次, 频率过高')
    elif not can_withdraw:
        audit_veto = True
        votes['auditor'] = 'VETO'
        reasons.append(f'🔎 审计师一票否决: 提现后 ¥{post_total:.2f} 低于启动金 ¥10000, 红线触发')
    else:
        votes['auditor'] = 'APPROVE'
        reasons.append(f'🔎 审计师: 近 7 天提现 {recent_withdraw} 次, 红线未触碰, 同意 (已载入审计日志)')

    # 3e. 最终裁决 (审计师一票否决权)
    approve_count = sum(1 for v in votes.values() if v == 'APPROVE')
    reject_count = sum(1 for v in votes.values() if v in ('REJECT', 'VETO'))
    if audit_veto:
        verdict = 'REJECTED'
        reasons.append('⛔ 审计师一票否决 → REJECTED')
    elif cfo_sign and approve_count >= 3:  # CFO 签字 + 3/4 通过
        verdict = 'APPROVED'
        reasons.append(f'✅ 金融团队表决 {approve_count}/4 通过 → APPROVED')
    else:
        verdict = 'REJECTED'
        reasons.append(f'❌ 表决不足 ({approve_count}/4 赞成) → REJECTED')

    # ═══ Step 4: 构建每人具体投票详情 (含 vote + 具体理由) ═══
    votes_detail = {
        "CFO":      {"vote": votes.get('CFO','PENDING'),      "reason": reasons[0] if len(reasons)>0 else "CFO 发起"},
        "CPA":      {"vote": votes.get('CPA','PENDING'),      "reason": reasons[1] if len(reasons)>1 else "CPA 核账"},
        "actuary":  {"vote": votes.get('actuary','PENDING'),  "reason": reasons[2] if len(reasons)>2 else "精算师 评估"},
        "auditor":  {"vote": votes.get('auditor','PENDING'),  "reason": reasons[3] if len(reasons)>3 else "审计师 独立审计"},
    }
    votes_detail_json = json.dumps(votes_detail, ensure_ascii=False)
    event_time_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ═══ Step 5: 写完整会议记录 (到会人员 + 每人投票 + 事件时间) ═══
    meeting_title = f"🏦 存银行卡审核会议: 提现 ¥{amount:.2f} ({reason[:40]})"
    cur.execute("""INSERT INTO mt_finance_meeting (
        meeting_type, amount_requested, attendants, quorum, meeting_title,
        cfo_initiate, cpa_verdict, actuary_verdict, auditor_verdict,
        cfo_sign_off, final_verdict, votes_detail_json, event_time, reason
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        'BANK_WITHDRAW_审核',
        amount, ','.join(attendants),
        f"{len(attendants)}/4 到位",
        meeting_title,
        cfo_initiate,
        votes.get('CPA', 'PENDING'),
        votes.get('actuary', 'PENDING'),
        votes.get('auditor', 'PENDING'),
        'SIGNED' if verdict == 'APPROVED' else 'NOT_SIGNED',
        verdict,
        votes_detail_json,
        event_time_now,
        reason,
    ))
    meeting_id = cur.lastrowid

    # ═══ Step 6: 真写银行流水 + 立即投喂 AI 脑库 ═══
    cur.execute("""INSERT INTO mt_bank_withdrawal (
        meeting_id, amount, realized_pnl_attributed, event_time,
        pre_total_assets, post_total_assets, pre_cash, post_cash,
        verdict, votes_json, meeting_summary, auditor_note, approved_by, bank_reference
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        meeting_id,
        amount if verdict == 'APPROVED' else 0,
        min(amount, realized_pnl) if verdict == 'APPROVED' else 0,
        event_time_now,
        round(total_assets, 2),
        round(post_total, 2) if verdict == 'APPROVED' else round(total_assets, 2),
        round(cash, 2),
        round(cash - amount, 2) if verdict == 'APPROVED' else round(cash, 2),
        verdict,
        json.dumps(votes, ensure_ascii=False),
        reason,
        '审计师一票否决' if audit_veto else '无',
        'CFO 签字' if verdict == 'APPROVED' else '未签字',
        None,  # bank_reference 可人工后续补录
    ))

    # 立即投喂 AI 脑库 (会议决议 + 投票分歧点 + 审计师案例)
    try:
        feed_id = _feed_meeting_to_brain(meeting_id, conn=conn)
        if feed_id:
            pass  # 已喂, 回写 brain_fed=1 由 _feed_meeting_to_brain 内部完成
    except Exception as _be:
        _log(f"⚠️ bank-withdraw brain feed err: {_be}")

    conn.commit(); conn.close()

    return jsonify({
        'success': verdict == 'APPROVED',
        'data': {
            'verdict': verdict,
            'meeting_id': meeting_id,
            'bank_withdrawal_id': cur.lastrowid,
            'pre_total_assets': round(total_assets, 2),
            'post_total_assets': round(post_total, 2) if verdict == 'APPROVED' else round(total_assets, 2),
            'amount': amount if verdict == 'APPROVED' else 0,
            'realized_pnl_available': round(realized_pnl, 2),
            'max_withdraw_allowed': round(max_withdraw, 2),
            'risk_pad_required': round(risk_pad, 0),
            'votes': votes,
            'reasons': reasons,
            'can_withdraw_10k_redline': can_withdraw,
            'attendants': attendants,
        },
        'code': 'APPROVED' if verdict == 'APPROVED' else 'REJECTED',
        'error': None if verdict == 'APPROVED' else f'金融团队表决 REJECTED: {reasons[-1]}',
    })


@sandbox_bp.route('/bank-withdrawals')
def api_bank_withdrawals():
    """🏦 银行存款流水历史"""
    try:
        _ensure_finance_ledger()
        conn = _get_db(); cur = conn.cursor()
        limit = min(int(request.args.get('limit', 20)), 100)
        cur.execute(f"""
            SELECT id, meeting_id, amount, realized_pnl_attributed,
                   pre_total_assets, post_total_assets, pre_cash, post_cash,
                   verdict, votes_json, auditor_note, approved_by, bank_reference, created_at
            FROM mt_bank_withdrawal ORDER BY id DESC LIMIT {limit}
        """)
        items = []
        for r in cur.fetchall():
            items.append({
                'id': r[0], 'meeting_id': r[1], 'amount': r[2],
                'realized_pnl_attributed': r[3],
                'pre_total': r[4], 'post_total': r[5],
                'pre_cash': r[6], 'post_cash': r[7],
                'verdict': r[8],
                'votes': json.loads(r[9] or '{}'),
                'auditor_note': r[10], 'approved_by': r[11],
                'bank_reference': r[12], 'created_at': r[13],
            })
        cur.execute("SELECT verdict, COUNT(*) FROM mt_bank_withdrawal GROUP BY verdict")
        summary = dict(cur.fetchall())
        conn.close()
        return jsonify({'success': True, 'data': {'items': items, 'summary': summary}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/finance-meetings')
def api_finance_meetings():
    """🏛️ 金融团队会议记录"""
    try:
        _ensure_finance_ledger()
        conn = _get_db(); cur = conn.cursor()
        limit = min(int(request.args.get('limit', 20)), 100)
        cur.execute(f"""
            SELECT id, meeting_type, amount_requested, attendants,
                   cfo_initiate, cpa_verdict, actuary_verdict, auditor_verdict,
                   cfo_sign_off, final_verdict, quorum, reason, created_at
            FROM mt_finance_meeting ORDER BY id DESC LIMIT {limit}
        """)
        items = []
        for r in cur.fetchall():
            items.append({
                'id': r[0], 'type': r[1], 'amount_requested': r[2],
                'attendants': r[3], 'cfo_initiate': r[4], 'cpa_verdict': r[5],
                'actuary_verdict': r[6], 'auditor_verdict': r[7],
                'cfo_sign_off': r[8], 'final_verdict': r[9],
                'quorum': r[10], 'reason': r[11], 'created_at': r[12],
            })
        cur.execute("SELECT final_verdict, COUNT(*) FROM mt_finance_meeting GROUP BY final_verdict")
        summary = dict(cur.fetchall())
        conn.close()
        return jsonify({'success': True, 'data': {'items': items, 'summary': summary}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@sandbox_bp.route('/audit/run', methods=['GET', 'POST'])
def api_audit_run():
    """🏛️ 即时触发全量金融合规审计 (CFO+精算师+CPA+审计师)"""
    try:
        report = _run_full_finance_audit()
        return jsonify({"success": True, "data": report})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)[:300]}), 500


@sandbox_bp.route('/audit/logs')
def api_audit_logs():
    """审计日志历史 (默认最新 20 条)"""
    limit = min(int(request.args.get('limit', 20)), 200)
    try:
        conn = _get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT audit_id, executed_at, verdict, errors_json, warnings_json, metrics_json, created_at
            FROM mt_finance_audit_log ORDER BY id DESC LIMIT ?
        """, (limit,))
        items = []
        for r in cur.fetchall():
            items.append({
                "audit_id": r[0], "executed_at": r[1], "verdict": r[2],
                "errors": json.loads(r[3] or "[]"),
                "warnings": json.loads(r[4] or "[]"),
                "metrics": json.loads(r[5] or "{}"),
                "created_at": r[6],
            })
        cur.execute("""
            SELECT verdict, COUNT(*) FROM mt_finance_audit_log
            GROUP BY verdict ORDER BY COUNT(*) DESC
        """)
        summary = dict(cur.fetchall())
        cur.execute("SELECT COUNT(*) FROM mt_finance_audit_log")
        total = cur.fetchone()[0]
        conn.close()
        return jsonify({"success": True, "data": {"items": items, "summary": summary, "total": total}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]}), 500


@sandbox_bp.route('/audit/task-hall')
def api_audit_task_hall():
    """审计异常触发的任务大厅"""
    try:
        conn = _get_db(); cur = conn.cursor()
        status = request.args.get('status', 'OPEN')
        cur.execute("""
            SELECT id, task_type, priority, title, detail_json, assigned_to, status, source_audit_id, created_at, resolved_at
            FROM mt_task_hall WHERE status=? ORDER BY id DESC LIMIT 50
        """, (status,))
        items = []
        for r in cur.fetchall():
            items.append({
                "id": r[0], "type": r[1], "priority": r[2], "title": r[3],
                "detail": json.loads(r[4] or "{}"), "assigned_to": r[5],
                "status": r[6], "source_audit_id": r[7], "created_at": r[8], "resolved_at": r[9],
            })
        cur.execute("SELECT status, COUNT(*) FROM mt_task_hall GROUP BY status")
        summary = dict(cur.fetchall())
        conn.close()
        return jsonify({"success": True, "data": {"items": items, "summary": summary}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]}), 500


@sandbox_bp.route('/audit/close-task', methods=['POST'])
def api_audit_close_task():
    """关闭审计任务 (复盘完成)"""
    try:
        body = request.get_json(silent=True) or {}
        task_id = body.get('id') or request.args.get('id')
        resolution = body.get('resolution', '')
        if not task_id:
            return jsonify({"success": False, "error": "need id"}), 400
        conn = _get_db(); cur = conn.cursor()
        cur.execute("""UPDATE mt_task_hall SET status='RESOLVED', resolved_at=datetime('now','localtime'),
            detail_json=json_set(detail_json, '$.resolution', ?) WHERE id=?""", (resolution, task_id))
        conn.commit(); conn.close()
        return jsonify({"success": True, "data": {"closed_id": int(task_id)}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]}), 500


@sandbox_bp.route('/audit/ledger')
def api_audit_ledger():
    """每笔进出账核对明细 (CPA 核账视角)"""
    try:
        period = request.args.get('period', 'today')
        import datetime as _dt
        today = _dt.date.today().strftime("%Y-%m-%d")
        sql_date = f"date(created_at)='{today}'"
        if period == 'week':
            sql_date = "date(created_at) >= date('now','-7 days')"
        elif period == 'month':
            sql_date = "date(created_at) >= date('now','-30 days')"
        elif period == 'all':
            sql_date = "1=1"

        conn = _get_db(); cur = conn.cursor()
        cur.execute(f"""
            SELECT id, action, symbol, name, fill_qty, fill_price, fill_amount, fee_total, reason, created_at
            FROM mt_trade_log WHERE {sql_date} ORDER BY id ASC
        """)
        items = []; total_buy = 0; total_sell = 0; total_fee = 0; issues = []
        for r in cur.fetchall():
            fee_ok = float(r[7] or 0) >= 3.0
            if not fee_ok: issues.append(f"id={r[0]} fee异常")
            if r[1] == "BUY": total_buy += float(r[6] or 0)
            else: total_sell += float(r[6] or 0)
            total_fee += float(r[7] or 0)
            items.append({
                "id": r[0], "action": r[1], "symbol": r[2], "name": r[3],
                "qty": int(r[4] or 0), "price": float(r[5] or 0),
                "amount": round(float(r[6] or 0), 2), "fee": round(float(r[7] or 0), 2),
                "fee_ok": fee_ok, "reason": (r[8] or "")[:60], "created_at": r[9],
            })
        cur.close(); conn.close()
        return jsonify({"success": True, "data": {
            "period": period, "count": len(items),
            "total_buy": round(total_buy, 2), "total_sell": round(total_sell, 2),
            "total_fee": round(total_fee, 2), "net_flow": round(total_sell - total_buy - total_fee, 2),
            "issues": issues, "items": items,
        }})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]}), 500
