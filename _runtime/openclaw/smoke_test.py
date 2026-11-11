#!/usr/bin/env python3
"""
OpenClawKGTool 完整沙盒测试
=============================

在同一个 Python 进程里启动 mock Semantica server（后台线程），
然后用 OpenClawKGTool 跑所有端点，包含 SSRF 防护复测。
"""

from __future__ import annotations

import sys, os, json, time, threading, socket, uuid, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# ---------------------------------------------------------------------------
# Mock KG (内嵌)
# ---------------------------------------------------------------------------

class MockKG:
    def __init__(self):
        self.entities = {}
        self.relationships = []
        self.decisions = []
        self._lock = threading.Lock()

    def nid(self): return uuid.uuid4().hex[:12]

    def add_entity(self, label, type_, **kw):
        with self._lock:
            e = {"id": self.nid(), "label": label, "type": type_, "props": kw, "ts": time.time()}
            self.entities[e["id"]] = e
            return e

    def add_rel(self, s, t, ty, **kw):
        with self._lock:
            r = {"id": self.nid(), "source": s, "target": t, "type": ty, "props": kw, "ts": time.time()}
            self.relationships.append(r); return r

    def add_dec(self, d, ctx=None, **kw):
        with self._lock:
            x = {"id": self.nid(), "decision": d, "context": ctx, "meta": kw, "ts": time.time()}
            self.decisions.append(x); return x

    def search_dec(self, q, limit=10):
        with self._lock:
            qq = q.lower()
            return [d for d in self.decisions if qq in d["decision"].lower() or (d.get("context") and qq in d["context"].lower())][:limit]

    def precedents(self, text, top_k=5):
        with self._lock:
            words = set(text.lower().split())
            scored = []
            for d in self.decisions:
                dw = set((d["decision"] + " " + (d.get("context") or "")).lower().split())
                scored.append((len(words & dw), d))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [d for _, d in scored[:top_k]]

    def summary(self):
        with self._lock:
            return {"entity_count": len(self.entities), "relationship_count": len(self.relationships),
                    "decision_count": len(self.decisions),
                    "node_types": list({e["type"] for e in self.entities.values()}),
                    "edge_types": list({r["type"] for r in self.relationships}), "generated_at": time.time()}

    def analytics(self):
        with self._lock:
            deg = {}
            for r in self.relationships:
                deg[r["source"]] = deg.get(r["source"], 0) + 1
                deg[r["target"]] = deg.get(r["target"], 0) + 1
            top = sorted(deg.items(), key=lambda x: x[1], reverse=True)[:10]
            return {"top_degree_nodes": [{"id": n, "degree": d} for n, d in top],
                    "communities_count": max(1, len(self.entities) // 5),
                    "avg_degree": sum(deg.values()) / max(1, len(self.entities))}

    def export(self, fmt="json"):
        with self._lock:
            if fmt == "json":
                return {"format": "json", "data": json.dumps({"entities": list(self.entities.values()),
                        "relationships": self.relationships, "decisions": self.decisions}, ensure_ascii=False)[:10000]}
            return {"format": fmt, "data": "<mock>"}

KG = MockKG()

def mock_extract(text):
    ents, rels = [], []
    seen = set()
    for w in text.split():
        c = w.strip(".,;:!?\"'()[]")
        if len(c) >= 2 and c[0].isupper() and c.lower() not in seen:
            seen.add(c.lower())
            e = KG.add_entity(c, "Concept")
            ents.append({"id": e["id"], "label": c, "type": "Concept", "confidence": 0.7})
    for code in re.findall(r"\b(s[hz]\d{6}|idx_[a-z_]+|stk_\d+)\b", text, re.I):
        if code.lower() not in seen:
            seen.add(code.lower())
            e = KG.add_entity(code.upper(), "Stock")
            ents.append({"id": e["id"], "label": code.upper(), "type": "Stock", "confidence": 0.95})
    return {"entities": ents, "relations": rels, "mock": True}

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a): pass  # silence

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n: return {}
        return json.loads(self.rfile.read(n))

    def _q(self):
        if "?" not in self.path: return {}, self.path
        p, q = self.path.split("?", 1)
        return dict(x.split("=", 1) for x in q.split("&") if "=" in x), p

    def do_GET(self):
        params, path = self._q()
        try:
            if path == "/graph/summary": self._send(200, KG.summary())
            elif path == "/analytics": self._send(200, KG.analytics())
            elif path == "/export": self._send(200, KG.export(params.get("format", "json")))
            elif path == "/decisions/search":
                self._send(200, {"decisions": KG.search_dec(params.get("q", ""), int(params.get("limit", 10)))})
            elif path == "/causal-chain":
                self._send(200, {"chain": [], "mock": True})
            elif path == "/healthz":
                self._send(200, {"status": "ok", "mock": True})
            else: self._send(404, {"error": path})
        except Exception as e: self._send(500, {"error": str(e)})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        b = self._body()
        try:
            if path == "/extract": self._send(200, mock_extract(b.get("text", "")))
            elif path == "/entities":
                e = KG.add_entity(b.get("label", ""), b.get("type", "Entity"),
                                  **{k: v for k, v in b.items() if k not in ("label", "type")})
                self._send(200, e)
            elif path == "/relationships":
                r = KG.add_rel(b.get("source", ""), b.get("target", ""), b.get("type", "related_to"))
                self._send(200, r)
            elif path == "/decisions":
                d = KG.add_dec(b.get("decision", ""), b.get("context"),
                               **{k: v for k, v in b.items() if k not in ("decision", "context")})
                self._send(200, d)
            elif path == "/decisions/precedents":
                self._send(200, {"precedents": KG.precedents(b.get("decision", ""), int(b.get("top_k", 5)))})
            elif path == "/reason":
                self._send(200, {"conclusion": "Mock reasoning", "rules_count": len(b.get("rules", [])),
                                  "facts_count": len(b.get("facts", [])), "mock": True})
            else: self._send(404, {"error": path})
        except Exception as e: self._send(500, {"error": str(e)})

