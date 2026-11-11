#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 AI Meta-Cognition Blueprint — /api/ai-meta/*
═══════════════════════════════════════════════════════════════════
AI 元认知能力 REST API 层

Endpoints:
  GET  /api/ai-meta/capabilities           AI 完整能力目录
  GET  /api/ai-meta/capabilities/score     AI 能力画像
  GET  /api/ai-meta/capabilities/refresh   刷新能力目录 (重建)
  POST /api/ai-meta/route                  AI 选引擎 (route_task)
  POST /api/ai-meta/compose                AI 组合工作流
  POST /api/ai-meta/workflow/execute       AI 执行工作流
  GET  /api/ai-meta/workflows              工作流历史
  GET  /api/ai-meta/experience             AI 经验库
  POST /api/ai-meta/experience/recall      AI 相似经验召回
  POST /api/ai-meta/experience/distill     提炼新经验
  GET  /api/ai-meta/cycles                 元认知周期历史
  GET  /api/ai-meta/router/decisions       路由器决策历史
  POST /api/ai-meta/full-cycle             运行完整元认知周期
  GET  /api/ai-meta/health                 元认知引擎健康状态
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from flask import Blueprint, jsonify, request

from app.db import DB_PATH, connect as _db

log = logging.getLogger("ai_meta_bp")

ai_meta_bp = Blueprint('ai_meta', __name__, url_prefix='/api/ai-meta')


def _get_aimc():
    """延迟导入 AIMetaCognition (避免循环依赖)"""
    from engines.ai_meta_cognition import AIMetaCognition
    return AIMetaCognition(DB_PATH)


def _ok(data=None, msg="ok"):
    resp = {"status": "ok", "message": msg, "timestamp": datetime.now().isoformat()}
    if data is not None:
        resp["data"] = data
    return jsonify(resp)


def _err(msg, code=400):
    return jsonify({"status": "error", "message": msg}), code


# ════════════════════════════════════════════════════════════════════
# ① Capabilities — AI 能力目录
# ════════════════════════════════════════════════════════════════════

@ai_meta_bp.route('/capabilities', methods=['GET'])
def list_capabilities():
    """AI 完整能力目录"""
    category = request.args.get('category')
    name = request.args.get('name')
    limit = int(request.args.get('limit', 500))
    
    aimc = _get_aimc()
    items = aimc.list_my_abilities(filter_category=category, filter_name=name)
    
    # 限制返回条数
    items = items[:limit]
    
    return _ok({
        "total": len(items),
        "capabilities": items,
    })


@ai_meta_bp.route('/capabilities/score', methods=['GET'])
def capability_score():
    """AI 能力画像 — 按维度打分"""
    aimc = _get_aimc()
    score = aimc.capability_score()
    
    # 格式化显示数据
    bars = {}
    for dim, val in sorted(score.items(), key=lambda x: -x[1]):
        bar = "█" * int(val / 5) + "░" * (20 - int(val / 5))
        bars[dim] = {"score": val, "bar": bar}
    
    return _ok({
        "scores": score,
        "bars": bars,
        "avg_score": round(sum(score.values()) / len(score), 1) if score else 0,
    })


@ai_meta_bp.route('/capabilities/refresh', methods=['GET', 'POST'])
def refresh_capabilities():
    """刷新能力目录 (重新扫描)"""
    aimc = _get_aimc()
    start = time.time()
    reg = aimc.build_meta_registry()
    elapsed = round((time.time() - start) * 1000, 1)
    
    return _ok({
        "stats": reg.get("stats", {}),
        "build_time_ms": elapsed,
    }, msg=f"刷新完成: {reg.get('stats', {}).get('engines', 0)} engines")


# ════════════════════════════════════════════════════════════════════
# ② Skill Router — AI 选引擎
# ════════════════════════════════════════════════════════════════════

@ai_meta_bp.route('/route', methods=['POST'])
def route_task():
    """AI 选引擎处理任务"""
    body = request.get_json(force=True, silent=True) or {}
    task = body.get('task') or request.args.get('task')
    context = body.get('context') or {}
    
    if not task:
        return _err("缺少 task 参数")
    
    aimc = _get_aimc()
    result = aimc.route_task(task, context=context)
    
    return _ok(result)


