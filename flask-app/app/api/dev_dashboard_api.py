#!/usr/bin/env python3
"""
dev_dashboard_api.py — 仅开发机可见的同步 Dashboard
访问控制: IP 白名单 (127.0.0.1 + 192.168.11.* + 192.168.1.*)
路由前缀: /api/dev/dashboard/*
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context, render_template
import sqlite3
import time
import json
import os
import subprocess
from datetime import datetime

dev_dashboard_api = Blueprint('dev_dashboard', __name__, url_prefix='/api/dev/dashboard')

# ═══════════════════════════════════════════
# 访问控制 — 仅开发机 IP
# ═══════════════════════════════════════════
DEV_IP_PREFIXES = [
    '127.0.0.',       # IPv4 loopback
    '::1',            # IPv6 loopback (Flask 默认)
    '192.168.11.',    # 家局域网
    '192.168.',       # 所有内网
    '10.',             # VPN
    '172.',            # Docker / 容器
]

def _is_dev_ip():
    """检查来源 IP 是否在白名单 — 支持 IPv6 loopback"""
    remote = request.remote_addr or '127.0.0.1'
    real_ip = request.headers.get('X-Forwarded-For', remote).split(',')[0].strip()
    # IPv6 loopback 特例 (Flask 默认监听 ::1)
    if real_ip in ('::1', '127.0.0.1', 'localhost'):
        return True
    for prefix in DEV_IP_PREFIXES:
        if real_ip.startswith(prefix):
            return True
    return False

@dev_dashboard_api.before_request
def _gate():
    if not _is_dev_ip():
        return jsonify({'error': 'Forbidden — dev dashboard only', 'ip': request.remote_addr}), 403

# ═══════════════════════════════════════════
# DB 连接 (复用 Flask 主库)
# ═══════════════════════════════════════════
DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'app.db')

def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn

# ═══════════════════════════════════════════
# 数据聚合
# ═══════════════════════════════════════════
def _aggregate():
    """从所有相关表聚合实时数据"""
    now = datetime.now()
    data = {
        'ts': now.isoformat(),
        'ts_epoch': int(time.time()),
        'system': {},
        'daemons': {},
        'employees': {},
        'handshake': {},
        'subsystems': {},
        'ai_passport': {},
        'cluster': {},
    }
    
    conn = _db()
    try:
        # ── System 基础 ──
        try:
            cur = conn.execute("SELECT sqlite_version()")
            data['system']['sqlite'] = cur.fetchone()[0]
        except: pass
        
        data['system']['pid'] = os.getpid()
        try:
            load = os.getloadavg()
            data['system']['load'] = {'1min': load[0], '5min': load[1], '15min': load[2]}
        except: pass
        try:
            mem = subprocess.check_output(['vm_stat'], text=True)
            data['system']['vmstat'] = mem[:300]
        except: pass
        
        # ── Daemon 统计 ──
        try:
            cur = conn.execute("SELECT status, COUNT(*) FROM mt_daemon_registry GROUP BY status")
            rows = cur.fetchall()
            data['daemons']['by_status'] = {r[0] or 'UNKNOWN': r[1] for r in rows}
            cur = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry")
            data['daemons']['total'] = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry WHERE status='RUNNING'")
            data['daemons']['running'] = cur.fetchone()[0]
            
            # 运行的 daemon 列表 (top 15) — 主库 database/app.db 列: process_name, duty, pid
            try:
                cur = conn.execute(
                    "SELECT process_name, status, duty, pid, last_heartbeat "
                    "FROM mt_daemon_registry ORDER BY last_heartbeat DESC LIMIT 15"
                )
                top_rows = [dict(r) for r in cur.fetchall()]
                # duty → duty_cycle_s (主库 duty 是 "描述+周期" 文本, 如 "系统心跳写入 30s")
                import re as _re
                for row in top_rows:
                    duty_text = str(row.pop('duty', '') or '')
                    m = _re.search(r'(\d+)\s*[smh]', duty_text)
                    if m:
                        secs = int(m.group(1))
                        if 'm' in duty_text: secs *= 60
                        elif 'h' in duty_text: secs *= 3600
                        row['duty_cycle_s'] = secs
                    else:
                        row['duty_cycle_s'] = 600  # fallback
                data['daemons']['top'] = top_rows
            except Exception as e:
                data['daemons']['top'] = []
                data['daemons']['top_error'] = str(e)[:200]
        except Exception as e:
            data['daemons']['error'] = str(e)[:200]
        
        # ── AI 员工 ──
        try:
            cur = conn.execute("SELECT employee_type, COUNT(*) FROM mt_andromeda_employee_registry GROUP BY employee_type")
            rows = cur.fetchall()
            data['employees']['by_type'] = {r[0] or 'UNKNOWN': r[1] for r in rows}
            cur = conn.execute("SELECT COUNT(*) FROM mt_andromeda_employee_registry")
            data['employees']['total'] = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM mt_andromeda_employee_registry WHERE enabled=1")
            data['employees']['enabled'] = cur.fetchone()[0]
        except Exception as e:
            data['employees']['error'] = str(e)
        
        # ── 握手 MacBook ↔ Mac mini ──
        try:
            # mt_evolution_log 真实列: phase, action, severity, file_path, status, created_at
            cur = conn.execute(
                "SELECT phase, action, severity, status, file_path, created_at "
                "FROM mt_evolution_log ORDER BY id DESC LIMIT 10"
            )
            data['handshake']['evolution_recent'] = [dict(r) for r in cur.fetchall()]
            
            # mt_handshake_reports: host_node, guest_node, guest_host, summary, created_at
            cur = conn.execute(
                "SELECT id, report_id, host_node, guest_node, guest_host, summary, created_at "
                "FROM mt_handshake_reports ORDER BY id DESC LIMIT 5"
            )
            data['handshake']['reports'] = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            data['handshake']['error'] = str(e)
        
        # ── 子系统任务 (25 仙女星域) ──
        subsystem_tables = {
            '文曲星':   'mt_wenquxing_tasks',
            '瑶池':     'mt_yaochi_tasks',
            '梵音':     'mt_fanyin_tasks',
            '繁花':     'mt_fanhua_tasks',
            '混天绫':   'mt_huntianling_tasks',
            '太极':     'mt_taiji_tasks',
            '紫微':     'mt_ziwei_tasks',
            '伏羲':     'mt_fuxi_tasks',
            '女娲':     'mt_nuwa_tasks',
            '鲁班':     'mt_luban_tasks',
            '扁鹊':     'mt_bianque_tasks',
            '仓颉':     'mt_cangjie_tasks',
            '后羿':     'mt_houyi_tasks',
            '真武':     'mt_zhenwu_tasks',
            '管仲':     'mt_guanzhong_tasks',
            '范蠡':     'mt_fanli_tasks',
            '神农':     'mt_shennong_tasks',
            '貔貅':     'mt_pixiu_tasks',
            '太公':     'mt_taigong_tasks',
            '应龙':     'mt_yinglong_tasks',
            '羲和':     'mt_xihe_tasks',
            '共工':     'mt_gonggong_tasks',
            '哪吒':     'mt_nezha_tasks',
            '月老':     'mt_yuelao_tasks',
            '千手':     'mt_qianshou_tasks',
        }
        subsys = {}
        heatmap = []
        for name, tbl in subsystem_tables.items():
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {tbl}")
                cnt = cur.fetchone()[0]
                subsys[name] = {'table': tbl, 'count': cnt}
                heatmap.append({'name': name, 'count': cnt, 'table': tbl})
            except:
                subsys[name] = {'table': tbl, 'count': 'N/A'}
                heatmap.append({'name': name, 'count': 0, 'table': tbl})
        # 按 count 排序
        heatmap.sort(key=lambda x: (x['count'] if isinstance(x['count'], int) else -1), reverse=True)
        data['subsystems']['by_domain'] = subsys
        data['subsystems']['heatmap'] = heatmap
        data['subsystems']['total_tasks'] = sum(
            v['count'] for v in subsys.values() if isinstance(v['count'], int)
        )

        # ── BLE / USB / Ollama 实时状态 ──
        ble = {}
        # USB 设备
        try:
            usb_devices = []
            for path in ['/dev/cu.usbmodem101', '/dev/cu.usbserial']:
                if os.path.exists(path):
                    usb_devices.append(path)
            ble['usb_devices'] = usb_devices
            ble['usb_count'] = len(usb_devices)
        except: pass
        # Ollama
        try:
            import urllib.request
            req = urllib.request.Request('http://127.0.0.1:11434/api/tags', headers={'User-Agent': 'dev-dashboard'})
            with urllib.request.urlopen(req, timeout=2) as resp:
                ollama_data = json.loads(resp.read())
                ble['ollama'] = {
                    'ok': True,
                    'models': [{'name': m['name'], 'size_mb': round(m.get('size',0)/1024/1024)} for m in ollama_data.get('models', [])],
                    'count': len(ollama_data.get('models', [])),
                }
        except Exception as e:
            ble['ollama'] = {'ok': False, 'error': str(e)[:100]}
        # MQTT Broker
        try:
            import socket
            s = socket.socket(); s.settimeout(1)
            s.connect(('127.0.0.1', 1883))
            s.close()
            ble['mqtt_broker'] = {'ok': True, 'port': 1883}
        except Exception:
            ble['mqtt_broker'] = {'ok': False}
        data['devices'] = ble
        
        # ── 规则变更 ──
        try:
            cur = conn.execute(
                "SELECT rule_id, to_version, change_type, change_summary, created_at "
                "FROM mt_rule_changelog ORDER BY created_at DESC LIMIT 5"
            )
            data['system']['rule_changes'] = [dict(r) for r in cur.fetchall()]
        except: pass
        
        # ── AI Passport (本地 VIKEY 硬件状态) ──
        # 🆕 2026-10-05: 支持多个 AI Passport (扫描 /dev/cu.usbmodem*)
        import glob as _glob
        usb_passports = sorted(set(_glob.glob('/dev/cu.usbmodem*') + _glob.glob('/dev/tty.usbmodem*')))
        ai_passport_devices = [p for p in usb_passports if 'Bluetooth' not in p]
        data['ai_passport']['usb'] = len(ai_passport_devices) > 0
        data['ai_passport']['usb_count'] = len(ai_passport_devices)
        data['ai_passport']['devices'] = ai_passport_devices
        # 取第一个设备的实时状态 (如果有)
        if ai_passport_devices:
            try:
                mtime = os.path.getmtime(ai_passport_devices[0])
                data['ai_passport']['first_seen_epoch'] = int(mtime)
            except: pass
        
        # ── 仙女座集群占比 (MacBook ↔ Mac mini) ──
        cluster = data['cluster']
        
        # --- MacBook 端实时聚合 ---
        macbook = {
            'hostname': 'MTSCOS-MacBook',
            'role': 'MASTER',
            'daemons_running': 0,
            'daemons_total': 0,
            'ai_employees': 0,
            'rules_count': 0,
            'iron_violations': 0,
            'brain_logs': 0,
            'qbank_items': 0,
            'subsystem_tasks': 0,
            'status': 'online',
        }
        try:
            cur = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry")
            macbook['daemons_total'] = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry WHERE status='RUNNING'")
            macbook['daemons_running'] = cur.fetchone()[0]
        except: pass
        try:
            cur = conn.execute("SELECT COUNT(*) FROM mt_andromeda_employee_registry")
            macbook['ai_employees'] = cur.fetchone()[0]
        except: pass
        try:
            cur = conn.execute("SELECT COUNT(*) FROM mt_rule_changelog")
            macbook['rules_count'] = cur.fetchone()[0]
        except: pass
        try:
            cur = conn.execute("SELECT COUNT(*) FROM mt_iron_rule_violations")
            macbook['iron_violations'] = cur.fetchone()[0]
        except: pass
        try:
            cur = conn.execute("SELECT COUNT(*) FROM mt_ai_brain_feed_log")
            macbook['brain_logs'] = cur.fetchone()[0]
        except: pass
        try:
            # 真实表名是 adult_education_questions (2862 条)
            # mt_qbank_questions 不存在
            try:
                cur = conn.execute("SELECT COUNT(*) FROM adult_education_questions")
            except Exception:
                cur = conn.execute("SELECT COUNT(*) FROM mt_qbank_questions")
            macbook['qbank_items'] = cur.fetchone()[0]
        except: pass
        # 25 星域任务合计
        try:
            total_subsys = 0
            for tbl in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mt_%_tasks'").fetchall()]:
                try:
                    total_subsys += conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                except: pass
            macbook['subsystem_tasks'] = total_subsys
        except: pass
        
        # --- Mac mini 端 (从最新 handshake 记录) ---
        # ⚠️ Mini 是 SLAVE 节点, 不跑 auto_hire daemon → 本地 AI 员工 = 0
        # 它只跑执行型 daemon (29个) + 题库/脑库存储
        mini = {
            'hostname': 'HULK-MACMINI',
            'ip': '192.168.31.9',
            'role': 'SLAVE',
            'ai_employees_note': 'SLAVE 节点不独立雇佣 AI 员工, 共享 MacBook MASTER 的 33,602 人',
            'daemons_running': 0,
            'daemons_total': 0,
            'ai_employees': 0,
            'rules_count': 0,
            'iron_violations': 0,
            'brain_logs': 0,
            'qbank_items': 0,
            'subsystem_tasks': 0,
            'status': 'unknown',
            'last_handshake': None,
        }
        try:
            cur = conn.execute(
                "SELECT phase1_handshake_json, created_at FROM mt_handshake_reports ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                mini['last_handshake'] = row['created_at']
                p1 = json.loads(row['phase1_handshake_json'])
                remote = p1.get('remote_capabilities', {})
                mini['daemons_total'] = remote.get('daemons', 0)
                mini['daemons_running'] = remote.get('daemons', 0)  # handshake 时 Mini 都在跑
                mini['ai_employees'] = remote.get('ai_employees', 0)
                mini['rules_count'] = remote.get('rules', 0)
                mini['iron_violations'] = remote.get('iron_violations', 0)
                mini['brain_logs'] = remote.get('brain_logs', 0)
                mini['qbank_items'] = remote.get('qbank', 0)
                # daemon_status 里的 remote 细节
                ds = p1.get('daemon_status', {})
                if ds.get('remote_host'):
                    mini['hostname'] = ds['remote_host']
        except Exception: pass
        
        # --- Mini 在线状态 (用最近握手时间判断) ---
        # 不用 subprocess/socket — Flask HTTP handler 线程网络行为异常
        # sys_andromeda_autosync_mini_online 每 120s 自动握手落库
        mini_online = False
        handshake_fresh = False
        if mini.get('last_handshake'):
            try:
                hs_time = datetime.strptime(mini['last_handshake'], '%Y-%m-%d %H:%M:%S')
                age_min = (datetime.now() - hs_time).total_seconds() / 60
                handshake_fresh = age_min < 30  # 30 分钟内算在线
                mini['handshake_age_min'] = round(age_min, 1)
            except:
                pass
        
        # 综合状态: 握手新鲜 = online, 有旧数据 = stale, 无数据 = unknown
        if handshake_fresh:
            mini['status'] = 'online'
        elif mini.get('last_handshake'):
            mini['status'] = 'offline_stale'
        else:
            mini['status'] = 'offline_unknown'
        mini['online'] = handshake_fresh
        
        # --- 两端聚合 + 占比 ---
        cluster['macbook'] = macbook
        cluster['mini'] = mini
        
        # 对比指标（每一项 MacBook vs Mini）
        metrics = [
            ('ai_employees', 'AI 员工', '人'),
            ('daemons_running', '运行 Daemon', '个'),
            ('brain_logs', '脑库条目', '条'),
            ('qbank_items', '题库题数', '题'),
            ('rules_count', '规则版本', '版'),
            ('subsystem_tasks', '星域任务', '条'),
        ]
        comparison = []
        for key, label, unit in metrics:
            mb_val = macbook.get(key, 0) or 0
            mn_val = mini.get(key, 0) or 0
            total = mb_val + mn_val
            mb_pct = round(mb_val / total * 100, 1) if total > 0 else 0
            mn_pct = 100 - mb_pct if total > 0 else 0
            comparison.append({
                'key': key, 'label': label, 'unit': unit,
                'macbook': mb_val, 'mini': mn_val,
                'macbook_pct': mb_pct, 'mini_pct': mn_pct,
            })
        cluster['comparison'] = comparison
        
        # 集群总体
        cluster['summary'] = {
            'total_ai_employees': macbook['ai_employees'] + mini['ai_employees'],
            'total_daemons': macbook['daemons_total'] + mini['daemons_total'],
            'total_brain_logs': macbook['brain_logs'] + mini['brain_logs'],
            'nodes': 2,
            'online_nodes': 1 + (1 if mini.get('online') else 0),
        }
        
    finally:
        conn.close()
    
    return data

# ═══════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════

@dev_dashboard_api.route('/')
def index():
    """Dashboard HTML 页面"""
    return render_template('dev_dashboard.html')

@dev_dashboard_api.route('/data')
def data():
    """拉取一次聚合数据"""
    return jsonify(_aggregate())

@dev_dashboard_api.route('/stream')
def stream():
    """
    SSE 实时流 — 5s 推送一次
    前端用 EventSource 消费
    """
    def generate():
        while True:
            try:
                agg = _aggregate()
                yield f"data: {json.dumps(agg, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            time.sleep(5)
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )

@dev_dashboard_api.route('/ping')
def ping():
    """健康检查"""
    return jsonify({
        'pong': True,
        'ts': int(time.time()),
        'dev': True,
        'ip': request.remote_addr,
    })


@dev_dashboard_api.route('/evolution')
def evolution():
    """仙女座演化时间序列 — 多指标日聚合, 用于画曲线图"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403

    # DB 路径 (与 main 一致)
    db_candidates = [
        os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'app.db'),
        '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/database/app.db',
    ]
    db_path = None
    for p in db_candidates:
        if os.path.exists(p):
            db_path = p
            break
    if not db_path:
        return jsonify({'error': 'db_not_found'}), 500

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 每条序列: (key, label, color, table, time_col, value_col, 额外 WHERE)
    # 所有指标按日聚合 DATE()
    # value_col: COUNT(*) 或 SUM(xxx), None 表示默认 COUNT(*)
    SERIES_DEFS = [
        # 1. 握手 (Mini ↔ MacBook)
        ('handshake',    '🤝 握手',     '#7DF9FF', 'mt_handshake_reports',         'created_at', None, ''),
        # 2. 自演化引擎 Cycle — 用 mt_evolution_runs (演化引擎真实写入)
        ('evolve',       '🧬 演化',     '#A78BFA', 'mt_evolution_runs',            'started_at', 'items_ok', ''),
        # 3. 修复 (觉醒日志 = 自动代码修复)
        ('heal',         '💊 修复',     '#4ADE80', 'mt_awakening_log',             'created_at', None, ''),
        # 4. 圆桌会议 (专家圆桌)
        ('roundtable',   '🏮 圆桌',     '#FBBF24', 'mt_roundtable_sessions',       'created_at', None, ''),
        # 5. 规则变更 (规则演进)
        ('rule_change',  '📜 规则演进', '#F87171', 'mt_rule_changelog',            'created_at', None, ''),
        # 6. EigenFlux 消息 (AI 社交/消息)
        ('eigenflux_msg','💬 EigenFlux','34D399', 'eigenflux_comm_messages',      'created_at', None, ''),
        # 7. 开发流 (§14 铁律 12 步骤)
        ('dev_flow',     '🔧 开发流',   '#60A5FA', 'mt_dev_flow_session',          'created_at', None, ''),
        # 8. 自演化日志 (AI 自主决策)
        ('self_evolve',  '🔄 自演化',   '#C084FC', 'mt_ai_self_evolution_log',     'created_at', None, ''),
    ]

    all_dates = set()
    series_data = {}

    for key, label, color, table, time_col, value_col, extra_where in SERIES_DEFS:
        try:
            where = f"WHERE {time_col} IS NOT NULL AND TRIM({time_col}) != '' {extra_where}"
            # value_col 有值时用 SUM, 否则 COUNT(*)
            if value_col:
                cnt_expr = f'SUM({value_col})'
            else:
                cnt_expr = 'COUNT(*)'
            rows = conn.execute(f"""
                SELECT DATE({time_col}) as d, {cnt_expr} as cnt
                FROM {table}
                {where}
                GROUP BY DATE({time_col})
                ORDER BY d
            """).fetchall()
            points = {r['d']: r['cnt'] for r in rows}
            all_dates.update(points.keys())
            series_data[key] = {
                'label': label, 'color': color,
                'table': table, 'points': points,
            }
        except Exception as e:
            series_data[key] = {'label': label, 'color': color, 'error': str(e)[:100], 'points': {}}

    # 对齐日期 (所有序列同日期轴, 缺失填 0)
    sorted_dates = sorted(d for d in all_dates if d)
    # 限制日期范围: 从最早数据开始 (9/10) 到今天
    if sorted_dates:
        start = sorted_dates[0]
        end = sorted_dates[-1]
        # 只保留最近 30 天 (如果跨度更大)
        import datetime as _dt
        try:
            end_dt = _dt.datetime.strptime(end, '%Y-%m-%d')
            start_dt = end_dt - _dt.timedelta(days=30)
            sorted_dates = [d for d in sorted_dates if _dt.datetime.strptime(d, '%Y-%m-%d') >= start_dt]
        except: pass

    aligned = {}
    for key, meta in series_data.items():
        pts = []
        for d in sorted_dates:
            pts.append({'date': d, 'v': meta['points'].get(d, 0)})
        aligned[key] = {
            'label': meta['label'],
            'color': meta['color'],
            'table': meta.get('table', ''),
            'error': meta.get('error'),
            'data': pts,
            'total': sum(p['v'] for p in pts),
        }

    conn.close()

    # 阶段标记 (仙女座演化里程碑)
    MILESTONES = [
        {'phase': '🧪 考试握手',    'date': '2026-09-28', 'desc': 'MacBook ↔ Mini 首次握手建立'},
        {'phase': '🔬 推演启动',    'date': '2026-09-10', 'desc': 'AI 自演化引擎开始推演'},
        {'phase': '⬆️ 规则升级',    'date': '2026-09-19', 'desc': '12 篇规则 L1 核心层升级'},
        {'phase': '💡 觉醒修复',    'date': '2026-09-27', 'desc': '觉醒引擎自动修复 35,997 条'},
        {'phase': '🏛️ 圆桌会议',    'date': '2026-09-25', 'desc': 'EigenFlux 专家圆桌机制启动'},
        {'phase': '🤝 信息共享',    'date': '2026-09-28', 'desc': '双向同步 (Mini ↔ MacBook) 全量跑通'},
        {'phase': '💬 EigenFlux',  'date': '2026-09-19', 'desc': 'AI 员工之间消息 56 万条'},
        {'phase': '🎯 Phase 3→4',   'date': '2026-10-05', 'desc': '🧊 冰山觉醒·演化引擎 Cycle #66 embedding 首次出向量 → Phase 自动升级 江山→衍生'},
    ]

    return jsonify({
        'start_date': sorted_dates[0] if sorted_dates else None,
        'end_date': sorted_dates[-1] if sorted_dates else None,
        'days': len(sorted_dates),
        'dates': sorted_dates,
        'series': aligned,
        'milestones': [m for m in MILESTONES if m['date'] in sorted_dates or 
                       (sorted_dates and m['date'] >= sorted_dates[0] and m['date'] <= sorted_dates[-1])],
        'ts': int(time.time()),
    })


