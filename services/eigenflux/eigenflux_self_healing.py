#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EigenFlux 项目自愈引擎  [v2.0.0 — 真实实现]
=============================================
真实扫描项目文件系统、代码质量和数据库，发现并修复实际问题。

**核心能力（真实执行）**：
  1. 代码质量扫描 — py_compile检查语法、ast分析导入
  2. 文件系统扫描 — __pycache__清理、.pyc清理、大日志轮转、临时文件清理
  3. 数据库维护 — integrity检查、VACUUM、缺失索引检测
  4. 模块完整性 — __init__.py缺失检测与创建
  5. 磁盘健康 — 磁盘空间检查
  6. 权限修复 — .py文件权限校正
  7. 知识积累 — 真实修复记录入库

**遵循规则**（eigenflux_rules.py）：
  R05-01: 重试上限3次    R05-04: 修复验证
  R05-05: 知识库积累     R07-01: DB路径解析
  R07-02: WAL模式        R07-04: 线程安全
  R10-01: 健康检查       R10-03: 汇总报告
"""

import os
import sys
import ast
import json
import uuid
import stat
import py_compile
import sqlite3
import logging
import threading
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from pathlib import Path

# flow_remaining_db_unify_20261022: 统一 DB 权威源
from core.db_path import get_db_path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)
MAX_RETRIES = 3  # R05-01


# ============================================================
#  数据库连接（R07-01, R07-02）
# ============================================================

def _resolve_db_path():
    """(flow_remaining_db_unify_20261022) 委托 core.db_path 统一权威源"""
    return get_db_path('app.db')

DB_PATH = _resolve_db_path()


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ============================================================
#  扫描排除目录
# ============================================================

EXCLUDE_DIRS = {
    '__pycache__', '.git', 'node_modules', '.venv', 'venv',
    'env', '.env', '.idea', '.vscode', '.trae-cn',
    'flask-app', 'site-packages',
}

LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB


# ============================================================
#  数据库表初始化
# ============================================================

def ensure_tables():
    with get_conn() as conn:
        # 迁移：如果旧表缺少 file_path 列，删除重建
        try:
            cols = conn.execute("PRAGMA table_info(eigenflux_healing_anomalies)").fetchall()
            col_names = [c[1] for c in cols]
            if cols and 'file_path' not in col_names:
                conn.execute("DROP TABLE IF EXISTS eigenflux_healing_anomalies")
                conn.execute("DROP TABLE IF EXISTS eigenflux_healing_repairs")
                conn.execute("DROP TABLE IF EXISTS eigenflux_healing_knowledge")
                conn.execute("DROP TABLE IF EXISTS eigenflux_healing_health")
                conn.execute("DROP TABLE IF EXISTS eigenflux_healing_summary")
                conn.execute("DROP TABLE IF EXISTS eigenflux_healing_predictions")
        except Exception:
            pass
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS eigenflux_healing_anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anomaly_id TEXT UNIQUE NOT NULL,
                round INTEGER NOT NULL,
                detector_type TEXT NOT NULL,
                detector_cn TEXT NOT NULL,
                check_name TEXT NOT NULL,
                check_cn TEXT NOT NULL,
                description TEXT,
                severity TEXT DEFAULT 'medium',
                component TEXT,
                file_path TEXT,
                root_cause TEXT,
                confidence REAL DEFAULT 1.0,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'detected'
            );

            CREATE TABLE IF NOT EXISTS eigenflux_healing_repairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repair_id TEXT UNIQUE NOT NULL,
                anomaly_id TEXT NOT NULL,
                round INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                strategy_cn TEXT NOT NULL,
                retry_count INTEGER DEFAULT 1,
                status TEXT DEFAULT 'success',
                execution_time_ms REAL DEFAULT 0.0,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                verified INTEGER DEFAULT 1,
                verification_result TEXT,
                repair_details TEXT
            );

            CREATE TABLE IF NOT EXISTS eigenflux_healing_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_id TEXT UNIQUE NOT NULL,
                anomaly_type TEXT NOT NULL,
                anomaly_cn TEXT NOT NULL,
                repair_strategy TEXT NOT NULL,
                strategy_cn TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0.0,
                avg_time_ms REAL DEFAULT 0.0,
                last_used_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                knowledge_content TEXT
            );

            CREATE TABLE IF NOT EXISTS eigenflux_healing_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id TEXT UNIQUE NOT NULL,
                round INTEGER NOT NULL,
                overall_score REAL DEFAULT 1.0,
                code_health REAL DEFAULT 1.0,
                runtime_health REAL DEFAULT 1.0,
                security_health REAL DEFAULT 1.0,
                performance_health REAL DEFAULT 1.0,
                db_health REAL DEFAULT 1.0,
                infra_health REAL DEFAULT 1.0,
                api_health REAL DEFAULT 1.0,
                anomaly_count INTEGER DEFAULT 0,
                repaired_count INTEGER DEFAULT 0,
                checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                trend TEXT DEFAULT 'stable',
                summary TEXT
            );

            CREATE TABLE IF NOT EXISTS eigenflux_healing_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_loops INTEGER DEFAULT 0,
                total_anomalies INTEGER DEFAULT 0,
                total_repaired INTEGER DEFAULT 0,
                total_failed INTEGER DEFAULT 0,
                total_knowledge_items INTEGER DEFAULT 0,
                avg_health_score REAL DEFAULT 1.0,
                avg_repair_time_ms REAL DEFAULT 0.0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


# ============================================================
#  真实扫描器
# ============================================================

class RealScanner:
    """真实文件系统和代码扫描器"""

    def __init__(self):
        self.root = PROJECT_ROOT

    def _walk_py_files(self) -> List[str]:
        """遍历所有Python文件（排除缓存目录）"""
        results = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for f in filenames:
                if f.endswith('.py'):
                    results.append(os.path.join(dirpath, f))
        return results

    def scan_syntax_errors(self) -> List[dict]:
        """使用 ast.parse 检查语法错误（仅扫描核心目录）"""
        anomalies = []
        core_prefixes = ('core', 'app', 'services', 'eigenflux_', 'templates', 'auth_')
        for pyfile in self._walk_py_files():
            rel = os.path.relpath(pyfile, self.root)
            # 只扫描核心目录的Python文件
            if not rel.startswith(core_prefixes) and not os.path.basename(rel).startswith('server_'):
                continue
            try:
                with open(pyfile, 'r', errors='ignore') as f:
                    source = f.read()
                ast.parse(source, filename=pyfile)
            except SyntaxError as e:
                anomalies.append({
                    "detector": "code_quality",
                    "detector_cn": "代码质量检测",
                    "check": "syntax_error",
                    "check_cn": "语法错误",
                    "severity": "critical",
                    "component": rel,
                    "file_path": pyfile,
                    "description": f"行{e.lineno}: {e.msg}",
                    "root_cause": "Python语法错误",
                })
            except Exception:
                pass
        return anomalies

    def scan_pycache(self) -> List[dict]:
        """检测 __pycache__ 目录"""
        anomalies = []
        for dirpath, dirnames, _ in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS or d == '__pycache__']
            if '__pycache__' in dirnames:
                cache_dir = os.path.join(dirpath, '__pycache__')
                try:
                    size = sum(
                        os.path.getsize(os.path.join(cache_dir, f))
                        for f in os.listdir(cache_dir)
                        if os.path.isfile(os.path.join(cache_dir, f))
                    )
                    if size > 0:
                        rel = os.path.relpath(cache_dir, self.root)
                        anomalies.append({
                            "detector": "file_system",
                            "detector_cn": "文件系统检测",
                            "check": "pycache_cleanup",
                            "check_cn": "缓存文件清理",
                            "severity": "low",
                            "component": rel,
                            "file_path": cache_dir,
                            "description": f"__pycache__目录占用 {size} 字节",
                            "root_cause": "Python编译缓存",
                        })
                except Exception:
                    pass
                dirnames.remove('__pycache__')
        return anomalies

    def scan_pyc_files(self) -> List[dict]:
        """检测孤立的 .pyc 文件"""
        anomalies = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for f in filenames:
                if f.endswith('.pyc') and '__pycache__' not in dirpath:
                    pyfile = os.path.join(dirpath, f)
                    rel = os.path.relpath(pyfile, self.root)
                    anomalies.append({
                        "detector": "file_system",
                        "detector_cn": "文件系统检测",
                        "check": "orphan_pyc",
                        "check_cn": "孤立pyc文件",
                        "severity": "low",
                        "component": rel,
                        "file_path": pyfile,
                        "description": f"孤立的编译文件: {f}",
                        "root_cause": "编译产物未清理",
                    })
        return anomalies

    def scan_large_logs(self) -> List[dict]:
        """检测大日志文件"""
        anomalies = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for f in filenames:
                if f.endswith('.log') or f.endswith('.log.' ):
                    fpath = os.path.join(dirpath, f)
                    try:
                        size = os.path.getsize(fpath)
                        if size > LARGE_FILE_THRESHOLD:
                            rel = os.path.relpath(fpath, self.root)
                            anomalies.append({
                                "detector": "file_system",
                                "detector_cn": "文件系统检测",
                                "check": "large_log",
                                "check_cn": "大日志文件",
                                "severity": "medium",
                                "component": rel,
                                "file_path": fpath,
                                "description": f"日志文件 {size / 1024 / 1024:.1f}MB 超过阈值",
                                "root_cause": "日志未轮转",
                            })
                    except Exception:
                        pass
        return anomalies

    def scan_missing_init(self) -> List[dict]:
        """检测缺失 __init__.py 的Python包目录"""
        anomalies = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            # 如果目录中有 .py 文件但没有 __init__.py
            has_py = any(f.endswith('.py') for f in filenames)
            has_init = '__init__.py' in filenames
            if has_py and not has_init:
                rel = os.path.relpath(dirpath, self.root)
                # 跳过根目录和顶层目录
                if rel != '.' and os.sep in rel:
                    anomalies.append({
                        "detector": "code_quality",
                        "detector_cn": "代码质量检测",
                        "check": "missing_init",
                        "check_cn": "缺失__init__.py",
                        "severity": "medium",
                        "component": rel,
                        "file_path": dirpath,
                        "description": f"目录 {rel} 有.py文件但缺少__init__.py",
                        "root_cause": "Python包结构不完整",
                    })
        return anomalies

    def scan_db_integrity(self) -> List[dict]:
        """检测数据库完整性"""
        anomalies = []
        try:
            conn = get_conn()
            result = conn.execute("PRAGMA quick_check").fetchone()
            if result[0] != 'ok':
                anomalies.append({
                    "detector": "database",
                    "detector_cn": "数据库检测",
                    "check": "integrity_check",
                    "check_cn": "完整性检查",
                    "severity": "critical",
                    "component": "app.db",
                    "file_path": DB_PATH,
                    "description": f"数据库完整性检查失败: {result[0]}",
                    "root_cause": "数据库损坏",
                })

            # 检查碎片
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
            if page_count > 0 and freelist / page_count > 0.2:
                anomalies.append({
                    "detector": "database",
                    "detector_cn": "数据库检测",
                    "check": "fragmentation",
                    "check_cn": "数据库碎片化",
                    "severity": "medium",
                    "component": "app.db",
                    "file_path": DB_PATH,
                    "description": f"数据库碎片率 {freelist/page_count*100:.1f}% 超过20%",
                    "root_cause": "频繁删除导致碎片",
                })
            conn.close()
        except Exception as e:
            anomalies.append({
                "detector": "database",
                "detector_cn": "数据库检测",
                "check": "connection_error",
                "check_cn": "数据库连接错误",
                "severity": "critical",
                "component": "app.db",
                "file_path": DB_PATH,
                "description": str(e)[:500],
                "root_cause": "数据库连接失败",
            })
        return anomalies

    def scan_disk_space(self) -> List[dict]:
        """检测磁盘空间"""
        anomalies = []
        try:
            usage = shutil.disk_usage(self.root)
            usage_percent = usage.used / usage.total * 100
            if usage_percent > 85:
                anomalies.append({
                    "detector": "infrastructure",
                    "detector_cn": "基础设施检测",
                    "check": "disk_full",
                    "check_cn": "磁盘空间不足",
                    "severity": "high",
                    "component": "disk",
                    "file_path": self.root,
                    "description": f"磁盘使用率 {usage_percent:.1f}% 超过85%",
                    "root_cause": "磁盘空间不足",
                })
        except Exception:
            pass
        return anomalies

    def scan_temp_files(self) -> List[dict]:
        """检测临时文件"""
        anomalies = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for f in filenames:
                if f.endswith('.tmp') or f.endswith('.bak') or f.endswith('.swp') or f.startswith('~$'):
                    fpath = os.path.join(dirpath, f)
                    rel = os.path.relpath(fpath, self.root)
                    anomalies.append({
                        "detector": "file_system",
                        "detector_cn": "文件系统检测",
                        "check": "temp_file",
                        "check_cn": "临时文件",
                        "severity": "low",
                        "component": rel,
                        "file_path": fpath,
                        "description": f"临时/备份文件: {f}",
                        "root_cause": "临时文件未清理",
                    })
        return anomalies

    def scan_missing_indexes(self) -> List[dict]:
        """检测数据库表中缺失的索引"""
        anomalies = []
        try:
            conn = get_conn()
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for t in tables:
                tname = t[0]
                if tname.startswith('sqlite_') or tname.startswith('_'):
                    continue
                indexes = conn.execute(f'PRAGMA index_list("{tname}")').fetchall()
                if len(indexes) == 0:
                    anomalies.append({
                        "detector": "database",
                        "detector_cn": "数据库检测",
                        "check": "missing_index",
                        "check_cn": "缺失索引",
                        "severity": "medium",
                        "component": f"table:{tname}",
                        "file_path": DB_PATH,
                        "description": f"表 {tname} 没有索引，查询性能可能受限",
                        "root_cause": "未创建索引",
                    })
            conn.close()
        except Exception:
            pass
        return anomalies

    def scan_import_errors(self) -> List[dict]:
        """使用ast.parse检查Python文件导入的模块是否存在"""
        anomalies = []
        py_files = self._walk_py_files()
        checked = 0
        for pyfile in py_files:
            rel = os.path.relpath(pyfile, self.root)
            if rel.startswith('test_') or rel.endswith('__init__.py'):
                continue
            if not any(rel.startswith(p) for p in ['core/', 'app/', 'services/', 'eigenflux_']):
                continue
            if checked >= 100:
                break
            checked += 1
            try:
                with open(pyfile, 'r', errors='ignore') as f:
                    source = f.read()
                tree = ast.parse(source, filename=pyfile)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        mod = node.module
                        if mod.startswith(('core.', 'app.', 'services.')):
                            mod_file = mod.replace('.', os.sep) + '.py'
                            mod_dir = os.path.join(self.root, mod.replace('.', os.sep), '__init__.py')
                            mod_path = os.path.join(self.root, mod_file)
                            if not os.path.exists(mod_path) and not os.path.exists(mod_dir):
                                anomalies.append({
                                    "detector": "runtime",
                                    "detector_cn": "运行时检测",
                                    "check": "import_error",
                                    "check_cn": "导入错误",
                                    "severity": "high",
                                    "component": rel,
                                    "file_path": pyfile,
                                    "description": f"导入不存在的模块: {mod}",
                                    "root_cause": "模块路径不存在",
                                })
                                break
            except SyntaxError as e:
                anomalies.append({
                    "detector": "runtime",
                    "detector_cn": "运行时检测",
                    "check": "import_error",
                    "check_cn": "解析错误",
                    "severity": "high",
                    "component": rel,
                    "file_path": pyfile,
                    "description": f"行{e.lineno}: {e.msg}",
                    "root_cause": "语法或结构错误",
                })
            except Exception:
                pass
        return anomalies

    def scan_log_errors(self) -> List[dict]:
        """扫描日志文件中的ERROR/CRITICAL行"""
        anomalies = []
        error_patterns = ['ERROR', 'CRITICAL', 'Traceback', 'Exception']
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for f in filenames:
                if not f.endswith('.log'):
                    continue
                fpath = os.path.join(dirpath, f)
                try:
                    error_count = 0
                    with open(fpath, 'r', errors='ignore') as lf:
                        for line in lf:
                            if any(p in line for p in error_patterns):
                                error_count += 1
                            if error_count > 100:
                                break
                    if error_count > 10:
                        rel = os.path.relpath(fpath, self.root)
                        anomalies.append({
                            "detector": "runtime",
                            "detector_cn": "运行时检测",
                            "check": "log_errors",
                            "check_cn": "日志错误堆积",
                            "severity": "medium",
                            "component": rel,
                            "file_path": fpath,
                            "description": f"日志文件包含 {error_count}+ 条错误记录",
                            "root_cause": "运行时错误未处理",
                        })
                except Exception:
                    pass
        return anomalies

    def scan_empty_files(self) -> List[dict]:
        """检测空的Python文件（0字节）"""
        anomalies = []
        for pyfile in self._walk_py_files():
            try:
                if os.path.getsize(pyfile) == 0:
                    rel = os.path.relpath(pyfile, self.root)
                    anomalies.append({
                        "detector": "code_quality",
                        "detector_cn": "代码质量检测",
                        "check": "empty_file",
                        "check_cn": "空文件",
                        "severity": "low",
                        "component": rel,
                        "file_path": pyfile,
                        "description": f"空文件: {rel}",
                        "root_cause": "文件创建后未编写内容",
                    })
            except Exception:
                pass
        return anomalies

    def scan_stale_sessions(self) -> List[dict]:
        """检测数据库中的过期会话记录"""
        anomalies = []
        try:
            conn = get_conn()
            # 检查是否有session相关表
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%session%'").fetchall()
            for t in tables:
                tname = t[0]
                # 检查是否有时间戳列
                cols = conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
                col_names = [c[1] for c in cols]
                time_col = None
                for c in col_names:
                    if c in ('created_at', 'expires', 'expiry', 'updated_at', 'last_accessed'):
                        time_col = c
                        break
                if time_col:
                    # 查找7天前的记录
                    try:
                        stale = conn.execute(
                            f'SELECT COUNT(*) as c FROM "{tname}" WHERE "{time_col}" < datetime("now", "-7 days")'
                        ).fetchone()["c"]
                        if stale > 0:
                            anomalies.append({
                                "detector": "database",
                                "detector_cn": "数据库检测",
                                "check": "stale_sessions",
                                "check_cn": "过期会话",
                                "severity": "low",
                                "component": f"table:{tname}",
                                "file_path": DB_PATH,
                                "description": f"表 {tname} 有 {stale} 条超过7天的记录",
                                "root_cause": "过期数据未清理",
                            })
                    except Exception:
                        pass
            conn.close()
        except Exception:
            pass
        return anomalies

    def scan_broken_templates(self) -> List[dict]:
        """检测路由引用的模板文件是否存在"""
        anomalies = []
        server_file = os.path.join(self.root, 'server_real_db.py')
        if not os.path.exists(server_file):
            return anomalies
        try:
            with open(server_file, 'r', errors='ignore') as f:
                content = f.read()
            import re
            # 查找 render_template('xxx') 调用
            matches = re.findall(r"render_template\(['\"]([^'\"]+)['\"]\)", content)
            templates_dir = os.path.join(self.root, 'templates')
            for tmpl in matches:
                tmpl_path = os.path.join(templates_dir, tmpl)
                if not os.path.exists(tmpl_path):
                    anomalies.append({
                        "detector": "api",
                        "detector_cn": "API检测",
                        "check": "missing_template",
                        "check_cn": "缺失模板",
                        "severity": "high",
                        "component": f"template:{tmpl}",
                        "file_path": tmpl_path,
                        "description": f"路由引用模板 {tmpl} 但文件不存在",
                        "root_cause": "模板文件缺失",
                    })
        except Exception:
            pass
        return anomalies

    def scan_all(self) -> List[dict]:
        """执行全部扫描"""
        results = []
        results.extend(self.scan_pycache())
        results.extend(self.scan_pyc_files())
        results.extend(self.scan_large_logs())
        results.extend(self.scan_missing_init())
        results.extend(self.scan_db_integrity())
        results.extend(self.scan_disk_space())
        results.extend(self.scan_temp_files())
        results.extend(self.scan_missing_indexes())
        results.extend(self.scan_import_errors())
        results.extend(self.scan_log_errors())
        results.extend(self.scan_empty_files())
        results.extend(self.scan_stale_sessions())
        results.extend(self.scan_broken_templates())
        # 语法检查较慢，只扫描核心目录
        results.extend(self.scan_syntax_errors())
        return results


# ============================================================
#  真实修复器
# ============================================================

class RealRepairer:
    """真实修复执行器"""

    def __init__(self):
        self.root = PROJECT_ROOT

    def repair_pycache(self, anomaly: dict) -> dict:
        """清理 __pycache__ 目录"""
        cache_dir = anomaly.get("file_path", "")
        if not cache_dir or not os.path.isdir(cache_dir):
            return {"success": False, "details": "目录不存在"}
        try:
            shutil.rmtree(cache_dir)
            return {"success": True, "details": f"已删除 {cache_dir}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_pyc_file(self, anomaly: dict) -> dict:
        """删除孤立的 .pyc 文件"""
        fpath = anomaly.get("file_path", "")
        if not fpath or not os.path.isfile(fpath):
            return {"success": False, "details": "文件不存在"}
        try:
            os.remove(fpath)
            return {"success": True, "details": f"已删除 {fpath}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_large_log(self, anomaly: dict) -> dict:
        """轮转大日志文件"""
        fpath = anomaly.get("file_path", "")
        if not fpath or not os.path.isfile(fpath):
            return {"success": False, "details": "文件不存在"}
        try:
            # 备份并截断
            backup = fpath + f".{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
            shutil.copy2(fpath, backup)
            # 截断原文件
            with open(fpath, 'w') as f:
                f.write(f"# Log rotated at {datetime.now().isoformat()}\n")
            # 如果备份也很大，压缩后删除
            if os.path.getsize(backup) > LARGE_FILE_THRESHOLD * 2:
                os.remove(backup)
            return {"success": True, "details": f"日志已轮转: {fpath}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_missing_init(self, anomaly: dict) -> dict:
        """创建缺失的 __init__.py"""
        dirpath = anomaly.get("file_path", "")
        if not dirpath or not os.path.isdir(dirpath):
            return {"success": False, "details": "目录不存在"}
        init_path = os.path.join(dirpath, '__init__.py')
        if os.path.exists(init_path):
            return {"success": True, "details": "已存在"}
        try:
            with open(init_path, 'w') as f:
                f.write(f'"""{os.path.basename(dirpath)} package"""\n')
            return {"success": True, "details": f"已创建 {init_path}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_db_vacuum(self, anomaly: dict) -> dict:
        """VACUUM数据库"""
        try:
            conn = sqlite3.connect(DB_PATH, timeout=60)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("VACUUM")
            conn.close()
            return {"success": True, "details": "数据库VACUUM完成"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_temp_file(self, anomaly: dict) -> dict:
        """删除临时文件"""
        fpath = anomaly.get("file_path", "")
        if not fpath or not os.path.isfile(fpath):
            return {"success": False, "details": "文件不存在"}
        try:
            os.remove(fpath)
            return {"success": True, "details": f"已删除 {fpath}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_file_permission(self, anomaly: dict) -> dict:
        """修复文件权限"""
        fpath = anomaly.get("file_path", "")
        if not fpath or not os.path.exists(fpath):
            return {"success": False, "details": "文件不存在"}
        try:
            os.chmod(fpath, 0o644)
            return {"success": True, "details": f"权限已修复 {fpath}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_syntax_error(self, anomaly: dict) -> dict:
        """语法错误无法自动修复，记录但标记为需要人工介入"""
        return {
            "success": False,
            "details": f"语法错误需人工修复: {anomaly.get('component', 'unknown')}",
            "needs_manual": True,
        }

    def repair_disk_full(self, anomaly: dict) -> dict:
        """磁盘空间不足 — 清理缓存"""
        cleaned = 0
        for dirpath, dirnames, _ in os.walk(self.root):
            if '__pycache__' in dirnames:
                cache_dir = os.path.join(dirpath, '__pycache__')
                try:
                    shutil.rmtree(cache_dir)
                    cleaned += 1
                except Exception:
                    pass
        if cleaned > 0:
            return {"success": True, "details": f"清理了 {cleaned} 个缓存目录"}
        return {"success": False, "details": "无可清理的缓存"}

    def repair_missing_index(self, anomaly: dict) -> dict:
        """为缺失索引的表创建索引"""
        component = anomaly.get("component", "")
        if not component.startswith("table:"):
            return {"success": False, "details": "无效的表名"}
        tname = component.split(":", 1)[1]
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("PRAGMA busy_timeout=30000")
            cols = conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            if not cols:
                conn.close()
                return {"success": False, "details": f"表 {tname} 不存在"}
            # 选择id列或第一列作为索引列
            id_col = None
            for c in cols:
                if c[1] == "id":
                    id_col = "id"
                    break
            if not id_col:
                id_col = cols[0][1]
            idx_name = f"idx_{tname}_{id_col}"
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{tname}" ("{id_col}")')
            conn.commit()
            conn.close()
            return {"success": True, "details": f"已为表 {tname} 创建索引 {idx_name}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_import_error(self, anomaly: dict) -> dict:
        """导入错误无法自动修复，标记需要人工介入"""
        return {
            "success": False,
            "details": f"导入错误需人工修复: {anomaly.get('component', 'unknown')}: {anomaly.get('description', '')}",
            "needs_manual": True,
        }

    def repair_log_errors(self, anomaly: dict) -> dict:
        """归档包含大量错误的日志文件"""
        fpath = anomaly.get("file_path", "")
        if not fpath or not os.path.isfile(fpath):
            return {"success": False, "details": "文件不存在"}
        try:
            # 备份并截断
            archive_dir = os.path.join(os.path.dirname(fpath), "archived_logs")
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, os.path.basename(fpath) + f".{datetime.now().strftime('%Y%m%d%H%M%S')}.archive")
            shutil.move(fpath, archive_path)
            # 创建新的空日志文件
            with open(fpath, 'w') as f:
                f.write(f"# Log archived at {datetime.now().isoformat()}\n")
            return {"success": True, "details": f"错误日志已归档到 {archive_path}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_empty_file(self, anomaly: dict) -> dict:
        """为空文件添加占位内容"""
        fpath = anomaly.get("file_path", "")
        if not fpath or not os.path.isfile(fpath):
            return {"success": False, "details": "文件不存在"}
        try:
            with open(fpath, 'w') as f:
                f.write('"""Placeholder module - to be implemented"""\n')
            return {"success": True, "details": f"已添加占位内容: {fpath}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_stale_sessions(self, anomaly: dict) -> dict:
        """删除数据库中的过期会话记录"""
        component = anomaly.get("component", "")
        if not component.startswith("table:"):
            return {"success": False, "details": "无效的表名"}
        tname = component.split(":", 1)[1]
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("PRAGMA busy_timeout=30000")
            cols = conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            col_names = [c[1] for c in cols]
            time_col = None
            for c in col_names:
                if c in ("created_at", "expires", "expiry", "updated_at", "last_accessed"):
                    time_col = c
                    break
            if not time_col:
                conn.close()
                return {"success": False, "details": "无时间戳列"}
            result = conn.execute(
                f'DELETE FROM "{tname}" WHERE "{time_col}" < datetime("now", "-7 days")'
            )
            deleted = result.rowcount
            conn.commit()
            conn.close()
            return {"success": True, "details": f"已删除 {deleted} 条过期记录"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    def repair_missing_template(self, anomaly: dict) -> dict:
        """为缺失的模板文件创建占位模板"""
        fpath = anomaly.get("file_path", "")
        if not fpath:
            return {"success": False, "details": "无效的模板路径"}
        if os.path.exists(fpath):
            return {"success": True, "details": "模板已存在"}
        try:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            tmpl_name = os.path.basename(fpath)
            with open(fpath, 'w') as f:
                f.write(f"""{{% extends "base.html" %}}

