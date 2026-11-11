#!/usr/bin/env python3
"""
即梦 AI 视频生成 API — 冰山 v23.12.0 视频编辑渲染引擎
=====================================================

集成火山引擎即梦 (Dreamin) / Seedance AI 视频生成.

严格遵循经验教训 (3 条):
1. ✅ AK/SK 从 os.environ 读取, 不硬编码, 不回显
2. ✅ 使用官方 volcengine SDK, 不自研 V4 签名
3. ✅ PolicyViolation → 返回 400 + 可操作输入调整建议, 不承诺绕过

环境变量:
    JIMENG_AK  火山引擎 Access Key
    JIMENG_SK  火山引擎 Secret Key

路由前缀: /api/jimeng (由 registrar 自动注册, 默认无前缀)
"""

from __future__ import annotations

import json
import os
import time
import uuid
import sqlite3

from flask import Blueprint, request, jsonify, session

# ── DB 路径 ──
_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(os.path.dirname(_HERE))
_APP_DB = os.path.join(_FLASK_APP, "database", "app.db")


# ── 🔑 环境变量读取 (只在运行时读, 不缓存) ──
def _get_credentials() -> tuple[str, str]:
    ak = os.environ.get("JIMENG_AK", "").strip()
    sk = os.environ.get("JIMENG_SK", "").strip()
    return ak, sk


def _credentials_ready() -> bool:
    ak, sk = _get_credentials()
    return bool(ak) and bool(sk)


# ── DB 操作 ──
def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(_APP_DB, timeout=10.0)


