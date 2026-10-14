"""
andromeda API 共享工具
======================
从 andromeda_api.py 抽取的可复用函数:
  _resolve_db_path / _read_checkpoint / _is_daemon_alive
  _mini_ping / _ollama_check / _now_iso / _db_conn / _api_success / _api_error
"""

import os
import json
import sqlite3
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 路径常量 (和 andromeda_api.py 完全对齐, 防漂移) ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# database/app.db 是 SSOT (单数据源), engines/app.db 旧迷你同步副本, 优先级先主库
_DB_CANDIDATES = [
    PROJECT_ROOT / "database" / "app.db",   # ① 主库 SSOT
    PROJECT_ROOT / "engines" / "app.db",   # ② engines 副本
    PROJECT_ROOT / "app.db",               # ③ fallback
]
CHECKPOINT_PATH = PROJECT_ROOT / "ai_engines" / "_runtime" / "evolution_checkpoint.json"
DAEMON_NAMES = ("sys_andromeda_autosync", "sys_andromeda_auto_evolution")
_OLLAMA_PORTS = (11435, 11434, 11436)
_MINI_ADDRS = [
    os.environ.get('MTSCOS_MINI_ADDR', ''),
    'hulk-macmini', '100.106.220.96', '192.168.31.9',
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _resolve_db_path() -> str:
    for p in _DB_CANDIDATES:
        if p.exists():
            return str(p)
    return str(_DB_CANDIDATES[0])


def _db_conn(timeout: int = 5) -> sqlite3.Connection:
    """统一 DB 连接 (WAL + busy_timeout). 调用方需 conn.close()."""
    conn = sqlite3.connect(_resolve_db_path(), timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _api_success(**kwargs) -> dict:
    payload = {"success": True, "generated_at": _now_iso()}
    payload.update(kwargs)
    return payload


def _api_error(msg: str, code: int = 500, **kwargs):
    payload = {"success": False, "msg": msg, "generated_at": _now_iso(), "code": code}
    payload.update(kwargs)
    return payload, code


def _read_checkpoint() -> dict:
    try:
        if CHECKPOINT_PATH.exists():
            with open(CHECKPOINT_PATH) as f:
                cp = json.load(f)
            return {
                "cycle_count": cp.get("cycle_count", 0),
                "total_derived": cp.get("total_derived", 0),
                "total_reinforced": cp.get("total_reinforced", 0),
                "last_knowledge_id": cp.get("last_knowledge_id"),
                "created_at": cp.get("created_at_checkpoint"),
            }
    except Exception:
        pass
    return {"cycle_count": 0, "total_derived": 0, "total_reinforced": 0}


def _is_daemon_alive(hb_str: Optional[str], grace_minutes: int = 60) -> bool:
    """daemon 最后心跳 grace_minutes 内算活 (兼容 UTC/本地混用)."""
    if not hb_str:
        return False
    try:
        raw = hb_str[:19]
        fmt = "%Y-%m-%dT%H:%M:%S" if "T" in raw else "%Y-%m-%d %H:%M:%S"
        ts = datetime.strptime(raw, fmt).timestamp()
        age = time.time() - ts
        if age < 0:
            ts_utc = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
            age = time.time() - ts_utc
        return age < grace_minutes * 60
    except Exception:
        return False


def _mini_ping() -> dict:
    """轻量 ping Mac mini, 不超过 2s."""
    result = {"alive": False, "latency_ms": None, "addr": None}
    for addr in _MINI_ADDRS:
        if not addr: continue
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "2000", addr],
                capture_output=True, text=True, timeout=4
            )
            if r.returncode == 0:
                result["alive"] = True
                result["addr"] = addr
                for line in r.stdout.split("\n"):
                    if "time=" in line:
                        try:
                            result["latency_ms"] = round(
                                float(line.split("time=")[1].split(" ")[0]), 1)
                        except Exception: pass
                        break
                break
        except Exception:
            continue
    return result


def _ollama_check() -> dict:
    """3s 超时检查 Ollama 多端口探测."""
    result = {"alive": False, "models": 0}
    try:
        import urllib.request
        for port in _OLLAMA_PORTS:
            try:
                req = urllib.request.Request(f"http://localhost:{port}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode())
                    result["alive"] = True
                    result["models"] = len(data.get("models", []))
                    result["port"] = port
                    break
            except Exception:
                continue
    except Exception:
        pass
    return result
