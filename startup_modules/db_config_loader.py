#!/usr/bin/env python3
"""
数据库配置加载器 - 8阶段配置加载
负责从数据库读取系统配置参数
"""

import os
import sys
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, 'split_databases')

class ConfigLoader:
    def __init__(self):
        self.configs = {}
        self.loaded_stages = []
        
        self.stages = [
            ('stage_core', '核心配置'),
            ('stage_database', '数据库配置'),
            ('stage_app', '应用配置'),
            ('stage_security', '安全配置'),
            ('stage_ai', 'AI引擎配置'),
            ('stage_exam', '考试系统配置'),
            ('stage_question', '题库配置'),
            ('stage_system', '系统配置'),
        ]
    
    def _get_db_connection(self, db_name):
        db_path = os.path.join(DB_DIR, f'{db_name}.db')
        if not os.path.exists(db_path):
            return None
        return sqlite3.connect(db_path)
    
    def load_stage(self, stage_name):
        configs = {}
        
        try:
            conn = self._get_db_connection('system')
            if conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT config_key, config_value, config_type 
                    FROM system_configs 
                    WHERE stage = ? OR stage IS NULL
                """, (stage_name,))
                for row in cursor.fetchall():
                    key, value, value_type = row
                    try:
                        if value_type == 'json':
                            configs[key] = json.loads(value)
                        elif value_type == 'int':
                            configs[key] = int(value)
                        elif value_type == 'float':
                            configs[key] = float(value)
                        elif value_type == 'bool':
                            configs[key] = value.lower() == 'true'
                        else:
                            configs[key] = value
                    except:
                        configs[key] = value
                conn.close()
        except Exception as e:
            pass
        
        try:
            conn = self._get_db_connection('config')
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM configs")
                for row in cursor.fetchall():
                    key, value = row
                    if key not in configs:
                        try:
                            configs[key] = json.loads(value)
                        except:
                            configs[key] = value
                conn.close()
        except Exception as e:
            pass
        
        self.configs[stage_name] = configs
        self.loaded_stages.append(stage_name)
        return configs
    
    def get_stage_config(self, stage_name):
        return self.configs.get(stage_name, {})
    
    def reload_stage(self, stage_name):
        if stage_name in self.loaded_stages:
            self.loaded_stages.remove(stage_name)
        return self.load_stage(stage_name)
    
    def load_all(self):
        all_configs = {}
        for stage_name, stage_desc in self.stages:
            stage_configs = self.load_stage(stage_name)
            all_configs.update(stage_configs)
        
        all_configs.update({
            'app_name': 'MTSCOS AI 智能考试系统',
            'app_version': '17.20.0',
            'app_code_name': 'Dynamic Question Engine Edition',
            'debug': False,
            'timezone': 'Asia/Shanghai',
            'db_count': 14,
        })
        
        return all_configs

config_loader = ConfigLoader()

def load_db_configs():
    return config_loader.load_all()

def get_all_db_configs():
    return config_loader.configs
