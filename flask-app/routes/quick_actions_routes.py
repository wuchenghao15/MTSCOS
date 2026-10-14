"""
quick_actions_routes — 用户上下文 + 快速 API (v22.36.0 P0 验证模块 #2)
=======================================================================
验证 Phase 5/6 代理模式在新代码上仍可工作。

路由 (代理模式: return _mt_sdb().xxx()):
  /api/quick/actions    → TODO (placeholder for future aggregator)
"""
from flask import Blueprint, jsonify
from app.middlewares.system_container import system_container

_bp = Blueprint('quick_actions_routes', __name__)
quick_actions_bp = _bp

_sdb = None


def _mt_sdb():
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


@_bp.route('/api/quick/actions', methods=['GET'])
@system_container(require_auth='login')
def api_quick_actions():
    """快速操作聚合 (placeholder) — 代理模式验证。当前返回空 actions 列表。
    后续可扩展: 用户常用操作推荐 / 最近考试 / 未完成任务等"""
    user_ctx = _mt_sdb()._safe_user_ctx(_mt_sdb()._current_user()) or {}
    return jsonify({
        'success': True,
        'user': user_ctx,
        'actions': [
            # 预留: 后续根据角色动态生成
        ],
        'hint': 'quick_actions_routes Phase 8 P0 验证模块',
    })
