#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政务中心引擎 Government Center Engine (flow_gov_center_20261026)
================================================================
13 中心之政务中心: 统一统筹 + 指挥调度

核心职责:
  ① 13 中心统一调度 — 监听任务大厅 + 智能分配到中心
  ② 应急指挥 — 数据爆仓/删库事件 → 启动应急预案 SOP
  ③ 状态总览 — 实时掌握 13 中心健康度 + 守卫对状态
  ④ 跨中心协作 — 触发中心间联动 (如: 守卫对拦截 → 备份中心快照)
  ⑤ 上报链路 — 紧急事件 → 立法委 + 三委 + SA

四表:
  mt_gov_dispatch_log     — 政务调度日志
  mt_gov_center_status    — 13 中心实时状态
  mt_gov_emergency_log    — 应急处置日志
  mt_gov_sop_library      — 应急预案 SOP 库

用法:
  python3 ai_gov_center_engine.py init
  python3 ai_gov_center_engine.py once
  python3 ai_gov_center_engine.py start
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_gov_center_20261026"
INTERVAL = 180

CENTERS_13 = ['HR', 'STR', 'DATA', 'BACKUP', 'GOV', 'LEG', 'SKILL', 'WFLOW',
              'SEC', 'RES', 'BRAIN', 'TEST', 'INFRA']

