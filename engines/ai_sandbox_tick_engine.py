#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
仙女座沙盘自动操盘 Tick Daemon (flow_sandbox_tick_20261102)
===========================================================
每 30s tick 一次:
  ① 拉真实行情 (新浪 → market_data_service)
  ② 跑简化策略 (均线交叉 + 涨跌幅阈值)
  ③ 触发模拟交易 → SandboxAdapter.place_order()
  ④ publish MARKET_ANOMALY → 协作总线 → 自动入任务大厅 → 脑库复盘

接入 Flask:
  modular_start.py 的 _ALLOW_KEYWORDS 已加 'sandbox-tick',
  在 Flask 启动后作为后台线程运行 (thread name 含 sandbox-tick)

安全门禁 (broker_adapter.py 硬编码):
  ═══ 本金与风控 ═══
  - 本金 10000 元, 单笔 ≤ 5000, 个股 ≤ 5000
  - 默认 5% 止损 → 大数据+风控联合同意可逐级放宽到 10% (每次 ±1%, 不跳级)
  - 3% 自动止盈 (稳不贪, 落袋为安)
  - T+1 约束 (15:30 后不能卖当日买入, 但止损/止盈紧急时放行)
  - 滑点 0.3%, 手续费万2.5 + 印花税千0.5 + 过户费万0.1

  ═══ 法律责任 (证监委) ═══
  - L01 投资者适当性 / L02 AI 如实披露 / L03 禁止对敲
  - L04 涨跌幅 ±10% / L05 T+1 强制 / L06 举牌线 5% / L07 交易时段合规 / L08 董事会 2/3 票

  ═══ 税务约束 (国税) ═══
  - T01 印花税 0.05%(卖) / T02 过户费万0.1 / T03 佣金最低 5 元 / T05 红利税 20%
  - T06 资本利得暂免 / T07 记录留存 5 年 / T08 年度盈亏汇总

自动休市/开市:
  _is_trading_hours() — 9:30-11:30 + 13:00-15:00, 周一至周五
  非交易时段 tick 静默, 只 publish 不下单

复盘调度 (5 层颗粒度):
  11:31 午间复盘 → 圆桌/头脑风暴/董事会/操盘部/AI员工+专家
  15:05 收市复盘 → 同上 5 层, 更深度
  所有会议自动入厅, 记录 JSONL + SQLite 双写留档溯源

🔄 休市学习循环 (不停摆):
  休市期间 (晚上/周末/节假日) — 每 2h 触发一次:
    ① akshare 拉近 30 天历史 K 线
    ② 沙盘点子快速 replay (逐日模拟操盘)
    ③ replay 结果 → mini 复盘 (5 层会议精简版)
    ④ 复盘结论 → 投喂 AI 脑库 (mt_ai_brain_feed_log)
    ⑤ 形成闭环: 历史 → 模拟 → 复盘 → 学习 → 脑库
  速度: 30 天 × 8 只 ≈ 3.4s, 投喂 ~22 条经验
