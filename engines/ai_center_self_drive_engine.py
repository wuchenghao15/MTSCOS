#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_center_self_drive_engine — 13 中心 自主驱动引擎
===================================================
flow_center_self_drive_20261026

核心思想:
  中心 ≠ 被动接单执行器
  中心 = 有自主意识的生命体: 心跳 + 自检 + 自愈 + 自研发 + 自进化

完整生命周期 (每个中心都跑自己的循环):
  ┌──────────────────────────────────────────────────────────────────┐
  │  ① 心跳      — 每 60s 自报健康状态 (mt_center_pulse)            │
  │  ② 自检      — 每 600s 扫自己领域表的新鲜度/质量/缺口            │
  │  ③ 自愈      — 自检发现异常 → 自动灌任务大厅 (source=SELF_DRIVE) │
  │  ④ 自研发    — 取方向池 SEED → 升级 ACTIVE → 出方案 → 执行      │
  │  ⑤ 自进化    — DONE 方向 → 回灌 mt_center_direction_pool        │
  └──────────────────────────────────────────────────────────────────┘

产出表 (全量留痕 + 可追溯):
  mt_center_pulse          — 13 中心心跳 (每 60s)
  mt_center_self_check     — 自检报告 (每 600s)
  mt_center_self_drive_log — 完整动作日志 (全生命周期)
  mt_center_capability_map — 能力图谱 (中心→领域→自检项)

状态流转:
  direction_pool.status: SEED → ACTIVE → EXECUTING → DONE / FAILED
