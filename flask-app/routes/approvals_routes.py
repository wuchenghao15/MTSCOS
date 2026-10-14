#!/usr/bin/env python3
"""
📋 仙女座审批 API 蓝图 — routes/approvals_routes.py
===============================================
端点全览:
  POST /api/approvals/submit            提交审批
  POST /api/approvals/<id>/action       审批动作 (approve/reject)
  GET  /api/approvals/list              我的所有
  GET  /api/approvals/pending           待我审批 (按 session role)
  GET  /api/approvals/<id>              详情 + 节点
  POST /api/approvals/wenquxing         文曲星产出一键提审
  POST /api/approvals/auto              触发仙女座自动审批 (daemon 调)
  GET  /approvals/center                审批工作台页面
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, request, jsonify, session, render_template

approvals_bp = Blueprint('approvals', __name__)

# 懒加载 — 避免循环导入
_engine = None
def _get_engine():
    global _engine
    if _engine is None:
        from engines.approvals_engine import ApprovalEngine
        _engine = ApprovalEngine()
    return _engine

def _current_user():
    return session.get('username') or 'anonymous'

def _current_role():
    return session.get('role') or ''


@approvals_bp.route('/api/approvals/submit', methods=['POST'])
def api_submit():
    """手动提交审批"""
    data = request.get_json(force=True, silent=True) or {}
    cat = data.get('category', '')
    sid = data.get('subject_id', '')
    snap = data.get('subject_snapshot', {})
    hint = data.get('subject_hint', '')
    if not cat:
        return jsonify({'ok': False, 'msg': 'category required'}), 400
    rid = _get_engine().submit(
        category=cat, subject_id=sid, subject_snapshot=snap,
        initiator=_current_user(), initiator_role=_current_role(),
        subject_hint=hint)
    return jsonify({'ok': True, 'request_id': rid})


@approvals_bp.route('/api/approvals/<request_id>', methods=['GET'])
def api_detail(request_id):
    d = _get_engine().get_request(request_id)
    if not d:
        return jsonify({'ok': False, 'msg': 'not found'}), 404
    return jsonify({'ok': True, 'data': d})


@approvals_bp.route('/api/approvals/<request_id>/action', methods=['POST'])
def api_action(request_id):
    """approve / reject"""
    data = request.get_json(force=True, silent=True) or {}
    action = data.get('action', '').lower()
    node_idx = data.get('node_index', 0)
    notes = data.get('notes', '')
    if action not in ('approve', 'reject'):
        return jsonify({'ok': False, 'msg': 'action must be approve/reject'}), 400
    res = _get_engine().action(
        request_id, int(node_idx), action,
        actor=_current_user(), actor_role=_current_role(), notes=notes)
    return jsonify(res)


@approvals_bp.route('/api/approvals/pending', methods=['GET'])
def api_pending():
    """当前用户角色的待审批"""
    role = _current_role()
    if not role:
        return jsonify({'ok': False, 'msg': 'need login'}), 401
    p = _get_engine().list_pending(role)
    return jsonify({'ok': True, 'pending': p, 'count': len(p)})


@approvals_bp.route('/api/approvals/list', methods=['GET'])
def api_list():
    """所有申请 (可按 initiator/status/cat 过滤)"""
    engine = _get_engine()
    rows = engine.list_pending(limit=100)  # 先全量
    # 简单过滤: 支持 ?status=&category=&initiator=
    st = request.args.get('status', '')
    cat = request.args.get('category', '')
    init = request.args.get('initiator', '')
    if st: rows = [r for r in rows if r.get('status') == st]
    if cat: rows = [r for r in rows if r.get('category') == cat]
    if init: rows = [r for r in rows if r.get('initiator') == init]
    return jsonify({'ok': True, 'list': rows, 'count': len(rows)})


@approvals_bp.route('/api/approvals/wenquxing', methods=['POST'])
def api_wenquxing_submit():
    """文曲星产出一键提审 — 自动判断风险"""
    data = request.get_json(force=True, silent=True) or {}
    task_id = data.get('task_id', '')
    preview = data.get('preview', '')
    from engines.approvals_engine import submit_wenquxing_for_approval
    rid = submit_wenquxing_for_approval(
        task_id=task_id, final_text=preview,
        initiator=_current_user(), initiator_role=_current_role())
    return jsonify({'ok': True, 'request_id': rid})


@approvals_bp.route('/api/approvals/auto', methods=['POST'])
def api_auto_approve():
    """触发仙女座自动审批 — daemon/内部调用"""
    res = _get_engine().auto_approve_low_risk()
    return jsonify({'ok': True, 'auto_passed': len(res), 'details': res})


@approvals_bp.route('/api/approvals/preview', methods=['GET'])
def api_preview_chain():
    """预览审批链 (不提交) — GET ?category=&role=&hint="""
    from engines.approvals_engine import build_approval_nodes, assess_risk
    cat = request.args.get('category', '')
    role = request.args.get('role', '')
    hint = request.args.get('hint', '')
    if not cat or not role:
        return jsonify({'ok': False, 'msg': 'category & role required'}), 400
    risk = assess_risk(cat, role, hint)
    nodes = build_approval_nodes(cat, role, risk, subject_hint=hint)
    return jsonify({'ok': True, 'risk': risk, 'nodes': nodes})


# ═══════════════════════════════════════════════════════════
# 审批工作台页面
# ═══════════════════════════════════════════════════════════
@approvals_bp.route('/approvals/center', methods=['GET'])
def approvals_center():
    role = _current_role()
    username = _current_user()
    engine = _get_engine()
    pending = engine.list_pending(role) if role else []
    my_submissions = [r for r in engine.list_pending(limit=50)
                      if r.get('initiator') == username]
    return render_template(
        'andromeda_approval_center.html',
        role=role, username=username,
        pending=pending, my_submissions=my_submissions,
    )
