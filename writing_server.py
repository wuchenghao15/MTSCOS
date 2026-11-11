#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古灵阁网文创作台 — 独立 Flask 服务
端口: 5002
依赖: flask, requests (ollama 本地 11434)
启动: python3 writing_server.py
"""
import os
import sys
import json
import time
import sqlite3
import threading
from datetime import datetime

import requests
from flask import Flask, request, jsonify, send_from_directory, Response

# ---------- 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
DB_PATH = os.path.join(BASE_DIR, 'static', 'writing_artifacts', 'writing.db')
OLLAMA_URL = 'http://127.0.0.1:11434'
DEFAULT_MODEL = 'qwen2.5:7b'
ALT_MODELS = ['qwen2.5:3b', 'qwen2.5:14b-q5', 'qwen2.5:7b']
PORT = 5002

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
app.config['JSON_AS_ASCII'] = False

# ---------- 数据库 ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS mt_writing_project
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         title TEXT, core_idea TEXT, genre TEXT, audience TEXT,
         word_count INTEGER DEFAULT 0, model_used TEXT,
         status TEXT DEFAULT 'created',
         created_at TEXT DEFAULT (datetime('now','localtime')),
         updated_at TEXT DEFAULT (datetime('now','localtime')))''')
    c.execute('''CREATE TABLE IF NOT EXISTS mt_writing_iteration
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         project_id INTEGER, iteration INTEGER,
         content TEXT, prompt_used TEXT,
         created_at TEXT DEFAULT (datetime('now','localtime')),
         FOREIGN KEY(project_id) REFERENCES mt_writing_project(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS mt_ai_brain_feed_log
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         flow_id TEXT, kind TEXT, content_preview TEXT,
         created_at TEXT DEFAULT (datetime('now','localtime')))''')
    conn.commit()
    conn.close()

# ---------- CORS ----------
@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

# ---------- Ollama 检测 ----------
def check_ollama():
    try:
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=3)
        if r.status_code == 200:
            data = r.json()
            models = [m['name'] for m in data.get('models', [])]
            return True, models
    except Exception:
        pass
    return False, []

def _ollama_stream(payload):
    """独立的流式生成器 (单独函数避免和 return 混用导致主函数变成 generator)"""
    r = requests.post(f'{OLLAMA_URL}/api/generate', json=payload, timeout=600, stream=True)
    for line in r.iter_lines():
        if line:
            yield line + b'\n'

def call_ollama(prompt, model=None, stream=False, num_predict=3000):
    if not model:
        model = DEFAULT_MODEL
    payload = {
        'model': model,
        'prompt': prompt,
        'stream': stream,
        'options': {'num_predict': num_predict, 'temperature': 0.8}
    }
    try:
        if stream:
            return _ollama_stream(payload), True  # 返回 generator 给调用方
        r = requests.post(f'{OLLAMA_URL}/api/generate', json=payload, timeout=300)
        if r.status_code == 200:
            data = r.json()
            return data.get('response', ''), True
        return f'Ollama 返回异常: HTTP {r.status_code}', False
    except requests.exceptions.ConnectionError:
        return '连接 Ollama 失败，请确认 ollama serve 正在运行', False
    except Exception as e:
        return f'Ollama 调用异常: {e}', False

# ---------- 路由 ----------
@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'writing-studio.html')

@app.route('/health')
def health():
    alive, models = check_ollama()
    return jsonify({
        'service': '古灵阁网文创作台',
        'ollama_alive': alive,
        'ollama_models': models,
        'default_model': DEFAULT_MODEL,
        'db': os.path.exists(DB_PATH),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/writing/models')
def list_models():
    alive, models = check_ollama()
    return jsonify({
        'ollama_alive': alive,
        'models': models,
        'default': DEFAULT_MODEL
    })

@app.route('/api/writing/genres')
def list_genres():
    genres = [
        '玄幻修仙','都市异能','穿越重生','科幻末世','历史架空',
        '悬疑推理','军事谍战','体育竞技','游戏竞技','二次元',
        '言情甜宠','耽美BL','百合GL','女尊','种田日常',
        '武侠江湖','奇幻魔法','蒸汽朋克','赛博朋克','灵异鬼怪',
        '纪实传记','官场商战','职场奋斗','校园青春','家庭伦理',
        '轻小说','同人衍生','快穿','系统流','无限流',
        '克苏鲁','废土','末日','星际','机甲',
        '仙侠','修真','洪荒','神话','都市',
        '高武','国术','异能','时空','位面'
    ]
    audiences = ['男频','女频','中性','青少年','成人']
    structures = ['三幕式','起承转合','英雄之旅','冰山结构','环形叙事','多线交织','POV切换']
    return jsonify({'genres': genres, 'audiences': audiences, 'structures': structures})

@app.route('/api/writing/generate', methods=['POST'])
def generate():
    data = request.get_json(force=True, silent=True) or {}
    core_idea = (data.get('core_idea') or '').strip()
    genre = data.get('genre') or '玄幻修仙'
    audience = data.get('audience') or '男频'
    title = data.get('title') or core_idea[:20] or '无题'
    structure = data.get('structure') or '起承转合'
    word_target = int(data.get('word_target') or 2000)
    model = data.get('model') or DEFAULT_MODEL
    extra_params = data.get('extra_params') or {}

    if not core_idea:
        return jsonify({'ok': False, 'error': '请输入核心创意（一句话也行）'}), 400

    # 构建 prompt
    extra_text = ''
    for k, v in extra_params.items():
        if v:
            extra_text += f'\n【{k}】{v}'

    prompt = f"""你是顶级网文写手，现在创作一部{genre}类型、面向{audience}读者的作品。

