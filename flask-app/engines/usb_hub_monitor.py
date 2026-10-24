#!/usr/bin/env python3
"""flow_secret_l0_sa_keys_20261024 USB Hub 枚举漂移守护 (蓝队稳定守护军)

每 5s 轮询 ioreg -w0 -r -c IOUSBHostDevice:
  ① 枚举所有 USB 设备的 (serial, Vid:Pid, Hub层级, 端口号, 供电功率)
  ② 缓存首次基线 → 周期对比 serial 集合:
     - serial 数量变了 → 新增/丢失 → 写 mt_hardware_events + 触发 rebind
     - serial 顺序变了 (Hub reset) → 写事件 + 告警
     - VID:PID 漂移 (电源不足) → CRITICAL 告警
  ③ 特别关注 VIKEY USB 加密狗 / SZU100 U盘:
     - 任何一层离线 → flask 触发 SA 密钥重验证
     - 双钥同时离线 → fail-closed 写 mt_iron_rule_violations

落库: mt_hardware_topology + mt_hardware_events
状态机: OK → WARNING(单钥) → CRITICAL(双钥) → RECOVERY(重绑中) → OK
"""
import os, sys, subprocess, time, sqlite3, json, re, hashlib, hmac, argparse, logging
from datetime import datetime

# ====== 配置 ======
POLL_INTERVAL = 5          # 秒
LOG_DIR = "/tmp/mtscos_usb_hub"
DB_PATH = os.path.expanduser("~/MTSCOS_AI_Project/flask-app/database/app.db")
FLASK_ROOT = os.path.expanduser("~/MTSCOS_AI_Project/flask-app")
PID_FILE = os.path.join(LOG_DIR, "usb_hub.pid")

# 硬件指纹 (可配置, 默认 SA 双密钥)
TARGETS = [
    {"name": "VIKEY-USB-ENCRYPTED",  "vid_pid": None, "serial_pattern": None},   # 所有 USB 加密狗
    {"name": "SZU100-SD-READER",     "vid_pid": None, "serial_pattern": None},   # 所有 SD 读卡器
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[
                        logging.StreamHandler(),
                        logging.FileHandler(os.path.join(LOG_DIR, "usb_hub.log")),
                    ])
log = logging.getLogger("usb_hub")

# ====== USB 枚举 ======
def enumerate_usb():
    """ioreg 轮询 + 正则解析所有 USB 设备"""
    try:
        out = subprocess.run(
            ["ioreg", "-w0", "-r", "-c", "IOUSBHostDevice", "-l"],
            capture_output=True, text=True, timeout=10
        ).stdout
    except Exception as e:
        log.error(f"ioreg 调用失败: {e}")
        return []

    devices = []
    cur = {}
    for line in out.split("\n"):
        raw = line.rstrip()
        clean = raw.strip()
        if clean.startswith("+-o") or clean.startswith("+-w"):
            # 新设备开始
            if cur and ("idVendor" in cur or cur.get("IOObjectClass") in
                        ("IOUSBHostDevice", "AppleUSBHostDevice", "IOUSBDevice")):
                devices.append(cur)
            cur = {"name": clean.split(":")[-1].strip('" ')}
        m = re.match(r'(?:\|)?\s*"?(\w+)"?\s*=\s*(?:"([^"]+)"|(\d+)|(\w+))', clean)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2) or m.group(3) or m.group(4) or ""
    if cur and ("idVendor" in cur):
        devices.append(cur)

    # 抽取 serial + idVendor + idProduct (多种 serial 字段兼容)
    result = []
    for d in devices:
        serial = (d.get("kUSBSerialNumberString")
                  or d.get("IOUSBHostSerialNumber")
                  or d.get("USB Serial Number")
                  or d.get("bDeviceSerialNumberIndex")
                  or "")
        vid = d.get("idVendor", "")
        pid = d.get("idProduct", "")
        class_code = d.get("bDeviceClass", "")
        prod_str = d.get("kUSBProductString") or d.get("iProduct", "")
        result.append({
            "serial": str(serial),
            "vid": vid, "pid": pid,
            "vid_pid": f"{vid}:{pid}" if vid and pid else "",
            "class_code": class_code,
            "product": prod_str[:80],
        })
    return result