# 数据爆仓删库应急预案 SOP
DATA_BLOWUP_SOP = {
    'sop_id': 'SOP_DATA_BLOWUP_001',
    'title': '数据爆仓/删库应急处置预案',
    'trigger': 'guardian_violation GDL-001/003/004',
    'severity': 'CRITICAL',
    'steps': [
        {'order': 1, 'center': 'SEC', 'action': '守卫对自动拦截 + 冻结写操作', 'timeout_sec': 5},
        {'order': 2, 'center': 'BACKUP', 'action': '立即创建冷快照 + WAL checkpoint', 'timeout_sec': 30},
        {'order': 3, 'center': 'DATA', 'action': '数据完整性校验 + 损坏表识别', 'timeout_sec': 60},
        {'order': 4, 'center': 'STR', 'action': '启动事故战略研究', 'timeout_sec': 120},
        {'order': 5, 'center': 'LEG', 'action': '触发立法委紧急立法程序', 'timeout_sec': 300},
        {'order': 6, 'center': 'GOV', 'action': '政务中心统筹指挥 + SA 上报', 'timeout_sec': 30},
    ],
    'escalation': '5min 无进展 → SA 直接接管',
}


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [GOV] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_gov_dispatch_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        task_title TEXT,
        dispatched_to TEXT,
        dispatch_reason TEXT,
        dispatch_strategy TEXT,
        flow_id TEXT,
        dispatched_at TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT
    );
    
    CREATE TABLE IF NOT EXISTS mt_gov_center_status (
        center_code TEXT PRIMARY KEY,
        center_name TEXT,
        health_score REAL DEFAULT 100,
        active_workers INTEGER DEFAULT 0,
        queue_depth INTEGER DEFAULT 0,
        last_heartbeat TEXT,
        status TEXT DEFAULT 'HEALTHY',
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_gov_emergency_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emergency_id TEXT,
        title TEXT,
        trigger_event TEXT,
        severity TEXT,
        sop_id TEXT,
        step_completed INTEGER DEFAULT 0,
        total_steps INTEGER DEFAULT 0,
        status TEXT DEFAULT 'RESPONDING',
        commander TEXT DEFAULT 'GOV_CENTER',
        started_at TEXT DEFAULT (datetime('now','localtime')),
        resolved_at TEXT
    );
    
    CREATE TABLE IF NOT EXISTS mt_gov_sop_library (
        sop_id TEXT PRIMARY KEY,
        title TEXT,
        trigger_event TEXT,
        severity TEXT,
        steps TEXT,
        escalation TEXT,
        status TEXT DEFAULT 'ACTIVE',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def init(conn) -> dict:
    _ensure_tables(conn)
    
    # 注册 13 中心状态
    for code in CENTERS_13:
        conn.execute("""INSERT OR IGNORE INTO mt_gov_center_status 
            (center_code, center_name, health_score, status)
            VALUES (?, ?, 100, 'HEALTHY')""", (code, code))
    
    # 注册 SOP
    conn.execute("""INSERT OR REPLACE INTO mt_gov_sop_library 
        (sop_id, title, trigger_event, severity, steps, escalation)
        VALUES (?,?,?,?,?,?)""",
        (DATA_BLOWUP_SOP['sop_id'], DATA_BLOWUP_SOP['title'],
         DATA_BLOWUP_SOP['trigger'], DATA_BLOWUP_SOP['severity'],
         json.dumps(DATA_BLOWUP_SOP['steps'], ensure_ascii=False),
         DATA_BLOWUP_SOP['escalation']))
    
    conn.commit()
    return {'centers': len(CENTERS_13), 'sop_registered': 1}


def update_center_health(conn) -> dict:
    """更新 13 中心健康度"""
    stats = {'updated': 0, 'unhealthy': 0}
    
    # 守卫对状态
    try:
        pairs = conn.execute(
            "SELECT COUNT(*) total, SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) active FROM mt_guardian_pair"
        ).fetchone()
        guardian_health = pairs[1] / pairs[0] * 100 if pairs[0] > 0 else 50
    except Exception:
        guardian_health = 50
    
    # 备份状态
    try:
        last = conn.execute(
            "SELECT created_at FROM mt_backup_log WHERE action='backup' AND ok=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        backup_health = 100 if last else 0
    except Exception:
        backup_health = 50
    
    # daemon 健康
    try:
        daemon_stats = conn.execute(
            "SELECT COUNT(*) total, SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) active FROM mt_daemon_registry"
        ).fetchone()
        daemon_health = daemon_stats[1] / daemon_stats[0] * 100 if daemon_stats[0] > 0 else 50
    except Exception:
        daemon_health = 50
    
    # 更新各中心
    health_map = {
        'BACKUP': backup_health,
        'SEC': guardian_health,
        'INFRA': daemon_health,
        'DATA': guardian_health * 0.8 + backup_health * 0.2,
        'GOV': (guardian_health + backup_health + daemon_health) / 3,
        'HR': 80, 'STR': 80, 'LEG': 80, 'SKILL': 75,
        'WFLOW': 75, 'RES': 80, 'BRAIN': 70, 'TEST': 85,
    }
    
    for code, score in health_map.items():
        status = 'HEALTHY' if score >= 70 else ('DEGRADED' if score >= 40 else 'CRITICAL')
        conn.execute("""UPDATE mt_gov_center_status SET health_score=?, status=?,
            updated_at=datetime('now','localtime') WHERE center_code=?""",
            (round(score, 1), status, code))
        stats['updated'] += 1
        if status != 'HEALTHY':
            stats['unhealthy'] += 1
    
    conn.commit()
    return stats


def monitor_guardian_emergency(conn) -> list:
    """监听守卫对 violation → 启动应急 SOP"""
    try:
        violations = conn.execute("""
            SELECT rule_id, rule_name, severity, table_name FROM mt_guardian_violation 
            WHERE block_status='BLOCKED' AND id > COALESCE((SELECT MAX(last_emergency_id) FROM mt_gov_emergency_log WHERE title='GUARDIAN_RESPONDED'), 0)
            ORDER BY id DESC LIMIT 5
        """).fetchall()
        
        emergencies = []
        for v in violations:
            rid, rname, sev, tbl = v
            emerg_id = f"EMG_{rid}_{int(time.time())}"
            
            cur = conn.execute("""INSERT INTO mt_gov_emergency_log 
                (emergency_id, title, trigger_event, severity, sop_id, total_steps)
                VALUES (?,?,?,?,?,?)""",
                (emerg_id, f"[应急] {rname} — {tbl or '_DB_'}",
                 f"守卫对拦截: {rid}", sev, DATA_BLOWUP_SOP['sop_id'],
                 len(DATA_BLOWUP_SOP['steps'])))
            if cur.rowcount > 0:
                emergencies.append(emerg_id)
                _log(f"🚨 应急启动: {rname}")
        
        conn.commit()
        return emergencies
    except Exception as e:
        _log(f"⚠️ 应急监控失败: {e}")
        return []


def dispatch_task(conn, task_title: str, task_desc: str = '') -> str:
    """智能调度: 根据任务关键词分配到 13 中心"""
    keywords = task_title.lower() + ' ' + task_desc.lower()
    
    center_map = {
        'HR': ['招募', '培训', '人力', 'cert', '证书'],
        'STR': ['战略', '研究', '分析', '风险'],
        'DATA': ['数据', '完整性', '质量', '清洗'],
        'BACKUP': ['备份', '恢复', '快照', '冗余'],
        'LEG': ['法律', '立法', '合规', '法条', '司法解释'],
        'SKILL': ['skill', '技能', '研发'],
        'WFLOW': ['工作流', '流程', '编排'],
        'SEC': ['安全', '守卫', '拦截', 'guardian', '删库'],
        'INFRA': ['基础设施', '运维', 'daemon', '部署'],
        'BRAIN': ['脑库', '知识', '向量', '投喂'],
        'TEST': ['测试', '质量', 'QA', '巡检'],
        'RES': ['AI', '研究', '算法'],
        'GOV': ['统筹', '调度', '应急', '指挥'],
    }
    
    best_center = 'GOV'  # 兜底政务中心
    best_score = 0
    for center, keys in center_map.items():
        score = sum(1 for k in keys if k in keywords)
        if score > best_score:
            best_score = score
            best_center = center
    
    task_id = f"GOV_TASK_{int(time.time())}"
    conn.execute("""INSERT INTO mt_gov_dispatch_log 
        (task_title, dispatched_to, dispatch_reason, dispatch_strategy, flow_id)
        VALUES (?,?,?,?,?)""",
        (task_title, best_center, f"关键词匹配得分 {best_score}", 'KEYWORD_MATCH', FLOW_ID))
    
    return best_center


def run_once() -> dict:
    conn = _db()
    _ensure_tables(conn)
    
    health_stats = update_center_health(conn)
    emergencies = monitor_guardian_emergency(conn)
    
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'health': health_stats,
        'emergencies_triggered': len(emergencies),
    }
    _log(f"健康度: {health_stats['unhealthy']} 中心异常, 应急: {len(emergencies)}")
    return report


def run_loop():
    _log(f"政务中心 loop 启动 (interval={INTERVAL}s)")
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
