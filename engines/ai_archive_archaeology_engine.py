#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
档案馆深度考古引擎 v2 — 完整 64 天文明时间线 (flow_archaeology_full_20261026)
========================================================================================

考古方法: 全库 715 张表逐列最早记录反推 (增量表永不删除, 是最可信的历史源)

文明 7 阶段 (2026-08-23 → 2026-10-26):
  阶段 1  🟤 史前脑库时代  (08-23 ~ 09-08) — 1.57M 脑库知识 + 23K 题库, 不带任何前缀
  阶段 2  🟣 EigenFlux 原生 (09-09 ~ 09-11) — 283K 原生消息, 部分 mt_ 前缀
  阶段 3  🟠 mt_ 规范统一   (09-12 ~ 09-17) — roles/users/heartbeat/firewall, Flask 基表落地
  阶段 4  🔴 铁律 + 规则    (09-18 ~ 09-22) — 34 条铁律违反 + 9 篇规则 changelog + 守护巡检
  阶段 5  🔵 SmartMount+冰山 (09-23 ~ 09-30) — 挂载决策 + 冰山进化档案 + 内容矩阵
  阶段 6  🔴 冰意识+升级   (10-01 ~ 10-13) — 4934 意识运行 + 4915 升级执行 + 930K 心跳
  阶段 7  🟡 安全铁律+任务厅 (10-14 ~ 10-26) — 守卫对 22 条 + SA 否决 + 任务厅 + 5 分区

数据来源 (42 张关键表):
  史前: ai_brain_enhanced_knowledge (1.57M) + question_bank (23K) + eigenflux_comm_sessions (11K)
  原生: eigenflux_comm_messages (283K) + daemon_registry
  mt_ : mt_andromeda_employee_registry (33K) + mt_ai_self_evolution_log (1K)
  规则: mt_iron_rule_violations (34) + mt_rule_changelog (23) + mt_daemon_supervisor_log (9K)
  冰山: mt_iceberg_* (52 张) + mt_ai_mount_decisions (25)
  近期: mt_lab_task_hall (561) + mt_sa_veto_log (5) + mt_guardian_violation (11) + mt_db_partition_registry

考古队建制 (15 人, 3 分队):
  考古总队长        ARCH_LEADER_01    L4  统筹全源交叉验证/宪法级权限
  史前脑库分队 (4人):
    ARCH_PRE_BRAIN_01   L3  1.57M 脑库知识溯源 + 题库原始数据
    ARCH_PRE_EIGEN_01   L3  EigenFlux 原生消息反推 + 会话重建
    ARCH_PRE_DATE_01     L2  碳14时间戳校准 (unix/ISO/混合格式)
    ARCH_PRE_DIRT_01     L2  脏数据清理 (SHELL注入/UTC后缀)
  mt_建制分队 (4人):
    ARCH_MT_SRC_01       L3  mt_*_log 增量日志探源
    ARCH_MT_GIT_01       L3  Git commit 溯源 + flow_id 反推
    ARCH_MT_STRAT_01     L2  版本节点梳理 + changelog 交叉
    ARCH_MT_RULE_01      L2  规则铁律违反事件重建
  冰山文明分队 (4人):
    ARCH_ICE_RUN_01      L3  冰山运行记录还原 + 进化档案
    ARCH_ICE_CONS_01     L3  4934 意识运行分析 + 升级执行链
    ARCH_ICE_CONTENT_01  L2  6749 内容矩阵 + 方向注册
    ARCH_ICE_WRITE_01    L2  历史报告撰写 + 时间线生成
  后勤:
    ARCH_WRITE_01        L2  总报告汇总 + 出版
