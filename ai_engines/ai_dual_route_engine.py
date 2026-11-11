# -*- coding: utf-8 -*-
"""
三轨路由AI推理引擎 (仙女座智囊团 LLM 统一入口)
==============================================
本地 Ollama 优先（零token）→ 科大讯飞星火（国产高质量中文）→ 火山引擎云API兜底

路由策略：
1. 本地 Ollama 可用 → 本地推理（零token消耗）
2. 本地不可用 + 星火可用 → 星火中文兜底（国产大模型，中文场景质量优）
3. 前两者都不可用 + 火山引擎可用 → 豆包兜底（英文/通用场景）
4. 全部不可用 → 返回错误

场景路由（星火优势场景）：
- 中文长对话/智囊团决策 → 优先星火（中文质量好）
- 简单任务（分类/审查）→ 本地 3B 模型
- 英文/技术任务 → 本地 7B 或火山引擎
- 本地不可用 → 星火 → 火山引擎 双保险

对接：ai_local_inference_engine.py 统一入口, 仙女座 dashboard, 所有引擎
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# 引擎路径
_AI_ENGINES_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DB = os.path.join(_AI_ENGINES_DIR, "app.db")

# 确保 ai_engines 目录在 sys.path 中（兼容不同调用方式）
if _AI_ENGINES_DIR not in sys.path:
    sys.path.insert(0, _AI_ENGINES_DIR)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_APP_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_routing_table() -> None:
    """确保路由决策记录表存在"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mt_ai_routing_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flow_id TEXT,
            inference_kind TEXT,
            route_chosen TEXT,
            local_available INTEGER,
            cloud_available INTEGER,
            reason TEXT,
            duration_ms INTEGER,
            tokens_saved INTEGER,
            triggered_at TEXT
        )""")
    conn.commit()
    conn.close()


def _log_routing(flow_id: Optional[str], kind: str, route: str,
                local_ok: bool, cloud_ok: bool, reason: str,
                duration_ms: int, tokens_saved: int) -> None:
    """落库路由决策"""
    _ensure_routing_table()
    conn = _get_conn()
    conn.execute("""INSERT INTO mt_ai_routing_decisions
        (flow_id, inference_kind, route_chosen, local_available, cloud_available,
         reason, duration_ms, tokens_saved, triggered_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (flow_id, kind, route, 1 if local_ok else 0, 1 if cloud_ok else 0,
         reason, duration_ms, tokens_saved, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def route_and_chat(prompt: str, system: str = "", kind: str = "chat",
                   flow_id: Optional[str] = None,
                   prefer_local: bool = True) -> Dict[str, Any]:
    """
    三轨路由聊天 (仙女座智囊团 LLM 统一入口)

    路由链: local_ollama → spark_xunfei → volcengine_ark → none

    场景智能路由:
    - kind in ("chat", "review", "bug_analyze") + prefer_local=True → 优先本地 7B
    - kind in ("classify", "audit") + prefer_local=True → 优先本地 3B
    - 中文/智囊团决策 (kind in ("chat", "deliberate")) → 本地不可用时优先星火
    - 本地+星火都不可用 → 火山引擎兜底

    返回 {success, response, model, route, duration_ms, tokens_saved, error}
    """
    import time
    start = time.time()

    # ══════════════════════════════════════════════════════════════
    # §1 探测三个引擎可用性
    # ══════════════════════════════════════════════════════════════
    local_ok = False
    spark_ok = False
    volc_ok = False

    try:
        from ai_ollama_engine import is_available as ollama_available, chat as ollama_chat
        local_ok = ollama_available()
    except Exception:
        local_ok = False

    try:
        from ai_spark_engine import is_available as spark_available, chat as spark_chat
        spark_ok = spark_available()
    except Exception:
        spark_ok = False

    try:
        from ai_volcengine_engine import is_available as ark_available
        volc_ok = ark_available()
    except Exception:
        volc_ok = False

    # ══════════════════════════════════════════════════════════════
    # §2 路由决策 — 按场景智能选择
    # ══════════════════════════════════════════════════════════════
    route = "none"
    result: Dict[str, Any] = {
        "success": False, "response": "", "model": "", "route": "none",
        "duration_ms": 0, "tokens_saved": 0, "error": "所有推理引擎不可用"
    }

    # ─── 路径 A: prefer_local=True 且本地可用 ───
    if prefer_local and local_ok:
        route = "local_ollama"
        prefer_7b = kind in ("chat", "review", "bug_analyze", "deliberate", "research")
        result = ollama_chat(prompt, system, flow_id, prefer_7b=prefer_7b)
        result["route"] = route
        _log_routing(flow_id, kind, route, True, spark_ok or volc_ok,
                     f"本地Ollama可用{' (7b优先)' if prefer_7b else ' (3b)'}，优先本地推理（零token）",
                     int((time.time() - start) * 1000), result.get("tokens_saved", 0))

    # ─── 路径 B: 本地不可用 + 星火可用 (中文高质量) ───
    elif spark_ok:
        route = "cloud_spark"
        from ai_spark_engine import chat as spark_chat
        result = spark_chat(prompt, system, flow_id, temperature=0.5)
        result["route"] = route
        _log_routing(flow_id, kind, route, local_ok, True,
                     "本地Ollama不可用，星火中文兜底（国产大模型，中文质量优）",
                     int((time.time() - start) * 1000), 0)

    # ─── 路径 C: 前两者都不行 + 火山引擎可用 (英文/通用兜底) ───
    elif volc_ok:
        route = "cloud_volcengine"
        from ai_volcengine_engine import chat as ark_chat
        result = ark_chat(prompt, system, flow_id)
        result["route"] = route
        _log_routing(flow_id, kind, route, local_ok, spark_ok,
                     "本地+星火均不可用，火山引擎豆包兜底",
                     int((time.time() - start) * 1000), 0)

    # ─── 路径 D: prefer_local=False 但云 API 都不可用 → 回退本地 ───
    elif local_ok:
        route = "local_ollama_fallback"
        result = ollama_chat(prompt, system, flow_id)
        result["route"] = route
        _log_routing(flow_id, kind, route, True, False,
                     "云API均不可用，回退本地Ollama",
                     int((time.time() - start) * 1000), result.get("tokens_saved", 0))

    # ─── 路径 E: 全部不可用 ───
    else:
        _log_routing(flow_id, kind, "none", False, False,
                     "本地+星火+火山引擎 全部不可用",
                     int((time.time() - start) * 1000), 0)

    # 附加信息
    result["local_available"] = local_ok
    result["spark_available"] = spark_ok
    result["volcengine_available"] = volc_ok
    return result


def chat(prompt: str, system: str = "", flow_id: Optional[str] = None) -> Dict[str, Any]:
    """双轨路由聊天（统一入口）"""
    return route_and_chat(prompt, system, "chat", flow_id, prefer_local=True)


def classify(text: str, categories: List[str], flow_id: Optional[str] = None) -> Dict[str, Any]:
    """双轨路由分类"""
    system = "你是分类器，只返回类别名称，不加其他文字。"
    prompt = f"将以下文本分类到 [{', '.join(categories)}] 中的一个：\n{text}\n类别："
    result = route_and_chat(prompt, system, "classify", flow_id, prefer_local=True)
    result["kind"] = "classify"
    return result


def review(code: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
    """双轨路由代码审查"""
    system = "你是代码审查专家，检查代码质量、安全、性能问题，给出改进建议。"
    prompt = f"审查以下代码：\n```\n{code}\n```\n给出问题和建议："
    result = route_and_chat(prompt, system, "review", flow_id, prefer_local=True)
    result["kind"] = "review"
    return result


def bug_analyze(error_desc: str, code: str = "", flow_id: Optional[str] = None) -> Dict[str, Any]:
    """双轨路由Bug分析"""
    system = "你是Bug分析专家，定位根因并给出修复方案。"
    prompt = f"错误描述：{error_desc}\n相关代码：\n```\n{code}\n```\n根因分析和修复方案："
    result = route_and_chat(prompt, system, "bug_analyze", flow_id, prefer_local=True)
    result["kind"] = "bug_analyze"
    return result


def health() -> Dict[str, Any]:
    """三轨路由引擎健康状态 (仙女座智囊团 LLM 统一入口)"""
    local_ok = False
    spark_ok = False
    volc_ok = False
    local_models: List[str] = []
    spark_domain = ""
    volc_model = ""

    try:
        from ai_ollama_engine import is_available, list_models
        local_ok = is_available()
        local_models = list_models()
    except Exception:
        pass
    try:
        from ai_spark_engine import is_available as spark_available, health as spark_health
        spark_ok = spark_available()
        spark_domain = spark_health().get("domain", "")
    except Exception:
        pass
    try:
        from ai_volcengine_engine import is_available as ark_available, health as ark_health
        volc_ok = ark_available()
        volc_model = ark_health().get("model", "")
    except Exception:
        pass

    # 路由策略描述
    if local_ok:
        strategy = "三轨: local_ollama → spark_xunfei → volcengine_ark"
    elif spark_ok:
        strategy = "双轨: spark_xunfei → volcengine_ark (本地不可用)"
    elif volc_ok:
        strategy = "单轨: volcengine_ark (本地+星火不可用)"
    else:
        strategy = "离线: 全部不可用"

    return {
        "engine": "ai_dual_route_engine",
        "route_strategy": strategy,
        "primary": "local_ollama" if local_ok else ("spark_xunfei" if spark_ok else ("volcengine_ark" if volc_ok else "none")),
        "engines": {
            "local_ollama": {"available": local_ok, "models": local_models},
            "spark_xunfei": {"available": spark_ok, "domain": spark_domain, "endpoint": "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat"},
            "volcengine_ark": {"available": volc_ok, "model": volc_model},
        },
        "hw_profile": {
            "chip": "Apple M5",
            "memory_gb": 24,
            "primary_model": "qwen2.5:7b",
            "fallback_model": "qwen2.5:3b",
        },
    }
