#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS Smart Mount Engine - 真守护进程启动器（双 fork + setsid）
====================================================================
flow_id: flow_smart_mount_daemonize_20260820_001
§14 STEP_7_EXECUTE 下场实施

设计目标:
  1. 用双 fork + setsid 让 ai_smart_mount_engine.py 脱离任何父进程
     (Trae IDE / Terminal.app / launchd 子 bash / nohup)，父进程
     变成 PID 1 (init/launchd)，从此 Trae 关闭/Terminal 退出都不
     会被信号杀掉。
  2. 在守护进程层捕获所有启动期异常并落日志/落库，启动失败时不
     重复 fork 形成进程风暴。
  3. 写入守护事件到 mt_daemon_supervisor_log 表 + 日志文件
     便于追踪运行状态和排查问题。

用法:
    /usr/bin/python3 _entry_wrappers/entrypoints/start_smart_mount_engine_daemon.py

停止:
    python3 flask-app/engines/ai_smart_mount_engine.py stop
    或 kill -TERM $(cat _runtime/pids/ai_smart_mount_engine_daemon.pid)
"""
import os
import sys
import time
import traceback
from datetime import datetime

# ----------------------------------------------------------------------
# 路径常量
# ----------------------------------------------------------------------
PROJECT_ROOT = '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project'
ENGINE_PY = os.path.join(PROJECT_ROOT, 'flask-app', 'engines', 'ai_smart_mount_engine.py')
RUNTIME_DIR = os.path.join(PROJECT_ROOT, '_runtime')
LOG_DIR = os.path.join(RUNTIME_DIR, 'logs')
PID_DIR = os.path.join(RUNTIME_DIR, 'pids')
DAEMON_PID_FILE = os.path.join(PID_DIR, 'ai_smart_mount_engine_daemon.pid')
ENGINE_PID_FILE = os.path.join(PID_DIR, 'ai_smart_mount_engine.pid')
SUPERVISOR_LOG = os.path.join(LOG_DIR, 'smart_mount_supervisor.log')
START_LOCK_FILE = os.path.join(RUNTIME_DIR, '.smart_mount_daemon.lock')
APP_DB = os.path.join(PROJECT_ROOT, 'flask-app', 'ai_engines', 'app.db')

for _d in (LOG_DIR, PID_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass


# ----------------------------------------------------------------------
# 日志工具（双通道：文件 + 数据库）
# ----------------------------------------------------------------------
def _stamp() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log_event(level: str, event: str, detail: str = '') -> None:
    """守护进程事件落日志 + 落库 mt_daemon_supervisor_log"""
    line = f"[{_stamp()}] [{level}] {event}"
    if detail:
        line += f" | {detail}"
    # 1. 落日志文件
    try:
        with open(SUPERVISOR_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()
    except Exception:
        pass
    # 2. 落库（独立连接，失败不影响主流程）
    try:
        import sqlite3
        conn = sqlite3.connect(APP_DB, timeout=3)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS mt_daemon_supervisor_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time    TEXT    NOT NULL,
                supervisor    TEXT    NOT NULL,
                level         TEXT    NOT NULL,
                event         TEXT    NOT NULL,
                detail        TEXT,
                pid           INTEGER,
                created_at    TEXT    NOT NULL
            )
        """)
        c.execute(
            "INSERT INTO mt_daemon_supervisor_log "
            "(event_time, supervisor, level, event, detail, pid, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_stamp(), 'smart_mount_daemon', level, event, detail, os.getpid(), _stamp()),
        )
        conn.commit()
        conn.close()
    except Exception:
        # 数据库不可用不阻塞守护启动
        pass


