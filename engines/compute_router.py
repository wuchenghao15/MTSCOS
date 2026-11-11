#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
算力路由管理器 — 开发机 + 服务器 Tailscale 聚合算力
========================================================
flow_id: flow_compute_router_20261013_001

核心逻辑:
  同 Tailscale 网 → 聚合双机 Ollama 算力 + 模型配比
  否则             → 服务器自行云端/本地方案

节点配置 (v22.17.0 实测):
  - devbox  (MacBook Pro, M5 10核 24GB)   0.0.0.0:11434  6模型
  - server  (Mac mini,    M4  10核 24GB)   *:11434        3模型
  双向跨机 Ollama HTTP ✅ 通, Tailscale ~440ms

路由优先级:
  1. 本地 Ollama     (零延迟, 首选)
  2. Tailscale 远程  (~440ms, 本地缺模型时)
  3. 云端 API        (最终兜底)

CLI:
  python3 compute_router.py discover       # 发现所有节点+模型
  python3 compute_router.py route <model> # 找某模型在哪台机器
  python3 compute_router.py health         # 全节点健康检查
  python3 compute_router.py table         # 聚合模型表
"""
import json
import os
import sys
import time
import socket
import subprocess
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# ====================================================================
# 节点注册表 (硬编码, 可热更新 discover() 后缓存)
# ====================================================================

NODE_REGISTRY: List[Dict] = [
    {
        "name": "devbox",
        "role": "development",
        "host": "100.121.98.15",        # Tailscale IP
        "ollama_port": 11434,
        "cpu": "Apple M5 10核",
        "ram_gb": 24,
        "hostname_aliases": ["wuchenghaodemacbookpro", "devbox", "trae"],
        "is_self": False,
    },
    {
        "name": "server",
        "role": "production",
        "host": "100.106.220.96",       # Tailscale IP
        "ollama_port": 11434,
        "cpu": "Apple M4 10核",
        "ram_gb": 24,
        "hostname_aliases": ["hulk-macmini", "hulk", "macmini", "server"],
        "is_self": False,
    },
]

# 缓存 (首次 discover() 后填充)
_MODEL_TABLE: Dict[str, List[Dict]] = {}   # {model_name: [{node, size_mb, latency_ms}]}
_NODE_STATUS: Dict[str, Dict] = {}         # {node_name: {online, models, latency_ms, last_seen}}
_ROUTER_READY: bool = False

# ====================================================================
# 底层探测
# ====================================================================

def _http_get(url: str, timeout: float = 3.0) -> Optional[Dict]:
    """轻量 HTTP GET, 返回 parsed JSON 或 None"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError,
            ConnectionResetError, OSError, ValueError):
        return None


