"""
红蓝攻防研究中心 (flow_redblue_ui_20261018)

红队视角: 攻击面盘点 (路由全景/匿名可达/管理面/API 面)
蓝队视角: 防御纵深 (4层拦截/密级覆盖/违反事件/错误中心)
对抗事件流: 最近规则违反告警
"""
import os
import sqlite3
from datetime import datetime

from flask import Blueprint, jsonify, render_template

from app.middlewares.system_container import system_container

redblue_bp = Blueprint('redblue', __name__)

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_DB_PATH = os.path.join(_BASE_DIR, 'database', 'app.db')


def _q(conn, sql, args=()):
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError:
        return []


def _attack_surface():
    """红队: 攻击面盘点 (运行时 url_map 事实源)"""
    from flask import current_app
    total = get_count = post_count = admin_n = api_n = static_n = 0
    try:
        rules = list(current_app.url_map.iter_rules())
        total = len(rules)
        for r in rules:
            m = r.methods or set()
            if 'GET' in m:
                get_count += 1
            if 'POST' in m:
                post_count += 1
            s = str(r)
            if s.startswith('/admin_app'):
                admin_n += 1
            elif s.startswith('/api/'):
                api_n += 1
            elif s.startswith('/static'):
                static_n += 1
    except Exception:
        pass
    return {
        'routes_total': total, 'routes_get': get_count, 'routes_post': post_count,
        'admin_surface': admin_n, 'api_surface': api_n, 'static_assets': static_n,
        'external_entries': ['https://www.mtos.site', 'https://mtos.site', '/ai (登录引导)'],
    }


def _defense_posture():
    """蓝队: 防御纵深 (DB 事实源)"""
    with sqlite3.connect(_DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cls_total = _q(conn, "SELECT COUNT(*) n FROM encryption_classification")
        cls_l0 = _q(conn, "SELECT COUNT(*) n FROM encryption_classification WHERE level=0")
        iron = _q(conn, "SELECT COUNT(*) n FROM mt_iron_rule_violations")
        alerts_7d = _q(conn, "SELECT COUNT(*) n FROM mt_rule_violation_alert WHERE created_at >= datetime('now','-7 day')")
        err_open = _q(conn, "SELECT COUNT(*) n FROM mt_error_center_events WHERE status='OPEN'")
        events = _q(conn, "SELECT alert_type, severity, alert_target, created_at FROM mt_rule_violation_alert ORDER BY created_at DESC LIMIT 10")
    return {
        'intercept_layers': ['git pre-commit hook', 'flask before_request', 'CI self-check', 'git pre-push'],
        'classification_registered': cls_total[0]['n'] if cls_total else 0,
        'classification_l0': cls_l0[0]['n'] if cls_l0 else 0,
        'iron_rule_violations': iron[0]['n'] if iron else 0,
        'rule_alerts_7d': alerts_7d[0]['n'] if alerts_7d else 0,
        'error_center_open': err_open[0]['n'] if err_open else 0,
        'events': events,
    }


@redblue_bp.route('/redblue/center', methods=['GET'])
@system_container(require_auth='login')
def redblue_center_page():
    """⚔️ 红蓝攻防研究中心 — 首页框架原生页 (flow_redblue_ui_20261018)"""
    return render_template('redblue_center.html')


@redblue_bp.route('/api/redblue/overview', methods=['GET'])
@system_container(require_auth='login')
def api_redblue_overview():
    return jsonify({
        'generated_at': datetime.now().isoformat(),
        'red': _attack_surface(),
        'blue': _defense_posture(),
    })
