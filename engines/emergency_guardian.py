#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚨 EMERGENCY GUARDIAN CENTER — Ollama + Flask 卡死的终极解药
================================================================
4 层防护 + 根因分析 + 防复发

Layer 1: DETECTION (30s heartbeat)
Layer 2: ISOLATION (卡死隔离, 不影响其他)
Layer 3: RECOVERY (自动恢复)
Layer 4: ROOT CAUSE (根因分析 + 防复发)

用法:
  python3 engines/emergency_guardian.py --loop       # 常驻守护 (launchd 模式)
  python3 engines/emergency_guardian.py --check      # 单次健康检查
  python3 engines/emergency_guardian.py --recover ollama
  python3 engines/emergency_guardian.py --recover flask
"""
import os
import sys
import time
import json
import uuid
import signal
import socket
import sqlite3
import subprocess
import threading
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
import urllib.error
import argparse

# ========== 配置 ==========
FLASK_HOST = '127.0.0.1'
FLASK_PORT = 5001
FLASK_LABEL = 'com.mtscos.flask'

OLLAMA_HOST = '127.0.0.1'
OLLAMA_PORT = 11434
OLLAMA_LABEL = 'com.mtscos.ollama'

HEARTBEAT_INTERVAL = 30  # 秒
HTTP_TIMEOUT = 3         # 秒 (tags/ping)
GENERATE_TIMEOUT = 30    # 秒 (generate 推理)

# 阈值
MEM_WARN_PCT = 90
SWAP_PAGES_FREE_WARN = 0.05  # < 5% 空闲
THREAD_LEAK = 500
FD_LEAK = 500
ZOMBIE_WCHAN_STUCK = 60  # 秒

# 数据库
_GUARDIAN_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'database', 'guardian.db'
)

# ========== 工具函数 ==========
def _now_iso():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _log(msg, level='INFO'):
    tag = {'INFO': 'ℹ️', 'WARN': '⚠️', 'ERROR': '❌', 'CRITICAL': '🔴', 'OK': '✅'}.get(level, 'ℹ️')
    print(f'[{_now_iso()}] {tag} [GUARDIAN] {msg}', flush=True)

def _run(cmd, timeout=10):
    """执行 shell 命令, 返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, '', f'TIMEOUT after {timeout}s'
    except Exception as e:
        return -1, '', str(e)

def _launchctl(label, action):
    """执行 launchctl 操作"""
    uid = os.getuid()
    cmd = f'launchctl {action} gui/{uid}/{label}'
    rc, out, err = _run(cmd, timeout=15)
    return rc, out, err

def _pid_of(name_pattern):
    """根据进程名模式找 PID"""
    rc, out, _ = _run(f'pgrep -f "{name_pattern}"', timeout=5)
    if rc == 0 and out:
        pids = out.strip().split('\n')
        return [int(p) for p in pids if p.strip()]
    return []

def _pid_listen_port(port):
    """找监听指定端口的 PID"""
    rc, out, _ = _run(f'lsof -ti tcp:{port} -sTCP:LISTEN 2>/dev/null', timeout=5)
    if rc == 0 and out:
        return [int(p.strip()) for p in out.strip().split('\n') if p.strip()]
    return []

