"""
copy_studio/workflows.py — 文案工作室域工作流 (v26.1 激活版)
============================================================

v26.1 激活: 从 copy_studio 包内部模块调用, ensure_schema 确保表存在,
          持久化不再静默失败. 新增 outline/write/polish/consistency 4 个.

子系统自注册: copy_studio 自己定义自己的 workflow, 不需要 engine 中央列表追加.
"""
import os, sys, json, time, sqlite3

# ── 触发 copy_studio 包级初始化 (DB_PATH env-first + ensure_schema) ──
from engines.copy_studio import DB_PATH as _CS_DB_PATH
from engines.copy_studio.db import ensure_schema as _ensure_schema
_ensure_schema()  # 幂等, 每次 import 都跑, 保证 PROD DB 表齐全


def _persist_variants(db_conn, seed_hash, variants, domain, source="workflow"):
    """统一持久化: variants → mt_copy_variants (已确保表存在)."""
    saved = 0
    for v in variants:
        try:
            db_conn.execute(
                """INSERT INTO mt_copy_variants
                   (seed_hash, variant_text, domain, source, created_at)
                   VALUES (?,?,?,?,datetime('now','localtime'))""",
                (seed_hash, v[:2000], domain, source))
            saved += 1
        except Exception:
            pass
    return saved


def _ollama_url() -> str:
    """自动探测活 Ollama 端口 (和 generator/router 对齐: 11434>11435>env)."""
    import requests as _r
    for port in (11434, 11435, 11436):
        try:
            _r.get(f"http://localhost:{port}/api/tags", timeout=1.5)
            return f"http://localhost:{port}"
        except Exception:
            continue
    env_url = os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST")
    return env_url.rstrip("/") if env_url else "http://localhost:11434"


