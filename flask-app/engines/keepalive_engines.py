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
import subprocess
import sys
import time
from datetime import datetime

PROJECT_ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
FA_DIR = os.path.join(PROJECT_ROOT, "flask-app")
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "_runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
PYTHON_BIN = "/opt/homebrew/bin/python3"
if not os.access(PYTHON_BIN, os.X_OK):
    PYTHON_BIN = sys.executable

THROTTLE_SECS = 300

ENGINES = [
    ("ai_smart_mount_engine", "engines/ai_smart_mount_engine.py", "start"),
    ("ai_eigenflux_network_engine", "engines/ai_eigenflux_network_engine.py", "start"),
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

    return rc


if __name__ == "__main__":
    sys.exit(main())