# ════════════════════════════════════════════════════════════════════
# ③ Composer — AI 组合工作流
# ════════════════════════════════════════════════════════════════════

@ai_meta_bp.route('/compose', methods=['POST'])
def compose_workflow():
    """AI 组合多引擎工作流"""
    body = request.get_json(force=True, silent=True) or {}
    task = body.get('task') or request.args.get('task')
    
    if not task:
        return _err("缺少 task 参数")
    
    aimc = _get_aimc()
    wf = aimc.compose_workflow(task)
    
    return _ok(wf)


@ai_meta_bp.route('/workflow/execute', methods=['POST'])
def execute_workflow():
    """AI 执行工作流"""
    body = request.get_json(force=True, silent=True) or {}
    workflow_id = body.get('workflow_id')
    workflow = body.get('workflow')
    
    # 支持传入 workflow_id 从数据库读取
    if workflow_id and not workflow:
        conn = _db(readonly=True)
        try:
            row = conn.execute("SELECT * FROM mt_ai_workflow WHERE workflow_id=?", (workflow_id,)).fetchone()
            if row:
                workflow = {
                    "workflow_id": row["workflow_id"],
                    "task_template": row["task_template"],
                    "steps": json.loads(row["steps"]),
                    "dag_graph": json.loads(row["dag_graph"]) if row["dag_graph"] else None,
                }
            else:
                return _err(f"workflow {workflow_id} 不存在", 404)
        finally:
            conn.close()
    
    if not workflow:
        return _err("缺少 workflow 或 workflow_id")
    
    aimc = _get_aimc()
    result = aimc.execute_workflow(workflow)
    
    return _ok(result)


