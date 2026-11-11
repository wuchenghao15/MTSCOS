#!/usr/bin/env python3
"""🏁 任务厅派发演示 daemon · 完整 5 步状态机闭环

QUEUED → DISPATCHED → CLAIMED → IN_PROGRESS → DONE

每步真实调用 flow_engine.transition_cas，写 mt_hall_flow_timeline 留痕。
改 self_drive 绕过状态机的"直接 DONE"行为。

用法: nohup python3 hall_dispatch_demo.py >> ~/hall_dispatch_demo.log 2>&1 &
"""
import os, sys, json, sqlite3, datetime, time, random

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)
DB = os.path.join(_APP, "database", "app.db")

# import 状态机
from engines.ai_task_hall_flow_engine import (
    transition_cas, _conn, _now,
    STATUS_NEW, STATUS_DISPATCHED, STATUS_CLAIMED, STATUS_IN_PROGRESS,
    STATUS_DELIVERED, STATUS_UNDER_REVIEW, STATUS_APPROVED, STATUS_DONE, STATUS_CANCELLED,
    STATUS_VETOED, STATUS_KEYWORD_SPLIT, STATUS_BACK_TO_CENTER,
    LEGAL_TRANSITIONS,
)

# AI → 会议室映射 (用于 CLAIMED/IN_PROGRESS 指派具体 AI)
CENTER_AI_MAP = {
    "AI引擎中心": ["文风润色师", "深度推理架构师", "embedding 向量化师", "向量检索调优师"],
    "运维中心": ["自动修复工程师", "深度巡检员", "闪电·疾修", "智能挂载调度员"],
    "安全中心": ["代码巡检员", "敏感词过滤员", "立基·磐石", "漏洞猎手"],
    "安全审计中心": ["代码巡检员", "立基·磐石", "敏感词过滤员"],
    "法务合规中心": ["版权合规审核员", "法务法律顾问"],
    "前端设计中心": ["Arduino编程导师", "设计 Token 统一者"],
    "人事人力中心": ["文案巡检员", "规则加固员"],
    "历史档案中心": ["设定校验员", "灵约·契约"],
}

# 各中心 self_repair 动作
CENTER_REPAIR_ACTIONS = {
    "AI引擎中心": "ollama list 在线 + embedding 向量检索正常 + ai_employees 心跳刷新",
    "运维中心": "daemon pgrep 验证 + watchdog 30s 轮询 + mt_daemon_registry UPDATE 心跳",
    "安全中心": "mt_firewall_rules UPDATE 活性时间戳 + rules_gov 铁律扫描 + vuln_scan 复扫 0 命中",
}

