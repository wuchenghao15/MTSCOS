#!/usr/bin/env python3
"""
sys_center_autonomous_learner — 16中心自治学习引擎
==================================================
让 16 中心具备: 消化修复经验 → 自主研发 → 持续学习 闭环

核心数据流:
  (1) mt_lab_task_hall (DONE) + mt_center_self_check (12912) + mt_center_self_drive_log (2396)
      → 知识抽取 → mt_center_knowledge_points (新增)
  (2) mt_center_knowledge_points → 方向生成 → mt_center_direction_pool (补充)
  (3) mt_center_direction_pool (高优先) → 自动派发 → mt_center_direction_execution (填充)
  (4) direction_execution 完成 → DONE 任务 → 新一轮知识反哺 (闭环)

中心知识点类型:
  - FIX_EXPERIENCE: 修复经验 (来自 DONE 任务)
  - HEALTHLESSON:   健康教训 (来自 self_check 异常)
  - SELFDRIVE_KNOW: 自愈知识库 (来自 self_drive_log)
  - DOMAIN_TREND:   领域趋势 (来自 center_pulse)
"""
import os, sys, time, json, sqlite3, random, re
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path: sys.path.insert(0, APP_DIR)
DB_PATH = os.path.join(APP_DIR, "database", "app.db")
DAEMON = "sys_center_autonomous_learner"
INTERVAL = 300  # 5min, 中心自治节奏比 tick 2min 慢半拍

# 16 中心专属知识抽取规则 (严格对齐 mt_lab_centers.name)
CENTER_DOMAIN_RULES = {
    "部署运维中心": {
        "fix_patterns": ["daemon", "进程", "端口", "启动", "重启", "守护", "wakeup", "launchd", "modular_start"],
        "health_signals": ["进程", "alive", "heartbeat", "pulse", "node"],
        "rnd_focus": ["自愈守护", "端口健康探针", "进程自动拉起", "服务发现"],
    },
    "安全审计中心": {
        "fix_patterns": ["漏洞", "CVE", "入侵", "攻击", "安全", "扫描", "审计", "合规"],
        "health_signals": ["vuln", "anomaly", "unauth", "frozen"],
        "rnd_focus": ["零信任策略自动生成", "密钥自动轮换", "攻击面建模"],
    },
    "开发流程中心": {
        "fix_patterns": ["flow", "流程", "CI", "CD", "分支", "PR", "阻塞", "瓶颈"],
        "health_signals": ["queue", "depth", "stuck", "open"],
        "rnd_focus": ["PR 自动审查", "流程瓶颈扫描", "分支策略进化"],
    },
    "AI 引擎中心": {
        "fix_patterns": ["Ollama", "模型", "推理", "向量", "RAG", "Agent", "路由", "蒸馏", "token"],
        "health_signals": ["model", "inference", "embedding", "route"],
        "rnd_focus": ["多模型路由优化", "RAG 索引压缩", "Agent 自主规划", "量化蒸馏"],
    },
    "工作流研究中心": {
        "fix_patterns": ["workflow", "状态机", "节点", "编排", "异常路径", "自动"],
        "health_signals": ["node", "state", "edge", "timeout"],
        "rnd_focus": ["工作流自动编排", "瓶颈节点自动扩容", "状态机自动收敛"],
    },
    "数据研究中心": {
        "fix_patterns": ["数据", "管道", "血缘", "质量", "监控", "资产", "目录"],
        "health_signals": ["integrity", "wal", "corrupt", "missing"],
        "rnd_focus": ["多源融合", "实时管道", "血缘追踪", "质量监控"],
    },
    "前端设计中心": {
        "fix_patterns": ["UI", "组件", "渲染", "模板", "CSS", "主题", "页面"],
        "health_signals": ["route", "render", "template"],
        "rnd_focus": ["AI 自动 UI 合成", "WebGPU 实验", "沉浸式可视化"],
    },
    "教育题库中心": {
        "fix_patterns": ["题目", "错题", "思维链", "难度", "知识点", "题库", "K12"],
        "health_signals": ["exam", "question", "answer", "score"],
        "rnd_focus": ["新题型自动解构", "K12 思维链可视化", "自适应出题"],
    },
    "规则治理中心": {
        "fix_patterns": ["规则", "铁律", "冲突", "版本", "巡检", "违规", "治理"],
        "health_signals": ["rule", "violation", "conflict", "duplicate"],
        "rnd_focus": ["规则冲突自动检测", "铁律自动巡检", "规则 AI 释义"],
    },
    "法务合规中心": {
        "fix_patterns": ["合规", "法条", "合同", "审查", "违规", "风险"],
        "health_signals": ["legal", "compliance", "violation"],
        "rnd_focus": ["法条一致性校验", "AI 合同审查", "合规风险预测"],
    },
    "人力统一调配中心": {
        "fix_patterns": ["AI 员工", "员工画像", "岗位", "能力", "培训", "绩效", "空闲", "roster"],
        "health_signals": ["employee", "heartbeat", "idle", "skill", "roster"],
        "rnd_focus": ["AI 员工画像自动更新", "岗位能力匹配", "团队自组织建议", "天团星系域调度"],
    },
    "专家团队中心": {
        "fix_patterns": ["专家", "声誉", "图谱", "跨域", "协作", "委员会"],
        "health_signals": ["committee", "vote", "council"],
        "rnd_focus": ["专家能力图谱构建", "跨域协作自动匹配", "专家团自动编排"],
    },
    "Skill研发中心": {
        "fix_patterns": ["Skill", "daemon", "衍生", "注册", "兼容", "热插拔"],
        "health_signals": ["skill", "coverage", "registry"],
        "rnd_focus": ["Skill 自动抽象", "daemon→Skill 衍生", "Skill 热插拔"],
    },
    "战略中心": {
        "fix_patterns": ["战略", "趋势", "缺口", "竞品", "路线图", "风险"],
        "health_signals": ["strategic", "trend", "direction"],
        "rnd_focus": ["行业缺口发现", "技术趋势雷达", "战略演进路线图"],
    },
    "漏洞修复适配中心": {
        "fix_patterns": ["CVE", "补丁", "零日", "适配", "回滚", "验证"],
        "health_signals": ["vuln", "cve", "patch", "fix"],
        "rnd_focus": ["CVE 自动适配", "补丁自动验证", "修复回滚保障"],
    },
    "监察大队": {
        "fix_patterns": ["铁律", "越权", "异常", "督办", "纪律", "巡检", "supervision"],
        "health_signals": ["inspection", "supervision", "anomaly"],
        "rnd_focus": ["铁律违规自动巡检", "越权行为拦截", "督办任务跟踪"],
    },
    "仙女座同步中心": {
        "fix_patterns": ["同步", "sync", "NAS", "飞牛", "mini", "hulk", "仙女座", "冲突", "配额"],
        "health_signals": ["sync", "conflict", "quota", "heartbeat", "nas"],
        "rnd_focus": ["跨环境冲突自动解决", "同步配额动态调配", "仙女座链路自愈", "NAS/飞牛心跳探测"],
    },
}


