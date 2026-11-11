#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金盾独立守护 daemon

职责:
  1. 每 30s 把 mt_shield_events 里 hall_dispatched=0 的事件注入冰山大厅队列
  2. 事件表 30 分钟窗口外的积压做归档标记, 避免无限堆积
  3. 心跳留痕 (logs/shield_daemon.log)

金盾拦截本身由 Flask 中间件 shield_inject_middleware 完成, 本 daemon 只负责
把中间件产生的事件持续消费掉, 不再依赖 Flask 请求触发。
"""
import os
import sys
import time
import sqlite3
import datetime

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

from engines.shield_inject_middleware import _shield_pending_for_iceberg  # noqa: E402

DB = os.path.join(_APP, "database", "app.db")
INTERVAL = 30


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def cycle():
    rows = _shield_pending_for_iceberg() or []
    conn = sqlite3.connect(DB, timeout=5)
    try:
        stale = conn.execute(
            "UPDATE mt_shield_events SET hall_dispatched=1 "
            "WHERE hall_dispatched=0 AND created_at < datetime('now','-30 minutes')"
        ).rowcount
        conn.commit()
        total = conn.execute("SELECT count(*) FROM mt_shield_events").fetchone()[0]
    finally:
        conn.close()
    log(f"drained={len(rows)} archived={stale} total_events={total}")
    return len(rows), stale


def main():
    log(f"shield_daemon start, interval={INTERVAL}s, db={DB}")
    while True:
        try:
            cycle()
        except Exception as e:
            log(f"cycle error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
