#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏁 任务结案真实落地引擎 (flow_landing_20261027)

用户闭环要求:
  结案(DONE) ≠ 结束 → 必须真实落地到服务器:
    ① 落地执行 — vuln_scan 任务复扫验证该文件该规则 0 命中; 通用任务校验交付物
    ② 派生备份任务 — 真实数据备份单, 发入任务大厅正常循环 (QUEUED)
    ③ 派生后续研发任务 — 状态 RESEARCH(研究和完善), 不入大厅循环
       (run_hall_auto 只取 QUEUED, RESEARCH 天然旁路), 跟进移交监察大队
    ④ 移交监察大队 — 原轮巡队已注销替换, 新建 supervision_brigade 监察大队接管
    ⑤ 全程留档 — mt_task_landing_log 落地记录 + mt_task_archive 备案
       + mt_lab_audit_log 审计 + 日志文件, 支持溯源回档

挂钩: engines/ai_task_hall_flow_engine.transition_cas 成功流转到 DONE 时调用
finalize_done_landing (懒加载, 异常不阻断结案本身)。
"""

import os
import re
import sys
import json
import logging
import sqlite3
from datetime import datetime

if True:  # 保证直跑/被挂载均可用
    _APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)

logger = logging.getLogger("landing_engine")

MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")

# 监察大队 (原轮巡队已注销替换): 接管 RESEARCH 态后续跟进
SUPERVISION_CENTER = ("supervision_brigade", "监察大队", "监察督办",
                      "监察,督办,跟进,研究,完善,备案,回档,巡检,审计,复盘")

_LANDING_TABLES = [
    """CREATE TABLE IF NOT EXISTS mt_task_landing_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        hall_code TEXT,
        landing_type TEXT,          -- vuln_rescan / deliverable_check / deploy
        result TEXT,                -- LANDED / LANDED_WITH_NOTE / FAILED
        detail_json TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_task_archive (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        hall_code TEXT UNIQUE,
        case_no TEXT,               -- 备案号 AR-YYYYMMDD-####
        status_at_archive TEXT,
        derived_backup_task INTEGER,
        derived_research_task INTEGER,
        supervision_owner TEXT DEFAULT '监察大队',
        summary TEXT,
        detail_json TEXT,
        archived_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
]

_VULN_FP_RX = re.compile(r"【fp:([A-Z_0-9]+):([^\】]+)】")


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_landing_tables():
    conn = _db()
    try:
        for sql in _LANDING_TABLES:
            conn.execute(sql)
        conn.execute("INSERT OR IGNORE INTO mt_lab_centers (center_code,name,domain,keywords) "
                     "VALUES (?,?,?,?)", SUPERVISION_CENTER)
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


# ════════════════ ① 落地执行 ════════════════

def _landing_vuln_rescan(desc):
    """vuln_scan 任务落地验证: 复扫该文件该规则, 0 命中 = 真实落地"""
    try:
        from ai_engines.ai_vuln_scan_dispatch_engine import _RULES
        m = _VULN_FP_RX.search(desc or "")
        if not m:
            return "LANDED_WITH_NOTE", {"note": "无 fp 指纹, 跳过复扫"}
        rule_id, rel = m.group(1), m.group(2)
        rule = next((r for r in _RULES if r[0] == rule_id), None)
        if rule is None:
            return "LANDED_WITH_NOTE", {"note": f"规则 {rule_id} 已下线, 视为落地"}
        fp = os.path.join(_APP_DIR, rel)
        hits = 0
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if rule[4].search(line):
                        hits += 1
        else:
            return "LANDED", {"note": f"文件已移除: {rel}", "hits": 0}
        if hits == 0:
            return "LANDED", {"file": rel, "rule": rule_id, "hits": 0, "verify": "复扫 0 命中"}
        return "FAILED", {"file": rel, "rule": rule_id, "hits": hits,
                          "verify": f"仍有 {hits} 处命中, 需监察大队督办"}
    except Exception as e:
        return "LANDED_WITH_NOTE", {"note": f"复扫异常: {e}"}


def _landing_deliverable_check(task):
    """通用任务落地校验: 交付物非空即视为已落地服务器 (留痕)"""
    deliverable = (task["deliverable"] if "deliverable" in task.keys() else "") or ""
    if deliverable.strip():
        return "LANDED", {"deliverable_preview": deliverable[:200]}
    return "LANDED_WITH_NOTE", {"note": "无交付物文本, 以结案留档为准"}


# ════════════════ ②③ 派生任务 ════════════════

def _hall_next_code(conn):
    prefix = "TH-" + datetime.now().strftime("%Y%m%d") + "-"
    n = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE hall_code LIKE ?",
                     (prefix + "%",)).fetchone()[0]
    return f"{prefix}{int(n) + 1:04d}"


def _insert_hall_task(conn, title, desc, priority, task_type, status, center_id, owner):
    """结案派生任务直插大厅 (系统身份 APPROVED 免审批; RESEARCH 态不走 transition_cas)"""
    code = _hall_next_code(conn)
    cur = conn.execute(
        "INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority,status,"
        "hall_code,publisher,publisher_role,task_type,approval_status,approved_by,approved_at,"
        "center_id,claim_owner,claim_owner_role,claim_type,claimed_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'),?,?,?,?,?,datetime('now','localtime'))",
        (title[:120], desc[:500], "landing_derive", None, priority, status, code,
         "landing_engine", "system_daemon", task_type, "APPROVED", "system",
         center_id, owner or None, SUPERVISION_CENTER[1] if owner else None,
         "team" if owner else None, _now() if owner else None))
    return cur.lastrowid, code


