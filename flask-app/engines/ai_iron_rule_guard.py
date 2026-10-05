#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§14 IRON_RULE 守护进程：IronRuleGuard
===========================================
铁律 MT_IR_D9 强制第 2 层拦截（dev_activity_preflight 是第 1 层，
只拦截 Flask HTTP API；本守护进程是第 2 层，监控文件系统直接变更）

功能：
- 每 30s 扫描：git diff HEAD~5 变更 + 文件 mtime 最近 10 分钟变更
- 检测到变更 → 查 mt_dev_flow_session 表是否有合法 flow_id
- 无合法 flow_id → 落库 mt_iron_rule_violations(viol_rule=MT_IR_D9)
- 告警 → 投喂 AI 脑库 mt_ai_brain_feed_log
- 巡检：每 300s 自动巡检已存在的 mt_iron_rule_violations 是否需要升级

启动：python3 ai_iron_rule_guard.py
注册：smart_mount_engine.sys_iron_rule_guard
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════
_ENGINES_DIR = Path(__file__).resolve().parent  # flask-app/engines/
_FLASK_APP = _ENGINES_DIR.parent                  # flask-app/
_PROJ_ROOT = _FLASK_APP.parent                    # 项目根
_DB_PATH = _FLASK_APP / "database" / "app.db"
_GIT_DIR = _PROJ_ROOT / ".git"

# 巡检周期
_SCAN_INTERVAL = 30  # 秒 — 文件扫描
_FULL_CHECK_INTERVAL = 300  # 秒 — 全量巡检

# 时间窗口
_FILE_MTIME_WINDOW = 600  # 秒 — 10 分钟内的文件变更
_GIT_SINCE_COMMITS = 5  # 向后看 N 个 commit

# 允许变更的路径（这些路径下的文件变更不强制 flow_id）
_ALLOWED_PATHS = [
    "_runtime/logs/",
    "_runtime/pids/",
    "logs/",
    "tmp/",
    "__pycache__/",
    ".pyc$",
    ".log$",
]

# 开发活动关键词（与 dev_activity_preflight.py 保持一致）
_DEV_FILE_EXTENSIONS = {".py", ".html", ".css", ".js", ".json", ".sql"}

# ═══════════════════════════════════════════════════════════
# DB 工具
# ═══════════════════════════════════════════════════════════
def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_tables(conn: sqlite3.Connection) -> None:
    """确保所需表存在 (主库已有真实表, 此函数只做软检查)"""
    # 检查表是否存在, 不存在时只打印警告 (不 CREATE, 用主库真实 schema)
    for tbl in ["mt_dev_flow_session", "mt_iron_rule_violations"]:
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
            ).fetchone()
            if not row:
                print(f"  [guard] ⚠️ 表 {tbl} 不存在", flush=True)
        except Exception:
            pass
    conn.commit()

def _has_legitimate_flow(conn: sqlite3.Connection) -> bool:
    """
    检查是否有"有效"的 flow_id:
    条件: current_step >= STEP_7_EXECUTE AND 最近 30 分钟内有更新
    (历史遗留的 STEP_9A/FINAL_DONE session 不算 — 可能是很久以前留下的)
    """
    ALLOWED = {
        "STEP_7_EXECUTE", "STEP_8_ACCEPTANCE",
        "STEP_9A_PASS_OR_LOOPBACK", "STEP_9B_SUMMARY",
        "STEP_10_SMART_VERSION_UPGRADE", "STEP_11_AUTO_GIT_SYNC",
        "STEP_12_TEST1000", "FINAL_DONE",
    }
    try:
        now_ts = time.time()
        CUTOFF = 1800  # 30 分钟内更新
        rows = conn.execute(
            "SELECT flow_id, current_step, final_status, updated_at "
            "FROM mt_dev_flow_session WHERE current_step IS NOT NULL"
        ).fetchall()

        # 解析 updated_at (真实 schema: updated_at TEXT)
        from datetime import datetime as _dt
        recent_valid = 0
        step_dist = {}
        for r in rows:
            step = r["current_step"] or "NULL"
            step_dist[step] = step_dist.get(step, 0) + 1

            if step not in ALLOWED:
                continue
            if r["final_status"] in ("DONE", "ABANDONED", "REJECTED", "BYPASSED"):
                continue

            # 检查最近更新时间
            try:
                ts_str = r["updated_at"] or ""
                if not ts_str:
                    continue  # updated_at 为空 → 太老了, 不算有效
                dt = _dt.fromisoformat(ts_str)
                upd_ts = dt.timestamp()
                if now_ts - upd_ts > CUTOFF:
                    continue  # 30 分钟以上没更新了, 不算有效
            except Exception:
                continue  # 时间解析失败 → 保守拒绝 (不算有效)

            recent_valid += 1
            if recent_valid >= 1:
                print(f"  [guard] ✅ 找到有效 flow_id={r['flow_id'][:40]} step={step}", flush=True)
                return True

        top3 = sorted(step_dist.items(), key=lambda x: -x[1])[:3]
        print(f"  [guard] session step top3: {top3} | recent_valid={recent_valid}", flush=True)
    except Exception as e:
        print(f"  [guard] _has_legitimate_flow 错误: {e}", flush=True)
    return False

