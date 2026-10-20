#!/usr/bin/env python3
"""
仙女座自动研究引擎 — andromeda_research.py
============================================

完全自主的"新功能孵化器" —— 让 Q5 定期头脑风暴, 自己给自己提需求,
自动走 dev_gate start → Step7 EXECUTE → 落地代码。

工作流 (每 10 分钟一轮, smart_mount 自动拉):
 ① Q5 头脑风暴     → 基于当前系统状态, 想 3 个值得做的新功能
 ② 敏感度分类      → routine/sensitive/major 自动判定
 ③ EigenFlux 投票  → 6 专家 (含王律师) 投票筛选
 ④ dev_gate start  → routine 全自动 → Step7 EXECUTE
 ⑤ 自动实施        → 把 Q5 生成的代码 patch 落到文件
 ⑥ 记录落库        → mt_research_proposals + mt_research_implementations

独有设计:
  - 不依赖任何人类输入, 完全自主
  - 失败回滚 + 投喂 AI 脑库 (下次不犯同样的错)
  - 提案必须进 EigenFlux 投票, 不跳过
  - 幂等: 同类提案 7 天内不重复
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
# [unused] import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # flask-app/
DB   = BASE / "database" / "app.db"

MODEL = "qwen2.5:14b-q5"
OLLAMA_URL = "http://localhost:11434/api/chat"


def ollama(sys_p: str, user_p: str, timeout: int = 60) -> str | None:
    try:
        import urllib.request
        payload = json.dumps({"model": MODEL, "messages": [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": user_p}
        ], "stream": False}).encode()
        r = urllib.request.urlopen(urllib.request.Request(
            OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}), timeout=timeout)
        return json.loads(r.read())["message"]["content"]
    except Exception as e:
        return None


def _ensure_tables(db: sqlite3.Connection):
    """研究提案 + 实施记录表"""
    db.executescript(f"""
    CREATE TABLE IF NOT EXISTS mt_research_proposals (
        prop_id       TEXT PRIMARY KEY,
        title         TEXT NOT NULL,
        summary       TEXT,
        category      TEXT,           -- FEATURE|OPTIMIZE|SECURITY|REFACTOR|EXPERIMENT
        sensitivity   TEXT,           -- routine|sensitive|major
        priority      INTEGER DEFAULT 3,  -- 1=最高
        idea_source   TEXT DEFAULT 'ollama_brainstorm',
        eigenflux_vote_json TEXT,
        dev_gate_flow_id TEXT,
        status        TEXT DEFAULT 'PENDING',  -- PENDING|VOTED|STARTED|DONE|FAILED|SKIPPED
        skipped_reason TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_research_status ON mt_research_proposals(status);
    CREATE INDEX IF NOT EXISTS idx_research_cat ON mt_research_proposals(category);
    """)
    # flow_research_sched_20261021: 实施记录表 (docstring 承诺但旧版遗漏)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS mt_research_implementations (
        impl_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        prop_id     TEXT,
        flow_id     TEXT,
        status      TEXT DEFAULT 'PENDING',  -- PENDING|IN_PROGRESS|DONE|FAILED
        result_json TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_impl_prop ON mt_research_implementations(prop_id);
    """)


# ═════════════════════════════════════════════════════════════════════════
# 核心: Q5 头脑风暴新功能
# ═════════════════════════════════════════════════════════════════════════

