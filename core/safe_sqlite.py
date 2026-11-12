"""
╔══════════════════════════════════════════════════════════════════════════╗
║  🛡️ SafeSqlite — 统一安全 SQLite 封装 (解决 FD 泄露 + 锁争用)              ║
║                                                                            ║
║  设计原则:                                                                 ║
║  1. 短连接 + autocommit — 用完即关, 不留事务                               ║
║  2. 自动 retry + busy_timeout — 不怕瞬时锁争用                              ║
║  3. 上下文管理器强制 close — 确保永不泄露 FD                                ║
║  4. 全局 SQLiteConfig — 一次性 PRAGMA WAL/journal_mode/busy_timeout         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sqlite3 as _sqlite3_module  # 模块级 import 保存原始引用, monkeypatch 不影响
_ORIGINAL_SQLITE_CONNECT = _sqlite3_module.connect  # ⚠️ 关键: 在任何 patch 之前保存原始 connect

import time
import threading
import os
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple

log = logging.getLogger('SafeSqlite')

# ═══════════════════════════════════════════════════════════════════════
# 全局配置 — 所有进程共用
# ═══════════════════════════════════════════════════════════════════════

_DB_PATH_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
    os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'app.db'),
    '/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db',
]


def _resolve_db_path(custom: Optional[str] = None) -> str:
    """解析 DB 路径

    修复: custom 路径只要是合理的 (有父目录或显式 .db 后缀) 就用它,
    不管文件是否存在 (SQLite 会自动创建)。之前 os.path.exists(custom)
    导致新文件路径被错误丢弃, 回退到默认 app.db → CryptoWrapper 在
    app.db 上操作导致 DB 文件头损坏 (malformed)。
    """
    if custom:
        # 绝对路径或带目录 → 直接用
        if os.path.isabs(custom) or os.path.dirname(custom):
            _dir = os.path.dirname(os.path.abspath(custom))
            if os.path.isdir(_dir):
                return os.path.abspath(custom)
        # 相对路径带 .db 后缀 → 可能是新文件, 也用它
        if custom.endswith('.db'):
            return os.path.abspath(custom)
        # 文件已存在 → 用它
        if os.path.exists(custom):
            return os.path.abspath(custom)
    # 回退: 在 candidate 里找存在的
    for p in _DB_PATH_CANDIDATES:
        resolved = os.path.abspath(p)
        if os.path.exists(resolved):
            return resolved
    # 兜底: 第一个 candidate (即使不存在)
    return os.path.abspath(_DB_PATH_CANDIDATES[0])


# 进程内互斥锁 (多线程竞争, 不解决多进程)
_thread_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════
# 核心: safe_connect —— 唯一安全的连接构造函数
# ═══════════════════════════════════════════════════════════════════════

def safe_connect(
    db_path: Optional[str] = None,
    *,
    timeout: float = 3.0,         # SQLite 内部 busy_timeout
    busy_timeout_ms: int = 1000,  # PRAGMA busy_timeout (短, 不阻塞)
    autocommit: bool = True,      # True = isolation_level=None (推荐)
    wal_mode: bool = True,
    row_factory: bool = True,
    check_same_thread: bool = False,
    immediate_retry: int = 3,     # 打开失败时的立即重试
) -> sqlite3.Connection:
    """创建一个安全的 SQLite 连接。

    所有 daemon/engine 统一走这个入口, 确保:
    - 短生命周期 + autocommit
    - 正确的 PRAGMA 设置
    - 线程安全
    - 失败时有限 retry (不阻塞太久)
    """
    db = _resolve_db_path(db_path)

    last_err = None
    for attempt in range(immediate_retry):
        try:
            # ⚠️ 必须用 _ORIGINAL_SQLITE_CONNECT —— 绕过 monkeypatch, 避免无限递归
            conn = _ORIGINAL_SQLITE_CONNECT(
                db,
                timeout=timeout,
                isolation_level=None if autocommit else '',
                check_same_thread=check_same_thread,
            )
            if row_factory:
                conn.row_factory = _sqlite3_module.Row
            # 关键 PRAGMA
            if wal_mode:
                try:
                    conn.execute('PRAGMA journal_mode=WAL')
                except Exception:
                    pass
            try:
                conn.execute(f'PRAGMA busy_timeout={busy_timeout_ms}')
            except Exception:
                pass
            try:
                conn.execute('PRAGMA synchronous=NORMAL')
            except Exception:
                pass
            try:
                conn.execute('PRAGMA cache_size=-64000')  # 64MB
            except Exception:
                pass
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            if 'locked' in str(e).lower() or 'busy' in str(e).lower():
                time.sleep(0.1 * (attempt + 1))  # 递增退避
                continue
            raise
    # 所有 retry 耗尽
    raise sqlite3.OperationalError(f'SafeSqlite: failed after {immediate_retry} attempts: {last_err}')


# ═══════════════════════════════════════════════════════════════════════
# 上下文管理器 —— 强制 close (自动 rollback 未提交事务)
# ═══════════════════════════════════════════════════════════════════════

@contextmanager
def safe_conn(
    db_path: Optional[str] = None,
    *,
    timeout: float = 3.0,
    busy_timeout_ms: int = 1000,
    autocommit: bool = True,
):
    """with safe_conn() as conn: —— 用完自动 close, 永不泄露"""
    conn = safe_connect(db_path, timeout=timeout, busy_timeout_ms=busy_timeout_ms,
                        autocommit=autocommit)
    try:
        yield conn
    except Exception:
        try:
            if not autocommit:
                conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 便捷查询函数 —— 自动 open → query → close
# ═══════════════════════════════════════════════════════════════════════

def safe_query(sql: str, params: Tuple = (), db_path: Optional[str] = None,
               busy_timeout_ms: int = 1000) -> List[sqlite3.Row]:
    """SELECT 快捷: open → execute → fetchall → close"""
    with safe_conn(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall()


def safe_query_one(sql: str, params: Tuple = (), db_path: Optional[str] = None,
                   busy_timeout_ms: int = 1000) -> Optional[sqlite3.Row]:
    """SELECT 单条: open → execute → fetchone → close"""
    with safe_conn(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone()


def safe_exec(sql: str, params: Tuple = (), db_path: Optional[str] = None,
              busy_timeout_ms: int = 2000) -> int:
    """INSERT/UPDATE/DELETE: open → execute(autocommit) → close → 返回 changes"""
    with safe_conn(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount


def safe_execmany(sql: str, params_list: List[Tuple],
                  db_path: Optional[str] = None,
                  busy_timeout_ms: int = 2000) -> int:
    """批量: open → executemany → close"""
    if not params_list:
        return 0
    with safe_conn(db_path, busy_timeout_ms=busy_timeout_ms) as conn:
        cur = conn.executemany(sql, params_list)
        return cur.rowcount


# ═══════════════════════════════════════════════════════════════════════
# 长事务版本 —— 显式 begin/commit/rollback (极少见, 写复杂原子操作时用)
# ═══════════════════════════════════════════════════════════════════════

@contextmanager
def safe_tx(db_path: Optional[str] = None, *, busy_timeout_ms: int = 3000):
    """with safe_tx() as conn: —— 显式事务, 用完自动 close

    在 with 块内用 conn.execute('BEGIN'), 正常退出会自动 commit, 异常自动 rollback.
    """
    conn = safe_connect(db_path, busy_timeout_ms=busy_timeout_ms, autocommit=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.execute('COMMIT')
    except Exception:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 紧急修复工具: 立即强制 checkpoint (WAL → main) + 降低持锁时间
# ═══════════════════════════════════════════════════════════════════════

def force_checkpoint(db_path: Optional[str] = None) -> Dict[str, Any]:
    """强制 WAL checkpoint, 释放 WAL 文件"""
    try:
        with safe_conn(db_path, busy_timeout_ms=5000) as conn:
            cur = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            row = cur.fetchone()
            return {'ok': True, 'wal_checkpoint': dict(row) if row else {}}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ═══════════════════════════════════════════════════════════════════════
# 进程 FD 健康检查 (诊断用)
# ═══════════════════════════════════════════════════════════════════════

def get_db_fd_count(db_path: Optional[str] = None) -> Dict[str, int]:
    """返回当前进程打开的 DB FD 数量"""
    import subprocess
    db = os.path.abspath(_resolve_db_path(db_path))
    try:
        result = subprocess.run(
            ['lsof', '-p', str(os.getpid()), db],
            capture_output=True, text=True, timeout=5
        )
        lines = [l for l in result.stdout.split('\n') if db in l]
        return {'db_fds': len(lines), 'pid': os.getpid()}
    except Exception:
        return {'db_fds': -1, 'pid': os.getpid()}


# ═══════════════════════════════════════════════════════════════════════
# 🔧 关键: monkeypatch sqlite3.connect
# 让整个进程内所有现存和未来的 sqlite3.connect() 调用
# 自动走 safe_connect (短连接 + autocommit + 正确 PRAGMA)
# ═══════════════════════════════════════════════════════════════════════

_ORIGINAL_CONNECT = None
_PATCHED = False


def install_sqlite3_monkeypatch(**kwargs):
    """安装全局 monkeypatch —— 一次性解决 25+ 文件 ratio=0% 的问题

    在任何 import sqlite3 的模块之前调用:
        from core.safe_sqlite import install_sqlite3_monkeypatch
        install_sqlite3_monkeypatch()
        ... (然后正常 import 所有业务代码)

    kwargs 会传给 safe_connect 默认值 (timeout, busy_timeout_ms 等)
    """
    global _ORIGINAL_CONNECT, _PATCHED
    if _PATCHED:
        return  # 已 patch, 幂等

    import sqlite3 as _sqlite3_mod
    _ORIGINAL_CONNECT = _sqlite3_mod.connect

    def _patched_connect(*args, **kw):
        """拦截 sqlite3.connect(...) → safe_connect"""
        # 提取 db_path (第一个 positional arg, 或 kwarg['database'] / kwarg['db'])
        db_path = args[0] if args else kw.get('database') or kw.get('db') or None
        # 用户显式传的 timeout / isolation_level 等不覆盖 safe 默认值
        # 但保留 row_factory (因为很多代码依赖它)
        row_factory = kw.get('row_factory', None)
        check_same_thread = kw.get('check_same_thread', False)
        autocommit = kwargs.get('autocommit', True)
        busy_ms = kwargs.get('busy_timeout_ms', 1500)
        timeout = kwargs.get('timeout', 3.0)

        try:
            conn = safe_connect(
                db_path=db_path,
                timeout=timeout,
                busy_timeout_ms=busy_ms,
                autocommit=autocommit,
                wal_mode=True,
                row_factory=False,  # safe_connect 已经处理
                check_same_thread=check_same_thread,
            )
            # 如果调用方显式设置了 row_factory, 尊重它
            if row_factory is not None:
                conn.row_factory = row_factory
            return conn
        except Exception as e:
            # safe_connect 失败时 fallback 到原始 connect (避免启动时崩溃)
            log.warning(f'SafeSqlite: safe_connect failed ({e}), fallback to original')
            return _ORIGINAL_CONNECT(*args, **kw)

    _sqlite3_mod.connect = _patched_connect
    _PATCHED = True
    log.info('🛡️ SafeSqlite monkeypatch installed — all sqlite3.connect() now auto-safe')

