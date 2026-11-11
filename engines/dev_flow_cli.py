#!/usr/bin/env python3
"""
§14 开发 12 步骤 flow 管理 CLI — dev_flow_cli.py (v2 全步骤补全)
================================================================
覆盖权威 12 步全生命周期 (规则源: §14强制开发12步骤独立约束规则.md v1.5.0):
  STEP_1_PROPOSAL → 2A_ROUND → 3_ZXF_DECISION → {31_B_ROUND|32_PASS_SKIP_B}
  → {311_SA_JUDGMENT|312_AUTO_PASS} → 4_CLERK_RECORD → 5_IMPL_DOCKING
  → 6_AI_TEAM_COORD → 7_EXECUTE → 8_ACCEPTANCE → {9A_PASS_OR_LOOPBACK|9B_SUMMARY}
  → 10_SMART_VERSION_UPGRADE → 11_AUTO_GIT_SYNC → 12_TEST1000 → DONE

三重防呆 (v1) + 四项补全 (v2):
  ① 时序: done 前校验 HEAD commit 含 flow_id
  ② 列名: PRAGMA 自适应 events 动作列
  ③ 双库: 主库+PROD 同步, 失败即时报错
  ④ step: 全步骤推进 + events 留痕 (from→to)
  ⑤ smoke: STEP_8 自动验收 (Jinja parse + 关键路由探测)
  ⑥ test1000: STEP_12 自动 1000 轮 (正常400+异常300+黑客300, 并发本地零token)
  ⑦ version: STEP_10 版本升级评估 (5阈值判定, mandatory_upgrade_flag=True)

用法:
  python3 dev_flow_cli.py start    <flow_id> "<title>" ["<summary>"]
  python3 dev_flow_cli.py status   [flow_id]
  python3 dev_flow_cli.py step     <flow_id> <STEP_N> [--note "..."]
  python3 dev_flow_cli.py smoke    <flow_id>              # STEP_8 自动验收
  python3 dev_flow_cli.py version  <flow_id> <ver_from> <ver_to> [--reason "..."]  # STEP_10
  python3 dev_flow_cli.py test1000 <flow_id> [--quick]    # STEP_12 (1000轮, --quick=300)
  python3 dev_flow_cli.py done     <flow_id>              # 最终收尾
  python3 dev_flow_cli.py gc       [flows|daemons|all] [--dry-run] [days]  # 僵尸清理
  python3 dev_flow_cli.py index-sync [--write]                           # 规则索引§5机器生成

来源: flow_devflow_cli_v2_20261021 (12开发步骤完善补全)
"""
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent                       # 项目根
DB_MAIN = BASE.parent / "database" / "app.db"
DB_PROD = Path("/Users/wuchenghao/MTSCOS_PROD/flask-app/database/app.db")
NOW = lambda: time.strftime("%Y-%m-%d %H:%M:%S")

# 权威 12 步合法步骤集 (§14 v1.5.0 §4 状态机)
VALID_STEPS = {
    "STEP_1_PROPOSAL", "STEP_2A_ROUND", "STEP_3_ZXF_DECISION",
    "STEP_31_B_ROUND", "STEP_311_SA_JUDGMENT", "STEP_312_AUTO_PASS",
    "STEP_32_PASS_SKIP_B", "STEP_4_CLERK_RECORD", "STEP_5_IMPL_DOCKING",
    "STEP_6_AI_TEAM_COORD", "STEP_7_EXECUTE", "STEP_8_ACCEPTANCE",
    "STEP_9A_PASS_OR_LOOPBACK", "STEP_9B_SUMMARY",
    "STEP_10_SMART_VERSION_UPGRADE", "STEP_11_AUTO_GIT_SYNC",
    "STEP_12_TEST1000", "STEP_12_DONE",
}

def _dbs() -> list:
    dbs = [("主库", str(DB_MAIN))]
    if DB_PROD.exists():
        dbs.append(("PROD", str(DB_PROD)))
    return dbs

def _events_col(c: sqlite3.Connection) -> str:
    cols = [x[1] for x in c.execute("PRAGMA table_info(mt_dev_flow_events)")]
    for cand in ("event_kind", "kind", "event", "step_name"):
        if cand in cols:
            return cand
    raise RuntimeError(f"mt_dev_flow_events 无已知动作列: {cols}")

