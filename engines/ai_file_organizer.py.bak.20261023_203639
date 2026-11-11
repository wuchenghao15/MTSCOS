#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
智能自动化文件整理引擎
================================================================
flow_id: flow_file_organizer_20260819_001

功能:
  1. 扫描项目根目录, 识别散落的文件
  2. 按文件类型智能归类到正确目录
  3. 清理空目录/临时文件/备份文件
  4. 检测命名规范违规, 自动重命名
  5. 整理记录落库, 可追溯

整理规则:
  - .py → flask-app/engines/ 或 flask-app/ai_engines/ 或对应模块
  - .sh/.command → _config/services/ 或 scripts/
  - .plist → _config/services/
  - .html → templates/对应模块/
  - .js → static/js/对应模块/
  - .css → static/css/
  - .json → 对应模块/config/
  - .md → docs/ 或 .trae/rules/
  - .sql → _config/sql/
  - .log → _runtime/logs/
  - .pid → _runtime/pids/
  - 空目录 → 删除
  - 临时文件(*.tmp, *.bak, *.swp, ~*) → 删除

CLI:
  python3 ai_file_organizer.py scan     扫描+报告(不执行)
  python3 ai_file_organizer.py organize  执行整理
  python3 ai_file_organizer.py status   查看历史
  python3 ai_file_organizer.py start    守护模式
