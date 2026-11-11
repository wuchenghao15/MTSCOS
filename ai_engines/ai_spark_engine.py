# -*- coding: utf-8 -*-
"""
科大讯飞星火大模型引擎 (iFLYTEK Spark)
======================================
作为 Ollama/本地推理 的在线兜底，按场景路由
API 类型: WebSocket + HMAC-SHA256 签名鉴权
端点: wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat

接入需要 4 个凭证 (讯飞开放平台控制台获取):
  - SPARK_APP_ID:     应用 AppID
  - SPARK_API_KEY:    应用 APIKey
  - SPARK_API_SECRET: 应用 APISecret
  - SPARK_DOMAIN:     服务 ID (serviceId, 开通的模型服务)

鉴权签名流程 (通用 URL 鉴权):
  1) 生成 timestamp (GMT 格式)
  2) 生成 date (GMT 格式)
  3) 拼 signature_origin = "host: maas-api.cn-huabei-1.xf-yun.com" + date + "GET /v1.1/chat"
  4) HMAC-SHA256(signature_origin, api_secret) → base64 → signature
  5) authorization = base64("api_key=\"X\", algorithm=\"hmac-sha256\", headers=\"host date request-line\", signature=\"Y\"")

响应: WebSocket 流式 JSON, status=2 表示最后一包

凭证安全:
  优先环境变量 > _runtime/config/ai_secrets.json (与 Volcengine 共用 secrets 文件)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional

# WebSocket 客户端 (优先 websocket-client, 无则用轻量实现)
try:
    import websocket  # pip install websocket-client
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════
# §0 配置 (可被环境变量覆盖)
# ═══════════════════════════════════════════════════════════════════

_SPARK_WS_URL = os.environ.get("SPARK_WS_URL",
    "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat")

_AI_ENGINES_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DB = os.path.join(_AI_ENGINES_DIR, "app.db")
_SECRETS_FILE = os.path.join(
    os.path.dirname(_AI_ENGINES_DIR), "..", "_runtime", "config", "ai_secrets.json"
)


def _load_secrets() -> Dict[str, str]:
    try:
        with open(_SECRETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_secrets(secrets: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(_SECRETS_FILE), exist_ok=True)
    with open(_SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump(secrets, f, ensure_ascii=False, indent=2)


def _get_credentials() -> Dict[str, str]:
    """获取星火 4 凭证 (环境变量优先 > secrets 文件)"""
    s = _load_secrets()
    return {
        "app_id":     os.environ.get("SPARK_APP_ID", s.get("spark_app_id", "")),
        "api_key":    os.environ.get("SPARK_API_KEY", s.get("spark_api_key", "")),
        "api_secret": os.environ.get("SPARK_API_SECRET", s.get("spark_api_secret", "")),
        "domain":     os.environ.get("SPARK_DOMAIN", s.get("spark_domain", "")),
    }


# ═══════════════════════════════════════════════════════════════════
# §1 鉴权签名 — HMAC-SHA256 (讯飞通用 URL 鉴权)
# ═══════════════════════════════════════════════════════════════════

def _build_auth_url(api_key: str, api_secret: str, host: str, path: str) -> str:
    """
    生成带鉴权参数的完整 WSS URL
    流程: signature_origin → HMAC-SHA256(api_secret) → base64
          → authorization = base64("api_key=..., algorithm=..., headers=..., signature=...")
          → 拼到 URL query 里
    """
    from email.utils import formatdate
    import calendar

    # GMT 时间戳
    date = formatdate(timeval=None, localtime=False, usegmt=True)

    # signature_origin 拼接
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"

    # HMAC-SHA256 签名
    signature_sha = hmac.new(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")

    # authorization 字符串
    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")

    # 拼 URL
    params = {
        "authorization": authorization,
        "date": date,
        "host": host,
    }
    return f"wss://{host}{path}?{urllib.parse.urlencode(params)}"


# ═══════════════════════════════════════════════════════════════════
# §2 核心调用 — WebSocket 流式聊天
# ═══════════════════════════════════════════════════════════════════

def _parse_ws_url(ws_url: str) -> tuple[str, str]:
    """从 wss://host/path 中拆解 host 和 path"""
    parsed = urllib.parse.urlparse(ws_url)
    return parsed.netloc, parsed.path


