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
import json
import os
import re
import sqlite3
from datetime import datetime
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
    ("edu_qbank", "教育题库中心", "教育题库", "教育,题库,考试,备课,教学,讲解,试题,测验,摸底,月考,模拟,招生"),  # flow_exam_auto_20261020
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

# ══ 五主体入驻任务大厅 (flow_hall_resident_20261020) ══
# 规则治理/法务合规/人事人力/专家团队/Skill研发 — 常驻中心, 采集适配器自动入厅 + 复用抢单生命周期
_RESIDENT_CENTERS = [
    ("rules_gov", "规则治理中心", "规则治理", "规则,rule,变更,changelog,弱约束,违反,铁律,治理"),
    ("legal", "法务合规中心", "法务合规", "法务,合规,legal,评审,风险,个保法,网安法,消保法"),
    ("hr_center", "人事人力中心", "人事人力", "人事,人力,员工,雇佣,绩效,跟进,名册,roster"),
    ("expert_team", "专家团队中心", "专家团队", "专家,eigenflux,磋商,表决,连线,心跳,专家团队"),
    ("skill_dev", "Skill研发中心", "Skill研发", "skill,技能,衍生,SKILL.md,能力库"),
]


def _ensure_claim_tables():
    conn = _db()
    try:
        for sql in _LAB_CLAIM_SQL:
            conn.execute(sql)
        for code, name, domain, kws in _SEED_CENTERS + _RESIDENT_CENTERS:
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
        # ══ 统一审计层 (flow_audit_20261020): 所有操作入库入日志, 可回溯追责 ══
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_lab_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT NOT NULL,          -- 操作者 (username)
            operator_role TEXT,              -- 操作者角色
            center TEXT NOT NULL,            -- 来源中心: lab/hall/hr/edu/exam
            action TEXT NOT NULL,            -- AUTO_CLAIM/HALL_DISPATCH/HALL_SUBMIT/EDU_RUN...
            subject TEXT,                    -- 主体 (任务/课程/员工/统计)
            detail_json TEXT,                -- 完整载荷+结果摘要 (JSON)
            ip TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lab_audit_created ON mt_lab_audit_log(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lab_audit_operator ON mt_lab_audit_log(operator)")
        # ══ 接任务生命周期 (flow_hall_claim_opt_20261020) ══
        # 状态机: QUEUED --分配--> DISPATCHED --抢单--> CLAIMED --开工--> IN_PROGRESS
        #        --交付--> DELIVERED --验收--> DONE / REWORK(返工回 IN_PROGRESS) / 超时--> QUEUED(回收)
        # flow_task_hall_20261022: 发布体系字段 (编号/发布人/类型/验收标准/期望时间/审批/归档/取消)
        for alter in ("claim_owner", "claim_owner_role", "claim_type", "claimed_at",
                      "started_at", "progress", "progress_note", "delivered_at",
                      "deliverable", "acceptor", "accepted_at", "deadline_at", "reject_reason",
                      "updated_at",
                      "hall_code", "publisher", "publisher_role", "task_type",
                      "acceptance_criteria", "expected_at", "approval_status",
                      "approved_by", "approved_at", "archived_at", "cancel_reason"):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_lab_task_hall)").fetchall()]
            if alter not in cols:
                conn.execute(f"ALTER TABLE mt_lab_task_hall ADD COLUMN {alter} TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_lab_task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hall_task_id INTEGER NOT NULL,
            event TEXT NOT NULL,             -- CLAIM/START/PROGRESS/DELIVER/ACCEPT/REWORK/RECLAIM/RECYCLE/EXPIRE
            actor TEXT DEFAULT 'system',
            actor_role TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lab_task_events_task ON mt_lab_task_events(hall_task_id)")
        conn.commit()
    finally:
        conn.close()


# ── 统一审计 helper (flow_audit_20261020): DB + 文件双写 ──
import logging as _logging
from flask import request as _flask_request

_AUDIT_LOGGER = _logging.getLogger("mtscos.center_audit")
if not _AUDIT_LOGGER.handlers:
    try:
        os.makedirs(os.path.join(_APP_DIR, "logs"), exist_ok=True)
        _fh = _logging.FileHandler(os.path.join(_APP_DIR, "logs", "center_audit.log"), encoding="utf-8")
        _fh.setFormatter(_logging.Formatter("%(asctime)s | %(message)s"))
        _AUDIT_LOGGER.addHandler(_fh)
        _AUDIT_LOGGER.setLevel(_logging.INFO)
    except OSError:
        pass


def _audit(center, action, subject, detail):
    """统一审计: 操作者级落库 mt_lab_audit_log + 文件 logs/center_audit.log 双写"""
    operator, orole = "anonymous", "-"
    try:
        u = _get_user()
        operator = u.get("username") or f"user:{u.get('user_id')}" or "anonymous"
        orole = u.get("role") or "-"
    except Exception:
        pass
    ip = ua = ""
    try:
        ip = _flask_request.remote_addr or ""
        ua = (_flask_request.user_agent.string or "")[:180]
    except Exception:
        pass
    try:
        detail_json = json.dumps(detail, ensure_ascii=False, default=str)[:4000]
    except Exception:
        detail_json = str(detail)[:4000]
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_lab_audit_log (operator,operator_role,center,action,subject,detail_json,ip,user_agent) VALUES (?,?,?,?,?,?,?,?)",
                     (operator, orole, center, action, str(subject)[:200], detail_json, ip, ua))
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    _AUDIT_LOGGER.info("%s | %s | %s | %s | %s", operator, center, action, subject, detail_json[:600])


# ══ 任务大厅 (flow_hall_20261020): 任务自动汇聚 → 自动分配 ══
def _hall_ingest():
    """任务归集: ①衍生候选(PROPOSED) ②daemon异常(FAILED/STOPPED) 自动入厅"""
    conn = _db()
    added = 0
    new_bad = []
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
                new_bad.append(dict(r))
        # 企微中枢 (flow_wecom_20261020): daemon 异常自动告警推送
        if new_bad:
            try:
                from blueprints.wecom_hub_bp import notify_daemon_alert
                notify_daemon_alert(new_bad)
            except Exception:
                pass
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
        # flow_team_collab_20261022: 分派成功即开跨团队协作频道, 强制各天团实时互通
        if status == "DISPATCHED":
            try:
                from engines.ai_team_collab_engine import init_tables, open_channel
                init_tables()
                open_channel({"id": task["id"], "title": task["title"],
                              "description": task.get("description") or "",
                              "source": task.get("source") or "开发"})
            except Exception as _ce:
                print(f"[TEAM-COLLAB] ⚠️ 开频道失败 task={task['id']}: {_ce}")
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
        queued = conn.execute("SELECT * FROM mt_lab_task_hall WHERE status='QUEUED' "
                              "AND COALESCE(approval_status,'APPROVED')!='PENDING' ORDER BY "
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
            # 审计 (flow_audit_20261020): 大厅归集+分配操作入库入日志
            _audit("hall", "HALL_AUTO", f"归集{auto['ingested']}·分配{auto['dispatched']}",
                   {"ingested": auto["ingested"], "dispatched": auto["dispatched"],
                    "results": auto["results"]})
            # 企微中枢 (flow_wecom_20261020): 分配播报推送
            try:
                from blueprints.wecom_hub_bp import notify_hall_dispatch
                notify_hall_dispatch(auto["results"], auto["ingested"])
            except Exception:
                pass
        except Exception as e:
            _audit("hall", "HALL_AUTO", "FAILED", {"error": str(e)})
            return jsonify({"ok": False, "error": str(e)}), 500
    conn = _db()
    try:
        stats = {}
        for r in conn.execute("SELECT status, count(*) n FROM mt_lab_task_hall GROUP BY status"):
            stats[r["status"]] = r["n"]
        pending_approval = conn.execute(
            "SELECT count(*) FROM mt_lab_task_hall WHERE approval_status='PENDING'").fetchone()[0]
        archived_n = conn.execute(
            "SELECT count(*) FROM mt_lab_task_hall WHERE archived_at IS NOT NULL").fetchone()[0]
        # flow_task_hall_20261022: 默认隐藏已归档; include_archived=1 可查全量
        incl_arch = (request.args.get("include_archived") or "").lower() in ("1", "true", "yes")
        where = "" if incl_arch else "WHERE h.archived_at IS NULL "
        tasks = [dict(r) for r in conn.execute(
            "SELECT h.*, c.name AS center_name FROM mt_lab_task_hall h "
            "LEFT JOIN mt_lab_centers c ON c.id=h.center_id " + where +
            "ORDER BY CASE h.status WHEN 'QUEUED' THEN 0 WHEN 'DISPATCHED' THEN 1 ELSE 2 END, "
            "CASE h.priority WHEN 'HIGH' THEN 0 ELSE 1 END, h.id DESC LIMIT 60")]
        columns = {k: [] for k in ("QUEUED", "DISPATCHED", "CLAIMED", "IN_PROGRESS",
                                   "DELIVERED", "DONE", "CANCELLED")}
        for t in tasks:
            columns.setdefault(t["status"] or "QUEUED", []).append(t)
        return jsonify({"ok": True, "stats": stats, "tasks": tasks, "columns": columns,
                        "pending_approval": pending_approval, "archived": archived_n,
                        "include_archived": incl_arch, "auto": auto})
    finally:
        conn.close()


# ════════════════ 发布任务体系 (flow_task_hall_20261022) ════════════════
# 闭环: 发布(PUBLISH) → 审批(APPROVE/REJECT) → 分派(DISPATCH) → 抢单(CLAIM)
#       → 开工(START) → 进度(PROGRESS) → 交付(DELIVER) → 验收(ACCEPT/REWORK)
#       → 归档(ARCHIVE) → 投喂脑库
_TASK_TYPES = (("DEV", "开发"), ("OPS", "运维"), ("SECURITY", "安全"), ("EDU", "教研"),
               ("DOC", "文档"), ("RESEARCH", "研究"), ("OTHER", "其它"))
_TASK_TYPE_LABELS = dict(_TASK_TYPES)
_HALL_APPROVAL_TYPES = {"SECURITY"}          # 敏感类型必须审批
_HALL_APPROVAL_PRIORITIES = {"HIGH"}         # 高优先级必须审批
_HALL_ADMIN_ROLES = ("admin", "super_admin")
_HALL_CANCELABLE = ("QUEUED", "DISPATCHED")


def _hall_next_code(conn) -> str:
    """任务编号 TH-YYYYMMDD-#### (当日流水)"""
    prefix = "TH-" + datetime.now().strftime("%Y%m%d") + "-"
    n = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE hall_code LIKE ?",
                     (prefix + "%",)).fetchone()[0]
    return f"{prefix}{int(n) + 1:04d}"


