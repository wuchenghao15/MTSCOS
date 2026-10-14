#!/usr/bin/env python3
"""
📝 copy_studio — rag (v26.0 Step4)
==================================
Embedding RAG 流水线 (零第三方依赖):
  1. Ollama nomic-embed-text → 768-dim embedding (优先)
  2. 失败时降级 TF-IDF 伪向量 (纯 Python, 零 token)
  3. chunk 切分 → mt_copy_chunks 落库
  4. cosine similarity / TF-IDF 点积 检索 top-k 跨章节相关片段

设计原则: 降级友好 — 任何 embedding 相关失败都不阻断写章, 自动跳过 RAG 注入.
"""
from __future__ import annotations
import json, os, re, time, uuid, math, urllib.request, urllib.error, datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# [unused] from . import DB_PATH

# ═══════════════════════════════════════════════════════════
# Ollama 端点动态发现 (与 generator 对齐)
# ═══════════════════════════════════════════════════════════
_STATIC_OLLAMA = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
_OLLAMA_PORTS = [11435, 11434, 11436]
_EMBED_MODEL = 'nomic-embed-text:latest'

_backend_base: Optional[str] = None


def _probe_embed() -> Optional[str]:
    """扫端口 + 试 /api/embeddings, 找 Ollama embedding 端点."""
    import subprocess as _sp
    # ps 发现优先
    try:
        out = _sp.run(['ps', 'aux'], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            if 'ollama serve' in line:
                m = re.search(r'--port\s+(\d+)', line) or re.search(r'--port=(\d+)', line)
                if m:
                    _OLLAMA_PORTS.insert(0, int(m.group(1)))
                    break
    except Exception:
        pass
    candidates = [_STATIC_OLLAMA] + [f"http://127.0.0.1:{p}" for p in _OLLAMA_PORTS]
    for base in candidates:
        try:
            payload = json.dumps({'model': _EMBED_MODEL, 'prompt': 'test'}).encode()
            req = urllib.request.Request(f"{base}/api/embeddings", data=payload,
                                         headers={'Content-Type': 'application/json'}, method='POST')
            resp = urllib.request.urlopen(req, timeout=5)
            d = json.loads(resp.read())
            if 'embedding' in d and len(d['embedding']) > 0:
                return base
        except Exception:
            continue
    return None


def _get_backend() -> Optional[str]:
    global _backend_base
    if _backend_base is None:
        _backend_base = _probe_embed()
    return _backend_base


# ═══════════════════════════════════════════════════════════
# Ollama Embedding (768-dim)
# ═══════════════════════════════════════════════════════════

def embed_with_ollama(text: str, _retry: int = 2) -> Optional[List[float]]:
    """Ollama nomic-embed-text embedding. 失败 → None (调用方自动降级)."""
    base = _get_backend()
    if not base:
        return None
    for attempt in range(_retry + 1):
        try:
            payload = json.dumps({'model': _EMBED_MODEL, 'prompt': text[:2000]}).encode()
            req = urllib.request.Request(f"{base}/api/embeddings", data=payload,
                                         headers={'Content-Type': 'application/json'}, method='POST')
            resp = urllib.request.urlopen(req, timeout=15)
            d = json.loads(resp.read())
            return d.get('embedding')
        except Exception as e:
            if attempt < _retry:
                _backend_base = None  # 触发下次重 probe
                base = _get_backend()
                time.sleep(0.5)
            else:
                return None
    return None


# ═══════════════════════════════════════════════════════════
# TF-IDF 降级 (纯 Python, 零依赖)
# ═══════════════════════════════════════════════════════════

def _tokenize(text: str) -> List[str]:
    """中文按字 n-gram + 英文按词, 统一小写."""
    text = (text or '').lower()
    # 英文词
    en = re.findall(r'[a-z][a-z0-9_\-]{2,}', text)
    # 中文按 2-gram (覆盖常用搭配)
    zh = []
    only_cn = re.sub(r'[^\u4e00-\u9fff]', ' ', text)
    for seg in only_cn.split():
        for i in range(len(seg) - 1):
            zh.append(seg[i:i + 2])
    return en + zh


def _idf(corpus: List[List[str]]) -> Dict[str, float]:
    df: Dict[str, int] = {}
    n = len(corpus)
    for toks in corpus:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1 + n / v) for t, v in df.items()}


def _tfidf_vec(tokens: List[str], idf_map: Dict[str, float]) -> List[Tuple[str, float]]:
    tf: Dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    total = sum(tf.values()) or 1
    return [(t, (c / total) * idf_map.get(t, 0.0)) for t, c in tf.items() if t in idf_map]