def _call_spark(messages: List[Dict], temperature: float = 0.5,
                max_tokens: int = 4096, uid: str = "mtscos_engine",
                app_id: str = "", api_key: str = "", api_secret: str = "",
                domain: str = "") -> Dict[str, Any]:
    """
    调用星火 WebSocket API, 收集所有流式返回拼接完整内容
    返回 {content, prompt_tokens, completion_tokens, ok, error}
    """
    host, path = _parse_ws_url(_SPARK_WS_URL)
    auth_url = _build_auth_url(api_key, api_secret, host, path)

    # 组装请求 JSON
    request_payload = {
        "header": {
            "app_id": app_id,
            "uid": uid,
        },
        "parameter": {
            "chat": {
                "domain": domain,
                "temperature": temperature,
                "top_k": 4,
            }
        },
        "payload": {
            "message": {
                "text": messages
            }
        }
    }

    full_content_parts: List[str] = []
    last_usage: Dict[str, int] = {}
    sid = ""
    error_msg = ""

    if not _WS_AVAILABLE:
        # Fallback: 用 socket + ssl 手动握手 (最轻量)
        return _call_spark_socket(auth_url, request_payload)

    try:
        ws = websocket.create_connection(auth_url, timeout=60)
        ws.settimeout(60)
        ws.send(json.dumps(request_payload))

        while True:
            try:
                raw = ws.recv()
                if not raw:
                    break
                data = json.loads(raw)
                header = data.get("header", {})
                code = header.get("code", -1)
                sid = header.get("sid", sid)
                status = header.get("status", 2)

                if code != 0:
                    error_msg = f"星火 API 错误码 {code}: {header.get('message', '')}"
                    break

                choices = data.get("payload", {}).get("choices", {})
                for text_item in choices.get("text", []):
                    content = text_item.get("content", "")
                    if content:
                        full_content_parts.append(content)

                if status == 2:  # 最后一包, 带 usage
                    usage_data = data.get("payload", {}).get("usage", {})
                    last_usage = usage_data.get("text", {})
                    break

            except websocket.WebSocketTimeoutException:
                error_msg = "星火 API 超时 (60s)"
                break

        ws.close()

        return {
            "content": "".join(full_content_parts),
            "prompt_tokens": last_usage.get("prompt_tokens", 0),
            "completion_tokens": last_usage.get("completion_tokens", 0),
            "total_tokens": last_usage.get("total_tokens", 0),
            "sid": sid,
            "ok": not error_msg,
            "error": error_msg,
        }

    except Exception as e:
        return {
            "content": "",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "sid": "", "ok": False, "error": str(e)[:200],
        }


