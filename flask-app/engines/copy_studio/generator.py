#!/usr/bin/env python3
"""
📝 copy_studio — generator (v26.0)
===================================
大纲→分章→正文流水线. 直接调 Ollama /api/generate (零 token).
复用 andromeda_cluster_matrix.py 的 Ollama 检测与连接模式.
"""
from __future__ import annotations
import json, os, time, uuid, re, urllib.request, urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List
from .policy import GENRE_CONFIG, GENRE_NOVEL, GENRE_SCRIPT, GENRE_AD_COPY
from .prompt_library import build_style_block
from .router import route_model

# ═══════════════════════════════════════════════════════════
# Ollama / llama-server 双后端动态发现 (防端口漂移)
# ═══════════════════════════════════════════════════════════
import subprocess as _sp

# 常见静态端口 + 环境变量覆盖
_STATIC_OLLAMA = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
_STATIC_LLAMA  = os.environ.get('LLAMA_SERVER_URL', 'http://127.0.0.1:62916')
# 常见候选端口 (Ollama serve 漂移 / llama-server 漂移)
_OLLAMA_PORTS = [11434, 11435, 11436]
_LLAMA_PORTS  = [62916, 64799]

_backend = None   # 'ollama' | 'llama' | None
_model_name = ''
_active_base = ''   # 当前活跃 base URL


def _find_llama_port_from_ps() -> Optional[int]:
    """从 ps 输出中 grep llama-server --port=XXXX."""
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


def _refresh_backend() -> tuple[Optional[str], str, str]:
    """刷新后端: 扫常见端口 + ps grep llama-server port. 返回 (backend, model, base)."""
    # 1. Ollama 标准 API — 环境变量 + 静态端口
    candidates = [_STATIC_OLLAMA] + [f"http://127.0.0.1:{p}" for p in _OLLAMA_PORTS]
    for base in candidates:
        tags = _probe(base, '/api/tags')
        if tags and tags.get('models'):
            m = next((m['name'] for m in tags['models'] if 'qwen' in m['name'].lower()),
                     tags['models'][0]['name'])
            return 'ollama', m, base
    # 2. llama-server — ps 发现优先, 再扫静态端口
    ps_port = _find_llama_port_from_ps()
    if ps_port:
        candidates = [f"http://127.0.0.1:{ps_port}"] + [_STATIC_LLAMA] + [f"http://127.0.0.1:{p}" for p in _LLAMA_PORTS]
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


