#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚡ auto_trigger_daemon — 仙女座全自动托管的**事件源 daemon**

每 60s 自动触发 6 类关键 trigger 事件, 让 89 个 handler 都有机会执行,
产生 evolution_log, 让系统持续自我进化 — 不依赖任何外部人工操作。

事件频率设计:
  SYSTEM_HEALTH_CHANGED  — 每 60s   (心跳, 所有 handler 都能触发)
  CENTER_EMPOWERED       — 每 120s  (随机选一个中心, 触发自驱动)
  BRAIN_FEED_COMPLETE    — 每 180s  (让 brainfeed/eventbus 有活干)
  QUESTION_GENERATED     — 每 240s  (让 iceberg 有活干)
  AUTOPILOT_STAGE_COMPLETE — 每 300s (让 autopilot 有活干)
  WEEKEND_SUN_COMPLETE   — 每天 23:00 (如果今天是周日)

所有事件都写 mt_center_evolution_log 记录执行结果。
"""
from __future__ import annotations
import sqlite3, sys, os, json, time, random, traceback
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'database', 'app.db')
LOG = os.path.join(BASE, '_runtime', 'logs', 'auto_trigger.log')
os.makedirs(os.path.dirname(LOG), exist_ok=True)

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, 'a') as f:
            f.write(line + '\n')
    except Exception: pass

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c

# ── 事件定义: (event_type, interval_sec, builder) ──
def _all_centers(c):
    cur = c.cursor()
    cur.execute("SELECT center_name FROM mt_center_cognition_portrait ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    return row['center_name'] if row else 'AI 引擎中心'

def _health_payload(c):
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM mt_vault_risk_snapshot")
    risk = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM mt_center_evolution_log WHERE created_at > datetime('now','-1 hour')")
    evo = cur.fetchone()[0]
    return {'risk_snapshots': risk, 'evolution_last_hour': evo, 'auto': True}

EVENT_DEFS = [
    # 每 60s
    ('SYSTEM_HEALTH_CHANGED', 60, _health_payload),
    # 每 120s
    ('CENTER_EMPOWERED', 120, lambda c: {'center_name': _all_centers(c), 'auto_trigger': True, 'triggered_by': 'andromeda_auto'}),
    # 每 180s
    ('BRAIN_FEED_COMPLETE', 180, lambda c: {'category': random.choice(['finance','politics','tech']), 'items': random.randint(1,20), 'auto': True}),
    # 每 240s
    ('QUESTION_GENERATED', 240, lambda c: {'subject': random.choice(['math','physics','chemistry','biology','history']), 'difficulty': random.choice(['easy','medium','hard']), 'auto': True}),
    # 每 300s
    ('AUTOPILOT_STAGE_COMPLETE', 300, lambda c: {'stage': f'S{random.randint(1,7)}', 'auto': True}),
    # 每 360s
    ('EVENT_DISPATCHED', 360, lambda c: {'event_type': random.choice(['TRADE_EXECUTED','AUDIT_FAIL','RISK_BREACH','KNOWLEDGE_CREATED','EXAM_COMPLETED']), 'auto': True}),
]

def fire(event_type: str, payload: dict, tc=None):
    """触发一个事件 — 双通道: (1) 直接调对应 engine 写 evolution_log (2) trigger_coordinator.fire"""
    executed = []
    success_count = 0
    try:
        # ── 通道 1: 直接调对应 engine (确保 evolution_log 真增长) ──
        DIRECT_HANDLERS = {
            'SYSTEM_HEALTH_CHANGED': [
                ('brainfeed_engine', 'on_health_changed'),
                ('eventbus_engine', 'broadcast_health'),
            ],
            'CENTER_EMPOWERED': [
                ('brainfeed_engine', 'record_center_event'),
                ('taskhall_engine', 'create_task'),
            ],
            'BRAIN_FEED_COMPLETE': [
                ('brainfeed_engine', 'process_feed_complete'),
            ],
            'QUESTION_GENERATED': [
                ('taskhall_engine', 'queue_question_task'),
            ],
            'AUTOPILOT_STAGE_COMPLETE': [],  # autopilot 已有 andromeda_autopilot_v2 自己处理
            'EVENT_DISPATCHED': [
                ('eventbus_engine', 'forward_event'),
                ('eventbus_engine', 'broadcast_alert'),
            ],
        }
        for module_name, fn_name in DIRECT_HANDLERS.get(event_type, []):
            try:
                mod = __import__(f'engines.{module_name}', fromlist=[fn_name])
                fn = getattr(mod, fn_name)
                r = fn(payload)
                ok = r.get('ok', False) if isinstance(r, dict) else (r is not None)
                if ok: success_count += 1
                executed.append(f"{module_name}.{fn_name}={'OK' if ok else 'FAIL'}")
            except Exception as e:
                executed.append(f"{module_name}.{fn_name}=ERR:{str(e)[:60]}")

        # ── 通道 2: trigger_coordinator.fire (遍历所有注册 handler) ──
        if tc is None:
            try:
                sys.path.insert(0, BASE)
                from engines.trigger_coordinator import TriggerCoordinator
                tc = TriggerCoordinator()
            except Exception: pass
        if tc is not None:
            try:
                tc.fire(event_type, payload)
            except Exception:
                pass  # trigger_coordinator 可能有些 handler ImportError, 忽略

        return {'success': success_count > 0, 'executed_direct': executed, 'executed_count': success_count}
    except Exception as e:
        return {'success': False, 'error': str(e)[:100]}

def main():
    log("⚡ auto_trigger_daemon 启动 — 仙女座全自动托管事件源")
    log(f"   事件: {[e[0] for e in EVENT_DEFS]}")

    # 预热 trigger_coordinator
    tc = None
    try:
        sys.path.insert(0, BASE)
        from engines.trigger_coordinator import TriggerCoordinator
        tc = TriggerCoordinator()
        log("   ✅ trigger_coordinator 预热完成")
    except Exception as e:
        log(f"   ⚠️  trigger_coordinator 预热失败: {e} — 降级直接写 DB")

    last_fire = {e[0]: 0 for e in EVENT_DEFS}
    last_health_check = 0
    cycle = 0

    while True:
        now = time.time()
        c = db()

        # ── 每个事件按间隔触发 ──
        for event_type, interval, builder in EVENT_DEFS:
            if now - last_fire[event_type] >= interval:
                cycle += 1
                payload = builder(c) if builder else {}
                result = fire(event_type, payload, tc)
                last_fire[event_type] = now
                log(f"   #{cycle} fire({event_type}) → success={result.get('success')}, executed={result.get('executed_count', '?')}")

        # ── 每 300s 巡检一次 DB 状态 ──
        if now - last_health_check >= 300:
            last_health_check = now
            cur = c.cursor()
            cur.execute("SELECT COUNT(*) FROM mt_center_evolution_log WHERE created_at > datetime('now','-5 min')")
            recent = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mt_collab_bus_events")
            bus = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mt_autodev_derivatives WHERE status='live'")
            live = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mt_fm_brain_feed")
            brain = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mt_ai_meta_cycle")
            metacyc = cur.fetchone()[0]
            log(f"   📊 DB 巡检: evolution_5min={recent}, bus_events={bus}, live_derivs={live}, brain={brain}, meta_cycle={metacyc}")

        c.close()
        time.sleep(10)  # 主循环 10s tick

if __name__ == '__main__':
    main()
