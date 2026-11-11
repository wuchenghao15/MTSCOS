#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trigger_coordinator.py — 🎛️ 触发器事件开关协调器
==================================================
MTSCOS NERVOUS SYSTEM — 所有中心事件的统一 trigger/switch/coordination 层.

7 大能力:
  1. 触发器注册表     event_type → handler → 优先级 → 开关
  2. 开关面板         全局开关 + 中心级开关 + 事件级开关
  3. 优先级调度       CRITICAL>HIGH>NORMAL>LOW 队列
  4. 节流/限流        token bucket per event type
  5. 事件编排         AND/OR/THEN 组合 (TRIGGER_GATEWAY)
  6. 死信队列         失败事件 → 重试 → 降级 → DLQ
  7. 统一配置中心     替换所有 engines 里的 hardcoded ENABLE_xxx

用法 (任何 engine 都可调用):
    from engines.trigger_coordinator import TriggerCoordinator
    tc = TriggerCoordinator()                      # 自动解析 DB
    tc.fire('TRADE_EXECUTED', 'ledger_engine', {'symbol':'sh600519'}, 'sh600519', 'HIGH')
    tc.emit('RISK_BREACH', source='finance_risk_engine', payload={'level':'CRITICAL'})
    tc.toggle_switch('REAL_TIME_AUDIT', False)
    enabled = tc.get_switch('BRAIN_FEED_ENABLED')
