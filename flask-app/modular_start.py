#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS AI Flask 入口 (modular_start.py)
被 sys_flask_server daemon 调用启动 Web 服务
端口: 8888 (避免 macOS AirPlay 5000 端口冲突)
"""
import os
import sys

# 🆕 2026-09-17: Flask 模式 — 全局拦截后台守护线程创建
# 所有模块级单例 (auto_routine_maintenance, AI_Cluster_Manager, comprehensive 等)
# 在 import 时会创建 threading.Thread 启动后台线程, 永久持 DB 写锁 → Flask worker 被堵
# 在 import 任何模块前 patch threading.Thread.__init__, 拦截可疑后台线程
os.environ['MTSCOS_FLASK_MODE'] = '1'
# P1 修复 (2026-10-15): MTSCOS_DB_PATH fallback — Flask 后台进程有时 env 丢失,
# 导致 db_path.get_db_path('app.db') 错误解析到 OneDrive 旧库 (disk I/O error),
# 而 PROD DB (/Users/wuchenghao/MTSCOS_PROD/flask-app/database/app.db) 才是权威源
if not os.environ.get('MTSCOS_DB_PATH'):
    _prod_db = os.path.expanduser('~/MTSCOS_PROD/flask-app/database/app.db')
    if os.path.exists(_prod_db) and os.path.getsize(_prod_db) > 1e9:
        os.environ['MTSCOS_DB_PATH'] = _prod_db
    else:
        # 兜底: 本地 PROD 不存在时用本地 app.db
        _local_db = os.path.join(os.path.dirname(__file__), 'database', 'app.db')
        if os.path.exists(_local_db):
            os.environ['MTSCOS_DB_PATH'] = _local_db
import threading as _threading_flask

# ===== flow_unified_ops_20261023 P1-2: 端口守卫 (单一拉起方) =====
# mini 上有三个潜在拉起方: launchd com.mtscos.flask (KeepAlive) + cron keepalive + 手动启动.
# 历史事故: pkill 重启 Flask 后 launchd 复活第二实例 → EADDRINUSE 崩溃循环.
# 守卫: 端口已有健康服务 → 本实例立即安静退出 (在重模块导入之前执行, 零 DB 开销).
if __name__ == '__main__':
    _pg_port = 8888
    for _pg_argv in sys.argv[1:]:
        if _pg_argv.startswith("--port="):
            try:
                _pg_port = int(_pg_argv.split("=", 1)[1])
            except ValueError:
                pass
            break
    try:
        import urllib.request as _pg_req
        _pg_resp = _pg_req.urlopen(f'http://127.0.0.1:{_pg_port}/index', timeout=3)
        if getattr(_pg_resp, 'status', 0) == 200:
            sys.stderr.write(f'[PORT-GUARD] :{_pg_port} 已有健康 Flask 服务, 本实例退出 (单一拉起方守卫 P1-2)\n')
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass  # 端口不可达 → 正常启动

_ORIGINAL_THREAD_INIT = _threading_flask.Thread.__init__

# ===== flow_unified_ops_20261023 P1-1b: sqlite3 连接注册表 (泄漏事务可发现性) =====
# Python 3.9 的 sqlite3.Connection 不被 gc 跟踪 → gc.get_objects() 扫不到,
# 必须在重模块导入前 monkey-patch sqlite3.connect 登记 weakref, 清道夫才能遍历.
import sqlite3 as _sq_flask
import weakref as _weakref_flask
_SQLITE_CONN_REGISTRY = []
_ORIG_SQLITE_CONNECT = _sq_flask.connect
def _tracked_sqlite_connect(*args, **kwargs):
    _conn = _ORIG_SQLITE_CONNECT(*args, **kwargs)
    try:
        _SQLITE_CONN_REGISTRY.append(_weakref_flask.ref(_conn))
    except Exception:
        pass
    return _conn
_sq_flask.connect = _tracked_sqlite_connect

_SKIP_KEYWORDS = (
    # 原守护线程
    'routine_maintenance', 'comprehensive_upgrader', 'system_upgrade',
    'auto_repair', 'ai_inspection', 'auto_inspection', 'auto_patrol',
    'auto_hire', 'file_organizer', 'rule_enforcer', 'auto_learning',
    'monitoring', 'scheduler', 'heartbeat', 'watcher', 'health_check',
    # 🆕 Flask 模式下不需要的后台 (由 smart_mount_engine 独立进程负责)
    'archive', 'archiver', 'evolution', 'andromeda', 'autosync',
    'normalize', 'idle_monitor', 'idlemonitor', 'idle.',
    'patrol', 'eigenflux', 'brain_feed',
)
# 🆕 直接拦截所有后台线程 — Flask 进程只做 HTTP handler 请求
# autosync daemon / ANDROMEDA 演化 / normalize_system / ai_archive 等
# 全部改成 NOP 空跑, Flask 成纯 HTTP server
def _patched_thread_init(self, *args, **kwargs):
    target = kwargs.get('target') or (args[0] if args else None)
    name = kwargs.get('name', '')
    target_name = target.__name__.lower() if target else ''
    qualname = getattr(target, '__qualname__', '').lower() if target else ''
    name_lower = name.lower()
    should_skip = any(kw in target_name or kw in qualname or kw in name_lower for kw in _SKIP_KEYWORDS)
    # 🆕 同时拦截 Flask app.run() 之前启动的所有 daemon (除了 werkzeug 自己的)
    # 只有 app.run() 后由 Flask 内部启动的 worker 线程放行
    if should_skip:
        kwargs['target'] = lambda: None
        try:
            _ORIGINAL_THREAD_INIT(self, *args, **kwargs)
            return
        except Exception:
            pass
    _ORIGINAL_THREAD_INIT(self, *args, **kwargs)
_threading_flask.Thread.__init__ = _patched_thread_init
sys.stderr.write("[FLASK-MODE] threading.Thread.__init__ 已 patch, 拦截 17 种后台线程关键字\n")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

try:
    from core.db_path import patch_sqlite3_connect as _mtscos_patch
    _mtscos_patch(verbose=False)
except Exception as _e:
    sys.stderr.write(f"[WARN] db_path patch failed: {_e}\n")

# Phase 7 局部 Factory: 显式调用 ensure_app_ready() 完成蓝图+API注册
# 注: server_real_db 模块加载时也会自动调一次 ensure_app_ready(),
#     但显式调用是 Factory 模式的推荐入口, 且 _app_initialized 防重入保证只执行一次
from server_real_db import ensure_app_ready, app
ensure_app_ready()  # 幂等, 即使模块加载时已执行过也不会重复注册

# ===== autosync blueprint (两端 Flask 都注册, GUI 上下文有 TCC 访问 DB) =====
try:
    import autosync_andromeda as _sync
    _sync.register_sync_routes(app)
except Exception as _e:
    sys.stderr.write(f"[AUTOSYNC] blueprint 注册失败 (非致命): {_e}\n")

# ===== 系统正规化初始化 (放到后台线程, 不阻塞 Flask listen) =====
# 之前同步执行卡死在 DB 锁 (系统升级 84 任务 + AI 巡检 7 阶段),
# 导致 app.run() 永远不执行, 系统对外 HTTP 不可用.
try:
    import threading as _mt

    def _normalize_async():
        try:
            from ai_engines.system_normalizer import normalize_system
            _norm_report = normalize_system(app)
            sys.stderr.write(
                f"[SYS-NORM] 异步初始化完成: "
                f"overall_ok={_norm_report.get('overall_ok')}, "
                f"耗时={_norm_report.get('took_sec')}s\n"
            )
        except Exception as _e:
            sys.stderr.write(f"[SYS-NORM] 异步初始化失败(非致命): {_e}\n")

    _mt.Thread(target=_normalize_async, name='sys-norm-async', daemon=True).start()
    sys.stderr.write("[SYS-NORM] 异步线程已提交 (不阻塞 Flask listen)\n")
except Exception as _e:
    sys.stderr.write(f"[SYS-NORM] 启动失败(非致命): {_e}\n")

if __name__ == "__main__":
    # ===== v6.2: 仙女座七阶段自演化后台线程 (自动联想→检索→衍生→强化→拓展→优化) =====
    try:
        import threading
        import time as _time

        def _andromeda_evolution_loop():
            """
            仙女座拉马努金式自演化循环.
            每 600s 周期跑一轮, 或被 autosync 同步完 eigenflux 消息后立刻唤醒.
            自举循环: AI 员工跨机讨论 → 同步 → 摄入脑库 → 关联图谱 → 衍生新知识 → 反向驱动新讨论
            """
            _time.sleep(180)  # 等 Flask + Ollama 完全就绪
            sys.stderr.write("[ANDROMEDA-EVOL] 自演化后台线程启动 (cycle_interval=600s, autosync可唤醒)\n")
            from engines.andromeda_auto_evolution import (
                run_cycle, EVOLUTION_WAKEUP_EVENT, reset_evolution_event,
            )
            while True:
                try:
                    run_cycle()
                except Exception as _e:
                    sys.stderr.write(f"[ANDROMEDA-EVOL] cycle crashed: {_e}\n")
                # 清唤醒信号 → wait 下一轮 (被唤醒则立刻跑, 否则等 600s)
                reset_evolution_event()
                _was_wakeup = EVOLUTION_WAKEUP_EVENT.wait(timeout=600)
                if _was_wakeup:
                    sys.stderr.write("[ANDROMEDA-EVOL] 🔔 被 autosync 唤醒, 提前跑下一轮\n")

        _evol_thread = threading.Thread(
            target=_andromeda_evolution_loop,
            name='andromeda-auto-evolution',
            daemon=True,
        )
        _evol_thread.start()
        sys.stderr.write("[ANDROMEDA-EVOL] 后台线程已提交 (180s 后首次 cycle)\n")
    except Exception as _e:
        sys.stderr.write(f"[ANDROMEDA-EVOL] 后台线程启动失败 (非致命): {_e}\n")

    # ===== v6.3: 仙女座双向同步后台线程 (自动发现 Mac mini → 双向 rsync + DB 合并) =====
    try:
        def _autosync_loop():
            """后台双向同步循环: 直接调用 autosync_andromeda.main_loop()"""
            sys.stderr.write("[AUTOSYNC] 双向同步后台线程启动\n")
            import autosync_andromeda as _sync
            _sync.main_loop()

        _sync_thread = threading.Thread(
            target=_autosync_loop,
            name='andromeda-autosync',
            daemon=True,
        )
        _sync_thread.start()
        sys.stderr.write("[AUTOSYNC] 后台线程已提交 (自动发现 Mac mini → 双向同步)\n")
    except Exception as _e:
        sys.stderr.write(f"[AUTOSYNC] 后台线程启动失败 (非致命): {_e}\n")

    # 🆕 2026-09-17: Flask 进程成为纯 HTTP server, 不启动任何后台守护线程
    # Flask 进程内模块级单例 (auto_routine_maintenance, comprehensive_system_upgrader,
    # AI_Cluster_Manager 等) 在 import 时会启动后台线程, 永久持写锁做长事务 →
    # Flask worker 被堵 → HTTP timeout. 后台任务改由 smart_mount_engine (独立进程) 负责.
    import os as _os_flask
    _os_flask.environ['MTSCOS_FLASK_MODE'] = '1'
    def _nop_start(self):
        import sys as _sys
        _sys.stderr.write(f"[FLASK-MODE] {type(self).__name__}.start() SKIPPED (Flask 纯 HTTP 模式)\n")
    # Monkey-patch 所有已知会启动后台线程的单例
    try:
        from ai_engines.auto_routine_maintenance import auto_routine_maintenance_system
        auto_routine_maintenance_system.start = lambda: None
        print('[FLASK-MODE] ✅ auto_routine_maintenance patched')
    except Exception as _e: pass
    try:
        from ai_engines.management.ai_cluster_manager import ai_cluster_manager
        ai_cluster_manager._get_manager = lambda: type('Fake',(),{'_start_monitoring_thread':lambda self:None,'start':lambda self:None,'get_cluster_status':lambda self:{},'get_employee_status':lambda self:{}})()
        print('[FLASK-MODE] ✅ ai_cluster_manager patched (lazy)')
    except Exception as _e: pass
    try:
        # 跳过 comprehensive_system_upgrader / smart_auto_upgrade 的 start
        import sys as _sys_flask
        for _mod_name in list(_sys_flask.modules.keys()):
            if 'upgrade' in _mod_name.lower() or 'upgrader' in _mod_name.lower() or 'maintenance' in _mod_name.lower() or 'inspection' in _mod_name.lower():
                _mod = _sys_flask.modules[_mod_name]
                for _attr_name in dir(_mod):
                    if _attr_name.endswith('_system') or _attr_name.endswith('_manager') or _attr_name.endswith('_engine'):
                        _obj = getattr(_mod, _attr_name, None)
                        if _obj and hasattr(_obj, 'start') and callable(_obj.start):
                            try:
                                _obj.start = lambda *a, **kw: None
                                print(f'[FLASK-MODE] ✅ {_mod_name}.{_attr_name}.start patched')
                            except Exception: pass
    except Exception as _e: pass
    print('[FLASK-MODE] ✅ 所有后台守护线程 start() 已 patch 为 NOP')

    # 🆕 Flask app.run() 前等待 5s 让模块级初始化建表事务跑完
    # Thread patch 已经拦截了所有后台守护线程的 start, 但模块级单例的
    # __init__ 里可能同步做一些轻量建表, 等 5s 让它们 commit
    import time as _t_pre_run
    sys.stderr.write("[BOOT] 等待 5s 让模块初始化 commit...\n")
    _t_pre_run.sleep(5)
    sys.stderr.write("[BOOT] Flask 开始 listen\n")

    # flow_iceberg_saga_20261021: 支持 --port=N 覆盖 (smart_sync PROD :5001 启动),
    # 默认仍 8888 (避免 macOS AirPlay 5000 冲突)
    _mt_port = 8888
    for _argv in sys.argv[1:]:
        if _argv.startswith("--port="):
            try:
                _mt_port = int(_argv.split("=", 1)[1])
                sys.stderr.write(f"[BOOT] 端口覆盖: {_mt_port}\n")
            except ValueError:
                pass
            break
    # ===== flow_unified_ops_20261023 P1-1b: WAL 泄漏事务清道夫 =====
    # 实证: Flask 启动后 ~45s 内部某引擎连接 DML 后不 commit (常驻单例持有连接),
    # WAL 写锁被永久占用 → 全舰队外部写 database is locked, Flask 其它连接也写不进.
    # 清道夫: 每 20s 遍历连接注册表 (sqlite3.connect monkey-patch 登记, 见模块顶部),
    # 对 in_transaction 的连接代为 commit (保留写意图, 释放写锁).
    try:
        import time as _t_reaper

        def _wal_txn_reaper():
            _n_total = 0
            while True:
                _t_reaper.sleep(20)
                try:
                    for _ref in list(_SQLITE_CONN_REGISTRY):
                        _o = _ref()
                        if _o is None:
                            try:
                                _SQLITE_CONN_REGISTRY.remove(_ref)
                            except ValueError:
                                pass
                            continue
                        try:
                            if _o.in_transaction:
                                _o.commit()
                                _n_total += 1
                                sys.stderr.write(
                                    f'[WAL-REAPER] 已代提交泄漏事务 #{_n_total} (连接 {_o!r:.60})\n')
                        except Exception:
                            pass
                except Exception:
                    pass

        _reaper_t = _threading_flask.Thread(target=_wal_txn_reaper, name='wal-txn-reaper', daemon=True)
        _reaper_t.start()
        sys.stderr.write("[WAL-REAPER] 泄漏事务清道夫已启动 (20s 周期)\n")
    except Exception as _e:
        sys.stderr.write(f"[WAL-REAPER] 启动失败(非致命): {_e}\n")

    app.run(host="0.0.0.0", port=_mt_port, debug=False, threaded=True)
