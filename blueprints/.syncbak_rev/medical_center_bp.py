#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
医疗中心 REST API Blueprint
flow: flow_medical_center_20261102_bp

所有端点 pass-through 登录检查 (内部基础设施)
"""

from __future__ import annotations

import json
import sys
from functools import wraps
from flask import Blueprint, jsonify, request

medical_center_bp = Blueprint(
    'medical_center',
    __name__,
    url_prefix='/api/medical'
)

# 确保引擎表已初始化
try:
    from engines.ai_medical_center_engine import ensure_medical_tables
    ensure_medical_tables()
except Exception as e:
    sys.stderr.write(f"[MEDICAL-BP] 初始化表失败: {e}\n")


# ═══════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════

@medical_center_bp.route('/status', methods=['GET'])
def api_status():
    """健康概览"""
    try:
        from engines.ai_medical_center_engine import get_health_summary
        summary = get_health_summary()
        return jsonify({
            "ok": True,
            "status": summary,
            "timestamp": __import__('datetime').datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@medical_center_bp.route('/exam', methods=['GET'])
def api_exam():
    """
    执行体检
    query params:
    - target: andromeda | iceberg | both (默认 both)
    - level: quick | full | deep (默认 full)
    - auto_submit: 1 | 0 (默认 0, 不自动入厅)
    """
    try:
        from engines.ai_medical_center_engine import run_exam, submit_to_hall
        
        target = request.args.get('target', 'both')
        level = request.args.get('level', 'full')
        auto_submit = request.args.get('auto_submit', '0') == '1'
        
        if target not in ('andromeda', 'iceberg', 'both'):
            return jsonify({"ok": False, "error": f"无效 target: {target}"}), 400
        if level not in ('quick', 'full', 'deep'):
            return jsonify({"ok": False, "error": f"无效 level: {level}"}), 400
        
        report = run_exam(target=target, level=level, trigger_type='manual')
        
        hall_code = None
        if auto_submit and report['overall_status'] != 'healthy':
            hall_code = submit_to_hall(report)
        
        # 简化返回 (去掉长 JSON)
        response = {
            "ok": True,
            "report_id": report['report_id'],
            "target": report['target'],
            "exam_level": report['exam_level'],
            "health_score": report['health_score'],
            "overall_status": report['overall_status'],
            "bugs_found": report['bugs_found'],
            "elapsed_s": report['elapsed_s'],
            "hall_code": hall_code,
            "dimensions": report['dimensions'],
            "created_at": report['created_at'],
        }
        return jsonify(response)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@medical_center_bp.route('/reports', methods=['GET'])
def api_reports():
    """
    获取体检报告列表
    query params:
    - limit: 默认 50, 最大 200
    """
    try:
        from engines.ai_medical_center_engine import get_recent_reports
        
        limit = min(int(request.args.get('limit', 50)), 200)
        reports = get_recent_reports(limit=limit)
        
        return jsonify({
            "ok": True,
            "count": len(reports),
            "reports": reports,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@medical_center_bp.route('/bugs', methods=['GET'])
def api_bugs():
    """
    获取 bug 列表
    query params:
    - status: open | fixed | all (默认 open)
    """
    try:
        from engines.ai_medical_center_engine import get_bugs
        
        status = request.args.get('status', 'open')
        bugs = get_bugs(status=status)
        
        return jsonify({
            "ok": True,
            "count": len(bugs),
            "bugs": bugs,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@medical_center_bp.route('/trigger', methods=['POST'])
def api_trigger():
    """
    手动触发体检 + 入厅 (用于定时/事件驱动之外的场景)
    body JSON:
    {
        "target": "andromeda|iceberg|both",
        "level": "quick|full|deep",
        "event_type": "MANUAL_TRIGGER",
        "auto_submit": true
    }
    """
    try:
        from engines.ai_medical_center_engine import run_exam, submit_to_hall
        
        data = request.get_json() or {}
        target = data.get('target', 'both')
        level = data.get('level', 'full')
        trigger_type = data.get('event_type', 'manual')
        auto_submit = data.get('auto_submit', True)
        
        report = run_exam(target=target, level=level, trigger_type=trigger_type)
        
        hall_code = None
        if auto_submit and report['overall_status'] != 'healthy':
            hall_code = submit_to_hall(report)
        
        # 如果健康, 也入厅归档
        if auto_submit and report['overall_status'] == 'healthy':
            hall_code = submit_to_hall(report)
        
        return jsonify({
            "ok": True,
            "report_id": report['report_id'],
            "health_score": report['health_score'],
            "overall_status": report['overall_status'],
            "bugs_found": report['bugs_found'],
            "hall_code": hall_code,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@medical_center_bp.route('/daemon/start', methods=['POST'])
def api_daemon_start():
    """启动医疗中心 daemon (如果未运行)"""
    try:
        from engines.ai_medical_center_engine import get_medical_center
        
        daemon = get_medical_center()
        daemon.start()
        
        return jsonify({
            "ok": True,
            "message": "医疗中心 daemon 启动指令已发送",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@medical_center_bp.route('/daemon/status', methods=['GET'])
def api_daemon_status():
    """daemon 运行状态"""
    try:
        from engines.ai_medical_center_engine import MedicalCenterDaemon
        
        d = MedicalCenterDaemon()
        thread = getattr(d, '_thread', None)
        
        return jsonify({
            "ok": True,
            "daemon_alive": thread.is_alive() if thread else False,
            "subscribed_to_collab": d._subscribed,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# 导出蓝图 (供 server_real_db.py 注册)
__all__ = ['medical_center_bp']
