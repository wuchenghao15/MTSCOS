#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 统一响应 + 异常码字典查询工具
======================================================
§14 IRON_RULE · STEP_7_EXECUTE · 模块1 后端Blueprint P1
flow_id: flow_dev_pages_functions_complete_20260818_001

统一JSON响应格式(对齐开发规则 §21 API契约):
  {
    "code": 0/非0,           # 0=成功, 非0=业务错误码(对照mt_exception_code_dict)
    "msg": "中文说明",       # 用户可读消息
    "data": {...} | null,    # 业务数据(失败时为null)
    "trace_id": "uuid16"     # 请求追踪ID(贯穿日志+审计+前端)
  }

异常码字典查询: 调用 mt_exception_code_dict (模块4 P1-A Seed 20条)
  - exception_code → (http_status, title_zh, severity, repair_suggestion, design_tokens)
  - 设计Token颜色映射, 前端按 severity 渲染对应主题
"""
import os, sqlite3, uuid
from datetime import datetime
from flask import jsonify

PROJECT_ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
APP_DB = os.path.join(PROJECT_ROOT, "flask-app/ai_engines/app.db")

# 默认异常码 fallback (当DB不可用时使用, 保证响应不中断)
_FALLBACK_EXC = {
    "E_AUTH_401":        (401, "未登录或登录已过期", "error",   "请重新登录", "danger:#F56C6C"),
    "E_AUTH_403":        (403, "权限不足，禁止访问", "critical","请联系管理员", "danger:#F56C6C"),
    "E_ROUTE_404":       (404, "页面/接口不存在",   "warning", "检查URL拼写", "warning:#E6A23C"),
    "E_SRV_500":         (500, "服务器内部错误",   "critical","查看日志",    "danger:#F56C6C"),
    "E_SRV_504":         (504, "网关超时",          "error",   "优化SQL",      "warning:#E6A23C"),
    "E_MAINTENANCE":     (503, "系统维护中",        "info",    "等待维护完成","info:#909399"),
    "E_TOKEN_BREACH":    (403, "CSRF Token校验失败","error",   "刷新页面",    "danger:#F56C6C"),
    "E_PERM_ILLEGAL":    (403, "VIKEY合法性校验失败","critical","插入VIKEY加密狗","danger:#F56C6C"),
    "E_RATE_LIMIT":      (429, "请求频率超限",      "warning", "稍后重试",    "warning:#E6A23C"),
    "E_DB_CONSTRAINT":   (500, "数据库约束失败",    "error",   "检查数据",    "danger:#F56C6C"),
}


def _gen_trace_id():
    """生成16位UUID请求追踪ID"""
    return str(uuid.uuid4()).replace("-", "")[:16]


def _lookup_exception_code(exc_code):
    """从 mt_exception_code_dict 查询异常码详情(失败回退到_FALLBACK_EXC)
    返回: (http_status, title_zh, severity, repair_suggestion, design_tokens)
    """
    try:
        conn = sqlite3.connect(APP_DB, timeout=2)
        c = conn.cursor()
        c.execute("""SELECT http_status, title_zh, severity, repair_suggestion, design_tokens
                     FROM mt_exception_code_dict WHERE exception_code=?""", (exc_code,))
        row = c.fetchone()
        conn.close()
        if row:
            return tuple(row)
    except Exception:
        pass
    # 回退
    return _FALLBACK_EXC.get(exc_code, (500, "未知异常", "error", "联系管理员", "danger:#F56C6C"))


def build_success_response(data=None, msg="操作成功", trace_id=None, extra=None):
    """统一成功响应构建器"""
    payload = {
        "code": 0,
        "msg": msg,
        "data": data,
        "trace_id": trace_id or _gen_trace_id(),
        "timestamp": datetime.now().isoformat(),
    }
    if extra:
        payload.update(extra)
    return jsonify(payload), 200


def build_error_response(exc_code, msg=None, trace_id=None, route_path=None,
                         blueprint=None, extra=None):
    """统一错误响应构建器(对照异常码字典)"""
    http_status, title_zh, severity, repair_suggestion, design_tokens = _lookup_exception_code(exc_code)
    payload = {
        "code": exc_code,
        "msg": msg or title_zh,
        "data": None,
        "trace_id": trace_id or _gen_trace_id(),
        "severity": severity,
        "repair_suggestion": repair_suggestion,
        "design_tokens": design_tokens,
        "route_path": route_path,
        "blueprint": blueprint,
        "timestamp": datetime.now().isoformat(),
    }
    if extra:
        payload.update(extra)
    return jsonify(payload), http_status


def build_paginated_response(items, total, page=1, per_page=20, msg="查询成功", trace_id=None):
    """分页响应构建器(对齐开发规则 §21 分页契约)"""
    return jsonify({
        "code": 0,
        "msg": msg,
        "data": {
            "items": items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        },
        "trace_id": trace_id or _gen_trace_id(),
        "timestamp": datetime.now().isoformat(),
    }), 200


if __name__ == "__main__":
    # 自检
    print(f"统一响应格式: code/msg/data/trace_id")
    print(f"异常码字典查询函数: {_lookup_exception_code.__name__}")
    print(f"成功响应构建器: {build_success_response.__name__}")
    print(f"错误响应构建器: {build_error_response.__name__}")
    print(f"分页响应构建器: {build_paginated_response.__name__}")
    # 查询异常码示例
    r = _lookup_exception_code("E_AUTH_401")
    print(f"E_AUTH_401 查询: {r}")
    print("OK mtscos_response 工具就绪")
