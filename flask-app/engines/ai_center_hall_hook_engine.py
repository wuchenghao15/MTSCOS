#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
各中心挂钩任务大厅自动监听引擎 (flow_center_hook_hall_20261025)
================================================================
闭环 (每 300s 一轮, 零 token):
  ① 监听   — 任务大厅 QUEUED 新任务
  ② 认领   — 复用 run_hall_auto: 按中心领域关键词+人力能力自动分配 (DISPATCHED)
  ③ 执行   — 复用 _hall_auto_execute_and_deliver: 研究任务产出结构化研究报告 (DONE)
  ④ 脑库   — 研究报告上报 mt_ai_brain_feed_log (feed_target='center_hall_hook')
  ⑤ 备案   — 备份中心备案 mt_backup_log (action='CENTER_HOOK_FILING')
  ⑥ 留痕   — mt_center_hook_log (hall_task_id UNIQUE 幂等, 防重复上报)

入口:
  python3 ai_center_hall_hook_engine.py start   — loop 模式 (keepalive/cron 拉起)
  python3 ai_center_hall_hook_engine.py once    — 单轮执行 (手动/测试)
"""
import os
import sys
import json
import time
import sqlite3
import argparse

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_center_hook_hall_20261025"
ENGINE_NAME = "ai_center_hall_hook_engine"
POLL_INTERVAL = 300          # 5min, 与 sys_rule_enforcer 同款周期
BATCH_LIMIT = 30             # 每轮认领/交付批量

_HOOK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mt_center_hook_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hall_task_id INTEGER UNIQUE,
    title TEXT,
    center TEXT,
    brain_fed INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    report_digest TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)"""


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [CENTER-HOOK] {msg}", flush=True)


def _heartbeat(status="RUNNING"):
    """daemon 注册表心跳 (自动修复引擎巡检依据; process_name 无 UNIQUE 约束 → UPDATE-else-INSERT)"""
    try:
        conn = _db()
        cur = conn.execute("""UPDATE mt_daemon_registry SET status=?, last_heartbeat=datetime('now','localtime'),
                              updated_at=datetime('now','localtime') WHERE process_name=?""",
                           (status, ENGINE_NAME))
        if cur.rowcount == 0:
            conn.execute("""INSERT INTO mt_daemon_registry (process_name, duty, status, last_heartbeat, created_at, updated_at)
                            VALUES (?, ?, ?, datetime('now','localtime'), datetime('now','localtime'), datetime('now','localtime'))""",
                         (ENGINE_NAME, "各中心挂钩任务大厅: 监听→认领→结案→脑库上报→备份备案", status))
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f"⚠️ 心跳失败: {e}")


def _baseline_skip():
    """首轮基线: 引擎启用前已 DONE 的存量任务标记跳过, 避免历史积压噪音灌脑库"""
    conn = _db()
    conn.execute(_HOOK_TABLE_SQL)
    n = conn.execute("SELECT COUNT(*) c FROM mt_center_hook_log").fetchone()["c"]
    if n == 0:
        cur = conn.execute("""INSERT OR IGNORE INTO mt_center_hook_log (hall_task_id, title, center, report_digest)
                              SELECT id, title, 'baseline', '(baseline_skip) 引擎启用前存量结案, 不追溯上报'
                              FROM mt_lab_task_hall WHERE status='DONE'""")
        conn.commit()
        _log(f"基线: 存量 DONE {cur.rowcount} 条标记跳过, 此后新结案才上报")
    conn.close()


def _report_digest(deliverable):
    """研究报告 → 摘要 (供脑库/备案)"""
    try:
        r = json.loads(deliverable) if deliverable else {}
        method = r.get("research_method", "通用执行")
        findings = "; ".join(r.get("findings", [])[:2])
        scan = r.get("scan")
        extra = f" (扫描:{scan['files']}文件/{scan['hex_colors']}硬编码)" if isinstance(scan, dict) and "files" in scan else ""
        return f"{method}{extra} | {findings}"[:500]
    except Exception:
        return (deliverable or "")[:200]


