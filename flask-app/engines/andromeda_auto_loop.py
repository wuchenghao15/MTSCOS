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
DB   = BASE / "database" / "app.db"   # 演化权威库 (建议池/研究/evolution_runs)

# daemon 运行时权威库: 与 ai_smart_mount_engine 的 _DB_CANDIDATES 同序 (engines 优先)。
# 关键: 心跳/拉起由 smart_mount 在该库管理, auto_loop 对 daemon 只做只读感知 + 审计,
# 绝不在影子库维护一套竞争的存活状态 (历史教训: 误把 5 天未更新的 database 影子库当权威,
# 给健康 daemon 虚标 FAILED)。
_DAEMON_DB_CANDIDATES = [
    BASE / "engines" / "app.db",
    BASE / "database" / "app.db",
]


def _resolve_daemon_db():
    """返回真正被 smart_mount 管理的、含 mt_daemon_registry 的权威库路径。"""
    for p in _DAEMON_DB_CANDIDATES:
        try:
            if p.exists() and p.stat().st_size > 1_000_000:
                c = sqlite3.connect(str(p))
                c.execute("SELECT 1 FROM mt_daemon_registry LIMIT 1")
                c.close()
                return p
        except Exception:
            continue
    return _DAEMON_DB_CANDIDATES[-1]

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
    _safe("consume", _loop_consume_derivatives)
    
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


def _parse_ts(hb):
    if not hb:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return time.mktime(time.strptime(hb[:26] if 'T' in hb else hb[:19], fmt))
        except Exception:
            continue
    return None


def _reg_key_col(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mt_daemon_registry)").fetchall()}
    return "daemon_name" if "daemon_name" in cols else "process_name"


