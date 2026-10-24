#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维和部队分队化 + 市场下沉引擎 (sys_corps_field)
================================================
flow_unified_ops_20261023 · 部队从单一 guard 合规三查 → 六类分队下沉市场

六类分队 (54 连按 squad_id 取模分编):
  PATROL 巡逻队   : registry 异常/FAILED daemon/心跳停摆 → 大厅抢修单
  SURVEY 调研队   : 下沉扫停滞表/空表/同步链新鲜度 → 大厅缺口单
  REPAIR 抢修队   : QUEUED 超龄任务催办 + CONTAMINATED 复检 → 大厅
  GUARD  监察队   : 合规三查 (原 guard 职能, 保留引用不重写)
  EMPOWER 赋能队  : 连队技能 vs 中心技能包对齐 → 赋能记录
  RECON  侦察队   : EigenFlux 最新情报消息 → 大厅情报单
守护: loop 600s, 每轮轮转 1-2 类分队; 全程 maintenance_log + 大厅留痕.
"""
from __future__ import annotations
import json
import os
import sys
import time

import sqlite3

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON_NAME = 'sys_corps_field'
POLL_SECS = 600
SQUAD_TYPES = ['PATROL', 'SURVEY', 'REPAIR', 'EMPOWER', 'RECON']
# GUARD 不占轮转 — dispatch 引擎 guard_once 持有


def _connect():
    conn = sqlite3.connect(os.path.join(FA_DIR, 'database', 'app.db'), timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _log(conn, action, detail):
    try:
        conn.execute(
            "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
            "VALUES ('CORPS_FIELD', ?, ?, ?)",
            (DAEMON_NAME, action, json.dumps(detail, ensure_ascii=False)))
        conn.commit()
    except Exception:
        pass


def _hall_task(conn, title, desc, prio='NORMAL', source='corps_field'):
    try:
        if conn.execute(
                "SELECT count(*) FROM mt_lab_task_hall WHERE title=? AND "
                "created_at>datetime('now','localtime','-24 hours')",
                (title,)).fetchone()[0]:
            return False
        conn.execute(
            "INSERT INTO mt_lab_task_hall (title, description, source, priority, "
            "status, created_at) VALUES (?,?,?,?,'QUEUED',datetime('now','localtime'))",
            (title, desc, source, prio))
        conn.commit()
        return True
    except Exception:
        return False


def _squads(conn, stype: str, limit: int = 12):
    """按 rowid 取模分编 — 54 连全编入, 每类 ~11 连."""
    return conn.execute(
        "SELECT squad_id, IFNULL(name,'') FROM mt_corps_squads "
        "WHERE (rowid % 5)=? ORDER BY rowid LIMIT ?",
        (SQUAD_TYPES.index(stype), limit)).fetchall()


# 下沉领域池 (连队级细分): 领域 → 检查表/检查方式
DOMAIN_POOL = [
    ('教辅K12', 'mt_edu_sync_log'), ('Arduino 同步', 'mt_arduino_sync_log'),
    ('文件整理', 'mt_file_organize_log'), ('防火墙', 'mt_firewall_rules'),
    ('任务大厅', 'mt_lab_task_hall'), ('脑库投喂', 'mt_ai_brain_feed_log'),
    ('EigenFlux', 'eigenflux_comm_messages'), ('维护部队', 'mt_maintenance_log'),
    ('冰山脉冲', 'mt_iceberg_runs'), ('三委立法', 'mt_committee_proposals'),
    ('题库质量', 'mt_edu_sync_content'), ('关系绑定', 'mt_center_ai_binding'),
    ('规则学习', 'mt_ai_rule_learning_log'), ('深度巡检', 'mt_daemon_registry'),
    ('员工心跳', 'ai_employees'),
]


def assign_domains_once(conn) -> dict:
    """连队级领域绑定: 54 连按序领领域 (多轮循环), 落 duty 列."""
    stats = {'assigned': 0, 'squads': 0}
    squads = conn.execute(
        "SELECT rowid, squad_id, IFNULL(duty,'') FROM mt_corps_squads "
        "ORDER BY rowid").fetchall()
    stats['squads'] = len(squads)
    for i, (rowid, sid, duty) in enumerate(squads):
        stype = SQUAD_TYPES[i % 5]
        dom = DOMAIN_POOL[(i // 5) % len(DOMAIN_POOL)][0]
        new_duty = f'{stype}·{dom}'
        if duty == new_duty:
            continue
        try:
            conn.execute("UPDATE mt_corps_squads SET duty=? WHERE rowid=?",
                         (new_duty, rowid))
            stats['assigned'] += 1
        except Exception:
            pass
    conn.commit()
    return stats


def domain_health_once(conn) -> dict:
    """按连队领域抽查对应表新鲜度 (每轮抽查 4 个领域)."""
    stats = {'checked': 0, 'stale': 0}
    start = int(time.time() // POLL_SECS) % len(DOMAIN_POOL)
    for k in range(4):
        dom, tbl = DOMAIN_POOL[(start + k) % len(DOMAIN_POOL)]
        try:
            n = conn.execute(
                f"SELECT count(*) FROM {tbl} WHERE rowid>(SELECT max(rowid)-50 "
                f"FROM {tbl})").fetchone()[0]
            stats['checked'] += 1
            if n == 0:
                stats['stale'] += 1
                _hall_task(conn, f'维和下沉: 领域「{dom}」近 50 行零产出',
                           f'抽查表 {tbl} 无近期活动, 需领域连队核查', 'NORMAL')
        except Exception:
            continue
    if stats['stale']:
        _log(conn, 'DOMAIN_STALE', stats)
    return stats


def patrol_once(conn) -> dict:
    """巡逻队: 异常 daemon 扫描 → 抢修单."""
    stats = {'squads': 0, 'findings': 0}
    rows = conn.execute(
        "SELECT process_name, IFNULL(last_heartbeat,'') FROM mt_daemon_registry "
        "WHERE status='RUNNING' AND (last_heartbeat IS NULL OR last_heartbeat<"
        "datetime('now','localtime','-2 hours')) LIMIT 8").fetchall()
    stats['squads'] = len(_squads(conn, 'PATROL'))
    if rows:
        stats['findings'] = len(rows)
        if _hall_task(conn, '维和巡逻队: 心跳停摆 daemon 抢修',
                      f'{len(rows)} 个 daemon 心跳超 2h: '
                      f'{",".join(r[0] for r in rows[:5])}', 'HIGH'):
            _log(conn, 'PATROL_FINDING', {'n': len(rows)})
    return stats


def survey_once(conn) -> dict:
    """调研队: 停滞同步链下沉检查 → 缺口单."""
    stats = {'squads': 0, 'findings': 0}
    stats['squads'] = len(_squads(conn, 'SURVEY'))
    checks = [('教辅同步', 'mt_edu_sync_log'), ('Arduino 同步', 'mt_arduino_sync_log'),
              ('文件整理', 'mt_file_organize_log')]
    stale = []
    for label, tbl in checks:
        try:
            n = conn.execute(
                f"SELECT count(*) FROM {tbl} WHERE created_at>"
                "datetime('now','localtime','-24 hours')").fetchone()[0]
            if n == 0:
                stale.append(label)
        except Exception:
            continue
    if stale:
        stats['findings'] = len(stale)
        if _hall_task(conn, '维和调研队: 下沉发现同步链停滞',
                      f'24h 零产出: {",".join(stale)}', 'NORMAL'):
            _log(conn, 'SURVEY_FINDING', {'stale': stale})
    return stats


def repair_once(conn) -> dict:
    """抢修队: QUEUED 超龄催办."""
    stats = {'squads': 0, 'findings': 0}
    stats['squads'] = len(_squads(conn, 'REPAIR'))
    n = conn.execute(
        "SELECT count(*) FROM mt_lab_task_hall WHERE status='QUEUED' AND "
        "created_at<datetime('now','localtime','-24 hours')").fetchone()[0]
    if n > 0:
        stats['findings'] = n
        if _hall_task(conn, f'维和抢修队: {n} 单 QUEUED 超 24h 催办',
                      '超龄任务需加速认领或外派阀门介入', 'HIGH'):
            _log(conn, 'REPAIR_FINDING', {'n': n})
    return stats


def empower_once(conn) -> dict:
    """赋能队: 连队技能 vs 中心技能包对齐盘点."""
    stats = {'squads': 0, 'empowered': 0}
    squads = _squads(conn, 'EMPOWER')
    stats['squads'] = len(squads)
    skills = conn.execute("SELECT count(*) FROM mt_task_hall_skills").fetchone()[0]
    emp = conn.execute(
        "SELECT count(*) FROM mt_corps_empowerment WHERE squad_id IN "
        "(SELECT squad_id FROM mt_corps_squads WHERE (CAST(squad_id AS INTEGER) % 5)=3)"
    ).fetchone()[0] if squads else 0
    if emp < skills:
        stats['empowered'] = skills - emp
        _log(conn, 'EMPOWER_GAP', {'squad_skills': emp, 'center_skills': skills})
    return stats


def recon_once(conn) -> dict:
    """侦察队: EigenFlux 最新情报 → 情报单."""
    stats = {'squads': 0, 'findings': 0}
    stats['squads'] = len(_squads(conn, 'RECON'))
    try:
        row = conn.execute(
            "SELECT IFNULL(content,'') FROM eigenflux_comm_messages "
            "ORDER BY rowid DESC LIMIT 1").fetchone()
        if row:
            _log(conn, 'RECON_WATCH', {'latest': row[0][:60]})
    except Exception:
        pass
    return stats


LOOPS = [('PATROL', patrol_once), ('SURVEY', survey_once), ('REPAIR', repair_once),
         ('EMPOWER', empower_once), ('RECON', recon_once)]


def field_once(conn) -> dict:
    """每轮: 领域分配 (幂等) + 轮转 1 类分队行动 + 领域健康抽查."""
    r = {'assign': assign_domains_once(conn),
         'domain_health': domain_health_once(conn)}
    idx = int(time.time() // POLL_SECS) % len(LOOPS)
    name, fn = LOOPS[idx]
    r['squad_action'] = fn(conn)
    r['squad_action']['squad_type'] = name
    return r


def run_all(conn) -> dict:
    out = {'assign': assign_domains_once(conn),
           'domain_health': domain_health_once(conn)}
    for name, fn in LOOPS:
        out[name] = fn(conn)
    out['note'] = 'GUARD 由 dispatch.guard_once 持有'
    return out


def _heartbeat():
    try:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?,?,?,?, datetime('now','localtime'), datetime('now','localtime'))",
            (DAEMON_NAME, '维和部队分队化市场下沉 (巡逻/调研/抢修/赋能/侦察 轮转) 600s',
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
        if cmd == 'run_all':
            print(json.dumps(run_all(conn), ensure_ascii=False, default=str))
        elif cmd == 'once':
            print(json.dumps(field_once(conn), ensure_ascii=False, default=str))
        else:
            print(f'[{DAEMON_NAME}] 分队下沉守护 pid={os.getpid()} '
                  f'poll={POLL_SECS}s', flush=True)
            while True:
                try:
                    r = field_once(conn)
                    if r.get('findings') or r.get('empowered'):
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
