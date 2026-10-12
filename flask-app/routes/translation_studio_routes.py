#!/usr/bin/env python3
"""
🌐 translation_studio — Flask 路由蓝图 (v26.0)
================================================
url_prefix=/andromeda, 全部 @system_container.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template
from typing import Optional

bp = Blueprint('translation_studio', __name__, url_prefix='/andromeda')

SYS_CONTAINER = None
def _ensure_container():
    global SYS_CONTAINER
    if SYS_CONTAINER is None:
        try:
            from app.middlewares.system_container import system_container as _sc
            SYS_CONTAINER = _sc
        except Exception:
            SYS_CONTAINER = None

def _sc(require_auth: str = 'login', **kw):
    """@system_container 装饰器代理."""
    def deco(fn):
        def wrapper(*args, **kwargs):
            _ensure_container()
            if SYS_CONTAINER:
                return SYS_CONTAINER(require_auth=require_auth, **kw)(fn)(*args, **kwargs)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco

@bp.route('/translation_studio/workbench')
@_sc(require_auth='guest')
def translation_workbench():
    return render_template('translation_workbench.html')

@bp.route('/api/translation_studio/stats')
@_sc(require_auth='login')
def api_trans_stats():
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    return jsonify({'success': True, 'data': svc.stats()})

@bp.route('/api/translation_studio/tasks', methods=['POST'])
@_sc(require_auth='login')
def api_trans_create():
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    d = request.get_json() or {}
    r = svc.create_task(
        source_text=d.get('source_text', ''),
        source_lang=d.get('source_lang', 'zh'),
        target_lang=d.get('target_lang', 'en'),
        quality=d.get('quality', 'standard'),
        source_project_id=d.get('source_project_id'),
        initiator=request.headers.get('X-User', 'wuchenghao15'))
    return jsonify({'success': 'error' not in r, 'data': r})

@bp.route('/api/translation_studio/tasks/<task_id>/run', methods=['POST'])
@_sc(require_auth='login')
def api_trans_run(task_id):
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    r = svc.run_task(task_id)
    return jsonify({'success': 'error' not in r, 'data': r})

@bp.route('/api/translation_studio/tasks/<task_id>')
@_sc(require_auth='login')
def api_trans_get(task_id):
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    t = svc.get_task(task_id)
    return jsonify({'success': t is not None, 'data': t})

@bp.route('/api/translation_studio/tasks')
@_sc(require_auth='login')
def api_trans_list():
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    return jsonify({'success': True, 'data': svc.list_tasks(status, limit)})

@bp.route('/api/translation_studio/glossary')
@_sc(require_auth='login')
def api_trans_glossary_list():
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    src = request.args.get('src_lang')
    tgt = request.args.get('tgt_lang')
    return jsonify({'success': True, 'data': svc.list_glossary(src, tgt)})

@bp.route('/api/translation_studio/glossary', methods=['POST'])
@_sc(require_auth='login')
def api_trans_glossary_add():
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    d = request.get_json() or {}
    ok = svc.add_glossary(d.get('src_lang',''), d.get('tgt_lang',''),
                          d.get('source_term',''), d.get('target_term',''),
                          d.get('domain','general'))
    return jsonify({'success': ok})

@bp.route('/api/translation_studio/copy_project/<project_id>', methods=['POST'])
@_sc(require_auth='login')
def api_trans_copy_project(project_id):
    from engines.translation_studio.service import TranslationService
    svc = TranslationService()
    d = request.get_json() or {}
    r = svc.translate_copy_project(project_id, d.get('target_langs'), d.get('quality','standard'))
    return jsonify({'success': 'error' not in r, 'data': r})

# 快速翻译 (一行文本直接翻, 不建任务)
@bp.route('/api/translation_studio/quick', methods=['POST'])
@_sc(require_auth='login')
def api_trans_quick():
    from engines.translation_studio.pipeline import translate_full
    d = request.get_json() or {}
    r = translate_full(d.get('text',''), d.get('src','zh'), d.get('tgt','en'),
                      quality=d.get('quality','standard'))
    return jsonify({'success': r.get('error_segments',0)==0, 'data': r})
