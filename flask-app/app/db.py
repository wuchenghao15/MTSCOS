#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单一数据库入口 (flow_db_unify_chat_20261022)
============================================
MTSCOS 所有模块应从此文件取 DB_PATH 和 connect()。

解析优先级 (权威源由上至下):
  1. 环境变量 MTSCOS_DB_PATH / APP_DB (prod 部署强制注入)
  2. ~/MTSCOS_PROD/flask-app/database/app.db (本地磁盘 > 1e8 字节)
  3. flask-app/database/app.db (仓库内副本 > 1e8)
  4. 回退候选 (engines/app.db / flask-app/app.db / flask-app/database/app.db)

连接策略:
  - 只读模式 → 自动启用 WAL (journal_mode=WAL)
  - 写模式 → PRAGMA busy_timeout=30000 + journal_mode=WAL
  - 每次 connect 都会自动把 DB_PATH 写进 os.environ['APP_DB'] (让其他模块同步)

瘦身:
  - db_top_tables(conn, limit=10)  → 按页面数 + 行数
  - db_vacuum(conn)                → VACUUM (建议每 10GB 跑一次)
  - db_wal_status(conn)            → 诊断 WAL/shm 文件大小
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

FLOW_ID = "flow_db_unify_chat_20261022"

# ─── 路径解析 ──────────────────────────────────────────────────────────
_FLASK_APP = str(Path(__file__).resolve().parent.parent)
_ROOT = str(Path(_FLASK_APP).parent)


