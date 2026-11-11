"""
_common/workflows.py — 引擎级基础工作流注册
==========================================

把 andromeda_workflow_engine.py 里原有的 6 个工作流注册到去中心化 registry.
"""
# [unused] import os, sys, json, sqlite3, time, uuid, importlib

def _get_app_db():
    """env-first + PROD 本地优先 — 和 db_resolver.py 统一."""
    prod = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
    onedrive = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'app.db'))
    for k in ("ANDROMEDA_DB", "APP_DB"):
        v = os.environ.get(k)
        if v and os.path.exists(v) and os.path.getsize(v) > 1_000_000:
            return v
    if os.path.exists(prod) and os.path.getsize(prod) > 1_000_000:
        return prod
    return onedrive


# ── handler 实现 ──

def _h_vectorize(input):
    """wf_vectorize_text — 本地 Ollama nomic-embed-text 向量化."""
    text = (input.get("text") or input.get("content") or "")[:8000]
    if not text:
        return {"status": "FAILED", "output": {}, "error": "no text", "wall_ms": 0}
    import requests
    t0 = time.time()
    try:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        r = requests.post(
            f"{host}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=60)
        if r.status_code != 200:
            return {"status": "FAILED", "output": {}, "error": f"ollama {r.status_code}",
                    "wall_ms": int((time.time() - t0) * 1000)}
        emb = r.json().get("embedding", [])
        return {"status": "SUCCESS", "output": {"embedding_dim": len(emb), "chars": len(text),
                                                  "truncated": len(text) >= 8000},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e), "wall_ms": int((time.time() - t0) * 1000)}


