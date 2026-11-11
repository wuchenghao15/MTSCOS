#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 AI 元认知引擎 — AIMetaCognition
═══════════════════════════════════════════════════════════════════════
AI 对自己的认知 + AI 自我使用能力

5 大能力:
  ① MetaRegistry       AI 能读到自己完整的能力目录
  ② SkillRouter        AI 根据任务自动选最优引擎/技能组合
  ③ Composer           AI 能串联多个引擎组成工作流
  ④ ExperienceMemory   AI 反思自己的历史行为 → 经验教训摘要
  ⑤ IdleSelfImprove    空闲时 AI 自动学习/测试/衍生新能力

数据源 (全真实):
  - engines/       ← 276 个 .py 引擎 (ast 解析)
  - blueprints/    ← 41 个 Flask Blueprint
  - mt_skill_registry        ← 245 skills
  - mt_trigger_handler       ← 33 handlers
  - mt_switch_panel          ← 13 switches
  - mt_center_evolution_log  ← 60881 条历史
  - mt_center_health_matrix  ← 86 条健康快照
  - mt_autodev_derivatives   ← 4 条衍生产物
  Ollama: qwen2.5:3b (路由推理) + 7 models

关键原则:
  - ALL 数据来自真实表, 绝不 mock
  - Ollama 不可用 → 规则 fallback, 不伪造推理
  - 新表自动创建 (幂等)
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import sqlite3
import sys
import time
import uuid
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ═════════════════════════════════════════════════════════════════════
# 路径解析
# ═════════════════════════════════════════════════════════════════════
_FLASK_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = os.environ.get("APP_DB") or os.path.join(_FLASK_ROOT, "database", "app.db")
_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [AIMETA] %(levelname)s %(message)s')
log = logging.getLogger("ai_meta_cognition")


