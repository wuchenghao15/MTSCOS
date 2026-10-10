#!/usr/bin/env python3
"""
🧊 冰山移动管理端 · Flask 蓝图
==================================
路由:
  GET  /iceberg/mobile         → 冰山管理端页面
  GET  /api/iceberg/mobile     → 冰山状态聚合 (移动端拉取)
  GET  /api/iceberg/new_directions → 自发明方向列表
  GET  /api/iceberg/daemon_status  → daemon 在线状态
"""

import os, sys, json, sqlite3, urllib.request
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request
from functools import wraps

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, 'database', 'app.db')
# daemon_registry / ai_employees 等仙女座引擎数据在 engines/app.db
ENGINES_DB = os.path.join(PROJECT_ROOT, 'engines', 'app.db')

mobile_iceberg_bp = Blueprint('mobile_iceberg', __name__)

def _db():
    return sqlite3.connect(DB_PATH)

def c(db, q):
    r = db.execute(q).fetchone()
    return r[0] if r else 0

def _f(n):
    """大数格式化"""
    if not n: return 0
    if n >= 10000: return f"{n/10000:.1f}w"
    return n

# ========================================================
# 页面
# ========================================================

@mobile_iceberg_bp.route('/iceberg/mobile', methods=['GET'])
def page_mobile():
    """🧊 冰山移动管理端页面"""
    # 检查登录态 (session 里有 user_id 即可)
    from flask import session, redirect
    if not session.get('user_id'):
        return redirect('/auth/login')

    db = _db()
    sync_tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN (SELECT name FROM sqlite_master WHERE type='table')"
    ).fetchall()
    # 从 mac_mini_sync_engine.SYNC_TABLES 拿
    sync_list = []
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from engines.mac_mini_sync_engine import SYNC_TABLES
        sync_list = [{'name': t[0], 'col': t[1]} for t in SYNC_TABLES]
    except Exception:
        pass
    db.close()
    return render_template('mobile/iceberg_manage.html', sync_tables_json=json.dumps(sync_list, ensure_ascii=False))


# ========================================================
# API: 状态聚合 (移动端用)
# ========================================================

@mobile_iceberg_bp.route('/api/iceberg/mobile', methods=['GET'])
def api_mobile_status():
    """聚合返回冰山核心状态"""
    db = _db()

    # runs / recent / recent20
    runs = c(db, "SELECT COUNT(*) FROM mt_iceberg_consciousness_runs")
    executions = c(db, "SELECT COUNT(*) FROM mt_iceberg_upgrade_execution")

    recent = db.execute(
        "SELECT id, substr(created_at,12,5), evolution_decision, brain_feed_delta "
        "FROM mt_iceberg_consciousness_runs ORDER BY id DESC LIMIT 5"
    ).fetchall()
    recent20 = db.execute(
        "SELECT id, substr(created_at,12,5), evolution_decision, brain_feed_delta, "
        "COALESCE(substr(upgrade_direction,1,40),'') "
        "FROM mt_iceberg_consciousness_runs ORDER BY id DESC LIMIT 20"
    ).fetchall()

    # 决策分布
    dist_rows = db.execute(
        "SELECT evolution_decision, COUNT(*) FROM mt_iceberg_consciousness_runs "
        "GROUP BY evolution_decision"
    ).fetchall()
    decision_dist = {d: n for d, n in dist_rows}

    # 方向 TOP 10
    top_dirs = db.execute(
        "SELECT direction_num, substr(direction_desc,1,40), hit_count "
        "FROM mt_iceberg_direction_registry ORDER BY hit_count DESC LIMIT 10"
    ).fetchall()

    # 脑库总量 + 最近增量
    brain = c(db, "SELECT COUNT(*) FROM mt_ai_brain_feed_log")
    try:
        brain_delta = c(db,
            "SELECT brain_feed_delta FROM mt_iceberg_consciousness_runs ORDER BY id DESC LIMIT 1")
    except Exception:
        brain_delta = 0

    db.close()

    def fmt_row(r, n_fields):
        if n_fields == 4:
            return {'id': r[0], 'time': r[1], 'decision': r[2], 'brain_delta': r[3]}
        if n_fields == 5:
            return {'id': r[0], 'time': r[1], 'decision': r[2], 'brain_delta': r[3],
                    'upgrade_direction': r[4]}

    return jsonify({
        'runs': runs,
        'executions': executions,
        'brain': brain,
        'brain_delta': brain_delta or 0,
        'decision_dist': decision_dist,
        'recent': [fmt_row(r, 4) for r in recent],
        'recent20': [fmt_row(r, 5) for r in recent20],
        'top_dirs': [{'num': d[0], 'desc': d[1], 'hit': d[2]} for d in top_dirs],
    })


