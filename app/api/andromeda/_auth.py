"""
可选 API Key 认证
==================
env MTSCOS_API_KEY 未设置 → 开发模式放行 (fail-open)
设置后 → 必须 header X-API-Key 匹配
"""
import os
from functools import wraps
from flask import request, jsonify

_API_KEY = os.environ.get("MTSCOS_API_KEY", "").strip()


def require_api_key(f):
    """Decorator: 如果设置了 API Key 则校验 header X-API-Key."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _API_KEY:
            provided = request.headers.get("X-API-Key", "").strip()
            if not provided or provided != _API_KEY:
                return jsonify({"success": False, "msg": "Unauthorized",
                                "header": "X-API-Key"}), 401
        return f(*args, **kwargs)
    return wrapper


def api_key_status() -> dict:
    """公开状态: API key 是否启用 (不泄露实际 key)."""
    return {
        "auth_required": bool(_API_KEY),
        "header": "X-API-Key" if _API_KEY else None,
        "note": "Set env MTSCOS_API_KEY to enable API key protection",
    }
