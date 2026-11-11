"""自动生成的路由蓝图 - education_edge_computing_service"""
from flask import Blueprint, jsonify, request
from services.education_edge_computing_service import EducationEdgeComputingService
from app.middlewares.system_container import system_container

education_edge_computing_service_bp = Blueprint('education_edge_computing_service_bp', __name__, url_prefix='/api/education/edge/computing/service')

@education_edge_computing_service_bp.route('/register_node', methods=['POST'])
@system_container()
def register_node():
    """"""
    data = request.get_json() or {}
    kwargs = {'node_name': data.get('node_name'), 'node_type': data.get('node_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.register_node(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/update_node_status/<int:item_id>', methods=['PUT'])
@system_container()
def update_node_status(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'node_id': data.get('node_id'), 'status': data.get('status')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.update_node_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/get_node_info', methods=['GET'])
@system_container()
def get_node_info():
    """"""
    kwargs = {'node_id': request.args.get('node_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.get_node_info(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/list_nodes', methods=['GET'])
@system_container()
def list_nodes():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'node_type': request.args.get('node_type'), 'status': request.args.get('status'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.list_nodes(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/create_computing_task', methods=['POST'])
@system_container()
def create_computing_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_name': data.get('task_name'), 'task_type': data.get('task_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.create_computing_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/assign_task', methods=['POST'])
@system_container()
def assign_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id'), 'node_id': data.get('node_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.assign_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/update_task_progress/<int:item_id>', methods=['PUT'])
@system_container()
def update_task_progress(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'task_id': data.get('task_id'), 'progress': data.get('progress')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.update_task_progress(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/list_tasks', methods=['GET'])
@system_container()
def list_tasks():
    """"""
    kwargs = {'education_type': request.args.get('education_type'), 'task_type': request.args.get('task_type'), 'status': request.args.get('status'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.list_tasks(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/collect_data', methods=['POST'])
@system_container()
def collect_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'data_name': data.get('data_name'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.collect_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/process_data', methods=['POST'])
@system_container()
def process_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'data_id': data.get('data_id'), 'processing_type': data.get('processing_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.process_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/store_data', methods=['POST'])
@system_container()
def store_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'data_id': data.get('data_id'), 'storage_id': data.get('storage_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.store_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/sync_data', methods=['POST'])
@system_container()
def sync_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'source_node_id': data.get('source_node_id'), 'target_node_id': data.get('target_node_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.sync_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/create_inference_task', methods=['POST'])
@system_container()
def create_inference_task():
    """"""
    data = request.get_json() or {}
    kwargs = {'inference_name': data.get('inference_name'), 'model_type': data.get('model_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.create_inference_task(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/execute_inference', methods=['POST'])
@system_container()
def execute_inference():
    """"""
    data = request.get_json() or {}
    kwargs = {'inference_id': data.get('inference_id'), 'node_id': data.get('node_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.execute_inference(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_edge_computing_service_bp.route('/get_inference_result', methods=['GET'])
@system_container()
def get_inference_result():
    """"""
    kwargs = {'inference_id': request.args.get('inference_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationEdgeComputingService()
        result = service.get_inference_result(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
