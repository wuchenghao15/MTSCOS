#!/usr/bin/env python3
"""
仙女座统一审批引擎 (v26.0 SHIM) — ApprovalBuilder 薄封装
=========================================================
本文件已降级为薄 shim, 核心逻辑全部迁入 engines/approval/ 包.
所有旧调用点 (gray_release / routes / smart_mount / test_engines.py) 零改动.

SHIM 契约:
  - DB_PATH / assess_risk / build_approval_nodes / _get_next_approver
    → 直接重导出 policy + chains 里的同名函数
  - SCHEMA → 空字符串 (新包 ensure_schema 管 schema 迁移)
  - ApprovalEngine(db_path=...) → 内部持有 ApprovalService 实例,
    所有方法委托过去; self.db 持有一个懒加载的 sqlite3.Connection
    (仅为了兼容 test_engines.py 末尾的 eng.db.close())
  - auto_approve_low_risk() → 委托 svc.auto_pass_all()
  - submit_wenquxing_for_approval → 委托 svc.submit() + SAFE_CATEGORIES
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════
# 重导出新包的权威源
# ═══════════════════════════════════════════════════════════
from engines.approval.policy import (
    assess_risk,         # 1:1 行为兼容旧引擎 8 条断言
    ROLE_CHAIN,
)
from engines.approval.chains import build_nodes as _build_nodes
from engines.approval.service import ApprovalService as _ApprovalService
# [unused] from engines.approval.db import DB_PATH as _REAL_DB_PATH, ensure_schema


# ═══════════════════════════════════════════════════════════
# 旧 API 保持
# ═══════════════════════════════════════════════════════════
DB_PATH = _REAL_DB_PATH
SCHEMA = ""   # 空串 — 新包 ensure_schema 管

_SAFE_CATS = {'wenquxing', 'parent_feedback', 'homework', 'course_content', 'exam'}


def build_approval_nodes(
    category: str,
    initiator_role: str,
    risk_level: str | None = None,
    **kwargs: Any,
) -> list[dict]:
    """旧 API 兼容: 底层是 chains.build_nodes (mode/quorum/新扩展键已包含)."""
    return _build_nodes(category, initiator_role, risk_level, **kwargs)


def _get_next_approver(role: str) -> str | None:
    """旧 API — 底层是 policy.ROLE_CHAIN"""
    return ROLE_CHAIN.get((role or '').lower())


# ═══════════════════════════════════════════════════════════
# ApprovalEngine — 薄 shim (test_engines.py 断言兼容)
# ═══════════════════════════════════════════════════════════
class ApprovalEngine:
    def __init__(self, db_path: Path | str = DB_PATH):
        self._path = Path(db_path)
        self._svc = _ApprovalService(db_path=self._path)
        # 兼容旧实例级长连接 (仅为了 eng.db.close())
        self.db = sqlite3.connect(str(self._path), timeout=10)
        self.db.row_factory = sqlite3.Row

    # ── submit ──
    def submit(
        self,
        category: str,
        initiator: str,
        initiator_role: str,
        subject_id: str = '',
        subject_snapshot: str | dict = '',
        **kwargs: Any,
    ) -> str:
        """旧 API — 委托 ApprovalService.submit, subject_hint 透传给风险评估."""
        return self._svc.submit(
            category=category,
            initiator=initiator,
            initiator_role=initiator_role,
            subject_id=subject_id,
            subject_snapshot=subject_snapshot,
            subject_hint=str(kwargs.get('subject_hint', '') or ''),
        )

    # ── action ──
    def action(
        self,
        request_id: str,
        node_index: int,
        action: str,
        actor: str,
        actor_role: str,
        notes: str = '',
    ) -> dict:
        """旧 API — 委托 ApprovalService.action.
        旧引擎行为: 任何人可 approve/reject 任意待审批节点 (无 current_node 顺序约束).
        这里先 auto_pass 前置可自动节点推进 current_node, 再在新 current_node 上执行目标动作.
        如果目标 node_index 已被 auto_pass 过掉, 自动 fallback 到新的首个 pending 节点.
        """
        # 推进前置节点 (approve/reject 才需要, delegate 不用)
        if action in ('approve', 'reject'):
            self._svc.auto_pass_for(request_id)

        # 确认目标节点现在是否还可操作, 否则 fallback
        user = {'username': actor, 'user_role': actor_role or ''}
        req = self._svc.get(request_id)
        target_ni = node_index
        if req:
            target_node = next((n for n in req['nodes'] if n['node_index'] == node_index), None)
            if target_node:
                cur_st = (target_node.get('status') or target_node.get('action') or 'pending').lower()
                if cur_st not in ('pending', '', None):
                    # 目标节点已定, fallback 到新 current_node
                    new_cur = req.get('current_node')
                    if new_cur is not None and action in ('approve', 'reject'):
                        target_ni = new_cur

        res = self._svc.action(request_id, target_ni, action, user, notes)
        if not res.get('ok') and action == 'reject':
            # reject 最后兜底: 直接调 state_machine (绕过 authz, 保持旧引擎宽松行为)
            from engines.approval.state_machine import apply_node_action
            try:
                res2 = apply_node_action(
                    request_id, target_ni, 'reject',
                    actor=actor, actor_role=actor_role or '',
                    notes=notes, db_path=self._path)
                if res2.get('ok'):
                    return res2
            except Exception:
                pass
        return res

    # ── 仙女座自动审批 ──
    def auto_approve_low_risk(self) -> list[dict]:
        """旧 API — 扫所有 pending 单自动审批. 返回 [{request_id, reason}]
        test_engines.py 断言 rid1 auto 后 approved, rid2 rule_change 不被全过."""
        out: list[dict] = []
        passes = self._svc.auto_pass_all()
        # 按 request_id 去重 reason
        seen_rid = {}
        for p in passes:
            rid = p['request_id']
            if rid not in seen_rid:
                seen_rid[rid] = p['reason']
                out.append({'request_id': rid, 'reason': p['reason']})
        return out

    # ── list_pending ──
    def list_pending(self, role: str = '', limit: int = 20) -> list[dict]:
        """旧 API — 按角色查待审批. 退化为原生 SQL (新 svc.list_todo 依赖 user 字典)."""
        from engines.approval.db import get_conn
        if role:
            with get_conn(self._path) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT r.* FROM mt_approval_requests r "
                    "JOIN mt_approval_nodes n ON n.request_id=r.request_id "
                    "WHERE r.status='pending' "
                    "  AND (n.status IS NULL OR n.status='pending' OR n.action IS NULL) "
                    "  AND n.node_type != 'initiate' "
                    "  AND n.approver_role=? "
                    "ORDER BY r.created_at DESC LIMIT ?",
                    (role, limit)).fetchall()
            return [dict(r) for r in rows]
        user = {'username': '_legacy', 'user_role': 'admin'}
        return self._svc.list_all(user, limit=limit)

    def _legacy_conn(self, db_path):
        from engines.approval.db import get_conn
        return get_conn(db_path)

    # ── get_request ──
    def get_request(self, request_id: str) -> dict | None:
        """旧 API — 委托 ApprovalService.get"""
        return self._svc.get(request_id)

    # ── close (保留) ──
    def close(self):
        try:
            self.db.close()
        except Exception:
            pass


def _legacy_conn(db_path):
    """list_pending 旧路径专用短连接."""
    from engines.approval.db import get_conn
    return get_conn(db_path)


# ═══════════════════════════════════════════════════════════
# 便捷入口 (旧 API)
# ═══════════════════════════════════════════════════════════
def submit_wenquxing_for_approval(
    task_id: str,
    initiator: str,
    initiator_role: str,
    final_text: str = '',
) -> str:
    """文曲星产出自动进审批链 — 委托 svc.submit(category='wenquxing')"""
    svc = _ApprovalService()
    subject_hint = final_text[:500] if final_text else ''
    return svc.submit(
        category='wenquxing',
        subject_id=task_id,
        initiator=initiator,
        initiator_role=initiator_role,
        subject_snapshot={'task_id': task_id, 'preview': subject_hint[:200]},
        subject_hint=subject_hint,
    )


# ── CLI ──
if __name__ == "__main__":
    import argparse, sys, json
    ap = argparse.ArgumentParser(description="📋 仙女座统一审批引擎 (v26.0 shim)")
    ap.add_argument('--submit', nargs='*', help="category initiator role [subject_id]")
    ap.add_argument('--build', nargs='+', metavar='ARG', help="构建审批链预览: cat role [hint...]")
    ap.add_argument('--auto', action='store_true', help="自动审批 low-risk")
    ap.add_argument('--pending', metavar='ROLE', help="列出待审批 (按角色)")
    ap.add_argument('--risk', nargs='+', metavar='ARG', help="风险评估: cat role [hint...]")
    ap.add_argument('--show', metavar='REQUEST_ID')
    args = ap.parse_args()

    if args.build:
        cat, role = args.build[0], args.build[1]
        hint = ' '.join(args.build[2:]) if len(args.build) > 2 else ''
        risk = assess_risk(cat, role, hint)
        nodes = build_approval_nodes(cat, role, risk, subject_hint=hint)
        print(f"📋 审批链预览 risk={risk} nodes={len(nodes)} cat={cat} role={role}")
        for n in nodes:
            print(f"  [{n['node_index']}] {n['node_type']:14s} → {n.get('approver_role','-'):14s} "
                  f"auto={n.get('auto_pass','-')} mode={n.get('mode','-')} quorum={n.get('quorum','-')} | {n.get('description','')}")

    elif args.risk:
        cat, role = args.risk[0], args.risk[1]
        hint = ' '.join(args.risk[2:]) if len(args.risk) > 2 else ''
        print(f"risk={assess_risk(cat, role, hint)}")

    elif args.submit:
        cat, init, role = args.submit[:3]
        sid = args.submit[3] if len(args.submit) > 3 else ''
        rid = ApprovalEngine().submit(cat, init, role, sid)
        print(f"✅ submitted request_id={rid}")

    elif args.auto:
        res = ApprovalEngine().auto_approve_low_risk()
        print(f"✅ 仙女座自动审批: {len(res)} 个通过")
        for r in res: print(f"  {r['request_id']}: {r['reason']}")

    elif args.pending:
        p = ApprovalEngine().list_pending(args.pending)
        print(f"📋 待审批 ({args.pending}): {len(p)} 个")
        for r in p: print(f"  {r['request_id']} [{r['category']}] risk={r.get('risk_level')} init={r.get('initiator')}")

    elif args.show:
        d = ApprovalEngine().get_request(args.show)
        print(json.dumps(d, ensure_ascii=False, indent=2) if d else "not found")

    else:
        ap.print_help()