"""
from __future__ import annotations
import os, sys, time, json, sqlite3, hashlib, random
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
DB = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_center_self_drive_20261026"
DAEMON = "ai_center_self_drive"

# ═══════════════════════════════════════════════════════════════════
# §1 14 中心 × 自检矩阵 (center → [检查项: 表名/阈值/动作])
# ═══════════════════════════════════════════════════════════════════
# 每个中心声明自己负责的领域 → 系统自动扫表 → 发现缺口 → 自动自愈
CENTER_PROFILES = {
    # ── 对齐 mt_center_direction_pool 实际存的 center_name (23 个新中心体系) ──

    # ── 🤖 AI 引擎中心 (老名"AI引擎中心", DB 实际存"AI 引擎中心"— 注意有空格!) ──
    "AI 引擎中心": {
        "tables": [
            ("mt_daemon_registry", "守护进程注册表", None),
            # ai_employees 表已迁移/停用: 守护心跳由 mt_daemon_registry 统一承接, 不再单独设 ai_employees 新鲜度阈值
        ],
        "self_repair": [
            ("mt_daemon_registry", "FAILED 进程", "自动重启守护"),
        ],
        "rnd_domains": ["多模型路由优化", "RAG 向量压缩", "Agent 自主规划"],
    },

    # ── 🛠️ 部署运维中心 (老名"运维中心") ──
    "部署运维中心": {
        "tables": [
            # 守护心跳由 center-self-drive 自身每轮更新 mt_daemon_registry, 不再需要独立心跳新鲜度阈值
            ("mt_daemon_registry", "daemon 注册表", None),
        ],
        "self_repair": [
            ("mt_daemon_registry", "FAILED 进程", "自动重启守护"),
        ],
        "rnd_domains": ["端口漂移防护", "节点故障切换", "容量预测"],
    },

    # ── 🔒 安全审计中心 (老名"安全中心") ──
    "安全审计中心": {
        "tables": [
            ("mt_firewall_rules", "防火墙规则注册表", None),
            ("mt_threat_signals", "威胁信号新鲜度", 3600),
        ],
        "self_repair": [
            ("mt_firewall_rules", "ACTIVE 规则不足", "自动补规则"),
        ],
        "rnd_domains": ["零信任策略自动生成", "AI 攻击面建模", "密钥自动轮换"],
    },

    # ── 💾 数据备份中心 (老名"备份中心") ──
    "数据备份中心": {
        "tables": [
            ("mt_backup_webhook_throttle", "备份频率", 3600),
        ],
        "self_repair": [
            ("mt_daemon_registry", "备份守护心跳", "触发立即备份"),
        ],
        "rnd_domains": ["增量快照压缩", "三库一致性自愈", "跨节点协商"],
    },

    # ── 📊 数据研究中心 (老名"数据中心") ──
    "数据研究中心": {
        "tables": [
            ("mt_db_partition_registry", "5 分区完整度", None),
        ],
        "self_repair": [
        ],
        "rnd_domains": ["多源数据融合", "数据血缘追踪", "数据质量监控"],
    },

    # ── 🌱 教育题库中心 (老名一致) ──
    "教育题库中心": {
        "tables": [
            ("mt_edu_sync_log", "教辅同步新鲜度", 86400),
            ("mt_edu_sync_content", "题库产能", None),
        ],
        "self_repair": [
            ("mt_edu_sync_log", "24h 零新增", "触发教辅重同步"),
        ],
        "rnd_domains": ["新题型自动解构", "错题智能归因", "自适应出题"],
    },

    # ── 🎨 前端设计中心 (老名一致) ──
    "前端设计中心": {
        "tables": [
            ("ui_component_registry", "组件库完整度", None),
        ],
        "self_repair": [
        ],
        "rnd_domains": ["AI 自动 UI 合成", "WebGPU 实验", "沉浸式可视化"],
    },

    # ── 以下新中心仅在 direction_pool 存在, 无 self_check 表定义 ──
    # pulse_all / self_check_all / rnd_cycle_all 通过 _get_all_centers() 统一覆盖
    # 这些中心的自研发 (rnd) 循环将自动生效
}


# ═══════════════════════════════════════════════════════════════════
# §1.1 CENTERS 动态化: DB direction_pool ∪ CENTER_PROFILES
# 解决 CENTER_PROFILES 硬编码 14 老中心 vs direction_pool 存 23 新中心
# 不匹配导致自研发 (rnd_cycle_all) 永远找不到可升级方向的根因。
# ═══════════════════════════════════════════════════════════════════

def _get_all_centers() -> list:
    """运行时动态获取所有中心 (去重, 稳定顺序: 先 CENTER_PROFILES 再 direction_pool)"""
    try:
        c = _db()
        pool_rows = c.execute("SELECT DISTINCT center_name FROM mt_center_direction_pool").fetchall()
        c.close()
        pool_names = [r[0] for r in pool_rows]
    except Exception:
        pool_names = []
    # CENTER_PROFILES 的 key 在 pool_names 优先 (保持有 self_check 的中心在前)
    profile_names = [k for k in CENTER_PROFILES.keys() if k not in pool_names]
    seen = set()
    ordered = []
    for cn in list(CENTER_PROFILES.keys()) + pool_names + profile_names:
        if cn not in seen:
            seen.add(cn); ordered.append(cn)
    return ordered

# 启动时一次性快照 (loop 长驻进程, 每次 run_once 内也会 refresh)
CENTERS = _get_all_centers()


# ═══════════════════════════════════════════════════════════════════
# §2 数据库 + 建表 + 索引 (幂等, 可重复跑)
# ═══════════════════════════════════════════════════════════════════

_SCHEMA = [
    # 中心心跳 (每 60s)
    """CREATE TABLE IF NOT EXISTS mt_center_pulse (
        pulse_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT NOT NULL,
        health_score INTEGER DEFAULT 100,    -- 0-100 健康度
        status TEXT DEFAULT 'OK',            -- OK / WARN / CRITICAL / DOWN
        active_tasks INTEGER DEFAULT 0,       -- 执行中任务数
        queue_depth INTEGER DEFAULT 0,        -- 积压深度
        tables_checked INTEGER DEFAULT 0,
        anomalies_found INTEGER DEFAULT 0,
        rnd_directions INTEGER DEFAULT 0,     -- 当前 ACTIVE 方向数
        detail TEXT,                           -- JSON 详情
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(center_name, created_at))""",

    # 自检报告 (每 600s)
    """CREATE TABLE IF NOT EXISTS mt_center_self_check (
        check_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT NOT NULL,
        check_type TEXT NOT NULL,             -- TABLE_FRESHNESS / TABLE_INTEGRITY / DAEMON_HEALTH / DOMAIN_GAP
        target TEXT,                           -- 被检查的表/daemon
        metric TEXT,                           -- 指标名
        metric_value REAL,                     -- 实测值
        threshold REAL,                        -- 阈值
        result TEXT,                           -- PASS / WARN / FAIL
        auto_repaired INTEGER DEFAULT 0,      -- 是否已自愈
        repair_task_id INTEGER,               -- 自愈触发的任务大厅 ID
        detail TEXT,                           -- JSON
        created_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 完整动作日志 (全生命周期溯源)
    """CREATE TABLE IF NOT EXISTS mt_center_self_drive_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT NOT NULL,
        action TEXT NOT NULL,                  -- PULSE / SELF_CHECK / SELF_REPAIR / RND_START / RND_EXECUTE / RND_DONE / RND_FAIL
        direction_id INTEGER,                  -- 关联方向池 ID (可选)
        task_hall_id INTEGER,                  -- 关联任务大厅 ID (可选)
        outcome TEXT,                          -- OK / WARN / FAIL / STARTED / DONE / VETOED
        duration_ms INTEGER,
        detail TEXT,                           -- JSON
        created_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 方向池状态扩展 (upgrade: SEED→ACTIVE→EXECUTING→DONE)
    """CREATE TABLE IF NOT EXISTS mt_center_direction_execution (
        exec_id INTEGER PRIMARY KEY AUTOINCREMENT,
        direction_id INTEGER NOT NULL,
        center_name TEXT,
        direction_title TEXT,
        phase TEXT DEFAULT 'ACTIVE',           -- ACTIVE / EXECUTING / DONE / FAILED
        plan_summary TEXT,                     -- AI 自研发方案摘要
        auto_spawned_tasks INTEGER DEFAULT 0,  -- 自动灌了几个任务大厅单
        tasks_completed INTEGER DEFAULT 0,
        evidence TEXT,                          -- DONE 的真实证据 JSON
        started_at TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT,
        UNIQUE(direction_id))""",
]


def _db():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def install_schema():
    """建表 + 注册守护 + 写启动日志 (幂等)"""
    c = _db()
    created = 0
    for s in _SCHEMA:
        try:
            c.execute(s)
            created += 1
        except Exception:
            pass
    # 守护注册
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (DAEMON, f"14中心自主驱动: 心跳60s+自检600s+自愈+自研发", "RUNNING",
             now, os.getpid(),
             json.dumps({"flow_id": FLOW_ID, "centers": len(CENTERS)}, ensure_ascii=False),
             now))
    except Exception:
        pass
    # 启动日志
    try:
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, detail)
            VALUES (?,?,?,?)""",
            ("SYSTEM", "ENGINE_START", "OK",
             json.dumps({"flow_id": FLOW_ID, "centers": CENTERS}, ensure_ascii=False)))
    except Exception:
        pass
    c.close()
    return f"✅ 自建表 {created}/{len(_SCHEMA)}, 守护已注册, {len(CENTERS)} 中心就绪"


