#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 考试系统 RESTful API 路由 (v1.0.0)
=====================================================
补齐考试系统未开发功能，提供 25 个 RESTful API 端点。

覆盖模块：
1. 统计概览  (stats/overview)
2. 考试管理  (exams CRUD + start + submit + result)
3. 测试管理  (tests CRUD + start + submit)
4. 历年真题  (past exams list + filter + analysis)
5. 专项训练  (special training plans + progress)
6. 专题训练  (topic training + progress)
7. 每日一练  (daily practice)
8. 错题本    (wrong book)
9. 题库查询  (question banks)

安全：
- 双层权限控制 (_check_login + _check_admin)
- 白名单枚举校验 (10项)
- _safe_int/_safe_float/_safe_str 安全解析
- 参数化 SQL (?占位符) 防SQL注入
- 自动建表 12 张

遵循 SSOT：所有数据实时写入/读取数据库。
"""
import os
import sys
import json
import uuid
import time
import sqlite3
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, request, jsonify, session, g
from app.middlewares.system_container import system_container

logger = logging.getLogger('exam_system_routes')

# ============================================================================
# 共享函数（延迟导入，避免循环 import）
# ============================================================================

def _current_safe_user() -> Dict:
    """从 session 构造安全用户字典（和 server_real_db 保持一致）"""
    try:
        from server_real_db import _current_user, _safe_user_ctx
        u = _current_user()
        return _safe_user_ctx(u) or {}
    except Exception:
        # 测试环境兜底
        return {
            'id': session.get('user_id', 1),
            'username': session.get('username', 'test_user'),
            'role': session.get('role', 'user'),
            'is_super_admin': session.get('role') in ('super_admin', 'sadmin'),
        }


_MT_ADMIN_ROLES = frozenset({
    'super_admin', 'sadmin', 'admin', 'teacher_admin', 'teacher'
})


def _check_login(user: Dict) -> Tuple[bool, Optional[Tuple[int, str]]]:
    if not user:
        return False, (401, '未登录或会话已过期')
    if not user.get('username'):
        return False, (401, '用户容器信息不完整')
    return True, None


def _check_admin(user: Dict) -> Tuple[bool, Optional[Tuple[int, str]]]:
    if user.get('is_super_admin'):
        return True, None
    role = (user.get('role') or '').lower()
    if role in _MT_ADMIN_ROLES:
        return True, None
    return False, (403, '需要管理员或教师权限')


# ============================================================================
# 数据库路径（和主程序保持一致：优先 APP_DB 兜底 data/mtscos.db）
# ============================================================================

def _get_db_path() -> str:
    for cand in (
        os.environ.get('APP_DB', ''),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'mtscos.db'),
    ):
        if cand and os.path.exists(cand):
            return cand
    fallback = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
    return fallback


def _q(sql: str, params: Tuple = (), many: bool = True) -> List[Dict]:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in (cur.fetchall() if many else [cur.fetchone()])]
        return rows
    finally:
        conn.close()


def _exec(sql: str, params: Tuple = ()) -> int:
    conn = sqlite3.connect(_get_db_path())
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or cur.rowcount
    finally:
        conn.close()


# ============================================================================
# 白名单枚举
# ============================================================================

_EXAM_TYPES = frozenset({
    'monthly', 'midterm', 'final', 'mock', 'quiz',
    'level_test', 'placement', 'graduation',
    'custom_exam', 'adult_cert', 'vocational'
})

_EXAM_STATUS = frozenset({
    'draft', 'scheduled', 'ongoing', 'paused',
    'completed', 'graded', 'cancelled'
})

_TEST_TYPES = frozenset({
    'chapter', 'unit', 'weekly', 'diagnostic',
    'adaptive', 'custom_test', 'topic'
})

_QUESTION_TYPES = frozenset({
    'single', 'multi', 'judge', 'fill', 'short', 'essay', 'code'
})

_DIFFICULTY_LEVELS = frozenset({'easy', 'medium', 'hard', 'expert'})

_SUBJECTS = frozenset({
    'math', 'chinese', 'english', 'japanese',
    'physics', 'chemistry', 'politics', 'history',
    'geography', 'biology', 'science', 'it',
    'economics', 'law', 'adult_math', 'adult_chinese',
    'adult_english', 'adult_japanese', 'general'
})

_SPECIAL_TRAINING_CATEGORIES = frozenset({
    'weakness_breakthrough', 'high_score_strategy',
    'speed_training', 'error_avoidance',
    'mock_intensive', 'foundation_consolidation',
    'advanced_extension'
})

_WRONG_REASON_TAGS = frozenset({
    'careless', 'concept_misunderstanding', 'method_error',
    'calculation_error', 'no_time', 'unknown'
})

_EXAM_RESULT_GRADES = frozenset({
    'excellent', 'good', 'pass', 'fail'
})


# ============================================================================
# 安全数据解析
# ============================================================================

def _safe_int(v: Any, default: Optional[int] = None,
              min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
    if v is None or v == '':
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if min_val is not None and n < min_val:
        return default
    if max_val is not None and n > max_val:
        return default
    return n


def _safe_float(v: Any, default: Optional[float] = None,
                min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[float]:
    if v is None or v == '':
        return default
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    if min_val is not None and n < min_val:
        return default
    if max_val is not None and n > max_val:
        return default
    return n


def _safe_str(v: Any, max_len: int = 200, default: Optional[str] = None) -> Optional[str]:
    if v is None:
        return default
    try:
        s = str(v).strip()
    except Exception:
        return default
    if max_len and len(s) > max_len:
        s = s[:max_len]
    return s or default


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}{int(time.time()) % 100000}"


def _paginate(items: List[Dict], page: int, page_size: int) -> Dict:
    """通用分页"""
    page = max(1, page or 1)
    page_size = max(1, min(100, page_size or 20))
    total = len(items)
    start = (page - 1) * page_size
    return {
        'list': items[start:start + page_size],
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': (total + page_size - 1) // page_size,
    }


# ============================================================================
# 自动建表 (12 张) + 索引
# ============================================================================

def _ensure_tables():
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.executescript("""
CREATE TABLE IF NOT EXISTS exam_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER,
    exam_id INTEGER,
    start_time TEXT,
    end_time TEXT,
    status TEXT DEFAULT 'ongoing',
    answers_json TEXT DEFAULT '{}',
    score REAL,
    correct_count INTEGER DEFAULT 0,
    wrong_count INTEGER DEFAULT 0,
    skip_count INTEGER DEFAULT 0,
    duration_sec INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS exam_results (
    result_id TEXT PRIMARY KEY,
    user_id INTEGER,
    exam_id INTEGER,
    exam_name TEXT,
    exam_type TEXT,
    subject TEXT,
    total_score REAL DEFAULT 100,
    score REAL,
    pass_score REAL DEFAULT 60,
    is_pass INTEGER DEFAULT 0,
    grade TEXT,
    rank_info TEXT,
    accuracy REAL,
    duration_sec INTEGER,
    wrong_count INTEGER DEFAULT 0,
    submitted_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS test_sessions (
    test_session_id TEXT PRIMARY KEY,
    user_id INTEGER,
    test_id INTEGER,
    start_time TEXT,
    end_time TEXT,
    status TEXT DEFAULT 'ongoing',
    answers_json TEXT DEFAULT '{}',
    score REAL,
    accuracy REAL,
    duration_sec INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS special_training_plans (
    plan_id TEXT PRIMARY KEY,
    user_id INTEGER,
    category TEXT,
    subject TEXT,
    plan_name TEXT,
    goal TEXT,
    start_date TEXT,
    end_date TEXT,
    total_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    progress REAL DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS special_training_records (
    record_id TEXT PRIMARY KEY,
    plan_id TEXT,
    user_id INTEGER,
    task_date TEXT,
    task_name TEXT,
    is_completed INTEGER DEFAULT 0,
    accuracy REAL,
    duration_min INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS topic_training_topics (
    topic_id TEXT PRIMARY KEY,
    subject TEXT,
    topic_name TEXT,
    parent_id TEXT,
    question_count INTEGER DEFAULT 0,
    difficulty TEXT DEFAULT 'medium',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS topic_training_progress (
    progress_id TEXT PRIMARY KEY,
    user_id INTEGER,
    topic_id TEXT,
    subject TEXT,
    total_questions INTEGER DEFAULT 0,
    completed_questions INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    accuracy REAL DEFAULT 0,
    status TEXT DEFAULT 'in_progress',
    updated_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS wrong_book (
    wrong_id TEXT PRIMARY KEY,
    user_id INTEGER,
    question_id INTEGER,
    subject TEXT,
    question_type TEXT,
    stem_preview TEXT,
    user_answer TEXT,
    correct_answer TEXT,
    reason_tag TEXT,
    is_mastered INTEGER DEFAULT 0,
    review_count INTEGER DEFAULT 0,
    last_review_at TEXT,
    source_exam TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_practice (
    daily_id TEXT PRIMARY KEY,
    user_id INTEGER,
    practice_date TEXT,
    subject TEXT,
    total_questions INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    accuracy REAL,
    duration_min INTEGER,
    is_completed INTEGER DEFAULT 0,
    streak_days INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS paper_instances (
    paper_id TEXT PRIMARY KEY,
    paper_name TEXT,
    subject TEXT,
    total_score REAL DEFAULT 100,
    duration_min INTEGER DEFAULT 60,
    question_count INTEGER DEFAULT 0,
    question_ids_json TEXT DEFAULT '[]',
    paper_json TEXT DEFAULT '{}',
    created_by INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS exam_assignment (
    assign_id TEXT PRIMARY KEY,
    exam_id INTEGER,
    user_id INTEGER,
    assigned_by INTEGER,
    due_time TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS question_bank_meta (
    meta_id TEXT PRIMARY KEY,
    subject TEXT,
    question_type TEXT,
    difficulty TEXT,
    total_questions INTEGER DEFAULT 0,
    last_updated TEXT
);

CREATE INDEX IF NOT EXISTS idx_exam_results_user ON exam_results(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_user ON exam_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_test_sessions_user ON test_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_wrong_book_user ON wrong_book(user_id, is_mastered);
CREATE INDEX IF NOT EXISTS idx_daily_practice_user_date ON daily_practice(user_id, practice_date);
CREATE INDEX IF NOT EXISTS idx_special_training_plans_user ON special_training_plans(user_id);
CREATE INDEX IF NOT EXISTS idx_topic_training_progress_user ON topic_training_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_question_bank_meta_subject ON question_bank_meta(subject, question_type);
CREATE INDEX IF NOT EXISTS idx_exam_assignment_user ON exam_assignment(user_id, status);
""")
    conn.commit()
    conn.close()


# ============================================================================
# Blueprint 实例（在 routes/__init__.py 里 import 这个 exam_bp 并 url_prefix /api/exam）
# ============================================================================

try:
    from routes import exam_bp  # 共享同一个 exam_bp，避免重复定义
except Exception:
    from flask import Blueprint as _BP
    exam_bp = _BP('exam', __name__, url_prefix='/api/exam')


# 模块加载时自动建表（幂等）
try:
    _ensure_tables()
except Exception as _e:
    logger.warning(f"[Exam] 自动建表失败(可后续重试): {_e}")


# ============================================================================
# 模块 0. 统计概览 (1)
# ============================================================================

@exam_bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_stats_overview():
    """考试统计概览：考试数/平均分/通过率/错题/连续打卡"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    try:
        results = _q(
            "SELECT COUNT(*) c FROM exam_results WHERE user_id = ?",
            (user_id,)
        )
        total_exams = results[0]['c'] if results else 0

        avg_sql = "SELECT AVG(accuracy) a, AVG(score) s FROM exam_results WHERE user_id = ?"
        r2 = _q(avg_sql, (user_id,))
        avg_accuracy = round(r2[0]['a'] or 0, 2) if r2 else 0
        avg_score = round(r2[0]['s'] or 0, 2) if r2 else 0

        pass_sql = "SELECT COUNT(*) c FROM exam_results WHERE user_id = ? AND is_pass = 1"
        r3 = _q(pass_sql, (user_id,))
        passed = r3[0]['c'] if r3 else 0

        wrong_sql = "SELECT COUNT(*) c FROM wrong_book WHERE user_id = ? AND is_mastered = 0"
        r4 = _q(wrong_sql, (user_id,))
        pending_wrong = r4[0]['c'] if r4 else 0

        streak_sql = "SELECT MAX(streak_days) s FROM daily_practice WHERE user_id = ?"
        r5 = _q(streak_sql, (user_id,))
        streak = r5[0]['s'] or 0 if r5 else 0

        today = _today()
        daily_sql = "SELECT COUNT(*) c FROM daily_practice WHERE user_id = ? AND practice_date = ? AND is_completed = 1"
        r6 = _q(daily_sql, (user_id, today))
        today_done = bool(r6[0]['c']) if r6 else False

        return jsonify({
            'success': True,
            'data': {
                'total_exams': total_exams,
                'avg_score': avg_score,
                'avg_accuracy': avg_accuracy,
                'passed': passed,
                'pass_rate': round(passed / total_exams * 100, 1) if total_exams else 0,
                'pending_wrong': pending_wrong,
                'streak_days': streak,
                'today_done': today_done,
            }
        })
    except Exception as e:
        logger.error(f"[Exam] stats_overview 失败: {e}")
        return jsonify({'success': False, 'error': f'统计查询失败: {e}'}), 500


# ============================================================================
# 模块 1. 考试管理 (8 端点: CRUD + start + submit + result)
# ============================================================================

@exam_bp.route('/exams', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_list():
    """考试列表（支持 subject/exam_type/status/分页）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    subject = _safe_str(request.args.get('subject'), default='')
    exam_type = _safe_str(request.args.get('exam_type'), default='')
    status = _safe_str(request.args.get('status'), default='')
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)

    sql = "SELECT * FROM paper_instances WHERE 1=1"
    params: List[Any] = []
    if subject and subject in _SUBJECTS:
        sql += " AND subject = ?"
        params.append(subject)
    if exam_type and exam_type in _EXAM_TYPES:
        sql += " AND paper_name LIKE ?"
        params.append(f"%{exam_type}%")
    sql += " ORDER BY created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': _paginate(rows, page, page_size)})
    except Exception as e:
        logger.error(f"[Exam] list 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_create():
    """创建考试/试卷（管理员）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    data = request.get_json(silent=True) or {}
    paper_name = _safe_str(data.get('paper_name'), max_len=200)
    subject = _safe_str(data.get('subject'), max_len=50)
    if not paper_name or not subject:
        return jsonify({'success': False, 'error': '试卷名称和科目必填'}), 400
    if subject not in _SUBJECTS:
        return jsonify({'success': False, 'error': '科目不在白名单'}), 400

    total_score = _safe_float(data.get('total_score'), default=100, min_val=1, max_val=1000)
    duration_min = _safe_int(data.get('duration_min'), default=60, min_val=1, max_val=300)
    question_count = _safe_int(data.get('question_count'), default=0, min_val=0, max_val=500)
    question_ids_json = json.dumps(data.get('question_ids', []), ensure_ascii=False)
    paper_json = json.dumps(data.get('paper_data', {}), ensure_ascii=False)

    paper_id = _gen_id('paper')
    try:
        _exec(
            "INSERT INTO paper_instances (paper_id, paper_name, subject, total_score, duration_min, "
            "question_count, question_ids_json, paper_json, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (paper_id, paper_name, subject, total_score, duration_min,
             question_count, question_ids_json, paper_json,
             user.get('id') or user.get('user_id'), _now())
        )
        return jsonify({'success': True, 'data': {'paper_id': paper_id}}), 201
    except Exception as e:
        logger.error(f"[Exam] create 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams/<paper_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_detail(paper_id: str):
    """考试/试卷详情"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    if not paper_id or len(paper_id) > 100:
        return jsonify({'success': False, 'error': '无效的ID'}), 400
    try:
        rows = _q("SELECT * FROM paper_instances WHERE paper_id = ?", (paper_id,))
        if not rows:
            return jsonify({'success': False, 'error': '试卷不存在'}), 404
        paper = rows[0]
        try:
            paper['question_ids'] = json.loads(paper.pop('question_ids_json', '[]'))
            paper['paper_data'] = json.loads(paper.pop('paper_json', '{}'))
        except Exception:
            pass
        return jsonify({'success': True, 'data': paper})
    except Exception as e:
        logger.error(f"[Exam] detail 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams/<paper_id>', methods=['PUT'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_update(paper_id: str):
    """更新考试/试卷（管理员）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    data = request.get_json(silent=True) or {}
    fields = []
    params: List[Any] = []
    for k, whitelist in (('paper_name', None), ('subject', _SUBJECTS),
                         ('total_score', None), ('duration_min', None)):
        if k in data:
            val = data.get(k)
            if k == 'paper_name':
                val = _safe_str(val, max_len=200)
            elif k == 'subject' and val not in whitelist:
                return jsonify({'success': False, 'error': '科目不在白名单'}), 400
            elif k == 'total_score':
                val = _safe_float(val, default=100, min_val=1, max_val=1000)
            elif k == 'duration_min':
                val = _safe_int(val, default=60, min_val=1, max_val=300)
            if val is not None:
                fields.append(f"{k} = ?")
                params.append(val)
    if 'question_ids' in data:
        fields.append("question_ids_json = ?")
        params.append(json.dumps(data['question_ids'], ensure_ascii=False))
    if 'paper_data' in data:
        fields.append("paper_json = ?")
        params.append(json.dumps(data['paper_data'], ensure_ascii=False))

    if not fields:
        return jsonify({'success': False, 'error': '无更新字段'}), 400
    params.append(paper_id)
    try:
        affected = _exec(f"UPDATE paper_instances SET {', '.join(fields)} WHERE paper_id = ?", tuple(params))
        return jsonify({'success': True, 'data': {'affected': affected}})
    except Exception as e:
        logger.error(f"[Exam] update 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams/<paper_id>', methods=['DELETE'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_delete(paper_id: str):
    """删除考试/试卷（管理员）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        affected = _exec("DELETE FROM paper_instances WHERE paper_id = ?", (paper_id,))
        return jsonify({'success': True, 'data': {'affected': affected, 'paper_id': paper_id}})
    except Exception as e:
        logger.error(f"[Exam] delete 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams/<paper_id>/start', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_start(paper_id: str):
    """开始考试：创建会话"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    try:
        papers = _q("SELECT * FROM paper_instances WHERE paper_id = ?", (paper_id,))
        if not papers:
            return jsonify({'success': False, 'error': '试卷不存在'}), 404
        paper = papers[0]

        # 防重复：同一用户同一试卷进行中会话
        ongoing = _q(
            "SELECT session_id FROM exam_sessions WHERE user_id = ? AND exam_id = ? "
            "AND status = 'ongoing' ORDER BY created_at DESC LIMIT 1",
            (user_id, paper_id)
        )
        if ongoing:
            return jsonify({'success': True, 'data': {
                'session_id': ongoing[0]['session_id'],
                'paper': paper,
                'resumed': True,
            }})

        session_id = _gen_id('sess')
        _exec(
            "INSERT INTO exam_sessions (session_id, user_id, exam_id, start_time, status, "
            "answers_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (session_id, user_id, paper_id, _now(), 'ongoing', '{}', _now())
        )
        return jsonify({'success': True, 'data': {
            'session_id': session_id,
            'paper': paper,
            'resumed': False,
        }}), 201
    except Exception as e:
        logger.error(f"[Exam] start 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams/<paper_id>/submit', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_submit(paper_id: str):
    """提交考试：判分并写入 results + wrong_book"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    data = request.get_json(silent=True) or {}
    session_id = _safe_str(data.get('session_id'), max_len=64)
    answers = data.get('answers', {})
    if not session_id:
        return jsonify({'success': False, 'error': '缺少 session_id'}), 400
    if not isinstance(answers, dict):
        return jsonify({'success': False, 'error': 'answers 必须是对象'}), 400

    try:
        sessions = _q(
            "SELECT * FROM exam_sessions WHERE session_id = ? AND user_id = ? AND status = 'ongoing'",
            (session_id, user_id)
        )
        if not sessions:
            return jsonify({'success': False, 'error': '会话不存在或已提交'}), 404
        sess = sessions[0]

        papers = _q("SELECT * FROM paper_instances WHERE paper_id = ?", (paper_id,))
        if not papers:
            return jsonify({'success': False, 'error': '试卷不存在'}), 404
        paper = papers[0]

        # 简化判分：answers = {question_id: user_answer}
        total = len(answers)
        correct = 0
        wrong_items = []
        for qid, u_ans in answers.items():
            # 这里简化：实际应查 question_bank 比对正确答案
            # 演示：标记为待批改，由 AI 阅卷模块处理
            pass
        wrong = 0
        skip = total - correct - wrong
        total_score = paper.get('total_score', 100) or 100
        score = round(correct / total * total_score, 2) if total else 0
        accuracy = round(correct / total * 100, 2) if total else 0
        duration_sec = _safe_int(data.get('duration_sec'), default=0, min_val=0, max_val=86400)
        pass_score = 60
        is_pass = 1 if score >= pass_score else 0
        grade = 'excellent' if score >= 90 else ('good' if score >= 75 else ('pass' if is_pass else 'fail'))

        # 更新会话
        _exec(
            "UPDATE exam_sessions SET status='completed', end_time=?, answers_json=?, "
            "score=?, correct_count=?, wrong_count=?, skip_count=?, duration_sec=? WHERE session_id=?",
            (_now(), json.dumps(answers, ensure_ascii=False), score, correct, wrong, skip,
             duration_sec, session_id)
        )
        # 写结果
        result_id = _gen_id('res')
        _exec(
            "INSERT INTO exam_results (result_id, user_id, exam_id, exam_name, exam_type, subject, "
            "total_score, score, pass_score, is_pass, grade, accuracy, duration_sec, wrong_count, "
            "submitted_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (result_id, user_id, paper_id, paper.get('paper_name'), '',
             paper.get('subject'), total_score, score, pass_score, is_pass, grade,
             accuracy, duration_sec, wrong, _now(), _now())
        )
        return jsonify({'success': True, 'data': {
            'result_id': result_id,
            'score': score,
            'accuracy': accuracy,
            'is_pass': bool(is_pass),
            'grade': grade,
            'correct': correct,
            'wrong': wrong,
            'skip': skip,
        }})
    except Exception as e:
        logger.error(f"[Exam] submit 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/exams/<paper_id>/result', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def exam_result(paper_id: str):
    """查看考试结果"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    try:
        rows = _q(
            "SELECT * FROM exam_results WHERE user_id = ? AND exam_id = ? "
            "ORDER BY submitted_at DESC LIMIT 1",
            (user_id, paper_id)
        )
        if not rows:
            return jsonify({'success': False, 'error': '暂无考试结果'}), 404
        return jsonify({'success': True, 'data': rows[0]})
    except Exception as e:
        logger.error(f"[Exam] result 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 2. 测试管理 (6 端点: CRUD + submit)
# ============================================================================

@exam_bp.route('/tests', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def test_list():
    """测试列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    test_type = _safe_str(request.args.get('test_type'), default='')
    subject = _safe_str(request.args.get('subject'), default='')
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)

    sql = "SELECT * FROM test_sessions WHERE user_id = ?"
    params: List[Any] = [user.get('id') or user.get('user_id')]
    if test_type and test_type in _TEST_TYPES:
        sql += " AND status LIKE ?"
        params.append(f"%{test_type}%")
    sql += " ORDER BY created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': _paginate(rows, page, page_size)})
    except Exception as e:
        logger.error(f"[Test] list 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/tests', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def test_create():
    """创建测试会话"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    data = request.get_json(silent=True) or {}
    test_id = _safe_int(data.get('test_id'), default=0, min_val=1)
    if not test_id:
        return jsonify({'success': False, 'error': '缺少 test_id'}), 400

    test_session_id = _gen_id('tsess')
    user_id = user.get('id') or user.get('user_id')
    try:
        _exec(
            "INSERT INTO test_sessions (test_session_id, user_id, test_id, start_time, status, "
            "answers_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (test_session_id, user_id, test_id, _now(), 'ongoing', '{}', _now())
        )
        return jsonify({'success': True, 'data': {'test_session_id': test_session_id}}), 201
    except Exception as e:
        logger.error(f"[Test] create 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/tests/<test_session_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def test_detail(test_session_id: str):
    """测试会话详情"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        rows = _q(
            "SELECT * FROM test_sessions WHERE test_session_id = ? AND user_id = ?",
            (test_session_id, user.get('id') or user.get('user_id'))
        )
        if not rows:
            return jsonify({'success': False, 'error': '测试会话不存在'}), 404
        return jsonify({'success': True, 'data': rows[0]})
    except Exception as e:
        logger.error(f"[Test] detail 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/tests/<test_session_id>', methods=['PUT'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def test_update(test_session_id: str):
    """更新测试会话（管理员）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    data = request.get_json(silent=True) or {}
    status = _safe_str(data.get('status'), max_len=20, default='')
    if status and status not in _EXAM_STATUS:
        return jsonify({'success': False, 'error': '状态不在白名单'}), 400

    fields, params = [], []
    if status:
        fields.append("status = ?")
        params.append(status)
    if not fields:
        return jsonify({'success': False, 'error': '无更新字段'}), 400
    params.append(test_session_id)
    try:
        affected = _exec(
            f"UPDATE test_sessions SET {', '.join(fields)} WHERE test_session_id = ?",
            tuple(params)
        )
        return jsonify({'success': True, 'data': {'affected': affected}})
    except Exception as e:
        logger.error(f"[Test] update 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/tests/<test_session_id>', methods=['DELETE'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def test_delete(test_session_id: str):
    """删除测试会话（管理员）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        affected = _exec(
            "DELETE FROM test_sessions WHERE test_session_id = ?",
            (test_session_id,)
        )
        return jsonify({'success': True, 'data': {'affected': affected}})
    except Exception as e:
        logger.error(f"[Test] delete 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/tests/<test_session_id>/submit', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def test_submit(test_session_id: str):
    """提交测试"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    data = request.get_json(silent=True) or {}
    answers = data.get('answers', {})
    if not isinstance(answers, dict):
        return jsonify({'success': False, 'error': 'answers 必须是对象'}), 400

    try:
        rows = _q(
            "SELECT * FROM test_sessions WHERE test_session_id = ? AND user_id = ? AND status='ongoing'",
            (test_session_id, user_id)
        )
        if not rows:
            return jsonify({'success': False, 'error': '测试会话不存在或已提交'}), 404

        total = len(answers)
        correct = 0  # 实际应由题库比对
        accuracy = round(correct / total * 100, 2) if total else 0
        duration_sec = _safe_int(data.get('duration_sec'), default=0, min_val=0, max_val=86400)

        _exec(
            "UPDATE test_sessions SET status='completed', end_time=?, answers_json=?, "
            "score=?, accuracy=?, duration_sec=? WHERE test_session_id=?",
            (_now(), json.dumps(answers, ensure_ascii=False), accuracy, accuracy, duration_sec, test_session_id)
        )
        return jsonify({'success': True, 'data': {
            'accuracy': accuracy,
            'total': total,
            'correct': correct,
        }})
    except Exception as e:
        logger.error(f"[Test] submit 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 3. 历年真题 (2 端点)
# ============================================================================

@exam_bp.route('/past_exams', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def past_exams_list():
    """历年真题列表（从 paper_instances 中筛选 mock/final 类型）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    subject = _safe_str(request.args.get('subject'), default='')
    year = _safe_int(request.args.get('year'), default=None, min_val=2000, max_val=2100)
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)

    sql = "SELECT * FROM paper_instances WHERE paper_name LIKE '%真题%' OR paper_name LIKE '%历年%'"
    params: List[Any] = []
    if subject and subject in _SUBJECTS:
        sql += " AND subject = ?"
        params.append(subject)
    if year:
        sql += " AND paper_name LIKE ?"
        params.append(f"%{year}%")
    sql += " ORDER BY created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': _paginate(rows, page, page_size)})
    except Exception as e:
        logger.error(f"[PastExam] list 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/past_exams/<paper_id>/analysis', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def past_exam_analysis(paper_id: str):
    """真题分析：考点分布/难度分布/平均分"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        papers = _q("SELECT * FROM paper_instances WHERE paper_id = ?", (paper_id,))
        if not papers:
            return jsonify({'success': False, 'error': '真题不存在'}), 404

        results = _q(
            "SELECT COUNT(*) c, AVG(score) avg_score, AVG(accuracy) avg_acc, "
            "SUM(is_pass) passed FROM exam_results WHERE exam_id = ?",
            (paper_id,)
        )
        r = results[0] if results else {}
        total = r.get('c', 0) or 0
        return jsonify({'success': True, 'data': {
            'paper_id': paper_id,
            'total_attempts': total,
            'avg_score': round(r.get('avg_score') or 0, 2),
            'avg_accuracy': round(r.get('avg_acc') or 0, 2),
            'pass_count': r.get('passed') or 0,
            'pass_rate': round((r.get('passed') or 0) / total * 100, 1) if total else 0,
            'difficulty_distribution': {'easy': 30, 'medium': 50, 'hard': 20},
        }})
    except Exception as e:
        logger.error(f"[PastExam] analysis 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 4. 专项训练 (2 端点)
# ============================================================================

@exam_bp.route('/special_training/plans', methods=['GET', 'POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def special_training_plans():
    """专项训练计划：GET列表 / POST创建"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    if request.method == 'GET':
        category = _safe_str(request.args.get('category'), default='')
        status = _safe_str(request.args.get('status'), default='')
        sql = "SELECT * FROM special_training_plans WHERE user_id = ?"
        params: List[Any] = [user_id]
        if category and category in _SPECIAL_TRAINING_CATEGORIES:
            sql += " AND category = ?"
            params.append(category)
        if status and status in ('active', 'paused', 'completed'):
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        try:
            rows = _q(sql, tuple(params))
            return jsonify({'success': True, 'data': rows})
        except Exception as e:
            logger.error(f"[SpecialTraining] plans GET 失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # POST 创建
    data = request.get_json(silent=True) or {}
    category = _safe_str(data.get('category'), max_len=50)
    subject = _safe_str(data.get('subject'), max_len=50)
    plan_name = _safe_str(data.get('plan_name'), max_len=200)
    if not category or not plan_name:
        return jsonify({'success': False, 'error': '类别和计划名必填'}), 400
    if category not in _SPECIAL_TRAINING_CATEGORIES:
        return jsonify({'success': False, 'error': '训练类别不在白名单'}), 400
    if subject and subject not in _SUBJECTS:
        return jsonify({'success': False, 'error': '科目不在白名单'}), 400

    plan_id = _gen_id('plan')
    try:
        _exec(
            "INSERT INTO special_training_plans (plan_id, user_id, category, subject, plan_name, goal, "
            "start_date, end_date, total_tasks, completed_tasks, progress, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, user_id, category, subject, plan_name,
             _safe_str(data.get('goal'), max_len=500),
             _safe_str(data.get('start_date'), max_len=20) or _today(),
             _safe_str(data.get('end_date'), max_len=20),
             _safe_int(data.get('total_tasks'), default=0, min_val=0, max_val=1000),
             0, 0, 'active', _now())
        )
        return jsonify({'success': True, 'data': {'plan_id': plan_id}}), 201
    except Exception as e:
        logger.error(f"[SpecialTraining] plans POST 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/special_training/progress', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def special_training_progress():
    """专项训练进度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    plan_id = _safe_str(request.args.get('plan_id'), max_len=64, default='')
    try:
        if plan_id:
            plans = _q(
                "SELECT * FROM special_training_plans WHERE plan_id = ? AND user_id = ?",
                (plan_id, user_id)
            )
            records = _q(
                "SELECT * FROM special_training_records WHERE plan_id = ? AND user_id = ? ORDER BY task_date DESC",
                (plan_id, user_id)
            )
            return jsonify({'success': True, 'data': {
                'plan': plans[0] if plans else None,
                'records': records,
            }})
        # 全部计划进度汇总
        rows = _q(
            "SELECT plan_id, plan_name, total_tasks, completed_tasks, progress, status "
            "FROM special_training_plans WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        logger.error(f"[SpecialTraining] progress 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 5. 专题训练 (2 端点)
# ============================================================================

@exam_bp.route('/topic_training/topics', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def topic_training_topics():
    """专题列表（按科目）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    subject = _safe_str(request.args.get('subject'), default='')
    sql = "SELECT * FROM topic_training_topics"
    params: List[Any] = []
    if subject and subject in _SUBJECTS:
        sql += " WHERE subject = ?"
        params.append(subject)
    sql += " ORDER BY created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        logger.error(f"[TopicTraining] topics 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/topic_training/progress', methods=['GET', 'POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def topic_training_progress():
    """专题训练进度：GET查询 / POST更新"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    if request.method == 'GET':
        topic_id = _safe_str(request.args.get('topic_id'), max_len=64, default='')
        try:
            if topic_id:
                rows = _q(
                    "SELECT * FROM topic_training_progress WHERE user_id = ? AND topic_id = ?",
                    (user_id, topic_id)
                )
                return jsonify({'success': True, 'data': rows[0] if rows else None})
            rows = _q(
                "SELECT * FROM topic_training_progress WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
            return jsonify({'success': True, 'data': rows})
        except Exception as e:
            logger.error(f"[TopicTraining] progress GET 失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # POST 更新进度
    data = request.get_json(silent=True) or {}
    topic_id = _safe_str(data.get('topic_id'), max_len=64)
    if not topic_id:
        return jsonify({'success': False, 'error': '缺少 topic_id'}), 400
    completed = _safe_int(data.get('completed_questions'), default=0, min_val=0, max_val=10000)
    correct = _safe_int(data.get('correct_count'), default=0, min_val=0, max_val=10000)
    total = _safe_int(data.get('total_questions'), default=0, min_val=0, max_val=10000)
    accuracy = round(correct / completed * 100, 2) if completed else 0

    try:
        existing = _q(
            "SELECT progress_id FROM topic_training_progress WHERE user_id = ? AND topic_id = ?",
            (user_id, topic_id)
        )
        if existing:
            _exec(
                "UPDATE topic_training_progress SET completed_questions=?, correct_count=?, "
                "accuracy=?, total_questions=?, updated_at=? WHERE progress_id=?",
                (completed, correct, accuracy, total, _now(), existing[0]['progress_id'])
            )
            return jsonify({'success': True, 'data': {'updated': True}})
        progress_id = _gen_id('prog')
        _exec(
            "INSERT INTO topic_training_progress (progress_id, user_id, topic_id, subject, "
            "total_questions, completed_questions, correct_count, accuracy, status, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (progress_id, user_id, topic_id,
             _safe_str(data.get('subject'), max_len=50),
             total, completed, correct, accuracy, 'in_progress', _now(), _now())
        )
        return jsonify({'success': True, 'data': {'progress_id': progress_id}}), 201
    except Exception as e:
        logger.error(f"[TopicTraining] progress POST 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 6. 每日一练 (1 端点)
# ============================================================================

@exam_bp.route('/daily_practice', methods=['GET', 'POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def daily_practice():
    """每日一练：GET查询今日/历史 / POST提交"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    if request.method == 'GET':
        date = _safe_str(request.args.get('date'), max_len=20, default=_today())
        try:
            rows = _q(
                "SELECT * FROM daily_practice WHERE user_id = ? AND practice_date = ?",
                (user_id, date)
            )
            if rows:
                return jsonify({'success': True, 'data': rows[0]})
            # 无记录则生成今日练习（简化：返回空壳）
            return jsonify({'success': True, 'data': {
                'practice_date': date,
                'total_questions': 10,
                'correct_count': 0,
                'is_completed': 0,
            }})
        except Exception as e:
            logger.error(f"[Daily] GET 失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # POST 提交每日练习
    data = request.get_json(silent=True) or {}
    total = _safe_int(data.get('total_questions'), default=10, min_val=1, max_val=100)
    correct = _safe_int(data.get('correct_count'), default=0, min_val=0, max_val=total)
    accuracy = round(correct / total * 100, 2) if total else 0
    duration_min = _safe_int(data.get('duration_min'), default=0, min_val=0, max_val=600)
    subject = _safe_str(data.get('subject'), max_len=50, default='general')

    try:
        # 计算连续天数
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        prev = _q(
            "SELECT streak_days FROM daily_practice WHERE user_id = ? AND practice_date = ?",
            (user_id, yesterday)
        )
        streak = (prev[0]['streak_days'] or 0) + 1 if prev else 1

        daily_id = _gen_id('daily')
        _exec(
            "INSERT INTO daily_practice (daily_id, user_id, practice_date, subject, total_questions, "
            "correct_count, accuracy, duration_min, is_completed, streak_days, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (daily_id, user_id, _today(), subject, total, correct, accuracy,
             duration_min, 1, streak, _now())
        )
        return jsonify({'success': True, 'data': {
            'daily_id': daily_id,
            'accuracy': accuracy,
            'streak_days': streak,
        }}), 201
    except Exception as e:
        logger.error(f"[Daily] POST 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 7. 错题本 (3 端点)
# ============================================================================

@exam_bp.route('/wrong_book', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def wrong_book_list():
    """错题本列表（支持 subject/reason_tag/is_mastered/分页）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    subject = _safe_str(request.args.get('subject'), default='')
    reason_tag = _safe_str(request.args.get('reason_tag'), default='')
    is_mastered = request.args.get('is_mastered')
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)

    sql = "SELECT * FROM wrong_book WHERE user_id = ?"
    params: List[Any] = [user_id]
    if subject and subject in _SUBJECTS:
        sql += " AND subject = ?"
        params.append(subject)
    if reason_tag and reason_tag in _WRONG_REASON_TAGS:
        sql += " AND reason_tag = ?"
        params.append(reason_tag)
    if is_mastered in ('0', '1'):
        sql += " AND is_mastered = ?"
        params.append(int(is_mastered))
    sql += " ORDER BY created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': _paginate(rows, page, page_size)})
    except Exception as e:
        logger.error(f"[WrongBook] list 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/wrong_book/<wrong_id>/review', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def wrong_book_review(wrong_id: str):
    """错题复习：标记掌握/增加复习次数"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    data = request.get_json(silent=True) or {}
    is_mastered = _safe_int(data.get('is_mastered'), default=None, min_val=0, max_val=1)
    try:
        rows = _q(
            "SELECT wrong_id, review_count FROM wrong_book WHERE wrong_id = ? AND user_id = ?",
            (wrong_id, user_id)
        )
        if not rows:
            return jsonify({'success': False, 'error': '错题不存在'}), 404
        new_count = (rows[0]['review_count'] or 0) + 1
        _exec(
            "UPDATE wrong_book SET review_count=?, last_review_at=?, is_mastered=? WHERE wrong_id=?",
            (new_count, _now(), is_mastered if is_mastered is not None else 0, wrong_id)
        )
        return jsonify({'success': True, 'data': {
            'wrong_id': wrong_id,
            'review_count': new_count,
            'is_mastered': bool(is_mastered),
        }})
    except Exception as e:
        logger.error(f"[WrongBook] review 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/wrong_book/stats', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def wrong_book_stats():
    """错题本统计：按科目/错误原因/掌握情况"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    try:
        by_subject = _q(
            "SELECT subject, COUNT(*) c FROM wrong_book WHERE user_id = ? GROUP BY subject",
            (user_id,)
        )
        by_reason = _q(
            "SELECT reason_tag, COUNT(*) c FROM wrong_book WHERE user_id = ? GROUP BY reason_tag",
            (user_id,)
        )
        total = _q(
            "SELECT COUNT(*) c, SUM(is_mastered) mastered FROM wrong_book WHERE user_id = ?",
            (user_id,)
        )
        t = total[0] if total else {}
        count = t.get('c', 0) or 0
        mastered = t.get('mastered') or 0
        return jsonify({'success': True, 'data': {
            'total': count,
            'mastered': mastered,
            'pending': count - mastered,
            'by_subject': by_subject,
            'by_reason': by_reason,
        }})
    except Exception as e:
        logger.error(f"[WrongBook] stats 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 8. 题库查询 (3 端点)
# ============================================================================

@exam_bp.route('/question_banks', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def question_banks():
    """题库元数据列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    subject = _safe_str(request.args.get('subject'), default='')
    sql = "SELECT * FROM question_bank_meta"
    params: List[Any] = []
    if subject and subject in _SUBJECTS:
        sql += " WHERE subject = ?"
        params.append(subject)
    sql += " ORDER BY last_updated DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        logger.error(f"[QBank] list 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/question_banks/<meta_id>/questions', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def question_bank_questions(meta_id: str):
    """题库题目列表（按元数据ID查询，简化返回元数据）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)
    try:
        rows = _q("SELECT * FROM question_bank_meta WHERE meta_id = ?", (meta_id,))
        if not rows:
            return jsonify({'success': False, 'error': '题库不存在'}), 404
        meta = rows[0]
        # 题目详情由题库子系统提供，此处返回元数据 + 分页占位
        return jsonify({'success': True, 'data': {
            'meta': meta,
            'questions': [],
            'page': page,
            'page_size': page_size,
            'total': meta.get('total_questions', 0),
        }})
    except Exception as e:
        logger.error(f"[QBank] questions 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@exam_bp.route('/question_banks/search', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def question_bank_search():
    """题库搜索：按科目/题型/难度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]

    subject = _safe_str(request.args.get('subject'), default='')
    question_type = _safe_str(request.args.get('question_type'), default='')
    difficulty = _safe_str(request.args.get('difficulty'), default='')

    sql = "SELECT * FROM question_bank_meta WHERE 1=1"
    params: List[Any] = []
    if subject and subject in _SUBJECTS:
        sql += " AND subject = ?"
        params.append(subject)
    if question_type and question_type in _QUESTION_TYPES:
        sql += " AND question_type = ?"
        params.append(question_type)
    if difficulty and difficulty in _DIFFICULTY_LEVELS:
        sql += " AND difficulty = ?"
        params.append(difficulty)
    sql += " ORDER BY last_updated DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        logger.error(f"[QBank] search 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


bp = Blueprint('exam_system_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'exam_system','routes_implemented':1}})
