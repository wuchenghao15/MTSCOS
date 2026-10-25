#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞牛 fnOS NAS 存储节点接入引擎 (flow_fnos_nas_integrate_20261025)
=================================================================
四节点容灾架构: Mac mini(热) + fnOS NAS(冷层 16TB /vol1) + GitHub/Gitee(代码) + 本地 Mac(开发)

主通道: rsync over SSH (端口 5593, mini→NAS 免密 key 已部署)
职责:
  ① SSH 探活  — 端口 5593 + 免密执行 echo (连续失败 3 次 → 告警备案)
  ② 冷层快照  — 法案第十一条三步法: checkpoint → rsync 直传 → NAS 端 VACUUM (滚动 7 份)
  ③ 容量上报  — NAS df 采样 /vol1 → mt_storage_nodes
  ④ 留痕备案  — mt_backup_log NAS_COLD_SNAPSHOT / NAS_NODE_ALERT
  ⑤ SMB 可选  — fnOS web 建共享后可启用 (share 参数, 非必需)
铁律: 禁止 mini 本地 VACUUM/VACUUM INTO 大库 (35G+35G 爆盘教训, flow_fnos_nas_integrate_20261025);
      瘦身一律在 NAS 端 (16TB /vol1) 由 python3 sqlite3 VACUUM INTO 完成。
入口:
  python3 ai_nas_storage_engine.py init    — 注册节点 (免密 key 模式, 无需凭据)
  python3 ai_nas_storage_engine.py once    — 单轮: 探活+快照+容量+心跳
  python3 ai_nas_storage_engine.py start   — loop 模式 (keepalive 拉起)
"""
import os
import sys
import json
import time
import sqlite3
import argparse
import subprocess

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_fnos_nas_integrate_20261025"
ENGINE_NAME = "ai_nas_storage_engine"
NAS_HOST = "192.168.31.57"
NAS_NAME = "hulk-nas-fnos"
NAS_SSH_PORT = 5593
NAS_USER = "wuchenghao15"
NAS_COLD_ROOT = "/vol1/mtscos_nas"
NAS_BACKUP_DIR = f"{NAS_COLD_ROOT}/backup_db"
MOUNT_POINT = os.path.expanduser("~/mtscos_nas_mount")   # SMB 可选挂载点
POLL_INTERVAL = 300
SNAPSHOT_INTERVAL = 86400          # 全量冷层快照节流: 24h 一次 (37G 库 rsync+VACUUM 耗时长)
SLIM_NAME = "app_slim_latest.db"   # NAS 端 VACUUM 紧凑版文件名 (供 hulk-server Datasette 拉取)

_NODES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mt_storage_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_name TEXT UNIQUE,
    node_type TEXT,
    host TEXT,
    ssh_port INTEGER DEFAULT 22,
    share TEXT,
    smb_user TEXT,
    mount_point TEXT,
    cold_root TEXT,
    status TEXT DEFAULT 'UNKNOWN',
    capacity_gb REAL,
    used_gb REAL,
    ssh_alive INTEGER DEFAULT 0,
    last_heartbeat TEXT,
    last_snapshot TEXT,
    fail_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)"""


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [NAS-STORAGE] {msg}", flush=True)