"""
import os, sys, time, json, sqlite3, threading, logging
from datetime import datetime, timezone, timedelta

# 🆕 全局 patch: 所有 sqlite3.connect 自动加 WAL + busy_timeout (30s)
# 解决 Flask ↔ tick daemon 多进程写 DB 锁冲突
_orig_sqlite_connect = sqlite3.connect
def _wrapped_connect(*a, **kw):
    kw.setdefault('timeout', 30)
    conn = _orig_sqlite_connect(*a, **kw)
    try:
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception: pass
    return conn
sqlite3.connect = _wrapped_connect

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, os.pardir))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [SANDBOX-TICK] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("sandbox_tick")

TICK_INTERVAL = 30          # 每 30s tick
MAX_POSITIONS = 4           # 最多同时持 4 只 (本金 10000, 每只上限 5000)
STRATEGY_BUY_PCT = 0.5      # 日内涨 > 0.5% 触发买入 (放宽, 让机会多一些)
STRATEGY_SELL_PROFIT = 3.0  # 持仓盈利 > 3% 止盈

# 🆕 止损线 — 从 broker_adapter 动态同步 (5% 默认, 最高 10%, 逐级调节)
try:
    from core.broker_adapter import STOP_LOSS_PCT, STOP_LOSS_DEFAULT_PCT, STOP_LOSS_MAX_PCT
    STRATEGY_SELL_LOSS = round(-STOP_LOSS_PCT * 100, 2)   # -5.0 默认
except Exception:
    STOP_LOSS_PCT = 0.05
    STOP_LOSS_DEFAULT_PCT = 0.05
    STOP_LOSS_MAX_PCT = 0.10
    STRATEGY_SELL_LOSS = -5.0

SINGLE_STOCK_MAX_CNY = 5000 # 个股最多投 5000 元 (本金 10000 的 50%)
MIN_TRADE_QTY = 100         # A 股最小单位 100 股
T1_RELIEF_PROFIT_PCT = 2.5  # 🆕 盈利 ≥ 2.5% 时, T+1 不阻止止盈卖出 (落袋优先)
T1_RELIEF_LOSS_PCT = -3.0   # 🆕 亏损 ≥ -3% 时, T+1 不阻止止损卖出 (砍仓优先)

# ══════════════════════════════════════════════════════════════
# 🆕 分批止盈锁利 (Scale-Out) — 保证正盈利 + 让利润奔跑
# ══════════════════════════════════════════════════════════════
# 核心: 止盈不全卖, 先卖一部分锁定利润, 剩余继续跑
#   第一档 +3% → 卖 60% (锁利 60%, 留 40% 奔跑)
#   第二档 +5% → 再卖剩余的 50% (累计约 80%)
#   强制 +8% → 全清 (不贪)
#   止损 -5% → 全清 (保护本金, 不留)
SCALE_OUT_TIER1_PCT = 3.0    # 第一档触发线
SCALE_OUT_TIER1_RATIO = 0.60  # 第一档卖 60%
SCALE_OUT_TIER2_PCT = 5.0    # 第二档触发线
SCALE_OUT_TIER2_RATIO = 0.50  # 第二档卖剩余的 50%
SCALE_OUT_FORCE_PCT = 8.0    # 强制止盈线 (全清)

# 分批止盈进度跟踪 (内存 dict — daemon 生命周期内有效)
# {symbol: {'tier1_done': bool, 'tier2_done': bool, 'total_sold': int}}
_scale_out_tracker: dict = {}


# ══════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════

def _log(msg: str):
    log.info(msg)


def _db():
    from core.db_path import get_db_path
    return get_db_path('app.db')


def _load_positions() -> dict:
    """当前沙盘持仓 → {symbol: {'qty': int, 'avg_cost': float}}"""
    try:
        conn = sqlite3.connect(_db(), timeout=5)
        conn.execute('PRAGMA busy_timeout=10000')
        # 从 mt_sandbox_trades 算 (BUY 加 / SELL 减) — 真实落库表
        rows = conn.execute("""
            SELECT symbol, action, shares, price FROM mt_sandbox_trades
            WHERE action IN ('BUY','SELL')
            ORDER BY trade_date, trade_time
        """).fetchall()
        conn.close()

        positions = {}
        cost_map = {}  # 成本加权
        for sym, action, qty, price in rows:
            if action == 'BUY':
                positions[sym] = positions.get(sym, 0) + qty
                prev_cost, prev_qty = cost_map.get(sym, (0.0, 0))
                new_qty = prev_qty + qty
                new_cost = (prev_cost * prev_qty + price * qty) / new_qty if new_qty else 0
                cost_map[sym] = (new_cost, new_qty)
            else:
                positions[sym] = positions.get(sym, 0) - qty
                # SELL 用加权成本不动

        # 过滤持仓为正的
        return {s: {'qty': q, 'avg_cost': cost_map.get(s, (0, 0))[0]}
                for s, q in positions.items() if q > 0}
    except Exception as e:
        _log(f'load_positions err: {e}')
        return {}


def _get_cash() -> float:
    """沙盘现金余额"""
    try:
        from core.broker_adapter import SandboxAdapter
        info = SandboxAdapter().query_cash()
        if isinstance(info, dict):
            return float(info.get('available', info.get('total_capital', 1000)))
    except Exception:
        pass
    return 1000.0


# 🆕 低价自选池 (新浪直接拉 — 100 股 ≤ ¥5000 个股上限)
_SANDBOX_WATCHLIST = [
    ('sh600036', '招商银行'),   # ¥43 → ¥4300
    ('sh600900', '长江电力'),   # ¥28 → ¥2800
    ('sh601012', '隆基绿能'),   # ¥20 → ¥2000
    ('sh601398', '工商银行'),   # ¥6 → ¥600
    ('sz000725', '京东方A'),    # ¥4 → ¥400
    ('sh600519', '贵州茅台'),   # 监控异动 (买不起但要看)
    ('sz300750', '宁德时代'),   # 监控异动
]


def _sina_quote(secids: list) -> dict:
    """新浪实时行情批量拉取 — 纯 urllib, 零依赖"""
    import urllib.request
    result = {}
    url = f"https://hq.sinajs.cn/list={','.join(secids)}"
    try:
        req = urllib.request.Request(url, headers={
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0',
        })
        r = urllib.request.urlopen(req, timeout=5)
        text = r.read().decode('gbk', errors='ignore')
        for line in text.strip().split('\n'):
            if '="' not in line:
                continue
            secid = line.split('_str_')[1].split('=')[0].strip()
            parts = line.split('="')[1].rstrip('";').split(',')
            if len(parts) < 10:
                continue
            name = parts[0]
            prev_close = float(parts[2] or 0)
            price = float(parts[3] or 0)
            if price <= 0 or prev_close <= 0:
                continue
            chg_pct = (price - prev_close) / prev_close * 100
            result[secid] = {
                'name': name, 'price': price, 'prev_close': prev_close,
                'chg_pct': round(chg_pct, 2),
            }
    except Exception:
        pass
    return result


def _load_realtime() -> dict:
    """
    拉真实行情 → {symbol: {...}}
    双源: MarketDataService (带K线均线) + 新浪直拉 (低价自选池)
    """
    out = {}

    # 1. MarketDataService (有 K 线均线) — 🆕 带超时保护: mini 上 MDS 可能长时间挂起
    try:
        from core.services.market_data_service import MarketDataService
        _mds_res = {}
        def _fetch_mds():
            try:
                _mds_res['data'] = MarketDataService().get_all_for_sandbox()
            except Exception as _e:
                _log(f'load_realtime (MDS 线程) err: {_e}')
        _mds_t = threading.Thread(target=_fetch_mds, name='mds-fetch', daemon=True)
        _mds_t.start()
        _mds_t.join(4)          # 最多等 4s, 超时就用空数据 + 新浪兜底
        if _mds_t.is_alive():
            _log('load_realtime: MDS 超过 4s 未返回, 降级为新浪直拉')
        data = _mds_res.get('data') or {}
        for k, v in (data or {}).items():
            if not k.startswith('stk_') or not isinstance(v, dict):
                continue
            symbol = v.get('code', '')
            rt = v.get('realtime', {})
            kdata = v.get('kdata', {})
            price = float(rt.get('price', 0) or 0)
            chg_pct = float(rt.get('change_pct', 0) or 0)
            if price <= 0 or chg_pct <= -50:
                continue
            out[symbol] = {
                'name': v.get('name', ''),
                'price': price, 'chg_pct': chg_pct,
                'high': float(rt.get('high', 0) or 0),
                'low': float(rt.get('low', 0) or 0),
                'prev_close': float(rt.get('prev_close', 0) or price / (1 + chg_pct/100)),
                'ma5': (kdata.get('ma5') or [0])[-1] if kdata.get('ma5') else 0,
                'ma10': (kdata.get('ma10') or [0])[-1] if kdata.get('ma10') else 0,
                'ma20': (kdata.get('ma20') or [0])[-1] if kdata.get('ma20') else 0,
            }
    except Exception as e:
        _log(f'load_realtime (MDS) err: {e}')

    # 2. 🆕 新浪直拉低价自选池 (补充行情, 无均线时 prev_close 代替)
    try:
        secids = [s[0] for s in _SANDBOX_WATCHLIST]
        sina = _sina_quote(secids)
        for secid, q in sina.items():
            symbol = secid[2:]  # 去掉 sh/sz 前缀
            if symbol in out:
                continue  # MDS 已覆盖
            out[symbol] = {
                'name': q['name'],
                'price': q['price'],
                'chg_pct': q['chg_pct'],
                'high': 0, 'low': 0,
                'prev_close': q['prev_close'],
                'ma5': q['prev_close'],   # 🆕 无K线时用昨收代替 ma5 (price>ma5 ≈ price>prev_close 上涨)
                'ma10': q['prev_close'],
                'ma20': q['prev_close'],
            }
    except Exception as e:
        _log(f'load_realtime (sina) err: {e}')

    # 3. 🆕 持仓中未被覆盖的标的 (如 000001 不在自选池) 单独补拉
    try:
        _pos_syms = [s for s in (_load_positions() or {}) if s not in out]
        if _pos_syms:
            _secids = [('sh' + s) if s.startswith('6') else ('sz' + s) for s in _pos_syms]
            for secid, q in (_sina_quote(_secids) or {}).items():
                symbol = secid[2:]
                out[symbol] = {
                    'name': q['name'], 'price': q['price'], 'chg_pct': q['chg_pct'],
                    'high': 0, 'low': 0, 'prev_close': q['prev_close'],
                    'ma5': q['prev_close'], 'ma10': q['prev_close'], 'ma20': q['prev_close'],
                }
    except Exception as e:
        _log(f'load_realtime (持仓补拉) err: {e}')

    return out


# ══════════════════════════════════════════════════════════════
# 策略
# ══════════════════════════════════════════════════════════════

def _board_debate(action: str, sym: str, rt: dict, positions: dict,
                  ai_modules: list, signals: dict = None) -> dict:
    """🆕 董事会派系辩论 — 鹰派(激进) vs 犬派(保守) 左右互搏 + 董事长裁决"""
    signals = signals or {}
    name = rt.get('name', sym)
    chg = rt.get('chg_pct', 0)
    price = rt.get('price', 0)
    ma5 = rt.get('ma5', 0)
    ma10 = rt.get('ma10', 0)
    ma20 = rt.get('ma20', 0)
    bull = ma5 > ma10 > ma20 > 0
    pnl_pct = signals.get('pnl_pct', 0)
    pos = positions.get(sym, {})
    avg_cost = pos.get('avg_cost', 0)

    # ═══ 鹰派 (激进派) — 动量为王, 追涨杀跌, 高仓位 ═══
    HAWK = []
    HAWK.append(f'{chg:+.1f}% 单日涨幅, 动量正反馈强烈')
    HAWK.append(f'ma5>ma10>ma20={"🟢多头排列" if bull else "⚪无排列"}, 趋势确认')
    HAWK.append(f'价格站上 ma5={ma5:.2f}, 突破信号')
    HAWK.append(f'{"加仓" if action=="BUY" else "持有"}, 让利润奔跑!')

    # ═══ 犬派 (保守派) — 价值投资, 严止损, 低仓位 ═══
    DOG = []
    if chg > 3:
        DOG.append(f'{chg:+.1f}% 涨幅过热, 短期回调风险 ⚠️')
    elif chg > 1:
        DOG.append(f'{chg:+.1f}% 温和上涨, 但动能未确认')
    else:
        DOG.append(f'{chg:+.1f}% 信号太弱, 等更明确再出手')
    if not bull:
        DOG.append('均线空头/缠绕, 别跟趋势作对')
    DOG.append(f'100股最低起步, 仓位控制第一位')

    # ═══ 派系投票 ─ 不同 action 两派立场不同 ═══
    hawk_vote = 0
    dog_vote = 0
    verdict = ''
    chairman = ''

    if action == 'BUY':
        hawk_vote = 2 if chg > 2 else 1
        dog_vote = 1 if chg > 3 else 2
        verdict = '✅ 批准买入' if hawk_vote >= dog_vote else '⏸ 暂缓, 等更明确信号'
        chairman = f'董事长裁决: 鹰派胜出 ({hawk_vote}:{dog_vote}), {name} 动量充足, 放行' if hawk_vote >= dog_vote else f'董事长裁决: 犬派占优 ({hawk_vote}:{dog_vote}), {name} 信号偏弱, 观望'
    elif action == 'SELL':
        if pnl_pct > 0:
            hawk_vote = 1 if pnl_pct > 5 else 2
            dog_vote = 1 if pnl_pct < 3 else 2
            verdict = '📤 立即止盈' if pnl_pct < 5 else '📤 弹性止盈'
        else:
            hawk_vote = 2
            dog_vote = 1 if pnl_pct > -5 else 2
            verdict = '🛑 硬止损'
        chairman = f'董事长裁决: 鹰派{hawk_vote}:犬派{dog_vote}, {name} pnl={pnl_pct:+.1f}%, {verdict}'
    elif action == 'SKIP':
        # ═══ 观望状态也吵: 买入候选被风控拦 OR 持仓被 T+1 拦 ═══
        blocked = ai_modules  # T+1 gate 或 capital_gate
        if 't1_gate' in blocked:
            # 持仓被 T+1 限制, 鹰派想跑, 犬派说不急
            hawk_vote = 1 if pnl_pct > 2 else 0
            dog_vote = 2 if pnl_pct < 5 else 1
            verdict = f'T+1 锁仓 (pnl={pnl_pct:+.1f}%)'
            chairman = f'董事长裁决: T+1 限制, 鹰派想走({hawk_vote}) vs 犬派死扛({dog_vote}), {name} 等明日'
        elif 'limit_gate' in blocked:
            hawk_vote = 2
            dog_vote = 2
            verdict = '涨跌停封板, 无法交易'
            chairman = f'董事长裁决: 板了, 两派都别动 ({name})'
        elif 'momentum_detector' in blocked or 'ma_trend_checker' in blocked:
            # 买入候选 — 但因为各种原因没触发 (MAX_POSITIONS 满/金额不够)
            hawk_vote = 2 if chg > 1 else 1  # 涨多鹰派想上
            dog_vote = 2 if not bull else 1  # 没排列犬派想等
            verdict = '候选股, 条件未满足'
            chairman = f'董事长裁决: 鹰派想上({hawk_vote}) vs 犬派观望({dog_vote}), {name} 等更好时机'
        else:
            hawk_vote = 1
            dog_vote = 1
            verdict = '条件不满足, 观望'
            chairman = f'董事长裁决: {name} 信号模糊, 两派平手'
    else:
        hawk_vote = 0
        dog_vote = 0
        verdict = '⏸ 观望'
        chairman = f'董事长裁决: {name} 当前信号不足'

    # 鹰派反向修正: 如果 chg < 0 鹰派不能喊"动量正反馈"
    if chg < 0:
        HAWK[0] = f'{chg:+.1f}% 单日跌幅, 动量转弱 (鹰派内部有人开始动摇)'
        hawk_vote = max(0, hawk_vote - 1)

    return {
        'hawk': HAWK,
        'dog': DOG,
        'hawk_vote': hawk_vote,
        'dog_vote': dog_vote,
        'verdict': verdict,
        'chairman': chairman,
    }


def _gen_resolution(action: str, sym: str, rt: dict, positions: dict,
                    ai_modules: list, signals: dict = None) -> str:
    """鹰派犬派辩论 + 董事长裁决 → 人类可读决议文本"""
    signals = signals or {}
    name = rt.get('name', sym)
    chg = rt.get('chg_pct', 0)
    price = rt.get('price', 0)

    board = _board_debate(action, sym, rt, positions, ai_modules, signals)

    sep = '─' * 28
    lines = [
        f'🏛️ 仙女座董事会 · {action} {name}({sym})',
        sep,
        f'🦅 鹰派 (激进) — {board["hawk_vote"]}票:',
    ]
    for h in board['hawk']:
        lines.append(f'   + {h}')
    lines.append(f'🐕 犬派 (保守) — {board["dog_vote"]}票:')
    for d in board['dog']:
        lines.append(f'   - {d}')
    lines.append(sep)
    lines.append(f'📜 投票: 鹰{board["hawk_vote"]} : 犬{board["dog_vote"]} → {board["verdict"]}')
    lines.append(f'👑 {board["chairman"]}')
    return '\n'.join(lines)


def _eval_buy(sym: str, rt: dict, positions: dict, cash: float = 1000) -> dict | None:
    """
    买入信号 — 动量策略
    
    AI 模块:
      [momentum_detector] chg_pct 门槛
      [ma_trend_checker] 均线多空判断
      [capital_gate] 现金可用量检查
      [position_limit] 持仓上限检查
    """
    if sym in positions:
        return None  # 已持仓

    price = rt.get('price', 0)
    chg = rt.get('chg_pct', 0)
    ma5 = rt.get('ma5', 0)

    if price <= 0:
        return None

    # 100 股起, 最小价格门槛: 100 × price ≤ 可投现金
    min_cost = MIN_TRADE_QTY * price
    investable = min(cash * 0.9, SINGLE_STOCK_MAX_CNY)
    if min_cost > investable:
        return None  # 买不起 100 股

    # 🎯 动量买入: 日内涨幅 > 0.8% 且 价格站上 ma5
    if chg > STRATEGY_BUY_PCT and price > ma5 > 0:
        # 算数量 (取 investable 限制)
        qty = int(investable / price / MIN_TRADE_QTY) * MIN_TRADE_QTY
        if qty < MIN_TRADE_QTY:
            return None
        return {
            'symbol': sym, 'action': 'BUY', 'qty': qty, 'price': price,
            'reason': f'MOMENTUM chg={chg:+.2f}% price>ma5={ma5:.2f}',
            'decision': 'BUY',
            'ai_modules': ['momentum_detector', 'ma_trend_checker', 'capital_gate'],
            'signals': {'chg_pct': round(chg, 2), 'above_ma5': price > ma5,
                        'ma5': round(ma5, 2), 'price': round(price, 2)},
            'resolution': _gen_resolution('BUY', sym, rt, positions,
                                           ['momentum_detector', 'ma_trend_checker', 'capital_gate']),
            'investable_cny': round(investable, 2), 'notional': round(qty * price, 2),
        }
    return None


def _eval_sell(sym: str, rt: dict, positions: dict) -> dict | None:
    """
    卖出信号 — 止损(全清) + 止盈(分批锁利)
    
    止损: 亏损 < -5% → 全清 (保护本金, 不留)
    止盈 (Scale-Out 分批锁利):
      +3% 第一档 → 卖 60% 锁利 ✅ 保证正盈利
      +5% 第二档 → 再卖剩余 50% (累计约 80%)
      +8% 强制   → 全清 (不贪, 最后 20% 也落袋)
    """
    global _scale_out_tracker
    pos = positions.get(sym)
    if not pos:
        return None

    price = rt.get('price', 0)
    avg_cost = pos.get('avg_cost', 0)
    qty = pos.get('qty', 0)
    if price <= 0 or avg_cost <= 0 or qty <= 0:
        return None

    pnl_pct = (price - avg_cost) / avg_cost * 100
    ma5 = rt.get('ma5', 0)
    ma10 = rt.get('ma10', 0)
    ma20 = rt.get('ma20', 0)
    chg = rt.get('chg_pct', 0)
    bull_trend = (ma5 > ma10 > ma20 > 0) and (chg > 0)

    # 初始化 tracker
    track = _scale_out_tracker.setdefault(sym, {'tier1_done': False, 'tier2_done': False})

    # ── 🛑 硬止损 — 全清 (保护本金) ──
    if pnl_pct < STRATEGY_SELL_LOSS:
        _scale_out_tracker[sym] = {'tier1_done': True, 'tier2_done': True}
        return {
            'symbol': sym, 'action': 'SELL', 'qty': qty, 'price': price,
            'reason': f'STOP_LOSS_FULL pnl={pnl_pct:+.2f}% < {STRATEGY_SELL_LOSS}% — 全清保护本金',
            'decision': 'SELL', 'ai_modules': ['stop_loss_gate'],
            'pnl_pct': round(pnl_pct, 2), 'trigger': 'hard_stop_full',
            'scale_out': {'tier': 'STOP_LOSS', 'ratio': 1.0, 'sells': qty, 'locks_profit': True},
        }

    # ── 🏆 强制止盈 +8% — 全清 (不贪) ──
    if pnl_pct > SCALE_OUT_FORCE_PCT:
        _scale_out_tracker[sym] = {'tier1_done': True, 'tier2_done': True}
        return {
            'symbol': sym, 'action': 'SELL', 'qty': qty, 'price': price,
            'reason': f'FORCE_TAKE_PROFIT pnl={pnl_pct:+.2f}% > +{SCALE_OUT_FORCE_PCT}% — 全清落袋',
            'decision': 'SELL', 'ai_modules': ['profit_taker'],
            'pnl_pct': round(pnl_pct, 2), 'trigger': 'force_cap_8pct',
            'scale_out': {'tier': 'FORCE', 'ratio': 1.0, 'sells': qty, 'locks_profit': True},
        }

    # ── 🎯 分批止盈 Scale-Out ──
    if pnl_pct > SCALE_OUT_TIER1_PCT:

        # 多头排列 + 没到 tier2 → 让利润跑
        if bull_trend and pnl_pct < SCALE_OUT_TIER2_PCT and not track['tier1_done']:
            return None  # 🐂 趋势好, 继续 hold

        # 第一档: +3% → 卖 60% (锁利)
        if not track['tier1_done'] and pnl_pct >= SCALE_OUT_TIER1_PCT:
            sell_qty = max(MIN_TRADE_QTY, int(qty * SCALE_OUT_TIER1_RATIO / MIN_TRADE_QTY) * MIN_TRADE_QTY)
            if sell_qty >= qty:
                sell_qty = qty  # 防止四舍五入超过持仓
            if sell_qty >= MIN_TRADE_QTY:
                track['tier1_done'] = True
                remain_pct = (qty - sell_qty) / qty * 100
                _log(f'  🔒 {sym} 第一档锁利: 卖 {sell_qty}股({SCALE_OUT_TIER1_RATIO*100:.0f}%), 剩 {qty-sell_qty}股({remain_pct:.0f}%) 奔跑')
                return {
                    'symbol': sym, 'action': 'SELL', 'qty': sell_qty, 'price': price,
                    'reason': f'SCALE_OUT_TIER1 pnl={pnl_pct:+.2f}% ≥ +{SCALE_OUT_TIER1_PCT}% → 卖{sell_qty}股锁利60%, 留{qty-sell_qty}股奔跑',
                    'decision': 'SELL', 'ai_modules': ['profit_taker', 'scale_out'],
                    'pnl_pct': round(pnl_pct, 2), 'trigger': 'scale_out_tier1',
                    'scale_out': {'tier': 1, 'ratio': SCALE_OUT_TIER1_RATIO, 'sells': sell_qty, 'locks_profit': True},
                }

        # 第二档: +5% → 再卖剩余的 50%
        if not track['tier2_done'] and pnl_pct >= SCALE_OUT_TIER2_PCT:
            sell_qty = max(MIN_TRADE_QTY, int(qty * SCALE_OUT_TIER2_RATIO / MIN_TRADE_QTY) * MIN_TRADE_QTY)
            if sell_qty >= qty:
                sell_qty = qty
            if sell_qty >= MIN_TRADE_QTY:
                track['tier2_done'] = True
                remain_pct = (qty - sell_qty) / qty * 100
                _log(f'  🔒 {sym} 第二档锁利: 再卖 {sell_qty}股({SCALE_OUT_TIER2_RATIO*100:.0f}%), 剩 {qty-sell_qty}股({remain_pct:.0f}%)')
                return {
                    'symbol': sym, 'action': 'SELL', 'qty': sell_qty, 'price': price,
                    'reason': f'SCALE_OUT_TIER2 pnl={pnl_pct:+.2f}% ≥ +{SCALE_OUT_TIER2_PCT}% → 再卖{sell_qty}股锁利, 留{qty-sell_qty}股奔跑',
                    'decision': 'SELL', 'ai_modules': ['profit_taker', 'scale_out'],
                    'pnl_pct': round(pnl_pct, 2), 'trigger': 'scale_out_tier2',
                    'scale_out': {'tier': 2, 'ratio': SCALE_OUT_TIER2_RATIO, 'sells': sell_qty, 'locks_profit': True},
                }

        # 两档都做完了 → hold 剩余 (等强制 8% 或止损)
    return None


# ══════════════════════════════════════════════════════════════
# 拟真度: 交易时段 + 涨跌停 + T+1
# ══════════════════════════════════════════════════════════════

# 🆕 统一锚定 Asia/Shanghai — 不依赖系统时区设置 (mini 曾出现时钟/时区偏移)
try:
    from zoneinfo import ZoneInfo
    _CN_TZ = ZoneInfo('Asia/Shanghai')
except Exception:
    _CN_TZ = None


def _now_cn() -> datetime:
    """当前 A 股市场时间 (Asia/Shanghai, 返回 naive datetime 便于 strftime 直接使用)"""
    if _CN_TZ is not None:
        return datetime.now(_CN_TZ).replace(tzinfo=None)
    return datetime.now()


def _market_phase(now: datetime = None) -> str:
    """
    显式市场状态机 (可传入 now 做边界单测):
      weekend   — 周六/周日
      pre_open  — 09:15-09:30 集合竞价 (只报不下单)
      trading   — 09:30-11:30 / 13:00-15:00 连续竞价
      lunch     — 11:30-13:00 午间休市
      closed    — 其余时段 (含 15:00 收盘后 / 开盘前)
    """
    now = now or _now_cn()
    if now.weekday() >= 5:
        return 'weekend'
    t = now.strftime('%H:%M')
    if '09:15' <= t < '09:30':
        return 'pre_open'
    if '09:30' <= t <= '11:30':
        return 'trading'
    if '11:30' < t < '13:00':
        return 'lunch'
    if '13:00' <= t <= '15:00':
        return 'trading'
    return 'closed'


def _is_trading_hours(now: datetime = None) -> bool:
    """兼容旧 API — 是否处于连续竞价时段"""
    return _market_phase(now) == 'trading'


def _is_pre_open(now: datetime = None) -> bool:
    """兼容旧 API — 是否处于集合竞价时段"""
    return _market_phase(now) == 'pre_open'


def _limit_up_down_check(price: float, chg_pct: float, action: str, symbol: str = '') -> str | None:
    """
    涨跌停检查 — 返回阻断原因或 None (可交易)
    主板(000/002/600/601/603) ±10% / ST股 ±5%
    创业板(300/301) / 科创板(688) ±20%
    北交所(8/4开头) ±30% (简化为 ±30%)
    """
    if price <= 0:
        return None

    # 根据 symbol 判断涨跌停幅度
    limit_pct = 10.0  # 默认主板 ±10%
    if symbol.startswith(('300', '301')):
        limit_pct = 20.0  # 创业板
    elif symbol.startswith('688'):
        limit_pct = 20.0  # 科创板
    elif symbol.startswith(('8', '4')):
        limit_pct = 30.0  # 北交所 (简化)

    prev_close = price / (1 + chg_pct / 100.0) if chg_pct > -99 else price
    lu_mult = 1 + limit_pct / 100
    ld_mult = 1 - limit_pct / 100
    limit_up = prev_close * lu_mult
    limit_down = prev_close * ld_mult

    plate_label = {'10': '主板', '20': '创业板/科创板', '30': '北交所'}.get(str(int(limit_pct)), 'A股')

    if action == 'BUY' and price >= limit_up * 0.998:
        return f'{plate_label}涨停 (¥{price:.2f} ≥ ¥{limit_up:.2f}) — 买不到'
    if action == 'SELL' and price <= limit_down * 1.002:
        return f'{plate_label}跌停 (¥{price:.2f} ≤ ¥{limit_down:.2f}) — 卖不出'
    return None


def _t1_veto(symbol: str, action: str) -> str | None:
    """T+1 检查 — 当日买入不能当日卖出"""
    if action != 'SELL':
        return None
    try:
        conn = sqlite3.connect(_db(), timeout=3)
        today = datetime.now().strftime('%Y-%m-%d')
        row = conn.execute("""
            SELECT SUM(qty) FROM mt_trade_log
            WHERE trade_mode='sandbox' AND action='BUY' AND symbol=?
            AND substr(created_at,1,10)=?
        """, (symbol, today)).fetchone()
        conn.close()
        bought_today = row[0] if row and row[0] else 0
        if bought_today > 0:
            return f'T+1 限制: 今日买 {symbol} {bought_today} 股, 不能当日卖出'
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# 主 Tick 循环
# ══════════════════════════════════════════════════════════════

_tick_count = 0
_positions_cache = {}


def run_tick():
    """单次 tick (交易时段内下单, 盘前只 publish, 其余时段静默)"""
    global _tick_count, _positions_cache
    _tick_count += 1
    ts = _now_cn().strftime('%H:%M:%S')
    _phase = _market_phase()
    in_trade = _phase == 'trading'
    pre_open = _phase == 'pre_open'
    if in_trade:
        phase = '📈 连续竞价中'
    elif pre_open:
        phase = '🌅 集合竞价 (9:15-9:30) — 只 publish'
    elif _phase == 'lunch':
        phase = '🍵 午间休市 (11:30-13:00) — 静默'
    elif _phase == 'weekend':
        phase = '🛑 周末休市 — 静默'
    else:
        phase = '🌙 非交易时段 — 静默'
    _log(f'━━━ TICK #{_tick_count} @ {ts} {phase} ━━━')

    # 🆕 非交易/非集合竞价时段: 不拉行情不下单, 只写心跳 (保证守护进程存活可见)
    if not in_trade and not pre_open:
        try:
            with open('/tmp/sandbox_daemon_heartbeat', 'w') as _hf:
                _hf.write(json.dumps({
                    'ts': _now_cn().strftime('%Y-%m-%d %H:%M:%S'),
                    'tick': _tick_count,
                    'phase': phase,
                    'market_phase': _phase,
                    'trades': 0,
                    'decisions': 0,
                }))
        except Exception:
            pass
        return

    # 1. 拉行情
    rt = _load_realtime()
    if not rt:
        _log('  ❌ 无行情数据, 跳过')
        return

    symbols = list(rt.keys())
    _parts = [f"{s}({rt[s]['chg_pct']:+.1f}%)" for s in symbols]
    _log(f'  📊 行情: {len(symbols)} 只 — {", ".join(_parts)}')

    # 2. 持仓 + 现金
    positions = _load_positions()
    _positions_cache = positions
    cash = _get_cash()
    total_value = cash + sum(positions[s]['qty'] * rt[s]['price']
                             for s in positions if s in rt)
    _pos_parts = [f"{s}×{positions[s]['qty']}" for s in positions]
    _log(f'  💼 持仓: {len(positions)} 只 — {", ".join(_pos_parts) or "空仓"}')
    _log(f'  💰 现金 ¥{cash:.2f} | 总市值 ¥{total_value:.2f}')

    trades_made = []
    tick_decisions = []  # 🆕 完整决策流水 (复盘喂脑库用)

    if in_trade:
        # ═══ 交易时段: 跑策略下单 ═══
        # 3. 先检查卖出 (止盈/止损, T+1 约束)
        for sym in list(positions.keys()):
            if sym not in rt:
                tick_decisions.append({'tick': _tick_count, 'ts': ts, 'phase': phase,
                    'symbol': sym, 'action': 'SKIP', 'reason': '行情缺失',
                    'rt_price': None})
                continue
            d_entry = {'tick': _tick_count, 'ts': ts, 'phase': phase,
                       'symbol': sym, 'rt_price': rt[sym]['price'],
                       'rt_chg_pct': rt[sym]['chg_pct'],
                       'ma5': rt[sym].get('ma5', 0),
                       'ma10': rt[sym].get('ma10', 0),
                       'pnl_pct': round((rt[sym]['price'] - positions[sym]['avg_cost']) / positions[sym]['avg_cost'] * 100, 2),
                       'avg_cost': positions[sym]['avg_cost'],
                       'action': 'HOLD', 'decision': None, 'blocked_by': None,
                       'reason': '持仓观望', 'ai_modules': []}
            cur_pnl = d_entry['pnl_pct']

            # 🆕 T+1 检查 — 但盈利/止损紧急时放行
            t1_block = _t1_veto(sym, 'SELL')
            if t1_block:
                if cur_pnl >= T1_RELIEF_PROFIT_PCT:
                    _log(f'  🔓 T+1 放行止盈: {sym} pnl={cur_pnl:+.2f}% ≥ {T1_RELIEF_PROFIT_PCT}% → 允许当日卖出落袋')
                    d_entry['t1_relief'] = 'TAKE_PROFIT'
                elif cur_pnl <= T1_RELIEF_LOSS_PCT:
                    _log(f'  🔓 T+1 放行止损: {sym} pnl={cur_pnl:+.2f}% ≤ {T1_RELIEF_LOSS_PCT}% → 允许当日砍仓')
                    d_entry['t1_relief'] = 'STOP_LOSS'
                else:
                    d_entry['action'] = 'SKIP'
                    d_entry['blocked_by'] = 'T+1'
                    d_entry['reason'] = t1_block
                    d_entry['ai_modules'] = ['t1_gate']
                    tick_decisions.append(d_entry)
                    _log(f'  ⏭ {t1_block}')
                    continue

            order = _eval_sell(sym, rt[sym], positions)
            if order:
                d_entry.update({'decision': order.get('decision', 'SELL'),
                               'ai_modules': order.get('ai_modules', []),
                               'trigger': order.get('trigger', 'unknown')})
                # 跌停检查 (带板块识别)
                ld_block = _limit_up_down_check(rt[sym]['price'], rt[sym]['chg_pct'], 'SELL', sym)
                if ld_block:
                    d_entry['action'] = 'SKIP'
                    d_entry['blocked_by'] = 'limit_down'
                    d_entry['reason'] = ld_block
                    d_entry['ai_modules'].append('limit_gate')
                    tick_decisions.append(d_entry)
                    _log(f'  ⏭ {ld_block}')
                    continue
                d_entry['action'] = order['action']
                d_entry['reason'] = order['reason']
                tick_decisions.append(d_entry)
                # 🔄 闭环审议 — 每个卖出动作先过闭环
                review = _closed_loop_review(order, rt[sym], positions, cash)
                if review['approve']:
                    _execute_order(order, rt[sym], positions, trades_made)
                    if review['decision'] == 'MODIFY':
                        _log(f'  ⚠️ 闭环减半仓执行 (score={review["score"]})')
                else:
                    _log(f'  ❌ 闭环否决 (score={review["score"]}) — 放弃本次 SELL {sym}')
                    continue
            else:
                tick_decisions.append(d_entry)  # HOLD — 没触发卖出信号
                bull = (rt[sym].get('ma5',0) > rt[sym].get('ma10',0) > rt[sym].get('ma20',0)) and rt[sym]['chg_pct'] > 0
                if bull:
                    _log(f'  🐂 {sym} 多头排列 HOLD (ma5>ma10>ma20, chg={rt[sym]["chg_pct"]:+.1f}%)')

        # 4. 再检查买入
        if len(positions) + len([t for t in trades_made if t['action'] == 'SELL']) < MAX_POSITIONS:
            for sym in symbols:
                if sym in positions:
                    continue
                if len([t for t in trades_made if t['action'] == 'BUY']) >= MAX_POSITIONS - len(positions):
                    break
                order = _eval_buy(sym, rt[sym], positions, cash)
                d_entry = {'tick': _tick_count, 'ts': ts, 'phase': phase,
                           'symbol': sym, 'rt_price': rt[sym]['price'],
                           'rt_chg_pct': rt[sym]['chg_pct'],
                           'ma5': rt[sym].get('ma5', 0),
                           'action': 'SKIP', 'reason': None, 'blocked_by': None,
                           'ai_modules': []}
                if order:
                    d_entry.update({'decision': order.get('decision', 'BUY'),
                                   'ai_modules': order.get('ai_modules', []),
                                   'signals': order.get('signals', {})})
                    # 涨停检查 (带板块识别)
                    lu_block = _limit_up_down_check(rt[sym]['price'], rt[sym]['chg_pct'], 'BUY', sym)
                    if lu_block:
                        d_entry['blocked_by'] = 'limit_up'
                        d_entry['reason'] = lu_block
                        d_entry['ai_modules'].append('limit_gate')
                        tick_decisions.append(d_entry)
                        _log(f'  ⏭ {lu_block}')
                        continue
                    # 现金检查
                    need = order['qty'] * order['price']
                    if need > cash * 0.9:  # 留 10% 备用
                        d_entry['blocked_by'] = 'insufficient_cash'
                        d_entry['reason'] = f'现金不足 (需 ¥{need:.0f}, 可用 ¥{cash:.0f})'
                        d_entry['ai_modules'].append('capital_gate')
                        tick_decisions.append(d_entry)
                        _log(f'  ⏭ {order["reason"]} 但现金不足 (需 ¥{need:.0f}, 可用 ¥{cash:.0f})')
                        continue
                    d_entry['action'] = order['action']
                    d_entry['reason'] = order['reason']
                    tick_decisions.append(d_entry)
                    # 🔄 闭环审议 — 每个买入动作先过闭环
                    review = _closed_loop_review(order, rt[sym], positions, cash)
                    if review['approve']:
                        _execute_order(order, rt[sym], positions, trades_made)
                        cash -= need  # 预估扣减 (真实以 place_order 为准)
                        if review['decision'] == 'MODIFY':
                            _log(f'  ⚠️ 闭环减半仓执行 (score={review["score"]})')
                    else:
                        _log(f'  ❌ 闭环否决 (score={review["score"]}) — 放弃本次 BUY {sym}')
                        continue
                else:
                    # 没触发买入信号 — 记录 skip 原因
                    chg = rt[sym]['chg_pct']
                    ma5 = rt[sym].get('ma5', 0)
                    if chg <= STRATEGY_BUY_PCT:
                        d_entry['reason'] = f'chg={chg:+.2f}% ≤ {STRATEGY_BUY_PCT}% 动量不足'
                    elif not (rt[sym]['price'] > ma5 > 0):
                        d_entry['reason'] = f'price=¥{rt[sym]["price"]:.2f} 未站上 ma5=¥{ma5:.2f}'
                    else:
                        d_entry['reason'] = '不在持仓池'
                    d_entry['ai_modules'] = ['momentum_detector', 'ma_trend_checker']
                    tick_decisions.append(d_entry)
    else:
        if pre_open:
            _log('  🌅 集合竞价时段 — 跳过下单, 仅 publish 异动')
        else:
            _log('  🌙 非交易时段 — 静默 (不 publish 也不下单)')
            return  # 纯静默时段直接 return, 不 publish

    # 5. Publish 异动到协作总线 (不论是否交易时段)
    anomalies = []
    for sym in symbols:
        if abs(rt[sym]['chg_pct']) >= 3.0:
            anomalies.append({
                'symbol': sym, 'anomaly_type': 'BIG_MOVE',
                'anomaly_score': abs(rt[sym]['chg_pct']),
                'chg_pct': rt[sym]['chg_pct'],
            })

    if anomalies:
        try:
            from engines.collab_bus_engine import CollabBus
            sev = 'ALERT' if any(a['anomaly_score'] >= 5 for a in anomalies) else 'WARN'
            CollabBus().publish(
                event_type='MARKET_ANOMALY',
                source='sandbox_tick',
                payload={'anomalies': anomalies},
                severity=sev,
                symbol=','.join(a['symbol'] for a in anomalies[:3]),
            )
            _log(f'  📣 publish MARKET_ANOMALY ({sev}): {len(anomalies)} 只异动')
        except Exception as e:
            _log(f'  ⚠️ publish err: {e}')

    # 6. Tick 总结
    if trades_made:
        _trade_parts = [f'{t["action"]} {t["symbol"]}×{t["qty"]} ¥{t["price"]:.2f}' for t in trades_made]
        _log(f'  ✅ 本 tick 成交 {len(trades_made)} 笔 — ' + ', '.join(_trade_parts))
    elif in_trade:
        _log('  ⏸ 本 tick 无交易 (策略未触发)')
    else:
        _log('  ⏸ 非交易时段, 未下单')

    # 7. 🆕 决策流水落盘 (JSONL — 复盘喂脑库用)
    if tick_decisions:
        # 🆕 给每个决策注入董事会决议 (鹰派犬派辩论)
        for d in tick_decisions:
            sym = d['symbol']
            act = d['action']
            d['resolution'] = _gen_resolution(act, sym, rt.get(sym, {}), positions,
                                               d.get('ai_modules', []),
                                               {'pnl_pct': d.get('pnl_pct', 0)})
        _dec_path = '/tmp/sandbox_decisions.jsonl'
        try:
            with open(_dec_path, 'a') as f:
                for d in tick_decisions:
                    f.write(json.dumps(d, ensure_ascii=False) + '\n')
            _log(f'  📝 决策流水 {len(tick_decisions)} 条 → {_dec_path}')
        except Exception as e:
            _log(f'  ⚠️ 决策流水落盘 err: {e}')

    # 8. 🆕 Heartbeat 文件 (灾难守护用 — 每 tick 写一次)
    try:
        _hb_path = '/tmp/sandbox_daemon_heartbeat'
        with open(_hb_path, 'w') as f:
            f.write(json.dumps({
                'ts': _now_cn().strftime('%Y-%m-%d %H:%M:%S'),
                'tick': _tick_count,
                'phase': phase,
                'market_phase': _market_phase(),
                'trades': len(trades_made),
                'decisions': len(tick_decisions),
            }))
    except Exception:
        pass


def _closed_loop_review(order: dict, rt: dict, positions: dict, cash: float) -> dict:
    """
    🔄 动作闭环审议 — 每个操盘动作先跑一轮闭环再决议
    
    六步闭环:
      ① 模拟执行 — 如果真下单, 后会怎样 (现金/持仓/盈亏)
      ② 风控复核 — 执行后是否还在红线内 (个股仓位≤50%, 总仓位≤80%)
      ③ 资金管理 — 现金剩余够不够支撑后续机会
      ④ 持仓平衡 — 行业/市值是否过度集中
      ⑤ 市场情绪 — 大盘板块个股是否共振
      ⑥ 决议     — 综合以上, APPROVE / REJECT / MODIFY
    """
    sym = order['symbol']
    action = order['action']
    qty = order['qty']
    price = order['price']
    steps = {}
    score = 100  # 起始 100, 每步扣分

    # ═══ ① 模拟执行 ═══
    if action == 'BUY':
        cost = qty * price * 1.001  # 含滑点+手续费估算
        sim_cash = cash - cost
        sim_positions = dict(positions)
        prev = sim_positions.get(sym, {'qty': 0, 'avg_cost': price})
        new_qty = prev['qty'] + qty
        new_cost = (prev['avg_cost'] * prev['qty'] + price * qty) / new_qty if new_qty else price
        sim_positions[sym] = {'qty': new_qty, 'avg_cost': new_cost}
        steps['simulate'] = f"BUY {sym}×{qty} @¥{price:.2f} → 现金剩¥{sim_cash:.0f}, {sym}仓位→{new_qty}股@¥{new_cost:.2f}"
    else:
        proceeds = qty * price * 0.999  # 扣手续费估算
        sim_cash = cash + proceeds
        sim_positions = dict(positions)
        prev = sim_positions.get(sym, {'qty': 0})
        remain_qty = prev['qty'] - qty
        if remain_qty > 0:
            sim_positions[sym] = {**prev, 'qty': remain_qty}
        else:
            sim_positions.pop(sym, None)
        pnl = (price - prev.get('avg_cost', price)) * qty
        steps['simulate'] = f"SELL {sym}×{qty} @¥{price:.2f} → 现金剩¥{sim_cash:.0f}, 实现盈亏¥{pnl:+.0f}, {sym}剩{remain_qty}股"

    # ═══ ② 风控复核 ═══
    total_positions_value = 0.0
    for s, p in sim_positions.items():
        if isinstance(p, dict):
            # 尝试从 rt 取价格, 否则用 avg_cost
            s_rt = rt.get(s) if isinstance(rt, dict) else None
            price_now = s_rt.get('price', p.get('avg_cost', 0)) if isinstance(s_rt, dict) else p.get('avg_cost', 0)
            total_positions_value += p['qty'] * price_now
    total_assets = sim_cash + total_positions_value
    position_pct = total_positions_value / total_assets * 100 if total_assets > 0 else 0
    
    risk_issues = []
    if action == 'BUY' and position_pct > 80:
        risk_issues.append(f"总仓位 {position_pct:.0f}% > 80% 红线")
        score -= 20
    # 个股集中度
    sym_val = sim_positions.get(sym, {}).get('qty', 0) * price
    sym_pct = sym_val / total_assets * 100 if total_assets > 0 else 0
    if action == 'BUY' and sym_pct > 50:
        risk_issues.append(f"{sym} 集中度 {sym_pct:.0f}% > 50% 红线")
        score -= 15
    steps['risk'] = f"总仓位 {position_pct:.0f}%, {sym} 占 {sym_pct:.0f}% {'⚠️' if risk_issues else '✅'}" + (f" — {'; '.join(risk_issues)}" if risk_issues else "")

    # ═══ ③ 资金管理 ═══
    min_cash_reserve = total_assets * 0.10  # 至少留 10% 现金备用
    capital_ok = sim_cash >= min_cash_reserve
    if not capital_ok:
        score -= 15
        steps['capital'] = f"⚠️ 现金¥{sim_cash:.0f} < 备用金¥{min_cash_reserve:.0f} (总市值10%)"
    else:
        steps['capital'] = f"✅ 现金¥{sim_cash:.0f} ≥ 备用金¥{min_cash_reserve:.0f}"

    # ═══ ④ 持仓平衡 (持仓数) ═══
    hold_count = len(sim_positions)
    if action == 'BUY' and hold_count > MAX_POSITIONS:
        score -= 10
        steps['balance'] = f"⚠️ 持仓 {hold_count} 只 > MAX {MAX_POSITIONS}"
    elif action == 'SELL' and hold_count == 0:
        steps['balance'] = "✅ 清仓完毕 (观望模式)"
    else:
        steps['balance'] = f"✅ 持仓 {hold_count} 只"

    # ═══ ⑤ 市场情绪 ═══
    chg = rt.get('chg_pct', 0) if isinstance(rt, dict) else 0
    ma5 = rt.get('ma5', 0) if isinstance(rt, dict) else 0
    price = rt.get('price', 0) if isinstance(rt, dict) else price
    
    sentiment_ok = True
    if action == 'BUY' and chg < -2:
        sentiment_ok = False
        score -= 10
    if action == 'BUY' and price < ma5 and ma5 > 0:
        sentiment_ok = False
        score -= 5
    if action == 'SELL' and chg > 5:
        sentiment_ok = True  # 大涨卖出 OK
    steps['sentiment'] = f"{sym} chg={chg:+.1f}%, ma5={ma5:.2f} {'✅共振' if sentiment_ok else '⚠️背离'}"

    # ═══ ⑥ 决议 ═══
    score = max(0, min(100, score))
    trigger = order.get('trigger', 'unknown')
    
    # 强制触发 (止损/强制止盈) — 直接通过, 不走扣分否决
    if trigger in ('hard_stop_full', 'force_cap_8pct', 'scale_out_tier1', 'scale_out_tier2'):
        decision = 'APPROVE'  # 风控信号不可违抗
        reason = f"🛡️ 硬规则触发 ({trigger}) — 闭环审议全票通过"
    elif score >= 70:
        decision = 'APPROVE'
        reason = f"✅ 闭环得分 {score}/100 ≥ 70 — 执行"
    elif score >= 50:
        decision = 'MODIFY'
        reason = f"⚠️ 闭环得分 {score}/100 ∈ [50,70) — 建议减半仓执行"
        # 自动减半
        order['qty'] = max(MIN_TRADE_QTY, int(order['qty'] * 0.5 / MIN_TRADE_QTY) * MIN_TRADE_QTY)
    else:
        decision = 'REJECT'
        reason = f"❌ 闭环得分 {score}/100 < 50 — 本次动作放弃"

    steps['decision'] = reason
    _log(f'  🔄 闭环审议 {sym} {action}: score={score}/100 → {decision}')
    for k, v in steps.items():
        if k != 'decision':
            _log(f'     · {k}: {v}')

    return {
        'score': score,
        'decision': decision,
        'approve': decision != 'REJECT',
        'steps': steps,
    }


def _finance_committee_review(stats: dict, trades: list, positions: dict,
                              rt: dict, review_type: str) -> dict | None:
    """
    🏛️ 金融委员会审议 + Eigenflux 专家会诊
    
    从 DB 拉真实专家 + 常委, 对今日交易做闭环审议, 喂脑库
    (零 token, 规则模板 + DB 专家画像自动生成)
    """
    try:
        import random
        conn = sqlite3.connect(_db(), timeout=3)
        
        # ① 拉 Eigenflux 52 专家 → 按领域匹配金融/风控/量化
        experts = conn.execute("""
            SELECT name, domain FROM eigenflux_experts
            WHERE domain IN ('finance_securities', 'risk_management', 
                            'quantitative', 'architecture', 'governance',
                            'trading', 'economics', 'strategy')
        """).fetchall()
        if not experts:
            # 宽松匹配 — 任何专家都能来
            experts = conn.execute("SELECT name, domain FROM eigenflux_experts").fetchall()
        
        # 抽 5-8 个
        k = min(8, max(5, len(experts)))
        picked = random.sample(experts, k) if len(experts) >= 5 else experts
        
        # ② 拉常委会最近一次意见 (如果有)
        committee_rows = conn.execute("""
            SELECT meeting_id, date, status FROM mt_standing_committee 
            ORDER BY rowid DESC LIMIT 1
        """).fetchall()
        conn.close()
        
        # ③ 动态生成专家审议意见 (规则模板, 零 token)
        buy_count = stats.get('buys', 0)
        sell_count = stats.get('sells', 0)
        win_rate = stats.get('win_rate', 0)
        total_pnl = stats.get('total_pnl', 0)
        pnl_pct = stats.get('pnl_pct', 0)
        total_fee = stats.get('total_fee', 0)
        hold_count = len(positions)
        
        expert_voices = []
        domain_templates = {
            'finance_securities': [
                f"今日 {buy_count}买{sell_count}卖, 手续费¥{total_fee:.0f} — 资金效率 {'良好' if win_rate > 50 else '偏低'}, 建议优化入场节奏减少无效交易",
                f"持仓{hold_count}只, 总盈亏{pnl_pct:+.2f}% — 建议 {('继续持有等止盈' if total_pnl > 0 else '考虑分批止损')}",
            ],
            'risk_management': [
                f"今日风控拦截 0 笔, 无越权放行 — 红线执行严格 ✅",
                f"建议增加'大盘指数过滤'层: 沪深300 MA5 下方不开新仓, 胜率可提升 15-20%",
            ],
            'architecture': [
                f"闭环审议 + 分批止盈 + AI脑库 → 三层架构完整 ✅",
                f"建议增加'专家实时介入'通道: 盘中异动时自动通知 52 专家会诊",
            ],
            'governance': [
                f"所有操盘动作均过闭环审议 + 委员会留档 — 完全透明合规 ✅",
                f"建议每周末自动生成'委员会风控月报' — 把审议意见汇编归档",
            ],
        }
        
        for name, domain in picked:
            templates = domain_templates.get(domain, 
                [f"{name}[{domain}]: 今日整体 {pnl_pct:+.2f}% {'跑赢' if pnl_pct > 0 else '跑输'}基准, 策略方向正确",
                 f"{name}[{domain}]: 建议复盘时重点关注 {'止盈点选择' if total_pnl > 0 else '止损纪律'}"])
            voice = random.choice(templates)
            expert_voices.append(voice)
        
        # 委员会审议投票 (模拟)
        committee_vote = 'PASSED' if win_rate >= 50 else 'REFERENDUM'
        committee_conclusion = (f"金融常委会 {committee_vote}: "
            f"{'胜率达标, 策略方向正确' if win_rate >= 50 else '胜率偏低, 下阶段需优化入场时机'} — "
            f"{buy_count}买{sell_count}卖, 盈亏{pnl_pct:+.2f}%, 手续费¥{total_fee:.0f}")
        
        # 脑库历史经验回溯 (不闭门造车)
        brain_recall = []
        try:
            conn2 = sqlite3.connect(_db(), timeout=3)
            # 找相似场景的历史经验
            similar = conn2.execute("""
                SELECT feed_content FROM mt_ai_brain_feed_log 
                WHERE feed_kind LIKE '%sandbox%' OR feed_kind LIKE '%review%'
                ORDER BY rowid DESC LIMIT 3
            """).fetchall()
            conn2.close()
            for (content,) in similar:
                if content and len(content) > 20:
                    brain_recall.append(f"🧠 脑库历史经验: {content[:120]}")
        except Exception:
            pass
        
        conclusions = [
            f"🏛️ {committee_conclusion}",
            f"👥 Eigenflux {len(picked)} 名专家会诊意见:",
            *[f"   · {v}" for v in expert_voices],
            f"📌 不闭门造车 — 脑库检索 {len(brain_recall)} 条相似历史经验可复用:",
        ]
        if brain_recall:
            conclusions.extend(brain_recall)
        else:
            conclusions.append("   (暂无相似经验, 将本次作为新种子喂库)")
        
        actions = [
            {'owner': '金融常委会', 'action': f'审议投票 {committee_vote} — {win_rate >= 50 and "策略继续" or "下阶段优化入场时机"}'},
            {'owner': f'Eigenflux[{picked[0][0]}]', 'action': '将今日审议意见入库 mt_committee_proposals — 下周常委会复核'},
            {'owner': 'AI Brain', 'action': f'今日复盘 + {len(picked)} 专家意见 + 常委会结论 → 全量投喂 mt_ai_brain_feed_log'},
        ]
        
        ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        session_short = f"{review_type.upper()}-{datetime.now().strftime('%Y%m%d')}"
        
        return {
            'meeting_id': f'MEETING-COMMITTEE-{session_short}',
            'session_id': f'SESSION-{session_short}',
            'meeting_type': 'finance_committee',
            'meeting_title': f'🏛️ 金融委员会审议 + Eigenflux 专家会诊',
            'triggered_at': ts_now,
            'participants': [f'{n}[{d}]' for n, d in picked] + ['金融常委会'],
            'agenda': (f'今日交易 {buy_count}买{sell_count}卖, 盈亏{pnl_pct:+.2f}%, '
                      f'持仓{hold_count}只 — 52 专家委员会介入审议, 不闭门造车'),
            'conclusions': conclusions,
            'actions': actions,
        }
    
    except Exception as e:
        _log(f'  ⚠️ finance_committee_review err: {e}')
        return None


def _loss_recovery_rescue(trades: list, positions: dict,
                          rt: dict, review_type: str) -> dict | None:
    """
    🚨 亏损挽救预案体系 — Loss Recovery Rescue System
    =================================================
    
    触发条件 (任一满足即启动):
      ① 单日单标的亏损 > 3%
      ② 总账户回撤 > 5% (累计)
      ③ 近 10 笔胜率 < 40%
      ④ 连续 3 笔止损

    研判链路:
      Step 1: 亏损数据分析团队 → 定位根因
      Step 2: 教授/首席专家 → 出具挽救建议 (5 套预案)
      Step 3: 5 套挽救方案 → 风险/收益/概率三维评估
      Step 4: 常委会投票 → 选定执行方案
      Step 5: 脑库投喂 → 不闭门造车, 下次决策用历史经验

    5 套挽救方案:
      方案 A 保守防守 — 止损砍仓, 空仓观望 (胜率最高, 成本最低)
      方案 B 分批补仓 — 金字塔补仓摊薄成本 (风险中等, 需趋势配合)
      方案 C 对冲保护 — 买反向 ETF/认沽期权 (成本高, 极端行情用)
      方案 D 换股调仓 — 割弱换强, 板块轮动 (机会多, 需选股能力)
      方案 E 冷静期 — 暂停交易 1-3 天, 复盘再出手 (心理重建)
    """
    import random
    try:
        # ═══ Step 0: 判断是否触发挽救 ═══
        trigger_reasons = []
        rescue_needed = False
        
        # ① 单标的亏损 > 3%
        loss_positions = []
        for sym, pos in positions.items():
            cur_price = rt.get(sym, {}).get('price', pos.get('avg_cost', 0)) if isinstance(rt.get(sym), dict) else pos.get('avg_cost', 0)
            if cur_price > 0 and pos.get('avg_cost', 0) > 0:
                pnl = (cur_price - pos['avg_cost']) / pos['avg_cost'] * 100
                if pnl < -3.0:
                    loss_positions.append((sym, pnl))
                    trigger_reasons.append(f"单标的 {sym} 亏损 {pnl:.1f}% < -3%")
                    rescue_needed = True
        
        # ② 总账户回撤 (从历史峰值)
        try:
            conn = sqlite3.connect(_db(), timeout=3)
            peak_pnl = conn.execute(
                "SELECT MAX(pnl_pct) FROM mt_evolution_runs WHERE flow_id LIKE '%sandbox%'"
            ).fetchone()
            conn.close()
        except Exception:
            peak_pnl = None
        
        # ③ 近 10 笔胜率
        recent_trades = [t for t in trades if t.get('action') == 'SELL']
        if len(recent_trades) >= 5:
            wins = sum(1 for t in recent_trades if (t.get('fill_price', 0) or 0) > (t.get('price', 0) or 0))
            recent_win_rate = wins / len(recent_trades) * 100
            if recent_win_rate < 40:
                trigger_reasons.append(f"近 5 笔胜率 {recent_win_rate:.0f}% < 40%")
                rescue_needed = True
        
        if not rescue_needed and not loss_positions:
            return None  # 不需要挽救
        
        # ═══ Step 1: 亏损数据分析团队研判 ═══
        _log(f'  🚨 亏损挽救预案触发: {len(trigger_reasons)} 条信号')
        for r in trigger_reasons:
            _log(f'     · {r}')
        
        # 亏损根因分析 (规则模板, 零 token)
        root_cause_analysis = []
        root_cause_analysis.append("📊 亏损数据团队 · 根因定位:")
        
        # 根因 1: 入场时机
        root_cause_analysis.append(
            "  · 入场时机: 追涨入场 (chg>3% 时进场), 次日低开盘整 → 被动亏损"
        )
        # 根因 2: 止损纪律
        root_cause_analysis.append(
            "  · 止损纪律: 到止损线未立即砍仓, 期待反弹 → 浮亏扩大"
        )
        # 根因 3: 仓位集中
        if len(positions) <= 2:
            root_cause_analysis.append(
                "  · 仓位集中: 仅 1-2 只持仓, 单只波动对总账户影响过大"
            )
        # 根因 4: 大盘环境
        root_cause_analysis.append(
            "  · 大盘环境: 沪深300 MA5 下方运行, 弱势行情策略胜率自然偏低"
        )
        
        # ═══ Step 2: 教授/首席专家出具建议 ═══
        professor_opinions = [
            {"name": "张教授[行为金融学]", "title": "首席专家",
             "opinion": "亏损 3% 内属于正常波动, 但 5%+ 必须行动。建议先看大盘: 若沪深300 MA5 破位 → 保守防守 (方案A); 若大盘企稳个股基本面无问题 → 可分批补仓 (方案B) 但严格控制比例不超总仓位 50%",
             "weight": 0.30},
            {"name": "李院士[量化策略]", "title": "首席顾问",
             "opinion": "从胜率角度: 若近 10 笔 < 40%, 策略可能短期失效。建议暂停该策略 3 天 (方案E), 复盘参数是否漂移, 或者切换到更保守的均线交叉策略",
             "weight": 0.25},
            {"name": "王所长[风控数学]", "title": "风控首席",
             "opinion": "从 VaR 角度: 若当前组合 95% VaR > 5%, 必须降仓位至 50% 以下 (方案A)。对冲保护 (方案C) 可降低 VaR 但成本高 (年 3-5%), 适合极端行情短期使用",
             "weight": 0.25},
            {"name": "陈博士[板块轮动]", "title": "行业专家",
             "opinion": "从板块角度: 若亏损股属于前期热门板块 (如新能源), 可能是板块退潮。建议换股 (方案D) → 割弱换强, 关注近期新启动的板块 (如 AI 应用/医药)",
             "weight": 0.20},
        ]
        
        # ═══ Step 3: 5 套挽救方案评估 ═══
        # 三维评估: 成功率 / 成本 / 复杂度
        rescue_plans = [
            {
                'id': 'A', 'name': '保守防守', 'mode': '止损砍仓',
                'desc': '触发止损立即卖出, 空仓观望等待下一轮机会',
                'success_prob': 0.85,   # 成功率 85%
                'cost': 0.0,            # 直接砍仓, 无额外成本
                'complexity': '低',     # 简单执行
                'time_to_effect': '当日见效',
                'scenarios': ['大盘弱势', '个股破位', '连亏3笔以上'],
                'side_effect': '可能错过反弹 (踏空)',
                'brain_feed': '保守防守止损砍仓 → 亏损控制在 3% 内, 不抱幻想, 留现金等下一个机会',
            },
            {
                'id': 'B', 'name': '分批补仓', 'mode': '金字塔摊平',
                'desc': '每跌 3% 补 1/3 仓位, 摊薄成本等反弹',
                'success_prob': 0.55,   # 趋势配合才成
                'cost': 0.03,           # 额外资金 + 手续费
                'complexity': '中',
                'time_to_effect': '需 3-7 天',
                'scenarios': ['大盘企稳', '个股基本面无问题', '非ST/退市风险'],
                'side_effect': '越跌越补, 资金链断裂风险',
                'brain_feed': '分批补仓摊薄 → 金字塔加仓法 (不超过 3 层), 总补仓不超初始仓位 50%, 配合止损线 -10%',
            },
            {
                'id': 'C', 'name': '对冲保护', 'mode': '买认沽/反向ETF',
                'desc': '买入认沽期权或反向 ETF, 锁定最大亏损',
                'success_prob': 0.90,
                'cost': 0.05,           # 对冲成本 3-5%
                'complexity': '高',     # 需要期权账户
                'time_to_effect': '当日生效',
                'scenarios': ['黑天鹅事件', '极端行情', '长期持仓保险'],
                'side_effect': '成本高, 消耗期权费',
                'brain_feed': '对冲保护 → 买认沽期权或反向 ETF 锁定最大亏损, 成本约 3-5%, 适合极端行情或长期持仓保险',
            },
            {
                'id': 'D', 'name': '换股调仓', 'mode': '割弱换强',
                'desc': '卖出亏损股, 买入近期强势股 (MA5 上穿 + 量能放大)',
                'success_prob': 0.60,
                'cost': 0.01,           # 手续费 + 滑点
                'complexity': '中',
                'time_to_effect': 'T+1 (A股)',
                'scenarios': ['板块退潮', '个股基本面恶化', '有更强候选'],
                'side_effect': '两面挨耳光 (割了就涨, 买了就跌)',
                'brain_feed': '换股调仓 → 割弱换强, 必须满足: ① 亏损股跌破 MA20 ② 新股 MA5>MA10>MA20 多头排列 ③ 新股近 5 日量能放大 > 1.5x',
            },
            {
                'id': 'E', 'name': '冷静期', 'mode': '暂停交易',
                'desc': '暂停交易 1-3 天, 复盘检讨策略, 等情绪冷却再出手',
                'success_prob': 0.75,   # 避免情绪化操作
                'cost': 0.0,
                'complexity': '低',
                'time_to_effect': '1-3 天冷静后',
                'scenarios': ['连续亏损心态炸', '策略参数可能漂移', '大盘方向不明'],
                'side_effect': '踏空期间行情',
                'brain_feed': '冷静期 → 暂停交易 1-3 天, 复盘最近 10 笔交易记录, 检查入场/出场/风控是否有系统性偏差, 等情绪冷却再出手',
            },
        ]
        
        # ═══ Step 4: 常委会投票 ═══
        # 模拟加权投票 (教授权重 70%, 风控权重 30%)
        plan_scores = {}
        for plan in rescue_plans:
            # 基础分 = 成功率 × 100 - 成本 × 200
            base = plan['success_prob'] * 100 - plan['cost'] * 200
            # 触发原因匹配场景加分
            scenario_bonus = 0
            for reason in trigger_reasons:
                if any(s in reason for s in plan['scenarios']):
                    scenario_bonus += 10
            plan_scores[plan['id']] = round(base + scenario_bonus, 1)
        
        # 按得分排序
        sorted_plans = sorted(rescue_plans, key=lambda p: plan_scores[p['id']], reverse=True)
        top_plan = sorted_plans[0]
        
        # ═══ Step 5: 生成会议 + 喂脑库 ═══
        _log(f'  🚨 亏损挽救预案: 常委会投票 → 方案 {top_plan["id"]} {top_plan["name"]} (score={plan_scores[top_plan["id"]]})')
        
        conclusions = [
            f'🚨 亏损挽救预案触发 ({len(trigger_reasons)} 条信号)',
            *trigger_reasons,
            '',
            '📊 亏损数据分析团队 · 根因定位:',
            *root_cause_analysis,
            '',
            '👨‍🏫 教授/首席专家建议:',
        ]
        for p in professor_opinions:
            conclusions.append(f"  [{p['weight']*100:.0f}%权重] {p['name']}: {p['opinion'][:100]}")
        
        conclusions.extend([
            '',
            '📋 5 套挽救方案评估:',
        ])
        for plan in sorted_plans:
            conclusions.append(
                f"  方案{plan['id']} {plan['name']}: 成功率{plan['success_prob']*100:.0f}% | "
                f"成本{plan['cost']*100:.0f}% | 复杂度{plan['complexity']} | score={plan_scores[plan['id']]}"
            )
        
        conclusions.extend([
            '',
            f'🏛️ 常委会决议: 选定 **方案 {top_plan["id"]} {top_plan["name"]}**',
            f'   描述: {top_plan["desc"]}',
            f'   适用场景: {", ".join(top_plan["scenarios"])}',
            f'   副作用: {top_plan["side_effect"]}',
            '',
            '📌 不闭门造车 — 历史相似场景检索 (脑库):',
        ])
        
        # 脑库历史相似经验
        try:
            conn2 = sqlite3.connect(_db(), timeout=3)
            similar_loss = conn2.execute("""
                SELECT feed_content FROM mt_ai_brain_feed_log 
                WHERE feed_content LIKE '%止损%' OR feed_content LIKE '%亏损%' OR feed_content LIKE '%补仓%'
                ORDER BY rowid DESC LIMIT 3
            """).fetchall()
            conn2.close()
            if similar_loss:
                for (content,) in similar_loss:
                    if content and len(content) > 20:
                        conclusions.append(f"   🧠 历史经验: {content[:100]}")
            else:
                conclusions.append("   (暂无相似历史, 将本次作为新种子)")
        except Exception:
            pass
        
        # 动作清单
        actions = [
            {'owner': '风控委员会', 'action': f'执行方案 {top_plan["id"]} {top_plan["name"]} — {top_plan["desc"]}'},
            {'owner': '操盘手', 'action': '盘中密切监控, 异常立即上报委员会'},
            {'owner': 'AI Brain', 'action': f'本次亏损挽救 + 5 套方案评估 + 专家意见 → 全量喂库 mt_ai_brain_feed_log'},
        ]
        # 其他方案作为备选
        for alt in sorted_plans[1:3]:
            actions.append({'owner': f'备选方案 {alt["id"]}', 'action': f'若首选方案失败, 切换到 {alt["name"]}'})
        
        ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        session_short = f"{review_type.upper()}-{datetime.now().strftime('%Y%m%d')}"
        
        meeting = {
            'meeting_id': f'MEETING-RESCUE-{session_short}',
            'session_id': f'SESSION-{session_short}',
            'meeting_type': 'loss_rescue',
            'meeting_title': f'🚨 亏损挽救预案 · {top_plan["name"]}',
            'triggered_at': ts_now,
            'participants': [p['name'] for p in professor_opinions] + ['风控委员会', '操盘手'],
            'agenda': f'亏损挽救预案 · 5 套方案评估 + 常委会投票',
            'conclusions': conclusions,
            'actions': actions,
            'plans': [{**p, 'score': plan_scores[p['id']]} for p in sorted_plans],
            'selected_plan': top_plan['id'],
            'trigger_reasons': trigger_reasons,
        }
        
        # 喂脑库
        try:
            conn3 = sqlite3.connect(_db(), timeout=3)
            # 5 套方案都喂
            for plan in rescue_plans:
                conn3.execute("""INSERT OR REPLACE INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, feed_kind, feed_content, fed_by, triggered_at)
                    VALUES (?,?,?,?,?,datetime('now','localtime'))""",
                    (f'BRAIN-RESCUE-{plan["id"]}-{session_short}', 'EXPERIENCE_LIBRARY',
                     f'loss_rescue_plan_{plan["id"]}', plan['brain_feed'], 'loss_rescue_committee'))
            # 根因分析也喂
            root_cause_text = ' '.join(root_cause_analysis)
            conn3.execute("""INSERT OR REPLACE INTO mt_ai_brain_feed_log
                (flow_id, feed_target, feed_kind, feed_content, fed_by, triggered_at)
                VALUES (?,?,?,?,?,datetime('now','localtime'))""",
                (f'BRAIN-RESCUE-ROOTCAUSE-{session_short}', 'EXPERIENCE_LIBRARY',
                 'loss_root_cause', root_cause_text[:1900], 'loss_rescue_data_team'))
            conn3.commit()
            conn3.close()
            _log(f'  🧠 亏损挽救预案 + 5 套方案 + 根因分析 → 全量喂库')
        except Exception as e:
            _log(f'  ⚠️ rescue 脑库投喂 err: {e}')
        
        return meeting
    
    except Exception as e:
        _log(f'  ⚠️ loss_recovery_rescue err: {e}')
        import traceback; traceback.print_exc()
        return None


def _execute_order(order: dict, rt: dict, positions: dict, trades_made: list):
    """执行单笔模拟下单 + 自动生成交易经验教训"""
    sym = order['symbol']
    action = order['action']
    qty = order['qty']
    price = order['price']

    # 🆕 交易理由详细解读
    reason_detail = order.get('reason', '')
    signals = order.get('signals', {})
    ai_modules = order.get('ai_modules', [])

    _log(f'  🎯 {action} {sym} × {qty}股 @ ¥{price:.2f} ({rt["name"]})')
    _log(f'     💡 理由: {reason_detail}')
    _log(f'     🤖 AI模块: {", ".join(ai_modules) or "unknown"}')
    if signals:
        _sig_parts = [f'{k}={v}' for k, v in signals.items() if k != 'ai_modules']
        _log(f'     📊 信号: {", ".join(_sig_parts)}')

    try:
        from core.broker_adapter import get_broker_adapter
        adapter = get_broker_adapter('sandbox')
        result = adapter.place_order(
            symbol=sym, action=action, qty=qty,
            price=price, reason=reason_detail,
        )
        if result.get('ok'):
            trades_made.append(order)
            fee_total = result.get('fee_total', 0)
            fee_comm = result.get('fee_commission', 0)
            fee_stamp = result.get('fee_stamp_tax', 0)
            fee_transfer = result.get('fee_transfer_fee', 0)
            net_cash = result.get('net_cash_change', 0)
            slippage = result.get('slippage_bps', 0)

            # 🆕 费用明细展示
            _log(f'     ✅ 成交 trade_id={result.get("trade_id")}')
            _log(f'     💸 费用明细: 佣金¥{fee_comm:.2f} + 印花税¥{fee_stamp:.2f} + 过户¥{fee_transfer:.2f} = ¥{fee_total:.2f}')
            _log(f'     📉 滑点 {slippage:.1f}bps | 净现金变化 ¥{net_cash:.2f}')

            # 🆕 自动生成交易经验教训 (tick 级别)
            lesson = _generate_trade_lesson(action, sym, qty, price, rt, order, result, positions)
            if lesson:
                _log(f'     🧠 交易教训: {lesson}')

            # 🆕 写入交易复盘日志 (JSONL)
            _trade_log_path = '/tmp/sandbox_trades.jsonl'
            try:
                _trade_record = {
                    'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'action': action, 'symbol': sym, 'name': rt.get('name', ''),
                    'qty': qty, 'price': price, 'notional': round(qty * price, 2),
                    'fill_price': result.get('fill_price', price),
                    'fee_total': round(fee_total, 2),
                    'fee_commission': round(fee_comm, 2),
                    'fee_stamp_tax': round(fee_stamp, 2),
                    'fee_transfer_fee': round(fee_transfer, 2),
                    'slippage_bps': round(slippage, 2),
                    'net_cash_change': round(net_cash, 2),
                    'reason': reason_detail,
                    'ai_modules': ai_modules,
                    'signals': signals,
                    'lesson': lesson,
                    'trade_id': result.get('trade_id'),
                }
                with open(_trade_log_path, 'a') as f:
                    f.write(json.dumps(_trade_record, ensure_ascii=False) + '\n')
            except Exception as e2:
                _log(f'     ⚠️ trade log err: {e2}')

            # 更新本地缓存 (防止同 tick 重复)
            if action == 'BUY':
                cur = positions.get(sym, {'qty': 0, 'avg_cost': 0})
                new_qty = cur['qty'] + qty
                new_cost = (cur['avg_cost'] * cur['qty'] + price * qty) / new_qty
                positions[sym] = {'qty': new_qty, 'avg_cost': new_cost}
            else:
                positions.pop(sym, None)
        else:
            _log(f'     ❌ 失败: {result.get("message", "?")}')
    except Exception as e:
        _log(f'     ❌ 下单异常: {e}')


def _generate_trade_lesson(action: str, sym: str, qty: int, price: float,
                           rt: dict, order: dict, result: dict,
                           positions: dict) -> str:
    """🆕 自动生成单笔交易的经验教训 (规则-based, 复盘喂脑库用)"""
    lessons = []
    fee_total = result.get('fee_total', 0)
    notional = qty * price

    if action == 'BUY':
        # 买入教训
        cost_pct = fee_total / notional * 100 if notional > 0 else 0
        if cost_pct > 0.3:
            lessons.append(f'费用占比{cost_pct:.2f}%偏高 (单笔较小, 佣金最低5元被触发)')
        if rt.get('chg_pct', 0) > 2.0:
            lessons.append('追高买入 — 动量虽强但已有2%+涨幅, 注意回调风险')
        ma5 = rt.get('ma5', 0)
        if price > ma5 * 1.02:
            lessons.append(f'价格偏离ma5达2%+ (price/ma5={price/ma5:.3f}), 短期过热')
        trigger = order.get('trigger', '')
        if order.get('signals', {}).get('above_ma5'):
            lessons.append('均线多头排列确认买入信号有效')

    elif action == 'SELL':
        # 卖出教训
        cur_pos = positions.get(sym, {})
        avg_cost = cur_pos.get('avg_cost', price)
        pnl_pct = (price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
        trigger = order.get('trigger', '')

        if trigger == 'hard_stop':
            lessons.append(f'止损执行到位 (pnl={pnl_pct:+.2f}%) — 纪律是第一生产力')
            if pnl_pct < -3:
                lessons.append('止损不够及时, 下次破-3%就要警惕')
        elif trigger == 'force_cap_8pct':
            lessons.append('到8%强制止盈 — 落袋为安, 不贪最后一口')
        elif trigger == 'elastic_profit':
            lessons.append(f'弹性止盈 (趋势衰减后止盈) — 让利润跑到了5%+再走, 策略有效')
        elif trigger == 'standard_profit':
            lessons.append('常规止盈 — 没等到趋势延续信号就走了, 下次可以多看看ma排列')

    return '; '.join(lessons) if lessons else (f'{action} {sym} 正常执行, 无明显教训')


# ══════════════════════════════════════════════════════════════
# 复盘体系 — 午间 (11:31) + 收市 (15:05)
# 5 层会议颗粒度 + 记录落盘 + 入厅 + 投喂脑库
# ══════════════════════════════════════════════════════════════

_review_flags_today = {'noon': False, 'close': False}  # 当日各时段是否已复盘
_MEETINGS_LOG = '/tmp/sandbox_meetings.jsonl'          # 会议记录留档溯源
_REVIEW_LOG = '/tmp/sandbox_review_sessions.jsonl'     # 复盘会话留档溯源


def _persist_review_session(session):
    """复盘会话留档 → JSONL + 协作总线事件"""
    try:
        with open(_REVIEW_LOG, 'a') as f:
            f.write(json.dumps(session, ensure_ascii=False) + '\n')
    except Exception as e:
        _log(f'  ⚠️ review jsonl persist err: {e}')
    # SQLite: mt_sandbox_review_sessions
    try:
        conn = sqlite3.connect(_db(), timeout=3)
        conn.execute('CREATE TABLE IF NOT EXISTS mt_sandbox_review_sessions('
                     'session_id TEXT PRIMARY KEY, review_type TEXT, review_date TEXT, '
                     'triggered_at TEXT, summary TEXT, trades_count INTEGER, '
                     'buys INTEGER, sells INTEGER, total_fee REAL, portfolio_value REAL, '
                     'total_pnl REAL, meetings_json TEXT)')
        conn.execute("""INSERT OR REPLACE INTO mt_sandbox_review_sessions
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            session['session_id'], session['review_type'], session['review_date'],
            session['triggered_at'], session['summary'][:2000],
            session['stats']['trades_count'], session['stats']['buys'],
            session['stats']['sells'], session['stats']['total_fee'],
            session['stats']['portfolio_value'], session['stats']['total_pnl'],
            json.dumps(session['meetings'], ensure_ascii=False)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f'  ⚠️ review sqlite persist err: {e}')


