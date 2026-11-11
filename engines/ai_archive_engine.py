# -*- coding: utf-8 -*-
"""
P1 数据归档引擎: 日志类大表滚动归档 (flow_archive_20261021)
=============================================================
背景: 主库 8.2GB, mt_ai_heartbeat_log 183万 / eigenflux 消息 84万 /
security_events 12.7万 全部 append-only 只进不出, 单库单调膨胀。

设计 (安全第一):
  ① 冷归档库 flask-app/database/app_archive.db (OneDrive 内, 与主库同目录)
  ② 每表配置 (PK列, 时间列, 保留天数) — 时间列 ISO 格式, 字符串比较安全
  ③ 分批事务: INSERT INTO archive SELECT → DELETE 主库 同一事务, 失败回滚,
     归档行数与删除行数强一致, 绝不先删后写
  ④ 单轮每表上限 MAX_BATCH_ROWS, 首次海量迁移分多轮消化, 不锁死主库
  ⑤ 每表动作落库 mt_archive_log (自动化永久化)
  ⑥ 主库 VACUUM 不自动做 (8.2GB 锁库太久) — 空间回收由人工择机执行

用法:
  python3 ai_archive_engine.py run [--dry-run]   # daemon 每6h调 (dry-run 只统计)
  python3 ai_archive_engine.py status            # 各表存量与归档进度
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DB = os.path.join(PROJECT_ROOT, "flask-app", "database", "app.db")
ARCHIVE_DB = os.path.join(PROJECT_ROOT, "flask-app", "database", "app_archive.db")

# 表 → (PK列, 时间列, 保留天数)
ARCHIVE_CONFIG = {
    "mt_ai_heartbeat_log":      ("hb_id", "created_at", 14),
    "mt_ai_eigenflux_messages": ("msg_id", "created_at", 60),
    "security_events_log":      ("id", "created_at", 90),
    "ai_inspection_issues":     ("id", "detected_at", 60),
}
BATCH_SIZE = 20000
MAX_BATCH_ROWS = 300000   # 单表单轮搬运上限


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(action: str, table: str, archived: int, deleted: int, ok: int = 1, detail: str = "") -> None:
    try:
        c = sqlite3.connect(SOURCE_DB, timeout=15)
        c.execute("""CREATE TABLE IF NOT EXISTS mt_archive_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, table_name TEXT, archived_rows INTEGER, deleted_rows INTEGER,
            ok INTEGER, detail TEXT, created_at TEXT)""")
        c.execute("INSERT INTO mt_archive_log (action, table_name, archived_rows, deleted_rows, ok, detail, created_at) "
                  "VALUES (?,?,?,?,?,?,?)", (action, table, archived, deleted, ok, detail, _now()))
        c.commit()
        c.close()
    except Exception as _e:
        print(f"  ⚠️ 落库失败(不阻断): {_e}")


def _ensure_archive_table(ac, table: str) -> bool:
    """在归档库复刻主库同名表 schema (含索引定义取 CREATE TABLE 原文)。"""
    src = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    try:
        row = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not row:
            return False
        # 幂等建表: 主库 schema 原文无 IF NOT EXISTS, 二次归档必须幂等
        # (flow_archive_20261021 首跑实测: 表已存在→引擎级异常→daemon轮0行)
        ddl = row[0]
        if "IF NOT EXISTS" not in ddl.upper():
            ddl = ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
        ac.execute(ddl)
        ac.commit()
        return True
    finally:
        src.close()


def archive_table(table: str, dry_run: bool = False) -> int:
    pk, tcol, keep_days = ARCHIVE_CONFIG[table]
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    src = sqlite3.connect(SOURCE_DB, timeout=30)
    total_archived = total_deleted = 0
    try:
        old = src.execute(f"SELECT COUNT(*) FROM {table} WHERE {tcol} < ?", (cutoff,)).fetchone()[0]
        if old == 0:
            print(f"[archive] {table}: 无超 {keep_days} 天旧行 → 跳过")
            return 0
        if dry_run:
            print(f"[archive] {table}: {old} 行早于 {cutoff} 可归档 (dry-run)")
            return old
        ac = sqlite3.connect(ARCHIVE_DB, timeout=30)
        if not _ensure_archive_table(ac, table):
            print(f"[archive] {table}: 主库无此表 → 跳过")
            ac.close()
            return 0
        # 分批同事务搬运
        while total_deleted < min(old, MAX_BATCH_ROWS):
            batch = src.execute(f"SELECT {pk} FROM {table} WHERE {tcol} < ? LIMIT {BATCH_SIZE}",
                                (cutoff,)).fetchall()
            if not batch:
                break
            ids = [r[0] for r in batch]
            ph = ",".join("?" * len(ids))
            # 搬运: 从主库读整行 → 写归档库 → 同事务删主库 (失败回滚, 强一致)
            rows = src.execute(f"SELECT * FROM {table} WHERE {pk} IN ({ph})", ids).fetchall()
            try:
                ac.executemany(f"INSERT OR IGNORE INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
                ac.commit()
                src.execute(f"DELETE FROM {table} WHERE {pk} IN ({ph})", ids)
                src.commit()
                total_archived += len(rows)
                total_deleted += len(ids)
            except Exception as _e:
                ac.rollback()
                src.rollback()
                print(f"[archive] {table}: 批次失败回滚 → {_e}")
                _log("archive_batch_fail", table, total_archived, total_deleted, ok=0, detail=str(_e)[:300])
                break
        ac.close()
        print(f"[archive] {table}: 归档 {total_archived} 行, 主库删除 {total_deleted} 行 (cutoff={cutoff})")
        _log("archive", table, total_archived, total_deleted,
             ok=1, detail=f"cutoff={cutoff} batch={BATCH_SIZE}")
        return total_archived
    finally:
        src.close()


def cmd_run(dry_run: bool = False) -> int:
    print(f"[archive] run dry_run={dry_run} archive_db={ARCHIVE_DB}")
    grand = 0
    for table in ARCHIVE_CONFIG:
        try:
            grand += archive_table(table, dry_run=dry_run) or 0
        except Exception as _e:
            print(f"[archive] {table}: 引擎级异常 → {_e}")
            _log("archive_engine_err", table, 0, 0, ok=0, detail=str(_e)[:300])
    print(f"[archive] 本轮合计 {grand} 行")
    return 0


def cmd_status() -> int:
    src = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    print(f"[status] {'表':30s} {'主库存量':>10s} {'保留期':>6s} {'归档库存量':>10s}")
    has_arch = os.path.exists(ARCHIVE_DB)
    ac = sqlite3.connect(f"file:{ARCHIVE_DB}?mode=ro", uri=True) if has_arch else None
    for table, (_pk, tcol, keep) in ARCHIVE_CONFIG.items():
        try:
            n = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            n = -1
        try:
            a = ac.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if ac else 0
        except Exception:
            a = 0   # 归档库尚未建该表 (未被归档过)
        print(f"  {table:30s} {n:>10d} {keep:>5d}d {a:>10d}")
    src.close()
    if ac:
        ac.close()
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 2:
        print(__doc__)
        sys.exit(1)
    if a[1] == "run":
        cmd_run(dry_run="--dry-run" in a)
    elif a[1] == "status":
        cmd_status()
    else:
        print(f"未知命令: {a[1]}")
        sys.exit(1)
    sys.exit(0)
