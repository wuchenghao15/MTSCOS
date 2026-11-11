"""k12_management_routes — K12教育管理 Blueprint
功能: K12学生档案/知识点/错题本/家校互动/综合素质评价/升学指导/学习游戏化
遵循: SSOT原则(所有数据实时写入数据库) + 权限双保险(@system_container + _check_login/_check_admin)
权限: 查询类需登录，写操作(知识点/分层)需管理员
版本: v1.0.0 (配合 auto_maintenance_agent v2.11.0)
"""
from . import k12_bp

from flask import Blueprint, jsonify, jsonify, request, session
import sqlite3
import logging
from app.middlewares.system_container import system_container

logger = logging.getLogger('K12Routes')


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


# ========== P0修复: 模块级鉴权符号绑定 (此前仅定义在 _get_shared_funcs 内部、从未绑定,
#             导致全部 k12 路由首行 `_current_safe_user()` 抛 NameError → 500, 学生功能整体不可用) ==========

# 教师/管理员角色集合(优先取 server_real_db SSOT; 不可用时用本兜底集合, 含 teacher 以覆盖K12教育场景)
_MT_ADMIN_ROLES = frozenset({
    'admin', 'super_admin', 'sadmin', 'teacher_admin', 'school_admin',
    'sysadmin', 'teacher', 'exam_proctor',
})


def _current_safe_user():
    """统一当前用户读取(懒加载 server_real_db 避免循环导入; 未登录返回 guest, 不抛异常)。

    返回字典(对齐 server_real_db): uid(字符串)/username/role/logged_in/is_guest/is_super_admin。
    """
    try:
        from server_real_db import _current_safe_user as _impl
        return _impl()
    except Exception:
        try:
            _uid = session.get('user_id')
            _uname = session.get('username')
            _role = session.get('role') or 'guest'
            _logged = bool(session.get('logged_in'))
        except Exception:
            _uid, _uname, _role, _logged = None, None, 'guest', False
        if _uid and _uname and _logged:
            return {'uid': str(_uid), 'username': _uname, 'role': _role,
                    'logged_in': True, 'is_guest': False,
                    'is_super_admin': str(_uname).lower() == 'wuchenghao15'}
        return {'uid': '', 'username': 'guest', 'role': 'guest',
                'logged_in': False, 'is_guest': True, 'is_super_admin': False}


def _is_staff(user):
    """是否教师/管理员(可跨学生查询/操作)。超级管理员无条件放行。"""
    if user.get('is_super_admin'):
        return True
    role = user.get('role')
    # 优先用 server_real_db 的 SSOT 角色集合
    try:
        from server_real_db import _MT_ADMIN_ROLES as _ssot_roles
        if role in _ssot_roles:
            return True
    except Exception:
        pass
    return role in _MT_ADMIN_ROLES


def _uid_of(user):
    """取当前登录用户ID字符串(兼容 uid/user_id/id)。"""
    return str(user.get('uid') or user.get('user_id') or user.get('id') or '')


# ========== 服务单例（延迟初始化） ==========

_k12_service = None
_k12_game_service = None
_k12_eval_service = None
_k12_admission_service = None


def _get_k12_service():
    """获取K12教育服务单例"""
    global _k12_service
    if _k12_service is None:
        from core.services.k12_education_service import K12EducationService
        _k12_service = K12EducationService()
    return _k12_service


def _get_game_service():
    """获取K12游戏化服务单例"""
    global _k12_game_service
    if _k12_game_service is None:
        from core.services.k12_education_service import K12GameService
        _k12_game_service = K12GameService()
    return _k12_game_service


def _get_eval_service():
    """获取K12综合素质评价服务单例"""
    global _k12_eval_service
    if _k12_eval_service is None:
        from core.services.k12_education_service import K12ComprehensiveEvaluationService
        _k12_eval_service = K12ComprehensiveEvaluationService()
    return _k12_eval_service


def _get_admission_service():
    """获取K12升学指导服务单例"""
    global _k12_admission_service
    if _k12_admission_service is None:
        from core.services.k12_education_service import K12CollegeAdmissionService
        _k12_admission_service = K12CollegeAdmissionService()
    return _k12_admission_service


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