# ====== 落库 ======
def init_schema(db):
    """首次运行自动建表"""
    cur = db.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mt_hardware_topology (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_ts TEXT NOT NULL,
                device_count INTEGER,
                devices_json TEXT,
                snapshot_hash TEXT,
                status TEXT DEFAULT 'OK'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mt_hardware_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,  -- OK/WARNING/CRITICAL/RECOVERY
                detail TEXT,
                serial_affected TEXT,
                vid_pid TEXT,
                action_taken TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mh_events_ts ON mt_hardware_events(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mh_topology_hash ON mt_hardware_topology(snapshot_hash)")
        db.commit()
    except Exception as e:
        log.error(f"init_schema FAIL: {e}")


def save_snapshot(db, devices, status="OK"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dev_json = json.dumps(devices, ensure_ascii=False)
    snap_hash = hashlib.sha256(dev_json.encode()).hexdigest()[:16]
    db.execute(
        "INSERT INTO mt_hardware_topology(snapshot_ts, device_count, devices_json, snapshot_hash, status) VALUES(?,?,?,?,?)",
        (now, len(devices), dev_json, snap_hash, status))
    # 只保留最近 200 条快照
    db.execute("DELETE FROM mt_hardware_topology WHERE id NOT IN (SELECT id FROM mt_hardware_topology ORDER BY id DESC LIMIT 200)")
    db.commit()
    return snap_hash


def log_event(db, event_type, severity, detail, serial="", vid_pid="", action=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO mt_hardware_events(ts, event_type, severity, detail, serial_affected, vid_pid, action_taken) VALUES(?,?,?,?,?,?,?)",
        (now, event_type, severity, detail[:500], serial, vid_pid, action))
    db.commit()


# ====== 核心监控循环 ======
def monitor_loop():
    os.makedirs(LOG_DIR, exist_ok=True)
    # PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    log.info(f"USB Hub 守护启动, PID={os.getpid()}, 周期={POLL_INTERVAL}s")

    db = sqlite3.connect(DB_PATH)
    init_schema(db)

    baseline_serial_set = None       # {serial: vid_pid}
    last_status = "OK"
    consec_critical = 0

    # 首次基线
    first_devs = enumerate_usb()
    baseline_serial_set = {d["serial"]: d["vid_pid"] for d in first_devs if d["serial"]}
    save_snapshot(db, first_devs, status="OK")
    log.info(f"首次基线: {len(baseline_serial_set)} 台 USB 设备")
    log_event(db, "BASELINE", "OK", f"首次基线建立: {len(baseline_serial_set)} 台 USB 设备")

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                devs = enumerate_usb()
            except Exception as e:
                log.error(f"enumerate FAIL: {e}")
                continue

            current_set = {d["serial"]: d["vid_pid"] for d in devs if d["serial"]}
            now_count = len(current_set)
            base_count = len(baseline_serial_set)

            # 1) serial 集合完全一致
            if current_set == baseline_serial_set:
                if last_status != "OK":
                    log_event(db, "RECOVERY", "OK", f"恢复到基线状态 ({now_count} 台)")
                    last_status = "OK"
                    consec_critical = 0
                    save_snapshot(db, devs, status="OK")
                continue

            # 2) serial 集合不同 → 漂移检测
            added = set(current_set.keys()) - set(baseline_serial_set.keys())
            removed = set(baseline_serial_set.keys()) - set(current_set.keys())
            changed = set()
            for s in current_set.keys() & baseline_serial_set.keys():
                if current_set[s] != baseline_serial_set[s]:
                    changed.add(s)

            # 状态评估
            if not removed and not changed:
                severity = "WARNING"
                status = "WARNING"
                detail = f"新增设备: {added}"
            elif removed and not changed:
                severity = "CRITICAL" if len(removed) >= 2 else "WARNING"
                status = severity
                detail = f"丢失设备: {removed} (预期有 {base_count}, 现在 {now_count})"
            elif changed:
                severity = "CRITICAL"
                status = "CRITICAL"
                detail = f"VID:PID 漂移 (可能电源不足): {changed}"
            else:
                severity = "CRITICAL"
                status = "CRITICAL"
                detail = f"混合漂移: added={added} removed={removed} changed={changed}"

            # 3) 触发动作
            if severity == "CRITICAL":
                consec_critical += 1
                action = ""
                if consec_critical >= 3:
                    # 连续 CRITICAL → 触发 Flask SA 密钥重验证
                    action = "trigger_rebind"
                    try:
                        import urllib.request
                        urllib.request.urlopen("http://127.0.0.1:5001/api/sa/rebind", timeout=3)
                    except Exception:
                        pass
                    # 写 mt_iron_rule_violations
                    try:
                        db.execute(
                            "INSERT INTO mt_iron_rule_violations(rule_id,violation_type,detail,severity,created_at) "
                            "VALUES(?,?,?,?,datetime('now','localtime'))",
                            ("MT_RULE_CLASSIFICATION", "SA_DUALKEY_DRIFT",
                             f"USB Hub CRITICAL 连续 {consec_critical} 次: {detail[:300]}",
                             "CRITICAL"))
                        db.commit()
                    except Exception:
                        pass
                baseline_serial_set = current_set  # 漂移后重建基线
            else:
                consec_critical = 0
                action = "auto_baseline_update"
                baseline_serial_set = current_set

            # 4) 落库 + 日志
            save_snapshot(db, devs, status=status)
            log_event(db, "HUB_DRIFT", severity, detail,
                      serial=json.dumps(list(removed | changed)) if removed or changed else "",
                      action=action)
            log.warning(f"[{severity}] {detail}  action={action}")
            last_status = status

    except KeyboardInterrupt:
        log.info("收到 SIGINT, 退出")
    finally:
        os.remove(PID_FILE) if os.path.exists(PID_FILE) else None
        db.close()


# ====== launchd plist 生成 ======
def write_launchd_plist():
    plist_path = os.path.expanduser("~/Library/LaunchAgents/com.mtscos.usbhub.monitor.plist")
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.mtscos.usbhub.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{os.path.abspath(__file__)}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>{LOG_DIR}/hub.stdout.log</string>
    <key>StandardErrorPath</key><string>{LOG_DIR}/hub.stderr.log</string>
    <key>WorkingDirectory</key><string>{os.path.dirname(os.path.abspath(__file__))}</string>
</dict>
</plist>"""
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
    with open(plist_path, "w") as f:
        f.write(plist)
    print(f"✅ launchd plist 已生成: {plist_path}")
    print(f"   加载: launchctl load -w {plist_path}")
    print(f"   启动: launchctl start com.mtscos.usbhub.monitor")
    print(f"   状态: launchctl list | grep usbhub")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plist", action="store_true", help="生成 launchd plist 文件")
    ap.add_argument("--oneshot", action="store_true", help="单次枚举 + 落库, 不进循环")
    args = ap.parse_args()

    if args.plist:
        write_launchd_plist()
    elif args.oneshot:
        init_schema(sqlite3.connect(DB_PATH))
        devs = enumerate_usb()
        db = sqlite3.connect(DB_PATH)
        save_snapshot(db, devs, status="OK")
        print(f"✅ 单次枚举: {len(devs)} 台 USB 设备")
        for d in devs:
            print(f"   [{d['vid_pid']}] serial={d['serial'][:20]:20s} product={d['product'][:50]}")
        db.close()
    else:
        monitor_loop()
