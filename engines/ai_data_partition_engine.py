#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据中心 5 大数据库分区 + AI 建制引擎 (flow_data_partition_20261026)
====================================================================

5 大数据库分区 (单 app.db 内逻辑分域, 禁止删库删表, 增量迁移):
  ┌─────────────────────────────────────────────────────────────┐
  │ ① 档案馆 Archive          — 不可变历史快照 + 归档 + 审计    │
  │ ② 核心数据库 Core         — 系统核心表 (daemon/guardian/三委) │
  │ ③ 用户数据库 User         — AI 员工 + 权限 + 会话            │
  │ ④ 系统参数数据库 Param    — 基础参数 + 配置 (mt_param_*)     │
  │ ⑤ 用户高定数据库 Pref     — 用户自定义/偏好/扩展字段         │
  └─────────────────────────────────────────────────────────────┘

AI 建制:
  每个数据库分区 → 指定责任 AI + 能力矩阵 + 健康度评分
  → 守卫对联动: DROP 核心表 → BLOCKED + 档案馆自动归档

幂等原则: 所有 DDL 用 CREATE TABLE IF NOT EXISTS, 可重复执行

用法:
  python3 ai_data_partition_engine.py init   # 注册分区 + 建表 + AI建制
  python3 ai_data_partition_engine.py map    # 打印分区映射
  python3 ai_data_partition_engine.py health # 健康度巡检
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_data_partition_20261026"

# ═══════════════════════════════════════════════════════════
# 5 大数据库分区定义
# ═══════════════════════════════════════════════════════════
PARTITIONS = [
    {
        'code': 'ARCHIVE', 'name': '档案馆',
        'desc': '不可变历史快照 + 归档 + 审计 + 备份快照',
        'priority': 'P0_CRITICAL',
        'immutable': True,
        'tables': [
            'mt_archive_snapshot', 'mt_archive_retention',
            'mt_backup_log', 'mt_backup_chain',
            'mt_lab_audit_log', 'mt_gatekeeper_violation',
            'mt_sa_veto_log', 'mt_guardian_violation',
            'mt_iron_rule_violations', 'mt_rule_changelog',
            'mt_daemon_history', 'mt_health_history',
        ],
        'responsibilities': ['历史快照归档', '不可变审计记录', '备份快照留存', '数据安全最后防线'],
        'ai_owners': [
            {'employee_code': 'ARCH_KEEPER_01', 'name': '档案馆·司库AI', 'capabilities': ['归档', '快照', '审计', '备份']},
        ],
        'guardian_rule': 'DROP mt_archive_* / mt_backup_* → GDL-001 BLOCKED (绝对不可删)',
    },
    {
        'code': 'CORE', 'name': '核心数据库',
        'desc': '系统核心表, 守卫对重点防护, DROP 零容忍',
        'priority': 'P0_CRITICAL',
        'immutable': True,
        'tables': [
            'mt_daemon_registry', 'mt_guardian_pair',
            'mt_committee_proposals', 'mt_committee_bills', 'mt_committee_articles',
            'mt_sa_veto_log',
        ],
        'responsibilities': ['daemon注册', '守卫对配置', '立法提案法案'],
        'ai_owners': [
            {'employee_code': 'CORE_GUARD_01', 'name': '核心库·守关AI', 'capabilities': ['完整性', '权限', 'schema-guard']},
        ],
        'guardian_rule': 'DROP mt_daemon_registry/mt_guardian_pair → GDL-001 BLOCKED + SA告警',
    },
    {
        'code': 'USER', 'name': '用户数据库',
        'desc': 'AI 员工体系 + 权限 + 角色 + 证书',
        'priority': 'P0_CRITICAL',
        'immutable': False,
        'tables': [
            'ai_employees',
            'mt_hr_center_registry', 'mt_hr_training_log', 'mt_hr_certification',
            'mt_center_ai_binding',
            'mt_hall_vote',
            'mt_edu_incident_case', 'mt_edu_learning_log', 'mt_edu_dispatch_plan',
        ],
        'responsibilities': ['AI员工注册/权限/角色', '培训证书', '中心绑定'],
        'ai_owners': [
            {'employee_code': 'USER_GUARD_01', 'name': '用户库·司库AI', 'capabilities': ['员工管理', '角色权限', '证书监管']},
        ],
        'guardian_rule': 'DROP ai_employees → GDL-001 BLOCKED + 脑库告警',
    },
    {
        'code': 'PARAM', 'name': '系统基本参数数据库',
        'desc': '系统级参数 + 配置 + 版本 + 规则元数据',
        'priority': 'P1_HIGH',
        'immutable': False,
        'tables': [
            'mt_rule_changelog', 'mt_rule_violation_alert', 'mt_rule_integrity_scan',
            'mt_version_registry',
            'mt_system_param',
            'mt_sa_veto_log',
        ],
        'responsibilities': ['规则元数据', '版本管理', '系统参数'],
        'ai_owners': [
            {'employee_code': 'PARAM_KEEPER_01', 'name': '参数库·司库AI', 'capabilities': ['规则一致性', '版本追踪']},
        ],
        'guardian_rule': 'DROP mt_rule_changelog → GDL-001 BLOCKED',
    },
    {
        'code': 'PREF', 'name': '用户高定数据库',
        'desc': '用户自定义字段 + 偏好设置 + 扩展配置',
        'priority': 'P2_MEDIUM',
        'immutable': False,
        'tables': [
            'mt_user_custom_field', 'mt_user_preference',
            'mt_user_extension_schema',
            'mt_wecom_config',
        ],
        'responsibilities': ['用户高定扩展', '偏好设置', '第三方配置'],
        'ai_owners': [
            {'employee_code': 'PREF_MANAGER_01', 'name': '高定库·司库AI', 'capabilities': ['schema扩展', '偏好管理']},
        ],
        'guardian_rule': '允许 DROP (用户自定义表, 可重建)',
    },
]


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [DATA-PART] {msg}", flush=True)


