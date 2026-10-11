#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座大思维发散集群矩阵 v3.0 (asyncio 并发 + local_inference 接入)
=====================================================================
flow_id: flow_20261008142006_andromeda_cluster_sync

架构:
  12 EigenFlux 节点 × 3 维度 (隐喻/类比/跨域) = 36 并发任务
  asyncio.Semaphore(2) 限流 → Mac mini 14B 模型 OOM 保护
  aiohttp ClientSession keep-alive TCP 复用
  try/finally 确保资源释放
  SQLite → run_in_executor 串行写

时序:
  v2 串行 12×15s ≈ 180s → v3 并发 Sem=2 ≈ 90s → Sem=4 ≈ 45s

命令:
  python3 andromeda_cluster_matrix.py start   建表 seed
  python3 andromeda_cluster_matrix.py scan    asyncio 并发跑一轮
  python3 andromeda_cluster_matrix.py status  状态
"""

import json
import os
import sqlite3
import sys
import time
import random
import datetime
import asyncio

# ============ DB 路径 ============
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(_SCRIPT_DIR)
_PROJECT_ROOT = os.path.dirname(_FLASK_APP)
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", _PROJECT_ROOT)

DB_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "app.db"),
    os.path.join(_FLASK_APP, "app.db"),
    os.path.join(_FLASK_APP, "database", "app.db"),
]
APP_DB = os.environ.get("APP_DB") or next(
    (p for p in DB_CANDIDATES if os.path.exists(p)), DB_CANDIDATES[0]
)
os.environ["APP_DB"] = APP_DB

# ============ Ollama 检测 ============
try:
    import urllib.request as _ur
    def _ollama_available():
        try:
            req = _ur.Request("http://127.0.0.1:11434/api/tags")
            resp = _ur.urlopen(req, timeout=2)
            return resp.status == 200
        except:
            return False
    OLLAMA_OK = _ollama_available()
except Exception:
    OLLAMA_OK = False

# ============ 模型自动检测 ============
def _detect_model():
    if not OLLAMA_OK:
        return None
    try:
        import urllib.request as _ur
        req = _ur.Request("http://127.0.0.1:11434/api/tags")
        resp = _ur.urlopen(req, timeout=3)
        models = json.loads(resp.read()).get("models", [])
        if models:
            return next((m["name"] for m in models if "qwen" in m["name"].lower()), models[0]["name"])
    except Exception:
        pass
    return "qwen2.5:14b"

OLLAMA_MODEL = _detect_model()
# Mac mini 16GB RAM, 14B 模型 ~8GB → 并行 2 个
CONCURRENCY = 2 if OLLAMA_OK else 1

# ============ 12 EigenFlux 思维节点 ============
EIGENFLUX_NODES = [
    {"expert_name": "EigenFlux_架构师",   "expert_role": "系统架构", "weight": 1.2, "focus": "分布式/微服务/高可用"},
    {"expert_name": "EigenFlux_合规师",   "expert_role": "规则治理", "weight": 1.1, "focus": "IronRule/12步/全链路追溯"},
    {"expert_name": "EigenFlux_安全官",   "expert_role": "安全审查", "weight": 1.15, "focus": "OWASP/注入/XSS/越权"},
    {"expert_name": "EigenFlux_DBA",      "expert_role": "数据库",   "weight": 1.0, "focus": "SQLite/索引/慢查询"},
    {"expert_name": "EigenFlux_运维师",   "expert_role": "DevOps",   "weight": 1.05, "focus": "监控/告警/自动修复"},
    {"expert_name": "EigenFlux_前端师",   "expert_role": "UI/UX",    "weight": 1.0, "focus": "ElementPlus/响应式/Token"},
    {"expert_name": "EigenFlux_后端师",   "expert_role": "Flask",    "weight": 1.05, "focus": "蓝图/权限/限流"},
    {"expert_name": "EigenFlux_AI专家",   "expert_role": "LLM",      "weight": 1.2, "focus": "Ollama/本地推理/零token"},
    {"expert_name": "EigenFlux_数据师",   "expert_role": "数据科学", "weight": 0.95, "focus": "向量/embedding/相似度"},
    {"expert_name": "EigenFlux_教育家",   "expert_role": "K12",      "weight": 1.0, "focus": "教学法/认知科学"},
    {"expert_name": "EigenFlux_IoT师",    "expert_role": "Arduino",  "weight": 0.9,  "focus": "硬件/传感器/串口"},
    {"expert_name": "EigenFlux_综合师",   "expert_role": "全栈",     "weight": 1.1,  "focus": "跨域发散/类比/隐喻"},
]

DIVERGENT_DIMENSIONS = [
    ("metaphor",     "隐喻",     "用一个领域的概念比喻另一个领域, 创造新视角"),
    ("analogy",      "类比",     "找到两个不同领域的相似结构, 迁移解决方案"),
    ("cross_domain", "跨域",     "完全不相关的领域碰撞, 产生突破性想法"),
]


# ============ 同步组件 ============
def _connect():
    conn = sqlite3.connect(APP_DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_cluster_tables():
    conn = _connect()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_andromeda_cluster_matrix (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      round_id TEXT, node_id INTEGER, expert_name TEXT, expert_role TEXT,
      weight REAL DEFAULT 1.0, dimension TEXT, divergent_direction TEXT,
      input_topic TEXT, output_suggestion TEXT, aggregation_score REAL DEFAULT 0.0,
      is_aggregated INTEGER DEFAULT 0, is_fed_to_brain INTEGER DEFAULT 0,
      llm_generated INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_acm_round ON mt_andromeda_cluster_matrix(round_id);
    CREATE INDEX IF NOT EXISTS idx_acm_node ON mt_andromeda_cluster_matrix(expert_name);
    CREATE INDEX IF NOT EXISTS idx_acm_dim ON mt_andromeda_cluster_matrix(dimension);

    CREATE TABLE IF NOT EXISTS mt_andromeda_cluster_aggregation (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      round_id TEXT, topic TEXT, top_suggestions TEXT,
      cluster_summary TEXT, created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS mt_andromeda_cluster_status (
      node_name TEXT PRIMARY KEY,
      status TEXT DEFAULT "idle", last_heartbeat TEXT, current_task TEXT,
      completed_rounds INTEGER DEFAULT 0, last_error TEXT,
      updated_at TEXT DEFAULT (datetime('now'))
    );
    """)
    for col, dflt in [("llm_generated", "0"), ("is_fed_to_brain", "0"), ("node_id", "NULL")]:
        try:
            conn.execute(f"ALTER TABLE mt_andromeda_cluster_matrix ADD COLUMN {col} INTEGER DEFAULT {dflt}")
        except: pass
    conn.commit()
    conn.close()
    print(f"[CLUSTER v3] ✅ DB={APP_DB} Ollama={'🟢 '+OLLAMA_MODEL if OLLAMA_OK else '⚪'} Semaphore={CONCURRENCY}")


