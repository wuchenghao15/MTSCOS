"""自动生成的路由蓝图 - education_smart_customer_service"""
from flask import Blueprint, jsonify, request
from services.education_smart_customer_service import EducationSmartCustomerService
from app.middlewares.system_container import system_container

education_smart_customer_service_bp = Blueprint('education_smart_customer_service_bp', __name__, url_prefix='/api/education/smart/customer/service')

@education_smart_customer_service_bp.route('/ask_question', methods=['POST'])
@system_container()
def ask_question():
    """"""
    data = request.get_json() or {}
    kwargs = {'customer_id': data.get('customer_id'), 'question': data.get('question'), 'channel_id': data.get('channel_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.ask_question(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/get_qa_history', methods=['GET'])
@system_container()
def get_qa_history():
    """"""
    kwargs = {'customer_id': request.args.get('customer_id'), 'education_type': request.args.get('education_type'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.get_qa_history(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/add_knowledge', methods=['POST'])
@system_container()
def add_knowledge():
    """"""
    data = request.get_json() or {}
    kwargs = {'title': data.get('title'), 'content': data.get('content'), 'knowledge_type': data.get('knowledge_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.add_knowledge(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/update_knowledge/<int:item_id>', methods=['PUT'])
@system_container()
def update_knowledge(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'knowledge_id': data.get('knowledge_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.update_knowledge(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/delete_knowledge/<int:item_id>', methods=['DELETE'])
@system_container()
def delete_knowledge(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'knowledge_id': data.get('knowledge_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.delete_knowledge(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/list_knowledge', methods=['GET'])
@system_container()
def list_knowledge():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'knowledge_type': request.args.get('knowledge_type'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.list_knowledge(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/send_message', methods=['POST'])
@system_container()
def send_message():
    """"""
    data = request.get_json() or {}
    kwargs = {'session_id': data.get('session_id'), 'content': data.get('content'), 'sender_type': data.get('sender_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.send_message(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/get_session_messages', methods=['GET'])
@system_container()
def get_session_messages():
    """"""
    kwargs = {'session_id': request.args.get('session_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.get_session_messages(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/close_session', methods=['POST'])
@system_container()
def close_session():
    """"""
    data = request.get_json() or {}
    kwargs = {'session_id': data.get('session_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.close_session(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/transfer_session', methods=['POST'])
@system_container()
def transfer_session():
    """"""
    data = request.get_json() or {}
    kwargs = {'session_id': data.get('session_id'), 'target_agent_id': data.get('target_agent_id'), 'target_agent_name': data.get('target_agent_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.transfer_session(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/analyze_sentiment', methods=['POST'])
@system_container()
def analyze_sentiment():
    """"""
    data = request.get_json() or {}
    kwargs = {'content': data.get('content')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.analyze_sentiment(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/get_session_sentiment', methods=['GET'])
@system_container()
def get_session_sentiment():
    """"""
    kwargs = {'session_id': request.args.get('session_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.get_session_sentiment(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/get_sentiment_trend', methods=['GET'])
@system_container()
def get_sentiment_trend():
    """"""
    kwargs = {'customer_id': request.args.get('customer_id'), 'days': request.args.get('days')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.get_sentiment_trend(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/create_ticket', methods=['POST'])
@system_container()
def create_ticket():
    """"""
    data = request.get_json() or {}
    kwargs = {'ticket_type': data.get('ticket_type'), 'title': data.get('title'), 'customer_id': data.get('customer_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.create_ticket(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_customer_service_bp.route('/assign_ticket', methods=['POST'])
@system_container()
def assign_ticket():
    """"""
    data = request.get_json() or {}
    kwargs = {'ticket_id': data.get('ticket_id'), 'agent_id': data.get('agent_id'), 'agent_name': data.get('agent_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartCustomerService()
        result = service.assign_ticket(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
