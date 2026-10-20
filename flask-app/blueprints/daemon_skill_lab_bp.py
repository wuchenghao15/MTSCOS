#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daemon & Skill 研究与研发中心 (flow_lab_20261020)
====================================================
页面:  GET /daemon-skill-lab          — 研发中心主页 (登录门禁)
API:   GET /api/daemon-lab/overview  — 研究总览 JSON (daemon 注册表 + skill 盘点 + 衍生候选)

研究逻辑 (纯本地, 零 token):
  Daemon 研究所: 读 mt_daemon_registry (状态分布/挂载分/重启数/职责) + 实时进程扫描
  Skill  研究所: 扫描 ~/.trae-cn/skills/*/SKILL.md frontmatter, 关键词分类
  衍生引擎:      daemon 无对应 skill 管理Skill → 生成候选, 落库 mt_lab_suggestions
"""
import os
import re
import sqlite3
from flask import Blueprint, render_template, jsonify

from blueprints.chat_local_bp import _login_required, _get_user

daemon_skill_lab_bp = Blueprint("daemon_skill_lab_bp", __name__, template_folder=None)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")
SKILLS_DIR = os.path.expanduser("~/.trae-cn/skills")

# Skill 分类关键词 (本地规则, 零 token)
_SKILL_CATEGORIES = [
    ("部署运维", ["deploy", "daemon", "smart-mount", "keepalive", "ops", "运维", "挂载"]),
    ("安全审计", ["security", "audit", "漏洞", "安全", "审查", "加密"]),
    ("开发流程", ["dev", "flow", "git", "commit", "rule", "flask", "代码"]),
    ("AI 引擎", ["ai", "eigenflux", "inference", "brain", "ollama", "向量", "脑库", "推理"]),
    ("数据文档", ["data", "report", "analysis", "research", "文档", "研究", "分析"]),
    ("前端设计", ["frontend", "design", "ui", "前端", "设计"]),
]

_LAB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mt_lab_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- daemon_to_skill / skill_to_daemon
    subject TEXT NOT NULL,           -- 候选主体 (如 sys_rule_enforcer)
    reason TEXT,                     -- 推荐理由
    status TEXT DEFAULT 'PROPOSED',  -- PROPOSED / ACCEPTED / DISMISSED
    created_at TEXT DEFAULT (datetime('now','localtime'))
)
"""


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _categorize(text):
    t = text.lower()
    for cat, kws in _SKILL_CATEGORIES:
        if any(k.lower() in t for k in kws):
            return cat
    return "通用"


def _scan_skills():
    """扫描本地 skill 目录, 解析 SKILL.md frontmatter"""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for name in sorted(os.listdir(SKILLS_DIR)):
        sm = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if not os.path.isfile(sm):
            continue
        try:
            with open(sm, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2000)
        except OSError:
            continue
        fm_name, fm_desc = name, ""
        m = re.search(r"^name:\s*(.+)$", head, re.M)
        if m:
            fm_name = m.group(1).strip()
        m = re.search(r"^description:\s*(.+)$", head, re.M)
        if m:
            fm_desc = m.group(1).strip()[:160]
        cat = _categorize(fm_name + " " + fm_desc)
        skills.append({"dir": name, "name": fm_name, "desc": fm_desc, "category": cat})
    return skills


def _scan_daemons():
    """读 daemon 注册表 + 实时进程对照"""
    rows, states = [], {}
    try:
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT process_name, current_state, pid, mount_score, restart_count, "
                "mount_source, daemon_duty FROM mt_daemon_registry ORDER BY process_name"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    daemons = []
    for r in rows:
        st = r["current_state"] or "UNKNOWN"
        states[st] = states.get(st, 0) + 1
        duty = (r["daemon_duty"] or "")[:120]
        daemons.append({
            "name": r["process_name"], "state": st, "pid": r["pid"],
            "score": round(r["mount_score"] or 0, 2),
            "restarts": r["restart_count"] or 0,
            "source": r["mount_source"] or "-", "duty": duty,
        })
    # 实时进程 (注册表为空时兜底为研究数据源)
    live = set()
    try:
        import subprocess
        out = subprocess.run(["ps", "axo", "command"], capture_output=True, text=True, timeout=10).stdout
        live = set(re.findall(r"sys_[a-z_]+", out))
    except Exception:
        pass
    if not daemons and live:
        known = {"sys_eigenflux_network"}
        for name in sorted(live):
            st = "IDLE" if name in known else "RUNNING"
            states[st] = states.get(st, 0) + 1
            daemons.append({
                "name": name, "state": st, "pid": None,
                "score": 0.0, "restarts": 0, "source": "live_ps", "duty": "实时进程扫描发现 (注册表落库待同步)",
            })
    return daemons, states, live


def _derive_candidates(daemons, skills):
    """衍生引擎: daemon 无对应管理 skill → 候选; 已管理 → 跳过"""
    skill_text = " ".join(s["dir"] + " " + s["desc"] for s in skills).lower()
    candidates = []
    for d in daemons:
        key = d["name"].replace("sys_", "")
        if key in skill_text or d["name"] in skill_text:
            continue
        if d["state"] != "RUNNING":
            continue
        reason = f"daemon {d['name']} 长期运行但无配套管理 Skill (巡检/修复/状态查询 CLI 化)"
        candidates.append({"kind": "daemon_to_skill", "subject": d["name"], "reason": reason})
    return candidates[:8]


def _persist_suggestions(candidates):
    if not candidates:
        return
    try:
        conn = _db()
        try:
            conn.execute(_LAB_TABLE_SQL)
            for c in candidates:
                dup = conn.execute(
                    "SELECT 1 FROM mt_lab_suggestions WHERE kind=? AND subject=? AND status='PROPOSED'",
                    (c["kind"], c["subject"])).fetchone()
                if not dup:
                    conn.execute("INSERT INTO mt_lab_suggestions (kind, subject, reason) VALUES (?,?,?)",
                                 (c["kind"], c["subject"], c["reason"]))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


@daemon_skill_lab_bp.route("/daemon-skill-lab")
@_login_required
def lab_page():
    user = _get_user()
    return render_template("daemon_skill_lab.html", user=user)


@daemon_skill_lab_bp.route("/api/daemon-lab/overview")
@_login_required
def lab_overview():
    daemons, states, live = _scan_daemons()
    skills = _scan_skills()
    candidates = _derive_candidates(daemons, skills)
    _persist_suggestions(candidates)
    # 历史候选 (已落库)
    persisted = []
    try:
        conn = _db()
        try:
            conn.execute(_LAB_TABLE_SQL)
            rows = conn.execute(
                "SELECT kind, subject, reason, status, created_at FROM mt_lab_suggestions "
                "ORDER BY id DESC LIMIT 20").fetchall()
            persisted = [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    # 分类统计
    cat_stats = {}
    for s in skills:
        cat_stats[s["category"]] = cat_stats.get(s["category"], 0) + 1
    return jsonify({
        "ok": True,
        "daemon": {
            "total": len(daemons), "states": states, "live_processes": len(live),
            "items": daemons[:40],
        },
        "skill": {
            "total": len(skills), "categories": cat_stats, "items": skills,
        },
        "suggestions": {
            "fresh": candidates, "persisted": persisted,
        },
    })
