"""
state_machine.py — 单事务状态流转 + 会签计票
==============================================
所有写操作包在一个 BEGIN IMMEDIATE 事务里, 步骤固定:
  1. 插 mt_approval_actions 流水 (计票唯一权威)
  2. 更新 mt_approval_nodes (status + action 双写)
  3. 重算 current_node = 首个 (非 skipped/delegated/ai_passed) pending 节点
  4. 终态判定 → 更新 mt_approval_requests
  5. COMMIT

会签 countersign: distinct 审批人计票达 quorum 才过, 同人不重复计票,
任一 reject 默认一票否决.
或签 or_sign: 任一 approve 即过, reject 不阻断他人.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .db import get_conn, db_retry
from .policy import (
    NODE_STATUS_PENDING, NODE_STATUS_APPROVED, NODE_STATUS_REJECTED,
    NODE_STATUS_SKIPPED, NODE_STATUS_DELEGATED, NODE_STATUS_AI_PASSED,
    REQ_STATUS_PENDING, REQ_STATUS_APPROVED, REQ_STATUS_REJECTED,
    REQ_STATUS_WITHDRAWN, REQ_STATUS_EXPIRED,
    ACTION_APPROVE, ACTION_REJECT, ACTION_AUTO_PASS, ACTION_AI_REVIEW,
    ACTION_WITHDRAW, ACTION_EXPIRE, ACTION_SYSTEM_CLOSE, ACTION_ESCALATE,
)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _safe_load_json(s, default=None):
    if default is None:
        default = []
    if isinstance(s, (list, dict)):
        return s
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


# ════════════════════════════════════════════════════════════════════
# 单节点动作流转 (会签/或签/单签 全部走这里)
# ════════════════════════════════════════════════════════════════════
@db_retry()
def apply_node_action(
    request_id: str,
    node_index: int,
    action: str,          # approve / reject / auto_pass / ai_review / delegate
    actor: str,
    actor_role: str = '',
    notes: str = '',
    detail: dict | None = None,
    db_path: Any = None,
) -> dict:
    """返回 {ok, request_id, node_index, current_node, final_status, msg}
    所有写操作在一个 BEGIN IMMEDIATE 事务里完成.
    """
    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            req = conn.execute(
                "SELECT * FROM mt_approval_requests WHERE request_id=?",
                (request_id,)).fetchone()
            if not req:
                conn.execute("ROLLBACK")
                return {'ok': False, 'msg': 'request_not_found'}
            nodes = conn.execute(
                "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index",
                (request_id,)).fetchall()
            # sqlite3.Row 不支持 .get(), 统一转 dict
            nodes = [dict(n) for n in nodes]
            node_map = {n['node_index']: n for n in nodes}
            if node_index not in node_map:
                conn.execute("ROLLBACK")
                return {'ok': False, 'msg': f'node_{node_index}_not_found'}
            node = node_map[node_index]

            # ── 幂等保护: 节点已定则拒绝重复 ──
            cur_status = node['status'] or node['action'] or NODE_STATUS_PENDING
            if cur_status not in (NODE_STATUS_PENDING, '', None):
                # 会签下同一节点仍可能 pending 但同人重复提交 → 拒绝
                conn.execute("ROLLBACK")
                return {'ok': False, 'msg': f'node_already_{cur_status}'}

            now = _now()
            mode = (node['mode'] or 'single').lower()
            quorum = int(node['quorum'] or 1)
            current_actions = conn.execute(
                "SELECT actor, action FROM mt_approval_actions "
                "WHERE request_id=? AND node_index=? AND action IN ('approve','reject','auto_pass','ai_review')",
                (request_id, node_index)).fetchall()

            # ── 插 actions 流水 ──
            detail_json = json.dumps(detail or {}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO mt_approval_actions "
                "(request_id, node_index, action, actor, actor_role, notes, acted_at, detail_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (request_id, node_index, action, actor, actor_role, notes, now, detail_json))

            # ── 会签/或签 计票 ──
            new_status = None
            if action in (ACTION_APPROVE, ACTION_AUTO_PASS, ACTION_AI_REVIEW):
                approvers = {a['actor'] for a in current_actions}  # 同人去重
                approvers.add(actor)
                has_reject = any(a['action'] in (ACTION_REJECT,) for a in current_actions)
                # 一票否决
                if has_reject and mode != 'or_sign':
                    new_status = NODE_STATUS_REJECTED
                else:
                    if mode == 'countersign':
                        if len(approvers) >= quorum:
                            new_status = NODE_STATUS_APPROVED
                        else:
                            new_status = NODE_STATUS_PENDING   # 继续等
                    elif mode == 'or_sign':
                        # 任一 approve 即过
                        new_status = NODE_STATUS_APPROVED
                    else:  # single
                        new_status = NODE_STATUS_APPROVED
            elif action == ACTION_REJECT:
                if mode == 'or_sign':
                    # 或签下 reject 不阻断, 节点仍 pending
                    new_status = NODE_STATUS_PENDING
                else:
                    new_status = NODE_STATUS_REJECTED
            elif action == 'delegate':
                new_status = NODE_STATUS_DELEGATED

            if new_status == NODE_STATUS_PENDING:
                # 节点仍 pending, 只更新 approvers_json (计票状态)
                existing = _safe_load_json(node.get('approvers_json'), [])
                if actor not in existing:
                    existing.append(actor)
                conn.execute(
                    "UPDATE mt_approval_nodes SET approvers_json=? WHERE request_id=? AND node_index=?",
                    (json.dumps(existing), request_id, node_index))
                conn.execute("COMMIT")
                return {
                    'ok': True, 'request_id': request_id,
                    'node_index': node_index,
                    'current_node': _find_first_pending(nodes, conn),
                    'final_status': None,
                    'msg': 'countersign_pending',
                }

            # ── 节点终态: 更新 status + action 双写 ──
            action_col = action if new_status == NODE_STATUS_APPROVED else (
                'reject' if new_status == NODE_STATUS_REJECTED else action
            )
            conn.execute(
                "UPDATE mt_approval_nodes SET status=?, action=?, approver_name=?, "
                "notes=?, decided_at=? WHERE request_id=? AND node_index=?",
                (new_status, action_col, actor, notes, now, request_id, node_index))

            # ── 重算 current_node ──
            new_current = _find_first_pending(nodes, conn)
            conn.execute(
                "UPDATE mt_approval_requests SET current_node=?, updated_at=? WHERE request_id=?",
                (new_current, now, request_id))

            # ── 终态判定 ──
            final_status = None
            all_nodes = conn.execute(
                "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index",
                (request_id,)).fetchall()
            # 只有 role_approver 节点才算"人工决定"; initiate 自动过, ai_review auto/LLM 非阻塞
            human_nodes = [n for n in all_nodes
                           if n['node_type'] == 'role_approver']
            all_non_initiate = [n for n in all_nodes
                                if n['node_type'] != 'initiate']
            # 任一非 initiate 节点 reject → 整体 reject (含 ai_review reject)
            if any((n['status'] or n['action']) == NODE_STATUS_REJECTED for n in all_non_initiate):
                final_status = REQ_STATUS_REJECTED
            elif human_nodes:
                # 所有 role_approver 都已定 (approve/skip/delegate) → approved
                human_decided = [n for n in human_nodes
                                 if (n['status'] or n['action']) in (
                                     NODE_STATUS_APPROVED, NODE_STATUS_REJECTED,
                                     NODE_STATUS_SKIPPED, NODE_STATUS_DELEGATED,
                                 )]
                if len(human_decided) == len(human_nodes):
                    final_status = REQ_STATUS_APPROVED
            else:
                # 无 role_approver 节点 → 只有 initiate/ai_review → approved
                final_status = REQ_STATUS_APPROVED

            if final_status:
                conn.execute(
                    "UPDATE mt_approval_requests SET status=?, final_decision=?, "
                    "decided_by=?, decided_at=?, updated_at=? WHERE request_id=?",
                    (final_status, final_status, actor, now, now, request_id))

            conn.execute("COMMIT")
            return {
                'ok': True, 'request_id': request_id,
                'node_index': node_index,
                'current_node': new_current,
                'final_status': final_status,
                'msg': 'ok',
            }
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise


def _find_first_pending(nodes_prev: list, conn) -> int | None:
    """查询当前所有节点, 找首个非终态的 pending 节点.
    终态: approved/rejected/skipped/delegated/ai_passed.
    initiate 如果没被自动过也算 pending (理论上 submit 时已 auto_pass).
    """
    all_nodes = conn.execute(
        "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index",
        (nodes_prev[0]['request_id'],)).fetchall()
    terminal = {
        NODE_STATUS_APPROVED, NODE_STATUS_REJECTED,
        NODE_STATUS_SKIPPED, NODE_STATUS_DELEGATED, NODE_STATUS_AI_PASSED,
        'approve', 'reject',  # 旧 action 列也兼容
    }
    for n in all_nodes:
        st = n['status'] or n['action'] or NODE_STATUS_PENDING
        if st not in terminal:
            return n['node_index']
    return None


# ════════════════════════════════════════════════════════════════════
# 终态动作: withdraw / expire / system_close
# ════════════════════════════════════════════════════════════════════
@db_retry()
def finalize_request(
    request_id: str,
    final_status: str,   # REQ_STATUS_WITHDRAWN / REQ_STATUS_EXPIRED
    actor: str,
    reason: str = '',
    db_path: Any = None,
) -> dict:
    """整单终态收敛 — 所有未决节点标记为 skipped, 写 actions 流水."""
    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            req = conn.execute(
                "SELECT * FROM mt_approval_requests WHERE request_id=?",
                (request_id,)).fetchone()
            if not req:
                conn.execute("ROLLBACK")
                return {'ok': False, 'msg': 'request_not_found'}
            if (req['status'] or '').lower() not in (REQ_STATUS_PENDING, ''):
                conn.execute("ROLLBACK")
                return {'ok': False, 'msg': f'request_already_{req["status"]}'}

            now = _now()
            # 1. 插 finalize action
            conn.execute(
                "INSERT INTO mt_approval_actions "
                "(request_id, node_index, action, actor, actor_role, notes, acted_at, detail_json) "
                "VALUES (?, -1, ?, ?, '', ?, ?, ?)",
                (request_id,
                 ACTION_EXPIRE if final_status == REQ_STATUS_EXPIRED else ACTION_WITHDRAW,
                 actor, reason, now, json.dumps({'final_status': final_status}, ensure_ascii=False)))

            # 2. 所有 pending 节点 → skipped
            conn.execute(
                "UPDATE mt_approval_nodes SET status='skipped', action='skipped', "
                "decided_at=? WHERE request_id=? AND (status IS NULL OR status='pending' OR status='')",
                (now, request_id))

            # 3. 终态
            if final_status == REQ_STATUS_WITHDRAWN:
                conn.execute(
                    "UPDATE mt_approval_requests SET status='withdrawn', final_decision='withdrawn', "
                    "decided_by=?, decided_at=?, withdrawn_by=?, withdrawn_at=?, "
                    "updated_at=? WHERE request_id=?",
                    (actor, now, actor, now, now, request_id))
            elif final_status == REQ_STATUS_EXPIRED:
                conn.execute(
                    "UPDATE mt_approval_requests SET status='expired', final_decision='expired', "
                    "decided_by=?, decided_at=?, expired_at=?, "
                    "updated_at=? WHERE request_id=?",
                    (actor, now, now, now, request_id))
            else:
                conn.execute("ROLLBACK")
                return {'ok': False, 'msg': f'unknown_final_status_{final_status}'}

            conn.execute("COMMIT")
            return {'ok': True, 'request_id': request_id, 'final_status': final_status}
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