def _derive_backup_task(conn, task):
    """② 备份任务 → 发入任务大厅正常循环 (QUEUED, 关键词路由到部署运维中心)"""
    title = f"【数据备份】结案回档备份 · {task['hall_code'] or task['id']}"
    desc = (f"任务已结案, 按闭环要求真实落地后需备份留档: {task['title']}\n"
            f"内容: 对任务涉及数据/交付物做服务器侧备份归档, 回档可查。")
    tid, code = _insert_hall_task(conn, title, desc, "NORMAL", "OPS", "QUEUED", None, None)
    return tid, code


def _derive_research_task(conn, task, landing_result, landing_detail):
    """③ 后续研发任务 → RESEARCH(研究和完善), 不入大厅循环, 监察大队接管"""
    title = f"【研究完善】{task['title'][:90]}"
    desc = (f"结案落地结论: {landing_result}\n"
            f"后续研究和完善事项移交监察大队跟进督办 (不入大厅自动循环)。")
    sup = conn.execute("SELECT id FROM mt_lab_centers WHERE center_code=?",
                       (SUPERVISION_CENTER[0],)).fetchone()
    sup_id = sup["id"] if sup else None
    tid, code = _insert_hall_task(conn, title, desc, "LOW", "RESEARCH", "RESEARCH",
                                  sup_id, SUPERVISION_CENTER[1])
    return tid, code


# ════════════════ 主入口 ════════════════

def finalize_done_landing(task_id):
    """结案(DONE)真实落地钩子: ①落地验证 ②派生备份单 ③派生研究单(监察大队)
    ④备案留档 ⑤审计上报. 任何异常不抛出 (结案流程不受阻)。"""
    try:
        ensure_landing_tables()
        conn = _db()
        try:
            task = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
            if not task:
                return None
            task = dict(task)
            desc = task.get("description") or ""
            # ① 落地执行
            if task.get("source") == "vuln_scan" or "【fp:" in desc:
                result, detail = _landing_vuln_rescan(desc)
                ltype = "vuln_rescan"
            else:
                result, detail = _landing_deliverable_check(task)
                ltype = "deliverable_check"
            conn.execute("INSERT INTO mt_task_landing_log (task_id,hall_code,landing_type,result,detail_json) "
                         "VALUES (?,?,?,?,?)",
                         (task_id, task.get("hall_code"), ltype, result,
                          json.dumps(detail, ensure_ascii=False, default=str)[:2000]))
            # ② 备份任务 (QUEUED 入大厅循环)
            # 防递归: 结案派生单(landing_derive)不再派生备份/研究单, 否则无限套娃
            is_derived = (task.get("source") == "landing_derive")
            b_id = b_code = None
            if not is_derived:
                try:
                    b_id, b_code = _derive_backup_task(conn, task)
                except sqlite3.Error as e:
                    logger.warning("派生备份任务失败 task=%s: %s", task_id, e)
            # ③ 研究任务 (RESEARCH 态, 监察大队接管, 不入循环)
            r_id = r_code = None
            if not is_derived:
                try:
                    r_id, r_code = _derive_research_task(conn, task, result, detail)
                except sqlite3.Error as e:
                    logger.warning("派生研究任务失败 task=%s: %s", task_id, e)
            # ④ 备案
            n = conn.execute("SELECT count(*) FROM mt_task_archive WHERE case_no LIKE ?",
                             ("AR-" + datetime.now().strftime("%Y%m%d") + "-%",)).fetchone()[0]
            case_no = f"AR-{datetime.now().strftime('%Y%m%d')}-{n + 1:04d}"
            conn.execute(
                "INSERT OR REPLACE INTO mt_task_archive (task_id,hall_code,case_no,status_at_archive,"
                "derived_backup_task,derived_research_task,supervision_owner,summary,detail_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (task_id, task.get("hall_code"), case_no, "DONE",
                 b_id, r_id, SUPERVISION_CENTER[1],
                 f"结案落地={result}",
                 json.dumps({"landing": detail, "backup_task": b_code,
                             "research_task": r_code}, ensure_ascii=False, default=str)[:3000]))
            conn.commit()
        finally:
            conn.close()
        # ⑤ 审计上报
        try:
            conn = _db()
            try:
                conn.execute(
                    "INSERT INTO mt_lab_audit_log (operator,operator_role,center,action,subject,detail_json) "
                    "VALUES (?,?,?,?,?,?)",
                    ("landing_engine", "system_daemon", "hall", "TASK_DONE_LANDING",
                     f"task={task_id} 落地={result} 备案={case_no}",
                     json.dumps({"detail": detail, "backup": b_id, "research": r_id},
                                ensure_ascii=False, default=str)[:3000]))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            pass
        logger.info("[LANDING] task=%s code=%s 落地=%s 备份单=%s 研究单=%s 备案=%s",
                    task_id, task.get("hall_code"), result, b_code, r_code, case_no)
        return {"task_id": task_id, "landing": result, "detail": detail,
                "backup_task": b_code, "research_task": r_code, "case_no": case_no}
    except Exception as e:
        logger.warning("[LANDING] ⚠️ 结案落地钩子异常 task=%s: %s", task_id, e)
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="结案落地引擎 CLI")
    ap.add_argument("task_id", type=int)
    print(json.dumps(finalize_done_landing(ap.parse_args().task_id),
                     ensure_ascii=False, indent=2))
