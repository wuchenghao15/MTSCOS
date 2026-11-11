#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务器侧 → 开发机算力调用 · 端到端测试脚本
==========================================
flow_id: flow_compute_router_test_20261013_001

运行位置: Mac mini 服务器 (或任何节点)
核心验证:
  T1 discover        双节点发现 + Aggregable=YES
  T2 route           服务器专属模型 → 本地; 开发机专属 → 跨机
  T3 ollama_chat     服务器发起 → 开发机 Ollama /api/chat 推理
  T4 ollama_generate 服务器发起 → 开发机 Ollama /api/generate 流式
  T5 latency_compare 同模型 本地 vs 跨机 延迟对比
  T6 concurrent      多模型并发路由到两端

用法:
  python3 compute_router_test.py            # 跑全部 (6 轮)
  python3 compute_router_test.py T3 T4      # 只跑指定轮
  python3 compute_router_test.py --verbose  # 打印完整 Ollama 响应
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import threading
from datetime import datetime
from typing import Dict, List, Optional, Callable

# 让脚本可直接 scp 到 /tmp 运行
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# 也尝试当前目录 (scp 到 /tmp 时)
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

try:
    from compute_router import (
        discover, route_model, available_models,
        get_ollama_base_url, _detect_self_host,
    )
    ROUTER_AVAILABLE = True
except ImportError as e:
    print(f"❌ compute_router 未找到: {e}")
    print("   请先 scp compute_router.py 到同目录")
    ROUTER_AVAILABLE = False

# ====================================================================
# 测试基础设施
# ====================================================================

PASS = 0
FAIL = 0
RESULTS: List[Dict] = []
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


def _http_post(url: str, payload: Dict, timeout: float = 60.0,
               stream: bool = False) -> Optional[Dict]:
    """POST JSON, 支持流式 (stream=True 时返回拼接文本)"""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if stream:
                # Ollama /api/chat stream: 多行 JSON, 每行一个对象
                chunks = []
                for line in raw.strip().splitlines():
                    try:
                        obj = json.loads(line)
                        chunks.append(obj.get("message", {}).get("content", ""))
                        if obj.get("done"):
                            break
                    except json.JSONDecodeError:
                        pass
                return {"stream_text": "".join(chunks)}
            else:
                return json.loads(raw)
    except Exception as e:
        return {"error": str(e)}


def t(name: str, fn: Callable, tags: List[str] = None):
    """测试装饰器 (简化版): 执行 + 记录 + 打印"""
    global PASS, FAIL
    tags = tags or []
    print(f"\n{'─'*60}")
    print(f"▶ {name}  [{' '.join(tags) if tags else 'basic'}]")
    print(f"{'─'*60}")
    t0 = time.time()
    try:
        result = fn()
        ok = result.get("ok", False) if isinstance(result, dict) else bool(result)
        dur_ms = (time.time() - t0) * 1000
        status = "✅ PASS" if ok else "❌ FAIL"
        if ok:
            PASS += 1
        else:
            FAIL += 1
        extra = result.get("msg", "") if isinstance(result, dict) else str(result)
        print(f"  {status}  ({dur_ms:.0f}ms)  {extra}")
        RESULTS.append({"name": name, "ok": ok, "dur_ms": round(dur_ms, 1), "tags": tags, "extra": extra})
        return result
    except Exception as e:
        dur_ms = (time.time() - t0) * 1000
        FAIL += 1
        print(f"  ❌ FAIL  ({dur_ms:.0f}ms)  异常: {e}")
        RESULTS.append({"name": name, "ok": False, "dur_ms": round(dur_ms, 1), "tags": tags, "extra": f"exception: {e}"})
        return {"ok": False, "msg": str(e)}


