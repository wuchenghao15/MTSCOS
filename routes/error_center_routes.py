"""
错误异常处理中心 — Flask 路由 (页面 + API)

flow_id: flow_error_center_20261018
version: v1.0.0
注册: routes/__init__.py → _modules ('error_center_routes', 'error_center_bp')

页面:
  GET  /error-center               → 中心主页

API:
  GET  /api/error-center/summary   → 聚合 KPI + 多源错误清单 (规则违反/铁律违反/FAILED daemon/中心事件)
  POST /api/error-center/report    → 错误上报 (前端 console beacon / 服务端组件均可调)
  POST /api/error-center/resolve   → 事件处理闭环 (OPEN → RESOLVED)

事件表: mt_error_center_events (首次调用自动建表)
"""
import os
import sqlite3
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app.middlewares.system_container import system_container

error_center_bp = Blueprint('error_center', __name__)

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_DB_PATH = os.path.join(_BASE_DIR, 'database', 'app.db')

_SEVERITIES = ('CRITICAL', 'ERROR', 'WARN', 'INFO')


def _db():
    conn = sqlite3.connect(_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_error_center_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'ERROR',
                source TEXT NOT NULL DEFAULT 'unknown',
                error_type TEXT DEFAULT '',
                message TEXT DEFAULT '',
                url TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'OPEN',
                resolved_at TEXT,
                resolved_by TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ece_status ON mt_error_center_events(status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ece_severity ON mt_error_center_events(severity, created_at)")


def _q(conn, sql, args=()):
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError:
        return []


@error_center_bp.route('/error-center', methods=['GET'])
@system_container(require_auth='login')
def error_center_page():
    return render_template('error_center.html')


@error_center_bp.route('/api/error-center/summary', methods=['GET'])
@system_container(require_auth='login')
def api_summary():
    _ensure_table()
    now = datetime.now().isoformat()
    with _db() as conn:
        events = _q(conn, "SELECT * FROM mt_error_center_events ORDER BY id DESC LIMIT 60")
        open_events = _q(conn, "SELECT COUNT(*) n FROM mt_error_center_events WHERE status='OPEN'")[0]['n']
        crit24 = _q(conn, "SELECT COUNT(*) n FROM mt_error_center_events WHERE severity='CRITICAL' AND created_at >= datetime('now','-1 day')")[0]['n']
        rule_viol = _q(conn, "SELECT alert_id, violation_code, severity, alert_status, created_at FROM mt_rule_violation_alert ORDER BY created_at DESC LIMIT 12")
        rule_viol_7d = _q(conn, "SELECT COUNT(*) n FROM mt_rule_violation_alert WHERE created_at >= datetime('now','-7 day')")[0]['n']
        iron_viol = _q(conn, "SELECT * FROM mt_iron_rule_violations ORDER BY rowid DESC LIMIT 12")
        failed_daemons = _q(conn, "SELECT process_name, status, last_heartbeat FROM mt_daemon_registry WHERE status NOT IN ('RUNNING','OK','ACTIVE') ORDER BY process_name LIMIT 30")
        daemon_total = _q(conn, "SELECT COUNT(*) n FROM mt_daemon_registry")[0]['n']
    return jsonify({
        'now': now,
        'kpis': {
            'open_events': open_events,
            'critical_24h': crit24,
            'rule_violations_7d': rule_viol_7d,
            'failed_daemons': len(failed_daemons),
            'daemon_total': daemon_total,
            'iron_violations': len(iron_viol),
        },
        'events': events,
        'rule_violations': rule_viol,
        'iron_violations': iron_viol,
        'failed_daemons': failed_daemons,
    })


@error_center_bp.route('/api/error-center/report', methods=['POST'])
@system_container(require_auth='login')
def api_report():
    """错误上报: {severity, source, error_type, message, url}"""
    data = request.get_json(silent=True) or {}
    severity = str(data.get('severity') or 'ERROR').upper()
    if severity not in _SEVERITIES:
        severity = 'ERROR'
    message = str(data.get('message') or '')[:2000]
    _ensure_table()
    with _db() as conn:
        conn.execute(
            "INSERT INTO mt_error_center_events (created_at, severity, source, error_type, message, url, status) VALUES (?,?,?,?,?,?,'OPEN')",
            (datetime.now().isoformat(), severity,
             str(data.get('source') or 'manual')[:64],
             str(data.get('error_type') or 'Unspecified')[:128],
             message, str(data.get('url') or '')[:512]))
        row = conn.execute("SELECT last_insert_rowid() id").fetchone()
    return jsonify({'success': True, 'id': row['id']})


@error_center_bp.route('/api/error-center/resolve', methods=['POST'])
@system_container(require_auth='login')
def api_resolve():
    """处理闭环: {id} → status=RESOLVED"""
    data = request.get_json(silent=True) or {}
    eid = data.get('id')
    if not eid:
        return jsonify({'success': False, 'error': 'id required'}), 400
    _ensure_table()
    with _db() as conn:
        cur = conn.execute(
            "UPDATE mt_error_center_events SET status='RESOLVED', resolved_at=?, resolved_by=? WHERE id=? AND status='OPEN'",
            (datetime.now().isoformat(), 'operator', eid))
    return jsonify({'success': True, 'updated': cur.rowcount})