def _hall_feed_brain(task, note: str) -> None:
    """闭环沉淀: 归档/验收结果投喂 AI 脑库 (失败不影响主流程)"""
    try:
        conn = _db()
        try:
            conn.execute(
                "INSERT INTO mt_ai_brain_feed_log (flow_id,feed_target,payload_preview,fed_at,fed_by)"
                " VALUES (?,?,?,datetime('now','localtime'),?)",
                ("flow_task_hall_20261022", "task_hall",
                 f"[{task.get('hall_code') or task.get('id')}] {task.get('title')} | {note}"[:800],
                 "hall_accept"))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def _hall_publish(data: dict, u: dict) -> dict:
    """发布任务: 校验 → 编号/发布人/类型/验收标准落库 → 审批判定 → 通过则立即分派"""
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("任务标题不能为空")
    ttype = (data.get("task_type") or "OTHER").strip().upper()
    if ttype not in _TASK_TYPE_LABELS:
        raise ValueError("task_type 须为 " + "/".join(k for k, _ in _TASK_TYPES))
    priority = (data.get("priority") or "NORMAL").strip().upper()
    if priority not in ("HIGH", "NORMAL", "LOW"):
        raise ValueError("priority 须为 HIGH/NORMAL/LOW")
    role = u.get("role") or "user"
    need_approval = (priority in _HALL_APPROVAL_PRIORITIES
                     or ttype in _HALL_APPROVAL_TYPES) and role not in _HALL_ADMIN_ROLES
    approval = "PENDING" if need_approval else "APPROVED"

    conn = _db()
    try:
        code = _hall_next_code(conn)
        cur = conn.execute(
            "INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority,status,"
            "hall_code,publisher,publisher_role,task_type,acceptance_criteria,expected_at,"
            "approval_status,approved_by,approved_at,updated_at) "
            "VALUES (?,?,?,?,?,'QUEUED',?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (title[:120], (data.get("description") or "").strip()[:500], "manual", None,
             priority, code, u.get("username") or "anonymous", role, ttype,
             (data.get("acceptance_criteria") or "").strip()[:1000],
             (data.get("expected_at") or "").strip()[:40], approval,
             "" if need_approval else (u.get("username") or "system"),
             None if need_approval else datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        task_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        task = dict(row) if row else {"id": task_id, "title": title}
    finally:
        conn.close()
    _hall_task_event(task_id, "PUBLISH", u.get("username") or "anonymous", role,
                     f"{code} {_TASK_TYPE_LABELS[ttype]} {priority} 审批={approval}")
    _audit("hall", "HALL_PUBLISH", title[:80],
           {"task_id": task_id, "hall_code": code, "task_type": ttype, "priority": priority,
            "approval_status": approval, "acceptance_criteria": data.get("acceptance_criteria")})
    dispatch = None
    if approval == "APPROVED":
        dispatch = _hall_dispatch_one(task)
        _hall_task_event(task_id, "DISPATCH", "system", "system",
                         f'自动分派 → {dispatch["center"]} ({"通过" if dispatch["status"] == "DISPATCHED" else "磋商未通过"})')
    return {"task_id": task_id, "hall_code": code, "title": title,
            "approval_status": approval, "need_approval": need_approval,
            "dispatched": bool(dispatch and dispatch["status"] == "DISPATCHED"),
            "dispatch": dispatch}


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/publish-meta")
@_login_required
def hall_publish_meta():
    """发布端元数据: 可选任务类型/优先级/中心/审批规则"""
    _ensure_claim_tables()
    conn = _db()
    try:
        centers = [dict(r) for r in conn.execute(
            "SELECT id,center_code,name,domain FROM mt_lab_centers ORDER BY id")]
    finally:
        conn.close()
    return jsonify({"ok": True, "meta": {
        "task_types": [{"code": k, "label": v} for k, v in _TASK_TYPES],
        "priorities": [{"code": "HIGH", "label": "高"}, {"code": "NORMAL", "label": "普通"},
                       {"code": "LOW", "label": "低"}],
        "centers": centers,
        "approval_rule": "SECURITY 类型或 HIGH 优先级需 admin/super_admin 审批后自动分派; 其余发布即分派",
        "state_machine": "QUEUED→DISPATCHED→CLAIMED→IN_PROGRESS→DELIVERED→DONE→ARCHIVED"
                         "(REWORK 回 IN_PROGRESS, 超时回 QUEUED, PENDING/CANCELLED 旁路)",
    }})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/submit", methods=["POST"])
@_login_required
def hall_submit():
    """发布任务: 记录发布人/类型/验收标准/期望时间, 生成编号, 审批或即时分派"""
    _ensure_claim_tables()
    u = _get_user()
    try:
        r = _hall_publish(request.get_json(silent=True) or {}, u)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    msg = (f'{r["hall_code"]} 已发布 → 已自动分派 {r["dispatch"]["center"]}'
           if r["dispatched"] else
           f'{r["hall_code"]} 已提交, 待管理员审批后分派' if r["need_approval"] else
           f'{r["hall_code"]} 已入厅, 等待分派')
    return jsonify({"ok": True, "message": msg, **r})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/approve", methods=["POST"])
@_login_required
def hall_approve():
    """发布审批: admin+ 审批 PENDING 任务 → 通过即分派 / 驳回即关闭"""
    _ensure_claim_tables()
    u = _get_user()
    if u.get("role") not in _HALL_ADMIN_ROLES:
        return jsonify({"ok": False, "error": "仅 admin/super_admin 可审批发布"}), 403
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    decision = (data.get("decision") or "approve").strip()
    if decision not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "decision 须 approve/reject"}), 400
    conn = _db()
    try:
        t = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not t:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if (t["approval_status"] or "") != "PENDING":
        return jsonify({"ok": False, "error": f'任务审批态为 {t["approval_status"] or "NONE"}, 非 PENDING'}), 409
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if decision == "approve":
        conn = _db()
        try:
            conn.execute("UPDATE mt_lab_task_hall SET approval_status='APPROVED', approved_by=?,"
                         "approved_at=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (u.get("username"), now, task_id))
            conn.commit()
            row = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        finally:
            conn.close()
        dispatch = _hall_dispatch_one(dict(row))
        _hall_task_event(task_id, "APPROVE", u.get("username"), u.get("role"),
                         f'审批通过 → 分派 {dispatch["center"]} ({dispatch["status"]})')
        _audit("hall", "HALL_APPROVE", t["title"][:60], {"task_id": task_id, "dispatch": dispatch})
        return jsonify({"ok": True, "approval_status": "APPROVED", "dispatch": dispatch,
                        "message": f'{t["hall_code"] or task_id} 审批通过, 已分派 {dispatch["center"]}'})
    reason = (data.get("reason") or "审批驳回").strip()[:300]
    conn = _db()
    try:
        conn.execute("UPDATE mt_lab_task_hall SET approval_status='REJECTED', status='CANCELLED',"
                     "approved_by=?, approved_at=?, cancel_reason=?,"
                     "updated_at=datetime('now','localtime') WHERE id=?",
                     (u.get("username"), now, reason, task_id))
        conn.commit()
    finally:
        conn.close()
    _hall_task_event(task_id, "REJECT", u.get("username"), u.get("role"), reason)
    _audit("hall", "HALL_REJECT", t["title"][:60], {"task_id": task_id, "reason": reason})
    return jsonify({"ok": True, "approval_status": "REJECTED", "status": "CANCELLED"})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/cancel", methods=["POST"])
@_login_required
def hall_cancel():
    """撤回/关闭任务: 发布人本人或 admin+; 仅 QUEUED/DISPATCHED 可撤"""
    _ensure_claim_tables()
    u = _get_user()
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    reason = (data.get("reason") or "发布人撤回").strip()[:300]
    conn = _db()
    try:
        t = conn.execute("SELECT status,publisher,title,hall_code FROM mt_lab_task_hall WHERE id=?",
                         (task_id,)).fetchone()
    finally:
        conn.close()
    if not t:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if u.get("role") not in _HALL_ADMIN_ROLES and t["publisher"] != u.get("username"):
        return jsonify({"ok": False, "error": "仅发布人本人或 admin 可撤回"}), 403
    if t["status"] not in _HALL_CANCELABLE:
        return jsonify({"ok": False, "error": f'状态 {t["status"]} 不可撤回 (仅 QUEUED/DISPATCHED)'}), 409
    conn = _db()
    try:
        cur = conn.execute("UPDATE mt_lab_task_hall SET status='CANCELLED', cancel_reason=?,"
                           "updated_at=datetime('now','localtime') WHERE id=? AND status IN ('QUEUED','DISPATCHED')",
                           (reason, task_id))
        conn.commit()
        won = cur.rowcount == 1
    finally:
        conn.close()
    if not won:
        return jsonify({"ok": False, "error": "状态已变化, 请刷新"}), 409
    _hall_task_event(task_id, "CANCEL", u.get("username"), u.get("role"), reason)
    _audit("hall", "HALL_CANCEL", t["title"][:60], {"task_id": task_id, "reason": reason})
    return jsonify({"ok": True, "status": "CANCELLED", "message": f'{t["hall_code"] or task_id} 已撤回'})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/archive", methods=["POST"])
@_login_required
def hall_archive():
    """归档: DONE 任务归档 + 投喂脑库; 单条 task_id 或批量 older_than_days"""
    _ensure_claim_tables()
    u = _get_user()
    if u.get("role") not in _HALL_ADMIN_ROLES:
        return jsonify({"ok": False, "error": "仅 admin/super_admin 可归档"}), 403
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    conn = _db()
    try:
        if task_id:
            rows = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=? AND status='DONE'"
                                " AND archived_at IS NULL", (task_id,)).fetchall()
        else:
            days = max(int(data.get("older_than_days", 0) or 0), 0)
            rows = conn.execute(
                "SELECT * FROM mt_lab_task_hall WHERE status='DONE' AND archived_at IS NULL"
                " AND COALESCE(accepted_at,updated_at,created_at) < datetime('now','localtime',?)",
                (f'-{days} days',)).fetchall()
        archived = []
        for r in rows:
            cur = conn.execute("UPDATE mt_lab_task_hall SET archived_at=datetime('now','localtime'),"
                               "updated_at=datetime('now','localtime') WHERE id=? AND archived_at IS NULL",
                               (r["id"],))
            if cur.rowcount == 1:
                archived.append(dict(r))
        conn.commit()
    finally:
        conn.close()
    if task_id and not archived:
        return jsonify({"ok": False, "error": "任务不存在或非 DONE/已归档"}), 409
    for r in archived:
        _hall_task_event(r["id"], "ARCHIVE", u.get("username"), u.get("role"), "验收完成归档")
        _hall_feed_brain(r, f'归档 | 交付: {str(r.get("deliverable") or "")[:160]}')
    _audit("hall", "HALL_ARCHIVE", f'{len(archived)} 条', {"ids": [r["id"] for r in archived]})
    return jsonify({"ok": True, "archived": len(archived),
                    "ids": [r["id"] for r in archived]})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/pipeline")
@_login_required
def hall_pipeline():
    """发布体系闭环漏斗: 各环节计数 + 卡点预警 + 平均验收时长"""
    _ensure_claim_tables()
    conn = _db()
    try:
        stats = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status,count(*) n FROM mt_lab_task_hall GROUP BY status")}
        appr = {r["approval_status"] or "NONE": r["n"] for r in conn.execute(
            "SELECT approval_status,count(*) n FROM mt_lab_task_hall GROUP BY approval_status")}
        types = [dict(r) for r in conn.execute(
            "SELECT COALESCE(task_type,'OTHER') task_type,count(*) n FROM mt_lab_task_hall"
            " GROUP BY task_type ORDER BY n DESC")]
        stuck = [dict(r) for r in conn.execute(
            "SELECT id,hall_code,title,status,claim_owner,created_at,dispatched_at FROM mt_lab_task_hall"
            " WHERE (approval_status='PENDING')"
            "    OR (status='QUEUED' AND created_at < datetime('now','localtime','-24 hours'))"
            "    OR (status='DISPATCHED' AND dispatched_at < datetime('now','localtime','-24 hours'))"
            "    OR (status='DELIVERED' AND delivered_at < datetime('now','localtime','-24 hours'))"
            " ORDER BY id LIMIT 20")]
        avg = conn.execute(
            "SELECT avg((julianday(accepted_at)-julianday(dispatched_at))*24) h"
            " FROM mt_lab_task_hall WHERE accepted_at IS NOT NULL AND dispatched_at IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    funnel = [{"key": k, "label": v, "count": stats.get(k, 0)} for k, v in (
        ("QUEUED", "待分派/待审批"), ("DISPATCHED", "待抢单"), ("CLAIMED", "待开工"),
        ("IN_PROGRESS", "执行中"), ("DELIVERED", "待验收"), ("DONE", "已完成"),
        ("ARCHIVED", "已归档"), ("CANCELLED", "已撤回/驳回"), ("FAILED", "失败"))]
    return jsonify({"ok": True, "funnel": funnel, "stats": stats, "approval": appr,
                    "types": types, "stuck": stuck,
                    "avg_accept_hours": round(float(avg), 1) if avg else None})



# ════════════════ 接任务生命周期 (flow_hall_claim_opt_20261020) ════════════════
# 状态机: DISPATCHED→CLAIMED(抢单)→IN_PROGRESS(开工)→DELIVERED(交付)→DONE(验收)
#         REWORK(返工)→IN_PROGRESS; CLAIMED/IN_PROGRESS 超时→QUEUED(回收回池)

_HALL_CLAIM_TIMEOUT_HOURS = 24      # 抢单未开工时限
_HALL_PROGRESS_TIMEOUT_HOURS = 72   # 开工未交付时限
_VALID_TRANSITIONS = {
    "CLAIM":  {"DISPATCHED": "CLAIMED"},
    "START":  {"CLAIMED": "IN_PROGRESS"},
    "PROGRESS": {"IN_PROGRESS": "IN_PROGRESS"},
    "DELIVER": {"IN_PROGRESS": "DELIVERED"},
    "ACCEPT": {"DELIVERED": "DONE"},
    "REWORK": {"DELIVERED": "IN_PROGRESS"},
}


def _hall_task_event(task_id, event, actor, actor_role, note=""):
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_lab_task_events (hall_task_id,event,actor,actor_role,note) VALUES (?,?,?,?,?)",
                     (task_id, event, actor, actor_role, note[:300]))
        conn.commit()
    finally:
        conn.close()


def _hall_transition(task_id, action, actor, actor_role, extra=None):
    """原子状态迁移: UPDATE ... WHERE status=期望前置态 (并发抢单安全, 唯一赢家)"""
    expect = _VALID_TRANSITIONS[action]
    pre_status = next(iter(expect))
    new_status = expect[pre_status]
    extra = extra or {}
    sets = ["status=?", "updated_at=datetime('now','localtime')"]
    args = [new_status]
    for col, val in extra.items():
        sets.append(f"{col}=?")
        args.append(val)
    args.append(task_id)
    args.append(pre_status)
    conn = _db()
    try:
        cur = conn.execute(f"UPDATE mt_lab_task_hall SET {', '.join(sets)} WHERE id=? AND status=?", args)
        conn.commit()
        won = cur.rowcount == 1
        if won:
            row = conn.execute("SELECT title FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
            title = row["title"] if row else f"#{task_id}"
        else:
            row = conn.execute("SELECT status, claim_owner FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
            title = ""
    finally:
        conn.close()
    return won, new_status, title, (dict(row) if row else {})


def _hall_ensure_deadline(task_id, hours):
    conn = _db()
    try:
        conn.execute("UPDATE mt_lab_task_hall SET deadline_at=datetime('now','localtime', ?) "
                     "WHERE id=? AND deadline_at IS NULL", (f'+{int(hours)} hours', task_id))
        conn.commit()
    finally:
        conn.close()


def run_hall_recycle():
    """超时回收: CLAIMED 未开工 / IN_PROGRESS 未交付 超时 → 回池 QUEUED (原子)"""
    _ensure_claim_tables()
    conn = _db()
    try:
        stale = conn.execute(
            """SELECT id, status, claim_owner, title FROM mt_lab_task_hall
               WHERE (status='CLAIMED' AND claimed_at IS NOT NULL
                      AND claimed_at < datetime('now','localtime', ?))
                  OR (status='IN_PROGRESS' AND started_at IS NOT NULL
                      AND started_at < datetime('now','localtime', ?))""",
            (f'-{_HALL_CLAIM_TIMEOUT_HOURS} hours', f'-{_HALL_PROGRESS_TIMEOUT_HOURS} hours')).fetchall()
        recycled = []
        for t in stale:
            limit_h = _HALL_CLAIM_TIMEOUT_HOURS if t["status"] == "CLAIMED" else _HALL_PROGRESS_TIMEOUT_HOURS
            cur = conn.execute(
                "UPDATE mt_lab_task_hall SET status='QUEUED', updated_at=datetime('now','localtime'), "
                "reject_reason='超时回收: '||? WHERE id=? AND status=?",
                (f'{t["status"]} 超过 {limit_h}h 未推进', t["id"], t["status"]))
            if cur.rowcount == 1:
                recycled.append({"id": t["id"], "title": t["title"], "was": t["status"], "owner": t["claim_owner"]})
        conn.commit()
    finally:
        conn.close()
    for r in recycled:
        _hall_task_event(r["id"], "RECYCLE", "system", "system", f'{r["was"]} 超时 → 回池 QUEUED (原认领: {r["owner"]})')
        _audit("hall", "HALL_RECYCLE", r["title"][:60], r)
    return recycled


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/claim", methods=["POST"])
@_login_required
def hall_claim():
    """抢单: 并发安全 (原子 UPDATE WHERE status=DISPATCHED), 唯一赢家"""
    _ensure_claim_tables()
    u = _get_user()
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"ok": False, "error": "缺少 task_id"}), 400
    won, new_status, title, cur = _hall_transition(
        task_id, "CLAIM", u.get("username") or "?", u.get("role") or "?",
        {"claim_owner": u.get("username") or "?",
         "claim_owner_role": u.get("role") or "?",
         "claim_type": data.get("claim_type") or "self",       # self(本人)/team(代表团队)
         "claimed_at": datetime.now().isoformat(timespec="seconds")})
    if not won:
        who = cur.get("claim_owner") or "-"
        return jsonify({"ok": False, "error": f"抢单失败: 任务已被认领 (当前: {cur.get('status')}·{who})"}), 409
    _hall_ensure_deadline(task_id, _HALL_CLAIM_TIMEOUT_HOURS)
    _hall_task_event(task_id, "CLAIM", u.get("username"), u.get("role"), data.get("note") or "")
    _audit("hall", "HALL_CLAIM", title[:60], {"task_id": task_id, "owner": u.get("username")})
    try:
        from blueprints.wecom_hub_bp import wecom_push
        wecom_push("hall", "🙋 任务被抢单",
                   f"> **{title[:40]}**\n> 认领人: {u.get('username')} ({u.get('role')})\n"
                   f"> 类型: {data.get('claim_type') or 'self'} · {_HALL_CLAIM_TIMEOUT_HOURS}h 内需开工, 否则回池", operator=u.get("username"))
    except Exception:
        pass
    return jsonify({"ok": True, "task_id": task_id, "status": new_status, "owner": u.get("username"),
                    "deadline_hours": _HALL_CLAIM_TIMEOUT_HOURS,
                    "message": f"抢单成功: {title[:40]} ( {_HALL_CLAIM_TIMEOUT_HOURS}h 内开工)"})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/start", methods=["POST"])
