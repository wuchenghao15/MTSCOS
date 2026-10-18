"""
仙女座总枢纽 — API 网关 (flow_andromeda_p3_20261018)

GET /api/andromeda/hub → 四层聚合 (内部聚合现有表, 不重写逻辑):
  L1 引擎层: mt_andromeda_engine_inventory 分层统计
  L2 数据层: mt_andromeda_data_dictionary 双胞胎裁决
  L3 网络层: EigenFlux 注册/消息/专家
  L4 运行层: daemon 状态 + 错误中心 OPEN + 规则违反
"""
import os
import sqlite3
from collections import Counter

from flask import Blueprint, jsonify, render_template

from app.middlewares.system_container import system_container

andromeda_hub_bp = Blueprint('andromeda_hub', __name__)

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_DB_PATH = os.path.join(_BASE_DIR, 'database', 'app.db')


def _q(conn, sql, args=()):
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError:
        return []


def _hub_payload():
    with sqlite3.connect(_DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        engines = _q(conn, "SELECT layer, COUNT(*) n FROM mt_andromeda_engine_inventory GROUP BY layer")
        debris = _q(conn, "SELECT COUNT(*) n FROM mt_andromeda_engine_inventory WHERE engine_name LIKE '%.new' OR engine_name LIKE '%auto_repair_backup'")
        twins = _q(conn, "SELECT group_key, authoritative_table, tables_json FROM mt_andromeda_data_dictionary")
        ef_reg = _q(conn, "SELECT COUNT(*) n FROM eigenflux_registrations")[0]['n']
        ef_reg24 = _q(conn, "SELECT COUNT(*) n FROM eigenflux_registrations WHERE last_heartbeat >= datetime('now','-1 day')")[0]['n']
        try:
            ef_msg = _q(conn, "SELECT COUNT(*) n FROM eigenflux_comm_messages")[0]['n']
        except Exception:
            ef_msg = 0
        experts = _q(conn, "SELECT COUNT(*) n FROM eigenflux_experts")[0]['n']
        daemons_total = _q(conn, "SELECT COUNT(*) n FROM mt_daemon_registry")[0]['n']
        daemons_bad = _q(conn, "SELECT process_name, status, last_heartbeat FROM mt_daemon_registry WHERE status NOT IN ('RUNNING','OK','ACTIVE') ORDER BY process_name LIMIT 20")
        try:
            err_open = _q(conn, "SELECT COUNT(*) n FROM mt_error_center_events WHERE status='OPEN'")[0]['n']
        except Exception:
            err_open = 0
        rule_7d = _q(conn, "SELECT COUNT(*) n FROM mt_rule_violation_alert WHERE created_at >= datetime('now','-7 day')")[0]['n']
        brain = _q(conn, "SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name LIKE '%brain%'")[0]['n']
    layer_cnt = Counter(e['layer'] for e in engines)
    return {
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'L1_engines': {'total': sum(layer_cnt.values()), 'by_layer': dict(layer_cnt), 'debris': debris[0]['n'] if debris else 0},
        'L2_data': {'twin_groups': [{'group': t['group_key'], 'authoritative': t['authoritative_table'], 'tables': t['tables_json']} for t in twins]},
        'L3_network': {'eigenflux_registered': ef_reg, 'heartbeat_24h': ef_reg24, 'comm_messages': ef_msg, 'experts': experts, 'brain_tables': brain},
        'L4_runtime': {'daemons_total': daemons_total, 'daemons_abnormal': daemons_bad, 'error_center_open': err_open, 'rule_violations_7d': rule_7d},
    }


@andromeda_hub_bp.route('/andromeda/hub', methods=['GET'])
@system_container(require_auth='login')
def andromeda_hub_page():
    """🪐 仙女座总枢纽 — 四层全景页 (flow_andromeda_p4_20261018)"""
    return render_template('andromeda_hub.html')


@andromeda_hub_bp.route('/api/andromeda/hub', methods=['GET'])
@system_container(require_auth='login')
def api_andromeda_hub():
    return jsonify(_hub_payload())