"""
import fcntl
import json
import os
import re
import shutil
import signal
import sqlite3
import sys
import time
import threading
from datetime import datetime
from typing import Dict, List
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.join(ROOT, "..")
PROJECT_ROOT = os.path.normpath(PROJECT_ROOT)
AI_ENGINES_DIR = os.path.join(ROOT, "ai_engines")
APP_DB = os.path.join(PROJECT_ROOT, "_runtime", "databases", "Database", "app.db")
# v25.4 SSOT 统一: get_app_db() 优先(PROD本地>主库), 直跑CLI时补 sys.path (修复 main() 前坏路径); 失败回退默认 (flow_gap_fill_20261018)
try:
    import sys as _sys
    _sys.path.insert(0, ROOT)
    from engines._common.db_resolver import get_app_db as _get_app_db
    APP_DB = _get_app_db()
except Exception:
    pass
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "_runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
PID_DIR = os.path.join(RUNTIME_DIR, "pids")
PID_FILE = os.path.join(PID_DIR, "ai_file_organizer.pid")
LOG_FILE = os.path.join(LOG_DIR, "ai_file_organizer.log")

for _d in [LOG_DIR, PID_DIR]:
    os.makedirs(_d, exist_ok=True)

_LOCK = threading.Lock()
SCAN_INTERVAL = 600  # 10分钟

# 防重入锁文件 (CLI organize/scan 模式互斥, 防止cron堆积)
LOCK_FILE = os.path.join(PID_DIR, "ai_file_organizer.lock")
# 全流程截止秒数 (超时截断扫描, 防止OneDrive IO卡死无限等待)
ORGANIZE_DEADLINE = 120
# 大文件保护阈值: 超过则跳过 stat/删除 (防止OneDrive占位符触发云下载物化)
MAX_FILE_SIZE = 50 * 1024 * 1024

# 递归扫描剪枝清单 (os.walk 标准剪枝法: 原地修改 dirnames, 真正不进入目录)
# 注意: 必须用 dirnames 列表成员判断, 禁止用 `in dirpath` 子串判断 (历史bug)
SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    "_runtime", "static", "docs", "templates", "_config", ".trae", ".idea",
    ".vscode", "backup", "backups", "archive", "archives", "dist", "build",
    "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache", "git_push_ws",
    "auto_daemons", "databases", "Database", "logs", "pids", "cdn", "assets",
    "sdk", "cluster", "nginx", "data", "recovery", "sandbox", "shadow",
    "versions", "target", ".cache", "htmlcov",
    # 数据库备份目录 (OneDrive IO 挂起高发区, 含2.6GB级备份文件)
    "Database_Backups", "Database_Backup", "db_backup", "sql_backup",
    "migrations", "app_db_backups",
}


class ScanTimeout(Exception):
    """SIGALRM 看门狗超时 (可中断挂起中的 OneDrive 系统调用)"""
    pass


def _alarm_handler(signum, frame):
    raise ScanTimeout()


def arm_watchdog(seconds: int):
    """启动看门狗: seconds 秒后向主线程发 SIGALRM, 中断一切挂起中的系统调用"""
    if threading.current_thread() is not threading.main_thread():
        return False
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(max(1, int(seconds)))
    return True


def disarm_watchdog():
    signal.alarm(0)

# 整理规则: (文件后缀/模式, 目标目录, 描述)
ORGANIZE_RULES = [
    # Python引擎文件
    (r"^ai_.*\.py$", "flask-app/engines", "AI引擎文件"),
    (r"^auto_.*\.py$", "flask-app/engines", "自动化引擎文件"),
    (r"^deep_.*\.py$", "flask-app/engines", "深度巡检引擎"),
    (r"^copy_.*\.py$", "flask-app/engines", "文案巡检引擎"),
    (r"^rule_.*\.py$", "flask-app/engines", "规则引擎文件"),
    # Shell脚本
    (r"^.*\.command$", "_config/services", "macOS启动脚本"),
    (r"^.*\.sh$", "_config/services", "Shell脚本"),
    # plist
    (r"^com\.mtscos\..*\.plist$", "_config/services", "launchd配置"),
    # SQL
    (r"^.*\.sql$", "_config/sql", "SQL脚本"),
    # 文档
    (r"^.*\.md$", "docs", "文档文件"),
    # 日志
    (r"^.*\.log$", "_runtime/logs", "日志文件"),
    # PID
    (r"^.*\.pid$", "_runtime/pids", "PID文件"),
    # 备份文件 (归档而非删除: 防止误删 ai fix 的 .bak 回滚点)
    (r"^.*\.bak$", "backups", "备份文件"),
    (r"^.*\.backup$", "backups", "备份文件"),
    (r"^.*\.(tar\.gz|tgz|tar|gz|zip|rar|7z|bz2|xz)$", "backups", "压缩备份包"),
]

# 临时文件模式 (自动删除)
TEMP_PATTERNS = [
    r"^.*\.tmp$",
    r"^.*\.swp$",
    r"^~.*",
    r"^.*\.DS_Store$",
    r"^__pycache__$",
    r"^.*\.pyc$",
]

# ── 系统级自动清理配置 (仙女座 patrol 队接管, daemon 每 30min 跑一次) ──
SYSTEM_TEMP_DIRS = [
    # /tmp 里的临时 Python 脚本 (.py, .sh, .txt 大于 24h)
    ("/private/tmp",  {".py": 86400, ".sh": 86400, ".txt": 86400, ".log": 3600}),
    ("/tmp",          {".py": 86400, ".sh": 86400, ".txt": 86400, ".log": 3600}),
    # macOS 用户缓存 (只清 .DS_Store + 空目录, 不碰真正的 App 缓存)
    (os.path.expanduser("~/Library/Caches"), {".DS_Store": 0}),
]

# orphan 后台进程模式 (pgrep 匹配后 kill)
ORPHAN_PROCESS_PATTERNS = [
    # 之前被 pkill -9 掉 Flask 后残留的子进程
    ("modular_start", {"max_age_sec": 3600, "action": "SIGTERM→SIGKILL"}),
    # 孤儿 Python 脚本 (/tmp/*.py 跑了超 2h)
    ("python3.*tmp.*\.py", {"max_age_sec": 7200, "action": "SIGTERM"}),
    # 残留的 tail -f /tmp/*.log
    ("tail.*flask_.*\\.log", {"max_age_sec": 86400, "action": "SIGTERM"}),
    # pgrep -f smart_mount / eigenflux 的重复实例 (正常应只各一个)
    ("ai_smart_mount_engine", {"max_instances": 1, "action": "SIGTERM 多余的"}),
    ("ai_eigenflux_network_engine", {"max_instances": 1, "action": "SIGTERM 多余的"}),
]

# 全局 __pycache__ + .pyc 清理 (项目内)
PYCACHE_SCAN_DIRS = [PROJECT_ROOT, ROOT]

# 目录映射: 根目录散落文件的目标
DIR_MAPPING = {
    "flask-app": "flask-app",
    "static": "static",
    "templates": "templates",
    "docs": "docs",
    "_config": "_config",
    "_runtime": "_runtime",
    ".trae": ".trae",
    "node_modules": "node_modules",
    "tests": "tests",
}

# 保留在根目录的文件
ROOT_KEEP_FILES = {
    "README.md", "requirements.txt", "package.json", ".gitignore",
    "sync_github.sh", "sync_github_fast.sh", "start_ai_eigenflux_daemon.command",
    "start_smart_mount_daemon.command",
}

# 保留在根目录的目录
ROOT_KEEP_DIRS = {
    "flask-app", "static", "templates", "docs", "_config", "_runtime",
    ".trae", ".git", "node_modules", "tests", "venv", ".venv",
    "__pycache__", "logs", "pids",
}


def _now() -> str:
    return datetime.now().isoformat()


def _log(msg: str):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{_now()}] {msg}\n")


# ============================================================
# 建表
# ============================================================
def ensure_organizer_tables():
    with _LOCK:
        # 看门狗保护: connect 2.6GB OneDrive SQLite 可能挂起, SIGALRM 可中断
        armed = arm_watchdog(60)
        try:
            conn = sqlite3.connect(APP_DB, timeout=30)
            c = conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS mt_file_organize_log (
                organize_id     TEXT PRIMARY KEY,
                action          TEXT NOT NULL,
                file_path       TEXT NOT NULL,
                from_path       TEXT,
                to_path         TEXT,
                file_size       INTEGER DEFAULT 0,
                reason          TEXT,
                organized_at    TEXT NOT NULL
            )""")
            c.execute("""
            CREATE TABLE IF NOT EXISTS mt_file_organize_stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT NOT NULL,
                files_moved     INTEGER DEFAULT 0,
                files_deleted   INTEGER DEFAULT 0,
                dirs_removed    INTEGER DEFAULT 0,
                dirs_created    INTEGER DEFAULT 0,
                bytes_freed     INTEGER DEFAULT 0,
                updated_at      TEXT NOT NULL
            )""")
            conn.commit()
            conn.close()
        except ScanTimeout:
            _log("[DB] ensure_organizer_tables 看门狗超时(60s), 跳过建表检查")
        finally:
            if armed:
                disarm_watchdog()


