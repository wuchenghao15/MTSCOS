#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOSBlueprint 基类 - Flask Blueprint 统一基类
======================================================
§14 IRON_RULE · STEP_7_EXECUTE · 模块1 后端Blueprint P1
flow_id: flow_dev_pages_functions_complete_20260818_001
目标版本: v21.12.1 (L3_FIX基于v21.12.0)

设计目标(对齐开发规则 §3.1 + 用户权限.md @system_container + 设计规范):
  1. 继承 Flask Blueprint, 不破坏现有 Blueprint(name, __name__) 用法
  2. 内置 @system_container 装饰器 4级权限模型(guest/login/admin/super_admin)
  3. 内置统一响应 build_success_response / build_error_response
  4. 内置错误码字典查询 mt_exception_code_dict
  5. 内置错误处理器 errorhandler(401/403/404/500/504/503/429/Exception)
  6. 内置容错注册 register_to(app) 单蓝图失败不影响整体(对齐B轮B3隔离决议)
  7. 内置蓝图失败日志落库 mt_blueprint_fail_log (模块4 P1-C)
  8. 内置业务域隔离机制(对齐B轮B3蓝图按业务域隔离)

用法(替代 Blueprint):
  from app.utils.mtscos_blueprint import MTSCOSBlueprint
  ai_dashboard_api = MTSCOSBlueprint('ai_dashboard_api', __name__,
                                       business_domain='ai', require_auth='admin')

  @ai_dashboard_api.route('/api/ai/dashboard/overview', methods=['GET'])
  @ai_dashboard_api.require_login()  # 等价 @system_container(require_auth='login')
  def ai_dashboard_overview():
      return ai_dashboard_api.success({'total': 100})

  @ai_dashboard_api.route('/api/ai/users/<int:user_id>', methods=['DELETE'])
@system_container(require_auth='admin')
  @ai_dashboard_api.require_super_admin()
  def delete_user(user_id):
      return ai_dashboard_api.success(None, msg='用户已删除')

