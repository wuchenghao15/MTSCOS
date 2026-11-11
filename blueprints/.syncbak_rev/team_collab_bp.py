# -*- coding: utf-8 -*-
"""
跨团队协作总线 API (flow_team_collab_20261022)
================================================
目标: 任务中心自动分单后, 各天团/专家组/顾问/仙女座天团在同一频道实时互通,
      杜绝各自为战、信息闭塞、闭门造车。

API:
  GET  /api/collab/overview                 — 总线总览 (频道/消息/沉默告警)
  GET  /api/collab/channels?status=ACTIVE   — 频道列表
  GET  /api/collab/channel/<cid>            — 单频道详情 (消息 + 参与度)
  GET  /api/collab/feed?limit=50            — 跨频道实时消息流 (看板用)
  POST /api/collab/channel/<cid>/say        — 人工/AI 发帖 (progress|question|suggestion|guess|risk)
  POST /api/collab/pulse                    — 手动推进一轮 (cron/daemon 亦可)
  POST /api/collab/rebuild                  — 回填在办任务频道
"""
import json
import os
import sqlite3

from flask import Blueprint, jsonify, request

from blueprints.chat_local_bp import _login_required, _get_user

team_collab_bp = Blueprint('team_collab_bp', __name__, template_folder=None)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_DB = os.path.join(_APP_DIR, 'database', 'app.db')
FLOW_ID = 'flow_team_collab_20261022'
ALLOWED_TYPES = ('progress', 'question', 'suggestion', 'guess', 'risk')


def _db():
    conn = sqlite3.connect(MAIN_DB, timeout=20)
    conn.execute('PRAGMA busy_timeout=15000')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _row(r):
    return dict(r) if r is not None else None


@team_collab_bp.route('/api/collab/overview')
@_login_required
def collab_overview():
    conn = _db()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM mt_collab_channel WHERE status='ACTIVE'").fetchone()[0]
        msgs = conn.execute('SELECT COUNT(*) FROM mt_collab_message').fetchone()[0]
        silent = conn.execute(
            'SELECT COUNT(*) FROM mt_collab_participation WHERE silent_flag=1').fetchone()[0]
        by_type = {r[0]: r[1] for r in conn.execute(
            'SELECT msg_type, COUNT(*) FROM mt_collab_message GROUP BY msg_type')}
        hosts = [dict(r) for r in conn.execute(
            "SELECT host_team, COUNT(*) n FROM mt_collab_channel WHERE status='ACTIVE' "
            'GROUP BY host_team ORDER BY n DESC LIMIT 10')]
        return jsonify({'ok': True, 'flow_id': FLOW_ID, 'active_channels': active,
                        'messages': msgs, 'silent': silent, 'by_type': by_type,
                        'hosts': hosts})
    except sqlite3.Error as e:
        return jsonify({'ok': False, 'error': str(e), 'hint': '先跑 blueprints/../engines/ai_team_collab_engine.py --init'}), 500
    finally:
        conn.close()


@team_collab_bp.route('/api/collab/channels')
@_login_required
def collab_channels():
    status = (request.args.get('status') or 'ACTIVE').upper()
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            'SELECT c.*, (SELECT COUNT(*) FROM mt_collab_participation p '
            'WHERE p.channel_id=c.channel_id) AS participants, '
            '(SELECT COUNT(*) FROM mt_collab_participation p2 WHERE p2.channel_id=c.channel_id '
            'AND p2.silent_flag=1) AS silent FROM mt_collab_channel c '
            'WHERE c.status=? ORDER BY c.last_activity_at DESC LIMIT 100', (status,))]
        return jsonify({'ok': True, 'count': len(rows), 'channels': rows})
    except sqlite3.Error as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@team_collab_bp.route('/api/collab/channel/<int:cid>')
@_login_required
def collab_channel(cid):
    conn = _db()
    try:
        ch = _row(conn.execute('SELECT * FROM mt_collab_channel WHERE channel_id=?', (cid,)).fetchone())
        if not ch:
            return jsonify({'ok': False, 'error': 'channel not found'}), 404
        parts = [dict(r) for r in conn.execute(
            'SELECT * FROM mt_collab_participation WHERE channel_id=? '
            'ORDER BY spoke_count DESC, actor', (cid,))]
        msgs = [dict(r) for r in conn.execute(
            'SELECT * FROM mt_collab_message WHERE channel_id=? ORDER BY msg_id DESC LIMIT 200',
            (cid,))]
        return jsonify({'ok': True, 'channel': ch, 'participants': parts,
                        'messages': list(reversed(msgs))})
    except sqlite3.Error as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@team_collab_bp.route('/api/collab/feed')
@_login_required
def collab_feed():
    limit = min(int(request.args.get('limit') or 50), 200)
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            'SELECT m.msg_id, m.channel_id, c.title AS task_title, m.actor, m.actor_type, '
            'm.msg_type, m.content, m.created_at FROM mt_collab_message m '
            'LEFT JOIN mt_collab_channel c ON c.channel_id=m.channel_id '
            'ORDER BY m.msg_id DESC LIMIT ?', (limit,))]
        return jsonify({'ok': True, 'count': len(rows), 'feed': list(reversed(rows))})
    except sqlite3.Error as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@team_collab_bp.route('/api/collab/channel/<int:cid>/say', methods=['POST'])
@_login_required
def collab_say(cid):
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': 'content required'}), 400
    mtype = (data.get('msg_type') or 'progress').lower()
    if mtype not in ALLOWED_TYPES:
        return jsonify({'ok': False, 'error': 'msg_type must be %s' % (ALLOWED_TYPES,)}), 400
    user = _get_user() or {}
    actor = data.get('actor') or user.get('username') or 'human'
    conn = _db()
    try:
        if not conn.execute('SELECT 1 FROM mt_collab_channel WHERE channel_id=?', (cid,)).fetchone():
            return jsonify({'ok': False, 'error': 'channel not found'}), 404
        cur = conn.execute(
            'INSERT INTO mt_collab_message (channel_id,actor,actor_type,msg_type,content,flow_id) '
            'VALUES (?,?,?,?,?,?)', (cid, actor, 'human', mtype, content, FLOW_ID))
        conn.execute(
            'INSERT OR IGNORE INTO mt_collab_participation (channel_id,actor,actor_type,must_speak) '
            "VALUES (?,?,'human',1)", (cid, actor))
        conn.execute(
            "UPDATE mt_collab_participation SET spoke_count=spoke_count+1, "
            "last_spoke_at=datetime('now','localtime'), silent_flag=0, "
            "updated_at=datetime('now','localtime') WHERE channel_id=? AND actor=?", (cid, actor))
        conn.execute(
            "UPDATE mt_collab_channel SET msg_count=msg_count+1, "
            "last_activity_at=datetime('now','localtime'), updated_at=datetime('now','localtime') "
            'WHERE channel_id=?', (cid,))
        conn.commit()
        return jsonify({'ok': True, 'msg_id': cur.lastrowid})
    except sqlite3.Error as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@team_collab_bp.route('/api/collab/pulse', methods=['POST'])
@_login_required
def collab_pulse():
    try:
        from engines.ai_team_collab_engine import init_tables, pulse
        init_tables()
        return jsonify({'ok': True, 'pulse': pulse()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@team_collab_bp.route('/api/collab/rebuild', methods=['POST'])
@_login_required
def collab_rebuild():
    try:
        from engines.ai_team_collab_engine import init_tables, backfill
        init_tables()
        opened = backfill()
        return jsonify({'ok': True, 'opened': len(opened), 'channels': opened})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