# ============================================================
# 1. 扫描散落文件
# ============================================================
def scan_loose_files() -> List[Dict]:
    """扫描根目录下散落的文件(不在正确目录中的文件)"""
    loose_files = []
    root = PROJECT_ROOT
    armed = arm_watchdog(ORGANIZE_DEADLINE)

    try:
        for entry in os.listdir(root):
            full_path = os.path.join(root, entry)

            # 跳过保留目录
            if os.path.isdir(full_path):
                if entry in ROOT_KEEP_DIRS or entry.startswith("."):
                    continue
                # 非保留目录 → 标记为需要整理
                loose_files.append({
                    "type": "directory",
                    "name": entry,
                    "path": full_path,
                    "size": 0,
                    "action": "REVIEW",
                    "reason": f"非标准目录: {entry}",
                })
                continue

            # 跳过保留文件
            if entry in ROOT_KEEP_FILES:
                continue

            # 检查是否是临时文件
            is_temp = False
            for pattern in TEMP_PATTERNS:
                if re.match(pattern, entry, re.IGNORECASE):
                    is_temp = True
                    break

            # OneDrive占位符保护: lstat 不触发云下载, 大文件 size 记0
            try:
                st = os.lstat(full_path)
                file_size = st.st_size if st.st_size <= MAX_FILE_SIZE else 0
            except OSError:
                continue

            if is_temp:
                loose_files.append({
                    "type": "temp_file",
                    "name": entry,
                    "path": full_path,
                    "size": file_size,
                    "action": "DELETE",
                    "reason": "临时文件",
                })
                continue

            # 匹配整理规则
            target_dir = None
            reason = ""
            for pattern, dest, desc in ORGANIZE_RULES:
                if re.match(pattern, entry, re.IGNORECASE):
                    target_dir = os.path.join(root, dest)
                    reason = desc
                    break

            if target_dir:
                # 检查文件是否已在正确位置
                rel_path = os.path.relpath(full_path, root)
                if not rel_path.startswith(dest):
                    loose_files.append({
                        "type": "loose_file",
                        "name": entry,
                        "path": full_path,
                        "size": file_size,
                        "action": "MOVE",
                        "target": target_dir,
                        "reason": reason,
                    })
            else:
                # 未知文件类型 → 保留但标记
                loose_files.append({
                    "type": "unknown_file",
                    "name": entry,
                    "path": full_path,
                    "size": file_size,
                    "action": "KEEP",
                    "reason": "未匹配整理规则",
                })
    except ScanTimeout:
        _log("[SCAN] loose_files 看门狗超时, 返回部分结果")
    finally:
        if armed:
            disarm_watchdog()

    return loose_files


