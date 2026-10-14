# -*- coding: utf-8 -*-
"""
杨安 AI 安全仪表盘 & 安全开关 & 审计日志 & CSP报告 Blueprint 第20号
Blueprint: security_bp  url_prefix=/api/security  (注册于 routes/__init__.py)

全部端点强制权限装饰器：
  dashboard / switches / audit_logs  → @system_container(require_auth='admin')
  POST switch_config (SA VIIKEY改开关) → @system_container(require_auth='super_admin')
  csp-report (公网UA上报浏览器CSP违规) → @system_container(require_auth='guest', audit=False)

§14 IRON_RULE bypass_allowed=False  (已体现在 lifecycle flow_id)
§用户权限 SA wuchenghao15 唯一：修改/开关/备份 必须SA VIIKEY签核校验
经验 1149526：
  - 所有密钥/口令字段返回时统一 *** 脱敏，不允许接口直接吐开关的 vikey_hash_signature 明文
  - 生产SECURE 缺省 → exit 2（在 server_real_db 启动入口实现，这里仅提供探针 /probe_prod_secure）
"""
import os
import sys
import json
import sqlite3
import hashlib
import time
import logging
import datetime
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, request, jsonify, session, g

logger = logging.getLogger('security_routes')

# 和 routes/__init__.py 中 security_bp 保持一致（第20号 Blueprint）
from . import security_bp


# ============================================================================
# 延迟导入 & 共享辅助
# ============================================================================
def _main_conn():
    """获取主库连接（真实MAIN_DB）。调用方关闭。"""
    from core.db_path import get_db_path
    return sqlite3.connect(get_db_path("app.db"), timeout=15)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _current_safe_user() -> Dict:
    """session 用户安全字典（兼容两种会话来源：server_real_db / 轻量session）"""
    try:
        from server_real_db import _current_user, _safe_user_ctx
        u = _current_user()
        return _safe_user_ctx(u) or {}
    except Exception:
        role = session.get('role', 'guest')
        return {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'role': role,
            'is_super_admin': role in ('super_admin', 'sadmin') or session.get('username') == 'wuchenghao15',
            'logged_in': bool(session.get('user_id')),
            'permissions': session.get('permissions', []),
        }


def _ip_masked(ip: str) -> str:
    """IPv4 掩码/24，IPv6 掩码/56；防PII写入审计库"""
    if not ip:
        return ""
    try:
        import ipaddress as _ip
        a = _ip.ip_address(ip)
        if a.version == 4:
            n = _ip.ip_network(f"{a}/24", strict=False)
            return str(n.network_address) + "/24"
        n = _ip.ip_network(f"{a}/56", strict=False)
        return str(n.network_address) + "/56"
    except Exception:
        if '.' in ip:
            return '.'.join(ip.split('.')[:3]) + '.0/24'
        return ip[:19] + '::/56' if ':' in ip else ip


def _ua_hash(ua: str) -> str:
    if not ua:
        return ""
    return hashlib.sha256(ua.encode('utf-8', errors='replace')).hexdigest()[:16]


def _req_meta() -> Tuple[str, str]:
    try:
        ip = request.remote_addr or ""
    except Exception:
        ip = ""
    try:
        ua = request.headers.get("User-Agent", "")
    except Exception:
        ua = ""
    return ip, ua


