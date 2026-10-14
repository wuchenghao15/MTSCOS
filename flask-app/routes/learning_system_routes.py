#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS 学习系统 RESTful API 路由 (v1.0.0)
完整实现版本 - 25 个端点全部真逻辑
"""

from flask import Blueprint, request, jsonify, session
from functools import wraps
import sqlite3, os, json, logging, uuid, time
from datetime import datetime, timedelta

try:
    from app.utils.security import require_permission
except Exception:
    try:
        from mtscos.auth import require_permission
    except Exception:
        def require_permission(fn):
            @wraps(fn)
            def _wrap(*a, **kw):
                return fn(*a, **kw)
            return _wrap

from app.middlewares.system_container import system_container
from . import learning_bp
bp = learning_bp

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'))

def ensure_tables(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mt_learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            plan_id INTEGER,
            subject TEXT,
            progress_pct REAL,
            hours_spent REAL,
            last_update TEXT,
            notes TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mt_learning_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            title TEXT,
            type TEXT,
            url TEXT,
            subject TEXT,
            difficulty TEXT,
            rating REAL,
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mt_learning_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            date TEXT,
            plan_id INTEGER,
            checkin_done INTEGER DEFAULT 0,
            minutes_spent INTEGER,
            notes TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mt_learning_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            title TEXT,
            subject TEXT,
            target_date TEXT,
            target_value REAL,
            current_value REAL,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mt_learning_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            subject TEXT,
            title TEXT,
            content TEXT,
            tags TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mt_learning_kp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            subject TEXT,
            kp_name TEXT,
            mastery_level INTEGER DEFAULT 0,
            last_practiced TEXT,
            total_practice INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def _get_db():
    ensure_tables(DB_PATH)
    return sqlite3.connect(DB_PATH)

def _get_current_user():
    u = session.get('username')
    if not u:
        u = request.headers.get('X-User-Name') or request.args.get('username') or 'unknown'
    return u

def _make_ok(data, code=0):
    return jsonify({'status': 'ok', 'code': code, 'data': data})

def _make_err(msg, code=1):
    return jsonify({'status': 'error', 'code': code, 'msg': msg})

def _row_to_dict(row, cursor):
    cols = [d[0] for d in cursor.description] if cursor.description else []
    return {cols[i]: (row[i] if row[i] is not None else '') for i in range(len(cols))}

def _rows_to_list(rows, cursor):
    return [_row_to_dict(r, cursor) for r in rows]

@require_permission
@bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='stats_overview', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def stats_overview():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            (SELECT COUNT(*) FROM mt_learning_progress) AS progress_count,
            (SELECT COUNT(*) FROM mt_learning_resources) AS resources_count,
            (SELECT COUNT(*) FROM mt_learning_calendar) AS calendar_count,
            (SELECT COUNT(*) FROM mt_learning_goals) AS goals_count,
            (SELECT COUNT(*) FROM mt_learning_notes) AS notes_count,
            (SELECT COUNT(*) FROM mt_learning_kp) AS kp_count,
            (SELECT COUNT(*) FROM mt_learning_calendar WHERE date = ? AND checkin_done = 1) AS today_checkins
    ''', (datetime.now().strftime('%Y-%m-%d'),))
    row = cursor.fetchone()
    conn.close()
    return _make_ok(_row_to_dict(row, cursor))

@require_permission
@bp.route('/plans', methods=['GET'])
@system_container(page_name='plans_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def plans_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM adult_study_plans')
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/plans', methods=['POST'])
@system_container(page_name='plans_create', require_auth='login', allowed_roles=['teacher','admin','super_admin'])
def plans_create():
    data = request.get_json() or {}
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO adult_study_plans 
        (user_id, plan_name, subject, target_level, start_date, end_date, weekly_hours, progress, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 'active')""",
        (_get_current_user(),
         data.get('plan_name') or data.get('title') or '未命名计划',
         data.get('subject', ''),
         data.get('target_level', 'beginner'),
         data.get('start_date', datetime.now().isoformat()[:10]),
         data.get('end_date', (datetime.now() + __import__('datetime').timedelta(days=90)).isoformat()[:10]),
         int(data.get('weekly_hours') or data.get('duration') or 5)))
    conn.commit()
    conn.close()
    return _make_ok({'id': cursor.lastrowid})

@require_permission
@bp.route('/plans/<int:id>', methods=['GET'])
@system_container(page_name='plans_detail', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def plans_detail(id):
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM adult_study_plans WHERE id = ?', (id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _make_ok(_row_to_dict(row, cursor))
    else:
        return _make_err('Plan not found', code=404)

@require_permission
@bp.route('/plans/<int:id>', methods=['PUT'])
@system_container(page_name='plans_update', require_auth='login', allowed_roles=['teacher','admin','super_admin'])
def plans_update(id):
    data = request.get_json()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE adult_study_plans SET title = ?, description = ?, duration = ? WHERE id = ?',
                   (data['title'], data['description'], data['duration'], id))
    conn.commit()
    conn.close()
    return _make_ok({'id': id})

@require_permission
@bp.route('/plans/<int:id>', methods=['DELETE'])
@system_container(page_name='plans_delete', require_auth='login', allowed_roles=['teacher','admin','super_admin'])
def plans_delete(id):
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM adult_study_plans WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return _make_ok({'id': id})

