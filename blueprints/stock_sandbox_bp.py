#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股市沙盘模拟交易 Blueprint
url_prefix = '/api/sandbox'

核心 API:
  GET  /status           沙盘状态 + 净值 + 持仓
  POST /tick             手动 tick (拉行情→策略→团队→执行)
  POST /simulate         模拟一周/一年 (days + scenario)
  POST /daemon/start     启动守护进程 (定时 tick + 协作总线事件)
  POST /daemon/stop      停止守护进程
  GET  /trades           交易流水
  GET  /positions        当前持仓 + 快照
  GET  /signals          策略信号池
  GET  /reports          沙盘报告 (session 净值曲线)
  POST /trigger          协作总线事件触发 (外部调用)
"""

from __future__ import annotations

import json
import sys
from flask import Blueprint, jsonify, request

stock_sandbox_bp = Blueprint(
    'stock_sandbox',
    __name__,
    url_prefix='/api/sandbox'
)


def _db_conn():
    import sqlite3, os
    from pathlib import Path
    return sqlite3.connect(os.path.join(
        Path(__file__).resolve().parent.parent, 'database', 'app.db'
    ))


def _daemon_alive(sb) -> bool:
    """daemon 存活判定: Flask 进程内线程 OR launchd 独立进程 (pgrep)"""
    if sb is not None and getattr(sb, '_thread', None) and sb._thread.is_alive():
        return True
    try:
        import subprocess
        r = subprocess.run(
            ['pgrep', '-f', 'ai_stock_sandbox_engine.py'],
            capture_output=True, timeout=3
        )
        return r.returncode == 0
    except Exception:
        return False


@stock_sandbox_bp.route('/sessions', methods=['GET'])
def api_sessions():
    """全部沙盘会话列表 (会话选择器数据源, 含幽灵会话标记)"""
    try:
        conn = _db_conn()
        try:
            rows = conn.execute(
                "SELECT p.session_id, p.scenario, p.scenario_days, p.initial_cash, "
                "p.current_cash, p.positions_json, p.is_frozen, p.status, "
                "p.created_at, p.updated_at, "
                "(SELECT COUNT(*) FROM mt_sandbox_trades t WHERE t.session_id = p.session_id) "
                "FROM mt_sandbox_portfolio p ORDER BY p.updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            try:
                pos = json.loads(r[5] or '[]')
            except Exception:
                pos = []
            out.append({
                'session_id': r[0], 'scenario': r[1], 'scenario_days': r[2],
                'initial_cash': r[3], 'current_cash': round(r[4], 2),
                'position_count': len(pos), 'positions': pos,
                'is_frozen': bool(r[6]), 'status': r[7],
                'created_at': r[8], 'updated_at': r[9], 'trade_count': r[10],
            })
        return jsonify({'ok': True, 'sessions': out, 'count': len(out)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:200]}), 500


@stock_sandbox_bp.route('/portfolio/<session_id>', methods=['GET'])
def api_portfolio_session(session_id):
    """任意会话只读详情 (状态 + 持仓 + 交易) — 独立路由, 不受蓝图共享路由遮蔽影响"""
    try:
        import sqlite3 as _sl
        from engines.ai_stock_sandbox_engine import SandboxPortfolio
        conn = _db_conn()
        conn.row_factory = _sl.Row
        try:
            row = conn.execute(
                "SELECT session_id, scenario, scenario_days, initial_cash, current_cash, "
                "positions_json, risk_floor_pct, is_frozen, start_date, current_date, "
                "daily_high_watermark FROM mt_sandbox_portfolio WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if not row:
                return jsonify({'ok': False, 'error': f'会话不存在: {session_id}'}), 404
            pf = SandboxPortfolio.from_row(tuple(row))
            trades = [dict(r) for r in conn.execute(
                "SELECT trade_id, trade_date, trade_time, symbol, stock_name, action, "
                "shares, price, total_amount, strategy, team_verdict, notes "
                "FROM mt_sandbox_trades WHERE session_id = ? ORDER BY trade_time DESC LIMIT 100",
                (session_id,)
            ).fetchall()]
            status_row = conn.execute(
                "SELECT status, updated_at, created_at FROM mt_sandbox_portfolio WHERE session_id = ?",
                (session_id,)
            ).fetchone()
        finally:
            conn.close()
        return jsonify({
            'ok': True,
            'session_id': pf.session_id,
            'scenario': pf.scenario,
            'scenario_days': pf.days,
            'initial_cash': pf.initial_cash,
            'current_cash': round(pf.current_cash, 2),
            'positions': pf.positions,
            'position_count': len(pf.positions),
            'is_frozen': pf.is_frozen,
            'risk_floor_pct': pf.risk_floor_pct,
            'status': status_row[0], 'updated_at': status_row[1], 'created_at': status_row[2],
            'trade_count': len(trades),
            'trades': trades,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:200]}), 500


@stock_sandbox_bp.route('/status', methods=['GET'])
def api_status():
    """沙盘状态概览 (默认活跃会话; ?session_id= 可只读查看任意历史会话)"""
    try:
        from engines.ai_stock_sandbox_engine import get_stock_sandbox, SandboxPortfolio
        sb = get_stock_sandbox()
        view_id = request.args.get('session_id')
        pf = None
        if view_id:
            conn0 = _db_conn()
            try:
                row = conn0.execute(
                    "SELECT session_id, scenario, scenario_days, initial_cash, current_cash, "
                    "positions_json, risk_floor_pct, is_frozen, start_date, current_date, "
                    "daily_high_watermark FROM mt_sandbox_portfolio WHERE session_id = ?",
                    (view_id,)
                ).fetchone()
            finally:
                conn0.close()
            if not row:
                return jsonify({'ok': False, 'error': f'会话不存在: {view_id}'}), 404
            pf = SandboxPortfolio.from_row(row)
        if pf is None:
            pf = sb.get_active_portfolio()
        
        import sqlite3
        conn = sqlite3.connect(str(__import__('os').path.join(
            __import__('pathlib').Path(__file__).resolve().parent.parent, 'database', 'app.db'
        )))
        
        # 最近交易数
        trade_cnt = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id = ?", (pf.session_id,)
        ).fetchone()[0]
        
        # 信号数
        signal_cnt = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_signals WHERE session_id = ?", (pf.session_id,)
        ).fetchone()[0]
        
        # 快照数
        snap_cnt = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_snapshots WHERE session_id = ?", (pf.session_id,)
        ).fetchone()[0]
        
        # 活跃 session 数
        session_cnt = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_portfolio WHERE is_frozen = 0"
        ).fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "ok": True,
            "session_id": pf.session_id,
            "scenario": pf.scenario,
            "scenario_days": pf.days,
            "initial_cash": pf.initial_cash,
            "current_cash": round(pf.current_cash, 2),
            "positions": pf.positions,
            "position_count": len(pf.positions),
            "trade_count": trade_cnt,
            "signal_count": signal_cnt,
            "snapshot_count": snap_cnt,
            "is_frozen": pf.is_frozen,
            "risk_floor_pct": pf.risk_floor_pct,
            "active_sessions": session_cnt,
            "daemon_running": _daemon_alive(sb),
            "viewing_session": pf.session_id,
            "viewing_frozen": pf.is_frozen,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@stock_sandbox_bp.route('/tick', methods=['POST', 'GET'])
def api_tick():
    """手动执行一次 tick"""
    try:
        from engines.ai_stock_sandbox_engine import get_stock_sandbox
        sb = get_stock_sandbox()
        result = sb.run_tick()
        
        # 简化返回
        return jsonify({
            "ok": True,
            "session_id": result.get("session_id"),
            "total_value": result.get("total_value"),
            "cash": result.get("cash"),
            "positions": result.get("positions"),
            "frozen": result.get("frozen"),
            "market_trend": result.get("market_trend"),
            "trade_count": sum(1 for r in result.get("results", []) if r.get("trade")),
            "trades": [
                {
                    "symbol": r['symbol'],
                    "name": r['name'],
                    "price": r['price'],
                    "change_pct": r['change_pct'],
                    "action": r['verdict']['final_action'],
                    "buy_score": r['verdict']['buy_score'],
                    "sell_score": r['verdict']['sell_score'],
                    "trade": r['trade'],
                    "risk_flags": r['verdict']['risk_flags'],
                }
                for r in result.get("results", [])
            ],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@stock_sandbox_bp.route('/simulate', methods=['POST'])
def api_simulate():
    """
    模拟一周/一年
    body JSON: {
        "days": 10,         # 或用 scenario
        "scenario": "WEEK" | "YEAR" | "CUSTOM"
    }
    """
    try:
        from engines.ai_stock_sandbox_engine import get_stock_sandbox
        
        data = request.get_json() or {}
        scenario = data.get('scenario', 'WEEK')
        days = data.get('days')
        
        sb = get_stock_sandbox()
        
        if scenario == "WEEK":
            report = sb.simulate_week()
        elif scenario == "YEAR":
            report = sb.simulate_year()
        elif days:
            report = sb.simulate_days(int(days), scenario=scenario)
        else:
            return jsonify({"ok": False, "error": "需要 scenario 或 days 参数"}), 400
        
        return jsonify({"ok": True, "report": report})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@stock_sandbox_bp.route('/daemon/start', methods=['POST'])
def api_daemon_start():
    """启动守护进程"""
    try:
        from engines.ai_stock_sandbox_engine import get_stock_sandbox
        sb = get_stock_sandbox()
        
        data = request.get_json() or {}
        interval = int(data.get('interval', 30))
        sb.start_daemon(interval=interval)
        
        return jsonify({
            "ok": True,
            "message": f"守护进程已启动 (interval={interval}s)",
            "daemon_running": _daemon_alive(sb),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@stock_sandbox_bp.route('/daemon/stop', methods=['POST'])
def api_daemon_stop():
    """停止守护进程"""
    try:
        from engines.ai_stock_sandbox_engine import get_stock_sandbox
        sb = get_stock_sandbox()
        sb.stop_daemon()
        return jsonify({"ok": True, "message": "守护进程已停止"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@stock_sandbox_bp.route('/trades', methods=['GET'])
def api_trades():
    """交易流水"""
    try:
        import sqlite3
        conn = sqlite3.connect(str(__import__('os').path.join(
            __import__('pathlib').Path(__file__).resolve().parent.parent, 'database', 'app.db'
        )))
        conn.row_factory = sqlite3.Row
        
        limit = min(int(request.args.get('limit', 50)), 200)
        session_id = request.args.get('session_id')
        
        if session_id:
            rows = conn.execute(
                "SELECT * FROM mt_sandbox_trades WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_sandbox_trades ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        
        conn.close()
        return jsonify({
            "ok": True,
            "count": len(rows),
            "trades": [dict(r) for r in rows],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@stock_sandbox_bp.route('/positions', methods=['GET'])
def api_positions():
    """当前持仓 — portfolio.positions_json 为空时用 mt_sandbox_trades 重算兜底"""
    try:
        from engines.ai_stock_sandbox_engine import get_stock_sandbox
        sb = get_stock_sandbox()
        pf = sb.get_active_portfolio()

        positions = list(pf.positions)

        # Fallback: 引擎 SELL 清仓后 positions_json 可能为空 (positions_json=[] 但 cash 已加回)
        # 用 mt_sandbox_trades 重算净持仓, 防止大盘持仓显示空
        if not positions:
            try:
                import sqlite3 as _sl
                from pathlib import Path as _P
                _db = str(_P(__file__).resolve().parent.parent / 'database' / 'app.db')
                _c = _sl.connect(_db); _c.row_factory = _sl.Row
                _rows = _c.execute("""
                    SELECT symbol, stock_name, action, shares, price
                    FROM mt_sandbox_trades WHERE action IN ('BUY','SELL') AND session_id = ?
                    ORDER BY trade_date, trade_time
                """, (pf.session_id,)).fetchall(); _c.close()
                if _rows:
                    _pos = {}; _cost = {}; _name = {}
                    for r in _rows:
                        s, n, a, q, p = r['symbol'], r['stock_name'], r['action'], r['shares'], r['price']
                        if a == 'BUY':
                            pc, pq = _cost.get(s, (0.0, 0)); nq = pq + q
                            _cost[s] = ((pc * pq + p * q) / nq if nq else 0, nq)
                            _pos[s] = _pos.get(s, 0) + q
                        else:
                            _pos[s] = _pos.get(s, 0) - q
                        if n and s not in _name:
                            _name[s] = n
                    positions = [
                        {'symbol': s, 'name': _name.get(s, s), 'shares': q, 'avg_cost': _cost[s][0]}
                        for s, q in _pos.items() if q > 0
                    ]
            except Exception:
                pass

        quotes = sb.data_provider.fetch_realtime(
            [s[0] for s in __import__('engines.ai_stock_sandbox_engine', fromlist=['WATCH_LIST_A']).WATCH_LIST_A]
        )

        price_map = {s['secid']: s['price'] for s in quotes.values()}
        total_value = pf.get_total_value(price_map)

        return jsonify({
            "ok": True,
            "session_id": pf.session_id,
            "total_value": round(total_value, 2),
            "initial_cash": pf.initial_cash,
            "cash": pf.current_cash,
            "positions": [
                {
                    "symbol": p['symbol'],
                    "name": p.get('name', ''),
                    "shares": p['shares'],
                    "avg_cost": round(p['avg_cost'], 2),
                    "current_price": price_map.get(p['symbol'], p.get('current_price', 0)),
                    "market_value": round(p['shares'] * price_map.get(p['symbol'], 0), 2),
                    "pnl": round((price_map.get(p['symbol'], p['avg_cost']) - p['avg_cost']) * p['shares'], 2),
                    "pnl_pct": round(
                        (price_map.get(p['symbol'], p['avg_cost']) - p['avg_cost']) / p['avg_cost'] * 100, 2
                    ),
                }
                for p in positions
            ],
            "is_frozen": pf.is_frozen,
            "risk_floor_value": round(pf.initial_cash * (1 - pf.risk_floor_pct / 100), 2),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@stock_sandbox_bp.route('/signals', methods=['GET'])
def api_signals():
    """策略信号池"""
    try:
        import sqlite3
        conn = sqlite3.connect(str(__import__('os').path.join(
            __import__('pathlib').Path(__file__).resolve().parent.parent, 'database', 'app.db'
        )))
        conn.row_factory = sqlite3.Row
        
        limit = min(int(request.args.get('limit', 30)), 200)
        rows = conn.execute(
            "SELECT * FROM mt_sandbox_signals ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        
        conn.close()
        return jsonify({
            "ok": True,
            "count": len(rows),
            "signals": [dict(r) for r in rows],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@stock_sandbox_bp.route('/reports', methods=['GET'])
def api_reports():
    """沙盘报告 — session 净值曲线"""
    try:
        import sqlite3
        conn = sqlite3.connect(str(__import__('os').path.join(
            __import__('pathlib').Path(__file__).resolve().parent.parent, 'database', 'app.db'
        )))
        conn.row_factory = sqlite3.Row
        
        # 最新 session
        session_row = conn.execute(
            "SELECT session_id, scenario, scenario_days, initial_cash, current_cash, "
            "is_frozen, start_date, updated_at "
            "FROM mt_sandbox_portfolio ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        
        if not session_row:
            conn.close()
            return jsonify({"ok": True, "sessions": [], "snapshots": []})
        
        session_id = session_row['session_id']
        
        # 净值快照
        snaps = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots WHERE session_id = ? ORDER BY snap_date ASC",
            (session_id,)
        ).fetchall()
        
        # 汇总统计
        trade_stats = conn.execute(
            "SELECT COUNT(*) as cnt, "
            "SUM(CASE WHEN action='BUY' THEN 1 ELSE 0 END) as buys, "
            "SUM(CASE WHEN action='SELL' THEN 1 ELSE 0 END) as sells "
            "FROM mt_sandbox_trades WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        
        conn.close()
        
        snapshots = [dict(s) for s in snaps]
        final_value = snapshots[-1]['total_value'] if snapshots else session_row['initial_cash']
        total_return = (final_value - session_row['initial_cash']) / session_row['initial_cash'] * 100
        max_dd = max((s.get('max_drawdown', 0) for s in snapshots), default=0)
        
        return jsonify({
            "ok": True,
            "session": dict(session_row),
            "snapshots": snapshots,
            "stats": {
                "snapshot_count": len(snapshots),
                "initial_cash": session_row['initial_cash'],
                "final_value": round(final_value, 2),
                "total_return_pct": round(total_return, 2),
                "max_drawdown_pct": round(max_dd, 2),
                "total_trades": trade_stats['cnt'] if trade_stats else 0,
                "buy_count": trade_stats['buys'] if trade_stats else 0,
                "sell_count": trade_stats['sells'] if trade_stats else 0,
            },
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# 导出
__all__ = ['stock_sandbox_bp']