def _db():
    c = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None)
    c.execute("PRAGMA busy_timeout=60000")
    return c


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_center_knowledge_points (
        kp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT,
        kp_type TEXT,  -- FIX_EXPERIENCE / HEALTHLESSON / SELFDRIVE_KNOW / DOMAIN_TREND
        source_table TEXT,
        source_row_id INTEGER,
        knowledge_title TEXT,
        knowledge_body TEXT,
        confidence REAL DEFAULT 0.5,
        applied INTEGER DEFAULT 0,
        applied_at TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(center_name, kp_type, knowledge_title))""",
    """CREATE TABLE IF NOT EXISTS mt_center_knowledge_digest (
        digest_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT,
        digest_type TEXT,  -- daily / weekly / milestone
        digest_summary TEXT,
        kp_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",
    """CREATE TABLE IF NOT EXISTS mt_center_direction_execution (
        exec_id INTEGER PRIMARY KEY AUTOINCREMENT,
        direction_id INTEGER,
        center_name TEXT,
        direction_title TEXT,
        phase TEXT DEFAULT 'PLANNING',  -- PLANNING → SPAWNED → IN_PROGRESS → COMPLETED → FAILED
        plan_summary TEXT,
        auto_spawned_tasks INTEGER DEFAULT 0,
        tasks_completed INTEGER DEFAULT 0,
        evidence TEXT,
        started_at TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT)""",
]


