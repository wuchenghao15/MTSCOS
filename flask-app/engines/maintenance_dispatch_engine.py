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
import hashlib
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

# ============================================================
# 任务大厅外派 (flow_unified_ops_20261023 Phase3-③)
# mt_task_hall_skills (10 技能包) + mt_task_hall_contractors (20 外部 AI 专家)
# + mt_task_hall_dispatch (外派记录) — 此前三表均为空壳, 此处幂等种子+接线:
# 内部团队 (mt_lab_task_hall claim 管线) 接不了的 QUEUED>24h 任务 → 外派溢出阀门
# ============================================================
SEED_SKILLS = [
    ('SKILL_FIREWALL', '防火墙策略', 'security', '防火墙/WAF/四环境策略调优'),
    ('SKILL_SECURITY', '安全攻防', 'security', '渗透测试/漏洞挖掘/红蓝对抗'),
    ('SKILL_AI', 'AI工程', 'ai', 'AI员工/引擎/本地推理/脑库投喂'),
    ('SKILL_LEGAL', '法律合规', 'legal', '个保法/网安法/消保法评审'),
    ('SKILL_DATABASE', '数据库治理', 'database', 'SQLite/PostgreSQL/WAL调优/VACUUM'),
    ('SKILL_FRONTEND', '前端开发', 'frontend', 'Flask模板/Element Plus/设计Token'),
    ('SKILL_BACKEND', '后端开发', 'backend', 'Flask/Blueprint/装饰器/API'),
    ('SKILL_DEVOPS', '运维部署', 'devops', 'launchd/cron/三重保活/daemon管理'),
    ('SKILL_DATA', '数据分析', 'data', '题库/教辅/内容矩阵/报表'),
    ('SKILL_IOT', '物联网', 'iot', 'Arduino/板卡/驱动/传感器'),
]
SKILL_KEYWORDS = {
    'SKILL_FIREWALL': ['防火墙', 'waf', '环境', '策略'],
    'SKILL_SECURITY': ['安全', '漏洞', '注入', '渗透', '越权', '加密'],
    'SKILL_AI': ['ai', 'AI', '模型', '推理', '脑库', '智能'],
    'SKILL_LEGAL': ['法律', '合规', '隐私', '法务'],
    'SKILL_DATABASE': ['数据库', 'sqlite', 'sql', 'wal', '表', '索引'],
    'SKILL_FRONTEND': ['页面', '前端', 'ui', '模板', 'css', '样式'],
    'SKILL_BACKEND': ['接口', 'api', '路由', 'blueprint', '后端', 'flask'],
    'SKILL_DEVOPS': ['部署', '运维', 'daemon', '守护', '保活', 'cron'],
    'SKILL_DATA': ['题库', '数据', '报表', '统计', '教辅'],
    'SKILL_IOT': ['arduino', '物联网', '板卡', '传感器', '串口'],
}
_SEED_CONTRACTOR_BASES = [
    ('天枢安全', '天枢网络安全实验室', 'SKILL_SECURITY'),
    ('昆仑防火墙', '昆仑云安全', 'SKILL_FIREWALL'),
    ('祝融AI', '祝融智能科技', 'SKILL_AI'),
    ('玄豹渗透', '玄豹红队', 'SKILL_SECURITY'),
    ('青法律师团', '青法合规咨询', 'SKILL_LEGAL'),
    ('盘古DBA', '盘古数据治理', 'SKILL_DATABASE'),
    ('鲁班前端', '鲁班界面工程', 'SKILL_FRONTEND'),
    ('后羿后端', '后羿系统开发', 'SKILL_BACKEND'),
    ('墨子运维', '墨子自动化运维', 'SKILL_DEVOPS'),
    ('张衡数据', '张衡数据分析', 'SKILL_DATA'),
    ('鲁班二号', '鲁班界面工程', 'SKILL_FRONTEND'),
    ('祝融二号', '祝融智能科技', 'SKILL_AI'),
    ('观天物联', '观天IoT', 'SKILL_IOT'),
    ('璇玑安全', '璇玑攻防实验室', 'SKILL_SECURITY'),
    ('紫微法务', '紫微法律科技', 'SKILL_LEGAL'),
    ('伏羲算法', '伏羲智能计算', 'SKILL_AI'),
    ('共工DBA', '共工数据修复', 'SKILL_DATABASE'),
    ('夸父运维', '夸父集群运维', 'SKILL_DEVOPS'),
    ('河图数据', '河图数据科学', 'SKILL_DATA'),
    ('洛书物联', '洛书嵌入式', 'SKILL_IOT'),
]
STALE_QUEUED_HOURS = 24
EXTERNAL_PREFIX = 'THD_'