# ====================================================================
# T1: discover — 双节点 + Aggregable=YES
# ====================================================================
def t1_discover() -> Dict:
    result = discover()
    topo = result["topology"]
    node_status = result["node_status"]

    checks = [
        ("至少 2 节点", topo["online_nodes"] >= 2),
        ("Aggregable=YES", result["is_lan_aggregable"]),
        ("self_name 非 unknown", result["self_name"] != "unknown"),
        ("self Ollama online", topo.get("self_ollama", False)),
        ("remote Ollama online", topo.get("remote_ollama_online", False)),
        ("聚合模型 ≥ 5", result["unique_model_count"] >= 5),
    ]
    all_ok = all(v for _, v in checks)

    detail = []
    for label, ok in checks:
        detail.append(f"{'✅' if ok else '❌'} {label}")

    print(f"\n  拓扑: self={result['self_name']}  "
          f"online={topo['online_nodes']}/{topo['total_nodes']}  "
          f"models={result['unique_model_count']}  "
          f"Aggregable={'YES' if result['is_lan_aggregable'] else 'NO'}")
    for name, st in node_status.items():
        lat = f"{st['tailscale_latency_ms']:.0f}ms" if st.get("tailscale_latency_ms") else "N/A"
        marker = "⭐" if st["is_self"] else "🔗"
        print(f"    {marker} {name:10s} host={st['host']:16s} ollama={'🟢' if st['ollama_online'] else '🔴'}  models={st['model_count']:d}  lat={lat}")

    return {"ok": all_ok, "msg": "; ".join(detail)}


# ====================================================================
# T2: route — 服务器专属 → 本地; 开发机专属 → 跨机
# ====================================================================
def t2_route() -> Dict:
    self_name = _detect_self_host() or "server"

    # 先 discover 拿到可用模型
    discover()
    all_models = available_models()

    # 判定: 哪些是 self 专属 / 远程专属 / 共享
    from compute_router import _MODEL_TABLE
    self_only = []   # 只在 self 上有
    remote_only = [] # 只在远程有
    shared = []      # 双机都有
    for name, entries in _MODEL_TABLE.items():
        local = any(e["is_local"] for e in entries)
        remote = any(not e["is_local"] for e in entries)
        if local and remote: shared.append(name)
        elif local: self_only.append(name)
        else: remote_only.append(name)

    print(f"\n  当前 self={self_name}")
    print(f"    self_only:   {self_only}")
    print(f"    remote_only: {remote_only}")
    print(f"    shared:      {shared}")

    checks = []
    # 远程专属模型 → route 必须指向远程 (is_local=False)
    for m in remote_only[:2]:
        r = route_model(m)
        ok = r is not None and not r["is_local"]
        checks.append((f"{m} → 远程", ok))
        if r:
            print(f"    📡 {m:25s} → {r['node']} ({r['host']}) is_local={r['is_local']}")

    # self 专属模型 → route 必须指向本地 (is_local=True)
    for m in self_only[:2]:
        r = route_model(m)
        ok = r is not None and r["is_local"]
        checks.append((f"{m} → 本地", ok))
        if r:
            print(f"    ⭐ {m:25s} → {r['node']} ({r['host']}) is_local={r['is_local']}")

    all_ok = all(v for _, v in checks)
    return {"ok": all_ok, "msg": f"tested {len(checks)} routes"}


# ====================================================================
# T3: Ollama /api/chat — 服务器发起 → 开发机跑
# ====================================================================
def t3_ollama_chat() -> Dict:
    # 选一个开发机专属模型 (服务器本地没有的), 强制跨机
    target_model = None
    for m in available_models():
        r = route_model(m)
        if r and not r["is_local"]:
            target_model = m
            break
    if not target_model:
        # fallback: 随便找一个 route
        r = route_model(available_models()[0]) if available_models() else None
        target_model = r["node"] if r else None
        return {"ok": False, "msg": "没有远程专属模型可用"}

    route = route_model(target_model)
    url = f"http://{route['host']}:{route['port']}/api/chat"

    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": "你是简洁的测试助手, 用一句话回答。"},
            {"role": "user", "content": "请说: 跨机算力调用测试成功"},
        ],
        "stream": False,
        "options": {"num_predict": 20},  # 短输出, 加速
    }

    print(f"\n  目标模型: {target_model}")
    print(f"  路由: {route['node']} ({route['host']}) is_local={route['is_local']}")
    print(f"  端点: {url}")
    print(f"  发起推理...", end=" ", flush=True)

    t0 = time.time()
    resp = _http_post(url, payload, timeout=60)
    dur_ms = (time.time() - t0) * 1000

    if "error" in resp:
        return {"ok": False, "msg": f"Ollama error: {resp['error']}"}

    content = resp.get("message", {}).get("content", "")
    eval_count = resp.get("eval_count", 0)
    eval_dur = resp.get("eval_duration", 0) / 1e9  # ns → s

    print(f"✅  ({dur_ms:.0f}ms total, {eval_dur:.2f}s eval, {eval_count} tokens)")
    if VERBOSE:
        print(f"  响应: {content[:100]}")

    ok = len(content) > 0 and eval_count > 0
    return {"ok": ok, "msg": f"cross-machine chat OK, {eval_count} tokens in {eval_dur:.2f}s"}