"""

import os
import sys
import json
import uuid
import time
import threading
import sqlite3
import logging
import traceback
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Optional, Union

# 确保 flask-app/ 在 sys.path — 这样 engines.xxx 模块可被正确 import
_FLASK_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _FLASK_APP_DIR not in sys.path:
    sys.path.insert(0, _FLASK_APP_DIR)

logger = logging.getLogger('trigger_coordinator')
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('%(asctime)s [TC] %(message)s'))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════
#  DB PATH 解析 (与 engines._common.db_resolver 一致)
# ═══════════════════════════════════════════════════════════════════════

def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """解析主库路径 — 优先 env > PROD_LOCAL > OneDrive."""
    if db_path and os.path.exists(db_path):
        return db_path
    # env 覆盖
    for env_key in ("ANDROMEDA_DB", "APP_DB", "DATABASE_URL"):
        env_val = os.environ.get(env_key)
        if env_val and os.path.exists(env_val):
            return env_val
    # PROD 本地优先
    prod_local = os.path.expanduser("~/MTSCOS_PROD/flask-app/database/app.db")
    if os.path.exists(prod_local):
        return prod_local
    # OneDrive flask-app/database/app.db
    onedrive = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db')
    if os.path.exists(onedrive):
        return onedrive
    # fallback: engines/app.db / cwd
    for cand in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.db'),
        os.path.join(os.getcwd(), 'database', 'app.db'),
        os.path.join(os.getcwd(), 'app.db'),
    ]:
        if os.path.exists(cand):
            return cand
    return onedrive  # 返回默认，让后续报错清晰


# ═══════════════════════════════════════════════════════════════════════
#  TRIGGER REGISTRY — 所有事件类型 + handlers + 节流 + 冷却
# ═══════════════════════════════════════════════════════════════════════

TRIGGERS: dict = {
    # ── Gobelin 金融事件 ──
    'TRADE_EXECUTED': {
        'priority': 'HIGH',
        'cooldown_ms': 500,
        'switches': ['ledger', 'audit', 'risk', 'attribution', 'brain_feed', 'iceberg'],
        'handlers': {
            'ledger':       {'engine': 'finance_ledger_engine', 'method': '_single_trade_journal', 'enabled': True},
            'audit':        {'engine': 'finance_realtime_audit', 'method': 'audit_trade', 'enabled': True},
            'risk':         {'engine': 'finance_risk_engine', 'method': 'incremental_risk', 'enabled': True},
            'attribution':  {'engine': 'finance_attribution', 'method': 'incremental_attribution', 'enabled': True},
            'brain_feed':   {'engine': 'andromeda_autopilot_v2', 'method': 'S3_feed_trade', 'enabled': True},
            'iceberg':      {'engine': 'auto_empower', 'method': 'generate_trade_question', 'enabled': False},
        },
        'throttle': {'max_per_sec': 50, 'burst': 100},
        'description': '每笔交易执行后触发 — 全链路 6 个 handler',
    },
    'RISK_BREACH': {
        'priority': 'CRITICAL',
        'cooldown_ms': 0,
        'switches': ['alert', 'shield', 'autopilot'],
        'handlers': {
            'alert':    {'engine': 'finance_risk_engine', 'method': 'emit_alert', 'enabled': True},
            'shield':   {'engine': 'shield_daemon', 'method': 'auto_protect', 'enabled': True},
            'autopilot': {'engine': 'andromeda_autopilot_v2', 'method': 'force_S7_repair', 'enabled': True},
        },
        'throttle': {'max_per_sec': 10, 'burst': 20},
        'description': '风控 breach (risk_score >= 75 或 max_drawdown >= 20%)',
    },
    'AUDIT_FAIL': {
        'priority': 'CRITICAL',
        'cooldown_ms': 1000,
        'switches': ['heal', 'alert'],
        'handlers': {
            'heal': {'engine': 'cross_self_heal', 'method': 'apply_heal_chain', 'enabled': True},
            'alert': {'engine': 'shield_daemon', 'method': 'emit_audit_alert', 'enabled': True},
        },
        'throttle': {'max_per_sec': 20, 'burst': 40},
        'description': '实时稽查 FAIL/CRITICAL — 触发自治愈',
    },
    # ── Iceberg 教育事件 ──
    'EXAM_COMPLETED': {
        'priority': 'NORMAL',
        'cooldown_ms': 200,
        'switches': ['hr', 'brain_feed'],
        'handlers': {
            'hr':         {'engine': 'hr_center', 'method': 'update_employee_score', 'enabled': True},
            'brain_feed': {'engine': 'andromeda_autopilot_v2', 'method': 'S3_feed_exam_result', 'enabled': True},
        },
        'throttle': {'max_per_sec': 30, 'burst': 60},
        'description': '考试/测验完成',
    },
    'KNOWLEDGE_CREATED': {
        'priority': 'LOW',
        'cooldown_ms': 0,
        'switches': ['autodev', 'brain_feed'],
        'handlers': {
            'autodev':    {'engine': 'autodev_engine', 'method': 'derive_from_knowledge', 'enabled': True},
            'brain_feed': {'engine': 'andromeda_autopilot_v2', 'method': 'S3_feed_knowledge', 'enabled': True},
        },
        'throttle': {'max_per_sec': 20, 'burst': 40},
        'description': '脑库新知识点入库',
    },
    # ── Autopilot 事件 ──
    'AUTOPILOT_STAGE_COMPLETE': {
        'priority': 'NORMAL',
        'cooldown_ms': 0,
        'switches': ['orchestrator', 'brain_feed'],
        'handlers': {
            'orchestrator': {'engine': 'center_orchestrator', 'method': 'rebalance_after_stage', 'enabled': True},
            'brain_feed':   {'engine': 'andromeda_autopilot_v2', 'method': 'S3_feed_stage_log', 'enabled': True},
        },
        'throttle': {'max_per_sec': 10, 'burst': 20},
        'description': 'Autopilot 7 阶段任一完成',
    },
    # ── 自治愈事件 ──
    'HEAL_APPLIED': {
        'priority': 'NORMAL',
        'cooldown_ms': 0,
        'switches': ['log', 'notify'],
        'handlers': {
            'log':    {'engine': 'center_orchestrator', 'method': 'log_heal_event', 'enabled': True},
            'notify': {'engine': 'notification_center', 'method': 'notify_heal_applied', 'enabled': False},
        },
        'throttle': {'max_per_sec': 20, 'burst': 40},
        'description': '自治愈链执行后',
    },
    # ── EventBus 事件 ──
    'EVENT_DISPATCHED': {
        'priority': 'LOW',
        'cooldown_ms': 0,
        'switches': ['log'],
        'handlers': {
            'log': {'engine': 'collab_bus_engine', 'method': 'record_dispatch', 'enabled': True},
        },
        'throttle': {'max_per_sec': 50, 'burst': 100},
        'description': '协作总线事件已分发 (审计用)',
    },
    # ── 周末事件 ──
    'WEEKEND_SAT_COMPLETE': {
        'priority': 'HIGH',
        'cooldown_ms': 0,
        'switches': ['autodev', 'futuresight', 'report'],
        'handlers': {
            'autodev':     {'engine': 'autodev_engine', 'method': 'weekend_digest', 'enabled': True},
            'futuresight': {'engine': 'autodev_engine', 'method': 'futuresight_weekly', 'enabled': True},
            'report':      {'engine': 'finance_daily_report', 'method': 'weekly_risk_report', 'enabled': False},
        },
        'throttle': {'max_per_sec': 5, 'burst': 10},
        'description': '周六学习大阶段完成',
    },
    'WEEKEND_SUN_COMPLETE': {
        'priority': 'HIGH',
        'cooldown_ms': 0,
        'switches': ['autodev', 'report'],
        'handlers': {
            'autodev': {'engine': 'autodev_engine', 'method': 'sunday_evolve', 'enabled': True},
            'report':  {'engine': 'finance_daily_report', 'method': 'weekly_risk_report', 'enabled': True},
        },
        'throttle': {'max_per_sec': 5, 'burst': 10},
        'description': '周日自治愈+汇报完成',
    },
    # ── 节假日事件 ──
    'HOLIDAY_TRIGGERED': {
        'priority': 'HIGH',
        'cooldown_ms': 0,
        'switches': ['scheduler', 'orchestrator'],
        'handlers': {
            'scheduler':     {'engine': 'holiday_trigger_engine', 'method': 'enter_holiday_mode', 'enabled': True},
            'orchestrator':  {'engine': 'center_orchestrator', 'method': 'holiday_rebalance', 'enabled': True},
        },
        'throttle': {'max_per_sec': 5, 'burst': 10},
        'description': '长假/节日进入 — 调度切换',
    },
    # ── 每日事件 ──
    'DAILY_AUDIT_COMPLETE': {
        'priority': 'HIGH',
        'cooldown_ms': 0,
        'switches': ['bank_daily', 'risk', 'report'],
        'handlers': {
            'bank_daily': {'engine': 'finance_ledger_engine', 'method': 'daily_settlement', 'enabled': True},
            'risk':       {'engine': 'finance_risk_engine', 'method': 'compute_all', 'enabled': True},
            'report':     {'engine': 'finance_daily_report', 'method': 'generate', 'enabled': True},
        },
        'throttle': {'max_per_sec': 10, 'burst': 20},
        'description': '8 阶段稽查完成 — 触发银行全套',
    },
    'DAILY_BANK_COMPLETE': {
        'priority': 'HIGH',
        'cooldown_ms': 0,
        'switches': ['orchestrator', 'brain_feed', 'futuresight'],
        'handlers': {
            'orchestrator': {'engine': 'center_orchestrator', 'method': 'post_bank_rebalance', 'enabled': True},
            'brain_feed':   {'engine': 'andromeda_autopilot_v2', 'method': 'S3_feed_daily_bank', 'enabled': True},
            'futuresight':  {'engine': 'autodev_engine', 'method': 'futuresight_daily', 'enabled': False},
        },
        'throttle': {'max_per_sec': 10, 'burst': 20},
        'description': '银行全套完成 — 编排后处理',
    },
}


# ═══════════════════════════════════════════════════════════════════════
#  GLOBAL SWITCH PANEL — 全局开关 (可运行时修改)
# ═══════════════════════════════════════════════════════════════════════

GLOBAL_SWITCHES: dict = {
    # 核心系统开关
    'EVENT_BUS_ENABLED':     True,
    'TRIGGER_COORD_ENABLED': True,
    'REAL_TIME_AUDIT':       True,
    'AUTO_HEAL_ENABLED':     True,
    'AUTODEV_ENABLED':       True,
    'BRAIN_FEED_ENABLED':    True,
    'AUTOPILOT_LOOP_ENABLED': True,
    'FUTURESIGHT_ENABLED':   True,
    # 节流
    'GLOBAL_THROTTLE_QPS':   100,
    'RETRY_MAX':             3,
    'DEAD_LETTER_QUEUE':     True,
    # 日志
    'EVENT_LOG_LEVEL':       'INFO',
    'LOG_PAYLOAD':           True,
}

PRIORITY_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'NORMAL': 2, 'LOW': 3}


# ═══════════════════════════════════════════════════════════════════════
#  Token Bucket — 真节流实现
# ═══════════════════════════════════════════════════════════════════════

class _TokenBucket:
    """token bucket 令牌桶 — per-event-type 节流."""
    __slots__ = ('capacity', 'refill_rate', 'tokens', 'last_ts', '_lock')

    def __init__(self, max_per_sec: int, burst: int):
        self.capacity = burst
        self.refill_rate = max_per_sec         # 每秒 refill 多少
        self.tokens = float(burst)
        self.last_ts = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, n: float = 1.0) -> bool:
        """尝试获取 n 个 token. 返回 True=通过, False=被节流."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_ts
            if elapsed > 0:
                self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
                self.last_ts = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False


