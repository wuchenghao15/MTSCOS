#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 日语学习系统 RESTful API 路由 (v1.0.0)
=====================================================
补齐日语学习未开发功能，提供 25 个 RESTful API 端点。

覆盖模块：
1. 统计概览  (stats/overview)
2. 五十音图  (kana list/quiz/progress)
3. 词汇学习  (vocabulary list/detail/study/review/search)
4. 语法学习  (grammar list/detail/study)
5. 听力练习  (listening list/detail/submit)
6. 阅读理解  (reading list/detail/submit)
7. JLPT模拟  (jlpt/mock list/start/submit)
8. 单词本    (wordbook list/add)
9. 进度推荐  (progress/recommend)

日语学习特色：
- 五十音图（平假名/片假名）学习与测试
- JLPT N5-N1 级别词汇/语法/听力/阅读
- 间隔重复算法(SRS)词汇复习
- 单词本管理

安全：
- 双层权限控制 + 白名单枚举 + 参数化SQL + 自动建表10张
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
from flask import Blueprint, request, jsonify, session
from app.middlewares.system_container import system_container

logger = logging.getLogger('japanese_learning_routes')


# ============================================================================
# 共享函数
# ============================================================================

def _current_safe_user() -> Dict:
    try:
        from server_real_db import _current_user, _safe_user_ctx
        u = _current_user()
        return _safe_user_ctx(u) or {}
    except Exception:
        return {
            'id': session.get('user_id', 1),
            'username': session.get('username', 'test_user'),
            'role': session.get('role', 'user'),
            'is_super_admin': session.get('role') in ('super_admin', 'sadmin'),
        }


_MT_ADMIN_ROLES = frozenset({'super_admin', 'sadmin', 'admin', 'teacher_admin', 'teacher'})


def _check_login(user):
    if not user:
        return False, (401, '未登录或会话已过期')
    if not user.get('username'):
        return False, (401, '用户容器信息不完整')
    return True, None


def _check_admin(user):
    if user.get('is_super_admin'):
        return True, None
    role = (user.get('role') or '').lower()
    if role in _MT_ADMIN_ROLES:
        return True, None
    return False, (403, '需要管理员或教师权限')


def _get_db_path() -> str:
    """返回正确的主库路径 (mtscos.db 明文表)
    优先 server_real_db.DATA_MTSCOS_DB, 回退 candidates 列表"""
    # 0. 优先复用 server_real_db 的 DB 常量 (注意真实属性名是 DATA_MTSCOS_DB)
    try:
        import server_real_db as _srd
        for attr in ('DATA_MTSCOS_DB', 'MTSCOS_DB', 'APP_DB', 'DB_PATH'):
            _v = getattr(_srd, attr, None)
            if _v and os.path.exists(_v) and os.path.getsize(_v) > 10000:
                # 确保不是空壳小 DB
                return _v
    except Exception:
        pass
    # 1. 环境变量
    cand = os.environ.get('APP_DB', '')
    if cand and os.path.exists(cand):
        return cand
    # 2. mtscos 明文主库 (最常用)
    for _cand in (
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     '_runtime', 'databases', 'Database', 'mtscos.db'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'mtscos.db'),
    ):
        if os.path.exists(_cand):
            return _cand
    # 3. 最后兜底: 写到 app.db
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')


def _q(sql, params=(), many=True):
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in (cur.fetchall() if many else [cur.fetchone()])]
    finally:
        conn.close()


def _exec(sql, params=()):
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

_JLPT_LEVELS = frozenset({'N5', 'N4', 'N3', 'N2', 'N1'})
_JLPT_LEVEL_ORDER = ['N5', 'N4', 'N3', 'N2', 'N1']

# --- 特殊用户的 JLPT 目标级别映射 (未登录/无法从 progress 推断时兜底) ---
# key = (username, 或 user_id), value = {'target': 'N2', 'allow': ['N2','N1'], 'weights': {'N2':0.75,'N1':0.25}}
_USER_LEVEL_OVERRIDES = {
    'caopw':  {'target': 'N2', 'allow': ['N2', 'N1'], 'weights': {'N2': 0.75, 'N1': 0.25}},
}


def _infer_user_jlpt_level(user) -> str:
    """
    推断用户当前 JLPT 级别 (5 步降级):
    1. 显式请求参数 level → 返回它 (调用方已处理)
    2. 特殊用户 override 表
    3. jp_*_progress 表的学习记录 level 众数
    4. knowledge_user_paths 的目标节点
    5. 兜底 'N5'
    """
    if not user:
        return 'N5'
    # Step 2: override
    uname = user.get('username', '') or ''
    uid = user.get('id') or user.get('user_id')
    if uname in _USER_LEVEL_OVERRIDES:
        return _USER_LEVEL_OVERRIDES[uname]['target']

    # Step 3: progress 众数
    try:
        conn = _get_conn()
        cur = conn.cursor()
        counts = {}
        for tbl in ('jp_vocabulary_progress', 'jp_grammar_progress',
                    'jp_kana_progress', 'jp_listening_records', 'jp_reading_records'):
            try:
                rows = cur.execute(
                    f"SELECT level, COUNT(*) FROM {tbl} WHERE user_id=? AND level IN ('N5','N4','N3','N2','N1') "
                    f"GROUP BY level ORDER BY COUNT(*) DESC LIMIT 5",
                    (uid,)).fetchall()
                for r in rows:
                    counts[r[0]] = counts.get(r[0], 0) + r[1]
            except Exception:
                pass
        conn.close()
        if counts:
            mode = max(counts, key=counts.get)
            return mode
    except Exception:
        pass
    return 'N5'


