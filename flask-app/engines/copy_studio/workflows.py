"""
copy_studio/workflows.py — 文案工作室域工作流
==============================================

子系统自注册: copy_studio 自己定义自己的 workflow, 不需要 engine 中央列表追加.
"""
import os, sys, json, time, sqlite3

def _get_app_db():
    prod = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
    for k in ("ANDROMEDA_DB", "APP_DB"):
        v = os.environ.get(k)
        if v and os.path.exists(v) and os.path.getsize(v) > 1_000_000:
            return v
    if os.path.exists(prod) and os.path.getsize(prod) > 1_000_000:
        return prod
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "database", "app.db"))


def _h_copy_variant(input):
    """wf_copy_variant — 基于 seed 文案生成 N 个变体 + 持久化."""
    seed = (input.get("seed") or input.get("content") or "")[:2000]
    count = max(1, min(10, int(input.get("count", 3))))
    domain = input.get("domain", "copy_studio")
    variants = input.get("variants", [])  # 可选: 直接传 variants 跳过生成
    t0 = time.time()
    try:
        if not variants and seed:
            # 本地 Ollama 兜底生成
            import requests
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            prompt = f"""Generate {count} distinct creative variants for this ad copy.
Seed: "{seed[:800]}"
Output each variant on its own line, prefixed by "V1:", "V2:", etc (1-indexed)."""
            r = requests.post(f"{host}/api/generate",
                              json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False},
                              timeout=90)
            if r.status_code == 200:
                raw = r.json().get("response", "")
                variants = [l.split(":", 1)[-1].strip() for l in raw.split("\n") if ":" in l][:count]
        # 持久化到 PROD DB (copy_studio 的表)
        saved = 0
        db = _get_app_db()
        try:
            conn = sqlite3.connect(db, timeout=10)
            for v in variants:
                conn.execute(
                    """INSERT INTO mt_copy_variants
                       (seed_hash, variant_text, domain, source, created_at)
                       VALUES (?,?,?,?,datetime('now','localtime'))""",
                    (str(hash(seed))[:16], v[:2000], domain, "workflow"))
                saved += 1
            conn.commit()
            conn.close()
        except Exception:
            # 表不存在时跳过持久化 (不影响返回 variants)
            pass
        return {"status": "SUCCESS",
                "output": {"variants": variants, "variant_count": len(variants), "saved": saved},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_copy_semantic_audit(input):
    """wf_copy_semantic_audit — 语义合规审查 (敏感词 + 歧义检测)."""
    text = (input.get("text") or input.get("content") or "")[:3000]
    t0 = time.time()
    flags = []
    try:
        # 1) 硬编码敏感词扫描 (本地零成本)
        SENSITIVE = ["赌博", "毒品", "色情", "暴力", "恐怖", "自杀", "传销"]
        for kw in SENSITIVE:
            if kw in text:
                flags.append({"type": "sensitive_word", "keyword": kw, "severity": "high"})
        # 2) 本地 Ollama 语义审查
        try:
            import requests
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            r = requests.post(f"{host}/api/generate",
                              json={"model": "qwen2.5:7b",
                                    "prompt": f"Scan this text for semantic issues (hate, misleading, claims without evidence). Return JSON array of flags with keys: type, severity, explanation.\n\nText: '{text[:1000]}'\n\nJSON:",
                                    "stream": False},
                              timeout=60)
            if r.status_code == 200:
                import re
                raw = r.json().get("response", "")
                arr_match = re.search(r"\[.*\]", raw, re.DOTALL)
                if arr_match:
                    ollama_flags = json.loads(arr_match.group())
                    flags.extend(ollama_flags if isinstance(ollama_flags, list) else [])
        except Exception:
            pass
        return {"status": "SUCCESS",
                "output": {"flags": flags, "flag_count": len(flags),
                           "passed": len(flags) == 0},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {"flags": flags}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def register_workflows(registry, register_fn):
    """copy_studio 域 — 文案变体生成 + 语义审查."""
    register_fn("wf_copy_variant", {
        "name": "文案变体生成", "domain": "copy_studio",
        "description": "基于 seed 文案生成 N 个创意变体 (本地 Ollama + 持久化)",
        "price_per_unit": 0.10, "pricing_unit": "variant",
        "handler": _h_copy_variant, "requires": ["OLLAMA"],
        "tags": ["copy", "variant", "creative"],
    })
    register_fn("wf_copy_semantic_audit", {
        "name": "文案语义审查", "domain": "copy_studio",
        "description": "敏感词扫描 + 本地 Ollama 语义歧义检测",
        "price_per_unit": 0.05, "pricing_unit": "1K chars",
        "handler": _h_copy_semantic_audit, "requires": ["OLLAMA"],
        "tags": ["copy", "audit", "compliance"],
    })
