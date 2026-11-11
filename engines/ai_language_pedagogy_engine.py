#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多语种在线教育平台引擎 [flow_lang_pedagogy_20261031]
=====================================================
仙女座多语种教学中枢 — 英/日/韩沉浸式语言学习全链路 (数学教学法引擎领域适配):
  ① 语言点解析解答  词法/语法/翻译/听力/阅读题型识别 → 语法点模型匹配 → 三轨 LLM 详解 → 本地兜底 → 入库沉淀
  ② 题目创造        按语言/语法考点/难度/题型定向造题 (母题变式 + LLM 精修)
  ③ 分级课程体系    CEFR A1~C1 分级 (日语注 JLPT / 韩语注 TOPIK) + 课程/课时 + 单元测验组卷
  ④ 练习批改        单词 SRS 间隔重复 / 语法客观判分 / 口语跟读相似度评分 / 听力对照 + 五类错因归因
  ⑤ 难度动态弹性    学情画像驱动 ELO 式难度带(2-4)自动升降档 + 事件留痕
  ⑥ 个性化路径推荐  认知层级(L1~L5) + 薄弱语法点前置 + 自动补救练习 + 每日学习计划

平台功能 (用户需求 6 项全覆盖):
  - 用户注册登录 (pbkdf2 + token)      - 学习进度追踪 (课程完成度/正确率/连续打卡)
  - 社区交流 (帖子/评论/点赞)          - 成就激励系统 (XP/等级/徽章/连续打卡)
  - 全操作留痕 mt_lang_activity_log    - EigenFlux languages 领域 6 专家雇佣

设计约束 (项目规则):
  - 本地离线优先: 内置三语种子词库/语法库/口语句/听力文本, 零 token 可跑通全链路
  - LLM 三轨 (local_ollama → spark → volcengine) 仅作增强, 失败自动本地兜底
  - 数据库数据中心统一存储, 全操作入库留痕

CLI:
  python3 ai_language_pedagogy_engine.py init     # 建表 + 雇佣语言专家 + 种子资产
  python3 ai_language_pedagogy_engine.py demo     # 全链路演示(注册→课程→四模块→批改→弹性→路径→社区→成就)
  python3 ai_language_pedagogy_engine.py status   # 总览
