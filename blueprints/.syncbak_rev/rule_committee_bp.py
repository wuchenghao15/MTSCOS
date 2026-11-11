#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
制法委员会 Blueprint (flow_rule_committee_20261023)
=====================================================
6 权立法机构: 制定 / 修改 / 新增 / 废除 / 整合 / 修订

页面:  GET /rule-committee              — 制法委员会主页
API:   GET /api/rule-committee/overview — 委员会总览 (法案/表决/合规)
API:   POST /api/rule-committee/propose  — 提交法案 (6 权)
API:   POST /api/rule-committee/vote     — 表决
API:   GET /api/rule-committee/archive   — 法案归档

落地表 (6 张):
  mt_committee_bills       — 法案主表 (6 种 type + 状态机)
  mt_committee_votes       — 表决记录 (赞成/反对/弃权)
  mt_committee_comments    — 委员会审议意见
  mt_committee_articles    — 法案条文 (原子条款)
  mt_committee_decrees     — 生效法令 (通过后落库)
  mt_committee_audit_log   — 立法审计日志
"""
import json, os, sqlite3, hashlib, random
from datetime import datetime
from flask import Blueprint, jsonify, request

rule_committee_bp = Blueprint("rule_committee_bp", __name__, template_folder=None)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")

def _db():
    conn = sqlite3.connect(MAIN_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn

_INIT_SQL = [
    """CREATE TABLE IF NOT EXISTS mt_committee_bills (
        bill_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT NOT NULL,              -- 制定/修改/新增/废除/整合/修订
        category TEXT,                    -- 法律法规/规则约束/准则铁律/红线
        current_status TEXT DEFAULT 'DRAFT',  -- DRAFT/REVIEWING/VOTING/PASSED/REJECTED/APPLIED/REVOKED
        proposer TEXT,                    -- 提案人 (AI员工)
        sponsor TEXT,                     -- 发起人 (委员会成员)
        description TEXT,
        rationale TEXT,                   -- 立法理由
        target_text TEXT,                 -- 目标 (要改什么)
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        vote_count INTEGER DEFAULT 0,
        approve_count INTEGER DEFAULT 0,
        reject_count INTEGER DEFAULT 0,
        abstain_count INTEGER DEFAULT 0,
        applied_at TEXT,
        revoked_at TEXT,
        UNIQUE(title, type)
    )""",
    """CREATE TABLE IF NOT EXISTS mt_committee_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id TEXT NOT NULL,
        article_no INTEGER,
        old_text TEXT,
        new_text TEXT,
        reason TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_committee_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id TEXT NOT NULL,
        voter_name TEXT NOT NULL,
        voter_role TEXT,                   -- 委员长/委员/秘书
        vote TEXT NOT NULL,                -- APPROVE/REJECT/ABSTAIN
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_committee_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id TEXT NOT NULL,
        commenter TEXT,
        role TEXT,
        content TEXT,
        severity TEXT DEFAULT 'SUGGESTION',  -- SUGGESTION/ISSUE/BLOCKER
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_committee_decrees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id TEXT UNIQUE NOT NULL,
        decree_no TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        type TEXT,
        category TEXT,
        text TEXT,                         -- 生效全文
        effective_date TEXT,
        expires_at TEXT,
        status TEXT DEFAULT 'ACTIVE',       -- ACTIVE/AMENDED/REVOKED/EXPIRED
        revoked_by_bill TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_committee_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,               -- PROPOSE/VOTE/PASS/REVOKE/AMEND
        bill_id TEXT,
        actor TEXT,
        detail TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
]

# ══ 6 权类型定义 ══
SIX_POWERS = {
    "制定":  {"desc": "从零开始创建全新的法律法规或规则体系", "verb": "制定"},
    "修改":  {"desc": "对现有条文进行文字或参数调整 (不含废除)", "verb": "修改"},
    "新增":  {"desc": "在现有规则体系内增加新条款或新章节", "verb": "新增"},
    "废除":  {"desc": "完全撤销一条或多条现有规则/法条", "verb": "废除"},
    "整合":  {"desc": "将多条分散规则合并为统一的体系化框架", "verb": "整合"},
    "修订":  {"desc": "对经过一段时间实践的规则进行系统性复盘+调整", "verb": "修订"},
}

BILL_STATUSES = ["DRAFT", "REVIEWING", "VOTING", "PASSED", "REJECTED", "APPLIED", "REVOKED"]

