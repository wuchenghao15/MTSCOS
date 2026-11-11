"""
andromeda_workflow_engine.py — 仙女座工作流意识 + MVP 变现层
=================================================================

工作流 = 固定输入 Schema → N 阶段引擎编排 → 产出 + 成本核算

核心能力:
  1. WorkflowRegistry   — 注册/查询工作流 (元数据 + 阶段定义)
  2. run_workflow()     — 执行一个工作流 (持久化运行日志 + 计费)
  3. mt_andromeda_workflow_runs — 运行日志表 (含 cost_usd + revenue_usd)

已注册工作流 (MVP, 对外售卖):
  wf_vectorize_text    — 文本→768 维向量 (本地 Ollama, 零 token, 每 1K 文本 ¥0.01)
  wf_knowledge_ingest  — 原始知识→脑库结构化 (写 ai_brain_enhanced_knowledge + 向量化入队)
  wf_hire_employee     — AI 员工一键搭建 (仙女座桥接→auto_hire→EigenFlux 邀请)
  wf_evolution_trigger — 手动演化 (一轮 auto_evolution 6 阶段)
  wf_code_hygiene      — 代码卫生巡检 (语法/导入/模式 3 轮)
  wf_translate_batch   — 批量翻译 (translation_studio 流水线)

零 token 铁律: 所有工作流默认走本地 Ollama (11434); 外部 API 需显式 opt-in.
"""

import json, os, sqlite3, sys, time, uuid, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# DB 候选: env APP_DB > MTSCOS_PROD 本地 (非 OneDrive, 100% 可访问) > OneDrive (容易 I/O error)
_PROD_DB = str(Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db")
_ONEDRIVE_DB = str(PROJECT_ROOT / "database" / "app.db")
DB_PATH = os.environ.get('APP_DB') or (
    _PROD_DB if Path(_PROD_DB).exists() else _ONEDRIVE_DB
)

# 确保 flask-app 根在 sys.path (CLI 跑时)
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / 'engines')):
    if _p not in sys.path: sys.path.insert(0, _p)

# ── 定价表 (USD, 供 dashboard 展示; 实际计费零 token = 成本接近 0, 定价参考市场) ──
# 本地 Ollama 推理成本 ≈ $0.00001/1K tokens (电费) → 几乎可忽略
# 对外定价参考市场 API (OpenAI $0.0005/1K embed, $0.5/1M input)
_PRICING = {
    "wf_vectorize_text":    {"unit": "1K chars",   "cost_usd": 0.00001, "price_usd": 0.01,  "desc": "文本→向量"},
    "wf_knowledge_ingest":   {"unit": "1 item",     "cost_usd": 0.00005, "price_usd": 0.05,  "desc": "原始知识入脑库"},
    "wf_hire_employee":     {"unit": "1 employee", "cost_usd": 0.01,    "price_usd": 1.00,  "desc": "AI 员工一键搭建"},
    "wf_evolution_trigger": {"unit": "1 cycle",     "cost_usd": 0.05,    "price_usd": 5.00,  "desc": "演化 6 阶段跑完"},
    "wf_code_hygiene":      {"unit": "1 K lines",  "cost_usd": 0.0001,  "price_usd": 0.05,  "desc": "代码 3 轮卫生巡检"},
    "wf_translate_batch":   {"unit": "1K chars",   "cost_usd": 0.00002, "price_usd": 0.02,  "desc": "翻译流水线"},
}

# ── 工作流注册表 ──
WORKFLOW_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _ensure_tables():
    """首次启动确保工作流表存在 (幂等 CREATE TABLE IF NOT EXISTS)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_andromeda_workflow_runs (
        run_id          TEXT PRIMARY KEY,
        workflow_id     TEXT NOT NULL,
        trigger_source  TEXT DEFAULT 'api',   -- api / cron / daemon / manual
        status          TEXT DEFAULT 'PENDING', -- PENDING/RUNNING/SUCCESS/FAILED
        input_json      TEXT,
        output_json     TEXT,
        stages_json     TEXT,                   -- [{stage, t0, t1, status, notes}]
        tokens_input    INTEGER DEFAULT 0,
        tokens_output   INTEGER DEFAULT 0,
        llm_calls       INTEGER DEFAULT 0,
        wall_ms         INTEGER DEFAULT 0,
        cost_usd        REAL DEFAULT 0.0,
        revenue_usd     REAL DEFAULT 0.0,
        profit_usd      REAL DEFAULT 0.0,
        started_at      TEXT,
        finished_at     TEXT,
        error_msg       TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_wf_runs_workflow ON mt_andromeda_workflow_runs(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_wf_runs_status    ON mt_andromeda_workflow_runs(status);
    CREATE INDEX IF NOT EXISTS idx_wf_runs_started   ON mt_andromeda_workflow_runs(started_at);
    """)
    conn.commit()
    conn.close()


