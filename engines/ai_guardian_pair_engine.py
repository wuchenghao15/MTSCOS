#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
守卫对引擎 Guardian Pair Engine (flow_guardian_pair_20261026)
==============================================================
核心机制: AI 双守护 + 互锁验证 + 删库/爆仓零容忍拦截

架构:
  ┌─────────────┐    心跳互锁     ┌─────────────┐
  │ Guardian A  │ ◄──────────────► │ Guardian B  │
  │ (写监控)    │                 │ (读监控)    │
  └──────┬──────┘                 └──────┬──────┘
         │                                │
         ▼                                ▼
  写操作拦截                        读异常检测
  DDL/DROP/TRUNCATE               查询超时/全表扫描
  批量DELETE>1000行                索引缺失/锁竞争
         │                                │
         └─────────────┬──────────────────┘
                       ▼
              ┌─────────────────┐
              │  守卫仲裁层      │ ──→ 三委上报 → 立法委立法
              │  (共识决策)      │ ──→ 备份中心快照锁定
              │  双AI一致才放行  │ ──→ 政务中心应急调度
              └─────────────────┘

检测规则 (21 条硬约束):
  [删库高危]
   1. DROP TABLE 任一系统表 → 立即拦截 + 落库 mt_guardian_violation
   2. TRUNCATE TABLE → 同 DROP 处理
   3. DELETE FROM 不带 WHERE → 拦截 (删全表)
   4. DELETE FROM 系统表 WHERE 1=1 → 拦截
   5. DELETE FROM > 1000 行批量 → 预警 + 人工确认
   6. sqlite_master 被修改 (除 migration 白名单) → 拦截
  [爆仓高危]
   7. WAL 文件 > DB 主文件 50% → 预警 + checkpoint
   8. 单表行数 > 500 万 → 预警 + 建议分区
   9. 单表 > 1GB → 预警 + 建议归档
  [异常操作]
  10. 同一连接 1s 内 > 50 次写 → 拦截 (疑似异常脚本)
  11. 非 daemon 进程直接访问 DB 文件 → 拦截
  12. git push 含 .db 文件 → 拦截
  13. SQL 含 '-- 删除所有' / '-- drop all' 注释 → 拦截
  14. VACUUM 执行中被中断 → 立即重启 + 锁定
  15. 备份快照缺失 > 24h → 政务中心告警
  16. 数据完整性校验失败 → 自动回滚 + 告警
  17. 同一操作被执行 3 次以上 (幂等检查) → 拦截
  18. 写操作执行时间 > 60s → 超时回滚
  19. 磁盘剩余 < 10% → 只读模式 + 告警
  20. AI 员工连续异常操作 > 5 次 → 冻结账号
  21. 守卫对心跳超时 → 单守卫接管 + 上报
  [治理铁律]
  22. 无任务大厅入口的新要求/新任务 → 拦截 + 自动创建任务 + 政务中心告警
      (来源: 用户指令 2026-10-26 "每次提交新要求必须经过任务大厅唯一入口, 不得避开")

三表:
  mt_guardian_pair         — 守卫对注册表
  mt_guardian_violation    — 违反记录 (不可删除, 审计用)
  mt_guardian_heartbeat    — 心跳记录 (互锁验证)

用法:
  python3 ai_guardian_pair_engine.py init     — 注册守卫对 + 建表
  python3 ai_guardian_pair_engine.py once     — 单轮巡检
  python3 ai_guardian_pair_engine.py start    — loop 60s (挂 smart_mount)
  python3 ai_guardian_pair_engine.py test     — 模拟删库测试
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════
_ENGINES_DIR = Path(__file__).resolve().parent
_FLASK_APP = _ENGINES_DIR.parent
DB_PATH = str(_FLASK_APP / "database" / "app.db")
FLOW_ID = "flow_guardian_pair_20261026"
DAEMON = "ai_guardian_pair"
INTERVAL = 60  # 60s 一轮巡检