# ═══════════════════════════════════════════════════════════════════
# §3 心跳 (每 60s) — 每个中心自报健康 + 写 mt_center_pulse
# ═══════════════════════════════════════════════════════════════════

def _count_hall_queue(c, center_name):
    """中心认领的大厅积压数"""
    try:
        return c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE claim_owner LIKE ? AND status IN ('QUEUED','DISPATCHED')""",
            (f"%{center_name[:3]}%",)).fetchone()[0]
    except Exception:
        return 0


def _count_active_tasks(c, center_name):
    try:
        return c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE claim_owner LIKE ? AND status IN ('IN_PROGRESS','DISPATCHED')""",
            (f"%{center_name[:3]}%",)).fetchone()[0]
    except Exception:
        return 0


def _count_active_directions(c, center_name):
    try:
        return c.execute("""SELECT COUNT(*) FROM mt_center_direction_pool
            WHERE center_name=? AND status IN ('ACTIVE','EXECUTING')""",
            (center_name,)).fetchone()[0]
    except Exception:
        return 0


def pulse_center(c, center_name: str) -> dict:
    """单个中心心跳"""
    active = _count_active_tasks(c, center_name)
    queue = _count_hall_queue(c, center_name)
    dirs = _count_active_directions(c, center_name)

    # 健康度: 基础 100, 积压扣分, 异常加分
    health = 100
    anomalies = 0
    if queue > 20:
        health -= 30; anomalies += 1
    elif queue > 5:
        health -= 10
    if queue > 0 and active == 0:
        health -= 20; anomalies += 1  # 有积压无执行 → 僵尸中心
    health = max(0, min(100, health))
    status = 'OK' if health >= 80 else ('WARN' if health >= 50 else 'CRITICAL')

    c.execute("""INSERT INTO mt_center_pulse
        (center_name, health_score, status, active_tasks, queue_depth,
         anomalies_found, rnd_directions, detail)
        VALUES (?,?,?,?,?,?,?,?)""",
        (center_name, health, status, active, queue, anomalies, dirs,
         json.dumps({"queue": queue, "active": active, "dirs": dirs}, ensure_ascii=False)))
    return {"health": health, "status": status, "queue": queue, "anomalies": anomalies}