def _call_spark_socket(auth_url: str, payload: Dict) -> Dict[str, Any]:
    """
    无 websocket-client 时的兜底: socket + ssl + 手动 WS 握手
    轻量但较笨, 只处理最简单的单包返回
    """
    import socket
    import ssl as _ssl

    parsed = urllib.parse.urlparse(auth_url)
    host = parsed.hostname
    port = parsed.port or 443
    path = parsed.path + ("?" + parsed.query if parsed.query else "")

    # WS 握手 key
    ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
    ws_accept = base64.b64encode(
        hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode("ascii")

    sock = socket.create_connection((host, port), timeout=30)
    ctx = _ssl.create_default_context()
    ssock = ctx.wrap_socket(sock, server_hostname=host)

    # HTTP Upgrade
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {ws_key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    ssock.sendall(handshake.encode())
    # 读握手响应
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = ssock.recv(4096)
        if not chunk: break
        buf += chunk
    if b"101" not in buf:
        ssock.close()
        return {"content": "", "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "sid": "", "ok": False,
                "error": f"WS 握手失败: {buf[:200]}"}

    def _ws_send(data: bytes):
        """发送 WebSocket 文本帧 (opcode=1, 无 masking 简化)"""
        mask = os.urandom(4)
        frame = bytearray([0x81])
        length = len(data)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(0x80 | 127)
            frame.extend(length.to_bytes(8, "big"))
        frame.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        frame.extend(masked)
        ssock.sendall(bytes(frame))

    def _ws_recv() -> bytes:
        """接收 WebSocket 帧 (简化版, 不处理分片)"""
        first = ssock.recv(1)
        if not first: return b""
        second = ssock.recv(1)
        length = second[0] & 0x7f
        if length == 126:
            length = int.from_bytes(ssock.recv(2), "big")
        elif length == 127:
            length = int.from_bytes(ssock.recv(8), "big")
        mask = ssock.recv(4) if second[0] & 0x80 else b""
        data = ssock.recv(length) if length else b""
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return data

    _ws_send(json.dumps(payload).encode("utf-8"))

    parts = []
    last_usage = {}
    last_error = ""
    for _ in range(50):  # 最多 50 包
        try:
            raw = _ws_recv()
            if not raw: break
            data = json.loads(raw)
            header = data.get("header", {})
            code = header.get("code", -1)
            if code != 0:
                last_error = f"星火 API 错误码 {code}: {header.get('message', '')}"
                break
            for item in data.get("payload", {}).get("choices", {}).get("text", []):
                parts.append(item.get("content", ""))
            if header.get("status") == 2:
                last_usage = data.get("payload", {}).get("usage", {}).get("text", {})
                break
        except Exception:
            break

    ssock.close()
    return {
        "content": "".join(parts),
        "prompt_tokens": last_usage.get("prompt_tokens", 0),
        "completion_tokens": last_usage.get("completion_tokens", 0),
        "total_tokens": last_usage.get("total_tokens", 0),
        "sid": "", "ok": not last_error, "error": last_error,
    }


# ═══════════════════════════════════════════════════════════════════
# §3 Flask 层友好 API
# ═══════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """星火引擎是否就绪 (4 凭证齐全)"""
    c = _get_credentials()
    return all([c["app_id"], c["api_key"], c["api_secret"], c["domain"]])


def chat(prompt: str, system: str = "", flow_id: Optional[str] = None,
         temperature: float = 0.5) -> Dict[str, Any]:
    """
    星火聊天主入口 (与 Volcengine 签名完全兼容)
    返回 {success, response, model, duration_ms, tokens_saved, error}
    """
    c = _get_credentials()
    if not all([c["app_id"], c["api_key"], c["api_secret"], c["domain"]]):
        missing = []
        for k in ["app_id", "api_key", "api_secret", "domain"]:
            if not c[k]:
                missing.append(k)
        return {
            "success": False, "response": "", "model": f"spark({c['domain']})",
            "duration_ms": 0, "tokens_saved": 0,
            "error": f"星火凭证未配置: 缺 {missing}. 用 SPARK_APP_ID/SPARK_API_KEY/SPARK_API_SECRET/SPARK_DOMAIN 环境变量 或 secrets 文件",
        }

    messages = []
    if system:
        messages.append({"role": "user", "content": f"[System]: {system}"})
    messages.append({"role": "user", "content": prompt})

    start = time.time()
    result = _call_spark(
        messages, temperature=temperature,
        app_id=c["app_id"], api_key=c["api_key"], api_secret=c["api_secret"],
        domain=c["domain"],
    )
    duration_ms = int((time.time() - start) * 1000)

    # 落库 (与 Volcengine 共用 inference_log)
    _log_inference(flow_id, "chat", f"spark({c['domain']})",
                   result["prompt_tokens"], result["completion_tokens"],
                   duration_ms, result["ok"], result["error"])

    if result["ok"]:
        return {
            "success": True,
            "response": result["content"],
            "model": f"spark({c['domain']})",
            "duration_ms": duration_ms,
            "tokens_saved": 0,  # 云 API 消耗 token
            "error": "",
            "sid": result["sid"],
        }
    else:
        return {
            "success": False,
            "response": "",
            "model": f"spark({c['domain']})",
            "duration_ms": duration_ms,
            "tokens_saved": 0,
            "error": result["error"],
        }


# ═══════════════════════════════════════════════════════════════════
# §4 基础设施 (与 Volcengine 共用)
# ═══════════════════════════════════════════════════════════════════

def _log_inference(flow_id: Optional[str], kind: str, model: str,
                   prompt_tokens: int, completion_tokens: int, duration_ms: int,
                   success: bool, error_msg: str) -> None:
    """落库 mt_local_ai_inference_log (source=spark)"""
    try:
        conn = sqlite3.connect(_APP_DB, timeout=5)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_local_ai_inference_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flow_id TEXT, inference_kind TEXT, model_name TEXT,
                prompt_tokens INTEGER, completion_tokens INTEGER,
                duration_ms INTEGER, tokens_saved INTEGER DEFAULT 0,
                success INTEGER, error_msg TEXT,
                request_preview TEXT, response_preview TEXT,
                triggered_at TEXT, source TEXT DEFAULT 'ollama'
            )""")
        try:
            conn.execute("SELECT source FROM mt_local_ai_inference_log LIMIT 0")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE mt_local_ai_inference_log ADD COLUMN source TEXT DEFAULT 'ollama'")

        conn.execute("""
            INSERT INTO mt_local_ai_inference_log
            (flow_id, inference_kind, model_name, prompt_tokens, completion_tokens,
             duration_ms, tokens_saved, success, error_msg, triggered_at, source)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (flow_id, kind, model, prompt_tokens, completion_tokens,
              duration_ms, 0, 1 if success else 0, error_msg,
              datetime.now().isoformat(), "spark"))
        conn.commit()
        conn.close()
    except Exception:
        pass  # 日志落库失败不影响主链路