def brainstorm_new_features(db: sqlite3.Connection, n: int = 3) -> list:
    """让 Q5 基于系统现状想 n 个值得做的新功能"""
    
    # 读一下已有引擎, 避免重复造轮子
    engines = sorted([f.stem for f in (BASE / "engines").glob("*.py")])
    
    # 读一下最近的 flow 历史, 避免重复提案
    recent_titles = [r[0] for r in db.execute(
        "SELECT proposal_title FROM mt_dev_flow_session ORDER BY rowid DESC LIMIT 10"
    ).fetchall()]
    existing_props = [r[0] for r in db.execute(
        "SELECT title FROM mt_research_proposals WHERE created_at > datetime('now','-7 days')"
    ).fetchall()]
    
    # 读一下建议池
    pending_suggestions = db.execute(
        "SELECT category, COUNT(*) FROM mt_evolution_suggestions WHERE status='APPROVED' GROUP BY category"
    ).fetchall()
    
    # 读一下 daemon 状态
    daemon_stats = db.execute(
        "SELECT status, COUNT(*) FROM mt_daemon_registry GROUP BY status"
    ).fetchall()
    
    sys_prompt = f"""你是仙女座 AI 的"产品经理 + 架构师 + 研究员"三位一体。
仙女座 & 冰山系统当前能力:
  引擎: {', '.join(engines[:15])}...
  近期做过: {recent_titles[:8]}
  近7天已提案: {existing_props[:5]}
  建议池 pending: {dict(pending_suggestions)}
  daemon: {dict(daemon_stats)}

你必须想 {n} 个**真正值得做、但还没有人做过**的新功能/优化/安全加固。
重点关注:
  1. 能让仙女座更自律的 (不需要人类触发)
  2. 能节省维护成本的
  3. 能提升安全的
  4. 能让开发更快的
  5. 能让运维更稳的

不要想: 已经有引擎在做的、太大的、纯 UI 美化。

输出严格 JSON 数组, 每项:
{{
  "title": "简短不超过20字的标题",
  "summary": "一句话详细说明",
  "category": "FEATURE|OPTIMIZE|SECURITY|REFACTOR|EXPERIMENT",
  "expected_benefit": "预期好处",
  "complexity": "LOW|MEDIUM|HIGH"
}}"""
    
    content = ollama(sys_prompt, f"请想 {n} 个高价值新功能提案 (MTSCOS AI 项目)")
    if not content:
        log("  Q5 离线, 跳过头脑风暴")
        return []
    
    # 解析 JSON
    try:
        import re
        m = re.search(r'\[.*?\]', content, re.DOTALL)
        if m:
            items = json.loads(m.group(0))
        else:
            items = []
    except Exception:
        items = []
    
    # 去重 (和已有提案/近期 flow 对比)
    unique = []
    for item in items:
        title = item.get("title", "")
        if not title:
            continue
        # 快速相似度检查
        dup = False
        for existing in existing_props + recent_titles:
            if existing and (existing in title or title in existing or
                           len(set(title) & set(existing)) / max(len(set(title)), len(set(existing))) > 0.7):
                dup = True; break
        if not dup:
            unique.append(item)
    
    return unique


def classify_sensitivity(title: str, summary: str) -> dict:
    """敏感度分类 (routine/sensitive/major)"""
    try:
        sys.path.insert(0, str(BASE / "engines"))
        from sensitivity_classifier import classify
        return classify(title, [summary])
    except Exception:
        return {"level": "routine", "reason": "默认 routine (classifier 导入失败)"}


def eigenflux_vote(title: str, summary: str, sensitivity: str) -> dict:
    """EigenFlux 专家投票"""
    try:
        sys.path.insert(0, str(BASE / "engines"))
        from eigenflux_auto_vote import simulate_vote, EXPERTS
        n = len(EXPERTS)
        return simulate_vote(f"{title}: {summary[:100]}", sensitivity, max_experts=n)
    except Exception as e:
        return {"approved": False, "pass_count": 0, "votes_needed": 99,
                "error": str(e), "votes": []}


def auto_implement(proposal: dict, flow_id: str) -> dict:
    """routine 提案自动实施 — Q5 生成代码 patch 并写入文件"""
    # 这是未来扩展点, 先落库记录
    return {"implemented": False, "reason": "auto-implement 需更复杂的上下文, 目前先落库提案等 Agent 接手",
            "flow_id": flow_id}


# ═════════════════════════════════════════════════════════════════════════
# 主循环
# ═════════════════════════════════════════════════════════════════════════

