#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本中心 + 同步中心触发引擎
══════════════════════════════════════════════════
flow: flow_version_center_20261102

## 版本号规范
v{MAJOR}.{MINOR}.{PATCH}-{suffix}
- MAJOR: 架构级变更 (v1 → v2)，破坏性修改
- MINOR: 新功能 / 新中心 / 新模块 (v1.2 → v1.3)
- PATCH: Bug修复 / 配置变更 / 体检报告 / 市场异动 (v1.2.0 → v1.2.1)

## 触发条件矩阵
┌───────────────────────┬──────────────────┬────────┬──────────────────────────────┐
│ 触发事件               │ 组件             │ bump   │ 触发源                        │
├───────────────────────┼──────────────────┼────────┼──────────────────────────────┤
│ MARKET_ANOMALY         │ collab_bus       │ PATCH  │ 市场雷达                      │
│ CRITICAL_ALERT         │ dr_system        │ MINOR  │ DR 灾难恢复                   │
│ CRASH_ALERT            │ core_engine      │ PATCH  │ 引擎崩溃告警                   │
│ SKILL_REPORT           │ andromeda_core   │ PATCH  │ Skill Agent                   │
│ FAILOVER               │ dr_system        │ MAJOR  │ DR 切换 (架构级)              │
│ MARKET_TICK (每100次)  │ collab_bus       │ PATCH  │ 雷达常规 tick                 │
│ severity=CRITICAL      │ andromeda_core   │ MINOR  │ 高危告警默认 MINOR            │
│ severity=ALERT         │ andromeda_core   │ PATCH  │ 中危告警默认 PATCH            │
│ 大体检报告(deep)        │ medical_center   │ PATCH  │ 每日大体检                    │
│ 新 Skill 注册          │ skill_registry   │ MINOR  │ Skill Lab 注册新 Skill        │
│ VERSION_CHANGE         │ 联动 sync_center │ 触发sync │ 版本变更自动同步DB          │
└───────────────────────┴──────────────────┴────────┴──────────────────────────────┘

## 同步中心触发事件
CRITICAL_ALERT, MARKET_ANOMALY, FAILOVER, DB_LOCK, VERSION_CHANGE
→ 自动调 db_triple_sync_engine.sync_all(dry_run=False)

## DB 表
- mt_version_center — 版本历史 (component/version/bump_type/trigger_event/changelog)
- mt_sync_triggers — 同步触发日志
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
from typing import Any, Dict, List, Optional, Tuple
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
def ensure_version_tables() -> None:
    conn = _conn()
    try:
        # 分开执行每个 DDL (避免某些 SQLite 版本的 executescript 事务问题)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_version_center (
                version_id      TEXT PRIMARY KEY,
                component       TEXT NOT NULL,
                old_version     TEXT,
                new_version     TEXT NOT NULL,
                bump_type       TEXT NOT NULL,
                trigger_event   TEXT,
                trigger_source  TEXT,
                trigger_payload TEXT DEFAULT '{}',
                changelog       TEXT DEFAULT '',
                version_suffix  TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ver_component ON mt_version_center(component, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ver_bump ON mt_version_center(bump_type)")
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_sync_triggers (
                trigger_id      TEXT PRIMARY KEY,
                trigger_event   TEXT NOT NULL,
                sync_type       TEXT NOT NULL,
                source          TEXT,
                affected_tables TEXT DEFAULT '[]',
                success         INTEGER DEFAULT 0,
                duration_ms     INTEGER DEFAULT 0,
                error_msg       TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_trigger ON mt_sync_triggers(trigger_event, created_at)")
        conn.commit()
        
        # 初始版本记录 (如果表为空)
        row = conn.execute("SELECT COUNT(*) AS cnt FROM mt_version_center").fetchone()
        if row['cnt'] == 0:
            # 从 VERSION 文件读取初始版本
            initial_ver = "v25.0.0.1"
            version_file = BASE / "VERSION"
            if version_file.exists():
                try:
                    initial_ver = version_file.read_text().strip()
                except Exception:
                    pass
            
            conn.execute(
                "INSERT INTO mt_version_center "
                "(version_id, component, new_version, bump_type, trigger_event, changelog) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_gen_id("VER"), "andromeda_core", initial_ver, "INIT",
                 "INIT", "仙女座核心初始版本")
            )
            conn.execute(
                "INSERT INTO mt_version_center "
                "(version_id, component, new_version, bump_type, trigger_event, changelog) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_gen_id("VER"), "iceberg", initial_ver, "INIT",
                 "INIT", "冰山初始版本")
            )
            conn.execute(
                "INSERT INTO mt_version_center "
                "(version_id, component, new_version, bump_type, trigger_event, changelog) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_gen_id("VER"), "collab_bus", "v1.0.0", "INIT",
                 "INIT", "协作总线初始版本")
            )
            conn.execute(
                "INSERT INTO mt_version_center "
                "(version_id, component, new_version, bump_type, trigger_event, changelog) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_gen_id("VER"), "medical_center", "v1.0.0", "INIT",
                 "INIT", "医疗中心初始版本")
            )
        
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §2 版本号解析 + Bump 逻辑
# ═══════════════════════════════════════════════════════════════════
def parse_version(ver: str) -> Tuple[int, int, int, str]:
    """解析版本号 vX.Y.Z-suffix → (major, minor, patch, suffix)"""
    # 格式: v25.0.0.1-iceberg-saga 或 v1.2.3 或 v1.2.3-beta
    ver = ver.lstrip('v')
    suffix = ""
    if '-' in ver:
        parts = ver.split('-', 1)
        ver = parts[0]
        suffix = parts[1]
    
    nums = ver.split('.')
    major = int(nums[0]) if len(nums) > 0 else 0
    minor = int(nums[1]) if len(nums) > 1 else 0
    patch = int(nums[2]) if len(nums) > 2 else 0
    
    return major, minor, patch, suffix