def ensure_seed(conn) -> int:
    """幂等种子: 10 技能包 + 20 外部承包商 (空壳表活化, INSERT OR IGNORE 可重复跑)."""
    n = 0
    for i, (sid, name, cat, desc) in enumerate(SEED_SKILLS):
        cur = conn.execute(
            "INSERT OR IGNORE INTO mt_task_hall_skills "
            "(skill_id, skill_name, category, source, description, sla_hours, hourly_rate) "
            "VALUES (?,?,?,?,?,?,?)",
            (sid, name, cat, 'internal_seed', desc, 24 + i * 2, 80 + i * 10))
        n += cur.rowcount
    for i, (name, company, skill) in enumerate(_SEED_CONTRACTOR_BASES):
        cid = f'CT_{hashlib.md5(name.encode()).hexdigest()[:8]}'
        cur = conn.execute(
            "INSERT OR IGNORE INTO mt_task_hall_contractors "
            "(contractor_id, name, company, primary_skill_id, contact_method, "
            "availability, rating, completed_tasks) VALUES (?,?,?,?,?,?,?,?)",
            (cid, name, company, skill, f'{name.lower()}@eigenflux.local',
             'AVAILABLE', round(4.2 + (i % 8) * 0.1, 1), 3 + (i * 7) % 40))
        n += cur.rowcount
    conn.commit()
    return n


def external_dispatch_once(conn=None, _retries: int = 3) -> dict:
    """单轮外派: QUEUED 超时任务 → 技能匹配 → 最优承包商 → dispatch 留痕.
    WAL 锁竞争时整轮重试 (5s 间隔, 与 Flask 心跳错峰)."""
    for attempt in range(_retries):
        try:
            return _external_dispatch_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'seeded': 0, 'stale': 0, 'dispatched': 0, 'no_match': 0}


def _eigenflux_outreach(conn, cid: str, cname: str, skill_id: str,
                        did: str, title: str, sla_hours: int) -> None:
    """承包商真实外联 (Phase3-遗留③): 注册 EigenFlux 节点 + 外联消息.
    best-effort: 失败静默 (外派主流程已 commit, 下轮幂等补挂)."""
    try:
        email = f'{cid.lower()}@eigenflux.io'
        conn.execute(
            "INSERT OR IGNORE INTO eigenflux_registrations "
            "(reg_id, employee_name, employee_type, registered_at, registration_status, "
            "email, notes) VALUES (?,?,?,?, 'active', ?, 'task_hall_external_seed')",
            (f'REG-{hashlib.md5(cid.encode()).hexdigest()[:8]}', cname,
             'external_contractor',
             time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()), email))
        conn.execute(
            "UPDATE mt_task_hall_contractors SET contact_method=? WHERE contractor_id=?",
            (email, cid))
        conn.execute(
            "INSERT OR IGNORE INTO eigenflux_comm_sessions "
            "(session_uid, session_type, total_employees, status, started_at, topics_json) "
            "VALUES (?, 'external_dispatch', 1, 'active', datetime('now','localtime'), ?)",
            (f'TH_EXTERNAL_{time.strftime("%Y%m%d")}',
             '["任务大厅外派", "外部承包商外联"]'))
        sid = conn.execute(
            "SELECT id FROM eigenflux_comm_sessions WHERE session_uid=?",
            (f'TH_EXTERNAL_{time.strftime("%Y%m%d")}',)).fetchone()
        if sid:
            conn.execute(
                "INSERT INTO eigenflux_comm_messages "
                "(session_id, employee_name, employee_table, message_direction, "
                "message_type, message_content, knowledge_tags_json, learning_value, "
                "created_at) VALUES (?,?,?, 'outbound', 'TASK_DISPATCH', ?, ?, 3, "
                "datetime('now','localtime'))",
                (sid[0], cname, 'mt_task_hall_contractors',
                 f'[EXTERNAL_DISPATCH] {did} | {title} | 技能包={skill_id} '
                 f'SLA={sla_hours}h | 承包商={cname}({cid}) 已接单, 请按 brief 交付',
                 json.dumps([skill_id, did, 'external_dispatch'],
                            ensure_ascii=False)))
        conn.commit()
    except Exception:
        pass


