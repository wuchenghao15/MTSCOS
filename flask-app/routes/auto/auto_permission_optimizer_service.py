"""自动生成的路由蓝图 - permission_optimizer_service"""
from flask import Blueprint, jsonify, request
from services.permission_optimizer_service import PermissionOptimizerService
from app.middlewares.system_container import system_container

permission_optimizer_service_bp = Blueprint('permission_optimizer_service_bp', __name__, url_prefix='/api/permission/optimizer/service')

@permission_optimizer_service_bp.route('/get_user_roles', methods=['GET'])
@system_container()
def get_user_roles():
    """获取用户角色列表"""
    kwargs = {'user_id': request.args.get('user_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_user_roles(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_user_permissions', methods=['GET'])
@system_container()
def get_user_permissions():
    """获取用户所有权限（合并所有角色的权限）"""
    kwargs = {'user_id': request.args.get('user_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_user_permissions(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/check_permission', methods=['POST'])
@system_container()
def check_permission():
    """检查用户是否拥有某项权限"""
    data = request.get_json() or {}
    kwargs = {'user_id': data.get('user_id'), 'permission_code': data.get('permission_code')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.check_permission(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_accessible_modules', methods=['GET'])
@system_container()
def get_accessible_modules():
    """获取用户可访问的模块列表（用于侧边栏菜单生成）"""
    kwargs = {'user_id': request.args.get('user_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_accessible_modules(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_module_buttons', methods=['GET'])
@system_container()
def get_module_buttons():
    """获取模块下的所有按钮"""
    kwargs = {'module_code': request.args.get('module_code')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_module_buttons(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_all_buttons', methods=['GET'])
@system_container()
def get_all_buttons():
    """获取所有按钮"""
    try:
        service = PermissionOptimizerService()
        result = service.get_all_buttons()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/add_button', methods=['POST'])
@system_container()
def add_button():
    """添加按钮"""
    data = request.get_json() or {}
    kwargs = {'module_code': data.get('module_code'), 'button_name': data.get('button_name'), 'button_code': data.get('button_code'), 'button_label': data.get('button_label'), 'parent_button_id': data.get('parent_button_id'), 'sort_order': data.get('sort_order')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.add_button(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/check_button_permission', methods=['POST'])
@system_container()
def check_button_permission():
    """检查用户是否拥有按钮权限"""
    data = request.get_json() or {}
    kwargs = {'user_id': data.get('user_id'), 'module_code': data.get('module_code'), 'button_code': data.get('button_code')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.check_button_permission(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_user_button_permissions', methods=['GET'])
@system_container()
def get_user_button_permissions():
    """获取用户所有按钮权限"""
    kwargs = {'user_id': request.args.get('user_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_user_button_permissions(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/delete_button/<int:item_id>', methods=['DELETE'])
@system_container()
def delete_button(item_id):
    """删除按钮"""
    data = request.get_json() or {}
    kwargs = {'button_id': data.get('button_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.delete_button(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_data_rules', methods=['GET'])
@system_container()
def get_data_rules():
    """获取数据权限规则"""
    kwargs = {'role_code': request.args.get('role_code'), 'module_code': request.args.get('module_code')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_data_rules(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/get_user_data_permission', methods=['GET'])
@system_container()
def get_user_data_permission():
    """获取用户在指定模块的数据权限"""
    kwargs = {'user_id': request.args.get('user_id'), 'module_code': request.args.get('module_code')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.get_user_data_permission(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/update_data_rule/<int:item_id>', methods=['PUT'])
@system_container()
def update_data_rule(item_id):
    """更新数据权限规则"""
    data = request.get_json() or {}
    kwargs = {'role_code': data.get('role_code'), 'module_code': data.get('module_code'), 'data_scope': data.get('data_scope'), 'data_level': data.get('data_level'), 'special_rules': data.get('special_rules')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.update_data_rule(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/update_data_rule_by_id/<int:item_id>', methods=['PUT'])
@system_container()
def update_data_rule_by_id(item_id):
    """通过ID更新数据权限规则"""
    data = request.get_json() or {}
    kwargs = {'rule_id': data.get('rule_id'), 'data_scope': data.get('data_scope'), 'data_level': data.get('data_level')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.update_data_rule_by_id(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@permission_optimizer_service_bp.route('/delete_data_rule/<int:item_id>', methods=['DELETE'])
@system_container()
def delete_data_rule(item_id):
    """删除数据权限规则"""
    data = request.get_json() or {}
    kwargs = {'rule_id': data.get('rule_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = PermissionOptimizerService()
        result = service.delete_data_rule(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
