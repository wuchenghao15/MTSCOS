"""v1/workflow — 仙女座工作流意识 + MVP 变现 API

端点:
  GET    /v1/workflow/list       — 所有可用工作流清单 (元数据 + 定价)
  GET    /v1/workflow/dashboard  — 变现仪表盘 (总运行数 / revenue / cost / profit)
  GET    /v1/workflow/runs       — 运行日志列表 (可按 workflow_id / status 过滤)
  GET    /v1/workflow/runs/<id>  — 单次运行详情
  POST   /v1/workflow/run       — 触发工作流 (blocking / async)

所有写操作 (run) 需 API Key; 只读端点公开.
"""
import time
from flask import Blueprint, request, jsonify
from .._helpers import _api_success, _api_error
from .._auth import require_api_key

bp = Blueprint("andromeda_v1_workflow", __name__, url_prefix="/workflow")


def _engine():
    """延迟 import workflow engine (避免蓝图 import 时触发)."""
    from engines.andromeda_workflow_engine import (
        list_workflows, run_workflow, dashboard_summary,
        list_runs, get_run, get_workflow,
    )
    return {
        "list": list_workflows, "get": get_workflow,
        "run": run_workflow, "dashboard": dashboard_summary,
        "runs": list_runs, "run_detail": get_run,
    }


@bp.route("/list", methods=["GET"])
def wf_list():
    """所有可用工作流清单 — 元数据 + 定价 + 阶段."""
    e = _engine()
    return jsonify(_api_success(workflows=e["list"]()))


@bp.route("/dashboard", methods=["GET"])
def wf_dashboard():
    """变现仪表盘 — 总运行数 / revenue / cost / profit / 按工作流分布."""
    e = _engine()
    return jsonify(_api_success(**e["dashboard"]()))


@bp.route("/runs", methods=["GET"])
def wf_runs():
    """运行日志列表.

    Query params:
      workflow_id (可选) — 过滤特定工作流
      status      (可选) — SUCCESS / FAILED / RUNNING
      limit       (可选) — 默认 50, 最多 200
    """
    e = _engine()
    wf_id = request.args.get("workflow_id")
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 50)), 200)
    runs = e["runs"](workflow_id=wf_id, status=status, limit=limit)
    return jsonify(_api_success(runs=runs, count=len(runs)))


@bp.route("/runs/<run_id>", methods=["GET"])
def wf_run_detail(run_id):
    """单次运行详情 — 含 stages / output / error."""
    e = _engine()
    run = e["run_detail"](run_id)
    if not run:
        return jsonify(_api_error(f"run not found: {run_id}")), 404
    return jsonify(_api_success(run=run))


@bp.route("/run", methods=["POST"])
@require_api_key
def wf_run():
    """触发一个工作流.

    Body (JSON):
      workflow_id  (必填) — 要执行的工作流
      input        (可选) — 工作流特定输入 (dict)
      blocking     (可选) — true 同步等待完成, false 后台异步 (默认 true)
      trigger_source (可选) — api / cron / daemon / manual (默认 api)
    """
    e = _engine()
    body = request.get_json(silent=True) or {}
    wf_id = body.get("workflow_id")
    if not wf_id:
        return jsonify(_api_error("workflow_id is required")), 400
    if wf_id not in [w["workflow_id"] for w in e["list"]()]:
        return jsonify(_api_error(f"unknown workflow_id: {wf_id}",
                                  available=[w["workflow_id"] for w in e["list"]()])), 400

    input_data = body.get("input", {})
    blocking = body.get("blocking", True)
    trigger_source = body.get("trigger_source", "api")

    t0 = time.time()
    try:
        result = e["run"](wf_id, input_data, trigger_source=trigger_source, blocking=blocking)
    except Exception as ex:
        return jsonify(_api_error(str(ex))), 500

    elapsed_ms = round((time.time() - t0) * 1000)
    resp = {
        "workflow_id": wf_id,
        "trigger_source": trigger_source,
        "blocking": blocking,
        "elapsed_ms": elapsed_ms,
        **result,
    }
    return jsonify(_api_success(**resp)), (202 if not blocking else 200)
