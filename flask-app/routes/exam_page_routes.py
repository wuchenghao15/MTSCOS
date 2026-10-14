"""
exam_page_routes — 考试域页面级路由 (v22.35.0 Phase 2 拆分)
==========================================================
从 server_real_db.py (L16871-17815) 迁移 7 个页面级 route，纯 GET/redirect/渲染。
/api/exam/* API 端点不动，归属 exam_system_routes Blueprint。
/exam_system/* catch-all (复杂多页聚合) 暂不迁移，下阶段处理。

延迟绑定策略: 本文件被 routes/__init__.py 的 importlib.import_module 加载时，
server_real_db.py 已经完整定义 app/全局常量/内部函数。但为了避免未来调整 server_real_db.py
顶层导入顺序时踩到循环导入，统一用 handler 内 _mt_sdb() 延迟获取引用。

依赖 server_real_db 内部符号 (L17547-17771 handler 调用):
  _ensure_exam_real_ddls, _current_user, _exam_read_exam_by_id, _exam_read_questions,
  _exam_write_db, _get_conn, get_version_info, _safe_user_ctx,
  APP_DB, SPLIT_EXAM_DB, DATA_MTSCOS_DB
"""
import datetime as _dt
import json as _json
import os as _os

from flask import (
    Blueprint, redirect, render_template, request, session,
    make_response as _make_response,
)
from app.middlewares.system_container import system_container


# ═══════════════════════════════════════════════════════════════════════
# 蓝图定义 + 懒加载 server_real_db 引用
# ═══════════════════════════════════════════════════════════════════════
_bp = Blueprint('exam_page_routes', __name__)
exam_page_bp = _bp  # register_all_blueprints 通过 getattr(mod, 'exam_page_bp') 查找

_sdb = None  # server_real_db 模块引用，handler 内第一次访问时才赋值


def _mt_sdb():
    """延迟获取 server_real_db 模块引用。
    必须在 handler 内部调用 — 此时 server_real_db.py 已经完整加载。"""
    global _sdb
    if _sdb is None:
        import server_real_db as _mod
        _sdb = _mod
    return _sdb


# ═══════════════════════════════════════════════════════════════════════
# 7 个页面级路由（从 server_real_db.py 原样迁移）
# ═══════════════════════════════════════════════════════════════════════

# --- 4 个 redirect handler：只依赖 session/redirect，零内部函数 ---

@_bp.route('/exam_center', methods=['GET'])
@system_container(require_auth='login')
def exam_center_redirect():
    """考试中心统一入口：按角色智能重定向。
    学生/家长 → 学生门户考试 tab
    教师/管理员 → 后台考试管理页"""
    role = (session.get('role') or 'user').lower()
    username = (session.get('username') or '').lower()
    if username == 'wuchenghao15' or role in {'super_admin', 'sadmin', 'admin', 'school_admin', 'sysadmin', 'teacher_admin'}:
        return redirect('/admin_app/exams')
    if role in {'teacher'}:
        return redirect('/admin_app/exams')
    # 学生/家长/成人学生 → 门户考试中心
    return redirect('/student_portal?tab=exam_center')


@_bp.route('/exam_start', methods=['GET'])
@system_container(require_auth='login')
def exam_start_redirect():
    """旧开始考试页 → 考试系统·考试列表"""
    role = (session.get('role') or 'user').lower()
    username = (session.get('username') or '').lower()
    if username == 'wuchenghao15' or role in {'super_admin', 'sadmin', 'admin'}:
        return redirect('/admin_app/dashboard#tab=exams')
    return redirect('/exam_system/exams')


@_bp.route('/exam_page', methods=['GET'])
@system_container(require_auth='login')
def exam_page_redirect():
    """旧答题页 → 考试系统·考试列表"""
    role = (session.get('role') or 'user').lower()
    username = (session.get('username') or '').lower()
    if username == 'wuchenghao15' or role in {'super_admin', 'sadmin', 'admin'}:
        return redirect('/admin_app/dashboard#tab=exams')
    return redirect('/exam_system/exams')


@_bp.route('/exam_result', methods=['GET'])
@system_container(require_auth='login')
def exam_result_redirect():
    """旧考试结果页 → 考试系统·历史考试"""
    role = (session.get('role') or 'user').lower()
    username = (session.get('username') or '').lower()
    if username == 'wuchenghao15' or role in {'super_admin', 'sadmin', 'admin'}:
        return redirect('/admin_app/dashboard#tab=exams')
    return redirect('/exam_system/past_exams')


# --- 3 个真实业务 handler：依赖 server_real_db 内部函数 ---

