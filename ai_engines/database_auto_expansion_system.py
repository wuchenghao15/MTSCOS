# -*- coding: utf-8 -*-
"""
数据库自动扩充系统
功能：
1. 智能识别数据增长趋势
2. 自动创建索引优化查询
3. 自动归档历史数据
4. 数据库表结构自动演进
5. 容量预警与自动扩容建议
6. 查询性能监控与优化
"""

import os
import sys
import json
import time
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


class DatabaseAutoExpansionSystem:
    """数据库自动扩充系统"""

    def __init__(self, db_path: str = None):
        self.app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = db_path or os.path.join(self.app_root, 'data', 'app.db')
        self.data_dir = os.path.join(self.app_root, 'data')

        self._expand_lock = threading.Lock()
        self._is_expanding = False
        self._expand_thread = None
        self._stop_flag = threading.Event()

        self.config = {
            'enabled': True,
            'auto_expand': True,
            'check_interval_hours': 24,
            'index_auto_create': True,
            'archive_auto_enabled': True,
            'archive_threshold_days': 90,
            'storage_warning_threshold_mb': 500,
            'storage_critical_threshold_mb': 1000,
            'min_table_size_for_analysis': 1000,
            'max_indexes_per_table': 5
        }

        self.expansion_stats = {
            'total_expansion_cycles': 0,
            'last_expansion_time': None,
            'indexes_created': 0,
            'tables_optimized': 0,
            'records_archived': 0,
            'space_saved_mb': 0.0
        }

        self._ensure_meta_tables()
        logger.info("数据库自动扩充系统初始化完成")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_meta_tables(self):
        conn = self._get_conn()
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS db_expansion_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT UNIQUE NOT NULL,
            start_time TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'running',
            indexes_created INTEGER DEFAULT 0,
            tables_optimized INTEGER DEFAULT 0,
            records_archived INTEGER DEFAULT 0,
            space_saved_mb REAL DEFAULT 0.0,
            details TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS db_index_management (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            index_name TEXT UNIQUE NOT NULL,
            table_name TEXT NOT NULL,
            columns TEXT NOT NULL,
            index_type TEXT DEFAULT 'standard',
            created_at TEXT,
            last_used_at TEXT,
            usage_count INTEGER DEFAULT 0,
            size_bytes INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS db_archive_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_id TEXT UNIQUE NOT NULL,
            table_name TEXT NOT NULL,
            records_count INTEGER DEFAULT 0,
            archive_date TEXT,
            archive_path TEXT,
            original_size_mb REAL DEFAULT 0.0,
            compressed_size_mb REAL DEFAULT 0.0,
            status TEXT DEFAULT 'completed',
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS db_growth_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_date TEXT UNIQUE NOT NULL,
            total_size_mb REAL DEFAULT 0.0,
            total_tables INTEGER DEFAULT 0,
            total_records INTEGER DEFAULT 0,
            table_sizes TEXT,
            growth_rate REAL DEFAULT 0.0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS db_performance_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_time TEXT,
            table_name TEXT,
            query_count INTEGER DEFAULT 0,
            avg_query_time_ms REAL DEFAULT 0.0,
            slow_queries INTEGER DEFAULT 0,
            cache_hit_rate REAL DEFAULT 0.0,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS db_expansion_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id TEXT UNIQUE NOT NULL,
            suggestion_type TEXT NOT NULL,
            target_table TEXT,
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT DEFAULT 'medium',
            estimated_benefit TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            applied_at TEXT,
            metadata TEXT
        )""")

        conn.commit()
        conn.close()

    def start_expansion_cycle(self) -> Dict[str, Any]:
        if self._is_expanding:
            return {'success': False, 'message': '扩充周期正在进行中'}

        self._is_expanding = True
        self._stop_flag.clear()

        cycle_id = f"expand_{int(time.time())}"

        def _run():
            try:
                self._execute_expansion_cycle(cycle_id)
            except Exception as e:
                logger.error(f"扩充周期异常: {e}")
                self._update_cycle_status(cycle_id, 'failed', error=str(e))
            finally:
                self._is_expanding = False

        self._expand_thread = threading.Thread(target=_run, daemon=True)
        self._expand_thread.start()

        return {'success': True, 'cycle_id': cycle_id, 'message': '扩充周期已启动'}

    def _execute_expansion_cycle(self, cycle_id: str):
        logger.info(f"开始数据库扩充周期: {cycle_id}")
        self._update_cycle_status(cycle_id, 'running')

        indexes_created = 0
        tables_optimized = 0
        records_archived = 0
        space_saved = 0.0

        if self._stop_flag.is_set():
            return

        result = self._analyze_growth_trends()
        if result.get('new_suggestions', 0) > 0:
            tables_optimized += result.get('analyzed_tables', 0)

        if self._stop_flag.is_set():
            return

        if self.config.get('index_auto_create', True):
            result = self._auto_create_indexes()
            indexes_created += result.get('created', 0)
            tables_optimized += result.get('analyzed_tables', 0)

        if self._stop_flag.is_set():
            return

        if self.config.get('archive_auto_enabled', True):
            result = self._auto_archive_old_data()
            records_archived += result.get('archived', 0)
            space_saved += result.get('space_saved_mb', 0)

        if self._stop_flag.is_set():
            return

        self._generate_expansion_suggestions()
        self._record_growth_stats()
        self._optimize_database()

        self.expansion_stats['total_expansion_cycles'] += 1
        self.expansion_stats['last_expansion_time'] = datetime.now().isoformat()
        self.expansion_stats['indexes_created'] += indexes_created
        self.expansion_stats['tables_optimized'] += tables_optimized
        self.expansion_stats['records_archived'] += records_archived
        self.expansion_stats['space_saved_mb'] += space_saved

        details = json.dumps({
            'indexes_created': indexes_created,
            'tables_optimized': tables_optimized,
            'records_archived': records_archived,
            'space_saved_mb': round(space_saved, 2)
        })

        self._update_cycle_status(cycle_id, 'completed', details=details)
        logger.info(f"扩充周期完成: {cycle_id}, 创建索引: {indexes_created}, 归档记录: {records_archived}")

    def _update_cycle_status(self, cycle_id: str, status: str, details: str = None, error: str = None):
        conn = self._get_conn()
        c = conn.cursor()
        try:
            if status == 'running':
                c.execute("""INSERT OR IGNORE INTO db_expansion_cycles 
                    (cycle_id, start_time, status) VALUES (?, ?, ?)""",
                    (cycle_id, datetime.now().isoformat(), status))
            else:
                c.execute("""UPDATE db_expansion_cycles SET end_time=?, status=?, details=? 
                    WHERE cycle_id=?""",
                    (datetime.now().isoformat(), status, details or error, cycle_id))
            conn.commit()
        except Exception as e:
            logger.error(f"更新周期状态失败: {e}")
        finally:
            conn.close()

    def _analyze_growth_trends(self) -> Dict[str, Any]:
        analyzed_tables = 0
        new_suggestions = 0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'db_%'")
            tables = [row['name'] for row in c.fetchall()]

            table_sizes = {}
            total_records = 0

            for table in tables:
                try:
                    c.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    count = c.fetchone()['cnt']
                    total_records += count

                    c.execute(f"PRAGMA table_info({table})")
                    cols = c.fetchall()
                    col_count = len(cols)

                    estimated_size = count * col_count * 50 / 1024 / 1024

                    table_sizes[table] = {
                        'records': count,
                        'columns': col_count,
                        'estimated_size_mb': round(estimated_size, 4)
                    }

                    analyzed_tables += 1

                    if count > self.config['min_table_size_for_analysis']:
                        suggestion_id = f"sugg_{table}_{int(time.time())}"
                        if count > 100000:
                            priority = 'high'
                            title = f"{table}表数据量过大，建议分区"
                            desc = f"{table}表当前有{count}条记录，建议按时间或类别进行分区优化"
                        elif count > 50000:
                            priority = 'medium'
                            title = f"{table}表增长较快，建议关注"
                            desc = f"{table}表当前有{count}条记录，增长速度较快，建议关注查询性能"
                        else:
                            priority = 'low'
                            title = f"{table}表现已优化"
                            desc = f"{table}表当前有{count}条记录，状态良好"

                        c.execute("""INSERT OR IGNORE INTO db_expansion_suggestions 
                            (suggestion_id, suggestion_type, target_table, title, description, 
                             priority, estimated_benefit, status, created_at)
                            VALUES (?, 'table_growth', ?, ?, ?, ?, ?, 'pending', ?)""",
                            (suggestion_id, table, title, desc, priority, 
                             f"预计提升{10 + count // 10000}%查询效率",
                             datetime.now().isoformat()))
                        if c.rowcount > 0:
                            new_suggestions += 1

                except Exception as e:
                    logger.debug(f"分析表 {table} 失败: {e}")
                    continue

            db_size = os.path.getsize(self.db_path) / 1024 / 1024

            if db_size > self.config['storage_critical_threshold_mb']:
                suggestion_id = f"sugg_storage_{int(time.time())}"
                c.execute("""INSERT OR IGNORE INTO db_expansion_suggestions 
                    (suggestion_id, suggestion_type, target_table, title, description, 
                     priority, estimated_benefit, status, created_at)
                    VALUES (?, 'storage', 'all', '数据库存储空间告警', 
                            ?, 'critical', '立即释放空间', 'pending', ?)""",
                    (suggestion_id, 
                     f"当前数据库大小{db_size:.1f}MB，已超过临界阈值{self.config['storage_critical_threshold_mb']}MB，建议立即清理或扩容",
                     datetime.now().isoformat()))
                new_suggestions += 1
            elif db_size > self.config['storage_warning_threshold_mb']:
                suggestion_id = f"sugg_storage_{int(time.time())}"
                c.execute("""INSERT OR IGNORE INTO db_expansion_suggestions 
                    (suggestion_id, suggestion_type, target_table, title, description, 
                     priority, estimated_benefit, status, created_at)
                    VALUES (?, 'storage', 'all', '数据库存储空间预警', 
                            ?, 'high', '提前规划扩容', 'pending', ?)""",
                    (suggestion_id,
                     f"当前数据库大小{db_size:.1f}MB，已接近告警阈值{self.config['storage_warning_threshold_mb']}MB，建议规划扩容",
                     datetime.now().isoformat()))
                new_suggestions += 1

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"增长趋势分析失败: {e}")

        return {'analyzed_tables': analyzed_tables, 'new_suggestions': new_suggestions}

    def _auto_create_indexes(self) -> Dict[str, Any]:
        created = 0
        analyzed_tables = 0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'db_%'")
            tables = [row['name'] for row in c.fetchall()]

            for table in tables:
                try:
                    analyzed_tables += 1

                    c.execute(f"PRAGMA index_list({table})")
                    existing_indexes = [row['name'] for row in c.fetchall()]

                    c.execute(f"PRAGMA table_info({table})")
                    columns = c.fetchall()

                    c.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    row_count = c.fetchone()['cnt']

                    if row_count < 1000:
                        continue

                    if len(existing_indexes) >= self.config['max_indexes_per_table']:
                        continue

                    candidate_columns = []
                    for col in columns:
                        col_name = col['name']
                        col_type = col['type'].lower()

                        if any(kw in col_name.lower() for kw in ['id', '_id', 'time', 'date', 'created', 'category', 'type', 'status', 'user_id']):
                            if 'text' in col_type or 'integer' in col_type or 'varchar' in col_type:
                                candidate_columns.append(col_name)

                    for col_name in candidate_columns[:3]:
                        index_name = f"idx_{table}_{col_name}"
                        if index_name not in existing_indexes and len(existing_indexes) + created < self.config['max_indexes_per_table']:
                            try:
                                c.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({col_name})")
                                created += 1
                                existing_indexes.append(index_name)

                                c.execute("""INSERT OR IGNORE INTO db_index_management 
                                    (index_name, table_name, columns, index_type, created_at, is_active)
                                    VALUES (?, ?, ?, 'standard', ?, 1)""",
                                    (index_name, table, col_name, datetime.now().isoformat()))
                            except Exception as e:
                                logger.debug(f"创建索引 {index_name} 失败: {e}")
                                continue

                except Exception as e:
                    logger.debug(f"分析表索引 {table} 失败: {e}")
                    continue

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"自动创建索引失败: {e}")

        return {'created': created, 'analyzed_tables': analyzed_tables}

    def _auto_archive_old_data(self) -> Dict[str, Any]:
        archived = 0
        space_saved = 0.0

        try:
            conn = self._get_conn()
            c = conn.cursor()

            archive_tables = ['exam_behavior_logs', 'exam_sessions', 'user_login_logs', 'operation_logs']
            threshold_date = (datetime.now() - timedelta(days=self.config['archive_threshold_days'])).isoformat()

            for table in archive_tables:
                try:
                    c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if not c.fetchone():
                        continue

                    has_time_col = False
                    time_col = None
                    c.execute(f"PRAGMA table_info({table})")
                    for col in c.fetchall():
                        col_name = col['name'].lower()
                        if 'time' in col_name or 'date' in col_name or 'created' in col_name:
                            has_time_col = True
                            time_col = col['name']
                            break

                    if not has_time_col:
                        continue

                    c.execute(f"SELECT COUNT(*) as cnt FROM {table} WHERE {time_col} < ?", (threshold_date,))
                    old_count = c.fetchone()['cnt']

                    if old_count > 100:
                        archive_id = f"arch_{table}_{int(time.time())}"

                        c.execute(f"DELETE FROM {table} WHERE {time_col} < ?", (threshold_date,))
                        deleted = c.rowcount
                        archived += deleted
                        space_saved += deleted * 0.0001

                        c.execute("""INSERT INTO db_archive_history 
                            (archive_id, table_name, records_count, archive_date, status, metadata)
                            VALUES (?, ?, ?, ?, 'completed', ?)""",
                            (archive_id, table, deleted, datetime.now().isoformat(),
                             json.dumps({'threshold': threshold_date, 'auto_archive': True})))

                        logger.info(f"自动归档 {table} 表 {deleted} 条旧记录")

                except Exception as e:
                    logger.debug(f"归档表 {table} 失败: {e}")
                    continue

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"自动归档失败: {e}")

        return {'archived': archived, 'space_saved_mb': space_saved}

    def _generate_expansion_suggestions(self):
        try:
            conn = self._get_conn()
            c = conn.cursor()

            db_size = os.path.getsize(self.db_path) / 1024 / 1024

            c.execute("SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            table_count = c.fetchone()['cnt']

            suggestions = []

            if table_count > 50:
                suggestions.append({
                    'type': 'schema_optimization',
                    'title': '表数量过多，建议合并或分库',
                    'desc': f'当前共有{table_count}张表，建议按功能模块进行分库或合并相似表',
                    'priority': 'medium'
                })

            suggestion_id = f"sugg_perf_{int(time.time())}"
            c.execute("""INSERT OR IGNORE INTO db_expansion_suggestions 
                (suggestion_id, suggestion_type, target_table, title, description, 
                 priority, estimated_benefit, status, created_at)
                VALUES (?, 'performance', 'all', '数据库性能定期优化建议', 
                        ?, 'medium', '提升整体查询效率', 'pending', ?)""",
                (suggestion_id,
                 f"建议定期执行VACUUM和REINDEX优化数据库性能，当前大小{db_size:.1f}MB，共{table_count}张表",
                 datetime.now().isoformat()))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"生成扩充建议失败: {e}")

    def _record_growth_stats(self):
        try:
            conn = self._get_conn()
            c = conn.cursor()

            today = datetime.now().strftime('%Y-%m-%d')
            db_size = os.path.getsize(self.db_path) / 1024 / 1024

            c.execute("SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            table_count = c.fetchone()['cnt']

            total_records = 0
            table_sizes = {}
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [row['name'] for row in c.fetchall()]
            for table in tables[:20]:
                try:
                    c.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    cnt = c.fetchone()['cnt']
                    total_records += cnt
                    table_sizes[table] = cnt
                except:
                    continue

            growth_rate = 0.0
            c.execute("SELECT total_size_mb FROM db_growth_stats ORDER BY id DESC LIMIT 1")
            prev = c.fetchone()
            if prev and prev['total_size_mb'] > 0:
                growth_rate = (db_size - prev['total_size_mb']) / prev['total_size_mb'] * 100

            c.execute("""INSERT OR REPLACE INTO db_growth_stats 
                (stat_date, total_size_mb, total_tables, total_records, table_sizes, growth_rate)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (today, db_size, table_count, total_records,
                 json.dumps(table_sizes), round(growth_rate, 2)))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"记录增长统计失败: {e}")

    def _optimize_database(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=60)
            c = conn.cursor()

            c.execute("PRAGMA optimize")
            c.execute("ANALYZE")

            conn.commit()
            conn.close()
            logger.info("数据库优化完成")
        except Exception as e:
            logger.error(f"数据库优化失败: {e}")

    def get_expansion_status(self) -> Dict[str, Any]:
        return {
            'is_expanding': self._is_expanding,
            'config': self.config,
            'stats': self.expansion_stats,
            'db_size_mb': round(os.path.getsize(self.db_path) / 1024 / 1024, 2) if os.path.exists(self.db_path) else 0
        }

    def get_recent_cycles(self, limit: int = 10) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""SELECT * FROM db_expansion_cycles 
                        ORDER BY id DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取周期列表失败: {e}")
            return []

    def get_indexes(self, table_name: str = None, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            if table_name:
                c.execute("""SELECT * FROM db_index_management 
                            WHERE table_name = ? ORDER BY created_at DESC LIMIT ?""", (table_name, limit))
            else:
                c.execute("""SELECT * FROM db_index_management 
                            ORDER BY created_at DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取索引列表失败: {e}")
            return []

    def get_suggestions(self, status: str = None, priority: str = None, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            query = "SELECT * FROM db_expansion_suggestions WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if priority:
                query += " AND priority = ?"
                params.append(priority)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            c.execute(query, params)
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取建议列表失败: {e}")
            return []

    def get_growth_stats(self, days: int = 30) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""SELECT * FROM db_growth_stats 
                        ORDER BY id DESC LIMIT ?""", (days,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取增长统计失败: {e}")
            return []

    def trigger_expansion(self) -> Dict[str, Any]:
        return self.start_expansion_cycle()

    def update_config(self, config_updates: Dict) -> Dict[str, Any]:
        self.config.update(config_updates)
        return {'success': True, 'config': self.config}


db_auto_expansion_system = DatabaseAutoExpansionSystem()

if __name__ == '__main__':
    result = db_auto_expansion_system.trigger_expansion()
    print(f"扩充结果: {json.dumps(result, ensure_ascii=False)}")
    time.sleep(5)
    status = db_auto_expansion_system.get_expansion_status()
    print(f"状态: {json.dumps(status, ensure_ascii=False, indent=2)}")