# ---------------------------------------------------------------------------
# 找空闲端口 + 启动 server
# ---------------------------------------------------------------------------

def _find_free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

PORT = _find_free_port()
SERVER = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
time.sleep(0.3)

# ---------------------------------------------------------------------------
# 现在跑 OpenClawKGTool smoke test
# ---------------------------------------------------------------------------

from ai_engines._semantica_fusion.integrations.openclaw import OpenClawKGTool, OpenClawMCPConfig

BASE_URL = f"http://localhost:{PORT}"
print(f"🤖 Mock Semantica on {BASE_URL}")
print("=" * 60)
print("📊 OpenClawKGTool 沙盒 Smoke Test")
print("=" * 60)

t = OpenClawKGTool(base_url=BASE_URL, timeout=10)
print(f"\n✅ 初始化: {t}")

results = []

# Test 1: extract
print("\n[1/10] extract() 实体抽取")
try:
    r = t.extract("今天推演了宁德时代 sz300750 和中芯国际 sh688981，大盘 idx_sh 跌破 3000")
    print(f"  ✅ 实体数={len(r['entities'])}, 关系数={len(r['relations'])}")
    for e in r["entities"][:5]: print(f"    - {e['label']} ({e['type']})")
    results.append(("extract", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("extract", False))

# Test 2: add_entity
print("\n[2/10] add_entity()")
try:
    e1 = t.add_entity("张博士", "Person", role="十专家")
    e2 = t.add_entity("仙女座沙盘", "Project", ver="v1")
    e3 = t.add_entity("mt_lab_task_hall", "System")
    print(f"  ✅ 3 实体: ids={e1['id'][:6]}..., {e2['id'][:6]}..., {e3['id'][:6]}...")
    results.append(("add_entity", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("add_entity", False))

# Test 3: add_relationship
print("\n[3/10] add_relationship()")
try:
    rel = t.add_relationship(e1['id'], e2['id'], "architected")
    print(f"  ✅ {e1['label']} → {e2['label']} ({rel['type']})")
    results.append(("add_relationship", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("add_relationship", False))

# Test 4: record_decision
print("\n[4/10] record_decision()")
try:
    d1 = t.record_decision("ERR_ABORTED 根因是 Vite /@vite/client 残留", context="沙盘调试", severity="P0")
    d2 = t.record_decision("SSRf 漏拦 0.0.0.0 → fallback 加 hostname 黑名单 + CIDR", context="安全加固", severity="P0")
    d3 = t.record_decision("semantica 不支持 Python 3.14", context="依赖诊断", severity="P1")
    print(f"  ✅ 3 决策: ids={d1['id'][:6]}..., {d2['id'][:6]}..., {d3['id'][:6]}...")
    results.append(("record_decision", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("record_decision", False))

# Test 5: query_decisions
print("\n[5/10] query_decisions('SSRf')")
try:
    r = t.query_decisions("SSRf", limit=5)
    print(f"  ✅ {len(r)} 条")
    for x in r: print(f"    - [{x.get('severity','?')}] {x['decision'][:50]}")
    results.append(("query_decisions", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("query_decisions", False))

# Test 6: find_precedents
print("\n[6/10] find_precedents('安全漏洞')")
try:
    p = t.find_precedents("安全漏洞修复方案", top_k=3)
    print(f"  ✅ {len(p)} 条先例"); results.append(("find_precedents", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("find_precedents", False))

# Test 7: get_graph_summary
print("\n[7/10] get_graph_summary()")
try:
    s = t.get_graph_summary()
    print(f"  ✅ 实体={s['entity_count']}, 关系={s['relationship_count']}, 决策={s['decision_count']}")
    print(f"     node_types={s.get('node_types', [])}")
    results.append(("get_graph_summary", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("get_graph_summary", False))

# Test 8: get_graph_analytics
print("\n[8/10] get_graph_analytics()")
try:
    a = t.get_graph_analytics()
    print(f"  ✅ top_degree={a['top_degree_nodes'][:3]}, avg_deg={a['avg_degree']:.1f}")
    results.append(("get_graph_analytics", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("get_graph_analytics", False))

# Test 9: run_reasoning
print("\n[9/10] run_reasoning()")
try:
    reason = t.run_reasoning(rules=["X → Y"], facts=["沙盘上线", "SSRf 修复"])
    print(f"  ✅ conclusion: {reason['conclusion']}")
    results.append(("run_reasoning", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("run_reasoning", False))

# Test 10: export_graph
print("\n[10/10] export_graph()")
try:
    exp = t.export_graph("json")
    print(f"  ✅ json → {len(exp)} 字符"); results.append(("export_graph", True))
except Exception as e:
    print(f"  ❌ {e}"); results.append(("export_graph", False))

# MCP Config
print("\n[MCP] OpenClawMCPConfig → mcporter.json")
cfg = OpenClawMCPConfig()
print(cfg.to_json())

# SSRF
print("\n" + "=" * 60)
print("🛡️  SSRF 防护复测")
print("=" * 60)
ssrf_tests = [
    ("http://localhost:8000", True),
    ("http://127.0.0.1:8000", False),
    ("http://0.0.0.0:22", False),
    ("http://169.254.169.254", False),
    ("http://127.0.0.1:6379", False),
    ("http://10.0.0.1:80", False),
    ("http://192.168.1.1:8080", False),
    ("http://172.17.0.1:2375", False),
    ("ftp://evil.com", False),
    ("http://", False),
    ("https://api.external.com:8000", True),
    ("http://mtos.site:8000", True),
]
ssrf_pass = 0
for url, should_pass in ssrf_tests:
    try:
        OpenClawKGTool(base_url=url, timeout=5)
        ok = should_pass
    except Exception:
        ok = not should_pass
    ssrf_pass += 1 if ok else 0
    mark = "✅" if ok else "❌"
    print(f"  {mark} {url}")

print(f"\n📊 SSRF: {ssrf_pass}/{len(ssrf_tests)}")
print("=" * 60)

# 总结
ok = sum(1 for _, v in results if v)
total = len(results)
print(f"\n🎉 API 端点: {ok}/{total} 通过")
for name, v in results:
    print(f"  {'✅' if v else '❌'} {name}")

SERVER.shutdown()
print("\n✅ 完成 — mock Semantica server 已关闭")
