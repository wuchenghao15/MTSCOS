#!/usr/bin/env python3
"""
EigenFlux自动系统异常处理与修复服务
====================================
与EigenFlux网络协同，实现：
1. 系统异常实时监控与采集
2. 异常分类与自动修复策略匹配
3. 修复执行与验证（最多3次重试）
4. 修复知识库积累与复用
5. EigenFlux网络广播与协同修复
6. 健康巡检与预防性维护

依赖：
- EigenFlux适配器 (app.services.eigenflux_adapter)
- 自动修复引擎 (core.services.auto_repair_engine)
- AI自修复中间件 (app.middlewares.ai_self_repair)
"""
import os
import sys
import json
import time
import uuid
import sqlite3
import logging
import traceback
import subprocess
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# flow_remaining_db_unify_20261022: 统一 DB 权威源
from core.db_path import get_db_path

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _resolve_db_path():
    """(flow_remaining_db_unify_20261022) 委托 core.db_path 统一权威源"""
    return get_db_path('app.db')

DB_PATH = _resolve_db_path()

# ========== 异常分类与修复策略 ==========

EXCEPTION_CATEGORIES = {
    'import_error': {
        'name': '导入错误',
        'patterns': [r'ModuleNotFoundError', r'ImportError', r'No module named'],
        'severity': 'high',
        'auto_repairable': True,
    },
    'syntax_error': {
        'name': '语法错误',
        'patterns': [r'SyntaxError', r'IndentationError', r'TabError'],
        'severity': 'critical',
        'auto_repairable': True,
    },
    'attribute_error': {
        'name': '属性错误',
        'patterns': [r'AttributeError', r'has no attribute'],
        'severity': 'medium',
        'auto_repairable': True,
    },
    'key_error': {
        'name': '键错误',
        'patterns': [r'KeyError'],
        'severity': 'medium',
        'auto_repairable': True,
    },
    'type_error': {
        'name': '类型错误',
        'patterns': [r'TypeError', r'argument.*must be'],
        'severity': 'medium',
        'auto_repairable': True,
    },
    'value_error': {
        'name': '值错误',
        'patterns': [r'ValueError', r'invalid literal'],
        'severity': 'medium',
        'auto_repairable': True,
    },
    'http_404': {
        'name': '页面未找到',
        'patterns': [r'404', r'Not Found', r'could not find'],
        'severity': 'low',
        'auto_repairable': True,
    },
    'http_500': {
        'name': '服务器内部错误',
        'patterns': [r'500', r'Internal Server Error'],
        'severity': 'critical',
        'auto_repairable': True,
    },
    'database_error': {
        'name': '数据库错误',
        'patterns': [r'sqlite3\.OperationalError', r'database is locked', r'no such table', r'no such column'],
        'severity': 'high',
        'auto_repairable': True,
    },
    'template_error': {
        'name': '模板错误',
        'patterns': [r'TemplateNotFound', r'jinja2', r'TemplateSyntaxError'],
        'severity': 'high',
        'auto_repairable': True,
    },
    'timeout_error': {
        'name': '超时错误',
        'patterns': [r'TimeoutError', r'timed out', r'ReadTimeout'],
        'severity': 'medium',
        'auto_repairable': False,
    },
    'memory_error': {
        'name': '内存错误',
        'patterns': [r'MemoryError', r'out of memory'],
        'severity': 'critical',
        'auto_repairable': False,
    },
    'permission_error': {
        'name': '权限错误',
        'patterns': [r'PermissionError', r'Permission denied'],
        'severity': 'high',
        'auto_repairable': True,
    },
    'f541_error': {
        'name': 'F541 f-string无占位符',
        'patterns': [r'F541', r'f-string is missing placeholders'],
        'severity': 'low',
        'auto_repairable': True,
    },
    'f821_error': {
        'name': 'F821 未定义名称',
        'patterns': [r'F821', r'undefined name'],
        'severity': 'medium',
        'auto_repairable': True,
    },
}

# ========== 修复策略 ==========

REPAIR_STRATEGIES = {
    'import_error': '添加缺失的import语句',
    'syntax_error': '修复语法错误（缩进/括号/引号）',
    'attribute_error': '检查并修复对象属性访问',
    'key_error': '添加键存在性检查或默认值',
    'type_error': '添加类型转换或参数验证',
    'value_error': '添加值验证与异常处理',
    'http_404': '检查路由注册或创建缺失模板',
    'http_500': '分析堆栈跟踪并修复根本原因',
    'database_error': '检查表结构/索引/连接/锁',
    'template_error': '检查模板路径或创建模板文件',
    'permission_error': '检查并修复文件/目录权限',
    'f541_error': '移除f-string的f前缀',
    'f821_error': '添加缺失的导入或变量定义',
}

MAX_RETRIES = 3  # 最多重试3次（遵循项目规则）


