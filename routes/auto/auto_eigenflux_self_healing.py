"""自动生成的路由蓝图 - eigenflux_self_healing"""
from flask import Blueprint, jsonify, request
from services.eigenflux_self_healing import RealScanner
from app.middlewares.system_container import system_container

eigenflux_self_healing_bp = Blueprint('eigenflux_self_healing_bp', __name__, url_prefix='/api/eigenflux/self/healing')

@eigenflux_self_healing_bp.route('/scan_syntax_errors', methods=['POST'])
@system_container()
def scan_syntax_errors():
    """使用 ast.parse 检查语法错误（仅扫描核心目录）"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_syntax_errors()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_pycache', methods=['POST'])
@system_container()
def scan_pycache():
    """检测 __pycache__ 目录"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_pycache()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_pyc_files', methods=['POST'])
@system_container()
def scan_pyc_files():
    """检测孤立的 .pyc 文件"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_pyc_files()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_large_logs', methods=['POST'])
@system_container()
def scan_large_logs():
    """检测大日志文件"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_large_logs()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_missing_init', methods=['POST'])
@system_container()
def scan_missing_init():
    """检测缺失 __init__.py 的Python包目录"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_missing_init()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_db_integrity', methods=['POST'])
@system_container()
def scan_db_integrity():
    """检测数据库完整性"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_db_integrity()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_disk_space', methods=['POST'])
@system_container()
def scan_disk_space():
    """检测磁盘空间"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_disk_space()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_temp_files', methods=['POST'])
@system_container()
def scan_temp_files():
    """检测临时文件"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_temp_files()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_missing_indexes', methods=['POST'])
@system_container()
def scan_missing_indexes():
    """检测数据库表中缺失的索引"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_missing_indexes()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_import_errors', methods=['POST'])
@system_container()
def scan_import_errors():
    """使用ast.parse检查Python文件导入的模块是否存在"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_import_errors()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_log_errors', methods=['POST'])
@system_container()
def scan_log_errors():
    """扫描日志文件中的ERROR/CRITICAL行"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_log_errors()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_empty_files', methods=['POST'])
@system_container()
def scan_empty_files():
    """检测空的Python文件（0字节）"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_empty_files()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_stale_sessions', methods=['POST'])
@system_container()
def scan_stale_sessions():
    """检测数据库中的过期会话记录"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_stale_sessions()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_broken_templates', methods=['POST'])
@system_container()
def scan_broken_templates():
    """检测路由引用的模板文件是否存在"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_broken_templates()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@eigenflux_self_healing_bp.route('/scan_all', methods=['POST'])
@system_container()
def scan_all():
    """执行全部扫描"""
    data = request.get_json() or {}
    try:
        service = RealScanner()
        result = service.scan_all()
        return jsonify(result) if isinstance(result, dict) else jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
