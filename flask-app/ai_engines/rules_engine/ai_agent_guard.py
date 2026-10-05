# -*- coding: utf-8 -*-
"""
§14 IRON_RULE MT_IR_D1/D9 — AI Agent Guard
=============================================
拦截 AI 助手的文件操作 (Write/Edit/Delete) 和 shell 命令，
必须携带合法 flow_id 且处于允许实施步骤集合中才放行。

铁律：
- MT_IR_D1: 所有开发活动必须有合法 flow_id
- MT_IR_D9: AI 助手收到开发请求但 flow_id 非法 → 阻断

拦截点:
- guard_check_write(file_path, content)  → 在 Write 操作前调用
- guard_check_edit(file_path, old, new)  → 在 Edit 操作前调用
- guard_check_delete(file_paths)          → 在 Delete 操作前调用
- guard_check_shell(cmd)                  → 在 Shell 命令前调用 (开发类)
- guard_check_all(operation, target)      → 统一入口

性能: 每次检查 <3ms (LRU 缓存 flow_id, TTL=30s)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# === 路径 ===
_GUARD_DIR = os.path.dirname(os.path.abspath(__file__))
_AI_ENGINES_DIR = os.path.dirname(_GUARD_DIR)
_FLASK_APP_DIR = os.path.dirname(_AI_ENGINES_DIR)

# DB 路径优先级:
# 1. flask-app/database/app.db (Flask 真实运行库, 402MB, 294表)
# 2. ai_engines/app.db (rules_engine 旧默认)
# 3. env var APP_DB (dev 环境覆盖)
_APP_DB = os.path.join(_FLASK_APP_DIR, "database", "app.db")
if not os.path.exists(_APP_DB):
    _ALT = os.path.join(_AI_ENGINES_DIR, "app.db")
    if os.path.exists(_ALT):
        _APP_DB = _ALT
_ENV_DB = os.environ.get("APP_DB")
if _ENV_DB and os.path.exists(_ENV_DB):
    _APP_DB = _ENV_DB

# === 铁律常量 ===
_MT_SESSION_TABLE = "mt_dev_flow_session"
_MT_VIOL_TABLE = "mt_iron_rule_violations"

_ALLOWED_IMPL_STEPS = {
    "STEP_7_EXECUTE",
    "STEP_8_ACCEPTANCE",
    "STEP_9A_PASS_OR_LOOPBACK",
    "STEP_9B_SUMMARY",
    "STEP_10_SMART_VERSION_UPGRADE",
    "STEP_11_AUTO_GIT_SYNC",
    "STEP_12_TEST1000",
    "FINAL_DONE",
}

# === 开发活动检测 (复用 preflight 关键词 + 补充 AI 操作场景) ===
_FILE_WRITE_KEYWORDS = re.compile(
    r"(flask-app/engines/)"          # 写引擎代码
    r"|(flask-app/ai_engines/)"      # 写 AI 引擎
    r"|(flask-app/routes/)"          # 写路由
    r"|(flask-app/core/)"            # 写核心模块
    r"|(\.py$)"                      # Python 文件
    r"|(\.html$)"                    # 模板
    r"|(\.js$)"                      # JS
    r"|(\.css$)"                     # CSS
    r"|(\.sh$)",                     # Shell 脚本
    re.IGNORECASE
)

_SHELL_DEV_PATTERN = re.compile(
    r"(pip\s+install|npm\s+install|gem\s+install|brew\s+install)"
    r"|(git\s+(commit|push|add|merge|pull))"
    r"|(python3\s+.*\.py)"
    r"|(docker|ollama\s+pull|systemctl|launchctl)"
    r"|(ALTER\s+TABLE|CREATE\s+TABLE|DROP\s+TABLE)"
    r"|(rm\s+-[rfR]+\s+)"
    r"|(crontab\s+(-l|-e|-r))",
    re.IGNORECASE
)

# === 白名单路径 (不拦截) ===
_TRUSTED_DIRS = {
    ".trae/memory/",                # 记忆
    "_runtime/logs/",               # 日志
    "_runtime/pids/",               # PID 文件
    "_runtime/backup/",             # 备份
    ".git/",                        # Git 内部
    "node_modules/",                # node 依赖
    "__pycache__/",                 # Python 缓存
    ".pyc$",                        # 编译文件
    "/tmp/",                        # 临时目录
}

# === flow_id 缓存 ===
_FLOW_CACHE: Dict[str, Tuple[str, float]] = {}
_CACHE_TTL = 30.0
_CACHE_LOCK = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_APP_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _query_flow_state(flow_id: str) -> Optional[str]:
    """查 flow_id 当前步骤 (带 LRU 缓存)"""
    now = time.time()
    with _CACHE_LOCK:
        if flow_id in _FLOW_CACHE:
            step, expire = _FLOW_CACHE[flow_id]
            if now < expire:
                return step
            del _FLOW_CACHE[flow_id]
    try:
        conn = _get_conn()
        row = conn.execute(
            f"SELECT current_step FROM {_MT_SESSION_TABLE} WHERE flow_id=?", (flow_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        step = row["current_step"]
        with _CACHE_LOCK:
            _FLOW_CACHE[flow_id] = (step, now + _CACHE_TTL)
        return step
    except Exception:
        return None


def _record_violation(flow_id: Optional[str], viol_rule: str, detail: str) -> None:
    """落库 mt_iron_rule_violations"""
    now = datetime.now().isoformat()
    try:
        conn = _get_conn()
        conn.execute(
            f"INSERT INTO {_MT_VIOL_TABLE} (flow_id, viol_rule, detail, created_at) "
            "VALUES (?,?,?,?)",
            (flow_id, viol_rule, detail, now),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _is_trusted_path(path: str) -> bool:
    """判断是否为信任路径 (不拦截)"""
    for trust in _TRUSTED_DIRS:
        if trust in path:
            return True
    return False


def _detect_file_write_risk(file_path: str) -> bool:
    """检测文件写入是否属于开发活动"""
    # 信任路径不拦
    if _is_trusted_path(file_path):
        return False
    # 关键代码目录拦
    if "flask-app/" in file_path or ".trae/rules/" in file_path or "engines/" in file_path:
        return True
    return _FILE_WRITE_KEYWORDS.search(file_path) is not None


def _detect_shell_risk(command: str) -> bool:
    """检测 shell 命令是否属于开发活动"""
    if not command:
        return False
    return _SHELL_DEV_PATTERN.search(command) is not None


# ============================================================
# 公开 API (被 Trae agent 或 CLI wrapper 调用)
# ============================================================

def guard_check_write(file_path: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
    """Write 操作前检查"""
    risk = _detect_file_write_risk(file_path)
    if not risk:
        return {"allowed": True, "reason": "非代码文件，放行"}
    return guard_check_all("write", file_path, flow_id)


def guard_check_edit(file_path: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
    """Edit 操作前检查"""
    risk = _detect_file_write_risk(file_path)
    if not risk:
        return {"allowed": True, "reason": "非代码文件，放行"}
    return guard_check_all("edit", file_path, flow_id)


def guard_check_delete(file_paths: List[str], flow_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete 操作前检查"""
    for fp in file_paths:
        if _detect_file_write_risk(fp):
            return guard_check_all("delete", ",".join(file_paths), flow_id)
    return {"allowed": True, "reason": "无代码文件，放行"}