核心创意: {core_idea}
结构框架: {structure}
目标字数: {word_target} 字（尽量写足）
作品标题: {title}
{extra_text}

要求:
1. 开头3段内必须抓住读者眼球
2. 对话要自然有性格，不要干巴巴
3. 场景描写调动五感
4. 每500字左右要有一个小钩子/悬念
5. 结尾留个让读者想追下去的缺口

现在开始创作，直接输出正文，不要写前言或说明："""

    t0 = time.time()
    content, ok = call_ollama(prompt, model=model, num_predict=min(word_target * 3, 8000))
    elapsed = time.time() - t0

    # 存库
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('INSERT INTO mt_writing_project (title,core_idea,genre,audience,word_count,model_used,status) VALUES (?,?,?,?,?,?,?)',
                  (title, core_idea, genre, audience, len(content), model, 'generated'))
        pid = c.lastrowid
        c.execute('INSERT INTO mt_writing_iteration (project_id,iteration,content,prompt_used) VALUES (?,?,?,?)',
                  (pid, 1, content, prompt[:500]))
        c.execute('INSERT INTO mt_ai_brain_feed_log (flow_id,kind,content_preview) VALUES (?,?,?)',
                  (f'WRITING-{pid}', 'CULTURE_WRITING', content[:200]))
        conn.commit()
        conn.close()
    except Exception as db_err:
        print(f'[DB WARN] {db_err}')
        pid = None

    return jsonify({
        'ok': ok,
        'project_id': pid,
        'title': title,
        'content': content,
        'word_count': len(content),
        'model_used': model,
        'elapsed_seconds': round(elapsed, 1),
        'ollama_alive': True,
        'error': None if ok else content
    })

@app.route('/api/writing/revise/<int:pid>', methods=['POST'])
def revise(pid):
    data = request.get_json(force=True, silent=True) or {}
    instruction = (data.get('instruction') or '').strip()
    model = data.get('model') or DEFAULT_MODEL

    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT content,title,core_idea FROM mt_writing_iteration WHERE project_id=? ORDER BY iteration DESC LIMIT 1', (pid,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': False, 'error': '找不到项目'}), 404
        prev = row['content']
        title = row['title']
        idea = row['core_idea']
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    revise_prompt = f"""你是顶级网文编辑。以下是《{title}》（核心创意：{idea}）现有章节：

--- 原文开始 ---
{prev[:4000]}
--- 原文结束 ---

修改意见: {instruction}

请根据修改意见重写全文。保持原文优点，修正问题，提升到发表级水准。直接输出修改后的完整正文："""

    content, ok = call_ollama(revise_prompt, model=model, num_predict=min(len(prev) * 2, 8000))

    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT MAX(iteration) as mx FROM mt_writing_iteration WHERE project_id=?', (pid,))
        cur_iter = (c.fetchone()['mx'] or 0) + 1
        c.execute('INSERT INTO mt_writing_iteration (project_id,iteration,content,prompt_used) VALUES (?,?,?,?)',
                  (pid, cur_iter, content, revise_prompt[:500]))
        c.execute('UPDATE mt_writing_project SET updated_at=datetime("now","localtime"), status="revised" WHERE id=?', (pid,))
        conn.commit()
        conn.close()
    except Exception as db_err:
        print(f'[DB WARN revise] {db_err}')

    return jsonify({
        'ok': ok,
        'project_id': pid,
        'iteration': cur_iter,
        'content': content,
        'word_count': len(content),
        'error': None if ok else content
    })

@app.route('/api/writing/projects')
def list_projects():
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM mt_writing_project ORDER BY id DESC LIMIT 30')
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'ok': True, 'projects': rows})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/writing/project/<int:pid>')
def get_project(pid):
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM mt_writing_project WHERE id=?', (pid,))
        p = c.fetchone()
        if not p:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        c.execute('SELECT id,iteration,length(content) as len,created_at FROM mt_writing_iteration WHERE project_id=? ORDER BY iteration', (pid,))
        iters = [dict(r) for r in c.fetchall()]
        conn.close()
        return jsonify({'ok': True, 'project': dict(p), 'iterations': iters})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/writing/project/<int:pid>/iter/<int:iter_id>')
def get_iteration(pid, iter_id):
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM mt_writing_iteration WHERE project_id=? AND iteration=?', (pid, iter_id))
        r = c.fetchone()
        conn.close()
        if not r:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        return jsonify({'ok': True, 'content': r['content']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ---------- 启动 ----------
if __name__ == '__main__':
    init_db()
    alive, models = check_ollama()
    print(f"""
╔══════════════════════════════════════════════╗
║     📜 古灵阁网文创作台 Writing Studio        ║
╠══════════════════════════════════════════════╣
║  Flask:  http://127.0.0.1:{PORT}              ║
║  Ollama: {'✅ alive' if alive else '❌ OFFLINE':<28s}║
║  模型:   {', '.join(models[:3]) if models else '无':<28s}║
║  默认:   {DEFAULT_MODEL:<28s}║
║  DB:     {DB_PATH:<28s}║
╚══════════════════════════════════════════════╝
""")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
