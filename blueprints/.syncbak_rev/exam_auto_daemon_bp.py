#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
考试院自动化 daemon (flow_exam_auto_20261023)
================================================
研究方向: 命题/审题/难度校准/学情诊断/备考方案
落实方向: 让考试引擎跑起来 → 虚拟考生 → 自动模考 → 数据闭环

页面:  GET /exam-auto                 — 考试院主页
API:   GET /api/exam-auto/overview    — 考试院总览 (题库+考试+学情)
API:   POST /api/exam-auto/run-cycle  — 手动触发一轮完整考试周期

Daemon 子任务 (30min 频率, 本地零 token):
  T1  难度校准 — 从 question_bank 抽 200 题, 用 IRT 简化模型重算 difficulty
  T2  虚拟模考 — 按 grade 从教育组抽 50 名 AI 员工做考生, 答 20 题
                → INSERT exam_sessions / exam_attempts / exam_results
  T3  学情诊断 — 聚合 exam_results → user_knowledge_mastery + learning_recommendations

落地表 (已有 + 补齐):
  已有: question_bank(23K) / k12_knowledge_points(300) / knowledge_graph(6K+9K)
  补齐: exam_sessions / exam_attempts / exam_results (从各 1-6 行 → 万级)
  新增: question_difficulty_calibration (IRT 输出)
  新增: user_knowledge_mastery (学情画像)
  新增: learning_recommendations (备考方案)
  新增: mt_exam_daemon_log (考试引擎日志)
"""
import hashlib
import json
import os
import random
import sqlite3
import time
from datetime import datetime
from flask import Blueprint, jsonify, request

exam_auto_bp = Blueprint("exam_auto_bp", __name__, template_folder=None)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")


# ══ 数据库连接 (WAL + busy_timeout) ══
def _db():
    conn = sqlite3.connect(MAIN_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


# ══ 表初始化 ══
_INIT_SQL = [
    """CREATE TABLE IF NOT EXISTS exam_sessions (
        session_id TEXT PRIMARY KEY,
        grade TEXT,                    -- 年级 (如 七年级/大学)
        subject TEXT,                  -- 学科
        question_count INTEGER DEFAULT 20,
        candidate_count INTEGER DEFAULT 0,
        avg_score REAL DEFAULT 0,
        duration_seconds INTEGER DEFAULT 0,
        status TEXT DEFAULT 'COMPLETED',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS exam_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        employee_name TEXT,            -- 虚拟考生 (from ai_employees)
        employee_code TEXT,
        track TEXT,                    -- 赛道
        score REAL DEFAULT 0,
        correct_count INTEGER DEFAULT 0,
        total_questions INTEGER DEFAULT 0,
        duration_seconds INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS exam_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        attempt_id INTEGER NOT NULL,
        question_id TEXT NOT NULL,
        selected_answer TEXT,
        correct_answer TEXT,
        is_correct INTEGER DEFAULT 0,
        reaction_time REAL DEFAULT 0,  -- 秒
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS question_difficulty_calibration (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id TEXT UNIQUE NOT NULL,
        p_value REAL DEFAULT 0.5,      -- 答对率
        item_total REAL DEFAULT 1.0,   -- 区分度
        difficulty_irt REAL DEFAULT 0,  -- IRT b 参数 (-3 ~ 3)
        calibrated_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS user_knowledge_mastery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_code TEXT NOT NULL,
        employee_name TEXT,
        knowledge_point TEXT NOT NULL,
        subject TEXT,
        grade TEXT,
        mastery REAL DEFAULT 0,        -- 0~1 掌握度
        attempt_count INTEGER DEFAULT 0,
        last_correct INTEGER DEFAULT 0,
        last_attempt_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(employee_code, knowledge_point)
    )""",
    """CREATE TABLE IF NOT EXISTS learning_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_code TEXT NOT NULL,
        employee_name TEXT,
        track TEXT,
        recommendation_type TEXT,      -- question / knowledge_point / study_plan / 方向
        content TEXT,
        priority INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_exam_daemon_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sub_task TEXT NOT NULL,
        cycle_no INTEGER DEFAULT 1,
        input_count INTEGER DEFAULT 0,
        output_count INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
]


