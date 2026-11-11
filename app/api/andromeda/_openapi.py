"""
andromeda v1 OpenAPI 3.0 文档 (自动生成 + redoc UI)
======================================================
GET /openapi.json  — OpenAPI 3.0 JSON 描述
GET /docs          — ReDoc 交互式文档页 (HTML, 零依赖)
"""
from flask import jsonify, Blueprint, request

_openapi = {
    "openapi": "3.0.3",
    "info": {
        "title": "Andromeda API v1",
        "version": "1.0.0",
        "description": (
            "仙女座模块化 API — AI 天团 / AI 员工 / 演化引擎 / EigenFlux 邀请 / Hire 触发.\n\n"
            "## 认证\n"
            "开发模式默认放行; 生产请设置环境变量 `MTSCOS_API_KEY`, 然后请求加 header `X-API-Key`.\n\n"
            "## 通用返回\n"
            "所有端点返回 `{success, generated_at, ...业务字段...}`; 错误带 `code` 字段."
        ),
    },
    "servers": [{"url": "/api/andromeda_v1", "description": "Default (same origin)"}],
    "security": [{"X-API-Key": []}],
    "components": {
        "securitySchemes": {
            "X-API-Key": {
                "type": "apiKey", "in": "header", "name": "X-API-Key",
                "description": "Optional — enabled when env MTSCOS_API_KEY is set",
            }
        }
    },
    "paths": {
        "/v1/auth/status": {"GET": {"summary": "API 认证状态",
          "responses": {"200": {"description": "auth_required + header"}}}},
        # ── Core ──
        "/v1/core/stats": {"GET": {"summary": "核心仪表盘全量数据 (evolution + db_tables + daemons + infra)",
          "responses": {"200": {"description": "andromeda_status + db_tables + evolution"}}}},
        "/v1/core/health": {"GET": {"summary": "快速健康检查 (给前端 badge)",
          "responses": {"200": {"description": "ok + ollama_alive + mini_alive"}}}},
        "/v1/core/trigger": {"POST": {"summary": "手动触发一轮演化 (异步)",
          "parameters": [{"name": "reason", "in": "query", "schema": {"type": "string"}}],
          "responses": {"200": {"description": "thread_started + estimated_s"}}}},
        "/v1/core/knowledge": {"GET": {"summary": "知识量快照 (messages + brain + graph + cycle 24h 增量)",
          "responses": {"200": {"description": "dev_snapshot"}}}},
        # ── Teams ──
        "/v1/teams/all": {"GET": {"summary": "全部 AI 天团 + 成员 (SVG 银河用)",
          "responses": {"200": {"description": "total_members + teams[]"}}}},
        "/v1/teams/employees": {"GET": {"summary": "AI 员工全景 (来源分布 + 最近 20)",
          "responses": {"200": {"description": "totals + source_distribution + recent"}}}},
        "/v1/teams/registry": {"GET": {"summary": "仙女座 33K+ 员工库统计",
          "responses": {"200": {"description": "level/source distribution + high_level_samples"}}}},
        # ── Hire ──
        "/v1/hire/trigger": {"POST": {"summary": "仙女座桥接 → auto_hire → EigenFlux 邀请 (异步)",
          "requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {
              "max_andromeda": {"type": "integer", "default": 30},
              "min_level": {"type": "integer", "default": 7}}}}}},
          "responses": {"200": {"description": "thread_started"}}}},
        "/v1/hire/pending": {"GET": {"summary": "EigenFlux 待邀请队列",
          "responses": {"200": {"description": "status_distribution + pending_list"}}}},
        # ── Invite ──
        "/v1/invite/status": {"GET": {"summary": "邀请状态跟踪 (mt_eigenflux_invite_log)",
          "responses": {"200": {"description": "status/source distribution + retry_summary + recent"}}}},
        "/v1/invite/batch": {"POST": {"summary": "批量邀请 (同步, 秒级)",
          "requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {
              "count": {"type": "integer", "default": 5},
              "domain": {"type": "string"},
              "source": {"type": "string", "default": "SA_BATCH_INVITE"}}}}}},
          "responses": {"200": {"description": "result"}}}},
        "/v1/invite/retry": {"POST": {"summary": "邀请重试 (非 ACCEPTED + 未达上限)",
          "requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {
              "max_retry": {"type": "integer", "default": 3}}}}}},
          "responses": {"200": {"description": "result"}}}},
        "/v1/invite/mutual_stats": {"GET": {"summary": "好友互推统计 + 连接强度",
          "responses": {"200": {"description": "connections + avg_strength + friend_recommended"}}}},
    }
}


def _redoc_html() -> str:
    return """<!DOCTYPE html>
<html>
<head>
  <title>Andromeda API v1 · ReDoc</title>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
  <style>body{margin:0;padding:0}redoc{height:100vh;display:block}</style>
</head>
<body>
  <redoc spec-url="__OPENAPI_URL__" hide-hostname="true" suppress-warnings="true"></redoc>
  <script src="https://unpkg.com/redoc@latest/bundles/redoc.standalone.js"></script>
</body>
</html>""".replace("__OPENAPI_URL__", "/api/andromeda_v1/v1/openapi.json")


def register_openapi(bp: Blueprint):
    """把 openapi.json + docs 注册到指定蓝图."""
    @bp.route("/openapi.json", methods=["GET"], endpoint="andromeda_v1_openapi_json")
    def api_openapi_json():
        base = request.host_url.rstrip("/")
        _openapi["servers"] = [{"url": base + "/api/andromeda_v1"}]
        return jsonify(_openapi)

    @bp.route("/docs", methods=["GET"], endpoint="andromeda_v1_docs")
    def api_docs():
        from flask import Response
        return Response(_redoc_html(), mimetype="text/html")
