#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协作总线 (Collaboration Bus) — 多中心事件广播枢纽
══════════════════════════════════════════════════
flow: flow_collab_bus_20261102

## 架构
┌──────────────────────────────────────────────────────────────────┐
│                     CollabBus (Pub/Sub 单例)                      │
│  ┌──────────┐  publish  ┌──────────┐  subscribe  ┌─────────────┐ │
│  │ 市场雷达  │ ────────▶ │ 事件队列  │ ─────────▶ │  N 订阅者   │ │
│  │ (5s poll) │           │ (线程安全)│            │ (带优先级)   │ │
│  └──────────┘           └──────────┘            └─────────────┘ │
└──────────────────────────────────────────────────────────────────┘

## 事件类型 (标准)
- MARKET_TICK       市场正常 tick (每 5s)
- MARKET_ANOMALY    市场异动 (涨跌停/放量/指数波动)
- CRITICAL_ALERT    系统紧急告警 (DB锁/daemon crash)
- CRASH_ALERT       引擎崩溃
- DAEMON_STOPPED    后台线程停止
- VERSION_CHANGE    版本号变更
- SKILL_REPORT      Skill 执行报告
- FAILOVER          DR 切换
- DB_LOCK           DB 锁争用
- PATCH_APPLIED     补丁已应用
- EVENT_CUSTOM      自定义事件

## 订阅中心 (标准7家)
1. medical_center (90)     ← 实时体检
2. version_center (70)     ← 自动 bump 版本
3. sync_center (80)        ← 三方同步
4. dr_center (100)         ← 灾难恢复
5. eigenflux (80)          ← 专家协作
6. brain_memory (50)       ← 复盘脑库 (订阅所有)
7. strategy_center (85)    ← 战略研判

## 市场雷达
- 数据源: 新浪实时行情 (hq.sinajs.cn)
- 轮询周期: 5s
- 异动检测: 涨跌幅>5%, 成交量突变>200%, 指数异动
- 广播: MARKET_TICK (正常), MARKET_ANOMALY (异动)

## REST API (via collab_bus_bp)
- GET  /api/collab-bus/status
- GET  /api/collab-bus/events?limit=50
- GET  /api/collab-bus/subscribers
- GET  /api/collab-bus/radar/cache
- POST /api/collab-bus/publish
- POST /api/collab-bus/start
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
# 路径 & DB
# ═══════════════════════════════════════════════════════════════════
BASE = Path(__file__).resolve().parent.parent

_PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
_ONEDRIVE_DB = BASE / "database" / "app.db"
_DB_ENV = os.environ.get('ANDROMEDA_DB') or os.environ.get('APP_DB')
if _DB_ENV and os.path.exists(_DB_ENV):
    DB_PATH = Path(_DB_ENV)
elif _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
    DB_PATH = _PROD_LOCAL
else:
    DB_PATH = _ONEDRIVE_DB


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now().isoformat()


def _gen_id(prefix: str) -> str:
    import hashlib
    raw = f"{prefix}-{time.time_ns()}-{os.getpid()}"
    return f"{prefix}-{hashlib.md5(raw.encode()).hexdigest()[:10]}"


# ═══════════════════════════════════════════════════════════════════
# §1 DB 表初始化
# ═══════════════════════════════════════════════════════════════════
def ensure_bus_tables() -> None:
    conn = _conn()
    try:
        conn.executescript("""
        -- 协作总线事件日志
        CREATE TABLE IF NOT EXISTS mt_collab_bus_events (
            event_id       TEXT PRIMARY KEY,
            event_type     TEXT NOT NULL,
            source         TEXT NOT NULL,
            severity       TEXT DEFAULT 'INFO',
            symbol         TEXT,
            payload        TEXT DEFAULT '{}',
            subscribers_json TEXT DEFAULT '[]',   -- 所有订阅者响应
            broadcast_ms   INTEGER DEFAULT 0,     -- 广播耗时
            created_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_bus_events_type ON mt_collab_bus_events(event_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_bus_events_sev ON mt_collab_bus_events(severity);

        -- 订阅者注册表
        CREATE TABLE IF NOT EXISTS mt_collab_bus_subscribers (
            subscriber_id   TEXT PRIMARY KEY,
            subscriber_name TEXT NOT NULL,
            subscribe_events TEXT DEFAULT '["*"]',   -- JSON array, "*"=所有
            priority        INTEGER DEFAULT 50,       -- 高优先级先响应
            handler_status  TEXT DEFAULT 'active',   -- active|inactive
            last_heartbeat  TEXT,
            registered_at   TEXT DEFAULT (datetime('now'))
        );

        -- 市场雷达缓存
        CREATE TABLE IF NOT EXISTS mt_market_radar_cache (
            symbol        TEXT PRIMARY KEY,
            name          TEXT,
            price         REAL,
            change_pct    REAL,
            volume        REAL,
            turnover      REAL,
            anomaly_type  TEXT,                       -- NORMAL|LIMIT_UP|LIMIT_DOWN|VOLUME_SPIKE|INDEX_SWING
            anomaly_score REAL DEFAULT 0,             -- 0-100 异动分
            tick_count    INTEGER DEFAULT 0,
            updated_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_radar_anomaly ON mt_market_radar_cache(anomaly_type, anomaly_score);
        """)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §2 CollabBus (Pub/Sub 单例)
