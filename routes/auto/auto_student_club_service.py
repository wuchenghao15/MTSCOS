"""自动生成的路由蓝图 - student_club_service"""
from flask import Blueprint, jsonify, request
from services.student_club_service import StudentClubService
from app.middlewares.system_container import system_container

student_club_service_bp = Blueprint('student_club_service_bp', __name__, url_prefix='/api/student/club/service')

@student_club_service_bp.route('/create_club', methods=['POST'])
@system_container()
def create_club():
    """"""
    data = request.get_json() or {}
    kwargs = {'club_name': data.get('club_name'), 'category': data.get('category')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.create_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/approve_club', methods=['POST'])
@system_container()
def approve_club():
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.approve_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/update_club/<int:item_id>', methods=['PUT'])
@system_container()
def update_club(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.update_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/dissolve_club', methods=['POST'])
@system_container()
def dissolve_club():
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.dissolve_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/get_club', methods=['GET'])
@system_container()
def get_club():
    """"""
    kwargs = {'club_id': request.args.get('club_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.get_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/list_clubs', methods=['GET'])
@system_container()
def list_clubs():
    """"""
    kwargs = {'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.list_clubs(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/join_club', methods=['POST'])
@system_container()
def join_club():
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id'), 'student_id': data.get('student_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.join_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/leave_club', methods=['POST'])
@system_container()
def leave_club():
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id'), 'student_id': data.get('student_id'), 'reason': data.get('reason')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.leave_club(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/update_member_role/<int:item_id>', methods=['PUT'])
@system_container()
def update_member_role(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id'), 'student_id': data.get('student_id'), 'role': data.get('role')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.update_member_role(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/list_members', methods=['GET'])
@system_container()
def list_members():
    """"""
    kwargs = {'club_id': request.args.get('club_id'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.list_members(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/get_member_info', methods=['GET'])
@system_container()
def get_member_info():
    """"""
    kwargs = {'club_id': request.args.get('club_id'), 'student_id': request.args.get('student_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.get_member_info(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/create_recruitment', methods=['POST'])
@system_container()
def create_recruitment():
    """"""
    data = request.get_json() or {}
    kwargs = {'club_id': data.get('club_id'), 'recruitment_name': data.get('recruitment_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.create_recruitment(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/apply_recruitment', methods=['POST'])
@system_container()
def apply_recruitment():
    """"""
    data = request.get_json() or {}
    kwargs = {'recruitment_id': data.get('recruitment_id'), 'student_id': data.get('student_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.apply_recruitment(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/interview_applicant', methods=['POST'])
@system_container()
def interview_applicant():
    """"""
    data = request.get_json() or {}
    kwargs = {'application_id': data.get('application_id'), 'score': data.get('score')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.interview_applicant(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@student_club_service_bp.route('/accept_applicant', methods=['POST'])
@system_container()
def accept_applicant():
    """"""
    data = request.get_json() or {}
    kwargs = {'application_id': data.get('application_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = StudentClubService()
        result = service.accept_applicant(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
