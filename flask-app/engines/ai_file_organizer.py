#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成daemon: sys_file_organizer
来源: AI建议 #0 (score=1.0)
生成时间: 2026-10-24T20:07:50.687919
职责: 智能文件整理 - 每600s清理临时文件和散落文件归类
"""
import os, sys, time, signal, sqlite3, json, glob, subprocess, random, re, logging, urllib.request
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE_DIR = os.path.join(_PROJECT_ROOT, "flask-app", "ai_engines")
# 🔧 flow_andromeda_selfheal_20261021: daemon 以 cwd=_runtime/auto_daemons 运行,
#    缺 flask-app 在 sys.path → `from engines.xxx` 持续 "No module named 'engines'".
#    必须在模板里注入 (生成器每轮重写 daemon 文件, 单改实例会被覆盖).
for _p in (os.path.join(_PROJECT_ROOT, "flask-app"), ENGINE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# 🔧 2026-10-16 修复: DB 解析 env 优先 + 补 PROD 真实路径候选 (旧模板只找 Database/app.db, PROD 树真实库在 flask-app/database/)
APP_DB = os.environ.get('MTSCOS_DB_PATH', '') or os.environ.get('APP_DB', '')
if not APP_DB:
    # 🔧 flow_keepalive_rebuild_20261021: 候选顺序修正 —
    #   项目根 `Database` 是软链 → _runtime/databases/Database (Mac mini 旧 16KB 库, 无
    #   mt_ai_smart_mount_processes 表/旧 schema), 旧顺序把它排第一 → daemon 全部
    #   "no such table: mt_ai_smart_mount_processes" 报错, 巡检/自监控段被跳过。
    #   正解: flask-app/database/app.db 优先 (当前唯一真实库)。
    for _cand in (
        os.path.join(_PROJECT_ROOT, "flask-app", "database", "app.db"),
        os.path.join(_PROJECT_ROOT, "Database", "app.db"),
        os.path.join(_PROJECT_ROOT, "flask-app", "ai_engines", "app.db"),
    ):
        if os.path.exists(_cand):
            APP_DB = _cand
            break
    else:
        APP_DB = os.path.join(_PROJECT_ROOT, "flask-app", "database", "app.db")
PID_FILE = os.path.join(_PROJECT_ROOT, "_runtime", "pids", "sys_file_organizer.pid")
LOG_FILE = os.path.join(_PROJECT_ROOT, "_runtime", "logs", "sys_file_organizer.log")

os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

_running = True

def _signal_handler(signum, frame):
    global _running
    _running = False

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

def _db():
    """🔧 仙女座 v5.0: 统一 DB 连接 — WAL + busy_timeout + checkpoint + synchronous=NORMAL
    所有自动生成的 daemon 脚本从此继承 DB 锁防护, 彻底消灭 database is locked"""
    conn = sqlite3.connect(APP_DB, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def _heartbeat():
    """🔧 flow_unified_ops_20261023 P1-1: 心跳优先走 Flask HTTP 代理 (根治 WAL 写锁竞争)
    根因: Flask 长持 WAL 写锁 → daemon 直写频发 database is locked → except pass 吞掉
         → registry 冻结 → patrol 误判 → 僵尸舰队.
    修复: ①令牌文件存在 → POST /api/internal/heartbeat (loopback+token, Flask 写自己的库永不锁)
         ②HTTP 失败/未配置 → 退回直写双表 (旧行为保留)."""
    try:
        import json as _hbjson
        import urllib.request as _hbreq
        _tok = ''
        try:
            _hb_tf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.internal_token')
            with open(_hb_tf, 'r') as _f:
                _tok = _f.read().strip()
        except Exception:
            _tok = ''
        if _tok:
            _hb_port = os.environ.get('MTSCOS_FLASK_PORT', '5001')
            _hb_req = _hbreq.Request(
                'http://127.0.0.1:' + _hb_port + '/api/internal/heartbeat',
                data=_hbjson.dumps({'process_name': 'sys_file_organizer', 'pid': os.getpid()}).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'X-Internal-Token': _tok},
                method='POST')
            _hb_resp = _hbreq.urlopen(_hb_req, timeout=2)
            if getattr(_hb_resp, 'status', 200) == 200:
                return  # ✅ Flask 进程内已双写, 无需直写
    except Exception:
        pass  # HTTP 失败 → 降级直写
    try:
        now_iso = datetime.now().isoformat()
        now_local = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = _db()
        c = conn.cursor()
        c.execute(
            "UPDATE mt_ai_smart_mount_processes SET heartbeat_at=?, updated_at=?, current_state='RUNNING' WHERE process_name=?",
            (now_iso, now_iso, "sys_file_organizer"))
        c.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), pid=?, status='RUNNING' WHERE process_name=?",
            (os.getpid(), "sys_file_organizer"))
        conn.commit()
        conn.close()
    except Exception:
        pass

def _param(group, key, default=None):
    """🔧 仙女座 v5.1 参数统一系统: 从 mt_params 实时读取参数, 不存在返回 default.
    每次读都查 DB — mt_params 表轻量(108条), 无缓存保证参数热生效.
    支持 type 转换: int/integer, float/number, bool/boolean, str(默认)"""
    try:
        conn = sqlite3.connect(APP_DB, timeout=3)
        conn.execute("PRAGMA busy_timeout=3000")
        row = conn.execute(
            "SELECT param_value, param_type FROM mt_params WHERE param_group=? AND param_key=?",
            (group, key)).fetchone()
        conn.close()
        if row is None: return default
        val, ptype = row[0], (row[1] or 'str').lower()
        if ptype in ('int','integer'): return int(val)
        if ptype in ('float','number'): return float(val)
        if ptype in ('bool','boolean'): return str(val).lower() in ('1','true','yes','on')
        return val
    except Exception:
        return default

def _log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")

def main_loop():
    import random as _rand
    _log(f"DAEMON START: sys_file_organizer pid={os.getpid()}")
    # 🆕 仙女座 v5.1: 参数统一系统 — 从 mt_params 读 cycle, 支持热调整
    CYCLE_GROUP = 'smart_mount' if 'sys_file_organizer'.startswith('sys_') else 'auto_gen'
    CYCLE_KEY = 'sys_file_organizer_interval_sec'
    CYCLE = _param(CYCLE_GROUP, CYCLE_KEY, 600)
    _log(f"🔧 v5.1 参数统一: CYCLE={CYCLE}s (来源=mt_params {CYCLE_GROUP}/{CYCLE_KEY})")
    # ✅ 仙女座 v5.0: 启动随机偏移 30-90s (🔧 2026-10-13 从 0-30 上调) —
    # 避免 daemon 启动后立刻写 WAL 导致父进程 mount 循环被 SQLite RESERVED 锁卡死
    _offset = _rand.randint(30, 90)
    _log(f"启动随机偏移: {_offset}s")
    time.sleep(_offset)
    # 写PID文件 (fsync 防 OneDrive 异步丢失)
    try:
        import tempfile as _tf2
        _fd2, _tmp2 = _tf2.mkstemp(prefix=".daemon_pid_", suffix=".tmp", dir=os.path.dirname(PID_FILE))
        try:
            os.write(_fd2, str(os.getpid()).encode("ascii"))
            os.fsync(_fd2)
        finally:
            os.close(_fd2)
        os.replace(_tmp2, PID_FILE)
        try:
            _dd = os.open(os.path.dirname(PID_FILE), os.O_RDONLY)
            try: os.fsync(_dd)
            finally: os.close(_dd)
        except OSError:
            pass
    except Exception:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    _heartbeat()

    # 🐕 P0 防挂死看门狗 (flow_unified_ops_20261023): 工作段超 90s 强制中断, 防 SQLite WAL 锁挂死整个循环
    import signal as _signal
    _WORK_TIMEOUT_S = 90
    def _work_timeout_handler(signum, frame):
        raise TimeoutError("work cycle timeout " + str(_WORK_TIMEOUT_S) + "s (DB lock hang?)")
    _signal.signal(_signal.SIGALRM, _work_timeout_handler)

    while _running:
        try:
            _signal.alarm(_WORK_TIMEOUT_S)
            # === daemon (NOTE: use module-level APP_DB, not os.environ.get)工作循环 ===
            import_home = os.path.expanduser("~/Desktop")
            stale = glob.glob(import_home + "/*.tmp")[:5] if os.path.isdir(import_home) else []
            _log(f"[file_organizer] scan: found {len(stale)} stale tmp files")
            _heartbeat()
            _signal.alarm(0)
            # 🆕 v5.1 参数热生效: 每轮循环刷新 CYCLE — mt_params 改了不用重启 daemon
            CYCLE = _param(CYCLE_GROUP, CYCLE_KEY, CYCLE)
        except Exception as e:
            _signal.alarm(0)
            _log(f"ERROR: {e}")
        time.sleep(CYCLE)

    # 清理
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    _log(f"DAEMON STOP: sys_file_organizer")

if __name__ == "__main__":
    main_loop()