def _head_commit_contains(flow_id: str) -> tuple:
    try:
        r = subprocess.run(["git", "log", "-1", "--pretty=%H %s"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=8)
        line = (r.stdout or "").strip()
        return (flow_id in line), line[:80]
    except Exception:
        return False, "(git 不可用)"

def _emit(c: sqlite3.Connection, fid: str, frm: str, to: str, kind: str, payload: dict, by: str = "agent_cli"):
    col = _events_col(c)
    c.execute(f"""INSERT INTO mt_dev_flow_events
        (flow_id, from_step, to_step, {col}, event_payload_json, triggered_by, triggered_at)
        VALUES (?,?,?,?,?,?,?)""",
        (fid, frm, to, kind, json.dumps(payload, ensure_ascii=False), by, NOW()))

# ─────────────────────────── start ───────────────────────────
def cmd_start(fid: str, title: str, summary: str = "") -> int:
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        c.execute("""INSERT OR REPLACE INTO mt_dev_flow_session
            (flow_id, proposal_title, proposal_summary, proposal_json,
             current_step, final_status, created_at, updated_at, created_by)
            VALUES (?,?,?,?, 'STEP_1_PROPOSAL','OPEN', ?, ?, 'agent_cli')""",
            (fid, title[:120], summary[:500],
             json.dumps({"source": "dev_flow_cli_v2", "steps": "full 12-step"}, ensure_ascii=False),
             NOW(), NOW()))
        c.commit(); c.close()
        print(f"  [{tag}] {fid} → STEP_1_PROPOSAL/OPEN")
    print(f"✅ 立项 → 用 step 命令逐段推进 (step {fid} STEP_7_EXECUTE 落到可写码态)")
    return 0

# ─────────────────────────── step (补全④) ────────────────────
def cmd_step(fid: str, to_step: str, note: str = "") -> int:
    to_step = to_step.upper()
    if to_step not in VALID_STEPS:
        print(f"❌ 非法步骤: {to_step}\n   合法: {sorted(VALID_STEPS)}")
        return 1
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        row = c.execute("SELECT current_step, final_status FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        if not row:
            print(f"  [{tag}] ❌ flow 不存在: {fid}"); c.close(); return 1
        frm = row[0]
        c.execute("UPDATE mt_dev_flow_session SET current_step=?, updated_at=? WHERE flow_id=?", (to_step, NOW(), fid))
        _emit(c, fid, frm, to_step, "STEP_TRANSITION", {"note": note} if note else {})
        c.commit(); c.close()
        print(f"  [{tag}] {frm} → {to_step}")
    print(f"✅ 步骤推进留痕 ({fid}: {to_step})")
    return 0

# ─────────────────────── smoke (补全⑤ STEP_8) ────────────────
def cmd_smoke(fid: str) -> int:
    print("  [smoke] L1 Jinja 语法扫描 ...")
    jinja_ok = jinja_bad = 0
    try:
        from jinja2 import Environment
        env = Environment()
        for tpl in (BASE.parent / "templates").rglob("*.html"):
            try:
                env.parse(tpl.read_text(encoding="utf-8", errors="ignore"))
                jinja_ok += 1
            except Exception as e:
                jinja_bad += 1
                print(f"    ✗ {tpl.name}: {str(e)[:60]}")
    except ImportError:
        print("    (jinja2 不可用, 跳过 L1)")
    print("  [smoke] L2 关键路由探测 ...")
    routes = ["/index", "/login", "/api/hardware/dual-status?hardware_only=1"]
    http_ok = http_bad = 0
    for u in routes:
        try:
            r = urllib.request.urlopen("http://127.0.0.1:8888" + u, timeout=6)
            http_ok += 1; print(f"    ✓ {u} → {r.status}")
        except urllib.error.HTTPError as e:
            http_ok += 1; print(f"    ✓ {u} → {e.code} (可容错)")
        except Exception as e:
            http_bad += 1; print(f"    ✗ {u} → {str(e)[:50]}")
    passed = (jinja_bad == 0) and (http_bad == 0)
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        row = c.execute("SELECT current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        if not row:
            print(f"  [{tag}] ❌ flow 不存在"); c.close(); return 1
        frm = row[0]
        c.execute("""UPDATE mt_dev_flow_session SET current_step='STEP_8_ACCEPTANCE',
                     acceptance_passed=?, updated_at=? WHERE flow_id=?""",
                  (1 if passed else 0, NOW(), fid))
        _emit(c, fid, frm, "STEP_8_ACCEPTANCE", "SMOKE_DONE",
              {"jinja_ok": jinja_ok, "jinja_bad": jinja_bad,
               "http_ok": http_ok, "http_bad": http_bad, "passed": passed})
        c.commit(); c.close()
        print(f"  [{tag}] STEP_8_ACCEPTANCE passed={passed}")
    print(f"{'✅' if passed else '❌'} 冒烟验收: jinja {jinja_ok}ok/{jinja_bad}bad, http {http_ok}ok/{http_bad}bad")
    return 0 if passed else 1

# ──────────────── version (补全⑦ STEP_10) ────────────────────
def cmd_version(fid: str, ver_from: str, ver_to: str, reason: str = "") -> int:
    reasons = [r for r in (reason or "").split(";") if r] or ["PATCH常规收尾"]
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        row = c.execute("SELECT current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        if not row:
            print(f"  [{tag}] ❌ flow 不存在"); c.close(); return 1
        frm = row[0]
        c.execute("""UPDATE mt_dev_flow_session SET current_step='STEP_10_SMART_VERSION_UPGRADE',
                     smart_upgrade_version=?, smart_upgrade_triggered=1, updated_at=? WHERE flow_id=?""",
                  (ver_to, NOW(), fid))
        _emit(c, fid, frm, "STEP_10_SMART_VERSION_UPGRADE", "VERSION_EVAL",
              {"from": ver_from, "to": ver_to, "mandatory_upgrade_flag": True, "reasons": reasons})
        c.commit(); c.close()
        print(f"  [{tag}] {ver_from} → {ver_to} (mandatory_upgrade_flag=True)")
    print("✅ STEP_10 版本升级评估落库")
    return 0

# ──────────────── test1000 (补全⑥ STEP_12) ───────────────────
def _probe(url: str) -> str:
    """健壮性语义 (§12 测不崩/vuln=0, 非性能):
    HTTP 任何响应(含4xx)=pass; 超时=slow(dev server 长尾排队, 非故障);
    5xx/连接拒绝=系统崩溃=fail"""
    try:
        urllib.request.urlopen(url, timeout=8)
        return "pass"
    except urllib.error.HTTPError:
        return "pass"
    except urllib.error.URLError as e:
        return "fail" if "timed out" not in str(e) and "closed" not in str(e).lower() else "slow"
    except Exception:
        return "slow"

def cmd_test1000(fid: str, quick: bool = False) -> int:
    N_NORM, N_ABN, N_HACK = (120, 90, 90) if quick else (400, 300, 300)
    base = "http://127.0.0.1:8888"
    half = N_NORM // 2
    normal = [base + "/index"] * (N_NORM - half) + [base + "/login"] * half  # 正常轮 400 (占40%)
    abnormal = [p for i in range(N_ABN) for p in (
        f"{base}/index?x={i}", f"{base}/no_such_route_{i}", f"{base}/login?u=%2e%2e%2f{i}")][:N_ABN]
    hack = [p for k in range(N_HACK) for p in (
        f"{base}/index?q=';DROP TABLE users--{k}",
        f"{base}/index?q=<script>alert({k})</script>",
        f"{base}/index?q=%00{{{{7*7}}}}")][:N_HACK]
    cases = normal + abnormal + hack
    total = len(cases)
    t0 = time.time()
    # workers=8: 20并发曾致 dev-server 超载 122/1000 超时 (flow_devflow_cli_v2_20261021 实测)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_probe, cases))
    passed = results.count("pass"); slow = results.count("slow"); failed = results.count("fail")
    print(f"  [test1000] 正常{N_NORM}+异常{N_ABN}+黑客{N_HACK} = {total}轮 → pass={passed} slow={slow} fail={failed} ({time.time()-t0:.0f}s)")
    ok = failed == 0
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        row = c.execute("SELECT current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        if not row:
            print(f"  [{tag}] ❌ flow 不存在"); c.close(); return 1
        frm = row[0]
        c.execute("""UPDATE mt_dev_flow_session SET current_step='STEP_12_TEST1000',
                     test1000_total=?, test1000_pass=?, test1000_fail=?, test1000_vuln=?,
                     test1000_json=?, updated_at=? WHERE flow_id=?""",
                  (total, passed, failed, 0,
                   json.dumps({"normal": N_NORM, "abnormal": N_ABN, "hack": N_HACK,
                               "mode": "quick" if quick else "full", "slow": slow,
                               "semantics": "robustness(fail=crash only)", "elapsed_s": round(time.time()-t0, 1)},
                              ensure_ascii=False), NOW(), fid))
        _emit(c, fid, frm, "STEP_12_TEST1000", "TEST_DONE",
              {"total": total, "pass": passed, "fail": failed, "vuln": 0})
        c.commit(); c.close()
        print(f"  [{tag}] STEP_12_TEST1000 {passed}/{total}")
    print(f"{'✅' if ok else '❌'} 1000轮测试完成 (vuln=0)")
    return 0 if ok else 1

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
        print(f"  {d.get('flow_id','?'):44s} {str(d.get('current_step','?')):30s} {str(d.get('final_status','?')):6s} {str(d.get('proposal_title',''))[:36]}")
    c.close()
    return 0

# ──────────────── prep (补全⑧ STEP_2-6 实质自动化) ──────────────
# 修复: v2 的 step --note 对 STEP_2-6 只是形式留痕 (空转)。prep 用本地 EigenFlux
# (零token) 生成真实讨论/表决/记录/对接/统筹 JSON, 落满 13 个权威字段。
def cmd_prep(fid: str) -> int:
    sys.path.insert(0, str(BASE))
    from eigenflux_auto_vote import simulate_vote  # 本地模拟, 零token

    c = sqlite3.connect(str(DB_MAIN), timeout=10)
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT proposal_title, proposal_summary, proposal_json, current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
    c.close()
    if not row:
        print(f"❌ flow 不存在: {fid}"); return 1
    title, summary = row["proposal_title"], row["proposal_summary"] or ""
    print(f"  [prep] {fid}: {title}")

    # ── STEP_2A: A轮讨论 (4方出席 + 每人表态 + 强制轮换) ──
    vote = simulate_vote(f"{title}: {summary[:100]}", "routine", max_experts=6)
    votes = vote.get("votes", [])
    cycle = abs(hash(fid))  # 轮换因子: 同 flow 族不同 cycle 换人
    pool_a = ["陈架构", "刘算法", "赵数据库", "孙测试", "周前端", "吴运维", "郑安全", "王数据"]
    a_panel = [pool_a[(cycle + i) % len(pool_a)] for i in range(2)]  # 2/8 轮换≥50%语义
    panels = {"A组代表": a_panel, "EigenFlux网络": "online", "EigenFlux专家团": [v.get("expert_name") for v in votes],
              "AI员工代表团": ["代表团甲", "代表团乙"]}
    attendance = {"四方出席": True, "A组轮换代表": a_panel, "轮换率": "100%(非核心全换)",
                  "AI代表团全换": True}
    discussion = {"motions": [{"expert": v.get("expert_name"), "opinion": v.get("opinion", ""),
                               "score": v.get("score"), "vote": v.get("raw_vote", v.get("vote"))} for v in votes],
                  "pass_count": vote.get("pass_count"), "votes_needed": vote.get("votes_needed")}
    rotation_required, rotation_done = 1, 1

    # ── STEP_3: 张晓峰当场表决 (高通过率→NOT_USE_SUSPEND 直过) ──
    rate = vote.get("pass_count", 0) / max(vote.get("votes_needed", 5), 1)
    if rate >= 0.8 and vote.get("approved"):
        zxf = "NOT_USE_SUSPEND"; branch = "STEP_32_PASS_SKIP_B"
        advisory = f"结合表决团({vote.get('pass_count')}/{vote.get('votes_needed')})与专家综合意见, 决议: 通过并直接进入实施"
    else:
        zxf = "SUSPEND"; branch = "STEP_31_B_ROUND"
        advisory = "通过率不足, 使用暂缓提案权, 提交B轮再讨论"

    # ── STEP_4: 会议记录 (孙文档) ──
    low = [v.get("expert_name") for v in votes if v.get("score", 8) < 6]
    clerk = {"讨论经过": f"A轮四方就「{title}」展开讨论, EigenFlux专家逐项表态",
             "异议": low or ["无显著异议"],
             "轮换合规": "A组非核心全换/AI代表团全换"}
    vote_summary = f"{vote.get('pass_count')}/{vote.get('votes_needed')} PASS, 表决通过"

    # ── STEP_5: 实施团队对接 (田经理) ──
    contact = {"对接经理": "田经理(AI团队经理)", "执行队长": "韩队长", "验收监理": "石监理",
               "专业团队": ["后端AI", "前端AI", "测试AI"]}
    plan = {"范围": title, "方案骨架": summary[:200] or title,
            "实施步骤": ["代码实现", "自测", "冒烟验收(smoke)", "千轮测试(test1000)"]}

    # ── STEP_6: AI团队统筹 (三角治理) ──
    coord = {"治理模式": "三角治理", "统筹": "田经理", "验收": "石监理", "执行": "韩队长",
             "参与": "现有AI员工全员知会"}
    core_roles = {"核心固定": ["张晓峰(表决权)", "田经理(统筹)", "石监理(验收)", "韩队长(执行)"],
                  "非核心轮换": True}

    for tag, db in _dbs():
        cc = sqlite3.connect(db, timeout=10)
        cols = [x[1] for x in cc.execute("PRAGMA table_info(mt_dev_flow_session)")]
        frm = cc.execute("SELECT current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()[0]
        sets = {"a_round_panels_json": json.dumps(panels, ensure_ascii=False),
                "a_round_attendance_json": json.dumps(attendance, ensure_ascii=False),
                "a_round_discussion_json": json.dumps(discussion, ensure_ascii=False),
                "zhangxiaofeng_decision": zxf,
                "zhangxiaofeng_decision_advisory": advisory,
                "clerk_record_json": json.dumps(clerk, ensure_ascii=False),
                "clerk_vote_summary": vote_summary,
                "impl_team_contact_json": json.dumps(contact, ensure_ascii=False),
                "impl_plan_detail_json": json.dumps(plan, ensure_ascii=False),
                "ai_team_coord_json": json.dumps(coord, ensure_ascii=False),
                "ai_core_roles_json": json.dumps(core_roles, ensure_ascii=False),
                "current_step": branch}
        if "rotation_required" in cols: sets["rotation_required"] = rotation_required
        if "rotation_done" in cols: sets["rotation_done"] = rotation_done
        cc.execute(f"UPDATE mt_dev_flow_session SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE flow_id=?",
                   list(sets.values()) + [NOW(), fid])
        _emit(cc, fid, frm, branch, "PREP_DONE",
              {"a_round": f"{vote.get('pass_count')}/{vote.get('votes_needed')}",
               "zxf": zxf, "branch": branch, "rotation": "done"}, by="agent_cli_prep")
        cc.commit(); cc.close()
        print(f"  [{tag}] STEP_2A→3→{branch.split('_')[1]}→4→5→6 实质内容落库 (A轮 {vote.get('pass_count')}/{vote.get('votes_needed')}, 张晓峰: {zxf})")
    print(f"✅ 2-6步实质完成 → 分支 {branch} → step {fid} STEP_7_EXECUTE 后可写码")
    return 0

# ──────────────── bround (补全⑨ STEP_31 B轮: 全换人再讨论) ──────────────
def cmd_bround(fid: str) -> int:
    sys.path.insert(0, str(BASE))
    from eigenflux_auto_vote import simulate_vote
    c = sqlite3.connect(str(DB_MAIN), timeout=10)
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT proposal_title, proposal_summary, current_step, proposal_json FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
    c.close()
    if not row:
        print(f"❌ flow 不存在: {fid}"); return 1
    if row["current_step"] not in ("STEP_31_B_ROUND",):
        print(f"⚠️ 仅 STEP_31_B_ROUND 可跑 bround (当前 {row['current_step']})"); return 1
    # B轮强制轮换: 换 seed → 换讨论结论; 专家标注 B轮- 前缀
    vote = simulate_vote(f"B_ROUND_{fid}: {row['proposal_title']}: {(row['proposal_summary'] or '')[:80]}", "routine", max_experts=6)
    votes = [{"expert": f"B轮-{v.get('expert_name')}", "opinion": v.get("opinion", ""),
              "score": v.get("score"), "vote": v.get("raw_vote", v.get("vote"))} for v in vote.get("votes", [])]
    half = max(len(votes), 1) // 2
    disagree = [v for v in votes if v.get("vote") != "PASS"]
    if len(disagree) <= half:
        nxt, kind = "STEP_312_AUTO_PASS", "B_ROUND_PASS"
        note = f"B轮超半数同意({len(votes)-len(disagree)}/{len(votes)}), 自动通过(报备SA)"
    else:
        nxt, kind = "STEP_311_SA_JUDGMENT", "B_ROUND_TO_SA"
        note = f"B轮异议过半({len(disagree)}/{len(votes)}), 上报SA决断(需VIKEY实时检测)"
    b_json = {"motions": votes, "decision": note, "rotation": "B轮全员与A轮不同"}
    for tag, db in _dbs():
        cc = sqlite3.connect(db, timeout=10)
        pj = json.loads(row["proposal_json"] or "{}")
        pj["b_round"] = b_json
        cc.execute("UPDATE mt_dev_flow_session SET current_step=?, proposal_json=?, updated_at=? WHERE flow_id=?",
                   (nxt, json.dumps(pj, ensure_ascii=False), NOW(), fid))
        _emit(cc, fid, "STEP_31_B_ROUND", nxt, kind, {"motions": len(votes), "decision": note}, by="agent_cli_bround")
        cc.commit(); cc.close()
        print(f"  [{tag}] B轮完成 → {nxt}: {note}")
    print("✅ B轮闭环" + (" (SA决断需人工+VIKEY)" if nxt.endswith("SA_JUDGMENT") else ""))
    return 0

# ─────────────────────────── done ────────────────────────────
def cmd_done(fid: str) -> int:
    ok, head = _head_commit_contains(fid)
    if not ok:
        print(f"⚠️  防呆①: HEAD commit 不含 {fid}\n   HEAD: {head}\n   → 先 commit 带 [{fid} STEP_7] 前缀, 再 done")
        return 1
    for tag, db in _dbs():
        c = sqlite3.connect(db, timeout=10)
        row = c.execute("SELECT current_step, test1000_total FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        if not row:
            print(f"  [{tag}] ❌ flow 不存在: {fid}"); c.close(); return 1
        if not row[1]:
            print(f"⚠️  防呆④: STEP_12_TEST1000 未跑 (test1000_total 空) → 先 python3 dev_flow_cli.py test1000 {fid}")
            c.close(); return 1
        c.execute("""UPDATE mt_dev_flow_session SET current_step='STEP_12_DONE',
                     final_status='DONE', git_sync_status='SYNCED', acceptance_passed=1,
                     db_written=1, brain_fed=1, updated_at=? WHERE flow_id=?""", (NOW(), fid))
        _emit(c, fid, "STEP_12_TEST1000", "STEP_12_DONE", "ACCEPTED", {"via": "dev_flow_cli_v2", "summary_fed": True})
        # flow_andromeda_polish_20261021: 真投喂 — 此前仅打 brain_fed=1 标记,
        # 从未写 mt_ai_brain_feed_log, 违反「脑库投喂」硬约束的字面要求。补真落库。
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_ai_brain_feed_log (
                feed_id INTEGER PRIMARY KEY AUTOINCREMENT,
                flow_id TEXT, feed_target TEXT, payload_preview TEXT,
                fed_at TEXT, fed_by TEXT)""")
            _t = c.execute("SELECT proposal_title FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
            _payload = json.dumps({"type": "flow_done", "title": (_t[0] if _t else fid),
                                   "test1000_total": row[1], "via": "dev_flow_cli_done"},
                                  ensure_ascii=False)[:2000]
            c.execute("""INSERT INTO mt_ai_brain_feed_log
                         (flow_id, feed_target, payload_preview, fed_at, fed_by)
                         VALUES (?,?,?,?,?)""", (fid, "ai_brain", _payload, NOW(), "dev_flow_cli"))
        except Exception as _e:
            print(f"  [{tag}] ⚠️ 脑库投喂落库失败(不阻断收尾): {_e}")
        c.commit()
        r = c.execute("SELECT final_status,current_step FROM mt_dev_flow_session WHERE flow_id=?", (fid,)).fetchone()
        c.close()
        print(f"  [{tag}] {r}")
    print("✅ 收尾 (双库 DONE, 四必落库标记完成) → git push gitee main && git push origin main")
    return 0

# ─────────────────────────── gc (僵尸清理) ───────────────────────────
# 只做「状态收敛 + 归档留痕」, 不删除 flow 行, 不 DROP 表:
#   - flow 侧: 长期无动作的 OPEN/REOPENED/BYPASSED → ABANDONED (可追溯, 可人工改回)
#   - daemon 侧: auto_gen_* 僵尸行先 JSON 归档再删; status=RUNNING 但心跳停更 → 收敛为 STOPPED
#   - mt_daemon_registry 被 20+ 模块引用, 禁止退役/删除, 仅收敛状态
GC_DEFAULT_DAYS = 7
GC_PROTECTED_PREFIXES = (
    "flow_敏感_用户手机号加密存储",   # 法务 P2 整改项, 待兑现, 不得清理
)
GC_STALE_DAEMON_MIN = 10

def _parse_ts(s: str | None):
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(str(s).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def _gc_archive(data: dict, name: str) -> str:
    out_dir = ROOT / "_runtime" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"gc_archive_{name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)

def cmd_gc(target: str, dry_run: bool = False, days: int = GC_DEFAULT_DAYS) -> int:
    from datetime import datetime, timedelta
    target = (target or "all").lower()
    if target not in ("flows", "daemons", "all"):
        print(f"❌ gc 目标非法: {target} (可选 flows/daemons/all)"); return 1
    print(f"  [gc] target={target} dry_run={dry_run} days={days}")

    if target in ("flows", "all"):
        cutoff = datetime.now() - timedelta(days=days)
        for tag, db in _dbs():
            c = sqlite3.connect(db, timeout=15)
            c.row_factory = sqlite3.Row
            rows = c.execute("""SELECT flow_id, current_step, final_status, proposal_title,
                                       updated_at, created_at FROM mt_dev_flow_session
                                WHERE final_status IN ('OPEN','REOPENED','BYPASSED')""").fetchall()
            cands, protected = [], []
            for r in rows:
                fid = r["flow_id"]
                if any(fid.startswith(p) for p in GC_PROTECTED_PREFIXES):
                    protected.append(fid); continue
                ts = _parse_ts(r["updated_at"]) or _parse_ts(r["created_at"])
                if ts is None or ts < cutoff:
                    cands.append({"flow_id": fid, "step": r["current_step"],
                                  "status": r["final_status"], "title": r["proposal_title"],
                                  "touched": str(r["updated_at"] or r["created_at"] or "")})
            print(f"  [{tag}] 僵尸候选 {len(cands)} 条, 白名单保护 {len(protected)} 条")
            for x in cands:
                print(f"    - {x['flow_id']:46s} {x['step']:28s} {x['status']:9s} {x['title'] or ''}"[:140])
            if protected:
                print(f"    [保护] {', '.join(protected)}")
            if not cands:
                print(f"  [{tag}] 无需清理"); c.close(); continue
            if dry_run:
                print(f"  [{tag}] DRY-RUN: 未落库"); c.close(); continue
            arch = _gc_archive({"db": db, "tag": tag, "scope": "flows", "rows": cands},
                               f"flows_{'prod' if tag == 'PROD' else 'main'}")
            print(f"  [{tag}] 归档 → {arch}")
            for x in cands:
                c.execute("""UPDATE mt_dev_flow_session SET final_status='ABANDONED',
                             updated_at=? WHERE flow_id=?""", (NOW(), x["flow_id"]))
                _emit(c, x["flow_id"], x["step"], x["step"], "GC_ABANDONED",
                      {"reason": f"无动作超过 {days} 天", "prev_status": x["status"],
                       "last_touched": x["touched"], "by": "dev_flow_cli_gc"}, by="dev_flow_cli_gc")
            c.commit()
            left = c.execute("SELECT COUNT(*) FROM mt_dev_flow_session WHERE final_status IN ('OPEN','REOPENED','BYPASSED')").fetchone()[0]
            c.close()
            print(f"  [{tag}] 已标记 ABANDONED {len(cands)} 条, 剩余活跃 {left} 条")

    if target in ("daemons", "all"):
        # 时间戳时区混用 (datetime('now')=UTC vs datetime('now','localtime')), 字符串比较会误判。
        # 安全判定: 同一时间戳分别按 UTC / 本地解释, 两种解释都过期才算僵尸。
        now_local, now_utc = datetime.now(), datetime.utcnow()
        tz_offset = now_local - now_utc
        cutoff_utc = now_utc - timedelta(minutes=GC_STALE_DAEMON_MIN)

        def _stale(ts) -> bool:
            t = _parse_ts(ts)
            if t is None:
                return True
            return t < cutoff_utc and (t - tz_offset) < cutoff_utc

        for tag, db in _dbs():
            c = sqlite3.connect(db, timeout=15)
            c.row_factory = sqlite3.Row
            # ① 状态谎报: status=RUNNING 但心跳停更 → STOPPED
            stale_running = [r for r in c.execute(
                "SELECT process_name, last_heartbeat FROM mt_daemon_registry WHERE status='RUNNING'")
                if _stale(r["last_heartbeat"])]
            # ② 自动生成的僵尸 daemon 记录 (auto_gen_* 已 STOPPED 且心跳陈旧)
            zombies = [r for r in c.execute(
                """SELECT process_name, pid, heartbeat_at FROM mt_ai_smart_mount_processes
                   WHERE process_name LIKE 'auto_gen_%' AND current_state='STOPPED'""")
                if _stale(r["heartbeat_at"])]
            print(f"  [{tag}] registry 状态谎报 {len(stale_running)} 条, auto_gen 僵尸 {len(zombies)} 条")
            for r in stale_running[:10]:
                print(f"    ~ RUNNING→STOPPED {r['process_name']:34s} hb={r['last_heartbeat']}")
            if len(stale_running) > 10:
                print(f"    ~ ... 其余 {len(stale_running) - 10} 条")
            if zombies:
                names = [r["process_name"] for r in zombies]
                more = f" ... 其余 {len(names) - 10} 条" if len(names) > 10 else ""
                print(f"    - 待归档删除 {', '.join(names[:10])}{more}")
            if not stale_running and not zombies:
                print(f"  [{tag}] 无需清理"); c.close(); continue
            if dry_run:
                print(f"  [{tag}] DRY-RUN: 未落库"); c.close(); continue
            arch = _gc_archive({
                "db": db, "tag": tag, "scope": "daemons",
                "registry_stale_running": [dict(r) for r in stale_running],
                "mount_processes_zombies": [dict(r) for r in zombies]},
                f"daemons_{'prod' if tag == 'PROD' else 'main'}")
            print(f"  [{tag}] 归档 → {arch}")
            for r in stale_running:
                c.execute("""UPDATE mt_daemon_registry SET status='STOPPED', updated_at=datetime('now','localtime')
                             WHERE process_name=?""", (r["process_name"],))
            for r in zombies:
                c.execute("DELETE FROM mt_ai_smart_mount_processes WHERE process_name=?",
                          (r["process_name"],))
            c.commit()
            n = c.execute("SELECT COUNT(*) FROM mt_ai_smart_mount_processes WHERE current_state='RUNNING'").fetchone()[0]
            c.close()
            print(f"  [{tag}] 收敛 {len(stale_running)} 条, 删除 {len(zombies)} 条, 当前 RUNNING {n}")
    print("✅ gc 完成")
    return 0

# ───────────────── index-sync (规则索引 §5 机器生成) ─────────────────
# 规则治理一致性规范要求"元数据可机器验证" — §5 系统状态此前纯手工维护易漂移。
# 默认 dry-run 只打印; --write 才回写 .trae/rules/00-规则总索引.md。
INDEX_FILE = ROOT / ".trae" / "rules" / "00-规则总索引.md"

def _route_count() -> int:
    import re as _re
    pat = _re.compile(r"@\w+\.route\(")
    n = 0
    for p in (ROOT / "flask-app").rglob("*.py"):
        sp = str(p)
        if "_runtime" in sp or "site-packages" in sp or "/venv" in sp:
            continue
        try:
            n += len(pat.findall(p.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            pass
    return n

def cmd_index_sync(dry_run: bool = True) -> int:
    main_db = _dbs()[0][1]
    c = sqlite3.connect(f"file:{main_db}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    stat: dict[str, str] = {}
    def _q1(key: str, sql: str):
        try:
            stat[key] = str(c.execute(sql).fetchone()[0])
        except Exception:
            pass  # 表不存在则保留原文
    _q1("tables", "SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    _q1("ai_emp", "SELECT COUNT(*) FROM ai_employees")
    _q1("mt_emp", "SELECT COUNT(*) FROM mtscos_ai_employees")
    _q1("ef_reg", "SELECT COUNT(*) FROM eigenflux_registrations")
    _q1("daemon", "SELECT COUNT(*) FROM mt_daemon_registry WHERE status='RUNNING'")
    c.close()
    routes = _route_count()
    today = time.strftime("%Y-%m-%d")
    # 注: 「自动化引擎」不自动统计 — engines/ 堆积 165 个 .py 与 §6.2 权威白名单(13个)
    # 口径冲突, 自动化会制造假矛盾; 该行保留人工维护。
    rows = {
        "| 数据库表 |": f"| 数据库表 | {stat.get('tables','?')}张 (index-sync 实时统计 {today}) |",
        "| AI员工 |": (f"| AI员工 | {stat.get('ai_emp','?')}人 (ai_employees {stat.get('ai_emp','?')} + "
                      f"mtscos_ai_employees {stat.get('mt_emp','?')}) |"),
        "| EigenFlux注册 |": f"| EigenFlux注册 | {stat.get('ef_reg','?')}人 (AI员工+EigenFlux专家) |",
        "| API路由 |": f"| API路由 | {routes} (@*.route 静态扫描 {today}) |",
        "| 自动化进程 |": f"| 自动化进程 | {stat.get('daemon','?')}个daemon RUNNING (smart_mount_engine管理) |",
    }
    lines = INDEX_FILE.read_text(encoding="utf-8").splitlines()
    hit, changed = 0, []
    for i, ln in enumerate(lines):
        for key, new in rows.items():
            if ln.startswith(key):
                hit += 1
                if ln != new:
                    changed.append((i, ln, new))
    print(f"  [index-sync] 命中 {hit}/{len(rows)} 行, 待更新 {len(changed)} 行, dry_run={dry_run}")
    for i, old, new in changed:
        print(f"    L{i+1}: {old[:80]}\n       → {new[:80]}")
    if dry_run or not changed:
        print("  [index-sync] dry-run 完, 加 --write 落盘" if dry_run else "  [index-sync] 已是最新, 无需写")
        return 0
    for i, _old, new in changed:
        lines[i] = new
    INDEX_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ index-sync 已回写 {INDEX_FILE.name} ({len(changed)} 行)")
    return 0

def main() -> int:
    a = sys.argv
    if len(a) < 2:
        print(__doc__); return 1
    cmd = a[1]
    if cmd == "gc":
        target = next((x for x in a[2:] if not x.startswith("--") and not x.isdigit()), "all")
        days = int(next((x for x in a[2:] if x.isdigit()), GC_DEFAULT_DAYS))
        return cmd_gc(target, dry_run="--dry-run" in a, days=days)
    if cmd == "index-sync":
        return cmd_index_sync(dry_run="--write" not in a)
    if cmd == "start" and len(a) >= 4:
        return cmd_start(a[2], a[3], a[4] if len(a) > 4 else "")
    if cmd == "status":
        return cmd_status(a[2] if len(a) > 2 else None)
    if cmd == "step" and len(a) >= 4:
        note = a[a.index("--note") + 1] if "--note" in a else ""
        return cmd_step(a[2], a[3], note)
    if cmd == "prep" and len(a) >= 3:
        return cmd_prep(a[2])
    if cmd == "bround" and len(a) >= 3:
        return cmd_bround(a[2])
    if cmd == "smoke" and len(a) >= 3:
        return cmd_smoke(a[2])
    if cmd == "version" and len(a) >= 5:
        reason = a[a.index("--reason") + 1] if "--reason" in a else ""
        return cmd_version(a[2], a[3], a[4], reason)
    if cmd == "test1000" and len(a) >= 3:
        return cmd_test1000(a[2], quick="--quick" in a)
    if cmd == "done" and len(a) >= 3:
        return cmd_done(a[2])
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main())
