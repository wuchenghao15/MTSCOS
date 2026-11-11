"""自动生成的路由蓝图 - education_accreditation_service"""
from flask import Blueprint, jsonify, request
from services.education_accreditation_service import EducationAccreditationService
from app.middlewares.system_container import system_container

education_accreditation_service_bp = Blueprint('education_accreditation_service_bp', __name__, url_prefix='/api/education/accreditation/service')

@education_accreditation_service_bp.route('/create_accreditation_program', methods=['POST'])
@system_container()
def create_accreditation_program():
    """"""
    data = request.get_json() or {}
    kwargs = {'program_name': data.get('program_name'), 'accreditation_type': data.get('accreditation_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.create_accreditation_program(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/update_program_status/<int:item_id>', methods=['PUT'])
@system_container()
def update_program_status(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'program_id': data.get('program_id'), 'status': data.get('status')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.update_program_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/get_program_detail', methods=['GET'])
@system_container()
def get_program_detail():
    """"""
    kwargs = {'program_id': request.args.get('program_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.get_program_detail(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/list_programs', methods=['GET'])
@system_container()
def list_programs():
    """"""
    kwargs = {'accreditation_type': request.args.get('accreditation_type'), 'education_type': request.args.get('education_type'), 'status': request.args.get('status'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.list_programs(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/create_standard', methods=['POST'])
@system_container()
def create_standard():
    """"""
    data = request.get_json() or {}
    kwargs = {'standard_name': data.get('standard_name'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.create_standard(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/add_criteria', methods=['POST'])
@system_container()
def add_criteria():
    """"""
    data = request.get_json() or {}
    kwargs = {'standard_id': data.get('standard_id'), 'dimension': data.get('dimension'), 'criteria_name': data.get('criteria_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.add_criteria(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/get_standard_criteria', methods=['GET'])
@system_container()
def get_standard_criteria():
    """"""
    kwargs = {'standard_id': request.args.get('standard_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.get_standard_criteria(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/apply_school_accreditation/<int:item_id>', methods=['PUT'])
@system_container()
def apply_school_accreditation(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'school_id': data.get('school_id'), 'school_name': data.get('school_name'), 'program_id': data.get('program_id'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.apply_school_accreditation(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/review_school_accreditation/<int:item_id>', methods=['PUT'])
@system_container()
def review_school_accreditation(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'accreditation_id': data.get('accreditation_id'), 'overall_score': data.get('overall_score'), 'decision': data.get('decision')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.review_school_accreditation(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/schedule_site_visit', methods=['POST'])
@system_container()
def schedule_site_visit():
    """"""
    data = request.get_json() or {}
    kwargs = {'accreditation_id': data.get('accreditation_id'), 'school_id': data.get('school_id'), 'visit_date': data.get('visit_date')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.schedule_site_visit(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/upload_evidence', methods=['POST'])
@system_container()
def upload_evidence():
    """"""
    data = request.get_json() or {}
    kwargs = {'accreditation_id': data.get('accreditation_id'), 'document_name': data.get('document_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.upload_evidence(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/get_school_accreditation_status/<int:item_id>', methods=['PUT'])
@system_container()
def get_school_accreditation_status(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'school_id': data.get('school_id'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.get_school_accreditation_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/apply_program_accreditation/<int:item_id>', methods=['PUT'])
@system_container()
def apply_program_accreditation(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'program_id': data.get('program_id'), 'program_name': data.get('program_name'), 'school_id': data.get('school_id'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.apply_program_accreditation(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/assess_program', methods=['POST'])
@system_container()
def assess_program():
    """"""
    data = request.get_json() or {}
    kwargs = {'accreditation_id': data.get('accreditation_id'), 'overall_score': data.get('overall_score')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.assess_program(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_accreditation_service_bp.route('/renew_program_accreditation', methods=['POST'])
@system_container()
def renew_program_accreditation():
    """"""
    data = request.get_json() or {}
    kwargs = {'accreditation_id': data.get('accreditation_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAccreditationService()
        result = service.renew_program_accreditation(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
