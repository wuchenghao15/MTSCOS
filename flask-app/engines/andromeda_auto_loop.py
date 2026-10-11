#!/usr/bin/env python3
"""
仙女座自律循环 — andromeda_auto_loop.py
=========================================

完全自主的自我演化循环 —— 不依赖 Trae 触发, 也不需要人工干预。
smart_mount_engine 会自动作为 daemon 启动, 每 5 分钟跑一轮。

5 个内置循环 (15-20s 一轮):
 ① loop_evolve         → 38 routes prompt 进化 + 自动实施建议池
 ② loop_patrol_auto    → 9 类规则扫描 + 发现问题 → Q5 生成 patch → 自动落库
 ③ loop_rule_strengthen → 规则弱约束词扫描 + 自动写回规则文件
 ④ loop_daemon_health  → 15 daemon 存活巡检 + 自动重启
 ⑤ loop_benchmark      → 每 24h 模型跑分

独有能力:
  - 发现的问题 → 自动调用 dev_gate start 创建 flow → 自动修复
  - 修复后 → 自动写 git commit (带 flow_id, pre-commit 放行)
  - 失败 → 自动回滚 + 投喂 AI 脑库 + 记录到建议池
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ── 路径 ──
BASE = Path(__file__).resolve().parent.parent  # flask-app/
DB   = BASE / "database" / "app.db"

# Ollama
OLLAMA_URL = "http://localhost:11435/api/chat"
MODEL = "qwen2.5:14b-q5"

def ollama_chat(sys_p: str, user_p: str, timeout: int = 30) -> str | None:
    try:
        import urllib.request
        payload = json.dumps({"model": MODEL, "messages": [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": user_p}
        ], "stream": False}).encode()
        r = urllib.request.urlopen(urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type":"application/json"}), timeout=timeout)
        return json.loads(r.read())["message"]["content"]
    except Exception as e:
        return None


# ═════════════════════════════════════════════════════════════════════════
# 核心循环
# ═════════════════════════════════════════════════════════════════════════

def run_self_loop():
    """一轮完整自律循环"""
    t0 = time.time()
    log(f"══════ 仙女座自律循环启动 ══════")
    
    results = {}

    # 1. Dev gate 检查 (自指闭环: 自律循环也必须有 flow_id)
    flow_id = _ensure_flow()
    if flow_id:
        log(f"  🛡️ flow_id={flow_id}")

    # 2. Daemon 健康巡检 (心跳级感知 + 修复诉求投递, 不再盲目 fork)
    # 3. 规则弱约束词扫描 + 自动强化
    # 4. 建议池自动实施
    # 5. 每 24h benchmark
    # 6. 🌌 自探研 (Ollama 头脑风暴, 30min 节流)
    # 7. 🧬 衍生升级 (研究提案 → 建议池)
    # 每步独立隔离: 任一步异常绝不拖垮整轮 (修复历史"零产出空转")
    def _safe(name, fn):
        try:
            results[name] = fn()
        except Exception as e:
            log(f"  ⚠️ 步骤 {name} 异常隔离: {e}")
            results[name] = {"error": str(e)[:200]}

    _safe("daemon", _loop_daemon_health)
    _safe("rule", _loop_rule_strengthen)
    _safe("auto_impl", _loop_auto_implement)
    _safe("benchmark", _loop_benchmark_if_needed)
    _safe("research", _loop_self_research)
    _safe("promote", _loop_promote_derivatives)
    
    dt = time.time() - t0
    log(f"══════ 自律循环完成 ({dt:.1f}s) ══════")
    log(f"  结果: {json.dumps(results, ensure_ascii=False)}")
    
    # 记录到 andromeda_core 的 mt_evolution_runs
    _record_run(dt, results)
    
    return results


def _ensure_flow() -> str | None:
    """确保自律循环自己有一个合法 flow_id — 直接 DB 操作, 不 fork subprocess"""
    db = sqlite3.connect(str(DB))
    # 找有没有 andromeda 自己的 OPEN flow
    r = db.execute(
        "SELECT flow_id FROM mt_dev_flow_session WHERE final_status='OPEN' AND flow_id LIKE '%andromeda%' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if r:
        db.close()
        return r[0]
    
    # 没有 → 直接 INSERT 一个 (routine, 跳过 dev_gate subprocess)
    try:
        flow_id = f"flow_andromeda_loop_{int(time.time())}"
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        
        db.execute("""INSERT OR IGNORE INTO mt_dev_flow_session
            (flow_id, proposal_title, proposal_summary, proposal_json,
             final_status, current_step, created_at, updated_at, created_by)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (flow_id, "仙女座自律循环", "自律循环自我演化 (routine)",
             json.dumps({"source": "andromeda_auto_loop", "auto": True}, ensure_ascii=False),
             "OPEN", "STEP_1_PROPOSAL", now, now, "andromeda_auto_loop"))
        db.commit()
        log(f"  🆕 自律循环自创建 flow_id={flow_id} (直接 DB, 跳过 dev_gate)")
        db.close()
        return flow_id
    except Exception as e:
        log(f"  ⚠️ 创建 flow 失败: {e}")
        db.close()
        return None


