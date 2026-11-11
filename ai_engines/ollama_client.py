#!/usr/bin/env python3
"""
仙女座 Ollama 双路路由客户端 — ollama_client.py
=================================================
统一入口: 所有引擎 (goal/meta/iceberg/compute) 通过这个客户端调用 Ollama

路由策略:
  1. 本地优先 (OLLAMA_HOST=127.0.0.1:11434) — 低延迟, mini 本地小模型
  2. 远程 fallback (OLLAMA_REMOTE_HOST=http://100.121.98.15:11434) — Tailnet 25ms, 本地 macOS 全套大模型
  3. 超时: 每个 endpoint 2s connect timeout + 120s read timeout
  4. 熔断: 远程 3 次失败 → 跳过远程 60s
  5. 能力匹配: 根据模型 family/size 自动选 endpoint

模型路由表:
  本地 1.5b → 本地推理 (低延迟, 意识自省)
  本地 embed → 本地推理 (向量化必须本地)
  远程 7b/14b → 远程 Tailnet 调 (强推理)
  远程 coder/flux → 远程 Tailnet 调 (代码/图像生成)

FLOW_ID: flow_andromeda_awakening_20261025
"""
from __future__ import annotations
import os, json, time, uuid, sqlite3, urllib.request, urllib.error, socket, logging
from pathlib import Path
from threading import Lock

log = logging.getLogger("ollama_client")
if not log.handlers:
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)

# ── 环境变量 (mini ~/.bashrc 已配置) ──
LOCAL_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
REMOTE_HOST = os.environ.get("OLLAMA_REMOTE_HOST", "http://100.121.98.15:11434")
LOCAL_MODELS = set(os.environ.get("OLLAMA_LOCAL_MODELS", "qwen2.5:1.5b,nomic-embed-text:latest").split(","))
REMOTE_MODELS = set(os.environ.get("OLLAMA_REMOTE_MODELS", "qwen2.5:7b,qwen2.5:14b-q5,qwen2.5-coder:7b,qwen2.5-coder:14b,x/flux2-klein:4b").split(","))

CONNECT_TIMEOUT = 2
READ_TIMEOUT = 120
CIRCUIT_BREAK_FAIL_LIMIT = 3
CIRCUIT_BREAK_COOLDOWN = 60

# 熔断器状态
_cb_state = {"local_fails": 0, "remote_fails": 0, "remote_disabled_until": 0}
_cb_lock = Lock()


def _url(host: str, path: str) -> str:
    if not host.startswith("http"):
        host = f"http://{host}"
    return f"{host.rstrip('/')}{path}"


def _post(host: str, path: str, payload: dict) -> dict | None:
    """发 POST 请求, 返回 JSON dict 或 None"""
    url = _url(host, path)
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(READ_TIMEOUT)  # connect+read 统一超时
    try:
        with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, socket.timeout) as e:
        log.warning(f"ollama POST {url} fail: {e}")
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)


def _get(host: str, path: str) -> dict | None:
    url = _url(host, path)
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(READ_TIMEOUT)
    try:
        with urllib.request.urlopen(url, timeout=READ_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning(f"ollama GET {url} fail: {e}")
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)


# ── 健康检查 ──
def health_check() -> dict:
    """返回 {local: bool, remote: bool, local_models: [...], remote_models: [...]}"""
    result = {"local": False, "remote": False, "local_models": [], "remote_models": []}

    local = _get(LOCAL_HOST, "/api/tags")
    if local:
        result["local"] = True
        result["local_models"] = [m["name"] for m in local.get("models", [])]

    # 检查远程熔断器
    with _cb_lock:
        if time.time() < _cb_state["remote_disabled_until"]:
            result["remote"] = False
            result["remote_cooldown"] = int(_cb_state["remote_disabled_until"] - time.time())
            return result

    remote = _get(REMOTE_HOST, "/api/tags")
    if remote:
        result["remote"] = True
        result["remote_models"] = [m["name"] for m in remote.get("models", [])]
        with _cb_lock:
            _cb_state["remote_fails"] = 0
    else:
        with _cb_lock:
            _cb_state["remote_fails"] += 1
            if _cb_state["remote_fails"] >= CIRCUIT_BREAK_FAIL_LIMIT:
                _cb_state["remote_disabled_until"] = time.time() + CIRCUIT_BREAK_COOLDOWN
                log.warning(f"remote circuit break! disabled {CIRCUIT_BREAK_COOLDOWN}s")

    return result