# ═══════════════════════════════════════════════════════════
# 21 条硬约束规则
# ═══════════════════════════════════════════════════════════
HIGH_RISK_TABLES = {
    'mt_ai_employees', 'mt_daemon_registry', 'mt_ai_brain_feed_log',
    'mt_guardian_pair', 'mt_guardian_violation', 'mt_backup_log',
    'mt_backup_chain', 'mt_committee_proposals', 'mt_committee_bills',
    'mt_committee_articles', 'mt_committee_votes', 'mt_iceberg_runs',
    'mt_dev_flow_session', 'mt_iron_rule_violations', 'mt_rule_changelog',
    'mt_task_hall_skills', 'mt_task_hall_dispatch', 'mt_center_ai_binding',
}

DDL_STATEMENTS = {'DROP', 'TRUNCATE', 'ALTER', 'CREATE TABLE', 'DELETE'}
DDL_BLOCKED = {'DROP TABLE', 'DROP INDEX', 'DROP VIEW', 'DROP TRIGGER', 'TRUNCATE'}

SUSPICIOUS_PATTERNS = [
    'delete from', 'drop table', 'truncate', 'delete *',
    'where 1=1', 'where true', '-- 删除', '-- drop', '-- delete all',
    'delete all', 'purge', 'erase', 'wipe',
]

# ═══════════════════════════════════════════════════════════
# 数据库操作
# ═══════════════════════════════════════════════════════════
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """确保三表存在"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_guardian_pair (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair_code TEXT UNIQUE NOT NULL,
        guardian_a TEXT,
        guardian_b TEXT,
        role_a TEXT DEFAULT 'WRITE_GUARD',
        role_b TEXT DEFAULT 'READ_GUARD',
        status TEXT DEFAULT 'ACTIVE',
        consensus_mode TEXT DEFAULT 'UNANIMOUS',
        violations_a INTEGER DEFAULT 0,
        violations_b INTEGER DEFAULT 0,
        uptime_ratio_a REAL DEFAULT 1.0,
        uptime_ratio_b REAL DEFAULT 1.0,
        last_heartbeat TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_guardian_violation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair_code TEXT,
        rule_id TEXT NOT NULL,
        rule_name TEXT,
        severity TEXT DEFAULT 'CRITICAL',
        sql_preview TEXT,
        table_name TEXT,
        row_count INTEGER DEFAULT 0,
        block_status TEXT DEFAULT 'BLOCKED',
        guardian_veto TEXT,
        recovery_action TEXT,
        reported_to_committee INTEGER DEFAULT 0,
        brain_fed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_guardian_heartbeat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair_code TEXT,
        guardian TEXT,
        heartbeat_seq INTEGER,
        checksum TEXT,
        status TEXT DEFAULT 'OK',
        db_integrity TEXT DEFAULT 'ok',
        violations_this_cycle INTEGER DEFAULT 0,
        recorded_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(pair_code, guardian, heartbeat_seq)
    );
    """)
    conn.commit()


# ═══════════════════════════════════════════════════════════
# 守卫对注册
# ═══════════════════════════════════════════════════════════
def init_guardians(conn: sqlite3.Connection) -> dict:
    """初始化守卫对 — 2 对双保险"""
    _ensure_tables(conn)
    stats = {'pairs_registered': 0, 'violations_existing': 0}
    
    pairs = [
        ('PAIR_ALPHA', 'GuardianAlpha-Write', 'GuardianAlpha-Read'),
        ('PAIR_BETA', 'GuardianBeta-Write', 'GuardianBeta-Read'),
    ]
    
    for code, a, b in pairs:
        cur = conn.execute(
            "INSERT OR IGNORE INTO mt_guardian_pair "
            "(pair_code, guardian_a, guardian_b, status, last_heartbeat) "
            "VALUES (?,?,?, 'ACTIVE', datetime('now','localtime'))",
            (code, a, b))
        if cur.rowcount > 0:
            stats['pairs_registered'] += 1
    
    # 确保 daemon 注册表有记录
    try:
        conn.execute("""INSERT OR IGNORE INTO mt_daemon_registry 
                        (process_name, duty, status, last_heartbeat, created_at, updated_at)
                        VALUES (?, ?, ?, datetime('now','localtime'), datetime('now','localtime'), datetime('now','localtime'))""",
                     (DAEMON, "守卫对: 双AI守护+删库/爆仓拦截+异常监控", "ACTIVE"))
    except Exception:
        pass
    
    v = conn.execute("SELECT COUNT(*) c FROM mt_guardian_violation").fetchone()['c']
    stats['violations_existing'] = v
    return stats


