#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座医疗中心 + 冰山健康体检引擎
══════════════════════════════════════════════
flow: flow_medical_center_20261102

## 双端体检架构
🧬 仙女座 (andromeda_core)：自演化主控 → 7个维度
🧊 冰山 (iceberg_command)：安全合规总指挥 → 6个维度

## 三层触发机制
┌─────────────────────────────────────────────────────────────────┐
│  实时体检  │  协作总线事件 (MARKET_ANOMALY/CRITICAL_ALERT/...)  │
│            │  → 立即触发仙女座+冰山小体检 (10s内出结果)        │
├─────────────────────────────────────────────────────────────────┤
│  定时体检  │  每1h: 全量小体检 (健康分)                        │
│            │  每24h: 大体检 (全量扫描+深度诊断)               │
├─────────────────────────────────────────────────────────────────┤
│  不定时    │  版本变更/DB异常/skill注册/daemon crash          │
│            │  → 触发针对性体检 + 自动修复建议                 │
└─────────────────────────────────────────────────────────────────┘

## 自动入厅闭环
体检 → 生成报告 → mt_medical_center_reports
  ↓ (健康分<80 或发现bug)
生成任务 → mt_task_hall (task_type='MEDICAL_EXAM')
  ↓ tick flow 自动结案
DONE / 修复建议入厅

## DB 表
- mt_medical_center_reports  — 体检报告 (双端)
- mt_medical_center_bugs     — bug库 (可修复)
- mt_medical_center_skill_registry — 已注册的 Skill/Agent/Hook

## REST API (via medical_center_bp)
- GET  /api/medical/exam?target=andromeda|iceberg|both&level=quick|full|deep
- GET  /api/medical/reports?limit=50
- GET  /api/medical/bugs?status=open|fixed|all
- GET  /api/medical/status        — 健康概览
- POST /api/medical/trigger       — 手动触发体检
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
# 路径 & DB 配置
# ═══════════════════════════════════════════════════════════════════
BASE = Path(__file__).resolve().parent.parent  # flask-app/
PROJECT_ROOT = BASE.parent

# 和 andromeda_core / iceberg_command 一致的 DB 解析逻辑
_PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
_ONEDRIVE_DB = BASE / "database" / "app.db"
_DB_ENV = os.environ.get('ANDROMEDA_DB') or os.environ.get('APP_DB')
if _DB_ENV and os.path.exists(_DB_ENV):
    DB_PATH = Path(_DB_ENV)
elif _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
    DB_PATH = _PROD_LOCAL
else:
    DB_PATH = _ONEDRIVE_DB

OLLAMA_URL = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')


