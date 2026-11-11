#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blueprints/finance_bank_bp.py — 古灵阁银行仪表板 REST API
=====================================================
24+ 端点覆盖: 总览 / 风控 / 归因 / 稽查 / 日报 / 行情 / 综合 / 会计总账 / 三表.

url_prefix: /api/finance/bank
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template

logger = logging.getLogger('finance_bank_bp')

bp = Blueprint('finance_bank', __name__, url_prefix='/api/finance/bank')


# ── DB 解析 ───────────────────────────────────────────────

def _db_path():
    """自动定位 app.db."""
    candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
        os.path.join(os.getcwd(), 'database', 'app.db'),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def _connect():
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ═══ v2.0 数据源隔离 ═══
# 数据层分三层:
#   LIVE     → mt_live_* (真实交易, LIVE-* session) — 当前空表
#   VAULT    → mt_vault_* (LedgerEngine 从 mt_sandbox_* 结转) — 古灵阁银行仪表盘主数据源
#   SANDBOX  → mt_sandbox_* (传统沙盘学习, SB-* session) — 沙盘模拟
#   LAB      → mt_lab_* (新 Lab Sandbox, LAB-* session) — AI 教师学习沙盘
# 古灵阁银行仪表盘应只看 LIVE + VAULT (来自传统沙盘结转), 不碰 LAB
# session_id 前缀约定:
#   SB-*  = 传统沙盘 SandBox
#   LAB-* = 新 Lab Sandbox (AI 教师学习)
#   LIVE-* = 真实交易
# 历史遗留: LedgerEngine Phase 1 从 mt_sandbox_trades 全量转换, 没有排除 LAB

_DATA_MODE = os.environ.get('GOBELIN_DATA_MODE', 'VAULT')  # LIVE / VAULT / SANDBOX (默认 VAULT)

def _ok(data=None, code='E_OK', http=200, data_source=None):
    """统一响应 + 数据源声明。所有端点返回 data_source 让前端清楚知道数据来自哪层."""
    if data_source is None:
        data_source = {
            'mode': _DATA_MODE,
            'mode_label': {'LIVE': '真实交易', 'VAULT': '古灵阁银行 (沙盘结转)',
                          'SANDBOX': '传统沙盘模拟'}[_DATA_MODE],
            'session_prefix': 'SB-* (传统沙盘)' if _DATA_MODE == 'VAULT' else (
                'LIVE-* (真实交易)' if _DATA_MODE == 'LIVE' else 'SB-* (传统沙盘)'),
        }
    return jsonify({'success': True, 'code': code, 'data': data,
                    'arch': '古灵阁银行 (Gobelin Bank) v2.0 + 数据源隔离',
                    'data_source': data_source}), http

def _sandbox_session_filter(table_alias='s'):
    """SQL 片段: 排除 LAB-* session (新沙盘学习), 只保留 SB-* 传统沙盘.
    LedgerEngine 当前结转的全是 SB-* session, 但为了未来 LAB-* 也被结转进 vault,
    这里做显式过滤防止混淆."""
    return f"{table_alias}.session_id NOT LIKE 'LAB-%' AND {table_alias}.session_id LIKE 'SB-%'"


def _err(msg, http=400):
    return jsonify({'success': False, 'code': 'E_INTERNAL', 'message': msg}), http


# ════════════════════════════════════════════════════════════
# 主账户解析 (单一真实账户, 不是 31 个沙盘 session 求和!)
# ════════════════════════════════════════════════════════════

_PRIMARY_SESSION_ID = os.environ.get('GOBELIN_PRIMARY_SESSION_ID', 'SB-e3105ea094db')
# SB-e3105ea094db = 2026-11-02 注资 1 万, 6 个交易日, total_value=11655.98, pnl=+1655.98

def _primary_session(conn):
    """返回当前应该展示的单一主账户 session_id.
    优先级: mt_live_account (真实层) → GOBELIN_PRIMARY_SESSION_ID 环境变量 → 默认 SB-e3105ea094db.
    绝对不能把多个沙盘 session 加总成一个"总资产"."""
    # 1. 真实层优先 (LIVE 层是单账户设计, 无 session_id 字段, 用表是否有数据判断)
    try:
        live_cnt = conn.execute("SELECT COUNT(*) FROM mt_live_account").fetchone()[0]
        pos_cnt = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
        if live_cnt > 0 or pos_cnt > 0:
            return 'LIVE_REAL_ACCOUNT', 'LIVE', '真实交易账户'
    except Exception:
        pass
    # 2. 指定 session 验证存在
    sid = _PRIMARY_SESSION_ID
    try:
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM mt_sandbox_snapshots WHERE session_id=? AND {_sandbox_session_filter('mt_sandbox_snapshots')}",
            (sid,)
        ).fetchone()[0]
        if cnt > 0:
            return sid, 'SANDBOX_SINGLE', '沙盘单账户演示 (真实层未初始化)'
    except Exception:
        pass
    # 3. fallback: pnl 非零 + 最近活跃
    try:
        row = conn.execute(
            f"SELECT session_id FROM mt_sandbox_snapshots "
            f"WHERE {_sandbox_session_filter('mt_sandbox_snapshots')} AND pnl_amount > 0 "
            f"ORDER BY snap_date DESC LIMIT 1"
        ).fetchone()
        if row:
            return row['session_id'], 'SANDBOX_SINGLE', '沙盘单账户演示 (真实层未初始化)'
    except Exception:
        pass
    return _PRIMARY_SESSION_ID, 'SANDBOX_SINGLE', '沙盘单账户演示 (fallback)'