def _write_audit(action: str, module: str, risk_level: str = "L", detail: Optional[Dict] = None):
    """安全操作落审计（杨安AI mt_security_audit_log）。失败=静默。"""
    try:
        u = _current_safe_user()
        ip, ua = _req_meta()
        conn = _main_conn()
        try:
            conn.execute("""INSERT INTO mt_security_audit_log
(ts, user_id, action, module, risk_level, ip_masked, user_agent_hash, detail_json, created_at)
VALUES (?,?,?,?,?,?,?,?,?)""",
(_now_iso(), str(u.get('username') or u.get('id') or ''), action, module, risk_level,
 _ip_masked(ip), _ua_hash(ua),
 json.dumps(detail or {}, ensure_ascii=False)[:8192],
 _now_iso()))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _sa_vikey_signature_check(expect_operation: str) -> Tuple[bool, str]:
    """
    SA VIIKEY 签核校验。
    在桌面端环境，SA操作前会通过USB读取VID:PID生成vikey_hash传到请求头X-MTSCOS-VIKEY-SIG。
    简化版校验：SA用户名必须=wuchenghao15；sign非空；写入mt_sa_vikey_ticket一次记录。
    生产=必须 USB 硬件心跳 + VID:PID = 白名单真实匹配；此处保留最小可运行骨架。
    """
    u = _current_safe_user()
    if u.get('username') != 'wuchenghao15' and not u.get('is_super_admin'):
        return False, "需要超级管理员 wuchenghao15"
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    sig = request.headers.get("X-MTSCOS-VIKEY-SIG") or body.get("vikey_signature")
    if not sig:
        return False, "SA VIKEY签名缺失：请求头X-MTSCOS-VIKEY-SIG或body.vikey_signature"
    if not session.get('_sa_session') or session.get('auth_method') != 'vikey+szu100_dual':
        return False, "SA 双硬件会话无效"
    try:
        from core.services.vikey_driver import get_hardware_key_provider
        dual_ok, dual_reason = get_hardware_key_provider().verify_dual_key_atomic(timeout=5.0)
    except Exception:
        dual_ok, dual_reason = False, 'provider_error'
    if not dual_ok:
        return False, f"SA 双硬件复核失败: {dual_reason}"
    # 写入 VIIKEY ticket 审计链（一次一票 redeem 后失效）
    try:
        ticket_id = f"VIK_{hashlib.sha256((sig + expect_operation + _now_iso()).encode()).hexdigest()[:24]}"
        op_hash = hashlib.sha256(json.dumps({"op": expect_operation, "ts": _now_iso()}, sort_keys=True).encode()).hexdigest()
        pid_vid = request.headers.get("X-MTSCOS-VIKEY-VIDPID") or "UNKNOWN"
        issued_at = _now_iso()
        exp = (datetime.datetime.now() + datetime.timedelta(minutes=5)).isoformat(timespec="seconds")
        conn = _main_conn()
        try:
            conn.execute("""INSERT OR IGNORE INTO mt_sa_vikey_ticket
(ticket_id, operation_hash, issued_by_sa, vikey_device_pid_vid, issued_at, expiry_at, redeemed_at)
VALUES (?,?,?,?,?,?,?)""",
(ticket_id, op_hash, u.get('username') or 'wuchenghao15', pid_vid, issued_at, exp, issued_at))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    return True, "ok"


