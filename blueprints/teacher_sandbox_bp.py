#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🎓 TeacherSandbox Blueprint — /api/teacher-sandbox/*
同理 lab_sandbox_bp.py, 完全隔离 mt_ts_* 表
"""
from __future__ import annotations
import sys
import json
import traceback
import logging
import sqlite3
from flask import Blueprint, request, jsonify

logger = logging.getLogger('teacher_sandbox_bp')

ts_bp = Blueprint('teacher_sandbox', __name__, url_prefix='/api/teacher-sandbox')

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from engines.teacher_sandbox_engine import TeacherSandboxEngine
        _engine = TeacherSandboxEngine()
    return _engine


def _ok(data=None, **extra):
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    payload.update(extra)
    return jsonify(payload)


def _err(msg, code=400):
    return jsonify({'success': False, 'error': msg}), code


# ── Health ──
@ts_bp.route('/health', methods=['GET'])
def health():
    try:
        eng = _get_engine()
        return _ok({
            'engine': 'TeacherSandboxEngine',
            'db_path': eng.db_path,
            'ok': True,
            'tables': [k for k in __import__('engines.teacher_sandbox_engine', fromlist=['TS_SCHEMAS']).TS_SCHEMAS.keys()],
        })
    except Exception as e:
        return _err(str(e), 500)


# ── 团队 CRUD ──
@ts_bp.route('/teams', methods=['GET'])
def list_teams():
    status = request.args.get('status', '')
    limit = int(request.args.get('limit', 20))
    try:
        items = _get_engine().list_teams(status=status, limit=limit)
        return _ok({'teams': items, 'count': len(items)})
    except Exception as e:
        return _err(f'list failed: {e}', 500)


@ts_bp.route('/teams', methods=['POST'])
def create_team():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return _err('title 必填')
    subject = data.get('subject', 'general')
    team_type = data.get('type', 'lesson_review')
    focus = data.get('focus', '')
    try:
        r = _get_engine().create_team(title, subject=subject, team_type=team_type, focus=focus)
        if r.get('success'):
            return _ok(r, message=f'团队已创建, {r.get("teachers_count",0)} AI 教师自动加入')
        return _err(r.get('error', 'unknown'))
    except Exception as e:
        traceback.print_exc()
        return _err(f'create failed: {e}', 500)


@ts_bp.route('/teams/<team_id>', methods=['GET'])
def get_team(team_id):
    try:
        r = _get_engine().get_team_status(team_id)
        if r.get('success'):
            return _ok(r)
        return _err(r.get('error', 'not found'), 404)
    except Exception as e:
        return _err(str(e), 500)


# ── 教师列表 ──
@ts_bp.route('/teams/<team_id>/teachers', methods=['GET'])
def list_teachers(team_id):
    try:
        from engines.teacher_sandbox_engine import _open_conn
        conn = _open_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM mt_ts_teacher WHERE team_id=? ORDER BY total_score DESC",
            (team_id,)).fetchall()
        conn.close()
        return _ok({'teachers': [dict(r) for r in rows]})
    except Exception as e:
        return _err(str(e), 500)


# ── 教案提交 ──
@ts_bp.route('/teams/<team_id>/lessons', methods=['POST'])
def submit_lesson(team_id):
    data = request.get_json(silent=True) or {}
    teacher_id = (data.get('teacher_id') or request.args.get('teacher_id') or '').strip()
    if not teacher_id:
        return _err('teacher_id 必填')
    title = (data.get('title') or '').strip()
    plan_content = data.get('plan_content') or data.get('plan') or ''
    if not title or not plan_content:
        return _err('title + plan_content 必填')
    subject = data.get('subject', '')
    grade = data.get('grade', '')
    duration_min = int(data.get('duration_min', 45))
    objectives = data.get('objectives', '')
    key_points = data.get('key_points', '')
    difficult_points = data.get('difficult_points', '')
    teaching_method = data.get('teaching_method', '讲授法+讨论法')

    try:
        r = _get_engine().submit_lesson_plan(
            team_id, teacher_id, title, plan_content,
            subject=subject, grade=grade, duration_min=duration_min,
            objectives=objectives, key_points=key_points,
            difficult_points=difficult_points, teaching_method=teaching_method,
        )
        if r.get('success'):
            return _ok(r, message=f'教案已提交 + AI 五维点评完成 (综合 {r["overall_score"]:.1f}/5)')
        return _err(r.get('error'))
    except Exception as e:
        traceback.print_exc()
        return _err(str(e), 500)


def _tsconn():
    from engines.teacher_sandbox_engine import _open_conn
    conn = _open_conn()
    conn.row_factory = sqlite3.Row
    return conn


@ts_bp.route('/teams/<team_id>/lessons', methods=['GET'])
def list_lessons(team_id):
    try:
        conn = _tsconn()
        rows = conn.execute(
            "SELECT * FROM mt_ts_lesson_plan WHERE team_id=? ORDER BY created_at DESC",
            (team_id,)).fetchall()
        conn.close()
        return _ok({'lessons': [dict(r) for r in rows]})
    except Exception as e:
        return _err(str(e), 500)


# ── AI 模拟课堂 ──
@ts_bp.route('/teams/<team_id>/lessons/<plan_id>/mock', methods=['POST'])
def run_mock(team_id, plan_id):
    data = request.get_json(silent=True) or {}
    teacher_id = (data.get('teacher_id') or request.args.get('teacher_id') or '').strip()
    if not teacher_id:
        # 自动取第一个老师
        try:
            eng = _get_engine()
            row = eng._conn.execute(
                "SELECT teacher_id FROM mt_ts_teacher WHERE team_id=? LIMIT 1",
                (team_id,)).fetchone()
            teacher_id = row['teacher_id'] if row else ''
        except Exception:
            pass
    if not teacher_id:
        return _err('teacher_id 必填')

    student_types = data.get('student_types') or ['优生', '中等生', '差生']
    if isinstance(student_types, str):
        student_types = [t.strip() for t in student_types.split(',') if t.strip()]

    try:
        r = _get_engine().run_mock_class(plan_id, team_id, teacher_id, student_types)
        if r.get('success'):
            return _ok(r, message=f'AI 模拟 {r["mock_count"]} 类学生课堂反应')
        return _err(r.get('error'))
    except Exception as e:
        traceback.print_exc()
        return _err(str(e), 500)


# ── AI 团队教学反思 ──
@ts_bp.route('/teams/<team_id>/reflect', methods=['POST'])
def team_reflect(team_id):
    try:
        r = _get_engine().team_reflection(team_id)
        if r.get('success'):
            return _ok(r, message=f'AI 反思完成, {r["lessons_count"]} 条教训, {r["brain_feed_count"]} 条投喂脑库')
        return _err(r.get('error'))
    except Exception as e:
        traceback.print_exc()
        return _err(str(e), 500)


# ── 反思报告列表 ──
@ts_bp.route('/teams/<team_id>/reflections', methods=['GET'])
def list_reflections(team_id):
    try:
        conn = _tsconn()
        rows = conn.execute(
            "SELECT * FROM mt_ts_reflection WHERE team_id=? ORDER BY created_at DESC LIMIT 10",
            (team_id,)).fetchall()
        conn.close()
        return _ok({'reflections': [dict(r) for r in rows]})
    except Exception as e:
        return _err(str(e), 500)


# ── 能力画像 ──
@ts_bp.route('/teachers/<teacher_id>/competency', methods=['GET'])
def get_competency(teacher_id):
    try:
        conn = _tsconn()
        teacher = conn.execute(
            "SELECT * FROM mt_ts_teacher WHERE teacher_id=?", (teacher_id,)).fetchone()
        comps = conn.execute(
            "SELECT * FROM mt_ts_competency WHERE teacher_id=?", (teacher_id,)).fetchall()
        conn.close()
        return _ok({
            'teacher': dict(teacher) if teacher else None,
            'competencies': [dict(c) for c in comps],
        })
    except Exception as e:
        return _err(str(e), 500)


# =====================================================================
# 注册入口
# =====================================================================
def register_teacher_sandbox_blueprint(app):
    try:
        app.register_blueprint(ts_bp)
        try:
            import threading
            def _ensure():
                try:
                    _get_engine()
                except Exception:
                    pass
            threading.Thread(target=_ensure, daemon=True, name='teacher-sandbox-init').start()
        except Exception:
            pass
        sys.stderr.write("[TeacherSandbox] ✅ /api/teacher-sandbox/* blueprint 已注册 (完全隔离 mt_ts_* 表)\n")
        return True
    except Exception as e:
        sys.stderr.write(f"[TeacherSandbox] ❌ blueprint 注册失败: {e}\n")
        return False