"""
import difflib
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# flow_remaining_db_unify_20261022: 统一 DB 权威源 (PROD 优先 → flask-app/database 加成)
from core.db_path import get_db_path

DB_PATH = get_db_path('app.db')
_FLOW = "flow_lang_pedagogy_20261031"
LANGS = {"en": "英语", "ja": "日语", "ko": "韩语"}


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ============================================================
#  建表 (17 张 mt_lang_* 平台表)
# ============================================================

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_lang_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    token TEXT,
    target_languages TEXT DEFAULT 'en,ja,ko',
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    streak_days INTEGER DEFAULT 0,
    last_active_date TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,              -- en/ja/ko
    cefr TEXT NOT NULL,                  -- A1/A2/B1/B2/C1
    native_level TEXT,                   -- JLPT N5~N2 / TOPIK 1~4
    title TEXT NOT NULL,
    description TEXT,
    difficulty INTEGER DEFAULT 1,        -- 1易~5难
    lesson_count INTEGER DEFAULT 0,
    order_no INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_code TEXT UNIQUE NOT NULL,
    course_code TEXT NOT NULL,
    title TEXT NOT NULL,
    lesson_type TEXT NOT NULL,           -- vocab/grammar/speaking/listening
    content TEXT,                        -- JSON {vocab_ids/grammar_id/speaking_ids/listening_id}
    difficulty INTEGER DEFAULT 1,
    order_no INTEGER DEFAULT 0
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_vocab (
    word_id TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    word TEXT NOT NULL,
    reading TEXT,                        -- 日语假名/韩语罗马音/英语音标
    meaning TEXT NOT NULL,
    example_sentence TEXT,
    example_translation TEXT,
    cefr TEXT DEFAULT 'A1',
    topic TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_grammar (
    gp_id TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    title TEXT NOT NULL,
    pattern TEXT,                        -- 句型
    explanation TEXT,
    examples TEXT,                       -- JSON 数组
    cefr TEXT DEFAULT 'A1',
    topic TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_listening (
    audio_id TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    title TEXT NOT NULL,
    transcript TEXT NOT NULL,
    translation TEXT,
    questions TEXT,                      -- JSON [{q, options, answer}]
    cefr TEXT DEFAULT 'A1',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_speaking (
    sp_id TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    sentence TEXT NOT NULL,
    translation TEXT,
    tips TEXT,
    cefr TEXT DEFAULT 'A1',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_qbank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qcode TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    question TEXT NOT NULL,
    q_type TEXT DEFAULT '语法选择',      -- 单词选择/语法选择/翻译/听力理解/阅读理解
    topic TEXT,                          -- 语法点/主题
    knowledge_points TEXT,
    difficulty INTEGER DEFAULT 3,
    answer TEXT,
    solution TEXT,
    analysis TEXT,
    hints TEXT,
    source TEXT DEFAULT 'engine',
    expert_id TEXT,
    model_ref TEXT,
    quality_score REAL DEFAULT 0.8,
    usage_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_vocab_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    word_id TEXT NOT NULL,
    ease REAL DEFAULT 2.5,               -- SM-2 简化版
    interval_days INTEGER DEFAULT 1,
    due_date TEXT NOT NULL,
    repetitions INTEGER DEFAULT 0,
    last_result TEXT,                    -- good/miss
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(username, word_id)
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    language TEXT NOT NULL,
    lesson_code TEXT,
    action TEXT,                         -- lesson_done/vocab_review/grammar_practice/speaking/listening
    score REAL,
    detail TEXT,                         -- JSON
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_learner_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    language TEXT NOT NULL,
    level TEXT DEFAULT 'L3',             -- L1~L5 认知层级
    mastery TEXT,                        -- JSON {语法点/主题: 0~1}
    correct_rate REAL DEFAULT 0.5,
    recent_trend REAL DEFAULT 0,
    difficulty_band TEXT DEFAULT '2-4',
    style TEXT DEFAULT '步骤型',
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(username, language)
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_difficulty_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    language TEXT NOT NULL,
    old_band TEXT,
    new_band TEXT,
    trigger TEXT,
    correct_rate REAL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_practice_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    language TEXT NOT NULL,
    paper_code TEXT,
    score REAL,
    max_score REAL,
    item_results TEXT,                   -- JSON
    error_attribution TEXT,              -- JSON 五类错因
    weak_points TEXT,                    -- JSON
    graded_by TEXT DEFAULT '仙女座语言批改组',
    graded_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    language TEXT NOT NULL,
    level TEXT,
    plan TEXT,                           -- JSON {weak_points, daily_plan, remedial, next_lessons}
    generated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    likes INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    username TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_user_achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    ach_code TEXT NOT NULL,
    earned_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(username, ach_code)
)""",
    """CREATE TABLE IF NOT EXISTS mt_lang_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,                         -- JSON 全操作留痕
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]

# 成就定义 (code → 名称/描述/条件/XP 奖励)
_ACHIEVEMENTS = [
    {"code": "first_step",    "name": "初次启程",   "desc": "完成第一节课",        "cond": ("lessons", 1),   "xp": 20},
    {"code": "vocab_10",      "name": "词汇新兵",   "desc": "累计复习单词 10 次",   "cond": ("vocab", 10),    "xp": 30},
    {"code": "vocab_50",      "name": "词汇达人",   "desc": "累计复习单词 50 次",   "cond": ("vocab", 50),    "xp": 80},
    {"code": "grammar_10",    "name": "语法学徒",   "desc": "完成 10 道语法题",     "cond": ("grammar", 10),  "xp": 40},
    {"code": "speaker",       "name": "开口勇士",   "desc": "完成 5 次口语跟读",    "cond": ("speaking", 5),  "xp": 50},
    {"code": "listener",      "name": "顺风耳",     "desc": "完成 5 次听力训练",    "cond": ("listening", 5), "xp": 50},
    {"code": "streak_3",      "name": "三日之约",   "desc": "连续打卡 3 天",        "cond": ("streak", 3),    "xp": 60},
    {"code": "streak_7",      "name": "七日恒心",   "desc": "连续打卡 7 天",        "cond": ("streak", 7),    "xp": 150},
    {"code": "community",     "name": "社区之星",   "desc": "发布第一篇社区帖子",   "cond": ("posts", 1),     "xp": 30},
    {"code": "polyglot",      "name": "多语者",     "desc": "同时学习 2 门及以上语言", "cond": ("langs", 2),  "xp": 100},
]


def ensure_tables():
    conn = get_conn()
    try:
        for sql in _DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _log(username: str, action: str, detail: dict):
    """全操作留痕 (项目规则: 所有系统操作必须完整留痕入库入日志)"""
    try:
        conn = get_conn()
        conn.execute("INSERT INTO mt_lang_activity_log (username,action,detail) VALUES (?,?,?)",
                     (username, action, json.dumps(detail, ensure_ascii=False)[:2000]))
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


# ============================================================
#  EigenFlux 语言专家雇佣 (动态人力资源中心)
# ============================================================

def hire_language_experts(count: int = 6, round_num: int = 1) -> List[dict]:
    """通过 EigenFlux 雇佣 languages 领域专家 (英/日/韩教研/二语习得/发音/命题)"""
    ensure_tables()
    from services.eigenflux.eigenflux_expert_hiring import get_expert_hiring_engine, ensure_tables as _ef_tables
    _ef_tables()
    return get_expert_hiring_engine().hire_batch(round_num, count, domain="languages")


def form_language_team(round_num: int = 1) -> dict:
    """组建多语种教研专家团队 (跨中心: 专家团队中心协同)"""
    from services.eigenflux.eigenflux_expert_hiring import get_expert_hiring_engine, ensure_tables as _ef_tables
    _ef_tables()
    return get_expert_hiring_engine().form_team(
        round_num, objective="多语种沉浸式教学与个性化路径攻坚")


def list_language_experts() -> List[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT expert_id,name,role,role_cn,level,performance_score,status "
            "FROM eigenflux_experts WHERE domain='languages' ORDER BY performance_score DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _pick_expert(conn, specialty: str = "") -> Optional[dict]:
    """按专长挑活跃语言专家 (教研→解析/路径, 发音→口语, 命题→造题)"""
    try:
        rows = conn.execute(
            "SELECT expert_id,role_cn,name,level FROM eigenflux_experts "
            "WHERE domain='languages' AND status='active' ORDER BY performance_score DESC").fetchall()
        if not rows:
            return None
        prefs = {"发音": "发音", "口语": "发音", "命题": "命题", "习得": "习得", "教研": "教研"}
        want = prefs.get(specialty)
        if want:
            for r in rows:
                if want in (r["role_cn"] or ""):
                    return dict(r)
        return dict(rows[0])
    except sqlite3.Error:
        return None


# ============================================================
#  种子资产 (本地离线优先: 三语内置词库/语法/口语/听力/课程, 幂等)
# ============================================================

_SEED_VOCAB = [
    # 英语 A1
    ("env001", "en", "apple",     "/ˈæpl/",     "苹果",   "I eat an apple every day.",        "我每天吃一个苹果。", "A1", "饮食"),
    ("env002", "en", "book",      "/bʊk/",      "书",     "This book is very interesting.",   "这本书非常有趣。",   "A1", "学习"),
    ("env003", "en", "water",     "/ˈwɔːtər/",  "水",     "Could I have some water?",         "能给我一些水吗？",   "A1", "饮食"),
    ("env004", "en", "friend",    "/frend/",    "朋友",   "She is my best friend.",           "她是我最好的朋友。", "A1", "社交"),
    ("env005", "en", "beautiful", "/ˈbjuːtɪfl/", "美丽的", "The sunset is beautiful today.",  "今天的日落很美。",   "A2", "描述"),
    ("env006", "en", "journey",   "/ˈdʒɜːrni/", "旅程",   "Life is a long journey.",          "人生是一场漫长的旅程。", "B1", "抽象"),
    # 日语 N5
    ("jav001", "ja", "食べる",     "たべる",      "吃",     "毎朝ご飯を食べます。",             "每天早上吃饭。",     "A1", "饮食"),
    ("jav002", "ja", "学校",       "がっこう",    "学校",   "学校へ行きます。",                 "去学校。",           "A1", "场所"),
    ("jav003", "ja", "友達",       "ともだち",    "朋友",   "友達と映画を見ました。",           "和朋友看了电影。",   "A1", "社交"),
    ("jav004", "ja", "綺麗",       "きれい",      "漂亮的", "この花は本当に綺麗です。",         "这朵花真漂亮。",     "A2", "描述"),
    ("jav005", "ja", "経験",       "けいけん",    "经验",   "いい経験になりました。",           "成为了很好的经验。", "B1", "抽象"),
    ("jav006", "ja", "約束",       "やくそく",    "约定",   "約束を守らなければなりません。",   "必须遵守约定。",     "B1", "抽象"),
    # 日语 N2 (B2)
    ("jav007", "ja", "削減",       "さくげん",    "削减",   "コストを削減する必要があります。", "有必要削减成本。",   "B2", "商务"),
    ("jav008", "ja", "改善",       "かいぜん",    "改善",   "サービスの質を改善しました。",     "改善了服务质量。",   "B2", "商务"),
    ("jav009", "ja", "負担",       "ふたん",      "负担",   "家計の負担が増えてきました。",     "家庭负担越来越重。", "B2", "社会"),
    # 日语 N1 (C1)
    ("jav010", "ja", "見積",       "みつもり",    "估价",   "正確な見積もりを出してください。", "请给出准确的估价。", "C1", "商务"),
    ("jav011", "ja", "締結",       "ていけつ",    "签订",   "両社は契約を締結しました。",       "两家公司签订了合同。", "C1", "商务"),
    ("jav012", "ja", "抑制",       "よくせい",    "抑制",   "コスト増を抑制する方針です。",     "方针是抑制成本增加。", "C1", "书面"),
    # 韩语 TOPIK1
    ("kov001", "ko", "사과",       "sagwa",       "苹果",   "저는 사과를 좋아해요.",            "我喜欢苹果。",       "A1", "饮食"),
    ("kov002", "ko", "학교",       "hakgyo",      "学校",   "학교에 갑니다.",                   "去学校。",           "A1", "场所"),
    ("kov003", "ko", "친구",       "chingu",      "朋友",   "친구를 만났어요.",                 "见了朋友。",         "A1", "社交"),
    ("kov004", "ko", "예쁘다",     "yeppeuda",    "漂亮",   "이 꽃이 정말 예쁘네요.",           "这花真漂亮啊。",     "A2", "描述"),
    ("kov005", "ko", "경험",       "gyeongheom",  "经验",   "좋은 경험이었어요.",               "是很好的经验。",     "B1", "抽象"),
    ("kov006", "ko", "약속",       "yaksok",      "约定",   "약속을 지켜야 해요.",              "要遵守约定。",       "B1", "抽象"),
]

_SEED_GRAMMAR = [
    ("eng001", "en", "一般现在时",   "主语 + 动词原形(三单加-s)",
     "表示习惯性、经常性的动作或客观事实。第三人称单数动词加 -s/-es。",
     ["I go to school every day.", "She watches TV in the evening."], "A1", "时态"),
    ("eng002", "en", "现在进行时",   "主语 + be + V-ing",
     "表示此刻正在进行的动作。be 动词随主语变化。",
     ["I am reading a book now.", "They are playing football."], "A1", "时态"),
    ("eng003", "en", "比较级",       "形容词 + er / more + 形容词",
     "两者比较。单音节加 -er, 多音节前加 more, 最高级加 -est/most。",
     ["This book is more interesting than that one.", "He is taller than me."], "A2", "比较"),
    ("jag001", "ja", "です・ます形", "名词/形容词 + です / 动词ます形",
     "日语敬体基础。名词句结尾加です, 动词句结尾用ます形。",
     ["これは本です。", "毎日勉強します。"], "A1", "敬体"),
    ("jag002", "ja", "を助词",       "名词 + を + 他动词",
     "を 表示他动词的宾语。发音作 'o'。",
     ["パンを食べます。", "水を飲みます。"], "A1", "助词"),
    ("jag003", "ja", "て形",         "动词て形 + てください / ている",
     "て形是日语最重要的活用: 请求(てください)、进行(ている)、并列等。",
     ["ちょっと待ってください。", "今、本を読んでいます。"], "A2", "活用"),
    ("jag004", "ja", "ば〜ほど",     "动词ば形 + 同一动词辞书形 + ほど",
     "N2 比例表达「越…越…」。前接ば形后接辞书形, 形容词亦可使用。",
     ["日本語は勉強すればするほど面白くなる。", "パソコンは軽いほど便利だ。"], "B2", "比例"),
    ("jag005", "ja", "〜ざるを得ない", "动词ない形(ぬ) + ざるを得ない",
     "N1 书面语法「不得不…」。する 变 せざるを得ない, 表示别无选择。",
     ["今日は残業せざるを得ない。", "その提案を受けざるを得なかった。"], "C1", "书面"),
    ("kog001", "ko", "-요体",        "词干 + 아요/어요/여요",
     "韩语非格式体终结词尾, 日常礼貌用语的基础。元音末音接 아요/어요。",
     ["가다 → 가요.", "먹다 → 먹어요."], "A1", "终结词尾"),
    ("kog002", "ko", "을/를 助词",   "宾语 + 을/를 + 动词",
     "을 接辅音结尾名词, 를 接元音结尾名词, 标记宾语。",
     ["밥을 먹어요.", "커피를 마셔요."], "A1", "助词"),
    ("kog003", "ko", "-고 싶다",     "动词词干 + 고 싶어요",
     "表示说话人的愿望「想做…」。主语为第三人称时用 -고 싶어하다。",
     ["한국에 가고 싶어요.", "김치를 먹고 싶어요."], "A2", "愿望表达"),
]

_SEED_SPEAKING = [
    ("ens001", "en", "Nice to meet you. I'm looking forward to learning with you.", "很高兴认识你, 期待与你一起学习。", "注意 meet /miːt/ 长元音, looking forward 连读", "A1"),
    ("ens002", "en", "Could you speak more slowly, please?", "请您说慢一点好吗？", "Could you 后接动词原形, 尾调上扬表礼貌请求", "A1"),
    ("ens003", "en", "I'd like to improve my pronunciation step by step.", "我想一步步改进我的发音。", "I'd like to 缩读 /aɪdlaɪktə/, 重音落在 improve", "A2"),
    ("jas001", "ja", "はじめまして、どうぞよろしくお願いします。", "初次见面, 请多关照。", "よろしくお願いします 是万能寒暄, 语速平稳", "A1"),
    ("jas002", "ja", "もう少しゆっくり話してください。", "请再说慢一点。", "ゆっくり 重音在ゆ, ください 尾音下沉表郑重", "A1"),
    ("jas003", "ja", "毎日少しずつ練習したいです。", "想每天一点点地练习。", "少しずつ 表「一点点地」, たいです 表愿望", "A2"),
    ("jas004", "ja", "本日ご提示した改善案について、ご意見を伺えますでしょうか。", "关于今天提出的改善方案, 能听听您的意见吗？", "伺える 是聞く 的谦让语, でしょうか 郑重收尾", "B2"),
    ("jas005", "ja", "恐れ入りますが、今回の締結条件につきましては、持ち帰って検討させていただきます。", "不好意思, 关于本次签约条件, 请允许我带回去研究。", "恐れ入りますが 为缓冲语, させていただきます 是谦让最高级", "C1"),
    ("kos001", "ko", "처음 뵙겠습니다. 잘 부탁드립니다.", "初次见面, 请多关照。", "뵙겠습니다 是 만나다 的敬语, 发音 bpwaep-get-", "A1"),
    ("kos002", "ko", "조천천히 말해 주세요.", "请说慢一点。", "천천히 重音在 천, 주세요 尾调平缓表请求", "A1"),
    ("kos003", "ko", "매일 조금씩 연습하고 싶어요.", "想每天练习一点点。", "조금씩 表「一点点」, 싶어요 表愿望, 连读 조그씨", "A2"),
]

_SEED_LISTENING = [
    ("enl001", "en", "Airport Check-in 机场值机",
     "Good morning. May I see your passport and boarding pass, please? — Sure, here you are. — Thank you. Your seat is 32A, and boarding starts at ten thirty.",
     "早上好。请出示您的护照和登机牌。— 好的, 给您。— 谢谢。您的座位是 32A, 十点半开始登机。",
     [{"q": "What is the seat number?", "options": ["12A", "32A", "23B", "33A"], "answer": "32A"},
      {"q": "When does boarding start?", "options": ["10:13", "10:30", "11:30", "3:10"], "answer": "10:30"}], "A2"),
    ("jal001", "ja", "駅で 在车站",
     "すみません、東京駅はどこですか。— 次の電車で二駅目です。— ありがとうございます。— いいえ、気をつけて。",
     "请问, 东京站在哪里？— 坐下一班车, 第二站就到。— 谢谢。— 不客气, 路上小心。",
     [{"q": "東京駅は何駅目ですか。", "options": ["一駅目", "二駅目", "三駅目", "四駅目"], "answer": "二駅目"}], "A2"),
    ("jal002", "ja", "会議で 在会议上",
     "部長、来期のコスト削減案がまとまりました。— わかった。見積もりと合わせて金曜までに出してくれ。— かしこまりました。負担の少ない案を優先します。",
     "部长, 下期成本削减方案汇总好了。— 知道了。连同估价一起周五之前交上来。— 遵命。优先考虑负担较小的方案。",
     [{"q": "いつまでに提出しますか。", "options": ["水曜日", "木曜日", "金曜日", "土曜日"], "answer": "金曜日"},
      {"q": "何を優先しますか。", "options": ["スピード", "負担の少ない案", "コスト重視", "見積もり"], "answer": "負担の少ない案"}], "B2"),
    ("kol001", "ko", "카페에서 在咖啡厅",
     "주문하시겠어요? — 아이스 아메리카노 한 잔 주세요. — 사이즈는 어떻게 하세요? — 큰 거로 주세요.",
     "要点什么吗？— 请给我一杯冰美式。— 要什么尺寸？— 请给大杯。",
     [{"q": "무엇을 주문했어요?", "options": ["따뜻한 라떼", "아이스 아메리카노", "아이스 라떼", "홍차"], "answer": "아이스 아메리카노"}], "A2"),
]

# 课程体系: 英语/韩语 3 级 (A1/A2/B1), 日语 5 级 (N5~N1); 每级 1~4 课时 (词汇/语法/口语/听力)
_SEED_COURSES = [
    # (course_code, language, cefr, native_level, title, description, difficulty)
    ("ENC-A1", "en", "A1", "KET入门",  "英语入门 · 生活场景起步", "零基础起步: 问候、饮食、学习三大场景词汇与基础时态。", 1),
    ("ENC-A2", "en", "A2", "KET",      "英语初级 · 表达与比较",   "描述事物、进行比较, 掌握比较级与日常口语请求句型。", 2),
    ("ENC-B1", "en", "B1", "PET",      "英语中级 · 观点与旅程",   "谈论旅程与抽象话题, 听懂机场等真实场景对话。", 3),
    ("JAC-N5", "ja", "A1", "JLPT N5",  "日语入门 · 五十音后的第一课", "敬体基础、を助词、常见饮食场所词汇。", 1),
    ("JAC-N4", "ja", "A2", "JLPT N4",  "日语初级 · て形活用",     "て形请求与进行体, 描述人物与事物。", 2),
    ("JAC-N3", "ja", "B1", "JLPT N3",  "日语中级 · 抽象表达",     "経験/約束等抽象名词, 读解长句。", 3),
    ("JAC-N2", "ja", "B2", "JLPT N2",  "日语中高级 · 商务与改善", "削減/改善/負担等社会话题词汇, ば〜ほど比例表达, 会议真实听力。", 4),
    ("JAC-N1", "ja", "C1", "JLPT N1",  "日语高级 · 正式场合精准表达", "見積/締結等正式语汇, 〜ざるを得ない书面语法, 商务敬语跟读。", 5),
    ("KOC-T1", "ko", "A1", "TOPIK 1",  "韩语入门 · 从 안녕 开始",   "-요体、을/를 助词、饮食学校场景词汇。", 1),
    ("KOC-T2", "ko", "A2", "TOPIK 2",  "韩语初级 · 愿望表达",     "-고 싶다 愿望句、形容词描述。", 2),
    ("KOC-T3", "ko", "B1", "TOPIK 3",  "韩语中级 · 经验与约定",   "抽象名词运用、咖啡厅等真实听力。", 3),
]

# 课时: (lesson_code, course_code, title, type, content, difficulty) content 引用种子 id
_SEED_LESSONS = [
    ("EN-A1-L1", "ENC-A1", "词汇: 日常饮食与学习用品", "vocab",     {"vocab_ids": ["env001", "env002", "env003", "env004"]}, 1),
    ("EN-A1-L2", "ENC-A1", "语法: 一般现在时与现在进行时", "grammar", {"grammar_id": "eng001", "extra": "eng002"}, 1),
    ("EN-A1-L3", "ENC-A1", "口语: 初次见面问候",       "speaking",  {"speaking_ids": ["ens001", "ens002"]}, 1),
    ("EN-A1-L4", "ENC-A1", "听力: 机场值机",           "listening", {"listening_id": "enl001"}, 2),
    ("EN-A2-L1", "ENC-A2", "词汇: 描述性形容词",       "vocab",     {"vocab_ids": ["env005"]}, 2),
    ("EN-A2-L2", "ENC-A2", "语法: 比较级",             "grammar",   {"grammar_id": "eng003"}, 2),
    ("EN-A2-L3", "ENC-A2", "口语: 礼貌请求与发音",     "speaking",  {"speaking_ids": ["ens002", "ens003"]}, 2),
    ("EN-B1-L1", "ENC-B1", "词汇: 旅程与抽象名词",     "vocab",     {"vocab_ids": ["env006"]}, 3),
    ("JA-N5-L1", "JAC-N5", "词汇: 饮食与场所",         "vocab",     {"vocab_ids": ["jav001", "jav002", "jav003"]}, 1),
    ("JA-N5-L2", "JAC-N5", "语法: です・ます形与を助词", "grammar",  {"grammar_id": "jag001", "extra": "jag002"}, 1),
    ("JA-N5-L3", "JAC-N5", "口语: 日语寒暄问候",       "speaking",  {"speaking_ids": ["jas001", "jas002"]}, 1),
    ("JA-N4-L1", "JAC-N4", "语法: て形活用",           "grammar",   {"grammar_id": "jag003"}, 2),
    ("JA-N4-L2", "JAC-N4", "词汇: 描述与评价",         "vocab",     {"vocab_ids": ["jav004"]}, 2),
    ("JA-N3-L1", "JAC-N3", "词汇: 経験・約束抽象名词", "vocab",     {"vocab_ids": ["jav005", "jav006"]}, 3),
    ("JA-N2-L1", "JAC-N2", "词汇: 削減・改善・負担",   "vocab",     {"vocab_ids": ["jav007", "jav008", "jav009"]}, 4),
    ("JA-N2-L2", "JAC-N2", "语法: ば〜ほど 比例表达",   "grammar",   {"grammar_id": "jag004"}, 4),
    ("JA-N2-L3", "JAC-N2", "听力: 会议指示",           "listening", {"listening_id": "jal002"}, 4),
    ("JA-N1-L1", "JAC-N1", "词汇: 見積・締結・抑制",   "vocab",     {"vocab_ids": ["jav010", "jav011", "jav012"]}, 5),
    ("JA-N1-L2", "JAC-N1", "语法: 〜ざるを得ない",     "grammar",   {"grammar_id": "jag005"}, 5),
    ("JA-N1-L3", "JAC-N1", "口语: 商务郑重表达",       "speaking",  {"speaking_ids": ["jas004", "jas005"]}, 5),
    ("KO-T1-L1", "KOC-T1", "词汇: 饮食与学校",         "vocab",     {"vocab_ids": ["kov001", "kov002", "kov003"]}, 1),
    ("KO-T1-L2", "KOC-T1", "语法: -요体与을/를 助词",   "grammar",   {"grammar_id": "kog001", "extra": "kog002"}, 1),
    ("KO-T1-L3", "KOC-T1", "口语: 韩语初次见面",       "speaking",  {"speaking_ids": ["kos001", "kos002"]}, 1),
    ("KO-T2-L1", "KOC-T2", "语法: -고 싶다 愿望表达",   "grammar",   {"grammar_id": "kog003"}, 2),
    ("KO-T2-L2", "KOC-T2", "词汇: 描述形容词",         "vocab",     {"vocab_ids": ["kov004"]}, 2),
    ("KO-T3-L1", "KOC-T3", "词汇: 경험・약속 抽象名词", "vocab",     {"vocab_ids": ["kov005", "kov006"]}, 3),
]


def seed_base_assets() -> Dict[str, int]:
    """种子资产入库 (幂等): 词汇/语法/口语/听力/课程/课时/成就"""
    ensure_tables()
    n = {"vocab": 0, "grammar": 0, "listening": 0, "speaking": 0, "courses": 0, "lessons": 0}
    conn = get_conn()
    try:
        for wid, lang, word, reading, meaning, ex, ext, cefr, topic in _SEED_VOCAB:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_vocab (word_id,language,word,reading,meaning,"
                "example_sentence,example_translation,cefr,topic) VALUES (?,?,?,?,?,?,?,?,?)",
                (wid, lang, word, reading, meaning, ex, ext, cefr, topic))
            n["vocab"] += cur.rowcount
        for gid, lang, title, pattern, expl, examples, cefr, topic in _SEED_GRAMMAR:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_grammar (gp_id,language,title,pattern,explanation,"
                "examples,cefr,topic) VALUES (?,?,?,?,?,?,?,?)",
                (gid, lang, title, pattern, expl, json.dumps(examples, ensure_ascii=False), cefr, topic))
            n["grammar"] += cur.rowcount
        for aid, lang, title, transcript, translation, questions, cefr in _SEED_LISTENING:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_listening (audio_id,language,title,transcript,"
                "translation,questions,cefr) VALUES (?,?,?,?,?,?,?)",
                (aid, lang, title, transcript, translation, json.dumps(questions, ensure_ascii=False), cefr))
            n["listening"] += cur.rowcount
        for sid, lang, sentence, translation, tips, cefr in _SEED_SPEAKING:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_speaking (sp_id,language,sentence,translation,tips,cefr) "
                "VALUES (?,?,?,?,?,?)", (sid, lang, sentence, translation, tips, cefr))
            n["speaking"] += cur.rowcount
        for code, lang, cefr, native, title, desc, diff in _SEED_COURSES:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_courses (course_code,language,cefr,native_level,title,"
                "description,difficulty,order_no) VALUES (?,?,?,?,?,?,?,?)",
                (code, lang, cefr, native, title, desc, diff, len(code)))
            n["courses"] += cur.rowcount
        for lcode, ccode, title, ltype, content, diff in _SEED_LESSONS:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_lessons (lesson_code,course_code,title,lesson_type,"
                "content,difficulty,order_no) VALUES (?,?,?,?,?,?,?)",
                (lcode, ccode, title, ltype, json.dumps(content, ensure_ascii=False), diff, 0))
            n["lessons"] += cur.rowcount
        # 课程课时数回填
        conn.execute("""UPDATE mt_lang_courses SET lesson_count=(
            SELECT count(*) FROM mt_lang_lessons WHERE mt_lang_lessons.course_code=mt_lang_courses.course_code)""")
        for a in _ACHIEVEMENTS:
            conn.execute(
                "INSERT OR IGNORE INTO mt_lang_user_achievements (username,ach_code) VALUES ('__meta__','DEF__'||?)",
                (a["code"],))  # 占位防重定义; 真正定义在代码 _ACHIEVEMENTS
        conn.commit()
    finally:
        conn.close()
    return n


# ============================================================
#  用户注册登录 (pbkdf2 + token, 平台自持用户体系)
# ============================================================

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, _hex = (stored or "").split("$", 1)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return secrets.compare_digest(h.hex(), _hex)
    except Exception:
        return False


def register_user(username: str, password: str, display_name: str = "",
                  target_languages: str = "en,ja,ko") -> Dict[str, Any]:
    """注册: 用户名唯一 + pbkdf2 哈希 + 初始 token"""
    ensure_tables()
    username = (username or "").strip()
    if not username or not password:
        return {"ok": False, "error": "username/password 不能为空"}
    if len(password) < 6:
        return {"ok": False, "error": "密码至少 6 位"}
    conn = get_conn()
    try:
        exists = conn.execute("SELECT 1 FROM mt_lang_users WHERE username=?", (username,)).fetchone()
        if exists:
            return {"ok": False, "error": f"用户名已存在: {username}"}
        token = secrets.token_hex(24)
        conn.execute(
            "INSERT INTO mt_lang_users (username,password_hash,display_name,token,target_languages,last_active_date) "
            "VALUES (?,?,?,?,?,?)",
            (username, _hash_password(password), display_name or username, token, target_languages, _today()))
        conn.commit()
        _log(username, "REGISTER", {"username": username})
        return {"ok": True, "username": username, "token": token,
                "display_name": display_name or username}
    finally:
        conn.close()


def login_user(username: str, password: str) -> Dict[str, Any]:
    """登录: 密码校验 → 换发新 token + 打卡连击"""
    ensure_tables()
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM mt_lang_users WHERE username=?", ((username or "").strip(),)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return {"ok": False, "error": "用户名或密码错误"}
        token = secrets.token_hex(24)
        streak = row["streak_days"] or 0
        last = row["last_active_date"]
        if last != _today():
            streak = streak + 1 if last == (_today() and str(datetime.now() - timedelta(days=1))[:10]) else 1
        conn.execute(
            "UPDATE mt_lang_users SET token=?, last_active_date=?, streak_days=?, updated_at=? WHERE id=?",
            (token, _today(), streak, _now(), row["id"]))
        conn.commit()
        _log(row["username"], "LOGIN", {"streak": streak})
        return {"ok": True, "username": row["username"], "token": token,
                "display_name": row["display_name"], "xp": row["xp"], "level": row["level"],
                "streak_days": streak}
    finally:
        conn.close()


def auth_user(token: str = "", username: str = "") -> Optional[dict]:
    """鉴权: token 优先, 用户名兜底 (供蓝图会话用户复用)"""
    conn = get_conn()
    try:
        if token:
            row = conn.execute("SELECT * FROM mt_lang_users WHERE token=?", (token,)).fetchone()
            if row:
                return dict(row)
        if username and not str(username).startswith("guest"):
            row = conn.execute("SELECT * FROM mt_lang_users WHERE username=?", (username,)).fetchone()
            if row:
                return dict(row)
        # 未注册会话用户: 以会话名自动建轻量账号 (游客转化, 零摩擦体验)
        if username and not str(username).startswith("guest"):
            return None
        return None
    finally:
        conn.close()


def _require_user(token: str, username: str) -> Optional[dict]:
    return auth_user(token, username)


def _add_xp(conn, username: str, amount: int):
    conn.execute(
        "UPDATE mt_lang_users SET xp=xp+?, level=max(1,(xp+?)/100+1), updated_at=? WHERE username=?",
        (amount, amount, _now(), username))


def _touch_streak(conn, username: str):
    row = conn.execute("SELECT streak_days,last_active_date FROM mt_lang_users WHERE username=?",
                       (username,)).fetchone()
    if not row:
        return
    today = _today()
    if row["last_active_date"] == today:
        return
    yst = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = (row["streak_days"] or 0) + 1 if row["last_active_date"] == yst else 1
    conn.execute("UPDATE mt_lang_users SET streak_days=?, last_active_date=? WHERE username=?",
                 (streak, today, username))


def _check_achievements(conn, username: str) -> List[dict]:
    """成就扫描: 按累计行为解锁徽章 + XP 奖励"""
    got = []
    cnt = {}
    cnt["vocab"] = conn.execute(
        "SELECT count(*) FROM mt_lang_vocab_reviews WHERE username=?", (username,)).fetchone()[0]
    for act in ("grammar", "speaking", "listening"):
        cnt[act] = conn.execute(
            "SELECT count(*) FROM mt_lang_progress WHERE username=? AND action=?", (username, act)).fetchone()[0]
    cnt["lessons"] = conn.execute(
        "SELECT count(DISTINCT lesson_code) FROM mt_lang_progress WHERE username=? AND lesson_code IS NOT NULL",
        (username,)).fetchone()[0]
    cnt["posts"] = conn.execute("SELECT count(*) FROM mt_lang_posts WHERE username=?", (username,)).fetchone()[0]
    cnt["streak"] = conn.execute("SELECT streak_days FROM mt_lang_users WHERE username=?", (username,)).fetchone()[0] \
        if conn.execute("SELECT 1 FROM mt_lang_users WHERE username=?", (username,)).fetchone() else 0
    cnt["langs"] = conn.execute(
        "SELECT count(DISTINCT language) FROM mt_lang_progress WHERE username=?", (username,)).fetchone()[0]
    for a in _ACHIEVEMENTS:
        kind, thr = a["cond"]
        if cnt.get(kind, 0) >= thr:
            cur = conn.execute(
                "INSERT OR IGNORE INTO mt_lang_user_achievements (username,ach_code) VALUES (?,?)",
                (username, a["code"]))
            if cur.rowcount:
                _add_xp(conn, username, a["xp"])
                got.append({"code": a["code"], "name": a["name"], "xp": a["xp"]})
    return got


# ============================================================
#  ① 题型识别 + 解析解答 (语言点)
# ============================================================

_TYPE_KEYWORDS = [
    ("单词题",   ["单词", "词汇", "什么意思", "意思是", "中文", "怎么读"]),
    ("听力理解", ["听力", "听录音", "对话", "音频", "刚才听到"]),
    ("翻译题",   ["翻译", "译成", "翻成", "怎么说", "用英语/日语/韩语说"]),
    ("阅读理解", ["阅读", "短文", "文章", " passage"]),
    ("语法选择", ["语法", "填空", "选词", "助词", "时态", "活用", "词尾"]),
]

_KNOWN_TOPICS = [
    ("时态", ["时态", "现在时", "过去时", "进行时", "完成时"]),
    ("助词", ["助词", "を", "は", "が", "에", "을", "를", "은", "는"]),
    ("活用", ["て形", "た形", "活用", "变形", "词尾", "变位"]),
    ("敬体与礼貌", ["です", "ます", "요体", "敬语", "礼貌", "请"]),
    ("比较与愿望", ["比较级", "最高级", "たい", "싶다", "想", "愿望"]),
    ("场景词汇", ["机场", "车站", "咖啡", "餐厅", "问候", "打招呼", "饮食", "学校"]),
]


def classify_language_question(question: str, language: str = "en") -> Dict[str, Any]:
    """语言题型识别 (零 token 本地规则): 关键词加权"""
    scores: Dict[str, int] = {}
    for qtype, kws in _TYPE_KEYWORDS:
        for kw in kws:
            if kw in question:
                scores[qtype] = scores.get(qtype, 0) + 2
    if "?" in question or "？" in question:
        scores["语法选择"] = scores.get("语法选择", 0) + 1
    q_type = max(scores, key=scores.get) if scores else "语法选择"
    topic, kps = None, []
    for t, kws in _KNOWN_TOPICS:
        hit = [k for k in kws if k in question]
        if hit:
            topic = t
            kps = hit
            break
    if not topic:
        # 词汇匹配 → 场景词汇考点
        conn = get_conn()
        try:
            row = conn.execute("SELECT topic FROM mt_lang_vocab WHERE language=? AND word=? LIMIT 1",
                               (language, question.strip())).fetchone()
            if row:
                topic = "场景词汇"
                kps = [question.strip()]
        finally:
            conn.close()
    return {"q_type": q_type, "topic": topic, "knowledge_points": kps}


def _match_grammar_model(conn, language: str, topic: Optional[str], kps: List[str]) -> Optional[dict]:
    """匹配语法点模型 (母题库 = mt_lang_grammar)"""
    try:
        rows = conn.execute("SELECT * FROM mt_lang_grammar WHERE language=?", (language,)).fetchall()
    except sqlite3.Error:
        return None
    best, best_hit = None, 0
    for r in rows:
        hit = 1 if (topic and r["topic"] == topic) else 0
        exs = r["examples"] or ""
        hit += sum(1 for k in kps if k in (r["title"] + r["pattern"] + exs))
        if hit > best_hit:
            best, best_hit = dict(r), hit
    return best if best_hit > 0 else None


def _local_solution(question: str, q_type: str, language: str,
                    topic: Optional[str], mother: Optional[dict]) -> str:
    """本地兜底解析 (零 token): 语法点模型 + 通用语言学习框架"""
    lname = LANGS.get(language, language)
    parts = [f"【题型定位】{q_type} · {lname}" + (f" · 考点「{topic}」" if topic else " · 综合考点")]
    if mother:
        parts.append(f"【语法点模型】{mother['title']}（{mother['pattern']}）")
        if mother.get("explanation"):
            parts.append(f"【规则讲解】{mother['explanation']}")
        try:
            exs = json.loads(mother["examples"] or "[]")
            if exs:
                parts.append("【例句】" + " / ".join(exs[:3]))
        except Exception:
            pass
    else:
        parts.append("【学习步骤】1.圈出关键词与词尾形态 2.回想对应语法规则 3.代入验证 4.朗读成句检验语感")
    parts.append("【通用提醒】语言点靠场景记忆: 学完立即造 1 个自己的句子, 并跟读 3 遍。")
    return "\n".join(p for p in parts if p.strip())


def _llm_solution(question: str, q_type: str, language: str, topic: Optional[str]) -> Optional[str]:
    """三轨 LLM 详解 (local_ollama → spark → volcengine), 失败走本地兜底"""
    try:
        from ai_engines.ai_dual_route_engine import route_and_chat
        lname = LANGS.get(language, language)
        sys_p = (f"你是资深{lname}特级教师。给出分步讲解: ①语言点定位 ②规则讲解 "
                 "③分步推导(含变形/语序) ④最终答案 ⑤易错点与跟读建议。")
        prompt = (f"语种: {lname}\n题型: {q_type}\n考点: {topic or '待分析'}\n题目: {question}\n"
                  "请按五段式给出完整解析。")
        r = route_and_chat(prompt, system=sys_p, kind="research",
                           flow_id=_FLOW, prefer_local=True)
        if r and r.get("success") and (r.get("response") or "").strip():
            return f"[{r.get('route', 'llm')}] " + r["response"].strip()[:3000]
    except Exception:
        pass
    return None


def solve_language_question(question: str, language: str = "en",
                            expert_specialty: str = "教研") -> Dict[str, Any]:
    """① 语言点解析解答: 题库命中 → 语法点模型匹配 → LLM 生成 → 本地兜底, 全部入库沉淀"""
    ensure_tables()
    seed_base_assets()
    language = language if language in LANGS else "en"
    cls = classify_language_question(question, language)
    q_type, topic, kps = cls["q_type"], cls["topic"], cls["knowledge_points"]
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM mt_lang_qbank WHERE language=? AND question LIKE ? LIMIT 1",
            (language, f"%{question.strip()[:60]}%")).fetchone()
        if row:
            conn.execute("UPDATE mt_lang_qbank SET usage_count=usage_count+1, updated_at=? WHERE id=?",
                         (_now(), row["id"]))
            conn.commit()
            return {"hit": "qbank", "qcode": row["qcode"], "q_type": row["q_type"],
                    "topic": row["topic"], "difficulty": row["difficulty"],
                    "solution": row["solution"], "analysis": row["analysis"],
                    "hints": json.loads(row["hints"] or "[]")}
        expert = _pick_expert(conn, expert_specialty)
        mother = _match_grammar_model(conn, language, topic, kps)
    finally:
        conn.close()
    solution = _llm_solution(question, q_type, language, topic) or _local_solution(
        question, q_type, language, topic, mother)
    analysis = (f"题型「{q_type}」· {LANGS.get(language, language)} · 考点「{topic or '综合'}」"
                + (f" · 语法点模型: {mother['title']}" if mother else ""))
    hints = json.dumps([
        f"提示1: 先确认考点「{topic or q_type}」对应的语法规则",
        "提示2: 圈出关键词与词尾/助词形态, 再代入规则",
        "提示3: 造一个自己的句子并跟读 3 遍巩固语感",
    ], ensure_ascii=False)
    qcode = _uid("LANGQ")
    diff = 3 if not mother else {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5}.get(
        (mother.get("cefr") or "A1"), 3)
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_lang_qbank (qcode,language,question,q_type,topic,knowledge_points,
               difficulty,answer,solution,analysis,hints,source,expert_id,model_ref,quality_score)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (qcode, language, question, q_type, topic, ",".join(kps), diff,
             None, solution, analysis, hints,
             "llm" if solution.startswith("[") else "engine",
             expert["expert_id"] if expert else None,
             mother["gp_id"] if mother else None, 0.85))
        conn.commit()
    finally:
        conn.close()
    return {"hit": "new", "qcode": qcode, "q_type": q_type, "topic": topic,
            "difficulty": diff, "solution": solution, "analysis": analysis,
            "hints": json.loads(hints), "expert": expert["name"] if expert else None,
            "grammar_model": mother["title"] if mother else None}


# ============================================================
#  ② 题目创造 (语言版)
# ============================================================

def create_questions(topic: str, language: str = "en", difficulty: int = 3, count: int = 3,
                     q_type: str = "语法选择", expert_specialty: str = "命题") -> List[dict]:
    """题目创造: 语法点模板 + LLM 精修, 全部入 mt_lang_qbank"""
    ensure_tables()
    language = language if language in LANGS else "en"
    conn = get_conn()
    try:
        expert = _pick_expert(conn, expert_specialty)
        mothers = conn.execute(
            "SELECT * FROM mt_lang_grammar WHERE language=? AND (topic=? OR title LIKE ?) LIMIT 3",
            (language, topic, f"%{topic}%")).fetchall()
        mother = dict(mothers[0]) if mothers else None
    finally:
        conn.close()

    made: List[dict] = []
    rows_to_insert: List[tuple] = []
    # LLM 调用必须在事务外执行 (修复: 原实现在写事务内逐题调 LLM, 长期占锁
    # 导致注册等并发写请求 OperationalError: database is locked)
    for i in range(count):
        variant_seed = _uid("LVAR")
        question = (f"[{LANGS[language]}·{q_type}·难度{difficulty}] 变式{variant_seed[-4:]}: "
                    f"围绕语法点「{topic}」的{q_type}, 难度层级 {difficulty}/5, "
                    "考查形态变化与场景运用。")
        sys_p = (f"你是{LANGS[language]}命题专家。输出格式: 题目→答案→解析→易错点, "
                 "例句需自然地道。")
        prompt = (f"请围绕语法点「{topic}」原创一道{LANGS[language]}{q_type}"
                  f"(难度{difficulty}/5), 并给出答案与解析。")
        llm_txt = None
        try:
            from ai_engines.ai_dual_route_engine import route_and_chat
            r = route_and_chat(prompt, system=sys_p, kind="chat",
                               flow_id=_FLOW, prefer_local=True)
            if r and r.get("success") and (r.get("response") or "").strip():
                llm_txt = r["response"].strip()[:2500]
        except Exception:
            llm_txt = None
        if llm_txt:
            question = llm_txt.split("\n")[0].strip()[:300]
            solution = llm_txt
        else:
            solution = (_local_solution(question, q_type, language, topic, mother)
                        + f"\n【变式编号】{variant_seed}")
        qcode = _uid("LANGQ")
        rows_to_insert.append((
            qcode, language, question, q_type, topic, topic, difficulty,
            solution,
            f"原创变式题 · 语法点「{topic}」· 难度{difficulty}",
            json.dumps([f"语法模型: {topic}", "先辨形态, 再验证语序"], ensure_ascii=False),
            "llm" if llm_txt else "engine",
            expert["expert_id"] if expert else None,
            mother["gp_id"] if mother else None,
            round(0.7 + 0.05 * difficulty, 2)))
        made.append({"qcode": qcode, "question": question[:120],
                     "difficulty": difficulty, "via": "llm" if llm_txt else "template"})
    if rows_to_insert:
        conn = get_conn()
        try:
            conn.executemany(
                """INSERT INTO mt_lang_qbank (qcode,language,question,q_type,topic,knowledge_points,
                   difficulty,solution,analysis,hints,source,expert_id,model_ref,quality_score)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows_to_insert)
            conn.commit()
        finally:
            conn.close()
    return made


