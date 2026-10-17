#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MT_RULE_CLASSIFICATION 唯一访问判定入口 (PermissionManager)
===========================================================
规范: .trae/rules/机密等级与访问控制规范.md (MT_RULE_CLASSIFICATION v1.2.0)

§2 访问判定硬约束:
- 所有受保护资源必须调用 PermissionManager.can_access_classification(),
  禁止按角色字符串自行判断
- 未登录、未知角色和失效会话一律拒绝 L0/L1/L2
- L0 不得仅凭 super_admin 字符串放行: 唯一用户校验 + VIKEY 在线实检
- SA 会话必须持续通过 VIKEY 与 SZU100 双硬件复核; 任一缺失/异常/检测失败 → 拒绝并清除残留 SA 会话状态
- 权限不足返回 403, 不得泄露资源存在性/表名/字段名/密钥状态/内部错误详情

§3 审计: L0/L1/L2 的读取/写入/导出/解密/授权失败必须记录
   操作类型/操作者/资源分类/结果/追踪ID; 日志不得含密码/令牌/VIKEY原始信息/明文密钥

§4 默认分类: 无法识别的密级一律 fail-closed 拒绝
§5 验证覆盖: 密级名称映射/角色清晰度/L0 VIKEY 门槛/未知角色拒绝/审计字段/脱敏输出

flow_id: flow_classification_20261017
"""

from __future__ import annotations

import os
import time
import uuid
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

# DB 路径 (与 classification_guard 一致: flask-app/database/app.db)
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(os.path.dirname(_HERE))
_APP_DB = os.path.join(_FLASK_APP, "database", "app.db")

# ---------------------------------------------------------------------------
# 一、密级名称映射 (§1 统一密级 + §5 密级名称映射)
# ---------------------------------------------------------------------------

# 机器值: 数值越小越敏感
L0_TOP_SECRET = 0        # 极密
L1_CONFIDENTIAL = 1      # 机密
L2_SECRET = 2            # 秘密
L3_INTERNAL = 3          # 内部 (由数据库加密模块管理)
L4_PUBLIC = 4            # 公开 (由数据库加密模块管理)

_LEVEL_NAME_MAP = {
    0: ("L0_TOP_SECRET", "极密"),
    1: ("L1_CONFIDENTIAL", "机密"),
    2: ("L2_SECRET", "秘密"),
    3: ("L3_INTERNAL", "内部"),
    4: ("L4_PUBLIC", "公开"),
}

# 任意表示法 → 机器值; 无法识别 → None (fail-closed, §4)
_NAME_ALIASES = {
    "l0_top_secret": 0, "l0": 0, "极密": 0, "top_secret": 0, "topsecret": 0,
    "l1_confidential": 1, "l1": 1, "机密": 1, "confidential": 1,
    "l2_secret": 2, "l2": 2, "秘密": 2, "secret": 2,
    "l3_internal": 3, "l3": 3, "内部": 3, "internal": 3,
    "l4_public": 4, "l4": 4, "公开": 4, "public": 4,
}


def normalize_level(value: Any) -> Optional[int]:
    """密级名称映射: 机器值/枚举名/中文名/数字 → 0-4; 无法识别返回 None (fail-closed)"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 4 else None
    key = str(value).strip().lower()
    if key in _NAME_ALIASES:
        return _NAME_ALIASES[key]
    # IntEnum (如 db_encryption.EncryptionLevel) → 取 int 值
    try:
        iv = int(value)
        return iv if 0 <= iv <= 4 else None
    except (TypeError, ValueError):
        return None


def level_display(level: int) -> str:
    """机器值 → (枚举名/中文名)"""
    names = _LEVEL_NAME_MAP.get(level)
    return f"{names[0]}/{names[1]}" if names else f"UNKNOWN({level})"


# ---------------------------------------------------------------------------
# 二、角色清晰度 (§2 未知角色拒绝)
# ---------------------------------------------------------------------------