def _ensure_tables() -> None:
    """确保即梦相关表存在 (模块加载时调用)"""
    try:
        conn = _get_conn()
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_jimeng_tasks (
            task_id TEXT PRIMARY KEY,
            project_id TEXT,
            prompt TEXT,
            aspect_ratio TEXT DEFAULT '16:9',
            duration_sec INTEGER DEFAULT 5,
            status TEXT DEFAULT 'PENDING',
            volc_task_id TEXT,
            result_url TEXT,
            local_path TEXT,
            error_code TEXT,
            error_message TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            cost_cents REAL DEFAULT 0,
            created_at REAL,
            updated_at REAL,
            completed_at REAL,
            triggered_by TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_jimeng_prompts (
            prompt_id TEXT PRIMARY KEY,
            scene_id TEXT,
            prompt_enhanced TEXT,
            negative_prompt TEXT,
            duration_sec INTEGER DEFAULT 5,
            aspect_ratio TEXT DEFAULT '16:9',
            created_at REAL)""")
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[JIMENG_API] _ensure_tables skip: {exc}")


# 模块加载时就建表 (不等到 first request)
_ensure_tables()


# ── 🔥 官方 SDK 封装 (延迟检测, 避免未装 SDK 时 Flask 崩溃) ──
def _get_volc_client():
    """
    获取火山引擎视频生成 client.
    
    自动适配 2 种 SDK:
    1. volcenginesdkarkruntime (Ark SDK → Seedance 模型, 推荐)
    2. volcengine (通用 SDK → Dreamin, 兼容)
    """
    ak, sk = _get_credentials()
    if not ak or not sk:
        return None, None
    
    # 优先 Ark SDK (较新, Seedance)
    try:
        from volcenginesdkarkruntime import Ark
        client = Ark(api_key=sk, base_url="https://ark.cn-beijing.volces.com/api/v3")
        return client, "ark"
    except ImportError:
        pass
    except Exception:
        pass
    
    # 兼容通用 volcengine SDK
    try:
        from volcengine.visual.VisualService import VisualService
        visual = VisualService()
        visual.set_ak(ak)
        visual.set_sk(sk)
        return visual, "volcengine"
    except ImportError:
        pass
    except Exception:
        pass
    
    return None, None


def _call_jimeng(client, api_type: str, prompt: str, duration: int, aspect: str) -> dict:
    """提交视频生成任务 (异步), 返回 task_id 或错误分类"""
    try:
        if api_type == "ark":
            resp = client.video.generations.create(
                model="doubao-seedance-1-0-250628",
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect,
            )
            task_id = getattr(resp, "task_id", str(uuid.uuid4()))
            return {"ok": True, "task_id": task_id}
        
        elif api_type == "volcengine":
            body = {"req_key": "high_aes", "prompt": prompt, "duration": duration, "aspect_ratio": aspect}
            resp = client.human_face(body)
            task_id = str(resp.get("task_id", resp.get("TaskId", uuid.uuid4())))
            return {"ok": True, "task_id": task_id}
        
        return {"ok": False, "error_code": "UNKNOWN_SDK", "error": f"unsupported api_type: {api_type}"}
    
    except Exception as exc:
        err = str(exc)
        if "AccessDenied" in err or "Access Denied" in err:
            return {"ok": False, "error_code": "AUTH_FAIL",
                    "error": "鉴权失败 — 检查 AK/SK 正确, 服务已开通即梦视频权限"}
        if "PolicyViolation" in err or "SensitiveContent" in err:
            return {"ok": False, "error_code": "POLICY_VIOLATION",
                    "error": "内容被平台策略拦截 (PolicyViolation)",
                    "suggestions": [
                        "真实人名/IP → 泛指 (如 '超人' → 'caped hero')",
                        "去除具体血腥/暴力描述",
                        "用 'anime/cartoon style' 替代真实人物",
                        "缩短提示词, 聚焦核心动作",
                    ]}
        if "InvalidParameter" in err or "invalid" in err.lower():
            return {"ok": False, "error_code": "PARAM_INVALID", "error": f"参数无效: {err[:100]}"}
        return {"ok": False, "error_code": "UNKNOWN", "error": err[:200]}


def _poll_jimeng(client, api_type: str, volc_task_id: str, max_wait: int = 300) -> dict:
    """轮询视频生成结果"""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            if api_type == "ark":
                resp = client.video.generations.retrieve(task_id=volc_task_id)
                status = getattr(resp, "status", "")
                if status == "succeeded":
                    return {"ok": True, "video_url": getattr(resp, "video_url", "")}
                if status in ("failed", "expired"):
                    return {"ok": False, "error": f"status={status}"}
            elif api_type == "volcengine":
                resp = client.get_result({"task_id": volc_task_id})
                status = resp.get("status", "")
                if status in ("success", "done", "SUCCEEDED"):
                    return {"ok": True, "video_url": resp.get("video_url", "")}
                if status in ("failed", "FAILED"):
                    return {"ok": False, "error": f"{resp}"}
            time.sleep(5)
        except Exception:
            time.sleep(5)
    return {"ok": False, "error": f"timeout {max_wait}s"}


# ═══════════════════════════════════════════════════════════════════════════
# 🔥 Module-level Blueprint (让 api_blueprint_registrar 正则能扫到)
# ═══════════════════════════════════════════════════════════════════════════
jimeng_bp = Blueprint("jimeng", __name__, url_prefix="/api/jimeng")


@jimeng_bp.route("/health", methods=["GET"])
def health():
    """健康检查 + 环境状态 (不需要登录)"""
    ark_ok, volc_ok = False, False
    try:
        import volcenginesdkarkruntime; ark_ok = True
    except ImportError: pass
    try:
        import volcengine; volc_ok = True
    except ImportError: pass
    
    return jsonify({
        "service": "jimeng_video_api",
        "version": "1.0.0",
        "credentials": _credentials_ready(),
        "sdk_available": {"ark": ark_ok, "volcengine": volc_ok},
        "env_status": {
            "JIMENG_AK": "set" if os.environ.get("JIMENG_AK") else "missing",
            "JIMENG_SK": "set" if os.environ.get("JIMENG_SK") else "missing",
        },
    }), 200


@jimeng_bp.route("/generate", methods=["POST"])
def generate():
    """
    提交视频生成任务
    
    JSON Body:
        prompt (str, 必填): 提示词 (3-500 字符)
        project_id (str, 可选): 关联 mt_video_projects
        duration_sec (int, 默认 5): 5 或 10
        aspect_ratio (str, 默认 16:9): 16:9 / 9:16 / 1:1
    """
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    project_id = data.get("project_id", "")
    duration = int(data.get("duration_sec", 5))
    aspect = data.get("aspect_ratio", "16:9")
    username = session.get("username", "") if session else ""
    
    # 参数校验
    if not prompt or len(prompt) < 3:
        return jsonify({"error": "PROMPT_TOO_SHORT", "msg": "提示词至少 3 字符"}), 400
    if len(prompt) > 500:
        prompt = prompt[:500]
    duration = duration if duration in (5, 10) else 5
    aspect = aspect if aspect in ("16:9", "9:16", "1:1") else "16:9"
    
    # 凭证检查
    if not _credentials_ready():
        return jsonify({
            "error": "CREDENTIALS_NOT_READY",
            "msg": "即梦 API 凭证未配置",
            "setup": "export JIMENG_AK=your_ak && export JIMENG_SK=your_sk",
            "note": "先在火山引擎开通即梦视频服务 (console.volcengine.com)",
        }), 503
    
    # SDK 检查
    client, api_type = _get_volc_client()
    if client is None:
        return jsonify({
            "error": "SDK_NOT_INSTALLED",
            "msg": "火山引擎 Python SDK 未安装",
            "install": "pip3 install volcenginesdkarkruntime volcengine",
        }), 503
    
    # 入库 (PENDING)
    task_id = f"JIMENG_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    now_ts = time.time()
    conn = _get_conn()
    conn.execute("""INSERT INTO mt_jimeng_tasks
        (task_id, project_id, prompt, aspect_ratio, duration_sec, status,
         created_at, updated_at, triggered_by)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (task_id, project_id, prompt, aspect, duration, "PENDING", now_ts, now_ts, username))
    conn.commit()
    conn.close()
    
    # 调 API
    result = _call_jimeng(client, api_type, prompt, duration, aspect)
    now_ts = time.time()
    conn = _get_conn()
    
    if result["ok"]:
        conn.execute("UPDATE mt_jimeng_tasks SET status='SUBMITTED', volc_task_id=?, updated_at=? WHERE task_id=?",
                     (result["task_id"], now_ts, task_id))
        conn.commit()
        conn.close()
        return jsonify({
            "status": "submitted",
            "task_id": task_id,
            "volc_task_id": result["task_id"],
            "poll_url": f"/api/jimeng/poll/{task_id}",
            "prompt": prompt[:100],
            "duration_sec": duration,
        }), 202
    
    # 失败
    err_code = result.get("error_code", "UNKNOWN")
    conn.execute("UPDATE mt_jimeng_tasks SET status='FAILED', error_code=?, error_message=?, updated_at=? WHERE task_id=?",
                 (err_code, result.get("error", "unknown"), now_ts, task_id))
    conn.commit()
    conn.close()
    
    http_code = 400 if err_code == "POLICY_VIOLATION" else (401 if err_code == "AUTH_FAIL" else 502)
    return jsonify({
        "status": "failed",
        "task_id": task_id,
        "error_code": err_code,
        "msg": result.get("error", "unknown"),
        "suggestions": result.get("suggestions", []),
    }), http_code


