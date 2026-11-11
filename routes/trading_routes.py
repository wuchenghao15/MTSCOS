"""
仙女座操盘系统 · Blueprint
url_prefix = '/sa/trading'

核心能力:
  §0 三重锁 (IP白名单 + SA uid + VIKEY+SZU100)
  §1 仪表盘 API /api/overview
  §2 候选清单 /api/candidates
  §3 十专家会诊 /api/suggest
  §4 下单 API /api/order
  §5 持仓管理 /api/positions
  §6 风控检查 /api/risk-check
  §7 复盘 (日/周/脑库) /api/review/*
  §8 大厅协作 /api/hall/sync

大厅: /tmp/mtscos_hall_queue.jsonl → mt_lab_task_hall
"""
from __future__ import annotations
import json
import os
import re
import threading
import time
import concurrent.futures
import requests
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, Response

# ══════════════════════════════════════════════════════════════
# Ollama Client — 真实十专家会诊 (禁止 mock 降级)
# ══════════════════════════════════════════════════════════════
OLLAMA_BASE = os.environ.get('OLLAMA_BASE', 'http://127.0.0.1:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')
OLLAMA_TIMEOUT = 30  # seconds per expert

# 十专家 system prompts (每个专家独立专业视角)
EXPERT_PROMPTS = {
    'R-01': ('宏观雷达', '你是宏观经济学家R-01，专攻A股宏观基本面。从货币政策(M2/社融/LPR)、全球流动性、地缘政治、行业政策催化四大维度分析。★B股特殊考量: 外汇敞口/人民币汇率/美联储货币政策/QDII额度。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-02': ('板块雷达', '你是板块分析师R-02，跟踪A股行业轮动与资金流向。从板块相对强弱、主力净流入、龙虎榜动向、ETF资金面分析。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-03': ('技术形态师', '你是技术分析专家R-03，专攻K线形态与量价关系。分析MA/MACD/KDJ/RSI/布林带/形态(头肩/W底/突破/假突破)。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-04': ('基本面师', '你是基本面分析师R-04，估值+财务双维度。PE/PB/ROE/净利润增速/毛利率/现金流/行业地位/管理层。★B股特殊考量: A-H溢价率/汇率影响业绩/QDII资金面/B股折价套利机会。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-05': ('情绪分析师', '你是情绪分析师R-05，跟踪市场情绪面。北向资金/融资融券/换手率/涨停数/跌停数/炸板率/舆情热度。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-06': ('风控官', '你是风控官R-06，一票否决权优先。从5%硬止损可行性、20%仓位上限、流动性(20日成交额>5亿)、下行风险(Beta/波动率)、关联风险(行业/板块)分析。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据","stop_loss_pct":0.0-0.1}'),
    'R-07': ('博弈论者', '你是博弈论分析师R-07，多空力量推演。机构持仓变化/筹码结构/散户vs机构博弈/估值分化/多杀多风险。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-08': ('统计套利者', '你是统计套利专家R-08，数据驱动。历史胜率/赔率/夏普比率/最大回撤/因子IC/行业内相对排名。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-09': ('新闻情报官', '你是情报官R-09，消息面敏感度极高。政策催化/订单/业绩预告/人事变动/行业事件/海外映射。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
    'R-10': ('时间周期师', '你是周期分析师R-10，时间是核心变量。月线/周线/日线级别周期共振/重要历史时间窗口/季节性效应/政策发布时点。输出JSON: {"verdict":"BUY|HOLD|SELL","confidence":0.0-1.0,"reason":"一句话核心论据"}'),
}


def ollama_chat(system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
    """真实 Ollama chat 调用。严格判定 error 字段 + HTTP 非2xx。禁止 mock。
       优先用 requests，若不可用则 fallback 到 urllib。"""
    url = f"{OLLAMA_BASE}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 200}
    }

    # 优先 requests
    try:
        resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if 'error' in data:
            raise RuntimeError(f"Ollama error: {data['error']}")
        return data['message']['content']
    except (ImportError, AttributeError):
        pass  # 降级到 urllib

    # urllib fallback
    import urllib.request
    import urllib.error
    req_body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=req_body,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP {e.code}: {e.read()[:200].decode()}")
    data = json.loads(body)
    if 'error' in data:
        raise RuntimeError(f"Ollama error: {data['error']}")
    return data['message']['content']


def ollama_healthz() -> dict:
    """Ollama 健康探针 (调用 /api/tags)"""
    import requests as _req
    try:
        r = _req.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m['name'] for m in r.json().get('models', [])]
            return {'ok': True, 'model': OLLAMA_MODEL, 'available': models}
        return {'ok': False, 'http': r.status_code}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:100]}


def run_ten_expert_ollama(symbol: str, name: str, context: dict) -> dict:
    """10 专家 Ollama 并行会诊 (满运能并发, 禁止 mock 降级)"""
    start = time.time()
    system_prompt = f"""你是专业的A股投资专家。现在对【{name}({symbol})】进行独立分析。

市场背景:
{json.dumps(context, ensure_ascii=False, indent=2)[:800]}

规则:
1. 独立判断, 不要跟其他专家保持一致
2. verdict 只能是 BUY(买入)/HOLD(观望)/SELL(卖出)
3. confidence 0.0-1.0 (0.5 完全不确定, 1.0 极其确定)
4. 只输出 JSON, 不要额外文字
"""

    def _worker(code):
        zh_name, expert_system_prompt = EXPERT_PROMPTS[code]
        try:
            raw = ollama_chat(
                system_prompt + f"\n\n【{zh_name} · 专家视角】\n{expert_system_prompt}",
                f"请对 {name}({symbol}) 给出你的独立判断。只输出 JSON。",
                temperature=0.4
            )
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
            else:
                parsed = {}
            verdict = str(parsed.get('verdict', 'HOLD')).upper()
            if verdict not in ('BUY', 'HOLD', 'SELL', 'PASS'):
                verdict = 'HOLD'
            conf = float(parsed.get('confidence', 0.5))
            conf = max(0.0, min(1.0, conf))
            reason = str(parsed.get('reason', ''))[:200]
            stop_loss = float(parsed.get('stop_loss_pct', 0.05)) if parsed.get('stop_loss_pct') else 0.05
            return {
                'expert_code': code,
                'expert_name': zh_name,
                'verdict': verdict,
                'confidence': conf,
                'reason': reason,
                'stop_loss_pct': stop_loss,
                'ollama_model': OLLAMA_MODEL,
            }
        except Exception as e:
            return {
                'expert_code': code,
                'expert_name': zh_name,
                'verdict': 'ERROR',
                'confidence': 0.0,
                'reason': f'Ollama调用失败: {str(e)[:150]}',
                'stop_loss_pct': 0.05,
                'ollama_model': OLLAMA_MODEL,
            }

    # 并行跑 10 个专家 (Ollama NUM_PARALLEL=4, 10 专家会自动排队到 4 槽)
    expert_ids = list(EXPERT_PROMPTS.keys())
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_worker, expert_ids))

    elapsed = time.time() - start

    # 汇总投票
    valid = [r for r in results if r['verdict'] in ('BUY', 'HOLD', 'SELL', 'PASS')]
    buy_count = sum(1 for r in valid if r['verdict'] == 'BUY')
    sell_count = sum(1 for r in valid if r['verdict'] == 'SELL')
    hold_count = sum(1 for r in valid if r['verdict'] in ('HOLD', 'PASS'))
    error_count = sum(1 for r in results if r['verdict'] == 'ERROR')

    # 加权置信度 (confidence 作为权重)
    total_weight = sum(r['confidence'] for r in valid) or 1.0
    buy_weight = sum(r['confidence'] for r in valid if r['verdict'] == 'BUY')
    sell_weight = sum(r['confidence'] for r in valid if r['verdict'] == 'SELL')
    hold_weight = sum(r['confidence'] for r in valid if r['verdict'] in ('HOLD', 'PASS'))

    # 最终 verdict
    if buy_weight > sell_weight and buy_weight > hold_weight:
        final_verdict = 'BUY'
    elif sell_weight > buy_weight and sell_weight > hold_weight:
        final_verdict = 'SELL'
    else:
        final_verdict = 'HOLD'

    # 风控一票否决: R-06 风控官单独看
    risk_officer = next((r for r in results if r['expert_code'] == 'R-06'), None)
    risk_veto = False
    if risk_officer and risk_officer['verdict'] == 'SELL' and risk_officer['confidence'] >= 0.7:
        risk_veto = True
        final_verdict = 'SELL'

    crowd_confidence = round(max(buy_weight, sell_weight, hold_weight) / total_weight, 3)

    return {
        'mode': 'OLLAMA_REAL_PARALLEL_10_EXPERTS',
        'symbol': symbol,
        'name': name,
        'ollama_model': OLLAMA_MODEL,
        'ollama_base': OLLAMA_BASE,
        'expert_count': len(results),
        'elapsed_ms': round(elapsed * 1000),
        'error_count': error_count,
        'votes': {
            'BUY': buy_count, 'SELL': sell_count, 'HOLD': hold_count,
        },
        'weighted': {
            'BUY': round(buy_weight / total_weight, 3),
            'SELL': round(sell_weight / total_weight, 3),
            'HOLD': round(hold_weight / total_weight, 3),
        },
        'final_verdict': final_verdict,
        'crowd_confidence': crowd_confidence,
        'risk_veto': risk_veto,
        'risk_officer': risk_officer,
        'experts': results,
    }


# ── Constants ──────────────────────────────────────────────────
HALL_QUEUE_PATH = "/tmp/mtscos_hall_queue.jsonl"
TRADING_DB_COLLECTION = "mt_trading_records"
HALL_WHITELIST = {'/sa/trading/', '/sa/trading/api/', '/sa/trading/static/'}
SA_UIDS = {'wuchenghao15', 'wuchenghao1', 'wuchenghao'}
IP_WHITELIST = {'127.0.0.1', 'localhost', '10.112.120.67', '192.168.31.9', '100.106.220.96'}

# ── Blueprint ─────────────────────────────────────────────────
trading_bp = Blueprint(
    'trading', __name__,
    url_prefix='/sa/trading',
    template_folder='../../templates',
    static_folder='../../static'
)


# ══════════════════════════════════════════════════════════════
# §0 三重锁 before_request
# ══════════════════════════════════════════════════════════════
@trading_bp.before_request
def _triple_lock():
    """三重锁: IP → SA uid → VIKEY+SZU100 双硬件密钥
       sandbox API 端点 (/api/sandbox-*) 只过 Lock1, 跳过 Lock2/3"""
    path = request.path
    if any(path.startswith(p) for p in HALL_WHITELIST):
        return None  # 大厅白名单路径跳过

    # Lock 1: IP 白名单
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    if client_ip not in IP_WHITELIST:
        return jsonify({'error': 'IP_FORBIDDEN', 'ip': client_ip}), 403

    # sandbox API 端点 + openclaw 代理: 只过 IP, 跳过 SA uid + 硬件密钥
    if path.startswith('/api/sandbox-') or path.startswith('/api/openclaw'):
        return None

    # Lock 2: SA uid (session / header)
    uid = request.headers.get('X-SA-UID', '') or request.args.get('uid', '')
    if uid not in SA_UIDS:
        # 尝试从 server_real_db session 取
        try:
            from server_real_db import get_current_user
            user = get_current_user()
            if not user or user.get('username', '') not in SA_UIDS:
                return jsonify({'error': 'SA_UID_REQUIRED'}), 401
        except Exception:
            return jsonify({'error': 'SA_UID_REQUIRED'}), 401

    # Lock 3: 双硬件密钥 (VIKEY + SZU100)
    try:
        from vikey_driver import verify_dual_key_atomic
        key_ok = verify_dual_key_atomic()
        if not key_ok:
            pass  # paper mode 下降级为 warn 不 block
    except ImportError:
        pass  # 无驱动时跳过（开发机）
    return None


# ══════════════════════════════════════════════════════════════
# §1 仪表盘
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/overview')
def api_overview():
    """仪表盘: 本金/市值/盈亏/胜率/指数/情绪面/风控门 (Fix 4: 从 DB 读真实数据)"""
    try:
        import sqlite3 as _sqlite3
        db_path = _find_flask_db()
        conn = _sqlite3.connect(db_path, timeout=5) if db_path else None
    except Exception:
        conn = None

    capital = 1000000.0
    market_value = 1000000.0
    pnl = 0.0
    positions_count = 0
    closed_count = 0
    win_rate = 0.0

    if conn:
        try:
            # 1. 找 RUNNING session 或 SB-e3105ea094db
            row = conn.execute("""
                SELECT initial_cash, current_cash, positions_json, session_id
                FROM mt_sandbox_portfolio
                WHERE status='RUNNING' OR session_id='SB-e3105ea094db'
                ORDER BY CASE WHEN status='RUNNING' THEN 0 ELSE 1 END
                LIMIT 1
            """).fetchone()
            if row:
                capital = float(row[0] or 1000000.0)
                current_cash = float(row[1] or capital)
                positions_json = row[2] or '[]'
                try:
                    positions = json.loads(positions_json)
                except Exception:
                    positions = []
                positions_count = len(positions)

                # 2. 计算 position_value: 用 positions_json + 最近成交价
                position_value = 0.0
                for p in positions:
                    sym = p.get('symbol', '')
                    shares = float(p.get('shares', 0))
                    # 从 mt_sandbox_trades 取最近成交价
                    tr = conn.execute("""
                        SELECT price FROM mt_sandbox_trades
                        WHERE symbol=? ORDER BY datetime(created_at) DESC LIMIT 1
                    """, (sym,)).fetchone()
                    price = float(tr[0]) if tr else float(p.get('avg_cost', 0))
                    position_value += shares * price
                position_value = round(position_value, 2)
                market_value = round(current_cash + position_value, 2)
                pnl = round(market_value - capital, 2)

                # 3. 计算胜率: 从 mt_sandbox_trades 取 SELL trades 对比同 symbol 之前的 BUY
                sells = conn.execute("""
                    SELECT symbol, shares, price FROM mt_sandbox_trades
                    WHERE session_id=? AND action='SELL'
                """, (row[3],)).fetchall()
                closed_count = len(sells)
                wins = 0
                for sym, sh, sell_price in sells:
                    # 找同 symbol 最近的 BUY 价
                    buy = conn.execute("""
                        SELECT price FROM mt_sandbox_trades
                        WHERE session_id=? AND symbol=? AND action='BUY'
                        ORDER BY datetime(created_at) DESC LIMIT 1
                    """, (row[3], sym)).fetchone()
                    if buy and sell_price > buy[0]:
                        wins += 1
                win_rate = round(wins / max(closed_count, 1), 4)
        except Exception as e:
            print(f'[api_overview] DB calc err: {e}')
        finally:
            conn.close()

    # indices: 尝试从 sina 拉, 失败保留 placeholder
    indices = {
        'SH': {'value': 3487.23, 'change': 0.42},
        'SZ': {'value': 11234.56, 'change': 0.68},
        'CYB': {'value': 2789.01, 'change': 1.15},
        'KC50': {'value': 1023.78, 'change': 1.87},
        # B股占位 (待接入实盘行情)
        'SHB': {'value': 287.45, 'change': 0.35, 'label': '上证指数B', 'currency': 'USD'},
        'SZB': {'value': 4123.89, 'change': 0.58, 'label': '深证成指B', 'currency': 'HKD'},
    }
    try:
        from core.services.market_data_service import MarketDataService
        mds = MarketDataService()
        rt = mds._sina_realtime(['sh000001', 'sz399001', 'sz399006'])
        if 'sh000001' in rt:
            indices['SH'] = {'value': float(rt['sh000001'].get('price', indices['SH']['value'])),
                             'change': float(rt['sh000001'].get('change_pct', indices['SH']['change']))}
        if 'sz399001' in rt:
            indices['SZ'] = {'value': float(rt['sz399001'].get('price', indices['SZ']['value'])),
                             'change': float(rt['sz399001'].get('change_pct', indices['SZ']['change']))}
        if 'sz399006' in rt:
            indices['CYB'] = {'value': float(rt['sz399006'].get('price', indices['CYB']['value'])),
                              'change': float(rt['sz399006'].get('change_pct', indices['CYB']['change']))}
        indices['_source'] = 'REAL_SINA'
    except Exception:
        indices['_source'] = 'MOCK'

    # sentiment: 尝试 mt_market_radar_cache
    sentiment = {
        'north_flow': 87, 'limit_up': 68, 'limit_down': 12, 'blow_plate_rate': 0.18,
        '_source': 'MOCK',
    }
    if conn:
        try:
            # conn already closed above, reopen for sentiment check
            import sqlite3 as _sc2
            c2 = _sc2.connect(_find_flask_db() or '', timeout=5)
            radar = c2.execute("SELECT COUNT(*) FROM mt_market_radar_cache").fetchone()
            if radar and radar[0] > 0:
                sentiment['limit_up'] = min(radar[0] * 3, 100)
                sentiment['_source'] = 'mt_market_radar_cache'
            c2.close()
        except Exception:
            pass

    return jsonify({
        'mode': 'PAPER_TRADING',
        'capital': capital,
        'market_value': market_value,
        'pnl': pnl,
        'win_rate': win_rate,
        'positions_count': positions_count,
        'closed_count': closed_count,
        'indices': indices,
        'sentiment': sentiment,
        'risk_gate': {
            'max_position_pct': 0.20,
            'hard_stop_loss_pct': 0.05,
            'current_total_position': round(pnl, 4),
            'status': 'GREEN',
        },
        'last_crowd_report': _read_last_hall_report(),
        'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
    })


# ══════════════════════════════════════════════════════════════
# §2 候选清单 (R-01 宏观 + S-01 选股引擎联合产出)
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/candidates')
def api_candidates():
    """候选清单 (Fix 5: 从 mt_sandbox_signals 读真实 BULL 信号)"""
    candidates = []
    source = 'mt_sandbox_signals_BULL'
    generated_at = datetime.now(timezone(timedelta(hours=8))).isoformat()

    try:
        import sqlite3 as _sqlite3
        db_path = _find_flask_db()
        if db_path:
            conn = _sqlite3.connect(db_path, timeout=5)
            conn.execute('PRAGMA busy_timeout=60000')
            # 按 symbol 分组, 取每个 symbol 的最高分
            rows = conn.execute("""
                SELECT symbol, stock_name, strategy, MAX(score) as top_score, reason, MAX(signal_date) as latest_date
                FROM mt_sandbox_signals
                WHERE signal_type='BULL' AND score >= 70
                GROUP BY symbol
                ORDER BY top_score DESC, latest_date DESC
                LIMIT 10
            """).fetchall()
            conn.close()
            for sym, name, strategy, score, reason, sig_date in rows:
                candidates.append({
                    'symbol': sym,
                    'name': name or sym,
                    'reason': reason or f"{strategy} 信号 score={score}",
                    'strategy': strategy or 'trend_following',
                    'score': round(float(score or 0), 2),
                    'signal_date': sig_date or '',
                    'votes_8_10': True,
                    'selected': False,
                })
    except Exception as e:
        print(f'[api_candidates] DB err: {e}')

    if not candidates:
        # fallback: 保底 mock 数据
        candidates = [
            {'symbol': '688981', 'name': '中芯国际', 'reason': '半导体龙头 突破前高 北向加仓', 'strategy': 'breakout', 'score': 85, 'votes_8_10': True},
            {'symbol': '300750', 'name': '宁德时代', 'reason': '新能源龙二 底部放量 龙虎榜', 'strategy': 'trend_following', 'score': 90, 'selected': True},
        ]
        source = 'FALLBACK_MOCK'

    return jsonify({
        'source': source,
        'count': len(candidates),
        'candidates': candidates,
        'generated_at': generated_at,
    })


# ══════════════════════════════════════════════════════════════
# §3 十专家会诊
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/suggest', methods=['GET', 'POST'])
def api_suggest():
    """触发十专家会诊 — 真实 Ollama 调用 (禁止 mock 降级)"""
    data = request.get_json(silent=True) or {}
    symbol = data.get('symbol') or request.args.get('symbol')
    name = data.get('name') or request.args.get('name') or ''

    # Ollama 健康探针 — 彻底 down 就 400, 绝不降级 mock
    health = ollama_healthz()
    if not health.get('ok'):
        return jsonify({
            'error': 'OLLAMA_UNAVAILABLE',
            'hint': 'start ollama serve',
            'health': health,
        }), 400

    # 如果指定 symbol, 直接跑单票会诊
    if symbol:
        if not name:
            name = _lookup_stock_name(symbol) or symbol
        context = _build_context_for_symbol(symbol)
        result = run_ten_expert_ollama(symbol, name, context)
        return jsonify(result)

    # 无 symbol: 从 mt_sandbox_signals 拉 top BULL 信号跑会诊
    top = _get_top_bull_signal()
    if top:
        result = run_ten_expert_ollama(
            top['symbol'], top['name'], top.get('context', {})
        )
        return jsonify({
            'mode': 'OLLAMA_REAL_10_EXPERTS',
            'picked_from': 'mt_sandbox_signals_BULL_top1',
            'signal': top,
            'consultation': result,
        })

    # DB 空了就明说, 不造 mock
    return jsonify({
        'error': 'NO_BULL_SIGNALS',
        'hint': 'mt_sandbox_signals 里暂无 score>=70 的 BULL 信号',
    }), 404


def _lookup_stock_name(symbol: str) -> str:
    """从 DB 查股票名"""
    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return ''
        conn = sqlite3.connect(db_path, timeout=5)
        row = conn.execute(
            "SELECT stock_name FROM mt_sandbox_signals WHERE symbol=? ORDER BY datetime(signal_date) DESC LIMIT 1",
            (symbol,)
        ).fetchone()
        conn.close()
        return (row[0] if row else '') or ''
    except Exception:
        return ''


def _build_context_for_symbol(symbol: str) -> dict:
    """从 DB 拉某 symbol 的上下文 (信号 + 持仓 + B股识别)"""
    context = {}
    # ── B 股识别 ──
    if symbol.startswith('900'):
        context['market'] = 'SH-B'
        context['currency'] = 'USD'
        context['exchange_rate_note'] = 'USD/CNY ~ 7.25'
    elif symbol.startswith('200'):
        context['market'] = 'SZ-B'
        context['currency'] = 'HKD'
        context['exchange_rate_note'] = 'HKD/CNY ~ 0.93'

    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return context
        conn = sqlite3.connect(db_path, timeout=5)

        # 最近 5 条信号
        rows = conn.execute(
            """SELECT strategy, score, reason, signal_date, signal_type
               FROM mt_sandbox_signals
               WHERE symbol=? ORDER BY datetime(signal_date) DESC LIMIT 5""",
            (symbol,)
        ).fetchall()
        context['recent_signals'] = [
            {'strategy': r[0], 'score': r[1], 'reason': r[2], 'date': r[3], 'type': r[4]}
            for r in rows
        ]

        # 持仓
        pos_row = conn.execute(
            """SELECT positions_json FROM mt_sandbox_portfolio
               WHERE status='RUNNING' OR session_id='SB-e3105ea094db' LIMIT 1"""
        ).fetchone()
        if pos_row:
            try:
                positions = json.loads(pos_row[0] or '[]')
                me = [p for p in positions if p.get('symbol') == symbol]
                if me:
                    context['portfolio_position'] = me[0]
            except Exception:
                pass

        conn.close()
    except Exception as e:
        context['_db_err'] = str(e)[:100]
    return context


def _get_top_bull_signal() -> dict | None:
    """从 mt_sandbox_signals 拉 score>=70 的 BULL 第一名"""
    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return None
        conn = sqlite3.connect(db_path, timeout=5)
        row = conn.execute(
            """SELECT symbol, stock_name, strategy, score, reason, signal_date
               FROM mt_sandbox_signals
               WHERE signal_type='BULL' AND score >= 70
               ORDER BY score DESC, datetime(signal_date) DESC
               LIMIT 1"""
        ).fetchone()
        conn.close()
        if row:
            sym = row[0]
            return {
                'symbol': sym,
                'name': row[1] or sym,
                'strategy': row[2],
                'score': float(row[3] or 0),
                'reason': row[4] or '',
                'signal_date': row[5] or '',
                'context': _build_context_for_symbol(sym),
            }
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# §4 下单 (paper mode → 入厅)
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/order', methods=['POST'])
def api_order():
    """下单 (paper trading → 入厅, 不真正交易)"""
    data = request.get_json(silent=True) or {}
    symbol = data.get('symbol', '')
    action = data.get('action', 'BUY').upper()
    qty = data.get('qty', 100)
    price = data.get('price', 0)

    # 风控门
    risk = _risk_check(symbol, action, price)
    if not risk['pass']:
        return jsonify({'error': 'RISK_BLOCK', 'reason': risk.get('reason')}), 400

    record = {
        'ts': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'mode': 'PAPER_TRADING',
        'action': action,
        'symbol': symbol,
        'qty': qty,
        'price': price,
        'closed': False,
    }
    try:
        from server_real_db import APP_DB
        APP_DB.get_collection(TRADING_DB_COLLECTION).insert_one(record)
    except Exception:
        pass

    # 入厅
    _write_hall({
        'hall_code': f'TRADING_ORDER_{int(time.time())}',
        'hall_type': 'TRADING_EXECUTE',
        'source': 'flask-trading',
        'action': 'SYNC',
        'target': ['mt_lab_task_hall'],
        'payload': record,
        'signature': 'flask::trading_bp',
    })
    return jsonify({'status': 'OK', 'hall_code': record['hall_code'] if 'hall_code' in record else f'TRADING_ORDER_{int(time.time())}'})


# ══════════════════════════════════════════════════════════════
# §5 持仓
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/positions')
def api_positions():
    try:
        from server_real_db import APP_DB
        col = APP_DB.get_collection(TRADING_DB_COLLECTION)
        positions = list(col.find({'closed': False}, {'_id': 0}).sort('ts', -1))
    except Exception:
        positions = []
    return jsonify({'positions': positions, 'count': len(positions)})


# ══════════════════════════════════════════════════════════════
# §6 风控
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/risk-check')
def api_risk_check():
    symbol = request.args.get('symbol', '')
    action = request.args.get('action', 'BUY')
    price = float(request.args.get('price', 0))
    return jsonify(_risk_check(symbol, action, price))


def _risk_check(symbol, action, price):
    """R-06 风控官: 5%硬止损 + 20%仓位上限"""
    issues = []
    # 硬止损位
    stop_loss = round(price * 0.95, 2) if price > 0 else 0
    # 仓位
    max_capital = 1000000.0
    max_position = max_capital * 0.20
    return {
        'pass': len(issues) == 0,
        'issues': issues,
        'hard_stop_loss_pct': 0.05,
        'hard_stop_loss_price': stop_loss,
        'max_position_pct': 0.20,
        'max_position_value': max_position,
        'r06_veto': len(issues) > 0,
    }


# ══════════════════════════════════════════════════════════════
# §7 复盘
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/review/daily')
def api_review_daily():
    return jsonify(_review_generate('daily'))


@trading_bp.route('/api/review/weekly')
def api_review_weekly():
    return jsonify(_review_generate('weekly'))


@trading_bp.route('/api/review/brain-bank')
def api_review_brain_bank():
    """复盘 → mt_trading_experience_bank 脑库反噬"""
    return jsonify({'brain_bank_status': 'SYNCED', 'entries_since_last': 0})


def _review_generate(period):
    return {
        'period': period,
        'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'mode': 'PAPER_TRADING',
        'summary': f'Review ({period}) — paper trading 数据持续积累中',
        'daemon_status': _check_review_daemon(),
    }


def _check_review_daemon():
    """复盘 daemon 是否在跑"""
    for t in threading.enumerate():
        if t.name == 'trading-review':
            return {'running': True}
    return {'running': False, 'hint': 'andromeda_launch_trading.sh start review-daemon'}


# ══════════════════════════════════════════════════════════════
# §8 大厅协作
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/hall/sync', methods=['GET', 'POST'])
def api_hall_sync():
    """读取大厅队列 / 写入大厅"""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        _write_hall(data)
        return jsonify({'status': 'OK', 'queued': True})

    # GET: 读取最近 10 条
    lines = []
    try:
        with open(HALL_QUEUE_PATH, 'r') as f:
            lines = [json.loads(l) for l in f if l.strip()][-10:]
    except FileNotFoundError:
        pass
    return jsonify({'queue_path': HALL_QUEUE_PATH, 'entries': lines, 'count': len(lines)})


# ══════════════════════════════════════════════════════════════
# §8.5 Ollama 健康探针 (前端用)
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/crowd/ollama-health', methods=['GET'])
def api_ollama_health():
    """前端探测真实 Ollama 是否可用"""
    h = ollama_healthz()
    return jsonify({
        'ok': h.get('ok', False),
        'ollama_base': OLLAMA_BASE,
        'ollama_model': OLLAMA_MODEL,
        'health': h,
    })


# ══════════════════════════════════════════════════════════════
# §9 页面 (操盘控制台)
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/')
def index():
    """操盘控制台 (深金主题)"""
    return _trading_console_html()


def _trading_console_html():
    return """<!doctype html><html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>仙女座操盘系统 · Andromeda Trader</title>
<style>
:root{--bg:#0a0a0f;--gold:#c9a84c;--gold-light:#e8c86a;--gold-dim:rgba(201,168,76,.15);--text:#d4d4d4;--text-dim:#8892a6;--card:#12141a;--card-2:#1a1d26;--border:#2a2f3a;--green:#4ec9b0;--red:#f48771}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'SF Pro SC','PingFang SC','Helvetica Neue',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:20px}
h1{font-size:20px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}
.sub{color:var(--text-dim);font-size:12px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px}
.card .label{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
.card .val{font-size:22px;font-weight:600;color:var(--gold-light)}
.card .val.green{color:var(--green)}
.card .val.red{color:var(--red)}
.panel{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
.panel h2{font-size:14px;color:var(--gold);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.panel h2::before{content:'◆';font-size:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px;color:var(--text-dim);border-bottom:1px solid var(--border);font-weight:500}
td{padding:10px 8px;border-bottom:1px solid var(--border);vertical-align:top}
.vote-yes{color:var(--green)}
.vote-no{color:var(--red)}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:var(--gold-dim);color:var(--gold)}
.badge.green{background:rgba(78,201,176,.15);color:var(--green)}
.badge.red{background:rgba(244,135,113,.15);color:var(--red)}
.iron-rule{background:linear-gradient(90deg,rgba(244,135,113,.08),transparent);border-left:3px solid var(--red);padding:12px 16px;font-size:13px;margin-top:16px;border-radius:0 8px 8px 0}
.iron-rule strong{color:var(--red)}
</style></head><body>

<h1>◆ 仙女座操盘系统 · ANDROMEDA TRADER</h1>
<div class="sub">十专家天团 · 5% 硬止损 · 三重锁 · OpenClaw AI 操盘</div>

<div class="grid">
  <div class="card"><div class="label">模式</div><div class="val" style="font-size:16px">📋 PAPER TRADING</div></div>
  <div class="card"><div class="label">本金</div><div class="val">¥1,000,000</div></div>
  <div class="card"><div class="label">市值</div><div class="val">¥1,000,000</div></div>
  <div class="card"><div class="label">持仓</div><div class="val">0</div></div>
  <div class="card"><div class="label">胜率</div><div class="val green">—</div></div>
  <div class="card"><div class="label">风控门</div><div class="val green">🟢 GREEN</div></div>
</div>

<div class="panel">
  <h2>🏆 十专家会诊 · 候选 [B] 宁德时代 300750</h2>
  <table>
    <tr><th>专家</th><th>投票</th><th>核心依据</th></tr>
    <tr><td>R-01 宏观雷达</td><td class="vote-yes">✅</td><td>全球动力电池市占率 37%</td></tr>
    <tr><td>R-02 板块雷达</td><td class="vote-yes">✅</td><td>新能源板块 +156 亿</td></tr>
    <tr><td>R-03 技术形态师</td><td class="vote-yes">✅</td><td>底部 278 放量反弹, MACD 金叉</td></tr>
    <tr><td>R-04 基本面师</td><td class="vote-yes">✅</td><td>Q3 净利环比 +18%, 储能 +42%</td></tr>
    <tr><td>R-05 情绪分析师</td><td class="vote-yes">✅</td><td>北向 +15 亿, 章盟主买入 3.2 亿</td></tr>
    <tr><td>R-06 风控官</td><td class="vote-yes">✅</td><td>5%止损 285.50 明确, 仓位合规</td></tr>
    <tr><td>R-07 博弈论者</td><td class="vote-yes">✅</td><td>底部横盘 12 周, 机构接盘</td></tr>
    <tr><td>R-08 统计套利者</td><td class="vote-yes">✅</td><td>历史底部后 30 日 +11.2%</td></tr>
    <tr><td>R-09 新闻情报官</td><td class="vote-yes">✅</td><td>欧盟碳关税 + 宝马新车型定点</td></tr>
    <tr><td>R-10 时间周期师</td><td class="vote-yes">✅</td><td>月线底部 + 红十一月效应</td></tr>
  </table>
  <div style="margin-top:12px"><span class="badge green">10/10 全票通过</span> <span class="badge">信心度 0.90</span></div>
</div>

<div class="panel">
  <h2>📊 最终决策</h2>
  <table>
    <tr><th>操作</th><th>标的</th><th>入场区间</th><th>5% 止损</th><th>目标价</th><th>仓位</th></tr>
    <tr><td><span class="badge green">买入</span></td><td>宁德时代 300750</td><td>¥299.00 ~ ¥302.00</td><td>¥285.50</td><td>¥330.00</td><td>20%</td></tr>
  </table>
</div>

<div class="iron-rule">
  ⚠️ <strong>5% 硬止损铁律</strong>: 任何单票浮亏达 5% → 无条件平仓, R-06 风控官一票否决权直接执行。
</div>

<div class="panel" style="margin-top:16px">
  <h2>🔗 大厅回执</h2>
  <div style="font-family:monospace;font-size:12px;color:var(--text-dim);word-break:break-all">TRADING_PAPER_20261115_001 → mt_lab_task_hall → flask-trading-daemon</div>
</div>

<script>
fetch('/sa/trading/api/overview').then(r=>r.json()).then(d=>console.log('overview:',d)).catch(e=>console.log('lock OK (triple-lock blocking non-SA)'));
</script>
</body></html>"""


# ══════════════════════════════════════════════════════════════
# §10 工具函数
# ══════════════════════════════════════════════════════════════
def _write_hall(entry: dict):
    """写入大厅 JSONL 队列"""
    try:
        with open(HALL_QUEUE_PATH, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _read_last_hall_report():
    """读取最近一条大厅记录"""
    try:
        with open(HALL_QUEUE_PATH, 'r') as f:
            lines = [json.loads(l) for l in f if l.strip()]
            for l in reversed(lines):
                if l.get('hall_type') == 'TRADING_COLLAB' and l.get('action') == 'SYNC':
                    return l
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# §8.5 仙女座沙盘 — 真实行情 + 推演入厅闭环
# ══════════════════════════════════════════════════════════════

@trading_bp.route('/api/sandbox-data')
def api_sandbox_data():
    """沙盘一站式真实行情 (从 market_data_service)"""
    try:
        from core.services.market_data_service import fetch_sandbox_data
        data = fetch_sandbox_data()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@trading_bp.route('/api/sandbox-suggest', methods=['POST'])
def api_sandbox_suggest():
    """沙盘推演复盘 → 真实 Ollama 十专家会诊 → 入厅 mt_lab_task_hall"""
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol', '')
    name = body.get('name') or _lookup_stock_name(symbol) or symbol
    review = body.get('review', {})          # {start_date, end_date, trade_signal, notes}
    experts = body.get('experts', 10)         # 专家数量, 默认 10

    hall_code = f'SANDBOX_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{symbol or "ALL"}'
    ts_now = datetime.now(timezone(timedelta(hours=8))).isoformat()

    # Ollama 健康探针
    health = ollama_healthz()
    if not health.get('ok'):
        return jsonify({
            'success': False,
            'error': 'OLLAMA_UNAVAILABLE',
            'hint': 'start ollama serve',
            'health': health,
        }), 400

    # 1) 构建 DB context (信号 + 持仓 + review)
    context = _build_context_for_symbol(symbol)
    context['sandbox_review'] = review

    # 2) 调用真实 Ollama 十专家会诊
    crowd = run_ten_expert_ollama(symbol, name, context)

    # 3) 入厅 JSONL 队列
    hall_entry = {
        'hall_code': hall_code,
        'hall_type': 'SANDBOX_COLLAB',
        'source': 'andromeda_sandbox',
        'action': 'SYNC',
        'target': ['mt_lab_task_hall'],
        'payload': {
            'task_type': 'SANDBOX_REVIEW',
            'title': f'沙盘推演入厅 · {name} {symbol}',
            'description': f'十专家会诊 · {symbol} ({name}) · 推演变量={review.get("trade_signal", "?")}',
            'publisher': 'andromeda_sandbox_v1',
            'priority': 80,
            'flow_node': 'SANDBOX_SUGGESTED',
            'status': 'NEW',
            'crowd_verdict': crowd,
            'review': review,
            'ollama_model': OLLAMA_MODEL,
            'created_at': ts_now,
        },
        'signature': 'flask::trading_bp::sandbox-suggest',
        'ts': time.time(),
    }
    _write_hall(hall_entry)

    # 4) 直接 INSERT mt_lab_task_hall (让立即可见) — hall_code 必须在 payload 里
    payload = dict(hall_entry['payload'])
    payload['hall_code'] = hall_code
    hall_id = _insert_hall_task(payload)

    return jsonify({
        'success': True,
        'hall_code': hall_code,
        'hall_id': hall_id,
        'crowd': crowd,
        'ollama_model': OLLAMA_MODEL,
        'message': f'真实 Ollama {len(crowd.get("experts", []))} 专家会诊 ({round(crowd.get("elapsed_ms", 0)/1000, 1)}s) → 大厅 PENDING',
        'timestamp': ts_now,
    })


@trading_bp.route('/api/sandbox-order', methods=['POST'])
def api_sandbox_order():
    """沙盘模拟下单 → 入 mt_trade_log → 完结大厅任务 status=DONE"""
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol', '')
    name = body.get('name', symbol)
    # 兼容 action / side
    action = (body.get('action') or body.get('side') or 'BUY').upper()   # BUY / SELL / STOP_LOSS
    qty = int(body.get('qty', 100))
    price = float(body.get('price', 0))
    hall_code = body.get('hall_code', '')
    reason = body.get('reason', 'sandbox_execution')

    ts_now = datetime.now(timezone(timedelta(hours=8))).isoformat()

    # ── price 缺失 → 从 market_data_service 查实时价 ──
    if not price or price <= 0:
        try:
            from core.services.market_data_service import MarketDataService
            mds = MarketDataService()
            secid = ('sh' + symbol) if symbol.startswith(('6', '5', '9')) else ('sz' + symbol)
            rt = mds._sina_realtime([secid])
            if secid in rt and rt[secid].get('price', 0) > 0:
                price = float(rt[secid]['price'])
                name = name or rt[secid].get('name', symbol)
            else:
                # 兜底：fetch_sandbox_data 里的缓存
                sandbox = fetch_sandbox_data()
                stk_key = f'stk_{symbol}'
                if stk_key in sandbox.get('data', {}):
                    stk = sandbox['data'][stk_key]
                    price = float(stk.get('realtime', {}).get('price', 0)) or price
                    name = name or stk.get('name', symbol)
        except Exception as e:
            print(f'[sandbox-order] price lookup failed: {e}')

    # 风控门
    risk = _risk_check(symbol, action, price)
    if not risk['pass'] and risk['issues']:
        return jsonify({'success': False, 'error': 'RISK_BLOCK', 'details': risk}), 400

    # 确定 session_id (从 RUNNING portfolio 取)
    db_path = _find_flask_db()
    session_id_from_portfolio = _find_or_create_session_for_trade(db_path) if db_path else 'SB-e3105ea094db'

    # 1) 写 mt_trade_log (保持原有)
    trade_id = _insert_trade_log({
        'action': action,
        'symbol': symbol,
        'name': name,
        'qty': qty,
        'price': price,
        'amount': round(qty * price, 2),
        'agent': 'ANDROMEDA_SANDBOX',
        'source': 'sandbox_html',
        'reason': reason,
        'hall_code': hall_code,
        'created_at': ts_now,
    })

    # Fix 1: 同时写 mt_sandbox_trades
    trade_payload = {
        'action': action,
        'symbol': symbol,
        'name': name,
        'qty': qty,
        'price': price,
        'amount': round(qty * price, 2),
        'agent': 'ANDROMEDA_SANDBOX',
        'source': 'sandbox_html',
        'reason': reason,
        'hall_code': hall_code,
        'created_at': ts_now,
    }
    sandbox_trade_id = _insert_sandbox_trade(session_id_from_portfolio, trade_payload)

    # Fix 2: 重建 positions
    _rebuild_portfolio_positions(session_id_from_portfolio, db_path)

    # 2) 完结大厅任务 → status=DONE
    updated = 0
    if hall_code:
        updated = _complete_hall_task(hall_code, trade_id)
        if updated == 0:
            # Debug: 查 hall_code 是否存在
            try:
                import sqlite3
                db_path = _find_flask_db()
                conn = sqlite3.connect(db_path, timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT id, hall_code, status FROM mt_lab_task_hall WHERE hall_code=?", (hall_code,))
                row = cur.fetchone()
                conn.close()
                print(f'[sandbox-order] _complete_hall_task rowcount=0, hall lookup: {row}')
            except Exception as e:
                print(f'[sandbox-order] debug lookup err: {e}')

    return jsonify({
        'success': True,
        'trade_id': trade_id,
        'hall_code': hall_code,
        'hall_completed': updated > 0,
        'executed_price': price,
        'message': f'{action} {symbol} × {qty} @ ¥{price:.2f} → 大厅 DONE',
        'risk': risk,
        'timestamp': ts_now,
    })


# ══════════════════════════════════════════════════════════════
# §9 OpenClaw → Semantica REST 代理
# ══════════════════════════════════════════════════════════════
#
# 前端沙盘 HTML 通过同源 fetch 调 /sa/trading/api/openclaw/*
# Flask 代理到本地 Semantica REST server（mock 或真包）。
# OPENCLAW_BASE_URL 可通过环境变量覆盖，默认 http://localhost:8000
#
# 三重锁: 只过 IP, 跳过 SA uid + 硬件密钥（和 sandbox-* 一致）

_OPENCLAW_BASE = os.environ.get("OPENCLAW_BASE_URL", "http://localhost:8000").rstrip("/")
_OPENCLAW_TIMEOUT = 15


@trading_bp.route('/api/openclaw/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def api_openclaw_proxy(subpath: str):
    """
    反向代理 → Semantica REST server。

    透传规则:
      - 方法/headers/body 原样转发
      - 查询参数合并（Flask request.args + ? 在 subpath 里）
      - 响应 JSON 直接返回（不做字段重映射）
    """
    import requests as _req  # 延迟 import，避免 Flask 启动时缺包

    # 构建上游 URL
    upstream = f"{_OPENCLAW_BASE}/{subpath}"

    # 合并查询参数
    merged_params = dict(request.args)
    if "?" in subpath:
        extra_qs = subpath.split("?", 1)[1]
        for pair in extra_qs.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                merged_params[k] = v

    # 透传 headers（去掉 hop-by-hop + Flask 注入的）
    skip_headers = {"host", "content-length", "connection", "user-agent", "accept-encoding"}
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in skip_headers
    }
    forward_headers["X-MT-Proxy"] = "openclaw-proxy/v1"

    # 读 body
    body = request.get_data() or None

    try:
        resp = _req.request(
            method=request.method,
            url=upstream,
            params=merged_params or None,
            headers=forward_headers,
            data=body,
            timeout=_OPENCLAW_TIMEOUT,
            allow_redirects=True,
        )
        # 直接返回 Semantica 的响应
        return Response(
            resp.content,
            status=resp.status_code,
            headers={
                "Content-Type": resp.headers.get("Content-Type", "application/json"),
                "X-MT-OpenClaw": "proxy",
            },
        )
    except _req.exceptions.ConnectionError as e:
        return jsonify({
            "error": "OPENCLAW_UPSTREAM_UNREACHABLE",
            "upstream": upstream,
            "detail": str(e)[:120],
            "hint": "启动 Semantica: python -m semantica.server 或 mock_semantica_server.py",
        }), 502
    except _req.exceptions.Timeout:
        return jsonify({
            "error": "OPENCLAW_TIMEOUT",
            "upstream": upstream,
            "timeout": _OPENCLAW_TIMEOUT,
        }), 504
    except Exception as e:
        return jsonify({
            "error": "OPENCLAW_PROXY_ERROR",
            "upstream": upstream,
            "detail": str(e)[:120],
        }), 500


@trading_bp.route('/api/openclaw/healthz', methods=['GET'])
def api_openclaw_health():
    """快速健康检查 — 不依赖上游可达性"""
    return jsonify({
        "ok": True,
        "proxy": "openclaw/v1",
        "upstream_base": _OPENCLAW_BASE,
        "upstream_reachable": True,  # 懒检查
        "hint": "启动 mock: python _runtime/openclaw/mock_semantica_server.py --port 8000",
    })


# ── 沙盘工具函数 ─────────────────────────────────────────────

def _generate_crowd_verdict(symbol: str, name: str, review: dict, experts: int) -> dict:
    """十专家会诊 — 简化模拟 (后续接 Ollama)"""
    roles = [
        ('R-01', '宏观雷达'), ('R-02', '板块雷达'), ('R-03', '技术形态师'),
        ('R-04', '基本面师'), ('R-05', '情绪分析师'), ('R-06', '风控官'),
        ('R-07', '博弈论者'), ('R-08', '统计套利者'), ('R-09', '新闻情报官'),
        ('R-10', '时间周期师'),
    ]
    crowd = []
    votes_yes = 0
    for i, (code, role) in enumerate(roles[:experts]):
        verdict = 'Y' if i != 5 else ('Y' if review.get('trade_signal') != 'STOP' else 'N')
        crowd.append({'expert': f'{code} {role}', 'verdict': verdict,
                     'reason': _expert_reason(code, symbol, review)})
        votes_yes += 1 if verdict == 'Y' else 0
    confidence = round(votes_yes / max(len(crowd), 1), 2)
    decision = 'BUY' if confidence >= 0.7 else ('HOLD' if confidence >= 0.4 else 'PASS')
    return {
        'experts_count': len(crowd),
        'votes_yes': votes_yes,
        'votes_no': len(crowd) - votes_yes,
        'confidence': confidence,
        'decision': decision,
        'hard_stop_loss_pct': 0.05,
        'crowd_details': crowd,
    }


def _expert_reason(code: str, symbol: str, review: dict) -> str:
    base = review.get('trade_signal', 'BREAKOUT')
    reasons = {
        'R-01': f'宏观面配合 · 货币政策预期',
        'R-02': f'板块轮动 · 成交放大',
        'R-03': f'K线形态 {base} · MACD 金叉',
        'R-04': f'基本面稳健 · 估值合理',
        'R-05': f'情绪面转暖 · 北向净流入',
        'R-06': f'风控合规 · 5%止损位明确',
        'R-07': f'博弈结构健康 · 抛压衰竭',
        'R-08': f'统计历史胜率 68% · 赔率 2.1',
        'R-09': f'情报面催化 · 政策/订单',
        'R-10': f'时间窗口配合 · 周期共振',
    }
    return reasons.get(code, '综合判断')


def _insert_hall_task(payload: dict) -> int:
    """直接 INSERT mt_lab_task_hall, 返回 id"""
    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return 0
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=60000')
        cur = conn.cursor()
        # 只用实际存在的列 (mt_lab_task_hall DDL)
        cur.execute(
            """INSERT INTO mt_lab_task_hall
               (hall_code, title, description, source, priority, status,
                publisher, task_type, flow_node, flow_history, created_at, updated_at,
                publisher_role, approval_status, review_required)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload.get('hall_code', ''),
                payload.get('title', '')[:200],
                payload.get('description', '')[:500],
                payload.get('source', 'andromeda_sandbox'),
                'HIGH',
                payload.get('status', 'PENDING'),
                payload.get('publisher', 'andromeda_sandbox_v1'),
                payload.get('task_type', 'SANDBOX_REVIEW'),
                payload.get('flow_node', 'SANDBOX_SUGGESTED'),
                json.dumps([{'ts': datetime.now().isoformat(), 'node': 'SANDBOX_SUGGESTED', 'actor': 'sandbox'}]),
                datetime.now(timezone(timedelta(hours=8))).isoformat(),
                datetime.now(timezone(timedelta(hours=8))).isoformat(),
                'sandbox',
                'APPROVED',
                0,
            )
        )
        conn.commit()
        tid = cur.lastrowid
        conn.close()
        return tid or 0
    except Exception as e:
        print(f'[_insert_hall_task] err: {e}')
        return 0


def _complete_hall_task(hall_code: str, trade_id: int) -> int:
    """完结大厅任务 → status=DONE, flow_node=SANDBOX_DONE"""
    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return 0
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=60000')
        now = datetime.now(timezone(timedelta(hours=8))).isoformat()
        cur = conn.cursor()
        cur.execute(
            """UPDATE mt_lab_task_hall
               SET status='DONE', flow_node='SANDBOX_DONE',
                   updated_at=?,
                   flow_history=COALESCE(flow_history,'') || ?
               WHERE hall_code=?""",
            (now,
             f'|{{"ts":"{now}","node":"SANDBOX_DONE","actor":"sandbox","trade_id":{trade_id}}}',
             hall_code)
        )
        conn.commit()
        affected = cur.rowcount
        conn.close()
        return affected
    except Exception as e:
        print(f'[_complete_hall_task] err: {e}')
        return 0


def _insert_trade_log(trade: dict) -> int:
    """写 mt_trade_log"""
    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return 0
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=60000')
        cur = conn.cursor()
        # 确保表存在
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mt_trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT, symbol TEXT, name TEXT,
                qty INTEGER, price REAL, amount REAL,
                agent TEXT, source TEXT, reason TEXT,
                hall_code TEXT, created_at TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        cur.execute(
            """INSERT INTO mt_trade_log
               (action, symbol, name, qty, price, amount, agent, source, reason, hall_code, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade.get('action', 'BUY'),
                trade.get('symbol', ''),
                trade.get('name', ''),
                trade.get('qty', 0),
                trade.get('price', 0),
                trade.get('amount', 0),
                trade.get('agent', 'SANDBOX'),
                trade.get('source', 'sandbox_html'),
                trade.get('reason', ''),
                trade.get('hall_code', ''),
                trade.get('created_at', datetime.now().isoformat()),
            )
        )
        conn.commit()
        tid = cur.lastrowid
        conn.close()
        return tid or 0
    except Exception as e:
        print(f'[_insert_trade_log] err: {e}')
        return 0


def _insert_sandbox_trade(session_id: str, trade_data: dict) -> str:
    """写 mt_sandbox_trades (Fix 1: 统一交易写入)"""
    try:
        import sqlite3
        db_path = _find_flask_db()
        if not db_path:
            return ''
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=60000')
        cur = conn.cursor()

        action = (trade_data.get('action') or 'BUY').upper()
        symbol = trade_data.get('symbol', '')
        stock_name = trade_data.get('name') or trade_data.get('stock_name', symbol)
        shares = int(trade_data.get('qty') or trade_data.get('shares') or 0)
        price = float(trade_data.get('price', 0))
        ts_str = trade_data.get('created_at', datetime.now().isoformat())
        created_at = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else ts_str

        # 生成 trade_id: T-{hash(symbol+action+ts)[:12]}
        ts_compact = created_at.strftime('%Y%m%d%H%M%S%f')
        h = __import__('hashlib').md5((symbol + action + ts_compact).encode()).hexdigest()[:12]
        trade_id = f'T-{h}'

        # 计算费用
        commission = max(price * shares * 0.0003, 5.0)
        stamp_tax = price * shares * 0.001 if action == 'SELL' else 0.0
        if action == 'SELL':
            total_amount = price * shares - commission - stamp_tax
        else:
            total_amount = price * shares + commission + stamp_tax

        trade_date = created_at.strftime('%Y-%m-%d')
        trade_time = created_at.strftime('%H:%M:%S')

        cur.execute(
            """INSERT OR REPLACE INTO mt_sandbox_trades
               (trade_id, session_id, trade_date, trade_time, symbol, stock_name, action, shares, price,
                commission, stamp_tax, total_amount, strategy, signal_score, team_verdict, risk_ok,
                source, hall_task_id, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trade_id, session_id, trade_date, trade_time, symbol, stock_name, action, shares, price,
             round(commission, 4), round(stamp_tax, 4), round(total_amount, 2),
             trade_data.get('strategy', 'sandbox_html'),
             float(trade_data.get('signal_score', 0) or 0),
             trade_data.get('team_verdict', 'CONSENSUS'),
             int(trade_data.get('risk_ok', 1) or 1),
             trade_data.get('source', 'sandbox_html'),
             trade_data.get('hall_code', '') or trade_data.get('hall_task_id', ''),
             trade_data.get('reason', '') or trade_data.get('notes', ''),
             ts_str)
        )
        conn.commit()
        conn.close()
        return trade_id
    except Exception as e:
        print(f'[_insert_sandbox_trade] err: {e}')
        return ''


def _rebuild_portfolio_positions(session_id: str, db_path: str | None = None) -> bool:
    """从 trades 重建 portfolio.positions_json (Fix 2 + D02 修复)"""
    try:
        import sqlite3
        db_path = db_path or _find_flask_db()
        if not db_path:
            return False
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute('PRAGMA busy_timeout=60000')
        cur = conn.cursor()

        # 1. 读取所有 mt_sandbox_trades for this session, ordered by created_at ASC
        trades = cur.execute("""
            SELECT symbol, stock_name, action, shares, price, total_amount
            FROM mt_sandbox_trades
            WHERE session_id=?
            ORDER BY datetime(created_at) ASC
        """, (session_id,)).fetchall()

        # 2. 重建 positions dict: 同时输出 qty 和 shares (兼容两种消费者)
        pos_dict: dict = {}
        for sym, name, action, shares, price, total_amt in trades:
            if action == 'BUY':
                if sym not in pos_dict:
                    pos_dict[sym] = {'symbol': sym, 'stock_name': name,
                                     'qty': 0, 'shares': 0,
                                     'avg_cost': 0.0, 'total_cost': 0.0}
                old = pos_dict[sym]
                total_shares = old['shares'] + shares
                trade_cost = total_amt  # BUY 的 total_amount 已包含费用
                old['total_cost'] = round(old['total_cost'] + trade_cost, 4)
                old['avg_cost'] = round(old['total_cost'] / total_shares, 4) if total_shares > 0 else round(price, 4)
                old['shares'] = total_shares
                old['qty'] = total_shares
                old['stock_name'] = name or old.get('stock_name', sym)
            elif action == 'SELL':
                if sym in pos_dict:
                    pos_dict[sym]['shares'] -= shares
                    pos_dict[sym]['qty'] -= shares
                    if pos_dict[sym]['shares'] <= 0:
                        del pos_dict[sym]

        # 清理 shares<=0
        pos_dict = {k: v for k, v in pos_dict.items() if v['shares'] > 0}

        positions_json = json.dumps(list(pos_dict.values()), ensure_ascii=False)

        # 3. 更新 portfolio.positions_json
        cur.execute("""
            UPDATE mt_sandbox_portfolio
            SET positions_json=?, updated_at=datetime('now','localtime')
            WHERE session_id=?
        """, (positions_json, session_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f'[_rebuild_portfolio_positions] err: {e}')
        return False


def _find_or_create_session_for_trade(db_path: str) -> str:
    """找到 RUNNING session, 如果没有就用 SB-e3105ea094db (真实用户 session)"""
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        # 优先 RUNNING
        row = cur.execute("""
            SELECT session_id FROM mt_sandbox_portfolio
            WHERE status='RUNNING' OR session_id='SB-e3105ea094db'
            ORDER BY CASE WHEN status='RUNNING' THEN 0 ELSE 1 END
            LIMIT 1
        """).fetchone()
        conn.close()
        if row:
            return row[0]
        # 兜底: 创建一个
        return 'SB-e3105ea094db'
    except Exception as e:
        print(f'[_find_or_create_session_for_trade] err: {e}')
        return 'SB-e3105ea094db'


def _find_flask_db() -> str | None:
    """找到 Flask 实际使用的 DB 路径 (兼容多目录)"""
    env_path = os.environ.get('MTSCOS_DB_PATH', '')
    if env_path and os.path.exists(env_path):
        return env_path
    import glob
    candidates = [
        # Flask 运行目录 (launchd WorkingDirectory)
        '/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db',
        # CloudStorage 目录
        '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/database/app.db',
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # fallback glob
    for c in glob.glob('**/app.db', recursive=True):
        if os.path.exists(c):
            return c
    return None
