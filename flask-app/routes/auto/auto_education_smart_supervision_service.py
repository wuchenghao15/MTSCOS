"""自动生成的路由蓝图 - education_smart_supervision_service"""
from flask import Blueprint, jsonify, request
from services.education_smart_supervision_service import EducationSmartSupervisionService
from app.middlewares.system_container import system_container

education_smart_supervision_service_bp = Blueprint('education_smart_supervision_service_bp', __name__, url_prefix='/api/education/smart/supervision/service')

@education_smart_supervision_service_bp.route('/create_supervision_plan', methods=['POST'])
@system_container()
def create_supervision_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_name': data.get('plan_name'), 'supervision_type': data.get('supervision_type'), 'plan_level': data.get('plan_level'), 'education_type': data.get('education_type')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.create_supervision_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/approve_plan', methods=['POST'])
@system_container()
def approve_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'approved': data.get('approved')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.approve_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/start_plan', methods=['POST'])
@system_container()
def start_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.start_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/archive_plan', methods=['POST'])
@system_container()
def archive_plan():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.archive_plan(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/create_monitoring_process', methods=['POST'])
@system_container()
def create_monitoring_process():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'process_name': data.get('process_name'), 'monitoring_method': data.get('monitoring_method')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.create_monitoring_process(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/start_process', methods=['POST'])
@system_container()
def start_process():
    """"""
    data = request.get_json() or {}
    kwargs = {'process_id': data.get('process_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.start_process(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/record_process_data', methods=['POST'])
@system_container()
def record_process_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'process_id': data.get('process_id'), 'record_type': data.get('record_type'), 'content': data.get('content')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.record_process_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/complete_process', methods=['POST'])
@system_container()
def complete_process():
    """"""
    data = request.get_json() or {}
    kwargs = {'process_id': data.get('process_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.complete_process(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/collect_supervision_data', methods=['POST'])
@system_container()
def collect_supervision_data():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'data_type': data.get('data_type'), 'data_category': data.get('data_category'), 'data_value': data.get('data_value')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.collect_supervision_data(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/perform_analysis', methods=['POST'])
@system_container()
def perform_analysis():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'analysis_method': data.get('analysis_method')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.perform_analysis(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/get_analysis_results', methods=['GET'])
@system_container()
def get_analysis_results():
    """"""
    kwargs = {'plan_id': request.args.get('plan_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.get_analysis_results(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/create_report', methods=['POST'])
@system_container()
def create_report():
    """"""
    data = request.get_json() or {}
    kwargs = {'plan_id': data.get('plan_id'), 'report_type': data.get('report_type'), 'report_title': data.get('report_title')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.create_report(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/update_report/<int:item_id>', methods=['PUT'])
@system_container()
def update_report(item_id):
    """"""
    data = request.get_json() or {}
    kwargs = {'report_id': data.get('report_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.update_report(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/publish_report', methods=['POST'])
@system_container()
def publish_report():
    """"""
    data = request.get_json() or {}
    kwargs = {'report_id': data.get('report_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.publish_report(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@education_smart_supervision_service_bp.route('/get_report_versions', methods=['GET'])
@system_container()
def get_report_versions():
    """"""
    kwargs = {'report_id': request.args.get('report_id')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = EducationSmartSupervisionService()
        result = service.get_report_versions(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
