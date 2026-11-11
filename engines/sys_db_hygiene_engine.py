#!/usr/bin/env python3
# sys_db_hygiene_engine.py — P0-20261026 磁盘满事故治本引擎 (flow_db_hygiene_20261026)
# 职责: 磁盘水位守护 + 心跳/消息日志滚动治理 (热72h/30d + 聚合落库 + NAS冷快照由backup_kernel链路承担)
# 铁律: 禁止 mini 本地 VACUUM 大库; 大数据一律 NAS 端瘦身 (flow_fnos_nas_integrate_20261025)
import sqlite3, os, time, shutil, json, datetime

DB = "/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db"
LOG = "/private/tmp/db_hygiene.log"
WARN, CRIT = 0.80, 0.90
HB_KEEP_DAYS = 3      # 心跳热数据保留天数 (12064员工高频写入, 只留72h)
MSG_KEEP_DAYS = 30    # EigenFlux消息保留天数

def log(msg):
    line = f"{datetime.datetime.now().isoformat()} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def disk_usage():
    st = shutil.disk_usage("/")
    return st.used / st.total, st.free / (1 << 30)

def ensure_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS mt_db_hygiene_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT, detail TEXT,
        disk_pct REAL, freed_rows INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mt_ai_heartbeat_daily_agg (
        day TEXT PRIMARY KEY, total_rows INTEGER, employees INTEGER)""")

def agg_and_prune(c, table, ts_col, keep_days, agg_table, agg_daycol="day"):
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=keep_days)).isoformat()
    # 1) 聚合即将删除的历史 (幂等: REPLACE)
    if agg_table:
        c.execute(f"""INSERT OR REPLACE INTO {agg_table} ({agg_daycol}, total_rows, employees)
            SELECT date({ts_col}), count(*), count(DISTINCT employee_id)
            FROM {table} WHERE {ts_col} < ? AND date({ts_col}) >= date('now','-90 days')""", (cutoff,))
    # 2) 分批删除 (每批50万, 避免长事务锁库)
    total = 0
    while True:
        cur = c.execute(f"DELETE FROM {table} WHERE rowid IN "
                        f"(SELECT rowid FROM {table} WHERE {ts_col} < ? LIMIT 500000)", (cutoff,))
        total += cur.rowcount
        c.commit()
        if cur.rowcount < 500000:
            break
    return total

def main():
    # 并发锁: 防止 launchd 300s 周期任务叠加运行 (大批量删除时单轮可达小时级)
    LOCK = "/private/tmp/db_hygiene.lock"
    try:
        if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 1800:
            return
        open(LOCK, "w").write(str(os.getpid()))
    except Exception:
        pass
    try:
        _run()
    finally:
        try:
            os.remove(LOCK)
        except Exception:
            pass

def _run():
    pct, free_gb = disk_usage()
    ts = datetime.datetime.utcnow().isoformat()
    c = sqlite3.connect(DB, timeout=30)
    ensure_tables(c)
    c.commit()
    # 心跳/消息治理每次运行执行 (增量小, 秒级)
    try:
        n1 = agg_and_prune(c, "mt_ai_heartbeat_log", "created_at", HB_KEEP_DAYS,
                           "mt_ai_heartbeat_daily_agg")
        n2 = agg_and_prune(c, "mt_ai_eigenflux_messages", "created_at", MSG_KEEP_DAYS, None)
        if n1 or n2:
            log(f"pruned heartbeat={n1} messages={n2}")
        c.execute("INSERT INTO mt_db_hygiene_log (ts, action, detail, disk_pct, freed_rows) "
                  "VALUES (?,?,?,?,?)", (ts, "PRUNE", f"hb={n1},msg={n2}", round(pct, 4), n1 + n2))
        c.commit()
    except Exception as e:
        log(f"prune error: {e}")
        try:
            c.execute("INSERT INTO mt_db_hygiene_log (ts, action, detail, disk_pct, freed_rows) "
                      "VALUES (?,?,?,?,?)", (ts, "PRUNE_ERROR", str(e)[:200], round(pct, 4), 0))
            c.commit()
        except Exception:
            pass
    # 水位守护
    if pct >= CRIT:
        log(f"CRITICAL disk {pct:.1%} free={free_gb:.1f}GB -> aggressive mode")
        try:
            n = agg_and_prune(c, "mt_ai_heartbeat_log", "created_at", 1, None)  # 降到24h
            c.execute("INSERT INTO mt_db_hygiene_log (ts, action, detail, disk_pct, freed_rows) "
                      "VALUES (?,?,?,?,?)", (ts, "CRIT_PRUNE", f"hb24h={n}", round(pct, 4), n))
            c.commit()
            log(f"aggressive prune freed {n}")
        except Exception as e:
            log(f"crit prune error: {e}")
    elif pct >= WARN:
        log(f"WARN disk {pct:.1%} free={free_gb:.1f}GB")
    c.close()

if __name__ == "__main__":
    main()
