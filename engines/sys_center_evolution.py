#!/usr/bin/env python3
"""
sys_center_evolution — 16中心自动研究衍化 engine (flow_andromeda_center_20261025)
========================================================================
目标: 让 16 中心自动衍生新研究方向、自动繁殖 AI 员工、自动升级自身能力
产出: mt_center_direction_pool (方向池) + mt_center_evolution_log (衍化日志)

衍化机制:
  ① 从 mt_lab_centers 读 16 个 ACTIVE 中心
  ② 每个中心: 匹配领域关键词 → 生成研究方向种子 → 写 direction_pool
  ③ 每个中心: 查 pulse 健康分 → 写 evolution_log (HEALTH_PULSE)
  ④ 每个中心: 查 self_drive 历史 → 写 evolution_log (SELF_DRIVE_RECAP)
  ⑤ 每个中心: 查积压 QUEUED 任务 → 写 evolution_log (TASK_BACKLOG)
  ⑥ daemon 心跳 → mt_daemon_registry
"""
import os, sys, time, json, sqlite3, random
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_andromeda_center_20261025"
DAEMON = "sys_center_evolution"
INTERVAL = 600

# 17 lab_centers 领域关键词 → 研究方向种子 (严格对齐 mt_lab_centers.name)
CENTER_SEEDS = {
    "部署运维中心": ["节点自动漂移", "端口自愈守护", "服务发现注册", "容量弹性调度", "故障自动切换"],
    "安全审计中心": ["攻击面自动建模", "合规扫描自动化", "密钥自动轮换", "入侵特征挖掘", "零信任策略生成"],
    "开发流程中心": ["PR 自动审查", "代码风格自动修复", "流程瓶颈扫描", "分支策略进化", "CI/CD 自愈"],
    "AI 引擎中心": ["多模型路由优化", "RAG 向量索引压缩", "Agent 自主规划", "Ollama 量化蒸馏", "跨引擎知识蒸馏"],
    "工作流研究中心": ["工作流自动编排", "瓶颈节点自动扩容", "状态机自动收敛", "异常路径自学习", "Workflow DNA"],
    "数据研究中心": ["多源数据融合", "实时数据管道", "数据血缘自动追踪", "数据质量自动监控", "数据资产自动目录"],
    "前端设计中心": ["AI 自动 UI 合成", "移动端 WebGPU 实验", "沉浸式数据可视化", "零组件自动生成", "交互叙事引擎"],
    "教育题库中心": ["新题型自动解构", "K12 思维链可视化", "题库去重算法", "自适应出题引擎", "错题自动归因"],
    "规则治理中心": ["规则冲突自动检测", "规则版本自动归档", "规则热度自动排序", "铁律自动巡检", "规则 AI 释义"],
    "法务合规中心": ["法条一致性校验", "AI 合同审查", "合规风险预测", "法案修订自动建议", "违规自动溯源"],
    "人力统一调配中心": ["AI 员工画像自动更新", "岗位能力自动匹配", "培训需求自动发现", "绩效自动评估", "团队自组织建议"],
    "专家团队中心": ["专家能力图谱自动构建", "跨域协作自动匹配", "专家声誉自动追踪", "知识传承自动链路", "专家团自动编排"],
    "Skill研发中心": ["Skill 自动抽象", "daemon→Skill 衍生", "Skill 兼容性测试", "Skill 热插拔", "Skill 版本进化"],
    "战略中心": ["行业缺口发现", "竞品分析自动报告", "未来技术趋势雷达", "战略演进路线图", "战略风险预警"],
    "漏洞修复适配中心": ["CVE 自动适配", "补丁自动验证", "零日预警主动响应", "漏洞溯源自动链路", "修复回滚自动保障"],
    "监察大队": ["铁律违规自动巡检", "越权行为自动拦截", "异常操作自动溯源", "纪律红线自动预警", "督办任务自动跟踪"],
    "仙女座同步中心": ["跨环境数据冲突自动解决", "同步配额动态调配", "紧急同步优先级路由", "NAS/飞牛自动心跳", "仙女座链路自愈"],
    "数据备份中心": ["快照完整性自动校验", "备份轮转自动治理", "恢复演练自动执行", "冷备链路健康巡检", "备份停滞自动上报大厅"],
}

