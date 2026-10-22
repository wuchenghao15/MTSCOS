#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通信链路守护 (Link Guard)
==========================
flow_link_guard_20261022 · 私网主通道 + 公网兜底通道

用户要求:
  ① 与服务器(Mac mini)保持通讯
  ② 若通讯断联, 至少保证服务器与公网的信息是共通的

三通道探测 (每轮全量):
  LOCAL   127.0.0.1:8888 (开发机 Flask) + 127.0.0.1:5001 (PROD)
  PRIVATE ssh 100.106.220.96 + http://100.106.220.96:8888/api/health  (Tailscale 私网)
  PUBLIC  https://mtos.site/api/health                                (Cloudflare Tunnel 公网)

状态机:
  LINK_OK              三通道全通
  DEGRADED_PUBLIC_ONLY 私网断 / 公网通  → 信息交换自动切到公网通道, 服务器未脱离公网
  PUBLIC_DOWN          公网断 / 私网通  → SSH 进 Mini kickstart 隧道自愈
  SERVER_ISOLATED      私网+公网全断    → 最高级告警 + 脑库投喂

兜底逻辑 (用户第②点):
  只要公网通道通, 即使私网 ssh 断开, 也能通过 https://mtos.site 读取服务器状态
  并写入本机库 → 服务器与公网的信息始终保持共通。
  反之公网断而私网通, 立刻用 SSH 拉起 cloudflared (KeepAlive 之外的一层主动自愈)。

落库:
  mt_link_guard_probe  每次探测明细
  mt_link_guard_event  状态变化
  mt_ai_brain_feed_log 状态变化投喂脑库

用法:
  python3 engines/ai_link_guard_engine.py --init
  python3 engines/ai_link_guard_engine.py --once
  python3 engines/ai_link_guard_engine.py --status
  python3 engines/ai_link_guard_engine.py --loop 120
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

FLOW_ID = 'flow_link_guard_20261022'
_FA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = (os.environ.get('MTSCOS_DB_PATH')
           or os.path.join(_FA, 'database', 'app.db'))

PRIVATE_HOST = os.environ.get('MTSCOS_LINK_PRIVATE_HOST', '100.106.220.96')
PRIVATE_HTTP = os.environ.get('MTSCOS_LINK_PRIVATE_HTTP',
                              f'http://{PRIVATE_HOST}:8888/api/health')
PUBLIC_HTTP = os.environ.get('MTSCOS_LINK_PUBLIC_HTTP',
                             'https://mtos.site/api/health')
LOCAL_HTTP = os.environ.get('MTSCOS_LINK_LOCAL_HTTP', 'http://127.0.0.1:8888/api/health')
PROD_HTTP = os.environ.get('MTSCOS_LINK_PROD_HTTP', 'http://127.0.0.1:5001/api/health')
TUNNEL_LABEL = 'com.mtscos.cloudflare-tunnel'

LOCK_FILE = '/tmp/mtscos_link_guard.lock'
STATE_FILE = '/tmp/mtscos_link_guard_state.json'

DDL = [
    """CREATE TABLE IF NOT EXISTS mt_link_guard_probe (
    probe_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now','localtime')),
    local_ok INTEGER, local_detail TEXT,
    private_ok INTEGER, private_detail TEXT,
    public_ok INTEGER, public_detail TEXT,
    wan_ok INTEGER, wan_detail TEXT,
    state TEXT, heal_action TEXT, flow_id TEXT
)""",
    """CREATE TABLE IF NOT EXISTS mt_link_guard_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now','localtime')),
    from_state TEXT, to_state TEXT, detail TEXT, flow_id TEXT
)""",
    "CREATE INDEX IF NOT EXISTS idx_linkguard_probe_ts ON mt_link_guard_probe(ts)",
    "CREATE INDEX IF NOT EXISTS idx_linkguard_event_ts ON mt_link_guard_event(ts)",
]


# ────────────────────────── 基础 ──────────────────────────
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute('PRAGMA busy_timeout=15000')
    conn.row_factory = sqlite3.Row
    return conn


