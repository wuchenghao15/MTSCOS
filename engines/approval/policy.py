"""
policy.py — 审批中台唯一配置源
==============================
所有风险规则 / 角色链 / 链模板 / SLA / LLM 矩阵 集中于此,
其他模块只 import 这里, 禁止各自硬编码.

旧 assess_risk() 是 test_engines.py 8 条断言的行为契约,
必须 1:1 移植, 禁止擅自改动. 新增规则只增量加.
"""
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════
# 角色审批链 (role → 上级审批人)
# SA 发起非 critical 单 → admin 兜底 (修旧 _get_next_approver
# 对 super_admin 返回 None 导致审批链死锁的 bug)
# ════════════════════════════════════════════════════════════════════
ROLE_CHAIN: dict[str, str] = {
    'student':    'teacher',
    'teacher':    'admin',
    'counselor':  'admin',
    'mentor':     'professor',
    'professor':  'admin',
    'parent':     'teacher',
    'admin':      'super_admin',
    'super_admin': 'admin',    # SA 自发 → admin 兜底 (critical 另加 SA 终审)
}


def _next_role(role: str) -> str | None:
    return ROLE_CHAIN.get((role or '').lower())


# ════════════════════════════════════════════════════════════════════
# 风险评估 — 1:1 移植旧 assess_risk 行为
# test_engines.py L57-64 8 条断言是契约, 禁止偏离
# ════════════════════════════════════════════════════════════════════
def assess_risk(category: str, initiator_role: str, subject_hint: str = '') -> str:
    """返回 low / medium / high / critical"""
    initiator_role = (initiator_role or '').lower()
    category = (category or '').lower()

    # 规则修改 / daemon / 权限 → 最高级
    if category in ('rule_change', 'daemon_change', 'permission_change'):
        return 'critical'

    # 管理员/SA 发的内容 → 至少 high
    if initiator_role in ('admin', 'super_admin') and category in ('course_content', 'exam', 'publish'):
        return 'high'

    # 教授/导师发表 → high
    if initiator_role in ('professor', 'mentor') and category in ('course_content', 'research', 'thesis'):
        return 'high'

    # 学生写文曲星 → low (longform / hint 前缀≥2000 → medium)
    if initiator_role == 'student' and category == 'wenquxing':
        hint_lower = (subject_hint or '').lower()
        try:
            hint_num = int(subject_hint.strip()[:6]) if (subject_hint or '').strip().isdigit() else 0
        except Exception:
            hint_num = 0
        if 'longform' in hint_lower or hint_num >= 2000:
            return 'medium'
        return 'low'

    # 教师布置作业 → medium
    if initiator_role == 'teacher' and category in ('homework', 'exam', 'course_content'):
        return 'medium'

    # 家长提的 → low
    if initiator_role == 'parent':
        return 'low'

    return 'medium'


