"""自动生成的路由蓝图 - education_bci_service"""
from flask import Blueprint, jsonify, request
from services.education_bci_service import EducationBCIService
from app.middlewares.system_container import system_container

education_bci_service_bp = Blueprint('education_bci_service_bp', __name__, url_prefix='/api/education/bci/service')

@education_bci_service_bp.route('/create_interface', methods=['POST'])
@system_container()
def create_interface():
    """"""
    data = request.get_json() or {}
    kwargs = {'interface_name': data.get('interface_name'), 'bci_type': data.get('bci_type'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.create_interface(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/connect_interface', methods=['POST'])
@system_container()
def connect_interface():
    """"""
    data = request.get_json() or {}
    kwargs = {'interface_id': data.get('interface_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.connect_interface(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/disconnect_interface', methods=['POST'])
@system_container()
def disconnect_interface():
    """"""
    data = request.get_json() or {}
    kwargs = {'interface_id': data.get('interface_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.disconnect_interface(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/configure_interface', methods=['POST'])
@system_container()
def configure_interface():
    """"""
    data = request.get_json() or {}
    kwargs = {'interface_id': data.get('interface_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.configure_interface(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/start_recording', methods=['POST'])
@system_container()
def start_recording():
    """"""
    data = request.get_json() or {}
    kwargs = {'device_id': data.get('device_id'), 'user_id': data.get('user_id'), 'user_name': data.get('user_name'), 'education_type': data.get('education_type'), 'signal_type': data.get('signal_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.start_recording(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/stop_recording', methods=['POST'])
@system_container()
def stop_recording():
    """"""
    data = request.get_json() or {}
    kwargs = {'recording_id': data.get('recording_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.stop_recording(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/save_recording_data', methods=['POST'])
@system_container()
def save_recording_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'recording_id': data.get('recording_id'), 'channel_data': data.get('channel_data')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.save_recording_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/get_recording_status', methods=['GET'])
@system_container()
def get_recording_status():
    """"""
    kwargs = {'recording_id': request.args.get('recording_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.get_recording_status(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/create_analysis', methods=['POST'])
@system_container()
def create_analysis():
    """"""
    data = request.get_json() or {}
    kwargs = {'recording_id': data.get('recording_id'), 'analysis_method': data.get('analysis_method'), 'user_id': data.get('user_id'), 'user_name': data.get('user_name'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.create_analysis(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/complete_analysis', methods=['POST'])
@system_container()
def complete_analysis():
    """"""
    data = request.get_json() or {}
    kwargs = {'analysis_id': data.get('analysis_id'), 'result_type': data.get('result_type'), 'result_data': data.get('result_data')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.complete_analysis(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/get_analysis_result', methods=['GET'])
@system_container()
def get_analysis_result():
    """"""
    kwargs = {'result_id': request.args.get('result_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.get_analysis_result(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/list_analysis_results', methods=['GET'])
@system_container()
def list_analysis_results():
    """"""
    kwargs = {'user_id': request.args.get('user_id'), 'education_type': request.args.get('education_type'), 'page': request.args.get('page'), 'page_size': request.args.get('page_size')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.list_analysis_results(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/create_control', methods=['POST'])
@system_container()
def create_control():
    """"""
    data = request.get_json() or {}
    kwargs = {'user_id': data.get('user_id'), 'control_mode': data.get('control_mode'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.create_control(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/calibrate_control', methods=['POST'])
@system_container()
def calibrate_control():
    """"""
    data = request.get_json() or {}
    kwargs = {'control_id': data.get('control_id'), 'accuracy': data.get('accuracy')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.calibrate_control(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_bci_service_bp.route('/start_control_session', methods=['POST'])
@system_container()
def start_control_session():
    """"""
    data = request.get_json() or {}
    kwargs = {'control_id': data.get('control_id'), 'user_id': data.get('user_id'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationBCIService()
        result = service.start_control_session(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
