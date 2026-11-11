"""
Mock Semantica REST Server
==========================

一个轻量级的 Semantica REST API mock server，用于 OpenClaw 集成层的
沙盒测试和上线前验证。所有端点返回结构化 JSON，不依赖 semantica 包。

运行:
    python3 mock_semantica_server.py --port 8000

端点:
    POST /extract       → 实体/关系抽取
    POST /entities       → 添加节点
    POST /relationships  → 添加边
    POST /decisions      → 记录决策
    GET  /decisions/search   → 搜索决策
    POST /decisions/precedents → 先例搜索
    GET  /causal-chain   → 因果链
    POST /reason         → 推理
    GET  /analytics      → 图分析
    GET  /export         → 导出
    GET  /graph/summary  → 图概要
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# 内存图存储（单例，线程安全）
# ---------------------------------------------------------------------------

class MockKnowledgeGraph:
    def __init__(self) -> None:
        self.entities: Dict[str, Dict[str, Any]] = {}       # id → entity
        self.relationships: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def add_entity(self, label: str, type: str, **props: Any) -> Dict[str, Any]:
        with self._lock:
            eid = self.new_id()
            ent = {"id": eid, "label": label, "type": type, "properties": props, "created_at": time.time()}
            self.entities[eid] = ent
            return ent

    def add_relationship(self, source: str, target: str, rel_type: str, **props: Any) -> Dict[str, Any]:
        with self._lock:
            rid = self.new_id()
            rel = {"id": rid, "source": source, "target": target, "type": rel_type, "properties": props, "created_at": time.time()}
            self.relationships.append(rel)
            return rel

    def add_decision(self, decision: str, context: str | None = None, **meta: Any) -> Dict[str, Any]:
        with self._lock:
            did = self.new_id()
            dec = {"id": did, "decision": decision, "context": context, "metadata": meta, "created_at": time.time()}
            self.decisions.append(dec)
            return dec

    def search_decisions(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            q = query.lower()
            results = [d for d in self.decisions if q in d["decision"].lower() or (d.get("context") and q in d["context"].lower())]
            return results[:limit]

    def precedents(self, decision_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        # 简单的关键词重叠模拟"相似度"
        with self._lock:
            words = set(decision_text.lower().split())
            scored = []
            for d in self.decisions:
                d_words = set((d["decision"] + " " + (d.get("context") or "")).lower().split())
                overlap = len(words & d_words)
                scored.append((overlap, d))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [d for _, d in scored[:top_k]]

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "entity_count": len(self.entities),
                "relationship_count": len(self.relationships),
                "decision_count": len(self.decisions),
                "node_types": list({e["type"] for e in self.entities.values()}),
                "edge_types": list({r["type"] for r in self.relationships}),
                "generated_at": time.time(),
            }

    def analytics(self) -> Dict[str, Any]:
        with self._lock:
            # 简单度中心性
            degree: Dict[str, int] = {}
            for r in self.relationships:
                degree[r["source"]] = degree.get(r["source"], 0) + 1
                degree[r["target"]] = degree.get(r["target"], 0) + 1
            top = sorted(degree.items(), key=lambda x: x[1], reverse=True)[:10]
            return {
                "top_degree_nodes": [{"id": n, "degree": d} for n, d in top],
                "communities_count": max(1, len(self.entities) // 5),
                "avg_degree": sum(degree.values()) / max(1, len(self.entities)),
            }

    def export(self, fmt: str = "json") -> Dict[str, Any]:
        with self._lock:
            if fmt == "json":
                return {
                    "format": "json",
                    "data": json.dumps({
                        "entities": list(self.entities.values()),
                        "relationships": self.relationships,
                        "decisions": self.decisions,
                    }, ensure_ascii=False, indent=2)[:10000],
                }
            return {"format": fmt, "data": "<graph data truncated in mock>"}


kg = MockKnowledgeGraph()


# ---------------------------------------------------------------------------
# 实体抽取（简单关键词匹配模拟 spaCy/NER）
# ---------------------------------------------------------------------------

def mock_extract(text: str) -> Dict[str, Any]:
    """从文本中模拟抽取实体和关系。"""
    entities: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []

    # 简单大写开头名词 → 可能的实体
    words = text.split()
    seen: set[str] = set()
    for w in words:
        clean = w.strip(".,;:!?\"'()[]")
        if len(clean) >= 2 and clean[0].isupper() and clean.lower() not in seen:
            seen.add(clean.lower())
            eid = kg.add_entity(clean, "Concept")
            entities.append({"id": eid["id"], "label": clean, "type": "Concept", "confidence": 0.7})

    # 股票代码识别
    import re
    codes = re.findall(r"\b(s[hz]\d{6}|idx_[a-z_]+|stk_\d+)\b", text, re.IGNORECASE)
    for code in codes:
        if code.lower() not in seen:
            seen.add(code.lower())
            eid = kg.add_entity(code.upper(), "Stock")
            entities.append({"id": eid["id"], "label": code.upper(), "type": "Stock", "confidence": 0.95})

    return {
        "entities": entities,
        "relations": relations,
        "text": text[:200],
        "mock": True,
    }


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class MockSemanticaHandler(BaseHTTPRequestHandler):
    server_version = "MockSemantica/0.6.8"

    def log_message(self, fmt: str, *args: Any) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {fmt % args}", file=sys.stderr, flush=True)

    def _send_json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        params = {}
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
            for pair in qs.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v

        try:
            if path == "/graph/summary":
                self._send_json(200, kg.summary())
            elif path == "/analytics":
                self._send_json(200, kg.analytics())
            elif path == "/export":
                fmt = params.get("format", "json")
                self._send_json(200, kg.export(fmt))
            elif path == "/decisions/search":
                q = params.get("q", "")
                limit = int(params.get("limit", 10))
                self._send_json(200, {"decisions": kg.search_decisions(q, limit)})
            elif path == "/causal-chain":
                node_id = params.get("node_id", "")
                depth = int(params.get("depth", 3))
                self._send_json(200, {"node_id": node_id, "depth": depth, "chain": [], "mock": True})
            elif path == "/healthz":
                self._send_json(200, {"status": "ok", "mock": True, "uptime": time.time() - _START})
            else:
                self._send_json(404, {"error": f"Unknown endpoint: {path}", "mock": True})
        except Exception as e:
            self._send_json(500, {"error": str(e), "mock": True})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        body = self._read_body()

        try:
            if path == "/extract":
                result = mock_extract(body.get("text", ""))
                self._send_json(200, result)
            elif path == "/entities":
                label = body.get("label", "")
                ent_type = body.get("type", "Entity")
                props = {k: v for k, v in body.items() if k not in ("label", "type")}
                result = kg.add_entity(label, ent_type, **props)
                self._send_json(200, result)
            elif path == "/relationships":
                result = kg.add_relationship(
                    body.get("source", ""),
                    body.get("target", ""),
                    body.get("type", "related_to"),
                )
                self._send_json(200, result)
            elif path == "/decisions":
                result = kg.add_decision(
                    body.get("decision", ""),
                    body.get("context"),
                    **{k: v for k, v in body.items() if k not in ("decision", "context")},
                )
                self._send_json(200, result)
            elif path == "/decisions/precedents":
                decision = body.get("decision", "")
                top_k = int(body.get("top_k", 5))
                self._send_json(200, {"precedents": kg.precedents(decision, top_k)})
            elif path == "/reason":
                self._send_json(200, {
                    "conclusion": "Mock reasoning engine: rules matched 0, facts consumed 0",
                    "rules_count": len(body.get("rules", [])),
                    "facts_count": len(body.get("facts", [])),
                    "mock": True,
                })
            else:
                self._send_json(404, {"error": f"Unknown endpoint: {path}", "mock": True})
        except Exception as e:
            self._send_json(500, {"error": str(e), "mock": True})


_START = time.time()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Semantica REST Server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockSemanticaHandler)
    print(f"🤖 Mock Semantica REST Server starting on http://{args.host}:{args.port}")
    print(f"   所有端点返回 mock 数据 — 用于 OpenClaw 集成层沙盒测试")
    print(f"   按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Mock Semantica server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