@bp.get('/overview')
def api_overview():
    """银行级总览 — 单一主账户视图 (优先 LIVE 真实层, fallback SANDBOX)."""
    try:
        conn = _connect()
        today = datetime.now().strftime('%Y-%m-%d')
        primary_sid, data_layer, layer_label = _primary_session(conn)

        if data_layer == 'LIVE':
            # ═══ LIVE 真实层数据源 (mt_live_* 无 session_id, 单账户设计) ═══
            acc = conn.execute(
                "SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1"
            ).fetchone()
            positions = conn.execute(
                "SELECT symbol, name as stock_name, qty, "
                "(qty * price) as market_value, avg_cost, price as last_price, "
                "pnl, pnl_pct, today_pnl FROM mt_live_position ORDER BY qty DESC"
            ).fetchall()
            trades_cnt = conn.execute("SELECT COUNT(*) FROM mt_live_trade_log").fetchone()[0]
            if acc:
                total_assets = float(acc['total_assets'] or 0)
                total_pnl = float(acc['pnl'] or 0)
            else:
                total_assets = sum(float(p['market_value'] or 0) for p in positions)
                total_pnl = sum(float(p['pnl'] or 0) for p in positions)

            # today_pnl = Σ (腾讯现价 - 腾讯昨收) × qty  ← 正确的今日盈亏口径
            today_pnl = round(sum(float(p['today_pnl'] or 0) for p in positions), 2)

            initial_capital = 10000.0  # LIVE 层默认初始资金
            conn.close()

            return _ok({
                'primary_session_id': primary_sid,
                'account_label': layer_label,
                'initial_capital': round(initial_capital, 2),
                'total_assets': round(total_assets, 2),
                'total_pnl': round(total_pnl, 2),
                'total_pnl_pct': round(total_pnl / initial_capital * 100, 2) if initial_capital > 0 else 0,
                'position_count': len(positions),
                'positions': [dict(p) for p in positions[:5]],
                'total_trades': trades_cnt,
                'today_trades': 0,
                'today_pnl': today_pnl,
                'today_pnl_pct': round(today_pnl / total_assets * 100, 2) if total_assets > 0 else 0,
                'total_sessions': 1,
                'active_sessions': 1,
                'risk_level': 'LIVE',
                'risk_score': 0,
                'report_date': today,
                'generated_at': datetime.now().isoformat(),
            }, data_source={
                'mode': 'LIVE',
                'mode_label': '真实交易账户 (mt_live_* 层)',
                'session_prefix': '单账户 (无 session_id)',
                'initial_capital': initial_capital,
                '⚠️': 'LIVE 真实层已初始化 — 数据源切换完成',
            })

        # ═══ SANDBOX/VAULT 沙盘结转层 (原有逻辑) ═══
        latest = conn.execute(
            "SELECT s.total_value, s.pnl_amount, s.cash_value, s.position_value "
            "FROM mt_sandbox_snapshots s "
            "WHERE s.session_id=? "
            "AND s.snap_date=(SELECT MAX(snap_date) FROM mt_sandbox_snapshots WHERE session_id=s.session_id)",
            (primary_sid,)
        ).fetchone()

        if not latest:
            return _ok({
                'total_assets': 0, 'total_pnl': 0, 'today_pnl': 0,
                'report_date': today, 'generated_at': datetime.now().isoformat(),
                'primary_session': primary_sid, 'data_source': f'{data_layer} ({layer_label})',
                'note': '⚠️ 主账户 session 找不到 snapshot, 请先检查 DB',
            })

        total_assets = float(latest['total_value'] or 0)
        total_pnl = float(latest['pnl_amount'] or 0)

        # 今日数据 (今日持仓涨跌, 从 mt_live_position.today_pnl 聚合)
        # today_pnl = Σ (腾讯现价 - 腾讯昨收) × qty  ← 正确的今日盈亏口径
        today_tp = conn.execute(
            "SELECT COALESCE(SUM(today_pnl), 0) FROM mt_live_position"
        ).fetchone()[0]
        # 如果 LIVE 层没数据, fallback 到 snapshots 的今日变化
        if not today_tp:
            today_pnl_row = conn.execute(
                "SELECT total_value FROM mt_sandbox_snapshots WHERE session_id=? "
                "ORDER BY snap_date DESC LIMIT 2",
                (primary_sid,)
            ).fetchall()
            if len(today_pnl_row) == 2:
                today_tp = float(today_pnl_row[0]['total_value']) - float(today_pnl_row[1]['total_value'])
        today_pnl = round(float(today_tp or 0), 2)

        # Trades (主账户)
        total_trades = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id=?", (primary_sid,)
        ).fetchone()[0]
        today_trades = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id=? AND trade_date=?",
            (primary_sid, today)
        ).fetchone()[0]

        # 持仓数 (主账户)
        position_cnt = conn.execute(
            "SELECT COUNT(*) FROM mt_vault_positions WHERE session_id=?", (primary_sid,)
        ).fetchone()[0]

        # 初始资金 (snap_date 最早那行的 total_value - pnl)
        init_row = conn.execute(
            "SELECT total_value, pnl_amount FROM mt_sandbox_snapshots WHERE session_id=? "
            "ORDER BY snap_date ASC, rowid ASC LIMIT 1",
            (primary_sid,)
        ).fetchone()
        initial_capital = (float(init_row['total_value'] or 0) - float(init_row['pnl_amount'] or 0)) if init_row else 10000

        # 风控 (主账户)
        risk_row = conn.execute(
            "SELECT risk_level, risk_score FROM mt_vault_risk_snapshot WHERE session_id=? "
            "ORDER BY rowid DESC LIMIT 1", (primary_sid,)
        ).fetchone()

        # 持仓明细 (主账户)
        positions = conn.execute(
            "SELECT symbol, stock_name, qty, market_value, avg_cost FROM mt_vault_positions WHERE session_id=?",
            (primary_sid,)
        ).fetchall()

        conn.close()

        return _ok({
            # 账户基础
            'primary_session_id': primary_sid,
            'account_label': layer_label,
            'initial_capital': round(initial_capital, 2),
            # 核心指标 (单一账户)
            'total_assets': round(total_assets, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round(total_pnl / initial_capital * 100, 4) if initial_capital > 0 else 0,
            'today_pnl': round(today_pnl, 2),
            'today_pnl_pct': round(today_pnl / total_assets * 100, 4) if total_assets > 0 else 0,
            # 交易
            'today_trades': today_trades,
            'total_trades': total_trades,
            'position_count': position_cnt,
            # 持仓快速预览
            'positions': [dict(p) for p in positions[:5]],
            # 风控
            'risk_level': risk_row['risk_level'] if risk_row else 'UNKNOWN',
            'risk_score': float(risk_row['risk_score'] or 0) if risk_row else 0,
            # 报告
            'report_date': today,
            'generated_at': datetime.now().isoformat(),
        }, data_source={
            'mode': 'SINGLE_ACCOUNT',
            'mode_label': f'单一主账户 ({layer_label})',
            'session_id': primary_sid,
            'layer': data_layer,
            'initial_capital': initial_capital,
            '⚠️': 'finance_bank_bp v2.1 — 从"31 个沙盘求和"修正为"单一主账户真实视图"',
        })
    except Exception as e:
        logger.error(f"overview error: {e}")
        return _err(str(e))


@bp.get('/pnl-breakdown')
def api_pnl_breakdown():
    """📊 资产结构分解 — 已实现 vs 未实现 vs 今日."""
    try:
        conn = _connect()
        acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
        positions = conn.execute("SELECT * FROM mt_live_position").fetchall()

        if not acc:
            conn.close()
            return _ok({'note': 'LIVE 层未初始化'})

        initial = float(acc['initial_cash'] or 10000)
        cash = float(acc['cash'] or acc['available'] or 0)
        mv = float(acc['market_value'] or 0)
        total = round(cash + mv, 2)
        total_pnl = round(total - initial, 2)
        today_pnl = round(sum(float(p['today_pnl'] or 0) for p in positions), 2)
        unrealized = round(sum(float(p['pnl'] or 0) for p in positions), 2)
        realized = round(total_pnl - unrealized, 2)  # 已实现 = 累计 - 未实现

        conn.close()
        return _ok({
            'initial_capital': round(initial, 2),
            'cash': round(cash, 2),
            'market_value': round(mv, 2),
            'total_assets': total,
            'total_pnl': total_pnl,
            'realized_pnl': realized,
            'unrealized_pnl': unrealized,
            'today_pnl': today_pnl,
            'positions': [dict(p) for p in positions],
            'data_source': '腾讯实时行情 API → mt_live_*',
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/sessions')
def api_sessions():
    """所有 session 列表 + 收益率排名."""
    try:
        conn = _connect()
        rows = conn.execute(
            f"SELECT DISTINCT session_id FROM mt_sandbox_snapshots s WHERE {_sandbox_session_filter('s')} ORDER BY session_id"
        ).fetchall()
        results = []
        for r in rows:
            sid = r['session_id']
            first = conn.execute(
                "SELECT total_value, snap_date FROM mt_sandbox_snapshots "
                "WHERE session_id=? ORDER BY snap_date ASC LIMIT 1", (sid,)
            ).fetchone()
            last = conn.execute(
                "SELECT total_value, snap_date FROM mt_sandbox_snapshots "
                "WHERE session_id=? ORDER BY snap_date DESC LIMIT 1", (sid,)
            ).fetchone()
            if first and last and float(first['total_value'] or 0) > 0:
                ret = float(last['total_value']) / float(first['total_value']) - 1
            else:
                ret = 0.0
            portfolio = conn.execute(
                "SELECT scenario, status, is_frozen FROM mt_sandbox_portfolio "
                "WHERE session_id=?", (sid,)
            ).fetchone()
            risk = conn.execute(
                "SELECT risk_score, risk_level, sharpe, max_drawdown FROM mt_vault_risk_snapshot "
                "WHERE session_id=?", (sid,)
            ).fetchone()
            results.append({
                'session_id': sid,
                'start_date': first['snap_date'] if first else None,
                'end_date': last['snap_date'] if last else None,
                'total_return_pct': round(ret * 100, 2),
                'scenario': portfolio['scenario'] if portfolio else None,
                'status': portfolio['status'] if portfolio else None,
                'is_frozen': portfolio['is_frozen'] if portfolio else 0,
                'risk_score': round(risk['risk_score'], 1) if risk else None,
                'risk_level': risk['risk_level'] if risk else None,
                'sharpe': round(risk['sharpe'], 3) if risk else None,
                'max_drawdown': round(risk['max_drawdown'], 4) if risk else None,
            })

        # 按收益率排序
        sort_by = request.args.get('sort', 'return')
        if sort_by == 'return':
            results.sort(key=lambda x: -x['total_return_pct'])
        elif sort_by == 'risk':
            results.sort(key=lambda x: x.get('risk_score') or 999)

        conn.close()
        return _ok(results)
    except Exception as e:
        return _err(str(e))


@bp.get('/sessions/<session_id>')
def api_session_detail(session_id):
    """单 session 完整四维数据."""
    try:
        conn = _connect()

        overview = conn.execute(
            "SELECT * FROM mt_sandbox_portfolio WHERE session_id=?", (session_id,)
        ).fetchone()
        snapshots = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots WHERE session_id=? ORDER BY snap_date ASC",
            (session_id,)
        ).fetchall()
        trades = conn.execute(
            "SELECT * FROM mt_sandbox_trades WHERE session_id=? ORDER BY trade_date",
            (session_id,)
        ).fetchall()
        risk = conn.execute(
            "SELECT * FROM mt_vault_risk_snapshot WHERE session_id=?", (session_id,)
        ).fetchone()
        attrs = conn.execute(
            "SELECT * FROM mt_vault_attribution WHERE session_id=? "
            "ORDER BY attr_type, metric", (session_id,)
        ).fetchall()

        conn.close()

        return _ok({
            'portfolio': dict(overview) if overview else None,
            'snapshots': [dict(s) for s in snapshots],
            'trades': [dict(t) for t in trades],
            'risk': dict(risk) if risk else None,
            'attributions': [dict(a) for a in attrs],
            'snapshot_count': len(snapshots),
            'trade_count': len(trades),
        })
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# 风控 RISK
# ════════════════════════════════════════════════════════════

@bp.get('/risk/summary')
def api_risk_summary():
    """10 大风控指标汇总 (全 session)."""
    try:
        conn = _connect()
        rows = conn.execute(
            f"SELECT * FROM mt_vault_risk_snapshot r WHERE {_sandbox_session_filter('r')} ORDER BY risk_score DESC"
        ).fetchall()
        conn.close()

        if not rows:
            return _ok({'note': '暂无风控数据, 请先跑 RiskEngine', 'rows': []})

        # 全 portfolio 平均指标
        avg = {}
        for metric in ['var_95', 'cvar_95', 'sharpe', 'calmar', 'sortino',
                       'win_rate', 'profit_factor', 'max_drawdown', 'turnover', 'beta',
                       'risk_score', 'total_return', 'annualized_return', 'annualized_volatility']:
            vals = [float(r[metric] or 0) for r in rows]
            avg[metric] = round(sum(vals) / len(vals), 6) if vals else 0

        level_dist = {}
        for r in rows:
            lv = r['risk_level'] or 'UNKNOWN'
            level_dist[lv] = level_dist.get(lv, 0) + 1

        # LIVE 层有数据时, 往 sessions 里加一条 LIVE_REAL_ACCOUNT
        live_sessions = list(rows)
        conn2 = _connect()
        live_pos_cnt = conn2.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
        if live_pos_cnt > 0:
            live_row = conn2.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
            if live_row:
                live_entry = {
                    'session_id': 'LIVE_REAL_ACCOUNT',
                    'risk_level': 'LIVE',
                    'risk_score': 0,
                    'total_return': float(live_row['pnl'] or 0) / float(live_row['initial_cash'] or 10000) * 100,
                    'var_95': 0, 'cvar_95': 0, 'sharpe': 0,
                    'calmar': 0, 'sortino': 0, 'win_rate': 0,
                    'profit_factor': 0, 'max_drawdown': 0, 'turnover': 0, 'beta': 0,
                }
                live_sessions.insert(0, live_entry)
                level_dist['LIVE'] = level_dist.get('LIVE', 0) + 1

        return _ok({
            'snapshot_count': len(rows),
            'averages': avg,
            'level_distribution': level_dist,
            'sessions': [dict(r) for r in live_sessions],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/risk/<session_id>')
def api_risk_detail(session_id):
    """单 session 风控详情."""
    try:
        conn = _connect()
        risk = conn.execute(
            "SELECT * FROM mt_vault_risk_snapshot WHERE session_id=?", (session_id,)
        ).fetchone()
        conn.close()
        if not risk:
            return _ok({'note': f'{session_id} 暂无风控数据'})
        return _ok(dict(risk))
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# 归因 ATTRIBUTION
# ════════════════════════════════════════════════════════════

@bp.get('/attribution/industry')
def api_attr_industry():
    """Brinson 行业归因汇总."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT industry, metric, SUM(value) as total_value "
            "FROM mt_vault_attribution WHERE attr_type='INDUSTRY' "
            "GROUP BY industry, metric "
            "ORDER BY industry"
        ).fetchall()

        industries = {}
        for r in rows:
            ind = r['industry'] or 'Unknown'
            if ind not in industries:
                industries[ind] = {}
            industries[ind][r['metric']] = round(float(r['total_value'] or 0), 4)

        # 再按 total_contribution 排序
        sorted_industries = sorted(industries.items(),
                                   key=lambda x: -abs(x[1].get('contribution', 0)))

        conn.close()
        return _ok({
            'industries': [{'industry': k, 'metrics': v} for k, v in sorted_industries],
            'count': len(industries),
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/attribution/trade')
def api_attr_trade():
    """交易归因 TOP 盈利/亏损 trade."""
    try:
        conn = _connect()
        limit = int(request.args.get('limit', 10))

        best = conn.execute(
            "SELECT session_id, symbol, industry, value, details "
            "FROM mt_vault_attribution WHERE attr_type='TRADE' AND value IS NOT NULL "
            "ORDER BY value DESC LIMIT ?", (limit,)
        ).fetchall()
        worst = conn.execute(
            "SELECT session_id, symbol, industry, value, details "
            "FROM mt_vault_attribution WHERE attr_type='TRADE' AND value IS NOT NULL "
            "ORDER BY value ASC LIMIT ?", (limit,)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM mt_vault_attribution WHERE attr_type='TRADE'"
        ).fetchone()

        conn.close()
        return _ok({
            'best_trades': [dict(r) for r in best],
            'worst_trades': [dict(r) for r in worst],
            'total_trade_attr': total['cnt'],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/attribution/signal')
def api_attr_signal():
    """信号归因 IC 排名."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT session_id, metric, value, details FROM mt_vault_attribution "
            "WHERE attr_type='SIGNAL' AND metric='ic' "
            "ORDER BY value DESC"
        ).fetchall()
        conn.close()

        return _ok({
            'signal_ics': [dict(r) for r in rows],
            'interpretation': {
                'IC > 0.3': '信号得分与收益强正相关 (好信号)',
                '0 < IC < 0.3': '弱正相关 (信号尚可)',
                '-0.3 < IC < 0': '弱负相关 (信号质量一般)',
                'IC < -0.3': '强负相关 (信号背离严重)',
            },
        })
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# 稽查 AUDIT
# ════════════════════════════════════════════════════════════

@bp.get('/audit/summary')
def api_audit_summary():
    """12 维度稽查通过率."""
    try:
        conn = _connect()
        today = datetime.now().strftime('%Y-%m-%d')
        latest_date = today   # ← 初始值, 避免 UnboundLocalError

        dims = conn.execute(
            "SELECT dimension, level, verdict, COUNT(*) as cnt "
            "FROM mt_vault_audit_log WHERE date(created_at)=? "
            "GROUP BY dimension, level, verdict", (today,)
        ).fetchall()

        # 如果今天没数据, 取最新
        if not dims:
            row = conn.execute(
                "SELECT date(MAX(created_at)) FROM mt_vault_audit_log"
            ).fetchone()
            latest_date = row[0] if row and row[0] else today
            if latest_date != today:
                dims = conn.execute(
                    "SELECT dimension, level, verdict, COUNT(*) as cnt "
                    "FROM mt_vault_audit_log WHERE date(created_at)=? "
                    "GROUP BY dimension, level, verdict", (latest_date,)
                ).fetchall()

        summary = {}
        total_pass = 0
        total_fail = 0
        total_warn = 0
        for d in dims:
            dim = d['dimension']
            if dim not in summary:
                summary[dim] = {'PASS': 0, 'WARN': 0, 'FAIL': 0, 'level': d['level']}
            verdict = d['verdict'] or d['level']
            if verdict in ('PASS', 'INFO'):
                summary[dim]['PASS'] += d['cnt']
                total_pass += d['cnt']
            elif verdict in ('WARN',):
                summary[dim]['WARN'] += d['cnt']
                total_warn += d['cnt']
            else:
                summary[dim]['FAIL'] += d['cnt']
                total_fail += d['cnt']

        total = total_pass + total_warn + total_fail
        conn.close()

        return _ok({
            'date': latest_date,
            'dimensions': summary,
            'pass_rate': round(total_pass / total * 100, 1) if total > 0 else 100,
            'pass': total_pass, 'warn': total_warn, 'fail': total_fail,
            'total': total,
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/audit/issues')
def api_audit_issues():
    """未解决的 WARN/FAIL."""
    try:
        conn = _connect()
        resolved = request.args.get('resolved', '0')
        if resolved == '1':
            rows = conn.execute(
                "SELECT * FROM mt_vault_audit_log WHERE verdict IN ('WARN','FAIL') AND resolved=1 "
                "ORDER BY rowid DESC LIMIT 50"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_vault_audit_log WHERE verdict IN ('WARN','FAIL') AND resolved=0 "
                "ORDER BY rowid DESC LIMIT 50"
            ).fetchall()
        conn.close()
        return _ok([dict(r) for r in rows])
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# 日报 REPORT
# ════════════════════════════════════════════════════════════

@bp.get('/report/latest')
def api_report_latest():
    """最新日报 JSON."""
    try:
        from engines.finance_daily_report import DailyReportGenerator, _resolve_runtime
        rt = _resolve_runtime()
        files = sorted([f for f in os.listdir(rt) if f.startswith('bank_report_') and f.endswith('.json')],
                       reverse=True)
        if not files:
            return _ok({'note': '暂无日报, 可调用 /report/generate 生成'})
        path = os.path.join(rt, files[0])
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return _ok(data)
    except Exception as e:
        return _err(str(e))


@bp.get('/report/<date>')
def api_report_by_date(date):
    """指定日期日报."""
    try:
        from engines.finance_daily_report import _resolve_runtime
        rt = _resolve_runtime()
        path = os.path.join(rt, f'bank_report_{date}.json')
        if not os.path.exists(path):
            return _err(f'{date} 日报不存在', 404)
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return _ok(data)
    except Exception as e:
        return _err(str(e))


@bp.post('/report/generate')
def api_report_generate():
    """手动触发日报生成."""
    try:
        data = request.get_json(silent=True) or {}
        date = data.get('date') or request.args.get('date')
        from engines.finance_daily_report import DailyReportGenerator
        gen = DailyReportGenerator(report_date=date)
        report = gen.generate()
        json_path, txt_path = gen.write_files(report)
        gen.write_knowledge(report)
        return _ok({
            'generated': True,
            'date': report['report_date'],
            'json_path': json_path,
            'txt_path': txt_path,
            'health_score': report['health_score'],
        })
    except Exception as e:
        logger.error(f"report generate error: {e}", exc_info=True)
        return _err(str(e), 500)


# ════════════════════════════════════════════════════════════
# 行情 MARKET
# ════════════════════════════════════════════════════════════

@bp.get('/market/topmovers')
def api_market_topmovers():
    """TOP 涨跌 (从 trades 推断)."""
    try:
        conn = _connect()

        # 按 symbol 聚合交易 (BUY → 买入均价, SELL → 卖出均价, 计算推断涨跌)
        trades = conn.execute(
            f"SELECT symbol, action, price, shares, trade_date FROM mt_sandbox_trades t "
            f"WHERE {_sandbox_session_filter('t')} ORDER BY trade_date, trade_time"
        ).fetchall()

        symbol_buy_avg = {}  # symbol -> (total_cost, total_shares)
        symbol_sell_avg = {}

        for t in trades:
            sym = t['symbol']
            price = float(t['price'] or 0)
            shares = int(t['shares'] or 0)
            if t['action'].upper() == 'BUY':
                prev = symbol_buy_avg.get(sym, (0.0, 0))
                symbol_buy_avg[sym] = (prev[0] + price * shares, prev[1] + shares)
            elif t['action'].upper() == 'SELL':
                prev = symbol_sell_avg.get(sym, (0.0, 0))
                symbol_sell_avg[sym] = (prev[0] + price * shares, prev[1] + shares)

        movers = []
        for sym in set(list(symbol_buy_avg.keys()) + list(symbol_sell_avg.keys())):
            buy_cost, buy_shares = symbol_buy_avg.get(sym, (0.0, 0))
            sell_cost, sell_shares = symbol_sell_avg.get(sym, (0.0, 0))
            if buy_shares > 0 and sell_shares > 0:
                buy_px = buy_cost / buy_shares
                sell_px = sell_cost / sell_shares
                change = sell_px / buy_px - 1
                movers.append({
                    'symbol': sym,
                    'avg_buy_price': round(buy_px, 4),
                    'avg_sell_price': round(sell_px, 4),
                    'inferred_change_pct': round(change * 100, 2),
                    'buy_shares': buy_shares,
                    'sell_shares': sell_shares,
                })

        movers.sort(key=lambda x: -x['inferred_change_pct'])
        conn.close()

        limit = int(request.args.get('limit', 10))
        top = movers[:limit]
        bottom = movers[-limit:] if len(movers) > limit else list(reversed(movers))

        return _ok({
            'total_symbols': len(movers),
            'top_gainers': top,
            'top_losers': list(reversed(bottom)),
        })
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# 综合 HOLISTIC
# ════════════════════════════════════════════════════════════

@bp.get('/holistic')
def api_holistic():
    """一站式综合: overview + risk + attribution + audit."""
    try:
        overview, _ = api_overview()
        risk, _ = api_risk_summary()
        attr_ind, _ = api_attr_industry()
        audit, _ = api_audit_summary()

        return _ok({
            'overview': overview.get_json() if hasattr(overview, 'get_json') else overview,
            'risk': risk.get_json() if hasattr(risk, 'get_json') else risk,
            'attribution_industry': attr_ind.get_json() if hasattr(attr_ind, 'get_json') else attr_ind,
            'audit': audit.get_json() if hasattr(audit, 'get_json') else audit,
            'generated_at': datetime.now().isoformat(),
        })
    except Exception as e:
        return _err(str(e))


# ── 状态接口 ──────────────────────────────────────────────

@bp.get('/status')
def api_status():
    """Blueprint 健康状态."""
    try:
        conn = _connect()
        tables = ['mt_sandbox_snapshots', 'mt_sandbox_trades', 'mt_sandbox_portfolio',
                  'mt_sandbox_signals', 'mt_vault_risk_snapshot', 'mt_vault_attribution',
                  'mt_vault_audit_log']
        counts = {}
        for t in tables:
            try:
                counts[t] = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            except Exception:
                counts[t] = 'N/A'
        conn.close()

        endpoints = [
            ('GET',  '/overview'),
            ('GET',  '/sessions'),
            ('GET',  '/sessions/<id>'),
            ('GET',  '/risk/summary'),
            ('GET',  '/risk/<id>'),
            ('GET',  '/attribution/industry'),
            ('GET',  '/attribution/trade'),
            ('GET',  '/attribution/signal'),
            ('GET',  '/audit/summary'),
            ('GET',  '/audit/issues'),
            ('GET',  '/report/latest'),
            ('GET',  '/report/<date>'),
            ('POST', '/report/generate'),
            ('GET',  '/market/topmovers'),
            ('GET',  '/holistic'),
        ]

        return _ok({
            'name': '古灵阁银行 Gobelin Bank',
            'version': '1.0.0',
            'db_path': _db_path(),
            'table_counts': counts,
            'endpoints': [f'{m} {p}' for m, p in endpoints],
        })
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# 会计总账 LEDGER / JOURNAL / 三表 / 异常 / 持仓 / 对手方
# ════════════════════════════════════════════════════════════

@bp.get('/ledger/overview')
def api_ledger_overview():
    """总账科目余额 (所有 session × 10 科目)."""
    try:
        conn = _connect()
        period = request.args.get('period', datetime.now().strftime('%Y-%m'))
        rows = conn.execute(
            "SELECT * FROM mt_vault_ledger WHERE period=? ORDER BY session_id, account_code",
            (period,)
        ).fetchall()
        conn.close()
        # 按 session 分组
        grouped = {}
        for r in rows:
            sid = r['session_id']
            if sid not in grouped:
                grouped[sid] = {'session_id': sid, 'period': period, 'accounts': {}}
            grouped[sid]['accounts'][r['account_code']] = {
                'code': r['account_code'],
                'name': r['account_name'],
                'type': r['account_type'],
                'balance': round(float(r['balance'] or 0), 2),
                'debit': round(float(r['debit'] or 0), 4),
                'credit': round(float(r['credit'] or 0), 4),
            }
        return _ok({
            'period': period,
            'session_count': len(grouped),
            'sessions': list(grouped.values()),
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/ledger/journal')
def api_ledger_journal():
    """日记账凭证 (分页)."""
    try:
        conn = _connect()
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        session_id = request.args.get('session_id')
        voucher_no = request.args.get('voucher_no')

        sql = "SELECT * FROM mt_vault_journal WHERE 1=1"
        params = []
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        if voucher_no:
            sql += " AND voucher_no=?"
            params.append(voucher_no)

        count = conn.execute(sql.replace('SELECT *', 'SELECT COUNT(*)'), params).fetchone()[0]
        sql += " ORDER BY journal_date DESC, voucher_no, entry_seq LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()

        # 按 voucher 分组
        by_voucher = {}
        for r in rows:
            vn = r['voucher_no']
            if vn not in by_voucher:
                by_voucher[vn] = {'voucher_no': vn, 'session_id': r['session_id'],
                                  'date': r['journal_date'], 'summary': r['summary'],
                                  'entries': []}
            by_voucher[vn]['entries'].append({
                'seq': r['entry_seq'], 'code': r['account_code'],
                'name': r['account_name'],
                'debit': round(float(r['debit'] or 0), 2),
                'credit': round(float(r['credit'] or 0), 2),
            })

        conn.close()
        return _ok({
            'total': count, 'limit': limit, 'offset': offset,
            'vouchers': list(by_voucher.values()),
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/balance-sheet')
def api_balance_sheet():
    """最新资产负债表."""
    try:
        conn = _connect()
        # 最新日期
        latest = conn.execute("SELECT MAX(report_date) FROM mt_vault_balance_sheet").fetchone()[0]
        sid = request.args.get('session_id')
        if sid:
            rows = conn.execute(
                "SELECT * FROM mt_vault_balance_sheet WHERE session_id=? AND report_date=?",
                (sid, latest)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_vault_balance_sheet WHERE report_date=?", (latest,)
            ).fetchall()

        # 汇总
        agg = {
            'cash': 0, 'receivables': 0, 'positions_market_value': 0, 'total_assets': 0,
            'payables': 0, 'margin_debt': 0, 'total_liabilities': 0,
            'capital': 0, 'accumulated_pnl': 0, 'total_equity': 0,
        }
        balanced_count = 0
        for r in rows:
            for k in agg:
                agg[k] += float(r[k] or 0)
            balanced_count += int(r['is_balanced'] or 0)
        agg['balanced_sessions'] = balanced_count
        agg['total_sessions'] = len(rows)
        agg['report_date'] = latest

        conn.close()
        return _ok({
            'report_date': latest,
            'aggregate': {k: round(v, 2) if isinstance(v, float) else v
                          for k, v in agg.items()},
            'sessions': [dict(r) for r in rows],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/income-stmt')
def api_income_stmt():
    """最新利润表."""
    try:
        conn = _connect()
        period = request.args.get('period')
        if not period:
            period = conn.execute("SELECT MAX(period) FROM mt_vault_income_stmt").fetchone()[0]
        sid = request.args.get('session_id')
        if sid:
            rows = conn.execute(
                "SELECT * FROM mt_vault_income_stmt WHERE session_id=? AND period=?",
                (sid, period)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_vault_income_stmt WHERE period=?", (period,)
            ).fetchall()

        conn.close()
        return _ok({
            'period': period,
            'sessions': [dict(r) for r in rows],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/cash-flow')
def api_cash_flow():
    """现金流量表."""
    try:
        conn = _connect()
        period = request.args.get('period')
        sid = request.args.get('session_id')
        sql = "SELECT * FROM mt_vault_cash_flow WHERE 1=1"
        params = []
        if period:
            sql += " AND period=?"
            params.append(period)
        if sid:
            sql += " AND session_id=?"
            params.append(sid)
        sql += " ORDER BY period, activity_type"
        rows = conn.execute(sql, params).fetchall()

        # 按 activity_type 汇总
        activities = {}
        for r in rows:
            at = r['activity_type']
            if at not in activities:
                activities[at] = {'inflow': 0, 'outflow': 0, 'net': 0, 'count': 0}
            activities[at]['inflow'] += float(r['inflow'] or 0)
            activities[at]['outflow'] += float(r['outflow'] or 0)
            activities[at]['net'] += float(r['net'] or 0)
            activities[at]['count'] += int(r['transaction_count'] or 0)
        for k in activities:
            for kk in ('inflow', 'outflow', 'net'):
                activities[k][kk] = round(activities[k][kk], 2)

        conn.close()
        return _ok({
            'activities': activities,
            'details': [dict(r) for r in rows],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/alerts')
def api_alerts():
    """异常预警列表."""
    try:
        conn = _connect()
        limit = int(request.args.get('limit', 100))
        alert_type = request.args.get('type')
        level = request.args.get('level')
        verdict = request.args.get('verdict', 'OPEN')
        sid = request.args.get('session_id')

        sql = "SELECT * FROM mt_vault_alert WHERE 1=1"
        params = []
        if alert_type:
            sql += " AND alert_type=?"; params.append(alert_type)
        if level:
            sql += " AND level=?"; params.append(level)
        if verdict:
            sql += " AND verdict=?"; params.append(verdict)
        if sid:
            sql += " AND session_id=?"; params.append(sid)
        sql += " ORDER BY CASE level WHEN 'CRITICAL' THEN 1 WHEN 'ERROR' THEN 2 WHEN 'WARN' THEN 3 WHEN 'INFO' THEN 4 ELSE 5 END LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

        # 按 type 汇总
        by_type = {}
        for r in rows:
            t = r['alert_type']
            if t not in by_type:
                by_type[t] = {'total': 0, 'critical': 0, 'warn': 0, 'info': 0}
            by_type[t]['total'] += 1
            lv = r['level'].lower()
            if lv in by_type[t]:
                by_type[t][lv] += 1

        conn.close()
        return _ok({
            'total': len(rows),
            'by_type': by_type,
            'alerts': [dict(r) for r in rows],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/counterparties')
def api_counterparties():
    """交易对手汇总."""
    try:
        conn = _connect()
        sid = request.args.get('session_id')
        if sid:
            rows = conn.execute(
                "SELECT * FROM mt_vault_counterparty WHERE session_id=? ORDER BY total_volume DESC",
                (sid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_vault_counterparty ORDER BY total_volume DESC"
            ).fetchall()

        # 全局汇总
        agg = {
            'total_trades': 0, 'total_volume': 0, 'total_fees': 0,
        }
        for r in rows:
            agg['total_trades'] += int(r['trade_count'] or 0)
            agg['total_volume'] += float(r['total_volume'] or 0)
            agg['total_fees'] += float(r['total_fees'] or 0)
        for k in ('total_volume', 'total_fees'):
            agg[k] = round(agg[k], 2)

        conn.close()
        return _ok({
            'aggregate': agg,
            'counterparties': [dict(r) for r in rows],
        })
    except Exception as e:
        return _err(str(e))


@bp.get('/positions')
def api_positions():
    """持仓明细 (含市值计算)."""
    try:
        conn = _connect()
        sid = request.args.get('session_id')
        if sid:
            rows = conn.execute(
                "SELECT * FROM mt_vault_positions WHERE session_id=? ORDER BY market_value DESC",
                (sid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_vault_positions ORDER BY market_value DESC"
            ).fetchall()

        # 按 session 聚合
        by_session = {}
        total_mv = 0
        total_cost = 0
        for r in rows:
            sid = r['session_id']
            if sid not in by_session:
                by_session[sid] = {'market_value': 0, 'total_cost': 0, 'unrealized_pnl': 0, 'positions': []}
            by_session[sid]['market_value'] += float(r['market_value'] or 0)
            by_session[sid]['total_cost'] += float(r['total_cost'] or 0)
            by_session[sid]['unrealized_pnl'] += float(r['unrealized_pnl'] or 0)
            by_session[sid]['positions'].append(dict(r))
            total_mv += float(r['market_value'] or 0)
            total_cost += float(r['total_cost'] or 0)

        for sid, v in by_session.items():
            v['market_value'] = round(v['market_value'], 2)
            v['total_cost'] = round(v['total_cost'], 2)
            v['unrealized_pnl'] = round(v['unrealized_pnl'], 2)
            v['unrealized_pnl_pct'] = round(v['unrealized_pnl'] / v['total_cost'] * 100, 2) if v['total_cost'] > 0 else 0

        conn.close()
        return _ok({
            'total_market_value': round(total_mv, 2),
            'total_cost': round(total_cost, 2),
            'total_unrealized_pnl': round(total_mv - total_cost, 2),
            'by_session': by_session,
        })
    except Exception as e:
        return _err(str(e))


# ════════════════════════════════════════════════════════════
# Dashboard HTML 路由
# ════════════════════════════════════════════════════════════

@bp.get('/dashboard')
def bank_dashboard():
    """银行级 Dashboard — Gobelin 主题."""
    return render_template('bank_dashboard.html')


@bp.get('/build-ledger')
def api_build_ledger():
    """触发 LedgerEngine 重建所有 12 张表."""
    try:
        from engines.finance_ledger_engine import LedgerEngine
        engine = LedgerEngine()
        result = engine.build_all()
        return _ok(result)
    except Exception as e:
        logger.error(f"build_ledger error: {e}", exc_info=True)
        return _err(str(e), 500)


@bp.post('/refresh-live')
def api_refresh_live():
    """刷新 LIVE 层实时行情 (腾讯行情 API → mt_live_*)."""
    try:
        from engines.live_layer_refresh import refresh_live_layer
        ok = refresh_live_layer(dry_run=False)
        # 汇总结果
        conn = _connect()
        pos_cnt = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
        acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
        rows = conn.execute("SELECT symbol, name, price, pnl, pnl_pct FROM mt_live_position").fetchall()
        conn.close()
        return _ok({
            'refreshed': ok,
            'positions_count': pos_cnt,
            'account': dict(acc) if acc else {},
            'positions': [dict(r) for r in rows],
            'generated_at': datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"refresh_live error: {e}", exc_info=True)
        return _err(str(e), 500)


@bp.get('/live/status')
def api_live_status():
    """LIVE 层状态诊断."""
    try:
        conn = _connect()
        pos = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
        trades = conn.execute("SELECT COUNT(*) FROM mt_live_trade_log").fetchone()[0]
        orders = conn.execute("SELECT COUNT(*) FROM mt_live_order").fetchone()[0]
        acc_row = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if acc_row:
            acc = {
                'total_assets': float(acc_row['total_assets'] or 0),
                'cash': float(acc_row['cash'] or 0),
                'market_value': float(acc_row['market_value'] or 0),
                'pnl': float(acc_row['pnl'] or 0),
                'updated_at': acc_row['updated_at'],
            }
        else:
            acc = None
        return _ok({
            'layer': 'LIVE',
            'positions': pos,
            'trade_logs': trades,
            'orders': orders,
            'account': acc,
            'configured': pos > 0,
        })
    except Exception as e:
        return _err(str(e))