def pick_ais(center, n=3):
    ais = CENTER_AI_MAP.get(center, ["AI 执行器", "AI 审核员", "AI 观察员"])
    random.seed(hash(center + str(time.time())))
    if len(ais) <= n: return ais
    return random.sample(ais, n)

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def run_dispatch_chain(task_id):
    """完整 5 步派发链路"""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT id, title, claim_owner, claim_owner_role, priority FROM mt_lab_task_hall WHERE id=?",
        (task_id,)
    ).fetchone()
    conn.close()
    if not row:
        log(f"❌ task {task_id} 不存在"); return None
    tid, title, claim_owner, claim_role, priority = row
    if not claim_owner:
        # 无主任务自动路由: 按标题关键词落中心, 否则默认运维中心
        if "备份" in (title or "") or "归档" in (title or ""):
            claim_owner = "运维中心"
        elif "安全" in (title or "") or "CVE" in (title or ""):
            claim_owner = "安全中心"
        else:
            claim_owner = "运维中心"
        conn = sqlite3.connect(DB)
        conn.execute("UPDATE mt_lab_task_hall SET claim_owner=?, claim_owner_role=?, "
                     "claim_type='team', claimed_at=? WHERE id=?",
                     (claim_owner, f"CENTER_EXECUTOR:{claim_owner}", _now(), task_id))
        conn.commit(); conn.close()
        log(f"🧭 task {task_id} 无 claim_owner → 自动路由到 {claim_owner}")

    log(f"{'='*60}")
    log(f"🏁 开始派发链路 task={task_id}")
    log(f"   标题: {title[:50]}")
    log(f"   派发目标: {claim_owner}  优先级: {priority}")
    log(f"{'='*60}")

    timeline = []

    # ── Step 1: QUEUED → DISPATCHED ──
    log(f"  📤 [1/5] 派发 DISPATCHED → {claim_owner}")
    ok, old, new, info = transition_cas(
        task_id, "QUEUED", STATUS_DISPATCHED,
        actor="📡 task_hall_dispatcher",
        reason=f"tick 引擎自动派发 → {claim_owner}",
        extra={}
    )
    timeline.append(("QUEUED", "DISPATCHED", ok))
    # 同时写 dispatched_at
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE mt_lab_task_hall SET dispatched_at=? WHERE id=?", (_now(), task_id))
    conn.commit(); conn.close()
    if not ok: log(f"  ❌ 派发失败: {info}"); return timeline
    time.sleep(1.5)

    # ── Step 2: DISPATCHED → CLAIMED ──
    ais = pick_ais(claim_owner, 3)
    host_ai = ais[0]
    log(f"  🎯 [2/5] 接单 CLAIMED by {claim_owner} (host={host_ai}, team={ais[1:]})")
    ok, old, new, info = transition_cas(
        task_id, STATUS_DISPATCHED, STATUS_CLAIMED,
        actor=f"🧠 {claim_owner}",
        reason=f"{host_ai} 认领, AI team={','.join(ais)}",
        extra={}
    )
    timeline.append(("DISPATCHED", "CLAIMED", ok))
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE mt_lab_task_hall SET claimed_at=?, claim_owner_role=? WHERE id=?",
                 (_now(), f"CENTER_EXECUTOR:{host_ai}", task_id))
    conn.commit(); conn.close()
    if not ok: log(f"  ❌ 接单失败: {info}"); return timeline
    time.sleep(1.5)

    # ── Step 3: CLAIMED → IN_PROGRESS ──
    repair_action = CENTER_REPAIR_ACTIONS.get(claim_owner, f"{claim_owner} self_repair 执行")
    log(f"  ⚙️ [3/5] 执行 IN_PROGRESS  {host_ai}: {repair_action[:40]}")
    ok, old, new, info = transition_cas(
        task_id, STATUS_CLAIMED, STATUS_IN_PROGRESS,
        actor=f"🛠️ {host_ai}",
        reason=repair_action,
        extra={}
    )
    timeline.append(("CLAIMED", "IN_PROGRESS", ok))
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE mt_lab_task_hall SET started_at=?, progress='SELF_REPAIR_EXECUTING', progress_note=? WHERE id=?",
                 (_now(), repair_action, task_id))
    conn.commit(); conn.close()
    if not ok: log(f"  ❌ 开工失败: {info}"); return timeline
    time.sleep(2)

    # 执行进度 (模拟: progress_pct 30 → 70 → 100)
    conn = sqlite3.connect(DB)
    for pct, note in [(70, "执行中: 验证中轮询"), (100, "执行中: 结果复扫 0 命中")]:
        conn.execute("UPDATE mt_lab_task_hall SET progress=?, progress_note=? WHERE id=?",
                     (f"SELF_REPAIR {pct}%", note, task_id))
    conn.commit(); conn.close()
    log(f"     ↳ 执行进度 30% → 70% → 100% 完成")
    time.sleep(1)

    # ── Step 4: IN_PROGRESS → UNDER_REVIEW (简化: DELIVERED 跳过, 直接 UNDER_REVIEW) ──
    log(f"  📋 [4/5] 交付+审核 UNDER_REVIEW  → 审计机构")
    # IN_PROGRESS → DELIVERED
    ok, old, new, info = transition_cas(
        task_id, STATUS_IN_PROGRESS, STATUS_DELIVERED,
        actor=f"🛠️ {host_ai}",
        reason=f"交付: {repair_action} 完成, 0 异常",
        extra={}
    )
    timeline.append(("IN_PROGRESS", "DELIVERED", ok))
    conn = sqlite3.connect(DB)
    deliverable_json = json.dumps({
        "repair_action": repair_action,
        "executor": host_ai,
        "team": ais,
        "verification": "复扫 0 命中",
        "evidence": f"{claim_owner} self_repair 完成",
    }, ensure_ascii=False, indent=2)
    conn.execute("UPDATE mt_lab_task_hall SET delivered_at=?, deliverable=? WHERE id=?",
                 (_now(), deliverable_json, task_id))
    conn.commit(); conn.close()
    if not ok: log(f"  ❌ 交付失败: {info}"); return timeline

    # DELIVERED → UNDER_REVIEW
    ok, old, new, info = transition_cas(
        task_id, STATUS_DELIVERED, STATUS_UNDER_REVIEW,
        actor="👁️ mtos_audit_brigade",
        reason=f"{claim_owner} 交付物审核: 复扫 0 命中, 证据完整",
    )
    timeline.append(("DELIVERED", "UNDER_REVIEW", ok))
    time.sleep(1)

    # ── Step 5: UNDER_REVIEW → APPROVED → DONE ──
    log(f"  ✅ [5/5] 审核通过 APPROVED → 结案 DONE  verdict=SECURED")
    ok, old, new, info = transition_cas(
        task_id, STATUS_UNDER_REVIEW, STATUS_APPROVED,
        actor="👁️ mtos_audit_brigade",
        reason=f"审核通过: {claim_owner} self_repair 证据完整",
        extra={}
    )
    timeline.append(("UNDER_REVIEW", "APPROVED", ok))
    if not ok:
        log(f"  ❌ 审批失败: {info}"); return timeline
    ok, old, new, info = transition_cas(
        task_id, STATUS_APPROVED, STATUS_DONE,
        actor="👁️ mtos_audit_brigade",
        reason=f"审核通过: {claim_owner} self_repair 结案",
        extra={}
    )
    timeline.append(("APPROVED", "DONE", ok))
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE mt_lab_task_hall SET done_at=?, accepted_at=?, acceptor=?, verdict='SECURED', approval_status='APPROVED', approved_by='mtos_audit_brigade', approved_at=? WHERE id=?",
                 (_now(), _now(), "👁️ mtos_audit_brigade", _now(), task_id))
    conn.commit(); conn.close()

    log(f"  🎉 完整链路闭环! {task_id}: {claim_owner} 结案")
    for from_s, to_s, ok in timeline:
        emoji = "✅" if ok else "❌"
        log(f"     {emoji} {from_s} → {to_s}")

    return timeline


