#!/usr/bin/env python3
"""
📝 copy_studio 文案创作引擎 — db 层 (v26.0)
==========================================
对齐 approval/db.py 模式: 短连接 + busy_timeout + @db_retry + BEGIN IMMEDIATE
6 表幂等迁移: mt_copy_projects / chapters / characters / scenes / consistency_log / rag_inject_log
"""
from __future__ import annotations
import sqlite3, threading, time, os, functools, datetime
from pathlib import Path
from typing import Optional, Iterator
from . import DB_PATH

# ═══════════════════════════════════════════════════════════
# 迁移锁 (同进程内保证 ensure_schema 只跑一次)
# ═══════════════════════════════════════════════════════════
_LOCK = threading.Lock()
_MIGRATED: set[str] = set()
NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def db_retry(max_retries: int = 3, backoff: float = 0.5):
    """SQLite busy_timeout + 锁冲突重试 (只对 locked 错重试, 其他直接抛)"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    if 'locked' in msg or 'busy' in msg:
                        if attempt < max_retries - 1:
                            time.sleep(backoff * (attempt + 1))
                            continue
                    raise
            return None
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════
# 短连接工厂
# ═══════════════════════════════════════════════════════════
def get_conn(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """短连接 (with get_conn() as conn: ...). 自动 busy_timeout=30s."""
    p = str(Path(db_path) if db_path else DB_PATH)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════
# 幂等迁移 (6 表 + 索引)
# ═══════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_copy_projects (
  project_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  genre TEXT NOT NULL DEFAULT 'novel',
  sub_genre TEXT,
  target_words INTEGER DEFAULT 50000,
  current_words INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  initiator TEXT NOT NULL,
  initiator_role TEXT DEFAULT '',
  risk_level TEXT DEFAULT 'medium',
  approval_id TEXT,
  outline_json TEXT,
  style_guide_json TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_copy_chapters (
  chapter_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  chapter_no INTEGER NOT NULL DEFAULT 1,
  title TEXT,
  chapter_type TEXT NOT NULL DEFAULT 'chapter',
  target_words INTEGER DEFAULT 3000,
  actual_words INTEGER DEFAULT 0,
  content TEXT,
  summary TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  ai_worker_role TEXT,
  polish_count INTEGER DEFAULT 0,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY (project_id) REFERENCES mt_copy_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_copy_characters (
  character_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  role_type TEXT DEFAULT 'supporting',
  personality TEXT,
  appearance TEXT,
  backstory TEXT,
  goals TEXT,
  conflicts TEXT,
  relationships_json TEXT,
  tags_json TEXT,
  created_at TEXT,
  FOREIGN KEY (project_id) REFERENCES mt_copy_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_copy_scenes (
  scene_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  scene_no INTEGER NOT NULL DEFAULT 1,
  location TEXT,
  time_day TEXT,
  characters_present TEXT,
  action_desc TEXT,
  dialogue TEXT,
  notes TEXT,
  duration_sec INTEGER DEFAULT 30,
  created_at TEXT,
  FOREIGN KEY (project_id) REFERENCES mt_copy_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_copy_consistency_log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  chapter_id TEXT,
  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  description TEXT,
  suggestion TEXT,
  auto_fix_status TEXT DEFAULT 'pending',
  fixed_content TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY (project_id) REFERENCES mt_copy_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_copy_rag_inject_log (
  inject_id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  chapter_id TEXT,
  inject_type TEXT NOT NULL,
  inject_content TEXT,
  tokens_estimate INTEGER DEFAULT 0,
  created_at TEXT,
  FOREIGN KEY (project_id) REFERENCES mt_copy_projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_copy_chapters_project ON mt_copy_chapters(project_id);
CREATE INDEX IF NOT EXISTS idx_copy_chapters_no ON mt_copy_chapters(project_id, chapter_no);
CREATE INDEX IF NOT EXISTS idx_copy_characters_project ON mt_copy_characters(project_id);
CREATE INDEX IF NOT EXISTS idx_copy_scenes_project ON mt_copy_scenes(project_id);
CREATE INDEX IF NOT EXISTS idx_copy_consistency_project ON mt_copy_consistency_log(project_id);
CREATE INDEX IF NOT EXISTS idx_copy_rag_project ON mt_copy_rag_inject_log(project_id);
CREATE INDEX IF NOT EXISTS idx_copy_projects_init ON mt_copy_projects(initiator, status);

-- v26.0 P3 daemon 日志表 (统一由 ensure_schema 管理, 避免 daemon 分散 CREATE)
CREATE TABLE IF NOT EXISTS mt_copy_chapter_versions (
  version_id TEXT PRIMARY KEY,
  chapter_id TEXT NOT NULL,
  version_no INTEGER NOT NULL DEFAULT 1,
  content TEXT,
  actual_words INTEGER DEFAULT 0,
  trigger_type TEXT NOT NULL DEFAULT 'auto',  -- auto_write / polish / manual_restore / manual_edit
  ai_worker_role TEXT,
  note TEXT,
  created_at TEXT,
  FOREIGN KEY (chapter_id) REFERENCES mt_copy_chapters(chapter_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_copy_versions_chapter ON mt_copy_chapter_versions(chapter_id, version_no);

-- v26.0 Step4: Embedding RAG 向量块表
CREATE TABLE IF NOT EXISTS mt_copy_chunks (
  chunk_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  chapter_id TEXT NOT NULL,
  chunk_idx INTEGER NOT NULL DEFAULT 0,
  chunk_text TEXT,
  embedding_json TEXT,          -- JSON array of float, nomic-embed-text = 768-dim
  embed_model TEXT DEFAULT '',  -- nomic-embed-text / fastembed_tfidf_fallback
  tokens_estimate INTEGER DEFAULT 0,
  created_at TEXT,
  FOREIGN KEY (project_id) REFERENCES mt_copy_projects(project_id) ON DELETE CASCADE,
  FOREIGN KEY (chapter_id) REFERENCES mt_copy_chapters(chapter_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_copy_chunks_project ON mt_copy_chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_copy_chunks_chapter ON mt_copy_chunks(chapter_id, chunk_idx);

CREATE TABLE IF NOT EXISTS mt_copy_learning_log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  patterns_json TEXT,
  feedback_json TEXT,
  suggestions_json TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_copy_expansion_log (
  log_id TEXT PRIMARY KEY,
  trigger_type TEXT,
  details_json TEXT,
  parliament_proposal_id TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS mt_parliament_proposals (
  proposal_id TEXT PRIMARY KEY,
  title TEXT,
  content TEXT,
  author TEXT DEFAULT 'sys_copy_expander',
  status TEXT DEFAULT 'pending_vote',
  votes_for INTEGER DEFAULT 0,
  votes_against INTEGER DEFAULT 0,
  created_at TEXT
);
"""