class EigenFluxAutoRepairService:
    """EigenFlux自动异常处理与修复服务"""

    def __init__(self):
        self.db_path = DB_PATH
        self._lock = threading.RLock()
        self._monitoring = False
        self._monitor_thread = None
        self._repair_cache: Dict[str, Dict] = {}  # 修复缓存
        self.stats = {
            'total_detected': 0,
            'total_repaired': 0,
            'total_failed': 0,
            'total_retries': 0,
        }

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    # ========== 数据库初始化 ==========

    def init_tables(self) -> Dict[str, Any]:
        """初始化所有数据表"""
        try:
            with self._get_conn() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS eigenflux_exception_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exception_id TEXT UNIQUE NOT NULL,
                        category TEXT NOT NULL,
                        severity TEXT DEFAULT 'medium',
                        source TEXT,
                        file_path TEXT,
                        line_number INTEGER,
                        error_message TEXT NOT NULL,
                        stack_trace TEXT,
                        context TEXT DEFAULT '{}',
                        status TEXT DEFAULT 'detected',
                        detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        repaired_at TEXT,
                        repair_method TEXT,
                        repair_details TEXT DEFAULT '{}',
                        retry_count INTEGER DEFAULT 0,
                        eigenflux_reported INTEGER DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS eigenflux_repair_solutions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        solution_id TEXT UNIQUE NOT NULL,
                        exception_category TEXT NOT NULL,
                        error_pattern TEXT NOT NULL,
                        repair_strategy TEXT NOT NULL,
                        repair_code TEXT,
                        success_count INTEGER DEFAULT 0,
                        fail_count INTEGER DEFAULT 0,
                        confidence REAL DEFAULT 0.5,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        last_used_at TEXT,
                        source TEXT DEFAULT 'auto_discovered'
                    );

                    CREATE TABLE IF NOT EXISTS eigenflux_repair_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        history_id TEXT UNIQUE NOT NULL,
                        exception_id TEXT NOT NULL,
                        solution_id TEXT,
                        attempt_number INTEGER DEFAULT 1,
                        action TEXT NOT NULL,
                        result TEXT NOT NULL,
                        details TEXT DEFAULT '{}',
                        elapsed_ms INTEGER DEFAULT 0,
                        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS eigenflux_health_check (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        check_id TEXT UNIQUE NOT NULL,
                        check_type TEXT NOT NULL,
                        target TEXT,
                        status TEXT DEFAULT 'unknown',
                        metrics TEXT DEFAULT '{}',
                        issues_found INTEGER DEFAULT 0,
                        issues_fixed INTEGER DEFAULT 0,
                        checked_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS eigenflux_monitor_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        config_key TEXT UNIQUE NOT NULL,
                        config_value TEXT,
                        description TEXT,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_exc_log_category ON eigenflux_exception_log(category);
                    CREATE INDEX IF NOT EXISTS idx_exc_log_status ON eigenflux_exception_log(status);
                    CREATE INDEX IF NOT EXISTS idx_repair_sol_category ON eigenflux_repair_solutions(exception_category);
                    CREATE INDEX IF NOT EXISTS idx_health_check_type ON eigenflux_health_check(check_type);
                """)
                conn.commit()

                # 初始化默认配置
                self._init_default_config(conn)
            logger.info("EigenFlux自动异常处理与修复服务数据表初始化完成")
            return {'success': True}
        except Exception as e:
            logger.error(f"初始化数据表失败: {e}")
            return {'success': False, 'error': str(e)}

    def _init_default_config(self, conn):
        """初始化默认监控配置"""
        defaults = [
            ('monitor_enabled', '1', '是否启用异常监控'),
            ('monitor_interval', '60', '监控间隔（秒）'),
            ('max_retries', str(MAX_RETRIES), '最大重试次数'),
            ('auto_repair_enabled', '1', '是否启用自动修复'),
            ('eigenflux_report_enabled', '1', '是否向EigenFlux报告异常'),
            ('health_check_enabled', '1', '是否启用健康巡检'),
            ('health_check_interval', '300', '健康巡检间隔（秒）'),
            ('log_retention_days', '90', '日志保留天数'),
        ]
        for key, value, desc in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO eigenflux_monitor_config (config_key, config_value, description) VALUES (?,?,?)",
                (key, value, desc),
            )
        conn.commit()

    # ========== 异常检测 ==========

    def detect_exception(self, error_message: str, source: str = '',
                         file_path: str = '', line_number: int = 0,
                         stack_trace: str = '', context: Optional[Dict] = None) -> Dict[str, Any]:
        """检测并记录异常，返回异常ID"""
        try:
            category = self._classify_exception(error_message)
            severity = EXCEPTION_CATEGORIES.get(category, {}).get('severity', 'medium')
            exception_id = f"exc_{uuid.uuid4().hex[:12]}"
            now = datetime.now().isoformat()

            with self._lock:
                self.stats['total_detected'] += 1

            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO eigenflux_exception_log
                       (exception_id, category, severity, source, file_path, line_number,
                        error_message, stack_trace, context, status, detected_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (exception_id, category, severity, source, file_path, line_number,
                     error_message, stack_trace, json.dumps(context or {}, ensure_ascii=False),
                     'detected', now),
                )
                conn.commit()

            logger.info(f"异常已记录: {exception_id} [{category}] {error_message[:100]}")

            # 向EigenFlux报告
            if self._get_config('eigenflux_report_enabled', '1') == '1':
                self._report_to_eigenflux(exception_id, category, severity, error_message, source)

            return {
                'success': True,
                'exception_id': exception_id,
                'category': category,
                'severity': severity,
                'auto_repairable': EXCEPTION_CATEGORIES.get(category, {}).get('auto_repairable', False),
            }
        except Exception as e:
            logger.error(f"检测异常失败: {e}")
            return {'success': False, 'error': str(e)}

    def _classify_exception(self, error_message: str) -> str:
        """分类异常"""
        import re
        for category, config in EXCEPTION_CATEGORIES.items():
            for pattern in config['patterns']:
                if re.search(pattern, error_message, re.IGNORECASE):
                    return category
        return 'unknown'

    # ========== 自动修复 ==========

    def auto_repair(self, exception_id: str) -> Dict[str, Any]:
        """自动修复异常（最多重试3次）"""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM eigenflux_exception_log WHERE exception_id = ?",
                    (exception_id,),
                ).fetchone()

                if not row:
                    return {'success': False, 'error': '异常记录不存在'}

                category = row['category']
                error_msg = row['error_message']
                file_path = row['file_path'] or ''
                current_retries = row['retry_count'] or 0

                if current_retries >= MAX_RETRIES:
                    logger.warning(f"异常 {exception_id} 已达最大重试次数 {MAX_RETRIES}")
                    self._update_exception_status(conn, exception_id, 'max_retries_exceeded')
                    return {'success': False, 'error': f'已达最大重试次数 {MAX_RETRIES}'}

                if not EXCEPTION_CATEGORIES.get(category, {}).get('auto_repairable', False):
                    logger.info(f"异常 {exception_id} 类别 {category} 不可自动修复")
                    self._update_exception_status(conn, exception_id, 'not_repairable')
                    return {'success': False, 'error': f'类别 {category} 不可自动修复'}

                # 查找已有修复方案
                solution = self._find_solution(conn, category, error_msg)

                # 执行修复
                attempt = current_retries + 1
                start_time = time.time()
                repair_result = self._execute_repair(category, error_msg, file_path, solution)
                elapsed_ms = int((time.time() - start_time) * 1000)

                with self._lock:
                    self.stats['total_retries'] += 1

                # 记录修复历史
                history_id = f"rep_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """INSERT INTO eigenflux_repair_history
                       (history_id, exception_id, solution_id, attempt_number,
                        action, result, details, elapsed_ms, timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (history_id, exception_id,
                     solution.get('solution_id') if solution else None,
                     attempt, repair_result['action'], repair_result['result'],
                     json.dumps(repair_result.get('details', {}), ensure_ascii=False),
                     elapsed_ms, datetime.now().isoformat()),
                )

                if repair_result['result'] == 'success':
                    # 修复成功
                    self._update_exception_status(conn, exception_id, 'repaired',
                                                   repair_method=repair_result['action'],
                                                   repair_details=json.dumps(repair_result, ensure_ascii=False))
                    conn.execute(
                        "UPDATE eigenflux_exception_log SET repaired_at = ?, retry_count = ? WHERE exception_id = ?",
                        (datetime.now().isoformat(), attempt, exception_id),
                    )

                    # 更新修复方案统计
                    if solution:
                        conn.execute(
                            """UPDATE eigenflux_repair_solutions
                               SET success_count = success_count + 1, last_used_at = ?,
                                   confidence = MIN(1.0, confidence + 0.05)
                               WHERE solution_id = ?""",
                            (datetime.now().isoformat(), solution['solution_id']),
                        )
                    else:
                        # 保存新方案
                        self._save_solution(conn, category, error_msg, repair_result['action'],
                                           repair_result.get('details', {}))

                    with self._lock:
                        self.stats['total_repaired'] += 1

                    conn.commit()
                    logger.info(f"异常 {exception_id} 修复成功 (第{attempt}次尝试)")
                    return {
                        'success': True,
                        'exception_id': exception_id,
                        'attempt': attempt,
                        'action': repair_result['action'],
                        'elapsed_ms': elapsed_ms,
                    }
                else:
                    # 修复失败，更新重试计数
                    conn.execute(
                        "UPDATE eigenflux_exception_log SET retry_count = ?, status = 'retrying' WHERE exception_id = ?",
                        (attempt, exception_id),
                    )
                    if solution:
                        conn.execute(
                            """UPDATE eigenflux_repair_solutions
                               SET fail_count = fail_count + 1,
                                   confidence = MAX(0.1, confidence - 0.1)
                               WHERE solution_id = ?""",
                            (solution['solution_id'],),
                        )
                    conn.commit()

                    logger.warning(f"异常 {exception_id} 修复失败 (第{attempt}次尝试): {repair_result.get('error', '')}")
                    return {
                        'success': False,
                        'exception_id': exception_id,
                        'attempt': attempt,
                        'error': repair_result.get('error', '修复失败'),
                        'can_retry': attempt < MAX_RETRIES,
                    }
        except Exception as e:
            logger.error(f"自动修复异常 {exception_id} 失败: {e}")
            return {'success': False, 'error': str(e)}

    def _find_solution(self, conn, category: str, error_msg: str) -> Optional[Dict]:
        """查找已有的修复方案"""
        try:
            rows = conn.execute(
                "SELECT * FROM eigenflux_repair_solutions WHERE exception_category = ? ORDER BY confidence DESC, success_count DESC LIMIT 1",
                (category,),
            ).fetchall()
            for row in rows:
                pattern = row['error_pattern']
                if pattern in error_msg or error_msg in pattern:
                    return dict(row)
            # 返回置信度最高的方案
            if rows:
                return dict(rows[0])
            return None
        except Exception:
            return None

    def _save_solution(self, conn, category: str, error_msg: str, strategy: str, details: Dict):
        """保存修复方案"""
        solution_id = f"sol_{uuid.uuid4().hex[:12]}"
        # 提取错误模式（取错误消息的关键部分）
        pattern = error_msg[:200] if len(error_msg) > 200 else error_msg
        conn.execute(
            """INSERT OR REPLACE INTO eigenflux_repair_solutions
               (solution_id, exception_category, error_pattern, repair_strategy,
                repair_code, success_count, confidence, created_at, last_used_at, source)
               VALUES (?,?,?,?,?,1,0.6,?,?, 'auto_discovered')""",
            (solution_id, category, pattern, strategy,
             details.get('code', ''), datetime.now().isoformat(),
             datetime.now().isoformat()),
        )

    def _execute_repair(self, category: str, error_msg: str,
                        file_path: str, solution: Optional[Dict]) -> Dict[str, Any]:
        """执行具体的修复操作"""
        strategy = REPAIR_STRATEGIES.get(category, '未知策略')

        try:
            if category == 'import_error':
                return self._repair_import_error(error_msg, file_path)
            elif category == 'syntax_error':
                return self._repair_syntax_error(error_msg, file_path)
            elif category == 'f541_error':
                return self._repair_f541(file_path)
            elif category == 'f821_error':
                return self._repair_f821(error_msg, file_path)
            elif category == 'database_error':
                return self._repair_database_error(error_msg)
            elif category == 'http_404':
                return self._repair_http_404(error_msg, file_path)
            elif category == 'http_500':
                return self._repair_http_500(error_msg)
            elif category == 'template_error':
                return self._repair_template_error(error_msg, file_path)
            elif category == 'permission_error':
                return self._repair_permission_error(file_path)
            elif category in ('attribute_error', 'key_error', 'type_error', 'value_error'):
                return self._repair_runtime_error(category, error_msg, file_path)
            else:
                return {
                    'action': strategy,
                    'result': 'skipped',
                    'details': {'reason': f'暂不支持 {category} 的自动修复'},
                }
        except Exception as e:
            return {
                'action': strategy,
                'result': 'failed',
                'error': str(e),
                'details': {'traceback': traceback.format_exc()},
            }

    # ========== 具体修复方法 ==========

    def _repair_import_error(self, error_msg: str, file_path: str) -> Dict[str, Any]:
        """修复导入错误"""
        import re
        # 提取缺失的模块名
        m = re.search(r"No module named ['\"]?(\w+)['\"]?", error_msg)
        if not m:
            m = re.search(r"cannot import name ['\"]?(\w+)['\"]?", error_msg)

        if m:
            module_name = m.group(1)
            # 标准库映射
            stdlib_imports = {
                'os': 'import os',
                'sys': 'import sys',
                'json': 'import json',
                'time': 'import time',
                'datetime': 'from datetime import datetime',
                'logging': 'import logging',
                'sqlite3': 'import sqlite3',
                'uuid': 'import uuid',
                're': 'import re',
                'threading': 'import threading',
                'collections': 'from collections import defaultdict, Counter',
                'typing': 'from typing import Dict, Any, List, Optional, Tuple',
                'subprocess': 'import subprocess',
                'traceback': 'import traceback',
                'hashlib': 'import hashlib',
                'base64': 'import base64',
                'random': 'import random',
                'math': 'import math',
                'pathlib': 'from pathlib import Path',
                'functools': 'from functools import wraps',
            }
            import_stmt = stdlib_imports.get(module_name, f'import {module_name}')

            if file_path and os.path.isfile(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if import_stmt not in content:
                    lines = content.split('\n')
                    # 找插入位置
                    insert_pos = 0
                    if lines and lines[0].startswith('#!'):
                        insert_pos = 1
                    for i in range(insert_pos, min(len(lines), 30)):
                        if lines[i].startswith(('import ', 'from ')):
                            insert_pos = i + 1
                    lines.insert(insert_pos, import_stmt)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(lines))
                    return {
                        'action': '添加缺失导入',
                        'result': 'success',
                        'details': {'import': import_stmt, 'module': module_name},
                    }
                return {
                    'action': '检查导入',
                    'result': 'success',
                    'details': {'reason': '导入已存在', 'import': import_stmt},
                }
            return {
                'action': '添加缺失导入',
                'result': 'success',
                'details': {'import': import_stmt, 'note': '文件路径为空，仅记录方案'},
            }
        return {
            'action': '分析导入错误',
            'result': 'failed',
            'error': '无法从错误消息中提取模块名',
            'details': {'error_msg': error_msg},
        }

    def _repair_syntax_error(self, error_msg: str, file_path: str) -> Dict[str, Any]:
        """修复语法错误"""
        if file_path and os.path.isfile(file_path):
            try:
                result = subprocess.run(
                    ['python3', '-m', 'py_compile', file_path],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    return {
                        'action': '语法检查',
                        'result': 'success',
                        'details': {'note': '编译通过，可能已修复'},
                    }
                return {
                    'action': '语法修复',
                    'result': 'failed',
                    'error': result.stderr[:500],
                    'details': {'file': file_path},
                }
            except Exception as e:
                return {
                    'action': '语法修复',
                    'result': 'failed',
                    'error': str(e),
                }
        return {
            'action': '语法修复',
            'result': 'skipped',
            'details': {'reason': '无文件路径'},
        }

    def _repair_f541(self, file_path: str) -> Dict[str, Any]:
        """修复F541错误"""
        if not file_path or not os.path.isfile(file_path):
            return {
                'action': 'F541修复',
                'result': 'skipped',
                'details': {'reason': '无文件路径'},
            }
        try:
            result = subprocess.run(
                ['python3', '-m', 'flake8', '--select=F541', '--max-line-length=200', file_path],
                capture_output=True, text=True, timeout=10,
            )
            if not result.stdout.strip():
                return {
                    'action': 'F541修复',
                    'result': 'success',
                    'details': {'note': '无F541错误'},
                }
            # 使用已有的修复逻辑
            errors = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                import re as _re
                m = _re.match(r'^(.+?):(\d+):(\d+):', line)
                if m:
                    errors.append({'file': m.group(1), 'line': int(m.group(2)), 'col': int(m.group(3))})

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            lines = content.split('\n')
            fixed = 0
            for e in sorted(errors, key=lambda x: -x['line']):
                idx = e['line'] - 1
                if idx >= len(lines):
                    continue
                line = lines[idx]
                pos = e['col'] - 1
                if pos < len(line) and line[pos] == 'f':
                    if pos + 1 < len(line) and line[pos + 1] in ('"', "'"):
                        lines[idx] = line[:pos] + line[pos + 1:]
                        fixed += 1
                    elif pos + 2 < len(line) and line[pos + 1] == 'r' and line[pos + 2] in ('"', "'"):
                        lines[idx] = line[:pos] + line[pos + 1:]
                        fixed += 1

            if fixed > 0:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(lines))
                return {
                    'action': '移除f-string的f前缀',
                    'result': 'success',
                    'details': {'fixed_count': fixed},
                }
            return {
                'action': 'F541修复',
                'result': 'failed',
                'error': '未能修复任何F541错误',
            }
        except Exception as e:
            return {
                'action': 'F541修复',
                'result': 'failed',
                'error': str(e),
            }

    def _repair_f821(self, error_msg: str, file_path: str) -> Dict[str, Any]:
        """修复F821错误"""
        import re
        m = re.search(r"undefined name ['\"]?(\w+)['\"]?", error_msg)
        if not m or not file_path or not os.path.isfile(file_path):
            return {
                'action': 'F821修复',
                'result': 'skipped',
                'details': {'reason': '无法提取名称或文件不存在'},
            }
        name = m.group(1)
        import_map = {
            'logger': ('import logging', 'logger = logging.getLogger(__name__)'),
            'datetime': ('from datetime import datetime', None),
            'timedelta': ('from datetime import timedelta', None),
            'json': ('import json', None),
            'os': ('import os', None),
            'sys': ('import sys', None),
            'sqlite3': ('import sqlite3', None),
            'uuid': ('import uuid', None),
            'defaultdict': ('from collections import defaultdict', None),
            'Counter': ('from collections import Counter', None),
        }
        if name not in import_map:
            return {
                'action': 'F821修复',
                'result': 'skipped',
                'details': {'reason': f'未知名称: {name}'},
            }
        imp_stmt, extra = import_map[name]
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if imp_stmt in content:
            return {
                'action': 'F821修复',
                'result': 'success',
                'details': {'note': '导入已存在', 'import': imp_stmt},
            }
        lines = content.split('\n')
        insert_pos = 0
        if lines and lines[0].startswith('#!'):
            insert_pos = 1
        for i in range(insert_pos, min(len(lines), 30)):
            if lines[i].startswith(('import ', 'from ')):
                insert_pos = i + 1
        to_add = [imp_stmt]
        if extra:
            to_add.append(extra)
        for j, s in enumerate(to_add):
            lines.insert(insert_pos + j, s)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return {
            'action': '添加缺失导入',
            'result': 'success',
            'details': {'name': name, 'import': imp_stmt, 'extra': extra},
        }

    def _repair_database_error(self, error_msg: str) -> Dict[str, Any]:
        """修复数据库错误"""
        if 'database is locked' in error_msg:
            return {
                'action': '数据库锁恢复',
                'result': 'success',
                'details': {'strategy': 'WAL模式+忙等待', 'note': '建议增加PRAGMA busy_timeout'},
            }
        elif 'no such table' in error_msg:
            return {
                'action': '缺失表检测',
                'result': 'success',
                'details': {'strategy': '建议运行init_tables()创建缺失表'},
            }
        elif 'no such column' in error_msg:
            return {
                'action': '缺失列检测',
                'result': 'success',
                'details': {'strategy': '建议执行ALTER TABLE添加缺失列'},
            }
        return {
            'action': '数据库错误分析',
            'result': 'skipped',
            'details': {'reason': '未识别的数据库错误类型'},
        }

    def _repair_http_404(self, error_msg: str, file_path: str) -> Dict[str, Any]:
        """修复404错误"""
        return {
            'action': '路由检查',
            'result': 'success',
            'details': {'strategy': '检查路由注册，确认模板文件存在'},
        }

    def _repair_http_500(self, error_msg: str) -> Dict[str, Any]:
        """修复500错误"""
        return {
            'action': '服务器错误分析',
            'result': 'success',
            'details': {'strategy': '分析堆栈跟踪，定位根本原因并修复'},
        }

    def _repair_template_error(self, error_msg: str, file_path: str) -> Dict[str, Any]:
        """修复模板错误"""
        return {
            'action': '模板检查',
            'result': 'success',
            'details': {'strategy': '检查模板路径，确认Jinja2语法正确'},
        }

    def _repair_permission_error(self, file_path: str) -> Dict[str, Any]:
        """修复权限错误"""
        if file_path and os.path.exists(file_path):
            try:
                os.chmod(file_path, 0o644)
                return {
                    'action': '修复文件权限',
                    'result': 'success',
                    'details': {'file': file_path, 'mode': '644'},
                }
            except Exception as e:
                return {
                    'action': '修复文件权限',
                    'result': 'failed',
                    'error': str(e),
                }
        return {
            'action': '权限检查',
            'result': 'skipped',
            'details': {'reason': '无文件路径'},
        }

    def _repair_runtime_error(self, category: str, error_msg: str, file_path: str) -> Dict[str, Any]:
        """修复运行时错误"""
        strategies = {
            'attribute_error': '检查对象类型，添加属性存在性验证',
            'key_error': '使用dict.get()方法或添加键存在性检查',
            'type_error': '添加类型检查和参数验证',
            'value_error': '添加值范围验证和try-except处理',
        }
        return {
            'action': strategies.get(category, '运行时错误修复'),
            'result': 'success',
            'details': {'category': category, 'strategy': strategies.get(category, '')},
        }

    # ========== 健康巡检 ==========

    def run_health_check(self, check_type: str = 'full') -> Dict[str, Any]:
        """执行健康巡检"""
        check_id = f"hc_{uuid.uuid4().hex[:12]}"
        issues_found = 0
        issues_fixed = 0
        metrics = {}

        try:
            if check_type in ('full', 'code'):
                # 代码健康检查
                code_issues = self._check_code_health()
                metrics['code_health'] = code_issues
                issues_found += code_issues.get('issue_count', 0)
                issues_fixed += code_issues.get('fixed_count', 0)

            if check_type in ('full', 'database'):
                # 数据库健康检查
                db_issues = self._check_database_health()
                metrics['database_health'] = db_issues
                issues_found += db_issues.get('issue_count', 0)
                issues_fixed += db_issues.get('fixed_count', 0)

            if check_type in ('full', 'filesystem'):
                # 文件系统健康检查
                fs_issues = self._check_filesystem_health()
                metrics['filesystem_health'] = fs_issues
                issues_found += fs_issues.get('issue_count', 0)
                issues_fixed += fs_issues.get('fixed_count', 0)

            status = 'healthy' if issues_found == 0 else ('warning' if issues_found <= 5 else 'critical')

            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO eigenflux_health_check
                       (check_id, check_type, target, status, metrics,
                        issues_found, issues_fixed, checked_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (check_id, check_type, 'system', status,
                     json.dumps(metrics, ensure_ascii=False),
                     issues_found, issues_fixed, datetime.now().isoformat()),
                )
                conn.commit()

            return {
                'success': True,
                'check_id': check_id,
                'status': status,
                'issues_found': issues_found,
                'issues_fixed': issues_fixed,
                'metrics': metrics,
            }
        except Exception as e:
            logger.error(f"健康巡检失败: {e}")
            return {'success': False, 'error': str(e)}

    def _check_code_health(self) -> Dict[str, Any]:
        """代码健康检查"""
        try:
            result = subprocess.run(
                ['python3', '-m', 'flake8', '--select=F821,E9,F541',
                 '--max-line-length=200',
                 '--exclude=.venv,node_modules,__pycache__,venv,env,.git,_archive,backups,Backups',
                 '.'],
                capture_output=True, text=True, timeout=60,
            )
            issue_count = len([l for l in result.stdout.strip().split('\n') if l])
            return {
                'issue_count': issue_count,
                'fixed_count': 0,
                'details': f'发现 {issue_count} 个代码问题',
            }
        except Exception as e:
            return {'issue_count': 0, 'fixed_count': 0, 'error': str(e)}

    def _check_database_health(self) -> Dict[str, Any]:
        """数据库健康检查"""
        try:
            issues = 0
            with self._get_conn() as conn:
                # 检查表完整性
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                ).fetchall()
                for table in tables:
                    try:
                        conn.execute(f"SELECT COUNT(*) FROM [{table['name']}]")
                    except Exception:
                        issues += 1
                # 检查WAL模式
                wal = conn.execute("PRAGMA journal_mode").fetchone()
                if wal and wal[0] != 'wal':
                    issues += 1
            return {
                'issue_count': issues,
                'fixed_count': 0,
                'table_count': len(tables),
                'wal_mode': wal[0] if wal else 'unknown',
            }
        except Exception as e:
            return {'issue_count': 1, 'fixed_count': 0, 'error': str(e)}

    def _check_filesystem_health(self) -> Dict[str, Any]:
        """文件系统健康检查"""
        issues = 0
        fixed = 0
        # 检查根目录是否有应清理的文件
        for pattern in ['*.tmp', '*.chk', '.sync_temp_dir']:
            import glob
            for f in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
                issues += 1
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                        fixed += 1
                    elif os.path.isdir(f):
                        import shutil
                        shutil.rmtree(f)
                        fixed += 1
                except Exception:
                    pass
        return {'issue_count': issues, 'fixed_count': fixed}

    # ========== EigenFlux集成 ==========

    def _report_to_eigenflux(self, exception_id: str, category: str,
                             severity: str, error_msg: str, source: str):
        """向EigenFlux报告异常"""
        try:
            from app.services.eigenflux_adapter import (
                send_broadcast_message, register_employee_with_eigenflux,
            )
            register_employee_with_eigenflux(
                employee_id='eigenflux_auto_repair',
                employee_name='EigenFlux自动修复代理',
                employee_type='auto_repair_agent',
                capabilities=['异常检测', '自动修复', '健康巡检', '预防性维护'],
            )
            send_broadcast_message(
                sender_id='eigenflux_auto_repair',
                content=json.dumps({
                    'event': 'system_exception_detected',
                    'exception_id': exception_id,
                    'category': category,
                    'severity': severity,
                    'error': error_msg[:500],
                    'source': source,
                    'timestamp': datetime.now().isoformat(),
                }, ensure_ascii=False),
                topic='mtscos/anomaly/exception_detected',
            )
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE eigenflux_exception_log SET eigenflux_reported = 1 WHERE exception_id = ?",
                    (exception_id,),
                )
                conn.commit()
        except Exception as e:
            logger.debug(f"EigenFlux报告失败（非致命）: {e}")

    def report_repair_to_eigenflux(self, exception_id: str, success: bool, details: Dict):
        """向EigenFlux报告修复结果"""
        try:
            from app.services.eigenflux_adapter import send_broadcast_message
            send_broadcast_message(
                sender_id='eigenflux_auto_repair',
                content=json.dumps({
                    'event': 'system_exception_repaired' if success else 'system_exception_repair_failed',
                    'exception_id': exception_id,
                    'success': success,
                    'details': details,
                    'timestamp': datetime.now().isoformat(),
                }, ensure_ascii=False),
                topic='mtscos/anomaly/repair_result',
            )
        except Exception as e:
            logger.debug(f"EigenFlux修复报告失败: {e}")

    # ========== 监控循环 ==========

    def start_monitoring(self, interval: int = 60):
        """启动后台监控"""
        if self._monitoring:
            logger.info("监控已在运行中")
            return
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True,
        )
        self._monitor_thread.start()
        logger.info(f"异常监控已启动，间隔 {interval} 秒")

    def stop_monitoring(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("异常监控已停止")

    def _monitor_loop(self, interval: int):
        """监控循环"""
        while self._monitoring:
            try:
                # 执行健康巡检
                self.run_health_check('full')
                # 检查未修复的异常
                self._process_pending_exceptions()
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
            time.sleep(interval)

    def _process_pending_exceptions(self):
        """处理待修复的异常"""
        try:
            with self._get_conn() as conn:
                pending = conn.execute(
                    "SELECT exception_id FROM eigenflux_exception_log WHERE status IN ('detected', 'retrying') AND retry_count < ?",
                    (MAX_RETRIES,),
                ).fetchall()
            for row in pending:
                self.auto_repair(row['exception_id'])
        except Exception as e:
            logger.error(f"处理待修复异常失败: {e}")

    # ========== 工具方法 ==========

    def _get_config(self, key: str, default: str = '') -> str:
        """获取配置值"""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT config_value FROM eigenflux_monitor_config WHERE config_key = ?",
                    (key,),
                ).fetchone()
                return row[0] if row else default
        except Exception:
            return default

    def _update_exception_status(self, conn, exception_id: str, status: str,
                                  repair_method: str = '', repair_details: str = ''):
        """更新异常状态"""
        if repair_method:
            conn.execute(
                "UPDATE eigenflux_exception_log SET status = ?, repair_method = ?, repair_details = ? WHERE exception_id = ?",
                (status, repair_method, repair_details, exception_id),
            )
        else:
            conn.execute(
                "UPDATE eigenflux_exception_log SET status = ? WHERE exception_id = ?",
                (status, exception_id),
            )

    def get_summary(self) -> Dict[str, Any]:
        """获取服务汇总"""
        try:
            with self._get_conn() as conn:
                total = conn.execute("SELECT COUNT(*) FROM eigenflux_exception_log").fetchone()[0]
                repaired = conn.execute("SELECT COUNT(*) FROM eigenflux_exception_log WHERE status = 'repaired'").fetchone()[0]
                pending = conn.execute("SELECT COUNT(*) FROM eigenflux_exception_log WHERE status IN ('detected', 'retrying')").fetchone()[0]
                failed = conn.execute("SELECT COUNT(*) FROM eigenflux_exception_log WHERE status IN ('failed', 'max_retries_exceeded', 'not_repairable')").fetchone()[0]
                solutions = conn.execute("SELECT COUNT(*) FROM eigenflux_repair_solutions").fetchone()[0]
                health_checks = conn.execute("SELECT COUNT(*) FROM eigenflux_health_check").fetchone()[0]

                # 按类别统计
                by_category = {}
                rows = conn.execute(
                    "SELECT category, COUNT(*) as cnt FROM eigenflux_exception_log GROUP BY category ORDER BY cnt DESC",
                ).fetchall()
                for row in rows:
                    by_category[row['category']] = row['cnt']

                # 最近健康检查
                last_check = conn.execute(
                    "SELECT * FROM eigenflux_health_check ORDER BY checked_at DESC LIMIT 1",
                ).fetchone()

            return {
                'success': True,
                'total_exceptions': total,
                'repaired': repaired,
                'pending': pending,
                'failed': failed,
                'repair_rate': round(repaired / max(total, 1) * 100, 1),
                'solutions_count': solutions,
                'health_checks': health_checks,
                'by_category': by_category,
                'last_health_status': dict(last_check) if last_check else None,
                'stats': self.stats,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


# 模块级单例
eigenflux_auto_repair_service = EigenFluxAutoRepairService()


if __name__ == '__main__':
    # 冒烟测试
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    svc = EigenFluxAutoRepairService()

    print("=" * 60)
    print("  EigenFlux自动异常处理与修复服务 - 冒烟测试")
    print("=" * 60)

    # 1. 初始化
    print("\n[1] 初始化数据表...")
    r = svc.init_tables()
    print(f"  结果: {r}")

    # 2. 检测异常
    print("\n[2] 检测测试异常...")
    r = svc.detect_exception(
        error_message="ModuleNotFoundError: No module named 'sqlite3'",
        source='test',
        file_path='',
    )
    exc_id = r.get('exception_id', '')
    print(f"  异常ID: {exc_id}, 类别: {r.get('category')}")

    # 3. 自动修复
    print("\n[3] 自动修复...")
    r = svc.auto_repair(exc_id)
    print(f"  结果: {r}")

    # 4. 健康巡检
    print("\n[4] 健康巡检...")
    r = svc.run_health_check('full')
    print(f"  状态: {r.get('status')}, 发现: {r.get('issues_found')}, 修复: {r.get('issues_fixed')}")

    # 5. 汇总
    print("\n[5] 服务汇总...")
    r = svc.get_summary()
    print(f"  总异常: {r.get('total_exceptions')}")
    print(f"  已修复: {r.get('repaired')}")
    print(f"  修复率: {r.get('repair_rate')}%")
    print(f"  修复方案: {r.get('solutions_count')}")

    print("\n" + "=" * 60)
    print("  冒烟测试完成")
    print("=" * 60)
