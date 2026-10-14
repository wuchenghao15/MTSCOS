"""自动生成的路由蓝图 - education_supervision_service"""
from flask import Blueprint, jsonify, request
from services.education_supervision_service import EducationSupervisionService
from app.middlewares.system_container import system_container

education_supervision_service_bp = Blueprint('education_supervision_service_bp', __name__, url_prefix='/api/education/supervision/service')

@education_supervision_service_bp.route('/create_supervision_plan', methods=['POST'])
@system_container()
def create_supervision_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_name': data.get('plan_name'), 'supervision_type': data.get('supervision_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.create_supervision_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/approve_supervision_plan', methods=['POST'])
@system_container()
def approve_supervision_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'approved_by': data.get('approved_by'), 'approved': data.get('approved')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.approve_supervision_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/publish_supervision_plan', methods=['POST'])
@system_container()
def publish_supervision_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.publish_supervision_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/list_supervision_plans', methods=['GET'])
@system_container()
def list_supervision_plans():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'status': request.args.get('status'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.list_supervision_plans(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/create_supervision_task', methods=['POST'])
@system_container()
def create_supervision_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'task_name': data.get('task_name'), 'assignee_id': data.get('assignee_id'), 'assignee_name': data.get('assignee_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.create_supervision_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/assign_supervision_task', methods=['POST'])
@system_container()
def assign_supervision_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id'), 'assignee_id': data.get('assignee_id'), 'assignee_name': data.get('assignee_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.assign_supervision_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/complete_supervision_task', methods=['POST'])
@system_container()
def complete_supervision_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.complete_supervision_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/archive_supervision_task', methods=['POST'])
@system_container()
def archive_supervision_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.archive_supervision_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/create_supervision_team', methods=['POST'])
@system_container()
def create_supervision_team():
    """"""
    data = request.get_json() or {}
    kwargs = {'team_name': data.get('team_name'), 'leader_id': data.get('leader_id'), 'leader_name': data.get('leader_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.create_supervision_team(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/add_team_member', methods=['POST'])
@system_container()
def add_team_member():
    """"""
    data = request.get_json() or {}
    kwargs = {'team_id': data.get('team_id'), 'member_id': data.get('member_id'), 'member_name': data.get('member_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.add_team_member(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/list_team_members', methods=['GET'])
@system_container()
def list_team_members():
    """"""
    kwargs = {'team_id': request.args.get('team_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.list_team_members(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/create_supervision_record', methods=['POST'])
@system_container()
def create_supervision_record():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id'), 'school_id': data.get('school_id'), 'school_name': data.get('school_name'), 'education_type': data.get('education_type'), 'supervisor_id': data.get('supervisor_id'), 'supervisor_name': data.get('supervisor_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.create_supervision_record(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/update_supervision_record/<int:item_id>', methods=['PUT'])
@system_container()
def update_supervision_record(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'record_id': data.get('record_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.update_supervision_record(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/submit_supervision_record', methods=['POST'])
@system_container()
def submit_supervision_record():
    """"""
    data = request.get_json() or {}
    kwargs = {'record_id': data.get('record_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.submit_supervision_record(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_supervision_service_bp.route('/approve_supervision_record', methods=['POST'])
@system_container()
def approve_supervision_record():
    """"""
    data = request.get_json() or {}
    kwargs = {'record_id': data.get('record_id'), 'approved': data.get('approved')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSupervisionService()
        result = service.approve_supervision_record(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