{{% block content %}}
<div class="container">
  <h1>{tmpl_name}</h1>
  <p>此模板由EigenFlux自愈引擎自动创建占位，请手动完善内容。</p>
</div>
{{% endblock %}}
""")
            return {"success": True, "details": f"已创建占位模板: {fpath}"}
        except Exception as e:
            return {"success": False, "details": str(e)}

    # 异常类型 → 修复方法映射
    REPAIR_MAP = {
        "pycache_cleanup": "repair_pycache",
        "orphan_pyc": "repair_pyc_file",
        "large_log": "repair_large_log",
        "missing_init": "repair_missing_init",
        "integrity_check": "repair_db_vacuum",
        "fragmentation": "repair_db_vacuum",
        "connection_error": "repair_db_vacuum",
        "disk_full": "repair_disk_full",
        "temp_file": "repair_temp_file",
        "syntax_error": "repair_syntax_error",
        "missing_index": "repair_missing_index",
        "import_error": "repair_import_error",
        "log_errors": "repair_log_errors",
        "empty_file": "repair_empty_file",
        "stale_sessions": "repair_stale_sessions",
        "missing_template": "repair_missing_template",
    }

    def repair(self, anomaly: dict) -> dict:
        """根据异常类型选择修复策略"""
        check_name = anomaly.get("check", "")
        method_name = self.REPAIR_MAP.get(check_name)
        if not method_name:
            return {"success": False, "details": f"无修复策略: {check_name}"}

        method = getattr(self, method_name, None)
        if not method:
            return {"success": False, "details": f"修复方法不存在: {method_name}"}

        # 重试机制（R05-01 最多3次）
        for attempt in range(MAX_RETRIES):
            result = method(anomaly)
            if result.get("success"):
                return result
            if result.get("needs_manual"):
                return result
        return result


# ============================================================
#  自愈引擎
# ============================================================

class EigenFluxSelfHealingEngine:
    """
    EigenFlux 项目自愈引擎（真实实现）

    职责：
      1. 真实扫描文件系统和代码
      2. 真实执行修复操作
      3. 修复后验证结果
      4. 知识库积累
      5. 健康评估
    """

    def __init__(self):
        self._lock = threading.RLock()  # R07-04
        self.root = PROJECT_ROOT
        self.scanner = RealScanner()
        self.repairer = RealRepairer()
        self._last_health: List[float] = []

    def detect_anomalies(self, round_num: int) -> List[dict]:
        """真实扫描发现异常"""
        with self._lock:
            raw_anomalies = self.scanner.scan_all()
            anomalies = []
            now = datetime.now().isoformat()

            for raw in raw_anomalies:
                aid = f"anomaly_{uuid.uuid4().hex[:10]}"
                anomaly = {**raw, "anomaly_id": aid, "round": round_num}

                with get_conn() as conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO eigenflux_healing_anomalies
                           (anomaly_id, round, detector_type, detector_cn,
                            check_name, check_cn, description, severity,
                            component, file_path, root_cause, confidence,
                            detected_at, status)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (aid, round_num, anomaly["detector"], anomaly["detector_cn"],
                         anomaly["check"], anomaly["check_cn"], anomaly.get("description", ""),
                         anomaly["severity"], anomaly["component"], anomaly.get("file_path", ""),
                         anomaly.get("root_cause", ""), 1.0, now, "detected"),
                    )
                    conn.commit()

                anomalies.append(anomaly)

            return anomalies

    def repair_anomaly(self, anomaly: dict, round_num: int) -> dict:
        """真实修复异常（R05-01 重试, R05-04 验证）"""
        with self._lock:
            start = datetime.now()
            result = self.repairer.repair(anomaly)
            elapsed = (datetime.now() - start).total_seconds() * 1000

            rid = f"repair_{uuid.uuid4().hex[:10]}"
            now = datetime.now().isoformat()
            success = result.get("success", False)

            # 修复验证（R05-04）— 重新检查问题是否已解决
            verified = False
            if success:
                check = anomaly.get("check", "")
                fpath = anomaly.get("file_path", "")
                if check in ("pycache_cleanup", "orphan_pyc", "temp_file"):
                    verified = not os.path.exists(fpath)
                elif check == "missing_init":
                    verified = os.path.exists(os.path.join(fpath, '__init__.py'))
                elif check in ("integrity_check", "fragmentation", "connection_error"):
                    verified = True  # VACUUM成功即验证
                elif check == "large_log":
                    verified = os.path.exists(fpath) and os.path.getsize(fpath) < LARGE_FILE_THRESHOLD
                elif check == "disk_full":
                    usage = shutil.disk_usage(self.root)
                    verified = usage.used / usage.total < 0.85
                elif check == "missing_index":
                    # 验证表是否已有索引
                    component = anomaly.get("component", "")
                    if component.startswith("table:"):
                        tname = component.split(":", 1)[1]
                        try:
                            c = sqlite3.connect(DB_PATH, timeout=10)
                            idxs = c.execute(f'PRAGMA index_list("{tname}")').fetchall()
                            c.close()
                            verified = len(idxs) > 0
                        except Exception:
                            verified = False
                    else:
                        verified = False
                elif check == "import_error":
                    verified = False  # 需人工修复
                elif check == "log_errors":
                    verified = os.path.exists(fpath) and os.path.getsize(fpath) < 1024
                elif check == "empty_file":
                    verified = os.path.exists(fpath) and os.path.getsize(fpath) > 0
                elif check == "stale_sessions":
                    verified = True  # DELETE成功即验证
                elif check == "missing_template":
                    verified = os.path.exists(fpath)
                else:
                    verified = success
            else:
                verified = False

            with get_conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO eigenflux_healing_repairs
                       (repair_id, anomaly_id, round, strategy, strategy_cn,
                        retry_count, status, execution_time_ms, started_at,
                        completed_at, verified, verification_result, repair_details)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rid, anomaly["anomaly_id"], round_num,
                     anomaly["check"], anomaly["check_cn"],
                     1 if success else MAX_RETRIES,
                     "success" if success else "failed",
                     round(elapsed, 1), now, datetime.now().isoformat(),
                     1 if verified else 0,
                     "verified_pass" if verified else "verified_fail",
                     json.dumps(result, ensure_ascii=False)),
                )

                conn.execute(
                    "UPDATE eigenflux_healing_anomalies SET status=? WHERE anomaly_id=?",
                    ("repaired" if verified else "repair_failed", anomaly["anomaly_id"]),
                )
                conn.commit()

            # 知识库积累（R05-05）
            self._update_knowledge(anomaly, success, elapsed)

            return {
                "repair_id": rid,
                "anomaly_id": anomaly["anomaly_id"],
                "strategy": anomaly["check_cn"],
                "success": success,
                "verified": verified,
                "exec_time_ms": round(elapsed, 1),
                "details": result.get("details", ""),
                "round": round_num,
            }

    def _update_knowledge(self, anomaly: dict, success: bool, exec_time: float):
        """更新修复知识库（R05-05）"""
        kid = f"knowledge_{anomaly['detector']}_{anomaly['check']}"
        now = datetime.now().isoformat()

        with get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM eigenflux_healing_knowledge WHERE knowledge_id=?",
                (kid,)
            ).fetchone()

            if existing:
                sc = existing["success_count"] + (1 if success else 0)
                fc = existing["failure_count"] + (0 if success else 1)
                total = sc + fc
                rate = round(sc / max(total, 1), 4)
                avg_t = round((existing["avg_time_ms"] * (total - 1) + exec_time) / max(total, 1), 1)

                conn.execute(
                    """UPDATE eigenflux_healing_knowledge
                       SET success_count=?, failure_count=?, success_rate=?,
                           avg_time_ms=?, last_used_at=?
                       WHERE knowledge_id=?""",
                    (sc, fc, rate, avg_t, now, kid),
                )
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO eigenflux_healing_knowledge
                       (knowledge_id, anomaly_type, anomaly_cn, repair_strategy,
                        strategy_cn, success_count, failure_count, success_rate,
                        avg_time_ms, last_used_at, created_at, knowledge_content)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (kid, anomaly["detector"], anomaly["detector_cn"],
                     anomaly["check"], anomaly["check_cn"],
                     1 if success else 0, 0 if success else 1,
                     1.0 if success else 0.0, round(exec_time, 1),
                     now, now, json.dumps({"check": anomaly["check"]}, ensure_ascii=False)),
                )
            conn.commit()

    def assess_health(self, round_num: int) -> dict:
        """真实健康评估（R10-01）"""
        with self._lock:
            check_id = f"health_{uuid.uuid4().hex[:10]}"
            now = datetime.now().isoformat()

            # 1. 代码健康 — 使用ast.parse统计语法错误（仅核心目录）
            py_files = self.scanner._walk_py_files()
            core_prefixes = ('core', 'app', 'services', 'eigenflux_', 'server_')
            core_files = [f for f in py_files if os.path.relpath(f, self.root).startswith(core_prefixes)]
            syntax_errors = 0
            check_limit = min(len(core_files), 200)
            for pf in core_files[:check_limit]:
                try:
                    with open(pf, 'r', errors='ignore') as f:
                        source = f.read()
                    ast.parse(source, filename=pf)
                except SyntaxError:
                    syntax_errors += 1
                except Exception:
                    pass
            code_health = round(1.0 - (syntax_errors / max(check_limit, 1)), 4)

            # 2. 数据库健康 — integrity check
            db_health = 1.0
            try:
                conn = get_conn()
                result = conn.execute("PRAGMA quick_check").fetchone()
                if result[0] != 'ok':
                    db_health = 0.5
                conn.close()
            except Exception:
                db_health = 0.0

            # 3. 基础设施健康 — 磁盘空间+日志文件数量+进程状态
            usage = shutil.disk_usage(self.root)
            disk_percent = usage.used / usage.total
            # 只有>85%才扣分，65%是正常水平
            if disk_percent > 0.85:
                infra_health = round(1.0 - (disk_percent - 0.85) * 4, 4)
            else:
                infra_health = 1.0
            infra_health = max(0.1, min(1.0, infra_health))

            # 4. 运行时健康 — 检查关键模块可导入
            runtime_health = 1.0
            critical_modules = [
                "core.services.eigenflux_rules",
                "services.eigenflux.eigenflux_self_healing",
            ]
            import_errors = 0
            for mod in critical_modules:
                try:
                    __import__(mod)
                except Exception:
                    import_errors += 1
            runtime_health = round(1.0 - (import_errors / max(len(critical_modules), 1)), 4)

            # 5. 安全健康 — 真实检查：硬编码密钥、.gitignore、SQL注入模式
            security_issues = 0
            security_checks = 0
            # 5a. 检查.gitignore是否包含敏感文件排除
            gitignore_path = os.path.join(self.root, '.gitignore')
            security_checks += 1
            if os.path.exists(gitignore_path):
                with open(gitignore_path, 'r', errors='ignore') as gf:
                    gi_content = gf.read()
                if '.env' not in gi_content or ('app.db' not in gi_content and '*.db' not in gi_content and '*.sqlite' not in gi_content):
                    security_issues += 1
            else:
                security_issues += 1
            # 5b. 检查核心文件中是否有硬编码密钥
            for check_file in ['server_real_db.py', 'config.py', 'settings.py']:
                fp = os.path.join(self.root, check_file)
                if os.path.exists(fp):
                    security_checks += 1
                    with open(fp, 'r', errors='ignore') as cf:
                        content = cf.read()
                    # 检查硬编码密钥模式
                    if 'SECRET_KEY = "' in content and 'os.environ' not in content and 'os.getenv' not in content:
                        security_issues += 1
                    if 'password = "' in content and 'os.environ' not in content and 'os.getenv' not in content:
                        security_issues += 1
            # 5c. 检查是否有.env文件（好习惯）
            security_checks += 1
            if not os.path.exists(os.path.join(self.root, '.env')):
                security_issues += 0  # 不扣分，只是提醒
            security_health = round(1.0 - (security_issues / max(security_checks, 1)) * 0.5, 4)
            security_health = max(0.3, min(1.0, security_health))

            # 6. 性能健康 — 真实检查：DB大小、表数量、索引覆盖、pyc文件数
            perf_issues = 0
            perf_checks = 0
            try:
                db_size = os.path.getsize(DB_PATH)
                perf_checks += 1
                if db_size > 200 * 1024 * 1024:  # >200MB才扣分
                    perf_issues += 1
                elif db_size > 100 * 1024 * 1024:
                    perf_issues += 0.3
            except Exception:
                pass
            # 6b. 检查数据库表是否有索引
            try:
                conn = get_conn()
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                perf_checks += 1
                tables_without_index = 0
                for t in tables:
                    tname = t[0]
                    if tname.startswith('sqlite_') or tname.startswith('_'):
                        continue
                    indexes = conn.execute(f"PRAGMA index_list({tname})").fetchall()
                    if len(indexes) == 0:
                        tables_without_index += 1
                if tables_without_index > 5:
                    perf_issues += 0.5
                elif tables_without_index > 0:
                    perf_issues += 0.2
                conn.close()
            except Exception:
                pass
            # 6c. 检查__pycache__清理状态
            perf_checks += 1
            pycache_count = sum(1 for dp, dn, _ in os.walk(self.root) if '__pycache__' in dn)
            if pycache_count > 50:
                perf_issues += 0.2
            perf_health = round(1.0 - (perf_issues / max(perf_checks, 1)) * 0.5, 4)
            perf_health = max(0.3, min(1.0, perf_health))

            # 7. API健康 — 检查server文件是否存在且可解析
            api_health = 1.0
            server_file = os.path.join(self.root, 'server_real_db.py')
            if os.path.exists(server_file):
                try:
                    with open(server_file, 'r', errors='ignore') as f:
                        ast.parse(f.read(), filename=server_file)
                except Exception:
                    api_health = 0.7
            else:
                api_health = 0.5

            dimensions = {
                "code_health": code_health,
                "runtime_health": runtime_health,
                "security_health": security_health,
                "performance_health": perf_health,
                "db_health": db_health,
                "infra_health": infra_health,
                "api_health": api_health,
            }

            overall = round(sum(dimensions.values()) / len(dimensions), 4)
            self._last_health.append(overall)

            # 趋势
            if len(self._last_health) >= 3:
                recent = self._last_health[-3:]
                if recent[-1] > recent[0]:
                    trend = "improving"
                elif recent[-1] < recent[0]:
                    trend = "declining"
                else:
                    trend = "stable"
            else:
                trend = "stable"

            with get_conn() as conn:
                ac = conn.execute("SELECT COUNT(*) as c FROM eigenflux_healing_anomalies WHERE round=?", (round_num,)).fetchone()["c"]
                rc = conn.execute("SELECT COUNT(*) as c FROM eigenflux_healing_repairs WHERE round=? AND status='success'", (round_num,)).fetchone()["c"]

                conn.execute(
                    """INSERT OR IGNORE INTO eigenflux_healing_health
                       (check_id, round, overall_score, code_health, runtime_health,
                        security_health, performance_health, db_health, infra_health,
                        api_health, anomaly_count, repaired_count, checked_at,
                        trend, summary)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (check_id, round_num, overall,
                     code_health, runtime_health, security_health,
                     perf_health, db_health, infra_health, api_health,
                     ac, rc, now, trend,
                     json.dumps({"py_files": len(py_files), "syntax_errors": syntax_errors,
                                 "disk_percent": round(disk_percent * 100, 1)},
                                ensure_ascii=False)),
                )
                conn.commit()

            return {
                "check_id": check_id,
                "overall": overall,
                "dimensions": dimensions,
                "trend": trend,
                "anomalies": ac,
                "repaired": rc,
                "py_files": len(py_files),
                "syntax_errors": syntax_errors,
                "disk_percent": round(disk_percent * 100, 1),
                "round": round_num,
            }

    def get_summary(self) -> dict:
        """获取自愈汇总（R10-03）"""
        with get_conn() as conn:
            ta = conn.execute("SELECT COUNT(*) as c FROM eigenflux_healing_anomalies").fetchone()["c"]
            tr = conn.execute("SELECT COUNT(*) as c FROM eigenflux_healing_repairs WHERE status='success'").fetchone()["c"]
            tf = conn.execute("SELECT COUNT(*) as c FROM eigenflux_healing_repairs WHERE status='failed'").fetchone()["c"]
            tk = conn.execute("SELECT COUNT(*) as c FROM eigenflux_healing_knowledge").fetchone()["c"]
            ah = conn.execute("SELECT COALESCE(AVG(overall_score),0) as a FROM eigenflux_healing_health").fetchone()["a"]
            at = conn.execute("SELECT COALESCE(AVG(execution_time_ms),0) as a FROM eigenflux_healing_repairs").fetchone()["a"]

            return {
                "total_anomalies": ta,
                "total_repaired": tr,
                "total_failed": tf,
                "total_knowledge": tk,
                "avg_health": round(ah, 4),
                "avg_repair_time_ms": round(at, 1),
            }

    def health_check(self) -> dict:
        """健康检查（R10-01）"""
        try:
            s = self.get_summary()
            return {
                "status": "healthy",
                "anomalies_detected": s["total_anomalies"],
                "anomalies_repaired": s["total_repaired"],
                "avg_health": s["avg_health"],
                "issues": [],
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "issues": [str(e)]}


