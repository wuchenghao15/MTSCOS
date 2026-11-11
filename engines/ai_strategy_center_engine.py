#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
战略中心引擎 Strategy Center Engine (flow_strategy_center_20261026)
====================================================================
13 中心之战略中心: 异常/事故针对性战略研究

核心产出:
  ① 数据爆仓/删库事故复盘报告 (深度分析)
  ② 风险地图 (HIGH/MEDIUM/LOW 三级)
  ③ 应急预案 SOP (标准作业程序)
  ④ 战略研究 → 立法委 + 政务中心 上报链路
  ⑤ 主动风险预警 (守护对 violation 实时研究)

两表:
  mt_strategy_research    — 战略研究报告
  mt_strategy_risk_map    — 风险地图

用法:
  python3 ai_strategy_center_engine.py init
  python3 ai_strategy_center_engine.py once
  python3 ai_strategy_center_engine.py start
"""
from __future__ import annotations

import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_strategy_center_20261026"
DAEMON = "ai_strategy_center"
INTERVAL = 1200

# 数据爆仓/删库事件元数据
DATA_BLOWUP_EVENT = {
    'event_id': 'EVT_20261026_DATA_BLOWUP',
    'title': '数据爆仓意外删库事件',
    'severity': 'CRITICAL',
    'root_causes': [
        '单节点备份缺失 → 无冷备兜底',
        '工作流意识混乱 → 操作顺序错误',
        '缺乏守卫对 → DROP/DELETE 无拦截',
        '磁盘空间监控缺失 → WAL 膨胀',
        '批量 DELETE 无 WHERE → 误删全表',
    ],
    'lessons_learned': [
        '必须建立守卫对双AI守护机制',
        '必须 12 种备份策略全覆盖',
        '工作流中心必须统一意识',
        '人力资源必须培训删库防护',
        '立法委必须出台数据安全法律',
    ],
    'mitigations': [
        '建立 PAIR_ALPHA + PAIR_BETA 守卫对',
        '启用 ai_backup_kernel 12 策略互锁',
        '工作流中心统一认知到执行闭环',
        '人力中心删库防护全员证书',
        '立法委起草《数据安全与删库防护法》',
    ],
}


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [STRATEGY] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_strategy_research (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        research_id TEXT UNIQUE,
        title TEXT,
        category TEXT,
        severity TEXT DEFAULT 'MEDIUM',
        event_id TEXT,
        root_causes TEXT,
        lessons_learned TEXT,
        mitigations TEXT,
        risk_level TEXT DEFAULT 'MEDIUM',
        status TEXT DEFAULT 'PUBLISHED',
        flow_id TEXT,
        published_at TEXT DEFAULT (datetime('now','localtime')),
        reported_to_committee INTEGER DEFAULT 0,
        brain_fed INTEGER DEFAULT 0
    );
    
    CREATE TABLE IF NOT EXISTS mt_strategy_risk_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        risk_code TEXT UNIQUE,
        risk_name TEXT,
        category TEXT,
        current_level TEXT DEFAULT 'LOW',
        trigger_threshold TEXT,
        mitigation_strategy TEXT,
        owner_center TEXT,
        last_updated TEXT DEFAULT (datetime('now','localtime')),
        status TEXT DEFAULT 'MONITORING'
    );
    """)
    conn.commit()