def bump_version(ver: str, bump_type: str) -> str:
    """
    根据 bump_type 升级版本号
    PATCH: patch+1
    MINOR: minor+1, patch=0
    MAJOR: major+1, minor=0, patch=0
    """
    major, minor, patch, suffix = parse_version(ver)
    
    if bump_type.upper() == 'PATCH':
        patch += 1
    elif bump_type.upper() == 'MINOR':
        minor += 1
        patch = 0
    elif bump_type.upper() == 'MAJOR':
        major += 1
        minor = 0
        patch = 0
    
    new_ver = f"v{major}.{minor}.{patch}"
    if suffix:
        new_ver += f"-{suffix}"
    return new_ver


def get_current_version(component: str) -> str:
    """获取组件当前版本号"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT new_version FROM mt_version_center "
            "WHERE component = ? ORDER BY created_at DESC LIMIT 1",
            (component,)
        ).fetchone()
        if row:
            return row['new_version']
    finally:
        conn.close()
    return "v0.0.0"


def set_version(component: str, new_version: str, bump_type: str,
                trigger_event: str = "", trigger_source: str = "",
                changelog: str = "", trigger_payload: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    正式 bump 版本号并记录
    """
    old_ver = get_current_version(component)
    if old_ver == new_version:
        return {"skipped": True, "reason": "版本号未变化"}
    
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO mt_version_center "
            "(version_id, component, old_version, new_version, bump_type, "
            "trigger_event, trigger_source, trigger_payload, changelog) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_gen_id("VER"), component, old_ver, new_version, bump_type,
             trigger_event, trigger_source,
             json.dumps(trigger_payload or {}, ensure_ascii=False),
             changelog)
        )
        conn.commit()
        
        result = {
            "component": component,
            "old_version": old_ver,
            "new_version": new_version,
            "bump_type": bump_type,
            "trigger_event": trigger_event,
            "trigger_source": trigger_source,
            "created_at": _now_iso(),
        }
        
        # 同步联动: 版本变更 → 广播 VERSION_CHANGE 事件
        try:
            sys.path.insert(0, str(BASE))
            from engines.collab_bus_engine import get_collab_bus
            bus = get_collab_bus()
            bus.publish(
                event_type='VERSION_CHANGE',
                source='version_center',
                severity='INFO',
                symbol=component,
                payload=result,
            )
            sys.stderr.write(f"[VERSION] 📡 VERSION_CHANGE 广播: {component} {old_ver}→{new_version} ({bump_type})\n")
        except Exception as e:
            sys.stderr.write(f"[VERSION] 广播失败(非致命): {e}\n")
        
        sys.stderr.write(f"[VERSION] ✅ {component}: {old_ver} → {new_version} ({bump_type}) [trigger={trigger_event or 'manual'}]\n")
        return result
        
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §3 触发条件矩阵引擎
# ═══════════════════════════════════════════════════════════════════
# 触发矩阵: event_type → (component, bump_type)
_TRIGGER_MATRIX: List[Dict[str, str]] = [
    {"event_pattern": "MARKET_ANOMALY",     "component": "collab_bus",       "bump": "PATCH"},
    {"event_pattern": "CRITICAL_ALERT",      "component": "dr_system",        "bump": "MINOR"},
    {"event_pattern": "CRASH_ALERT",         "component": "core_engine",      "bump": "PATCH"},
    {"event_pattern": "SKILL_REPORT",        "component": "andromeda_core",   "bump": "PATCH"},
    {"event_pattern": "FAILOVER",            "component": "dr_system",        "bump": "MAJOR"},
    {"event_pattern": "DB_LOCK",             "component": "sync_center",      "bump": "PATCH"},
    {"event_pattern": "DAEMON_STOPPED",      "component": "medical_center",    "bump": "PATCH"},
    {"event_pattern": "VERSION_CHANGE",      "component": "andromeda_core",   "bump": "PATCH"},
    {"event_pattern": "EVENT_CUSTOM",        "component": "collab_bus",       "bump": "PATCH"},
]


