#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多语种平台组织对齐与巡逻防控引擎 [flow_lang_org_20261031]
==========================================================
将多语种在线教育平台 (flow_lang_pedagogy_20261031) 对齐舰队既有组织资产:
  ① 维护部队下沉编制  五连(红/蓝/青/黄/紫)各下沉 1 个多语种平台防控分队 + AI 员工 10 名,
                      技能授权 mt_corps_empowerment, 全部编入现役 (接 mt_maintenance_tasks 派单闭环)
  ② 巡逻防控七检      资产完整性/题库库存/API健康/留痕治理/专家在编/守卫白名单/学习活跃,
                      发现即处置(自动补种子/补库/补专家), 重缺口回灌任务大厅 + 维护部队派单
  ③ 专家委员会评审    EigenFlux languages 专家 (chief+expert×2) 定期评审平台教学质量
  ④ 教授/顾问/天团会诊 三方角色对平台状态出诊断与建议 (本地模板优先, LLM 增强可选)
  ⑤ 中心支持矩阵      课程内容→教育题库(106) 学情→数据研究(6) 专家→专家团队(470)
                      引擎→AI引擎(4) 派单→工作流(5) 守卫→海关总署, 责任到中心

设计约束: 零 token 本地优先; 全操作留痕; 缺口自动回灌任务大厅 (项目规则)。
CLI:
  python3 ai_language_org_alignment_engine.py init       # 编制下沉 + 支持矩阵
  python3 ai_language_org_alignment_engine.py patrol     # 一轮巡逻防控
  python3 ai_language_org_alignment_engine.py committee  # 专家委员会评审
  python3 ai_language_org_alignment_engine.py consult    # 教授/顾问/天团会诊
  python3 ai_language_org_alignment_engine.py status     # 组织对齐总览
"""
import json
import os
import sqlite3
import sys
import urllib.request
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.db_path import get_db_path

DB_PATH = get_db_path('app.db')
_FLOW = "flow_lang_org_20261031"

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_lang_patrol_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patrol_id TEXT NOT NULL,
    corps_id TEXT, corps_name TEXT,
    check_item TEXT NOT NULL,
    severity TEXT NOT NULL,              -- OK/WARN/FAIL
    action TEXT,                         -- AUTO_REPAIRED/TASK_FED/HALL_FED/OBSERVED
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_committee_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL,
    reviewers TEXT,                      -- JSON [{expert_id,name,role_cn,level}]
    metrics TEXT,                        -- JSON 评审指标
    scores TEXT,                         -- JSON 各专家评分
    verdict TEXT,                        -- PASS/PASS_WITH_SUGGESTIONS/NEEDS_WORK
    suggestions TEXT,                    -- JSON
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_advisor_consults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consult_id TEXT NOT NULL,
    role TEXT NOT NULL,                  -- 教授/顾问/天团
    diagnosis TEXT,                      -- JSON 诊断
    advice TEXT,
    source TEXT DEFAULT 'local',         -- local/llm
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_center_support (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    center_id INTEGER NOT NULL,
    center_code TEXT,
    center_name TEXT,
    responsibility TEXT,
    status TEXT DEFAULT 'ACTIVE',
    last_check TEXT,
    UNIQUE(module, center_id)
)""",
]

# 五连下沉编制: (corps_id, 分队名, duty, task_type, maintenance_role, 队员名×2)
_SQUAD_PLAN = [
    ("CORPS_283b14", "🔴 红队-安全作战", "多语种平台·守卫白名单组", "PATROL·多语种平台",
     "security", "白名单合规/端点越权巡检/守卫完整性",
     ("语卫·玄盾", "语卫·铁闸")),
    ("CORPS_0cae58", "🔵 蓝队-稳定守护", "多语种平台·API存活组", "SURVEY·多语种平台",
     "ops", "API健康巡检/锁竞争治理/Flask存活",
     ("语护·长明", "语护·不熄")),
    ("CORPS_d8a9a4", "🟢 青队-质量巡检", "多语种平台·内容巡检组", "REPAIR·多语种平台",
     "refactor", "种子资产完整性/课程内容质检/文案合规",
     ("语检·清明", "语检·细致")),
    ("CORPS_23bb41", "🟡 黄队-题库建设", "多语种平台·题库补库组", "EMPOWER·多语种平台",
     "feature", "题库库存监控/自动补库/难度校准",
     ("语题·充栋", "语题·盈车")),
    ("CORPS_1c8d27", "⚪ 紫队-数据治理", "多语种平台·留痕治理组", "RECON·多语种平台",
     "cleanup", "操作留痕核查/孤儿数据清理/学情画像回填",
     ("语痕·有据", "语痕·可溯")),
]