def _ping_tailscale(host: str, count: int = 2) -> Optional[float]:
    """Tailscale ping → 平均延迟 ms, 不通返回 None"""
    try:
        result = subprocess.run(
            ["tailscale", "ping", "--c", str(count), host],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.splitlines():
            # tailscale ping 输出: "pong from 100.x.x.x in 15ms"
            if "pong from" in line and "in" in line:
                ms = line.rsplit("in", 1)[-1].strip()
                if ms.endswith("ms"):
                    return float(ms[:-2])
    except Exception:
        pass
    # fallback: 普通 ICMP
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", "1", host],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if "round-trip" in line:
                # ... min/avg/max = 434.757/439.993/445.229/5.236 ms
                parts = line.split("=")[-1].strip()
                avg = parts.split("/")[1]
                return float(avg)
    except Exception:
        pass
    return None


def _ollama_models(node: Dict) -> Tuple[bool, List[Dict], float]:
    """探测节点 Ollama /api/tags → (online, models[], latency_ms)"""
    url = f"http://{node['host']}:{node['ollama_port']}/api/tags"
    t0 = time.time()
    data = _http_get(url, timeout=3.0)
    latency = (time.time() - t0) * 1000
    if data is None:
        return False, [], latency
    models = []
    for m in data.get("models", []):
        models.append({
            "name": m["name"],
            "size_mb": m.get("size", 0) // 1024 // 1024,
            "digest": m.get("digest", ""),
        })
    return True, models, latency


def _detect_self_host() -> Optional[str]:
    """自动判定当前机器在 NODE_REGISTRY 中对应哪个节点"""
    # 全部策略: hostname alias > tailscale ip > 本机端口匹配

    hostname = socket.gethostname().lower()
    # 先检查 alias 包含
    for node in NODE_REGISTRY:
        aliases = [a.lower() for a in node.get("hostname_aliases", [])]
        if any(alias in hostname for alias in aliases):
            return node["name"]

    # tailscale ip -4 (CLI 可能不存在)
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            my_ips = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            for node in NODE_REGISTRY:
                if node["host"] in my_ips:
                    return node["name"]
    except FileNotFoundError:
        pass  # tailscale CLI 未安装

    # fallback: hostname 包含节点名 (通用匹配)
    for node in NODE_REGISTRY:
        if node["name"].lower() in hostname:
            return node["name"]

    # 最终兜底: 取第一个 localhost Ollama 在线的节点
    for node in NODE_REGISTRY:
        url = f"http://127.0.0.1:{node['ollama_port']}/api/tags"
        if _http_get(url, timeout=2.0) is not None:
            return node["name"]

    return None


# ====================================================================
# 发现 + 聚合
# ====================================================================

def discover(force: bool = False) -> Dict:
    """
    扫描所有节点, 构建聚合模型表.
    返回 dict: {node_status, model_table, topology, is_lan_aggregable}
    """
    global _MODEL_TABLE, _NODE_STATUS, _ROUTER_READY

    self_name = _detect_self_host() or "unknown"
    aggregated: Dict[str, List[Dict]] = {}
    node_status: Dict[str, Dict] = {}

    for node in NODE_REGISTRY:
        node["is_self"] = (node["name"] == self_name)

        # Step 1: 延迟 (Tailscale ping)
        latency = _ping_tailscale(node["host"])

        # Step 2: Ollama 模型
        online, models, ollama_lat = _ollama_models(node)

        node_status[node["name"]] = {
            "role": node["role"],
            "host": node["host"],
            "is_self": node["is_self"],
            "tailscale_latency_ms": latency,
            "ollama_online": online,
            "ollama_latency_ms": round(ollama_lat, 1),
            "model_count": len(models),
            "models": [m["name"] for m in models],
            "last_seen": datetime.now().isoformat(),
        }

        # Step 3: 聚合进总表
        for m in models:
            entry = {
                "node": node["name"],
                "host": node["host"],
                "port": node["ollama_port"],
                "is_local": node["is_self"],
                "size_mb": m["size_mb"],
                "tailscale_latency_ms": latency,
            }
            if m["name"] not in aggregated:
                aggregated[m["name"]] = []
            aggregated[m["name"]].append(entry)

    # 每个模型排序: 本地优先 → 低延迟优先
    for name in aggregated:
        aggregated[name].sort(key=lambda e: (
            0 if e["is_local"] else 1,
            e["tailscale_latency_ms"] or 9999,
        ))

    _MODEL_TABLE = aggregated
    _NODE_STATUS = node_status
    _ROUTER_READY = True

    # 判定: 是否同 Tailscale 网可聚合
    self_node = node_status.get(self_name, {})
    remote_nodes = [n for n in node_status.values() if not n.get("is_self")]
    remote_online = [n for n in remote_nodes if n["ollama_online"]]
    self_ollama_online = self_node.get("ollama_online", False)
    any_remote_online = len(remote_online) > 0

    return {
        "self_name": self_name,
        "topology": {
            "total_nodes": len(NODE_REGISTRY),
            "online_nodes": sum(1 for n in node_status.values() if n["ollama_online"]),
            "self_ollama": self_ollama_online,
            "remote_ollama_online": any_remote_online,
            "remote_online_count": len(remote_online),
        },
        "node_status": node_status,
        "model_table": aggregated,
        "unique_model_count": len(aggregated),
        "is_lan_aggregable": any_remote_online and (self_ollama_online or len(aggregated) > 0),
        "discovered_at": datetime.now().isoformat(),
    }


# ====================================================================
# 路由查询
# ====================================================================

def route_model(model_name: str) -> Optional[Dict]:
    """
    找某模型的最佳部署节点.
    返回 dict: {node, host, port, is_local, latency_ms, route_source}
    找不到返回 None
    """
    if not _ROUTER_READY:
        discover()

    # 精确匹配
    if model_name in _MODEL_TABLE:
        pick = _MODEL_TABLE[model_name][0]  # 已按本地+低延迟排序
        return {**pick, "route_source": "discovered"}

    # 模糊匹配 (忽略 tag)
    base = model_name.split(":")[0] if ":" in model_name else model_name
    for known_name, entries in _MODEL_TABLE.items():
        if known_name.split(":")[0] == base:
            pick = entries[0]
            return {**pick, "route_source": "fuzzy_match"}

    return None


def available_models() -> List[str]:
    """列出所有已发现的唯一模型名"""
    if not _ROUTER_READY:
        discover()
    return sorted(_MODEL_TABLE.keys())


def health_check() -> Dict:
    """全节点健康快照"""
    return discover()


def get_ollama_base_url(model_name: str = "", prefer_local: bool = True) -> Optional[str]:
    """
    便捷方法: 直接拿 Ollama base URL
    本地优先 → 找不到再远程 → 找不到返回 None
    """
    if not _ROUTER_READY:
        discover()

    if model_name:
        route = route_model(model_name)
        if route:
            return f"http://{route['host']}:{route['port']}"
        return None

    # 无参: 拿本机 Ollama 或第一个在线的
    self_url = None
    remote_url = None
    for name, entries in _MODEL_TABLE.items():
        for e in entries:
            if e["is_local"] and self_url is None:
                self_url = f"http://{e['host']}:{e['port']}"
            elif remote_url is None:
                remote_url = f"http://{e['host']}:{e['port']}"

    if prefer_local and self_url:
        return self_url
    return self_url or remote_url


# ====================================================================
# 渲染
# ====================================================================

def _render_table(result: Dict) -> str:
    """终端渲染聚合模型表"""
    lines = []
    topo = result["topology"]
    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║  算力路由拓扑                                              ║")
    lines.append("╠══════════════════════════════════════════════════════════╣")
    lines.append(f"║  Self: {result['self_name']:10s}  Nodes: {topo['online_nodes']}/{topo['total_nodes']}  "
                 f"Aggregable: {'YES ✅' if result['is_lan_aggregable'] else 'NO ❌':6s}  ║")
    lines.append("╚══════════════════════════════════════════════════════════╝")
    lines.append("")

    # 节点状态
    lines.append("─── 节点状态 ───")
    lines.append(f"  {'Node':10s} {'Role':14s} {'Host':16s} {'Ollama':7s} {'Models':7s} {'Latency':>8s} {'IsSelf':7s}")
    for name, st in result["node_status"].items():
        lat_str = f"{st['tailscale_latency_ms']:.0f}ms" if st.get("tailscale_latency_ms") else "N/A"
        online = "🟢" if st["ollama_online"] else "🔴"
        self_mark = "⭐" if st["is_self"] else ""
        lines.append(f"  {name:10s} {st['role']:14s} {st['host']:16s} {online+'':7s} {st['model_count']:7d} {lat_str:>8s} {self_mark:7s}")

    lines.append("")
    lines.append(f"─── 聚合模型表 ({result['unique_model_count']} 个唯一模型) ───")
    for name, entries in sorted(result["model_table"].items()):
        where = " + ".join(
            ("⭐" if e["is_local"] else "🔗") + e["node"]
            for e in entries
        )
        lines.append(f"  {name:30s}  [{where}]")

    return "\n".join(lines)


# ====================================================================
# CLI
# ====================================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "discover":
        result = discover()
        print(_render_table(result))

    elif cmd == "route":
        if len(sys.argv) < 3:
            print("Usage: compute_router.py route <model_name>")
            sys.exit(1)
        route = route_model(sys.argv[2])
        if route:
            print(json.dumps(route, indent=2, ensure_ascii=False))
        else:
            print(f"❌ 模型 {sys.argv[2]} 未发现")

    elif cmd == "health":
        result = discover()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "table":
        result = discover()
        print(_render_table(result))

    elif cmd == "url":
        model = sys.argv[2] if len(sys.argv) > 2 else ""
        url = get_ollama_base_url(model)
        print(url or "❌ 无可用 Ollama")

    elif cmd == "models":
        discover()
        for m in available_models():
            print(m)

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