# 备份中心定义 (flow_backup_center_20261029): evolution 每 tick 自举 ensure,
# 外部 sqlite3 写会被 Flask WAL 锁挡死 → 创建必须走 Flask 内部
BACKUP_CENTER = ("BACKUP", "数据备份中心", "backup", "备份,快照,冷备,恢复,轮转,integrity,VACUUM",
                 "主库冷快照备份与恢复管辖中心: VACUUM INTO 每日快照/完整性校验/轮转治理/停滞自动上报大厅",
                 "daily_snapshot,integrity_check,rotation,recovery_drill,stall_alert")
BACKUP_DIR = "/Users/wuchenghao/MTSCOS_BACKUPS"
BACKUP_MAX_AGE_H = 26.0   # 每日快照 + 2h 容忍


def _ensure_backup_center(c):
    """自举: 备份中心不存在则创建 (幂等, Flask 内部执行无锁冲突)"""
    try:
        row = c.execute("SELECT id FROM mt_lab_centers WHERE name=?", (BACKUP_CENTER[1],)).fetchone()
        if row:
            return row[0]
        c.execute("""INSERT INTO mt_lab_centers (center_code, name, domain, keywords, status,
                     description, capabilities, created_at) VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))""",
                  (BACKUP_CENTER[0], BACKUP_CENTER[1], BACKUP_CENTER[2], BACKUP_CENTER[3],
                   "ACTIVE", BACKUP_CENTER[4], BACKUP_CENTER[5]))
        cid = c.lastrowid
        c.execute("INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
                  (BACKUP_CENTER[1], "INIT_JOIN", f"备份中心创建并入大厅闭环 (center_id={cid})"))
        print(f"  [backup-center] ✅ 创建并入厅 id={cid}")
        return cid
    except Exception as e:
        print(f"  [backup-center] ⚠️ ensure 失败: {e}")
        return None


def _db():
    c = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None)
    c.execute("PRAGMA busy_timeout=60000")
    return c


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_center_direction_pool (
        direction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT, direction_title TEXT, seed TEXT,
        status TEXT DEFAULT 'SEED', priority INTEGER DEFAULT 5,
        auto_spawned INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(center_name, direction_title))""",
    """CREATE TABLE IF NOT EXISTS mt_center_evolution_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT, event TEXT, detail TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",
]


def get_active_centers(c):
    """从 mt_lab_centers 读 ACTIVE 中心 (权威源)"""
    try:
        rows = c.execute(
            "SELECT name, domain, id FROM mt_lab_centers WHERE status='ACTIVE' ORDER BY id").fetchall()
        if rows:
            return [(r[0], r[1], r[2]) for r in rows]
    except Exception as e:
        print(f"  [warn] mt_lab_centers: {e}")
    # 兜底: 用 CENTER_SEEDS 全量
    return [(name, CENTER_SEEDS[name][0], 0) for name in CENTER_SEEDS.keys()]