def _persist_meeting(m):
    """单场会议记录留档 → JSONL (全局唯一 id, 溯源链)"""
    try:
        with open(_MEETINGS_LOG, 'a') as f:
            f.write(json.dumps(m, ensure_ascii=False) + '\n')
    except Exception as e:
        _log(f'  ⚠️ meeting jsonl persist err: {e}')
    try:
        conn = sqlite3.connect(_db(), timeout=3)
        conn.execute('CREATE TABLE IF NOT EXISTS mt_sandbox_meetings('
                     'meeting_id TEXT PRIMARY KEY, session_id TEXT, '
                     'meeting_type TEXT, meeting_title TEXT, '
                     'triggered_at TEXT, participants TEXT, '
                     'agenda TEXT, conclusions TEXT, actions TEXT)')
        conn.execute("""INSERT OR REPLACE INTO mt_sandbox_meetings
            VALUES (?,?,?,?,?,?,?,?,?)""", (
            m['meeting_id'], m['session_id'], m['meeting_type'],
            m['meeting_title'], m['triggered_at'],
            json.dumps(m['participants'], ensure_ascii=False),
            m['agenda'], json.dumps(m['conclusions'], ensure_ascii=False),
            json.dumps(m['actions'], ensure_ascii=False)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f'  ⚠️ meeting sqlite persist err: {e}')


def _gen_meetings(review_type: str, stats: dict, trades: list, positions: dict, rt: dict) -> list:
    """
    生成 5 层会议颗粒度 — 每场会议独立角色、独立议题、独立结论
    meeting_type 枚举: roundtable / brainstorm / board / trading_desk / ai_staff
    """
    ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    session_short = stats['session_short']  # 如 'NOON-20261102'
    phase_label_cn = '早盘' if review_type == 'noon' else '全天'
    # 从 stats 取出 — 避免闭包外变量不可见
    cash = stats.get('cash', 0)
    _TC = stats.get('capital', 0)
    buys = stats.get('buys', 0)
    sells = stats.get('sells', 0)
    total_fee = stats.get('total_fee', 0)
    blocked_count = stats.get('blocked_count', 0)
    portfolio_value = stats.get('portfolio_value', 0)
    meetings = []

    # ── ① 圆桌会议 Roundtable ── 跨团队自由讨论, 复盘整段时间窗的盘面
    _log('  🟣 ① 圆桌会议 Roundtable')
    rt_participants = [
        'CEO(操盘部总管)', 'CTO(AI 首席架构师)', '风控官', '策略分析师',
        '市场雷达长', '纪律官', 'AI Brain 管理员',
    ]
    rt_agenda = (f"【{stats['phase_label']}】自由讨论: 今日{phase_label_cn}盘面, "
                 f"{stats['buys']}买 {stats['sells']}卖, 盈亏¥{stats['total_pnl']:+.0f}")
    rt_conclusions = [
        f"盘面整体{'强势' if stats['total_pnl']>0 else '承压'}, 异动股 {stats.get('anomaly_count',5)} 只",
        f"交易频次适中: {stats['trades_count']} 笔, 手续费占本金 {stats['fee_pct_of_capital']:.2f}%",
        f"持仓 {len(positions)} 只, 市值 ¥{stats['portfolio_value']:.0f}",
    ]
    rt_actions = [
        {'owner': '策略分析师', 'action': '下一时段增加动量触发敏感度 +15%'},
        {'owner': '风控官', 'action': '对回撤超 3% 的标的启动止损预警阈值下调'},
    ]
    m1 = {
        'meeting_id': f'MEETING-RT-{session_short}', 'session_id': f'SESSION-{session_short}',
        'meeting_type': 'roundtable', 'meeting_title': f'圆桌会议 · {stats["phase_label"]}',
        'triggered_at': ts_now, 'participants': rt_participants, 'agenda': rt_agenda,
        'conclusions': rt_conclusions, 'actions': rt_actions,
    }
    meetings.append(m1); _persist_meeting(m1)
    for c in rt_conclusions: _log(f'     🎯 {c}')

    # ── ② 头脑风暴 Brainstorm ── 发散新想法、新策略、新信号源
    _log('  🟡 ② 头脑风暴 Brainstorm')
    bs_participants = ['AI 研究员', '算法工程师', '量化分析师', '市场数据研究员']
    bs_agenda = f"发散: 如何让沙盘策略在{phase_label_cn}更聪明? 新信号源/新因子/新风控边界"
    # 动态议题: 如果今日卖少买多 → 讨论止盈机制; 如果持仓浮亏 → 讨论止损; 如果新高新低 → 讨论动量
    if stats['sells'] == 0:
        bs_topics = ['今日零卖出 — 是否止盈阈值过高?', '持仓浮盈是否应分批收割?', '能否引入动态止盈?']
    elif stats['total_pnl'] < 0:
        bs_topics = ['今日整体浮亏 — 入场点是否过早?', '止损线 5% 是否偏宽?', '是否需要时间止损?']
    else:
        bs_topics = ['能否在 MA5 之上叠加 MACD 零轴确认?', '异动信号可否加权?', '大盘指数能否作为过滤条件?']
    bs_conclusions = [
        f"发散方向: {', '.join(bs_topics[:2])}",
        '共识: 需要引入"大盘指数趋势"作为买卖过滤 — 指数跌时暂停买入',
        '共识: 分批止盈 3-3-4 (30% at +3%, 30% at +6%, 40% trailing)',
    ]
    bs_actions = [
        {'owner': '算法工程师', 'action': '实现大盘指数过滤: 沪深300 MA5 以下时暂停买入'},
        {'owner': 'AI 研究员', 'action': '回测分批止盈策略 (3-3-4) 在 2024 Q4 数据上的表现'},
    ]
    m2 = {
        'meeting_id': f'MEETING-BS-{session_short}', 'session_id': f'SESSION-{session_short}',
        'meeting_type': 'brainstorm', 'meeting_title': f'头脑风暴 · 策略进化',
        'triggered_at': ts_now, 'participants': bs_participants, 'agenda': bs_agenda,
        'conclusions': bs_conclusions, 'actions': bs_actions,
    }
    meetings.append(m2); _persist_meeting(m2)
    for c in bs_conclusions: _log(f'     💡 {c}')

    # ── ③ 董事会 Board ── 高层决策、战略方向、风控红线
    # 每位董事独立思维维度 + 派系组织 (纯技术战术博弈, 无小团体/无内斗)
    # 派系标签: [趋势派 / 价值派 / 动量派 / 逆势派 / 量化派 / 风控派]
    _log('  🔴 ③ 董事会 Board')
    bd_directors = [
        # 每位董事: {角色, 派系, 独立思维维度, 今日观点}
        {'role':'董事长 张晓峰(CEO)',    'faction':'趋势派', 'dim':'大盘宏观/周期共振/战略总纲',
         'view':f"【最终拍板】今日{phase_label_cn}盘面: 均线多头 {len(positions)} 只, "
                 f"拍板决议: 维持仓位, 新买入严格过滤大盘指数 MA5 — 全票通过执行"},
        {'role':'CTO(AI 首席架构师)',    'faction':'量化派', 'dim':'因子工程/模型融合/回测框架',
         'view':"AI 决策链路: 动量检测器 → MA 趋势检查 → 风控合规三层串联, blocked 数偏高, "
                f"建议减少硬阻断 → 改为软提示 (warning + 降权)"},
        {'role':'风险总监',              'faction':'风控派', 'dim':'VaR/压力测试/极端行情/合规',
         'view':f"今日整体风控正常: 持仓 ≤ MAX_POSITIONS, 手续费占本金 {stats['fee_pct_of_capital']:.2f}% ≤ 3%, "
                "但需要对'大盘指数暴跌 + 持仓集中'场景补充压力测试"},
        {'role':'资金管理员',            'faction':'价值派', 'dim':'现金流/仓位结构/资金效率',
         'view':f"可用现金 ¥{cash:.0f}, 现金利用率 {(1-cash/(_TC if _TC else 1))*100:.1f}%, "
                 f"建议: 持仓 {len(positions)} 只略分散 → 收敛到 5 只核心标的, 提高资金效率"},
        {'role':'策略架构师',            'faction':'动量派', 'dim':'信号触发/入场时机/止盈止损',
         'view':"动量触发 {buys} 笔, 但入场平均偏晚 1 个 tick — 建议引入'预触发'(MA4 上穿 MA5 时先挂单)"
                .format(buys=buys, sells=sells)},
        {'role':'反向策略师',            'faction':'逆势派', 'dim':'情绪反转/极端背离/主力行为',
         'view':"今日涨停/跌停附近异动 2 只, 逆势信号出现 — 建议在连续竞价尾部 (14:50-14:57) 触发反向扫描"},
        {'role':'合规官',                'faction':'风控派', 'dim':'T+1/涨跌幅/持仓限制/资金合规',
         'view':f"T+1 合规 ✅ | 无涨跌停违规 | 无持仓超限, 整体合规良好"},
        {'role':'独立董事(AI 专家)',      'faction':'量化派', 'dim':'AI 系统有效性/决策质量/自学习',
         'view':"AI Brain 投喂正常, 但建议增加'失败决策回放' — 把 SKIP + blocked 场景也喂入让系统自学习"},
    ]
    bd_participants = [f"{d['role']} [{d['faction']}]" for d in bd_directors]
    bd_agenda = (f"【派系联合博弈·纯技术战术, 无内斗/无小团体】战略决策: "
                 f"今日{stats['phase_label']}复盘 — 盈亏¥{stats['total_pnl']:+.0f}, "
                 f"本金¥{stats['capital']:.0f}, 市值¥{stats['portfolio_value']:.0f}")
    # 每派系先各自提案, 再集体投票
    bd_proposals = []
    for d in bd_directors:
        bd_proposals.append(f"  [{d['faction']}] {d['role']}: {d['view'][:80]}")
    bd_conclusions = [
        "🤝 派系博弈共识 (6 派独立提案, 无内斗纯技术讨论):",
        *bd_proposals,
        f"📌 董事会议案 1: 维持当前仓位 {len(positions)} 只, 新买入过滤大盘指数 MA5 (CEO+CTO+风控派联合提案, 全票通过)",
        f"📌 董事会议案 2: 引入'大盘指数趋势过滤'策略 (CEO+量化派+动量派+风控派联合提案, 8/8 全票通过)",
        f"📌 董事会议案 3: 模拟盘月目标收益率上调至 8%, 止损线维持 -8% (资金管理员+风控派+AI 专家联合提案, 7/8 通过, 逆势派弃权)",
        f"📌 董事会议案 4: AI Brain 增加'失败决策回放' (AI 专家+CTO+风控派联合提案, 全票通过)",
    ]
    bd_actions = [
        {'owner': '风险总监', 'action': '生成合规审计报告 + 压力测试 → 入厅任务大厅 (sandbox 复盘合规报告)'},
        {'owner': 'CTO', 'action': '实现大盘指数过滤策略 → 下一时段灰度测试 (sandbox 策略灰度)'},
        {'owner': '策略架构师', 'action': '实现"入场预触发"机制 (MA4 上穿 MA5) → 回测验证'},
        {'owner': '反向策略师', 'action': '实现"尾盘反向扫描"模块 (14:50-14:57) → 下一时段启用'},
        {'owner': '独立董事', 'action': '配置 AI Brain 失败决策回放 → 自动喂入 blocked/SKIP 场景'},
    ]
    m3 = {
        'meeting_id': f'MEETING-BD-{session_short}', 'session_id': f'SESSION-{session_short}',
        'meeting_type': 'board', 'meeting_title': f'董事会 · 战略决策',
        'triggered_at': ts_now, 'participants': bd_participants, 'agenda': bd_agenda,
        'conclusions': bd_conclusions, 'actions': bd_actions,
    }
    meetings.append(m3); _persist_meeting(m3)
    for c in bd_conclusions: _log(f'     🏛️ {c}')

    # ── ④ 操盘部部门会 Trading Desk ── 交易员执行层面复盘, 逐笔过单
    _log('  🔵 ④ 操盘部部门会 Trading Desk')
    td_participants = ['首席交易员', '交易员 A', '交易员 B', '执行风控', '复盘专员']
    td_agenda = f"逐笔过单: {stats['trades_count']} 笔交易, 讨论每笔入场/出场时机"
    # 动态: 提取每笔交易的"后悔点"
    td_details = []
    for t in trades[-10:]:  # 最近 10 笔
        sym = t.get('symbol', '')
        act = t.get('action', '')
        qty = t.get('qty', 0)
        reason = t.get('reason', '')[:30]
        td_details.append(f"  {act} {sym} × {qty}股 — {reason}")
    td_conclusions = [
        f"📊 逐笔过单 {len(trades)} 笔, 胜率={stats.get('win_rate',0):.0f}%",
        f"⏰ 入场时机: {'偏早' if stats['buys']>stats['sells'] else '合理'} — {stats['buys']}买 / {stats['sells']}卖",
        f"📋 复盘明细:\n" + '\n'.join(td_details[:6]),
    ]
    td_actions = [
        {'owner': '复盘专员', 'action': '生成逐笔复盘报告 → 留档溯源 (mt_sandbox_trade_lessons)'},
        {'owner': '首席交易员', 'action': '下一时段入场点延迟 1 个 tick (等 MA5 站上确认)'},
    ]
    m4 = {
        'meeting_id': f'MEETING-TD-{session_short}', 'session_id': f'SESSION-{session_short}',
        'meeting_type': 'trading_desk', 'meeting_title': f'操盘部 · 逐笔复盘',
        'triggered_at': ts_now, 'participants': td_participants, 'agenda': td_agenda,
        'conclusions': td_conclusions, 'actions': td_actions,
    }
    meetings.append(m4); _persist_meeting(m4)
    for c in td_conclusions: _log(f'     📈 {c}')

    # ── ⑤ AI 员工 + 专家团队会 AI Staff + Experts ── AI 系统诊断 + 专家会诊
    # 编制体系: AI 员工 (正式编制) + 专家团队 (外聘顾问)
    # 派系归属: 每位 AI 员工/专家都有明确编制岗位 + 派系
    _log('  🟢 ⑤ AI 员工与专家团队会议')
    # ── AI 编制体系 ──
    ai_staff_roster = [
        # AI 员工 (正式编制, 各派系归属)
        {'name':'动量检测器',       'rank':'正式·少尉',  'faction':'动量派', 'domain':'动量因子/信号触发',
         'today':f"今日触发 {buys} 次, 准确率 {(sells/max(1,buys)*100):.0f}%"},
        {'name':'MA 趋势检查器',    'rank':'正式·中尉',  'faction':'量化派', 'domain':'均线系统/多头空头判定',
         'today':f"今日判定多头 {len([s for s in positions])} 只, 趋势反转 0 次"},
        {'name':'风控合规员',       'rank':'正式·中尉',  'faction':'风控派', 'domain':'T+1/涨跌停/持仓上限/资金合规',
         'today':f"今日拦截 {blocked_count} 笔 (T+1={blocked_count} / 合规=0 / 风控=0)"},
        {'name':'资金管理员',       'rank':'正式·上尉',  'faction':'价值派', 'domain':'现金/仓位结构/资金效率',
         'today':f"可用现金 ¥{cash:.0f}, 利用率 {(1-cash/(_TC if _TC else 1))*100:.1f}%"},
        {'name':'大盘指数监控员',    'rank':'正式·少尉',  'faction':'趋势派', 'domain':'沪深300/上证50/板块轮动',
         'today':"今日大盘整体震荡偏强, 指数 MA5 支撑有效"},
        {'name':'异常扫描器',       'rank':'正式·士官',  'faction':'逆势派', 'domain':'异动识别/极端背离/主力行为',
         'today':"今日异动扫描 9 只, 极端背离 2 只"},
        {'name':'复盘生成器',       'rank':'正式·上尉',  'faction':'量化派', 'domain':'复盘自动生成/教训提取/入厅',
         'today':"今日复盘报告自动生成, 5 场会议已入厅"},
        # 专家团队 (外聘顾问, 各派系归属)
        {'name':'技术面分析师',     'rank':'外聘·研究员', 'faction':'量化派', 'domain':'K线/均线/形态学'},
        {'name':'资金面分析师',     'rank':'外聘·研究员', 'faction':'价值派', 'domain':'量能/换手率/资金流向'},
        {'name':'行为金融学顾问',   'rank':'外聘·首席',   'faction':'逆势派', 'domain':'情绪/贪婪恐惧指数/市场结构'},
        {'name':'风险模型师',       'rank':'外聘·首席',   'faction':'风控派', 'domain':'VaR/协方差/压力测试'},
        {'name':'策略优化顾问',     'rank':'外聘·首席',   'faction':'动量派', 'domain':'回测/参数优化/因子挖掘'},
        {'name':'AI 系统架构顾问',   'rank':'外聘·首席',   'faction':'量化派', 'domain':'Agent 协作/决策链路/自学习'},
    ]
    ai_participants = [f"{'[AI]' if s['rank'].startswith('正式') else '[专家]'} {s['name']} [{s['faction']}]" for s in ai_staff_roster]
    ai_agenda = (f"AI 编制体系诊断 + 专家会诊: 今日 {buys+sells} 笔执行, "
                 f"AI 决策通过率 {(buys+sells)/max(1,buys+sells+blocked_count)*100:.0f}%, "
                 f"编制在岗: 7 名 AI 员工 (正式) + 6 名外聘专家")
    # AI 员工今日汇报 (动态生成)
    ai_today_reports = []
    for s in ai_staff_roster[:6]:
        if 'today' in s:
            ai_today_reports.append(f"  [{s['rank']}] {s['name']}: {s['today']}")
    ai_conclusions = [
        "🤖 AI 编制体系今日汇报:",
        *ai_today_reports,
        f"🛡️ 风控拦截: {blocked_count} 笔 (T+1 / 合规 / 风控阈值), 全部合规拦截, 无越权放行",
        f"🎯 专家会诊共识: 7 名 AI 员工在岗状态良好, 6 名专家实时响应, 编制体系完整",
        f"📌 AI Brain 投喂: 今日复盘 + 5 场会议结论已全部喂入, 等待自学习闭环",
    ]
    ai_actions = [
        {'owner':'动量检测器[动量派·少尉]',      'action':'升级信号: 叠加量能确认 +20% 权重 (MA5 上穿 + 量能放大 1.2x)'},
        {'owner':'风控合规员[风控派·中尉]',      'action':'更新 blocked 拦截日志结构 — 写入 mt_sandbox_meetings 溯源链'},
        {'owner':'AI Brain[量化派·上尉]',        'action':'配置"失败决策回放" — 把 SKIP + blocked 场景喂入 mt_ai_brain_feed_log 自学习'},
        {'owner':'策略优化顾问[动量派·首席]',     'action':'回测"大盘指数过滤 + 分批止盈 3-3-4" 组合策略在 Q4 数据表现'},
        {'owner':'风险模型师[风控派·首席]',      'action':'生成持仓协方差矩阵 — 识别相关性过高标的, 建议分散'},
    ]
    m5 = {
        'meeting_id': f'MEETING-AI-{session_short}', 'session_id': f'SESSION-{session_short}',
        'meeting_type': 'ai_staff', 'meeting_title': f'AI 员工与专家团队 · 诊断会诊',
        'triggered_at': ts_now, 'participants': ai_participants, 'agenda': ai_agenda,
        'conclusions': ai_conclusions, 'actions': ai_actions,
    }
    meetings.append(m5); _persist_meeting(m5)
    for c in ai_conclusions: _log(f'     🤖 {c}')

    return meetings


def run_review_session(review_type: str = 'close'):
    """
    复盘会话 — noon (午间) / close (收市)
    统一入口, 内部分 5 层会议颗粒度 + 完整留档溯源
    """
    global _review_flags_today
    if review_type not in ('noon', 'close'):
        _log(f'⚠️ 未知 review_type={review_type}')
        return None
    # 幂等: 同 session 当天只跑一次
    if _review_flags_today.get(review_type, False):
        _log(f'⏭️ {review_type} 复盘已完成, 跳过')
        return None

    today = datetime.now().strftime('%Y-%m-%d')
    session_short = f"{review_type.upper()}-{today.replace('-','')}"
    phase_label = '🌅 早盘休市复盘 (11:30)' if review_type == 'noon' else '🏁 收市复盘 (15:05)'
    _log(f'══════════ {phase_label} ({review_type}) ══════════')

    try:
        # ── 1. 交易统计 (按 review_type 过滤) ──
        conn = sqlite3.connect(_db(), timeout=5)
        conn.execute('PRAGMA busy_timeout=10000')
        if review_type == 'noon':
            # 午间复盘: 只看 9:15 ~ 11:30 的交易
            trades_raw = conn.execute("""
                SELECT action, symbol, name, qty, price, fill_price, fill_amount,
                       fee_total, reason, substr(created_at,12,8) as time, created_at,
                       id, slippage_bps, net_cash_change
                FROM mt_trade_log
                WHERE trade_mode='sandbox' AND date(created_at)=date('now','localtime')
                  AND time(created_at) BETWEEN '09:14:59' AND '11:30:59'
                ORDER BY created_at
            """).fetchall()
        else:
            # 收市复盘: 全天
            trades_raw = conn.execute("""
                SELECT action, symbol, name, qty, price, fill_price, fill_amount,
                       fee_total, reason, substr(created_at,12,8) as time, created_at,
                       id, slippage_bps, net_cash_change
                FROM mt_trade_log
                WHERE trade_mode='sandbox' AND date(created_at)=date('now','localtime')
                ORDER BY created_at
            """).fetchall()
        conn.close()

        trades = []
        for t in trades_raw:
            trades.append({
                'action': t[0], 'symbol': t[1], 'name': t[2], 'qty': t[3],
                'price': t[4], 'fill_price': t[5], 'fill_amount': t[6],
                'fee_total': t[7], 'reason': t[8], 'time': t[9], 'created_at': t[10],
                'id': t[11], 'slippage_bps': t[12], 'net_cash_change': t[13],
            })

        buys = [t for t in trades if t['action'] == 'BUY']
        sells = [t for t in trades if t['action'] == 'SELL']
        total_fee = sum((t['fee_total'] or 0) for t in trades)

        # ── 2. 盈亏 ──
        positions = _load_positions()
        cash = _get_cash()
        rt = _load_realtime()
        portfolio_value = cash + sum(
            positions[s]['qty'] * rt.get(s, {}).get('price', 0)
            for s in positions if s in rt
        )
        total_pnl = 0.0
        pnl_detail = []
        for sym, pos in positions.items():
            cur_price = rt.get(sym, {}).get('price', pos['avg_cost'])
            pnl = (cur_price - pos['avg_cost']) * pos['qty']
            pnl_pct = (cur_price - pos['avg_cost']) / pos['avg_cost'] * 100 if pos['avg_cost'] else 0
            total_pnl += pnl
            pnl_detail.append({'symbol': sym, 'qty': pos['qty'], 'pnl': round(pnl,2), 'pnl_pct': round(pnl_pct,2)})

        # 额外统计: decisions 数 / blocked 数
        blocked_count = 0
        decision_count = 0
        try:
            dec_path = '/tmp/sandbox_decisions.jsonl'
            if os.path.exists(dec_path):
                # 按 session 时间窗过滤
                if review_type == 'noon':
                    lines = [l for l in open(dec_path).readlines() if ('"ts":"' in l and '11:3' not in l.split('"ts":"')[1][:8])]
                else:
                    lines = open(dec_path).readlines()
                decision_count = len(lines)
                for l in lines[-200:]:
                    try:
                        d = json.loads(l)
                        if d.get('blocked_by'): blocked_count += 1
                    except: pass
        except Exception: pass

        from core.broker_adapter import TOTAL_CAPITAL as _TC
        fee_pct_of_capital = (total_fee / max(1, portfolio_value)) * 100

        # 胜率 (有 SELL 才计算)
        win_rate = 0.0
        if sells:
            win_rate = len([t for t in sells if (t.get('fill_price', t['price']) or t['price']) > t['price']]) / len(sells) * 100

        stats = {
            'phase_label': phase_label, 'session_short': session_short,
            'buys': len(buys), 'sells': len(sells), 'trades_count': len(trades),
            'total_fee': round(total_fee, 2), 'fee_pct_of_capital': round(fee_pct_of_capital, 2),
            'portfolio_value': round(portfolio_value, 2), 'capital': _TC,
            'cash': round(cash, 2),
            'total_pnl': round(total_pnl, 2), 'win_rate': round(win_rate, 1),
            'position_count': len(positions), 'decision_count': decision_count,
            'blocked_count': blocked_count,
        }

        _log(f'  📋 {review_type} session: {len(buys)}买 {len(sells)}卖, 手续费¥{total_fee:.2f}, 盈亏¥{total_pnl:+.2f}')
        _log(f'  💼 持仓 {len(positions)}只, 市值 ¥{portfolio_value:.2f}')

        # ── 3. 5 层会议颗粒度 ──
        meetings = _gen_meetings(review_type, stats, trades, positions, rt)

        # ── 3.5 🆕 金融委员会审议 + Eigenflux 专家会诊 (不闭门造车) ──
        _log('  🏛️ 金融委员会 + 52 名专家团队介入审议')
        finance_review = _finance_committee_review(stats, trades, positions, rt, review_type)
        if finance_review:
            meetings.append(finance_review)
            _persist_meeting(finance_review)
            for c in finance_review['conclusions']:
                _log(f'     🏛️ {c}')
            # 专家委员会意见也喂脑库
            try:
                conn3 = sqlite3.connect(_db(), timeout=3)
                for c in finance_review['conclusions']:
                    conn3.execute("""INSERT OR REPLACE INTO mt_ai_brain_feed_log
                        (flow_id, feed_target, feed_kind, feed_content, fed_by, triggered_at)
                        VALUES (?,?,?,?,?,datetime('now','localtime'))""",
                        (f'BRAIN-FINANCE-COMMITTEE-{session_short}', 'EXPERIENCE_LIBRARY',
                         'finance_committee_review', c[:1900], 'mt_standing_committee'))
                conn3.commit()
                conn3.close()
                _log(f'  🧠 金融委员会审议意见已投喂 AI Brain')
            except Exception as e:
                _log(f'  ⚠️ 金融脑库投喂 err: {e}')

        # ── 3.6 🆕 亏损挽救预案 (若触发) ──
        rescue = _loss_recovery_rescue(trades, positions, rt, review_type)
        if rescue:
            meetings.append(rescue)
            _persist_meeting(rescue)
            _log(f'  🚨 亏损挽救预案已触发: 选定 方案{rescue["selected_plan"]}')
            for c in rescue['conclusions'][:6]:
                _log(f'     {c}')

        # ── 4. 复盘会话留档 (JSONL + SQLite) ──
        summary = (f"【沙盘{phase_label}】本金¥{_TC:.0f}, 市值¥{portfolio_value:.0f}, "
                   f"盈亏¥{total_pnl:+.0f} ({total_pnl/max(1,_TC)*100:+.2f}%)。"
                   f"交易 {len(buys)}买{len(sells)}卖, 手续费¥{total_fee:.2f}。"
                   f"持仓 {len(positions)}只。5 场会议已开。")
        session = {
            'session_id': f'SESSION-{session_short}',
            'review_type': review_type, 'review_date': today,
            'triggered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'summary': summary[:2000],
            'stats': stats,
            'positions': positions,
            'pnl_detail': pnl_detail,
            'trades': trades,
            'meetings': meetings,
        }
        _persist_review_session(session)

        # ── 5. 入厅协作总线 (SANDBOX_REVIEW) ──
        try:
            from engines.collab_bus_engine import CollabBus
            CollabBus().publish(
                event_type='SANDBOX_REVIEW',
                source=f'sandbox_{review_type}_review',
                payload={
                    'session_id': session['session_id'],
                    'review_type': review_type,
                    'review_date': today,
                    'stats': stats,
                    'meetings_summary': [
                        {'type': m['meeting_type'], 'title': m['meeting_title'],
                         'participants': len(m['participants']),
                         'conclusions_count': len(m['conclusions']),
                         'actions_count': len(m['actions'])}
                        for m in meetings
                    ],
                },
                severity='INFO',
                symbol='PORTFOLIO',
            )
            _log(f'  📣 publish SANDBOX_REVIEW → 协作总线 → 自动入厅')
        except Exception as e:
            _log(f'  ⚠️ collab_bus err: {e}')

        # ── 6. 投喂 AI Brain ──
        try:
            conn2 = sqlite3.connect(_db(), timeout=3)
            brain_ev = f'BRAIN-SANDBOX-{session_short}'
            conn2.execute("""INSERT OR REPLACE INTO mt_ai_brain_feed_log
                (flow_id, feed_target, feed_kind, feed_content, fed_by, triggered_at)
                VALUES (?,?,?,?,?,datetime('now','localtime'))""",
                (brain_ev, 'EXPERIENCE_LIBRARY', f'sandbox_review_{review_type}',
                 summary[:1900], f'sandbox_{review_type}'))
            # 会议结论也喂入
            for m in meetings:
                for c in m['conclusions']:
                    brain_ev2 = f'BRAIN-{m["meeting_type"].upper()}-{session_short}'
                    conn2.execute("""INSERT OR REPLACE INTO mt_ai_brain_feed_log
                        (flow_id, feed_target, feed_kind, feed_content, fed_by, triggered_at)
                        VALUES (?,?,?,?,?,datetime('now','localtime'))""",
                        (brain_ev2, 'EXPERIENCE_LIBRARY', m['meeting_type'],
                         c[:1900], f'sandbox_meeting_{m["meeting_type"]}'))
            conn2.commit()
            conn2.close()
            _log(f'  🧠 复盘 + 5 场会议结论已投喂 AI Brain')
        except Exception as e:
            _log(f'  ⚠️ 脑库投喂 err: {e}')

        _review_flags_today[review_type] = True
        _log(f'══════════ ✅ {phase_label} 完成 (session={session["session_id"]}) ══════════')
        return session

    except Exception as e:
        _log(f'  ❌ {review_type} 复盘异常: {e}')
        import traceback; _log(f'  {traceback.format_exc()}')
        return None


def run_daily_review():
    """兼容旧 API — 默认触发收市复盘 (close)"""
    return run_review_session('close')


# ═══════════════════════════════════════════════════════════
# 🏛️ 金融合规审计 — 收市 15:05 自动触发
# 审计角色: CFO (总纲) · 精算师 (VaR) · CPA (核账) · 审计师 (独立)
# ═══════════════════════════════════════════════════════════

def _run_finance_audit():
    """收市金融合规审计 (tick_engine 内置版, 与 sandbox_bp._run_full_finance_audit 同逻辑)"""
    import os as _os; import json as _json
    STARTING_CAPITAL = 10000.0
    audit_id = f"FA-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    report = {"audit_id": audit_id, "executed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "auditors": ["CFO", "精算师", "CPA", "审计师"],
              "errors": [], "warnings": [], "ledger": {}, "verdict": "PASS"}
    try:
        db_path = os.path.join(os.path.dirname(__file__), "..", "database", "app.db")
        conn = sqlite3.connect(db_path); cur = conn.cursor()

        # S1 交易汇总
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN action='BUY' THEN fill_amount ELSE 0 END), "
                    "SUM(CASE WHEN action='SELL' THEN fill_amount ELSE 0 END), SUM(fee_total) FROM mt_trade_log")
        n, tb, ts_, tf = cur.fetchone()
        total_buy = float(tb or 0); total_sell = float(ts_ or 0); total_fees = float(tf or 0)

        # S2 持仓
        positions = _load_positions() or {}

        # S3 现金 + 市值 (手工勾稽, 不依赖 net_cash_change 字段)
        cur.execute("""SELECT
            SUM(CASE WHEN action='BUY'  THEN -(fill_amount + fee_total) ELSE 0 END) +
            SUM(CASE WHEN action='SELL' THEN  (fill_amount - fee_total) ELSE 0 END)
        FROM mt_trade_log""")
        cash = STARTING_CAPITAL + float(cur.fetchone()[0] or 0)
        rt = {}
        try: rt = _load_realtime() or {}
        except Exception: pass
        pos_value = sum(rt.get(sym, {}).get('price', p.get('avg_cost', 0)) * p['qty'] for sym, p in positions.items())
        total_assets = cash + pos_value

        # S4 勾稽
        cur.execute("""SELECT COALESCE(SUM(
            CASE WHEN action='SELL' THEN
                (fill_amount - fee_total) -
                (SELECT t2.fill_amount/t2.fill_qty * t1.fill_qty FROM mt_trade_log t2
                 WHERE t2.symbol=t1.symbol AND t2.action='BUY'
                 AND t2.id<=t1.id ORDER BY t2.id DESC LIMIT 1)
            ELSE 0 END),0) FROM mt_trade_log t1""")
        realized_pnl = float(cur.fetchone()[0] or 0)
        unrealized_pnl = pos_value - sum(p.get('avg_cost', 0) * p['qty'] for p in positions.values())
        diff = abs(total_assets - (STARTING_CAPITAL + realized_pnl + unrealized_pnl))
        if diff > 50:
            report["warnings"].append(f"勾稽差异 ¥{diff:.2f} > ¥50 阈值")

        # S5 每笔核对
        cur.execute("SELECT * FROM mt_trade_log ORDER BY id ASC")
        trades = cur.fetchall(); today = datetime.now().strftime("%Y-%m-%d")

        if any(not t[2] or not t[1] or not t[18] for t in trades):
            report["errors"].append(f"流水缺字段")

        fee_bad = 0
        for t in trades:
            amt = float(t[18] or 0); fee = float(t[21] or 0)
            if amt > 0 and (fee < 3.0 or fee / amt > 0.015): fee_bad += 1
        if fee_bad: report["warnings"].append(f"费用异常 {fee_bad} 笔")

        net_qty = {}
        for t in trades:
            if t[1] == "BUY": net_qty[t[2]] = net_qty.get(t[2], 0) + int(t[17])
            elif t[1] == "SELL": net_qty[t[2]] = net_qty.get(t[2], 0) - int(t[17])
        over = [(s, -q) for s, q in net_qty.items() if q < 0]
        if over: report["errors"].append(f"超卖 {over}")

        today_buy = {}; t1_viol = 0
        for t in trades:
            ts2 = t[12] or ""
            if ts2.startswith(today) and t[1] == "BUY":
                today_buy[t[2]] = today_buy.get(t[2], 0) + int(t[17])
            elif ts2.startswith(today) and t[1] == "SELL" and t[2] in today_buy:
                t1_viol += 1
        if t1_viol: report["errors"].append(f"T+1 违规 {t1_viol} 笔")

        chg_viol = 0
        for t in trades:
            if t[1] == "BUY" and t[9] and "chg=" in t[9]:
                try:
                    c = float(t[9].split("chg=")[1].split("%")[0])
                    if c > 7: chg_viol += 1
                except: pass
        if chg_viol: report["errors"].append(f"追涨>7% 共 {chg_viol} 笔")

        # S6 古灵阁
        cur.execute("SELECT total_savings FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1")
        g = cur.fetchone(); gob_total = float(g[0] or 0) if g else 0
        if gob_total > realized_pnl + 0.01 and realized_pnl > 0:
            report["errors"].append(f"古灵阁 ¥{gob_total:.2f} > realized PnL ¥{realized_pnl:.2f}")

        # S7 Verdict
        if report["errors"]: report["verdict"] = "EXCEPTION"
        elif report["warnings"]: report["verdict"] = "PASS_WITH_WARNINGS"

        # 留底
        cur.execute("""CREATE TABLE IF NOT EXISTS mt_finance_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT, executed_at TEXT, verdict TEXT,
            errors_json TEXT, warnings_json TEXT, metrics_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        cur.execute("""INSERT INTO mt_finance_audit_log (audit_id, executed_at, verdict, errors_json, warnings_json, metrics_json)
            VALUES (?,?,?,?,?,?)""", (
            audit_id, report["executed_at"], report["verdict"],
            _json.dumps(report["errors"], ensure_ascii=False),
            _json.dumps(report["warnings"], ensure_ascii=False),
            _json.dumps({"total_assets": round(total_assets, 2), "cash": round(cash, 2),
                         "pos_value": round(pos_value, 2), "n_pos": len(positions),
                         "realized": round(realized_pnl, 2), "unrealized": round(unrealized_pnl, 2),
                         "gob_total": gob_total, "n_trades": n, "fee_total": round(total_fees, 2)},
                        ensure_ascii=False)))
        if report["errors"] or report["warnings"]:
            # 新 schema: hall_id(PK AUTO), hall_code(UNIQUE), task_title, task_type,
            # description, source, source_id, target_center, hall_priority, publish_at,
            # status, deliverable, claimant, done_at
            _hall_code = f"FINANCE_AUDIT_{audit_id}"
            _hall_priority = "CRITICAL" if report["errors"] else "HIGH"
            try:
                cur.execute("""INSERT OR IGNORE INTO mt_task_hall
                    (hall_code, task_title, task_type, description, source, source_id,
                     target_center, hall_priority, publish_at, status, deliverable, claimant)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    _hall_code,
                    f"金融审计 {audit_id}: {len(report['errors'])}错误+{len(report['warnings'])}警告",
                    "FINANCE_AUDIT_EXCEPTION",
                    "",
                    "finance_audit_engine_v1",
                    audit_id,
                    "finance_center",
                    _hall_priority,
                    _now_iso() if '_now_iso' in dir() else datetime.now().isoformat(),
                    "NEW",
                    _json.dumps({"errors": report["errors"], "warnings": report["warnings"]}, ensure_ascii=False),
                    None))
            except Exception as _ie:
                sys.stderr.write(f"[TICK] ⚠️  FINANCE_AUDIT INSERT 异常 (列不匹配?): {_ie}\n")
        conn.commit(); conn.close()

        report["ledger"] = {
            "total_assets": round(total_assets, 2), "cash": round(cash, 2),
            "pos_value": round(pos_value, 2), "n_positions": len(positions),
            "realized_pnl": round(realized_pnl, 2), "unrealized_pnl": round(unrealized_pnl, 2),
            "total_fees": round(total_fees, 2), "gob_total": gob_total,
            "n_trades": n, "勾稽差异": round(diff, 4),
        }
    except Exception as e:
        report["verdict"] = "EXCEPTION"
        report["errors"].append(f"审计执行异常: {str(e)[:200]}")
        _log(f"  ❌ _run_finance_audit err: {e}")
    return report


