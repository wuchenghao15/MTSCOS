#!/usr/bin/env python3
"""
AI脑库与知识管理API
提供脑库连接、知识投喂、学习升级、知识检索等功能
"""

import os
import json
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.middlewares.access_control import require_login, require_admin
from app.middlewares.system_container import system_container

ai_brain_api = Blueprint('ai_brain_api', __name__)


def _get_brain_system():
    try:
        from app.ai.brain_based_learning import brain_based_learning_system
        return brain_based_learning_system
    except Exception as e:
        return None


def _get_brain_service():
    try:
        from app.services.ai_brain_service import ai_brain_service
        return ai_brain_service
    except Exception as e:
        return None


@ai_brain_api.route('/api/ai/brain/connect', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def connect_to_brain():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    result = system.connect_to_brain()
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/status', methods=['GET'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def get_brain_status():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    status = system.get_brain_status()
    return jsonify({'success': True, 'data': status, 'timestamp': datetime.now().isoformat()})


@ai_brain_api.route('/api/ai/brain/learn', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def learn_from_brain():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    data = request.get_json() or {}
    component_id = data.get('component_id')
    
    if component_id:
        result = system.learn_from_brain(component_id)
    else:
        results = []
        components = list(system.component_knowledge_mapping.keys())
        for comp_id in components:
            result = system.learn_from_brain(comp_id)
            results.append(result)
        result = {'success': True, 'message': '所有组件学习完成', 'results': results}
    
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/upgrade', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def upgrade_from_brain():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    data = request.get_json() or {}
    component_id = data.get('component_id')
    
    if component_id:
        result = system.upgrade_from_brain(component_id)
    else:
        result = system.auto_learn_and_upgrade_all()
    
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/upgrade/all', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def upgrade_all_from_brain():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    result = system.auto_learn_and_upgrade_all()
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/progress', methods=['GET'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def get_learning_progress():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    progress = system.get_learning_progress()
    return jsonify({'success': True, 'data': progress, 'timestamp': datetime.now().isoformat()})


@ai_brain_api.route('/api/ai/brain/sync/start', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def start_auto_sync():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    result = system.start_auto_sync()
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/sync/stop', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def stop_auto_sync():
    system = _get_brain_system()
    if not system:
        return jsonify({'success': False, 'error': '脑库系统不可用'}), 503
    
    result = system.stop_auto_sync()
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/knowledge', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def add_knowledge():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    data = request.get_json() or {}
    
    result = service.add_knowledge(
        knowledge_type=data.get('knowledge_type'),
        content=data.get('content'),
        tags=data.get('tags'),
        source=data.get('source'),
        confidence=data.get('confidence', 0.8)
    )
    
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/knowledge/search', methods=['GET'])
@system_container(require_auth='admin')
@require_login
@system_container()
def search_knowledge():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    query = request.args.get('q', '')
    knowledge_type = request.args.get('type')
    limit = request.args.get('limit', 10, type=int)
    
    result = service.search_knowledge(query, knowledge_type, limit)
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/knowledge/<knowledge_id>', methods=['GET'])
@system_container(require_auth='admin')
@require_login
@system_container()
def get_knowledge_detail(knowledge_id):
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    result = service.get_knowledge(knowledge_id)
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/knowledge/<knowledge_id>', methods=['PUT'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def update_knowledge(knowledge_id):
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    data = request.get_json() or {}
    
    result = service.update_knowledge(
        knowledge_id,
        content=data.get('content'),
        tags=data.get('tags'),
        confidence=data.get('confidence')
    )
    
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/knowledge/<knowledge_id>', methods=['DELETE'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def delete_knowledge(knowledge_id):
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    result = service.delete_knowledge(knowledge_id)
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/knowledge/list', methods=['GET'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def list_knowledge():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    knowledge_type = request.args.get('type')
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    
    result = service.list_knowledge(knowledge_type, page, page_size)
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/feed', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def feed_knowledge():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    data = request.get_json() or {}
    
    result = service.feed_knowledge(
        knowledge_type=data.get('knowledge_type'),
        content=data.get('content'),
        tags=data.get('tags'),
        source=data.get('source'),
        confidence=data.get('confidence', 0.8),
        priority=data.get('priority', 'normal')
    )
    
    return jsonify(result)


@ai_brain_api.route('/api/ai/brain/feed/batch', methods=['POST'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def batch_feed_knowledge():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    data = request.get_json() or {}
    knowledge_items = data.get('items', [])
    
    results = []
    for item in knowledge_items:
        result = service.feed_knowledge(
            knowledge_type=item.get('knowledge_type'),
            content=item.get('content'),
            tags=item.get('tags'),
            source=item.get('source'),
            confidence=item.get('confidence', 0.8)
        )
        results.append(result)
    
    success_count = sum(1 for r in results if r.get('success'))
    return jsonify({
        'success': success_count == len(results),
        'total': len(results),
        'success_count': success_count,
        'failed_count': len(results) - success_count,
        'results': results
    })


@ai_brain_api.route('/api/ai/brain/stats', methods=['GET'])
@system_container(require_auth='admin')
@require_admin
@system_container()
def get_brain_stats():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    stats = service.get_statistics()
    return jsonify({'success': True, 'data': stats, 'timestamp': datetime.now().isoformat()})


@ai_brain_api.route('/api/ai/brain/health', methods=['GET'])
@system_container(require_auth='admin')
@require_admin
def brain_health_check():
    service = _get_brain_service()
    if not service:
        return jsonify({'success': False, 'error': '脑库服务不可用'}), 503
    
    health = service.health_check()
    return jsonify({'success': True, 'data': health, 'timestamp': datetime.now().isoformat()})