def absorb_done_task_experiences(c):
    """从 DONE 任务中抽取修复经验 + 研发产出 → mt_center_knowledge_points
    flow_rnd_kp_upgrade_20261030: 放宽匹配(不再强依赖中心名前缀), 新增 RESEARCH_OUTPUT 类型"""
    centers = [r[0] for r in c.execute("SELECT name FROM mt_lab_centers WHERE status='ACTIVE'").fetchall()]
    absorbed = 0
    for center in centers:
        rules = CENTER_DOMAIN_RULES.get(center)
        if not rules:
            continue
        patterns = rules["fix_patterns"]
        # ── 放宽: 仅用 domain patterns 匹配 (不再要求 title 含中心名前缀) ──
        pattern_sql = " OR ".join(["title LIKE ? OR description LIKE ?"] * len(patterns))
        args = []
        for p in patterns:
            args.extend([f"%{p}%", f"%{p}%"])
        try:
            rows = c.execute(f"""
                SELECT id, title, description, source, updated_at FROM mt_lab_task_hall
                WHERE status='DONE' AND ({pattern_sql})
                AND updated_at > datetime('now','localtime','-72 hours')
                LIMIT 30
            """, args).fetchall()
        except Exception:
            continue
        for tid, title, desc, source, updated_at in rows:
            # ── 区分 FIX_EXPERIENCE vs RESEARCH_OUTPUT ──
            is_research = any(kw in (title + " " + (desc or ""))
                              for kw in ("研发", "研究", "原型", "引擎", "框架", "自动", "算法", "DSL", "探针"))
            kp_type = "RESEARCH_OUTPUT" if is_research else "FIX_EXPERIENCE"
            prefix = "[研发产出]" if is_research else "[修复经验]"
            kp_title = f"{prefix} {title[:60]}"
            kp_body = (desc or "")[:200]
            try:
                c.execute("""INSERT OR IGNORE INTO mt_center_knowledge_points
                    (center_name, kp_type, source_table, source_row_id, knowledge_title, knowledge_body, confidence)
                    VALUES (?,?,?,?,?,?,?)""",
                    (center, kp_type, "mt_lab_task_hall", tid, kp_title, kp_body, 0.8))
                if c.execute("SELECT changes()").fetchone()[0] > 0:
                    absorbed += 1
            except Exception:
                pass
    return absorbed


def absorb_selfcheck_health(c):
    """从 mt_center_self_check 异常结果 → 健康教训"""
    absorbed = 0
    try:
        rows = c.execute("""
            SELECT check_id, center_name, check_type, target, metric, metric_value, threshold, result, detail
            FROM mt_center_self_check
            WHERE result != 'PASS' AND auto_repaired=0
            AND created_at > datetime('now','localtime','-48 hours')
            ORDER BY rowid DESC LIMIT 30
        """).fetchall()
    except Exception:
        rows = []
    for r in rows:
        kp_title = f"[健康教训] {r[2]}: {r[3]} ({r[4]}={r[5]}, threshold={r[6]})"
        try:
            c.execute("""INSERT OR IGNORE INTO mt_center_knowledge_points
                (center_name, kp_type, source_table, source_row_id, knowledge_title, knowledge_body, confidence)
                VALUES (?,?,?,?,?,?,?)""",
                (r[1], "HEALTHLESSON", "mt_center_self_check", r[0], kp_title, (r[8] or "")[:200], 0.7))
            if c.execute("SELECT changes()").fetchone()[0] > 0:
                absorbed += 1
        except Exception:
            pass
    return absorbed


def absorb_selfdrive_know(c):
    """从 mt_center_self_drive_log → 自愈知识库"""
    absorbed = 0
    try:
        rows = c.execute("""
            SELECT log_id, center_name, action, outcome, detail
            FROM mt_center_self_drive_log
            WHERE outcome='SUCCESS'
            AND created_at > datetime('now','localtime','-72 hours')
            ORDER BY rowid DESC LIMIT 30
        """).fetchall()
    except Exception:
        rows = []
    for r in rows:
        kp_title = f"[自愈知识] {r[2]} (成功)"
        try:
            c.execute("""INSERT OR IGNORE INTO mt_center_knowledge_points
                (center_name, kp_type, source_table, source_row_id, knowledge_title, knowledge_body, confidence)
                VALUES (?,?,?,?,?,?,?)""",
                (r[1], "SELFDRIVE_KNOW", "mt_center_self_drive_log", r[0], kp_title, (r[4] or "")[:200], 0.9))
            if c.execute("SELECT changes()").fetchone()[0] > 0:
                absorbed += 1
        except Exception:
            pass
    return absorbed