# ============================================================
# 2. 扫描空目录
# ============================================================
def scan_empty_dirs() -> List[Dict]:
    """扫描空目录 (仅限 flask-app 代码目录, 剪枝+超时保护)"""
    empty_dirs = []
    deadline = time.time() + ORGANIZE_DEADLINE
    armed = arm_watchdog(ORGANIZE_DEADLINE)

    try:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # os.walk 标准剪枝: 原地修改 dirnames, 真正不进入跳过目录
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if time.time() > deadline:
                _log("[SCAN] empty_dirs 扫描超时截断")
                break

            if not dirnames and not filenames:
                if dirpath != ROOT:
                    empty_dirs.append({
                        "type": "empty_dir",
                        "path": dirpath,
                        "action": "DELETE",
                        "reason": "空目录",
                    })
    except ScanTimeout:
        _log("[SCAN] empty_dirs 看门狗超时, 返回部分结果")
    finally:
        if armed:
            disarm_watchdog()

    return empty_dirs


# ============================================================
# 3. 扫描临时文件(递归)
# ============================================================
def scan_temp_files() -> List[Dict]:
    """递归扫描临时文件 (仅限 flask-app 代码目录, 剪枝+超时+大文件保护)"""
    temp_files = []
    deadline = time.time() + ORGANIZE_DEADLINE
    pycache_count = 0
    armed = arm_watchdog(ORGANIZE_DEADLINE)

    try:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            # 先记录 __pycache__ 再剪枝 (保证删除逻辑仍生效)
            if "__pycache__" in dirnames:
                temp_files.append({
                    "type": "pycache_dir",
                    "path": os.path.join(dirpath, "__pycache__"),
                    "action": "DELETE",
                    "reason": "Python缓存目录",
                })
                dirnames.remove("__pycache__")
                pycache_count += 1
                if pycache_count > 100:
                    break

            # os.walk 标准剪枝: 原地修改 dirnames, 真正不进入跳过目录
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if time.time() > deadline:
                _log("[SCAN] temp_files 扫描超时截断")
                break

            for filename in filenames:
                for pattern in TEMP_PATTERNS:
                    if re.match(pattern, filename, re.IGNORECASE):
                        full_path = os.path.join(dirpath, filename)
                        # OneDrive占位符保护: lstat 不触发云下载, 大文件跳过
                        try:
                            st = os.lstat(full_path)
                            if st.st_size > MAX_FILE_SIZE:
                                continue
                            file_size = st.st_size
                        except OSError:
                            continue
                        temp_files.append({
                            "type": "temp_file",
                            "name": filename,
                            "path": full_path,
                            "size": file_size,
                            "action": "DELETE",
                            "reason": "临时文件",
                        })
                        break
    except ScanTimeout:
        _log("[SCAN] temp_files 看门狗超时, 返回部分结果")
    finally:
        if armed:
            disarm_watchdog()

    return temp_files


