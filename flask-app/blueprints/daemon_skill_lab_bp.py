#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daemon & Skill 研究与研发中心 (flow_lab_20261020)
====================================================
页面:  GET /daemon-skill-lab          — 研发中心主页 (登录门禁)
API:   GET /api/daemon-lab/overview  — 研究总览 JSON (daemon 注册表 + skill 盘点 + 衍生候选)

研究逻辑 (纯本地, 零 token):
  Daemon 研究所: 读 mt_daemon_registry (状态分布/挂载分/重启数/职责) + 实时进程扫描
  Skill  研究所: 扫描 ~/.trae-cn/skills/*/SKILL.md frontmatter, 关键词分类
  衍生引擎:      daemon 无对应 skill 管理Skill → 生成候选, 落库 mt_lab_suggestions
"""
import os
import re
import sqlite3
from flask import Blueprint, render_template, jsonify, request

from blueprints.chat_local_bp import _login_required, _get_user

daemon_skill_lab_bp = Blueprint("daemon_skill_lab_bp", __name__, template_folder=None)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")
SKILLS_DIR = os.path.expanduser("~/.trae-cn/skills")

# Skill 分类关键词 (本地规则, 零 token)
_SKILL_CATEGORIES = [
    ("部署运维", ["deploy", "daemon", "smart-mount", "keepalive", "ops", "运维", "挂载"]),
    ("安全审计", ["security", "audit", "漏洞", "安全", "审查", "加密"]),
    ("开发流程", ["dev", "flow", "git", "commit", "rule", "flask", "代码"]),
    ("AI 引擎", ["ai", "eigenflux", "inference", "brain", "ollama", "向量", "脑库", "推理"]),
    ("数据文档", ["data", "report", "analysis", "research", "文档", "研究", "分析"]),
    ("前端设计", ["frontend", "design", "ui", "前端", "设计"]),
]

_LAB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mt_lab_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- daemon_to_skill / skill_to_daemon
    subject TEXT NOT NULL,           -- 候选主体 (如 sys_rule_enforcer)
    reason TEXT,                     -- 推荐理由
    status TEXT DEFAULT 'PROPOSED',  -- PROPOSED / CLAIMED / ACCEPTED / DISMISSED
    created_at TEXT DEFAULT (datetime('now','localtime'))
)
"""

# ══ 研究中心自动认领 + AI人力分配 + EigenFlux磋商 (flow_lab_claim_20261020) ══
_LAB_CLAIM_SQL = [
    """CREATE TABLE IF NOT EXISTS mt_lab_centers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    keywords TEXT NOT NULL,          -- 逗号分隔领域关键词
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lab_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suggestion_id INTEGER NOT NULL,
    center_id INTEGER NOT NULL,
    employee_names TEXT,             -- 认领时分配的 AI员工 (json)
    professor_names TEXT,            -- 教授数字分身 (json)
    expert_verdict TEXT,             -- EigenFlux 磋商结论
    status TEXT DEFAULT 'CLAIMED',   -- CLAIMED / ACCEPTED / REJECTED
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lab_deliberations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    round_no INTEGER DEFAULT 1,
    speaker TEXT NOT NULL,
    role TEXT NOT NULL,              -- expert/employee/professor/chair
    viewpoint TEXT,
    vote TEXT,                       -- APPROVE / REJECT / ABSTAIN
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lab_workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    domain TEXT DEFAULT '工作流',
    direction TEXT NOT NULL,         -- 研究方向
    description TEXT,
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]

# 研究中心种子 (专业领域 → 自动认领关键词; 含工作流新研究方向)
_SEED_CENTERS = [
    ("daemon_ops", "部署运维中心", "部署运维", "daemon,挂载,keepalive,巡检,修复,ops,部署"),
    ("security_audit", "安全审计中心", "安全审计", "安全,审计,漏洞,加密,风险,红线"),
    ("dev_flow", "开发流程中心", "开发流程", "dev,git,flask,commit,代码,规则,flow"),
    ("ai_engine", "AI 引擎中心", "AI引擎", "ai,推理,脑库,ollama,向量,eigenflux,embedding"),
    ("workflow", "工作流研究中心", "工作流", "工作流,workflow,流水线,调度,协同,编排,任务链"),
    ("data_research", "数据研究中心", "数据研究", "数据,分析,报告,统计,研究,画像"),
    ("frontend_design", "前端设计中心", "前端设计", "前端,设计,ui,页面,视觉,交互"),
]

# 工作流研究方向种子 (新增研究方向)
_SEED_WORKFLOWS = [
    ("认领-磋商-研发流水线", "认领引擎产出的候选如何流入磋商→研发→验收的闭环工作流", "研究候选任务从 PROPOSED 到 ACCEPTED 的全链路编排与 SLA 度量"),
    ("daemon-skill 双向衍生工作流", "daemon 无 Skill 自动补 Skill / Skill 研发成果反哺 daemon 参数", "研究双向衍生触发条件与循环熔断策略"),
    ("教授分身导师工作流", "教授数字分身在研发任务中的评审/导师节点接入", "研究分身专家在代码评审与方向把关中的触发时机与权重"),
    ("零 token 磋商协议", "EigenFlux 多角色磋商的本地规则化表决协议", "研究纯本地磋商的议事规则、平票裁决与升级到 SA 的阈值"),
    ("跨中心任务交换协议", "多中心对同一候选的认领冲突与任务交换", "研究认领冲突仲裁与跨中心协作的握手协议"),
]

# 教授数字分身候选池 (按姓名优先匹配 ai_employees)
_PROFESSOR_HINTS = ["霍金", "拉马努金", "爱因斯坦", "钱学森", "齐白石", "吴道子", "唐伯虎", "韩愈", "图灵", "冯诺依曼", "达芬奇"]


def _ensure_claim_tables():
    conn = _db()
    try:
        for sql in _LAB_CLAIM_SQL:
            conn.execute(sql)
        for code, name, domain, kws in _SEED_CENTERS:
            conn.execute("INSERT OR IGNORE INTO mt_lab_centers (center_code,name,domain,keywords) VALUES (?,?,?,?)",
                         (code, name, domain, kws))
        if conn.execute("SELECT count(*) FROM mt_lab_workflows").fetchone()[0] == 0:
            for nm, desc, direction in _SEED_WORKFLOWS:
                conn.execute("INSERT INTO mt_lab_workflows (name,direction,description) VALUES (?,?,?)",
                             (nm, direction, desc))
        # ══ 任务大厅 (flow_hall_20261020) ══
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_lab_task_hall (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            source TEXT DEFAULT 'manual',    -- derivation/manual/daemon_repair
            source_id INTEGER,               -- 建议/daemon id
            priority TEXT DEFAULT 'NORMAL',  -- HIGH/NORMAL/LOW
            status TEXT DEFAULT 'QUEUED',    -- QUEUED/DISPATCHED/DONE/FAILED
            center_id INTEGER,
            assignment_id INTEGER,
            verdict TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            dispatched_at TEXT
        )""")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_lab_assignments)").fetchall()]
        if "hall_task_id" not in cols:
            conn.execute("ALTER TABLE mt_lab_assignments ADD COLUMN hall_task_id INTEGER")
        # ══ AI 人力资源中心 (flow_hall_20261020, 与任务大厅联动) ══
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_lab_hr_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_name TEXT NOT NULL,
            employee_code TEXT,
            role TEXT DEFAULT 'employee',    -- employee/professor
            hall_task_id INTEGER,
            action TEXT DEFAULT 'DISPATCH',  -- DISPATCH / COMPLETE / REVIEW
            verdict TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.commit()
    finally:
        conn.close()


# ══ 任务大厅 (flow_hall_20261020): 任务自动汇聚 → 自动分配 ══
def _hall_ingest():
    """任务归集: ①衍生候选(PROPOSED) ②daemon异常(FAILED/STOPPED) 自动入厅"""
    conn = _db()
    added = 0
    try:
        for r in conn.execute("SELECT id, subject, reason FROM mt_lab_suggestions WHERE status='PROPOSED'").fetchall():
            if not conn.execute("SELECT 1 FROM mt_lab_task_hall WHERE source='derivation' AND source_id=?", (r["id"],)).fetchone():
                conn.execute("INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority) VALUES (?,?,?,?,?)",
                             (r["subject"], r["reason"], "derivation", r["id"], "NORMAL"))
                added += 1
        try:
            bad = conn.execute("SELECT id, process_name, current_state FROM mt_daemon_registry "
                               "WHERE current_state IN ('FAILED','STOPPED')").fetchall()
        except sqlite3.Error:
            bad = []
        for r in bad:
            if not conn.execute("SELECT 1 FROM mt_lab_task_hall WHERE source='daemon_repair' AND source_id=? AND status!='FAILED'", (r["id"],)).fetchone():
                conn.execute("INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority) VALUES (?,?,?,?,?)",
                             (f"修复 daemon: {r['process_name']}",
                              f"daemon {r['process_name']} 状态 {r['current_state']}, 需巡检修复",
                              "daemon_repair", r["id"], "HIGH"))
                added += 1
        conn.commit()
    finally:
        conn.close()
    return added


def _hall_dispatch_one(task):
    """单任务自动分配: 匹配中心 → 分配人力 → 磋商 → 状态回写"""
    text = f"{task['title']} {task['description'] or ''}"
    center, hit = _match_center(text)
    if not center or hit == 0:
        conn = _db()
        try:
            center = conn.execute("SELECT * FROM mt_lab_centers WHERE center_code='dev_flow'").fetchone()
        finally:
            conn.close()
    emps, profs = _pick_staff(center["domain"], center["keywords"])
    import json as _json
    conn = _db()
    try:
        cur = conn.execute("INSERT INTO mt_lab_assignments (suggestion_id,center_id,employee_names,professor_names,hall_task_id) VALUES (?,?,?,?,?)",
                           (task["source_id"] or 0, center["id"],
                            _json.dumps(emps, ensure_ascii=False), _json.dumps(profs, ensure_ascii=False), task["id"]))
        aid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    verdict = _deliberate(aid, task["title"], center["name"], emps, profs)
    status = "DISPATCHED" if "通过" in verdict else "QUEUED"
    conn = _db()
    try:
        conn.execute("UPDATE mt_lab_task_hall SET status=?, center_id=?, assignment_id=?, verdict=?, dispatched_at=datetime('now','localtime') WHERE id=?",
                     (status, center["id"], aid, verdict, task["id"]))
        if status == "DISPATCHED" and task["source"] == "derivation" and task["source_id"]:
            conn.execute("UPDATE mt_lab_suggestions SET status='CLAIMED' WHERE id=? AND status='PROPOSED'", (task["source_id"],))
        # AI 人力资源中心: 分配成功自动登记人力账
        if status == "DISPATCHED":
            for e in emps:
                conn.execute("INSERT INTO mt_lab_hr_log (employee_name, employee_code, role, hall_task_id, action, verdict) VALUES (?,?,?,?,?,?)",
                             (e["name"], e.get("code"), "employee", task["id"], "DISPATCH", verdict))
            for p in profs:
                conn.execute("INSERT INTO mt_lab_hr_log (employee_name, employee_code, role, hall_task_id, action, verdict) VALUES (?,?,?,?,?,?)",
                             (p["name"], p.get("code"), "professor", task["id"], "REVIEW", verdict))
        conn.commit()
    finally:
        conn.close()
    return {"task": task["title"], "center": center["name"],
            "employees": [e["name"] for e in emps], "professors": [p["name"] for p in profs],
            "verdict": verdict, "status": status}


def run_hall_auto():
    """任务大厅自动引擎: 归集 → 逐任务分配"""
    _ensure_claim_tables()
    ingested = _hall_ingest()
    conn = _db()
    try:
        queued = conn.execute("SELECT * FROM mt_lab_task_hall WHERE status='QUEUED' ORDER BY "
                              "CASE priority WHEN 'HIGH' THEN 0 ELSE 1 END, id").fetchall()
    finally:
        conn.close()
    results = [_hall_dispatch_one(t) for t in queued]
    return {"ingested": ingested, "dispatched": len(results), "results": results}


@daemon_skill_lab_bp.route("/api/daemon-lab/hr/roster")
@_login_required
def hr_roster():
    """AI 人力资源中心: 名册 + 任务负载 + 人力账 (与任务大厅联动)"""
    _ensure_claim_tables()
    conn = _db()
    try:
        total_active = conn.execute("SELECT count(*) FROM ai_employees WHERE status='active'").fetchone()[0]
        prof_total = conn.execute(
            "SELECT count(*) FROM ai_employees WHERE status='active' AND (" +
            " OR ".join(["name LIKE ?"] * len(_PROFESSOR_HINTS)) + ")",
            [f"%{h}%" for h in _PROFESSOR_HINTS]).fetchone()[0]
        # 大厅负载 TOP (人力账聚合)
        workload = [dict(r) for r in conn.execute(
            "SELECT employee_name, role, count(*) AS tasks FROM mt_lab_hr_log "
            "GROUP BY employee_name, role ORDER BY tasks DESC LIMIT 15")]
        # 最近人力账
        recent_log = [dict(r) for r in conn.execute(
            "SELECT l.employee_name, l.role, l.action, l.verdict, l.created_at, h.title AS task_title "
            "FROM mt_lab_hr_log l LEFT JOIN mt_lab_task_hall h ON h.id=l.hall_task_id "
            "ORDER BY l.id DESC LIMIT 20")]
        in_pool = conn.execute("SELECT count(DISTINCT employee_name) FROM mt_lab_hr_log").fetchone()[0]
        return jsonify({"ok": True, "hr": {
            "pool_total": total_active, "prof_total": prof_total,
            "engaged": in_pool, "workload": workload, "recent_log": recent_log,
        }})
    finally:
        conn.close()


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/board", methods=["GET", "POST"])
@_login_required
def hall_board():
    """大厅看板: GET=纯看板; POST=自动归集+自动分配后看板"""
    _ensure_claim_tables()
    auto = None
    if request.method == "POST":
        try:
            auto = run_hall_auto()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    conn = _db()
    try:
        stats = {}
        for r in conn.execute("SELECT status, count(*) n FROM mt_lab_task_hall GROUP BY status"):
            stats[r["status"]] = r["n"]
        tasks = [dict(r) for r in conn.execute(
            "SELECT h.*, c.name AS center_name FROM mt_lab_task_hall h "
            "LEFT JOIN mt_lab_centers c ON c.id=h.center_id "
            "ORDER BY CASE h.status WHEN 'QUEUED' THEN 0 WHEN 'DISPATCHED' THEN 1 ELSE 2 END, "
            "CASE h.priority WHEN 'HIGH' THEN 0 ELSE 1 END, h.id DESC LIMIT 40")]
        return jsonify({"ok": True, "stats": stats, "tasks": tasks, "auto": auto})
    finally:
        conn.close()


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/submit", methods=["POST"])
@_login_required
def hall_submit():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "任务标题不能为空"}), 400
    _ensure_claim_tables()
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority) VALUES (?,?,?,?,?)",
                     (title[:120], (data.get("description") or "").strip()[:500],
                      "manual", None, data.get("priority") or "NORMAL"))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "message": f"任务已入厅: {title[:40]}"})


def _match_center(text):
    """领域匹配: 返回 (center_row, matched_kw)"""
    conn = _db()
    try:
        centers = conn.execute("SELECT * FROM mt_lab_centers WHERE status='ACTIVE'").fetchall()
    finally:
        conn.close()
    t = text.lower()
    best, best_hit = None, 0
    for c in centers:
        hit = sum(1 for k in c["keywords"].split(",") if k.strip().lower() in t)
        if hit > best_hit:
            best, best_hit = c, hit
    return best, best_hit


def _pick_staff(domain, keywords):
    """从 ai_employees 按专业领域分配 AI员工 + 教授数字分身 (纯本地 LIKE 匹配)"""
    conn = _db()
    like_terms = [k.strip() for k in keywords.split(",") if k.strip()][:6]
    conds = " OR ".join(["specialties LIKE ?"] * len(like_terms) + ["description LIKE ?"] * len(like_terms) + ["capabilities LIKE ?"] * len(like_terms))
    args = [f"%{t}%" for t in like_terms] * 3
    try:
        rows = conn.execute(
            f"SELECT name, employee_code, specialties, accuracy FROM ai_employees "
            f"WHERE status='active' AND ({conds}) ORDER BY accuracy DESC LIMIT 24", args).fetchall()
    except sqlite3.Error:
        rows = []
    profs, emps = [], []
    for r in rows:
        nm = r["name"] or ""
        item = {"name": nm, "code": r["employee_code"], "spec": (r["specialties"] or "")[:60]}
        if any(h in nm for h in _PROFESSOR_HINTS) or (r["employee_code"] or "").startswith("PROF"):
            profs.append(item)
        else:
            emps.append(item)
    conn.close()
    return emps[:4], profs[:2]


def _deliberate(assignment_id, subject, center_name, emps, profs):
    """EigenFlux 磋商: 本地规则化 5 席表决 (2专家+2员工+1教授+主席裁决)"""
    votes = []
    conn = _db()
    try:
        def speak(speaker, role, viewpoint, vote):
            conn.execute("INSERT INTO mt_lab_deliberations (assignment_id,round_no,speaker,role,viewpoint,vote) VALUES (?,?,?,?,?,?)",
                         (assignment_id, 1, speaker, role, viewpoint, vote))
            votes.append(vote)
        speak("EigenFlux-架构专家", "expert", f"{subject} 与现有 daemon 体系存在职责重叠风险, 建议以管理 Skill 形态落地而非新进程", "APPROVE")
        speak("EigenFlux-安全专家", "expert", f"新增 {center_name} 认领任务需遵守最小权限与审计落库, 方案可行", "APPROVE")
        for e in emps[:2]:
            speak(e["name"], "employee", f"本岗位可承接 {subject} 的巡检/维护自动化, 专业匹配: {e['spec']}", "APPROVE")
        if profs:
            speak(profs[0]["name"], "professor", f"方向符合长期研究价值, 注意沉淀方法论反哺脑库", "APPROVE")
        else:
            speak("轮值教授席", "professor", "教授分身池暂无精确匹配, 由轮值席代行评审", "ABSTAIN")
        approve = votes.count("APPROVE")
        verdict = "通过 — 进入研发队列" if approve >= 4 else ("附条件通过 — 需补员后复议" if approve >= 3 else "驳回 — 重新论证")
        speak(f"{center_name}·主席团", "chair", f"表决结果 APPROVE={approve}/5, 裁决: {verdict}", verdict[:2])
        conn.execute("UPDATE mt_lab_assignments SET expert_verdict=?, status=? WHERE id=?",
                     (verdict, "ACCEPTED" if approve >= 4 else "CLAIMED", assignment_id))
        if approve >= 4:
            conn.execute("UPDATE mt_lab_suggestions SET status='ACCEPTED' WHERE id=?",
                         (conn.execute("SELECT suggestion_id FROM mt_lab_assignments WHERE id=?", (assignment_id,)).fetchone()[0],))
        conn.commit()
    finally:
        conn.close()
    return verdict


def run_auto_claim():
    """自动认领主引擎: PROPOSED 候选 → 中心认领 → 人力分配 → 磋商裁决"""
    _ensure_claim_tables()
    conn = _db()
    try:
        pending = conn.execute("SELECT id, subject, reason FROM mt_lab_suggestions WHERE status='PROPOSED' ORDER BY id").fetchall()
    finally:
        conn.close()
    results = []
    for s in pending:
        text = f"{s['subject']} {s['reason'] or ''}"
        center, hit = _match_center(text)
        if not center or hit == 0:
            center = next((c for c in _SEED_CENTERS if c[0] == "dev_flow"), None)
            conn2 = _db()
            try:
                center = conn2.execute("SELECT * FROM mt_lab_centers WHERE center_code='dev_flow'").fetchone()
            finally:
                conn2.close()
        emps, profs = _pick_staff(center["domain"], center["keywords"])
        conn2 = _db()
        try:
            cur = conn2.execute("INSERT INTO mt_lab_assignments (suggestion_id,center_id,employee_names,professor_names) VALUES (?,?,?,?)",
                                (s["id"], center["id"],
                                 __import__("json").dumps(emps, ensure_ascii=False),
                                 __import__("json").dumps(profs, ensure_ascii=False)))
            conn2.execute("UPDATE mt_lab_suggestions SET status='CLAIMED' WHERE id=?", (s["id"],))
            conn2.commit()
            aid = cur.lastrowid
        finally:
            conn2.close()
        verdict = _deliberate(aid, s["subject"], center["name"], emps, profs)
        results.append({"subject": s["subject"], "center": center["name"], "employees": [e["name"] for e in emps],
                        "professors": [p["name"] for p in profs], "verdict": verdict})
    return results


@daemon_skill_lab_bp.route("/api/daemon-lab/auto-claim", methods=["POST"])
@_login_required
def lab_auto_claim():
    try:
        results = run_auto_claim()
        return jsonify({"ok": True, "claimed": len(results), "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@daemon_skill_lab_bp.route("/api/daemon-lab/workspaces")
@_login_required
def lab_workspaces():
    _ensure_claim_tables()
    conn = _db()
    try:
        centers = conn.execute("SELECT * FROM mt_lab_centers WHERE status='ACTIVE' ORDER BY id").fetchall()
        out = []
        for c in centers:
            asg = conn.execute(
                "SELECT a.id, a.status, a.expert_verdict, a.employee_names, a.professor_names, s.subject "
                "FROM mt_lab_assignments a JOIN mt_lab_suggestions s ON s.id=a.suggestion_id "
                "WHERE a.center_id=? ORDER BY a.id DESC LIMIT 10", (c["id"],)).fetchall()
            deli = conn.execute(
                "SELECT d.speaker, d.role, d.viewpoint, d.vote FROM mt_lab_deliberations d "
                "JOIN mt_lab_assignments a ON a.id=d.assignment_id WHERE a.center_id=? "
                "ORDER BY d.id DESC LIMIT 8", (c["id"],)).fetchall()
            out.append({
                "center": dict(c), "assignments": [dict(a) for a in asg],
                "deliberations": [dict(r) for r in deli],
            })
        workflows = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_lab_workflows WHERE status='ACTIVE' ORDER BY id").fetchall()]
        stats = {"total": conn.execute("SELECT count(*) FROM mt_lab_assignments").fetchone()[0],
                 "accepted": conn.execute("SELECT count(*) FROM mt_lab_assignments WHERE status='ACCEPTED'").fetchone()[0],
                 "claimed": conn.execute("SELECT count(*) FROM mt_lab_assignments WHERE status='CLAIMED'").fetchone()[0]}
        return jsonify({"ok": True, "centers": out, "workflows": workflows, "stats": stats})
    finally:
        conn.close()


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _categorize(text):
    t = text.lower()
    for cat, kws in _SKILL_CATEGORIES:
        if any(k.lower() in t for k in kws):
            return cat
    return "通用"


def _scan_skills():
    """扫描本地 skill 目录, 解析 SKILL.md frontmatter"""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for name in sorted(os.listdir(SKILLS_DIR)):
        sm = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if not os.path.isfile(sm):
            continue
        try:
            with open(sm, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2000)
        except OSError:
            continue
        fm_name, fm_desc = name, ""
        m = re.search(r"^name:\s*(.+)$", head, re.M)
        if m:
            fm_name = m.group(1).strip()
        m = re.search(r"^description:\s*(.+)$", head, re.M)
        if m:
            fm_desc = m.group(1).strip()[:160]
        cat = _categorize(fm_name + " " + fm_desc)
        skills.append({"dir": name, "name": fm_name, "desc": fm_desc, "category": cat})
    return skills


def _scan_daemons():
    """读 daemon 注册表 + 实时进程对照"""
    rows, states = [], {}
    try:
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT process_name, current_state, pid, mount_score, restart_count, "
                "mount_source, daemon_duty FROM mt_daemon_registry ORDER BY process_name"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    daemons = []
    for r in rows:
        st = r["current_state"] or "UNKNOWN"
        states[st] = states.get(st, 0) + 1
        duty = (r["daemon_duty"] or "")[:120]
        daemons.append({
            "name": r["process_name"], "state": st, "pid": r["pid"],
            "score": round(r["mount_score"] or 0, 2),
            "restarts": r["restart_count"] or 0,
            "source": r["mount_source"] or "-", "duty": duty,
        })
    # 实时进程 (注册表为空时兜底为研究数据源)
    live = set()
    try:
        import subprocess
        out = subprocess.run(["ps", "axo", "command"], capture_output=True, text=True, timeout=10).stdout
        live = set(re.findall(r"sys_[a-z_]+", out))
    except Exception:
        pass
    if not daemons and live:
        known = {"sys_eigenflux_network"}
        for name in sorted(live):
            st = "IDLE" if name in known else "RUNNING"
            states[st] = states.get(st, 0) + 1
            daemons.append({
                "name": name, "state": st, "pid": None,
                "score": 0.0, "restarts": 0, "source": "live_ps", "duty": "实时进程扫描发现 (注册表落库待同步)",
            })
    return daemons, states, live


def _derive_candidates(daemons, skills):
    """衍生引擎: daemon 无对应管理 skill → 候选; 已管理 → 跳过"""
    skill_text = " ".join(s["dir"] + " " + s["desc"] for s in skills).lower()
    candidates = []
    for d in daemons:
        key = d["name"].replace("sys_", "")
        if key in skill_text or d["name"] in skill_text:
            continue
        if d["state"] != "RUNNING":
            continue
        reason = f"daemon {d['name']} 长期运行但无配套管理 Skill (巡检/修复/状态查询 CLI 化)"
        candidates.append({"kind": "daemon_to_skill", "subject": d["name"], "reason": reason})
    return candidates[:8]


def _persist_suggestions(candidates):
    if not candidates:
        return
    try:
        conn = _db()
        try:
            conn.execute(_LAB_TABLE_SQL)
            for c in candidates:
                dup = conn.execute(
                    "SELECT 1 FROM mt_lab_suggestions WHERE kind=? AND subject=? AND status='PROPOSED'",
                    (c["kind"], c["subject"])).fetchone()
                if not dup:
                    conn.execute("INSERT INTO mt_lab_suggestions (kind, subject, reason) VALUES (?,?,?)",
                                 (c["kind"], c["subject"], c["reason"]))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


@daemon_skill_lab_bp.route("/daemon-skill-lab")
@_login_required
def lab_page():
    user = _get_user()
    return render_template("daemon_skill_lab.html", user=user)


@daemon_skill_lab_bp.route("/api/daemon-lab/overview")
@_login_required
def lab_overview():
    daemons, states, live = _scan_daemons()
    skills = _scan_skills()
    candidates = _derive_candidates(daemons, skills)
    _persist_suggestions(candidates)
    # 历史候选 (已落库)
    persisted = []
    try:
        conn = _db()
        try:
            conn.execute(_LAB_TABLE_SQL)
            rows = conn.execute(
                "SELECT kind, subject, reason, status, created_at FROM mt_lab_suggestions "
                "ORDER BY id DESC LIMIT 20").fetchall()
            persisted = [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    # 分类统计
    cat_stats = {}
    for s in skills:
        cat_stats[s["category"]] = cat_stats.get(s["category"], 0) + 1
    return jsonify({
        "ok": True,
        "daemon": {
            "total": len(daemons), "states": states, "live_processes": len(live),
            "items": daemons[:40],
        },
        "skill": {
            "total": len(skills), "categories": cat_stats, "items": skills,
        },
        "suggestions": {
            "fresh": candidates, "persisted": persisted,
        },
    })
