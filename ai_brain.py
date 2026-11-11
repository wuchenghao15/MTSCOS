#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容重导出包装器：flask-app/ai_brain.py
---------------------------------------------
项目重组后模块已迁移到 ai_engines.ai_brain，本文件保持旧导入路径不报错。
使用 PEP 562 惰性加载 + 完整符号透传。整合AI内部指令集统一调度。
"""
import importlib as _importlib
import subprocess as _subprocess

_TARGET_MODULE = 'ai_engines.ai_brain'

# 统一AI内部指令注册表
_AI_INTERNAL_COMMANDS = {
    "upgrade_local_model": None,
    "enhance_skills_and_functionality": None,
    "sync_git_and_github": None,
    "extend_local_skills": None,
    "sync_local_skills": None,
    "improve_local_skills": None,
    "ai_fix": None,
    "new_command": None  # 新增的内部指令
}

def _load_target():
    return _importlib.import_module(_TARGET_MODULE)

# 内部AI指令统一调度器
def _ai_internal_command_exec(cmd_name, *args, **kwargs):
    if cmd_name not in _AI_INTERNAL_COMMANDS:
        raise PermissionError(f"Unauthorized AI internal command: {cmd_name}")
    if _AI_INTERNAL_COMMANDS[cmd_name] is None:
        # 懒加载对应指令实现
        if cmd_name in ("upgrade_local_model", "enhance_skills_and_functionality"):
            target_module = _importlib.import_module(_TARGET_MODULE)
            _AI_INTERNAL_COMMANDS["upgrade_local_model"] = getattr(
                target_module, "upgrade_local_model", None
            )
            _AI_INTERNAL_COMMANDS["enhance_skills_and_functionality"] = getattr(
                target_module, "enhance_skills_and_functionality", None
            )
        elif cmd_name == "sync_git_and_github":
            def _impl():
                _subprocess.run(["git", "pull"], check=False)
                _subprocess.run(["git", "push"], check=False)
            _AI_INTERNAL_COMMANDS["sync_git_and_github"] = _impl
        elif cmd_name == "extend_local_skills":
            def _impl():
                target = _load_target()
                if hasattr(target, "extend_local_skills"):
                    target.extend_local_skills()
            _AI