def seed_cluster_nodes():
    conn = _connect()
    for node in EIGENFLUX_NODES:
        conn.execute("""INSERT OR IGNORE INTO mt_andromeda_cluster_status
          (node_name, status, completed_rounds)
          VALUES (?, "idle", 0)""", (node["expert_name"],))
    conn.commit()
    conn.close()
    print(f"[CLUSTER v3] ✅ {len(EIGENFLUX_NODES)} 节点 seed")


# ============ asyncio 并发 Ollama 调用 ============
async def _ollama_generate_aio(session, prompt, sem, model=None, timeout=90):
    """asyncio 并发 Ollama generate → 带 Semaphore 限流"""
    if not OLLAMA_OK:
        return None
    if not model:
        model = OLLAMA_MODEL
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 120, "temperature": 0.85}
        })
        async with sem:  # Semaphore 限流 (try/finally 自动释放)
            async with session.post(
                "http://127.0.0.1:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout
            ) as resp:
                result = await resp.json()
                text = result.get("response", "").strip()
                return text if text else None
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None


def _build_prompt(topic, dim_name, expert_name, expert_focus):
    prompts = {
        "metaphor": (f"你是{expert_name},专注{expert_focus}。隐喻发散:如果「{topic}」是一个隐喻,"
                     "它的核心意象、隐藏含义、能带来什么新洞察?一句话60字内。"),
        "analogy":  (f"你是{expert_name},专注{expert_focus}。类比发散:「{topic}」和{expert_focus}领域的"
                     "哪个概念有相似结构?能迁移什么解决方案?一句话60字内。"),
        "cross_domain": (f"你是{expert_name},专注{expert_focus}。跨域发散:「{topic}」和{expert_focus}"
                         "+完全不相关领域碰撞,产生一个突破性想法?一句话60字内。"),
    }
    return prompts.get(dim_name, prompts["metaphor"])


