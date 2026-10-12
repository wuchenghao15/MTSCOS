#!/usr/bin/env python3
"""
📝 copy_studio_routes.py — 文案创作中台路由蓝图 (P2)
=================================================
URL 前缀: /andromeda (注册到 andromeda_dashboard_bp)
@system_container 统一鉴权
API 端点:
  POST   /andromeda/api/copy_studio/projects          创建项目
  GET    /andromeda/api/copy_studio/projects          列表
  GET    /andromeda/api/copy_studio/projects/<id>     详情
  POST   /andromeda/api/copy_studio/projects/<id>/outline  生成大纲
  POST   /andromeda/api/copy_studio/projects/<id>/chapters  添加章节
  GET    /andromeda/api/copy_studio/projects/<id>/chapters  章节列表
  POST   /andromeda/api/copy_studio/chapters/<id>/write     AI 写章节
  POST   /andromeda/api/copy_studio/chapters/<id>/polish    AI 润色
  POST   /andromeda/api/copy_studio/projects/<id>/check    自巡检
  POST   /andromeda/api/copy_studio/projects/<id>/submit    提交审批
  GET    /andromeda/api/copy_studio/stats                   统计

页面:
  GET    /andromeda/copy_studio/workbench                  长篇小说工作台 (MVP)
"""
from __future__ import annotations
import json, datetime, uuid
from flask import Blueprint, jsonify, request, render_template, session as _sess
from pathlib import Path
from app.middlewares.system_container import system_container

# ── 蓝图 (独立注册, url_prefix=/andromeda 与 andromeda_dashboard_bp 对齐) ──
bp = Blueprint('copy_studio', __name__, url_prefix='/andromeda')


def _svc():
    """懒加载 Service 门面."""
    from engines.copy_studio.service import ApprovalService
    return ApprovalService()


def _user():
    username = _sess.get('username') or _sess.get('authenticated_username') or 'anonymous'
    role = (_sess.get('role') or _sess.get('user_role') or 'teacher').strip().lower()
    return username, role


# ═══════════════════════════════════════════════════════════
# 页面入口
# ═══════════════════════════════════════════════════════════

@bp.route('/copy_studio/workbench', methods=['GET'])
@system_container(require_auth='guest')
def copy_workbench():
    """📖 文案创作工作台 — 根据 genre 自动路由模板 (服务端模板选择 = 自动编译)"""
    genre = request.args.get('genre', 'novel')
    svc = _svc()
    stats = svc.stats()
    from engines.copy_studio.policy import GENRE_CONFIG
    return render_template(
        'copy_workbench.html',
        genre=genre,
        genre_cfg=GENRE_CONFIG.get(genre, GENRE_CONFIG['novel']),
        genres=[{'key': k, **v} for k, v in GENRE_CONFIG.items()],
        ollama_ok=stats['ollama_ok'],
        ollama_model=stats['ollama_model'],
        stats=stats,
    )


# ═══════════════════════════════════════════════════════════
# 项目 API
# ═══════════════════════════════════════════════════════════

@bp.route('/api/copy_studio/projects', methods=['POST'])
@system_container(require_auth='login')
def api_create_project():
    data = request.get_json(force=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'code': 1, 'msg': '标题必填'}), 400
    genre = (data.get('genre') or 'novel').strip()
    sub_genre = (data.get('sub_genre') or '').strip()
    target_words = int(data.get('target_words') or 50000)
    user_intent = (data.get('user_intent') or '').strip()
    style_guide = (data.get('style_guide') or '').strip()
    username, role = _user()
    svc = _svc()
    p = svc.create_project(
        title=title, genre=genre, sub_genre=sub_genre,
        target_words=target_words, initiator=username, initiator_role=role,
        user_intent=user_intent, style_guide=style_guide,
    )
    return jsonify({'code': 0, 'data': p})


@bp.route('/api/copy_studio/projects', methods=['GET'])
@system_container(require_auth='login')
def api_list_projects():
    username = _sess.get('username') or _sess.get('authenticated_username')
    genre = request.args.get('genre')
    status = request.args.get('status')
    limit = int(request.args.get('limit') or 50)
    svc = _svc()
    items = svc.list_projects(initiator=username, genre=genre, status=status, limit=limit)
    return jsonify({'code': 0, 'data': items})


