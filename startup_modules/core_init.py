#!/usr/bin/env python3
"""
核心初始化模块 - 4步骤初始化
负责Flask应用创建和核心配置
"""

import os
import sys
import sqlite3
import urllib.parse
from flask import Flask, render_template, send_from_directory, request
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, 'split_databases')

def core_initialization(config=None):
    if not config:
        config = {}
    
    app = Flask(__name__, 
                template_folder=os.path.join(BASE_DIR, 'Logs', 'html_files'),
                static_folder=os.path.join(BASE_DIR, 'Logs'))
    
    app.config['DEBUG'] = config.get('debug', False)
    app.config['SECRET_KEY'] = config.get('secret_key', 'mtscos_secret_key_2026')
    app.config['SPLIT_DB_DIR'] = DB_DIR
    app.config['STATIC_URL_PATH'] = '/static'
    
    os.makedirs(DB_DIR, exist_ok=True)
    
    CORS(app, resources={r'/api/*': {'origins': '*'}})
    
    @app.template_global(name='get_config')
    def get_config(key, default=None):
        return config.get(key, default)
    
    @app.template_global(name='config')
    def get_config_obj():
        return config
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/index.html')
    def index_html():
        return render_template('index.html')
    
    @app.route('/css_files/<filename>')
    def css_files(filename):
        return send_from_directory(os.path.join(BASE_DIR, 'Logs', 'css_files'), filename)
    
    @app.route('/js_files/<filename>')
    def js_files(filename):
        return send_from_directory(os.path.join(BASE_DIR, 'Logs', 'js_files'), filename)
    
    @app.route('/login_system/<filename>')
    def login_system_files(filename):
        return send_from_directory(os.path.join(BASE_DIR, 'Logs', 'login_system'), filename)
    
    @app.route('/html_files/<filename>')
    def html_files(filename):
        return send_from_directory(os.path.join(BASE_DIR, 'Logs', 'html_files'), filename)
    
    @app.route('/static/css/<filename>')
    def static_css(filename):
        css_dirs = ['css_files', 'login_system', '系统监控', 'Arduino模块', '其他日志']
        for css_dir in css_dirs:
            css_path = os.path.join(BASE_DIR, 'Logs', css_dir, filename)
            if os.path.exists(css_path):
                with open(css_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return app.response_class(content, mimetype='text/css')
        return '', 404
    
    @app.route('/static/js/<filename>')
    def static_js(filename):
        js_path = os.path.join(BASE_DIR, 'Logs', 'js_files', filename)
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return app.response_class(content, mimetype='application/javascript')
        js_path = os.path.join(BASE_DIR, 'Logs', 'login_system', filename)
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return app.response_class(content, mimetype='application/javascript')
        return '', 404
    
    @app.route('/static/<path:filepath>')
    def static_files(filepath):
        file_path = os.path.join(BASE_DIR, 'Logs', filepath)
        if os.path.exists(file_path):
            import mimetypes
            mime_type, _ = mimetypes.guess_type(file_path)
            with open(file_path, 'rb') as f:
                content = f.read()
            return app.response_class(content, mimetype=mime_type or 'application/octet-stream')
        return '', 404
    
    _init_database_connections(app)
    
    return app

def _init_database_connections(app):
    DATABASES = {
        'auth': os.path.join(DB_DIR, 'auth.db'),
        'exam': os.path.join(DB_DIR, 'exam.db'),
        'question': os.path.join(DB_DIR, 'question.db'),
        'learning': os.path.join(DB_DIR, 'learning.db'),
        'system': os.path.join(DB_DIR, 'system.db'),
        'ai': os.path.join(DB_DIR, 'ai.db'),
        'physics': os.path.join(DB_DIR, 'physics.db'),
        'math': os.path.join(DB_DIR, 'math.db'),
        'admin': os.path.join(DB_DIR, 'admin.db'),
        'proctor': os.path.join(DB_DIR, 'proctor.db'),
        'user': os.path.join(DB_DIR, 'user.db'),
        'log': os.path.join(DB_DIR, 'log.db'),
        'other': os.path.join(DB_DIR, 'other.db'),
        'config': os.path.join(DB_DIR, 'config.db'),
    }
    
    app.config['DATABASES'] = DATABASES
    
    TABLE_TO_DB = {}
    for db_name, db_path in DATABASES.items():
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [t[0] for t in cursor.fetchall()]
                conn.close()
                for table in tables:
                    TABLE_TO_DB[table] = db_name
            except:
                pass
    
    app.config['TABLE_TO_DB'] = TABLE_TO_DB
