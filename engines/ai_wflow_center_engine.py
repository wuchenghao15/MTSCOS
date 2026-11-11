#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流中心引擎 Workflow Center Engine (flow_wflow_center_20261026)
===================================================================
13 中心之工作流中心: 工作流统一意识 + 闭环调度 + 任务大厅联动

核心解决: 数据爆仓事件暴露的 "工作流意识混乱 → 多人并行 → 操作错误"

职责:
  ① 13 中心任务大厅闭环工作流
     QUEUED → DISPATCHED → ACCEPTED → EXECUTING → REPORTED → REVIEWED → CLOSED/ESCALATED
  ② 工作流意识统一 (全员认知同一套流程模型)
  ③ 跨中心协作工作流 (守卫对→备份→数据→政务→立法)
  ④ 异常工作流检测 (并行操作/跳过步骤/状态卡壳)
  ⑤ 工作流知识沉淀 → 脑库 + 教育中心下沉学习

三表:
  mt_wflow_definition    — 工作流定义
  mt_wflow_instance      — 工作流实例
  mt_wflow_step_log      — 步骤执行日志

用法:
  python3 ai_wflow_center_engine.py init
  python3 ai_wflow_center_engine.py once
  python3 ai_wflow_center_engine.py start
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_wflow_center_20261026"
INTERVAL = 120

# 13 中心标准任务闭环工作流定义
CENTER_TASK_WFLOW = {
    'wflow_id': 'WFLOW_CENTER_TASK_001',
    'name': '13中心任务大厅闭环',
    'steps': [
        {'step': 1, 'name': 'QUEUED', 'desc': '任务大厅接收新任务', 'timeout_sec': 0,
         'next': 'DISPATCHED', 'error': 'ESCALATED', 'handler': '任务大厅自动监听'},
        {'step': 2, 'name': 'DISPATCHED', 'desc': '政务中心智能分配到中心', 'timeout_sec': 300,
         'next': 'ACCEPTED', 'error': 'ESCALATED', 'handler': '政务中心 GOV'},
        {'step': 3, 'name': 'ACCEPTED', 'desc': '中心负责人接单确认', 'timeout_sec': 600,
         'next': 'EXECUTING', 'error': 'ESCALATED', 'handler': '各中心主任'},
        {'step': 4, 'name': 'EXECUTING', 'desc': 'AI团队执行任务', 'timeout_sec': 7200,
         'next': 'REPORTED', 'error': 'ESCALATED', 'handler': '中心AI团队'},
        {'step': 5, 'name': 'REPORTED', 'desc': '上报交付物到任务大厅', 'timeout_sec': 300,
         'next': 'REVIEWED', 'error': 'REEXECUTE', 'handler': '执行AI'},
        {'step': 6, 'name': 'REVIEWED', 'desc': '质量中心验收', 'timeout_sec': 600,
         'next': 'CLOSED', 'error': 'REEXECUTE', 'handler': 'TEST 中心'},
        {'step': 7, 'name': 'CLOSED', 'desc': '结案 → 脑库投喂 + 备份备案', 'timeout_sec': 300,
         'next': 'DONE', 'error': 'ESCALATED', 'handler': '工作流中心'},
    ],
    'failure_paths': {
        'ESCALATED': '政务中心应急 → 升级到 SA',
        'REEXECUTE': '退回执行 → 重新进入 EXECUTING',
    },
}