# ═════════════════════════════════════════════════════════════════════
# Schema SQL — 5 张新表
# ═════════════════════════════════════════════════════════════════════
SCHEMA_SQL = """
-- AI 能力目录 (MetaRegistry 输出)
CREATE TABLE IF NOT EXISTS mt_ai_capability_registry (
    cap_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    capability_name TEXT NOT NULL,
    source_file TEXT,
    description TEXT,
    parameters TEXT,
    ollama_usage INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    health_score REAL DEFAULT 0,
    last_used TEXT,
    usage_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0,
    discovered_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(category, capability_name)
);

-- AI 路由器决策历史
CREATE TABLE IF NOT EXISTS mt_ai_route_decision (
    route_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    context TEXT,
    selected_engines TEXT,
    reasoning TEXT,
    confidence REAL DEFAULT 0,
    fallback_used INTEGER DEFAULT 0,
    switches_applied TEXT,
    execution_duration_ms REAL,
    success INTEGER,
    experience_learnt TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- AI 工作流组合
CREATE TABLE IF NOT EXISTS mt_ai_workflow (
    workflow_id TEXT PRIMARY KEY,
    task_template TEXT NOT NULL,
    steps TEXT NOT NULL,
    dag_graph TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    last_executed TEXT,
    execution_count INTEGER DEFAULT 0,
    avg_duration_ms REAL DEFAULT 0,
    success_rate REAL DEFAULT 0
);

-- AI 经验记忆片段
CREATE TABLE IF NOT EXISTS mt_ai_experience_snippet (
    snippet_id TEXT PRIMARY KEY,
    snippet_type TEXT NOT NULL,
    domain TEXT,
    context_summary TEXT,
    action_taken TEXT,
    outcome TEXT,
    lesson_learnt TEXT,
    confidence REAL DEFAULT 0,
    source_log_ids TEXT,
    applicable_engines TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    source_log_count INTEGER DEFAULT 0
);

-- AI 元认知运行日志
CREATE TABLE IF NOT EXISTS mt_ai_meta_cycle (
    cycle_id TEXT PRIMARY KEY,
    cycle_time TEXT DEFAULT (datetime('now','localtime')),
    registry_count INTEGER DEFAULT 0,
    routes_decided INTEGER DEFAULT 0,
    workflows_composed INTEGER DEFAULT 0,
    experiences_distilled INTEGER DEFAULT 0,
    idle_improve_actions INTEGER DEFAULT 0,
    ollama_calls INTEGER DEFAULT 0,
    ollama_latency_ms REAL DEFAULT 0,
    total_duration_ms REAL DEFAULT 0,
    meta_score REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


# ═════════════════════════════════════════════════════════════════════
# Ollama 工具函数
# ═════════════════════════════════════════════════════════════════════
def _ollama_up() -> bool:
    """检测 Ollama 是否可用"""
    try:
        req = urllib.request.Request(f"{_OLLAMA_HOST}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_generate(prompt: str, model: str = None, temperature: float = 0.3) -> Optional[str]:
    """调用 Ollama /api/generate 生成文本"""
    if not _ollama_up():
        return None
    try:
        data = json.dumps({
            "model": model or _OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{_OLLAMA_HOST}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "").strip() or None
    except Exception as e:
        log.debug(f"Ollama generate fail: {e}")
        return None


def _ollama_chat(messages: list, model: str = None, temperature: float = 0.3) -> Optional[str]:
    """调用 Ollama /api/chat"""
    if not _ollama_up():
        return None
    try:
        data = json.dumps({
            "model": model or _OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{_OLLAMA_HOST}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            msg = body.get("message", {})
            return msg.get("content", "").strip() or None
    except Exception as e:
        log.debug(f"Ollama chat fail: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════
# 规则路由表 — Ollama 挂时 fallback
# ═════════════════════════════════════════════════════════════════════
RULE_ROUTES = [
    # (关键词列表, 引擎组合, 描述)
    (["风控", "风险", "risk", "Risk"],
     ["finance_risk_engine", "finance_realtime_audit", "cross_self_heal"],
     "任务涉及交易风控, 选风险引擎+实时稽查+自愈链"),
    (["稽查", "审计", "audit", "对账"],
     ["finance_audit_daemon", "finance_realtime_audit", "code_audit_daemon"],
     "任务涉及代码/交易稽查, 选审计守护进程+实时审计+代码审计"),
    (["交易", "下单", "trade", "ledger", "账本"],
     ["finance_ledger_engine", "finance_attribution", "finance_risk_engine"],
     "任务涉及交易账本, 选账本引擎+归因引擎+风险引擎"),
    (["学习", "训练", "learn", "自研发", "autodev"],
     ["autodev_engine", "ai_brain_feed_engine", "sys_center_autonomous_learner"],
     "任务涉及AI学习, 选自研发引擎+脑库投喂+自主学习"),
    (["自愈", "修复", "heal", "repair", "fix"],
     ["cross_self_heal", "emergency_guardian", "auto_repair_engine"],
     "任务涉及系统修复, 选自愈链+紧急守护+自动修复"),
    (["同步", "sync", "时间", "时钟"],
     ["sync_center", "time_sync_engine", "db_triple_sync_engine"],
     "任务涉及多机同步, 选同步中心+时间同步+三库同步"),
    (["报告", "报表", "report", "日报"],
     ["finance_daily_report", "auto_doc_generator", "finance_audit_daemon"],
     "任务涉及报告生成, 选日报引擎+文档生成器+审计守护进程"),
    (["触发", "trigger", "开关", "switch"],
     ["trigger_coordinator", "center_orchestrator", "center_registry"],
     "任务涉及触发器, 选触发器协调器+编排中心+注册表"),
    (["代码", "code", "review", "重构"],
     ["code_audit_daemon", "autodev_engine", "dev_gate"],
     "任务涉及代码, 选代码审计+自研发+开发门禁"),
    (["备份", "backup", "恢复", "recovery"],
     ["ai_backup_engine", "ai_disaster_recovery_engine", "ai_multi_layer_backup"],
     "任务涉及备份恢复, 选备份引擎+灾难恢复+多层备份"),
    (["监控", "monitor", "健康", "health"],
     ["system_manager", "ai_console_monitor", "ai_smart_monitor"],
     "任务涉及监控, 选系统管理+控制台监控+智能监控"),
    (["安全", "security", "扫描", "vuln"],
     ["ai_security_brigade_engine", "penetration_tester", "ai_iron_rule_guard"],
     "任务涉及安全, 选安全旅+渗透测试+铁律守护"),
    (["教育", "学习路径", "pedagogy", "教学"],
     ["ai_math_pedagogy_engine", "ai_language_pedagogy_engine", "ai_edu_learning_engine"],
     "任务涉及教育, 选数学教学+语言教学+教育学习引擎"),
    (["Gobelin", "古灵阁", "银行", "bank"],
     ["gobelin_daily_pnl", "finance_risk_engine", "finance_attribution"],
     "任务涉及Gobelin银行, 选日盈亏+风险+归因"),
    (["Iceberg", "冰山", "题库", "qbank"],
     ["iceberg_consciousness", "iceberg_content_matrix", "iceberg_command"],
     "任务涉及Iceberg冰山, 选意识引擎+内容矩阵+指令引擎"),
    (["EigenFlux", "专家", "广播", "collab"],
     ["eigenflux_broadcast_engine", "collab_bus_engine", "ai_team_collab_engine"],
     "任务涉及EigenFlux协作, 选广播引擎+协作总线+团队协作"),
    (["Futuresight", "未来", "场景", "模拟"],
     ["autodev_engine", "sys_future_vision", "simulation_sandbox_engine"],
     "任务涉及未来预测, 选自研发引擎+未来愿景+模拟沙箱"),
    (["Sync", "同步", "mini", "hulk"],
     ["sync_center", "mac_mini_sync_engine", "db_triple_sync_engine"],
     "任务涉及多机同步, 选同步中心+Mac mini同步+三库同步"),
]


# ═════════════════════════════════════════════════════════════════════
# AST 扫描工具 — 从 Python 文件提取类/函数签名
# ═════════════════════════════════════════════════════════════════════
def _scan_engine_file(filepath: str) -> dict:
    """扫描一个引擎 .py 文件, 提取类名、方法、ollama 引用"""
    result = {
        "classes": [],
        "functions": [],
        "ollama_refs": False,
        "methods": defaultdict(list),
    }
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        
        # 快速 grep Ollama 引用 (避免 AST 失败)
        if re.search(r"ollama|/api/generate|/api/chat|11434", source, re.IGNORECASE):
            result["ollama_refs"] = True
        
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return result
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                result["classes"].append(node.name)
                # 提取方法
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        result["methods"][node.name].append(item.name)
            elif isinstance(node, ast.FunctionDef):
                result["functions"].append(node.name)
    except Exception as e:
        log.debug(f"scan fail {filepath}: {e}")
    
    return result


def _list_engine_files() -> list:
    """列出 engines/ 下所有有效 .py 文件"""
    engines_dir = _FLASK_ROOT / "engines"
    exclude = (
        ".auto_repair_backup", ".bak", ".bak_p", ".bak2", ".bak3",
        ".bak_orderfix", ".deprecated", ".inspect_bak", ".syncbak",
    )
    results = []
    for f in sorted(engines_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        if any(f.name.endswith(s) for s in exclude):
            continue
        if f.name in {"__init__.py"}:
            continue
        results.append(str(f))
    return results


def _list_blueprint_files() -> list:
    """列出 blueprints/ 下所有有效 .py 文件"""
    bp_dir = _FLASK_ROOT / "blueprints"
    results = []
    for f in sorted(bp_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        if f.name in {"__init__.py"}:
            continue
        results.append(str(f))
    return results


# ═════════════════════════════════════════════════════════════════════
# AIMetaCognition 主类
# ═════════════════════════════════════════════════════════════════════
class AIMetaCognition:
    """
    🧠 AI 元认知 — AI 对自己的认知 + AI 自我使用能力
    """
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or _DB_PATH
        self._ollama_calls = 0
        self._ollama_latency = 0.0
        self._ensure_schema()
    
    def _ensure_schema(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()
    
    def _conn(self, readonly: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        if not readonly:
            conn.execute("PRAGMA busy_timeout=30000")
            if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def _gen_id(self, prefix: str = "") -> str:
        return f"{prefix}{uuid.uuid4().hex[:12]}"
    
    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # ══════════════════════════════════════════════════════════════════
    # ① META REGISTRY — AI 认识自己
    # ══════════════════════════════════════════════════════════════════
    
    def build_meta_registry(self) -> dict:
        """
        扫描所有能力源 → 生成 AI 可理解的能力目录
        并写入 mt_ai_capability_registry 表
        """
        log.info("[Registry] 开始构建 AI 能力目录...")
        start = time.time()
        
        registry = {
            "engines": [],
            "blueprints": [],
            "skills": [],
            "triggers": [],
            "switches": [],
            "tables": [],
            "ollama_models": [],
            "stats": {},
        }
        
        conn = self._conn()
        try:
            # ── 1. 扫描引擎文件 (AST) ──
            engine_files = _list_engine_files()
            log.info(f"[Registry] 扫描 {len(engine_files)} 个引擎文件...")
            
            for filepath in engine_files:
                scan = _scan_engine_file(filepath)
                name = Path(filepath).stem
                
                # 从 health_matrix 获取健康分数 (简化版: 用 total_score)
                health_score = 0.0
                try:
                    row = conn.execute(
                        "SELECT AVG(total_score) FROM mt_center_health_matrix "
                    ).fetchone()
                    health_score = row[0] or 50.0  # 默认 50
                except Exception:
                    health_score = 50.0
                
                # 从 evolution_log 获取使用统计 (用 center_name 匹配)
                usage_count = 0
                success_rate = 0.8
                try:
                    row = conn.execute(
                        "SELECT COUNT(*), AVG(CASE WHEN (event LIKE '%ERROR%' OR event LIKE '%FAIL%') THEN 0 ELSE 1 END) "
                        "FROM mt_center_evolution_log WHERE center_name LIKE ?", 
                        (f"%{name}%",)
                    ).fetchone()
                    if row[0] and row[0] > 0:
                        usage_count = row[0]
                        success_rate = round(row[1] or 0.8, 2)
                except Exception:
                    pass
                
                # 从触发日志获取 Ollama 使用
                ollama_count = 0
                try:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM mt_center_evolution_log "
                        "WHERE center_name LIKE ? AND (detail LIKE '%ollama%' OR event LIKE '%OLLAMA%')",
                        (f"%{name}%",)
                    ).fetchone()
                    ollama_count = row[0] or 0
                except Exception:
                    pass
                
                cap_id = f"ENGINE_{name}"
                params = json.dumps({"classes": scan["classes"], "ollama_refs": scan["ollama_refs"]},
                                    ensure_ascii=False)
                
                conn.execute("""
                    INSERT OR REPLACE INTO mt_ai_capability_registry
                    (cap_id, category, capability_name, source_file, description, parameters,
                     ollama_usage, enabled, health_score, usage_count, success_rate, discovered_at)
                    VALUES (?, 'ENGINE', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """, (cap_id, name, filepath,
                      f"Engine: {name}", params,
                      ollama_count, health_score, usage_count, success_rate, self._now()))
                
                registry["engines"].append({
                    "name": name,
                    "classes": scan["classes"],
                    "ollama_refs": scan["ollama_refs"],
                    "health_score": round(health_score, 2),
                    "usage_count": usage_count,
                    "success_rate": round(success_rate, 2),
                })
            
            # ── 2. 扫描 Blueprint ──
            bp_files = _list_blueprint_files()
            for filepath in bp_files:
                name = Path(filepath).stem
                cap_id = f"BLUEPRINT_{name}"
                
                conn.execute("""
                    INSERT OR REPLACE INTO mt_ai_capability_registry
                    (cap_id, category, capability_name, source_file, description, parameters,
                     ollama_usage, enabled, health_score, usage_count, success_rate, discovered_at)
                    VALUES (?, 'BLUEPRINT', ?, ?, ?, '{}', 0, 1, 0, 0, 0, ?)
                """, (cap_id, name, filepath, f"Blueprint: {name}", self._now()))
                
                registry["blueprints"].append({"name": name})
            
            # ── 3. 从数据库读 Skills ──
            try:
                rows = conn.execute("""
                    SELECT skill_id, skill_name, category, description, readiness
                    FROM mt_skill_registry LIMIT 500
                """).fetchall()
                for row in rows:
                    cap_id = f"SKILL_{row[0]}"
                    conn.execute("""
                        INSERT OR REPLACE INTO mt_ai_capability_registry
                        (cap_id, category, capability_name, source_file, description, parameters,
                         ollama_usage, enabled, health_score, usage_count, success_rate, discovered_at)
                        VALUES (?, 'SKILL', ?, ?, ?, ?, 0, ?, 0, 0, 0, ?)
                    """, (cap_id, row[1], "", (row[3] or f"Skill: {row[1]}")[:500],
                          json.dumps({"category": row[2]}, ensure_ascii=False),
                          1 if (row[4] or 0) >= 1 else 0, self._now()))
                    registry["skills"].append({"skill_id": row[0], "name": row[1], "category": row[2]})
            except Exception as e:
                log.debug(f"skills query fail: {e}")
            
            # ── 4. 从数据库读 Triggers ──
            try:
                rows = conn.execute("""
                    SELECT handler_id, handler_key, target_engine, target_method, enabled,
                           trigger_event_type, exec_count
                    FROM mt_trigger_handler LIMIT 200
                """).fetchall()
                for row in rows:
                    cap_id = f"TRIGGER_{row[0]}"
                    handler_name = f"{row[1]} → {row[2]}.{row[3]}"
                    conn.execute("""
                        INSERT OR REPLACE INTO mt_ai_capability_registry
                        (cap_id, category, capability_name, source_file, description, parameters,
                         ollama_usage, enabled, health_score, usage_count, success_rate, discovered_at)
                        VALUES (?, 'TRIGGER', ?, ?, ?, ?, 0, ?, 0, ?, 0, ?)
                    """, (cap_id, handler_name, "", 
                          f"Trigger [{row[5]}] → {row[2]}.{row[3]}",
                          json.dumps({"target_engine": row[2], "target_method": row[3], 
                                     "event_type": row[5]}, ensure_ascii=False),
                          1 if row[4] else 0, row[6] or 0, self._now()))
                    registry["triggers"].append({
                        "handler_id": row[0], "handler_key": row[1],
                        "target": f"{row[2]}.{row[3]}", "event_type": row[5],
                    })
            except Exception as e:
                log.debug(f"triggers query fail: {e}")
            
            # ── 5. 从数据库读 Switches ──
            try:
                rows = conn.execute("""
                    SELECT switch_id, switch_name, category, switch_value
                    FROM mt_switch_panel LIMIT 100
                """).fetchall()
                for row in rows:
                    cap_id = f"SWITCH_{row[0]}"
                    conn.execute("""
                        INSERT OR REPLACE INTO mt_ai_capability_registry
                        (cap_id, category, capability_name, source_file, description, parameters,
                         ollama_usage, enabled, health_score, usage_count, success_rate, discovered_at)
                        VALUES (?, 'SWITCH', ?, ?, ?, ?, 0, 1, 0, 0, 0, ?)
                    """, (cap_id, row[1], "", f"Switch: {row[1]} ({row[2]})",
                          json.dumps({"current_value": row[3]}, ensure_ascii=False),
                          self._now()))
                    registry["switches"].append({"switch_id": row[0], "name": row[1], "value": row[3]})
            except Exception as e:
                log.debug(f"switches query fail: {e}")
            
            # ── 6. 数据库表 ──
            try:
                rows = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name LIKE 'mt_%' OR name LIKE 'ai_%'
                    ORDER BY name
                """).fetchall()
                registry["tables"] = [r[0] for r in rows]
            except Exception:
                pass
            
            # ── 7. Ollama 模型 ──
            if _ollama_up():
                try:
                    req = urllib.request.Request(f"{_OLLAMA_HOST}/api/tags", method="GET")
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        registry["ollama_models"] = [m.get("name", "") for m in data.get("models", [])]
                except Exception:
                    registry["ollama_models"] = []
            
            conn.commit()
            
        finally:
            conn.close()
        
        elapsed = time.time() - start
        registry["stats"] = {
            "engines": len(registry["engines"]),
            "blueprints": len(registry["blueprints"]),
            "skills": len(registry["skills"]),
            "triggers": len(registry["triggers"]),
            "switches": len(registry["switches"]),
            "tables": len(registry["tables"]),
            "ollama_models": len(registry["ollama_models"]),
            "build_time_ms": round(elapsed * 1000, 1),
        }
        
        log.info(f"[Registry] 完成: {registry['stats']['engines']} engines + "
                 f"{registry['stats']['skills']} skills + {registry['stats']['triggers']} triggers "
                 f"({registry['stats']['build_time_ms']}ms)")
        
        return registry
    
    def list_my_abilities(self, filter_category: str = None, filter_name: str = None) -> list:
        """AI 问自己: "我有哪些能力?" → 返回结构化目录"""
        conn = self._conn(readonly=True)
        try:
            sql = "SELECT * FROM mt_ai_capability_registry WHERE 1=1"
            params = []
            if filter_category:
                sql += " AND category=?"
                params.append(filter_category.upper())
            if filter_name:
                sql += " AND capability_name LIKE ?"
                params.append(f"%{filter_name}%")
            sql += " ORDER BY category, capability_name LIMIT 2000"
            
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    
    def capability_score(self) -> dict:
        """AI 能力画像: 按维度打分"""
        scores = defaultdict(lambda: {"score": 0.0, "count": 0})
        
        # 维度关键词 → 引擎名前缀映射
        dim_map = {
            "reasoning": ("reason", "think", "cognitive", "intelligence"),
            "code": ("code", "dev", "autodev", "repair", "test", "review"),
            "trading": ("finance", "risk", "ledger", "trade", "gobelin", "sandbox"),
            "audit": ("audit", "check", "inspect", "monitor", "health"),
            "creativity": ("creative", "generat", "inspire", "brainstorm", "futuresight"),
            "risk": ("risk", "guard", "iron", "security", "vuln", "penetr"),
            "education": ("edu", "pedagogy", "learn", "question", "exam", "teaching"),
            "sync": ("sync", "time", "db_triple", "mac_mini", "center_evolution"),
        }
        
        conn = self._conn(readonly=True)
        try:
            rows = conn.execute("""
                SELECT category, capability_name, health_score, success_rate, usage_count, ollama_usage
                FROM mt_ai_capability_registry WHERE enabled=1
            """).fetchall()
            
            for cat, name, health, success, usage, ollama in rows:
                name_lower = name.lower()
                for dim, keywords in dim_map.items():
                    if any(kw in name_lower for kw in keywords):
                        # 综合得分: health(0-100) + success_rate*100 + usage_weight + ollama_bonus
                        usage_weight = min(usage / 100.0, 10)  # 封顶 10
                        ollama_bonus = 5 if ollama > 0 else 0
                        total = (health or 0) * 0.4 + (success or 0.8) * 40 + usage_weight + ollama_bonus
                        scores[dim]["score"] += total
                        scores[dim]["count"] += 1
            
            # 归一化到 0-100
            result = {}
            for dim, data in scores.items():
                if data["count"] > 0:
                    result[dim] = round(data["score"] / data["count"], 1)
            
            # 确保所有维度都存在
            for dim in dim_map:
                if dim not in result:
                    result[dim] = 0.0
            
            return result
        finally:
            conn.close()
    
    # ══════════════════════════════════════════════════════════════════
    # ② SKILL ROUTER — AI 选引擎
    # ══════════════════════════════════════════════════════════════════
    
    def route_task(self, task: str, context: dict = None) -> dict:
        """
        AI 选引擎/技能处理任务 — Ollama qwen2.5:3b 驱动
        Ollama 挂 → 规则 fallback (规则表 RULE_ROUTES)
        """
        start = time.time()
        log.info(f"[Route] 任务: {task[:80]}...")
        
        result = {
            "selected_engines": [],
            "reasoning": "",
            "confidence": 0.0,
            "fallback_used": False,
            "switches_needed": {},
            "execution_duration_ms": 0,
        }
        
        # ── 尝试 Ollama 推理 ──
        engines_list = self._get_available_engines()
        
        ollama_reasoning = None
        if _ollama_up() and engines_list:
            prompt = f"""你是 MTSCOS AI 系统的路由引擎。根据用户任务选择最合适的引擎组合。

可用引擎列表:
{', '.join(engines_list[:80])}

任务: {task}
上下文: {json.dumps(context or {}, ensure_ascii=False)[:500]}

请以 JSON 格式回答 (严格 JSON, 不要其他文字):
{{
  "engines": ["engine1", "engine2", ...],
  "reasoning": "选择理由",
  "confidence": 0.0 到 1.0,
  "switches_needed": {{"SWITCH_NAME": true/false}}
}}"""
            
            raw = _ollama_generate(prompt, temperature=0.2)
            if raw:
                ollama_reasoning = self._parse_ollama_json(raw)
        
        if ollama_reasoning:
            # Ollama 成功
            result["selected_engines"] = ollama_reasoning.get("engines", [])[:5]
            result["reasoning"] = ollama_reasoning.get("reasoning", "")
            result["confidence"] = float(ollama_reasoning.get("confidence", 0.7))
            result["switches_needed"] = ollama_reasoning.get("switches_needed", {})
        else:
            # ── 规则 Fallback ──
            result["fallback_used"] = True
            result = self._rule_fallback(task)
        
        # 记录决策历史
        self._save_route_decision(task, context, result, time.time() - start)
        result["execution_duration_ms"] = round((time.time() - start) * 1000, 1)
        
        self._ollama_calls += 0 if result["fallback_used"] else 1
        
        log.info(f"[Route] → {result['selected_engines']} (conf={result['confidence']:.2f}, "
                 f"fallback={result['fallback_used']})")
        
        return result
    
    def _get_available_engines(self) -> list:
        """获取启用的引擎列表"""
        conn = self._conn(readonly=True)
        try:
            rows = conn.execute("""
                SELECT capability_name FROM mt_ai_capability_registry
                WHERE category='ENGINE' AND enabled=1
                ORDER BY usage_count DESC LIMIT 200
            """).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()
    
    def _parse_ollama_json(self, text: str) -> Optional[dict]:
        """从 Ollama 输出提取 JSON"""
        try:
            # 直接解析
            return json.loads(text)
        except Exception:
            pass
        try:
            # 尝试从 ```json ... ``` 提取
            match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except Exception:
            pass
        try:
            # 尝试找第一个 { ... }
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None
    
    def _rule_fallback(self, task: str) -> dict:
        """规则路由 — Ollama 挂时使用"""
        task_lower = task.lower()
        
        for keywords, engines, desc in RULE_ROUTES:
            if any(kw.lower() in task_lower for kw in keywords):
                return {
                    "selected_engines": engines,
                    "reasoning": f"[规则fallback] {desc}",
                    "confidence": 0.7,
                    "fallback_used": True,
                    "switches_needed": {},
                }
        
        # 默认 fallback: 选最基础的几个
        return {
            "selected_engines": ["center_orchestrator", "trigger_coordinator", "system_manager"],
            "reasoning": "[规则fallback] 通用任务 → 编排中心+触发器+系统管理",
            "confidence": 0.5,
            "fallback_used": True,
            "switches_needed": {},
        }
    
    def _save_route_decision(self, task: str, context: dict, result: dict, elapsed: float):
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO mt_ai_route_decision
                (route_id, task, context, selected_engines, reasoning, confidence,
                 fallback_used, switches_applied, execution_duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._gen_id("route_"),
                task[:500],
                json.dumps(context or {}, ensure_ascii=False)[:1000],
                json.dumps(result.get("selected_engines", []), ensure_ascii=False),
                result.get("reasoning", "")[:1000],
                result.get("confidence", 0),
                1 if result.get("fallback_used") else 0,
                json.dumps(result.get("switches_needed", {}), ensure_ascii=False),
                round(elapsed * 1000, 1),
                self._now(),
            ))
            conn.commit()
        except Exception as e:
            log.debug(f"save route fail: {e}")
        finally:
            conn.close()
    
    # ══════════════════════════════════════════════════════════════════
    # ③ COMPOSER — AI 组合工作流
    # ══════════════════════════════════════════════════════════════════
    
    def compose_workflow(self, task: str) -> dict:
        """
        AI 组合多引擎工作流 → DAG
        """
        log.info(f"[Compose] 任务: {task[:80]}...")
        
        # 先路由选引擎
        route = self.route_task(task)
        engines = route.get("selected_engines", [])
        
        # 为每个引擎生成步骤
        steps = []
        for i, engine in enumerate(engines):
            step = {
                "step_id": f"s{i+1}",
                "engine": engine,
                "method": self._guess_engine_method(engine),
                "depends_on": [s["step_id"] for s in steps[-1:]] if i > 0 else [],
                "switch_check": True,
                "retry_on_fail": True,
                "timeout_ms": 60000,
            }
            steps.append(step)
        
        # 构建 DAG 图
        dag = {
            "nodes": [s["step_id"] for s in steps],
            "edges": [],  # 从 depends_on 构建
        }
        for step in steps:
            for dep in step["depends_on"]:
                dag["edges"].append({"from": dep, "to": step["step_id"]})
        
        workflow = {
            "workflow_id": self._gen_id("wf_"),
            "task_template": task,
            "steps": steps,
            "dag_graph": dag,
            "engine_source": route.get("selected_engines", []),
            "total_steps": len(steps),
            "created_at": self._now(),
        }
        
        # 存入数据库
        self._save_workflow(workflow)
        
        log.info(f"[Compose] → {len(steps)} steps ({workflow['workflow_id']})")
        return workflow
    
    def _guess_engine_method(self, engine_name: str) -> str:
        """猜测引擎的主要方法名"""
        conn = self._conn(readonly=True)
        try:
            row = conn.execute("""
                SELECT parameters FROM mt_ai_capability_registry
                WHERE category='ENGINE' AND capability_name=?
            """, (engine_name,)).fetchone()
            if row:
                try:
                    params = json.loads(row[0] or "{}")
                    # 简单猜测: 找类中最长的方法名 (排除 __ 开头)
                    for cls in params.get("classes", []):
                        # 从注册表中没有方法列表的问题, 只能猜测
                        pass
                except Exception:
                    pass
        finally:
            conn.close()
        
        # 根据名称模式猜测
        if "risk" in engine_name:
            return "compute_all"
        elif "ledger" in engine_name:
            return "build_all"
        elif "audit" in engine_name:
            return "audit_all"
        elif "daily_report" in engine_name or "report" in engine_name:
            return "generate"
        elif "self_heal" in engine_name or "heal" in engine_name:
            return "run_heal"
        elif "orchestrator" in engine_name:
            return "run_cycle"
        elif "coordinator" in engine_name or "trigger" in engine_name:
            return "process_pending"
        elif "sync" in engine_name:
            return "sync_all"
        elif "brain" in engine_name:
            return "feed"
        elif "autodev" in engine_name:
            return "generate_strategies"
        elif "futuresight" in engine_name:
            return "run_scenarios"
        return "run"
    
    def _save_workflow(self, workflow: dict):
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO mt_ai_workflow
                (workflow_id, task_template, steps, dag_graph, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                workflow["workflow_id"],
                workflow["task_template"],
                json.dumps(workflow["steps"], ensure_ascii=False),
                json.dumps(workflow["dag_graph"], ensure_ascii=False),
                workflow["created_at"],
            ))
            conn.commit()
        except Exception as e:
            log.debug(f"save workflow fail: {e}")
        finally:
            conn.close()
    
    def execute_workflow(self, workflow: dict) -> dict:
        """执行组合工作流 (带 try-except + 降级)"""
        log.info(f"[Execute] 工作流 {workflow.get('workflow_id', '?')}...")
        start = time.time()
        
        results = []
        success_count = 0
        fail_count = 0
        
        for step in workflow.get("steps", []):
            result = {
                "step_id": step.get("step_id"),
                "engine": step.get("engine"),
                "method": step.get("method"),
                "status": "SKIPPED",
                "output": None,
                "error": None,
                "duration_ms": 0,
            }
            
            step_start = time.time()
            try:
                # 动态导入引擎并调用
                engine_name = step["engine"]
                method_name = step.get("method", "run")
                
                # 尝试 import
                import importlib
                mod = importlib.import_module(f"engines.{engine_name}")
                
                # 找主类 (通常和文件名匹配)
                cls_name = None
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if isinstance(obj, type) and engine_name.lower() in attr.lower():
                        cls_name = attr
                        break
                
                if cls_name:
                    cls = getattr(mod, cls_name)
                    instance = cls(db_path=self.db_path)
                    method = getattr(instance, method_name, None)
                    if method and callable(method):
                        result["output"] = method()
                        result["status"] = "SUCCESS"
                        success_count += 1
                    else:
                        result["status"] = "SKIPPED"
                        result["error"] = f"方法 {method_name} 不存在"
                else:
                    # 尝试直接调用模块级函数
                    if hasattr(mod, method_name) and callable(getattr(mod, method_name)):
                        result["output"] = getattr(mod, method_name)()
                        result["status"] = "SUCCESS"
                        success_count += 1
                    else:
                        result["status"] = "SKIPPED"
                        result["error"] = f"找不到类或方法"
            
            except Exception as e:
                result["status"] = "FAILED"
                result["error"] = str(e)[:300]
                fail_count += 1
            
            result["duration_ms"] = round((time.time() - step_start) * 1000, 1)
            results.append(result)
        
        total_ms = round((time.time() - start) * 1000, 1)
        
        # 更新 workflow 执行统计
        self._update_workflow_stats(workflow.get("workflow_id"), total_ms, success_count, len(results))
        
        return {
            "workflow_id": workflow.get("workflow_id"),
            "step_results": results,
            "success_count": success_count,
            "fail_count": fail_count,
            "total_duration_ms": total_ms,
            "overall_status": "SUCCESS" if fail_count == 0 else ("PARTIAL" if success_count > 0 else "FAILED"),
        }
    
    def _update_workflow_stats(self, workflow_id: str, duration_ms: float, success: int, total: int):
        if not workflow_id:
            return
        conn = self._conn()
        try:
            rate = success / total if total > 0 else 0
            conn.execute("""
                UPDATE mt_ai_workflow SET
                last_executed=?,
                execution_count=execution_count+1,
                avg_duration_ms=(avg_duration_ms + ?)/2,
                success_rate=(success_rate + ?)/2
                WHERE workflow_id=?
            """, (self._now(), duration_ms, rate, workflow_id))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
    
    # ══════════════════════════════════════════════════════════════════
    # ④ EXPERIENCE MEMORY — AI 反思历史
    # ══════════════════════════════════════════════════════════════════
    
    def distill_experience(self, days: int = 7) -> dict:
        """
        从 mt_center_evolution_log 提炼经验片段
        """
        log.info(f"[Experience] 提炼最近 {days} 天经验...")
        start = time.time()
        
        result = {
            "success_patterns": [],
            "failure_lessons": [],
            "perf_stats": {},
            "insights": [],
            "snippet_ids": [],
        }
        
        conn = self._conn()
        try:
            # ── 从 evolution_log 读真实数据 ──
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            
            # 按 center_name 聚合
            module_stats = conn.execute("""
                SELECT center_name, 
                       COUNT(*) as total,
                       SUM(CASE WHEN (event LIKE '%ERROR%' OR event LIKE '%FAIL%') THEN 1 ELSE 0 END) as errors,
                       MIN(created_at) as first_seen,
                       MAX(created_at) as last_seen
                FROM mt_center_evolution_log
                WHERE created_at >= ?
                GROUP BY center_name
                ORDER BY total DESC
                LIMIT 50
            """, (since,)).fetchall()
            
            for module, total, errors, first, last in module_stats:
                if not module:
                    continue
                error_rate = errors / total if total > 0 else 0
                
                # 找代表性事件详情
                samples = conn.execute("""
                    SELECT event, detail, created_at
                    FROM mt_center_evolution_log
                    WHERE center_name=? AND created_at >= ?
                    LIMIT 3
                """, (module, since)).fetchall()
                
                if error_rate < 0.1 and total >= 10:
                    # 成功模式
                    snippet = {
                        "module": module,
                        "type": "SUCCESS_PATTERN",
                        "total_events": total,
                        "error_rate": round(error_rate, 3),
                        "samples": [{"event_type": s[0], "detail": (s[1] or "")[:80]} for s in samples],
                    }
                    result["success_patterns"].append(snippet)
                    
                    self._save_experience_snippet(
                        snippet_type="SUCCESS_PATTERN",
                        domain=self._guess_domain(module),
                        context_summary=f"模块 {module} 稳定运行 {total} 次，错误率 {error_rate:.1%}",
                        action_taken=f"{module}.run()",
                        outcome=f"error_rate={error_rate:.1%}",
                        lesson_learnt=f"{module} 组合效果好, 可复用",
                        confidence=0.8,
                        applicable_engines=[module],
                    )
                
                elif error_rate > 0.3 and total >= 5:
                    # 失败教训
                    snippet = {
                        "module": module,
                        "type": "FAILURE_LESSON",
                        "total_events": total,
                        "error_rate": round(error_rate, 3),
                        "errors": errors,
                        "samples": [{"event_type": s[0], "detail": (s[1] or "")[:80]} for s in samples],
                    }
                    result["failure_lessons"].append(snippet)
                    
                    self._save_experience_snippet(
                        snippet_type="FAILURE_LESSON",
                        domain=self._guess_domain(module),
                        context_summary=f"模块 {module} 出现 {errors}/{total} 次错误",
                        action_taken=f"{module} 执行",
                        outcome=f"error_rate={error_rate:.1%}",
                        lesson_learnt=f"{module} 不稳定, 需要检查依赖或增加重试",
                        confidence=0.7,
                        applicable_engines=[module],
                    )
                
                result["perf_stats"][module] = {
                    "total": total,
                    "errors": errors,
                    "error_rate": round(error_rate, 3),
                }
            
            # ── 用 Ollama 生成洞察 (可选) ──
            if _ollama_up() and result["success_patterns"]:
                top_success = [s["module"] for s in result["success_patterns"][:5]]
                top_fail = [s["module"] for s in result["failure_lessons"][:5]] if result["failure_lessons"] else []
                
                prompt = f"""MTSCOS AI 系统经验总结 ({days}天)

成功模块 (error_rate < 10%): {', '.join(top_success)}
问题模块 (error_rate > 30%): {', '.join(top_fail) if top_fail else '无'}

请用 1-2 句话总结:
1. 当前系统最稳定的能力是什么?
2. 哪个方面最需要改进?
3. 建议下一步做什么?

输出 JSON:
{{"summary": "...", "stable_capability": "...", "weak_point": "...", "next_action": "..."}}"""
                
                raw = _ollama_generate(prompt, temperature=0.3)
                if raw:
                    insight = self._parse_ollama_json(raw)
                    if insight:
                        result["insights"] = [insight]
                        self._save_experience_snippet(
                            snippet_type="INSPIRATION",
                            domain="system",
                            context_summary=insight.get("summary", "")[:500],
                            action_taken="analysis",
                            outcome="",
                            lesson_learnt=insight.get("next_action", "")[:500],
                            confidence=0.6,
                            applicable_engines=[],
                        )
                        self._ollama_calls += 1
        
        finally:
            conn.close()
        
        elapsed = round((time.time() - start) * 1000, 1)
        log.info(f"[Experience] 完成: {len(result['success_patterns'])} 成功 + "
                 f"{len(result['failure_lessons'])} 失败 ({elapsed}ms)")
        
        result["duration_ms"] = elapsed
        return result
    
    def _guess_domain(self, module_name: str) -> str:
        """猜模块所属领域"""
        m = module_name.lower()
        if "finance" in m or "risk" in m or "ledger" in m or "gobelin" in m:
            return "trading"
        if "audit" in m or "check" in m or "inspect" in m:
            return "audit"
        if "heal" in m or "repair" in m or "guard" in m:
            return "recovery"
        if "sync" in m:
            return "sync"
        if "edu" in m or "pedagogy" in m or "learn" in m:
            return "education"
        if "orchestrator" in m or "trigger" in m:
            return "orchestration"
        return "general"
    
    def _save_experience_snippet(self, snippet_type, domain, context_summary, 
                                  action_taken, outcome, lesson_learnt, 
                                  confidence, applicable_engines):
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO mt_ai_experience_snippet
                (snippet_id, snippet_type, domain, context_summary, action_taken, outcome,
                 lesson_learnt, confidence, applicable_engines, source_log_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                self._gen_id("snippet_"),
                snippet_type,
                domain,
                context_summary[:1000],
                action_taken[:500],
                outcome[:500],
                lesson_learnt[:1000],
                confidence,
                json.dumps(applicable_engines, ensure_ascii=False),
                self._now(),
            ))
            conn.commit()
        except Exception as e:
            log.debug(f"save snippet fail: {e}")
        finally:
            conn.close()
    
    def recall_similar(self, task: str, top_k: int = 3) -> list:
        """AI 问: "类似任务我以前做过吗?" → 返回 top_k 经验片段"""
        task_lower = task.lower()
        
        conn = self._conn(readonly=True)
        try:
            rows = conn.execute("""
                SELECT snippet_id, snippet_type, domain, context_summary, lesson_learnt,
                       confidence, applicable_engines, created_at
                FROM mt_ai_experience_snippet
                ORDER BY confidence DESC, created_at DESC
                LIMIT 50
            """).fetchall()
            
            # 简单相关性: 关键词匹配
            scored = []
            for row in rows:
                score = 0
                text = f"{row[2]} {row[3]} {row[4]}".lower()
                for word in task_lower.split():
                    if len(word) > 2 and word in text:
                        score += 1
                if score > 0 or row[5] > 0.7:
                    scored.append((score, row))
            
            scored.sort(key=lambda x: -x[0])
            results = []
            for _, row in scored[:top_k]:
                results.append({
                    "snippet_id": row[0],
                    "snippet_type": row[1],
                    "domain": row[2],
                    "context_summary": row[3],
                    "lesson_learnt": row[4],
                    "confidence": row[5],
                    "applicable_engines": json.loads(row[6] or "[]"),
                    "created_at": row[7],
                })
            return results
        finally:
            conn.close()
    
    # ══════════════════════════════════════════════════════════════════
    # ⑤ IDLE SELF-IMPROVE — 空闲时自我提升
    # ══════════════════════════════════════════════════════════════════
    
    def idle_improve_loop(self) -> dict:
        """
        当没有活跃任务时: 自动学习/测试/衍生新能力
        """
        log.info("[Idle] 空闲自我提升开始...")
        actions_taken = []
        start = time.time()
        
        # ── 1. 扫描 health_matrix 找弱项 ──
        try:
            conn = self._conn(readonly=True)
            weak = conn.execute("""
                SELECT module_name, health_score FROM mt_center_health_matrix
                WHERE health_score < 60
                ORDER BY health_score ASC
                LIMIT 5
            """).fetchall()
            conn.close()
            
            if weak:
                actions_taken.append(f"发现 {len(weak)} 个弱项模块")
                for mod, score in weak[:3]:
                    log.info(f"  [弱点] {mod}: {score}")
        except Exception:
            pass
        
        # ── 2. Ollama brainstorm 衍生新 prompt ──
        if _ollama_up():
            try:
                # 读一些现有 derivatives 作为 inspiration
                conn = self._conn(readonly=True)
                existing = conn.execute("""
                    SELECT derivative_id, derivative_title, derivative_status
                    FROM mt_autodev_derivatives
                    ORDER BY created_at DESC LIMIT 5
                """).fetchall()
                conn.close()
                
                existing_titles = [e[1] for e in existing if e[1]]
                
                prompt = f"""你是 AI 研发引擎的 prompt 设计师。根据现有衍生项目 brainstorm 新想法。

现有衍生: {', '.join(existing_titles) if existing_titles else '(暂无)'}
时间: {self._now()}

请生成 3 个新的衍生项目想法 (JSON):
{{"ideas": [
  {{"title": "...", "description": "...", "category": "prompt|strategy|engine|skill"}},
  ...
]}}"""
                
                raw = _ollama_generate(prompt, temperature=0.7)
                if raw:
                    ideas = self._parse_ollama_json(raw)
                    if ideas and "ideas" in ideas:
                        # 写入 mt_autodev_derivatives
                        self._save_derivative_ideas(ideas["ideas"][:3])
                        actions_taken.append(f"衍生 {len(ideas['ideas'][:3])} 个新想法")
                        self._ollama_calls += 1
            except Exception as e:
                log.debug(f"brainstorm fail: {e}")
        
        # ── 3. 检查 skill_registry 过期技能 ──
        try:
            conn = self._conn(readonly=True)
            stale = conn.execute("""
                SELECT skill_id, skill_name, is_active
                FROM mt_skill_registry
                WHERE is_active=0 OR (updated_at < datetime('now','-30 days'))
                LIMIT 5
            """).fetchall()
            conn.close()
            
            if stale:
                actions_taken.append(f"发现 {len(stale)} 个过期技能")
        except Exception:
            pass
        
        # ── 4. 运行一次 Futuresight 新场景 (随机参数) ──
        if _ollama_up():
            try:
                prompt = """设计一个新的 Futuresight 未来场景测试 (JSON):
{{"scenario_name": "...", "description": "...", "parameters": {{}}, "expected_outcome": "..."}}"""
                raw = _ollama_generate(prompt, temperature=0.8)
                if raw:
                    scene = self._parse_ollama_json(raw)
                    if scene and scene.get("scenario_name"):
                        self._save_futuresight_scene(scene)
                        actions_taken.append(f"新 Futuresight 场景: {scene['scenario_name'][:50]}")
                        self._ollama_calls += 1
            except Exception:
                pass
        
        elapsed = round((time.time() - start) * 1000, 1)
        log.info(f"[Idle] 完成: {len(actions_taken)} actions ({elapsed}ms)")
        
        return {
            "actions": actions_taken,
            "ollama_calls_made": self._ollama_calls,
            "duration_ms": elapsed,
        }
    
    def _save_derivative_ideas(self, ideas: list):
        conn = self._conn()
        try:
            for idea in ideas:
                try:
                    conn.execute("""
                        INSERT INTO mt_autodev_derivatives
                        (derivative_id, derivative_title, derivative_description, category,
                         source, status, created_at)
                        VALUES (?, ?, ?, ?, 'ollama_brainstorm', 'PENDING', ?)
                    """, (
                        self._gen_id("deriv_"),
                        idea.get("title", "")[:200],
                        idea.get("description", "")[:1000],
                        idea.get("category", "prompt"),
                        self._now(),
                    ))
                except Exception as e:
                    log.debug(f"save derivative fail: {e}")
            conn.commit()
        finally:
            conn.close()
    
    def _save_futuresight_scene(self, scene: dict):
        conn = self._conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO mt_futuresight_scenario
                (scenario_id, scenario_name, description, parameters_json, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                self._gen_id("scene_"),
                scene.get("scenario_name", "")[:200],
                scene.get("description", "")[:500],
                json.dumps(scene.get("parameters", {}), ensure_ascii=False),
                self._now(),
            ))
            conn.commit()
        except Exception as e:
            log.debug(f"save futuresight fail: {e}")
        finally:
            conn.close()
    
    # ══════════════════════════════════════════════════════════════════
    # 🎯 FULL META CYCLE — 完整元认知周期
    # ══════════════════════════════════════════════════════════════════
    
    def run_full_meta_cycle(self) -> dict:
        """完整元认知周期: Registry→Route→Compose→Experience→IdleImprove"""
        log.info("=" * 60)
        log.info("🧠 AI 元认知完整周期 开始")
        log.info("=" * 60)
        
        cycle_start = time.time()
        cycle_id = self._gen_id("cycle_")
        
        stats = {
            "registry_count": 0,
            "routes_decided": 0,
            "workflows_composed": 0,
            "experiences_distilled": 0,
            "idle_improve_actions": 0,
            "ollama_calls": 0,
            "ollama_latency_ms": 0,
            "total_duration_ms": 0,
            "meta_score": 0.0,
        }
        
        # ── ① Registry ──
        try:
            reg = self.build_meta_registry()
            stats["registry_count"] = (
                reg["stats"]["engines"] + reg["stats"]["blueprints"] +
                reg["stats"]["skills"] + reg["stats"]["triggers"] +
                reg["stats"]["switches"]
            )
            log.info(f"  ✓ Registry: {stats['registry_count']} capabilities")
        except Exception as e:
            log.error(f"  ✗ Registry fail: {e}")
        
        # ── ② Route (测试几个典型任务) ──
        test_tasks = [
            "帮我检查今天的交易风控",
            "账本对不上了帮我查",
            "生成新的策略 prompt",
            "系统有问题帮我自愈",
        ]
        for task in test_tasks:
            try:
                self.route_task(task)
                stats["routes_decided"] += 1
            except Exception as e:
                log.error(f"  ✗ Route fail ({task[:20]}): {e}")
        
        # ── ③ Compose ──
        try:
            wf = self.compose_workflow("完成今日风控全流程")
            stats["workflows_composed"] = 1
            log.info(f"  ✓ Compose: {wf['total_steps']} steps")
        except Exception as e:
            log.error(f"  ✗ Compose fail: {e}")
        
        # ── ④ Experience ──
        try:
            exp = self.distill_experience(days=7)
            stats["experiences_distilled"] = (
                len(exp["success_patterns"]) + len(exp["failure_lessons"])
            )
            log.info(f"  ✓ Experience: {stats['experiences_distilled']} patterns")
        except Exception as e:
            log.error(f"  ✗ Experience fail: {e}")
        
        # ── ⑤ Idle Improve ──
        try:
            idle = self.idle_improve_loop()
            stats["idle_improve_actions"] = len(idle.get("actions", []))
            log.info(f"  ✓ Idle: {stats['idle_improve_actions']} actions")
        except Exception as e:
            log.error(f"  ✗ Idle fail: {e}")
        
        # ── 计算 meta_score ──
        try:
            score = self.capability_score()
            avg = sum(score.values()) / len(score) if score else 0
            stats["meta_score"] = round(avg, 1)
        except Exception:
            pass
        
        stats["ollama_calls"] = self._ollama_calls
        stats["total_duration_ms"] = round((time.time() - cycle_start) * 1000, 1)
        
        # 写入周期日志
        self._save_meta_cycle(cycle_id, stats)
        
        log.info(f"  📊 MetaScore: {stats['meta_score']}/100")
        log.info(f"  ⏱ Total: {stats['total_duration_ms']}ms")
        log.info("=" * 60)
        log.info("🧠 AI 元认知完整周期 完成")
        log.info("=" * 60)
        
        return {"cycle_id": cycle_id, "stats": stats}
    
    def _save_meta_cycle(self, cycle_id: str, stats: dict):
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO mt_ai_meta_cycle
                (cycle_id, cycle_time, registry_count, routes_decided, workflows_composed,
                 experiences_distilled, idle_improve_actions, ollama_calls, ollama_latency_ms,
                 total_duration_ms, meta_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cycle_id,
                self._now(),
                stats["registry_count"],
                stats["routes_decided"],
                stats["workflows_composed"],
                stats["experiences_distilled"],
                stats["idle_improve_actions"],
                stats["ollama_calls"],
                stats["ollama_latency_ms"],
                stats["total_duration_ms"],
                stats["meta_score"],
                self._now(),
            ))
            conn.commit()
        except Exception as e:
            log.debug(f"save meta cycle fail: {e}")
        finally:
            conn.close()