@_login_required
def hall_start():
    """开工: 仅认领人本人"""
    _ensure_claim_tables()
    u = _get_user()
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    conn = _db()
    try:
        t = conn.execute("SELECT status, claim_owner FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not t:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if t["status"] != "CLAIMED":
        return jsonify({"ok": False, "error": f"状态非 CLAIMED (当前 {t['status']})"}), 409
    if t["claim_owner"] != u.get("username"):
        return jsonify({"ok": False, "error": f"仅认领人 {t['claim_owner']} 可开工"}), 403
    won, new_status, title, _ = _hall_transition(task_id, "START", u.get("username"), u.get("role"),
                                                 {"started_at": datetime.now().isoformat(timespec="seconds"),
                                                  "progress": "0"})
    if not won:
        return jsonify({"ok": False, "error": "状态已变化, 请刷新"}), 409
    _hall_ensure_deadline(task_id, _HALL_PROGRESS_TIMEOUT_HOURS)
    _hall_task_event(task_id, "START", u.get("username"), u.get("role"), data.get("note") or "")
    _audit("hall", "HALL_START", title[:60], {"task_id": task_id})
    return jsonify({"ok": True, "status": new_status, "deadline_hours": _HALL_PROGRESS_TIMEOUT_HOURS,
                    "message": "已开工, 交付时限 72h"})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/progress", methods=["POST"])
@_login_required
def hall_progress():
    """进度上报: 认领人本人, IN_PROGRESS 态, 顺带续期防误回收"""
    _ensure_claim_tables()
    u = _get_user()
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    pct = data.get("progress")
    try:
        pct = int(pct)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "progress 需 0-100 整数"}), 400
    if not (0 <= pct <= 100):
        return jsonify({"ok": False, "error": "progress 需 0-100 整数"}), 400
    conn = _db()
    try:
        t = conn.execute("SELECT status, claim_owner FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not t or t["status"] != "IN_PROGRESS":
        return jsonify({"ok": False, "error": "任务不在 IN_PROGRESS 态"}), 409
    if t["claim_owner"] != u.get("username"):
        return jsonify({"ok": False, "error": "仅认领人可上报进度"}), 403
    won, _, title, _ = _hall_transition(task_id, "PROGRESS", u.get("username"), u.get("role"),
                                        {"progress": str(pct),
                                         "progress_note": (data.get("note") or "")[:200],
                                         "started_at": datetime.now().isoformat(timespec="seconds")})
    if not won:
        return jsonify({"ok": False, "error": "状态已变化, 请刷新"}), 409
    _hall_task_event(task_id, "PROGRESS", u.get("username"), u.get("role"), f"{pct}% {data.get('note') or ''}")
    _audit("hall", "HALL_PROGRESS", title[:60], {"task_id": task_id, "progress": pct})
    return jsonify({"ok": True, "progress": pct})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/deliver", methods=["POST"])
@_login_required
def hall_deliver():
    """交付: 产出物摘要落库 → DELIVERED 待验收"""
    _ensure_claim_tables()
    u = _get_user()
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    deliverable = (data.get("deliverable") or "").strip()
    if not deliverable:
        return jsonify({"ok": False, "error": "交付说明 (deliverable) 不能为空"}), 400
    conn = _db()
    try:
        t = conn.execute("SELECT status, claim_owner FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not t or t["status"] not in ("IN_PROGRESS", "REWORK"):
        return jsonify({"ok": False, "error": f"任务不在可交付态 (当前 {t['status'] if t else 'N/A'})"}), 409
    if t["claim_owner"] != u.get("username"):
        return jsonify({"ok": False, "error": "仅认领人可交付"}), 403
    won, _, title, _ = _hall_transition(task_id, "DELIVER", u.get("username"), u.get("role"),
                                        {"delivered_at": datetime.now().isoformat(timespec="seconds"),
                                         "deliverable": deliverable[:4000],
                                         "progress": "100"})
    if not won:
        return jsonify({"ok": False, "error": "状态已变化, 请刷新"}), 409
    _hall_task_event(task_id, "DELIVER", u.get("username"), u.get("role"), deliverable[:200])
    _audit("hall", "HALL_DELIVER", title[:60], {"task_id": task_id, "deliverable": deliverable[:300]})
    try:
        from blueprints.wecom_hub_bp import wecom_push
        wecom_push("hall", "📦 任务交付待验收",
                   f"> **{title[:40]}**\n> 交付人: {u.get('username')}\n> 产出: {deliverable[:150]}", operator=u.get("username"))
    except Exception:
        pass
    return jsonify({"ok": True, "status": "DELIVERED", "message": "交付成功, 等待验收"})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/accept", methods=["POST"])
@_login_required
def hall_accept():
    """验收/返工: admin 及以上; REWORK 带 reason 回 IN_PROGRESS"""
    _ensure_claim_tables()
    u = _get_user()
    if u.get("role") not in ("admin", "super_admin"):
        return jsonify({"ok": False, "error": "仅 admin/super_admin 可验收"}), 403
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    decision = (data.get("decision") or "accept").strip()
    if decision not in ("accept", "rework"):
        return jsonify({"ok": False, "error": "decision 须 accept/rework"}), 400
    conn = _db()
    try:
        t = conn.execute("SELECT status, title, claim_owner FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not t or t["status"] != "DELIVERED":
        return jsonify({"ok": False, "error": f"任务不在 DELIVERED 态 (当前 {t['status'] if t else 'N/A'})"}), 409
    if decision == "accept":
        won, _, _, _ = _hall_transition(task_id, "ACCEPT", u.get("username"), u.get("role"),
                                        {"acceptor": u.get("username"),
                                         "accepted_at": datetime.now().isoformat(timespec="seconds")})
        event, note = "ACCEPT", data.get("note") or "验收通过"
        # HR 人力账: 完成
        conn = _db()
        try:
            try:
                for emp in conn.execute("SELECT employee_names FROM mt_lab_assignments WHERE hall_task_id=?", (task_id,)):
                    for nm in json.loads(emp["employee_names"] or "[]"):
                        conn.execute("INSERT INTO mt_lab_hr_log (employee_name, role, hall_task_id, action, verdict) VALUES (?,?,?,?,?)",
                                     (nm, "employee", task_id, "COMPLETE", "验收通过"))
            except Exception:
                pass
            # flow_task_hall_20261022: 验收通过即归档 (闭环终点), 并沉淀脑库
            conn.execute("UPDATE mt_lab_task_hall SET archived_at=datetime('now','localtime')"
                         " WHERE id=? AND archived_at IS NULL", (task_id,))
            conn.commit()
        finally:
            conn.close()
    else:
        reason = (data.get("reason") or "").strip()
        if not reason:
            return jsonify({"ok": False, "error": "返工必须说明 reason"}), 400
        won, _, _, _ = _hall_transition(task_id, "REWORK", u.get("username"), u.get("role"),
                                        {"reject_reason": reason[:300]})
        event, note = "REWORK", reason[:200]
    if not won:
        return jsonify({"ok": False, "error": "状态已变化, 请刷新"}), 409
    _hall_task_event(task_id, event, u.get("username"), u.get("role"), note)
    _audit("hall", "HALL_ACCEPT" if decision == "accept" else "HALL_REWORK",
           t["title"][:60], {"task_id": task_id, "decision": decision, "note": note})
    if decision == "accept":
        conn = _db()
        try:
            row = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        finally:
            conn.close()
        if row:
            _hall_feed_brain(dict(row), f"验收通过归档 | {note}")
    try:
        from blueprints.wecom_hub_bp import wecom_push
        wecom_push("hall", "✅ 任务验收通过" if decision == "accept" else "🔁 任务返工",
                   f"> **{t['title'][:40]}**\n> 决策人: {u.get('username')}\n> {note}", operator=u.get("username"))
    except Exception:
        pass
    return jsonify({"ok": True, "decision": decision,
                    "status": "DONE" if decision == "accept" else "IN_PROGRESS"})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/task")
@_login_required
def hall_task_detail():
    """任务详情: 状态机轨迹 + 生命周期字段"""
    _ensure_claim_tables()
    task_id = request.args.get("task_id")
    conn = _db()
    try:
        t = conn.execute("SELECT h.*, c.name AS center_name FROM mt_lab_task_hall h "
                         "LEFT JOIN mt_lab_centers c ON c.id=h.center_id WHERE h.id=?", (task_id,)).fetchone()
        if not t:
            return jsonify({"ok": False, "error": "任务不存在"}), 404
        events = [dict(r) for r in conn.execute(
            "SELECT event,actor,actor_role,note,created_at FROM mt_lab_task_events "
            "WHERE hall_task_id=? ORDER BY id DESC LIMIT 50", (task_id,))]
    finally:
        conn.close()
    return jsonify({"ok": True, "task": dict(t), "events": events})


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/recycle", methods=["POST"])
@_login_required
def hall_recycle_api():
    """手动/被动触发超时回收"""
    recycled = run_hall_recycle()
    return jsonify({"ok": True, "recycled": recycled, "count": len(recycled),
                    "rules": {"claim_timeout_h": _HALL_CLAIM_TIMEOUT_HOURS,
                              "progress_timeout_h": _HALL_PROGRESS_TIMEOUT_HOURS}})


# ════════════════ 五主体入驻任务大厅 (flow_hall_resident_20261020) ════════════════
# 规则/法务/人事/专家团队/Skill — 采集适配器扫真实数据源 → 去重入厅 → 分配入驻中心 → 可抢单

_RESIDENT_TAKE = 5   # 每中心单轮最多入厅条数 (防刷屏)


def _resident_center_id(conn, code):
    row = conn.execute("SELECT id FROM mt_lab_centers WHERE center_code=?", (code,)).fetchone()
    return row["id"] if row else None


def _resident_pick(conn, items):
    """去重: 同名开放任务已在厅则跳过; 截断 _RESIDENT_TAKE"""
    picked = []
    for it in items:
        if len(picked) >= _RESIDENT_TAKE:
            break
        dup = conn.execute("SELECT 1 FROM mt_lab_task_hall WHERE title=? AND status NOT IN ('DONE','FAILED') LIMIT 1",
                           (it["title"],)).fetchone()
        if not dup:
            picked.append(it)
    return picked


# ── 适配器: 每个返回 [{title, description, priority, note}], 全部本地 SQLite 零 token ──
def _resident_rules(conn):
    """规则治理: 未处置的规则违反告警 (mt_rule_violation_alert OPEN)"""
    rows = conn.execute("SELECT alert_id, violation_code, severity, description FROM mt_rule_violation_alert "
                        "WHERE alert_status='OPEN' ORDER BY alert_id DESC LIMIT 20").fetchall()
    return [{"title": f"规则违反处置: {r['violation_code'] or ('alert#' + str(r['alert_id']))}",
             "description": ((r["description"] or "")[:200] or "规则违反告警待处置"),
             "priority": "HIGH" if str(r["severity"] or "").lower() in ("high", "critical") else "NORMAL",
             "note": f"alert#{r['alert_id']}"} for r in rows]


def _resident_legal(conn):
    """法务合规: 日巡检 (在办法务任务存在则不再重复发布)"""
    dup = conn.execute("SELECT 1 FROM mt_lab_task_hall WHERE source='resident:legal' "
                       "AND status NOT IN ('DONE','FAILED') LIMIT 1").fetchone()
    if dup:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    return [{"title": f"法务合规日巡检 {today}",
             "description": "个保法/网安法/数安法/消保法合规扫描 + 敏感操作审计抽查 (法律合规规范 v1.1.0 §11 法务评审)",
             "priority": "NORMAL", "note": "daily_patrol"}]


def _resident_hr(conn):
    """人事人力: 已派工但无 COMPLETE 记录的员工交付跟进"""
    rows = conn.execute("SELECT h.employee_name, MIN(h.created_at) first_at FROM mt_lab_hr_log h "
                        "WHERE h.action='DISPATCH' AND NOT EXISTS ("
                        "  SELECT 1 FROM mt_lab_hr_log c WHERE c.employee_name=h.employee_name AND c.action='COMPLETE') "
                        "GROUP BY h.employee_name ORDER BY first_at LIMIT 20").fetchall()
    return [{"title": f"人力跟进: {r['employee_name']} 交付确认",
             "description": f"员工 {r['employee_name']} 已派工但无 COMPLETE 记录, 需跟进任务交付/验收状态",
             "priority": "NORMAL", "note": f"dispatched_at={r['first_at']}"} for r in rows]


def _resident_expert(conn):
    """专家团队: EigenFlux 在册专家心跳失联 >24h 的连线修复"""
    rows = conn.execute("SELECT employee_name, employee_type, last_heartbeat FROM eigenflux_registrations "
                        "WHERE registration_status='ACTIVE' AND (last_heartbeat IS NULL OR last_heartbeat < "
                        "datetime('now','localtime','-24 hours')) ORDER BY last_heartbeat LIMIT 20").fetchall()
    return [{"title": f"专家连线修复: {r['employee_name']}",
             "description": f"{r['employee_type'] or 'expert'} 心跳失联 (last={r['last_heartbeat'] or 'NULL'}), 需重连/重邀/除名评估",
             "priority": "NORMAL", "note": "eigenflux_stale_24h"} for r in rows]


def _resident_skill(conn):
    """Skill 研发: 衍生引擎产出的 PROPOSED 候选 (daemon↔skill 双向)"""
    rows = conn.execute("SELECT id, kind, subject, reason FROM mt_lab_suggestions "
                        "WHERE status='PROPOSED' ORDER BY id DESC LIMIT 20").fetchall()
    kind_cn = {"daemon_to_skill": "daemon补Skill", "skill_to_daemon": "Skill反哺daemon"}
    return [{"title": f"Skill研发: {kind_cn.get(r['kind'], r['kind'])} · {r['subject']}",
             "description": (r["reason"] or "")[:200] or f"候选 #{r['id']} 待研发",
             "priority": "NORMAL", "note": f"suggestion#{r['id']}"} for r in rows]


_RESIDENT_ADAPTERS = {
    "rules_gov": _resident_rules,
    "legal": _resident_legal,
    "hr_center": _resident_hr,
    "expert_team": _resident_expert,
    "skill_dev": _resident_skill,
}


def run_hall_residents():
    """五主体入驻巡检: 采集→去重→入厅→分配到入驻中心 (DISPATCHED 可抢单)"""
    _ensure_claim_tables()
    created, skipped = [], {}
    conn = _db()
    try:
        for code, adapter in _RESIDENT_ADAPTERS.items():
            try:
                items = adapter(conn)
            except Exception as e:
                skipped[code] = f"adapter_err: {e}"
                continue
            picked = _resident_pick(conn, items)
            skipped[code] = max(0, len(items) - len(picked))
            cid = _resident_center_id(conn, code)
            for it in picked:
                cur = conn.execute(
                    "INSERT INTO mt_lab_task_hall (title,description,source,priority,status,center_id,dispatched_at) "
                    "VALUES (?,?,?,?, 'DISPATCHED', ?, datetime('now','localtime'))",
                    (it["title"][:120], it["description"][:500], f"resident:{code}", it["priority"], cid))
                # 同连接内插事件 (外层有未提交写, 另开连接会撞 SQLite 库级写锁)
                conn.execute("INSERT INTO mt_lab_task_events (hall_task_id,event,actor,actor_role,note) VALUES (?,?,?,?,?)",
                             (cur.lastrowid, "DISPATCH", f"resident:{code}", "system", (it.get("note") or "")[:300]))
                created.append({"id": cur.lastrowid, "title": it["title"], "resident": code})
        conn.commit()
    finally:
        conn.close()
    if created:
        _audit("hall", "HALL_RESIDENT", f"入驻巡检入厅{len(created)}项", {"created": created, "skipped": skipped})
    return {"created": created, "created_count": len(created), "skipped": skipped}


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/residents", methods=["GET", "POST"])
@_login_required
def hall_residents():
    """五主体入驻: GET=入驻状态总览; POST=跑一轮入驻巡检采集入厅"""
    if request.method == "POST":
        result = run_hall_residents()
        return jsonify({"ok": True, **result})
    _ensure_claim_tables()
    conn = _db()
    try:
        residents = []
        for code, name, domain, _kws in _RESIDENT_CENTERS:
            cid = _resident_center_id(conn, code)
            open_n = done_n = 0
            if cid:
                open_n = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE center_id=? AND status NOT IN ('DONE','FAILED')",
                                      (cid,)).fetchone()[0]
                done_n = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE center_id=? AND status='DONE'",
                                      (cid,)).fetchone()[0]
            residents.append({"code": code, "name": name, "domain": domain,
                              "center_id": cid, "open_tasks": open_n, "done_tasks": done_n})
        sources = {
            "rules_open_alerts": conn.execute("SELECT count(*) FROM mt_rule_violation_alert WHERE alert_status='OPEN'").fetchone()[0],
            "skill_proposed": conn.execute("SELECT count(*) FROM mt_lab_suggestions WHERE status='PROPOSED'").fetchone()[0],
            "hr_overdue": conn.execute("SELECT count(*) FROM (SELECT DISTINCT h.employee_name FROM mt_lab_hr_log h "
                                       "WHERE h.action='DISPATCH' AND NOT EXISTS (SELECT 1 FROM mt_lab_hr_log c "
                                       "WHERE c.employee_name=h.employee_name AND c.action='COMPLETE'))").fetchone()[0],
            "expert_stale": conn.execute("SELECT count(*) FROM eigenflux_registrations WHERE registration_status='ACTIVE' "
                                         "AND (last_heartbeat IS NULL OR last_heartbeat < datetime('now','localtime','-24 hours'))").fetchone()[0],
        }
    finally:
        conn.close()
    return jsonify({"ok": True, "residents": residents, "sources": sources})


# ════════════════ AI 自动接单·组队·委派专家·自动交付 (flow_hall_resident_20261020) ════════════════
_HALL_AUTO_WORKER = "ai_auto_worker"      # 自动接单虚拟工作者
_HALL_AUTO_TEAM_SIZE = 3                  # 每单 AI 员工数


def _hall_auto_pick_team(conn, center_id):
    """按中心领域关键词匹配 AI 员工 3 人 + 教授分身 1 人 (纯本地, 零 token)"""
    kws = []
    if center_id:
        row = conn.execute("SELECT keywords, domain FROM mt_lab_centers WHERE id=?", (center_id,)).fetchone()
        if row:
            kws = [k.strip() for k in (row["keywords"] or row["domain"] or "").split(",") if k.strip()]
    emps, seen = [], set()
    for kw in kws[:6]:
        like = f"%{kw}%"
        for r in conn.execute("SELECT name FROM ai_employees WHERE is_enabled=1 AND "
                              "(specialties LIKE ? OR description LIKE ? OR name LIKE ?) LIMIT 4", (like, like, like)):
            if r["name"] not in seen:
                seen.add(r["name"]); emps.append(r["name"])
            if len(emps) >= _HALL_AUTO_TEAM_SIZE:
                break
        if len(emps) >= _HALL_AUTO_TEAM_SIZE:
            break
    if len(emps) < _HALL_AUTO_TEAM_SIZE:   # 兜底: 任意在职员工补齐
        for r in conn.execute("SELECT name FROM ai_employees WHERE is_enabled=1 LIMIT 6"):
            if r["name"] not in seen:
                seen.add(r["name"]); emps.append(r["name"])
            if len(emps) >= _HALL_AUTO_TEAM_SIZE:
                break
    prof = conn.execute("SELECT name FROM ai_employees WHERE is_enabled=1 AND name IN "
                        f"({','.join('?' for _ in _PROFESSOR_HINTS)}) LIMIT 1", _PROFESSOR_HINTS).fetchone()
    return emps[:_HALL_AUTO_TEAM_SIZE] or ["通用执行员"], (prof["name"] if prof else _PROFESSOR_HINTS[0])


def _hall_auto_pick_experts(conn, center_id):
    """委派 EigenFlux 专家: 按中心领域匹配, 战力分优先, 取 2 名"""
    domain = ""
    if center_id:
        row = conn.execute("SELECT domain FROM mt_lab_centers WHERE id=?", (center_id,)).fetchone()
        domain = (row["domain"] if row else "") or ""
    like = f"%{domain[:4]}%"
    experts = [r["name"] for r in conn.execute(
        "SELECT name FROM eigenflux_experts WHERE (domain LIKE ? OR domain_cn LIKE ? OR skills LIKE ?) "
        "ORDER BY performance_score DESC LIMIT 2", (like, like, like))]
    if not experts:
        experts = [r["name"] for r in conn.execute(
            "SELECT name FROM eigenflux_experts ORDER BY performance_score DESC LIMIT 2")]
    return experts


def _hall_auto_work_one(task_id, title, center_id):
    """单任务自动闭环: 抢单→组队→委派专家磋商→HR记帐→开工→交付(待验收)"""
    won, _, _, _ = _hall_transition(
        task_id, "CLAIM", _HALL_AUTO_WORKER, "ai_team",
        {"claim_owner": _HALL_AUTO_WORKER, "claim_owner_role": "ai_team", "claim_type": "team",
         "claimed_at": datetime.now().isoformat(timespec="seconds")})
    if not won:
        return None
    _hall_task_event(task_id, "CLAIM", _HALL_AUTO_WORKER, "ai_team", "AI 自动接单 (auto-work)")

    conn = _db()
    try:
        emps, prof = _hall_auto_pick_team(conn, center_id)
        experts = _hall_auto_pick_experts(conn, center_id)
        verdict = f"{experts[0] if experts else '首席专家'} 表决: 方案可行, 由 {'、'.join(emps)} 执行, {prof} 导师把关"
        cur = conn.execute(
            "INSERT INTO mt_lab_assignments (suggestion_id, center_id, employee_names, professor_names, "
            "expert_verdict, status, hall_task_id) VALUES (0, ?, ?, ?, ?, 'CLAIMED', ?)",
            (center_id, json.dumps(emps, ensure_ascii=False), json.dumps([prof], ensure_ascii=False),
             verdict, task_id))
        aid = cur.lastrowid
        # 磋商留痕 (本地规则化观点, 零 token)
        for i, spk in enumerate(emps[:2]):
            conn.execute("INSERT INTO mt_lab_deliberations (assignment_id, round_no, speaker, role, viewpoint, vote) "
                         "VALUES (?,?,?, 'employee', ?, 'APPROVE')",
                         (aid, 1, spk, f"认领任务「{title[:30]}」, 按中心工作流拆解执行"))
        if experts:
            conn.execute("INSERT INTO mt_lab_deliberations (assignment_id, round_no, speaker, role, viewpoint, vote) "
                         "VALUES (?,?,?, 'expert', ?, 'APPROVE')",
                         (aid, 1, experts[0], f"专家评审通过: 风险可控, 建议交付时限 {72}h 内"))
        for emp in emps:
            conn.execute("INSERT INTO mt_lab_hr_log (employee_name, role, hall_task_id, action, verdict) "
                         "VALUES (?, 'employee', ?, 'DISPATCH', 'AI自动接单派工')", (emp, task_id))
        conn.commit()
    finally:
        conn.close()

    _hall_transition(task_id, "START", _HALL_AUTO_WORKER, "ai_team",
                     {"started_at": datetime.now().isoformat(timespec="seconds"), "progress": "0"})
    _hall_ensure_deadline(task_id, _HALL_PROGRESS_TIMEOUT_HOURS)
    _hall_task_event(task_id, "START", _HALL_AUTO_WORKER, "ai_team", f"团队 {'、'.join(emps)} · 专家 {'、'.join(experts)}")

    deliverable = (f"AI 团队自动执行产出: 团队 {len(emps)} 人 ({'、'.join(emps)}), 导师 {prof}, "
                   f"委派专家 {('、'.join(experts)) or '首席专家'} 磋商通过。"
                   f"针对「{title[:40]}」完成分析、拆解与方案 v1 交付, 待人工验收。")
    won, _, _, _ = _hall_transition(task_id, "DELIVER", _HALL_AUTO_WORKER, "ai_team",
                                    {"delivered_at": datetime.now().isoformat(timespec="seconds"),
                                     "deliverable": deliverable[:4000], "progress": "100"})
    _hall_task_event(task_id, "DELIVER", _HALL_AUTO_WORKER, "ai_team", "AI 自动交付, 待验收")
    _audit("hall", "HALL_AUTO_WORK", title[:60],
           {"task_id": task_id, "team": emps, "professor": prof, "experts": experts})
    try:
        from blueprints.wecom_hub_bp import wecom_push
        wecom_push("hall", "🤖 AI 自动接单并交付",
                   f"> **{title[:40]}**\n> 团队: {'、'.join(emps)} · 导师: {prof}\n"
                   f"> 专家: {'、'.join(experts) or '首席专家'} 磋商通过\n> 已交付, 待验收", operator=_HALL_AUTO_WORKER)
    except Exception:
        pass
    return {"task_id": task_id, "title": title[:60], "team": emps, "professor": prof,
            "experts": experts, "status": "DELIVERED"}


def run_hall_auto_work(max_tasks=2):
    """AI 自动接单引擎: 取 DISPATCHED (HIGH 优先) 逐单自动闭环 → 交付待验收"""
    _ensure_claim_tables()
    conn = _db()
    try:
        tasks = [dict(r) for r in conn.execute(
            "SELECT id, title, center_id FROM mt_lab_task_hall WHERE status='DISPATCHED' "
            "ORDER BY CASE priority WHEN 'HIGH' THEN 0 ELSE 1 END, id LIMIT ?", (int(max_tasks),))]
    finally:
        conn.close()
    worked = []
    for t in tasks:
        r = _hall_auto_work_one(t["id"], t["title"], t["center_id"])
        if r:
            worked.append(r)
    return {"worked": worked, "worked_count": len(worked), "candidates": len(tasks)}


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/auto-work", methods=["GET", "POST"])
@_login_required
def hall_auto_work():
    """AI 自动接单: GET=状态总览; POST=跑一轮自动接单 (抢单→组队→委派专家→交付待验收)"""
    if request.method == "POST":
        max_tasks = min(int((request.get_json(silent=True) or {}).get("max_tasks", 2) or 2), 10)
        result = run_hall_auto_work(max_tasks)
        return jsonify({"ok": True, **result})
    _ensure_claim_tables()
    conn = _db()
    try:
        queued = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE status='DISPATCHED'").fetchone()[0]
        mine_open = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE claim_owner=? AND status NOT IN ('DONE','FAILED')",
                                 (_HALL_AUTO_WORKER,)).fetchone()[0]
        mine_done = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE claim_owner=? AND status='DONE'",
                                 (_HALL_AUTO_WORKER,)).fetchone()[0]
        delivered = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE claim_owner=? AND status='DELIVERED'",
                                 (_HALL_AUTO_WORKER,)).fetchone()[0]
    finally:
        conn.close()
    return jsonify({"ok": True, "worker": _HALL_AUTO_WORKER, "dispatched_waiting": queued,
                    "mine_open": mine_open, "mine_delivered": delivered, "mine_done": mine_done})


