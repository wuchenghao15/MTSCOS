"""
blueprints/finance_audit_bp.py — Gobelin 财务稽查 REST API
====================================================
实时 + 定时双引擎稽查数据查询 / 手动触发

url_prefix: /api/finance/audit
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger('finance_audit_bp')

bp = Blueprint('finance_audit', __name__, url_prefix='/api/finance/audit')


# ── DB 解析 ──────────────────────────────────────────────────

def _db():
    """获取数据库连接"""
    try:
        from engines.finance_realtime_audit import _resolve_db_path, _connect
        path = _resolve_db_path(None)
        return _connect(path), path
    except Exception:
        # fallback
        candidates = [
            os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
            os.path.join(os.getcwd(), 'database', 'app.db'),
        ]
        for c in candidates:
            if os.path.exists(c):
                conn = sqlite3.connect(c, timeout=10)
                conn.row_factory = sqlite3.Row
                return conn, c
        raise RuntimeError('finance_audit_bp: 找不到 app.db')


# ── GET /api/finance/audit/status ────────────────────────────

@bp.get('/status')
def api_status():
    """实时稽查总览 — 今日通过/警告/失败统计"""
    try:
        conn, path = _db()
        today = datetime.now().strftime('%Y-%m-%d')

        by_level = conn.execute(
            "SELECT level, COUNT(*) AS cnt FROM mt_vault_audit_log "
            "WHERE date(created_at)=? GROUP BY level", (today,)
        ).fetchall()
        by_type = conn.execute(
            "SELECT audit_type, COUNT(*) AS cnt FROM mt_vault_audit_log "
            "WHERE date(created_at)=? GROUP BY audit_type", (today,)
        ).fetchall()
        total_today = conn.execute(
            "SELECT COUNT(*) FROM mt_vault_audit_log WHERE date(created_at)=?",
            (today,)
        ).fetchone()[0]

        # 实时: 所有 trade 的 verdict 分布 (通过实时审计)
        total_trades = conn.execute("SELECT COUNT(*) FROM mt_sandbox_trades").fetchone()[0]

        # 最新定时报告摘要
        latest_scheduled = conn.execute(
            "SELECT audit_id, description, verdict, level FROM mt_vault_audit_log "
            "WHERE audit_type='SCHEDULED' AND dimension='SUMMARY' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

        conn.close()

        return jsonify({
            'ok': True,
            'today': today,
            'total_logs_today': total_today,
            'by_level': {row['level']: row['cnt'] for row in by_level},
            'by_type': {row['audit_type']: row['cnt'] for row in by_type},
            'total_sandbox_trades': total_trades,
            'latest_scheduled': dict(latest_scheduled) if latest_scheduled else None,
        })
    except Exception as e:
        logger.exception(f"/status 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── GET /api/finance/audit/dimensions ─────────────────────────

@bp.get('/dimensions')
def api_dimensions():
    """12 维度详细通过率"""
    try:
        conn, _ = _db()
        rows = conn.execute(
            "SELECT dimension, level, verdict, COUNT(*) AS cnt "
            "FROM mt_vault_audit_log "
            "WHERE audit_type='REALTIME' "
            "GROUP BY dimension, level, verdict "
            "ORDER BY dimension, level"
        ).fetchall()
        conn.close()

        DIMS = {
            'D01': '资金充足', 'D02': '持仓充足', 'D03': 'T+1 结算',
            'D04': '价格异常', 'D05': '数量异常', 'D06': '双写一致性',
            'D07': '佣金计算', 'D08': '印花税规则', 'D09': '现金守恒',
            'D10': '重复下单', 'D11': '熔断检查', 'D12': '信号一致性',
        }

        result = {}
        for r in rows:
            d = r['dimension']
            result.setdefault(d, {
                'dimension': d,
                'name': DIMS.get(d, ''),
                'level_counts': {},
                'verdict_counts': {},
                'total': 0,
            })
            result[d]['level_counts'][r['level']] = r['cnt']
            result[d]['verdict_counts'][r['verdict']] = r['cnt']
            result[d]['total'] += r['cnt']

        for d in DIMS:
            result.setdefault(d, {
                'dimension': d, 'name': DIMS[d],
                'level_counts': {}, 'verdict_counts': {}, 'total': 0,
            })

        return jsonify({
            'ok': True,
            'dimensions': result,
            'total_dimensions': len(DIMS),
        })
    except Exception as e:
        logger.exception(f"/dimensions 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── GET /api/finance/audit/log ────────────────────────────────

@bp.get('/log')
def api_log():
    """稽查日志列表 (支持 level/dimension/session 过滤, 分页)"""
    try:
        conn, _ = _db()
        q = "SELECT * FROM mt_vault_audit_log WHERE 1=1"
        args = []

        level = request.args.get('level', '').upper()
        dimension = request.args.get('dimension', '').upper()
        session_id = request.args.get('session', '')
        trade_id = request.args.get('trade_id', '')
        audit_type = request.args.get('type', '')

        if level:
            q += " AND level=?"; args.append(level)
        if dimension:
            q += " AND dimension=?"; args.append(dimension)
        if session_id:
            q += " AND session_id=?"; args.append(session_id)
        if trade_id:
            q += " AND trade_id=?"; args.append(trade_id)
        if audit_type:
            q += " AND audit_type=?"; args.append(audit_type)

        page = int(request.args.get('page', 1))
        page_size = min(int(request.args.get('page_size', 50)), 200)
        offset = (page - 1) * page_size

        total = conn.execute(q.replace("SELECT * FROM", "SELECT COUNT(*) FROM"), args).fetchone()[0]

        q += " ORDER BY rowid DESC LIMIT ? OFFSET ?"
        args.append(page_size); args.append(offset)

        rows = conn.execute(q, args).fetchall()
        conn.close()

        return jsonify({
            'ok': True,
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': [dict(r) for r in rows],
        })
    except Exception as e:
        logger.exception(f"/log 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── GET /api/finance/audit/report/latest ────────────────────────

@bp.get('/report/latest')
def api_report_latest():
    """最新定时稽查完整报告"""
    try:
        from engines.finance_audit_daemon import REPORTS_DIR

        files = sorted([f for f in os.listdir(REPORTS_DIR) if f.endswith('.json')])
        if not files:
            return jsonify({'ok': False, 'error': '无定时稽查报告 — 请 POST /trigger-scheduled 生成'}), 404

        path = os.path.join(REPORTS_DIR, files[-1])
        with open(path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        return jsonify({'ok': True, 'report': report, 'report_path': path})
    except Exception as e:
        logger.exception(f"/report/latest 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── GET /api/finance/audit/session/<session_id> ──────────────

@bp.get('/session/<session_id>')
def api_session_audit(session_id):
    """某 session 的完整账务历史 (交易/资金/持仓/PnL 四维)"""
    try:
        conn, _ = _db()

        # 交易
        trades = conn.execute(
            "SELECT trade_id, trade_date, trade_time, symbol, action AS side, "
            "shares AS qty, price, commission AS fee, stamp_tax AS tax, total_amount "
            "FROM mt_sandbox_trades WHERE session_id=? ORDER BY trade_date, trade_time",
            (session_id,)
        ).fetchall()

        # portfolio
        pf = conn.execute(
            "SELECT * FROM mt_sandbox_portfolio WHERE session_id=?", (session_id,)
        ).fetchone()

        # snapshots
        snaps = conn.execute(
            "SELECT * FROM mt_sandbox_snapshots WHERE session_id=? ORDER BY snap_date DESC LIMIT 30",
            (session_id,)
        ).fetchall()

        # 审计记录
        logs = conn.execute(
            "SELECT * FROM mt_vault_audit_log WHERE session_id=? OR session_id IS NULL "
            "ORDER BY rowid DESC LIMIT 50",
            (session_id,)
        ).fetchall()

        conn.close()

        return jsonify({
            'ok': True,
            'session_id': session_id,
            'portfolio': dict(pf) if pf else None,
            'trades': [dict(t) for t in trades],
            'snapshots': [dict(s) for s in snaps],
            'audit_logs': [dict(l) for l in logs],
        })
    except Exception as e:
        logger.exception(f"/session/{session_id} 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── POST /api/finance/audit/trigger-realtime ─────────────────

@bp.post('/trigger-realtime')
def api_trigger_realtime():
    """手动触发实时稽查 (传入 trade data JSON)

    body 字段: trade_id, session_id, symbol, side, qty, price, fee, tax, cash_before, cash_after
    或: 批量传入 trades: [...]
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
        from engines.finance_realtime_audit import audit_trade, RealtimeAuditor

        if 'trades' in body and isinstance(body['trades'], list):
            # 批量: 类似 RealtimeAuditor.audit_all_existing
            results = {'batch_results': []}
            for t in body['trades']:
                r = audit_trade(t)
                results['batch_results'].append({
                    'trade_id': t.get('trade_id'),
                    'verdict': r['verdict'],
                    'issues': r['issues'],
                })
            return jsonify({'ok': True, 'mode': 'batch', 'result': results})

        # 单笔
        r = audit_trade(body)
        return jsonify({
            'ok': True,
            'mode': 'single',
            'trade_id': body.get('trade_id'),
            'verdict': r['verdict'],
            'dimensions_passed': r['dimensions_passed'],
            'dimensions_failed': r.get('dimensions_failed', []),
            'issues': r['issues'],
        })
    except Exception as e:
        logger.exception(f"/trigger-realtime 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── POST /api/finance/audit/trigger-scheduled ─────────────────

@bp.post('/trigger-scheduled')
def api_trigger_scheduled():
    """手动触发完整 8 阶段定时稽查"""
    try:
        from engines.finance_audit_daemon import run_scheduled_audit
        result = run_scheduled_audit()
        report = result['report']
        return jsonify({
            'ok': True,
            'report_path': result['report_path'],
            'audit_id': report['audit_id'],
            'verdict': report['summary']['overall_verdict'],
            'risk_score': report['summary']['risk_score'],
            'summary': report['summary'],
            'recommendations': report['recommendations'],
        })
    except Exception as e:
        logger.exception(f"/trigger-scheduled 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── GET /api/finance/audit/health ─────────────────────────────

@bp.get('/health')
def api_audit_health():
    """稽查引擎健康状态"""
    try:
        conn, path = _db()

        # 确认表存在
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('mt_vault_audit_log', 'mt_sandbox_trades', 'mt_trade_log', "
            "'mt_sandbox_portfolio', 'mt_sandbox_signals', 'mt_sandbox_snapshots')"
        ).fetchall()]

        counts = {}
        for t in tables:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

        # 最新报告
        latest = conn.execute(
            "SELECT MAX(created_at) FROM mt_vault_audit_log WHERE audit_type='SCHEDULED'"
        ).fetchone()[0]
        latest_rt = conn.execute(
            "SELECT MAX(created_at) FROM mt_vault_audit_log WHERE audit_type='REALTIME'"
        ).fetchone()[0]

        conn.close()

        health = {
            'ok': True,
            'db_path': path,
            'tables': {t: 'OK' for t in tables},
            'row_counts': counts,
            'last_scheduled_run': latest,
            'last_realtime_run': latest_rt,
            'engines': {
                'realtime': 'OK',
                'scheduled': 'OK',
            },
            'timestamp': datetime.now().isoformat(),
        }
        # 异常
        if 'mt_vault_audit_log' not in tables:
            health['engines']['realtime'] = 'UNAVAILABLE'
            health['engines']['scheduled'] = 'UNAVAILABLE'
            health['ok'] = False
        return jsonify(health)
    except Exception as e:
        logger.exception(f"/health 失败: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