# ════════════════════════════════════════════════════════════════════
# 链模板 — 按 risk_level 定义 (内部再按 category 微调)
# 每个模板返回节点构造元组, chains.py 负责展开成完整节点 dict
# ════════════════════════════════════════════════════════════════════
def build_chain_nodes(
    category: str,
    initiator_role: str,
    risk: str,
) -> list[dict]:
    """返回节点 dict 列表 (兼容旧键 + 新扩展键).
    旧键: node_index / node_type / approver_role / description / auto_pass
    新键: mode / quorum / approvers_json / vikey_required / backfill_flag
    """
    initiator_role = (initiator_role or '').lower()
    category = (category or '').lower()
    nodes: list[dict] = []
    idx = 0

    # ── 0. initiate 节点 (所有链都有) ──
    nodes.append({
        "node_index": idx,
        "node_type": "initiate",
        "approver_role": initiator_role,
        "description": f"发起人({initiator_role})自动通过",
        "auto_pass": True,
        "mode": "single", "quorum": 1,
        "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
    })
    idx += 1

    # ── 1. ai_review 节点 (非 low 才有) ──
    if risk != 'low':
        nodes.append({
            "node_index": idx,
            "node_type": "ai_review",
            "approver_role": "andromeda",
            "description": f"仙女座 AI 风控预审 (risk={risk}, category={category})",
            "auto_pass": False,
            "mode": "single", "quorum": 1,
            "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
        })
        idx += 1

    # ── 2. 按 risk 生成人工审批节点 ──
    if risk == 'low':
        # low → student+wenquxing 例外要 teacher 确认; 其余无人工
        if initiator_role == 'student' and category == 'wenquxing':
            nodes.append({
                "node_index": idx, "node_type": "role_approver",
                "approver_role": "teacher",
                "description": "学生文曲星产出 → 任课教师确认",
                "auto_pass": True,
                "mode": "single", "quorum": 1,
                "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
            })

    elif risk == 'medium':
        # medium → 直属上级 (SA 自发 → admin)
        nr = _next_role(initiator_role)
        if nr:
            nodes.append({
                "node_index": idx, "node_type": "role_approver",
                "approver_role": nr,
                "description": f"直属上级 ({nr}) 审批",
                "auto_pass": False,
                "mode": "single", "quorum": 1,
                "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
            })

    elif risk == 'high':
        # high → 直属上级 (跳过 admin/SA) + admin
        nr = _next_role(initiator_role)
        if nr and nr not in ('admin', 'super_admin'):
            nodes.append({
                "node_index": idx, "node_type": "role_approver",
                "approver_role": nr,
                "description": f"直属上级 ({nr}) 审批",
                "auto_pass": False,
                "mode": "single", "quorum": 1,
                "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
            })
            idx += 1
        nodes.append({
            "node_index": idx, "node_type": "role_approver",
            "approver_role": "admin",
            "description": "管理员审批",
            "auto_pass": False,
            "mode": "single", "quorum": 1,
            "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
        })

    elif risk == 'critical':
        # critical → 直属上级 (非 admin/SA 才加) + admin 会签 quorum=2 + SA vikey 终审
        nr = _next_role(initiator_role)
        if nr and nr not in ('admin', 'super_admin'):
            nodes.append({
                "node_index": idx, "node_type": "role_approver",
                "approver_role": nr,
                "description": f"直属上级 ({nr})",
                "auto_pass": False,
                "mode": "single", "quorum": 1,
                "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
            })
            idx += 1
        # admin 会签 (两人不同管理员)
        nodes.append({
            "node_index": idx, "node_type": "role_approver",
            "approver_role": "admin",
            "description": "管理员会签 (quorum=2, 两名不同管理员)",
            "auto_pass": False,
            "mode": "countersign", "quorum": 2,
            "approvers_json": "[]", "vikey_required": 0, "backfill_flag": 0,
        })
        idx += 1
        # SA vikey 终审 (rule_change / permission_change / daemon_change 强制)
        vikey_needed = 1 if category in ('rule_change', 'permission_change', 'daemon_change') else 0
        nodes.append({
            "node_index": idx, "node_type": "role_approver",
            "approver_role": "super_admin",
            "description": "SA 终审 (§14 IRON_RULE)",
            "auto_pass": False,
            "mode": "single", "quorum": 1,
            "approvers_json": "[]", "vikey_required": vikey_needed, "backfill_flag": 0,
        })

    return nodes


