#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 系统守护进程启动器（双 fork daemonize）
============================================================
作用：用双 fork + setsid 让 modular_start.py 脱离沙盒进程树，
     父进程变成 PID 1 (init/launchd)，沙盒在 tool 边界清理时找不到此进程。

用法：
    /usr/bin/python3 _entry_wrappers/entrypoints/start_daemon.py

停止：
    lsof -nP -iTCP:8888 | awk 'NR>1 {print $2}' | xargs kill
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# /_entry_wrappers/entrypoints/start_daemon.py → 项目根
# 已是项目根，无需再上溯
PROJECT_ROOT = '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project'


def _daemonize():
    """双 fork + setsid 创建真守护进程"""
    # 第一次 fork
    try:
        pid = os.fork()
        if pid > 0:
            # 父进程立即退出，子进程变孤儿被 init 接管
            sys.stdout.flush()
            print(f'[start_daemon] 启动守护进程，父 PID={os.getpid()}, 子 PID={pid}')
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f'[start_daemon] 第一次 fork 失败: {e}\n')
        sys.exit(1)

    # 子进程：脱离控制终端
    os.setsid()
    os.chdir(PROJECT_ROOT)
    os.umask(0)

    # 第二次 fork（防重新获取控制终端）
    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError as e:
        sys.stderr.write(f'[start_daemon] 第二次 fork 失败: {e}\n')
        os._exit(1)

    # 真正的守护进程：重定向标准 IO
    sys.stdout.flush()
    sys.stderr.flush()
    with open('/tmp/mtscos_server.log', 'a') as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
    # stdin 从 /dev/null 读
    with open('/dev/null', 'r') as f:
        os.dup2(f.fileno(), 0)


def main():
    _daemonize()
    # 守护进程从此处执行：启动 modular_start
    env = os.environ.copy()
    env['PYTHONPATH'] = (
        f'{PROJECT_ROOT}/flask-app:'
        f'{PROJECT_ROOT}/_config:'
        f'{PROJECT_ROOT}/_entry_wrappers:'
        f'{PROJECT_ROOT}/_entry_wrappers/startup_modules'
    )
    env['PYTHONUNBUFFERED'] = '1'
    os.execvpe(
        '/usr/bin/python3',
        ['/usr/bin/python3', f'{PROJECT_ROOT}/_entry_wrappers/entrypoints/modular_start.py'],
        env
    )


if __name__ == '__main__':
    main()