_K12_TIERS = frozenset({'A', 'B', 'C'})
_K12_EXAM_TYPES = frozenset({'gaokao', 'zhongkao', 'sat', 'ielts', 'toefl', 'gre'})
_K12_SENDER_ROLES = frozenset({'parent', 'teacher', 'student', 'admin'})
_K12_MESSAGE_TYPES = frozenset({
    'study_report', 'behavior_feedback', 'exam_notice',
    'homework_notice', 'achievement', 'concern', 'meeting'
})
_K12_WRONG_TYPES = frozenset({
    'concept_error', 'calculation_error', 'careless_error',
    'method_error', 'knowledge_gap', 'other'
})
_K12_TRANSACTION_TYPES = frozenset({
    'daily_login', 'correct_answer', 'wrong_resolved',
    'first_correct_in_row', 'perfect_practice', 'study_hour',
    'achievement_unlock', 'manual_adjust'
})
_K12_SUBJECTS = frozenset({
    '语文', '数学', '英语', '物理', '化学', '生物',
    '政治', '历史', '地理', '科学', '道德与法治'
})
_K12_GRADES = frozenset({str(i) for i in range(1, 13)})
_K12_DIFFICULTY = frozenset({1, 2, 3, 4, 5})
_K12_INTEREST_TYPES = frozenset({
    '现实型', '研究型', '艺术型', '社会型', '企业型', '常规型'
})


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


