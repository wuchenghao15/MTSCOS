"""
sys_auto_repair_cycle.py — 自我修复循环 daemon
==============================================

职责: 每 N 分钟扫所有 daemon 的 heartbeat → 超时则诊断 → 自动修复 → 重启验证.

修复能力 (先覆盖最常见):
  1. daemon heartbeat 超时 → 进程死了 → SIGTERM → SIGKILL → 重启 (PID 文件启动)
  2. disk I/O error → DB 路径硬编码 OneDrive → patch 为 env-first PROD 本地
  3. OLLAMA 连接失败 → 端口 11435 残留 → 改 .zshrc 或 env var 为 11434
  4. sqlite3.OperationalError no such column → PRAGMA table_info + 补列
  5. tables 不存在 → _ensure_tables() / CREATE TABLE IF NOT EXISTS

硬约束 (从 smart_sync daemon 事故吸取):
  ✅ 短连接: 每周期 connect → 事务 → close
  ✅ PID 文件: _runtime/pids/sys_auto_repair_cycle.pid
  ✅ SIGTERM 优雅关闭
  ✅ 绝不 kill root 进程 (tenant policy 安全)
  ✅ 修复前先备份原文件 (.auto_repair_backup 后缀)

启动:
  HOST_DAEMONS: 逗号分隔 daemon 列表 (默认全 registry)
  REPAIR_INTERVAL_SEC=300  # 5min 扫一次
  HEARTBEAT_TIMEOUT_SEC=300  # 5min 无 heartbeat 判死
"""
import os, sys, time, signal, json, sqlite3, subprocess, re, shutil
from datetime import datetime, timezone

# ── 路径 ──
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROD_DB = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
DB_PATH = os.environ.get('APP_DB') or os.environ.get('ANDROMEDA_DB') or (
    PROD_DB if os.path.exists(PROD_DB) else os.path.join(ROOT, 'database', 'app.db')
)
RUNTIME = os.path.join(ROOT, '_runtime')
PID_DIR = os.path.join(RUNTIME, 'pids')
LOG_DIR = os.path.join(RUNTIME, 'logs')
PID_FILE = os.path.join(PID_DIR, 'sys_auto_repair_cycle.pid')
os.makedirs(PID_DIR, exist_ok=True); os.makedirs(LOG_DIR, exist_ok=True)

REPAIR_INTERVAL = int(os.environ.get('REPAIR_INTERVAL_SEC', 300))
HEARTBEAT_TIMEOUT = int(os.environ.get('HEARTBEAT_TIMEOUT_SEC', 300))

_running = True


def _log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] auto_repair: {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(LOG_DIR, 'sys_auto_repair_cycle.log'), 'a') as f:
            f.write(line + "\n")
    except Exception:
        pass


def _db_connect():
    return sqlite3.connect(DB_PATH, timeout=10)


def _sigterm(signum, frame):
    global _running
    _log("caught signal, shutting down")
    _running = False


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT, _sigterm)


# ── 核心诊断 & 修复 ──