def _pick_adaptive_levels(user, explicit_level=None, allow_below=False):
    """
    根据用户级别推断合适的内容级别列表。

    规则:
    - caopw (N2): levels=['N2','N1'], weights 75/25  → 过滤 N3/N4/N5
    - 显式 level='N2': 返回 ['N2'] (精确匹配)
    - 显式 level 为空: 按推断级别向上一级 + 本级
    - 兜底: ['N5']

    Args:
        user:        user dict
        explicit_level: 前端传的 level 参数 (None = 自适应)
        allow_below: 是否允许包含下级内容 (默认 False, caopw 这种 N2 用户不需要 N3 及以下)

    Returns:
        (levels_list, primary_level)
        levels_list 用于 SQL WHERE level IN (?,?,...)
        primary_level 用于前端显示 / 统计
    """
    # 1) 显式指定
    if explicit_level and explicit_level in _JLPT_LEVELS:
        return [explicit_level], explicit_level

    # 2) 特殊 override (含权重混合)
    uname = (user or {}).get('username', '') or ''
    if uname in _USER_LEVEL_OVERRIDES:
        ov = _USER_LEVEL_OVERRIDES[uname]
        return ov['allow'], ov['target']

    # 3) 推断级别
    inferred = _infer_user_jlpt_level(user)
    idx = _JLPT_LEVEL_ORDER.index(inferred) if inferred in _JLPT_LEVEL_ORDER else 0

    if allow_below:
        # 宽松模式: 本级 + 上下各 1 (兜底场景)
        lo = max(0, idx - 1)
        hi = min(len(_JLPT_LEVEL_ORDER), idx + 2)
        levels = _JLPT_LEVEL_ORDER[lo:hi]
    else:
        # 严格模式: 本级 + 向上 1 (不给下级)
        levels = _JLPT_LEVEL_ORDER[idx: idx + 2]

    return levels, inferred
_KANA_TYPES = frozenset({'hiragana', 'katakana'})
_KANA_ROWS = frozenset({
    'a', 'ka', 'sa', 'ta', 'na', 'ha', 'ma', 'ya', 'ra', 'wa',
    'gyo_a', 'gyo_ka', 'gyo_sa', 'gyo_ta', 'gyo_na', 'gyo_ha', 'gyo_ma',
    'gyo_ya', 'gyo_ra', 'gyo_wa', 'yoon'
})
_WORD_POS = frozenset({
    'noun', 'verb', 'adjective', 'adverb', 'particle',
    'conjunction', 'interjection', 'counter', 'pronoun',
    'auxiliary_verb', 'adjective_noun', 'prefix', 'suffix'
})
_GRAMMAR_TYPES = frozenset({
    'particle', 'verb_conjugation', 'sentence_pattern',
    'honorific', 'conditional', 'passive', 'causative', 'tense'
})
_LISTENING_TYPES = frozenset({'conversation', 'news', 'lecture', 'story', 'daily'})
_READING_TYPES = frozenset({'essay', 'news', 'story', 'letter', 'advertisement'})
_SRS_GRADES = frozenset({0, 1, 2, 3, 4, 5})
_QUIZ_TYPES = frozenset({'kana_to_romanji', 'romanji_to_kana', 'kana_pair', 'meaning'})


# ============================================================================
# 安全数据解析
# ============================================================================

def _safe_int(v, default=None, min_val=None, max_val=None):
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


def _safe_str(v, max_len=200, default=None):
    if v is None:
        return default
    try:
        s = str(v).strip()
    except Exception:
        return default
    if max_len and len(s) > max_len:
        s = s[:max_len]
    return s or default


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _gen_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}{int(time.time()) % 100000}"


def _paginate(items, page, page_size):
    page = max(1, page or 1)
    page_size = max(1, min(100, page_size or 20))
    total = len(items)
    start = (page - 1) * page_size
    return {
        'list': items[start:start + page_size],
        'page': page, 'page_size': page_size,
        'total': total, 'total_pages': (total + page_size - 1) // page_size,
    }