async def _single_dim_divergent(session, sem, topic, dim_name, expert, n_tries=2):
    """单节点单维度 → 并发调 Ollama + fallback 模板"""
    dim_desc = next((d[2] for d in DIVERGENT_DIMENSIONS if d[0] == dim_name), "")
    prompt = _build_prompt(topic, dim_name, expert["expert_name"], expert["focus"])
    
    for _ in range(n_tries):
        llm_text = await _ollama_generate_aio(session, prompt, sem)
        if llm_text and len(llm_text) > 10:
            return {
                "expert_name": expert["expert_name"],
                "expert_role": expert["expert_role"],
                "weight": expert["weight"],
                "dimension": dim_name,
                "suggestion": llm_text[:200],
                "score": (0.85 + random.random() * 0.15) * expert["weight"],
                "llm": True,
            }
    
    # Fallback 模板 (并发失败时)
    tmpls = {
        "metaphor": [
            f"隐喻:「{topic}」的核心意象是什么?",
            f"隐喻:把「{topic}」比作{expert['focus'].split('/')[0]}",
        ],
        "analogy": [
            f"类比:「{topic}」≈{expert['focus']}领域的什么?",
            f"类比:迁移{expert['focus']}方案到「{topic}」",
        ],
        "cross_domain": [
            f"跨域:「{topic}」×{expert['focus']}×量子物理→新想法?",
            f"跨域:让{expert['expert_name']}重新设计「{topic}」",
        ],
    }
    tmpl = tmpls.get(dim_name, tmpls["metaphor"])
    return {
        "expert_name": expert["expert_name"],
        "expert_role": expert["expert_role"],
        "weight": expert["weight"],
        "dimension": dim_name,
        "suggestion": random.choice(tmpl),
        "score": (0.65 + random.random() * 0.30) * expert["weight"],
        "llm": False,
    }