# ══ T1: IRT 简化难度校准 ══
# 简化 IRT: 用 p_value(答对率) → 难度 (-3~3)
def _irt_calibrate(cursor, limit=200):
    """从 exam_results 聚合作答数据, 重算 question_difficulty_calibration"""
    # 1. 统计每题答对率
    cursor.execute(f"""
        SELECT question_id,
               COUNT(*) as total,
               SUM(is_correct) as correct
        FROM exam_results
        GROUP BY question_id
        HAVING total >= 3
        LIMIT {limit}
    """)
    rows = cursor.fetchall()
    calibrated = 0
    for r in rows:
        total = r["total"]
        correct = r["correct"] or 0
        p = correct / total if total > 0 else 0.5
        # p → IRT b 参数: 容易 p=0.9 → b=-1.5, 困难 p=0.1 → b=1.5
        difficulty_irt = -3.0 + 6.0 * (1.0 - p)  # 映射到 -3 ~ +3
        item_total = min(1.0, 0.3 + 0.7 * (1.0 - abs(p - 0.5) * 2))  # 区分度 0.3~1.0
        cursor.execute("""
            INSERT OR REPLACE INTO question_difficulty_calibration
            (question_id, p_value, item_total, difficulty_irt, calibrated_at)
            VALUES (?,?,?,?,datetime('now','localtime'))
        """, (r["question_id"], p, item_total, round(difficulty_irt, 3)))
        calibrated += 1
    return calibrated


# ══ T2: 虚拟模考 — 教育组 AI 员工当考生 ══
_GRADE_SUBJECT = [
    ("小学1年级", "数学"), ("小学2年级", "语文"), ("小学3年级", "英语"),
    ("小学4年级", "数学"), ("小学5年级", "语文"), ("小学6年级", "数学"),
    ("初中7年级", "数学"), ("初中8年级", "物理"), ("初中9年级", "化学"),
    ("高中10年级", "数学"), ("高中11年级", "物理"), ("高中12年级", "化学"),
    ("大学", "高等数学"), ("研究生", "科研方法"),
    # ── JLPT 日语 ──
    ("JLPT N5", "日语"), ("JLPT N4", "日语"), ("JLPT N3", "日语"),
    ("JLPT N2", "日语"), ("JLPT N1", "日语"),
    # ── 新概念英语 ──
    ("新概念第一册", "英语"), ("新概念第二册", "英语"),
    ("新概念第三册", "英语"), ("新概念第四册", "英语"),
    # ── 雅思 ──
    ("雅思听力", "英语"), ("雅思阅读", "英语"),
    ("雅思写作", "英语"), ("雅思口语", "英语"),
    # ── 托福 ──
    ("托福阅读", "英语"), ("托福听力", "英语"),
    ("托福口语", "英语"), ("托福写作", "英语"),
    # ── 标准普通话 ──
    ("普通话一级乙等", "普通话"), ("普通话二级甲等", "普通话"),
    ("普通话二级乙等", "普通话"), ("普通话三级甲等", "普通话"),
    # ── 中学语文 (汉语赛道引擎 flow_cnkr_track_20261031) ──
    ("中考语文", "语文"), ("高考语文", "语文"),
    # ── HSK 汉语水平考试 ──
    ("HSK四级", "汉语"), ("HSK五级", "汉语"), ("HSK六级", "汉语"),
    # ── TOPIK 韩国语能力考试 ──
    ("TOPIK 1级", "韩语"), ("TOPIK 2级", "韩语"), ("TOPIK 3级", "韩语"),
    ("TOPIK 4级", "韩语"), ("TOPIK 5级", "韩语"), ("TOPIK 6级", "韩语"),
]