# ════════════════ 各中心自动委派能力提升任务 (flow_hall_delegate_20261020) ════════════════
# 中心自查能力短板 (本地 SQL 零 token) → 自动生成提升任务入厅 → AI 自动接单提升自身能力
_DELEGATE_COOLDOWN_HOURS = 24   # 同中心 24h 内不重复委派


def _dg_daemon_ops(conn):
    n = conn.execute("SELECT count(*) FROM mt_daemon_registry WHERE status='FAILED'").fetchone()[0]
    if not n:
        return None
    return f"daemon 修复能力提升 ({n} 个 FAILED 待练手)", f"当前 {n} 个 FAILED daemon, 修复实战可提升中心运维能力", "HIGH"


def _dg_security_audit(conn):
    n = conn.execute("SELECT count(*) FROM mt_rule_violation_alert WHERE alert_status='OPEN'").fetchone()[0]
    if not n:
        return None
    return f"安全审计复盘能力提升 ({n} 条 OPEN 告警样本)", f"{n} 条规则违反告警可作审计复盘实战样本", "HIGH"


def _dg_dev_flow(conn):
    n = conn.execute("SELECT count(*) FROM mt_dev_flow_session WHERE final_status='OPEN' AND current_step='STEP_7_EXECUTE'").fetchone()[0]
    if n < 2:
        return None
    return f"开发流程并行能力提升 ({n} 个 OPEN flow)", f"{n} 个进行中 flow, 可演练并行 flow 编排与收尾能力", "NORMAL"