def pulse_all() -> list:
    """14 中心全心跳"""
    c = _db()
    results = []
    for cn in CENTERS:
        try:
            r = pulse_center(c, cn)
            results.append({"center": cn, **r})
        except Exception as e:
            results.append({"center": cn, "health": 0, "status": "DOWN", "err": str(e)[:80]})
    c.close()
    return results


# ═══════════════════════════════════════════════════════════════════
# §4 自检 (每 600s) — 扫自己领域表的新鲜度/完整度 → mt_center_self_check
# ═══════════════════════════════════════════════════════════════════

def _report_stale_to_hall(c, center_name: str, table: str, desc: str, age: float, stale_secs: int):
    """TABLE_FRESHNESS FAIL → 自动上报任务大厅 (24h 去重, 认领制闭环)"""
    try:
        recent = c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE source='TABLE_FRESHNESS_ALERT' AND description LIKE ?
            AND created_at > datetime('now','localtime','-24 hours')""",
            (f"%{table}%",)).fetchone()[0]
        if recent > 0:
            return
        code = f"HALL-STALE-{table.replace('_','')}-{datetime.now():%Y%m%d%H%M%S}"
        hours = age / 3600.0
        c.execute("""INSERT INTO mt_lab_task_hall
            (title, description, source, priority, status,
             hall_code, approval_status, publisher, publisher_role, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (f"[表停滞] {center_name}: {table} {hours:.0f}h未更新",
             f"旧体系中心 {center_name} 自检发现表 {table} ({desc}) 已 {hours:.1f} 小时无写入"
             f"(阈值 {stale_secs}s)。请认领排查: 1)确认职能是否已迁移至新17中心体系 "
             f"2)若未迁移则修复写入链路 3)若已废弃则标记退役。",
             "TABLE_FRESHNESS_ALERT", "HIGH", "QUEUED",
             code, "APPROVED", "ai_center_self_drive", "hall_ingest"))
    except Exception:
        pass


def _check_table_freshness(c, center_name: str, table: str, desc: str, stale_secs: int | None):
    """检查表最近产出新鲜度"""
    now = time.time()
    try:
        rows = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        result = "PASS"
        metric = rows
        threshold = 1
        if rows == 0:
            result = "WARN"
        elif stale_secs:
            try:
                # 取最近 10 行里 max created_at
                latest = c.execute(
                    f"SELECT MAX(created_at) FROM (SELECT created_at FROM {table} ORDER BY rowid DESC LIMIT 10)").fetchone()[0]
                if latest:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.strptime(latest, "%Y-%m-%d %H:%M:%S")
                        age = (datetime.now() - dt).total_seconds()
                        metric = int(age)
                        threshold = stale_secs
                        if age > stale_secs:
                            result = "FAIL"
                            # → 触发自愈
                            trigger_self_repair(c, center_name, table, desc, "新鲜度超阈值", age, stale_secs)
                            # → FAIL 自动上报任务大厅 (24h 去重 + hall_code 幂等)
                            _report_stale_to_hall(c, center_name, table, desc, age, stale_secs)
                    except Exception:
                        pass
            except Exception:
                pass
        c.execute("""INSERT INTO mt_center_self_check
            (center_name, check_type, target, metric, metric_value, threshold, result, detail)
            VALUES (?,?,?,?,?,?,?,?)""",
            (center_name, "TABLE_FRESHNESS", table, desc, metric, threshold, result,
             json.dumps({"rows": rows}, ensure_ascii=False)))
        return {"table": table, "result": result, "metric": metric}
    except Exception as e:
        c.execute("""INSERT INTO mt_center_self_check
            (center_name, check_type, target, metric, metric_value, threshold, result, detail)
            VALUES (?,?,?,?,?,?,?,?)""",
            (center_name, "TABLE_FRESHNESS", table, desc, -1, stale_secs or 0, "SKIP",
             json.dumps({"error": str(e)[:100]}, ensure_ascii=False)))
        return {"table": table, "result": "SKIP"}


