#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mac mini 探活 → 自动补跑双向同步 守护
=========================================
flow_mini_sync_watchdog_20261021

背景: Mini 侧 sshd 出现 "exec request failed on channel 0" (能握手不能 fork),
      双向同步 13 张缺表全部 skip, 需人工盯着重试。
本守护: 每分钟探活一次, 一旦 SSH 真能执行命令, 立刻:
  ① pull --create-missing 补齐 12 张 Mini 独有表 + mt_error_thinking_chain
  ② 再跑一轮默认 28 表双向增量, 让两端收敛
  ③ 落报告并自动退出 (一次性任务, 不做常驻轮询)

用法:
  nohup python3 engines/mini_sync_watchdog.py >> ../_runtime/logs/mini_sync_watchdog.log 2>&1 &
  python3 engines/mini_sync_watchdog.py --once      # 只探一次, 通了就补跑
  python3 engines/mini_sync_watchdog.py --status    # 看当前状态
"""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import time

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(FA_DIR)
LOG_DIR = os.path.join(PROJECT_ROOT, '_runtime', 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'mini_sync_watchdog.log')
SYNC_ENGINE = os.path.join(FA_DIR, 'engines', 'bidirectional_sync.py')
REPORT = os.path.join(FA_DIR, '_runtime', 'logs', 'mini_sync_watchdog_last.json')

HOST = os.environ.get('MTSCOS_SYNC_HOST', 'wuchenghao@100.106.220.96')
POLL_SECS = int(os.environ.get('MTSCOS_WATCHDOG_POLL', '60'))
MAX_HOURS = float(os.environ.get('MTSCOS_WATCHDOG_MAX_HOURS', '72'))
LOCK_FILE = '/tmp/mtscos_mini_sync_watchdog.lock'

# Mini 独有 / 本机缺的表 (需 --create-missing 复制 schema)
MISSING_TABLES = [
    'mt_andromeda_knowledge_base', 'mt_upgrade_reports', 'mt_upgrade_overviews',
    'mt_andromeda_contributor_persona', 'mt_ai_employee_profiles',
    'mt_ai_employee_social_graph', 'mt_ai_employee_consultations',
    'mt_ai_employee_contributions', 'mt_ai_employee_empowerment_log',
    'mt_pipeline_execution_log', 'mt_release_sessions', 'mt_auto_empower_log',
    'mt_error_thinking_chain',
]


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
    # stdout 已重定向到同一日志文件时不重复打印 (nohup 场景)
    if sys.stdout.isatty():
        print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _lock() -> bool:
    """单实例锁 (放 /tmp, 不碰 OneDrive), 僵尸锁 30min 接管"""
    try:
        if os.path.exists(LOCK_FILE):
            pid, age = 0, 1e9
            try:
                pid = int(open(LOCK_FILE).read().split()[0])
                age = time.time() - os.path.getmtime(LOCK_FILE)
            except Exception:
                pass
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except Exception:
                    pass
            if alive and age < 1800:
                return False
            if alive:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return True


def _unlock() -> None:
    try:
        if int(open(LOCK_FILE).read().split()[0]) == os.getpid():
            os.remove(LOCK_FILE)
    except Exception:
        pass


def probe() -> tuple:
    """返回 (ok, 详情). 只有真能 exec 才算通 — sshd 能握手但 fork 失败时仍判不通"""
    try:
        r = subprocess.run(
            ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
             '-o', 'ServerAliveInterval=5', HOST, 'echo MTSCOS_PROBE_OK'],
            capture_output=True, text=True, timeout=25,
        )
        out = (r.stdout or '').strip()
        if r.returncode == 0 and 'MTSCOS_PROBE_OK' in out:
            return True, 'exec_ok'
        err = (r.stderr or '').strip().splitlines()
        return False, (err[-1][:120] if err else f'rc={r.returncode} empty stdout')
    except subprocess.TimeoutExpired:
        return False, 'probe_timeout'
    except Exception as e:
        return False, str(e)[:120]


def run_sync(tables: list, create_missing: bool, label: str) -> dict:
    cmd = [sys.executable, SYNC_ENGINE]
    if tables:
        cmd += ['--tables', ','.join(tables)]
    if create_missing:
        cmd += ['--create-missing']
    _log(f"▶ {label}: {' '.join(cmd[1:])}")
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=FA_DIR, capture_output=True, text=True, timeout=3600)
        tail = (r.stdout or '').strip().splitlines()[-3:]
        for ln in tail:
            _log(f"  | {ln[:160]}")
        return {'label': label, 'rc': r.returncode, 'secs': round(time.time() - t0, 1),
                'tail': tail}
    except subprocess.TimeoutExpired:
        _log(f"✗ {label} 超时 (>3600s)")
        return {'label': label, 'rc': -9, 'secs': round(time.time() - t0, 1), 'tail': ['timeout']}
    except Exception as e:
        _log(f"✗ {label} 失败: {e}")
        return {'label': label, 'rc': 1, 'secs': 0, 'tail': [str(e)[:160]]}


def run_all() -> list:
    results = [
        run_sync(MISSING_TABLES, True, 'phase1_缺表建表+拉全量'),
        run_sync([], False, 'phase2_默认白名单双向增量'),
    ]
    try:
        os.makedirs(os.path.dirname(REPORT), exist_ok=True)
        with open(REPORT, 'w', encoding='utf-8') as f:
            json.dump({'finished_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                       'host': HOST, 'results': results}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return results


def main() -> int:
    args = sys.argv[1:]
    if '--status' in args:
        ok, info = probe()
        print(json.dumps({'host': HOST, 'reachable': ok, 'detail': info,
                          'lock_exists': os.path.exists(LOCK_FILE),
                          'report_exists': os.path.exists(REPORT)}, ensure_ascii=False, indent=2))
        return 0

    once = '--once' in args
    if not _lock():
        _log('已有守护实例在跑 (lock 存在) → 本次退出')
        return 0
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
    try:
        deadline = time.time() + MAX_HOURS * 3600
        _log(f"守护启动 pid={os.getpid()} host={HOST} poll={POLL_SECS}s max={MAX_HOURS}h")
        n = 0
        while True:
            ok, info = probe()
            n += 1
            if ok:
                _log(f"✅ Mini 恢复 (第 {n} 次探活) → 开始补跑")
                res = run_all()
                ok_all = all(r['rc'] == 0 for r in res)
                _log(f"补跑完成 {'全部成功' if ok_all else '有失败, 详见报告'} → 守护退出")
                return 0 if ok_all else 1
            if n == 1 or n % 10 == 0:
                _log(f"探活 #{n} 未通: {info}")
            if once:
                _log('--once 且未通 → 退出(不做后台等待)')
                return 2
            if time.time() >= deadline:
                _log(f'超过 {MAX_HOURS}h 仍未探通 → 守护放弃退出')
                return 3
            time.sleep(POLL_SECS)
    except SystemExit:
        _log('收到终止信号 → 退出')
        return 0
    finally:
        _unlock()


if __name__ == '__main__':
    sys.exit(main())
