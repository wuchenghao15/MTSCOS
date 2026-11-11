"""自动生成的路由蓝图 - education_intelligent_tutoring_service"""
from flask import Blueprint, jsonify, request
from services.education_intelligent_tutoring_service import EducationIntelligentTutoringService
from app.middlewares.system_container import system_container

education_intelligent_tutoring_service_bp = Blueprint('education_intelligent_tutoring_service_bp', __name__, url_prefix='/api/education/intelligent/tutoring/service')

@education_intelligent_tutoring_service_bp.route('/create_tutoring_plan', methods=['POST'])
@system_container()
def create_tutoring_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_name': data.get('plan_name'), 'tutoring_type': data.get('tutoring_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.create_tutoring_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/add_plan_detail', methods=['POST'])
@system_container()
def add_plan_detail():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'week_number': data.get('week_number'), 'topic': data.get('topic')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.add_plan_detail(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/activate_plan', methods=['POST'])
@system_container()
def activate_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.activate_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/get_plan_details', methods=['GET'])
@system_container()
def get_plan_details():
    """"""
    kwargs = {'plan_id': request.args.get('plan_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.get_plan_details(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/create_learning_path', methods=['POST'])
@system_container()
def create_learning_path():
    """"""
    data = request.get_json() or {}
    kwargs = {'student_id': data.get('student_id'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.create_learning_path(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/add_path_node', methods=['POST'])
@system_container()
def add_path_node():
    """"""
    data = request.get_json() or {}
    kwargs = {'path_id': data.get('path_id'), 'node_order': data.get('node_order'), 'node_type': data.get('node_type'), 'content': data.get('content')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.add_path_node(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/mark_node_completed', methods=['POST'])
@system_container()
def mark_node_completed():
    """"""
    data = request.get_json() or {}
    kwargs = {'path_id': data.get('path_id'), 'node_order': data.get('node_order')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.mark_node_completed(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/get_learning_progress', methods=['GET'])
@system_container()
def get_learning_progress():
    """"""
    kwargs = {'student_id': request.args.get('student_id'), 'education_type': request.args.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.get_learning_progress(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/add_qna', methods=['POST'])
@system_container()
def add_qna():
    """"""
    data = request.get_json() or {}
    kwargs = {'question': data.get('question'), 'question_type': data.get('question_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.add_qna(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/query_qna', methods=['GET'])
@system_container()
def query_qna():
    """"""
    kwargs = {'question': request.args.get('question')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.query_qna(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/record_qna_interaction', methods=['POST'])
@system_container()
def record_qna_interaction():
    """"""
    data = request.get_json() or {}
    kwargs = {'student_id': data.get('student_id'), 'qna_id': data.get('qna_id'), 'question_text': data.get('question_text'), 'answer_text': data.get('answer_text')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.record_qna_interaction(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/get_qna_history', methods=['GET'])
@system_container()
def get_qna_history():
    """"""
    kwargs = {'student_id': request.args.get('student_id'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.get_qna_history(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/create_analysis', methods=['POST'])
@system_container()
def create_analysis():
    """"""
    data = request.get_json() or {}
    kwargs = {'student_id': data.get('student_id'), 'analysis_method': data.get('analysis_method'), 'period_start': data.get('period_start'), 'period_end': data.get('period_end')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.create_analysis(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/add_analysis_result', methods=['POST'])
@system_container()
def add_analysis_result():
    """"""
    data = request.get_json() or {}
    kwargs = {'analysis_id': data.get('analysis_id'), 'metric_name': data.get('metric_name'), 'metric_value': data.get('metric_value')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.add_analysis_result(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_intelligent_tutoring_service_bp.route('/complete_analysis', methods=['POST'])
@system_container()
def complete_analysis():
    """"""
    data = request.get_json() or {}
    kwargs = {'analysis_id': data.get('analysis_id'), 'report_url': data.get('report_url')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationIntelligentTutoringService()
        result = service.complete_analysis(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