# ============================================================
#  ③ 分级课程体系 + 单元测验组卷
# ============================================================

def list_courses(language: str = "") -> List[dict]:
    """分级课程目录 (CEFR A1~C1, 日语注 JLPT / 韩语注 TOPIK)"""
    ensure_tables()
    seed_base_assets()
    conn = get_conn()
    try:
        if language in LANGS:
            rows = conn.execute(
                "SELECT * FROM mt_lang_courses WHERE language=? ORDER BY difficulty,order_no",
                (language,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_lang_courses ORDER BY language,difficulty,order_no").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_lesson_detail(lesson_code: str) -> Dict[str, Any]:
    """课时详情: 按类型装载词汇/语法/口语/听力内容 (沉浸式素材直出)"""
    ensure_tables()
    conn = get_conn()
    try:
        les = conn.execute("SELECT * FROM mt_lang_lessons WHERE lesson_code=?", (lesson_code,)).fetchone()
        if not les:
            return {"ok": False, "error": f"课时不存在: {lesson_code}"}
        les = dict(les)
        content = json.loads(les["content"] or "{}")
        payload: Dict[str, Any] = {"ok": True, **les, "materials": {}}
        if les["lesson_type"] == "vocab":
            ids = content.get("vocab_ids", [])
            if ids:
                marks = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT word_id,word,reading,meaning,example_sentence,example_translation,cefr,topic "
                    f"FROM mt_lang_vocab WHERE word_id IN ({marks})", ids).fetchall()
                payload["materials"]["vocab"] = [dict(r) for r in rows]
        elif les["lesson_type"] == "grammar":
            gids = [content.get("grammar_id")] + ([content["extra"]] if content.get("extra") else [])
            gids = [g for g in gids if g]
            for g in gids:
                r = conn.execute("SELECT * FROM mt_lang_grammar WHERE gp_id=?", (g,)).fetchone()
                if r:
                    d = dict(r)
                    d["examples"] = json.loads(d["examples"] or "[]")
                    payload["materials"].setdefault("grammar", []).append(d)
        elif les["lesson_type"] == "speaking":
            sids = content.get("speaking_ids", [])
            if sids:
                marks = ",".join("?" * len(sids))
                rows = conn.execute(
                    f"SELECT sp_id,sentence,translation,tips,cefr FROM mt_lang_speaking "
                    f"WHERE sp_id IN ({marks})", sids).fetchall()
                payload["materials"]["speaking"] = [dict(r) for r in rows]
        elif les["lesson_type"] == "listening":
            lid = content.get("listening_id")
            if lid:
                r = conn.execute("SELECT * FROM mt_lang_listening WHERE audio_id=?", (lid,)).fetchone()
                if r:
                    d = dict(r)
                    d["questions"] = json.loads(d["questions"] or "[]")
                    payload["materials"]["listening"] = d
        return payload
    finally:
        conn.close()


_BELT = {1: [(1, 0.5), (2, 0.5)], 2: [(2, 0.5), (3, 0.5)], 3: [(3, 0.5), (2, 0.25), (4, 0.25)],
         4: [(4, 0.5), (3, 0.25), (5, 0.25)], 5: [(5, 0.6), (4, 0.4)]}


def generate_unit_test(language: str = "en", cefr: str = "A1", title: str = "",
                       question_count: int = 6, topics: Optional[List[str]] = None) -> Dict[str, Any]:
    """单元测验组卷: 课程考点覆盖 + 难度带分布, 库存不足自动造题回填"""
    ensure_tables()
    language = language if language in LANGS else "en"
    level_no = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5}.get(cefr, 2)
    plan = _BELT.get(level_no, _BELT[2])
    need = [(d, max(1, round(question_count * r))) for d, r in plan]
    if not topics:
        conn = get_conn()
        try:
            topics = [r[0] for r in conn.execute(
                "SELECT DISTINCT topic FROM mt_lang_grammar WHERE language=? LIMIT 5", (language,))]
        finally:
            conn.close()
    topics = topics or ["时态", "助词", "活用"]

    conn = get_conn()
    picked: List[dict] = []
    try:
        for d, n in need:
            for t in topics:
                if len(picked) >= question_count:
                    break
                rows = conn.execute(
                    """SELECT qcode,question,q_type,topic,difficulty FROM mt_lang_qbank
                       WHERE language=? AND difficulty=? AND (topic=? OR knowledge_points LIKE ?)
                       LIMIT ?""", (language, d, t, f"%{t}%", n)).fetchall()
                got = {p["qcode"] for p in picked}
                for r in rows:
                    if r["qcode"] not in got and len(picked) < question_count:
                        picked.append(dict(r))
    finally:
        conn.close()
    shortage = question_count - len(picked)
    filled = []
    for i in range(shortage):
        d = need[i % len(need)][0]
        t = topics[i % len(topics)]
        batch = create_questions(topic=t, language=language, difficulty=d, count=1,
                                 q_type="语法选择" if d <= 2 else "翻译")
        if batch:
            filled.append(batch[0])
            picked.append({"qcode": batch[0]["qcode"], "question": batch[0]["question"],
                           "q_type": "语法选择" if d <= 2 else "翻译",
                           "topic": t, "difficulty": d})
    picked = picked[:question_count]
    if not picked:
        return {"ok": False, "error": "组卷失败: 无可用题目且自动造题失败"}

    raw = sum(p["difficulty"] * 20 for p in picked)
    for p in picked:
        p["score"] = round(p["difficulty"] * 20 * 100.0 / max(raw, 1), 1)
    coverage: Dict[str, int] = {}
    for p in picked:
        coverage[p.get("topic") or "综合"] = coverage.get(p.get("topic") or "综合", 0) + 1
    paper_code = _uid("LTEST")
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_lang_practice_results (username,language,paper_code,score,max_score,
               item_results,error_attribution,weak_points,graded_by)
               VALUES ('__paper__',?,?,0,100,'[]','[]','[]','仙女座命题组')""",
            (language, paper_code))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "paper_code": paper_code, "language": language, "cefr": cefr,
            "title": title or f"{LANGS[language]} {cefr} 单元测验",
            "question_count": len(picked), "topic_coverage": coverage,
            "auto_created": len(filled), "items": [
                {"qcode": p["qcode"], "topic": p.get("topic"), "q_type": p.get("q_type"),
                 "difficulty": p["difficulty"], "score": p["score"]} for p in picked]}


# ============================================================
#  ④ 互动学习四模块 (单词 SRS / 语法练习 / 口语跟读 / 听力训练)
# ============================================================

def review_vocab(username: str, word_id: str, result: str = "good") -> Dict[str, Any]:
    """单词记忆: SM-2 简化间隔重复 (答对间隔×ease, 答错重置为 1 天)"""
    ensure_tables()
    conn = get_conn()
    try:
        w = conn.execute("SELECT * FROM mt_lang_vocab WHERE word_id=?", (word_id,)).fetchone()
        if not w:
            return {"ok": False, "error": f"单词不存在: {word_id}"}
        row = conn.execute(
            "SELECT * FROM mt_lang_vocab_reviews WHERE username=? AND word_id=?",
            (username, word_id)).fetchone()
        if result == "good":
            if row:
                ease = min(3.0, (row["ease"] or 2.5) + 0.1)
                interval = max(1, round((row["interval_days"] or 1) * ease))
                reps = (row["repetitions"] or 0) + 1
            else:
                ease, interval, reps = 2.5, 1, 1
        else:
            ease = max(1.3, (row["ease"] if row else 2.5) - 0.2)
            interval, reps = 1, 0
        due = (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d")
        conn.execute(
            """INSERT INTO mt_lang_vocab_reviews (username,word_id,ease,interval_days,due_date,
               repetitions,last_result,updated_at) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(username,word_id) DO UPDATE SET ease=excluded.ease,
               interval_days=excluded.interval_days, due_date=excluded.due_date,
               repetitions=excluded.repetitions, last_result=excluded.last_result,
               updated_at=excluded.updated_at""",
            (username, word_id, ease, interval, due, reps, result, _now()))
        conn.execute(
            "INSERT INTO mt_lang_progress (username,language,lesson_code,action,score,detail) "
            "VALUES (?,?,?,?,?,?)",
            (username, w["language"], None, "vocab",
             1.0 if result == "good" else 0.0,
             json.dumps({"word_id": word_id, "word": w["word"], "result": result}, ensure_ascii=False)))
        _touch_streak(conn, username)
        _add_xp(conn, username, 2 if result == "good" else 1)
        got = _check_achievements(conn, username)
        conn.commit()
        due_n = conn.execute(
            "SELECT count(*) FROM mt_lang_vocab_reviews WHERE username=? AND due_date<=?",
            (username, _today())).fetchone()[0]
        _log(username, "VOCAB_REVIEW", {"word_id": word_id, "result": result, "interval": interval})
        return {"ok": True, "word_id": word_id, "word": w["word"], "meaning": w["meaning"],
                "next_interval_days": interval, "due_date": due, "repetitions": reps,
                "due_today": due_n, "new_achievements": got}
    finally:
        conn.close()


def due_vocab(username: str, language: str = "en", limit: int = 10) -> List[dict]:
    """到期单词队列 (SRS 复习): 到期优先, 不足补新词"""
    ensure_tables()
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT v.*, r.due_date, r.repetitions FROM mt_lang_vocab v
               LEFT JOIN mt_lang_vocab_reviews r ON r.word_id=v.word_id AND r.username=?
               WHERE v.language=? AND (r.due_date IS NULL OR r.due_date<=?)
               ORDER BY r.due_date IS NOT NULL DESC, r.due_date, v.cefr LIMIT ?""",
            (username, language, _today(), limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def grammar_practice(language: str = "en", topic: str = "", difficulty: int = 0,
                     count: int = 5) -> Dict[str, Any]:
    """语法练习出题: 题库抽取, 不足自动造题"""
    ensure_tables()
    language = language if language in LANGS else "en"
    conn = get_conn()
    try:
        sql = "SELECT qcode,question,q_type,topic,difficulty FROM mt_lang_qbank WHERE language=?"
        args: List[Any] = [language]
        if topic:
            sql += " AND (topic=? OR knowledge_points LIKE ?)"
            args += [topic, f"%{topic}%"]
        if difficulty:
            sql += " AND difficulty=?"
            args.append(difficulty)
        sql += " ORDER BY usage_count ASC, RANDOM() LIMIT ?"
        args.append(count)
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()
    if len(rows) < count:
        t = topic or (rows[0]["topic"] if rows and rows[0]["topic"] else "时态")
        d = difficulty or 2
        made = create_questions(topic=t, language=language, difficulty=d,
                                count=count - len(rows), q_type="语法选择")
        for m in made:
            rows.append({"qcode": m["qcode"], "question": m["question"],
                         "q_type": "语法选择", "topic": t, "difficulty": d})
    return {"ok": True, "language": language, "count": len(rows), "questions": rows[:count]}


def score_speaking(username: str, sp_id: str, said: str) -> Dict[str, Any]:
    """口语跟读: 本地相似度评分 (difflib, 零 token) + 发音要点 + XP 激励"""
    ensure_tables()
    conn = get_conn()
    try:
        sp = conn.execute("SELECT * FROM mt_lang_speaking WHERE sp_id=?", (sp_id,)).fetchone()
        if not sp:
            return {"ok": False, "error": f"口语句不存在: {sp_id}"}
        target = sp["sentence"]
    finally:
        conn.close()
    norm = lambda s: re.sub(r"[\s，。,.!?！？、~〜]+", "", (s or "")).lower()
    ratio = difflib.SequenceMatcher(None, norm(target), norm(said or "")).ratio()
    score = round(ratio * 100, 1)
    if score >= 90:
        feedback = "优秀! 语序与发音要素完整, 保持语速节奏。"
    elif score >= 70:
        feedback = "良好! 个别音节吞字或连读不到位, 再跟读 2 遍。"
    elif score >= 40:
        feedback = "有进步空间: 对照原句逐词确认漏读部分, 放慢速度跟读 3 遍。"
    else:
        feedback = "需要重来: 先听原句, 分小段模仿, 再整句跟读。"
    diff_ratio = difflib.SequenceMatcher(None, norm(target), norm(said or ""))
    hints = []
    for tag, i1, i2, j1, j2 in diff_ratio.get_opcodes():
        if tag in ("replace", "delete"):
            frag = target[i1:i2]
            if frag and len(frag) <= 30:
                hints.append(f"注意「{frag}」的读音与语序")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO mt_lang_progress (username,language,lesson_code,action,score,detail) "
            "VALUES (?,?,?,?,?,?)",
            (username, sp["language"], None, "speaking", score,
             json.dumps({"sp_id": sp_id, "similarity": ratio}, ensure_ascii=False)))
        _touch_streak(conn, username)
        _add_xp(conn, username, 8 if score >= 90 else (5 if score >= 70 else 2))
        got = _check_achievements(conn, username)
        conn.commit()
        _log(username, "SPEAKING", {"sp_id": sp_id, "score": score})
        return {"ok": True, "sp_id": sp_id, "target": target, "translation": sp["translation"],
                "score": score, "feedback": feedback,
                "focus_points": [sp["tips"]] if sp["tips"] else [],
                "pronunciation_hints": hints[:3], "xp_gained": 8 if score >= 90 else (5 if score >= 70 else 2),
                "new_achievements": got}
    finally:
        conn.close()


