#!/usr/bin/env python3
"""Minimal Flask server for login page preview - no DB required"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    from app.version import VERSION, VERSION_INFO, get_version_info, get_latest_version
except Exception:
    VERSION = '2.1.0'
    def get_version_info():
        return {
            'version': VERSION,
            'build_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'commit': 'local-preview',
            'branch': 'main',
            'author': 'Chenghao Wu',
        }
    def get_latest_version():
        return VERSION

from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.secret_key = 'mtscos-preview-secret'

@app.route('/')
def index():
    version_info = get_version_info()
    latest_version = get_latest_version()
    return render_template('index.html',
                           version=VERSION,
                           version_info=version_info,
                           latest_version=latest_version)

@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        if not username or not password:
            return jsonify({'success': False, 'message': '请输入用户名和密码'}), 400
        if username == 'admin' and password == 'admin123':
            return jsonify({'success': True, 'message': '登录成功', 'redirect': '/dashboard',
                            'user': {'username': username, 'role': 'admin'}})
        if username == 'wuchenghao15' and password == 'admin123':
            return jsonify({'success': True, 'message': '登录成功', 'redirect': '/dashboard',
                            'user': {'username': username, 'role': 'super_admin'}})
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401
    return redirect('/')

@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        if not username or not password:
            return jsonify({'success': False, 'message': '请填写用户名和密码'}), 400
        return jsonify({'success': True, 'message': '注册成功（预览模式，无需写入DB）',
                        'redirect': '/'})
    try:
        return render_template('register.html', version=VERSION)
    except Exception:
        return redirect('/')

@app.route('/dashboard')
def dashboard():
    try:
        return render_template('dashboard.html', version=VERSION)
    except Exception:
        return '<h2 style="font-family:sans-serif;padding:40px;">✅ 登录成功 · Dashboard 占位页（MTSCOS v%s）</h2><p><a href="/">返回登录</a></p>' % VERSION

@app.route('/api/health')
def health():
    return jsonify({'status': 'healthy', 'version': VERSION, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')})

if __name__ == '__main__':
    print(f'[MTSCOS Preview] Starting on http://0.0.0.0:8888  version={VERSION}')
    app.run(host='0.0.0.0', port=8888, debug=False, threaded=True)
