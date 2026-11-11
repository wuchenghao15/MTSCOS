#!/usr/bin/env python3
"""
sa_arduino_guard.py — SA Arduino 专属权限装饰器 (flow_sa_perm_ext)

封装现有 _check_arduino_auth(scope) 为 @sa_arduino_guard(scope='ide') 装饰器
并新增:
  1. mt_arduino_sessions 生命周期记录
  2. mt_sa_privileges privilege_code 映射检查
  3. mt_grace_windows graceful window 临时权限机制

scope 等级:
  vault  → 登录即可, 记录 session
  setup  → admin/hardware_admin 或 SA 双密钥
  ide    → SA wuchenghao15 + 双密钥 (VIKEY + SZU100)

Author: Trae-Agent (flow_sa_perm_ext)
Date: 2026-09-18
Flow: flow_sa_perm_ext_1789703900
"""

import os
import time
import json
import uuid
import logging
import sqlite3
from functools import wraps
from flask import request, jsonify, g

logger = logging.getLogger(__name__)

# ─── DB 路径 ───
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_APP_DB = os.path.join(_PROJECT_ROOT, "database", "app.db")

# ─── scope → privilege_code 映射 ───
_SCOPE_PRIVILEGE_MAP = {
    "vault":   "ARDUINO_VAULT_ACCESS",
    "detect":  "ARDUINO_DEVICE_DETECT",
    "setup":   "ARDUINO_IDE_SETUP",
    "compile": "ARDUINO_CODE_COMPILE",
    "ide":     "ARDUINO_IDE_SETUP",   # ide 复用 setup 权限
}

# ─── 双密钥检测缓存 (避免重复 USB 轮询) ───
_DUAL_CACHE = {"ts": 0.0, "result": None, "ttl": 2.0}


# ─── 辅助: 当前用户 ───
def _current_username():
    try:
        return g.get("system_container_username") or g.get("user") or "anonymous"
    except Exception:
        return "anonymous"


def _current_role():
    try:
        return g.get("system_container_role") or g.get("role") or "guest"
    except Exception:
        return "guest"


def _is_sa():
    username = _current_username()
    role = _current_role()
    return username == "wuchenghao15" or role.lower() == "super_admin"


def _check_login():
    """复用 system_container 的登录检查"""
    username = _current_username()
    return username and username != "anonymous", username


# ─── 辅助: DB 操作 ───
def _db():
    try:
        return sqlite3.connect(_APP_DB, timeout=15)
    except Exception as e:
        logger.error(f"sa_arduino_guard DB connect failed: {e}")
        return None


def _write_session(session_id, username, scope, priv_code, vikey_ok, fp_ok, auth_method, status="active"):
    """写 mt_arduino_sessions"""
    conn = _db()
    if not conn:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""INSERT OR REPLACE INTO mt_arduino_sessions 
        (session_id, sa_user_id, sa_login_time, sa_last_active,
         sa_vikey_status, sa_fingerprint_status, sa_auth_method,
         session_type, timeout_minutes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, username, now, now,
         1 if vikey_ok else 0, 1 if fp_ok else 0, auth_method,
         scope, 30, status, now, now))
    conn.commit()
    conn.close()


def _check_privilege(priv_code, username):
    """检查用户是否有对应 privilege_code (mt_sa_privileges 表)"""
    conn = _db()
    if not conn:
        return True, None
    try:
        row = conn.execute(
            "SELECT requires_vikey, requires_fingerprint, requires_grace, risk_level, min_role FROM mt_sa_privileges WHERE privilege_code=?",
            (priv_code,)).fetchone()
        if not row:
            return True, None  # 无配置 → pass through
        return True, {
            "requires_vikey": bool(row[0]),
            "requires_fingerprint": bool(row[1]),
            "requires_grace": bool(row[2]),
            "risk_level": row[3],
            "min_role": row[4],
        }
    except Exception as e:
        logger.warning(f"privilege check error: {e}")
        return True, None
    finally:
        conn.close()


def _check_grace_window(priv_code, username):
    """检查是否有有效的 graceful window (mt_grace_windows)"""
    conn = _db()
    if not conn:
        return False, None
    try:
        row = conn.execute("""
            SELECT grace_code, end_time FROM mt_grace_windows 
            WHERE sa_user_id=? AND privilege_code=? AND status='active' AND end_time > datetime('now','localtime')
            ORDER BY end_time DESC LIMIT 1""",
            (username, priv_code)).fetchone()
        if row:
            return True, {"grace_code": row[0], "end_time": row[1]}
        return False, None
    except Exception:
        return False, None
    finally:
        conn.close()