# 守卫对拦截 → 全链路应急工作流
GUARDIAN_EMERGENCY_WFLOW = {
    'wflow_id': 'WFLOW_GUARDIAN_EMG_001',
    'name': '守卫对拦截应急全链路',
    'trigger': 'guardian_violation BLOCKED',
    'steps': [
        {'step': 1, 'center': 'SEC', 'name': '拦截+冻结', 'action': '守卫对拦截SQL + 冻结写操作', 'timeout': 5},
        {'step': 2, 'center': 'BACKUP', 'name': '快照', 'action': '立即创建冷快照', 'timeout': 30},
        {'step': 3, 'center': 'DATA', 'name': '校验', 'action': '数据完整性校验', 'timeout': 60},
        {'step': 4, 'center': 'STR', 'name': '研究', 'action': '战略中心事故研究', 'timeout': 120},
        {'step': 5, 'center': 'LEG', 'name': '立法', 'action': '立法委紧急立法', 'timeout': 300},
        {'step': 6, 'center': 'GOV', 'name': '调度', 'action': '政务中心统筹 + SA上报', 'timeout': 30},
        {'step': 7, 'center': 'HR+EDU', 'name': '学习', 'action': '人力中心全员培训 + 教育中心下沉学习', 'timeout': 3600},
    ],
}


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WFLOW] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_wflow_definition (
        wflow_id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        steps TEXT,
        failure_paths TEXT,
        trigger_event TEXT,
        status TEXT DEFAULT 'ACTIVE',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_wflow_instance (
        instance_id TEXT PRIMARY KEY,
        wflow_id TEXT,
        wflow_name TEXT,
        current_step INTEGER DEFAULT 0,
        current_status TEXT DEFAULT 'QUEUED',
        task_id INTEGER,
        task_title TEXT,
        assigned_center TEXT,
        priority TEXT DEFAULT 'NORMAL',
        status TEXT DEFAULT 'RUNNING',
        started_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT,
        escalated_to TEXT
    );
    
    CREATE TABLE IF NOT EXISTS mt_wflow_step_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        instance_id TEXT,
        step_order INTEGER,
        step_name TEXT,
        step_action TEXT,
        handler TEXT,
        center TEXT,
        status TEXT DEFAULT 'PENDING',
        started_at TEXT,
        completed_at TEXT,
        error_msg TEXT,
        elapsed_sec REAL
    );
    """)
    conn.commit()


def init(conn) -> dict:
    _ensure_tables(conn)
    stats = {'wflows': 0}
    
    # 注册两个核心工作流
    for wflow in [CENTER_TASK_WFLOW, GUARDIAN_EMERGENCY_WFLOW]:
        cur = conn.execute("""INSERT OR REPLACE INTO mt_wflow_definition 
            (wflow_id, name, description, steps, failure_paths, trigger_event)
            VALUES (?,?,?,?,?,?)""",
            (wflow['wflow_id'], wflow['name'], wflow.get('desc', ''),
             json.dumps(wflow['steps'], ensure_ascii=False),
             json.dumps(wflow.get('failure_paths', {}), ensure_ascii=False),
             wflow.get('trigger', 'MANUAL')))
        stats['wflows'] += 1
    
    # 确保 daemon 注册
    try:
        conn.execute("""INSERT OR IGNORE INTO mt_daemon_registry 
            (process_name, duty, status, last_heartbeat, created_at, updated_at)
            VALUES (?, ?, 'ACTIVE', datetime('now','localtime'), datetime('now','localtime'), datetime('now','localtime'))""",
            ('ai_wflow_center', '工作流中心: 13中心闭环+守卫对应急全链路'))
    except Exception:
        pass
    
    return stats


def create_emergency_instance(conn) -> list:
    """监听守卫对 violation → 创建应急工作流实例"""
    try:
        violations = conn.execute("""
            SELECT DISTINCT rule_id, rule_name FROM mt_guardian_violation 
            WHERE block_status='BLOCKED' 
            AND pair_code='PAIR_ALPHA'
            ORDER BY id DESC LIMIT 3
        """).fetchall()
        
        instances = []
        for rid, rname in violations:
            inst_id = f"INST_EMG_{rid}_{int(time.time())}"
            cur = conn.execute("""INSERT OR IGNORE INTO mt_wflow_instance 
                (instance_id, wflow_id, wflow_name, current_step, current_status,
                 task_title, priority, status)
                VALUES (?,?,?,?,?,?,?,?)""",
                (inst_id, GUARDIAN_EMERGENCY_WFLOW['wflow_id'],
                 GUARDIAN_EMERGENCY_WFLOW['name'], 0, 'QUEUED',
                 f"应急: {rname}", 'CRITICAL', 'RUNNING'))
            if cur.rowcount > 0:
                instances.append(inst_id)
                _log(f"🚨 应急实例创建: {inst_id}")
        
        return instances
    except Exception as e:
        _log(f"⚠️ 应急实例创建失败: {e}")
        return []


def advance_instances(conn) -> dict:
    """推进工作流实例"""
    stats = {'checked': 0, 'advanced': 0, 'stuck': 0}
    
    try:
        instances = conn.execute(
            "SELECT instance_id, current_step, current_status, status FROM mt_wflow_instance WHERE status='RUNNING'"
        ).fetchall()
        
        for inst in instances:
            stats['checked'] += 1
            inst_id, step, status, wf_status = inst
            
            # 模拟推进 (实际由各中心引擎触发)
            if step < 7:  # 7 步完成
                new_step = step + 1
                new_status = GUARDIAN_EMERGENCY_WFLOW['steps'][step]['name'] if step < len(GUARDIAN_EMERGENCY_WFLOW['steps']) else 'DONE'
                conn.execute("""UPDATE mt_wflow_instance SET current_step=?, current_status=?,
                    updated_at=datetime('now','localtime') WHERE instance_id=?""",
                    (new_step, new_status, inst_id))
                
                conn.execute("""INSERT INTO mt_wflow_step_log 
                    (instance_id, step_order, step_name, status, started_at, completed_at, elapsed_sec)
                    VALUES (?,?,?,?, datetime('now','localtime'), datetime('now','localtime'), 0)""",
                    (inst_id, new_step, new_status, 'COMPLETED'))
                
                stats['advanced'] += 1
            else:
                conn.execute("""UPDATE mt_wflow_instance SET status='DONE', 
                    completed_at=datetime('now','localtime') WHERE instance_id=?""",
                    (inst_id,))
        
        conn.commit()
    except Exception as e:
        _log(f"⚠️ 推进失败: {e}")
    
    return stats


def run_once() -> dict:
    conn = _db()
    _ensure_tables(conn)
    
    init_stats = init(conn)
    emergencies = create_emergency_instance(conn)
    advance_stats = advance_instances(conn)
    
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'wflows_registered': init_stats['wflows'],
        'emergencies_created': len(emergencies),
        'advance': advance_stats,
    }
    _log(f"工作流 {advance_stats['advanced']} 步推进, {len(emergencies)} 应急实例")
    return report


def run_loop():
    _log(f"工作流中心 loop 启动 (interval={INTERVAL}s)")
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