@bp.route('/api/copy_studio/projects/<project_id>', methods=['GET'])
@system_container(require_auth='login')
def api_get_project(project_id: str):
    svc = _svc()
    p = svc.get_project(project_id)
    if not p:
        return jsonify({'code': 1, 'msg': '项目不存在'}), 404
    chapters = svc.list_chapters(project_id)
    p['chapters'] = chapters
    # 解析 outline_json
    try:
        p['outline'] = json.loads(p.get('outline_json') or '{}')
    except Exception:
        p['outline'] = {}
    return jsonify({'code': 0, 'data': p})


@bp.route('/api/copy_studio/projects/<project_id>/outline', methods=['POST'])
@system_container(require_auth='login')
def api_generate_outline(project_id: str):
    svc = _svc()
    p = svc.get_project(project_id)
    if not p:
        return jsonify({'code': 1, 'msg': '项目不存在'}), 404
    outline = svc.generate_outline(project_id)
    if outline is None:
        return jsonify({'code': 1, 'msg': 'Ollama 离线或生成失败'}), 503
    return jsonify({'code': 0, 'data': outline})


# ═══════════════════════════════════════════════════════════
# 章节 API
# ═══════════════════════════════════════════════════════════

@bp.route('/api/copy_studio/projects/<project_id>/chapters', methods=['POST'])
@system_container(require_auth='login')
def api_add_chapter(project_id: str):
    data = request.get_json(force=True) or {}
    chapter_no = int(data.get('chapter_no') or 0)
    if chapter_no <= 0:
        return jsonify({'code': 1, 'msg': 'chapter_no 必填'}), 400
    title = (data.get('title') or '').strip()
    summary = (data.get('summary') or '').strip()
    target_words = int(data.get('target_words') or 3000)
    svc = _svc()
    cid = svc.add_chapter(project_id, chapter_no, title=title, summary=summary, target_words=target_words)
    return jsonify({'code': 0, 'data': {'chapter_id': cid}})


@bp.route('/api/copy_studio/projects/<project_id>/chapters', methods=['GET'])
@system_container(require_auth='login')
def api_list_chapters(project_id: str):
    svc = _svc()
    chs = svc.list_chapters(project_id)
    return jsonify({'code': 0, 'data': chs})


@bp.route('/api/copy_studio/chapters/<chapter_id>/write', methods=['POST'])
@system_container(require_auth='login')
def api_write_chapter(chapter_id: str):
    svc = _svc()
    # 先找到 project_id (从 chapter 表)
    from engines.copy_studio.db import get_conn
    with get_conn() as c:
        row = c.execute("SELECT project_id FROM mt_copy_chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
    if not row:
        return jsonify({'code': 1, 'msg': '章节不存在'}), 404
    res = svc.write_chapter(row['project_id'], chapter_id=chapter_id)
    if res is None:
        return jsonify({'code': 1, 'msg': 'Ollama 离线或生成失败'}), 503
    return jsonify({'code': 0, 'data': res})


@bp.route('/api/copy_studio/chapters/<chapter_id>/polish', methods=['POST'])
@system_container(require_auth='login')
def api_polish_chapter(chapter_id: str):
    data = request.get_json(force=True) or {}
    style_hint = (data.get('style_hint') or '').strip()
    svc = _svc()
    res = svc.polish_chapter(chapter_id, style_hint=style_hint)
    if res is None:
        return jsonify({'code': 1, 'msg': 'Ollama 离线或章节无内容'}), 503
    return jsonify({'code': 0, 'data': res})


# ═══════════════════════════════════════════════════════════
# 自巡检 + 审批
# ═══════════════════════════════════════════════════════════

@bp.route('/api/copy_studio/projects/<project_id>/check', methods=['POST'])
@system_container(require_auth='login')
def api_consistency_check(project_id: str):
    svc = _svc()
    issues = svc.run_consistency_check(project_id)
    return jsonify({'code': 0, 'data': {'issues': issues, 'count': len(issues)}})


@bp.route('/api/copy_studio/projects/<project_id>/submit', methods=['POST'])
@system_container(require_auth='login')
def api_submit_approval(project_id: str):
    svc = _svc()
    aid = svc.submit_for_approval(project_id)
    if aid is None:
        return jsonify({'code': 1, 'msg': 'approval 中台不可用'}), 503
    return jsonify({'code': 0, 'data': {'approval_id': aid}})


@bp.route('/api/copy_studio/stats', methods=['GET'])
@system_container(require_auth='login')
def api_stats():
    svc = _svc()
    return jsonify({'code': 0, 'data': svc.stats()})
