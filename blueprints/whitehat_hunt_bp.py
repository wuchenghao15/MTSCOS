#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WHITEHAT 白帽猎捕系统 (flow_whitehat_hunt_20261027)
SA 专属页面: 网络漏洞白帽查找 → 猎捕结果入任务大厅 → 喂养冰山/仙女座
访问控制: 仅 SA (super_admin/admin/wuchenghao15), 页面独立壳不入导航"""
from __future__ import annotations
import os, sys, sqlite3, json
from datetime import datetime
from flask import Blueprint, jsonify, request, session, render_template

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import DB_PATH

whitehat_bp = Blueprint("whitehat_hunt_bp", __name__)

def _u():
    return {"user_id": session.get("user_id", ""), "username": session.get("username", ""),
            "role": session.get("role", "user")}

def _is_sa(u):
    return u["role"] in ("admin", "super_admin") or u["username"] == "wuchenghao15"

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c

def _ensure_log_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS whitehat_hunt_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mode TEXT NOT NULL DEFAULT 'hunt',
        files INTEGER DEFAULT 0, findings INTEGER DEFAULT 0,
        groups INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
        published INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, capped INTEGER DEFAULT 0,
        operator TEXT DEFAULT '', detail TEXT DEFAULT '',
        started_at TEXT DEFAULT (datetime('now','localtime')),
        finished_at TEXT)""")

# ──────────────── 页面 (SA ONLY) ────────────────

@whitehat_bp.route("/whitehat", methods=["GET"])
def whitehat_page():
    u = _u()
    if not _is_sa(u):
        return "<h1>403</h1><p>WHITEHAT SYSTEM · SA ONLY</p>", 403
    return render_template("whitehat_hunt.html")

# ──────────────── 状态/喂养面板 ────────────────

@whitehat_bp.route("/whitehat/api/status", methods=["GET"])
def whitehat_status():
    u = _u()
    if not _is_sa(u):
        return jsonify({"success": False, "error": "forbidden"}), 403
    c = _conn()
    try:
        _ensure_log_table(c)
        last = c.execute("SELECT * FROM whitehat_hunt_log WHERE mode='hunt' "
                         "ORDER BY id DESC LIMIT 1").fetchone()
        feed = {
            "total_published": c.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE source='vuln_scan'").fetchone()[0],
            "done": c.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE source='vuln_scan' AND status='DONE'").fetchone()[0],
            "active": c.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE source='vuln_scan' "
                "AND status IN ('QUEUED','DISPATCHED','CLAIMED','IN_PROGRESS')").fetchone()[0],
            "center": "漏洞修复适配中心",
        }
        return jsonify({"success": True,
                        "last": dict(last) if last else None,
                        "feed": feed})
    finally:
        c.close()

# ──────────────── 静默侦察 (scan only) ────────────────

@whitehat_bp.route("/whitehat/api/scan", methods=["POST"])
def whitehat_scan():
    u = _u()
    if not _is_sa(u):
        return jsonify({"success": False, "error": "forbidden"}), 403
    from ai_engines.ai_vuln_scan_dispatch_engine import scan_once
    groups, stats = scan_once()
    c = _conn()
    try:
        _ensure_log_table(c)
        c.execute("INSERT INTO whitehat_hunt_log (mode,files,findings,groups,errors,published,operator,finished_at) "
                  "VALUES ('scan',?,?,?,?,0,?,datetime('now','localtime'))",
                  (stats["files"], stats["findings"], len(groups), stats["errors"], u["username"]))
        c.commit()
    finally:
        c.close()
    return jsonify({"success": True, **stats, "groups": len(groups)})

# ──────────────── 猎捕下发 (hunt → 任务大厅 → 冰山/仙女座) ────────────────

@whitehat_bp.route("/whitehat/api/hunt", methods=["POST"])
def whitehat_hunt():
    u = _u()
    if not _is_sa(u):
        return jsonify({"success": False, "error": "forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    max_tasks = min(int(data.get("max_tasks") or 12), 50)
    from ai_engines.ai_vuln_scan_dispatch_engine import run_vuln_scan_dispatch_once
    summary = run_vuln_scan_dispatch_once(max_tasks=max_tasks, scan_only=False)
    c = _conn()
    try:
        _ensure_log_table(c)
        c.execute("INSERT INTO whitehat_hunt_log (mode,files,findings,groups,errors,published,skipped,capped,operator,detail,finished_at) "
                  "VALUES ('hunt',?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
                  (summary.get("files", 0), summary.get("findings", 0), summary.get("groups", 0),
                   summary.get("errors", 0), len(summary.get("published") or []),
                   summary.get("skipped_existing", 0), summary.get("capped", 0),
                   u["username"], json.dumps((summary.get("published") or [])[:20], ensure_ascii=False)))
        c.commit()
    finally:
        c.close()
    return jsonify({"success": True, **summary})