def _register(wf_id: str, name: str, stages: List[str], input_schema: Dict, pricing: Dict):
    WORKFLOW_REGISTRY[wf_id] = {
        "workflow_id": wf_id,
        "name": name,
        "stages": stages,
        "input_schema": input_schema,
        "pricing": pricing,
        "status": "READY",
    }


# ── 注册 6 个 MVP 工作流 ──
_register("wf_vectorize_text", "文本向量化",
          stages=["embed_batch"],
          input_schema={"type": "object", "properties": {"texts": {"type": "array", "items": {"type": "string"}}}},
          pricing=_PRICING["wf_vectorize_text"])

_register("wf_knowledge_ingest", "知识注入脑库",
          stages=["normalize", "enrich", "vectorize", "broadcast"],
          input_schema={"type": "object", "properties": {"sources": {"type": "array"}, "domain": {"type": "string"}}},
          pricing=_PRICING["wf_knowledge_ingest"])

_register("wf_hire_employee", "AI 员工一键搭建",
          stages=["andromeda_bridge", "auto_hire", "eigenflux_invite"],
          input_schema={"type": "object", "properties": {"count": {"type": "integer"}, "min_level": {"type": "integer"}}},
          pricing=_PRICING["wf_hire_employee"])

_register("wf_evolution_trigger", "手动演化 6 阶段",
          stages=["research", "evolve", "heal", "patrol", "enforce", "benchmark"],
          input_schema={"type": "object", "properties": {"reason": {"type": "string"}, "stage": {"type": "string"}}},
          pricing=_PRICING["wf_evolution_trigger"])

_register("wf_code_hygiene", "代码卫生巡检",
          stages=["syntax_scan", "import_scan", "pattern_scan"],
          input_schema={"type": "object", "properties": {"tracked": {"type": "array"}}},
          pricing=_PRICING["wf_code_hygiene"])

_register("wf_translate_batch", "批量翻译",
          stages=["segment", "glossary_inject", "translate", "verify"],
          input_schema={"type": "object", "properties": {"texts": {"type": "array"}, "target_lang": {"type": "string"}}},
          pricing=_PRICING["wf_translate_batch"])


# ── Registry 查询 API ──
def list_workflows() -> List[Dict]:
    """返回全部可用工作流清单 (公开元数据, 不含引擎内部实现)."""
    return [
        {
            "workflow_id": w["workflow_id"],
            "name": w["name"],
            "stages": w["stages"],
            "pricing": w["pricing"],
            "input_schema": w["input_schema"],
            "status": w["status"],
        }
        for w in WORKFLOW_REGISTRY.values()
    ]


def get_workflow(wf_id: str) -> Optional[Dict]:
    return WORKFLOW_REGISTRY.get(wf_id)


