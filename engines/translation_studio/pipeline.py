#!/usr/bin/env python3
"""
🌐 translation_studio — pipeline (v26.0)
========================================
翻译流水线. 复用 copy_studio 的 generator  Ollama 双后端 + 动态端口发现 + retry.

流水线:
  原文 → 分段 (≤1200 tokens) → 术语表注入 → Ollama 翻译 → 拼接 → 术语一致性校验
  精品模式: 额外回译校验 + 术语二次替换
"""
from __future__ import annotations
import os, re, json, time, uuid, datetime, hashlib, subprocess as _sp
import urllib.request, urllib.error
from typing import Optional, List, Dict, Any, Tuple

from . import (DB_PATH, get_conn, db_retry, NOW_F,
               FOUR_LANGS, LANG_LABELS, valid_direction, DEFAULT_GLOSSARY,
               QUALITY_STANDARD, QUALITY_PREMIUM)

# ═══════════════════════════════════════════════════════════
# 复用 copy_studio 风格的 Ollama/llama-server 双后端探测
# ═══════════════════════════════════════════════════════════
_STATIC_OLLAMA = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
_STATIC_LLAMA  = os.environ.get('LLAMA_SERVER_URL', 'http://127.0.0.1:62916')
_OLLAMA_PORTS = [11434, 11435, 11436]
_LLAMA_PORTS  = [62916, 64799]

_backend = None
_model_name = ''
_active_base = ''