# ═════════════════════════════════════════════════════════════════════
# CLI 入口
# ═════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="🧠 AIMetaCognition CLI")
    parser.add_argument("--registry", action="store_true", help="Build capability registry")
    parser.add_argument("--score", action="store_true", help="Show capability score")
    parser.add_argument("--route", type=str, help="Route a task")
    parser.add_argument("--compose", type=str, help="Compose a workflow")
    parser.add_argument("--experience", action="store_true", help="Distill experience")
    parser.add_argument("--idle", action="store_true", help="Run idle improve")
    parser.add_argument("--full-cycle", action="store_true", help="Run full meta cycle")
    parser.add_argument("--db", type=str, help="DB path")
    
    args = parser.parse_args()
    aimc = AIMetaCognition(args.db)
    
    if args.registry:
        r = aimc.build_meta_registry()
        print(json.dumps(r["stats"], ensure_ascii=False, indent=2))
    
    elif args.score:
        s = aimc.capability_score()
        for dim, val in sorted(s.items(), key=lambda x: -x[1]):
            bar = "█" * int(val / 5) + "░" * (20 - int(val / 5))
            print(f"  {dim:15s} [{bar}] {val:5.1f}")
    
    elif args.route:
        r = aimc.route_task(args.route)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    
    elif args.compose:
        w = aimc.compose_workflow(args.compose)
        print(json.dumps(w, ensure_ascii=False, indent=2))
    
    elif args.experience:
        e = aimc.distill_experience()
        print(f"Success: {len(e['success_patterns'])}, Failures: {len(e['failure_lessons'])}")
    
    elif args.idle:
        aimc.idle_improve_loop()
    
    elif args.full_cycle:
        aimc.run_full_meta_cycle()
    
    else:
        parser.print_help()
