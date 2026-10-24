"""MTSCOS sqlite3 全局加固 (flow_unified_ops_20261024 数据库连接问题修复)
所有进程的 sqlite3.connect 默认 timeout=30s + busy_timeout=30000 —
把 'database is locked' 即时失败变成最长 30s 等待, 与 Flask(WAL 持有方)共存。
幂等: 已 patch 则跳过。
"""
import functools
import sqlite3

if not getattr(sqlite3, '_mtscos_hardened', False):
    _orig_connect = sqlite3.connect

    @functools.wraps(_orig_connect)
    def _hardened_connect(*args, **kwargs):
        kwargs.setdefault('timeout', 30)
        conn = _orig_connect(*args, **kwargs)
        try:
            conn.execute('PRAGMA busy_timeout=30000')
        except Exception:
            pass
        return conn

    sqlite3.connect = _hardened_connect
    sqlite3._mtscos_hardened = True
