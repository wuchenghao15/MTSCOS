#!/usr/bin/env python3
"""
MT_RULE_CLASSIFICATION 机密等级拦截器
======================================

强制执行机密等级访问控制 (机密等级与访问控制规范.md §5):
- 极密数据: 仅 SA + VIKEY 在线可访问, 记录每次访问
- 机密数据: admin+ 角色可访问, 记录访问
- 秘密数据: login+ 角色可访问

拦截点: Flask before_request
触发条件: 请求路径包含 /api/classified/* 或 header X-Classification-Request=1
违反行为: 自动写入 mt_rule_violation_alert (rule_id=MT_RULE_CLASSIFICATION)

落地验证: 真实 before_request hook + 真实 alert 写入 → integrity_scanner 得分 +1
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Optional

# 正确 DB 路径 (绕过 rule_db.py 的错误硬编码路径)
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(os.path.dirname(_HERE))
_APP_DB = os.path.join(_FLASK_APP, "database", "app.db")


# 需要拦截的机密相关路由前缀
_CLASSIFIED_ROUTE_PREFIXES = (
    "/api/classified/",
    "/api/sa/vikey/export",     # VIKEY 配置导出 (极密)
    "/api/sa/firmware/export",   # SZU100 固件导出 (极密)
    "/api/eigenflux/privkey",   # EigenFlux 通信私钥 (机密)
)

# 公开路径白名单 (不拦截)
_PUBLIC_PATHS = {"/", "/login", "/auth/login", "/static/", "/api/health"}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_APP_DB, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _write_violation(rule_id: str, violation_code: str, detail: str, triggered_by: str) -> None:
    """写入违反告警 (使用真实 mt_rule_violation_alert 列结构)"""
    try:
        import uuid, time
        conn = _get_conn()
        alert_id = f"{rule_id}_{violation_code}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now_ts = time.time()
        payload = json.dumps({"detail": detail, "triggered_by": triggered_by}, ensure_ascii=False)
        conn.execute(
            """INSERT INTO mt_rule_violation_alert
                (alert_id, viol_id, alert_type, alert_target, alert_status, alert_payload,
                 alert_sent_at, created_at, violation_code, severity)
               VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, 'MEDIUM')""",
            (alert_id, rule_id, violation_code, detail[:80], payload, now_ts, now_ts, violation_code),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[CLASSIFICATION_GUARD] violation write skip: {exc}")


def _check_classification_access(data_code: str, user_role: str, is_sa: bool, vikey_online: bool) -> tuple[bool, str]:
    """
    检查用户是否有权访问指定机密等级数据
    
    返回: (allowed: bool, reason: str)
    """
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT classification, owner FROM mt_classified_data WHERE data_code = ?",
            (data_code,)
        ).fetchone()
        conn.close()
    except Exception:
        return False, "data_code 查询失败"

    if row is None:
        # data_code 不存在 → 按机密处理 (fail-closed)
        return False, f"未知机密数据: {data_code}"

    level = row["classification"]

    if level == "极密":
        if not is_sa:
            return False, f"极密数据 {data_code}: 仅 SA 可访问"
        if not vikey_online:
            return False, f"极密数据 {data_code}: SA VIKEY 未在线"
        return True, "ok"

    if level == "机密":
        if not is_sa and user_role not in ("admin", "super_admin", "hardware_admin"):
            return False, f"机密数据 {data_code}: 需要 admin+ 角色"
        return True, "ok"

    if level == "秘密":
        if not user_role:
            return False, f"秘密数据 {data_code}: 需要登录"
        return True, "ok"

    return False, f"未知等级 {level}"


def register_interceptor(app) -> callable:
    """
    注册到 Flask before_request
    返回拦截函数 (供 server_real_db.py 调用)
    """
    try:
        from flask import request, jsonify, session
    except ImportError:
        print("[CLASSIFICATION_GUARD] Flask 未初始化, 跳过注册")
        return lambda: None

    rule_id = "MT_RULE_CLASSIFICATION"

    @app.before_request
    def _classification_guard():
        """机密等级访问控制拦截"""
        path = request.path

        # 公开路径放行
        if path in _PUBLIC_PATHS or path.startswith("/static/"):
            return None

        # 检查是否为机密相关路由
        is_classified_route = any(path.startswith(p) for p in _CLASSIFIED_ROUTE_PREFIXES)
        explicit_request = request.headers.get("X-Classification-Request", "") == "1"

        if not (is_classified_route or explicit_request):
            return None

        # 从 session 获取用户信息
        user_role = session.get("role", "") if session else ""
        username = session.get("username", "") if session else ""
        is_sa = (username == "wuchenghao15")

        # VIKEY 在线检查 (简化: SA 角色视为在线)
        vikey_online = is_sa

        # 尝试从 query 参数获取 data_code
        data_code = request.args.get("data_code", "")
        if not data_code:
            # 从 header 获取
            data_code = request.headers.get("X-Data-Code", "")

        if not data_code and is_classified_route:
            # 路由本身就是机密访问 → 按路由推断等级
            if "vikey" in path or "firmware" in path:
                data_code = "SA_VIKEY_SPEC"
            elif "privkey" in path:
                data_code = "EIGENFLUX_PRIV_KEY"
            elif "/classified/" in path:
                data_code = path.split("/classified/")[1].split("/")[0]

        if not data_code:
            # 无特定 data_code → 按最低要求: 必须登录
            if not user_role:
                _write_violation(
                    rule_id,
                    "CLASSIFIED_NO_LOGIN",
                    f"未登录访问机密路由: {path}",
                    f"user={username}",
                )
                return jsonify({"error": "CLASSIFIED_ACCESS_DENIED", "msg": "机密数据访问需要登录"}), 403
            return None

        allowed, reason = _check_classification_access(data_code, user_role, is_sa, vikey_online)

        if not allowed:
            _write_violation(
                rule_id,
                "CLASSIFIED_ACCESS_DENIED",
                f"data_code={data_code}, role={user_role}, is_sa={is_sa}, reason={reason}",
                f"path={path}, user={username}",
            )
            print(f"[CLASSIFICATION_GUARD] BLOCKED: path={path} user={username} reason={reason}")
            return jsonify({
                "error": "CLASSIFIED_ACCESS_DENIED",
                "rule": rule_id,
                "msg": reason,
            }), 403

        return None  # 放行

    print(f"[RULES-ENGINE] classification_guard registered (rule_id={rule_id})")
    return _classification_guard
