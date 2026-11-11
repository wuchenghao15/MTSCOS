"""
iceberg/workflows.py — 冰山系统域工作流整合
==============================================

整合 8 个 iceberg_* 模块的核心能力到去中心化 workflow_registry.

冰山系统 (安全合规 6 大自动能力):
  🛡️ wf_iceberg_upgrade          → 规则版本自动升级
  🧱 wf_iceberg_ops              → 防火墙/违规巡检 + 审计压缩
  🧬 wf_iceberg_derive           → Q5 自动生成新规则 (从违规案例)
  💪 wf_iceberg_strengthen       → 弱约束词强化 + 规则学习
  🔭 wf_iceberg_expand           → 违规模式 → 新规则入库
  🔬 wf_iceberg_research         → Q5 研究新威胁/新绕过手法

子模块能力桥接:
  🤝 wf_iceberg_handshake        → AI 节点握手引擎 (Flask blueprint)
  📚 wf_iceberg_qbank_adaptive   → 自适应题库生成 (初中/高中/大学)
  🌐 wf_iceberg_content_matrix   → 多语内容矩阵查询/同步
  🎨 wf_iceberg_slang_substitute → 网络语/黑话替换 (内容审核)
  🤖 wf_iceberg_arduino_ai       → Arduino AI 代码生成/编译修复
  🧠 wf_iceberg_consciousness    → 冰山意识脉冲/域统计
  📐 wf_iceberg_meta_model       → 绑定矩阵/域统计
"""
# [unused] import os, sys, json, sqlite3, time, subprocess, importlib.util


def _get_app_db():
    prod = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
    for k in ("ANDROMEDA_DB", "APP_DB"):
        v = os.environ.get(k)
        if v and os.path.exists(v) and os.path.getsize(v) > 1_000_000:
            return v
    if os.path.exists(prod) and os.path.getsize(prod) > 1_000_000:
        return prod
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "database", "app.db"))


def _iceberg_import(module_name: str):
    """惰性 import iceberg 子模块 (避免一次性加载 240KB)."""
    mod_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", f"{module_name}.py"))
    if not os.path.exists(mod_path):
        return None
    try:
        spec = importlib.util.spec_from_file_location(module_name, mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"[iceberg.workflows] import {module_name} fail: {e}")
        return None


# ── 6 大自动能力 (iceberg_command.py loop 代理) ──

