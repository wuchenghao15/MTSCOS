"""adult_education_routes — 成人教育管理 Blueprint
功能: 职业导向学习/碎片化学习计划/学分证书/企业培训/在线考试认证/学习社群
遵循: SSOT原则(所有数据实时写入数据库) + 权限双保险(@system_container + _check_login/_check_admin)
权限: 查询类需登录，写操作(证书/企业/考试)需管理员
版本: v1.0.0 (配合 auto_maintenance_agent v2.12.0)
"""
from . import adult_bp

from flask import Blueprint, jsonify, jsonify, request
import sqlite3
import uuid
import logging
from datetime import datetime
from app.middlewares.system_container import system_container

logger = logging.getLogger('AdultEducationRoutes')


def _get_shared_funcs():
    """延迟导入 server_real_db 共享函数（避免循环导入）"""
    try:
        from server_real_db import _current_safe_user, _MT_ADMIN_ROLES
        return _current_safe_user, _MT_ADMIN_ROLES
    except ImportError:
        import sys
        import os
        _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _base not in sys.path:
            sys.path.insert(0, _base)
        from server_real_db import _current_safe_user, _MT_ADMIN_ROLES
        return _current_safe_user, _MT_ADMIN_ROLES


# ========== 权限校验 ==========

def _check_admin(user):
    """校验管理员权限（超级管理员 wuchenghao15 无条件放行）"""
    if user.get('is_super_admin'):
        return True, None
    if user.get('role') in _MT_ADMIN_ROLES:
        return True, None
    return False, (403, '需要管理员权限')


def _check_login(user):
    """校验登录状态"""
    if user.get('logged_in'):
        return True, None
    return False, (401, '未登录')


# ========== 输入校验白名单 ==========

_ADULT_CAREER_PATHS = frozenset({
    'software_development', 'data_science', 'product_management',
    'ux_design', 'cybersecurity', 'digital_marketing',
    'business_analysis', 'project_management'
})
_ADULT_CREDIT_TYPES = frozenset({
    'course_completion', 'exam_passed', 'activity_participation',
    'project_completion', 'study_duration', 'certification'
})
_ADULT_CERT_TYPES = frozenset({
    'course_completion', 'professional_cert', 'skill_cert',
    'exam_passed', 'advanced_study'
})
_ADULT_TRAINING_TYPES = frozenset({
    'onboarding', 'skill_upgrade', 'management_training',
    'certification', 'product_training', 'compliance'
})
_ADULT_EXAM_TYPES = frozenset({
    'certification', 'assessment', 'placement', 'final'
})
_ADULT_COMMUNITY_CATEGORIES = frozenset({
    'career_development', 'skill_sharing', 'study_group',
    'industry_discussion', 'networking'
})
_ADULT_PRIVACY = frozenset({'public', 'private'})
_ADULT_PLAN_STATUS = frozenset({'active', 'paused', 'completed', 'dropped'})