# ============================================================================
# 0. 权限装饰器：统一 @system_container
# ============================================================================
def _with_system_container(require_auth: str = "login", allowed_roles: Optional[List[str]] = None, audit: bool = True):
    """与现有 @system_container 保持接口一致；优先导入真实装饰器，fallback=自实现最小兼容。"""
    try:
        from app.middlewares.system_container import system_container as _real
        real_decorator = _real(require_auth=require_auth, allowed_roles=allowed_roles, audit=audit)
        if require_auth != "super_admin":
            return real_decorator

        def sa_decorator(fn):
            from functools import wraps
            protected = real_decorator(fn)

            @wraps(protected)
            def wrapper(*a, **kw):
                if not session.get('_sa_session') or session.get('auth_method') != 'vikey+szu100_dual':
                    return jsonify({
                        "success": False,
                        "error": "需要有效的 VIKEY + SZU100 双硬件会话",
                        "code": "SA_DUAL_HARDWARE_REQUIRED",
                    }), 403
                return protected(*a, **kw)

            return wrapper

        return sa_decorator
    except Exception:
        # fallback 轻量实现（保证不绕开权限：至少 login 级 session.logged_in / username 非空）
        def decorator(fn):
            from functools import wraps
            @wraps(fn)
            def wrapper(*a, **kw):
                u = _current_safe_user()
                if require_auth in ("login", "admin", "super_admin"):
                    if not (u.get('logged_in') or u.get('id') or u.get('username')):
                        return jsonify({"success": False, "error": "未登录或会话已过期", "code": "CONTAINER_MISSING"}), 401
                if require_auth in ("admin", "super_admin"):
                    if u.get('role') not in ('admin', 'senior_admin', 'developer', 'supervisor', 'super_admin', 'sadmin', 'teacher_admin') and not u.get('is_super_admin'):
                        return jsonify({"success": False, "error": "需要管理员权限", "code": "ADMIN_ONLY"}), 403
                if require_auth == "super_admin":
                    if not u.get('is_super_admin') and u.get('username') != 'wuchenghao15':
                        return jsonify({"success": False, "error": "需要超级管理员权限(wuchenghao15)", "code": "SA_ONLY", "arduino_route_rule": "仅SA可访问，参考Arduino路由403硬锁规则"}), 403
                    if not session.get('_sa_session') or session.get('auth_method') != 'vikey+szu100_dual':
                        return jsonify({"success": False, "error": "需要有效的 VIKEY + SZU100 双硬件会话", "code": "SA_DUAL_HARDWARE_REQUIRED"}), 403
                if allowed_roles and u.get('role') not in allowed_roles and not u.get('is_super_admin'):
                    return jsonify({"success": False, "error": "角色不在允许列表", "code": "ROLE_NOT_ALLOWED"}), 403
                return fn(*a, **kw)
            return wrapper
        return decorator


# ============================================================================
# 1. GET /api/security/dashboard  杨安AI仪表盘：header基线/13开关/审计汇总/密码算法/硬编码密钥线索 6灯
# ============================================================================
@security_bp.route("/dashboard", methods=["GET"])
@_with_system_container(require_auth="admin")
def sec_dashboard():
    u = _current_safe_user()
    headers_expected = ("Strict-Transport-Security", "Content-Security-Policy",
                        "X-Frame-Options", "X-XSS-Protection", "Referrer-Policy",
                        "X-Content-Type-Options", "Permissions-Policy")
    # 开关表
    conn = _main_conn()
    try:
        switches = [dict(r) for r in conn.execute(
            "SELECT config_key, enabled, threshold_value, last_modified_by_sa, updated_at FROM mt_security_switch_config ORDER BY config_key"
        ).fetchall()]
        # 审计日志：24h 按风险等级分布
        ts_24h = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat(timespec="seconds")
        risk_rows = conn.execute(
            "SELECT COALESCE(risk_level,'?'), COUNT(*) FROM mt_security_audit_log WHERE created_at>=? GROUP BY risk_level",
            (ts_24h,)).fetchall()
        risk_dist = dict(risk_rows)
        total_audit_24h = sum(risk_dist.values())
        # DB访问审计7天
        ts_7d = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(timespec="seconds")
        db_op_rows = conn.execute(
            "SELECT COALESCE(op_type,'?'), COUNT(*) FROM mt_db_access_audit WHERE created_at>=? GROUP BY op_type",
            (ts_7d,)).fetchall()
        # VIIKEY ticket 近24h
        vikey_cnt_24h = conn.execute(
            "SELECT COUNT(*) FROM mt_sa_vikey_ticket WHERE issued_at>=?",
            (ts_24h,)).fetchone()[0]
    finally:
        conn.close()
    switch_map = {s["config_key"]: bool(int(s["enabled"])) for s in switches}
    # header基线灯：HSTS/XXSS/XContent/CSP/XFO/Referrer = 开关真实状态
    header_6_status = {
        "Strict-Transport-Security": switch_map.get("sec_header_hsts", False),
        "Content-Security-Policy-Report-Only": switch_map.get("sec_header_csp", False),
        "X-Frame-Options_DENY": switch_map.get("sec_header_xfo_deny", False),
        "X-XSS-Protection": switch_map.get("sec_header_xxss", True),
        "Referrer-Policy": switch_map.get("sec_header_referrer", False),
        "X-Content-Type-Options": switch_map.get("sec_header_xcontenttype", True),
        "Permissions-Policy": True,  # always on
    }
    return jsonify({
        "success": True,
        "module": "YANG_AI_SECURITY_CENTER",
        "version": "1.0.0",
        "user": {"username": u.get('username'), "role": u.get('role'), "is_sa": bool(u.get('is_super_admin') or u.get('username') == 'wuchenghao15')},
        "header_baseline_6_lights": header_6_status,
        "security_switches_13": [
            {"key": s["config_key"], "enabled": bool(int(s["enabled"])),
             "threshold": s.get("threshold_value"),
             "last_modified_by_sa": s.get("last_modified_by_sa"),
             "updated_at": s.get("updated_at")} for s in switches
        ],
        "audit_summary_24h": {
            "total": total_audit_24h,
            "by_risk_level": risk_dist,
            "db_access_op_distribution_7d": dict(db_op_rows),
            "vikey_tickets_24h": vikey_cnt_24h,
        },
        "security_goals": {
            "headers_present_target_6of7": sum(1 for v in header_6_status.values() if v),
            "weak_constraint_words_target_0": 0,  # 对应 sys_rule_enforcer:300s 扫描
            "hacker_probe_pass_rate_target": "100% (1000轮:正400/异300/黑300)",
            "production_fail_fast_exit_code": 2,  # 经验1149526
        },
        "notice": "所有安全开关可SA VIIKEY PATCH /api/security/switch_config 一键热回滚(<30s)；CSP 先 ReportOnly 14天再启用阻断。",
    })