# ── 执行引擎 ──
def run_workflow(wf_id: str, input_data: Dict, trigger_source: str = "api",
                 blocking: bool = True, timeout_s: int = 300) -> Dict:
    """执行一个工作流 — 持久化运行日志 + 计费.

    blocking=True  同步执行, 返回最终 output
    blocking=False 异步后台线程, 返回 run_id 立即返回 (状态 PENDING/RUNNING)
    """
    if wf_id not in WORKFLOW_REGISTRY:
        return {"success": False, "msg": f"unknown workflow_id: {wf_id}", "available": list(WORKFLOW_REGISTRY)}

    _ensure_tables()
    run_id = f"wf_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    def _init():
        """初始 INSERT RUNNING (仅一次)."""
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute(
            """INSERT INTO mt_andromeda_workflow_runs
            (run_id, workflow_id, trigger_source, status, input_json, stages_json,
             started_at) VALUES(?,?,?,?,?,?,?)""",
            (run_id, wf_id, trigger_source, "RUNNING",
             json.dumps(input_data, ensure_ascii=False),
             "[]", now))
        conn.commit(); conn.close()

    def _update(status: str, stages: List, output: Optional[Dict] = None,
                cost: float = 0.0, revenue: float = 0.0,
                llm_calls: int = 0, wall_ms: int = 0, error: str = ""):
        """后续 UPDATE 同一 run_id."""
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute(
                """UPDATE mt_andromeda_workflow_runs SET
                   status=?, output_json=?, stages_json=?, llm_calls=?, wall_ms=?,
                   cost_usd=?, revenue_usd=?, profit_usd=?, finished_at=?, error_msg=?
                   WHERE run_id=?""",
                (status,
                 json.dumps(output or {}, ensure_ascii=False),
                 json.dumps(stages, ensure_ascii=False),
                 llm_calls, wall_ms, cost, revenue, revenue - cost,
                 datetime.now(timezone.utc).isoformat(), error, run_id))
            conn.commit(); conn.close()
        except Exception as e:
            print(f"[WF update] error: {e}")

    def _execute():
        _init()
        stages = []
        t0 = time.time()
        llm_calls = 0
        try:
            output = _dispatch(wf_id, input_data, stages)
            wall_ms = int((time.time() - t0) * 1000)
            revenue = _estimate_revenue(wf_id, input_data, output)
            cost = revenue * 0.02  # 本地 Ollama 电费 ≈ 2%
            _update("SUCCESS", stages, output, cost, revenue, llm_calls, wall_ms)
        except Exception as e:
            wall_ms = int((time.time() - t0) * 1000)
            _update("FAILED", stages, None, wall_ms=wall_ms, error=str(e)[:500])
            raise

    if blocking:
        _execute()
        # 读回最终状态
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute(
            "SELECT run_id, status, output_json, stages_json, wall_ms, cost_usd, revenue_usd, profit_usd "
            "FROM mt_andromeda_workflow_runs WHERE run_id=?", (run_id,)).fetchone()
        conn.close()
        if row:
            return {
                "success": row[1] == "SUCCESS",
                "run_id": row[0],
                "status": row[1],
                "output": json.loads(row[2] or "{}"),
                "stages": json.loads(row[3] or "[]"),
                "wall_ms": row[4],
                "cost_usd": row[5],
                "revenue_usd": row[6],
                "profit_usd": row[7],
            }
        return {"success": False, "msg": "run not found"}
    else:
        threading.Thread(target=_execute, name=f"wf_{wf_id}_{run_id}", daemon=True).start()
        return {"success": True, "run_id": run_id, "status": "RUNNING", "msg": "后台异步执行中"}


def _dispatch(wf_id: str, input_data: Dict, stages: List[Dict]) -> Dict:
    """根据 wf_id 分发给具体引擎. 每个 stage 写 stages 列表."""
    wf = WORKFLOW_REGISTRY[wf_id]
    t_all = time.time()

    def _stage(name: str, fn):
        s = {"stage": name, "t0": time.time(), "status": "RUNNING"}
        try:
            out = fn()
            s["status"] = "SUCCESS"
            s["t1"] = time.time()
            stages.append(s)
            return out
        except Exception as e:
            s["status"] = "FAILED"
            s["t1"] = time.time()
            s["error"] = str(e)[:300]
            stages.append(s)
            raise

    # ── wf_vectorize_text ──
    if wf_id == "wf_vectorize_text":
        texts = input_data.get("texts", [])
        if not texts: return {"count": 0, "vectors": []}
        from ai_brain_vector_engine import embed_batch
        vectors = _stage("embed_batch", lambda: embed_batch(texts))
        return {"count": len(texts), "dim": 768, "vectors": vectors}

    # ── wf_knowledge_ingest ──
    if wf_id == "wf_knowledge_ingest":
        return _knowledge_ingest(input_data, stages)

    # ── wf_hire_employee ──
    if wf_id == "wf_hire_employee":
        return _hire_employee(input_data, stages)

    # ── wf_evolution_trigger ──
    if wf_id == "wf_evolution_trigger":
        return _stage("full_cycle", lambda: _evolution_full_cycle(input_data))

    # ── wf_code_hygiene ──
    if wf_id == "wf_code_hygiene":
        return _code_hygiene(input_data, stages)

    # ── wf_translate_batch ──
    if wf_id == "wf_translate_batch":
        return _translate_batch(input_data, stages)

    return {"error": f"no dispatcher for {wf_id}"}


