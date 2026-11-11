#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🎓 TeacherSandboxEngine — 完全隔离的 AI 教师学习团队沙盘

设计原则 (同理 LabSandboxEngine):
  1. ISOLATION: 所有表前缀 mt_ts_*, 绝不读写真实教学表
  2. AI_MENTOR: Ollama qwen2.5 实时点评教案 + 模拟学生反应 + 教学反思
  3. TEAM_MODE: 多位 AI 教师集体备课 / 互相评课 / 模拟课堂
  4. COMPETENCY: 教师职业能力五维画像 (学科/设计/管理/心理/评价)
  5. BRAIN_FEED: 教训自动写入 mt_fm_brain_feed (category=TEACHER_LESSON)

核心场景:
  教案设计 → AI 导师点评 → AI 模拟学生反应 → 教学反思 → 能力蒸馏 → 脑库投喂

Usage:
  python3 teacher_sandbox_engine.py init                              # 建表
  python3 teacher_sandbox_engine.py create "高一函数单元备课" --subject math
  python3 teacher_sandbox_engine.py join-all <team_id>                # 所有 AI 教师加入
  python3 teacher_sandbox_engine.py lesson   <team_id> <teacher_id> \
      --title "函数的单调性" --grade 高一 --duration 45 \
      --plan "教案正文..."
  python3 teacher_sandbox_engine.py reflect  <team_id>                 # AI 教学反思 + 能力蒸馏
  python3 teacher_sandbox_engine.py status   <team_id>
