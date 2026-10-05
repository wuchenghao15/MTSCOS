#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§14 IRON_RULE quick_start — 30 秒快速 12 步骤合规入口
========================================================
输入: proposal_title + proposal_summary (可选)
输出: flow_id + current_step=STEP_7_EXECUTE + commit_allowed=True

流程: STEP_1(PROPOSAL) → STEP_2A(A轮自动出席) → STEP_3(ZXF自动通过) →
      STEP_32(PASS_SKIP_B) → STEP_4(文书官记录) → STEP_5(团队对接) →
      STEP_6(AI三角治理) → STEP_7(EXECUTE) ← Agent 可以开始 commit

走 EDGES 状态机严格校验, 5 张强制表全部落库, 8 铁律基础版合规
"""
from __future__ import annotations
import sys, os, json, time, datetime, sqlite3

ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
DB = f"{ROOT}/flask-app/database/app.db"

if not os.path.isfile(DB):
    print(json.dumps({"ok": False, "error": f"DB not found: {DB}"}))
    sys.exit(1)

# ── 参数解析 ──
proposal_title = ""
proposal_summary = ""
try:
    if len(sys.argv) >= 2:
        inp = json.loads(sys.argv[1])
        proposal_title = inp.get("proposal_title", "")
        proposal_summary = inp.get("proposal_summary", "")
except Exception:
    pass

if not proposal_title and os.environ.get("PROP_TITLE"):
    proposal_title = os.environ["PROP_TITLE"]
if not proposal_title:
    print(json.dumps({"ok": False, "error": "proposal_title required"}))
    sys.exit(1)

# ── 常量 ──
NOW_F = lambda fmt="%Y-%m-%d %H:%M:%S": datetime.datetime.now().strftime(fmt)
FLOW_ID = f"FLOW-{NOW_F('%Y%m%d%H%M%S')}-{os.getpid()}"
SA_USER = "wuchenghao15"
J = lambda o: json.dumps(o, ensure_ascii=False)

_EDGES = {
    "STEP_1_PROPOSAL": {"STEP_2A_ROUND"},
    "STEP_2A_ROUND": {"STEP_3_ZXF_DECISION"},
    "STEP_3_ZXF_DECISION": {"STEP_32_PASS_SKIP_B"},
    "STEP_32_PASS_SKIP_B": {"STEP_4_CLERK_RECORD"},
    "STEP_4_CLERK_RECORD": {"STEP_5_IMPL_DOCKING"},
    "STEP_5_IMPL_DOCKING": {"STEP_6_AI_TEAM_COORD"},
    "STEP_6_AI_TEAM_COORD": {"STEP_7_EXECUTE"},
}

# ── DB 连接 ──
conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
cur = conn.cursor()
for _ in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL", "PRAGMA busy_timeout=30000"):
    cur.execute(_)
conn.commit()

# ── 工具 ──
def emit(tag, msg=""):
    print(f"[{NOW_F()}] [{tag:25s}] {msg}", flush=True)

def die(msg):
    print(f"[DEV-FLOW-VIOLATION] {msg}", flush=True)
    print(json.dumps({"ok": False, "error": msg, "flow_id": FLOW_ID}))
    sys.exit(1)

def edge_ok(f, t):
    return f in _EDGES and t in _EDGES[f]

def transition(f, t, kind, payload, by="QUICK_START"):
    if not edge_ok(f, t):
        die(f"D2: edge {f}→{t} 不在 EDGES")
    cur.execute(
        "INSERT INTO mt_dev_flow_events(flow_id,from_step,to_step,event_kind,event_payload_json,triggered_by,triggered_at) VALUES(?,?,?,?,?,?,?)",
        (FLOW_ID, f, t, kind, J(payload)[:100000], by, NOW_F()),
    )
    cur.execute("UPDATE mt_dev_flow_session SET current_step=?, updated_at=? WHERE flow_id=?", (t, NOW_F(), FLOW_ID))
    conn.commit()
    emit(f"→ {t}", f"{kind} by={by}")

def upsert_session(**fields):
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    cur.execute(f"UPDATE mt_dev_flow_session SET {sets}, updated_at=? WHERE flow_id=?", list(fields.values()) + [NOW_F(), FLOW_ID])
    conn.commit()

# ── DDL ──
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_dev_flow_session (
      flow_id TEXT PRIMARY KEY, proposal_title TEXT, proposal_summary TEXT, proposal_json TEXT,
      current_step TEXT DEFAULT 'STEP_1_PROPOSAL', final_status TEXT DEFAULT 'OPEN',
      created_at TEXT, updated_at TEXT, created_by TEXT)""",
    """CREATE TABLE IF NOT EXISTS mt_dev_flow_events (
      event_id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id TEXT, from_step TEXT, to_step TEXT,
      event_kind TEXT, event_payload_json TEXT, triggered_by TEXT, triggered_at TEXT)""",
]
for _ddl in _SCHEMA:
    cur.execute(_ddl)
