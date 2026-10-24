#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轮巡队→维和部队 交接协议引擎 (flow_corps_handover_20261025)
================================================================
轮巡队 = mt_corps_squads 中 duty LIKE 'PATROL%' 的巡逻类连队 + 挂靠 AI 员工
维和部队 = 其余四类连队 (SURVEY/REPAIR/EMPOWER/RECON), 按同领域对口接管

五阶段交接协议 (一次性交接, 支持 --drill 演练):
  ① 盘点   — PATROL 连清单 + 挂靠员工 (ai_employees.squad_id) + 在途任务
  ② 任务交接 — 轮巡队名下在途任务 → 按领域改派对口非 PATROL 连 (mt_lab_task_events RECLAIM)
  ③ 能力学习 — 每个 PATROL 连的领域职责 → 对口接管连 mt_corps_empowerment 授予技能
             + 脑库投喂学习记录 (mt_ai_brain_feed_log)
  ④ 缺口上报 — 轮巡队职责 − 接管连已授技能 = 缺口 → 每缺口入任务大厅提需求
             (source='skill_gap_handover')
  ⑤ 就地解散 — 挂靠员工 is_enabled=0 + status='DISBANDED' (留痕不删数据)
             + PATROL 连 status='DISBANDED' (配额释放)

落库: mt_corps_handover_log (每轮交接全量留痕) + mt_backup_log (备案)
入口: python3 ai_corps_handover_engine.py once [--drill]
"""
import os
import sys
import json
import uuid
import time
import sqlite3
import argparse

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_corps_handover_20261025"
ENGINE_NAME = "ai_corps_handover_engine"
PATROL_PREFIX = "PATROL"        # 轮巡队连队标识 (mt_corps_squads.duty 前缀)

_HANDOVER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mt_corps_handover_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handover_id TEXT UNIQUE,
    drill INTEGER DEFAULT 0,
    from_unit TEXT,
    to_unit TEXT,
    members_found INTEGER DEFAULT 0,
    tasks_transferred INTEGER DEFAULT 0,
    skills_learned INTEGER DEFAULT 0,
    gaps_reported INTEGER DEFAULT 0,
    members_disbanded INTEGER DEFAULT 0,
    detail_json TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)"""


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [CORPS-HANDOVER] {msg}", flush=True)


def _domain_of(duty):
    """'PATROL·教辅K12' → '教辅K12'"""
    return duty.split("·", 1)[1].strip() if "·" in (duty or "") else (duty or "").strip()


def _successor_squad(conn, domain):
    """同领域非 PATROL 连 (接管方): SURVEY/REPAIR/EMPOWER/RECON 优先级"""
    for prefix in ("REPAIR", "SURVEY", "EMPOWER", "RECON"):
        row = conn.execute(
            "SELECT rowid, squad_id, name, duty FROM mt_corps_squads "
            "WHERE duty LIKE ? AND duty LIKE ? LIMIT 1",
            (prefix + "%", f"%{domain}%")).fetchone()
        if row:
            return row
    return None


