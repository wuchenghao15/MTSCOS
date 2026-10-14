"""v1 subpackage — 仙女座 API v1 四个领域模块"""
from flask import Blueprint
from .._auth import api_key_status
from .._openapi import register_openapi
from . import core, teams, hire, invite

v1_bp = Blueprint("andromeda_v1", __name__, url_prefix="/v1")

# ── 子路由挂载 ──
v1_bp.register_blueprint(core.bp)     # /v1/core/*
v1_bp.register_blueprint(teams.bp)    # /v1/teams/*
v1_bp.register_blueprint(hire.bp)      # /v1/hire/*
v1_bp.register_blueprint(invite.bp)    # /v1/invite/*

# ── 认证状态 + OpenAPI ──
@v1_bp.route("/auth/status", methods=["GET"], endpoint="andromeda_v1_auth_status")
def auth_status():
    from flask import jsonify
    return jsonify({"success": True, "auth": api_key_status()})

register_openapi(v1_bp)