# ============================================================
# 4. 执行整理
# ============================================================
def execute_organize(scan_only: bool = False) -> Dict:
    """执行文件整理"""
    ensure_organizer_tables()
    now = _now()
    stats = {"files_moved": 0, "files_deleted": 0, "dirs_removed": 0,
             "dirs_created": 0, "bytes_freed": 0, "errors": 0}

    # 扫描
    loose = scan_loose_files()
    empty = scan_empty_dirs()
    temps = scan_temp_files()
    all_items = loose + empty + temps

    if scan_only:
        return {**stats, "total_scanned": len(all_items),
                "loose_files": len(loose), "empty_dirs": len(empty),
                "temp_files": len(temps), "items": all_items[:50]}

    import uuid

    # 阶段1: 文件操作 (不持数据库锁, 逐条收集落库记录; 看门狗可中断 OneDrive IO 挂起)
    log_rows = []
    deadline = time.time() + ORGANIZE_DEADLINE
    aborted = False
    armed = arm_watchdog(ORGANIZE_DEADLINE)

    try:
        for item in all_items:
            if time.time() > deadline:
                aborted = True
                _log("[ORGANIZE] 文件操作阶段超时截断, 剩余项跳过")
                break
            path = ""
            try:
                org_id = "ORG-%s" % uuid.uuid4().hex[:10]
                action = item.get("action", "KEEP")
                path = item.get("path", "")

                if action == "DELETE":
                    file_size = item.get("size", 0)
                    # 大文件保护: 防止 OneDrive 占位符触发云下载
                    try:
                        if os.path.getsize(path) > MAX_FILE_SIZE:
                            continue
                    except OSError:
                        continue
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    elif os.path.exists(path):
                        os.remove(path)
                    stats["files_deleted"] += 1
                    stats["bytes_freed"] += file_size
                    log_rows.append((org_id, "DELETE", path, path, "", file_size,
                                     item.get("reason", ""), now))

                elif action == "MOVE":
                    target_dir = item.get("target", "")
                    if not target_dir:
                        continue
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir, exist_ok=True)
                        stats["dirs_created"] += 1

                    filename = os.path.basename(path)
                    dest_path = os.path.join(target_dir, filename)

                    # dest 已存在同名文件: 不覆盖、也不跳过(跳过会让源文件僵在根目录永远无法归档,
                    # 历史上 files_moved 几乎全因此为0)。改为带时间戳的归档名 <stem>_root_<ts><ext>,
                    # 旧文件保留、源文件移入, 零覆盖零丢失。
                    renamed = False
                    if os.path.exists(dest_path):
                        stem, ext = os.path.splitext(filename)
                        ts = datetime.now().strftime("%Y%m%d%H%M%S")
                        dest_path = os.path.join(target_dir, f"{stem}_root_{ts}{ext}")
                        _n = 1
                        while os.path.exists(dest_path):  # 同一秒重复再加序号
                            dest_path = os.path.join(target_dir, f"{stem}_root_{ts}_{_n}{ext}")
                            _n += 1
                        renamed = True

                    if os.path.exists(path):
                        shutil.move(path, dest_path)
                        stats["files_moved"] += 1
                        reason = item.get("reason", "") + (";同名归档" if renamed else "")
                        log_rows.append((org_id, "MOVE", path, path, dest_path,
                                         item.get("size", 0), reason, now))

                elif action == "DELETE_DIR" or item.get("type") == "empty_dir":
                    if os.path.isdir(path) and not os.listdir(path):
                        os.rmdir(path)
                        stats["dirs_removed"] += 1
                        log_rows.append((org_id, "DELETE_DIR", path, path, "", 0,
                                         item.get("reason", "空目录"), now))

            except Exception as e:
                stats["errors"] += 1
                _log(f"[ORGANIZE] error: {e} path={path}")
    except ScanTimeout:
        aborted = True
        _log("[ORGANIZE] 文件操作阶段看门狗超时截断")
    finally:
        if armed:
            disarm_watchdog()

    # 阶段2: 短事务集中落库 (busy_timeout + 看门狗保护, 失败不影响已完成的文件操作)
    try:
        db_armed = arm_watchdog(30)
        try:
            with _LOCK:
                conn = sqlite3.connect(APP_DB, timeout=30)
                try:
                    conn.execute("PRAGMA busy_timeout=5000")
                    if log_rows:
                        conn.executemany(
                            """INSERT OR IGNORE INTO mt_file_organize_log
                            (organize_id, action, file_path, from_path, to_path, file_size, reason, organized_at)
                            VALUES (?,?,?,?,?,?,?,?)""", log_rows)

                    today = now[:10]
                    row = conn.execute(
                        "SELECT id FROM mt_file_organize_stats WHERE date=?", (today,)
                    ).fetchone()
                    if row:
                        conn.execute(
                            """UPDATE mt_file_organize_stats SET
                            files_moved=files_moved+?, files_deleted=files_deleted+?,
                            dirs_removed=dirs_removed+?, dirs_created=dirs_created+?,
                            bytes_freed=bytes_freed+?, updated_at=? WHERE id=?""",
                            (stats["files_moved"], stats["files_deleted"],
                             stats["dirs_removed"], stats["dirs_created"],
                             stats["bytes_freed"], now, row[0]))
                    else:
                        conn.execute(
                            """INSERT INTO mt_file_organize_stats
                            (date, files_moved, files_deleted, dirs_removed, dirs_created, bytes_freed, updated_at)
                            VALUES (?,?,?,?,?,?,?)""",
                            (today, stats["files_moved"], stats["files_deleted"],
                             stats["dirs_removed"], stats["dirs_created"],
                             stats["bytes_freed"], now))
                    conn.commit()
                finally:
                    conn.close()
        except ScanTimeout:
            _log("[ORGANIZE] 落库看门狗超时(30s), 文件操作已生效, 落库延迟到下轮")
        finally:
            if db_armed:
                disarm_watchdog()
    except sqlite3.Error as e:
        _log(f"[ORGANIZE] 落库失败(文件操作已生效): {e}")

    if aborted:
        stats["aborted_timeout"] = True
    _log(f"[ORGANIZE] moved={stats['files_moved']} deleted={stats['files_deleted']} "
         f"dirs_removed={stats['dirs_removed']} bytes_freed={stats['bytes_freed']} "
         f"aborted={aborted}")
    return {**stats, "total_scanned": len(all_items)}