@mobile_iceberg_bp.route('/api/iceberg/new_directions', methods=['GET'])
def api_new_directions():
    """自发明方向列表"""
    db = _db()
    rows = db.execute(
        "SELECT id, direction_key, direction_cn, seed_employees, created_at "
        "FROM mt_iceberg_new_direction_registry ORDER BY id"
    ).fetchall()

    # emoji 映射
    icon_map = {
        'music_edu': '🎵', 'mental_health': '🧠', 'data_viz_auto': '📊',
        'astronomy_edu': '🌌', 'multi_lang_trans': '🗣️', 'legal_search': '🏛️',
        'iot_orchestration': '🔌', 'gamified_learning': '🎮',
        'news_fact_check': '📰', 'career_skill_graph': '💼',
    }

    items = []
    for r in rows:
        items.append({
            'id': r[0],
            'key': r[1],
            'cn_name': r[2],
            'icon': icon_map.get(r[1], '🎯'),
            'seed_employees': r[3],
            'created_at': str(r[4])[:16],
        })
    db.close()
    return jsonify({'list': items, 'total': len(items)})


@mobile_iceberg_bp.route('/api/iceberg/daemon_status', methods=['GET'])
def api_daemon_status():
    """两个关键 daemon 是否在跑"""
    import subprocess

    def _running(pattern):
        r = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True)
        return r.returncode == 0 and bool(r.stdout.strip())

    return jsonify({
        'iceberg': _running('iceberg_consciousness.*启动'),
        'empower': _running('auto_empower_engine.*启动'),
        'flask': _running('modular_start'),
    })


# ========================================================
# 赋能状态聚合 (移动端用 · 补遗漏字段)
# ========================================================

@mobile_iceberg_bp.route('/api/iceberg/empower_mobile', methods=['GET'])
def api_empower_mobile():
    """赋能状态 (移动端轻量)"""
    db = _db()
    employees = c(db, "SELECT COUNT(*) FROM mt_ai_employee_profiles")
    avg_sen = db.execute("SELECT AVG(seniority_years) FROM mt_ai_employee_profiles").fetchone()[0] or 0
    contributions = c(db, "SELECT COUNT(*) FROM mt_ai_employee_contributions")
    consultations = c(db, "SELECT COUNT(*) FROM mt_ai_employee_consultations")
    edges = c(db, "SELECT COUNT(*) FROM mt_ai_employee_social_graph")
    mentor_pairs = c(db, "SELECT COUNT(*) FROM mt_ai_employee_social_graph WHERE relation='MENTOR'")

    # 资历段位
    buckets = []
    for lo, hi, label in [(0,50,'<50'), (50,60,'50-59'), (60,70,'60-69'), (70,80,'70-79'), (80,90,'80-89'), (90,100,'90-99')]:
        cnt = c(db, f"SELECT COUNT(*) FROM mt_ai_employee_profiles WHERE seniority_years>={lo} AND seniority_years<{hi}")
        buckets.append({'range': label, 'count': cnt})
    total_b = sum(b['count'] for b in buckets) or 1
    for b in buckets: b['pct'] = round(b['count'] / total_b * 100, 1)

    # TOP 10 员工
    top = db.execute(
        "SELECT p.name, p.domain, p.seniority_years, COUNT(c.contr_id) AS cnt "
        "FROM mt_ai_employee_profiles p LEFT JOIN mt_ai_employee_contributions c ON c.employee_id = p.employee_id "
        "GROUP BY p.employee_id ORDER BY COUNT(c.contr_id) DESC LIMIT 10"
    ).fetchall()
    top_emps = [{'name': r[0], 'domain': r[1] or '', 'seniority': round(r[2] or 0, 1), 'contribs': r[3]} for r in top]

    db.close()
    return jsonify({
        'employees': employees,
        'avg_seniority': round(avg_sen, 1),
        'contributions': contributions,
        'consultations': consultations,
        'edges': edges,
        'mentor_pairs': mentor_pairs,
        'seniority_buckets': buckets,
        'top_employees': top_emps,
    })