def _ensure_tables(conn):
    """增量迁移: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN 幂等"""
    
    def _ensure_col(tbl: str, col: str, col_def: str):
        """确保某列存在 (表已存在时 ALTER ADD COLUMN)"""
        existing = conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()
        if not any(c[1] == col for c in existing):
            conn.execute(f"ALTER TABLE [{tbl}] ADD COLUMN {col} {col_def}")
    
    # 1. 分区注册表
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_db_partition_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partition_code TEXT UNIQUE NOT NULL,
        partition_name TEXT,
        description TEXT,
        priority TEXT,
        immutable INTEGER DEFAULT 0,
        tables_count INTEGER DEFAULT 0,
        ai_owners TEXT,
        responsibilities TEXT,
        guardian_rule TEXT,
        health_score REAL DEFAULT 100,
        last_audit TEXT,
        flow_id TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 2. 表 → 分区 映射
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_table_partition_map (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT UNIQUE NOT NULL,
        partition_code TEXT NOT NULL,
        table_size_bytes INTEGER DEFAULT 0,
        row_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 3. 档案馆快照
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_archive_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_code TEXT UNIQUE,
        snapshot_type TEXT,
        source_table TEXT,
        trigger_event TEXT,
        snapshot_content TEXT,
        integrity_hash TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 4. AI 建制能力矩阵 (注意: AI employee_code 是 UNIQUE NOT NULL)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_ai_governance_matrix (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ai_employee_code TEXT UNIQUE NOT NULL,
        employee_name TEXT,
        partition_code TEXT NOT NULL,
        role TEXT,
        responsibilities TEXT,
        capabilities TEXT,
        authority_level TEXT,
        health_score REAL DEFAULT 100,
        performance_metrics TEXT,
        cert_level TEXT,
        onboarded_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    _ensure_col('mt_ai_governance_matrix', 'updated_at', "TEXT DEFAULT (datetime('now','localtime'))")
    _ensure_col('mt_ai_governance_matrix', 'cert_level', "TEXT DEFAULT 'L1'")
    _ensure_col('mt_ai_governance_matrix', 'authority_level', "TEXT DEFAULT 'L2'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agm_code ON mt_ai_governance_matrix(ai_employee_code)")
    
    # 5. 用户自定义字段
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_user_custom_field (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        field_code TEXT UNIQUE,
        field_name TEXT,
        field_type TEXT,
        partition_code TEXT,
        target_table TEXT,
        description TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 6. 系统参数
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_system_param (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        param_code TEXT UNIQUE,
        param_name TEXT,
        param_value TEXT,
        param_type TEXT,
        param_category TEXT,
        scope TEXT DEFAULT 'GLOBAL',
        description TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    _ensure_col('mt_system_param', 'updated_at', "TEXT DEFAULT (datetime('now','localtime'))")
    
    # 7. 守卫对核心表保护
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_core_table_protection (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT UNIQUE,
        partition_code TEXT,
        protection_level TEXT,
        auto_archive_on_drop INTEGER DEFAULT 1,
        registered_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    conn.commit()


def init_partitions(conn) -> dict:
    """注册 5 大分区 + 建表 + 映射现有表"""
    _ensure_tables(conn)
    stats = {'partitions': 0, 'tables_mapped': 0, 'ai_governance': 0}
    
    # 注册分区
    for p in PARTITIONS:
        cur = conn.execute("""INSERT OR REPLACE INTO mt_db_partition_registry 
            (partition_code, partition_name, description, priority, immutable, tables_count,
             ai_owners, responsibilities, guardian_rule, flow_id, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))""",
            (p['code'], p['name'], p['desc'], p['priority'], 
             1 if p['immutable'] else 0, len(p['tables']),
             json.dumps(p['ai_owners'], ensure_ascii=False),
             json.dumps(p['responsibilities'], ensure_ascii=False),
             p['guardian_rule'], FLOW_ID))
        stats['partitions'] += 1
    
    # 表 → 分区 映射 + 核心表保护
    for p in PARTITIONS:
        for tbl in p['tables']:
            # 幂等映射
            cur = conn.execute("""INSERT OR IGNORE INTO mt_table_partition_map 
                (table_name, partition_code, row_count, table_size_bytes)
                VALUES (?,?,0,0)""",
                (tbl, p['code']))
            if cur.rowcount > 0:
                stats['tables_mapped'] += 1
            
            # 核心表保护 (P0 分区表 → ABSOLUTE 级保护)
            protection_level = 'ABSOLUTE' if p['priority'] == 'P0_CRITICAL' else 'STRONG'
            try:
                conn.execute("""INSERT OR IGNORE INTO mt_core_table_protection 
                    (table_name, partition_code, protection_level, auto_archive_on_drop)
                    VALUES (?,?,?, 1)""",
                    (tbl, p['code'], protection_level))
            except Exception:
                pass
    
    # AI 建制能力矩阵
    for p in PARTITIONS:
        for owner in p['ai_owners']:
            capabilities_json = json.dumps([f"PARTITION_{p['code']}", f"TABLE_GUARD", 
                                           f"RESP_{'_'.join(p['responsibilities'][:2])}"], ensure_ascii=False)
            cur = conn.execute("""INSERT OR REPLACE INTO mt_ai_governance_matrix 
                (ai_employee_code, employee_name, partition_code, role,
                 responsibilities, capabilities, authority_level, cert_level, updated_at)
                VALUES (?,?,?,?,?,?,?,?, datetime('now','localtime'))""",
                (owner['employee_code'], owner['name'], p['code'], 'KEEPER',
                 json.dumps(p['responsibilities'], ensure_ascii=False),
                 capabilities_json,
                 'L3', 'L2'))
            stats['ai_governance'] += 1
    
    # 系统参数初始化 (PARAM 分区)
    default_params = [
        ('DB_PARTITION_VERSION', '分区版本号', 'flow_data_partition_20261026', 'STRING', 'DB'),
        ('AI_GOVERNANCE_ENABLED', 'AI 建制启用', '1', 'BOOL', 'SYSTEM'),
        ('GUARDIAN_PAIR_ACTIVE', '守卫对启用', '1', 'BOOL', 'SECURITY'),
        ('ARCHIVE_AUTO_SNAPSHOT', '档案馆自动快照', '1', 'BOOL', 'DB'),
        ('VETO_CASCADE', 'SA 否决级联', '1', 'BOOL', 'SECURITY'),
        ('DATA_ZERO_TOKEN', '零token推理强制', '1', 'BOOL', 'AI'),
    ]
    for code, name, val, ptype, cat in default_params:
        conn.execute("""INSERT OR REPLACE INTO mt_system_param 
            (param_code, param_name, param_value, param_type, param_category)
            VALUES (?,?,?,?,?)""",
            (code, name, val, ptype, cat))
    
    conn.commit()
    return stats


def health_scan(conn) -> dict:
    """5 大分区健康度巡检"""
    report = {'partitions': {}}
    
    for p in PARTITIONS:
        try:
            # 表存在性检查
            existing = []
            missing = []
            for tbl in p['tables']:
                r = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
                (existing if r else missing).append(tbl)
            
            # 行数统计
            total_rows = 0
            for tbl in existing:
                try:
                    total_rows += conn.execute(f"SELECT COUNT(*) c FROM [{tbl}]").fetchone()[0]
                except Exception:
                    pass
            
            health = 100 - len(missing) * 20  # 每缺一张表 -20
            
            report['partitions'][p['code']] = {
                'name': p['name'],
                'existing_tables': len(existing),
                'missing_tables': missing,
                'total_rows': total_rows,
                'health_score': health,
                'status': 'HEALTHY' if health >= 80 else ('DEGRADED' if health >= 40 else 'CRITICAL'),
            }
            
            # 更新注册表
            conn.execute("""UPDATE mt_db_partition_registry SET 
                tables_count=?, health_score=?, last_audit=datetime('now','localtime')
                WHERE partition_code=?""",
                (len(existing), health, p['code']))
        except Exception as e:
            report['partitions'][p['code']] = {'status': 'ERROR', 'error': str(e)[:100]}
    
    conn.commit()
    return report


def print_map(conn):
    """打印分区映射"""
    print(f"\n{'='*70}")
    print(f"📊 MTSCOS AI 5 大数据库分区映射")
    print(f"{'='*70}")
    
    for p in PARTITIONS:
        mark = '🔒' if p['immutable'] else '🔓'
        print(f"\n{mark} {p['priority']} | {p['code']} {p['name']}")
        print(f"   {p['desc']}")
        print(f"   责任 AI: {', '.join(o['name'] for o in p['ai_owners'])}")
        print(f"   表清单 ({len(p['tables'])} 张):")
        
        # 检查哪些表实际存在
        for tbl in p['tables']:
            r = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
            exists = '✅' if r else '❌ 未创建'
            print(f"     {exists} {tbl}")
    
    print(f"\n{'='*70}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'map', 'health'])
    args = parser.parse_args()
    
    conn = _db()
    
    if args.command == 'init':
        stats = init_partitions(conn)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        # 顺便跑一次健康度
        health = health_scan(conn)
        print("\n健康度:", json.dumps({k: {'health_score': v.get('health_score'), 'status': v.get('status')} 
                                    for k, v in health.get('partitions', {}).items()}, indent=2))
    elif args.command == 'map':
        print_map(conn)
    elif args.command == 'health':
        health = health_scan(conn)
        print(json.dumps(health, ensure_ascii=False, indent=2))
    
    conn.close()


if __name__ == '__main__':
    main()