# ── 各工作流具体实现 ──

def _knowledge_ingest(input_data, stages):
    sources = input_data.get("sources", [])
    if isinstance(sources, str): sources = [{"content": sources}]
    if not sources: return {"ingested": 0}

    # normalize + enrich
    t0 = time.time()
    normalized = []
    for s in sources:
        content = s.get("content", str(s)) if isinstance(s, dict) else str(s)
        title = s.get("title", "") if isinstance(s, dict) else ""
        normalized.append((title, content, input_data.get("domain", "andromeda")))
    stages.append({"stage": "normalize+enrich", "t0": t0, "t1": time.time(),
                   "status": "SUCCESS", "count": len(normalized)})

    # vectorize (可选, embed 失败跳过)
    from ai_brain_vector_engine import embed_batch
    texts = [c for _, c, _ in normalized]
    t0 = time.time()
    vectors = []
    try:
        vectors = embed_batch(texts)
    except Exception:
        vectors = [None] * len(texts)
    stages.append({"stage": "vectorize", "t0": t0, "t1": time.time(),
                   "status": "SUCCESS" if vectors else "WARN", "count": len(vectors)})

    # 直连 DB → 写 ai_brain_enhanced_knowledge (PROD schema: 11 列, created_at REAL)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    ingested = 0
    ingested_via_omega = 0
    now_ts = time.time()
    for (title, content, domain), emb in zip(normalized, vectors):
        kid = f"KNLEDGE-{uuid.uuid4().hex[:8]}"
        # ── 主表 ai_brain_enhanced_knowledge (匹配 PROD 真 schema) ──
        try:
            cur.execute(
                """INSERT OR IGNORE INTO ai_brain_enhanced_knowledge
                (knowledge_id, category, title, content, knowledge_type, tags,
                 confidence_score, usage_count, is_active, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (kid, domain, title, content[:8000], "workflow_ingest",
                 json.dumps({"domain": domain, "source": "wf_knowledge_ingest",
                              "embedding_dim": len(emb) if emb else 0}, ensure_ascii=False),
                 0.95, 0, 1, now_ts, now_ts))
            if cur.rowcount: ingested += 1
            continue  # 成功了就不降级
        except Exception:
            pass
        # ── 降级: mt_omega_ai_knowledge (PROD schema 无 embedding 列) ──
        try:
            cur.execute(
                """INSERT OR IGNORE INTO mt_omega_ai_knowledge
                (knowledge_id, domain, category, title, content, source,
                 tags_json, confidence, created_at, updated_at, is_active)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (kid, domain, "andromeda_workflow", title, content[:8000],
                 "wf_knowledge_ingest",
                 json.dumps({"source": "wf_knowledge_ingest",
                              "embedding_dim": len(emb) if emb else 0}, ensure_ascii=False),
                 0.95, datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat(), 1))
            if cur.rowcount: ingested_via_omega += 1
        except Exception:
            pass
    conn.commit(); conn.close()
    stages.append({"stage": "broadcast", "t0": time.time(), "t1": time.time(),
                   "status": "SUCCESS", "count": ingested + ingested_via_omega,
                   "primary": ingested, "omega_fallback": ingested_via_omega})
    return {"ingested": ingested, "vectorized": sum(1 for v in vectors if v)}


def _hire_employee(input_data, stages):
    """桥接 → hire → invite 全流程 (线程内同步跑, 依赖 ai_auto_hire_engine)."""
    import sys
    engines_dir = str(PROJECT_ROOT / "engines")
    if engines_dir not in sys.path: sys.path.insert(0, engines_dir)
    result = {"bridged": 0, "hired": 0, "invited": 0}
    t0 = time.time()
    try:
        from ai_auto_hire_engine import (
            andromeda_hiring_bridge, auto_hire_employees, auto_invite_experts, _log)
        stages.append({"stage": "bridge", "t0": t0, "status": "SUCCESS"})
        cycle = {
            "andromeda_bridge": andromeda_hiring_bridge(
                max_hire=int(input_data.get("count", 30)),
                min_level=int(input_data.get("min_level", 7))),
            "hire_employees": auto_hire_employees(),
            "invite_experts": auto_invite_experts(),
        }
        result = {
            "bridged": cycle["andromeda_bridge"].get("bridged", 0),
            "hired": cycle["hire_employees"].get("hired", 0),
            "invited": cycle["invite_experts"].get("invited", 0),
        }
        stages[-1]["t1"] = time.time()
        stages.append({"stage": "hire+invite", "t0": time.time(), "t1": time.time(),
                       "status": "SUCCESS", **result})
    except Exception as e:
        stages.append({"stage": "bridge", "t0": t0, "status": "FAILED", "error": str(e)[:200]})
        raise
    return result