def _record_violation(conn: sqlite3.Connection, detail: str, source: str) -> None:
    """
    落库 mt_iron_rule_violations (真实 schema)
    viol_id TEXT PRIMARY KEY, viol_rule, viol_stage, viol_action, viol_payload(TEXT JSON),
    viol_git_commit, viol_handler, viol_blocked INT, created_at REAL, updated_at REAL
    """
    now_ts = time.time()
    viol_id = f"guard_D9_{int(now_ts)}"
    payload = json.dumps({"reason": "IronRuleGuard detected file changes without flow_id",
                         "source": source, "detail": detail[:300]}, ensure_ascii=False)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO mt_iron_rule_violations"
            "(viol_id, viol_rule, viol_stage, viol_action, viol_payload,"
            " viol_handler, viol_blocked, viol_rolled_back, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (viol_id, "MT_IR_D9", "dev_activity_preflight", "WARN", payload,
             "IronRuleGuard", 1, 0, now_ts, now_ts)
        )
        conn.commit()
    except Exception as e:
        print(f"  [guard] record_violation 错误: {e}", flush=True)

def _feed_brain(conn: sqlite3.Connection, message: str, msg_type: str = "rule_violation") -> None:
    """投喂 AI 脑库"""
    now = datetime.now().isoformat()
    try:
        conn.execute(
            "INSERT INTO mt_ai_brain_feed_log(content, feed_type, created_at) VALUES(?,?,?)",
            (message, msg_type, now)
        )
        conn.commit()
    except Exception:
        pass  # 脑库不存在时静默忽略

