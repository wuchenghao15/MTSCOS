#!/usr/bin/env python3
"""
📝 copy_studio 文案创作引擎包 (v26.0 · 绑定冰山域)
=================================================
双层架构: wenquxing(教育写作) 保留 + copy_studio(创作级文案) 新增
体裁: 长篇小说 / 短剧剧本 / 广告文案 / 网文连载
三层兜底: AI 员工(sys_auto_hire) + EigenFlux 专家(12+4文学) + 法务合规
九自绑定: 五基础自 + 四文案自(自修复/自辅助/自学习/自拓展)
审批: 接入 approval 中台(不同体裁/字数走不同审批策略)
本地推理: Ollama 零 token

模块:
  db          — 短连接 + 幂等迁移 (6 表) + @db_retry
  policy      — 体裁策略 + 字数约束 + 审批策略映射
  generator   — 大纲→分章→正文流水线 (调用 Ollama)
  rag_engine  — 角色/设定持久化 + RAG 上下文注入
  service     — 门面: create_project / add_chapter / write_chapter / polish / submit_approval
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

# DB 路径 (对齐 approval 包模式: 候选探测)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_CANDIDATES = [
    _PROJECT_ROOT / 'database' / 'app.db',
    _PROJECT_ROOT / 'app.db',
]
DB_PATH: Path = next((p for p in _DB_CANDIDATES if p.exists()), _DB_CANDIDATES[0])

# 体裁常量
GENRE_NOVEL = 'novel'          # 长篇小说 / 网文连载
GENRE_SCRIPT = 'script'        # 短剧剧本
GENRE_AD_COPY = 'ad_copy'      # 广告文案

# 项目状态
PROJECT_DRAFT = 'draft'
PROJECT_OUTLINING = 'outlining'
PROJECT_WRITING = 'writing'
PROJECT_REVIEWING = 'reviewing'
PROJECT_APPROVED = 'approved'
PROJECT_PUBLISHED = 'published'
PROJECT_ARCHIVED = 'archived'

# 章节状态
CHAPTER_PENDING = 'pending'
CHAPTER_WRITING = 'writing'
CHAPTER_DONE = 'done'
CHAPTER_POLISHED = 'polished'
CHAPTER_CHECKED = 'checked'

__all__ = [
    'DB_PATH',
    'GENRE_NOVEL', 'GENRE_SCRIPT', 'GENRE_AD_COPY',
    'PROJECT_DRAFT', 'PROJECT_OUTLINING', 'PROJECT_WRITING',
    'PROJECT_REVIEWING', 'PROJECT_APPROVED', 'PROJECT_PUBLISHED', 'PROJECT_ARCHIVED',
    'CHAPTER_PENDING', 'CHAPTER_WRITING', 'CHAPTER_DONE', 'CHAPTER_POLISHED', 'CHAPTER_CHECKED',
    'ensure_schema', 'get_conn', 'ApprovalService',
]

# 延迟导入 (避免循环)
def __getattr__(name: str):
    if name in ('ensure_schema', 'get_conn'):
        from .db import ensure_schema, get_conn
        return locals()[name]
    if name == 'ApprovalService':
        from .service import ApprovalService
        return locals()[name]
    raise AttributeError(f"copy_studio has no attribute {name!r}")