def run_handover(drill=False):
    """五阶段交接: 盘点 → 任务交接 → 能力学习 → 缺口上报 → 就地解散"""
    conn = _db()
    conn.execute(_HANDOVER_TABLE_SQL)
    hid = f"handover_{uuid.uuid4().hex[:12]}"
    detail = {"squads": [], "tasks": [], "skills": [], "gaps": [], "disbanded_squads": []}

    # ── ① 盘点: 轮巡队连队 + 挂靠员工 + 在途任务 ──
    tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mt_corps_squads'").fetchone()
    if not tbl:
        _log("本库无 mt_corps_squads (开发副本无部队表) → 空交接返回")
        conn.execute(_HANDOVER_TABLE_SQL)
        conn.execute("""INSERT OR REPLACE INTO mt_corps_handover_log
                        (handover_id, drill, from_unit, to_unit, members_found)
                        VALUES (?, ?, '轮巡队(PATROL)', '维和部队', 0)""", (hid, 1 if drill else 0))
        conn.commit()
        conn.close()
        return {"handover_id": hid, "drill": drill, "patrol_squads": 0, "members": 0,
                "tasks_transferred": 0, "skills_learned": 0, "gaps_reported": 0, "members_disbanded": 0}
    patrols = conn.execute(
        "SELECT rowid, squad_id, name, duty, status FROM mt_corps_squads WHERE duty LIKE ?",
        (PATROL_PREFIX + "%",)).fetchall()
    patrol_ids = [p["squad_id"] for p in patrols]
    ph = ",".join("?" * len(patrol_ids)) if patrol_ids else "NULL"
    members = conn.execute(
        f"SELECT id, name, squad_id FROM ai_employees WHERE squad_id IN ({ph})",
        patrol_ids).fetchall() if patrol_ids else []
    _log(f"① 盘点: 轮巡队 {len(patrols)} 连, 挂靠员工 {len(members)} 人")

    # ── ② 任务交接: 在途任务按领域改派对口连 ──
    transferred = 0
    if patrol_ids:
        active = conn.execute(
            f"""SELECT DISTINCT h.id, h.title, IFNULL(h.description,'') desc
                FROM mt_lab_task_hall h
                WHERE h.status IN ('QUEUED','DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED')
                  AND (h.title LIKE '%轮巡%' OR h.description LIKE '%轮巡%'
                       OR h.claim_owner IN (SELECT IFNULL(name,'') FROM ai_employees WHERE squad_id IN ({ph})))""",
            patrol_ids).fetchall()
        for t in active:
            succ = _successor_squad(conn, _domain_of("PATROL·任务大厅"))  # 默认接管域
            # 领域匹配: 任务描述含某轮巡连领域关键词 → 该连对口接管连
            for p in patrols:
                dom = _domain_of(p["duty"])
                if dom and dom in (t["title"] + t["desc"]):
                    s = _successor_squad(conn, dom)
                    if s:
                        succ = s
                    break
            if succ and not drill:
                note = f"轮巡队解散交接: 由 {succ['duty']} 接管 (handover={hid})"
                conn.execute("""UPDATE mt_lab_task_hall SET status='QUEUED', claim_owner=NULL,
                                claim_owner_role=?, verdict=?, updated_at=datetime('now','localtime')
                                WHERE id=?""", (f"维和部队·{succ['duty']}", note, t["id"]))
                conn.execute("""INSERT INTO mt_lab_task_events (hall_task_id, event, actor, actor_role, note)
                                VALUES (?, 'RECLAIM', ?, ?, ?)""", (t["id"], ENGINE_NAME, succ["duty"], note))
            detail["tasks"].append({"task_id": t["id"], "title": t["title"],
                                    "to_squad": succ["duty"] if succ else "(无对口)"})
            transferred += 1
    _log(f"② 任务交接: {transferred} 单 → 维和部队对口连队")

    # ── ③ 能力学习: PATROL 连职责 → 对口接管连授技 + 脑库投喂 ──
    learned = 0
    for p in patrols:
        dom = _domain_of(p["duty"])
        succ = _successor_squad(conn, dom)
        skill = f"{dom}巡逻巡检"[:40]
        if succ:
            if not drill:
                conn.execute("""INSERT OR IGNORE INTO mt_corps_empowerment (squad_id, skill_name, skill_category, description, level)
                                VALUES (?, ?, 'HANDOVER', ?, 3)""",
                             (succ["squad_id"], skill, f"轮巡队解散交接继承自 {p['duty']} (handover:{hid})"))
            learned += 1
            detail["skills"].append({"from": p["duty"], "to": succ["duty"], "skill": skill})
            if not drill:
                conn.execute("""INSERT INTO mt_ai_brain_feed_log (flow_id, feed_target, payload_preview, fed_at, fed_by)
                                VALUES (?, ?, ?, datetime('now','localtime'), ?)""",
                             (FLOW_ID, "corps_handover:capability_learn",
                              f"[轮巡队交接] {p['duty']} ({p['name']}, {len(members)}人) 职能移交 {succ['duty']}: "
                              f"自动学习技能[{skill}]"[:500], ENGINE_NAME))
        detail["squads"].append({"squad_id": p["squad_id"], "name": p["name"], "duty": p["duty"],
                                 "successor": succ["duty"] if succ else "(无对口)"})
    _log(f"③ 能力学习: {learned} 项领域职责技能授予接管连 + 脑库投喂")

    # ── ④ 缺口上报: 接管连缺该领域巡逻技能 → 任务大厅需求单 ──
    gaps = 0
    have = {r[0] for r in conn.execute("SELECT DISTINCT IFNULL(skill_name,'') FROM mt_corps_empowerment").fetchall()} \
        if not drill else set()
    for item in detail["skills"]:
        if item["skill"] not in have:
            if not drill:
                conn.execute("""INSERT INTO mt_lab_task_hall (title, description, source, priority)
                                SELECT ?, ?, 'skill_gap_handover', 'HIGH' WHERE NOT EXISTS
                                (SELECT 1 FROM mt_lab_task_hall WHERE title=? AND source='skill_gap_handover')""",
                             (f"【技能缺口】{item['to']} 需继承 {item['skill']}",
                              f"轮巡队解散后由 {item['to']} 接管原 {item['from']} 职能, 需自动学习补齐巡逻巡检能力 "
                              f"(handover={hid})", f"【技能缺口】{item['to']} 需继承 {item['skill']}"))
                gaps += 1
            detail["gaps"].append(item)
    _log(f"④ 缺口上报: {gaps} 项 → 任务大厅【技能缺口】需求单")

    # ── ⑤ 就地解散: 员工释放 + 连队解散 (留痕不删) ──
    disbanded_members = 0
    if not drill and patrol_ids:
        cur = conn.execute(f"""UPDATE ai_employees SET is_enabled=0, status='DISBANDED',
                               updated_at=datetime('now','localtime')
                               WHERE squad_id IN ({ph}) AND is_enabled=1""", patrol_ids)
        disbanded_members = cur.rowcount
        for p in patrols:
            conn.execute("""UPDATE mt_corps_squads SET status='DISBANDED' WHERE squad_id=?""", (p["squad_id"],))
            detail["disbanded_squads"].append({"squad_id": p["squad_id"], "duty": p["duty"]})
    _log(f"⑤ 就地解散: 员工 {disbanded_members}/{len(members)} 人 DISBANDED (配额释放), 连队 {len(patrols)} 个 DISBANDED")

    conn.execute("""INSERT OR REPLACE INTO mt_corps_handover_log
                    (handover_id, drill, from_unit, to_unit, members_found, tasks_transferred,
                     skills_learned, gaps_reported, members_disbanded, detail_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (hid, 1 if drill else 0, f"轮巡队(PATROL×{len(patrols)})",
                  "维和部队(SURVEY/REPAIR/EMPOWER/RECON)", len(members), transferred,
                  learned, gaps, disbanded_members, json.dumps(detail, ensure_ascii=False)[:2000]))
    if not drill:
        conn.execute("""INSERT INTO mt_backup_log (action, detail, ok, size_bytes, elapsed_sec, created_at)
                        VALUES ('CORPS_HANDOVER_FILING', ?, 1, 0, 0, datetime('now','localtime'))""",
                     (json.dumps({"handover_id": hid, "patrol_squads": len(patrols),
                                  "members": len(members), "tasks": transferred, "skills": learned,
                                  "gaps": gaps, "disbanded": disbanded_members, "flow_id": FLOW_ID},
                                 ensure_ascii=False),))
    conn.commit()
    conn.close()
    return {"handover_id": hid, "drill": drill, "patrol_squads": len(patrols), "members": len(members),
            "tasks_transferred": transferred, "skills_learned": learned,
            "gaps_reported": gaps, "members_disbanded": disbanded_members}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["once"], nargs="?", default="once")
    ap.add_argument("--drill", action="store_true", help="演练模式: 只盘点不留库")
    a = ap.parse_args()
    r = run_handover(drill=a.drill)
    _log(f"交接完成: {json.dumps(r, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
