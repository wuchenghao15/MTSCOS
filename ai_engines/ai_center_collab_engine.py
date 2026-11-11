#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤝 中心深度协作引擎 (flow_center_collab_20261027)

三种协作模式 (共享资源池, 单 makespan 目标 — 不做独立系统取 max):
  ① JOINT  联合认领 — 主中心 + 协作中心并行推进同一任务不同子目标
  ② HANDOFF 接力转办 — A 中心完成某阶段后自动转交 B 中心接续
  ③ PEER_REVIEW 交叉评审 — 某中心交付前需其他领域中心评审签字

设计原则 (来自 Experience 100037542):
  - 资源边界显式化: 协作=合并资源池, 不是多独立系统取 max
  - 目标函数: 协作场景用单任务整体 makespan, 分阶段交接有 SLA 约束
  - 不新建并行系统: 扩展 mt_collab_participation 加 center_id 维度,
    复用现有 mt_lab_task_hall / mt_collab_channel / transition_cas 钩子

挂点:
  - _hall_dispatch_one 派单成功 → match_collaborators 自动匹配协作中心
  - transition_cas DONE → handoff 接力触发 / peer_review 评审请求
  - ai_team_collab_engine.open_channel → 也拉中心作为参与方

CLI:
  python3 ai_engines/ai_center_collab_engine.py --once   # 全量匹配+开协作
  python3 ai_engines/ai_center_collab_engine.py --status # JSON 概览