def _safe_int(value, default=None, min_val=None, max_val=None):
    """安全转换为整数"""
    try:
        v = int(value)
        if min_val is not None and v < min_val:
            return default
        if max_val is not None and v > max_val:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=None, min_val=None, max_val=None):
    """安全转换为浮点数"""
    try:
        v = float(value)
        if min_val is not None and v < min_val:
            return default
        if max_val is not None and v > max_val:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_str(value, max_len=200):
    """安全字符串：截断长度，拒绝控制字符"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if '\x00' in s:
        s = s.replace('\x00', '')
    return s[:max_len] if s else None


def _get_db_path():
    """获取数据库路径"""
    try:
        from core.db_path import get_db_path as _mtscos_get_db_path
        return _mtscos_get_db_path('app.db')
    except Exception:
        import os
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app.db'
        )


def _ensure_tables():
    """确保成人教育相关表存在"""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.executescript('''
CREATE TABLE IF NOT EXISTS adult_career_paths (
    user_id INTEGER PRIMARY KEY, career_path TEXT, target_level TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_study_plans (
    plan_id TEXT PRIMARY KEY, user_id INTEGER, subject TEXT, target_level TEXT,
    weekly_hours REAL, plan_name TEXT, progress REAL DEFAULT 0,
    status TEXT DEFAULT 'active', created_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, credit_type TEXT,
    credits REAL, subject TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_certificates (
    certificate_id TEXT PRIMARY KEY, user_id INTEGER, certificate_type TEXT,
    subject TEXT, level TEXT, accuracy REAL, issued_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_companies (
    company_id TEXT PRIMARY KEY, company_name TEXT, industry TEXT,
    employee_count INTEGER, contact_email TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_training_programs (
    program_id TEXT PRIMARY KEY, company_id TEXT, program_name TEXT,
    training_type TEXT, target_role TEXT, duration_hours REAL,
    required_credits REAL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, program_id TEXT,
    progress REAL DEFAULT 0, completed INTEGER DEFAULT 0, enrolled_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_exams (
    exam_id TEXT PRIMARY KEY, exam_name TEXT, exam_type TEXT, subject TEXT,
    duration_minutes INTEGER, total_score REAL, passing_score REAL,
    question_count INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_exam_certifications (
    cert_id TEXT PRIMARY KEY, user_id INTEGER, exam_id TEXT, certificate_id TEXT,
    exam_name TEXT, subject TEXT, score REAL, total_score REAL, issued_at TEXT
);
CREATE TABLE IF NOT EXISTS adult_communities (
    group_id TEXT PRIMARY KEY, group_name TEXT, category TEXT, description TEXT,
    max_members INTEGER, privacy TEXT, member_count INTEGER DEFAULT 0, created_at TEXT
);
    ''')
    conn.commit()
    conn.close()


# ============================================================================
# 查询类接口（登录即可访问）
# ============================================================================

@adult_bp.route('/stats', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_stats():
    """获取成人教育统计"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM adult_career_paths")
            learners = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM adult_training_programs")
            programs = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM adult_exams")
            exams = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM adult_certificates")
            certs = cur.fetchone()[0] or 0
        return jsonify({
            'success': True, 'total_learners': learners,
            'total_programs': programs, 'total_exams': exams,
            'total_certificates': certs
        })
    except Exception as e:
        logger.error(f'[Adult] stats失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/career/recommendation/<int:user_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_career_recommendation(user_id):
    """获取职业方向推荐"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT career_path, target_level FROM adult_career_paths WHERE user_id=?",
                (user_id,))
            row = cur.fetchone()
        if row:
            return jsonify({
                'success': True, 'career_path': row['career_path'],
                'target_level': row['target_level'],
                'match_score': 0.85,
                'reason': '基于已设置职业方向',
                'recommended_courses': []
            })
        return jsonify({
            'success': True, 'career_path': None,
            'match_score': 0.0, 'reason': '尚未设置职业方向'
        })
    except Exception as e:
        logger.error(f'[Adult] career_recommendation失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/credits/summary/<int:user_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_credits_summary(user_id):
    """获取学分汇总"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT credit_type, SUM(credits) as total FROM adult_credits WHERE user_id=? GROUP BY credit_type",
                (user_id,))
            rows = cur.fetchall()
            total = sum(r['total'] or 0 for r in rows)
            details = [{'credit_type': r['credit_type'], 'credits': r['total']} for r in rows]
        return jsonify({
            'success': True, 'total_credits': total, 'credit_details': details
        })
    except Exception as e:
        logger.error(f'[Adult] credits_summary失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/certificate/list/<int:user_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_certificate_list(user_id):
    """获取证书列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT certificate_id, certificate_type, subject, level, accuracy, issued_at FROM adult_certificates WHERE user_id=? ORDER BY issued_at DESC",
                (user_id,))
            rows = cur.fetchall()
        certs = [dict(r) for r in rows]
        return jsonify({'success': True, 'certificates': certs})
    except Exception as e:
        logger.error(f'[Adult] certificate_list失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/corporate/status/<int:user_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_corporate_status(user_id):
    """获取员工培训状态"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''
                SELECT e.id, e.program_id, e.progress, e.completed, e.enrolled_at,
                       p.program_name
                FROM adult_enrollments e
                LEFT JOIN adult_training_programs p ON e.program_id = p.program_id
                WHERE e.user_id=? ORDER BY e.enrolled_at DESC
            ''', (user_id,))
            rows = cur.fetchall()
        enrollments = [dict(r) for r in rows]
        return jsonify({'success': True, 'enrollments': enrollments})
    except Exception as e:
        logger.error(f'[Adult] corporate_status失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/exam/certifications/<int:user_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_exam_certifications(user_id):
    """获取用户考试认证"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT cert_id, certificate_id, exam_name, subject, score, total_score, issued_at FROM adult_exam_certifications WHERE user_id=? ORDER BY issued_at DESC",
                (user_id,))
            rows = cur.fetchall()
        certs = [dict(r) for r in rows]
        return jsonify({'success': True, 'certifications': certs})
    except Exception as e:
        logger.error(f'[Adult] exam_certifications失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/study/plans', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_study_plans_list():
    """获取学习计划列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        uid = _safe_int(request.args.get('user_id'), min_val=1, max_val=999999999)
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if uid:
                cur.execute(
                    "SELECT plan_id, user_id, subject, target_level, weekly_hours, plan_name, progress, status, created_at FROM adult_study_plans WHERE user_id=? ORDER BY created_at DESC LIMIT 500",
                    (uid,))
            else:
                cur.execute(
                    "SELECT plan_id, user_id, subject, target_level, weekly_hours, plan_name, progress, status, created_at FROM adult_study_plans ORDER BY created_at DESC LIMIT 500")
            rows = cur.fetchall()
        plans = [dict(r) for r in rows]
        return jsonify({'success': True, 'data': plans, 'count': len(plans)})
    except Exception as e:
        logger.error(f'[Adult] study_plans_list失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/corporate/programs', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_programs_list():
    """获取培训项目列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT program_id, company_id, program_name, training_type, target_role, duration_hours, required_credits, created_at FROM adult_training_programs ORDER BY created_at DESC LIMIT 500")
            rows = cur.fetchall()
        programs = [dict(r) for r in rows]
        return jsonify({'success': True, 'data': programs, 'count': len(programs)})
    except Exception as e:
        logger.error(f'[Adult] programs_list失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/exam/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_exams_list():
    """获取考试列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT exam_id, exam_name, exam_type, subject, duration_minutes, total_score, passing_score, question_count, created_at FROM adult_exams ORDER BY created_at DESC LIMIT 500")
            rows = cur.fetchall()
        exams = [dict(r) for r in rows]
        return jsonify({'success': True, 'data': exams, 'count': len(exams)})
    except Exception as e:
        logger.error(f'[Adult] exams_list失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/community/list', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_community_list():
    """获取社群列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT group_id, group_name, category, description, max_members, privacy, member_count, created_at FROM adult_communities ORDER BY created_at DESC LIMIT 500")
            rows = cur.fetchall()
        communities = [dict(r) for r in rows]
        return jsonify({'success': True, 'data': communities, 'count': len(communities)})
    except Exception as e:
        logger.error(f'[Adult] community_list失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 写操作接口
# ============================================================================

@adult_bp.route('/career/path', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_set_career_path():
    """设置职业方向（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        career_path = _safe_str(data.get('career_path'), 50)
        target_level = _safe_str(data.get('target_level'), 100)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not career_path or career_path not in _ADULT_CAREER_PATHS:
            return jsonify({'success': False, 'error': 'career_path不在白名单内'}), 400
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO adult_career_paths (user_id, career_path, target_level, created_at) VALUES (?, ?, ?, ?)",
                (user_id, career_path, target_level or '', now))
            conn.commit()
        return jsonify({'success': True, 'message': '职业方向设置成功'})
    except Exception as e:
        logger.error(f'[Adult] set_career_path失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/study/plan', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_create_study_plan():
    """创建学习计划（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        subject = _safe_str(data.get('subject'), 100)
        target_level = _safe_str(data.get('target_level'), 100)
        weekly_hours = _safe_float(data.get('weekly_hours'), default=5.0, min_val=0.5, max_val=168.0)
        plan_name = _safe_str(data.get('plan_name'), 200)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not subject:
            return jsonify({'success': False, 'error': 'subject为必填项'}), 400
        if not plan_name:
            plan_name = subject + '_计划'
        plan_id = 'sp_' + uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_study_plans (plan_id, user_id, subject, target_level, weekly_hours, plan_name, progress, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', ?)",
                (plan_id, user_id, subject, target_level or '', weekly_hours, plan_name, now))
            conn.commit()
        return jsonify({'success': True, 'plan_id': plan_id})
    except Exception as e:
        logger.error(f'[Adult] create_study_plan失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/credits', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_add_credits():
    """增加学分（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        credit_type = _safe_str(data.get('credit_type'), 30)
        credits = _safe_float(data.get('credits'), min_val=0.1, max_val=10000.0)
        subject = _safe_str(data.get('subject'), 100)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not credit_type or credit_type not in _ADULT_CREDIT_TYPES:
            return jsonify({'success': False, 'error': 'credit_type不在白名单内'}), 400
        if credits is None:
            return jsonify({'success': False, 'error': 'credits为必填项且须在0.1-10000'}), 400
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_credits (user_id, credit_type, credits, subject, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, credit_type, credits, subject or '', now))
            conn.commit()
        return jsonify({'success': True, 'message': '学分增加成功'})
    except Exception as e:
        logger.error(f'[Adult] add_credits失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/certificate/issue', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_issue_certificate():
    """发放证书（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        certificate_type = _safe_str(data.get('certificate_type'), 30)
        subject = _safe_str(data.get('subject'), 100)
        level = _safe_str(data.get('level'), 50)
        accuracy = _safe_float(data.get('accuracy'), default=0.0, min_val=0.0, max_val=1.0)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not certificate_type or certificate_type not in _ADULT_CERT_TYPES:
            return jsonify({'success': False, 'error': 'certificate_type不在白名单内'}), 400
        if not subject:
            return jsonify({'success': False, 'error': 'subject为必填项'}), 400
        cert_id = 'cert_' + uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_certificates (certificate_id, user_id, certificate_type, subject, level, accuracy, issued_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cert_id, user_id, certificate_type, subject, level or '', accuracy, now))
            conn.commit()
        return jsonify({'success': True, 'certificate_id': cert_id})
    except Exception as e:
        logger.error(f'[Adult] issue_certificate失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/corporate/company', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_create_company():
    """创建企业（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        company_id = _safe_str(data.get('company_id'), 64)
        company_name = _safe_str(data.get('company_name'), 200)
        industry = _safe_str(data.get('industry'), 100)
        employee_count = _safe_int(data.get('employee_count'), default=0, min_val=0, max_val=9999999)
        contact_email = _safe_str(data.get('contact_email'), 200)
        if not company_id:
            return jsonify({'success': False, 'error': 'company_id为必填项'}), 400
        if not company_name:
            return jsonify({'success': False, 'error': 'company_name为必填项'}), 400
        if contact_email and '@' not in contact_email:
            return jsonify({'success': False, 'error': 'contact_email格式非法'}), 400
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO adult_companies (company_id, company_name, industry, employee_count, contact_email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (company_id, company_name, industry or '', employee_count, contact_email or '', now))
            conn.commit()
        return jsonify({'success': True, 'company_id': company_id})
    except Exception as e:
        logger.error(f'[Adult] create_company失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/corporate/program', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_create_program():
    """创建培训项目（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        company_id = _safe_str(data.get('company_id'), 64)
        program_name = _safe_str(data.get('program_name'), 200)
        training_type = _safe_str(data.get('training_type'), 30)
        target_role = _safe_str(data.get('target_role'), 100)
        duration_hours = _safe_float(data.get('duration_hours'), default=0.0, min_val=0.0, max_val=10000.0)
        required_credits = _safe_float(data.get('required_credits'), default=0.0, min_val=0.0, max_val=10000.0)
        if not company_id:
            return jsonify({'success': False, 'error': 'company_id为必填项'}), 400
        if not program_name:
            return jsonify({'success': False, 'error': 'program_name为必填项'}), 400
        if not training_type or training_type not in _ADULT_TRAINING_TYPES:
            return jsonify({'success': False, 'error': 'training_type不在白名单内'}), 400
        program_id = 'tp_' + uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_training_programs (program_id, company_id, program_name, training_type, target_role, duration_hours, required_credits, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (program_id, company_id, program_name, training_type, target_role or '', duration_hours, required_credits, now))
            conn.commit()
        return jsonify({'success': True, 'program_id': program_id})
    except Exception as e:
        logger.error(f'[Adult] create_program失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/exam', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_create_exam():
    """创建考试（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        exam_name = _safe_str(data.get('exam_name'), 200)
        exam_type = _safe_str(data.get('exam_type'), 30)
        subject = _safe_str(data.get('subject'), 100)
        duration_minutes = _safe_int(data.get('duration_minutes'), min_val=1, max_val=600)
        total_score = _safe_float(data.get('total_score'), min_val=1.0, max_val=1000.0)
        passing_score = _safe_float(data.get('passing_score'), min_val=0.0, max_val=1000.0)
        question_count = _safe_int(data.get('question_count'), min_val=1, max_val=500)
        if not exam_name:
            return jsonify({'success': False, 'error': 'exam_name为必填项'}), 400
        if not exam_type or exam_type not in _ADULT_EXAM_TYPES:
            return jsonify({'success': False, 'error': 'exam_type不在白名单内'}), 400
        if not subject:
            return jsonify({'success': False, 'error': 'subject为必填项'}), 400
        if duration_minutes is None or total_score is None or passing_score is None or question_count is None:
            return jsonify({'success': False, 'error': 'duration_minutes/total_score/passing_score/question_count为必填项'}), 400
        if passing_score > total_score:
            return jsonify({'success': False, 'error': '及格分数不能超过总分'}), 400
        exam_id = 'ex_' + uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_exams (exam_id, exam_name, exam_type, subject, duration_minutes, total_score, passing_score, question_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exam_id, exam_name, exam_type, subject, duration_minutes, total_score, passing_score, question_count, now))
            conn.commit()
        return jsonify({'success': True, 'exam_id': exam_id})
    except Exception as e:
        logger.error(f'[Adult] create_exam失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/community', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_create_community():
    """创建社群（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        group_name = _safe_str(data.get('group_name'), 200)
        category = _safe_str(data.get('category'), 30)
        description = _safe_str(data.get('description'), 1000)
        max_members = _safe_int(data.get('max_members'), default=500, min_val=1, max_val=100000)
        privacy = _safe_str(data.get('privacy'), 10)
        if not group_name:
            return jsonify({'success': False, 'error': 'group_name为必填项'}), 400
        if not category or category not in _ADULT_COMMUNITY_CATEGORIES:
            return jsonify({'success': False, 'error': 'category不在白名单内'}), 400
        if not privacy or privacy not in _ADULT_PRIVACY:
            privacy = 'public'
        group_id = 'com_' + uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_communities (group_id, group_name, category, description, max_members, privacy, member_count, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                (group_id, group_name, category, description or '', max_members, privacy, now))
            conn.commit()
        return jsonify({'success': True, 'group_id': group_id})
    except Exception as e:
        logger.error(f'[Adult] create_community失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/study/plan/<plan_id>/progress', methods=['PUT'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_update_plan_progress(plan_id):
    """更新学习计划进度（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        pid = _safe_str(plan_id, 64)
        if not pid or not pid.startswith('sp_'):
            return jsonify({'success': False, 'error': '无效的计划ID'}), 400
        data = request.get_json(silent=True) or {}
        progress = _safe_float(data.get('progress'), min_val=0.0, max_val=1.0)
        if progress is None:
            return jsonify({'success': False, 'error': 'progress为必填项(0.0-1.0)'}), 400
        status = _safe_str(data.get('status'), 20)
        if status and status not in _ADULT_PLAN_STATUS:
            status = None
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            if status:
                conn.execute(
                    "UPDATE adult_study_plans SET progress=?, status=? WHERE plan_id=?",
                    (progress, status, pid))
            else:
                conn.execute(
                    "UPDATE adult_study_plans SET progress=? WHERE plan_id=?",
                    (progress, pid))
            conn.commit()
        return jsonify({'success': True, 'message': '进度更新成功'})
    except Exception as e:
        logger.error(f'[Adult] update_plan_progress失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/corporate/enroll', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_enroll_program():
    """员工报名培训项目（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        program_id = _safe_str(data.get('program_id'), 64)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not program_id:
            return jsonify({'success': False, 'error': 'program_id为必填项'}), 400
        now = datetime.now().isoformat()
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO adult_enrollments (user_id, program_id, progress, completed, enrolled_at) VALUES (?, ?, 0, 0, ?)",
                (user_id, program_id, now))
            conn.commit()
        return jsonify({'success': True, 'message': '报名成功'})
    except Exception as e:
        logger.error(f'[Adult] enroll_program失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@adult_bp.route('/community/<group_id>/join', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def adult_join_community(group_id):
    """加入社群（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        _ensure_tables()
        gid = _safe_str(group_id, 64)
        if not gid or not gid.startswith('com_'):
            return jsonify({'success': False, 'error': '无效的社群ID'}), 400
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT max_members, member_count FROM adult_communities WHERE group_id=?", (gid,))
            row = cur.fetchone()
            if not row:
                return jsonify({'success': False, 'error': '社群不存在'}), 404
            if row[1] >= row[0]:
                return jsonify({'success': False, 'error': '社群已满'}), 400
            conn.execute(
                "UPDATE adult_communities SET member_count = member_count + 1 WHERE group_id=?",
                (gid,))
            conn.commit()
        return jsonify({'success': True, 'message': '加入成功'})
    except Exception as e:
        logger.error(f'[Adult] join_community失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


bp = Blueprint('adult_education_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['student', 'student_vip', 'teacher', 'admin', 'super_admin'])
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'adult_education','routes_implemented':1}})
