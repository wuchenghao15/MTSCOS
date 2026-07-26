#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Firewall Blueprint - 防火墙规则 / 事件 / 统计 API
鉴权模式：
- GET /api/ai_firewall/*  -> 要求登录 + 管理员；非管理员 403
- 写操作（PUT/POST/DELETE） -> 要求 super_admin
"""
import os, sys, json
from datetime import datetime
from flask import Blueprint, request, jsonify, session

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'core', 'services'))

ai_firewall_api = Blueprint('ai_firewall_api', __name__, url_prefix='/api/ai_firewall')

from core.services import ai_firewall as fw  # noqa: E402


AUTH_DB = os.path.join(PROJECT_ROOT, 'split_databases', 'auth.db')


def _conn_auth():
    import sqlite3
    c = sqlite3.connect(AUTH_DB)
    c.row_factory = sqlite3.Row
    return c


def _current_user():
    if not session.get('username'):
        return None
    uid = session.get('user_id')
    user = {'id': uid, 'username': session.get('username'), 'role': session.get('role'), 'is_admin': False, 'is_super_admin': False}
    try:
        if uid and os.path.exists(AUTH_DB):
            with _conn_auth() as c:
                row = c.execute(
                    "SELECT super_admin_approved, role FROM users WHERE id=? LIMIT 1", (uid,)
                ).fetchone()
                if row:
                    if row['super_admin_approved']:
                        user['is_super_admin'] = True
                        user['is_admin'] = True
                    role = (row['role'] or '').lower()
                    admin_roles = {'admin', 'super_admin', 'school_admin', 'institution_admin', 'teacher_admin', 'sysadmin'}
                    if role in admin_roles:
                        user['is_admin'] = True
                        if role == 'super_admin':
                            user['is_super_admin'] = True
    except Exception:
        pass
    if str(session.get('role') or '').lower() in {'admin', 'super_admin'}:
        user['is_admin'] = True
    if session.get('super_admin_approved') is True:
        user['is_super_admin'] = True
    return user


def _auth_required(need_super=False):
    def decorator(fn):
        import functools
        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            u = _current_user()
            if not u:
                return jsonify({'success': False, 'message': '需要登录'}), 401
            if not u['is_admin']:
                return jsonify({'success': False, 'message': '需要管理员权限'}), 403
            if need_super and not u['is_super_admin']:
                return jsonify({'success': False, 'message': '需要超级管理员权限'}), 403
            return fn(*args, **kwargs)
        return wrap
    return decorator


@ai_firewall_api.route('/stats', methods=['GET'])
@_auth_required(need_super=False)
def stats():
    return jsonify({'success': True, 'data': fw.stats_summary()})


@ai_firewall_api.route('/rules', methods=['GET'])
@_auth_required(need_super=False)
def list_rules():
    keyword = (request.args.get('keyword') or '').strip() or None
    category = (request.args.get('category') or '').strip() or None
    status = (request.args.get('status') or '').strip() or None
    data = fw.list_rules(keyword=keyword, category=category, status=status)
    return jsonify({'success': True, 'count': len(data), 'data': data})


@ai_firewall_api.route('/rules/<int:rule_id>', methods=['GET'])
@_auth_required(need_super=False)
def get_rule(rule_id):
    r = fw.get_rule(rule_id)
    if not r:
        return jsonify({'success': False, 'message': '规则不存在'}), 404
    return jsonify({'success': True, 'data': r})


@ai_firewall_api.route('/rules', methods=['POST'])
@_auth_required(need_super=True)
def create_rule():
    data = request.get_json(silent=True) or {}
    for req in ('name', 'category', 'severity', 'rule_type', 'action'):
        if req not in data:
            return jsonify({'success': False, 'message': f'缺少必填字段 {req}'}), 400
    r = fw.create_or_update_rule(**data)
    if r is None:
        return jsonify({'success': False, 'message': '创建失败'}), 500
    return jsonify({'success': True, 'message': '已创建规则', 'data': r}), 201


@ai_firewall_api.route('/rules/<int:rule_id>', methods=['PUT'])
@_auth_required(need_super=True)
def update_rule(rule_id):
    data = request.get_json(silent=True) or {}
    if fw.get_rule(rule_id) is None:
        return jsonify({'success': False, 'message': '规则不存在'}), 404
    r = fw.create_or_update_rule(rule_id=rule_id, **data)
    if r is None:
        return jsonify({'success': False, 'message': '更新失败'}), 500
    return jsonify({'success': True, 'message': '已更新规则', 'data': r})


@ai_firewall_api.route('/rules/<int:rule_id>/toggle', methods=['POST'])
@_auth_required(need_super=False)
def toggle_rule(rule_id):
    data = request.get_json(silent=True) or {}
    status = data.get('status', request.args.get('status', '')).strip()
    if status not in ('enabled', 'disabled'):
        return jsonify({'success': False, 'message': 'status 必须是 enabled 或 disabled'}), 400
    r = fw.toggle_rule(rule_id, status)
    if r is None:
        return jsonify({'success': False, 'message': '规则不存在或更新失败'}), 404
    return jsonify({'success': True, 'message': f'已{ "启用" if status=="enabled" else "禁用" }规则', 'data': r})


@ai_firewall_api.route('/rules/<int:rule_id>', methods=['DELETE'])
@_auth_required(need_super=True)
def delete_rule(rule_id):
    ok = fw.delete_rule(rule_id)
    if not ok:
        return jsonify({'success': False, 'message': '删除失败或规则不存在'}), 404
    return jsonify({'success': True, 'message': '已删除规则'})


@ai_firewall_api.route('/events', methods=['GET'])
@_auth_required(need_super=False)
def list_events():
    limit = max(1, min(1000, int(request.args.get('limit', 100) or 100)))
    rule_code = (request.args.get('rule_code') or '').strip() or None
    severity = (request.args.get('severity') or '').strip() or None
    data = fw.list_events(limit=limit, rule_code=rule_code, severity=severity)
    return jsonify({'success': True, 'count': len(data), 'data': data})


@ai_firewall_api.route('/reload', methods=['POST'])
@_auth_required(need_super=False)
def reload():
    from core.services.ai_firewall import load_rules
    rules = load_rules(force=True)
    return jsonify({'success': True, 'message': f'已重新加载 {len(rules)} 条启用规则', 'loaded_rules': len(rules)})


@ai_firewall_api.route('/resync_defaults', methods=['POST'])
@_auth_required(need_super=True)
def resync_defaults():
    inserted = fw.seed_default_firewall_rules(force_refresh=True)
    rules = fw.load_rules(force=True)
    return jsonify({'success': True, 'message': f'已同步默认规则（影响 {inserted} 条），当前启用 {len(rules)} 条',
                    'affected': inserted, 'enabled_rules': len(rules)})
