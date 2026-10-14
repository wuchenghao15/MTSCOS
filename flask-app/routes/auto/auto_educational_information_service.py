"""自动生成的路由蓝图 - educational_information_service"""
from flask import Blueprint, jsonify, request
from services.educational_information_service import EducationalInformationService
from app.middlewares.system_container import system_container

educational_information_service_bp = Blueprint('educational_information_service_bp', __name__, url_prefix='/api/educational/information/service')

@educational_information_service_bp.route('/add_campus_system', methods=['POST'])
@system_container()
def add_campus_system():
    """"""
    data = request.get_json() or {}
    kwargs = {'system_name': data.get('system_name'), 'system_type': data.get('system_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.add_campus_system(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/enable_system_module', methods=['POST'])
@system_container()
def enable_system_module():
    """"""
    data = request.get_json() or {}
    kwargs = {'system_id': data.get('system_id'), 'module_name': data.get('module_name')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.enable_system_module(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/get_system_status', methods=['GET'])
@system_container()
def get_system_status():
    """"""
    kwargs = {'system_id': request.args.get('system_id'), 'education_type': request.args.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.get_system_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/update_system_config/<int:item_id>', methods=['PUT'])
@system_container()
def update_system_config(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'system_id': data.get('system_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.update_system_config(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/add_infrastructure', methods=['POST'])
@system_container()
def add_infrastructure():
    """"""
    data = request.get_json() or {}
    kwargs = {'infra_type': data.get('infra_type'), 'infra_name': data.get('infra_name'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.add_infrastructure(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/add_network_device', methods=['POST'])
@system_container()
def add_network_device():
    """"""
    data = request.get_json() or {}
    kwargs = {'device_name': data.get('device_name'), 'device_type': data.get('device_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.add_network_device(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/get_infrastructure_status', methods=['GET'])
@system_container()
def get_infrastructure_status():
    """"""
    kwargs = {'infra_type': request.args.get('infra_type'), 'education_type': request.args.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.get_infrastructure_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/update_infrastructure/<int:item_id>', methods=['PUT'])
@system_container()
def update_infrastructure(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'infra_id': data.get('infra_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.update_infrastructure(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/add_data_center', methods=['POST'])
@system_container()
def add_data_center():
    """"""
    data = request.get_json() or {}
    kwargs = {'dc_name': data.get('dc_name'), 'dc_type': data.get('dc_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.add_data_center(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/update_data_center_status/<int:item_id>', methods=['PUT'])
@system_container()
def update_data_center_status(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'dc_id': data.get('dc_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.update_data_center_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/get_data_center_status', methods=['GET'])
@system_container()
def get_data_center_status():
    """"""
    try:
        service = EducationalInformationService()
        result = service.get_data_center_status()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/add_iot_device', methods=['POST'])
@system_container()
def add_iot_device():
    """"""
    data = request.get_json() or {}
    kwargs = {'device_name': data.get('device_name'), 'device_type': data.get('device_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.add_iot_device(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/update_iot_device_data/<int:item_id>', methods=['PUT'])
@system_container()
def update_iot_device_data(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'device_id': data.get('device_id'), 'data_value': data.get('data_value')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.update_iot_device_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/get_iot_device_status', methods=['GET'])
@system_container()
def get_iot_device_status():
    """"""
    kwargs = {'device_type': request.args.get('device_type'), 'education_type': request.args.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.get_iot_device_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@educational_information_service_bp.route('/add_smart_classroom', methods=['POST'])
@system_container()
def add_smart_classroom():
    """"""
    data = request.get_json() or {}
    kwargs = {'classroom_name': data.get('classroom_name'), 'location': data.get('location'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationalInformationService()
        result = service.add_smart_classroom(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
