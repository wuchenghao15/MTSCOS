"""
仙女座 API v1 模块化包
======================
注册: from app.api.andromeda import andromeda_v1_bp; app.register_blueprint(andromeda_v1_bp)
端点: /api/andromeda_v1/*
文档: /api/andromeda_v1/openapi.json  /api/andromeda_v1/docs (ReDoc)
旧 API: /api/andromeda/* (andromeda_api.py, 保留向后兼容)
认证:  env MTSCOS_API_KEY 设置后, 所有 POST 和 stats/teams 需要 header X-API-Key
"""
from flask import Blueprint
from .v1 import v1_bp

andromeda_v1_bp = Blueprint("andromeda_v1_root", __name__, url_prefix="/api/andromeda_v1")
andromeda_v1_bp.register_blueprint(v1_bp)

__all__ = ["andromeda_v1_bp"]