# ═══════════════════════════════════════════════════════════════════
class CollabBus:
    """
    协作总线核心: 线程安全的 Pub/Sub 单例
    
    设计:
    - 订阅者 = (id, name, events_filter, priority, handler)
    - publish: 按 priority 降序 → 依次调用 handler → 记录每个订阅者的响应
    - 异常隔离: 某个 handler crash 不影响其他订阅者
    """
    _instance: Optional['CollabBus'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'CollabBus':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._subscribers: Dict[str, Dict[str, Any]] = {}
        self._subscribers_lock = threading.Lock()
        self._publish_count = 0
        self._last_publish_ts = 0.0
        self._total_broadcast_ms = 0.0
    
    # ── 订阅 / 取消 ──
    def subscribe(self, subscriber_id: str, subscriber_name: str,
                  subscribe_events: List[str], event_handler: Callable,
                  priority: int = 50) -> bool:
        """
        注册订阅者
        subscribe_events: ["MARKET_ANOMALY", "CRITICAL_ALERT"] 或 ["*"] 表示所有
        """
        with self._subscribers_lock:
            self._subscribers[subscriber_id] = {
                "subscriber_id": subscriber_id,
                "subscriber_name": subscriber_name,
                "subscribe_events": subscribe_events,
                "handler": event_handler,
                "priority": priority,
                "registered_at": _now_iso(),
                "last_heartbeat": _now_iso(),
            }
        
        # 持久化到 DB
        try:
            conn = _conn()
            conn.execute(
                "INSERT OR REPLACE INTO mt_collab_bus_subscribers "
                "(subscriber_id, subscriber_name, subscribe_events, priority, handler_status) "
                "VALUES (?, ?, ?, ?, 'active')",
                (subscriber_id, subscriber_name,
                 json.dumps(subscribe_events, ensure_ascii=False), priority)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            sys.stderr.write(f"[COLLAB-BUS] 持久化订阅者失败: {e}\n")
        
        sys.stderr.write(f"[COLLAB-BUS] 📨 订阅者已注册: {subscriber_name} (id={subscriber_id}, priority={priority}, events={subscribe_events})\n")
        return True
    
    def unsubscribe(self, subscriber_id: str) -> bool:
        with self._subscribers_lock:
            if subscriber_id in self._subscribers:
                del self._subscribers[subscriber_id]
        try:
            conn = _conn()
            conn.execute("UPDATE mt_collab_bus_subscribers SET handler_status='inactive' WHERE subscriber_id=?",
                        (subscriber_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass
        return True
    
    def list_subscribers(self) -> List[Dict[str, Any]]:
        with self._subscribers_lock:
            return [
                {k: v for k, v in s.items() if k != 'handler'}
                for s in self._subscribers.values()
            ]
    
    # ── 发布事件 ──
    def publish(self, event_type: str, source: str, payload: Dict[str, Any],
                severity: str = 'INFO', symbol: str = "") -> Dict[str, Any]:
        """
        发布事件到总线
        返回: {"event_id": str, "subscribers": [{subscriber_id, status, response_ms, error}]}
        """
        event_id = _gen_id("EVT")
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "severity": severity,
            "symbol": symbol,
            "payload": payload,
            "created_at": _now_iso(),
        }
        
        # 收集匹配的订阅者 (按 priority 降序)
        matched: List[Dict[str, Any]] = []
        with self._subscribers_lock:
            subs = list(self._subscribers.values())
        
        for sub in subs:
            events_filter = sub['subscribe_events']
            if '*' in events_filter or event_type in events_filter:
                matched.append(sub)
        
        # 按 priority 降序
        matched.sort(key=lambda s: s.get('priority', 50), reverse=True)
        
        # 广播到所有匹配订阅者
        subscriber_results: List[Dict[str, Any]] = []
        t0 = time.time()
        
        for sub in matched:
            sub_t0 = time.time()
            try:
                handler = sub['handler']
                if handler:
                    handler(event)
                subscriber_results.append({
                    "subscriber_id": sub['subscriber_id'],
                    "subscriber_name": sub['subscriber_name'],
                    "status": "ok",
                    "response_ms": round((time.time() - sub_t0) * 1000, 1),
                    "error": None,
                })
                # 更新心跳
                sub['last_heartbeat'] = _now_iso()
            except Exception as e:
                subscriber_results.append({
                    "subscriber_id": sub['subscriber_id'],
                    "subscriber_name": sub['subscriber_name'],
                    "status": "error",
                    "response_ms": round((time.time() - sub_t0) * 1000, 1),
                    "error": str(e)[:200],
                })
        
        broadcast_ms = round((time.time() - t0) * 1000, 1)
        self._publish_count += 1
        self._last_publish_ts = time.time()
        self._total_broadcast_ms += broadcast_ms
        
        # 持久化事件
        try:
            conn = _conn()
            conn.execute(
                "INSERT INTO mt_collab_bus_events "
                "(event_id, event_type, source, severity, symbol, payload, subscribers_json, broadcast_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, event_type, source, severity, symbol,
                 json.dumps(payload, ensure_ascii=False),
                 json.dumps(subscriber_results, ensure_ascii=False),
                 broadcast_ms)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            sys.stderr.write(f"[COLLAB-BUS] 持久化事件失败: {e}\n")
        
        sys.stderr.write(
            f"[COLLAB-BUS] 📡 {event_type} ({severity}) → "
            f"{len(matched)}/{len(subs)} 订阅者, 广播耗时={broadcast_ms}ms, "
            f"总发布次数={self._publish_count}"
        )
        
        return {
            "event": event,
            "broadcast_ms": broadcast_ms,
            "matched_subscribers": len(matched),
            "total_subscribers": len(subs),
            "subscriber_results": subscriber_results,
        }
    
    # ── 状态查询 ──
    def get_status(self) -> Dict[str, Any]:
        with self._subscribers_lock:
            sub_count = len(self._subscribers)
        return {
            "publish_count": self._publish_count,
            "subscriber_count": sub_count,
            "last_publish_ts": datetime.fromtimestamp(self._last_publish_ts).isoformat() if self._last_publish_ts else None,
            "avg_broadcast_ms": round(self._total_broadcast_ms / max(1, self._publish_count), 1),
            "uptime": time.time() - (self._last_publish_ts if self._last_publish_ts else time.time()),
        }


def get_collab_bus() -> CollabBus:
    """获取协作总线单例"""
    return CollabBus()


# ═══════════════════════════════════════════════════════════════════
# §3 市场雷达 Daemon (新浪实时行情)
# ═══════════════════════════════════════════════════════════════════
SINA_STOCKS = [
    ("sh600519", "贵州茅台"),
    ("sh600036", "招商银行"),
    ("sz300750", "宁德时代"),
    ("sz000858", "五粮液"),
    ("sh601318", "中国平安"),
    ("sz002594", "比亚迪"),
    ("sh000001", "上证指数"),
    ("sz399006", "创业板指"),
]


class MarketRadarDaemon:
    """
    市场雷达: 每 5s poll 新浪行情 → 异动检测 → 广播
    """
    _instance: Optional['MarketRadarDaemon'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'MarketRadarDaemon':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cycle = 5  # 默认 5s
    
    # ── 生命周期 ──
    def start(self, cycle: int = 5) -> None:
        if self._thread and self._thread.is_alive():
            sys.stderr.write("[RADAR] 已在运行\n")
            return
        self._cycle = max(3, min(30, cycle))
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name='market-radar',
            daemon=True
        )
        self._thread.start()
        sys.stderr.write(f"[RADAR] ✅ 市场雷达启动 (cycle={self._cycle}s, 监控 {len(SINA_STOCKS)} 标的)\n")
    
    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
    
    # ── 核心循环 ──
    def _run_loop(self) -> None:
        sys.stderr.write("[RADAR] loop 开始...")
        while not self._stop_event.is_set():
            try:
                self._poll_and_broadcast()
            except Exception as e:
                sys.stderr.write(f"[RADAR] poll 异常: {e}\n")
            self._stop_event.wait(timeout=self._cycle)
    
    def _poll_and_broadcast(self) -> None:
        """拉取新浪行情 → 异动检测 → 广播"""
        # 构建 URL
        secids = ','.join([s[0] for s in SINA_STOCKS])
        url = f"https://hq.sinajs.cn/list={secids}"
        try:
            import urllib.request
            headers = {
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (MTSCOS-Market-Radar)",
            }
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=3.0)
            raw = resp.read()
            text = raw.decode('gbk', errors='ignore')
            
            # 解析新浪行情 (gbk编码)
            tick_data = {}
            for line in text.strip().split('\n'):
                line = line.strip()
                if not line or '=' not in line:
                    continue
                # var hq_str_sh600519="贵州茅台,1688.00,1670.00,1685.50,...";
                match = re.match(r'var hq_str_(\w+)="(.+?)";', line)
                if not match:
                    continue
                secid = match.group(1)
                fields = match.group(2).split(',')
                if len(fields) < 32:
                    continue
                
                name = fields[0]
                price = float(fields[3]) if fields[3] else 0.0
                prev_close = float(fields[2]) if fields[2] else 0.0
                open_p = float(fields[1]) if fields[1] else 0.0
                high = float(fields[4]) if fields[4] else 0.0
                low = float(fields[5]) if fields[5] else 0.0
                volume = float(fields[8]) if fields[8] else 0.0  # 成交量
                turnover = float(fields[9]) if fields[9] else 0.0  # 成交额
                
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
                
                # 异动检测
                anomaly, anomaly_score = self._detect_anomaly(
                    price, prev_close, change_pct, volume, self._cache.get(secid, {})
                )
                
                tick_data[secid] = {
                    "secid": secid, "name": name,
                    "price": price, "prev_close": prev_close, "open": open_p,
                    "high": high, "low": low,
                    "change_pct": round(change_pct, 2),
                    "volume": volume, "turnover": turnover,
                    "anomaly_type": anomaly, "anomaly_score": anomaly_score,
                    "timestamp": _now_iso(),
                }
                
                # 更新缓存
                self._cache[secid] = tick_data[secid]
                
                # 写 DB
                try:
                    conn = _conn()
                    conn.execute(
                        "INSERT OR REPLACE INTO mt_market_radar_cache "
                        "(symbol, name, price, change_pct, volume, turnover, "
                        "anomaly_type, anomaly_score, tick_count, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(tick_count, 0)+1, ?)",
                        (secid, name, price, change_pct, volume, turnover,
                         anomaly, anomaly_score, _now_iso())
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
            
            # 广播 MARKET_TICK (正常)
            bus = get_collab_bus()
            has_anomaly = any(v['anomaly_type'] != 'NORMAL' for v in tick_data.values())
            
            if has_anomaly:
                # 有异动 → 广播 MARKET_ANOMALY (高优先级)
                anomalies = {k: v for k, v in tick_data.items() if v['anomaly_type'] != 'NORMAL'}
                for secid, data in anomalies.items():
                    bus.publish(
                        event_type='MARKET_ANOMALY',
                        source='market_radar',
                        severity='ALERT',
                        symbol=secid,
                        payload=data,
                    )
                sys.stderr.write(f"[RADAR] 🔴 异动: {len(anomalies)} 个标的\n")
            else:
                # 正常 tick → 低频率广播 (每 10 个 cycle 广播一次, 节省资源)
                if self._tick_count_increment():
                    bus.publish(
                        event_type='MARKET_TICK',
                        source='market_radar',
                        severity='INFO',
                        payload={"summary": f"监控 {len(tick_data)} 标的, 全部正常"},
                    )
                    
        except Exception as e:
            sys.stderr.write(f"[RADAR] poll 失败 (可能网络波动): {e}\n")
    
    def _detect_anomaly(self, price: float, prev_close: float, 
                        change_pct: float, volume: float,
                        prev_cache: Dict[str, Any]) -> Tuple[str, float]:
        """异动检测 → (anomaly_type, anomaly_score 0-100)"""
        anomaly_type = "NORMAL"
        score = 0.0
        
        # 涨跌停: ±10%
        if change_pct >= 9.8:
            anomaly_type = "LIMIT_UP"
            score = 95.0
        elif change_pct <= -9.8:
            anomaly_type = "LIMIT_DOWN"
            score = 95.0
        elif abs(change_pct) >= 5.0:
            anomaly_type = "BIG_MOVE"
            score = 60.0 + abs(change_pct) * 2
        elif abs(change_pct) >= 3.0:
            anomaly_type = "NOTABLE_MOVE"
            score = 30.0 + abs(change_pct) * 2
        
        # 成交量突变 (200%+)
        if prev_cache.get('volume', 0) > 0:
            vol_ratio = volume / prev_cache['volume']
            if vol_ratio >= 2.5:
                if anomaly_type == "NORMAL":
                    anomaly_type = "VOLUME_SPIKE"
                score = max(score, 70.0)
        
        return anomaly_type, min(100.0, round(score, 1))
    
    _counter = 0
    def _tick_count_increment(self) -> bool:
        """每 10 个 tick 返回 True (降频广播 MARKET_TICK)"""
        MarketRadarDaemon._counter += 1
        if MarketRadarDaemon._counter >= 10:
            MarketRadarDaemon._counter = 0
            return True
        return False
    
    def get_cache(self) -> Dict[str, Any]:
        """获取当前缓存"""
        return self._cache.copy()


# ═══════════════════════════════════════════════════════════════════
# §4 标准订阅者注册 (启动时自动注册)
# ═══════════════════════════════════════════════════════════════════
def register_standard_subscribers() -> None:
    """
    注册 5 个内置订阅者 (避免循环导入问题, 用延迟 import)
    """
    bus = get_collab_bus()
    
    # 订阅者1: 版本中心 (动态触发 bump)
    def _on_version_events(event: Dict[str, Any]) -> None:
        sys.stderr.write(f"[COLLAB-BUS → VERSION] 收到: {event.get('event_type')}")
        try:
            from engines.ai_version_center_engine import trigger_version_bump
            trigger_version_bump(event)
        except Exception as e:
            sys.stderr.write(f"[VERSION] 处理事件异常: {e}")
    bus.subscribe(
        subscriber_id="version_center",
        subscriber_name="版本中心",
        subscribe_events=["MARKET_ANOMALY", "CRITICAL_ALERT", "CRASH_ALERT", 
                         "SKILL_REPORT", "FAILOVER", "EVENT_CUSTOM"],
        event_handler=_on_version_events,
        priority=70,
    )
    
    # 订阅者2: 同步中心 (DB 三方同步)
    def _on_sync_events(event: Dict[str, Any]) -> None:
        sys.stderr.write(f"[COLLAB-BUS → SYNC] 收到: {event.get('event_type')}")
        try:
            from engines.db_triple_sync_engine import sync_all
            severity = event.get('severity', 'INFO')
            if severity in ('CRITICAL', 'ALERT'):
                sync_all(dry_run=False)
                sys.stderr.write(f"[SYNC] 三方同步已触发 (原因: {event.get('event_type')})")
        except Exception as e:
            sys.stderr.write(f"[SYNC] 处理事件异常: {e}")
    bus.subscribe(
        subscriber_id="sync_center",
        subscriber_name="同步中心",
        subscribe_events=["CRITICAL_ALERT", "FAILOVER", "DB_LOCK", "MARKET_ANOMALY"],
        event_handler=_on_sync_events,
        priority=80,
    )
    
    # 订阅者3: 医疗中心 (延迟注册, 在医疗中心自身启动时)
    # ⚠️ 医疗中心内部自己注册 (避免循环导入)
    
    # 订阅者4: 复盘脑库 (订阅所有, 用于复盘学习)
    def _on_brain_feed(event: Dict[str, Any]) -> None:
        # 轻量处理: 只记录关键事件
        if event.get('severity') in ('CRITICAL', 'ALERT'):
            sys.stderr.write(f"[COLLAB-BUS → BRAIN] 关键事件入库: {event.get('event_type')}")
    bus.subscribe(
        subscriber_id="brain_memory",
        subscriber_name="复盘反噬脑库",
        subscribe_events=["*"],  # 所有事件
        event_handler=_on_brain_feed,
        priority=50,
    )
    
    # 订阅者5: EigenFlux 专家协作
    def _on_eigenflux(event: Dict[str, Any]) -> None:
        if event.get('event_type') == 'MARKET_ANOMALY':
            sys.stderr.write(f"[COLLAB-BUS → EIGENFLUX] 市场异动, 专家协作启动")
    bus.subscribe(
        subscriber_id="eigenflux",
        subscriber_name="EigenFlux专家协作",
        subscribe_events=["MARKET_ANOMALY", "CRITICAL_ALERT"],
        event_handler=_on_eigenflux,
        priority=80,
    )
    
    # 🆕 2026-11-02: 6 大高频触发中心 (研发/文案/Skill/教育/战略/人事)
    # 订阅者6: 研发中心 (高触发: MARKET_TICK/MARKET_ANOMALY → 新功能研发)
    def _on_rd_events(event: Dict[str, Any]) -> None:
        et = event.get('event_type', '')
        if et in ('MARKET_TICK', 'MARKET_ANOMALY', 'CRITICAL_ALERT', 'SKILL_REPORT'):
            sys.stderr.write(f"[COLLAB-BUS → RD] 触发研发: {et} (source={event.get('source')})")
    bus.subscribe(
        subscriber_id="rd_center",
        subscriber_name="研发中心",
        subscribe_events=["MARKET_TICK", "MARKET_ANOMALY", "CRITICAL_ALERT", "SKILL_REPORT",
                         "VERSION_CHANGE", "EVENT_CUSTOM"],
        event_handler=_on_rd_events,
        priority=85,  # 高优先级, 每次 tick 都触发研发新功能
    )
    
    # 订阅者7: Skill 中心 (高触发: 新 Skill/OpenClaw 开发)
    def _on_skill_events(event: Dict[str, Any]) -> None:
        sys.stderr.write(f"[COLLAB-BUS → SKILL] 触发 Skill/OpenClaw: {event.get('event_type')}")
    bus.subscribe(
        subscriber_id="skill_center",
        subscriber_name="Skill/OpenClaw 中心",
        subscribe_events=["MARKET_ANOMALY", "CRITICAL_ALERT", "SKILL_REPORT",
                         "VERSION_CHANGE", "EVENT_CUSTOM", "CRASH_ALERT"],
        event_handler=_on_skill_events,
        priority=85,
    )
    
    # 订阅者8: 教育中心 (题库更新/教学内容刷新)
    def _on_edu_events(event: Dict[str, Any]) -> None:
        et = event.get('event_type', '')
        if et in ('MARKET_TICK', 'MARKET_ANOMALY', 'VERSION_CHANGE', 'SKILL_REPORT'):
            sys.stderr.write(f"[COLLAB-BUS → EDU] 触发题库/教学更新: {et}")
    bus.subscribe(
        subscriber_id="edu_center",
        subscriber_name="教育题库中心",
        subscribe_events=["MARKET_TICK", "MARKET_ANOMALY", "VERSION_CHANGE", "SKILL_REPORT", "EVENT_CUSTOM"],
        event_handler=_on_edu_events,
        priority=75,
    )
    
    # 订阅者9: 战略中心 (全局研判/进化方向)
    def _on_strategy_events(event: Dict[str, Any]) -> None:
        sys.stderr.write(f"[COLLAB-BUS → STRATEGY] 触发战略研判: {event.get('event_type')}")
    bus.subscribe(
        subscriber_id="strategy_center",
        subscriber_name="战略中心",
        subscribe_events=["MARKET_ANOMALY", "CRITICAL_ALERT", "FAILOVER",
                         "VERSION_CHANGE", "EVENT_CUSTOM", "CRASH_ALERT"],
        event_handler=_on_strategy_events,
        priority=90,  # 最高优先级之一
    )
    
    # 订阅者10: 人事中心 (资源调度/专家雇佣)
    def _on_hr_events(event: Dict[str, Any]) -> None:
        sys.stderr.write(f"[COLLAB-BUS → HR] 触发人事调度: {event.get('event_type')}")
    bus.subscribe(
        subscriber_id="hr_center",
        subscriber_name="人事/调度中心",
        subscribe_events=["MARKET_ANOMALY", "CRITICAL_ALERT", "SKILL_REPORT",
                         "FAILOVER", "EVENT_CUSTOM"],
        event_handler=_on_hr_events,
        priority=80,
    )
    
    # 订阅者11: 文案中心 (说明书/文档/更新日志)
    def _on_copy_events(event: Dict[str, Any]) -> None:
        et = event.get('event_type', '')
        if et in ('VERSION_CHANGE', 'SKILL_REPORT', 'EVENT_CUSTOM'):
            sys.stderr.write(f"[COLLAB-BUS → COPY] 触发文档更新: {et}")
    bus.subscribe(
        subscriber_id="copy_center",
        subscriber_name="文案/说明书中心",
        subscribe_events=["VERSION_CHANGE", "SKILL_REPORT", "EVENT_CUSTOM", "MARKET_ANOMALY"],
        event_handler=_on_copy_events,
        priority=75,
    )
    
    # ── 🆕 订阅者 12: 脑库复盘 (市场雷达 + 版本中心) ──
    _brain_tick_counter = {"n": 0}  # MARKET_TICK 降频计数器
    
    def _on_brain_feed_events(event: Dict[str, Any]) -> None:
        """协作总线事件 → AI 脑库自动投喂"""
        try:
            from engines.ai_brain_feed_engine import brain_feed
            et = event.get('event_type', '?')
            payload = event.get('payload', {})
            source = event.get('source', '?')
            severity = event.get('severity', 'NORMAL')
            
            if et == 'MARKET_TICK':
                # 每 50 次 MARKET_TICK 才投喂 1 次 (降频)
                _brain_tick_counter["n"] += 1
                if _brain_tick_counter["n"] % 50 != 0:
                    return
                
                tick = payload.get('tick', {}) if isinstance(payload, dict) else {}
                pulse = payload.get('market_pulse', {}) if isinstance(payload, dict) else {}
                if tick or pulse:
                    summary = f"[MARKET_TICK #{_brain_tick_counter['n']}] 大盘脉动 "
                    summary += f"{pulse.get('trend', '?')} 波动={pulse.get('volatility', 0):.2f}%"
                    brain_feed.feed(
                        content=summary,
                        category="market",
                        feed_type="experience",
                        source="market_tick",
                        score=float(pulse.get('volatility', 0)) * 10,
                        extra={"tick_count": _brain_tick_counter["n"], "market_pulse": pulse},
                    )
            
            elif et == 'MARKET_ANOMALY':
                # 市场异动 → 高价值投喂 + 入厅 (需要派单复盘)
                anomalies = payload.get('anomalies', []) if isinstance(payload, dict) else []
                if anomalies:
                    lines = []
                    for a in anomalies[:3]:
                        lines.append(
                            f"[{a.get('type','?')}] {a.get('symbol','?')} "
                            f"{a.get('name','')} → 异动分={a.get('score',0):.0f}"
                        )
                    detail = "; ".join(lines[:2])
                    brain_feed.feed(
                        content=f"[MARKET_ANOMALY] 发现市场异动:\n" + "\n".join(lines),
                        category="market",
                        feed_type="signal",
                        source="market_anomaly",
                        score=float(payload.get('max_anomaly_score', 50)),
                        extra={"anomalies": anomalies, "severity": severity},
                    )
                    # 🆕 入厅: MARKET_REVIEW (派单给专家复盘异动)
                    brain_feed.submit_to_hall(
                        task_type="MARKET_REVIEW",
                        task_title=f"市场异动复盘: {detail[:50]}",
                        description="协作总线触发市场异动, 需要专家复盘异动原因 "
                                    "(涨跌停/放量/指数波动)",
                        source="market_radar",
                        priority=70,
                        auto_done=False,
                        extra={"anomalies": anomalies[:5]},
                    )
            
            elif et == 'VERSION_CHANGE':
                # 版本变更 → 投喂变更复盘 + 入厅备案
                component = payload.get('component', '?')
                bump = payload.get('bump', '?')
                reason = payload.get('reason', '')
                old_v = payload.get('old_version', '?')
                new_v = payload.get('new_version', '?')
                brain_feed.feed(
                    content=f"[版本变更] {component} {old_v} → {new_v} ({bump})\n原因: {reason[:100]}",
                    category="system",
                    feed_type="experience",
                    source="version_center",
                    score={"PATCH": 30, "MINOR": 60, "MAJOR": 100}.get(bump, 20),
                    extra={"component": component, "bump": bump, 
                           "old_version": old_v, "new_version": new_v,
                           "reason": reason},
                )
                # 🆕 入厅: VERSION_BUMP (自动结案, 备案版本变更)
                brain_feed.submit_to_hall(
                    task_type="VERSION_BUMP",
                    task_title=f"{component} v{old_v}→v{new_v} ({bump})",
                    description=f"版本变更原因: {reason}",
                    source="version_center",
                    priority=30,
                    auto_done=True,
                    extra={"component": component, "bump": bump,
                           "old_version": old_v, "new_version": new_v},
                )
            
            elif et in ('CRITICAL_ALERT', 'FAILOVER', 'DB_LOCK', 'CRASH_ALERT'):
                # 运维故障 → 高优先级脑库经验 + 入厅紧急派单
                brain_feed.feed(
                    content=f"[运维] {et} from {source} "
                            f"(severity={severity})\n"
                            f"details: {str(payload)[:200]}",
                    category="system",
                    feed_type="experience",
                    source=f"system_{et.lower()}",
                    score=100.0,
                    extra={"payload_keys": list(payload.keys()) if isinstance(payload, dict) else []},
                )
                # 🆕 入厅: SYSTEM_FIX (最高优先级派单修复)
                brain_feed.submit_to_hall(
                    task_type="SYSTEM_FIX",
                    task_title=f"紧急修复: {et} ({source})",
                    description=f"协作总线 {et} from {source} severity={severity}",
                    source=source,
                    priority=100,  # 最高优先级
                    auto_done=False,
                    extra={"event_type": et, "payload": str(payload)[:500]},
                )
            
            else:
                # 其他事件 (SKILL_REPORT, EVENT_CUSTOM, SANDBOX_*, ...)
                # 低优先级, 只投一条 summary
                if severity in ('HIGH', 'CRITICAL'):
                    brain_feed.feed(
                        content=f"[EVENT] {et} (severity={severity}) from {source}",
                        category="system",
                        feed_type="experience",
                        source=f"collab_{et.lower()}",
                        score=float(payload.get('score', 30)) if isinstance(payload, dict) else 30,
                        extra={"event_type": et, "source": source, "severity": severity},
                    )
        
        except Exception as e:
            sys.stderr.write(f"[COLLAB-BUS → BRAIN] 跳过: {e}\n")
    
    bus.subscribe(
        subscriber_id="brain_feed",
        subscriber_name="AI 脑库复盘",
        subscribe_events=["*"],  # 接所有事件, 内部按类型分流
        event_handler=_on_brain_feed_events,
        priority=55,  # 低优先级, 不阻塞主流程
    )
    
    sys.stderr.write(
        f"[COLLAB-BUS] ✅ 12 个订阅者已注册 "
        f"(version_center, sync_center, brain_memory, eigenflux, "
        f"rd_center, skill_center, edu_center, strategy_center, hr_center, "
        f"copy_center, brain_feed)"
    )


# ═══════════════════════════════════════════════════════════════════
# §5 公共 API
# ═══════════════════════════════════════════════════════════════════
def get_recent_events(limit: int = 50, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取最近事件"""
    conn = _conn()
    try:
        if event_type:
            rows = conn.execute(
                "SELECT event_id, event_type, source, severity, symbol, "
                "payload, broadcast_ms, created_at "
                "FROM mt_collab_bus_events WHERE event_type = ? ORDER BY created_at DESC LIMIT ?",
                (event_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_id, event_type, source, severity, symbol, "
                "payload, broadcast_ms, created_at "
                "FROM mt_collab_bus_events ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['payload'] = json.loads(d['payload']) if d.get('payload') else {}
                d['subscribers_json'] = json.loads(d.get('subscribers_json', '[]'))
            except Exception:
                pass
            result.append(d)
        return result
    finally:
        conn.close()


def get_radar_cache() -> List[Dict[str, Any]]:
    """获取市场雷达缓存"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mt_market_radar_cache ORDER BY anomaly_score DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# §6.5 TriggerCoordinator 桥接模块级函数
# ═══════════════════════════════════════════════════════════════════
def record_dispatch(payload: dict = None):
    """触发器分发记录 — 由 TriggerCoordinator 的 log handler 调用

    将一笔事件分发的完整链路记录到协作总线 (便于审计 & 复盘).
    """
    payload = payload or {}
    try:
        bus = get_collab_bus()
        # 发布一条内部 EVENT_DISPATCHED 事件 (不触发递归)
        result = bus.publish(
            event_type='EVENT_DISPATCHED',
            source='trigger_coordinator',
            severity='INFO',
            payload=payload if isinstance(payload, dict) else {"raw": str(payload)[:200]},
        )
        return {"ok": True, "event_id": result.get("event", {}).get("event_id"),
                "broadcast_ms": result.get("broadcast_ms"),
                "matched": result.get("matched_subscribers")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="协作总线 + 市场雷达")
    parser.add_argument("--radar", action="store_true", help="启动市场雷达 daemon")
    parser.add_argument("--cycle", type=int, default=5, help="雷达轮询周期(s)")
    parser.add_argument("--publish", action="store_true", help="发布一条测试事件")
    parser.add_argument("--events", type=int, default=20, help="显示最近 N 事件")
    args = parser.parse_args()
    
    ensure_bus_tables()
    register_standard_subscribers()
    
    if args.radar:
        print(f"[RADAR] 启动 (cycle={args.cycle}s)...")
        radar = MarketRadarDaemon()
        radar.start(cycle=args.cycle)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            radar.stop()
    elif args.publish:
        bus = get_collab_bus()
        result = bus.publish(
            event_type='EVENT_CUSTOM',
            source='cli_test',
            severity='INFO',
            payload={"msg": "协作总线测试消息", "ts": _now_iso()},
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        events = get_recent_events(limit=args.events)
        print(f"\n{'='*60}")
        print(f"📡 协作总线最近 {len(events)} 事件")
        print(f"{'='*60}")
        for e in events:
            print(f"  [{e['severity']:8s}] {e['event_type']:20s} ← {e['source']:15s}  ({e['broadcast_ms']}ms) {e['created_at']}")
        print(f"{'='*60}\n")