兼容: 现有 Blueprint(name, __name__) 不强制改造, 渐进式迁移
"""
import os, sys, json, sqlite3, traceback
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from app.middlewares.system_container import system_container

from app.middlewares.system_container import (
    system_container, PERM_GUEST, PERM_LOGIN, PERM_ADMIN, PERM_SUPER_ADMIN,
    _audit_log
)
from app.utils.mtscos_response import (
    build_success_response, build_error_response, build_paginated_response,
    _lookup_exception_code, _gen_trace_id
)

PROJECT_ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
APP_DB = os.path.join(PROJECT_ROOT, "flask-app/ai_engines/app.db")


def _log_blueprint_failure(blueprint_name, import_path, error_message, stack_trace,
                            severity="error", is_fault_tolerant=1, flow_id=None):
    """蓝图失败日志落库 mt_blueprint_fail_log (模块4 P1-C)
    is_fault_tolerant=1 表示容错(不影响整体注册), 0=致命
    """
    try:
        conn = sqlite3.connect(APP_DB, timeout=2)
        c = conn.cursor()
        c.execute("""INSERT INTO mt_blueprint_fail_log
            (blueprint_name, import_path, error_message, stack_trace,
             severity, is_fault_tolerant, retry_count, last_retry_at, created_at)
            VALUES(?,?,?,?,?,?,0,?,?)""",
            (blueprint_name, import_path, str(error_message)[:2000], stack_trace[:8000],
             severity, 1 if is_fault_tolerant else 0,
             datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[MTSCOSBlueprint.fail_log WARN] {e}", file=sys.stderr)


class MTSCOSBlueprint(Blueprint):
    """
    MTSCOS 统一蓝图基类(继承 Flask Blueprint)
    内置: 权限装饰器 / 统一响应 / 错误处理 / 容错注册 / 业务域隔离
    """
    # 业务域白名单(对齐B轮B3决议: 5个业务域独立蓝图)
    BUSINESS_DOMAINS = ("auth", "admin", "student", "mobile", "ai", "system", "common")

    def __init__(self, name, import_name, business_domain="common",
                 require_auth=None, url_prefix=None, subdomain=None,
                 url_defaults=None, template_folder=None, static_folder=None,
                 flow_id=None, **kwargs):
        """
        参数:
          name            - Blueprint名称
          import_name     - 通常 __name__
          business_domain - 业务域(auth/admin/student/mobile/ai/system/common)
          require_auth    - 蓝图级默认权限要求(可选, 路由级装饰器可覆盖)
          flow_id         - §14流程ID(关联审计日志)
          其他参数同 Flask Blueprint
        """
        if business_domain not in self.BUSINESS_DOMAINS:
            raise ValueError(f"business_domain 必须 {self.BUSINESS_DOMAINS}, 实际={business_domain}")

        super().__init__(name, import_name, url_prefix=url_prefix, subdomain=subdomain,
                         url_defaults=url_defaults, template_folder=template_folder,
                         static_folder=static_folder, **kwargs)

        self.business_domain = business_domain
        self.default_require_auth = require_auth
        self.flow_id = flow_id

        # 注册 8 类异常错误处理器(对齐模块4 P1-A 异常码字典)
        self._register_errorhandlers()

    def _register_errorhandlers(self):
        """注册蓝图级错误处理器(对齐异常码字典20条)"""
        @self.errorhandler(401)
        def _h401(e):
            return build_error_response("E_AUTH_401", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(403)
        def _h403(e):
            return build_error_response("E_AUTH_403", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(404)
        def _h404(e):
            return build_error_response("E_ROUTE_404", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(429)
        def _h429(e):
            return build_error_response("E_RATE_LIMIT", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(500)
        def _h500(e):
            return build_error_response("E_SRV_500", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(503)
        def _h503(e):
            return build_error_response("E_MAINTENANCE", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(504)
        def _h504(e):
            return build_error_response("E_SRV_504", route_path=request.path,
                                         blueprint=self.name)

        @self.errorhandler(Exception)
        def _hExc(e):
            # 未捕获异常兜底, 落库蓝图失败日志
            _log_blueprint_failure(self.name, self.import_name,
                                   f"Unhandled Exception: {e}",
                                   traceback.format_exc(),
                                   severity="error", is_fault_tolerant=1,
                                   flow_id=self.flow_id)
            return build_error_response("E_SRV_500", route_path=request.path,
                                         blueprint=self.name)

    # -------- 权限装饰器便捷方法(等价 @system_container) --------
    def allow_guest(self, **kw):
        """访客可访问(等价 @system_container(require_auth='guest'))"""
        kw.setdefault("flow_id", self.flow_id)
        return system_container(require_auth=PERM_GUEST, **kw)

    def require_login(self, **kw):
        """登录用户(等价 @system_container(require_auth='login'))"""
        kw.setdefault("flow_id", self.flow_id)
        return system_container(require_auth=PERM_LOGIN, **kw)

    def require_admin(self, **kw):
        """管理员(等价 @system_container(require_auth='admin'))"""
        kw.setdefault("flow_id", self.flow_id)
        return system_container(require_auth=PERM_ADMIN, **kw)

    def require_super_admin(self, **kw):
        """超级管理员(等价 @system_container(require_auth='super_admin')+VIKEY)"""
        kw.setdefault("flow_id", self.flow_id)
        return system_container(require_auth=PERM_SUPER_ADMIN, **kw)

    def require_role(self, allowed_roles, require_auth=PERM_LOGIN, **kw):
        """指定角色白名单(等价 @system_container(allowed_roles=[...]))"""
        kw.setdefault("flow_id", self.flow_id)
        return system_container(require_auth=require_auth,
                                allowed_roles=allowed_roles, **kw)

    # -------- 统一响应便捷方法(等价 build_*_response) --------
    def success(self, data=None, msg="操作成功", trace_id=None, **kw):
        """成功响应快捷方法"""
        return build_success_response(data, msg, trace_id, **kw)

    def error(self, exc_code, msg=None, trace_id=None, **kw):
        """错误响应快捷方法(对照异常码字典)"""
        return build_error_response(exc_code, msg, trace_id,
                                     route_path=request.path,
                                     blueprint=self.name, **kw)

    def paginated(self, items, total, page=1, per_page=20, msg="查询成功", **kw):
        """分页响应快捷方法"""
        return build_paginated_response(items, total, page, per_page, msg, **kw)

    # -------- 容错注册(对齐B轮B3单蓝图失败不影响整体) --------
    def register_to(self, app):
        """容错注册到 Flask app
        单蓝图注册失败不影响其他蓝图(对齐B轮B3 + 开发规则 §3.1 容错注册)
        失败时落库 mt_blueprint_fail_log (模块4 P1-C)
        """
        try:
            app.register_blueprint(self)
            return True, None
        except Exception as e:
            stack = traceback.format_exc()
            _log_blueprint_failure(self.name, self.import_name, str(e), stack,
                                   severity="error", is_fault_tolerant=1,
                                   flow_id=self.flow_id)
            return False, str(e)


def register_mtscos_blueprints(app, blueprint_specs, flow_id=None):
    """批量容错注册蓝图(对齐开发规则 §3.1 + B轮B3 业务域隔离)
    blueprint_specs: List[Tuple[module_path, blueprint_attr_name, business_domain]]
    返回: {registered: int, failed: int, failed_list: []}
    """
    registered = 0
    failed = 0
    failed_list = []
    for module_path, bp_attr, domain in blueprint_specs:
        try:
            module = __import__(module_path, fromlist=[bp_attr])
            bp = getattr(module, bp_attr)
            # 兼容: 如果是MTSCOSBlueprint则用容错注册, 否则用普通注册
            if isinstance(bp, MTSCOSBlueprint):
                ok, err = bp.register_to(app)
                if ok:
                    registered += 1
                else:
                    failed += 1
                    failed_list.append((bp_attr, err))
            else:
                # 普通Blueprint保持兼容注册
                app.register_blueprint(bp)
                registered += 1
        except Exception as e:
            failed += 1
            failed_list.append((bp_attr, str(e)[:200]))
            _log_blueprint_failure(bp_attr, module_path, str(e),
                                   traceback.format_exc(),
                                   severity="warning", is_fault_tolerant=1,
                                   flow_id=flow_id)
    return {"registered": registered, "failed": failed, "failed_list": failed_list}


if __name__ == "__main__":
    # 模块自检
    print(f"MTSCOSBlueprint 业务域: {MTSCOSBlueprint.BUSINESS_DOMAINS}")
    print(f"4级权限: guest/login/admin/super_admin")
    print(f"8类异常错误处理器: 401/403/404/429/500/503/504/Exception")
    print(f"容错注册方法: MTSCOSBlueprint.register_to(app)")
    print(f"批量容错注册函数: register_mtscos_blueprints(app, specs, flow_id)")
    print(f"统一响应方法: success/error/paginated")
    print(f"权限装饰器方法: allow_guest/require_login/require_admin/require_super_admin/require_role")
    print("OK MTSCOSBlueprint 基类就绪(待Flask app上下文激活)")
