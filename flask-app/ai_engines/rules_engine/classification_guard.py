#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MT_RULE_CLASSIFICATION 机密等级拦截器 (v1.2.0 §B before_request 强制层)
========================================================================
规范: .trae/rules/机密等级与访问控制规范.md (MT_RULE_CLASSIFICATION v1.2.0)

判定: 唯一入口 PermissionManager.can_access_classification() (perm_manager.py)
拦截: Flask before_request, 覆盖 v1.2.0 §B 四类路径 + 既有机密路由:
    /api/admin/*          → L0: SA 唯一用户 + VIKEY+SZU100 双硬件; 失败 403+销毁会话
    /api/auth/vikey       → VIKEY 状态完整性; 状态不一致/伪造 → 403 fail-closed + 清残留
    /api/user/container   → L1 用户容器权限; 失败 403+审计
    /api/db/export/*      → L2 导出审批; 失败 403+导出日志
    /api/classified/*     → 按 mt_classified_data 注册密级判定
    /api/sa/vikey/export  → L0 (极密)
    /api/sa/firmware/export → L0 (极密)
    /api/eigenflux/privkey → L1 (机密)
审计: L0/L1/L2 成功与失败均写 mt_classified_access_audit (§3)
违反: 写 mt_rule_violation_alert (rule_id=MT_RULE_CLASSIFICATION)
合规门: 最新 classification_compliance 扫描 failed>0 → fail-closed 全拒 (v1.2.0 §A)
403: 仅返回固定错误码, 不泄露资源存在性/表名/字段名/密钥状态 (§2)

flow_id: flow_classification_20261017
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

# 正确 DB 路径 (绕过 rule_db.py 的错误硬编码路径)
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(os.path.dirname(_HERE))
_APP_DB = os.path.join(_FLASK_APP, "database", "app.db")

from ai_engines.rules_engine.perm_manager import (
    PermissionManager,
    normalize_level,
    check_sa_hardware,
    clear_sa_session_residue,
    L0_TOP_SECRET,
    L1_CONFIDENTIAL,
    L2_SECRET,
)

RULE_ID = "MT_RULE_CLASSIFICATION"

# ---------------------------------------------------------------------------
# 路径 → 密级策略 (v1.2.0 §B + 既有注册路由)
# ---------------------------------------------------------------------------

# 拦截前缀 (命中即进入密级判定)
_CLASSIFIED_ROUTE_PREFIXES = (
    # v1.2.0 §B 强制四类
    "/api/admin/",
    "/api/auth/vikey",
    "/api/user/container",
    "/api/db/export/",
    # 既有受保护路由
    "/api/classified/",
    "/api/sa/vikey/export",      # VIKEY 配置导出 (极密)
    "/api/sa/firmware/export",   # SZU100 固件导出 (极密)
    "/api/eigenflux/privkey",    # EigenFlux 通信私钥 (机密)
)

# 前缀 → 默认密级
_PREFIX_LEVEL = {
    "/api/admin/": L0_TOP_SECRET,
    "/api/user/container": L1_CONFIDENTIAL,
    "/api/db/export/": L2_SECRET,
    "/api/classified/": None,          # 由注册表/路径段解析
    "/api/sa/vikey/export": L0_TOP_SECRET,
    "/api/sa/firmware/export": L0_TOP_SECRET,
    "/api/eigenflux/privkey": L1_CONFIDENTIAL,
}

# 公开路径白名单 (不拦截)
_PUBLIC_PATHS = {"/", "/login", "/auth/login", "/static/", "/api/health"}

# data_code 注册表缓存
_DATA_CODE_CACHE: dict = {"ts": 0.0, "rows": {}}
_CACHE_TTL = 60.0


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_APP_DB, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _load_registry() -> dict:
    """mt_classified_data 注册表 (data_code → classification), 缓存 60s"""
    now = time.time()
    if now - _DATA_CODE_CACHE["ts"] < _CACHE_TTL and _DATA_CODE_CACHE["rows"]:
        return _DATA_CODE_CACHE["rows"]
    rows = {}
    try:
        conn = _get_conn()
        for r in conn.execute("SELECT data_code, classification FROM mt_classified_data"):
            rows[str(r["data_code"])] = r["classification"]
        conn.close()
    except Exception:
        rows = {}
    if rows:
        _DATA_CODE_CACHE.update({"ts": now, "rows": rows})
    return rows


def _write_violation(rule_id: str, violation_code: str, detail: str, triggered_by: str) -> None:
    """写入违反告警 (使用真实 mt_rule_violation_alert 列结构; detail 已脱敏)"""
    try:
        import uuid
        conn = _get_conn()
        alert_id = f"{rule_id}_{violation_code}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now_ts = time.time()
        # detail 仅使用固定枚举文案, 不含用户输入/密钥/令牌 (§3 日志不落敏感内容)
        payload = json.dumps({"detail": detail, "triggered_by": triggered_by}, ensure_ascii=False)
        conn.execute(
            """INSERT INTO mt_rule_violation_alert
                (alert_id, viol_id, alert_type, alert_target, alert_status, alert_payload,
                 alert_sent_at, created_at, violation_code, severity)
               VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, 'MEDIUM')""",
            (alert_id, rule_id, violation_code, str(detail)[:80], payload, now_ts, now_ts, violation_code),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[CLASSIFICATION_GUARD] violation write skip: {exc}")


def _resolve_data_code(path: str) -> str:
    """从路径解析 data_code (registered/classified 路由)"""
    if "/classified/" in path:
        return path.split("/classified/")[1].split("/")[0]
    if "vikey" in path and "export" in path:
        return "SA_VIKEY_SPEC"
    if "firmware" in path:
        return "SA_SZU100_SPEC"
    if "privkey" in path:
        return "EIGENFLUX_PRIV_KEY"
    return ""


def _check_classification_access(data_code: str, user_role: str, is_sa: bool, vikey_online: bool):
    """兼容包装: 委托 PermissionManager 唯一判定 (禁止绕过)"""
    registry = _load_registry()
    level = registry.get(data_code)
    if level is None:
        level = L0_TOP_SECRET  # 未知 data_code → 按最高敏感等级 fail-closed (§4)
    session = None
    username = ""
    try:
        from flask import session as _session
        session = _session
        username = _session.get("username", "") if _session else ""
    except Exception:
        pass
    # is_sa/vikey_online 参数仅为兼容签名; 判定一律以 PermissionManager 双硬件复核为准
    return PermissionManager.can_access_classification(
        level, username=username, role=user_role, session=session,
        op_type="read", resource=f"data_code={data_code}",
    )


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

    def _deny(resp_code: str, audit_decision: dict, client_ip: str,
              destroy_session: bool = False, violation_code: str = "CLASSIFIED_ACCESS_DENIED",
              detail: str = ""):
        """统一拒绝出口: 违反告警 + 审计 + (可选)销毁会话 + 无泄露 403"""
        _write_violation(RULE_ID, violation_code, detail or resp_code, f"path={request.path}, user={session.get('username', '') if session else ''}")
        PermissionManager.audit_access(audit_decision, client_ip=client_ip)
        if destroy_session:
            try:
                clear_sa_session_residue(session)
                session.clear()
            except Exception:
                pass
        return jsonify({"error": "CLASSIFIED_ACCESS_DENIED", "code": resp_code}), 403

    @app.before_request
    def _classification_guard():
        """机密等级访问控制拦截 (MT_RULE_CLASSIFICATION v1.2.0 §B)"""
        path = request.path

        # 公开路径放行
        if path in _PUBLIC_PATHS or path.startswith("/static/"):
            return None

        is_classified_route = any(path.startswith(p) for p in _CLASSIFIED_ROUTE_PREFIXES)
        explicit_request = request.headers.get("X-Classification-Request", "") == "1"
        if not (is_classified_route or explicit_request):
            return None

        username = (session.get("username", "") or "") if session else ""
        user_role = (session.get("role", "") or "") if session else ""
        client_ip = request.remote_addr or ""
        op_type = {"GET": "read", "POST": "write", "PUT": "write",
                   "PATCH": "write", "DELETE": "write"}.get(request.method, "read")

        # --- 特例: /api/auth/vikey VIKEY 状态完整性 (不强制登录 GET 轮询, 保登录页可用) ---
        if path.startswith("/api/auth/vikey"):
            sa_flag = (session.get("_sa_override_from_vikey") is True) if session else False
            if sa_flag and (not username or not user_role):
                # 会话声称 VIKEY SA 覆盖但无身份 → 状态不完整, fail-closed 清残留
                decision = PermissionManager.can_access_classification(
                    L0_TOP_SECRET, username=username, role=user_role, session=session,
                    op_type=op_type, resource="vikey_state_integrity")
                decision.update({"trace_id": decision.get("trace_id"), "level": L0_TOP_SECRET,
                                 "resource": "vikey_state_integrity"})
                return _deny("CLASSIFIED_DENY_SESSION_INVALID", decision, client_ip,
                             destroy_session=True, violation_code="VIKEY_STATE_INTEGRITY",
                             detail="session sa_override without identity")
            if request.method in ("POST", "PUT", "PATCH") and not username:
                decision = {"allowed": False, "reason_code": "CLASSIFIED_DENY_UNAUTHENTICATED",
                            "level": L0_TOP_SECRET, "op_type": "write",
                            "resource": "vikey_verify", "operator": "anonymous",
                            "operator_role": None, "classification": "L0_TOP_SECRET/极密",
                            "trace_id": __import__("uuid").uuid4().hex}
                return _deny("CLASSIFIED_DENY_UNAUTHENTICATED", decision, client_ip,
                             violation_code="VIKEY_VERIFY_NO_LOGIN",
                             detail="unauthenticated vikey verify attempt")
            return None

        # --- 解析密级 ---
        data_code = request.args.get("data_code", "") or request.headers.get("X-Data-Code", "")
        level = None
        resource = path
        if data_code:
            registry = _load_registry()
            level = registry.get(data_code)
            resource = f"data_code={data_code}"
            if level is None:
                level = L0_TOP_SECRET  # 未注册 data_code → 最高敏感等级 (§4 fail-closed)
        else:
            for prefix, lv in _PREFIX_LEVEL.items():
                if path.startswith(prefix):
                    level = lv
                    break
            if level is None and "/classified/" in path:
                code = _resolve_data_code(path)
                level = _load_registry().get(code, L0_TOP_SECRET)
                resource = f"data_code={code}"
            if level is None:
                level = L0_TOP_SECRET  # 显式机密请求头但无密级 → fail-closed

        # --- 唯一判定入口 (§2) ---
        decision = PermissionManager.can_access_classification(
            level, username=username, role=user_role, session=session,
            op_type=op_type, resource=resource, client_ip=client_ip)

        if decision.get("allowed"):
            PermissionManager.audit_access(decision, client_ip=client_ip)
            return None

        # --- 拒绝: /api/admin/* L0 失败 → 403 + 销毁会话 (§B 表) ---
        destroy = path.startswith("/api/admin/")
        return _deny(decision.get("reason_code") or "CLASSIFIED_DENY_ROLE", decision, client_ip,
                     destroy_session=destroy)

    print(f"[RULES-ENGINE] classification_guard registered (rule_id={RULE_ID}, "
          f"paths={len(_CLASSIFIED_ROUTE_PREFIXES)}, perm_manager=ON)")
    return _classification_guard
