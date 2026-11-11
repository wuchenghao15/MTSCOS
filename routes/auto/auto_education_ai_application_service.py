"""自动生成的路由蓝图 - education_ai_application_service"""
from flask import Blueprint, jsonify, request
from services.education_ai_application_service import EducationAIApplicationService
from app.middlewares.system_container import system_container

education_ai_application_service_bp = Blueprint('education_ai_application_service_bp', __name__, url_prefix='/api/education/ai/application/service')

@education_ai_application_service_bp.route('/create_assistant', methods=['POST'])
@system_container()
def create_assistant():
    """"""
    data = request.get_json() or {}
    kwargs = {'assistant_name': data.get('assistant_name'), 'assistant_type': data.get('assistant_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.create_assistant(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/configure_assistant', methods=['POST'])
@system_container()
def configure_assistant():
    """"""
    data = request.get_json() or {}
    kwargs = {'assistant_id': data.get('assistant_id'), 'config_key': data.get('config_key'), 'config_value': data.get('config_value')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.configure_assistant(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/get_assistant', methods=['GET'])
@system_container()
def get_assistant():
    """"""
    kwargs = {'assistant_id': request.args.get('assistant_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.get_assistant(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/list_assistants', methods=['GET'])
@system_container()
def list_assistants():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'assistant_type': request.args.get('assistant_type'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.list_assistants(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/create_correction', methods=['POST'])
@system_container()
def create_correction():
    """"""
    data = request.get_json() or {}
    kwargs = {'correction_type': data.get('correction_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.create_correction(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/submit_answer', methods=['POST'])
@system_container()
def submit_answer():
    """"""
    data = request.get_json() or {}
    kwargs = {'correction_id': data.get('correction_id'), 'student_id': data.get('student_id'), 'answer_content': data.get('answer_content')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.submit_answer(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/execute_correction', methods=['POST'])
@system_container()
def execute_correction():
    """"""
    data = request.get_json() or {}
    kwargs = {'correction_id': data.get('correction_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.execute_correction(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/get_correction_result', methods=['GET'])
@system_container()
def get_correction_result():
    """"""
    kwargs = {'result_id': request.args.get('result_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.get_correction_result(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/create_exam_paper', methods=['POST'])
@system_container()
def create_exam_paper():
    """"""
    data = request.get_json() or {}
    kwargs = {'paper_name': data.get('paper_name'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.create_exam_paper(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/add_question_to_paper', methods=['POST'])
@system_container()
def add_question_to_paper():
    """"""
    data = request.get_json() or {}
    kwargs = {'paper_id': data.get('paper_id'), 'question_type': data.get('question_type'), 'content': data.get('content')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.add_question_to_paper(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/generate_paper_from_template', methods=['POST'])
@system_container()
def generate_paper_from_template():
    """"""
    data = request.get_json() or {}
    kwargs = {'template_id': data.get('template_id'), 'paper_name': data.get('paper_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.generate_paper_from_template(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/publish_paper', methods=['POST'])
@system_container()
def publish_paper():
    """"""
    data = request.get_json() or {}
    kwargs = {'paper_id': data.get('paper_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.publish_paper(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/add_qna', methods=['POST'])
@system_container()
def add_qna():
    """"""
    data = request.get_json() or {}
    kwargs = {'question': data.get('question'), 'answer': data.get('answer')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.add_qna(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/query_qna', methods=['GET'])
@system_container()
def query_qna():
    """"""
    kwargs = {'user_id': request.args.get('user_id'), 'user_question': request.args.get('user_question')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.query_qna(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_ai_application_service_bp.route('/update_qna/<int:item_id>', methods=['PUT'])
@system_container()
def update_qna(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'qna_id': data.get('qna_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationAIApplicationService()
        result = service.update_qna(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