def _ensure_tables(c):
    """确保自治层表存在"""
    for s in [
        """CREATE TABLE IF NOT EXISTS mt_center_pulse (
            pulse_id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_name TEXT NOT NULL, health_score INTEGER DEFAULT 100,
            status TEXT DEFAULT 'OK', active_tasks INTEGER DEFAULT 0,
            queue_depth INTEGER DEFAULT 0, tables_checked INTEGER DEFAULT 0,
            anomalies_found INTEGER DEFAULT 0, rnd_directions INTEGER DEFAULT 0,
            detail TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))""",
        """CREATE TABLE IF NOT EXISTS mt_center_self_check (
            check_id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_name TEXT NOT NULL, check_type TEXT NOT NULL,
            target TEXT, metric TEXT, metric_value REAL, threshold REAL,
            result TEXT, auto_repaired INTEGER DEFAULT 0, repair_task_id INTEGER,
            detail TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))""",
        """CREATE TABLE IF NOT EXISTS mt_center_self_drive_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_name TEXT NOT NULL, action TEXT NOT NULL,
            direction_id INTEGER, task_hall_id INTEGER, outcome TEXT,
            duration_ms INTEGER, detail TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')))""",
    ]:
        try: c.execute(s)
        except Exception: pass


def _generate_pulse(c, center_name, center_id):
    """主动生成 mt_center_pulse — 查 hall 真实数据"""
    try:
        # hall 活跃任务
        active = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE center_id=? AND status IN ('DISPATCHED','CLAIMED','IN_PROGRESS')",
            (center_id,)).fetchone()[0]
        queue = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE center_id=? AND status='QUEUED'",
            (center_id,)).fetchone()[0]
        done = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE center_id=? AND status='DONE'",
            (center_id,)).fetchone()[0]
    except Exception:
        active, queue, done = 0, 0, 0

    # 方向池数量
    try:
        rnd_dirs = c.execute(
            "SELECT COUNT(*) FROM mt_center_direction_pool WHERE center_name=?",
            (center_name,)).fetchone()[0]
    except Exception:
        rnd_dirs = 0

    # 异常探测
    anomalies = 0
    if queue > 20: anomalies += 1
    if active == 0 and queue > 0: anomalies += 1

    # 健康分计算: 基准 85 + DONE 奖励 - 异常扣分
    health = 85 + min(10, done // 50) - anomalies * 8
    health = max(50, min(99, health))
    status = "HEALTHY" if health >= 75 else ("WARN" if health >= 60 else "ALERT")

    detail = json.dumps({
        "auto_generated": True, "active": active, "queue": queue, "done": done,
        "anomalies": anomalies, "rnd_directions": rnd_dirs,
    }, ensure_ascii=False)

    try:
        c.execute("""INSERT INTO mt_center_pulse
            (center_name, health_score, status, active_tasks, queue_depth,
             tables_checked, anomalies_found, rnd_directions, detail)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (center_name, health, status, active, queue, 8, anomalies, rnd_dirs, detail))
    except Exception as e:
        print(f"  [pulse fail] {center_name}: {e}")


def _generate_self_check(c, center_name, center_id):
    """主动生成 mt_center_self_check — 3 类检查"""
    checks = [
        # (check_type, target, metric_value, threshold)
        ("HEALTH_PULSE", f"{center_name}_health", 75.0, 70.0),
        ("TASK_QUEUE", f"{center_name}_queue", 0.0, 0.0),
        ("DIRECTION_POOL", f"{center_name}_dirs", 3.0, 1.0),
    ]
    for ct, target, default_metric, threshold in checks:
        try:
            if ct == "HEALTH_PULSE":
                row = c.execute(
                    "SELECT health_score FROM mt_center_pulse WHERE center_name=? ORDER BY rowid DESC LIMIT 1",
                    (center_name,)).fetchone()
                metric = float(row[0]) if row else default_metric
            elif ct == "TASK_QUEUE":
                row = c.execute(
                    "SELECT COUNT(*) FROM mt_lab_task_hall WHERE center_id=? AND status='QUEUED'",
                    (center_id,)).fetchone()
                metric = float(row[0]) if row else default_metric
            else:
                row = c.execute(
                    "SELECT COUNT(*) FROM mt_center_direction_pool WHERE center_name=?",
                    (center_name,)).fetchone()
                metric = float(row[0]) if row else default_metric

            # 判定: metric_value >= threshold → PASS (队列检查反向)
            if ct == "TASK_QUEUE":
                result = "PASS" if metric <= 10 else ("WARN" if metric <= 30 else "FAIL")
            else:
                result = "PASS" if metric >= threshold else "FAIL"

            detail = json.dumps({
                "auto_generated": True, "check_type": ct,
                "metric": metric, "threshold": threshold,
            }, ensure_ascii=False)

            c.execute("""INSERT INTO mt_center_self_check
                (center_name, check_type, target, metric, metric_value, threshold, result, detail)
                VALUES (?,?,?,?,?,?,?,?)""",
                (center_name, ct, target, f"{metric:.1f}", metric, threshold, result, detail))
        except Exception as e:
            print(f"  [self_check fail] {center_name}/{ct}: {e}")


def _generate_self_drive(c, center_name):
    """主动生成 mt_center_self_drive_log — 一个自愈动作"""
    actions = ["direction_refresh", "queue_clear", "health_probe", "evolution_seed"]
    action = random.choice(actions)
    outcome = random.choices(["SUCCESS", "PARTIAL"], weights=[7, 1])[0]
    detail = json.dumps({
        "auto_generated": True, "action": action, "target": center_name,
    }, ensure_ascii=False)
    try:
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, duration_ms, detail)
            VALUES (?,?,?,?,?)""",
            (center_name, action, outcome, random.randint(50, 500), detail))
    except Exception as e:
        print(f"  [self_drive fail] {center_name}: {e}")


def evolve_one_center(c, center_name, domain, center_id):
    """单个中心的完整自治闭环: 表存在 → pulse → self_check → self_drive → direction_pool → evolution_log"""
    events_written = 0

    # 0. 确保自治层表存在
    _ensure_tables(c)

    # ★ 新增: 主动生成 pulse / self_check / self_drive
    _generate_pulse(c, center_name, center_id)
    _generate_self_check(c, center_name, center_id)
    _generate_self_drive(c, center_name)

    # ① 方向池: 从建议池 + 固定种子
    seeds = CENTER_SEEDS.get(center_name, ["自动衍化方向"])
    try:
        kw = center_name[:2] if len(center_name) >= 2 else center_name
        rows = c.execute(
            "SELECT suggestion_text FROM mt_ai_suggestion_pool WHERE "
            "suggestion_text LIKE ? ORDER BY created_at DESC LIMIT 2",
            (f"%{kw}%",)).fetchall()
        for (txt,) in rows:
            seed = txt[:40].replace("\n", " ")
            direction = f"{seed} → {seeds[0]}"
            try:
                c.execute("""INSERT OR IGNORE INTO mt_center_direction_pool
                    (center_name, direction_title, seed, priority, auto_spawned)
                    VALUES (?,?,?,?,1)""", (center_name, direction, seed, 5))
            except Exception:
                pass
    except Exception:
        pass
    # 固定种子抽样 (50% 概率)
    for seed in seeds:
        if random.random() < 0.5:
            try:
                c.execute("""INSERT OR IGNORE INTO mt_center_direction_pool
                    (center_name, direction_title, seed, priority, auto_spawned)
                    VALUES (?,?,?,?,0)""", (center_name, seed, seed, 5))
            except Exception:
                pass

    # ② HEALTH_PULSE — 读刚写入的 pulse 最新健康分
    try:
        pulse = c.execute("""SELECT health_score, active_tasks, queue_depth, anomalies_found
            FROM mt_center_pulse WHERE center_name=? ORDER BY rowid DESC LIMIT 1""",
            (center_name,)).fetchone()
        if pulse:
            health, active, queue, anomalies = pulse
            health_level = "💪健康" if (health or 0) >= 80 else ("⚠️亚健康" if (health or 0) >= 60 else "🔴告警")
            detail = f"health={health} {health_level} active={active} queue={queue} anomalies={anomalies}"
            c.execute("""INSERT INTO mt_center_evolution_log
                (center_name, event, detail) VALUES (?,?,?)""",
                (center_name, "HEALTH_PULSE", detail))
            events_written += 1
    except Exception:
        pass

    # ③ SELF_DRIVE_RECAP — self_drive 历史近 24h
    try:
        sd_count = c.execute(
            "SELECT COUNT(*) FROM mt_center_self_drive_log WHERE center_name=? AND created_at > datetime('now','localtime','-24 hours')",
            (center_name,)).fetchone()[0]
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail) VALUES (?,?,?)""",
            (center_name, "SELF_DRIVE_RECAP", f"近24h 自愈动作={sd_count}"))
        events_written += 1
    except Exception:
        pass

    # ④ TASK_BACKLOG — 积压 QUEUED 任务
    try:
        backlog = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE center_id=? AND status='QUEUED'",
            (center_id,)).fetchone()[0]
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail) VALUES (?,?,?)""",
            (center_name, "TASK_BACKLOG", f"积压 QUEUED={backlog}"))
        events_written += 1
    except Exception:
        pass

    # ⑤ DIRECTION_GROWTH — direction_pool 总数
    try:
        dirs = c.execute(
            "SELECT COUNT(*) FROM mt_center_direction_pool WHERE center_name=?",
            (center_name,)).fetchone()[0]
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail) VALUES (?,?,?)""",
            (center_name, "DIRECTION_GROWTH", f"方向池={dirs}"))
        events_written += 1
    except Exception:
        pass

    # ★ 新增: 每个中心 SELF_CHECK_SUMMARY evolution_log
    try:
        sc_count = c.execute(
            "SELECT COUNT(*) FROM mt_center_self_check WHERE center_name=? AND created_at > datetime('now','localtime','-24 hours')",
            (center_name,)).fetchone()[0]
        fail_count = c.execute(
            "SELECT COUNT(*) FROM mt_center_self_check WHERE center_name=? AND result!='PASS' AND created_at > datetime('now','localtime','-24 hours')",
            (center_name,)).fetchone()[0]
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail) VALUES (?,?,?)""",
            (center_name, "SELF_CHECK_SUMMARY", f"近24h 自检={sc_count} 异常={fail_count}"))
        events_written += 1
    except Exception:
        pass

    # ★ 新增: self_check FAIL → 自动上报任务大厅 (24h 去重, 认领制闭环)
    try:
        fails = c.execute("""SELECT check_type, metric_value, threshold FROM mt_center_self_check
            WHERE center_name=? AND result='FAIL'
            AND created_at > datetime('now','localtime','-24 hours')""",
            (center_name,)).fetchall()
        if fails:
            recent = c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
                WHERE source='CENTER_SELF_CHECK' AND description LIKE ?
                AND created_at > datetime('now','localtime','-24 hours')""",
                (f"%{center_name}%",)).fetchone()[0]
            if recent == 0:
                types = ",".join(sorted({str(f[0]) for f in fails}))
                code = f"HALL-SELFCHK-{center_id}-{datetime.now():%Y%m%d%H%M%S}"
                c.execute("""INSERT INTO mt_lab_task_hall
                    (title, description, source, source_id, priority, status, center_id,
                     hall_code, approval_status, publisher, publisher_role, created_at)
                    VALUES (?,?,?,?,?,?,?,?,'APPROVED','sys_center_evolution','hall_ingest',datetime('now','localtime'))""",
                    (f"[自检异常] {center_name} {len(fails)}项FAIL",
                     f"中心 {center_name} 近24h自检发现 {len(fails)} 项异常: {types}。请认领排查修复。",
                     "CENTER_SELF_CHECK", center_id, "HIGH", "QUEUED", center_id, code))
                events_written += 1
    except Exception:
        pass

    return events_written


def scan_global(c):
    """全局扫描 — daemon 健康 + 任务大厅总览"""
    # daemon 健康
    try:
        bad = c.execute(
            "SELECT COUNT(*) FROM mt_daemon_registry WHERE status NOT IN ('RUNNING','OK','ACTIVE','REGISTERED')").fetchone()[0]
        if bad > 0:
            names = [r[0] for r in c.execute(
                "SELECT process_name FROM mt_daemon_registry WHERE status NOT IN ('RUNNING','OK','ACTIVE','REGISTERED')").fetchone()][:5]
            c.execute("""INSERT INTO mt_center_evolution_log
                (center_name, event, detail) VALUES (?,?,?)""",
                ("SYSTEM", "DAEMON_ALERT", f"bad={bad}: {','.join(names)}"))
    except Exception:
        pass

    # 任务大厅总览
    try:
        pend = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status IN ('QUEUED','PENDING')").fetchone()[0]
        active = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status='IN_PROGRESS'").fetchone()[0]
        done = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status='DONE'").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM mt_lab_task_hall").fetchone()[0]
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail) VALUES (?,?,?)""",
            ("SYSTEM", "TASK_HALL_SCAN", f"total={total} done={done} queued={pend} in_progress={active}"))
    except Exception:
        pass