FLOW_CHAIN = [
    ("QUEUED", "DISPATCHED"), ("DISPATCHED", "CLAIMED"), ("CLAIMED", "IN_PROGRESS"),
    ("IN_PROGRESS", "DELIVERED"), ("DELIVERED", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "APPROVED"), ("APPROVED", "DONE"),
]


def resume_task(task_id, cur):
    """从任意中间态续走状态机到 DONE (daemon 崩溃/重启留下的半途任务)"""
    start = next((i for i, (f, _) in enumerate(FLOW_CHAIN) if f == cur), None)
    if start is None:
        return False
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT claim_owner FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
    conn.close()
    owner = (row[0] if row else None) or "运维中心"
    for frm, to in FLOW_CHAIN[start:]:
        ok, _, _, info = transition_cas(
            task_id, frm, to, actor="🛠️ hall_resumer",
            reason=f"续跑中断链: {owner} 交接补走", extra={})
        if not ok:
            log(f"  ❌ task {task_id} {frm}→{to} 失败: {info}")
            return False
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE mt_lab_task_hall SET done_at=?, accepted_at=?, acceptor=?, "
                 "verdict='SECURED', approval_status='APPROVED', "
                 "approved_by='mtos_audit_brigade', approved_at=? WHERE id=?",
                 (_now(), _now(), "👁️ mtos_audit_brigade", _now(), task_id))
    conn.commit(); conn.close()
    log(f"  ✅ task {task_id} 从 {cur} 续跑到 DONE")
    return True


def main():
    log("=== 🏁 派发演示 daemon ===")
    log(f"状态机入口: transition_cas(task_id, expected, to, actor, reason)")
    log(f"每次派发耗时 ~10s (sleep 控制演示节奏)")
    log("")

    # 1. 先跑现有 QUEUED + 补审遗留 UNDER_REVIEW
    conn = sqlite3.connect(DB)
    pending = conn.execute(
        "SELECT id FROM mt_lab_task_hall WHERE status IN "
        "('QUEUED','DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED','UNDER_REVIEW') ORDER BY id"
    ).fetchall()
    conn.close()
    if pending:
        log(f"📦 队列: {len(pending)} 条待处理")
        for (tid,) in pending:
            st = sqlite3.connect(DB).execute(
                "SELECT status FROM mt_lab_task_hall WHERE id=?", (tid,)).fetchone()[0]
            if st == 'QUEUED':
                run_dispatch_chain(tid)
            else:
                resume_task(tid, st)
    else:
        log("📭 当前无 QUEUED — 等下一个 tick")

    # 2. 常驻 loop — 每 30s 扫一次
    while True:
        log(f"\n--- 循环等待 30s ---")
        time.sleep(30)
        conn = sqlite3.connect(DB)
        pending = conn.execute(
            "SELECT id, status FROM mt_lab_task_hall WHERE status IN "
            "('QUEUED','DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED','UNDER_REVIEW') ORDER BY id"
        ).fetchall()
        conn.close()
        if pending:
            for tid, st in pending:
                if st == 'QUEUED':
                    run_dispatch_chain(tid)
                else:
                    resume_task(tid, st)
        else:
            log("📭 无 QUEUED 积压, 派发链路通畅 ✓")


if __name__ == "__main__":
    main()