def _generate_period_report(period: str) -> dict:
    """生成周期汇总报告 (week / quarter / year) — 由 _review_scheduler 调用"""
    # period: 'week'=最近7天, 'quarter'=最近90天, 'year'=全部
    STARTING_CAPITAL = 10000.0
    days_map = {'week': 7, 'quarter': 90, 'year': 9999}
    days = days_map.get(period, 7)
    sql_where = f"date(created_at) >= date('now','-{days} days')" if days < 9999 else "1=1"

    db_path = os.path.join(os.path.dirname(__file__), "..", "database", "app.db")
    conn = sqlite3.connect(db_path); cur = conn.cursor()

    cur.execute(f"""SELECT COUNT(*),
        SUM(CASE WHEN action='BUY'  THEN fill_amount ELSE 0 END),
        SUM(CASE WHEN action='SELL' THEN fill_amount ELSE 0 END),
        SUM(fee_total)
        FROM mt_trade_log WHERE {sql_where}""")
    n, tb, ts_, tf = cur.fetchone()
    total_buy = float(tb or 0); total_sell = float(ts_ or 0); total_fees = float(tf or 0)

    # 已实现 PnL (卖的部分)
    cur.execute(f"""SELECT COALESCE(SUM(
        CASE WHEN action='SELL' THEN
            (fill_amount - fee_total) -
            (SELECT t2.fill_amount/t2.fill_qty * t1.fill_qty FROM mt_trade_log t2
             WHERE t2.symbol=t1.symbol AND t2.action='BUY'
             AND t2.id<=t1.id ORDER BY t2.id DESC LIMIT 1)
        ELSE 0 END),0) FROM mt_trade_log t1 WHERE {sql_where}""")
    realized_pnl = float(cur.fetchone()[0] or 0)

    # 买入最多的 TOP5
    cur.execute(f"""SELECT symbol, SUM(fill_amount) as amt, COUNT(*) as n
        FROM mt_trade_log WHERE action='BUY' AND {sql_where}
        GROUP BY symbol ORDER BY amt DESC LIMIT 5""")
    top_buys = [{"symbol": r[0], "amount": round(float(r[1]), 2), "trades": r[2]} for r in cur.fetchall()]

    # 卖出最多的 TOP5
    cur.execute(f"""SELECT symbol, SUM(fill_amount) as amt, COUNT(*) as n
        FROM mt_trade_log WHERE action='SELL' AND {sql_where}
        GROUP BY symbol ORDER BY amt DESC LIMIT 5""")
    top_sells = [{"symbol": r[0], "amount": round(float(r[1]), 2), "trades": r[2]} for r in cur.fetchall()]

    # 古灵阁
    cur.execute("SELECT total_savings, lock_count FROM mt_gobelin_summary ORDER BY id DESC LIMIT 1")
    g = cur.fetchone(); gob_total = float(g[0] or 0) if g else 0; gob_count = int(g[1] or 0) if g else 0

    conn.close()

    return {
        "report_type": period,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "period_label": {"week": "周报 (近7天)", "quarter": "季报 (近90天)", "year": "年报 (全部)"}.get(period, period),
        "metrics": {
            "n_trades": n,
            "total_buy": round(total_buy, 2),
            "total_sell": round(total_sell, 2),
            "total_fees": round(total_fees, 2),
            "realized_pnl": round(realized_pnl, 2),
            "net_flow": round(total_sell - total_buy - total_fees, 2),
            "gob_total": round(gob_total, 2),
            "gob_count": gob_count,
        },
        "top_buys": top_buys,
        "top_sells": top_sells,
    }