def _safe_str(value, max_len=200):
    """安全字符串：截断长度，拒绝控制字符"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # 拒绝null字节和常见控制字符
    if '\x00' in s or '\r' in s or '\n' in s and len(s) > max_len:
        s = s.replace('\x00', '').replace('\r', ' ').replace('\n', ' ')
    return s[:max_len]


# ============================================================================
# 查询类接口（登录即可访问）
# ============================================================================

@k12_bp.route('/stats', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_stats():
    """获取K12教育统计"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        service = _get_k12_service()
        return jsonify(service.get_statistics())
    except Exception as e:
        logger.error(f'[K12] stats失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/students', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_students():
    """获取学生档案列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''SELECT user_id, grade, grade_group, learning_tier,
                              subjects, class_id, parent_user_id, avg_accuracy,
                              total_questions_done, created_at
                           FROM k12_student_profiles ORDER BY created_at DESC LIMIT 500''')
            rows = cursor.fetchall()
        data = []
        for r in rows:
            data.append({
                'user_id': r['user_id'],
                'grade': r['grade'],
                'grade_group': r['grade_group'],
                'learning_tier': r['learning_tier'],
                'subjects': r['subjects'] or '',
                'class_id': r['class_id'],
                'parent_user_id': r['parent_user_id'],
                'avg_accuracy': r['avg_accuracy'],
                'total_questions_done': r['total_questions_done'],
                'created_at': r['created_at']
            })
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        logger.error(f'[K12] students失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/knowledge/points', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_knowledge_points():
    """获取知识点列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        subject = _safe_str(request.args.get('subject'), 20)
        grade = _safe_str(request.args.get('grade'), 4)
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = '''SELECT point_id, subject, grade, chapter, point_name,
                     parent_point_id, difficulty_level, description, created_at
                     FROM k12_knowledge_points'''
            params = []
            conditions = []
            if subject and subject in _K12_SUBJECTS:
                conditions.append('subject = ?')
                params.append(subject)
            if grade and grade in _K12_GRADES:
                conditions.append('grade = ?')
                params.append(grade)
            if conditions:
                sql += ' WHERE ' + ' AND '.join(conditions)
            sql += ' ORDER BY created_at DESC LIMIT 500'
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        data = []
        _diff_map = {1: '了解', 2: '理解', 3: '掌握', 4: '熟练', 5: '精通'}
        for r in rows:
            data.append({
                'point_id': r['point_id'],
                'subject': r['subject'],
                'grade': r['grade'],
                'chapter': r['chapter'],
                'point_name': r['point_name'],
                'parent_point_id': r['parent_point_id'],
                'difficulty_level': r['difficulty_level'],
                'difficulty': _diff_map.get(r['difficulty_level'], '-'),
                'description': r['description'],
                'created_at': r['created_at']
            })
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        logger.error(f'[K12] knowledge_points失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/wrong/questions', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_wrong_questions():
    """获取错题列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        user_id = _safe_int(request.args.get('user_id'))
        subject = _safe_str(request.args.get('subject'), 20)
        resolved = request.args.get('resolved', '0')
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = '''SELECT wrong_id, user_id, subject, question_id, point_id,
                     wrong_type, wrong_count, first_wrong_at, last_wrong_at,
                     resolved, note
                     FROM k12_wrong_questions'''
            params = []
            conditions = []
            if user_id is not None:
                conditions.append('user_id = ?')
                params.append(user_id)
            if subject and subject in _K12_SUBJECTS:
                conditions.append('subject = ?')
                params.append(subject)
            if resolved in ('0', '1'):
                conditions.append('resolved = ?')
                params.append(int(resolved))
            if conditions:
                sql += ' WHERE ' + ' AND '.join(conditions)
            sql += ' ORDER BY last_wrong_at DESC LIMIT 500'
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        data = []
        for r in rows:
            data.append({
                'wrong_id': r['wrong_id'],
                'user_id': r['user_id'],
                'subject': r['subject'],
                'question_id': r['question_id'],
                'point_id': r['point_id'],
                'wrong_type': r['wrong_type'],
                'wrong_count': r['wrong_count'],
                'first_wrong_at': r['first_wrong_at'],
                'last_wrong_at': r['last_wrong_at'],
                'resolved': bool(r['resolved']),
                'note': r['note']
            })
        return jsonify({'success': True, 'wrong_questions': data, 'count': len(data)})
    except Exception as e:
        logger.error(f'[K12] wrong_questions失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/home-school/messages', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_home_school_messages():
    """获取家校互动消息列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        student_user_id = _safe_int(request.args.get('student_user_id'))
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = '''SELECT message_id, student_user_id, sender_id, sender_role,
                     message_type, title, content, read_status, created_at, read_at
                     FROM k12_home_school_messages'''
            params = []
            if student_user_id is not None:
                sql += ' WHERE student_user_id = ?'
                params.append(student_user_id)
            sql += ' ORDER BY created_at DESC LIMIT 500'
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        _msg_types = {
            'study_report': '学习报告', 'behavior_feedback': '行为反馈',
            'exam_notice': '考试通知', 'homework_notice': '作业通知',
            'achievement': '表扬鼓励', 'concern': '关注提醒', 'meeting': '家长会通知'
        }
        data = []
        for r in rows:
            data.append({
                'message_id': r['message_id'],
                'student_user_id': r['student_user_id'],
                'sender_id': r['sender_id'],
                'sender_role': r['sender_role'],
                'message_type': r['message_type'],
                'message_type_name': _msg_types.get(r['message_type'], r['message_type']),
                'title': r['title'],
                'content': r['content'],
                'read_status': bool(r['read_status']),
                'created_at': r['created_at'],
                'read_at': r['read_at']
            })
        return jsonify({
            'success': True, 'messages': data, 'count': len(data),
            'unread_count': sum(1 for m in data if not m['read_status'])
        })
    except Exception as e:
        logger.error(f'[K12] home_school_messages失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/home-school/messages/<message_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_message_detail(message_id):
    """获取消息详情并标记已读"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        # 校验 message_id 格式（防注入）
        mid = _safe_str(message_id, 64)
        if not mid or not mid.startswith('msg_'):
            return jsonify({'success': False, 'error': '无效的消息ID'}), 400
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''SELECT message_id, student_user_id, sender_id, sender_role,
                              message_type, title, content, read_status, created_at, read_at
                              FROM k12_home_school_messages WHERE message_id = ?''', (mid,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'success': False, 'error': '消息不存在'}), 404
            # 标记已读
            if not row['read_status']:
                service = _get_k12_service()
                service.mark_message_read(mid)
        _msg_types = {
            'study_report': '学习报告', 'behavior_feedback': '行为反馈',
            'exam_notice': '考试通知', 'homework_notice': '作业通知',
            'achievement': '表扬鼓励', 'concern': '关注提醒', 'meeting': '家长会通知'
        }
        return jsonify({
            'success': True,
            'message': {
                'message_id': row['message_id'],
                'student_user_id': row['student_user_id'],
                'sender_id': row['sender_id'],
                'sender_role': row['sender_role'],
                'message_type': row['message_type'],
                'message_type_name': _msg_types.get(row['message_type'], row['message_type']),
                'title': row['title'],
                'content': row['content'],
                'read_status': True,
                'created_at': row['created_at'],
                'read_at': row['read_at']
            }
        })
    except Exception as e:
        logger.error(f'[K12] message_detail失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/evaluations', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_evaluations():
    """获取综合素质评价列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        user_id = _safe_int(request.args.get('user_id'))
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = '''SELECT eval_id, user_id, eval_period, moral_score,
                     intellectual_score, physical_score, aesthetic_score,
                     labor_score, total_score, eval_level, created_at
                     FROM k12_comprehensive_eval'''
            params = []
            if user_id is not None:
                sql += ' WHERE user_id = ?'
                params.append(user_id)
            sql += ' ORDER BY created_at DESC LIMIT 500'
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        data = []
        for r in rows:
            data.append({
                'eval_id': r['eval_id'],
                'user_id': r['user_id'],
                'eval_period': r['eval_period'],
                'moral_character': r['moral_score'],
                'academic_level': r['intellectual_score'],
                'physical_health': r['physical_score'],
                'artistic_accomplishment': r['aesthetic_score'],
                'social_practice': r['labor_score'],
                'total_score': r['total_score'],
                'eval_level': r['eval_level'],
                'created_at': r['created_at']
            })
        return jsonify({'success': True, 'evaluations': data, 'count': len(data)})
    except Exception as e:
        logger.error(f'[K12] evaluations失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/admission/plans', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_admission_plans():
    """获取升学计划列表"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        user_id = _safe_int(request.args.get('user_id'))
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            sql = '''SELECT record_id, user_id, exam_type, target_province,
                     target_majors, interest_type, estimated_score, actual_score,
                     admission_result, created_at
                     FROM k12_admission_records'''
            params = []
            if user_id is not None:
                sql += ' WHERE user_id = ?'
                params.append(user_id)
            sql += ' ORDER BY created_at DESC LIMIT 500'
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        data = []
        for r in rows:
            data.append({
                'record_id': r['record_id'],
                'user_id': r['user_id'],
                'exam_type': r['exam_type'],
                'target_province': r['target_province'],
                'target_majors': r['target_majors'],
                'interest_type': r['interest_type'],
                'estimated_score': r['estimated_score'],
                'actual_score': r['actual_score'],
                'admission_result': r['admission_result'],
                'created_at': r['created_at']
            })
        return jsonify({'success': True, 'plans': data, 'count': len(data)})
    except Exception as e:
        logger.error(f'[K12] admission_plans失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/game/status/<int:user_id>', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_game_status(user_id):
    """获取用户游戏状态"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    # P0越权修复(IDOR): 学生只能查本人游戏状态; 教师/管理员可查任意学生
    if not _is_staff(user) and _uid_of(user) != str(user_id):
        logger.warning(f'[K12] game_status 越权访问: uid={_uid_of(user)} 尝试查看 user_id={user_id}')
        return jsonify({'success': False, 'error': '无权查看他人游戏状态'}), 403
    try:
        service = _get_game_service()
        return jsonify(service.get_user_game_status(user_id))
    except Exception as e:
        logger.error(f'[K12] game_status失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# 写操作类接口
# ============================================================================

@k12_bp.route('/student/profile', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_create_student_profile():
    """创建学生档案（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        grade = _safe_str(data.get('grade'), 4)
        if user_id is None or not grade or grade not in _K12_GRADES:
            return jsonify({'success': False, 'error': 'user_id和grade(1-12)为必填项'}), 400
        subjects = data.get('subjects')
        if subjects is not None:
            if not isinstance(subjects, list):
                return jsonify({'success': False, 'error': 'subjects必须为列表'}), 400
            subjects = [s for s in subjects if isinstance(s, str) and s in _K12_SUBJECTS]
            if not subjects:
                subjects = None
        parent_user_id = _safe_int(data.get('parent_user_id'), min_val=1, max_val=999999999)
        class_id = _safe_str(data.get('class_id'), 50)
        service = _get_k12_service()
        return jsonify(service.create_student_profile(
            user_id, grade, subjects=subjects,
            parent_user_id=parent_user_id, class_id=class_id
        ))
    except Exception as e:
        logger.error(f'[K12] create_student_profile失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/knowledge/points', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_add_knowledge_point():
    """添加知识点（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        subject = _safe_str(data.get('subject'), 20)
        grade = _safe_str(data.get('grade'), 4)
        point_name = _safe_str(data.get('point_name'), 100)
        if not subject or subject not in _K12_SUBJECTS:
            return jsonify({'success': False, 'error': 'subject不在白名单内'}), 400
        if not grade or grade not in _K12_GRADES:
            return jsonify({'success': False, 'error': 'grade(1-12)为必填项'}), 400
        if not point_name:
            return jsonify({'success': False, 'error': 'point_name为必填项'}), 400
        chapter = _safe_str(data.get('chapter'), 100)
        difficulty_level = _safe_int(data.get('difficulty_level'), default=2, min_val=1, max_val=5)
        if difficulty_level not in _K12_DIFFICULTY:
            difficulty_level = 2
        description = _safe_str(data.get('description'), 500)
        service = _get_k12_service()
        return jsonify(service.add_knowledge_point(
            subject, grade, point_name, chapter=chapter,
            difficulty_level=difficulty_level, description=description
        ))
    except Exception as e:
        logger.error(f'[K12] add_knowledge_point失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/wrong/questions', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_add_wrong_question():
    """添加错题（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        subject = _safe_str(data.get('subject'), 20)
        question_id = _safe_str(data.get('question_id'), 64)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not subject or subject not in _K12_SUBJECTS:
            return jsonify({'success': False, 'error': 'subject不在白名单内'}), 400
        if not question_id:
            return jsonify({'success': False, 'error': 'question_id为必填项'}), 400
        point_id = _safe_str(data.get('point_id'), 64)
        wrong_type = _safe_str(data.get('wrong_type'), 30)
        if not wrong_type or wrong_type not in _K12_WRONG_TYPES:
            wrong_type = 'concept_error'
        note = _safe_str(data.get('note'), 500)
        service = _get_k12_service()
        return jsonify(service.add_wrong_question(
            user_id, subject, question_id, point_id=point_id,
            wrong_type=wrong_type, note=note
        ))
    except Exception as e:
        logger.error(f'[K12] add_wrong_question失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/home-school/message', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_send_home_school_message():
    """发送家校互动消息（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        student_user_id = _safe_int(data.get('student_user_id'), min_val=1, max_val=999999999)
        sender_id = _safe_int(data.get('sender_id'), min_val=1, max_val=999999999)
        sender_role = _safe_str(data.get('sender_role'), 20)
        message_type = _safe_str(data.get('message_type'), 30)
        title = _safe_str(data.get('title'), 200)
        content = _safe_str(data.get('content'), 2000)
        if student_user_id is None or sender_id is None:
            return jsonify({'success': False, 'error': 'student_user_id和sender_id为必填项'}), 400
        if not sender_role or sender_role not in _K12_SENDER_ROLES:
            return jsonify({'success': False, 'error': 'sender_role不在白名单内'}), 400
        if not message_type or message_type not in _K12_MESSAGE_TYPES:
            return jsonify({'success': False, 'error': 'message_type不在白名单内'}), 400
        if not title or not content:
            return jsonify({'success': False, 'error': 'title和content为必填项'}), 400
        service = _get_k12_service()
        return jsonify(service.send_home_school_message(
            student_user_id, sender_id, sender_role,
            message_type, title, content
        ))
    except Exception as e:
        logger.error(f'[K12] send_home_school_message失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/evaluation', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_create_evaluation():
    """创建综合素质评价（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        eval_period = _safe_str(data.get('eval_period'), 30)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not eval_period:
            return jsonify({'success': False, 'error': 'eval_period为必填项'}), 400
        # eval_period 格式校验（防注入：只允许 年-学期 格式）
        import re
        if not re.match(r'^[\u4e00-\u9fa5\w\-]{1,30}$', eval_period):
            return jsonify({'success': False, 'error': 'eval_period格式非法'}), 400
        created_by = _safe_int(data.get('created_by'), min_val=1, max_val=999999999)
        service = _get_eval_service()
        return jsonify(service.create_evaluation(user_id, eval_period, created_by=created_by))
    except Exception as e:
        logger.error(f'[K12] create_evaluation失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/admission/plan', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_set_admission_plan():
    """设置升学计划（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        exam_type = _safe_str(data.get('exam_type'), 20)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not exam_type or exam_type not in _K12_EXAM_TYPES:
            return jsonify({'success': False, 'error': 'exam_type不在白名单内'}), 400
        target_province = _safe_str(data.get('target_province'), 30)
        estimated_score = _safe_int(data.get('estimated_score'), min_val=0, max_val=999)
        interest_type = _safe_str(data.get('interest_type'), 20)
        if interest_type and interest_type not in _K12_INTEREST_TYPES:
            interest_type = None
        service = _get_admission_service()
        return jsonify(service.set_admission_plan(
            user_id, exam_type, target_province or '',
            estimated_score or 0, interest_type=interest_type
        ))
    except Exception as e:
        logger.error(f'[K12] set_admission_plan失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/wrong/questions/<wrong_id>/resolve', methods=['PUT'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_resolve_wrong_question(wrong_id):
    """标记错题为已解决（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        wid = _safe_str(wrong_id, 64)
        if not wid or not wid.startswith('wq_'):
            return jsonify({'success': False, 'error': '无效的错题ID'}), 400
        service = _get_k12_service()
        return jsonify(service.resolve_wrong_question(wid))
    except Exception as e:
        logger.error(f'[K12] resolve_wrong_question失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/student/tier', methods=['PUT'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_update_tier():
    """更新学习分层（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        tier = _safe_str(data.get('tier'), 4)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not tier or tier not in _K12_TIERS:
            return jsonify({'success': False, 'error': 'tier必须为A/B/C'}), 400
        subject = _safe_str(data.get('subject'), 20)
        if subject and subject not in _K12_SUBJECTS:
            subject = None
        service = _get_k12_service()
        return jsonify(service.update_learning_tier(user_id, tier, subject=subject))
    except Exception as e:
        logger.error(f'[K12] update_tier失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/knowledge/points/<point_id>', methods=['DELETE'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_delete_knowledge_point(point_id):
    """删除知识点（管理员）"""
    user = _current_safe_user()
    ok, err = _check_admin(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        pid = _safe_str(point_id, 64)
        if not pid or not pid.startswith('kp_'):
            return jsonify({'success': False, 'error': '无效的知识点ID'}), 400
        db_path = _get_db_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM k12_knowledge_points WHERE point_id = ?', (pid,))
            deleted = cursor.rowcount
            conn.commit()
        if deleted == 0:
            return jsonify({'success': False, 'error': '知识点不存在'}), 404
        logger.info(f'[K12] 删除知识点: {pid}')
        return jsonify({'success': True, 'point_id': pid, 'deleted': deleted})
    except Exception as e:
        logger.error(f'[K12] delete_knowledge_point失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@k12_bp.route('/game/points', methods=['POST'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def k12_add_game_points():
    """添加游戏积分（登录即可）"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        data = request.get_json(silent=True) or {}
        user_id = _safe_int(data.get('user_id'), min_val=1, max_val=999999999)
        transaction_type = _safe_str(data.get('transaction_type'), 30)
        points = _safe_int(data.get('points'), min_val=-100, max_val=10000)
        if user_id is None:
            return jsonify({'success': False, 'error': 'user_id为必填项'}), 400
        if not transaction_type or transaction_type not in _K12_TRANSACTION_TYPES:
            return jsonify({'success': False, 'error': 'transaction_type不在白名单内'}), 400
        if points is None or points == 0:
            return jsonify({'success': False, 'error': 'points必须为非零整数'}), 400
        # P0越权/刷分修复:
        #  ① manual_adjust(人工调整)仅教职人员可用; 学生不得手工调分
        #  ② 非教职人员只能给自己加积分(改 user_id 给他人加/刷分 → 403)
        staff = _is_staff(user)
        if transaction_type == 'manual_adjust' and not staff:
            logger.warning(f'[K12] game_points 越权: uid={_uid_of(user)} 尝试 manual_adjust')
            return jsonify({'success': False, 'error': 'manual_adjust 仅教师/管理员可用'}), 403
        if not staff and _uid_of(user) != str(user_id):
            logger.warning(f'[K12] game_points 越权: uid={_uid_of(user)} 尝试给 user_id={user_id} 加分')
            return jsonify({'success': False, 'error': '只能给自己的账号加积分'}), 403
        description = _safe_str(data.get('description'), 200)
        related_activity = _safe_str(data.get('related_activity'), 100)
        service = _get_game_service()
        return jsonify(service.add_points(
            user_id, transaction_type, points,
            description=description or '', related_activity=related_activity or ''
        ))
    except Exception as e:
        logger.error(f'[K12] add_game_points失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


bp = Blueprint('k12_management_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
@system_container(page_name='(auto)', require_auth='login', allowed_roles=['teacher', 'school_admin', 'admin', 'super_admin'])
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'k12_management','routes_implemented':1}})