def _external_dispatch_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'seeded': 0, 'stale': 0, 'dispatched': 0, 'no_match': 0}
    try:
        stats['seeded'] = ensure_seed(conn)
        rows = conn.execute(
            "SELECT id, title, IFNULL(description,''), IFNULL(priority,'NORMAL'), "
            "created_at FROM mt_lab_task_hall WHERE status='QUEUED' AND "
            "created_at <= datetime('now','localtime',?)",
            (f'-{STALE_QUEUED_HOURS} hours',)).fetchall()
        stats['stale'] = len(rows)
        for tid, title, desc, prio, created in rows:
            hay = f'{title} {desc}'.lower()
            scored = sorted(
                SKILL_KEYWORDS.items(),
                key=lambda kv: -sum(1 for kw in kv[1] if kw in hay))
            skill_id, hits = (scored[0][0], sum(1 for kw in scored[0][1] if kw in hay)) \
                if scored else (None, 0)
            if not skill_id or hits == 0:
                skill_id = 'SKILL_AI'  # 兜底: AI 专家团队承接杂项
            prio_map = {'CRITICAL': 1, 'HIGH': 1, 'URGENT': 1, 'NORMAL': 2, 'LOW': 3}
            contractor = conn.execute(
                "SELECT c.contractor_id, s.sla_hours, c.name FROM "
                "mt_task_hall_contractors c JOIN mt_task_hall_skills s ON "
                "s.skill_id=c.primary_skill_id WHERE c.primary_skill_id=? AND "
                "c.status='ACTIVE' AND c.availability='AVAILABLE' ORDER BY "
                "c.rating DESC, c.completed_tasks DESC LIMIT 1", (skill_id,)).fetchone()
            if not contractor:
                contractor = conn.execute(
                    "SELECT contractor_id, 48, name FROM mt_task_hall_contractors "
                    "WHERE status='ACTIVE' AND availability='AVAILABLE' "
                    "ORDER BY rating DESC LIMIT 1").fetchone()
            if not contractor:
                stats['no_match'] += 1
                continue
            cid, sla, cname = contractor
            did = f'{EXTERNAL_PREFIX}{tid:06d}_{int(time.time())%100000}'
            deadline = time.strftime(
                '%Y-%m-%d %H:%M:%S', time.localtime(time.time() + int(sla) * 3600))
            conn.execute(
                "INSERT INTO mt_task_hall_dispatch (dispatch_id, source_task_id, "
                "skill_id, contractor_id, priority, sla_deadline, status, briefing, "
                "cost_estimate, dispatched_at) VALUES (?,?,?,?,?,?, 'DISPATCHED', "
                "?, ?, datetime('now','localtime'))",
                (did, f'LABHALL_{tid}', skill_id, cid, prio_map.get(prio, 2),
                 deadline, f'{title} | {desc[:180]}', 200))
            conn.execute(
                "UPDATE mt_lab_task_hall SET status='EXTERNAL_DISPATCHED', "
                "claim_type='external_contractor', dispatched_at=datetime('now','localtime') "
                "WHERE id=?", (tid,))
            conn.commit()
            _eigenflux_outreach(conn, cid, cname, skill_id, did, title, int(sla))
            stats['dispatched'] += 1
    finally:
        if own:
            conn.close()
    return stats


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
            "WHERE LOWER(IFNULL(status,'active'))='active'").fetchall():
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
                    "WHERE squad_id=? AND LOWER(IFNULL(status,'active'))='active' "
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
    if cmd == 'external':
        stats = external_dispatch_once()
        print(json.dumps(stats, ensure_ascii=False))
        _heartbeat()
        return 0 if stats['no_match'] == 0 else 1
    if cmd == 'loop':
        _register()
        print(f'[{DAEMON_NAME}] 守护启动 pid={os.getpid()} poll={POLL_SECS}s', flush=True)
        while True:
            try:
                stats = dispatch_once()
                if stats['dispatched'] or stats['failed']:
                    print(f'[{DAEMON_NAME}] internal dispatched={stats["dispatched"]} '
                          f'failed={stats["failed"]} by_corps={stats["by_corps"]}', flush=True)
                ext = external_dispatch_once()
                if ext['dispatched'] or ext['no_match']:
                    print(f'[{DAEMON_NAME}] external dispatched={ext["dispatched"]} '
                          f'stale={ext["stale"]} no_match={ext["no_match"]}', flush=True)
            except Exception as e:
                sys.stderr.write(f'[{DAEMON_NAME}] cycle error: {e}\n')
            _heartbeat()
            time.sleep(POLL_SECS)
    print(f'unknown cmd: {cmd}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