# ══ 委员会成员 (从教育组 exam_role='命题' 中 hash 精选 + 部分污染治理组) ══
def _get_committee_members(cursor, size=30):
    """从 ai_employees 中按 exam_role + track 选委员"""
    rows = cursor.execute("""
        SELECT name, employee_code, exam_role, track, title
        FROM ai_employees
        WHERE (exam_role IN ('命题','审题','阅卷') OR group_tag='AI污染治理')
          AND status='active'
        ORDER BY RANDOM() LIMIT ?
    """, (size,)).fetchall()
    return rows

# ══ 核心: 提案 → 审议 → 表决 → 生效 状态机 ══
def _advance_bill(cursor, bill_id, action, detail=""):
    """推进法案状态"""
    transitions = {
        "PROPOSE":  {"from": None,        "to": "REVIEWING"},
        "REVIEW":   {"from": "REVIEWING", "to": "VOTING"},
        "VOTE":     {"from": "VOTING",    "to": None},
        "PASS":     {"from": "VOTING",    "to": "PASSED"},
        "APPLY":    {"from": "PASSED",    "to": "APPLIED"},
        "REJECT":   {"from": "VOTING",    "to": "REJECTED"},
        "REVOKE":   {"from": "APPLIED",   "to": "REVOKED"},
    }
    cursor.execute("UPDATE mt_committee_bills SET updated_at=datetime('now','localtime') WHERE bill_id=?", (bill_id,))
    cursor.execute("""INSERT INTO mt_committee_audit_log (action, bill_id, actor, detail) VALUES (?,?,?,?,?)""",
                   (action, bill_id, "committee", detail))
    return transitions.get(action, {}).get("to")

# ══ 守护循环 (每 60min 自动推进审议) ══
def run_committee_cycle():
    """法案自动流转: DRAFT→REVIEWING→VOTING→(PASS→APPLIED) / REJECT"""
    conn = _db()
    c = conn.cursor()
    for sql in _INIT_SQL: c.execute(sql)
    conn.commit()

    log = {"auto_review": 0, "auto_vote": 0, "auto_pass": 0, "auto_reject": 0, "auto_apply": 0}

    # 自动审议: DRAFT → REVIEWING
    drafts = c.execute("SELECT bill_id FROM mt_committee_bills WHERE current_status='DRAFT' LIMIT 5").fetchall()
    for d in drafts:
        new_state = _advance_bill(c, d["bill_id"], "REVIEW")
        if new_state == "VOTING":
            c.execute("UPDATE mt_committee_bills SET current_status='VOTING', updated_at=datetime('now','localtime') WHERE bill_id=?", (d["bill_id"],))
            log["auto_review"] += 1

    # 自动表决: REVIEWING → VOTING + 模拟委员投票
    reviewing = c.execute("SELECT bill_id FROM mt_committee_bills WHERE current_status='REVIEWING' LIMIT 3").fetchall()
    for r in reviewing:
        bid = r["bill_id"]
        c.execute("UPDATE mt_committee_bills SET current_status='VOTING' WHERE bill_id=?", (bid,))
        members = _get_committee_members(c, size=10)
        approve = reject = abstain = 0
        for m in members:
            h = int(hashlib.md5((bid + m["employee_code"]).encode()).hexdigest(), 16) % 100
            if h < 70:
                vote = "APPROVE"; approve += 1
            elif h < 85:
                vote = "REJECT"; reject += 1
            else:
                vote = "ABSTAIN"; abstain += 1
            c.execute("""INSERT INTO mt_committee_votes (bill_id, voter_name, voter_role, vote, created_at)
                         VALUES (?,?,?,?,datetime('now','localtime'))""",
                      (bid, m["name"], m["exam_role"] or "委员", vote))
        c.execute("""UPDATE mt_committee_bills SET vote_count=?, approve_count=?, reject_count=?, abstain_count=?
                     WHERE bill_id=?""", (len(members), approve, reject, abstain, bid))
        log["auto_vote"] += 1
        # 过半数赞成 → PASSED, 否则 REJECTED
        if approve > reject and approve >= len(members) * 0.5:
            c.execute("UPDATE mt_committee_bills SET current_status='PASSED' WHERE bill_id=?", (bid,))
            log["auto_pass"] += 1
        else:
            c.execute("UPDATE mt_committee_bills SET current_status='REJECTED' WHERE bill_id=?", (bid,))
            log["auto_reject"] += 1

    # 自动生效: PASSED → APPLIED + 落库 mt_committee_decrees
    passed = c.execute("SELECT bill_id, title, type, category FROM mt_committee_bills WHERE current_status='PASSED' LIMIT 2").fetchall()
    for p in passed:
        bid = p["bill_id"]
        decree_no = f"DEC-{bid[-8:]}"
        c.execute("""INSERT OR REPLACE INTO mt_committee_decrees
                     (bill_id, decree_no, title, type, category, effective_date, status)
                     VALUES (?,?,?,?,?,datetime('now','localtime'),'ACTIVE')""",
                  (bid, decree_no, p["title"], p["type"], p["category"]))
        c.execute("""UPDATE mt_committee_bills SET current_status='APPLIED', applied_at=datetime('now','localtime')
                     WHERE bill_id=?""", (bid,))
        log["auto_apply"] += 1

    conn.commit()
    conn.close()
    return log


