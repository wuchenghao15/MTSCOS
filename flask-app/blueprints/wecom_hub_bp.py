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
    # 指令桥 (flow_wecom_andromeda_20261020 P1): 企微上行指令 → 白名单执行器
    """CREATE TABLE IF NOT EXISTS mt_wecom_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cmd TEXT NOT NULL,               -- 白名单指令: daemon_status/hall/patrol/meeting/exam/approve/reject
    args_json TEXT,                  -- 参数 (如 approve: {"suggestion_id": N})
    source TEXT DEFAULT 'callback',  -- callback / api / approval_gate
    operator TEXT DEFAULT 'wecom',
    status TEXT DEFAULT 'PENDING',   -- PENDING/RUNNING/DONE/REJECTED/FAILED
    result_md TEXT,                  -- 执行结果 (markdown, 回推企微群)
    error TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    executed_at TEXT
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
                        "approval_required": _cfg("wecom_approval_required", "0") == "1",
                        "callback_token_set": bool(_cfg("callback_token")),
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
    # 指令桥/审批闭环配置 (flow_wecom_andromeda_20261020): 白名单键才可写
    extra_key = (data.get("key") or "").strip()
    if extra_key in ("callback_token", "wecom_approval_required"):
        _set_cfg(extra_key, str(data.get("value") or ""), operator)
    _audit("wecom", "CONFIG_SET", f"webhook={'已设' if url else '已清'}",
           {"enabled": bool(data.get("enabled", True)), "operator": operator,
            "extra": {extra_key: str(data.get("value") or "")} if extra_key else {}})
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


# ══════════ 指令桥 (flow_wecom_andromeda_20261020 P1) ══════════
# 企微上行通道: 企微自建应用回调 → token 校验 → 白名单指令执行 → 结果回推企微群

_CMD_WHITELIST = ("daemon_status", "hall", "patrol", "meeting", "exam", "approve", "reject")


def _cmd_daemon_status():
    """P2 配套: 仙女座 daemon 全景 (供群内查询)"""
    conn = _db()
    try:
        by_state = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, count(*) n FROM mt_daemon_registry GROUP BY status")}
        bad = [dict(r) for r in conn.execute(
            "SELECT process_name, status FROM mt_daemon_registry "
            "WHERE status IN ('FAILED','TIMEOUT','STOPPED') LIMIT 8")]
        total = conn.execute("SELECT count(*) FROM mt_daemon_registry").fetchone()[0]
    finally:
        conn.close()
    lines = [f"> 注册 **{total}** 个 · " + " · ".join(f"{k}:{v}" for k, v in sorted(by_state.items())) or "空"]
    for b in bad:
        lines.append(f"- ⚠️ {b['process_name']} [{b['status']}]")
    return "\n".join(lines) if len(lines) > 1 else lines[0]


def _cmd_hall():
    from blueprints.daemon_skill_lab_bp import run_hall_auto
    auto = run_hall_auto()
    return (f"> 归集 **{auto['ingested']}** 项 · 分配 **{auto['dispatched']}** 项\n" +
            "\n".join(f"- {r['task'][:28]} → {r['center']} [{r['status']}]" for r in auto["results"][:6]) or "无分配")


def _cmd_patrol():
    return _cmd_hall()


def _cmd_meeting():
    result = run_auto_meeting(topic="企微指令 · 即时例会", convener="wecom_command")
    return f"> 会议 #{result.get('meeting_id')} 已召开, 纪要已推送群内 (列出 {result.get('sections', '全域')} 快照)"


def _cmd_exam():
    from engines.ai_exam_auto_engine import run_exam_auto
    s = run_exam_auto()
    cal = s["calendar"]
    return (f"> 窗口 **{'/'.join(cal['exam_types'])}** · 入库 **{s['total_inserted']}** 题 (含结题讲解) · "
            f"大厅#{s['hall_task_id'] or '-'} · 备课#{s['prep_plan_id'] or '-'}")


def _cmd_approve(args):
    """P4 审批闭环: 群内「同意」→ 放行挂载 (建议 DEFERRED → EVALUATED, 下轮 scan_and_mount 自动挂载)"""
    sid = args.get("suggestion_id")
    if not sid:
        return "缺少 suggestion_id"
    conn = _db()
    try:
        cur = conn.execute("UPDATE mt_ai_suggestion_pool SET status='EVALUATED' "
                           "WHERE suggestion_id=? AND status='DEFERRED'", (sid,))
        conn.commit()
        n = cur.rowcount
    except sqlite3.Error as e:
        return f"建议池更新失败: {e}"
    finally:
        conn.close()
    if n:
        return f"> 建议 **#{sid}** 已同意放行, 下轮扫描自动挂载 🚀"
    return f"> 建议 #{sid} 不在待审批状态 (可能已处理)"


def _cmd_reject(args):
    sid = args.get("suggestion_id")
    if not sid:
        return "缺少 suggestion_id"
    conn = _db()
    try:
        cur = conn.execute("UPDATE mt_ai_suggestion_pool SET status='REJECTED' "
                           "WHERE suggestion_id=? AND status='DEFERRED'", (sid,))
        conn.commit()
        n = cur.rowcount
    finally:
        conn.close()
    return f"> 建议 **#{sid}** 已驳回 🛑" if n else f"> 建议 #{sid} 不在待审批状态"


_CMD_DISPATCH = {
    "daemon_status": lambda a: _cmd_daemon_status(),
    "hall": _cmd_hall,
    "patrol": _cmd_patrol,
    "meeting": _cmd_meeting,
    "exam": _cmd_exam,
    "approve": _cmd_approve,
    "reject": _cmd_reject,
}


def run_wecom_command(cmd, args=None, operator="wecom", source="callback"):
    """指令桥执行器: 落库 → 白名单分发 → 结果回推企微群。永不抛异常。"""
    _ensure_tables()
    args = args or {}
    conn = _db()
    try:
        cur = conn.execute("INSERT INTO mt_wecom_commands (cmd,args_json,source,operator,status) VALUES (?,?,?,?,?)",
                           (cmd, json.dumps(args, ensure_ascii=False), source, operator,
                            "REJECTED" if cmd not in _CMD_WHITELIST else "RUNNING"))
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    result_md, err = "", None
    if cmd not in _CMD_WHITELIST:
        err = f"指令不在白名单: {cmd}"
        result_md = f"> ⛔ {err}"
    else:
        try:
            result_md = _CMD_DISPATCH[cmd](args) or "(空结果)"
        except Exception as e:
            err = str(e)[:300]
            result_md = f"> ⚠️ 指令执行失败: {err}"
    conn = _db()
    try:
        conn.execute("UPDATE mt_wecom_commands SET status=?, result_md=?, error=?, executed_at=datetime('now','localtime') WHERE id=?",
                     ("FAILED" if err else "DONE", result_md, err, cid))
        conn.commit()
    finally:
        conn.close()
    # 结果回推企微群
    try:
        wecom_push("command", f"📮 指令回执 · {cmd} #{cid}", result_md, operator=operator)
    except Exception:
        pass
    try:
        _audit("wecom", "CMD_" + cmd.upper(), "FAILED" if err else "DONE",
               {"cmd": cmd, "args": args, "cid": cid, "error": err, "operator": operator})
    except Exception:
        pass
    return {"ok": not err, "cmd_id": cid, "cmd": cmd, "result_md": result_md, "error": err}


def request_approval(suggestion):
    """P4 审批闭环 (供 smart_mount 引擎调用): 高风险建议 → 企微审批播报 + 待审批指令落库"""
    _ensure_tables()
    sid = suggestion.get("suggestion_id")
    text = (suggestion.get("suggestion") or suggestion.get("suggestion_text") or "")[:120]
    risk = float(suggestion.get("risk_score") or 0)
    score = suggestion.get("final_score") or suggestion.get("total_score") or 0
    conn = _db()
    try:
        conn.execute("INSERT INTO mt_wecom_commands (cmd,args_json,source,operator,status) VALUES (?,?,?,?,?)",
                     ("approve", json.dumps({"suggestion_id": sid}, ensure_ascii=False),
                      "approval_gate", "wecom", "PENDING"))
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    wecom_push("approval", "🛡 仙女座挂载审批",
               f"> 建议 **#{sid}** 综合分 {score} · 风险分 {risk}\n> 内容: {text}\n"
               f"> 回复指令同意/驳回: `{{\"cmd\":\"approve\",\"args\":{{\"suggestion_id\":{sid}}}}}` (指令 #{cid})")
    return cid


@wecom_hub_bp.route("/api/wecom/callback", methods=["GET", "POST"])
def wecom_callback():
    """企微自建应用回调端点 (上行通道):
    GET  = 企微 URLVerification (echostr 回显)
    POST = 指令桥: {"token": "...", "cmd": "...", "args": {...}, "operator": "..."}
    """
    _ensure_tables()
    if request.method == "GET":
        return request.args.get("echostr", "ok")
    data = request.get_json(silent=True) or {}
    token_cfg = _cfg("callback_token")
    if not token_cfg or data.get("token") != token_cfg:
        return jsonify({"ok": False, "error": "callback token 校验失败"}), 403
    cmd = (data.get("cmd") or "").strip()
    if not cmd:
        # 自由文本指令: "同意 #12" / "开会" 简易映射
        text = (data.get("text") or "").strip()
        if "同意" in text and "#" in text:
            cmd, args = "approve", {"suggestion_id": text.split("#")[-1].strip()}
        elif "驳回" in text and "#" in text:
            cmd, args = "reject", {"suggestion_id": text.split("#")[-1].strip()}
        elif "开会" in text:
            cmd, args = "meeting", {}
        elif "状态" in text:
            cmd, args = "daemon_status", {}
        else:
            return jsonify({"ok": False, "error": "缺少 cmd 且文本未命中指令映射"}), 400
        if isinstance(args.get("suggestion_id"), str) and args["suggestion_id"].isdigit():
            args["suggestion_id"] = int(args["suggestion_id"])
    else:
        args = data.get("args") or {}
        if cmd not in _CMD_WHITELIST:
            result = run_wecom_command(cmd, args, operator=data.get("operator") or "wecom")
            return jsonify(result), 400 if not result["ok"] else 200
    result = run_wecom_command(cmd, args, operator=data.get("operator") or "wecom")
    return jsonify(result), 200 if result["ok"] else 400


@wecom_hub_bp.route("/api/wecom/commands")
@_login_required
def wecom_commands():
    """指令流水: 回溯追责入口"""
    _ensure_tables()
    limit = min(int(request.args.get("limit", 30) or 30), 100)
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,cmd,args_json,source,operator,status,substr(result_md,1,120) result_md,error,created_at "
            "FROM mt_wecom_commands ORDER BY id DESC LIMIT ?", (limit,))]
        by_status = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, count(*) n FROM mt_wecom_commands GROUP BY status")}
        return jsonify({"ok": True, "by_status": by_status, "commands": rows,
                        "whitelist": list(_CMD_WHITELIST)})
    finally:
        conn.close()