def listening_practice(username: str, audio_id: str, answers: Dict[str, str]) -> Dict[str, Any]:
    """听力训练: 遮罩原文判分 + 对照讲解 (先答后看 transcript)"""
    ensure_tables()
    conn = get_conn()
    try:
        item = conn.execute("SELECT * FROM mt_lang_listening WHERE audio_id=?", (audio_id,)).fetchone()
        if not item:
            return {"ok": False, "error": f"听力材料不存在: {audio_id}"}
        item = dict(item)
        qs = json.loads(item["questions"] or "[]")
    finally:
        conn.close()
    results, correct_n = [], 0
    for q in qs:
        gold = str(q.get("answer", "")).strip()
        got = str(answers.get(q.get("q", "")) or answers.get(str(qs.index(q))) or "").strip()
        ok = bool(got) and (got in gold or gold in got)
        correct_n += 1 if ok else 0
        results.append({"q": q.get("q"), "your_answer": got, "answer": gold, "correct": ok})
    score = round(correct_n * 100.0 / max(len(qs), 1), 1)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO mt_lang_progress (username,language,lesson_code,action,score,detail) "
            "VALUES (?,?,?,?,?,?)",
            (username, item["language"], None, "listening", score,
             json.dumps({"audio_id": audio_id, "correct": correct_n, "total": len(qs)},
                        ensure_ascii=False)))
        _touch_streak(conn, username)
        _add_xp(conn, username, 6 if score >= 80 else 3)
        got = _check_achievements(conn, username)
        conn.commit()
        _log(username, "LISTENING", {"audio_id": audio_id, "score": score})
        return {"ok": True, "audio_id": audio_id, "title": item["title"], "score": score,
                "results": results,
                "transcript": item["transcript"],        # 判分后揭示原文 (先答后看)
                "translation": item["translation"],
                "xp_gained": 6 if score >= 80 else 3, "new_achievements": got}
    finally:
        conn.close()


