#!/usr/bin/env python3
"""
MTSCOS AI · 开发机维护专用主页 (端口 1988)
=========================================
- 仅开发机 DEV 模式启动
- localhost only (127.0.0.1:1988)
- 功能: 系统状态 / daemon 管理 / AI 引擎 / 规则巡检 / DB 健康
"""
import os
import sys

# ── 强制 DEV 模式 ──
os.environ['NODE_ROLE'] = 'DEV'
os.environ['MTSCOS_MAINT_PORT'] = '1988'

from flask import Flask, render_template, jsonify, request
from pathlib import Path

# ── 路径 ──
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# ── 独立 Flask App ──
app = Flask(__name__,
            template_folder=str(BASE / 'templates'),
            static_folder=str(BASE / 'static'))

@app.route('/')
def maintenance_home():
    """开发机维护主页 — 极简数据面板"""
    try:
        import sqlite3, json
        db_path = BASE / 'engines' / 'app.db'
        stats = {}
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            # daemon_registry
            cur = conn.execute("SELECT COUNT(*) FROM daemon_registry")
            stats['daemon_total'] = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM daemon_registry WHERE status='RUNNING'")
            stats['daemon_running'] = cur.fetchone()[0]
            # AI 员工
            cur = conn.execute("SELECT COUNT(*) FROM ai_employees")
            stats['ai_employees'] = cur.fetchone()[0]
            conn.close()
        else:
            stats = {'daemon_total': 0, 'daemon_running': 0, 'ai_employees': 0}
    except Exception as e:
        stats = {'error': str(e)}
    
    return render_template('maintenance_home.html', stats=stats)

@app.route('/api/health')
def health():
    return jsonify({
        'port': 1988,
        'role': 'DEV-only',
        'maintenance': True,
        'pid': os.getpid()
    })

if __name__ == '__main__':
    port = int(os.environ.get('MAINT_PORT', 1988))
    print(f"""
╔═══════════════════════════════════════════════╗
║  MTSCOS AI · 开发机维护专用主页                   ║
║  http://127.0.0.1:{port}/                      ║
║  localhost ONLY · DEV mode                      ║
╚═══════════════════════════════════════════════╝
""")
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
