#!/usr/bin/env python3
""" 历史数据服务 实现历史数据记录、归档和管理功能 """

import os
import sqlite3
import logging
import json
import time
import shutil
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class HistoryDataService:
    """历史数据服务"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        self.retention_days = self.config.get('retention_days', 90)
        self.compress_enabled = self.config.get('compress_enabled', True)
        self.archive_enabled = self.config.get('archive_enabled', True)
        self.archive_interval = self.config.get('archive_interval', 86400)
        self._running = False
        
        self._archive_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'archive')
        os.makedirs(self._archive_path, exist_ok=True)
        
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(''' CREATE TABLE IF NOT EXISTS history_data ( id INTEGER PRIMARY KEY AUTOINCREMENT, data_type TEXT NOT NULL, data_key TEXT, data_value TEXT, original_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, archived_at TEXT, is_archived INTEGER DEFAULT 0 ) ''')
        
        cursor.execute(''' CREATE TABLE IF NOT EXISTS archive_records ( id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id TEXT UNIQUE NOT NULL, data_type TEXT, record_count INTEGER DEFAULT 0, archive_path TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) ''')
        
        conn.commit()
        conn.close()
    
    def _generate_archive_id(self) -> str:
        """生成归档ID"""
        return f'arch_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    
    def record(self, data_type: str, data_key: str, data_value: str, original_id: int = None):
        """记录历史数据"""
        if not self.enabled:
            return
        
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(''' INSERT INTO history_data (data_type, data_key, data_value, original_id) VALUES (?, ?, ?, ?) ''', (data_type, data_key, data_value, original_id))
        
        conn.commit()
        conn.close()
        
        logger.debug(f"记录历史数据: {data_type}.{data_key}")
    
    def _archive_data(self, data_type: str = None):
        """归档历史数据"""
        if not self.archive_enabled:
            return
        
        cutoff_time = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
        
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        query = 'SELECT * FROM history_data WHERE is_archived = 0 AND created_at < ?'
        params = [cutoff_time]
        
        if data_type:
            query += ' AND data_type = ?'
            params.append(data_type)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return
        
        archive_id = self._generate_archive_id()
        archive_path = os.path.join(self._archive_path, f'{archive_id}.json')
        
        archive_data = [{
            'id': row[0],
            'data_type': row[1],
            'data_key': row[2],
            'data_value': row[3],
            'original_id': row[4],
            'created_at': row[5]
        } for row in rows]
        
        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        
        cursor.execute('INSERT INTO archive_records (archive_id, data_type, record_count, archive_path) VALUES (?, ?, ?, ?)',
                      (archive_id, data_type or 'all', len(rows), archive_path))
        
        cursor.execute('UPDATE history_data SET is_archived = 1, archived_at = ? WHERE id IN (' + 
                      ','.join(['?'] * len(rows)) + ')', 
                      [datetime.now().isoformat()] + [row[0] for row in rows])
        
        conn.commit()
        conn.close()
        
        logger.info(f"归档历史数据: {archive_id}, 记录数: {len(rows)}")
    
    def _cleanup_old_data(self):
        """清理过期数据"""
        cutoff_time = (datetime.now() - timedelta(days=self.retention_days * 2)).isoformat()
        
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM history_data WHERE is_archived = 1 AND archived_at < ?', (cutoff_time,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            logger.info(f"清理了 {deleted_count} 条过期历史数据")
    
    def get_history(self, data_type: str = None, data_key: str = None, 
                   start_time: str = None, end_time: str = None,
                   limit: int = 100, offset: int = 0) -> list:
        """查询历史数据"""
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        query = 'SELECT * FROM history_data WHERE 1=1'
        params = []
        
        if data_type:
            query += ' AND data_type = ?'
            params.append(data_type)
        if data_key:
            query += ' AND data_key = ?'
            params.append(data_key)
        if start_time:
            query += ' AND created_at >= ?'
            params.append(start_time)
        if end_time:
            query += ' AND created_at <= ?'
            params.append(end_time)
        
        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'id': row[0],
            'data_type': row[1],
            'data_key': row[2],
            'data_value': row[3],
            'original_id': row[4],
            'created_at': row[5],
            'archived_at': row[6],
            'is_archived': row[7]
        } for row in rows]
    
    def start(self):
        """启动历史数据服务"""
        logger.info(f"启动历史数据服务，归档间隔: {self.archive_interval}秒")
        self._running = True
        
        while self._running:
            try:
                self._archive_data()
                self._cleanup_old_data()
            except Exception as e:
                logger.error(f"历史数据服务异常: {e}")
            
            for _ in range(self.archive_interval):
                if not self._running:
                    break
                time.sleep(1)
    
    def stop(self):
        """停止历史数据服务"""
        logger.info("停止历史数据服务")
        self._running = False

history_data_service = HistoryDataService()