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


# ═══════════════════════════════════════════════════════════
# 体裁专属 prompt 模板
# ═══════════════════════════════════════════════════════════
SYSTEM_OUTLINE_NOVEL = """你是一名资深长篇小说大纲架构师. 擅长构建严谨的世界观、多层主线支线、人物弧光.
输出要求: 结构化 JSON 格式, 包含 worldview(世界观), main_plot(主线), volumes(分卷列表) 三部分.
每卷包含 volume_no, title, summary, key_events(关键事件数组).
禁止输出 Markdown, 只输出合法 JSON."""

SYSTEM_OUTLINE_SCRIPT = """你是一名短剧剧本大纲架构师. 擅长紧凑节奏、强钩子、场景级冲突设计.
输出要求: 结构化 JSON 格式, 包含 premise(故事前提), act_breaks(三幕断点), scenes(场景列表).
每场景包含 scene_no, location, characters, conflict, hook(钩子).
禁止输出 Markdown, 只输出合法 JSON."""

SYSTEM_WRITER_NOVEL = """你是一名中文长篇小说写手. 擅长场景描写、人物对话、心理刻画、五感细节.
写作风格: 生动自然, 避免AI腔, 使用具体的感官细节和人物视角.
输出: 直接输出章节正文, 不写标题, 不写作者."""

SYSTEM_WRITER_SCRIPT = """你是一名短剧剧本写手. 擅长紧凑场景、精准台词、镜头感强.
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
    """生成大纲. 返回结构化 JSON dict 或 None."""
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
    raw = ollama_call(prompt, system=system, temperature=0.8)
    if raw is None:
        return None
    data = _extract_json(raw)
    if data is None:
        # fallback: 用原始文本包装
        data = {'raw_outline': raw}
    return data


def write_chapter_text(genre: str, chapter_title: str, chapter_summary: str,
                       target_words: int, context_chapter_texts: List[str] = None,
                       character_briefs: List[str] = None,
                       style_guide: str = '') -> Optional[str]:
    """写单章正文. context 是前文 (用于 RAG 窗口), character_briefs 是角色卡摘要."""
    system = pick_system(genre, 'write')
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
    prompt = '\n'.join(parts)

    raw = ollama_call(prompt, system=system, temperature=0.75,
                      max_tokens=min(target_words * 2, 4096))
    return raw


def polish_text(text: str, style_hint: str = '') -> Optional[str]:
    """润色. 保留原意, 优化文笔."""
    if not text:
        return None
    system = SYSTEM_POLISHER
    prompt = f"请润色以下文本{' (' + style_hint + ')' if style_hint else ''}:\n\n{text}"
    return ollama_call(prompt, system=system, temperature=0.6, max_tokens=len(text) * 2)
