#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🛡️ 自身漏洞自扫描 → 任务大厅自动派单引擎 (flow_vuln_scan_dispatch_20261027)

闭环 (零 token 本地规则, 无外部依赖):
  ① 扫描   — 扫 flask-app 自身 *.py 源码 (shell=True / os.system / eval/exec /
             SQL 拼接注入 / 动态 DDL / 硬编码凭证)
  ② 发布   — 发现按 (规则,文件) 分组去重后自动入任务大厅 mt_lab_task_hall
             (source='vuln_scan', task_type=SECURITY, 系统身份发布免审批)
  ③ 下发   — 复用 _hall_dispatch_one 关键词路由 → 漏洞修复适配中心 (vuln_fix)
             + EigenFlux 磋商 → QUEUED→DISPATCHED
  ④ 领取   — transition_cas DISPATCHED→CLAIMED, 认领人=漏洞修复适配中心
             (修复交付仍走大厅人工/中心执行, 不做占位自动交付)

接入:
  - blueprints/daemon_skill_lab_bp.run_lab_daemon_loop 每 60min tick 自动跑
  - POST /api/daemon-lab/vuln-scan/run 手动触发
  - CLI: python3 ai_engines/ai_vuln_scan_dispatch_engine.py [--scan-only] [--max-tasks N]
