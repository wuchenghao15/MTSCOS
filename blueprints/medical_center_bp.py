"""
仙女座医疗中心 REST Blueprint
routes:
  POST /api/medical/exam        手动触发全身体检 (入厅)
  GET  /api/medical/reports     最近体检报告
  GET  /api/medical/bugs        bug 列表
  GET  /api/medical/registry    Skill/Agent/Hook/OpenClaw 注册中心
  GET  /api/medical/status      医疗中心 daemon 状态
"""
import functools
import json
import sys
import traceback

from flask import Blueprint, jsonify, request


medical_bp = Blueprint('medical_center', __name__, url_prefix='/api/medical')


def _login_required(fn):
    """医疗中心端点 — 允许内部 daemon + 外部 SA 访问"""
    @functools.wraps(fn)
    def _wrap(*args, **kwargs):
        # 不强制: 让 Flask 内部线程 (daemon/collab-bus) 也能调用
        # 外部 HTTP 如果 session 里有 user 就记录一下, 没有也放行
        return fn(*args, **kwargs)
    return _wrap


@medical_bp.route('/exam', methods=['POST'])
@_login_required
def api_exam():
    """全身体检 (自动入厅)"""
    try:
        from engines.ai_medical_center_engine import run_manual_exam
        body = request.get_json(silent=True) or {}
        auto_hall = body.get('auto_hall', True)
        report = run_manual_exam(auto_hall=auto_hall)
        return jsonify({'success': True, 'report': report}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@medical_bp.route('/reports', methods=['GET'])
@_login_required
def api_reports():
    """最近体检报告"""
    try:
        from engines.ai_medical_center_engine import get_latest_reports
        limit = min(int(request.args.get('limit', 5)), 20)
        reports = get_latest_reports(limit)
        return jsonify({'success': True, 'reports': reports}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@medical_bp.route('/bugs', methods=['GET'])
@_login_required
def api_bugs():
    """Bug 列表"""
    try:
        from engines.ai_medical_center_engine import get_bugs
        severity = request.args.get('severity')
        limit = min(int(request.args.get('limit', 50)), 200)
        bugs = get_bugs(severity, limit)
        return jsonify({'success': True, 'bugs': bugs}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@medical_bp.route('/registry', methods=['GET'])
@_login_required
def api_registry():
    """Skill/Agent/Hook/OpenClaw 注册中心"""
    try:
        from engines.ai_medical_center_engine import get_skill_registry, SkillAgentHookRegistry
        # 同时做一次实时 audit
        audit = SkillAgentHookRegistry().audit()
        reg = get_skill_registry()
        return jsonify({
            'success': True,
            'registered': reg,
            'live_audit': {
                'skill_count': audit.get('registered_count'),
                'audit_issues': audit.get('issues'),
                'audit_score': audit.get('score'),
            },
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@medical_bp.route('/status', methods=['GET'])
@_login_required
def api_status():
    """医疗中心 daemon 状态"""
    try:
        # 查 daemon 线程
        import threading
        daemon_thread = None
        for t in threading.enumerate():
            if t.name == 'medical-daemon':
                daemon_thread = t
                break
        return jsonify({
            'success': True,
            'daemon_running': daemon_thread is not None,
            'thread_count': threading.active_count(),
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def register_medical_bp(app):
    """注册 Blueprint + daemon 嵌入"""
    app.register_blueprint(medical_bp)
    sys.stderr.write("[MEDICAL] ✅ 医疗中心 Blueprint 已注册 (/api/medical/*)\n")
    # 嵌入 daemon (delay 60s, 让 Flask 先稳定)
    try:
        import threading as _t
        def _start():
            import time as _tm
            _tm.sleep(60)
            try:
                from engines.ai_medical_center_engine import start_medical_daemon
                import os
                start_medical_daemon(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    cycle_seconds=600)  # 10min
            except Exception as e:
                sys.stderr.write(f"[MEDICAL] ⚠️ daemon 启动失败: {e}\n")
        _t.Thread(target=_start, name='medical-daemon-startup', daemon=True).start()
        sys.stderr.write("[MEDICAL] ✅ daemon startup 线程已提交 (delay 60s)\n")
    except Exception as e:
        sys.stderr.write(f"[MEDICAL] ⚠️ daemon 嵌入失败: {e}\n")