@_bp.route('/exam/start/<int:exam_id>', methods=['GET'])
@system_container(require_auth='login')
def exam_start_real(exam_id):
    """真实考试答题页（落库 attempt + 渲染题目）"""
    sdb = _mt_sdb()
    import time as _t
    sdb._ensure_exam_real_ddls()
    user = sdb._current_user() or {}
    uid = int(user.get('id') or user.get('user_id') or session.get('user_id') or 0)
    if uid <= 0:
        return redirect('/exam_system/exams')
    exam = sdb._exam_read_exam_by_id(exam_id)
    if not exam:
        return redirect('/exam_system/exams')
    questions = sdb._exam_read_questions(exam, limit=200)
    # 创建/复用 attempt（同一考试可继续答题）
    wdb = sdb._exam_write_db()
    attempt_id = None
    try:
        with sdb._get_conn(wdb) as c:
            old = c.execute(
                "SELECT id, status FROM exam_attempts WHERE user_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",
                (uid, exam_id)).fetchone()
            if old and str(old.get('status') or '') == 'in_progress':
                attempt_id = int(old['id'])
            else:
                cur = c.execute("""INSERT INTO exam_attempts
                    (user_id, exam_id, paper_id, start_time, status, duration_sec, total_score)
                    VALUES (?,?,?, ?, 'in_progress', 0, ?)""",
                    (uid, exam_id, exam.get('paper_id') or exam.get('id'),
                     _dt.datetime.now().isoformat(),
                     float(exam.get('total_score') or exam.get('score') or 100)))
                attempt_id = cur.lastrowid
            c.commit()
    except Exception:
        pass
    v, info, _ = sdb.get_version_info()
    _safe_ctx = sdb._safe_user_ctx(user)
    _role = user.get('role') or 'student'
    _rlm = {'student': '学生', 'teacher': '教师', 'admin': '管理员',
            'super_admin': '超级管理员', 'sadmin': '超级管理员', 'user': '用户'}
    _exam_title = exam.get('title') or '在线考试'
    _exam_desc = (exam.get('description') or '').strip()
    _exam_full_title = _exam_title
    if _exam_desc and _exam_desc != _exam_title:
        _exam_full_title = f"{_exam_title} — {_exam_desc}"
    ctx = dict(
        user=_safe_ctx, role=_role, role_label=_rlm.get(_role, '学生'),
        version=v, version_info=info,
        attempt_id=attempt_id, exam_id=exam_id,
        exam=exam, questions=questions,
        exam_title=_exam_full_title,
        total_score=float(exam.get('total_score') or 100),
        passing_score=float(exam.get('passing_score') or 60),
        duration_min=int(exam.get('duration') or exam.get('duration_min') or 120),
        start_ts=int(_t.time()),
    )
    resp = _make_response(render_template('exam_answer_sheet.html', **ctx))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@_bp.route('/exam/review/<int:exam_id>', methods=['GET'])
@system_container(require_auth='login')
def exam_review_real(exam_id):
    """真实成绩详情页（从 exam_results 查询）"""
    sdb = _mt_sdb()
    sdb._ensure_exam_real_ddls()
    user = sdb._current_user() or {}
    uid = int(user.get('id') or user.get('user_id') or session.get('user_id') or 0)
    if uid <= 0:
        return redirect('/exam_system/exams')
    exam = sdb._exam_read_exam_by_id(exam_id)
    if not exam:
        return redirect('/exam_system/exams')
    questions = sdb._exam_read_questions(exam, limit=500)
    # 跨库读取 result/attempt
    result = None
    attempt = None
    for p in [sdb.APP_DB, sdb.SPLIT_EXAM_DB, sdb.DATA_MTSCOS_DB]:
        if not (p and _os.path.exists(p)):
            continue
        with sdb._get_conn(p) as c:
            try:
                if not result:
                    r = c.execute(
                        "SELECT * FROM exam_results WHERE user_id=? AND exam_id=? ORDER BY id DESC LIMIT 1",
                        (uid, exam_id)).fetchone()
                    if r:
                        result = dict(r)
            except Exception:
                pass
            try:
                if not attempt:
                    aid = result.get('attempt_id') if result else 0
                    if aid and aid > 0:
                        a = c.execute("SELECT * FROM exam_attempts WHERE id=? LIMIT 1", (int(aid),)).fetchone()
                    else:
                        a = c.execute(
                            "SELECT * FROM exam_attempts WHERE user_id=? AND exam_id=? AND status='submitted' ORDER BY id DESC LIMIT 1",
                            (uid, exam_id)).fetchone()
                    if a:
                        attempt = dict(a)
            except Exception:
                pass
        if result and attempt:
            break
    v, info, _ = sdb.get_version_info()
    _safe_ctx = sdb._safe_user_ctx(user)
    _role = user.get('role') or 'student'
    _rlm = {'student': '学生', 'teacher': '教师', 'admin': '管理员',
            'super_admin': '超级管理员', 'sadmin': '超级管理员', 'user': '用户'}
    answers_parsed = {}
    if attempt and attempt.get('answers_json'):
        try:
            answers_parsed = _json.loads(attempt['answers_json']) if isinstance(attempt['answers_json'], str) else (attempt['answers_json'] or {})
        except Exception:
            answers_parsed = {}
    wrong_parsed = []
    if result and result.get('wrong_answers_json'):
        try:
            wrong_parsed = _json.loads(result['wrong_answers_json']) if isinstance(result['wrong_answers_json'], str) else (result['wrong_answers_json'] or [])
        except Exception:
            wrong_parsed = []
    attr_parsed = {}
    if result and result.get('ai_attribution_json'):
        try:
            attr_parsed = _json.loads(result['ai_attribution_json']) if isinstance(result['ai_attribution_json'], str) else (result['ai_attribution_json'] or {})
        except Exception:
            attr_parsed = {}
    if not result:
        result = {
            'best_score': None, 'total_score': float(exam.get('total_score') or 100),
            'passing_score': float(exam.get('passing_score') or 60), 'is_passed': 0,
            'questions_count': len(questions), 'correct_count': 0, 'wrong_count': 0,
        }
    else:
        result.setdefault('wrong_count', len(wrong_parsed))
    ctx = dict(
        user=_safe_ctx, role=_role, role_label=_rlm.get(_role, '学生'),
        version=v, version_info=info,
        exam=exam, exam_id=exam_id,
        result=result, attempt=attempt or {},
        questions=questions, answers=answers_parsed,
        wrong_questions=wrong_parsed,
        ai_attribution=attr_parsed,
    )
    return render_template('exam_review.html', **ctx)


@_bp.route('/exam_page_real/<int:exam_id>', methods=['GET'])
@system_container(require_auth='login')
def exam_page_real(exam_id):
    """真实答题页别名 → 合并到 /exam/start/<id>"""
    return redirect(f'/exam/start/{exam_id}')