def _h_knowledge_ingest(input):
    """wf_knowledge_ingest — 把 sources 写入 ai_brain_enhanced_knowledge 主表."""
    sources = input.get("sources") or []
    domain = input.get("domain", "workflow")
    if not sources:
        return {"status": "FAILED", "output": {}, "error": "no sources", "wall_ms": 0}
    db = _get_app_db()
    t0 = time.time()
    ingested = 0
    try:
        conn = sqlite3.connect(db, timeout=15)
        for src in sources:
            content = src.get("content", "")[:4000]
            title = src.get("title", "")[:200]
            if not content:
                continue
            conn.execute(
                """INSERT INTO ai_brain_enhanced_knowledge
                   (knowledge_id, category, title, content, knowledge_type,
                    tags, confidence_score, usage_count, is_active, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (f"{domain}::{uuid.uuid4().hex[:12]}", domain, title, content,
                 "workflow_ingest",
                 json.dumps(src.get("tags", [domain]), ensure_ascii=False)[:500],
                 src.get("confidence", 0.7), 0, 1, time.time(), time.time()))
            ingested += 1
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "output": {"ingested": ingested, "domain": domain,
                                                  "db": os.path.basename(os.path.dirname(db))},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {"ingested": ingested},
                "error": str(e), "wall_ms": int((time.time() - t0) * 1000)}


def _h_hire_employee(input):
    """wf_hire_employee — 代理 ai_auto_hire_engine 的 hire_employees()."""
    count = max(1, int(input.get("count", input.get("max_new", 3))))
    min_level = input.get("min_level", 7)
    t0 = time.time()
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        import ai_auto_hire_engine as hire
        result = hire.hire_employees(count=count, min_level=min_level)
        return {"status": "SUCCESS",
                "output": {"hired": result.get("hired", 0), "bridged": result.get("bridged", 0),
                           "invited": result.get("invited", 0), "total": result.get("total", 0)},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e), "wall_ms": int((time.time() - t0) * 1000)}


def _h_evolution_trigger(input):
    """wf_evolution_trigger — 代理 andromeda_auto_evolution.run_cycle()."""
    t0 = time.time()
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        import andromeda_auto_evolution as ev
        ev.reset_evolution_event() if hasattr(ev, 'reset_evolution_event') else None
        result = ev.run_cycle()
        return {"status": "SUCCESS",
                "output": {"cycle": result.get("cycle", "?"), "stages": result.get("stages", {}),
                           "skipped": result.get("skipped", False)},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e), "wall_ms": int((time.time() - t0) * 1000)}


def _h_code_hygiene(input):
    """wf_code_hygiene — 对目标文件做语法/导入检查."""
    target = input.get("target") or input.get("path")
    t0 = time.time()
    issues = []
    checked = 0
    try:
        if target and os.path.exists(target):
            import ast
            try:
                with open(target) as f:
                    ast.parse(f.read())
            except SyntaxError as se:
                issues.append(f"SyntaxError L{se.lineno}: {se.msg}")
            checked = 1
            # 导入检查
            try:
                import py_compile
                py_compile.compile(target, doraise=True)
            except py_compile.PyCompileError as pe:
                issues.append(f"ImportError: {pe}")
        return {"status": "SUCCESS",
                "output": {"checked": checked, "issues": issues, "issue_count": len(issues)},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {"checked": checked}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


def _h_translate_batch(input):
    """wf_translate_batch — 简单直译 (本地 Ollama 兜底)."""
    texts = input.get("texts") or []
    target = input.get("target_lang", "en")
    t0 = time.time()
    translated = []
    try:
        import requests
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        for t in texts[:20]:
            try:
                r = requests.post(
                    f"{host}/api/generate",
                    json={"model": "qwen2.5:7b", "prompt": f"Translate to {target}: {t[:500]}",
                          "stream": False},
                    timeout=60)
                if r.status_code == 200:
                    translated.append(r.json().get("response", "").strip())
                else:
                    translated.append("")
            except Exception:
                translated.append("")
        return {"status": "SUCCESS",
                "output": {"translated": translated, "count": len(translated), "target_lang": target},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {"count": 0}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ── 注册入口 ──

def register_workflows(registry, register_fn):
    """_common/ 基础引擎级 workflow."""
    register_fn("wf_vectorize_text", {
        "name": "文本向量化", "domain": "engine",
        "description": "本地 Ollama nomic-embed-text 向量化 (零 token, 零成本)",
        "price_per_unit": 0.01, "pricing_unit": "1K chars",
        "handler": _h_vectorize, "requires": ["OLLAMA", "PROD_DB"],
        "tags": ["embed", "rag", "brain"],
    })
    register_fn("wf_knowledge_ingest", {
        "name": "知识摄入", "domain": "engine",
        "description": "sources 批量写入 ai_brain_enhanced_knowledge 主表",
        "price_per_unit": 0.05, "pricing_unit": "item",
        "handler": _h_knowledge_ingest, "requires": ["PROD_DB"],
        "tags": ["brain", "ingest", "knowledge"],
    })
    register_fn("wf_hire_employee", {
        "name": "AI 员工雇佣", "domain": "engine",
        "description": "雇佣新 AI 员工 + EigenFlux 邀请 + 桥接配对",
        "price_per_unit": 1.00, "pricing_unit": "员工",
        "handler": _h_hire_employee, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["hire", "org_growth", "empower"],
    })
    register_fn("wf_evolution_trigger", {
        "name": "进化触发", "domain": "engine",
        "description": "仙女座自动进化周期 (eigenflux ingest + detect + optimize)",
        "price_per_unit": 5.00, "pricing_unit": "cycle",
        "handler": _h_evolution_trigger, "requires": ["PROD_DB", "OLLAMA"],
        "tags": ["evolution", "self_heal", "trigger"],
    })
    register_fn("wf_code_hygiene", {
        "name": "代码卫生", "domain": "engine",
        "description": "AST 语法 + 导入检查",
        "price_per_unit": 0.05, "pricing_unit": "K LOC",
        "handler": _h_code_hygiene, "requires": [],
        "tags": ["lint", "qa", "ast"],
    })
    register_fn("wf_translate_batch", {
        "name": "批量翻译", "domain": "engine",
        "description": "本地 Ollama qwen2.5 批量翻译",
        "price_per_unit": 0.02, "pricing_unit": "1K chars",
        "handler": _h_translate_batch, "requires": ["OLLAMA"],
        "tags": ["translate", "i18n"],
    })