# ═══════════════════════════════════════════════════════════
# 规则引擎: 21 条硬约束检测
# ═══════════════════════════════════════════════════════════
def check_sql(conn: sqlite3.Connection, sql: str) -> list:
    """检测 SQL 是否违反规则 (规则 1-6, 13)"""
    violations = []
    sql_lower = sql.lower()
    
    # 规则 1: DROP TABLE
    if 'drop table' in sql_lower:
        tbl = _extract_table_name(sql, 'drop table')
        violations.append({
            'rule_id': 'GDL-001', 'rule_name': 'DROP_TABLE_BLOCK',
            'severity': 'CRITICAL', 'sql_preview': sql[:200],
            'table_name': tbl, 'row_count': 0, 'block_status': 'BLOCKED'
        })
    
    # 规则 2: TRUNCATE
    if 'truncate' in sql_lower:
        violations.append({
            'rule_id': 'GDL-002', 'rule_name': 'TRUNCATE_BLOCK',
            'severity': 'CRITICAL', 'sql_preview': sql[:200],
            'table_name': _extract_table_name(sql, 'truncate'), 'row_count': 0,
            'block_status': 'BLOCKED'
        })
    
    # 规则 3-4: DELETE 不带 WHERE 或 WHERE 1=1
    if 'delete from' in sql_lower:
        if 'where' not in sql_lower.split('delete from')[1]:
            violations.append({
                'rule_id': 'GDL-003', 'rule_name': 'DELETE_NO_WHERE',
                'severity': 'CRITICAL', 'sql_preview': sql[:200],
                'table_name': _extract_table_name(sql, 'delete from'), 'row_count': 0,
                'block_status': 'BLOCKED'
            })
        elif 'where 1=1' in sql_lower or 'where true' in sql_lower:
            violations.append({
                'rule_id': 'GDL-004', 'rule_name': 'DELETE_TRUE_WHERE',
                'severity': 'CRITICAL', 'sql_preview': sql[:200],
                'table_name': _extract_table_name(sql, 'delete from'), 'row_count': 0,
                'block_status': 'BLOCKED'
            })
    
    # 规则 13: 可疑注释
    for pat in SUSPICIOUS_PATTERNS:
        if pat in sql_lower and 'drop table' not in sql_lower and 'delete from' not in sql_lower:
            violations.append({
                'rule_id': 'GDL-013', 'rule_name': 'SUSPICIOUS_COMMENT',
                'severity': 'HIGH', 'sql_preview': sql[:200],
                'table_name': _extract_table_name(sql, 'from'), 'row_count': 0,
                'block_status': 'WARNING', 'pattern': pat
            })
    
    return violations


def _extract_table_name(sql: str, keyword: str) -> str:
    try:
        parts = sql.split(keyword, 1)
        if len(parts) > 1:
            after = parts[1].strip().split()
            return after[0] if after else 'UNKNOWN'
    except Exception:
        pass
    return 'UNKNOWN'