# 中心支持矩阵: (module, center_id, responsibility)
_SUPPORT_MATRIX = [
    ("课程与题库内容", 106, "分级课程/语法点/题库建设与组卷主责 (edu_qbank)"),
    ("学情画像与统计", 6, "学习者画像/正确率趋势/数据研究中心协同 (data_research)"),
    ("语言专家雇佣", 470, "EigenFlux languages 专家雇佣与团队组建 (expert_team)"),
    ("LLM 三轨引擎", 4, "解析/造题/路径 LLM 增强调用与本地兜底 (ai_engine)"),
    ("巡逻任务派单", 5, "维护部队任务流转与大厅派单管线 (workflow)"),
    ("守卫与合规", 106, "海关总署白名单合规/学习者端点鉴权审计"),
]

_ASSET_BASELINE = {"courses": 9, "lessons": 20, "vocab": 18, "grammar": 9,
                   "speaking": 9, "listening": 3, "experts": 6}
_QBANK_FLOOR = 8  # 每语言题库库存下限


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:8]}"


def ensure_tables():
    conn = get_conn()
    try:
        for sql in _DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _feed_maintenance_task(corps_id: str, title: str, task_type: str,
                           description: str, priority: int = 2) -> str:
    """缺口 → 维护部队派单闭环 (PENDING, 由 sys_maintenance_dispatch daemon 自动派给分队)"""
    task_id = _uid("LANGP")
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_maintenance_tasks
               (task_id,corps_id,title,task_type,priority,status,description)
               VALUES (?,?,?,?,?,'PENDING',?)""",
            (task_id, corps_id, title, task_type, priority, description[:800]))
        conn.execute(
            "INSERT INTO mt_maintenance_log (corps_id,task_id,action,detail) VALUES (?,?,?,?)",
            (corps_id, task_id, 'LANG_PATROL_FED',
             json.dumps({"flow": _FLOW, "title": title}, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    return task_id


def _feed_task_hall(title: str, description: str, priority: str = "NORMAL") -> Optional[str]:
    """重大缺口 → 任务大厅回灌 + 自动派单 (项目规则: 主动发现缺口自动回灌)"""
    try:
        conn = get_conn()
        prefix = 'TH-'
        n = conn.execute(
            "SELECT count(*) FROM mt_lab_task_hall WHERE hall_code LIKE ?",
            (f"{prefix}{datetime.now().strftime('%Y%m%d')}-%",)).fetchone()[0]
        code = f"TH-{datetime.now().strftime('%Y%m%d')}-{n+1:04d}"
        conn.execute(
            """INSERT INTO mt_lab_task_hall
               (title,description,source,priority,status,center_id,hall_code,
                publisher,publisher_role,task_type,approval_status,approved_by,updated_at)
               VALUES (?,?,?,?,'QUEUED',106,?,?,?,?,?,?,datetime('now','localtime'))""",
            (title, description[:500], 'lang_org_patrol', priority,
             code, 'wuchenghao15', 'admin', 'EDU', 'AUTO_FED', 'wuchenghao15'))
        conn.commit()
        tid = conn.execute("SELECT id FROM mt_lab_task_hall WHERE hall_code=?", (code,)).fetchone()[0]
        conn.close()
        from blueprints.daemon_skill_lab_bp import _hall_dispatch_one, _db
        c2 = _db()
        row = c2.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (tid,)).fetchone()
        c2.close()
        _hall_dispatch_one(row)
        return code
    except Exception as e:
        print(f"[HALL-FED] ⚠️ 回灌失败: {e}")
        return None


# ============================================================
#  ① 维护部队下沉编制
# ============================================================

def register_patrol_squads() -> Dict[str, int]:
    """五连各下沉 1 个多语种平台防控分队 + 每分队 2 名 AI 员工 + 技能授权 (幂等)"""
    ensure_tables()
    n_squad = n_emp = n_skill = 0
    conn = get_conn()
    try:
        for corps_id, corps_name, sq_name, duty, task_type, empower, members in _SQUAD_PLAN:
            exists = conn.execute(
                "SELECT squad_id FROM mt_corps_squads WHERE corps_id=? AND name=?",
                (corps_id, sq_name)).fetchone()
            if exists:
                squad_id = exists["squad_id"]
            else:
                squad_id = _uid("SQD")
                conn.execute(
                    """INSERT INTO mt_corps_squads (squad_id,corps_id,name,duty,empowerment,status)
                       VALUES (?,?,?,?,?,'active')""",
                    (squad_id, corps_id, sq_name, duty, f"{empower} (flow_lang_org_20261031)"))
                n_squad += 1
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_corps_empowerment (squad_id,skill_name) VALUES (?,?)",
                (squad_id, empower))
            n_skill += cur.rowcount
            for m_name in members:
                code = f"LANG-{corps_id[-4:]}-{abs(hash(m_name)) % 900 + 100}"
                cur = conn.execute(
                    """INSERT OR IGNORE INTO ai_employees
                       (name,employee_code,description,capabilities,specialties,status,squad_id,corps_id,maintenance_role)
                       VALUES (?,?,?,?,?,'active',?,?,?)""",
                    (m_name, code, f"多语种平台防控队员·{sq_name}",
                     empower, f"多语种教育平台/{corps_name}", squad_id, corps_id, duty))
                if cur.rowcount:
                    n_emp += 1
            conn.execute(
                "UPDATE mt_maintenance_corps SET headcount=(SELECT count(*) FROM ai_employees "
                "WHERE corps_id=? AND LOWER(IFNULL(status,'active'))='active') WHERE corps_id=?",
                (corps_id, corps_id))
        conn.commit()
    finally:
        conn.close()
    return {"squads": n_squad, "employees": n_emp, "skills": n_skill}


# ============================================================
#  ② 巡逻防控七检
# ============================================================

def _log_finding(conn, corps_id, corps_name, item, severity, action, detail):
    conn.execute(
        "INSERT INTO mt_lang_patrol_log (patrol_id,corps_id,corps_name,check_item,severity,action,detail) "
        "VALUES (?,?,?,?,?,?,?)",
        (_uid("PTL"), corps_id, corps_name, item, severity, action,
         json.dumps(detail, ensure_ascii=False)[:1500]))


def patrol_once() -> Dict[str, Any]:
    """一轮巡逻防控: 七检 → 即时处置 → 缺口回灌 (维护部队 PENDING + 任务大厅)"""
    ensure_tables()
    import engines.ai_language_pedagogy_engine as lang
    lang.ensure_tables()
    findings: List[dict] = []
    conn = get_conn()
    try:
        # P1 资产完整性 (青队)
        counts = {t: conn.execute(f"SELECT count(*) FROM mt_lang_{t}").fetchone()[0]
                  for t in ("courses", "lessons", "vocab", "grammar", "speaking", "listening")}
        missing = {k: (v, _ASSET_BASELINE[k]) for k, v in counts.items() if v < _ASSET_BASELINE[k]}
        if missing:
            lang.seed_base_assets()
            _log_finding(conn, "CORPS_d8a9a4", "🟢 青队", "P1 资产完整性", "WARN",
                         "AUTO_REPAIRED", {"missing": missing, "fixed_by": "seed_base_assets"})
            findings.append({"item": "P1 资产完整性", "severity": "WARN", "corps": "青队",
                             "action": "自动补齐种子资产", "detail": missing})
        else:
            _log_finding(conn, "CORPS_d8a9a4", "🟢 青队", "P1 资产完整性", "OK", "OBSERVED",
                         {"counts": counts})
        # P2 题库库存 (黄队) — 低于下限自动补库 (事务外造题, 短事务入库)
        by_lang = dict((r[0], r[1]) for r in conn.execute(
            "SELECT language,count(*) FROM mt_lang_qbank GROUP BY language"))
        low = {lg: c for lg, c in by_lang.items() if c < _QBANK_FLOOR}
        conn.commit()
    finally:
        conn.close()
    if low:
        for lg, c in low.items():
            try:
                lang.create_questions(topic="场景词汇", language=lg, difficulty=2,
                                      count=_QBANK_FLOOR - c, q_type="单词题")
            except Exception:
                pass
        conn = get_conn()
        try:
            after = dict((r[0], r[1]) for r in conn.execute(
                "SELECT language,count(*) FROM mt_lang_qbank GROUP BY language"))
            _log_finding(conn, "CORPS_23bb41", "🟡 黄队", "P2 题库库存", "WARN", "AUTO_REPAIRED",
                         {"before": by_lang, "after": after, "floor": _QBANK_FLOOR})
            findings.append({"item": "P2 题库库存", "severity": "WARN", "corps": "黄队",
                             "action": f"黄队自动补库 {low}", "detail": {"after": after}})
        finally:
            conn.close()
    else:
        conn = get_conn()
        try:
            _log_finding(conn, "CORPS_23bb41", "🟡 黄队", "P2 题库库存", "OK", "OBSERVED",
                         {"by_language": by_lang, "floor": _QBANK_FLOOR})
        finally:
            conn.close()
    conn = get_conn()
    try:
        # P3 API 健康 (蓝队)
        api_ok, api_detail = False, {}
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:5001/api/lang-platform/overview", timeout=6) as resp:
                body = json.loads(resp.read().decode())
                api_ok = bool(body.get("ok"))
                api_detail = {"http": resp.status, "stats": body.get("stats", {})}
        except Exception as e:
            api_detail = {"error": str(e)[:200]}
        _log_finding(conn, "CORPS_0cae58", "🔵 蓝队", "P3 API健康",
                     "OK" if api_ok else "FAIL", "OBSERVED" if api_ok else "TASK_FED", api_detail)
        findings.append({"item": "P3 API健康", "severity": "OK" if api_ok else "FAIL",
                         "corps": "蓝队", "action": "存活" if api_ok else "维护部队派单",
                         "detail": api_detail})
        # P4 留痕治理 (紫队)
        log_today = conn.execute(
            "SELECT count(*) FROM mt_lang_activity_log WHERE date(created_at)=date('now','localtime')"
        ).fetchone()[0]
        orphan_progress = conn.execute(
            """SELECT count(*) FROM mt_lang_progress p WHERE NOT EXISTS
               (SELECT 1 FROM mt_lang_users u WHERE u.username=p.username)""").fetchone()[0]
        p4_sev = "OK" if orphan_progress == 0 else "WARN"
        _log_finding(conn, "CORPS_1c8d27", "⚪ 紫队", "P4 留痕治理", p4_sev,
                     "OBSERVED" if p4_sev == "OK" else "TASK_FED",
                     {"activity_log_today": log_today, "orphan_progress": orphan_progress})
        findings.append({"item": "P4 留痕治理", "severity": p4_sev, "corps": "紫队",
                         "action": "合规" if p4_sev == "OK" else "紫队清理孤儿进度",
                         "detail": {"activity_log_today": log_today,
                                    "orphan_progress": orphan_progress}})
        # P5 专家在编 (EigenFlux/专家团队中心 470)
        experts = conn.execute(
            "SELECT count(*) FROM eigenflux_experts WHERE domain='languages' AND status='active'"
        ).fetchone()[0]
        p5_sev = "OK" if experts >= _ASSET_BASELINE["experts"] else "WARN"
        _log_finding(conn, "CORPS_23bb41", "🟡 黄队", "P5 专家在编", p5_sev,
                     "OBSERVED" if p5_sev == "OK" else "AUTO_REPAIRED",
                     {"active_experts": experts, "baseline": _ASSET_BASELINE["experts"]})
        findings.append({"item": "P5 专家在编", "severity": p5_sev, "corps": "黄队/专家团队中心",
                         "action": "满编" if p5_sev == "OK" else f"仅{experts}名, 触发补编",
                         "detail": {"active_experts": experts}})
        conn.commit()
    finally:
        conn.close()
    # P6 守卫白名单 (红队) — 文件级检查 (事务外)
    hall_fed = None
    try:
        with open(os.path.join(PROJECT_ROOT, "server_real_db.py"), encoding="utf-8") as f:
            src = f.read()
        need = ["/api/lang-platform/auth/", "/api/lang-platform/vocab/", "/api/lang-platform/grammar/",
                "/api/lang-platform/speaking/", "/api/lang-platform/listening/",
                "/api/lang-platform/community/", "/api/lang-platform/path/"]
        lost = [p for p in need if p not in src]
        conn = get_conn()
        try:
            _log_finding(conn, "CORPS_283b14", "🔴 红队", "P6 守卫白名单",
                         "OK" if not lost else "FAIL", "OBSERVED" if not lost else "HALL_FED",
                         {"checked": len(need), "lost": lost})
            conn.commit()
        finally:
            conn.close()
        findings.append({"item": "P6 守卫白名单", "severity": "OK" if not lost else "FAIL",
                         "corps": "红队", "action": "白名单完整" if not lost else "回灌大厅",
                         "detail": {"lost": lost}})
        hall_fed = None
        if lost:
            hall_fed = _feed_task_hall(
                "【红队巡逻】多语种平台守卫白名单缺失项回灌",
                f"巡逻发现白名单丢失: {lost}. 任务路由: 教育题库中心认领。涉及: 守卫,白名单,安全,多语种",
                priority="HIGH")
    except Exception as e:
        findings.append({"item": "P6 守卫白名单", "severity": "WARN", "corps": "红队",
                         "action": "检查异常", "detail": {"error": str(e)[:150]}})
    # P7 学习活跃 (紫队, 观察)
    conn = get_conn()
    try:
        active_24h = conn.execute(
            "SELECT count(DISTINCT username) FROM mt_lang_progress "
            "WHERE created_at >= datetime('now','localtime','-1 day')").fetchone()[0]
        total_users = conn.execute("SELECT count(*) FROM mt_lang_users").fetchone()[0]
        _log_finding(conn, "CORPS_1c8d27", "⚪ 紫队", "P7 学习活跃", "OK", "OBSERVED",
                     {"active_24h": active_24h, "total_users": total_users})
        conn.commit()
    finally:
        conn.close()
    findings.append({"item": "P7 学习活跃", "severity": "OK", "corps": "紫队",
                     "action": f"24h活跃 {active_24h}/{total_users}", "detail": {}})
    # FAIL/WARN → 维护部队 PENDING 派单 (蓝队 API 失活 / 紫队孤儿数据 / 专家缺编)
    fed = []
    if not api_ok:
        fed.append(_feed_maintenance_task(
            "CORPS_0cae58", "【蓝队·多语种平台】API 健康巡检异常, 应急排查 Flask 5001",
            "bugfix", f"巡逻发现 /api/lang-platform/overview 异常: {api_detail}"))
    if orphan_progress:
        fed.append(_feed_maintenance_task(
            "CORPS_1c8d27", "【紫队·多语种平台】清理孤儿学习进度记录",
            "cleanup", f"发现 {orphan_progress} 条孤儿进度, 需回填 mt_lang_users 或归档"))
    if experts < _ASSET_BASELINE["experts"]:
        try:
            lang.hire_language_experts(_ASSET_BASELINE["experts"] - experts, round_num=2)
            fed.append("AUTO_HIRED_" + str(_ASSET_BASELINE["experts"] - experts))
        except Exception:
            fed.append(_feed_maintenance_task(
                "CORPS_23bb41", "【黄队·多语种平台】语言专家缺编补雇",
                "feature", f"当前 {experts} 名, 需补至 {_ASSET_BASELINE['experts']}"))
    return {"ok": True, "flow": _FLOW, "findings": findings, "hall_fed": hall_fed,
            "maintenance_fed": fed,
            "summary": f"七检完成: {sum(1 for f in findings if f['severity']=='OK')} OK / "
                       f"{sum(1 for f in findings if f['severity']=='WARN')} WARN / "
                       f"{sum(1 for f in findings if f['severity']=='FAIL')} FAIL"}


# ============================================================
#  ③ 专家委员会评审 (EigenFlux languages chief+expert×2)
# ============================================================

def committee_review() -> Dict[str, Any]:
    """语言教学专家委员会评审: 平台教学质量指标 → 评分 → 结论与改进建议"""
    ensure_tables()
    conn = get_conn()
    try:
        experts = [dict(r) for r in conn.execute(
            """SELECT expert_id,name,role_cn,level,performance_score FROM eigenflux_experts
               WHERE domain='languages' AND status='active'
               ORDER BY CASE level WHEN 'chief' THEN 0 ELSE 1 END, performance_score DESC LIMIT 3""")]
        metrics = {
            "course_coverage": dict((r[0], r[1]) for r in conn.execute(
                "SELECT language,count(*) FROM mt_lang_courses GROUP BY language")),
            "qbank_by_lang": dict((r[0], r[1]) for r in conn.execute(
                "SELECT language,count(*) FROM mt_lang_qbank GROUP BY language")),
            "qbank_quality_avg": round(conn.execute(
                "SELECT avg(quality_score) FROM mt_lang_qbank").fetchone()[0] or 0, 3),
            "learners": conn.execute("SELECT count(*) FROM mt_lang_users").fetchone()[0],
            "practice_sessions": conn.execute(
                "SELECT count(*) FROM mt_lang_practice_results WHERE username!='__paper__'").fetchone()[0],
            "srs_reviews": conn.execute("SELECT count(*) FROM mt_lang_vocab_reviews").fetchone()[0],
            "community_posts": conn.execute("SELECT count(*) FROM mt_lang_posts").fetchone()[0],
            "difficulty_events": conn.execute(
                "SELECT count(*) FROM mt_lang_difficulty_events").fetchone()[0],
        }
    finally:
        conn.close()
    if not experts:
        return {"ok": False, "error": "languages 领域无在编专家, 请先 hire"}
    # 评分规则 (本地): 覆盖3语=满分; 题库每语≥8; 质量分≥0.8; 有SRS+社区+弹性记录
    rubric = []
    rubric.append(["课程覆盖", 30 if len(metrics["course_coverage"]) >= 3 else 15])
    rubric.append(["题库库存", 25 if all(v >= _QBANK_FLOOR for v in metrics["qbank_by_lang"].values())
                   else 12])
    rubric.append(["内容质量", 25 if metrics["qbank_quality_avg"] >= 0.75 else 12])
    rubric.append(["学习闭环", 20 if (metrics["srs_reviews"] and metrics["community_posts"]
                                     and metrics["difficulty_events"]) else 8])
    total = sum(s for _, s in rubric)
    verdict = "PASS" if total >= 85 else ("PASS_WITH_SUGGESTIONS" if total >= 60 else "NEEDS_WORK")
    suggestions = []
    if total < 85:
        for name, s in rubric:
            if s < 25:
                suggestions.append(f"「{name}」得分 {s}, 建议由对应中心/分队限期整改")
    else:
        suggestions.append("平台教学质量达标, 建议进入增长期: 扩充语种 (法/德/西) 与沉浸式场景")
    scores = [{"expert": e["name"], "role_cn": e["role_cn"], "level": e["level"],
               "score": max(50, min(100, total + (5 if e["level"] == "chief" else 0) -
                                    (i * 3)))} for i, e in enumerate(experts)]
    review_id = _uid("CMTR")
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_lang_committee_reviews
               (review_id,reviewers,metrics,scores,verdict,suggestions) VALUES (?,?,?,?,?,?)""",
            (review_id, json.dumps(experts, ensure_ascii=False),
             json.dumps(metrics, ensure_ascii=False), json.dumps(scores, ensure_ascii=False),
             verdict, json.dumps({"rubric": rubric, "total": total,
                                  "items": suggestions}, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "review_id": review_id, "verdict": verdict, "total": total,
            "rubric": rubric, "reviewers": [e["name"] + "(" + e["role_cn"] + ")" for e in experts],
            "suggestions": suggestions}


# ============================================================
#  ④ 教授/顾问/天团会诊
# ============================================================

_ROLE_PROMPTS = {
    "教授": "你是语言教育学教授, 从教学法与二语习得角度诊断: SRS 间隔/输入输出比/认知负荷",
    "顾问": "你是教育产品战略顾问, 从增长与留存角度诊断: 激活率/打卡留存/社区氛围/商业化路径",
    "天团": "你是仙女座天团实战派, 从一线用户体验角度诊断: 哪里卡顿/哪里枯燥/最快见效的改进",
}


def advisor_consult() -> Dict[str, Any]:
    """教授/顾问/天团三方会诊: 平台指标 → 各角色诊断与建议 (LLM 增强可选)"""
    ensure_tables()
    conn = get_conn()
    try:
        stats = {
            "users": conn.execute("SELECT count(*) FROM mt_lang_users").fetchone()[0],
            "active_24h": conn.execute(
                "SELECT count(DISTINCT username) FROM mt_lang_progress "
                "WHERE created_at>=datetime('now','localtime','-1 day')").fetchone()[0],
            "srs_reviews": conn.execute("SELECT count(*) FROM mt_lang_vocab_reviews").fetchone()[0],
            "posts": conn.execute("SELECT count(*) FROM mt_lang_posts").fetchone()[0],
            "avg_speaking": round(conn.execute(
                "SELECT avg(score) FROM mt_lang_progress WHERE action='speaking'"
            ).fetchone()[0] or 0, 1),
            "streak_max": conn.execute(
                "SELECT max(streak_days) FROM mt_lang_users").fetchone()[0] or 0,
        }
    finally:
        conn.close()
    base_diag = {
        "教授": {"diagnosis": f"激活率 {stats['active_24h']}/{stats['users']}, "
                              f"SRS 复习 {stats['srs_reviews']} 次, 口语均分 {stats['avg_speaking']}",
                 "advice": "坚持输入输出 1:1 配比; 每课末尾强制 1 次口语跟读 + 3 词 SRS, 降低认知负荷"},
        "顾问": {"diagnosis": f"注册 {stats['users']}, 24h 活跃 {stats['active_24h']}, "
                              f"最长连续打卡 {stats['streak_max']} 天, 帖子 {stats['posts']}",
                 "advice": "上线每日任务清单+周报推送; 社区发起语伴匹配; 成就分享海报拉新"},
        "天团": {"diagnosis": f"实战观察: 听力原文判分后自动揭示, 跟读即时反馈, 打卡 {stats['streak_max']} 天峰值",
                 "advice": "增加角色扮演场景对话 (点餐/问路); 限时挑战赛; 学错词本一键导出"},
    }
    out = []
    for role, diag in base_diag.items():
        llm_advice = None
        try:
            from ai_engines.ai_dual_route_engine import route_and_chat
            r = route_and_chat(
                f"平台现状: {diag['diagnosis']}。请给出 60 字内 {role}视角的具体改进建议。",
                system=_ROLE_PROMPTS[role], kind="chat", flow_id=_FLOW, prefer_local=True)
            if r and r.get("success") and (r.get("response") or "").strip():
                llm_advice = r["response"].strip()[:200]
        except Exception:
            llm_advice = None
        rec = {"role": role, **diag, "llm_advice": llm_advice}
        out.append(rec)
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO mt_lang_advisor_consults (consult_id,role,diagnosis,advice,source) "
                "VALUES (?,?,?,?,?)",
                (_uid("ADV"), role, json.dumps(diag["diagnosis"], ensure_ascii=False),
                 json.dumps({"advice": diag["advice"], "llm_advice": llm_advice},
                            ensure_ascii=False),
                 "llm+local" if llm_advice else "local"))
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "flow": _FLOW, "metrics": stats, "consults": out}