def self_check_center(c, center_name: str) -> dict:
    """单个中心自检"""
    profile = CENTER_PROFILES.get(center_name)
    if not profile:
        return {"checked": 0}
    results = []
    for table, desc, stale_secs in profile.get("tables", []):
        results.append(_check_table_freshness(c, center_name, table, desc, stale_secs))
    return {"center": center_name, "checks": results,
            "fails": sum(1 for r in results if r.get("result") == "FAIL")}


def self_check_all() -> dict:
    c = _db()
    summary = {"fails": {}, "total_checks": 0}
    for cn in CENTERS:
        r = self_check_center(c, cn)
        summary["total_checks"] += len(r.get("checks", []))
        if r.get("fails", 0) > 0:
            summary["fails"][cn] = r["fails"]
    c.close()
    return summary


# ═══════════════════════════════════════════════════════════════════
# §5 自愈 — 自检发现异常 → 自动灌任务大厅 (source=CENTER_SELF_DRIVE)
# ═══════════════════════════════════════════════════════════════════

def trigger_self_repair(c, center_name, table, desc, reason, metric, threshold):
    """触发自愈: 直接写任务大厅 + 留痕"""
    try:
        # 防重复: 1h 内同一中心+表 已灌过就跳过
        recent = c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE claim_owner LIKE ? AND description LIKE ?
            AND created_at > datetime('now','localtime','-1 hours')""",
            (f"%{center_name[:3]}%", f"%{table}%")).fetchone()[0]
        if recent > 0:
            return None

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        title = f"[自愈] {center_name}: {desc} — {reason}"
        c.execute("""INSERT INTO mt_lab_task_hall
            (title, description, source, publisher, publisher_role, priority,
             claim_owner, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (title,
             f"center_self_drive_engine 自检发现: 表={table} 指标={metric} 阈值={threshold} 自动触发自愈",
             "CENTER_SELF_DRIVE", "ai_center_self_drive", "AUTO", "HIGH",
             center_name, "QUEUED", now))
        tid = c.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 同时写 mt_maintenance_log 让巡逻队也能感知 (表不存在时跳过, 不影响自愈主流程)
        try:
            c.execute("""INSERT INTO mt_maintenance_log
                (corps_id, task_id, action, detail)
                VALUES (?,?,?,?)""",
                ("CENTER_SELF_DRIVE", str(tid), "SELF_REPAIR_TRIGGERED",
                 json.dumps({"center": center_name, "table": table, "reason": reason,
                             "task_hall_id": tid}, ensure_ascii=False)))
        except Exception:
            pass  # mt_maintenance_log 可能不存在, 忽略

        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, task_hall_id, outcome, detail)
            VALUES (?,?,?,?,?)""",
            (center_name, "SELF_REPAIR", tid, "QUEUED",
             json.dumps({"table": table, "reason": reason, "metric": metric}, ensure_ascii=False)))
        return tid
    except Exception as e:
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, detail)
            VALUES (?,?,?,?)""",
            (center_name, "SELF_REPAIR_FAIL", "FAIL", json.dumps({"error": str(e)[:150]}, ensure_ascii=False)))
        return None


# ═══════════════════════════════════════════════════════════════════
# §6 自研发 — 取 SEED 方向 → ACTIVE → 自动出方案 → 灌任务 → EXECUTING → DONE
# ═══════════════════════════════════════════════════════════════════