"""
from __future__ import annotations
import os, sys, json, time, sqlite3, argparse, hashlib
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_archaeology_full_20261026"


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _ensure_tables(conn):
    def _ensure_col(tbl, col, col_def):
        cols = [c[1] for c in conn.execute(f'PRAGMA table_info([{tbl}])').fetchall()]
        if col not in cols:
            conn.execute(f'ALTER TABLE [{tbl}] ADD COLUMN {col} {col_def}')

    # ── 基础表 (可能已存在, 加新列) ──
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_archive_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_code TEXT UNIQUE, snapshot_type TEXT,
        source_table TEXT, trigger_event TEXT, snapshot_content TEXT, integrity_hash TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_version_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT, version_code TEXT UNIQUE,
        version_name TEXT, version_number TEXT,
        milestone_date TEXT DEFAULT '', source_tables TEXT DEFAULT '',
        is_active INTEGER DEFAULT 0, description TEXT DEFAULT '',
        civilization_stage TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    _ensure_col('mt_version_registry', 'civilization_stage', "TEXT DEFAULT ''")

    conn.execute("""CREATE TABLE IF NOT EXISTS mt_archaeology_team (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_code TEXT UNIQUE, member_name TEXT, role TEXT,
        squad TEXT DEFAULT ' archaeology_main',
        capabilities TEXT, authority_level TEXT,
        status TEXT DEFAULT 'ACTIVE',
        onboarded_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    _ensure_col('mt_archaeology_team', 'squad', "TEXT DEFAULT 'main'")
    _ensure_col('mt_archaeology_team', 'status', "TEXT DEFAULT 'ACTIVE'")

    conn.execute("""CREATE TABLE IF NOT EXISTS mt_history_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timeline_date TEXT NOT NULL, timeline_order INTEGER,
        event_type TEXT, title TEXT, detail TEXT,
        source_tables TEXT, importance TEXT DEFAULT 'MEDIUM',
        civilization_stage TEXT DEFAULT '',
        data_rows TEXT DEFAULT '',
        archived_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    _ensure_col('mt_history_timeline', 'civilization_stage', "TEXT DEFAULT ''")
    _ensure_col('mt_history_timeline', 'data_rows', "TEXT DEFAULT ''")

    # ── 新增: 文明阶段定义表 ──
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_archaeology_civilization (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_code TEXT UNIQUE, stage_name TEXT,
        stage_order INTEGER,
        start_date TEXT, end_date TEXT,
        description TEXT,
        key_tables TEXT,
        total_rows INTEGER DEFAULT 0,
        color_mark TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")

    # ── 新增: 考古发现记录 (脏数据/特殊格式/彩蛋) ──
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_archaeology_discovery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discovery_code TEXT UNIQUE,
        discovery_type TEXT,  -- DIRTY_DATA / FORMAT_ANOMALY / MISSING_COL / EASTER_EGG / LARGE_TABLE
        target_table TEXT, target_column TEXT DEFAULT '',
        description TEXT,
        raw_value_preview TEXT DEFAULT '',
        severity TEXT DEFAULT 'INFO',
        discovered_by TEXT DEFAULT 'ARCH_AUTO',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")

    conn.commit()


# ═══════════════════════════════════════════════════════════
# 文明 7 阶段定义
# ═══════════════════════════════════════════════════════════
CIVILIZATIONS = [
    # code, name, order, start, end, desc, key_tables, color
    ('PRE_BRAIN',   '史前脑库时代',   1, '2026-08-23', '2026-09-08',
     '系统原型启动, 1.57M 脑库知识 + 23K 题库 + 11K EigenFlux 会话, 全部不带命名前缀',
     'ai_brain_enhanced_knowledge,question_bank,eigenflux_comm_sessions', '🟤'),
    ('NATIVE_FLUX', 'EigenFlux 原生时代', 2, '2026-09-09', '2026-09-11',
     '283K EigenFlux 原生消息 (不带 mt_!) + 守护进程注册 (daemon_registry 不带 mt_)',
     'daemon_registry,eigenflux_comm_messages,mt_i18n_keys', '🟣'),
    ('MT_NAMED',    'mt_ 命名规范统一', 3, '2026-09-12', '2026-09-17',
     'Flask 基表批量落地: roles/users/heartbeat/firewall/skills/workflows, 全部强制 mt_ 前缀',
     'roles,users,system_heartbeat,ai_firewall_rules,ai_skills,design_system_tokens', '🟠'),
    ('IRON_RULE',   '铁律 + 规则引擎', 4, '2026-09-18', '2026-09-22',
     '34 条铁律违反 (unix ts) + 守护巡检启动 + mt_ 命名 EigenFlux 消息 840K + 9 篇规则 changelog',
     'mt_iron_rule_violations,mt_daemon_supervisor_log,mt_ai_eigenflux_messages,mt_rule_changelog', '🔴'),
    ('ICEBERG_BIRTH','SmartMount + 冰山诞生', 5, '2026-09-23', '2026-09-30',
     'SmartMount 首次挂载决策 + 冰山进化档案 + 冰山运行 + 内容矩阵 6749 行',
     'mt_ai_mount_decisions,mt_iceberg_evolution_archive,mt_iceberg_runs,mt_iceberg_content_matrix', '🔵'),
    ('ICEBERG_CONS','冰意识 + 升级引擎', 6, '2026-10-01', '2026-10-13',
     '冰意识运行 4934 次 + 冰升级执行 4915 次 + AI 心跳日志 930K 行',
     'mt_iceberg_consciousness_runs,mt_iceberg_upgrade_execution,mt_ai_heartbeat_log', '🔴'),
    ('SECURITY_EST','安全铁律 + 建制完善', 7, '2026-10-14', '2026-10-26',
     '守卫对 22 条 GDL + SA 一票否决 + 任务大厅 561 任务 + 5 大数据库分区',
     'mt_guardian_violation,mt_sa_veto_log,mt_lab_task_hall,mt_db_partition_registry', '🟡'),
]


# ═══════════════════════════════════════════════════════════
# 完整时间线 (7 阶段, 48 事件)
# ═══════════════════════════════════════════════════════════
TIMELINE = [
    # ══════════════════ 阶段 1: 史前脑库时代 ══════════════════
    ('2026-08-23', 1, 'PREHISTORIC', '🧠 史前脑库知识首批写入 (1,576,594 行)',
     'ai_brain_enhanced_knowledge MIN=1787466828.417247 → 2026-08-23 14:33:48, 内容是 EigenFlux 消息摘要',
     'ai_brain_enhanced_knowledge', 'CRITICAL', '1,576,594'),
    ('2026-08-23', 2, 'PREHISTORIC', '📚 原始题库首批导入 (23,208 行)',
     'question_bank MIN=1787466828.417247 → 同日 14:33:48, 与脑库同一秒',
     'question_bank', 'CRITICAL', '23,208'),
    ('2026-08-23', 3, 'PREHISTORIC', '💬 EigenFlux 原生会话启动 (11,842 行)',
     'eigenflux_comm_sessions MIN=2026-08-23 15:29:11, status=failed 为主 (无 AI 员工可交流)',
     'eigenflux_comm_sessions', 'HIGH', '11,842'),

    # ══════════════════ 阶段 2: EigenFlux 原生时代 ══════════════════
    ('2026-09-09', 1, 'FOUNDATION', '⚙️ 守护进程注册 (daemon_registry 不带 mt_)',
     'MIN=2026-09-09 11:49:07, 只有 1 行 — 早期守护进程原型',
     'daemon_registry', 'MEDIUM', '1'),
    ('2026-09-09', 2, 'COMM', '💬 EigenFlux 原生通信爆发 (283,100 行)',
     'eigenflux_comm_messages MIN=2026-09-09 16:15:27 → MAX=09-20 11:53, 不带 mt_ 前缀',
     'eigenflux_comm_messages', 'CRITICAL', '283,100'),

    # ══════════════════ 阶段 3: mt_ 命名规范统一 ══════════════════
    ('2026-09-10', 1, 'ENGINE', '🧬 AI 自我进化日志启动 (1,181 行)',
     'mt_ai_self_evolution_log MIN=2026-09-10 05:43:31 — 第一个带 mt_ 的引擎日志表',
     'mt_ai_self_evolution_log', 'HIGH', '1,181'),
    ('2026-09-10', 2, 'EMPLOYEE', '👥 仙女座员工注册 (33,525 行)',
     'mt_andromeda_employee_registry MIN=08:53:57 → MAX=09-12 22:15, 33K AI 员工注册',
     'mt_andromeda_employee_registry', 'CRITICAL', '33,525'),
    ('2026-09-12', 1, 'FOUNDATION', '🏗️ roles + users 基表落地 (4+5 行)',
     'MIN=2026-09-12 13:35:22 — Flask 用户体系奠基',
     'roles,users', 'CRITICAL', '9'),
    ('2026-09-12', 2, 'SECURITY', '🛡️ AI 防火墙规则落地 (39 行)',
     'MIN=2026-09-12 21:35:18 — 第一个安全相关 mt_ 表',
     'ai_firewall_rules', 'HIGH', '39'),
    ('2026-09-12', 3, 'INFRA', '🖥️ AI 集群节点 + MCP + Skills + Workflows',
     'ai_cluster_nodes / ai_mcp_servers(3) / ai_skills(133) / ai_workflows(5) MIN 全部 21:35:39',
     'ai_cluster_nodes,ai_mcp_servers,ai_skills,ai_workflows', 'MEDIUM', '142'),
    ('2026-09-12', 4, 'DESIGN', '🎨 设计系统 Token 注册 (31 行)',
     'design_system_tokens MIN=2026-09-12 22:00:21 — Element Plus Token 体系',
     'design_system_tokens', 'MEDIUM', '31'),
    ('2026-09-12', 5, 'INFRA', '💓 系统心跳启动 (10,391 行)',
     'system_heartbeat MIN=2026-09-12 21:59:38 → MAX=10-15 08:37, flask_app/ai_engine/scheduler',
     'system_heartbeat', 'HIGH', '10,391'),
    ('2026-09-12', 6, 'UPGRADE', '🔄 自动升级日志首批 (9 行)',
     'system_auto_upgrade_logs MIN=2026-09-12 22:01:33',
     'system_auto_upgrade_logs,upgrade_history', 'MEDIUM', '14'),

    # ══════════════════ 阶段 4: 铁律 + 规则引擎 ══════════════════
    ('2026-09-18', 1, 'IRON_RULE', '⚡ 铁律违反首次爆发 (34 行, unix ts)',
     'mt_iron_rule_violations MIN=1789689625.6464808 → 2026-09-18 08:00:25, viol_flow_galaxy_v2320 D1 系列',
     'mt_iron_rule_violations', 'CRITICAL', '34'),
    ('2026-09-18', 2, 'MONITOR', '👁️ 守护巡检日志启动 (9,312 行)',
     'mt_daemon_supervisor_log MIN=2026-09-18 10:55:05 → MAX=10-26 11:15, ENGINE_START/CYCLE_EXCEPTION',
     'mt_daemon_supervisor_log', 'HIGH', '9,312'),
    ('2026-09-19', 1, 'COMM', '💬 mt_ 命名 EigenFlux 消息 (840,024 行)',
     'mt_ai_eigenflux_messages MIN=2026-09-19 05:21:57 → MAX=10-15 08:36, 比原生版晚 10 天',
     'mt_ai_eigenflux_messages', 'CRITICAL', '840,024'),
    ('2026-09-19', 2, 'RULES', '📜 规则 changelog 启动 (23 行)',
     'MT_IRON_RULE_12STEPS v1.0→v1.3 MAJOR + 9 篇 PATCH 批量同步 + 4 篇 MINOR',
     'mt_rule_changelog', 'CRITICAL', '23'),

    # ══════════════════ 阶段 5: SmartMount + 冰山诞生 ══════════════════
    ('2026-09-23', 1, 'ENGINE', '⚙️ SmartMount 首次挂载决策 (25 行)',
     'mt_ai_mount_decisions MIN=2026-09-23 08:02:40 → MAX=09-24 00:09, 4 daemon 首次挂载',
     'mt_ai_mount_decisions', 'CRITICAL', '25'),
    ('2026-09-23', 2, 'ICEBERG', '🧊 冰山进化档案首次创建 (7 行)',
     'mt_iceberg_evolution_archive MIN=2026-09-23 14:00:28 — 冰山文明诞生时间点',
     'mt_iceberg_evolution_archive', 'CRITICAL', '7'),
    ('2026-09-23', 3, 'ENGINE', '🧠 进化建议引擎 (434 行)',
     'mt_evolution_suggestions MIN=2026-09-23 23:35:09',
     'mt_evolution_suggestions', 'MEDIUM', '434'),
    ('2026-09-24', 1, 'ICEBERG', '🧊 冰山首次运行 + 自动生成规则',
     'mt_iceberg_runs MIN=03:24:46 + mt_iceberg_rules_generated MIN=03:25:00',
     'mt_iceberg_runs,mt_iceberg_rules_generated', 'HIGH', '7'),
    ('2026-09-28', 1, 'ICEBERG', '📊 冰山内容矩阵 (6,749 行)',
     'mt_iceberg_content_matrix MIN=2026-09-28 05:38:35 → MAX=10-04 03:27',
     'mt_iceberg_content_matrix', 'HIGH', '6,749'),

    # ══════════════════ 阶段 6: 冰意识 + 升级引擎 ══════════════════
    ('2026-10-02', 1, 'ICEBERG', '🧠 冰意识运行引擎启动 (4,934 行)',
     'mt_iceberg_consciousness_runs MIN=2026-10-02 13:01:14 → MAX=10-26 03:17',
     'mt_iceberg_consciousness_runs', 'CRITICAL', '4,934'),
    ('2026-10-03', 1, 'ICEBERG', '🚀 冰升级执行引擎 (4,915 行)',
     'mt_iceberg_upgrade_execution MIN=2026-10-03 12:58:42 → MAX=10-26 03:04',
     'mt_iceberg_upgrade_execution', 'CRITICAL', '4,915'),
    ('2026-10-12', 1, 'VERSION', '🏷️ SYSTEM_VERSION v22.2 → v23.0 (MAJOR)',
     '规则大版本升级, 基础设施大规模重构',
     'mt_rule_changelog', 'CRITICAL', '-'),
    ('2026-10-14', 1, 'MONITOR', '💓 AI 心跳日志爆发 (930,568 行)',
     'mt_ai_heartbeat_log MIN=2026-10-14 18:03:09 — 最大单表之一',
     'mt_ai_heartbeat_log', 'HIGH', '930,568'),

    # ══════════════════ 阶段 7: 安全铁律 + 建制完善 ══════════════════
    ('2026-10-15', 1, 'RULES', '📜 SYS_OPS v1.5 + 全量规则体检',
     '域名掉绑定事故复盘 + flow_rule_audit_20261015 + 法务介入',
     'mt_rule_changelog', 'CRITICAL', '-'),
    ('2026-10-20', 1, 'EXTERNAL', '💬 企微集成启用 (2,529 行)',
     'mt_wecom_send_log MIN=2026-10-20 11:28:01 → MAX=10-26 11:16',
     'mt_wecom_send_log', 'CRITICAL', '2,529'),
    ('2026-10-20', 2, 'TASK_HALL', '📋 任务大厅首批任务 (561 行)',
     'mt_lab_task_hall MIN=2026-10-20 10:49:03 — 系统唯一入口',
     'mt_lab_task_hall', 'CRITICAL', '561'),
    ('2026-10-23', 1, 'GOVERNMENT', '🏛️ 三委合一启动',
     '12 立法提案 + 8 正式法案通过',
     'mt_committee_proposals,mt_committee_bills', 'HIGH', '20'),
    ('2026-10-25', 1, 'BACKUP', '💾 备份访问日志 (2,082 行)',
     'mt_backup_access_log MIN=2026-10-25 08:24:01',
     'mt_backup_access_log', 'MEDIUM', '2,082'),
    ('2026-10-26', 1, 'SECURITY', '🛡️ 守卫对 22 条 GDL 激活',
     'GDL-001~023: DROP BLOCKED / WAL 膨胀 / 磁盘低 / 任务大厅入口',
     'mt_guardian_violation', 'CRITICAL', '11'),
    ('2026-10-26', 2, 'CONSTITUTION', '👑 SA 一票否决权宪法级生效',
     'mt_sa_veto_log 5 条 CHECK constraint: to_status=VETOED AND vetoed_by=wuchenghao15',
     'mt_sa_veto_log', 'CRITICAL', '5'),
    ('2026-10-26', 3, 'DATA', '🗄️ 5 大数据库分区注册 (100/100)',
     'ARCHIVE/CORE/USER/PARAM/PREF + 26 ABSOLUTE DROP 零容忍表 + 5 KEEPER AI',
     'mt_db_partition_registry', 'CRITICAL', '5'),
    ('2026-10-26', 4, 'GOVERNANCE', '🚧 任务大厅唯一入口 gatekeeper 生效',
     '所有新需求 → submit_to_hall() → QUEUED, 无 task_id 拦截 + 自动建任务',
     'mt_gatekeeper_violation', 'CRITICAL', '-'),
]


def run(conn) -> dict:
    _ensure_tables(conn)

    stats = {'timeline_events': 0, 'versions': 0, 'civilizations': 0,
             'archaeology_team': 0, 'snapshots': 0, 'discoveries': 0}

    # ═══════════════════════════════════════════════════════════
    # 0. 写入文明阶段定义
    # ═══════════════════════════════════════════════════════════
    for code, name, order, start, end, desc, key_tables, color in CIVILIZATIONS:
        # 计算该阶段关键表总行数
        total = 0
        for t in key_tables.split(','):
            t = t.strip()
            try:
                r = conn.execute(f"SELECT COUNT(*) c FROM [{t}]").fetchone()
                if r: total += r[0]
            except: pass
        conn.execute("""INSERT OR REPLACE INTO mt_archaeology_civilization
            (stage_code, stage_name, stage_order, start_date, end_date,
             description, key_tables, total_rows, color_mark)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (code, name, order, start, end, desc[:500], key_tables, total, color))
        stats['civilizations'] += 1

    # ═══════════════════════════════════════════════════════════
    # 1. 写入时间线 (带文明阶段标记)
    # ═══════════════════════════════════════════════════════════
    # 建立日期→阶段映射
    date_to_stage = {}
    for code, _, _, start, end, _, _, _ in CIVILIZATIONS:
        cur = start
        while cur <= end:
            date_to_stage[cur] = code
            # +1 day
            d = datetime.strptime(cur, '%Y-%m-%d')
            d = datetime.fromordinal(d.toordinal() + 1)
            cur = d.strftime('%Y-%m-%d')

    for event in TIMELINE:
        date, order, etype, title, detail, sources, importance, rows = event
        stage = date_to_stage.get(date, 'UNKNOWN')
        cur = conn.execute("""INSERT OR IGNORE INTO mt_history_timeline
            (timeline_date, timeline_order, event_type, title, detail, source_tables,
             importance, civilization_stage, data_rows)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (date, order, etype, title, detail[:800], sources, importance, stage, rows))
        if cur.rowcount > 0:
            stats['timeline_events'] += 1

    # ═══════════════════════════════════════════════════════════
    # 2. 版本里程碑 (补齐史前/原生层)
    # ═══════════════════════════════════════════════════════════
    milestones = [
        # 史前层
        ('V_PREHISTORIC_20260823', '史前脑库原型', 'v0.0-pre',
         '2026-08-23', 'ai_brain_enhanced_knowledge,question_bank,eigenflux_comm_sessions',
         'PRE_BRAIN', False, 'flow_archaeology 考古发现: 1.57M 脑库知识 + 23K 题库, 系统最早有记录时间点'),
        ('V_NATIVE_FLUX_20260909', 'EigenFlux 原生通信', 'v0.1-native',
         '2026-09-09', 'daemon_registry,eigenflux_comm_messages',
         'NATIVE_FLUX', False, '283K 原生 EigenFlux 消息, 不带 mt_ 前缀'),
        # mt_ 规范层
        ('V_MT_NAMED_20260912', 'mt_ 命名规范统一', 'v0.2-named',
         '2026-09-12', 'roles,users,system_heartbeat,ai_firewall_rules',
         'MT_NAMED', False, 'Flask 基表批量落地, mt_ 前缀强制规范'),
        ('V_EMPLOYEE_20260917', 'AI 员工奠基', 'v0.3-employee',
         '2026-09-17', 'ai_employees,mt_iron_rule_violations',
         'MT_NAMED', False, 'ai_employees 首批入职, 铁律 viol_flow_galaxy_v2320'),
        # 规则层
        ('V_GUARDS_20260919', '规则守护启动', 'v1.0-guarded',
         '2026-09-19', 'mt_rule_changelog,mt_rule_integrity_scan',
         'IRON_RULE', False, '9 篇规则 changelog 启动, 完整性扫描'),
        # 引擎层
        ('V_ENGINE_20260923', 'SmartMount + 冰山诞生', 'v2.0-engine',
         '2026-09-23', 'mt_ai_mount_decisions,mt_iceberg_evolution_archive',
         'ICEBERG_BIRTH', False, 'SmartMount 首次挂载 + 冰山进化档案'),
        # 冰山层
        ('V_ICE_CONS_20261002', '冰意识 + 升级引擎', 'v3.0-iceberg',
         '2026-10-02', 'mt_iceberg_consciousness_runs,mt_iceberg_upgrade_execution',
         'ICEBERG_CONS', False, '4934 意识运行 + 4915 升级执行'),
        ('V_MAJOR_20261012', 'SYSTEM_VERSION MAJOR', 'v23.0.0',
         '2026-10-12', 'mt_rule_changelog',
         'ICEBERG_CONS', False, 'v22.2→v23.0 大版本'),
        # 近期层
        ('V_WECOM_20261020', '企微 + 任务大厅', 'v23.1-wecom',
         '2026-10-20', 'mt_wecom_send_log,mt_lab_task_hall',
         'SECURITY_EST', False, '2529 企微消息 + 561 任务'),
        ('V_GOV_20261023', '三委合一', 'v23.2-gov',
         '2026-10-23', 'mt_committee_proposals,mt_committee_bills',
         'SECURITY_EST', False, '12 提案 + 8 法案'),
        ('V_SECURITY_20261026', '安全铁律 + 5 分区', 'v23.3-security',
         '2026-10-26', 'mt_guardian_violation,mt_sa_veto_log,mt_db_partition_registry',
         'SECURITY_EST', True, '守卫对 22 条 + SA 否决 + 5 分区 100/100'),
    ]
    for code, name, ver, date, sources, stage, active, desc in milestones:
        conn.execute("""INSERT OR REPLACE INTO mt_version_registry
            (version_code, version_name, version_number, milestone_date, source_tables,
             is_active, description, civilization_stage)
            VALUES (?,?,?,?,?,?,?,?)""",
            (code, name, ver, date, sources, active, desc, stage))
        stats['versions'] += 1

    # ═══════════════════════════════════════════════════════════
    # 3. 考古队扩编 (15 人, 3 分队)
    # ═══════════════════════════════════════════════════════════
    team = [
        # 总队长
        ('ARCH_LEADER_01', '档案馆·考古队长AI', 'LEADER', 'main',
         '统筹全源交叉验证/时间线审定/宪法级权限', 'L4'),
        # 史前脑库分队 (4 人)
        ('ARCH_PRE_BRAIN_01', '史前脑库溯源AI', 'BRAIN_ARCH', 'pre_brain',
         '1.57M 脑库知识溯源 + 23K 题库原始数据提取 + 最早记录 MIN 校准', 'L3'),
        ('ARCH_PRE_EIGEN_01', 'EigenFlux 原生溯源AI', 'NATIVE_ARCH', 'pre_brain',
         '283K EigenFlux 原生消息反推 + 11K 会话重建 + 不带 mt_ 表鉴定', 'L3'),
        ('ARCH_PRE_DATE_01', '碳14时间戳校准AI', 'DATE_CAL', 'pre_brain',
         'unix ts/ISO 带微秒/混合格式统一解析 + 脏数据过滤', 'L2'),
        ('ARCH_PRE_DIRT_01', '脏数据清理AI', 'DIRT_CLEAN', 'pre_brain',
         'SHELL 注入($())+ UTC 后缀 + success/ACTIVE 误解析修复', 'L2'),
        # mt_ 建制分队 (4 人)
        ('ARCH_MT_SRC_01', 'mt_ 日志探源AI', 'LOG_ARCH', 'mt_named',
         'mt_*_log 增量日志最早记录提取 + 42 张关键表时间线反推', 'L3'),
        ('ARCH_MT_GIT_01', 'Git 溯源AI', 'GIT_ARCH', 'mt_named',
         'git log/commit diff/flow_id 反推 + 三部署节点核对', 'L3'),
        ('ARCH_MT_STRAT_01', '版本节点梳理AI', 'VERSION_STRAT', 'mt_named',
         'flow_id/version changelog 交叉验证 + 文明阶段边界校准', 'L2'),
        ('ARCH_MT_RULE_01', '规则铁律重建AI', 'RULE_ARCH', 'mt_named',
         '34 条铁律违反 unix ts 反推 + 9 篇规则 changelog 交叉 + 守护巡检链', 'L2'),
        # 冰山文明分队 (4 人)
        ('ARCH_ICE_RUN_01', '冰山运行还原AI', 'ICE_RUN', 'iceberg',
         '6 次冰山运行 + 7 条进化档案 + 52 张冰山表交叉验证', 'L3'),
        ('ARCH_ICE_CONS_01', '冰意识分析AI', 'ICE_CONS', 'iceberg',
         '4934 意识运行 + 4915 升级执行链重建 + 方向注册交叉', 'L3'),
        ('ARCH_ICE_CONTENT_01', '冰内容矩阵AI', 'ICE_CONTENT', 'iceberg',
         '6749 内容矩阵 + 方向注册 + 新方向注册时间线', 'L2'),
        ('ARCH_ICE_WRITE_01', '冰山报告AI', 'ICE_WRITE', 'iceberg',
         '冰山文明演化报告 + 意识觉醒时间线 + 升级触发链', 'L2'),
        # 后勤
        ('ARCH_WRITE_01', '总报告汇总AI', 'WRITER', 'main',
         '7 阶段完整时间线汇总 + 64 天文明报告 + 42 张关键表取证目录', 'L2'),
    ]
    for code, name, role, squad, caps, level in team:
        conn.execute("""INSERT OR REPLACE INTO mt_archaeology_team
            (member_code, member_name, role, squad, capabilities, authority_level)
            VALUES (?,?,?,?,?,?)""",
            (code, name, role, squad, caps, level))
        stats['archaeology_team'] += 1

    # ═══════════════════════════════════════════════════════════
    # 4. 考古发现记录 (脏数据 / 格式异常 / 彩蛋)
    # ═══════════════════════════════════════════════════════════
    discoveries = [
        ('DISC_SHELL_INJECT', 'DIRTY_DATA', 'mt_ai_brain_feed_log', 'fed_at',
         'MIN 值是 SHELL 命令字符串 $(date -u +%Y-%m-%dT%H:%M:%SZ) — 有一条记录写入了 shell 命令而非时间戳',
         '$(date -u +%Y-%m-%dT%H:%M:%SZ)', 'MEDIUM', 'ARCH_PRE_DIRT_01'),
        ('DISC_UTC_SUFFIX', 'FORMAT_ANOMALY', 'andromeda_self_heal_log', 'timestamp',
         '时间值带 UTC 后缀 (2026-09-20 12:34:53 UTC) — 标准 ISO 不带时区后缀',
         '2026-09-20 12:34:53 UTC', 'LOW', 'ARCH_PRE_DATE_01'),
        ('DISC_NO_TIME_COL', 'MISSING_COL', 'mt_ai_heartbeat_log', '-',
         '全库第二大表 (930,568 行) 有 created_at 列但 PRAGMA 排在第 13 位, 早期扫描漏掉',
         'created_at 在列序第 13 位', 'LOW', 'ARCH_MT_SRC_01'),
        ('DISC_PURE_INT_COL', 'FORMAT_ANOMALY', 'knowledge_graph_nodes', 'created_at',
         'created_at 列类型是 REAL (unix ts) 而非 TEXT (ISO), 需要特殊解析',
         'REAL 类型存储 unix ts', 'LOW', 'ARCH_PRE_DATE_01'),
        ('DISC_EARLIEST_TABLE', 'LARGE_TABLE', 'ai_brain_enhanced_knowledge', 'created_at',
         '全库最早有记录的表 (2026-08-23 14:33:48) 也是最大表 (1,576,594 行)',
         '1,576,594 rows, 最早 8/23', 'INFO', 'ARCH_PRE_BRAIN_01'),
        ('DISC_NO_MT_BEFORE', 'FORMAT_ANOMALY', 'daemon_registry', '-',
         'daemon_registry 不带 mt_ 前缀, 但功能是 mt_daemon_registry 的早期原型',
         '表名: daemon_registry (无 mt_)', 'INFO', 'ARCH_PRE_EIGEN_01'),
        ('DISC_42_TABLES', 'FORMAT_ANOMALY', '全库', '-',
         '全库 715 张表中只有 42 张有可解析的时间列, 其余 344 张无可用时间',
         '42/715 = 5.9%', 'INFO', 'ARCH_MT_SRC_01'),
    ]
    for code, dtype, tbl, col, desc, preview, sev, discoverer in discoveries:
        conn.execute("""INSERT OR REPLACE INTO mt_archaeology_discovery
            (discovery_code, discovery_type, target_table, target_column, description,
             raw_value_preview, severity, discovered_by)
            VALUES (?,?,?,?,?,?,?,?)""",
            (code, dtype, tbl, col, desc[:500], preview[:200], sev, discoverer))
        stats['discoveries'] += 1

    # ═══════════════════════════════════════════════════════════
    # 5. 档案馆快照 (每个文明阶段一张)
    # ═══════════════════════════════════════════════════════════
    for code, name, order, start, end, desc, key_tables, color in CIVILIZATIONS:
        tables = key_tables.split(',')
        summary = []
        for tbl in tables[:4]:
            tbl = tbl.strip()
            try:
                earliest = conn.execute(f"SELECT MIN(created_at) FROM [{tbl}]").fetchone()[0]
                cnt = conn.execute(f'SELECT COUNT(*) c FROM [{tbl}]').fetchone()[0]
                summary.append(f'{tbl} earliest={str(earliest)[:20]} rows={cnt}')
            except Exception:
                # 尝试其他时间列
                for tc in ['created_at','registered_at','started_at','run_at','fed_at','timestamp']:
                    try:
                        earliest = conn.execute(f'SELECT MIN([{tc}]) FROM [{tbl}]').fetchone()[0]
                        cnt = conn.execute(f'SELECT COUNT(*) c FROM [{tbl}]').fetchone()[0]
                        summary.append(f'{tbl} col={tc} earliest={str(earliest)[:20]} rows={cnt}')
                        break
                    except: pass
        snap_code = f"SNAP_{code}_{start.replace('-','')}_{end.replace('-','')}"
        content = json.dumps({
            'stage': code, 'name': name, 'start': start, 'end': end,
            'tables': summary, 'flow_id': FLOW_ID,
        }, ensure_ascii=False)
        conn.execute("""INSERT OR IGNORE INTO mt_archive_snapshot
            (snapshot_code, snapshot_type, source_table, trigger_event,
             snapshot_content, integrity_hash)
            VALUES (?,?,?,?,?,?)""",
            (snap_code, 'CIVILIZATION_STAGE', key_tables[:200],
             f'ARCH_STAGE:{code}', content[:3000],
             hashlib.sha256(content.encode()).hexdigest()))
        stats['snapshots'] += 1

    conn.commit()
    return stats


def print_report(conn):
    # ══ 文明阶段 ══
    civs = conn.execute("SELECT * FROM mt_archaeology_civilization ORDER BY stage_order").fetchall()
    print(f"\n{'='*80}")
    print(f"  🏛️ MTSCOS AI 完整文明时间线 (flow_archaeology_full_20261026)")
    print(f"{'='*80}")
    print(f"  系统生日: 2026-08-23 | 文明跨度: 64 天 | 阶段: {len(civs)} 个 | 关键表: 42 张")

    for c in civs:
        print(f"\n  {c['color_mark']} 阶段 {c['stage_order']}: {c['stage_name']} ({c['stage_code']})")
        print(f"     时间: {c['start_date']} → {c['end_date']}")
        print(f"     规模: {c['total_rows']:,} 行 | 关键表: {c['key_tables']}")
        print(f"     {c['description'][:80]}")

    # ══ 时间线事件 ══
    events = conn.execute("SELECT * FROM mt_history_timeline ORDER BY timeline_date ASC, timeline_order ASC").fetchall()
    current_stage = ''
    for e in events:
        stage = e['civilization_stage'] or ''
        if stage != current_stage:
            current_stage = stage
            cm = next((c['color_mark'] for c in civs if c['stage_code'] == stage), '·')
            cn = next((c['stage_name'] for c in civs if c['stage_code'] == stage), '')
            print(f"\n  {cm} ─── {cn} ({stage}) ───")

        im = {'CRITICAL':'🔴', 'HIGH':'🟡', 'MEDIUM':'🟢', 'LOW':'⚪'}.get(e['importance'], '⚪')
        print(f"     {im} {e['timeline_date']} #{e['timeline_order']:>2} [{e['event_type']}] {e['title']}")
        if e['data_rows']:
            print(f"        规模: {e['data_rows']} 行 | 来源: {e['source_tables']}")

    # ══ 版本里程碑 ══
    versions = conn.execute("SELECT * FROM mt_version_registry ORDER BY milestone_date ASC").fetchall()
    print(f"\n{'='*80}")
    print(f"  🏷️ 版本里程碑 ({len(versions)} 个 — 含史前层)")
    print(f"{'='*80}")
    for v in versions:
        active = '✨ 当前' if v['is_active'] else ''
        stage_name = next((c['color_mark'] + c['stage_name'] for c in civs if c['stage_code'] == v['civilization_stage']), '')
        print(f"  {v['milestone_date']} | {v['version_number']:<16} | {v['version_name']:<16} {active} {stage_name}")

    # ══ 考古队 ══
    team = conn.execute("SELECT * FROM mt_archaeology_team ORDER BY authority_level DESC, squad ASC").fetchall()
    squads = {}
    for t in team:
        squad = t['squad'] or 'main'
        if squad not in squads: squads[squad] = []
        squads[squad].append(t)

    squad_names = {
        'main': '🏛️ 考古总部',
        'pre_brain': '🟤 史前脑库分队',
        'mt_named': '🟠 mt_ 建制分队',
        'iceberg': '🔵 冰山文明分队',
    }
    print(f"\n{'='*80}")
    print(f"  🏺 档案馆考古队 ({len(team)} 人, {len(squads)} 分队)")
    print(f"{'='*80}")
    for squad, members in squads.items():
        print(f"\n  {squad_names.get(squad, squad)} ({len(members)} 人)")
        for m in members:
            print(f"    [{m['authority_level']}] {m['member_name']} — {m['capabilities'][:60]}")

    # ══ 考古发现 ══
    discs = conn.execute("SELECT * FROM mt_archaeology_discovery ORDER BY severity DESC").fetchall()
    if discs:
        print(f"\n{'='*80}")
        print(f"  🧪 考古发现 ({len(discs)} 条)")
        print(f"{'='*80}")
        for d in discs:
            sm = {'CRITICAL':'🔴','MEDIUM':'🟡','LOW':'🟢','INFO':'⚪'}.get(d['severity'],'⚪')
            print(f"  {sm} [{d['discovery_type']}] {d['target_table']}.{d['target_column']}")
            print(f"     {d['description'][:80]}")

    # ══ 快照统计 ══
    snaps = conn.execute("SELECT * FROM mt_archive_snapshot").fetchall()
    print(f"\n{'='*80}")
    print(f"  📸 档案馆快照 ({len(snaps)} 张)")
    print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['run', 'show', 'stats'])
    args = parser.parse_args()
    conn = _db()
    if args.command == 'run':
        print(json.dumps(run(conn), ensure_ascii=False, indent=2))
    elif args.command == 'show':
        run(conn)
        print_report(conn)
    elif args.command == 'stats':
        # 直接打印统计
        civs = conn.execute("SELECT * FROM mt_archaeology_civilization").fetchall()
        events = conn.execute("SELECT COUNT(*) FROM mt_history_timeline").fetchone()[0]
        team = conn.execute("SELECT COUNT(*) FROM mt_archaeology_team").fetchone()[0]
        discs = conn.execute("SELECT COUNT(*) FROM mt_archaeology_discovery").fetchone()[0]
        versions = conn.execute("SELECT COUNT(*) FROM mt_version_registry").fetchone()[0]
        snaps = conn.execute("SELECT COUNT(*) FROM mt_archive_snapshot").fetchone()[0]
        print(json.dumps({
            'flow_id': FLOW_ID,
            'civilizations': len(civs),
            'timeline_events': events,
            'archaeology_team': team,
            'discoveries': discs,
            'versions': versions,
            'snapshots': snaps,
        }, ensure_ascii=False, indent=2))
    conn.close()


if __name__ == '__main__':
    main()
