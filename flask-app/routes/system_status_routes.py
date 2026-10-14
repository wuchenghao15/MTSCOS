"""
system_status_routes — 系统状态面板 (v22.36.0 P0 验证模块 #1)
=============================================================
验证 Phase 2/3/4 完整复制 + 延迟绑定 模式在新代码上仍可工作。

路由:
  /system/status     → render_template('system_status.html') 展示 6 维健康面板 (admin)
  /system/health     → JSON 接口 (代理 sdb._aggregate_system_health)
"""
from flask import Blueprint, render_template, jsonify
from app.middlewares.system_container import system_container

_bp = Blueprint('system_status_routes', __name__)
system_status_bp = _bp

_sdb = None


def _mt_sdb():
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


@_bp.route('/system/status', methods=['GET'])
@system_container(require_auth='admin', allowed_roles=['super_admin', 'sadmin', 'admin'])
def system_status_page():
    """系统状态面板 — 完整复制模式验证。调用 sdb 内部函数 + render_template"""
    sdb = _mt_sdb()
    health = sdb._aggregate_system_health()
    v, info, _ = sdb.get_version_info()
    ctx = {
        'health': health,
        'subsystems': health.get('subsystems', {}),
        'overall_status': health.get('overall_status', 'UNKNOWN'),
        'timestamp': health.get('timestamp', ''),
        'version': v,
        'version_info': info,
        'user': sdb._safe_user_ctx(sdb._current_user()),
    }
    return render_template('system_status.html', **ctx)


@_bp.route('/system/health', methods=['GET'])
def system_health_json():
    """系统健康 JSON 接口 — 轻量无认证, 供前端仪表板轮询"""
    return jsonify(_mt_sdb()._aggregate_system_health())