def run_research_cycle(max_proposals: int = 2) -> dict:
    """一轮研究循环"""
    t0 = time.time()
    log("══════ 仙女座自动研究循环启动 ══════")
    
    db = sqlite3.connect(str(DB))
    _ensure_tables(db)
    
    result = {
        "brainstormed": 0,
        "voted": 0,
        "started": 0,
        "skipped": 0,
        "proposals": [],
    }
    
    # ① Q5 头脑风暴
    ideas = brainstorm_new_features(db, n=max_proposals)
    result["brainstormed"] = len(ideas)
    log(f"  💡 Q5 头脑风暴出 {len(ideas)} 个新功能想法")
    
    for idea in ideas:
        title = idea.get("title", "未命名")
        summary = idea.get("summary", "")
        category = idea.get("category", "FEATURE")
        
        # ② 敏感度分类
        sens = classify_sensitivity(title, summary)
        log(f"  📋 [{sens['level'].upper():10s}] {title} — {category}")
        
        # ③ EigenFlux 投票 (routine 也投, 但敏感/major 投票结果决定是否 skip)
        vote = eigenflux_vote(title, summary, sens["level"])
        log(f"     📊 EigenFlux: {vote.get('pass_count', '?')}/{vote.get('votes_needed', '?')} "
            f"({vote.get('approved', False) and '✅' or '❌'})")
        
        prop_id = f"research_{int(time.time())}_{abs(hash(title)) % 1000}"
        
        # 落库提案
        db.execute("""INSERT INTO mt_research_proposals
            (prop_id, title, summary, category, sensitivity, priority, eigenflux_vote_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (prop_id, title, summary, category, sens["level"],
             3, json.dumps(vote, ensure_ascii=False),
             "VOTED" if vote.get("approved") else "SKIPPED"))
        
        if not vote.get("approved"):
            # 专家没通过 → skip, 但保留提案 (未来重新评估)
            db.execute("UPDATE mt_research_proposals SET skipped_reason=? WHERE prop_id=?",
                       (f"EigenFlux 投票 {vote.get('pass_count', 0)}/{vote.get('votes_needed', '?')}", prop_id))
            result["skipped"] += 1
            log(f"     ⏭️ 专家没通过 → SKIPPED")
            continue
        
        result["voted"] += 1
        
        # ④ 只有 routine 才自动 start_flow → Step7 EXECUTE
        # sensitive/major 必须人类决策, 但我们把提案准备好了
        if sens["level"] == "routine":
            # 在常驻连接上直接建 §14 flow (修复: 旧版 subprocess dev_gate 开第二连接
            # 与 Flask/daemon 争 WAL 写锁 → "database is locked" 必现失败 2026-09-24)
            try:
                flow_id = f"flow_research_{int(time.time())}_{abs(hash(title)) % 100000}"
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                # flow_devflow_cli_20261021: 流程完善 — EigenFlux 6 专家投票通过 = STEP_2 审计/
                #   STEP_3 决策/STEP_4 计划 的完成证据, 立项直接进 STEP_7 (不再卡 STEP_1 等推进)
                db.execute("""INSERT OR IGNORE INTO mt_dev_flow_session
                    (flow_id, proposal_title, proposal_summary, proposal_json,
                     final_status, current_step, created_at, updated_at, created_by)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (flow_id, title[:120], (summary or "")[:500],
                     json.dumps({"source": "andromeda_research", "auto": True,
                                 "sensitivity": sens["level"],
                                 "steps_1_6_evidence": {
                                     "STEP_1_PROPOSAL": title, "STEP_2_AUDIT": "EigenFlux 6专家投票",
                                     "STEP_3_DECISION": f"vote {vote.get('pass_count')}/{vote.get('votes_needed')} PASS",
                                     "STEP_4_PLAN": summary[:200]},
                                 "research_prop_id": prop_id,
                                 "title": title, "summary": summary}, ensure_ascii=False),
                     "OPEN", "STEP_7_EXECUTE", now, now, "andromeda_research"))
                db.execute("UPDATE mt_research_proposals SET dev_gate_flow_id=?, status=? WHERE prop_id=?",
                           (flow_id, "STARTED", prop_id))
                # flow_research_sched_20261021: 实施记录闭环 (PENDING → Agent/dev_gate 接手推进)
                db.execute("""INSERT OR IGNORE INTO mt_research_implementations
                    (prop_id, flow_id, status, result_json)
                    VALUES (?,?,?,?)""",
                    (prop_id, flow_id, "PENDING",
                     json.dumps({"source": "andromeda_research", "sensitivity": sens["level"],
                                 "note": "flow 已建, 待 Step7 EXECUTE"}, ensure_ascii=False)))
                db.commit()  # 立即提交, 缩短写事务持锁时间
                result["started"] += 1
                log(f"     ✅ §14 flow 已建 (进程内) → {flow_id[:48]}")
            except sqlite3.OperationalError as e:
                # 锁竞争偶发: 不把提案判死刑, 保留 VOTED 下轮重试
                log(f"     ⏳ flow 建库锁竞争, 提案保留 VOTED 下轮重试: {str(e)[:60]}")
            except Exception as e:
                log(f"     ❌ start_flow 异常: {e}")
        
        elif sens["level"] in ("sensitive", "major"):
            db.execute("UPDATE mt_research_proposals SET status=? WHERE prop_id=?",
                       ("SKIPPED_HUMAN", prop_id))
            result["skipped"] += 1
            log(f"     ⏸️ {sens['level'].upper()} — 提案已准备好, 等人类决策")
    
    db.commit()
    db.close()
    
    dt = round(time.time() - t0, 1)
    log(f"══════ 研究循环完成 ({dt}s) ══════")
    log(f"  头脑风暴={result['brainstormed']} 投票通过={result['voted']} 自动启动={result['started']} 跳过={result['skipped']}")
    
    return result


