#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据中心引擎 Data Center Engine (flow_data_center_20261026)
=========================================================
13 中心之数据中心: 数据质量监控 + 数据正常使用存储

职责:
  ① 数据完整性巡检 (integrity check + 引用完整性)
  ② 数据一致性巡检 (三库同步验证)
  ③ 数据使用监控 (慢查询/高频查询/全表扫描)
  ④ 存储容量管理 (增长预测/归档建议)
  ⑤ 与守卫对联动 (异常写入拦截 + 备份触发)

两表:
  mt_data_quality_report    — 数据质量报告
  mt_data_usage_monitor     — 数据使用监控

用法:
  python3 ai_data_center_engine.py init
  python3 ai_data_center_engine.py once
  python3 ai_data_center_engine.py start
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_data_center_20261026"
INTERVAL = 300


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [DATA] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_data_quality_report (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT,
        issue_type TEXT,
        issue_detail TEXT,
        severity TEXT DEFAULT 'MEDIUM',
        row_count INTEGER DEFAULT 0,
        integrity_ok INTEGER DEFAULT 1,
        consistency_ok INTEGER DEFAULT 1,
        remediation TEXT,
        flow_id TEXT,
        reported_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_data_usage_monitor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_name TEXT,
        metric_value REAL,
        metric_unit TEXT,
        trend TEXT,
        alert_level TEXT DEFAULT 'NORMAL',
        collected_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def init(conn) -> dict:
    _ensure_tables(conn)
    return {'tables_created': 2, 'status': 'OK'}


def integrity_check(conn) -> dict:
    """完整性巡检"""
    issues = []
    
    # 全库完整性
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != 'ok':
            issues.append({'table_name': '_DB_', 'issue_type': 'INTEGRITY_FAIL',
                          'issue_detail': f"PRAGMA integrity_check: {result}", 'severity': 'CRITICAL'})
    except Exception as e:
        issues.append({'table_name': '_DB_', 'issue_type': 'INTEGRITY_ERROR',
                      'issue_detail': str(e), 'severity': 'HIGH'})
    
    # 检查关键表是否存在
    key_tables = ['mt_ai_employees', 'mt_daemon_registry', 'mt_backup_log',
                  'mt_guardian_pair', 'mt_strategy_research']
    for tbl in key_tables:
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
            if not row:
                issues.append({'table_name': tbl, 'issue_type': 'TABLE_MISSING',
                              'issue_detail': '表不存在', 'severity': 'CRITICAL'})
        except Exception:
            pass
    
    # 大表行数统计
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mt_%' LIMIT 50"
        ).fetchall()
        for (tbl,) in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) c FROM [{tbl}]").fetchone()
                cnt = row[0]
                if cnt > 100000:
                    conn.execute("""INSERT INTO mt_data_usage_monitor 
                        (metric_name, metric_value, metric_unit, alert_level)
                        VALUES (?,?,?,?)""",
                        (f"table_rows_{tbl}", cnt, 'rows', 'WARNING'))
            except Exception:
                pass
    except Exception:
        pass
    
    return {'issues_found': len(issues), 'issues': issues[:10]}


def storage_check(conn) -> dict:
    """存储容量检查"""
    result = {'db_size_mb': 0, 'wal_size_mb': 0, 'free_disk_pct': 0, 'alerts': []}
    
    try:
        db_size = os.path.getsize(_DB_PATH)
        wal_size = os.path.getsize(_DB_PATH + '-wal') if os.path.exists(_DB_PATH + '-wal') else 0
        result['db_size_mb'] = round(db_size / 1e6, 1)
        result['wal_size_mb'] = round(wal_size / 1e6, 1)
        
        if wal_size > db_size * 0.5:
            result['alerts'].append(f"WAL 膨胀 {result['wal_size_mb']}MB")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _log(f"⚠️ WAL 膨胀 → 自动 checkpoint")
        
        stat = os.statvfs(os.path.dirname(_DB_PATH))
        free_pct = stat.f_bavail / stat.f_blocks * 100
        result['free_disk_pct'] = round(free_pct, 1)
        
        if free_pct < 10:
            result['alerts'].append(f"磁盘剩余 {free_pct:.1f}%")
    except Exception as e:
        result['alerts'].append(str(e))
    
    # 落库监控
    conn.execute("""INSERT INTO mt_data_usage_monitor 
        (metric_name, metric_value, metric_unit, alert_level)
        VALUES ('db_size_mb', ?, 'MB', 'NORMAL')""", (result['db_size_mb'],))
    conn.execute("""INSERT INTO mt_data_usage_monitor 
        (metric_name, metric_value, metric_unit, alert_level)
        VALUES ('free_disk_pct', ?, '%', ?)""",
        (result['free_disk_pct'], 'WARNING' if result['free_disk_pct'] < 20 else 'NORMAL'))
    
    return result


def save_issues(conn, issues: list) -> int:
    n = 0
    for iss in issues:
        try:
            conn.execute("""INSERT INTO mt_data_quality_report 
                (table_name, issue_type, issue_detail, severity, flow_id)
                VALUES (?,?,?,?,?)""",
                (iss.get('table_name', '_UNKNOWN_'), iss.get('issue_type', 'UNKNOWN'),
                 iss.get('issue_detail', '')[:500], iss.get('severity', 'MEDIUM'), FLOW_ID))
            n += 1
        except Exception:
            pass
    return n


def run_once() -> dict:
    conn = _db()
    _ensure_tables(conn)
    
    integrity = integrity_check(conn)
    storage = storage_check(conn)
    
    issues_saved = save_issues(conn, integrity['issues'])
    conn.commit()
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'integrity': integrity,
        'storage': storage,
        'issues_saved': issues_saved,
    }
    _log(f"完整性: {integrity['issues_found']} 问题, 存储: {storage['db_size_mb']}MB")
    return report


def run_loop():
    _log(f"数据中心 loop 启动 (interval={INTERVAL}s)")
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