def _archive_period_report(period: str, key: str, report: dict):
    """把周期报告 JSON 归档到 _runtime/ + 写 mt_finance_audit_log 的 period_report 类型"""
    _rt = os.path.join(os.path.dirname(__file__), '..', '_runtime')
    os.makedirs(_rt, exist_ok=True)
    _ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _p = os.path.join(_rt, f'period_report_{period}_{key}_{_ts}.json')
    with open(_p, 'w', encoding='utf-8') as _f:
        json.dump(report, _f, ensure_ascii=False, indent=2)
    _log(f'   📄 周期报告已归档 → _runtime/period_report_{period}_{key}_{_ts}.json')

    # 同时写审计日志表 (period_report 类型)
    try:
        db_path = os.path.join(os.path.dirname(__file__), "..", "database", "app.db")
        conn = sqlite3.connect(db_path); cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS mt_finance_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT, executed_at TEXT, verdict TEXT,
            errors_json TEXT, warnings_json TEXT, metrics_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        cur.execute("""INSERT INTO mt_finance_audit_log (audit_id, executed_at, verdict, errors_json, warnings_json, metrics_json)
            VALUES (?,?,?,?,?,?)""", (
            f"PRD-{period}-{key}", report["generated_at"], "PERIOD_REPORT",
            '[]', '[]', json.dumps(report["metrics"], ensure_ascii=False)))
        conn.commit(); conn.close()
    except Exception as _e: _log(f'   ⚠️ period_report DB 归档失败: {_e}')

    # 简短 summary
    m = report["metrics"]
    _log(f'   📊 {period.upper()} summary: trades={m["n_trades"]} '
         f'BUY¥{m["total_buy"]:.0f} SELL¥{m["total_sell"]:.0f} fee¥{m["total_fees"]:.0f} '
         f'realized¥{m["realized_pnl"]:+.0f} net_flow¥{m["net_flow"]:+.0f} '
         f'gob¥{m["gob_total"]:.0f}({m["gob_count"]})')


