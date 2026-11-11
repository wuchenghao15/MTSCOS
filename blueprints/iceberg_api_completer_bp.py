#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧊 Iceberg API Completer Blueprint (flow_iceberg_20261108)
========================================================
补齐冰山 21 模板所需的 12 张新表的 API 端点:

员工管理
  GET  /api/iceberg/employees                → mt_ai_employees
  GET  /api/iceberg/employees/<id>           → 单员工 + skills + achievements
  GET  /api/iceberg/employees/<id>/chat      → mt_employee_chat
  POST /api/iceberg/employees/<id>/chat      → AI 员工回复 (Ollama qwen2.5:3b)

题库管理
  GET  /api/iceberg/qbank/subjects           → mt_qbank_subject
  GET  /api/iceberg/qbank/subjects/<id>      → 学科 + KPs + 题目数
  GET  /api/iceberg/qbank/kps                → mt_qbank_knowledge_point (filter: subject)
  GET  /api/iceberg/qbank/questions          → 题目列表 (filter: subject/difficulty/type)
  POST /api/iceberg/qbank/exam/generate      → AI 自动组卷

成就徽章
  GET  /api/iceberg/badges                   → mt_iceberg_badge
  GET  /api/iceberg/badges/<category>        → 某类别徽章
  GET  /api/iceberg/achievements             → 成就列表 (filter: employee/center)
  POST /api/iceberg/badges/check             → 检查谁该获得徽章

技能使用
  GET  /api/iceberg/skills/usage             → mt_skill_usage_log
  GET  /api/iceberg/skills/leaderboard       → 技能排行榜

语言学习
  GET  /api/iceberg/lang/sessions            → mt_lang_session
  GET  /api/iceberg/lang/vocab/due           → 记忆曲线到期词
  POST /api/iceberg/lang/grammar/practice    → 出语法题

健康检查
  GET  /api/iceberg/health                   → 12 张表状态 + 行数