def _nas_ssh(cmd, timeout=30):
    """免密 SSH 执行 NAS 命令 (主通道)"""
    try:
        r = subprocess.run(["ssh", "-p", str(NAS_SSH_PORT), "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=8", f"{NAS_USER}@{NAS_HOST}", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def init_node():
    """注册节点 (rsync/SSH 免密模式)"""
    conn = _db()
    conn.execute(_NODES_TABLE_SQL)
    conn.execute("""INSERT OR REPLACE INTO mt_storage_nodes
                    (node_name, node_type, host, ssh_port, smb_user, mount_point, cold_root,
                     status, last_heartbeat)
                    VALUES (?, 'FNOS_NAS_COLD_16TB', ?, ?, ?, ?, ?, 'REGISTERED',
                            datetime('now','localtime'))""",
                 (NAS_NAME, NAS_HOST, NAS_SSH_PORT, NAS_USER, MOUNT_POINT, NAS_COLD_ROOT))
    conn.commit()
    conn.close()
    _log(f"节点注册: {NAS_NAME} ({NAS_HOST}:{NAS_SSH_PORT}) 冷层 {NAS_COLD_ROOT} (16TB /vol1)")


def _node_row(conn):
    return conn.execute("SELECT * FROM mt_storage_nodes WHERE node_name=?", (NAS_NAME,)).fetchone()


def _capacity(conn):
    """NAS df 采样 /vol1"""
    ok, out, _ = _nas_ssh("df -k /vol1 | tail -1")
    if ok and out:
        parts = out.split()
        if len(parts) >= 3:
            total_gb = int(parts[1]) / 1024 / 1024
            used_gb = int(parts[2]) / 1024 / 1024
            conn.execute("UPDATE mt_storage_nodes SET capacity_gb=?, used_gb=? WHERE node_name=?",
                         (round(total_gb, 1), round(used_gb, 1), NAS_NAME))
            return total_gb, used_gb
    return None, None


def _snapshot_due(conn):
    """快照节流: 24h 内已有成功全量快照则跳过"""
    row = conn.execute("""SELECT created_at FROM mt_backup_log
                          WHERE action='NAS_COLD_SNAPSHOT' AND ok=1
                          ORDER BY created_at DESC LIMIT 1""").fetchone()
    if not row:
        return True
    try:
        last = time.mktime(time.strptime(str(row["created_at"]), "%Y-%m-%d %H:%M:%S"))
        return (time.time() - last) >= SNAPSHOT_INTERVAL
    except Exception:
        return True


def _snapshot(conn):
    """DB 快照 → NAS 冷层 (法案第十一条三步法, 24h 节流):
      ① mini: PRAGMA wal_checkpoint(TRUNCATE) — WAL 落盘归零
      ② rsync 主库直传 NAS backup_db/app_YYYYmmdd_HHMMSS.db (边写库不阻塞, 主库大小稳定)
      ③ NAS 端 python3 VACUUM INTO → app_slim_latest.db 紧凑版 (16TB 冷层, mini 零风险)
      + NAS 端滚动保留 7 份 + rsync 孤儿临时文件清理 + mt_backup_log 备案
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = f"{NAS_BACKUP_DIR}/app_{stamp}.db"

    # ① WAL checkpoint (失败不阻塞: 残留 WAL 只影响快照时点一致性, 不影响主库文件)
    try:
        subprocess.run(["sqlite3", DB_PATH, ".timeout 30000", "PRAGMA wal_checkpoint(TRUNCATE);"],
                       capture_output=True, text=True, timeout=120)
    except Exception as e:
        _log(f"⚠️ checkpoint 异常(继续): {e}")

    # ② rsync 直传 (LAN 千兆关 -z 省 CPU; --partial 保断点)
    t0 = time.time()
    r = subprocess.run(["rsync", "--partial", "--timeout=120", "-e",
                        f"ssh -p {NAS_SSH_PORT} -o BatchMode=yes", DB_PATH,
                        f"{NAS_USER}@{NAS_HOST}:{target}"],
                       capture_output=True, text=True, timeout=14400)
    if r.returncode != 0:
        _log(f"⚠️ rsync 失败: {r.stderr.strip()[:150]}")
        conn.execute("""INSERT INTO mt_backup_log (action, detail, ok, size_bytes, elapsed_sec, created_at)
                        VALUES ('NAS_COLD_SNAPSHOT', ?, 0, 0, ?, datetime('now','localtime'))""",
                     (json.dumps({"target": target, "stage": "rsync",
                                  "err": r.stderr.strip()[:200]}, ensure_ascii=False),
                      int(time.time() - t0)))
        return False

    src_gb = os.path.getsize(DB_PATH) / 1024 / 1024 / 1024

    # ③ NAS 端 VACUUM INTO 紧凑版 (孤儿临时文件一并清理)
    # 注: python3 -c 内联引号严格匹配, .vac_tmp 必须加引号
    vac = ("import sqlite3,os,sys; "
           "src=sys.argv[1]; dst=sys.argv[2]; tmp=src+'.vac_tmp'; "
           "c=sqlite3.connect(src); c.execute('VACUUM INTO ?',(tmp,)); c.close(); "
           "os.replace(tmp,dst)")
    ok3, out3, err3 = _nas_ssh(
        f"python3 -c '{vac}' {target} {NAS_BACKUP_DIR}/{SLIM_NAME} && "
        f"find {NAS_BACKUP_DIR} -maxdepth 1 -name '.*' -size +1G -mmin +30 -delete && "
        f"ls -t {NAS_BACKUP_DIR}/app_2*.db 2>/dev/null | tail -n +8 | xargs -r rm -f && "
        f"ls -l {NAS_BACKUP_DIR}/{SLIM_NAME}",
        timeout=14400)
    slim_note = ""
    if ok3 and SLIM_NAME in out3:
        try:
            slim_kb = int(out3.splitlines()[-1].split()[4]) // 1024
            slim_note = f", slim={slim_kb/1024:.1f}MB"
        except Exception:
            slim_note = ", slim=OK"
    else:
        _log(f"⚠️ NAS VACUUM 失败(原始快照已保留): {err3.strip()[:120]}")

    elapsed = int(time.time() - t0)
    conn.execute("UPDATE mt_storage_nodes SET last_snapshot=datetime('now','localtime') WHERE node_name=?",
                 (NAS_NAME,))
    conn.execute("""INSERT INTO mt_backup_log (action, detail, ok, size_bytes, elapsed_sec, created_at)
                    VALUES ('NAS_COLD_SNAPSHOT', ?, 1, ?, ?, datetime('now','localtime'))""",
                 (json.dumps({"target": target, "node": NAS_NAME, "src_gb": round(src_gb, 1),
                              "slim": SLIM_NAME, "slim_ok": ok3, "flow_id": FLOW_ID},
                             ensure_ascii=False),
                  int(src_gb * 1024 * 1024 * 1024), elapsed))
    _log(f"冷层快照完成: {os.path.basename(target)} (src={src_gb:.1f}GB, {elapsed}s{slim_note})")
    return True


def run_once(do_snapshot=True):
    conn = _db()
    conn.execute(_NODES_TABLE_SQL)
    n = _node_row(conn)
    if not n:
        conn.close()
        _log("节点未注册 — 先运行 init")
        return {"status": "NOT_REGISTERED"}

    # ① SSH 免密探活
    ok, out, _ = _nas_ssh("echo PING_OK && hostname")
    ssh_ok = ok and "PING_OK" in out
    web_ok = _nas_ssh("true", timeout=5)[0]   # 复用 ssh 连通性
    fail = 0 if ssh_ok else (n["fail_count"] or 0) + 1
    status = "ONLINE" if ssh_ok else "OFFLINE"

    cap = (None, None)
    snap = False
    if ssh_ok:
        cap = _capacity(conn)
        if do_snapshot and _snapshot_due(conn):
            snap = _snapshot(conn)

    conn.execute("""UPDATE mt_storage_nodes SET status=?, ssh_alive=?, fail_count=?,
                    last_heartbeat=datetime('now','localtime') WHERE node_name=?""",
                 (status, 1 if ssh_ok else 0, fail, NAS_NAME))
    if fail >= 3:
        conn.execute("""INSERT INTO mt_backup_log (action, detail, ok, size_bytes, elapsed_sec, created_at)
                        VALUES ('NAS_NODE_ALERT', ?, 0, 0, 0, datetime('now','localtime'))""",
                     (json.dumps({"node": NAS_NAME, "host": f"{NAS_HOST}:{NAS_SSH_PORT}",
                                  "fail_count": fail}, ensure_ascii=False),))
        _log(f"🚨 断连告警: 连续 {fail} 次 SSH 失败")
    conn.commit()
    conn.close()
    result = {"node": NAS_NAME, "ssh": ssh_ok, "status": status,
              "capacity_gb": cap[0], "used_gb": cap[1], "snapshot": snap, "fail_count": fail}
    _log(f"探活: {json.dumps(result, ensure_ascii=False)}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["init", "once", "start"], nargs="?", default="once")
    a = ap.parse_args()
    if a.mode == "init":
        init_node()
        run_once()
        return
    if a.mode == "once":
        run_once()
        return
    _log(f"引擎启动 loop, 周期 {POLL_INTERVAL}s")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ 轮次异常: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