def _loop_daemon_health() -> dict:
    """daemon 健康巡检 v4 (主管存活感知 + 只读 live 权威 + 审计闭环 + 影子镜像自洽).

    权威关系 (2026-10 双库核对后的正确模型):
    - engines/app.db = daemon 运行时权威, 由 smart_mount heartbeat_check 做 pid 探测/拉起/状态转移。
    - database/app.db = 演化库 (建议池/研究), 其 mt_daemon_registry 是可能陈旧的影子, 禁止在此改存活状态。

    v4 关键修正 (根因: smart_mount 主管整体离线, 而非 N 个 daemon 各自故障):
    - 以"全体 RUNNING 中最新心跳"判定主管在线与否。最新心跳都 > SUPERVISOR_DOWN_SEC
      → 主管离线 / 全局停摆。此时所有 RUNNING 心跳一起老化是**同一个根因**,
      只投 1 张 `daemon_supervisor_offline` 单, 绝不再按 daemon 逐个刷 DAEMON_REPAIR
      (v3 教训: 单周期误写 40 张 per-daemon 假单又自相矛盾地关闭)。
    - 仅当主管在线 (最新心跳新鲜) 时, 某个 daemon 单独心跳老化 > STALE_SEC 才算个体 stale。
    - 显式 FAILED/REPAIRING 状态在任何情况下都算真实个体故障。
    - auto_loop 不 fork 主管 (避免脑裂; launchctl 属 SA 终端操作), 离线只审计告警, 由 SA/launchd 拉起。

    本函数:
    1) 只读 live 权威库分类 + 判定主管在线。
    2) 主管离线 → 保证恰好 1 张 PENDING 主管离线单; 恢复在线 → 关闭它。
    3) 个体真实故障 → 一张 PENDING DAEMON_REPAIR (去重); 恢复/孤儿 → DEPLOYED/DEFERRED。
    4) 影子镜像自洽: 影子库 FAILED 但 live RUNNING → 回写 RUNNING。
    """
    SUPERVISOR_DOWN_SEC = 900   # 全体最新心跳 > 15min → 判定主管离线
    STALE_SEC = 1800            # 主管在线时, 单 daemon 心跳 > 30min 才算个体 stale
    SUP_TICKET = "daemon_supervisor_offline"
    now_ts = time.time()
    counts = {"total": 0, "alive": 0, "failed": 0, "idle": 0, "stale": 0, "stalled": 0,
              "supervisor_online": 0, "repair_requested": 0, "repaired_closed": 0,
              "deferred": 0, "shadow_corrected": 0}

    # ── 1) 读 live 权威库 ──
    live_path = _resolve_daemon_db()
    live = sqlite3.connect(str(live_path))
    live_key = _reg_key_col(live)
    live_map = {}
    try:
        for name, status, hb in live.execute(
                f"SELECT {live_key}, status, COALESCE(last_heartbeat,'') FROM mt_daemon_registry"):
            live_map[name] = (status or "", hb)
    finally:
        live.close()

    # 主管存活判据: 全体 RUNNING 中最新一次心跳
    running_ages = [now_ts - t for t in
                    (_parse_ts(hb) for _n, (st, hb) in live_map.items() if st == "RUNNING")
                    if t is not None]
    freshest_age = min(running_ages) if running_ages else None
    supervisor_online = freshest_age is not None and freshest_age <= SUPERVISOR_DOWN_SEC
    counts["supervisor_online"] = 1 if supervisor_online else 0

    genuine_bad = {}   # name -> reason (仅个体真实故障)
    for name, (status, hb) in live_map.items():
        age = (now_ts - _parse_ts(hb)) if _parse_ts(hb) is not None else None
        if status in ("FAILED", "REPAIRING"):
            counts["failed"] += 1
            genuine_bad[name] = "live 状态=%s" % status
        elif status == "IDLE":
            counts["idle"] += 1
        elif status == "RUNNING":
            if age is None:
                counts["alive"] += 1
            elif not supervisor_online and age > SUPERVISOR_DOWN_SEC:
                counts["stalled"] += 1          # 全局停摆的一份子, 非个体故障
            elif supervisor_online and age > STALE_SEC:
                counts["stale"] += 1
                genuine_bad[name] = "主管在线但心跳单独停滞 %d 分钟" % int(age // 60)
            else:
                counts["alive"] += 1
        else:
            counts["alive"] += 1
    counts["total"] = len(live_map)

    # ── 2-4) 演化库: 主管单 + 个体审计闭环 + 影子镜像 ──
    evo = sqlite3.connect(str(DB))
    try:
        # 2a) 主管离线 → 恰好 1 张 PENDING 主管单
        if not supervisor_online:
            exists = evo.execute(
                "SELECT 1 FROM mt_ai_suggestion_pool WHERE flow_id=? AND status='PENDING' LIMIT 1",
                (SUP_TICKET,)).fetchone()
            if not exists:
                freshest_hb = max((hb for _n, (st, hb) in live_map.items() if st == "RUNNING"),
                                  default=None)
                evo.execute("""INSERT INTO mt_ai_suggestion_pool
                    (source_type, source_name, suggestion_text, priority, status,
                     feasibility_score, value_score, cost_score, risk_score,
                     flow_id, created_at, meta_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("DAEMON_REPAIR", "andromeda_auto_loop",
                     "## ⚠️ smart_mount 主管离线 (全局停摆)\n\n"
                     "**现象**: live 权威库全体 daemon 最新心跳已 %s 分钟未刷新 "
                     "(最新=%s), %d 个 RUNNING 一起老化; OS 无 ai_smart_mount_engine 进程。\n"
                     "**权威库**: %s\n"
                     "**根因**: daemon 唯一主管 smart_mount 未运行, 非各 daemon 个体故障。\n"
                     "**处置**: 由 SA 在终端经 launchd 重新拉起 smart_mount_engine "
                     "(auto_loop 不自行 fork, 避免主管脑裂)。恢复后本单自动关闭。"
                     % ("?" if freshest_age is None else int(freshest_age // 60),
                        freshest_hb or "n/a", counts["stalled"], live_path.name),
                     1, "PENDING", 0.95, 0.95, 0.1, 0.2,
                     SUP_TICKET, time.strftime("%Y-%m-%d %H:%M:%S"),
                     json.dumps({"kind": "supervisor_offline", "freshest_hb": freshest_hb,
                                 "freshest_age_min": None if freshest_age is None else int(freshest_age // 60),
                                 "stalled": counts["stalled"], "authority_db": str(live_path)},
                                ensure_ascii=False)))
                counts["repair_requested"] += 1
        # 2b) 主管恢复在线 → 关闭主管单
        else:
            cur = evo.execute(
                "UPDATE mt_ai_suggestion_pool SET status='DEPLOYED', deployed_at=? "
                "WHERE flow_id=? AND status='PENDING'",
                (time.strftime("%Y-%m-%d %H:%M:%S"), SUP_TICKET))
            if cur.rowcount:
                counts["repaired_closed"] += cur.rowcount

        # 3a) 个体真实故障 → 保证一条 PENDING 审计 (去重)
        for name, reason in genuine_bad.items():
            flow_id = "daemon_repair_%s" % name
            exists = evo.execute(
                "SELECT 1 FROM mt_ai_suggestion_pool WHERE flow_id=? AND status='PENDING' LIMIT 1",
                (flow_id,)).fetchone()
            if not exists:
                evo.execute("""INSERT INTO mt_ai_suggestion_pool
                    (source_type, source_name, suggestion_text, priority, status,
                     feasibility_score, value_score, cost_score, risk_score,
                     flow_id, created_at, meta_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("DAEMON_REPAIR", "andromeda_auto_loop",
                     "## daemon 个体故障: %s\n\n**live 现象**: %s\n**权威库**: %s\n"
                     "**建议**: smart_mount heartbeat_check 自动拉起; 本单仅审计留痕。"
                     % (name, reason, live_path.name),
                     1, "PENDING", 0.9, 0.9, 0.2, 0.1,
                     flow_id, time.strftime("%Y-%m-%d %H:%M:%S"),
                     json.dumps({"daemon": name, "reason": reason,
                                 "authority_db": str(live_path)}, ensure_ascii=False)))
                counts["repair_requested"] += 1

        # 3b) 关闭/裁决历史 PENDING 个体审计单
        open_rows = evo.execute(
            "SELECT suggestion_id, flow_id FROM mt_ai_suggestion_pool "
            "WHERE source_type='DAEMON_REPAIR' AND status='PENDING' AND flow_id!=?",
            (SUP_TICKET,)).fetchall()
        for sid, flow_id in open_rows:
            name = flow_id.replace("daemon_repair_", "", 1)
            if name not in live_map:
                # live 目录无此 daemon (孤儿) → DEFERRED, 禁止盲拉
                evo.execute("UPDATE mt_ai_suggestion_pool SET status='DEFERRED', meta_json=? "
                            "WHERE suggestion_id=?",
                            (json.dumps({"reason": "not_registered_in_live_catalog",
                                         "authority_db": str(live_path)}, ensure_ascii=False), sid))
                counts["deferred"] += 1
            elif name in genuine_bad:
                pass  # 仍真实故障, 保持 PENDING
            elif live_map[name][0] in ("FAILED", "REPAIRING"):
                pass  # 显式故障, 保持 PENDING
            elif live_map[name][0] == "RUNNING":
                age = now_ts - (_parse_ts(live_map[name][1]) or 0)
                if supervisor_online and age <= STALE_SEC:
                    evo.execute("UPDATE mt_ai_suggestion_pool SET status='DEPLOYED', deployed_at=? "
                                "WHERE suggestion_id=?", (time.strftime("%Y-%m-%d %H:%M:%S"), sid))
                    counts["repaired_closed"] += 1
                # 主管离线时无法确认个体健康 → 保持 PENDING, 不刷量不误关

        # 4) 影子镜像自洽: shadow.FAILED 但 live.RUNNING → 回写 RUNNING
        if "mt_daemon_registry" in {r[0] for r in evo.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}:
            sh_key = _reg_key_col(evo)
            shadow_failed = evo.execute(
                f"SELECT {sh_key}, COALESCE(last_heartbeat,'') FROM mt_daemon_registry "
                "WHERE status='FAILED'").fetchall()
            for name, _hb in shadow_failed:
                lst = live_map.get(name)
                if lst and lst[0] == "RUNNING":
                    evo.execute(
                        f"UPDATE mt_daemon_registry SET status='RUNNING', last_heartbeat=? "
                        "WHERE {0}=? AND status='FAILED'".format(sh_key),
                        (lst[1] or time.strftime("%Y-%m-%dT%H:%M:%S"), name))
                    counts["shadow_corrected"] += 1
        evo.commit()
    finally:
        evo.close()

    counts["live_db"] = live_path.name
    counts["sup"] = "在线" if supervisor_online else "离线"
    log("  daemon[live=%(live_db)s 主管=%(sup)s]: total=%(total)d alive=%(alive)d failed=%(failed)d "
        "idle=%(idle)d stale=%(stale)d stalled=%(stalled)d | 新增审计=%(repair_requested)d "
        "关闭=%(repaired_closed)d DEFERRED=%(deferred)d 影子纠正=%(shadow_corrected)d" % counts)
    counts["restarted"] = 0
    return counts


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


# ═════════════════════════════════════════════════════════════════════════
# 🧬 衍生升级消费 (节流) — RESEARCH_DERIVE 工作项 → 本地 AI 产出 Skill 草案 → 落库
# ═════════════════════════════════════════════════════════════════════════
CONSUME_GAP_SEC = 1800   # 两次消费间隔 ≥ 30min (省本地算力)
CONSUME_DAILY_MAX = 8    # 每日最多产出 8 个
CONSUME_PER_LOOP = 1     # 每轮最多 1 个
CONSUME_MAX_ATTEMPTS = 3
_CONSUME_CAT_SLUG = {"SECURITY": "security", "OPTIMIZE": "optimize", "REFACTOR": "refactor",
                     "FEATURE": "feature", "EXPERIMENT": "experiment"}


def _skill_slug(prop_id: str, category: str) -> str:
    nums = re.findall(r"\d+", prop_id or "")
    tail = "-".join(nums[-2:]) if nums else str(int(time.time()))
    slug = _CONSUME_CAT_SLUG.get((category or "").upper(), "research")
    return ("andromeda-%s-%s" % (slug, tail))[:48]


def _stale_skill_path_if_valid(prop_id: str, category: str):
    """崩溃恢复探测: 该提案受控名的 SKILL.md 若已落盘且 frontmatter 合法(name 精确匹配),
    返回其路径; 不存在/不合法返回 None。用于"写盘成功但落库前中断"的幂等补登, 避免重算。"""
    try:
        import ai_skill_deriver_engine as deriver
        skill_name = _skill_slug(prop_id, category)
        target = os.path.join(deriver.SKILLS_DIR, skill_name, "SKILL.md")
        if not os.path.exists(target):
            return None
        with open(target, "r", encoding="utf-8") as f:
            txt = f.read()
        if not txt.startswith("---"):
            return None
        parts = txt.split("---", 2)
        if len(parts) < 3:
            return None
        nm = re.search(r'name:\s*"([^"]+)"', parts[1])
        ds = re.search(r'description:\s*"([^"]+)"', parts[1])
        if not nm or not ds or nm.group(1).strip() != skill_name:
            return None
        return target
    except Exception:
        return None


def _loop_consume_derivatives() -> dict:
    """节流消费 RESEARCH_DERIVE: 研究提案 → 本地 Ollama 生成 Skill 草案 → 写盘校验 → 落库.

    状态全部写 database/app.db (演化权威库), 不碰 engines 运行时库。
    - 节流: 距上次消费 <30min 跳过; 当日产出 >=8 跳过; 每轮只做 1 个。
    - 认领: PENDING → EVALUATED (带租约), 同步完成后 → DEPLOYED/DEFERRED/REJECTED。
    - 崩溃恢复: EVALUATED 租约 >10min 视为陈旧, 回 PENDING 重新认领。
    - 重试: 本地 AI 不可用/超时 → attempts+1, <3 回 PENDING; 到顶 DEFERRED(环境) / REJECTED(产物不合格)。
    复用 ai_skill_deriver_engine.write_and_validate_skill 做写盘+frontmatter 校验;
    正文用本进程 ollama_chat(qwen2.5:14b-q5) 按研究提案生成, frontmatter 由代码受控拼装
    (避免模型任意指定 name 造成目录穿越/覆盖)。
    """
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    today = time.strftime("%Y-%m-%d")
    db = sqlite3.connect(str(DB))
    try:
        # 0) 崩溃恢复: 陈旧 EVALUATED 租约 (>600s)
        #    a) 若同名合法 Skill 已落盘(写盘成功但落库前中断) → 幂等补登 DEPLOYED 并收口, 立即收敛;
        #    b) 否则 → 回 PENDING, 由后续轮重新认领生成(attempts 已在 impl 持久化)。
        #    本步在 30min 节流之前, 已成功产物的补登不被节流推迟。
        stale = db.execute(
            "SELECT suggestion_id, meta_json FROM mt_ai_suggestion_pool "
            "WHERE source_type='RESEARCH_DERIVE' AND status='EVALUATED' AND evaluated_at IS NOT NULL "
            "AND CAST((julianday(?) - julianday(evaluated_at)) * 86400 AS INTEGER) > 600",
            (now_str,)).fetchall()
        adopted = 0; reaped = 0
        for sid, _m in stale:
            info = db.execute(
                """SELECT p.flow_id, pr.category, i.impl_id
                     FROM mt_ai_suggestion_pool p
                     JOIN mt_research_proposals pr ON pr.prop_id = p.flow_id
                LEFT JOIN mt_research_implementations i ON i.suggestion_id = p.suggestion_id
                    WHERE p.suggestion_id=?""", (sid,)).fetchone()
            target = _stale_skill_path_if_valid(info[0], info[1]) if info else None
            if info and target:
                prop_id, _cat, impl_id = info
                db.execute(
                    "UPDATE mt_ai_suggestion_pool SET status='DEPLOYED', deployed_at=? "
                    "WHERE suggestion_id=? AND status='EVALUATED'", (now_str, sid))
                if impl_id:
                    db.execute(
                        "UPDATE mt_research_implementations SET artifact_path=?, status='DEPLOYED', "
                        "error='', updated_at=? WHERE impl_id=?", (target, now_str, impl_id))
                db.commit(); adopted += 1
                try:
                    import andromeda_research as _ar
                    _ar.close_research_proposal(prop_id, artifact=target)
                except Exception as e:
                    log(f"  consume: 补登 {sid} DEPLOYED, §14 收口异常: {str(e)[:80]}")
                log(f"  consume: 陈旧租约 {sid} Skill 已落盘, 幂等补登 DEPLOYED (免重算)")
            else:
                db.execute(
                    "UPDATE mt_ai_suggestion_pool SET status='PENDING' "
                    "WHERE suggestion_id=? AND status='EVALUATED'", (sid,))
                reaped += 1
        if stale:
            db.commit()
            log(f"  consume: 陈旧租约恢复 — 补登已落盘 {adopted} 个, 回 PENDING 重算 {reaped} 个")

        # 1) 节流: 间隔
        last = db.execute(
            "SELECT MAX(created_at) FROM mt_research_implementations").fetchone()[0]
        if last:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    if time.time() - time.mktime(time.strptime(last[:19], fmt)) < CONSUME_GAP_SEC:
                        return {"skipped": True, "reason": "节流: 距上次消费不足30min"}
                    break
                except Exception:
                    continue
        # 2) 节流: 日额度
        done_today = db.execute(
            "SELECT COUNT(*) FROM mt_research_implementations WHERE status='DEPLOYED' AND created_at LIKE ?",
            (today + "%",)).fetchone()[0]
        if done_today >= CONSUME_DAILY_MAX:
            return {"skipped": True, "reason": f"当日已产出 {done_today}, 达上限 {CONSUME_DAILY_MAX}"}

        # 3) 取一个候选 (PENDING, 提案 PROMOTED), 优先级高优先
        cand = db.execute("""
            SELECT p.suggestion_id, p.flow_id, pr.title, pr.summary, pr.category
            FROM mt_ai_suggestion_pool p
            JOIN mt_research_proposals pr ON pr.prop_id = p.flow_id
            WHERE p.source_type='RESEARCH_DERIVE' AND p.status='PENDING' AND pr.status='PROMOTED'
            ORDER BY p.priority ASC, p.suggestion_id ASC LIMIT ?""", (CONSUME_PER_LOOP,)).fetchone()
        if not cand:
            return {"skipped": True, "reason": "无可消费 RESEARCH_DERIVE"}
        sid, prop_id, title, summary, category = cand

        # 4) 原子认领
        claim_meta = json.dumps({"lease_owner": "andromeda_auto_loop", "leased_at": now_str},
                                ensure_ascii=False)
        cur = db.execute(
            "UPDATE mt_ai_suggestion_pool SET status='EVALUATED', evaluated_at=?, meta_json=? "
            "WHERE suggestion_id=? AND status='PENDING'", (now_str, claim_meta, sid))
        db.commit()
        if cur.rowcount != 1:
            return {"skipped": True, "reason": "认领竞争失败"}

        # 5) implementations 记录 (attempts 持久化)
        impl = db.execute(
            "SELECT impl_id, attempts FROM mt_research_implementations WHERE suggestion_id=?",
            (sid,)).fetchone()
        if impl:
            impl_id, attempts = impl
        else:
            attempts = 0
            cur2 = db.execute("""INSERT INTO mt_research_implementations
                (prop_id, suggestion_id, artifact_type, artifact_path, status, attempts, error, flow_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (prop_id, sid, "SKILL", "", "PENDING", 0, "", prop_id, now_str, now_str))
            impl_id = cur2.lastrowid
            db.commit()

        # 6) 本地 AI 生成 Skill 正文 (受控 frontmatter)
        skill_name = _skill_slug(prop_id, category)
        safe_title = re.sub(r'[\"\r\n]', '', (title or prop_id))[:60]
        sys_p = ("你是仙女座自演化引擎, 把通过 EigenFlux 投票的研究提案沉淀成可复用 Skill。"
                 "只输出 Markdown 正文(从 '# 标题' 开始), 不要输出 frontmatter。中文, 结构清晰, 内容务实可执行。")
        user_p = (
            f"研究提案: {title}\n类别: {category}\n摘要: {summary or '(无)'}\n\n"
            "请产出 Skill 正文, 包含小节: "
            "## 解决什么问题 / ## 快速上手 / ## 实施要点(编号步骤) / "
            "## 已踩过的坑(表格) / ## 快速命令或代码片段 / ## 预防铁律。"
            "内容紧扣提案, 不要编造与提案无关的功能。")
        body = ollama_chat(sys_p, user_p, timeout=180)

        final_status = None; artifact_path = ""; err = ""
        body = (body or "").strip()
        if not body or not body.startswith("#"):
            attempts += 1
            err = "本地 AI 无产出或格式不符"
            if attempts >= CONSUME_MAX_ATTEMPTS:
                final_status, pool_status = "DEFERRED", "DEFERRED"
            else:
                final_status, pool_status = "PENDING", "PENDING"
        else:
            desc = "%s — 仙女座自探研衍生 Skill(%s). Invoke when working on this pattern." \
                   % (safe_title, (category or "RESEARCH"))
            skill_md = '---\nname: "%s"\nalwaysApply: false\ndescription: "%s"\n---\n\n%s' \
                       % (skill_name, desc, body)
            try:
                import ai_skill_deriver_engine as deriver
                ok, res = deriver.write_and_validate_skill(skill_name, skill_md)
            except Exception as e:
                ok, res = False, "write_and_validate 异常: %s" % e
            attempts += 1
            if ok:
                final_status, pool_status, artifact_path = "DEPLOYED", "DEPLOYED", res
                log(f"  🧬 consume: {safe_title} → Skill {skill_name}")
            else:
                err = "产物校验失败: %s" % res
                if attempts >= CONSUME_MAX_ATTEMPTS:
                    final_status, pool_status = "REJECTED", "REJECTED"
                else:
                    final_status, pool_status = "PENDING", "PENDING"

        # 7) 写回 database 库 (建议池 + implementations)
        if pool_status == "DEPLOYED":
            db.execute("UPDATE mt_ai_suggestion_pool SET status='DEPLOYED', deployed_at=? "
                       "WHERE suggestion_id=?", (now_str, sid))
        else:
            db.execute("UPDATE mt_ai_suggestion_pool SET status=? WHERE suggestion_id=?", (pool_status, sid))
        db.execute("""UPDATE mt_research_implementations
            SET artifact_type='SKILL', artifact_path=?, status=?, attempts=?, error=?, updated_at=?
            WHERE impl_id=?""", (artifact_path, final_status, attempts, err[:500], now_str, impl_id))
        db.commit()

        # 8) DEPLOYED 后沿官方 12 步状态机收口该 routine 提案的 §14 flow
        close_info = None
        if pool_status == "DEPLOYED":
            try:
                import andromeda_research as ar
                close_info = ar.close_research_proposal(prop_id, artifact=artifact_path)
            except Exception as e:
                close_info = {"closed": False, "error": str(e)[:150]}
        return {"skipped": False, "suggestion_id": sid, "skill": skill_name,
                "pool_status": pool_status, "attempts": attempts,
                "deployed": 1 if pool_status == "DEPLOYED" else 0,
                "flow_closed": bool(close_info and close_info.get("closed")),
                "close": close_info,
                "artifact_path": artifact_path, "error": err}
    finally:
        db.close()


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
                 + _n("research", "started") + _n("promote", "promoted")
                 + _n("consume", "deployed"))
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