def _run_iceberg_loop(loop_name: str, db_path: str) -> dict:
    """代理 iceberg_command.py 的 _loop_* 函数."""
    mod = _iceberg_import("iceberg_command")
    if not mod:
        return {"status": "FAILED", "error": "iceberg_command.py not found", "wall_ms": 0, "output": {}}
    loop_fn = getattr(mod, f"_loop_{loop_name}", None)
    if not loop_fn:
        return {"status": "FAILED", "error": f"_loop_{loop_name} not found", "wall_ms": 0, "output": {}}
    t0 = time.time()
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        result = loop_fn(conn)
        conn.close()
        return {"status": "SUCCESS", "output": result or {},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_iceberg_upgrade(input):
    return _run_iceberg_loop("upgrade", _get_app_db())

def _h_iceberg_ops(input):
    return _run_iceberg_loop("ops", _get_app_db())

def _h_iceberg_derive(input):
    return _run_iceberg_loop("derive", _get_app_db())

def _h_iceberg_strengthen(input):
    return _run_iceberg_loop("strengthen", _get_app_db())

def _h_iceberg_expand(input):
    return _run_iceberg_loop("expand", _get_app_db())

def _h_iceberg_research(input):
    return _run_iceberg_loop("research", _get_app_db())


# ── 子模块桥接 (高价值能力) ──

def _h_handshake(input):
    """wf_iceberg_handshake — AI 节点握手状态查询."""
    mod = _iceberg_import("iceberg_handshake")
    t0 = time.time()
    if not mod:
        return {"status": "FAILED", "error": "iceberg_handshake not found", "wall_ms": 0, "output": {}}
    try:
        eng = mod.get_handshake_engine()
        status = eng.status() if hasattr(eng, 'status') else {}
        return {"status": "SUCCESS", "output": status,
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_qbank_adaptive(input):
    """wf_iceberg_qbank_adaptive — 自适应题库生成."""
    subject = input.get("subject", "数学")
    count = max(1, min(50, int(input.get("count", 5))))
    difficulty = max(1, min(5, int(input.get("difficulty", 3))))
    t0 = time.time()
    mod = _iceberg_import("iceberg_qbank_adaptive")
    if not mod:
        return {"status": "FAILED", "error": "iceberg_qbank_adaptive not found", "wall_ms": 0, "output": {}}
    try:
        conn = sqlite3.connect(_get_app_db(), timeout=30)
        questions = mod.q5_generate_questions(conn, subject, count, difficulty)
        conn.close()
        return {"status": "SUCCESS", "output": {"questions": questions, "count": len(questions),
                                                  "subject": subject, "difficulty": difficulty},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_slang_substitute(input):
    """wf_iceberg_slang_substitute — 网络语替换."""
    text = input.get("text", "")[:4000]
    t0 = time.time()
    mod = _iceberg_import("iceberg_slang_substitution")
    if not mod:
        return {"status": "FAILED", "error": "iceberg_slang_substitution not found", "wall_ms": 0, "output": {}}
    try:
        conn = sqlite3.connect(_get_app_db(), timeout=15)
        result = mod.substitute(text, db=conn)
        conn.close()
        return {"status": "SUCCESS", "output": {"original": text[:200], "substituted": result[:200] if result else text[:200]},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_arduino_ai(input):
    """wf_iceberg_arduino_ai — Arduino AI 代码生成."""
    prompt = input.get("prompt", "")[:1000]
    board = input.get("board", "UNO")
    t0 = time.time()
    mod = _iceberg_import("iceberg_arduino_ai")
    if not mod:
        return {"status": "FAILED", "error": "iceberg_arduino_ai not found", "wall_ms": 0, "output": {}}
    try:
        result = mod.ai_generate_code(prompt, board=board)
        return {"status": "SUCCESS", "output": result,
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_consciousness(input):
    """wf_iceberg_consciousness — 冰山意识脉冲 + 域统计."""
    mod = _iceberg_import("iceberg_consciousness")
    t0 = time.time()
    if not mod:
        return {"status": "FAILED", "error": "iceberg_consciousness not found", "wall_ms": 0, "output": {}}
    try:
        pulse = mod.IcebergConsciousness.pulse() if hasattr(mod, 'IcebergConsciousness') else {}
        return {"status": "SUCCESS", "output": pulse,
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ── 注册入口 ──

def register_workflows(registry, register_fn):
    """冰山系统域 — 6 大自动能力 + 7 子模块桥接."""
    # 6 大自动能力
    register_fn("wf_iceberg_upgrade", {
        "name": "冰山自动升级", "domain": "iceberg",
        "description": "规则版本自动升级 + 一致性校验",
        "price_per_unit": 0.10, "pricing_unit": "run",
        "handler": _h_iceberg_upgrade, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["iceberg", "upgrade", "compliance"],
    })
    register_fn("wf_iceberg_ops", {
        "name": "冰山自动运维", "domain": "iceberg",
        "description": "防火墙规则巡检 + 违规清理 + 审计日志压缩",
        "price_per_unit": 0.05, "pricing_unit": "run",
        "handler": _h_iceberg_ops, "requires": ["PROD_DB"],
        "tags": ["iceberg", "ops", "audit"],
    })
    register_fn("wf_iceberg_derive", {
        "name": "冰山自动衍生", "domain": "iceberg",
        "description": "Q5 从违规案例自动生成新规则",
        "price_per_unit": 0.20, "pricing_unit": "rule",
        "handler": _h_iceberg_derive, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["iceberg", "derive", "rule_gen"],
    })
    register_fn("wf_iceberg_strengthen", {
        "name": "冰山自动强化", "domain": "iceberg",
        "description": "弱约束词强化 + 规则自动学习",
        "price_per_unit": 0.15, "pricing_unit": "run",
        "handler": _h_iceberg_strengthen, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["iceberg", "strengthen", "enforce"],
    })
    register_fn("wf_iceberg_expand", {
        "name": "冰山自动拓展", "domain": "iceberg",
        "description": "违规模式 → 新规则自动入库 → 自动部署",
        "price_per_unit": 0.20, "pricing_unit": "rule",
        "handler": _h_iceberg_expand, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["iceberg", "expand", "deploy"],
    })
    register_fn("wf_iceberg_research", {
        "name": "冰山自动研究", "domain": "iceberg",
        "description": "Q5 研究新威胁 / 新绕过手法 / 新合规风险",
        "price_per_unit": 0.50, "pricing_unit": "research",
        "handler": _h_iceberg_research, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["iceberg", "research", "threat"],
    })
    # 子模块桥接
    register_fn("wf_iceberg_handshake", {
        "name": "AI 节点握手", "domain": "iceberg",
        "description": "iceberg_handshake 引擎状态查询 (Flask blueprint)",
        "price_per_unit": 0.005, "pricing_unit": "status",
        "handler": _h_handshake, "requires": ["PROD_DB"],
        "tags": ["iceberg", "handshake", "network"],
    })
    register_fn("wf_iceberg_qbank_adaptive", {
        "name": "自适应题库生成", "domain": "iceberg",
        "description": "Q5 本地 Ollama 自适应难度题库生成",
        "price_per_unit": 0.05, "pricing_unit": "question",
        "handler": _h_qbank_adaptive, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["iceberg", "qbank", "education"],
    })
    register_fn("wf_iceberg_slang_substitute", {
        "name": "网络语替换", "domain": "iceberg",
        "description": "内容安全审核: 黑话/网络语 → 合规表述",
        "price_per_unit": 0.02, "pricing_unit": "1K chars",
        "handler": _h_slang_substitute, "requires": ["PROD_DB"],
        "tags": ["iceberg", "content_safety", "substitute"],
    })
    register_fn("wf_iceberg_arduino_ai", {
        "name": "Arduino AI 代码", "domain": "iceberg",
        "description": "Arduino 开发板 AI 代码生成 + 编译修复",
        "price_per_unit": 0.30, "pricing_unit": "sketch",
        "handler": _h_arduino_ai, "requires": ["OLLAMA"],
        "tags": ["iceberg", "arduino", "iot"],
    })
    register_fn("wf_iceberg_consciousness", {
        "name": "冰山意识脉冲", "domain": "iceberg",
        "description": "IcebergConsciousness.pulse() + 域统计",
        "price_per_unit": 0.001, "pricing_unit": "pulse",
        "handler": _h_consciousness, "requires": ["PROD_DB"],
        "tags": ["iceberg", "consciousness", "meta"],
    })
