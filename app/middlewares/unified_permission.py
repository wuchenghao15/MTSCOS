#!/usr/bin/env python3

def get_redirect_url_for_role(role):
    """角色登录后智能重定向：基于角色自动跳转到最合适的首页"""
    role_map = {
        'super_admin': '/smart_dashboard',
        'admin': '/admin_app/dashboard_unified',
        'sadmin': '/smart_dashboard',
        'hardware_admin': '/smart_dashboard',
        'school_admin': '/admin_app/dashboard_unified',
        'sysadmin': '/admin_app/dashboard_unified',
        'teacher': '/student_portal',
        'teacher_admin': '/admin_app/dashboard_unified',
        'student': '/student_portal',
        'student_vip': '/student_portal',
        '成人学生': '/student_portal',
        'parent': '/student_portal',
        '家长': '/student_portal',
        'ai_manager': '/admin_app/ai_employee_dashboard',
        'cluster_manager': '/admin_app/neural_array_matrix',
        'question_manager': '/admin_app/intelligent_question_bank',
        'exam_proctor': '/admin_app/exams',
    }
    return role_map.get(role, '/dashboard')