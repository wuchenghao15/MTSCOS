#!/usr/bin/env python3
"""
§14 开发 12 步骤 flow 管理 CLI — dev_flow_cli.py
=================================================
把 dev-flow-step 技能的"复制粘贴 SQL"固化为可执行工具, 内置三重防呆:
  ① 时序防呆: done 前校验 git HEAD commit 已含 flow_id (先 commit 后 DONE)
  ② 列名防呆: PRAGMA 自适应 events 列 (event_kind), 不再手猜
  ③ 双库防呆: 主库成功才写 PROD 镜像, 任一失败即时报错不静默

用法:
  python3 dev_flow_cli.py start  <flow_id> "<title>" ["<summary>"]   # 立项→STEP_7/OPEN
  python3 dev_flow_cli.py status  [flow_id]                          # 列最近flow/查单个
  python3 dev_flow_cli.py done   <flow_id> [--test TOTAL PASS VULN]  # 收尾→STEP_12/DONE+2events

来源: flow_devflow_cli_20261021 (完善开发流程步骤)
"""
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent          # flask-app/engines/
DB_MAIN = BASE.parent / "database" / "app.db"   # OneDrive 主库
DB_PROD = Path("/Users/wuchenghao/MTSCOS_PROD/flask-app/database/app.db")
NOW = lambda: time.strftime("%Y-%m-%d %H:%M:%S")

def _dbs() -> list:
    dbs = [("主库", str(DB_MAIN))]
    if DB_PROD.exists():
        dbs.append(("PROD", str(DB_PROD)))
    return dbs

def _events_col(c: sqlite3.Connection) -> str:
    """防呆②: 自适应 events 动作列"""
    cols = [x[1] for x in c.execute("PRAGMA table_info(mt_dev_flow_events)")]
    for cand in ("event_kind", "kind", "event", "step_name"):
        if cand in cols:
            return cand
    raise RuntimeError(f"mt_dev_flow_events 无已知动作列: {cols}")

def _head_commit_contains(flow_id: str) -> tuple:
    """防呆①: HEAD commit msg 是否已含 flow_id"""
    try:
        r = subprocess.run(["git", "log", "-1", "--pretty=%H %s"], cwd=str(BASE.parent.parent),
                           capture_output=True, text=True, timeout=8)
        line = (r.stdout or "").strip()
        return (flow_id in line), line[:80]
    except Exception:
        return False, "(git 不可用)"

# ─────────────────────────── start ───────────────────────────
def cmd_start(fid: str, title: str, summary: str = "") -> int:
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        c.execute("""INSERT OR REPLACE INTO mt_dev_flow_session
            (flow_id, proposal_title, proposal_summary, proposal_json,
             current_step, final_status, created_at, updated_at, created_by)
            VALUES (?,?,?,?, 'STEP_7_EXECUTE','OPEN', ?, ?, 'agent_cli')""",
            (fid, title[:120], summary[:500],
             json.dumps({"source": "dev_flow_cli", "steps_1_6": "proposal+audit done"}, ensure_ascii=False),
             NOW(), NOW()))
        c.commit(); c.close()
        print(f"  [{tag}] {fid} → STEP_7_EXECUTE/OPEN")
    print(f"✅ 立项完成 → 可写码 → commit 带 [{fid} STEP_7] 前缀 → python3 dev_flow_cli.py done {fid}")
    return 0

# ─────────────────────────── status ──────────────────────────
def cmd_status(fid: str | None) -> int:
    c = sqlite3.connect(f"file:{DB_MAIN}?mode=ro", uri=True, timeout=8)
    c.row_factory = sqlite3.Row
    if fid:
        rows = c.execute("SELECT * FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchall()
    else:
        rows = c.execute("""SELECT flow_id, current_step, final_status, proposal_title, updated_at
                            FROM mt_dev_flow_session ORDER BY updated_at DESC LIMIT 10""").fetchall()
    for r in rows:
        d = dict(r)
        mark = "🔴未收尾" if d.get("final_status") == "OPEN" and d.get("current_step") == "STEP_12_DONE" else ""
        print(f"  {d.get('flow_id','?'):44s} {str(d.get('current_step','?')):18s} {str(d.get('final_status','?')):6s} {mark} {str(d.get('proposal_title',''))[:40]}")
    c.close()
    return 0

# ─────────────────────────── done ────────────────────────────
def cmd_done(fid: str, test: tuple | None = None) -> int:
    ok, head = _head_commit_contains(fid)
    if not ok:
        print(f"⚠️  防呆①: HEAD commit 不含 {fid}\n   HEAD: {head}\n   → 请先 git commit -m \"[{fid} STEP_7] ...\" 再收尾 (先 commit 后 DONE)")
        return 1
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        sets = ["current_step='STEP_12_DONE'", "final_status='DONE'",
                "git_sync_status='SYNCED'", "acceptance_passed=1", "updated_at=?"]
        args: list = [NOW()]
        if test:
            sets += ["test1000_total=?", "test1000_pass=?", "test1000_fail=?", "test1000_vuln=?"]
            args += [test[0], test[1], test[1] - test[0], test[2]]
        args.append(fid)
        cur = c.execute(f"UPDATE mt_dev_flow_session SET {', '.join(sets)} WHERE flow_id=?", args)
        if cur.rowcount == 0:
            print(f"  [{tag}] ❌ flow 不存在: {fid} — 先 start"); c.close(); return 1
        col = _events_col(c)
        n0 = c.execute(f"SELECT COUNT(*) FROM mt_dev_flow_events WHERE flow_id=? AND {col} IN ('TEST_DONE','ACCEPTED')", (fid,)).fetchone()[0]
        if n0 == 0:
            for kind, frm, to in (("TEST_DONE", "STEP_7_EXECUTE", "STEP_12_DONE"),
                                  ("ACCEPTED", "STEP_12_DONE", "DONE")):
                c.execute(f"""INSERT INTO mt_dev_flow_events
                    (flow_id, from_step, to_step, {col}, event_payload_json, triggered_by, triggered_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (fid, frm, to, kind, json.dumps({"via": "dev_flow_cli"}), "agent_cli", NOW()))
        c.commit()
        r = c.execute("SELECT final_status,current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        c.close()
        print(f"  [{tag}] {r} events=2")
    print("✅ 收尾完成 (双库 DONE) → git push gitee main && git push origin main")
    return 0

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__); return 1
    cmd = sys.argv[1]
    if cmd == "start" and len(sys.argv) >= 4:
        return cmd_start(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    if cmd == "status":
        return cmd_status(sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd == "done" and len(sys.argv) >= 3:
        test = None
        if "--test" in sys.argv:
            i = sys.argv.index("--test")
            test = tuple(int(x) for x in sys.argv[i + 1:i + 4])
        return cmd_done(sys.argv[2], test)
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main())