# ═══════════════════════════════════════════════════════════════════════
#  TriggerCoordinator — 主类
# ═══════════════════════════════════════════════════════════════════════

class TriggerCoordinator:
    """🎛️ 触发器事件开关协调器 — MTSCOS NERVOUS SYSTEM 核心."""

    _instance = None
    _instance_lock = threading.Lock()

    # ── 单例 (但允许显式传 db_path 创建独立实例) ──
    def __new__(cls, db_path: Optional[str] = None):
        if db_path is None and cls._instance is not None:
            return cls._instance
        obj = super().__new__(cls)
        if db_path is None:
            cls._instance = obj
        return obj

    def __init__(self, db_path: Optional[str] = None):
        if getattr(self, '_initialized', False):
            return
        self.db_path = _resolve_db_path(db_path)
        self._tbuckets: dict = {}                    # event_type → TokenBucket
        self._cooldown_tracker: dict = {}             # (event_type, symbol) → last_fire_ts_ms
        self._cooldown_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._in_memory_event_log: deque = deque(maxlen=1000)
        self._initialized = True
        self._ensure_tables()
        self._sync_registry_to_db()
        self._sync_global_switches_to_db()

    # ═══════════════════════════════════════════════════════════════
    #  DB helpers
    # ═══════════════════════════════════════════════════════════════

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn, name: str) -> bool:
        try:
            r = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            return r is not None
        except Exception:
            return False

    def _ensure_tables(self):
        """幂等 DDL — 先检查 PRAGMA，避免 ALTER TABLE 报错."""
        ddls = [
            # 1. 触发器注册表
            """CREATE TABLE IF NOT EXISTS mt_trigger_registry (
                trigger_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL UNIQUE,
                priority TEXT DEFAULT 'NORMAL',
                cooldown_ms INTEGER DEFAULT 0,
                handler_count INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                throttle_max_per_sec INTEGER DEFAULT 100,
                throttle_burst INTEGER DEFAULT 200,
                description TEXT,
                registered_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )""",
            # 2. 触发器处理器注册表
            """CREATE TABLE IF NOT EXISTS mt_trigger_handler (
                handler_id TEXT PRIMARY KEY,
                trigger_event_type TEXT NOT NULL,
                handler_key TEXT NOT NULL,
                target_engine TEXT NOT NULL,
                target_method TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                phase INTEGER DEFAULT 0,
                last_executed TEXT,
                last_success INTEGER,
                exec_count INTEGER DEFAULT 0,
                avg_duration_ms REAL DEFAULT 0,
                UNIQUE(trigger_event_type, handler_key)
            )""",
            # 3. 开关面板
            """CREATE TABLE IF NOT EXISTS mt_switch_panel (
                switch_id TEXT PRIMARY KEY,
                switch_name TEXT NOT NULL UNIQUE,
                switch_value TEXT NOT NULL,
                switch_type TEXT DEFAULT 'BOOLEAN',
                category TEXT,
                description TEXT,
                updated_by TEXT DEFAULT 'system',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )""",
            # 4. 事件触发执行日志
            """CREATE TABLE IF NOT EXISTS mt_trigger_execution_log (
                exec_id TEXT PRIMARY KEY,
                event_id TEXT,
                event_type TEXT NOT NULL,
                handler_key TEXT NOT NULL,
                target_engine TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_ms REAL,
                result TEXT,
                error_msg TEXT,
                retry_count INTEGER DEFAULT 0,
                UNIQUE(event_id, handler_key)
            )""",
            # 5. 事件编排门 (AND/OR/THEN)
            """CREATE TABLE IF NOT EXISTS mt_trigger_gate (
                gate_id TEXT PRIMARY KEY,
                gate_name TEXT NOT NULL,
                gate_type TEXT NOT NULL,
                condition_events TEXT NOT NULL,
                output_event TEXT,
                enabled INTEGER DEFAULT 1,
                fired_count INTEGER DEFAULT 0,
                last_fired TEXT,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )""",
            # 6. 死信队列
            """CREATE TABLE IF NOT EXISTS mt_dead_letter_queue (
                dlq_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                source TEXT,
                payload TEXT,
                original_handler TEXT,
                error_msg TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                first_failed TEXT NOT NULL,
                last_failed TEXT,
                resolution TEXT DEFAULT 'PENDING',
                resolved_at TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )""",
            # 7. 节流指标
            """CREATE TABLE IF NOT EXISTS mt_throttle_metrics (
                metric_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                window_start TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                throttled_count INTEGER DEFAULT 0,
                avg_qps REAL DEFAULT 0,
                max_qps REAL DEFAULT 0,
                UNIQUE(event_type, window_start)
            )""",
            # 8. 触发器综合状态
            """CREATE TABLE IF NOT EXISTS mt_trigger_health_check (
                health_id TEXT PRIMARY KEY,
                check_time TEXT DEFAULT (datetime('now','localtime')),
                total_triggers INTEGER DEFAULT 0,
                active_triggers INTEGER DEFAULT 0,
                total_handlers INTEGER DEFAULT 0,
                enabled_handlers INTEGER DEFAULT 0,
                event_count_1h INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0,
                avg_latency_ms REAL DEFAULT 0,
                throttle_events INTEGER DEFAULT 0,
                retry_queue_count INTEGER DEFAULT 0,
                dlq_count INTEGER DEFAULT 0,
                global_switches_json TEXT,
                health_score REAL DEFAULT 0,
                overall_status TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )""",
        ]
        idx_list = [
            "CREATE INDEX IF NOT EXISTS idx_tlog_event ON mt_trigger_execution_log(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_tlog_started ON mt_trigger_execution_log(started_at)",
            "CREATE INDEX IF NOT EXISTS idx_dlq_status ON mt_dead_letter_queue(resolution)",
            "CREATE INDEX IF NOT EXISTS idx_dlq_retry ON mt_dead_letter_queue(retry_count)",
            "CREATE INDEX IF NOT EXISTS idx_tm_window ON mt_throttle_metrics(window_start)",
            "CREATE INDEX IF NOT EXISTS idx_registry_event ON mt_trigger_registry(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_handler_trigger ON mt_trigger_handler(trigger_event_type)",
        ]
        conn = self._connect()
        try:
            for ddl in ddls:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError as e:
                    if 'already exists' not in str(e):
                        logger.warning(f"DDL warn: {e}")
            for idx in idx_list:
                try:
                    conn.execute(idx)
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  注册表同步: 内存 TRIGGERS → DB
    # ═══════════════════════════════════════════════════════════════

    def _sync_registry_to_db(self):
        conn = self._connect()
        try:
            for event_type, cfg in TRIGGERS.items():
                tid = f"TRG-{uuid.uuid5(uuid.NAMESPACE_DNS, event_type).hex[:12]}"
                handlers = cfg.get('handlers', {})
                tmax = cfg.get('throttle', {}).get('max_per_sec', 100)
                tburst = cfg.get('throttle', {}).get('burst', 200)
                try:
                    conn.execute("""
                        INSERT INTO mt_trigger_registry
                            (trigger_id, event_type, priority, cooldown_ms, handler_count,
                             enabled, throttle_max_per_sec, throttle_burst, description, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
                        ON CONFLICT(event_type) DO UPDATE SET
                            priority=excluded.priority,
                            cooldown_ms=excluded.cooldown_ms,
                            handler_count=excluded.handler_count,
                            throttle_max_per_sec=excluded.throttle_max_per_sec,
                            throttle_burst=excluded.throttle_burst,
                            description=excluded.description,
                            updated_at=datetime('now','localtime')
                    """, (tid, event_type, cfg.get('priority', 'NORMAL'),
                          cfg.get('cooldown_ms', 0), len(handlers), 1,
                          tmax, tburst, cfg.get('description', '')))
                except Exception as e:
                    logger.warning(f"sync registry {event_type}: {e}")
                # 同步 handler
                for hkey, hcfg in handlers.items():
                    hid = f"HDL-{uuid.uuid5(uuid.NAMESPACE_DNS, event_type + hkey).hex[:12]}"
                    try:
                        conn.execute("""
                            INSERT INTO mt_trigger_handler
                                (handler_id, trigger_event_type, handler_key, target_engine, target_method, enabled)
                            VALUES (?,?,?,?,?,?)
                            ON CONFLICT(trigger_event_type, handler_key) DO UPDATE SET
                                target_engine=excluded.target_engine,
                                target_method=excluded.target_method,
                                enabled=excluded.enabled
                        """, (hid, event_type, hkey, hcfg.get('engine', ''),
                              hcfg.get('method', ''), 1 if hcfg.get('enabled', True) else 0))
                    except Exception as e:
                        logger.warning(f"sync handler {event_type}.{hkey}: {e}")
                # 初始化 token bucket
                self._tbuckets[event_type] = _TokenBucket(tmax, tburst)
            conn.commit()
            logger.info(f"[TC] registry synced: {len(TRIGGERS)} events → {sum(len(c.get('handlers',{})) for c in TRIGGERS.values())} handlers")
        finally:
            conn.close()

    def _sync_global_switches_to_db(self):
        conn = self._connect()
        try:
            for name, val in GLOBAL_SWITCHES.items():
                sid = f"SW-{uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:12]}"
                # ⚠️ bool 必须先于 int 检查 (Python isinstance(True, int)=True)
                if isinstance(val, bool):
                    stype = 'BOOLEAN'
                elif isinstance(val, (int, float)):
                    stype = 'NUMBER'
                else:
                    stype = 'STRING'
                sval = 'true' if val is True else ('false' if val is False else str(val))
                try:
                    conn.execute("""
                        INSERT INTO mt_switch_panel
                            (switch_id, switch_name, switch_value, switch_type, category, updated_at)
                        VALUES (?,?,?,?,?,datetime('now','localtime'))
                        ON CONFLICT(switch_name) DO UPDATE SET
                            switch_value=excluded.switch_value,
                            switch_type=excluded.switch_type
                    """, (sid, name, sval, stype, 'core'))
                except Exception as e:
                    logger.warning(f"sync switch {name}: {e}")
            conn.commit()
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  开关面板 API
    # ═══════════════════════════════════════════════════════════════

    def get_switch(self, switch_name: str) -> Union[bool, int, float, str]:
        """读取开关值 — DB → 内存默认 → env 覆盖."""
        # 1) env 覆盖 (允许运行时强制 override)
        env_val = os.environ.get(f'MT_SW_{switch_name}')
        if env_val is not None:
            return self._coerce(switch_name, env_val)
        # 2) DB
        conn = self._connect()
        try:
            r = conn.execute(
                "SELECT switch_value, switch_type FROM mt_switch_panel WHERE switch_name=?",
                (switch_name,)
            ).fetchone()
            if r:
                return self._coerce(switch_name, r['switch_value'], r['switch_type'])
        finally:
            conn.close()
        # 3) 内存默认
        return GLOBAL_SWITCHES.get(switch_name, False)

    def _coerce(self, name: str, raw: str, stype: str = None):
        if stype is None:
            # 从 GLOBAL_SWITCHES 推断
            default = GLOBAL_SWITCHES.get(name)
            if isinstance(default, bool):
                stype = 'BOOLEAN'
            elif isinstance(default, (int, float)):
                stype = 'NUMBER'
            else:
                stype = 'STRING'
        if stype == 'BOOLEAN':
            return str(raw).lower() in ('true', '1', 'yes', 'on')
        if stype == 'NUMBER':
            try:
                return int(raw) if str(raw).isdigit() else float(raw)
            except Exception:
                return 0
        return raw

    def toggle_switch(self, switch_name: str, value: Optional[bool] = None) -> dict:
        """切换或设置开关值. value=None 时自动 toggle (仅限 BOOLEAN)."""
        old = self.get_switch(switch_name)
        if value is None:
            if not isinstance(old, bool):
                return {'ok': False, 'error': f'{switch_name} is not BOOLEAN, pass explicit value'}
            value = not old
        conn = self._connect()
        try:
            sid_row = conn.execute(
                "SELECT switch_id FROM mt_switch_panel WHERE switch_name=?", (switch_name,)
            ).fetchone()
            sid = sid_row['switch_id'] if sid_row else f"SW-{uuid.uuid4().hex[:12]}"
            # ⚠️ bool 必须先于 int 检查
            if isinstance(value, bool):
                stype = 'BOOLEAN'
            elif isinstance(value, (int, float)):
                stype = 'NUMBER'
            else:
                stype = 'STRING'
            sval = 'true' if value is True else ('false' if value is False else str(value))
            conn.execute("""
                INSERT INTO mt_switch_panel
                    (switch_id, switch_name, switch_value, switch_type, category, updated_at, updated_by)
                VALUES (?,?,?,?,?,datetime('now','localtime'),'api')
                ON CONFLICT(switch_name) DO UPDATE SET
                    switch_value=excluded.switch_value,
                    updated_at=datetime('now','localtime'), updated_by='api'
            """, (sid, switch_name, sval, stype, 'core'))
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[TC] toggle_switch {switch_name}: {old} → {value}")
        return {'ok': True, 'switch': switch_name, 'old': old, 'new': value}

    def list_switches(self) -> dict:
        """返回所有开关当前值 (DB 优先)."""
        result = {}
        conn = self._connect()
        try:
            rows = conn.execute("SELECT switch_name, switch_value, switch_type FROM mt_switch_panel").fetchall()
            for r in rows:
                result[r['switch_name']] = self._coerce(r['switch_name'], r['switch_value'], r['switch_type'])
        finally:
            conn.close()
        # 内存默认里没出现的也补上
        for k, v in GLOBAL_SWITCHES.items():
            result.setdefault(k, v)
        return result

    # ═══════════════════════════════════════════════════════════════
    #  节流 & 冷却
    # ═══════════════════════════════════════════════════════════════

    def throttle_check(self, event_type: str) -> bool:
        """token bucket 节流检查. 返回 True=通过, False=被节流."""
        # 全局开关 — 全局节流上限
        global_qps = self.get_switch('GLOBAL_THROTTLE_QPS')
        bucket = self._tbuckets.get(event_type)
        if bucket is None:
            # 动态创建
            cfg = TRIGGERS.get(event_type, {}).get('throttle', {'max_per_sec': global_qps, 'burst': global_qps * 2})
            bucket = _TokenBucket(cfg['max_per_sec'], cfg['burst'])
            self._tbuckets[event_type] = bucket
        return bucket.acquire(1.0)

    def _cooldown_ok(self, event_type: str, symbol: Optional[str]) -> bool:
        """冷却检查: 同 event_type + symbol 在 cooldown_ms 内不重复触发."""
        cfg = TRIGGERS.get(event_type, {})
        cd_ms = cfg.get('cooldown_ms', 0) or 0
        if cd_ms <= 0:
            return True
        key = (event_type, symbol or '__all__')
        now_ms = time.monotonic() * 1000
        with self._cooldown_lock:
            last = self._cooldown_tracker.get(key, 0)
            if now_ms - last < cd_ms:
                return False
            self._cooldown_tracker[key] = now_ms
        return True

    # ═══════════════════════════════════════════════════════════════
    #  🔥 fire() — 核心入口
    # ═══════════════════════════════════════════════════════════════

    def fire(self, event_type: str, source: str, payload: dict = None,
             symbol: Optional[str] = None, severity: str = 'NORMAL',
             skip_handlers: Optional[list] = None,
             extra: Optional[dict] = None) -> dict:
        """🔥 触发事件 — 核心入口.

        流程:
          1) TRIGGER_COORD_ENABLED 全局总开关检查
          2) 节流 token bucket
          3) 冷却检查 (同 symbol 不重复)
          4) 事件未知 → 只写总线 + 返回 registered=False
          5) 按 phase/优先级 顺序分发所有 enabled handler
          6) 失败 → retry (最多 RETRY_MAX 次) → DLQ
          7) 触发编排门 (TRIGGER_GATEWAY)
        """
        payload = payload or {}
        extra = extra or {}
        result = {
            'status': 'ok',
            'event_id': None,
            'event_type': event_type,
            'handlers_dispatched': [],
            'handlers_failed': [],
            'skipped_reasons': [],
            'registered': event_type in TRIGGERS,
            'throttled': False,
            'cooldown_skipped': False,
            'emit_to_bus': False,
        }

        # ── 1) 总开关 ──
        if not self.get_switch('TRIGGER_COORD_ENABLED'):
            result['status'] = 'disabled'
            result['skipped_reasons'].append('TRIGGER_COORD_ENABLED=False')
            return result

        # ── 2) 节流 ──
        if not self.throttle_check(event_type):
            result['throttled'] = True
            result['status'] = 'throttled'
            self._record_throttle(event_type)
            return result

        # ── 3) 冷却 ──
        if not self._cooldown_ok(event_type, symbol):
            result['cooldown_skipped'] = True
            result['status'] = 'cooldown'
            return result

        # ── 4) 生成 event_id + 写 collab_bus (如果 EVENT_BUS_ENABLED) ──
        event_id = f"EVT-{uuid.uuid4().hex[:10]}"
        result['event_id'] = event_id

        # 写入 mt_collab_bus_events (桥接)
        if self.get_switch('EVENT_BUS_ENABLED'):
            try:
                self._write_collab_bus(event_id, event_type, source, severity, symbol, payload)
                result['emit_to_bus'] = True
            except Exception as e:
                logger.warning(f"[TC] collab_bus 写入失败: {e}")

        # ── 5) 未注册事件 (只写 bus, 不 dispatch) ──
        if event_type not in TRIGGERS:
            logger.info(f"[TC] unregistered event_type={event_type} source={source} → 只写总线")
            self._in_memory_event_log.append({'event_id': event_id, 'event_type': event_type,
                                              'source': source, 'severity': severity, 'ts': time.time()})
            return result

        cfg = TRIGGERS[event_type]
        handlers = cfg.get('handlers', {})
        # 过滤 enabled + 排除 skip_handlers
        dispatch_queue = []
        for hkey, hcfg in handlers.items():
            if skip_handlers and hkey in skip_handlers:
                result['skipped_reasons'].append(f'{hkey}:skip_list')
                continue
            # handler 级开关 — 读 DB
            h_enabled = self._is_handler_enabled(event_type, hkey, hcfg)
            if not h_enabled:
                result['skipped_reasons'].append(f'{hkey}:disabled')
                continue
            dispatch_queue.append((hkey, hcfg))

        # 按 priority 内顺序 (phase) 排序 — 先 DB 中 phase
        dispatch_queue.sort(key=lambda x: x[1].get('phase', 0))

        # ── 6) 分发所有 handlers ──
        for hkey, hcfg in dispatch_queue:
            h_result = self._dispatch_handler(
                event_id, event_type, source, payload, symbol, severity, hkey, hcfg
            )
            if h_result.get('success'):
                result['handlers_dispatched'].append(hkey)
            else:
                result['handlers_failed'].append({hkey: h_result.get('error')})

        # ── 7) 编排门检查 ──
        self._check_gates(event_type, source, payload)

        # ── 内存日志 ──
        self._in_memory_event_log.append({
            'event_id': event_id, 'event_type': event_type, 'source': source,
            'severity': severity, 'handlers': list(result['handlers_dispatched']),
            'failed': result['handlers_failed'], 'ts': time.time()
        })
        return result

    def emit(self, event_type: str, **kwargs) -> dict:
        """📤 便捷 emit — 给各中心调用的简化接口 (fire 的别名)."""
        return self.fire(
            event_type,
            source=kwargs.pop('source', 'unknown'),
            payload=kwargs.pop('payload', None),
            symbol=kwargs.pop('symbol', None),
            severity=kwargs.pop('severity', 'NORMAL'),
            **kwargs,
        )

    # ═══════════════════════════════════════════════════════════════
    #  handler 实际分发 (带 retry + DLQ)
    # ═══════════════════════════════════════════════════════════════

    def _dispatch_handler(self, event_id, event_type, source, payload, symbol,
                          severity, hkey, hcfg) -> dict:
        target_engine = hcfg.get('engine', '')
        target_method = hcfg.get('method', '')
        max_retry = int(self.get_switch('RETRY_MAX'))

        started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        t0 = time.monotonic()

        def _log_exec(result: str, error_msg: str = '', retry_count: int = 0):
            dur = (time.monotonic() - t0) * 1000
            try:
                conn = self._connect()
                conn.execute("""
                    INSERT OR REPLACE INTO mt_trigger_execution_log
                        (exec_id, event_id, event_type, handler_key, target_engine,
                         started_at, ended_at, duration_ms, result, error_msg, retry_count)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (f"EXE-{event_id}-{hkey}", event_id, event_type, hkey, target_engine,
                      started_at, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                      round(dur, 2), result, error_msg[:500], retry_count))
                # 更新 handler 统计
                conn.execute("""
                    UPDATE mt_trigger_handler
                    SET last_executed=datetime('now','localtime'),
                        last_success=?,
                        exec_count=exec_count+1,
                        avg_duration_ms=CASE WHEN avg_duration_ms=0 THEN ?
                                             ELSE (avg_duration_ms*(exec_count-1)+?)/exec_count END
                    WHERE trigger_event_type=? AND handler_key=?
                """, (1 if result == 'SUCCESS' else 0, round(dur, 2), round(dur, 2), event_type, hkey))
                conn.commit()
            except Exception as e:
                logger.warning(f"[TC] exec_log write fail: {e}")
            finally:
                try: conn.close()
                except Exception: pass

        # 尝试导入 + 调用 (带重试)
        for attempt in range(max_retry + 1):
            try:
                # 动态导入
                mod_name = f"engines.{target_engine}"
                mod = sys.modules.get(mod_name)
                if mod is None:
                    import importlib
                    mod = importlib.import_module(mod_name)
                # 查找方法 (支持模块级函数或类方法)
                fn = getattr(mod, target_method, None)
                if fn is None:
                    # 尝试常见类封装
                    for cls_name in [target_engine.replace('_engine', 'Engine'),
                                    'Engine', 'MainEngine', target_engine.split('_')[0].capitalize() + 'Engine']:
                        cls = getattr(mod, cls_name, None)
                        if cls is not None:
                            # 尝试无参构造 (传 db_path 兜底)
                            try:
                                instance = cls(self.db_path)
                            except TypeError:
                                try: instance = cls()
                                except Exception: continue
                            fn = getattr(instance, target_method, None)
                            if fn is not None:
                                break
                if fn is None:
                    raise ImportError(f"method {target_engine}.{target_method} not found")
                # 调用 — 尝试多态参数 (payload / event_id / symbol / severity)
                try:
                    r = fn(payload or {})
                except TypeError:
                    try: r = fn(payload or {}, symbol)
                    except TypeError:
                        try: r = fn(event_type, payload or {}, symbol, severity)
                        except Exception: r = fn()
                _log_exec('SUCCESS', retry_count=attempt)
                return {'success': True, 'result': r, 'attempts': attempt + 1}

            except Exception as e:
                err_str = f"{type(e).__name__}: {e}"
                logger.warning(f"[TC] handler {event_type}.{hkey} attempt {attempt+1}/{max_retry+1}: {err_str}")
                if attempt < max_retry:
                    time.sleep(0.05 * (attempt + 1))  # 递增 backoff
                    continue
                # 最终失败 → DLQ
                _log_exec('FAIL', err_str, retry_count=attempt)
                if self.get_switch('DEAD_LETTER_QUEUE'):
                    self._enqueue_dlq(event_type, source, payload, hkey, err_str)
                return {'success': False, 'error': err_str, 'attempts': attempt + 1}

    def _is_handler_enabled(self, event_type: str, hkey: str, hcfg: dict) -> bool:
        """handler 级开关 — DB 优先, 回退内存 cfg."""
        # 全局 event_bus 开关
        if not self.get_switch('EVENT_BUS_ENABLED'):
            return False
        conn = self._connect()
        try:
            r = conn.execute(
                "SELECT enabled FROM mt_trigger_handler WHERE trigger_event_type=? AND handler_key=?",
                (event_type, hkey)
            ).fetchone()
            if r:
                return bool(r['enabled'])
        finally:
            conn.close()
        return bool(hcfg.get('enabled', True))

    def _write_collab_bus(self, event_id, event_type, source, severity, symbol, payload):
        """桥接到 mt_collab_bus_events."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO mt_collab_bus_events
                    (event_id, event_type, source, severity, symbol, payload,
                     created_at, status, source_system)
                VALUES (?,?,?,?,?,?,datetime('now','localtime'),'DISPATCHED','trigger_coordinator')
            """, (event_id, event_type, source, severity, symbol or '',
                  json.dumps(payload or {}, ensure_ascii=False)[:2000]))
            conn.commit()
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  编排门 (TRIGGER_GATEWAY): AND/OR/THEN
    # ═══════════════════════════════════════════════════════════════

    def _check_gates(self, fired_event: str, source: str, payload: dict):
        conn = self._connect()
        try:
            gates = conn.execute(
                "SELECT gate_id, gate_name, gate_type, condition_events, output_event, enabled "
                "FROM mt_trigger_gate WHERE enabled=1"
            ).fetchall()
        finally:
            conn.close()
        for g in gates:
            cond = json.loads(g['condition_events']) if isinstance(g['condition_events'], str) else g['condition_events']
            if not isinstance(cond, list) or fired_event not in cond:
                continue
            # 查最近 60s 内 cond 中事件的 fired 次数
            recent = self._query_recent_events(cond, window_sec=60)
            gate_type = g['gate_type']
            triggered = False
            if gate_type == 'AND':
                triggered = all(recent.get(e, 0) > 0 for e in cond)
            elif gate_type == 'OR':
                triggered = any(recent.get(e, 0) > 0 for e in cond)
            elif gate_type == 'THEN':
                # THEN: fired_event 必须是 cond 中最后一个 (顺序触发)
                idx = cond.index(fired_event)
                prev_ok = idx == 0 or all(recent.get(e, 0) > 0 for e in cond[:idx])
                triggered = prev_ok
            if triggered and g['output_event']:
                logger.info(f"[TC] gate {g['gate_name']}({gate_type}) 触发 → emit {g['output_event']}")
                self.fire(g['output_event'], source, payload, severity='NORMAL')
                # 更新 gate 统计
                conn2 = self._connect()
                try:
                    conn2.execute("""
                        UPDATE mt_trigger_gate
                        SET fired_count=fired_count+1, last_fired=datetime('now','localtime')
                        WHERE gate_id=?
                    """, (g['gate_id'],))
                    conn2.commit()
                finally:
                    conn2.close()

    def _query_recent_events(self, event_types: list, window_sec: int = 60) -> dict:
        conn = self._connect()
        try:
            result = {e: 0 for e in event_types}
            placeholders = ','.join('?' * len(event_types))
            rows = conn.execute(
                f"SELECT event_type, COUNT(*) as cnt FROM mt_collab_bus_events "
                f"WHERE event_type IN ({placeholders}) "
                f"AND created_at >= datetime('now','-{window_sec} seconds') "
                f"GROUP BY event_type",
                event_types
            ).fetchall()
            for r in rows:
                result[r['event_type']] = r['cnt']
            return result
        except Exception:
            return {e: 0 for e in event_types}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  死信队列 (DLQ)
    # ═══════════════════════════════════════════════════════════════

    def _enqueue_dlq(self, event_type, source, payload, handler, error_msg):
        conn = self._connect()
        try:
            dlq_id = f"DLQ-{uuid.uuid4().hex[:10]}"
            conn.execute("""
                INSERT INTO mt_dead_letter_queue
                    (dlq_id, event_type, source, payload, original_handler, error_msg,
                     retry_count, max_retries, first_failed, last_failed, resolution)
                VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'),'PENDING')
            """, (dlq_id, event_type, source,
                  json.dumps(payload or {}, ensure_ascii=False)[:2000],
                  handler, error_msg[:1000], 0, int(self.get_switch('RETRY_MAX')) + 2))
            conn.commit()
            logger.warning(f"[TC] DLQ enqueued: {event_type}.{handler} → {error_msg[:80]}")
        finally:
            conn.close()

    def retry_process(self, limit: int = 10) -> dict:
        """处理 DLQ 中 PENDING + 未超 max_retries 的事件."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT * FROM mt_dead_letter_queue
                WHERE resolution='PENDING' AND retry_count < max_retries
                ORDER BY first_failed ASC
                LIMIT ?
            """, (limit,)).fetchall()
        finally:
            conn.close()
        retried = 0
        resolved = 0
        for r in rows:
            payload = {}
            try:
                payload = json.loads(r['payload']) if r['payload'] else {}
            except Exception:
                pass
            try:
                new_r = self.fire(
                    r['event_type'], r['source'] or 'dlq_retry',
                    payload, severity='NORMAL',
                    skip_handlers=[r['original_handler']] if r['original_handler'] else None
                )
                # 更新 DLQ
                conn2 = self._connect()
                try:
                    if new_r.get('status') == 'ok' and r['original_handler'] not in new_r.get('handlers_failed', []):
                        conn2.execute("""
                            UPDATE mt_dead_letter_queue
                            SET resolution='RESOLVED', resolved_at=datetime('now','localtime')
                            WHERE dlq_id=?
                        """, (r['dlq_id'],))
                        resolved += 1
                    else:
                        conn2.execute("""
                            UPDATE mt_dead_letter_queue
                            SET retry_count=retry_count+1,
                                last_failed=datetime('now','localtime')
                            WHERE dlq_id=?
                        """, (r['dlq_id'],))
                        retried += 1
                    conn2.commit()
                finally:
                    conn2.close()
            except Exception as e:
                logger.error(f"[TC] DLQ retry error: {e}")
        return {'retried': retried, 'resolved': resolved, 'checked': len(rows)}

    def dead_letter_process(self, limit: int = 20) -> dict:
        """处理 DLQ 中超 max_retries 的事件 → ABANDONED."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT * FROM mt_dead_letter_queue
                WHERE resolution='PENDING' AND retry_count >= max_retries
                LIMIT ?
            """, (limit,)).fetchall()
            abandoned = 0
            for r in rows:
                conn.execute("""
                    UPDATE mt_dead_letter_queue
                    SET resolution='ABANDONED', resolved_at=datetime('now','localtime')
                    WHERE dlq_id=?
                """, (r['dlq_id'],))
                abandoned += 1
            conn.commit()
            return {'abandoned': abandoned, 'checked': len(rows)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  节流指标
    # ═══════════════════════════════════════════════════════════════

    def _record_throttle(self, event_type: str):
        window = datetime.now().strftime('%Y-%m-%d %H:%M')
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO mt_throttle_metrics
                    (metric_id, event_type, window_start, throttled_count)
                VALUES (?,?,?,1)
                ON CONFLICT(event_type, window_start) DO UPDATE SET
                    throttled_count=throttled_count+1
            """, (f"TM-{uuid.uuid5(uuid.NAMESPACE_DNS, event_type+window).hex[:12]}",
                  event_type, window))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    #  健康检查
    # ═══════════════════════════════════════════════════════════════

    def health_check(self) -> dict:
        """计算综合健康分 + 写入 mt_trigger_health_check."""
        conn = self._connect()
        try:
            total_triggers = len(TRIGGERS)
            active_triggers = conn.execute(
                "SELECT COUNT(*) FROM mt_trigger_registry WHERE enabled=1"
            ).fetchone()[0]
            total_handlers = conn.execute(
                "SELECT COUNT(*) FROM mt_trigger_handler"
            ).fetchone()[0]
            enabled_handlers = conn.execute(
                "SELECT COUNT(*) FROM mt_trigger_handler WHERE enabled=1"
            ).fetchone()[0]
            event_1h = conn.execute(
                "SELECT COUNT(*) FROM mt_collab_bus_events "
                "WHERE created_at >= datetime('now','-1 hour')"
            ).fetchone()[0]
            success_rate_row = conn.execute("""
                SELECT
                    AVG(CASE WHEN result='SUCCESS' THEN 1.0 ELSE 0.0 END) as sr,
                    AVG(duration_ms) as avg_lat,
                    COUNT(*) as total
                FROM mt_trigger_execution_log
                WHERE started_at >= datetime('now','-1 hour')
            """).fetchone()
            success_rate = (success_rate_row['sr'] or 0) * 100
            avg_latency = success_rate_row['avg_lat'] or 0
            throttle_events = conn.execute(
                "SELECT COALESCE(SUM(throttled_count),0) FROM mt_throttle_metrics "
                "WHERE window_start >= datetime('now','-1 hour')"
            ).fetchone()[0]
            retry_q = conn.execute(
                "SELECT COUNT(*) FROM mt_dead_letter_queue "
                "WHERE resolution='PENDING'"
            ).fetchone()[0]
            dlq_count = conn.execute(
                "SELECT COUNT(*) FROM mt_dead_letter_queue"
            ).fetchone()[0]
        finally:
            conn.close()

        # 健康分: success_rate*0.5 + enabled_ratio*0.3 + (1-min(dlq,50)/50)*100*0.2
        enabled_ratio = enabled_handlers / max(total_handlers, 1) * 100
        dlq_penalty = min(dlq_count, 50) / 50 * 100
        health_score = round(success_rate * 0.5 + enabled_ratio * 0.3 + (100 - dlq_penalty) * 0.2, 1)
        if health_score >= 90: status = 'HEALTHY'
        elif health_score >= 70: status = 'DEGRADED'
        else: status = 'CRITICAL'

        health_id = f"HLC-{uuid.uuid4().hex[:10]}"
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO mt_trigger_health_check
                    (health_id, total_triggers, active_triggers, total_handlers, enabled_handlers,
                     event_count_1h, success_rate, avg_latency_ms, throttle_events,
                     retry_queue_count, dlq_count, global_switches_json, health_score, overall_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (health_id, total_triggers, active_triggers, total_handlers, enabled_handlers,
                  event_1h, round(success_rate, 2), round(avg_latency, 2), throttle_events,
                  retry_q, dlq_count,
                  json.dumps(self.list_switches(), ensure_ascii=False),
                  health_score, status))
            conn.commit()
        finally:
            conn.close()

        return {
            'total_triggers': total_triggers, 'active_triggers': active_triggers,
            'total_handlers': total_handlers, 'enabled_handlers': enabled_handlers,
            'event_count_1h': event_1h, 'success_rate': round(success_rate, 2),
            'avg_latency_ms': round(avg_latency, 2), 'throttle_events': throttle_events,
            'retry_queue_count': retry_q, 'dlq_count': dlq_count,
            'health_score': health_score, 'overall_status': status,
        }

    # ═══════════════════════════════════════════════════════════════
    #  协调循环 — cron/daemon 入口
    # ═══════════════════════════════════════════════════════════════

    def run_coordination_loop(self, dry_run: bool = False) -> dict:
        """5 分钟心跳: 扫描未处理事件 + 重试 + 死信 + 健康快照."""
        logger.info("[TC] === coordination_loop START ===")
        report = {'retry': {}, 'dlq': {}, 'health': {}}
        if not dry_run:
            report['retry'] = self.retry_process(limit=20)
            report['dlq'] = self.dead_letter_process(limit=30)
        report['health'] = self.health_check()
        logger.info(f"[TC] coordination_loop done: {json.dumps(report, default=str)}")
        return report


