#!/usr/bin/env python3
import os
import psutil
import sqlite3
import time
import redis
import requests
from datetime import datetime
from flask import Blueprint, jsonify
from app.middlewares.system_container import system_container

health_api = Blueprint('health_api', __name__)

# 三节点拓扑 (dev 是本机, hulk-server HP DL360 物理机 Tailscale, mini hulk-macmini)
NODE_TOPOLOGY = [
    ('dev',       'localhost',         5001),
    ('mini',      '100.106.220.96',    5001),   # hulk-macmini Tailscale IP
    ('hulk',      '100.100.244.47',    5001),   # hulk-server Linux HP DL360
]


def get_system_metrics():
    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        'cpu': {
            'percent': cpu_percent,
            'count': psutil.cpu_count()
        },
        'memory': {
            'total': round(memory.total / 1024 / 1024 / 1024, 2),
            'used': round(memory.used / 1024 / 1024 / 1024, 2),
            'available': round(memory.available / 1024 / 1024 / 1024, 2),
            'percent': memory.percent
        },
        'disk': {
            'total': round(disk.total / 1024 / 1024 / 1024, 2),
            'used': round(disk.used / 1024 / 1024 / 1024, 2),
            'free': round(disk.free / 1024 / 1024 / 1024, 2),
            'percent': disk.percent
        },
        'uptime': time.time() - psutil.boot_time(),
        'process_count': len(psutil.pids())
    }


def check_database_connection(db_path):
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        conn.close()
        return {'status': 'healthy', 'latency_ms': 0}
    except Exception as e:
        return {'status': 'unhealthy', 'error': str(e)}


def check_redis_connection():
    # 多端点优先: localhost → hulk-server Tailscale → 跳过 (graceful degrade)
    REDIS_ENDPOINTS = [
        ('localhost', 6379),                    # 本地 brew (优先, 零 RTT)
        ('100.100.244.47', 6379),              # hulk-server HP DL360 物理机
        ('100.106.220.96', 6379),              # mini 跳板 (如 mini 有 redis)
    ]
    for host, port in REDIS_ENDPOINTS:
        try:
            r = redis.Redis(host=host, port=port, db=0, socket_connect_timeout=2, socket_timeout=2)
            start = time.time()
            r.ping()
            latency = (time.time() - start) * 1000
            return {'status': 'healthy', 'endpoint': f'{host}:{port}', 'latency_ms': round(latency, 2)}
        except Exception:
            continue
    return {'status': 'unhealthy', 'error': '所有端点均不可达, 已降级内存缓存', 'fallback': 'local'}


def check_scheduler_status():
    # 多路径查找 (scheduler_control 在 core/ 里写, 健康中心兼容老位置)
    BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CANDIDATES = [
        os.path.join(BASE, 'core', '.scheduler_pid'),
        os.path.join(BASE, 'core', 'services', '.scheduler_pid'),
        os.path.join(BASE, '.scheduler_pid'),
    ]
    HB_CANDIDATES = [
        os.path.join(BASE, 'core', '.scheduler_heartbeat'),
        os.path.join(BASE, 'core', 'services', '.scheduler_heartbeat'),
        os.path.join(BASE, '.scheduler_heartbeat'),
    ]
    # 选最新 mtime 的那一对
    pid_file, heartbeat_file = None, None
    best_mtime = 0
    for p, h in zip(CANDIDATES, HB_CANDIDATES):
        m = 0
        if os.path.exists(p): m = max(m, os.path.getmtime(p))
        if os.path.exists(h): m = max(m, os.path.getmtime(h))
        if m > best_mtime: best_mtime, pid_file, heartbeat_file = m, p, h

    status = 'stopped'
    if pid_file and os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            pid_raw = f.read().strip()
        if pid_raw:
            try:
                process = psutil.Process(int(pid_raw))
                status = 'healthy' if process.is_running() else 'unhealthy'
            except Exception:
                status = 'unhealthy'
    last_heartbeat = None
    if heartbeat_file and os.path.exists(heartbeat_file):
        try:
            with open(heartbeat_file, 'r') as f:
                last_heartbeat = f.read().strip()
        except Exception:
            pass
    return {'status': status, 'last_heartbeat': last_heartbeat, 'pid_file': pid_file, 'heartbeat_file': heartbeat_file}


def get_service_status():
    services = {}
    
    services['database'] = check_database_connection(
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app.db')
    )
    
    services['redis'] = check_redis_connection()
    
    services['scheduler'] = check_scheduler_status()
    
    services['daemon_registry'] = check_daemon_registry()

    services['remote_nodes'] = check_remote_nodes()

    services['auto_repair'] = {
        'status': 'healthy' if os.path.exists(
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'auto_scheduler.log')
        ) else 'unknown'
    }
    
    return services