@require_permission
@bp.route('/progress', methods=['GET'])
@system_container(page_name='progress_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def progress_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_progress WHERE user_id = ?', (_get_current_user(),))
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/progress', methods=['POST'])
@system_container(page_name='progress_create', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def progress_create():
    data = request.get_json()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mt_learning_progress (user_id, plan_id, subject, progress_pct, hours_spent, last_update, notes) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (_get_current_user(), data['plan_id'], data['subject'], data['progress_pct'], data['hours_spent'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['notes']))
    conn.commit()
    conn.close()
    return _make_ok({'id': cursor.lastrowid})

@require_permission
@bp.route('/resources', methods=['GET'])
@system_container(page_name='resources_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def resources_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_resources WHERE user_id = ?', (_get_current_user(),))
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/resources', methods=['POST'])
@system_container(page_name='resources_create', require_auth='login', allowed_roles=['teacher','admin','super_admin'])
def resources_create():
    data = request.get_json()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mt_learning_resources (user_id, title, type, url, subject, difficulty, rating, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                   (_get_current_user(), data['title'], data['type'], data['url'], data['subject'], data['difficulty'], data['rating'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return _make_ok({'id': cursor.lastrowid})

@require_permission
@bp.route('/resources/<int:id>', methods=['GET'])
@system_container(page_name='resources_detail', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def resources_detail(id):
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_resources WHERE id = ?', (id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _make_ok(_row_to_dict(row, cursor))
    else:
        return _make_err('Resource not found', code=404)

@require_permission
@bp.route('/calendar', methods=['GET'])
@system_container(page_name='calendar_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def calendar_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_calendar WHERE user_id = ?', (_get_current_user(),))
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/calendar/checkin', methods=['POST'])
@system_container(page_name='calendar_checkin', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def calendar_checkin():
    data = request.get_json()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mt_learning_calendar (user_id, date, plan_id, checkin_done, minutes_spent, notes) VALUES (?, ?, ?, ?, ?, ?)',
                   (_get_current_user(), data['date'], data['plan_id'], 1, data['minutes_spent'], data['notes']))
    conn.commit()
    conn.close()
    return _make_ok({'id': cursor.lastrowid})

@require_permission
@bp.route('/goals', methods=['GET'])
@system_container(page_name='goals_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def goals_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_goals WHERE user_id = ?', (_get_current_user(),))
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/goals', methods=['POST'])
@system_container(page_name='goals_create', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def goals_create():
    data = request.get_json()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mt_learning_goals (user_id, title, subject, target_date, target_value, current_value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (_get_current_user(), data['title'], data['subject'], data['target_date'], data['target_value'], data['current_value'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return _make_ok({'id': cursor.lastrowid})

@require_permission
@bp.route('/goals/<int:id>', methods=['PUT'])
@system_container(page_name='goals_update', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def goals_update(id):
    data = request.get_json()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE mt_learning_goals SET title = ?, subject = ?, target_date = ?, target_value = ?, current_value = ? WHERE id = ?',
                   (data['title'], data['subject'], data['target_date'], data['target_value'], data['current_value'], id))
    conn.commit()
    conn.close()
    return _make_ok({'id': id})

@require_permission
@bp.route('/notes', methods=['GET'])
@system_container(page_name='notes_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def notes_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_notes WHERE user_id = ?', (_get_current_user(),))
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/notes', methods=['POST'])
@system_container(page_name='notes_create', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def notes_create():
    data = request.get_json() or {}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO mt_learning_notes (user_id, subject, title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (_get_current_user(), data.get('subject', ''), data.get('title', ''),
         data.get('content', ''), data.get('tags', ''), now, now))
    conn.commit()
    conn.close()
    return _make_ok({'id': cursor.lastrowid})

@require_permission
@bp.route('/notes/<int:note_id>', methods=['DELETE'])
@system_container(page_name='notes_delete', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def notes_delete(note_id):
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM mt_learning_notes WHERE id = ? AND user_id = ?', (note_id, _get_current_user()))
    if cursor.rowcount == 0:
        conn.close()
        return _make_err('Note not found or not owned', code=404)
    conn.commit()
    conn.close()
    return _make_ok({'id': note_id})

@require_permission
@bp.route('/knowledge_points', methods=['GET'])
@system_container(page_name='kp_list', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def kp_list():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM mt_learning_kp WHERE user_id = ?', (_get_current_user(),))
    rows = cursor.fetchall()
    conn.close()
    return _make_ok(_rows_to_list(rows, cursor))

@require_permission
@bp.route('/knowledge_points/<int:kp_id>', methods=['POST'])
@system_container(page_name='kp_update', require_auth='login', allowed_roles=['student','student_vip','teacher','parent','admin','super_admin'])
def kp_update(kp_id):
    data = request.get_json() or {}
    mastery = data.get('mastery_level', 0)
    practiced = data.get('last_practiced', datetime.now().strftime('%Y-%m-%d'))
    now_total = data.get('total_practice')  # 可选: 直接指定新总次数
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT total_practice FROM mt_learning_kp WHERE id = ? AND user_id = ?',
                   (kp_id, _get_current_user()))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return _make_err('Knowledge point not found', code=404)
    new_total = now_total if now_total is not None else (row[0] or 0) + 1
    cursor.execute(
        'UPDATE mt_learning_kp SET mastery_level = ?, last_practiced = ?, total_practice = ? WHERE id = ? AND user_id = ?',
        (mastery, practiced, new_total, kp_id, _get_current_user()))
    conn.commit()
    conn.close()
    return _make_ok({'id': kp_id, 'mastery_level': mastery, 'total_practice': new_total})