def init_tables() -> None:
    conn = _db()
    try:
        for sql in DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _http(url: str, timeout: float = 8.0) -> tuple:
    """返回 (ok, detail) — 只要拿到 <500 的状态码就算链路通。
    401/403 是鉴权墙, 恰恰证明服务活着 (开发机 /api/health 需登录, 服务器角色才放行)。"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MTSCOS-LinkGuard/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.getcode()
            return code < 500, f'http_{code}'
    except urllib.error.HTTPError as e:
        return e.code < 500, f'http_{e.code}'
    except Exception as e:
        return False, type(e).__name__[:24]


def _ssh(cmd: str, timeout: float = 15.0) -> tuple:
    try:
        r = subprocess.run(
            ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
             f'wuchenghao@{PRIVATE_HOST}', cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout or '').strip()
        if r.returncode == 0 and out:
            return True, out.splitlines()[-1][:80]
        err = (r.stderr or '').strip().splitlines()
        return False, (err[-1][:90] if err else f'rc={r.returncode}')
    except subprocess.TimeoutExpired:
        return False, 'ssh_timeout'
    except Exception as e:
        return False, type(e).__name__[:24]


# ────────────────────────── 三通道 ──────────────────────────
def probe_local() -> tuple:
    ok8, d8 = _http(LOCAL_HTTP, 6)
    ok5, d5 = _http(PROD_HTTP, 6)
    return (ok8 and ok5), f'dev8888={d8} prod5001={d5}'


def probe_private() -> tuple:
    """SSH 能真 exec 才算私网通 (sshd 能握手但 fork 失败时判不通)"""
    ok_ssh, d_ssh = _ssh('echo MTSCOS_LINK_OK')
    ok_http, d_http = _http(PRIVATE_HTTP, 6)
    return ok_ssh, f'ssh={d_ssh} http={d_http}'


def probe_public() -> tuple:
    ok, d = _http(PUBLIC_HTTP, 12)
    return ok, f'{PUBLIC_HTTP} → {d}'


def probe_wan() -> tuple:
    """服务器出网能力 (Cloudflare Tunnel 的物理前提)"""
    if not probe_private()[0]:
        return False, 'ssh_unreachable'
    return _ssh('curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://www.baidu.com')


# ────────────────────────── 自愈 ──────────────────────────
def heal_tunnel() -> str:
    """公网断而私网通 → 主动 kickstart 隧道, 越过 launchd 的失败退避"""
    ok, out = _ssh(
        f'launchctl kickstart -k gui/$(id -u)/{TUNNEL_LABEL} >/dev/null 2>&1; '
        f'sleep 6; pgrep -f cloudflared >/dev/null && echo TUNNEL_RESTARTED || echo TUNNEL_DEAD'
    )
    if ok and 'TUNNEL_RESTARTED' in out:
        return 'kickstart_cloudflared_ok'
    return f'kickstart_failed({out})'


# ────────────────────────── 状态机 ──────────────────────────
def classify(local_ok: bool, priv_ok: bool, pub_ok: bool, wan_ok: bool) -> str:
    if priv_ok and pub_ok:
        return 'LINK_OK'
    if pub_ok and not priv_ok:
        return 'DEGRADED_PUBLIC_ONLY'
    if priv_ok and not pub_ok:
        return 'PUBLIC_DOWN' if wan_ok else 'SERVER_NO_WAN'
    return 'SERVER_ISOLATED'


HINTS = {
    'LINK_OK': '私网+公网双通道正常',
    'DEGRADED_PUBLIC_ONLY': '私网断联, 已切公网通道 (服务器仍与公网共通)',
    'PUBLIC_DOWN': '公网断联但私网通, 已尝试自愈隧道',
    'SERVER_NO_WAN': '服务器出网中断, 隧道无法建立 → 需人工检查网络',
    'SERVER_ISOLATED': '私网+公网全断, 服务器已失联',
}


def _last_state() -> str:
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f).get('state') or ''
    except Exception:
        return ''


def _save_state(state: str, payload: dict) -> None:
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'state': state, 'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
                       **payload}, f, ensure_ascii=False)
    except Exception:
        pass


def cycle() -> dict:
    init_tables()
    local_ok, local_d = probe_local()

    priv_ok, priv_d = probe_private()
    wan_ok, wan_d = (True, 'ssh_skip') if not priv_ok else _ssh(
        'curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://www.baidu.com')
    wan_ok = wan_ok and wan_d == '200'

    pub_ok, pub_d = probe_public()

    state = classify(local_ok, priv_ok, pub_ok, wan_ok)
    heal = ''

    # 公网断/服务器无出网, 但私网还能进 → 主动自愈
    if state in ('PUBLIC_DOWN', 'SERVER_NO_WAN') and priv_ok:
        heal = heal_tunnel()
        time.sleep(2)
        pub_ok2, pub_d2 = probe_public()
        if pub_ok2:
            pub_ok, pub_d = pub_ok2, f'{pub_d2}(自愈后)'
            state = 'LINK_OK' if priv_ok else 'DEGRADED_PUBLIC_ONLY'
    # 私网断但公网通 → 兜底: 用公网通道确认服务器存活 (信息仍共通)
    elif state == 'DEGRADED_PUBLIC_ONLY':
        heal = 'fallback_to_public_channel'

    prev = _last_state()
    conn = _db()
    try:
        conn.execute(
            """INSERT INTO mt_link_guard_probe
               (local_ok,local_detail,private_ok,private_detail,public_ok,public_detail,
                wan_ok,wan_detail,state,heal_action,flow_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (int(local_ok), local_d, int(priv_ok), priv_d, int(pub_ok), pub_d,
             int(wan_ok), wan_d, state, heal, FLOW_ID))

        changed = prev != state
        if changed:
            conn.execute(
                """INSERT INTO mt_link_guard_event (from_state,to_state,detail,flow_id)
                   VALUES (?,?,?,?)""",
                (prev or 'INIT', state, HINTS.get(state, ''), FLOW_ID))
            conn.execute(
                """INSERT INTO mt_ai_brain_feed_log (flow_id,feed_target,payload_preview,fed_by)
                   VALUES (?,?,?,?)""",
                (FLOW_ID, 'link_guard',
                 f'链路状态 {prev or "INIT"} → {state}: {HINTS.get(state, "")} | '
                 f'private={priv_d} public={pub_d} wan={wan_d}'[:480],
                 'ai_link_guard_engine'))
        conn.commit()
    finally:
        conn.close()

    _save_state(state, {'private_ok': priv_ok, 'public_ok': pub_ok,
                        'local_ok': local_ok, 'wan_ok': wan_ok, 'heal': heal})
    return {'state': state, 'hint': HINTS.get(state, ''), 'changed': changed,
            'private_ok': priv_ok, 'private_detail': priv_d,
            'public_ok': pub_ok, 'public_detail': pub_d,
            'local_ok': local_ok, 'local_detail': local_d,
            'wan_ok': wan_ok, 'wan_detail': wan_d, 'heal': heal}


