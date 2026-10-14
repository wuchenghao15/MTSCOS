"""
system_health_routes — 系统健康/状态路由 (v22.35.0 Phase 6 拆分)
===============================================================
从 server_real_db.py 迁移 health 域路由（代理模式 + 修复重复注册）。

迁移路由 (代理模式: return _mt_sdb().xxx()):
  /api/health         → sdb.api_health_check()  (轻量 DB 检查, 无认证)
  /api/system_health  → sdb.system_health_api() (系统健康聚合, admin 权限)

BUG 修复: server_real_db.py 里 /api/health 重复注册了两次
  L9030 @app.route('/api/health') → def api_health_check()  ← 保留函数体, 搬路由到本蓝图
  L14482 @app.route('/api/health') → def health()            ← 函数体保留, 路由改名为 /api/health/v2
"""
from flask import Blueprint
from app.middlewares.system_container import system_container

_bp = Blueprint('system_health_routes', __name__)
system_health_bp = _bp

_sdb = None


def _mt_sdb():
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


# ═══════════════════════════════════════════════════════════════════════
# 代理 handlers — 转发到 server_real_db 函数定义
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/api/health', methods=['GET'])
@system_container(require_auth='admin')
def api_health_check():
    """轻量健康检查: DB SELECT 1, 无认证 (前端 MTNetGuard 专用)"""
    return _mt_sdb().api_health_check()


@_bp.route('/api/system_health', methods=['GET'])
@system_container(require_auth='admin', allowed_roles=['super_admin', 'sadmin', 'admin'])
def system_health_api():
    """系统健康聚合: 6 大子系统健康状态, admin 权限"""
    return _mt_sdb().system_health_api()


# Phase 6 BUG 修复: 原 server_real_db.py L14482 有第二个 @app.route('/api/health') def health()
# 这是重复注册！给它一个独立路径 /api/system/meta 避免 endpoint 冲突
@_bp.route('/api/system/meta', methods=['GET'])
@system_container(require_auth='admin')
def health_version():
    """系统元信息端点 (原 /api/health 重复注册修复) — 返回版本号/构建时间等"""
    return _mt_sdb().health()
