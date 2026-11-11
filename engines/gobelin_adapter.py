"""
🎯 Gobelin v2 统一数据适配层 — 唯一权威入口
所有引擎和 Flask 路由必须通过这里读数据, 禁止直接 SELECT 表

数据源优先级:
  1. mt_live_position (腾讯 API, A 股, 最高优先级)
  2. mt_gobelin_price (Guardian API, 覆盖 ETF/贵金属/可转债)
  3. mt_gobelin_position.current_price (持仓表内置, 兜底)

输出字段统一 model:
  get_price(code)     → {price, source_label, pnl_pct, prev_close, updated_at}
  get_account()       → {total_assets, cash_balance, position_value, cumulative_pnl, ...}
  get_positions()     → [{asset_code, asset_name, channel, qty, real_price, market_value, pnl_pct, src_label, open_date}, ...]
  get_sources()       → {live_count, price_count, position_count, is_trading_hours}
"""
import os, sys, datetime as _dt

# channel 常量
CHANNELS = {
    'A_STOCK': {'name':'A股主板','icon':'📈','col':'#ef4444','cn_name':'A股'},
    'ETF':     {'name':'ETF指数','icon':'📊','col':'#3b82f6','cn_name':'ETF'},
    'METAL':   {'name':'贵金属','icon':'🥇','col':'#f59e0b','cn_name':'贵金属'},
    'BOND':    {'name':'可转债','icon':'📜','col':'#8b5cf6','cn_name':'可转债'},
    'FUND':    {'name':'基金','icon':'💹','col':'#10b981','cn_name':'基金'},
    'BANK':    {'name':'理财','icon':'🏦','col':'#06b6d4','cn_name':'理财'},
    'CASH':    {'name':'现金账户','icon':'💵','col':'#22c55e','cn_name':'现金'},
}

# URL code 映射 (URL 小写别名 → Gobelin channel)
URL_TO_CHANNEL = {
    'stock':'A_STOCK','a_stock':'A_STOCK','astock':'A_STOCK',
    'etf':'ETF','metal':'METAL','bond':'BOND','fund':'FUND','bank':'BANK',
    'cash':'CASH','other':'OTHER',
}

# 腾讯 API 不覆盖的 channel (结构性限制)
LIVE_UNAVAILABLE_CHANNELS = {'ETF','METAL','BOND','FUND','BANK'}


def get_db_path():
    """权威 DB 路径"""
    return os.environ.get('MTSCOS_DB_PATH') or \
           os.path.expanduser('~/MTSCOS_AI_Project/flask-app/database/app.db')


def get_conn():
    """返回带 Row 的 sqlite3 连接"""
    import sqlite3
    conn = sqlite3.connect(get_db_path(), timeout=30)
    conn.execute('PRAGMA busy_timeout=60000')
    conn.row_factory = sqlite3.Row
    return conn


def is_trading_hours():
    """判断 A 股是否在交易时段 (简化版: 周一-周五 9:30-11:30 / 13:00-15:00)"""
    now = _dt.datetime.now()
    if now.weekday() >= 5: return False
    t = now.time()
    morning = _dt.time(9,30) <= t <= _dt.time(11,30)
    afternoon = _dt.time(13,0) <= t <= _dt.time(15,0)
    return morning or afternoon


def _build_live_map(conn):
    """拉 mt_live_position 全表 dict"""
    cur = conn.cursor()
    cur.execute("SELECT symbol, price, prev_close, pnl_pct, updated_at FROM mt_live_position")
    return {r['symbol']: dict(r) for r in cur.fetchall()}


def _build_gp_map(conn):
    """拉 mt_gobelin_price 全表 dict"""
    cur = conn.cursor()
    cur.execute("SELECT asset_code, last_price, prev_close, chg_pct, source, fetched_at FROM mt_gobelin_price")
    return {r['asset_code']: dict(r) for r in cur.fetchall()}