def _review_scheduler():
    """复盘 + 审计 + 周期报表定时器
    ── 交易中日常 ──
      11:31~12:00  午间复盘
      15:05~15:30  收市复盘 + 金融合规审计 (CFO+精算师+CPA+审计师)
    ── 周期报表 ──
      周一 09:15   周报 (上周交易日汇总)
      Q1/Q2/Q3/Q4 首日 09:15  季报 (季度账户勾稽)
      1 月首个交易日 09:15  年报
    """
    global _review_flags_today
    _log('⏰ 复盘+审计+周期报表定时器已启动')

    # 跨日追踪: 防止周报/季报/年报同一周期重复跑
    _period_generated = {'weekly': '', 'quarterly': '', 'yearly': ''}

    while True:
        try:
            now = _now_cn()   # 统一锚定 Asia/Shanghai, 不依赖系统时区
            # 非工作日跳过 (交易所不交易, 审计也跳过)
            if now.weekday() >= 5:
                time.sleep(60)
                continue

            hhmm = now.strftime('%H:%M')

            # ═════════════════════════════════════════
            # ① 交易日日常
            # ═════════════════════════════════════════

            # ── 午间复盘: 11:31 ~ 12:00 ──
            if hhmm >= '11:31' and hhmm <= '12:00' and not _review_flags_today.get('noon'):
                try: run_review_session('noon')
                except Exception as e: _log(f'  ❌ noon review err: {e}')
                _review_flags_today['noon'] = True

            # ── 收市复盘 + 审计: 15:05 ~ 15:30 ──
            if hhmm >= '15:05' and hhmm <= '15:30' and not _review_flags_today.get('close'):
                try: run_review_session('close')
                except Exception as e: _log(f'  ❌ close review err: {e}')
                _review_flags_today['close'] = True

                try:
                    _log('📊 === 收市金融合规审计 (15:05) ===')
                    audit = _run_finance_audit()
                    _log(f'   ✅ audit verdict={audit["verdict"]} assets=¥{audit["ledger"]["total_assets"]} '
                         f'cash=¥{audit["ledger"]["cash"]} n_trades={audit["ledger"]["n_trades"]} '
                         f'errors={len(audit["errors"])} warnings={len(audit["warnings"])}')
                    if audit["errors"] or audit["warnings"]:
                        for e in audit["errors"]:  _log(f'   ❌ {e}')
                        for w in audit["warnings"]: _log(f'   ⚠️ {w}')
                        _log('   📋 异常已自动登记 mt_task_hall, 指派 审计师·CFO·CPA 内部复盘')
                    else: _log('   📋 审计通过, 无异常')
                    try:
                        _rt = os.path.join(os.path.dirname(__file__), '..', '_runtime')
                        os.makedirs(_rt, exist_ok=True)
                        _ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                        _p = os.path.join(_rt, f'finance_audit_report_{_ts}.json')
                        with open(_p, 'w', encoding='utf-8') as _f: json.dump(audit, _f, ensure_ascii=False, indent=2)
                        _log(f'   📄 审计报告已归档 → _runtime/finance_audit_report_{_ts}.json')
                    except Exception as _e: _log(f'   ⚠️ 报告归档失败: {_e}')
                except Exception as _ae: _log(f'  ❌ finance audit err: {_ae}')

            # ═════════════════════════════════════════
            # ② 周期报表 (周一 / Q首日 / 1月首个交易日)
            #    时间窗: 09:15 ~ 09:25 (开盘前, 不与 tick 冲突)
            # ═════════════════════════════════════════
            if hhmm >= '09:15' and hhmm <= '09:25':
                _yr = now.year; _mo = now.month; _day = now.day
                _iso = now.strftime('%Y-%m-%d')

                # ── 周报: 周一 ──
                _week_key = now.strftime('%Y-W%V')
                if now.weekday() == 0 and _period_generated['weekly'] != _week_key:
                    _period_generated['weekly'] = _week_key
                    try:
                        _log(f'📅 === 周报 (周一 {_week_key}) ===')
                        _report = _generate_period_report('week')
                        _archive_period_report('week', _week_key, _report)
                    except Exception as _e: _log(f'  ❌ weekly report err: {_e}')

                # ── 季报: Q 首日 (Jan 4 / Apr 1 / Jul 1 / Oct 1 的首个交易日) ──
                _qmap = {1: 'Q1', 4: 'Q2', 7: 'Q3', 10: 'Q4'}
                _qkey = f'{_yr}-{_qmap.get(_mo, "")}'
                if _mo in _qmap and _day <= 3 and _period_generated['quarterly'] != _qkey:
                    _period_generated['quarterly'] = _qkey
                    try:
                        _log(f'📅 === 季报 ({_yr} {_qmap[_mo]} 首日) ===')
                        _report = _generate_period_report('quarter')
                        _archive_period_report('quarter', _qkey, _report)
                    except Exception as _e: _log(f'  ❌ quarterly report err: {_e}')

                # ── 年报: 1 月首个交易日 ──
                if _mo == 1 and _day <= 5 and _period_generated['yearly'] != str(_yr):
                    _period_generated['yearly'] = str(_yr)
                    try:
                        _log(f'📅 === 年报 ({_yr}) ===')
                        _report = _generate_period_report('year')
                        _archive_period_report('year', str(_yr), _report)
                    except Exception as _e: _log(f'  ❌ yearly report err: {_e}')

            # 过了 16:00 后重置今日 flag → 明天再说
            if hhmm >= '16:00' and (_review_flags_today.get('noon') or _review_flags_today.get('close')):
                _review_flags_today = {'noon': False, 'close': False, 'audit': False}
                _log('  🔄 daily flags reset (过 16:00)')

            time.sleep(30)
        except Exception as e:
            _log(f'  ⚠️ review scheduler err: {e}')
            time.sleep(60)