def resolve_db_path() -> str:
    """单一权威解析器 (v22.25.42+).

    v25.1 → v25.4 → v22.25.42 三次强化: PROD DB 强制优先, 避免 OneDrive 路径
    disk I/O error 和多库漂移 (chat_local_bp vs andromeda_chat_bp 曾各解析一次)。
    """
    for env_key in ("MTSCOS_DB_PATH", "APP_DB"):
        env = os.environ.get(env_key, "").strip()
        if env and os.path.exists(env):
            return env
    # 强制 PROD DB 优先 (本地磁盘权威源)
    prod = os.path.expanduser("~/MTSCOS_PROD/flask-app/database/app.db")
    if os.path.exists(prod) and os.path.getsize(prod) > 1e8:
        return prod
    # 候选: 任何 > 1e8 字节的都视为真库
    candidates = [
        os.path.join(_FLASK_APP, "database", "app.db"),
        os.path.join(_FLASK_APP, "engines", "app.db"),
        os.path.join(_ROOT, "app.db"),
        os.path.join(_FLASK_APP, "app.db"),
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 1e8:
            return c
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


DB_PATH = resolve_db_path()
# 同步到环境变量: 让仍未迁移的旧模块 (34 份 _db()) 也能拿到正确路径
os.environ.setdefault("APP_DB", DB_PATH)


# ─── 连接工厂 ─────────────────────────────────────────────────────────
def connect(timeout: float = 15.0, busy_timeout_ms: int = 30000,
             readonly: bool = False, row_factory=sqlite3.Row) -> sqlite3.Connection:
    """统一 sqlite3.connect + WAL + row_factory.

    readonly=True 时只走 WAL, 不设置 busy_timeout (减少锁).
    """
    if readonly:
        conn = sqlite3.connect(DB_PATH, timeout=timeout, uri=True)
        conn.execute("PRAGMA journal_mode=WAL")
    else:
        conn = sqlite3.connect(DB_PATH, timeout=timeout)
        conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # WAL 下 NORMAL 安全且快
    conn.row_factory = row_factory
    return conn


# ─── 瘦身工具 ─────────────────────────────────────────────────────────
def db_size_mb() -> float:
    return os.path.getsize(DB_PATH) / 1e6 if os.path.exists(DB_PATH) else 0.0


def wal_size_mb() -> float:
    wal = DB_PATH + "-wal"
    shm = DB_PATH + "-shm"
    return (os.path.getsize(wal) if os.path.exists(wal) else 0
            + os.path.getsize(shm) if os.path.exists(shm) else 0) / 1e6


def db_top_tables(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """按 sqlite_stat1 统计页面数 + 估算行数 (需 ANALYZE 过)."""
    try:
        # stat 字段形如 "12345 6789" (pages rows)
        rows = conn.execute(
            'SELECT tbl, stat FROM sqlite_stat1 '
            'ORDER BY CAST(substr(stat, 1, instr(stat, " ") - 1) AS INTEGER) DESC LIMIT ?',
            (limit,)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        parts = (r["stat"] or "").split()
        pages = int(parts[0]) if parts else 0
        est_rows = int(parts[1]) if len(parts) > 1 else 0
        out.append({"table": r["tbl"], "pages": pages, "estimated_rows": est_rows,
                    "page_mb": round(pages * 4096 / 1e6, 2)})
    return out


def db_vacuum(conn: sqlite3.Connection | None = None) -> float:
    """执行 VACUUM, 返回节省的 MB (粗略估算)."""
    before = db_size_mb()
    close_after = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=60)
        close_after = True
    try:
        conn.execute("VACUUM")
    finally:
        if close_after:
            conn.close()
    return round(before - db_size_mb(), 2)


# ─── 日志表瘦身 (flow_db_slim_20261022 入口预备) ─────────────────────
# 诊断 (python3 app/db.py): Top 3 表占 81% —— heartbeat_log 3.7GB,
# eigenflux_messages 2.3GB, eigenflux_comm 1.2GB. 都是只写不删的日志.
_LOG_RETENTION_TABLES = [
    # (table, timestamp_col, days_to_keep)
    ("mt_ai_heartbeat_log", "created_at", 3),       # 心跳 30s 一条, 3 天够了
    ("mt_ai_eigenflux_messages", "created_at", 14),  # 消息 14 天
    ("eigenflux_comm_messages", "created_at", 14),   # 同上
    ("mt_local_ai_inference_log", "created_at", 7),  # 推理日志 7 天
    ("mt_daemon_health_log", "created_at", 3),       # daemon 心跳 3 天
    ("mt_rule_violation_alert", "created_at", 90),   # 违规告警 90 天 (合规)
    ("mt_dev_flow_events", "created_at", 365),       # §14 事件 1 年 (审计)
    ("mt_dev_flow_session_events", "created_at", 365),
]


def db_purge_logs(conn: sqlite3.Connection | None = None,
                   tables: list[tuple[str, str, int]] | None = None) -> dict:
    """按保留天数清理旧日志行, 返回 {table: deleted_rows}.

    默认用 _LOG_RETENTION_TABLES; 任何表/列不存在就跳过不报错.
    """
    tables = tables or _LOG_RETENTION_TABLES
    close_after = conn is None
    conn = conn or connect(timeout=30)
    result = {}
    try:
        for tbl, ts_col, days in tables:
            try:
                # 先检查表和列是否存在, 避免全库 DDL 变更
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
                if ts_col not in cols:
                    continue
                cur = conn.execute(
                    f"DELETE FROM {tbl} WHERE {ts_col} < datetime('now','-{days} days')")
                if cur.rowcount > 0:
                    result[tbl] = cur.rowcount
            except sqlite3.Error:
                continue
        conn.commit()
    finally:
        if close_after:
            conn.close()
    return result


def db_wal_status(conn: sqlite3.Connection) -> dict:
    """诊断 WAL / journal 状态, 用于判断是否需要 checkpoint."""
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    except Exception:
        mode = "unknown"
    return {
        "journal_mode": mode,
        "wal_mb": wal_size_mb(),
        "db_mb": db_size_mb(),
        "auto_checkpoint": conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0] if mode == "wal" else None,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="MTSCOS DB 诊断/瘦身 CLI")
    ap.add_argument("--purge", action="store_true", help="按保留天数清理旧日志")
    ap.add_argument("--vacuum", action="store_true", help="执行 VACUUM 回收磁盘")
    ap.add_argument("--top", type=int, default=10, help="Top N 大表 (默认 10)")
    args = ap.parse_args()

    c = connect()
    print(f"DB_PATH  = {DB_PATH}")
    print(f"DB size  = {db_size_mb():.1f} MB   WAL = {wal_size_mb():.1f} MB")
    print(f"journal  = {c.execute('PRAGMA journal_mode').fetchone()[0]}")
    print("\nTop tables:")
    for t in db_top_tables(c, args.top):
        print(f"  {t['table']:<32s} pages={t['pages']:>10d}  est_rows={t['estimated_rows']:>12d}  ~{t['page_mb']:>8.1f} MB")
    c.close()

    if args.purge:
        print("\n--- db_purge_logs ---")
        before = db_size_mb()
        purged = db_purge_logs()
        for tbl, n in purged.items():
            print(f"  {tbl:<32s} -{n} 行")
        if purged:
            print(f"清理后 DB {db_size_mb():.1f} MB (回收 {before - db_size_mb():.1f} MB)")
        else:
            print("  无过期行, 未清理")

    if args.vacuum:
        print("\n--- db_vacuum (可能数秒到数分钟) ---")
        saved = db_vacuum()
        print(f"VACUUM 完成, 节省 {saved:.1f} MB, 当前 {db_size_mb():.1f} MB")
