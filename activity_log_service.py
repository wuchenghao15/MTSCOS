#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容重导出包装器：flask-app/activity_log_service.py
---------------------------------------------
项目重组后模块已迁移到 services.activity_log_service，本文件保持旧导入路径不报错。
使用 PEP 562 惰性加载 + 完整符号透传。
"""

import importlib as _importlib

_TARGET_MODULE = 'services.activity_log_service'


def _load_target():
    return _importlib.import_module(_TARGET_MODULE)


def __getattr__(attr):
    target = _load_target()
    val = getattr(target, attr)
    globals()[attr] = val
    return val


def __dir__():
    target = _load_target()
    return sorted(set(list(globals().keys()) + list(getattr(target, "__all__", []) or dir(target))))


def upgrade_local_model_and_skill():
    """
    兼容旧接口，直接调用 services.activity_log_service 的实现。
    """
    target = _load_target()
    return target.upgrade_local_model_and_skill()