# ========================================================
# 📡 蓝牙 API (移动端专用)
# ========================================================

@mobile_iceberg_bp.route('/api/iceberg/ble/devices', methods=['GET'])
def api_ble_devices():
    """已扫描的 BLE 设备清单 (Flask DB 历史)"""
    db = _db()
    rows = db.execute(
        "SELECT id, name, address, local_name, rssi, scan_count, "
        "last_seen, first_seen, services "
        "FROM mt_ble_devices ORDER BY last_seen DESC LIMIT 50"
    ).fetchall()
    items = []
    for r in rows:
        try:
            services = json.loads(r[6]) if r[6] else []
        except: services = []
        items.append({
            'id': r[0], 'name': r[1] or '(未知)', 'address': r[2],
            'local_name': r[3], 'rssi': r[4], 'scan_count': r[5],
            'last_seen': r[7], 'first_seen': r[8],
            'services': services,
        })
    gatt_count = c(db, "SELECT COUNT(*) FROM mt_ble_gatt_cache")
    try:
        arduino_count = c(db, "SELECT COUNT(*) FROM mt_arduino_detected_devices")
    except: arduino_count = 0
    db.close()
    return jsonify({
        'devices': items,
        'total': len(items),
        'gatt_cache_count': gatt_count,
        'arduino_devices': arduino_count,
    })


@mobile_iceberg_bp.route('/api/iceberg/ble/gatt/<addr>', methods=['GET'])
def api_ble_gatt(addr):
    """单台设备的 GATT 缓存详情"""
    db = _db()
    rows = db.execute(
        "SELECT svc_name, chr_name, chr_props, chr_value_hex, chr_readable, chr_writeable, chr_notifyable "
        "FROM mt_ble_gatt_cache WHERE device_addr=? ORDER BY svc_name, chr_name",
        (addr,)
    ).fetchall()
    services = {}
    for r in rows:
        svc = r[0] or 'Unknown'
        if svc not in services: services[svc] = []
        services[svc].append({
            'name': r[1], 'props': r[2], 'value_hex': r[3],
            'readable': bool(r[4]), 'writeable': bool(r[5]), 'notifyable': bool(r[6]),
        })
    db.close()
    return jsonify({'device': addr, 'services': services})


@mobile_iceberg_bp.route('/api/iceberg/ble/arduino', methods=['GET'])
def api_ble_arduino():
    """Arduino 已检测设备"""
    db = _db()
    try:
        rows = db.execute(
            "SELECT device_name, vid_pid, status, last_heartbeat, driver_adapted "
            "FROM mt_arduino_detected_devices ORDER BY last_heartbeat DESC LIMIT 20"
        ).fetchall()
        items = [{'name': r[0], 'vid_pid': r[1], 'status': r[2],
                  'last_hb': r[3], 'driver': r[4]} for r in rows]
    except:
        items = []
    db.close()
    return jsonify({'devices': items, 'total': len(items)})


# ========================================================
# 🔐 管理员 API (daemon / health / log)
# ========================================================

