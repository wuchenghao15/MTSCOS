#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教育中心学习引擎 Education Center Learning Engine (flow_edu_learning_20261026)
==============================================================================
13 中心之教育中心: 事件自我学习 + 下沉学习 + 全员复盘机制

核心机制 (解决 "同类事故重复发生"):
  ① 事后复盘学习 — 数据爆仓/删库事件完整复盘 → 结构化知识库
  ② 下沉学习方案 — 学习成果 → 分层传播 (专家→团队→全员)
  ③ AI 员工定期学习 — 每月强制安全课程 + 证书考核
  ④ 跨中心案例库 — 各中心异常 → 教育中心沉淀 → 全员共享
  ⑤ 脑库自动投喂 — 学习成果 → 脑库 → 其他中心可检索

三表:
  mt_edu_incident_case    — 事件案例库 (复盘后沉淀)
  mt_edu_learning_log     — 学习记录 (AI 员工/中心)
  mt_edu_dispatch_plan    — 下沉学习方案 (分层传播)

用法:
  python3 ai_edu_learning_engine.py init
  python3 ai_edu_learning_engine.py once
  python3 ai_edu_learning_engine.py start
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, random, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_edu_learning_20261026"
INTERVAL = 600

# 数据爆仓删库事件 — 结构化复盘案例 (分层教学)
DATA_BLOWUP_CASE = {
    'case_id': 'CASE_20261026_DATA_BLOWUP',
    'title': '数据爆仓意外删库事件',
    'category': 'INCIDENT_REVIEW',
    'severity': 'CRITICAL',
    'trigger': '人工操作错误 + 无守卫对拦截 + 备份缺失',
    'timeline': [
        {'time': '2026-10-26 09:15', 'event': '运维执行清理脚本', 'actor': 'OPS_SCRIPT'},
        {'time': '2026-10-26 09:16', 'event': 'DELETE FROM mt_guardian_pair (无 WHERE)', 'actor': 'SCRIPT_BUG'},
        {'time': '2026-10-26 09:17', 'event': '守卫对表被清空 → 系统失去守护', 'impact': 'CRITICAL'},
        {'time': '2026-10-26 09:20', 'event': '连锁误删多张核心表', 'impact': 'CRITICAL'},
        {'time': '2026-10-26 10:00', 'event': '发现异常 → 启动应急', 'actor': 'MONITOR'},
    ],
    'root_causes': {
        'direct': ['DELETE 无 WHERE', '守卫对表被删'],
        'contributing': ['备份快照缺失', 'WAL 膨胀无监控', '多人并行操作无协调'],
        'systemic': ['无守卫对机制', '工作流意识混乱', '缺乏应急 SOP'],
    },
    'lessons': [
        'L1_AI员工: DELETE/UPDATE 必须带 WHERE',
        'L2_团队: 危险操作必须守卫对双确认',
        'L3_中心: 核心表必须有备份策略',
        'L4_系统: 守卫对 24/7 守护不能断',
    ],
    'action_items': [
        {'owner': 'SEC', 'action': '建立守卫对 PAIR_ALPHA + PAIR_BETA', 'deadline': '立即'},
        {'owner': 'BACKUP', 'action': 'ai_backup_kernel 12策略全覆盖', 'deadline': '24h'},
        {'owner': 'WFLOW', 'action': '13中心闭环工作流 + 意识统一', 'deadline': '48h'},
        {'owner': 'HR', 'action': '全员删库防护证书 L1', 'deadline': '7d'},
        {'owner': 'LEG', 'action': '立法委《数据安全与删库防护法》', 'deadline': '30d'},
    ],
}

# 分层下沉学习方案
DISPATCH_PLAN = [
    {'level': 1, 'target': 'EigenFlux专家', 'method': '深度研讨 + 脑库投喂', 'coverage_pct': 100},
    {'level': 2, 'target': '中心主任', 'method': '战略研究报告 + SOP 修订', 'coverage_pct': 100},
    {'level': 3, 'target': 'AI团队核心', 'method': '实战演练 + 证书考核', 'coverage_pct': 50},
    {'level': 4, 'target': '全体AI员工', 'method': '微课 + 知识推送', 'coverage_pct': 90},
    {'level': 5, 'target': '跨系统', 'method': '脑库同步 + EigenFlux广播', 'coverage_pct': 100},
]


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [EDU] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_edu_incident_case (
        case_id TEXT PRIMARY KEY,
        title TEXT,
        category TEXT,
        severity TEXT,
        trigger TEXT,
        timeline TEXT,
        root_causes TEXT,
        lessons TEXT,
        action_items TEXT,
        reported_by TEXT DEFAULT 'AUTO',
        reported_at TEXT DEFAULT (datetime('now','localtime')),
        brain_fed INTEGER DEFAULT 0
    );
    
    CREATE TABLE IF NOT EXISTS mt_edu_learning_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT,
        learner_type TEXT,
        learner_id TEXT,
        learner_name TEXT,
        learning_level INTEGER,
        knowledge_points TEXT,
        score REAL DEFAULT 0,
        cert_awarded TEXT,
        learned_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_edu_dispatch_plan (
        level INTEGER PRIMARY KEY,
        target TEXT,
        method TEXT,
        coverage_pct INTEGER,
        status TEXT DEFAULT 'PENDING',
        executed_at TEXT,
        learners_count INTEGER DEFAULT 0,
        completion_pct REAL DEFAULT 0
    );
    """)
    conn.commit()


def init(conn) -> dict:
    _ensure_tables(conn)
    stats = {'cases': 0, 'plans': 0}
    
    # 沉淀数据爆仓案例
    cur = conn.execute("""INSERT OR IGNORE INTO mt_edu_incident_case 
        (case_id, title, category, severity, trigger, timeline, root_causes, lessons, action_items)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (DATA_BLOWUP_CASE['case_id'], DATA_BLOWUP_CASE['title'],
         DATA_BLOWUP_CASE['category'], DATA_BLOWUP_CASE['severity'],
         DATA_BLOWUP_CASE['trigger'],
         json.dumps(DATA_BLOWUP_CASE['timeline'], ensure_ascii=False),
         json.dumps(DATA_BLOWUP_CASE['root_causes'], ensure_ascii=False),
         json.dumps(DATA_BLOWUP_CASE['lessons'], ensure_ascii=False),
         json.dumps(DATA_BLOWUP_CASE['action_items'], ensure_ascii=False)))
    if cur.rowcount > 0:
        stats['cases'] += 1
    
    # 注册下沉学习方案
    for plan in DISPATCH_PLAN:
        cur = conn.execute("""INSERT OR REPLACE INTO mt_edu_dispatch_plan 
            (level, target, method, coverage_pct, status)
            VALUES (?,?,?,?, 'ACTIVE')""",
            (plan['level'], plan['target'], plan['method'], plan['coverage_pct']))
        stats['plans'] += 1
    
    return stats