_ERROR_KINDS = ["词义混淆", "语法未掌握", "拼写/形态错误", "听力疏漏", "审题偏差"]


def grade_submission(paper_code: str, username: str, answers: Dict[str, str]) -> Dict[str, Any]:
    """④ 练习批改: 客观精确判分 + 五类错因归因 + 学情画像联动 + XP/成就"""
    ensure_tables()
    conn = get_conn()
    try:
        items = []
        for qcode, _a in (answers or {}).items():
            q = conn.execute("SELECT * FROM mt_lang_qbank WHERE qcode=?", (qcode,)).fetchone()
            if q:
                items.append(dict(q))
        if not items:
            return {"ok": False, "error": "未找到可批改的题目 (answers 需为 {qcode: 作答}"}
    finally:
        conn.close()
    results, attribution = [], {k: 0 for k in _ERROR_KINDS}
    topic_stats: Dict[str, Dict[str, int]] = {}
    total, max_total = 0.0, 0.0
    for q in items:
        ans = str(answers.get(q["qcode"]) or "").strip()
        gold = (q.get("answer") or q.get("solution") or "")
        max_s = float(q["difficulty"] * 20)
        max_total += max_s
        if q["q_type"] in ("语法选择", "单词题"):
            ok = bool(ans) and (ans == gold[:len(ans)] or ans in gold[:80])
            score = max_s if ok else 0.0
        else:
            kws = [w for w in re.findall(r"[\u4e00-\u9fa5A-Za-zぁ-んァ-ヶ가-힣]{2,8}",
                                         (q.get("knowledge_points") or "") + gold[:200])][:8]
            hit = sum(1 for k in kws if k and k.lower() in ans.lower()) if kws else 0
            ratio = hit / len(kws) if kws else (0.6 if ans else 0.0)
            score = round(max_s * min(1.0, ratio + 0.2 if ans else 0), 1)
            ok = score >= max_s * 0.6
        total += score
        t = q.get("topic") or "综合"
        st = topic_stats.setdefault(t, {"total": 0, "correct": 0})
        st["total"] += 1
        st["correct"] += 1 if ok else 0
        if not ok:
            if q["q_type"] == "听力理解":
                kind = "听力疏漏"
            elif q["q_type"] == "单词题":
                kind = "词义混淆"
            elif score > 0:
                kind = "拼写/形态错误"
            elif st["correct"] == 0:
                kind = "语法未掌握"
            else:
                kind = "审题偏差"
            attribution[kind] += 1
        results.append({"qcode": q["qcode"], "q_type": q["q_type"], "topic": t,
                        "difficulty": q["difficulty"], "score": score,
                        "max": max_s, "correct": ok})
    weak = [t for t, s in topic_stats.items() if s["correct"] * 2 < s["total"]]
    score = round(total, 1)
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_lang_practice_results (username,language,paper_code,score,max_score,
               item_results,error_attribution,weak_points,graded_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (username, items[0]["language"], paper_code or None, score, max_total or 100.0,
             json.dumps(results, ensure_ascii=False),
             json.dumps(attribution, ensure_ascii=False),
             json.dumps(weak, ensure_ascii=False), "仙女座语言批改组"))
        for r in results:
            conn.execute(
                "INSERT INTO mt_lang_progress (username,language,lesson_code,action,score,detail) "
                "VALUES (?,?,?,?,?,?)",
                (username, items[0]["language"], None, "grammar",
                 1.0 if r["correct"] else 0.0,
                 json.dumps({"qcode": r["qcode"], "topic": r["topic"], "score": r["score"]},
                            ensure_ascii=False)))
        _touch_streak(conn, username)
        _add_xp(conn, username, int(score / 20))
        got = _check_achievements(conn, username)
        conn.commit()
    finally:
        conn.close()
    _update_profile_from_results(username, items[0]["language"], results, weak)
    _log(username, "GRADE", {"paper_code": paper_code, "score": score, "weak": weak})
    return {"ok": True, "username": username, "score": score, "max": max_total or 100.0,
            "weak_points": weak, "error_attribution": attribution,
            "item_results": results, "new_achievements": got}