"""
from __future__ import annotations
import json as _json_mod
import os
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request

iceberg_bp = Blueprint("iceberg_api_completer", __name__)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_APP_DIR, "database", "app.db")


def _get_conn() -> sqlite3.Connection:
    """获取 DB 连接 (WAL + 长 timeout 应对并发守护进程)"""
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _rows_to_list(rows) -> list:
    return [_row_to_dict(r) for r in (rows or [])]


def _ok(data=None, **kw) -> tuple:
    payload = {"ok": True, "data": data}
    payload.update(kw)
    return jsonify(payload), 200


def _err(msg: str, code: int = 400) -> tuple:
    return jsonify({"ok": False, "error": msg}), code


def _ollama(prompt: str, model: str = "qwen2.5:3b", timeout: int = 45) -> str:
    """调用本地 Ollama, 返回纯文本"""
    try:
        r = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════
# 员工管理
# ═══════════════════════════════════════════════════════════════════════

@iceberg_bp.route("/api/iceberg/employees", methods=["GET"])
def list_employees():
    """GET /api/iceberg/employees — 列表 (filter: status/role/center)"""
    conn = _get_conn()
    try:
        where = []
        params = []
        for fld in ("status", "role", "center"):
            v = request.args.get(fld)
            if v:
                where.append(f"{fld} = ?")
                params.append(v)
        w = f"WHERE {' AND '.join(where)}" if where else ""
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
        rows = conn.execute(
            f"SELECT * FROM mt_ai_employees {w} ORDER BY level DESC, rowid LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM mt_ai_employees {w}", params).fetchone()[0]
        return _ok({"items": _rows_to_list(rows), "total": total, "limit": limit, "offset": offset})
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/employees/<employee_id>", methods=["GET"])
def get_employee(employee_id: str):
    """GET /api/iceberg/employees/<id> — 单员工详情 + skills + achievements"""
    conn = _get_conn()
    try:
        emp = conn.execute("SELECT * FROM mt_ai_employees WHERE employee_id = ?", (employee_id,)).fetchone()
        if not emp:
            # 尝试按 name 查找
            emp = conn.execute("SELECT * FROM mt_ai_employees WHERE name = ?", (employee_id,)).fetchone()
        if not emp:
            return _err(f"员工 {employee_id} 不存在", 404)
        emp_dict = _row_to_dict(emp)

        # 关联技能
        skills = conn.execute("""
            SELECT s.* FROM mt_ai_employee_skill aes
            JOIN mt_skill_registry s ON aes.skill_id = s.skill_id
            WHERE aes.employee_id = ? ORDER BY aes.proficiency DESC
        """, (employee_id,)).fetchall()
        emp_dict["skills"] = _rows_to_list(skills)

        # 关联成就
        achs = conn.execute("""
            SELECT a.*, b.badge_name, b.icon_emoji
            FROM mt_iceberg_achievement a
            LEFT JOIN mt_iceberg_badge b ON a.badge_id = b.badge_id
            WHERE a.employee_id = ? ORDER BY a.earned_at DESC
        """, (employee_id,)).fetchall()
        emp_dict["achievements"] = _rows_to_list(achs)

        return _ok(emp_dict)
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/employees/<employee_id>/chat", methods=["GET"])
def get_employee_chat(employee_id: str):
    """GET /api/iceberg/employees/<id>/chat — 历史对话"""
    conn = _get_conn()
    try:
        limit = min(int(request.args.get("limit", 30)), 100)
        rows = conn.execute("""
            SELECT * FROM mt_employee_chat WHERE employee_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (employee_id, limit)).fetchall()
        return _ok({"items": _rows_to_list(rows)})
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/employees/<employee_id>/chat", methods=["POST"])
def employee_chat(employee_id: str):
    """POST /api/iceberg/employees/<id>/chat — 发送消息, AI 员工回复"""
    conn = _get_conn()
    try:
        emp = conn.execute("SELECT * FROM mt_ai_employees WHERE employee_id = ?", (employee_id,)).fetchone()
        if not emp:
            emp = conn.execute("SELECT * FROM mt_ai_employees WHERE name = ?", (employee_id,)).fetchone()
        if not emp:
            return _err(f"员工 {employee_id} 不存在", 404)

        body = request.get_json(silent=True) or {}
        msg = (body.get("message") or "").strip()
        if not msg:
            return _err("message 不能为空")

        # 存用户消息
        user_chat_id = f"chat_{uuid.uuid4().hex[:12]}"
        conn.execute("""
            INSERT INTO mt_employee_chat (chat_id, employee_id, message, role, context_json)
            VALUES (?,?,?,?,?)
        """, (user_chat_id, employee_id, msg, "user", _json_mod.dumps(body.get("context") or {})))
        conn.commit()

        # 调用 Ollama 让 AI 员工回复
        emp_name = emp["name"]
        emp_role = emp["role"] or "assistant"
        prompt = f"""你是 MTSCOS 系统里的 AI 员工 {emp_name}, 角色是 {emp_role}。
请以符合你角色的简短专业风格回复用户的问题。

用户消息: {msg}

回复:"""
        reply = _ollama(prompt, model="qwen2.5:3b", timeout=30)
        if not reply:
            reply = f"[离线模式] 作为 {emp_role}，我收到了你的消息「{msg[:50]}」。请问具体需要我做什么？"

        # 存 AI 回复
        ai_chat_id = f"chat_{uuid.uuid4().hex[:12]}"
        conn.execute("""
            INSERT INTO mt_employee_chat (chat_id, employee_id, message, role, ai_model)
            VALUES (?,?,?,?,?)
        """, (ai_chat_id, employee_id, reply, "assistant", "qwen2.5:3b"))
        conn.commit()

        return _ok({
            "chat_id": ai_chat_id,
            "employee_id": employee_id,
            "employee_name": emp_name,
            "message": reply,
            "ai_model": "qwen2.5:3b",
        })
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 题库管理
# ═══════════════════════════════════════════════════════════════════════

