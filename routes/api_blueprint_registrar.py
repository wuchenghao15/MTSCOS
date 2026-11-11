# -*- coding: utf-8 -*-
"""app/api 蓝图统一注册器 — 物理链路闭环组件

功能:
  动态扫描 app/api/*_api.py, 把其中定义的 Blueprint 全部注册到 Flask app,
  修复 32 个 API 蓝图孤儿状态 (共 ~368 路由, 其中 361 条为独有路由).

策略:
  1. 逐文件 import, 提取 Blueprint 实例
  2. 单个蓝图注册失败不阻断其他 (try/except per blueprint)
  3. 端点名冲突 (AssertionError) 自动跳过, 不影响主服务
  4. 注册顺序: 文件名字典序, 可预测

属于系统正规化治理 M1 物理链路打通组件.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
from typing import Dict, List, Tuple

from flask import Blueprint, Flask

logger = logging.getLogger("api_blueprint_registrar")

_API_DIR_CANDIDATES = [
    "app/api",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "api"),
]


def _find_api_dir() -> str:
    for d in _API_DIR_CANDIDATES:
        if os.path.isdir(d):
            return d
    return ""


def _extract_blueprint_names(file_path: str) -> List[str]:
    """从 .py 文件中提取所有 `xxx = Blueprint(...)` 的变量名."""
    try:
        with open(file_path, encoding="utf-8") as fh:
            txt = fh.read()
        return re.findall(r"(\w+)\s*=\s*Blueprint\(", txt)
    except Exception:
        return []


def register_all_api_blueprints(app: Flask) -> Dict[str, object]:
    """扫描 app/api/ 并注册全部 Blueprint 到 app.

    Returns:
        dict: {total, registered, skipped, failed, details}
    """
    api_dir = _find_api_dir()
    if not api_dir:
        logger.warning("[api_registrar] app/api 目录未找到, 跳过")
        return {"total": 0, "registered": 0, "skipped": 0, "failed": 0, "details": [], "error": "no app/api dir"}

    t0_dir = api_dir
    # 计算 import 包名: app/api -> app.api
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkg_base = os.path.relpath(api_dir, project_root).replace(os.sep, ".")
    if pkg_base.startswith("app.api"):
        pkg_base = "app.api"
    else:
        pkg_base = "app.api"

    api_files = sorted(f for f in os.listdir(api_dir) if f.endswith("_api.py"))
    total = len(api_files)
    registered: List[str] = []
    skipped: List[Tuple[str, str]] = []
    failed: List[Tuple[str, str]] = []
    routes_added = 0

    for fname in api_files:
        stem = fname[:-3]  # 去 .py
        mod_full = f"{pkg_base}.{stem}"
        try:
            mod = importlib.import_module(mod_full)
        except Exception as e:
            failed.append((fname, f"import: {type(e).__name__}: {str(e)[:120]}"))
            continue

        bp_names = _extract_blueprint_names(os.path.join(api_dir, fname))
        if not bp_names:
            # 没有 Blueprint 定义, 跳过
            skipped.append((fname, "no Blueprint defined"))
            continue

        for bn in bp_names:
            bp = getattr(mod, bn, None)
            if not isinstance(bp, Blueprint):
                failed.append((fname, f"{bn} not a Blueprint instance"))
                continue
            # ✅ 防重复注册: 如果该 blueprint name 已在 app.blueprints 里, 跳过
            if bn in app.blueprints:
                skipped.append((fname, f"{bn}: already in app.blueprints"))
                continue
            # 🔧 v25.2.0 NODE_ROLE 过滤: SERVER 模式排除 render_template blueprint
            # 审计显示只有 dev_dashboard + history 这 2 个有 render_template
            try:
                from app.node_role import ALLOW_TEMPLATE, NODE_ROLE
                _has_tpl = "render_template" in open(os.path.join(api_dir, fname), encoding="utf-8").read()
                if not ALLOW_TEMPLATE and _has_tpl:
                    skipped.append((fname, f"{bn}: NODE_ROLE={NODE_ROLE} 排除 render_template"))
                    continue
            except Exception:
                pass
            try:
                app.register_blueprint(bp)
                registered.append(f"{stem}.{bn}")
                try:
                    routes_added += len(list(bp.deferred_functions))
                except Exception:
                    pass
            except Exception as reg_e:
                msg = str(reg_e)
                if "already been registered" in msg or "already registered" in msg:
                    skipped.append((fname, f"{bn}: already registered"))
                else:
                    # 端点名冲突等, 跳过但记录
                    skipped.append((fname, f"{bn}: {msg[:100]}"))
                    logger.debug("[api_registrar] skip %s.%s: %s", stem, bn, msg)

    summary = {
        "total": total,
        "registered": len(registered),
        "skipped": len(skipped),
        "failed": len(failed),
        "routes_added_approx": routes_added,
        "registered_list": registered,
        "skipped_list": skipped[:20],
        "failed_list": failed[:20],
    }
    print(f"[API-Registrar] app/api 蓝图注册: 共{total}文件, 成功{summary['registered']}, "
          f"跳过{summary['skipped']}, 失败{summary['failed']}, 新增路由~{routes_added}")
    if failed:
        print(f"[API-Registrar] 失败详情(前5): {failed[:5]}")
    logger.info("[api_registrar] %s", {k: v for k, v in summary.items() if k in ("total", "registered", "skipped", "failed")})
    return summary


if __name__ == "__main__":
    # 自检: 列出会注册的蓝图
    api_dir = _find_api_dir()
    print(f"api_dir={api_dir}")
    if api_dir:
        for f in sorted(os.listdir(api_dir)):
            if f.endswith("_api.py"):
                bps = _extract_blueprint_names(os.path.join(api_dir, f))
                print(f"  {f}: {bps}")