def ollama_call(prompt: str, system: str = '', model: Optional[str] = None,
                temperature: float = 0.7, max_tokens: int = 2048,
                _retry: int = 2) -> Optional[str]:
    """统一 LLM 调用. 自动路由 + 失败重试 + 刷新后端."""
    # 首次调用时若后端 None, 先 refresh 一次
    global _backend, _model_name, _active_base, OLLAMA_OK
    if not _backend:
        _backend, _model_name, _active_base = _refresh_backend()
        OLLAMA_OK = _backend is not None
    if not _backend:
        return None
    m = model or _model_name

    last_err = None
    for attempt in range(_retry + 1):
        try:
            if _backend == 'ollama':
                payload = {
                    'model': m, 'prompt': prompt, 'system': system, 'stream': False,
                    'options': {'temperature': temperature, 'num_predict': max_tokens},
                }
                req = urllib.request.Request(
                    f"{_active_base}/api/generate",
                    data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                resp = urllib.request.urlopen(req, timeout=180)
                data = json.loads(resp.read())
                return data.get('response', '')

            elif _backend == 'llama':
                messages = []
                if system: messages.append({'role': 'system', 'content': system})
                messages.append({'role': 'user', 'content': prompt})
                payload = {
                    'model': m, 'messages': messages,
                    'temperature': temperature, 'max_tokens': max_tokens, 'stream': False,
                }
                req = urllib.request.Request(
                    f"{_active_base}/v1/chat/completions",
                    data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                resp = urllib.request.urlopen(req, timeout=180)
                data = json.loads(resp.read())
                return data['choices'][0]['message']['content']

        except Exception as e:
            last_err = e
            # 连接类错误 → 刷新后端后重试
            if attempt < _retry:
                time.sleep(1 + attempt)
                _backend, _model_name, _active_base = _refresh_backend()
                OLLAMA_OK = _backend is not None
                if _backend is None:
                    continue  # 刷新后还是没后端, 跳过重试

    print(f"  [llm_call FAILED ×{_retry+1}] {last_err}")
    return None


def ollama_call_stream(prompt: str, system: str = '', model: Optional[str] = None,
                       temperature: float = 0.7, max_tokens: int = 2048):
    """流式 LLM 调用. 逐块 yield 文本; 失败时 yield None 表示终止.
    支持 ollama /api/generate (NDJSON) 与 llama-server /v1/chat/completions (SSE) 双后端."""
    global _backend, _model_name, _active_base, OLLAMA_OK
    if not _backend:
        _backend, _model_name, _active_base = _refresh_backend()
        OLLAMA_OK = _backend is not None
    if not _backend:
        yield None
        return
    m = model or _model_name
    try:
        if _backend == 'ollama':
            payload = {
                'model': m, 'prompt': prompt, 'system': system, 'stream': True,
                'options': {'temperature': temperature, 'num_predict': max_tokens},
            }
            req = urllib.request.Request(
                f"{_active_base}/api/generate",
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            resp = urllib.request.urlopen(req, timeout=300)
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue
                if chunk.get('done'):
                    break
                piece = chunk.get('response', '')
                if piece:
                    yield piece

        elif _backend == 'llama':
            messages = []
            if system:
                messages.append({'role': 'system', 'content': system})
            messages.append({'role': 'user', 'content': prompt})
            payload = {
                'model': m, 'messages': messages,
                'temperature': temperature, 'max_tokens': max_tokens, 'stream': True,
            }
            req = urllib.request.Request(
                f"{_active_base}/v1/chat/completions",
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            resp = urllib.request.urlopen(req, timeout=300)
            for line in resp:
                line = line.strip()
                if not line.startswith('data:'):
                    continue
                data_str = line[5:].strip()
                if data_str == '[DONE]':
                    break
                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue
                choices = chunk.get('choices') or []
                piece = ((choices[0].get('delta') or {}).get('content', '')
                         if choices else '')
                if piece:
                    yield piece
    except Exception as e:
        print(f"  [llm_stream FAILED] {e}")
        yield None


# ═══════════════════════════════════════════════════════════
# 体裁专属 prompt 模板
# ═══════════════════════════════════════════════════════════
SYSTEM_OUTLINE_NOVEL = """你是一名资深长篇小说大纲架构师. 擅长构建严谨的世界观、多层主线支线、人物弧光.
输出要求: 结构化 JSON 格式 (禁止 Markdown, 直接输出 JSON).
必须包含以下顶层字段:
  "worldview": {世界观设定, 含 setting/magic/technology/society},
  "characters": [{人物数组, 每人含 name/role_type/protagonist/personality/backstory/goal}],
  "chapters": [{章节数组, 每章含 chapter_no/title/summary/target_words/main_characters}],
  "themes": [核心主题数组]
请生成 5-10 章, 每章字数根据目标总字数均分. 主角至少 2 名. 只输出合法 JSON."""

SYSTEM_OUTLINE_SCRIPT = """你是一名短剧剧本大纲架构师. 擅长紧凑节奏、强钩子、场景级冲突设计.
输出要求: 结构化 JSON 格式 (禁止 Markdown, 直接输出 JSON).
必须包含:
  "premise": 故事前提,
  "characters": [{人物数组, 每人含 name/role_type/personality/backstory}],
  "scenes": [{场景数组, 每场景含 scene_no/location/time/characters/conflict/hook/}],
  "acts": [三幕断点数组].
每幕 3-5 个场景. 只输出合法 JSON."""

SYSTEM_OUTLINE_AD = """你是一名资深广告文案策划. 擅长短平快、有记忆点的广告脚本.
输出要求: 结构化 JSON. 包含:
  "hook": 开头钩子, "body": 主体卖点, "cta": 行动号召,
  "characters": [{角色数组}], "scenes": [{场景数组}].
只输出合法 JSON."""

SYSTEM_WRITER_NOVEL = """你是一名中文长篇小说写手. 擅长场景描写、人物对话、心理刻画、五感细节.
核心方法: 用户消息中若附有【写作示范库】, 正例示范就是你的目标笔法 — 模仿其节奏、句式与细节密度;
反例示范是要对照避开的写法 (空泛抒情/概念堆砌/心理说明代替动作). 优先落实叙事动作模板.
输出: 直接输出章节正文, 不写标题, 不写作者."""

SYSTEM_WRITER_SCRIPT = """你是一名短剧剧本写手. 擅长紧凑场景、精准台词、镜头感强.
核心方法: 用户消息中若附有【写作示范库】, 正例示范就是你的目标笔法 — 模仿其台词节奏与画面感;
反例示范是要对照避开的写法 (台词直白无潜台词/旁白抒情). 优先落实叙事动作模板.
输出格式: 场景地点/时间 → 动作描写 → 角色名: 台词 (括号内可加动作提示).
人物名后紧跟冒号和台词."""

SYSTEM_POLISHER = """你是一名文风润色编辑. 保留原意, 优化节奏与情感浓度, 去AI味.
不要增删核心情节, 只优化文笔和可读性."""


def pick_system(genre: str, purpose: str) -> str:
    """根据体裁和用途选 system prompt."""
    key = f"{purpose}_{genre}"
    mapping = {
        f"outline_{GENRE_NOVEL}": SYSTEM_OUTLINE_NOVEL,
        f"outline_{GENRE_SCRIPT}": SYSTEM_OUTLINE_SCRIPT,
        f"write_{GENRE_NOVEL}": SYSTEM_WRITER_NOVEL,
        f"write_{GENRE_SCRIPT}": SYSTEM_WRITER_SCRIPT,
        "polish_": SYSTEM_POLISHER,
    }
    return mapping.get(key, SYSTEM_WRITER_NOVEL if genre == GENRE_NOVEL else SYSTEM_WRITER_SCRIPT)


# ═══════════════════════════════════════════════════════════
# 公共流水线函数
# ═══════════════════════════════════════════════════════════
def _extract_json(text: str) -> Optional[Any]:
    """从 LLM 输出中提取 JSON (容忍 markdown 包裹/前后杂讯)."""
    if not text:
        return None
    # 直接 parse
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    # 去掉 ```json ... ```
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    # 找第一个 { ... } 块
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


def generate_outline(genre: str, title: str, sub_genre: str = '',
                     target_words: int = 50000, user_intent: str = '') -> Optional[Dict]:
    """生成大纲. 返回结构化 JSON dict 或 None. 自动路由 14b 大模型."""
    cfg = GENRE_CONFIG.get(genre, GENRE_CONFIG[GENRE_NOVEL])
    system = pick_system(genre, 'outline')
    prompt = (
        f"体裁: {cfg['label']}\n"
        f"标题: {title}\n"
        f"子类型: {sub_genre or cfg.get('sub_genres', [''])[0]}\n"
        f"目标字数: {target_words}\n"
        f"用户意图/提案: {user_intent or '经典创意'}\n"
        f"\n请生成结构化大纲 (JSON 格式)."
    )
    model = route_model('outline', genre, sub_genre)
    raw = ollama_call(prompt, system=system, model=model, temperature=0.8)
    if raw is None:
        return None
    data = _extract_json(raw)
    if data is None:
        data = {'raw_outline': raw}
    return data


def _build_write_prompt(chapter_title: str, chapter_summary: str, target_words: int,
                        context_chapter_texts: Optional[List[str]],
                        character_briefs: Optional[List[str]],
                        style_guide: str, sub_genre: str = '',
                        genre: str = '') -> str:
    """构造写章 prompt (write_chapter_text / write_chapter_text_stream 共用)."""
    parts = [
        f"章节标题: {chapter_title}",
        f"本章概要: {chapter_summary}",
        f"目标字数: {target_words}",
    ]
    if context_chapter_texts:
        ctx = '\n'.join(context_chapter_texts[-3:])  # 最近 3 章
        parts.append(f"\n【前文上下文】\n{ctx[-2000:]}" if len(ctx) > 2000 else f"\n【前文上下文】\n{ctx}")
    if character_briefs:
        parts.append(f"\n【本章节出现角色】\n" + '\n'.join(character_briefs))
    if style_guide:
        parts.append(f"\n【文风指南】\n{style_guide}")
    # 示例库注入: 正反示范 + 叙事动作模板 (Step2)
    style_block = build_style_block(genre, sub_genre)
    if style_block:
        parts.append(f"\n{style_block}")
    return '\n'.join(parts)


def write_chapter_text(genre: str, chapter_title: str, chapter_summary: str,
                       target_words: int, context_chapter_texts: List[str] = None,
                       character_briefs: List[str] = None,
                       style_guide: str = '', sub_genre: str = '',
                       rag_chunks_text: str = '') -> Optional[str]:
    """写单章正文. 自动路由 coder:14b, 注入 RAG 跨章节参考."""
    system = pick_system(genre, 'write')
    prompt = _build_write_prompt(chapter_title, chapter_summary, target_words,
                                 context_chapter_texts, character_briefs, style_guide,
                                 sub_genre=sub_genre, genre=genre)
    if rag_chunks_text:
        prompt += '\n' + rag_chunks_text
    model = route_model('write', genre, sub_genre)
    return ollama_call(prompt, system=system, model=model, temperature=0.75,
                       max_tokens=min(target_words * 2, 4096))


def write_chapter_text_stream(genre: str, chapter_title: str, chapter_summary: str,
                              target_words: int, context_chapter_texts: List[str] = None,
                              character_briefs: List[str] = None,
                              style_guide: str = '', sub_genre: str = '',
                              rag_chunks_text: str = ''):
    """流式写单章正文. 自动路由 coder:14b, 注入 RAG 跨章节参考."""
    system = pick_system(genre, 'write')
    prompt = _build_write_prompt(chapter_title, chapter_summary, target_words,
                                 context_chapter_texts, character_briefs, style_guide,
                                 sub_genre=sub_genre, genre=genre)
    if rag_chunks_text:
        prompt += '\n' + rag_chunks_text
    model = route_model('write', genre, sub_genre)
    yield from ollama_call_stream(prompt, system=system, model=model, temperature=0.75,
                                  max_tokens=min(target_words * 2, 4096))


def polish_text(text: str, style_hint: str = '') -> Optional[str]:
    """润色. 自动路由 7b 小模型 (任务简单, 速度快)."""
    if not text:
        return None
    system = SYSTEM_POLISHER
    prompt = f"请润色以下文本{' (' + style_hint + ')' if style_hint else ''}:\n\n{text}"
    model = route_model('polish')
    return ollama_call(prompt, system=system, model=model, temperature=0.6, max_tokens=len(text) * 2)
