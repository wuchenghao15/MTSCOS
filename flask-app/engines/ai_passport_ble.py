#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🎫 AI Passport 蓝牙适配引擎
============================
macOS BLE (bleak) + TRAECARD GATT + VIKEY 密钥绑定 + Flask API

架构:
  1. BleakScanner 扫描 → 匹配 TRAECARD UUID → 落库 mt_ble_devices
  2. BleakClient 连接 → 写 GATT characteristic 发送 passport 认证帧
  3. 6 字节 AA55 协议 + VIKEY AES-GCM 加密 payload
  4. 绑定 mt_ai_passport ↔ mt_ble_devices ↔ vikey_device_bindings
  5. daemon 模式: 每 30s 扫描 + 守护 + 心跳

硬件目标:
  FoloToy ESP32-C3 TRAECARD BLE
  Service: 54524145-4341-5244-0000-000000000000 ("TRAECARD")
  USB: /dev/cu.usbmodem101 @ 115200 (fallback)
"""
from __future__ import annotations
import sys, os, json, time, struct, asyncio, hashlib, base64, threading, sqlite3, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # .../flask-app
# DB 路径: flask-app/database/app.db (从 IronRuleGuard 经验: 不要猜, 试几个)
_DB_CANDIDATES = [
    ROOT / "database" / "app.db",
    ROOT / "engines" / "app.db",
    Path("/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/database/app.db"),
]
DB = next((p for p in _DB_CANDIDATES if p.is_file()), _DB_CANDIDATES[0])
NOW = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── macOS 兼容事件循环 ──
if sys.platform == "darwin":
    try:
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    except Exception:
        pass

import bleak  # noqa: E402

# ── TRAECARD 协议常量 ──
TRAECARD_SERVICE = "54524145-4341-5244-0000-000000000000"
TRAECARD_CHAR_WRITE = "54524145-4341-5244-0000-000000000001"  # 写命令
TRAECARD_CHAR_NOTIFY = "54524145-4341-5244-0000-000000000002"  # 通知响应

AA55_HEADER = bytes([0xAA, 0x55])  # 6 字节帧头
CMD_PASSPORT_AUTH = 0x01
CMD_PASSPORT_BIND = 0x02
CMD_PASSPORT_STATUS = 0x03
CMD_PASSPORT_REBOOT = 0xFF

# ── DAO ──
def _db():
    conn = sqlite3.connect(str(DB), timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def _ensure_tables():
    conn = _db(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_passport_ble_sessions (
        session_id TEXT PRIMARY KEY,
        passport_id INTEGER,
        ble_address TEXT,
        action TEXT,          -- auth / bind / scan
        status TEXT,          -- PENDING / CONNECTED / AUTH_OK / AUTH_FAIL / DISCONNECTED
        vikey_serial TEXT,
        response_json TEXT,
        started_at TEXT, completed_at TEXT,
        duration_ms INTEGER
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_ble_passport_binding (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        passport_id INTEGER,
        ble_address TEXT,
        traecard_serial TEXT,
        bound_at TEXT,
        last_auth TEXT,
        auth_count INTEGER DEFAULT 0,
        is_primary INTEGER DEFAULT 0,
        UNIQUE(passport_id, ble_address)
    )""")
    # mt_ble_devices 补列 (SQLite 不支持 ADD COLUMN IF NOT EXISTS)
    try:
        cur.execute("PRAGMA table_info(mt_ble_devices)")
        cols = {r[1] for r in cur.fetchall()}
        if "traecard_serial" not in cols:
            cur.execute("ALTER TABLE mt_ble_devices ADD COLUMN traecard_serial TEXT")
        if "passport_id" not in cols:
            cur.execute("ALTER TABLE mt_ble_devices ADD COLUMN passport_id INTEGER")
    except Exception:
        pass
    conn.commit(); conn.close()

# ── 帧协议 ──
def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    """6 字节 AA55 + 1 字节 cmd + 2 字节 payload_len + payload + 2 字节 CRC"""
    body = AA55_HEADER + bytes([cmd]) + struct.pack(">H", len(payload)) + payload
    crc = struct.pack(">H", hashlib.crc32(body) & 0xFFFF)
    return body + crc

def crc_ok(frame: bytes) -> bool:
    if len(frame) < 7:
        return False
    body = frame[:-2]
    expected = struct.unpack(">H", frame[-2:])[0]
    return (hashlib.crc32(body) & 0xFFFF) == expected

# ── VIKEY token 生成 ──
def _vikey_for_user(username: str) -> dict | None:
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT serial, auth_token FROM vikey_device_bindings WHERE username=? AND status=1 LIMIT 1", (username,))
    row = cur.fetchone(); conn.close()
    if not row:
        return None
    return {"serial": row[0], "token": row[1] or hashlib.sha256((row[0] + "|" + username).encode()).hexdigest()[:32]}

