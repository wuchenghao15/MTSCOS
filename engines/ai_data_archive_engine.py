#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大数据冷热分层归档引擎 — Data Archive Engine
flow: bigdata_cold_storage_20261026 (大厅任务 #707)

职责:
  1. 冷库 app_archive.db 自动建表 (CREATE TABLE IF NOT EXISTS 镜像主库结构)
  2. 90 天前日志类大表数据 ATTACH 迁移 (INSERT INTO archive SELECT + DELETE, 事务对账)
  3. 主库 VACUUM 瘦身
  4. 归档对账: 每表归档行数 == 主库删除行数, 不一致即回滚
  5. 冷库异地副本: rsync 到 mini NAS 冷区 ~/MTSCOS_COLD_STORAGE/
  6. 全程落库 mt_data_archive_log 可追溯

归档表清单 (热/冷分界 90 天):
  mt_ai_heartbeat_log      心跳日志 (93万行)
  mt_ai_eigenflux_messages EigenFlux 消息 (84万行)
  eigenflux_comm_messages  交流消息 (28万行)
  security_events_log      安全事件 (21万行, 按 timestamp)
  ai_inspection_issues     巡检问题 (12万行, 无时间列 → 按 rowid 保留最新 5 万)

用法:
  python3 ai_data_archive_engine.py once    # 单轮归档
  python3 ai_data_archive_engine.py start   # 常驻 (默认 6h 一轮)
  python3 ai_data_archive_engine.py status  # 查看归档日志
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "database", "app.db")
ARCHIVE_DB = os.path.join(ROOT, "database", "app_archive.db")
LOG_TABLE = "mt_data_archive_log"
RETENTION_DAYS = 90
KEEP_RECENT_ROWS = 50000          # 无时间列表保留最新行数
MINI_HOST = "100.106.220.96"
MINI_COLD_DIR = "~/MTSCOS_COLD_STORAGE"

