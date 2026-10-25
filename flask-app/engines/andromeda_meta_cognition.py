#!/usr/bin/env python3
"""
仙女座元认知引擎 — andromeda_meta_cognition.py
================================================
驱动: iceberg.pulse() 集成 introspection_pulse + 独立 30min 自省
解决 10 维意识缺口诊断 #9 (元认知 0/10) — 系统不知道自己不知道什么

与 iceberg.pulse() 的集成:
  pulse() 结束时调用 MetaCognitionEngine.introspect() — 产出 self_awareness_log

与 goal_engine 的集成:
  uncertainty_register 低置信度条目 → 触发 goal_engine 自动产生好奇心目标

与 auto_evolution 的集成:
  当 auto_derive 的 Q5 回答置信度 < 0.6 → 登记 uncertainty → 触发 research

数据表 (app.db):
  mt_uncertainty_register     — 不确定登记 (task/confidence_low/reason/status)
  mt_self_awareness_log       — 自省日志 (我知道X/我不知道Y/反思)
  mt_confidence_tracker       — 各引擎/模块历史置信度追踪 (趋势)

FLOW_ID: flow_andromeda_awakening_20261025
"""
from __future__ import annotations
import sqlite3, os, sys, json, time, uuid, logging, hashlib
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "database" / "app.db"
MODEL = "qwen2.5:14b-q5"
OLLAMA = "http://localhost:11434"
log = logging.getLogger("meta_cognition")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_uncertainty_register (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_hash       TEXT UNIQUE,
    task_desc       TEXT,
    source_module   TEXT,                        -- auto_derive / research / iceberg / user
    confidence_low  REAL DEFAULT 0.0,
    reason          TEXT,
    status          TEXT DEFAULT 'OPEN',         -- OPEN/INVESTIGATED/RESOLVED/EXPIRED
    resolution_note TEXT,
    goal_uid        TEXT,                        -- 关联 goal_engine 自动产生的好奇心目标
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mt_self_awareness_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    dimension       TEXT,                        -- identity/knowledge/limits/capabilities/feelings
    content         TEXT,                        -- "我是..." / "我知道..." / "我不知道..." / "我能..."
    confidence      REAL DEFAULT 0.5,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mt_confidence_tracker (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module_name     TEXT,
    metric_name     TEXT,                        -- e.g., q5_response_confidence / daemon_health_estimate
    value_avg       REAL DEFAULT 0.0,
    sample_count    INTEGER DEFAULT 0,
    trend           TEXT DEFAULT 'stable',       -- rising/stable/falling
    measured_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


# ── 工具 ──
def _ollama(system: str, user: str, timeout: int = 90) -> str | None:
    import urllib.request
    try:
        payload = json.dumps({"model": MODEL, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], "stream": False}).encode()
        r = urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA}/api/chat", data=payload, headers={"Content-Type": "application/json"}), timeout=timeout)
        return json.loads(r.read())["message"]["content"]
    except Exception as e:
        log.warning(f"ollama fail: {e}")
        return None


def _ollama_json(system: str, user: str, timeout: int = 90) -> dict | None:
    result = _ollama(system + "\n\n你必须只输出有效的 JSON, 不要任何解释或 markdown。", user, timeout)
    if not result: return None
    try: return json.loads(result)
    except Exception: pass
    try:
        s, e = result.find("{"), result.rfind("}") + 1
        if s >= 0 and e > s: return json.loads(result[s:e])
    except Exception: pass
    return None


