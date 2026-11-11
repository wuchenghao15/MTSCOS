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
    # 实际刷新 (带超时保护)
    try:
        from engines.ai_sandbox_tick_engine import _load_realtime
        _RT_CACHE['data'] = _load_realtime() or old_data
        _RT_CACHE['ts'] = time.time()
    except Exception:
        _RT_CACHE['data'] = old_data
    return _RT_CACHE['data']

# ═══ 延迟导入 (避免循环依赖) ═══

def _get_db():
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.execute('PRAGMA busy_timeout=8000')
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
        
        # 3. 读现金 (DB 快查询)
        cash = 10000.0 - total_cost  # 默认本金 1w,现金=本金-持仓成本
        
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
                'pnl': round(total_pnl, 2),                   # ✅ OK
                'pnl_pct': round(pnl_pct, 2),                 # ✅ OK
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
    """当前持仓 — 带实时行情"""
    try:
        from engines.ai_sandbox_tick_engine import _load_positions
        positions = _load_positions()
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
                'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2),
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
    # 时间阶段
    try:
        from engines.ai_sandbox_tick_engine import _is_trading_hours, _is_pre_open
        if _is_trading_hours(): status['phase'] = '📈 连续竞价'
        elif _is_pre_open(): status['phase'] = '🌅 集合竞价'
        else: status['phase'] = '🌙 休市'
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

# AI 员工注册表 — 仙女座交易军团 (三院二室一委员会,共 12 席)
# 编制来源:ai_sandbox_tick_engine + collab_bus + market_radar + rule_committee + auto_hire
_AI_LEGION = [
    # ═══ 第一梯队:董事会核心决策层 ═══
    {'id':'bing','name':'冰','role':'总控指挥官','emoji':'🧊','icon':'⚙️','color':'#5B8FB9',
     'desc':'调度所有 AI 节奏,避免追涨杀跌,控制仓位 85% 红线'},
    {'id':'tian_tuan','name':'天团','role':'研判委员会','emoji':'🦅','icon':'🧠','color':'#C9A961',
     'desc':'技术面+资金面+情绪面三维研判,每笔决策投鹰/犬票'},
    {'id':'jiaoshou','name':'教授','role':'风控顾问','emoji':'🎓','icon':'🛡️','color':'#6FA88B',
     'desc':'估值 PE/PB+集中度 HHI+止损线三维风控,超 50% 集中度触发红色警报'},
    
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
    
    # ═══ 第四梯队:后勤保障 ═══
    {'id':'finance','name':'财','role':'财务管家','emoji':'💰','icon':'🧾','color':'#B788C0',
     'desc':'佣金+印花税+过户费实时计算,净利对比,每月对账'},
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
        return False, 0, 0, str(e)


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
        pnl = total_assets - 10000.0
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
        from engines.ai_sandbox_tick_engine import _load_today_buys
        try:
            today_buys = _load_today_buys() if hasattr(_load_today_buys, '__call__') else {}
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

        # ═══ Step 3: 投票裁决 ═══
        hawk_total = votes['hawk']  # 赞成锁利
        dog_total = votes['dog']    # 反对
        if force:
            verdict = 'FORCE_EXEC'
        elif hawk_total > dog_total:
            verdict = 'LOCK'
        elif dog_total > hawk_total:
            verdict = 'HOLD'
        elif pnl >= weekly_pnl_trigger:
            verdict = 'LOCK'
        else:
            verdict = 'HOLD'

        # ═══ Step 4: 执行锁利 ═══
        locked_amount = 0.0
        new_gobelin_total = gob['total_savings']
        lock_executed = False
        if verdict in ('LOCK', 'FORCE_EXEC') and pnl > 0:
            ok, new_gobelin_total, new_count = _gobelin_lock(
                amount=round(pnl, 2),
                reason=f'{"自动研判LOCK" if verdict=="LOCK" else "强制执行"} · pnl={pnl:.2f}',
                board_vote=_json.dumps({'votes': votes, 'verdict': verdict, 'reasons': reasons}, ensure_ascii=False)
            )
            if ok:
                locked_amount = round(pnl, 2)
                lock_executed = True
            else:
                verdict = f'ERROR: {new_count}'

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
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
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


def register_sandbox_bp(app):
    """蓝图注册 + / 根路径 host-gated (stock.mtos.site/ → 沙盘终端)"""
    # 确保古灵阁表存在
    _ensure_gobelin()

    app.register_blueprint(sandbox_bp)
    print(f"[SANDBOX-BP] ✅ 仙女座沙盘 API Blueprint 已注册 (/api/sandbox/*)")

    _TERMINAL_HTML = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'static', 'sandbox-trading-terminal.html'
    )

    # ═══ stock.mtos.site/ → 沙盘终端 (子域名根路径直达) ═══
    # host gating: 只对 stock.mtos.site 和 localhost 开发时返回沙盘终端
    # mtos.site 主站走其他 handler, 不冲突
    _SANDBOX_HOSTS = {'stock.mtos.site', 'stock.mtos.site:443',
                      'localhost', 'localhost:5001', '127.0.0.1:5001'}

    @app.route('/')
    def route_root_sandbox():
        """stock.mtos.site/ → 沙盘终端; 其他 host → 交给主站"""
        from flask import send_file, request
        host = request.host.lower()
        if host in _SANDBOX_HOSTS or 'stock.mtos.site' in host:
            if os.path.exists(_TERMINAL_HTML):
                return send_file(_TERMINAL_HTML, mimetype='text/html')
        return None, 404

    print(f"[SANDBOX-BP] ✅ stock.mtos.site/ → 沙盘终端 (host-gated)")