def _find_llama_port_from_ps() -> Optional[int]:
    try:
        out = _sp.run(['ps', 'aux'], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            if 'llama-server' in line:
                m = re.search(r'--port\s+(\d+)', line) or re.search(r'--port=(\d+)', line)
                if m: return int(m.group(1))
    except Exception: pass
    return None


def _probe(url: str, path: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(f"{url}{path}")
        resp = urllib.request.urlopen(req, timeout=2)
        return json.loads(resp.read())
    except Exception:
        return None


def _refresh_backend() -> Tuple[Optional[str], str, str]:
    candidates = [_STATIC_OLLAMA] + [f"http://127.0.0.1:{p}" for p in _OLLAMA_PORTS]
    for base in candidates:
        tags = _probe(base, '/api/tags')
        if tags and tags.get('models'):
            m = next((m['name'] for m in tags['models'] if 'qwen' in m['name'].lower()),
                     tags['models'][0]['name'])
            return 'ollama', m, base
    ps_port = _find_llama_port_from_ps()
    if ps_port:
        candidates = [f"http://127.0.0.1:{ps_port}", _STATIC_LLAMA] + [f"http://127.0.0.1:{p}" for p in _LLAMA_PORTS]
    else:
        candidates = [_STATIC_LLAMA] + [f"http://127.0.0.1:{p}" for p in _LLAMA_PORTS]
    for base in candidates:
        models = _probe(base, '/v1/models')
        if models and models.get('data'):
            return 'llama', models['data'][0]['id'], base
    return None, '', ''


_backend, _model_name, _active_base = _refresh_backend()
OLLAMA_OK = _backend is not None
OLLAMA_MODEL = _model_name


# ═══════════════════════════════════════════════════════════
# 统一 LLM 调用 (与 copy_studio 对齐)
# ═══════════════════════════════════════════════════════════
def llm_call(prompt: str, system: str = '',
             temperature: float = 0.3, max_tokens: int = 2048,
             _retry: int = 2) -> Optional[str]:
    global _backend, _model_name, _active_base, OLLAMA_OK
    if not _backend:
        _backend, _model_name, _active_base = _refresh_backend()
        OLLAMA_OK = _backend is not None
    if not _backend: return None
    m = _model_name

    last_err = None
    for attempt in range(_retry + 1):
        try:
            if _backend == 'ollama':
                payload = {'model': m, 'prompt': prompt, 'system': system, 'stream': False,
                           'options': {'temperature': temperature, 'num_predict': max_tokens}}
                req = urllib.request.Request(f"{_active_base}/api/generate",
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                resp = urllib.request.urlopen(req, timeout=180)
                return json.loads(resp.read()).get('response', '')
            elif _backend == 'llama':
                messages = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}]
                payload = {'model': m, 'messages': messages, 'temperature': temperature,
                           'max_tokens': max_tokens, 'stream': False}
                req = urllib.request.Request(f"{_active_base}/v1/chat/completions",
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                resp = urllib.request.urlopen(req, timeout=180)
                return json.loads(resp.read())['choices'][0]['message']['content']
        except Exception as e:
            last_err = e
            if attempt < _retry:
                time.sleep(1 + attempt)
                _backend, _model_name, _active_base = _refresh_backend()
                OLLAMA_OK = _backend is not None
                if _backend is None: continue
    return None


# ═══════════════════════════════════════════════════════════
# 翻译 system prompts (四国 × 标准/精品)
# ═══════════════════════════════════════════════════════════
_TRANSLATE_SYSTEMS: Dict[str, str] = {
    'zh→en':     "You are a professional Chinese-to-English translator. Translate faithfully, preserve tone and nuance. "
                 "Keep proper nouns unchanged unless in the glossary. Output ONLY the translated text.",
    'en→zh':     "你是专业的英译中翻译家. 忠实翻译, 保留语气和细微差别. 专有名词按习惯译法. 只输出译文.",
    'zh→ja':     "あなたはプロの中日翻訳家です. 忠実に翻訳し, トーンとニュアンスを保ち, 固有名詞は原則そのままで. 訳文のみ出力.",
    'ja→zh':     "你是专业的日译中翻译家. 忠实翻译, 保留语气和语感. 专有名词按中文习惯译法. 只输出译文.",
    'zh→zh_tw':  "你是专业的简转繁翻译家. 把简体中文转为繁体中文, 保留原文意思和语气. "
                 "注意台湾常用术语: 数据库→資料庫, 人工智能→人工智慧, 服务器→伺服器, 组件→元件. 只输出译文.",
    'zh_tw→zh':  "你是专业的繁转简翻译家. 把繁体中文转为简体中文, 保留原文意思和语气. "
                 "注意术语对齐中国大陆常用译法. 只输出译文.",
    'en→ja':     "あなたはプロの英日翻訳家です. 自然な日本語に. 固有名詞は原則そのまま. 訳文のみ出力.",
    'ja→en':     "You are a professional Japanese-to-English translator. Natural English. Keep proper nouns. Output ONLY translation.",
    'en→zh_tw':  "你是专业的英译繁翻译家. 译为自然繁体中文, 保留原意. 专有名词按习惯. 只输出译文.",
    'zh_tw→en':  "You are a professional Traditional Chinese to English translator. Output ONLY translation.",
    'en→zh_zh':  "你是专业的英译简翻译家. 译为自然简体中文. 只输出译文.",
    # fallback: 任何未覆盖的方向用通用翻译 system
    '_default':  "You are a professional translator between source and target languages. "
                 "Translate faithfully, preserve tone and meaning. Output ONLY the translated text, nothing else.",
}


def get_translate_system(src: str, tgt: str) -> str:
    key = f"{src}→{tgt}"
    return _TRANSLATE_SYSTEMS.get(key, _TRANSLATE_SYSTEMS['_default'])


# ═══════════════════════════════════════════════════════════
# 翻译流水线核心函数
# ═══════════════════════════════════════════════════════════
def split_into_segments(text: str, max_chars: int = 1200) -> List[str]:
    """按段落拆 + 单段过长则按句号/换行再拆. 每段 ≤ max_chars."""
    if not text: return []
    paragraphs = re.split(r'\n\s*\n|\n', text)
    segments = []
    for p in paragraphs:
        p = p.strip()
        if not p: continue
        if len(p) <= max_chars:
            segments.append(p)
        else:
            # 按句号/感叹号/问号拆
            sentences = re.split(r'(?<=[。！？!?.;;])\s*', p)
            buf = ''
            for s in sentences:
                if len(buf) + len(s) <= max_chars:
                    buf += s
                else:
                    if buf: segments.append(buf.strip())
                    # 单句过长: 硬切
                    if len(s) > max_chars:
                        for i in range(0, len(s), max_chars):
                            segments.append(s[i:i+max_chars])
                        buf = ''
                    else:
                        buf = s
            if buf.strip(): segments.append(buf.strip())
    return segments


def apply_glossary_to_prompt(text: str, direction: str, custom_glossary: Optional[Dict[str, str]] = None) -> str:
    """在 prompt 中注入术语表 (不修改原文, 让 LLM 自行替换)."""
    glossary = dict(DEFAULT_GLOSSARY.get(direction, {}))
    if custom_glossary: glossary.update(custom_glossary)
    # 从 DB 加载用户自定义术语
    try:
        with get_conn() as c:
            rows = c.execute("""SELECT source_term, target_term FROM mt_trans_glossary
                              WHERE src_lang=? AND tgt_lang=?""",
                              direction.split('→')).fetchall()
            for r in rows: glossary[r['source_term']] = r['target_term']
    except Exception: pass

    if not glossary:
        return text

    glossary_lines = '\n'.join(f'  "{k}" → "{v}"' for k, v in list(glossary.items())[:40])
    return f"""【术语表 Glossary · 请严格遵守以下译法】:
{glossary_lines}

【待翻译文本】:
{text}"""


def translate_segment(text: str, src: str, tgt: str,
                      quality: str = QUALITY_STANDARD,
                      custom_glossary: Optional[Dict[str, str]] = None) -> Optional[str]:
    """翻译单段. 标准模式直接翻, 精品模式加回译校验."""
    system = get_translate_system(src, tgt)
    direction = f"{src}→{tgt}"
    prompt_text = apply_glossary_to_prompt(text, direction, custom_glossary)

    raw = llm_call(prompt_text, system=system, temperature=0.3, max_tokens=len(text) * 3)
    if raw is None: return None

    # 清理 LLM 可能输出的 markdown 包裹
    m = re.search(r'```(?:json|text)?\s*([\s\S]*?)```', raw)
    if m: raw = m.group(1).strip()
    raw = raw.strip()

    if quality == QUALITY_PREMIUM and raw:
        # 回译校验: 翻回源语言, 相似度太低则重翻一次
        back_dir = f"{tgt}→{src}"
        back_system = get_translate_system(tgt, src)
        back_raw = llm_call(raw, system=back_system, temperature=0.1, max_tokens=len(text) * 2)
        if back_raw:
            # 简单相似度: 字符重叠率
            orig_chars = set(text)
            back_chars = set(back_raw)
            if len(orig_chars) > 5:
                overlap = len(orig_chars & back_chars) / len(orig_chars)
                if overlap < 0.4:
                    # 相似度太低, 用更严格 system 重翻
                    strict_system = system + "\n\nIMPORTANT: Translate EVERY sentence faithfully. Do not skip or summarize."
                    raw2 = llm_call(prompt_text, system=strict_system, temperature=0.1, max_tokens=len(text) * 3)
                    if raw2 and len(raw2) > len(raw) * 0.5:
                        raw = raw2.strip()

    return raw


def translate_full(text: str, src: str, tgt: str,
                   quality: str = QUALITY_STANDARD,
                   custom_glossary: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """翻译完整文本. 返回 {translated, segments, stats, ollama_ok}."""
    if not valid_direction(src, tgt):
        return {'error': f'Invalid direction: {src}→{tgt}', 'translated': ''}

    segments = split_into_segments(text)
    translated_segs = []
    ok_count = 0
    errors = []

    for i, seg in enumerate(segments):
        t0 = time.time()
        tgt_seg = translate_segment(seg, src, tgt, quality, custom_glossary)
        if tgt_seg:
            translated_segs.append(tgt_seg)
            ok_count += 1
        else:
            translated_segs.append(f"[⚠️ 第{i+1}段翻译失败]")
            errors.append(i)

    translated = '\n\n'.join(translated_segs)
    return {
        'translated': translated,
        'segments_total': len(segments),
        'segments_ok': ok_count,
        'segments_failed': len(errors),
        'error_segments': errors,
        'quality': quality,
        'ollama_ok': OLLAMA_OK,
        'model': OLLAMA_MODEL[:50],
        'backend': _backend,
    }