def write_daemon_pid() -> None:
    try:
        with open(DAEMON_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def clear_daemon_pid() -> None:
    try:
        os.remove(DAEMON_PID_FILE)
    except OSError:
        pass


def is_engine_running() -> bool:
    """检测 engine 进程是否还在跑（用 PID 文件 + kill -0）"""
    try:
        with open(ENGINE_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # 不发信号，仅检测存活
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as proc_cmdline:
                command = proc_cmdline.read().decode(errors='ignore')
            return 'ai_smart_mount_engine.py' in command
        except (FileNotFoundError, PermissionError):
            # macOS 无 /proc；PID 文件由引擎自身写入，存活检查足够。
            return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


# ----------------------------------------------------------------------
# 双 fork daemonize
# ----------------------------------------------------------------------
def _daemonize() -> None:
    """
    双 fork + setsid 创建真守护进程
    - 第一次 fork: 父进程立即退出，子进程被 init 接管
    - setsid: 子进程成为新会话组长，脱离控制终端
    - 第二次 fork: 防止重新获取控制终端
    - 重定向 stdio: stdout/stderr -> 日志文件，stdin -> /dev/null
    """
    # 第一次 fork
    try:
        pid = os.fork()
        if pid > 0:
            # 父进程立即退出
            sys.stdout.flush()
            sys.stderr.flush()
            print(f"[start_daemon] smart_mount daemonize: parent PID={os.getpid()}, child PID={pid}")
            os._exit(0)
    except OSError as e:
        sys.stderr.write(f"[start_daemon] first fork failed: {e}\n")
        os._exit(1)

    # 子进程：脱离控制终端
    os.setsid()
    os.chdir(PROJECT_ROOT)
    os.umask(0o022)

    # 第二次 fork（防止重新获取控制终端）
    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError as e:
        sys.stderr.write(f"[start_daemon] second fork failed: {e}\n")
        os._exit(1)

    # 真正的守护进程：重定向标准 IO (用 os.open 避免 OneDrive TCC 文本模式问题)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        _sup_fd = os.open(SUPERVISOR_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(_sup_fd, 1)
        os.dup2(_sup_fd, 2)
        os.close(_sup_fd)
    except Exception:
        pass
    try:
        _null_fd = os.open('/dev/null', os.O_RDONLY)
        os.dup2(_null_fd, 0)
        os.close(_null_fd)
    except Exception:
        pass


# ----------------------------------------------------------------------
# 引擎启动 + 监督
# ----------------------------------------------------------------------
def _resolve_python() -> str:
    """优先使用 _runtime/.venv 的 python3，回退系统 python3"""
    candidates = [
        os.path.join(RUNTIME_DIR, '.venv', 'bin', 'python3'),
        '/Library/Developer/CommandLineTools/usr/bin/python3',
        '/usr/bin/python3',
        sys.executable,
    ]
    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return '/usr/bin/python3'


def _build_env() -> dict:
    env = os.environ.copy()
    env['PYTHONPATH'] = (
        f'{PROJECT_ROOT}/flask-app:'
        f'{PROJECT_ROOT}/_config:'
        f'{PROJECT_ROOT}/_entry_wrappers:'
        f'{PROJECT_ROOT}/_entry_wrappers/startup_modules'
    )
    env['PYTHONUNBUFFERED'] = '1'
    # 守护进程标识（引擎内部可读取做差异化处理）
    env['MTSCOS_SM_DAEMONIZED'] = '1'
    return env


def _dbg(msg: str) -> None:
    """守护进程调试日志：统一走 log_event 落库+落文件，
    不依赖 fd 1/stdout，避免 fork 后 dup2 状态不一致问题。"""
    log_event('DBG', msg)


def launch_engine() -> int:
    """
    启动 ai_smart_mount_engine.py，使用 os.execvpe 替换当前守护
    进程的镜像。这样守护进程本身就是 engine 主进程，省一层中间
    进程，进程树更干净，PID 文件直接对应 engine。
    """
    _dbg(f"launch_engine() enter pid={os.getpid()}")
    try:
        py_bin = _resolve_python()
        _dbg(f"python resolved: {py_bin}")
        env = _build_env()
        _dbg(f"env built, PYTHONPATH={env.get('PYTHONPATH','?')[:80]}")
        log_event('INFO', 'ENGINE_EXEC_START',
                  f'py={py_bin} engine={ENGINE_PY} daemon_pid={os.getpid()}')
        _dbg(f"about to execvpe: {py_bin} {ENGINE_PY} start")
        os.execvpe(
            py_bin,
            [py_bin, ENGINE_PY, 'start'],
            env,
        )
        # execvpe 成功不会返回；下面是不可达
        _dbg("[FATAL] execvpe returned without replacing!")
    except Exception as e:
        _dbg(f"[FATAL] launch_engine exception: {e}")
        # execvpe 失败属于致命错误（一般不会发生），落日志后退出
        log_event('FATAL', 'ENGINE_EXEC_FAILED',
                  f'err={e}\n{traceback.format_exc()}')
        clear_daemon_pid()
        sys.exit(2)


def main() -> None:
    """
    主入口:
      1) 守护模式: 双fork + setsid 后 exec engine
      2) 若检测到 engine 已在跑则直接退出避免重复启动
    """
    # 1. 防止重复启动（包括多个 launchd/cron 调用同时进入）
    try:
        lock_fd = os.open(START_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, str(os.getpid()).encode())
        os.close(lock_fd)
    except FileExistsError:
        try:
            with open(START_LOCK_FILE) as existing:
                lock_pid = int(existing.read().strip())
            os.kill(lock_pid, 0)
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            try:
                os.remove(START_LOCK_FILE)
                return main()
            except OSError:
                pass
        log_event('INFO', 'SKIP_LOCKED', 'another launcher is starting or checking the daemon')
        return

    try:
        _main_locked()
    finally:
        try:
            os.remove(START_LOCK_FILE)
        except OSError:
            pass


def _main_locked() -> None:
    """Run the launcher while holding the single-start lock."""
    # 防止重复启动
    if is_engine_running():
        # engine 还活着，无需再 fork 一个守护进程
        print(f"[start_daemon] engine already RUNNING, skip daemonize")
        log_event('INFO', 'SKIP_DAEMONIZE', 'engine already running, skip')
        return

    # 2. 清理 stale daemon PID
    try:
        with open(DAEMON_PID_FILE) as f:
            old = int(f.read().strip())
        try:
            os.kill(old, 0)
            # 守护进程还活着但 engine 不在 -> 可能正在重启，等一下
            print(f"[start_daemon] supervisor PID={old} still alive, waiting for engine spawn")
            log_event('WARN', 'SUPERVISOR_ALIVE_ENGINE_DOWN',
                      f'supervisor_pid={old}')
            return
        except ProcessLookupError:
            # stale，清理
            clear_daemon_pid()
    except (FileNotFoundError, ValueError):
        pass

    # 3. 双 fork daemonize
    log_event('INFO', 'DAEMONIZE_START', f'caller_pid={os.getpid()}')
    _daemonize()

    # 4. 守护进程从此处执行
    write_daemon_pid()
    log_event('INFO', 'DAEMON_READY', f'daemon_pid={os.getpid()} ppid={os.getppid()}')
    _dbg(f"after fork, daemon_pid={os.getpid()} ppid={os.getppid()}")

    # 5. 安装 SIGTERM/SIGINT 优雅退出 handler
    import signal

    def _graceful(signum, frame):
        log_event('INFO', 'DAEMON_SIGNAL',
                  f'signal={signum} daemon_pid={os.getpid()}')
        clear_daemon_pid()
        # 把信号转发给 engine 进程组（engine 是当前进程，exec 后就是它）
        try:
            os.killpg(os.getpid(), signal.SIGTERM)
        except Exception:
            pass
        os._exit(128 + signum)

    _dbg("installing signal handlers")
    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)
    _dbg("signal handlers installed, calling launch_engine()")

    # 6. exec engine（替换镜像，PID 不变）
    launch_engine()
    _dbg("[FATAL] launch_engine returned!")


if __name__ == '__main__':
    main()