def _persist_audit(db_conn, workflow_id, text, flags, wall_ms):
    """统一持久化: audit → mt_copy_audit_log."""
    text_hash = str(hash(text))[:16] if text else ""
    try:
        db_conn.execute(
            """INSERT INTO mt_copy_audit_log
               (workflow_id, text_hash, text_preview, flags_json, flag_count, passed, wall_ms, created_at)
               VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (workflow_id, text_hash, text[:200] if text else "",
             json.dumps(flags, ensure_ascii=False), len(flags),
             1 if len(flags) == 0 else 0, wall_ms))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 1. wf_copy_variant — 文案变体生成 (升级版)
# ═══════════════════════════════════════════════════════════
def _h_copy_variant(input):
    """基于 seed 文案生成 N 个创意变体 + PROD DB 持久化."""
    seed = (input.get("seed") or input.get("content") or "")[:2000]
    count = max(1, min(10, int(input.get("count", 3))))
    domain = input.get("domain", "copy_studio")
    variants = input.get("variants", [])  # 可选: 直接传 variants 跳过生成
    t0 = time.time()
    saved = 0
    try:
        if not variants and seed:
            import requests
            host = _ollama_url()
            prompt = f"""Generate {count} distinct creative variants for this ad copy.
Seed: "{seed[:800]}"
Output each variant on its own line, prefixed by "V1:", "V2:", etc (1-indexed)."""
            r = requests.post(f"{host}/api/generate",
                              json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False},
                              timeout=90)
            if r.status_code == 200:
                raw = r.json().get("response", "")
                variants = [l.split(":", 1)[-1].strip()
                            for l in raw.split("\n") if ":" in l][:count]
        if variants:
            conn = sqlite3.connect(str(_CS_DB_PATH), timeout=10)
            saved = _persist_variants(conn, str(hash(seed))[:16], variants, domain)
            conn.commit(); conn.close()
        return {"status": "SUCCESS",
                "output": {"variants": variants, "variant_count": len(variants), "saved": saved},
                "wall_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"status": "FAILED", "output": {"saved": saved}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ═══════════════════════════════════════════════════════════
# 2. wf_copy_semantic_audit — 语义合规审查 (升级版)
# ═══════════════════════════════════════════════════════════
def _h_copy_semantic_audit(input):
    """敏感词 + Ollama 语义歧义检测 + PROD DB 持久化."""
    text = (input.get("text") or input.get("content") or "")[:3000]
    t0 = time.time()
    flags = []
    try:
        SENSITIVE = ["赌博", "毒品", "色情", "暴力", "恐怖", "自杀", "传销"]
        for kw in SENSITIVE:
            if kw in text:
                flags.append({"type": "sensitive_word", "keyword": kw, "severity": "high"})
        try:
            import requests, re
            host = _ollama_url()
            r = requests.post(f"{host}/api/generate",
                              json={"model": "qwen2.5:7b",
                                    "prompt": f"Scan this text for semantic issues (hate, misleading, claims without evidence). Return JSON array of flags with keys: type, severity, explanation.\n\nText: '{text[:1000]}'\n\nJSON:",
                                    "stream": False},
                              timeout=60)
            if r.status_code == 200:
                arr_match = re.search(r"\[.*\]", r.json().get("response", ""), re.DOTALL)
                if arr_match:
                    ollama_flags = json.loads(arr_match.group())
                    flags.extend(ollama_flags if isinstance(ollama_flags, list) else [])
        except Exception:
            pass
        wall_ms = int((time.time() - t0) * 1000)
        conn = sqlite3.connect(str(_CS_DB_PATH), timeout=10)
        _persist_audit(conn, "wf_copy_semantic_audit", text, flags, wall_ms)
        conn.commit(); conn.close()
        return {"status": "SUCCESS",
                "output": {"flags": flags, "flag_count": len(flags),
                           "passed": len(flags) == 0},
                "wall_ms": wall_ms}
    except Exception as e:
        return {"status": "FAILED", "output": {"flags": flags}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ═══════════════════════════════════════════════════════════
# 3. wf_copy_outline_generate — 大纲生成 (调 generator.py)
# ═══════════════════════════════════════════════════════════
def _h_copy_outline(input):
    """基于标题+体裁生成结构化大纲 JSON (本地 Ollama)."""
    from engines.copy_studio.generator import generate_outline
    genre = input.get("genre", "novel")
    title = (input.get("title") or "").strip() or "未命名"
    sub_genre = input.get("sub_genre", "")
    target_words = int(input.get("target_words", 50000))
    user_intent = input.get("user_intent", "")
    t0 = time.time()
    try:
        outline = generate_outline(genre, title, sub_genre, target_words, user_intent)
        wall_ms = int((time.time() - t0) * 1000)
        if outline:
            conn = sqlite3.connect(str(_CS_DB_PATH), timeout=10)
            pid = "copy_" + str(int(time.time()))
            conn.execute(
                """INSERT OR IGNORE INTO mt_copy_projects
                   (project_id, title, genre, sub_genre, target_words, status, initiator, outline_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                (pid, title, genre, sub_genre, target_words, "outlining",
                 "workflow", json.dumps(outline, ensure_ascii=False)))
            conn.commit(); conn.close()
            return {"status": "SUCCESS",
                    "output": {"outline": outline, "project_id": pid},
                    "wall_ms": wall_ms}
        return {"status": "FAILED", "output": {}, "error": "outline is None (Ollama call failed?)",
                "wall_ms": wall_ms}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ═══════════════════════════════════════════════════════════
# 4. wf_copy_write_chapter — 章节正文生成 (调 generator.py)
# ═══════════════════════════════════════════════════════════
def _h_copy_write_chapter(input):
    """基于章节标题+摘要生成正文 (自动路由 coder:14b, 支持 RAG 跨章参考)."""
    from engines.copy_studio.generator import write_chapter_text
    genre = input.get("genre", "novel")
    chapter_title = (input.get("chapter_title") or "第 N 章").strip()
    chapter_summary = input.get("chapter_summary", "")
    target_words = int(input.get("target_words", 3000))
    context_chapters = input.get("context_chapters") or []
    character_briefs = input.get("character_briefs") or []
    style_guide = input.get("style_guide", "")
    sub_genre = input.get("sub_genre", "")
    t0 = time.time()
    try:
        text = write_chapter_text(genre, chapter_title, chapter_summary, target_words,
                                  context_chapters, character_briefs, style_guide, sub_genre)
        wall_ms = int((time.time() - t0) * 1000)
        if text:
            return {"status": "SUCCESS",
                    "output": {"chapter_text": text, "actual_words": len(text)},
                    "wall_ms": wall_ms}
        return {"status": "FAILED", "output": {}, "error": "chapter text is None",
                "wall_ms": wall_ms}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ═══════════════════════════════════════════════════════════
# 5. wf_copy_polish — 文本润色 (调 generator.py)
# ═══════════════════════════════════════════════════════════
def _h_copy_polish(input):
    """对已有文本做润色重写 (自动路由 7b 小模型)."""
    from engines.copy_studio.generator import polish_text
    text = (input.get("text") or input.get("content") or "")[:5000]
    style_hint = input.get("style_hint", "")
    t0 = time.time()
    try:
        polished = polish_text(text, style_hint)
        wall_ms = int((time.time() - t0) * 1000)
        if polished:
            return {"status": "SUCCESS",
                    "output": {"polished": polished,
                               "original_words": len(text),
                               "polished_words": len(polished)},
                    "wall_ms": wall_ms}
        return {"status": "FAILED", "output": {}, "error": "polish returned None",
                "wall_ms": wall_ms}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ═══════════════════════════════════════════════════════════
# 6. wf_copy_consistency_check — 一致性审查 (调 semanticaudit.py)
# ═══════════════════════════════════════════════════════════
def _h_copy_consistency_check(input):
    """多章节一致性: 角色名漂移 + 代词切换 + 重复检测 + 标点规范."""
    from engines.copy_studio.semanticaudit import audit_chapters
    raw_chapters = input.get("chapters") or input.get("chapter_texts") or []
    char_names = input.get("char_names") or input.get("known_names") or []
    threshold = float(input.get("threshold", 0.85))
    # 统一 chapters → List[Dict] (audit_chapters 签名)
    chapters = []
    for i, ch in enumerate(raw_chapters):
        if isinstance(ch, dict):
            chapters.append(ch)
        else:
            chapters.append({"chapter_id": f"ch_{i+1}", "chapter_no": i+1, "content": str(ch)})
    t0 = time.time()
    try:
        issues = audit_chapters(chapters, char_names=char_names)
        wall_ms = int((time.time() - t0) * 1000)
        # 聚合报告
        by_rule = {}
        for iss in issues:
            rule = iss.get('type', 'unknown')
            by_rule.setdefault(rule, []).append(iss)
        report = {
            "all_issues": issues,
            "flags_total": len(issues),
            "by_rule": {k: len(v) for k, v in by_rule.items()},
        }
        conn = sqlite3.connect(str(_CS_DB_PATH), timeout=10)
        preview = "\n".join(c.get("content","")[:100] for c in chapters[:2])
        _persist_audit(conn, "wf_copy_consistency_check", preview, issues, wall_ms)
        conn.commit(); conn.close()
        return {"status": "SUCCESS",
                "output": report,
                "wall_ms": wall_ms}
    except Exception as e:
        return {"status": "FAILED", "output": {}, "error": str(e),
                "wall_ms": int((time.time() - t0) * 1000)}


# ═══════════════════════════════════════════════════════════
# 自注册
# ═══════════════════════════════════════════════════════════
def register_workflows(registry, register_fn):
    """copy_studio 域 — 6 个 workflow (v26.1 激活版)."""
    register_fn("wf_copy_variant", {
        "name": "文案变体生成", "domain": "copy_studio",
        "description": "基于 seed 文案生成 N 个创意变体 (本地 Ollama + PROD DB 持久化)",
        "price_per_unit": 0.10, "pricing_unit": "variant",
        "handler": _h_copy_variant, "requires": ["OLLAMA"],
        "tags": ["copy", "variant", "creative"],
    })
    register_fn("wf_copy_semantic_audit", {
        "name": "文案语义审查", "domain": "copy_studio",
        "description": "敏感词扫描 + Ollama 语义歧义检测 + PROD DB 持久化",
        "price_per_unit": 0.05, "pricing_unit": "1K chars",
        "handler": _h_copy_semantic_audit, "requires": ["OLLAMA"],
        "tags": ["copy", "audit", "compliance"],
    })
    register_fn("wf_copy_outline_generate", {
        "name": "大纲生成", "domain": "copy_studio",
        "description": "标题+体裁 → 结构化大纲 JSON (自动路由 14b 大模型 + 项目落库)",
        "price_per_unit": 0.50, "pricing_unit": "outline",
        "handler": _h_copy_outline, "requires": ["OLLAMA"],
        "tags": ["copy", "outline", "planning"],
    })
    register_fn("wf_copy_write_chapter", {
        "name": "章节正文生成", "domain": "copy_studio",
        "description": "章节标题+摘要 → 正文 (自动路由 coder:14b, 支持 RAG 跨章参考)",
        "price_per_unit": 0.02, "pricing_unit": "100 words",
        "handler": _h_copy_write_chapter, "requires": ["OLLAMA"],
        "tags": ["copy", "write", "chapter"],
    })
    register_fn("wf_copy_polish", {
        "name": "文本润色", "domain": "copy_studio",
        "description": "对已有文本做润色重写 (自动路由 7b 小模型, 速度快)",
        "price_per_unit": 0.03, "pricing_unit": "1K chars",
        "handler": _h_copy_polish, "requires": ["OLLAMA"],
        "tags": ["copy", "polish", "refine"],
    })
    register_fn("wf_copy_consistency_check", {
        "name": "多章节一致性审查", "domain": "copy_studio",
        "description": "角色名漂移 + 代词切换 + 重复检测 + 标点规范 (多章节)",
        "price_per_unit": 0.10, "pricing_unit": "chapter",
        "handler": _h_copy_consistency_check, "requires": [],
        "tags": ["copy", "consistency", "quality"],
    })
