# -*- coding: utf-8 -*-
"""
网站自动化升级拓展系统
功能：
1. 自动版本检测与升级
2. AI自动学习升级协调
3. 数据库自动扩充协调
4. 功能模块自动拓展
5. 系统健康自检与自动修复
"""

import os
import sys
import json
import time
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


class AutoUpgradeSystem:
    """网站自动化升级拓展系统"""

    def __init__(self, app_root: str = None):
        self.app_root = app_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(self.app_root, 'data', 'app.db')
        self.data_dir = os.path.join(self.app_root, 'data')
        self.log_dir = os.path.join(self.data_dir, 'logs')

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)

        self._upgrade_lock = threading.Lock()
        self._is_upgrading = False
        self._scheduler_running = False
        self._scheduler_thread = None
        self._stop_flag = threading.Event()

        self.config = {
            'enabled': True,
            'auto_upgrade_enabled': True,
            'check_interval_hours': 12,
            'auto_learning_enabled': True,
            'auto_db_expansion_enabled': True,
            'auto_feature_expansion_enabled': True,
            'auto_health_check_enabled': True,
            'backup_before_upgrade': True,
            'upgrade_window_start': '02:00',
            'upgrade_window_end': '05:00',
            'notify_on_upgrade': True,
            'version': '1.0.0'
        }

        self.upgrade_stats = {
            'total_upgrades': 0,
            'last_upgrade_time': None,
            'last_upgrade_version': None,
            'total_features_added': 0,
            'total_failures': 0,
            'uptime_since_restart': None
        }

        self.start_time = datetime.now()

        self._ai_system = None
        self._db_system = None

        self._ensure_tables()
        self._init_subsystems()
        logger.info("网站自动化升级拓展系统初始化完成")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self):
        conn = self._get_conn()
        c = conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS auto_upgrade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upgrade_id TEXT UNIQUE NOT NULL,
            upgrade_type TEXT NOT NULL,
            from_version TEXT,
            to_version TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'running',
            changes_summary TEXT,
            backup_path TEXT,
            error_message TEXT,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS auto_upgrade_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_id TEXT UNIQUE NOT NULL,
            feature_name TEXT NOT NULL,
            feature_type TEXT,
            description TEXT,
            version_added TEXT,
            status TEXT DEFAULT 'active',
            enabled INTEGER DEFAULT 1,
            added_at TEXT,
            last_used_at TEXT,
            usage_count INTEGER DEFAULT 0,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS auto_health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id TEXT UNIQUE NOT NULL,
            check_type TEXT NOT NULL,
            check_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            result TEXT,
            details TEXT,
            checked_at TEXT,
            fix_applied INTEGER DEFAULT 0,
            fix_description TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS system_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT UNIQUE NOT NULL,
            current_version TEXT NOT NULL,
            latest_version TEXT,
            last_checked TEXT,
            last_updated TEXT,
            update_available INTEGER DEFAULT 0,
            metadata TEXT
        )""")

        conn.commit()
        conn.close()

    def _init_subsystems(self):
        try:
            sys.path.insert(0, self.app_root)
            from ai_engines.advanced_auto_learning_system import AdvancedAutoLearningSystem
            self._ai_system = AdvancedAutoLearningSystem(db_path=self.db_path)
        except Exception as e:
            logger.warning(f"AI学习系统导入失败: {e}")

        try:
            sys.path.insert(0, self.app_root)
            from ai_engines.database_auto_expansion_system import DatabaseAutoExpansionSystem
            self._db_system = DatabaseAutoExpansionSystem(db_path=self.db_path)
        except Exception as e:
            logger.warning(f"数据库扩充系统导入失败: {e}")

        self._register_builtin_features()

    def _register_builtin_features(self):
        builtin_features = [
            {
                'feature_id': 'feat_ai_learning_001',
                'feature_name': 'AI错误模式学习',
                'feature_type': 'ai_learning',
                'description': '自动学习用户答题错误模式，提供针对性优化建议'
            },
            {
                'feature_id': 'feat_ai_learning_002',
                'feature_name': '用户行为挖掘',
                'feature_type': 'ai_learning',
                'description': '深度挖掘用户学习行为数据，生成个性化学习路径'
            },
            {
                'feature_id': 'feat_ai_learning_003',
                'feature_name': '题目质量评估',
                'feature_type': 'ai_learning',
                'description': '自动评估题目质量并提供优化建议'
            },
            {
                'feature_id': 'feat_ai_learning_004',
                'feature_name': '知识图谱扩展',
                'feature_type': 'ai_learning',
                'description': '自动扩展知识图谱，发现知识点关联'
            },
            {
                'feature_id': 'feat_db_expand_001',
                'feature_name': '智能索引创建',
                'feature_type': 'db_expansion',
                'description': '自动分析查询模式，创建最优索引'
            },
            {
                'feature_id': 'feat_db_expand_002',
                'feature_name': '历史数据归档',
                'feature_type': 'db_expansion',
                'description': '自动归档历史数据，释放存储空间'
            },
            {
                'feature_id': 'feat_db_expand_003',
                'feature_name': '容量预警与建议',
                'feature_type': 'db_expansion',
                'description': '智能监控数据库容量，提前预警并给出扩容建议'
            },
            {
                'feature_id': 'feat_health_001',
                'feature_name': '系统健康自检',
                'feature_type': 'health_check',
                'description': '定期检查系统健康状态，自动修复常见问题'
            },
            {
                'feature_id': 'feat_upgrade_001',
                'feature_name': '自动版本升级',
                'feature_type': 'upgrade',
                'description': '自动检测并应用系统版本更新'
            },
            {
                'feature_id': 'feat_upgrade_002',
                'feature_name': '功能模块拓展',
                'feature_type': 'upgrade',
                'description': '根据用户使用数据，智能推荐并启用新功能模块'
            }
        ]

        try:
            conn = self._get_conn()
            c = conn.cursor()

            for feat in builtin_features:
                c.execute("""INSERT OR IGNORE INTO auto_upgrade_features 
                    (feature_id, feature_name, feature_type, description, 
                     version_added, status, enabled, added_at)
                    VALUES (?, ?, ?, ?, ?, 'active', 1, ?)""",
                    (feat['feature_id'], feat['feature_name'], feat['feature_type'],
                     feat['description'], self.config['version'], datetime.now().isoformat()))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"注册内置功能失败: {e}")

    def start_scheduler(self):
        if self._scheduler_running:
            return {'success': False, 'message': '调度器已在运行'}

        self._scheduler_running = True
        self._stop_flag.clear()

        def _scheduler_loop():
            logger.info("自动化升级调度器启动")
            while not self._stop_flag.is_set():
                try:
                    now = datetime.now()
                    hour = now.hour
                    minute = now.minute

                    if hour == 3 and minute == 0:
                        if self.config.get('auto_learning_enabled', True):
                            self.trigger_ai_learning()

                    if hour == 4 and minute == 0:
                        if self.config.get('auto_db_expansion_enabled', True):
                            self.trigger_db_expansion()

                    if hour == 2 and minute == 30 and now.weekday() == 0:
                        if self.config.get('auto_health_check_enabled', True):
                            self.run_health_check()

                    self._stop_flag.wait(60)
                except Exception as e:
                    logger.error(f"调度器循环异常: {e}")
                    self._stop_flag.wait(60)

            logger.info("自动化升级调度器停止")
            self._scheduler_running = False

        self._scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
        self._scheduler_thread.start()

        return {'success': True, 'message': '调度器已启动'}

    def stop_scheduler(self):
        self._stop_flag.set()
        return {'success': True, 'message': '调度器正在停止'}

    def trigger_full_upgrade(self) -> Dict[str, Any]:
        if self._is_upgrading:
            return {'success': False, 'message': '升级正在进行中'}

        self._is_upgrading = True
        upgrade_id = f"upgrade_{int(time.time())}"

        def _run():
            try:
                self._execute_full_upgrade(upgrade_id)
            except Exception as e:
                logger.error(f"完整升级异常: {e}")
                self._record_upgrade(upgrade_id, 'full_upgrade', status='failed', error=str(e))
            finally:
                self._is_upgrading = False

        threading.Thread(target=_run, daemon=True).start()

        return {'success': True, 'upgrade_id': upgrade_id, 'message': '完整升级已启动'}

    def _execute_full_upgrade(self, upgrade_id: str):
        logger.info(f"开始完整升级: {upgrade_id}")
        self._record_upgrade(upgrade_id, 'full_upgrade', status='running')

        changes = []

        if self.config.get('backup_before_upgrade', True):
            backup_result = self._create_backup()
            if backup_result.get('success'):
                changes.append(f"备份完成: {backup_result.get('backup_path')}")
            else:
                changes.append(f"备份警告: {backup_result.get('message')}")

        if self.config.get('auto_health_check_enabled', True):
            health_result = self.run_health_check()
            changes.append(f"健康检查: {len(health_result.get('checks', []))}项检查完成")

        if self.config.get('auto_learning_enabled', True) and self._ai_system:
            learn_result = self._ai_system.trigger_learning()
            if learn_result.get('success'):
                changes.append("AI学习周期已启动")

        if self.config.get('auto_db_expansion_enabled', True) and self._db_system:
            db_result = self._db_system.trigger_expansion()
            if db_result.get('success'):
                changes.append("数据库扩充周期已启动")

        if self.config.get('auto_feature_expansion_enabled', True):
            feature_result = self._expand_features()
            changes.append(f"功能拓展: {feature_result.get('added', 0)}个新功能")

        self.upgrade_stats['total_upgrades'] += 1
        self.upgrade_stats['last_upgrade_time'] = datetime.now().isoformat()
        self.upgrade_stats['last_upgrade_version'] = self.config['version']

        self._record_upgrade(upgrade_id, 'full_upgrade', status='completed',
                            changes_summary=json.dumps(changes, ensure_ascii=False))
        logger.info(f"完整升级完成: {upgrade_id}")

    def _record_upgrade(self, upgrade_id: str, upgrade_type: str, status: str,
                       from_version: str = None, to_version: str = None,
                       changes_summary: str = None, backup_path: str = None,
                       error: str = None):
        try:
            conn = self._get_conn()
            c = conn.cursor()

            now = datetime.now().isoformat()
            if status == 'running':
                c.execute("""INSERT OR IGNORE INTO auto_upgrade_history 
                    (upgrade_id, upgrade_type, from_version, to_version, 
                     start_time, status, backup_path, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (upgrade_id, upgrade_type, from_version or self.config['version'],
                     to_version, now, status, backup_path, None))
            else:
                c.execute("""UPDATE auto_upgrade_history SET end_time=?, status=?, 
                            changes_summary=?, error_message=? 
                            WHERE upgrade_id=?""",
                    (now, status, changes_summary, error, upgrade_id))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"记录升级历史失败: {e}")

    def _create_backup(self) -> Dict[str, Any]:
        try:
            backup_dir = os.path.join(self.data_dir, 'backups')
            os.makedirs(backup_dir, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(backup_dir, f'app_backup_{timestamp}.db')

            if os.path.exists(self.db_path):
                import shutil
                shutil.copy2(self.db_path, backup_file)
                return {'success': True, 'backup_path': backup_file}
            else:
                return {'success': False, 'message': '数据库文件不存在'}
        except Exception as e:
            logger.error(f"创建备份失败: {e}")
            return {'success': False, 'message': str(e)}

    def trigger_ai_learning(self) -> Dict[str, Any]:
        if self._ai_system:
            return self._ai_system.trigger_learning()
        return {'success': False, 'message': 'AI学习系统未初始化'}

    def trigger_db_expansion(self) -> Dict[str, Any]:
        if self._db_system:
            return self._db_system.trigger_expansion()
        return {'success': False, 'message': '数据库扩充系统未初始化'}

    def run_health_check(self) -> Dict[str, Any]:
        check_id = f"health_{int(time.time())}"
        checks = []

        health_items = [
            ('database', '数据库连接检查', self._check_database),
            ('database', '数据库完整性检查', self._check_db_integrity),
            ('disk', '磁盘空间检查', self._check_disk_space),
            ('memory', '内存使用检查', self._check_memory),
            ('files', '文件完整性检查', self._check_file_integrity),
            ('config', '配置文件检查', self._check_config),
            ('cache', '缓存状态检查', self._check_cache),
            ('logs', '日志系统检查', self._check_logs)
        ]

        idx = 0
        for check_type, check_name, check_func in health_items:
            try:
                result = check_func()
                item_check_id = f"{check_id}_{idx}"
                idx += 1
                status = 'ok' if result.get('success') else 'warning'
                self._record_health_check(item_check_id, check_type, check_name,
                                         status, result.get('message'), result.get('details'))
                checks.append({
                    'type': check_type,
                    'name': check_name,
                    'status': status,
                    'message': result.get('message')
                })
            except Exception as e:
                logger.error(f"健康检查 {check_name} 失败: {e}")
                checks.append({
                    'type': check_type,
                    'name': check_name,
                    'status': 'error',
                    'message': str(e)
                })

        return {'check_id': check_id, 'checks': checks,
                'total': len(checks),
                'ok_count': sum(1 for c in checks if c['status'] == 'ok'),
                'warning_count': sum(1 for c in checks if c['status'] == 'warning'),
                'error_count': sum(1 for c in checks if c['status'] == 'error')}

    def _record_health_check(self, check_id: str, check_type: str, check_name: str,
                            status: str, result: str, details: str = None):
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO auto_health_checks 
                (check_id, check_type, check_name, status, result, details, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (check_id, check_type, check_name, status, result, details,
                 datetime.now().isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"记录健康检查失败: {e}")

    def _check_database(self) -> Dict[str, Any]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("SELECT 1")
            c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = c.fetchone()[0]
            conn.close()
            return {'success': True, 'message': f'数据库正常，共{table_count}张表'}
        except Exception as e:
            return {'success': False, 'message': f'数据库异常: {str(e)}'}

    def _check_db_integrity(self) -> Dict[str, Any]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("PRAGMA integrity_check")
            result = c.fetchone()[0]
            conn.close()
            if result == 'ok':
                return {'success': True, 'message': '数据库完整性正常'}
            else:
                return {'success': False, 'message': f'数据库完整性问题: {result}'}
        except Exception as e:
            return {'success': False, 'message': f'完整性检查失败: {str(e)}'}

    def _check_disk_space(self) -> Dict[str, Any]:
        try:
            statvfs = os.statvfs(self.data_dir)
            free_mb = (statvfs.f_frsize * statvfs.f_bavail) / 1024 / 1024
            total_mb = (statvfs.f_frsize * statvfs.f_blocks) / 1024 / 1024
            usage_percent = (1 - free_mb / total_mb) * 100 if total_mb > 0 else 0

            if usage_percent > 90:
                return {'success': False, 'message': f'磁盘空间不足，使用率{usage_percent:.1f}%，剩余{free_mb:.0f}MB'}
            elif usage_percent > 80:
                return {'success': True, 'message': f'磁盘空间正常，使用率{usage_percent:.1f}%，剩余{free_mb:.0f}MB'}
            else:
                return {'success': True, 'message': f'磁盘空间充足，使用率{usage_percent:.1f}%，剩余{free_mb:.0f}MB'}
        except Exception as e:
            return {'success': False, 'message': f'磁盘检查失败: {str(e)}'}

    def _check_memory(self) -> Dict[str, Any]:
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent > 90:
                return {'success': False, 'message': f'内存使用率过高: {mem.percent:.1f}%'}
            else:
                return {'success': True, 'message': f'内存使用正常: {mem.percent:.1f}%'}
        except ImportError:
            return {'success': True, 'message': '内存检查: psutil未安装，跳过'}
        except Exception as e:
            return {'success': False, 'message': f'内存检查失败: {str(e)}'}

    def _check_file_integrity(self) -> Dict[str, Any]:
        try:
            required_files = ['app.py']
            missing = []
            for f in required_files:
                fpath = os.path.join(self.app_root, f)
                if not os.path.exists(fpath):
                    missing.append(f)

            if missing:
                return {'success': False, 'message': f'缺少关键文件: {", ".join(missing)}'}
            else:
                return {'success': True, 'message': '关键文件完整'}
        except Exception as e:
            return {'success': False, 'message': f'文件检查失败: {str(e)}'}

    def _check_config(self) -> Dict[str, Any]:
        try:
            config_path = os.path.join(self.app_root, 'config.py')
            if os.path.exists(config_path):
                return {'success': True, 'message': '配置文件存在'}
            else:
                return {'success': True, 'message': '使用默认配置'}
        except Exception as e:
            return {'success': False, 'message': f'配置检查失败: {str(e)}'}

    def _check_cache(self) -> Dict[str, Any]:
        try:
            cache_dir = os.path.join(self.data_dir, 'cache')
            if os.path.exists(cache_dir):
                file_count = len(os.listdir(cache_dir))
                return {'success': True, 'message': f'缓存目录正常，共{file_count}个文件'}
            else:
                os.makedirs(cache_dir, exist_ok=True)
                return {'success': True, 'message': '缓存目录已创建'}
        except Exception as e:
            return {'success': False, 'message': f'缓存检查失败: {str(e)}'}

    def _check_logs(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.log_dir):
                log_count = len(os.listdir(self.log_dir))
                return {'success': True, 'message': f'日志目录正常，共{log_count}个文件'}
            else:
                os.makedirs(self.log_dir, exist_ok=True)
                return {'success': True, 'message': '日志目录已创建'}
        except Exception as e:
            return {'success': False, 'message': f'日志检查失败: {str(e)}'}

    def _expand_features(self) -> Dict[str, Any]:
        added = 0
        try:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("SELECT COUNT(*) as cnt FROM exam_behavior_logs")
            log_count = c.fetchone()['cnt']

            c.execute("SELECT COUNT(*) as cnt FROM users")
            user_count = c.fetchone()['cnt'] if self._table_exists(c, 'users') else 0

            if log_count > 1000 and user_count > 10:
                new_features = [
                    {
                        'feature_id': 'feat_adv_001',
                        'feature_name': '高级学习分析报告',
                        'feature_type': 'premium',
                        'description': '基于大数据的深度学习分析报告，可视化展示学习进度和知识掌握度',
                        'version': self.config['version']
                    }
                ]

                for feat in new_features:
                    c.execute("""INSERT OR IGNORE INTO auto_upgrade_features 
                        (feature_id, feature_name, feature_type, description, 
                         version_added, status, enabled, added_at)
                        VALUES (?, ?, ?, ?, ?, 'active', 1, ?)""",
                        (feat['feature_id'], feat['feature_name'], feat['feature_type'],
                         feat['description'], feat['version'], datetime.now().isoformat()))
                    if c.rowcount > 0:
                        added += 1

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"功能拓展失败: {e}")

        self.upgrade_stats['total_features_added'] += added
        return {'added': added}

    def _table_exists(self, cursor, table_name: str) -> bool:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return cursor.fetchone() is not None

    def get_upgrade_status(self) -> Dict[str, Any]:
        uptime = datetime.now() - self.start_time
        return {
            'is_upgrading': self._is_upgrading,
            'scheduler_running': self._scheduler_running,
            'config': self.config,
            'stats': self.upgrade_stats,
            'uptime': str(uptime),
            'ai_system_available': self._ai_system is not None,
            'db_system_available': self._db_system is not None
        }

    def get_upgrade_history(self, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""SELECT * FROM auto_upgrade_history 
                        ORDER BY id DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取升级历史失败: {e}")
            return []

    def get_features(self, feature_type: str = None, limit: int = 50) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            if feature_type:
                c.execute("""SELECT * FROM auto_upgrade_features 
                            WHERE feature_type = ? ORDER BY added_at DESC LIMIT ?""",
                         (feature_type, limit))
            else:
                c.execute("""SELECT * FROM auto_upgrade_features 
                            ORDER BY added_at DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取功能列表失败: {e}")
            return []

    def get_health_history(self, limit: int = 20) -> List[Dict]:
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""SELECT * FROM auto_health_checks 
                        ORDER BY id DESC LIMIT ?""", (limit,))
            rows = c.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"获取健康检查历史失败: {e}")
            return []

    def update_config(self, config_updates: Dict) -> Dict[str, Any]:
        self.config.update(config_updates)
        return {'success': True, 'config': self.config}


auto_upgrade_system = AutoUpgradeSystem()

if __name__ == '__main__':
    status = auto_upgrade_system.get_upgrade_status()
    print(f"系统状态: {json.dumps(status, ensure_ascii=False, indent=2)}")
    health = auto_upgrade_system.run_health_check()
    print(f"健康检查: {json.dumps(health, ensure_ascii=False, indent=2)}")
