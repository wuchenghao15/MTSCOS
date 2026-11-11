"""
仙女座参数中心路由 (Andromeda Param Center)
=============================================
flow_andromeda_param_20261021 · MT_RULE_PARAM 规范§6 权限模型:
  查询/统计  → 登录用户
  修改/创建  → super_admin (wuchenghao15) + 变更审计落库
  删除       → super_admin + 审计留痕

引擎: engines/ai_param_center_engine.py (统一参数体系 mt_param_registry)
"""
from __future__ import annotations
import os
import sys

from flask import Blueprint, jsonify, render_template, request, session

bp = Blueprint('andromeda_param', __name__, url_prefix='/andromeda')
# 注册别名 (routes/__init__.py _modules 表按 andromeda_param_bp 取 attr)
andromeda_param_bp = bp

_FLASK_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINES = os.path.join(_FLASK_APP, 'engines')
_SA = 'wuchenghao15'


def _engine():
    if _ENGINES not in sys.path:
        sys.path.insert(0, _ENGINES)
    import ai_param_center_engine as pce
    pce.ensure_tables()
    return pce


def _is_sa() -> bool:
    return session.get('username') == _SA or session.get('role') == 'super_admin'


# ── 页面 ──────────────────────────────────────────────────────
@bp.route('/param_center', methods=['GET'])
def param_center_page():
    """⚙️ 仙女座参数中心 — 统一参数体系面板"""
    from flask import session as _sess
    is_sa = _sess.get('username') == _SA or _sess.get('role') == 'super_admin'
    return render_template('andromeda_param_center.html', is_sa=is_sa)


# ── API: 查询 (登录即可) ──────────────────────────────────────
@bp.route('/api/param/list', methods=['GET'])
def api_param_list():
    """参数清单 ?domain=ai  (is_secret=1 值脱敏)"""
    pce = _engine()
    return jsonify({'success': True,
                    'data': pce.list_params(domain=(request.args.get('domain') or '').strip())})


@bp.route('/api/param/stats', methods=['GET'])
def api_param_stats():
    """参数体系总览: 域分布/类型分布/健康度/最近巡检"""
    pce = _engine()
    return jsonify({'success': True, 'data': pce.stats()})


@bp.route('/api/param/changelog', methods=['GET'])
def api_param_changelog():
    """变更审计链 (规范§6 留痕可溯) ?limit=50"""
    import sqlite3 as _sq3
    pce = _engine()
    limit = min(int(request.args.get('limit') or 50), 200)
    conn = _sq3.connect(pce.APP_DB, timeout=10)
    conn.row_factory = _sq3.Row
    rows = [dict(r) for r in conn.execute(
        f"SELECT param_key, action, old_value, new_value, operator, flow_id, created_at "
        f"FROM {pce.CHANGELOG_TABLE} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    conn.close()
    for r in rows:
        if r.get('old_value'):
            r['old_value'] = r['old_value'][:80]
        if r.get('new_value'):
            r['new_value'] = r['new_value'][:80]
    return jsonify({'success': True, 'data': rows})


# ── API: 修改 (仅 SA, 审计落库) ────────────────────────────────
@bp.route('/api/param/set', methods=['POST'])
def api_param_set():
    """创建/修改参数 — 仅 super_admin (规范§6.1)"""
    if not _is_sa():
        return jsonify({'success': False, 'error': '仅超级管理员可修改参数 (MT_RULE_PARAM §6.1)'}), 403
    d = request.get_json(silent=True) or {}
    key = (d.get('param_key') or '').strip()
    if not key:
        return jsonify({'success': False, 'error': '缺少 param_key'})
    pce = _engine()
    r = pce.set_param(key, d.get('value'), operator=session.get('username') or _SA,
                      data_type=d.get('data_type'), scope=d.get('scope'),
                      description=d.get('description') or '',
                      is_secret=1 if d.get('is_secret') else 0,
                      flow_id=d.get('flow_id') or 'flow_andromeda_param_20261021')
    return jsonify({'success': bool(r.get('ok')), 'data': r})


@bp.route('/api/param/delete', methods=['POST'])
def api_param_delete():
    """删除参数 — 仅 super_admin + 审计留痕"""
    if not _is_sa():
        return jsonify({'success': False, 'error': '仅超级管理员可删除参数 (MT_RULE_PARAM §6.1)'}), 403
    d = request.get_json(silent=True) or {}
    key = (d.get('param_key') or '').strip()
    if not key:
        return jsonify({'success': False, 'error': '缺少 param_key'})
    pce = _engine()
    r = pce.delete_param(key, operator=session.get('username') or _SA,
                         flow_id=d.get('flow_id') or 'flow_andromeda_param_20261021')
    return jsonify({'success': bool(r.get('ok')), 'data': r})


@bp.route('/api/param/scan', methods=['POST'])
def api_param_scan():
    """手动触发参数健康巡检 (登录可触发, 修改无需权限—只读扫描+落库)"""
    pce = _engine()
    return jsonify({'success': True, 'data': pce.scan()})
