#!/usr/bin/env python3
"""
🌐 translation_studio — 四国翻译系统 (v26.0)
============================================
copy_studio 配套子能力. 文案创作 → 翻译 → 四国语言发布.
同时支持独立翻译: 直接上传任意文本翻译.

复用 copy_studio 双后端 + db_retry + 短连接 + busy_timeout 模式.
"""
from __future__ import annotations
import os, re, uuid, datetime, json, time, functools, sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

# ═══════════════════════════════════════════════════════════
# 四国语言定义
# ═══════════════════════════════════════════════════════════
LANG_ZH = 'zh'
LANG_EN = 'en'
LANG_JA = 'ja'
LANG_TW = 'zh_tw'   # 繁体中文

LANG_LABELS = {
    'zh':    {'label': '🇨🇳 简体中文', 'native': '简体中文', 'flag': '\U0001F1E8\U0001F1F3', 'flag_code': 'CN'},
    'en':    {'label': '🇺🇸 English',  'native': 'English',  'flag': '\U0001F1FA\U0001F1F8', 'flag_code': 'US'},
    'ja':    {'label': '🇯🇵 日本語',   'native': '日本語',    'flag': '\U0001F1EF\U0001F1F5', 'flag_code': 'JP'},
    'zh_tw': {'label': '🇹🇼 繁體中文', 'native': '繁體中文',  'flag': '\U0001F1F9\U0001F1FC', 'flag_code': 'TW'},
}
# \U0001F1F9\U0001F1FC = 🇹🇼 (台湾地区旗, 显式 codepoint, 避免 emoji 序列渲染问题)

FOUR_LANGS = ['zh', 'en', 'ja', 'zh_tw']

# 翻译方向: 所有源语言可译到所有目标语言 (除了同语言)
def valid_direction(src: str, tgt: str) -> bool:
    return src in FOUR_LANGS and tgt in FOUR_LANGS and src != tgt

# 行业术语表 (自动加载 + 可扩展)
DEFAULT_GLOSSARY: Dict[str, Dict[str, str]] = {
    'zh→en':     {'仙女座': 'Andromeda', '冰山': 'Iceberg', '文案中台': 'Copy Studio',
                  '星舰': 'Starship', '天团': 'Dream Team', 'EigenFlux': 'EigenFlux',
                  '文案创作': 'Copywriting', '翻译系统': 'Translation System', '四国': 'Four Nations'},
    'en→zh':     {'Andromeda': '仙女座', 'Iceberg': '冰山', 'Copy Studio': '文案中台',
                  'Starship': '星舰', 'Dream Team': '天团', 'EigenFlux': 'EigenFlux',
                  'Copywriting': '文案创作', 'Translation System': '翻译系统'},
    'zh→ja':     {'仙女座': 'アンドロメダ', '冰山': '氷山', '文案中台': 'コピースタジオ',
                  '星舰': 'スターシップ', '天团': 'ドリームチーム', 'EigenFlux': 'EigenFlux'},
    'ja→zh':     {'アンドロメダ': '仙女座', '氷山': '冰山', 'コピースタジオ': '文案中台',
                  'スターシップ': '星舰', 'ドリームチーム': '天团', 'EigenFlux': 'EigenFlux'},
    'zh→zh_tw':  {'仙女座': '仙女座', '冰山': '冰山', '文案中台': '文案中台',
                  '星舰': '星艦', '天团': '天團', 'EigenFlux': 'EigenFlux',
                  '文案创作': '文案創作', '翻译系统': '翻譯系統', '数据库': '資料庫',
                  '人工智能': '人工智慧', '服务器': '伺服器', '组件': '元件'},
    'zh_tw→zh':  {'仙女座': '仙女座', '冰山': '冰山', '文案中台': '文案中台',
                  '星艦': '星舰', '天團': '天团', 'EigenFlux': 'EigenFlux',
                  '文案創作': '文案创作', '翻譯系統': '翻译系统', '資料庫': '数据库',
                  '人工智慧': '人工智能', '伺服器': '服务器', '元件': '组件'},
}