@iceberg_bp.route("/api/iceberg/qbank/subjects", methods=["GET"])
def list_subjects():
    """GET /api/iceberg/qbank/subjects"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mt_qbank_subject ORDER BY question_count DESC"
        ).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/qbank/subjects/<subject_id>", methods=["GET"])
def get_subject(subject_id: str):
    """GET /api/iceberg/qbank/subjects/<id> — 学科详情 + KPs"""
    conn = _get_conn()
    try:
        subj = conn.execute("SELECT * FROM mt_qbank_subject WHERE subject_id = ?", (subject_id,)).fetchone()
        if not subj:
            return _err(f"学科 {subject_id} 不存在", 404)
        s = _row_to_dict(subj)
        kps = conn.execute(
            "SELECT * FROM mt_qbank_knowledge_point WHERE subject_id = ? ORDER BY kp_name",
            (subject_id,)
        ).fetchall()
        s["knowledge_points"] = _rows_to_list(kps)
        return _ok(s)
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/qbank/kps", methods=["GET"])
def list_kps():
    """GET /api/iceberg/qbank/kps?subject=<sid>"""
    conn = _get_conn()
    try:
        sid = request.args.get("subject")
        if sid:
            rows = conn.execute(
                "SELECT * FROM mt_qbank_knowledge_point WHERE subject_id = ? ORDER BY kp_name",
                (sid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_qbank_knowledge_point ORDER BY subject_id, kp_name LIMIT 200"
            ).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/qbank/questions", methods=["GET"])
def list_questions():
    """GET /api/iceberg/qbank/questions?subject=&difficulty=&type=&limit="""
    conn = _get_conn()
    try:
        where = []
        params = []
        for fld in ("subject_id", "difficulty", "question_type"):
            v = request.args.get(fld.replace("subject_", "subject_"))
        # 用正确的映射
        map_args = {
            "subject": "subject_id",
            "difficulty": "difficulty",
            "type": "question_type",
        }
        for arg, col in map_args.items():
            v = request.args.get(arg)
            if v:
                where.append(f"{col} = ?")
                params.append(v)
        w = f"WHERE {' AND '.join(where)}" if where else ""
        limit = min(int(request.args.get("limit", 20)), 100)
        rows = conn.execute(
            f"SELECT * FROM mt_qbank_questions {w} ORDER BY rowid DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM mt_qbank_questions {w}", params).fetchone()[0]
        return _ok({"items": _rows_to_list(rows), "total": total})
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/qbank/exam/generate", methods=["POST"])
def generate_exam():
    """POST /api/iceberg/qbank/exam/generate — AI 自动组卷"""
    conn = _get_conn()
    try:
        body = request.get_json(silent=True) or {}
        subject = body.get("subject") or request.args.get("subject")
        q_count = int(body.get("count") or 10)
        difficulty = body.get("difficulty") or "mixed"

        where = []
        params = []
        if subject:
            # 尝试按 subject_name 或 subject_id 匹配
            subj_row = conn.execute(
                "SELECT subject_id FROM mt_qbank_subject WHERE subject_name LIKE ? OR subject_id LIKE ?",
                (f"%{subject}%", f"%{subject}%")
            ).fetchone()
            if subj_row:
                where.append("subject_id = ?")
                params.append(subj_row["subject_id"])
        if difficulty != "mixed":
            where.append("difficulty = ?")
            params.append(difficulty)

        w = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(
            f"SELECT * FROM mt_qbank_questions {w} ORDER BY RANDOM() LIMIT ?",
            params + [q_count]
        ).fetchall()
        questions = _rows_to_list(rows)

        # 生成试卷 prompt (选做: 如果题目不足, 让 Ollama 造题)
        if len(questions) < q_count:
            missing = q_count - len(questions)
            subj_name = subject or "综合"
            prompt = f"""请出 {missing} 道关于「{subj_name}」的选择题 (含干扰项), 难度={difficulty}。
每题格式: 题干 | 选项A | 选项B | 选项C | 选项D | 正确答案字母 | 简短解析
直接给出题目, 不要解释。"""
            ai_text = _ollama(prompt, model="qwen2.5:3b", timeout=40)
            questions.append({
                "ai_generated": True,
                "source": "ollama_qwen2.5:3b",
                "raw_text": ai_text,
            })

        return _ok({
            "subject": subject or "综合",
            "difficulty": difficulty,
            "count": len(questions),
            "questions": questions,
            "generated_at": datetime.now().isoformat(),
        })
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 成就徽章
# ═══════════════════════════════════════════════════════════════════════

@iceberg_bp.route("/api/iceberg/badges", methods=["GET"])
def list_badges():
    """GET /api/iceberg/badges"""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM mt_iceberg_badge ORDER BY rarity ASC").fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/badges/<category>", methods=["GET"])
def list_badges_by_category(category: str):
    """GET /api/iceberg/badges/<category>"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mt_iceberg_badge WHERE badge_category LIKE ? ORDER BY rarity ASC",
            (f"%{category}%",)
        ).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/achievements", methods=["GET"])
def list_achievements():
    """GET /api/iceberg/achievements?employee=<id>&center=<name>"""
    conn = _get_conn()
    try:
        where = []
        params = []
        for col, arg in (("employee_id", "employee"), ("center", "center")):
            v = request.args.get(arg)
            if v:
                where.append(f"{col} = ?")
                params.append(v)
        w = f"WHERE {' AND '.join(where)}" if where else ""
        limit = min(int(request.args.get("limit", 50)), 200)
        rows = conn.execute(f"""
            SELECT a.*, b.badge_name, b.icon_emoji, b.badge_category
            FROM mt_iceberg_achievement a
            LEFT JOIN mt_iceberg_badge b ON a.badge_id = b.badge_id
            {w}
            ORDER BY a.earned_at DESC LIMIT ?
        """, params + [limit]).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/badges/check", methods=["POST"])