# ============================================================
# 4b. 系统级自动清理 (仙女座 patrol 队)
# ============================================================
def cleanup_system_temp() -> Dict:
    """清理系统级临时目录: /tmp/*.py / /tmp/*.sh / ~/Library/Caches/.DS_Store 等"""
    import time as _t
    now = _t.time()
    result = {"dirs_scanned": 0, "files_deleted": 0, "bytes_freed": 0, "errors": 0, "items": []}
    for dir_path, rules in SYSTEM_TEMP_DIRS:
        if not os.path.isdir(dir_path):
            continue
        result["dirs_scanned"] += 1
        try:
            for name in os.listdir(dir_path):
                full = os.path.join(dir_path, name)
                if not os.path.isfile(full):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in rules:
                    continue
                try:
                    age = now - os.path.getmtime(full)
                    max_age = rules[ext]
                    if max_age == 0 or age > max_age:
                        size = os.path.getsize(full)
                        os.remove(full)
                        result["files_deleted"] += 1
                        result["bytes_freed"] += size
                        result["items"].append({"action": "SYS_TEMP", "name": name, "reason": f"系统临时文件 age={int(age)}s>max={max_age}s"})
                except OSError as e:
                    result["errors"] += 1
                    _log(f"[SYS_TEMP] ERR {full}: {e}")
        except PermissionError as e:
            _log(f"[SYS_TEMP] SKIP {dir_path}: {e}")
    _log(f"[SYS_TEMP] scanned={result['dirs_scanned']} deleted={result['files_deleted']} bytes={result['bytes_freed']}")
    return result


def cleanup_orphan_terminals() -> Dict:
    """清理孤儿后台终端进程: 超时 Flask 子进程 / 重复 daemon / 残留 tail"""
    import subprocess
    import signal as _sig
    result = {"patterns_checked": 0, "processes_killed": 0, "errors": 0, "items": []}
    for pattern, cfg in ORPHAN_PROCESS_PATTERNS:
        result["patterns_checked"] += 1
        try:
            out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
            pids = [int(p) for p in out.stdout.strip().split("\n") if p.strip().isdigit()]
            if not pids:
                continue
            # max_instances: 保留最老的 N 个, 杀多余的
            if "max_instances" in cfg and len(pids) > cfg["max_instances"]:
                keep_n = cfg["max_instances"]
                kill_pids = pids[keep_n:]
            elif "max_age_sec" in cfg:
                # 简单策略: 全部匹配都 kill (patrol 每 30min 跑, 不会频繁杀)
                kill_pids = pids
            else:
                kill_pids = []
            for pid in kill_pids:
                try:
                    os.kill(pid, _sig.SIGTERM)
                    result["processes_killed"] += 1
                    result["items"].append({"action": "SIGTERM", "pid": pid, "pattern": pattern})
                    _log(f"[ORPHAN] SIGTERM pid={pid} pattern={pattern}")
                except OSError:
                    pass  # 已退出
        except Exception as e:
            result["errors"] += 1
    _log(f"[ORPHAN] checked={result['patterns_checked']} killed={result['processes_killed']}")
    return result


