#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS AI 本地聊天蓝图 — 仙女座发散思维引擎
=============================================
flow_id: CHAT_LOCAL_v22_10_20261008

功能:
  1. 本地 Ollama 大模型聊天 (qwen2.5-coder:14b / qwen2.5:7b)
  2. SSE 流式推送 (Server-Sent Events, 避开 RATE_IP_001 短轮询限流)
  3. 仙女座发散思维 prompt 增强 (冰山矩阵 + 认知画像适配)
  4. 动作记录 (每次 send/receive 永久化落库)
  5. 拐点记录 (对话方向突变/情绪转折/灵感爆发)
  6. 脑库投喂 (对话结束 → 经验蒸馏 → mt_ai_brain_feed_log)

权限: @system_container(require_auth='login') — 所有已注册用户
      guest 403, 登录即可用 (role=user/admin/super_admin 全部放行)

路由:
  GET  /local-chat          → 聊天页面 (templates/local_chat.html)
  POST /api/local-chat/send → 发送消息 + SSE 流式接收
  GET  /api/local-chat/history?session_id=xxx → 拉取历史
  POST /api/local-chat/session → 创建新会话
  GET  /api/local-chat/sessions → 我的会话列表
"""
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, Response, g, jsonify, request, session, stream_with_context

# ── 路径解析 ────────────────────────────────────────────────────
_BLUEPRINT_DIR = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP_DIR = os.path.dirname(_BLUEPRINT_DIR)
_ROOT_DIR = os.path.dirname(_FLASK_APP_DIR)
_DB_PATH = os.path.join(_ROOT_DIR, "app.db")

for _d in [_FLASK_APP_DIR, _ROOT_DIR]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

chat_local_bp = Blueprint("chat_local_bp", __name__, template_folder=None)


# ════════════════════════════════════════════════════════════════
# 数据库层
# ════════════════════════════════════════════════════════════════
def _db():
    conn = sqlite3.connect(_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables():
    """确保聊天相关表存在"""
    conn = _db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            title TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            message_count INTEGER DEFAULT 0,
            last_message TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            reasoning TEXT DEFAULT '',
            tokens INTEGER DEFAULT 0,
            model TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
        );

        CREATE TABLE IF NOT EXISTS chat_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('send','receive','stream','finish','inflection','new_session')),
            detail TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS chat_inflection_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            inflection_type TEXT NOT NULL CHECK(inflection_type IN ('diverge','converge','breakthrough','question','metaphor','contradiction')),
            trigger_text TEXT DEFAULT '',
            ai_response TEXT DEFAULT '',
            quality_score REAL DEFAULT 0.0,
            fed_to_brain INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_chat_msgs_session ON chat_messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_chat_actions_session ON chat_actions(session_id);
        CREATE INDEX IF NOT EXISTS idx_chat_infl_session ON chat_inflection_points(session_id);
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);
        """)
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"[CHAT-LOCAL] _ensure_tables error: {e}\n")
    finally:
        conn.close()


_ensure_tables()