def _srs_next_interval(grade):
    """间隔重复算法：根据当前等级返回下次复习间隔（天）"""
    intervals = {0: 1, 1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
    return intervals.get(grade, 1)


# ============================================================================
# 自动建表 (10 张) + 索引
# ============================================================================

def _ensure_tables():
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.executescript("""
CREATE TABLE IF NOT EXISTS jp_kana_progress (
    kprogress_id TEXT PRIMARY KEY,
    user_id INTEGER,
    kana_char TEXT,
    kana_type TEXT DEFAULT 'hiragana',
    kana_row TEXT,
    romanji TEXT,
    is_mastered INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    wrong_count INTEGER DEFAULT 0,
    last_review_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_vocabulary (
    word_id TEXT PRIMARY KEY,
    word TEXT,
    kana TEXT,
    kanji TEXT,
    romanji TEXT,
    meaning_cn TEXT,
    meaning_jp TEXT,
    pos TEXT DEFAULT 'noun',
    level TEXT DEFAULT 'N5',
    example_jp TEXT,
    example_cn TEXT,
    tags_json TEXT DEFAULT '[]',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_vocabulary_progress (
    vprogress_id TEXT PRIMARY KEY,
    user_id INTEGER,
    word_id TEXT,
    level TEXT DEFAULT 'N5',
    srs_grade INTEGER DEFAULT 0,
    is_mastered INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    wrong_count INTEGER DEFAULT 0,
    next_review_at TEXT,
    last_review_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_grammar (
    grammar_id TEXT PRIMARY KEY,
    title TEXT,
    pattern TEXT,
    meaning_cn TEXT,
    grammar_type TEXT DEFAULT 'sentence_pattern',
    level TEXT DEFAULT 'N5',
    explanation TEXT,
    example_jp TEXT,
    example_cn TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_grammar_progress (
    gprogress_id TEXT PRIMARY KEY,
    user_id INTEGER,
    grammar_id TEXT,
    level TEXT DEFAULT 'N5',
    is_mastered INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    wrong_count INTEGER DEFAULT 0,
    last_review_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_listening (
    listening_id TEXT PRIMARY KEY,
    title TEXT,
    level TEXT DEFAULT 'N5',
    listening_type TEXT DEFAULT 'conversation',
    audio_url TEXT,
    transcript_jp TEXT,
    transcript_cn TEXT,
    duration_sec INTEGER DEFAULT 0,
    questions_json TEXT DEFAULT '[]',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_listening_records (
    lrecord_id TEXT PRIMARY KEY,
    user_id INTEGER,
    listening_id TEXT,
    level TEXT,
    score REAL,
    accuracy REAL,
    correct_count INTEGER DEFAULT 0,
    total_count INTEGER DEFAULT 0,
    duration_sec INTEGER DEFAULT 0,
    submitted_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_reading (
    reading_id TEXT PRIMARY KEY,
    title TEXT,
    level TEXT DEFAULT 'N5',
    reading_type TEXT DEFAULT 'essay',
    content_jp TEXT,
    content_cn TEXT,
    word_count INTEGER DEFAULT 0,
    questions_json TEXT DEFAULT '[]',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_reading_records (
    rrecord_id TEXT PRIMARY KEY,
    user_id INTEGER,
    reading_id TEXT,
    level TEXT,
    score REAL,
    accuracy REAL,
    correct_count INTEGER DEFAULT 0,
    total_count INTEGER DEFAULT 0,
    duration_sec INTEGER DEFAULT 0,
    submitted_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS jp_wordbook (
    wb_id TEXT PRIMARY KEY,
    user_id INTEGER,
    word_id TEXT,
    word TEXT,
    kana TEXT,
    meaning_cn TEXT,
    level TEXT DEFAULT 'N5',
    note TEXT,
    is_favorite INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jp_kana_progress_user ON jp_kana_progress(user_id, kana_char);
CREATE INDEX IF NOT EXISTS idx_jp_vocab_level ON jp_vocabulary(level, word);
CREATE INDEX IF NOT EXISTS idx_jp_vocab_progress_user_review ON jp_vocabulary_progress(user_id, next_review_at);
CREATE INDEX IF NOT EXISTS idx_jp_grammar_level ON jp_grammar(level);
CREATE INDEX IF NOT EXISTS idx_jp_grammar_progress_user ON jp_grammar_progress(user_id, grammar_id);
CREATE INDEX IF NOT EXISTS idx_jp_listening_level ON jp_listening(level);
CREATE INDEX IF NOT EXISTS idx_jp_listening_records_user ON jp_listening_records(user_id, listening_id);
CREATE INDEX IF NOT EXISTS idx_jp_reading_level ON jp_reading(level);
CREATE INDEX IF NOT EXISTS idx_jp_reading_records_user ON jp_reading_records(user_id, reading_id);
CREATE INDEX IF NOT EXISTS idx_jp_wordbook_user ON jp_wordbook(user_id, is_favorite);
""")
    conn.commit()
    conn.close()


# ============================================================================
# Blueprint 实例
# ============================================================================

try:
    from routes import japanese_bp
except Exception:
    from flask import Blueprint as _BP
    japanese_bp = _BP('japanese', __name__, url_prefix='/api/japanese')

try:
    _ensure_tables()
except Exception as _e:
    logger.warning(f"[Japanese] 自动建表失败(可后续重试): {_e}")


# ============================================================================
# 模块 0. 统计概览 (1)
# ============================================================================

@japanese_bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def jp_stats_overview():
    """日语学习统计概览"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    try:
        kana_mastered = _q(
            "SELECT COUNT(*) c FROM jp_kana_progress WHERE user_id = ? AND is_mastered = 1", (user_id,))
        kana_total = _q("SELECT COUNT(*) c FROM jp_kana_progress WHERE user_id = ?", (user_id,))

        vocab_mastered = _q(
            "SELECT COUNT(*) c FROM jp_vocabulary_progress WHERE user_id = ? AND is_mastered = 1", (user_id,))
        vocab_total = _q("SELECT COUNT(*) c FROM jp_vocabulary_progress WHERE user_id = ?", (user_id,))

        grammar_mastered = _q(
            "SELECT COUNT(*) c FROM jp_grammar_progress WHERE user_id = ? AND is_mastered = 1", (user_id,))

        listening_count = _q(
            "SELECT COUNT(*) c FROM jp_listening_records WHERE user_id = ?", (user_id,))
        reading_count = _q(
            "SELECT COUNT(*) c FROM jp_reading_records WHERE user_id = ?", (user_id,))

        # 待复习词汇
        today = _now()
        due_review = _q(
            "SELECT COUNT(*) c FROM jp_vocabulary_progress WHERE user_id = ? AND next_review_at <= ? AND is_mastered = 0",
            (user_id, today))

        # 各级别进度
        level_progress = {}
        for level in ['N5', 'N4', 'N3', 'N2', 'N1']:
            lvl_vocab = _q(
                "SELECT COUNT(*) c FROM jp_vocabulary_progress WHERE user_id = ? AND level = ? AND is_mastered = 1",
                (user_id, level))
            level_progress[level] = lvl_vocab[0]['c'] if lvl_vocab else 0

        return jsonify({'success': True, 'data': {
            'kana_mastered': kana_mastered[0]['c'] if kana_mastered else 0,
            'kana_total': kana_total[0]['c'] if kana_total else 0,
            'vocab_mastered': vocab_mastered[0]['c'] if vocab_mastered else 0,
            'vocab_total': vocab_total[0]['c'] if vocab_total else 0,
            'grammar_mastered': grammar_mastered[0]['c'] if grammar_mastered else 0,
            'listening_count': listening_count[0]['c'] if listening_count else 0,
            'reading_count': reading_count[0]['c'] if reading_count else 0,
            'due_review': due_review[0]['c'] if due_review else 0,
            'level_progress': level_progress,
        }})
    except Exception as e:
        logger.error(f"[JP] stats_overview 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 1. 五十音图 (3: list/quiz/progress)
# ============================================================================

@japanese_bp.route('/kana/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def kana_list():
    """五十音图列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    kana_type = _safe_str(request.args.get('kana_type'), default='')
    # 返回标准五十音图（基础部分）
    basic_kana = [
        {'char': 'あ', 'type': 'hiragana', 'row': 'a', 'romanji': 'a'},
        {'char': 'い', 'type': 'hiragana', 'row': 'a', 'romanji': 'i'},
        {'char': 'う', 'type': 'hiragana', 'row': 'a', 'romanji': 'u'},
        {'char': 'え', 'type': 'hiragana', 'row': 'a', 'romanji': 'e'},
        {'char': 'お', 'type': 'hiragana', 'row': 'a', 'romanji': 'o'},
        {'char': 'か', 'type': 'hiragana', 'row': 'ka', 'romanji': 'ka'},
        {'char': 'き', 'type': 'hiragana', 'row': 'ka', 'romanji': 'ki'},
        {'char': 'く', 'type': 'hiragana', 'row': 'ka', 'romanji': 'ku'},
        {'char': 'け', 'type': 'hiragana', 'row': 'ka', 'romanji': 'ke'},
        {'char': 'こ', 'type': 'hiragana', 'row': 'ka', 'romanji': 'ko'},
        {'char': 'さ', 'type': 'hiragana', 'row': 'sa', 'romanji': 'sa'},
        {'char': 'し', 'type': 'hiragana', 'row': 'sa', 'romanji': 'shi'},
        {'char': 'す', 'type': 'hiragana', 'row': 'sa', 'romanji': 'su'},
        {'char': 'せ', 'type': 'hiragana', 'row': 'sa', 'romanji': 'se'},
        {'char': 'そ', 'type': 'hiragana', 'row': 'sa', 'romanji': 'so'},
        {'char': 'ア', 'type': 'katakana', 'row': 'a', 'romanji': 'a'},
        {'char': 'イ', 'type': 'katakana', 'row': 'a', 'romanji': 'i'},
        {'char': 'ウ', 'type': 'katakana', 'row': 'a', 'romanji': 'u'},
        {'char': 'エ', 'type': 'katakana', 'row': 'a', 'romanji': 'e'},
        {'char': 'オ', 'type': 'katakana', 'row': 'a', 'romanji': 'o'},
    ]
    if kana_type and kana_type in _KANA_TYPES:
        basic_kana = [k for k in basic_kana if k['type'] == kana_type]
    return jsonify({'success': True, 'data': basic_kana})


@japanese_bp.route('/kana/quiz', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def kana_quiz():
    """假名测试：提交答案，更新进度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')

    data = request.get_json(silent=True) or {}
    quiz_type = _safe_str(data.get('quiz_type'), max_len=30, default='kana_to_romanji')
    if quiz_type not in _QUIZ_TYPES:
        return jsonify({'success': False, 'error': '测试类型不在白名单'}), 400

    answers = data.get('answers', [])
    if not isinstance(answers, list):
        return jsonify({'success': False, 'error': 'answers 必须是数组'}), 400

    correct = 0
    wrong = 0
    now = _now()
    for ans in answers:
        kana_char = _safe_str(ans.get('kana_char'), max_len=10)
        user_answer = _safe_str(ans.get('user_answer'), max_len=20)
        correct_answer = _safe_str(ans.get('correct_answer'), max_len=20)
        if not kana_char:
            continue
        is_correct = (user_answer == correct_answer) if correct_answer else False
        if is_correct:
            correct += 1
        else:
            wrong += 1
        # 更新进度
        existing = _q(
            "SELECT kprogress_id, correct_count, wrong_count FROM jp_kana_progress "
            "WHERE user_id = ? AND kana_char = ?",
            (user_id, kana_char))
        if existing:
            e = existing[0]
            new_correct = (e['correct_count'] or 0) + (1 if is_correct else 0)
            new_wrong = (e['wrong_count'] or 0) + (0 if is_correct else 1)
            mastered = 1 if new_correct >= 5 and new_wrong == 0 else 0
            _exec(
                "UPDATE jp_kana_progress SET correct_count=?, wrong_count=?, is_mastered=?, last_review_at=? "
                "WHERE kprogress_id=?",
                (new_correct, new_wrong, mastered, now, e['kprogress_id']))
        else:
            _exec(
                "INSERT INTO jp_kana_progress (kprogress_id, user_id, kana_char, kana_type, kana_row, romanji, "
                "is_mastered, correct_count, wrong_count, last_review_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (_gen_id('kp'), user_id, kana_char,
                 _safe_str(ans.get('kana_type'), max_len=20, default='hiragana'),
                 _safe_str(ans.get('kana_row'), max_len=20),
                 _safe_str(ans.get('romanji'), max_len=20),
                 1 if is_correct else 0, 1 if is_correct else 0, 0 if is_correct else 1, now, now))

    total = correct + wrong
    accuracy = round(correct / total * 100, 2) if total else 0
    return jsonify({'success': True, 'data': {
        'correct': correct, 'wrong': wrong, 'total': total, 'accuracy': accuracy,
    }})


@japanese_bp.route('/kana/progress', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def kana_progress():
    """假名学习进度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    try:
        rows = _q("SELECT * FROM jp_kana_progress WHERE user_id = ? ORDER BY last_review_at DESC", (user_id,))
        mastered = sum(1 for r in rows if r.get('is_mastered'))
        return jsonify({'success': True, 'data': {
            'total': len(rows), 'mastered': mastered,
            'progress': rows,
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 2. 词汇学习 (5: list/detail/study/review/search)
# ============================================================================

@japanese_bp.route('/vocabulary/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def vocab_list():
    """词汇列表（按级别）— 自动适配 caopw 等用户"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    explicit_level = _safe_str(request.args.get('level'), default=None)
    levels, primary = _pick_adaptive_levels(user, explicit_level=explicit_level)
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)
    try:
        placeholders = ','.join(['?'] * len(levels))
        rows = _q(f"SELECT * FROM jp_vocabulary WHERE level IN ({placeholders}) ORDER BY level DESC, created_at DESC", levels)
        return jsonify({
            'success': True,
            'data': _paginate(rows, page, page_size),
            'adaptive': {
                'primary_level': primary,
                'levels_served': levels,
                'explicit_level': explicit_level,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/vocabulary/<word_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def vocab_detail(word_id):
    """词汇详情"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    if not word_id or len(word_id) > 100:
        return jsonify({'success': False, 'error': '无效的ID'}), 400
    try:
        rows = _q("SELECT * FROM jp_vocabulary WHERE word_id = ?", (word_id,))
        if not rows:
            return jsonify({'success': False, 'error': '词汇不存在'}), 404
        w = rows[0]
        try:
            w['tags'] = json.loads(w.pop('tags_json', '[]'))
        except Exception:
            pass
        return jsonify({'success': True, 'data': w})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/vocabulary/study', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def vocab_study():
    """学习词汇：记录学习进度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    data = request.get_json(silent=True) or {}
    word_id = _safe_str(data.get('word_id'), max_len=64)
    if not word_id:
        return jsonify({'success': False, 'error': '缺少 word_id'}), 400
    is_correct = _safe_int(data.get('is_correct'), default=1, min_val=0, max_val=1)
    level = _safe_str(data.get('level'), max_len=5, default='N5')
    if level not in _JLPT_LEVELS:
        return jsonify({'success': False, 'error': '级别不在白名单'}), 400

    now = _now()
    try:
        existing = _q(
            "SELECT vprogress_id, srs_grade, correct_count, wrong_count FROM jp_vocabulary_progress "
            "WHERE user_id = ? AND word_id = ?", (user_id, word_id))
        if existing:
            e = existing[0]
            grade = e['srs_grade'] or 0
            grade = min(5, grade + 1) if is_correct else max(0, grade - 1)
            new_correct = (e['correct_count'] or 0) + (1 if is_correct else 0)
            new_wrong = (e['wrong_count'] or 0) + (0 if is_correct else 1)
            mastered = 1 if grade >= 5 else 0
            next_review = (datetime.now() + timedelta(days=_srs_next_interval(grade))).strftime('%Y-%m-%d %H:%M:%S')
            _exec(
                "UPDATE jp_vocabulary_progress SET srs_grade=?, is_mastered=?, correct_count=?, wrong_count=?, "
                "next_review_at=?, last_review_at=? WHERE vprogress_id=?",
                (grade, mastered, new_correct, new_wrong, next_review, now, e['vprogress_id']))
            return jsonify({'success': True, 'data': {'srs_grade': grade, 'next_review_at': next_review}})
        # 新建进度
        grade = 1 if is_correct else 0
        next_review = (datetime.now() + timedelta(days=_srs_next_interval(grade))).strftime('%Y-%m-%d %H:%M:%S')
        vprogress_id = _gen_id('vp')
        _exec(
            "INSERT INTO jp_vocabulary_progress (vprogress_id, user_id, word_id, level, srs_grade, is_mastered, "
            "correct_count, wrong_count, next_review_at, last_review_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (vprogress_id, user_id, word_id, level, grade, 0,
             1 if is_correct else 0, 0 if is_correct else 1, next_review, now, now))
        return jsonify({'success': True, 'data': {'vprogress_id': vprogress_id, 'srs_grade': grade}}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/vocabulary/review', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def vocab_review():
    """复习词汇：获取待复习列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    limit = _safe_int(request.args.get('limit'), default=20, min_val=1, max_val=100)
    now = _now()
    try:
        rows = _q(
            "SELECT vp.*, v.word, v.kana, v.kanji, v.romanji, v.meaning_cn, v.pos, v.example_jp, v.example_cn "
            "FROM jp_vocabulary_progress vp LEFT JOIN jp_vocabulary v ON vp.word_id = v.word_id "
            "WHERE vp.user_id = ? AND vp.next_review_at <= ? AND vp.is_mastered = 0 "
            "ORDER BY vp.next_review_at ASC LIMIT ?",
            (user_id, now, limit))
        return jsonify({'success': True, 'data': {'due_count': len(rows), 'words': rows}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/vocabulary/search', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def vocab_search():
    """词汇搜索"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    keyword = _safe_str(request.args.get('q'), max_len=100, default='')
    if not keyword:
        return jsonify({'success': False, 'error': '缺少搜索关键词'}), 400
    level = _safe_str(request.args.get('level'), default='')
    sql = "SELECT * FROM jp_vocabulary WHERE (word LIKE ? OR kana LIKE ? OR kanji LIKE ? OR meaning_cn LIKE ?)"
    params = [f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%']
    if level and level in _JLPT_LEVELS:
        sql += " AND level = ?"; params.append(level)
    sql += " ORDER BY level ASC LIMIT 50"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 3. 语法学习 (3: list/detail/study)
# ============================================================================

@japanese_bp.route('/grammar/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def grammar_list():
    """语法列表 — 自动适配 caopw 等用户"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    explicit_level = _safe_str(request.args.get('level'), default=None)
    levels, primary = _pick_adaptive_levels(user, explicit_level=explicit_level)
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)
    try:
        placeholders = ','.join(['?'] * len(levels))
        rows = _q(f"SELECT * FROM jp_grammar WHERE level IN ({placeholders}) ORDER BY level DESC, created_at DESC", levels)
        return jsonify({
            'success': True,
            'data': _paginate(rows, page, page_size),
            'adaptive': {'primary_level': primary, 'levels_served': levels},
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/grammar/<grammar_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def grammar_detail(grammar_id):
    """语法详情"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    if not grammar_id or len(grammar_id) > 100:
        return jsonify({'success': False, 'error': '无效的ID'}), 400
    try:
        rows = _q("SELECT * FROM jp_grammar WHERE grammar_id = ?", (grammar_id,))
        if not rows:
            return jsonify({'success': False, 'error': '语法不存在'}), 404
        return jsonify({'success': True, 'data': rows[0]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/grammar/study', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def grammar_study():
    """学习语法：记录进度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    data = request.get_json(silent=True) or {}
    grammar_id = _safe_str(data.get('grammar_id'), max_len=64)
    if not grammar_id:
        return jsonify({'success': False, 'error': '缺少 grammar_id'}), 400
    is_correct = _safe_int(data.get('is_correct'), default=1, min_val=0, max_val=1)
    level = _safe_str(data.get('level'), max_len=5, default='N5')
    now = _now()
    try:
        existing = _q(
            "SELECT gprogress_id, correct_count FROM jp_grammar_progress WHERE user_id = ? AND grammar_id = ?",
            (user_id, grammar_id))
        if existing:
            e = existing[0]
            new_correct = (e['correct_count'] or 0) + (1 if is_correct else 0)
            mastered = 1 if new_correct >= 3 else 0
            _exec(
                "UPDATE jp_grammar_progress SET correct_count=?, is_mastered=?, last_review_at=? WHERE gprogress_id=?",
                (new_correct, mastered, now, e['gprogress_id']))
            return jsonify({'success': True, 'data': {'mastered': bool(mastered)}})
        gprogress_id = _gen_id('gp')
        _exec(
            "INSERT INTO jp_grammar_progress (gprogress_id, user_id, grammar_id, level, is_mastered, "
            "correct_count, wrong_count, last_review_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (gprogress_id, user_id, grammar_id, level, 0,
             1 if is_correct else 0, 0 if is_correct else 1, now, now))
        return jsonify({'success': True, 'data': {'gprogress_id': gprogress_id}}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 4. 听力练习 (3: list/detail/submit)
# ============================================================================

@japanese_bp.route('/listening/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def listening_list():
    """听力列表 — 自动适配 caopw 等用户"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    explicit_level = _safe_str(request.args.get('level'), default=None)
    listening_type = _safe_str(request.args.get('listening_type'), default='')
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)
    levels, primary = _pick_adaptive_levels(user, explicit_level=explicit_level)
    sql = f"SELECT * FROM jp_listening WHERE level IN ({','.join(['?']*len(levels))})"
    params = list(levels)
    if listening_type and listening_type in _LISTENING_TYPES:
        sql += " AND listening_type = ?"; params.append(listening_type)
    sql += " ORDER BY level DESC, created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({
            'success': True,
            'data': _paginate(rows, page, page_size),
            'adaptive': {'primary_level': primary, 'levels_served': levels},
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/listening/<listening_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def listening_detail(listening_id):
    """听力详情"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    if not listening_id or len(listening_id) > 100:
        return jsonify({'success': False, 'error': '无效的ID'}), 400
    try:
        rows = _q("SELECT * FROM jp_listening WHERE listening_id = ?", (listening_id,))
        if not rows:
            return jsonify({'success': False, 'error': '听力不存在'}), 404
        l = rows[0]
        try:
            l['questions'] = json.loads(l.pop('questions_json', '[]'))
        except Exception:
            pass
        return jsonify({'success': True, 'data': l})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/listening/submit', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def listening_submit():
    """听力答题提交"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    data = request.get_json(silent=True) or {}
    listening_id = _safe_str(data.get('listening_id'), max_len=64)
    if not listening_id:
        return jsonify({'success': False, 'error': '缺少 listening_id'}), 400
    answers = data.get('answers', [])
    if not isinstance(answers, list):
        return jsonify({'success': False, 'error': 'answers 必须是数组'}), 400

    correct = sum(1 for a in answers if a.get('is_correct'))
    total = len(answers)
    accuracy = round(correct / total * 100, 2) if total else 0
    score = round(correct / total * 100, 2) if total else 0
    duration_sec = _safe_int(data.get('duration_sec'), default=0, min_val=0, max_val=86400)
    now = _now()
    try:
        _exec(
            "INSERT INTO jp_listening_records (lrecord_id, user_id, listening_id, level, score, accuracy, "
            "correct_count, total_count, duration_sec, submitted_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_gen_id('lr'), user_id, listening_id,
             _safe_str(data.get('level'), max_len=5, default='N5'),
             score, accuracy, correct, total, duration_sec, now, now))
        return jsonify({'success': True, 'data': {
            'score': score, 'accuracy': accuracy, 'correct': correct, 'total': total,
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 5. 阅读理解 (3: list/detail/submit)
# ============================================================================

@japanese_bp.route('/reading/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def reading_list():
    """阅读列表 — 自动适配 caopw 等用户"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    explicit_level = _safe_str(request.args.get('level'), default=None)
    reading_type = _safe_str(request.args.get('reading_type'), default='')
    page = _safe_int(request.args.get('page'), default=1, min_val=1)
    page_size = _safe_int(request.args.get('page_size'), default=20, min_val=1, max_val=100)
    levels, primary = _pick_adaptive_levels(user, explicit_level=explicit_level)
    sql = f"SELECT * FROM jp_reading WHERE level IN ({','.join(['?']*len(levels))})"
    params = list(levels)
    if reading_type and reading_type in _READING_TYPES:
        sql += " AND reading_type = ?"; params.append(reading_type)
    sql += " ORDER BY level DESC, created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({
            'success': True,
            'data': _paginate(rows, page, page_size),
            'adaptive': {'primary_level': primary, 'levels_served': levels},
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/reading/<reading_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def reading_detail(reading_id):
    """阅读详情"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    if not reading_id or len(reading_id) > 100:
        return jsonify({'success': False, 'error': '无效的ID'}), 400
    try:
        rows = _q("SELECT * FROM jp_reading WHERE reading_id = ?", (reading_id,))
        if not rows:
            return jsonify({'success': False, 'error': '阅读不存在'}), 404
        r = rows[0]
        try:
            r['questions'] = json.loads(r.pop('questions_json', '[]'))
        except Exception:
            pass
        return jsonify({'success': True, 'data': r})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/reading/submit', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def reading_submit():
    """阅读答题提交"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    data = request.get_json(silent=True) or {}
    reading_id = _safe_str(data.get('reading_id'), max_len=64)
    if not reading_id:
        return jsonify({'success': False, 'error': '缺少 reading_id'}), 400
    answers = data.get('answers', [])
    if not isinstance(answers, list):
        return jsonify({'success': False, 'error': 'answers 必须是数组'}), 400

    correct = sum(1 for a in answers if a.get('is_correct'))
    total = len(answers)
    accuracy = round(correct / total * 100, 2) if total else 0
    score = round(correct / total * 100, 2) if total else 0
    duration_sec = _safe_int(data.get('duration_sec'), default=0, min_val=0, max_val=86400)
    now = _now()
    try:
        _exec(
            "INSERT INTO jp_reading_records (rrecord_id, user_id, reading_id, level, score, accuracy, "
            "correct_count, total_count, duration_sec, submitted_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_gen_id('rr'), user_id, reading_id,
             _safe_str(data.get('level'), max_len=5, default='N5'),
             score, accuracy, correct, total, duration_sec, now, now))
        return jsonify({'success': True, 'data': {
            'score': score, 'accuracy': accuracy, 'correct': correct, 'total': total,
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 6. JLPT模拟 (3: list/start/submit)
# ============================================================================

@japanese_bp.route('/jlpt/mock/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def jlpt_mock_list():
    """JLPT模拟考试列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    level = _safe_str(request.args.get('level'), default='')
    sql = "SELECT * FROM jp_listening WHERE 1=1"
    params = []
    if level and level in _JLPT_LEVELS:
        sql += " AND level = ?"; params.append(level)
    sql += " ORDER BY level ASC, created_at DESC LIMIT 20"
    try:
        # 简化：JLPT模拟复用听力+阅读资源作为模拟题
        listening = _q(sql, tuple(params))
        reading = _q("SELECT * FROM jp_reading WHERE 1=1" +
                     (" AND level = ?" if level and level in _JLPT_LEVELS else "") +
                     " ORDER BY level ASC, created_at DESC LIMIT 20",
                     tuple(params) if level else ())
        return jsonify({'success': True, 'data': {
            'listening_section': listening,
            'reading_section': reading,
            'levels': list(_JLPT_LEVELS),
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/jlpt/mock/<mock_id>/start', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def jlpt_mock_start(mock_id):
    """开始JLPT模拟考试"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    data = request.get_json(silent=True) or {}
    level = _safe_str(data.get('level'), max_len=5, default='N5')
    if level not in _JLPT_LEVELS:
        return jsonify({'success': False, 'error': '级别不在白名单'}), 400
    session_id = _gen_id('jlpt')
    return jsonify({'success': True, 'data': {
        'session_id': session_id,
        'mock_id': mock_id,
        'level': level,
        'duration_min': 120,
        'sections': ['vocabulary', 'grammar', 'reading', 'listening'],
    }}), 201


@japanese_bp.route('/jlpt/mock/<mock_id>/submit', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def jlpt_mock_submit(mock_id):
    """提交JLPT模拟考试"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    data = request.get_json(silent=True) or {}
    session_id = _safe_str(data.get('session_id'), max_len=64)
    if not session_id:
        return jsonify({'success': False, 'error': '缺少 session_id'}), 400
    level = _safe_str(data.get('level'), max_len=5, default='N5')
    if level not in _JLPT_LEVELS:
        return jsonify({'success': False, 'error': '级别不在白名单'}), 400

    answers = data.get('answers', {})
    if not isinstance(answers, dict):
        return jsonify({'success': False, 'error': 'answers 必须是对象'}), 400

    total = sum(len(v) for v in answers.values()) if answers else 0
    correct = 0
    for section, section_answers in answers.items():
        if isinstance(section_answers, list):
            correct += sum(1 for a in section_answers if isinstance(a, dict) and a.get('is_correct'))

    score = round(correct / total * 180, 2) if total else 0  # JLPT满分180
    pass_score = 95  # N5-N1及格线约95
    is_pass = score >= pass_score
    now = _now()
    try:
        _exec(
            "INSERT INTO jp_listening_records (lrecord_id, user_id, listening_id, level, score, accuracy, "
            "correct_count, total_count, duration_sec, submitted_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_gen_id('jlpt_r'), user_id, mock_id, level, score,
             round(correct / total * 100, 2) if total else 0,
             correct, total,
             _safe_int(data.get('duration_sec'), default=0, min_val=0, max_val=86400),
             now, now))
        return jsonify({'success': True, 'data': {
            'score': score, 'total_score': 180, 'is_pass': is_pass,
            'correct': correct, 'total': total, 'level': level,
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 7. 单词本 (2: list/add)
# ============================================================================

@japanese_bp.route('/wordbook', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def wordbook_list():
    """单词本列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    level = _safe_str(request.args.get('level'), default='')
    is_favorite = request.args.get('is_favorite')
    sql = "SELECT * FROM jp_wordbook WHERE user_id = ?"
    params = [user_id]
    if level and level in _JLPT_LEVELS:
        sql += " AND level = ?"; params.append(level)
    if is_favorite in ('0', '1'):
        sql += " AND is_favorite = ?"; params.append(int(is_favorite))
    sql += " ORDER BY created_at DESC"
    try:
        rows = _q(sql, tuple(params))
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/wordbook/add', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def wordbook_add():
    """添加单词到单词本"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    data = request.get_json(silent=True) or {}
    word_id = _safe_str(data.get('word_id'), max_len=64)
    word = _safe_str(data.get('word'), max_len=100)
    if not word_id and not word:
        return jsonify({'success': False, 'error': '缺少 word_id 或 word'}), 400
    level = _safe_str(data.get('level'), max_len=5, default='N5')
    if level not in _JLPT_LEVELS:
        return jsonify({'success': False, 'error': '级别不在白名单'}), 400

    # 检查是否已存在
    if word_id:
        existing = _q("SELECT wb_id FROM jp_wordbook WHERE user_id = ? AND word_id = ?", (user_id, word_id))
    else:
        existing = _q("SELECT wb_id FROM jp_wordbook WHERE user_id = ? AND word = ?", (user_id, word))
    if existing:
        return jsonify({'success': True, 'data': {'wb_id': existing[0]['wb_id'], 'duplicate': True}})

    wb_id = _gen_id('wb')
    try:
        _exec(
            "INSERT INTO jp_wordbook (wb_id, user_id, word_id, word, kana, meaning_cn, level, note, "
            "is_favorite, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (wb_id, user_id, word_id,
             word,
             _safe_str(data.get('kana'), max_len=100),
             _safe_str(data.get('meaning_cn'), max_len=500),
             level,
             _safe_str(data.get('note'), max_len=500),
             _safe_int(data.get('is_favorite'), default=0, min_val=0, max_val=1),
             _now()))
        return jsonify({'success': True, 'data': {'wb_id': wb_id}}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 模块 8. 进度+推荐 (2: progress/recommend)
# ============================================================================

@japanese_bp.route('/progress', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def jp_progress():
    """日语学习进度"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    try:
        # 各级别进度
        levels = {}
        for level in ['N5', 'N4', 'N3', 'N2', 'N1']:
            vocab = _q(
                "SELECT COUNT(*) c FROM jp_vocabulary_progress WHERE user_id = ? AND level = ?",
                (user_id, level))
            vocab_m = _q(
                "SELECT COUNT(*) c FROM jp_vocabulary_progress WHERE user_id = ? AND level = ? AND is_mastered = 1",
                (user_id, level))
            grammar = _q(
                "SELECT COUNT(*) c FROM jp_grammar_progress WHERE user_id = ? AND level = ?",
                (user_id, level))
            grammar_m = _q(
                "SELECT COUNT(*) c FROM jp_grammar_progress WHERE user_id = ? AND level = ? AND is_mastered = 1",
                (user_id, level))
            levels[level] = {
                'vocab_total': vocab[0]['c'] if vocab else 0,
                'vocab_mastered': vocab_m[0]['c'] if vocab_m else 0,
                'grammar_total': grammar[0]['c'] if grammar else 0,
                'grammar_mastered': grammar_m[0]['c'] if grammar_m else 0,
            }
        return jsonify({'success': True, 'data': levels})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@japanese_bp.route('/recommend', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def jp_recommend():
    """推荐学习内容"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    user_id = user.get('id') or user.get('user_id')
    try:
        # 推荐待复习词汇
        now = _now()
        due_vocab = _q(
            "SELECT vp.word_id, v.word, v.kana, v.meaning_cn, v.level FROM jp_vocabulary_progress vp "
            "LEFT JOIN jp_vocabulary v ON vp.word_id = v.word_id "
            "WHERE vp.user_id = ? AND vp.next_review_at <= ? AND vp.is_mastered = 0 "
            "ORDER BY vp.next_review_at ASC LIMIT 5",
            (user_id, now))
        # 推荐未学语法
        new_grammar = _q(
            "SELECT g.* FROM jp_grammar g WHERE g.level = 'N5' AND g.grammar_id NOT IN "
            "(SELECT grammar_id FROM jp_grammar_progress WHERE user_id = ?) LIMIT 5",
            (user_id,))
        return jsonify({'success': True, 'data': {
            'due_review_vocab': due_vocab,
            'new_grammar': new_grammar,
            'suggestion': '优先复习到期词汇，然后学习新语法',
        }})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


bp = Blueprint('japanese_learning_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'japanese_learning','routes_implemented':1}})
