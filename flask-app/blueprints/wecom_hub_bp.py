#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信中枢 (flow_wecom_20261020)
====================================
把全部 AI 资源整合到企业微信, 统一自动管理与自动开会:
  ① 自动管理推送: 中心体系事件(任务分配/考试晋升/daemon告警/审计) → 企微群机器人 webhook
  ② 自动开会: 汇聚 daemon/大厅/HR/教育/审计 全域状态 → EigenFlux 磋商式会议纪要 → 推送企微 + 落库
  ③ 配置数据中心化: webhook 等全部存 DB (mt_wecom_config), 禁止硬编码, 界面可配
  ④ 全量审计: 每次推送/配置变更/开会 → mt_lab_audit_log + mt_wecom_send_log 双轨留痕

依赖: 企业微信群机器人 webhook URL (企微群 → 添加群机器人 → 复制 webhook), 未配置时安全降级 dry-run。
"""
import json
import os
import sqlite3
import urllib.request

from flask import Blueprint, jsonify, request

from blueprints.chat_local_bp import _login_required, _get_user
from blueprints.daemon_skill_lab_bp import _audit, _db as _lab_db, _APP_DIR

wecom_hub_bp = Blueprint("wecom_hub_bp", __name__)

MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_wecom_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    updated_by TEXT
)""",
    """CREATE TABLE IF NOT EXISTS mt_wecom_send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center TEXT NOT NULL,            -- hall/edu/lab/daemon/meeting/test
    title TEXT NOT NULL,
    content TEXT,
    status TEXT DEFAULT 'SENT',      -- SENT / FAILED / SKIPPED_NOT_CONFIGURED
    resp_code INTEGER,
    error TEXT,
    operator TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_wecom_meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    minutes_md TEXT NOT NULL,        -- 会议纪要 (markdown)
    stats_json TEXT,                 -- 开会时的全域快照
    attendees TEXT,                  -- 列席: 中心代表 (json)
    push_status TEXT DEFAULT 'PENDING',
    convener TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables():
    conn = _db()
    try:
        for sql in _DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def _cfg(key, default=""):
    conn = _db()
    try:
        r = conn.execute("SELECT value FROM mt_wecom_config WHERE key=?", (key,)).fetchone()
        return (r["value"] if r else default) or default
    finally:
        conn.close()


def _set_cfg(key, value, operator):
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_wecom_config (key,value,updated_at,updated_by) VALUES (?,?,datetime('now','localtime'),?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                     (key, value, operator))
        conn.commit()
    finally:
        conn.close()


def wecom_push(center, title, md_content, operator="system"):
    """统一企微推送入口: webhook 已配置 → 真发; 未配置 → SKIPPED 留痕。永远不抛异常。"""
    _ensure_tables()
    url = _cfg("webhook_url")
    status, code, err = "SKIPPED_NOT_CONFIGURED", None, "webhook 未配置"
    if url.startswith("http"):
        payload = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{md_content}"[:4096]}}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                code = resp.status
                body = json.loads(resp.read().decode("utf-8") or "{}")
                status = "SENT" if body.get("errcode") == 0 else "FAILED"
                if status == "FAILED":
                    err = f"errcode={body.get('errcode')} errmsg={body.get('errmsg')}"
        except Exception as e:
            status, err = "FAILED", str(e)[:300]
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_wecom_send_log (center,title,content,status,resp_code,error,operator) VALUES (?,?,?,?,?,?,?)",
                     (center, title[:120], md_content[:2000], status, code, err, operator))
        conn.commit()
    finally:
        conn.close()
    return status, err


# ── 中心体系事件钩子 (供各蓝图调用) ──
def notify_hall_dispatch(results, ingested):
    if not results:
        return
    lines = [f"> 归集 **{ingested}** 项 · 分配 **{len(results)}** 项"]
    for r in results[:8]:
        lines.append(f"- **{r['task'][:24]}** → {r['center']} [{r['status']}] 员工:{'、'.join(r['employees'][:2]) or '—'}")
    wecom_push("hall", "📋 任务大厅 · 自动分配播报", "\n".join(lines))


def notify_edu_run(pipeline):
    p = pipeline
    if not p.get("exam_taken") and not p.get("promoted"):
        return
    md = (f"> 建课 {p.get('courses_added')} · 应试 {p.get('exam_taken')} · 通过 {p.get('exam_passed')} · 回炉 {p.get('failed_back_to_school')}\n"
          + "\n".join(f"- 🎖 **{x['employee']}** 晋升 {x['level']}" for x in p.get("promoted", [])[:8]))
    wecom_push("edu", "🎓 教育中心 · 考试晋升播报", md)


def notify_daemon_alert(bad_daemons):
    if not bad_daemons:
        return
    md = "\n".join(f"- ⚠️ **{d['process_name']}** 状态 {d['current_state']}" for d in bad_daemons[:8])
    wecom_push("daemon", "🚨 Daemon 异常告警", md)


# ── ① 自动开会: 全域状态 → 纪要 → 推送 ──
def run_auto_meeting(topic="AI 体系例行会议", convener="system"):
    _ensure_tables()
    conn = _db()
    snap = {}
    try:
        try:
            snap["daemons_total"] = conn.execute("SELECT count(*) FROM mt_daemon_registry").fetchone()[0]
            snap["daemons_running"] = conn.execute("SELECT count(*) FROM mt_daemon_registry WHERE current_state='RUNNING'").fetchone()[0]
            snap["daemons_bad"] = [dict(r) for r in conn.execute(
                "SELECT process_name, current_state FROM mt_daemon_registry WHERE current_state IN ('FAILED','STOPPED') LIMIT 6")]
        except sqlite3.Error:
            snap["daemons_total"] = snap["daemons_running"] = 0
            snap["daemons_bad"] = []
        snap["hall"] = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, count(*) n FROM mt_lab_task_hall GROUP BY status")}
        snap["hr_top"] = [dict(r) for r in conn.execute(
            "SELECT employee_name, count(*) tasks FROM mt_lab_hr_log GROUP BY employee_name ORDER BY tasks DESC LIMIT 3")]
        snap["edu"] = {"qualified": conn.execute("SELECT count(*) FROM mt_edu_promotions").fetchone()[0],
                       "exam_passed": conn.execute("SELECT count(*) FROM mt_edu_exam_results WHERE passed=1").fetchone()[0]}
        snap["audit_today"] = conn.execute("SELECT count(*) FROM mt_lab_audit_log WHERE created_at >= date('now','localtime')").fetchone()[0]
    finally:
        conn.close()

    d_ok = snap["daemons_running"]
    d_tot = snap["daemons_total"]
    hall_q = snap["hall"].get("QUEUED", 0)
    d_disp = snap["hall"].get("DISPATCHED", 0)
    health = "⚪ 本机无注册数据" if d_tot == 0 else ("🟢 良好" if d_ok >= d_tot * 0.9 else ("🟡 需关注" if d_ok >= d_tot * 0.6 else "🔴 异常"))
    items = [
        f"### 🤖 AI 体系自动会议纪要 — {health}",
        f"**议题**: {topic}",
        "**一、Daemon 军团**",
        f"- 在册 {d_tot}, 运行 {d_ok}, 存活率 {round(d_ok*100/max(d_tot,1))}%",
    ]
    if snap["daemons_bad"]:
        items.append("- 异常: " + ", ".join(f"{d['process_name']}({d['current_state']})" for d in snap["daemons_bad"]))
    items += [
        "**二、任务大厅**",
        f"- 排队 {hall_q} · 已分配 {d_disp} · 完成 {snap['hall'].get('DONE', 0)}",
        "**三、人力资源**",
        f"- 负载 TOP: " + (", ".join(f"{w['employee_name']}({w['tasks']}单)" for w in snap["hr_top"]) or "暂无"),
        "**四、教育考试**",
        f"- 考试通过 {snap['edu']['exam_passed']} 科次, 具晋升资格 {snap['edu']['qualified']} 人",
        f"**五、今日审计操作** {snap['audit_today']} 次",
        "> 议定: 异常 daemon 转交任务大厅 HIGH 修复单; 队列积压由认领引擎消化; 结果回流审计。",
    ]
    minutes = "\n".join(items)
    attendees = json.dumps(["部署运维中心", "任务大厅", "人力资源中心", "教育中心", "审计组"], ensure_ascii=False)
    push_status, err = wecom_push("meeting", f"🤖 {topic} · 纪要", minutes, operator=convener)
    conn = _db()
    try:
        cur = conn.execute("INSERT INTO mt_wecom_meetings (topic,minutes_md,stats_json,attendees,push_status,convener) VALUES (?,?,?,?,?,?)",
                           (topic[:120], minutes, json.dumps(snap, ensure_ascii=False, default=str), attendees,
                            push_status, convener))
        conn.commit()
        mid = cur.lastrowid
    finally:
        conn.close()
    _audit("wecom", "AUTO_MEETING", f"会议#{mid} {topic[:40]}",
           {"push_status": push_status, "push_err": err, "stats": snap})
    return {"meeting_id": mid, "minutes": minutes, "push_status": push_status, "push_err": err, "stats": snap}


# ── API ──
@wecom_hub_bp.route("/api/wecom/status")
@_login_required
def wecom_status():
    _ensure_tables()
    url = _cfg("webhook_url")
    conn = _db()
    try:
        stats = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, count(*) n FROM mt_wecom_send_log GROUP BY status")}
        recent = [dict(r) for r in conn.execute(
            "SELECT center,title,status,error,created_at FROM mt_wecom_send_log ORDER BY id DESC LIMIT 10")]
        meetings = [dict(r) for r in conn.execute(
            "SELECT id,topic,push_status,convener,created_at FROM mt_wecom_meetings ORDER BY id DESC LIMIT 5")]
        return jsonify({"ok": True, "configured": url.startswith("http"),
                        "webhook_masked": (url[:42] + "…") if len(url) > 42 else url,
                        "enabled": _cfg("enabled", "1") == "1",
                        "send_stats": stats, "recent_sends": recent, "meetings": meetings})
    finally:
        conn.close()


@wecom_hub_bp.route("/api/wecom/config", methods=["POST"])
@_login_required
def wecom_config_set():
    data = request.get_json(silent=True) or {}
    url = (data.get("webhook_url") or "").strip()
    if url and not (url.startswith("https://qyapi.weixin.qq.com/") or url.startswith("http://localhost")):
        return jsonify({"ok": False, "error": "webhook 必须是 qyapi.weixin.qq.com 群机器人地址"}), 400
    u = _get_user()
    operator = u.get("username") or "unknown"
    _ensure_tables()
    _set_cfg("webhook_url", url, operator)
    _set_cfg("enabled", "1" if data.get("enabled", True) else "0", operator)
    _audit("wecom", "CONFIG_SET", f"webhook={'已设' if url else '已清'}",
           {"enabled": bool(data.get("enabled", True)), "operator": operator})
    return jsonify({"ok": True, "message": "配置已存数据中心库"})


@wecom_hub_bp.route("/api/wecom/test", methods=["POST"])
@_login_required
def wecom_test():
    u = _get_user()
    operator = u.get("username") or "unknown"
    status, err = wecom_push("test", "✅ MTSCOS AI 企微通道测试",
                             f"> 由 **{operator}** 触发的连通性测试, 中心体系推送链路正常。",
                             operator=operator)
    _audit("wecom", "TEST_PUSH", status, {"error": err, "operator": operator})
    ok = status == "SENT"
    return jsonify({"ok": ok, "status": status,
                    "message": "推送成功" if ok else ("webhook 未配置 — 请先保存企微群机器人地址" if status == "SKIPPED_NOT_CONFIGURED" else f"推送失败: {err}")})


@wecom_hub_bp.route("/api/wecom/meeting", methods=["GET", "POST"])
@_login_required
def wecom_meeting():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        u = _get_user()
        convener = u.get("username") or "unknown"
        topic = (data.get("topic") or "AI 体系例行会议").strip()[:80]
        result = run_auto_meeting(topic, convener)
        return jsonify({"ok": True, "meeting": result})
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,topic,push_status,convener,created_at FROM mt_wecom_meetings ORDER BY id DESC LIMIT 20")]
        return jsonify({"ok": True, "meetings": rows})
    finally:
        conn.close()


@wecom_hub_bp.route("/api/wecom/meeting/<int:mid>")
@_login_required
def wecom_meeting_detail(mid):
    _ensure_tables()
    conn = _db()
    try:
        r = conn.execute("SELECT * FROM mt_wecom_meetings WHERE id=?", (mid,)).fetchone()
        if not r:
            return jsonify({"ok": False, "error": "会议不存在"}), 404
        return jsonify({"ok": True, "meeting": dict(r)})
    finally:
        conn.close()