@ai_meta_bp.route('/workflows', methods=['GET'])
def list_workflows():
    """工作流历史"""
    limit = int(request.args.get('limit', 50))
    
    conn = _db(readonly=True)
    try:
        rows = conn.execute("""
            SELECT workflow_id, task_template, steps, created_at, last_executed,
                   execution_count, avg_duration_ms, success_rate
            FROM mt_ai_workflow
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        workflows = []
        for r in rows:
            workflows.append({
                "workflow_id": r["workflow_id"],
                "task_template": r["task_template"],
                "total_steps": len(json.loads(r["steps"] or "[]")),
                "created_at": r["created_at"],
                "last_executed": r["last_executed"],
                "execution_count": r["execution_count"],
                "avg_duration_ms": r["avg_duration_ms"],
                "success_rate": r["success_rate"],
            })
        
        return _ok({"total": len(workflows), "workflows": workflows})
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════
# ④ Experience Memory — AI 经验库
# ════════════════════════════════════════════════════════════════════

@ai_meta_bp.route('/experience', methods=['GET'])
def list_experience():
    """AI 经验库"""
    snippet_type = request.args.get('type')  # SUCCESS_PATTERN / FAILURE_LESSON / INSPIRATION
    domain = request.args.get('domain')
    limit = int(request.args.get('limit', 100))
    
    conn = _db(readonly=True)
    try:
        sql = "SELECT * FROM mt_ai_experience_snippet WHERE 1=1"
        params = []
        if snippet_type:
            sql += " AND snippet_type=?"
            params.append(snippet_type)
        if domain:
            sql += " AND domain=?"
            params.append(domain)
        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)
        
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        
        # 统计
        stats_row = conn.execute("""
            SELECT snippet_type, COUNT(*) as cnt 
            FROM mt_ai_experience_snippet 
            GROUP BY snippet_type
        """).fetchall()
        stats = {r["snippet_type"]: r["cnt"] for r in stats_row}
        
        snippets = []
        for r in rows:
            snippets.append(dict(r))
        
        return _ok({
            "total": len(snippets),
            "snippets": snippets,
            "stats": stats,
        })
    finally:
        conn.close()


@ai_meta_bp.route('/experience/distill', methods=['POST'])
def distill_experience():
    """提炼新经验"""
    body = request.get_json(force=True, silent=True) or {}
    days = int(body.get('days', request.args.get('days', 7)))
    
    aimc = _get_aimc()
    exp = aimc.distill_experience(days=days)
    
    return _ok({
        "days": days,
        "success_patterns": len(exp.get("success_patterns", [])),
        "failure_lessons": len(exp.get("failure_lessons", [])),
        "insights": exp.get("insights", []),
        "duration_ms": exp.get("duration_ms", 0),
    })


@ai_meta_bp.route('/experience/recall', methods=['POST'])
def recall_similar():
    """AI 相似经验召回"""
    body = request.get_json(force=True, silent=True) or {}
    task = body.get('task') or request.args.get('task')
    top_k = int(body.get('top_k', request.args.get('top_k', 3)))
    
    if not task:
        return _err("缺少 task 参数")
    
    aimc = _get_aimc()
    results = aimc.recall_similar(task, top_k=top_k)
    
    return _ok({
        "task": task,
        "results": results,
        "count": len(results),
    })


# ════════════════════════════════════════════════════════════════════
# ⑤ Meta Cycles — 元认知周期历史
# ════════════════════════════════════════════════════════════════════

@ai_meta_bp.route('/cycles', methods=['GET'])
def list_meta_cycles():
    """元认知周期历史"""
    limit = int(request.args.get('limit', 30))
    
    conn = _db(readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM mt_ai_meta_cycle
            ORDER BY cycle_time DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        cycles = [dict(r) for r in rows]
        
        # 计算平均 meta_score
        avg_score = 0
        if cycles:
            scores = [c.get("meta_score", 0) for c in cycles if c.get("meta_score", 0) > 0]
            avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        
        return _ok({
            "total": len(cycles),
            "cycles": cycles,
            "avg_meta_score": avg_score,
        })
    finally:
        conn.close()


@ai_meta_bp.route('/router/decisions', methods=['GET'])
def list_route_decisions():
    """路由器决策历史"""
    limit = int(request.args.get('limit', 50))
    
    conn = _db(readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT route_id, task, selected_engines, reasoning, confidence,
                   fallback_used, execution_duration_ms, created_at
            FROM mt_ai_route_decision
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        decisions = []
        for r in rows:
            d = dict(r)
            try:
                d["selected_engines"] = json.loads(d["selected_engines"] or "[]")
            except Exception:
                d["selected_engines"] = []
            decisions.append(d)
        
        # 统计
        total = conn.execute("SELECT COUNT(*) FROM mt_ai_route_decision").fetchone()[0]
        ollama_pct = 0
        if total > 0:
            ollama_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_ai_route_decision WHERE fallback_used=0"
            ).fetchone()[0]
            ollama_pct = round(ollama_cnt / total * 100, 1)
        
        return _ok({
            "total": total,
            "ollama_percent": ollama_pct,
            "decisions": decisions,
        })
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════
# 🎯 Full Cycle + Health
# ════════════════════════════════════════════════════════════════════

@ai_meta_bp.route('/full-cycle', methods=['POST'])
def run_full_cycle():
    """运行完整元认知周期"""
    aimc = _get_aimc()
    result = aimc.run_full_meta_cycle()
    
    return _ok(result)


@ai_meta_bp.route('/health', methods=['GET'])
def meta_health():
    """元认知引擎健康状态"""
    import urllib.request
    
    # 检查 Ollama
    ollama_up = False
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            ollama_up = resp.status == 200
    except Exception:
        pass
    
    # 检查核心表
    conn = _db(readonly=True)
    table_status = {}
    try:
        for t in ['mt_ai_capability_registry', 'mt_ai_route_decision', 
                  'mt_ai_workflow', 'mt_ai_experience_snippet', 'mt_ai_meta_cycle']:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                table_status[t] = {"exists": True, "rows": cnt}
            except Exception:
                table_status[t] = {"exists": False, "rows": 0}
    finally:
        conn.close()
    
    # 最近一次 cycle
    last_cycle = None
    try:
        conn = _db(readonly=True)
        row = conn.execute("""
            SELECT cycle_time, meta_score, total_duration_ms 
            FROM mt_ai_meta_cycle ORDER BY cycle_time DESC LIMIT 1
        """).fetchone()
        if row:
            last_cycle = {"time": row[0], "meta_score": row[1], "duration_ms": row[2]}
        conn.close()
    except Exception:
        pass
    
    return _ok({
        "engine": "AIMetaCognition",
        "ollama_up": ollama_up,
        "tables": table_status,
        "last_cycle": last_cycle,
        "status": "healthy" if ollama_up else "degraded",
    })
