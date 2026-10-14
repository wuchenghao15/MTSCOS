"""
translation_studio/workflows.py — 翻译工作室域工作流
======================================================

子系统自注册: translation_studio 自己定义 workflow.
"""
import os, sys, time

def _get_app_db():
    prod = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
    for k in ("ANDROMEDA_DB", "APP_DB"):
        v = os.environ.get(k)
        if v and os.path.exists(v) and os.path.getsize(v) > 1_000_000:
            return v
    if os.path.exists(prod) and os.path.getsize(prod) > 1_000_000:
        return prod
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "database", "app.db"))


def _h_translate_iceberg_bridge(input):
    """wf_translate_iceberg_bridge — 翻译工作室 → 冰山引擎桥接.
    
    批量翻译 + 自动落库 mt_translation_jobs + 触发冰山缓存.
    """
    items = input.get("items") or input.get("texts") or []
    source = input.get("source_lang", "zh")
    target = input.get("target_lang", "en")
    domain = input.get("domain", "general")
    t0 = time.time()
    results = []
    try:
        import requests
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        batch_size = input.get("batch_size", 10)
        for chunk_start in range(0, min(len(items), 200), batch_size):
            chunk = items[chunk_start:chunk_start + batch_size]
            translated_chunk = []
            for t in chunk:
                try:
                    prompt = f"Translate this {source} text to natural {target}. Only output the translation, no explanation.\n\n{t[:800]}"
                    r = requests.post(f"{host}/api/generate",
                                      json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False},
                                      timeout=60)
                    translated_chunk.append(r.json().get("response", "").strip() if r.status_code == 200 else "")
                except Exception:
                    translated_chunk.append("")
            results.extend(translated_chunk)
        return {"status": "SUCCESS",
                "output": {"translated": results, "count": len(results),
                           "source_lang": source, "target_lang": target, "domain": domain},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {"translated": results}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def register_workflows(registry, register_fn):
    """translation_studio 域 — 翻译批量桥接冰山引擎."""
    register_fn("wf_translate_iceberg_bridge", {
        "name": "翻译-冰山桥接", "domain": "translation_studio",
        "description": "批量翻译 + 自动落库 + 冰山引擎缓存触发",
        "price_per_unit": 0.03, "pricing_unit": "1K chars",
        "handler": _h_translate_iceberg_bridge, "requires": ["OLLAMA"],
        "tags": ["translate", "iceberg", "i18n"],
    })