"""
from __future__ import annotations
import os
import sys
import json
import uuid
import time
import sqlite3
import logging
import argparse
import urllib.request
from datetime import datetime
from typing import Optional

# ── 路径 ──
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(_BASE_DIR)
_DB_PATH_DEFAULT = os.path.join(_FLASK_APP, 'database', 'app.db')


def _get_db_path():
    env_p = os.environ.get('MTSCOS_DB_PATH', '')
    if env_p and os.path.exists(env_p):
        return env_p
    if os.path.exists(_DB_PATH_DEFAULT):
        return _DB_PATH_DEFAULT
    prod = os.path.expanduser('~/MTSCOS_PROD/flask-app/database/app.db')
    if os.path.exists(prod):
        return prod
    return _DB_PATH_DEFAULT


DB_PATH = _get_db_path()

logger = logging.getLogger('teacher_sandbox')
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('[TEACHER] %(message)s'))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


# =====================================================================
# ISOLATION SAFETY NET
# =====================================================================
_REAL_TEACHING_TABLES = {
    'mt_teacher_development', 'mt_teacher_records', 'mt_class_records',
    'mt_student_grades', 'mt_exam_papers', 'mt_lesson_plans',
}


def _isolation_check_sql(sql: str) -> None:
    import re as _re
    tokens = _re.findall(r'"?([a-zA-Z_][a-zA-Z0-9_]*)"?', sql)
    suspicious = [t for t in tokens if t in _REAL_TEACHING_TABLES]
    if suspicious:
        raise Exception(f"⛔ ISOLATION VIOLATION: {suspicious}")


def _open_conn(timeout: float = 30.0) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    conn.row_factory = sqlite3.Row
    return conn


def _make_id(prefix: str = 'TS') -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# =====================================================================
# TEACHER SCHEMAS — 完全隔离 mt_ts_* 前缀
# =====================================================================
TS_SCHEMAS: dict = {
    # 教师学习团队 (对应 lab 的 experiment)
    'mt_ts_team': """
        CREATE TABLE IF NOT EXISTS mt_ts_team (
            team_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            subject TEXT DEFAULT 'general',           -- math/chinese/english/physics/chemistry/biology/history/geography/general
            grade TEXT,                                -- 高一/高二/高三/初一...
            type TEXT DEFAULT 'lesson_review',        -- lesson_review/collective_prep/mock_class/competency
            status TEXT DEFAULT 'active',              -- active/paused/completed
            focus TEXT,                                -- 本次聚焦方向: 教学设计/课堂管理/差生辅导...
            created_by TEXT DEFAULT 'ollama',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT
        )""",

    # AI 教师成员 (对应 lab 的 participant)
    'mt_ts_teacher': """
        CREATE TABLE IF NOT EXISTS mt_ts_teacher (
            teacher_id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            name TEXT NOT NULL,
            subject TEXT DEFAULT 'general',
            role TEXT DEFAULT 'teacher',               -- teacher/mentor/observer/student_role
            is_ai INTEGER DEFAULT 1,
            ai_employee_id TEXT,
            level REAL DEFAULT 3.0,                    -- 教师能力等级 1-5
            total_score REAL DEFAULT 0,                -- 累计得分
            lessons_done INTEGER DEFAULT 0,             -- 完成教案数
            reflections_done INTEGER DEFAULT 0,        -- 完成反思数
            join_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(team_id, name)
        )""",

    # 教案提交 (对应 lab 的 trade)
    'mt_ts_lesson_plan': """
        CREATE TABLE IF NOT EXISTS mt_ts_lesson_plan (
            plan_id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            teacher_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            grade TEXT,
            duration_min INTEGER DEFAULT 45,
            objectives TEXT,                           -- 教学目标
            plan_content TEXT,                         -- 教案正文
            key_points TEXT,                           -- 重点
            difficult_points TEXT,                     -- 难点
            teaching_method TEXT,                      -- 教学方法
            ollama_feedback TEXT,                      -- AI 导师点评
            feedback_dimensions TEXT,                  -- JSON: {design:4.2, mgmt:3.5, psych:4.0, ...}
            overall_score REAL,                        -- 综合评分 1-5
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",

    # AI 模拟学生反应 (教师场景独有的 — AI 扮演真实课堂)
    'mt_ts_mock_class': """
        CREATE TABLE IF NOT EXISTS mt_ts_mock_class (
            mock_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            teacher_id TEXT NOT NULL,
            student_type TEXT,                         -- 优生/中等生/差生/活跃型/沉默型/偏科生
            student_persona TEXT,                      -- AI 生成的学生画像
            reaction TEXT,                             -- 学生在课堂中的真实反应
            question_raised TEXT,                      -- 学生提出的问题
            confusion_spot TEXT,                       -- 学生困惑点
            engagement_score REAL,                     -- 参与度 1-5
            understanding_score REAL,                  -- 理解度 1-5
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",

    # 教学反思 / 评课 (对应 lab 的 report)
    'mt_ts_reflection': """
        CREATE TABLE IF NOT EXISTS mt_ts_reflection (
            ref_id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            plan_id TEXT,
            teacher_id TEXT,
            reflection_type TEXT,                      -- self_reflection/peer_review/ai_summary/team_summary
            content TEXT,                              -- 反思正文
            strengths_json TEXT,                       -- JSON: 亮点/做得好的地方
            improvements_json TEXT,                    -- JSON: 待改进点/结构化建议
            competency_shift_json TEXT,               -- JSON: 五维能力变化 {design:+0.2, mgmt:-0.1, ...}
            brain_feed_ids TEXT,                      -- JSON array: 已投喂脑库的 ID
            created_by TEXT DEFAULT 'ollama',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",

    # 教师职业能力画像 (教师场景独有 — 长期成长追踪)
    'mt_ts_competency': """
        CREATE TABLE IF NOT EXISTS mt_ts_competency (
            comp_id TEXT PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            team_id TEXT,
            dimension TEXT NOT NULL,                   -- subject_knowledge/instructional_design/classroom_mgmt/student_psyche/assessment
            score REAL DEFAULT 3.0,                    -- 1-5
            delta REAL DEFAULT 0,                      -- 变化量
            evidence TEXT,                             -- 支撑证据
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(teacher_id, dimension)
        )""",

    # 团队聊天/讨论
    'mt_ts_chat': """
        CREATE TABLE IF NOT EXISTS mt_ts_chat (
            chat_id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            teacher_id TEXT,
            role TEXT,                                 -- user/assistant/mentor
            message TEXT NOT NULL,
            context_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
}


def ensure_ts_tables(conn: sqlite3.Connection) -> None:
    """幂等建表 + 索引"""
    for name, ddl in TS_SCHEMAS.items():
        conn.execute(ddl)
    _idx = [
        "CREATE INDEX IF NOT EXISTS idx_ts_plan_team ON mt_ts_lesson_plan(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_ts_plan_teacher ON mt_ts_lesson_plan(teacher_id)",
        "CREATE INDEX IF NOT EXISTS idx_ts_mock_plan ON mt_ts_mock_class(plan_id)",
        "CREATE INDEX IF NOT EXISTS idx_ts_ref_team ON mt_ts_reflection(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_ts_ref_plan ON mt_ts_reflection(plan_id)",
        "CREATE INDEX IF NOT EXISTS idx_ts_comp_teacher ON mt_ts_competency(teacher_id)",
        "CREATE INDEX IF NOT EXISTS idx_ts_teacher_team ON mt_ts_teacher(team_id)",
    ]
    for i in _idx:
        try:
            conn.execute(i)
        except Exception:
            pass
    conn.commit()


# =====================================================================
# Ollama 调用 (同理 lab)
# =====================================================================
def call_ollama(prompt: str, system: str = '你是专业的教师发展导师', timeout: float = 60) -> str:
    """调用 Ollama, 返回生成文本"""
    try:
        req_body = json.dumps({
            'model': 'qwen2.5:7b',
            'prompt': prompt,
            'system': system,
            'stream': False,
            'options': {'temperature': 0.7, 'num_predict': 512},
        }).encode('utf-8')
        req = urllib.request.Request(
            'http://localhost:11434/api/generate',
            data=req_body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data.get('response', '')
    except Exception as e:
        logger.warning(f"Ollama call failed: {e}")
        return f"[Ollama unavailable: {e}]"


# =====================================================================
# AI 导师: 教案五维点评
# =====================================================================
def ollama_feedback_plan(plan_title: str, grade: str, plan_content: str, subject: str = '') -> str:
    """AI 导师从五维能力点评教案"""
    prompt = f"""你是资深教研导师, 请对以下教案进行五维点评 (每维 1-5 星)。

【教案标题】{plan_title}
【学科】{subject}
【年级】{grade}
【教案正文】
{plan_content[:2000]}

请按以下五维给出评分 + 简短理由 + 1 句改进建议:
1. 学科知识 (subject_knowledge) — 知识点准确性、深度、前瞻性
2. 教学设计 (instructional_design) — 目标明确性、活动设计、学生参与
3. 课堂管理 (classroom_management) — 时间分配、节奏把控、预案设计
4. 学生心理 (student_psyche) — 认知负荷、动机激发、情感关怀
5. 评价反馈 (assessment) — 形成性评价、检测点、反馈策略

最后给出综合评分 (overall 1-5)。
输出 JSON: {{"design":{{"score":4,"reason":"...","suggestion":"..."}}, ..., "overall":4}}"""
    return call_ollama(prompt, system='资深教研导师, 输出纯 JSON', timeout=60)


# =====================================================================
# AI 模拟学生: 3 类典型学生反应
# =====================================================================
def ollama_mock_student(plan_title: str, grade: str, plan_content: str, student_type: str) -> dict:
    """AI 扮演某类学生, 输出课堂反应"""
    persona_map = {
        '优生': '学霸型学生, 思维活跃, 喜欢提问, 经常想超纲内容',
        '中等生': '基础扎实但不主动, 能跟上节奏, 很少主动提问',
        '差生': '基础薄弱, 容易走神, 需要反复解释, 经常似懂非懂',
        '活跃型': '外向好动, 爱插嘴, 课堂气氛调节剂, 但有时注意力分散',
        '沉默型': '内向害羞, 不主动发言, 可能听懂了也可能没懂',
        '偏科生': '某科特别好某科特别差, 对不擅长的科目有畏难情绪',
    }
    persona = persona_map.get(student_type, persona_map['中等生'])

    prompt = f"""你是【{student_type}】学生 (画像: {persona})。正在上一节课。

【课程】{plan_title} ({grade})
【教案摘要】{plan_content[:800]}

请用第一人称模拟你在这节课中的真实表现:
1. engagement (1-5): 你这节课的参与程度
2. understanding (1-5): 你对内容的理解程度
3. reaction: 你在课堂中的真实反应 (1-2 句)
4. question: 你可能提出的一个问题 (如果没有则写 "没有提问")
5. confusion: 你感到困惑的点 (如果没有则写 "没有困惑")

输出纯 JSON, 键名: engagement, understanding, reaction, question, confusion"""
    resp = call_ollama(prompt, system=f'{student_type}学生, 真实自然, 输出纯 JSON', timeout=45)

    # 解析 JSON
    parsed = {'engagement': 3, 'understanding': 3, 'reaction': '', 'question': '', 'confusion': ''}
    try:
        cleaned = resp
        if '```' in cleaned:
            cleaned = cleaned.split('```')[1]
            if cleaned.startswith('json'):
                cleaned = cleaned[4:]
        j = json.loads(cleaned.strip())
        for k in parsed:
            if k in j:
                parsed[k] = j[k]
    except Exception:
        pass
    parsed['student_type'] = student_type
    parsed['persona'] = persona
    return parsed


# =====================================================================
# AI 教学反思 + 能力蒸馏
# =====================================================================
def ollama_team_reflection(plans_summary: str, mock_summary: str) -> dict:
    """AI 对一组教案 + 模拟课堂结果做团队层面的教学反思"""
    prompt = f"""你是教学反思专家。根据以下一个备课团队的教案和模拟课堂表现, 输出:
1. 3-5 条团队亮点 (strengths)
2. 3-5 条待改进点 (improvements, 每条含 actionable 建议)
3. 五维能力变化建议 (competency_shift, 格式 {{"design":+0.2, "mgmt":-0.1, ...}})
4. 3-5 条可写入教师脑库的 TEACHER_LESSON (每条 lesson + actionable)

【教案摘要】
{plans_summary[:1500]}

【模拟课堂结果】
{mock_summary[:1500]}

输出纯 JSON array, 每项格式: {{"type":"strength|improvement|competency|lesson", "content":"...", "actionable":"..."}}"""
    resp = call_ollama(prompt, system='教学反思专家, 只输出 JSON', timeout=90)

    lessons = []
    try:
        cleaned = resp
        if '```' in cleaned:
            cleaned = cleaned.split('```')[1]
            if cleaned.startswith('json'):
                cleaned = cleaned[4:]
        arr = json.loads(cleaned.strip())
        if isinstance(arr, list):
            lessons = arr
    except Exception:
        # 降级: 用正则提取每个 JSON 对象 (Ollama 有时输出半截/malformed JSON)
        import re as _re
        for m in _re.finditer(r'\{[^{}]*"type"[^{}]*\}', resp):
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict) and obj.get('type'):
                    lessons.append(obj)
            except Exception:
                continue
    return {'raw': resp, 'lessons': lessons}


# =====================================================================
# ENGINE 类 (同理 LabSandboxEngine)
# =====================================================================
class TeacherSandboxEngine:
    """🎓 AI 教师学习团队沙盘引擎"""

    TEACHER_SUBJECTS = [
        ('数学教师', 'math', '理性严谨的数学思维培养者'),
        ('语文教师', 'chinese', '人文素养的传播者'),
        ('英语教师', 'english', '跨文化交流的桥梁'),
        ('物理教师', 'physics', '自然规律的探索者'),
        ('化学教师', 'chemistry', '物质变化的魔法师'),
        ('生物教师', 'biology', '生命科学的启蒙者'),
        ('历史教师', 'history', '以史为鉴的智者'),
        ('地理教师', 'geography', '地球家园的守望者'),
        ('班主任', 'class_teacher', '学生成长的引路人'),
        ('心理辅导师', 'psychology', '心灵健康的守护者'),
    ]

    STUDENT_TYPES = ['优生', '中等生', '差生', '活跃型', '沉默型', '偏科生']

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # 注意: 不在这里开连接 — Flask 多线程下 SQLite 连接不能跨线程共享
        # 每个方法内部自己 _open_conn() + close()
        logger.info(f"🎓 TeacherSandboxEngine init OK, db={db_path}")

    def _open(self) -> sqlite3.Connection:
        """每个方法内部调用, 线程安全"""
        conn = _open_conn()
        ensure_ts_tables(conn)
        conn.commit()
        return conn

    # ── 团队 CRUD ──
    def create_team(self, title: str, subject: str = 'general',
                    team_type: str = 'lesson_review', focus: str = '',
                    auto_join: bool = True) -> dict:
        conn = self._open()
        try:
            team_id = _make_id('TEAM')
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("""INSERT INTO mt_ts_team
                (team_id, title, subject, type, focus, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (team_id, title, subject, team_type, focus, now))

            if auto_join:
                self._auto_join_ai_teachers(conn, team_id, subject)

            conn.commit()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_ts_teacher WHERE team_id=?", (team_id,)).fetchone()[0]
            logger.info(f"🎓 团队已创建: {team_id} | {title} | {cnt} 教师")
            return {'success': True, 'team_id': team_id, 'title': title, 'teachers_count': cnt}
        finally:
            conn.close()

    def _auto_join_ai_teachers(self, conn, team_id: str, subject: str = 'general') -> int:
        """自动加入 AI 教师 — 从 mt_ai_employees 取 active 员工, 按 subject 匹配学科"""
        conn.execute("""INSERT OR IGNORE INTO mt_ts_teacher
            (teacher_id, team_id, name, subject, role, is_ai, ai_employee_id, level)
            VALUES (?, ?, ?, ?, ?, 1, ?, 3.0)""",
            (_make_id('TCH'), team_id, '教研导师', 'general', 'mentor', None))

        count = 0
        try:
            rows = conn.execute(
                "SELECT employee_id, name FROM mt_ai_employees WHERE status='active' LIMIT 36"
            ).fetchall()
            for emp_id, name in rows:
                conn.execute("""INSERT OR IGNORE INTO mt_ts_teacher
                    (teacher_id, team_id, name, subject, role, is_ai, ai_employee_id, level)
                    VALUES (?, ?, ?, ?, ?, 1, ?, 3.5)""",
                    (_make_id('TCH'), team_id, name, subject, 'teacher', emp_id))
                count += 1
        except Exception as e:
            logger.warning(f"auto_join from mt_ai_employees: {e}")

        # 额外加 5 个典型学科教师 (保证学科覆盖)
        for tname, tsubj, tdesc in self.TEACHER_SUBJECTS[:5]:
            try:
                conn.execute("""INSERT OR IGNORE INTO mt_ts_teacher
                    (teacher_id, team_id, name, subject, role, is_ai, level)
                    VALUES (?, ?, ?, ?, 'teacher', 1, 3.5)""",
                    (_make_id('TCH'), team_id, tname, tsubj))
                count += 1
            except Exception:
                pass
        return count + 1  # +1 for mentor

    # ── 教案提交 + AI 五维点评 ──
    def submit_lesson_plan(self, team_id: str, teacher_id: str,
                           title: str, plan_content: str,
                           subject: str = '', grade: str = '',
                           duration_min: int = 45, objectives: str = '',
                           key_points: str = '', difficult_points: str = '',
                           teaching_method: str = '讲授法+讨论法') -> dict:
        conn = self._open()
        try:
            # 写入教案
            plan_id = _make_id('PLAN')
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("""INSERT INTO mt_ts_lesson_plan
                (plan_id, team_id, teacher_id, title, subject, grade, duration_min,
                 objectives, plan_content, key_points, difficult_points, teaching_method, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_id, team_id, teacher_id, title, subject, grade, duration_min,
                 objectives, plan_content, key_points, difficult_points, teaching_method, now))
            conn.commit()

            # AI 五维点评
            logger.info(f"🤖 AI 五维点评 {title}...")
            raw = ollama_feedback_plan(title, grade, plan_content, subject)

            # 解析 JSON 或降级
            dims = {}
            overall = 3.0
            try:
                cleaned = raw
                if '```' in cleaned:
                    cleaned = cleaned.split('```')[1]
                    if cleaned.startswith('json'):
                        cleaned = cleaned[4:]
                j = json.loads(cleaned.strip())
                for key in ['design', 'knowledge', 'mgmt', 'psych', 'assessment',
                            'instructional_design', 'subject_knowledge',
                            'classroom_management', 'student_psyche', 'overall']:
                    if key in j:
                        dims[key] = j[key]
                overall_val = j.get('overall')
                if isinstance(overall_val, (int, float)):
                    overall = float(overall_val)
                elif isinstance(overall_val, dict):
                    s = overall_val.get('score', 3)
                    overall = float(s) if isinstance(s, (int, float)) else 3.0
            except Exception:
                # 降级: 按文字长度粗略评分
                overall = min(max(len(raw) / 300, 2), 5)

            # 写回教案
            conn.execute("""UPDATE mt_ts_lesson_plan SET
                ollama_feedback=?, feedback_dimensions=?, overall_score=?
                WHERE plan_id=?""", (raw, json.dumps(dims, ensure_ascii=False)[:500], overall, plan_id))
            conn.execute("""UPDATE mt_ts_teacher SET lessons_done = lessons_done + 1,
                total_score = total_score + ? WHERE teacher_id=?""", (overall, teacher_id))
            conn.commit()

            logger.info(f"  ✅ {title} AI 综合评分: {overall:.1f}/5")
            return {
                'success': True, 'plan_id': plan_id, 'overall_score': overall,
                'dimensions': dims, 'feedback_length': len(raw),
            }
        finally:
            conn.close()

    # ── AI 模拟课堂 (3 类学生) ──
    def run_mock_class(self, plan_id: str, team_id: str, teacher_id: str,
                       student_types: list = None) -> dict:
        conn = self._open()
        try:
            if student_types is None:
                student_types = ['优生', '中等生', '差生']

            # 拿教案
            row = conn.execute(
                "SELECT title, grade, plan_content FROM mt_ts_lesson_plan WHERE plan_id=?",
                (plan_id,)).fetchone()
            if not row:
                return {'success': False, 'error': 'plan not found'}
            title, grade, content = row['title'], row['grade'], row['plan_content']

            results = []
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for stype in student_types:
                logger.info(f"🎭 AI 模拟【{stype}】学生...")
                r = ollama_mock_student(title, grade or '', content or '', stype)
                mock_id = _make_id('MOCK')
                conn.execute("""INSERT INTO mt_ts_mock_class
                    (mock_id, plan_id, team_id, teacher_id, student_type, student_persona,
                     reaction, question_raised, confusion_spot, engagement_score,
                     understanding_score, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (mock_id, plan_id, team_id, teacher_id, r['student_type'], r['persona'],
                     r.get('reaction', ''), r.get('question', ''), r.get('confusion', ''),
                     float(r.get('engagement', 3)), float(r.get('understanding', 3)), now))
                results.append(r)
            conn.commit()

            # 平均分
            avg_eng = sum(r['engagement'] for r in results) / len(results) if results else 0
            avg_und = sum(r['understanding'] for r in results) / len(results) if results else 0
            logger.info(f"  📊 模拟课堂 avg engagement={avg_eng:.1f}, understanding={avg_und:.1f}")

            return {
                'success': True, 'plan_id': plan_id,
                'mock_count': len(results), 'mocks': results,
                'avg_engagement': avg_eng, 'avg_understanding': avg_und,
            }
        finally:
            conn.close()

    # ── AI 团队教学反思 + 能力蒸馏 + 脑库投喂 ──
    def team_reflection(self, team_id: str) -> dict:
        conn = self._open()
        try:
            # 拿本团队所有教案
            plans = conn.execute("""SELECT title, subject, grade, overall_score,
                substr(plan_content,1,300) FROM mt_ts_lesson_plan
                WHERE team_id=? ORDER BY created_at DESC LIMIT 10""", (team_id,)).fetchall()
            if not plans:
                return {'success': False, 'error': 'no plans in team'}

            plans_summary = '\n'.join(
                f"  [{p['overall_score']:.1f}/5] {p['title']} ({p['subject']}/{p['grade']})"
                for p in plans)

            # 拿所有模拟课堂
            mocks = conn.execute("""SELECT student_type, engagement_score, understanding_score,
                reaction, confusion_spot FROM mt_ts_mock_class
                WHERE team_id=? ORDER BY created_at DESC LIMIT 20""", (team_id,)).fetchall()
            mock_summary = '\n'.join(
                f"  [{m['student_type']}] eng={m['engagement_score']} und={m['understanding_score']} "
                f"reaction={m['reaction'][:40]} confusion={m['confusion_spot'][:40]}"
                for m in mocks)

            # AI 反思
            logger.info(f"📋 AI 教学反思 team={team_id}...")
            result = ollama_team_reflection(plans_summary, mock_summary)
            lessons = result['lessons']
            logger.info(f"  🎯 提取 {len(lessons)} 条教学教训")

            # 写 reflection
            ref_id = _make_id('REF')
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            strengths = [l for l in lessons if l.get('type') == 'strength']
            improvements = [l for l in lessons if l.get('type') == 'improvement']

            brain_feed_ids = []
            # 投喂脑库
            for l in lessons[:5]:
                try:
                    ct = l.get('content', str(l)[:100])
                    act = l.get('actionable', '')
                    full = f"{ct} → {act}" if act else ct
                    conn.execute("""INSERT INTO mt_fm_brain_feed
                        (stream_name, category, asr_text, trigger_keywords, emotion,
                         emotion_score, has_price_info, has_policy, created_at)
                        VALUES ('teacher_sandbox', 'TEACHER_LESSON', ?, ?, 'neutral', 0.5, 0, 0, ?)""",
                        (full[:500], team_id, now))
                    brain_feed_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                except Exception as e:
                    logger.warning(f"brain_feed write: {e}")

            # 更新团队教师反思数
            conn.execute("""UPDATE mt_ts_teacher SET reflections_done = reflections_done + 1
                WHERE team_id=?""", (team_id,))

            # 写反思表
            conn.execute("""INSERT INTO mt_ts_reflection
                (ref_id, team_id, reflection_type, content, strengths_json, improvements_json,
                 brain_feed_ids, created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (ref_id, team_id, 'team_summary', result['raw'],
                 json.dumps(strengths, ensure_ascii=False)[:1000],
                 json.dumps(improvements, ensure_ascii=False)[:1000],
                 json.dumps(brain_feed_ids), now))
            conn.commit()

            logger.info(f"  🧠 {len(brain_feed_ids)} 条 TEACHER_LESSON 已投喂脑库")
            return {
                'success': True, 'ref_id': ref_id, 'team_id': team_id,
                'lessons_count': len(lessons), 'brain_feed_count': len(brain_feed_ids),
                'lessons': lessons,
            }
        finally:
            conn.close()

    # ── 团队排名 ──
    def get_team_status(self, team_id: str) -> dict:
        conn = self._open()
        try:
            team = conn.execute("SELECT * FROM mt_ts_team WHERE team_id=?", (team_id,)).fetchone()
            if not team:
                return {'success': False, 'error': 'team not found'}

            teachers = conn.execute("""SELECT teacher_id, name, subject, role, level,
                lessons_done, reflections_done, total_score
                FROM mt_ts_teacher WHERE team_id=? ORDER BY total_score DESC""", (team_id,)).fetchall()

            plans = conn.execute("""SELECT plan_id, title, subject, grade, overall_score
                FROM mt_ts_lesson_plan WHERE team_id=? ORDER BY created_at DESC""", (team_id,)).fetchall()

            reflections = conn.execute(
                "SELECT ref_id, reflection_type, substr(content,1,60), created_at "
                "FROM mt_ts_reflection WHERE team_id=? ORDER BY created_at DESC LIMIT 5",
                (team_id,)).fetchall()

            return {
                'success': True,
                'team': dict(team),
                'teachers': [dict(t) for t in teachers],
                'plans': [dict(p) for p in plans],
                'reflections': [dict(r) for r in reflections],
            }
        finally:
            conn.close()

    def list_teams(self, status: str = '', limit: int = 20) -> list:
        conn = self._open()
        try:
            sql = "SELECT * FROM mt_ts_team"
            params = []
            if status:
                sql += " WHERE status=?"
                params.append(status)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def close(self):
        pass  # 每个方法内部自己关连接, 这里不需要


# =====================================================================
# CLI
# =====================================================================
def _cli():
    ap = argparse.ArgumentParser(description='🎓 TeacherSandboxEngine CLI')
    sub = ap.add_subparsers(dest='cmd')

    p_init = sub.add_parser('init')
    p_create = sub.add_parser('create')
    p_create.add_argument('title')
    p_create.add_argument('--subject', default='general')
    p_create.add_argument('--type', default='lesson_review')
    p_create.add_argument('--focus', default='')

    p_join = sub.add_parser('join-all')
    p_join.add_argument('team_id')

    p_lesson = sub.add_parser('lesson')
    p_lesson.add_argument('team_id')
    p_lesson.add_argument('teacher_id')
    p_lesson.add_argument('--title', required=True)
    p_lesson.add_argument('--plan', required=True)
    p_lesson.add_argument('--subject', default='')
    p_lesson.add_argument('--grade', default='')

    p_mock = sub.add_parser('mock')
    p_mock.add_argument('plan_id')
    p_mock.add_argument('team_id')
    p_mock.add_argument('teacher_id')

    p_reflect = sub.add_parser('reflect')
    p_reflect.add_argument('team_id')

    p_status = sub.add_parser('status')
    p_status.add_argument('team_id')

    args = ap.parse_args()
    eng = TeacherSandboxEngine()

    if args.cmd == 'init':
        print("✅ 教师沙盒表已就绪")
    elif args.cmd == 'create':
        r = eng.create_team(args.title, subject=args.subject, team_type=args.type, focus=args.focus)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'join-all':
        eng._auto_join_ai_teachers(eng._conn, args.team_id)
        eng._conn.commit()
        print(f"✅ AI 教师已加入 {args.team_id}")
    elif args.cmd == 'lesson':
        r = eng.submit_lesson_plan(args.team_id, args.teacher_id, args.title, args.plan,
                                   subject=args.subject, grade=args.grade)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'mock':
        r = eng.run_mock_class(args.plan_id, args.team_id, args.teacher_id)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'reflect':
        r = eng.team_reflection(args.team_id)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == 'status':
        r = eng.get_team_status(args.team_id)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        ap.print_help()
    eng.close()


if __name__ == '__main__':
    _cli()