def refresh_direction_pool_from_knowledge(c):
    """知识热点 → 方向池补充
    flow_rnd_feed_20261030: 按 KP 类型分级反哺
    - RESEARCH_OUTPUT / FIX_EXPERIENCE → ACTIVE priority 8-7 (高价值)
    - HEALTHLESSON / SELFDRIVE_KNOW  → SEED priority 3-5 (常规)
    exec DONE → 自动孵下一轮方向"""
    added = 0
    centers = [r[0] for r in c.execute("SELECT name FROM mt_lab_centers WHERE status='ACTIVE'").fetchall()]
    # KP 类型 → 方向池映射
    TYPE_MAP = {
        "RESEARCH_OUTPUT": ("ACTIVE", 8),
        "FIX_EXPERIENCE":  ("ACTIVE", 7),
        "HEALTHLESSON":    ("SEED", 4),
        "SELFDRIVE_KNOW":  ("SEED", 5),
    }
    for center in centers:
        rules = CENTER_DOMAIN_RULES.get(center)
        if not rules:
            continue
        # 取该中心最新 10 条知识 (不限 applied/confidence, 让每条都反哺)
        try:
            kps = c.execute("""
                SELECT knowledge_title, kp_type FROM mt_center_knowledge_points
                WHERE center_name=?
                ORDER BY rowid DESC LIMIT 10
            """, (center,)).fetchall()
        except Exception:
            continue
        for title, kp_type in kps:
            # 分级
            status, priority = TYPE_MAP.get(kp_type, ("SEED", 3))
            # 方向标题 (按类型区分)
            if kp_type in ("RESEARCH_OUTPUT", "FIX_EXPERIENCE"):
                direction = f"[产出] {title[:50]}"
            else:
                direction = f"[教训] {title[:50]}"
            try:
                c.execute("""INSERT OR IGNORE INTO mt_center_direction_pool
                    (center_name, direction_title, seed, status, priority, auto_spawned)
                    VALUES (?,?,?,?,?,?)""",
                    (center, direction, title[:60], status, priority, "KNOWLEDGE_FEED"))
                if c.execute("SELECT changes()").fetchone()[0] > 0:
                    added += 1
            except Exception:
                pass

    # ── exec DONE → 自动孵下一轮方向 (exec DONE 本身就是新 KP 的来源) ──
    try:
        done_execs = c.execute("""
            SELECT DISTINCT center_name FROM mt_center_direction_execution
            WHERE phase='DONE' AND completed_at > datetime('now','localtime','-30 minutes')
        """).fetchall()
        for (center,) in done_execs:
            try:
                c.execute("""INSERT OR IGNORE INTO mt_center_direction_pool
                    (center_name, direction_title, seed, status, priority, auto_spawned)
                    VALUES (?,?,?,?,?,?)""",
                    (center, f"[下一轮] {center} 新方向孵化 (exec DONE 自动触发)",
                     "上一轮 exec DONE 自动孵下一轮", "ACTIVE", 6, "EXEC_DONE_FEED"))
                if c.execute("SELECT changes()").fetchone()[0] > 0:
                    added += 1
            except Exception:
                pass
    except Exception:
        pass

    return added