@mobile_iceberg_bp.route('/api/iceberg/admin/daemons', methods=['GET'])
def api_admin_daemons():
    """daemon 注册表 + 运行状态 (smart_mount_processes 动态数据 + daemon_registry 静态配置 + pgrep 双重校验)"""
    import subprocess, re
    db = sqlite3.connect(ENGINES_DB)

    # 核心修复: 用 JOIN 把两个表拼起来!
    # smart_mount_processes (动态进程): process_name, pid, heartbeat_at, restart_count, current_state
    # daemon_registry (静态配置): daemon_name, description, status, last_heartbeat
    sql = """
        SELECT
            COALESCE(s.process_name, d.daemon_name)     AS name,
            COALESCE(d.description, '')                 AS duty,
            COALESCE(s.current_state, d.status, 'UNKNOWN') AS status,
            COALESCE(s.restart_count, 0)                AS restart_count,
            COALESCE(s.heartbeat_at, d.last_heartbeat)  AS last_heartbeat,
            s.pid                                       AS pid
        FROM mt_daemon_registry d
        LEFT JOIN mt_ai_smart_mount_processes s
               ON s.process_name = d.daemon_name
        WHERE COALESCE(s.process_name, d.daemon_name) IS NOT NULL
        ORDER BY status DESC, name ASC
    """
    try:
        rows = db.execute(sql).fetchall()
    except sqlite3.OperationalError:
        # smart_mount_processes 不存在 -> 退回 daemon_registry (用正确的 daemon_name 列!)
        rows = db.execute(
            "SELECT daemon_name, description, status, 0, last_heartbeat, NULL "
            "FROM mt_daemon_registry ORDER BY status DESC, daemon_name"
        ).fetchall()

    # pgrep 进程名匹配 (存活验证)
    try:
        pgrep_out = subprocess.check_output(
            ['pgrep', '-af', '(python|iceberg|smart_mount|handshake|autosync|daemon)'],
            text=True, timeout=3
        )
        live_procs = pgrep_out.strip().split('\n')
    except Exception:
        live_procs = []

    _NAME_MAP = {
        'heartbeat': ['heartbeat_writer'], 'patrol': ['patrol_inspector'],
        'arduino_detect': ['arduino_detect'], 'eigenflux': ['eigenflux_network'],
        'auto_repair': ['auto_repair'], 'local_inference': ['local_inference'],
        'rule_enforcer': ['rule_enforcer'], 'auto_patrol': ['auto_patrol'],
        'auto_hire': ['auto_hire'], 'deep_inspection': ['deep_inspection'],
        'edu_sync': ['edu_sync'], 'file_organizer': ['file_organizer'],
        'copy_inspection': ['copy_inspection'], 'andromeda': ['andromeda_evolution'],
    }

    def _pgrep_alive(name):
        patterns = [name]
        for key, extras in _NAME_MAP.items():
            if key in name:
                patterns.extend(extras)
        for line in live_procs:
            for p in patterns:
                if p and p in line:
                    return True, line.split()[0] if line.split() else None
        return False, None

    items = []
    for r in rows:
        name, duty, status, rc, hb, pid = r
        alive = False
        real_pid = pid
        # 方式 1: pid 字段
        if pid:
            try:
                os.kill(int(pid), 0)
                alive = True
            except Exception:
                pass
        # 方式 2: pgrep 进程名匹配
        if not alive:
            alive, found_pid = _pgrep_alive(name)
            if found_pid:
                real_pid = found_pid
        items.append({
            'name': name, 'duty': duty or '',
            'status': status or 'UNKNOWN',
            'restart_count': rc or 0,
            'last_heartbeat': hb,
            'pid': real_pid, 'alive': alive,
        })
    run = [i for i in items if i['status'] == 'RUNNING' and i['alive']]
    dead = [i for i in items if i['status'] == 'RUNNING' and not i['alive']]
    stopped = [i for i in items if i['status'] != 'RUNNING']
    db.close()
    return jsonify({
        'daemons': items, 'total': len(items),
        'running': len(run), 'zombie': len(dead), 'stopped': len(stopped),
    })