def _run_virtual_exam(cursor, cycles=3):
    """每 cycle: 选 grade+subject → 抽 20 题 → 抽 50 名考生 → 模拟答题"""
    sessions = 0
    attempts = 0
    results = 0

    for _ in range(cycles):
        grade, subject = random.choice(_GRADE_SUBJECT)

        # 抽题 三级优先: ① grade=赛道精确匹配 (英语赛道引擎已按 grade=track 落库)
        #               ② subject 模糊匹配
        #               ③ 随机回退
        cursor.execute("""
            SELECT question_id, answer, content, difficulty
            FROM question_bank
            WHERE status='published' AND grade = ?
            ORDER BY RANDOM() LIMIT 20
        """, (grade,))
        questions = cursor.fetchall()
        if len(questions) < 5:
            cursor.execute("""
                SELECT question_id, answer, content, difficulty
                FROM question_bank
                WHERE status='published' AND subject LIKE ?
                ORDER BY RANDOM() LIMIT 20
            """, (f"%{subject[:2]}%",))
            questions = cursor.fetchall()
        if len(questions) < 5:
            # 回退: 随机抽
            cursor.execute("""
                SELECT question_id, answer, content, difficulty
                FROM question_bank WHERE status='published'
                ORDER BY RANDOM() LIMIT 20
            """)
            questions = cursor.fetchall()
        if not questions:
            continue

        # 抽考生 (教育组 + 对应 grade 或 hash 匹配)
        cursor.execute("""
            SELECT name, employee_code, track, skill_level
            FROM ai_employees
            WHERE group_tag='教育' AND status='active'
            ORDER BY RANDOM() LIMIT 50
        """)
        candidates = cursor.fetchall()
        if not candidates:
            continue

        # 创建 session
        session_id = f"exam_{grade}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(100,999)}"
        cursor.execute("""
            INSERT INTO exam_sessions (session_id, grade, subject, question_count, candidate_count, status)
            VALUES (?,?,?,?,?,?)
        """, (session_id, grade, subject, len(questions), len(candidates), 'COMPLETED'))

        session_score = 0
        session_attempts = 0

        for cand in candidates:
            emp_code = cand["employee_code"] or f"virtual_{cand['name']}"
            skill_lvl = cand["skill_level"] or 2
            # 答对概率由 skill_level 决定: L1=40%, L2=55%, L3=70%, L4=85%
            base_p = {1: 0.40, 2: 0.55, 3: 0.70, 4: 0.85}.get(skill_lvl, 0.55)

            total_q = len(questions)
            correct = 0
            cand_results = []
            for q in questions:
                # 随机决定对错 (按 base_p)
                is_correct = 1 if random.random() < base_p else 0
                if is_correct:
                    correct += 1
                    selected = q["answer"] or "A"
                else:
                    # 错误答案: 选非正确选项的随机字母
                    wrong_opts = [c for c in "ABCD" if c != (q["answer"] or "A")]
                    selected = random.choice(wrong_opts) if wrong_opts else "A"

                # 反应时间: 正确 ~30s, 错误 ~60s
                reaction = random.uniform(10, 50) if is_correct else random.uniform(40, 90)
                cand_results.append((session_id, None, q["question_id"], selected,
                                    q["answer"] or "", is_correct, reaction))

            score = round(correct / total_q * 100, 1) if total_q > 0 else 0
            session_score += score
            session_attempts += 1

            # INSERT attempt + results
            cursor.execute("""
                INSERT INTO exam_attempts
                (session_id, employee_name, employee_code, track, score, correct_count, total_questions, duration_seconds)
                VALUES (?,?,?,?,?,?,?,?)
            """, (session_id, cand["name"], emp_code, cand["track"], score, correct, total_q,
                  int(reaction * total_q)))
            attempt_id = cursor.lastrowid
            results += len(cand_results)
            for r in cand_results:
                cursor.execute("""
                    INSERT INTO exam_results
                    (session_id, attempt_id, question_id, selected_answer, correct_answer, is_correct, reaction_time)
                    VALUES (?,?,?,?,?,?,?)
                """, (r[0], attempt_id, r[2], r[3], r[4], r[5], r[6]))

            # 更新 user_knowledge_mastery
            for q in questions:
                kp = q["content"][:20] if q["content"] else ""
                cursor.execute("""
                    INSERT INTO user_knowledge_mastery
                    (employee_code, employee_name, knowledge_point, subject, grade, mastery, attempt_count, last_correct)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(employee_code, knowledge_point) DO UPDATE SET
                        mastery=(mastery*attempt_count+?)/(attempt_count+1),
                        attempt_count=attempt_count+1,
                        last_correct=?
                """, (emp_code, cand["name"], kp, subject, grade, 0, 0, 0,
                      0.8 if any(r[5] for r in cand_results if r[2] == q["question_id"]) else 0.4,
                      1 if any(r[5] for r in cand_results if r[2] == q["question_id"]) else 0))

        # 更新 session 平均分
        avg_score = round(session_score / max(session_attempts, 1), 1)
        cursor.execute("UPDATE exam_sessions SET avg_score=? WHERE session_id=?", (avg_score, session_id))
        sessions += 1
        attempts += session_attempts

    return sessions, attempts, results