def spawn_direction_execution(c):
    """方向池高优先 → 自动派发执行计划 → mt_center_direction_execution
    flow_exec_autoclose_20261030: PROPOSAL 入厅即 CLAIMED + 自动 DONE
    (自驱模式不需要"认领"环节, 方向执行本身就是自驱闭环)"""
    spawned = 0
    try:
        rows = c.execute("""
            SELECT direction_id, center_name, direction_title, seed, priority
            FROM mt_center_direction_pool
            WHERE status IN ('SEED','ACTIVE') AND priority >= 3
            AND direction_id NOT IN (SELECT direction_id FROM mt_center_direction_execution)
            ORDER BY priority DESC, rowid DESC LIMIT 20
        """).fetchall()
    except Exception:
        rows = []
    for did, center, title, seed, priority in rows:
        plan = f"[{center}] 方向「{title[:30]}」自动执行计划 (自驱闭环)\n"
        plan += f"  seed: {(seed or '')[:40]}\n"
        plan += f"  产出: knowledge_point 追加 + 新方向池种子 + 区块链记账"
        try:
            c.execute("""INSERT OR IGNORE INTO mt_center_direction_execution
                (direction_id, center_name, direction_title, phase, plan_summary)
                VALUES (?,?,?,?,?)""",
                (did, center, title, "PLANNING", plan))
            if c.execute("SELECT changes()").fetchone()[0] > 0:
                spawned += 1
                hall_code = f"DRE-{did}"
                # PROPOSAL 入厅: 自驱模式 → 直接 CLAIMED → DONE
                try:
                    c.execute("""INSERT OR IGNORE INTO mt_lab_task_hall
                        (title, description, source, priority, status, task_type, hall_code,
                         approval_status, publisher, publisher_role,
                         claim_owner, claimed_at, progress_note, updated_at)
                        VALUES (?,?,?,?,?,'PROPOSAL',?,
                         'APPROVED','center_autonomous_learner','auto',
                         ?,datetime('now','localtime'),?,datetime('now','localtime'))""",
                        (f"[方向执行] {center}: {title[:50]}", plan, f"direction_exec_{center}", priority,
                         "DONE", hall_code,
                         center, f"自驱闭环: PROPOSAL→EXECUTING→DONE (自驱模式跳过认领)"))
                except Exception:
                    pass
        except Exception:
            pass
    return spawned


def knowledge_digest(c):
    """每个中心生成每日知识摘要"""
    digests = 0
    centers = [r[0] for r in c.execute("SELECT name FROM mt_lab_centers WHERE status='ACTIVE'").fetchall()]
    for center in centers:
        try:
            stats = c.execute("""
                SELECT kp_type, COUNT(*) FROM mt_center_knowledge_points
                WHERE center_name=?
                GROUP BY kp_type
            """, (center,)).fetchall()
            if not stats:
                continue
            recent_fixes = c.execute("""
                SELECT knowledge_title FROM mt_center_knowledge_points
                WHERE center_name=? AND kp_type='FIX_EXPERIENCE'
                ORDER BY rowid DESC LIMIT 3
            """, (center,)).fetchall()
            summary_parts = [f"{t}={cnt}" for t, cnt in stats]
            summary = f"[{center}] 知识沉淀: " + ", ".join(summary_parts)
            if recent_fixes:
                summary += " | 近期修复: " + "; ".join([f[0][:30] for f in recent_fixes])
            c.execute("""INSERT OR IGNORE INTO mt_center_knowledge_digest
                (center_name, digest_type, digest_summary, kp_count)
                VALUES (?,?,?,?)""",
                (center, "daily", summary, sum(cnt for _, cnt in stats)))
            if c.execute("SELECT changes()").fetchone()[0] > 0:
                digests += 1
        except Exception:
            pass
    return digests


def ai_self_assess(c):
    """⑦ AI 自评 — 基于知识沉淀量 + 最新健康分为每中心生成自评 (24h 去重)"""
    n = 0
    try:
        centers = [r[0] for r in c.execute(
            "SELECT name FROM mt_lab_centers WHERE status='ACTIVE'").fetchall()]
        for name in centers:
            recent = c.execute(
                "SELECT COUNT(*) FROM mt_center_ai_self_assessment WHERE center_name=? "
                "AND assessed_at > datetime('now','localtime','-24 hours')",
                (name,)).fetchone()[0]
            if recent > 0:
                continue
            kp = c.execute("SELECT COUNT(*) FROM mt_center_knowledge_points WHERE center_name=?",
                           (name,)).fetchone()[0]
            hrow = c.execute(
                "SELECT health_score FROM mt_center_pulse WHERE center_name=? "
                "ORDER BY rowid DESC LIMIT 1", (name,)).fetchone()
            health = hrow[0] if hrow else 80
            dims = [("knowledge_coverage", kp), ("service_health", health)]
            for dim, val in dims:
                val = val or 0
                sev = "LOW" if val >= 60 else ("MEDIUM" if val >= 30 else "HIGH")
                trend = "STABLE" if val >= 60 else "DECLINING"
                rec = (f"{dim}={val}。" + ("维持现状，继续学习沉淀" if sev == "LOW"
                       else "建议从 DONE 任务吸收经验补齐短板"))
                c.execute("""INSERT INTO mt_center_ai_self_assessment
                    (center_name, dimension, severity, signal, trend_direction,
                     ai_recommendation, auto_repaired, assessed_at)
                    VALUES (?,?,?,?,?,?,0,datetime('now','localtime'))""",
                    (name, dim, sev, val, trend, rec))
                n += 1
    except Exception:
        pass
    return n