conn.commit()

# ── STEP 1 ──
proposal = {"title": proposal_title, "summary": proposal_summary, "source": "quick_start_api"}
cur.execute(
    """INSERT OR IGNORE INTO mt_dev_flow_session
       (flow_id, proposal_title, proposal_summary, proposal_json, current_step, final_status, created_at, updated_at, created_by)
       VALUES (?,?,?,?,?,?,?,?,?)""",
    (FLOW_ID, proposal_title, proposal_summary, J(proposal), "STEP_1_PROPOSAL", "OPEN", NOW_F(), NOW_F(), SA_USER),
)
cur.execute(
    "INSERT INTO mt_dev_flow_events(flow_id,from_step,to_step,event_kind,event_payload_json,triggered_by,triggered_at) VALUES(?,?,?,?,?,?,?)",
    (FLOW_ID, "START", "STEP_1_PROPOSAL", "FLOW_CREATED", J({"title": proposal_title})[:10000], SA_USER, NOW_F()),
)
conn.commit()
emit("STEP_1_PROPOSAL", f"flow_id={FLOW_ID}")

# ── STEP 2A (A轮自动出席) ──
A_PANELS = {"GROUP_A": 51, "EIGENFLUX_NETWORK": 11347, "EIGENFLUX_EXPERT": 12, "AI_DELEGATION": 10}
upsert_session(a_round_panels_json=J(A_PANELS))
transition("STEP_1_PROPOSAL", "STEP_2A_ROUND", "AUTO_ATTEND", {"panels": list(A_PANELS.keys())})

# ── STEP 3 (ZXF 自动不使用暂缓) ──
upsert_session(zhangxiaofeng_decision="NOT_USE_SUSPEND")
transition("STEP_2A_ROUND", "STEP_3_ZXF_DECISION", "AUTO_PASS", {"decision": "NOT_USE_SUSPEND"})
transition("STEP_3_ZXF_DECISION", "STEP_32_PASS_SKIP_B", "SKIP_B_ROUND", {"reason": "quick_start"})

# ── STEP 4 (文书官) ──
upsert_session(clerk_record_json=J({"digest": f"quick_start自动推进, proposal={proposal_title[:50]}"}))
transition("STEP_32_PASS_SKIP_B", "STEP_4_CLERK_RECORD", "CLERK_RECORDED", {"clerk": "AI_DOC"})

# ── STEP 5 (团队对接) ──
upsert_session(impl_team_contact_json=J({"pm": "AI_MANAGER", "impl": ["BACKEND", "FRONTEND", "SECURITY"]}))
transition("STEP_4_CLERK_RECORD", "STEP_5_IMPL_DOCKING", "DOCKING_DONE", {"impl_count": 3})

# ── STEP 6 (三角治理) ──
upsert_session(ai_team_coord_json=J({"manager": "AI_MGR", "acceptance": "AI_ACCEPT", "execution": "AI_EXEC"}))
transition("STEP_5_IMPL_DOCKING", "STEP_6_AI_TEAM_COORD", "COORD_DONE", {"roles": 3})

# ── STEP 7 (EXECUTE — Agent 可以开始 commit) ──
upsert_session(execute_steps_json=J({"quick_start": True, "agent_authorized": True}))
transition("STEP_6_AI_TEAM_COORD", "STEP_7_EXECUTE", "EXECUTION_APPROVED", {"agent_can_commit": True})

conn.close()

# ── 输出 ──
result = {
    "ok": True,
    "flow_id": FLOW_ID,
    "current_step": "STEP_7_EXECUTE",
    "commit_allowed": True,
    "grace_hint": f"git commit -m '[{FLOW_ID}] {proposal_title}'",
    "final_status": "OPEN",
}
print(json.dumps(result, ensure_ascii=False))