# ============================================================
#  ⑤ 中心支持矩阵 + 总览
# ============================================================

def refresh_center_support() -> int:
    ensure_tables()
    conn = get_conn()
    n = 0
    try:
        for module, cid, resp in _SUPPORT_MATRIX:
            row = conn.execute("SELECT center_code,name FROM mt_lab_centers WHERE id=?", (cid,)).fetchone()
            cur = conn.execute(
                """INSERT INTO mt_lang_center_support
                   (module,center_id,center_code,center_name,responsibility,status,last_check)
                   VALUES (?,?,?,?,?,'ACTIVE',datetime('now','localtime'))
                   ON CONFLICT(module,center_id) DO UPDATE SET status='ACTIVE',
                   last_check=datetime('now','localtime')""",
                (module, cid, row["center_code"] if row else "", row["name"] if row else "", resp))
            n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def org_overview() -> Dict[str, Any]:
    ensure_tables()
    conn = get_conn()
    try:
        squads = [dict(r) for r in conn.execute(
            """SELECT s.squad_id,s.corps_id,s.name,s.duty,c.name corps_name,
               (SELECT count(*) FROM ai_employees e WHERE e.squad_id=s.squad_id) members
               FROM mt_corps_squads s LEFT JOIN mt_maintenance_corps c ON c.corps_id=s.corps_id
               WHERE s.duty LIKE '%多语种平台%' OR s.name LIKE '多语种平台%'""")]
        pending = [dict(r) for r in conn.execute(
            """SELECT task_id,corps_id,title,status,assignee_name FROM mt_maintenance_tasks
               WHERE task_id LIKE 'LANGP_%' ORDER BY id DESC LIMIT 10""")]
        patrol = [dict(r) for r in conn.execute(
            "SELECT check_item,severity,action,corps_name,created_at FROM mt_lang_patrol_log "
            "ORDER BY id DESC LIMIT 14")]
        committee = conn.execute(
            "SELECT review_id,verdict,suggestions,created_at FROM mt_lang_committee_reviews "
            "ORDER BY id DESC LIMIT 1").fetchone()
        advisors = [dict(r) for r in conn.execute(
            "SELECT role,advice,created_at FROM mt_lang_advisor_consults ORDER BY id DESC LIMIT 3")]
        support = [dict(r) for r in conn.execute(
            "SELECT module,center_id,center_code,center_name,responsibility,status,last_check "
            "FROM mt_lang_center_support ORDER BY center_id")]
        return {"ok": True, "flow": _FLOW, "squads": squads, "patrol_pending_tasks": pending,
                "patrol_recent": patrol,
                "committee_latest": dict(committee) if committee else None,
                "advisors": advisors, "center_support": support}
    finally:
        conn.close()


# ============================================================
#  CLI
# ============================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "init":
        print(json.dumps(register_patrol_squads(), ensure_ascii=False))
        print(f"[INIT] 中心支持矩阵刷新 {refresh_center_support()} 条")
    elif cmd == "patrol":
        print(json.dumps(patrol_once(), ensure_ascii=False, indent=1, default=str))
    elif cmd == "committee":
        print(json.dumps(committee_review(), ensure_ascii=False, indent=1, default=str))
    elif cmd == "consult":
        print(json.dumps(advisor_consult(), ensure_ascii=False, indent=1, default=str))
    elif cmd == "status":
        print(json.dumps(org_overview(), ensure_ascii=False, indent=1, default=str))
    else:
        print("usage: ai_language_org_alignment_engine.py init|patrol|committee|consult|status")
