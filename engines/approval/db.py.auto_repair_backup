"""
db.py — 审批中台短连接与幂等 schema 迁移
=========================================
OneDrive 大库 (database/app.db, 2.6GB WAL) 多守护并发, 历史教训:
实例级长连接是 database is locked 的主要来源之一。故:
  - 所有业务方法用 get_conn() 短连接, 方法结束即关;
  - 写事务一律 BEGIN IMMEDIATE (直接拿 RESERVED 锁, 避免 DEFERRED 升级死锁);
  - @db_retry 仅对 locked 类 OperationalError 指数退避重试。

注意: 显式锁定 flask-app/database/app.db, 不走 core.db_path.patch_sqlite3_connect
(那会把连接解析到 _runtime 影子库), 审批 SSOT 不允许漂移。
"""
from __future__ import annotations

import functools
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_CANDIDATES = [
    _PROJECT_ROOT / "database" / "app.db",
    _PROJECT_ROOT / "app.db",
]
DB_PATH = next((p for p in _DB_CANDIDATES if p.exists()), _DB_CANDIDATES[0])

_LOCK = threading.Lock()
_MIGRATED: set[str] = set()


# ════════════════════════════════════════════════════════════════════
# Schema — 老三表带全列 (全新库一次到位), 主库靠 ALTER 增量补缺
# ════════════════════════════════════════════════════════════════════
SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS mt_approval_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT UNIQUE,
    category        TEXT NOT NULL,
    subject_id      TEXT,
    subject_snapshot TEXT,
    initiator       TEXT NOT NULL,
    initiator_role  TEXT,
    risk_level      TEXT DEFAULT 'medium',
    auto_passed     INTEGER DEFAULT 0,
    current_node    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'pending',
    final_decision  TEXT,
    decided_by      TEXT,
    decided_at      TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    title           TEXT DEFAULT '',
    mode            TEXT DEFAULT 'single',
    priority        TEXT DEFAULT 'normal',
    cc_json         TEXT DEFAULT '[]',
    due_at          TEXT,
    remind_count    INTEGER DEFAULT 0,
    escalate_count  INTEGER DEFAULT 0,
    delegate_chain_json TEXT DEFAULT '[]',
    llm_review_json TEXT DEFAULT '',
    callback_key    TEXT DEFAULT '',
    callback_status TEXT DEFAULT 'none',
    callback_attempts INTEGER DEFAULT 0,
    withdraw_reason TEXT DEFAULT '',
    withdrawn_by    TEXT DEFAULT '',
    withdrawn_at    TEXT,
    expired_at      TEXT,
    flow_id         TEXT DEFAULT '',
    schema_v2       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mt_approval_nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    node_index      INTEGER NOT NULL,
    node_type       TEXT NOT NULL,
    approver_role   TEXT,
    auto_pass       INTEGER DEFAULT 0,
    approver_name   TEXT,
    action          TEXT,
    notes           TEXT,
    decided_at      TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    status          TEXT DEFAULT 'pending',
    mode            TEXT DEFAULT 'single',
    quorum          INTEGER DEFAULT 1,
    approvers_json  TEXT DEFAULT '[]',
    approved_by_json TEXT DEFAULT '[]',
    rejected_by     TEXT DEFAULT '',
    activated_at    TEXT,
    due_at          TEXT,
    remind_count    INTEGER DEFAULT 0,
    escalate_level  INTEGER DEFAULT 0,
    delegated_to    TEXT DEFAULT '',
    delegate_reason TEXT DEFAULT '',
    vikey_required  INTEGER DEFAULT 0,
    llm_verdict     TEXT DEFAULT '',
    llm_detail_json TEXT DEFAULT '',
    llm_retries     INTEGER DEFAULT 0,
    backfill_flag   INTEGER DEFAULT 0,
    FOREIGN KEY(request_id) REFERENCES mt_approval_requests(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_approval_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    node_index      INTEGER,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    actor_role      TEXT,
    notes           TEXT,
    acted_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    detail_json     TEXT DEFAULT '',
    vikey_verified  INTEGER DEFAULT 0,
    FOREIGN KEY(request_id) REFERENCES mt_approval_requests(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_appr_req_status ON mt_approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_appr_req_init   ON mt_approval_requests(initiator);
CREATE INDEX IF NOT EXISTS idx_appr_req_cat    ON mt_approval_requests(category);
CREATE INDEX IF NOT EXISTS idx_appr_nodes_req  ON mt_approval_nodes(request_id);
CREATE INDEX IF NOT EXISTS idx_nodes_req_status ON mt_approval_nodes(request_id, status);
CREATE INDEX IF NOT EXISTS idx_nodes_todo ON mt_approval_nodes(approver_role, status);
CREATE INDEX IF NOT EXISTS idx_req_due ON mt_approval_requests(status, due_at);
CREATE INDEX IF NOT EXISTS idx_req_callback ON mt_approval_requests(callback_status);
"""

SCHEMA_NEW_TABLES = """
CREATE TABLE IF NOT EXISTS mt_approval_delegations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    delegator       TEXT NOT NULL,
    delegatee       TEXT NOT NULL,
    scope_categories TEXT DEFAULT '["*"]',
    scope_roles     TEXT DEFAULT '["*"]',
    start_at        TEXT,
    end_at          TEXT,
    enabled         INTEGER DEFAULT 1,
    note            TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_deleg_unique
    ON mt_approval_delegations(delegator, delegatee, start_at);

CREATE TABLE IF NOT EXISTS mt_approval_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    node_index      INTEGER,
    kind            TEXT NOT NULL,
    from_target     TEXT,
    to_target       TEXT,
    channel         TEXT DEFAULT 'notify',
    note            TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rem_req_node_kind
    ON mt_approval_reminders(request_id, node_index, kind);
CREATE INDEX IF NOT EXISTS idx_rem_kind_time
    ON mt_approval_reminders(kind, created_at);

CREATE TABLE IF NOT EXISTS mt_approval_callback_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL,
    callback_key    TEXT DEFAULT '',
    event           TEXT DEFAULT '',
    status          TEXT DEFAULT '',
    response        TEXT DEFAULT '',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cblog_req ON mt_approval_callback_log(request_id);
"""

# 主库存量老表需要增量补齐的列 (表 -> [(列, 类型DEFAULT)])
_ADD_COLUMNS = {
    'mt_approval_requests': [
        ('title', "TEXT DEFAULT ''"),
        ('mode', "TEXT DEFAULT 'single'"),
        ('priority', "TEXT DEFAULT 'normal'"),
        ('cc_json', "TEXT DEFAULT '[]'"),
        ('due_at', 'TEXT'),
        ('remind_count', 'INTEGER DEFAULT 0'),
        ('escalate_count', 'INTEGER DEFAULT 0'),
        ('delegate_chain_json', "TEXT DEFAULT '[]'"),
        ('llm_review_json', "TEXT DEFAULT ''"),
        ('callback_key', "TEXT DEFAULT ''"),
        ('callback_status', "TEXT DEFAULT 'none'"),
        ('callback_attempts', 'INTEGER DEFAULT 0'),
        ('withdraw_reason', "TEXT DEFAULT ''"),
        ('withdrawn_by', "TEXT DEFAULT ''"),
        ('withdrawn_at', 'TEXT'),
        ('expired_at', 'TEXT'),
        ('flow_id', "TEXT DEFAULT ''"),
        ('schema_v2', 'INTEGER DEFAULT 0'),
    ],
    'mt_approval_nodes': [
        ('status', "TEXT DEFAULT 'pending'"),
        ('mode', "TEXT DEFAULT 'single'"),
        ('quorum', 'INTEGER DEFAULT 1'),
        ('approvers_json', "TEXT DEFAULT '[]'"),
        ('approved_by_json', "TEXT DEFAULT '[]'"),
        ('rejected_by', "TEXT DEFAULT ''"),
        ('activated_at', 'TEXT'),
        ('due_at', 'TEXT'),
        ('remind_count', 'INTEGER DEFAULT 0'),
        ('escalate_level', 'INTEGER DEFAULT 0'),
        ('delegated_to', "TEXT DEFAULT ''"),
        ('delegate_reason', "TEXT DEFAULT ''"),
        ('vikey_required', 'INTEGER DEFAULT 0'),
        ('llm_verdict', "TEXT DEFAULT ''"),
        ('llm_detail_json', "TEXT DEFAULT ''"),
        ('llm_retries', 'INTEGER DEFAULT 0'),
        ('backfill_flag', 'INTEGER DEFAULT 0'),
    ],
    'mt_approval_actions': [
        ('detail_json', "TEXT DEFAULT ''"),
        ('vikey_verified', 'INTEGER DEFAULT 0'),
    ],
}


@contextmanager
def get_conn(db_path: Path | str | None = None):
    """短连接上下文。with get_conn() as conn: ... 正常退出 commit, 异常 rollback。"""
    path = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)  # autocommit, 手动 BEGIN
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def db_retry(times: int = 3, base: float = 0.2):
    """仅对 database is locked 类错误指数退避重试。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for i in range(times):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    last = e
                    if 'locked' not in str(e).lower() and 'busy' not in str(e).lower():
                        raise
                    time.sleep(base * (2 ** i))
            raise last
        return wrapper
    return deco


def _existing_columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


@db_retry()
def ensure_schema(db_path: Path | str | None = None) -> None:
    """幂等迁移: 建三新表/索引 + 老表增量 ADD COLUMN. 每库进程内只跑一次.
    不管表存不存在都先跑 executescript (CREATE TABLE IF NOT EXISTS 天然幂等),
    再补缺失列和存量数据.
    """
    path = str(Path(db_path) if db_path else DB_PATH)
    with _LOCK:
        with get_conn(path) as conn:
            # 1. 全量建表 (CREATE TABLE IF NOT EXISTS 天然幂等, 不影响已有表结构)
            conn.executescript(SCHEMA_BASE)
            conn.executescript(SCHEMA_NEW_TABLES)
            # 2. 增量补列 (老库三表可能缺新列)
            conn.execute("BEGIN IMMEDIATE")
            for table, cols in _ADD_COLUMNS.items():
                have = _existing_columns(conn, table)
                for name, decl in cols:
                    if name not in have:
                        try:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                        except sqlite3.OperationalError:
                            pass
            # 3. 存量: action 有值者同步 status
            conn.execute(
                "UPDATE mt_approval_nodes SET status='approved' "
                "WHERE action='approve' AND (status IS NULL OR status='pending' OR status='')")
            conn.execute(
                "UPDATE mt_approval_nodes SET status='rejected' "
                "WHERE action='reject' AND (status IS NULL OR status='pending' OR status='')")
            conn.execute("COMMIT")
        _MIGRATED.add(path)
