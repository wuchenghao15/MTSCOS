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
    """账户状态 — 本金/现金/持仓市值/总资产/盈亏/手续费"""
    try:
        from core.broker_adapter import SandboxAdapter
        info = SandboxAdapter().query_cash()
        # 附加实时持仓 + 盈亏 (用缓存行情)
        from engines.ai_sandbox_tick_engine import _load_positions
        positions = _load_positions()
        rt = _cached_realtime()
        pos_detail = []
        total_pnl = 0.0
        for sym, pos in positions.items():
            cur = rt.get(sym, {})
            cur_price = cur.get('price', pos['avg_cost'])
            pnl = (cur_price - pos['avg_cost']) * pos['qty']
            pnl_pct = (cur_price - pos['avg_cost']) / pos['avg_cost'] * 100 if pos['avg_cost'] else 0
            total_pnl += pnl
            pos_detail.append({
                'symbol': sym,
                'name': cur.get('name', ''),
                'qty': pos['qty'],
                'avg_cost': round(pos['avg_cost'], 2),
                'cur_price': round(cur_price, 2),
                'market_value': round(cur_price * pos['qty'], 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'ma5': cur.get('ma5', 0),
                'ma10': cur.get('ma10', 0),
                'ma20': cur.get('ma20', 0),
                'chg_pct': cur.get('chg_pct', 0),
            })
        info['positions_detail'] = pos_detail
        info['position_count'] = len(positions)
        info['realized_pnl_today'] = total_pnl  # 简化
        info['ts'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return jsonify({'success': True, 'data': info})
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

    if not data or len(data) < 10:
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
    if len(dates) < 10:
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
                        or k == sym or k.endswith(sym)):
                    matched[k] = v
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


def _run_eng_review(review_type: str):
    """隔离 wrapper — 避免 Flask 主路由内调用阻塞"""
    try:
        from engines.ai_sandbox_tick_engine import run_review_session
        run_review_session(review_type)
    except Exception as e:
        import sys
        print(f"[SANDBOX-BP] trigger-review err: {e}", file=sys.stderr)


def register_sandbox_bp(app):
    """蓝图注册 + / 根路径 host-gated (stock.mtos.site/ → 沙盘终端)"""
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
