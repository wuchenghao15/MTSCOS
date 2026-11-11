#!/usr/bin/env python3
from functools import wraps
from flask import session, redirect, jsonify, request

def require_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': '未登录', 'code': 401}), 401
            return redirect('/auth/login')
        return f(*args, **kwargs)
    return decorated_function

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/auth/login')
        role = session.get('role', 'guest')
        if role not in ['admin', 'super_admin', 'system_admin', 'hardware_admin', 'hardware_vikey_admin']:
            return jsonify({'success': False, 'error': '权限不足'}), 403
        return f(*args, **kwargs)
    return decorated_function

def require_super_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/auth/login')
        role = session.get('role', 'guest')
        if role != 'super_admin':
            return jsonify({'success': False, 'error': '权限不足'}), 403
        return f(*args, **kwargs)
    return decorated_function

def require_role(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect('/auth/login')
            role = session.get('role', 'guest')
            if role not in allowed_roles:
                return jsonify({'success': False, 'error': '权限不足'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def allow_guest_access(f):
    """允许访客（未登录用户）访问的装饰器。

    用于公开 API 端点（如题目列表浏览、公共信息查询等），
    不做任何登录或权限检查，直接放行。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function