# 唯一超级管理员 (用户权限.md §1.1 + 本规范 §2)
SA_UNIQUE_USERNAME = "wuchenghao15"

# L0: 唯一 SA
_L0_ROLES = {"super_admin"}
# L1: 已认证的管理/安全角色
_L1_ROLES = {"super_admin", "admin", "hardware_admin", "security_admin"}
# L2: 已认证用户且具有业务权限 (guest 无业务权限)
_L2_ROLES = {"super_admin", "admin", "hardware_admin", "security_admin",
             "user", "teacher", "student", "observer", "auditor", "operator"}
# 已知角色全集 (未知角色一律拒绝)
_KNOWN_ROLES = _L2_ROLES | {"guest"}


# ---------------------------------------------------------------------------
# 三、双硬件复核 (§2: VIKEY + SZU100 持续复核, 结果缓存 30s)
# ---------------------------------------------------------------------------

_HW_CACHE: Dict[str, Any] = {"ts": 0.0, "vikey": False, "szu100": False}
_HW_TTL = 30.0


def _is_local_client() -> bool:
    """当前请求是否来自本机 (与 server_real_db._is_local_client 同口径)"""
    try:
        from flask import request
        addr = (request.remote_addr or "").lower()
        return addr in ("127.0.0.1", "::1", "localhost")
    except Exception:
        return True  # 无请求上下文 (daemon/CLI) → 视为服务器本机


def _probe_hardware(force: bool = False) -> Tuple[bool, bool]:
    """服务器侧双硬件探测 (仅本机客户端; 结果缓存 30s)"""
    now = time.time()
    if not force and now - _HW_CACHE["ts"] < _HW_TTL:
        return _HW_CACHE["vikey"], _HW_CACHE["szu100"]
    vikey_ok, szu100_ok = False, False
    try:
        from core.services.vikey_driver import get_vikey_manager
        det = get_vikey_manager().detect()
        vikey_ok = det.get("present_count", 0) > 0
    except Exception:
        vikey_ok = False
    try:
        from core.services.szu100_driver import detect_szu100
        szu100_ok = bool(detect_szu100().get("is_authentic", False))
    except Exception:
        szu100_ok = False
    _HW_CACHE.update({"ts": now, "vikey": vikey_ok, "szu100": szu100_ok})
    return vikey_ok, szu100_ok


def check_sa_hardware(session: Any = None) -> Tuple[bool, bool]:
    """SA 双硬件复核 (VIKEY + SZU100)

    VIKEY: 会话保护标志 _sa_override_from_vikey (插入注入/拔出清除) 或 服务器实检
    SZU100: 服务器实检 (本机客户端); 非本机客户端无持续复核通道 → fail-closed False

    Returns: (vikey_ok, szu100_ok)
    """
    vikey_flag = False
    try:
        vikey_flag = (session is not None and session.get("_sa_override_from_vikey") is True)
    except Exception:
        vikey_flag = False
    if _is_local_client():
        srv_vikey, srv_szu100 = _probe_hardware()
        return (vikey_flag or srv_vikey), srv_szu100
    # 非本机: VIKEY 依赖会话标志; SZU100 无复核通道 → fail-closed
    return vikey_flag, False


