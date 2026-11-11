"""auto_gen_gateway v6.0 - 统一 API 网关 Blueprint"""
from flask import Blueprint, jsonify

bp = Blueprint("auto_api_gateway", __name__, url_prefix="/api/v1")

@bp.route("/health")
def health():
    return jsonify(status="ok", service="auto_gen_gateway")

@bp.route("/rate-limited")
def rate_limited():
    """速率限制演示 - 未来接 slowapi"""
    return jsonify(status="ok", note="rate_limited_ready")

__all__ = ["bp"]
