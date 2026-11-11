#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
防火墙四抗加固引擎 (sys_firewall_hardening)
============================================
flow_unified_ops_20261024 · 抗病毒/抗冲击/抗攻击/抗污染源入侵

四抗机制 (复用现有表, 零 DDL):
  ① 抗攻击 ATTACK  : 高频失败来源扫描 (403/404/locked 异常) → mt_firewall_rules
                      自动插 BLOCK 规则 (hit_count 计数) + 大厅留痕
  ② 抗冲击 SURGE   : 日志行速率基线突增 (>3x 均值) → 大厅回灌 '流量冲击体检'
  ③ 抗病毒 VIRUS   : auto_daemons/engines 目录快照比对 — 新增 .py 含可疑特征
                      (exec/eval 长串 base64/socket 反连) → 大厅告警 + 隔离建议
  ④ 抗污染 POLLUTE : 大厅 QUEUED + 脑库最新投喂扫污染特征 → CONTAMINATED 隔离/
                      大厅告警 (与 guard_once 黑名单互补, 此处管'内容'层)
留痕: mt_maintenance_log(corps_id='FIREWALL_HARDENING') + mt_firewall_rules
守护: loop 300s + launchd com.mtscos.fw-hardening (拉起保护)
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import time

import sqlite3

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = FA_DIR
PID_DIR = os.environ.get('MTSCOS_PID_DIR', os.path.join(
    PROJECT_ROOT, '_runtime', 'pids'))
LOG_CANDIDATES = ['/tmp/flask_launchd.log', os.path.join(
    PROJECT_ROOT, '_runtime', 'logs', 'flask_launchd.log')]
DAEMON_NAME = 'sys_firewall_hardening'
# 防火墙 AI 员工专岗 (flow_unified_ops_20261023): 四抗各配一名, 行动留痕自动归属
OFFICERS = {'ATTACK': ('FW_OFF_ATTACK', 'FW·磐石'),
            'SURGE': ('FW_OFF_SURGE', 'FW·观澜'),
            'VIRUS': ('FW_OFF_VIRUS', 'FW·照妖'),
            'POLLUTE': ('FW_OFF_POLLUTE', 'FW·涤尘')}
OFFICER_SEEDS = [
    ('FW·磐石', 'FW_OFF_ATTACK', '防火墙抗攻击专岗', 'attack_detection,ip_blacklist', '网络安全'),
    ('FW·观澜', 'FW_OFF_SURGE', '防火墙抗冲击专岗', 'rate_analysis,anomaly_detection', '流量治理'),
    ('FW·照妖', 'FW_OFF_VIRUS', '防火墙抗病毒专岗', 'file_integrity,malware_signature', '病毒防护'),
    ('FW·涤尘', 'FW_OFF_POLLUTE', '防火墙抗污染专岗', 'content_sanitization,injection_detect', '数据治理'),
]


def ensure_officers(conn) -> int:
    """幂等注册 4 名防火墙 AI 员工 (mini 重建后自愈)."""
    n = 0
    for name, code, desc, caps, spec in OFFICER_SEEDS:
        try:
            conn.execute(
                "INSERT INTO ai_employees (name, employee_code, description, "
                "capabilities, specialties, status) SELECT ?,?,?,?,?, 'active' "
                "WHERE NOT EXISTS (SELECT 1 FROM ai_employees WHERE employee_code=?)",
                (name, code, desc, caps, spec, code))
            conn.commit()
            n += conn.execute("SELECT changes()").fetchone()[0]
        except Exception:
            pass
    return n
POLL_SECS = 300
POLLUTION_MARKS = ['<script', '${', '{{', 'union select', 'or 1=1', 'drop table',
                   'javascript:', 'eval(', 'rm -rf', '../../etc/passwd']
VIRUS_MARKS = [r'eval\(compile\(', r'base64\.b64decode\(.{64,}',
               r'socket\.socket\(.*connect', r'subprocess.*curl.*\|\s*sh',
               r'/etc/passwd', r'__import__\(.os.\)']
SNAPSHOT_FILE = os.path.join(PID_DIR, 'fw_hardening_py_snapshot.json')


