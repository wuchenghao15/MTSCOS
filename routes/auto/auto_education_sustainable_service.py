"""自动生成的路由蓝图 - education_sustainable_service"""
from flask import Blueprint, jsonify, request
from services.education_sustainable_service import EducationSustainableService
from app.middlewares.system_container import system_container

education_sustainable_service_bp = Blueprint('education_sustainable_service_bp', __name__, url_prefix='/api/education/sustainable/service')

@education_sustainable_service_bp.route('/create_sustainability_project', methods=['POST'])
@system_container()
def create_sustainability_project():
    """"""
    data = request.get_json() or {}
    kwargs = {'project_name': data.get('project_name'), 'goal_type': data.get('goal_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.create_sustainability_project(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/add_project_activity', methods=['POST'])
@system_container()
def add_project_activity():
    """"""
    data = request.get_json() or {}
    kwargs = {'project_id': data.get('project_id'), 'activity_name': data.get('activity_name'), 'activity_date': data.get('activity_date')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.add_project_activity(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/update_project_status/<int:item_id>', methods=['PUT'])
@system_container()
def update_project_status(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'project_id': data.get('project_id'), 'status': data.get('status')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.update_project_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/list_sustainability_projects', methods=['GET'])
@system_container()
def list_sustainability_projects():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'status': request.args.get('status'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.list_sustainability_projects(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/create_carbon_tracking', methods=['POST'])
@system_container()
def create_carbon_tracking():
    """"""
    data = request.get_json() or {}
    kwargs = {'category': data.get('category'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.create_carbon_tracking(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/record_carbon_data', methods=['POST'])
@system_container()
def record_carbon_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'tracking_id': data.get('tracking_id'), 'record_date': data.get('record_date'), 'emission_value': data.get('emission_value')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.record_carbon_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/verify_carbon_data', methods=['POST'])
@system_container()
def verify_carbon_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'data_id': data.get('data_id'), 'verified': data.get('verified')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.verify_carbon_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/get_carbon_summary', methods=['GET'])
@system_container()
def get_carbon_summary():
    """"""
    kwargs = {'tracking_id': request.args.get('tracking_id'), 'start_date': request.args.get('start_date'), 'end_date': request.args.get('end_date')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.get_carbon_summary(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/create_green_initiative', methods=['POST'])
@system_container()
def create_green_initiative():
    """"""
    data = request.get_json() or {}
    kwargs = {'initiative_type': data.get('initiative_type'), 'education_type': data.get('education_type'), 'name': data.get('name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.create_green_initiative(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/update_initiative_progress/<int:item_id>', methods=['PUT'])
@system_container()
def update_initiative_progress(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'initiative_id': data.get('initiative_id'), 'report_date': data.get('report_date'), 'progress': data.get('progress')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.update_initiative_progress(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/list_green_initiatives', methods=['GET'])
@system_container()
def list_green_initiatives():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'initiative_type': request.args.get('initiative_type'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.list_green_initiatives(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/get_initiative_progress', methods=['GET'])
@system_container()
def get_initiative_progress():
    """"""
    kwargs = {'initiative_id': request.args.get('initiative_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.get_initiative_progress(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/create_environmental_course', methods=['POST'])
@system_container()
def create_environmental_course():
    """"""
    data = request.get_json() or {}
    kwargs = {'ee_type': data.get('ee_type'), 'education_type': data.get('education_type'), 'course_name': data.get('course_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.create_environmental_course(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/create_education_program', methods=['POST'])
@system_container()
def create_education_program():
    """"""
    data = request.get_json() or {}
    kwargs = {'ee_id': data.get('ee_id'), 'program_name': data.get('program_name'), 'start_date': data.get('start_date')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.create_education_program(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_sustainable_service_bp.route('/enroll_program', methods=['POST'])
@system_container()
def enroll_program():
    """"""
    data = request.get_json() or {}
    kwargs = {'program_id': data.get('program_id'), 'participant_count': data.get('participant_count')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSustainableService()
        result = service.enroll_program(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