# ════════════════════════════════════════════════════════════════
# 动作记录 + 拐点记录 + 脑库投喂
# ════════════════════════════════════════════════════════════════
def _record_action(session_id, user_id, action, detail=None):
    """动作记录 → chat_actions 表"""
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO chat_actions(session_id,user_id,action,detail) VALUES(?,?,?,?)",
            (session_id, user_id, action, json.dumps(detail or {}, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _detect_inflections(session_id, user_id, user_text, ai_text):
    """拐点检测 — 识别发散思维/灵感爆发/矛盾碰撞"""
    INFLECTION_RULES = [
        ('diverge', ['如果', '假设', '想象', '倘若', '万一', '不妨', '试想']),
        ('breakthrough', ['原来如此', '恍然大悟', '灵光', '豁然开朗', '顿悟', '突破']),
        ('question', ['为什么', '怎么会', '难道', '究竟', '到底']),
        ('metaphor', ['就像', '好比', '仿佛', '如同', '类似于', '比如']),
        ('contradiction', ['但是', '不过', '然而', '但实际上', '可是']),
    ]
    points = []
    text = (user_text or '') + ' ' + (ai_text or '')
    for itype, keywords in INFLECTION_RULES:
        for kw in keywords:
            if kw in text:
                points.append({
                    'inflection_type': itype,
                    'trigger_text': kw,
                    'ai_response': (ai_text or '')[:500],
                    'quality_score': 0.6 if itype in ('breakthrough', 'diverge') else 0.4,
                })
                break  # 每种类型只记一次
    if points:
        try:
            conn = _db()
            for p in points:
                conn.execute(
                    "INSERT INTO chat_inflection_points(session_id,user_id,inflection_type,trigger_text,ai_response,quality_score) VALUES(?,?,?,?,?,?)",
                    (session_id, user_id, p['inflection_type'], p['trigger_text'], p['ai_response'], p['quality_score'])
                )
            conn.commit()
            conn.close()
        except Exception:
            pass
    return points


def _feed_brain(session_id, user_id, username, user_text, ai_text, inflection_points):
    """脑库投喂 — 对话经验蒸馏 → mt_ai_brain_feed_log"""
    try:
        # 尝试调 BrainFeedingEngine
        from engines.brain_feeding_engine import BrainFeedingEngine
        bf = BrainFeedingEngine()
        bf.feed({
            'source': 'local_chat',
            'session_id': session_id,
            'user_id': user_id,
            'username': username,
            'content': f"用户({username}): {user_text[:500]}\nAI回复: {ai_text[:500]}",
            'inflections': len(inflection_points),
            'quality': 0.7 if inflection_points else 0.5,
        })
    except Exception:
        # Fallback: 直接写 mt_ai_brain_feed_log（如果表存在）
        try:
            conn = _db()
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%brain%feed%'").fetchall()]
            if tables:
                conn.execute(
                    f"INSERT INTO {tables[0]}(source, content, created_at) VALUES(?,?,datetime('now','localtime'))",
                    ('local_chat', f"user={username}: {user_text[:200]} | ai: {ai_text[:200]}")
                )
                conn.commit()
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# 仙女座发散思维 prompt 增强
# ════════════════════════════════════════════════════════════════
def _build_divergent_prompt(user_text, username, cognitive_profile=None, history=None):
    """
    仙女座发散思维 prompt 增强层
    基于: 冰山矩阵 + 认知画像 + 对话历史 → 增强 system prompt
    """
    # 1. 基础角色
    system = """你是仙女座星系AI助手，具备发散思维引擎 (Divergent Thinking Engine)。
你的思考流程:
  1. 先快速分析用户问题的本质 (what)
  2. 从多个角度发散 (why 因果 / how 方法 / what_if 假设 / analogy 隐喻)
  3. 选出最有洞察力的 2-3 个角度深入
  4. 用结构化方式输出 (emoji + 小标题 + 简明要点)

核心原则:
  - 不停留在表面, 追问一层
  - 用类比/隐喻让抽象概念具象
  - 对"假设性"问题大胆想象 (what if)
  - 对"矛盾/反直觉"现象给出合理解释
  - 用中文回答, 语气亲切专业"""

    # 2. 认知画像适配
    cp = cognitive_profile or {}
    style = cp.get('learning_style', 'visual')
    level = cp.get('cognitive_level', 'intermediate')
    role = cp.get('role', 'student')

    STYLE_HINTS = {
        'visual': '视觉型学习者偏好: 用 emoji/列表/结构化呈现, 避免长段文字',
        'auditory': '听觉型学习者偏好: 口语化, 对话感强, 可多设问引导思考',
        'kinesthetic': '动手型学习者偏好: 给可操作步骤/小实验/实践建议',
        'reading': '阅读型学习者偏好: 深入分析, 分层次展开, 引用概念',
    }
    LEVEL_HINTS = {
        'beginner': '入门水平: 先给概念定义, 用简单类比',
        'intermediate': '中级水平: 可以讲原理, 给示例代码/公式',
        'advanced': '高级水平: 深入推导, 讨论边界case, 给拓展方向',
    }

    extra = f"\n\n当前用户 {username} ({role}):\n  学习风格={style} → {STYLE_HINTS.get(style, '')}\n  认知水平={level} → {LEVEL_HINTS.get(level, '')}"
    system += extra

    # 3. 发散触发 — 如果用户问题含"假设/如果/想象/万一", 强化发散模式
    DIVERGE_KEYWORDS = ['如果', '假设', '想象', '倘若', '万一', '不妨', '试想', 'what if', '假如']
    if any(kw in user_text.lower() for kw in DIVERGE_KEYWORDS):
        system += """

⚠️ 发散思维强化模式:
用户问题含假设/想象类关键词 → 请大胆发散, 给出 3-5 个不同可能性,
每个可能性标注 "可能性1/2/3", 最后给出你认为最有价值的那个方向。"""

    return system


def _call_ollama_stream(user_text, system_prompt, username):
    """
    直接调用本地 Ollama /api/chat (流式原生)
    仙女座发散思维 prompt 由上游 _build_divergent_prompt 生成, 完全可控
    """
    import urllib.request as _ur
    yield f"data: [thinking]\n\n"

    try:
        # Ollama 原生 /api/chat 端点 (支持 system + messages)
        body = json.dumps({
            "model": "qwen2.5:14b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": True,
            "options": {"temperature": 0.85, "top_p": 0.92, "num_predict": 1024}
        }).encode()

        req = _ur.Request(
            "http://127.0.0.1:11434/api/chat",
            data=body,
            headers={"Content-Type": "application/json"}
        )
        resp = _ur.urlopen(req, timeout=180)

        for line in resp:
            line = line.decode().strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                token = msg.get("content", "")
                if token:
                    yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
                if chunk.get("done"):
                    total_dur = chunk.get("total_duration", 0)
                    yield f"data: [done] {json.dumps({'model': 'qwen2.5:14b', 'duration_ms': total_dur//1000000 if total_dur else 0}, ensure_ascii=False)}\n\n"
                    break
            except json.JSONDecodeError:
                continue
    except Exception as e:
        yield f"data: [error] {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"


# ════════════════════════════════════════════════════════════════
# 权限装饰器
# ════════════════════════════════════════════════════════════════
def _login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        uid = session.get('user_id')
        if not uid or uid == 'guest':
            # GET 页面请求 → 302 跳登录 (保留 next 参数)
            if request.method == 'GET' and request.path.endswith('/local-chat'):
                from flask import redirect, url_for
                return redirect(f'/auth/login?next={request.path}', code=302)
            # API 请求 → 401 JSON
            return jsonify({'success': False, 'error': 'login_required', 'message': '请先登录'}), 401
        return fn(*args, **kwargs)
    return wrapper


def _get_user():
    return {
        'user_id': session.get('user_id'),
        'username': session.get('username'),
        'role': session.get('role', 'user'),
    }


def _get_cognitive_profile(user_id, username):
    """查认知画像 — 适配 caopw 问题里发现的双关联模式"""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT username, cognitive_level, learning_style, role, iceberg_layer, "
            "focus_subjects, pace_setting, ai_tutor_type "
            "FROM mt_user_cognitive_profile WHERE user_id=? OR username=? LIMIT 1",
            (str(user_id), username or '')
        ).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════
# 路由
# ════════════════════════════════════════════════════════════════

@chat_local_bp.route('/local-chat', methods=['GET'])
@_login_required
def local_chat_page():
    """聊天页面 — 仅登录用户可见"""
    from flask import render_template
    return render_template('local_chat.html')


@chat_local_bp.route('/api/local-chat/session', methods=['POST'])
@_login_required
def create_session():
    """创建新会话"""
    u = _get_user()
    sid = str(uuid.uuid4())
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = request.json.get('title', '') if request.is_json else ''
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO chat_sessions(session_id,user_id,username,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, u['user_id'], u['username'], title or f"{u['username']}的新对话", now, now)
        )
        conn.commit()
        conn.close()
        _record_action(sid, u['user_id'], 'new_session', {'username': u['username']})
        return jsonify({'success': True, 'session_id': sid, 'created_at': now})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/sessions', methods=['GET'])