def _upgrade_seed_to_active(c, center_name: str, max_directions: int = 2) -> int:
    """把方向池 SEED 升级为 ACTIVE (每轮最多升 max_directions 个)

    room 计算修正: 只计入真正活跃的方向 (pool ACTIVE + execution phase != DONE).
    之前只数 pool ACTIVE 导致所有中心 room=0 (因为历史遗留 ACTIVE 方向 execution 全 DONE).
    """
    upgraded = 0
    try:
        # 真正活跃: pool ACTIVE/EXECUTING 且 execution 阶段还在跑
        active_count = c.execute("""
            SELECT COUNT(*) FROM mt_center_direction_pool d
            JOIN mt_center_direction_execution e ON d.direction_id = e.direction_id
            WHERE d.center_name=?
              AND d.status IN ('ACTIVE','EXECUTING')
              AND e.phase IN ('ACTIVE','EXECUTING')
        """, (center_name,)).fetchone()[0]
        room = max(0, max_directions - active_count)
        if room == 0:
            return 0

        seeds = c.execute("""SELECT direction_id, direction_title, seed
            FROM mt_center_direction_pool
            WHERE center_name=? AND status='SEED'
            ORDER BY priority DESC, ROWID DESC LIMIT ?""",
            (center_name, room)).fetchall()

        for did, title, seed in seeds:
            try:
                c.execute("""UPDATE mt_center_direction_pool
                    SET status='ACTIVE', auto_spawned=1 WHERE direction_id=?""", (did,))
                # 用 REPLACE INTO 而非 INSERT OR IGNORE: 已存在 phase=DONE 的 stale 行
                # 必须重置为 ACTIVE, 否则 _rnd_auto_dispatch 找不到可灌单的 execution
                c.execute("""REPLACE INTO mt_center_direction_execution
                    (direction_id, center_name, direction_title, phase, plan_summary,
                     auto_spawned_tasks, tasks_completed, evidence, started_at, completed_at)
                    VALUES (?,?,?,?,?,?,0,0,NULL,datetime('now','localtime'),NULL)""",
                    (did, center_name, title, "ACTIVE",
                     f"自研发种子升级: {seed}"))
                c.execute("""INSERT INTO mt_center_self_drive_log
                    (center_name, action, direction_id, outcome, detail)
                    VALUES (?,?,?,?,?)""",
                    (center_name, "RND_START", did, "ACTIVE",
                     json.dumps({"title": title, "seed": seed}, ensure_ascii=False)))
                upgraded += 1
            except Exception as e:
                pass
    except Exception:
        pass
    return upgraded