# ============================================================================
# 2. GET /api/security/switch_config  列表13开关（admin+）
# ============================================================================
@security_bp.route("/switch_config", methods=["GET"])
@_with_system_container(require_auth="admin")
def sec_switch_get():
    conn = _main_conn()
    try:
        rows = conn.execute(
            "SELECT config_key, enabled, threshold_value, last_modified_by_sa, updated_at FROM mt_security_switch_config ORDER BY config_key"
        ).fetchall()
    finally:
        conn.close()
    return jsonify({
        "success": True,
        "switches": [
            {"config_key": r[0], "enabled": bool(int(r[1])),
             "threshold_value": r[2], "last_modified_by_sa": r[3], "updated_at": r[4]}
            for r in rows
        ],
    })


# ============================================================================
# 3. PATCH /api/security/switch_config  SA VIIKEY改开关 (单点 or 批量)
# ============================================================================
@security_bp.route("/switch_config", methods=["PATCH", "POST"])
@_with_system_container(require_auth="super_admin")
def sec_switch_set():
    u = _current_safe_user()
    ok, msg = _sa_vikey_signature_check("sec_switch_set")
    if not ok:
        _write_audit("SEC_SWITCH_REJECT", "SECURITY_SWITCHES", "H", {"reason": msg, "ip_masked": _ip_masked(request.remote_addr or "")})
        return jsonify({"success": False, "error": msg, "code": "SA_VIKEY_SIG_MISSING"}), 403
    body = request.get_json(silent=True) or {}
    updates = body.get("updates") or ([body.get("update")] if body.get("config_key") else [])
    # 简化：单对象直接传入config_key/enabled/threshold
    if not any(updates):
        single = {
            "config_key": body.get("config_key"),
            "enabled": body.get("enabled"),
            "threshold_value": body.get("threshold_value"),
        }
        if single["config_key"]:
            updates = [single]
    # 白名单：只允许修改 mt_security_switch_config 中存在的 key
    allowed_keys = set()
    conn = _main_conn()
    try:
        allowed_keys = {r[0] for r in conn.execute("SELECT config_key FROM mt_security_switch_config").fetchall()}
    finally:
        pass
    applied = []
    rejected = []
    now = _now_iso()
    sa_name = u.get('username') or 'wuchenghao15'
    for item in updates:
        if not item:
            continue
        k = item.get("config_key")
        if k not in allowed_keys:
            rejected.append({"config_key": k, "reason": "not in mt_security_switch_config"})
            continue
        en = item.get("enabled")
        thr = item.get("threshold_value")
        fields = []
        params = []
        if isinstance(en, (bool, int)):
            fields.append("enabled=?")
            params.append(1 if en else 0)
        if thr is not None:
            fields.append("threshold_value=?")
            params.append(str(thr)[:1024])
        if not fields:
            rejected.append({"config_key": k, "reason": "no fields to update (enabled/threshold_value)"})
            continue
        fields.append("last_modified_by_sa=?")
        params.append(sa_name)
        fields.append("vikey_hash_signature=?")
        params.append(request.headers.get("X-MTSCOS-VIKEY-SIG") or "PATCHED_BY_SA_VIKEY_AT_" + now)
        fields.append("updated_at=?")
        params.append(now)
        params.append(k)
        try:
            conn.execute(f"UPDATE mt_security_switch_config SET {', '.join(fields)} WHERE config_key=?", params)
            applied.append(k)
        except Exception as e:
            rejected.append({"config_key": k, "reason": f"db_error: {e}"})
    try:
        conn.commit()
    finally:
        conn.close()
    _write_audit("SEC_SWITCH_UPDATED", "SECURITY_SWITCHES", "M", {
        "applied_count": len(applied), "rejected_count": len(rejected),
        "applied_keys": applied[:50], "rejected": rejected[:20], "sa": sa_name,
    })
    return jsonify({"success": len(applied) > 0, "applied": applied, "rejected": rejected,
                    "message": "热回滚已完成(<30s，无需重启服务)，下一次请求即生效。" if applied else "无更新"})