def match_trigger(event_type: str, severity: str = "INFO",
                  symbol: str = "", payload: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    """
    根据触发矩阵匹配 bump 规则
    返回: {"component": str, "bump_type": str, "reason": str} 或 None
    """
    # 1. 精确匹配触发矩阵
    for rule in _TRIGGER_MATRIX:
        if rule['event_pattern'] == event_type:
            return {
                "component": rule['component'],
                "bump_type": rule['bump'],
                "reason": f"触发矩阵: {event_type} → {rule['component']} {rule['bump']}",
            }
    
    # 2. 基于 severity 的默认规则 (未在矩阵中的事件)
    sev = severity.upper()
    if sev == 'CRITICAL':
        return {
            "component": "andromeda_core",
            "bump_type": "MINOR",
            "reason": f"严重告警默认 MINOR (severity={severity})",
        }
    elif sev in ('ALERT', 'HIGH'):
        return {
            "component": "andromeda_core",
            "bump_type": "PATCH",
            "reason": f"中危告警默认 PATCH (severity={severity})",
        }
    
    # 3. 市场 tick 特殊处理: 每 100 次 tick bump 一次
    if event_type == 'MARKET_TICK':
        if not hasattr(_match_trigger, '_tick_counter'):
            _match_trigger._tick_counter = 0
        _match_trigger._tick_counter += 1
        if _match_trigger._tick_counter % 100 == 0:
            return {
                "component": "collab_bus",
                "bump_type": "PATCH",
                "reason": f"MARKET_TICK 每 100 次 bump 一次 (第 {_match_trigger._tick_counter} 次)",
            }
        return None  # 其他 tick 不触发
    
    # INFO/LOW 级别事件不触发
    return None


def trigger_version_bump(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    协作总线事件回调 → 自动 bump 版本
    (被 collab_bus_engine 的 version_center 订阅者调用)
    """
    event_type = event.get('event_type', '')
    source = event.get('source', '')
    severity = event.get('severity', 'INFO')
    symbol = event.get('symbol', '')
    payload = event.get('payload', {})
    
    match = match_trigger(event_type, severity, symbol, payload)
    if not match:
        sys.stderr.write(f"[VERSION] 事件 {event_type} ({severity}) 不触发 bump\n")
        return None
    
    component = match['component']
    bump_type = match['bump_type']
    
    # 获取当前版本 → bump → 写入
    old_ver = get_current_version(component)
    new_ver = bump_version(old_ver, bump_type)
    
    changelog = f"自动 bump: {event_type} (severity={severity}, src={source})"
    if symbol:
        changelog += f", symbol={symbol}"
    
    result = set_version(
        component=component,
        new_version=new_ver,
        bump_type=bump_type,
        trigger_event=event_type,
        trigger_source=source,
        changelog=changelog,
        trigger_payload=payload,
    )
    
    return result


# ═══════════════════════════════════════════════════════════════════
# §4 多组件批量 bump (大体检后)
# ═══════════════════════════════════════════════════════════════════
def bump_after_deep_exam(exam_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    大体检完成后 → 根据体检结果批量 bump 相关组件版本
    """
    results = []
    health_score = exam_report.get('health_score', 50)
    bugs_found = exam_report.get('bugs_found', 0)
    
    bumps: List[Tuple[str, str, str]] = []  # (component, bump_type, reason)
    
    # 1. 医疗中心自身 → 总是 bump PATCH (有新体检报告)
    bumps.append(("medical_center", "PATCH", "大体检报告生成"))
    
    # 2. 根据健康分决定 bump 级别
    if health_score < 60 or bugs_found >= 5:
        # 严重问题 → MINOR
        if exam_report.get('target') in ('andromeda', 'both'):
            bumps.append(("andromeda_core", "MINOR", f"仙女座健康分={health_score}, Bug={bugs_found}"))
        if exam_report.get('target') in ('iceberg', 'both'):
            bumps.append(("iceberg", "MINOR", f"冰山健康分={health_score}, Bug={bugs_found}"))
    elif health_score < 80 or bugs_found >= 2:
        # 中等问题 → PATCH
        if exam_report.get('target') in ('andromeda', 'both'):
            bumps.append(("andromeda_core", "PATCH", f"仙女座健康分={health_score}, Bug={bugs_found}"))
        if exam_report.get('target') in ('iceberg', 'both'):
            bumps.append(("iceberg", "PATCH", f"冰山健康分={health_score}, Bug={bugs_found}"))
    
    # 3. 执行 bump
    for component, bump_type, reason in bumps:
        old_ver = get_current_version(component)
        new_ver = bump_version(old_ver, bump_type)
        try:
            result = set_version(
                component=component,
                new_version=new_ver,
                bump_type=bump_type,
                trigger_event="DEEP_EXAM",
                trigger_source="medical_center",
                changelog=reason,
            )
            results.append(result)
        except Exception as e:
            sys.stderr.write(f"[VERSION] bump {component} 失败: {e}\n")
    
    return results


# ═══════════════════════════════════════════════════════════════════
# §5 同步中心触发引擎
# ═══════════════════════════════════════════════════════════════════
# 同步触发事件表
_SYNC_TRIGGERS: List[str] = [
    "CRITICAL_ALERT",
    "MARKET_ANOMALY",
    "FAILOVER",
    "DB_LOCK",
    "VERSION_CHANGE",
    "CRASH_ALERT",
]


def should_sync_on_event(event_type: str, severity: str = "INFO") -> Tuple[bool, str]:
    """判断是否需要触发同步"""
    if event_type in _SYNC_TRIGGERS:
        sync_type = "sync_all" if severity in ('CRITICAL', 'ALERT') else "sync_quick"
        return True, sync_type
    return False, ""


def trigger_sync(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    触发 DB 三方同步 (被协作总线 sync_center 订阅者调用)
    """
    event_type = event.get('event_type', '')
    severity = event.get('severity', 'INFO')
    source = event.get('source', '')
    
    should, sync_type = should_sync_on_event(event_type, severity)
    if not should:
        return {"skipped": True, "reason": f"{event_type} 不在同步触发列表"}
    
    t0 = time.time()
    success = 0
    error_msg = ""
    
    try:
        sys.path.insert(0, str(BASE))
        from engines.db_triple_sync_engine import sync_all
        
        if sync_type == "sync_all":
            result = sync_all(dry_run=False)
        else:
            # quick: 只同步关键表
            result = sync_all(dry_run=False)
        
        success = 1
        duration_ms = round((time.time() - t0) * 1000, 1)
        
    except Exception as e:
        error_msg = str(e)[:200]
        duration_ms = round((time.time() - t0) * 1000, 1)
    
    # 记录同步触发日志
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO mt_sync_triggers "
            "(trigger_id, trigger_event, sync_type, source, success, duration_ms, error_msg) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_gen_id("SYNC"), event_type, sync_type, source,
             success, int(duration_ms), error_msg)
        )
        conn.commit()
    finally:
        conn.close()
    
    sys.stderr.write(f"[SYNC] {'✅' if success else '❌'} {event_type} → {sync_type} "
                     f"({'成功' if success else '失败: ' + error_msg}, {int(duration_ms)}ms)\n")
    
    return {
        "trigger_event": event_type,
        "sync_type": sync_type,
        "success": bool(success),
        "duration_ms": int(duration_ms),
        "error": error_msg,
    }


# ═══════════════════════════════════════════════════════════════════
# §6 公共 API
# ═══════════════════════════════════════════════════════════════════
def get_all_versions(component: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """获取版本历史"""
    conn = _conn()
    try:
        if component:
            rows = conn.execute(
                "SELECT * FROM mt_version_center WHERE component = ? ORDER BY created_at DESC LIMIT ?",
                (component, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mt_version_center ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_components() -> List[Dict[str, Any]]:
    """获取所有组件的当前版本"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT component, new_version, bump_type, trigger_event, created_at "
            "FROM mt_version_center "
            "WHERE version_id IN (SELECT MAX(version_id) FROM mt_version_center GROUP BY component) "
            "ORDER BY component"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sync_triggers(limit: int = 50) -> List[Dict[str, Any]]:
    """获取同步触发日志"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mt_sync_triggers ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def manual_bump(component: str, bump_type: str = "PATCH", 
                reason: str = "手动触发") -> Dict[str, Any]:
    """手动触发 bump (API 调用)"""
    old_ver = get_current_version(component)
    new_ver = bump_version(old_ver, bump_type)
    return set_version(
        component=component,
        new_version=new_ver,
        bump_type=bump_type,
        trigger_event="MANUAL",
        trigger_source="api",
        changelog=reason,
    )


# ═══════════════════════════════════════════════════════════════════
# §7 CLI
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="版本中心 + 同步中心")
    parser.add_argument("--bump", choices=["PATCH", "MINOR", "MAJOR"], help="手动 bump")
    parser.add_argument("--component", default="andromeda_core", help="组件名")
    parser.add_argument("--versions", action="store_true", help="显示版本历史")
    parser.add_argument("--components", action="store_true", help="显示所有组件")
    parser.add_argument("--sync", action="store_true", help="触发同步")
    parser.add_argument("--simulate", action="store_true", help="模拟事件触发 bump")
    parser.add_argument("--event", default="MARKET_ANOMALY", help="模拟事件类型")
    parser.add_argument("--severity", default="ALERT", help="模拟 severity")
    args = parser.parse_args()
    
    ensure_version_tables()
    
    if args.bump:
        result = manual_bump(args.component, args.bump, "CLI 手动触发")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.simulate:
        event = {
            "event_type": args.event,
            "source": "cli_simulate",
            "severity": args.severity,
            "symbol": "",
            "payload": {"test": True},
        }
        result = trigger_version_bump(event)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"事件 {args.event} ({args.severity}) 不触发 bump")
    elif args.components:
        comps = get_components()
        print(f"\n{'='*60}")
        print(f"📦 所有组件当前版本")
        print(f"{'='*60}")
        for c in comps:
            print(f"  {c['component']:20s} → {c['new_version']:15s}  (bump={c['bump_type']}, trigger={c.get('trigger_event','?')})")
        print(f"{'='*60}\n")
    elif args.sync:
        trigger_sync({
            "event_type": "CLI_TEST",
            "severity": "ALERT",
            "source": "cli",
        })
    else:
        versions = get_all_versions(limit=20)
        print(f"\n{'='*60}")
        print(f"📦 版本历史 (最近 20)")
        print(f"{'='*60}")
        for v in versions:
            print(f"  [{v['bump_type']:5s}] {v['component']:20s} {v['old_version'] or 'INIT':15s} → {v['new_version']:15s}  (trigger={v.get('trigger_event','?')})")
        print(f"{'='*60}\n")