# 翻译质量等级
QUALITY_STANDARD = 'standard'   # 标准 (Ollama 直接翻)
QUALITY_PREMIUM = 'premium'     # 精品 (Ollama + 术语表 + 回译校验)


# ═══════════════════════════════════════════════════════════
# DB 路径探测 (对齐 copy_studio/approval 模式)
# ═══════════════════════════════════════════════════════════
def _find_db() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / 'database' / 'app.db',
        Path(__file__).resolve().parent.parent / 'database' / 'app.db',
    ]
    for c in candidates:
        if c.exists(): return c
    return candidates[0]

DB_PATH = _find_db()
os.makedirs(DB_PATH.parent, exist_ok=True)

NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def db_retry(max_retries: int = 3, backoff: float = 0.5):
    """SQLite busy_timeout + 锁冲突重试."""
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    if 'locked' in msg or 'busy' in msg:
                        if attempt < max_retries - 1:
                            time.sleep(backoff * (attempt + 1)); continue
                    raise
            return None
        return wrapper
    return decorator


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════
# 幂等迁移 (6 张表 + 索引)
# ═══════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_trans_tasks (
  task_id TEXT PRIMARY KEY,
  source_lang TEXT NOT NULL,
  target_lang TEXT NOT NULL,
  source_text TEXT,
  source_project_id TEXT,
  target_text TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  quality TEXT DEFAULT 'standard',
  glossary_json TEXT,
  quality_score REAL,
  error_msg TEXT,
  initiator TEXT DEFAULT 'wuchenghao15',
  created_at TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_trans_segments (
  seg_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  seg_no INTEGER,
  source_segment TEXT,
  target_segment TEXT,
  token_count INTEGER,
  quality_score REAL,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_trans_glossary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_lang TEXT NOT NULL,
  tgt_lang TEXT NOT NULL,
  source_term TEXT NOT NULL,
  target_term TEXT NOT NULL,
  domain TEXT DEFAULT 'general',
  created_at TEXT,
  UNIQUE(src_lang, tgt_lang, source_term)
);

CREATE TABLE IF NOT EXISTS mt_trans_quality_log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  check_type TEXT,
  original TEXT,
  translated TEXT,
  issue TEXT,
  suggestion TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_trans_review (
  review_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  reviewer TEXT,
  status TEXT DEFAULT 'pending',
  score REAL,
  review_note TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_trans_cache (
  cache_key TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,
  source_lang TEXT NOT NULL,
  target_lang TEXT NOT NULL,
  target_text TEXT NOT NULL,
  token_count INTEGER,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_trans_tasks_status ON mt_trans_tasks(status);
CREATE INDEX IF NOT EXISTS idx_trans_tasks_lang ON mt_trans_tasks(source_lang, target_lang);
CREATE INDEX IF NOT EXISTS idx_trans_segments_task ON mt_trans_segments(task_id);
CREATE INDEX IF NOT EXISTS idx_trans_glossary_langs ON mt_trans_glossary(src_lang, tgt_lang);
CREATE INDEX IF NOT EXISTS idx_trans_cache_hash ON mt_trans_cache(source_hash, source_lang, target_lang);
"""


def ensure_schema(db_path: Optional[str | Path] = None) -> None:
    p = str(Path(db_path) if db_path else DB_PATH)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    # 预置默认术语表
    for direction, pairs in DEFAULT_GLOSSARY.items():
        src, tgt = direction.split('→')
        for st, tt in pairs.items():
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO mt_trans_glossary
                    (src_lang, tgt_lang, source_term, target_term, domain, created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (src, tgt, st, tt, 'mtscos', NOW_F()))
            except Exception: pass
    conn.commit()
    conn.close()