def _rnd_auto_dispatch(c, center_name: str, max_tasks: int = 2) -> int:
    """ACTIVE 方向 → 自动出 mini-plan → 灌任务大厅"""
    dispatched = 0
    try:
        actives = c.execute("""SELECT e.exec_id, e.direction_id, e.direction_title, e.plan_summary,
                                  d.priority
            FROM mt_center_direction_execution e JOIN mt_center_direction_pool d
            ON e.direction_id=d.direction_id
            WHERE e.center_name=? AND e.phase='ACTIVE'
            LIMIT ?""",
            (center_name, max_tasks)).fetchall()

        for eid, did, title, plan, prio in actives:
            try:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                task_title = f"[{center_name}·自研发] {title}"
                c.execute("""INSERT INTO mt_lab_task_hall
                    (title, description, source, publisher, publisher_role, priority,
                     claim_owner, status, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (task_title,
                     f"自研发方向自动灌单: {title}\n方案: {plan or '探索性研发, 无预设方案'}\n"
                     f"关联 direction_id={did}, center={center_name}",
                     "CENTER_SELF_DRIVE", "ai_center_self_drive", "AUTO",
                     "NORMAL", center_name, "QUEUED", now))
                tid = c.execute("SELECT last_insert_rowid()").fetchone()[0]

                c.execute("""UPDATE mt_center_direction_execution
                    SET phase='EXECUTING', auto_spawned_tasks=auto_spawned_tasks+1
                    WHERE exec_id=?""", (eid,))
                c.execute("""INSERT INTO mt_center_self_drive_log
                    (center_name, action, direction_id, task_hall_id, outcome, detail)
                    VALUES (?,?,?,?,?,?)""",
                    (center_name, "RND_EXECUTE", did, tid, "EXECUTING",
                     json.dumps({"title": title, "phase": "EXECUTING"}, ensure_ascii=False)))
                dispatched += 1
            except Exception:
                pass
    except Exception:
        pass
    return dispatched


def _rnd_collect_done(c, center_name: str) -> int:
    """EXECUTING 方向 → 查大厅 DONE → 升级 phase=DONE + 写证据"""
    done_count = 0
    try:
        rows = c.execute("""SELECT e.exec_id, e.direction_id, e.direction_title
            FROM mt_center_direction_execution e
            WHERE e.center_name=? AND e.phase='EXECUTING'""",
            (center_name,)).fetchall()
        for eid, did, title in rows:
            tasks = c.execute("""SELECT id, status FROM mt_lab_task_hall
                WHERE claim_owner LIKE ? AND description LIKE ?""",
                (f"%{center_name[:3]}%", f"%direction_id={did}%")).fetchall()
            done = [t for t in tasks if t[1] == 'DONE']
            if done and all(t[1] == 'DONE' for t in tasks):
                # 全 done → 升级方向
                c.execute("""UPDATE mt_center_direction_pool
                    SET status='DONE' WHERE direction_id=?""", (did,))
                c.execute("""UPDATE mt_center_direction_execution
                    SET phase='DONE', tasks_completed=?, evidence=?, completed_at=datetime('now','localtime')
                    WHERE exec_id=?""",
                    (len(done), json.dumps({"hall_tasks": [t[0] for t in tasks]}, ensure_ascii=False), eid))
                c.execute("""INSERT INTO mt_center_self_drive_log
                    (center_name, action, direction_id, outcome, detail)
                    VALUES (?,?,?,?,?)""",
                    (center_name, "RND_DONE", did, "DONE",
                     json.dumps({"hall_tasks": [t[0] for t in tasks]}, ensure_ascii=False)))
                done_count += 1
    except Exception:
        pass
    return done_count


def rnd_cycle_center(c, center_name: str) -> dict:
    """单个中心自研发循环: 升级 SEED → 自动灌单 → 收集 DONE"""
    upgrade = _upgrade_seed_to_active(c, center_name)
    dispatch = _rnd_auto_dispatch(c, center_name)
    done = _rnd_collect_done(c, center_name)
    return {"upgrade": upgrade, "dispatch": dispatch, "done": done}


def rnd_cycle_all() -> dict:
    c = _db()
    summary = {"upgrade": {}, "dispatch": {}, "done": {}}
    for cn in CENTERS:
        try:
            r = rnd_cycle_center(c, cn)
            for k in ("upgrade", "dispatch", "done"):
                if r[k] > 0:
                    summary[k][cn] = r[k]
        except Exception:
            pass
    c.close()
    return summary


# ═══════════════════════════════════════════════════════════════════
# §7 守护循环 (推荐 300s)
# ═══════════════════════════════════════════════════════════════════

def run_once() -> dict:
    """一轮完整驱动: 心跳 + 自检 + 自愈 + 自研发

    每次进入 run_once 都动态 refresh CENTERS, 保证长驻 daemon 进程
    在 direction_pool 新增中心时不用重启就能覆盖 (loop 300s 一轮)。
    """
    global CENTERS
    start = time.time()
    CENTERS = _get_all_centers()
    out = {"timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "active_centers": len(CENTERS)}

    c = _db()
    # ① 心跳
    out["pulse"] = pulse_all()

    # ② 自检 + 自愈
    out["self_check"] = self_check_all()

    # ③ 自研发
    c.close()
    out["rnd"] = rnd_cycle_all()

    elapsed = int((time.time() - start) * 1000)
    out["elapsed_ms"] = elapsed

    # daemon 心跳 + 主日志
    try:
        c = _db()
        c.execute("""UPDATE mt_daemon_registry
            SET last_heartbeat=datetime('now','localtime'), status='RUNNING', pid=?
            WHERE process_name=?""", (os.getpid(), DAEMON))
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, detail)
            VALUES (?,?,?,?)""",
            ("SYSTEM", "DRIVE_CYCLE", "OK", json.dumps(out, ensure_ascii=False)))
        c.close()
    except Exception:
        pass

    return out