def cleanup_pycache_globally() -> Dict:
    """全局 __pycache__ + .pyc 清理 (项目内, 排除 .git/venv/node_modules)"""
    result = {"pycache_removed": 0, "pyc_removed": 0, "bytes_freed": 0, "errors": 0}
    for base in PYCACHE_SCAN_DIRS:
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, topdown=True):
            # 剪枝
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.git')]
            # __pycache__ 目录
            if os.path.basename(dirpath) == "__pycache__":
                try:
                    size = sum(os.path.getsize(os.path.join(dirpath, f)) for f in os.listdir(dirpath))
                    shutil.rmtree(dirpath, ignore_errors=True)
                    result["pycache_removed"] += 1
                    result["bytes_freed"] += size
                except OSError:
                    result["errors"] += 1
            # 独立 .pyc 文件
            for f in filenames:
                if f.endswith(".pyc"):
                    fp = os.path.join(dirpath, f)
                    try:
                        result["bytes_freed"] += os.path.getsize(fp)
                        os.remove(fp)
                        result["pyc_removed"] += 1
                    except OSError:
                        result["errors"] += 1
    _log(f"[PYCACHE] dirs={result['pycache_removed']} files={result['pyc_removed']} bytes={result['bytes_freed']}")
    return result


def run_system_cleanup() -> Dict:
    """仙女座 patrol 队主入口: 串起三个系统级清理"""
    _log("[SYSTEM_CLEANUP] === 仙女座 patrol 队接管 系统级清理 ===")
    t1 = cleanup_system_temp()
    t2 = cleanup_orphan_terminals()
    t3 = cleanup_pycache_globally()
    total = {
        "total_files_deleted": t1["files_deleted"] + t3["pycache_removed"],
        "total_processes_killed": t2["processes_killed"],
        "total_bytes_freed": t1["bytes_freed"] + t3["bytes_freed"],
        "system_temp": t1,
        "orphan_terminals": t2,
        "pycache": t3,
    }
    # 落库
    try:
        ensure_organizer_tables()
        conn = sqlite3.connect(APP_DB)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO mt_file_organize_log (action, path, reason, size, detail) VALUES (?,?,?,?,?)",
            ("SYSTEM_CLEANUP", "/system", "仙女座patrol自动清理",
             total["total_bytes_freed"],
             json.dumps({"sys_temp": t1["files_deleted"], "pycache": t3["pycache_removed"],
                         "py_files": t3["pyc_removed"], "processes": t2["processes_killed"]}, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f"[SYSTEM_CLEANUP] DB ERR: {e}")
    _log(f"[SYSTEM_CLEANUP] DONE files={total['total_files_deleted']} procs={total['total_processes_killed']} bytes={total['total_bytes_freed']}")
    return total


# ============================================================
# 5. 查看历史
# ============================================================
def get_status() -> Dict:
    ensure_organizer_tables()
    with _LOCK:
        conn = sqlite3.connect(APP_DB, timeout=30)
        total_logs = conn.execute("SELECT COUNT(*) FROM mt_file_organize_log").fetchone()[0]

        today = _now()[:10]
        today_row = conn.execute(
            "SELECT files_moved, files_deleted, dirs_removed, dirs_created, bytes_freed FROM mt_file_organize_stats WHERE date=?",
            (today,)
        ).fetchone()

        total_row = conn.execute(
            "SELECT SUM(files_moved), SUM(files_deleted), SUM(dirs_removed), SUM(dirs_created), SUM(bytes_freed) FROM mt_file_organize_stats"
        ).fetchone()

        # 最近10条记录
        recent = conn.execute(
            "SELECT organize_id, action, file_path, reason, organized_at FROM mt_file_organize_log ORDER BY organized_at DESC LIMIT 10"
        ).fetchall()

        conn.close()

    return {
        "total_logs": total_logs,
        "today": {
            "files_moved": today_row[0] if today_row else 0,
            "files_deleted": today_row[1] if today_row else 0,
            "dirs_removed": today_row[2] if today_row else 0,
            "dirs_created": today_row[3] if today_row else 0,
            "bytes_freed": today_row[4] if today_row else 0,
        },
        "total": {
            "files_moved": total_row[0] or 0,
            "files_deleted": total_row[1] or 0,
            "dirs_removed": total_row[2] or 0,
            "dirs_created": total_row[3] or 0,
            "bytes_freed": total_row[4] or 0,
        },
        "recent": [{"id": r[0], "action": r[1], "path": r[2],
                     "reason": r[3], "at": r[4]} for r in recent],
    }


# ============================================================
# 6. CLI守护
# ============================================================
class FileOrganizerDaemon:
    @staticmethod
    def read_pid():
        if not os.path.exists(PID_FILE):
            return None
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            return None

    @staticmethod
    def clear_pid():
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    @staticmethod
    def start():
        existing = FileOrganizerDaemon.read_pid()
        if existing:
            print(f"[STATUS] RUNNING pid={existing}")
            return
        ensure_organizer_tables()
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        def _term(signum, frame):
            _log("[DAEMON] SIGTERM")
            FileOrganizerDaemon.clear_pid()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _term)
        signal.signal(signal.SIGINT, _term)
        _log(f"[DAEMON] START pid={os.getpid()} interval={SCAN_INTERVAL}s")
        cycle = 0
        execute_organize(scan_only=False)
        while True:
            time.sleep(SCAN_INTERVAL)
            cycle += 1
            try:
                execute_organize(scan_only=False)
                # 每 3 轮 (约 30min) 跑一次系统级清理 + 冰山仙女座瘦身
                if cycle % 3 == 0:
                    try:
                        run_system_cleanup()
                    except Exception as e:
                        _log(f"[DAEMON] SYSTEM_CLEANUP ERR: {e}")
            except Exception as e:
                _log(f"[DAEMON] ERROR: {e}")

    @staticmethod
    def stop():
        pid = FileOrganizerDaemon.read_pid()
        if not pid:
            print("[STATUS] STOPPED")
            return
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        FileOrganizerDaemon.clear_pid()
        print("[STATUS] STOPPED")