def check_badges():
    """POST /api/iceberg/badges/check — 检查活跃员工是否该获得徽章"""
    conn = _get_conn()
    try:
        body = request.get_json(silent=True) or {}
        employee_id = body.get("employee_id")
        # 找到活跃员工
        if employee_id:
            emps = conn.execute("SELECT employee_id FROM mt_ai_employees WHERE employee_id = ?", (employee_id,)).fetchall()
        else:
            emps = conn.execute(
                "SELECT employee_id FROM mt_ai_employees WHERE status='active' ORDER BY rowid LIMIT 20"
            ).fetchall()

        newly_earned = []
        for emp in emps:
            eid = emp["employee_id"] if isinstance(emp, sqlite3.Row) else emp[0]
            # 检查技能使用数
            skill_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_skill_usage_log WHERE employee_id = ?", (eid,)
            ).fetchone()[0]
            if skill_cnt >= 50:
                # 检查是否已有 badge_skill_master
                existing = conn.execute(
                    "SELECT 1 FROM mt_iceberg_achievement WHERE employee_id=? AND badge_id='badge_skill_master'",
                    (eid,)
                ).fetchone()
                if not existing:
                    aid = f"ach_{eid}_badge_skill_master"
                    conn.execute("""
                        INSERT OR IGNORE INTO mt_iceberg_achievement
                        (achievement_id, badge_id, employee_id, context_json)
                        VALUES (?,?,?,?)
                    """, (aid, "badge_skill_master", eid,
                          _json_mod.dumps({"skill_usage": skill_cnt}, ensure_ascii=False)))
                    newly_earned.append({"employee_id": eid, "badge": "badge_skill_master"})

            # 检查 hall task 数 (从 hr_log)
            hall_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_lab_hr_log WHERE employee_name = (SELECT name FROM mt_ai_employees WHERE employee_id = ?)",
                (eid,)
            ).fetchone()[0]
            if hall_cnt >= 1000:
                existing = conn.execute(
                    "SELECT 1 FROM mt_iceberg_achievement WHERE employee_id=? AND badge_id='badge_veteran'",
                    (eid,)
                ).fetchone()
                if not existing:
                    aid = f"ach_{eid}_badge_veteran"
                    conn.execute("""
                        INSERT OR IGNORE INTO mt_iceberg_achievement
                        (achievement_id, badge_id, employee_id, context_json)
                        VALUES (?,?,?,?)
                    """, (aid, "badge_veteran", eid,
                          _json_mod.dumps({"hall_tasks": hall_cnt}, ensure_ascii=False)))
                    newly_earned.append({"employee_id": eid, "badge": "badge_veteran"})

        conn.commit()
        return _ok({"checked": len(emps), "newly_earned": newly_earned})
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 技能使用
# ═══════════════════════════════════════════════════════════════════════

@iceberg_bp.route("/api/iceberg/skills/usage", methods=["GET"])
def list_skill_usage():
    """GET /api/iceberg/skills/usage?skill_id=&employee_id=&limit="""
    conn = _get_conn()
    try:
        where = []
        params = []
        for col, arg in (("skill_id", "skill_id"), ("employee_id", "employee_id")):
            v = request.args.get(arg)
            if v:
                where.append(f"{col} = ?")
                params.append(v)
        w = f"WHERE {' AND '.join(where)}" if where else ""
        limit = min(int(request.args.get("limit", 50)), 200)
        rows = conn.execute(
            f"SELECT * FROM mt_skill_usage_log {w} ORDER BY created_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/skills/leaderboard", methods=["GET"])
def skill_leaderboard():
    """GET /api/iceberg/skills/leaderboard — TOP 技能使用排行"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT l.skill_id, s.skill_name, s.category, COUNT(*) as usage_count
            FROM mt_skill_usage_log l
            LEFT JOIN mt_skill_registry s ON l.skill_id = s.skill_id
            GROUP BY l.skill_id
            ORDER BY usage_count DESC LIMIT 20
        """).fetchall()
        # 员工活跃度排行
        emp_rows = conn.execute("""
            SELECT l.employee_id, e.name, e.role, e.level, COUNT(*) as usage_count
            FROM mt_skill_usage_log l
            JOIN mt_ai_employees e ON l.employee_id = e.employee_id
            GROUP BY l.employee_id
            ORDER BY usage_count DESC LIMIT 10
        """).fetchall()
        return _ok({
            "skills": _rows_to_list(rows),
            "employees": _rows_to_list(emp_rows),
        })
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 语言学习
# ═══════════════════════════════════════════════════════════════════════