# ═══════════════════════════════════════════════════════════
# 扫描器
# ═══════════════════════════════════════════════════════════
def _git_diff_changed_files() -> list:
    """通过 git diff HEAD~N 检测最近变更的文件"""
    try:
        result = subprocess.run(
            ["git", "diff", f"HEAD~{_GIT_SINCE_COMMITS}", "--name-only"],
            capture_output=True, text=True,
            cwd=str(_PROJ_ROOT), timeout=10
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except Exception:
        pass
    return []

def _recently_modified_files() -> list:
    """扫描 flask-app/ 下 mtime 最近变更的文件"""
    cutoff = time.time() - _FILE_MTIME_WINDOW
    changed = []
    try:
        for base in ["flask-app", "engines"]:
            p = _PROJ_ROOT / base
            if not p.exists():
                continue
            for root, dirs, files in os.walk(str(p)):
                # 跳过 __pycache__
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    fp = os.path.join(root, f)
                    ext = os.path.splitext(f)[1]
                    if ext not in _DEV_FILE_EXTENSIONS:
                        continue
                    try:
                        mtime = os.path.getmtime(fp)
                        if mtime > cutoff:
                            rel = os.path.relpath(fp, str(_PROJ_ROOT))
                            changed.append(rel)
                    except OSError:
                        continue
    except Exception as e:
        print(f"  [guard] _recently_modified_files 错误: {e}")
    return changed

def _is_allowed_path(filepath: str) -> bool:
    """检查文件路径是否在白名单内"""
    for pat in _ALLOWED_PATHS:
        if pat.endswith("$"):
            # 正则后缀匹配
            if filepath.endswith(pat[:-1]):
                return True
        elif pat in filepath:
            return True
    return False

def scan_once() -> dict:
    """
    一次完整扫描
    返回: {"git_changed": [...], "mtime_changed": [...], "merged": [...], "has_legit_flow": bool}
    """
    git_files = _git_diff_changed_files()
    mtime_files = _recently_modified_files()

    # 去重 + 白名单过滤
    all_files = list(set(git_files + mtime_files))
    filtered = [f for f in all_files if not _is_allowed_path(f)]

    result = {
        "git_changed": git_files,
        "mtime_changed": mtime_files,
        "merged": filtered,
        "has_legit_flow": False,
    }

    if filtered:
        conn = _get_db()
        try:
            result["has_legit_flow"] = _has_legitimate_flow(conn)
        finally:
            conn.close()

    return result

# ═══════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════
def main() -> None:
    print(f"[IronRuleGuard] §14 IRON_RULE 守护进程启动", flush=True)
    print(f"[IronRuleGuard] DB={_DB_PATH}", flush=True)
    print(f"[IronRuleGuard] git={_GIT_DIR.exists()}", flush=True)

    # 确保表存在
    conn = _get_db()
    _ensure_tables(conn)
    conn.close()
    print(f"[IronRuleGuard] 表就绪", flush=True)

    last_report_time = 0  # 上次详细报告时间
    violation_counter = 0  # 违规计数（限频）

    while True:
        try:
            result = scan_once()
            merged = result["merged"]
            has_flow = result["has_legit_flow"]

            now = time.time()

            if merged and not has_flow:
                # 检测到未授权变更
                violation_counter += 1
                # 限频：最多每 10 秒落库一次，10 分钟内同一批变更不重复落
                if violation_counter % 3 == 1:  # 3 * 30s = 90s 落一次
                    conn = _get_db()
                    try:
                        _ensure_tables(conn)
                        detail = (
                            f"detected {len(merged)} files changed without flow_id: "
                            + ", ".join(merged[:10])
                            + ("..." if len(merged) > 10 else "")
                        )
                        _record_violation(conn, detail, "IronRuleGuard")
                        _feed_brain(
                            conn,
                            f"⚠️ [MT_IR_D9] IronRuleGuard 检测到 {len(merged)} 个文件变更未走 12 步骤\n"
                            f"文件列表: {', '.join(merged[:15])}\n"
                            f"建议：先创建 flow_id 并走完 STEP_1→STEP_7 再实施",
                            "iron_rule_violation"
                        )
                        print(f"  [guard] ⚠️ 落库 MT_IR_D9 violation: {len(merged)} files", flush=True)
                    finally:
                        conn.close()

            # 详细报告（每 5 分钟一次）
            if now - last_report_time > _FULL_CHECK_INTERVAL:
                last_report_time = now
                print(
                    f"[IronRuleGuard] {datetime.now().strftime('%H:%M:%S')} "
                    f"scan: git={len(result['git_changed'])} "
                    f"mtime={len(result['mtime_changed'])} "
                    f"has_flow={has_flow} "
                    f"viol_count={violation_counter}",
                    flush=True
                )

                # 巡检 mt_iron_rule_violations
                conn = _get_db()
                try:
                    _ensure_tables(conn)
                    total = conn.execute(
                        "SELECT COUNT(*) FROM mt_iron_rule_violations"
                    ).fetchone()[0]
                    recent = conn.execute(
                        "SELECT viol_rule, COUNT(*) FROM mt_iron_rule_violations "
                        "GROUP BY viol_rule ORDER BY COUNT(*) DESC LIMIT 5"
                    ).fetchall()
                    print(f"  [guard] DB violations total={total}", flush=True)
                    for r in recent:
                        print(f"    {r[0]}: {r[1]}", flush=True)
                finally:
                    conn.close()

            # 下一轮
            time.sleep(_SCAN_INTERVAL)

        except KeyboardInterrupt:
            print(f"[IronRuleGuard] 收到中断, 退出", flush=True)
            break
        except Exception as e:
            print(f"[IronRuleGuard] 异常: {e}", flush=True)
            time.sleep(_SCAN_INTERVAL)

# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