def _dg_ai_engine(conn):
    n = conn.execute("SELECT count(*) FROM mt_ai_brain_feed_log WHERE created_at < datetime('now','localtime','-24 hours')").fetchone()[0]
    if n:
        return None  # 24h 内有投喂 → 能力在线
    return "AI 脑库投喂量提升", "近 24h 脑库零投喂, 委派任务复盘近期经验充实脑库", "NORMAL"


def _dg_workflow(conn):
    n = conn.execute("SELECT count(*) FROM mt_lab_suggestions WHERE status='PROPOSED'").fetchone()[0]
    if n < 3:
        return None
    return f"工作流消化提速 ({n} 个候选积压)", f"{n} 个候选待消化, 委派流水线提效演练", "NORMAL"


def _dg_data_research(conn):
    n = conn.execute("SELECT count(*) FROM mt_lab_audit_log WHERE created_at > datetime('now','localtime','-24 hours')").fetchone()[0]
    if n >= 10:
        return None
    return "审计数据利用率提升", f"近 24h 仅 {n} 条中心操作留痕, 委派数据画像与利用率分析", "NORMAL"


def _dg_edu_qbank(conn):
    q = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='mt_edu_sync_question_types'").fetchone()[0]
    if not q:
        return None
    n = conn.execute("SELECT count(*) FROM mt_edu_sync_question_types").fetchone()[0]
    if n >= 7:
        return None
    return "教辅题库扩充能力提升", f"教辅题型 {n}/7 未满编, 委派题型与母题扩充", "NORMAL"


def _dg_rules_gov(conn):
    n = conn.execute("SELECT count(*) FROM mt_rule_changelog WHERE created_at > datetime('now','localtime','-7 days')").fetchone()[0]
    if n:
        return None
    return "规则治理活跃度提升", "近 7 天零规则变更, 委派规则体检与 changelog 补录演练", "NORMAL"


def _dg_legal(conn):
    return None  # 法务日巡检已由 resident:legal 常驻, 不重复委派


def _dg_hr_center(conn):
    n = conn.execute("SELECT count(*) FROM ai_employees WHERE is_enabled=0").fetchone()[0]
    if n < 5:
        return None
    return f"员工状态治理能力提升 ({n} 人停用)", f"{n} 名 AI 员工停用, 委派名册治理与复编评估", "NORMAL"


def _dg_expert_team(conn):
    n = conn.execute("SELECT count(*) FROM eigenflux_experts").fetchone()[0]
    if n >= 10:
        return None
    return f"专家队伍扩编 (当前 {n} 人)", f"EigenFlux 专家 {n}<10, 委派专家招募与连线扩编", "NORMAL"


def _dg_skill_dev(conn):
    daemons = conn.execute("SELECT count(*) FROM mt_daemon_registry").fetchone()[0]
    if os.path.isdir(SKILLS_DIR):
        skills = len([d for d in os.listdir(SKILLS_DIR) if os.path.isdir(os.path.join(SKILLS_DIR, d))])
    else:
        skills = 0
    if skills >= daemons:
        return None
    return f"Skill 覆盖率提升 ({skills} skills / {daemons} daemons)", f"Skill({skills}) 少于 daemon({daemons}), 委派缺失 skill 补编", "NORMAL"


def _dg_frontend_design(conn):
    return None  # 无低成本本地信号, 暂不委派


_CENTER_DELEGATE_CHECKS = {
    "daemon_ops": _dg_daemon_ops, "security_audit": _dg_security_audit, "dev_flow": _dg_dev_flow,
    "ai_engine": _dg_ai_engine, "workflow": _dg_workflow, "data_research": _dg_data_research,
    "frontend_design": _dg_frontend_design, "edu_qbank": _dg_edu_qbank,
    "rules_gov": _dg_rules_gov, "legal": _dg_legal, "hr_center": _dg_hr_center,
    "expert_team": _dg_expert_team, "skill_dev": _dg_skill_dev,
}


def run_hall_center_delegations():
    """各中心自动委派: 自查能力短板 → 24h 去重 → 生成提升任务入厅 (DISPATCHED 可被 AI 接单)"""
    _ensure_claim_tables()
    created, idle, cooled = [], [], []
    conn = _db()
    try:
        for code, check in _CENTER_DELEGATE_CHECKS.items():
            center = conn.execute("SELECT id, name FROM mt_lab_centers WHERE center_code=?", (code,)).fetchone()
            if not center:
                continue
            # 24h 冷却: 同中心在办/近期委派不重复
            recent = conn.execute(
                "SELECT 1 FROM mt_lab_task_hall WHERE source=? AND status NOT IN ('DONE','FAILED') LIMIT 1",
                (f"center:{code}",)).fetchone()
            if recent:
                cooled.append(code)
                continue
            try:
                gap = check(conn)
            except Exception:
                gap = None
            if not gap:
                idle.append(code)
                continue
            title, desc, prio = gap
            cur = conn.execute(
                "INSERT INTO mt_lab_task_hall (title,description,source,priority,status,center_id,dispatched_at) "
                "VALUES (?,?,?,?,'DISPATCHED',?,datetime('now','localtime'))",
                (f"{center['name']}: {title}"[:120], desc[:500], f"center:{code}", prio, center["id"]))
            conn.execute("INSERT INTO mt_lab_task_events (hall_task_id,event,actor,actor_role,note) VALUES (?,?,?,?,?)",
                         (cur.lastrowid, "DISPATCH", f"center:{code}", "system", "中心自动委派(能力提升)"))
            created.append({"id": cur.lastrowid, "center": code, "title": f"{center['name']}: {title}", "priority": prio})
        conn.commit()
    finally:
        conn.close()
    if created:
        _audit("hall", "HALL_CENTER_DELEGATE", f"中心自动委派{len(created)}项", {"created": created, "idle": idle, "cooldown": cooled})
    return {"created": created, "created_count": len(created), "idle": idle, "cooldown": cooled}


@daemon_skill_lab_bp.route("/api/daemon-lab/hall/center-delegate", methods=["GET", "POST"])
@_login_required
def hall_center_delegate():
    """中心自动委派: GET=13中心自查总览; POST=跑一轮委派 (能力短板→任务入厅)"""
    if request.method == "POST":
        result = run_hall_center_delegations()
        return jsonify({"ok": True, **result})
    _ensure_claim_tables()
    conn = _db()
    try:
        overview = []
        for code, check in _CENTER_DELEGATE_CHECKS.items():
            center = conn.execute("SELECT id, name FROM mt_lab_centers WHERE center_code=?", (code,)).fetchone()
            if not center:
                continue
            open_n = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE source=? AND status NOT IN ('DONE','FAILED')",
                                  (f"center:{code}",)).fetchone()[0]
            done_n = conn.execute("SELECT count(*) FROM mt_lab_task_hall WHERE source=? AND status='DONE'",
                                  (f"center:{code}",)).fetchone()[0]
            overview.append({"code": code, "name": center["name"], "open_delegations": open_n, "done_delegations": done_n})
    finally:
        conn.close()
    return jsonify({"ok": True, "centers": overview})


@daemon_skill_lab_bp.route("/api/daemon-lab/audit")
@_login_required
def lab_audit_query():
    """统一审计查询 (flow_audit_20261020): 回溯追责入口 — 支持操作者/中心/动作过滤"""
    _ensure_claim_tables()
    limit = min(int(request.args.get("limit", 50) or 50), 200)
    operator = request.args.get("operator", "").strip()
    center = request.args.get("center", "").strip()
    action = request.args.get("action", "").strip()
    conds, args = [], []
    if operator:
        conds.append("operator LIKE ?")
        args.append(f"%{operator}%")
    if center:
        conds.append("center = ?")
        args.append(center)
    if action:
        conds.append("action LIKE ?")
        args.append(f"%{action}%")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM mt_lab_audit_log {where} ORDER BY id DESC LIMIT ?", args + [limit])]
        total = conn.execute(f"SELECT count(*) FROM mt_lab_audit_log {where}", args).fetchone()[0]
        by_action = {r["action"]: r["n"] for r in conn.execute(
            "SELECT action, count(*) n FROM mt_lab_audit_log GROUP BY action")}
        by_operator = {r["operator"]: r["n"] for r in conn.execute(
            "SELECT operator, count(*) n FROM mt_lab_audit_log GROUP BY operator ORDER BY n DESC LIMIT 10")}
        return jsonify({"ok": True, "total": total, "by_action": by_action,
                        "by_operator": by_operator, "items": rows})
    finally:
        conn.close()


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
        # 审计 (flow_audit_20261020): 认领操作入库入日志
        _audit("lab", "AUTO_CLAIM", f"{len(results)}项候选认领",
               {"count": len(results),
                "items": [{"subject": r["subject"], "center": r["center"],
                           "employees": r["employees"], "professors": r["professors"],
                           "verdict": r["verdict"]} for r in results]})
        # 企微中枢 (flow_wecom_20261020): 认领结果推送
        try:
            from blueprints.wecom_hub_bp import wecom_push
            if results:
                md = "\n".join(f"- **{r['subject'][:30]}** → {r['center']} [{r['verdict'][:10]}]" for r in results[:8])
                wecom_push("lab", "🔬 研发中心 · 自动认领播报", md)
        except Exception:
            pass
        return jsonify({"ok": True, "claimed": len(results), "results": results})
    except Exception as e:
        _audit("lab", "AUTO_CLAIM", "FAILED", {"error": str(e)})
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


# ════════════════════════════════════════════════════════════════
# Phase 2: 研究院觉醒 — 自动组建测试团队 + 交付任务大厅
# Phase 3: AI HR 智能匹配 — 没团队自动从 HR pool 拉人
# Phase 4: Skill 自动衍生闭环 — 做完任务提炼成 skill
# flow_test_gold_team_20261023
# ════════════════════════════════════════════════════════════════

GOLD_TEST_TEAM = "🧪 专业测试30年金牌天团"

# ── 研究院觉醒触发源 ──
_AWAKEN_TRIGGERS = [
    # (触发源类型, 查询 SQL, 觉醒理由模板)
    ("daemon_failure",
     "SELECT id, process_name, current_state FROM mt_daemon_registry WHERE current_state IN ('FAILED','STOPPED')",
     "Daemon {{process_name}} 状态 {{current_state}}, 需金牌天团介入专项测试"),
    ("high_priority_task",
     "SELECT id, title FROM mt_lab_task_hall WHERE priority='HIGH' AND status IN ('QUEUED','PENDING')",
     "高优先级任务 #{{id}} {{title}} 待派发, 金牌天团自动请缨"),
    ("no_team_match",
     "SELECT id, title FROM mt_lab_task_hall WHERE status='QUEUED' AND id NOT IN (SELECT hall_task_id FROM mt_lab_assignments)",
     "任务大厅有未分配任务, AI HR 自动组建测试团队认领"),
    # flow_daemon_skill_lab 自动巡检: 建议队列 PROPOSED
    ("suggestion_queue",
     "SELECT id, subject, reason FROM mt_lab_suggestions WHERE status='PROPOSED' LIMIT 5",
     "衍生建议 #{{id}} {{subject}} 需金牌天团评估"),
]

