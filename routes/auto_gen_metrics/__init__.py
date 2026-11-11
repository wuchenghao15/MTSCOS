"""auto_gen_metrics v6.0 - 实时监控 API"""
from flask import Blueprint, jsonify
import sqlite3, os

bp = Blueprint("auto_metrics", __name__, url_prefix="/api/metrics")
DB = os.path.join(os.path.dirname(__file__), "..", "..", "engines", "app.db")

@bp.route("/health")
def health():
    return jsonify(status="ok", service="auto_gen_metrics")

@bp.route("/daemons")
def daemons():
    conn = sqlite3.connect(DB, timeout=5)
    rows = conn.execute("SELECT daemon_name, status, interval_sec FROM mt_daemon_registry ORDER BY daemon_name").fetchall()
    conn.close()
    return jsonify(daemons=[{"name":r[0],"status":r[1],"interval":r[2]} for r in rows])

__all__ = ["bp"]
