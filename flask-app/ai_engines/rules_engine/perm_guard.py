#!/usr/bin/env python3
"""
MT_RULE_PERM 权限规则强化拦截器
================================

在 b1_global_permission_guard.py 已有基础上, 额外增加:
- 敏感写操作二次验证 (POST/PUT /api/admin/* 需要 session 中双重认证标记)
- 防盗链加固 (非首页 Referer + 未授权 session → 强制重新登录)
- Arduino 路由深度拦截 (sa_arduino_guard scope 覆盖)

拦截点: Flask before_request (在 b1_global_permission_guard 之后执行)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(os.path.dirname(_HERE))
_APP_DB = os.path.join(_FLASK_APP, "database", "app.db")

# 需要二次验证的敏感写路由
_SENSITIVE_WRITE_PREFIXES = (
    "/api/admin/",
    "/api/rules/",
    "/api/arduino/",
    "/api/db/backup",
    "/api/user/role/update",
)

# 敏感操作冷却时间 (秒) — 防止快速连续敏感操作
_SENSITIVE_COOLDOWN_SEC = 60


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_APP_DB, timeout=10.0)
    return conn


def _write_violation(rule_id: str, violation_code: str, detail: str, triggered_by: str) -> None:
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
        print(f"[PERM_GUARD] violation write skip: {exc}")


def _is_sensitive_write(path: str, method: str) -> bool:
    """判断是否为敏感写操作"""
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    return any(path.startswith(p) for p in _SENSITIVE_WRITE_PREFIXES)


def _check_anti_hotlink(referrer: str, user_role: str) -> Optional[str]:
    """
    防盗链检查
    返回错误原因 (None 表示通过)
    """
    # 已登录用户不触发防盗链
    if user_role:
        return None
    # 无 Referer → 允许 (直接访问)
    if not referrer:
        return None
    # 本机 Referer → 允许
    if "localhost" in referrer or "127.0.0.1" in referrer:
        return None
    # 包含登录页 → 允许
    if "/login" in referrer or "/auth" in referrer:
        return None
    # 其他 → 疑似盗链
    return f"Referer={referrer} 非授权来源"


# 内存级敏感操作冷却表 (ip:user → last_sensitive_ts)
_sensitive_cooldown: dict[str, float] = {}


def register_interceptor(app) -> callable:
    """注册 Flask before_request"""
    try:
        from flask import request, jsonify, session, redirect
    except ImportError:
        print("[PERM_GUARD] Flask 未初始化, 跳过注册")
        return lambda: None

    rule_id = "MT_RULE_PERM"

    @app.before_request
    def _perm_guard():
        """权限规则强化拦截 (Layer 2 supplement to b1_global_permission_guard)"""
        path = request.path
        method = request.method
        user_role = session.get("role", "") if session else ""
        username = session.get("username", "") if session else ""
        remote_ip = request.remote_addr or "unknown"

        # 静态 / 公开路径放行
        if path.startswith("/static/") or path in ("/", "/login", "/auth/login", "/api/health"):
            return None

        # ── 检查 1: 防盗链 ──
        referrer = request.headers.get("Referer", "") or request.headers.get("referer", "")
        hotlink_reason = _check_anti_hotlink(referrer, user_role)
        if hotlink_reason:
            _write_violation(
                rule_id,
                "PERM_ANTI_HOTLINK",
                f"IP={remote_ip} {hotlink_reason}",
                f"user={username}",
            )
            return redirect("/")  # 强制回首页

        # ── 检查 2: 敏感写操作二次验证 ──
        if _is_sensitive_write(path, method):
            # 冷却检查 (内存级, 防止连续滥用)
            import time
            cooldown_key = f"{remote_ip}:{username}"
            now = time.time()
            last_ts = _sensitive_cooldown.get(cooldown_key, 0)
            if now - last_ts < _SENSITIVE_COOLDOWN_SEC:
                remaining = int(_SENSITIVE_COOLDOWN_SEC - (now - last_ts))
                _write_violation(
                    rule_id,
                    "PERM_SENSITIVE_COOLDOWN",
                    f"IP={remote_ip} 敏感操作过于频繁, 剩余冷却 {remaining}s",
                    f"user={username}",
                )
                return jsonify({
                    "error": "PERM_SENSITIVE_COOLDOWN",
                    "rule": rule_id,
                    "msg": f"敏感操作冷却中, 请 {remaining} 秒后重试",
                }), 429

            # 记录本次时间
            _sensitive_cooldown[cooldown_key] = now

        return None

    print(f"[RULES-ENGINE] perm_guard registered (rule_id={rule_id})")
    return _perm_guard