@jimeng_bp.route("/poll/<task_id>", methods=["GET"])
def poll(task_id: str):
    """轮询视频生成结果"""
    conn = _get_conn()
    # 用游标方式拿字段名
    cur = conn.execute("SELECT * FROM mt_jimeng_tasks WHERE task_id=?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "TASK_NOT_FOUND"}), 404
    cols = [d[0] for d in cur.description]
    conn.close()
    
    data = dict(zip(cols, row))
    status = data["status"]
    
    # 已终态 → 直接返回
    if status in ("COMPLETED", "FAILED"):
        return jsonify({
            "task_id": task_id,
            "status": status.lower(),
            "video_url": data.get("result_url", ""),
            "local_path": data.get("local_path", ""),
            "error_code": data.get("error_code"),
            "error_message": data.get("error_message"),
        }), 200
    
    # 还在处理中 → 实时轮询 (最多等 60s)
    volc_task_id = data.get("volc_task_id")
    if volc_task_id:
        client, api_type = _get_volc_client()
        if client:
            poll_result = _poll_jimeng(client, api_type, volc_task_id, max_wait=60)
            now_ts = time.time()
            conn = _get_conn()
            if poll_result.get("ok"):
                conn.execute("UPDATE mt_jimeng_tasks SET status='COMPLETED', result_url=?, completed_at=?, updated_at=? WHERE task_id=?",
                             (poll_result["video_url"], now_ts, now_ts, task_id))
                conn.commit()
                conn.close()
                return jsonify({"task_id": task_id, "status": "completed", "video_url": poll_result["video_url"]}), 200
            conn.execute("UPDATE mt_jimeng_tasks SET updated_at=? WHERE task_id=?", (now_ts, task_id))
            conn.commit()
            conn.close()
    
    return jsonify({"task_id": task_id, "status": status.lower(), "waiting": True}), 202


@jimeng_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """列出任务 (分页)"""
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    conn = _get_conn()
    rows = conn.execute(
        "SELECT task_id, substr(prompt,1,80), status, result_url, error_code, created_at FROM mt_jimeng_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM mt_jimeng_tasks").fetchone()[0]
    conn.close()
    return jsonify({
        "total": total, "limit": limit, "offset": offset,
        "tasks": [{"task_id": r[0], "prompt": r[1], "status": r[2],
                   "result_url": r[3], "error_code": r[4], "created_at": r[5]} for r in rows],
    }), 200
