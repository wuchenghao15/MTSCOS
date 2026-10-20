# -*- coding: utf-8 -*-
"""
P0 备份体系: 每日冷快照引擎 (flow_backup_20261021)
====================================================
背景: 主库 8.2GB 单点零备份 (实测无 .bak / 无快照目录)。
OneDrive 是同步不是备份 — 误删/损坏会原样扩散到云端。

设计:
  ① 每日一次 VACUUM INTO 冷快照 → /Users/wuchenghao/MTSCOS_BACKUPS (OneDrive 之外)
  ② 当日已有快照则幂等跳过 (--force 强制重跑)
  ③ PRAGMA integrity_check 校验快照完整性
  ④ 保留 KEEP_SNAPSHOTS 份轮转, 删最旧
  ⑤ 每次动作落库 mt_backup_log (自动化永久化硬约束)

用法:
  python3 ai_backup_engine.py backup [--force]   # 单次 (daemon 每小时调, 内部幂等)
  python3 ai_backup_engine.py status             # 查看快照与日志
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DB = os.path.join(PROJECT_ROOT, "flask-app", "database", "app.db")
BACKUP_DIR = "/Users/wuchenghao/MTSCOS_BACKUPS"   # OneDrive 之外, 真冷备
KEEP_SNAPSHOTS = 3
LOG_TABLE = "mt_backup_log"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log_db(action: str, detail: str, ok: int = 1, size: int = 0, elapsed: float = 0) -> None:
    """落库留痕 (表不存在则建)。失败不阻断主流程。"""
    try:
        c = sqlite3.connect(SOURCE_DB, timeout=15)
        c.execute(f"""CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, detail TEXT, ok INTEGER,
            size_bytes INTEGER, elapsed_sec REAL, created_at TEXT)""")
        c.execute(f"INSERT INTO {LOG_TABLE} (action, detail, ok, size_bytes, elapsed_sec, created_at) "
                  "VALUES (?,?,?,?,?,?)", (action, detail, ok, size, elapsed, _now()))
        c.commit()
        c.close()
    except Exception as _e:
        print(f"  ⚠️ 落库失败(不阻断): {_e}")


def today_snapshot() -> str:
    return os.path.join(BACKUP_DIR, f"app_backup_{time.strftime('%Y%m%d')}.db")


def cmd_backup(force: bool = False) -> int:
    t0 = time.time()
    if not os.path.exists(SOURCE_DB):
        print(f"❌ 源库不存在: {SOURCE_DB}")
        return 1
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dst = today_snapshot()
    if os.path.exists(dst) and not force:
        print(f"[backup] 今日快照已存在 → 幂等跳过: {dst}")
        return 0
    tmp = dst + ".building"
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except Exception:
            pass
    print(f"[backup] VACUUM INTO 开始: {SOURCE_DB} → {tmp}")
    src = sqlite3.connect(SOURCE_DB, timeout=60)
    try:
        src.execute("VACUUM INTO ?", (tmp,))
    finally:
        src.close()
    os.rename(tmp, dst)
    elapsed = time.time() - t0
    size = os.path.getsize(dst)
    # 完整性校验
    chk = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    try:
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        chk.close()
    print(f"[backup] 快照完成: {dst} ({size/1e9:.2f}GB, {elapsed:.0f}s, integrity={'OK' if ok else 'FAIL'})")
    _log_db("backup", dst, ok=1 if ok else 0, size=size, elapsed=elapsed)
    if not ok:
        print("❌ 完整性校验失败 → 删除坏快照")
        os.remove(dst)
        return 1
    _rotate()
    return 0


def _rotate() -> None:
    """保留最近 KEEP_SNAPSHOTS 份, 其余删除。"""
    snaps = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith("app_backup_") and f.endswith(".db"))
    for old in snaps[:-KEEP_SNAPSHOTS]:
        p = os.path.join(BACKUP_DIR, old)
        try:
            os.remove(p)
            print(f"[rotate] 删除过期快照: {old}")
            _log_db("rotate", old)
        except Exception as _e:
            print(f"[rotate] 删除失败 {old}: {_e}")
    print(f"[rotate] 现存 {min(len(snaps), KEEP_SNAPSHOTS)} 份快照")


def cmd_status() -> int:
    if not os.path.isdir(BACKUP_DIR):
        print(f"[status] 备份目录不存在: {BACKUP_DIR}")
        return 0
    snaps = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith("app_backup_") and f.endswith(".db"))
    print(f"[status] {BACKUP_DIR} 共 {len(snaps)} 份快照:")
    for s in snaps:
        p = os.path.join(BACKUP_DIR, s)
        print(f"  {s}  {os.path.getsize(p)/1e9:.2f}GB")
    try:
        c = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
        rows = c.execute(f"SELECT action, ok, created_at FROM {LOG_TABLE} ORDER BY id DESC LIMIT 5").fetchall()
        c.close()
        print("[status] 最近动作:")
        for r in rows:
            print(f"  {r[2]}  {r[0]}  ok={r[1]}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 2:
        print(__doc__)
        sys.exit(1)
    if a[1] == "backup":
        sys.exit(cmd_backup(force="--force" in a))
    if a[1] == "status":
        sys.exit(cmd_status())
    print(f"未知命令: {a[1]}")
    sys.exit(1)
