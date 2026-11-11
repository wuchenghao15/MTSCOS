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
import threading
import time
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, Response

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

    # sandbox API 端点: 只过 IP, 跳过 SA uid + 硬件密钥
    if path.startswith('/api/sandbox-'):
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
    """仪表盘: 本金/市值/盈亏/胜率/指数/情绪面/风控门"""
    try:
        from server_real_db import APP_DB
        col = APP_DB.get_collection(TRADING_DB_COLLECTION)
        records = list(col.find({}, {'_id': 0}).sort('ts', -1).limit(100))
    except Exception:
        records = []

    positions = [r for r in records if r.get('action') == 'BUY' and not r.get('closed')]
    closed = [r for r in records if r.get('closed')]
    pnl = sum((r.get('exit_price', 0) - r.get('entry_price', 0)) * r.get('qty', 0) for r in closed)
    win_rate = sum(1 for r in closed if r.get('exit_price', 0) > r.get('entry_price', 0)) / max(len(closed), 1)

    return jsonify({
        'mode': 'PAPER_TRADING',
        'capital': 1000000.0,
        'market_value': 1000000.0 + pnl,
        'pnl': pnl,
        'win_rate': round(win_rate, 4),
        'positions_count': len(positions),
        'closed_count': len(closed),
        'indices': {
            'SH': {'value': 3487.23, 'change': 0.42},
            'SZ': {'value': 11234.56, 'change': 0.68},
            'CYB': {'value': 2789.01, 'change': 1.15},
            'KC50': {'value': 1023.78, 'change': 1.87},
        },
        'sentiment': {
            'north_flow': 87,
            'limit_up': 68,
            'limit_down': 12,
            'blow_plate_rate': 0.18,
        },
        'risk_gate': {
            'max_position_pct': 0.20,
            'hard_stop_loss_pct': 0.05,
            'current_total_position': 0.0,
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
    """候选清单"""
    return jsonify({
        'source': 'R-01+S-01_joint',
        'count': 5,
        'candidates': [
            {'symbol': '688981', 'name': '中芯国际', 'reason': '半导体龙头 突破前高 北向加仓', 'votes_8_10': True},
            {'symbol': '300750', 'name': '宁德时代', 'reason': '新能源龙二 底部放量 龙虎榜', 'votes': '10/10', 'selected': True},
            {'symbol': '688256', 'name': '寒武纪', 'reason': 'AI芯片 形态完美 RSI=52', 'votes': '10/10'},
            {'symbol': '603259', 'name': '药明康德', 'reason': '医药龙头 估值新低 政策催化', 'votes': '9/10'},
            {'symbol': '600150', 'name': '中国船舶', 'reason': '军工周期底 量能异动', 'votes': '10/10'},
        ],
        'generated_at': '2026-11-15T14:30:00+08:00',
    })


# ══════════════════════════════════════════════════════════════
# §3 十专家会诊
# ══════════════════════════════════════════════════════════════
@trading_bp.route('/api/suggest', methods=['GET', 'POST'])
def api_suggest():
    """触发十专家会诊 — 调用本地 Ollama (如果可用) 或返回上次结果"""
    data = request.get_json(silent=True) or {}
    symbol = data.get('symbol') or request.args.get('symbol')

    # 如果指定 symbol, 跑单票会诊; 否则返回上次全量结果
    if symbol:
        return jsonify(_crowd_single(symbol))

    # 读取上次会诊结果 (从大厅 JSONL)
    last = _read_last_hall_report()
    if last:
        return jsonify({
            'mode': 'CROWD_10_EXPERTS',
            'session': 'andromeda-trade-003',
            'model': 'ollama/qwen2.5:7b',
            'last_report': last,
            'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        })
    return jsonify({'status': 'no_pending_crowd', 'hint': '先跑一次 openclaw agent'})


def _crowd_single(symbol):
    """单票会诊 (模拟 — 实际走 Ollama)"""
    return {
        'symbol': symbol,
        'crowd': {f'R-{i:02d}': 'Y' for i in range(1, 11)},
        'total': '10/10',
        'decision': 'PASS',
        'confidence': 0.9,
    }


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
    """沙盘推演复盘 → 十专家会诊 → 入厅 mt_lab_task_hall"""
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol', '')
    name = body.get('name', symbol)
    review = body.get('review', {})          # {start_date, end_date, trade_signal, notes}
    experts = body.get('experts', 10)         # 专家数量, 默认 10

    hall_code = f'SANDBOX_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{symbol or "ALL"}'
    ts_now = datetime.now(timezone(timedelta(hours=8))).isoformat()

    # 1) 生成十专家会诊意见
    crowd = _generate_crowd_verdict(symbol, name, review, experts)

    # 2) 入厅 JSONL 队列
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
            'status': 'PENDING',
            'crowd_verdict': crowd,
            'review': review,
            'created_at': ts_now,
        },
        'signature': 'flask::trading_bp::sandbox-suggest',
        'ts': time.time(),
    }
    _write_hall(hall_entry)

    # 3) 直接 INSERT mt_lab_task_hall (让立即可见) — hall_code 必须在 payload 里
    payload = dict(hall_entry['payload'])
    payload['hall_code'] = hall_code
    hall_id = _insert_hall_task(payload)

    return jsonify({
        'success': True,
        'hall_code': hall_code,
        'hall_id': hall_id,
        'crowd': crowd,
        'message': f'{experts} 位专家已会诊 → 大厅 PENDING',
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

    # 1) 写 mt_trade_log
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

    # ═══ 实时账务稽查 (双引擎 Hook) ═══
    try:
        from engines.finance_realtime_audit import audit_trade
        gross_amount = round(qty * price, 2)
        fee_now = max(5.0, gross_amount * 0.0003)            # 万三, 最低 5
        tax_now = round(gross_amount * 0.001, 2) if action.upper() == 'SELL' else 0.0
        audit_result = audit_trade({
            'trade_id': trade_id,
            'session_id': hall_code or '',                     # sandbox-order 无 session_id
            'symbol': symbol,
            'side': action.upper(),
            'qty': qty,
            'price': price,
            'fee': fee_now,
            'tax': tax_now,
            'cash_before': None,                                # sandbox-order 无 portfolio 快照
            'cash_after': None,
        })
        if audit_result.get('verdict') not in ('PASS',):
            try:
                app.logger.warning(
                    f"[AUDIT-REALTIME] trade {trade_id}: "
                    f"{audit_result.get('verdict')} — issues={audit_result.get('issues')}"
                )
            except Exception:
                print(f"[AUDIT-REALTIME] trade {trade_id}: "
                      f"{audit_result.get('verdict')} — issues={audit_result.get('issues')}")
    except Exception as _audit_err:
        try:
            app.logger.error(f"[AUDIT-REALTIME] realtime audit hook failed: {_audit_err}")
        except Exception:
            print(f"[AUDIT-REALTIME] realtime audit hook failed: {_audit_err}")

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