def check_daemon_registry():
    """聚合 mt_daemon_registry 25 个 daemon 心跳."""
    # mt_daemon_registry 在 database/app.db (业务主库), 不在 core/app.db (调度器自己用的)
    BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # health_api.py 在 app/api/, 往上 3 层是 flask-app/
    # 业务主库是 flask-app/database/app.db
    db = os.path.join(BASE, 'database', 'app.db')
    if not os.path.exists(db):
        return {'status': 'unknown', 'error': f'DB not found: {db}'}
    try:
        conn = sqlite3.connect(db, timeout=3)
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM mt_daemon_registry GROUP BY status"
        ).fetchall()
        details = dict(rows)
        running = details.get('RUNNING', 0)
        exited = details.get('EXITED', 0)
        crashed = details.get('CRASHED', 0)
        conn.close()
        status = 'healthy' if crashed == 0 and running > 0 else 'degraded'
        return {
            'status': status,
            'running': running,
            'exited': exited,
            'crashed': crashed,
            'total': running + exited + crashed,
            'note': 'EXITED=run-once scripts; CRASHED 非零即异常'
        }
    except Exception as e:
        return {'status': 'unknown', 'error': str(e)}


def check_remote_nodes():
    """拉远程节点 /api/health/quick, 三节点聚合."""
    results = []
    overall = 'healthy'
    for name, host, port in NODE_TOPOLOGY:
        if name == 'dev':
            # 本地直接查, 省一次 HTTP
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app.db')
            db = check_database_connection(db_path)
            node_status = 'healthy' if db['status'] == 'healthy' else 'unhealthy'
            results.append({'node': name, 'host': host, 'status': node_status, 'latency_ms': 0})
        else:
            url = f'http://{host}:{port}/health'
            try:
                start = time.time()
                r = requests.get(url, timeout=2)
                lat = round((time.time() - start) * 1000, 2)
                if r.status_code == 200:
                    st = r.json().get('status', 'healthy')
                    # mini/hulk /health 返回 status=sandbox-5001, 视为 healthy
                    node_status = 'healthy' if st not in ('offline','error','frozen') else 'degraded'
                else:
                    node_status = f'http_{r.status_code}'
                results.append({'node': name, 'host': host, 'status': node_status, 'latency_ms': lat})
                if node_status != 'healthy':
                    overall = 'degraded'
            except Exception as e:
                results.append({'node': name, 'host': host, 'status': 'unreachable', 'error': str(e)})
                overall = 'degraded'
    return {'status': overall, 'nodes': results}


@health_api.route('/api/health', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def health_check():
    metrics = get_system_metrics()
    services = get_service_status()
    
    overall_status = 'healthy'
    for service_name, service_info in services.items():
        if service_info.get('status') == 'unhealthy':
            overall_status = 'unhealthy'
            break
    
    response = {
        'status': overall_status,
        'timestamp': datetime.now().isoformat(),
        'system': metrics,
        'services': services
    }
    
    http_status = 200 if overall_status == 'healthy' else 503
    return jsonify(response), http_status


@health_api.route('/api/health/system', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def system_metrics():
    metrics = get_system_metrics()
    return jsonify({
        'success': True,
        'data': metrics,
        'timestamp': datetime.now().isoformat()
    })


@health_api.route('/api/health/services', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def service_status():
    services = get_service_status()
    return jsonify({
        'success': True,
        'data': services,
        'timestamp': datetime.now().isoformat()
    })


@health_api.route('/api/health/database', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def database_health():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app.db')
    result = check_database_connection(db_path)
    return jsonify({
        'success': result['status'] == 'healthy',
        'data': result,
        'timestamp': datetime.now().isoformat()
    })


@health_api.route('/api/health/redis', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def redis_health():
    result = check_redis_connection()
    return jsonify({
        'success': result['status'] == 'healthy',
        'data': result,
        'timestamp': datetime.now().isoformat()
    })


@health_api.route('/api/health/scheduler', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def scheduler_health():
    result = check_scheduler_status()
    return jsonify({
        'success': result['status'] == 'healthy',
        'data': result,
        'timestamp': datetime.now().isoformat()
    })


@health_api.route('/api/health/quick', methods=['GET'])
@system_container(require_auth='guest', audit=False)
def quick_health():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app.db')
    db_status = check_database_connection(db_path)
    
    status = 'healthy' if db_status['status'] == 'healthy' else 'unhealthy'
    
    return jsonify({
        'status': status,
        'timestamp': datetime.now().isoformat()
    }), 200 if status == 'healthy' else 503