def _update_profile_from_results(username: str, language: str, results: List[dict],
                                 weak: List[str]):
    """批改 → 学情画像更新: 掌握度/正确率/趋势 (数据研究中心协同资产)"""
    conn = get_conn()
    try:
        correct = sum(1 for r in results if r["correct"])
        rate = correct / len(results) if results else 0.5
        prev = conn.execute(
            "SELECT mastery,correct_rate FROM mt_lang_learner_profiles WHERE username=? AND language=?",
            (username, language)).fetchone()
        mastery = {}
        if prev and prev["mastery"]:
            try:
                mastery = json.loads(prev["mastery"])
            except Exception:
                mastery = {}
        for r in results:
            t = r.get("topic") or "综合"
            old = mastery.get(t, 0.5)
            mastery[t] = round(old * 0.6 + (1.0 if r["correct"] else 0.0) * 0.4, 3)
        trend = round(rate - (prev["correct_rate"] if prev else 0.5), 3)
        conn.execute(
            """INSERT INTO mt_lang_learner_profiles (username,language,mastery,correct_rate,
               recent_trend,style,updated_at) VALUES (?,?,?,?,?,?,datetime('now','localtime'))
               ON CONFLICT(username,language) DO UPDATE SET mastery=excluded.mastery,
               correct_rate=excluded.correct_rate, recent_trend=excluded.recent_trend,
               updated_at=datetime('now','localtime')""",
            (username, language, json.dumps(mastery, ensure_ascii=False), round(rate, 3), trend, "步骤型"))
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  ⑤ 难度动态弹性调整 (ELO 式难度带)
# ============================================================

def _rate_to_band(rate: float) -> str:
    d = max(1, min(5, 1 + round(rate * 4)))
    return f"{max(1, d - 1)}-{min(5, d + 1)}"


def _level_of(rate: float) -> str:
    if rate >= 0.9:
        return "L5"
    if rate >= 0.75:
        return "L4"
    if rate >= 0.6:
        return "L3"
    if rate >= 0.4:
        return "L2"
    return "L1"