# ════════════════════════════════════════════════════════════════════
# SLA 策略 — low 24h催8h×2过期72h; medium 12h催4h×2过期48h;
# high 6h催2h×3过期24h; critical 2h催1h×3只升级不过期
# 保护类目 (rule_change/permission_change/daemon_change/release) 永久不过期
# ════════════════════════════════════════════════════════════════════
SLA_POLICY: dict[str, dict] = {
    'low':      {'sla_hours': 24, 'remind_every_hours': 8,  'remind_max': 2, 'escalate_every_hours': 96, 'escalate_max': 1, 'expire_hours': 72},
    'medium':   {'sla_hours': 12, 'remind_every_hours': 4,  'remind_max': 2, 'escalate_every_hours': 48, 'escalate_max': 2, 'expire_hours': 48},
    'high':     {'sla_hours': 6,  'remind_every_hours': 2,  'remind_max': 3, 'escalate_every_hours': 24, 'escalate_max': 3, 'expire_hours': 24},
    'critical': {'sla_hours': 2,  'remind_every_hours': 1,  'remind_max': 3, 'escalate_every_hours': 12, 'escalate_max': 3, 'expire_hours': 0},
}

EXPIRE_PROTECTED_CATEGORIES = frozenset({
    'rule_change', 'permission_change', 'daemon_change', 'release',
})


def sla_for(risk: str) -> dict:
    return SLA_POLICY.get(risk or 'medium', SLA_POLICY['medium'])


def is_expire_protected(category: str) -> bool:
    return (category or '').lower() in EXPIRE_PROTECTED_CATEGORIES


# ════════════════════════════════════════════════════════════════════
# LLM 矩阵 — 本地 Ollama 语义预审
# FORCED_MANUAL: 无论模型结论, 强制人工
# AUTO_PASS: 模型 verdict=pass 且 low/medium → 自动过
# AUTO_REJECT_OK: 模型 verdict=reject 可直接终局驳回 (仅 low)
# ════════════════════════════════════════════════════════════════════
FORCED_MANUAL = frozenset({
    'rule_change', 'permission_change', 'daemon_change',
})

LLM_SAFE_CATEGORIES = frozenset({
    'wenquxing', 'parent_feedback', 'homework', 'course_content', 'exam',
})

LLM_MODEL = 'qwen2.5:14b-q5'
LLM_ENDPOINT = 'http://localhost:11434/api/chat'
LLM_PROBE_ENDPOINT = 'http://localhost:11434/api/tags'
LLM_TIMEOUT = 45
LLM_PROBE_TIMEOUT = 3


def llm_policy_for(category: str, risk: str) -> str:
    """返回 'forced_manual' / 'auto_pass' / 'manual' (默认)"""
    cat = (category or '').lower()
    r = (risk or 'medium').lower()
    if cat in FORCED_MANUAL:
        return 'forced_manual'
    if cat in LLM_SAFE_CATEGORIES and r in ('low', 'medium'):
        return 'auto_pass'
    return 'manual'


# ════════════════════════════════════════════════════════════════════
# 节点状态常量 (新 STATUS 列权威值)
# ════════════════════════════════════════════════════════════════════
NODE_STATUS_PENDING   = 'pending'
NODE_STATUS_APPROVED  = 'approved'
NODE_STATUS_REJECTED  = 'rejected'
NODE_STATUS_SKIPPED   = 'skipped'
NODE_STATUS_DELEGATED = 'delegated'
NODE_STATUS_AI_PASSED = 'ai_passed'

REQ_STATUS_PENDING   = 'pending'
REQ_STATUS_APPROVED  = 'approved'
REQ_STATUS_REJECTED  = 'rejected'
REQ_STATUS_WITHDRAWN = 'withdrawn'
REQ_STATUS_EXPIRED   = 'expired'

ACTION_SUBMIT    = 'submit'
ACTION_APPROVE   = 'approve'
ACTION_REJECT    = 'reject'
ACTION_DELEGATE  = 'delegate'
ACTION_WITHDRAW  = 'withdraw'
ACTION_EXPIRE    = 'expire'
ACTION_AI_REVIEW = 'ai_review'
ACTION_AUTO_PASS = 'auto_pass'
ACTION_ESCALATE  = 'escalate'
ACTION_CC        = 'cc'
ACTION_SYSTEM_CLOSE = 'system_close'