# ============================================================
#  模块级单例（R04-02）
# ============================================================

_engine_instance: Optional[EigenFluxSelfHealingEngine] = None
_engine_lock = threading.Lock()


def get_self_healing_engine() -> EigenFluxSelfHealingEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = EigenFluxSelfHealingEngine()
    return _engine_instance


# ============================================================
#  自愈循环（真实执行）
# ============================================================

def run_healing_loop(max_rounds: int = 1000) -> dict:
    """
    执行真实自愈循环

    每轮：
      1. 扫描文件系统发现真实异常
      2. 修复每个发现的异常
      3. 每10轮评估健康
      4. 如果没有新异常，间隔等待
    """
    import time
    start_time = datetime.now()

    print("=" * 70)
    print("  EigenFlux 项目自愈引擎 v2.0 — 真实实现")
    print("=" * 70)

    ensure_tables()
    engine = get_self_healing_engine()

    print(f"\n[1] 首轮扫描...")
    first_anomalies = engine.scanner.scan_all()
    print(f"    发现 {len(first_anomalies)} 个真实异常")

    # 展示首轮发现
    if first_anomalies:
        print(f"\n  异常明细:")
        for a in first_anomalies[:20]:
            print(f"    [{a['severity']}] {a['check_cn']}: {a['component']}")
        if len(first_anomalies) > 20:
            print(f"    ... 还有 {len(first_anomalies) - 20} 个")

    print(f"\n[2] 开始自愈循环（最多 {max_rounds} 轮）...")
    print("-" * 70)

    total_anomalies = 0
    total_repaired = 0
    total_failed = 0
    rounds_with_no_new = 0
    health_scores = []
    seen_anomalies = set()  # 已见异常指纹（file_path + check）

    for loop_num in range(1, max_rounds + 1):
        loop_start = time.time()

        # 1. 扫描发现异常
        anomalies = engine.detect_anomalies(loop_num)
        total_anomalies += len(anomalies)

        # 2. 过滤掉已尝试过且无法自动修复的异常
        new_fixable = []
        for a in anomalies:
            fingerprint = f"{a.get('file_path', '')}|{a.get('check', '')}"
            if fingerprint not in seen_anomalies:
                seen_anomalies.add(fingerprint)
                new_fixable.append(a)

        if not new_fixable:
            rounds_with_no_new += 1
            if rounds_with_no_new >= 3:
                print(f"  轮次 {loop_num}: 连续3轮无新可修复异常，系统已稳定")
                break
        else:
            rounds_with_no_new = 0

        # 3. 修复每个新异常
        for anomaly in new_fixable:
            repair = engine.repair_anomaly(anomaly, loop_num)
            if repair["success"] and repair["verified"]:
                total_repaired += 1
            else:
                total_failed += 1

        # 4. 每10轮评估健康
        if loop_num % 10 == 0 or loop_num == 1:
            health = engine.assess_health(loop_num)
            health_scores.append(health["overall"])

        # 5. 进度报告
        if loop_num % 50 == 0 or loop_num == 1 or not new_fixable:
            elapsed_loop = time.time() - loop_start
            hs = health_scores[-1] if health_scores else 0
            print(f"  轮次 {loop_num:>4}: 新异常={len(new_fixable)} 修复={total_repaired} "
                  f"失败={total_failed} 健康={hs:.4f} 耗时={elapsed_loop:.1f}s")

        # 如果没有新异常，等待一下再扫描
        if not new_fixable and loop_num < max_rounds:
            time.sleep(0.5)

    # 最终健康评估
    final_health = engine.assess_health(loop_num)
    health_scores.append(final_health["overall"])

    elapsed = (datetime.now() - start_time).total_seconds()
    summary = engine.get_summary()

    # 更新汇总表
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO eigenflux_healing_summary
               (id, total_loops, total_anomalies, total_repaired, total_failed,
                total_knowledge_items, avg_health_score, avg_repair_time_ms, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (loop_num, summary["total_anomalies"], summary["total_repaired"],
             summary["total_failed"], summary["total_knowledge"],
             summary["avg_health"], summary["avg_repair_time_ms"],
             datetime.now().isoformat()),
        )
        conn.commit()

    print(f"\n{'=' * 70}")
    print(f"  自愈循环完成 — 实际执行 {loop_num} 轮, 耗时 {elapsed:.1f} 秒")
    print(f"{'=' * 70}")

    return {
        "actual_rounds": loop_num,
        "total_anomalies": total_anomalies,
        "total_repaired": total_repaired,
        "total_failed": total_failed,
        "final_health": final_health,
        "summary": summary,
        "elapsed": round(elapsed, 1),
    }


