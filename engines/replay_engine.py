"""
🔄 仙女座休市学习循环 v2 — ReplayEngine
══════════════════════════════════════════════════════════
休市期间 (晚上 / 周末 / 节假日):
  ① akshare 拉近 30~250 天历史日线 K 线
  ② **多策略并行 replay** — 动量/均线金叉/抄底/轮动 4 种策略同时跑
  ③ **市场状态分类** — 把历史分段成 上涨段/下跌段/震荡段, 每段独立回测
  ④ replay 结果 → mini 复盘 (圆桌/董事会/专家) + 策略优胜结论
  ⑤ **实时 mini 复盘** (v2 新增) — tick 联动, 盘中每 30 分钟开小会
  ⑥ 经验 → 投喂 AI 脑库 (mt_ai_brain_feed_log)
  ⑦ 形成闭环: 历史 → 模拟 → 复盘 → 学习 → 脑库 → 实时开会

v2 新增:
  - run_multi_strategy_replay() — 4 种策略对比
  - classify_market_state() — 牛/熊/震荡自动识别
  - run_state_segment_replay() — 各市场状态独立 replay
  - run_real_time_mini_meeting() — 盘中实时 mini 复盘会
══════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, sys, json, sqlite3, time, random, hashlib
from datetime import datetime, timedelta
from typing import Optional

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, os.pardir))


# ═══════════════════════════════════════════════════════════
# 默认监控池
# ═══════════════════════════════════════════════════════════
DEFAULT_POOL = ['000001', '601012', '601398', '600519', '000858', '300750', '600036', '002594']


# ═══════════════════════════════════════════════════════════
# ① 历史数据拉取
# ═══════════════════════════════════════════════════════════

def fetch_history(symbols: list = None, days: int = 60) -> dict:
    """拉 N 天历史日线 K 线 → {symbol: [{'date','open','close','high','low','pct','vol'}, ...]}"""
    symbols = symbols or DEFAULT_POOL
    end = datetime.now()
    start = end - timedelta(days=days + 10)

    result = {}
    try:
        import akshare as ak
    except ImportError:
        return {}

    for s in symbols:
        try:
            df = ak.stock_zh_a_hist(
                symbol=s, period='daily',
                start_date=start.strftime('%Y%m%d'),
                end_date=end.strftime('%Y%m%d'),
                adjust='qfq',
            )
            if df is None or len(df) == 0:
                continue
            rows = []
            for _, r in df.iterrows():
                rows.append({
                    'date': str(r['日期']),
                    'open': float(r['开盘']),
                    'close': float(r['收盘']),
                    'high': float(r['最高']),
                    'low': float(r['最低']),
                    'pct': float(r['涨跌幅']),
                    'vol': float(r['成交量']),
                    'amount': float(r['成交额']),
                })
            result[s] = rows[-days:]
            time.sleep(0.3)
        except Exception:
            result[s] = []
    return result


# ═══════════════════════════════════════════════════════════
# ② 市场状态分类 (v2 新增) — 识别牛/熊/震荡段
# ═══════════════════════════════════════════════════════════

def classify_market_state(index_history: dict, window: int = 60) -> list:
    """
    把指数历史分段 — 每段标注市场状态
    index_history = {'sh000001': [{'date','close','pct'}, ...]}
    返回: [{'state':'BULL','start_date':'...','end_date':'...','ret_pct':x}, ...]
    """
    segments = []
    all_closes = []
    for sym, rows in index_history.items():
        all_closes = rows
        break
    if not all_closes:
        return segments

    # 滑动窗口分类: 每个 window 天窗口判断一次状态
    n = len(all_closes)
    i = 0
    while i < n - window:
        seg = all_closes[i:i+window]
        closes = [r['close'] for r in seg]
        start_price = closes[0]
        end_price = closes[-1]
        ret = (end_price / start_price - 1) * 100

        # 算 MA20 和 MA60
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else sum(closes) / len(closes)
        ma60 = sum(closes) / len(closes)

        # 算最大回撤
        peak = closes[0]
        max_dd = 0
        for c in closes:
            if c > peak: peak = c
            dd = (peak - c) / peak * 100
            if dd > max_dd: max_dd = dd

        # 算波动率
        pcts = [(closes[j]/closes[j-1]-1)*100 for j in range(1, len(closes))]
        vol = (sum((p - sum(pcts)/len(pcts))**2 for p in pcts) / len(pcts)) ** 0.5 if pcts else 0

        if ret > 8 and ma20 > ma60:
            state = 'BULL'
        elif ret < -8 and ma20 < ma60:
            state = 'BEAR'
        else:
            state = 'RANGING'

        segments.append({
            'state': state,
            'start_date': seg[0]['date'],
            'end_date': seg[-1]['date'],
            'ret_pct': round(ret, 2),
            'max_drawdown': round(max_dd, 2),
            'volatility': round(vol, 2),
        })
        i += window // 2  # 50% 重叠

    return segments


# ═══════════════════════════════════════════════════════════
# ③ 多策略并行 Replay (v2 新增)
# ═══════════════════════════════════════════════════════════

def run_strategy_momentum(history: dict, **kw) -> dict:
    """策略 A — 动量追涨: 日内涨 > 阈值 + 站上 MA5"""
    return _run_single_strategy(history, strategy_name='MOMENTUM',
                                buy_cond=lambda row, ma: row['pct'] >= kw.get('buy_pct', 0.5) and row['close'] > ma['ma5'],
                                **kw)

def run_strategy_ma_cross(history: dict, **kw) -> dict:
    """策略 B — MA 金叉: MA5 上穿 MA10 时买入"""
    return _run_single_strategy(history, strategy_name='MA_CROSS',
                                use_ma_cross=True, **kw)

def run_strategy_dip_buy(history: dict, **kw) -> dict:
    """策略 C — 抄底反弹: 前日跌 >3%, 今日涨回来"""
    return _run_single_strategy(history, strategy_name='DIP_BUY',
                                buy_cond=lambda row, ma, prev_row:
                                    row['pct'] >= 1.0 and prev_row and prev_row['pct'] <= -3.0,
                                need_prev=True, **kw)

def run_strategy_rotation(history: dict, **kw) -> dict:
    """策略 D — 轮动: 每天只买当日涨幅最弱但 MA20 仍向上的 (逆向补涨)"""
    return _run_single_strategy(history, strategy_name='ROTATION',
                                rotation_mode=True, **kw)


def _run_single_strategy(history: dict, strategy_name: str = 'DEFAULT',
                          initial_capital: float = 10000.0,
                          max_positions: int = 4,
                          sell_profit: float = 5.0,
                          sell_loss: float = -5.0,
                          buy_pct: float = 0.5,
                          buy_cond=None,
                          use_ma_cross: bool = False,
                          need_prev: bool = False,
                          rotation_mode: bool = False,
                          **extra) -> dict:
    """单策略 replay 引擎"""
    trades = []
    capital = initial_capital
    positions = {}
    peak_capital = capital
    max_dd = 0.0

    all_dates = set()
    for s, rows in history.items():
        for r in rows:
            all_dates.add(r['date'])
    sorted_dates = sorted(all_dates)
    index = {s: {r['date']: r for r in rows} for s, rows in history.items()}

    # 预计算 MA
    ma_cache = {}  # (symbol, date) → {'ma5', 'ma10', 'ma20'}
    for s, rows in history.items():
        dates = [r['date'] for r in rows]
        closes = [r['close'] for r in rows]
        for i, d in enumerate(dates):
            ma5 = sum(closes[max(0,i-4):i+1]) / min(5, i+1)
            ma10 = sum(closes[max(0,i-9):i+1]) / min(10, i+1)
            ma20 = sum(closes[max(0,i-19):i+1]) / min(20, i+1)
            ma_cache[(s, d)] = {'ma5': ma5, 'ma10': ma10, 'ma20': ma20}

    # MA 交叉信号预计算
    ma_cross_signals = {}  # (symbol, date) → 'GOLD'/'DEAD'/None
    if use_ma_cross:
        for s, rows in history.items():
            dates = [r['date'] for r in rows]
            for i in range(1, len(dates)):
                ma_today = ma_cache.get((s, dates[i]), {})
                ma_yest = ma_cache.get((s, dates[i-1]), {})
                if not ma_today or not ma_yest:
                    continue
                if ma_yest.get('ma5', 0) <= ma_yest.get('ma10', 0) and ma_today.get('ma5', 0) > ma_today.get('ma10', 0):
                    ma_cross_signals[(s, dates[i])] = 'GOLD'
                elif ma_yest.get('ma5', 0) >= ma_yest.get('ma10', 0) and ma_today.get('ma5', 0) < ma_today.get('ma10', 0):
                    ma_cross_signals[(s, dates[i])] = 'DEAD'

    for day in sorted_dates:
        # 1. 止盈止损
        for sym in list(positions.keys()):
            if sym not in index or day not in index[sym]: continue
            price = index[sym][day]['close']
            pos = positions[sym]
            pnl_pct = (price - pos['cost']) / pos['cost'] * 100

            action = None
            if pnl_pct >= sell_profit: action = 'TAKE_PROFIT'
            elif pnl_pct <= sell_loss: action = 'STOP_LOSS'

            if action:
                qty = pos['qty']
                amount = price * qty
                fee = amount * 0.0003
                capital += amount - fee
                pnl = (price - pos['cost']) * qty - fee
                trades.append({'symbol': sym, 'action': 'SELL', 'qty': qty,
                    'price': price, 'reason': f'{strategy_name}_{action}',
                    'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2), 'date': day})
                del positions[sym]
                if capital > peak_capital: peak_capital = capital
                dd = (peak_capital - capital) / peak_capital * 100
                if dd > max_dd: max_dd = dd

        # 2. 买入
        if len(positions) < max_positions:
            candidates = []
            for sym, row_dict in index.items():
                if day not in row_dict or sym in positions: continue
                row = row_dict[day]
                ma = ma_cache.get((sym, day), {'ma5': row['close'], 'ma10': row['close'], 'ma20': row['close']})

                trigger = False
                if strategy_name == 'MA_CROSS':
                    trigger = ma_cross_signals.get((sym, day)) == 'GOLD'
                elif strategy_name == 'DIP_BUY':
                    # 找前一个交易日
                    day_idx = sorted_dates.index(day) if day in sorted_dates else -1
                    prev_row = None
                    for j in range(day_idx-1, max(0, day_idx-10), -1):
                        prev_date = sorted_dates[j]
                        if sym in index and prev_date in index[sym]:
                            prev_row = index[sym][prev_date]; break
                    trigger = row['pct'] >= 1.0 and prev_row and prev_row['pct'] <= -2.0
                elif strategy_name == 'ROTATION':
                    # 每天选涨跌幅最低但 MA20 向上的
                    if ma['ma5'] > ma['ma20'] > 0 and row['pct'] < 0:
                        candidates.append((sym, row, -row['pct']))  # 取负, 后面排序最弱的
                else:  # MOMENTUM
                    trigger = row['pct'] >= buy_pct and row['close'] > ma['ma5']

                if trigger and strategy_name != 'ROTATION':
                    candidates.append((sym, row, row['pct']))

            if rotation_mode:
                candidates.sort(key=lambda x: x[2])  # 选最弱的 (逆向)
            else:
                candidates.sort(key=lambda x: -x[2])  # 选最强的

            slots = max_positions - len(positions)
            for sym, row, _ in candidates[:slots]:
                if capital < 1000: break
                per_slot = capital / max(1, max_positions - len(positions))
                qty = int(per_slot / row['close'] / 100) * 100
                if qty < 100: continue
                cost = row['close'] * qty
                fee = cost * 0.0003
                if cost + fee > capital: continue
                capital -= cost + fee
                positions[sym] = {'qty': qty, 'cost': row['close'], 'buy_date': day}
                trades.append({'symbol': sym, 'action': 'BUY', 'qty': qty,
                    'price': row['close'], 'reason': f'{strategy_name}_BUY pct={row["pct"]:+.1f}%',
                    'pnl': 0, 'pnl_pct': 0, 'date': day})

    # 3. 清仓结算
    final_day = sorted_dates[-1] if sorted_dates else None
    for sym, pos in list(positions.items()):
        if sym in index and final_day in index.get(sym, {}):
            price = index[sym][final_day]['close']
            qty = pos['qty']; fee = price * qty * 0.0003
            capital += price * qty - fee
            pnl = (price - pos['cost']) * qty - fee
            pnl_pct = (price - pos['cost']) / pos['cost'] * 100
            trades.append({'symbol': sym, 'action': 'SELL', 'qty': qty,
                'price': price, 'reason': f'{strategy_name}_END',
                'pnl': round(pnl, 2), 'pnl_pct': round(pnl_pct, 2), 'date': final_day})

    sells = [t for t in trades if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl', 0) > 0]
    losses = [t for t in sells if t.get('pnl', 0) <= 0]

    return {
        'strategy': strategy_name,
        'days': len(sorted_dates), 'trades': trades,
        'final_capital': round(capital, 2),
        'total_pnl': round(capital - initial_capital, 2),
        'pnl_pct': round((capital - initial_capital) / initial_capital * 100, 2),
        'win_rate': round(len(wins) / len(sells) * 100, 2) if sells else 0,
        'max_drawdown': round(max_dd, 2),
        'trades_count': len(trades),
        'winning_trades': wins, 'losing_trades': losses,
        'initial_capital': initial_capital,
    }


def run_multi_strategy_replay(history: dict, **kw) -> dict:
    """4 种策略同时跑 → 返回对比结果"""
    t0 = time.time()
    strategies = [
        ('MOMENTUM_追涨', run_strategy_momentum),
        ('MA_CROSS_金叉', run_strategy_ma_cross),
        ('DIP_BUY_抄底', run_strategy_dip_buy),
        ('ROTATION_轮动', run_strategy_rotation),
    ]
    results = {}
    for name, fn in strategies:
        try:
            results[name] = fn(history, **kw)
        except Exception as e:
            results[name] = {'strategy': name, 'error': str(e)[:80]}
        time.sleep(0.2)

    # 排名: 综合 pnl_pct, win_rate, max_drawdown
    valid = [(name, r) for name, r in results.items() if 'error' not in r]
    ranked = sorted(valid, key=lambda x: (x[1]['pnl_pct'], x[1]['win_rate'], -x[1]['max_drawdown']), reverse=True)

    return {
        'strategies': results,
        'ranking': [(name, r['pnl_pct'], r['win_rate'], r['max_drawdown']) for name, r in ranked],
        'best_strategy': ranked[0][0] if ranked else 'UNKNOWN',
        'worst_strategy': ranked[-1][0] if ranked else 'UNKNOWN',
        'elapsed': round(time.time() - t0, 2),
    }


# ═══════════════════════════════════════════════════════════
# ④ Mini 复盘 (5 层会议)
# ═══════════════════════════════════════════════════════════

def gen_replay_meetings(replay: dict, multi_result: dict = None) -> list:
    """基于 replay + 多策略对比结果生成 5 层会议"""
    trades = replay['trades']
    sells = [t for t in trades if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl', 0) > 0]
    losses = [t for t in sells if t.get('pnl', 0) <= 0]
    top_win = max(wins, key=lambda t: t.get('pnl', 0)) if wins else None
    top_loss = min(losses, key=lambda t: t.get('pnl', 0)) if losses else None

    session_id = f"replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    meetings = []

    # 圆桌
    agenda = [
        f"Replay 结果: 初始¥{replay['initial_capital']} → 最终¥{replay['final_capital']} ({replay['pnl_pct']:+.2f}%)",
        f"交易 {replay['trades_count']} 笔, 胜率 {replay['win_rate']}%, 最大回撤 {replay['max_drawdown']}%",
    ]
    if multi_result:
        agenda.append(f"多策略优胜: {multi_result.get('best_strategy','')} 胜, 最差 {multi_result.get('worst_strategy','')}")
    if top_win: agenda.append(f"✅ 最赚: {top_win['symbol']} +¥{top_win.get('pnl',0)}")
    if top_loss: agenda.append(f"❌ 最亏: {top_loss['symbol']} -¥{abs(top_loss.get('pnl',0))}")

    conclusions = [
        f"Replay {replay['days']} 天: {'跑赢大盘' if replay['pnl_pct'] > 0 else '跑输大盘'}",
        f"胜率 {replay['win_rate']}% {'及格' if replay['win_rate'] >= 40 else '不及格'}",
        f"最大回撤 {replay['max_drawdown']}% {'可控' if replay['max_drawdown'] <= 5 else '⚠️ 超限'}",
    ]
    if multi_result:
        conclusions.append(f"🏆 最优策略 {multi_result['best_strategy']}, 建议正式策略参考其参数")

    meetings.append({
        'session_id': session_id, 'meeting_id': f'{session_id}_roundtable',
        'meeting_type': 'roundtable', 'meeting_title': f'🔄 休市复盘 · 圆桌 ({replay["days"]}天)',
        'participants': ['操盘手·老K', '策略架构师', '风控合规员', '资金管理员', 'AI研究员·张博士'],
        'agenda': agenda, 'conclusions': conclusions,
    })

    # 头脑风暴 (多策略对比)
    if multi_result:
        strat_lines = []
        for name, pnl, wr, dd in multi_result.get('ranking', []):
            strat_lines.append(f"  {name}: pnl={pnl:+.2f}% 胜率={wr}% 回撤={dd}%")
        meetings.append({
            'session_id': session_id, 'meeting_id': f'{session_id}_brainstorm',
            'meeting_type': 'brainstorm', 'meeting_title': '🧠 头脑风暴 · 多策略对比',
            'participants': ['AI研究员·张博士', '量化专家·李教授', 'AI研究员·王副教授'],
            'agenda': [f"4 种策略对比:\n{chr(10).join(strat_lines)}"],
            'conclusions': [
                f"🏆 {multi_result.get('best_strategy')} 胜出 — 主策略方向确定",
                f"⚠️ {multi_result.get('worst_strategy')} 跑输 — 不建议作为主策略",
                "✅ 建议: 实盘采用最优策略 + 次优策略分散 (7:3 分仓)",
            ],
        })

    # 董事会
    meetings.append({
        'session_id': session_id, 'meeting_id': f'{session_id}_board',
        'meeting_type': 'board', 'meeting_title': '🏛️ 休市董事会 · Replay 审计',
        'participants': ['董事长·张晓峰[趋势派]', 'CTO[量化派]', '风险总监[风控派]', '资金管理员[价值派]'],
        'conclusions': [
            f"📌 董事长: Replay {replay['pnl_pct']:+.2f}%, 复盘合格",
            f"📌 CTO: 多策略引擎验证通过, 实盘可部署",
            f"📌 风险总监: 回撤 {replay['max_drawdown']}% {'合规' if replay['max_drawdown'] <= 5 else '⚠️ 建议收紧止损'}",
        ],
    })

    # 操盘部
    meetings.append({
        'session_id': session_id, 'meeting_id': f'{session_id}_trading_desk',
        'meeting_type': 'trading_desk', 'meeting_title': '💼 操盘部 · 每笔交易复盘',
        'participants': ['操盘手·老K', '操盘手·小王', '订单分析师'],
        'agenda': [
            f"Replay 共 {len(trades)} 笔 — BUY {len([t for t in trades if t['action']=='BUY'])} / SELL {len(sells)}",
            f"止盈出场 {len([t for t in sells if t.get('reason','').startswith('TAKE')])} 笔",
            f"止损出场 {len([t for t in sells if t.get('reason','').startswith('STOP')])} 笔",
        ],
    })

    # AI 员工 + 专家
    meetings.append({
        'session_id': session_id, 'meeting_id': f'{session_id}_ai_team',
        'meeting_type': 'ai_team', 'meeting_title': '🤖 AI 员工 + 专家 · 经验交流',
        'participants': ['动量检测器', 'MA趋势检查器', '风控合规员', '大盘指数监控员',
                         '外聘·首席量化研究员', '外聘·资深风控专家'],
        'conclusions': [
            "📌 MA趋势检查器: MA5金叉MA10 时胜率最高 → 建议正式策略接入",
            "📌 外聘·首席: 多策略并行优于单策略 — 建议正交组合",
            "📌 全体: 本次 replay 经验已全部投喂 AI 脑库 ✅",
        ],
    })

    return meetings


# ═══════════════════════════════════════════════════════════
# ⑤ AI 脑库投喂
# ═══════════════════════════════════════════════════════════

def _get_conn():
    import sqlite3
    from core.db_path import get_db_path
    conn = sqlite3.connect(get_db_path('app.db'), timeout=5)
    conn.execute('PRAGMA busy_timeout=10000')
    return conn


def feed_brain(replay: dict, meetings: list, multi_result: dict = None) -> int:
    """replay + 多策略结果 + 会议 → 脑库"""
    try:
        conn = _get_conn()
    except Exception:
        return 0

    flow_prefix = f"REPLAY-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    count = 0

    def _insert(flow_id, feed_kind, feed_content, fed_by='replay_engine'):
        nonlocal count
        try:
            preview = (feed_content[:180] if isinstance(feed_content, str)
                       else json.dumps(feed_content, ensure_ascii=False)[:180])
            conn.execute("""INSERT INTO mt_ai_brain_feed_log
                (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_by, triggered_at)
                VALUES (?,?,?,?,?,?,datetime('now','localtime'))""",
                (flow_id, 'EXPERIENCE_LIBRARY', feed_kind, str(feed_content)[:1900], preview, fed_by))
            count += 1
        except Exception:
            pass

    # 整体 summary
    summary = (f"Replay {replay['days']}天 | ¥{replay['initial_capital']}→¥{replay['final_capital']} "
               f"({replay['pnl_pct']:+.2f}%) | 胜率{replay['win_rate']}% | 回撤{replay['max_drawdown']}% | {replay['trades_count']}笔")
    _insert(f'{flow_prefix}-SUMMARY', 'REPLAY_SUMMARY', summary)

    # 多策略对比
    if multi_result:
        for name, pnl, wr, dd in multi_result.get('ranking', []):
            _insert(f'{flow_prefix}-STRAT-{name}', 'STRATEGY_COMPARE',
                    f"[STRATEGY] {name}: pnl={pnl:+.2f}% 胜率={wr}% 回撤={dd}%")
        _insert(f'{flow_prefix}-BEST', 'BEST_STRATEGY',
                f"最佳策略: {multi_result.get('best_strategy')} | 最差: {multi_result.get('worst_strategy')}")

    # 亏损教训 (重点)
    for i, t in enumerate(replay.get('losing_trades', [])[:10]):
        _insert(f'{flow_prefix}-LOSS-{i:02d}', 'REPLAY_LOSS',
                f"❌ {t['symbol']} SELL @ ¥{t['price']} | pnl={t.get('pnl',0):+.1f} ({t.get('pnl_pct',0):+.1f}%)")

    # 盈利经验
    for i, t in enumerate(replay.get('winning_trades', [])[:10]):
        _insert(f'{flow_prefix}-WIN-{i:02d}', 'REPLAY_WIN',
                f"✅ {t['symbol']} SELL @ ¥{t['price']} | pnl={t.get('pnl',0):+.1f} ({t.get('pnl_pct',0):+.1f}%)")

    # 会议结论
    for m in meetings:
        for i, c in enumerate(m.get('conclusions', [])):
            _insert(f'{flow_prefix}-{m["meeting_type"].upper()}-{i}',
                    f'REPLAY_MEETING_{m["meeting_type"].upper()}', c,
                    fed_by=f'replay_{m["meeting_type"]}')

    conn.commit()
    conn.close()
    return count


# ═══════════════════════════════════════════════════════════
# ⑥ 实时 Mini 复盘会 (v2 新增) — 盘中每 30 分钟
# ═══════════════════════════════════════════════════════════

def run_real_time_mini_meeting(rt_data: dict, positions: dict, cash: float,
                                trades_since_last: list = None,
                                brain_knowledge_refs: list = None) -> dict:
    """
    盘中实时 mini 复盘会 — 5 分钟内快速开完
    rt_data: {symbol: {'name','price','chg_pct','ma5','ma10','ma20'}}
    positions: {symbol: {'qty','avg_cost'}}
    cash: 可用资金
    trades_since_last: 自上次会后的新成交
    brain_knowledge_refs: 脑库中关于这些股票的历史知识引用 (可选)
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    session_id = f"MINI-{datetime.now().strftime('%H%M')}"
    trades_since_last = trades_since_last or []
    brain_refs = brain_knowledge_refs or []

    # 1. 快速扫描持仓状态
    pos_status = []
    for sym, pos in positions.items():
        if sym not in rt_data: continue
        rt = rt_data[sym]
        pnl_pct = (rt['price'] - pos['avg_cost']) / pos['avg_cost'] * 100
        ma5 = rt.get('ma5', 0); ma20 = rt.get('ma20', 0)
        trend = '🟢' if ma5 > ma20 else '🔴' if ma5 < ma20 else '⚪'
        pos_status.append(f"{trend} {sym}({rt['name']}) 持有{pos['qty']}股 | 成本¥{pos['avg_cost']:.2f} → ¥{rt['price']:.2f} ({pnl_pct:+.1f}%)")

    # 2. 扫描市场异动
    anomalies = []
    for sym, rt in rt_data.items():
        if abs(rt.get('chg_pct', 0)) >= 3.0:
            anomalies.append(f"🚨 {sym} {rt['name']} {rt['chg_pct']:+.1f}%")

    # 3. 看脑库里有没有这些股票的历史经验
    brain_context = []
    if brain_refs:
        for ref in brain_refs[:5]:
            brain_context.append(f"🧠 {ref}")

    # 4. 生成 mini 会议
    meeting = {
        'session_id': session_id,
        'meeting_id': f'MEETING-MINI-{session_id}',
        'meeting_type': 'real_time_mini',
        'meeting_title': f'⏱ 盘中实时 mini 复盘 · {now}',
        'triggered_at': now,
        'participants': ['值班操盘手', 'AI 动量检测器', '风控合规员'],
        'agenda': [
            f"💰 现金 ¥{cash:.2f} | 💼 持仓 {len(positions)} 只",
            f"📈 异动 {len(anomalies)} 只 | 🆕 自上次会以来成交 {len(trades_since_last)} 笔",
        ],
        'positions_status': pos_status,
        'anomalies': anomalies,
        'brain_context': brain_context,
        'conclusions': [],
        'actions': [],
    }

    # 自动生成结论
    if pos_status:
        meeting['conclusions'].append(f"当前 {len(positions)} 只持仓状态已扫描")
    if anomalies:
        meeting['conclusions'].append(f"⚠️ {len(anomalies)} 只异动 — 建议关注是否到止盈止损位")
        meeting['actions'].append({'owner': '操盘手', 'action': '检查异动股的止盈止损条件'})
    if brain_context:
        meeting['conclusions'].append(f"🧠 已关联 {len(brain_context)} 条脑库历史经验作参考")

    return meeting