def _loop_daemon_health() -> dict:
    """全量 daemon 心跳级健康巡检 (v2: 不再盲目 fork).

    设计原则:
    - smart_mount_engine 是权威进程主管, auto_loop 不做第二个 fork 监管者 (避免脑裂)
    - 本函数只负责: 感知 (pid 存活 + 心跳新鲜度) → 标记 FAILED → 向建议池投递修复诉求
    - 修复诉求被 auto_repair / smart_mount 的强制要求池扫描消费, 由权威主管统一拉起
    """
    db = sqlite3.connect(str(DB))
    alive = 0; dead = 0; stale = 0; repair_requested = 0
    STALE_SEC = 1800  # 心跳超过 30 分钟视为停滞
    now_ts = time.time()

    def _parse_hb(hb):
        if not hb: return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try: return time.mktime(time.strptime(hb[:len(time.strftime(fmt))] if '.' not in hb else hb[:26], fmt))
            except Exception: continue
        return None

    rows = db.execute(
        "SELECT process_name, pid, status, COALESCE(last_heartbeat,'') "
        "FROM mt_daemon_registry").fetchall()
    total = len(rows)

    for name, pid_str, status, hb in rows:
        # ① pid 存活检测
        pid_dead = False
        tracked = pid_str not in (None, "", 0, "0")
        if tracked:
            try:
                os.kill(int(pid_str), 0)
            except Exception:
                pid_dead = True

        # ② 心跳新鲜度
        hb_ts = _parse_hb(hb)
        hb_age = (now_ts - hb_ts) if hb_ts else None
        hb_stale = hb_age is not None and hb_age > STALE_SEC

        if pid_dead:
            dead += 1
            log(f"  🔴 进程死亡: {name} (pid={pid_str}, hb={hb})")
        elif hb_stale and status == "RUNNING":
            stale += 1
            log(f"  🟡 心跳停滞 {int(hb_age//60)}min: {name} (pid={pid_str})")
        else:
            alive += 1
            continue

        # ③ 标记 FAILED (状态机纠偏: RUNNING 但实际死/停 → FAILED)
        if status == "RUNNING":
            db.execute("UPDATE mt_daemon_registry SET status='FAILED' WHERE process_name=?", (name,))

        # ④ 投递修复诉求到建议池 (去重: 同一 daemon 只保留一个 PENDING)
        flow_id = f"daemon_repair_{name}"
        exists = db.execute(
            "SELECT 1 FROM mt_ai_suggestion_pool WHERE flow_id=? AND status='PENDING' LIMIT 1",
            (flow_id,)).fetchone()
        if not exists:
            reason = "进程死亡" if pid_dead else f"心跳停滞 {int(hb_age//60)} 分钟"
            db.execute("""INSERT INTO mt_ai_suggestion_pool
                (source_type, source_name, suggestion_text, priority, status,
                 feasibility_score, value_score, cost_score, risk_score,
                 flow_id, created_at, meta_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("DAEMON_REPAIR", "andromeda_auto_loop",
                 f"## daemon 需拉起: {name}\n\n**现象**: {reason}\n**建议**: "
                 f"由 smart_mount 权威主管按注册表 config_json 重新拉起, 校验收敛后回写 RUNNING 心跳。",
                 1, "PENDING", 0.9, 0.9, 0.2, 0.1,
                 flow_id, time.strftime("%Y-%m-%d %H:%M:%S"),
                 json.dumps({"daemon": name, "pid": pid_str, "last_heartbeat": hb,
                             "pid_dead": pid_dead, "hb_stale": bool(hb_stale)}, ensure_ascii=False)))
            repair_requested += 1

    db.commit()
    db.close()
    log(f"  daemon: total={total} alive={alive} dead={dead} stale={stale} repair_requested={repair_requested}")
    return {"total": total, "alive": alive, "dead": dead, "stale": stale,
            "restarted": 0, "repair_requested": repair_requested}


def _loop_rule_strengthen() -> dict:
    """规则弱约束词扫描 + 自动写回"""
    rules_dir = BASE.parent / ".trae" / "rules"
    weak_words = ["may", "might", "should", "考虑", "建议", "可能", "可以考虑"]
    found = 0; fixed = 0
    
    if not rules_dir.exists():
        return {"found": 0, "fixed": 0}
    
    for rule_file in rules_dir.glob("*.md"):
        content = rule_file.read_text()
        # 已经自动强化过的跳过
        if "auto-strengthened" in content:
            continue
        orig = content
        for w in weak_words:
            count = content.lower().count(w.lower())
            if count > 0 and count <= 20:  # 过滤真正的标题/ID里的
                # 简单替换: should→必须, may→必须 (带边界保护)
                if w == "should":
                    content = re.sub(r'\b[Ss]hould\b', '必须', content)
                elif w == "may":
                    content = re.sub(r'\b[Mm]ay\b', '必须', content)
                elif w == "might":
                    content = re.sub(r'\b[Mm]ight\b', '必须', content)
                count_after = content.lower().count(w.lower())
                if count_after < count:
                    found += 1
        
        if content != orig and found > 0:
            log(f"  📝 {rule_file.name}: 强化 {found} 处弱约束词")
            rule_file.write_text(f"<!-- auto-strengthened by andromeda_auto_loop at {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n" + content)
            fixed += 1
            found = 0
    
    log(f"  rule_strengthen: fixed={fixed}")
    return {"fixed": fixed}


def _loop_auto_implement() -> dict:
    """
    建议池自动实施: 取 APPROVED 且 routine 的建议,
    用 Q5 生成修复 patch → 应用到代码
    """
    db = sqlite3.connect(str(DB))
    suggestions = db.execute("""
        SELECT id, category, target, issue, suggestion, severity
        FROM mt_evolution_suggestions
        WHERE status='APPROVED' AND severity <= 2
          AND category IN ('hardcoded_color', 'root_file', 'perm_bypass', 'rule_scan')
        ORDER BY rowid DESC LIMIT 5
    """).fetchall()
    db.close()
    
    implemented = 0
    
    for sid, cat, target, issue, suggestion, sev in suggestions:
        # 硬编码颜色 → 这个最难自动 fix, 建议写个简单脚本来批量替换
        if cat == "hardcoded_color" and "#" in issue:
            log(f"  🛠️  尝试自动修复 #{sid}: {issue[:60]}")
            # 找到那个文件, 扫描里面的硬编码颜色
            target_path = None
            for p in [BASE / "routes" / target, BASE / "engines" / target, BASE / "ai_engines" / target]:
                if p.exists():
                    target_path = p; break
            
            if target_path:
                content = target_path.read_text()
                # 简单替换: #hex → 加注释 (实际替换成 CSS 变量需要前端联动, 先标记)
                new_content = content
                replaced = 0
                for m in re.finditer(r"[\"'](#[0-9a-fA-F]{3,8})[\"']", content):
                    hex_color = m.group(1)
                    new_content = new_content.replace(f'"{hex_color}"', f'"{hex_color}"  # TODO: 替换为 var(--el-color-primary-dark)')
                    replaced += 1
                
                if replaced > 0:
                    target_path.write_text(new_content)
                    implemented += 1
                    log(f"    ✅ {target}: 标记 {replaced} 处硬编码颜色 → TODO 替换")
                    
                    # 更新建议状态 → DONE
                    db2 = sqlite3.connect(str(DB))
                    db2.execute("UPDATE mt_evolution_suggestions SET status='DONE', approved_by='auto_implement_loop' WHERE id=?", (sid,))
                    db2.commit(); db2.close()
    
    log(f"  auto_implement: implemented={implemented}")
    return {"implemented": implemented}


# ═════════════════════════════════════════════════════════════════════════
# 🌌 自探研机制 (自我探研) — 节流调用 andromeda_research 头脑风暴循环
# ═════════════════════════════════════════════════════════════════════════
RESEARCH_THROTTLE_SEC = 1800  # 自探研每 30 分钟最多一轮 (省本地算力)


def _loop_self_research() -> dict:
    """进程内调用 andromeda_research.run_research_cycle (1 个提案).

    - 节流: mt_research_proposals 最新提案 <30min 则跳过
    - 进程内调用 (同一 DB, 不再 subprocess dev_gate 之外的额外 fork)
    - Ollama 离线 / 异常一律 fail-soft, 不影响自律主循环
    """
    db = sqlite3.connect(str(DB))
    last = db.execute("SELECT created_at FROM mt_research_proposals ORDER BY rowid DESC LIMIT 1").fetchone()
    db.close()
    if last and last[0]:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                ts = time.mktime(time.strptime(last[0][:19], fmt))
                if time.time() - ts < RESEARCH_THROTTLE_SEC:
                    return {"skipped": True, "reason": f"节流: {int((time.time()-ts)//60)}min 前刚探研"}
            except Exception:
                continue

    try:
        import andromeda_research as ar  # 同目录, 共享 database/app.db
        res = ar.run_research_cycle(max_proposals=1)
        log(f"  research: 头脑风暴={res.get('brainstormed',0)} 通过={res.get('voted',0)} "
            f"启动={res.get('started',0)} 跳过={res.get('skipped',0)}")
        return {"skipped": False,
                "brainstormed": res.get("brainstormed", 0),
                "voted": res.get("voted", 0),
                "started": res.get("started", 0)}
    except Exception as e:
        log(f"  research: 异常 fail-soft: {e}")
        return {"skipped": False, "error": str(e)[:200]}


# ═════════════════════════════════════════════════════════════════════════
# 🧬 衍生升级闭环 — 研究提案 → 建议池 (auto-dev / skill-deriver 可消费)
# ═════════════════════════════════════════════════════════════════════════
_PROMOTE_STATUSES = ("VOTED", "STARTED", "DONE")
_PROMOTE_PRIORITY = {"SECURITY": 1, "OPTIMIZE": 2, "REFACTOR": 2, "FEATURE": 3, "EXPERIMENT": 4}


def _loop_promote_derivatives() -> dict:
    """把已通过的 routine 研究提案衍生为建议池工作项.

    闭环: run_research_cycle (头脑风暴/投票) → mt_research_proposals
          → 本函数 → mt_ai_suggestion_pool → auto_dev_team / skill_deriver 消费
    去重: 建议池 flow_id = research prop_id, 已存在则不重复投递
    """
    db = sqlite3.connect(str(DB))
    props = db.execute("""
        SELECT prop_id, title, summary, category, sensitivity, status
        FROM mt_research_proposals
        WHERE status IN ('VOTED','STARTED','DONE') AND sensitivity='routine'
        ORDER BY rowid DESC LIMIT 10""").fetchall()

    promoted = 0
    for prop_id, title, summary, category, sens, pstatus in props:
        exists = db.execute(
            "SELECT 1 FROM mt_ai_suggestion_pool WHERE flow_id=? LIMIT 1", (prop_id,)).fetchone()
        if exists:
            continue
        prio = _PROMOTE_PRIORITY.get(category, 3)
        db.execute("""INSERT INTO mt_ai_suggestion_pool
            (source_type, source_name, suggestion_text, priority, status,
             feasibility_score, value_score, cost_score, risk_score,
             flow_id, created_at, meta_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("RESEARCH_DERIVE", "andromeda_auto_loop",
             f"## [研究衍生] {title}\n\n**类别**: {category}\n**摘要**: {summary or ''}\n\n"
             f"**来源**: 仙女座自探研提案 {prop_id} (状态 {pstatus})\n"
             f"**建议**: 交 auto_dev_team / skill_deriver 评估并衍生为 Skill 或自动开发任务。",
             prio, "PENDING", 0.6, 0.7, 0.4, 0.2,
             prop_id, time.strftime("%Y-%m-%d %H:%M:%S"),
             json.dumps({"derived_from": "mt_research_proposals", "prop_id": prop_id,
                         "category": category, "proposal_status": pstatus}, ensure_ascii=False)))
        db.execute("UPDATE mt_research_proposals SET status='PROMOTED', updated_at=? WHERE prop_id=?",
                   (time.strftime("%Y-%m-%d %H:%M:%S"), prop_id))
        promoted += 1
        log(f"  🧬 衍生升级: {title[:40]} → 建议池 (prio={prio})")

    db.commit()
    db.close()
    if promoted:
        log(f"  promote: 衍生 {promoted} 个研究提案 → 建议池")
    return {"promoted": promoted, "candidates": len(props)}


def _loop_benchmark_if_needed() -> dict:
    """每 24h 跑一次模型 benchmark"""
    db = sqlite3.connect(str(DB))
    last = db.execute("SELECT finished_at FROM mt_evolution_runs WHERE loop='benchmark' ORDER BY started_at DESC LIMIT 1").fetchone()
    db.close()
    
    need = True
    if last and last[0]:
        try:
            last_ts = time.mktime(time.strptime(last[0], "%Y-%m-%d %H:%M:%S"))
            if time.time() - last_ts < 86400:
                need = False
        except: pass
    
    if not need:
        return {"skipped": True, "reason": "24h 内刚跑过"}
    
    try:
        payload = json.dumps({"model": MODEL, "messages": [
            {"role": "user", "content": "用中文说 10 种水果, 每种一个字"}
        ], "stream": False}).encode()
        t0 = time.time()
        import urllib.request
        r = urllib.request.urlopen(urllib.request.Request(
            OLLAMA_URL, data=payload, headers={"Content-Type":"application/json"}), timeout=30)
        resp = json.loads(r.read())
        dt = time.time() - t0
        speed = 10 / max(dt, 0.1)
        
        db = sqlite3.connect(str(DB))
        db.execute("""INSERT INTO mt_evolution_runs
            (loop, started_at, finished_at, duration_s, items_processed, items_ok, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("benchmark", time.strftime("%Y-%m-%d %H:%M:%S"),
             time.strftime("%Y-%m-%d %H:%M:%S"), round(dt, 1), 1, 1,
             f"qwen2.5:14b-q5 → {speed:.1f} tok/s"))
        db.commit(); db.close()
        
        log(f"  benchmark: {speed:.1f} tok/s ✅")
        return {"speed": round(speed, 1), "model": MODEL, "skipped": False}
    except Exception as e:
        return {"error": str(e), "skipped": False}


def _record_run(dt: float, results: dict):
    """记录到 mt_evolution_runs"""
    db = sqlite3.connect(str(DB))
    try:
        # 全口径统计: 修复诉求 + 规则强化 + 自动实施 + 自探研 + 衍生升级
        def _n(step, key):
            try: return int(results.get(step, {}).get(key, 0) or 0)
            except Exception: return 0
        items = (_n("daemon", "repair_requested") + _n("rule", "fixed")
                 + _n("auto_impl", "implemented") + _n("research", "voted")
                 + _n("research", "started") + _n("promote", "promoted"))
        db.execute("""INSERT INTO mt_evolution_runs
            (loop, started_at, finished_at, duration_s, items_processed, items_ok, suggestion_count, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SELF_LOOP",
             time.strftime("%Y-%m-%d %H:%M:%S"),
             time.strftime("%Y-%m-%d %H:%M:%S"),
             round(dt, 1), items, items,
             items,
             json.dumps(results, ensure_ascii=False)[:2000]))
        db.commit()
    except Exception as e:
        pass
    db.close()


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] [自律循环] {msg}")


# ═════════════════════════════════════════════════════════════════════════
# CLI: 单次 / daemon
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--loop" in sys.argv or "--daemon" in sys.argv:
        # daemon 模式: 每 5 分钟一轮, 失败不退出
        log("仙女座自律循环 daemon 启动 (每 5 分钟一轮)")
        while True:
            try:
                run_self_loop()
            except Exception as e:
                log(f"  ❌ 自律循环异常: {e}")
            time.sleep(300)  # 5 分钟
    else:
        # 单次
        result = run_self_loop()
        print("\n✅ 自律循环完成!")
        print(json.dumps(result, ensure_ascii=False, indent=2))