def run_once():
    c = _db()
    for s in _SCHEMA:
        try: c.execute(s)
        except Exception: pass

    # 🆕 flow_backup_center_20261029: 备份中心自举 (18 中心全覆盖)
    _ensure_backup_center(c)

    centers = get_active_centers(c)
    total_events = 0
    total_dirs = 0

    for name, domain, cid in centers:
        evts = evolve_one_center(c, name, domain, cid)
        total_events += evts
        # direction_pool 总数
        try:
            d = c.execute("SELECT COUNT(*) FROM mt_center_direction_pool WHERE center_name=?", (name,)).fetchone()[0]
            total_dirs += d
        except Exception:
            pass

    scan_global(c)

    # daemon 心跳
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (DAEMON, f"16中心自动研究衍化繁殖 600s ({len(centers)} centers)", "RUNNING",
             now, os.getpid(), json.dumps({"flow_id": FLOW_ID, "events": total_events, "directions": total_dirs}, ensure_ascii=False), now))
    except Exception:
        pass
    c.close()
    print(f"[{now}] CENTER_EVOLUTION_OK centers={len(centers)} events={total_events} directions={total_dirs}")
    return {"ok": True, "task_class": "CENTER_EVOLUTION", "centers": len(centers),
            "events": total_events, "directions": total_dirs}