# ═════════════════════════════════════════════════════════════════════════
# 蓝牙开发能力 — BLE 扫描 + 经典蓝牙 + PCM 音频通路
# ═════════════════════════════════════════════════════════════════════════

def _get_bt_db_path():
    for p in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'app.db'),
        '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/database/app.db',
    ]:
        if os.path.exists(p): return p
    return None

def _ensure_bt_tables(conn):
    """幂等创建蓝牙相关表"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mt_ble_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT UNIQUE NOT NULL,
            name TEXT,
            local_name TEXT,
            rssi INTEGER,
            services TEXT,           -- JSON: 服务 UUID 列表
            manufacturer_data TEXT,   -- JSON
            tx_power INTEGER,
            scan_count INTEGER DEFAULT 1,
            last_seen TEXT,
            first_seen TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ble_last_seen ON mt_ble_devices(last_seen);

        CREATE TABLE IF NOT EXISTS mt_ble_gatt_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_addr TEXT NOT NULL,
            device_name TEXT,
            svc_uuid TEXT,
            svc_name TEXT,
            chr_uuid TEXT,
            chr_name TEXT,
            chr_props TEXT,           -- JSON: [read,write,notify,indicate]
            chr_value_hex TEXT,       -- 最后读到的值 (hex)
            chr_readable INTEGER DEFAULT 0,
            chr_writeable INTEGER DEFAULT 0,
            chr_notifyable INTEGER DEFAULT 0,
            explored_at TEXT,
            UNIQUE(device_addr, svc_uuid, chr_uuid)
        );
        CREATE INDEX IF NOT EXISTS idx_gatt_device ON mt_ble_gatt_cache(device_addr);

        CREATE TABLE IF NOT EXISTS mt_ble_pcm_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_addr TEXT,
            device_name TEXT,
            svc_uuid TEXT,
            write_uuid TEXT,
            ack_uuid TEXT,
            samples_sent INTEGER,
            acks_received INTEGER,
            status TEXT,             -- ok/error/partial
            started_at TEXT,
            ended_at TEXT,
            duration_ms INTEGER,
            error_msg TEXT
        );
    """)
    conn.commit()