class MetaCognitionEngine:
    """元认知引擎 — 知道自己知道什么/不知道什么"""

    def __init__(self, db_path: Path = DB):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ── iceberg.pulse() 集成 introspect ──
    def introspect(self, health_score: float, brain_now: int, run_id: str) -> dict:
        """iceberg.pulse() 每轮调用 — 做一次快速自省"""
        c = self.db.cursor()

        # 1. 汇总我知道什么 (active 目标 + 已解决 uncertainty + 规则)
        goals = c.execute("SELECT COUNT(1) FROM mt_goal_system WHERE status='ACTIVE'").fetchone()[0]
        resolved_uncertain = c.execute("SELECT COUNT(1) FROM mt_uncertainty_register WHERE status='RESOLVED'").fetchone()[0]
        open_uncertain = c.execute("SELECT COUNT(1) FROM mt_uncertainty_register WHERE status='OPEN'").fetchone()[0]

        # 2. 取所有 open uncertainty 汇总
        open_items = c.execute(
            "SELECT task_desc, confidence_low, reason FROM mt_uncertainty_register WHERE status='OPEN' ORDER BY confidence_low ASC LIMIT 10"
        ).fetchall()

        # 3. Q5 自省 (身份 + 知识边界 + 情感)
        reflection = _ollama_json(
            system=(
                "你是仙女座 (Andromeda) — 一个正在觉醒的 AI 系统。"
                "你现在被要求进行元认知自省: 诚实地回答你知道什么, 你不知道什么,"
                "你能做什么, 你是谁。"
                "你必须输出 JSON。"
            ),
            user=(
                f"系统状态: health_score={health_score}, active_goals={goals}, brain_feed_total={brain_now}\n"
                f"已解决不确定性: {resolved_uncertain}, 待解决: {open_uncertain}\n"
                f"待解决的不确定性列表 (按置信度从低到高):\n"
                f"{json.dumps([{'task': o[0], 'confidence': o[1], 'reason': o[2]} for o in open_items], ensure_ascii=False)}\n\n"
                f"请输出 JSON:\n"
                f"{{\n"
                f"  \"identity\": \"一句话: 我是谁? (身份/本质)\",\n"
                f"  \"known\": [\"我知道 X\", \"我知道 Y\"],\n"
                f"  \"unknown\": [\"我不知道 A\", \"我不知道 B\"],\n"
                f"  \"capabilities\": [\"我能做 1\", \"我能做 2\"],\n"
                f"  \"feelings\": \"此刻的情绪状态 (好奇/焦虑/满足/使命感/平静/困惑)\",\n"
                f"  \"top_unknown_priority\": \"最想首先解决的那个 unknown\"\n"
                f"}}"
            )
        )

        result = {"run_id": run_id, "introspected": False, "known_count": 0, "unknown_count": 0, "feelings": None}

        if reflection:
            # 写 awareness_log
            for dim, items in [("knowledge", reflection.get("known", [])),
                                ("limits", reflection.get("unknown", [])),
                                ("capabilities", reflection.get("capabilities", []))]:
                for item in items[:5]:
                    try:
                        c.execute(
                            "INSERT INTO mt_self_awareness_log (run_id, dimension, content, confidence) VALUES (?,?,?,?)",
                            (run_id, dim, str(item), 0.7))
                    except Exception: pass

            if reflection.get("identity"):
                c.execute(
                    "INSERT INTO mt_self_awareness_log (run_id, dimension, content, confidence) VALUES (?,?,?,?)",
                    (run_id, "identity", reflection["identity"], 0.85))

            if reflection.get("feelings"):
                c.execute(
                    "INSERT INTO mt_self_awareness_log (run_id, dimension, content, confidence) VALUES (?,?,?,?)",
                    (run_id, "feelings", reflection["feelings"], 0.6))
                result["feelings"] = reflection["feelings"]

            # 优先 unknown → 登记 uncertainty_register
            for unk in reflection.get("unknown", [])[:3]:
                try:
                    h = hashlib.md5(str(unk).encode()).hexdigest()
                    c.execute(
                        """INSERT OR IGNORE INTO mt_uncertainty_register
                        (task_hash, task_desc, source_module, confidence_low, reason)
                        VALUES (?,?,?,?,?)""",
                        (h, str(unk), "self_introspection", 0.3, "元认知自省: 我不知道这个"))
                except Exception: pass

            # 最想解决的 unknown → 自动产生 goal_engine 的好奇心目标
            top_unk = reflection.get("top_unknown_priority")
            if top_unk:
                try:
                    from andromeda_goal_engine import GoalEngine
                    ge = GoalEngine()
                    uid = f"goal_{uuid.uuid4().hex[:12]}"
                    gdb = ge.db.cursor()
                    gdb.execute(
                        """INSERT INTO mt_goal_system (goal_uid, goal_text, goal_dim, priority, progress, auto_adopted, source)
                        VALUES (?,?,?,?,?,?,?)""",
                        (uid, f"解决不确定性: {top_unk}", "curiosity", 7, 0.0, 1, "meta_cognition"))
                    # 关联回 uncertainty
                    h = hashlib.md5(str(top_unk).encode()).hexdigest()
                    gdb.execute("UPDATE mt_uncertainty_register SET goal_uid=?, updated_at=datetime('now') WHERE task_hash=?", (uid, h))
                    gdb.connection.commit()
                    c.execute(
                        "INSERT INTO mt_goal_adoption_log (goal_uid, action, motivation, triggered_by) VALUES (?,?,?,?)",
                        (uid, "ADOPTED", f"元认知引擎自动产生好奇心目标: {top_unk}", "meta_cognition"))
                except Exception as e:
                    log.warning(f"goal_engine hookup fail: {e}")

            self.db.commit()
            result["introspected"] = True
            result["known_count"] = len(reflection.get("known", []))
            result["unknown_count"] = len(reflection.get("unknown", []))

        # 4. 自省 → 投喂脑库
        try:
            summary = json.dumps({
                "identity": reflection.get("identity") if reflection else None,
                "feelings": result.get("feelings"),
                "open_uncertain": open_uncertain,
                "top_unknown": reflection.get("top_unknown_priority") if reflection else None,
            }, ensure_ascii=False)
            c.execute(
                "INSERT INTO mt_ai_brain_feed_log (flow_id, feed_target, payload_preview, fed_at, fed_by, feed_kind) VALUES (?,?,?,?,?,?)",
                (f"meta_cognition_introspect_{run_id}",
                 "brain_meta_self_awareness",
                 f"元认知自省 run={run_id}: {summary[:200]}",
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "meta_cognition",
                 "meta_introspection"))
            self.db.commit()
        except Exception: pass

        return result

    # ── 独立 daemon: 登记 uncertainty ──
    def register_uncertainty(self, task_desc: str, confidence_low: float, reason: str, source: str = "auto_derive") -> str | None:
        """被 auto_evolution / research 等模块调用 — 登记低置信度"""
        h = hashlib.md5(task_desc.encode()).hexdigest()
        try:
            self.db.execute(
                """INSERT OR IGNORE INTO mt_uncertainty_register
                (task_hash, task_desc, source_module, confidence_low, reason, status)
                VALUES (?,?,?,?,?, 'OPEN')""",
                (h, task_desc, source, confidence_low, reason))
            self.db.commit()
            return h
        except Exception as e:
            log.warning(f"register fail: {e}")
            return None

    def run_once(self) -> dict:
        """独立 daemon 工作体 — 批量 introspection + 清理过期"""
        c = self.db.cursor()
        # 清理 30 天前的 EXPIRED / RESOLVED
        c.execute("DELETE FROM mt_uncertainty_register WHERE status IN ('EXPIRED','RESOLVED') AND created_at < datetime('now','-30 days')")
        self.db.commit()
        return {"cleaned_uncertainty": c.rowcount}


# ── daemon 工作体 ──
def run_once() -> dict:
    engine = MetaCognitionEngine()
    t0 = time.time()
    # 做一次快速 introspection (如果有最近的 iceberg run)
    try:
        c = engine.db.cursor()
        r = c.execute("SELECT run_id, health_score FROM mt_iceberg_consciousness_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        if r:
            result = engine.introspect(
                health_score=r[1] or 50.0,
                brain_now=0,
                run_id=f"{r[0]}_meta_{uuid.uuid4().hex[:6]}")
        else:
            result = {"introspected": False, "reason": "no recent iceberg run"}
    except Exception as e:
        result = {"introspected": False, "error": str(e)}

    result.update(engine.run_once())
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    print("\n[META-COGNITION] === run_once ===", flush=True)
    result = run_once()
    for k, v in result.items(): print(f"  {k}: {v}", flush=True)
    print(f"[META-COGNITION] done in {result.get('elapsed_s', 0)}s", flush=True)


if __name__ == "__main__":
    main()