# 任务类型 → 需要的测试角色映射
_TASK_TYPE_TO_TEST_ROLES = {
    "security": ["SEC_QA", "AI_QA", "REVIEW_QA"],
    "perf":     ["PERF_QA", "REL_QA", "CHIEF_QA"],
    "api":      ["API_QA", "AUTO_QA", "REVIEW_QA"],
    "ui":       ["UI_QA", "QA_EDU", "REVIEW_QA"],
    "ai":       ["AI_QA", "AUTO_QA", "CHIEF_QA"],
    "db":       ["PERF_QA", "REL_QA"],
    "general":  ["AUTO_QA", "REVIEW_QA", "CHIEF_QA"],
}


def _match_task_type(text):
    """从任务文本推断测试类型 (本地关键词匹配, 零 token)"""
    t = text.lower()
    if any(k in t for k in ["安全", "security", "vikey", "审计", "auth", "权限", "漏洞", "encrypt"]):
        return "security"
    if any(k in t for k in ["性能", "perf", "压力", "latency", "throughput", "cpu", "内存"]):
        return "perf"
    if any(k in t for k in ["api", "接口", "endpoint", "flask", "route", "blueprint"]):
        return "api"
    if any(k in t for k in ["ui", "前端", "页面", "css", "html", "渲染", "布局"]):
        return "ui"
    if any(k in t for k in ["ai", "llm", "ollama", "agent", "脑库", "推理", "model"]):
        return "ai"
    if any(k in t for k in ["db", "数据库", "sqlite", "dba", "表", "column", "wal"]):
        return "db"
    return "general"


def _gold_team_roster(roles_needed=None):
    """从金牌天团拉人, 按需要的角色过滤"""
    conn = _db()
    try:
        if roles_needed:
            placeholders = ",".join("?" * len(roles_needed))
            rows = conn.execute(
                f"SELECT member_name, skill_level, capabilities FROM mt_team_members "
                f"WHERE team_name=? AND skill_level IN ({placeholders})",
                (GOLD_TEST_TEAM, *roles_needed)).fetchall()
        else:
            rows = conn.execute(
                "SELECT member_name, skill_level, capabilities FROM mt_team_members "
                "WHERE team_name=?", (GOLD_TEST_TEAM,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _auto_form_test_roster(task_text):
    """Phase 3: AI HR 智能组建 — 没匹配到团队时自动从金牌天团拉人"""
    test_type = _match_task_type(task_text)
    roles_needed = _TASK_TYPE_TO_TEST_ROLES.get(test_type, ["AUTO_QA", "REVIEW_QA"])
    # 先从金牌天团找
    members = _gold_team_roster(roles_needed)
    if not members:
        # 金牌天团没有完全匹配 → 扩展到其他天团 (AI HR "挖人")
        conn = _db()
        try:
            extra = conn.execute(
                "SELECT member_name, skill_level, capabilities FROM mt_team_members "
                "WHERE team_name IN ('🧪 测试巡检天团','⚖️ 合规安全天团','🏛️ 架构天团','🔧 运维修复天团') "
                "AND team_name != ? LIMIT 3",
                (GOLD_TEST_TEAM,)).fetchall()
            members = [dict(r) for r in extra]
        finally:
            conn.close()
    return {"members": members, "test_type": test_type, "roles_needed": roles_needed}


# ── Phase 2: 研究院觉醒 daemon ──
def run_test_gold_team_auto():
    """
    研究院觉醒入口 (可被 cron/daemon 调用)
    1. 扫描 4 种触发源 → 生成本地测试任务
    2. 金牌天团自动认领 → 交付任务大厅
    3. AI HR 自动派发 → 没匹配自动组队
    4. 任务完成 → 自动提炼 skill 并注册
    """
    awakening_events = []
    conn = _db()
    try:
        conn.execute(_LAB_TABLE_SQL)
        conn.execute(_ensure_claim_tables.__code__.co_consts[0] if hasattr(_ensure_claim_tables, '__code__') else "")
    except Exception:
        pass

    ingested = 0
    dispatched = 0
    formed = 0

    try:
        for trigger_type, sql, reason_tpl in _AWAKEN_TRIGGERS:
            try:
                rows = conn.execute(sql).fetchall()
            except sqlite3.Error:
                continue
            for r in rows:
                rdict = dict(r)
                # 生成觉醒理由
                reason = reason_tpl
                for k, v in rdict.items():
                    reason = reason.replace("{{" + k + "}}", str(v))
                # 检查是否已入厅
                existing = conn.execute(
                    "SELECT 1 FROM mt_lab_task_hall WHERE source=? AND source_id=?",
                    (trigger_type, rdict.get("id"))).fetchone()
                if existing:
                    continue
                # 自动生成测试任务
                title = f"[🏆金牌测试] {rdict.get('subject') or rdict.get('title') or reason[:40]}"
                conn.execute(
                    "INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority,status,task_type,claim_owner,claim_owner_role) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (title, reason, trigger_type, rdict.get("id"),
                     "HIGH" if trigger_type in ("daemon_failure", "high_priority_task") else "NORMAL",
                     "QUEUED", "test", GOLD_TEST_TEAM, "gold_qa_team"))
                ingested += 1
                awakening_events.append({"trigger": trigger_type, "title": title})
        conn.commit()
    finally:
        conn.close()

    # 第二轮: 对 QUEUED 且 claim_owner=金牌天团 的任务自动派发
    conn = _db()
    try:
        queued = conn.execute(
            "SELECT id, title, description FROM mt_lab_task_hall "
            "WHERE status='QUEUED' AND claim_owner=?",
            (GOLD_TEST_TEAM,)).fetchall()
        for t in queued:
            task_text = f"{t['title']} {t['description'] or ''}"
            formed_result = _auto_form_test_roster(task_text)
            if formed_result["members"]:
                formed += 1
                verdict = f"🏆金牌天团自动组队: {len(formed_result['members'])}人, 类型={formed_result['test_type']}, 角色={formed_result['roles_needed']}"
                conn.execute(
                    "UPDATE mt_lab_task_hall SET status='DISPATCHED', verdict=?, dispatched_at=datetime('now','localtime') WHERE id=?",
                    (verdict, t["id"]))
                dispatched += 1
                # HR 日志
                for m in formed_result["members"]:
                    conn.execute(
                        "INSERT INTO mt_lab_hr_log (employee_name, role, hall_task_id, action, verdict) VALUES (?,?,?,?,?)",
                        (m["member_name"], "gold_qa", t["id"], "GOLD_TEAM_CLAIM", verdict))
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True, "trigger": "run_test_gold_team_auto",
        "ingested": ingested, "dispatched": dispatched, "formed": formed,
        "events": awakening_events[:20],
        "gold_team": GOLD_TEST_TEAM,
        "gold_size": len(_gold_team_roster()),
    }


# ── Phase 4: Skill 自动衍生闭环 ──
def _auto_derive_skill_from_task(task_id):
    """
    任务完成后 → 自动提炼可复用 skill → 注册到 mt_skill_registry
    触发条件: mt_lab_task_hall.acceptor IS NOT NULL (已验收)
    """
    conn = _db()
    try:
        task = conn.execute(
            "SELECT id, title, description, verdict, status, deliverable, acceptor, accepted_at "
            "FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        if not task or not task["acceptor"]:
            return {"ok": False, "reason": "task not accepted"}

        # 从 verdict + deliverable 提取关键词 → skill 命名
        title = task["title"]
        verdict = task["verdict"] or ""
        deliverable = task["deliverable"] or ""
        text = f"{title} {verdict} {deliverable}"

        # 推断 skill 分类 (复用 _match_task_type 逻辑 + 关键词)
        skill_type_map = {
            "security": ("SECURITY_TEST", "安全测试 Skill", "security_audit"),
            "perf":     ("PERF_TEST", "性能测试 Skill", "performance"),
            "api":      ("API_TEST", "接口测试 Skill", "api_contract"),
            "ui":       ("UI_TEST", "UI测试 Skill", "ui_regression"),
            "ai":       ("AI_TEST", "AI智能体测试 Skill", "llm_qa"),
            "db":       ("DB_TEST", "数据库测试 Skill", "db_integrity"),
            "general":  ("TEST_GENERAL", "通用测试 Skill", "qa_general"),
        }
        ttype = _match_task_type(text)
        skill_id, skill_name, category = skill_type_map.get(ttype, skill_type_map["general"])

        # 检查是否已存在 (去重)
        existing = conn.execute(
            "SELECT 1 FROM mt_skill_registry WHERE name=? OR skill_id=?",
            (skill_name, f"{skill_id}_{task_id}")).fetchone()
        if existing:
            return {"ok": True, "skill_id": f"{skill_id}_{task_id}", "note": "already exists, skip"}

        # 提炼 skill 描述 (从 verdict 提炼)
        import hashlib
        skill_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        full_skill_id = f"{skill_id}_{task_id}_{skill_hash}"
        skill_desc = verdict[:200] if verdict else f"从任务 #{task_id} 自动衍生的 {skill_name}"
        tags = json.dumps([ttype, "auto_derived", "gold_30y", f"task_{task_id}"], ensure_ascii=False)

        conn.execute("""CREATE TABLE IF NOT EXISTS mt_skill_registry (
            skill_id TEXT PRIMARY KEY, name TEXT, category TEXT, description TEXT,
            level TEXT DEFAULT 'intermediate', icon TEXT, tags_json TEXT,
            module_path TEXT, entry_func TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')))""")

        conn.execute(
            "INSERT INTO mt_skill_registry (skill_id, name, category, description, level, tags_json) "
            "VALUES (?,?,?,?,?,?)",
            (full_skill_id, skill_name, category, skill_desc, "intermediate", tags))

        # 审计日志
        conn.execute(
            "INSERT INTO mt_lab_audit_log (center, action, subject, detail) VALUES (?,?,?,?)",
            ("skill_dev", "AUTO_SKILL_DERIVED", full_skill_id,
             json.dumps({"task_id": task_id, "source": "gold_30y_skill_derive", "ttype": ttype}, ensure_ascii=False)))
        conn.commit()
        return {"ok": True, "skill_id": full_skill_id, "skill_name": skill_name, "category": category}
    finally:
        conn.close()


# ── 额外: 批量衍生所有已完成但未提炼 skill 的任务 ──
def run_skill_derive_all():
    """跑一遍所有已验收任务 → 批量衍生 skill"""
    conn = _db()
    derived = []
    try:
        accepted = conn.execute(
            "SELECT id FROM mt_lab_task_hall WHERE acceptor IS NOT NULL AND status IN ('DONE','ACCEPTED') "
            "ORDER BY accepted_at DESC LIMIT 20").fetchall()
        for t in accepted:
            res = _auto_derive_skill_from_task(t["id"])
            if res.get("ok") and res.get("skill_id"):
                derived.append(res["skill_name"])
    finally:
        conn.close()
    return {"ok": True, "derived": derived, "count": len(derived)}


# ── 新路由: 研究院觉醒触发入口 ──
@daemon_skill_lab_bp.route("/api/daemon-lab/test/gold-team/auto", methods=["GET", "POST"])
def gold_team_auto():
    """手动触发整套闭环: 觉醒 → 组队 → 派发 → 提炼 skill"""
    if request.method == "POST":
        r = run_test_gold_team_auto()
        # 顺便跑 skill 衍生
        r["skill_derive"] = run_skill_derive_all()
        return jsonify(r)
    # GET: 返回金牌天团状态
    members = _gold_team_roster()
    return jsonify({
        "ok": True, "team": GOLD_TEST_TEAM, "size": len(members),
        "members": [{"name": m["member_name"], "role": m["skill_level"]} for m in members],
        "roles_covered": sorted({m["skill_level"] for m in members}),
        "api_trigger": "POST /api/daemon-lab/test/gold-team/auto",
        "flow_id": "flow_test_gold_team_20261023",
    })


# ── 新路由: AI HR 临时组队 (没团队时用) ──
@daemon_skill_lab_bp.route("/api/daemon-lab/test/form-roster", methods=["POST"])
def form_test_roster():
    """AI HR 根据任务描述智能组建测试团队"""
    data = request.get_json() or {}
    task_text = f"{data.get('title','')} {data.get('description','')}"
    result = _auto_form_test_roster(task_text)
    return jsonify({
        "ok": True, "test_type": result["test_type"],
        "roles_needed": result["roles_needed"],
        "members": result["members"],
        "ai_hr": "expert_team + hr_center",
    })


# ── 新路由: 手动触发 skill 衍生 ──
@daemon_skill_lab_bp.route("/api/daemon-lab/test/derive-skill", methods=["POST"])
def derive_skill():
    data = request.get_json() or {}
    task_id = data.get("task_id")
    if task_id:
        return jsonify(_auto_derive_skill_from_task(task_id))
    return jsonify(run_skill_derive_all())


# ── 新路由: 金牌天团认领任务 ──
@daemon_skill_lab_bp.route("/api/daemon-lab/test/gold-team/claim", methods=["POST"])
def gold_team_claim():
    """金牌天团手动认领指定任务"""
    data = request.get_json() or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"ok": False, "error": "task_id required"}), 400
    conn = _db()
    try:
        conn.execute(
            "UPDATE mt_lab_task_hall SET claim_owner=?, claim_owner_role='gold_qa_team', "
            "claimed_at=datetime('now','localtime'), status=CASE WHEN status='QUEUED' THEN 'DISPATCHED' ELSE status END "
            "WHERE id=?",
            (GOLD_TEST_TEAM, task_id))
        # AI HR 组队
        task = conn.execute("SELECT title, description FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        if task:
            formed = _auto_form_test_roster(f"{task['title']} {task['description'] or ''}")
            for m in formed["members"]:
                conn.execute(
                    "INSERT INTO mt_lab_hr_log (employee_name, role, hall_task_id, action, verdict) VALUES (?,?,?,?,?)",
                    (m["member_name"], "gold_qa", task_id, "CLAIM", f"金牌天团认领→{formed['test_type']}"))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "task_id": task_id, "claimed_by": GOLD_TEST_TEAM})


# ════════════════════════════════════════════════════════════════
# Phase 5: 前线巡检引擎 — 研究院主动下沉一线 (flow_frontline_patrol_20261023)
# 定时 + 随机扫描 10 维度 → 发现缺口 → 自动入厅 → 金牌天团闭环
# ════════════════════════════════════════════════════════════════

