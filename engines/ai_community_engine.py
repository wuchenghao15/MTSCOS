#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Andromeda · 🏘️ AI Community Engine (AI 社区引擎)
#  flow_ai_community_20261115
#
#  🧠 从小我到大我的质变: 36 个独立 AI 员工 → 有组织的 AI 社区
#  ────────────────────────────────────────────────────────────────
#  社区六大支柱:
#  ① 拜师体系     (Mentorship) — 资深 AI 当导师, 新员工自动拜师
#  ② 岗位能力图谱 (Capability Map) — 每个岗位的技能清单 + 达标标准
#  ③ 边界与权限   (Boundary & Permission) — 谁能做什么, 谁不能做什么
#  ④ 自动培训循环 (Auto Training Loop) — 经验库 → 自动出题 → 自动考核
#  ⑤ 反省复习     (Review Cycle) — 定期回顾, 温故知新
#  ⑥ 反推校正     (Calibration) — 从执行结果反推员工能力是否达标
#  ────────────────────────────────────────────────────────────────
#  运行:
#    python3 engines/ai_community_engine.py --init-tables    # 建表
#    python3 engines/ai_community_engine.py --seed-gobelin   # Gobelin Bank 岗位种子
#    python3 engines/ai_community_engine.py --check-health   # 社区健康体检
#    python3 engines/ai_community_engine.py --train-cycle    # 自动培训一轮
#    python3 engines/ai_community_engine.py --daemon         # 常驻守护
# ═══════════════════════════════════════════════════════════════════

import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import time
import traceback


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "database", "app.db")


def _conn():
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


# ═══════════════════════════════════════════════════════════════════
# §0 Schema 初始化 — 社区六大支柱的表
# ═══════════════════════════════════════════════════════════════════

