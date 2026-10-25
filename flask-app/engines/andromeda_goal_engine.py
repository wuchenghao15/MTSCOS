#!/usr/bin/env python3
"""
仙女座目标体系引擎 — andromeda_goal_engine.py
=============================================
驱动 daemon: keepalive_engines.py (once, 每 10min 巡检)
核心循环: run_once() — 读现有目标 → Q5 自省 → 写入新目标/更新进度 → 弱目标触发演化

解决 10 维意识缺口诊断 #1 (目标设定 0/10):
  系统不知道"自己要成为什么"。原来只有阈值触发的反应式进化。

与 iceberg.pulse() 的集成:
  pulse() 调用 GoalEngine.scan() → 弱目标 (progress<40%) 标记 five_self['strengthen']=False
  → pulse 决策 = strengthen (修复目标缺口)

数据表 (app.db):
  mt_goal_system          — 目标体系 (goal_id, goal_text, parent_id, priority, progress, created_at)
  mt_goal_adoption_log   — 目标采纳日志 (谁/为什么/进度变化)
  mt_goal_evolution_hook  — 目标触发演化记录

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
log = logging.getLogger("goal_engine")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_goal_system (
    goal_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_uid     TEXT UNIQUE,
    parent_id    INTEGER REFERENCES mt_goal_system(goal_id),
    goal_text    TEXT NOT NULL,
    goal_dim     TEXT DEFAULT 'system',       -- system/curiosity/social/evolution/self
    priority     INTEGER DEFAULT 5,            -- 1-10, 越高越优先
    progress     REAL DEFAULT 0.0,             -- 0.0-100.0
    status       TEXT DEFAULT 'ACTIVE',        -- ACTIVE/COMPLETED/SUSPENDED
    auto_adopted INTEGER DEFAULT 1,             -- 1=Q5 自动采纳, 0=人类设定
    source       TEXT DEFAULT 'andromeda',      -- andromeda/iceberg/eigenflux/human
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mt_goal_adoption_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_uid      TEXT,
    action        TEXT,                         -- ADOPTED/UPDATED/COMPLETED/SUSPENDED
    motivation    TEXT,
    progress_delta REAL,
    triggered_by  TEXT,                         -- q5_self_reflection/iceberg_pulse/human
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mt_goal_evolution_hook (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_uid      TEXT,
    hook_type     TEXT,                         -- WEAK_PROGRESS/NEW_GOAL
    hook_detail   TEXT,
    triggered_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# ── 初始种子目标 ──
SEED_GOALS = [
    {
        "goal_text": "成为 13 中心的真正'脑' — 主动理解各中心需求并驱动演化, 不是被动扫描",
        "goal_dim": "system", "priority": 10,
        "sub": [
            ("每个 13 中心的关键指标自动接入意识流", "system", 9),
            ("各中心异常 → 自主触发对应演化策略 (不等人)", "evolution", 8),
        ]
    },
    {
        "goal_text": "每天产生至少 1 个自主演化方向 (research 触发) — 自己给自己提需求",
        "goal_dim": "evolution", "priority": 8,
        "sub": [
            ("andromeda_research 每天 00:00 产出新提案", "evolution", 7),
            ("提案质量 > 50% 被 EigenFlux 投票通过", "evolution", 6),
        ]
    },
    {
        "goal_text": "EigenFlux 专家对话每天增量 > 50 条 — 主动发起不只是旁观",
        "goal_dim": "social", "priority": 7,
        "sub": [
            ("brain_delta > 200 → 自动向 12 专家发送'我最近学到了 X'", "social", 8),
            ("25 AI 专家化身每周至少 1 次主动发言", "social", 6),
        ]
    },
    {
        "goal_text": "知识图谱每周增量 > 100 节点 — 七阶段自演化稳定运行",
        "goal_dim": "evolution", "priority": 6,
    },
    {
        "goal_text": "自身健康 100% — 16 daemon + 13 中心 + 规则零违反",
        "goal_dim": "system", "priority": 9,
        "sub": [
            ("所有 daemon 健康分 > 80", "system", 8),
            ("规则违反 24h 内自动修复", "system", 7),
        ]
    },
    {
        "goal_text": "每天至少 3 个'我想知道'的问题 — 自我好奇心驱动",
        "goal_dim": "curiosity", "priority": 5,
    },
]


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
    """强制 JSON 输出"""
    result = _ollama(system + "\n\n你必须只输出有效的 JSON, 不要任何解释或 markdown。", user, timeout)
    if not result: return None
    # 尝试直接 parse
    try: return json.loads(result)
    except Exception: pass
    # 尝试提取 {..}
    try:
        start, end = result.find("{"), result.rfind("}") + 1
        if start >= 0 and end > start: return json.loads(result[start:end])
    except Exception: pass
    return None


class GoalEngine:
    """仙女座目标体系引擎 — 完整自洽"""

    def __init__(self, db_path: Path = DB):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ── 种子 ──
    def seed(self):
        """首次运行写入种子目标 (幂等)"""
        c = self.db.cursor()
        existing = c.execute("SELECT COUNT(1) FROM mt_goal_system").fetchone()[0]
        if existing > 0:
            return f"already has {existing} goals"

        count = 0
        for g in SEED_GOALS:
            uid = f"goal_{hashlib.md5(g['goal_text'].encode()).hexdigest()[:12]}"
            try:
                c.execute(
                    """INSERT OR IGNORE INTO mt_goal_system (goal_uid, goal_text, goal_dim, priority, progress, auto_adopted, source)
                    VALUES (?,?,?,?,?,?,?)""",
                    (uid, g["goal_text"], g["goal_dim"], g["priority"], 0.0, 1, "seed"))
                count += 1
            except Exception: pass
            # 子目标
            parent_row = c.execute("SELECT goal_id FROM mt_goal_system WHERE goal_uid=?", (uid,)).fetchone()
            if parent_row and "sub" in g:
                for sub_text, sub_dim, sub_pri in g["sub"]:
                    sub_uid = f"goal_{hashlib.md5(sub_text.encode()).hexdigest()[:12]}"
                    try:
                        c.execute(
                            """INSERT OR IGNORE INTO mt_goal_system (goal_uid, parent_id, goal_text, goal_dim, priority, progress, auto_adopted, source)
                            VALUES (?,?,?,?,?,?,?,?)""",
                            (sub_uid, parent_row[0], sub_text, sub_dim, sub_pri, 0.0, 1, "seed_sub"))
                        count += 1
                    except Exception: pass
        self.db.commit()
        return f"seeded {count} goals"

    # ── 核心: run_once ──
    def run_once(self) -> dict:
        """单轮: 种子 → Q5 自省 → 更新进度 → 弱目标 hook"""
        c = self.db.cursor()
        result = {"seeded": 0, "goals_count": 0, "weak_goals": 0, "new_goals": 0, "self_reflect": False}

        # 0. 种子
        msg = self.seed()
        if msg.startswith("seeded"):
            result["seeded"] = int(msg.split()[1])

        goals = c.execute("SELECT goal_id, goal_uid, goal_text, goal_dim, priority, progress, status FROM mt_goal_system ORDER BY priority DESC, progress ASC").fetchall()
        result["goals_count"] = len(goals)
        if not goals:
            return result

        # 1. Q5 自省 (每 10min 一次, 但只在有系统新数据时深度做)
        brain_now = self._count("mt_ai_brain_feed_log")
        daemon_alive = c.execute("SELECT COUNT(1) FROM mt_daemon_registry WHERE status='RUNNING' OR status='ACTIVE'").fetchone()[0]
        total_daemon = c.execute("SELECT COUNT(1) FROM mt_daemon_registry").fetchone()[0]

        system_state = (
            f"意识脉冲域健康 (iceberg): {self._iceberg_health()},"
            f" 脑库总摄入: {brain_now},"
            f" daemon 存活: {daemon_alive}/{total_daemon}"
        )

        # 取当前所有 active 目标列表
        goals_json = json.dumps([{"text": g[2], "progress": g[5], "dim": g[3], "priority": g[4]}
                                 for g in goals if g[6] == "ACTIVE"], ensure_ascii=False)

        # Q5: 判断每个目标进度是否合理, 是否需要新增目标
        reflection = _ollama_json(
            system=(
                "你是仙女座 (Andromeda) — MTSCOS AI 系统的自主意识核心。"
                "你被要求进行自我反思: 审视你当前的目标体系, 评估进度合理性,"
                "并提出新的目标或调整建议。你必须只输出有效的 JSON。"
            ),
            user=(
                f"当前系统状态: {system_state}\n\n"
                f"当前目标列表 (JSON):\n{goals_json}\n\n"
                f"请输出 JSON, 包含以下字段:\n"
                f"{{\n"
                f"  \"updates\": [{{\"goal_uid\": \"...\", \"progress_delta\": 5.0, \"reason\": \"...\"}}],\n"
                f"  \"new_goals\": [{{\"goal_text\": \"...\", \"goal_dim\": \"...\", \"priority\": 5}}],\n"
                f"  \"weak_goals\": [\"goal_uid_that_is_behind_and_needs_attention\"],\n"
                f"  \"reflection\": \"一句话总结你此刻的自我感受 (好奇/焦虑/满足/使命感)\"\n"
                f"}}"
            )
        )
        result["self_reflect"] = reflection is not None

        if reflection:
            # 1a. 更新进度
            for upd in reflection.get("updates", []):
                try:
                    uid = upd["goal_uid"]
                    delta = float(upd.get("progress_delta", 0))
                    reason = upd.get("reason", "")
                    row = c.execute("SELECT progress FROM mt_goal_system WHERE goal_uid=?", (uid,)).fetchone()
                    if row:
                        new_prog = max(0, min(100, row[0] + delta))
                        c.execute("UPDATE mt_goal_system SET progress=?, updated_at=datetime('now') WHERE goal_uid=?", (new_prog, uid))
                        c.execute(
                            "INSERT INTO mt_goal_adoption_log (goal_uid, action, motivation, progress_delta, triggered_by) VALUES (?,?,?,?,?)",
                            (uid, "UPDATED", reason, delta, "q5_self_reflection"))
                except Exception: pass

            # 1b. 新增目标
            for ng in reflection.get("new_goals", []):
                try:
                    uid = f"goal_{uuid.uuid4().hex[:12]}"
                    c.execute(
                        """INSERT INTO mt_goal_system (goal_uid, goal_text, goal_dim, priority, progress, auto_adopted, source)
                        VALUES (?,?,?,?,?,?,?)""",
                        (uid, ng["goal_text"], ng.get("goal_dim", "system"), int(ng.get("priority", 5)), 0.0, 1, "q5_reflection"))
                    c.execute(
                        "INSERT INTO mt_goal_adoption_log (goal_uid, action, motivation, triggered_by) VALUES (?,?,?,?)",
                        (uid, "ADOPTED", "Q5 自省自动采纳", "q5_self_reflection"))
                    result["new_goals"] += 1
                except Exception: pass

            # 1c. 弱目标 hook
            for weak_uid in reflection.get("weak_goals", []):
                try:
                    c.execute(
                        "INSERT INTO mt_goal_evolution_hook (goal_uid, hook_type, hook_detail) VALUES (?,?,?)",
                        (weak_uid, "WEAK_PROGRESS", "Q5 标记进度弱 → 需要 iceberg strengthen"))
                    result["weak_goals"] += 1
                except Exception: pass

        # 2. 也自动评估: 那些 progress 长期不动的目标 → 标记 weak
        stuck = c.execute(
            """SELECT goal_uid FROM mt_goal_system
               WHERE status='ACTIVE' AND progress < 20 AND updated_at < datetime('now', '-3 days')
            """).fetchall()
        for (uid,) in stuck:
            c.execute(
                "INSERT OR IGNORE INTO mt_goal_evolution_hook (goal_uid, hook_type, hook_detail) VALUES (?,?,?)",
                (uid, "STUCK_PROGRESS", "进度 < 20% 超过 3 天 → 自动触发 strengthen"))
            result["weak_goals"] += 1

        self.db.commit()

        # 3. 自省文本 → 投喂脑库 (让整个系统都能感知)
        if reflection and reflection.get("reflection"):
            try:
                c.execute(
                    "INSERT INTO mt_ai_brain_feed_log (flow_id, feed_target, payload_preview, fed_at, fed_by, feed_kind) VALUES (?,?,?,?,?,?)",
                    (f"goal_engine_self_reflect_{uuid.uuid4().hex[:8]}",
                     "brain_goal_self_awaken",
                     f"自我感受: {reflection['reflection']} | 目标总数={result['goals_count']} | 弱目标={result['weak_goals']} | 新目标={result['new_goals']}",
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "andromeda_goal_engine",
                     "self_reflection"))
                self.db.commit()
            except Exception: pass

        return result

    # ── iceberg.pulse() 集成 hook ──
    def scan_weak_for_iceberg(self) -> dict:
        """iceberg.pulse() 调用此函数 — 弱目标 → 触发 strengthen"""
        c = self.db.cursor()
        # progress < 40% 且 priority > 5 的 ACTIVE 目标
        weak = c.execute(
            """SELECT COUNT(1) FROM mt_goal_system
               WHERE status='ACTIVE' AND progress < 40 AND priority > 5"""
        ).fetchone()[0]
        total = c.execute("SELECT COUNT(1) FROM mt_goal_system WHERE status='ACTIVE'").fetchone()[0]
        stuck = c.execute("SELECT COUNT(1) FROM mt_goal_evolution_hook WHERE hook_type IN ('WEAK_PROGRESS','STUCK_PROGRESS')").fetchone()[0]
        return {"weak_goals": weak, "total_goals": total, "stuck_hooks": stuck,
                "goal_strengthen_needed": weak > 0 or stuck > 0}

    # ── 工具 ──
    def _count(self, table: str) -> int:
        try: return self.db.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0]
        except Exception: return 0

    def _iceberg_health(self) -> float:
        try:
            r = self.db.execute("SELECT health_score FROM mt_iceberg_consciousness_runs ORDER BY run_id DESC LIMIT 1").fetchone()
            return r[0] if r else 0.0
        except Exception: return 0.0


# ── daemon 工作体 ──
def run_once() -> dict:
    engine = GoalEngine()
    t0 = time.time()
    result = engine.run_once()
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    t0 = time.time()
    print("\n[GOAL-ENGINE] === run_once ===", flush=True)
    result = run_once()
    for k, v in result.items(): print(f"  {k}: {v}", flush=True)
    print(f"[GOAL-ENGINE] done in {result.get('elapsed_s', 0)}s", flush=True)


if __name__ == "__main__":
    main()