def health() -> Dict[str, Any]:
    """引擎健康状态"""
    c = _get_credentials()
    return {
        "engine": "ai_spark_engine",
        "available": is_available(),
        "ws_url": _SPARK_WS_URL,
        "domain": c["domain"] or "(未配置)",
        "app_id_configured": bool(c["app_id"]),
        "api_key_configured": bool(c["api_key"]),
        "api_secret_configured": bool(c["api_secret"]),
        "ws_client": "websocket-client" if _WS_AVAILABLE else "socket_fallback",
        "role": "online_llm",
    }


def set_credentials(app_id: str, api_key: str, api_secret: str,
                    domain: str) -> Dict[str, Any]:
    """保存 4 个凭证到 secrets 文件"""
    secrets = _load_secrets()
    if app_id:     secrets["spark_app_id"] = app_id.strip()
    if api_key:    secrets["spark_api_key"] = api_key.strip()
    if api_secret: secrets["spark_api_secret"] = api_secret.strip()
    if domain:     secrets["spark_domain"] = domain.strip()
    _save_secrets(secrets)
    return {
        "success": True,
        "message": f"星火凭证已保存到 {_SECRETS_FILE}",
        "health": health(),
    }


# ═══════════════════════════════════════════════════════════════════
# §5 CLI — 配置/验证/测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="科大讯飞星火大模型引擎")
    sub = parser.add_subparsers(dest="cmd")

    # set 子命令: 配置全部凭证
    p_set = sub.add_parser("set", help="配置全部 4 个凭证")
    p_set.add_argument("--app-id", default="", help="AppID")
    p_set.add_argument("--api-key", default="", help="APIKey")
    p_set.add_argument("--api-secret", default="", help="APISecret")
    p_set.add_argument("--domain", default="", help="服务 ID (serviceId)")

    # set-one 子命令: 单独设某凭证
    p_one = sub.add_parser("set-one", help="单独设一个凭证")
    p_one.add_argument("field", choices=["app_id", "api_key", "api_secret", "domain"])
    p_one.add_argument("value")

    sub.add_parser("health", help="查看引擎健康")

    # test 子命令
    p_test = sub.add_parser("test", help="测试星火 API 连通性")
    p_test.add_argument("--prompt", default="你好, 请用一句话介绍你自己", help="测试提示词")
    p_test.add_argument("--system", default="", help="System prompt")

    sub.add_parser("secrets", help="查看当前凭证配置 (脱敏)")

    args = parser.parse_args()

    if args.cmd == "set":
        result = set_credentials(args.app_id, args.api_key, args.api_secret, args.domain)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == "set-one":
        secrets = _load_secrets()
        field_map = {
            "app_id": "spark_app_id",
            "api_key": "spark_api_key",
            "api_secret": "spark_api_secret",
            "domain": "spark_domain",
        }
        secrets[field_map[args.field]] = args.value.strip()
        _save_secrets(secrets)
        print(json.dumps({"success": True, "field": args.field,
                          "health": health()}, ensure_ascii=False, indent=2))

    elif args.cmd == "health":
        print(json.dumps(health(), ensure_ascii=False, indent=2))

    elif args.cmd == "test":
        print(f"[测试] prompt={args.prompt!r}")
        result = chat(args.prompt, system=args.system, flow_id="cli_test")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == "secrets":
        c = _get_credentials()
        masked = {}
        for k, v in c.items():
            masked[k] = v[:6] + "..." if v else "(未配置)"
        print(json.dumps(masked, ensure_ascii=False, indent=2))
        print(f"secrets 文件: {_SECRETS_FILE}")

    else:
        parser.print_help()