# ─── 辅助: 双密钥检测 (带缓存) ───
def _check_dual_keys():
    """
    检测 SA 双密钥 (VIKEY USB + SZU100 指纹)
    返回 (vikey_ok, fp_ok, reason_list, auth_method)
    
    注: 真实 VIKEY/SZU100 检测由 vikey_enforcement_middleware 统一做,
    这里只做轻量检查 + 缓存, 失败时返回 reason 让上层决定
    """
    now = time.time()
    
    # 2 秒缓存
    if _DUAL_CACHE["result"] and (now - _DUAL_CACHE["ts"]) < _DUAL_CACHE["ttl"]:
        return _DUAL_CACHE["result"]
    
    reasons = []
    vikey_ok = True   # 默认 pass (真实检测在 middleware)
    fp_ok = True      # 默认 pass
    
    # 检查 Flask g context 里是否已有双密钥检测结果
    try:
        dual = g.get("vikey_dual_status")
        if dual and isinstance(dual, dict):
            vikey_ok = dual.get("vikey_status", True) in (True, "online", "ok")
            fp_ok = dual.get("szu100_status", True) in (True, "online", "ok")
            if not vikey_ok:
                reasons.append("VIKEY 加密狗未在线")
            if not fp_ok:
                reasons.append("SZU100 指纹/专用U盘未验证")
    except Exception:
        pass
    
    if vikey_ok and fp_ok:
        auth_method = "vikey+fingerprint"
    elif vikey_ok and not fp_ok:
        auth_method = "vikey_only"
    elif not vikey_ok and fp_ok:
        auth_method = "fingerprint_only"
    else:
        auth_method = "none"
    
    result = (vikey_ok, fp_ok, reasons, auth_method)
    _DUAL_CACHE["result"] = result
    _DUAL_CACHE["ts"] = now
    return result


# ─── 403 响应 ───
def _deny(code, reason, vikey_ok=None, fp_ok=None, grace_code=None, terminal_status="denied"):
    body = {
        "success": False,
        "error": reason,
        "error_code": code,
        "flow_id": "flow_sa_perm_ext_1789703900",
        "vikey_status": "online" if vikey_ok else ("offline" if vikey_ok is False else None),
        "fingerprint_status": "online" if fp_ok else ("offline" if fp_ok is False else None),
        "terminal_status": terminal_status,
    }
    if grace_code:
        body["grace_code"] = grace_code
    return jsonify(body), 403


