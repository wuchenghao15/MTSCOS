#!/usr/bin/env python3
"""
统一 DB 路径解析器  (v2 — 修复 OneDrive disk I/O error 根因)
==================================================================

优先级: env ANDROMEDA_DB > env APP_DB > PROD 本地 > OneDrive flask-app/database
  PROD 本地 = ~/MTSCOS_PROD/flask-app/database/app.db  (非 OneDrive, 1.02GB SSOT)
  OneDrive  = 项目根/flask-app/database/app.db        (被 OneDrive sync 锁死, 9.7GB, disk I/O error)

解决 smart_sync daemon 持 21 FD 锁死 OneDrive DB 导致的全引擎崩链。

用法:
  from engines._common.db_resolver import get_app_db
  APP_DB = get_app_db()
"""
import os
from pathlib import Path

def _find_project_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(6):
        if (p / ".git").exists() or (p / "flask-app").exists():
            return p
        if p == p.parent:
            break
        p = p.parent
    return start.resolve().parent.parent.parent.parent

_PROJECT_ROOT = _find_project_root(Path(__file__))
_FLASK_APP_DIR = _PROJECT_ROOT / "flask-app"

# v2 候选列表: PROD 本地第一, OneDrive 降级为兜底
_PROD_LOCAL_DB = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
_ONEDRIVE_DB   = _FLASK_APP_DIR / "database" / "app.db"
_MAC_MINI_OLD  = _PROJECT_ROOT / "_runtime" / "databases" / "Database" / "app.db"

_DB_CANDIDATES = [
    _PROD_LOCAL_DB,                        # ✅ PROD 本地 1.02GB SSOT 第一
    _ONEDRIVE_DB,                          # OneDrive 镜像 (仅当 PROD 不可用时)
    _MAC_MINI_OLD,                         # Mac mini 旧库兜底
    _FLASK_APP_DIR / "app.db",
    _PROJECT_ROOT / "app.db",
]


def get_app_db() -> str:
    """返回真实可用主库路径. 优先级: env > PROD 本地 > OneDrive (size>1MB 过滤)"""
    # 1) env 覆盖 (ANDROMEDA_DB > APP_DB)
    for env_key in ("ANDROMEDA_DB", "APP_DB", "DATABASE_URL"):
        env_val = os.environ.get(env_key)
        if env_val and os.path.exists(env_val) and os.path.getsize(env_val) > 1_000_000:
            return env_val

    # 2) PROD 本地优先 (size>1MB)
    if _PROD_LOCAL_DB.exists() and _PROD_LOCAL_DB.stat().st_size > 1_000_000:
        return str(_PROD_LOCAL_DB)

    # 3) 候选列表 fallback
    for cand in _DB_CANDIDATES:
        if cand.exists() and cand.stat().st_size > 1_000_000:
            return str(cand)

    # 4) 兜底: 第一个存在的
    for cand in _DB_CANDIDATES:
        if cand.exists():
            return str(cand)

    return str(_PROD_LOCAL_DB)


def get_pid_file(name: str) -> str:
    pids_dir = _PROJECT_ROOT / "_runtime" / "pids"
    pids_dir.mkdir(parents=True, exist_ok=True)
    return str(pids_dir / f"{name}.pid")


def get_project_root() -> str:
    return str(_PROJECT_ROOT)


def get_flask_app_dir() -> str:
    return str(_FLASK_APP_DIR)


APP_DB = get_app_db()

if __name__ == "__main__":
    print(f"APP_DB          = {APP_DB}")
    print(f"  size          = {os.path.getsize(APP_DB)/1024/1024:.1f} MB")
    print(f"PROJECT_ROOT    = {get_project_root()}")
    print(f"PID_DIR         = {os.path.dirname(get_pid_file('test'))}")
    for c in _DB_CANDIDATES:
        exists = c.exists()
        size = c.stat().st_size / 1024 / 1024 if exists else 0
        flag = "✅" if (exists and size > 1) else ("⚠️" if exists else "❌")
        print(f"  {flag} {c}  {size:.1f}MB")