def init(conn) -> dict:
    """初始化: 数据爆仓事件复盘 + 风险地图"""
    _ensure_tables(conn)
    stats = {'researches': 0, 'risks': 0}
    
    # 数据爆仓复盘
    cur = conn.execute("""INSERT OR IGNORE INTO mt_strategy_research 
        (research_id, title, category, severity, event_id, root_causes, lessons_learned, 
         mitigations, risk_level, flow_id, reported_to_committee)
        VALUES (?,?,?,?,?,?,?,?,?, ?, 1)""",
        (DATA_BLOWUP_EVENT['event_id'] + '_REVIEW',
         DATA_BLOWUP_EVENT['title'] + ' — 深度复盘报告',
         'INCIDENT_REVIEW', DATA_BLOWUP_EVENT['severity'],
         DATA_BLOWUP_EVENT['event_id'],
         json.dumps(DATA_BLOWUP_EVENT['root_causes'], ensure_ascii=False),
         json.dumps(DATA_BLOWUP_EVENT['lessons_learned'], ensure_ascii=False),
         json.dumps(DATA_BLOWUP_EVENT['mitigations'], ensure_ascii=False),
         'CRITICAL', FLOW_ID))
    if cur.rowcount > 0:
        stats['researches'] += 1
    
    # 风险地图 10 项
    risks = [
        ('RSK_BACKUP_GAP', '备份策略缺口', 'DATA', 'CRITICAL', '24h无备份快照', 'ai_backup_kernel 12策略全覆盖', 'BACKUP'),
        ('RSK_GUARDIAN_DOWN', '守卫对离线', 'SECURITY', 'HIGH', '守卫对心跳超时3轮', '单守卫接管+政务中心告警', 'SEC'),
        ('RSK_WAL_BLOAT', 'WAL膨胀', 'STORAGE', 'MEDIUM', 'WAL>DB 50%', '自动checkpoint+备份', 'INFRA'),
        ('RSK_NO_WHERE_DEL', '无WHERE删除', 'DATA', 'CRITICAL', 'DELETE FROM无WHERE', '守卫对SQL拦截', 'DATA'),
        ('RSK_DISK_FULL', '磁盘满', 'STORAGE', 'HIGH', '剩余<10%', '只读模式+自动清理', 'INFRA'),
        ('RSK_WFLOW_CONFUSION', '工作流混乱', 'PROCESS', 'HIGH', '多人并行操作', '工作流中心统一调度', 'WFLOW'),
        ('RSK_SKILL_GAP', '技能缺口', 'HR', 'MEDIUM', '证书覆盖<30%', '人力中心培训', 'HR'),
        ('RSK_EMG_NO_RESPONSE', '无应急预案', 'EMERGENCY', 'HIGH', '事故响应>10min', '政务中心SOP调度', 'GOV'),
        ('RSK_BRAIN_EMPTY', '脑库空', 'KNOWLEDGE', 'LOW', '投喂率<10%', 'EigenFlux主动投喂', 'BRAIN'),
        ('RSK_DAEMON_DOWN', 'daemon离线', 'INFRA', 'HIGH', '心跳超时', '智能挂载自动修复', 'INFRA'),
    ]
    
    for code, name, cat, level, threshold, mit, owner in risks:
        cur = conn.execute("""INSERT OR IGNORE INTO mt_strategy_risk_map 
            (risk_code, risk_name, category, current_level, trigger_threshold, mitigation_strategy, owner_center)
            VALUES (?,?,?,?,?,?,?)""",
            (code, name, cat, level, threshold, mit, owner))
        if cur.rowcount > 0:
            stats['risks'] += 1
    
    return stats


def scan_guardian_violations(conn) -> list:
    """守卫对 violation → 即时战略研究"""
    try:
        violations = conn.execute("""
            SELECT rule_id, rule_name, severity, table_name, sql_preview, created_at
            FROM mt_guardian_violation 
            WHERE block_status='BLOCKED'
            ORDER BY id DESC LIMIT 10
        """).fetchall()
        
        researches = []
        for v in violations:
            rid, rname, sev, tbl, sql, created = v
            research_id = f"STRAT_{rid}_{int(time.time())}"
            
            cur = conn.execute("""INSERT OR IGNORE INTO mt_strategy_research 
                (research_id, title, category, severity, root_causes, mitigations, risk_level, flow_id)
                VALUES (?,?,?,?,?,?,?,?)""",
                (research_id,
                 f"[即时研究] {rname} — {tbl or '_DB_'}",
                 'GUARDIAN_REACTION', sev,
                 json.dumps([f"守卫对拦截: {rid}", f"SQL: {sql[:100]}"], ensure_ascii=False),
                 json.dumps([f"已自动拦截", f"通知 {tbl or '_DB_'} 中心检查"], ensure_ascii=False),
                 sev, FLOW_ID))
            
            if cur.rowcount > 0:
                researches.append(research_id)
        
        return researches
    except Exception as e:
        _log(f"⚠️ violation 研究失败: {e}")
        return []


def update_risk_map(conn) -> dict:
    """风险地图实时更新"""
    stats = {'updated': 0, 'escalated': 0}
    
    # 检查守卫对状态
    try:
        broken = conn.execute(
            "SELECT COUNT(*) c FROM mt_guardian_pair WHERE status!='ACTIVE'"
        ).fetchone()['c']
        if broken > 0:
            conn.execute("UPDATE mt_strategy_risk_map SET current_level='HIGH', status='ESCALATED', updated_at=datetime('now','localtime') WHERE risk_code='RSK_GUARDIAN_DOWN'")
            stats['escalated'] += 1
    except Exception:
        pass
    
    # 检查备份
    try:
        last = conn.execute(
            "SELECT created_at FROM mt_backup_log WHERE action='backup' AND ok=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not last:
            conn.execute("UPDATE mt_strategy_risk_map SET current_level='CRITICAL', status='ESCALATED' WHERE risk_code='RSK_BACKUP_GAP'")
            stats['escalated'] += 1
    except Exception:
        pass
    
    conn.commit()
    stats['updated'] = conn.execute("SELECT COUNT(*) c FROM mt_strategy_risk_map").fetchone()['c']
    return stats


def run_once() -> dict:
    conn = _db()
    init_stats = init(conn)
    guardian_researches = scan_guardian_violations(conn)
    risk_stats = update_risk_map(conn)
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'init': init_stats,
        'guardian_researches': len(guardian_researches),
        'risk_map': risk_stats,
    }
    _log(f"本轮: 战略报告 {init_stats['researches']}, 风险项 {risk_stats['updated']}")
    return report


def run_loop():
    _log(f"战略中心 loop 启动 (interval={INTERVAL}s)")
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
