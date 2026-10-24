#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中心↔AI 联动关系引擎 (sys_center_relation)
============================================
flow_unified_ops_20261023 · 各中心及各 AI 之间的联动和关系适配

能力:
  ① bind_once   : 10 技能包中心 × ai_employees 自动匹配绑定 (specialties 关键词,
                   每中心 4 名主责 + 1 名 EigenFlux 外聘顾问) → mt_center_ai_binding
  ② notify_once : 中心认领任务 (DISPATCHED 1h 内) → 给绑定 AI 写 comm 消息
                   (CENTER_NOTIFY, 24h 幂等) — 认领即广播, 联动可审计
  ③ report_once : 关系健康盘点 → mt_maintenance_log 留痕
守护: loop 300s + launchd com.mtscos.center-relation
"""
from __future__ import annotations
import json
import os
import sys
import time

import sqlite3

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_DIR = os.environ.get('MTSCOS_PID_DIR', os.path.join(
    FA_DIR, '..', '_runtime', 'pids'))
DAEMON_NAME = 'sys_center_relation'
POLL_SECS = 300

DDL = """
CREATE TABLE IF NOT EXISTS mt_center_ai_binding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_code TEXT NOT NULL,
    center_name TEXT,
    ai_employee_code TEXT,
    ai_name TEXT,
    link_role TEXT DEFAULT 'member',
    contractor_id INTEGER,
    contractor_name TEXT,
    status TEXT DEFAULT 'ACTIVE',
    bound_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(center_code, ai_employee_code)
)"""


def _connect():
    conn = sqlite3.connect(os.path.join(FA_DIR, 'database', 'app.db'), timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_table(conn) -> None:
    conn.execute(DDL)
    conn.commit()


# 中心 → 匹配关键词 (specialties/名称 LIKE)
CENTER_KEYS = {
    '综合调度中心': ['调度', '运维', '系统'],
    'AI 研究院': ['AI', '算法', '研究', '推理'],
    '教育题库中心': ['教育', '题库', '教学', 'K12'],
    '安全防护中心': ['安全', '防护', '漏洞', '渗透'],
    '法律合规中心': ['法律', '合规', '法务', '政法'],
    '数据治理中心': ['数据', '治理', '清洗', '分析'],
    '知识脑库中心': ['脑库', '知识', '向量', '投喂'],
    '基础设施中心': ['基础设施', '运维', 'daemon', '部署'],
    '测试质量中心': ['测试', '质量', 'QA', '巡检'],
    '对外协作中心': ['协作', '外交', 'EigenFlux', '社区'],
}


def bind_once(conn) -> dict:
    stats = {'centers': 0, 'new_binds': 0, 'new_contractors': 0}
    skills = conn.execute(
        "SELECT rowid, IFNULL(skill_name,''), IFNULL(skill_id,skill_name) "
        "FROM mt_task_hall_skills ORDER BY rowid").fetchall()
    stats['centers'] = len(skills)
    for srow, name, code in skills:
        keys = CENTER_KEYS.get(name) or [name[:2]]
        # 匹配员工: specialties/capabilities/description LIKE 任一关键词
        like = ' OR '.join(
            "IFNULL(specialties,'') LIKE ? OR IFNULL(capabilities,'') LIKE ? "
            "OR IFNULL(description,'') LIKE ?" for _ in keys)
        args: list = []
        for k in keys:
            args += [f'%{k}%'] * 3
        rows = conn.execute(
            f"SELECT employee_code, IFNULL(name,'') FROM ai_employees "
            f"WHERE IFNULL(status,'')='active' AND ({like}) LIMIT 4", args).fetchall()
        if not rows:  # 兜底: 任取 4 名活跃员工保证每中心有人
            rows = conn.execute(
                "SELECT employee_code, IFNULL(name,'') FROM ai_employees "
                "WHERE IFNULL(status,'')='active' ORDER BY RANDOM() LIMIT 4").fetchall()
        for ecode, ename in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_center_ai_binding (center_code, center_name, "
                "ai_employee_code, ai_name, link_role) VALUES (?,?,?,?, 'member')",
                (code, name, ecode, ename))
            stats['new_binds'] += cur.rowcount
        # 外聘顾问: 承包商按技能就近分配 (rowid 取模)
        ct = conn.execute(
            "SELECT rowid, IFNULL(name,'') FROM mt_task_hall_contractors "
            "WHERE availability='available' ORDER BY rowid").fetchall()
        if ct:
            cid, cname = ct[srow % len(ct)]
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_center_ai_binding (center_code, center_name, "
                "contractor_id, contractor_name, link_role) VALUES (?,?,?,?, 'advisor')",
                (code, name, cid, cname))
            stats['new_contractors'] += cur.rowcount
    conn.commit()
    return stats


def notify_once(conn, hours: float = 1.0) -> dict:
    """认领任务 → 绑定 AI comm 广播 (24h 同任务幂等)."""
    stats = {'claimed': 0, 'notified': 0}
    tasks = conn.execute(
        "SELECT task_id, IFNULL(title,''), IFNULL(assigned_center,'') "
        "FROM mt_lab_task_hall WHERE status IN ('DISPATCHED','CENTER_COMPLETE') "
        "AND updated_at>datetime('now','localtime',?) LIMIT 20",
        (f'-{int(hours*3600)} seconds',)).fetchall()
    stats['claimed'] = len(tasks)
    for tid, title, center in tasks:
        # 幂等: 同任务已通知过则跳过
        dup = conn.execute(
            "SELECT count(*) FROM eigenflux_comm_messages WHERE message_type='CENTER_NOTIFY' "
            "AND content LIKE ?", (f'%[{tid}]%',)).fetchone()[0]
        if dup:
            continue
        bnds = conn.execute(
            "SELECT IFNULL(ai_name,''), IFNULL(contractor_name,'') FROM mt_center_ai_binding "
            "WHERE center_name=? AND status='ACTIVE'", (center,)).fetchall() \
            if center else conn.execute(
            "SELECT IFNULL(ai_name,''), IFNULL(contractor_name,'') FROM mt_center_ai_binding "
            "WHERE status='ACTIVE' ORDER BY RANDOM() LIMIT 4").fetchall()
        names = [a or b for a, b in bnds][:5]
        if not names:
            continue
        content = (f'[{tid}] 中心「{center or "综合调度中心"}」认领任务「{title[:40]}」— '
                   f'联动组: {",".join(names)} (relation 引擎自动广播)')
        try:
            conn.execute(
                "INSERT INTO eigenflux_comm_messages (from_id, to_id, content, message_type) "
                "VALUES ('sys_center_relation', 'center_group', ?, 'CENTER_NOTIFY')",
                (content,))
            stats['notified'] += 1
        except Exception:
            pass
    conn.commit()
    return stats


def report_once(conn) -> dict:
    stats = bind_once(conn)
    stats.update(notify_once(conn))
    try:
        total = conn.execute("SELECT count(*) FROM mt_center_ai_binding").fetchone()[0]
        centers = conn.execute(
            "SELECT count(DISTINCT center_code) FROM mt_center_ai_binding").fetchone()[0]
        conn.execute(
            "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
            "VALUES ('CENTER_RELATION', ?, 'RELATION_REPORT', ?)",
            (DAEMON_NAME, json.dumps(
                {'bindings': total, 'centers': centers, **stats}, ensure_ascii=False)))
        conn.commit()
    except Exception:
        pass
    return stats


def _heartbeat():
    try:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?,?,?,?, datetime('now','localtime'), datetime('now','localtime'))",
            (DAEMON_NAME, '中心↔AI 联动关系引擎 (自动绑定/认领广播/关系盘点) 300s',
             os.getpid()))
        conn.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
            "pid=?, status='RUNNING' WHERE process_name=?", (os.getpid(), DAEMON_NAME))
        conn.commit()
        conn.close()
    except Exception:
        pass


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'loop'
    conn = _connect()
    try:
        ensure_table(conn)
        if cmd == 'bind':
            print(json.dumps(bind_once(conn), ensure_ascii=False))
        elif cmd == 'report':
            print(json.dumps(report_once(conn), ensure_ascii=False))
        else:  # loop
            print(f'[{DAEMON_NAME}] 中心↔AI 联动守护 pid={os.getpid()} '
                  f'poll={POLL_SECS}s', flush=True)
            while True:
                try:
                    r = report_once(conn)
                    if r.get('new_binds') or r.get('notified'):
                        print(f'[{DAEMON_NAME}] {r}', flush=True)
                except Exception as e:
                    sys.stderr.write(f'[{DAEMON_NAME}] {e}\n')
                _heartbeat()
                time.sleep(POLL_SECS)
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
