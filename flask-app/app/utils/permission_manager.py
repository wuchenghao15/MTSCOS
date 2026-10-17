#!/usr/bin/env python3
import logging
from enum import IntEnum

logger = logging.getLogger(__name__)


class SecurityClassification(IntEnum):
    """Protected-data levels; lower values require stronger clearance."""

    TOP_SECRET = 0
    CONFIDENTIAL = 1
    SECRET = 2


CLASSIFICATION_ALIASES = {
    '极密': SecurityClassification.TOP_SECRET,
    'top_secret': SecurityClassification.TOP_SECRET,
    'l0': SecurityClassification.TOP_SECRET,
    '机密': SecurityClassification.CONFIDENTIAL,
    'confidential': SecurityClassification.CONFIDENTIAL,
    'l1': SecurityClassification.CONFIDENTIAL,
    '秘密': SecurityClassification.SECRET,
    'secret': SecurityClassification.SECRET,
    'l2': SecurityClassification.SECRET,
}


ROLE_CLEARANCE = {
    'super_admin': SecurityClassification.TOP_SECRET,
    'system_admin': SecurityClassification.CONFIDENTIAL,
    'admin': SecurityClassification.CONFIDENTIAL,
    'sysadmin': SecurityClassification.CONFIDENTIAL,
    'hardware_admin': SecurityClassification.CONFIDENTIAL,
    'hardware_vikey_admin': SecurityClassification.CONFIDENTIAL,
}


def normalize_classification(level):
    """Return a supported classification or raise ValueError for bad input."""
    if isinstance(level, SecurityClassification):
        return level
    if isinstance(level, int) and level in range(3):
        return SecurityClassification(level)
    if isinstance(level, str):
        key = level.strip().lower()
        if key in CLASSIFICATION_ALIASES:
            return CLASSIFICATION_ALIASES[key]
    raise ValueError(f'不支持的密级: {level!r}')


class PermissionManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._permissions = {
                'super_admin': ['*'],
                'system_admin': ['manage_users', 'manage_exams', 'manage_courses', 'manage_settings',
                                 'view_users', 'view_exams', 'view_courses', 'view_settings',
                                 'view_notifications', 'view_data_analysis', 'view_ai_center'],
                'admin': ['manage_users', 'manage_exams', 'manage_courses', 'manage_settings',
                          'view_users', 'view_exams', 'view_courses', 'view_settings',
                          'view_notifications', 'view_data_analysis', 'view_ai_center',
                          'view_resource_manager', 'view_monitor', 'view_health_monitor'],
                'hardware_admin': ['view_exams', 'view_courses', 'view_profile', 'view_monitor'],
                'hardware_vikey_admin': ['view_exams', 'view_courses', 'view_profile', 'view_monitor'],
                'designer': ['manage_courses', 'view_courses', 'view_exams', 'view_profile'],
                'teacher': ['view_exams', 'view_courses', 'view_notifications', 'view_profile',
                            'manage_exams', 'view_students'],
                'student_vip': ['view_exams', 'view_courses', 'view_profile', 'view_ai_tutor'],
                'student': ['view_exams', 'view_courses', 'view_profile'],
                'user': ['view_profile'],
                'guest': [],
                'school_admin': ['manage_users', 'manage_courses', 'view_users', 'view_exams',
                                 'view_courses', 'view_notifications', 'view_students',
                                 'view_data_analysis', 'view_profile'],
                'teacher_admin': ['manage_users', 'view_users', 'view_exams', 'view_courses',
                                  'view_notifications', 'view_students', 'view_profile'],
                'sysadmin': ['manage_settings', 'view_users', 'view_settings', 'view_monitor',
                             'view_health_monitor', 'view_profile'],
                'cluster_manager': ['view_monitor', 'view_profile', 'cluster_manage'],
                'ai_manager': ['view_ai_center', 'ai_manage', 'ai_model_manage', 'view_profile'],
                'question_manager': ['question_bank_manage', 'view_exams', 'view_courses',
                                      'view_profile'],
                'exam_proctor': ['manage_exams', 'exam_proctor', 'view_exams', 'view_profile'],
                'parent': ['view_exams', 'view_courses', 'view_students', 'parent_communication',
                           'view_profile'],
                'parent_vip': ['view_exams', 'view_courses', 'view_students',
                               'parent_communication', 'view_profile']
            }
        return cls._instance

    def has_permission(self, user_id, permission):
        from flask import session
        role = session.get('role', 'guest')
        role_perms = self._permissions.get(role, [])
        if '*' in role_perms:
            return is_super_admin({
                'username': session.get('username'),
                'role': role,
            })
        return permission in role_perms

    def get_permissions(self, role):
        return self._permissions.get(role, [])

    def get_user_permissions(self, user_id):
        from flask import session
        role = session.get('role', 'guest')
        return self.get_permissions(role)

    def check_role_access(self, required_roles):
        from flask import session
        role = session.get('role', 'guest')
        if '*' in required_roles:
            return True
        if role == 'super_admin' and not is_super_admin({
            'username': session.get('username'),
            'role': role,
        }):
            return False
        return role in required_roles

    def can_access_classification(self, level, *, require_vikey=False):
        """Check session clearance for protected data without exposing its value."""
        from flask import session

        try:
            requested = normalize_classification(level)
        except ValueError:
            logger.warning('拒绝未知密级访问请求')
            return False

        role = session.get('role_canonical') or session.get('role', 'guest')
        if not session.get('logged_in') or role not in ROLE_CLEARANCE:
            return False

        if requested == SecurityClassification.TOP_SECRET:
            if not is_super_admin({
                'username': session.get('username'),
                'role': role,
            }) or not session.get('_sa_session', False):
                return False

        return ROLE_CLEARANCE[role] <= requested

class HardwareAuthManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._authorized = True
        return cls._instance

    def is_authorized(self):
        return self._authorized

    def authorize(self, hardware_key):
        self._authorized = True
        return True

    def revoke(self):
        self._authorized = False
        return True

def get_permission_manager():
    return PermissionManager()

def get_hardware_auth_manager():
    return HardwareAuthManager()

def is_super_admin(user):
    """
    判断用户是否为超级管理员
    依据PERM_SUPER_ADMIN_UNIQUE_USER规则，只有配置的唯一用户才是真正的super_admin
    """
    if not user:
        return False
    
    username = user.get('username') if isinstance(user, dict) else getattr(user, 'username', None)
    role = user.get('role') if isinstance(user, dict) else getattr(user, 'role', None)
    
    if not username or role != 'super_admin':
        return False
    
    try:
        import sqlite3
        from app import DATABASE_PATH
        
        with sqlite3.connect(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT rule_value FROM system_rules WHERE rule_code = ?', 
                         ('PERM_SUPER_ADMIN_UNIQUE_USER',))
            result = cursor.fetchone()
            
            if result and result[0] == username:
                return True
            return False
    except Exception as e:
        logger.error(f"检查超级管理员失败: {e}")
        return False