"""

import os
import re
import sys
import json
import sqlite3
from datetime import datetime, timedelta

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)  # CLI 直跑时保证 blueprints/engines 可导入
MAIN_DB = os.path.join(_APP_DIR, "database", "app.db")

# 漏洞修复适配中心 (与 _SEED_CENTERS 同结构, 引擎兜底再 ensure 一次)
VULN_CENTER = ("vuln_fix", "漏洞修复适配中心", "安全适配",
               "漏洞,修复,安全,补丁,加固,适配,sql注入,命令执行,硬编码,凭证,shell")

_SRC_SUFFIX = ".py"
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
    "database", "static", "templates", "logs", "backups", "backup",
    "_git_quarantine", "_security_reports", "_runtime",
    "_SimpleMem_fusion", "_memvid_fusion", "_Hyper-Extract_fusion",
    "_Agent_Memory_Techniques_fusion", "tests", "test", "testing",
}
_SELF_FILE = os.path.abspath(__file__)

# 扫描规则: (rule_id, 名称, severity, 修复建议, 编译好的行正则)
_RULES = [
    ("VULN_SHELL_TRUE", "subprocess shell=True 命令执行", "critical",
     "去掉 shell=True 改列表参数传给 subprocess, 外部输入严禁拼进 shell 字符串",
     re.compile(r"shell\s*=\s*True")),
    ("VULN_OS_SYSTEM", "os.system 命令执行", "high",
     "改用 subprocess.run(列表参数, shell=False), 变量经 shlex.quote 转义或白名单校验",
     re.compile(r"\bos\.system\s*\(")),
    ("VULN_EVAL_EXEC", "eval/exec 动态代码执行", "high",
     "移除 eval/exec, 改用 ast.literal_eval 或显式函数映射表",
     re.compile(r"\b(?:eval|exec)\s*\(")),
    ("VULN_SQL_FSTRING", "f-string 拼接 SQL (注入)", "critical",
     "改参数化查询 conn.execute(sql, params), 禁止 f-string 内插 SQL 语句/表名",
     re.compile(r"\.execute\s*\(\s*f[\"']")),
    ("VULN_SQL_FORMAT", "%/.format 拼接 SQL (注入)", "critical",
     "改参数化查询 conn.execute(sql, params), 值走占位符 ?, 表名走白名单",
     re.compile(r"\.execute\s*\(\s*[\"'][^\"']*[\"']\s*(?:%|\.format\s*\()")),
    ("VULN_SQL_CONCAT", "字符串拼接 SQL (注入)", "high",
     "改参数化查询 conn.execute(sql, params), 禁止 \"...\" + 变量拼 SQL",
     re.compile(r"\.execute\s*\(\s*[\"'][^\"']*[\"']\s*\+")),
    ("VULN_DDL_DYNAMIC", "动态 DDL 表名拼接", "high",
     "ALTER/CREATE/DROP TABLE 表名改白名单映射表, 禁止 f-string/拼接构造表名",
     re.compile(r"f[\"'][^\"']*\b(?:ALTER|CREATE|DROP)\s+TABLE\b[^\"']*\{")),
    ("VULN_HARDCRED", "硬编码凭证", "medium",
     "改环境变量/密钥管理服务读取, 代码内仅保留占位引用",
     re.compile(r"\b(?:password|passwd|pwd|secret|api_key|apikey|access_key|secret_key|token)\s*"
                r"[=:]\s*[\"']([^\"']{6,})[\"']", re.I)),
]

# 硬编码凭证误报过滤 (test/示例/占位符直接跳过)
_CRED_FP_WORDS = (
    "example", "sample", "placeholder", "xxx", "your", "test", "dummy", "mock",
    "todo", "fixme", "changeme", "change_me", "demo", "示例", "占位", "替换",
    "${", "%s", "{", "<", "…", "...",
)
_CRED_FP_KEYS = ("os.environ", "getenv", "getpass", "input(", "config", ".get(")

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SEV_PRIORITY = {"critical": "HIGH", "high": "HIGH", "medium": "NORMAL", "low": "LOW"}


# ════════════════ ① 扫描 ════════════════

def _iter_py_files():
    for root, dirs, files in os.walk(_APP_DIR):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.endswith((".egg-info",))]
        for fn in files:
            if not fn.endswith(_SRC_SUFFIX) or fn.endswith((".bak", ".orig")):
                continue
            fp = os.path.join(root, fn)
            if os.path.abspath(fp) == _SELF_FILE:
                continue  # 跳过自身 (内含规则文本会自匹配)
            yield fp


def _cred_line_fp(line_lower):
    if any(w in line_lower for w in _CRED_FP_KEYS):
        return True
    return False


def scan_once():
    """扫描全部 py 文件, 返回 (groups, stats)
    groups: {(rule_id, relpath): {"rule","name","severity","fix","hits":[{"line","text"}]}}
    """
    groups, stats = {}, {"files": 0, "findings": 0, "errors": 0}
    for fp in _iter_py_files():
        rel = os.path.relpath(fp, _APP_DIR).replace(os.sep, "/")
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            stats["errors"] += 1
            continue
        stats["files"] += 1
        for i, raw in enumerate(lines, 1):
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            low = stripped.lower()
            for rule_id, name, sev, fix, rx in _RULES:
                m = rx.search(stripped)
                if not m:
                    continue
                if rule_id == "VULN_HARDCRED":
                    val = (m.group(1) or "").strip()
                    vl = val.lower()
                    if any(w in vl for w in _CRED_FP_WORDS) or _cred_line_fp(low):
                        continue
                g = groups.setdefault((rule_id, rel), {
                    "rule": rule_id, "name": name, "severity": sev, "fix": fix, "hits": []})
                g["hits"].append({"line": i, "text": stripped[:160]})
                stats["findings"] += 1
    return groups, stats


# ════════════════ ② 发布 → ③ 下发 → ④ 领取 ════════════════

def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_tables():
    conn = _db()
    try:
        # 适配中心兜底注册 (与 _SEED_CENTERS 幂等一致)
        conn.execute("INSERT OR IGNORE INTO mt_lab_centers (center_code,name,domain,keywords) "
                     "VALUES (?,?,?,?)", VULN_CENTER)
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def _fp_tag(rule_id, rel):
    return f"【fp:{rule_id}:{rel}】"


def _has_open_task(rule_id, rel):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT 1 FROM mt_lab_task_hall WHERE source='vuln_scan' "
            "AND instr(description, ?)>0 "
            "AND status NOT IN ('DONE','CANCELLED','VETOED','FAILED','ARCHIVED') LIMIT 1",
            (_fp_tag(rule_id, rel),)).fetchone()
        return row is not None
    finally:
        conn.close()


def _build_desc(g, rel):
    hits = g["hits"]
    lines_txt = "\n".join(f"  L{h['line']}: {h['text']}" for h in hits[:8])
    more = f"\n  ... 等共 {len(hits)} 处" if len(hits) > 8 else ""
    return (
        f"任务路由: 漏洞修复适配中心认领, 组织加固适配补丁\n"
        f"漏洞类型: {g['name']} ({g['severity']})\n"
        f"位置: {rel} 共 {len(hits)} 处命中\n"
        f"代表片段:\n{lines_txt}{more}\n"
        f"修复建议: {g['fix']}\n"
        f"验收标准: 该文件本规则复扫 0 命中, 且不引入新问题\n"
        f"{_fp_tag(g['rule'], rel)}"
    )


def _publish_one(conn, g, rel, now):
    """发布漏洞修复任务 → 返回 (task_id, hall_code, title)"""
    from blueprints.daemon_skill_lab_bp import _hall_next_code
    title = f"【安全修复】{g['name']} · {rel} ({len(g['hits'])}处)"[:120]
    code = _hall_next_code(conn)
    cur = conn.execute(
        "INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority,status,"
        "hall_code,publisher,publisher_role,task_type,acceptance_criteria,"
        "approval_status,approved_by,approved_at,updated_at) "
        "VALUES (?,?,?,?,?,'QUEUED',?,?,?,?,?,?,?,?,datetime('now','localtime'))",
        (title, _build_desc(g, rel), "vuln_scan", None,
         _SEV_PRIORITY.get(g["severity"], "NORMAL"), code,
         "vuln_scanner_agent", "super_admin", "SECURITY",
         f"1) 消除 {rel} 全部 {len(g['hits'])} 处 {g['name']} "
         f"2) 复扫该规则 0 命中 3) 不引入新风险",
         "APPROVED", "system", now))
    return cur.lastrowid, code, title


def run_vuln_scan_dispatch_once(max_tasks=12, scan_only=False):
    """主入口: 扫描 → 去重 → 发布 → 派单 → 适配中心领取. 返回 summary dict"""
    _ensure_tables()
    groups, stats = scan_once()
    if scan_only:
        return {"ok": True, "scan_only": True, **stats, "groups": len(groups)}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 发布顺序: severity 升序 (critical 最先), 同级按命中数降序
    ordered = sorted(groups.items(),
                     key=lambda kv: (_SEV_RANK.get(kv[1]["severity"], 9), -len(kv[1]["hits"])))
    published, skipped, capped = [], 0, 0
    for (rule_id, rel), g in ordered:
        if len(published) >= max_tasks:
            capped += 1
            continue
        if _has_open_task(rule_id, rel):
            skipped += 1
            continue
        conn = _db()
        try:
            task_id, code, title = _publish_one(conn, g, rel, now)
            conn.commit()
        finally:
            conn.close()
        published.append({"task_id": task_id, "hall_code": code, "title": title,
                          "severity": g["severity"], "count": len(g["hits"]), "file": rel})

    if not published:
        return {"ok": True, **stats, "groups": len(groups),
                "published": [], "skipped_existing": skipped, "capped": capped}

    # ③ 下发 + ④ 领取 (复用大厅既有闭环)
    from blueprints.daemon_skill_lab_bp import _hall_dispatch_one, _hall_task_event
    from engines.ai_task_hall_flow_engine import transition_cas
    for p in published:
        try:
            conn = _db()
            try:
                row = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (p["task_id"],)).fetchone()
            finally:
                conn.close()
            d = _hall_dispatch_one(dict(row))
            p["center"] = d.get("center")
            p["dispatched"] = d.get("status") == "DISPATCHED"
            if p["center"] != VULN_CENTER[1]:
                p["route_warning"] = f"路由到 {p['center']} (期望 {VULN_CENTER[1]})"
            p["verdict"] = (d.get("verdict") or "")[:60]
        except Exception as e:
            p["dispatched"] = False
            p["error"] = str(e)[:200]
            continue
        if not p.get("dispatched"):
            continue  # 磋商未过留 QUEUED, daemon run_hall_auto 下一轮自动重派
        try:
            won, _, _, _info = transition_cas(
                p["task_id"], "DISPATCHED", "CLAIMED", actor="VULN-FIX-CENTER",
                reason="漏洞修复适配中心自动领取修复任务",
                extra={"claim_owner": "漏洞修复适配中心", "claim_owner_role": "center",
                       "claim_type": "team", "claimed_at": now,
                       "deadline_at": (datetime.now() + timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")})
            p["claimed"] = bool(won)
            if won:
                _hall_task_event(p["task_id"], "CLAIM", "vuln_fix_center", "center",
                                 "适配中心自动领取 (72h 内开工)")
        except Exception as e:
            p["claimed"] = False
            p["claim_error"] = str(e)[:200]

    # 审计落库 (可回溯)
    try:
        conn = _db()
        try:
            conn.execute(
                "INSERT INTO mt_lab_audit_log (operator,operator_role,center,action,subject,detail_json) "
                "VALUES (?,?,?,?,?,?)",
                ("vuln_scanner_agent", "system_daemon", "lab", "VULN_SCAN_DISPATCH",
                 f"扫描{stats['files']}文件/{stats['findings']}发现 发布{len(published)}单",
                 json.dumps({"published": published, "stats": stats}, ensure_ascii=False, default=str)[:4000]))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass

    return {"ok": True, **stats, "groups": len(groups), "published": published,
            "skipped_existing": skipped, "capped": capped}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="自身漏洞自扫描 → 任务大厅派单引擎")
    ap.add_argument("--scan-only", action="store_true", help="只扫描不发布")
    ap.add_argument("--max-tasks", type=int, default=12, help="单次最多发布任务数 (默认12)")
    args = ap.parse_args()
    r = run_vuln_scan_dispatch_once(max_tasks=args.max_tasks, scan_only=args.scan_only)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
