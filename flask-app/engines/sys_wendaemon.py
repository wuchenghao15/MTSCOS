"""
sys_wendaemon.py — 仙女座自养活 daemon
===========================================

职责:
  1. 每 6h 触发 wf_hire_employee (AI 员工扩张)
  2. 每 30min 触发 wf_knowledge_ingest (从 eigenflux 新消息自动喂脑库)

硬约束 (从 smart_sync daemon 事故吸取):
  ✅ 短连接: 每周期 connect → 工作事务 → close, 绝不持久持有 DB FD
  ✅ PID 文件: _runtime/pids/sys_wendaemon.pid (启动写, SIGTERM 删)
  ✅ mt_daemon_registry: 注册 process_name=sys_wendaemon + heartbeat + status
  ✅ SIGTERM 优雅关闭: 捕获信号, 清理, exit 0
  ✅ 零空跑: knowledge 来源 = eigenflux_comm_messages WHERE id > last_knowledge_id
  ✅ cadence 可配置: env HIRE_INTERVAL_SEC / INGEST_INTERVAL_SEC

启动:
  python3 engines/sys_wendaemon.py &
  或 launchd: ~/Library/LaunchAgents/com.mtscos.wendaemon.plist
"""

import os, sys, time, signal, json, sqlite3, uuid, threading
from pathlib import Path
from datetime import datetime, timezone

# ── 路径配置 (env-first, 和其他引擎统一) ──
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROD_DB = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
_ONEDRIVE_DB = os.path.join(ROOT, 'database', 'app.db')
DB_PATH = os.environ.get('APP_DB') or (
    _PROD_DB if os.path.exists(_PROD_DB) else _ONEDRIVE_DB
)
RUNTIME_DIR = os.path.join(ROOT, '_runtime')
PID_DIR = os.path.join(RUNTIME_DIR, 'pids')
LOG_DIR = os.path.join(RUNTIME_DIR, 'logs')
PID_FILE = os.path.join(PID_DIR, 'sys_wendaemon.pid')
CHECKPOINT_FILE = os.path.join(RUNTIME_DIR, 'wendaemon_checkpoint.json')

# ── cadence ──
HIRE_INTERVAL = int(os.environ.get('HIRE_INTERVAL_SEC', 6 * 3600))     # 6h
INGEST_INTERVAL = int(os.environ.get('INGEST_INTERVAL_SEC', 30 * 60))   # 30min
HEARTBEAT_INTERVAL = 30  # 30s 一次 heartbeat
HIRE_BATCH_SIZE = int(os.environ.get('HIRE_BATCH_SIZE', 3))
INGEST_BATCH_SIZE = int(os.environ.get('INGEST_BATCH_SIZE', 50))

# ── 状态 ──
_running = True
_lock = threading.Lock()


def _log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] wendaemon: {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, 'sys_wendaemon.log'), 'a') as f:
            f.write(line + "\n")
    except Exception:
        pass


def _pid_write():
    try:
        os.makedirs(PID_DIR, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        _log(f"pid write fail: {e}", "WARN")


def _pid_cleanup():
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(PID_FILE)
    except Exception:
        pass


def _checkpoint_load() -> dict:
    try:
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_hire_at": 0,          # unix ts
        "last_ingest_at": 0,
        "last_knowledge_id": 0,     # 已 ingest 的 eigenflux 最大 id
        "total_hires": 0,
        "total_ingested": 0,
        "total_revenue_usd": 0.0,
    }


def _checkpoint_save(cp: dict):
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(cp, f, indent=2)
    except Exception as e:
        _log(f"checkpoint save fail: {e}", "WARN")


