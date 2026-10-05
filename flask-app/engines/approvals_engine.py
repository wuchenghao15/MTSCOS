#!/usr/bin/env python3
"""
仙女座统一审批引擎 (v25.0) — ApprovalBuilder
===============================================

单权威源: 所有审批链节点从这里生成.
零上下文依赖: 禁止读 request/session, 所有参数显式传入.
支持: 角色→审批节点自动映射, 低风险自动通过, 多级审批, 通知.

依赖:
  - mt_approval_requests (自动建)
  - mt_approval_nodes    (自动建)
  - mt_approval_actions  (自动建)
  - routes/role_registry.py (ROLE_REGISTRY)
"""
from __future__ import annotations
import json, sqlite3, time, uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_CANDIDATES = [
    _PROJECT_ROOT / "database" / "app.db",
    _PROJECT_ROOT / "app.db",
]
DB_PATH = next((p for p in _DB_CANDIDATES if p.exists()), _DB_CANDIDATES[0])

# ═══════════════════════════════════════════════════════════
# DB Schema
# ═══════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_approval_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT UNIQUE,                -- "appr_" + uuid[:12]
    category        TEXT NOT NULL,              -- wenquxing/course_content/exam/rule_change
    subject_id      TEXT,                       -- 业务对象 ID (如 task_id/proposal_id)
    subject_snapshot TEXT,                      -- 业务对象快照 JSON
    initiator       TEXT NOT NULL,              -- 发起人 username
    initiator_role  TEXT,                       -- 发起人角色
    risk_level      TEXT DEFAULT 'medium',      -- low/medium/high/critical
    auto_passed     INTEGER DEFAULT 0,          -- 1=仙女座自动通过 (低风险)
    current_node    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'pending',     -- pending/approved/rejected/cancelled
    final_decision  TEXT,                       -- 审批通过/拒绝
    decided_by      TEXT,                       -- 最终审批人
    decided_at      TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mt_approval_nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    node_index      INTEGER NOT NULL,           -- 0-based
    node_type       TEXT NOT NULL,              -- role_approver/auto_approve/delegate
    approver_role   TEXT,                       -- 需要这个角色来批
    auto_pass       INTEGER DEFAULT 0,          -- 1=仙女座可自动过 (low-risk 规则)
    approver_name   TEXT,                       -- 实际审批人 (如果已批)
    action          TEXT,                       -- approve/reject/pending
    notes           TEXT,
    decided_at      TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(request_id) REFERENCES mt_approval_requests(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_approval_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    node_index      INTEGER,
    action          TEXT NOT NULL,               -- submit/approve/reject/delegate/auto_pass
    actor           TEXT NOT NULL,
    actor_role      TEXT,
    notes           TEXT,
    acted_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(request_id) REFERENCES mt_approval_requests(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_appr_req_status ON mt_approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_appr_req_init   ON mt_approval_requests(initiator);
CREATE INDEX IF NOT EXISTS idx_appr_req_cat    ON mt_approval_requests(category);
CREATE INDEX IF NOT EXISTS idx_appr_nodes_req  ON mt_approval_nodes(request_id);
"""


# ═══════════════════════════════════════════════════════════
# 风险评估 (零上下文依赖)
# ═══════════════════════════════════════════════════════════
def assess_risk(category: str, initiator_role: str, subject_hint: str = "") -> str:
    """风险等级自动评估 — 决定审批链长度
    返回: low / medium / high / critical
    """
    initiator_role = (initiator_role or '').lower()
    category = (category or '').lower()

    # 规则修改 → 最高级
    if category in ('rule_change', 'daemon_change', 'permission_change'):
        return 'critical'

    # 管理员发的内容 → 至少 high
    if initiator_role in ('admin', 'super_admin') and category in ('course_content', 'exam', 'publish'):
        return 'high'

    # 教授/导师发表 → high
    if initiator_role in ('professor', 'mentor') and category in ('course_content', 'research', 'thesis'):
        return 'high'

    # 学生写文曲星产出 → low (自动审批)
    if initiator_role == 'student' and category == 'wenquxing':
        # 除非写了超长篇 (hint 里有 longform 关键词, 或 hint 前 5 位是纯数字且 >=2000)
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

    # 家长提的 → low (信息查看类)
    if initiator_role == 'parent':
        return 'low'

    return 'medium'


# ═══════════════════════════════════════════════════════════
# 审批链构建器 (单权威源, 零上下文依赖)
# ═══════════════════════════════════════════════════════════
def build_approval_nodes(
    category: str,
    initiator_role: str,
    risk_level: Optional[str] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """根据发起角色+类别+风险 → 生成完整审批链节点列表.

    禁止读 request/session! 所有参数显式传入.

    返回: [
      {'node_index': 0, 'node_type': 'role_approver', 'approver_role': 'teacher', ...},
      {'node_index': 1, 'node_type': 'role_approver', 'approver_role': 'admin', ...},
    ]

    规则 (role_registry.py 同步):
      - risk=low    → 0 级 (仙女座自动通过)  或 1 级 (发起人直属上级角色)
      - risk=medium → 1-2 级 (teacher → admin)
      - risk=high   → 2-3 级 (teacher → admin → super_admin)
      - risk=critical → 3 级强制 (admin → super_admin → SA 终审)
    """
    initiator_role = (initiator_role or '').lower()
    risk = risk_level or assess_risk(category, initiator_role, str(kwargs.get('subject_hint', '')))
    category = (category or '').lower()

    nodes: List[Dict[str, Any]] = []
    idx = 0

    # ── 发起人自己的 node (发起人自动通过, 规则要求) ──
    nodes.append({
        "node_index": idx,
        "node_type": "initiate",
        "approver_role": initiator_role,
        "description": f"发起人({initiator_role})自动通过",
        "auto_pass": True,
    })
    idx += 1

    # ── 仙女座智能风控 (所有非 low 风险都过 AI 预审) ──
    if risk != 'low':
        nodes.append({
            "node_index": idx,
            "node_type": "ai_review",
            "approver_role": "andromeda",
            "description": f"仙女座 AI 风控预审 (risk={risk}, category={category})",
            "auto_pass": False,  # AI 可自动过, 但也可能打回人工
        })
        idx += 1

    # ── 按风险级生成人工审批节点 ──
    if risk == 'low':
        # low → 不生成人工节点 (全自动)
        # 例外: student 写 wenquxing → teacher 过一下
        if initiator_role == 'student' and category == 'wenquxing':
            nodes.append({
                "node_index": idx,
                "node_type": "role_approver",
                "approver_role": "teacher",
                "description": "学生文曲星产出 → 任课教师确认",
                "auto_pass": True,  # 默认 teacher 授权范围内容自动过
            })
            idx += 1

    elif risk == 'medium':
        # medium → 直属上级
        next_role = _get_next_approver(initiator_role)
        if next_role:
            nodes.append({
                "node_index": idx,
                "node_type": "role_approver",
                "approver_role": next_role,
                "description": f"直属上级 ({next_role}) 审批",
                "auto_pass": False,
            })
            idx += 1

    elif risk == 'high':
        # high → 直属上级 (非 admin) + admin
        next_role = _get_next_approver(initiator_role)
        if next_role and next_role not in ('admin', 'super_admin'):
            nodes.append({
                "node_index": idx,
                "node_type": "role_approver",
                "approver_role": next_role,
                "description": f"直属上级 ({next_role}) 审批",
                "auto_pass": False,
            })
            idx += 1
        nodes.append({
            "node_index": idx,
            "node_type": "role_approver",
            "approver_role": "admin",
            "description": "管理员审批",
            "auto_pass": False,
        })
        idx += 1

    elif risk == 'critical':
        # critical → 强制三级: role → admin → super_admin
        next_role = _get_next_approver(initiator_role)
        if next_role and next_role not in ('admin', 'super_admin'):
            nodes.append({
                "node_index": idx, "node_type": "role_approver",
                "approver_role": next_role, "description": f"直属上级 ({next_role})",
                "auto_pass": False,
            })
            idx += 1
        nodes.append({
            "node_index": idx, "node_type": "role_approver",
            "approver_role": "admin", "description": "管理员审批",
            "auto_pass": False,
        })
        idx += 1
        nodes.append({
            "node_index": idx, "node_type": "role_approver",
            "approver_role": "super_admin", "description": "SA 终审 (§14 IRON_RULE)",
            "auto_pass": False,
        })
        idx += 1

    return nodes


def _get_next_approver(role: str) -> Optional[str]:
    """角色 → 上级审批人 (硬编码, 简单稳定)"""
    chain = {
        'student': 'teacher',
        'teacher': 'admin',
        'counselor': 'admin',
        'mentor': 'professor',
        'professor': 'admin',
        'parent': 'teacher',   # 家长反馈 → 教师处理
        'admin': 'super_admin',
    }
    return chain.get(role)


# ═══════════════════════════════════════════════════════════
# Row → dict 辅助 (sqlite3.Row 兼容)
# ═══════════════════════════════════════════════════════════
def _row_to_dict(row) -> Dict:
    """sqlite3.Row → dict 安全转换"""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        try:
            return dict(row)
        except Exception:
            return {i: row[i] for i in range(len(row))}


def _rows_to_dicts(rows) -> List[Dict]:
    return [_row_to_dict(r) for r in rows]
class ApprovalEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.row_factory = sqlite3.Row  # ✅ tuple → dict-like
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ── 提交 ──
    def submit(
        self,
        category: str,
        initiator: str,
        initiator_role: str,
        subject_id: str = '',
        subject_snapshot: str | Dict = '',
        **kwargs,
    ) -> str:
        """提交一个审批申请 → 返回 request_id"""
        risk = assess_risk(category, initiator_role, str(kwargs.get('subject_hint', '')))
        nodes = build_approval_nodes(category, initiator_role, risk, **kwargs)
        request_id = f"appr_{uuid.uuid4().hex[:12]}"
        snapshot = json.dumps(subject_snapshot if isinstance(subject_snapshot, dict) else {}, ensure_ascii=False)

        c = self.db.cursor()
        c.execute(
            "INSERT INTO mt_approval_requests (request_id, category, subject_id, subject_snapshot, "
            "initiator, initiator_role, risk_level, status) VALUES (?,?,?,?,?,?,?,'pending')",
            (request_id, category, subject_id, snapshot, initiator, initiator_role, risk))

        # 插入所有节点 (含 auto_pass)
        for n in nodes:
            c.execute(
                "INSERT INTO mt_approval_nodes "
                "(request_id, node_index, node_type, approver_role, auto_pass, notes) "
                "VALUES (?,?,?,?,?,?)",
                (request_id, n['node_index'], n['node_type'],
                 n.get('approver_role', ''),
                 1 if n.get('auto_pass') else 0,
                 n.get('description', '')))

        # 记录 submit 动作
        c.execute(
            "INSERT INTO mt_approval_actions (request_id, node_index, action, actor, actor_role) "
            "VALUES (?,0,'submit',?,?)",
            (request_id, initiator, initiator_role))

        self.db.commit()
        print(f"[📋 审批] {request_id} category={category} risk={risk} "
              f"nodes={len(nodes)} initiator={initiator}({initiator_role})")
        return request_id

    # ── 审批操作 ──
    def action(self, request_id: str, node_index: int, action: str,
               actor: str, actor_role: str, notes: str = '') -> Dict:
        """approve / reject / delegate"""
        c = self.db.cursor()
        # 校验请求 + 节点
        req = c.execute(
            "SELECT * FROM mt_approval_requests WHERE request_id=?", (request_id,)).fetchone()
        if not req:
            return {'ok': False, 'msg': 'request not found'}
        nodes = c.execute(
            "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index", (request_id,)).fetchall()
        node = next((n for n in nodes if n['node_index'] == node_index), None)
        if not node:
            return {'ok': False, 'msg': f'node {node_index} not found'}
        if node['action'] not in (None, 'pending', ''):
            return {'ok': False, 'msg': f'node {node_index} already decided: {node["action"]}'}

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("UPDATE mt_approval_nodes SET action=?, approver_name=?, notes=?, decided_at=? "
                  "WHERE request_id=? AND node_index=?",
                  (action, actor, notes, now, request_id, node_index))
        c.execute("INSERT INTO mt_approval_actions (request_id, node_index, action, actor, actor_role, notes) "
                  "VALUES (?,?,?,?,?,?)",
                  (request_id, node_index, action, actor, actor_role, notes))

        # 如果是 approve 且是最后一个节点 → 整体 approved
        if action == 'approve':
            all_decided = all(
                n['action'] in ('approve', None, '', 'pending') for n in nodes)
            # 更精确: 所有非 initiate 节点都 approve
            remaining = [n for n in nodes
                        if n['node_index'] > node_index and n['node_type'] != 'initiate']
            if not remaining or all(n['action'] in ('approve',) for n in nodes):
                # 所有需要审批的节点都 approve 了
                c.execute("UPDATE mt_approval_requests SET status='approved', final_decision='approved', "
                          "decided_by=?, decided_at=?, current_node=? WHERE request_id=?",
                          (actor, now, node_index, request_id))
            else:
                # 还有后续节点, 推进 current_node
                next_pending = next(
                    (n['node_index'] for n in remaining
                     if n['action'] not in ('approve', 'reject')), None)
                if next_pending is not None:
                    c.execute("UPDATE mt_approval_requests SET current_node=? WHERE request_id=?",
                              (next_pending, request_id))

        elif action == 'reject':
            c.execute("UPDATE mt_approval_requests SET status='rejected', final_decision='rejected', "
                      "decided_by=?, decided_at=? WHERE request_id=?",
                      (actor, now, request_id))

        self.db.commit()
        return {'ok': True, 'request_id': request_id, 'node_index': node_index, 'action': action}

    # ── 仙女座全场景智能自动审批 ──
    def auto_approve_low_risk(self) -> List[Dict]:
        """扫所有 pending 请求 → 仙女座智能自动审批 (全场景, 不限 risk=low)
        自动通过条件 (AND/OR 组合):
          1. initiate 节点 → 发起人自己 (100% 自动过)
          2. ai_review 节点 → 安全 category (wenquxing/parent_feedback/homework/course_content) 自动过
          3. role_approver 节点 + auto_pass=True 字段 → 自动过
          4. role_approver: teacher → student 文曲星产出 (仙女座智能确认)
        """
        _SAFE_CATS = {'wenquxing', 'parent_feedback', 'homework', 'course_content', 'exam'}
        c = self.db.cursor()
        c.execute("SELECT * FROM mt_approval_requests WHERE status='pending' LIMIT 50")
        pending = c.fetchall()
        results = []

        for req in pending:
            rid = req['request_id']
            nodes = c.execute(
                "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index",
                (rid,)).fetchall()
            initiator_role = req['initiator_role']
            category = (req['category'] or '').lower()

            for node in nodes:
                if node['action'] in ('approve', 'reject'):
                    continue
                reason = None

                # 规则 1: 发起人自己 → 100% 自动过
                if node['node_type'] == 'initiate':
                    reason = '发起人自动通过'

                # 规则 2: AI 预审 + 安全 category → 自动过
                elif node['node_type'] == 'ai_review' and category in _SAFE_CATS:
                    reason = f'仙女座 AI 风控通过 · category={category} 为安全类'

                # 规则 3: auto_pass=True (DB 字段)
                elif bool(node['auto_pass']):
                    reason = 'auto_pass=True 规则命中'

                # 规则 4: teacher 级自动确认 student 文曲星产出
                elif (node['node_type'] == 'role_approver'
                      and node['approver_role'] == 'teacher'
                      and initiator_role == 'student'
                      and category == 'wenquxing'):
                    reason = 'teacher 自动确认 student 文曲星产出'

                if reason:
                    self.action(rid, node['node_index'], 'approve',
                                actor='andromeda', actor_role='ai',
                                notes=f'仙女座自动审批 · {reason}')
                    results.append({'request_id': rid, 'reason': reason})

        return results

    # ── 查询 ──
    def list_pending(self, role: str = '', limit: int = 20) -> List[Dict]:
        c = self.db.cursor()
        if role:
            # 查需要该角色审批的
            rows = c.execute(
                "SELECT r.* FROM mt_approval_requests r "
                "JOIN mt_approval_nodes n ON n.request_id=r.request_id "
                "WHERE r.status='pending' AND n.action IS NULL AND n.approver_role=? "
                "ORDER BY r.created_at DESC LIMIT ?",
                (role, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM mt_approval_requests ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return _rows_to_dicts(rows)

    def get_request(self, request_id: str) -> Optional[Dict]:
        c = self.db.cursor()
        req = c.execute(
            "SELECT * FROM mt_approval_requests WHERE request_id=?", (request_id,)).fetchone()
        if not req: return None
        nodes = c.execute(
            "SELECT * FROM mt_approval_nodes WHERE request_id=? ORDER BY node_index",
            (request_id,)).fetchall()
        actions = c.execute(
            "SELECT * FROM mt_approval_actions WHERE request_id=? ORDER BY node_index, id",
            (request_id,)).fetchall()
        d = _row_to_dict(req)
        d['nodes'] = _rows_to_dicts(nodes)
        d['actions'] = _rows_to_dicts(actions)
        return d


# ── 便捷入口: 文曲星产出 → 自动提交审批 ──
def submit_wenquxing_for_approval(task_id: str, initiator: str, initiator_role: str,
                                   final_text: str = '') -> str:
    """文曲星产出自动进入审批链 — 仙女座智能判断是否自动通过"""
    eng = ApprovalEngine()
    subject_hint = final_text[:500] if final_text else ''
    return eng.submit(
        category='wenquxing',
        subject_id=task_id,
        initiator=initiator,
        initiator_role=initiator_role,
        subject_snapshot={'task_id': task_id, 'preview': subject_hint[:200]},
        subject_hint=subject_hint,
    )


# ── CLI ──
if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(description="📋 仙女座统一审批引擎")
    ap.add_argument('--submit', nargs='*', help="category initiator role [subject_id]")
    ap.add_argument('--build', nargs='+', metavar='ARG', help="构建审批链预览: cat role [hint...]")
    ap.add_argument('--auto', action='store_true', help="自动审批 low-risk")
    ap.add_argument('--pending', metavar='ROLE', help="列出待审批 (按角色)")
    ap.add_argument('--risk', nargs='+', metavar='ARG', help="风险评估: cat role [hint...]")
    ap.add_argument('--show', metavar='REQUEST_ID')
    args = ap.parse_args()

    if args.build:
        if len(args.build) < 2:
            print("❌ --build 需要至少 2 个参数: cat role [hint...]")
            sys.exit(1)
        cat = args.build[0]; role = args.build[1]
        hint = ' '.join(args.build[2:]) if len(args.build) > 2 else ''
        risk = assess_risk(cat, role, hint)
        nodes = build_approval_nodes(cat, role, risk, subject_hint=hint)
        print(f"📋 审批链预览 risk={risk} nodes={len(nodes)} cat={cat} role={role}")
        for n in nodes:
            print(f"  [{n['node_index']}] {n['node_type']:14s} → {n.get('approver_role','-'):14s} "
                  f"auto={n.get('auto_pass','-')} | {n.get('description','')}")

    elif args.risk:
        if len(args.risk) < 2:
            print("❌ --risk 需要至少 2 个参数")
            sys.exit(1)
        hint = ' '.join(args.risk[2:]) if len(args.risk) > 2 else ''
        r = assess_risk(args.risk[0], args.risk[1], hint)
        print(f"risk={r}")

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
        for r in p: print(f"  {r['request_id']} [{r['category']}] risk={r['risk_level']} init={r['initiator']}")

    elif args.show:
        d = ApprovalEngine().get_request(args.show)
        print(json.dumps(d, ensure_ascii=False, indent=2) if d else "not found")

    else:
        ap.print_help()
        print("\n💡 示例:")
        print("  python3 approvals_engine.py --build wenquxing student '测试'")
        print("  python3 approvals_engine.py --build exam teacher ''")
        print("  python3 approvals_engine.py --build rule_change admin ''")
        print("  python3 approvals_engine.py --submit wenquxing wuchenghao15 super_admin wqx_xxx")
        print("  python3 approvals_engine.py --auto")
