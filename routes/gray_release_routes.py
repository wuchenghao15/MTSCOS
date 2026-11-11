#!/usr/bin/env python3
"""
🟢 仙女座灰度发布 API 蓝图 — routes/gray_release_routes.py
===========================================================
端点全览:
  POST /api/gray/releases                    新建发布 (自动提交审批)
  GET  /api/gray/releases                    列出 (支持 status filter)
  GET  /api/gray/releases/<rel_id>          详情 + 指标
  POST /api/gray/releases/<rel_id>/start    审批通过 → canary
  POST /api/gray/releases/<rel_id>/advance  升 stage (自动门禁)
  POST /api/gray/releases/<rel_id>/rollback 一键回滚
  POST /api/gray/releases/<rel_id>/metrics  采集指标
  POST /api/gray/progress                   自动推进所有 releasing (daemon 调)
  GET  /api/gray/flags                      feature flags 列表
  POST /api/gray/flags                      创建 feature flag
  GET  /api/gray/flags/<name>/check         检查用户是否命中灰度
  GET  /gray/center                         灰度发布工作台页面
"""
from __future__ import annotations
import sys, hashlib, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, request, jsonify, session, render_template

gray_bp = Blueprint('gray_release', __name__)

_engine = None
def _get_engine():
    global _engine
    if _engine is None:
        from engines.gray_release_engine import GrayReleaseEngine
        _engine = GrayReleaseEngine()
    return _engine


@gray_bp.route('/api/gray/releases', methods=['POST'])
def api_create_release():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name', ''); target = data.get('target_version', ''); scope = data.get('scope', 'flask_engine')
    if not name or not target:
        return jsonify({'ok': False, 'msg': 'name & target_version required'}), 400
    eng = _get_engine()
    rid = eng.create_release(
        name=name, target_version=target, scope=scope,
        description=data.get('description', ''),
        change_summary=data.get('change_summary', {}),
        risk_level=data.get('risk_level', 'medium'),
        initiator=session.get('username') or 'anonymous')
    return jsonify({'ok': True, 'release_id': rid})


@gray_bp.route('/api/gray/releases', methods=['GET'])
def api_list_releases():
    status = request.args.get('status', '')
    eng = _get_engine()
    rels = eng.list_releases(status=status)
    return jsonify({'ok': True, 'releases': rels, 'count': len(rels)})


@gray_bp.route('/api/gray/releases/<rel_id>', methods=['GET'])
def api_release_detail(rel_id):
    d = _get_engine().get_release(rel_id)
    if not d: return jsonify({'ok': False, 'msg': 'not found'}), 404
    return jsonify({'ok': True, 'data': d})


@gray_bp.route('/api/gray/releases/<rel_id>/start', methods=['POST'])
def api_start_release(rel_id):
    eng = _get_engine()
    res = eng.approve_and_start(rel_id, session.get('username') or 'anonymous')
    return jsonify({'ok': res.get('ok', True), 'data': res})


@gray_bp.route('/api/gray/releases/<rel_id>/advance', methods=['POST'])
def api_advance(rel_id):
    force = request.get_json(force=True, silent=True).get('force', False) if request.get_json(silent=True) else False
    res = _get_engine().advance_stage(rel_id, force=force)
    return jsonify({'ok': res.get('ok', True), 'data': res})


@gray_bp.route('/api/gray/releases/<rel_id>/rollback', methods=['POST'])
def api_rollback(rel_id):
    data = request.get_json(force=True, silent=True) or {}
    reason = data.get('reason', 'manual rollback')
    res = _get_engine().rollback(rel_id, reason=reason, actor=session.get('username') or 'cli')
    return jsonify({'ok': True, 'data': res})


@gray_bp.route('/api/gray/releases/<rel_id>/metrics', methods=['POST'])
def api_collect_metrics(rel_id):
    m = _get_engine().collect_metrics(rel_id)
    return jsonify({'ok': True, 'metrics': m})


@gray_bp.route('/api/gray/progress', methods=['POST'])
def api_progress_all():
    """daemon 调 — 自动推进所有 releasing"""
    res = _get_engine().auto_progress_releases()
    return jsonify({'ok': True, 'results': res, 'count': len(res)})


@gray_bp.route('/api/gray/flags', methods=['GET'])
def api_list_flags():
    import sqlite3
    db = sqlite3.connect(str(Path(__file__).parent.parent / 'database' / 'app.db'))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM mt_release_feature_flags ORDER BY updated_at DESC").fetchall()
    return jsonify({'ok': True, 'flags': [dict(r) for r in rows]})


@gray_bp.route('/api/gray/flags', methods=['POST'])
def api_create_flag():
    import sqlite3
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('flag_name', ''); pct = int(data.get('rollout_pct', 0))
    if not name: return jsonify({'ok': False, 'msg': 'flag_name required'}), 400
    salt = hashlib.md5(name.encode()).hexdigest()[:8]
    db = sqlite3.connect(str(Path(__file__).parent.parent / 'database' / 'app.db'))
    db.execute("INSERT OR REPLACE INTO mt_release_feature_flags (flag_name, rollout_pct, description, scope, salt) "
               "VALUES (?,?,?,?,?)",
               (name, pct, data.get('description', ''), data.get('scope', 'all'), salt))
    db.commit(); db.close()
    return jsonify({'ok': True, 'flag_name': name, 'rollout_pct': pct})


@gray_bp.route('/api/gray/flags/<flag_name>/check', methods=['GET'])
def api_check_flag(flag_name):
    user_id = request.args.get('user_id', session.get('username', 'anonymous'))
    from engines.gray_release_engine import check_feature_flag
    on = check_feature_flag(flag_name, user_id)
    return jsonify({'ok': True, 'flag_name': flag_name, 'user_id': user_id, 'enabled': on})


# ═══════════════════════════════════════════════════════════
# 工作台页面 (返回 JSON 给后续前端用)
# ═══════════════════════════════════════════════════════════
@gray_bp.route('/gray/center', methods=['GET'])
def gray_center():
    eng = _get_engine()
    rels = eng.list_releases()
    return render_template(
        'andromeda_gray_center.html',
        releases=rels,
        username=session.get('username', 'anonymous'),
        role=session.get('role', ''),
    )
