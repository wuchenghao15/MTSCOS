"""
exam_post_routes — exam 域 POST 提交路由 (v22.35.0 Phase 5 拆分)
=================================================================
从 server_real_db.py 迁移 exam 域 POST 提交 handler (自定义考试/练习提交)。

代理模式: blueprint handler 不复制 sdb 已有的长函数体，而是 return _mt_sdb().xxx_post()
  - 函数定义保留在 sdb 不动（它们的内部 def/常量引用都在 sdb 模块作用域）
  - 只删除 sdb 里的 @app.route 装饰器，让路由挂在本 blueprint 上

迁移路由:
  /exam_system/create_custom_exam (POST) → sdb.create_custom_exam_post()
  /exam_system/create_custom_test (POST) → sdb.create_custom_test_post()

不动: 函数定义 / _CUSTOM_EXAM_ALLOWED_SUBJECTS 等常量（仍在 sdb 模块作用域）
"""
from flask import Blueprint
from app.middlewares.system_container import system_container

_bp = Blueprint('exam_post_routes', __name__)
exam_post_bp = _bp

_sdb = None


def _mt_sdb():
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


# ═══════════════════════════════════════════════════════════════════════
# 代理 handlers — 转发到 server_real_db 已有的函数定义
# ═══════════════════════════════════════════════════════════════════════

@_bp.route('/exam_system/create_custom_exam', methods=['POST'])
@system_container(require_auth='login')
def create_custom_exam_post():
    """Phase 5 代理: 调用 sdb.create_custom_exam_post() — 函数定义保留在 sdb
    (含 _CUSTOM_EXAM_ALLOWED_SUBJECTS/_VERIFY/DDL 等模块级常量与辅助函数)"""
    return _mt_sdb().create_custom_exam_post()


@_bp.route('/exam_system/create_custom_test', methods=['POST'])
@system_container(require_auth='login')
def create_custom_test_post():
    """Phase 5 代理: 调用 sdb.create_custom_test_post()"""
    return _mt_sdb().create_custom_test_post()