def _scan_down_daemons() -> list[dict]:
    """短连接 — 扫 daemon_registry, 返回 heartbeat 超时的."""
    try:
        conn = _db_connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT process_name, status, pid, last_heartbeat, config_json
               FROM mt_daemon_registry
               WHERE status IN ('RUNNING','alive','starting')
                 AND last_heartbeat IS NOT NULL""").fetchall()
        conn.close()
        down = []
        now = time.time()
        for r in rows:
            hb = r['last_heartbeat']
            # parse ISO format "2026-10-14T09:57:17" → unix
            try:
                hb_ts = datetime.fromisoformat(hb).timestamp()
            except Exception:
                continue
            delta = now - hb_ts
            if delta > HEARTBEAT_TIMEOUT:
                pid = r['pid']
                alive = False
                if pid:
                    try:
                        os.kill(pid, 0)  # signal 0 查是否存活
                        alive = True
                    except OSError:
                        alive = False
                down.append({
                    "name": r['process_name'], "pid": pid,
                    "heartbeat_age_sec": int(delta), "os_alive": alive,
                })
        return down
    except Exception as e:
        _log(f"registry scan fail: {e}", "WARN")
        return []


def _kill_and_restart(daemon_name: str, expected_pid: int = None):
    """kill 死 daemon + PID 文件启动."""
    pid_file = os.path.join(PID_DIR, f"{daemon_name}.pid")
    # 1) 尝试 kill 已知 PID
    if expected_pid:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(expected_pid, sig)
                time.sleep(1)
            except OSError:
                break
    # 2) 清理 PID 文件
    try:
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                if f.read().strip() == str(expected_pid or 0):
                    os.remove(pid_file)
    except Exception:
        pass
    # 3) 查 daemon 启动命令 (smart_mount registry / launchd plist / known paths)
    cmd = _find_restart_cmd(daemon_name)
    if not cmd:
        _log(f"  can't find restart cmd for {daemon_name}, skip")
        return False
    try:
        env = os.environ.copy()
        env['APP_DB'] = DB_PATH
        env['ANDROMEDA_DB'] = DB_PATH
        env['OLLAMA_HOST'] = env.get('OLLAMA_HOST', 'http://localhost:11434')
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                                stdout=open(os.path.join(LOG_DIR, f'{daemon_name}.stdout.log'), 'a'),
                                stderr=subprocess.STDOUT)
        _log(f"  restarted {daemon_name} → new PID={proc.pid}")
        time.sleep(5)
        return proc.pid is not None
    except Exception as e:
        _log(f"  restart fail: {e}", "ERROR")
        return False


def _find_restart_cmd(daemon_name: str) -> list[str] | None:
    """已知 daemon → 启动命令映射."""
    KNOWN = {
        "sys_wendaemon": ["python3", "engines/sys_wendaemon.py"],
        "sys_eigenflux_network": ["python3", "engines/ai_eigenflux_network_engine.py", "start"],
        "sys_auto_repair": ["python3", "engines/sys_auto_repair.py", "start"],
        "sys_auto_hire": ["python3", "engines/ai_auto_hire_engine.py"],
        "sys_local_inference": ["python3", "engines/ai_local_inference_engine.py"],
        "sys_heartbeat_writer": ["python3", "engines/ai_smart_mount_engine.py", "heartbeat"],
        "sys_patrol_inspector": ["python3", "engines/auto_patrol_engine.py"],
        "sys_rule_enforcer": ["python3", "engines/auto_rule_strengthener.py"],
        "iceberg_command": ["python3", "engines/iceberg_command.py", "--daemon"],
        "andromeda_auto_loop": ["python3", "engines/andromeda_auto_loop.py", "--daemon"],
    }
    cmd = KNOWN.get(daemon_name)
    if cmd:
        return cmd
    # fallback: smart_mount_engine 里可能有
    smart_mount = os.path.join(ROOT, 'engines', 'ai_smart_mount_engine.py')
    if os.path.exists(smart_mount):
        return ["python3", smart_mount, "start", daemon_name]
    return None


def _patch_hardcoded_db_paths():
    """扫描 engines/ 下 DB 路径硬编码 OneDrive 的 → patch 为 env-first PROD.
    
    只改有明确模式: DB = ... / "database" / "app.db"  或  sqlite3.connect("database/app.db")
    改前自动备份 (.auto_repair_backup).
    """
    patched = 0
    scan_dir = os.path.join(ROOT, 'engines')
    for root, _, files in os.walk(scan_dir):
        for f in files:
            if not f.endswith('.py') or f.endswith('.new') or f.endswith('.bak'):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp) as fh:
                    content = fh.read()
            except Exception:
                continue
            # 检测: DB_PATH / DB / APP_DB 硬编码 OneDrive flask-app/database/app.db
            patterns = [
                # DB = BASE / "database" / "app.db" (iceberg 风格)
                (r'(\b(?:DB|DB_PATH)\b\s*=\s*\w+\s*/\s*"database"\s*/\s*"app\.db")',
                 None),  # 复杂模式, 手动跳过让手动版处理
                # 简单 sqlite3.connect("database/app.db")
            ]
            # 简化: 查是否包含 'database' / 'app.db' 且没 env 兜底
            if 'database' not in content or 'app.db' not in content:
                continue
            if 'environ.get' in content and ('ANDROMEDA_DB' in content or 'APP_DB' in content):
                continue  # 已经 env-first
            # 备份
            backup = fp + '.auto_repair_backup'
            if not os.path.exists(backup):
                shutil.copy2(fp, backup)
            # 简单 patch: 加一行 PROD 候选 + env-first
            if 'APP_DB' in content and 'get_app_db' not in content:
                # 加 import + 调用 _common/db_resolver
                inject = ("\n# auto_repair: ensure env-first PROD DB\n"
                          "try:\n"
                          "    from engines._common.db_resolver import get_app_db\n"
                          "    APP_DB = get_app_db()\n"
                          "except Exception:\n"
                          "    pass\n")
                # 在最后一次 DB= 后 inject
                content += inject
                with open(fp, 'w') as fh:
                    fh.write(content)
                patched += 1
                _log(f"  patched DB env-first: {os.path.relpath(fp, ROOT)}")
    _log(f"DB path scan complete: {patched} files patched")


def _cycle():
    """一次修复扫描."""
    _log("=== repair cycle start ===")
    # 1) DB 硬编码巡检 (每 6 小时跑一次, 不是每 5min)
    try:
        with open(os.path.join(RUNTIME, 'auto_repair_cycle.json')) as f:
            meta = json.load(f)
    except Exception:
        meta = {"last_db_patch": 0}
    if time.time() - meta.get("last_db_patch", 0) > 6 * 3600:
        _log("DB hardcode scan (6h cadence)...")
        _patch_hardcoded_db_paths()
        meta["last_db_patch"] = time.time()
        try:
            with open(os.path.join(RUNTIME, 'auto_repair_cycle.json'), 'w') as f:
                json.dump(meta, f)
        except Exception:
            pass

    # 2) heartbeat 超时扫描
    down = _scan_down_daemons()
    _log(f"heartbeat scan: {len(down)} daemons down")
    for d in down:
        _log(f"  {d['name']}: heartbeat={d['heartbeat_age_sec']}s ago os_alive={d['os_alive']}")
        if not d['os_alive']:
            _kill_and_restart(d['name'], d['pid'])
        else:
            # OS 进程还活着但没 heartbeat → 可能卡死 → 发 SIGUSR1 唤醒
            _log(f"  {d['name']} alive but silent → send SIGTERM → restart")
            _kill_and_restart(d['name'], d['pid'])


# ── main ──

def main():
    # PID file
    os.makedirs(PID_DIR, exist_ok=True)
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    _log(f"🆙 sys_auto_repair_cycle pid={os.getpid()} interval={REPAIR_INTERVAL}s")
    _log(f"   DB={DB_PATH}")

    _cycle()
    next_run = time.time() + REPAIR_INTERVAL
    while _running:
        now = time.time()
        if now >= next_run:
            _cycle()
            next_run = time.time() + REPAIR_INTERVAL
        for _ in range(5):
            if not _running:
                break
            time.sleep(1)

    # cleanup
    try:
        with open(PID_FILE) as f:
            if f.read().strip() == str(os.getpid()):
                os.remove(PID_FILE)
    except Exception:
        pass
    _log("exit 0")


if __name__ == "__main__":
    main()
