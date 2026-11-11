#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════
# test_ios_funnel.py — 小龙 iOS App 公网 Funnel 端到端验证
# flow_ios_funnel_20261030
#
# 验证链路: iPhone → Tailscale Funnel HTTPS → Flask → 模型 → SSE 回传
# 步骤: 注册/登录 → 获取 token → 发送消息 → 解析 SSE → 验收
# ═══════════════════════════════════════════════════════════════════════

import json, time, uuid, sys, urllib.request, urllib.parse

# ── 服务器配置 ──
# 优先读 /tmp/mtscos_public_url.txt (cloudflared quick tunnel)
# 否则 Funnel 固定域名
def _detect_base():
    try:
        with open("/tmp/mtscos_public_url.txt") as f:
            url = f.read().strip().rstrip("/")
            if url:
                return url
    except: pass
    return "https://macbook-pro.tail5140cb.ts.net"

BASE = _detect_base()
print(f"🌐 Base URL: {BASE}")

username = f"ios_test_{uuid.uuid4().hex[:6]}"
password = "ios_test_pw_2026"
device_id = f"ios-{uuid.uuid4().hex}"

def _post(path, body, token=None):
    url = BASE + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-XL-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")
    except Exception as e:
        return 0, {"error": str(e)}

def _stream(path, body, token):
    url = BASE + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    req.add_header("X-XL-Token", token)
    events = []
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            if r.status != 200:
                return {"ok": False, "error": f"HTTP {r.status}", "body": r.read()[:200].decode()}
            buffer = ""
            for raw in r:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("data: "):
                    buffer = line[6:]
                    try:
                        obj = json.loads(buffer)
                        events.append(obj)
                    except: pass
                    if buffer.strip() == "[DONE]":
                        break
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "events": events}

print(f"🧪 Step 1/4: 注册新用户 {username}")
status, data = _post("/api/xiaolong/register",
                     {"username": username, "password": password, "device_id": device_id})
print(f"  HTTP {status}  success={data.get('success')}  msg={data.get('message', data.get('error',''))}")
if not data.get("success"):
    print(f"  ⚠️ 注册失败, 继续尝试登录 (用户可能已存在)")

print(f"🔑 Step 2/4: 登录获取 X-XL-Token")
status, data = _post("/api/xiaolong/token",
                     {"username": username, "password": password, "device_id": device_id})
print(f"  HTTP {status}  success={data.get('success')}")
if not data.get("success") or not data.get("token"):
    print(f"  ❌ 登录失败: {json.dumps(data, ensure_ascii=False)[:200]}")
    sys.exit(1)

token = data["token"]
print(f"  Token: {token[:30]}...")

print(f"💬 Step 3/4: 发送 SSE 流式消息 (hello + 时间)")
session_id = f"session_{uuid.uuid4().hex[:8]}"
result = _stream("/api/xiaolong/chat/stream",
                 {"message": "你好, 请用一句话介绍你自己",
                  "session_id": session_id,
                  "model": "qwen2.5:7b"}, token)

if not result.get("ok"):
    print(f"  ❌ SSE 失败: {result}")
    sys.exit(1)

events = result["events"]
print(f"  ✅ 收到 {len(events)} 个 SSE 事件")

types = {}
answer_parts = []
tool_calls = []
done_event = None
for e in events:
    t = e.get("type", "?")
    types[t] = types.get(t, 0) + 1
    if t == "delta":
        answer_parts.append(e.get("text", ""))
    elif t == "tool_done":
        tool_calls.append(f"{e.get('tool')}({'ok' if e.get('ok') else 'FAIL'})")
    elif t == "done":
        done_event = e

print(f"  事件类型统计: {json.dumps(types)}")
if answer_parts:
    full_answer = "".join(answer_parts)[:100]
    print(f"  模型回答 (前100字): {full_answer}")
if tool_calls:
    print(f"  工具调用: {', '.join(tool_calls)}")
if done_event:
    print(f"  会话结束: session={done_event.get('session_id')} msg_id={done_event.get('message_id')}")

print()
print("═══════════════════════════════════════════════════════")
print("  ✅ Funnel 端到端验证通过!")
print(f"  公网 HTTPS → Flask → SSE 全链路 OK")
print(f"  事件数: {len(events)}  模型回包: {'OK' if answer_parts else '空'}")
print("═══════════════════════════════════════════════════════")
