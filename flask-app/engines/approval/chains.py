"""
chains.py — 风险评估 + 审批链构建 (薄封装层)
==============================================
所有规则在 policy.py, 本模块只暴露业务函数:
  assess_risk()        — 1:1 行为兼容旧引擎
  build_nodes()        — 兼容旧 node_index/node_type/approver_role
                         + 新 mode/quorum/approvers_json/vikey_required
  backfill_chain()     — 给零节点孤儿单补链 (SA 选择 continue 时)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

# [unused] from .db import get_conn, db_retry
from .policy import (
    assess_risk as _assess_risk,
    build_chain_nodes,
)


def assess_risk(category: str, initiator_role: str, subject_hint: str = "") -> str:
    """1:1 行为兼容旧引擎 — 直接委托 policy.assess_risk"""
    return _assess_risk(category, initiator_role, subject_hint)


def build_nodes(
    category: str,
    initiator_role: str,
    risk_level: str | None = None,
    **kwargs: Any,
) -> list[dict]:
    """根据发起角色 + 类别 + 风险 → 完整审批链节点.
    kwargs: subject_hint (给 assess_risk), title/approvers 等 (透传)
    返回节点 dict 列表, 旧键 (node_index/node_type/approver_role/description/auto_pass)
    与新扩展键 (mode/quorum/approvers_json/vikey_required) 同时存在.
    """
    cat = (category or '').lower()
    init_role = (initiator_role or '').lower()
    hint = str(kwargs.get('subject_hint', '') or '')
    risk = risk_level or _assess_risk(cat, init_role, hint)
    return build_chain_nodes(cat, init_role, risk)


def backfill_chain(
    request_id: str,
    db_path: Any = None,
) -> int:
    """给零节点孤儿单补链 — 返回插入的节点数 (0 表示无需补).

    业务场景: reconcile 发现 2 单 demo 孤儿节点数=0,
    SA 选 continue 时调用. 补链后 backfill_flag=1 标识.
    """
    with get_conn(db_path) as conn:
        req = conn.execute(
            "SELECT * FROM mt_approval_requests WHERE request_id=?",
            (request_id,)).fetchone()
        if not req:
            return 0
        existing = conn.execute(
            "SELECT COUNT(*) AS c FROM mt_approval_nodes WHERE request_id=?",
            (request_id,)).fetchone()[0]
        if existing > 0:
            return 0

        nodes = build_chain_nodes(
            req['category'], req['initiator_role'], req['risk_level'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("BEGIN IMMEDIATE")
        for n in nodes:
            conn.execute(
                "INSERT INTO mt_approval_nodes "
                "(request_id, node_index, node_type, approver_role, auto_pass, "
                "notes, action, status, mode, quorum, approvers_json, "
                "vikey_required, backfill_flag, created_at) "
                "VALUES (?,?,?,?,?,?, 'pending', 'pending',?,?,?,?, 1, ?)",
                (request_id, n['node_index'], n['node_type'],
                 n.get('approver_role', ''),
                 1 if n.get('auto_pass') else 0,
                 n.get('description', ''),
                 n.get('mode', 'single'), n.get('quorum', 1),
                 n.get('approvers_json', '[]'),
                 n.get('vikey_required', 0), now))
        # 推进 current_node 到首个非 initiate 节点
        first_pending = next((n['node_index'] for n in nodes if n['node_type'] != 'initiate'), 0)
        conn.execute(
            "UPDATE mt_approval_requests SET current_node=? WHERE request_id=?",
            (first_pending, request_id))
        conn.execute("COMMIT")
        return len(nodes)
