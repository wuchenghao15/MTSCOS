#!/usr/bin/env python3
"""
📝 copy_studio — policy (v26.0)
================================
文案体裁策略 + 字数约束 + 审批策略映射
对齐 approval 中台 policy.py 的 assess_risk 接口风格
"""
from __future__ import annotations
from typing import Dict, Any, Optional
from . import GENRE_NOVEL, GENRE_SCRIPT, GENRE_AD_COPY

# ═══════════════════════════════════════════════════════════
# 体裁策略配置
# ═══════════════════════════════════════════════════════════
GENRE_CONFIG: Dict[str, Dict[str, Any]] = {
    GENRE_NOVEL: {
        'label': '长篇小说/网文连载',
        'icon': '📖',
        'default_target_words': 50000,
        'default_chapter_words': 3000,
        'max_chapters_single_run': 3,          # 每次并发生成章节数
        'ai_workers': {
            'outline': 'copy_outline_writer',
            'character': 'copy_character_designer',
            'planner': 'copy_chapter_planner',
            'writer': 'copy_chapter_writer',
            'polisher': 'copy_polisher',
            'checker': 'copy_consistency_checker',
        },
        'sub_genres': ['悬疑推理', '都市言情', '历史军事', '科幻玄幻', '现实主义', '武侠仙侠', '青春校园'],
    },
    GENRE_SCRIPT: {
        'label': '短剧剧本',
        'icon': '🎬',
        'default_target_words': 8000,
        'default_chapter_words': 1500,
        'max_scenes_single_run': 2,
        'ai_workers': {
            'outline': 'copy_outline_writer',
            'character': 'copy_character_designer',
            'planner': 'copy_chapter_planner',
            'writer': 'copy_chapter_writer',        # 这里指场景正文+台词
            'polisher': 'copy_polisher',
            'checker': 'copy_consistency_checker',
        },
        'sub_genres': ['都市情感', '古装甜宠', '犯罪悬疑', '奇幻玄幻', '职场励志', '搞笑喜剧'],
    },
    GENRE_AD_COPY: {
        'label': '广告文案',
        'icon': '📢',
        'default_target_words': 500,
        'default_chapter_words': 500,
        'max_versions_single_run': 3,          # 多版本生成
        'ai_workers': {
            'writer': 'copy_chapter_writer',
            'polisher': 'copy_polisher',
            'checker': 'copy_consistency_checker',
        },
        'sub_genres': ['品牌故事', '产品卖点', '社交媒体', '短视频脚本', '邮件营销', '落地页'],
    },
}

# ═══════════════════════════════════════════════════════════
# 字数阈值 → risk_level 映射
# ═══════════════════════════════════════════════════════════
# 低字数 → 可自动通过 (low)
# 中等字数 → teacher 确认 (medium)
# 大字数 → high risk 链式审批
# 超长/百万字 → critical
WORD_THRESHOLDS = {
    GENRE_NOVEL: {
        'low_max': 3000,         # ≤3k 短篇片段
        'medium_max': 20000,     # 3k-20k 单卷/中篇
        'high_max': 200000,      # 20k-200k 长篇
        # >200k → critical 百万字级
    },
    GENRE_SCRIPT: {
        'low_max': 1500,
        'medium_max': 5000,
        'high_max': 20000,
    },
    GENRE_AD_COPY: {
        'low_max': 300,
        'medium_max': 2000,
        'high_max': 5000,
    },
}

# 角色 → risk 偏移 (某些角色自动降一级)
ROLE_OFFSET: Dict[str, int] = {
    'super_admin': -2,   # SA 自发, 自动降 2 级
    'admin': -1,         # admin 降 1
    'professor': 0,
    'teacher': 0,
    'student': 1,        # 学生写的升 1 级 (确保有人审)
    'counselor': 0,
    'mentor': 0,
}

RISK_LEVELS = ['low', 'medium', 'high', 'critical']


def assess_risk(genre: str, target_words: int, user_role: str = 'teacher',
                sub_genre: Optional[str] = None) -> str:
    """评估 risk_level. 与 approval 中台 policy 接口对齐.
    返回: low / medium / high / critical
    """
    genre_cfg = WORD_THRESHOLDS.get(genre, WORD_THRESHOLDS[GENRE_AD_COPY])
    t = target_words or 0

    # 1. 字数基准
    if t <= genre_cfg['low_max']:
        base = 0  # low
    elif t <= genre_cfg['medium_max']:
        base = 1  # medium
    elif t <= genre_cfg['high_max']:
        base = 2  # high
    else:
        base = 3  # critical

    # 2. 角色偏移
    offset = ROLE_OFFSET.get(user_role, 0)
    level_idx = max(0, min(3, base + offset))

    return RISK_LEVELS[level_idx]


# ═══════════════════════════════════════════════════════════
# SLA 策略 (审批超时, 秒)
# ═══════════════════════════════════════════════════════════
SLA_POLICY: Dict[str, int] = {
    'low':     4 * 3600,    # 4h
    'medium':  8 * 3600,    # 8h
    'high':   24 * 3600,    # 24h
    'critical': 72 * 3600,  # 72h
}


def get_sla_hours(risk_level: str) -> int:
    """返回小时数."""
    return SLA_POLICY.get(risk_level, 8 * 3600) // 3600


# ═══════════════════════════════════════════════════════════
# LLM 安全边界 (哪些体裁禁止 LLM 单独过)
# ═══════════════════════════════════════════════════════════
LLM_SAFE_GENRES = {GENRE_AD_COPY}           # 广告文案: LLM 可自动生成草稿 (需人工确认)
LLM_ALWAYS_NEEDS_HUMAN = {GENRE_NOVEL}     # 长篇小说: LLM 不能单独定稿, 必须人工审核


def is_llm_safe_to_auto_pass(genre: str, risk_level: str) -> bool:
    """True = LLM 生成后可自动通过 (low-risk + 安全体裁)."""
    if genre in LLM_ALWAYS_NEEDS_HUMAN:
        return False
    if risk_level == 'low' and genre in LLM_SAFE_GENRES:
        return True
    return False
