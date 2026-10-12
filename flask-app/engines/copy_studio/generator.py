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
# Ollama 检测 (复用 andromeda_cluster_matrix.py 模式)
# ═══════════════════════════════════════════════════════════
OLLAMA_BASE = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')

def _ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        resp = urllib.request.urlopen(req, timeout=2)
        return resp.status == 200
    except Exception:
        return False

def _detect_model() -> str:
    if not _ollama_available():
        return 'qwen2.5:14b'
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        resp = urllib.request.urlopen(req, timeout=3)
        models = json.loads(resp.read()).get('models', [])
        if models:
            return next((m['name'] for m in models if 'qwen' in m['name'].lower()), models[0]['name'])
    except Exception:
        pass
    return 'qwen2.5:14b'

OLLAMA_OK = _ollama_available()
OLLAMA_MODEL = _detect_model()


def ollama_call(prompt: str, system: str = '', model: Optional[str] = None,
                temperature: float = 0.7, max_tokens: int = 2048) -> Optional[str]:
    """单次 Ollama generate. 返回文本或 None (失败)."""
    if not OLLAMA_OK:
        return None
    m = model or OLLAMA_MODEL
    payload = {
        'model': m,
        'prompt': prompt,
        'system': system,
        'stream': False,
        'options': {'temperature': temperature, 'num_predict': max_tokens},
    }
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        resp = urllib.request.urlopen(req, timeout=180)
        data = json.loads(resp.read())
        return data.get('response', '')
    except Exception as e:
        print(f"  [ollama_call FAILED] {e}")
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