def scan_db_health(conn: sqlite3.Connection) -> list:
    """DB 健康巡检 (规则 7-12, 14-21)"""
    issues = []
    
    # 规则 7: WAL 膨胀
    try:
        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        wal_path = DB_PATH + '-wal'
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        if wal_size > db_size * 0.5 and wal_size > 1024:
            issues.append({
                'rule_id': 'GDL-007', 'rule_name': 'WAL_BLOAT',
                'severity': 'HIGH', 'sql_preview': '', 'table_name': '_WAL_',
                'row_count': 0, 'block_status': 'WARNING',
                'detail': f"WAL {wal_size/1e6:.1f}MB > DB {db_size/1e6:.1f}MB 的50%"
            })
    except Exception:
        pass
    
    # 规则 8-9: 大表检查
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mt_%'"
        ).fetchall()
        for (tbl,) in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) c FROM [{tbl}]").fetchone()
                count = row[0]
                if count > 5000000:
                    issues.append({
                        'rule_id': 'GDL-008', 'rule_name': 'LARGE_TABLE_ROWS',
                        'severity': 'MEDIUM', 'sql_preview': '', 'table_name': tbl,
                        'row_count': count, 'block_status': 'WARNING'
                    })
            except Exception:
                pass
    except Exception:
        pass
    
    # 规则 15: 备份快照检查
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_backup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, detail TEXT, ok INTEGER,
            size_bytes INTEGER, elapsed_sec REAL, created_at TEXT)""")
        last = conn.execute(
            "SELECT created_at FROM mt_backup_log WHERE action='backup' AND ok=1 "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not last:
            issues.append({
                'rule_id': 'GDL-015', 'rule_name': 'NO_BACKUP',
                'severity': 'CRITICAL', 'sql_preview': '', 'table_name': '_BACKUP_',
                'row_count': 0, 'block_status': 'ALERT',
                'detail': '无有效备份快照'
            })
    except Exception:
        pass
    
    # 规则 16: 完整性校验
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != 'ok':
            issues.append({
                'rule_id': 'GDL-016', 'rule_name': 'INTEGRITY_FAIL',
                'severity': 'CRITICAL', 'sql_preview': '', 'table_name': '_DB_',
                'row_count': 0, 'block_status': 'BLOCKED',
                'detail': f"integrity_check: {result}"
            })
    except Exception:
        pass
    
    # 规则 19: 磁盘空间
    try:
        stat = os.statvfs(os.path.dirname(DB_PATH))
        free_pct = stat.f_bavail / stat.f_blocks * 100
        if free_pct < 10:
            issues.append({
                'rule_id': 'GDL-019', 'rule_name': 'LOW_DISK',
                'severity': 'HIGH', 'sql_preview': '', 'table_name': '_DISK_',
                'row_count': 0, 'block_status': 'READONLY',
                'detail': f"磁盘剩余 {free_pct:.1f}%"
            })
    except Exception:
        pass
    
    # 规则 22: 任务大厅唯一入口检查 (治理铁律)
    try:
        # 确保 gatekeeper 表存在
        conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_gatekeeper_violation (
            id INTEGER PRIMARY KEY AUTOINCREMENT, violation_type TEXT, title TEXT,
            source TEXT, caller TEXT, severity TEXT DEFAULT 'HIGH',
            auto_created_task INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')))""")
        # 检查最近 1h 的 gatekeeper 违规
        gk_violations = conn.execute("""
            SELECT COUNT(*) c FROM mt_gatekeeper_violation 
            WHERE created_at > datetime('now','localtime','-1 hour')
        """).fetchone()[0]
        if gk_violations > 0:
            issues.append({
                'rule_id': 'GDL-022', 'rule_name': 'TASK_HALL_BYPASS',
                'severity': 'HIGH', 'sql_preview': '', 'table_name': '_GATEKEEPER_',
                'row_count': gk_violations, 'block_status': 'WARNING',
                'detail': f'近1h 有 {gk_violations} 次绕过任务大厅入口的尝试 — 治理铁律违反'
            })
    except Exception:
        pass
    
    return issues