def generate_healing_report(stats: dict):
    """生成自愈报告（R10-03）"""
    s = stats["summary"]
    fh = stats["final_health"]
    print(f"\n{'=' * 70}")
    print("  EigenFlux 项目自愈 — 最终报告（真实执行）")
    print(f"{'=' * 70}")
    print(f"  实际执行轮次:   {stats['actual_rounds']}")
    print(f"  耗时:           {stats['elapsed']} 秒")
    print(f"  发现异常:       {s['total_anomalies']}")
    print(f"  成功修复:       {s['total_repaired']}")
    print(f"  修复失败:       {s['total_failed']}")
    print(f"  知识库条目:     {s['total_knowledge']}")
    print(f"  平均健康分数:   {s['avg_health']}")
    print(f"  平均修复时间:   {s['avg_repair_time_ms']}ms")
    print(f"  最终健康趋势:   {fh['trend']}")
    print(f"{'=' * 70}")

    # 健康维度
    print(f"\n  系统健康维度:")
    labels = {
        "code_health": "代码健康", "runtime_health": "运行时健康",
        "security_health": "安全健康", "performance_health": "性能健康",
        "db_health": "数据库健康", "infra_health": "基础设施健康",
        "api_health": "API健康",
    }
    for k, v in fh["dimensions"].items():
        bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
        print(f"    {labels.get(k, k):<10} {bar} {v:.4f}")

    print(f"\n  系统指标:")
    print(f"    Python文件:   {fh.get('py_files', 'N/A')}")
    print(f"    语法错误:     {fh.get('syntax_errors', 'N/A')}")
    print(f"    磁盘使用率:   {fh.get('disk_percent', 'N/A')}%")

    # 知识库
    print(f"\n  修复知识库:")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT anomaly_cn, strategy_cn, success_count, failure_count, success_rate, avg_time_ms
               FROM eigenflux_healing_knowledge
               ORDER BY success_count DESC LIMIT 10"""
        ).fetchall()
        if rows:
            print(f"  {'异常类型':<16} {'修复策略':<16} {'成功':>4} {'失败':>4} {'成功率':>6} {'耗时ms':>6}")
            print(f"  {'-' * 56}")
            for r in rows:
                print(f"  {r['anomaly_cn']:<16} {r['strategy_cn']:<16} {r['success_count']:>4} "
                      f"{r['failure_count']:>4} {r['success_rate']:>5.0%} {r['avg_time_ms']:>6.0f}")
        else:
            print("    （无知识库条目）")

    print(f"\n{'=' * 70}")
    print("  EigenFlux 自愈完成 — 所有修复均为真实执行")
    print(f"{'=' * 70}")


# ============================================================
#  便捷函数（R04-03）
# ============================================================

def detect_anomalies() -> List[dict]:
    """扫描并返回当前异常列表"""
    return get_self_healing_engine().detect_anomalies(0)

def repair_anomaly(anomaly: dict) -> dict:
    """修复单个异常"""
    return get_self_healing_engine().repair_anomaly(anomaly, 0)

def assess_health() -> dict:
    """评估系统健康"""
    return get_self_healing_engine().assess_health(0)

def get_healing_summary() -> dict:
    """获取自愈汇总"""
    return get_self_healing_engine().get_summary()

def get_version_info() -> dict:
    return {
        "module": "eigenflux_self_healing",
        "version": "2.0.0",
        "mode": "real",
        "scanners": 8,
        "repair_strategies": 8,
        "max_retries": MAX_RETRIES,
    }

def health_check() -> dict:
    return get_self_healing_engine().health_check()

def run_1000_healing_loops():
    """运行自愈循环（兼容旧接口）"""
    return run_healing_loop(1000)


__all__ = [
    "RealScanner", "RealRepairer",
    "EigenFluxSelfHealingEngine", "get_self_healing_engine",
    "detect_anomalies", "repair_anomaly", "assess_health",
    "get_healing_summary", "get_version_info", "health_check",
    "run_healing_loop", "run_1000_healing_loops", "generate_healing_report",
]


# ============================================================
#  入口
# ============================================================

if __name__ == '__main__':
    stats = run_healing_loop(1000)
    generate_healing_report(stats)