def guard_check_shell(command: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
    """Shell 命令前检查"""
    risk = _detect_shell_risk(command)
    if not risk:
        return {"allowed": True, "reason": "非开发命令，放行"}
    return guard_check_all("shell", command[:100], flow_id)


def guard_check_all(operation: str, target: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
    """统一入口：所有开发操作必须携带合法 flow_id"""
    now = datetime.now().isoformat()
    result = {
        "allowed": False,
        "operation": operation,
        "target": target[:80],
        "flow_id": flow_id or "",
        "current_step": "",
        "violation_code": "",
        "viol_rule": "",
        "prompt": "",
        "checked_at": now,
    }

    # 检查1: flow_id 是否存在
    if not flow_id:
        result["viol_rule"] = "MT_IR_D9"
        result["violation_code"] = "DEV-FLOW-VIOLATION-IRON-RULE"
        result["prompt"] = (
            "[§14 IRON_RULE MT_IR_D9] 检测到开发操作 "
            f"({operation}: {target[:40]})，但未携带合法 flow_id。\n"
            "必须先走 12 步骤创建 flow_id 后方可执行。"
        )
        _record_violation(None, "MT_IR_D9", f"operation={operation}, target={target[:80]}")
        return result

    # 检查2: flow_id 是否存在于数据库
    current_step = _query_flow_state(flow_id)
    if current_step is None:
        result["viol_rule"] = "MT_IR_D1"
        result["violation_code"] = "DEV-FLOW-VIOLATION-IRON-RULE"
        result["prompt"] = (
            f"[§14 IRON_RULE MT_IR_D1] flow_id={flow_id} 不存在于 mt_dev_flow_session。\n"
            "必须先走 STEP_1_PROPOSAL 创建合法 flow_id。"
        )
        _record_violation(flow_id, "MT_IR_D1", f"operation={operation}, target={target[:80]}")
        return result

    result["current_step"] = current_step

    # 检查3: flow_id 是否在允许实施的步骤
    if current_step not in _ALLOWED_IMPL_STEPS:
        result["viol_rule"] = "MT_IR_D1"
        result["violation_code"] = "DEV-FLOW-VIOLATION-IRON-RULE"
        result["prompt"] = (
            f"[§14 IRON_RULE MT_IR_D1] flow_id={flow_id} current_step={current_step}\n"
            "当前步骤不允许执行开发操作，必须推进到 STEP_7_EXECUTE 后方可执行。"
        )
        _record_violation(flow_id, "MT_IR_D1",
                         f"operation={operation}, current_step={current_step} not in allowed")
        return result

    # 全部通过 → 放行
    result["allowed"] = True
    return result


# === CLI 包装器 (供终端使用) ===

def guard_cli_main():
    """命令行入口
    用法:
        python3 ai_agent_guard.py write <file_path> [flow_id]
        python3 ai_agent_guard.py shell <command> [flow_id]
        python3 ai_agent_guard.py check <operation> <target> [flow_id]
        python3 ai_agent_guard.py health
    """
    import sys

    if len(sys.argv) < 2:
        print("[ai_agent_guard] §14 IRON_RULE MT_IR_D1/D9 guard")
        print("用法:")
        print("  python3 ai_agent_guard.py write <file> [flow_id]")
        print("  python3 ai_agent_guard.py edit  <file> [flow_id]")
        print("  python3 ai_agent_guard.py shell <cmd>  [flow_id]")
        print("  python3 ai_agent_guard.py check <op> <target> [flow_id]")
        print("  python3 ai_agent_guard.py health")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "health":
        print(json.dumps({
            "module": "ai_agent_guard",
            "iron_rule": "MT_IR_D1 + MT_IR_D9",
            "guard_level": "AI_agent_file_ops",
            "allowed_impl_steps": list(_ALLOWED_IMPL_STEPS),
            "db_path": _APP_DB,
            "db_exists": os.path.exists(_APP_DB),
            "cache_size": len(_FLOW_CACHE),
            "cache_ttl": _CACHE_TTL,
            "status": "ACTIVE",
        }, ensure_ascii=False, indent=2))
        return

    op_map = {"write": guard_check_write, "edit": guard_check_edit, "shell": guard_check_shell}
    fn = op_map.get(cmd, guard_check_all)

    if cmd in ("write", "edit"):
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        flow_id = sys.argv[3] if len(sys.argv) > 3 else None
        result = fn(target, flow_id=flow_id)
    elif cmd == "shell":
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        flow_id = sys.argv[3] if len(sys.argv) > 3 else None
        result = fn(target, flow_id=flow_id)
    elif cmd == "check":
        operation = sys.argv[2] if len(sys.argv) > 2 else ""
        target = sys.argv[3] if len(sys.argv) > 3 else ""
        flow_id = sys.argv[4] if len(sys.argv) > 4 else None
        result = fn(operation, target, flow_id=flow_id)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["allowed"]:
        print(f"\n❌ {result.get('prompt', 'DEV-FLOW-VIOLATION-IRON-RULE')}")
        sys.exit(2)
    else:
        print(f"✅ 放行 (flow_id={result['flow_id']}, step={result['current_step']})")


if __name__ == "__main__":
    guard_cli_main()
