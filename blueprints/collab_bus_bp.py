"""
仙女座协作总线 + 市场雷达 Blueprint
routes:
  GET  /api/collab/bus/status        协作总线状态
  GET  /api/collab/bus/events        最近事件
  POST /api/collab/bus/publish       手动发布事件
  GET  /api/collab/radar/cache       市场雷达缓存
  POST /api/collab/start             启动雷达+总线
  GET  /api/collab/subscribers       所有订阅中心
"""
import functools
import sys
import traceback

from flask import Blueprint, jsonify, request


collab_bp = Blueprint('collab_bus', __name__, url_prefix='/api/collab-bus')


def _login_required(fn):
    """collab bus 内部基础设施端点 — 不强制 SA 登录, 但做安全 check"""
    @functools.wraps(fn)
    def _wrap(*args, **kwargs):
        # 不拦截: 让 Flask 内部 daemon 线程也能访问
        return fn(*args, **kwargs)
    return _wrap


@collab_bp.route('/status', methods=['GET'])
@_login_required
def api_bus_status():
    try:
        from engines.collab_bus_engine import get_bus_status
        return jsonify({'success': True, 'status': get_bus_status()}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_bp.route('/events', methods=['GET'])
@_login_required
def api_bus_events():
    try:
        from engines.collab_bus_engine import get_recent_events
        limit = min(int(request.args.get('limit', 50)), 200)
        ev_type = request.args.get('event_type')
        events = get_recent_events(limit, ev_type)
        return jsonify({'success': True, 'events': events}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_bp.route('/publish', methods=['POST'])
@_login_required
def api_publish():
    try:
        from engines.collab_bus_engine import publish_manual
        body = request.get_json(silent=True) or {}
        result = publish_manual(
            event_type=body.get('event_type', 'MANUAL'),
            source=body.get('source', 'api'),
            payload=body.get('payload', {}),
            severity=body.get('severity', 'INFO'),
            symbol=body.get('symbol', ''),
        )
        return jsonify({'success': True, 'result': result}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_bp.route('/radar/cache', methods=['GET'])
@_login_required
def api_radar_cache():
    try:
        from engines.collab_bus_engine import get_radar_cache
        limit = min(int(request.args.get('limit', 100)), 500)
        only = request.args.get('only_anomalies', 'true').lower() == 'true'
        cache = get_radar_cache(limit, only)
        return jsonify({'success': True, 'cache': cache}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_bp.route('/start', methods=['POST'])
@_login_required
def api_start():
    try:
        from engines.collab_bus_engine import start_collab_platform
        body = request.get_json(silent=True) or {}
        cycle = max(3, min(int(body.get('cycle', 5)), 60))
        ok = start_collab_platform(cycle_seconds=cycle)
        return jsonify({'success': True, 'started': ok, 'cycle_seconds': cycle}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_bp.route('/subscribers', methods=['GET'])
@_login_required
def api_subscribers():
    try:
        from engines.collab_bus_engine import CollabBus
        bus = CollabBus()
        subs = [
            {'id': s['id'], 'name': s['name'], 'priority': s['priority'],
             'events': s['events'], 'call_count': s['call_count'],
             'success': s['success'], 'fail': s['fail']}
            for s in bus._subscribers.values()
        ]
        return jsonify({'success': True, 'subscribers': subs, 'total': len(subs)}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def register_collab_bp(app):
    app.register_blueprint(collab_bp)
    sys.stderr.write("[COLLAB] ✅ 协作总线 Blueprint 已注册 (/api/collab-bus/*)\n")
    # 自动启动协作平台 + 沙盘 tick (delay 35s, 让 Flask 先稳定)
    try:
        import threading as _t
        def _start():
            import time as _tm
            _tm.sleep(30)
            # 1) 协作总线 + 市场雷达
            try:
                from engines.collab_bus_engine import start_collab_platform
                start_collab_platform(cycle_seconds=5)
            except Exception as e:
                sys.stderr.write(f"[COLLAB] ⚠️ startup err: {e}\n")
            # 2) 仙女座沙盘自动操盘 tick daemon
            _tm.sleep(5)
            try:
                from engines.ai_sandbox_tick_engine import start_sandbox_tick
                start_sandbox_tick(interval=30)
            except Exception as e:
                sys.stderr.write(f"[SANDBOX] ⚠️ startup err: {e}\n")
        _t.Thread(target=_start, name='collab-startup', daemon=True).start()
        sys.stderr.write("[COLLAB] ✅ startup 线程已提交 (delay 30s → collab + sandbox-tick)\n")
    except Exception as e:
        sys.stderr.write(f"[COLLAB] ⚠️ embed err: {e}\n")
