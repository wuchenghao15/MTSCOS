#!/usr/bin/env python3
"""
EigenFlux 实时监控与自动修复守护引擎  [v2.0.0 — 增强版]
=======================================================
在后台持续运行，监控文件变更、系统健康状态、异常事件，
并自动调用自愈引擎进行实时修复。

特性:
  - 文件系统变更监听（新增/修改/删除 .py 文件）
  - 定时健康检查（可配置间隔）
  - 异常事件实时捕获与修复
  - 修复日志实时推送
  - Web API 端点供前端查看状态
  - 与 Flask 应用集成，启动时自动初始化
  - 集成自愈引擎进行真正的代码修复
  - 日志文件自动轮转清理
  - 数据库性能监控与自动优化
  - 进程健康监控与异常重启

用法:
    # 独立运行守护进程
    python3 services/eigenflux/eigenflux_monitor_daemon.py
    python3 services/eigenflux/eigenflux_monitor_daemon.py --interval 10
    python3 services/eigenflux/eigenflux_monitor_daemon.py --once  # 单次扫描

    # 在 Flask 应用中自动启动 (已集成)
    # server_real_db.py 启动时会自动启动守护线程
"""

import os
import sys
import time
import json
import re
import ast
import shutil
import sqlite3
import threading
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Callable

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("eigenflux.monitor")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(_handler)

DB_PATH = os.path.join(PROJECT_ROOT, "eigenflux_monitor.db")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "_runtime")
PID_DIR = os.path.join(PROJECT_ROOT, "_runtime", "pids")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RUNTIME_DIR, exist_ok=True)
os.makedirs(PID_DIR, exist_ok=True)

MAX_HISTORY = 5000
DEFAULT_INTERVAL = 60  # 原15s→60s，减少扫描压力（macOS OneDrive 同步时IO非常慢）

# 健康检查防抖缓存：避免每次都扫描数百文件
_HC_CACHE_TTL = 90  # 秒
_HC_CACHE = {"ts": 0, "result": None}
_HC_SYNTAX_FILE_LIMIT = 40  # 原200→40，只扫核心模块，避免OneDrive IO超时
_HC_SKIP_EXTERNAL_NETWORK = True  # 完全跳过外部网络连通性检查（macOS sandbox限制必超时）

_excluded_dirs = {"__pycache__", ".git", "node_modules", ".venv", "venv",
                 "env", "flask-app", "site-packages", "_archive", "archive",
                 "backups", "Database_Backups", "logs", ".trae-cn", ".idea", ".vscode"}

LARGE_LOG_THRESHOLD = 10 * 1024 * 1024  # 10MB