# ────────────────────────── CLI ──────────────────────────
def _lock() -> bool:
    try:
        if os.path.exists(LOCK_FILE):
            try:
                pid = int(open(LOCK_FILE).read().split()[0])
                os.kill(pid, 0)
                if time.time() - os.path.getmtime(LOCK_FILE) < 1800:
                    return False
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
            os.remove(LOCK_FILE)
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f'{os.getpid()} {time.time()}'.encode())
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


def show_status() -> None:
    out = {'last_state': _last_state() or 'NONE', 'db': DB_PATH,
           'private_host': PRIVATE_HOST, 'public': PUBLIC_HTTP,
           'lock_exists': os.path.exists(LOCK_FILE)}
    try:
        conn = _db()
        rows = conn.execute(
            'SELECT ts,state,private_ok,public_ok,wan_ok,heal_action '
            'FROM mt_link_guard_probe ORDER BY probe_id DESC LIMIT 5').fetchall()
        out['recent'] = [dict(r) for r in rows]
        out['events'] = [dict(r) for r in conn.execute(
            'SELECT ts,from_state,to_state FROM mt_link_guard_event '
            'ORDER BY event_id DESC LIMIT 5').fetchall()]
        conn.close()
    except Exception as e:
        out['db_error'] = str(e)[:120]
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--loop', type=int, default=0)
    a = ap.parse_args()

    if a.init:
        init_tables()
        print(json.dumps({'ok': True, 'action': 'init', 'db': DB_PATH}, ensure_ascii=False))
        return 0
    if a.status:
        show_status()
        return 0
    if a.once:
        print(json.dumps(cycle(), ensure_ascii=False))
        return 0
    if a.loop:
        if not _lock():
            print('已有实例在跑 (lock 存在)')
            return 0
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(0)))
        try:
            n = 0
            while True:
                n += 1
                try:
                    r = cycle()
                    print(f"[{time.strftime('%H:%M:%S')}] #{n} {r['state']} "
                          f"priv={r['private_ok']} pub={r['public_ok']} "
                          f"wan={r['wan_ok']} heal={r['heal'] or '-'}", flush=True)
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] #{n} ERROR {e}", flush=True)
                time.sleep(a.loop)
        except SystemExit:
            return 0
        finally:
            _unlock()
    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