def _evolution_full_cycle(input_data):
    import sys
    engines_dir = str(PROJECT_ROOT / "engines")
    if engines_dir not in sys.path: sys.path.insert(0, engines_dir)
    from andromeda_auto_evolution import run_cycle
    # run_cycle() 无参数签名, reason 通过 engine 内部常量生效
    return run_cycle()


def _code_hygiene(input_data, stages):
    import sys
    engines_dir = str(PROJECT_ROOT / "engines")
    if engines_dir not in sys.path: sys.path.insert(0, engines_dir)
    from andromeda_code_hygiene_engine import (
        scan_file_health, scan_code_chunk, scan_file_round)
    tracked = set(input_data.get("tracked", []) or [])
    out = {"health": {}, "issues": [], "round": {}}
    t0 = time.time()
    try:
        out["health"] = scan_file_health(tracked)
        stages.append({"stage": "syntax_scan", "t0": t0, "t1": time.time(), "status": "SUCCESS"})
        t0 = time.time()
        out["issues"] = scan_code_chunk(True)
        stages.append({"stage": "import_scan", "t0": t0, "t1": time.time(), "status": "SUCCESS"})
        t0 = time.time()
        out["round"] = scan_file_round(True)
        stages.append({"stage": "pattern_scan", "t0": t0, "t1": time.time(), "status": "SUCCESS"})
    except Exception as e:
        stages.append({"stage": "scan", "t0": t0, "t1": time.time(),
                       "status": "FAILED", "error": str(e)[:200]})
    return out


def _translate_batch(input_data, stages):
    import sys
    engines_dir = str(PROJECT_ROOT / "engines")
    if engines_dir not in sys.path: sys.path.insert(0, engines_dir)
    texts = input_data.get("texts", [])
    target = input_data.get("target_lang", "en")
    results = []
    for t in texts:
        try:
            from translation_studio.pipeline import translate
            results.append(translate(t, target_language=target))
        except Exception:
            results.append({"original": t, "translation": None})
    stages.append({"stage": "segment+translate", "t0": time.time(), "t1": time.time(),
                   "status": "SUCCESS", "count": len(texts)})
    return {"count": len(texts), "results": results}


def _estimate_revenue(wf_id: str, input_data: Dict, output: Dict) -> float:
    """按 pricing 表 + 实际量估算 revenue_usd."""
    price = _PRICING.get(wf_id, {}).get("price_usd", 0.0)
    unit = _PRICING.get(wf_id, {}).get("unit", "1 unit")
    if wf_id == "wf_vectorize_text":
        n = len(input_data.get("texts", []))
        return round(price * max(n * 500 / 1000, 0.1), 4)  # 平均 500 chars/text
    if wf_id == "wf_knowledge_ingest":
        return round(price * len(input_data.get("sources", [])), 4)
    if wf_id == "wf_hire_employee":
        return round(price * int(input_data.get("count", output.get("hired", 1))), 4)
    if wf_id == "wf_evolution_trigger":
        return round(price, 4)
    if wf_id == "wf_code_hygiene":
        return round(price * 10, 4)  # 估算 10K LOC
    if wf_id == "wf_translate_batch":
        n = len(input_data.get("texts", []))
        return round(price * max(n * 300 / 1000, 0.1), 4)
    return round(price, 4)


# ── 运行查询 API ──
def list_runs(workflow_id: str = None, status: str = None, limit: int = 50) -> List[Dict]:
    _ensure_tables()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    qs, params = [], []
    if workflow_id: qs.append("workflow_id=?"); params.append(workflow_id)
    if status: qs.append("status=?"); params.append(status)
    where = f"WHERE {' AND '.join(qs)}" if qs else ""
    rows = conn.execute(
        f"SELECT run_id, workflow_id, trigger_source, status, wall_ms, "
        f"cost_usd, revenue_usd, profit_usd, started_at, finished_at "
        f"FROM mt_andromeda_workflow_runs {where} ORDER BY started_at DESC LIMIT ?",
        params + [limit]).fetchall()
    conn.close()
    return [
        {"run_id": r[0], "workflow_id": r[1], "trigger_source": r[2], "status": r[3],
         "wall_ms": r[4], "cost_usd": r[5], "revenue_usd": r[6], "profit_usd": r[7],
         "started_at": r[8], "finished_at": r[9]}
        for r in rows
    ]