def loop(poll_secs: int = 300):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {DAEMON} start, poll={poll_secs}s, centers={len(CENTERS)}", flush=True)
    while True:
        try:
            r = run_once()
            fails = r.get("self_check", {}).get("fails", {})
            total_queue = sum(p.get("queue", 0) for p in r.get("pulse", []))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                  f"✅ drive_cycle queue_total={total_queue} "
                  f"fails={len(fails)} rnd_upgrade={sum(r.get('rnd',{}).get('upgrade',{}).values())} "
                  f"rnd_dispatch={sum(r.get('rnd',{}).get('dispatch',{}).values())} "
                  f"rnd_done={sum(r.get('rnd',{}).get('done',{}).values())} "
                  f"({r.get('elapsed_ms',0)}ms)", flush=True)
            if fails:
                print(f"  ⚠️ fails: {list(fails.keys())}", flush=True)
        except Exception as e:
            sys.stderr.write(f"[self_drive] ERR: {e}\n")
        time.sleep(poll_secs)


# ═══════════════════════════════════════════════════════════════════
# §8 CLI + 展示
# ═══════════════════════════════════════════════════════════════════

def show_centers():
    c = _db()
    print(f"\n{'═'*72}")
    print(f"  🧠 14 中心 自主驱动引擎 — 状态快照")
    print(f"{'═'*72}")

    # 心跳 (每中心最新一条)
    try:
        rows = c.execute("""SELECT p.center_name, p.health_score, p.status,
            p.active_tasks, p.queue_depth, p.anomalies_found, p.rnd_directions
            FROM mt_center_pulse p JOIN (
                SELECT center_name, MAX(rowid) AS latest
                FROM mt_center_pulse GROUP BY center_name
            ) latest ON p.rowid=latest.latest
            ORDER BY p.health_score ASC""").fetchall()
        print(f"\n  {'中心':<14} {'健康':>4} {'状态':<10} {'执行':>4} {'积压':>4} {'异常':>4} {'方向':>4}")
        print(f"  {'-'*52}")
        for cn, h, st, act, qd, an, rd in rows:
            icon = "🟢" if h >= 80 else ("🟡" if h >= 50 else "🔴")
            print(f"  {icon} {cn:<14} {h:>3}/100 {st:<10} {act:>4} {qd:>4} {an:>4} {rd:>4}")
        missing = [cn for cn in CENTERS if cn not in [r[0] for r in rows]]
        if missing:
            print(f"  ⚪ {'  (未心跳)':<12} —  {' '.join(missing)}")
    except Exception as e:
        print(f"  [skip pulse]: {e}")

    # 方向池状态
    try:
        dirs = c.execute("""SELECT status, COUNT(*) FROM mt_center_direction_pool
            GROUP BY status ORDER BY COUNT(*) DESC""").fetchall()
        print(f"\n  📋 方向池状态: {'  '.join(f'{s}={n}' for s, n in dirs)}")
    except Exception:
        pass

    # 方向执行
    try:
        excs = c.execute("""SELECT phase, COUNT(*) FROM mt_center_direction_execution
            GROUP BY phase""").fetchall()
        if excs:
            print(f"  🔬 研发执行: {'  '.join(f'{p}={n}' for p, n in excs)}")
    except Exception:
        pass

    # 自愈
    try:
        rep = c.execute("""SELECT center_name, COUNT(*) FROM mt_center_self_check
            WHERE result='FAIL' GROUP BY center_name ORDER BY COUNT(*) DESC LIMIT 5""").fetchall()
        if rep:
            print(f"  🚨 自检 FAIL 最多的中心: {rep}")
    except Exception:
        pass

    c.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="🧠 14 中心 自主驱动引擎")
    p.add_argument("action", choices=[
        "install",   # 建表 + 注册守护
        "pulse",     # 单轮心跳
        "check",     # 单轮自检 + 自愈
        "rnd",       # 单轮自研发
        "once",      # 完整一轮 (心跳+自检+研发)
        "loop",      # 守护循环 (默认)
        "show",      # 状态快照
    ])
    p.add_argument("--poll", type=int, default=300)
    args = p.parse_args()

    if args.action == "install":
        print(install_schema())
    elif args.action == "pulse":
        print(json.dumps(pulse_all(), ensure_ascii=False, indent=2))
    elif args.action == "check":
        print(json.dumps(self_check_all(), ensure_ascii=False, indent=2))
    elif args.action == "rnd":
        print(json.dumps(rnd_cycle_all(), ensure_ascii=False, indent=2))
    elif args.action == "once":
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.action == "loop":
        install_schema()
        loop(args.poll)
    elif args.action == "show":
        show_centers()