@mobile_iceberg_bp.route('/api/iceberg/admin/health', methods=['GET'])
def api_admin_health():
    """系统健康快照"""
    import shutil, os as _os
    db = _db()
    # DB 大小
    db_size = 0
    try:
        db_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'database', 'app.db')
        db_size = _os.path.getsize(db_path) if _os.path.exists(db_path) else 0
    except: pass
    # DB 表数
    try:
        table_count = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    except: table_count = 0
    # 各引擎核心计数
    counts = {}
    for label, table, default in [
        ('daemons', 'mt_daemon_registry', 0),
        ('ble_devices', 'mt_ble_devices', 0),
        ('brain_feed', 'mt_ai_brain_feed_log', 0),
        ('ice_runs', 'mt_iceberg_consciousness_runs', 0),
        ('emp_employees', 'mt_ai_employee_profiles', 0),
        ('aurora_skills', 'mt_aurora_skill_registry', 0),
    ]:
        try: counts[label] = c(db, f"SELECT COUNT(*) FROM {table}")
        except: counts[label] = default
    db.close()
    # 磁盘
    try:
        disk = shutil.disk_usage('/')
        disk_pct = round(disk.used / disk.total * 100, 1)
    except: disk_pct = 0
    # Flask
    flask_pid = None
    try:
        import subprocess as sp
        out = sp.check_output(['lsof', '-ti', ':8888'], text=True, timeout=3).strip()
        flask_pid = int(out.split('\n')[0]) if out else None
    except: pass
    return jsonify({
        'db_size_mb': round(db_size / 1024 / 1024, 1),
        'table_count': table_count,
        'disk_pct': disk_pct,
        'flask_pid': flask_pid,
        'counts': counts,
        'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


@mobile_iceberg_bp.route('/api/iceberg/admin/actions', methods=['POST'])
def api_admin_actions():
    """管理员操作: restart_daemon / stop_daemon / ping_sync"""
    import subprocess
    data = request.get_json(silent=True) or {}
    action = data.get('action', '')
    target = data.get('target', '')
    result = {'action': action, 'target': target, 'ok': False, 'msg': ''}

    # 仅允许 restart / stop / ping
    if action == 'restart_daemon' and target:
        # 触发 autosync 重启 (daemon 名字交给 smart_mount_engine 重启)
        # 这里只返回 ack，实际由 daemon 自己监控重启
        result['ok'] = True
        result['msg'] = f'🔄 已提交 {target} 重启请求 (daemon 自动巡检时执行)'
    elif action == 'ping_sync':
        # 触发 handshake ping
        try:
            r = urllib.request.urlopen('http://127.0.0.1:8888/api/handshake/ping', timeout=5)
            result['ok'] = True
            result['msg'] = '📡 握手 ping 已发送'
        except Exception as e:
            result['msg'] = f'❌ ping 失败: {e}'
    elif action == 'flask_status':
        pid = None
        try:
            out = subprocess.check_output(['lsof', '-ti', ':8888'], text=True, timeout=3).strip()
            pid = int(out.split('\n')[0]) if out else None
        except: pass
        result['ok'] = bool(pid)
        result['msg'] = f'Flask PID={pid}' if pid else 'Flask DOWN'
        result['pid'] = pid
    else:
        result['msg'] = f'未知操作: {action}'
    return jsonify(result)


# ========================================================
# 📱 APK 下载路由 (小米 13 WiFi 安装)
# ========================================================
@mobile_iceberg_bp.route('/apk', methods=['GET'])
def apk_landing():
    """📱 APK 下载引导页 (小米 13 / 所有手机)"""
    import flask as _f
    return _f.send_from_directory(PROJECT_ROOT, 'apk_download.html', mimetype='text/html')

@mobile_iceberg_bp.route('/apk/binary', methods=['GET'])
@mobile_iceberg_bp.route('/apk/download', methods=['GET'])
def serve_apk_binary():
    """真正的 APK 二进制下载 — send_from_directory 绕过拦截"""
    import flask as _f
    apk_dir = os.path.dirname(PROJECT_ROOT)  # flask-app 的父目录 = 项目根
    return _f.send_from_directory(
        apk_dir,
        'MTSCOS-AI-Iceberg-Mobile-v25.3.0-debug.apk',
        as_attachment=True,
        download_name='MTSCOS-AI-Iceberg-Mobile-v25.3.0-debug.apk',
        mimetype='application/vnd.android.package-archive',
        conditional=True,
    )