def embed_tfidf(text: str, idf_map: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """TF-IDF 稀疏向量. 返回 {token: weight} dict (代替 768-dim dense array)."""
    toks = _tokenize(text)
    if idf_map is None:
        idf_map = _idf([toks])  # 单文档 corpus → idf 全 0, 退化为纯 TF
    return dict(_tfidf_vec(toks, idf_map))


def cosine_dense(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def dot_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
    """两个稀疏 TF-IDF 向量的点积 (共同 token × weight 乘积求和)."""
    common = set(a.keys()) & set(b.keys())
    return sum(a[t] * b[t] for t in common)


# ═══════════════════════════════════════════════════════════
# Chunk 切分 + 入库
# ═══════════════════════════════════════════════════════════

def chunk_text(text: str, max_chars: int = 500, overlap: int = 80) -> List[str]:
    """按段落切分, 单段 > max_chars 时再按 overlap 窗口拆分."""
    if not text or not text.strip():
        return []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chunks: List[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
        else:
            # 滑动窗口
            start = 0
            while start < len(para):
                chunks.append(para[start:start + max_chars])
                start += max_chars - overlap
                if start >= len(para):
                    break
    return chunks


def embed_text(text: str) -> Tuple[Optional[Any], str]:
    """统一 embedding 入口. 返回 (vector, model_label). model_label 用于落 embed_model 字段.
    vector 类型: List[float] (dense) 或 Dict[str,float] (sparse TF-IDF)."""
    v = embed_with_ollama(text)
    if v is not None:
        return v, _EMBED_MODEL
    # 降级 TF-IDF
    return embed_tfidf(text), 'fastembed_tfidf_fallback'


# ═══════════════════════════════════════════════════════════
# DAO: chunk 入库 + 检索
# ═══════════════════════════════════════════════════════════

def _new_id(prefix: str = 'chunk') -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def upsert_chunks(project_id: str, chapter_id: str, content: str,
                  db_path: Optional[str] = None) -> int:
    """切分 + embed + 落库. 返回 chunk 数 (RAG 失败时跳过, 不中断)."""
    from .db import get_conn, ensure_schema
    ensure_schema(db_path)
    chunks = chunk_text(content)
    if not chunks:
        return 0
    conn = get_conn(db_path)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn.execute("BEGIN")
        # 先清该章节旧 chunks (写后重算)
        conn.execute("DELETE FROM mt_copy_chunks WHERE chapter_id=?", (chapter_id,))
        for idx, text in enumerate(chunks):
            vec, label = embed_text(text)
            if vec is None:
                continue
            if label == 'fastembed_tfidf_fallback':
                emb_json = json.dumps(vec, ensure_ascii=False)  # sparse dict
            else:
                emb_json = json.dumps(vec)  # dense array
            conn.execute(
                """INSERT INTO mt_copy_chunks
                (chunk_id, project_id, chapter_id, chunk_idx, chunk_text,
                 embedding_json, embed_model, tokens_estimate, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (_new_id('chunk'), project_id, chapter_id, idx, text,
                 emb_json, label, len(text) // 4, now))
        conn.execute("COMMIT")
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"  [rag upsert_chunks FAILED] {e}")
        return 0
    finally:
        conn.close()
    return len(chunks)


def search_chunks(query: str, project_id: str, limit: int = 5,
                  exclude_chapter_id: Optional[str] = None,
                  db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """跨章节语义检索 top-k chunks. 任何失败 → 返回空列表 (降级为无 RAG 注入)."""
    from .db import get_conn
    try:
        q_vec, q_model = embed_text(query)
    except Exception as e:
        print(f"  [rag embed_query FAILED] {e}")
        return []
    if q_vec is None:
        return []
    conn = get_conn(db_path)
    try:
        sql = "SELECT * FROM mt_copy_chunks WHERE project_id=?"
        params: list = [project_id]
        if exclude_chapter_id:
            sql += " AND chapter_id != ?"
            params.append(exclude_chapter_id)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    if not rows:
        return []

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in rows:
        emb_raw = r['embedding_json'] or ''
        embed_model = r['embed_model'] or ''
        if not emb_raw:
            continue
        try:
            stored = json.loads(emb_raw)
        except Exception:
            continue
        if q_model == embed_model and isinstance(q_vec, list) and isinstance(stored, list):
            sim = cosine_dense(q_vec, stored)
        elif q_model == embed_model and isinstance(q_vec, dict) and isinstance(stored, dict):
            sim = dot_sparse(q_vec, stored)
        else:
            # dense vs sparse 或反 — 用 overlap token 数代替
            if isinstance(q_vec, dict) and isinstance(stored, dict):
                sim = dot_sparse(q_vec, stored)
            else:
                sim = 0.0
        if sim > 0:
            scored.append((sim, dict(r)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for (_, chunk) in scored[:limit]]


def format_chunks_for_prompt(chunks: List[Dict[str, Any]]) -> str:
    """把检索到的 chunks 拼成 prompt 的【跨章节参考】块."""
    if not chunks:
        return ''
    lines = ['【跨章节语义参考 (RAG 检索)】']
    for i, c in enumerate(chunks, 1):
        lines.append(f"[{i}] {c['chunk_text']}")
    return '\n'.join(lines)


# CLI 自检
if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from engines.copy_studio.db import ensure_schema
    ensure_schema()
    # 1. embed 测试
    base = _probe_embed()
    print(f"Ollama embedding endpoint: {base}")
    v = embed_with_ollama("测试 embedding")
    if v:
        print(f"  dense embed OK, dim={len(v)}")
    else:
        print("  dense embed FAILED, 降级 TF-IDF")
    # 2. TF-IDF
    corpus = [_tokenize("雨停后台阶上的血迹淡成一种锈色"), _tokenize("周衍蹲下去，指尖悬在痕迹上方半寸")]
    idf = _idf(corpus)
    a = embed_tfidf("血迹 锈色", idf)
    b = embed_tfidf("台阶", idf)
    print(f"  TF-IDF sparse dim={len(a)}, overlap_score={dot_sparse(a, b):.3f}")
    # 3. chunk 切分
    text = "第一段\n\n第二段\n\n" + ("A" * 600)
    cs = chunk_text(text, max_chars=500)
    print(f"  chunk split: {len(cs)} chunks, sizes={[len(c) for c in cs]}")
    print("✅ rag self-check OK")