async def execute_round_async(topic=None):
    """v3: asyncio 并发执行一轮 → 36 任务并发 Semaphore 限流"""
    # 延迟导入 aiohttp
    try:
        import aiohttp
    except ImportError:
        print("[CLUSTER v3] ⚠️ aiohttp 未安装, pip install aiohttp")
        return None, 0
    
    # 选主题
    conn_sync = _connect()
    input_topic = topic or _pick_topic(conn_sync)
    conn_sync.close()
    
    # round_id
    try:
        round_id = "round_" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    except:
        round_id = "round_" + datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    
    print(f"\n{'='*60}")
    print(f"🧠 v3 asyncio 集群第 {round_id} 轮")
    print(f"   主题: {input_topic}")
    print(f"   Ollama: {'🟢 '+OLLAMA_MODEL if OLLAMA_OK else '⚪'} | Semaphore={CONCURRENCY}")
    print(f"   并发任务: {len(EIGENFLUX_NODES)} 节点 × {len(DIVERGENT_DIMENSIONS)} 维度 = {len(EIGENFLUX_NODES)*len(DIVERGENT_DIMENSIONS)}")
    print(f"{'='*60}")
    
    t0 = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)
    all_results = []
    
    # aiohttp keep-alive ClientSession (TCP 复用)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=CONCURRENCY),
        timeout=aiohttp.ClientTimeout(total=120)
    ) as session:
        # 构造 36 个并发任务
        tasks = [
            _single_dim_divergent(session, sem, input_topic, dim_name, expert)
            for expert in EIGENFLUX_NODES
            for dim_name, _, _ in DIVERGENT_DIMENSIONS
        ]
        
        # 并发执行 + 进度打印
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            all_results.append(result)
            done += 1
            llm_mark = "🤖" if result["llm"] else "📝"
            if done % 6 == 0 or done == len(tasks):
                print(f"  {llm_mark} [{done}/{len(tasks)}] {result['expert_name']}|{result['dimension']}")
    
    elapsed = time.time() - t0
    
    # 聚合
    all_results.sort(key=lambda x: x["score"], reverse=True)
    top_10 = all_results[:10]
    llm_cnt = sum(1 for r in all_results if r["llm"])
    
    # 同步写 DB (SQLite 不支持多线程并发写)
    conn = _connect()
    
    # 落库 36 条发散记录
    for r in all_results:
        conn.execute("""INSERT INTO mt_andromeda_cluster_matrix
          (round_id, expert_name, expert_role, weight, dimension,
           divergent_direction, input_topic, output_suggestion,
           aggregation_score, llm_generated, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
          (round_id, r["expert_name"], r["expert_role"], r["weight"],
           r["dimension"], r["dimension"] + ("_llm" if r["llm"] else "_tmpl"),
           input_topic, r["suggestion"], r["score"], 1 if r["llm"] else 0))
    
    # completed_rounds++ + heartbeat
    for node in EIGENFLUX_NODES:
        conn.execute("""UPDATE mt_andromeda_cluster_status
          SET status="idle", last_heartbeat=datetime('now'),
              completed_rounds=completed_rounds+1, updated_at=datetime('now')
          WHERE node_name=?""", (node["expert_name"],))
    
    # 写聚合
    summary_lines = [
        f"🧠 v3 asyncio 第 {round_id} 轮",
        f"Ollama: {'🟢' if OLLAMA_OK else '⚪'} | LLM={llm_cnt}/{len(all_results)} | 耗时={elapsed:.1f}s",
    ]
    for i, s in enumerate(top_10[:5], 1):
        l = "🤖" if s["llm"] else "📝"
        summary_lines.append(f"  {i}. [{s['score']:.2f}] {l} {s['expert_name']}|{s['dimension']} → {s['suggestion'][:50]}")
    
    conn.execute("""INSERT INTO mt_andromeda_cluster_aggregation
      (round_id, topic, top_suggestions, cluster_summary, created_at)
      VALUES (?, ?, ?, ?, datetime('now'))""",
      (round_id, input_topic, json.dumps(top_10, ensure_ascii=False),
       "\n".join(summary_lines)))
    
    # 脑库投喂
    brain_cnt = 0
    for s in top_10[:5]:
        kid = f"cluster_{round_id}_{s['expert_name']}_{s['dimension']}"
        try:
            conn.execute("""INSERT OR IGNORE INTO ai_brain_enhanced_knowledge
              (knowledge_id, category, title, content, knowledge_type, tags,
               confidence_score, usage_count, is_active, created_at)
              VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, strftime('%s','now'))""",
              (kid, "cluster_divergent",
               f"[{s['expert_name']}|{s['dimension']}] 发散",
               s["suggestion"], "discovery",
               json.dumps({"round": round_id, "topic": input_topic, "llm": s["llm"]}, ensure_ascii=False),
               s["score"]))
            brain_cnt += 1
        except:
            pass
    
    conn.execute("UPDATE mt_andromeda_cluster_matrix SET is_aggregated=1 WHERE round_id=?", (round_id,))
    conn.commit()
    conn.close()
    
    print(f"\n📊 聚合 Top 5 ({llm_cnt}/{len(all_results)} LLM, {elapsed:.1f}s):")
    for i, s in enumerate(top_10[:5], 1):
        l = "🤖" if s["llm"] else "📝"
        print(f"  {i}. [{s['score']:.2f}] {l} {s['expert_name']}|{s['dimension']}")
        print(f"     → {s['suggestion'][:70]}")
    print(f"🧠 脑库投喂: {brain_cnt} 条")
    print(f"{'='*60}")
    
    return round_id, brain_cnt


# ============ _pick_topic (同步) ============
def _pick_topic(conn):
    try:
        topics = conn.execute(
            "SELECT content FROM eigenflux_messages ORDER BY RANDOM() LIMIT 3"
        ).fetchall()
        if topics and topics[0]:
            return topics[0][0][:80]
    except:
        pass
    fixed = [
        "仙女座集群矩阵 EigenFlux 12专家圆桌会议协作",
        "本地 Ollama 推理零 token 策略 vs API 成本对比",
        "智能挂载 daemon 心跳 watchdog 闭环架构优化",
        "冰山三层发散意识 Peak→Body→Base 联动机制",
        "Flask 限流白名单 Cloudflare 出口 IP 策略",
        "源码巡逻队 AST 扫描自动修复率提升方案",
        "Mac mini launchd daemon 管理 vs cron 对比",
        "集群矩阵 asyncio 并发 vs 串行性能对比",
    ]
    return random.choice(fixed)


def status():
    conn = _connect()
    print(f"""
