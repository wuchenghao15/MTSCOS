#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🛡️ autonomous_overseer — 仙女座全自动托管的**进程守护 daemon**

每 300s 巡检所有 MTSCOS 关键进程:
  1. :8888 Flask 公网 (start_public_hulk.py)
  2. :5001 Gobelin 古灵阁 (modular_start.py 或 server_real_db.py)
  3. Ollama (localhost:11434)
  4. emergency-guardian daemon
  5. 所有 launchd 里注册的 MTSCOS daemon

死了 → launchctl kickstart -k → 拉起
崩溃 → 记录到 mt_center_evolution_log (event=OVERSEER_REPAIR_APPLIED)
健康 → 记录到 mt_center_evolution_log (event=OVERSEER_HEALTH_OK)

完全不需要人工干预 — 人类脱离后, 这是最后一道守护屏障。
"""
from __future__ import annotations
import sqlite3, sys, os, json, time, subprocess, traceback, urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'database', 'app.db')
LOG = os.path.join(BASE, '_runtime', 'logs', 'autonomous_overseer.log')
os.makedirs(os.path.dirname(LOG), exist_ok=True)

PID = os.getpid()
HOSTNAME = os.uname().nodename

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] 🛡️ overseer: {msg}"
    print(line, flush=True)
    try:
        with open(LOG, 'a') as f:
            f.write(line + '\n')
    except Exception: pass

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c

def _kill_launchctl(label):
    """kickstart 一个 launchd service"""
    try:
        r = subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/{label}'],
                          capture_output=True, text=True, timeout=15)
        ok = r.returncode == 0
        log(f"   kickstart -k {label}: {'✅ OK' if ok else f'❌ {r.stderr[:100]}'}")
        return ok
    except Exception as e:
        log(f"   kickstart {label} 异常: {e}")
        return False

def _check_port(port):
    """检查端口是否 LISTENING"""
    try:
        r = subprocess.run(['lsof', '-i', f':{port}', '-sTCP:LISTEN', '-t'],
                          capture_output=True, text=True, timeout=5)
        return r.returncode == 0 and r.stdout.strip() != ''
    except Exception: return False

def _check_ollama():
    """检查 Ollama API 是否可达"""
    try:
        req = urllib.request.Request('http://localhost:11434/api/tags')
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception: return False

def _check_http(path, port=8888):
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}')
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception: return False

def _check_launchd(label):
    """检查 launchd service 是否有正整数 PID 在跑
    
    两种方式取 PID (优先用 print, 因为 list<label> 输出是 plist dict 不是表格):
    1. launchctl print → regex 'pid = 数字'
    2. launchctl list | grep label → tab 表格第 1 列
    """
    try:
        uid = subprocess.run(['id', '-u'], capture_output=True, text=True).stdout.strip()
        # 方式 1: print 输出里找 pid = 数字
        r = subprocess.run(['launchctl', 'print', f'gui/{uid}/{label}'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.split('\n'):
            line = line.strip()
            if line.startswith('pid = '):
                try:
                    pid = int(line.split('=')[1].strip())
                    return pid > 0  # 正 PID = 活着
                except ValueError:
                    continue
        # 方式 2: 全量 list 里 grep
        r2 = subprocess.run(['launchctl', 'list'], capture_output=True, text=True, timeout=5)
        for line in r2.stdout.split('\n'):
            if label in line:
                parts = line.split()
                if parts and parts[0].isdigit():
                    return int(parts[0]) > 0
        return False
    except Exception: return False

# 关键守护对象列表 (按优先级)
CRITICAL_SERVICES = [
    # (name, launchd_label, health_check, repair_action)
    ('Ollama 大模型',          'com.mtscos.ollama',         lambda: _check_ollama(),                 lambda: _kill_launchctl('com.mtscos.ollama')),
    ('Flask 公网 :8888',      'com.mtscos.flask-public',   lambda: _check_http('/health', 8888),     lambda: _kill_launchctl('com.mtscos.flask-public')),
    ('Gobelin :5001',         'com.mtscos.flask',          lambda: _check_port(5001),                lambda: _kill_launchctl('com.mtscos.flask')),
    ('Emergency Guardian 30s','com.mtscos.emergency-guardian', lambda: _check_launchd('com.mtscos.emergency-guardian'), lambda: _kill_launchctl('com.mtscos.emergency-guardian')),
    ('Andromeda Warden',      'com.mtscos.andromeda-warden', lambda: _check_launchd('com.mtscos.andromeda-warden'), lambda: _kill_launchctl('com.mtscos.andromeda-warden')),
    ('Center Self-Drive',     'com.mtscos.center-self-drive', lambda: _check_launchd('com.mtscos.center-self-drive'), lambda: _kill_launchctl('com.mtscos.center-self-drive')),
    ('FM Listener',           'com.mtscos.fm-listener',     lambda: _check_launchd('com.mtscos.fm-listener'), lambda: _kill_launchctl('com.mtscos.fm-listener')),
    ('Shield Daemon',         'com.mtscos.shield-daemon',   lambda: _check_launchd('com.mtscos.shield-daemon'), lambda: _kill_launchctl('com.mtscos.shield-daemon')),
    ('Auto Trigger Daemon',   'com.mtscos.auto-trigger',    lambda: _check_launchd('com.mtscos.auto-trigger'), lambda: _kill_launchctl('com.mtscos.auto-trigger')),
    ('Autonomous Overseer',   'com.mtscos.autonomous-overseer', lambda: _check_launchd('com.mtscos.autonomous-overseer'), lambda: _kill_launchctl('com.mtscos.autonomous-overseer')),
]

# 低优先级: 每天一次的 cron-like services — 死了就 kickstart 但不频繁重试
PERIODIC_SERVICES = [
    'com.mtscos.bank-daily', 'com.mtscos.audit-daily', 'com.mtscos.weekly-audit',
    'com.mtscos.gobelin-daily-pnl', 'com.mtscos.meeting-auto',
    'com.mtscos.doc-sync', 'com.mtscos.doc-updater',
    'com.mtscos.roundtable_orchestrator',
]

def _log_evolution(c, center, event, detail):
    try:
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail, created_at)
            VALUES (?, ?, ?, ?)""",
            (center, event, detail[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.commit()
    except Exception: pass

def scan_once(repair=False):
    """巡检一次 — 返回 dict"""
    results = []
    c = db()
    try:
        all_ok = True
        for name, label, health_fn, repair_fn in CRITICAL_SERVICES:
            try:
                ok = health_fn()
            except Exception as e:
                ok = False
                log(f"   health check 异常 {name}: {e}")
            status = 'OK' if ok else 'DOWN'
            results.append({'name': name, 'label': label, 'status': status})
            if not ok:
                all_ok = False
                log(f"   ❌ {name}  DOWN → 尝试修复...")
                _log_evolution(c, 'andromeda', 'OVERSEER_DETECT_DOWN',
                               json.dumps({'name': name, 'label': label, 'hostname': HOSTNAME}, ensure_ascii=False))
                if repair:
                    _repair_start = time.time()
                    fixed = repair_fn()
                    _repair_elapsed = time.time() - _repair_start
                    results[-1]['repaired'] = fixed
                    results[-1]['repair_ms'] = int(_repair_elapsed * 1000)
                    if fixed:
                        log(f"   ✅ {name} 修复成功 ({int(_repair_elapsed*1000)}ms)")
                        _log_evolution(c, 'andromeda', 'OVERSEER_REPAIR_APPLIED',
                                       json.dumps({'name': name, 'label': label, 'repair_ms': int(_repair_elapsed*1000)}, ensure_ascii=False))
                    else:
                        log(f"   ❌ {name} 修复失败")
                        _log_evolution(c, 'andromeda', 'OVERSEER_REPAIR_FAILED',
                                       json.dumps({'name': name, 'label': label}, ensure_ascii=False))

        # 定期任务巡检
        for label in PERIODIC_SERVICES:
            ok = _check_launchd(label)
            results.append({'name': label, 'label': label, 'status': 'OK' if ok else 'DOWN'})
            if not ok and repair:
                _kill_launchctl(label)
                _log_evolution(c, 'andromeda', 'OVERSEER_PERIODIC_RESTART',
                               json.dumps({'label': label}, ensure_ascii=False))

        if all_ok and repair:
            _log_evolution(c, 'andromeda', 'OVERSEER_HEALTH_OK',
                           json.dumps({'healthy': len(results), 'hostname': HOSTNAME}, ensure_ascii=False))
    finally:
        c.close()

    down_count = sum(1 for r in results if r['status'] == 'DOWN')
    log(f"   📊 巡检完成: total={len(results)}, down={down_count}")
    return results

def main():
    log(f"🛡️ autonomous_overseer 启动 (pid={PID}, host={HOSTNAME})")
    log(f"   ✅ 守护 {len(CRITICAL_SERVICES)} 个关键服务 + {len(PERIODIC_SERVICES)} 个定期任务")
    log(f"   ✅ 每 300s 巡检一次, 死了自动 kickstart -k 拉起")

    cycle = 0
    while True:
        cycle += 1
        log(f"   ════ 巡检 #{cycle} ════")
        try:
            scan_once(repair=True)
        except Exception as e:
            log(f"   ❌ 巡检异常: {e}")
            traceback.print_exc()
        time.sleep(300)  # 5min

if __name__ == '__main__':
    main()