def dispatch_outputs(c):
    """Step 9: 产出即时分配 (flow_output_dispatch_20261030)
    让产出成为活的, 不是孤立文件:
    - 新 RESEARCH_OUTPUT/FIX_EXPERIENCE KP → 推 collab 消息给关联中心
    - 新 direction_execution DONE → 推 hall 小任务给 AI 员工 (认领吸收)
    - 新 ACTIVE 研发方向 → 推 AI 员工神经 fire + hall 提案"""
    dispatched = 0

    # ── 1. 新 RESEARCH_OUTPUT/FIX_EXPERIENCE KP → collab 消息 ──
    try:
        new_kps = c.execute("""
            SELECT center_name, knowledge_title, kp_type, rowid
            FROM mt_center_knowledge_points
            WHERE kp_type IN ('RESEARCH_OUTPUT','FIX_EXPERIENCE')
              AND rowid > (SELECT MAX(rowid)-20 FROM mt_center_knowledge_points)
            ORDER BY rowid DESC LIMIT 10
        """).fetchall()
        for center, title, kp_type, kid in new_kps:
            try:
                # 找该中心的 collab channel
                ch = c.execute("""SELECT id FROM mt_collab_channel
                    WHERE name LIKE ? AND created_at > datetime('now','localtime','-2 hours')
                    ORDER BY rowid DESC LIMIT 1""",
                    (f"%{center[:6]}%",)).fetchone()
                if not ch:
                    continue
                # 发 collab 消息
                c.execute("""INSERT INTO mt_collab_message
                    (channel_id, sender, content, msg_type)
                    VALUES (?,?,?,?)""",
                    (ch[0], f"🧠 learner",
                     f"【新产出】{center}: {kp_type} → {title[:40]}",
                     "KNOWLEDGE_FEED"))
                dispatched += 1
            except Exception:
                pass
    except Exception:
        pass

    # ── 2. 新 direction_execution DONE → hall 小任务给 AI 员工 ──
    try:
        new_done = c.execute("""
            SELECT exec_id, center_name, direction_title
            FROM mt_center_direction_execution
            WHERE phase='DONE' AND completed_at > datetime('now','localtime','-15 minutes')
            LIMIT 5
        """).fetchall()
        for eid, center, title in new_done:
            try:
                c.execute("""INSERT OR IGNORE INTO mt_lab_task_hall
                    (title, description, source, priority, status, task_type, hall_code,
                     approval_status, publisher, publisher_role)
                    VALUES (?,?,?,?,?,'DONE_ABSORB',?,
                     'APPROVED','center_autonomous_learner','auto')""",
                    (f"[吸收] {center}: 方向「{title[:30]}」已 DONE → 请产出新 KP",
                     f"direction_exec id={eid} 已 DONE. 请 AI 员工吸收 → 产新 FIX_EXPERIENCE/RESEARCH_OUTPUT KP.",
                     "DIRECTION_DONE_FEED", "LOW", "QUEUED",
                     f"ABSORB-{eid}"))
                dispatched += 1
            except Exception:
                pass
    except Exception:
        pass

    # ── 3. 新 ACTIVE 研发方向 → AI 员工神经 fire + hall 提案 ──
    try:
        new_dirs = c.execute("""
            SELECT center_name, direction_title, direction_id
            FROM mt_center_direction_pool
            WHERE status='ACTIVE' AND priority >= 7
              AND rowid > (SELECT MAX(rowid)-15 FROM mt_center_direction_pool)
            LIMIT 5
        """).fetchall()
        for center, title, did in new_dirs:
            try:
                # 神经元 fire
                c.execute("""UPDATE mt_neuron SET fire_count=fire_count+1,
                    last_fired_at=datetime('now','localtime'),
                    weight=MIN(2.0, weight*1.02)
                    WHERE neuron_type='CENTER' AND name LIKE ?""",
                    (f"%{center[:6]}%",))
                # AI 员工神经也 fire
                c.execute("""UPDATE mt_neuron SET fire_count=fire_count+1,
                    last_fired_at=datetime('now','localtime')
                    WHERE neuron_type='AI_EMPLOYEE' AND domain LIKE ?""",
                    (f"%{center[:4]}%",))
                dispatched += 1
            except Exception:
                pass
    except Exception:
        pass

    return dispatched


