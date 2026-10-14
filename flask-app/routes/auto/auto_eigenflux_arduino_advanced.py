"""自动生成的路由蓝图 - eigenflux_arduino_advanced"""
from flask import Blueprint, jsonify, request
from services.eigenflux_arduino_advanced import SerialPortMonitor
from app.middlewares.system_container import system_container

eigenflux_arduino_advanced_bp = Blueprint('eigenflux_arduino_advanced_bp', __name__, url_prefix='/api/eigenflux/arduino/advanced')

@eigenflux_arduino_advanced_bp.route('/scan_ports', methods=['POST'])
@system_container(require_auth='super_admin')
def scan_ports():
    """扫描所有可用串口并识别Arduino硬件"""
    data = request.get_json() or {}
    try:
        service = SerialPortMonitor()
        result = service.scan_ports()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_arduino_advanced_bp.route('/start_monitoring', methods=['POST'])
@system_container(require_auth='super_admin')
def start_monitoring():
    """启动后台端口监听线程"""
    data = request.get_json() or {}
    kwargs = {'interval': data.get('interval')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = SerialPortMonitor()
        result = service.start_monitoring(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_arduino_advanced_bp.route('/stop_monitoring', methods=['POST'])
@system_container(require_auth='super_admin')
def stop_monitoring():
    """停止端口监听"""
    data = request.get_json() or {}
    try:
        service = SerialPortMonitor()
        result = service.stop_monitoring()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_arduino_advanced_bp.route('/read_serial', methods=['POST'])
@system_container(require_auth='super_admin')
def read_serial():
    """读取串口数据（真实pyserial读取）"""
    data = request.get_json() or {}
    kwargs = {'port_name': data.get('port_name'), 'baud_rate': data.get('baud_rate'), 'duration': data.get('duration')}
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        service = SerialPortMonitor()
        result = service.read_serial(**kwargs)
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