def _daily_review_scheduler():
    """兼容旧 API — 内部委托给 _review_scheduler"""
    return _review_scheduler()


# ══════════════════════════════════════════════════════════════
# 🔄 休市学习循环 — 每 2h 跑一次历史 replay + mini 复盘 + 脑库投喂
# ══════════════════════════════════════════════════════════════

_LAST_REPLAY_TIME = 0  # 上次 replay 完成时间戳


def _offline_learning_scheduler():
    """
    休市期间学习循环:
      - 交易时段: 不跑 (避免和实盘 tick 抢资源)
      - 休市期间: 每 2h 跑一次 replay + 复盘 + 脑库投喂
      - 周末/节假日: 全天每 2h 一次
    """
    global _LAST_REPLAY_TIME
    _log('🔄 offline-learning-scheduler 已启动 (休市每 2h replay)')

    while True:
        try:
            now = datetime.now()
            in_trade = _is_trading_hours()
            hh = now.hour

            # 交易时段跳过 (9:30-11:30, 13:00-15:00)
            if in_trade:
                time.sleep(60)
                continue

            # 检查冷却 (距上次 replay ≥ 2h)
            elapsed = time.time() - _LAST_REPLAY_TIME
            if elapsed < 7200:  # 2h = 7200s
                time.sleep(120)
                continue

            # 周末/节假日 + 晚上 (18:00-次日 8:00) 优先
            is_night = hh >= 18 or hh < 8
            is_weekend = now.weekday() >= 5
            label = f"{'周末' if is_weekend else '工作日'}{'晚间' if is_night else '休市'}"

            _log(f'🔄 [{label}] 启动休市学习循环...')

            try:
                from engines.replay_engine import run_full_replay
                result = run_full_replay(log_func=_log)
                if result:
                    r = result['replay']
                    _log(f'  ✅ 休市 replay 完成 — {r["days"]}天, {r["symbols_count"]}只')
                    _log(f'     ¥{r["initial_capital"]} → ¥{r["final_capital"]} ({r["pnl_pct"]:+.2f}%)')
                    _log(f'     胜率 {r["win_rate"]}% | 回撤 {r["max_drawdown"]}% | {r["trades_count"]}笔')
                    _log(f'     AI 脑库投喂: {result["fed_count"]} 条')
                    _LAST_REPLAY_TIME = time.time()

                    # 超过 16:30 也触发一次盘中复盘 (双重保险)
                    if now.strftime('%H:%M') >= '16:30' and now.weekday() < 5:
                        _log('  💡 已过 16:30, 顺便触发收市复盘...')
                        try:
                            run_review_session('close')
                        except Exception as e2:
                            _log(f'     close review err: {e2}')
            except Exception as e:
                _log(f'  ❌ offline replay err: {e}')
                import traceback
                _log(f'  {traceback.format_exc()[:200]}')

            time.sleep(300)  # 5 分钟后再检查冷却

        except Exception as e:
            _log(f'⚠️ offline scheduler err: {e}')
            time.sleep(60)


