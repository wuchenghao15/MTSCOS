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
    VERSION = '17.22.0'
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


def _default_homepage_stats():
    stats = {
        'version': VERSION or '17.22.0',
        'modules_count': 42,
        'availability': '99.9',
        'rules_count': 925,
        'avg_response_ms': 14,
        'scoring_consistency': '99.97',
        'questions_count': 323,
        'users_count': 8,
        'exams_count': 8,
        'ai_employees_count': 41,
    }
    try:
        from core.db_path import get_db_path
        import sqlite3
        p = get_db_path('app.db')
        if os.path.exists(p):
            c = sqlite3.connect(p)
            for (tbl, k) in [('users', 'users_count'), ('questions', 'questions_count'),
                             ('exams', 'exams_count'), ('ai_employees', 'ai_employees_count')]:
                try:
                    r = c.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
                    if r: stats[k] = r[0] or stats[k]
                except Exception:
                    pass
            try:
                cur = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='system_rules'").fetchone()
                if cur and cur[0]:
                    rc = c.execute('SELECT COUNT(*) FROM system_rules').fetchone()
                    if rc and rc[0] > 0:
                        stats['rules_count'] = max(stats['rules_count'], rc[0])
            except Exception:
                pass
            c.close()
    except Exception:
        pass
    stats['modules'] = stats['modules_count']
    stats['questions'] = stats['questions_count']
    stats['rules'] = stats['rules_count']
    stats['latency'] = stats['avg_response_ms']
    stats['consistency'] = stats['scoring_consistency']
    return stats


@app.route('/')
def index():
    version_info = get_version_info()
    latest_version = get_latest_version()
    stats = _default_homepage_stats()
    return render_template('index.html',
                           version=VERSION,
                           version_info=version_info,
                           latest_version=latest_version,
                           homepage_stats=stats,
                           _s=stats)


@app.route('/api/homepage/stats')
def api_homepage_stats():
    try:
        return jsonify({'success': True, 'stats': _default_homepage_stats()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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