# ══ T3: 学情诊断 + 备考方案 ══
def _generate_learning_recommendations(cursor, limit=50):
    """从 exam_results 聚合 → 生成 learning_recommendations"""
    # 找正确率低的知识点
    cursor.execute("""
        SELECT employee_code, employee_name, knowledge_point,
               mastery, attempt_count, last_correct
        FROM user_knowledge_mastery
        WHERE mastery < 0.6 AND attempt_count >= 2
        ORDER BY mastery ASC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    recs = 0
    for r in rows:
        rec_types = ["question", "knowledge_point", "study_plan", "方向"]
        rtype = rec_types[int(hashlib.md5(r["employee_code"].encode()).hexdigest()[0], 16) % 4]
        if rtype == "question":
            content = f"针对 '{r['knowledge_point']}' 刷 10 道练习题"
        elif rtype == "knowledge_point":
            content = f"重读知识点: {r['knowledge_point']} (当前掌握度 {round(r['mastery']*100,1)}%)"
        elif rtype == "study_plan":
            content = f"每周 3 次复习 '{r['knowledge_point']}'，每次 30 分钟"
        else:
            content = f"综合方向需加强基础，建议先补 '{r['knowledge_point']}'"

        cursor.execute("""
            INSERT INTO learning_recommendations
            (employee_code, employee_name, track, recommendation_type, content, priority)
            VALUES (?,?,?,?,?,?)
        """, (r["employee_code"], r["employee_name"], "", rtype, content, 1 if r["mastery"] < 0.3 else 2))
        recs += 1
    return recs


# ══ 核心守护循环 (30min 频率) ══
def run_exam_cycle():
    """一轮完整考试周期: 初始化 → T2 模考 → T1 校准 → T3 诊断"""
    conn = _db()
    cursor = conn.cursor()

    # 确保表存在
    for sql in _INIT_SQL:
        cursor.execute(sql)
    conn.commit()

    log = {"T1_IRT": 0, "T2_sessions": 0, "T2_attempts": 0, "T2_results": 0, "T3_recs": 0}

    # T2 先跑 (需要 results 数据才能校准)
    t2_sessions, t2_attempts, t2_results = _run_virtual_exam(cursor, cycles=3)
    conn.commit()
    log["T2_sessions"] = t2_sessions
    log["T2_attempts"] = t2_attempts
    log["T2_results"] = t2_results

    # T1 IRT 校准
    t1 = _irt_calibrate(cursor, limit=200)
    conn.commit()
    log["T1_IRT"] = t1

    # T3 学情诊断
    t3 = _generate_learning_recommendations(cursor, limit=50)
    conn.commit()
    log["T3_recs"] = t3

    # 写日志
    cursor.execute("""
        INSERT INTO mt_exam_daemon_log (sub_task, cycle_no, input_count, output_count, detail)
        VALUES ('FULL_CYCLE', 1, ?, ?, ?)
    """, (t2_results, t1 + t3, json.dumps(log, ensure_ascii=False)))
    conn.commit()

    conn.close()
    return log


# ══ Flask 路由 ══
@exam_auto_bp.route("/api/exam-auto/overview")
def api_overview():
    try:
        conn = _db()
        c = conn.cursor()

        # 确保表存在
        for sql in _INIT_SQL:
            c.execute(sql)
        conn.commit()

        qb = c.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
        sessions = c.execute("SELECT COUNT(*) FROM exam_sessions").fetchone()[0]
        attempts = c.execute("SELECT COUNT(*) FROM exam_attempts").fetchone()[0]
        results = c.execute("SELECT COUNT(*) FROM exam_results").fetchone()[0]
        calib = c.execute("SELECT COUNT(*) FROM question_difficulty_calibration").fetchone()[0]
        mastery = c.execute("SELECT COUNT(*) FROM user_knowledge_mastery").fetchone()[0]
        recs = c.execute("SELECT COUNT(*) FROM learning_recommendations").fetchone()[0]
        edu_staff = c.execute("SELECT COUNT(*) FROM ai_employees WHERE group_tag='教育'").fetchone()[0]

        # 考试最近日志
        logs = c.execute("""
            SELECT sub_task, output_count, detail, created_at
            FROM mt_exam_daemon_log ORDER BY id DESC LIMIT 5
        """).fetchall()
        log_list = [dict(l) for l in logs]

        conn.close()
        return jsonify({
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "question_bank": qb,
            "exam_sessions": sessions,
            "exam_attempts": attempts,
            "exam_results": results,
            "irt_calibrated": calib,
            "mastery_records": mastery,
            "recommendations": recs,
            "edu_staff_available": edu_staff,
            "daemon_log": log_list,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@exam_auto_bp.route("/api/exam-auto/run-cycle", methods=["POST"])
def api_run_cycle():
    try:
        log = run_exam_cycle()
        return jsonify({"ok": True, "log": log})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@exam_auto_bp.route("/exam-auto")
def page_exam_auto():
    """考试院主页 — 直接返回 JSON (无模板)"""
    return api_overview()