def _acquire_single_instance():
    """CLI模式防重入: flock 独占锁, 上一轮未结束则本次直接退出 (防cron堆积)"""
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        _log("[CLI] 上一轮整理仍在运行, 本次跳过 (防堆积)")
        print("[SKIP] 上一轮整理仍在运行, 本次跳过")
        sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1].lower()
    if cmd == "start":
        FileOrganizerDaemon.start()
    elif cmd == "stop":
        FileOrganizerDaemon.stop()
    elif cmd == "scan":
        _lock_fh = _acquire_single_instance()
        r = execute_organize(scan_only=True)
        print(f"{'='*60}")
        print(f"  File Organizer Scan Report")
        print(f"{'='*60}")
        print(f"  Total scanned:    {r['total_scanned']}")
        print(f"  Loose files:      {r['loose_files']}")
        print(f"  Empty dirs:       {r['empty_dirs']}")
        print(f"  Temp files:       {r['temp_files']}")
        print(f"{'='*60}")
        if r.get("items"):
            print(f"  Items (first 50):")
            for item in r["items"]:
                action = item.get("action", "?")
                name = item.get("name", os.path.basename(item.get("path", "")))
                reason = item.get("reason", "")
                size = item.get("size", 0)
                print(f"    [{action:6s}] {name:40s} {reason} ({size}B)")
    elif cmd == "organize":
        _lock_fh = _acquire_single_instance()
        r = execute_organize(scan_only=False)
        print(f"{'='*60}")
        print(f"  File Organize Result")
        print(f"{'='*60}")
        print(f"  Files moved:     {r['files_moved']}")
        print(f"  Files deleted:    {r['files_deleted']}")
        print(f"  Dirs removed:     {r['dirs_removed']}")
        print(f"  Dirs created:     {r['dirs_created']}")
        print(f"  Bytes freed:      {r['bytes_freed']:,}")
        print(f"  Errors:           {r['errors']}")
        print(f"  Total scanned:    {r['total_scanned']}")
    elif cmd == "status":
        s = get_status()
        print(f"{'='*60}")
        print(f"  File Organizer Status")
        print(f"{'='*60}")
        print(f"  Total log entries: {s['total_logs']}")
        print(f"{'='*60}")
        print(f"  Today:")
        t = s["today"]
        print(f"    Files moved:    {t['files_moved']}")
        print(f"    Files deleted:  {t['files_deleted']}")
        print(f"    Dirs removed:   {t['dirs_removed']}")
        print(f"    Bytes freed:    {t['bytes_freed']:,}")
        print(f"{'='*60}")
        total = s["total"]
        print(f"  All-time:")
        print(f"    Files moved:    {total['files_moved']}")
        print(f"    Files deleted:  {total['files_deleted']}")
        print(f"    Dirs removed:   {total['dirs_removed']}")
        print(f"    Bytes freed:    {total['bytes_freed']:,}")
        print(f"{'='*60}")
        print(f"  Recent 10 actions:")
        for r in s["recent"]:
            print(f"    [{r['action']:10s}] {r['path'][:50]:50s} {r['reason']}")
    else:
        print(f"  未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()

# auto_repair: ensure env-first PROD DB
try:
    from engines._common.db_resolver import get_app_db
    APP_DB = get_app_db()
except Exception:
    pass
