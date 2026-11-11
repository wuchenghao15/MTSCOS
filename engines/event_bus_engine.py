#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Event Bus Engine — 跨系统事件统一调度器
====================================
解决问题: autopilot_v2 S5 broadcast/collab_bus_events 分散在 16 个文件, 无统一入口

核心能力:
1. emit(event_name, source_system, target_system=None, payload={})
   → 写入 mt_collab_bus_events 表 (如果存在) 或 mt_center_evolution_log
2. subscribe(event_name, handler) — 引擎可以注册事件处理函数
3. dispatch_loop() — 后台循环, 轮询未处理事件 → 分发
4. list_events(source, target, since) — 查询事件历史

预定义事件类型:
  ICEBERG_PULSE_COMPLETE    → 冰山意识脉冲完成
  ICEBERG_BINDING_CHANGED   → 冰山阈值/绑定变更
  GOBELIN_SIGNAL_GENERATED  → 古灵阁信号产出
  GOBELIN_TRADE_EXECUTED    → 古灵阁交易执行
  GOBELIN_TEN_EXPERT_DONE   → 十专家会诊完成
  AUTOPILOT_STAGE_COMPLETE  → autopilot 某阶段完成
  AUTOPILOT_HEALTH_ALERT    → autopilot 健康告警
  WEEKEND_SATURDAY_DONE     → 周六大学习完成
  WEEKEND_SUNDAY_DONE       → 周日考试完成
  OLLAMA_MODEL_LOADED       → Ollama 模型加载
  HEALTH_CHECK_FAILED       → 健康检查失败

依赖: SQLite (mt_collab_bus_events 表已存在)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ═══════════════════════════════════════════════════════════════════
# DB 路径解析 (与其他引擎保持一致)
# ═══════════════════════════════════════════════════════════════════
_BASE = Path(__file__).resolve().parent.parent
_PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
_ONEDRIVE_DB = _BASE / "database" / "app.db"
_DB_ENV = os.environ.get('ANDROMEDA_DB') or os.environ.get('APP_DB')
if _DB_ENV and os.path.exists(_DB_ENV):
    _DB_PATH = Path(_DB_ENV)
elif _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
    _DB_PATH = _PROD_LOCAL
else:
    _DB_PATH = _ONEDRIVE_DB


# ═══════════════════════════════════════════════════════════════════
# 预定义事件类型
# ═══════════════════════════════════════════════════════════════════
PREDEFINED_EVENTS = {
    # ── Iceberg ──
    "ICEBERG_PULSE_COMPLETE":     {"system": "iceberg",   "severity": "INFO",  "desc": "冰山意识脉冲完成"},
    "ICEBERG_BINDING_CHANGED":   {"system": "iceberg",   "severity": "INFO",  "desc": "冰山阈值/绑定变更"},
    "ICEBERG_DOMAIN_HEALTH":     {"system": "iceberg",   "severity": "INFO",  "desc": "冰山域健康快照"},

    # ── Gobelin ──
    "GOBELIN_SIGNAL_GENERATED":  {"system": "gobelin",   "severity": "INFO",  "desc": "古灵阁信号产出"},
    "GOBELIN_TRADE_EXECUTED":    {"system": "gobelin",   "severity": "INFO",  "desc": "古灵阁交易执行"},
    "GOBELIN_TEN_EXPERT_DONE":   {"system": "gobelin",   "severity": "INFO",  "desc": "十专家会诊完成"},
    "GOBELIN_DAILY_PNL_DONE":    {"system": "gobelin",   "severity": "INFO",  "desc": "每日PnL汇总完成"},

    # ── Andromeda ──
    "AUTOPILOT_STAGE_COMPLETE":  {"system": "andromeda", "severity": "INFO",  "desc": "autopilot 某阶段完成"},
    "AUTOPILOT_HEALTH_ALERT":    {"system": "andromeda", "severity": "WARN",  "desc": "autopilot 健康告警"},
    "AUTOPILOT_FULL_CYCLE_DONE": {"system": "andromeda", "severity": "INFO",  "desc": "autopilot 完整周期完成"},

    # ── Weekend ──
    "WEEKEND_SATURDAY_DONE":     {"system": "andromeda", "severity": "INFO",  "desc": "周六大学习完成"},
    "WEEKEND_SUNDAY_DONE":       {"system": "andromeda", "severity": "INFO",  "desc": "周日考试完成"},

    # ── Infrastructure ──
    "OLLAMA_MODEL_LOADED":       {"system": "infra",     "severity": "INFO",  "desc": "Ollama 模型加载"},
    "HEALTH_CHECK_FAILED":       {"system": "infra",     "severity": "ERROR", "desc": "健康检查失败"},
    "DAEMON_STARTED":            {"system": "infra",     "severity": "INFO",  "desc": "守护进程启动"},
    "DAEMON_STOPPED":            {"system": "infra",     "severity": "WARN",  "desc": "守护进程停止"},
}


