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
  POST   /andromeda/api/copy_studio/chapters/<id>/write_stream  SSE 流式写作
  POST   /andromeda/api/copy_studio/chapters/<id>/polish    AI 润色
  GET    /andromeda/api/copy_studio/projects/<id>/characters 角色列表
  POST   /andromeda/api/copy_studio/projects/<id>/characters 新建角色
  PUT    /andromeda/api/copy_studio/characters/<cid>        更新角色
  DELETE /andromeda/api/copy_studio/characters/<cid>        删除角色
  POST   /andromeda/api/copy_studio/projects/<id>/check    自巡检
  POST   /andromeda/api/copy_studio/projects/<id>/submit    提交审批
  GET    /andromeda/api/copy_studio/stats                   统计

页面:
  GET    /andromeda/copy_studio/workbench                  长篇小说工作台 (MVP)
"""
from __future__ import annotations
import json, datetime, uuid
from flask import Blueprint, jsonify, request, render_template, session as _sess, Response, stream_with_context
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


@bp.route('/api/copy_studio/chapters/<chapter_id>/write_stream', methods=['POST'])
@system_container(require_auth='login')
def api_write_chapter_stream(chapter_id: str):
    """🚄 SSE 流式 AI 写章节 — 逐块推送事件 (chunk/done/error), 零 token 本地推理."""
    svc = _svc()
    from engines.copy_studio.db import get_conn
    with get_conn() as c:
        row = c.execute("SELECT project_id FROM mt_copy_chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
    if not row:
        return jsonify({'code': 1, 'msg': '章节不存在'}), 404
    gen = svc.write_chapter_stream(row['project_id'], chapter_id=chapter_id)
    if gen is None:
        return jsonify({'code': 1, 'msg': '章节不存在'}), 404

    def _sse():
        try:
            for ev in gen:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': str(e)}, ensure_ascii=False)}\n\n"

    resp = Response(stream_with_context(_sse()), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


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
# 角色卡 API (Step2)
# ═══════════════════════════════════════════════════════════

@bp.route('/api/copy_studio/projects/<project_id>/characters', methods=['GET'])
@system_container(require_auth='login')
def api_list_characters(project_id: str):
    svc = _svc()
    if not svc.get_project(project_id):
        return jsonify({'code': 1, 'msg': '项目不存在'}), 404
    return jsonify({'code': 0, 'data': svc.list_characters(project_id)})


@bp.route('/api/copy_studio/projects/<project_id>/characters', methods=['POST'])
@system_container(require_auth='login')
def api_create_character(project_id: str):
    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'code': 1, 'msg': '角色名必填'}), 400
    svc = _svc()
    if not svc.get_project(project_id):
        return jsonify({'code': 1, 'msg': '项目不存在'}), 404
    c = svc.create_character(
        project_id, name,
        role_type=(data.get('role_type') or 'supporting').strip(),
        personality=(data.get('personality') or '').strip(),
        appearance=(data.get('appearance') or '').strip(),
        backstory=(data.get('backstory') or '').strip(),
        goals=(data.get('goals') or '').strip(),
        conflicts=(data.get('conflicts') or '').strip(),
        relationships=(data.get('relationships') or '').strip(),
        tags=(data.get('tags') or '').strip(),
    )
    return jsonify({'code': 0, 'data': c})


@bp.route('/api/copy_studio/characters/<character_id>', methods=['PUT'])
@system_container(require_auth='login')
def api_update_character(character_id: str):
    data = request.get_json(force=True) or {}
    svc = _svc()
    fields = {}
    for k in ('name', 'role_type', 'personality', 'appearance', 'backstory',
              'goals', 'conflicts'):
        if isinstance(data.get(k), str):
            fields[k] = data[k]
    for k in ('relationships', 'tags'):
        if isinstance(data.get(k), str):
            fields[k + '_json'] = json.dumps(
                [s.strip() for s in data[k].split(',') if s.strip()], ensure_ascii=False)
    c = svc.update_character(character_id, **fields)
    if not c:
        return jsonify({'code': 1, 'msg': '角色不存在'}), 404
    return jsonify({'code': 0, 'data': c})


@bp.route('/api/copy_studio/characters/<character_id>', methods=['DELETE'])
@system_container(require_auth='login')
def api_delete_character(character_id: str):
    svc = _svc()
    if not svc.delete_character(character_id):
        return jsonify({'code': 1, 'msg': '角色不存在'}), 404
    return jsonify({'code': 0, 'data': {'deleted': character_id}})


# ═══════════════════════════════════════════════════════════
# 章节版本历史 (Step3)
# ═══════════════════════════════════════════════════════════

@bp.route('/api/copy_studio/chapters/<chapter_id>/versions', methods=['GET'])
@system_container(require_auth='login')
def api_list_versions(chapter_id: str):
    svc = _svc()
    # 章节存在性校验
    from engines.copy_studio.db import get_conn
    with get_conn() as c:
        ch = c.execute("SELECT chapter_id FROM mt_copy_chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
    if not ch:
        return jsonify({'code': 1, 'msg': '章节不存在'}), 404
    limit = int(request.args.get('limit') or 20)
    vers = svc.list_versions(chapter_id, limit=limit)
    return jsonify({'code': 0, 'data': vers})


@bp.route('/api/copy_studio/versions/<version_id>', methods=['GET'])
@system_container(require_auth='login')
def api_get_version(version_id: str):
    svc = _svc()
    v = svc.get_version(version_id)
    if not v:
        return jsonify({'code': 1, 'msg': '版本不存在'}), 404
    return jsonify({'code': 0, 'data': v})


@bp.route('/api/copy_studio/versions/<version_id>/restore', methods=['POST'])
@system_container(require_auth='login')
def api_restore_version(version_id: str):
    svc = _svc()
    res = svc.restore_version(version_id)
    if not res:
        return jsonify({'code': 1, 'msg': '版本不存在'}), 404
    return jsonify({'code': 0, 'data': res})


# ═══════════════════════════════════════════════════════════
# 自巡检 + 审批
# ═══════════════════════════════════════════════════════════

@bp.route('/api/copy_studio/projects/<project_id>/check', methods=['POST'])
@system_container(require_auth='login')
def api_consistency_check(project_id: str):
    """一致性巡检. body 可选: auto_fix=true (生成修复草案, 不覆盖正文)."""
    req = request.get_json(silent=True) or {}
    auto_fix = bool(req.get('auto_fix', False))
    svc = _svc()
    issues = svc.run_consistency_check(project_id, auto_fix=auto_fix)
    sev_count = {}
    for iss in issues:
        sev_count[iss.get('severity', 'info')] = sev_count.get(iss.get('severity', 'info'), 0) + 1
    auto_ready = sum(1 for i in issues if i.get('auto_fix_status') == 'draft_ready')
    return jsonify({
        'code': 0,
        'data': {
            'issues': issues,
            'count': len(issues),
            'severity_count': sev_count,
            'auto_fix': {'requested': auto_fix, 'draft_ready': auto_ready, 'manual_needed': len(issues) - auto_ready if auto_fix else None},
            'rules_used': ['dialogue_mark', 'overlong_paragraph', 'ai_tone', 'pronoun_shift',
                           'char_name_drift', 'half_width_punct', 'excessive_punct', 'cross_chapter_repeat'],
        }
    })


@bp.route('/api/copy_studio/projects/<project_id>/rag_stats', methods=['GET'])
@system_container(require_auth='login')
def api_rag_stats(project_id: str):
    """RAG 索引统计: chunk 总数 / embed_model 分布 / 各章节 chunk 数 / 最后一次 upsert 时间."""
    from engines.copy_studio.db import get_conn
    with get_conn() as c:
        # 总数
        total = c.execute(
            "SELECT COUNT(*) as n FROM mt_copy_chunks WHERE project_id=?", (project_id,)).fetchone()['n']
        # embed_model 分布
        dist = [dict(r) for r in c.execute(
            "SELECT embed_model, COUNT(*) as n FROM mt_copy_chunks WHERE project_id=? GROUP BY embed_model",
            (project_id,)).fetchall()]
        # 各章节 chunk 数
        per_ch = [dict(r) for r in c.execute(
            """SELECT ch.chapter_no, ch.title, COUNT(c.chunk_id) as n
               FROM mt_copy_chapters ch
               LEFT JOIN mt_copy_chunks c ON c.chapter_id = ch.chapter_id AND c.project_id = ch.project_id
               WHERE ch.project_id = ?
               GROUP BY ch.chapter_id, ch.chapter_no, ch.title
               ORDER BY ch.chapter_no""", (project_id,)).fetchall()]
        # 最后一次 upsert
        last = c.execute(
            "SELECT MAX(created_at) as t FROM mt_copy_chunks WHERE project_id=?", (project_id,)).fetchone()['t']
    return jsonify({
        'code': 0,
        'data': {
            'project_id': project_id,
            'total_chunks': total,
            'embed_model_distribution': dist,
            'per_chapter': per_ch,
            'last_indexed_at': last,
        }
    })


@bp.route('/api/copy_studio/projects/<project_id>/issues', methods=['GET'])
@system_container(require_auth='login')
def api_list_issues(project_id: str):
    """列出项目一致性巡检记录. query: status=applied/rejected/pending, severity=, issue_type=, chapter_id=."""
    from engines.copy_studio.db import get_conn
    status = request.args.get('status', '')
    severity = request.args.get('severity', '')
    issue_type = request.args.get('issue_type', '')
    chapter_id = request.args.get('chapter_id', '')
    only_fixable = request.args.get('fixable_only', '')

    where = ['project_id = ?']
    params: list = [project_id]
    if status:
        where.append("auto_fix_status = ?")
        params.append(status)
    if severity:
        where.append("severity = ?")
        params.append(severity)
    if issue_type:
        where.append("issue_type = ?")
        params.append(issue_type)
    if chapter_id:
        where.append("chapter_id = ?")
        params.append(chapter_id)
    if only_fixable:
        where.append("auto_fix_status = 'pending' AND fixed_content IS NOT NULL")

    with get_conn() as c:
        rows = [dict(r) for r in c.execute(
            f"""SELECT l.*, ch.title as chapter_title, ch.chapter_no
                FROM mt_copy_consistency_log l
                LEFT JOIN mt_copy_chapters ch ON ch.chapter_id = l.chapter_id
                WHERE {' AND '.join(where)}
                ORDER BY l.created_at DESC, ch.chapter_no""", params).fetchall()]
        # 统计
        counts = {}
        for row in rows:
            k = row.get('auto_fix_status', 'pending')
            counts[k] = counts.get(k, 0) + 1
    return jsonify({
        'code': 0,
        'data': {'issues': rows, 'total': len(rows), 'status_counts': counts,
                 'project_id': project_id}
    })


@bp.route('/api/copy_studio/fix/<int:log_id>', methods=['POST'])
@system_container(require_auth='login')
def api_apply_fix(log_id: int):
    """接受/拒绝单条 auto_fix 草案. body: {accept: true/false, manual_content?: '...'}"""
    req = request.get_json(silent=True) or {}
    accept = bool(req.get('accept', True))
    manual = req.get('manual_content') if accept else None
    svc = _svc()
    result = svc.apply_fix(log_id, accept=accept, manual_content=manual)
    if result is None:
        return jsonify({'code': 404, 'msg': 'consistency_log row not found'}), 404
    return jsonify({'code': 0, 'data': result})


@bp.route('/api/copy_studio/fix_batch', methods=['POST'])
@system_container(require_auth='login')
def api_apply_fix_batch():
    """批量接受/拒绝. body: {log_ids: [1,2,3], accept: true/false}"""
    req = request.get_json(silent=True) or {}
    ids = req.get('log_ids') or []
    accept = bool(req.get('accept', True))
    if not ids:
        return jsonify({'code': 400, 'msg': 'log_ids required'}), 400
    svc = _svc()
    results = svc.apply_fix_batch(ids, accept=accept)
    success = sum(1 for r in results if r and r.get('status') in ('applied', 'already_applied', 'already_rejected'))
    return jsonify({'code': 0, 'data': {'results': results, 'total': len(ids), 'success': success}})


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
