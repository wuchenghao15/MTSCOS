#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座托管者 — Andromeda Warden
全系统统一健康扫描 + 异常检测 + AI 自愈接管

纳管子系统:
  1. Flask 5001 (沙盘主服务)
  2. intel_gateway (情报网关, launchd 守护)
  3. fm_listener (央广 FM 监听, launchd 守护)
  4. ai_sandbox_tick_engine (沙盘 tick 引擎)
  5. DB 脑库数据新鲜度

扫描周期: 15s
异常 → 自愈动作 (按优先级):
  Tier 1: launchd 进程死 → bootstrap 重启
  Tier 2: API 连续 3× fail → circuit close + backfill
  Tier 3: DB 空窗 >3min → 触发 backfill API
  Tier 4: CPU/内存打爆 → kill 非关键进程 + 告警

用法:
  python3 andromeda_warden.py &
  launchctl bootstrap gui/$(id -u) com.mtscos.andromeda-warden.plist
"""
import os, sys, re, json, time, threading, subprocess, sqlite3, logging, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[WARDEN][%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("warden")

_DB_PATH = os.environ.get("MTSCOS_DB_PATH") or str(
    Path(__file__).resolve().parent.parent / "database" / "app.db"
)
_FLASK_URL = os.environ.get("MTSCOS_FLASK_URL", "http://127.0.0.1:5001")

# ═══ 纳管子系统注册表 ═══
SUBSYSTEMS = [
    {
        "key": "flask_sandbox",
        "label": "Flask 沙盘 5001",
        # 20261106: 5001 已由 launchd com.mtscos.flask 托管, 自愈必须走 kickstart,
        # 否则 warden 的 T2(pkill+nohup) 会和 launchd 抢进程, 造成 60s 级抖动
        "type": "launchd",
        "launch_label": "com.mtscos.flask",
        "pid_keyword": "modular_start.py",
        "critical": True,
    },
    {
        "key": "intel_gateway",
        "label": "💡 情报网关",
        "type": "launchd",
        "launch_label": "com.mtscos.intel-gateway",
        "pid_keyword": "intel_gateway_daemon",
        "db_table": "mt_intel_brain_feed",
        "freshness_col": "created_at",
        "freshness_max_age_min": 5,
        "restart_cmd": ["launchctl", "bootstrap", "gui/$(id -u)",
                         str(Path.home() / "Library/LaunchAgents/com.mtscos.intel-gateway.plist")],
    },
    {
        "key": "fm_listener",
        "label": "📻 FM 监听",
        "type": "launchd",
        "launch_label": "com.mtscos.fm-listener",
        "pid_keyword": "fm_listener_daemon",
        "db_table": "mt_fm_brain_feed",
        "freshness_col": "created_at",
        "freshness_max_age_min": 10,
        "restart_cmd": ["launchctl", "bootstrap", "gui/$(id -u)",
                         str(Path.home() / "Library/LaunchAgents/com.mtscos.fm-listener.plist")],
    },
    {
        "key": "tick_engine",
        "label": "⏱️ Tick 引擎",
        "type": "process",
        "pid_keyword": "ai_sandbox_tick_engine",
        "restart_cmd": None,  # 由 Flask 主进程守护
    },
    {
        "key": "screen_monitor",
        "label": "📸 屏幕监控",
        "type": "launchd",
        "launch_label": "com.mtscos.screen-monitor",
        "pid_keyword": "screen_monitor_daemon",
        # 事件驱动型 daemon: 没异常时 mt_screen_events 本来就是空, 不能拿它当存活信号。
        # 改用心跳表 —— 线程每轮写 last_heartbeat, 线程死了心跳就停 (进程在也救不了)。
        "db_table": "mt_daemon_registry",
        "db_where": "WHERE process_name='screen_monitor'",
        "freshness_col": "last_heartbeat",
        "freshness_max_age_min": 5,
        "restart_cmd": ["launchctl", "bootstrap", "gui/$(id -u)",
                         str(Path.home() / "Library/LaunchAgents/com.mtscos.screen-monitor.plist")],
    },
    {
        "key": "data_monitor",
        "label": "📊 数据监控",
        "type": "launchd",
        "launch_label": "com.mtscos.data-monitor",
        "pid_keyword": "data_monitor_daemon",
        "db_table": "mt_data_anomalies",
        "freshness_col": "created_at",
        "freshness_max_age_min": 60,
        "restart_cmd": ["launchctl", "bootstrap", "gui/$(id -u)",
                         str(Path.home() / "Library/LaunchAgents/com.mtscos.data-monitor.plist")],
    },
    # ── 20261106 新增: 核心闭环 daemon 全部纳管 ──
    {
        "key": "stock_sandbox",
        "label": "📈 股市沙盒",
        "type": "launchd",
        "launch_label": "com.mtscos.stock-sandbox",
        "pid_keyword": "ai_stock_sandbox_engine.py",
        "db_table": "mt_sandbox_trades",
        "freshness_col": "created_at",
        "freshness_max_age_min": 180,   # 无信号时不出单属正常, 仅兜底
        "restart_cmd": ["launchctl", "kickstart", "-k", "gui/$(id -u)/com.mtscos.stock-sandbox"],
    },
    {
        "key": "hall_dispatch",
        "label": "🏁 任务厅派发",
        "type": "launchd",
        "launch_label": "com.mtscos.hall-dispatch",
        "pid_keyword": "hall_dispatch_demo.py",
        "restart_cmd": ["launchctl", "kickstart", "-k", "gui/$(id -u)/com.mtscos.hall-dispatch"],
    },
    {
        "key": "center_self_drive",
        "label": "🧠 中心自驱",
        "type": "launchd",
        "launch_label": "com.mtscos.center-self-drive",
        "pid_keyword": "ai_center_self_drive_engine.py",
        "restart_cmd": ["launchctl", "kickstart", "-k", "gui/$(id -u)/com.mtscos.center-self-drive"],
    },
    {
        "key": "flask_public",
        "label": "🌐 仙女座门户 8888",
        "type": "launchd",
        "launch_label": "com.mtscos.flask-public",
        "pid_keyword": "start_public_hulk.py",
        "restart_cmd": ["launchctl", "kickstart", "-k", "gui/$(id -u)/com.mtscos.flask-public"],
    },
    {
        "key": "shield_daemon",
        "label": "🛡️ 金盾守护",
        "type": "launchd",
        "launch_label": "com.mtscos.shield-daemon",
        "pid_keyword": "shield_daemon.py",
        "restart_cmd": ["launchctl", "kickstart", "-k", "gui/$(id -u)/com.mtscos.shield-daemon"],
    },
]

# ═══ 资源告警阈值 (只读, 不自动 kill 进程) ═══
_RES_THRESHOLDS = {
    "cpu_warn": 85.0, "cpu_crit": 95.0,
    "mem_warn": 90.0, "mem_crit": 95.0,
    "disk_warn": 90.0, "disk_crit": 95.0,
}

# ═══ 历史状态 (用于趋势检测) ═══
_health_history = {}    # {subsys_key: [(timestamp, ok), ...]}
_recent_failures = {}   # {subsys_key: [(timestamp, reason), ...]}
_taken_actions = {}     # {subsys_key: last_action_timestamp}
_resource_snapshots = [] # [(ts, cpu_pct, mem_pct, disk_pct), ...]
_last_resource_scan = 0

# 阈值
_RECENT_WINDOW_SEC = 120   # 2min 窗口
_FAIL_THRESHOLD = 3         # 连续 3 次失败 → 触发自愈
_COOLDOWN_SEC = 120         # 同一 subsystem 自愈冷却

# ═══ 熔断状态持久化 ═══
def _save_state():
    try:
        state = {"taken_actions": {}, "saved_at": time.time()}
        cutoff = time.time() - 3600
        for k, v in _taken_actions.items():
            if v > cutoff: state["taken_actions"][k] = v
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

def _load_state():
    global _taken_actions
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f:
                state = json.load(f)
            cutoff = time.time() - 3600
            _taken_actions = {k: v for k, v in (state.get("taken_actions") or {}).items() if v > cutoff}
            if _taken_actions:
                log.info("🔄 熔断恢复: %d subsystems cooling", len(_taken_actions))
    except Exception:
        pass

# ═══ 资源扫描器 (只读, 告警但不自动 kill) ═══
def _scan_resources() -> dict:
    result = {"cpu_pct": 0, "mem_pct": 0, "disk_pct": 0, "alerts": [], "ok": True}
    # CPU
    try:
        out = subprocess.run(["top", "-l", "1", "-s", "0", "-n", "0"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.split("\n"):
            if "CPU usage" in line:
                m = re.search(r"([\d.]+)% user.*?([\d.]+)% sys", line)
                if m: result["cpu_pct"] = float(m.group(1)) + float(m.group(2)); break
    except Exception:
        pass
    # 内存
    try:
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
        page_size = 4096; active = 0
        for line in vm.split("\n"):
            if "page size of" in line: page_size = int(re.search(r"(\d+)", line).group(1))
            elif "Pages active" in line: active = int(re.search(r"(\d+)", line).group(1))
        mem = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2).stdout.strip()
        if mem.isdigit() and int(mem) > 0:
            result["mem_pct"] = min(99.0, active * page_size / int(mem) * 100)
    except Exception:
        pass
    # 磁盘
    try:
        df = subprocess.run(["df", "-k", "/"], capture_output=True, text=True, timeout=3).stdout
        for line in df.split("\n")[1:]:
            p = line.split()
            if len(p) >= 5: result["disk_pct"] = float(p[4].rstrip("%")); break
    except Exception:
        pass
    # 告警
    T = _RES_THRESHOLDS
    if result["cpu_pct"] >= T["cpu_crit"]: result["alerts"].append(("CRITICAL", f"CPU {result['cpu_pct']:.1f}%")); result["ok"] = False
    elif result["cpu_pct"] >= T["cpu_warn"]: result["alerts"].append(("WARN", f"CPU {result['cpu_pct']:.1f}%"))
    if result["mem_pct"] >= T["mem_crit"]: result["alerts"].append(("CRITICAL", f"内存 {result['mem_pct']:.1f}%")); result["ok"] = False
    elif result["mem_pct"] >= T["mem_warn"]: result["alerts"].append(("WARN", f"内存 {result['mem_pct']:.1f}%"))
    if result["disk_pct"] >= T["disk_crit"]: result["alerts"].append(("CRITICAL", f"磁盘 {result['disk_pct']:.1f}%")); result["ok"] = False
    elif result["disk_pct"] >= T["disk_warn"]: result["alerts"].append(("WARN", f"磁盘 {result['disk_pct']:.1f}%"))
    # 历史
    _resource_snapshots.append((time.time(), result["cpu_pct"], result["mem_pct"], result["disk_pct"]))
    _resource_snapshots = _resource_snapshots[-120:]
    return result


# ═══ 扫描器 ═══
def _scan_port(port: int, health_url: str = "") -> dict:
    """扫描端口 + 可选 HTTP health"""
    result = {"ok": False, "latency_ms": 0, "http_code": 0, "details": ""}
    # 端口
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-ti", str(port)], capture_output=True, text=True, timeout=3)
        if not out.stdout.strip():
            result["details"] = f"port {port} 未监听"
            return result
    except Exception as e:
        result["details"] = f"lsof err: {e}"
        return result
    # HTTP health
    if health_url:
        import urllib.request
        url = f"http://127.0.0.1:{port}{health_url}"
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                result["http_code"] = r.status
                result["latency_ms"] = int((time.time() - t0) * 1000)
                result["ok"] = (r.status == 200)
        except Exception as e:
            result["details"] = f"http: {e}"
    else:
        result["ok"] = True
    return result


def _scan_launchd(subsys: dict) -> dict:
    """扫描 launchd 进程 + DB 数据新鲜度"""
    result = {"ok": False, "alive": False, "fresh": False, "db_items": 0,
              "last_seen": "", "details": ""}
    label = subsys["launch_label"]
    # launchd 注册
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=3)
        if label in out.stdout:
            result["alive"] = True
    except Exception as e:
        result["details"] += f"launchctl err: {e}; "
    # PID 进程
    try:
        out = subprocess.run(["pgrep", "-f", subsys["pid_keyword"]],
                             capture_output=True, text=True, timeout=3)
        if out.stdout.strip():
            result["alive"] = True
            result["details"] += f"pid={out.stdout.strip()[:20]}"
    except Exception:
        pass
    # DB 数据新鲜度 (仅配置了 db_table 的子系统)
    if not subsys.get("db_table"):
        result["fresh"] = True
        result["ok"] = result["alive"]
        return result
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=3)
        cur = conn.cursor()
        where = subsys.get("db_where", "")
        cur.execute(f"SELECT COUNT(*) FROM {subsys['db_table']} {where}")
        result["db_items"] = cur.fetchone()[0]
        cur.execute(f"SELECT MAX({subsys['freshness_col']}) FROM {subsys['db_table']} {where}")
        last = cur.fetchone()[0]
        result["last_seen"] = last or ""
        if last:
            try:
                dt = datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S")
                # 库里部分表用 UTC 存, 统一按 UTC 比较
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - dt).total_seconds() / 60
                result["fresh"] = age < subsys["freshness_max_age_min"]
                result["details"] += f"; age={age:.1f}min"
            except Exception:
                pass
        conn.close()
    except Exception as e:
        result["details"] += f"db: {e}"
    result["ok"] = result["alive"] and result["fresh"]
    return result


def _scan_process(subsys: dict) -> dict:
    result = {"ok": False, "alive": False, "details": ""}
    try:
        out = subprocess.run(["pgrep", "-f", subsys["pid_keyword"]],
                             capture_output=True, text=True, timeout=3)
        if out.stdout.strip():
            result["alive"] = True
            result["details"] = f"pid={out.stdout.strip()[:20]}"
    except Exception as e:
        result["details"] = str(e)
    result["ok"] = result["alive"]
    return result


# ═══ AI 自愈 ═══
def _record_failure(key: str, reason: str):
    now = time.time()
    _recent_failures.setdefault(key, [])
    _recent_failures[key].append((now, reason))
    # 只留窗口内的
    _recent_failures[key] = [
        (t, r) for t, r in _recent_failures[key]
        if now - t < _RECENT_WINDOW_SEC
    ]


def _should_heal(key: str) -> bool:
    """窗口内连续 ≥N 次失败 + 冷却已过 → 可以自愈"""
    now = time.time()
    failures = _recent_failures.get(key, [])
    recent_health = _health_history.get(key, [])
    # 至少 N 次失败
    if len(failures) < _FAIL_THRESHOLD:
        return False
    # 最近 N 次 health 全是 fail
    last_n_ok = [h[1] for h in recent_health[-_FAIL_THRESHOLD:]]
    if last_n_ok and any(last_n_ok):
        return False
    # 冷却
    last_action = _taken_actions.get(key, 0)
    if now - last_action < _COOLDOWN_SEC:
        log.info("  ⏳ %s 冷却中, 剩余 %.0fs", key, _COOLDOWN_SEC - (now - last_action))
        return False
    return True


def _heal(subsys: dict, scan_result: dict):
    """AI 接管: 按 tier 执行自愈"""
    key = subsys["key"]
    now = time.time()
    _taken_actions[key] = now

    log.warning("🤖 AI 接管 %s — 开始自愈", subsys["label"])

    # ── Tier 1: launchd 重启 ──
    if subsys["type"] == "launchd":
        label = subsys["launch_label"]
        plist_path = str(Path.home() / f"Library/LaunchAgents/{label}.plist")
        log.info("  [T1] bootout %s", label)
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                       capture_output=True, timeout=5)
        subprocess.run(["pkill", "-9", "-f", subsys["pid_keyword"]],
                       capture_output=True, timeout=3)
        time.sleep(2)
        log.info("  [T1] bootstrap %s", label)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", plist_path],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            log.info("  ✅ %s launchd 重启成功", subsys["label"])
        else:
            log.error("  ❌ bootstrap 失败: %s", r.stderr[:200])
            return
        time.sleep(8)  # 等启动
        return

    # ── Tier 2: Flask 端口重启 ──
    if subsys["type"] == "port":
        port = subsys["target"]
        log.info("  [T2] kill port %d", port)
        out = subprocess.run(["/usr/sbin/lsof", "-ti", str(port)], capture_output=True, text=True, timeout=3)
        for pid in out.stdout.strip().split("\n"):
            if pid:
                subprocess.run(["kill", "-9", pid], capture_output=True, timeout=3)
        time.sleep(2)
        # 找到 Flask 启动脚本
        for script in ["start_sandbox_hulk.py", "modular_start.py"]:
            p = Path(__file__).resolve().parent.parent / script
            if p.exists():
                log.info("  [T2] nohup %s", script)
                subprocess.Popen(
                    ["python3", script] +
                    (["5001"] if "modular" in script else []),
                    cwd=str(p.parent),
                    stdout=open("/tmp/flask_recover.log", "a"),
                    stderr=subprocess.STDOUT,
                )
                break
        time.sleep(6)
        return

    # ── Tier 3: DB 空窗 → 启动 backfill ──
    if subsys["type"] == "process" or not scan_result.get("fresh", True):
        log.info("  [T3] 数据空窗: 尝试触发 backfill")
        try:
            import urllib.request
            urllib.request.urlopen(
                f"{_FLASK_URL}/api/sandbox/intel/recent?limit=5",
                timeout=5,
            )
        except Exception as e:
            log.warning("  backfill http: %s", e)


# ═══ 主扫描循环 ═══
def _record_health(key: str, ok: bool):
    now = time.time()
    _health_history.setdefault(key, [])
    _health_history[key].append((now, ok))
    # 只留最近 300 条
    _health_history[key] = _health_history[key][-300:]


def scan_all():
    """扫描所有子系统 + 资源层 + 触发自愈"""
    global _last_resource_scan
    t0 = time.time()
    summary = []

    # 主扫描: 各子系统 (保持原有自愈逻辑不变)
    for subsys in SUBSYSTEMS:
        key = subsys["key"]
        if subsys["type"] == "port":
            r = _scan_port(subsys["target"], subsys.get("health_url", ""))
        elif subsys["type"] == "launchd":
            r = _scan_launchd(subsys)
        elif subsys["type"] == "process":
            r = _scan_process(subsys)
        else:
            r = {"ok": False, "details": "unknown type"}

        ok = r.get("ok", False)
        _record_health(key, ok)
        summary.append((subsys["label"], ok, r))

        if not ok:
            reason = r.get("details", "unknown")
            _record_failure(key, reason)
            log.warning("❌ %s: %s", subsys["label"], reason[:120])
            # AI 自愈 (冷却机制已在 _taken_actions 中)
            if _should_heal(key):
                _heal(subsys, r)
        else:
            if key in _recent_failures and len(_recent_failures[key]) > 0:
                _recent_failures[key] = []
                log.info("✅ %s 恢复正常", subsys["label"])

    # 资源层扫描 (每 4 轮一次, 只记录告警不自动 kill 进程)
    if time.time() - _last_resource_scan >= 60:
        _last_resource_scan = time.time()
        try:
            res = _scan_resources()
            if res.get("alerts"):
                for sev, msg in res["alerts"]:
                    icon = {"CRITICAL": "🔴", "WARN": "🟡"}.get(sev, "⚪")
                    log.warning("%s [资源告警] %s", icon, msg)
        except Exception as e:
            log.debug("res scan err: %s", e)

    # 熔断状态持久化 (每轮都存, 防止进程重启丢失冷却)
    _save_state()

    # 汇总日志 (每 5 轮打一次)
    alive = sum(1 for _, ok, _ in summary if ok)
    total = len(summary)
    icon = "💚" if alive == total else "🟡" if alive >= total - 1 else "🔴"
    labels = [f"{label}={'🟢' if ok else '🔴'}" for label, ok, _ in summary]
    # 资源信息 (每轮都附带最新快照)
    res_info = ""
    if _resource_snapshots:
        last = _resource_snapshots[-1]
        res_info = f" | 💻{last[1]:.0f}% 🧠{last[2]:.0f}% 💾{last[3]:.0f}%"
    log.info("%s 全托管 %d/%d | %s%s (%.1fs)", icon, alive, total,
             " | ".join(labels), res_info, time.time() - t0)


def health_endpoint() -> dict:
    """供 Flask /api/sandbox/warden/status 调用"""
    result = {"subsystems": [], "action_log": [], "scanned_at": datetime.now().isoformat(),
              "resources": None, "fused_managed": True}
    for subsys in SUBSYSTEMS:
        key = subsys["key"]
        last_health = _health_history.get(key, [])
        ok = last_health[-1][1] if last_health else False
        failures = len(_recent_failures.get(key, []))
        result["subsystems"].append({
            "key": key, "label": subsys["label"],
            "ok": ok, "recent_failures": failures,
            "last_action_ts": _taken_actions.get(key, 0),
            "type": subsys["type"],
        })
    # 最新资源快照
    if _resource_snapshots:
        last = _resource_snapshots[-1]
        result["resources"] = {
            "ts": datetime.fromtimestamp(last[0]).strftime("%H:%M:%S"),
            "cpu_pct": round(last[1], 1),
            "mem_pct": round(last[2], 1),
            "disk_pct": round(last[3], 1),
        }
    # 熔断中 (冷却期内) 的子系统
    result["cooling_down"] = [
        {"key": k, "remaining_sec": max(0, _COOLDOWN_SEC - (time.time() - v))}
        for k, v in _taken_actions.items()
        if time.time() - v < _COOLDOWN_SEC
    ]
    return result


def run():
    """主守护循环"""
    _load_state()  # 恢复上一轮的熔断冷却状态
    log.info("🎯 Andromeda Warden v2.0 全托管启动 — 纳管 %d 个子系统", len(SUBSYSTEMS))
    for s in SUBSYSTEMS:
        log.info("  • %s (%s)", s["label"], s["type"])

    scan_all()

    cycle = 0
    while True:
        cycle += 1
        try:
            scan_all()
        except Exception as e:
            log.error("scan err: %s", e)
        time.sleep(15)


if __name__ == "__main__":
    run()