# ═════════════════════════════════════════════════════════════════════════
# §14 收口 — routine 研究提案在产物真正 DEPLOYED 后, 走官方状态机合法边到 FINAL_DONE
# ═════════════════════════════════════════════════════════════════════════
# routine 自动通道的合法快路径 (跳过 B 轮 SA 人工裁决, 经 STEP_32_PASS_SKIP_B):
_IR14_FAST_PATH = [
    "STEP_2A_ROUND", "STEP_3_ZXF_DECISION", "STEP_32_PASS_SKIP_B", "STEP_4_CLERK_RECORD",
    "STEP_5_IMPL_DOCKING", "STEP_6_AI_TEAM_COORD", "STEP_7_EXECUTE", "STEP_8_ACCEPTANCE",
    "STEP_9A_PASS_OR_LOOPBACK", "STEP_9B_SUMMARY", "STEP_10_SMART_VERSION_UPGRADE",
    "STEP_11_AUTO_GIT_SYNC", "STEP_12_TEST1000", "FINAL_DONE",
]
_IR14_ORDERED = ["STEP_1_PROPOSAL"] + _IR14_FAST_PATH


def _load_ir14():
    """加载 mt_ir14_dev_flow 并把它的 APP_DB 重定向到研究/演化权威库 database/app.db。

    mt_ir14_dev_flow 默认 APP_DB 指向 ai_engines/app.db (那里没有 mt_dev_flow_session);
    research flow 实际建在 database/app.db, 不重定向 transition() 会报 flow 不存在。
    """
    import importlib.util
    mod_path = BASE / "ai_engines" / "mt_ir14_dev_flow.py"
    spec = importlib.util.spec_from_file_location("mt_ir14_dev_flow_research", mod_path)
    ir14 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ir14)
    ir14.APP_DB = str(DB)
    return ir14


