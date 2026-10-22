#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座 · 聊天系统补全 — flow_chat_complete_20261022
==================================================
在既有 /api/local-chat/* (会话/房间/排程/SSE/计费) 之上补齐闭环缺口:

  ① 跨会话全文检索      GET    /api/local-chat/search
  ② 消息编辑            PUT    /api/local-chat/msg/<mid>
  ③ 消息软删            DELETE /api/local-chat/msg/<mid>
  ④ 消息反馈→脑库       POST   /api/local-chat/msg/<mid>/feedback
  ⑤ 会话归档/恢复       POST   /api/local-chat/session/<sid>/archive
  ⑥ 未读统计            GET    /api/local-chat/unread
  ⑦ 标记已读            POST   /api/local-chat/session/<sid>/read
  ⑧ 会话导出 md/json    GET    /api/local-chat/session/<sid>/export
  ⑨ @天团 派单          POST   /api/local-chat/mention   (建任务大厅任务 + 分派 + 系统/AI 回帖)
  ⑩ 增强元数据          GET    /api/local-chat/plus/meta
  ⑪ AI 跳转解析         GET    /api/local-chat/jump/resolve     (任务号/天团/会话 → 目标)
  ⑫ 任务跳转详情        GET    /api/local-chat/jump/task/<id>   (面板内展示任务轨迹)

权限: 本人 / SA / 群聊房间成员; 编辑仅限本人 user 消息; 删除仅本人或 SA。
所有写操作落 chat_actions + 关键操作投喂 AI 脑库 (失败不影响主流程)。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime

from flask import Blueprint, Response, jsonify, request, session

FLOW_ID = 'flow_chat_complete_20261022'

_FA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = (os.environ.get('MTSCOS_DB_PATH')
           or os.path.join(_FA, 'database', 'app.db'))

chat_plus_bp = Blueprint('andromeda_chat_plus_bp', __name__)

_MSG_COLS = (
    ("edited_at", "TEXT"),
    ("deleted", "INTEGER DEFAULT 0"),
    ("reply_to", "INTEGER"),
    ("feedback", "INTEGER DEFAULT 0"),
    ("feedback_note", "TEXT"),
)
_SESS_COLS = (("archived", "INTEGER DEFAULT 0"),)
# @天团派单需要的任务大厅列 (旧库可能缺 hall_code 等)
_HALL_COLS = (
    ("hall_code", "TEXT"),
    ("publisher", "TEXT"),
    ("publisher_role", "TEXT"),
    ("task_type", "TEXT"),
    ("acceptance_criteria", "TEXT"),
    ("approval_status", "TEXT DEFAULT 'APPROVED'"),
    ("approved_by", "TEXT"),
    ("approved_at", "TEXT"),
)

DDL_READ = """CREATE TABLE IF NOT EXISTS chat_read_state (
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    last_read_id INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (session_id, user_id)
)"""

DDL_MENTION = """CREATE TABLE IF NOT EXISTS chat_mention_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    target TEXT NOT NULL,
    keyword TEXT,
    task_id INTEGER,
    hall_code TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)"""


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute('PRAGMA busy_timeout=15000')
    conn.row_factory = sqlite3.Row
    return conn


def _ensure() -> None:
    conn = _db()
    try:
        conn.execute(DDL_READ)
        conn.execute(DDL_MENTION)
        for table, cols in (('chat_messages', _MSG_COLS), ('chat_sessions', _SESS_COLS),
                            ('mt_lab_task_hall', _HALL_COLS)):
            have = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
            if not have:
                continue   # 表未建 (由 daemon_skill_lab_bp._ensure_claim_tables 负责)
            for name, ddl in cols:
                if name not in have:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_msgs_deleted ON chat_messages(session_id, deleted)")
        conn.commit()
    finally:
        conn.close()


def _u() -> dict:
    uid = session.get('user_id')
    return {'user_id': str(uid) if uid is not None else '',
            'username': session.get('username') or '',
            'role': session.get('role') or 'user'}


def _is_sa(u: dict) -> bool:
    return u['role'] in ('admin', 'super_admin') or u['username'] == 'wuchenghao15'


def _login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('user_id') or session.get('user_id') == 'guest':
            return jsonify({'success': False, 'error': 'login_required'}), 401
        return fn(*a, **kw)
    return wrapper


def _visible_session(conn, sid: str, u: dict) -> sqlite3.Row | None:
    row = conn.execute('SELECT * FROM chat_sessions WHERE session_id=?', (sid,)).fetchone()
    if not row:
        return None
    if _is_sa(u) or str(row['user_id']) == u['user_id']:
        return row
    cols = {r[1] for r in conn.execute('PRAGMA table_info(chat_sessions)')}
    if 'is_room' in cols and row['is_room']:
        m = conn.execute('SELECT 1 FROM mt_chat_room_members WHERE session_id=? AND user_id=?',
                         (sid, u['user_id'])).fetchone()
        if m:
            return row
    return None


def _action(conn, sid: str, uid: str, action: str, detail: dict) -> None:
    try:
        conn.execute('INSERT INTO chat_actions(session_id,user_id,action,detail) VALUES(?,?,?,?)',
                     (sid, uid, action, json.dumps(detail, ensure_ascii=False)))
    except sqlite3.Error:
        pass


def _feed(string: str, target: str, payload: str, by: str) -> None:
    try:
        conn = _db()
        try:
            conn.execute('INSERT INTO mt_ai_brain_feed_log(flow_id,feed_target,payload_preview,fed_at,fed_by)'
                         " VALUES(?,?,?,datetime('now','localtime'),?)",
                         (FLOW_ID, target, payload[:800], by or 'chat'))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


# ────────────────────────── ① 全文检索 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/search', methods=['GET'])
@_login_required
def chat_search():
    u = _u()
    q = (request.args.get('q') or '').strip()[:80]
    try:
        limit = min(max(int(request.args.get('limit', 30)), 1), 100)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'limit 须为整数'}), 400
    if not q:
        return jsonify({'success': False, 'error': 'q 不能为空'}), 400
    _ensure()
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title "
            "FROM chat_messages m JOIN chat_sessions s ON s.session_id=m.session_id "
            "WHERE (s.user_id=? OR s.session_id IN "
            "       (SELECT session_id FROM mt_chat_room_members WHERE user_id=?)) "
            "  AND COALESCE(m.deleted,0)=0 AND m.content LIKE ? "
            "ORDER BY m.id DESC LIMIT ?",
            (u['user_id'], u['user_id'], f'%{q}%', limit)).fetchall()
        items = []
        for r in rows:
            content = r['content'] or ''
            pos = content.lower().find(q.lower())
            start = max(pos - 30, 0)
            items.append({
                'id': r['id'], 'session_id': r['session_id'], 'title': r['title'],
                'role': r['role'], 'created_at': r['created_at'],
                'snippet': ('…' if start else '') + content[start:start + 140],
            })
        return jsonify({'success': True, 'q': q, 'total': len(items), 'items': items})
    finally:
        conn.close()


# ────────────────────────── ② 编辑消息 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/msg/<int:mid>', methods=['PUT'])
@_login_required
def chat_msg_edit(mid: int):
    u = _u()
    _ensure()
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'content 不能为空'}), 400
    if len(content) > 8000:
        return jsonify({'success': False, 'error': 'content 超长 (上限 8000)'}), 413
    conn = _db()
    try:
        m = conn.execute('SELECT session_id,user_id,role,content FROM chat_messages WHERE id=?',
                         (mid,)).fetchone()
        if not m:
            return jsonify({'success': False, 'error': '消息不存在'}), 404
        if m['role'] != 'user':
            return jsonify({'success': False, 'error': '仅可编辑自己发送的消息'}), 409
        if not _visible_session(conn, m['session_id'], u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        if str(m['user_id']) != u['user_id'] and not _is_sa(u):
            return jsonify({'success': False, 'error': '仅本人可编辑'}), 403
        conn.execute("UPDATE chat_messages SET content=?, edited_at=datetime('now','localtime')"
                     ' WHERE id=?', (content, mid))
        _action(conn, m['session_id'], u['user_id'], 'edit',
                {'msg_id': mid, 'old_len': len(m['content'] or ''), 'new_len': len(content)})
        conn.commit()
        return jsonify({'success': True, 'id': mid, 'content': content})
    finally:
        conn.close()


# ────────────────────────── ②b 消息列表(带 id, 供编辑/删除/反馈) ──────────────────────────
@chat_plus_bp.route('/api/local-chat/msg/list', methods=['GET'])
@_login_required
def chat_msg_list():
    u = _u()
    sid = (request.args.get('session_id') or '').strip()
    if not sid:
        return jsonify({'success': False, 'error': 'missing session_id'}), 400
    try:
        limit = min(max(int(request.args.get('limit', 100)), 1), 300)
        before = int(request.args.get('before_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'limit/before_id 须为整数'}), 400
    _ensure()
    conn = _db()
    try:
        if not _visible_session(conn, sid, u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        sql = ('SELECT id, role, content, model, tokens, created_at, edited_at, feedback, feedback_note'
               ' FROM chat_messages WHERE session_id=? AND COALESCE(deleted,0)=0')
        args = [sid]
        if before:
            sql += ' AND id < ?'
            args.append(before)
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(limit)
        rows = [dict(r) for r in conn.execute(sql, args)]
        rows.reverse()
        return jsonify({'success': True, 'session_id': sid, 'messages': rows,
                        'has_more': len(rows) == limit})
    finally:
        conn.close()


# ────────────────────────── ③ 软删消息 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/msg/<int:mid>', methods=['DELETE'])
@_login_required
def chat_msg_delete(mid: int):
    u = _u()
    _ensure()
    conn = _db()
    try:
        m = conn.execute('SELECT session_id,user_id FROM chat_messages WHERE id=?', (mid,)).fetchone()
        if not m:
            return jsonify({'success': False, 'error': '消息不存在'}), 404
        if not _visible_session(conn, m['session_id'], u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        if str(m['user_id']) != u['user_id'] and not _is_sa(u):
            return jsonify({'success': False, 'error': '仅本人或 SA 可删除'}), 403
        conn.execute("UPDATE chat_messages SET deleted=1, feedback=-1,"
                     " feedback_note='DELETED', edited_at=datetime('now','localtime') WHERE id=?", (mid,))
        _action(conn, m['session_id'], u['user_id'], 'delete', {'msg_id': mid})
        conn.commit()
        return jsonify({'success': True, 'id': mid, 'deleted': True})
    finally:
        conn.close()


# ────────────────────────── ④ 消息反馈 → 脑库 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/msg/<int:mid>/feedback', methods=['POST'])
@_login_required
def chat_msg_feedback(mid: int):
    u = _u()
    _ensure()
    data = request.get_json(silent=True) or {}
    verdict = (data.get('verdict') or '').strip().lower()
    if verdict not in ('up', 'down', 'clear'):
        return jsonify({'success': False, 'error': 'verdict 须 up/down/clear'}), 400
    note = (data.get('note') or '').strip()[:300]
    conn = _db()
    try:
        m = conn.execute('SELECT session_id,role,content,model FROM chat_messages WHERE id=?',
                         (mid,)).fetchone()
        if not m:
            return jsonify({'success': False, 'error': '消息不存在'}), 404
        if not _visible_session(conn, m['session_id'], u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        val = {'up': 1, 'down': -1, 'clear': 0}[verdict]
        conn.execute('UPDATE chat_messages SET feedback=?, feedback_note=? WHERE id=?',
                     (val, note, mid))
        _action(conn, m['session_id'], u['user_id'], 'feedback',
                {'msg_id': mid, 'verdict': verdict, 'note': note})
        conn.commit()
    finally:
        conn.close()
    if verdict != 'clear':
        _feed('chat_feedback', 'chat_feedback',
              f'[{verdict}] msg#{mid} role={m["role"]} model={m["model"]} | '
              f'{(m["content"] or "")[:200]} | note={note}', u['username'])
    return jsonify({'success': True, 'id': mid, 'feedback': val if verdict != 'clear' else 0})


# ────────────────────────── ⑤ 会话归档/恢复 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/session/<sid>/archive', methods=['POST'])
@_login_required
def chat_session_archive(sid: str):
    u = _u()
    _ensure()
    data = request.get_json(silent=True) or {}
    archived = 1 if str(data.get('archived', 1)).lower() in ('1', 'true', 'yes') else 0
    conn = _db()
    try:
        if not _visible_session(conn, sid, u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        conn.execute("UPDATE chat_sessions SET archived=?,"
                     " updated_at=datetime('now','localtime') WHERE session_id=?", (archived, sid))
        _action(conn, sid, u['user_id'], 'archive', {'archived': archived})
        conn.commit()
        return jsonify({'success': True, 'session_id': sid, 'archived': bool(archived)})
    finally:
        conn.close()


# ────────────────────────── ⑥ 未读统计 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/unread', methods=['GET'])
@_login_required
def chat_unread():
    u = _u()
    _ensure()
    conn = _db()
    try:
        sess = conn.execute(
            "SELECT s.session_id, s.title, COALESCE(s.archived,0) archived,"
            " (SELECT count(*) FROM chat_messages m WHERE m.session_id=s.session_id"
            "   AND m.role='assistant' AND COALESCE(m.deleted,0)=0"
            "   AND m.id > COALESCE((SELECT last_read_id FROM chat_read_state r"
            "                        WHERE r.session_id=s.session_id AND r.user_id=?),0)) unread,"
            " (SELECT max(id) FROM chat_messages m WHERE m.session_id=s.session_id) max_id "
            "FROM chat_sessions s WHERE s.user_id=? OR s.session_id IN "
            " (SELECT session_id FROM mt_chat_room_members WHERE user_id=?) "
            "ORDER BY unread DESC, s.updated_at DESC LIMIT 50",
            (u['user_id'], u['user_id'], u['user_id'])).fetchall()
        items = [dict(r) for r in sess]
        return jsonify({'success': True, 'total': sum(i['unread'] for i in items), 'sessions': items})
    finally:
        conn.close()


# ────────────────────────── ⑦ 标记已读 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/session/<sid>/read', methods=['POST'])
@_login_required
def chat_mark_read(sid: str):
    u = _u()
    _ensure()
    data = request.get_json(silent=True) or {}
    conn = _db()
    try:
        if not _visible_session(conn, sid, u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        last_id = data.get('last_id')
        if not last_id:
            row = conn.execute('SELECT max(id) m FROM chat_messages WHERE session_id=?', (sid,)).fetchone()
            last_id = (row['m'] or 0) if row else 0
        conn.execute('INSERT INTO chat_read_state(session_id,user_id,last_read_id) VALUES(?,?,?)'
                     ' ON CONFLICT(session_id,user_id) DO UPDATE SET'
                     " last_read_id=excluded.last_read_id, updated_at=datetime('now','localtime')",
                     (sid, u['user_id'], int(last_id)))
        conn.commit()
        return jsonify({'success': True, 'session_id': sid, 'last_read_id': int(last_id)})
    finally:
        conn.close()


# ────────────────────────── ⑧ 会话导出 ──────────────────────────
@chat_plus_bp.route('/api/local-chat/session/<sid>/export', methods=['GET'])
@_login_required
def chat_export(sid: str):
    u = _u()
    _ensure()
    fmt = (request.args.get('fmt') or 'md').lower()
    if fmt not in ('md', 'json'):
        return jsonify({'success': False, 'error': 'fmt 须 md/json'}), 400
    conn = _db()
    try:
        s = _visible_session(conn, sid, u)
        if not s:
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        msgs = conn.execute(
            'SELECT id, role, content, reasoning, model, tokens, created_at, feedback'
            ' FROM chat_messages WHERE session_id=? AND COALESCE(deleted,0)=0 ORDER BY id',
            (sid,)).fetchall()
    finally:
        conn.close()
    title = s['title'] or sid
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    if fmt == 'json':
        body = json.dumps({'session_id': sid, 'title': title,
                           'exported_at': datetime.now().isoformat(timespec='seconds'),
                           'messages': [dict(m) for m in msgs]},
                          ensure_ascii=False, indent=2)
        return Response(body, mimetype='application/json',
                        headers={'Content-Disposition': f'attachment; filename="{sid}_{stamp}.json"'})
    lines = [f'# {title}', f'', f'- 会话: {sid}', f'- 导出时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
             f'- 消息数: {len(msgs)}', '']
    who = {'user': '我', 'assistant': 'AI', 'system': '系统'}
    for m in msgs:
        lines.append(f'**{who.get(m["role"], m["role"])}** · {m["created_at"] or ""}')
        lines.append('')
        lines.append(_md_links(m['content'] or ''))
        if m['reasoning']:
            lines.append('')
            lines.append('<details><summary>思考过程</summary>')
            lines.append('')
            lines.append(m['reasoning'])
            lines.append('')
            lines.append('</details>')
        lines.append('')
    body = '\n'.join(lines)
    return Response(body, mimetype='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{sid}_{stamp}.md"'})


# ────────────────────────── ⑨ @天团 派单 ──────────────────────────
_MENTION_RE = re.compile(r'@([^\s@，,。;；:：]{1,24})')


def _teams(conn) -> list:
    try:
        rows = conn.execute('SELECT team_name, skill_keywords FROM mt_team_registry'
                            ' ORDER BY team_name').fetchall()
        return [{'name': r['team_name'], 'keywords': r['skill_keywords'] or ''} for r in rows]
    except sqlite3.Error:
        return []


# ────────────────────── ⑪ AI 跳转 (消息内可点击链接) ──────────────────────
_JUMP_RE = re.compile(r'\[\[jump\|([^|\]]{1,60})\|([a-z]+):([^\]\[]+)\]\]')


def _jump(label, kind: str, key) -> str:
    """生成跳转标记: 前端 linkify 成可点击链接, 导出 md 转 Markdown 链接"""
    def safe(s):
        return str(s).replace('|', ' ').replace('[', ' ').replace(']', ' ')
    return f'[[jump|{safe(label)}|{kind}:{safe(key)}]]'


def _jump_href(kind: str, key: str) -> str:
    from urllib.parse import quote
    if kind == 'task':
        return '/admin/center#hall-section'
    if kind == 'team':
        return '/local-chat?team=' + quote(key)
    if kind == 'center':
        return '/local-chat?center=' + quote(key)
    if kind == 'session':
        return '/local-chat?sid=' + quote(key)
    return '/'


def _md_links(text: str) -> str:
    """导出 md 时把 [[jump|标签|kind:key]] 还原为标准 Markdown 链接"""
    return _JUMP_RE.sub(
        lambda m: f'[{m.group(1)}]({_jump_href(m.group(2), m.group(3))})', text or '')


@chat_plus_bp.route('/api/local-chat/jump/resolve', methods=['GET'])
@_login_required
def chat_jump_resolve():
    """把消息里的任务号 / @天团 / 会话号解析成可跳转目标"""
    kind = (request.args.get('kind') or '').strip()
    key = (request.args.get('key') or '').strip()
    if kind not in ('task', 'team', 'session') or not key:
        return jsonify({'success': False, 'error': 'kind 须 task/team/session 且 key 非空'}), 400
    u = _u()
    _ensure()
    conn = _db()
    try:
        if kind == 'task':
            row = None
            try:
                if key.isdigit():
                    row = conn.execute('SELECT * FROM mt_lab_task_hall WHERE id=?',
                                       (int(key),)).fetchone()
                if not row:
                    row = conn.execute('SELECT * FROM mt_lab_task_hall WHERE hall_code=?',
                                       (key,)).fetchone()
            except sqlite3.Error:
                row = None
            if not row:
                return jsonify({'success': False, 'error': '任务不存在或未同步到本机',
                                'kind': kind, 'key': key}), 404
            hall_code = row['hall_code'] if 'hall_code' in row.keys() else key
            return jsonify({'success': True, 'kind': 'task', 'task_id': row['id'],
                            'hall_code': hall_code,
                            'title': row['title'] if 'title' in row.keys() else '',
                            'href': _jump_href('task', str(row['id']))})
        if kind == 'team':
            name = key[1:] if key.startswith('@') else key
            hit = None
            for t in _teams(conn):
                if t['name'] == name or name in t['name'] or t['name'] in name:
                    hit = t
                    break
            real = (hit or {}).get('name') or name
            return jsonify({'success': True, 'kind': 'team', 'name': real,
                            'matched': bool(hit), 'href': _jump_href('team', real)})
        if not _visible_session(conn, key, u):
            return jsonify({'success': False, 'error': '无权访问该会话'}), 403
        return jsonify({'success': True, 'kind': 'session', 'session_id': key,
                        'href': _jump_href('session', key)})
    finally:
        conn.close()


@chat_plus_bp.route('/api/local-chat/jump/center', methods=['GET'])
@_login_required
def chat_jump_center():
    """任务中心详情: 各状态任务数 + 近期任务 (任务大厅中心名可点击进入)"""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'name 不能为空'}), 400
    _ensure()
    conn = _db()
    try:
        center = None
        try:
            for r in conn.execute('SELECT id,name FROM mt_lab_centers'):
                if r['name'] == name or name in r['name'] or r['name'] in name:
                    center = dict(r)
                    break
        except sqlite3.Error:
            pass
        if not center:
            return jsonify({'success': False, 'error': '未找到任务中心: ' + name}), 404
        stats, tasks = {}, []
        try:
            for r in conn.execute('SELECT status,COUNT(*) c FROM mt_lab_task_hall'
                                  ' WHERE center_id=? GROUP BY status', (center['id'],)):
                stats[r['status']] = r['c']
        except sqlite3.Error:
            pass
        try:
            tasks = [dict(r) for r in conn.execute(
                'SELECT id,hall_code,title,status,priority,created_at FROM mt_lab_task_hall'
                ' WHERE center_id=? ORDER BY id DESC LIMIT 8', (center['id'],))]
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return jsonify({'success': True, 'center': center, 'stats': stats, 'tasks': tasks,
                    'total': sum(stats.values()), 'href': _jump_href('center', center['name'])})


@chat_plus_bp.route('/api/local-chat/jump/team', methods=['GET'])
@_login_required
def chat_jump_team():
    """天团详情: 名称/关键词/成员/近期承接任务 (供聊天面板内展示, 不跳空白页)"""
    name = (request.args.get('name') or '').strip().lstrip('@')
    if not name:
        return jsonify({'success': False, 'error': 'name 不能为空'}), 400
    _ensure()
    conn = _db()
    try:
        meta, real = None, name
        try:
            for r in conn.execute('SELECT team_name,member_count,skill_keywords,color_tag'
                                  ' FROM mt_team_registry'):
                if r['team_name'] == name or name in r['team_name'] or r['team_name'] in name:
                    meta, real = dict(r), r['team_name']
                    break
        except sqlite3.Error:
            pass
        members = []
        try:
            members = [dict(r) for r in conn.execute(
                'SELECT member_name,skill_level,capabilities FROM mt_team_members'
                ' WHERE team_name=? ORDER BY id LIMIT 40', (real,))]
        except sqlite3.Error:
            pass
        tasks = []
        try:
            tasks = [dict(r) for r in conn.execute(
                'SELECT id,hall_code,title,status,created_at FROM mt_lab_task_hall'
                ' WHERE center_id IN (SELECT id FROM mt_lab_centers WHERE name=?)'
                ' ORDER BY id DESC LIMIT 5', (real,))]
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    if not meta and not members:
        return jsonify({'success': False, 'error': '未找到天团: ' + name}), 404
    return jsonify({'success': True, 'team': meta or {'team_name': real}, 'name': real,
                    'members': members, 'tasks': tasks,
                    'href': _jump_href('team', real)})


@chat_plus_bp.route('/api/local-chat/jump/task/<int:task_id>', methods=['GET'])
@_login_required
def chat_jump_task(task_id: int):
    """任务跳转详情: 基础信息 + 状态机轨迹 (供聊天面板内展示)"""
    _ensure()
    conn = _db()
    try:
        try:
            t = conn.execute('SELECT * FROM mt_lab_task_hall WHERE id=?', (task_id,)).fetchone()
        except sqlite3.Error:
            t = None
        if not t:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
        task = dict(t)
        center = ''
        try:
            c = conn.execute('SELECT name FROM mt_lab_centers WHERE id=?',
                             (task.get('center_id'),)).fetchone()
            center = c['name'] if c else ''
        except sqlite3.Error:
            pass
        events = []
        try:
            events = [dict(r) for r in conn.execute(
                'SELECT event,actor,actor_role,note,created_at FROM mt_lab_task_events'
                ' WHERE hall_task_id=? ORDER BY id DESC LIMIT 40', (task_id,))]
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return jsonify({'success': True, 'task': task, 'center': center, 'events': events,
                    'href': _jump_href('task', str(task_id))})


@chat_plus_bp.route('/api/local-chat/plus/meta', methods=['GET'])
@_login_required
def chat_plus_meta():
    _ensure()
    conn = _db()
    try:
        teams = _teams(conn)
    finally:
        conn.close()
    return jsonify({'success': True, 'features': [
        'search', 'msg_edit', 'msg_delete', 'feedback', 'session_archive',
        'unread', 'mark_read', 'export', 'mention_dispatch', 'jump'], 'teams': teams})


@chat_plus_bp.route('/api/local-chat/mention', methods=['POST'])
@_login_required
def chat_mention():
    """把聊天里 @天团 的内容一键派成任务大厅任务, 并回帖系统消息"""
    u = _u()
    _ensure()
    data = request.get_json(silent=True) or {}
    sid = (data.get('session_id') or '').strip()
    text = (data.get('text') or '').strip()
    if not sid or not text:
        return jsonify({'success': False, 'error': '需 session_id + text'}), 400
    conn = _db()
    try:
        if not _visible_session(conn, sid, u):
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        teams = _teams(conn)
    finally:
        conn.close()
    names = _MENTION_RE.findall(text)
    if not names and '@' not in text:
        return jsonify({'success': False, 'error': '未识别到 @天团, 例: @安全天团 排查登录异常'}), 400
    matched = []

    def _short(raw):
        """去掉天团名前的 emoji/符号, 便于 @合规安全天团 也能命中"""
        return re.sub(r'^[^0-9A-Za-z\u4e00-\u9fa5]+', '', raw or '').strip()

    for t in teams:
        sname = _short(t['name'])
        cands = [t['name'], sname] + ([sname.split(' ')[0]] if ' ' in sname else [])
        for cand in cands:
            if not cand:
                continue
            hit = ('@' + cand) in text or any(
                n == cand or n in cand or cand in n for n in names)
            if hit and t['name'] not in [m['name'] for m in matched]:
                matched.append(t)
                break
    if not matched:
        return jsonify({'success': False, 'error': f'未匹配到天团: {", ".join(names) or text[:20]}',
                        'teams': [t['name'] for t in teams]}), 404

    try:
        from blueprints.daemon_skill_lab_bp import _ensure_claim_tables, _hall_dispatch_one
    except Exception:
        _ensure_claim_tables = None
        _hall_dispatch_one = None
    if _ensure_claim_tables:
        try:
            _ensure_claim_tables()
        except Exception:
            pass

    created = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = _db()
    try:
        for t in matched[:3]:
            title = f'[聊天派单] @{t["name"]} {text[:80]}'
            desc = f'来源会话 {sid}\n派单人 {u["username"]}\n原文: {text[:400]}'
            code_row = conn.execute(
                "SELECT count(*) n FROM mt_lab_task_hall WHERE hall_code LIKE ?",
                ('TH-' + datetime.now().strftime('%Y%m%d') + '-%',)).fetchone()
            code = 'TH-' + datetime.now().strftime('%Y%m%d') + '-' + f'{int(code_row["n"]) + 1:04d}'
            cur = conn.execute(
                'INSERT INTO mt_lab_task_hall (title,description,source,source_id,priority,status,'
                'hall_code,publisher,publisher_role,task_type,acceptance_criteria,'
                'approval_status,approved_by,approved_at,updated_at)'
                " VALUES (?,?,'chat_mention',?, 'NORMAL','QUEUED',?,?,?,?,?,?,?,?,"
                " datetime('now','localtime'))",
                (title[:120], desc[:500], sid, code, u['username'], u['role'],
                 'OTHER', '天团在聊天内给出可执行结论/代码/方案, 并回帖到会话', 'APPROVED',
                 u['username'], now))
            task_id = cur.lastrowid
            conn.commit()   # 先落库释放写锁, 否则 _hall_dispatch_one 独立连接会 database is locked
            task = {'id': task_id, 'title': title, 'description': desc, 'source_id': None,
                    'priority': 'NORMAL', 'source': 'chat_mention'}
            dispatch, dispatch_err = None, ''
            if _hall_dispatch_one:
                try:
                    dispatch = _hall_dispatch_one(task)
                except Exception as _de:
                    dispatch_err = str(_de)[:120]
            conn.execute('INSERT INTO chat_mention_log(session_id,user_id,target,keyword,task_id,hall_code)'
                         ' VALUES(?,?,?,?,?,?)',
                         (sid, u['user_id'], t['name'], text[:120], task_id, code))
            created.append({'team': t['name'], 'task_id': task_id, 'hall_code': code,
                            'center': (dispatch or {}).get('center'),
                            'status': (dispatch or {}).get('status') or 'QUEUED',
                            'dispatch': dispatch, 'dispatch_error': dispatch_err,
                            'href': _jump_href('task', str(task_id)),
                            'team_href': _jump_href('team', t['name'])})
        # ① 系统消息: 任务号/中心均为可点击跳转标记 (@天团 由前端 linkify 自动识别)
        lines = []
        for c in created:
            seg = [f'@{c["team"]}', _jump(c['hall_code'], 'task', str(c['task_id'])), '→',
                   (_jump(c['center'], 'center', c['center']) if c['center'] else '待分派'),
                   f'[{c["status"]}]']
            if c.get('dispatch_error'):
                seg.append('⚠️ 分派异常: ' + c['dispatch_error'])
            lines.append(' '.join(seg))
        reply = '【仙女座介入】已派单 ' + str(len(created)) + ' 条:\n' + '\n'.join(lines)
        conn.execute("INSERT INTO chat_messages(session_id,user_id,role,content,model) VALUES(?,?,?,?,?)",
                     (sid, 0, 'system', reply, 'andromeda'))
        # ② AI 消息: 天团实际承接结果 (员工/判定), 让用户看到 AI 真的接手了
        emp = []
        for c in created:
            for e in ((c.get('dispatch') or {}).get('employees') or [])[:6]:
                if e not in emp:
                    emp.append(e)
        ai_note = ('天团已接手: ' + ('、'.join(emp) if emp else '本机暂无空闲员工, 任务已入队等待认领')
                   + '。任务: ' + '；'.join(
                       f'{_jump(c["hall_code"], "task", str(c["task_id"]))} → '
                       + (_jump(c['center'], 'center', c['center']) if c['center'] else '待分派')
                       for c in created)
                   + '。点击任务号看状态机轨迹, 点中心看该中心任务池。')
        conn.execute("INSERT INTO chat_messages(session_id,user_id,role,content,model) VALUES(?,?,?,?,?)",
                     (sid, 0, 'assistant', ai_note, 'andromeda'))
        conn.execute("UPDATE chat_sessions SET last_message=?, message_count=message_count+2,"
                     " updated_at=datetime('now','localtime') WHERE session_id=?", (ai_note[:200], sid))
        _action(conn, sid, u['user_id'], 'mention', {'tasks': created})
        conn.commit()
    finally:
        conn.close()
    _feed('chat_mention', 'chat_mention',
          f'{u["username"]} 在 {sid} @{",".join(c["team"] for c in created)} '
          f'→ {",".join(c["hall_code"] for c in created)} | {text[:200]}', u['username'])
    return jsonify({'success': True, 'created': created, 'reply': reply})