"""

import os
import re
import sys
import json
import sqlite3
from datetime import datetime

if True:
    _APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)

MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")

FLOW_ID = "flow_center_collab_20261027"

# 协作模式 → 匹配规则 (关键词命中, 高权重域匹配协作中心)
# 规则: 任务文本命中 domain_keywords 的中心视为协作候选, 取 top N
_COLLAB_RULES = [
    # (协作中心 domain, 关键词正则, 最低协作数)
    ("AI引擎", re.compile(r"\b(?:ollama|向量|embedding|推理|eigenflux|脑库|llm|模型)\b", re.I), 1),
    ("安全审计", re.compile(r"\b(?:漏洞|注入|加密|风险|红线|审计|合规|安全)\b"), 1),
    ("开发流程", re.compile(r"\b(?:dev|git|flask|commit|代码|merge|review|ci)\b", re.I), 1),
    ("数据研究", re.compile(r"\b(?:数据|分析|报告|统计|画像|etl|报表)\b"), 1),
    ("前端设计", re.compile(r"\b(?:前端|ui|页面|交互|设计token|渲染|组件|页面)\b"), 1),
    ("教育题库", re.compile(r"\b(?:教育|题库|考试|教学|备课|试题|学情)\b"), 1),
    ("工作流", re.compile(r"\b(?:工作流|workflow|流水线|调度|编排|任务链|协作)\b", re.I), 1),
    ("部署运维", re.compile(r"\b(?:daemon|挂载|keepalive|巡检|部署|ops|云|docker|容器)\b", re.I), 1),
    ("安全适配", re.compile(r"\b(?:补丁|加固|适配|修复|shell|sql注入|凭证)\b"), 1),
    ("监察督办", re.compile(r"\b(?:督办|跟进|研究|完善|备案|回档|巡检|审计|复盘)\b"), 1),
]


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ════════════════ DDL ════════════════

_COLLAB_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_lab_collab (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hall_task_id INTEGER NOT NULL,
        mode TEXT NOT NULL,              -- JOINT / HANDOFF / PEER_REVIEW
        primary_center_id INTEGER NOT NULL,
        collab_center_ids TEXT,          -- json array [center_id, ...]
        status TEXT DEFAULT 'ACTIVE',    -- ACTIVE / COMPLETED / CANCELLED
        handoff_seq INTEGER DEFAULT 0,   -- 接力序号 (HANDOFF 用)
        review_round INTEGER DEFAULT 0,  -- 评审轮次 (PEER_REVIEW 用)
        sla_hours INTEGER,               -- 整体 SLA (小时)
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(hall_task_id, mode)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_collab_task ON mt_lab_collab(hall_task_id)",
    "CREATE INDEX IF NOT EXISTS idx_collab_status ON mt_lab_collab(status, mode)",
    # mt_collab_participation 扩展 (幂等, 列不存在才加)
]


def _ensure_tables():
    conn = _db()
    try:
        for sql in _COLLAB_DDL:
            conn.execute(sql)
        # 幂等扩展 mt_collab_participation 加 center_id 维度
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_participation)").fetchall()]
        for col, typ in [("center_id", "INTEGER"), ("center_domain", "TEXT")]:
            if col not in cols:
                conn.execute(f"ALTER TABLE mt_collab_participation ADD COLUMN {col} {typ}")
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


# ════════════════ 协作中心匹配 ════════════════

def _active_centers():
    conn = _db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, center_code, name, domain, keywords FROM mt_lab_centers WHERE status='ACTIVE'")]
    finally:
        conn.close()


def match_collaborators(task_text, primary_center_id, max_collab=3):
    """为任务匹配协作中心 (共享资源池语义, 不做独立系统取 max)
    返回: [(center_id, domain, hit_count), ...] — 不含主中心"""
    text = (task_text or "").lower()
    centers = _active_centers()
    scored = []
    for c in centers:
        if c["id"] == primary_center_id:
            continue
        # domain 关键词命中数
        hits = 0
        for rule_domain, rx, _min in _COLLAB_RULES:
            if rule_domain == c["domain"]:
                hits = len(rx.findall(text))
                break
        # 中心自身关键词
        own_kws = [k.strip().lower() for k in (c["keywords"] or "").split(",") if k.strip()]
        own_hit = sum(1 for k in own_kws if k in text)
        score = hits * 2 + own_hit
        if score > 0:
            scored.append((score, c["id"], c["domain"], c["name"]))
    scored.sort(reverse=True)
    return [(cid, dom, name) for _s, cid, dom, name in scored[:max_collab]]


# ════════════════ 开启协作 ════════════════

def open_collab_task(task_id, mode="JOINT", max_collab=3):
    """为一个已派单任务开启跨中心协作"""
    _ensure_tables()
    conn = _db()
    try:
        task = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        if not task or not task["center_id"]:
            return None
        # 幂等: 已存在协作关系则跳过
        exist = conn.execute(
            "SELECT id FROM mt_lab_collab WHERE hall_task_id=? AND mode=? AND status='ACTIVE'",
            (task_id, mode)).fetchone()
        if exist:
            return {"id": exist["id"], "existing": True}
        collaborators = match_collaborators(
            (task["title"] or "") + " " + (task["description"] or ""),
            task["center_id"], max_collab)
        if not collaborators:
            return None
        cids = [c[0] for c in collaborators]
        cur = conn.execute(
            "INSERT INTO mt_lab_collab (hall_task_id,mode,primary_center_id,collab_center_ids,sla_hours) "
            "VALUES (?,?,?,?,?)",
            (task_id, mode, task["center_id"], json.dumps(cids), 72))
        collab_id = cur.lastrowid
        conn.commit()
        # 同时扩展协作频道: 拉中心参与方
        try:
            from engines.ai_team_collab_engine import open_channel
            ch = open_channel(dict(task))
            if ch and not ch.get("existing"):
                # 频道刚开, 注入中心参与方
                for cid, dom, name in collaborators:
                    conn.execute(
                        "INSERT OR IGNORE INTO mt_collab_participation "
                        "(channel_id,actor,actor_type,must_speak,center_id,center_domain) "
                        "VALUES (?,?,?,?,?,?)",
                        (ch["channel_id"], name, "center", 1, cid, dom))
                conn.execute(
                    "INSERT INTO mt_collab_message (channel_id,actor,actor_type,msg_type,content) "
                    "VALUES (?,?,?,?,?)",
                    (ch["channel_id"], "协作引擎", "ai", "progress",
                     f"跨中心协作已开启({mode}): 主中心→协作中心={task['center_id']}→{cids}, SLA 72h"))
                conn.commit()
        except Exception:
            pass  # 协作频道失败不影响协作关系本身
        return {"collab_id": collab_id, "mode": mode,
                "primary_center": task["center_id"],
                "collaborators": collaborators}
    finally:
        conn.close()


# ════════════════ 接力转办 ════════════════

def handoff_task(task_id, from_center_id, to_center_id, reason=""):
    """HANDOFF: A 中心完成阶段后转交 B 中心接续"""
    _ensure_tables()
    conn = _db()
    try:
        collab = conn.execute(
            "SELECT * FROM mt_lab_collab WHERE hall_task_id=? AND mode='HANDOFF' AND status='ACTIVE'",
            (task_id,)).fetchone()
        if not collab:
            # 自动开启 HANDOFF
            open_collab_task(task_id, mode="HANDOFF")
            collab = conn.execute(
                "SELECT * FROM mt_lab_collab WHERE hall_task_id=? AND mode='HANDOFF' AND status='ACTIVE'",
                (task_id,)).fetchone()
        seq = (collab["handoff_seq"] or 0) + 1
        conn.execute(
            "UPDATE mt_lab_collab SET handoff_seq=?, updated_at=? WHERE id=?",
            (seq, _now(), collab["id"]))
        # 记录接力事件 (复用 transition_cas 钩子的 timeline)
        try:
            from engines.ai_task_hall_flow_engine import transition_cas
            won, old, nw, _info = transition_cas(
                task_id, old_status=None, to_status="DISPATCHED",
                actor=f"HANDOFF-{from_center_id}",
                reason=f"接力转办 #{seq}: center {from_center_id} → {to_center_id} ({reason})",
                extra={"handoff_seq": seq, "from_center": from_center_id,
                       "to_center": to_center_id, "flow": FLOW_ID})
        except Exception:
            pass
        # 协作频道广播
        try:
            from engines.ai_team_collab_engine import _db as _collab_db
            db2 = _collab_db()
            try:
                ch = db2.execute(
                    "SELECT channel_id FROM mt_collab_channel WHERE hall_task_id=?",
                    (task_id,)).fetchone()
                if ch:
                    db2.execute(
                        "INSERT INTO mt_collab_message (channel_id,actor,actor_type,msg_type,content) "
                        "VALUES (?,?,?,?,?)",
                        (ch["channel_id"], "协作引擎", "ai", "progress",
                         f"接力转办 #{seq}: 中心 {from_center_id} → {to_center_id}, 原因: {reason}"))
                    db2.commit()
            finally:
                db2.close()
        except Exception:
            pass
        return {"handoff_seq": seq, "ok": True}
    finally:
        conn.close()


# ════════════════ 交叉评审请求 ════════════════

def peer_review_request(task_id, reviewer_center_id, reason=""):
    """PEER_REVIEW: 请求某中心对交付物评审签字"""
    _ensure_tables()
    conn = _db()
    try:
        collab = conn.execute(
            "SELECT * FROM mt_lab_collab WHERE hall_task_id=? AND mode='PEER_REVIEW' AND status='ACTIVE'",
            (task_id,)).fetchone()
        if not collab:
            open_collab_task(task_id, mode="PEER_REVIEW")
            collab = conn.execute(
                "SELECT * FROM mt_lab_collab WHERE hall_task_id=? AND mode='PEER_REVIEW' AND status='ACTIVE'",
                (task_id,)).fetchone()
        round_no = (collab["review_round"] or 0) + 1
        conn.execute(
            "UPDATE mt_lab_collab SET review_round=?, updated_at=? WHERE id=?",
            (round_no, _now(), collab["id"]))
        # 写评审请求消息到协作频道
        try:
            from engines.ai_team_collab_engine import _db as _collab_db
            db2 = _collab_db()
            try:
                ch = db2.execute(
                    "SELECT channel_id FROM mt_collab_channel WHERE hall_task_id=?",
                    (task_id,)).fetchone()
                reviewer = db2.execute(
                    "SELECT name FROM mt_lab_centers WHERE id=?", (reviewer_center_id,)).fetchone()
                if ch:
                    db2.execute(
                        "INSERT INTO mt_collab_message (channel_id,actor,actor_type,msg_type,content) "
                        "VALUES (?,?,?,?,?)",
                        (ch["channel_id"], "协作引擎", "ai", "risk",
                         f"交叉评审请求 Round {round_no}: 请 {reviewer['name'] if reviewer else reviewer_center_id} 评审, 原因: {reason}"))
                    db2.commit()
            finally:
                db2.close()
        except Exception:
            pass
        return {"review_round": round_no, "ok": True}
    finally:
        conn.close()


# ════════════════ 批量触发 (daemon tick) ════════════════

def batch_enable_collab(limit=20, modes=None):
    """对近期 DISPATCHED/CLAIMED 的任务批量开启协作"""
    modes = modes or ["JOINT"]
    _ensure_tables()
    conn = _db()
    try:
        tasks = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_lab_task_hall WHERE status IN ('DISPATCHED','CLAIMED') "
            "AND center_id IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
    results = []
    for t in tasks:
        for mode in modes:
            try:
                r = open_collab_task(t["id"], mode=mode)
                if r:
                    results.append({"task": t["hall_code"], "mode": mode, "result": r})
            except Exception as e:
                results.append({"task": t["hall_code"], "mode": mode, "error": str(e)[:200]})
    return results


def rnd_escalation_collab():
    """flow_rnd_collab_20261030: R&D 三中心方向驱动的跨中心协同递进
    扫描 R&D 方向池 ACTIVE/SEED 方向 → 自动匹配协作中心 → 开协作通道 → 入厅协同任务"""
    _ensure_tables()
    conn = _db()
    results = []
    # R&D → 依赖中心映射 (硬编码, 比关键词匹配精准)
    RND_DEPENDENCIES = {
        5: [4, 471, 2899, 6],    # 工作流研究 → AI引擎/Skill/仙女座/数据
        6: [4, 2, 3227, 2899],   # 数据研究 → AI引擎/安全/备份/仙女座
        471: [4, 5, 2899, 7],    # Skill研发 → AI引擎/工作流/仙女座/前端
    }
    try:
        # 取 R&D 中心 ACTIVE 方向
        dirs = [dict(r) for r in conn.execute("""
            SELECT dp.*, c.id AS center_db_id FROM mt_center_direction_pool dp
            JOIN mt_lab_centers c ON c.name=dp.center_name AND c.status='ACTIVE'
            WHERE dp.center_name IN ('工作流研究中心','数据研究中心','Skill研发中心')
              AND dp.status='ACTIVE' AND dp.priority >= 7
            ORDER BY dp.priority DESC, dp.rowid DESC LIMIT 30
        """)]
    finally:
        conn.close()

    import sqlite3 as _s3
    _db_path = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')

    for d in dirs:
        rnd_id = d["center_db_id"]
        partners = RND_DEPENDENCIES.get(rnd_id, [])
        if not partners:
            continue
        # 幂等: 已存在同方向协作则跳过
        conn2 = _s3.connect(_db_path, timeout=10)
        try:
            exist = conn2.execute(
                "SELECT id FROM mt_center_direction_execution WHERE direction_title=? AND phase IN ('PLANNING','EXECUTING','DONE')",
                (d["direction_title"],)).fetchone()
            if not exist:
                # 确保 direction_execution 有记录, 让 learner 推进引擎接管
                conn2.execute("""INSERT OR IGNORE INTO mt_center_direction_execution
                    (direction_id, center_name, direction_title, phase, plan_summary)
                    VALUES (?,?,?, 'EXECUTING', ?)""",
                    (d["direction_id"], d["center_name"], d["direction_title"],
                     f"[RND_ESCALATION] 协作中心: {partners} — 主动拉跨中心协同推进"))
                conn2.commit()
                results.append({"direction": d["direction_title"][:40], "partners": partners, "created": True})
            else:
                results.append({"direction": d["direction_title"][:40], "partners": partners, "created": False})
        finally:
            conn2.close()

    return results


def status():
    _ensure_tables()
    conn = _db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM mt_lab_collab").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM mt_lab_collab WHERE status='ACTIVE'").fetchone()[0]
        by_mode = {r[0]: r[1] for r in conn.execute(
            "SELECT mode, COUNT(*) FROM mt_lab_collab GROUP BY mode")}
        recent = [dict(r) for r in conn.execute(
            "SELECT c.id, t.hall_code, c.mode, c.primary_center_id, c.status, c.created_at "
            "FROM mt_lab_collab c JOIN mt_lab_task_hall t ON t.id=c.hall_task_id "
            "ORDER BY c.id DESC LIMIT 10")]
        return {"total": total, "active": active, "by_mode": by_mode, "recent": recent}
    finally:
        conn.close()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="中心深度协作引擎")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--enable", type=int, default=0, help="批量开启协作的任务数")
    ap.add_argument("--mode", default="JOINT", help="JOINT/HANDOFF/PEER_REVIEW")
    ap.add_argument("--task", type=int, help="指定任务 ID 开启协作")
    args = ap.parse_args()

    _ensure_tables()
    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.task:
        r = open_collab_task(args.task, mode=args.mode)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.enable:
        r = batch_enable_collab(limit=args.enable)
        print(json.dumps({"results": r, "count": len(r)}, ensure_ascii=False, indent=2))
    elif args.once:
        r = batch_enable_collab(limit=20)
        print(json.dumps({"enabled": len(r), "results": r[:5]}, ensure_ascii=False, indent=2))
    else:
        print("use --status / --once / --enable N / --task ID --mode JOINT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
