#!/usr/bin/env python3
"""
⚙️ 仙女座角色设置 + Dashboard 统一蓝图 — routes/role_settings_routes.py
端点:
  GET    /api/roles                          列出所有角色
  GET    /api/roles/<key>                    单个角色完整设置 (通用+专属+audit)
  POST   /api/roles/<key>/set                单字段设置 (section/key/value)
  POST   /api/roles/<key>/bulk               批量设置
  GET    /api/roles/<key>/audit              审计日志
  POST   /api/roles/sync                     从 role_registry.py 重新同步默认值
  GET    /api/roles/summary                  Dashboard 汇总
  GET    /roles/dashboard                    后台 Dashboard 聚合页面
  GET    /roles/<key>/settings               单个角色设置面板页面
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, request, jsonify, session, render_template

role_bp = Blueprint('role_settings', __name__)

_engine = None
def _get():
    global _engine
    if _engine is None:
        from engines.role_settings_engine import RoleSettingsEngine
        _engine = RoleSettingsEngine()
    return _engine


@role_bp.route('/api/roles', methods=['GET'])
def api_list():
    eng = _get()
    return jsonify({'ok': True, 'roles': eng.list_all(), 'count': 8})


@role_bp.route('/api/roles/summary', methods=['GET'])
def api_summary():
    return jsonify({'ok': True, 'summary': _get().cluster_summary()})


@role_bp.route('/api/roles/<role_key>', methods=['GET'])
def api_get(role_key):
    d = _get().get(role_key)
    if not d: return jsonify({'ok': False, 'msg': 'not found'}), 404
    return jsonify({'ok': True, 'data': d})


@role_bp.route('/api/roles/<role_key>/set', methods=['POST'])
def api_set(role_key):
    d = request.get_json(force=True, silent=True) or {}
    section = d.get('section') or d.get('json_section')
    key = d.get('key') or d.get('field')
    value = d.get('value')
    if not section or not key:
        return jsonify({'ok': False, 'msg': 'section & key required'}), 400
    ok = _get().set(role_key, section, key, value,
                    changed_by=session.get('username', 'anonymous'),
                    changed_from='web_api')
    return jsonify({'ok': ok})


@role_bp.route('/api/roles/<role_key>/bulk', methods=['POST'])
def api_bulk(role_key):
    d = request.get_json(force=True, silent=True) or {}
    updates = d.get('updates') or d
    count = _get().bulk_set(role_key, updates,
                            changed_by=session.get('username', 'anonymous'),
                            changed_from='web_api')
    return jsonify({'ok': True, 'updated': count})


@role_bp.route('/api/roles/<role_key>/audit', methods=['GET'])
def api_audit(role_key):
    limit = int(request.args.get('limit', 50))
    return jsonify({'ok': True, 'role_key': role_key, 'audits': _get().audit(role_key, limit)})


@role_bp.route('/api/roles/sync', methods=['POST'])
def api_sync():
    n = _get().sync_from_registry()
    return jsonify({'ok': True, 'synced': n})


@role_bp.route('/roles/dashboard', methods=['GET'])
def roles_dashboard():
    """后台 Dashboard 聚合页面"""
    eng = _get()
    return render_template(
        'andromeda_role_dashboard.html',
        summary=eng.cluster_summary(),
        username=session.get('username', 'wuchenghao15'),
        role=session.get('role', 'super_admin'),
    )


@role_bp.route('/roles/<role_key>/settings', methods=['GET'])
def role_settings_page(role_key):
    """单个角色设置面板"""
    eng = _get()
    data = eng.get(role_key)
    if not data: return 'not found', 404
    return render_template(
        'andromeda_role_settings.html',
        role_data=data,
        username=session.get('username', 'wuchenghao15'),
        role=session.get('role', 'super_admin'),
    )
