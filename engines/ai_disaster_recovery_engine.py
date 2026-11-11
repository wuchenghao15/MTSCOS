#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_disaster_recovery_engine — 灾难恢复中心 (Warm Standby)
===========================================================
flow_disaster_recovery_20261026

核心架构:
  ┌──────────────────────┐          ┌──────────────────────┐
  │  🟢 PRIMARY (主)     │ 30s probe │  🟡 STANDBY (备)      │
  │  hulk-macmini:5001   │◄────────►│  hulk-macmini:5002   │
  │  db: database/app.db │ .backup  │  db: COLD_STORAGE/   │
  └──────────────────────┘          └──────────────────────┘
           │                                 │
           ▼                                 ▼
  连续 3× 失败 ❌                     自动升级为 🟢 ACTIVE
  → 触发 failover                     → 更新 registry.status=PRIMARY

failover 三种模式: AUTO / SEMI / LITE

snapshot WAL 管理链 (根治爆盘):
  ① checkpoint 主 WAL → ② 删备 wal/shm → ③ .backup → ④ checkpoint 备 WAL → ⑤ 删备 wal/shm
  standby.db 默认放 ~/MTSCOS_COLD_STORAGE/ (同盘但跟主 DB 分离目录)

用法:
  python3 ai_disaster_recovery_engine.py init     # 建表
  python3 ai_disaster_recovery_engine.py run      # 守护循环 (推荐)
  python3 ai_disaster_recovery_engine.py probe    # 单次探测
  python3 ai_disaster_recovery_engine.py snapshot # 单次 DB 同步
  python3 ai_disaster_recovery_engine.py failover # 手动触发 failover
  python3 ai_disaster_recovery_engine.py recover  # 手动恢复
  python3 ai_disaster_recovery_engine.py status   # 查看状态
"""
from __future__ import annotations
import os, sys, time, json, sqlite3, subprocess, argparse
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_disaster_recovery_20261026"
DAEMON = "sys_disaster_recovery"

# ═══════════════════════════════════════════════════════════════════
# §0 拓扑配置 (可被环境变量覆盖)
# ═══════════════════════════════════════════════════════════════════

PRIMARY_HOST  = os.environ.get('DR_PRIMARY_HOST',  '100.106.220.96')
PRIMARY_PORT  = int(os.environ.get('DR_PRIMARY_PORT',  '5001'))
PRIMARY_SCHEME = os.environ.get('DR_PRIMARY_SCHEME', 'http')
PRIMARY_URL   = f"{PRIMARY_SCHEME}://{PRIMARY_HOST}:{PRIMARY_PORT}"

STANDBY_HOST  = os.environ.get('DR_STANDBY_HOST',  '100.106.220.96')
STANDBY_PORT  = int(os.environ.get('DR_STANDBY_PORT',  '5002'))
STANDBY_URL   = f"http://{STANDBY_HOST}:{STANDBY_PORT}"

# standby.db 默认放 COLD_STORAGE 避免同盘爆盘
_COLD_DIR = os.path.expanduser("~/MTSCOS_COLD_STORAGE")
STANDBY_DB = os.environ.get('DR_STANDBY_DB',
    os.path.join(_COLD_DIR, "app_standby.db"))

PROBE_FAIL_THRESHOLD = 3
PROBE_INTERVAL = 30
DB_SYNC_INTERVAL = 300
FAILOVER_MODE = os.environ.get('DR_FAILOVER_MODE', 'AUTO')

# ═══════════════════════════════════════════════════════════════════
# §1 建表
# ═══════════════════════════════════════════════════════════════════

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_disaster_recovery_registry (
        id INTEGER PRIMARY KEY CHECK(id=1),
        flow_id TEXT,
        primary_url TEXT,
        standby_url TEXT,
        standby_db_path TEXT,
        status TEXT DEFAULT 'NORMAL',
        failover_count INTEGER DEFAULT 0,
        last_failover_at TEXT,
        last_recover_at TEXT,
        last_db_sync_at TEXT,
        db_sync_bytes INTEGER DEFAULT 0,
        db_sync_latency_ms INTEGER DEFAULT 0,
        probe_fail_count INTEGER DEFAULT 0,
        probe_last_ok TEXT,
        probe_last_fail TEXT,
        mode TEXT DEFAULT 'AUTO',
        updated_at TEXT DEFAULT (datetime('now','localtime')))""",

    """CREATE TABLE IF NOT EXISTS mt_disaster_recovery_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT DEFAULT (datetime('now','localtime')),
        event TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT,
        detail TEXT)""",

    """CREATE INDEX IF NOT EXISTS idx_dr_log_ts ON mt_disaster_recovery_log(ts)""",
]