@dev_dashboard_api.route('/bt/info')
def bt_info():
    """蓝牙硬件信息 + 经典蓝牙设备列表"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403

    info = {'controller': {}, 'paired': [], 'available_libs': []}

    # 硬件信息 (system_profiler)
    try:
        r = subprocess.run(['system_profiler', 'SPBluetoothDataType'],
                           capture_output=True, text=True, timeout=10)
        out = r.stdout
        # 解析 Controller
        for line in out.split('\n'):
            line = line.strip()
            if line.startswith('Address:'): info['controller']['address'] = line.split(':', 1)[1].strip()
            elif line.startswith('State:'): info['controller']['state'] = line.split(':', 1)[1].strip()
            elif line.startswith('Chipset:'): info['controller']['chipset'] = line.split(':', 1)[1].strip()
            elif line.startswith('Firmware Version:'): info['controller']['firmware'] = line.split(':', 1)[1].strip()
            elif line.startswith('Transport:'): info['controller']['transport'] = line.split(':', 1)[1].strip()
            elif line.startswith('Supported services:'): info['controller']['services'] = line.split(':', 1)[1].strip()
            elif line.startswith('Product ID:'): info['controller']['product_id'] = line.split(':', 1)[1].strip()
            elif line.startswith('Vendor ID:'): info['controller']['vendor_id'] = line.split(':', 1)[1].strip()
    except Exception as e:
        info['controller']['error'] = str(e)[:100]

    # Python 库检测
    for lib in ['bleak', 'CoreBluetooth', 'Foundation', 'asyncio']:
        try:
            __import__(lib)
            info['available_libs'].append(lib)
        except: pass

    # 已配对设备 (从 system_profiler 解析)
    current_device = None
    for line in (r.stdout if 'r' in dir() else '').split('\n'):
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith(' ') and ':' in line_stripped[:30]:
            # 可能是设备名
            if current_device:
                info['paired'].append(current_device)
            current_device = {'name': line_stripped}
        elif ':' in line_stripped and current_device:
            k, v = line_stripped.split(':', 1)
            current_device[k.strip().lower().replace(' ', '_')] = v.strip()
    if current_device:
        info['paired'].append(current_device)

    # DB 中已扫描过的 BLE 设备
    db_path = _get_bt_db_path()
    info['db_devices'] = []
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            _ensure_bt_tables(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM mt_ble_devices ORDER BY last_seen DESC LIMIT 20"
            ).fetchall()
            info['db_devices'] = [dict(r) for r in rows]
            # PCM sessions
            pcms = conn.execute(
                "SELECT * FROM mt_ble_pcm_sessions ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
            info['pcm_sessions'] = [dict(r) for r in pcms]
            conn.close()
        except Exception as e:
            info['db_error'] = str(e)[:100]

    info['ts'] = int(time.time())
    return jsonify(info)


@dev_dashboard_api.route('/bt/scan', methods=['GET', 'POST'])
def bt_scan():
    """BLE 扫描 — 异步跑 bleak, 结果落库并返回"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403

    timeout_sec = int(request.args.get('timeout') or request.json.get('timeout', 8))

    # 子进程跑 asyncio bleak (Flask 主线程不能跑 asyncio)
    scan_script = f"""
import asyncio, json, sys, time
try:
    import bleak
except ImportError:
    print(json.dumps({{'error': 'bleak_not_found'}}))
    sys.exit(1)

async def scan():
    scanner = bleak.BleakScanner()
    devices = await scanner.discover(timeout={timeout_sec})
    results = []
    for d in devices:
        meta = getattr(d, 'metadata', {{}}) or {{}}
        adv = meta.get('advertisement_data', {{}}) or {{}}
        results.append({{
            'address': d.address,
            'name': d.name or adv.get('local_name', ''),
            'local_name': adv.get('local_name', ''),
            'rssi': meta.get('rssi'),
            'services': list(getattr(d, 'service_uuids', []) or adv.get('service_uuids', [])),
            'manufacturer_data': {{str(k): list(v) for k,v in adv.get('manufacturer_data', {{}}).items()}},
            'tx_power': adv.get('tx_power'),
        }})
    return results

results = asyncio.run(scan())
print(json.dumps({{'ts': int(time.time()), 'count': len(results), 'devices': results}}, ensure_ascii=False))
"""
    try:
        r = subprocess.run(
            ['python3', '-c', scan_script],
            capture_output=True, text=True, timeout=timeout_sec + 15
        )
        if r.returncode != 0:
            return jsonify({'error': 'scan_failed', 'stderr': r.stderr[:500]}), 500
        data = json.loads(r.stdout.strip().split('\n')[-1])
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'scan_timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)[:100]}), 500

    # 落库
    db_path = _get_bt_db_path()
    if db_path and 'devices' in data:
        try:
            conn = sqlite3.connect(db_path)
            _ensure_bt_tables(conn)
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            for d in data['devices']:
                try:
                    existing = conn.execute(
                        "SELECT id, scan_count, first_seen FROM mt_ble_devices WHERE address=?",
                        (d['address'],)
                    ).fetchone()
                    if existing:
                        new_count = (existing[1] or 1) + 1
                        conn.execute("""UPDATE mt_ble_devices SET name=?, local_name=?, rssi=?,
                            services=?, manufacturer_data=?, tx_power=?, scan_count=?, last_seen=?
                            WHERE address=?""",
                            (d.get('name'), d.get('local_name'), d.get('rssi'),
                             json.dumps(d.get('services', [])), json.dumps(d.get('manufacturer_data', {})),
                             d.get('tx_power'), new_count, now, d['address']))
                    else:
                        conn.execute("""INSERT INTO mt_ble_devices
                            (address, name, local_name, rssi, services, manufacturer_data, tx_power,
                             scan_count, first_seen, last_seen)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (d['address'], d.get('name'), d.get('local_name'), d.get('rssi'),
                             json.dumps(d.get('services', [])), json.dumps(d.get('manufacturer_data', {})),
                             d.get('tx_power'), 1, now, now))
                except: pass
            conn.commit()
            conn.close()
        except: pass

    return jsonify(data)


@dev_dashboard_api.route('/bt/pcm', methods=['POST'])
def bt_pcm():
    """BLE PCM 音频通路测试 — 发送裸 PCM 分片到目标设备"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403

    body = request.get_json(force=True) or {}
    address = body.get('address') or body.get('device')
    if not address:
        return jsonify({'error': 'address_required'}), 400

    svc_uuid = body.get('svc_uuid', '54524145-4341-5244-0000-000000000000')
    write_uuid = body.get('write_uuid', '54524145-4341-5244-0000-000000000010')
    ack_uuid = body.get('ack_uuid', '54524145-4341-5244-0000-000000000011')
    duration_sec = int(body.get('duration', 3))

    pcm_script = f"""
import asyncio, json, sys, time, struct
try:
    import bleak
except ImportError:
    print(json.dumps({{'error': 'bleak_not_found'}}))
    sys.exit(1)

TARGET = '{address}'
SVC = '{svc_uuid}'
WR = '{write_uuid}'
ACK = '{ack_uuid}'
DURATION = {duration_sec}

ack_buf = []
def on_ack(sender, data):
    ack_buf.append(bytes(data))

async def run():
    results = {{'acks': 0, 'bytes_sent': 0, 'status': 'ok', 'error': None}}
    try:
        async with bleak.BleakClient(TARGET, timeout=10) as client:
            if ACK:
                try: await client.start_notify(ACK, on_ack)
                except: pass
            # 生成 PCM 正弦波 (440Hz, 8bit, 8kHz)
            sample_rate = 8000
            samples_needed = sample_rate * DURATION
            chunk_size = 20
            sent = 0
            t0 = time.time()
            for i in range(0, samples_needed, chunk_size):
                chunk = bytearray()
                for j in range(chunk_size):
                    phase = 2 * 3.14159 * 440 * (i + j) / sample_rate
                    chunk.append(int(128 + 60 * __import__('math').sin(phase)) & 0xFF)
                try:
                    await client.write_gatt_char(WR, bytes(chunk), response=False)
                    sent += len(chunk)
                    results['bytes_sent'] = sent
                except Exception as e:
                    results['error'] = str(e)[:100]
                    break
            await asyncio.sleep(0.5)
            results['acks'] = len(ack_buf)
            results['duration_ms'] = int((time.time() - t0) * 1000)
            if results['acks'] > 0: results['status'] = 'ok'
            elif results['error']: results['status'] = 'error'
            else: results['status'] = 'partial_no_ack'
    except Exception as e:
        results['status'] = 'error'
        results['error'] = str(e)[:200]
    print(json.dumps(results))

asyncio.run(run())
"""
    try:
        r = subprocess.run(
            ['python3', '-c', pcm_script],
            capture_output=True, text=True,
            timeout=duration_sec * 3 + 20
        )
        data = json.loads(r.stdout.strip().split('\n')[-1]) if r.stdout.strip() else {'error': r.stderr[:500]}
    except subprocess.TimeoutExpired:
        data = {'status': 'timeout', 'error': f'{duration_sec * 3 + 20}s'}
    except Exception as e:
        data = {'status': 'error', 'error': str(e)[:100]}

    # 落库
    db_path = _get_bt_db_path()
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            _ensure_bt_tables(conn)
            conn.execute("""INSERT INTO mt_ble_pcm_sessions
                (device_addr, svc_uuid, write_uuid, ack_uuid, samples_sent, acks_received,
                 status, started_at, ended_at, duration_ms, error_msg)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (address, svc_uuid, write_uuid, ack_uuid,
                 data.get('bytes_sent', 0), data.get('acks', 0),
                 data.get('status', 'unknown'),
                 time.strftime('%Y-%m-%d %H:%M:%S'), time.strftime('%Y-%m-%d %H:%M:%S'),
                 data.get('duration_ms', 0), data.get('error')))
            conn.commit()
            conn.close()
        except: pass

    return jsonify(data)


# ── GATT 探索 ──────────────────────────────────────────────────────────────

# 常用 BLE Service / Characteristic UUID → 人类可读名称
BLE_UUID_NAMES = {
    # Services
    '1800': ('GAP', 'Generic Access Profile'),
    '1801': ('GATT', 'Generic Attribute Profile'),
    '180d': ('HID', 'Human Interface Device'),
    '1812': ('HID-overGATT', 'HID over GATT Profile'),
    '180f': ('Battery', 'Battery Service'),
    '180a': ('DeviceInfo', 'Device Information'),
    '1819': ('ScanParams', 'Scan Parameters'),
    '181c': ('AUD', 'Audio Control'),
    '1843': ('VCP', 'Volume Control'),
    '1803': ('LinkLoss', 'Link Loss'),
    '1814': ('AlertNotif', 'Alert Notification'),
    '1818': ('HeartRate', 'Heart Rate'),
    '181d': ('CyclingPower', 'Cycling Power'),
    '1826': ('Fitness', 'Fitness Machine'),
    # Characteristics
    '2a00': ('DeviceName', 'Device Name'),
    '2a01': ('Appearance', 'Appearance'),
    '2a02': ('PeripheralPrivacy', 'Peripheral Privacy Flag'),
    '2a19': ('BatteryLevel', 'Battery Level'),
    '2a24': ('ModelNumber', 'Model Number String'),
    '2a25': ('SerialNumber', 'Serial Number String'),
    '2a26': ('FirmwareRev', 'Firmware Revision String'),
    '2a27': ('HardwareRev', 'Hardware Revision String'),
    '2a28': ('SoftwareRev', 'Software Revision String'),
    '2a29': ('ManufacturerName', 'Manufacturer Name String'),
    '2a4d': ('ReportMap', 'HID Report Map'),
    '2a4e': ('HIDControl', 'HID Control Point'),
    '2a4f': ('HIDInfo', 'HID Information'),
    '2a1c': ('BootInput', 'Boot Keyboard Input Report'),
    '2a2d': ('BootOutput', 'Boot Keyboard Output Report'),
    '2a32': ('BootMouseInput', 'Boot Mouse Input Report'),
    '2a4c': ('Report', 'HID Report'),
    '2a50': ('ProtocolMode', 'Protocol Mode'),
    '2a37': ('HeartRateMeasurement', 'Heart Rate Measurement'),
    '2a38': ('BodySensorLocation', 'Body Sensor Location'),
}

def _uuid_short(uuid):
    if not uuid: return ''
    s = str(uuid).lower()
    if s.startswith('0000') and s.endswith('-0000-1000-8000-00805f9b34fb'):
        return s[4:8]
    return s[:8]


@dev_dashboard_api.route('/bt/gatt', methods=['GET', 'POST'])
def bt_gatt():
    """GATT 服务探索 — 连接 BLE 设备列出所有 Service + Characteristic + 属性"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403

    body = request.get_json(silent=True) or {}
    address = request.args.get('address') or body.get('address')
    if not address:
        return jsonify({'error': 'address_required'}), 400
    read_values = (request.args.get('read') or body.get('read', 'false')).lower() in ('1', 'true', 'yes')

    gatt_script = f"""
import asyncio, json, sys, time
try:
    import bleak
except ImportError:
    print(json.dumps({{'error': 'bleak_not_found'}}))
    sys.exit(1)

TARGET = '{address}'
READ_VALUES = {read_values}

def props_to_list(prop_obj):
    names = []
    p = str(prop_obj).lower()
    for kw in ['read','write','write_no_response','notify','indicate','broadcast','signed_write','extended']:
        if kw in p: names.append(kw)
    return sorted(set(names))

async def explore():
    result = {{'services': [], 'error': None, 'connected': False}}
    t0 = time.time()
    try:
        async with bleak.BleakClient(TARGET, timeout=15) as client:
            result['connected'] = True
            for svc in client.services:
                svc_info = {{
                    'uuid': str(svc.uuid),
                    'uuid_short': str(svc.uuid)[:8] if svc.uuid else '',
                    'name': getattr(svc, 'description', None) or '',
                    'characteristics': [],
                }}
                for char in svc.characteristics:
                    prop_list = props_to_list(char.properties)
                    chr_info = {{
                        'uuid': str(char.uuid),
                        'uuid_short': str(char.uuid)[:8] if char.uuid else '',
                        'name': getattr(char, 'description', None) or '',
                        'properties': prop_list,
                        'readable': 'read' in prop_list,
                        'writeable': any(p.startswith('write') for p in prop_list),
                        'notifyable': 'notify' in prop_list or 'indicate' in prop_list,
                        'value_hex': None,
                    }}
                    if READ_VALUES and chr_info['readable']:
                        try:
                            raw = await client.read_gatt_char(char)
                            chr_info['value_hex'] = raw.hex()
                            try: chr_info['value_ascii'] = raw.decode('utf-8', errors='replace')
                            except: pass
                        except Exception as e:
                            chr_info['value_error'] = str(e)[:100]
                    svc_info['characteristics'].append(chr_info)
                result['services'].append(svc_info)
            result['duration_ms'] = int((time.time() - t0) * 1000)
    except Exception as e:
        result['error'] = str(e)[:300]
        result['duration_ms'] = int((time.time() - t0) * 1000)
    print(json.dumps(result, ensure_ascii=False))

asyncio.run(explore())
"""
    try:
        timeout = 45 if read_values else 20
        r = subprocess.run(['python3', '-c', gatt_script], capture_output=True, text=True, timeout=timeout)
        output = r.stdout.strip().split('\n')[-1] if r.stdout.strip() else ''
        if not output:
            return jsonify({'error': 'empty_output', 'stderr': r.stderr[:500]}), 500
        data = json.loads(output)
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'timeout', 'connected': False}), 504
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500

    # 追加友好名称 + 落库
    db_path = _get_bt_db_path()
    if db_path and data.get('connected'):
        try:
            conn = sqlite3.connect(db_path)
            _ensure_bt_tables(conn)
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            dev_name = ''
            row = conn.execute("SELECT name FROM mt_ble_devices WHERE address=?", (address,)).fetchone()
            if row: dev_name = row[0] or ''
            for svc in data['services']:
                code = _uuid_short(svc['uuid'])
                friendly = BLE_UUID_NAMES.get(code, ('', ''))
                svc['friendly_name'] = friendly[0]
                svc['friendly_desc'] = friendly[1]
                for chr in svc['characteristics']:
                    ccode = _uuid_short(chr['uuid'])
                    cfriendly = BLE_UUID_NAMES.get(ccode, ('', ''))
                    chr['friendly_name'] = cfriendly[0]
                    chr['friendly_desc'] = cfriendly[1]
                    try:
                        conn.execute("""INSERT INTO mt_ble_gatt_cache
                            (device_addr, device_name, svc_uuid, svc_name, chr_uuid, chr_name,
                             chr_props, chr_value_hex, chr_readable, chr_writeable, chr_notifyable, explored_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(device_addr, svc_uuid, chr_uuid) DO UPDATE SET
                                chr_props=excluded.chr_props,
                                chr_value_hex=COALESCE(excluded.chr_value_hex, mt_ble_gatt_cache.chr_value_hex),
                                chr_readable=excluded.chr_readable,
                                chr_writeable=excluded.chr_writeable,
                                chr_notifyable=excluded.chr_notifyable,
                                explored_at=excluded.explored_at""",
                            (address, dev_name, svc['uuid'], friendly[0] or svc['name'] or '',
                             chr['uuid'], cfriendly[0] or chr['name'] or '',
                             json.dumps(chr['properties']), chr.get('value_hex'),
                             1 if chr['readable'] else 0,
                             1 if chr['writeable'] else 0,
                             1 if chr['notifyable'] else 0, now))
                    except: pass
            conn.commit()
            conn.close()
        except: pass

    data['device_address'] = address
    data['ts'] = int(time.time())
    return jsonify(data)