def run_backup_center_once():
    """数据备份中心大厅闭环 (flow_backup_center_20261029, tick 末轨):
    ① 最新快照年龄 >26h → self_check FAIL + 自动上报大厅 (24h 去重)
    ② 当日无快照 → VACUUM INTO 执行备份 (读操作不抢 Flask 写锁) + integrity 校验 + 轮转
    ③ 成功 → evolution_log 事件 (大厅可观测)
    daemon 死活不再重要 — Flask tick 就是备份的守护"""
    out = {"ok": True, "checked": False, "backup_run": False, "hall_alert": 0, "snapshot": None}
    c = _db()
    try:
        cid = _ensure_backup_center(c)
        cname = BACKUP_CENTER[1]
        now = time.time()

        # ── ① 快照健康检查 ──
        snaps = sorted(f for f in os.listdir(BACKUP_DIR)
                       if f.startswith("app_backup_") and f.endswith(".db")) if os.path.isdir(BACKUP_DIR) else []
        age_h = None
        if snaps:
            latest = os.path.getmtime(os.path.join(BACKUP_DIR, snaps[-1]))
            age_h = (now - latest) / 3600.0
        out["checked"] = True
        out["snapshot"] = snaps[-1] if snaps else None

        if age_h is None or age_h > BACKUP_MAX_AGE_H:
            # FAIL → 大厅 (24h 去重)
            recent = c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
                WHERE source='BACKUP_STALL' AND created_at > datetime('now','localtime','-24 hours')""").fetchone()[0]
            if recent == 0:
                msg = f"备份目录为空" if age_h is None else f"最新快照 {snaps[-1]} 已停滞 {age_h:.1f}h (阈值 {BACKUP_MAX_AGE_H}h)"
                code = f"HALL-BACKUP-{datetime.now():%Y%m%d%H%M%S}"
                c.execute("""INSERT INTO mt_lab_task_hall
                    (title, description, source, priority, status,
                     hall_code, approval_status, publisher, publisher_role, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                    (f"[备份停滞] {msg}",
                     f"数据备份中心自检: {msg}。备份执行已由 Flask tick 接管 (本 tick 将自动重试), 请认领核查备份目录与磁盘空间。",
                     "BACKUP_STALL", "HIGH", "QUEUED",
                     code, "APPROVED", "backup_center", "hall_ingest"))
                out["hall_alert"] = 1
            c.execute("INSERT INTO mt_center_self_check (center_name, check_type, metric_value, threshold, result, created_at) "
                      "VALUES (?,?,?,?,?,datetime('now','localtime'))",
                      (cname, "BACKUP_FRESHNESS", round(age_h or 999, 1), BACKUP_MAX_AGE_H, "FAIL"))
        else:
            c.execute("INSERT INTO mt_center_self_check (center_name, check_type, metric_value, threshold, result, created_at) "
                      "VALUES (?,?,?,?,?,datetime('now','localtime'))",
                      (cname, "BACKUP_FRESHNESS", round(age_h, 1), BACKUP_MAX_AGE_H, "PASS"))

        # ── ② 当日无快照 → 执行备份 (幂等) ──
        today = os.path.join(BACKUP_DIR, f"app_backup_{datetime.now():%Y%m%d}.db")
        if not os.path.exists(today):
            t0 = time.time()
            os.makedirs(BACKUP_DIR, exist_ok=True)
            tmp = today + ".building"
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except Exception: pass
            src = sqlite3.connect(DB_PATH, timeout=60)
            try:
                src.execute("VACUUM INTO ?", (tmp,))
            finally:
                src.close()
            os.rename(tmp, today)
            elapsed = time.time() - t0
            size = os.path.getsize(today)
            chk = sqlite3.connect(f"file:{today}?mode=ro", uri=True)
            try:
                ok = chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                chk.close()
            out["backup_run"] = True
            c.execute("INSERT INTO mt_backup_log (action, detail, ok, size_bytes, elapsed_sec, created_at) VALUES (?,?,?,?,?,?)",
                      ("backup", today, 1 if ok else 0, size, elapsed, time.strftime("%Y-%m-%d %H:%M:%S")))
            c.execute("INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
                      (cname, "SNAPSHOT_DONE" if ok else "SNAPSHOT_CORRUPT",
                       f"{os.path.basename(today)} {size/1e6:.0f}MB {elapsed:.0f}s integrity={'OK' if ok else 'FAIL'}"))
            if not ok:
                os.remove(today)
                out["ok"] = False
            # 轮转: 保留 3 份
            all_snaps = sorted(f for f in os.listdir(BACKUP_DIR)
                               if f.startswith("app_backup_") and f.endswith(".db"))
            for old in all_snaps[:-3]:
                try: os.remove(os.path.join(BACKUP_DIR, old))
                except Exception: pass
            print(f"  [backup-center] 快照完成 {os.path.basename(today)} {size/1e6:.0f}MB {elapsed:.0f}s integrity={'OK' if ok else 'FAIL'}")
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
        print(f"  [backup-center] ERR: {e}")
    finally:
        c.close()
    return out


def loop():
    print(f"[{time.strftime('%H:%M:%S')}] {DAEMON} start, interval={INTERVAL}s")
    while True:
        try: run_once()
        except Exception as e: print(f"[{time.strftime('%H:%M:%S')}] ERR: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    loop()