def get_price(conn, symbol):
    """
    统一取价 — 适配层核心
    返回 dict: {price, source_label, pnl_pct, prev_close, updated_at}
    source_label: LIVE / API / FALLBACK
    
    优先级: mt_live_position > mt_gobelin_price > 持仓表 avg_cost
    """
    if not symbol:
        return {'price':0,'source_label':'FALLBACK','pnl_pct':0,'prev_close':0,'updated_at':''}
    
    # 1. LIVE
    cur = conn.cursor()
    cur.execute("SELECT symbol, price, prev_close, pnl_pct, updated_at FROM mt_live_position WHERE symbol=?", (symbol,))
    l = cur.fetchone()
    if l and l['price'] and l['price'] > 0:
        return {
            'price': l['price'],
            'source_label': 'LIVE',
            'pnl_pct': l['pnl_pct'] or 0,
            'prev_close': l['prev_close'] or l['price'],
            'updated_at': l['updated_at'] or '',
        }
    
    # 2. API (Guardian)
    cur.execute("SELECT last_price, prev_close, chg_pct, source, fetched_at FROM mt_gobelin_price WHERE asset_code=?", (symbol,))
    gp = cur.fetchone()
    if gp and gp['last_price'] and gp['last_price'] > 0:
        return {
            'price': gp['last_price'],
            'source_label': 'API',
            'pnl_pct': gp['chg_pct'] or 0,
            'prev_close': gp['prev_close'] or gp['last_price'],
            'updated_at': gp['fetched_at'] or '',
        }
    
    # 3. FALLBACK (持仓表 avg_cost)
    cur.execute("SELECT avg_cost_basis, prev_close FROM mt_gobelin_position WHERE asset_code=? AND qty>0 LIMIT 1", (symbol,))
    p = cur.fetchone()
    if p and p['avg_cost_basis']:
        return {
            'price': p['avg_cost_basis'],
            'source_label': 'FALLBACK',
            'pnl_pct': 0,
            'prev_close': p['prev_close'] or p['avg_cost_basis'],
            'updated_at': '',
        }
    
    return {'price':0,'source_label':'FALLBACK','pnl_pct':0,'prev_close':0,'updated_at':''}


def get_account(conn):
    """
    Gobelin 主账户 (mt_gobelin_account WHERE account_name='GOBELIN_MAIN')
    返回 dict, 包含计算好的 cumulative_pnl / cash_ratio 等派生指标
    """
    cur = conn.cursor()
    cur.execute("SELECT * FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'")
    row = cur.fetchone()
    if not row:
        # 不存在 — 返回默认空账户
        return {
            'account_name':'GOBELIN_MAIN','initial_endowment':0,
            'cash_balance':0,'position_value':0,'total_assets':0,
            'unrealized_pnl':0,'realized_pnl':0,'cumulative_pnl':0,
            'cumulative_pnl_pct':0,'cash_ratio':0,'trade_count':0,
            'created_at':'','updated_at':'',
        }
    
    acc = dict(row)
    acc['total_assets'] = acc.get('total_assets') or acc['cash_balance'] + acc.get('position_value',0)
    acc['cumulative_pnl'] = acc['total_assets'] - acc['initial_endowment']
    acc['cumulative_pnl_pct'] = acc['cumulative_pnl'] / acc['initial_endowment'] * 100 if acc['initial_endowment'] else 0
    acc['cash_ratio'] = acc['cash_balance'] / acc['total_assets'] * 100 if acc['total_assets'] else 0
    return acc