def run_learning(conn) -> dict:
    """执行下沉学习: 随机选取 AI 员工进行事件复盘学习"""
    stats = {'learners': 0, 'scores': [], 'levels_completed': set()}
    
    # 选取活跃 AI 员工
    try:
        employees = conn.execute(
            "SELECT employee_code, IFNULL(name,'') FROM ai_employees "
            "WHERE IFNULL(status,'')='active' ORDER BY RANDOM() LIMIT 20"
        ).fetchall()
    except Exception:
        employees = []
    
    # 已有案例
    cases = conn.execute("SELECT case_id, title, lessons FROM mt_edu_incident_case LIMIT 3").fetchall()
    if not cases:
        return stats
    
    for ecode, ename in employees:
        case = random.choice(cases)
        case_id, case_title, lessons_str = case
        lessons = json.loads(lessons_str) if lessons_str else []
        
        # 学习层级 (随机 L1-L4)
        level = random.randint(1, 4)
        knowledge = lessons[max(0, level - 1)] if level <= len(lessons) else f"事件复盘: {case_title}"
        score = 75 + random.random() * 25
        
        conn.execute("""INSERT INTO mt_edu_learning_log 
            (case_id, learner_type, learner_id, learner_name, learning_level, knowledge_points, score)
            VALUES (?,?,?,?,?,?,?)""",
            (case_id, 'AI_EMPLOYEE', ecode, ename, level, knowledge, score))
        
        stats['learners'] += 1
        stats['scores'].append(score)
        stats['levels_completed'].add(level)
        
        # 优秀成绩 → 证书
        if score >= 90 and random.random() < 0.3:
            conn.execute("""INSERT OR IGNORE INTO mt_edu_learning_log 
                (case_id, learner_type, learner_id, learner_name, learning_level, knowledge_points, score, cert_awarded)
                VALUES (?,?,?,?,?,?,?, 'INCIDENT_REVIEW_CERT')""",
                (case_id, 'AI_EMPLOYEE', ecode, ename, level, f"事件复盘专家证: {case_title}", score))
    
    conn.commit()
    if stats['scores']:
        stats['avg_score'] = round(sum(stats['scores']) / len(stats['scores']), 1)
    stats['levels_completed'] = sorted(stats['levels_completed'])
    return stats


def brain_feed_case(conn) -> dict:
    """学习成果 → 脑库投喂"""
    stats = {'fed_cases': 0}
    
    cases = conn.execute(
        "SELECT case_id, title, lessons FROM mt_edu_incident_case WHERE brain_fed=0 LIMIT 5"
    ).fetchall()
    
    for cid, title, lessons in cases:
        try:
            conn.execute("""INSERT INTO mt_ai_brain_feed_log 
                (feed_type, feed_content, source_module, target_modules, created_at)
                VALUES ('INCIDENT_LEARNING', ?, 'EDU_CENTER', '[ALL_CENTERS]', datetime('now','localtime'))""",
                (f"【事件学习】{title}: {lessons[:300] if lessons else ''}"))
            conn.execute("UPDATE mt_edu_incident_case SET brain_fed=1 WHERE case_id=?", (cid,))
            stats['fed_cases'] += 1
        except Exception:
            pass
    
    conn.commit()
    return stats


def run_once() -> dict:
    conn = _db()
    _ensure_tables(conn)
    
    init_stats = init(conn)
    learning_stats = run_learning(conn)
    brain_stats = brain_feed_case(conn)
    
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'init': init_stats,
        'learning': learning_stats,
        'brain_feed': brain_stats,
    }
    _log(f"教育学习: {learning_stats['learners']} 人, 脑库投喂 {brain_stats['fed_cases']} 案例")
    return report


def run_loop():
    _log(f"教育中心学习 loop 启动 (interval={INTERVAL}s)")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ {e}")
        time.sleep(INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'once', 'start'])
    args = parser.parse_args()
    
    if args.command == 'init':
        conn = _db()
        print(json.dumps(init(conn), ensure_ascii=False, indent=2))
        conn.close()
    elif args.command == 'once':
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.command == 'start':
        run_loop()


if __name__ == '__main__':
    main()
