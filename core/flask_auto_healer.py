"""
╔══════════════════════════════════════════════════════════════════════════╗
║  🩺 Center 30 自愈引擎 — Flask 崩溃自动恢复                               ║
║                                                                            ║
║  设计原则:                                                                 ║
║  1. 外部守护 —— launchd KeepAlive 是最后防线, 本引擎是快速修复             ║
║  2. 多策略恢复 —— kill→checkpoint→backup restore→restart                  ║
║  3. 熔断机制 —— 连续 5 次快速崩溃 → 降级到 standby DB 运行                 ║
║  4. 可观测 —— 每次恢复都记 mt_sync_log + stdout/stderr 保存               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import signal
import sqlite3
import subprocess
import logging
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

log = logging.getLogger('Center30')

_BASE = Path(__file__).resolve().parent.parent
_DB = _BASE / 'database' / 'app.db'
_SB = _BASE / 'database' / 'app_standby.db'

# Flask 实际启动脚本: 优先 modular_start.py, 回退 server_real_db.py
_FLASK_STARTUPS = [
    f"{sys.executable} -u {_BASE}/modular_start.py --port=5001",
    f"{sys.executable} -u {_BASE}/server_real_db.py",
]
# 用于 pgrep 和 kill 的模式 (取第一个)
_FLASK_KILL_PATTERN = 'modular_start.py'


class FlaskAutoHealer:
    """Center 30: Flask 崩溃自愈引擎"""

    PORT = 5001
    MAX_RECOVERIES = 5       # 熔断阈值: 连崩 5 次 → 降级
    RAPID_CRASH_WINDOW = 30  # 秒: 这个窗口内连续崩溃算 rapid crash

    # Flask 可能的启动脚本 (按优先级 pgrep)
    FLASK_SCRIPTS = ['modular_start.py', 'server_real_db.py', 'app.py', 'wsgi.py']

    def __init__(self):
        self._crash_times: list[float] = []
        self._in_downgrade = False
        self._heal_count = 0

    # ── ① 检测: Flask 是否活着 ──
    def probe(self) -> dict:
        """HTTP 探测 + pgrep 双保险"""
        result = {'http_ok': False, 'process_ok': False, 'pid': None, 'db_locks': 0}

        # 方式 1: curl 健康检查 —— 多个候选路径, 只要任意一个返回 200/401/403 都算活着
        # (401/403 是 auth 拦截, 说明 Flask 确实在响应)
        _HEALTH_PATHS = ['/health', '/api/health', '/', '/index']
        for path in _HEALTH_PATHS:
            try:
                req = urllib.request.Request(f'http://localhost:{self.PORT}{path}')
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status < 500:
                        result['http_ok'] = True
                        break
            except urllib.error.HTTPError as e:
                # 401/403 也算 Flask 活着 (是 auth 拦截不是 Flask 崩了)
                if e.code in (401, 403, 404):
                    result['http_ok'] = True
                    break
            except Exception:
                continue

        # 方式 2: pgrep —— 尝试多个可能的 Flask 启动脚本
        try:
            for script in self.FLASK_SCRIPTS:
                r = subprocess.run(
                    ['pgrep', '-f', script],
                    capture_output=True, text=True, timeout=3)
                pids = r.stdout.strip().split('\n')
                if pids and pids[0]:
                    result['pid'] = int(pids[0])
                    result['process_ok'] = True
                    break
        except Exception:
            pass

        # 方式 3: DB 锁争用
        try:
            r = subprocess.run(
                ['lsof', '-i', f':{self.PORT}', '-sTCP:LISTEN'],
                capture_output=True, text=True, timeout=3)
            result['port_listening'] = bool(r.stdout.strip())
        except Exception:
            result['port_listening'] = False

        # DB 锁数量 (超过 50 就是异常)
        try:
            r = subprocess.run(
                ['lsof', str(_DB)], capture_output=True, text=True, timeout=5)
            result['db_locks'] = len([l for l in r.stdout.split('\n') if str(_DB) in l]) - 1
        except Exception:
            result['db_locks'] = -1

        return result

    # ── ② 恢复策略 ──
    def recover(self, probe_result: dict) -> dict:
        """多策略自动恢复"""
        t0 = time.time()
        result = {'steps': [], 'db_recovered': False, 'downgraded': False}

        # 记录崩溃时间
        self._crash_times.append(time.time())
        # 清理窗口外的
        self._crash_times = [t for t in self._crash_times
                             if time.time() - t < self.RAPID_CRASH_WINDOW]
        rapid_crash = len(self._crash_times) >= self.MAX_RECOVERIES

        if rapid_crash:
            log.warning(f"🩺 Rapid crash 检测: {len(self._crash_times)}/{self.MAX_RECOVERIES} → 触发降级")
            self._in_downgrade = True
            result['downgraded'] = True

        # ── Step 1: kill 僵尸 Flask ──
        if probe_result.get('pid'):
            result['steps'].append(f'kill {probe_result["pid"]}')
            subprocess.run(['kill', '-9', str(probe_result['pid'])], timeout=3)
            time.sleep(2)

        # 确保端口释放
        for _ in range(3):
            try:
                r = subprocess.run(
                    ['lsof', '-i', f':{self.PORT}', '-sTCP:LISTEN', '-t'],
                    capture_output=True, text=True, timeout=2)
                if r.stdout.strip():
                    subprocess.run(['kill', '-9'] + r.stdout.strip().split(),
                                   timeout=3, stderr=subprocess.DEVNULL)
                    time.sleep(1)
                else:
                    break
            except Exception:
                break

        result['steps'].append('port 5001 已释放')

        # ── Step 2: WAL checkpoint + integrity_check ──
        try:
            conn = sqlite3.connect(str(_DB), timeout=10)
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            conn.close()
            result['steps'].append(f'WAL checkpoint + integrity={integrity}')

            if integrity != 'ok':
                log.error(f"💥 DB integrity={integrity} → 尝试从 standby 恢复")
                self._recover_from_standby()
                result['db_recovered'] = True
                result['steps'].append('DB 已从 standby 恢复')
        except Exception as e:
            log.error(f"💥 WAL checkpoint 失败: {e}")
            result['steps'].append(f'checkpoint error: {e}')

        # ── Step 3: 降级模式 ──
        env = os.environ.copy()
        if self._in_downgrade:
            env['MTSCOS_DB_OVERRIDE'] = str(_SB)
            env['MTSCOS_DOWNGRADE'] = '1'
            result['steps'].append('降级模式: 使用 standby DB')

        # ── Step 4: 重启 Flask ──
        log.info(f"🩺 重启 Flask (downgrade={self._in_downgrade})")
        # 优先用 launchd 重启 (如果有的话), 回退到 nohup
        _launchd_label = 'com.mtscos.flask'
        _restart_cmd = None
        try:
            # 先尝试 launchd
            r = subprocess.run(
                ['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/{_launchd_label}'],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                _restart_cmd = f'launchctl kickstart {_launchd_label}'
                result['steps'].append(f'launchd kickstart OK')
        except Exception:
            pass

        if not _restart_cmd:
            # 回退方案: nohup 直接启动
            _startup = _FLASK_STARTUPS[0]
            proc = subprocess.Popen(
                f"cd {_BASE} && nohup {_startup} >> /tmp/flask.out 2>> /tmp/flask.err &",
                shell=True, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _restart_cmd = 'nohup ' + _startup.split(' ')[-1]
            result['steps'].append(f'Flask restarted via nohup')
        else:
            result['steps'].append(f'Flask restarted via launchd')

        # ── Step 5: 验证 ──
        time.sleep(8)
        probe_after = self.probe()
        result['http_ok_after'] = probe_after['http_ok']
        result['process_ok_after'] = probe_after['process_ok']
        result['duration_ms'] = round((time.time() - t0) * 1000)

        if probe_after['http_ok']:
            self._heal_count += 1
            self._crash_times.clear()  # 成功后清空 crash 窗口
            result['status'] = 'RECOVERED'
            log.info(f"🩺 Flask 自愈成功 ✅ ({result['duration_ms']:.0f}ms, 累计 heal #{self._heal_count})")
        else:
            result['status'] = 'FAILED'
            log.error(f"🩺 Flask 自愈失败 ❌ ({result['duration_ms']:.0f}ms)")

        # 写 mt_sync_log
        self._log_recovery(result)
        return result

    def _recover_from_standby(self):
        """DB 损坏 → standby restore"""
        if not _SB.exists():
            log.error(f"💥 standby DB 不存在 {_SB}")
            return False
        backup_path = _DB.parent / f"app.db.pre_heal_{int(time.time())}"
        try:
            import shutil
            shutil.copy2(_DB, backup_path)
            # 用 sqlite3 .backup 命令 (安全)
            subprocess.run(['sqlite3', str(_DB), '.backup', str(backup_path)], timeout=15)
            # standby → main
            subprocess.run(['sqlite3', str(_SB), '.dump'], capture_output=True, timeout=60)
            # 简化: 直接 copy standby 过来
            shutil.copy2(_SB, _DB)
            log.info(f"💾 DB 已从 standby 恢复 → {_DB}")
            return True
        except Exception as e:
            log.error(f"💥 standby restore 失败: {e}")
            return False

    def _log_recovery(self, result: dict):
        """把恢复事件写入 mt_sync_log"""
        try:
            conn = sqlite3.connect(str(_DB), timeout=5)
            # 确保表存在
            conn.execute("""CREATE TABLE IF NOT EXISTS mt_sync_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_type TEXT, direction TEXT, target TEXT, status TEXT,
                rows_changed INTEGER DEFAULT 0, duration_ms REAL DEFAULT 0,
                error_msg TEXT DEFAULT '', backup_path TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')))""")
            conn.execute("""INSERT INTO mt_sync_log
                (sync_type, direction, target, status, duration_ms, error_msg, created_at)
                VALUES ('HEAL', 'flask', 'localhost:5001', ?, ?, ?, ?)""",
                (result['status'], result.get('duration_ms', 0),
                 str(result.get('steps', []))[:500],
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"mt_sync_log 写入失败: {e}")

    # ── CLI: 直接运行自愈检查 ──
    @classmethod
    def run(cls):
        """一次性自愈检查 (供 cron_entry.sh daemon_check 调用)"""
        healer = cls()
        probe = healer.probe()
        if probe['http_ok'] and probe['process_ok']:
            print(f"🩺 Flask OK (PID={probe.get('pid')}, port={probe.get('port_listening')}, db_locks={probe.get('db_locks')})")
            return 0
        print(f"🩺 Flask 异常: http={probe['http_ok']}, process={probe['process_ok']}, db_locks={probe.get('db_locks')}")
        result = healer.recover(probe)
        print(f"   → {result['status']} ({result.get('duration_ms', 0):.0f}ms)")
        return 0 if result.get('http_ok_after') else 1


# CLI 入口
if __name__ == '__main__':
    import sys
    sys.exit(FlaskAutoHealer.run())