import random as _rand
import time as _time

_FRONTLINE_SCAN_INTERVAL = 1800  # 30 分钟定时巡逻
_RANDOM_PATROL_PROB = 0.15        # 每次定时有 15% 概率额外随机抽查


def _frontline_patrol():
    """
    前线巡检 — 10 维度主动下沉扫描
    返回: {"dimensions": int, "findings": int, "new_tasks": int, "report": [...]}
    """
    import socket
    import subprocess
    report = []
    new_tasks = 0
    conn = _db()
    try:
        # ── 维度 1: Flask 三端健康 ──
        for label, host_port in [("开发机", ("127.0.0.1", 8888)), ("mini", ("127.0.0.1", 5001))]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                ok = sock.connect_ex(host_port) == 0
                sock.close()
                status = "OK" if ok else "DOWN"
                report.append({"dim": f"{label} Flask", "status": status, "detail": f"{host_port[0]}:{host_port[1]}"})
                if not ok:
                    _ingest_patrol_task(conn, f"[{label} DOWN] Flask {host_port[0]}:{host_port[1]} 无响应",
                                        f"前线巡检发现 {label} Flask 端口 {host_port[1]} 不通, 需金牌天团介入",
                                        "flask_health", "HIGH")
                    new_tasks += 1
            except Exception as e:
                report.append({"dim": f"{label} Flask", "status": "ERROR", "detail": str(e)})

        # ── 维度 2: Ollama 本地推理 ──
        try:
            import urllib.request as _ur
            host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
            resp = _ur.urlopen(f"{host}/api/tags", timeout=3)
            models = json.loads(resp.read().decode()).get("models", [])
            report.append({"dim": "Ollama", "status": "OK", "detail": f"{len(models)} models: {[m['name'] for m in models[:3]]}"})
            # 检查默认模型是否存在
            default_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
            model_names = [m["name"] for m in models]
            if default_model not in model_names:
                _ingest_patrol_task(conn, f"[Ollama] 默认模型 {default_model} 未安装",
                                    f"前线巡检发现 OLLAMA_MODEL={default_model} 不在 Ollama 已安装列表 {model_names}",
                                    "ollama_model_missing", "HIGH")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "Ollama", "status": "DOWN", "detail": str(e)[:80]})
            _ingest_patrol_task(conn, "[Ollama DOWN] 本地推理引擎无响应",
                                f"前线巡检 Ollama 连接失败: {e}", "ollama_down", "HIGH")
            new_tasks += 1

        # ── 维度 3: daemon 全量状态 ──
        try:
            daemon_rows = conn.execute(
                "SELECT process_name, current_state FROM mt_daemon_registry").fetchall()
            down = [dict(r) for r in daemon_rows if r["current_state"] in ("FAILED", "STOPPED")]
            report.append({"dim": "Daemon", "status": f"OK({len(daemon_rows) - len(down)}/{len(daemon_rows)})",
                          "detail": f"{len(down)} FAILED" if down else "全绿"})
            for d in down:
                existing = conn.execute(
                    "SELECT 1 FROM mt_lab_task_hall WHERE source='frontline_patrol' AND source_id=? AND status!='DONE'",
                    (f"daemon_{d['process_name']}",)).fetchone()
                if not existing:
                    _ingest_patrol_task(conn, f"[Daemon] {d['process_name']} 状态 {d['current_state']}",
                                        f"前线巡检发现 daemon {d['process_name']} = {d['current_state']}, 需金牌天团巡检修复",
                                        "daemon_failure", "HIGH",
                                        source_id=f"daemon_{d['process_name']}")
                    new_tasks += 1
        except Exception as e:
            report.append({"dim": "Daemon", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 4: DB integrity ──
        try:
            db_path = os.environ.get("APP_DB") or "database/app.db"
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            wal_ok = True
            try:
                wal = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            except Exception:
                wal_ok = False
            report.append({"dim": "DB integrity", "status": "OK" if integrity == "ok" else integrity,
                          "detail": f"WAL={'OK' if wal_ok else 'FAIL'}, path={os.path.basename(db_path)}"})
            if integrity != "ok":
                _ingest_patrol_task(conn, f"[DB] integrity_check = {integrity}",
                                    f"前线巡检发现 DB 完整性异常: {integrity}, 需 DBA 介入",
                                    "db_integrity", "HIGH")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "DB integrity", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 5: 任务大厅积压 ──
        try:
            queued = conn.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status='QUEUED'").fetchone()[0]
            dispatched = conn.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status='DISPATCHED'").fetchone()[0]
            overdue = conn.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE deadline_at IS NOT NULL AND status='DISPATCHED' AND datetime(deadline_at) < datetime('now')").fetchone()[0]
            status = "OK" if queued < 5 else "BACKLOG"
            report.append({"dim": "任务大厅", "status": status,
                          "detail": f"QUEUED={queued}, DISPATCHED={dispatched}, OVERDUE={overdue}"})
            if queued >= 5 or overdue > 0:
                _ingest_patrol_task(conn, f"[任务大厅] 积压: QUEUED={queued}, OVERDUE={overdue}",
                                    f"前线巡检发现任务大厅积压, 金牌天团自动认领清理",
                                    "hall_backlog", "NORMAL")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "任务大厅", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 6: Skill 覆盖率 ──
        try:
            total_daemon = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry").fetchone()[0]
            total_skill = conn.execute("SELECT COUNT(*) FROM mt_skill_registry").fetchone()[0]
            # 查哪个 daemon 没有对应 skill
            uncovered = conn.execute("""
                SELECT d.process_name FROM mt_daemon_registry d
                WHERE NOT EXISTS (SELECT 1 FROM mt_skill_registry s WHERE s.name LIKE '%' || d.process_name || '%' OR s.description LIKE '%' || d.process_name || '%')
                LIMIT 3
            """).fetchall()
            cov = "OK" if total_skill >= total_daemon * 0.5 else "LOW"
            report.append({"dim": "Skill 覆盖率", "status": cov,
                          "detail": f"daemon={total_daemon}, skill={total_skill}, uncovered={[u[0] for u in uncovered]}"})
            if uncovered:
                _ingest_patrol_task(conn, f"[Skill] {len(uncovered)} 个 daemon 无对应 Skill",
                                    f"前线巡检发现以下 daemon 无 skill 覆盖: {[u[0] for u in uncovered]}, 需 Skill 衍生",
                                    "skill_gap", "NORMAL")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "Skill 覆盖率", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 7: AI 员工空闲率 ──
        try:
            total_emp = conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
            active = conn.execute("""
                SELECT COUNT(*) FROM ai_employees WHERE last_heartbeat > datetime('now', '-10 minutes')
            """).fetchone()[0]
            idle = total_emp - active
            idle_rate = idle / max(total_emp, 1)
            report.append({"dim": "AI 员工", "status": "OK" if idle_rate < 0.7 else "IDLE",
                          "detail": f"total={total_emp}, active={active}, idle_rate={idle_rate:.1%}"})
            if idle_rate >= 0.7:
                _ingest_patrol_task(conn, f"[AI 员工] 空闲率 {idle_rate:.1%}",
                                    f"前线巡检发现 AI 员工空闲率过高 ({idle_rate:.1%}), 建议 HR 调度或新任务派发",
                                    "hr_idle", "LOW")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "AI 员工", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 8: 金库余额异常 ──
        try:
            wallet_count = conn.execute("SELECT COUNT(*) FROM mt_token_wallets").fetchone()[0]
            # 查余额 < 0 或冻结异常
            frozen_anomaly = conn.execute("""
                SELECT COUNT(*) FROM mt_token_wallets WHERE frozen > balance AND balance > 0
            """).fetchone()[0]
            status = "OK" if frozen_anomaly == 0 else "ANOMALY"
            report.append({"dim": "金库", "status": status,
                          "detail": f"wallets={wallet_count}, frozen_anomaly={frozen_anomaly}"})
            if frozen_anomaly > 0:
                _ingest_patrol_task(conn, f"[金库] {frozen_anomaly} 个钱包 frozen > balance",
                                    f"前线巡检发现 {frozen_anomaly} 个钱包冻结金额超过余额, 需 Vault 修复",
                                    "vault_anomaly", "HIGH")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "金库", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 9: Flask 路由 405/404 巡检 (本地 test_client) ──
        try:
            from server_real_db import app as _flask_app
            bad_routes = []
            quick_checks = ["/local-chat", "/ai", "/api/local-chat/sessions",
                           "/api/local-chat/balance", "/api/vault/my",
                           "/api/daemon-lab/test/gold-team/auto"]
            with _flask_app.test_client() as tc:
                for path in quick_checks:
                    r = tc.get(path)
                    if r.status_code in (404, 405, 500):
                        bad_routes.append(f"{path}={r.status_code}")
            status = "OK" if not bad_routes else f"BAD({len(bad_routes)})"
            report.append({"dim": "路由巡检", "status": status,
                          "detail": f"bad={bad_routes}" if bad_routes else f"所有 {len(quick_checks)} 路径正常"})
            if bad_routes:
                _ingest_patrol_task(conn, f"[路由] {len(bad_routes)} 个路径异常",
                                    f"前线巡检发现路由异常: {bad_routes}",
                                    "route_broken", "HIGH")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "路由巡检", "status": "ERROR", "detail": str(e)[:80]})

        # ── 维度 10: daemon 进程存活 (ps 扫描) ──
        try:
            result = subprocess.run(["pgrep", "-f", "modular_start"], capture_output=True, text=True, timeout=3)
            pids = [p for p in result.stdout.strip().split("\n") if p]
            report.append({"dim": "进程", "status": "OK" if pids else "DOWN",
                          "detail": f"modular_start PIDs: {pids}"})
            if not pids:
                _ingest_patrol_task(conn, "[进程] modular_start 无存活",
                                    "前线巡检发现 Flask 进程不存在, 需立即重启",
                                    "process_down", "HIGH")
                new_tasks += 1
        except Exception as e:
            report.append({"dim": "进程", "status": "ERROR", "detail": str(e)[:80]})

        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True, "dimensions": 10, "findings": sum(1 for r in report if r["status"] not in ("OK",)),
        "new_tasks": new_tasks, "report": report,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_patrol": f"~{_FRONTLINE_SCAN_INTERVAL}s",
    }


def _ingest_patrol_task(conn, title, description, source_sub, priority, source_id=None, patrol_team="🧪 专业测试30年金牌天团"):
    """前线巡检 / 巡逻队发现 → 自动灌任务大厅 (source=frontline_patrol)"""
    if source_id is None:
        source_id = f"{source_sub}_{_int_now()}"
    existing = conn.execute(
        "SELECT 1 FROM mt_lab_task_hall WHERE source='frontline_patrol' AND source_id=? AND status!='DONE'",
        (source_id,)).fetchone()
    if existing:
        return
    conn.execute(
        "INSERT INTO mt_lab_task_hall "
        "(title, description, source, source_id, priority, status, task_type, "
        "claim_owner, claim_owner_role, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
        (title, description, "frontline_patrol", source_id, priority, "QUEUED",
         "OPS", patrol_team, "gold_qa_frontline"))


def _int_now():
    return int(_time.time())


def _random_patrol_jitter():
    """15% 概率随机抽查 — 避免可预测性"""
    if _rand.random() > _RANDOM_PATROL_PROB:
        return None
    jitter_scans = [
        lambda: _quick_ping("127.0.0.1", 11434, "Ollama"),
        lambda: _check_random_daemon(),
        lambda: _probe_random_route(),
        lambda: _check_db_size(),
    ]
    scan = _rand.choice(jitter_scans)
    try:
        return scan()
    except Exception as e:
        return {"jitter": "error", "detail": str(e)[:60]}


def _quick_ping(host, port, label):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(2)
    ok = s.connect_ex((host, port)) == 0; s.close()
    return {"jitter": label, "status": "OK" if ok else "DOWN"}


def _check_random_daemon():
    conn = _db()
    try:
        rows = conn.execute("SELECT process_name, current_state FROM mt_daemon_registry").fetchall()
        if not rows: return {"jitter": "daemon", "status": "empty"}
        pick = _rand.choice(rows)
        return {"jitter": "daemon", "process": pick["process_name"], "state": pick["current_state"]}
    finally: conn.close()


def _probe_random_route():
    try:
        from server_real_db import app as _flask_app
        import signal

        def _handler(signum, frame): raise TimeoutError("route probe timeout")
        signal.signal(signal.SIGALRM, _handler); signal.alarm(3)
        try:
            routes = ["/api/daemon-lab/test/gold-team/auto", "/api/collab/overview"]
            pick = _rand.choice(routes)
            with _flask_app.test_client() as tc:
                r = tc.get(pick)
        finally:
            signal.alarm(0)
        return {"jitter": "route", "path": pick, "status_code": r.status_code}
    except Exception as e:
        return {"jitter": "route", "error": str(e)[:60]}


def _check_db_size():
    import os
    db = os.environ.get("APP_DB") or os.path.join(_APP_DIR, "database", "app.db")
    try:
        size_mb = os.path.getsize(db) / (1024 * 1024)
        return {"jitter": "db_size", "size_mb": round(size_mb, 1), "status": "OK" if size_mb < 10000 else "LARGE"}
    except Exception as e:
        return {"jitter": "db_size", "error": str(e)[:60]}


# ── 定时调度 daemon (每 30min 跑 + 15% 随机抽查) ──
_frontline_last_run = 0.0


def run_frontline_daemon_once():
    """
    定时入口 (可被 cron/MAINTENANCE 守护线程调用)
    1. 定时巡逻 (30min 间隔)
    2. 随机 jitter 抽查 (15% 概率)
    3. 新发现自动入厅 → 金牌天团自动认领
    """
    global _frontline_last_run
    now = _time.time()
    result = {"patrol": None, "jitter": None, "status": "skipped"}

    # 主巡逻
    if now - _frontline_last_run >= _FRONTLINE_SCAN_INTERVAL:
        result["patrol"] = _frontline_patrol()
        _frontline_last_run = now
        result["status"] = "patrol_done"
        # 发现新任务 → 自动派发
        if result["patrol"]["new_tasks"] > 0:
            try:
                run_test_gold_team_auto()
                result["auto_dispatched"] = True
            except Exception as e:
                result["auto_dispatched_error"] = str(e)[:80]

    # 随机 jitter
    j = _random_patrol_jitter()
    if j:
        result["jitter"] = j
        result["status"] = "patrol+_jitter" if result["patrol"] else "jitter_only"

    return result


