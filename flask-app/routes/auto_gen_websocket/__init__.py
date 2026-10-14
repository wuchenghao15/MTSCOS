"""auto_gen_websocket v6.0"""
from flask import Blueprint, jsonify, request
import sqlite3, os, json
bp = Blueprint("auto_ws", __name__, url_prefix="/api/ws")
APP_DB = os.path.join(os.path.dirname(__file__), "..", "..", "engines", "app.db")
def _conn():
    c = sqlite3.connect(APP_DB, timeout=5); c.execute("PRAGMA journal_mode=WAL"); return c
def _ensure():
    c = _conn()
    c.execute("""CREATE TABLE IF NOT EXISTS mt_ws_channels (channel TEXT PRIMARY KEY, description TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mt_ws_notifications (nid INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, payload TEXT, level TEXT DEFAULT 'info', pushed INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))""")
    for ch, desc in [("system","系统通知"),("daemon_status","daemon状态"),("dev_activity","开发活动"),("ai_chat","AI消息"),("alarm","告警")]:
        c.execute("INSERT OR IGNORE INTO mt_ws_channels VALUES (?,?)", (ch, desc))
    c.commit(); c.close()
@bp.route("/health")
def health():
    _ensure(); return jsonify(status="ok", ws_port=8889)
@bp.route("/channels")
def channels():
    _ensure(); c = _conn(); rows = c.execute("SELECT * FROM mt_ws_channels").fetchall(); c.close()
    return jsonify(channels=[{"name":r[0],"desc":r[1]} for r in rows])
@bp.route("/push", methods=["POST"])
def push():
    data = request.get_json() or {}
    channel = data.get("channel","system")
    payload = data.get("payload","{}")
    level = data.get("level","info")
    _ensure(); c = _conn()
    cur = c.execute("INSERT INTO mt_ws_notifications (channel,payload,level) VALUES (?,?,?)", (channel, json.dumps(payload, ensure_ascii=False) if isinstance(payload,(dict,list)) else payload, level))
    nid = cur.lastrowid; c.commit(); c.close()
    trigger = os.path.join(os.path.dirname(APP_DB), "_ws_trigger.json")
    import time as _t
    with open(trigger,"w") as f: json.dump({"nid":nid,"channel":channel,"ts":int(_t.time())}, f)
    return jsonify(status="ok", nid=nid, channel=channel, level=level)
@bp.route("/history")
def history():
    _ensure(); c = _conn()
    rows = c.execute("SELECT nid,channel,payload,level,created_at FROM mt_ws_notifications ORDER BY nid DESC LIMIT 50").fetchall()
    c.close()
    return jsonify(items=[{"nid":r[0],"channel":r[1],"payload":json.loads(r[2]) if r[2].startswith(("{","[")) else r[2],"level":r[3],"ts":r[4]} for r in rows])
__all__ = ["bp"]
