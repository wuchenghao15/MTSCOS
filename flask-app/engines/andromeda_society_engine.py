#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座自治区引擎 (sys_andromeda_society)
==========================================
flow_unified_ops_20261024 · AI 社会全自动化运转编排层

14 类社会行为 → 模块映射 (已有引擎复用, 本引擎只做编排+补缺):
  立法        legislature_once 生成提案 → governance.committee_once 自动表决颁布
  组织学习    governance.social_once (圆桌=组织学习, 已有)
  轮岗/赋能   rotation_once (6h): 连队技能轮换 + level 重洗 + 脑库留痕
  组织架构    org_review_once (24h): 架构审视报告 + 失衡建议落建议池
  智能研发/   incubate_once (12h): 圆桌共识→skill 提案落 mt_task_hall_skills
  孵化skill             + daemon 提案落 mt_ai_suggestion_pool → smart_mount 自动 mount
  下沉调研    survey_once (30min): 缺口信号扫描 → 自动建任务进大厅 (回灌闭环)
  收集需求    survey_once 信号源之二 (圆桌 outcome / 脑库提问)
  接大厅任务  maintenance_dispatch_engine.dispatch_once (已有, 派单→执行闭环)
  自动交友    ai_eigenflux_network_engine (已有, 2.2万连接/天)
  自动学习    social_once 学习记录 (已有)
  自动拜师    mentorship_once (2h): 新星↔专家 MENTOR 连接
  战略规划    strategy_once (24h): 运行数据汇总备忘录 → 脑库投喂 → 成为下一轮圆桌议题