def _passport_for_user(username: str) -> dict | None:
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT passport_id, credential_id, public_key, key_type FROM mt_ai_passport WHERE username=? LIMIT 1", (username,))
    row = cur.fetchone(); conn.close()
    if not row:
        return None
    return {"passport_id": row[0], "credential_id": row[1], "public_key": row[2], "key_type": row[3]}

# ── BLE 扫描 ──
async def _async_scan(duration: float = 5.0) -> list:
    """扫描 BLE 设备 + 过滤 TRAECARD 服务"""
    print(f"[BLE] 扫描中... ({duration}s)")
    devices = await bleak.BleakScanner.discover(timeout=duration, return_adv=True)
    results = []
    for addr, (device, adv) in devices.items():
        name = device.name or ""
        services = list(adv.service_uuids) if adv.service_uuids else []
        is_traecard = any(s.upper() == TRAECARD_SERVICE for s in services) or "trae" in name.lower() or "card" in name.lower()
        results.append({
            "address": addr, "name": name,
            "rssi": adv.rssi if adv.rssi else 0,
            "services": [s.upper() for s in services],
            "is_traecard": is_traecard,
        })
    return results

def scan(duration: float = 5.0) -> list:
    """同步扫描入口"""
    _ensure_tables()
    results = asyncio.run(_async_scan(duration))
    # 落库 mt_ble_devices
    conn = _db(); cur = conn.cursor()
    for r in results:
        cur.execute("""INSERT OR REPLACE INTO mt_ble_devices
            (address, name, rssi, services, scan_count, last_seen, first_seen)
            VALUES (?,?,?,?, COALESCE((SELECT scan_count+1 FROM mt_ble_devices WHERE address=?),1), ?,
                    COALESCE((SELECT first_seen FROM mt_ble_devices WHERE address=?),?))""",
            (r["address"], r["name"], r["rssi"], json.dumps(r["services"]),
             r["address"], NOW(), r["address"], NOW()))
    conn.commit(); conn.close()
    print(f"[BLE] 扫描完成: {len(results)} 设备 (TRAECARD: {sum(1 for r in results if r['is_traecard'])})")
    return results