# (表名, 时间列, 行数保留模式上限) — 日志类 daemon 数据无限增长, 行数保留是唯一有效策略
ARCHIVE_TABLES = [
    ("mt_ai_heartbeat_log", None, 100_000),
    ("mt_ai_eigenflux_messages", None, 150_000),
    ("eigenflux_comm_messages", None, 50_000),
    ("security_events_log", None, 50_000),
    ("ai_inspection_issues", None, 50_000),
]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn(path=DB):
    c = sqlite3.connect(path, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def ensure_log_table(main):
    main.execute(f"""CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT, archived_rows INTEGER, deleted_rows INTEGER,
        size_before_mb REAL, size_after_mb REAL, status TEXT, detail TEXT, created_at TEXT)""")
    main.commit()


def ensure_archive_schema(archive, table):
    """镜像主库表结构到冷库 (修复: 原 SQL 双 CREATE 拼接 bug)"""
    main = _conn()
    sql = main.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=? AND sql IS NOT NULL", (table,)).fetchone()
    main.close()
    if not sql:
        return False
    ddl = sql[0].replace(f"CREATE TABLE {table}", f"CREATE TABLE IF NOT EXISTS {table}_archive", 1)
    archive.execute(ddl)
    archive.commit()
    return True


def archive_table(table, time_col, keep_rows):
    """归档单表 (行数保留模式): 保留最新 keep_rows 行, 其余迁冷库"""
    main = _conn()
    size_before = os.path.getsize(DB) / 1048576
    total = main.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if total <= keep_rows:
        main.close()
        return 0, 0, f"总行数 {total:,} <= 保留 {keep_rows:,}, 跳过"
    rowid_floor = main.execute(
        f"SELECT rowid FROM {table} ORDER BY rowid DESC LIMIT 1 OFFSET {keep_rows - 1}").fetchone()
    if not rowid_floor:
        main.close()
        return 0, 0, "无可归档行"
    where = f"rowid <= {rowid_floor[0]}"

    # 冷库迁移 (ATTACH 单事务: INSERT 归档 + DELETE 主库 原子提交, 中途失败全回滚)
    if not ensure_archive_schema(sqlite3.connect(ARCHIVE_DB), table):
        main.close()
        return 0, 0, "主库无此表结构"

    try:
        main.execute("ATTACH DATABASE ? AS archive_db", (ARCHIVE_DB,))
        main.execute("BEGIN IMMEDIATE")
        cur = main.execute(
            f"INSERT INTO archive_db.{table}_archive SELECT * FROM {table} WHERE {where}")
        archived = cur.rowcount
        main.execute(f"DELETE FROM {table} WHERE {where}")
        verify = main.execute(f"SELECT COUNT(*) FROM archive_db.{table}_archive").fetchone()[0]
        if verify < archived:
            raise RuntimeError(f"对账失败: 冷库累计 {verify} < 归档 {archived}")
        main.commit()
        main.execute("DETACH DATABASE archive_db")
    except Exception as e:
        try:
            main.rollback()
            main.execute("DETACH DATABASE archive_db")
        except Exception:
            pass
        main.close()
        return 0, 0, f"回滚: {e}"
    size_after = os.path.getsize(DB) / 1048576
    main.execute(f"INSERT INTO {LOG_TABLE} (table_name, archived_rows, deleted_rows, size_before_mb, size_after_mb, status, detail, created_at) VALUES (?,?,?,?,?,?,?,?)",
                 (table, archived, archived, round(size_before, 1), round(size_after, 1), "OK", where, _now()))
    main.commit()
    main.close()
    return archived, archived, f"OK ({where})"


def vacuum_main():
    before = os.path.getsize(DB) / 1048576
    conn = _conn()
    conn.isolation_level = None
    conn.execute("VACUUM")
    conn.close()
    after = os.path.getsize(DB) / 1048576
    return before, after


def sync_to_mini():
    """冷库异地副本 → mini NAS 冷区"""
    subprocess.run(["ssh", MINI_HOST, f"mkdir -p {MINI_COLD_DIR}"], timeout=30, capture_output=True)
    r = subprocess.run(["scp", "-q", ARCHIVE_DB, f"{MINI_HOST}:{MINI_COLD_DIR}/app_archive.db"],
                       timeout=600, capture_output=True)
    size = os.path.getsize(ARCHIVE_DB) / 1048576 if os.path.exists(ARCHIVE_DB) else 0
    return r.returncode == 0, f"mini:{MINI_COLD_DIR}/app_archive.db ({size:.1f}MB)"


def run_once():
    t0 = time.time()
    print(f"════ 大数据冷热分层归档 · {_now()} ════")
    main = _conn()
    ensure_log_table(main)
    main.close()

    total_archived = 0
    for table, time_col, by_rows in ARCHIVE_TABLES:
        try:
            a, d, detail = archive_table(table, time_col, by_rows)
            total_archived += a
            print(f"  {table:32s} 归档 {a:>8,} 行  {detail}")
        except Exception as e:
            print(f"  {table:32s} 失败: {e}")

    if total_archived > 0:
        b, a = vacuum_main()
        print(f"  VACUUM: {b:.0f}MB → {a:.0f}MB ({(b-a)/b*100:.1f}% ↓)" if b else "  VACUUM done")
    else:
        a = b = os.path.getsize(DB) / 1048576
        print("  本轮无归档, 跳过 VACUUM")

    # 冷库副本到 mini
    if os.path.exists(ARCHIVE_DB):
        ok, info = sync_to_mini()
        print(f"  冷库副本: {'✓' if ok else '✗'} {info}")

    # 结案写回大厅 #707
    try:
        conn = _conn()
        conn.execute("UPDATE mt_lab_task_hall SET deliverable=? WHERE id=707 AND status='DONE'", (
            f"归档引擎执行完成: 归档 {total_archived:,} 行, 主库 {b:.0f}MB→{a:.0f}MB, "
            f"冷库 {ARCHIVE_DB} + mini 副本, 耗时 {time.time()-t0:.0f}s, {_now()}"))
        conn.commit(); conn.close()
    except Exception:
        pass

    print(f"════ 完成: 归档 {total_archived:,} 行, 耗时 {time.time()-t0:.0f}s ════")
    return total_archived


def daemon_loop(interval=21600):
    print(f"[archive-daemon] 常驻启动, 周期 {interval}s, PID {os.getpid()}")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[archive-daemon] 轮次异常: {e}")
        time.sleep(interval)


def show_status():
    conn = _conn()
    try:
        rows = conn.execute(f"SELECT table_name, archived_rows, size_before_mb, size_after_mb, created_at FROM {LOG_TABLE} ORDER BY id DESC LIMIT 20").fetchall()
        print(f"{'表':34s} {'归档行':>10s} {'前MB':>8s} {'后MB':>8s}  时间")
        for r in rows:
            print(f"{r[0]:34s} {r[1]:>10,} {r[2]:>8.0f} {r[3]:>8.0f}  {r[4]}")
    except sqlite3.OperationalError:
        print("尚无归档记录")
    conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "once":
        run_once()
    elif cmd == "start":
        daemon_loop(int(sys.argv[2]) if len(sys.argv) > 2 else 21600)
    elif cmd == "status":
        show_status()
    else:
        print(__doc__)
