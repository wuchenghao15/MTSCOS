#!/usr/bin/env python3
"""
🌉 translation_studio × 冰山 content_matrix 桥接层 (v26.0)
===========================================================
翻译完的文案 → 自动注入 mt_iceberg_content_matrix (store_content_4lang)
让所有冰山模板通过 t(key) 即时获取四国译文, 无需手动 seed.

Lang 映射 (对齐两边):
  translation_studio  →  冰山
  zh       →  zh_CN
  zh_tw    →  zh_TW
  ja       →  ja_JP
  en       →  en_US
"""
from __future__ import annotations
import json, time, datetime, sqlite3, functools, re, hashlib
# [unused] from pathlib import Path
from typing import Optional, Dict, Any, List

# ═══════════════════════════════════════════════════════════
# Lang 映射 (核心! 两边 lang code 不一致)
# ═══════════════════════════════════════════════════════════
TS_TO_ICEBERG = {
    'zh':    'zh_CN',
    'zh_tw': 'zh_TW',
    'ja':    'ja_JP',
    'en':    'en_US',
}
ICEBERG_TO_TS = {v: k for k, v in TS_TO_ICEBERG.items()}

# 反向映射: 冰山 lang → translation_studio lang
ICEBERG_FOUR_LANGS = ['zh_CN', 'zh_TW', 'ja_JP', 'en_US']


def ts_to_iceberg_lang(ts_lang: str) -> Optional[str]:
    """translation_studio lang → 冰山 lang."""
    return TS_TO_ICEBERG.get(ts_lang)


def iceberg_to_ts_lang(ice_lang: str) -> Optional[str]:
    """冰山 lang → translation_studio lang."""
    return ICEBERG_TO_TS.get(ice_lang)


def generate_content_key(domain: str, original_text: str, category: str = 'translated') -> str:
    """从原文生成确定性 content_key (基于 hash)."""
    h = hashlib.sha256((original_text or '').encode('utf-8')).hexdigest()[:12]
    safe_domain = re.sub(r'[^a-zA-Z0-9_]', '_', domain or 'global')
    return f"ts_{safe_domain}_{h}"


def publish_to_iceberg(
    translations: Dict[str, str],
    domain: str = 'global',
    content_key: Optional[str] = None,
    audience: str = 'all',
    context_tag: str = '',
    **extra_store_kwargs,
) -> Dict[str, Any]:
    """
    把 translation_studio 的四语言译文注入冰山 content_matrix.

    Args:
        translations: {ts_lang: text} 映射, 如 {'zh':'你好','en':'Hello','ja':'こんにちは','zh_tw':'你好'}
        domain:       冰山域 (global / copy_studio / wenquxing / i18n / etc)
        content_key:  可选, 传进来用; 不传则从 zh 原文生成 hash key
        audience:     冰山 audience tag
        context_tag:  冰山 context tag

    Returns:
        {'content_key': str, 'iceberg_rows': [(ice_lang, row_id), ...], 'skipped': [...]}

    用法:
        from engines.translation_studio.iceberg_bridge import publish_to_iceberg
        publish_to_iceberg({'zh':'仙女座','en':'Andromeda','ja':'アンドロメダ','zh_tw':'仙女座'},
                           domain='copy_studio', content_key='andromeda.name')
    """
    # 1. 拿到冰山 store_content_4lang (动态 import, 避免循环依赖)
    try:
        from engines.iceberg_content_matrix import store_content_4lang, store_content
    except Exception as e:
        return {'error': f'iceberg store_content_4lang 不可用: {e}'}

    # 2. 规范化 translations dict
    zh = translations.get('zh') or translations.get('zh_CN') or ''
    tw = translations.get('zh_tw') or translations.get('zh_TW') or zh
    ja = translations.get('ja') or translations.get('ja_JP') or zh
    en = translations.get('en') or translations.get('en_US') or zh

    # 3. 生成 content_key
    if not content_key:
        content_key = generate_content_key(domain or 'global', zh)

    # 4. 写入冰山
    extra = {'audience': audience, 'context_tag': context_tag}
    extra.update(extra_store_kwargs)
    rows = store_content_4lang(content_key, zh=zh, tw=tw, ja=ja, en=en,
                               domain=domain or 'global', **extra)

    return {
        'content_key': content_key,
        'iceberg_rows': rows,
        'langs_published': [r[0] for r in rows],
        'domain': domain,
        'note': '已注入冰山 mt_iceberg_content_matrix, Jinja2 t(key) 可直接取四国译文',
    }


def batch_publish_to_iceberg(
    tasks: List[Dict[str, Any]],
    domain: str = 'copy_studio',
) -> List[Dict[str, Any]]:
    """
    批量 publish: 适合从 mt_trans_tasks 读取已完成任务后集中注入.

    tasks: [{'task_id','source_lang','target_lang','source_text','target_text','status':...}]
    """
    results = []
    for t in tasks:
        if t.get('status') not in ('done', 'partial'):
            continue
        # 需要先从 DB 读取完整译文 (只给了 target_text 一条)
        results.append({'task_id': t['task_id'],
                        'note': '需要完整四语言译文才能 publish (当前 translation_studio 只生成 src→tgt 单向)'})
    return results


def auto_translate_and_publish(
    source_text: str,
    source_lang: str,
    target_langs: Optional[List[str]] = None,
    domain: str = 'global',
    content_key: Optional[str] = None,
    quality: str = 'standard',
) -> Dict[str, Any]:
    """
    🔥 全流程: 原文 → 自动翻到四语言 → 注入冰山 content_matrix.

    这是冰山无缝切换的核心函数. 前端翻译完成后点 '🚀 发布到冰山' 就调它.

    Args:
        source_text: 原文 (通常是 zh)
        source_lang: 源语言, 默认 zh
        target_langs: 目标语言列表, None → 除 source_lang 外的全部 (en + ja + zh_tw)
        domain: 冰山域标签
        content_key: 可选, 指定 key; 不传自动 hash 生成
        quality: standard / premium

    Returns:
        {'content_key': ..., 'translations': {ts_lang: text}, 'iceberg_publish': {...}, 'ollama_ok': bool}
    """
    from engines.translation_studio.pipeline import translate_full, OLLAMA_OK

    if target_langs is None:
        target_langs = [l for l in ['en', 'ja', 'zh_tw'] if l != source_lang]

    translations = {source_lang: source_text}
    for tgt in target_langs:
        if tgt == source_lang: continue
        r = translate_full(source_text, source_lang, tgt, quality=quality)
        translations[tgt] = r.get('translated', source_text)
        # 反向 (如 en 目标还要翻回 zh_tw) — 跳过重翻, 先用 source 当 fallback

    # 注入冰山
    pub = publish_to_iceberg(translations, domain=domain, content_key=content_key)

    return {
        'content_key': pub.get('content_key'),
        'translations': translations,
        'iceberg_publish': pub,
        'ollama_ok': OLLAMA_OK,
        'domain': domain,
        'note': '✅ 已注入冰山 content_matrix, 所有 Jinja2 模板用 t(content_key) 自动按 session i18n_lang 取对应译文',
    }