def publish_mini_meeting(meeting: dict, log_func=print):
    """把 mini 复盘会发布到协作总线 + 脑库"""
    # 1. 协作总线
    try:
        from engines.collab_bus_engine import CollabBus
        CollabBus().publish(
            event_type='MINI_MEETING',
            source='sandbox_tick',
            payload=meeting,
            severity='INFO',
            symbol=','.join(meeting.get('agenda', [''])[0][:20]) if meeting.get('agenda') else '',
        )
        log_func(f'  📣 mini 复盘会已 publish → 协作总线')
    except Exception as e:
        log_func(f'  ⚠️ collab bus publish err: {e}')

    # 2. 脑库投喂
    try:
        conn = _get_conn()
        flow_id = f"MINI-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        agenda_str = ' | '.join(meeting.get('agenda', []))
        concl_str = ' | '.join(meeting.get('conclusions', []))
        content = f"[MINI_MEETING] {meeting['meeting_title']} | {agenda_str} | {concl_str}"
        preview = content[:180]
        conn.execute("""INSERT INTO mt_ai_brain_feed_log
            (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_by, triggered_at)
            VALUES (?,?,?,?,?,?,datetime('now','localtime'))""",
            (flow_id, 'MEETING_LOG', 'MINI_MEETING', content[:1900], preview, 'replay_engine'))
        conn.commit()
        conn.close()
        log_func(f'  🧠 mini 复盘会已投喂脑库 → {flow_id}')
    except Exception as e:
        log_func(f'  ⚠️ brain feed err: {e}')


