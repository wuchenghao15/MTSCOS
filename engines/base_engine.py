#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BaseEngine — 统一引擎基类
====================================
让所有引擎有标准签名 (health_check / emit_event / start / stop / run_loop)

继承 BaseEngine 的引擎自动获得:
  - self.config     → ConfigCenter 实例 (统一配置)
  - self.db_path    → 解析好的 DB 路径
  - self.logger     → 带 system name 的 logger
  - self.emit_event() → 发射事件到 EventBus
  - self.health_check() → 标准健康字典
  - self._running / self._loop_count / self._start_time → 循环状态
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# 默认 system —— 子类覆盖
DEFAULT_SYSTEM = "unknown"


def _resolve_db_path(db_path: Optional[str | Path] = None) -> Path:
    if db_path:
        return Path(db_path)
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    _PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
    _DB_ENV = os.environ.get('ANDROMEDA_DB') or os.environ.get('APP_DB')
    if _DB_ENV and os.path.exists(_DB_ENV):
        return Path(_DB_ENV)
    if _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
        return _PROD_LOCAL
    return _PROJECT_ROOT / "database" / "app.db"


class BaseEngine:
    """统一引擎基类 — 让所有引擎有标准签名"""

    SYSTEM: str = DEFAULT_SYSTEM
    ENGINE_NAME: str = ""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = str(_resolve_db_path(db_path))
        self._running = False
        self._loop_count = 0
        self._start_time: Optional[float] = None
        self._stop_time: Optional[float] = None
        self._lock = threading.Lock()
        self.logger = self._get_logger()

        # 延迟导入 ConfigCenter (避免循环导入)
        self._config = None

    # ── config 延迟加载 ──────────────────────────────────
    @property
    def config(self):
        if self._config is None:
            from engines.centralized_config import ConfigCenter
            self._config = ConfigCenter(self.db_path)
        return self._config

    # ── logger ──────────────────────────────────────────
    def _get_logger(self) -> logging.Logger:
        system = self.SYSTEM or DEFAULT_SYSTEM
        name = f"mtscos.{system}.{self.__class__.__name__}"
        logger = logging.getLogger(name)
        if not logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter(
                '%(asctime)s [%(name)s] %(levelname)s %(message)s'
            ))
            logger.addHandler(h)
            logger.setLevel(logging.INFO)
            # 避免向上传播到 root (导致重复)
            logger.propagate = False
        return logger

    # ── DB 检查 ──────────────────────────────────────────
    def _check_db(self) -> bool:
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.execute("SELECT 1")
            conn.close()
            return True
        except Exception as e:
            self.logger.warning(f"DB check failed: {e}")
            return False

    def _quick_query(self, sql: str, params=()):
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            row = conn.execute(sql, params).fetchone()
            conn.close()
            return row
        except Exception:
            return None

    # ── 生命周期 ──────────────────────────────────────────
    def init(self):
        """Optional: 初始化钩子 (子类覆盖)"""
        pass

    def start(self):
        """启动引擎主循环"""
        self._running = True
        self._start_time = time.time()
        self.logger.info(
            f"[{self.SYSTEM}] {self.__class__.__name__} START "
            f"(db={self.db_path})"
        )
        self.emit_event(
            "DAEMON_STARTED",
            payload={"engine": self.__class__.__name__, "system": self.SYSTEM}
        )

    def stop(self):
        """优雅停机"""
        self._running = False
        self._stop_time = time.time()
        self.logger.info(
            f"[{self.SYSTEM}] {self.__class__.__name__} STOP "
            f"(loops={self._loop_count})"
        )
        self.emit_event(
            "DAEMON_STOPPED",
            payload={"engine": self.__class__.__name__, "system": self.SYSTEM,
                     "loop_count": self._loop_count}
        )

    def run_loop_once(self):
        """单次循环体 — 子类覆盖实现业务"""
        self._loop_count += 1

    def run_loop(self, interval: float = 60):
        """阻塞式循环: start → while running → run_loop_once → sleep"""
        self.start()
        try:
            while self._running:
                try:
                    self.run_loop_once()
                except Exception as e:
                    self.logger.error(f"loop error: {e}", exc_info=True)
                    self.emit_event(
                        "HEALTH_CHECK_FAILED",
                        payload={"engine": self.__class__.__name__,
                                 "error": str(e)[:200]}
                    )
                # 用小 sleep 让 stop() 更快响应
                for _ in range(int(interval * 2)):
                    if not self._running:
                        break
                    time.sleep(0.5)
        finally:
            self.stop()

    # ── 事件发射 ──────────────────────────────────────────
    def emit_event(self,
                   event_name: str,
                   target: Optional[str] = None,
                   payload: Optional[Dict[str, Any]] = None,
                   severity: str = "INFO") -> Optional[str]:
        """Helper: 向 EventBus 发射事件"""
        try:
            from engines.event_bus_engine import emit as _emit
            return _emit(
                event_name=event_name,
                source_system=self.SYSTEM or self.__class__.__name__,
                target_system=target,
                payload=payload or {},
                severity=severity,
            )
        except Exception as e:
            self.logger.debug(f"emit_event fallback: {e}")
            # fallback: 写 mt_center_evolution_log
            try:
                conn = sqlite3.connect(self.db_path, timeout=5)
                conn.execute(
                    "INSERT INTO mt_center_evolution_log "
                    "(log_type, source, detail, created_at) VALUES (?, ?, ?, ?)",
                    (event_name, self.SYSTEM, str(payload or {})[:500],
                     datetime.now().isoformat())
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
            return None

    # ── 健康检查 ──────────────────────────────────────────
    def health_check(self) -> Dict[str, Any]:
        """返回标准健康字典"""
        uptime = 0.0
        if self._start_time:
            end = self._stop_time if self._stop_time else time.time()
            uptime = round(end - self._start_time, 1)

        return {
            "engine": self.__class__.__name__,
            "system": self.SYSTEM,
            "running": self._running,
            "uptime_sec": uptime,
            "loop_count": self._loop_count,
            "db_connected": self._check_db(),
            "db_path": self.db_path,
        }

    # ── __repr__ ──────────────────────────────────────────
    def __repr__(self):
        hc = self.health_check()
        return (
            f"<{self.__class__.__name__} system={self.SYSTEM} "
            f"running={hc['running']} uptime={hc['uptime_sec']}s "
            f"loops={hc['loop_count']}>"
        )