def _db():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init_dr():
    c = _db()
    for s in SCHEMA:
        try:
            c.execute(s)
        except Exception:
            pass
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("""INSERT OR REPLACE INTO mt_disaster_recovery_registry
        (id, flow_id, primary_url, standby_url, standby_db_path,
         status, mode, updated_at)
        VALUES (1,?,?,?,?, 'NORMAL', ?, datetime('now','localtime'))""",
        (FLOW_ID, PRIMARY_URL, STANDBY_URL, STANDBY_DB, FAILOVER_MODE))

    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, updated_at)
            VALUES (?,?, 'RUNNING', datetime('now','localtime'), datetime('now','localtime'))""",
            (DAEMON, f"灾难恢复: probe={PROBE_INTERVAL}s+db_sync={DB_SYNC_INTERVAL}s+auto failover (mode={FAILOVER_MODE})"))
    except Exception:
        pass

    c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
        VALUES ('ENGINE_START', NULL, 'NORMAL', ?)""",
        (json.dumps({"primary": PRIMARY_URL, "standby": STANDBY_URL,
                     "mode": FAILOVER_MODE, "standby_db": STANDBY_DB},
                    ensure_ascii=False),))
    c.close()
    return True


# ═══════════════════════════════════════════════════════════════════
# §2 Health Probe
# ═══════════════════════════════════════════════════════════════════

def _probe(url: str, timeout: float = 5.0) -> dict:
    t0 = time.time()
    try:
        req = Request(f"{url}/api/health", headers={'User-Agent': 'DR-Engine/1.0'})
        with urlopen(req, timeout=timeout) as r:
            latency = int((time.time() - t0) * 1000)
            body = r.read().decode('utf-8')[:200]
            try:
                j = json.loads(body)
                return {"ok": True, "latency_ms": latency, "detail": j}
            except Exception:
                return {"ok": True, "latency_ms": latency, "detail": body}
    except HTTPError as e:
        latency = int((time.time() - t0) * 1000)
        return {"ok": True, "latency_ms": latency, "detail": f"HTTP_{e.code}", "note": "401/403=鉴权墙, 证明服务活着"}
    except (URLError, OSError) as e:
        latency = int((time.time() - t0) * 1000)
        return {"ok": False, "latency_ms": latency, "detail": str(e)[:120]}


def health_probe() -> dict:
    c = _db()
    reg = c.execute("SELECT * FROM mt_disaster_recovery_registry WHERE id=1").fetchone()
    if not reg:
        c.close()
        return {"error": "registry_not_initialized"}

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    primary_url = reg[2]
    status = reg[5] or 'NORMAL'
    mode = reg[11] or 'AUTO'
    fail_count = reg[10] or 0

    primary = _probe(primary_url)
    if primary['ok']:
        fail_count = 0
        c.execute("""UPDATE mt_disaster_recovery_registry
            SET probe_fail_count=0, probe_last_ok=? WHERE id=1""", (now,))
        c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
            VALUES ('PROBE_OK', ?, ?, ?)""",
            (status, status,
             json.dumps({"primary": primary_url, "latency_ms": primary['latency_ms']},
                        ensure_ascii=False)))
    else:
        fail_count += 1
        c.execute("""UPDATE mt_disaster_recovery_registry
            SET probe_fail_count=?, probe_last_fail=? WHERE id=1""", (fail_count, now))
        c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
            VALUES ('PROBE_FAIL', ?, ?, ?)""",
            (status, status,
             json.dumps({"primary": primary_url, "fail_count": fail_count,
                         "detail": primary['detail']}, ensure_ascii=False)))

        if fail_count >= PROBE_FAIL_THRESHOLD and status == 'NORMAL':
            if mode == 'AUTO':
                _trigger_failover(c, reg, now)
            elif mode == 'SEMI':
                c.execute("""INSERT INTO mt_disaster_recovery_log
                    (event, from_status, to_status, detail)
                    VALUES ('FAILOVER_PENDING', ?, ?, ?)""",
                    (status, 'FAILOVER',
                     json.dumps({"mode": "SEMI", "need_confirm": True,
                                 "primary": primary_url,
                                 "fail_count": fail_count}, ensure_ascii=False)))

    if status == 'FAILOVER' and primary['ok']:
        _trigger_recover(c, reg, now)

    standby_url = reg[3]
    standby = _probe(standby_url)

    c.close()
    return {
        "primary": {"url": primary_url, **primary, "fail_count": fail_count},
        "standby": {"url": standby_url, **standby},
        "status": status, "mode": mode,
    }


