#!/usr/bin/env python3
"""MTSCOS 引擎保活 (flow_keepalive_rebuild_20261021 v3.2.0)

覆盖 2 个常驻引擎:
  1) ai_smart_mount_engine       — daemon 调度中枢 (15+ daemon)
  2) ai_eigenflux_network_engine — AI<->EigenFlux 网络/交流/心跳

为什么是 Python 而不是 bash:
  - macOS TCC: cron 里 `bash <OneDrive内 .sh/.command>` → "Operation not permitted"
  - 但 `python3 <OneDrive内 .py>` 正常 (ai_file_organizer_cron.log 每10分钟 0 errors 实证)
  - 引擎入口必须带 `start`; ai_smart_mount_engine 无参会打印 __doc__(None) 后 exit 0
  - cwd 必须是 flask-app (引擎用相对路径解析 DB/模板)

部署 (crontab):
  * * * * * /opt/homebrew/bin/python3 /path/_runtime/keepalive_engines.py >> .../logs/keepalive_cron.log 2>&1
  @reboot    /opt/homebrew/bin/python3 /path/_runtime/keepalive_engines.py >> .../logs/keepalive_cron.log 2>&1

用法:
  python3 keepalive_engines.py           # 巡检缺失则拉起 (cron 每分钟)
  python3 keepalive_engines.py --force   # 忽略节流立即拉起
"""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

# flow_autoaudit_20261024: 双机通用 (脚本在 <root>/flask-app/engines/ 下, 三层 dirname 回项目根)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FA_DIR = os.path.join(PROJECT_ROOT, "flask-app")
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "_runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
PYTHON_BIN = "/opt/homebrew/bin/python3"
if not os.access(PYTHON_BIN, os.X_OK):
    PYTHON_BIN = sys.executable

THROTTLE_SECS = 300
# flow_andromeda_selfheal_20261021: 单实例锁 (放 /tmp 本地盘, 不碰 OneDrive)
#   根因: cron 每分钟拉起一次, 当 OneDrive 文件提供者阻塞时进程不退出
#   → 实测堆积 1046 个 keepalive + 1046 个 sh -c + 106 个 file_organizer
LOCK_FILE = "/tmp/mtscos_keepalive.lock"
LOCK_TTL = 1800          # 旧实例卡死超过 30min 视为僵尸, 强制接管
SELF_TIMEOUT_SECS = 120  # 单次巡检自超时 (尽力而为, 若阻塞在系统调用则不保证生效)


def _acquire_lock() -> bool:
    """O_EXCL 单实例锁; 僵尸锁自动接管."""
    try:
        if os.path.exists(LOCK_FILE):
            pid, age = 0, 1e9
            try:
                pid = int(open(LOCK_FILE).read().split()[0])
                age = time.time() - os.path.getmtime(LOCK_FILE)
            except Exception:
                pass
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except Exception:
                    alive = False
            if alive and age < LOCK_TTL:
                return False
            if alive:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return True  # 锁不可用时退化放行, 不阻塞保活


def _release_lock() -> None:
    try:
        pid = int(open(LOCK_FILE).read().split()[0])
        if pid == os.getpid():
            os.remove(LOCK_FILE)
    except Exception:
        pass


def _on_alarm(signum, frame):
    raise SystemExit(3)


ENGINES = [
    ("ai_smart_mount_engine", "engines/ai_smart_mount_engine.py", "start"),
    ("ai_eigenflux_network_engine", "engines/ai_eigenflux_network_engine.py", "start"),
    ("ai_center_hall_hook_engine", "engines/ai_center_hall_hook_engine.py", "start"),  # flow_center_hook_hall_20261025
    ("ai_nas_storage_engine", "engines/ai_nas_storage_engine.py", "start"),  # flow_fnos_nas_integrate_20261025
    ("sys_network_probe", "engines/sys_network_probe.py", "start"),  # flow_andromeda_sense_20261025
    ("sys_center_evolution", "engines/sys_center_evolution.py", "start"),  # flow_andromeda_center_20261025
    ("sys_future_vision", "engines/sys_future_vision.py", "start"),  # flow_andromeda_future_20261025
    # flow_backup_webhook_20261025: 备份中心 kernel (webhook触发+周期独立, 双保险)
    ("ai_backup_kernel", "engines/ai_backup_kernel.py", "once"),
]


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _running(pattern: str) -> str:
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    pids = [p for p in r.stdout.strip().splitlines() if p.strip()]
    return pids[0] if pids else ""


def _throttled(stamp: str, force: bool) -> bool:
    if force:
        return False
    try:
        last = float(open(stamp).read().strip())
    except Exception:
        return False
    return (time.time() - last) < THROTTLE_SECS


def main() -> int:
    force = "--force" in sys.argv[1:]
    os.makedirs(LOG_DIR, exist_ok=True)
    rc = 0

    if not _acquire_lock():
        # 静默跳过: 上一轮仍在跑 (或卡在 OneDrive), 不能每分钟再叠一层
        return 0
    try:
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(SELF_TIMEOUT_SECS)

        for name, rel, arg in ENGINES:
            engine = os.path.join(FA_DIR, rel)
            pattern = f"{os.path.basename(rel)} {arg}"
            stamp = os.path.join(RUNTIME_DIR, f".keepalive_last_spawn_{name}")

            pid = _running(pattern)
            if pid:
                _log(f"{name} RUNNING pid={pid} -> ok")
                continue

            if _throttled(stamp, force):
                _log(f"{name} DOWN but throttled (<{THROTTLE_SECS}s) -> skip")
                continue

            try:
                with open(stamp, "w") as f:
                    f.write(str(time.time()))
            except Exception:
                pass

            if not os.path.exists(engine):
                _log(f"{name} FATAL missing: {engine}")
                rc = 2
                continue

            _log(f"{name} DOWN -> spawn: {PYTHON_BIN} {engine} {arg}")
            try:
                logf = open(os.path.join(LOG_DIR, f"{name}_cron.log"), "a")
                proc = subprocess.Popen(
                    [PYTHON_BIN, engine, arg],
                    cwd=FA_DIR,
                    stdout=logf,
                    stderr=logf,
                    start_new_session=True,
                )
            except Exception as e:
                _log(f"{name} spawn err: {e}")
                rc = 1
                continue

            time.sleep(4)
            if proc.poll() is None:
                _log(f"{name} spawned OK pid={proc.pid}")
            else:
                _log(f"{name} FATAL died in 4s rc={proc.returncode}")
                rc = 1
    except SystemExit:
        _log(f"WATCHDOG self-timeout {SELF_TIMEOUT_SECS}s -> abort this round")
        rc = 1
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass
        _release_lock()

    return rc


if __name__ == "__main__":
    sys.exit(main())