# ====================================================================
# T4: Ollama /api/generate 流式 — 服务器发起 → 开发机流式返回
# ====================================================================
def t4_ollama_generate_stream() -> Dict:
    target_model = None
    for m in available_models():
        r = route_model(m)
        if r and not r["is_local"]:
            target_model = m
            break
    if not target_model:
        return {"ok": False, "msg": "no remote-exclusive model"}

    route = route_model(target_model)
    url = f"http://{route['host']}:{route['port']}/api/generate"

    payload = {
        "model": target_model,
        "prompt": "写一个 Python hello world, 只输出代码:",
        "stream": True,
        "options": {"num_predict": 40},
    }

    print(f"\n  目标模型: {target_model} → {route['node']} ({route['host']})")
    print(f"  流式 generate...", end=" ", flush=True)

    t0 = time.time()
    # 流式需要手动处理 response
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            chunks = []
            total_eval = 0
            last_line = ""
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "response" in obj:
                    chunks.append(obj["response"])
                if obj.get("done"):
                    total_eval = obj.get("eval_count", 0)
                    last_line = line
                    break
            full_text = "".join(chunks)
        dur_ms = (time.time() - t0) * 1000
        print(f"✅  ({dur_ms:.0f}ms, {total_eval} tokens)")
        if VERBOSE:
            print(f"  流式片段: {full_text[:80]}")
        ok = len(full_text) > 0 and total_eval > 0
        return {"ok": ok, "msg": f"stream OK, {total_eval} tokens"}
    except Exception as e:
        return {"ok": False, "msg": f"stream error: {e}"}


# ====================================================================
# T5: 延迟对比 — 同模型 本地 vs 跨机
# ====================================================================
def t5_latency_compare() -> Dict:
    self_name = _detect_self_host() or "server"
    discover()

    # 共享模型 (双机都有), 对比本地 vs 远程
    from compute_router import _MODEL_TABLE
    shared = []
    for name, entries in _MODEL_TABLE.items():
        has_local = any(e["is_local"] for e in entries)
        has_remote = any(not e["is_local"] for e in entries)
        if has_local and has_remote:
            shared.append(name)

    if not shared:
        return {"ok": False, "msg": "没有双机共享模型, 无法对比"}

    model = shared[0]
    print(f"\n  共享模型: {model}")

    payload = {
        "model": model,
        "prompt": "ping",
        "stream": False,
        "options": {"num_predict": 5},
    }

    results = {}
    for route_type in ["local", "remote"]:
        # 手动指定 URL
        if route_type == "local":
            url = f"http://127.0.0.1:11434/api/generate"
        else:
            # 找远程节点
            for e in _MODEL_TABLE[model]:
                if not e["is_local"]:
                    url = f"http://{e['host']}:{e['port']}/api/generate"
                    break
            else:
                continue

        print(f"    {route_type:6s}: {url}", end=" ", flush=True)
        t0 = time.time()
        resp = _http_post(url, payload, timeout=60)
        dur_ms = (time.time() - t0) * 1000
        err = resp.get("error") if isinstance(resp, dict) else None
        if err:
            print(f"❌ {err}")
            results[route_type] = None
        else:
            eval_dur = resp.get("eval_duration", 0) / 1e9 if resp else 0
            eval_count = resp.get("eval_count", 0) if resp else 0
            print(f"✅  total={dur_ms:.0f}ms  eval={eval_dur:.2f}s  tokens={eval_count}")
            results[route_type] = {
                "total_ms": dur_ms,
                "eval_s": eval_dur,
                "tokens": eval_count,
            }

    local_ok = results.get("local") is not None
    remote_ok = results.get("remote") is not None

    if local_ok and remote_ok:
        overhead = results["remote"]["total_ms"] - results["local"]["total_ms"]
        print(f"\n  📊 跨机开销: +{overhead:.0f}ms "
              f"(本地 {results['local']['total_ms']:.0f}ms → 跨机 {results['remote']['total_ms']:.0f}ms)")

    return {"ok": local_ok and remote_ok,
            "msg": f"local={results.get('local')}, remote={results.get('remote')}"}


