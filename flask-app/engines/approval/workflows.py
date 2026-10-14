"""
approval/workflows.py — 审批域工作流
====================================

子系统自注册: approval 自己定义 workflow.
"""
import os, sys, time, json, sqlite3

def _get_app_db():
    prod = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
    for k in ("ANDROMEDA_DB", "APP_DB"):
        v = os.environ.get(k)
        if v and os.path.exists(v) and os.path.getsize(v) > 1_000_000:
            return v
    if os.path.exists(prod) and os.path.getsize(prod) > 1_000_000:
        return prod
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "database", "app.db"))


def _h_auto_approval_check(input):
    """wf_auto_approval_check — 审批策略自动放行/拦截检查.
    
    输入: {subject_type, subject_id, policy_name, risk_tags[], requester_role}
    输出: {decision: ALLOW|DENY|ESCALATE, reason, policy_hit}
    """
    subject_type = input.get("subject_type", "")
    subject_id = input.get("subject_id", "")
    risk_tags = input.get("risk_tags", [])
    role = input.get("requester_role", "guest")
    policy = input.get("policy_name", "default")
    t0 = time.time()
    
    # 内置审批策略矩阵 (可扩展)
    HIGH_RISK = {"secret_data", "vi_key", "payment", "sql_injection", "xss", "auth_bypass"}
    BLOCKED_ROLES_FOR_CRITICAL = {"guest", "student", "anonymous"}
    
    decision = "ALLOW"
    reason = "pass"
    policy_hit = policy
    
    risk_set = set(risk_tags)
    if risk_set & HIGH_RISK:
        hit = risk_set & HIGH_RISK
        if role in BLOCKED_ROLES_FOR_CRITICAL:
            decision = "DENY"
            reason = f"risk_tags {hit} blocked for role {role}"
        else:
            decision = "ESCALATE"
            reason = f"high risk {hit} → needs senior review"
    
    # 落库审批决策日志
    try:
        db = _get_app_db()
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            """INSERT INTO mt_approval_decisions
               (subject_type, subject_id, policy_name, requester_role, risk_tags_json,
                decision, reason, created_at)
               VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (subject_type, str(subject_id), policy, role, json.dumps(risk_tags, ensure_ascii=False),
             decision, reason))
        conn.commit()
        conn.close()
    except Exception:
        # 表不存在时跳过持久化
        pass
    
    return {"status": "SUCCESS",
            "output": {"decision": decision, "reason": reason, "policy_hit": policy_hit,
                       "risk_tags": risk_tags, "requester_role": role},
            "wall_ms": int((time.time() - t0) * 1000)}


def register_workflows(registry, register_fn):
    """approval 域 — 自动审批策略检查."""
    register_fn("wf_auto_approval_check", {
        "name": "自动审批检查", "domain": "approval",
        "description": "基于 risk_tags + requester_role 的审批策略放行/拦截/升级",
        "price_per_unit": 0.001, "pricing_unit": "check",
        "handler": _h_auto_approval_check, "requires": ["PROD_DB"],
        "tags": ["approval", "policy", "security"],
    })
