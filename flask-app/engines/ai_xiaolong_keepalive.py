#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小龙保活守护 (sys_xiaolong_keepalive)
任务: 保活完善并运行聊天室"小龙" — 全端点健康巡检 + Ollama 聊天链路抽检,
异常自动回灌大厅。300s 循环。
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'http://127.0.0.1:5001'
DAEMON = 'sys_xiaolong_keepalive'

ENDPOINTS = [
    ('页面', '/xiaolong', 'GET'),
    ('manifest', '/xiaolong/manifest', 'GET'),
    ('sw.js', '/xiaolong/sw.js', 'GET'),
    ('icon', '/xiaolong/icon.svg', 'GET'),
    ('health', '/api/xiaolong/health', 'GET'),
    ('persona_chat', '/andromeda/api/persona_chat', 'POST'),
]


def _connect():
    conn = sqlite3.connect(os.path.join(FA_DIR, 'database', 'app.db'), timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _hall_task(conn, title, desc, prio='NORMAL'):
    try:
        if conn.execute(
                "SELECT count(*) FROM mt_lab_task_hall WHERE title=? AND "
                "created_at>datetime('now','localtime','-6 hours')",
                (title,)).fetchone()[0]:
            return False
        conn.execute(
            "INSERT INTO mt_lab_task_hall (title, description, source, priority, "
            "status, created_at) VALUES (?,?,?,'HIGH','QUEUED',datetime('now','localtime'))",
            (title, desc, 'xiaolong_keepalive'))
        conn.commit()
        return True
    except Exception:
        return False


def check_once() -> dict:
    out = {'ok': [], 'bad': [], 'chat_ok': False}
    for label, path, method in ENDPOINTS:
        try:
            if method == 'GET':
                req = urllib.request.Request(BASE + path)
                r = urllib.request.urlopen(req, timeout=6)
                ok = r.status == 200
            else:  # persona_chat 端到端 (小龙真人回答才算 ok)
                payload = json.dumps({
                    'question': '保活抽检: ping, 简短回复',
                    'persona': {'name': '小龙', 'role': 'assistant',
                                'domain': 'chat', 'layer': 'L1'}}).encode()
                req = urllib.request.Request(
                    BASE + path, data=payload,
                    headers={'Content-Type': 'application/json'})
                r = urllib.request.urlopen(req, timeout=90)
                body = json.loads(r.read())
                ans = body.get('data', {}).get('answer', '')
                ok = body.get('code') == 0 and '未就绪' not in ans
                out['chat_ok'] = ok
            (out['ok'] if ok else out['bad']).append(label)
        except Exception as e:
            out['bad'].append(f'{label}:{str(e)[:40]}')
    return out


def _log(conn, detail):
    try:
        conn.execute(
            "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
            "VALUES ('XIAOLONG_KEEPALIVE', ?, 'XIAOLONG_CHECK', ?)",
            (DAEMON, json.dumps(detail, ensure_ascii=False)))
        conn.commit()
    except Exception:
        pass


def _heartbeat(conn):
    try:
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?,?,?,?, datetime('now','localtime'), datetime('now','localtime'))",
            (DAEMON, '小龙聊天室保活守护 (全端点+Ollama 聊天链路抽检) 300s', os.getpid()))
        conn.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
            "pid=?, status='RUNNING' WHERE process_name=?", (os.getpid(), DAEMON))
        conn.commit()
    except Exception:
        pass


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'loop'
    conn = _connect()
    try:
        if cmd == 'once':
            print(json.dumps(check_once(), ensure_ascii=False))
            return 0
        print(f'[{DAEMON}] 小龙保活守护 pid={os.getpid()} 300s', flush=True)
        while True:
            try:
                r = check_once()
                if r['bad']:
                    _hall_task(conn, '小龙保活: 端点异常自动回灌',
                               f'异常项: {",".join(r["bad"])}')
                    _log(conn, r)
                    print(f'[{DAEMON}] ⚠️ {r}', flush=True)
                elif r['ok'] or r['chat_ok']:
                    _log(conn, {'ok': r['ok'], 'chat_ok': r['chat_ok']})
            except Exception as e:
                sys.stderr.write(f'[{DAEMON}] {e}\n')
            _heartbeat(conn)
            time.sleep(300)
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