def _conn() -> sqlite3.Connection:
    """统一 DB 连接 (check_same_thread=False 支持跨线程)"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════
# §1 DB 表初始化
# ═══════════════════════════════════════════════════════════════════
def ensure_medical_tables() -> None:
    """初始化医疗中心三张核心表 (幂等)"""
    conn = _conn()
    try:
        conn.executescript("""
        -- 体检报告 (双端)
        CREATE TABLE IF NOT EXISTS mt_medical_center_reports (
            report_id      TEXT PRIMARY KEY,
            target         TEXT NOT NULL,           -- andromeda | iceberg | both
            exam_level     TEXT NOT NULL,           -- quick | full | deep
            trigger_type   TEXT NOT NULL,           -- realtime | scheduled | manual | version_change
            health_score   INTEGER DEFAULT 0,       -- 0-100 健康分
            overall_status TEXT DEFAULT 'unknown',  -- healthy | warning | critical | unknown
            dimensions     TEXT DEFAULT '{}',        -- JSON: 各维度分数
            bugs_found     INTEGER DEFAULT 0,
            suggestions    TEXT DEFAULT '[]',        -- JSON: 修复建议列表
            report_json    TEXT DEFAULT '{}',        -- 完整报告 JSON
            hall_task_id   TEXT,                     -- 关联任务大厅 ID
            created_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_med_reports_target ON mt_medical_center_reports(target, created_at);
        CREATE INDEX IF NOT EXISTS idx_med_reports_score ON mt_medical_center_reports(health_score);

        -- Bug 库 (可修复)
        CREATE TABLE IF NOT EXISTS mt_medical_center_bugs (
            bug_id         TEXT PRIMARY KEY,
            report_id      TEXT,
            target         TEXT NOT NULL,
            category       TEXT NOT NULL,            -- daemon|ollama|db|thread|rule|firewall|config
            severity       TEXT DEFAULT 'medium',    -- low|medium|high|critical
            description    TEXT NOT NULL,
            fix_suggestion TEXT,
            auto_fixed     INTEGER DEFAULT 0,
            fix_status     TEXT DEFAULT 'open',      -- open|fixed|ignored|in_progress
            fixed_at       TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_med_bugs_status ON mt_medical_center_bugs(fix_status, severity);

        -- Skill/Agent/Hook 注册表
        CREATE TABLE IF NOT EXISTS mt_medical_center_skill_registry (
            skill_id       TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            type           TEXT NOT NULL,            -- skill|agent|hook|openclaw
            target_center  TEXT NOT NULL,            -- 所属中心
            trigger_event  TEXT,                     -- 触发事件 (JSON array)
            last_checked   TEXT,
            health_status  TEXT DEFAULT 'unknown',   -- healthy|degraded|dead
            version_info   TEXT DEFAULT '{}',        -- JSON: 版本信息
            registered_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_med_skill_center ON mt_medical_center_skill_registry(target_center, type);
        """)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §2 公共工具函数
# ═══════════════════════════════════════════════════════════════════
def _now_iso() -> str:
    return datetime.now().isoformat()


def _gen_id(prefix: str) -> str:
    import hashlib
    raw = f"{prefix}-{time.time_ns()}-{os.getpid()}"
    return f"{prefix}-{hashlib.md5(raw.encode()).hexdigest()[:10]}"


def _http_check(url: str, timeout: float = 3.0) -> Tuple[bool, str, float]:
    """HTTP 健康检查 → (ok, status, latency_ms)"""
    t0 = time.time()
    try:
        import urllib.request
        req = urllib.request.Request(url, method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        latency = (time.time() - t0) * 1000
        return True, f"HTTP {resp.status}", latency
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return False, str(e)[:100], latency


def _ollama_check() -> Tuple[bool, str, float]:
    """Ollama 健康检查 (api/tags)"""
    return _http_check(f"{OLLAMA_URL.replace('/api/chat', '')}/api/tags", timeout=3.0)


def _process_check(keyword: str) -> Tuple[bool, str]:
    """检查系统进程中是否有 keyword"""
    try:
        result = os.popen(f"ps aux | grep -i '{keyword}' | grep -v grep").read().strip()
        if result:
            return True, result.split('\n')[0][:120]
        return False, f"未找到包含 '{keyword}' 的进程"
    except Exception as e:
        return False, f"进程检查失败: {e}"


def _db_simple_check() -> Tuple[bool, str, float]:
    """DB 简单健康检查 (1+1)"""
    t0 = time.time()
    try:
        conn = _conn()
        cur = conn.execute("SELECT 1 AS test")
        result = cur.fetchone()['test']
        conn.close()
        latency = (time.time() - t0) * 1000
        return (result == 1), f"DB OK ({latency:.1f}ms)", latency
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return False, f"DB 失败: {str(e)[:80]}", latency


def _thread_count() -> int:
    """当前 Flask 进程的线程数"""
    try:
        return threading.active_count()
    except Exception:
        return -1


def _file_readable(path: str) -> Tuple[bool, str]:
    """检查文件是否存在+可读"""
    p = Path(path)
    if p.exists():
        try:
            size = p.stat().st_size
            return True, f"存在 ({size:,} bytes)"
        except Exception as e:
            return False, f"存在但不可读: {e}"
    return False, "不存在"


# ═══════════════════════════════════════════════════════════════════
# §3 仙女座体检 (7 个维度)
# ═══════════════════════════════════════════════════════════════════
def exam_andromeda(level: str = 'full') -> Dict[str, Any]:
    """仙女座体检 → 返回维度字典"""
    dims: Dict[str, Any] = {}
    bugs: List[Dict[str, Any]] = []
    
    # 🧬 D1: 核心文件存在性
    core_files = [
        str(BASE / "engines" / "andromeda_core.py"),
        str(BASE / "engines" / "andromeda_bridge.py"),
        str(BASE / "engines" / "andromeda_auto_evolution.py"),
        str(BASE / "VERSION"),
    ]
    file_ok = 0
    for f in core_files:
        ok, info = _file_readable(f)
        if ok:
            file_ok += 1
        else:
            bugs.append({
                "category": "config",
                "target": "andromeda",
                "severity": "high",
                "description": f"核心文件缺失: {os.path.basename(f)}",
                "fix_suggestion": f"检查文件是否被误删或路径是否正确"
            })
    dims["core_files"] = {"score": int(file_ok / len(core_files) * 100), 
                            "detail": f"{file_ok}/{len(core_files)} 核心文件存在"}
    
    # 🧬 D2: Ollama 可达
    ollama_ok, ollama_info, ollama_lat = _ollama_check()
    dims["ollama"] = {"score": 100 if ollama_ok else 0, 
                       "detail": ollama_info, "latency_ms": round(ollama_lat, 1)}
    if not ollama_ok:
        bugs.append({"category": "ollama", "target": "andromeda", "severity": "critical",
                     "description": f"Ollama 不可达: {ollama_info}",
                     "fix_suggestion": "启动 Ollama: `ollama serve` 或检查端口 11434"})
    
    # 🧬 D3: DB 连接
    db_ok, db_info, db_lat = _db_simple_check()
    dims["db_connectivity"] = {"score": 100 if db_ok else 0,
                                "detail": db_info, "latency_ms": round(db_lat, 1)}
    if not db_ok:
        bugs.append({"category": "db", "target": "andromeda", "severity": "critical",
                     "description": f"DB 连接失败: {db_info}",
                     "fix_suggestion": "检查 DB 文件权限和锁状态"})
    
    # 🧬 D4: 进化循环状态 (从 mt_evolution_suggestions 表)
    evo_score = 100
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM mt_evolution_suggestions WHERE created_at > datetime('now', '-1 day')"
        ).fetchone()
        recent_cnt = row['cnt']
        if recent_cnt > 0:
            evo_score = 100
        else:
            # 检查最近一次 evolution run
            last_run = conn.execute(
                "SELECT run_at FROM mt_evolution_runs ORDER BY run_at DESC LIMIT 1"
            ).fetchone() if False else None  # 表可能不存在
            evo_score = 70  # 没有近期 suggestions 但没有 run 表也算正常
        conn.close()
    except Exception as e:
        evo_score = 80  # 表不存在不算严重
    dims["evolution_loop"] = {"score": evo_score, "detail": "进化循环正常" if evo_score >= 90 else "进化循环可能停滞"}
    
    # 🧬 D5: RAG 向量库
    rag_db = BASE / "database" / "local_rag_vectors.db"
    rag_ok, rag_info = _file_readable(str(rag_db))
    rag_score = 100 if rag_ok else 60  # 可选组件
    dims["rag_library"] = {"score": rag_score, "detail": rag_info}
    if not rag_ok and level in ('full', 'deep'):
        bugs.append({"category": "config", "target": "andromeda", "severity": "low",
                     "description": f"RAG 向量库不存在",
                     "fix_suggestion": "首次启动仙女座会自动构建 RAG 库"})
    
    # 🧬 D6: 线程健康
    thread_cnt = _thread_count()
    thread_score = 100 if 2 <= thread_cnt <= 50 else (80 if thread_cnt > 0 else 60)
    dims["thread_health"] = {"score": thread_score, "detail": f"线程数={thread_cnt}"}
    
    # 🧬 D7: 端口 8888 服务状态
    flask_ok, flask_info, flask_lat = _http_check("http://127.0.0.1:8888/index", timeout=3.0)
    dims["flask_service"] = {"score": 100 if flask_ok else 40,
                               "detail": flask_info, "latency_ms": round(flask_lat, 1)}
    if not flask_ok:
        bugs.append({"category": "daemon", "target": "andromeda", "severity": "high",
                     "description": f"Flask 服务 (8888) 不可达",
                     "fix_suggestion": "重启 Flask: `pkill -9 -f modular_start; nohup python3 modular_start.py &`"})
    
    return dims, bugs


# ═══════════════════════════════════════════════════════════════════
# §4 冰山体检 (6 个维度)
# ═══════════════════════════════════════════════════════════════════
def exam_iceberg(level: str = 'full') -> Dict[str, Any]:
    """冰山体检 → 返回维度字典"""
    dims: Dict[str, Any] = {}
    bugs: List[Dict[str, Any]] = []
    
    # 🧊 D1: 规则表存在性 (冰山核心)
    conn = _conn()
    try:
        rule_tables = [
            'mt_iron_rules', 'mt_iron_rule_violations', 'mt_iceberg_runs',
        ]
        rule_ok = 0
        for t in rule_tables:
            try:
                r = conn.execute(f"SELECT COUNT(*) AS cnt FROM {t}").fetchone()
                if r:
                    rule_ok += 1
            except sqlite3.OperationalError:
                pass
        dims["rule_system"] = {"score": int(rule_ok / len(rule_tables) * 100),
                                 "detail": f"{rule_ok}/{len(rule_tables)} 规则表存在"}
        if rule_ok < len(rule_tables):
            bugs.append({"category": "rule", "target": "iceberg", "severity": "medium",
                         "description": f"冰山规则表缺失 ({rule_ok}/{len(rule_tables)})",
                         "fix_suggestion": "首次启动冰山时会自动创建规则表"})
    finally:
        conn.close()
    
    # 🧊 D2: 最近安全运行
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, MAX(run_at) AS last_run FROM mt_iceberg_runs WHERE run_at > datetime('now', '-12 hours')"
        ).fetchone()
        recent_runs = row['cnt'] or 0
        last_run = row['last_run']
        iceberg_score = 100 if recent_runs > 0 else 60
        dims["recent_runs"] = {"score": iceberg_score,
                                "detail": f"12h内运行{recent_runs}次, 最近: {last_run or '无'}"}
        if recent_runs == 0:
            bugs.append({"category": "daemon", "target": "iceberg", "severity": "medium",
                         "description": f"冰山 12h 内无运行记录",
                         "fix_suggestion": "检查冰山 daemon 是否在运行"})
    except Exception as e:
        dims["recent_runs"] = {"score": 80, "detail": f"无 mt_iceberg_runs 表"}
    finally:
        conn.close()
    
    # 🧊 D3: 违规记录监控
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM mt_iron_rule_violations WHERE created_at > datetime('now', '-24 hours') AND severity IN ('critical','high')"
        ).fetchone()
        critical_violations = row['cnt'] or 0
        violation_score = max(0, 100 - critical_violations * 10)
        dims["violation_monitor"] = {"score": violation_score,
                                      "detail": f"24h 内严重违规 {critical_violations} 条"}
        if critical_violations > 3:
            bugs.append({"category": "rule", "target": "iceberg", "severity": "high",
                         "description": f"24h 内严重违规 {critical_violations} 条",
                         "fix_suggestion": "触发冰山自动研究新规则封堵漏洞"})
    except Exception:
        dims["violation_monitor"] = {"score": 80, "detail": "违规监控表不存在"}
    finally:
        conn.close()
    
    # 🧊 D4: 核心文件
    iceberg_files = [
        str(BASE / "engines" / "iceberg_command.py"),
        str(BASE / "engines" / "iceberg_consciousness.py"),
        str(BASE / "engines" / "iceberg_handshake.py"),
    ]
    file_ok = 0
    for f in iceberg_files:
        if _file_readable(f)[0]:
            file_ok += 1
    dims["core_files"] = {"score": int(file_ok / len(iceberg_files) * 100),
                            "detail": f"{file_ok}/{len(iceberg_files)} 核心文件存在"}
    
    # 🧊 D5: Ollama 共用
    ollama_ok, ollama_info, _ = _ollama_check()
    dims["ollama"] = {"score": 100 if ollama_ok else 0, "detail": ollama_info}
    if not ollama_ok:
        bugs.append({"category": "ollama", "target": "iceberg", "severity": "critical",
                     "description": "冰山依赖的 Ollama 不可达",
                     "fix_suggestion": "同仙女座 Ollama 修复"})
    
    # 🧊 D6: 防火墙状态 (deep level)
    fw_score = 100
    if level in ('full', 'deep'):
        try:
            fw_result = os.popen("sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null || echo 'unknown'").read().strip()
            if 'enabled' in fw_result.lower() or '1' in fw_result:
                fw_score = 100
            elif 'disabled' in fw_result.lower() or '0' in fw_result:
                fw_score = 50
                bugs.append({"category": "firewall", "target": "iceberg", "severity": "high",
                             "description": "macOS 防火墙已关闭",
                             "fix_suggestion": "sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on"})
            else:
                fw_score = 80
        except Exception:
            fw_score = 80
    dims["firewall"] = {"score": fw_score, "detail": "防火墙状态正常" if fw_score >= 90 else "防火墙可能未启用"}
    
    return dims, bugs


# ═══════════════════════════════════════════════════════════════════
# §5 统一体检入口 + 健康分计算
# ═══════════════════════════════════════════════════════════════════
def run_exam(target: str = 'both', level: str = 'full', 
             trigger_type: str = 'manual') -> Dict[str, Any]:
    """
    统一体检入口
    target: andromeda | iceberg | both
    level:  quick(快速，只查核心) | full(常规，全维度) | deep(深度，含防火墙/文件扫描)
    trigger_type: realtime | scheduled | manual | version_change | crash
    """
    report_id = _gen_id("MED")
    all_dims: Dict[str, Any] = {}
    all_bugs: List[Dict[str, Any]] = []
    target_label = target
    
    t0 = time.time()
    
    # 体检选择
    if target in ('andromeda', 'both'):
        ad, ab = exam_andromeda(level)
        all_dims[f"andromeda"] = ad
        all_bugs.extend(ab)
    if target in ('iceberg', 'both'):
        id_, ib = exam_iceberg(level)
        all_dims[f"iceberg"] = id_
        all_bugs.extend(ib)
    
    # 计算综合健康分
    all_scores: List[int] = []
    for sys_dims in all_dims.values():
        for d_name, d_val in sys_dims.items():
            s = d_val.get('score', 50) if isinstance(d_val, dict) else 50
            all_scores.append(s)
    
    avg_score = int(sum(all_scores) / len(all_scores)) if all_scores else 0
    # Bug 扣分: 每个 critical -15, high -8, medium -3
    bug_penalty = 0
    for b in all_bugs:
        sev = b.get('severity', 'medium')
        bug_penalty += {'critical': 15, 'high': 8, 'medium': 3, 'low': 1}.get(sev, 3)
    health_score = max(0, avg_score - bug_penalty)
    
    # 总体状态
    if health_score >= 85:
        overall = 'healthy'
    elif health_score >= 70:
        overall = 'warning'
    elif health_score >= 50:
        overall = 'degraded'
    else:
        overall = 'critical'
    
    elapsed = time.time() - t0
    
    # 构建完整报告
    report = {
        "report_id": report_id,
        "target": target_label,
        "exam_level": level,
        "trigger_type": trigger_type,
        "health_score": health_score,
        "overall_status": overall,
        "dimensions": all_dims,
        "bugs_found": len(all_bugs),
        "bugs_detail": all_bugs,
        "elapsed_s": round(elapsed, 2),
        "created_at": _now_iso(),
    }
    
    # 写入 DB
    _save_report(report, all_bugs)
    
    return report


def _save_report(report: Dict[str, Any], bugs: List[Dict[str, Any]]) -> None:
    """保存体检报告 + bug 到 DB"""
    report_id = report['report_id']
    conn = _conn()
    try:
        # 插入报告
        conn.execute(
            "INSERT INTO mt_medical_center_reports "
            "(report_id, target, exam_level, trigger_type, health_score, overall_status, "
            "dimensions, bugs_found, suggestions, report_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (report_id, report['target'], report['exam_level'], report['trigger_type'],
             report['health_score'], report['overall_status'],
             json.dumps(report['dimensions'], ensure_ascii=False),
             report['bugs_found'],
             json.dumps([b.get('fix_suggestion', '') for b in bugs], ensure_ascii=False),
             json.dumps(report, ensure_ascii=False),
             report['created_at'])
        )
        # 插入 bug
        for b in bugs:
            bug_id = _gen_id("BUG")
            conn.execute(
                "INSERT OR IGNORE INTO mt_medical_center_bugs "
                "(bug_id, report_id, target, category, severity, description, fix_suggestion) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (bug_id, report_id, b.get('target', report['target']),
                 b.get('category', 'unknown'), b.get('severity', 'medium'),
                 b.get('description', ''), b.get('fix_suggestion', ''))
            )
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"[MEDICAL] 保存报告失败: {e}\n")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §6 自动入厅 (体检结果 → 任务大厅)
# ═══════════════════════════════════════════════════════════════════
def submit_to_hall(report: Dict[str, Any]) -> Optional[str]:
    """
    将体检结果提交到任务大厅
    - 健康分 >= 85 且无 bug → 提交正常体检报告，自动结案
    - 健康分 < 85 或有 bug → 提交修复任务，走正常发配流程
    """
    report_id = report['report_id']
    health_score = report['health_score']
    overall = report['overall_status']
    bugs = report.get('bugs_detail', [])
    
    # ── 确保 mt_task_hall 表存在 (自动创建) ──
    try:
        conn = _conn()
        # 检查表是否存在
        tbl_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mt_task_hall'"
        ).fetchone()
        if not tbl_exists:
            sys.stderr.write("[MEDICAL] mt_task_hall 表不存在, 自动创建...\n")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mt_task_hall (
                    hall_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    hall_code        TEXT UNIQUE NOT NULL,
                    task_title       TEXT NOT NULL,
                    task_type        TEXT NOT NULL,
                    description      TEXT,
                    source           TEXT,
                    source_id        TEXT,
                    target_center    TEXT,
                    hall_priority    TEXT DEFAULT 'NORMAL',
                    publish_at       TEXT DEFAULT (datetime('now')),
                    status           TEXT DEFAULT 'NEW',
                    deliverable      TEXT,
                    created_at       TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
            sys.stderr.write("[MEDICAL] ✅ mt_task_hall 表自动创建完成\n")
        conn.close()
    except Exception as e:
        sys.stderr.write(f"[MEDICAL] mt_task_hall 表检查失败: {e}\n")
    
    try:
        # 尝试导入任务大厅引擎 (可选, 主要用于状态机流转)
        sys.path.insert(0, str(BASE))
        from engines.ai_task_hall_flow_engine import (
            STATUS_NEW, KEYWORD_CENTER_ROUTES, LEGAL_TRANSITIONS, _conn as _hall_conn
        )
    except Exception as e:
        sys.stderr.write(f"[MEDICAL] 任务大厅引擎未就绪 (非致命, 直接INSERT): {e}\n")
    
    # 构建任务描述
    title_prefix = "🧬仙女座" if report['target'] in ('andromeda', 'both') else "🧊冰山"
    exam_desc = f"""
{title_prefix}医疗中心体检报告
═══════════════════════════════════
报告ID: {report_id}
体检级别: {report['exam_level']}
触发方式: {report['trigger_type']}
健康分: {health_score}/100
总体状态: {overall}
Bug 数量: {len(bugs)}
耗时: {report['elapsed_s']}s
═══════════════════════════════════
体检时间: {report['created_at']}
"""
    
    if bugs:
        bug_list = "\n".join([f"  [{b.get('severity','?').upper()}] {b.get('description','')}" for b in bugs])
        exam_desc += f"\n发现的 Bug:\n{bug_list}\n"
    
    # 确定任务类型和 center
    if overall == 'healthy':
        # 健康体检报告 → 归档，自动结案
        task_title = f"✅ {title_prefix}体检结案 — 健康分 {health_score}"
        task_type = "MEDICAL_EXAM_REPORT"
        target_center = "gov_coordinate"  # 归档到政务中心
    else:
        # 有问题 → 需要修复
        critical_bugs = [b for b in bugs if b.get('severity') in ('critical', 'high')]
        if critical_bugs:
            task_title = f"🔴 {title_prefix}紧急修复 — {len(critical_bugs)}个高危Bug"
            task_type = "MEDICAL_EMERGENCY_FIX"
            target_center = "sec_ops" if any(b.get('category') in ('firewall', 'rule') for b in critical_bugs) else "backend"
            hall_priority = "CRITICAL"
        else:
            task_title = f"🟡 {title_prefix}常规修复 — {len(bugs)}个Bug"
            task_type = "MEDICAL_ROUTINE_FIX"
            target_center = "backend"
            hall_priority = "HIGH"
    
    # 插入任务大厅
    conn = _conn()
    try:
        # 生成 hall_code: MEDICAL_YYYYMMDD_XXX
        from datetime import datetime as _dt
        date_str = _dt.now().strftime("%Y%m%d")
        # 获取当日序号
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM mt_task_hall WHERE hall_code LIKE ?",
            (f"MEDICAL_{date_str}%",)
        ).fetchone()
        seq = (row['cnt'] or 0) + 1
        hall_code = f"MEDICAL_{date_str}_{seq:03d}"
        
        conn.execute(
            "INSERT INTO mt_task_hall "
            "(hall_code, task_title, task_type, description, source, source_id, "
            "target_center, hall_priority, publish_at, status, deliverable) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hall_code, task_title, task_type, exam_desc,
             "medical_center_v1", report_id,
             target_center, hall_priority if 'hall_priority' in dir() else ("CRITICAL" if overall == 'critical' else ("HIGH" if overall == 'warning' else "NORMAL")),
             _now_iso(), "NEW",
             json.dumps(report, ensure_ascii=False))
        )
        
        # 同时更新体检报告的 hall_task_id
        conn.execute(
            "UPDATE mt_medical_center_reports SET hall_task_id = ? WHERE report_id = ?",
            (hall_code, report_id)
        )
        conn.commit()
        
        sys.stderr.write(f"[MEDICAL] 已入厅: {hall_code} → {target_center} ({task_type})\n")
        return hall_code
        
    except Exception as e:
        sys.stderr.write(f"[MEDICAL] 入厅失败: {e}\n")
        conn.rollback()
        return None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §7 三层触发控制器 + Daemon
# ═══════════════════════════════════════════════════════════════════
class MedicalCenterDaemon:
    """
    医疗中心守护线程
    ┌─ 实时触发: 协作总线事件 (MARKET_ANOMALY/CRITICAL_ALERT/VERSION_CHANGE/...)
    ├─ 定时触发: 每 3600s (1h) 小体检; 每 86400s (24h) 大体检
    └─ 不定时: _manual_trigger / _crash_trigger / _version_trigger
    """
    
    _instance: Optional['MedicalCenterDaemon'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'MedicalCenterDaemon':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._stop_event = threading.Event()
        self._last_hourly = 0.0
        self._last_daily = 0.0
        self._thread: Optional[threading.Thread] = None
        self._subscribed = False
        self._realtime_interval = 1.0   # 实时体检冷却 1s (防止风暴)
        self._last_realtime = 0.0
    
    # ── 生命周期 ──
    def start(self) -> None:
        """启动 daemon (必须放在 Flask app.run() 之后)"""
        if self._thread and self._thread.is_alive():
            sys.stderr.write("[MEDICAL] daemon 已在运行\n")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name='medical-daemon',
            daemon=True
        )
        self._thread.start()
        # 确保 ALLOW_KEYWORDS 放行
        sys.stderr.write("[MEDICAL] ✅ 医疗中心 daemon 启动 (实时+定时+不定时 三层触发)\n")
        
        # 尝试注册协作总线订阅
        self._try_subscribe_collab()
    
    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        sys.stderr.write("[MEDICAL] daemon 停止\n")
    
    # ── 协作总线订阅 ──
    def _try_subscribe_collab(self) -> None:
        """尝试向协作总线注册为订阅者"""
        try:
            sys.path.insert(0, str(BASE))
            from engines.collab_bus_engine import get_collab_bus
            bus = get_collab_bus()
            bus.subscribe(
                subscriber_id="medical_center",
                subscriber_name="仙女座医疗中心",
                subscribe_events=["MARKET_ANOMALY", "CRITICAL_ALERT", 
                                  "VERSION_CHANGE", "CRASH_ALERT", "DAEMON_STOPPED"],
                event_handler=self._on_collab_event,
                priority=90
            )
            self._subscribed = True
            sys.stderr.write("[MEDICAL] ✅ 协作总线订阅成功\n")
        except Exception as e:
            sys.stderr.write(f"[MEDICAL] 协作总线订阅延迟 (等 collab_bus_engine 加载): {e}\n")
            # 延迟订阅: 30s 后重试
            def _retry_later():
                time.sleep(30)
                self._try_subscribe_collab()
            threading.Thread(target=_retry_later, name='medical-subscribe-retry', daemon=True).start()
    
    def _on_collab_event(self, event: Dict[str, Any]) -> None:
        """协作总线事件回调 → 实时触发体检"""
        event_type = event.get('event_type', '')
        source = event.get('source', '')
        severity = event.get('severity', 'INFO')
        now = time.time()
        
        # 冷却: 1s 内同一个 source 不重复触发
        if now - self._last_realtime < self._realtime_interval:
            return
        self._last_realtime = now
        
        sys.stderr.write(f"[MEDICAL] 🔥 实时触发: {event_type} (severity={severity}, src={source})\n")
        
        # 根据事件类型决定体检范围
        target = 'both'
        level = 'quick'
        if event_type in ('CRITICAL_ALERT', 'CRASH_ALERT', 'DAEMON_STOPPED'):
            level = 'full'
        elif event_type == 'MARKET_ANOMALY':
            level = 'quick'
        
        try:
            report = run_exam(target=target, level=level, trigger_type='realtime')
            # 只有非健康状态才自动入厅
            if report['overall_status'] != 'healthy':
                hall_code = submit_to_hall(report)
                sys.stderr.write(f"[MEDICAL] 实时体检: 健康分={report['health_score']}, 入厅={hall_code or '跳过(健康)'}\n")
            else:
                sys.stderr.write(f"[MEDICAL] 实时体检: ✅ 健康分={report['health_score']} → 不入厅\n")
        except Exception as e:
            sys.stderr.write(f"[MEDICAL] 实时体检异常: {e}\n")
    
    # ── 主循环 ──
    def _run_loop(self) -> None:
        sys.stderr.write("[MEDICAL] loop 开始 (cycle=1h 小体检, 24h 大体检)\n")
        
        # 启动后先跑一次 quick 体检 (确认系统正常)
        try:
            time.sleep(5)  # 等 Flask 完全就绪
            sys.stderr.write("[MEDICAL] 🚀 启动自检...")
            report = run_exam(target='both', level='quick', trigger_type='scheduled')
            sys.stderr.write(f" 健康分={report['health_score']}\n")
            if report['overall_status'] != 'healthy':
                submit_to_hall(report)
        except Exception as e:
            sys.stderr.write(f"[MEDICAL] 启动自检异常: {e}\n")
        
        self._last_hourly = time.time()
        self._last_daily = time.time()
        
        while not self._stop_event.is_set():
            try:
                now = time.time()
                
                # ⏰ 每 3600s (1h) → 全量小体检
                if now - self._last_hourly >= 3600:
                    sys.stderr.write("[MEDICAL] ⏰ 定时触发: 1h 全量小体检")
                    report = run_exam(target='both', level='full', trigger_type='scheduled')
                    sys.stderr.write(f" 健康分={report['health_score']}\n")
                    if report['overall_status'] != 'healthy':
                        submit_to_hall(report)
                    self._last_hourly = now
                
                # ⏰ 每 86400s (24h) → 大体检
                if now - self._last_daily >= 86400:
                    sys.stderr.write("[MEDICAL] 🌙 定时触发: 24h 大体检 (深度扫描)")
                    report = run_exam(target='both', level='deep', trigger_type='scheduled')
                    sys.stderr.write(f" 健康分={report['health_score']}, Bug={report['bugs_found']}\n")
                    submit_to_hall(report)  # 大体检结果全部入厅
                    self._last_daily = now
                
                # 心跳: 每 300s 打一条
                # (避免过度日志)
                
            except Exception as e:
                sys.stderr.write(f"[MEDICAL] loop 异常: {e}\n")
            
            # 10s 一次检查 (足够响应实时触发 + 检查定时)
            self._stop_event.wait(timeout=10)
        
        sys.stderr.write("[MEDICAL] loop 退出\n")


# ═══════════════════════════════════════════════════════════════════
# §8 公共 API
# ═══════════════════════════════════════════════════════════════════
def get_medical_center() -> MedicalCenterDaemon:
    """获取医疗中心单例"""
    return MedicalCenterDaemon()


def trigger_realtime_exam(event_type: str = "MANUAL_TRIGGER", 
                          severity: str = "INFO",
                          target: str = 'both') -> Dict[str, Any]:
    """
    对外接口: 触发一次实时体检 (供 Blueprint/协作总线调用)
    """
    report = run_exam(target=target, level='quick', trigger_type='realtime')
    hall_code = None
    if report['overall_status'] != 'healthy':
        hall_code = submit_to_hall(report)
    report['hall_code'] = hall_code
    return report


def trigger_version_change_exam(version: str, component: str) -> Dict[str, Any]:
    """
    版本变更触发体检 → 不定时体检
    """
    report = run_exam(target='both', level='full', trigger_type='version_change')
    # 关联版本信息
    report['version_info'] = {"version": version, "component": component}
    hall_code = None
    if report['overall_status'] != 'healthy':
        hall_code = submit_to_hall(report)
    report['hall_code'] = hall_code
    return report


def get_recent_reports(limit: int = 50) -> List[Dict[str, Any]]:
    """获取最近体检报告"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT report_id, target, exam_level, trigger_type, health_score, "
            "overall_status, bugs_found, created_at "
            "FROM mt_medical_center_reports ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_bugs(status: str = 'open') -> List[Dict[str, Any]]:
    """获取 bug 列表"""
    conn = _conn()
    try:
        if status == 'all':
            rows = conn.execute(
                "SELECT bug_id, report_id, target, category, severity, "
                "description, fix_suggestion, fix_status, auto_fixed, created_at "
                "FROM mt_medical_center_bugs ORDER BY severity, created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT bug_id, report_id, target, category, severity, "
                "description, fix_suggestion, fix_status, auto_fixed, created_at "
                "FROM mt_medical_center_bugs WHERE fix_status = ? ORDER BY severity, created_at DESC",
                (status,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_health_summary() -> Dict[str, Any]:
    """健康概览 (供 status API)"""
    conn = _conn()
    try:
        # 最近一次体检
        last_report = conn.execute(
            "SELECT target, health_score, overall_status, bugs_found, created_at "
            "FROM mt_medical_center_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        
        # 统计
        total_reports = conn.execute(
            "SELECT COUNT(*) AS cnt FROM mt_medical_center_reports"
        ).fetchone()['cnt']
        open_bugs = conn.execute(
            "SELECT COUNT(*) AS cnt FROM mt_medical_center_bugs WHERE fix_status = 'open'"
        ).fetchone()['cnt']
        critical_bugs = conn.execute(
            "SELECT COUNT(*) AS cnt FROM mt_medical_center_bugs WHERE fix_status = 'open' AND severity IN ('critical','high')"
        ).fetchone()['cnt']
        
        return {
            "last_report": dict(last_report) if last_report else None,
            "total_reports": total_reports,
            "open_bugs": open_bugs,
            "critical_bugs": critical_bugs,
            "daemon_status": MedicalCenterDaemon()._thread.is_alive() if MedicalCenterDaemon()._thread else False,
            "subscribed_to_collab": MedicalCenterDaemon()._subscribed,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §9 CLI 入口 (独立运行)
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="仙女座医疗中心体检")
    parser.add_argument("--target", default="both", choices=["andromeda", "iceberg", "both"])
    parser.add_argument("--level", default="full", choices=["quick", "full", "deep"])
    parser.add_argument("--daemon", action="store_true", help="启动守护线程")
    parser.add_argument("--submit", action="store_true", help="体检后自动入厅")
    args = parser.parse_args()
    
    ensure_medical_tables()
    
    if args.daemon:
        print(f"[MEDICAL] 启动 daemon (target={args.target}, level={args.level})...")
        get_medical_center().start()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            get_medical_center().stop()
    else:
        report = run_exam(target=args.target, level=args.level, trigger_type='manual')
        print(f"\n{'='*60}")
        print(f"🧬 仙女座+冰山 医疗中心体检报告")
        print(f"{'='*60}")
        print(f"报告ID: {report['report_id']}")
        print(f"目标:   {report['target']}")
        print(f"级别:   {report['exam_level']}")
        print(f"健康分: {report['health_score']}/100  ⚡")
        print(f"状态:   {report['overall_status'].upper()}")
        print(f"Bug数:  {report['bugs_found']}")
        print(f"耗时:   {report['elapsed_s']}s")
        print(f"时间:   {report['created_at']}")
        
        for sys_name, dims in report['dimensions'].items():
            print(f"\n  📊 {sys_name} 维度:")
            for d, v in dims.items():
                score = v.get('score', '?') if isinstance(v, dict) else '?'
                detail = v.get('detail', '') if isinstance(v, dict) else ''
                print(f"    {d:20s} → {score:>3s}  {detail[:60]}")
        
        if report['bugs_detail']:
            print(f"\n  🐛 BUG LIST:")
            for b in report['bugs_detail']:
                print(f"    [{b.get('severity','?').upper():8s}] {b.get('target','?'):10s} → {b.get('description','')[:50]}")
        
        if args.submit:
            hall_code = submit_to_hall(report)
            print(f"\n  📨 已入厅: {hall_code or '跳过(健康)'}")
        
        print(f"{'='*60}\n")