# ═══════════════════════════════════════════════════════════════════════
#  CLI 入口 (脚本自运行时)
# ═══════════════════════════════════════════════════════════════════════

def _self_test(db_path: Optional[str] = None):
    tc = TriggerCoordinator(db_path)
    out = []
    out.append(f"[TC] db_path={tc.db_path}")
    out.append(f"[TC] TRIGGERS: {len(TRIGGERS)} events")
    out.append(f"[TC] GLOBAL_SWITCHES: {len(GLOBAL_SWITCHES)} switches")
    out.append(f"[TC] all registered handlers: {sum(len(c.get('handlers',{})) for c in TRIGGERS.values())}")
    out.append("")
    # 手动 fire 测试
    r1 = tc.fire('TRADE_EXECUTED', 'self_test', {'symbol': 'sh600519', 'qty': 100}, 'sh600519', 'HIGH')
    out.append(f"fire TRADE_EXECUTED: status={r1['status']} dispatched={r1['handlers_dispatched']}")
    r2 = tc.fire('RISK_BREACH', 'self_test', {'level': 'CRITICAL', 'score': 88}, None, 'CRITICAL')
    out.append(f"fire RISK_BREACH: status={r2['status']} dispatched={r2['handlers_dispatched']}")
    r3 = tc.fire('NONEXISTENT_EVENT', 'self_test', {}, None, 'NORMAL')
    out.append(f"fire NONEXISTENT: status={r3['status']} registered={r3['registered']}")
    out.append("")
    # 健康快照
    h = tc.health_check()
    out.append(f"health: score={h['health_score']} status={h['overall_status']}")
    out.append(f"  handlers: {h['enabled_handlers']}/{h['total_handlers']} enabled")
    out.append(f"  events_1h: {h['event_count_1h']} success_rate={h['success_rate']}%")
    print("\n".join(out))
    return out


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='TriggerCoordinator CLI')
    p.add_argument('--db', default=None)
    p.add_argument('--loop', action='store_true', help='运行协调循环 (retry+DLQ+health)')
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--fire', nargs=2, metavar=('EVENT_TYPE', 'SOURCE'))
    p.add_argument('--health', action='store_true')
    p.add_argument('--list-switches', action='store_true')
    p.add_argument('--toggle', nargs=2, metavar=('NAME', 'VALUE'))
    args = p.parse_args()

    tc = TriggerCoordinator(args.db)

    if args.self_test:
        _self_test(args.db)
    elif args.loop:
        print(json.dumps(tc.run_coordination_loop(), ensure_ascii=False, indent=2, default=str))
    elif args.fire:
        r = tc.fire(args.fire[0], args.fire[1])
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    elif args.health:
        print(json.dumps(tc.health_check(), ensure_ascii=False, indent=2, default=str))
    elif args.list_switches:
        for k, v in tc.list_switches().items():
            print(f"  {k:25s}: {v}")
    elif args.toggle:
        name, val = args.toggle
        r = tc.toggle_switch(name, val.lower() in ('true', '1', 'yes') if val.lower() in ('true', 'false', '1', '0') else val)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        _self_test(args.db)