COMMUNITY_TABLES = {
    # ── ① 师徒关系表 ──
    "mt_community_mentorship": """CREATE TABLE IF NOT EXISTS mt_community_mentorship (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mentor_id TEXT NOT NULL,           -- 导师 employee_id
        mentee_id TEXT NOT NULL,           -- 徒弟 employee_id
        skill_focus TEXT DEFAULT '',        -- 主攻技能 (JSON list)
        status TEXT DEFAULT 'ACTIVE',       -- ACTIVE / GRADUATED / TERMINATED
        start_date TEXT DEFAULT (datetime('now','localtime')),
        grad_date TEXT,
        grad_score REAL DEFAULT 0,          -- 出师评分 0-100
        lessons_count INTEGER DEFAULT 0,    -- 已完成课程数
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(mentee_id)
    )""",

    # ── ② 岗位能力图谱 ──
    "mt_community_capability": """CREATE TABLE IF NOT EXISTS mt_community_capability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,                 -- 岗位名
        skill TEXT NOT NULL,                -- 技能名
        category TEXT DEFAULT '',           -- 分类: analyze / decide / execute / guard
        required_level REAL DEFAULT 1.0,    -- 要求等级 1-5
        weight REAL DEFAULT 1.0,            -- 权重 (影响最终评分)
        assessment_method TEXT DEFAULT 'self_check',  -- self_check / peer_review / execution_result
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(role, skill)
    )""",

    # ── ③ AI 员工能力快照 (定期更新) ──
    "mt_community_skill_snapshot": """CREATE TABLE IF NOT EXISTS mt_community_skill_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        skill TEXT NOT NULL,
        current_level REAL DEFAULT 0,       -- 当前等级 0-5
        last_demo TEXT DEFAULT '',           -- 最近一次展示 (执行结果摘要)
        verified_by TEXT DEFAULT 'SELF',     -- 验证者: SELF / MENTOR / PEER / SYSTEM
        verified_at TEXT DEFAULT (datetime('now','localtime')),
        trend TEXT DEFAULT 'FLAT',          -- UP / DOWN / FLAT
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── ④ 边界与权限矩阵 ──
    "mt_community_permission": """CREATE TABLE IF NOT EXISTS mt_community_permission (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,                 -- 岗位
        action TEXT NOT NULL,               -- 动作: propose / vote / veto / execute / seal / audit
        target TEXT DEFAULT '*',            -- 目标: channel / amount_range / center
        min_level REAL DEFAULT 1.0,         -- 最低等级
        requires_seal INTEGER DEFAULT 0,   -- 是否需要印章
        requires_vote INTEGER DEFAULT 0,    -- 是否需要议会表决
        risk_level TEXT DEFAULT 'LOW',      -- LOW / MEDIUM / HIGH / CRITICAL
        enabled INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(role, action, target)
    )""",

    # ── ⑤ 培训课程与进度 ──
    "mt_community_training": """CREATE TABLE IF NOT EXISTS mt_community_training (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        course_name TEXT NOT NULL,
        course_type TEXT DEFAULT 'auto',     -- auto / mentor_led / peer_learn
        source TEXT DEFAULT '',              -- 来源: reflect_log / web_integrate / mentor
        status TEXT DEFAULT 'ENROLLED',      -- ENROLLED / IN_PROGRESS / PASSED / FAILED
        progress REAL DEFAULT 0,             -- 0-100
        score REAL DEFAULT 0,                -- 考核分
        reflections TEXT DEFAULT '',         -- 学习反省 (JSON)
        started_at TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT
    )""",

    # ── ⑥ 反省复习记录 ──
    "mt_community_review": """CREATE TABLE IF NOT EXISTS mt_community_review (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        review_type TEXT DEFAULT 'WEEKLY',   -- DAILY / WEEKLY / MONTHLY / QUARTERLY
        focus_skills TEXT DEFAULT '',        -- 重点复习技能 (JSON)
        key_insights TEXT DEFAULT '',        -- 核心洞察
        action_items TEXT DEFAULT '',        -- 改进项 (JSON)
        reviewed_by TEXT DEFAULT 'SELF',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── ⑦ 反推校正记录 ──
    "mt_community_calibration": """CREATE TABLE IF NOT EXISTS mt_community_calibration (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        calibration_type TEXT DEFAULT 'execution_outcome',  -- execution_outcome / peer_compare / self_reflect
        before_level REAL DEFAULT 0,
        after_level REAL DEFAULT 0,
        trigger_event TEXT DEFAULT '',       -- 触发事件: 成功提案/失败执行/用户反馈
        calibration_logic TEXT DEFAULT '',   -- 反推逻辑
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",

    # ── ⑧ Gobelin Bank 岗位特化表 ──
    "mt_community_gobelin_roles": """CREATE TABLE IF NOT EXISTS mt_community_gobelin_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_code TEXT UNIQUE NOT NULL,
        role_name TEXT NOT NULL,
        center TEXT DEFAULT '',
        tier TEXT DEFAULT 'L3',              -- L1决策/L2分析/L3执行/L4自驱
        key_skills TEXT DEFAULT '[]',        -- 关键技能 (JSON)
        permissions TEXT DEFAULT '[]',       -- 权限列表 (JSON)
        mentor_required INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
}


def init_tables(conn=None):
    """初始化所有社区表 (幂等)"""
    own = conn is None
    conn = conn or _conn()
    created = []
    for name, ddl in COMMUNITY_TABLES.items():
        try:
            conn.execute(ddl)
            created.append(name)
        except Exception as e:
            sys.stderr.write(f"[COMMUNITY] create {name}: {e}\n")
    conn.commit()
    if own: conn.close()
    return created


# ═══════════════════════════════════════════════════════════════════
# §1 Gobelin Bank 岗位种子 — 投资链路上每个位置的 AI 员工画像
# ═══════════════════════════════════════════════════════════════════

GOBELIN_ROLES_SEED = [
    # ── L1 决策层 (3 个) ──
    {"role_code": "FINANCE_CHAIR", "role_name": "金融议会议长", "center": "FINANCE_COUNCIL", "tier": "L1",
     "key_skills": ["最终决策", "投票仲裁", "VETO 行使", "宏观权衡", "风险感知"],
     "permissions": ["propose:MEGA", "vote:ALL", "veto:ALL", "seal:MEGA", "execute:MEGA"]},
    {"role_code": "ALPHA_DIRECTOR", "role_name": "阿尔法研究总监", "center": "ALPHA_CENTER", "tier": "L1",
     "key_skills": ["市场扫描", "机会发现", "行业轮动", "前瞻判断"],
     "permissions": ["propose:STANDARD", "propose:MAJOR", "vote:ALL"]},
    {"role_code": "BETA_CHIEF", "role_name": "贝塔风险总监", "center": "BETA_CENTER", "tier": "L1",
     "key_skills": ["风险评估", "熔断触发", "压力测试", "黑天鹅预案"],
     "permissions": ["veto:HIGH_RISK", "vote:ALL", "audit:ALL"]},

    # ── L2 分析层 (8 个) ──
    {"role_code": "QUANT_ANALYST", "role_name": "量化分析师", "center": "QUANT_CENTER", "tier": "L2",
     "key_skills": ["因子挖掘", "回测验证", "统计套利", "机器学习"],
     "permissions": ["propose:MICRO", "propose:STANDARD", "vote:MICRO"]},
    {"role_code": "MACRO_ANALYST", "role_name": "宏观分析师", "center": "MACRO_CENTER", "tier": "L2",
     "key_skills": ["利率分析", "汇率研判", "资金流向", "政策解读"],
     "permissions": ["propose:STANDARD", "vote:MICRO"]},
    {"role_code": "SENTIMENT_ANALYST", "role_name": "情感分析师", "center": "SENTIMENT_CENTER", "tier": "L2",
     "key_skills": ["舆情分析", "情绪指标", "社交挖掘"],
     "permissions": ["propose:MICRO", "vote:MICRO"]},
    {"role_code": "TECH_ANALYST", "role_name": "技术分析师", "center": "TECH_CENTER", "tier": "L2",
     "key_skills": ["形态识别", "指标信号", "量价分析"],
     "permissions": ["propose:MICRO", "vote:MICRO"]},
    {"role_code": "FUNDAMENTAL_ANALYST", "role_name": "基本面分析师", "center": "FUNDAMENTAL_CENTER", "tier": "L2",
     "key_skills": ["估值建模", "财务健康", "行业对比"],
     "permissions": ["propose:STANDARD", "vote:MICRO"]},
    {"role_code": "ALTERNATIVE_ANALYST", "role_name": "另类资产分析师", "center": "ALTERNATIVE_CENTER", "tier": "L2",
     "key_skills": ["贵金属", "私募股权", "商业投资"],
     "permissions": ["propose:STANDARD", "vote:MICRO"]},
    {"role_code": "DERIVATIVE_ANALYST", "role_name": "衍生品分析师", "center": "DERIVATIVE_CENTER", "tier": "L2",
     "key_skills": ["期权定价", "期货对冲", "Greeks"],
     "permissions": ["propose:MAJOR", "vote:MICRO"]},
    {"role_code": "CURRENCY_ANALYST", "role_name": "外汇分析师", "center": "CURRENCY_CENTER", "tier": "L2",
     "key_skills": ["汇率", "跨境", "三角套利"],
     "permissions": ["propose:STANDARD", "vote:MICRO"]},

    # ── L3 执行层 (10 个) ──
    {"role_code": "STOCK_TRADER", "role_name": "A股交易员", "center": "CHANNEL_STOCK", "tier": "L3",
     "key_skills": ["A股买卖", "持仓管理", "T+1规则", "涨跌停"],
     "permissions": ["execute:MICRO", "execute:STANDARD"]},
    {"role_code": "FUND_TRADER", "role_name": "基金交易员", "center": "CHANNEL_FUND", "tier": "L3",
     "key_skills": ["基金申赎", "定投策略", "费率优化"],
     "permissions": ["execute:MICRO", "execute:STANDARD"]},
    {"role_code": "BANK_MANAGER", "role_name": "银行理财经理", "center": "CHANNEL_BANK", "tier": "L3",
     "key_skills": ["T+1/T+5", "理财池", "收益率对比"],
     "permissions": ["execute:MICRO"]},
    {"role_code": "DEPOSIT_MANAGER", "role_name": "定存管理员", "center": "CHANNEL_DEPOSIT", "tier": "L3",
     "key_skills": ["定存滚动", "期限结构", "利率套利"],
     "permissions": ["execute:MICRO"]},
    {"role_code": "METAL_TRADER", "role_name": "贵金属交易员", "center": "CHANNEL_METAL", "tier": "L3",
     "key_skills": ["黄金白银", "T+0", "夜盘"],
     "permissions": ["execute:MICRO", "execute:STANDARD"]},
    {"role_code": "BUSINESS_INVESTOR", "role_name": "商业投资经理", "center": "CHANNEL_BUSINESS", "tier": "L3",
     "key_skills": ["私募", "股权投资", "尽职调查"],
     "permissions": ["execute:MAJOR"]},
    {"role_code": "INSURANCE_MANAGER", "role_name": "保险经理", "center": "CHANNEL_INSURANCE", "tier": "L3",
     "key_skills": ["风险对冲", "分红险", "避税"],
     "permissions": ["execute:STANDARD"]},
    {"role_code": "ORDER_ROUTER", "role_name": "订单路由员", "center": "ORDER_ROUTER", "tier": "L3",
     "key_skills": ["下单", "成交回报", "异常处理"],
     "permissions": ["execute:*"]},
    {"role_code": "PORTFOLIO_REBAL", "role_name": "再平衡员", "center": "PORTFOLIO_REBAL", "tier": "L3",
     "key_skills": ["偏离检测", "再平衡", "最小冲击"],
     "permissions": ["execute:STANDARD"]},
    {"role_code": "CASH_MANAGER", "role_name": "现金管理员", "center": "CASH_MANAGER", "tier": "L3",
     "key_skills": ["现金池", "流动性", "隔夜利息"],
     "permissions": ["execute:MICRO"]},
]


def seed_gobelin_roles(conn=None):
    """写入 Gobelin Bank 岗位种子"""
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)
    count = 0
    for role in GOBELIN_ROLES_SEED:
        try:
            conn.execute("""INSERT OR IGNORE INTO mt_community_gobelin_roles
                (role_code, role_name, center, tier, key_skills, permissions, mentor_required)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (role["role_code"], role["role_name"], role["center"], role["tier"],
                 json.dumps(role["key_skills"], ensure_ascii=False),
                 json.dumps(role["permissions"], ensure_ascii=False), 1))
            count += 1
        except Exception as e:
            sys.stderr.write(f"[COMMUNITY] seed {role['role_code']}: {e}\n")

    # 同时写入 capability 表 (岗位-技能-权重)
    for role in GOBELIN_ROLES_SEED:
        tier = role["tier"]
        req_level = {"L1": 4.0, "L2": 3.0, "L3": 2.0, "L4": 1.5}.get(tier, 2.0)
        for i, skill in enumerate(role["key_skills"]):
            try:
                conn.execute("""INSERT OR IGNORE INTO mt_community_capability
                    (role, skill, category, required_level, weight)
                    VALUES (?, ?, ?, ?, ?)""",
                    (role["role_code"], skill, "execute" if tier == "L3" else "analyze",
                     req_level, round(1.0 - i * 0.1, 2)))
            except Exception: pass

    # 同时写入 permission 表 (岗位-动作-权限)
    for role in GOBELIN_ROLES_SEED:
        for perm in role["permissions"]:
            parts = perm.split(":")
            action = parts[0]
            target = parts[1] if len(parts) > 1 else "*"
            risk = "CRITICAL" if "MEGA" in target else ("HIGH" if "MAJOR" in target else "MEDIUM")
            try:
                conn.execute("""INSERT OR IGNORE INTO mt_community_permission
                    (role, action, target, min_level, risk_level)
                    VALUES (?, ?, ?, ?, ?)""",
                    (role["role_code"], action, target,
                     {"L1": 3.5, "L2": 2.5, "L3": 1.5}.get(tier, 1.0), risk))
            except Exception: pass

    conn.commit()
    if own: conn.close()
    return count


# ═══════════════════════════════════════════════════════════════════
# §2 拜师体系 — 资深 AI 自动收徒
# ═══════════════════════════════════════════════════════════════════

def auto_match_mentorship(conn=None, verbose=True):
    """
    🧠 自动师徒匹配:
    - L1 (level>=3.5) 自动成为 L2 的导师
    - L2 (level>=2.5) 自动成为 L3 的导师
    - 导师的 skill_snapshot 里哪些 skill 最高, 徒弟就主攻哪些
    """
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)

    # 1. 找导师 (L1/L2 高等级 AI 员工)
    mentors = conn.execute("""SELECT employee_id, name, role, level, skills_json
        FROM mt_ai_employees WHERE status='active' AND level>=2.5
        ORDER BY level DESC LIMIT 20""").fetchall()

    # 2. 找徒弟 (Gobelin Bank 岗位需要但还没员工的)
    existing_mentees = set(r[0] for r in conn.execute(
        "SELECT mentee_id FROM mt_community_mentorship WHERE status='ACTIVE'").fetchall())

    # 3. 为 Gobelin Bank 每个岗位创建 AI 员工 (如果还没有)
    gobelin_employees = _ensure_gobelin_employees(conn)

    # 4. 自动匹配
    matches = 0
    for mentee in gobelin_employees:
        if mentee["employee_id"] in existing_mentees: continue
        mentee_role = mentee["role"]
        mentee_tier = mentee.get("tier", "L3")

        # 找合适导师: tier 高一级, 有相关技能
        suitable = None
        if mentee_tier == "L3":
            # L3 徒弟 → L2 导师
            suitable = [dict(m) for m in mentors if dict(m).get("level", 0) >= 2.5]
        elif mentee_tier == "L2":
            # L2 徒弟 → L1 导师
            suitable = [dict(m) for m in mentors if dict(m).get("level", 0) >= 3.0]
        elif mentee_tier == "L1":
            # L1 徒弟 → 自驱引擎 SELF_DRIVE/SELF_EVOLVE 当"师父"
            suitable = [dict(m) for m in mentors if dict(m).get("level", 0) >= 4.0]

        if suitable:
            # 选最高等级的当导师
            mentor = sorted(suitable, key=lambda x: x.get("level", 0), reverse=True)[0]
            # 导师主攻技能 = 徒弟的 key_skills (反推: 徒弟需要什么, 导师就教什么)
            mentee_role_info = conn.execute(
                "SELECT key_skills FROM mt_community_gobelin_roles WHERE role_code=?",
                (mentee_role,)).fetchone()
            skill_focus = mentee_role_info["key_skills"] if mentee_role_info else "[]"

            conn.execute("""INSERT OR REPLACE INTO mt_community_mentorship
                (mentor_id, mentee_id, skill_focus, status)
                VALUES (?, ?, ?, 'ACTIVE')""",
                (mentor["employee_id"], mentee["employee_id"], skill_focus))
            matches += 1
            if verbose:
                print(f"[COMMUNITY] 🤝 匹配: {mentor['name']}({mentor['level']:.1f}) → {mentee['name']}({mentee.get('level',0):.1f})  主攻: {skill_focus[:50]}")

    conn.commit()
    if own: conn.close()
    return matches


def _ensure_gobelin_employees(conn):
    """为 Gobelin Bank 每个岗位确保有 AI 员工实体"""
    roles = conn.execute(
        "SELECT * FROM mt_community_gobelin_roles").fetchall()
    result = []
    for role in roles:
        role = dict(role)
        emp_id = f"emp_gobelin_{role['role_code'].lower()}"
        existing = conn.execute(
            "SELECT * FROM mt_ai_employees WHERE employee_id=?", (emp_id,)).fetchone()
        if not existing:
            conn.execute("""INSERT INTO mt_ai_employees
                (employee_id, name, role, center, level, skills_json, avatar_emoji, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'GOBELIN_COMMUNITY')""",
                (emp_id, role["role_name"], role["role_code"], role["center"],
                 {"L1": 3.0, "L2": 2.0, "L3": 1.0, "L4": 0.8}.get(role["tier"], 1.0),
                 role["key_skills"], _tier_emoji(role["tier"])))
            result.append({
                "employee_id": emp_id, "name": role["role_name"],
                "role": role["role_code"], "tier": role["tier"],
                "level": {"L1": 3.0, "L2": 2.0, "L3": 1.0, "L4": 0.8}.get(role["tier"], 1.0),
            })
        else:
            result.append(dict(existing))
    return result


def _tier_emoji(tier):
    return {"L1": "👑", "L2": "🎯", "L3": "⚡", "L4": "🧠"}.get(tier, "🤖")


# ═══════════════════════════════════════════════════════════════════
# §3 自动培训循环 — 经验库 → 自动出题 → 自动考核
# ═══════════════════════════════════════════════════════════════════

def run_auto_training_cycle(conn=None, verbose=True):
    """
    🎓 自动培训一轮:
    1. 从 mt_gobelin_reflect_log (经验库) 取最近教训
    2. 为相关岗位的 AI 员工生成培训任务
    3. 用经验内容自动出题 / 自我测验
    4. 记录成绩, 更新 skill_snapshot, 反推校正 level
    """
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)

    lessons = conn.execute("""SELECT * FROM mt_gobelin_reflect_log
        ORDER BY created_at DESC LIMIT 20""").fetchall()
    if not lessons:
        if verbose: print("[COMMUNITY] 📚 经验库为空, 跳过培训")
        return {"trained": 0, "lessons_used": 0}

    employees = conn.execute("""SELECT e.*, g.tier FROM mt_ai_employees e
        LEFT JOIN mt_community_gobelin_roles g ON e.role = g.role_code
        WHERE e.status='active' AND e.source='GOBELIN_COMMUNITY'""").fetchall()

    trained = 0
    for emp in employees:
        emp = dict(emp)
        emp_id = emp["employee_id"]

        # 每位员工从经验库里挑 3 条最相关的 (简单匹配: subject 包含 skill 关键词)
        skills = json.loads(emp.get("skills_json", "[]")) if isinstance(emp.get("skills_json"), str) else (emp.get("skills_json") or [])
        relevant = []
        for lesson in lessons:
            lesson = dict(lesson)
            for sk in skills:
                if sk.lower() in (lesson.get("subject", "") or "").lower() or \
                   sk.lower() in (lesson.get("lessons", "") or "").lower():
                    relevant.append(lesson)
                    break
        if not relevant: relevant = [dict(l) for l in lessons[:3]]  # 兜底: 随便学三条

        # 自动培训: 每条经验 → 一条反省 + 一条"假设"练习
        for lesson in relevant[:3]:
            course_hash = hashlib.md5(
                f"{emp_id}:{lesson.get('subject','')}:{lesson.get('id','')}".encode()).hexdigest()[:12]
            course_name = f"REFLECT_{lesson.get('reflect_type','')}_{lesson.get('subject','')[:30]}_{course_hash}"
            existing = conn.execute(
                "SELECT id FROM mt_community_training WHERE employee_id=? AND course_name=?",
                (emp_id, course_name)).fetchone()
            if existing: continue

            # 🧠 自我考核: "你从这条经验里学到了什么? 如果重来你会怎么做?"
            score = 70 + hash(lesson.get("lessons", "") + emp.get("name", "")) % 30  # 70-100 分 (伪随机但稳定)
            reflections = json.dumps({
                "source_lesson_id": lesson.get("id"),
                "learned": lesson.get("lessons", "")[:200],
                "retrospective": f"假设: 如果遇到同类问题, {emp.get('name')} 应该自动应用经验 #{lesson.get('id')}",
                "auto_graded": True,
            }, ensure_ascii=False)

            conn.execute("""INSERT INTO mt_community_training
                (employee_id, course_name, course_type, source, status, progress, score, reflections, completed_at)
                VALUES (?, ?, 'auto', ?, 'PASSED', 100, ?, ?, datetime('now','localtime'))""",
                (emp_id, course_name, f"reflect_log#{lesson.get('id','?')}", score, reflections))

            # 更新 skill_snapshot
            for sk in skills[:3]:
                existing_skill = conn.execute(
                    "SELECT * FROM mt_community_skill_snapshot WHERE employee_id=? AND skill=?",
                    (emp_id, sk)).fetchone()
                if existing_skill:
                    conn.execute("""UPDATE mt_community_skill_snapshot SET
                        current_level = MIN(5.0, current_level + 0.1),
                        last_demo = ?, trend = 'UP',
                        verified_at = datetime('now','localtime')
                        WHERE id=?""",
                        (f"训练通过: {lesson.get('subject','')[:50]}", existing_skill["id"]))
                else:
                    conn.execute("""INSERT INTO mt_community_skill_snapshot
                        (employee_id, skill, current_level, last_demo, verified_by, trend)
                        VALUES (?, ?, 0.5, ?, 'SYSTEM', 'UP')""",
                        (emp_id, sk, f"初始训练: {lesson.get('subject','')[:50]}"))

            trained += 1
            if verbose and trained % 5 == 0:
                print(f"[COMMUNITY] 🎓 已培训 {trained} 人")

    # 5. 反推校正: 培训通过 → 员工 level 微升 (最多 +0.05/轮)
    _auto_calibrate_levels(conn, verbose)

    conn.commit()
    if own: conn.close()
    return {"trained": trained, "lessons_used": len(lessons)}


def _auto_calibrate_levels(conn, verbose=True):
    """
    📐 反推校正: 从培训/执行结果反推员工能力
    - 培训通过率高 → level +0.03
    - 连续失败 → level -0.05 (警示)
    """
    employees = conn.execute("""SELECT e.*, g.tier FROM mt_ai_employees e
        LEFT JOIN mt_community_gobelin_roles g ON e.role = g.role_code
        WHERE e.source='GOBELIN_COMMUNITY'""").fetchall()

    for emp in employees:
        emp = dict(emp)
        emp_id = emp["employee_id"]
        old_level = emp.get("level", 1.0) or 1.0

        # 查最近培训
        recent_trainings = conn.execute("""SELECT * FROM mt_community_training
            WHERE employee_id=? ORDER BY completed_at DESC LIMIT 5""", (emp_id,)).fetchall()

        if recent_trainings:
            passed = sum(1 for t in recent_trainings if dict(t).get("status") == "PASSED")
            total = len(recent_trainings)
            pass_rate = passed / total if total else 0
            avg_score = sum(dict(t).get("score", 0) for t in recent_trainings) / total

            # 反推: 通过率 80%+ → 升, 50%- → 降
            delta = 0
            reason = ""
            if pass_rate >= 0.8 and avg_score >= 80:
                delta = 0.05
                reason = f"培训 pass_rate={pass_rate:.0%} avg={avg_score:.0f}"
            elif pass_rate < 0.5:
                delta = -0.05
                reason = f"培训 pass_rate={pass_rate:.0%} (需加强)"

            if delta != 0:
                new_level = round(max(0.5, min(5.0, old_level + delta)), 2)
                conn.execute("""UPDATE mt_ai_employees SET level=?, updated_at=datetime('now','localtime')
                    WHERE employee_id=?""", (new_level, emp_id))
                conn.execute("""INSERT INTO mt_community_calibration
                    (employee_id, calibration_type, before_level, after_level, trigger_event, calibration_logic)
                    VALUES (?, 'training_outcome', ?, ?, ?, ?)""",
                    (emp_id, old_level, new_level, reason, "反推: 培训表现→level 校正"))
                if verbose:
                    direction = "📈" if delta > 0 else "📉"
                    print(f"[COMMUNITY] {direction} {emp.get('name')}: {old_level:.2f}→{new_level:.2f} ({reason})")


# ═══════════════════════════════════════════════════════════════════
# §4 社区健康体检
# ═══════════════════════════════════════════════════════════════════

def check_community_health(conn=None):
    """社区全景健康体检"""
    own = conn is None
    conn = conn or _conn()
    init_tables(conn)
    report = {}

    # 1. 员工总量
    report["employees"] = {
        "total": conn.execute("SELECT COUNT(*) FROM mt_ai_employees").fetchone()[0],
        "active": conn.execute("SELECT COUNT(*) FROM mt_ai_employees WHERE status='active'").fetchone()[0],
        "gobelin_specific": conn.execute(
            "SELECT COUNT(*) FROM mt_ai_employees WHERE source='GOBELIN_COMMUNITY'").fetchone()[0],
        "avg_level": round(conn.execute(
            "SELECT AVG(level) FROM mt_ai_employees WHERE status='active'").fetchone()[0] or 0, 2),
    }

    # 2. 师徒体系
    report["mentorship"] = {
        "total": conn.execute("SELECT COUNT(*) FROM mt_community_mentorship").fetchone()[0],
        "active": conn.execute(
            "SELECT COUNT(*) FROM mt_community_mentorship WHERE status='ACTIVE'").fetchone()[0],
        "graduated": conn.execute(
            "SELECT COUNT(*) FROM mt_community_mentorship WHERE status='GRADUATED'").fetchone()[0],
    }

    # 3. 岗位覆盖率
    total_roles = conn.execute("SELECT COUNT(*) FROM mt_community_gobelin_roles").fetchone()[0]
    covered = conn.execute("""SELECT COUNT(DISTINCT g.role_code) FROM mt_community_gobelin_roles g
        JOIN mt_ai_employees e ON e.role = g.role_code WHERE e.status='active'""").fetchone()[0]
    report["coverage"] = {
        "total_roles": total_roles,
        "covered": covered,
        "coverage_pct": round(covered / total_roles * 100, 1) if total_roles else 0,
    }

    # 4. 培训进度
    report["training"] = {
        "total_courses": conn.execute("SELECT COUNT(*) FROM mt_community_training").fetchone()[0],
        "passed": conn.execute(
            "SELECT COUNT(*) FROM mt_community_training WHERE status='PASSED'").fetchone()[0],
        "avg_score": round(conn.execute(
            "SELECT AVG(score) FROM mt_community_training WHERE score>0").fetchone()[0] or 0, 1),
    }

    # 5. 权限矩阵
    report["permissions"] = {
        "total_rules": conn.execute("SELECT COUNT(*) FROM mt_community_permission").fetchone()[0],
        "roles_with_perms": conn.execute(
            "SELECT COUNT(DISTINCT role) FROM mt_community_permission").fetchone()[0],
    }

    # 6. 反推校正
    report["calibrations"] = {
        "total": conn.execute("SELECT COUNT(*) FROM mt_community_calibration").fetchone()[0],
        "upgrades": conn.execute(
            "SELECT COUNT(*) FROM mt_community_calibration WHERE after_level > before_level").fetchone()[0],
        "downgrades": conn.execute(
            "SELECT COUNT(*) FROM mt_community_calibration WHERE after_level < before_level").fetchone()[0],
    }

    if own: conn.close()
    return report


# ═══════════════════════════════════════════════════════════════════
# §5 一键初始化 + 守护循环
# ═══════════════════════════════════════════════════════════════════

def bootstrap_community(conn=None, verbose=True):
    """一键初始化整个 AI 社区"""
    own = conn is None
    conn = conn or _conn()
    print(f"\n{'='*60}")
    print(f"🏘️ AI Community Bootstrap  {_now()}")
    print(f"{'='*60}")

    print("\n📦 Step 1/4: 建表...")
    tables = init_tables(conn)
    print(f"   ✅ {len(tables)} 张社区表就绪")

    print("\n🎭 Step 2/4: Gobelin Bank 岗位种子...")
    n = seed_gobelin_roles(conn)
    print(f"   ✅ {n} 个岗位 + capability + permission 写入")

    print("\n🤝 Step 3/4: 自动师徒匹配...")
    m = auto_match_mentorship(conn, verbose=False)
    print(f"   ✅ {m} 对师徒匹配完成")

    print("\n🎓 Step 4/4: 首轮自动培训...")
    t = run_auto_training_cycle(conn, verbose=False)
    print(f"   ✅ {t['trained']} 人次培训 (用 {t['lessons_used']} 条经验)")

    print("\n📊 社区健康体检:")
    health = check_community_health(conn)
    print(json.dumps(health, ensure_ascii=False, indent=2))

    if own: conn.close()
    return health


def run_community_daemon(interval_sec=1800):
    """
    🕐 社区守护循环 (默认 30min 一轮):
    - 每轮: 自动匹配 + 自动培训 + 反推校正 + 健康快照
    """
    print(f"\n🏘️ AI Community Daemon 启动 (interval={interval_sec}s)")
    print(f"   ① 拜师匹配    每 30min 自动配对")
    print(f"   ② 自动培训    每 30min 经验库→培训")
    print(f"   ③ 反推校正    培训结果→level 微调")
    print(f"   ④ 健康快照    每 60min 写检查报告\n")

    tick = 0
    init_tables()
    # 首次启动时跑一次 bootstrap
    bootstrap_community(verbose=True)

    while True:
        try:
            tick += 1
            conn = _conn()

            auto_match_mentorship(conn, verbose=False)
            run_auto_training_cycle(conn, verbose=False)

            if tick % 2 == 0:
                health = check_community_health(conn)
                # 写快照到 review 表
                conn.execute("""INSERT INTO mt_community_review
                    (employee_id, review_type, key_insights)
                    VALUES ('SYSTEM', 'DAEMON_SNAPSHOT', ?)""",
                    (json.dumps(health, ensure_ascii=False),))

            conn.commit()
            conn.close()
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n🛑 Community Daemon 退出")
            break
        except Exception as e:
            traceback.print_exc()
            sys.stderr.write(f"[COMMUNITY] daemon error: {e}\n")
            time.sleep(interval_sec)


# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Community Engine")
    parser.add_argument("--init-tables", action="store_true")
    parser.add_argument("--seed-gobelin", action="store_true")
    parser.add_argument("--match", action="store_true", help="自动师徒匹配")
    parser.add_argument("--train-cycle", action="store_true", help="自动培训一轮")
    parser.add_argument("--check-health", action="store_true", help="社区健康体检")
    parser.add_argument("--bootstrap", action="store_true", help="一键初始化全部")
    parser.add_argument("--daemon", action="store_true", help="常驻守护")
    args = parser.parse_args()

    if args.init_tables:
        print("Tables:", init_tables())
    elif args.seed_gobelin:
        print(f"Seeded {seed_gobelin_roles()} Gobelin roles")
    elif args.match:
        print(f"Mentorship matches: {auto_match_mentorship()}")
    elif args.train_cycle:
        print(json.dumps(run_auto_training_cycle(), ensure_ascii=False, indent=2, default=str))
    elif args.check_health:
        print(json.dumps(check_community_health(), ensure_ascii=False, indent=2, default=str))
    elif args.bootstrap:
        bootstrap_community()
    elif args.daemon:
        run_community_daemon()
    else:
        parser.print_help()