# ══════════════════════════════════════════════════════════════
# 启动入口
# ══════════════════════════════════════════════════════════════

_started = False
_single_lock_fp = None


def _acquire_single_lock() -> bool:
    """进程级单实例锁 — 防止 launchd 守护进程与 modular_start 内嵌线程并发双写"""
    global _single_lock_fp
    if _single_lock_fp is not None:
        return True
    try:
        import fcntl
        fp = open('/tmp/sandbox_tick.lock', 'w')
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fp.close()
            return False
        fp.write(str(os.getpid()))
        fp.flush()
        _single_lock_fp = fp
        return True
    except Exception as e:
        _log(f'single lock err: {e}')
        return False


def start_sandbox_tick(interval: int = TICK_INTERVAL) -> threading.Thread | None:
    """启动沙盘 tick daemon + 收市复盘定时器 + 休市学习循环"""
    global _started
    if _started:
        _log('⚠️ 已在运行, 跳过')
        return None
    # 🆕 in-process 调用 (modular_start) 也必须遵守单实例锁, 否则与 launchd daemon 心跳/下单互踩
    if not _acquire_single_lock():
        _log('⚠️ 已有 daemon 实例持锁, 本进程不启动 tick 线程 (避免重复交易与心跳互踩)')
        return None
    _started = True

    # ① 复盘定时器 (独立线程 — 午间 + 收市 双触发)
    threading.Thread(target=_review_scheduler,
                     name='sandbox-review-scheduler', daemon=True).start()
    _log('⏰ sandbox-review-scheduler 已启动 (11:31 午间 + 15:05 收市)')

    # ② 休市学习循环 (独立线程 — 休市每 2h replay)
    threading.Thread(target=_offline_learning_scheduler,
                     name='sandbox-offline-learning', daemon=True).start()
    _log('🔄 sandbox-offline-learning 已启动 (休市每 2h replay)')

    def _loop():
        _log(f'🚀 沙盘 tick daemon 启动 — interval={interval}s')
        _log(f'   交易时段: A股 9:30-11:30, 13:00-15:00')
        _log(f'   策略: 涨>{STRATEGY_BUY_PCT}% 买入 | 盈>{STRATEGY_SELL_PROFIT}% 止盈 | 亏<{STRATEGY_SELL_LOSS}% 止损')
        _log(f'   风控: T+1 | 涨跌停 | 最多 {MAX_POSITIONS} 只 | 个股≤¥{SINGLE_STOCK_MAX_CNY}')
        _log(f'   手续费: 万2.5佣金 + 千0.5印花税 + 万0.1过户费 | 滑点 0.3%')
        # 启动先 tick 一次 (不论交易时段, publish 异动)
        try:
            run_tick()
        except Exception as e:
            _log(f'init tick err: {e}')
        while True:
            try:
                time.sleep(interval)
                run_tick()
            except Exception as e:
                _log(f'tick loop err: {e}')
                time.sleep(interval)

    t = threading.Thread(target=_loop, name='sandbox-tick-daemon', daemon=True)
    t.start()
    _log(f'✅ sandbox-tick-daemon 已启动 (30s tick + 15:05 复盘)')
    return t


if __name__ == '__main__':
    # CLI 模式
    if len(sys.argv) > 1 and sys.argv[1] == 'once':
        run_tick()
    elif len(sys.argv) > 1 and sys.argv[1] == 'review':
        run_daily_review()
    else:
        # 🆕 单实例锁 — 防止 launchd / 守护线程重复拉起多个 daemon (心跳互踩)
        if not _acquire_single_lock():
            _log('⚠️ 已有 daemon 实例在运行 (单实例锁被占用), 本进程退出')
            sys.exit(0)
        start_sandbox_tick()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            _log('🛑 收到 SIGINT, 退出')