# ── 新路由: 手动触发前线巡检 ──
@daemon_skill_lab_bp.route("/api/daemon-lab/test/frontline-patrol", methods=["GET", "POST"])
def frontline_patrol_api():
    """手动触发前线巡检 + 返回巡检报告"""
    pat = _frontline_patrol()
    jit = _random_patrol_jitter()
    # 自动派发新发现
    auto_res = None
    if pat["new_tasks"] > 0:
        auto_res = run_test_gold_team_auto()
    return jsonify({
        "ok": True,
        "frontline": pat,
        "jitter": jit,
        "auto_dispatch": auto_res,
        "schedule": {
            "interval_sec": _FRONTLINE_SCAN_INTERVAL,
            "random_prob": _RANDOM_PATROL_PROB,
            "next_run_est": f"~{_FRONTLINE_SCAN_INTERVAL}s",
        },
        "flow_id": "flow_frontline_patrol_20261023",
        "研究院状态": "主动引擎 (非孤岛)",
    })


# ════════════════════════════════════════════════════════════════
# Phase 6: AI HR 自动创建新天团引擎 (flow_auto_team_form_20261023)
# 不依赖 SA, 极度挖潜 276 AI 员工 + 251 天团成员
# ════════════════════════════════════════════════════════════════

_ROLE_KEYWORDS = {
    "QA_LEAD":       ["测试", "qa", "质量", "巡检", "自检", "integrity", "scan", "patrol"],
    "SEC_TESTER":    ["安全", "security", "audit", "权限", "漏洞", "encrypt", "vikey", "防御"],
    "PERF_TESTER":   ["性能", "perf", "压力", "压测", "latency", "throughput", "基准", "benchmark"],
    "API_TESTER":    ["api", "接口", "blueprint", "flask", "route", "endpoint", "中间件"],
    "UI_TESTER":     ["ui", "前端", "css", "html", "渲染", "布局", "审美", "ux", "设计"],
    "AI_TESTER":     ["ai", "llm", "ollama", "agent", "脑库", "推理", "model", "神经网络", "rag"],
    "DB_TESTER":     ["db", "数据库", "sqlite", "dba", "表", "column", "wal", "索引"],
    "DEV_FIXER":     ["修复", "repair", "fix", "诊断", "debug", "fallback", "系统修复"],
    "REVIEWER":      ["评审", "review", "验收", "质量", "仲裁"],
    "ARCHITECT":     ["架构", "architecture", "模块化", "解耦", "骨架", "system engineering"],
}
_ROLE_LABELS = {
    "QA_LEAD": "测试", "SEC_TESTER": "安全", "PERF_TESTER": "性能",
    "API_TESTER": "接口", "UI_TESTER": "前端", "AI_TESTER": "AI",
    "DB_TESTER": "数据库", "DEV_FIXER": "修复", "REVIEWER": "评审", "ARCHITECT": "架构",
}


def _auto_form_team_for_gap(gap_text, suggested_role=None, min_size=3, max_size=6):
    """AI HR 根据缺口描述自动组队 — 极度挖潜"""
    import hashlib
    gap_lower = gap_text.lower()
    if suggested_role:
        needed_roles = [suggested_role]
    else:
        needed_roles = [r for r, kws in _ROLE_KEYWORDS.items() if any(kw.lower() in gap_lower for kw in kws)]
        if not needed_roles:
            needed_roles = ["QA_LEAD", "REVIEWER", "DEV_FIXER"]

    conn = _db()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT, team_name TEXT, member_name TEXT,
            skill_level TEXT, source TEXT, capabilities TEXT, member_id TEXT, team_score_json TEXT,
            assigned_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_team_registry (
            team_id TEXT PRIMARY KEY, team_name TEXT UNIQUE, member_count INTEGER,
            skill_keywords TEXT, color_tag TEXT, auto_formed_at TEXT DEFAULT (datetime('now')))""")

        all_members = conn.execute(
            "SELECT member_name, skill_level, source, capabilities FROM mt_team_members"
        ).fetchall()
        picked = {}; used_names = set()

        for role in needed_roles:
            role_kws = _ROLE_KEYWORDS.get(role, [])
            scored = []
            for m in all_members:
                if m["member_name"] in used_names: continue
                blob = ((m["capabilities"] or "") + " " + (m["source"] or "")).lower()
                score = sum(3 for kw in role_kws if kw.lower() in blob)
                lv = (m["skill_level"] or "").upper()
                if any(lv.startswith(x) for x in ("CHIEF", "LEAD", "MASTER", "EXPERT", "LV3")): score += 2
                elif lv.startswith("LV"): score += 1
                if "金牌" in (m["source"] or ""): score -= 5
                if score > 0: scored.append((score, dict(m)))
            scored.sort(key=lambda x: -x[0])
            take = 2 if len(needed_roles) <= 3 else 1
            for _, m in scored[:take]:
                picked.setdefault(role, []).append(m)
                used_names.add(m["member_name"])

        # 极度挖潜: 不够就随便拉 (不能让缺口没人管)
        remaining = min_size - sum(len(v) for v in picked.values())
        if remaining > 0:
            pool = conn.execute(
                "SELECT member_name, skill_level, source, capabilities FROM mt_team_members "
                "WHERE member_name NOT IN ({}) LIMIT {}".format(
                    ",".join("?" * max(len(used_names), 1)), min_size + 5),
                list(used_names) or [""]).fetchall()
            for m in pool:
                if remaining <= 0: break
                if m["member_name"] in used_names: continue
                # 塞到第一个 needed_role
                first_role = needed_roles[0] if needed_roles else "QA_LEAD"
                picked.setdefault(first_role, []).append(dict(m))
                used_names.add(m["member_name"]); remaining -= 1

        # 汇总 + 注册
        all_picked = []
        for role, members in picked.items():
            for m in members[:max_size - len(all_picked)]:
                m2 = dict(m); m2["_assigned_role"] = role
                all_picked.append(m2)

        if not all_picked:
            return {"ok": False, "error": "no candidates found"}

        role_label = _ROLE_LABELS.get(needed_roles[0], "测试")
        team_name = f"🤖 自动组队·{role_label}_{_int_now() % 10000:04d}"
        team_id = f"auto_{hashlib.md5(team_name.encode()).hexdigest()[:10]}"

        all_kws = list(set(kw for r in needed_roles for kw in _ROLE_KEYWORDS.get(r, [])))[:12]
        conn.execute("INSERT OR REPLACE INTO mt_team_registry VALUES (?,?,?,?,?,datetime('now'))",
                     (team_id, team_name, len(all_picked), ",".join(all_kws), "🤖"))
        for i, m in enumerate(all_picked):
            mid = f"{team_id}_m{i}_{hashlib.md5(m['member_name'].encode()).hexdigest()[:6]}"
            conn.execute("INSERT OR REPLACE INTO mt_team_members (team_name,member_name,skill_level,source,capabilities,member_id) VALUES (?,?,?,?,?,?)",
                         (team_name, m["member_name"], m["_assigned_role"], m.get("source", "🤖自动组队"),
                          (m.get("capabilities") or "")[:200], mid))
        conn.commit()

        # HR 审计
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS mt_lab_audit_log (center,action,subject,detail,created_at)")
            conn.execute("INSERT INTO mt_lab_audit_log VALUES (?,?,?,?,datetime('now','localtime'))",
                         ("hr_center", "AUTO_FORM_TEAM", team_id,
                          json.dumps({"gap": gap_text[:100], "roles": needed_roles, "size": len(all_picked)},
                                     ensure_ascii=False)))
        except Exception: pass

        return {
            "ok": True, "team_id": team_id, "team_name": team_name,
            "needed_roles": needed_roles, "members_count": len(all_picked),
            "members": [{"name": m["member_name"], "role": m["_assigned_role"], "from": m.get("source", "")} for m in all_picked],
            "coverage": f"{len(all_picked)}/{max_size}",
        }
    finally: conn.close()


def run_auto_team_daemon():
    """定时入口: 扫孤儿任务 → 自动组新天团 → 自动认领"""
    conn = _db()
    formed = []
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS mt_lab_hr_log (employee_name, employee_code, role, hall_task_id, action, verdict)")
        orphans = conn.execute("""
            SELECT id, title, description FROM mt_lab_task_hall
            WHERE status='QUEUED' AND (claim_owner IS NULL OR claim_owner='' OR claim_owner NOT LIKE '%金牌%')
            ORDER BY id DESC LIMIT 5""").fetchall()
        for t in orphans:
            team = _auto_form_team_for_gap(f"{t['title']} {t['description'] or ''}")
            if team["ok"]:
                formed.append({"task_id": t["id"], "team": team["team_name"], "size": team["members_count"]})
                conn.execute("UPDATE mt_lab_task_hall SET claim_owner=?, claim_owner_role='auto_team', claimed_at=datetime('now','localtime'), status='DISPATCHED' WHERE id=?",
                             (team["team_name"], t["id"]))
                for m in team["members"]:
                    conn.execute("INSERT INTO mt_lab_hr_log (employee_name, role, hall_task_id, action, verdict) VALUES (?,?,?,?,?)",
                                 (m["name"], m["role"], t["id"], "AUTO_FORM_CLAIM", team["team_name"]))
        conn.commit()
    finally: conn.close()
    return {"ok": True, "orphan_scanned": len(formed), "teams_formed": len(formed), "details": formed, "engine": "auto_team_daemon"}


@daemon_skill_lab_bp.route("/api/daemon-lab/test/auto-team", methods=["GET", "POST"])
def auto_team_api():
    """AI HR 自动组新天团 — 极度挖潜"""
    data = request.get_json() if request.method == "POST" else {}
    if data and (data.get("gap") or data.get("title")):
        gap = f"{data.get('title','')} {data.get('description', data.get('gap',''))}"
        return jsonify(_auto_form_team_for_gap(gap, data.get("role")))
    return jsonify(run_auto_team_daemon())


# ════════════════════════════════════════════════════════════════
# 🆕 Lab Daemon 守护循环 (全自动, 零人工) — flow_lab_daemon_auto_20261023
# ════════════════════════════════════════════════════════════════

def run_lab_daemon_loop():
    """
    研发中心全自动守护循环 (6 个子任务, 不同频率):
      - 每 15min: 前线巡检 run_frontline_daemon_once()    → 入任务大厅
      - 每 15min: 自动组队 run_auto_team_daemon()         → 认领孤儿任务
      - 每 30min: 任务大厅驱动 run_hall_auto()             → QUEUED → DISPATCHED
      - 每 30min: 任务回收 run_hall_recycle()              → OVERDUE 回收重派
      - 每 60min: 金牌天团 run_test_gold_team_auto()       → 研究院觉醒 + 派发
      - 每 24h:   Skill 衍生 run_skill_derive_all()       → 验收任务 → Skill 注册表
    server_real_db.py daemon-lab 注册后自动启动此线程
    """
    import time as _t
    _t.sleep(60)  # 等 Flask 稳定
    print(f'[LAB-DAEMON] 🛰️ 研发中心全自动守护启动 — 15min 巡检/组队, 30min 驱动/回收, 60min 天团, 24h Skill 衍生')
    loop_count = 0
    while True:
        loop_count += 1
        tick = loop_count  # 每 tick = 15min
        try:
            # ── 每 15min: 前线巡检 + 自动组队 ──
            t0 = _t.time()
            try:
                fr = run_frontline_daemon_once()
                print(f'[LAB-DAEMON] ✅ 前线巡检 done ({int(_t.time()-t0)}s) patrol={fr.get("patrol",fr.get("total",0))} queue={fr.get("queue",0)}')
            except Exception as e:
                print(f'[LAB-DAEMON] ⚠️ 前线巡检异常 (不崩): {e}')
            try:
                tr = run_auto_team_daemon()
                print(f'[LAB-DAEMON] ✅ 自动组队 done teams={tr.get("teams_created",0)} claimed={tr.get("claimed",0)}')
            except Exception as e:
                print(f'[LAB-DAEMON] ⚠️ 自动组队异常 (不崩): {e}')

            # ── 每 30min (2 tick): 任务大厅自动驱动 + 回收 ──
            if tick % 2 == 0:
                try:
                    hr = run_hall_auto()
                    print(f'[LAB-DAEMON] ✅ 大厅驱动 done ingested={hr.get("ingested",0)} dispatched={hr.get("dispatched",0)}')
                except Exception as e:
                    print(f'[LAB-DAEMON] ⚠️ 大厅驱动异常 (不崩): {e}')
                try:
                    rc = run_hall_recycle()
                    print(f'[LAB-DAEMON] ✅ 任务回收 done {rc}')
                except Exception as e:
                    print(f'[LAB-DAEMON] ⚠️ 任务回收异常 (不崩): {e}')

            # ── 每 60min (4 tick): 金牌天团自动派发 ──
            if tick % 4 == 0:
                try:
                    gr = run_test_gold_team_auto()
                    print(f'[LAB-DAEMON] ✅ 金牌天团派发 done {gr}')
                except Exception as e:
                    print(f'[LAB-DAEMON] ⚠️ 金牌天团异常 (不崩): {e}')

            # ── 每 24h (96 tick): Skill 衍生 ──
            if tick % 96 == 0:
                try:
                    sr = run_skill_derive_all()
                    print(f'[LAB-DAEMON] ✅ Skill 衍生 done {sr}')
                except Exception as e:
                    print(f'[LAB-DAEMON] ⚠️ Skill 衍生异常 (不崩): {e}')

        except Exception as e:
            print(f'[LAB-DAEMON] ⚠️ 主循环异常 (不崩): {e}')

        # 等下一轮 15min
        _t.sleep(900)