@_login_required
def list_sessions():
    """我的会话列表"""
    u = _get_user()
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT session_id, title, message_count, last_message, created_at, updated_at "
            "FROM chat_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 50",
            (u['user_id'],)
        ).fetchall()
        conn.close()
        return jsonify({'success': True, 'sessions': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/history', methods=['GET'])
@_login_required
def get_history():
    """拉取会话历史"""
    u = _get_user()
    sid = request.args.get('session_id', '')
    if not sid:
        return jsonify({'success': False, 'error': 'missing session_id'}), 400
    try:
        conn = _db()
        # 权限检查: 只能看自己的会话
        row = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (sid,)
        ).fetchone()
        if not row or row['user_id'] != u['user_id']:
            conn.close()
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        msgs = conn.execute(
            "SELECT role, content, reasoning, tokens, model, created_at "
            "FROM chat_messages WHERE session_id=? ORDER BY id ASC",
            (sid,)
        ).fetchall()
        conn.close()
        return jsonify({'success': True, 'messages': [dict(m) for m in msgs]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/send', methods=['POST'])
@_login_required
def send_message():
    """
    发送消息 + SSE 流式接收 AI 回复
    请求体: {session_id, message}
    返回: SSE stream (data: {...}\n\n)
    """
    u = _get_user()
    data = request.get_json() if request.is_json else {}
    sid = data.get('session_id', '')
    user_text = (data.get('message') or '').strip()

    if not user_text:
        return jsonify({'success': False, 'error': 'empty_message'}), 400

    # 确保会话存在
    if not sid:
        sid = str(uuid.uuid4())
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = _db()
        conn.execute(
            "INSERT INTO chat_sessions(session_id,user_id,username,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, u['user_id'], u['username'], f"{u['username']}的对话", now, now)
        )
        conn.commit()
        conn.close()
        _record_action(sid, u['user_id'], 'new_session')

    # 认知画像
    cp = _get_cognitive_profile(u['user_id'], u['username'])
    system_prompt = _build_divergent_prompt(user_text, u['username'], cp)

    # 保存用户消息
    _save_message(sid, u['user_id'], 'user', user_text)
    _record_action(sid, u['user_id'], 'send', {'text_len': len(user_text)})

    # 生成 SSE 流
    def generate():
        full_response = []
        t0 = time.time()
        try:
            for chunk in _call_ollama_stream(user_text, system_prompt, u['username']):
                yield chunk
                # 收集完整回复
                if chunk.startswith('data:'):
                    payload = chunk[5:].strip()
                    if payload.startswith('['):
                        continue  # [thinking] [done] [error]
                    try:
                        d = json.loads(payload)
                        if 'token' in d:
                            full_response.append(d['token'])
                    except Exception:
                        pass
        except GeneratorExit:
            pass
        except Exception as e:
            yield f"data: [error] {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        full_ai_text = ''.join(full_response)
        duration_ms = int((time.time() - t0) * 1000)

        # 保存 AI 消息
        _save_message(sid, u['user_id'], 'assistant', full_ai_text,
                      model='qwen2.5-coder:14b', duration_ms=duration_ms)

        # 更新会话
        _update_session(sid, full_ai_text[:100])

        # 拐点检测
        inflections = _detect_inflections(sid, u['user_id'], user_text, full_ai_text)
        if inflections:
            for p in inflections:
                _record_action(sid, u['user_id'], 'inflection', p)

        # 脑库投喂 (异步触发, 不阻塞 SSE)
        try:
            import threading
            threading.Thread(target=_feed_brain, args=(
                sid, u['user_id'], u['username'], user_text, full_ai_text, inflections
            ), daemon=True).start()
        except Exception:
            pass

        _record_action(sid, u['user_id'], 'receive', {
            'duration_ms': duration_ms,
            'tokens': len(full_ai_text),
            'inflections': len(inflections),
        })

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── 内部辅助 ──────────────────────────────────────────────────────
def _save_message(session_id, user_id, role, content, reasoning='', tokens=0, model='', duration_ms=0):
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO chat_messages(session_id,user_id,role,content,reasoning,tokens,model,duration_ms) VALUES(?,?,?,?,?,?,?,?)",
            (session_id, user_id, role, content, reasoning, tokens, model, duration_ms)
        )
        # 更新会话计数
        conn.execute(
            "UPDATE chat_sessions SET message_count = message_count + 1, last_message=?, updated_at=datetime('now','localtime') WHERE session_id=?",
            (content[:100], session_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _update_session(session_id, last_msg):
    try:
        conn = _db()
        conn.execute(
            "UPDATE chat_sessions SET last_message=?, updated_at=datetime('now','localtime') WHERE session_id=?",
            (last_msg, session_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