# ========== Layer 0: Guardian DB ==========
class GuardianDB:
    """守护事件 + 健康日志"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        os.makedirs(os.path.dirname(_GUARDIAN_DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(_GUARDIAN_DB_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS mt_guardian_incident (
            incident_id TEXT PRIMARY KEY,
            service TEXT NOT NULL,
            severity TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            detection_method TEXT,
            recovery_method TEXT,
            recovery_duration_ms REAL,
            success INTEGER,
            root_cause TEXT,
            ps_snapshot TEXT,
            sqlite_wal TEXT,
            ollama_slots TEXT,
            memory_info TEXT,
            occurred_at TEXT DEFAULT (datetime('now','localtime')),
            resolved_at TEXT
        )""")
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS mt_guardian_health_log (
            log_id TEXT PRIMARY KEY,
            check_time TEXT DEFAULT (datetime('now','localtime')),
            ollama_status TEXT,
            ollama_latency_ms REAL,
            flask_status TEXT,
            flask_latency_ms REAL,
            memory_usage_pct REAL,
            swap_ins INTEGER,
            swap_outs INTEGER,
            sqlite_connections INTEGER,
            sqlite_wal_count INTEGER,
            incidents_active INTEGER
        )""")
        self.conn.commit()

    def write_incident(self, service, severity, issue_type, detection_method='',
                       recovery_method=None, recovery_duration_ms=None,
                       success=None, root_cause=None, ps_snapshot=None,
                       sqlite_wal=None, ollama_slots=None, memory_info=None):
        incident_id = f'INC-{uuid.uuid4().hex[:12].upper()}'
        try:
            self.conn.execute(
                """INSERT INTO mt_guardian_incident
                   (incident_id, service, severity, issue_type, detection_method,
                    recovery_method, recovery_duration_ms, success, root_cause,
                    ps_snapshot, sqlite_wal, ollama_slots, memory_info)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (incident_id, service, severity, issue_type, detection_method,
                 recovery_method, recovery_duration_ms, success,
                 json.dumps(root_cause, ensure_ascii=False) if root_cause else None,
                 json.dumps(ps_snapshot, ensure_ascii=False) if ps_snapshot else None,
                 json.dumps(sqlite_wal, ensure_ascii=False) if sqlite_wal else None,
                 json.dumps(ollama_slots, ensure_ascii=False) if ollama_slots else None,
                 json.dumps(memory_info, ensure_ascii=False) if memory_info else None)
            )
            self.conn.commit()
        except Exception as e:
            _log(f"写入 incident 失败: {e}", 'ERROR')
        return incident_id

    def resolve_incident(self, incident_id, recovery_method, duration_ms):
        try:
            self.conn.execute(
                """UPDATE mt_guardian_incident
                   SET recovery_method=?, recovery_duration_ms=?, success=1,
                       resolved_at=datetime('now','localtime')
                   WHERE incident_id=?""",
                (recovery_method, duration_ms, incident_id)
            )
            self.conn.commit()
        except Exception as e:
            _log(f"更新 incident 失败: {e}", 'ERROR')

    def write_health_log(self, **kwargs):
        log_id = f'HL-{uuid.uuid4().hex[:12].upper()}'
        cols = ['ollama_status', 'ollama_latency_ms', 'flask_status',
                'flask_latency_ms', 'memory_usage_pct', 'swap_ins',
                'swap_outs', 'sqlite_connections', 'sqlite_wal_count',
                'incidents_active']
        vals = [kwargs.get(c) for c in cols]
        try:
            self.conn.execute(
                """INSERT INTO mt_guardian_health_log
                   (log_id, ollama_status, ollama_latency_ms, flask_status,
                    flask_latency_ms, memory_usage_pct, swap_ins, swap_outs,
                    sqlite_connections, sqlite_wal_count, incidents_active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [log_id] + vals
            )
            self.conn.commit()
            # 只保留最近 1000 条, 防止日志膨胀
            self.conn.execute(
                """DELETE FROM mt_guardian_health_log
                   WHERE log_id NOT IN (
                       SELECT log_id FROM mt_guardian_health_log
                       ORDER BY check_time DESC LIMIT 1000)"""
            )
        except Exception as e:
            _log(f"写入 health_log 失败: {e}", 'ERROR')

    def active_incidents_count(self):
        try:
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM mt_guardian_incident WHERE resolved_at IS NULL"
            )
            return cur.fetchone()[0]
        except Exception:
            return 0


# ========== Layer 1: DETECTION ==========
class Detector:
    """3 层 Ollama + 4 层 Flask + 系统资源检测"""

    @staticmethod
    def check_ollama() -> dict:
        """Ollama 健康检查
        Layer 1: /api/tags GET (快)
        Layer 2: process alive?
        Layer 3: /api/generate (慢推理)
        """
        result = {
            'service': 'ollama',
            'status': 'UNKNOWN',
            'latency_ms': 0,
            'details': {},
            'issues': []
        }

        # Layer 2: 进程检测
        ollama_pids = _pid_of('ollama serve')
        if not ollama_pids:
            # 也可能是 Ollama.app 启动的
            ollama_pids = _pid_of('ollama')
        result['details']['pids'] = ollama_pids

        # Layer 1: /api/tags
        tags_ok = False
        t0 = time.time()
        try:
            url = f'http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags'
            resp = urlopen(url, timeout=HTTP_TIMEOUT)
            body = resp.read()
            result['latency_ms'] = (time.time() - t0) * 1000
            if resp.status == 200:
                tags_ok = True
                try:
                    data = json.loads(body)
                    models = [m.get('name', '') for m in data.get('models', [])]
                    result['details']['models'] = models[:10]
                except Exception:
                    pass
            else:
                result['issues'].append(f'HTTP {resp.status}')
        except URLError as e:
            result['issues'].append(f'/api/tags 连接失败: {e.reason}')
        except Exception as e:
            result['issues'].append(f'/api/tags 异常: {e}')

        # 综合判定
        if tags_ok and ollama_pids:
            result['status'] = 'HEALTHY'
        elif ollama_pids and not tags_ok:
            result['status'] = 'DEGRADED'
            result['issues'].append('进程存活但 API 不响应')
        elif not ollama_pids:
            result['status'] = 'DOWN'
            result['issues'].append('ollama serve 进程不存在')
        else:
            result['status'] = 'DOWN'

        return result

    @staticmethod
    def check_flask() -> dict:
        """Flask 健康检查
        Layer 1: 端口 LISTEN?
        Layer 2: /api/system/ping
        Layer 3: SQLite WAL 状态
        """
        result = {
            'service': 'flask',
            'status': 'UNKNOWN',
            'latency_ms': 0,
            'details': {},
            'issues': []
        }

        # Layer 1: 端口
        flask_pids = _pid_listen_port(FLASK_PORT)
        if not flask_pids:
            flask_pids = _pid_of(f'modular_start.*--port={FLASK_PORT}')
        result['details']['pids'] = flask_pids

        # Layer 2: ping
        # 🔧 2026-11-08: 判定逻辑升级 —— 只要 Flask 能返回 HTTP 响应 (任何状态码) 就算健康
        # 之前 /index 模板渲染错误返回 500 被误判为 DEGRADED, 但 Flask 进程其实活着
        ping_ok = False
        http_status = None
        t0 = time.time()
        try:
            url = f'http://{FLASK_HOST}:{FLASK_PORT}/index'
            try:
                resp = urlopen(url, timeout=HTTP_TIMEOUT)
                http_status = resp.status
            except urllib.error.HTTPError as http_err:
                http_status = http_err.code
            ping_ok = True  # 有 HTTP 响应就算通
            result['latency_ms'] = (time.time() - t0) * 1000
            if http_status != 200:
                result['issues'].append(f'HTTP {http_status} (进程健康但路由异常)')
        except Exception as e:
            result['issues'].append(f'/index 不响应: {e}')

        # Layer 3: SQLite
        try:
            wal_info = Detector._check_sqlite_wal()
            result['details']['wal'] = wal_info
            if wal_info.get('wal_count', 0) > 5000:
                result['issues'].append(f"SQLite WAL 积压 {wal_info['wal_count']} 页")
        except Exception as e:
            result['issues'].append(f'SQLite 检查失败: {e}')

        # 综合判定
        if flask_pids:
            if ping_ok:
                result['status'] = 'HEALTHY'
            else:
                result['status'] = 'DEGRADED'
                result['issues'].append('进程存活但 HTTP 无响应 (卡死)')
        else:
            result['status'] = 'DOWN'
            result['issues'].append(f'Flask 进程不存在 (端口 {FLASK_PORT} 未监听)')

        return result

    @staticmethod
    def _check_sqlite_wal():
        """检查 Flask 的 SQLite WAL 状态"""
        db_path = os.environ.get('MTSCOS_DB_PATH', '')
        if not db_path or not os.path.exists(db_path):
            # 尝试默认路径
            candidates = [
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'database', 'app.db'),
                os.path.expanduser('~/MTSCOS_PROD/flask-app/database/app.db'),
            ]
            for c in candidates:
                if os.path.exists(c):
                    db_path = c
                    break
        if not db_path or not os.path.exists(db_path):
            return {'error': 'db not found'}

        info = {'db_path': db_path}
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            info['journal_mode'] = conn.execute('PRAGMA journal_mode').fetchone()[0]
            info['page_count'] = conn.execute('PRAGMA page_count').fetchone()[0]
            info['wal_count'] = conn.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()[0]
            info['conn_count'] = len(conn.execute(
                "SELECT * FROM sqlite_master LIMIT 1"
            ).description) if False else 0  # 简化
            conn.close()

            # WAL 文件大小
            wal_file = db_path + '-wal'
            if os.path.exists(wal_file):
                info['wal_size_bytes'] = os.path.getsize(wal_file)
            else:
                info['wal_size_bytes'] = 0
        except Exception as e:
            info['error'] = str(e)
        return info

    @staticmethod
    def check_memory() -> dict:
        """内存/swap 压力检测"""
        info = {'status': 'HEALTHY', 'issues': []}

        # vm_stat
        try:
            rc, out, _ = _run('vm_stat', timeout=5)
            if rc == 0:
                page_size = 0
                pages_free = 0
                for line in out.split('\n'):
                    if 'page size of' in line.lower():
                        page_size = int(line.split('page size of')[1].strip().rstrip('.'))
                    if 'Pages free' in line:
                        pages_free = int(line.split(':')[1].strip().rstrip('.'))

                if page_size > 0 and pages_free > 0:
                    free_pct = pages_free * page_size / (32 * 1024**3)  # 假设 32GB
                    info['pages_free_pct'] = round(free_pct, 4)
                    if free_pct < SWAP_PAGES_FREE_WARN:
                        info['status'] = 'WARN'
                        info['issues'].append(f'物理内存空闲率 {free_pct:.1%} < {SWAP_PAGES_FREE_WARN:.0%}')
        except Exception as e:
            info['issues'].append(f'vm_stat 失败: {e}')

        # Swap 使用
        try:
            rc, out, _ = _run('sysctl vm.swapusage', timeout=5)
            if rc == 0:
                info['swapusage'] = out.strip()
        except Exception:
            pass

        return info

    @staticmethod
    def check_process(pid) -> dict:
        """进程级详细检查 (线程数/FD/wchan)"""
        info = {'pid': pid, 'status': 'HEALTHY', 'issues': []}
        rc, out, _ = _run(f'ps -o pid,stat,pcpu,pmem,threads,etime,wchan -p {pid}', timeout=5)
        if rc == 0:
            lines = out.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 6:
                    info['stat'] = parts[1]
                    info['cpu'] = parts[2]
                    info['mem'] = parts[3]
                    info['threads'] = int(parts[4]) if parts[4].isdigit() else 0
                    info['etime'] = parts[5]
                    info['wchan'] = parts[6] if len(parts) > 6 else ''

                    if info['threads'] > THREAD_LEAK:
                        info['status'] = 'WARN'
                        info['issues'].append(f'线程数 {info["threads"]} > {THREAD_LEAK} (thread leak?)')

        # FD 数
        try:
            rc, out, _ = _run(f'lsof -p {pid} 2>/dev/null | wc -l', timeout=5)
            fd_count = int(out.strip()) if rc == 0 and out.strip().isdigit() else 0
            info['fd_count'] = fd_count
            if fd_count > FD_LEAK:
                info['status'] = 'WARN'
                info['issues'].append(f'FD 数 {fd_count} > {FD_LEAK} (fd leak?)')
        except Exception:
            pass

        return info


# ========== Layer 3: RECOVERY ==========
class Recovery:
    """SOFT → HARD → launchctl 三级恢复"""

    @staticmethod
    def recover_ollama(level='HARD') -> dict:
        """Ollama 恢复 — 走 launchctl (不是手动 kill)"""
        start_ms = time.time()
        result = {'success': False, 'level': level, 'steps': []}

        # Step 1: kill -9 现有 ollama 进程 (无论级别都清)
        pids = _pid_of('ollama')
        if pids:
            for pid in pids:
                _run(f'kill -9 {pid}', timeout=3)
            result['steps'].append(f'kill -9 ollama ({len(pids)} 个)')
            time.sleep(2)

        # Step 2: launchctl kickstart -k 重启
        rc, out, err = _launchctl(OLLAMA_LABEL, 'kickstart -k')
        if rc != 0:
            # 尝试 unload + load
            result['steps'].append(f'kickstart 失败: {err}')
            _launchctl(OLLAMA_LABEL, 'unload')
            time.sleep(1)
            _launchctl(OLLAMA_LABEL, 'load')
            result['steps'].append('fallback: unload+load')
        else:
            result['steps'].append('launchctl kickstart -k ✅')

        # Step 3: 等待 + 验证
        for i in range(15):
            time.sleep(1)
            try:
                url = f'http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags'
                resp = urlopen(url, timeout=2)
                if resp.status == 200:
                    result['success'] = True
                    result['steps'].append(f'✅ Ollama 恢复成功 (等了 {i+1}s)')
                    break
            except Exception:
                pass
        else:
            result['steps'].append('❌ Ollama 恢复失败')

        result['duration_ms'] = (time.time() - start_ms) * 1000
        return result

    @staticmethod
    def recover_flask(level='HARD') -> dict:
        """Flask 恢复 — kill → launchctl kickstart"""
        start_ms = time.time()
        result = {'success': False, 'level': level, 'steps': []}

        # Step 1: kill 所有 Flask 相关进程
        pids = _pid_of('modular_start') + _pid_listen_port(FLASK_PORT)
        pids = list(set(pids))
        if pids:
            for pid in pids:
                _run(f'kill -9 {pid}', timeout=3)
            result['steps'].append(f'kill -9 Flask ({len(pids)} 个)')
            time.sleep(3)

        # Step 2: WAL checkpoint + VACUUM (DB 清理)
        db_info = Detector._check_sqlite_wal()
        if db_info.get('db_path') and os.path.exists(db_info['db_path']):
            try:
                conn = sqlite3.connect(db_info['db_path'], timeout=10)
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                conn.commit()
                conn.close()
                result['steps'].append('✅ WAL checkpoint(TRUNCATE)')
            except Exception as e:
                result['steps'].append(f'WAL checkpoint 失败: {e}')

        # Step 3: launchctl kickstart -k
        rc, out, err = _launchctl(FLASK_LABEL, 'kickstart -k')
        if rc != 0:
            result['steps'].append(f'kickstart 失败: {err}')
            _launchctl(FLASK_LABEL, 'unload')
            time.sleep(1)
            _launchctl(FLASK_LABEL, 'load')
            result['steps'].append('fallback: unload+load')
        else:
            result['steps'].append('launchctl kickstart -k ✅')

        # Step 4: 等待 + 验证
        for i in range(20):
            time.sleep(1)
            try:
                url = f'http://{FLASK_HOST}:{FLASK_PORT}/index'
                resp = urlopen(url, timeout=2)
                if resp.status == 200:
                    result['success'] = True
                    result['steps'].append(f'✅ Flask 恢复成功 (等了 {i+1}s)')
                    break
            except Exception:
                pass
        else:
            result['steps'].append('❌ Flask 恢复失败')

        result['duration_ms'] = (time.time() - start_ms) * 1000
        return result


# ========== Layer 4: ROOT CAUSE ==========
class RootCauseAnalyzer:
    """卡死根因采样"""

    @staticmethod
    def analyze_flask(pids) -> dict:
        """Flask 卡死时的根因分析"""
        analysis = {
            'ps_snapshots': [],
            'memory_analysis': {},
            'thread_leak': False,
            'fd_leak': False,
            'sqlite_locked': False
        }

        for pid in pids:
            # ps 完整快照
            rc, out, _ = _run(f'ps -o pid,stat,pcpu,pmem,rss,vsz,threads,etime,wchan,command -p {pid}', timeout=5)
            if rc == 0 and out:
                analysis['ps_snapshots'].append(out.strip())

            # 线程数
            proc_info = Detector.check_process(pid)
            if proc_info.get('threads', 0) > THREAD_LEAK:
                analysis['thread_leak'] = True
            if proc_info.get('fd_count', 0) > FD_LEAK:
                analysis['fd_leak'] = True

            # vmmap summary
            rc, vmmap_out, _ = _run(f'vmmap -summary {pid} 2>/dev/null | head -20', timeout=10)
            if rc == 0 and vmmap_out:
                analysis['memory_analysis']['vmmap'] = vmmap_out

        # SQLite WAL
        analysis['sqlite_wal'] = Detector._check_sqlite_wal()

        # WAL 文件大小
        wal_size = analysis['sqlite_wal'].get('wal_size_bytes', 0)
        if wal_size > 100 * 1024 * 1024:  # 100MB
            analysis['sqlite_locked'] = True

        return analysis

    @staticmethod
    def analyze_ollama(pids) -> dict:
        """Ollama 挂掉时的根因分析"""
        analysis = {'ps_snapshots': []}
        for pid in pids:
            rc, out, _ = _run(f'ps -o pid,stat,pcpu,pmem,rss,vsz,threads,etime,wchan,command -p {pid}', timeout=5)
            if rc == 0 and out:
                analysis['ps_snapshots'].append(out.strip())

        # Ollama slots 状态 (如果在线)
        try:
            url = f'http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/ps'
            resp = urlopen(url, timeout=2)
            data = json.loads(resp.read())
            analysis['ollama_slots'] = data
        except Exception:
            pass

        return analysis


# ========== EMERGENCY GUARDIAN CORE ==========
class EmergencyGuardian:
    """应急守护中心主类"""

    def __init__(self):
        self.db = GuardianDB()
        self._running = False
        self._last_status = {}
        self._consecutive_failures = {'ollama': 0, 'flask': 0}
        self._recovery_cooldown = {'ollama': 0, 'flask': 0}
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        _log(f'收到信号 {signum}, 优雅退出...', 'WARN')
        self._running = False

    # ---------- 单次检查 ----------
    def run_check(self):
        """执行一轮完整检查"""
        _log('===== 开始健康检查 =====')
        ollama_result = Detector.check_ollama()
        flask_result = Detector.check_flask()
        mem_result = Detector.check_memory()

        results = {'ollama': ollama_result, 'flask': flask_result, 'memory': mem_result}

        # 打印状态
        for svc, r in results.items():
            status_emoji = {'HEALTHY': '✅', 'DEGRADED': '⚠️', 'DOWN': '❌', 'WARN': '⚠️'}.get(
                r['status'], '❓')
            latency = r.get('latency_ms', 0)
            _log(f'{status_emoji} {svc}: {r["status"]} ({latency:.0f}ms)',
                 'OK' if r['status'] == 'HEALTHY' else 'WARN')
            if r.get('issues'):
                for issue in r['issues']:
                    _log(f'  - {issue}', 'ERROR')

        # 写健康日志
        self.db.write_health_log(
            ollama_status=ollama_result['status'],
            ollama_latency_ms=ollama_result.get('latency_ms'),
            flask_status=flask_result['status'],
            flask_latency_ms=flask_result.get('latency_ms'),
            memory_usage_pct=mem_result.get('pages_free_pct'),
            sqlite_connections=flask_result.get('details', {}).get('wal', {}).get('conn_count'),
            sqlite_wal_count=flask_result.get('details', {}).get('wal', {}).get('wal_count'),
            incidents_active=self.db.active_incidents_count()
        )

        self._last_status = results
        return results

    # ---------- 自动恢复触发 ----------
    def _maybe_recover(self, results):
        """根据检测结果决定是否恢复"""
        now = time.time()

        for svc in ('ollama', 'flask'):
            r = results[svc]
            status = r['status']

            if status == 'HEALTHY':
                self._consecutive_failures[svc] = 0
                continue

            self._consecutive_failures[svc] += 1

            # cooldown: 两次恢复至少间隔 60s (防止恢复风暴)
            if now < self._recovery_cooldown[svc]:
                _log(f'{svc}: 恢复冷却中 (cooldown {self._recovery_cooldown[svc] - now:.0f}s), 跳过', 'WARN')
                continue

            # DOWN → 立即恢复, DEGRADED → 连续 3 次再恢复
            need_recover = (status == 'DOWN') or (
                status == 'DEGRADED' and self._consecutive_failures[svc] >= 3)

            if need_recover:
                self._perform_recovery(svc, r)
                self._recovery_cooldown[svc] = now + 60

    def _perform_recovery(self, svc, detect_result):
        """执行恢复流程"""
        _log(f'🚨 {svc} 需要恢复!', 'CRITICAL')

        # 写 incident (检测阶段)
        issue_type = 'API_TIMEOUT' if detect_result['status'] == 'DEGRADED' else 'PROCESS_DEAD'
        incident_id = self.db.write_incident(
            service=svc,
            severity='CRITICAL' if detect_result['status'] == 'DOWN' else 'ERROR',
            issue_type=issue_type,
            detection_method=str(detect_result.get('issues', []))
        )

        # 根因分析
        pids = detect_result.get('details', {}).get('pids', [])
        if svc == 'flask':
            root_cause = RootCauseAnalyzer.analyze_flask(pids)
            self.db.conn.execute(
                "UPDATE mt_guardian_incident SET root_cause=? WHERE incident_id=?",
                (json.dumps(root_cause, ensure_ascii=False), incident_id)
            )
        else:
            root_cause = RootCauseAnalyzer.analyze_ollama(pids)
            self.db.conn.execute(
                "UPDATE mt_guardian_incident SET root_cause=? WHERE incident_id=?",
                (json.dumps(root_cause, ensure_ascii=False), incident_id)
            )
        self.db.conn.commit()

        # 执行恢复
        t0 = time.time()
        if svc == 'ollama':
            recovery = Recovery.recover_ollama(level='HARD')
        else:
            recovery = Recovery.recover_flask(level='HARD')

        duration_ms = (time.time() - t0) * 1000

        # 更新 incident
        self.db.resolve_incident(
            incident_id,
            recovery_method=f"HARD_RESTART_via_launchctl ({', '.join(recovery['steps'][:2])})",
            duration_ms=duration_ms
        )

        # 输出恢复结果
        level = 'OK' if recovery['success'] else 'CRITICAL'
        _log(f'恢复结果: success={recovery["success"]}, 耗时={duration_ms:.0f}ms, steps={recovery["steps"]}', level)

    # ---------- 心跳主循环 ----------
    def heartbeat_loop(self, interval=HEARTBEAT_INTERVAL):
        """30 秒心跳主循环"""
        _log('🚀 EMERGENCY GUARDIAN 已启动!', 'OK')
        _log(f'心跳间隔: {interval}s, Ollama: {OLLAMA_HOST}:{OLLAMA_PORT}, Flask: {FLASK_HOST}:{FLASK_PORT}')
        _log(f'Guardian DB: {_GUARDIAN_DB_PATH}')
        self._running = True

        cycle = 0
        while self._running:
            cycle += 1
            try:
                results = self.run_check()
                self._maybe_recover(results)
            except Exception as e:
                _log(f'心跳循环异常: {e}', 'ERROR')

            # 休眠 (允许信号中断)
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

        _log('👋 EMERGENCY GUARDIAN 优雅退出', 'OK')


# ========== CLI 入口 ==========
def main():
    parser = argparse.ArgumentParser(description='EMERGENCY GUARDIAN CENTER')
    parser.add_argument('--loop', action='store_true', help='常驻守护模式 (launchd)')
    parser.add_argument('--check', action='store_true', help='单次健康检查')
    parser.add_argument('--recover', choices=['ollama', 'flask'], help='手动触发恢复')
    parser.add_argument('--interval', type=int, default=HEARTBEAT_INTERVAL, help='心跳间隔 (秒)')

    args = parser.parse_args()
    guardian = EmergencyGuardian()

    if args.check:
        results = guardian.run_check()
        # 退出码: 0=全健康, 1=有问题
        any_bad = any(r['status'] not in ('HEALTHY', 'WARN')
                      for r in results.values() if isinstance(r, dict))
        sys.exit(1 if any_bad else 0)

    elif args.recover:
        if args.recover == 'ollama':
            recovery = Recovery.recover_ollama()
        else:
            recovery = Recovery.recover_flask()
        _log(f'恢复结果: {json.dumps(recovery, ensure_ascii=False, indent=2)}',
             'OK' if recovery['success'] else 'CRITICAL')
        sys.exit(0 if recovery['success'] else 1)

    elif args.loop:
        guardian.heartbeat_loop(interval=args.interval)

    else:
        # 默认: 单次检查
        guardian.run_check()


if __name__ == '__main__':
    main()