def _get_conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """获取 sqlite 连接 (WAL + busy_timeout)"""
    p = db_path or _DB_PATH
    conn = sqlite3.connect(str(p), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _ensure_table(conn: sqlite3.Connection):
    """确保扩展字段存在 (如果 mt_collab_bus_events 缺少 status/target_system)"""
    # 检查现有列
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_bus_events)").fetchall()]
    # 补齐可能缺失的列 (兼容原有表结构)
    if "target_system" not in cols:
        try: conn.execute("ALTER TABLE mt_collab_bus_events ADD COLUMN target_system TEXT")
        except sqlite3.OperationalError: pass
    if "status" not in cols:
        try: conn.execute("ALTER TABLE mt_collab_bus_events ADD COLUMN status TEXT DEFAULT 'PENDING'")
        except sqlite3.OperationalError: pass
    if "dispatched_at" not in cols:
        try: conn.execute("ALTER TABLE mt_collab_bus_events ADD COLUMN dispatched_at TEXT")
        except sqlite3.OperationalError: pass
    if "error" not in cols:
        try: conn.execute("ALTER TABLE mt_collab_bus_events ADD COLUMN error TEXT")
        except sqlite3.OperationalError: pass
    conn.commit()


# ═══════════════════════════════════════════════════════════════════
# EventBus 核心类
# ═══════════════════════════════════════════════════════════════════
class EventBus:
    """统一跨系统事件总线"""

    _instance: Optional[EventBus] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DB_PATH
        self._handlers: Dict[str, List[Callable]] = {}  # event_name -> [handler_fn]
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._handlers_lock = threading.Lock()
        self._dispatch_count = 0
        self._error_count = 0
        # 确保表结构完整
        try:
            conn = _get_conn(self.db_path)
            _ensure_table(conn)
            conn.close()
        except Exception as e:
            print(f"[EventBus] init warning: {e}")

    @classmethod
    def instance(cls, db_path: Optional[Path] = None) -> EventBus:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
            return cls._instance

    # ── emit ─────────────────────────────────────────────────
    def emit(self,
            event_name: str,
            source_system: str,
            target_system: Optional[str] = None,
            payload: Optional[Dict[str, Any]] = None,
            severity: str = "INFO",
            symbol: Optional[str] = None) -> str:
        """
        发射事件 → 写入 DB → 立即同步 dispatch 给已注册 handler
        返回 event_id
        """
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = payload or {}

        # 尝试查表预定义 severity
        if event_name in PREDEFINED_EVENTS:
            severity = PREDEFINED_EVENTS[event_name].get("severity", severity)

        # 写 DB —— 优先尝试扩展 INSERT, fallback 到原始字段
        written = False
        try:
            conn = _get_conn(self.db_path)
            # 先检查有哪些列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_bus_events)").fetchall()]

            if "target_system" in cols and "status" in cols:
                # 扩展版 INSERT
                conn.execute(
                    """INSERT INTO mt_collab_bus_events
                       (event_id, event_type, source, severity, symbol, payload,
                        target_system, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                    (event_id, event_name, source_system, severity, symbol,
                     json.dumps(payload, ensure_ascii=False), target_system, ts)
                )
            else:
                # 原版 INSERT (无扩展字段)
                conn.execute(
                    """INSERT INTO mt_collab_bus_events
                       (event_id, event_type, source, severity, symbol, payload, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (event_id, event_name, source_system, severity, symbol,
                     json.dumps(payload, ensure_ascii=False), ts)
                )
            conn.commit()
            conn.close()
            written = True
        except Exception as e:
            print(f"[EventBus] emit DB write failed: {e}")
            # fallback: 写 mt_center_evolution_log
            try:
                conn = _get_conn(self.db_path)
                conn.execute(
                    """INSERT INTO mt_center_evolution_log
                       (log_type, source, detail, created_at) VALUES (?, ?, ?, ?)""",
                    (event_name, source_system, json.dumps(payload, ensure_ascii=False), ts)
                )
                conn.commit()
                conn.close()
            except Exception as e2:
                print(f"[EventBus] fallback also failed: {e2}")

        # 同步 dispatch 给 in-memory handlers
        self._dispatch_to_handlers(event_id, event_name, source_system, target_system, payload, severity)
        return event_id

    # ── subscribe ────────────────────────────────────────────
    def subscribe(self, event_name: str, handler: Callable) -> None:
        """注册事件处理器"""
        with self._handlers_lock:
            self._handlers.setdefault(event_name, []).append(handler)

    def unsubscribe(self, event_name: str, handler: Callable) -> None:
        with self._handlers_lock:
            if event_name in self._handlers and handler in self._handlers[event_name]:
                self._handlers[event_name].remove(handler)

    # ── dispatch (in-memory) ─────────────────────────────────
    def _dispatch_to_handlers(self, event_id, event_name, source, target, payload, severity):
        """同步 dispatch 给所有注册的 handlers"""
        with self._handlers_lock:
            # 精确匹配 + 通配
            handlers = list(self._handlers.get(event_name, []))
            handlers += list(self._handlers.get("*", []))

        if not handlers:
            return

        for h in handlers:
            try:
                h({
                    "event_id": event_id,
                    "event_name": event_name,
                    "source": source,
                    "target": target,
                    "payload": payload,
                    "severity": severity,
                    "timestamp": datetime.now().isoformat(),
                })
                self._dispatch_count += 1
            except Exception as e:
                self._error_count += 1
                print(f"[EventBus] handler error for {event_name}: {e}")

    # ── dispatch_loop (后台轮询 PENDING) ────────────────────
    def dispatch_loop(self, interval: int = 30):
        """后台轮询 PENDING 事件 → 分发 → 更新状态"""
        while self._running:
            try:
                self._dispatch_pending_once()
            except Exception as e:
                print(f"[EventBus] dispatch_loop error: {e}")
            time.sleep(interval)

    def _dispatch_pending_once(self):
        conn = _get_conn(self.db_path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_bus_events)").fetchall()]
            if "status" not in cols:
                return  # 原表无状态列, 跳过后台轮询

            rows = conn.execute(
                "SELECT event_id, event_type, source, target_system, payload, severity "
                "FROM mt_collab_bus_events WHERE status='PENDING' "
                "ORDER BY created_at ASC LIMIT 50"
            ).fetchall()

            for row in rows:
                eid, etype, src, tgt, payload_json, sev = row
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except Exception:
                    payload = {"_raw": payload_json}

                self._dispatch_to_handlers(eid, etype, src, tgt, payload, sev)

                # 更新状态
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE mt_collab_bus_events SET status='DISPATCHED', dispatched_at=? WHERE event_id=?",
                    (now, eid)
                )
            conn.commit()
        finally:
            conn.close()

    def start_dispatch_loop(self, interval: int = 30):
        """启动后台分发线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self.dispatch_loop, args=(interval,), daemon=True)
        self._thread.start()

    def stop_dispatch_loop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    # ── 查询 ─────────────────────────────────────────────────
    def list_events(self,
                    source: Optional[str] = None,
                    target: Optional[str] = None,
                    since: Optional[str] = None,
                    event_name: Optional[str] = None,
                    limit: int = 50) -> List[Dict]:
        """查询事件历史"""
        conn = _get_conn(self.db_path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_bus_events)").fetchall()]
            extra_where = []
            params = []

            if source:
                extra_where.append("source = ?")
                params.append(source)
            if event_name:
                extra_where.append("event_type = ?")
                params.append(event_name)
            if since:
                extra_where.append("created_at >= ?")
                params.append(since)
            if target and "target_system" in cols:
                extra_where.append("target_system = ?")
                params.append(target)

            where = ("WHERE " + " AND ".join(extra_where)) if extra_where else ""
            rows = conn.execute(
                f"SELECT event_id, event_type, source, severity, symbol, payload, created_at "
                f"FROM mt_collab_bus_events {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                params + [limit]
            ).fetchall()

            result = []
            for r in rows:
                try:
                    payload = json.loads(r[5]) if r[5] else {}
                except Exception:
                    payload = {"_raw": r[5]}
                result.append({
                    "event_id": r[0],
                    "event_type": r[1],
                    "source": r[2],
                    "severity": r[3],
                    "symbol": r[4],
                    "payload": payload,
                    "created_at": r[6],
                })
            return result
        finally:
            conn.close()

    def stats(self) -> Dict[str, Any]:
        """总线统计"""
        conn = _get_conn(self.db_path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_bus_events)").fetchall()]
            total = conn.execute("SELECT COUNT(*) FROM mt_collab_bus_events").fetchone()[0]

            stats = {
                "total_events": total,
                "dispatch_count": self._dispatch_count,
                "error_count": self._error_count,
                "registered_handlers": sum(len(v) for v in self._handlers.values()),
                "running": self._running,
                "db_path": str(self.db_path),
            }
            if "status" in cols:
                pending = conn.execute("SELECT COUNT(*) FROM mt_collab_bus_events WHERE status='PENDING'").fetchone()[0]
                stats["pending"] = pending
            # 按 source 分组
            rows = conn.execute(
                "SELECT source, COUNT(*) FROM mt_collab_bus_events GROUP BY source"
            ).fetchall()
            stats["by_source"] = {r[0]: r[1] for r in rows}
            return stats
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════════
# 模块级便捷函数 (单例)
# ═══════════════════════════════════════════════════════════════════
_default_bus: Optional[EventBus] = None


def _default() -> EventBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


def emit(event_name: str,
         source_system: str,
         target_system: Optional[str] = None,
         payload: Optional[Dict[str, Any]] = None,
         severity: str = "INFO") -> str:
    """便捷发射函数 (使用默认总线)"""
    return _default().emit(event_name, source_system, target_system, payload, severity)


def subscribe(event_name: str, handler: Callable) -> None:
    _default().subscribe(event_name, handler)


def list_events(source: Optional[str] = None,
                target: Optional[str] = None,
                since: Optional[str] = None,
                event_name: Optional[str] = None,
                limit: int = 50) -> List[Dict]:
    return _default().list_events(source, target, since, event_name, limit)


def stats() -> Dict[str, Any]:
    return _default().stats()


# ═══════════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  EventBus Engine — 自测")
    print("=" * 60)

    bus = EventBus()

    # 注册 handler
    received = []
    def my_handler(evt):
        received.append(evt)
        print(f"  [HANDLER] 收到: {evt['event_name']} from {evt['source']}")

    bus.subscribe("TEST_EVENT", my_handler)
    bus.subscribe("ICEBERG_PULSE_COMPLETE", my_handler)

    # 发射测试事件
    e1 = bus.emit("TEST_EVENT", "andromeda", "gobelin", {"msg": "架构完善测试"})
    e2 = bus.emit("ICEBERG_PULSE_COMPLETE", "iceberg", None, {"health": 0.92})
    e3 = bus.emit("AUTOPILOT_HEALTH_ALERT", "andromeda", None, {"component": "S5", "healthy": True}, severity="WARN")

    print(f"\n发射了 3 个事件: {e1[:16]}... / {e2[:16]}... / {e3[:16]}...")
    print(f"Handler 收到: {len(received)} 个事件")

    # 查 DB
    import sqlite3 as _sq
    c = _sq.connect(str(bus.db_path))
    rows = c.execute(
        "SELECT event_type, source, payload FROM mt_collab_bus_events "
        "ORDER BY rowid DESC LIMIT 5"
    ).fetchall()
    print(f"\nDB 最新 5 条:")
    for r in rows:
        print(f"  {r[0]} [{r[1]}]: {str(r[2])[:80]}")
    total = c.execute("SELECT COUNT(*) FROM mt_collab_bus_events").fetchone()[0]
    print(f"DB 总事件数: {total}")
    c.close()

    print(f"\nStats: {bus.stats()}")
    print("\n✅ EventBus Engine OK")
