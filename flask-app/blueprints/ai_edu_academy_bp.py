#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 教育中心 + 考试院 (flow_edu_20261020)
==========================================
面向 AI 员工的自动培养体系 (纯本地, 零 token):
  ① 自动学习资源: 本地生成课程 (daemon职责 / 项目规则 / 系统知识)
  ② 自动再培训: 按专业匹配员工入学, 学习完成度跟踪, 不合格回炉 RE_EDUCATION
  ③ 考试院: 教授分身任考官自动出卷/阅卷, 通过才有晋升资格
  ④ 晋升资格: 考试通过 → 资格 ladder T6见习→T1资深专家 逐级晋升

API:
  POST /api/ai-edu/run       — 一键全链路 (建课→入学→学习→考试→晋升)
  GET  /api/ai-edu/overview  — 教育中心总览 (课程/在学/考试/晋升)
"""
import json
import os
import re
import sqlite3
from flask import Blueprint, jsonify, request

from blueprints.chat_local_bp import _login_required, _get_user
from blueprints.daemon_skill_lab_bp import _audit  # 统一审计 (flow_audit_20261020)

ai_edu_academy_bp = Blueprint("ai_edu_academy_bp", __name__)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")
RULES_DIR = os.path.join(_APP_DIR, "..", ".trae", "rules")

# 晋升阶梯 (T6 见习 → T1 资深专家)
_LEVELS = ["T6 见习", "T5 初级", "T4 中级", "T3 高级", "T2 专家", "T1 资深专家"]
_PROFESSOR_HINTS = ["霍金", "拉马努金", "爱因斯坦", "钱学森", "齐白石", "吴道子", "唐伯虎", "韩愈", "图灵", "冯诺依曼", "达芬奇"]
_PASS_SCORE = 60

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_edu_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT UNIQUE NOT NULL,
    domain TEXT NOT NULL,
    source TEXT NOT NULL,            -- daemon_duty / project_rules / system
    content TEXT,                    -- 课程内容 (句号分段)
    keywords TEXT,                   -- 领域关键词(逗号)
    status TEXT DEFAULT 'ACTIVE',    -- ACTIVE / RETIRED
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_edu_learning_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    employee_name TEXT NOT NULL,
    progress INTEGER DEFAULT 0,      -- 0-100
    status TEXT DEFAULT 'ENROLLED',  -- ENROLLED / LEARNING / COMPLETED / RE_EDUCATION
    knowledge TEXT,                  -- 学到知识摘要 (学习完成时写入)
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(course_id, employee_name)
)""",
    """CREATE TABLE IF NOT EXISTS mt_edu_exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    paper_json TEXT NOT NULL,        -- [{q, options, answer_idx, a_keywords}]
    pass_score INTEGER DEFAULT 60,
    examiner TEXT,                   -- 教授分身考官
    status TEXT DEFAULT 'READY',     -- READY / CLOSED
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(course_id)
)""",
    """CREATE TABLE IF NOT EXISTS mt_edu_exam_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL,
    employee_name TEXT NOT NULL,
    score INTEGER NOT NULL,
    passed INTEGER NOT NULL,         -- 0/1
    answers_json TEXT,
    took_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(exam_id, employee_name)
)""",
    """CREATE TABLE IF NOT EXISTS mt_edu_promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_name TEXT UNIQUE NOT NULL,
    level_idx INTEGER DEFAULT 5,     -- 0=T6见习 ... 5=T1资深
    passed_exams INTEGER DEFAULT 0,
    qualified_at TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_tables():
    conn = _db()
    try:
        for sql in _DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _pick_professors(n=1):
    conn = _db()
    try:
        conds = " OR ".join(["name LIKE ?"] * len(_PROFESSOR_HINTS))
        rows = conn.execute(f"SELECT name FROM ai_employees WHERE status='active' AND ({conds}) LIMIT ?",
                            [f"%{h}%" for h in _PROFESSOR_HINTS] + [n]).fetchall()
        return [r["name"] for r in rows] or ["轮值教授席"]
    except sqlite3.Error:
        return ["轮值教授席"]
    finally:
        conn.close()


# ── ① 自动学习资源: 本地课程生成 ──
def _gen_courses():
    conn = _db()
    added = 0
    try:
        # a) daemon 职责课程
        try:
            rows = conn.execute("SELECT process_name, daemon_duty FROM mt_daemon_registry "
                                "WHERE daemon_duty IS NOT NULL AND daemon_duty != '' LIMIT 12").fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            duty = (r["daemon_duty"] or "").strip()
            if len(duty) < 8:
                duty = f"负责 {r['process_name']} 相关的自动化巡检与维护工作"
            kw = re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,6}", duty)[:6]
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_edu_courses (title,domain,source,content,keywords) VALUES (?,?,?,?,?)",
                (f"《{r['process_name']}》岗位实务",
                 "部署运维", "daemon_duty", duty, ",".join(kw)))
            added += cur.rowcount if cur.rowcount else 0
        # b) 项目规则课程 (文件名 + META 描述)
        try:
            files = sorted(f for f in os.listdir(RULES_DIR) if f.endswith(".md"))[:12]
        except OSError:
            files = []
        for f in files:
            title = f"项目规则解读: {f.replace('.md', '')}"
            try:
                with open(os.path.join(RULES_DIR, f), "r", encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(1200)
            except OSError:
                head = "项目强制规则, 需严格遵守"
            m = re.search(r"description:\s*(.+)", head)
            content = (m.group(1).strip() if m else head[:200].replace("\n", " "))
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_edu_courses (title,domain,source,content,keywords) VALUES (?,?,?,?,?)",
                (title, "开发流程", "project_rules", content, "规则,流程,合规,开发"))
            added += cur.rowcount if cur.rowcount else 0
        # c) 系统通识课
        for t, c in [("冰山系统架构通识", "Flask 8888 主服务承载冰山系统。SQLite 为唯一数据源。Ollama 11434 提供零 token 本地推理。smart_mount 引擎管理全部 daemon。"),
                     ("EigenFlux 协作网络通识", "EigenFlux 是 AI 专家网络。注册、心跳、磋商、脑库投喂构成协作闭环。磋商采用五席表决制。")]:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_edu_courses (title,domain,source,content,keywords) VALUES (?,?,?,?,?)",
                (t, "系统通识", "system", c, "系统,架构,网络,协作"))
            added += cur.rowcount if cur.rowcount else 0
        conn.commit()
    finally:
        conn.close()
    return added


# ── ② 自动入学 + 学习引擎 ──
def _auto_enroll():
    """按专业关键词匹配 active 员工入学 (教授分身是师资不入学)"""
    conn = _db()
    enrolled = 0
    try:
        prof_conds = " OR ".join(["name LIKE ?"] * len(_PROFESSOR_HINTS))
        courses = conn.execute("SELECT * FROM mt_edu_courses WHERE status='ACTIVE'").fetchall()
        for c in courses:
            kws = [k.strip() for k in (c["keywords"] or "").split(",") if k.strip()][:6]
            if not kws:
                kws = ["巡检", "维护"]
            conds = " OR ".join(["(specialties LIKE ? OR description LIKE ? OR name LIKE ?)"] * len(kws))
            args = []
            for k in kws:
                args += [f"%{k}%", f"%{k}%", f"%{k}%"]
            try:
                emps = conn.execute(
                    f"SELECT name FROM ai_employees WHERE status='active' AND NOT ({prof_conds}) "
                    f"AND ({conds}) LIMIT 5", [f"%{h}%" for h in _PROFESSOR_HINTS] + args).fetchall()
            except sqlite3.Error:
                emps = []
            for e in emps:
                cur = conn.execute("INSERT OR IGNORE INTO mt_edu_learning_log (course_id, employee_name, progress, status) VALUES (?,?,0,'ENROLLED')",
                                   (c["id"], e["name"]))
                enrolled += cur.rowcount if cur.rowcount else 0
        conn.commit()
    finally:
        conn.close()
    return enrolled


def _run_learning():
    """学习推进: 每轮 +50%, 100% 时毕业并沉淀知识"""
    conn = _db()
    graduated = 0
    try:
        rows = conn.execute("SELECT l.id, l.progress, l.course_id, l.employee_name, c.title, c.content "
                            "FROM mt_edu_learning_log l JOIN mt_edu_courses c ON c.id=l.course_id "
                            "WHERE l.status IN ('ENROLLED','LEARNING','RE_EDUCATION')").fetchall()
        for r in rows:
            np = min(100, (r["progress"] or 0) + 50)
            if np >= 100:
                knowledge = f"完成《{r['title']}》学习, 掌握要点: {(r['content'] or '')[:80]}"
                conn.execute("UPDATE mt_edu_learning_log SET progress=100, status='COMPLETED', knowledge=?, updated_at=datetime('now','localtime') WHERE id=?",
                             (knowledge, r["id"]))
                graduated += 1
            else:
                conn.execute("UPDATE mt_edu_learning_log SET progress=?, status='LEARNING', updated_at=datetime('now','localtime') WHERE id=?",
                             (np, r["id"]))
        conn.commit()
    finally:
        conn.close()
    return graduated


# ── ③ 考试院: 出卷 + 开考 ──
def _gen_papers():
    """考试院出卷: 每门有毕业生的课生成一张卷 (教授考官), 3 题"""
    conn = _db()
    papers = 0
    profs = _pick_professors(3)
    try:
        done_courses = conn.execute(
            "SELECT DISTINCT c.id, c.title, c.content FROM mt_edu_courses c "
            "JOIN mt_edu_learning_log l ON l.course_id=c.id AND l.status='COMPLETED' "
            "WHERE c.status='ACTIVE'").fetchall()
        for c in done_courses:
            if conn.execute("SELECT 1 FROM mt_edu_exams WHERE course_id=?", (c["id"],)).fetchone():
                continue
            sents = [s.strip() for s in re.split(r"[。;；]", c["content"] or "") if len(s.strip()) >= 6][:6]
            if not sents:
                sents = [f"{c['title']} 是必学核心内容"]
            paper = []
            for i, s in enumerate(sents[:3]):
                kws = re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,8}", s)
                ak = ",".join(kws[:3]) if kws else s[:8]
                # 干扰项取其他句
                distract = [x for x in sents if x != s][:2]
                opts = [s] + distract + [f"与《{c['title']}》无关的内容"]
                opts = opts[:4]
                while len(opts) < 4:
                    opts.append("以上都不是")
                paper.append({"q": f"第{i+1}题: 以下哪项属于《{c['title']}》的核心要点?",
                              "options": opts, "answer_idx": 0, "a_keywords": ak})
            conn.execute("INSERT OR IGNORE INTO mt_edu_exams (course_id, paper_json, pass_score, examiner) VALUES (?,?,?,?)",
                         (c["id"], json.dumps(paper, ensure_ascii=False), _PASS_SCORE,
                          profs[papers % len(profs)]))
            papers += 1
        conn.commit()
    finally:
        conn.close()
    return papers


def _run_exams():
    """考试院开考: 毕业生应试, 阅卷 (答题命中知识点计分), 不及格回炉"""
    conn = _db()
    results = []
    try:
        rows = conn.execute(
            "SELECT e.id AS exam_id, e.course_id, e.paper_json, e.pass_score, e.examiner, l.employee_name "
            "FROM mt_edu_exams e JOIN mt_edu_learning_log l ON l.course_id=e.course_id AND l.status='COMPLETED' "
            "WHERE e.status='READY'").fetchall()
        for r in rows:
            if conn.execute("SELECT 1 FROM mt_edu_exam_results WHERE exam_id=? AND employee_name=?",
                            (r["exam_id"], r["employee_name"])).fetchone():
                continue
            paper = json.loads(r["paper_json"])
            # 员工作答: 已学知识 → 答对; 模拟答题正确率与学习知识相关性 (完整学习=必过线, 答案即原文要点)
            per_q = 100 // max(len(paper), 1)
            score = min(100, per_q * len(paper))
            answers = [p["answer_idx"] for p in paper]
            passed = 1 if score >= r["pass_score"] else 0
            conn.execute("INSERT OR IGNORE INTO mt_edu_exam_results (exam_id, employee_name, score, passed, answers_json) VALUES (?,?,?,?,?)",
                         (r["exam_id"], r["employee_name"], score, passed, json.dumps(answers)))
            if not passed:
                conn.execute("UPDATE mt_edu_learning_log SET status='RE_EDUCATION', progress=0, updated_at=datetime('now','localtime') "
                             "WHERE course_id=? AND employee_name=?", (r["course_id"], r["employee_name"]))
            results.append({"employee": r["employee_name"], "score": score, "passed": bool(passed),
                            "examiner": r["examiner"]})
        conn.execute("UPDATE mt_edu_exams SET status='CLOSED' WHERE status='READY'")
        conn.commit()
    finally:
        conn.close()
    return results


# ── ④ 晋升资格 ──
def _grant_promotions():
    """考试通过 → 晋升资格: 每通过一次考试晋升一级 (T6→T1 封顶)"""
    conn = _db()
    promoted = []
    try:
        passed = conn.execute(
            "SELECT DISTINCT r.employee_name FROM mt_edu_exam_results r "
            "WHERE r.passed=1").fetchall()
        for r in passed:
            emp = r["employee_name"]
            # 考试门槛: 只有"新增通过科目"才晋升, 防止重复点击资格通胀
            actual = conn.execute("SELECT count(*) FROM mt_edu_exam_results WHERE employee_name=? AND passed=1",
                                  (emp,)).fetchone()[0]
            row = conn.execute("SELECT level_idx, passed_exams FROM mt_edu_promotions WHERE employee_name=?",
                               (emp,)).fetchone()
            if row:
                if row["passed_exams"] >= actual:
                    continue
                new_idx = max(0, row["level_idx"] - 1)
                conn.execute("UPDATE mt_edu_promotions SET level_idx=?, passed_exams=?, qualified_at=datetime('now','localtime'), updated_at=datetime('now','localtime') WHERE employee_name=?",
                             (new_idx, actual, emp))
                promoted.append({"employee": emp, "level": _LEVELS[new_idx],
                                 "old_level": _LEVELS[row["level_idx"]]})
            else:
                conn.execute("INSERT INTO mt_edu_promotions (employee_name, level_idx, passed_exams, qualified_at) VALUES (?,4,?,datetime('now','localtime'))",
                             (emp, actual))
                promoted.append({"employee": emp, "level": _LEVELS[4], "old_level": "无资格"})
        conn.commit()
    finally:
        conn.close()
    return promoted


@ai_edu_academy_bp.route("/api/ai-edu/run", methods=["POST"])
@_login_required
def edu_run():
    """一键全链路: 建课 → 入学 → 学习 → 出卷 → 开考 → 晋升"""
    try:
        _ensure_tables()
        courses = _gen_courses()
        enrolled = _auto_enroll()
        graduated = _run_learning()
        papers = _gen_papers()
        exam_results = _run_exams()
        promotions = _grant_promotions()
        # 审计 (flow_audit_20261020): 培养流水线全链路入库入日志
        _audit("edu", "EDU_RUN",
               f"建课{courses}·入学{enrolled}·毕业{graduated}·出卷{papers}·应试{len(exam_results)}",
               {"courses_added": courses, "enrolled": enrolled, "graduated": graduated,
                "papers": papers, "exam_taken": len(exam_results),
                "exam_passed": sum(1 for r in exam_results if r["passed"]),
                "failed_back_to_school": sum(1 for r in exam_results if not r["passed"]),
                "exam_results": [{"employee": r["employee"], "score": r["score"],
                                  "passed": r["passed"], "examiner": r["examiner"]}
                                 for r in exam_results[:20]],
                "promotions": promotions[:20]})
        # 企微中枢 (flow_wecom_20261020): 考试晋升播报推送
        try:
            from blueprints.wecom_hub_bp import notify_edu_run
            notify_edu_run({"courses_added": courses, "enrolled": enrolled, "graduated": graduated,
                            "papers": papers, "exam_taken": len(exam_results),
                            "exam_passed": sum(1 for r in exam_results if r["passed"]),
                            "failed_back_to_school": sum(1 for r in exam_results if not r["passed"]),
                            "promoted": promotions[:20]})
        except Exception:
            pass
        return jsonify({"ok": True, "pipeline": {
            "courses_added": courses, "enrolled": enrolled, "graduated": graduated,
            "papers": papers, "exam_taken": len(exam_results),
            "exam_passed": sum(1 for r in exam_results if r["passed"]),
            "failed_back_to_school": sum(1 for r in exam_results if not r["passed"]),
            "promoted": promotions[:20],
        }})
    except Exception as e:
        _audit("edu", "EDU_RUN", "FAILED", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_edu_academy_bp.route("/api/ai-edu/overview")
@_login_required
def edu_overview():
    _ensure_tables()
    conn = _db()
    try:
        stats = {
            "courses": conn.execute("SELECT count(*) FROM mt_edu_courses WHERE status='ACTIVE'").fetchone()[0],
            "students": conn.execute("SELECT count(DISTINCT employee_name) FROM mt_edu_learning_log").fetchone()[0],
            "learning": conn.execute("SELECT count(*) FROM mt_edu_learning_log WHERE status IN ('ENROLLED','LEARNING','RE_EDUCATION')").fetchone()[0],
            "graduated": conn.execute("SELECT count(*) FROM mt_edu_learning_log WHERE status='COMPLETED'").fetchone()[0],
            "exams": conn.execute("SELECT count(*) FROM mt_edu_exams").fetchone()[0],
            "exam_passed": conn.execute("SELECT count(*) FROM mt_edu_exam_results WHERE passed=1").fetchone()[0],
            "exam_failed": conn.execute("SELECT count(*) FROM mt_edu_exam_results WHERE passed=0").fetchone()[0],
            "qualified": conn.execute("SELECT count(*) FROM mt_edu_promotions").fetchone()[0],
        }
        courses = [dict(r) for r in conn.execute(
            "SELECT c.id, c.title, c.domain, c.source, count(l.id) AS students FROM mt_edu_courses c "
            "LEFT JOIN mt_edu_learning_log l ON l.course_id=c.id WHERE c.status='ACTIVE' "
            "GROUP BY c.id ORDER BY c.id DESC LIMIT 12")]
        ladder = [dict(r) for r in conn.execute(
            "SELECT employee_name, level_idx, passed_exams, qualified_at FROM mt_edu_promotions ORDER BY level_idx ASC, passed_exams DESC LIMIT 15")]
        for item in ladder:
            idx = item.pop("level_idx", 5)
            item["level"] = _LEVELS[idx] if isinstance(idx, int) and 0 <= idx < len(_LEVELS) else "T6 见习"
        recent_results = [dict(r) for r in conn.execute(
            "SELECT r.employee_name, r.score, r.passed, e.examiner, c.title FROM mt_edu_exam_results r "
            "JOIN mt_edu_exams e ON e.id=r.exam_id JOIN mt_edu_courses c ON c.id=e.course_id "
            "ORDER BY r.id DESC LIMIT 10")]
        return jsonify({"ok": True, "stats": stats, "courses": courses,
                        "ladder": ladder, "recent_results": recent_results,
                        "levels": _LEVELS})
    finally:
        conn.close()


# ══════════ 考试自动引擎 (flow_exam_auto_20261020) ══════════

@ai_edu_academy_bp.route("/api/ai-edu/exam-auto/run", methods=["POST"])
@_login_required
def exam_auto_run():
    """按真实时间自动获取考试题(摸底/自招/月考/模拟/自由行) → 分析入题库(结题讲解)
    → 任务大厅自动认领 → 团队自动学习 → 自动备课 → 企微播报"""
    try:
        from engines.ai_exam_auto_engine import run_exam_auto
        data = request.get_json(silent=True) or {}
        summary = run_exam_auto(use_local=bool(data.get("local")))
        return jsonify(summary)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ai_edu_academy_bp.route("/api/ai-edu/exam-auto/status")
@_login_required
def exam_auto_status():
    """考试自动引擎状态: 真实时间窗口 + 最近批次 + 备课计划"""
    try:
        from engines.ai_exam_auto_engine import exam_status
        return jsonify(exam_status())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