def adapt_difficulty(username: str, language: str = "en") -> Dict[str, Any]:
    """难度动态弹性调整: 正确率+趋势 → 难度带自动升降档, 事件留痕"""
    ensure_tables()
    conn = get_conn()
    try:
        prof = conn.execute(
            "SELECT * FROM mt_lang_learner_profiles WHERE username=? AND language=?",
            (username, language)).fetchone()
        if not prof:
            conn.execute(
                "INSERT OR IGNORE INTO mt_lang_learner_profiles (username,language,difficulty_band) "
                "VALUES (?,?,?)", (username, language, "2-4"))
            conn.commit()
            old_band, rate, trend = None, 0.5, 0.0
        else:
            old_band = prof["difficulty_band"]
            rate, trend = prof["correct_rate"], prof["recent_trend"]
    finally:
        conn.close()
    eff = max(0.0, min(1.0, rate + trend * 0.3))
    new_band = _rate_to_band(eff)
    level = _level_of(eff)
    trigger = "INIT" if old_band is None else ("RISE" if new_band > (old_band or "") else
                                               ("FALL" if new_band < (old_band or "") else "HOLD"))
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO mt_lang_learner_profiles (username,language,level,difficulty_band,updated_at)
               VALUES (?,?,?,?,datetime('now','localtime'))
               ON CONFLICT(username,language) DO UPDATE SET level=excluded.level,
               difficulty_band=excluded.difficulty_band, updated_at=datetime('now','localtime')""",
            (username, language, level, new_band))
        conn.execute(
            "INSERT INTO mt_lang_difficulty_events (username,language,old_band,new_band,trigger,correct_rate) "
            "VALUES (?,?,?,?,?,?)", (username, language, old_band, new_band, trigger, eff))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "username": username, "language": language, "level": level,
            "old_band": old_band, "new_band": new_band, "trigger": trigger,
            "effective_rate": round(eff, 3),
            "note": f"难度带弹性调整为 {new_band} (认知层级 {level}), 出题将按新带抽取"}


# ============================================================
#  ⑥ 个性化学习路径推荐 + 个性化讲解
# ============================================================

_LAYER_TPL = {
    "L1": ("零基础陪跑", "从假名/发音/基础词讲起, 每句配白话解释, 先看提示1再模仿"),
    "L2": ("基础巩固", "按句型模板带做, 卡住时看提示2, 重点记助词与词尾形态"),
    "L3": ("语感点拨", "只点关键形态变化, 自己完成造句, 对比例句找差距"),
    "L4": ("进阶挑战", "隐去提示, 尝试同义改写与自由表达, 关注地道搭配"),
    "L5": ("母语者拓展", "探究惯用表达与文化语境, 尝试影子跟读原速材料"),
}
_STYLE_ADDON = {
    "视觉型": "建议用词卡+思维导图, 把语法结构画成树状图。",
    "步骤型": "严格按句型公式套用, 每步写清助词/词尾依据。",
    "直觉型": "先大量输入整句培养语感, 再回头对照规则。",
    "严谨型": "整理变形表与例外清单, 逐条验证造句。",
}


def recommend_path(username: str, language: str = "en") -> Dict[str, Any]:
    """⑥ 个性化学习路径推荐: 学情画像 → 薄弱点前置 + 每日计划 + 补救练习"""
    ensure_tables()
    seed_base_assets()
    language = language if language in LANGS else "en"
    conn = get_conn()
    try:
        prof = conn.execute(
            "SELECT * FROM mt_lang_learner_profiles WHERE username=? AND language=?",
            (username, language)).fetchone()
        mastery = json.loads(prof["mastery"]) if prof and prof["mastery"] else {}
        level = prof["level"] if prof else "L3"
        band = prof["difficulty_band"] if prof else "2-4"
        done = {r[0] for r in conn.execute(
            "SELECT DISTINCT lesson_code FROM mt_lang_progress WHERE username=? AND lesson_code IS NOT NULL",
            (username,)).fetchall()}
        weak = [t for t, v in mastery.items() if v < 0.4]
        courses = conn.execute(
            "SELECT * FROM mt_lang_courses WHERE language=? ORDER BY difficulty", (language,)).fetchall()
    finally:
        conn.close()

    next_lessons = []
    for c in courses:
        conn = get_conn()
        try:
            les = conn.execute(
                "SELECT lesson_code,title,lesson_type,difficulty FROM mt_lang_lessons "
                "WHERE course_code=? ORDER BY id", (c["course_code"],)).fetchall()
        finally:
            conn.close()
        for l in les:
            if l["lesson_code"] not in done:
                next_lessons.append({"lesson_code": l["lesson_code"], "title": l["title"],
                                     "lesson_type": l["lesson_type"],
                                     "course": c["title"], "cefr": c["cefr"]})
            if len(next_lessons) >= 6:
                break
        if len(next_lessons) >= 6:
            break

    remedial_q = None
    if weak:
        made = create_questions(topic=weak[0], language=language, difficulty=2, count=1,
                                q_type="语法选择")
        if made:
            remedial_q = made[0]["qcode"]

    layer_name, layer_guide = _LAYER_TPL.get(level, _LAYER_TPL["L3"])
    daily = [
        {"slot": "10 分钟 · 单词复习", "how": f"review SRS 到期词 (目标 10 词), 当前难度带 {band}"},
        {"slot": "15 分钟 · 语法练习", "how": (f"优先薄弱点「{weak[0]}」" if weak else "按下一课时语法点") + "做 5 题"},
        {"slot": "10 分钟 · 口语跟读", "how": "跟读当日课时口语句, 相似度目标 ≥ 85"},
        {"slot": "10 分钟 · 听力训练", "how": "先盲听答题, 再对照 transcript 精听 2 遍"},
    ]
    plan = {
        "level": level, "layer": layer_name, "guide": layer_guide,
        "weak_points": weak, "difficulty_band": band,
        "next_lessons": next_lessons,
        "remedial_qcode": remedial_q,
        "daily_plan": daily,
        "style_tip": _STYLE_ADDON.get("步骤型", ""),
    }
    # LLM 增强鼓励语 (可选, 失败不影响)
    try:
        from ai_engines.ai_dual_route_engine import route_and_chat
        r = route_and_chat(
            f"学习者当前层级{level}({layer_name}), 薄弱点{weak or '暂无'}。"
            f"请给一句 50 字内的{LANGS[language]}学习鼓励+今日建议。",
            system="你是温暖的多语种学习教练。", kind="chat",
            flow_id=_FLOW, prefer_local=True)
        if r and r.get("success") and (r.get("response") or "").strip():
            plan["coach_message"] = r["response"].strip()[:150]
    except Exception:
        pass
    conn = get_conn()
    try:
        conn.execute("INSERT INTO mt_lang_paths (username,language,level,plan) VALUES (?,?,?,?)",
                     (username, language, level, json.dumps(plan, ensure_ascii=False)))
        _log(username, "PATH_RECOMMEND", {"language": language, "weak": weak})
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "username": username, "language": language, **plan}


def personalized_explain(qcode: str, username: str,
                         question: Optional[str] = None) -> Dict[str, Any]:
    """个性化解析讲解: 认知层级 + 风格定制 + 薄弱语法点前置补救"""
    ensure_tables()
    conn = get_conn()
    try:
        q = conn.execute("SELECT * FROM mt_lang_qbank WHERE qcode=?", (qcode,)).fetchone()
        prof = None
        if q:
            prof = conn.execute(
                "SELECT * FROM mt_lang_learner_profiles WHERE username=? AND language=?",
                (username, q["language"])).fetchone()
        if not q and question:
            conn.close()
            solved = solve_language_question(question)
            return {**solved, "tutoring": "已即时解析, 首次学习默认 L3 语感点拨模式"}
        mastery = json.loads(prof["mastery"]) if prof and prof["mastery"] else {}
        level = prof["level"] if prof else "L3"
        style = prof["style"] if prof else "步骤型"
        band = prof["difficulty_band"] if prof else "2-4"
        weak = [t for t, v in mastery.items() if v < 0.4]
    finally:
        conn.close()
    if not q:
        return {"ok": False, "error": f"题目不存在: {qcode}"}
    q = dict(q)
    layer_name, layer_guide = _LAYER_TPL.get(level, _LAYER_TPL["L3"])
    hints = json.loads(q["hints"] or "[]")
    parts = [
        f"【定制模式】{level} {layer_name} · {style}",
        f"【学情适配】当前难度带 {band}"
        + (f", 薄弱考点前置: {','.join(weak[:3])}" if weak else ""),
        f"【讲解策略】{layer_guide}",
        f"【本题解析】{(q['solution'] or '')[:1200]}",
        f"【题型解析】{q['analysis']}",
    ]
    if hints:
        parts.append("【分层提示】" + " | ".join(hints[:2 if level in ("L1", "L2") else 3]))
    parts.append("【风格适配】" + _STYLE_ADDON.get(style, ""))
    weak_q = None
    if weak and q.get("topic") in weak:
        made = create_questions(topic=q["topic"] or weak[0], language=q["language"],
                                difficulty=max(1, q["difficulty"] - 1), count=1, q_type="语法选择")
        if made:
            weak_q = made[0]["qcode"]
            parts.append(f"【补救练习】薄弱考点「{q['topic']}」已配变式题 {made[0]['qcode']}")
    tutoring = "\n".join(p for p in parts if p.strip())
    try:
        from ai_engines.ai_dual_route_engine import route_and_chat
        r = route_and_chat(
            f"学习者层级{level}({layer_name}), 风格{style}。请把以下解析改写成面向该生的"
            f"个性化讲解(150字内, 只输出讲解正文):\n{(q['solution'] or '')[:500]}",
            system=f"你是因材施教的{LANGS.get(q['language'], '')}特级教师。", kind="chat",
            flow_id=_FLOW, prefer_local=True)
        if r and r.get("success") and (r.get("response") or "").strip():
            tutoring += "\n【AI 教师定制语】" + r["response"].strip()[:300]
    except Exception:
        pass
    return {"ok": True, "qcode": qcode, "username": username, "level": level,
            "style": style, "tutoring": tutoring, "remedial_qcode": weak_q}


# ============================================================
#  学习闭环增量 (flow_lang_org_20261031 顾问/天团建议落地):
#  错词本导出 (天团) / 每日任务清单 (顾问) / 学习周报 (顾问)
# ============================================================

def export_mistake_words(username: str, language: str = "") -> Dict[str, Any]:
    """错词本导出: SRS 答错词 + 到期待复习词, 输出 JSON 与 CSV (一键带走)"""
    ensure_tables()
    conn = get_conn()
    try:
        sql = ("SELECT v.language,v.word_id,v.word,v.reading,v.meaning,v.example_sentence,"
               "v.example_translation,r.last_result,r.repetitions,r.due_date "
               "FROM mt_lang_vocab_reviews r JOIN mt_lang_vocab v ON v.word_id=r.word_id "
               "WHERE r.username=? AND (r.last_result='miss' OR r.due_date<=?)")
        args: List[Any] = [username, _today()]
        if language in LANGS:
            sql += " AND v.language=?"
            args.append(language)
        sql += " ORDER BY v.language, r.last_result='miss' DESC, r.due_date"
        rows = [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()
    csv_lines = ["language,word,reading,meaning,example,last_result,repetitions,due_date"]
    for r in rows:
        ex = (r.get("example_sentence") or "").replace(",", "，")
        csv_lines.append(f"{r['language']},{r['word']},{r['reading'] or ''},{r['meaning']},"
                         f"{ex},{r['last_result'] or ''},{r['repetitions']},{r['due_date']}")
    _log(username, "MISTAKE_EXPORT", {"count": len(rows)})
    return {"ok": True, "username": username, "count": len(rows),
            "words": rows, "csv": "\n".join(csv_lines)}


def daily_todo(username: str, language: str = "en") -> Dict[str, Any]:
    """每日任务清单: 四模块今日配额与完成度 (顾问建议落地)"""
    ensure_tables()
    language = language if language in LANGS else "en"
    quota = {"vocab": 10, "grammar": 5, "speaking": 3, "listening": 2}
    conn = get_conn()
    try:
        done = {}
        for act in quota:
            done[act] = conn.execute(
                "SELECT count(*) FROM mt_lang_progress WHERE username=? AND language=? "
                "AND action=? AND date(created_at)=date('now','localtime')",
                (username, language, act)).fetchone()[0]
        due_n = conn.execute(
            "SELECT count(*) FROM mt_lang_vocab_reviews WHERE username=? AND due_date<=?",
            (username, _today())).fetchone()[0]
    finally:
        conn.close()
    items = [
        {"task": "单词复习", "act": "vocab", "done": min(done["vocab"], quota["vocab"]),
         "quota": quota["vocab"], "tip": f"当前到期 {due_n} 词", "xp_each": 2},
        {"task": "语法练习", "act": "grammar", "done": min(done["grammar"], quota["grammar"]),
         "quota": quota["grammar"], "tip": "优先薄弱考点", "xp_each": 5},
        {"task": "口语跟读", "act": "speaking", "done": min(done["speaking"], quota["speaking"]),
         "quota": quota["speaking"], "tip": "相似度目标 ≥ 85", "xp_each": 8},
        {"task": "听力训练", "act": "listening", "done": min(done["listening"], quota["listening"]),
         "quota": quota["listening"], "tip": "先盲听再精听", "xp_each": 6},
    ]
    total_done = sum(i["done"] for i in items)
    total_quota = sum(i["quota"] for i in items)
    return {"ok": True, "username": username, "language": language,
            "date": _today(), "items": items,
            "percent": round(total_done * 100.0 / max(total_quota, 1)),
            "all_done": total_done >= total_quota,
            "encourage": ("今日任务全部完成, 连续打卡保持中!" if total_done >= total_quota
                          else f"还差 {total_quota - total_done} 项小任务, 冲一下!")}


def weekly_report(username: str) -> Dict[str, Any]:
    """学习周报: 近 7 天各模块练习量/得分趋势/打卡/XP (顾问建议落地)"""
    ensure_tables()
    conn = get_conn()
    try:
        by_day = {}
        for r in conn.execute(
                """SELECT date(created_at) d, action, count(*) c, avg(score) s
                   FROM mt_lang_progress WHERE username=?
                   AND created_at >= datetime('now','localtime','-7 day')
                   GROUP BY d, action ORDER BY d""", (username,)):
            by_day.setdefault(r["d"], {})[r["action"]] = {
                "count": r["c"], "avg_score": round(r["s"] or 0, 1)}
        u = conn.execute(
            "SELECT xp,level,streak_days FROM mt_lang_users WHERE username=?",
            (username,)).fetchone()
        week_total = conn.execute(
            "SELECT count(*) FROM mt_lang_progress WHERE username=? "
            "AND created_at >= datetime('now','localtime','-7 day')",
            (username,)).fetchone()[0]
        active_days = len(by_day)
    finally:
        conn.close()
    acts = {}
    for d, m in by_day.items():
        for a, v in m.items():
            t = acts.setdefault(a, {"count": 0, "scores": []})
            t["count"] += v["count"]
            t["scores"].append(v["avg_score"])
    module_summary = {a: {"count": t["count"],
                          "avg_score": round(sum(t["scores"]) / len(t["scores"]), 1)}
                      for a, t in acts.items()}
    report = {
        "week_practice_total": week_total, "active_days": active_days,
        "module_summary": module_summary,
        "xp": u["xp"] if u else 0, "level": u["level"] if u else 1,
        "streak_days": u["streak_days"] if u else 0,
        "comment": (f"本周练习 {week_total} 次、活跃 {active_days} 天"
                    + (f"，最勤模块: {max(module_summary, key=lambda a: module_summary[a]['count'])}"
                       if module_summary else "，下周从每日任务清单起步")),
    }
    _log(username, "WEEKLY_REPORT", {"week_total": week_total, "active_days": active_days})
    return {"ok": True, "username": username, "days": by_day, **report}


# ============================================================
#  进度追踪 / 社区 / 成就 / 总览
# ============================================================

def get_progress(username: str, language: str = "") -> Dict[str, Any]:
    """学习进度追踪: 课程完成度 / 模块练习统计 / 正确率 / 连续打卡 / XP 等级"""
    ensure_tables()
    conn = get_conn()
    try:
        u = conn.execute("SELECT username,xp,level,streak_days,target_languages FROM mt_lang_users "
                         "WHERE username=?", (username,)).fetchone()
        if not u:
            return {"ok": False, "error": f"用户不存在: {username}"}
        base = "SELECT language,action,count(*) c,avg(score) s FROM mt_lang_progress WHERE username=?"
        args: List[Any] = [username]
        if language in LANGS:
            base += " AND language=?"
            args.append(language)
        base += " GROUP BY language,action"
        module_stats = {}
        for r in conn.execute(base, args).fetchall():
            module_stats.setdefault(r["language"], {})[r["action"]] = {
                "count": r["c"], "avg_score": round(r["s"] or 0, 1)}
        lessons = []
        for r in conn.execute(
                "SELECT language,lesson_code,count(*) n,max(score) best,max(created_at) last_at "
                "FROM mt_lang_progress WHERE username=? AND lesson_code IS NOT NULL GROUP BY lesson_code",
                (username,)).fetchall():
            lessons.append(dict(r))
        courses_done = {}
        for l in lessons:
            row = conn.execute("SELECT course_code FROM mt_lang_lessons WHERE lesson_code=?",
                               (l["lesson_code"],)).fetchone()
            if row:
                courses_done.setdefault(row["course_code"], []).append(l["lesson_code"])
        course_progress = []
        for c in conn.execute("SELECT course_code,title,language,cefr,lesson_count FROM mt_lang_courses"
                              + (" WHERE language=?" if language in LANGS else ""),
                              ([language] if language in LANGS else [])).fetchall():
            done_n = len(courses_done.get(c["course_code"], []))
            course_progress.append({
                "course_code": c["course_code"], "title": c["title"], "language": c["language"],
                "cefr": c["cefr"], "done": done_n, "total": c["lesson_count"],
                "percent": round(done_n * 100.0 / max(c["lesson_count"], 1))})
        recent = [dict(r) for r in conn.execute(
            "SELECT language,action,score,created_at FROM mt_lang_progress WHERE username=? "
            "ORDER BY id DESC LIMIT 12", (username,))]
        return {"ok": True, "username": username, "xp": u["xp"], "level": u["level"],
                "streak_days": u["streak_days"], "target_languages": u["target_languages"],
                "module_stats": module_stats, "course_progress": course_progress,
                "recent_activity": recent}
    finally:
        conn.close()


def create_post(username: str, language: str, title: str, content: str) -> Dict[str, Any]:
    """社区交流: 发帖 + XP 激励 + 成就"""
    ensure_tables()
    if not title.strip() or not content.strip():
        return {"ok": False, "error": "title/content 不能为空"}
    conn = get_conn()
    try:
        pid = _uid("POST")
        conn.execute(
            "INSERT INTO mt_lang_posts (post_id,username,language,title,content) VALUES (?,?,?,?,?)",
            (pid, username, language if language in LANGS else "en", title.strip()[:120], content.strip()[:5000]))
        _add_xp(conn, username, 3)
        got = _check_achievements(conn, username)
        conn.commit()
        _log(username, "COMMUNITY_POST", {"post_id": pid, "title": title[:60]})
        return {"ok": True, "post_id": pid, "new_achievements": got}
    finally:
        conn.close()


def list_posts(language: str = "", limit: int = 20) -> List[dict]:
    ensure_tables()
    conn = get_conn()
    try:
        if language in LANGS:
            rows = conn.execute(
                "SELECT post_id,username,language,title,content,likes,comment_count,created_at "
                "FROM mt_lang_posts WHERE language=? ORDER BY id DESC LIMIT ?",
                (language, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT post_id,username,language,title,content,likes,comment_count,created_at "
                "FROM mt_lang_posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def comment_post(username: str, post_id: str, content: str) -> Dict[str, Any]:
    ensure_tables()
    if not content.strip():
        return {"ok": False, "error": "content 不能为空"}
    conn = get_conn()
    try:
        p = conn.execute("SELECT 1 FROM mt_lang_posts WHERE post_id=?", (post_id,)).fetchone()
        if not p:
            return {"ok": False, "error": f"帖子不存在: {post_id}"}
        conn.execute("INSERT INTO mt_lang_post_comments (post_id,username,content) VALUES (?,?,?)",
                     (post_id, username, content.strip()[:2000]))
        conn.execute("UPDATE mt_lang_posts SET comment_count=comment_count+1 WHERE post_id=?", (post_id,))
        _add_xp(conn, username, 1)
        conn.commit()
        _log(username, "COMMUNITY_COMMENT", {"post_id": post_id})
        return {"ok": True, "post_id": post_id}
    finally:
        conn.close()


def like_post(username: str, post_id: str) -> Dict[str, Any]:
    ensure_tables()
    conn = get_conn()
    try:
        p = conn.execute("SELECT 1 FROM mt_lang_posts WHERE post_id=?", (post_id,)).fetchone()
        if not p:
            return {"ok": False, "error": f"帖子不存在: {post_id}"}
        conn.execute("UPDATE mt_lang_posts SET likes=likes+1 WHERE post_id=?", (post_id,))
        conn.commit()
        _log(username, "COMMUNITY_LIKE", {"post_id": post_id})
        return {"ok": True, "post_id": post_id}
    finally:
        conn.close()


def list_achievements(username: str = "") -> Dict[str, Any]:
    """成就墙: 全量成就定义 + 用户已解锁"""
    ensure_tables()
    conn = get_conn()
    try:
        earned = {}
        if username:
            for r in conn.execute(
                    "SELECT ach_code,earned_at FROM mt_lang_user_achievements WHERE username=?",
                    (username,)).fetchall():
                earned[r["ach_code"]] = r["earned_at"]
        items = []
        for a in _ACHIEVEMENTS:
            items.append({**a, "earned": a["code"] in earned,
                          "earned_at": earned.get(a["code"])})
        return {"ok": True, "achievements": items,
                "earned_count": sum(1 for i in items if i["earned"])}
    finally:
        conn.close()


def platform_overview() -> Dict[str, Any]:
    ensure_tables()
    seed_base_assets()
    conn = get_conn()
    try:
        stats = {
            "users": conn.execute("SELECT count(*) FROM mt_lang_users").fetchone()[0],
            "courses": conn.execute("SELECT count(*) FROM mt_lang_courses").fetchone()[0],
            "lessons": conn.execute("SELECT count(*) FROM mt_lang_lessons").fetchone()[0],
            "vocab": conn.execute("SELECT count(*) FROM mt_lang_vocab").fetchone()[0],
            "grammar_points": conn.execute("SELECT count(*) FROM mt_lang_grammar").fetchone()[0],
            "listening": conn.execute("SELECT count(*) FROM mt_lang_listening").fetchone()[0],
            "speaking": conn.execute("SELECT count(*) FROM mt_lang_speaking").fetchone()[0],
            "qbank": conn.execute("SELECT count(*) FROM mt_lang_qbank").fetchone()[0],
            "practice_results": conn.execute(
                "SELECT count(*) FROM mt_lang_practice_results").fetchone()[0],
            "learner_profiles": conn.execute(
                "SELECT count(*) FROM mt_lang_learner_profiles").fetchone()[0],
            "posts": conn.execute("SELECT count(*) FROM mt_lang_posts").fetchone()[0],
            "lang_experts": conn.execute(
                "SELECT count(*) FROM eigenflux_experts WHERE domain='languages'").fetchone()[0],
        }
        by_lang = dict((r[0], r[1]) for r in conn.execute(
            "SELECT language,count(*) FROM mt_lang_qbank GROUP BY language"))
        recent_activity = [dict(r) for r in conn.execute(
            "SELECT username,action,created_at FROM mt_lang_activity_log "
            "ORDER BY id DESC LIMIT 8")]
        events = [dict(r) for r in conn.execute(
            "SELECT username,language,old_band,new_band,trigger,created_at "
            "FROM mt_lang_difficulty_events ORDER BY id DESC LIMIT 6")]
        experts = list_language_experts()[:8]
        return {"ok": True, "flow": _FLOW, "stats": stats, "qbank_by_language": by_lang,
                "recent_activity": recent_activity, "difficulty_events": events,
                "experts": experts, "db": DB_PATH}
    finally:
        conn.close()


# ============================================================
#  CLI
# ============================================================

def _cli_init():
    ensure_tables()
    seeded = seed_base_assets()
    print(f"[INIT] 种子资产: {json.dumps(seeded, ensure_ascii=False)}")
    try:
        hired = hire_language_experts(6, round_num=1)
        team = form_language_team(1)
        print(f"[INIT] 语言专家雇佣 {len(hired)} 名, 团队: {team.get('team_name') or team}")
        for h in hired:
            print(f"  - {h['name']} {h['role_cn']} ({h['level']}) perf={h['performance']}")
    except Exception as e:
        print(f"[INIT] ⚠️ EigenFlux 专家雇佣失败 (不影响核心功能): {e}")


def _cli_demo():
    ensure_tables()
    seed_base_assets()
    print("== 注册/登录 ==")
    uname = f"demo_{_uid('U')[-6:]}"
    reg = register_user(uname, "demo123456", "演示学员")
    print(json.dumps({k: v for k, v in reg.items() if k != "token"}, ensure_ascii=False))
    print("== ① 语言点解析 ==")
    r = solve_language_question("「て形」的语法点: ちょっと待って___ください, 助词怎么用? (日语听力对话中常见)", "ja")
    print(json.dumps({k: v for k, v in r.items() if k != "solution"}, ensure_ascii=False, indent=1))
    print("== ② 题目创造 ==")
    made = create_questions(topic="て形", language="ja", difficulty=2, count=2, q_type="语法选择")
    print(json.dumps(made, ensure_ascii=False, indent=1))
    print("== ③ 单元测验组卷 ==")
    paper = generate_unit_test(language="ja", cefr="A2", question_count=5)
    print(json.dumps({k: v for k, v in paper.items() if k != "items"}, ensure_ascii=False, indent=1))
    print("== 单词记忆 SRS ==")
    v = due_vocab(uname, "ja", limit=3)
    if v:
        print(json.dumps(review_vocab(uname, v[0]["word_id"], "good"), ensure_ascii=False, indent=1))
    print("== 口语跟读评分 ==")
    sp = conn_q = None
    conn_q = get_conn()
    try:
        row = conn_q.execute("SELECT sp_id FROM mt_lang_speaking WHERE language='ja' LIMIT 1").fetchone()
        sp = row["sp_id"] if row else None
    finally:
        conn_q.close()
    if sp:
        s = score_speaking(uname, sp, "はじめまして、どうぞよろしくお願いします")
        print(json.dumps({k: s[k] for k in ("score", "feedback")}, ensure_ascii=False))
    print("== 听力训练 ==")
    if paper.get("ok"):
        answers = {}
        for it in paper["items"]:
            answers[it["qcode"]] = f"模拟作答 {it['topic']}"
        g = grade_submission(paper["paper_code"], uname, answers)
        print(json.dumps({k: g[k] for k in ("score", "weak_points", "error_attribution")},
                         ensure_ascii=False, indent=1))
        print("== ⑤ 难度弹性调整 ==")
        print(json.dumps(adapt_difficulty(uname, "ja"), ensure_ascii=False, indent=1))
    print("== ⑥ 个性化路径推荐 ==")
    p = recommend_path(uname, "ja")
    print(json.dumps({k: p[k] for k in ("level", "layer", "weak_points", "next_lessons", "daily_plan")[:4]},
                     ensure_ascii=False, indent=1)[:800])
    print("== 社区 + 成就 ==")
    post = create_post(uname, "ja", "五十音记忆心得", "片假名联动英语外来词记忆最快, 分享给大家!")
    print(json.dumps(post, ensure_ascii=False))
    ach = list_achievements(uname)
    print(json.dumps({k: ach[k] for k in ("earned_count",)}, ensure_ascii=False),
          "已解锁:", [a["name"] for a in ach["achievements"] if a["earned"]])
    print("== 总览 ==")
    print(json.dumps(platform_overview()["stats"], ensure_ascii=False, indent=1))


def _cli_status():
    print(json.dumps(platform_overview(), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "init":
        _cli_init()
    elif cmd == "hire":
        for h in hire_language_experts(int(sys.argv[2]) if len(sys.argv) > 2 else 3, 1):
            print(f"hired {h['name']} {h['role_cn']}")
    elif cmd == "demo":
        _cli_demo()
    elif cmd == "status":
        _cli_status()
    else:
        print("usage: ai_language_pedagogy_engine.py init|hire [n]|demo|status")