def pick_endpoint(model: str) -> str:
    """给定模型名 → 返回用本地还是远程 endpoint"""
    # embed 永远本地 (向量化不能走远程)
    if "embed" in model.lower():
        return LOCAL_HOST

    # 在本地清单 → 本地
    if model in LOCAL_MODELS:
        return LOCAL_HOST

    # 在远程清单 + 远程可用 → 远程
    with _cb_lock:
        remote_ok = time.time() >= _cb_state["remote_disabled_until"]

    if model in REMOTE_MODELS and remote_ok:
        return REMOTE_HOST

    # 小模型 (<=3b) → 本地, 大模型 (>3b) → 远程
    if any(x in model for x in ["14b", "7b", "32b", "72b", "flux", "coder:14"]):
        if remote_ok:
            return REMOTE_HOST
    # 小模型兜底本地
    return LOCAL_HOST


# ── 核心 API ──
def generate(model: str, prompt: str, **kwargs) -> dict:
    """双路 generate: 选 endpoint → 失败 fallback → 返回 response dict"""
    endpoint = pick_endpoint(model)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": kwargs.get("options", {"temperature": kwargs.get("temperature", 0.7)}),
    }
    t0 = time.time()
    result = _post(endpoint, "/api/generate", payload)
    if result and result.get("done"):
        result["_endpoint"] = endpoint
        result["_elapsed"] = round((time.time() - t0) * 1000)
        result["_run_id"] = uuid.uuid4().hex[:10]
        return result

    # 主 endpoint 失败 → fallback 另一个
    fallback = REMOTE_HOST if endpoint == LOCAL_HOST else LOCAL_HOST
    log.warning(f"ollama {endpoint} fail → fallback {fallback}")
    t1 = time.time()
    result2 = _post(fallback, "/api/generate", payload)
    if result2 and result2.get("done"):
        result2["_endpoint"] = fallback
        result2["_elapsed_fallback"] = round((time.time() - t1) * 1000)
        return result2

    return {"response": "", "done": False, "error": f"both local+remote fail"}


def chat(model: str, messages: list[dict], **kwargs) -> dict:
    """双路 chat (messages 格式)"""
    endpoint = pick_endpoint(model)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": kwargs.get("options", {"temperature": kwargs.get("temperature", 0.7)}),
    }
    result = _post(endpoint, "/api/chat", payload)
    if result and result.get("done"):
        result["_endpoint"] = endpoint
        return result
    # fallback
    fallback = REMOTE_HOST if endpoint == LOCAL_HOST else LOCAL_HOST
    result2 = _post(fallback, "/api/chat", payload)
    if result2 and result2.get("done"):
        result2["_endpoint"] = fallback
        return result2
    return {"message": {"content": ""}, "done": False, "error": "both fail"}


def embed(model: str, text: str) -> dict:
    """向量化 — 永远本地"""
    payload = {"model": model, "prompt": text, "stream": False}
    return _post(LOCAL_HOST, "/api/embeddings", payload) or {"embedding": []}


# ── 快捷函数 (被引擎直接 import) ──
def quick_chat(model: str, prompt: str) -> str:
    """单行快捷: 返回 response 文本"""
    r = generate(model, prompt)
    return r.get("response", "") or r.get("error", "")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n=== Ollama Dual-Route Client Test ===")
    health = health_check()
    print(f"  local:  {'✅' if health['local'] else '❌'} ({len(health['local_models'])} models)")
    print(f"  remote: {'✅' if health['remote'] else '❌'} ({len(health['remote_models'])} models)")
    for m in health["local_models"]:
        print(f"    LOCAL  {m}")
    for m in health["remote_models"]:
        print(f"    REMOTE {m}")

    print("\n  --- pick_endpoint tests ---")
    for m in ["qwen2.5:1.5b", "qwen2.5:7b", "qwen2.5-coder:7b", "nomic-embed-text:latest", "x/flux2-klein:4b"]:
        ep = pick_endpoint(m)
        tag = "LOCAL " if "127.0.0.1" in ep else "REMOTE"
        print(f"    {m:30s} → {tag} ({ep})")

    print("\n  --- local 1.5b test ---")
    r = generate("qwen2.5:1.5b", "仙女座是什么? 一句话")
    print(f"  response: {r.get('response', '')[:100]}")
    print(f"  endpoint: {r.get('_endpoint')}")
    print(f"  elapsed:  {r.get('_elapsed')}ms")