def _trigger_failover(c, reg, now):
    primary_url = reg[2]; standby_url = reg[3]
    prev_status = reg[5] or 'NORMAL'

    c.execute("""UPDATE mt_disaster_recovery_registry
        SET status='FAILOVER', failover_count=failover_count+1,
            last_failover_at=?, updated_at=datetime('now','localtime'),
            primary_url=?, standby_url=? WHERE id=1""",
        (now, standby_url, primary_url))

    c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
        VALUES ('FAILOVER_DONE', ?, ?, ?)""",
        (prev_status, 'FAILOVER',
         json.dumps({
             "old_primary": primary_url,
             "new_primary": standby_url,
             "at": now,
             "note": "灾难自动切换: 备 Flask 升级为 PRIMARY"
         }, ensure_ascii=False)))
    print(f"  🚨 FAILOVER {now}: {primary_url} → {standby_url}", flush=True)


def _trigger_recover(c, reg, now):
    prev_status = reg[5] or 'FAILOVER'
    standby_url = reg[3]; primary_url = reg[2]

    c.execute("""UPDATE mt_disaster_recovery_registry
        SET status='RECOVERING', last_recover_at=?, updated_at=datetime('now','localtime')
        WHERE id=1""", (now,))

    c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
        VALUES ('RECOVER_START', ?, 'RECOVERING', ?)""",
        (prev_status, json.dumps({"at": now}, ensure_ascii=False)))

    c.execute("""UPDATE mt_disaster_recovery_registry
        SET status='NORMAL', updated_at=datetime('now','localtime') WHERE id=1""")

    c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
        VALUES ('RECOVER_DONE', 'RECOVERING', 'NORMAL', ?)""",
        (json.dumps({"primary_back": primary_url, "standby_back": standby_url,
                     "at": now}, ensure_ascii=False),))
    print(f"  ✅ RECOVER {now}: {primary_url} 恢复为 PRIMARY", flush=True)


# ═══════════════════════════════════════════════════════════════════
# §3 DB Snapshot — 完整 WAL 管理链
# ═══════════════════════════════════════════════════════════════════

def _run_sqlite3(cmd: list[str], timeout: int = 60) -> int:
    """跑 SQLite 命令, 返回退出码"""
    try:
        r = subprocess.run(['sqlite3'] + cmd, capture_output=True, timeout=timeout)
        return r.returncode
    except Exception:
        return -1


def _prune_wal(db_path: str) -> None:
    """对一个 DB 做 checkpoint + 删 wal/shm (磁盘卫生)"""
    _run_sqlite3([db_path, 'PRAGMA wal_checkpoint(TRUNCATE);'], timeout=60)
    for ext in ('-wal', '-shm'):
        w = db_path + ext
        if os.path.exists(w):
            try:
                os.remove(w)
            except Exception:
                pass


def db_snapshot() -> dict:
    """主 DB 热备到备 DB — checkpoint主WAL → 删备wal/shm → .backup → checkpoint备WAL → 删wal/shm"""
    import shutil as _shutil

    c = _db()
    reg = c.execute("SELECT * FROM mt_disaster_recovery_registry WHERE id=1").fetchone()
    c.close()

    if not reg:
        return {"error": "registry_not_found"}

    source_db = DB
    target_db = STANDBY_DB
    target_dir = os.path.dirname(target_db)

    if not os.path.exists(source_db):
        return {"error": f"source_db_not_found: {source_db}"}

    os.makedirs(target_dir, exist_ok=True)

    t0 = time.time()
    try:
        # ① checkpoint 主 WAL (减少 backup 数据量 + 避免 lock)
        _prune_wal(source_db)

        # ② 删旧 standby wal/shm (避免 5002 残留 WAL 膨胀)
        for ext in ('-wal', '-shm'):
            w = target_db + ext
            if os.path.exists(w):
                try:
                    os.remove(w)
                except Exception:
                    pass

        # ③ .backup 原子热备
        result = subprocess.run(
            ['sqlite3', source_db, f'.backup {target_db}'],
            capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            _shutil.copy2(source_db, target_db)
            for ext in ('-wal', '-shm'):
                sw = source_db + ext
                if os.path.exists(sw):
                    _shutil.copy2(sw, target_db + ext)

        # ④ checkpoint standby WAL + 删 wal/shm (磁盘卫生!)
        _prune_wal(target_db)

        elapsed_ms = int((time.time() - t0) * 1000)
        size = os.path.getsize(target_db) if os.path.exists(target_db) else 0

        c = _db()
        c.execute("""UPDATE mt_disaster_recovery_registry
            SET last_db_sync_at=datetime('now','localtime'),
                db_sync_bytes=?, db_sync_latency_ms=? WHERE id=1""",
            (size, elapsed_ms))
        c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
            VALUES ('DB_SYNC', NULL, NULL, ?)""",
            (json.dumps({"source": source_db, "target": target_db,
                         "bytes": size, "latency_ms": elapsed_ms,
                         "note": "checkpoint+.backup+prune"},
                        ensure_ascii=False),))
        c.close()
        return {"ok": True, "bytes": size, "latency_ms": elapsed_ms}

    except Exception as e:
        c = _db()
        c.execute("""INSERT INTO mt_disaster_recovery_log (event, from_status, to_status, detail)
            VALUES ('DB_SYNC_FAIL', NULL, NULL, ?)""",
            (json.dumps({"error": str(e)[:150]}, ensure_ascii=False),))
        c.close()
        return {"ok": False, "error": str(e)[:150]}