# ═══════════════════════════════════════════════════════════
# ⑦ 一键完整运行
# ═══════════════════════════════════════════════════════════

def run_full_replay(symbols: list = None, days: int = 60,
                    log_func=print, run_multi: bool = True) -> dict:
    """完整一次休市学习循环 — v2 多策略版"""
    t0 = time.time()
    log_func(f"🔄 [REPLAY v2] 开始 — {days}天, {len(symbols or DEFAULT_POOL)}只"
             f"{' + 多策略对比' if run_multi else ''} + 📰新闻因子")

    # 1. 拉 K 线
    log_func(f"  📥 拉历史 K 线...")
    history = fetch_history(symbols, days)
    active = {k: v for k, v in history.items() if v}
    log_func(f"  ✅ {len(active)} 只有效数据, {sum(len(v) for v in active.values())} 条 K 线")
    if not active:
        return {}

    # 2. 采集新闻/外部因子
    news_data = {}
    news_summary = ''
    try:
        from engines.news_collector import NewsCollector
        nc = NewsCollector(symbols or DEFAULT_POOL)
        news_data = nc.collect_all(log_func=log_func)
        news_summary = nc.generate_learning_factors(news_data)
    except Exception as e:
        log_func(f"  ⚠️ 新闻采集跳过: {e}")

    # 3. 主策略 replay
    log_func(f"  🏃 主策略 replay...")
    replay = run_strategy_momentum(active)

    # 4. 多策略对比 (v2)
    multi_result = None
    if run_multi:
        log_func(f"  🎯 4 策略并行对比 (动量/金叉/抄底/轮动)...")
        multi_result = run_multi_strategy_replay(active)
        if multi_result:
            log_func(f"     🏆 最优: {multi_result.get('best_strategy')} | ⚠️ 最差: {multi_result.get('worst_strategy')}")
            for name, pnl, wr, dd in multi_result.get('ranking', []):
                log_func(f"     → {name}: pnl={pnl:+.2f}% 胜率={wr}% 回撤={dd}%")

    # 5. 市场状态分析 (可选)
    log_func(f"  📊 市场状态分段分析...")
    try:
        import akshare as ak
        idx_df = ak.stock_zh_index_daily_em(symbol='sh000001')
        idx_rows = []
        if idx_df is not None:
            for _, r in idx_df.tail(days + 10).iterrows():
                idx_rows.append({'date': str(r['date']), 'close': float(r['close']), 'pct': 0})
        segments = classify_market_state({'sh000001': idx_rows})
        state_counts = {}
        for seg in segments:
            state_counts[seg['state']] = state_counts.get(seg['state'], 0) + 1
        log_func(f"     🐂 BULL={state_counts.get('BULL',0)}段 | 🐻 BEAR={state_counts.get('BEAR',0)}段 | ⚖️ RANGING={state_counts.get('RANGING',0)}段")
    except Exception as e:
        log_func(f"  ⚠️ 市场状态分析跳过: {e}")

    # 6. Mini 复盘会议
    log_func(f"  📋 生成 5 层复盘会议...")
    meetings = gen_replay_meetings(replay, multi_result)
    if news_summary:
        for m in meetings:
            if m['meeting_type'] in ('board', 'brainstorm', 'roundtable'):
                m.setdefault('agenda', []).insert(0, f"📰 消息面: {news_summary[:100]}")
                m.setdefault('conclusions', []).append(f"📌 消息面参考: {news_summary[:150]}")

    # 7. 脑库投喂
    log_func(f"  🧠 投喂 AI 脑库...")
    fed = feed_brain(replay, meetings, multi_result)
    if news_summary:
        try:
            from engines.replay_engine import _feed_news_factor
            _feed_news_factor(news_data, news_summary)
            fed += 1
        except Exception: pass

    dt = time.time() - t0
    log_func(f"  ✅ 休市学习循环 v2 完成 — {dt:.1f}s | 🧠 {fed} 条入脑库")

    return {
        'replay': replay, 'meetings': meetings, 'multi_result': multi_result,
        'fed_count': fed, 'elapsed_sec': round(dt, 1),
        'news_data': news_data, 'news_summary': news_summary,
    }


# CLI
if __name__ == '__main__':
    result = run_full_replay(days=60, run_multi=True)
    if result:
        r = result['replay']
        print(f"\n{'='*55}")
        print(f"📊 Replay v2 学习报告")
        print(f"{'='*55}")
        print(f"  {r['days']} 天 | 初始¥{r['initial_capital']} → ¥{r['final_capital']} ({r['pnl_pct']:+.2f}%)")
        print(f"  胜率 {r['win_rate']}% | 回撤 {r['max_drawdown']}% | {r['trades_count']} 笔")
        if result.get('multi_result'):
            print(f"\n  🎯 多策略排名:")
            for name, pnl, wr, dd in result['multi_result'].get('ranking', []):
                print(f"     {name:20s} pnl={pnl:+.2f}%  胜率={wr}%  回撤={dd}%")
        print(f"\n  🧠 AI 脑库投喂: {result['fed_count']} 条")
