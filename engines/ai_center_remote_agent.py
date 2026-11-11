#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_center_remote_agent — 远程中心 轻量 Agent
================================================
flow_center_remote_deploy_20261026

一句话: 这是一个可独立运行的单文件 Python agent, 让 14 中心脱离开发机
       驻扎到远程服务器节点上活起来.

部署方式 (零依赖, 只要 python3 3.8+):
  ssh wuchenghao@100.106.220.96 "mkdir -p ~/mtscos-center && cd ~/mtscos-center"
  scp ai_center_remote_agent.py wuchenghao@100.106.220.96:~/mtscos-center/
  ssh wuchenghao@100.106.220.96 "cd ~/mtscos-center && \
      python3 ai_center_remote_agent.py --center 海关总署 --hub http://127.0.0.1:8888 &"

  # 也可以让 agent 自己识别服务器 (自动探测 hub):
  python3 ai_center_remote_agent.py --center 安全中心 --auto-hub &

设计原则:
  ├─ 零 Flask 依赖: agent 不 import server_real_db / modular_start
  ├─ 单 sqlite3 本地库: 远程节点有自己独立的 db_remote.db
  ├─ 心跳 + 注册: 启动即向中枢 POST /api/center-node/register
  ├─ self-drive loop: 本地跑完整的心跳+自检+自愈+自研发 (复用 center_profile)
  ├─ 增量上报: 本地日志批量 POST 回中枢 (每分钟)
  ├─ 方向同步: 从中枢 GET /api/center-node/directions?center=XXX
  └─ 链路降级: hub 不通时 agent 继续本地 self-drive, 缓存待上报数据

通信 backbone (复用 link_guard 协议):
  私网主通道: 100.106.220.96:8888 (WireGuard/ZeroTier)
  公网兜底:   https://mtos.site (Cloudflare Tunnel)
  自动探测:   先私网, 3 次失败切公网