# ═══════════════════════════════════════════════════════════════════
# §4 守护循环
# ═══════════════════════════════════════════════════════════════════

def run_once() -> dict:
    out = {"ts": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
           "probe": health_probe()}
    return out


def loop(probe_secs: int = 30, db_secs: int = 300):
    print(f"[DR] 守护启动 primary={PRIMARY_URL} standby={STANDBY_URL} "
          f"mode={FAILOVER_MODE} probe={probe_secs}s db_sync={db_secs}s "
          f"standby_db={STANDBY_DB}", flush=True)
    tick = 0
    while True:
        try:
            out = run_once()
            p = out.get("probe", {})
            status = p.get("status", "?")
            p_ok = p.get("primary", {}).get("ok", False)
            s_ok = p.get("standby", {}).get("ok", False)
            p_lat = p.get("primary", {}).get("latency_ms", "?")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] DR "
                  f"status={status} primary={'🟢' if p_ok else '🔴'}(lat={p_lat}) "
                  f"standby={'🟢' if s_ok else '🔴'}", flush=True)

            if tick % max(1, db_secs // probe_secs) == 0:
                ds = db_snapshot()
                if ds.get("ok"):
                    print(f"  📦 DB 同步 OK {ds['bytes']//1024//1024}MB "
                          f"({ds['latency_ms']}ms)", flush=True)
                else:
                    print(f"  ⚠️ DB 同步失败: {ds.get('error','?')}", flush=True)

            tick += 1
        except Exception as e:
            print(f"[DR] cycle error: {e}", flush=True)
        time.sleep(probe_secs)


# ═══════════════════════════════════════════════════════════════════
# §5 CLI
# ═══════════════════════════════════════════════════════════════════

def show_status():
    c = _db()
    reg = c.execute("SELECT * FROM mt_disaster_recovery_registry WHERE id=1").fetchone()
    print(f"\n{'═'*60}")
    print(f"  🚨 灾难恢复中心 — 状态")
    print(f"{'═'*60}")
    if reg:
        print(f"  主:     {reg[2]}")
        print(f"  备:     {reg[3]}")
        print(f"  备DB:   {reg[4]}")
        print(f"  状态:   {reg[5]}")
        print(f"  模式:   {reg[11]}")
        print(f"  切换:   {reg[6]}")
        print(f"  DB同步: {reg[8]} ({(reg[7] or 0)//1024//1024}MB {reg[12]}ms)")
    else:
        print("  (未初始化, 先 run `init`)")

    logs = c.execute("""SELECT ts, event, from_status, to_status, substr(detail,1,80)
        FROM mt_disaster_recovery_log ORDER BY rowid DESC LIMIT 10""").fetchall()
    if logs:
        print(f"\n  📜 最近日志:")
        for ts, ev, f, t, d in logs:
            print(f"    {ts}  {ev:20s}  {f or '-':10s} → {t or '-':10s}  {d}")
    c.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="🚨 灾难恢复中心 — Warm Standby Failover")
    p.add_argument("action", choices=[
        "init", "run", "probe", "snapshot", "failover", "recover", "status"])
    args = p.parse_args()

    if args.action == "init":
        print(f"🚨 灾难恢复中心初始化")
        print(f"  主: {PRIMARY_URL}")
        print(f"  备: {STANDBY_URL}")
        print(f"  备DB: {STANDBY_DB}")
        print(f"  模式: {FAILOVER_MODE}")
        init_dr()
        print("  ✅ 完成")

    elif args.action == "run":
        init_dr()
        loop()

    elif args.action == "probe":
        print(json.dumps(health_probe(), ensure_ascii=False, indent=2))

    elif args.action == "snapshot":
        print(json.dumps(db_snapshot(), ensure_ascii=False, indent=2))

    elif args.action == "failover":
        c = _db()
        reg = c.execute("SELECT * FROM mt_disaster_recovery_registry WHERE id=1").fetchone()
        _trigger_failover(c, reg, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        c.close()
        print("✅ failover 已触发")

    elif args.action == "recover":
        c = _db()
        reg = c.execute("SELECT * FROM mt_disaster_recovery_registry WHERE id=1").fetchone()
        _trigger_recover(c, reg, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        c.close()
        print("✅ recover 已触发")

    elif args.action == "status":
        show_status()
