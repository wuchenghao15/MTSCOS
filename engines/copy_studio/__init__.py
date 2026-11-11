#!/usr/bin/env python3
"""
📝 copy_studio 文案创作引擎包 (v26.1 · 激活版)
=================================================
双层架构: wenquxing(教育写作) 保留 + copy_studio(创作级文案) 激活
体裁: 长篇小说 / 短剧剧本 / 广告文案 / 网文连载
三层兜底: AI 员工(sys_auto_hire) + EigenFlux 专家(12+4文学) + 法务合规
九自绑定: 五基础自 + 四文案自(自修复/自辅助/自学习/自拓展)
审批: 接入 approval 中台(不同体裁/字数走不同审批策略)
本地推理: Ollama 零 token

v26.1 激活修复:
  ✅ DB_PATH env-first 统一链 (ANDROMEDA_DB > APP_DB > PROD > OneDrive)
  ✅ __getattr__ 真导入 (之前 locals()[name] 永远 KeyError)
  ✅ ensure_schema() 在 PROD DB 下幂等迁移 (11 表)
  ✅ mt_copy_variants 表补入 SCHEMA (之前 workflow INSERT 静默失败)

模块:
  db          — 短连接 + 幂等迁移 (11 表) + @db_retry
  policy      — 体裁策略 + 字数约束 + 审批策略映射
  generator   — 大纲→分章→正文流水线 (调用 Ollama)
  rag         — 角色/设定持久化 + Embedding RAG 向量块
  service     — 门面: create_project / add_chapter / write_chapter / polish / submit_approval
  workflows   — 去中心化注册 (2 → N 个 workflow)
"""
from __future__ import annotations
import os as _os
from pathlib import Path
# [unused] from typing import Optional

# ── DB 路径 (env-first 统一链, 和其他引擎对齐) ──
_PROJ_ROOT = Path(__file__).resolve().parent.parent.parent
_PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
_ONEDRIVE_DB = _PROJ_ROOT / 'database' / 'app.db'
_DB_ENV = _os.environ.get('ANDROMEDA_DB') or _os.environ.get('APP_DB')
if _DB_ENV and Path(_DB_ENV).exists():
    DB_PATH: Path = Path(_DB_ENV)
elif _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
    DB_PATH = _PROD_LOCAL
else:
    DB_PATH = _ONEDRIVE_DB

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


# ── 真延迟导入 (修复 v26.0 的 locals()[name] KeyError) ──
def __getattr__(name: str):
    if name == 'ensure_schema':
        from .db import ensure_schema
        return ensure_schema
    if name == 'get_conn':
        from .db import get_conn
        return get_conn
    if name == 'ApprovalService':
        from .service import ApprovalService
        return ApprovalService
    raise AttributeError(f"copy_studio has no attribute {name!r}")