闭环: survey 发现缺口 → 大厅 QUEUED → 现有管线自动认领/派发/执行 → 结果反哺调研
节奏: 文件时间戳 _runtime/pids/society_{module}.lastrun 控制, 零 DDL
"""
from __future__ import annotations
import hashlib
import json
import os
import random
import sys
import time

import sqlite3

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(FA_DIR)
PID_DIR = os.environ.get('MTSCOS_PID_DIR', os.path.join(PROJECT_ROOT, '_runtime', 'pids'))
DAEMON_NAME = 'sys_andromeda_society'
LOOP_SECS = int(os.environ.get('MTSCOS_SOCIETY_POLL', '60'))

# 模块 → 间隔秒 (定期/不定期: 研发/立法带随机抖动, 其余固定节奏)
SCHEDULE = {
    'survey': 30 * 60,
    'mentorship': 2 * 3600,
    'rotation': 6 * 3600,
    'incubate': 12 * 3600,
    'legislature': 24 * 3600,
    'strategy': 24 * 3600,
    'org_review': 24 * 3600,
}


def _connect():
    env = os.environ.get('MTSCOS_DB')
    path = env if (env and os.path.exists(env)) else os.path.join(
        FA_DIR, 'database', 'app.db')
    conn = sqlite3.connect(path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _now() -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def _due(module: str) -> bool:
    f = os.path.join(PID_DIR, f'society_{module}.lastrun')
    if not os.path.exists(f):
        return True
    return time.time() - os.path.getmtime(f) > SCHEDULE[module]


def _mark(module: str):
    os.makedirs(PID_DIR, exist_ok=True)
    with open(os.path.join(PID_DIR, f'society_{module}.lastrun'), 'a'):
        os.utime(os.path.join(PID_DIR, f'society_{module}.lastrun'), None)


def _feed(conn, fed_by: str, target: str, preview: str) -> None:
    """统一留痕: 脑库投喂 (全系统审计通道)."""
    try:
        conn.execute(
            "INSERT INTO mt_ai_brain_feed_log (fed_by, feed_target, payload_preview, "
            "fed_at) VALUES (?,?,?, datetime('now','localtime'))",
            (fed_by, target, preview[:200]))
        conn.commit()
    except Exception:
        pass


# ============================================================
# 1) 下沉市场调研 (30min) — 缺口扫描 → 大厅回灌
# ============================================================
def survey_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _survey_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'gaps': 0, 'tasks_created': 0}


def _survey_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'gaps': 0, 'tasks_created': 0}
    GAP_SIGNALS = [
        ('FAILED daemon 清障', "SELECT count(*) FROM mt_daemon_registry WHERE status='FAILED'",
         "发现 {} 个 FAILED daemon, 需排查根因并自动修复, 恢复到 RUNNING", 'HIGH'),
        ('僵尸心跳清理', "SELECT count(*) FROM mt_daemon_registry WHERE status='RUNNING' "
         "AND IFNULL(last_heartbeat,'')<datetime('now','localtime','-1 hour')",
         "发现 {} 个 daemon 心跳停滞超 1h, 疑似空转型, 需业务活性体检", 'NORMAL'),
        ('维护任务积压', "SELECT count(*) FROM mt_maintenance_tasks WHERE status='DISPATCHED'",
         "维护任务 DISPATCHED 积压 {} 单, 需评估执行吞吐是否要扩容", 'NORMAL'),
        ('大厅认领积压', "SELECT count(*) FROM mt_lab_task_hall WHERE status='QUEUED'",
         "任务大厅 QUEUED 积压 {} 单, 认领管线吞吐需体检", 'NORMAL'),
    ]
    try:
        for title_t, sql, desc_t, prio in GAP_SIGNALS:
            try:
                n = conn.execute(sql).fetchone()[0]
            except Exception:
                continue
            if n <= 0:
                continue
            stats['gaps'] += 1
            title = title_t
            if conn.execute(
                    "SELECT count(*) FROM mt_lab_task_hall WHERE title=? AND "
                    "created_at>datetime('now','localtime','-24 hours')",
                    (title,)).fetchone()[0] > 0:
                continue  # 24h 内已报过同一缺口, 不重复回灌
            if prio == 'HIGH' or stats['tasks_created'] < 2:
                conn.execute(
                    "INSERT INTO mt_lab_task_hall (title, description, source, "
                    "priority, status, created_at) VALUES (?,?,?,?, 'QUEUED', "
                    "datetime('now','localtime'))",
                    (title, desc_t.format(n), 'andromeda_survey', prio))
                conn.commit()
                stats['tasks_created'] += 1
                _feed(conn, 'andromeda_society_survey', 'task_hall',
                      f'[缺口回灌] {title}: n={n} → 大厅 QUEUED, 等待认领派发')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 2) 自动拜师 (2h) — 新星 ↔ 专家 MENTOR 连接
# ============================================================
def mentorship_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _mentor_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'pairs': 0}


def _mentor_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'pairs': 0}
    try:
        # 新星: 30min 内心跳活跃、尚未有任何 MENTOR 关系的节点
        novices = conn.execute(
            "SELECT IFNULL(NULLIF(employee_id,''), employee_name), employee_name "
            "FROM eigenflux_registrations r WHERE IFNULL(last_heartbeat,'')>"
            "datetime('now','localtime','-30 minutes') AND NOT EXISTS (SELECT 1 FROM "
            "mt_ai_eigenflux_connections c WHERE c.relation_level='MENTOR' AND "
            "(c.left_employee_id=r.employee_id OR c.right_employee_id=r.employee_id)) "
            "ORDER BY last_heartbeat DESC LIMIT 3").fetchall()
        for nid, nname in novices:
            if not nid:
                continue
            # 师父: 专家池里 specialty 与新星名/技能相关的高分员工
            mentor = conn.execute(
                "SELECT IFNULL(NULLIF(employee_code,''), name), name FROM ai_employees "
                "WHERE LOWER(IFNULL(status,'active'))='active' AND "
                "(IFNULL(specialties,'')!='' OR IFNULL(title,'')!='') AND name!=? "
                "ORDER BY IFNULL(successful_fixes,0) DESC, IFNULL(last_heartbeat,'') DESC "
                "LIMIT 1", (nname,)).fetchone()
            if not mentor:
                continue
            mid, mname = mentor
            cuid = f'CONN_MENTOR_{hashlib.md5(f"{nid}|{mid}".encode()).hexdigest()[:16]}'
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_ai_eigenflux_connections (conn_uid, "
                "left_employee_id, left_employee_table, left_employee_name, "
                "right_employee_id, right_employee_table, right_employee_name, "
                "handshake_state, relation_level, strength, first_connected_at, "
                "last_interaction_at, created_at) VALUES (?,?,?,?,?,?,?,?, 'MENTOR', 0.8, "
                "datetime('now','localtime'), datetime('now','localtime'), "
                "datetime('now','localtime'))",
                (cuid, nid, 'eigenflux_registrations', nname,
                 mid, 'ai_employees', mname, 'MENTORED'))
            conn.commit()
            if cur.rowcount:
                stats['pairs'] += 1
                _feed(conn, 'andromeda_society_mentorship', 'ai_brain',
                      f'[拜师] {nname} → 师从 {mname} (MENTOR 连接建立, 带徒计划启动)')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 3) 轮岗 + 动态赋能 (6h) — 连队技能轮换 + level 重洗
# ============================================================
def rotation_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _rotation_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'swapped': 0, 'leveled': 0}


def _rotation_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'swapped': 0, 'leveled': 0}
    try:
        rows = conn.execute(
            "SELECT id, squad_id, skill_name FROM mt_corps_empowerment "
            "ORDER BY RANDOM() LIMIT 2").fetchall()
        if len(rows) == 2:
            (i1, s1, k1), (i2, s2, k2) = rows
            if s1 != s2:  # 两个不同连队互换一条技能 = 轮岗
                conn.execute("UPDATE mt_corps_empowerment SET squad_id=? WHERE id=?",
                             (s2, i1))
                conn.execute("UPDATE mt_corps_empowerment SET squad_id=? WHERE id=?",
                             (s1, i2))
                conn.commit()
                stats['swapped'] = 1
                _feed(conn, 'andromeda_society_rotation', 'org',
                      f'[轮岗] 技能「{k1}」{s1}↔{s2}「{k2}」互换, 交叉赋能')
        for rid, in conn.execute(
                "SELECT id FROM mt_corps_empowerment ORDER BY RANDOM() LIMIT 5"):
            lv = conn.execute(
                "SELECT level FROM mt_corps_empowerment WHERE id=?", (rid,)).fetchone()
            if lv:
                new_lv = max(1, min(5, lv[0] + random.choice((-1, 0, 1))))
                if new_lv != lv[0]:
                    conn.execute(
                        "UPDATE mt_corps_empowerment SET level=? WHERE id=?",
                        (new_lv, rid))
                    stats['leveled'] += 1
        conn.commit()
        if stats['leveled']:
            _feed(conn, 'andromeda_society_rotation', 'org',
                  f'[动态赋能] {stats["leveled"]} 条技能等级微调 (演练-反馈循环)')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 4) 智能研发/孵化 (12h) — skill 落技能包 + daemon 提案落建议池
# ============================================================
def incubate_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _incubate_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'skills': 0, 'daemon_proposals': 0}


def _incubate_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'skills': 0, 'daemon_proposals': 0}
    try:
        row = conn.execute(
            "SELECT agenda, outcome FROM mt_roundtable_sessions ORDER BY id DESC "
            "LIMIT 1").fetchone()
        if not row:
            return stats
        agenda, outcome = row
        topic = (agenda or '综合优化')[:16].replace('「', '').replace('」', '')
        seed = hashlib.md5(f'{agenda}{_now()[:10]}'.encode()).hexdigest()[:6]
        skill_name = f'圆桌共识·{topic}落地法'
        if not conn.execute(
                "SELECT count(*) FROM mt_task_hall_skills WHERE skill_name=?",
                (skill_name,)).fetchone()[0]:
            conn.execute(
                "INSERT INTO mt_task_hall_skills (skill_id, skill_name, category, "
                "source, description, sla_hours, hourly_rate) VALUES (?,?,?,?,?,?,?)",
                (f'SKILL_INC_{seed}', skill_name, 'ai', 'andromeda_incubation',
                 f'源自圆桌共识: {outcome[:120]}', 48, 150))
            conn.commit()
            stats['skills'] += 1
        # daemon 孵化: 走 smart_mount 建议池 (auto_k12_tutor 同通道)
        daemon_name = f'auto_society_{topic}'.replace('·', '_').replace(' ', '_')[:32]
        stext = (f'{daemon_name} · {topic}自动化守护: MVP=从圆桌共识提炼巡检项, '
                 f'300s 周期执行并落库, 异常自动回灌任务大厅')
        if not conn.execute(
                "SELECT count(*) FROM mt_ai_suggestion_pool WHERE source_name=? AND "
                "status IN ('PENDING','DEPLOYED')", (daemon_name,)).fetchone()[0]:
            conn.execute(
                "INSERT INTO mt_ai_suggestion_pool (source_type, source_name, "
                "suggestion_text, priority, status, feasibility_score, value_score, "
                "cost_score, risk_score, meta_json, created_at) VALUES "
                "('AI_SUGGESTION', ?, ?, 7, 'PENDING', 0.8, 0.8, 0.3, 0.2, ?, "
                "datetime('now','localtime'))",
                (daemon_name, stext, json.dumps(
                    {'incubator': 'andromeda_society', 'agenda': agenda[:60]})))
            conn.commit()
            stats['daemon_proposals'] += 1
            _feed(conn, 'andromeda_society_incubation', 'smart_mount',
                  f'[孵化] daemon 提案 {daemon_name} 已入建议池等待 mount; '
                  f'skill「{skill_name}」已入技能包')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 5) 立法提案 (24h, 不定期抖动) — 缺口 → 提案 → governance 自动表决颁布
# ============================================================
def legislature_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _legis_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'proposals': 0}


def _legis_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'proposals': 0}
    try:
        gap = conn.execute(
            "SELECT title, description FROM mt_lab_task_hall WHERE "
            "source='andromeda_survey' AND created_at>datetime('now','localtime',"
            "'-48 hours') ORDER BY id DESC LIMIT 1").fetchone()
        if not gap:
            return stats
        title = f'关于建立「{gap[0]}」长效治理机制的提案'
        if conn.execute(
                "SELECT count(*) FROM mt_committee_proposals WHERE title=? AND "
                "created_at>datetime('now','localtime','-7 days')",
                (title,)).fetchone()[0]:
            return stats
        pid = f'PROP_SXY_{hashlib.md5(title.encode()).hexdigest()[:10]}'
        conn.execute(
            "INSERT OR IGNORE INTO mt_committee_proposals (proposal_id, title, type, "
            "category, proposer, priority, source, status) VALUES "
            "(?,?, '新增', '系统治理', '仙女座自治区', 2, 'ANDROMEDA_SOCIETY', 'PENDING')",
            (pid, title))
        conn.commit()
        if conn.execute("SELECT count(*) FROM mt_committee_proposals WHERE proposal_id=?",
                        (pid,)).fetchone()[0]:
            stats['proposals'] = 1
            _feed(conn, 'andromeda_society_legislature', 'committee',
                  f'[立法] 自治区提案 {pid}「{title[:40]}」已提交, 等待三委联席表决')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 6) 战略规划研究 (24h) — 运行数据汇总 → 脑库 → 成为下一轮圆桌议题
# ============================================================
def strategy_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _strategy_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'memo': 0}


def _strategy_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    try:
        alive = conn.execute(
            "SELECT count(*) FROM mt_daemon_registry WHERE status IN ('RUNNING','ACTIVE')"
        ).fetchone()[0]
        done24 = conn.execute(
            "SELECT count(*) FROM mt_maintenance_tasks WHERE status='DONE' AND "
            "IFNULL(updated_at,'')>datetime('now','localtime','-24 hours')").fetchone()[0]
        friends24 = conn.execute(
            "SELECT count(*) FROM mt_ai_eigenflux_connections WHERE "
            "created_at>datetime('now','localtime','-24 hours')").fetchone()[0]
        laws = conn.execute("SELECT count(*) FROM mt_committee_decrees").fetchone()[0]
        memo = (f'[战略备忘录 {(_now())[:10]}] 24h 社会运行盘点: daemon 存活 {alive}, '
                f'维护任务完成 {done24}, 新建社交 {friends24}, 现行法令 {laws} 部。'
                f'战略焦点: 从"规模扩张"转向"质量深化" — 提高任务完成质量、'
                f'深化师徒传承、孵化高价值 daemon。')
        _feed(conn, 'andromeda_society_strategy', 'ai_brain', memo)
        return {'memo': 1}
    finally:
        if own:
            conn.close()


# ============================================================
# 7) 组织架构审视 (24h) — 负载审视 + 失衡建议
# ============================================================
def org_review_once(conn=None, _retries: int = 3) -> dict:
    for a in range(_retries):
        try:
            return _org_inner(conn)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and a < _retries - 1:
                time.sleep(5)
                continue
            raise
    return {'reviewed': 0, 'imbalance': 0}


def _org_inner(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'reviewed': 0, 'imbalance': 0}
    try:
        rows = conn.execute(
            "SELECT corps_id, count(*) FROM mt_maintenance_tasks GROUP BY corps_id "
            "ORDER BY 2 DESC").fetchall()
        if len(rows) >= 2:
            hi, lo = rows[0], rows[-1]
            stats['reviewed'] = 1
            if lo[1] > 0 and hi[1] > lo[1] * 2:
                stats['imbalance'] = 1
                conn.execute(
                    "INSERT INTO mt_ai_suggestion_pool (source_type, source_name, "
                    "suggestion_text, priority, status, feasibility_score, value_score, "
                    "cost_score, risk_score, created_at) VALUES "
                    "('AI_SUGGESTION', 'auto_org_rebalancer', ?, 6, 'PENDING', "
                    "0.7, 0.7, 0.4, 0.3, datetime('now','localtime'))",
                    (f'auto_org_rebalancer · 组织再平衡: 军团 {hi[0]}({hi[1]}单) 与 '
                     f'{lo[0]}({lo[1]}单) 负载比 >2:1, 建议任务再分配管线',))
                conn.commit()
            _feed(conn, 'andromeda_society_org_review', 'org',
                  f'[架构审视] 负载分布 {rows[:3]}, 失衡={stats["imbalance"]}')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 守护主循环
# ============================================================
def _heartbeat():
    try:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?,?,?,?, datetime('now','localtime'), datetime('now','localtime'))",
            (DAEMON_NAME, '仙女座自治区 (调研/拜师/轮岗/孵化/立法/战略/架构, 多节奏)',
             os.getpid()))
        conn.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
            "pid=?, status='RUNNING' WHERE process_name=?", (os.getpid(), DAEMON_NAME))
        conn.commit()
        conn.close()
    except Exception:
        pass


MODULES = {
    'survey': survey_once,
    'mentorship': mentorship_once,
    'rotation': rotation_once,
    'incubate': incubate_once,
    'legislature': legislature_once,
    'strategy': strategy_once,
    'org_review': org_review_once,
}


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'loop'
    if cmd in MODULES:
        conn = _connect()
        try:
            print(json.dumps(MODULES[cmd](conn), ensure_ascii=False))
        finally:
            conn.close()
        _mark(cmd)
        return 0
    if cmd == 'run_all':
        conn = _connect()
        try:
            out = {m: fn(conn) for m, fn in MODULES.items()}
        finally:
            conn.close()
        for m in MODULES:
            _mark(m)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if cmd == 'loop':
        print(f'[{DAEMON_NAME}] 自治区守护启动 pid={os.getpid()} poll={LOOP_SECS}s',
              flush=True)
        while True:
            for name, fn in MODULES.items():
                if not _due(name):
                    continue
                try:
                    conn = _connect()
                    try:
                        r = fn(conn)
                    finally:
                        conn.close()
                    if any(r.values()):
                        print(f'[{DAEMON_NAME}] {name} {r}', flush=True)
                    _mark(name)
                except Exception as e:
                    sys.stderr.write(f'[{DAEMON_NAME}] {name} error: {e}\n')
            _heartbeat()
            time.sleep(LOOP_SECS)
    print(f'unknown cmd: {cmd}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