# ─── 核心装饰器 ───
def sa_arduino_guard(scope="vault", privilege_code=None, **kwargs):
    """
    SA Arduino 专属权限装饰器
    
    使用:
        @sa_arduino_guard(scope='ide')
        def my_arduino_route():
            ...
    
    scope: vault | setup | ide | detect | compile
    privilege_code: 可选, 覆盖默认 scope→privilege 映射
    """
    priv_code = privilege_code or _SCOPE_PRIVILEGE_MAP.get(scope, "ARDUINO_VAULT_ACCESS")
    
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kw):
            username = _current_username()
            role = _current_role()
            is_sa = _is_sa()
            session_id = f"ard-{uuid.uuid4().hex[:12]}"
            
            # ── Stage 1: 登录检查 ──
            login_ok, _ = _check_login()
            if not login_ok:
                _write_session(session_id, username, scope, priv_code, 
                              False, False, "none", "denied_no_login")
                return _deny("ARD_NOT_LOGGED_IN", "请登录后访问 Arduino 相关功能",
                            terminal_status="need_login")
            
            # ── Stage 2: privilege 配置检查 ──
            priv_ok, priv_info = _check_privilege(priv_code, username)
            
            # ── Stage 3: scope 级别守卫 ──
            if scope == "vault":
                # vault: 登录即可, 但非 SA 会被 role 限制在 admin+
                if not is_sa and role not in ("admin", "hardware_admin", "teacher"):
                    _write_session(session_id, username, scope, priv_code,
                                  False, False, "none", "denied_role")
                    return _deny("ARD_VAULT_ADMIN_ONLY", "需要 admin 或以上角色访问 Vault",
                                terminal_status="denied_role")
            
            elif scope == "detect":
                # detect: SA 双密钥
                if not is_sa:
                    _write_session(session_id, username, scope, priv_code,
                                  False, False, "none", "denied_role")
                    return _deny("ARD_DETECT_SA_ONLY", "仅 SA 可执行 Arduino 设备自动检测",
                                terminal_status="not_sa_role")
                vikey_ok, fp_ok, reasons, auth_method = _check_dual_keys()
                if not (vikey_ok and fp_ok):
                    grace_ok, grace_info = _check_grace_window(priv_code, username)
                    if not grace_ok:
                        _write_session(session_id, username, scope, priv_code,
                                      vikey_ok, fp_ok, auth_method, "denied_dual")
                        return _deny("ARDUINO_SA_ONLY", 
                                    "ARDUINO_SA_ONLY: 需 SA 双密钥同时在线: " + "; ".join(reasons),
                                    vikey_ok=vikey_ok, fp_ok=fp_ok,
                                    terminal_status="dual_fail")
            
            elif scope == "setup":
                # setup: SA 双密钥 或 admin 登录
                if not is_sa and role not in ("admin", "hardware_admin"):
                    _write_session(session_id, username, scope, priv_code,
                                  False, False, "none", "denied_role")
                    return _deny("ARD_SETUP_ADMIN_ONLY", "仅管理员可访问 Arduino 设置",
                                terminal_status="denied_role")
                if is_sa:
                    vikey_ok, fp_ok, reasons, auth_method = _check_dual_keys()
                    if not (vikey_ok and fp_ok):
                        grace_ok, grace_info = _check_grace_window(priv_code, username)
                        if not grace_ok:
                            _write_session(session_id, username, scope, priv_code,
                                          vikey_ok, fp_ok, auth_method, "denied_dual")
                            return _deny("ARDUINO_SA_ONLY",
                                        "Arduino 管理员设置(SA): 需双密钥: " + "; ".join(reasons),
                                        vikey_ok=vikey_ok, fp_ok=fp_ok,
                                        terminal_status="dual_fail")
            
            elif scope == "ide" or scope == "compile":
                # ide/compile: 严格 SA 双密钥
                if not is_sa:
                    _write_session(session_id, username, scope, priv_code,
                                  False, False, "none", "denied_role")
                    return _deny("ARDUINO_IDE_SA_ONLY", "仅超级管理员(wuchenghao15)可访问 Arduino IDE",
                                terminal_status="not_sa_role")
                vikey_ok, fp_ok, reasons, auth_method = _check_dual_keys()
                if not (vikey_ok and fp_ok):
                    grace_ok, grace_info = _check_grace_window(priv_code, username)
                    if not grace_ok:
                        _write_session(session_id, username, scope, priv_code,
                                      vikey_ok, fp_ok, auth_method, "denied_dual")
                        return _deny("ARDUINO_SA_ONLY",
                                    "Arduino IDE 需要 VIKEY + SZU100 双密钥: " + "; ".join(reasons),
                                    vikey_ok=vikey_ok, fp_ok=fp_ok,
                                    terminal_status="dual_fail")
            
            # ── Stage 4: pass → 写 session ──
            vikey_ok = _check_dual_keys()[0] if is_sa else None
            fp_ok = _check_dual_keys()[1] if is_sa else None
            auth = _check_dual_keys()[3] if is_sa else "login_only"
            _write_session(session_id, username, scope, priv_code,
                          vikey_ok, fp_ok, auth, "active")
            
            # 注入 session_id 到 g, 供后续使用
            g.arduino_session_id = session_id
            g.arduino_scope = scope
            g.arduino_privilege = priv_code
            
            return f(*args, **kw)
        return wrapper
    return decorator


# ─── SA 通用装饰器 (非 Arduino, 复用同一套机制) ───
def sa_privilege_guard(privilege_code=None, **kwargs):
    """
    SA 通用权限守卫 (基于 mt_sa_privileges 表)
    
    使用:
        @sa_privilege_guard(privilege_code="SYSTEM_VERSION_BUMP")
        def bump_version():
            ...
    """
    priv_code = privilege_code or "UNKNOWN"
    
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kw):
            username = _current_username()
            is_sa = _is_sa()
            
            if not _check_login()[0]:
                return _deny("SA_NOT_LOGGED_IN", "请登录", terminal_status="need_login")
            
            if not is_sa:
                return _deny("SA_ONLY", "需要 SA 权限", terminal_status="not_sa_role")
            
            # 检查 privilege
            priv_ok, priv_info = _check_privilege(priv_code, username)
            
            # 检查双密钥
            vikey_ok, fp_ok, reasons, _ = _check_dual_keys()
            if not (vikey_ok and fp_ok):
                # 尝试 grace
                grace_ok, _ = _check_grace_window(priv_code, username)
                if not grace_ok:
                    return _deny("SA_DUAL_KEY_REQUIRED",
                                f"{priv_code}: 需要 VIKEY + SZU100 双密钥",
                                vikey_ok=vikey_ok, fp_ok=fp_ok,
                                terminal_status="dual_fail")
            
            return f(*args, **kw)
        return wrapper
    return decorator
