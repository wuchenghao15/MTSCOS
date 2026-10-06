#!/usr/bin/env python3
"""
统一 DB 路径解析器
================

解决 Mac mini 旧库 vs MacBook Flask 活跃库反复踩坑的根因:
  _runtime/databases/Database/app.db  (Mac mini 旧库, 7GB, 缺很多表!)
  flask-app/database/app.db           (Flask 活跃库, 1.6GB, 全表)

用法:
  from engines._common.db_resolver import get_app_db
  APP_DB = get_app_db()       # 返回 flask-app/database/app.db (size>1MB 优先)
  PID_FILE = get_pid_file("ai_eigenflux_network_engine")
"""
import os
from pathlib import Path

def _find_project_root(start: Path) -> Path:
    """向上爬找到项目根 (含 .git 或 flask-app 子目录) — 兼容 symlink/OneDrive"""
    p = start.resolve()
    for _ in range(6):  # 最多爬 6 层
        if (p / ".git").exists() or (p / "flask-app").exists():
            return p
        if p == p.parent:
            break
        p = p.parent
    return start.resolve().parent.parent.parent.parent  # 兜底 4 级

_PROJECT_ROOT = _find_project_root(Path(__file__))
_FLASK_APP_DIR = _PROJECT_ROOT / "flask-app"

# 候选列表: 活跃库优先 + size>1MB 过滤排除空库
_DB_CANDIDATES = [
    _FLASK_APP_DIR / "database" / "app.db",          # ✅ 活跃库第一
    _PROJECT_ROOT / "_runtime" / "databases" / "Database" / "app.db",  # Mac mini 旧库兜底
    _FLASK_APP_DIR / "app.db",
    _PROJECT_ROOT / "app.db",
]

def get_app_db() -> str:
    """返回 Flask 活跃主库路径 (size > 1MB 过滤 + 环境变量覆盖)"""
    # 1) 环境变量覆盖 (最灵活)
    env_override = os.environ.get("APP_DB")
    if env_override and os.path.exists(env_override) and os.path.getsize(env_override) > 1_000_000:
        return env_override

    # 2) 候选列表 + size 过滤
    for cand in _DB_CANDIDATES:
        if cand.exists() and cand.stat().st_size > 1_000_000:
            return str(cand)

    # 3) 兜底: 第一个存在的 (即使 < 1MB)
    for cand in _DB_CANDIDATES:
        if cand.exists():
            return str(cand)

    return str(_DB_CANDIDATES[0])


def get_pid_file(name: str) -> str:
    """统一 PID 文件目录 (_runtime/pids/)"""
    pids_dir = _PROJECT_ROOT / "_runtime" / "pids"
    pids_dir.mkdir(parents=True, exist_ok=True)
    return str(pids_dir / f"{name}.pid")


def get_project_root() -> str:
    return str(_PROJECT_ROOT)


def get_flask_app_dir() -> str:
    return str(_FLASK_APP_DIR)


# 模块加载时就确定 (和老代码保持兼容)
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
