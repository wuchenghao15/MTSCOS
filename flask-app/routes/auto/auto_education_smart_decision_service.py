"""自动生成的路由蓝图 - education_smart_decision_service"""
from flask import Blueprint, jsonify, request
from services.education_smart_decision_service import EducationSmartDecisionService
from app.middlewares.system_container import system_container

education_smart_decision_service_bp = Blueprint('education_smart_decision_service_bp', __name__, url_prefix='/api/education/smart/decision/service')

@education_smart_decision_service_bp.route('/create_decision_model', methods=['POST'])
@system_container()
def create_decision_model():
    """"""
    data = request.get_json() or {}
    kwargs = {'model_name': data.get('model_name'), 'model_type': data.get('model_type'), 'decision_type': data.get('decision_type'), 'analysis_model': data.get('analysis_model')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.create_decision_model(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/add_decision_rule', methods=['POST'])
@system_container()
def add_decision_rule():
    """"""
    data = request.get_json() or {}
    kwargs = {'model_id': data.get('model_id'), 'rule_name': data.get('rule_name'), 'rule_expression': data.get('rule_expression')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.add_decision_rule(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/optimize_decision_strategy', methods=['POST'])
@system_container()
def optimize_decision_strategy():
    """"""
    data = request.get_json() or {}
    kwargs = {'model_id': data.get('model_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.optimize_decision_strategy(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/generate_decision_scheme', methods=['POST'])
@system_container()
def generate_decision_scheme():
    """"""
    data = request.get_json() or {}
    kwargs = {'model_id': data.get('model_id'), 'input_data': data.get('input_data')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.generate_decision_scheme(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/create_analysis_task', methods=['POST'])
@system_container()
def create_analysis_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_name': data.get('task_name'), 'data_domain': data.get('data_domain'), 'analysis_model': data.get('analysis_model')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.create_analysis_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/execute_analysis', methods=['POST'])
@system_container()
def execute_analysis():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.execute_analysis(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/query_analysis_results', methods=['GET'])
@system_container()
def query_analysis_results():
    """"""
    kwargs = {'task_id': request.args.get('task_id'), 'data_domain': request.args.get('data_domain'), 'education_type': request.args.get('education_type'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.query_analysis_results(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/compare_analysis_results', methods=['POST'])
@system_container()
def compare_analysis_results():
    """"""
    data = request.get_json() or {}
    kwargs = {'result_ids': data.get('result_ids')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.compare_analysis_results(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/create_knowledge_graph', methods=['POST'])
@system_container()
def create_knowledge_graph():
    """"""
    data = request.get_json() or {}
    kwargs = {'graph_name': data.get('graph_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.create_knowledge_graph(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/add_graph_node', methods=['POST'])
@system_container()
def add_graph_node():
    """"""
    data = request.get_json() or {}
    kwargs = {'graph_id': data.get('graph_id'), 'node_name': data.get('node_name'), 'node_type': data.get('node_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.add_graph_node(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/add_graph_edge', methods=['POST'])
@system_container()
def add_graph_edge():
    """"""
    data = request.get_json() or {}
    kwargs = {'graph_id': data.get('graph_id'), 'source_node_id': data.get('source_node_id'), 'target_node_id': data.get('target_node_id'), 'edge_type': data.get('edge_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.add_graph_edge(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/analyze_graph_path', methods=['POST'])
@system_container()
def analyze_graph_path():
    """"""
    data = request.get_json() or {}
    kwargs = {'graph_id': data.get('graph_id'), 'start_node_id': data.get('start_node_id'), 'end_node_id': data.get('end_node_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.analyze_graph_path(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/create_dashboard', methods=['POST'])
@system_container()
def create_dashboard():
    """"""
    data = request.get_json() or {}
    kwargs = {'dashboard_name': data.get('dashboard_name'), 'decision_level': data.get('decision_level')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.create_dashboard(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/add_dashboard_widget', methods=['POST'])
@system_container()
def add_dashboard_widget():
    """"""
    data = request.get_json() or {}
    kwargs = {'dashboard_id': data.get('dashboard_id'), 'widget_name': data.get('widget_name'), 'visualization_type': data.get('visualization_type'), 'data_domain': data.get('data_domain')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.add_dashboard_widget(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_decision_service_bp.route('/generate_report', methods=['POST'])
@system_container()
def generate_report():
    """"""
    data = request.get_json() or {}
    kwargs = {'dashboard_id': data.get('dashboard_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartDecisionService()
        result = service.generate_report(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