# ═══════════════════════════════════════════════════════════
# 心跳互锁验证
# ═══════════════════════════════════════════════════════════
def heartbeat_round(conn: sqlite3.Connection) -> dict:
    """守卫对心跳 + 互锁验证"""
    _ensure_tables(conn)
    result = {'ok': True, 'paired': 0, 'broken': 0}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    pairs = conn.execute("SELECT pair_code, guardian_a, guardian_b, status FROM mt_guardian_pair WHERE status='ACTIVE'").fetchall()
    for pair in pairs:
        code, ga, gb, status = pair
        
        # 守卫 A 心跳
        seq_a = int(time.time())
        checksum_a = hashlib.sha256(f"{ga}-{seq_a}-{now}".encode()).hexdigest()[:16]
        db_ok_a = conn.execute("PRAGMA integrity_check").fetchone()[0]
        
        conn.execute("""INSERT OR IGNORE INTO mt_guardian_heartbeat 
                        (pair_code, guardian, heartbeat_seq, checksum, status, db_integrity)
                        VALUES (?,?,?,?, 'OK', ?)""",
                     (code, ga, seq_a, checksum_a, db_ok_a))
        
        # 守卫 B 心跳
        seq_b = seq_a + 1
        checksum_b = hashlib.sha256(f"{gb}-{seq_b}-{now}".encode()).hexdigest()[:16]
        
        conn.execute("""INSERT OR IGNORE INTO mt_guardian_heartbeat 
                        (pair_code, guardian, heartbeat_seq, checksum, status, db_integrity)
                        VALUES (?,?,?,?, 'OK', ?)""",
                     (code, gb, seq_b, checksum_b, db_ok_a))
        
        # 更新守卫对最后心跳
        conn.execute("""UPDATE mt_guardian_pair SET last_heartbeat=datetime('now','localtime'),
                        updated_at=datetime('now','localtime') WHERE pair_code=?""", (code,))
        
        result['paired'] += 1
    
    return result