def get_positions(conn):
    """
    Gobelin 持仓列表 (mt_gobelin_position WHERE qty>0)
    每条叠加: real_price (通过 adapter 取价), src_label, 今日 PnL 等
    """
    cur = conn.cursor()
    cur.execute("""SELECT * FROM mt_gobelin_position WHERE qty>0 ORDER BY market_value DESC""")
    raw = [dict(r) for r in cur.fetchall()]
    
    live_map = _build_live_map(conn)
    gp_map = _build_gp_map(conn)
    
    for p in raw:
        sym = p['asset_code']
        
        # 取价 (优先级: LIVE > API > 持仓表 current_price > avg_cost)
        l = live_map.get(sym)
        gp = gp_map.get(sym)
        if l and l.get('price') and l['price'] > 0:
            real_price = l['price']
            src = 'LIVE'
            pnl_pct = l.get('pnl_pct',0) or 0
        elif gp and gp.get('last_price') and gp['last_price'] > 0:
            real_price = gp['last_price']
            src = 'API'
            pnl_pct = gp.get('chg_pct',0) or 0
        else:
            real_price = p.get('current_price') or p.get('avg_cost_basis',0) or 0
            src = 'FALLBACK'
            pnl_pct = p.get('unrealized_pnl_pct',0) or 0
        
        p['real_price'] = real_price
        p['src_label'] = src
        p['live_pnl_pct'] = pnl_pct
        
        # 用 real_price 重算 market_value + unrealized_pnl
        if real_price > 0:
            p['market_value'] = p['qty'] * real_price
            p['unrealized_pnl'] = p['market_value'] - p['total_cost']
            p['unrealized_pnl_pct'] = p['unrealized_pnl'] / p['total_cost'] * 100 if p['total_cost'] else 0
            p['today_pnl'] = p['qty'] * (real_price - (p.get('prev_close') or real_price))
    
    return raw


def get_account_and_positions(conn):
    """一次性获取账户 + 持仓 + 渠道聚合 (Flask 路由最常用)"""
    acc = get_account(conn)
    pos = get_positions(conn)
    
    # 渠道聚合
    by_ch = {}
    for p in pos:
        ch = p['channel'] or 'OTHER'
        if ch not in by_ch:
            by_ch[ch] = {'code':ch,'mv':0,'pnl':0,'rows':0}
        by_ch[ch]['mv'] += p['market_value'] or 0
        by_ch[ch]['pnl'] += p['unrealized_pnl'] or 0
        by_ch[ch]['rows'] += 1
    
    # 现金
    by_ch['CASH'] = {'code':'CASH','mv':acc['cash_balance'],'pnl':0,'rows':0}
    
    channels_out = []
    for code, v in by_ch.items():
        meta = CHANNELS.get(code, CHANNELS.get('OTHER',{}))
        channels_out.append({
            'code': code,
            'name': meta.get('name', code),
            'icon': meta.get('icon','💰'),
            'color': meta.get('col','#888'),
            'mv': v['mv'],
            'pnl': v['pnl'],
            'rows': v['rows'],
            'pct': v['mv']/acc['total_assets'] if acc['total_assets'] else 0,
        })
    
    return {
        'account': acc,
        'positions': pos,
        'channels': sorted(channels_out, key=lambda c: -c['mv']),
        'is_trading': is_trading_hours(),
        'updated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def get_channel_detail(conn, channel_code):
    """单渠道详情 (/governance/channel/<code> 路由用)"""
    # URL code → Gobelin channel
    cc_upper = URL_TO_CHANNEL.get(channel_code.lower(), channel_code.upper())
    
    # 持仓筛选
    cur = conn.cursor()
    if cc_upper == 'CASH':
        # 现金渠道
        acc = get_account(conn)
        positions = []
        ch_mv = acc['cash_balance']
        ch_pnl = 0
    else:
        all_pos = get_positions(conn)
        positions = [p for p in all_pos if p['channel'] == cc_upper]
        ch_mv = sum(p['market_value'] or 0 for p in positions)
        ch_pnl = sum(p['unrealized_pnl'] or 0 for p in positions)
    
    acc = get_account(conn)
    return {
        'channel_code': cc_upper,
        'cfg': CHANNELS.get(cc_upper, {'name':cc_upper,'icon':'💰','col':'#888'}),
        'account': acc,
        'positions': positions,
        'channel_mv': ch_mv,
        'channel_pnl': ch_pnl,
        'channel_count': len(positions),
        'today_pnl': sum(p.get('today_pnl',0) for p in positions),
        'init_cash': acc['initial_endowment'],
        'now_str': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'is_trading': is_trading_hours(),
    }