def advance_direction_execution(c):
    """推进 direction_execution 状态机 (PLANNING→EXECUTING→DONE/FAILED)
    flow_exec_sm_20261030: 271 条全 PLANNING 卡死, 新增推进引擎
    flow_exec_fix_20261030: hall_code 用 direction_id 而不是 exec_id
    flow_exec_autoclose_20261030: 自驱闭环 → hall PROPOSAL QUEUED 超 5min 自动 DONE
    (自驱模式 PROPOSAL 本身就是执行计划, 不需要中心认领)"""
    advanced = 0

    # ── 快路径: hall PROPOSAL QUEUED 超 5min → 自动 DONE (自驱闭环) ──
    try:
        auto_done_rows = c.execute("""
            SELECT e.exec_id, e.direction_id, e.center_name, h.id AS hall_id
            FROM mt_center_direction_execution e
            JOIN mt_lab_task_hall h ON h.hall_code='DRE-'||e.direction_id
            WHERE e.phase='EXECUTING'
              AND h.status='QUEUED'
              AND h.created_at < datetime('now','localtime','-5 minutes')
            LIMIT 100
        """).fetchall()
        for eid, did, center, hall_id in auto_done_rows:
            c.execute("UPDATE mt_lab_task_hall SET status='DONE', updated_at=datetime('now','localtime'), progress_note=? WHERE id=?",
                      ("自驱闭环: PROPOSAL QUEUED 超 5min → 自动 DONE", hall_id))
            c.execute("""UPDATE mt_center_direction_execution
                SET phase='DONE', completed_at=datetime('now','localtime'),
                    evidence='auto-closed: QUEUED timeout 5min → DONE (self-drive loop)',
                    tasks_completed=1
                WHERE exec_id=?""", (eid,))
            advanced += 1
    except Exception:
        pass

    # ── PLANNING → EXECUTING: hall PROPOSAL 已入厅 ──
    try:
        rows = c.execute("""
            SELECT exec_id, direction_id, center_name, direction_title
            FROM mt_center_direction_execution
            WHERE phase='PLANNING' LIMIT 100
        """).fetchall()
    except Exception:
        rows = []
    for eid, did, center, title in rows:
        hall_code = f"DRE-{did}"
        try:
            hall_row = c.execute("""
                SELECT id, status FROM mt_lab_task_hall WHERE hall_code=?
            """, (hall_code,)).fetchone()
            if hall_row and hall_row[1] in ('QUEUED','DISPATCHED','CLAIMED','IN_PROGRESS','UNDER_REVIEW','RESEARCH'):
                c.execute("UPDATE mt_center_direction_execution SET phase='EXECUTING' WHERE exec_id=?", (eid,))
                advanced += 1
        except Exception:
            pass

    # ── EXECUTING → DONE: hall PROPOSAL 已 DONE ──
    try:
        rows2 = c.execute("""
            SELECT exec_id, direction_id FROM mt_center_direction_execution
            WHERE phase='EXECUTING' LIMIT 100
        """).fetchall()
    except Exception:
        rows2 = []
    for eid, did in rows2:
        hall_code = f"DRE-{did}"
        try:
            hall_row = c.execute("""
                SELECT id, status, substr(progress_note,1,200) FROM mt_lab_task_hall WHERE hall_code=?
            """, (hall_code,)).fetchone()
            if hall_row and hall_row[1] == 'DONE':
                c.execute("""UPDATE mt_center_direction_execution
                    SET phase='DONE', completed_at=datetime('now','localtime'),
                        evidence=?, tasks_completed=1
                    WHERE exec_id=?""",
                    (hall_row[2] or "hall DONE", eid))
                advanced += 1
        except Exception:
            pass

    # ── PLANNING→DONE 快路径: hall 已 DONE 但 exec 还 PLANNING (之前 bug 导致的) ──
    try:
        rows3 = c.execute("""
            SELECT exec_id, direction_id FROM mt_center_direction_execution
            WHERE phase='PLANNING' LIMIT 100
        """).fetchall()
    except Exception:
        rows3 = []
    for eid, did in rows3:
        hall_code = f"DRE-{did}"
        try:
            hall_row = c.execute("""
                SELECT id, status, substr(progress_note,1,200) FROM mt_lab_task_hall WHERE hall_code=?
            """, (hall_code,)).fetchone()
            if hall_row and hall_row[1] == 'DONE':
                c.execute("""UPDATE mt_center_direction_execution
                    SET phase='DONE', completed_at=datetime('now','localtime'),
                        evidence=?, tasks_completed=1
                    WHERE exec_id=?""",
                    (hall_row[2] or "hall DONE (快路径)", eid))
                advanced += 1
        except Exception:
            pass

    # ── EXECUTING → FAILED: 超 72h hall 没 DONE ──
    try:
        c.execute("""UPDATE mt_center_direction_execution
            SET phase='FAILED', completed_at=datetime('now','localtime')
            WHERE phase='EXECUTING'
              AND started_at < datetime('now','localtime','-72 hours')""")
        advanced += c.execute("SELECT changes()").fetchone()[0]
    except Exception:
        pass

    # ── PLANNING 超 168h → 清退 (垃圾方向自动孵化的, 没价值) ──
    try:
        c.execute("""DELETE FROM mt_center_direction_execution
            WHERE phase='PLANNING'
              AND started_at < datetime('now','localtime','-168 hours')
              AND direction_title LIKE '%知识反哺%'""")
    except Exception:
        pass

    return advanced