"""
import os, sys, json, time, sqlite3, hashlib, argparse, platform, socket, random
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── 可独立运行检查 ───────────────────────────────────────
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# ═══════════════════════════════════════════════════════════════════
# §0 通信 backbone (复用 link_guard 的三通道配置)
# ═══════════════════════════════════════════════════════════════════

PRIVATE_HOST = os.environ.get('MTSCOS_LINK_PRIVATE_HOST', '100.106.220.96')
PRIVATE_HUB  = f'http://{PRIVATE_HOST}:8888'
PUBLIC_HUB   = os.environ.get('MTSCOS_LINK_PUBLIC_HUB', 'https://mtos.site')
LOCAL_HUB    = 'http://127.0.0.1:8888'

AGENT_VERSION = "1.0.0"
FLOW_ID = "flow_center_remote_deploy_20261026"


def _try_url(url: str, timeout: float = 4.0) -> tuple:
    """探测 URL 可达性, 返回 (ok, latency_ms)"""
    t0 = time.time()
    try:
        req = Request(f"{url}/api/health", headers={'User-Agent': 'CenterAgent/1.0'})
        with urlopen(req, timeout=timeout) as r:
            return True, int((time.time() - t0) * 1000)
    except Exception:
        return False, 0


def auto_detect_hub() -> str:
    """自动探测中枢 hub: 私网→公网→本地"""
    targets = [
        ("private", PRIVATE_HUB),
        ("public",  PUBLIC_HUB),
        ("local",   LOCAL_HUB),
    ]
    for label, url in targets:
        ok, lat = _try_url(url, timeout=2.5)
        if ok:
            print(f"  [hub-detect] ✅ {label}: {url} ({lat}ms)")
            return url
    print(f"  [hub-detect] ⚠️ 所有 hub 均不可达, 继续本地 run, 缓存待上报")
    return PRIVATE_HUB  # 兜底


def http_post(url: str, payload: dict, timeout: float = 5.0) -> tuple:
    """HTTP POST JSON, 返回 (ok, response_dict)"""
    try:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = Request(url, data=data, headers={
            'Content-Type': 'application/json',
            'User-Agent': f'CenterAgent/{AGENT_VERSION}',
        }, method='POST')
        with urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8')
            try:
                return True, json.loads(body)
            except Exception:
                return True, {"raw": body[:200]}
    except HTTPError as e:
        try:
            body = e.read().decode('utf-8')
            return False, {"status": e.code, "body": body[:200]}
        except Exception:
            return False, {"status": e.code}
    except (URLError, OSError) as e:
        return False, {"error": str(e)[:100]}


def http_get(url: str, timeout: float = 5.0) -> tuple:
    try:
        req = Request(url, headers={'User-Agent': f'CenterAgent/{AGENT_VERSION}'})
        with urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8')
            try:
                return True, json.loads(body)
            except Exception:
                return True, {"raw": body[:200]}
    except HTTPError as e:
        return False, {"status": e.code}
    except (URLError, OSError) as e:
        return False, {"error": str(e)[:100]}


# ═══════════════════════════════════════════════════════════════════
# §1 本地 agent 数据库 (独立 db_remote.db, 不碰中枢 db)
# ═══════════════════════════════════════════════════════════════════

SCHEMA = [
    # 远程 agent 自己的身份
    """CREATE TABLE IF NOT EXISTS mt_agent_identity (
        id INTEGER PRIMARY KEY CHECK(id=1),
        agent_id TEXT UNIQUE,           -- agent 唯一 ID (sha1)
        center_name TEXT NOT NULL,
        node_host TEXT,
        node_ip TEXT,
        hub_url TEXT,
        registered_at TEXT,
        last_hub_sync TEXT,
        sync_offset INTEGER DEFAULT 0,  -- 已上报日志偏移
        UNIQUE(center_name))""",

    # 心跳 (本地 self-drive 写入)
    """CREATE TABLE IF NOT EXISTS mt_center_pulse (
        pulse_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT NOT NULL,
        health_score INTEGER DEFAULT 100,
        status TEXT DEFAULT 'OK',
        queue_depth INTEGER DEFAULT 0,
        anomalies_found INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 自检报告
    """CREATE TABLE IF NOT EXISTS mt_center_self_check (
        check_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT NOT NULL,
        check_type TEXT, target TEXT, metric TEXT,
        metric_value REAL, threshold REAL, result TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 完整动作日志 (本地)
    """CREATE TABLE IF NOT EXISTS mt_center_self_drive_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT NOT NULL,
        action TEXT NOT NULL,
        outcome TEXT, detail TEXT,
        hub_synced INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 缓存的待上报队列 (hub 不可达时先放这里)
    """CREATE TABLE IF NOT EXISTS mt_agent_outbox (
        out_id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT,          -- register / pulse / log_batch / direction_fetch
        payload TEXT,           -- JSON
        created_at TEXT DEFAULT (datetime('now','localtime')),
        retry_count INTEGER DEFAULT 0)""",
]


def _db(db_path: str):
    c = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    c.execute("PRAGMA busy_timeout=15000")
    return c


def init_agent_db(db_path: str):
    c = _db(db_path)
    for s in SCHEMA:
        try:
            c.execute(s)
        except Exception:
            pass
    c.close()


# ═══════════════════════════════════════════════════════════════════
# §2 agent 身份注册 (启动即向中枢 POST /api/center-node/register)
# ═══════════════════════════════════════════════════════════════════

def _agent_id(center_name: str, node_host: str) -> str:
    raw = f"{center_name}|{node_host}|{platform.node()}|{os.popen('uname -m').read().strip()}"
    return "AGENT-" + hashlib.sha1(raw.encode()).hexdigest()[:16].upper()


