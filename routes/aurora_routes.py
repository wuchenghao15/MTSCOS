#!/usr/bin/env python3
"""
🧊 Aurora 极光衍生维护系统 — Flask 路由 routes/aurora_routes.py
端点:
  GET    /api/aurora/status             Aurora 子系统状态
  GET    /api/aurora/list               全部能力 (支持 ?type=daemon&enabled_only=true)
  GET    /api/aurora/<skill_key>        单条能力详情
  PUT    /api/aurora/<skill_key>/toggle 运行时开关
  PUT    /api/aurora/<skill_key>        更新元数据
  DELETE /api/aurora/<skill_key>        删除 (仅自定义, 内置拒绝)
  POST   /api/aurora/seed               重新 seed (从硬编码迁移)
  GET    /api/aurora/by_type/<type>     按类型
  GET    /aurora/center                 Aurora 管理面板
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, request, jsonify, session, render_template
from app.middlewares.system_container import system_container

aurora_bp = Blueprint('aurora', __name__)

# 页面级: login (数据 API 均需登录, 页面匿名渲染会 401 坏页 → 统一登录引导)
@aurora_bp.route('/aurora/center', methods=['GET'])
@system_container(require_auth='login')
def aurora_center():
    return render_template('andromeda_aurora_center.html', username=session.get('username','wuchenghao15'))

# 只读 API: login 可查
@aurora_bp.route('/api/aurora/status', methods=['GET'])
@system_container(require_auth='login')
def api_status():
    from engines.aurora_skill_registry import aurora_registry
    return jsonify({'ok': True, **aurora_registry.status()})

@aurora_bp.route('/api/aurora/list', methods=['GET'])
@system_container(require_auth='login')
def api_list():
    from engines.aurora_skill_registry import aurora_registry
    cap_type = request.args.get('type')
    enabled_only = request.args.get('enabled_only','') == 'true'
    rows = aurora_registry.by_type(cap_type, enabled_only) if cap_type else aurora_registry.all(enabled_only)
    return jsonify({'ok': True, 'total': len(rows), 'items': rows, 'by_type': aurora_registry.count_by_type()})

@aurora_bp.route('/api/aurora/by_type/<cap_type>', methods=['GET'])
@system_container(require_auth='login')
def api_by_type(cap_type):
    from engines.aurora_skill_registry import aurora_registry
    rows = aurora_registry.by_type(cap_type)
    return jsonify({'ok': True, 'capability_type': cap_type, 'items': rows, 'count': len(rows)})

@aurora_bp.route('/api/aurora/<skill_key>', methods=['GET'])
@system_container(require_auth='login')
def api_get(skill_key):
    from engines.aurora_skill_registry import aurora_registry
    row = aurora_registry.get(skill_key)
    return jsonify({'ok': bool(row), 'item': row or {}})

# 写 API (管理操作): admin 才允许
@aurora_bp.route('/api/aurora/<skill_key>/toggle', methods=['PUT'])
@system_container(require_auth='admin')
def api_toggle(skill_key):
    body = request.get_json(force=True) or {}
    enabled = bool(body.get('enabled', True))
    reason = body.get('reason', '')
    from engines.aurora_skill_registry import aurora_registry
    ok = aurora_registry.toggle(skill_key, enabled, reason)
    return jsonify({'ok': ok, 'skill_key': skill_key, 'enabled': enabled})

@aurora_bp.route('/api/aurora/<skill_key>', methods=['PUT'])
@system_container(require_auth='admin')
def api_update(skill_key):
    body = request.get_json(force=True) or {}
    from engines.aurora_skill_registry import aurora_registry
    ok = aurora_registry.update_meta(skill_key, **body)
    return jsonify({'ok': ok, 'skill_key': skill_key})

@aurora_bp.route('/api/aurora/<skill_key>', methods=['DELETE'])
@system_container(require_auth='super_admin')
def api_delete(skill_key):
    from engines.aurora_skill_registry import aurora_registry
    row = aurora_registry.get(skill_key)
    if row and row.get('source') in ('SYSTEM_REQUIRED_DAEMONS','ICEBERG_DOMAINS','SELF_CAPABILITIES','ROLE_REGISTRY'):
        return jsonify({'ok': False, 'error': '内置能力不可删除, 可 toggle 禁用'}), 400
    ok = aurora_registry.delete(skill_key)
    return jsonify({'ok': ok, 'skill_key': skill_key})

# 破坏性 seed: super_admin 才允许
@aurora_bp.route('/api/aurora/seed', methods=['POST'])
@system_container(require_auth='super_admin')
def api_seed():
    from engines.aurora_skill_registry import aurora_registry
    r = aurora_registry.seed_all()
    return jsonify({'ok': True, **r})