# ============================================================================
# 4. GET /api/security/audit_logs  分页+过滤 mt_security_audit_log
# ============================================================================
@security_bp.route("/audit_logs", methods=["GET"])
@_with_system_container(require_auth="admin")
def sec_audit_logs():
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(500, max(10, int(request.args.get("page_size", 50))))
    risk = request.args.get("risk_level")
    module = request.args.get("module")
    user_id = request.args.get("user_id")
    action_like = request.args.get("action_like")
    conn = _main_conn()
    try:
        where = []
        params = []
        if risk:
            where.append("risk_level=?"); params.append(risk)
        if module:
            where.append("module=?"); params.append(module)
        if user_id:
            where.append("user_id LIKE ?"); params.append(f"%{user_id}%")
        if action_like:
            where.append("action LIKE ?"); params.append(f"%{action_like}%")
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM mt_security_audit_log {wsql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id,ts,user_id,action,module,risk_level,ip_masked,created_at, substr(detail_json,1,400) FROM mt_security_audit_log {wsql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size]).fetchall()
    finally:
        conn.close()
    cols = ["id", "ts", "user_id", "action", "module", "risk_level", "ip_masked", "created_at", "detail_preview"]
    return jsonify({
        "success": True,
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "rows": [dict(zip(cols, r)) for r in rows],
    })


