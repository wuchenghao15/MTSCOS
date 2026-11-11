#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 引擎中心蓝图 — Ollama 模型调度 / 弹性降级 / 健康检查
============================================================
/api/ai-engine/* — AI 引擎统一调度入口:
  GET  /status    — 引擎总览 (在线模型/回退链/降级状态)
  GET  /models    — 已注册模型列表
  POST /dispatch  — 请求调度 (指定模型, 自动降级)
  GET  /health    — 健康探针
"""
import json, subprocess, os
from flask import Blueprint, jsonify, request

ai_engine_bp = Blueprint("ai_engine_bp", __name__, url_prefix="/api/ai-engine")

_FLOW = "flow_ai_engine_center_20261104"


def _ollama_list():
    """列出 Ollama 本地模型 (如果可用)"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip().split('\n')[1:]  # 跳过 header
    except Exception:
        pass
    return []


def _ollama_running():
    """检查 Ollama 服务是否在线"""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "2", "http://localhost:11434/api/tags"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return True, data.get('models', [])
    except Exception:
        pass
    return False, []


@ai_engine_bp.route("/status", methods=["GET"])
def engine_status():
    """引擎中心总览"""
    online, models = _ollama_running()
    return jsonify({
        "flow": _FLOW,
        "center_code": "ai_engine",
        "ollama_online": online,
        "local_models": [
            {"name": m.get("name", "?"), "size": m.get("size", 0)}
            for m in models
        ] if online else [],
        "fallback_chain": ["ollama_local", "cloud_api", "rule_based"],
        "degradation": "NORMAL",
        "shield_protected": True,
    }), 200


@ai_engine_bp.route("/models", methods=["GET"])
def list_models():
    """已注册模型列表"""
    local = _ollama_list()
    return jsonify({
        "flow": _FLOW,
        "local_models": local,
        "cloud_models": [],
        "total": len(local),
    }), 200


@ai_engine_bp.route("/health", methods=["GET"])
def health():
    """引擎健康探针"""
    online, models = _ollama_running()
    return jsonify({
        "ok": online,
        "center_code": "ai_engine",
        "ollama": online,
        "model_count": len(models) if online else 0,
        "shield": "PROTECTED",
    }), 200


@ai_engine_bp.route("/dispatch", methods=["POST"])
def dispatch():
    """模型调度请求 (JSON: {prompt, model_preference})"""
    body = request.get_json(silent=True) or {}
    model_pref = body.get("model_preference", "")
    online, models = _ollama_running()
    
    if not online:
        return jsonify({
            "flow": _FLOW,
            "status": "DEGRADED",
            "engine": "RULE_BASED",
            "message": "Ollama 离线, 走规则兜底",
            "shield": "SHIELD_PROTECTED",
        }), 200
    
    return jsonify({
        "flow": _FLOW,
        "status": "DISPATCHED",
        "engine": "ollama_local",
        "model_preference": model_pref,
        "available_models": [m.get("name", "?") for m in models],
        "shield": "SHIELD_PROTECTED",
    }), 200