def _existing_columns(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


@db_retry()
def ensure_schema(db_path: Optional[Path | str] = None) -> None:
    """幂等迁移. 每次都跑 CREATE TABLE IF NOT EXISTS (天然幂等) + 已知 ALTER."""
    path = str(Path(db_path) if db_path else DB_PATH)
    with _LOCK:
        with get_conn(path) as conn:
            conn.executescript(SCHEMA)
            # v26.0 Step5: mt_copy_consistency_log.suggestion (老库无此列时 ALTER)
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_copy_consistency_log)").fetchall()]
                for col in ('suggestion', 'updated_at'):
                    if col not in cols:
                        conn.execute(f"ALTER TABLE mt_copy_consistency_log ADD COLUMN {col} TEXT")
            except Exception:
                pass
        _MIGRATED.add(path)


# ═══════════════════════════════════════════════════════════
# CLI (调试用)
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse, json
    ap = argparse.ArgumentParser(description="📝 copy_studio DB")
    ap.add_argument('--migrate', action='store_true', help='执行幂等迁移')
    ap.add_argument('--stats', action='store_true', help='统计表行数')
    args = ap.parse_args()

    if args.migrate:
        ensure_schema()
        ensure_schema()  # 幂等二次
        print(f"✅ ensure_schema OK ({DB_PATH})")
    elif args.stats:
        ensure_schema()
        with get_conn() as c:
            for t in ['mt_copy_projects', 'mt_copy_chapters', 'mt_copy_characters',
                      'mt_copy_scenes', 'mt_copy_consistency_log', 'mt_copy_rag_inject_log']:
                try:
                    n = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                    print(f"  {t:35s} = {n}")
                except Exception as e:
                    print(f"  {t:35s} ❌ {e}")
    else:
        ap.print_help()
