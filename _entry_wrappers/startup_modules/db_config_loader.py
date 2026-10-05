#!/usr/bin/env python3
r"""
数据库配置加载器 - 8阶段配置加载
负责从数据库读取系统配置参数
r"""

import os
import sys
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, r'Database')

class ConfigLoader:
    def __init__(self):
        self.configs = {}
        self.loaded_stages = []

        self.stages = [
            (r'stage_core', r'核心配置'),
            (r'stage_database', r'数据库配置'),
            (r'stage_app', r'应用配置'),
            (r'stage_security', r'安全配置'),
            (r'stage_ai', r'AI引擎配置'),
            (r'stage_exam', r'考试系统配置'),
            (r'stage_question', r'题库配置'),
            (r'stage_system', r'系统配置'),
        ]

    def _get_db_connection(self, db_name):
        db_path = os.path.join(DB_DIR, fr'{db_name}.db')
        if not os.path.exists(db_path):
            return None
        return sqlite3.connect(db_path)

    def load_stage(self, stage_name):
        configs = {}

        try:
            conn = self._get_db_connection(r'system')
            if conn:
                cursor = conn.cursor()
                cursor.execute(r"""
                    SELECT config_key, config_value, config_type
                    FROM system_configs
                    WHERE stage = ? OR stage IS NULL
                r""", (stage_name,))
                for row in cursor.fetchall():
                    key, value, value_type = row
                    try:
                        if value_type == r'json':
                            configs[key] = json.loads(value)
                        elif value_type == r'int':
                            configs[key] = int(value)
                        elif value_type == r'float':
                            configs[key] = float(value)
                        elif value_type == r'bool':
                            configs[key] = value.lower() == r'true'
                        else:
                            configs[key] = value
                    except Exception:
                        configs[key] = value
                conn.close()
        except Exception as e:
            pass

        try:
            conn = self._get_db_connection(r'config')
            if conn:
                cursor = conn.cursor()
                cursor.execute(r"SELECT key, value FROM configs")
                for row in cursor.fetchall():
                    key, value = row
                    if key not in configs:
                        try:
                            configs[key] = json.loads(value)
                        except Exception:
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
            r'app_name': r'MTSCOS AI 智能考试系统',
            r'app_version': r'18.0.0',
            r'app_code_name': r'EigenFlux Enhanced Intelligence Edition',
            r'debug': False,
            r'timezone': r'Asia/Shanghai',
            r'db_count': 14,
        })

        return all_configs

config_loader = ConfigLoader()

def load_db_configs():
    return config_loader.load_all()

def get_all_db_configs():
    return config_loader.configs