# ====================================================================
# T6: 并发路由 — 多模型同时推理, 自动分散到两端
# ====================================================================
def t6_concurrent() -> Dict:
    discover()
    models = available_models()
    if len(models) < 2:
        return {"ok": False, "msg": "可用模型 < 2, 无法并发"}

    # 过滤: 剔除 embedding/CLIP 等非对话模型
    chat_models = [
        m for m in models
        if not any(k in m.lower() for k in ["embed", "clip", "rerank", "whisper"])
    ]
    if len(chat_models) < 2:
        return {"ok": False, "msg": "对话模型 < 2"}

    # 取前 4 个对话模型并发 (2 本地 + 2 远程 理想情况)
    batch = chat_models[:min(4, len(chat_models))]
    print(f"\n  并发模型: {batch}")

    results = {}
    lock = threading.Lock()
    errors = []

    def _run_one(model_name: str):
        route = route_model(model_name)
        if not route:
            with lock:
                errors.append(f"{model_name}: no route")
            return
        url = f"http://{route['host']}:{route['port']}/api/generate"
        payload = {
            "model": model_name,
            "prompt": "hi",
            "stream": False,
            "options": {"num_predict": 5},
        }
        t0 = time.time()
        resp = _http_post(url, payload, timeout=60)
        dur_ms = (time.time() - t0) * 1000
        with lock:
            if "error" in (resp or {}):
                errors.append(f"{model_name}: {resp['error']}")
            else:
                results[model_name] = {
                    "dur_ms": dur_ms,
                    "route": f"{route['node']}{'⭐' if route['is_local'] else '🔗'}",
                    "tokens": resp.get("eval_count", 0) if resp else 0,
                }

    t_total_0 = time.time()
    threads = [threading.Thread(target=_run_one, args=(m,)) for m in batch]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=90)
    total_ms = (time.time() - t_total_0) * 1000

    print(f"\n  并发总耗时: {total_ms:.0f}ms (串行预估 ≥ {len(batch)*500:.0f}ms)")
    for m, info in results.items():
        print(f"    ✅ {m:25s} → {info['route']:8s} {info['dur_ms']:6.0f}ms  {info['tokens']} tokens")
    for e in errors:
        print(f"    ❌ {e}")

    ok = len(errors) == 0 and len(results) >= 2
    speedup = (len(batch) * 500) / total_ms if total_ms > 0 else 0
    return {"ok": ok,
            "msg": f"{len(results)}/{len(batch)} success, speedup≈{speedup:.1f}x"}


# ====================================================================
# Main
# ====================================================================
def main():
    global PASS, FAIL

    # 指定跑哪些轮?
    run_specific = [a for a in sys.argv[1:] if a.startswith("T") and a[1].isdigit()]
    if run_specific:
        print(f"🎯 指定测试轮次: {run_specific}")

    if not ROUTER_AVAILABLE:
        print("❌ compute_router 模块不可用, 终止")
        sys.exit(1)

    print("=" * 60)
    print("  算力路由 · 服务器侧 → 开发机算力调用 · 端到端测试")
    print(f"  时间: {datetime.now().isoformat()}")
    print(f"  Self: {_detect_self_host()}")
    print("=" * 60)

    all_tests = [
        ("T1 discover (双节点发现)",   t1_discover,        ["topology"]),
        ("T2 route (路由正确)",        t2_route,           ["routing"]),
        ("T3 chat (跨机对话推理)",      t3_ollama_chat,     ["ollama", "chat", "cross-machine"]),
        ("T4 generate (跨机流式)",     t4_ollama_generate_stream, ["ollama", "stream"]),
        ("T5 latency (本地 vs 跨机)",  t5_latency_compare, ["benchmark"]),
        ("T6 concurrent (并发路由)",   t6_concurrent,      ["concurrency"]),
    ]

    for name, fn, tags in all_tests:
        test_id = name.split()[0]  # "T1", "T2" ...
        if run_specific and test_id not in run_specific:
            continue
        t(name, fn, tags)

    # 最终汇总
    print("\n" + "=" * 60)
    print(f"  汇总: {PASS} ✅  {FAIL} ❌  总计 {PASS + FAIL}")
    print("=" * 60)

    for r in RESULTS:
        mark = "✅" if r["ok"] else "❌"
        print(f"  {mark} {r['name']:40s}  {r['dur_ms']:7.0f}ms  {r['extra'][:60]}")

    print()
    if FAIL == 0:
        print("🎉 全部通过! 服务器侧调用开发机算力 · 端到端闭环已验证")
    else:
        print(f"⚠️  {FAIL} 轮失败, 请检查上方详情")

    # 退出码
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