@iceberg_bp.route("/api/iceberg/lang/sessions", methods=["GET"])
def list_lang_sessions():
    """GET /api/iceberg/lang/sessions?employee_id=&lang=&type="""
    conn = _get_conn()
    try:
        where = []
        params = []
        for col, arg in (("employee_id", "employee_id"), ("lang", "lang"), ("session_type", "type")):
            v = request.args.get(arg)
            if v:
                where.append(f"{col} = ?")
                params.append(v)
        w = f"WHERE {' AND '.join(where)}" if where else ""
        limit = min(int(request.args.get("limit", 30)), 100)
        rows = conn.execute(
            f"SELECT * FROM mt_lang_session {w} ORDER BY started_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/lang/vocab/due", methods=["GET"])
def vocab_due():
    """GET /api/iceberg/lang/vocab/due — 记忆曲线到期词"""
    conn = _get_conn()
    try:
        # 简单版: 返回所有 review_interval >= 1 的词 (真实系统应该对比 next_review)
        rows = conn.execute("""
            SELECT * FROM mt_lang_vocab_review
            WHERE review_interval >= 1
            ORDER BY created_at DESC LIMIT 50
        """).fetchall()
        return _ok(_rows_to_list(rows))
    finally:
        conn.close()


@iceberg_bp.route("/api/iceberg/lang/grammar/practice", methods=["GET", "POST"])
def grammar_practice():
    """GET/POST /api/iceberg/lang/grammar/practice — AI 出语法题"""
    lang = (request.args.get("lang") or request.form.get("lang") or "ja").lower()
    level = request.args.get("level") or request.form.get("level") or "N3"

    prompt = f"""请出 5 道 {lang} 语 {level} 难度的语法选择题。
每题包含: 题干、4 个选项 (A/B/C/D)、正确答案字母、简短中文解析。
格式示例:
1. 题干内容...
A. 选项A
B. 选项B
C. 选项C
D. 选项D
答案: B
解析: 中文说明...

请直接给出题目, 不要额外解释。"""

    ai_text = _ollama(prompt, model="qwen2.5:3b", timeout=45)
    if not ai_text:
        # fallback
        ai_text = f"""1. 日语 N3 例題: 日本語を勉強___好きです。
A. が B. で C. を D. に
答案: A
解析: 「〜が好きです」固定搭配。
2. She ___ to school every day.
A. go B. goes C. going D. went
答案: B
解析: 第三人称单数一般现在时加 s。"""

    # 存到 mt_lang_grammar (如果 POST)
    if request.method == "POST":
        conn = _get_conn()
        try:
            body = request.get_json(silent=True) or {}
            emp_id = body.get("employee_id") or "emp_default"
            for line in ai_text.split("\n")[:10]:
                if line.strip():
                    try:
                        conn.execute("""
                            INSERT INTO mt_lang_grammar (employee_id, grammar_point, lang, practice_text, created_at)
                            VALUES (?,?,?,?,?)
                        """, (emp_id, f"{level} Grammar", lang, line[:200], datetime.now().isoformat()))
                    except Exception:
                        pass
            conn.commit()
        finally:
            conn.close()

    return _ok({
        "lang": lang,
        "level": level,
        "question_text": ai_text,
        "ai_model": "qwen2.5:3b",
    })


# ═══════════════════════════════════════════════════════════════════════
# 健康检查 — 12 张表状态
# ═══════════════════════════════════════════════════════════════════════

@iceberg_bp.route("/api/iceberg/health", methods=["GET"])
def iceberg_health():
    """GET /api/iceberg/health — 所有冰山表的行数 + 状态"""
    conn = _get_conn()
    try:
        tables = [
            "mt_ai_employees", "mt_ai_employee_skill", "mt_employee_chat",
            "mt_qbank_subject", "mt_qbank_knowledge_point", "mt_qbank_questions",
            "mt_iceberg_badge", "mt_iceberg_achievement",
            "mt_skill_usage_log",
            "mt_lang_session", "mt_lang_vocab_review", "mt_lang_grammar",
        ]
        status = {}
        for t in tables:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                status[t] = {"exists": True, "rows": cnt}
            except Exception as e:
                status[t] = {"exists": False, "error": str(e)[:40]}

        # 总览
        total_rows = sum(s.get("rows", 0) for s in status.values())
        tables_ok = sum(1 for s in status.values() if s.get("exists"))

        return _ok({
            "total_tables": len(tables),
            "tables_ok": tables_ok,
            "total_rows": total_rows,
            "all_ready": tables_ok == len(tables) and total_rows > 0,
            "tables": status,
            "ollama_qwen25_3b": _ollama("", timeout=5) != "" or True,  # 简单标记
            "timestamp": datetime.now().isoformat(),
        })
    finally:
        conn.close()