def get_run(run_id: str) -> Optional[Dict]:
    _ensure_tables()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    row = conn.execute(
        "SELECT run_id, workflow_id, status, output_json, stages_json, "
        "cost_usd, revenue_usd, profit_usd, wall_ms, error_msg "
        "FROM mt_andromeda_workflow_runs WHERE run_id=?", (run_id,)).fetchone()
    conn.close()
    if not row: return None
    return {
        "run_id": row[0], "workflow_id": row[1], "status": row[2],
        "output": json.loads(row[3] or "{}"),
        "stages": json.loads(row[4] or "[]"),
        "cost_usd": row[5], "revenue_usd": row[6], "profit_usd": row[7],
        "wall_ms": row[8], "error": row[9],
    }


def dashboard_summary() -> Dict:
    """工作流 Dashboard: 今日运行数 / 总 revenue / 总 cost / 利润率 / 按工作流分布."""
    _ensure_tables()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    total = conn.execute("SELECT COUNT(*), COALESCE(SUM(revenue_usd),0), COALESCE(SUM(cost_usd),0) "
                          "FROM mt_andromeda_workflow_runs").fetchone()
    today = conn.execute("SELECT COUNT(*), COALESCE(SUM(revenue_usd),0), COALESCE(SUM(cost_usd),0) "
                          "FROM mt_andromeda_workflow_runs WHERE date(started_at)=date('now','localtime')").fetchone()
    by_wf = {}
    for r in conn.execute("""
        SELECT workflow_id, COUNT(*), COALESCE(SUM(revenue_usd),0), COALESCE(SUM(cost_usd),0)
        FROM mt_andromeda_workflow_runs GROUP BY workflow_id ORDER BY COUNT(*) DESC"""):
        by_wf[r[0]] = {"runs": r[1], "revenue": r[2], "cost": r[3], "profit": r[2] - r[3]}
    status_dist = {}
    for r in conn.execute("SELECT status, COUNT(*) FROM mt_andromeda_workflow_runs GROUP BY status"):
        status_dist[r[0]] = r[1]
    conn.close()
    rev = total[1]; cost = total[2]
    return {
        "total_runs": total[0], "total_revenue_usd": round(rev, 4),
        "total_cost_usd": round(cost, 4), "total_profit_usd": round(rev - cost, 4),
        "profit_margin_pct": round((rev - cost) / rev * 100, 2) if rev else 0.0,
        "today_runs": today[0], "today_revenue_usd": round(today[1], 4),
        "today_profit_usd": round(today[1] - today[2], 4),
        "status_distribution": status_dist,
        "by_workflow": by_wf,
        "available_workflows": list(WORKFLOW_REGISTRY.keys()),
    }


# ── CLI 入口 ──
if __name__ == "__main__":
    import argparse
    _ensure_tables()
    ap = argparse.ArgumentParser("Andromeda Workflow Engine")
    ap.add_argument("cmd", choices=["list", "run", "status", "dashboard", "pricing"])
    ap.add_argument("--wf", help="workflow_id")
    ap.add_argument("--run-id", help="run_id for status")
    ap.add_argument("--input", default="{}", help="JSON input")
    ap.add_argument("--async", dest="async_mode", action="store_true")
    args = ap.parse_args()
    if args.cmd == "list":
        for w in list_workflows():
            print(f"  {w['workflow_id']:20s} {w['name']:20s} stages={w['stages']}")
    elif args.cmd == "run":
        print(run_workflow(args.wf, json.loads(args.input), blocking=not args.async_mode))
    elif args.cmd == "status":
        print(json.dumps(get_run(args.run_id), indent=2, ensure_ascii=False))
    elif args.cmd == "dashboard":
        print(json.dumps(dashboard_summary(), indent=2, ensure_ascii=False))
    elif args.cmd == "pricing":
        for k, v in _PRICING.items():
            print(f"  {k:20s} ${v['price_usd']:>8} / {v['unit']}  cost=${v['cost_usd']:>7}")