# ══ Flask 路由 ══
@rule_committee_bp.route("/api/rule-committee/overview")
def api_overview():
    try:
        conn = _db(); c = conn.cursor()
        for sql in _INIT_SQL: c.execute(sql); conn.commit()

        bills = c.execute("SELECT current_status, COUNT(*) FROM mt_committee_bills GROUP BY current_status").fetchall()
        votes = c.execute("SELECT bill_id, vote, COUNT(*) FROM mt_committee_votes GROUP BY bill_id, vote").fetchall()
        decrees = c.execute("SELECT status, COUNT(*) FROM mt_committee_decrees GROUP BY status").fetchall()
        members = _get_committee_members(c, size=30)
        status_dict = {r["current_status"]: r[1] for r in bills}
        return jsonify({
            "ok": True,
            "timestamp": datetime.now().isoformat(),
            "bills_total": sum(status_dict.values()),
            "bills_by_status": status_dict,
            "decrees_active": sum(r[1] for r in decrees if r["status"] == "ACTIVE"),
            "committee_size": len(members),
            "six_powers": list(SIX_POWERS.keys()),
            "bill_count": dict(status_dict),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@rule_committee_bp.route("/api/rule-committee/propose", methods=["POST"])
def api_propose():
    try:
        data = request.get_json(force=True)
        title = data.get("title", "")
        btype = data.get("type", "制定")
        category = data.get("category", "规则约束")
        proposer = data.get("proposer", "committee")
        description = data.get("description", "")
        rationale = data.get("rationale", "")
        target = data.get("target", "")

        if btype not in SIX_POWERS:
            return jsonify({"ok": False, "error": f"type 必须是 {list(SIX_POWERS.keys())} 之一"}), 400
        if not title:
            return jsonify({"ok": False, "error": "title 必填"}), 400

        conn = _db(); c = conn.cursor()
        for sql in _INIT_SQL: c.execute(sql); conn.commit()

        bill_id = f"BILL_{btype}_{hashlib.md5(title.encode()).hexdigest()[:8]}"
        try:
            c.execute("""INSERT INTO mt_committee_bills
                         (bill_id, title, type, category, proposer, description, rationale, target_text, current_status)
                         VALUES (?,?,?,?,?,?,?,?,'DRAFT')""",
                      (bill_id, title, btype, category, proposer, description, rationale, target))
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "error": "同 type+title 已存在"}), 409
        conn.commit()

        # 立即自动流转一轮
        log = run_committee_cycle()

        return jsonify({"ok": True, "bill_id": bill_id, "cycle_log": log})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@rule_committee_bp.route("/api/rule-committee/archive")
def api_archive():
    try:
        conn = _db(); c = conn.cursor()
        bills = c.execute("""
            SELECT b.bill_id, b.title, b.type, b.current_status,
                   b.approve_count, b.reject_count, b.abstain_count,
                   d.decree_no, d.status as decree_status
            FROM mt_committee_bills b
            LEFT JOIN mt_committee_decrees d ON d.bill_id = b.bill_id
            ORDER BY b.created_at DESC LIMIT 50
        """).fetchall()
        return jsonify({"ok": True, "bills": [dict(b) for b in bills]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@rule_committee_bp.route("/rule-committee")
def page_committee():
    return api_overview()
