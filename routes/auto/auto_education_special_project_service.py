"""自动生成的路由蓝图 - education_special_project_service"""
from flask import Blueprint, jsonify, request
from services.education_special_project_service import EducationSpecialProjectService
from app.middlewares.system_container import system_container

education_special_project_service_bp = Blueprint('education_special_project_service_bp', __name__, url_prefix='/api/education/special/project/service')

@education_special_project_service_bp.route('/create_special_project', methods=['POST'])
@system_container()
def create_special_project():
    """"""
    data = request.get_json() or {}
    kwargs = {'project_name': data.get('project_name'), 'project_type': data.get('project_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.create_special_project(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/update_project_stage/<int:item_id>', methods=['PUT'])
@system_container()
def update_project_stage(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'project_id': data.get('project_id'), 'stage': data.get('stage')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.update_project_stage(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/get_project_details', methods=['GET'])
@system_container()
def get_project_details():
    """"""
    kwargs = {'project_id': request.args.get('project_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.get_project_details(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/archive_project', methods=['POST'])
@system_container()
def archive_project():
    """"""
    data = request.get_json() or {}
    kwargs = {'project_id': data.get('project_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.archive_project(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/create_curriculum', methods=['POST'])
@system_container()
def create_curriculum():
    """"""
    data = request.get_json() or {}
    kwargs = {'curriculum_name': data.get('curriculum_name'), 'curriculum_type': data.get('curriculum_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.create_curriculum(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/publish_curriculum', methods=['POST'])
@system_container()
def publish_curriculum():
    """"""
    data = request.get_json() or {}
    kwargs = {'curriculum_id': data.get('curriculum_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.publish_curriculum(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/list_curriculum', methods=['GET'])
@system_container()
def list_curriculum():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'curriculum_type': request.args.get('curriculum_type'), 'status': request.args.get('status'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.list_curriculum(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/update_curriculum/<int:item_id>', methods=['PUT'])
@system_container()
def update_curriculum(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'curriculum_id': data.get('curriculum_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.update_curriculum(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/create_project_learning', methods=['POST'])
@system_container()
def create_project_learning():
    """"""
    data = request.get_json() or {}
    kwargs = {'project_id': data.get('project_id'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.create_project_learning(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/create_learning_group', methods=['POST'])
@system_container()
def create_learning_group():
    """"""
    data = request.get_json() or {}
    kwargs = {'learning_id': data.get('learning_id'), 'group_name': data.get('group_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.create_learning_group(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/submit_deliverable', methods=['POST'])
@system_container()
def submit_deliverable():
    """"""
    data = request.get_json() or {}
    kwargs = {'learning_id': data.get('learning_id'), 'group_id': data.get('group_id'), 'title': data.get('title')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.submit_deliverable(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/evaluate_deliverable', methods=['POST'])
@system_container()
def evaluate_deliverable():
    """"""
    data = request.get_json() or {}
    kwargs = {'deliverable_id': data.get('deliverable_id'), 'score': data.get('score')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.evaluate_deliverable(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/create_special_activity', methods=['POST'])
@system_container()
def create_special_activity():
    """"""
    data = request.get_json() or {}
    kwargs = {'activity_name': data.get('activity_name'), 'category': data.get('category'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.create_special_activity(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/register_activity', methods=['POST'])
@system_container()
def register_activity():
    """"""
    data = request.get_json() or {}
    kwargs = {'activity_id': data.get('activity_id'), 'participant_id': data.get('participant_id'), 'participant_name': data.get('participant_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.register_activity(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_special_project_service_bp.route('/record_activity_attendance', methods=['POST'])
@system_container()
def record_activity_attendance():
    """"""
    data = request.get_json() or {}
    kwargs = {'activity_id': data.get('activity_id'), 'participant_id': data.get('participant_id'), 'attended': data.get('attended')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSpecialProjectService()
        result = service.record_activity_attendance(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