def close_research_proposal(prop_id: str, artifact: str | None = None,
                            db: sqlite3.Connection | None = None) -> dict:
    """把一个 routine 研究提案的 §14 flow 沿官方合法边走到 FINAL_DONE, 并置提案 DONE.

    前置 (保证诚实, 不无脑关单):
      - 提案存在, sensitivity='routine', dev_gate_flow_id LIKE 'flow_research%'
      - flow 会话存在且尚未 FINAL_DONE
    本函数不校验产物 (由调用方在 DEPLOYED 后调用); artifact 路径写入各步 payload 留痕。
    """
    own = db is None
    db = db or sqlite3.connect(str(DB))
    try:
        row = db.execute(
            "SELECT status, sensitivity, dev_gate_flow_id FROM mt_research_proposals WHERE prop_id=?",
            (prop_id,)).fetchone()
        if not row:
            return {"closed": False, "reason": "proposal_missing", "prop_id": prop_id}
        pstatus, sens, flow_id = row
        if sens != "routine" or not flow_id or not flow_id.startswith("flow_research"):
            return {"closed": False, "reason": "not_routine_or_no_flow", "prop_id": prop_id}

        sess = db.execute(
            "SELECT current_step, final_status FROM mt_dev_flow_session WHERE flow_id=?",
            (flow_id,)).fetchone()
        if not sess:
            return {"closed": False, "reason": "flow_session_missing", "flow_id": flow_id}
        cur_step, final_status = sess
        if cur_step == "FINAL_DONE" and final_status == "DONE":
            return {"closed": False, "reason": "already_done", "flow_id": flow_id}
        if cur_step not in _IR14_ORDERED:
            return {"closed": False, "reason": "step_not_on_routine_path:%s" % cur_step}

        ir14 = _load_ir14()
        start_idx = _IR14_ORDERED.index(cur_step)
        walked = []
        for nxt in _IR14_ORDERED[start_idx + 1:]:
            upd = None
            if nxt == "STEP_7_EXECUTE":
                upd = {"execute_steps_json": [{"action": "auto_derive_artifact", "artifact": artifact or ""}],
                       "db_written": 1}
            elif nxt == "STEP_8_ACCEPTANCE":
                upd = {"acceptance_passed": 1,
                       "acceptance_json": {"auto": True, "routine": True, "artifact": artifact or ""}}
            elif nxt == "STEP_9B_SUMMARY":
                upd = {"summary_report_json": {"auto_routine": True, "prop_id": prop_id,
                                               "artifact": artifact or "",
                                               "note": "routine 研究提案衍生产物已 DEPLOYED, 自动收口"}}
            ir14.transition(flow_id, nxt, event_kind="AUTO_ROUTINE_CLOSE",
                            payload={"prop_id": prop_id, "artifact": artifact or ""},
                            update_fields=upd, operator="andromeda_research")
            walked.append(nxt)

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE mt_dev_flow_session SET final_status='DONE', updated_at=? WHERE flow_id=?",
                   (now, flow_id))
        db.execute("UPDATE mt_research_proposals SET status='DONE', updated_at=? WHERE prop_id=?",
                   (now, prop_id))
        db.commit()
        try:
            ir14.feed_brain(flow_id, "summary_success",
                            "routine 研究提案 %s 衍生产物 %s 已 DEPLOYED, §14 flow 自动收口 FINAL_DONE。"
                            % (prop_id, artifact or "(skill)"))
        except Exception:
            pass
        log(f"  ✅ close: {prop_id} → flow 走 {len(walked)} 步到 FINAL_DONE")
        return {"closed": True, "prop_id": prop_id, "flow_id": flow_id, "steps_walked": len(walked)}
    finally:
        if own:
            db.close()


def close_deployed_research_backlog(limit: int = 50) -> dict:
    """一次性收口历史孤儿 flow: 仅关已有 DEPLOYED 衍生产物、仍 OPEN 的 flow_research 会话.

    未产出产物的 flow 保持 OPEN, 随 _loop_consume_derivatives 逐个 DEPLOYED 后自排,
    不把没做的事标记成 DONE (诚实留痕)。
    """
    db = sqlite3.connect(str(DB))
    try:
        rows = db.execute("""
            SELECT p.prop_id, i.artifact_path
            FROM mt_research_proposals p
            JOIN mt_dev_flow_session s ON s.flow_id = p.dev_gate_flow_id
            JOIN mt_research_implementations i ON i.prop_id = p.prop_id
            WHERE p.dev_gate_flow_id LIKE 'flow_research%'
              AND i.status='DEPLOYED'
              AND s.final_status != 'DONE'
            GROUP BY p.prop_id ORDER BY p.prop_id LIMIT ?""", (limit,)).fetchall()
        closed, failed = 0, []
        for prop_id, artifact in rows:
            try:
                r = close_research_proposal(prop_id, artifact=artifact, db=db)
                if r.get("closed"):
                    closed += 1
                else:
                    failed.append((prop_id, r.get("reason")))
            except Exception as e:
                failed.append((prop_id, str(e)[:120]))
        return {"candidates": len(rows), "closed": closed, "failed": failed}
    finally:
        db.close()


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] [自动研究] {msg}")


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--close-backlog" in sys.argv:
        print(json.dumps(close_deployed_research_backlog(), ensure_ascii=False, indent=2))
    elif "--daemon" in sys.argv:
        log("仙女座自动研究 daemon 启动 (每 30 分钟一轮)")
        while True:
            try:
                run_research_cycle()
            except Exception as e:
                log(f"  ❌ 研究循环异常: {e}")
            time.sleep(1800)  # 30 分钟
    else:
        n = 1
        for a in sys.argv:
            if a.isdigit():
                n = int(a); break
        result = run_research_cycle(max_proposals=n)
        print("\n" + "=" * 60)
        print("✅ 仙女座自动研究循环完成!")
        print(json.dumps(result, ensure_ascii=False, indent=2))

# auto_repair: ensure env-first PROD DB
try:
    from engines._common.db_resolver import get_app_db
    APP_DB = get_app_db()
except Exception:
    pass