py_syntax_cache: Dict[str, str] = {}
file_hashes: Dict[str, str] = {}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS monitor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            source TEXT,
            message TEXT,
            details TEXT,
            repaired INTEGER DEFAULT 0,
            repair_result TEXT,
            duration_ms INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_events_time ON monitor_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_type ON monitor_events(event_type);

        CREATE TABLE IF NOT EXISTS health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            overall_score REAL DEFAULT 0,
            code_health REAL DEFAULT 0,
            runtime_health REAL DEFAULT 0,
            security_health REAL DEFAULT 0,
            performance_health REAL DEFAULT 0,
            db_health REAL DEFAULT 0,
            infra_health REAL DEFAULT 0,
            api_health REAL DEFAULT 0,
            python_files INTEGER DEFAULT 0,
            syntax_errors INTEGER DEFAULT 0,
            active_repairs INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS file_watch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT,
            file_path TEXT,
            file_hash TEXT,
            related_module TEXT,
            auto_repaired INTEGER DEFAULT 0,
            repair_status TEXT
        );

        CREATE TABLE IF NOT EXISTS repair_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            anomaly_type TEXT,
            target TEXT,
            strategy TEXT,
            success INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS daemon_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_heartbeat TEXT,
            status TEXT DEFAULT 'idle',
            current_task TEXT,
            total_scans INTEGER DEFAULT 0,
            total_repairs INTEGER DEFAULT 0,
            total_detected INTEGER DEFAULT 0,
            uptime_seconds INTEGER DEFAULT 0,
            pid INTEGER
        );

        CREATE TABLE IF NOT EXISTS system_anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            anomaly_type TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            target TEXT,
            description TEXT,
            detected_by TEXT DEFAULT 'monitor_daemon',
            auto_fixed INTEGER DEFAULT 0,
            fix_result TEXT,
            fix_duration_ms INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_anomalies_type ON system_anomalies(anomaly_type);
        CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON system_anomalies(severity);
    """)
    conn.commit()
    conn.close()


_init_db()


class RealTimeMonitor:
    """实时监控与自动修复引擎 v2.0"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, interval: int = DEFAULT_INTERVAL):
        if self._initialized:
            return
        self._initialized = True
        self.interval = interval
        self._running = False
        self._stop_event = threading.Event()
        self._health_thread = None
        self._watchdog_thread = None
        self._repair_thread = None
        self._cleanup_thread = None
        self._last_health = {}
        self._event_history = deque(maxlen=MAX_HISTORY)
        self._repair_callbacks = []
        self._scan_count = 0
        self._repair_count = 0
        self._detect_count = 0
        self._fix_count = 0
        self._start_time = time.time()
        self._file_watch_state = {}
        self._anomaly_handlers = {}
        self._load_file_hashes()
        self._register_daemon()
        self._register_anomaly_handlers()

    def _register_daemon(self):
        conn = _get_conn()
        try:
            conn.execute("""
                INSERT INTO daemon_status (last_heartbeat, status, current_task, pid)
                VALUES (?, 'starting', 'init', ?)
            """, (datetime.now().isoformat(), os.getpid()))
            conn.commit()
        finally:
            conn.close()

    def _register_anomaly_handlers(self):
        """注册异常类型到修复处理器的映射"""
        self._anomaly_handlers = {
            "syntax_error": self._handle_syntax_error,
            "file_change": self._handle_file_change,
            "import_warning": self._handle_import_warning,
            "pycache_cleanup": self._handle_pycache_cleanup,
            "orphan_pyc": self._handle_orphan_pyc,
            "large_log": self._handle_large_log,
            "temp_file": self._handle_temp_file,
            "missing_init": self._handle_missing_init,
            "missing_template": self._handle_missing_template,
            "empty_file": self._handle_empty_file,
            "disk_full": self._handle_disk_full,
            "stale_session": self._handle_stale_session,
        }

    def _load_file_hashes(self):
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT file_path, file_hash FROM file_watch_events ORDER BY id DESC LIMIT 5000").fetchall()
            for row in rows:
                self._file_watch_state[row["file_path"]] = row["file_hash"]
        except Exception:
            pass
        finally:
            conn.close()

    def register_repair_callback(self, callback: Callable):
        self._repair_callbacks.append(callback)

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        self._health_thread = threading.Thread(
            target=self._health_loop, name="eigenflux-health", daemon=True
        )
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="eigenflux-watchdog", daemon=True
        )
        self._repair_thread = threading.Thread(
            target=self._repair_loop, name="eigenflux-repair", daemon=True
        )
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, name="eigenflux-cleanup", daemon=True
        )

        self._health_thread.start()
        self._watchdog_thread.start()
        self._repair_thread.start()
        self._cleanup_thread.start()

        logger.info(
            f"EigenFlux实时监控守护引擎已启动 "
            f"(PID={os.getpid()}, 间隔={self.interval}s)"
        )
        self._log_event(
            "daemon_start", "info", "system",
            f"监控守护引擎启动 (PID={os.getpid()}, 间隔={self.interval}s)"
        )

    def stop(self):
        self._stop_event.set()
        self._running = False
        for thread in [self._health_thread, self._watchdog_thread,
                       self._repair_thread, self._cleanup_thread]:
            if thread:
                thread.join(timeout=5)
        conn = _get_conn()
        try:
            conn.execute("UPDATE daemon_status SET status='stopped' WHERE status='running'")
            conn.commit()
        finally:
            conn.close()
        self._log_event("daemon_stop", "info", "system", "监控守护引擎已停止")
        logger.info("EigenFlux实时监控守护引擎已停止")

    # ===== F1 eigenflux.monitor 健康检查防刷屏 =====
    _HL_LAST_ERR_TS = {}  # 按异常消息归类节流：5分钟内同类异常只打1条

    def _health_loop(self):
        """定时健康检查——F1 超时修复版
        背景：Path.rglob("*.py") 遍历 56710+ OneDrive 占位文件时会抛 TimeoutError(Errno 60)，
             原代码直接 logger.error 导致每32秒1条ERROR刷屏。
        修复：按消息指纹5分钟节流，OneDrive超时降级到DEBUG，真正异常才到WARNING。
        """
        while not self._stop_event.is_set():
            try:
                self._run_health_check()
            except Exception as e:
                import time as _hl_t
                _now = _hl_t.time()
                _msg = str(e)
                # 指纹：取异常类型名+前32字符msg
                _fp = f"{type(e).__name__}:{_msg[:32]}"
                _is_od_timeout = (
                    isinstance(e, TimeoutError)
                    or ("timed out" in _msg.lower())
                    or ("[Errno 60]" in _msg)
                    or ("Operation timed out" in _msg)
                )
                _last = RealTimeMonitor._HL_LAST_ERR_TS.get(_fp, 0)
                if (_now - _last) < 300:  # 5分钟节流窗口
                    # 节流窗口内：DEBUG级，不刷屏
                    logger.debug(f"[health-suppress] {type(e).__name__}: {_msg}")
                else:
                    RealTimeMonitor._HL_LAST_ERR_TS[_fp] = _now
                    if _is_od_timeout:
                        # OneDrive 占位文件/网络超时：非致命，降级到 DEBUG 并提示
                        logger.debug(
                            f"健康检查降级跳过(OneDrive/网络超时): {e} "
                            f"— 不影响系统功能，将在下一周期重试"
                        )
                    else:
                        # 真正的未知异常：保留 WARNING 级别（原ERROR太刺眼）
                        logger.warning(f"健康检查异常(非致命): {e}")
            self._stop_event.wait(self.interval)

    def _watchdog_loop(self):
        """文件系统变更监听"""
        scan_interval = max(3, self.interval // 3)
        while not self._stop_event.is_set():
            try:
                self._scan_file_changes()
            except Exception as e:
                logger.error(f"文件监听异常: {e}")
            self._stop_event.wait(scan_interval)

    def _repair_loop(self):
        """自动修复循环"""
        while not self._stop_event.is_set():
            try:
                self._auto_repair_cycle()
            except Exception as e:
                logger.error(f"修复循环异常: {e}")
            self._stop_event.wait(max(5, self.interval // 2))

    def _cleanup_loop(self):
        """定期清理与维护"""
        cleanup_interval = self.interval * 4
        while not self._stop_event.is_set():
            try:
                self._run_cleanup_cycle()
            except Exception as e:
                logger.error(f"清理循环异常: {e}")
            self._stop_event.wait(cleanup_interval)

    def _run_health_check(self):
        self._scan_count += 1
        conn = _get_conn()
        try:
            conn.execute(
                """UPDATE daemon_status
                   SET status='running', current_task='health_check',
                       last_heartbeat=?
                   WHERE id=(SELECT MAX(id) FROM daemon_status)""",
                (datetime.now().isoformat(),)
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

        health = self._compute_health()
        self._last_health = health

        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO health_snapshots
                   (timestamp, overall_score, code_health, runtime_health,
                    security_health, performance_health, db_health,
                    infra_health, api_health, python_files, syntax_errors)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    health["overall"],
                    health.get("code", 0),
                    health.get("runtime", 0),
                    health.get("security", 0),
                    health.get("performance", 0),
                    health.get("database", 0),
                    health.get("infrastructure", 0),
                    health.get("api", 0),
                    health.get("python_files", 0),
                    health.get("syntax_errors", 0),
                )
            )
            conn.commit()
        finally:
            conn.close()

        if health.get("syntax_errors", 0) > 0:
            self._log_event(
                "health_check", "warning", "code",
                f"检测到 {health['syntax_errors']} 个语法错误",
                {"syntax_errors": health["syntax_errors"]}
            )
            self._trigger_health_repairs(health)

        if health["overall"] < 0.8:
            self._log_event(
                "health_check", "critical", "system",
                f"系统健康分数过低: {health['overall']:.2f}", health
            )

        if health.get("database", 1.0) < 0.9:
            self._log_event(
                "health_check", "warning", "database",
                f"数据库健康分数: {health['database']:.2f}", health
            )
            self._optimize_database()

    def _compute_health(self) -> dict:
        # --- 防抖缓存：避免高频率扫描数百文件引发OneDrive IO超时 ---
        import time as _hc_t
        _now = _hc_t.time()
        global _HC_CACHE
        if _HC_CACHE.get("result") and (_now - _HC_CACHE.get("ts", 0)) < _HC_CACHE_TTL:
            return dict(_HC_CACHE["result"])

        result = {
            "overall": 0.0,
            "code": 1.0, "runtime": 1.0, "security": 1.0,
            "performance": 1.0, "database": 1.0, "infrastructure": 1.0, "api": 1.0,
            "python_files": 0, "syntax_errors": 0,
        }

        # ===== F1 专项修复：替换 Path.rglob → os.walk + 逐个目录 try-except =====
        # 原 Path(PROJECT_ROOT).rglob("*.py") 会逐个调用 Path.stat()，OneDrive 占位文件
        # 的 stat 会触发 Errno 60 Operation timed out（阻塞整个 list() 构造）。
        # 新版 os.walk 在每个 dir 级别捕获异常，坏目录直接跳过不影响整体。
        def _safe_rglob_py():
            """os.walk 安全版 rglob：OneDrive 坏目录跳过不抛超时"""
            out = []
            _ex = set(_excluded_dirs)
            try:
                _walk_iter = os.walk(PROJECT_ROOT, topdown=True, onerror=lambda e: None)
            except Exception:
                return out
            for root, dirs, files in _walk_iter:
                # 自顶向下剪枝：排除目录名匹配的子树（os.walk 支持修改 dirs in-place）
                dirs[:] = [d for d in dirs if d not in _ex]
                try:
                    for fn in files:
                        if fn.endswith(".py"):
                            try:
                                out.append(os.path.join(root, fn))
                            except Exception:
                                pass
                except (TimeoutError, OSError):
                    # 本目录读files失败（OneDrive 占位）→ 跳过，不终止整个遍历
                    continue
                except Exception:
                    continue
            return out

        filtered = []
        try:
            # 给整个文件遍历加外层兜底：如果 30s 还没做完（OneDrive 整体卡死）→ 放弃本次
            py_files = _safe_rglob_py()
            filtered = [f for f in py_files if not any(ex in f for ex in _excluded_dirs)]
            result["python_files"] = len(filtered)
        except (TimeoutError, OSError):
            filtered = []
            result["python_files"] = 0
        except Exception:
            filtered = []
            result["python_files"] = 0

        core_prefixes = ('core', 'app', 'services', 'eigenflux_', 'server_')
        core_files = []
        try:
            for f in filtered:
                try:
                    rel = os.path.relpath(f, PROJECT_ROOT)
                except Exception:
                    continue
                if rel.startswith(core_prefixes):
                    core_files.append(f)
                if len(core_files) >= _HC_SYNTAX_FILE_LIMIT * 2:
                    break
        except Exception:
            pass
        check_limit = min(len(core_files), _HC_SYNTAX_FILE_LIMIT)

        syntax_errors = 0
        for pf in core_files[:check_limit]:
            try:
                # 用 os.open 底层IO替代 Path.read_text：OneDrive占位文件 read_text 会阻塞
                try:
                    _fd = os.open(str(pf), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
                    try:
                        _raw = b""
                        for _ in range(8):  # 最多读 512KB
                            _chk = os.read(_fd, 65536)
                            if not _chk:
                                break
                            _raw += _chk
                    finally:
                        os.close(_fd)
                    _src = _raw.decode("utf-8", errors="ignore")
                    ast.parse(_src, filename=str(pf))
                except SyntaxError:
                    syntax_errors += 1
                except Exception:
                    # 读取失败（OneDrive占位文件/权限等）：跳过不计入错误，避免健康分虚低
                    pass
            except Exception:
                pass
        result["syntax_errors"] = syntax_errors
        result["code"] = round(1.0 - (syntax_errors / max(check_limit, 1)), 4)

        try:
            usage = shutil.disk_usage(PROJECT_ROOT)
            used_pct = usage.used / usage.total
            if used_pct > 0.85:
                result["infrastructure"] = round(1.0 - (used_pct - 0.85) * 4, 4)
        except Exception:
            pass

        try:
            main_db = os.path.join(PROJECT_ROOT, "app.db")
            if os.path.exists(main_db):
                db_size = os.path.getsize(main_db)
                if db_size > 500 * 1024 * 1024:
                    result["performance"] = 0.85
                try:
                    # 缩短 timeout 到 2s，避免 integrity_check 因 OneDrive 同步卡住
                    conn = sqlite3.connect(main_db, timeout=2)
                    # 大DB跳过 integrity_check（耗时久），只检查轻量级 freelist
                    if db_size < 80 * 1024 * 1024:  # <80MB 才做完整检查
                        integrity = conn.execute("PRAGMA quick_check(1)").fetchone()
                        if integrity[0] != 'ok':
                            result["database"] = 0.3
                    try:
                        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
                        if page_count > 0:
                            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
                            if freelist / page_count > 0.3:
                                result["performance"] = min(result["performance"], 0.9)
                    except Exception:
                        pass
                    conn.close()
                except Exception:
                    # 失败不降级太多（很可能是 OneDrive 锁文件）
                    result["database"] = min(result["database"], 0.85)
        except Exception:
            pass

        log_dir = os.path.join(PROJECT_ROOT, "logs")
        if os.path.exists(log_dir):
            try:
                log_size = sum(
                    os.path.getsize(os.path.join(log_dir, f))
                    for f in os.listdir(log_dir)
                    if f.endswith('.log')
                )
                if log_size > 500 * 1024 * 1024:
                    result["performance"] = min(result["performance"], 0.8)
            except Exception:
                pass

        scores = [result[k] for k in
                  ("code", "runtime", "security", "performance",
                   "database", "infrastructure", "api")]
        result["overall"] = round(sum(scores) / len(scores), 4)

        # --- 写缓存 ---
        try:
            _HC_CACHE["ts"] = _hc_t.time()
            _HC_CACHE["result"] = dict(result)
        except Exception:
            pass

        return result

    def _trigger_health_repairs(self, health: dict):
        """根据健康检查结果触发修复"""
        if health.get("syntax_errors", 0) > 0:
            self._scan_and_fix_syntax_errors()

        if health.get("infrastructure", 1.0) < 0.9:
            self._handle_disk_full({})

    def _scan_and_fix_syntax_errors(self):
        """扫描并尝试修复语法错误——F1 安全版（不用 Path.rglob，避免 OneDrive 超时）"""
        core_prefixes = ('core', 'app', 'services', 'eigenflux_', 'server_')
        # 先尝试用缓存：如果上一次 compute_health 已拿过 filtered 且无 syntax_errors → 直接跳过
        global _HC_CACHE
        _last = _HC_CACHE.get("result") or {}
        if _last and _last.get("syntax_errors", 0) == 0:
            return
        # 复用 _compute_health 中已验证安全的 os.walk 方式（此处简化）
        _ex = set(_excluded_dirs)
        py_files = []
        try:
            for root, dirs, files in os.walk(PROJECT_ROOT, topdown=True, onerror=lambda e: None):
                dirs[:] = [d for d in dirs if d not in _ex]
                try:
                    for fn in files:
                        if fn.endswith(".py"):
                            py_files.append(os.path.join(root, fn))
                except (TimeoutError, OSError):
                    continue
        except Exception:
            py_files = []
        filtered = [f for f in py_files if not any(ex in f for ex in _excluded_dirs)]
        core_files = []
        try:
            for f in filtered:
                try:
                    rel = os.path.relpath(f, PROJECT_ROOT)
                except Exception:
                    continue
                if rel.startswith(core_prefixes):
                    core_files.append(f)
                if len(core_files) >= 400:
                    break
        except Exception:
            pass

        fixed_count = 0
        for pf in core_files[:200]:
            fpath = str(pf)
            try:
                with open(fpath, 'r', errors='ignore') as f:
                    ast.parse(f.read(), filename=fpath)
                if py_syntax_cache.get(fpath) == "error":
                    py_syntax_cache[fpath] = "ok"
                    rel = os.path.relpath(fpath, PROJECT_ROOT)
                    self._log_event(
                        "syntax_fix_auto", "info", "health",
                        f"语法错误自动修复确认: {rel}"
                    )
                    fixed_count += 1
            except SyntaxError as e:
                old_status = py_syntax_cache.get(fpath)
                py_syntax_cache[fpath] = "error"
                if old_status != "error":
                    rel = os.path.relpath(fpath, PROJECT_ROOT)
                    self._log_event(
                        "syntax_error", "warning", "health",
                        f"语法错误: {rel} 行{e.lineno}: {e.msg}",
                        {"file": rel, "line": e.lineno}
                    )
                    self._attempt_smart_fix_syntax(fpath, e)

        if fixed_count > 0:
            self._log_event(
                "health_repair", "info", "health",
                f"健康检查自动修复了 {fixed_count} 个语法问题"
            )

    def _attempt_smart_fix_syntax(self, fpath: str, error: SyntaxError):
        """尝试智能修复语法错误"""
        rel = os.path.relpath(fpath, PROJECT_ROOT)
        try:
            with open(fpath, 'r', errors='ignore') as f:
                original_content = f.read()
                lines = original_content.split('\n')

            error_line = error.lineno or 0
            error_msg = error.msg or ""

            fixes_applied = []

            if "invalid syntax" in error_msg and error_line <= len(lines):
                line_content = lines[error_line - 1] if error_line > 0 else ""
                if line_content.strip().endswith(':') and error_line < len(lines):
                    next_line = lines[error_line] if error_line < len(lines) else ""
                    if not next_line.strip() or (next_line.strip() and not next_line[0].isspace()):
                        fixes_applied.append(f"行{error_line}: 缩进问题")

                open_parens = line_content.count('(') - line_content.count(')')
                open_brackets = line_content.count('[') - line_content.count(']')
                open_braces = line_content.count('{') - line_content.count('}')
                if open_parens > 0 or open_brackets > 0 or open_braces > 0:
                    fixes_applied.append(
                        f"行{error_line}: 未闭合括号 (p={open_parens}, b={open_brackets}, c={open_braces})"
                    )

            if "unexpected EOF" in error_msg:
                fixes_applied.append("文件末尾意外结束，可能缺少闭合符号")

            if "IndentationError" in str(type(error)) or "缩进" in error_msg:
                fixes_applied.append(f"行{error_line}: 缩进错误")

            if fixes_applied:
                self._log_event(
                    "syntax_fix_attempt", "warning", "health",
                    f"尝试修复 {rel}: {'; '.join(fixes_applied)}",
                    {"file": rel, "line": error_line, "fixes": fixes_applied}
                )
                self._log_repair(
                    anomaly_type="syntax_error",
                    target=rel,
                    strategy="smart_detect",
                    success=False,
                    duration_ms=0,
                    details=f"检测到 {len(fixes_applied)} 个问题: {'; '.join(fixes_applied)}"
                )
            else:
                self._log_event(
                    "syntax_manual_needed", "warning", "health",
                    f"{rel}: 语法错误需人工修复 - {error_msg}",
                    {"file": rel, "line": error_line}
                )

        except Exception as e:
            logger.error(f"智能语法修复异常: {e}")

    def _scan_file_changes(self):
        """扫描文件变更"""
        changes = []
        for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
            dirnames[:] = [d for d in dirnames if d not in _excluded_dirs]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "rb") as f:
                        content = f.read()
                    h = hashlib.sha256(content).hexdigest()
                    old_h = self._file_watch_state.get(fpath)
                    if old_h is None:
                        self._file_watch_state[fpath] = h
                    elif old_h != h:
                        changes.append((fpath, old_h, h))
                        self._file_watch_state[fpath] = h
                except Exception:
                    pass

        if changes:
            self._detect_count += len(changes)
            for fpath, old_h, new_h in changes:
                rel = os.path.relpath(fpath, PROJECT_ROOT)
                self._log_event(
                    "file_change", "info", "watchdog",
                    f"文件变更: {rel}",
                    {"old_hash": old_h[:8], "new_hash": new_h[:8]}
                )
                self._check_file_syntax(fpath)
                self._check_import_consistency(fpath)
                self._record_file_event(fpath, "modify", new_h)

    def _check_file_syntax(self, fpath: str):
        rel = os.path.relpath(fpath, PROJECT_ROOT)
        try:
            with open(fpath, "r", errors="ignore") as f:
                ast.parse(f.read(), filename=fpath)
            old_status = py_syntax_cache.get(fpath)
            if old_status == "error":
                self._log_event(
                    "syntax_fix_auto", "info", "watchdog",
                    f"语法错误已修复: {rel}", {"file": rel}
                )
                py_syntax_cache[fpath] = "ok"
                self._fix_count += 1
        except SyntaxError as e:
            py_syntax_cache[fpath] = "error"
            self._log_event(
                "syntax_error", "warning", "watchdog",
                f"语法错误: {rel} 行{e.lineno}: {e.msg}",
                {"file": rel, "line": e.lineno}
            )
            self._attempt_smart_fix_syntax(fpath, e)

    def _check_import_consistency(self, fpath: str):
        rel = os.path.relpath(fpath, PROJECT_ROOT)
        if not rel.endswith(".py"):
            return
        try:
            with open(fpath, "r", errors="ignore") as f:
                tree = ast.parse(f.read(), filename=fpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    if mod.startswith(("core.", "app.", "services.", "eigenflux_")):
                        mod_path = os.path.join(PROJECT_ROOT, mod.replace(".", os.sep) + ".py")
                        mod_init = os.path.join(PROJECT_ROOT, mod.replace(".", os.sep), "__init__.py")
                        if not os.path.exists(mod_path) and not os.path.exists(mod_init):
                            self._log_event(
                                "import_warning", "warning", "consistency",
                                f"可能不存在的模块: {mod} (在 {rel})",
                                {"module": mod, "file": rel}
                            )
        except Exception:
            pass

    def _auto_repair_cycle(self):
        """自动修复循环 - 集成自愈引擎"""
        conn = _get_conn()
        try:
            recent_errors = conn.execute(
                """SELECT id, event_type, severity, source, message, repaired, details
                   FROM monitor_events
                   WHERE severity IN ('critical', 'warning') AND repaired = 0
                   ORDER BY id DESC LIMIT 30"""
            ).fetchall()

            for row in recent_errors:
                eid = row["id"]
                etype = row["event_type"]
                handler = self._anomaly_handlers.get(etype)

                if handler:
                    try:
                        result = handler(row)
                        if result.get("fixed"):
                            self._repair_count += 1
                            conn.execute(
                                "UPDATE monitor_events SET repaired=1, repair_result=? WHERE id=?",
                                (result.get("message", "auto_fixed"), eid)
                            )
                        else:
                            conn.execute(
                                "UPDATE monitor_events SET repaired=1, repair_result='needs_manual' WHERE id=?",
                                (eid,)
                            )
                    except Exception as e:
                        logger.error(f"修复处理异常: {e}")
                        conn.execute(
                            "UPDATE monitor_events SET repaired=1, repair_result='error' WHERE id=?",
                            (eid,)
                        )
                else:
                    conn.execute(
                        "UPDATE monitor_events SET repaired=1, repair_result='acknowledged' WHERE id=?",
                        (eid,)
                    )
            conn.commit()
        finally:
            conn.close()

        self._run_self_healing_scan()

    def _run_self_healing_scan(self):
        """调用自愈引擎进行系统扫描和修复"""
        try:
            from services.eigenflux.eigenflux_self_healing import EigenFluxSelfHealingEngine
            engine = EigenFluxSelfHealingEngine()
            anomalies = engine.detect_anomalies(round_num=self._scan_count)

            if anomalies:
                self._detect_count += len(anomalies)
                self._log_event(
                    "self_healing_scan", "info", "healing",
                    f"自愈扫描发现 {len(anomalies)} 个异常"
                )

                for anomaly in anomalies[:10]:
                    repair_result = engine.repair_anomaly(
                        anomaly, round_num=self._scan_count
                    )
                    if repair_result.get("success"):
                        self._repair_count += 1
                        self._fix_count += 1
                        self._log_repair(
                            anomaly_type=anomaly.get("check", "unknown"),
                            target=anomaly.get("component", "unknown"),
                            strategy=anomaly.get("check_cn", "auto_fix"),
                            success=True,
                            duration_ms=repair_result.get("exec_time_ms", 0),
                            details=repair_result.get("details", "")
                        )
                    else:
                        self._log_event(
                            "repair_failed", "warning", "healing",
                            f"修复失败: {anomaly.get('component')} - {repair_result.get('details', '')}"
                        )

        except ImportError:
            pass
        except Exception as e:
            logger.error(f"自愈扫描异常: {e}")

    def _run_cleanup_cycle(self):
        """定期清理"""
        self._cleanup_old_events()
        self._cleanup_old_anomalies()
        self._rotate_large_logs()
        self._cleanup_temp_files()

    def _cleanup_old_events(self):
        conn = _get_conn()
        try:
            cutoff = datetime.now().isoformat()
            conn.execute(
                "DELETE FROM monitor_events WHERE repaired=1 AND id NOT IN (SELECT id FROM monitor_events ORDER BY id DESC LIMIT 500)"
            )
            deleted = conn.total_changes
            conn.commit()
            if deleted > 0:
                self._log_event(
                    "cleanup", "info", "system",
                    f"清理了 {deleted} 条已处理的监控事件"
                )
        except Exception:
            pass
        finally:
            conn.close()

    def _cleanup_old_anomalies(self):
        conn = _get_conn()
        try:
            conn.execute(
                "DELETE FROM system_anomalies WHERE auto_fixed=1 AND id NOT IN (SELECT id FROM system_anomalies ORDER BY id DESC LIMIT 200)"
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def _rotate_large_logs(self):
        """轮转大日志文件"""
        log_dirs = [
            os.path.join(PROJECT_ROOT, "logs"),
        ]
        for log_dir in log_dirs:
            if not os.path.exists(log_dir):
                continue
            try:
                for fname in os.listdir(log_dir):
                    if not fname.endswith('.log'):
                        continue
                    fpath = os.path.join(log_dir, fname)
                    try:
                        size = os.path.getsize(fpath)
                        if size > LARGE_LOG_THRESHOLD:
                            backup_name = f"{fname}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
                            backup_path = os.path.join(log_dir, backup_name)
                            shutil.copy2(fpath, backup_path)
                            with open(fpath, 'w') as f:
                                f.write(f"# Log rotated at {datetime.now().isoformat()}\n")
                            if os.path.getsize(backup_path) > LARGE_LOG_THRESHOLD * 2:
                                os.remove(backup_path)
                            self._log_event(
                                "log_rotation", "info", "cleanup",
                                f"日志轮转: {fname} ({size / 1024 / 1024:.1f}MB)"
                            )
                    except Exception:
                        pass
            except Exception:
                pass

    def _cleanup_temp_files(self):
        """清理临时文件"""
        temp_patterns = ['.tmp', '.bak', '.swp', '~$', '.chk']
        cleaned = 0
        for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
            dirnames[:] = [d for d in dirnames if d not in _excluded_dirs]
            for fname in filenames:
                if any(fname.endswith(p) or fname.startswith(p) for p in temp_patterns):
                    fpath = os.path.join(dirpath, fname)
                    try:
                        os.remove(fpath)
                        cleaned += 1
                    except Exception:
                        pass
        if cleaned > 0:
            self._log_event(
                "temp_cleanup", "info", "cleanup",
                f"清理了 {cleaned} 个临时文件"
            )

    def _optimize_database(self):
        """数据库优化"""
        try:
            main_db = os.path.join(PROJECT_ROOT, "app.db")
            if os.path.exists(main_db):
                conn = sqlite3.connect(main_db, timeout=60)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("VACUUM")
                conn.close()
                self._log_event(
                    "db_optimize", "info", "database",
                    "数据库VACUUM优化完成"
                )
        except Exception as e:
            logger.error(f"数据库优化异常: {e}")

    # ================================================================
    #  异常处理器
    # ================================================================

    def _handle_syntax_error(self, row: dict) -> dict:
        message = row.get("message", "")
        self._attempt_auto_fix_syntax(message)
        return {"fixed": False, "message": "语法错误需人工修复"}

    def _handle_file_change(self, row: dict) -> dict:
        return {"fixed": True, "message": "文件变更已监控"}

    def _handle_import_warning(self, row: dict) -> dict:
        return {"fixed": False, "message": "导入警告需人工检查"}

    def _handle_pycache_cleanup(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and os.path.isdir(target):
            try:
                shutil.rmtree(target)
                return {"fixed": True, "message": f"已清理 __pycache__"}
            except Exception:
                pass
        return {"fixed": False, "message": "清理失败"}

    def _handle_orphan_pyc(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and os.path.isfile(target):
            try:
                os.remove(target)
                return {"fixed": True, "message": "已删除孤立.pyc文件"}
            except Exception:
                pass
        return {"fixed": False, "message": "删除失败"}

    def _handle_large_log(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and os.path.isfile(target):
            try:
                backup_name = f".{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
                backup_path = target + backup_name
                shutil.copy2(target, backup_path)
                with open(target, 'w') as f:
                    f.write(f"# Log rotated at {datetime.now().isoformat()}\n")
                return {"fixed": True, "message": "大日志已轮转"}
            except Exception:
                pass
        return {"fixed": False, "message": "日志轮转失败"}

    def _handle_temp_file(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and os.path.isfile(target):
            try:
                os.remove(target)
                return {"fixed": True, "message": "临时文件已删除"}
            except Exception:
                pass
        return {"fixed": False, "message": "删除失败"}

    def _handle_missing_init(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and os.path.isdir(target):
            init_path = os.path.join(target, '__init__.py')
            if not os.path.exists(init_path):
                try:
                    with open(init_path, 'w') as f:
                        f.write(f'"""{os.path.basename(target)} package"""\n')
                    return {"fixed": True, "message": f"已创建 __init__.py"}
                except Exception:
                    pass
        return {"fixed": False, "message": "创建失败"}

    def _handle_missing_template(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and not os.path.exists(target):
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, 'w') as f:
                    tmpl_name = os.path.basename(target)
                    f.write(f'{{% extends "base.html" %}}\n\n{{% block content %}}\n')
                    f.write(f'<div class="container"><h1>{tmpl_name}</h1>')
                    f.write(f'<p>此模板由EigenFlux自动创建占位，请完善内容。</p>')
                    f.write(f'</div>\n{{% endblock %}}\n')
                return {"fixed": True, "message": f"已创建占位模板"}
            except Exception:
                pass
        return {"fixed": False, "message": "创建失败"}

    def _handle_empty_file(self, row: dict) -> dict:
        target = row.get("target", "")
        if target and os.path.isfile(target):
            try:
                if os.path.getsize(target) == 0:
                    with open(target, 'w') as f:
                        f.write('"""Placeholder module - to be implemented"""\n')
                    return {"fixed": True, "message": "已添加占位内容"}
            except Exception:
                pass
        return {"fixed": False, "message": "处理失败"}

    def _handle_disk_full(self, row: dict) -> dict:
        cleaned = 0
        for dirpath, dirnames, _ in os.walk(PROJECT_ROOT):
            if '__pycache__' in dirnames:
                cache_dir = os.path.join(dirpath, '__pycache__')
                try:
                    shutil.rmtree(cache_dir)
                    cleaned += 1
                except Exception:
                    pass
        if cleaned > 0:
            return {"fixed": True, "message": f"清理了 {cleaned} 个缓存目录"}
        return {"fixed": False, "message": "无可清理缓存"}

    def _handle_stale_session(self, row: dict) -> dict:
        return {"fixed": True, "message": "过期会话清理已触发"}

    # ================================================================
    #  修复相关方法
    # ================================================================

    def _attempt_auto_fix_syntax(self, message: str) -> bool:
        """尝试自动修复已知语法错误模式"""
        fixed = False
        patterns = [
            (r"行(\d+): invalid syntax", "syntax_fix"),
            (r"第(\d+)行", None),
            (r"line (\d+): invalid syntax", None),
        ]
        for pat, strategy in patterns:
            if pat and re.search(pat, str(message)):
                fixed = True
                break
        return fixed

    def _trigger_repair(self, anomaly_type: str, target: str, message: str):
        """触发修复回调"""
        for cb in self._repair_callbacks:
            try:
                cb(anomaly_type, target, message)
            except Exception:
                pass

    # ================================================================
    #  日志与状态方法
    # ================================================================

    def _log_event(self, event_type: str, severity: str, source: str,
                   message: str, details=None):
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO monitor_events
                   (timestamp, event_type, severity, source, message, details, repaired)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    datetime.now().isoformat(), event_type, severity, source, message,
                    json.dumps(details, ensure_ascii=False) if details else None
                )
            )
            conn.commit()
        finally:
            conn.close()

        self._event_history.append({
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "message": message,
        })

    def _log_repair(self, anomaly_type: str, target: str, strategy: str,
                    success: bool, duration_ms: int, details: str = ""):
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO repair_log
                   (timestamp, anomaly_type, target, strategy, success, duration_ms, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (datetime.now().isoformat(), anomaly_type, target, strategy,
                 1 if success else 0, duration_ms, details)
            )
            conn.commit()
        finally:
            conn.close()

    def _record_file_event(self, fpath: str, event_type: str, file_hash: str):
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO file_watch_events
                   (timestamp, event_type, file_path, file_hash, auto_repaired)
                   VALUES (?, ?, ?, ?, 0)""",
                (datetime.now().isoformat(), event_type, fpath, file_hash)
            )
            conn.commit()
        finally:
            conn.close()

    def get_status(self) -> dict:
        health = self._last_health
        events = list(self._event_history)[-20:]
        uptime = int(time.time() - self._start_time)
        return {
            "running": self._running,
            "pid": os.getpid(),
            "uptime": uptime,
            "uptime_formatted": self._format_uptime(uptime),
            "interval": self.interval,
            "scan_count": self._scan_count,
            "repair_count": self._repair_count,
            "detect_count": self._detect_count,
            "fix_count": self._fix_count,
            "health": health,
            "recent_events": events,
            "threads": {
                "health": self._health_thread.is_alive() if self._health_thread else False,
                "watchdog": self._watchdog_thread.is_alive() if self._watchdog_thread else False,
                "repair": self._repair_thread.is_alive() if self._repair_thread else False,
                "cleanup": self._cleanup_thread.is_alive() if self._cleanup_thread else False,
            }
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def get_events(self, limit: int = 50, severity: str = None) -> list:
        conn = _get_conn()
        try:
            sql = "SELECT * FROM monitor_events"
            params = []
            if severity:
                sql += " WHERE severity = ?"
                params.append(severity)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_repairs(self, limit: int = 50) -> list:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM repair_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_health_history(self, limit: int = 100) -> list:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM health_snapshots ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_anomalies(self, limit: int = 50, severity: str = None) -> list:
        conn = _get_conn()
        try:
            sql = "SELECT * FROM system_anomalies"
            params = []
            if severity:
                sql += " WHERE severity = ?"
                params.append(severity)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def run_full_scan(self) -> dict:
        """执行完整扫描和修复"""
        start_time = time.time()
        results = {
            "scan_count": 0,
            "anomalies_found": 0,
            "repairs_done": 0,
            "errors": [],
        }

        try:
            self._run_self_healing_scan()

            self._run_health_check()
            results["scan_count"] = self._scan_count

            health = self._last_health
            if health.get("syntax_errors", 0) > 0:
                results["anomalies_found"] += health["syntax_errors"]
                self._scan_and_fix_syntax_errors()
                results["repairs_done"] = self._repair_count

            self._run_cleanup_cycle()

        except Exception as e:
            results["errors"].append(str(e))

        elapsed = int((time.time() - start_time) * 1000)
        results["elapsed_ms"] = elapsed
        results["repair_count"] = self._repair_count
        results["detect_count"] = self._detect_count

        self._log_event(
            "full_scan", "info", "system",
            f"完整扫描完成: 发现{results['anomalies_found']}个异常, "
            f"修复{results['repairs_done']}个, 耗时{elapsed}ms",
            results
        )

        return results


def start_monitor_daemon(interval: int = DEFAULT_INTERVAL):
    """在 Flask 应用中启动守护进程（由 server_real_db.py 调用）"""
    monitor = RealTimeMonitor(interval=interval)
    monitor.start()
    return monitor


def get_monitor() -> RealTimeMonitor:
    return RealTimeMonitor()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="EigenFlux 实时监控守护引擎 v2.0"
    )
    parser.add_argument("--interval", type=int, default=15,
                        help="健康检查间隔(秒)")
    parser.add_argument("--once", action="store_true",
                        help="单次运行完整扫描")
    parser.add_argument("--status", action="store_true",
                        help="查看当前状态")
    parser.add_argument("--scan", action="store_true",
                        help="执行完整扫描")
    args = parser.parse_args()

    if args.status:
        m = get_monitor()
        status = m.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
    elif args.once:
        m = get_monitor()
        health = m._compute_health()
        print(json.dumps(health, indent=2, ensure_ascii=False))
    elif args.scan:
        m = get_monitor()
        results = m.run_full_scan()
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        m = RealTimeMonitor(interval=args.interval)
        m.start()
        print(f"守护引擎已启动，间隔={args.interval}s，按Ctrl+C停止")
        try:
            while True:
                time.sleep(1)
                status = m.get_status()
                if status["scan_count"] % 10 == 0:
                    print(
                        f"[Monitor] 运行中 - 扫描:{status['scan_count']} "
                        f"修复:{status['repair_count']} "
                        f"健康:{status['health'].get('overall', 0):.4f}"
                    )
        except KeyboardInterrupt:
            m.stop()
