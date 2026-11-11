# -*- coding: utf-8 -*-
"""📜 文曲星 (WENQUXING) API — 仙女座文字编辑子系统

路由前缀: /api/wqx
所有端点返回 JSON {ok: bool, data: ..., error: ...}
"""
from __future__ import annotations
import sys, os, json, threading
from flask import Blueprint, request, jsonify, current_app

wqx_api = Blueprint("wqx_api", __name__, url_prefix="/api/wqx")

# 延迟导入引擎 (避免 Flask app 初始化循环)
_engine = None
_engine_lock = threading.Lock()

def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engines"))
                from ai_wenquxing_engine import WenquxingEngine, MODELS
                _engine = WenquxingEngine()
    return _engine

# ─── 元信息 ────────────────────────────────────────────────
@wqx_api.route("/modes", methods=["GET"])
def list_modes():
    """列出 7 种编辑模式"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engines"))
    from ai_wenquxing_engine import MODELS, _OLLAMA_PORT, OLLAMA_WRITER_MODEL
    return jsonify({
        "ok": True,
        "data": {
            "ollama_port": _OLLAMA_PORT,
            "ollama_model": OLLAMA_WRITER_MODEL,
            "modes": [{"key": k, **{kk:vv for kk,vv in v.items() if kk!="prompt"}} 
                      for k, v in MODELS.items()]
        }
    })


# ─── 生成 (异步) ───────────────────────────────────────────
_tasks = {}  # task_id → {"status", "result", "error"}
def _async_generate(task_id, mode, topic, audience, style, words):
    try:
        eng = _get_engine()
        _tasks[task_id] = {"status": "running"}
        tid = eng.write(mode, topic, audience, style, words)
        task = eng.get_task(tid)
        _tasks[task_id] = {"status": "done", "result": task}
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e)}


@wqx_api.route("/generate", methods=["POST"])
def generate():
    """触发一次文字编辑 (异步, 立即返回 task_id)
    
    JSON body:
      mode: copy | rewrite | outline | longform | proofread | polish | transform
      topic: str (主题或原文)
      audience: str (default "技术读者")
      style: str (default "专业客观")
      words: int (default 1500)
      async: bool (default true, 如果 false 则同步等待)
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "copy")
    topic = body.get("topic", "")
    if not topic:
        return jsonify({"ok": False, "error": "topic 不能为空"}), 400
    audience = body.get("audience", "技术读者")
    style = body.get("style", "专业客观")
    words = int(body.get("words", 1500))
    async_mode = body.get("async", True)

    import uuid
    task_id = f"wqx_api_{uuid.uuid4().hex[:10]}"

    if async_mode:
        t = threading.Thread(target=_async_generate,
                             args=(task_id, mode, topic, audience, style, words),
                             daemon=True)
        t.start()
        return jsonify({
            "ok": True, "task_id": task_id, "status": "running",
            "endpoint": f"/api/wqx/status/{task_id}"
        })
    else:
        eng = _get_engine()
        real_id = eng.write(mode, topic, audience, style, words)
        task = eng.get_task(real_id)
        task["final_text_preview"] = (task.get("final_text") or "")[:300]
        return jsonify({"ok": True, "task": task})


@wqx_api.route("/status/<task_id>", methods=["GET"])
def check_status(task_id):
    """查询异步任务状态"""
    info = _tasks.get(task_id)
    if not info:
        # 可能是历史 task_id, 查 DB
        eng = _get_engine()
        task = eng.get_task(task_id)
        if task:
            return jsonify({"ok": True, "status": task.get("status"), "task": task})
        return jsonify({"ok": False, "error": "task 不存在"}), 404
    if info["status"] == "done":
        t = info["result"]
        t["final_text_preview"] = (t.get("final_text") or "")[:300]
    return jsonify({"ok": True, "status": info["status"], 
                    "task": info.get("result"), "error": info.get("error")})


# ─── 任务查询 ─────────────────────────────────────────────
@wqx_api.route("/task/<task_id>", methods=["GET"])
def get_task(task_id):
    """获取 task 详情 + 完整 final_text"""
    eng = _get_engine()
    task = eng.get_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "task": task})


@wqx_api.route("/tasks", methods=["GET"])
def list_tasks():
    """列出最近 N 个 task
    Query: limit=20, mode=copy
    """
    limit = int(request.args.get("limit", 20))
    mode = request.args.get("mode")
    eng = _get_engine()
    tasks = eng.list_tasks(limit, mode)
    # 返回列表去掉 final_text (太长)
    brief = [{k: v for k, v in t.items() if k != "final_text"} for t in tasks]
    return jsonify({"ok": True, "total": len(brief), "tasks": brief})


# ─── artifact 文件访问 ────────────────────────────────────
@wqx_api.route("/artifact/<task_id>", methods=["GET"])
def get_artifact(task_id):
    """直接返回 artifact .md 文件内容"""
    project_root = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.join(project_root, "static", "wenquxing_artifacts", f"{task_id}.md")
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "artifact not found"}), 404
    with open(path, encoding="utf-8") as f:
        text = f.read()
    import mimetypes
    return text, 200, {"Content-Type": "text/markdown; charset=utf-8"}
