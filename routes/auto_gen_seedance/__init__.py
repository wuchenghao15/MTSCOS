"""auto_gen_seedance: Seedance 视频生成 REST API Blueprint
URL prefix: /api/seedance
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from flask import Blueprint, request, jsonify

bp = Blueprint("auto_gen_seedance", __name__, url_prefix="/api/seedance")

_client = None


def _get_client():
    global _client
    if _client is None:
        from engines.auto_gen_seedance.client import SeedanceClient
        _client = SeedanceClient()
    return _client


@bp.route("/health", methods=["GET"])
def health():
    c = _get_client()
    return jsonify(c.health())


@bp.route("/generate", methods=["POST"])
def generate():
    """POST /api/seedance/generate
    JSON: {
      "prompt": "第一人称视角的果茶广告...",
      "refs": [{"type":"image_url","image_url":{"url":"..."},"role":"reference_image"}],
      "ratio": "16:9", "duration": 5, "generate_audio": false
    }
    """
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"success": False, "error": "prompt is required"}), 400
    c = _get_client()
    refs = data.get("refs")
    result = c.generate(
        prompt, refs=refs,
        ratio=data.get("ratio", "16:9"),
        duration=int(data.get("duration", 5)),
        generate_audio=bool(data.get("generate_audio", False)),
    )
    return jsonify(result), 200 if result.get("success") else 500


@bp.route("/task/<task_id>", methods=["GET"])
def task(task_id):
    c = _get_client()
    resp = c._get(f"/contents/generations/tasks/{task_id}")
    return jsonify(resp)


@bp.route("/quick", methods=["POST"])
def quick():
    """提交 + 轮询 (同步等待, 最多 120s)"""
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"success": False, "error": "prompt is required"}), 400
    c = _get_client()
    result = c.quick_generate(
        prompt,
        refs=data.get("refs"),
        ratio=data.get("ratio", "16:9"),
        duration=int(data.get("duration", 5)),
        generate_audio=bool(data.get("generate_audio", False)),
    )
    return jsonify(result)