def _registry_heartbeat(status: str = "alive", note: str = ""):
    """短连接写 daemon_registry heartbeat — 用完即关.
    PROD schema (10 列): process_name/duty/status/restart_count/last_heartbeat/pid/cooldown_until/config_json/created_at/updated_at
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute(
            """INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, restart_count, last_heartbeat, pid,
             cooldown_until, config_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("sys_wendaemon", "hire_employee+knowledge_ingest", status, 0,
             datetime.now(timezone.utc).isoformat(), os.getpid(), 0,
             json.dumps({"note": note, "hire_interval": HIRE_INTERVAL,
                         "ingest_interval": INGEST_INTERVAL}, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f"registry fail: {e}", "WARN")


def _eigenflux_new_since(last_msg_id: int, limit: int) -> list[dict]:
    """短连接 — 拉 eigenflux daemon 活跃写入的 mt_ai_eigenflux_messages. 用完即关.
    注意: 不是 eigenflux_comm_messages (283K, 9/20 停更)
    而是 mt_ai_eigenflux_messages (567K+, 活跃 ticking, 列 msg_id/content/sender_name)
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT msg_id, sender_name, receiver_name, topic_cn, content,
                      knowledge_tags_json, learning_value,
                      substr(created_at,1,19) AS created_at
               FROM mt_ai_eigenflux_messages
               WHERE msg_id > ? AND content IS NOT NULL AND content != ''
               ORDER BY msg_id ASC LIMIT ?""",
            (last_msg_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        _log(f"eigenflux query fail: {e}", "WARN")
        return []


def _db_connect() -> sqlite3.Connection:
    """每次调用都新建连接 — 用完即关, 绝不持久持有."""
    return sqlite3.connect(DB_PATH, timeout=10)


# ── 核心周期任务 ──

def _do_hire():
    """触发 wf_hire_employee — 走 workflow engine (短连接)."""
    _log(f"hiring next {HIRE_BATCH_SIZE} AI employees ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import andromeda_workflow_engine as wf
        r = wf.run_workflow(
            'wf_hire_employee',
            {'count': HIRE_BATCH_SIZE, 'min_level': 7},
            trigger_source="daemon",
            blocking=True)
        _log(f"hire done: {r['status']} hired={r['output'].get('hired','?')} "
             f"bridged={r['output'].get('bridged','?')} invited={r['output'].get('invited','?')} "
             f"rev=\${r['revenue_usd']}")
        return True, r['revenue_usd']
    except Exception as e:
        _log(f"hire fail: {e}", "ERROR")
        return False, 0.0


def _do_ingest(last_msg_id: int):
    """从 mt_ai_eigenflux_messages (活跃表) 拉新 → wf_knowledge_ingest — 短连接."""
    msgs = _eigenflux_new_since(last_msg_id, INGEST_BATCH_SIZE)
    if not msgs:
        _log(f"no new mt_ai_eigenflux_messages since msg_id={last_msg_id}, skip ingest")
        return True, last_msg_id, 0.0
    sources = []
    for m in msgs:
        content = m.get('content', '')[:2000]
        sender = m.get('sender_name', 'anon')
        receiver = m.get('receiver_name', '')
        topic = m.get('topic_cn', '')[:40]
        title = f"eigenflux::{sender}→{receiver}#{m.get('msg_id','')}"
        if topic:
            title += f" [{topic}]"
        sources.append({"content": content, "title": title})
    _log(f"ingesting {len(sources)} eigenflux messages (last_msg_id={last_msg_id} → {msgs[-1]['msg_id']}) ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import andromeda_workflow_engine as wf
        r = wf.run_workflow(
            'wf_knowledge_ingest',
            {'sources': sources, 'domain': 'eigenflux_daemon'},
            trigger_source="daemon",
            blocking=True)
        _log(f"ingest done: {r['status']} ingested={r['output'].get('ingested','?')} "
             f"rev=\${r['revenue_usd']}")
        new_last_id = max(last_msg_id, msgs[-1]['msg_id']) if msgs else last_msg_id
        return True, new_last_id, r['revenue_usd']
    except Exception as e:
        _log(f"ingest fail: {e}", "ERROR")
        return False, last_msg_id, 0.0


# ── signal handler ──

def _sigterm_handler(signum, frame):
    global _running
    _log(f"caught signal {signum}, shutting down gracefully ...")
    _running = False


signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


# ── main loop ──

def main():
    global _running
    _pid_write()
    _registry_heartbeat(status="starting", note="wendaemon boot")
    _log(f"🆙 sys_wendaemon started pid={os.getpid()}")
    _log(f"   DB={DB_PATH}")
    _log(f"   HIRE_INTERVAL={HIRE_INTERVAL}s  INGEST_INTERVAL={INGEST_INTERVAL}s")
    _log(f"   HIRE_BATCH={HIRE_BATCH_SIZE}  INGEST_BATCH={INGEST_BATCH_SIZE}")

    # 第一次启动: 立即做一次 heartbeat + 预热
    _registry_heartbeat(status="alive", note="running")

    cp = _checkpoint_load()
    _log(f"   checkpoint loaded: last_hire={cp['last_hire_at']} last_ingest={cp['last_ingest_at']}")

    next_hire = cp['last_hire_at'] + HIRE_INTERVAL
    next_ingest = cp['last_ingest_at'] + INGEST_INTERVAL
    next_hb = time.time() + HEARTBEAT_INTERVAL

    while _running:
        try:
            now = time.time()

            # ── heartbeat ──
            if now >= next_hb:
                _registry_heartbeat(status="alive", note="tick")
                next_hb = now + HEARTBEAT_INTERVAL

            # ── hire ──
            if now >= next_hire:
                ok, rev = _do_hire()
                if ok:
                    cp['last_hire_at'] = now
                    cp['total_hires'] += 1
                    cp['total_revenue_usd'] += rev
                    _checkpoint_save(cp)
                next_hire = now + HIRE_INTERVAL

            # ── ingest ──
            if now >= next_ingest:
                ok, new_last_id, rev = _do_ingest(cp['last_knowledge_id'])
                if ok:
                    cp['last_ingest_at'] = now
                    cp['last_knowledge_id'] = new_last_id
                    cp['total_ingested'] += 1
                    cp['total_revenue_usd'] += rev
                    _checkpoint_save(cp)
                next_ingest = now + INGEST_INTERVAL

            # ── sleep (分片, 能快速响应 SIGTERM) ──
            for _ in range(5):
                if not _running:
                    break
                time.sleep(1)

        except Exception as e:
            _log(f"loop error: {e}", "ERROR")
            time.sleep(5)

    # ── shutdown ──
    _log("shutting down ...")
    _registry_heartbeat(status="stopped", note="graceful shutdown")
    _pid_cleanup()
    _log("✅ sys_wendaemon exit 0")


if __name__ == "__main__":
    main()