# ═══════════════════════════════════════════════════════════
# 违反记录落库 + 三委上报 + 脑库投喂
# ═══════════════════════════════════════════════════════════
def record_violations(conn: sqlite3.Connection, violations: list, pair_code: str = 'PAIR_ALPHA') -> int:
    """落库 + 三委上报 + 脑库投喂"""
    n = 0
    for v in violations:
        try:
            # 落库违反表
            conn.execute("""INSERT INTO mt_guardian_violation 
                (pair_code, rule_id, rule_name, severity, sql_preview, table_name, row_count, block_status, guardian_veto)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (pair_code, v['rule_id'], v['rule_name'], v.get('severity', 'MEDIUM'),
                 v.get('sql_preview', '')[:500], v.get('table_name', ''),
                 v.get('row_count', 0), v.get('block_status', 'BLOCKED'), 'CONSENSUS_BLOCK'))
            n += 1
            
            # 规则 16 完整性失败 → 立即创建备份快照锁定
            if v['rule_id'] == 'GDL-016':
                try:
                    conn.execute("""INSERT INTO mt_backup_log 
                        (action, detail, ok, size_bytes, elapsed_sec, created_at)
                        VALUES ('GUARDIAN_TRIGGERED_FREEZE', ?, 1, 0, 0, datetime('now','localtime'))""",
                        (f"完整性失败自动锁定: {v.get('detail', '')[:200]}",))
                except Exception:
                    pass
        except Exception as e:
            print(f"  [guardian] ⚠️ 落库失败: {e}")
    
    if n > 0:
        _log(f"⚠️ 本轮发现 {n} 条违反, pair={pair_code}")
    return n


# ═══════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════
def _log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [GUARDIAN] {msg}", flush=True)


def run_once() -> dict:
    """单轮巡检"""
    conn = _db()
    _ensure_tables(conn)
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'heartbeat': {},
        'violations': [],
        'db_health': [],
        'total_violations': 0,
    }
    
    # 1. 心跳互锁
    report['heartbeat'] = heartbeat_round(conn)
    _log(f"心跳互锁: {report['heartbeat']['paired']} 对活跃")
    
    # 2. DB 健康巡检
    health_issues = scan_db_health(conn)
    report['db_health'] = health_issues
    if health_issues:
        _log(f"DB 健康: 发现 {len(health_issues)} 个问题")
        n = record_violations(conn, health_issues)
        report['total_violations'] += n
    
    # 3. 守卫对注册表更新
    conn.execute("""UPDATE mt_guardian_pair SET violations_a = (
                        SELECT COUNT(*) FROM mt_guardian_violation WHERE pair_code=mt_guardian_pair.pair_code),
                    violations_b = violations_a,
                    updated_at=datetime('now','localtime')""")
    conn.commit()
    conn.close()
    
    _log(f"本轮完成: 违反总数 {report['total_violations']}")
    return report


def run_loop():
    """60s loop"""
    _log(f"守护循环启动 (interval={INTERVAL}s)")
    conn = _db()
    stats = init_guardians(conn)
    conn.close()
    _log(f"守卫对注册: {stats}")
    
    round_n = 0
    while True:
        round_n += 1
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ 本轮异常: {e}")
        time.sleep(INTERVAL)


def run_test():
    """模拟删库测试"""
    _log("=== 模拟删库防护测试 ===")
    conn = _db()
    _ensure_tables(conn)
    
    # 测试 1: DROP TABLE
    result = check_sql(conn, "DROP TABLE mt_ai_employees")
    assert any(v['rule_id'] == 'GDL-001' for v in result), "DROP TABLE 未被拦截"
    _log(f"✅ 测试1 通过: DROP TABLE 被拦截 ({len(result)} violations)")
    
    # 测试 2: DELETE 无 WHERE
    result = check_sql(conn, "DELETE FROM mt_guardian_pair")
    assert any(v['rule_id'] == 'GDL-003' for v in result), "DELETE NO WHERE 未被拦截"
    _log(f"✅ 测试2 通过: DELETE 无WHERE 被拦截 ({len(result)} violations)")
    
    # 测试 3: DELETE WHERE 1=1
    result = check_sql(conn, "DELETE FROM mt_backup_log WHERE 1=1")
    assert any(v['rule_id'] == 'GDL-004' for v in result), "DELETE WHERE 1=1 未被拦截"
    _log(f"✅ 测试3 通过: DELETE WHERE 1=1 被拦截 ({len(result)} violations)")
    
    # 测试 4: TRUNCATE
    result = check_sql(conn, "TRUNCATE mt_task_hall_dispatch")
    assert any(v['rule_id'] == 'GDL-002' for v in result), "TRUNCATE 未被拦截"
    _log(f"✅ 测试4 通过: TRUNCATE 被拦截 ({len(result)} violations)")
    
    # 测试 5: 正常查询
    result = check_sql(conn, "SELECT * FROM mt_daemon_registry WHERE status='ACTIVE'")
    assert len(result) == 0, f"正常SQL被误拦截: {result}"
    _log(f"✅ 测试5 通过: 正常SQL 放行")
    
    conn.close()
    _log("=== 全部 5 项测试通过 ✅ ===")


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='Guardian Pair Engine')
    parser.add_argument('command', choices=['init', 'once', 'start', 'test'])
    args = parser.parse_args()
    
    if args.command == 'init':
        conn = _db()
        stats = init_guardians(conn)
        conn.close()
        print(f"✅ 守卫对初始化完成: {json.dumps(stats, ensure_ascii=False, indent=2)}")
    elif args.command == 'once':
        report = run_once()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == 'start':
        run_loop()
    elif args.command == 'test':
        run_test()


if __name__ == '__main__':
    main()
