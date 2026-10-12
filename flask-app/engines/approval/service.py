"""
service.py — ApprovalService 全部业务方法
==========================================
门面层: 把 db + policy + chains + authz + state_machine 串起来.
路由层 (P2) 只调本类, 禁止直接 import 低层模块.

所有方法签名:
  - submit(category, initiator, initiator_role, ...) -> request_id
  - action(request_id, node_index, act, user_dict, notes) -> dict
  - delegate(request_id, node_index, delegatee, reason, user_dict) -> dict
  - withdraw(request_id, user_dict, reason) -> dict
  - add_cc(request_id, emails_or_usernames, user_dict) -> dict
  - list_todo(user_dict, ...) -> list[dict]
  - list_by_initiator(user_dict, ...) -> list[dict]
  - list_cc(user_dict, ...) -> list[dict]
  - get(request_id) -> dict | None
  - stats(user_dict) -> dict
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from .db import get_conn, db_retry, ensure_schema
from .policy import (
    assess_risk, sla_for,
    REQ_STATUS_PENDING, NODE_STATUS_PENDING,
    ACTION_SUBMIT,
)


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
from .chains import build_nodes
from .authz import can_act, is_sa
from .state_machine import apply_node_action, finalize_request, _now


def _sla_due_at(risk: str) -> str | None:
    sla = sla_for(risk)
    hours = sla.get('sla_hours')
    if not hours:
        return None
    return (datetime.now() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')


def _current_node_from_nodes(nodes: list) -> int:
    """首个人工待审批节点, 否则首个 initiate"""
    for n in nodes:
        if n['node_type'] != 'initiate':
            return n['node_index']
    return 0


class ApprovalService:
    """所有审批业务方法. 实例化后自动 ensure_schema."""

    def __init__(self, db_path: Any = None):
        self.db_path = db_path
        ensure_schema(db_path)

    # ──────────────────────────────────────────────────────────────
    # 提交
    # ──────────────────────────────────────────────────────────────
    def submit(
        self,
        category: str,
        initiator: str,
        initiator_role: str,
        subject_id: str = '',
        subject_snapshot: Any = '',
        *,
        title: str = '',
        mode: str = 'single',          # single / countersign / or_sign
        priority: str = 'normal',      # low / normal / high / urgent
        cc: list[str] | str | None = None,
        callback_key: str = '',
        flow_id: str = '',
        risk_level: str | None = None,
        sla_hours: int | None = None,
        vikey_required: bool = False,
        **kwargs,
    ) -> str:
        risk = risk_level or assess_risk(category, initiator_role, str(kwargs.get('subject_hint', '') or ''))
        nodes = build_nodes(category, initiator_role, risk, **kwargs)
        request_id = f"appr_{uuid.uuid4().hex[:12]}"
        snapshot_json = json.dumps(
            subject_snapshot if isinstance(subject_snapshot, (dict, list)) else {},
            ensure_ascii=False)
        cc_list = cc if isinstance(cc, list) else ([cc] if cc else [])
        cc_json = json.dumps(cc_list, ensure_ascii=False)
        due_at = _sla_due_at(risk) if sla_hours is None else (
            datetime.now() + timedelta(hours=sla_hours)).strftime('%Y-%m-%d %H:%M:%S')

        now = _now()
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO mt_approval_requests "
                    "(request_id, category, subject_id, subject_snapshot, "
                    "initiator, initiator_role, risk_level, status, "
                    "title, mode, priority, cc_json, due_at, "
                    "callback_key, flow_id, current_node, schema_v2, "
                    "created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 1,?,?)",
                    (request_id, category, subject_id, snapshot_json,
                     initiator, initiator_role, risk, REQ_STATUS_PENDING,
                     title or category, mode, priority, cc_json, due_at,
                     callback_key, flow_id,
                     _current_node_from_nodes(nodes),
                     now, now))

                for n in nodes:
                    # 节点自带的 mode 优先 (policy 里 countersign 节点),
                    # 全局 mode 只作 initiate/ai_review 的默认
                    nn_mode = n.get('mode') or (
                        'single' if n['node_type'] in ('initiate', 'ai_review') else mode)
                    conn.execute(
                        "INSERT INTO mt_approval_nodes "
                        "(request_id, node_index, node_type, approver_role, auto_pass, "
                        "notes, mode, quorum, approvers_json, vikey_required, "
                        "status, action, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?, 'pending', 'pending', ?)",
                        (request_id, n['node_index'], n['node_type'],
                         n.get('approver_role', ''),
                         1 if n.get('auto_pass') else 0,
                         n.get('description', ''),
                         nn_mode, n.get('quorum', 1),
                         n.get('approvers_json', '[]'),
                         1 if (vikey_required or n.get('vikey_required')) else 0,
                         now))

                conn.execute(
                    "INSERT INTO mt_approval_actions "
                    "(request_id, node_index, action, actor, actor_role, notes, acted_at) "
                    "VALUES (?, 0, ?, ?, ?, ?, ?)",
                    (request_id, ACTION_SUBMIT, initiator, initiator_role or '',
                     '提交审批', now))

                # 推进 current_node 到首个非 initiate 节点, 设 activated_at / due_at
                first_pending = next(
                    (n['node_index'] for n in nodes if n['node_type'] != 'initiate'), 0)
                if first_pending is not None:
                    conn.execute(
                        "UPDATE mt_approval_requests SET current_node=? WHERE request_id=?",
                        (first_pending, request_id))
                    conn.execute(
                        "UPDATE mt_approval_nodes SET activated_at=?, due_at=? "
                        "WHERE request_id=? AND node_index=?",
                        (now, due_at, request_id, first_pending))
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return request_id

    # ──────────────────────────────────────────────────────────────
    # 审批动作 (approve / reject / auto_pass / ai_review)
    # ──────────────────────────────────────────────────────────────
    def action(
        self,
        request_id: str,
        node_index: int,
        act: str,
        user_dict: dict,
        notes: str = '',
        detail: dict | None = None,
    ) -> dict:
        req = self.get(request_id)
        if not req:
            return {'ok': False, 'msg': 'request_not_found'}
        node = next((n for n in req['nodes'] if n['node_index'] == node_index), None)
        if not node:
            return {'ok': False, 'msg': 'node_not_found'}
        allowed, code = can_act(user_dict, req, node, act, db_path=self.db_path)
        if not allowed:
            return {'ok': False, 'msg': f'auth:{code}'}
        return apply_node_action(
            request_id, node_index, act,
            actor=user_dict['username'],
            actor_role=user_dict.get('user_role') or user_dict.get('role') or '',
            notes=notes,
            detail=detail,
            db_path=self.db_path,
        )

    # ──────────────────────────────────────────────────────────────
    # 自动审批 (安全类目: initiate + 安全 ai_review + auto_pass 字段)
    # ──────────────────────────────────────────────────────────────
    SAFE_CATEGORIES = frozenset({
        'wenquxing', 'parent_feedback', 'homework', 'course_content', 'exam',
    })

    def auto_pass_for(self, request_id: str) -> list[dict]:
        """给某单自动过掉可自动的节点 (按 node_index 顺序扫所有 pending 节点)."""
        req = self.get(request_id)
        if not req or req['status'] != 'pending':
            return []
        category = (req['category'] or '').lower()
        initiator_role = req.get('initiator_role') or ''
        safe_cat = category in self.SAFE_CATEGORIES
        results: list[dict] = []
        # 按 node_index 顺序扫所有 pending 节点, 逐个尝试自动过
        all_pending = sorted(
            [n for n in req['nodes']
             if (n.get('status') or n.get('action') or 'pending').lower() in ('pending', '')
             and n['node_type'] not in ('role_approver',)],
            key=lambda x: x['node_index'],
        )
        # 如果有 role_approver 节点 auto_pass=True 也要扫 (student wenquxing teacher 场景)
        all_pending += sorted(
            [n for n in req['nodes']
             if (n.get('status') or n.get('action') or 'pending').lower() in ('pending', '')
             and n['node_type'] == 'role_approver'
             and (bool(n.get('auto_pass')) or (
                 n.get('approver_role') == 'teacher'
                 and initiator_role == 'student'
                 and category == 'wenquxing'
             ))],
            key=lambda x: x['node_index'],
        )
        seen = set()
        for node in all_pending:
            ni = node['node_index']
            if ni in seen:
                continue
            seen.add(ni)
            ntype = node['node_type']
            reason = None
            if ntype == 'initiate':
                reason = '发起人自动通过'
            elif ntype == 'ai_review' and safe_cat:
                reason = f'仙女座 AI 风控通过 · category={category} 为安全类'
            elif ntype == 'ai_review':
                # 非安全类目也允许 AI 自动过 (daemon tick 里 LLM 已判定 auto_pass)
                reason = f'仙女座 AI 风控通过 · category={category}'
            elif bool(node.get('auto_pass')):
                reason = 'auto_pass=True 规则命中'
            elif (ntype == 'role_approver'
                  and node.get('approver_role') == 'teacher'
                  and initiator_role == 'student'
                  and category == 'wenquxing'):
                reason = 'teacher 自动确认 student 文曲星产出'
            if not reason:
                continue
            res = apply_node_action(
                request_id, ni, 'auto_pass',
                actor='andromeda', actor_role='ai',
                notes=f'仙女座自动审批 · {reason}',
                db_path=self.db_path,
            )
            if res.get('ok'):
                results.append({'node_index': ni, 'reason': reason})
            # 如果整单已经终态了, 停
            req_check = self.get(request_id)
            if req_check and req_check['status'] != 'pending':
                break
        return results

    def auto_pass_all(self, limit: int = 50) -> list[dict]:
        """扫所有 pending 请求自动审批. 返回 [{request_id, reason}]."""
        out: list[dict] = []
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT request_id FROM mt_approval_requests "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                (limit,)).fetchall()
        for r in rows:
            rid = r['request_id']
            passes = self.auto_pass_for(rid)
            for p in passes:
                out.append({'request_id': rid, 'node_index': p['node_index'],
                            'reason': p['reason']})
        return out

    # ──────────────────────────────────────────────────────────────
    # 委托 / 撤回 / 抄收
    # ──────────────────────────────────────────────────────────────
    def delegate(
        self,
        request_id: str,
        node_index: int,
        delegatee: str,
        reason: str,
        user_dict: dict,
    ) -> dict:
        """把某节点委托给他人 — 更新 node.delegated_to + approvers_json,
        插 action=delegate 流水, 同时 mt_approval_delegations 加/更一条."""
        req = self.get(request_id)
        if not req:
            return {'ok': False, 'msg': 'request_not_found'}
        node = next((n for n in req['nodes'] if n['node_index'] == node_index), None)
        if not node:
            return {'ok': False, 'msg': 'node_not_found'}
        username = user_dict['username']
        # 允许发起人/当前审批人委托
        if username != req['initiator'] and username != node.get('_current_approver') \
                and node.get('approver_role') != (user_dict.get('user_role') or '') \
                and not is_sa(user_dict):
            return {'ok': False, 'msg': 'no_permission_to_delegate'}

        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                approvers = _safe_load_json(node.get('approvers_json'), [])
                if delegatee not in approvers:
                    approvers.append(delegatee)
                conn.execute(
                    "UPDATE mt_approval_nodes SET delegated_to=?, delegate_reason=?, "
                    "approvers_json=?, notes=? WHERE request_id=? AND node_index=?",
                    (delegatee, reason, json.dumps(approvers), reason,
                     request_id, node_index))
                # 委托链
                chain = _safe_load_json(req.get('delegate_chain_json'), [])
                chain.append(delegatee)
                conn.execute(
                    "UPDATE mt_approval_requests SET delegate_chain_json=? WHERE request_id=?",
                    (json.dumps(chain), request_id))
                conn.execute(
                    "INSERT INTO mt_approval_actions "
                    "(request_id, node_index, action, actor, actor_role, notes, acted_at) "
                    "VALUES (?,?, 'delegate',?,?,?,?)",
                    (request_id, node_index, username,
                     user_dict.get('user_role') or '', reason, _now()))
                # 委托规则表 (方便后续 authz._has_effective_delegation)
                try:
                    conn.execute(
                        "INSERT INTO mt_approval_delegations "
                        "(delegator, delegatee, note, start_at, enabled, created_at) "
                        "VALUES (?,?,?,?, 1, ?)",
                        (username, delegatee, reason, _now(), _now()))
                except Exception:
                    pass
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return {'ok': True, 'request_id': request_id, 'node_index': node_index,
                'delegated_to': delegatee}

    def withdraw(self, request_id: str, user_dict: dict, reason: str = '') -> dict:
        req = self.get(request_id)
        if not req:
            return {'ok': False, 'msg': 'request_not_found'}
        username = user_dict['username']
        if username != req['initiator'] and not is_sa(user_dict):
            return {'ok': False, 'msg': 'only_initiator_can_withdraw'}
        return finalize_request(
            request_id, 'withdrawn', username, reason or '发起人撤回',
            db_path=self.db_path)

    def add_cc(self, request_id: str, targets: list[str] | str, user_dict: dict) -> dict:
        req = self.get(request_id)
        if not req:
            return {'ok': False, 'msg': 'request_not_found'}
        username = user_dict['username']
        # 发起人 / SA / 当前审批链上的人 才能加抄收
        can_cc = (username == req['initiator'] or is_sa(user_dict)
                  or any(n.get('approver_role') == (user_dict.get('user_role') or '')
                         for n in req['nodes']))
        if not can_cc:
            return {'ok': False, 'msg': 'no_permission_to_cc'}

        target_list = targets if isinstance(targets, list) else [targets]
        with get_conn(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cc = _safe_load_json(req.get('cc_json'), [])
            added = []
            for t in target_list:
                if t and t not in cc:
                    cc.append(t)
                    added.append(t)
            conn.execute(
                "UPDATE mt_approval_requests SET cc_json=? WHERE request_id=?",
                (json.dumps(cc, ensure_ascii=False), request_id))
            for t in added:
                conn.execute(
                    "INSERT INTO mt_approval_actions "
                    "(request_id, node_index, action, actor, actor_role, notes, acted_at) "
                    "VALUES (?, -1, 'cc', ?, ?, ?, ?)",
                    (request_id, username,
                     user_dict.get('user_role') or '', f'抄送给 {t}', _now()))
            conn.execute("COMMIT")
        return {'ok': True, 'added': added}

    # ──────────────────────────────────────────────────────────────
    # 查询
    # ──────────────────────────────────────────────────────────────
    def get(self, request_id: str) -> dict | None:
        with get_conn(self.db_path) as conn:
            req = conn.execute(
                "SELECT * FROM mt_approval_requests WHERE request_id=?",
                (request_id,)).fetchone()
            if not req:
                return None
            nodes = conn.execute(
                "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index",
                (request_id,)).fetchall()
            actions = conn.execute(
                "SELECT * FROM mt_approval_actions WHERE request_id=? ORDER BY node_index, id",
                (request_id,)).fetchall()

        def _r(r):
            if r is None:
                return {}
            if isinstance(r, dict):
                return r
            try:
                return {k: r[k] for k in r.keys()}
            except Exception:
                return dict(r)

        d = _r(req)
        d['nodes'] = [_r(n) for n in nodes]
        d['actions'] = [_r(a) for a in actions]
        # 兼容旧 action 列双写: 新逻辑只读 status, 旧读 action
        for n in d['nodes']:
            if n.get('action') and not n.get('status'):
                n['status'] = n['action']
        return d

    def list_todo(self, user_dict: dict, limit: int = 50) -> list[dict]:
        """待我审批 — 角色匹配 + 指定人 + 委托 + 会签未满 quorum."""
        username = user_dict.get('username', '')
        role = user_dict.get('user_role') or user_dict.get('role') or ''
        is_super = is_sa(user_dict)
        out: list[dict] = []
        with get_conn(self.db_path) as conn:
            # 简单版: 角色匹配 / 指定人 / 被委托
            rows = conn.execute(
                "SELECT DISTINCT r.*, n.node_index AS _ni, n.node_type AS _nt "
                "FROM mt_approval_requests r "
                "JOIN mt_approval_nodes n ON n.request_id=r.request_id "
                "WHERE r.status='pending' "
                "  AND (n.status IS NULL OR n.status='pending') "
                "  AND n.node_type != 'initiate' "
                "ORDER BY r.created_at DESC LIMIT ?",
                (limit * 3,)).fetchall()
            for r in rows:
                d = self.get(r['request_id'])
                if not d:
                    continue
                for n in d['nodes']:
                    if n['node_type'] == 'initiate':
                        continue
                    st = (n.get('status') or n.get('action') or 'pending').lower()
                    if st not in ('pending', ''):
                        continue
                    matched = False
                    if is_super and n['approver_role'] in ('admin', 'professor', 'mentor', 'teacher', 'counselor'):
                        matched = True
                    elif n['approver_role'] == role:
                        matched = True
                    elif username in _safe_load_json(n.get('approvers_json'), []):
                        matched = True
                    elif n.get('delegated_to') == username:
                        matched = True
                    if matched:
                        brief = _row_brief(d)
                        brief['_node_index'] = n['node_index']
                        out.append(brief)
                        break
                if len(out) >= limit:
                    break
        return out

    def list_by_initiator(self, user_dict: dict, limit: int = 50) -> list[dict]:
        with get_conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM mt_approval_requests WHERE initiator=? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_dict['username'], limit)).fetchall()
        return [_row_brief(r) for r in rows]

    def list_cc(self, user_dict: dict, limit: int = 50) -> list[dict]:
        username = user_dict['username']
        out: list[dict] = []
        with get_conn(self.db_path) as conn:
            all_rows = conn.execute(
                "SELECT * FROM mt_approval_requests ORDER BY created_at DESC LIMIT ?",
                (limit * 5,)).fetchall()
        for r in all_rows:
            cc = _safe_load_json(r.get('cc_json'), [])
            if username in cc:
                out.append(_row_brief(r))
                if len(out) >= limit:
                    break
        return out

    def list_all(self, user_dict: dict, status: str = '', limit: int = 50) -> list[dict]:
        """管理员/SA 看所有单, 普通用户看自己发起/待审/抄送."""
        username = user_dict['username']
        role = user_dict.get('user_role') or ''
        with get_conn(self.db_path) as conn:
            if is_sa(user_dict) or role in ('admin', 'professor'):
                if status:
                    rows = conn.execute(
                        "SELECT * FROM mt_approval_requests WHERE status=? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (status, limit)).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM mt_approval_requests "
                        "ORDER BY created_at DESC LIMIT ?",
                        (limit,)).fetchall()
            else:
                # 普通用户: 自己发起 + 待审 + 抄送
                rows = conn.execute(
                    "SELECT * FROM mt_approval_requests "
                    "WHERE initiator=? OR cc_json LIKE ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (username, f'%{username}%', limit)).fetchall()
        return [_row_brief(r) for r in rows]

    def stats(self, user_dict: dict) -> dict:
        is_admin = is_sa(user_dict) or (user_dict.get('user_role') in ('admin', 'professor'))
        username = user_dict['username']
        with get_conn(self.db_path) as conn:
            base_q = ("SELECT status, COUNT(*) AS c FROM mt_approval_requests GROUP BY status")
            status_rows = conn.execute(base_q).fetchall()
            summary = {r['status'] or 'unknown': r['c'] for r in status_rows}

            pending = summary.get('pending', 0)
            done = summary.get('approved', 0)
            rejected = summary.get('rejected', 0)
            expired = summary.get('expired', 0)
            withdrawn = summary.get('withdrawn', 0)

            out = {
                'total': sum(summary.values()),
                'pending': pending,
                'approved': done,
                'rejected': rejected,
                'expired': expired,
                'withdrawn': withdrawn,
            }
            if is_admin:
                # admin 看板: 过期/即将过期分布
                overdue = conn.execute(
                    "SELECT COUNT(*) AS c FROM mt_approval_requests "
                    "WHERE status='pending' AND due_at IS NOT NULL AND due_at < ?",
                    (_now(),)).fetchone()['c']
                out['overdue'] = overdue
            return out


def _row_brief(r):
    if isinstance(r, dict):
        return {k: r.get(k) for k in (
            'request_id', 'category', 'subject_id', 'initiator', 'initiator_role',
            'risk_level', 'status', 'final_decision', 'current_node',
            'title', 'priority', 'mode', 'due_at', 'created_at', 'decided_at',
        )}
    try:
        return {k: r[k] for k in (
            'request_id', 'category', 'subject_id', 'initiator', 'initiator_role',
            'risk_level', 'status', 'final_decision', 'current_node',
            'title', 'priority', 'mode', 'due_at', 'created_at', 'decided_at',
        )}
    except Exception:
        return {'request_id': r['request_id'], 'status': r['status']}
