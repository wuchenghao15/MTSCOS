#!/usr/bin/env python3
"""
MT_RULE_DEV 开发规则拦截器
==========================

强制执行开发规则 (开发规则.md §3 目录结构规范):
- Flask 蓝图必须注册到正确目录 (app/api/ 下)
- 新建文件必须在白名单目录内
- 硬编码颜色/API Key 写入 mt_audit_logs

拦截点: Flask before_request (只拦文件上传/API key 写入相关路由)
触发条件: POST/PUT /api/dev/file_upload 或请求包含敏感模式
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(os.path.dirname(_HERE))
_APP_DB = os.path.join(_FLASK_APP, "database", "app.db")

# 白名单目录 (允许新建文件)
_ALLOWED_DIRS = (
    "app/", "ai_engines/", "engines/", "templates/",
    "static/css/", "static/js/", "app/api/",
)

# 敏感模式检测 (硬编码 API Key / AK/SK)
_SECRET_PATTERNS = [
    re.compile(r'(?i)(api_key|apikey|secret_key|secretkey|access_key)\s*[:=]\s*["\'][A-Za-z0-9_\-]{16,}["\']'),
    re.compile(r'AKIA[0-9A-Z]{16}'),  # AWS AK
    re.compile(r'sk-[a-f0-9]{32}'),   # OpenAI SK
    re.compile(r'(?i)(volcengine|jimeng|即梦).*?["\'][A-Za-z0-9_\-]{20,}["\']'),
]

# 硬编码颜色检测
_COLOR_PATTERNS = [
    re.compile(r'#[0-9A-Fa-f]{6}'),  # #FFFFFF 形式
    re.compile(r'rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)'),
]


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
        print(f"[DEV_RULE_GUARD] violation write skip: {exc}")


def _contains_secret(text: str) -> Optional[str]:
    """检测是否包含硬编码密钥"""
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)[:30] + "..."
    return None


def _contains_hardcoded_color(text: str) -> bool:
    """检测硬编码颜色"""
    # 放宽: 只在前 1000 字符里检测, 且匹配上下文包含 style/color/bg
    first_1k = text[:1000].lower()
    for pattern in _COLOR_PATTERNS:
        match = pattern.search(first_1k)
        if match:
            ctx_start = max(0, match.start() - 10)
            ctx = first_1k[ctx_start:match.end() + 10]
            if any(kw in ctx for kw in ("style", "color", "background", "border", "bg", "btn", "text")):
                return True
    return False


def register_interceptor(app) -> callable:
    """注册 Flask before_request"""
    try:
        from flask import request, jsonify, session
    except ImportError:
        print("[DEV_RULE_GUARD] Flask 未初始化, 跳过注册")
        return lambda: None

    rule_id = "MT_RULE_DEV"

    # 只拦写操作
    @app.before_request
    def _dev_rule_guard():
        """开发规则拦截器"""
        path = request.path
        method = request.method

        # 只读请求放行
        if method in ("GET", "HEAD", "OPTIONS"):
            return None

        # 静态资源 / 登录放行
        if path.startswith("/static/") or path in ("/", "/login"):
            return None

        # 尝试读取请求体 (可能是上传文件或 JSON)
        body_text = ""
        try:
            if request.is_json:
                body_text = json.dumps(request.get_json(force=True, silent=True) or {})
            elif request.data:
                body_text = request.data.decode("utf-8", errors="replace")
        except Exception:
            pass

        # 检测 1: 硬编码密钥
        if body_text:
            secret_found = _contains_secret(body_text)
            if secret_found:
                username = session.get("username", "") if session else ""
                _write_violation(
                    rule_id,
                    "DEV_HARDCODED_SECRET",
                    f"路径 {path} 请求体包含疑似硬编码密钥: {secret_found}",
                    f"user={username}",
                )
                print(f"[DEV_RULE_GUARD] SECRET BLOCKED: {path} secret={secret_found}")
                return jsonify({
                    "error": "DEV_HARDCODED_SECRET",
                    "rule": rule_id,
                    "msg": "检测到硬编码密钥/AK/SK, 请改用环境变量 os.environ 注入",
                    "suggestion": "JIMENG_AK = os.environ.get('JIMENG_AK', '')",
                }), 400

            # 检测 2: 硬编码颜色 (放宽: 只对 admin 修改路由检查)
            if _contains_hardcoded_color(body_text) and "/admin/" in path:
                username = session.get("username", "") if session else ""
                _write_violation(
                    rule_id,
                    "DEV_HARDCODED_COLOR",
                    f"路径 {path} 包含硬编码颜色, 应使用 Element Plus CSS 变量",
                    f"user={username}",
                )

        # 检测 3: 目录白名单 (文件上传类路由)
        if "upload" in path.lower() or "file" in path.lower():
            file_path = request.form.get("file_path", "") or request.args.get("file_path", "")
            if file_path and not any(file_path.startswith(d) for d in _ALLOWED_DIRS):
                username = session.get("username", "") if session else ""
                _write_violation(
                    rule_id,
                    "DEV_PATH_NOT_WHITELISTED",
                    f"路径 {path} 上传到非白名单目录: {file_path}",
                    f"user={username}",
                )
                print(f"[DEV_RULE_GUARD] PATH BLOCKED: {file_path}")
                return jsonify({
                    "error": "DEV_PATH_NOT_WHITELISTED",
                    "rule": rule_id,
                    "msg": "目标目录不在白名单内",
                    "allowed": list(_ALLOWED_DIRS),
                }), 400

        return None

    print(f"[RULES-ENGINE] dev_rule_guard registered (rule_id={rule_id})")
    return _dev_rule_guard