def run_once():
    """单轮闭环: 监听 → 认领 → 执行结案 → 脑库上报 → 备份备案"""
    from blueprints.daemon_skill_lab_bp import run_hall_auto, _hall_auto_execute_and_deliver

    _baseline_skip()

    # ① 监听: 大厅 QUEUED 存量
    conn = _db()
    queued = conn.execute("SELECT COUNT(*) c FROM mt_lab_task_hall WHERE status='QUEUED'").fetchone()["c"]
    conn.close()
    _log(f"监听: 大厅 QUEUED 任务 {queued} 条")

    # ② 认领: 归集+按中心领域关键词分配 (含磋商)
    dispatched = 0
    try:
        r = run_hall_auto()
        dispatched = r.get("dispatched", 0)
        _log(f"认领: 分配 {dispatched} 条")
    except Exception as e:
        _log(f"⚠️ 认领异常: {e}")

    # ③ 执行结案: 研究任务自动产出结构化研究报告 → DONE
    try:
        d = _hall_auto_execute_and_deliver(limit=BATCH_LIMIT)
        _log(f"结案: 交付 {d['executed']} → 验收 {d['auto_accepted']}")
    except Exception as e:
        _log(f"⚠️ 执行异常: {e}")

    # ④⑤ 未备案 DONE 任务 → 脑库上报 + 备份中心备案 (幂等)
    conn = _db()
    conn.execute(_HOOK_TABLE_SQL)
    fresh = conn.execute("""
        SELECT h.id, h.title, h.deliverable, c.name AS center_name
        FROM mt_lab_task_hall h
        LEFT JOIN mt_lab_centers c ON c.id = h.center_id
        WHERE h.status='DONE' AND h.id NOT IN (SELECT hall_task_id FROM mt_center_hook_log)
        ORDER BY h.id DESC LIMIT ?""", (BATCH_LIMIT,)).fetchall()
    fed = archived = 0
    for t in fresh:
        digest = _report_digest(t["deliverable"])
        center = t["center_name"] or "未归属"
        try:
            conn.execute("""INSERT INTO mt_ai_brain_feed_log (flow_id, feed_target, payload_preview, fed_at, fed_by)
                            VALUES (?, ?, ?, datetime('now','localtime'), ?)""",
                         (FLOW_ID, f"center_hall_hook:{center}", f"[{t['title']}] {digest}", ENGINE_NAME))
            fed += 1
        except Exception as e:
            _log(f"⚠️ 脑库上报失败 task={t['id']}: {e}")
        try:
            conn.execute("""INSERT INTO mt_backup_log (action, detail, ok, size_bytes, elapsed_sec, created_at)
                            VALUES ('CENTER_HOOK_FILING', ?, 1, 0, 0, datetime('now','localtime'))""",
                         (json.dumps({"hall_task_id": t["id"], "title": t["title"], "center": center,
                                      "report_digest": digest, "flow_id": FLOW_ID}, ensure_ascii=False),))
            archived += 1
        except Exception as e:
            _log(f"⚠️ 备份备案失败 task={t['id']}: {e}")
        conn.execute("""INSERT OR IGNORE INTO mt_center_hook_log (hall_task_id, title, center, brain_fed, archived, report_digest)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     (t["id"], t["title"], center, 1 if fed else 0, 1 if archived else 0, digest))
    conn.commit()
    conn.close()
    _log(f"上报: 脑库 {fed} 条 | 备份中心备案 {archived} 条")
    _heartbeat("RUNNING")
    return {"queued": queued, "dispatched": dispatched, "brain_fed": fed, "archived": archived}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="start", choices=["start", "once"])
    args = ap.parse_args()
    if args.mode == "once":
        r = run_once()
        _log(f"单轮完成: {json.dumps(r, ensure_ascii=False)}")
        return
    _log(f"引擎启动 loop 模式, 周期 {POLL_INTERVAL}s")
    _heartbeat("RUNNING")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ 轮次异常: {e}")
            _heartbeat("RUNNING")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
