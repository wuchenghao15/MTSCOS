# -*- coding: utf-8 -*-
"""系统版本单一权威源 (Single Source of Truth for the system version).

版本号只允许有一个事实来源:
    flask-app/VERSION   —— 构建期/代码期权威常量(纯文本, 如 "v25.0.0.1-iceberg-saga")

运行时展示权威为数据库 system_versions 表(由 server_real_db.get_version_info
解密读取), 与 VERSION 文件在正式升级流程(§14 步骤10)中被同一处写入并保持一致。

=== v3.0.0 规则升级: 四段 MAJOR.MINOR.PATCH.BUILD ===
历史教训: 3级 SemVer 下每次小热修/微迭代都要 bump patch, 容易在版本历史里淹没
真正的大版本节点。4级语义化版本 (SemVer4) 引入 BUILD (构建序号), 负责所有常规
自动升级, 仅当架构/MINOR/PATCH 有实质变更时才 bump 前三段:

    - MAJOR  (主版本号): 不兼容 API 变更或重大架构重构  (每 6-12 月 1 次)
    - MINOR  (次版本号): 新增向后兼容功能/模块/子系统    (每 1-3 月 1 次)
    - PATCH  (修订号)  : Bug 修复/小优化, 不改变 API 契约 (每月 1-4 次)
    - BUILD  (构建序号) : 默认自动升级目标, 日常迭代/热修/配置调整全 bump BUILD
                                                           (每 1-3 天 1 次, 可高频)

BUILD 由 daemon/CI 在触发自动升级时递增, 不需要 SA 手动介入。规则见 `.trae/rules/版本升级规则.md`
"""

import os
import re

# 四段语义化版本: MAJOR.MINOR.PATCH.BUILD, 允许前导 v 与后缀 tag
#   例: v25.0.0.1-iceberg-saga / 25.0.0.1 / v22.2.1.3
_VERSION_RE = re.compile(r'^\s*[vV]?(\d{1,2})\.(\d{1,2})\.(\d{1,3})\.(\d{1,4})(?:[.\-+].*)?\s*$')
# 也兼容历史三段版本 (向后兼容), 补 BUILD=0
_VERSION_RE_COMPAT = re.compile(r'^\s*[vV]?(\d{1,2})\.(\d{1,2})\.(\d{1,3})(?:[.\-+].*)?\s*$')

# VERSION 文件缺失/损坏时的安全回退 (与最近一次正式升级保持一致, 仅兜底)
_SAFE_FALLBACK = '25.0.0.1'


def version_file_path():
    """返回 VERSION 文件绝对路径 (flask-app/VERSION)。本文件位于 flask-app/core/。"""
    core_dir = os.path.dirname(os.path.abspath(__file__))
    flask_root = os.path.dirname(core_dir)
    return os.path.join(flask_root, 'VERSION')


def read_raw_version():
    """读取 VERSION 文件原始版本字符串(去首尾空白), 读不到返回 None。"""
    try:
        with open(version_file_path(), 'r', encoding='utf-8') as f:
            txt = f.read().strip()
        return txt or None
    except Exception:
        return None


def parse_version(ver):
    """解析版本串为 (major, minor, patch, build); 非法返回 None。历史三段补 build=0。"""
    if not ver:
        return None
    m = _VERSION_RE.match(str(ver))
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    # 历史三段兼容
    m = _VERSION_RE_COMPAT.match(str(ver))
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), 0
    return None


def get_version_parts():
    """返回 (major, minor, patch, build) 四元组, 任何异常回退安全默认值。"""
    parts = parse_version(read_raw_version())
    if parts is None:
        parts = parse_version(_SAFE_FALLBACK)
    return parts


def get_system_version():
    """返回核心版本号(无前缀 v), 如 '25.0.0.1'。任何异常回退安全默认, 绝不抛错。"""
    major, minor, patch, build = get_version_parts()
    return f'{major}.{minor}.{patch}.{build}'


def get_system_version_tagged():
    """返回带 v 前缀的版本号, 如 'v25.0.0.1'。"""
    return 'v' + get_system_version()


def get_version_info():
    """返回版本信息 dict(major/minor/patch/build/tag), 供兼容层与前端使用。"""
    major, minor, patch, build = get_version_parts()
    return {
        'major': major,
        'minor': minor,
        'patch': patch,
        'build': build,
        'tag': 'release',
        'version': get_system_version_tagged(),
    }


def next_build(version=None):
    """返回 BUILD + 1 后的四段版本号 (无前缀 v)。默认自动升级目标。"""
    major, minor, patch, build = parse_version(version or read_raw_version() or _SAFE_FALLBACK)
    return f'{major}.{minor}.{patch}.{build + 1}'