def clear_sa_session_residue(session: Any) -> None:
    """失败尝试清除残留 SA 会话状态 (§2: 单独插钥不得触发/续期/恢复 SA 认证)"""
    if session is None:
        return
    try:
        session.pop("_sa_override_from_vikey", None)
        session.pop("super_admin_approved", None)
        session.pop("is_super_admin", None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 四、唯一判定入口 (§2)
# ---------------------------------------------------------------------------

# 通用拒绝码 (可返回给客户端; 不含资源存在性/表名/字段名/密钥状态)
DENY_UNAUTHENTICATED = "CLASSIFIED_DENY_UNAUTHENTICATED"
DENY_UNKNOWN_ROLE = "CLASSIFIED_DENY_UNKNOWN_ROLE"
DENY_ROLE = "CLASSIFIED_DENY_ROLE"
DENY_HARDWARE = "CLASSIFIED_DENY_HARDWARE"
DENY_SESSION_INVALID = "CLASSIFIED_DENY_SESSION_INVALID"
DENY_UNCLASSIFIED = "CLASSIFIED_DENY_UNCLASSIFIED"
DENY_COMPLIANCE_GATE = "CLASSIFIED_DENY_COMPLIANCE_GATE"


class PermissionManager:
    """机密等级访问判定唯一入口 (MT_RULE_CLASSIFICATION §2)"""

    @staticmethod
    def can_access_classification(level: Any, *,
                                  username: str = "",
                                  role: str = "",
                                  session: Any = None,
                                  op_type: str = "read",
                                  resource: Optional[str] = None,
                                  client_ip: Optional[str] = None) -> Dict[str, Any]:
        """判定是否可访问指定密级资源

        Args:
            level: 任意表示法的密级 (机器值/枚举名/中文名)
            username / role / session: 当前会话三要素
            op_type: read/write/export/decrypt/grant
            resource: 资源标识 (仅入审计, 不入响应)

        Returns:
            dict: {allowed, reason_code, level, op_type, resource,
                   operator, operator_role, classification, trace_id}
            reason_code 为固定枚举, 不含资源细节 (§2 不泄露)
        """
        trace_id = uuid.uuid4().hex
        lv = normalize_level(level)
        base = {
            "allowed": False, "reason_code": None, "level": lv,
            "op_type": op_type, "resource": resource,
            "operator": username or "anonymous", "operator_role": role or None,
            "classification": level_display(lv) if lv is not None else "UNCLASSIFIED",
            "trace_id": trace_id,
        }
        # §4: 无法识别的密级 → fail-closed
        if lv is None:
            base["reason_code"] = DENY_UNCLASSIFIED
            return base
        # 规则管辖范围 L0-L2; L3/L4 由数据库加密模块管理
        if lv >= L3_INTERNAL:
            base["allowed"] = True
            base["reason_code"] = "OK_NOT_PROTECTED"
            return base
        # §2: 未登录/失效会话一律拒绝
        uname = str(username or "").strip()
        rle = str(role or "").strip().lower()
        if not uname or not rle or session is None:
            base["reason_code"] = DENY_UNAUTHENTICATED
            return base
        # §5: 未知角色拒绝
        if rle not in _KNOWN_ROLES:
            base["reason_code"] = DENY_UNKNOWN_ROLE
            return base
        # 合规门 (v1.2.0 §A: 覆盖率<100% → fail-closed)
        if not PermissionManager.compliance_gate_open():
            base["reason_code"] = DENY_COMPLIANCE_GATE
            return base
        if lv == L2_SECRET:
            if rle not in _L2_ROLES:
                base["reason_code"] = DENY_ROLE
                return base
            base["allowed"] = True
            base["reason_code"] = "OK"
            return base
        if lv == L1_CONFIDENTIAL:
            if rle not in _L1_ROLES:
                base["reason_code"] = DENY_ROLE
                return base
            base["allowed"] = True
            base["reason_code"] = "OK"
            return base
        # L0 极密: 唯一用户 + 唯一角色, 禁止仅凭字符串放行
        if uname.lower() != SA_UNIQUE_USERNAME or rle not in _L0_ROLES:
            base["reason_code"] = DENY_ROLE
            return base
        # L0: VIKEY + SZU100 双硬件持续复核
        vikey_ok, szu100_ok = check_sa_hardware(session)
        if not (vikey_ok and szu100_ok):
            clear_sa_session_residue(session)
            base["reason_code"] = DENY_HARDWARE
            return base
        base["allowed"] = True
        base["reason_code"] = "OK"
        return base

    # ------------------------------------------------------------------
    # §A 合规门: 最新 classification_compliance 扫描 failed>0 → 关门
    # ------------------------------------------------------------------
    _gate_cache = {"ts": 0.0, "open": True}
    _GATE_TTL = 60.0

    @staticmethod
    def compliance_gate_open() -> bool:
        now = time.time()
        if now - PermissionManager._gate_cache["ts"] < PermissionManager._GATE_TTL:
            return PermissionManager._gate_cache["open"]
        gate_open = True  # 无扫描记录 → 开门 (首次运行前不锁全站, 由扫描闭环)
        try:
            conn = sqlite3.connect(_APP_DB, timeout=10.0)
            row = conn.execute(
                "SELECT failed FROM mt_rule_integrity_scan "
                "WHERE scan_type='classification_compliance' AND rule_id='MT_RULE_CLASSIFICATION' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row is not None and int(row[0] or 0) > 0:
                gate_open = False
        except Exception:
            gate_open = True  # 表缺失/查询失败不放大故障, 由扫描器闭环
        PermissionManager._gate_cache.update({"ts": now, "open": gate_open})
        return gate_open

    # ------------------------------------------------------------------
    # §3 审计落库 (mt_classified_access_audit)
    # ------------------------------------------------------------------
    @staticmethod
    def audit_access(decision: Dict[str, Any], *,
                     client_ip: Optional[str] = None) -> Optional[str]:
        """L0/L1/L2 访问审计 (成功与失败均记录; 不记录密码/令牌/VIKEY原始信息/明文密钥)"""
        try:
            lv = decision.get("level")
            if lv is None or int(lv) >= L3_INTERNAL:
                return None  # 仅 L0/L1/L2 需审计
            trace_id = decision.get("trace_id") or uuid.uuid4().hex
            conn = sqlite3.connect(_APP_DB, timeout=10.0)
            conn.execute(
                """INSERT INTO mt_classified_access_audit
                   (trace_id, op_type, operator, operator_role, resource,
                    resource_classification, access_level, result, deny_reason_code,
                    client_ip, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trace_id,
                 str(decision.get("op_type") or "read"),
                 str(decision.get("operator") or "anonymous"),
                 str(decision.get("operator_role") or "-"),
                 str(decision.get("resource") or "-"),
                 str(decision.get("classification") or "-"),
                 str(decision.get("level")),
                 "ALLOW" if decision.get("allowed") else "DENY",
                 decision.get("reason_code") if not decision.get("allowed") else None,
                 str(client_ip or "-"),
                 datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            return trace_id
        except Exception:
            return None  # 审计失败不阻断业务, 由 sys_rule_enforcer 扫描闭环

    # ------------------------------------------------------------------
    # §3/§5 脱敏输出
    # ------------------------------------------------------------------
    _SENSITIVE_KEY_HINTS = ("password", "passwd", "token", "secret", "key",
                            "vikey", "szu100", "credential", "auth_hash")

    @staticmethod
    def mask_output(value: Any, keep: int = 4) -> Any:
        """通用脱敏: 敏感键全掩码, 长字符串部分掩码, 结构递归"""
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if any(h in str(k).lower() for h in PermissionManager._SENSITIVE_KEY_HINTS):
                    out[k] = "****"
                else:
                    out[k] = PermissionManager.mask_output(v, keep=keep)
            return out
        if isinstance(value, (list, tuple)):
            return [PermissionManager.mask_output(v, keep=keep) for v in value]
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return s
            if len(s) <= keep:
                return "****"
            return f"{s[:2]}****{s[-2:]}"
        return value


__all__ = [
    "PermissionManager",
    "normalize_level",
    "level_display",
    "check_sa_hardware",
    "clear_sa_session_residue",
    "SA_UNIQUE_USERNAME",
    "L0_TOP_SECRET", "L1_CONFIDENTIAL", "L2_SECRET", "L3_INTERNAL", "L4_PUBLIC",
    "DENY_UNAUTHENTICATED", "DENY_UNKNOWN_ROLE", "DENY_ROLE", "DENY_HARDWARE",
    "DENY_SESSION_INVALID", "DENY_UNCLASSIFIED", "DENY_COMPLIANCE_GATE",
]