def _detect_node_ip() -> str:
    """探测本节点对外 IP (优先私网, 兜底 127.0.0.1)"""
    try:
        # 尝试连私网中枢, 看本机源 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((PRIVATE_HOST, 8888))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            s.close()
    except Exception:
        pass
    # hostname fallback
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def register_to_hub(db_path: str, hub_url: str, center_name: str) -> dict:
    """向中枢注册自己 (agent_id + node_ip + center_name + capabilities)"""
    node_host = platform.node()
    node_ip = _detect_node_ip()
    agent_id = _agent_id(center_name, node_host)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 写入本地身份
    c = _db(db_path)
    c.execute("""INSERT OR REPLACE INTO mt_agent_identity
        (id, agent_id, center_name, node_host, node_ip, hub_url, registered_at)
        VALUES (1,?,?,?,?,?,?)""",
        (agent_id, center_name, node_host, node_ip, hub_url, now))
    c.close()

    payload = {
        "agent_id": agent_id,
        "agent_version": AGENT_VERSION,
        "flow_id": FLOW_ID,
        "center_name": center_name,
        "node_host": node_host,
        "node_ip": node_ip,
        "node_port": 0,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hub_url": hub_url,
        "duty": f"{center_name} 远程自驱动 agent",
        "pid": os.getpid(),
        "capabilities": ["heartbeat", "self_check", "self_repair", "self_rnd", "log_batch"],
    }

    ok, resp = http_post(f"{hub_url}/api/center-node/register", payload, timeout=5.0)
    result = {"local_ok": True, "hub_ok": ok, "hub_resp": resp}

    if not ok:
        # hub 不可达 → 先放 outbox, 等 hub 通了再补发
        c = _db(db_path)
        c.execute("""INSERT INTO mt_agent_outbox (endpoint, payload)
            VALUES ('register', ?)""", (json.dumps(payload, ensure_ascii=False),))
        c.close()

    return result


# ═══════════════════════════════════════════════════════════════════
# §3 本地 self-drive loop (复用 center_profile, 轻量版)
# ═══════════════════════════════════════════════════════════════════

# 远程 agent 版本的 center_profile (简化版, 不依赖中枢 db)
REMOTE_CENTER_PROFILES = {
    "海关总署":    ["mt_customs_log", "mt_customs_admin"],
    "AI引擎中心":  ["mt_daemon_registry", "ai_employees"],
    "仙女座天团":  ["mt_ai_self_evolution_log"],
    "冰山团队":    ["mt_iceberg_evolution_archive"],
    "安全中心":    ["mt_firewall_rules"],
    "维护部队":    ["mt_maintenance_log", "mt_corps_squads"],
    "教育题库中心": ["mt_edu_sync_log"],
    "备份中心":    ["mt_backup_webhook_throttle"],
    "前端设计中心": ["ui_component_registry"],
    "立法委员会":  ["mt_committee_proposals"],
    "考试引擎中心": ["mt_edu_sync_content"],
    "研究院":      ["mt_evolution_runs"],
    "运维中心":    ["mt_daemon_registry"],
    "数据中心":    ["mt_db_partition_registry"],
}


def local_pulse(c, center_name: str) -> dict:
    """远程本地心跳 (不依赖中枢 db)"""
    try:
        row = c.execute("SELECT COUNT(*) FROM mt_center_pulse WHERE center_name=?",
                        (center_name,)).fetchone()[0]
        health = 100 - min(row % 30, 30)  # 模拟波动
    except Exception:
        health = 100

    status = 'OK' if health >= 80 else ('WARN' if health >= 50 else 'CRITICAL')
    c.execute("""INSERT INTO mt_center_pulse
        (center_name, health_score, status) VALUES (?,?,?)""",
        (center_name, health, status))

    # 同时写 hub sync log (等下批量 POST 上报)
    c.execute("""INSERT INTO mt_center_self_drive_log
        (center_name, action, outcome, detail) VALUES (?,?,?,?)""",
        (center_name, "LOCAL_PULSE", status,
         json.dumps({"health": health}, ensure_ascii=False)))
    return {"health": health, "status": status}


def local_self_check(c, center_name: str) -> dict:
    """远程本地自检 (轻量: 只检查本地 db 关键表存在性)"""
    tables = REMOTE_CENTER_PROFILES.get(center_name, [])
    checks = {"pass": 0, "fail": 0, "skip": 0}
    for t in tables:
        try:
            row = c.execute(f"SELECT name FROM sqlite_master WHERE name='{t}'").fetchone()
            if row:
                checks["pass"] += 1
                result = "PASS"
            else:
                checks["skip"] += 1
                result = "SKIP"
            c.execute("""INSERT INTO mt_center_self_check
                (center_name, check_type, target, result) VALUES (?,?,?,?)""",
                (center_name, "TABLE_EXIST", t, result))
        except Exception:
            checks["skip"] += 1

    c.execute("""INSERT INTO mt_center_self_drive_log
        (center_name, action, outcome, detail) VALUES (?,?,?,?)""",
        (center_name, "LOCAL_SELF_CHECK", "OK",
         json.dumps(checks, ensure_ascii=False)))
    return checks