def _connect():
    env = os.environ.get('MTSCOS_DB')
    path = env if (env and os.path.exists(env)) else os.path.join(
        FA_DIR, 'database', 'app.db')
    conn = sqlite3.connect(path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _log(conn, action: str, detail: dict) -> None:
    try:
        detail = dict(detail)
        for prefix, (code, name) in OFFICERS.items():
            if action.startswith(prefix):
                detail['ai_officer'] = f'{name}({code})'
                break
        conn.execute(
            "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
            "VALUES ('FIREWALL_HARDENING', ?, ?, ?)",
            (DAEMON_NAME, action, json.dumps(detail, ensure_ascii=False)))
        conn.commit()
    except Exception:
        pass


def _hall_task(conn, title: str, desc: str, prio: str = 'HIGH') -> bool:
    """缺口回灌大厅 (24h 同名去重)."""
    try:
        if conn.execute(
                "SELECT count(*) FROM mt_lab_task_hall WHERE title=? AND "
                "created_at>datetime('now','localtime','-24 hours')",
                (title,)).fetchone()[0]:
            return False
        conn.execute(
            "INSERT INTO mt_lab_task_hall (title, description, source, priority, "
            "status, created_at) VALUES (?,?, 'fw_hardening', ?, 'QUEUED', "
            "datetime('now','localtime'))", (title, desc, prio))
        conn.commit()
        return True
    except Exception:
        return False


def _tail_lines(path: str, n: int = 4000) -> list:
    try:
        with open(path, 'r', errors='ignore') as f:
            return f.readlines()[-n:]
    except Exception:
        return []


# ============================================================
# ① 抗攻击: 高频异常来源 → 自动 BLOCK 规则
# ============================================================
def attack_once(conn) -> dict:
    stats = {'scanned': 0, 'blocked': 0}
    lines = []
    for p in LOG_CANDIDATES:
        lines = _tail_lines(p)
        if lines:
            break
    hits: dict = {}
    for ln in lines:
        if not any(m in ln for m in (' 403 ', ' 429 ', 'database is locked',
                                     'Traceback', ' 404 ')):
            continue
        m = re.search(r'\b(\d+\.\d+\.\d+\.\d+)\b', ln)
        src = m.group(1) if m else None
        if not src or src.startswith('127.') or src.startswith('100.'):
            continue  # 无 IP(local)/loopback/内网 Tailscale 不拉黑 — 内部锁竞争归 surge 管
        hits[src] = hits.get(src, 0) + 1
    stats['scanned'] = len(hits)
    for src, cnt in sorted(hits.items(), key=lambda x: -x[1])[:5]:
        if cnt < 20:
            continue  # 阈值: 4000 行内 20 次异常才算攻击源
        rid = f'FW_BLK_{hashlib.md5(src.encode()).hexdigest()[:10]}'
        try:
            conn.execute(
                "INSERT OR IGNORE INTO mt_firewall_rules (rule_id, env_id, rule_name, "
                "rule_type, direction, source_cidr, action, status) VALUES "
                "(?, 'Internet', ?, 'blacklist', 'inbound', ?, 'DENY', 'ACTIVE')",
                (rid, f'自动拉黑: 异常频次 {cnt}/4000行', f'{src}/32'))
            conn.commit()
            if conn.execute("SELECT changes()").fetchone()[0]:
                stats['blocked'] += 1
                _log(conn, 'ATTACK_BLOCK', {'src': src, 'hits': cnt, 'rule': rid})
        except Exception:
            pass
    return stats


# ============================================================
# ② 抗冲击: 日志速率突增检测
# ============================================================
def surge_once(conn) -> dict:
    lines = []
    for p in LOG_CANDIDATES:
        lines = _tail_lines(p, 12000)
        if lines:
            break
    if len(lines) < 1000:
        return {'surge': 0}
    n = len(lines)
    recent_err = sum(1 for ln in lines[-n // 4:] if 'Traceback' in ln or 'ERROR' in ln)
    base_err = sum(1 for ln in lines[:n // 4] if 'Traceback' in ln or 'ERROR' in ln)
    stats = {'surge': 0, 'recent_err': recent_err, 'base_err': base_err}
    if base_err < 3 and recent_err > 30 or \
            (base_err > 0 and recent_err > base_err * 3 and recent_err > 20):
        stats['surge'] = 1
        if _hall_task(conn, '防火墙抗冲击体检: 异常速率突增',
                      f'近 1/4 窗口错误 {recent_err} vs 基线 {base_err}, '
                      f'疑似冲击/雪崩, 需限流与熔断体检', 'HIGH'):
            _log(conn, 'SURGE_ALERT', stats)
    return stats


# ============================================================
# ③ 抗病毒: python 文件快照 + 可疑特征扫描
# ============================================================
def virus_once(conn) -> dict:
    stats = {'files': 0, 'new_files': 0, 'suspicious': 0}
    watch_dirs = [os.path.join(PROJECT_ROOT, '_runtime', 'auto_daemons'), FA_DIR]
    snap: dict = {}
    if os.path.exists(SNAPSHOT_FILE):
        try:
            snap = json.load(open(SNAPSHOT_FILE))
        except Exception:
            snap = {}
    suspicious: list = []
    for wd in watch_dirs:
        try:
            for fn in os.listdir(wd):
                if not fn.endswith('.py'):
                    continue
                fp = os.path.join(wd, fn)
                try:
                    st = os.stat(fp)
                    key = f'{wd}/{fn}'
                    sig = f'{st.st_size}:{int(st.st_mtime)}'
                    snap[key] = sig
                    stats['files'] += 1
                    if key not in snap or snap.get(key) != sig:
                        stats['new_files'] += 1
                    body = open(fp, 'r', errors='ignore').read()
                    for pat in VIRUS_MARKS:
                        if re.search(pat, body):
                            suspicious.append(f'{fn}::{pat[:24]}')
                            break
                except Exception:
                    continue
        except Exception:
            continue
    stats['suspicious'] = len(suspicious)
    if suspicious:
        if _hall_task(conn, '防火墙抗病毒告警: 可疑代码特征',
                      f'发现 {len(suspicious)} 个含可疑特征的 py 文件: '
                      f'{suspicious[:5]}, 需人工复核隔离', 'HIGH'):
            _log(conn, 'VIRUS_ALERT', {'files': suspicious[:10]})
    try:
        os.makedirs(PID_DIR, exist_ok=True)
        json.dump(snap, open(SNAPSHOT_FILE, 'w'))
    except Exception:
        pass
    return stats


# ============================================================
# ④ 抗污染: 大厅 + 脑库内容污染扫描
# ============================================================
def pollute_once(conn, batch: int = 50) -> dict:
    stats = {'hall_scanned': 0, 'hall_quarantined': 0,
             'feed_scanned': 0, 'feed_dirty': 0}
    rows = conn.execute(
        "SELECT rowid, IFNULL(title,''), IFNULL(description,'') FROM mt_lab_task_hall "
        "WHERE status IN ('QUEUED','DISPATCHED') ORDER BY rowid DESC LIMIT ?",
        (batch,)).fetchall()
    for rid, title, desc in rows:
        stats['hall_scanned'] += 1
        hay = f'{title} {desc}'.lower()
        hit = [m for m in POLLUTION_MARKS if m in hay]
        if not hit:
            continue
        try:
            conn.execute("UPDATE mt_lab_task_hall SET status='CONTAMINATED' "
                         "WHERE rowid=?", (rid,))
            _log(conn, 'POLLUTE_QUARANTINE', {'task': title[:40], 'marks': hit[:3]})
            stats['hall_quarantined'] += 1
        except Exception:
            pass
    rows = conn.execute(
        "SELECT rowid, IFNULL(payload_preview,'') FROM mt_ai_brain_feed_log "
        "ORDER BY rowid DESC LIMIT ?", (batch,)).fetchall()
    for rid, preview in rows:
        stats['feed_scanned'] += 1
        low = preview.lower()
        if any(m in low for m in POLLUTION_MARKS):
            stats['feed_dirty'] += 1
    if stats['feed_dirty'] > 5:
        if _hall_task(conn, '防火墙抗污染告警: 脑库投喂污染',
                      f'近 {batch} 条投喂中 {stats["feed_dirty"]} 条含污染特征, '
                      f'需溯源投喂方并隔离', 'NORMAL'):
            _log(conn, 'POLLUTE_FEED_ALERT', stats)
    return stats


def _heartbeat():
    """Flow unified_ops 20261023: 改走 Flask /api/internal/heartbeat 代理
    Flask 自己写自己的 WAL 永不 locked (根治守护心跳被 Flask 写锁阻挡 except pass 吞掉)"""
    try:
        _tok_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 '..', '_runtime', '.internal_token')
        _tok = open(_tok_path).read().strip() if os.path.exists(_tok_path) else ''
        import urllib.request as _ur
        _payload = json.dumps({'process_name': DAEMON_NAME,
                               'pid': os.getpid()}).encode()
        _req = _ur.Request('http://127.0.0.1:5001/api/internal/heartbeat',
                           data=_payload,
                           headers={'Content-Type': 'application/json',
                                    'X-Internal-Token': _tok})
        _ur.urlopen(_req, timeout=4)
    except Exception:
        pass  # Flask 重启期间静默, 下轮再试

MODULES = [('attack', attack_once), ('surge', surge_once),
           ('virus', virus_once), ('pollute', pollute_once)]


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'loop'
    if cmd == 'run_all':
        conn = _connect()
        try:
            seeded = ensure_officers(conn)
            out = {name: fn(conn) for name, fn in MODULES}
            out['officers_seeded'] = seeded
        finally:
            conn.close()
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if cmd in dict(MODULES):
        conn = _connect()
        try:
            print(json.dumps(dict(MODULES)[cmd](conn), ensure_ascii=False))
        finally:
            conn.close()
        return 0
    if cmd == 'loop':
        print(f'[{DAEMON_NAME}] 防火墙四抗守护启动 pid={os.getpid()} '
              f'poll={POLL_SECS}s', flush=True)
        while True:
            try:
                conn = _connect()
                try:
                    ensure_officers(conn)
                    for name, fn in MODULES:
                        try:
                            r = fn(conn)
                            if any(v for v in r.values() if isinstance(v, int)):
                                print(f'[{DAEMON_NAME}] {name} {r}', flush=True)
                        except Exception as e:
                            sys.stderr.write(f'[{DAEMON_NAME}] {name}: {e}\n')
                finally:
                    conn.close()
            except Exception as e:
                sys.stderr.write(f'[{DAEMON_NAME}] cycle: {e}\n')
            _heartbeat()
            time.sleep(POLL_SECS)
    return 2


if __name__ == '__main__':
    sys.exit(main())