# ============================================================================
# 5. POST /api/security/csp-report  CSP违规上报接收器 (Report-Only 阶段 14天收集)
#    匿名可写；限速IP 5次/分钟；写审计 L 级别；字段脱敏
# ============================================================================
@security_bp.route("/csp-report", methods=["POST"])
@_with_system_container(require_auth="guest", audit=False)
def sec_csp_report():
    # 简单IP限速
    try:
        ip = request.remote_addr or "anon"
        k = f"csp_limit_{ip.replace(':','_')}"
        g_attr = getattr(g, "_csp_rate", None)
        if g_attr is None:
            g._csp_rate = {}
        now = time.time()
        g._csp_rate[k] = (ts_list := [t for t in g._csp_rate.get(k, []) if now - t < 60])
        if len(ts_list) >= 5:
            return jsonify({"success": False, "error": "too many reports per minute"}), 429
        ts_list.append(now)
    except Exception:
        pass
    raw = request.get_data(as_text=True) or "{}"
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {"raw": raw[:400]}
    csp_doc = payload.get("csp-report") or payload or {}
    if not isinstance(csp_doc, dict):
        csp_doc = {"raw": str(csp_doc)[:400]}
    # 脱敏：blocked-uri/document-uri/victim-username不写PII，保留域名/协议即可
    def _mask_uri(u):
        if not isinstance(u, str): return u
        try:
            from urllib.parse import urlparse
            p = urlparse(u)
            return f"{p.scheme}://{p.netloc}/***" if p.scheme else ("/***" if u.startswith("/") else u[:80])
        except Exception:
            return u[:80]
    report = {
        "blocked_uri": _mask_uri(csp_doc.get("blocked-uri")),
        "document_uri": _mask_uri(csp_doc.get("document-uri")),
        "violated_directive": csp_doc.get("violated-directive"),
        "effective_directive": csp_doc.get("effective-directive"),
        "original_policy": csp_doc.get("original-policy"),
        "source_file": _mask_uri(csp_doc.get("source-file")),
        "line_number": csp_doc.get("line-number"),
        "status_code": csp_doc.get("status-code"),
        "script_sample": (csp_doc.get("script-sample") or "")[:100],
    }
    _write_audit("CSP_REPORT", "CSP_COLLECT", "L", report)
    return jsonify({"success": True, "received": True})


# ============================================================================
# 6. GET /api/security/status  对外状态探针（兼容 security_middleware.get_security_status 风格）
# ============================================================================
@security_bp.route("/status", methods=["GET"])
@_with_system_container(require_auth="guest", audit=False)
def sec_status_probe():
    try:
        from app.middlewares.security_middleware import get_security_status
        base = dict(get_security_status() or {})
    except Exception as e:
        base = {"error": str(e)}
    base["module"] = "YANG_AI_SECURITY_BP"
    base["blueprint_registered"] = True
    base["timestamp"] = _now_iso()
    return jsonify(base)


# ============================================================================
# 7. GET /api/security/probe_prod_secure  经验1149526探针：生产SECURE缺失=exit code=2
# ============================================================================
@security_bp.route("/probe_prod_secure", methods=["GET"])
@_with_system_container(require_auth="super_admin")
def sec_probe_prod_secure():
    required_secure = [
        "SECRET_KEY", "CSRF_SECRET", "SEC_PRODUCTION_FAIL_FAST",
        "PASSWORD_DEFAULT_ALGO",
    ]
    missing = [k for k in required_secure if not os.environ.get(k)]
    missing_notes = []
    if int(os.environ.get("SEC_PRODUCTION_FAIL_FAST", "0") or "0") == 1 and missing:
        missing_notes.append("⚠️ 生产SECURE缺失以下变量：" + ",".join(missing))
        missing_notes.append("按经验1149526，启动入口（server_real_db.py 初始化Flask前）应 sys.exit(2)，不可 fallback 到开发默认值。")
    return jsonify({
        "success": True,
        "environment_probed": {
            "env_FLASK_ENV": os.environ.get("FLASK_ENV"),
            "SEC_PRODUCTION_FAIL_FAST": os.environ.get("SEC_PRODUCTION_FAIL_FAST"),
            "required_secure_vars_missing": missing,
            "missing_count": len(missing),
        },
        "policy": {
            "expected_exit_code_when_missing_in_prod": 2,
            "ref": "经验1149526：补丁式迭代必禁止，ProductionConfig 缺失SECURE直接exit，不fallback。",
        },
        "notes": missing_notes or ["✅ 必要SECURE环境变量齐全。"],
    })


logger.info("杨安AI security_bp(/api/security) Blueprint 20号 端点加载完成：dashboard/switch_config[GR]/audit_logs/csp-report/status/probe_prod_secure")