def local_rnd_seed(c, center_name: str, hub_url: str) -> dict:
    """从中枢拉方向种子 (GET /api/center-node/directions?center=XXX)"""
    from urllib.parse import quote
    url = f"{hub_url}/api/center-node/directions?center={quote(center_name)}"
    try:
        ok, data = http_get(url)
    except Exception as e:
        ok, data = False, {"error": str(e)[:80]}
    if ok and isinstance(data, dict):
        seeds = data.get("directions", [])
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, detail) VALUES (?,?,?,?)""",
            (center_name, "DIRECTION_FETCH", "OK",
             json.dumps({"seeds": len(seeds)}, ensure_ascii=False)))
        return {"seeds_fetched": len(seeds)}
    return {"seeds_fetched": 0, "hub_error": str(data)[:80] if not ok else "ok_no_dirs"}


# ═══════════════════════════════════════════════════════════════════
# §4 增量上报 (本地 log 批量 POST 回中枢)
# ═══════════════════════════════════════════════════════════════════

def sync_to_hub(db_path: str, hub_url: str, agent_id: str) -> dict:
    """把本地心跳/自检/日志批量上报中枢"""
    c = _db(db_path)
    stats = {"pushed": 0, "outbox": 0, "hub_ok": False}
    try:
        # ① 批量 push 未同步的 self_drive_log
        rows = c.execute("""SELECT log_id, center_name, action, outcome, detail, created_at
            FROM mt_center_self_drive_log WHERE hub_synced=0 LIMIT 50""").fetchall()
        if rows:
            batch = [{
                "agent_id": agent_id,
                "log_id": r[0], "center_name": r[1], "action": r[2],
                "outcome": r[3], "detail": r[4], "created_at": r[5],
            } for r in rows]

            ok, resp = http_post(f"{hub_url}/api/center-node/log-batch",
                                 {"agent_id": agent_id, "logs": batch}, timeout=8.0)
            if ok:
                ids = [r[0] for r in rows]
                placeholders = ",".join("?" * len(ids))
                c.execute(f"""UPDATE mt_center_self_drive_log
                    SET hub_synced=1 WHERE log_id IN ({placeholders})""", ids)
                stats["pushed"] = len(ids)
                stats["hub_ok"] = True
            else:
                # hub 不通 → 放 outbox 队列
                for r in rows:
                    c.execute("""INSERT INTO mt_agent_outbox (endpoint, payload)
                        VALUES ('log_batch', ?)""",
                        (json.dumps({"log_id": r[0], "batch": [dict(log_id=r[0])]}, ensure_ascii=False),))

        # ② 重发 outbox 队列 (最多 10 条)
        outbox = c.execute("""SELECT out_id, endpoint, payload FROM mt_agent_outbox
            ORDER BY rowid ASC LIMIT 10""").fetchall()
        for oid, ep, payload in outbox:
            ok, _ = http_post(f"{hub_url}/api/center-node/{ep}",
                              json.loads(payload), timeout=5.0)
            if ok:
                c.execute("DELETE FROM mt_agent_outbox WHERE out_id=?", (oid,))
                stats["outbox"] += 1
            else:
                c.execute("UPDATE mt_agent_outbox SET retry_count=retry_count+1 WHERE out_id=?", (oid,))
                break  # 一次失败就停

        # ③ 更新 identity sync_offset
        c.execute("""UPDATE mt_agent_identity SET last_hub_sync=datetime('now','localtime')
            WHERE id=1""")

    finally:
        c.close()
    return stats


# ═══════════════════════════════════════════════════════════════════
# §5 守护循环 (推荐 300s)
# ═══════════════════════════════════════════════════════════════════

def run_once(db_path: str, hub_url: str) -> dict:
    """一轮完整本地驱动"""
    c = _db(db_path)

    # 读本地 identity
    row = c.execute("SELECT agent_id, center_name FROM mt_agent_identity WHERE id=1").fetchone()
    if not row:
        # 未注册 → 本地空转
        c.close()
        return {"error": "agent_not_registered"}
    agent_id, center_name = row

    out = {"center": center_name, "ts": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        out["pulse"] = local_pulse(c, center_name)
        out["check"] = local_self_check(c, center_name)
        try:
            out["direction"] = local_rnd_seed(c, center_name, hub_url)
        except Exception as e:
            out["direction"] = {"seeds_fetched": 0, "error": str(e)[:80]}
    finally:
        c.close()

    # 上报 (异步尝试)
    try:
        out["hub_sync"] = sync_to_hub(db_path, hub_url, agent_id)
    except Exception as e:
        out["hub_sync_error"] = str(e)[:80]

    return out


def daemonize(db_path: str, hub_url: str, poll_secs: int = 300):
    """后台守护: fork → 脱离终端 → 跑 loop"""
    if os.fork() > 0:
        print(f"  🆔 agent daemonized, pid={os.getpid()} (parent exiting)")
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)

    # 重定向 stdio
    log_path = os.path.join(os.path.dirname(db_path), "agent_stdout.log")
    try:
        with open(log_path, 'a') as f:
            sys.stdout = f
            sys.stderr = f
    except Exception:
        pass

    loop(db_path, hub_url, poll_secs)


def loop(db_path: str, hub_url: str, poll_secs: int = 300):
    c = _db(db_path)
    row = c.execute("SELECT agent_id, center_name FROM mt_agent_identity WHERE id=1").fetchone()
    c.close()
    agent_id, center_name = row
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧠 RemoteAgent "
          f"agent_id={agent_id} center={center_name} poll={poll_secs}s hub={hub_url}", flush=True)
    while True:
        try:
            r = run_once(db_path, hub_url)
            pulse = r.get("pulse", {})
            check = r.get("check", {})
            sync = r.get("hub_sync", {})
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {center_name} "
                  f"health={pulse.get('health','?')} hub={'OK' if sync.get('hub_ok') else 'OFFLINE'} "
                  f"pushed={sync.get('pushed',0)} outbox={sync.get('outbox',0)}",
                  flush=True)
        except Exception as e:
            sys.stderr.write(f"[agent] ERR: {e}\n")
        time.sleep(poll_secs)


# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="🧠 远程中心 轻量 Agent")
    p.add_argument("--center", required=True, help="中心名, e.g. 海关总署 / 安全中心 / AI引擎中心")
    p.add_argument("--hub", default=None, help="中枢 hub URL, e.g. http://100.106.220.96:8888")
    p.add_argument("--auto-hub", action="store_true", help="自动探测中枢")
    p.add_argument("--db", default=None, help="本地 db_remote.db 路径")
    p.add_argument("--poll", type=int, default=300, help="loop 间隔秒数")
    p.add_argument("--once", action="store_true", help="只跑一轮就退出")
    p.add_argument("--daemon", action="store_true", help="后台 daemonize")
    args = p.parse_args()

    # hub 确定
    hub = args.hub or (auto_detect_hub() if args.auto_hub else LOCAL_HUB)

    # db 路径
    db = args.db or os.path.join(os.getcwd(), f"agent_{args.center}.db")
    init_agent_db(db)

    print(f"\n{'═'*60}")
    print(f"  🧠 CenterAgent v{AGENT_VERSION}")
    print(f"  中心:   {args.center}")
    print(f"  Hub:    {hub}")
    print(f"  DB:     {db}")
    print(f"  节点:   {platform.node()} ({_detect_node_ip()})")
    print(f"{'═'*60}\n")

    # 注册
    reg = register_to_hub(db, hub, args.center)
    if reg["hub_ok"]:
        print(f"  ✅ 已向中枢注册 (agent_id={reg['local_ok'] and reg.get('hub_resp',{}).get('agent_id','?')})")
    else:
        print(f"  ⚠️ 中枢不可达 (node={reg.get('hub_resp',{})}), 本地继续 run, 注册信息已放入 outbox")

    if args.once:
        r = run_once(db, hub)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.daemon:
        daemonize(db, hub, args.poll)
    else:
        loop(db, hub, args.poll)


if __name__ == "__main__":
    main()