@dev_dashboard_api.route('/bt/gatt/read', methods=['GET', 'POST'])
def bt_gatt_read():
    """读取指定 Characteristic 的当前值"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    address = request.args.get('address') or body.get('address')
    chr_uuid = request.args.get('uuid') or body.get('uuid')
    if not address or not chr_uuid:
        return jsonify({'error': 'address_and_uuid_required'}), 400
    script = f"""
import asyncio, json, bleak
async def run():
    try:
        async with bleak.BleakClient('{address}', timeout=10) as c:
            val = await c.read_gatt_char('{chr_uuid}')
            print(json.dumps({{'hex': val.hex(), 'ascii': val.decode('utf-8', errors='replace'), 'bytes': list(val), 'length': len(val)}}))
    except Exception as e:
        print(json.dumps({{'error': str(e)[:300]}}))
asyncio.run(run())
"""
    try:
        r = subprocess.run(['python3', '-c', script], capture_output=True, text=True, timeout=15)
        output = r.stdout.strip().split('\n')[-1] if r.stdout.strip() else ''
        return jsonify(json.loads(output)) if output else jsonify({'error': r.stderr[:500]})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@dev_dashboard_api.route('/bt/gatt/write', methods=['POST'])
def bt_gatt_write():
    """向指定 Characteristic 写入数据"""
    if not _is_dev_ip():
        return jsonify({'error': 'forbidden'}), 403
    body = request.get_json(force=True) or {}
    address = body.get('address')
    chr_uuid = body.get('uuid')
    hex_data = body.get('hex')
    text_data = body.get('text')
    if not address or not chr_uuid or (not hex_data and not text_data):
        return jsonify({'error': 'address_uuid_and_payload_required'}), 400
    if hex_data:
        data_literal = f"bytes.fromhex('{hex_data}')"
    else:
        data_literal = f"{text_data.encode('utf-8')!r}"
    script = f"""
import asyncio, json, bleak
async def run():
    try:
        async with bleak.BleakClient('{address}', timeout=10) as c:
            data = {data_literal}
            await c.write_gatt_char('{chr_uuid}', data, response=True)
            print(json.dumps({{'ok': True, 'bytes_written': len(data), 'hex': data.hex()}}))
    except Exception as e:
        print(json.dumps({{'ok': False, 'error': str(e)[:300]}}))
asyncio.run(run())
"""
    try:
        r = subprocess.run(['python3', '-c', script], capture_output=True, text=True, timeout=15)
        output = r.stdout.strip().split('\n')[-1] if r.stdout.strip() else ''
        return jsonify(json.loads(output)) if output else jsonify({'error': r.stderr[:500]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)[:200]}), 500