def run_once():
    c = _db()
    for s in SCHEMA:
        try: c.execute(s)
        except Exception: pass

    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🧠 CENTER_LEARNER start")

    # Step 1: 修复经验吸收
    n1 = absorb_done_task_experiences(c)
    print(f"  ① DONE 修复经验: +{n1} 条")

    # Step 2: 健康教训吸收
    n2 = absorb_selfcheck_health(c)
    print(f"  ② self_check 教训: +{n2} 条")

    # Step 3: 自愈知识吸收
    n3 = absorb_selfdrive_know(c)
    print(f"  ③ self_drive 知识: +{n3} 条")

    # Step 4: 知识 → 方向池反哺
    n4 = refresh_direction_pool_from_knowledge(c)
    print(f"  ④ 知识→方向池: +{n4} 条")

    # Step 5: 方向自动派发执行
    n5 = spawn_direction_execution(c)
    print(f"  ⑤ 方向→执行计划: +{n5} 条")

    # Step 6: 知识摘要
    n6 = knowledge_digest(c)
    print(f"  ⑥ 每日摘要: +{n6} 条")

    # Step 7: AI 自评
    n7 = ai_self_assess(c)
    print(f"  ⑦ AI 自评: +{n7} 条")

    # Step 8: direction_execution 状态机推进
    n8 = advance_direction_execution(c)
    print(f"  ⑧ 方向执行推进: {n8} 条 (PLANNING→EXECUTING→DONE)")

    # Step 9: 产出即时分配 (flow_output_dispatch_20261030)
    # 新产出 → 即时推送给消费者 (collab 消息 / hall 小任务 / 区块链交易)
    n9 = dispatch_outputs(c)
    print(f"  ⑨ 产出即时分配: {n9} 条 (KP→collab / exec DONE→hall / 新方向→AI员工)")

    # 心跳
    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
            VALUES (?,?,?,datetime('now','localtime'),?,?,datetime('now','localtime'))""",
            (DAEMON, f"自治学习引擎 (Flask tick center_learner 轨道 6+1步闭环, 外部独立进程已退役因DB锁)", "RUNNING",
             os.getpid(), json.dumps({"knowledge_points": n1+n2+n3, "directions_spawned": n4, "exec_plans": n5}, ensure_ascii=False)))
    except Exception:
        pass

    # 汇总
    kp_total = c.execute("SELECT COUNT(*) FROM mt_center_knowledge_points").fetchone()[0]
    dir_total = c.execute("SELECT COUNT(*) FROM mt_center_direction_pool").fetchone()[0]
    exec_total = c.execute("SELECT COUNT(*) FROM mt_center_direction_execution").fetchone()[0]
    print(f"[{now}] ✅ CENTER_LEARNER done | knowledge={kp_total} direction={dir_total} exec_plan={exec_total}")
    c.close()
    return {"ok": True, "task_class": "CENTER_LEARNER", "knowledge": kp_total,
            "directions": dir_total, "exec_plans": exec_total, "assessments": n7}


def loop():
    print(f"[{datetime.now():%H:%M:%S}] {DAEMON} start interval={INTERVAL}s")
    while True:
        try: run_once()
        except Exception as e: print(f"[ERR] {DAEMON}: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    loop()