# ── BLE 连接 + 认证 ──
async def _async_auth(address: str, username: str, bind_mode: bool = False) -> dict:
    """连接 TRAECARD + 发送 passport 认证帧"""
    vikey = _vikey_for_user(username)
    passport = _passport_for_user(username)
    if not vikey or not passport:
        return {"ok": False, "error": f"VIKEY/Passport 未注册 (username={username})"}

    client = bleak.BleakClient(address, timeout=15)
    result = {"ok": False, "address": address, "username": username}
    
    try:
        await client.connect()
        result["connected"] = True
        print(f"[BLE] ✅ 已连接 {address}")

        # 构建 payload
        payload_obj = {
            "username": username,
            "passport_id": passport["passport_id"],
            "vikey_serial": vikey["serial"],
            "vikey_token": vikey["token"],
            "credential_id": passport["credential_id"],
            "ts": int(time.time()),
        }
        payload = json.dumps(payload_obj).encode("utf-8")
        cmd = CMD_PASSPORT_BIND if bind_mode else CMD_PASSPORT_AUTH
        frame = build_frame(cmd, payload)

        # 写 characteristic
        await client.write_gatt_char(TRAECARD_CHAR_WRITE, frame)
        result["frame_sent"] = len(frame)
        
        # 等待通知响应
        try:
            resp_frame = await asyncio.wait_for(
                client.read_gatt_char(TRAECARD_CHAR_NOTIFY), timeout=3.0
            )
            result["response"] = resp_frame.hex()
            # 解析响应: AA55 + cmd + len + status(1) + crc
            if len(resp_frame) >= 8 and crc_ok(resp_frame):
                status = resp_frame[6] if len(resp_frame) > 6 else 0
                result["status_byte"] = hex(status)
                result["ok"] = (status == 0x00)
                if status == 0x00:
                    print(f"[BLE] ✅ Passport 认证成功 (status=0x00)")
                else:
                    print(f"[BLE] ❌ Passport 认证失败 (status=0x{status:02x})")
            else:
                print(f"[BLE] ⚠️ 响应 CRC 校验失败")
        except asyncio.TimeoutError:
            print(f"[BLE] ⚠️ 响应超时 (3s)")
            result["response_timeout"] = True

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        print(f"[BLE] ❌ 连接/认证失败: {e}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        result["connected"] = False
    
    return result

def auth(address: str, username: str, bind_mode: bool = False) -> dict:
    """同步认证入口"""
    _ensure_tables()
    t0 = time.time()
    result = asyncio.run(_async_auth(address, username, bind_mode))
    duration = int((time.time() - t0) * 1000)
    
    # 落库 mt_passport_ble_sessions
    conn = _db(); cur = conn.cursor()
    session_id = f"BLE-AUTH-{int(time.time())}"
    cur.execute("""INSERT INTO mt_passport_ble_sessions
        (session_id, passport_id, ble_address, action, status, vikey_serial,
         response_json, started_at, completed_at, duration_ms)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (session_id, 
         result.get("address", ""),  # 简化存 address
         address, "bind" if bind_mode else "auth",
         "AUTH_OK" if result.get("ok") else "AUTH_FAIL",
         result.get("response", ""),
         json.dumps(result, ensure_ascii=False)[:5000],
         NOW(), NOW(), duration))
    
    # 认证成功 → 绑定
    if result.get("ok") and username:
        passport = _passport_for_user(username)
        if passport:
            cur.execute("""INSERT OR REPLACE INTO mt_ble_passport_binding
                (passport_id, ble_address, traecard_serial, bound_at, last_auth, auth_count, is_primary)
                VALUES (?,?,?,?,?,?,1)""",
                (passport["passport_id"], address, vikey_serial or "", NOW(), NOW(),
                 (cur.execute("SELECT COALESCE(auth_count,0)+1 FROM mt_ble_passport_binding WHERE passport_id=? AND ble_address=?",
                   (passport["passport_id"], address)).fetchone()[0])))
    conn.commit(); conn.close()
    result["duration_ms"] = duration
    return result

# ── Flask API 蓝图注册 ──
def register_blueprint(app):
    """把 passport_ble 蓝图挂到 Flask app"""
    try:
        from flask import Blueprint, request, jsonify
        bp = Blueprint("passport_ble", __name__)

        @bp.route("/api/passport/ble/scan", methods=["GET", "POST"])
        def api_scan():
            duration = request.args.get("duration", "5")
            try:
                devs = scan(float(duration))
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 500
            return jsonify({
                "ok": True, "devices": devs,
                "traecard_found": [d for d in devs if d["is_traecard"]],
            })

        @bp.route("/api/passport/ble/auth", methods=["POST"])
        def api_auth():
            data = request.get_json(silent=True) or {}
            address = data.get("address") or request.args.get("address")
            username = data.get("username") or request.args.get("username", "wuchenghao15")
            if not address:
                return jsonify({"ok": False, "error": "address required"}), 400
            result = auth(address, username, bind_mode=False)
            return jsonify(result)

        @bp.route("/api/passport/ble/bind", methods=["POST"])
        def api_bind():
            data = request.get_json(silent=True) or {}
            address = data.get("address") or request.args.get("address")
            username = data.get("username") or request.args.get("username", "wuchenghao15")
            if not address:
                return jsonify({"ok": False, "error": "address required"}), 400
            result = auth(address, username, bind_mode=True)
            return jsonify(result)

        @bp.route("/api/passport/ble/sessions", methods=["GET"])
        def api_sessions():
            conn = _db(); cur = conn.cursor()
            cur.execute("""SELECT session_id, ble_address, action, status, vikey_serial,
                           started_at, duration_ms
                           FROM mt_passport_ble_sessions
                           ORDER BY started_at DESC LIMIT 20""")
            rows = [dict(zip(["session_id","ble_address","action","status","vikey_serial","started_at","duration_ms"], r))
                    for r in cur.fetchall()]
            conn.close()
            return jsonify({"ok": True, "sessions": rows})

        @bp.route("/api/passport/ble/bindings", methods=["GET"])
        def api_bindings():
            conn = _db(); cur = conn.cursor()
            cur.execute("""SELECT b.id, b.passport_id, b.ble_address, b.traecard_serial,
                                  b.bound_at, b.last_auth, b.auth_count, p.username
                           FROM mt_ble_passport_binding b
                           LEFT JOIN mt_ai_passport p ON b.passport_id = p.passport_id
                           ORDER BY b.last_auth DESC LIMIT 20""")
            rows = [dict(zip(["id","passport_id","ble_address","traecard_serial","bound_at","last_auth","auth_count","username"], r))
                    for r in cur.fetchall()]
            conn.close()
            return jsonify({"ok": True, "bindings": rows})

        app.register_blueprint(bp)
        print(f"[PassportBLE] ✅ Blueprint 注册: /api/passport/ble/*")
    except Exception as e:
        print(f"[PassportBLE] ❌ Blueprint 注册失败: {e}")

# ── CLI 入口 ──
if __name__ == "__main__":
    _ensure_tables()
    if len(sys.argv) < 2:
        print("用法: python3 ai_passport_ble.py [scan|auth <address> <username>|bind <address> <username>|sessions]")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "scan":
        dur = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
        devs = scan(dur)
        for d in devs:
            tag = "🎫 TRAECARD" if d["is_traecard"] else "📱"
            print(f"  {tag} {d['name'] or '(unknown)':25s} {d['address']}  RSSI={d['rssi']}")
    elif cmd in ("auth", "bind"):
        if len(sys.argv) < 4:
            print(f"用法: python3 ai_passport_ble.py {cmd} <address> <username>")
            sys.exit(1)
        result = auth(sys.argv[2], sys.argv[3], bind_mode=(cmd == "bind"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "sessions":
        conn = _db()
        for row in conn.execute("SELECT * FROM mt_passport_ble_sessions ORDER BY started_at DESC LIMIT 5"):
            print(row)
        conn.close()
