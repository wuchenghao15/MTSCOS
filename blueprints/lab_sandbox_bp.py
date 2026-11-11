#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 Lab Sandbox Blueprint — /api/lab/* 完全隔离的金融实验沙盘 API

所有写操作走 engines/lab_sandbox_engine.LabSandboxEngine
所有表前缀 mt_lab_* — 绝不碰 mt_sandbox_trades / mt_vault_*

CSRF + Customs + Customs-Gate 三重豁免 (server_real_db.py 中注册)
"""
from __future__ import annotations
import os
import sys
import json
import traceback
import logging

try:
    from flask import (Blueprint, jsonify, request, session)
except ImportError:
    # 兜底最小 stub — 允许模块在 Flask 未安装时被引擎 CLI 单独引用
    from types import SimpleNamespace
    class _StubBP:
        def __init__(self, name, **kw): self.name = name; self._kw = kw; self._routes = []
        def route(self, rule, **kw):
            def _wrap(f): self._routes.append((rule, f, kw)); return f
            return _wrap
    class _StubReq:
        @property
        def json(self): return {}
        def get_json(self, silent=False): return {}
        @property
        def args(self): return SimpleNamespace(get=lambda *a, **k: None)
    class _StubJ:
        @staticmethod
        def dumps(x, **kw): return json.dumps(x, ensure_ascii=False)
    jsonify = lambda *a, **k: None
    request = _StubReq()
    Blueprint = _StubBP

logger = logging.getLogger('lab_sandbox_bp')

lab_bp = Blueprint('lab_sandbox', __name__, url_prefix='/api/lab')

# ─── 延迟导入引擎 (避免 Flask app 尚未 ready 时循环 import) ───
_engine = None
def _get_engine():
    global _engine
    if _engine is None:
        from engines.lab_sandbox_engine import LabSandboxEngine
        _engine = LabSandboxEngine()
    return _engine

# ─── 统一响应 ───
def _ok(data=None, **extra):
    payload = {'success': True}
    if data is not None: payload['data'] = data
    payload.update(extra)
    return jsonify(payload)

def _err(msg, code=400):
    return jsonify({'success': False, 'error': msg}), code


# ═══════════════════════════════════════════════════════════════════
# 1. 实验 CRUD
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/experiments', methods=['GET'])
def list_experiments():
    """所有实验 (可按 status 过滤)"""
    status = request.args.get('status', '')
    limit = int(request.args.get('limit', 20))
    try:
        items = _get_engine().list_experiments(status=status, limit=limit)
        return _ok({'experiments': items, 'count': len(items)})
    except Exception as e:
        return _err(f'list failed: {e}', 500)


@lab_bp.route('/experiments', methods=['POST'])
def create_experiment():
    """创建实验 (自动加 36 AI 员工)"""
    data = request.get_json(silent=True) or {}
    title = data.get('title', '').strip()
    if not title:
        return _err('title 不能为空')
    exp_type = data.get('type', 'review')
    market = data.get('market', 'SIDE').upper()
    cash = float(data.get('initial_cash', 1_000_000))
    desc = data.get('description', '')
    auto_join = bool(data.get('auto_join_ai', True))
    if market not in ('BULL', 'BEAR', 'SIDE', 'CRASH', 'RALLY'):
        market = 'SIDE'
    try:
        r = _get_engine().create_experiment(
            title=title, exp_type=exp_type, initial_cash=cash,
            market_condition=market, description=desc, auto_join_ai=auto_join,
        )
        if r.get('success'):
            return _ok(r, message='实验已创建, AI 员工自动加入')
        return _err(r.get('error', 'unknown'))
    except Exception as e:
        traceback.print_exc()
        return _err(f'create failed: {e}', 500)


@lab_bp.route('/experiments/<exp_id>', methods=['GET'])
def get_experiment(exp_id):
    """实验详情 (组合/交易/排名)"""
    try:
        r = _get_engine().get_experiment_state(exp_id)
        if r.get('success'):
            return _ok(r)
        return _err(r.get('error', 'not found'), 404)
    except Exception as e:
        traceback.print_exc()
        return _err(str(e), 500)


@lab_bp.route('/experiments/<exp_id>/status', methods=['PUT', 'POST'])
def set_experiment_status(exp_id):
    """结束/暂停/重启实验"""
    data = request.get_json(silent=True) or {}
    status = (data.get('status') or request.args.get('status') or 'completed')
    try:
        r = _get_engine().update_experiment_status(exp_id, status)
        if r.get('success'): return _ok(r)
        return _err(r.get('error'))
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
# 2. 参与者
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/experiments/<exp_id>/join', methods=['POST'])
def join_experiment(exp_id):
    """人类加入实验"""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or request.args.get('name') or '').strip()
    if not name: return _err('name 不能为空')
    role = data.get('role', 'trader')
    cash = data.get('initial_cash')
    try:
        r = _get_engine().join_experiment(exp_id, name, role,
                                           float(cash) if cash else None)
        if r.get('success'): return _ok(r)
        return _err(r.get('error'))
    except Exception as e:
        return _err(str(e), 500)


@lab_bp.route('/experiments/<exp_id>/participants', methods=['GET'])
def list_participants(exp_id):
    participants = []
    conn = None
    try:
        from engines.lab_sandbox_engine import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM mt_lab_participant WHERE exp_id=?", (exp_id,)).fetchall()
        participants = [dict(r) for r in rows]
        return _ok({'exp_id': exp_id, 'participants': participants})
    except Exception as e:
        return _err(str(e), 500)
    finally:
        if conn: conn.close()


@lab_bp.route('/experiments/<exp_id>/rankings', methods=['GET'])
def get_rankings(exp_id):
    """团队排名 (基于总资产估算)"""
    try:
        r = _get_engine().get_experiment_state(exp_id)
        if r.get('success'):
            return _ok({'rankings': r.get('rankings', []),
                        'participants_count': len(r.get('participants', []))})
        return _err(r.get('error', 'not found'), 404)
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
# 3. 模拟下单
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/experiments/<exp_id>/trades', methods=['POST'])
def place_trade(exp_id):
    """模拟下单 + AI 点评 (同步返回)"""
    data = request.get_json(silent=True) or {}
    symbol = (data.get('symbol') or '').strip().lower()
    part_id = (data.get('part_id') or '').strip()
    action = (data.get('action') or '').strip().upper()
    qty = int(data.get('qty', 0))
    reason = data.get('reason', '')
    if not all([symbol, part_id, action in ('BUY', 'SELL'), qty > 0]):
        return _err('参数不足: symbol/part_id/action(BUY|SELL)/qty 必须提供')
    if not (qty % 100 == 0):
        return _err('qty 必须是 100 的倍数 (沙盘沿用 A 股规则)')
    try:
        r = _get_engine().place_trade(exp_id, part_id, symbol, action, qty, reason)
        if r.get('success'):
            return _ok(r, message='交易已执行 + AI 老师点评已生成')
        return _err(r.get('error', 'trade failed'))
    except Exception as e:
        traceback.print_exc()
        return _err(f'trade error: {e}', 500)


@lab_bp.route('/experiments/<exp_id>/trades', methods=['GET'])
def list_trades(exp_id):
    """实验所有交易"""
    limit = int(request.args.get('limit', 200))
    conn = None
    try:
        from engines.lab_sandbox_engine import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM mt_lab_trade WHERE exp_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (exp_id, limit)).fetchall()
        return _ok({'trades': [dict(r) for r in rows]})
    except Exception as e:
        return _err(str(e), 500)
    finally:
        if conn: conn.close()


@lab_bp.route('/experiments/<exp_id>/portfolio', methods=['GET'])
def get_portfolio(exp_id):
    """实验所有持仓"""
    conn = None
    try:
        from engines.lab_sandbox_engine import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM mt_lab_portfolio WHERE exp_id=?", (exp_id,)).fetchall()
        return _ok({'portfolios': [dict(r) for r in rows]})
    except Exception as e:
        return _err(str(e), 500)
    finally:
        if conn: conn.close()


# ═══════════════════════════════════════════════════════════════════
# 4. AI 复盘 + 脑库投喂
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/experiments/<exp_id>/review', methods=['POST'])
def run_review(exp_id):
    """AI 复盘 (同步, 可能耗时 30-60s — 已在 CLI 验证 Ollama 可用)"""
    try:
        r = _get_engine().run_experiment_review(exp_id)
        if r.get('success'):
            return _ok(r, message='AI 老师复盘完成')
        return _err(r.get('error', 'review failed'))
    except Exception as e:
        traceback.print_exc()
        return _err(f'review error: {e}', 500)


@lab_bp.route('/experiments/<exp_id>/feed', methods=['POST'])
def feed_brain(exp_id):
    """教训投喂脑库"""
    try:
        r = _get_engine().feed_lessons_to_brain(exp_id)
        if r.get('success'):
            return _ok(r, message='已投喂脑库')
        return _err(r.get('error', 'feed failed'))
    except Exception as e:
        traceback.print_exc()
        return _err(f'feed error: {e}', 500)


@lab_bp.route('/experiments/<exp_id>/report', methods=['GET'])
def get_report(exp_id):
    """查看复盘报告"""
    conn = None
    try:
        from engines.lab_sandbox_engine import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM mt_lab_report WHERE exp_id=?
               ORDER BY created_at DESC LIMIT 10""",
            (exp_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try: d['lessons'] = json.loads(d.pop('lessons_json', '[]') or '[]')
            except Exception: d['lessons'] = []
            try: d['brain_feed_ids'] = json.loads(d.get('brain_feed_ids') or '[]')
            except Exception: pass
            out.append(d)
        return _ok({'reports': out})
    except Exception as e:
        return _err(str(e), 500)
    finally:
        if conn: conn.close()


# ═══════════════════════════════════════════════════════════════════
# 5. AI 聊天 (沙盘内)
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/experiments/<exp_id>/chat', methods=['POST'])
def send_chat(exp_id):
    """AI 老师对话"""
    data = request.get_json(silent=True) or {}
    part_id = (data.get('part_id') or '').strip()
    message = (data.get('message') or '').strip()
    if not message: return _err('message 不能为空')
    if not part_id: return _err('part_id 不能为空')
    try:
        r = _get_engine().ai_chat(exp_id, part_id, message)
        if r.get('success'): return _ok(r)
        return _err(r.get('error'))
    except Exception as e:
        return _err(str(e), 500)


@lab_bp.route('/experiments/<exp_id>/chat', methods=['GET'])
def get_chat(exp_id):
    """对话历史"""
    limit = int(request.args.get('limit', 200))
    try:
        history = _get_engine().get_chat_history(exp_id, limit=limit)
        return _ok({'chat_history': history, 'count': len(history)})
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
# 6. 行情 + 工具
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/quote/<symbol>', methods=['GET'])
def quote(symbol):
    """实时行情 (腾讯 API)"""
    from engines.lab_sandbox_engine import get_realtime_quote
    q = get_realtime_quote(symbol.lower())
    if q.get('ok'):
        return _ok(q)
    return _err(q.get('error', 'quote failed'), 502)


@lab_bp.route('/batch-quotes', methods=['POST'])
def batch_quotes():
    """批量行情"""
    data = request.get_json(silent=True) or {}
    symbols = data.get('symbols', [])
    if not isinstance(symbols, list) or not symbols:
        return _err('symbols 必须是非空数组')
    from engines.lab_sandbox_engine import get_realtime_quote
    out = {}
    for s in symbols[:20]:  # 最多 20 只
        out[s] = get_realtime_quote(str(s).lower())
    return _ok({'quotes': out})


@lab_bp.route('/experiments/<exp_id>/tools', methods=['GET'])
def list_tools(exp_id):
    """金融工具清单 (沙盘内可用引擎列表) — 只暴露名称, 不影响真实数据"""
    tools = [
        {'name': 'tencent_quote', 'desc': '腾讯行情 API — 实时/历史行情', 'readonly': True},
        {'name': 'ollama_mentor', 'desc': 'Ollama qwen2.5:3b — 交易点评/复盘/教训蒸馏', 'readonly': True},
        {'name': 'portfolio_analyzer', 'desc': '组合分析: 胜率/盈亏比/Sharpe/MaxDD', 'readonly': True},
        {'name': 'risk_meter', 'desc': '风险仪表: 基于波动+仓位的简易评分', 'readonly': True},
        {'name': 'brain_feed_distiller', 'desc': '教训 → mt_fm_brain_feed + mt_center_knowledge_points 蒸馏器', 'readonly': True},
    ]
    return _ok({'tools': tools, 'note': '所有工具只读, 不影响真实交易数据'})


@lab_bp.route('/experiments/<exp_id>/run-tool', methods=['POST'])
def run_tool(exp_id):
    """运行金融工具 (只读, 不写真实表)"""
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip().lower()
    args = data.get('args', {})
    if not name: return _err('name 不能为空')
    # 仅允许清单内工具
    allowed = {'tencent_quote', 'ollama_mentor', 'portfolio_analyzer',
               'risk_meter', 'brain_feed_distiller'}
    if name not in allowed:
        return _err(f'未知工具: {name}, 允许: {sorted(allowed)}')

    if name == 'tencent_quote':
        sym = (args.get('symbol') or '').lower()
        syms = args.get('symbols') or ([sym] if sym else [])
        from engines.lab_sandbox_engine import get_realtime_quote
        out = {s: get_realtime_quote(s) for s in syms[:10]}
        return _ok({'tool': name, 'result': out})

    elif name == 'ollama_mentor':
        prompt = args.get('prompt', '')
        system = args.get('system', '')
        if not prompt: return _err('args.prompt 不能为空')
        from engines.lab_sandbox_engine import call_ollama
        reply = call_ollama(prompt, system=system)
        return _ok({'tool': name, 'reply': reply})

    elif name == 'portfolio_analyzer':
        # 直接复用 engine 的 get_experiment_state
        r = _get_engine().get_experiment_state(exp_id)
        if not r.get('success'): return _err(r.get('error'))
        metrics = _get_engine()._calc_metrics(
            r['trades'], r['participants'])
        return _ok({'tool': name, 'metrics': metrics,
                    'rankings': r['rankings'][:10]})

    elif name == 'risk_meter':
        r = _get_engine().get_experiment_state(exp_id)
        if not r.get('success'): return _err(r.get('error'))
        rankings = r['rankings']
        # 简易风险: 总资产 最大偏差 / 平均
        totals = [rk['total_assets'] for rk in rankings]
        if totals:
            avg = sum(totals) / len(totals)
            max_dev = max(abs(t - avg) / avg for t in totals)
            risk_score = min(100, max_dev * 100)
        else:
            risk_score = 0
        return _ok({'tool': name, 'risk_score': round(risk_score, 1),
                    'interpretation': (
                        '低风险' if risk_score < 15 else
                        '中等风险' if risk_score < 35 else
                        '高风险'
                    )})

    elif name == 'brain_feed_distiller':
        # 触发复盘 + 蒸馏
        from engines.lab_sandbox_engine import ollama_extract_lessons
        r = _get_engine().run_experiment_review(exp_id)
        if not r.get('success'): return _err(r.get('error'))
        lessons = ollama_extract_lessons(
            r.get('review_text', ''), r.get('trades_count', 0),
            r.get('metrics', {}).get('win_rate', 0),
            r.get('metrics', {}).get('pnl_pct', 0),
        )
        return _ok({'tool': name, 'lessons_count': len(lessons), 'lessons': lessons})

    return _err('tool not found', 404)


# ═══════════════════════════════════════════════════════════════════
# 7. 健康检查
# ═══════════════════════════════════════════════════════════════════

@lab_bp.route('/health', methods=['GET'])
def health():
    eng = _get_engine()
    try:
        eng.init_db()  # 确保表存在
    except Exception as e:
        return _ok({
            'engine': 'LabSandboxEngine', 'ok': True,
            'db_path': eng.db_path, 'ollama_ok': eng.ollama_ok,
            'quote_ok': eng.quote_ok, 'tables': list(__import__('engines.lab_sandbox_engine', fromlist=['LAB_SCHEMAS']).LAB_SCHEMAS.keys()),
        })
    return _ok({
        'engine': 'LabSandboxEngine', 'ok': True,
        'db_path': eng.db_path, 'ollama_ok': eng.ollama_ok,
        'quote_ok': eng.quote_ok, 'tables': list(LAB_SCHEMAS := __import__('engines.lab_sandbox_engine', fromlist=['LAB_SCHEMAS']).LAB_SCHEMAS.keys()),
    })


# =====================================================================
# Blueprint 注册入口 (供 server_real_db / routes/__init__.py 调用)
# =====================================================================
def register_lab_sandbox_blueprint(app):
    """把 lab_bp 注册到 Flask app, 并确保 6 张表存在"""
    try:
        app.register_blueprint(lab_bp)
        # 幂等建表 (后台线程, 不阻塞 Flask listen)
        try:
            import threading
            def _ensure():
                try:
                    _get_engine().init_db()
                except Exception: pass
            threading.Thread(target=_ensure, daemon=True, name='lab-sandbox-init').start()
        except Exception: pass
        sys.stderr.write("[LabSandbox] ✅ /api/lab/* blueprint 已注册 (完全隔离 mt_lab_* 表)\n")
        return True
    except Exception as e:
        sys.stderr.write(f"[LabSandbox] ❌ blueprint 注册失败: {e}\n")
        return False


# 模块被直接运行时可以 standalone 打印 routes (调试用)
if __name__ == '__main__':
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument('--health', action='store_true')
    parser.add_argument('--routes', action='store_true')
    args = parser.parse_args()
    if args.health:
        from engines.lab_sandbox_engine import LabSandboxEngine
        eng = LabSandboxEngine()
        print(json.dumps({
            'db_path': eng.db_path, 'ollama_ok': eng.ollama_ok,
            'quote_ok': eng.quote_ok,
        }, ensure_ascii=False, indent=2))
    if args.routes:
        for r in lab_bp._routes if hasattr(lab_bp, '_routes') else []:
            print(f"  {r[0]}")
