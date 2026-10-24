#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维护部队自动派单引擎 (sys_maintenance_dispatch)
================================================
flow_unified_ops_20261023 · Phase3-②

职责: 把 mt_maintenance_tasks 中 PENDING 任务自动分单到维护连 (mt_corps_squads)
  - 匹配: task_type + 标题关键词 → 连队 duty/empowerment/技能 (mt_corps_empowerment) 打分
  - 指派: 连队内 ai_employees 轮转取人 (assignee_name/assignee_code)
  - 留痕: mt_maintenance_log action=AUTO_DISPATCH (JSON 详情)
  - 心跳: 文件心跳 (_runtime/pids/*.heartbeat) + mt_daemon_registry best-effort
  - 幂等: 只碰 PENDING, 重复跑无副作用; 短事务 (逐任务 commit) 不与 Flask 抢长锁

用法:
  python3 maintenance_dispatch_engine.py dispatch   # 一次性派单 (冒烟/手动)
  python3 maintenance_dispatch_engine.py loop       # 守护循环 (默认 300s)
  python3 maintenance_dispatch_engine.py status     # 查看队列状态
"""
from __future__ import annotations
import json
import os
import sys
import time

import sqlite3

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(FA_DIR)
PID_DIR = os.environ.get('MTSCOS_PID_DIR', os.path.join(PROJECT_ROOT, '_runtime', 'pids'))
DAEMON_NAME = 'sys_maintenance_dispatch'
POLL_SECS = int(os.environ.get('MTSCOS_DISPATCH_POLL', '300'))

# task_type → 连队匹配关键词 (命中连队名/duty/empowerment/技能名 计分)
TYPE_KEYWORDS = {
    'security': ['安全', '注入', 'xss', 'csrf', 'waf', '防火墙', '越权', '漏洞',
                 '审计', '溯源', '加密', '红队', '靶场'],
    'bugfix': ['补丁', '修复', '应急', 'p0', '排障'],
    'cleanup': ['清理', '回收', '恢复', '瘦身', '归档'],
    'upgrade': ['升级', '版本', '补丁', '迭代'],
    'ops': ['部署', '运维', '监控', '日志', '巡检', 'keepalive'],
    'feature': ['研发', '开发', '功能', 'skill', '衍生', '新方向'],
    'refactor': ['重构', '优化', '治理', '整改'],
}


def _db_path() -> str:
    env = os.environ.get('MTSCOS_DB')
    if env and os.path.exists(env):
        return env
    for cand in (os.path.join(FA_DIR, 'database', 'app.db'),
                 os.path.join(PROJECT_ROOT, 'flask-app', 'database', 'app.db')):
        if os.path.exists(cand):
            return cand
    return os.path.join(FA_DIR, 'database', 'app.db')


def _connect():
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _heartbeat():
    """文件心跳 (WAL 锁免疫) + registry best-effort"""
    try:
        os.makedirs(PID_DIR, exist_ok=True)
        hb = os.path.join(PID_DIR, f'{DAEMON_NAME}.heartbeat')
        with open(hb, 'a'):
            os.utime(hb, None)
    except Exception:
        pass
    try:
        conn = _connect()
        conn.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
            "pid=?, status='RUNNING' WHERE process_name=?", (os.getpid(), DAEMON_NAME))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _load_squads(conn) -> dict:
    """corps_id → [{'squad_id','name','duty','empowerment','skills':[...]}]"""
    squads = {}
    for row in conn.execute(
            "SELECT squad_id, corps_id, name, duty, empowerment FROM mt_corps_squads "
            "WHERE status='ACTIVE'").fetchall():
        squads.setdefault(row[1], []).append(
            {'squad_id': row[0], 'name': row[2] or '', 'duty': row[3] or '',
             'empowerment': row[4] or '', 'skills': []})
    for sid, skill in conn.execute(
            "SELECT squad_id, skill_name FROM mt_corps_empowerment").fetchall():
        for corp in squads.values():
            for sq in corp:
                if sq['squad_id'] == sid and skill:
                    sq['skills'].append(skill.lower())
    return squads


def _score_task_squad(task_type: str, title: str, sq: dict) -> int:
    score = 0
    hay = ' '.join([sq['name'], sq['duty'], sq['empowerment']] + sq['skills']).lower()
    for kw in TYPE_KEYWORDS.get(task_type, []):
        if kw in hay:
            score += 2
    for kw in TYPE_KEYWORDS.get(task_type, []):
        if kw in (title or '').lower() and kw in hay:
            score += 1  # 标题与连队双重命中
    return score


def dispatch_once(conn=None) -> dict:
    """单轮派单: 全部 PENDING → DISPATCHED. 返回统计."""
    own = conn is None
    if own:
        conn = _connect()
    stats = {'pending': 0, 'dispatched': 0, 'failed': 0, 'by_corps': {}}
    try:
        squads = _load_squads(conn)
        tasks = conn.execute(
            "SELECT id, task_id, corps_id, title, task_type FROM mt_maintenance_tasks "
            "WHERE status='PENDING' ORDER BY priority ASC, id ASC").fetchall()
        stats['pending'] = len(tasks)
        for tid, task_id, corps_id, title, task_type in tasks:
            try:
                cand = squads.get(corps_id) or []
                if not cand:
                    cand = [sq for c in squads.values() for sq in c]
                if not cand:
                    stats['failed'] += 1
                    continue
                scored = sorted(cand, key=lambda sq: -_score_task_squad(task_type, title, sq))
                squad = scored[0]
                members = conn.execute(
                    "SELECT name, employee_code FROM ai_employees "
                    "WHERE squad_id=? AND IFNULL(status,'ACTIVE')='ACTIVE' "
                    "ORDER BY id", (squad['squad_id'],)).fetchall()
                if not members:
                    stats['failed'] += 1
                    continue
                load = conn.execute(
                    "SELECT count(*) FROM mt_maintenance_tasks WHERE assignee_code=?",
                    (members[0][1],)).fetchone()[0]
                member = members[load % len(members)]  # 按当前负载轮转
                conn.execute(
                    "UPDATE mt_maintenance_tasks SET status='DISPATCHED', assignee_name=?, "
                    "assignee_code=? WHERE id=?", (member[0], member[1], tid))
                conn.execute(
                    "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
                    "VALUES (?,?,?,?)",
                    (corps_id, task_id, 'AUTO_DISPATCH', json.dumps(
                        {'squad': squad['squad_id'], 'squad_name': squad['name'],
                         'employee': member[0], 'employee_code': member[1],
                         'task_type': task_type, 'engine': DAEMON_NAME},
                        ensure_ascii=False)))
                conn.commit()
                stats['dispatched'] += 1
                stats['by_corps'][corps_id] = stats['by_corps'].get(corps_id, 0) + 1
            except Exception as e:
                stats['failed'] += 1
                try:
                    sys.stderr.write(f'[DISPATCH] task {task_id} 失败: {e}\n')
                except Exception:
                    pass
    finally:
        if own:
            conn.close()
    return stats


def queue_status() -> dict:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT status, count(*) FROM mt_maintenance_tasks GROUP BY status").fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


def _register():
    try:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?, ?, ?, 'RUNNING', datetime('now','localtime'), datetime('now','localtime'))",
            (DAEMON_NAME, '维护部队自动派单 (PENDING→连队分单, 300s)', os.getpid()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'dispatch'
    if cmd == 'status':
        print(json.dumps(queue_status(), ensure_ascii=False))
        return 0
    if cmd == 'dispatch':
        stats = dispatch_once()
        print(json.dumps(stats, ensure_ascii=False))
        _heartbeat()
        return 0 if stats['failed'] == 0 else 1
    if cmd == 'loop':
        _register()
        print(f'[{DAEMON_NAME}] 守护启动 pid={os.getpid()} poll={POLL_SECS}s', flush=True)
        while True:
            try:
                stats = dispatch_once()
                if stats['dispatched'] or stats['failed']:
                    print(f'[{DAEMON_NAME}] dispatched={stats["dispatched"]} '
                          f'failed={stats["failed"]} by_corps={stats["by_corps"]}', flush=True)
            except Exception as e:
                sys.stderr.write(f'[{DAEMON_NAME}] cycle error: {e}\n')
            _heartbeat()
            time.sleep(POLL_SECS)
    print(f'unknown cmd: {cmd}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
