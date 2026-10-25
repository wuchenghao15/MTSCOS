#!/usr/bin/env python3
"""
sys_network_probe — 仙女座高贴合度嗅探 daemon (flow_andromeda_sense_20261025)
============================================================================
目标: 让仙女座主动嗅探网络上的所有可用资源 (API/数据源/模型/工具)
产出: mt_network_resource_pool (资源池) + mt_probe_log (嗅探日志)

探测维度:
  ① 本地端口/服务 (mini/hulk/nas 全量端口扫描)
  ② Tailscale tailnet 资源 (所有入网节点的 HTTP/API 端点)
  ③ 公网端点 (mtos.site + Cloudflare Tunnel 出口)
  ④ 公共 API 端点 (Ollama :11434 模型列表、datasette :8001 数据库列表)
  ⑤ 局域网服务发现 (mDNS/Bonjour 名称解析)

每 120s 一轮, 连续 3 轮发现新资源 → 自动建议 smart_mount 接入
"""
import os, sys, time, json, socket, sqlite3, subprocess, urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_andromeda_sense_20261025"
DAEMON = "sys_network_probe"
TARGETS = [
    ("hulk-macmini",   "192.168.31.246", [5001, 11434, 8001, 5593, 22]),
    ("hulk-server",    "192.168.31.103", [11434, 8001, 6379, 80, 22]),
    ("hulk-nas-fnos",  "192.168.31.57",  [5593, 5666, 445, 80]),
    ("tailnet-hulk",   "100.100.244.47", [11434, 8001, 22]),
    ("tailnet-mini",   "100.106.220.96", [5001, 22]),
    ("mtos.site",      "mtos.site",      [80, 443]),
]
HTTP_PROBES = [
    ("", 200), ("/health", None), ("/index", None),
    ("http://127.0.0.1:11434/api/tags", None),    # Ollama
    ("http://127.0.0.1:8001/", None),             # Datasette
]
SCAN_INTERVAL = 120

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_network_resource_pool (
        resource_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name TEXT, target TEXT, port INTEGER,
        service_hint TEXT, http_status INTEGER, note TEXT,
        first_seen TEXT DEFAULT (datetime('now','localtime')),
        last_seen  TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(source_name,target,port))""",
    """CREATE TABLE IF NOT EXISTS mt_probe_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT, event TEXT, detail TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",
]


def _db():
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _probe_tcp(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _probe_http(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MTSCOS-Sense/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def detect_service(port, http_status, banner=""):
    map_ = {
        22: "ssh", 80: "http", 443: "https", 5001: "flask-mtscos",
        11434: "ollama", 8001: "datasette", 5593: "ssh",
        5666: "fnos-web", 445: "smb", 6379: "redis",
    }
    return map_.get(port, f"unknown:{port}")


def scan_once():
    c = _db()
    for s in _SCHEMA:
        c.execute(s)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    new_count = 0
    for host_label, host, ports in TARGETS:
        for port in ports:
            tcp = _probe_tcp(host, port)
            service = detect_service(port, None) if tcp else "closed"
            http_status = None
            if tcp and port in (80, 443, 5001, 11434, 8001):
                scheme = "https" if port == 443 else "http"
                http_status = _probe_http(f"{scheme}://{host}:{port}/")
            note = json.dumps({"tcp": tcp, "http": http_status}, ensure_ascii=False)
            try:
                c.execute("""INSERT OR REPLACE INTO mt_network_resource_pool
                    (source_name, target, port, service_hint, http_status, note, last_seen)
                    VALUES (?,?,?,?,?,?,?)""",
                    (host_label, host, port, service, http_status, note, now))
            except Exception as e:
                print(f"  [skip] {host}:{port} {e}")
            # 新发现资源 → 记日志 (避免重复记录同状态)
            prev = c.execute("SELECT event FROM mt_probe_log WHERE target=? AND created_at > datetime('now','-10 minutes') ORDER BY log_id DESC LIMIT 1",
                           (f"{host}:{port}",)).fetchone()
            if tcp and (not prev or prev[0] != "DISCOVERED"):
                c.execute("""INSERT INTO mt_probe_log (target, event, detail)
                    VALUES (?,?,?)""",
                    (f"{host}:{port}", "DISCOVERED" if tcp else "DOWN", note))
                new_count += 1
    # 更新 daemon 心跳
    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (DAEMON, "仙女座网络资源嗅探 120s (TCP+HTTP 全端口扫描)", "RUNNING",
             now, os.getpid(), json.dumps({"flow_id": FLOW_ID, "targets": len(TARGETS)}, ensure_ascii=False), now))
    except Exception:
        pass
    c.close()
    print(f"[{now}] PROBE_OK new={new_count} targets={len(TARGETS)}")


def loop():
    print(f"[{time.strftime('%H:%M:%S')}] {DAEMON} start, interval={SCAN_INTERVAL}s")
    while True:
        try:
            scan_once()
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ERR: {e}")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    loop()