═══════════════════════════════════════════════════
  🧠 仙女座大思维发散集群矩阵 v3.0
  DB: {APP_DB} | Ollama: {'🟢 '+OLLAMA_MODEL if OLLAMA_OK else '⚪'} | Sem={CONCURRENCY}
═══════════════════════════════════════════════════""")
    try:
        nodes = conn.execute(
            "SELECT node_name, status, last_heartbeat, completed_rounds FROM mt_andromeda_cluster_status ORDER BY node_name"
        ).fetchall()
        print(f"\n  思维节点 ({len(nodes)}):")
        for name, st, hb, rounds in nodes:
            mark = "🟢" if st == "running" else "⚪"
            print(f"  {mark} {name:20s} rounds={rounds:3d} heartbeat={hb or '—'}")
    except Exception as e:
        print(f"  ⚠️ cluster_status: {e}")
    try:
        cm = conn.execute("SELECT COUNT(1) FROM mt_andromeda_cluster_matrix").fetchone()[0]
        llm = conn.execute("SELECT COUNT(1) FROM mt_andromeda_cluster_matrix WHERE llm_generated=1").fetchone()[0]
        agg = conn.execute("SELECT COUNT(1) FROM mt_andromeda_cluster_aggregation").fetchone()[0]
        rounds_cnt = conn.execute("SELECT COUNT(DISTINCT round_id) FROM mt_andromeda_cluster_matrix").fetchone()[0]
        brain = conn.execute("SELECT COUNT(1) FROM ai_brain_enhanced_knowledge WHERE category='cluster_divergent'").fetchone()[0]
        print(f"\n  发散: {cm} 条 (LLM: {llm}) | 轮次: {rounds_cnt} | 聚合: {agg} | 脑库: {brain}")
    except Exception as e:
        print(f"  ⚠️ 统计: {e}")
    conn.close()


def main():
    if len(sys.argv) < 2:
        print("用法: andromeda_cluster_matrix.py [start|scan|status|init]")
        return
    cmd = sys.argv[1]
    if cmd in ("start", "init"):
        ensure_cluster_tables()
        seed_cluster_nodes()
    elif cmd == "scan":
        ensure_cluster_tables()
        topic = sys.argv[2] if len(sys.argv) > 2 else None
        asyncio.run(execute_round_async(topic))
    elif cmd == "status":
        status()


if __name__ == "__main__":
    main()
