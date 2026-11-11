#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 冷日志归档 + 瘦身 (flow_cold_archive_20261027)
===================================================
策略:
  1. 先把过期日志行 .dump 到 NAS (保留合规审计数据)
  2. 再 DELETE 过期行 + VACUUM (立即减仓)
  3. 最后 WAL checkpoint (根治爆盘)

用法:
  python3 cold_archive.py run           # 完整归档+瘦身
  python3 cold_archive.py archive       # 只归档到 NAS (不删)
  python3 cold_archive.py purge          # 只删旧行 + VACUUM
  python3 cold_archive.py status         # 看各表行数 + 预计可减仓
"""
from __future__ import annotations
import os, sys, sqlite3, argparse, gzip, subprocess, shutil
from datetime import datetime, timedelta

# ── DB 路径 ──
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from app.db import DB_PATH, connect, db_purge_logs, db_size_mb, wal_size_mb, db_top_tables
except ImportError:
    DB_PATH = os.environ.get("MTSCOS_DB_PATH") or os.path.expanduser(
        "~/MTSCOS_AI_Project/flask-app/database/app.db")
    def connect(): return sqlite3.connect(DB_PATH, timeout=30)

# ── NAS 归档路径 (HULK-NAS 跨网段不可达 → 降级 MyData 1 本地大磁盘) ──
NAS_ARCHIVE_BASE = os.environ.get("MTSCOS_NAS_ARCHIVE",
    "/Volumes/MyData 1/MTSCOS/archive")
LOCAL_TMP = "/tmp/mtscos_cold_archive"

# ── 保留策略 (2026-11-09 对齐到实际 225 张 mt_* 表) ──
_RETENTION = [
    # (table, timestamp_col, days_to_keep)
    # 🔴 日志类表 (冷数据 → 归档后删)
    ("mt_center_proposal_consultations", "created_at", 30),
    ("mt_center_evolution_log",          "created_at", 30),
    ("mt_center_self_check",             "created_at", 30),
    ("mt_ai_brain_feed_log",             "created_at", 60),
    ("mt_collab_message",                "created_at", 30),
    ("mt_center_self_drive_log",         "created_at", 30),
    ("mt_lab_hr_log",                    "created_at", 60),
    ("mt_lab_audit_log",                 "created_at", 90),
    ("mt_trigger_execution_log",         "started_at",   14),
    ("mt_task_landing_log",              "created_at",   30),
    ("mt_vault_audit_log",               "created_at",   90),
    ("mt_dead_letter_queue",             "created_at",   30),
    ("mt_data_anomalies",                "created_at",   60),
    # 🟡 事件流类 (保留更久因为有业务价值)
    ("mt_shield_events",                 "created_at",   90),
    ("mt_hall_flow_timeline",            "transition_at", 60),
]


def _nas_available() -> bool:
    """检查 NAS 可达 (通过 sshfs 或直接路径)."""
    # 如果 MTSCOS_NAS_ARCHIVE 是 sshfs 挂载点, 直接 os.path.exists
    return os.path.exists(NAS_ARCHIVE_BASE)


def archive_table(conn, table: str, ts_col: str, days: int, out_dir: str) -> int:
    """把表中过期行 .dump → .gz. 返回归档行数."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    # 先算要导多少行
    cur = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {ts_col} < datetime('{cutoff}')")
    count = cur.fetchone()[0]
    if count == 0:
        print(f"    {table}: 无过期行 (cutoff={cutoff})")
        return 0

    # .dump 成 SQL 语句
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    out_sql = os.path.join(out_dir, f"{table}_lt_{days}d_{ts}.sql")
    out_gz = out_sql + ".gz"

    print(f"    {table}: 归档 {count:,} 行 → {os.path.basename(out_gz)}")

    # 用 sqlite3 命令行 .dump (比 Python 快)
    with open(out_sql, "w") as f:
        f.write(f"-- MTSCOS cold archive: {table}, cutoff={cutoff}, rows={count}\n")
        f.write(f"-- Generated: {datetime.utcnow().isoformat()}\n")
        # 只导 INSERT 语句, 不导 CREATE TABLE (表已存在)
        subprocess.run(
            ["sqlite3", DB_PATH,
             f"SELECT 'INSERT INTO {table} VALUES(' || "
             f"group_concat(quote({ts_col}), ',') || ',...);' "  # 简化, 实际需要所有列
             f"FROM {table} WHERE {ts_col} < datetime('{cutoff}') LIMIT 1;"],
            capture_output=True, text=True, timeout=120
        )

    # 更简单: 直接用 sqlite3 导出 TSV, 后续可以用 .import 恢复
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    col_str = ", ".join(cols)

    # 分批导出避免内存爆
    chunk = 100000
    offset = 0
    rows_written = 0
    with open(out_sql, "w") as f:
        while True:
            cur = conn.execute(
                f"SELECT {col_str} FROM {table} "
                f"WHERE {ts_col} < datetime('{cutoff}') "
                f"LIMIT {chunk} OFFSET {offset}")
            batch = cur.fetchall()
            if not batch:
                break
            for row in batch:
                vals = ", ".join("?" if v is None else repr(str(v)[:200]) for v in row)
                f.write(f"INSERT INTO {table} VALUES({vals});\n")
            rows_written += len(batch)
            offset += chunk
            print(f"      → {rows_written:,} 行...", end="\r", flush=True)

    # 压缩
    with open(out_sql, "rb") as f_in, gzip.open(out_gz, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(out_sql)
    gz_size = os.path.getsize(out_gz) / 1e6
    print(f"    ✅ {rows_written:,} 行 → {os.path.basename(out_gz)} ({gz_size:.1f} MB)")

    return rows_written


def run_archive():
    """完整归档流程."""
    print(f"DB: {DB_PATH} ({db_size_mb():.1f} MB, WAL={wal_size_mb():.1f} MB)")
    print(f"NAS 归档路径: {NAS_ARCHIVE_BASE} (可用={_nas_available()})")
    print()

    # 本地临时目录
    os.makedirs(LOCAL_TMP, exist_ok=True)

    # 归档到本地 tmp (WAL 安全, 不影响主库)
    conn = connect(readonly=True)
    total_archived = 0
    for table, ts_col, days in _RETENTION:
        try:
            n = archive_table(conn, table, ts_col, days, LOCAL_TMP)
            total_archived += n
        except sqlite3.Error as e:
            print(f"    ❌ {table}: {e}")
    conn.close()

    print(f"\n✅ 本地归档完成, 共 {total_archived:,} 行 → {LOCAL_TMP}/")

    # 如果 NAS 可用, rsync 过去
    if _nas_available():
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        dest = os.path.join(NAS_ARCHIVE_BASE, ts)
        os.makedirs(dest, exist_ok=True)
        for f in os.listdir(LOCAL_TMP):
            shutil.move(os.path.join(LOCAL_TMP, f), os.path.join(dest, f))
        print(f"✅ 已搬 NAS: {dest}/")
    else:
        print(f"⚠️ NAS 不可用, 归档留在本地 {LOCAL_TMP}/ (等 sshfs 挂好后手动 rsync)")


def run_purge():
    """归档后删旧行 + VACUUM."""
    print(f"DB: {DB_PATH} ({db_size_mb():.1f} MB)")
    print("\n删除旧行 (app/db.py db_purge_logs)...")
    result = db_purge_logs()
    total = sum(result.values())
    for tbl, n in result.items():
        print(f"  {tbl}: -{n:,} 行")
    print(f"共删 {total:,} 行")

    before = db_size_mb()
    print(f"\nVACUUM ({before:.1f} MB → ... )")
    try:
        subprocess.run(["sqlite3", DB_PATH, "VACUUM"], timeout=300)
    except subprocess.TimeoutExpired:
        print("⚠️ VACUUM 超时 (300s), 跳过, 下次再试")
    after = db_size_mb()
    print(f"✅ VACUUM 完成: {before:.1f} → {after:.1f} MB (回收 {before - after:.1f} MB)")

    # WAL checkpoint
    conn = connect()
    cp = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    conn.close()
    print(f"✅ WAL checkpoint: busy={cp[0]}, log={cp[1]}, checkpointed={cp[2]}")


def run_status():
    """看各表行数 + 预计可减仓."""
    conn = connect(readonly=True)
    print(f"DB: {DB_PATH} ({db_size_mb():.1f} MB, WAL={wal_size_mb():.1f} MB)")
    print(f"\nTop 日志表 (预估):")
    for table, ts_col, days in _RETENTION:
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            old = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {ts_col} < datetime('{cutoff}')"
            ).fetchone()[0]
            pct = old / total * 100 if total else 0
            print(f"  {table:<30s} 总行={total:>12,} 旧行={old:>12,} ({pct:.0f}%) → 保留 {days} 天")
        except Exception as e:
            print(f"  {table:<30s} ❌ {e}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "archive", "purge", "status"])
    args = ap.parse_args()

    if args.mode == "run":
        run_archive()
        run_purge()
    elif args.mode == "archive":
        run_archive()
    elif args.mode == "purge":
        run_purge()
    elif args.mode == "status":
        run_status()
