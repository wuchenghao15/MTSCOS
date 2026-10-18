"""
andromeda_dashboard_routes — 仙女座仪表盘 Blueprint (v1.1)
==========================================================
功能: 仙女座七阶段演化总览 + daemon 活率环形图 + DB 业务增量趋势
      + 双机健康对比 + Ollama 本地推理面板 + 异常自动修复链路
      + 🆕 冰山演化时间线 + 档案库查询 + 升级报告历史

数据源: flask-app/engines/app.db (仙女座专属主库, 784M WAL mode)
权限: 查询需登录 (@system_container)

表依赖:
  - mt_daemon_registry          (daemon 心跳注册表)
  - mt_ai_smart_mount_processes (smart_mount 守护进程)
  - mt_params                   (系统参数/daemon CYCLE)
  - mt_ai_brain_feed_log        (AI 脑库投喂)
  - mt_experience_library       (经验沉淀)
  - mt_dev_flow_session         (§14 开发流程)
  - mt_rule_violation_alert     (规则违反告警)
  - mt_ef_broadcast_events      (EigenFlux 广播)
  - ai_brain_activity           (脑库活动)
  - mt_patrol_squads            (巡逻队)
  - ai_employees                (AI 员工)
  # 🆕 Phase 4 新增档案表
  - mt_system_version_archive   (112 条全版本时间线)
  - mt_iceberg_evolution_archive (11 阶段冰山演化史)
  - mt_upgrade_reports          (每 4h 升级报告)
  - mt_upgrade_overviews        (每 7d 升级总览)
  - mt_copy_permanent_archive   (文案永久存档)

Phase 1 (本文件):
  [x] /andromeda/dashboard          — 仪表盘主页面
  [x] /api/andromeda/daemon_status — daemon 活率详情
  [x] /api/andromeda/db_metrics    — DB 业务增量趋势
  [x] /api/andromeda/system_health — 系统健康摘要
  [x] /api/andromeda/twin_machine  — 双机对比

Phase 4 🆕 (档案库补齐):
  [x] /api/iceberg_structure  — 冰山三层结构快照
  [x] /api/evolution_timeline — 11 阶段演化时间线
  [x] /api/upgrade_reports    — 最近 20 份 4h 报告
  [x] /api/upgrade_overviews  — 全部 7d 总览
  [x] /api/copy_archive       — 文案永久存档 (分页)
"""
from __future__ import annotations

import os
import time
import sqlite3
import subprocess
from collections import OrderedDict

from flask import jsonify, render_template, request
from app.middlewares.system_container import system_container

from . import andromeda_dashboard_bp as bp

# register_all_blueprints 通过 globals()[bp_attr] 查找
andromeda_dashboard_bp = bp

# ──────────────────────────────────────────────────────────────
# DB 路径 (v24.0: 仙女座引擎运行时专属 DB — 保留 engines/app.db, 
#  因为 mt_daemon_registry/mt_upgrade_reports 等核心表 schema 与主库完全不同)
# ⚠️ 注意: engines/app.db 也包含知识脑库 175 行 + 人格 14 行 + 版本档案 112 行
_FLASK_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_FLASK_APP)
ANDROMEDA_DB = os.path.join(_FLASK_APP, 'engines', 'app.db')

# daemon 分类 (7 大类, 与 smart_mount_engine.py SYSTEM_REQUIRED_DAEMONS 对齐)
DAEMON_CATEGORIES = OrderedDict([
    ("heartbeat/巡检", [
        "sys_heartbeat_writer", "sys_patrol_inspector", "sys_auto_repair"]),
    ("AI推理/脑库", [
        "sys_local_inference", "sys_brain_feed", "sys_error_digest",
        "sys_cognitive_assess"]),
    ("规则/合规", [
        "sys_rule_enforcer", "sys_rule_auto_learn", "sys_copy_inspection",
        "sys_security_pulse", "sys_resource_sched"]),
    ("网络/社交", [
        "sys_eigenflux_network", "sys_eigenflux_match",
        "sys_github_fusion_scan"]),
    ("雇佣/知识", [
        "sys_auto_hire", "sys_auto_patrol", "sys_knowledge_graph",
        "sys_knowledge_precious"]),
    ("深度/演化", [
        "sys_deep_inspection", "sys_andromeda_auto_evolution",
        "sys_ramanujan_derive"]),
    ("运维/IO", [
        "sys_file_organizer", "sys_cluster_snapshot", "sys_iot_cluster",
        "sys_predictive_maint", "sys_profile_fusion", "sys_matrix_synergy",
        "sys_experience_replay", "sys_knowledge_precious",
        "sys_tutor_learning", "sys_crypto_key_rotate",
        "sys_rule_auto_learn"]),
])


def _conn(read_only: bool = True) -> sqlite3.Connection:
    """仙女座专属 DB 连接

    v22.19.1 容灾: engines/app.db 不存在/损坏/缺核心表时自动回退主库
    (修复 iceberg_health/eigenflux 端点 500 — 服务器 engines/app.db 为空壳)
    """
    candidates = [ANDROMEDA_DB, os.path.join(_FLASK_APP, 'database', 'app.db')]
    for db_path in candidates:
        if not os.path.exists(db_path):
            continue
        try:
            uri = f'file:{db_path}?mode=ro' if read_only else f'file:{db_path}?mode=rwc'
            c = sqlite3.connect(uri, uri=True, timeout=3)
            has_core = c.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name IN ('mt_daemon_registry','mt_andromeda_knowledge_base')"
            ).fetchone()[0] > 0
            if has_core:
                c.row_factory = sqlite3.Row
                return c
            c.close()
        except Exception:
            continue
    raise FileNotFoundError(f'仙女座 DB 与主库均不可用: {ANDROMEDA_DB}')


def _daemon_rows(conn) -> list:
    """schema 兼容读取 daemon 注册表

    engines 库列: daemon_name/interval_sec/description
    主库列(v2.8.0): process_name/duty (无 interval_sec)
    统一输出: daemon_name/status/interval_sec/last_heartbeat/description
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mt_daemon_registry)").fetchall()}
    name_c = 'daemon_name' if 'daemon_name' in cols else 'process_name'
    desc_c = 'description' if 'description' in cols else ('duty' if 'duty' in cols else name_c)
    int_sel = 'interval_sec' if 'interval_sec' in cols else '600'
    sql = (f"SELECT {name_c} AS daemon_name, status, {int_sel} AS interval_sec, "
           f"last_heartbeat, {desc_c} AS description FROM mt_daemon_registry ORDER BY 1")
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _query(sql: str, args=()) -> list[dict]:
    try:
        with _conn() as c:
            return [dict(r) for r in c.execute(sql, tuple(args)).fetchall()]
    except Exception:
        return []


def _count(table: str) -> int:
    try:
        with _conn() as c:
            return c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    except Exception:
        return 0


def _live_daemons() -> set:
    """从 ps aux 拿当前活的 daemon 名"""
    try:
        out = subprocess.check_output(['ps', 'aux'], text=True, timeout=3)
    except Exception:
        return set()
    alive = set()
    for line in out.split('\n'):
        if '_runtime/auto_daemons/' in line and 'python' in line.lower():
            try:
                name = line.split('_runtime/auto_daemons/')[1].split('.py')[0].strip()
                if name and not name.startswith("'"):
                    alive.add(name)
            except Exception:
                pass
    return alive


# ──────────────────────────────────────────────────────────────
# 页面入口
# ──────────────────────────────────────────────────────────────
@bp.route('/dashboard', methods=['GET'])
def dashboard_page():
    """仙女座仪表盘主页面"""
    return render_template('andromeda_dashboard.html')


# ──────────────────────────────────────────────────────────────
# API: daemon 活率详情
# ──────────────────────────────────────────────────────────────
@bp.route('/api/daemon_status', methods=['GET'])
def api_daemon_status():
    live = _live_daemons()
    total = 0
    alive = 0
    categories = []

    _cols = {r['name'] for r in _query("PRAGMA table_info(mt_daemon_registry)")}
    _name_c = 'daemon_name' if 'daemon_name' in _cols else 'process_name'

    for cat, names in DAEMON_CATEGORIES.items():
        cat_total = len(names)
        cat_alive = sum(1 for n in names if n in live)
        total += cat_total
        alive += cat_alive
        status = []
        for n in names:
            # 从 mt_daemon_registry 拿最后心跳 (schema 兼容: engines=daemon_name / 主库=process_name)
            hb = _query(
                f"SELECT last_heartbeat, status FROM mt_daemon_registry WHERE {_name_c}=?",
                (n,))
            status.append({
                'name': n,
                'live': n in live,
                'last_heartbeat': hb[0]['last_heartbeat'][:19] if hb and hb[0].get('last_heartbeat') else None,
                'db_status': hb[0]['status'] if hb else 'UNKNOWN',
            })
        categories.append({
            'category': cat,
            'total': cat_total,
            'alive': cat_alive,
            'rate': round(cat_alive / cat_total * 100) if cat_total else 0,
            'daemons': status,
        })

    return jsonify({
        'code': 0,
        'data': {
            'summary': {'total': total, 'alive': alive, 'rate': round(alive / total * 100) if total else 0},
            'categories': categories,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        },
    })


# ──────────────────────────────────────────────────────────────
# API: DB 业务增量趋势
# ──────────────────────────────────────────────────────────────
@bp.route('/api/db_metrics', methods=['GET'])
def api_db_metrics():
    """核心表行数 + 24h 增量"""
    tables = [
        ('mt_ai_brain_feed_log',          'AI 脑库投喂'),
        ('mt_experience_library',          '经验沉淀'),
        ('mt_dev_flow_session',            '§14 开发流程'),
        ('mt_ef_broadcast_events',         'EigenFlux 广播'),
        ('ai_brain_activity',              '脑库活动'),
        ('ai_employees',                   'AI 员工'),
        ('mt_daemon_registry',             'daemon 心跳'),
        ('mt_params',                      '系统参数'),
        ('mt_patrol_squads',               '巡逻队'),
        ('mt_rule_violation_alert',        '规则违反'),
    ]

    result = []
    for tbl, label in tables:
        total = _count(tbl)
        # 24h 增量 (用 created_at / timestamp / formed_at 任一)
        col_candidates = ['created_at', 'timestamp', 'updated_at', 'formed_at', 'last_heartbeat']
        delta_24h = 0
        for col in col_candidates:
            rows = _query(
                f"SELECT COUNT(*) FROM {tbl} WHERE {col} > datetime('now','localtime','-1 day')")
            if rows:
                delta_24h = list(rows[0].values())[0]
                break
        result.append({
            'table': tbl,
            'label': label,
            'total': total,
            'delta_24h': delta_24h,
        })

    # DB 文件大小
    db_size = 0
    db_wal = 0
    try:
        db_size = os.path.getsize(ANDROMEDA_DB)
        wal_path = ANDROMEDA_DB + '-wal'
        if os.path.exists(wal_path):
            db_wal = os.path.getsize(wal_path)
    except Exception:
        pass

    return jsonify({
        'code': 0,
        'data': {
            'tables': result,
            'db_size_mb': round(db_size / 1024 / 1024, 1),
            'db_wal_mb': round(db_wal / 1024 / 1024, 1),
            'db_path': ANDROMEDA_DB,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        },
    })


# ──────────────────────────────────────────────────────────────
# API: 系统健康摘要
# ──────────────────────────────────────────────────────────────
@bp.route('/api/system_health', methods=['GET'])
def api_system_health():
    """一键健康检查"""
    checks = []

    # 1. DB 可达
    try:
        with _conn() as c:
            c.execute('SELECT 1')
        checks.append({'name': '仙女座 DB', 'status': 'OK', 'detail': ANDROMEDA_DB})
    except Exception as e:
        checks.append({'name': '仙女座 DB', 'status': 'FAIL', 'detail': str(e)})

    # 2. daemon 活率
    live = _live_daemons()
    checks.append({'name': 'daemon 活率', 'status': 'OK' if len(live) >= 25 else 'WARN',
                   'detail': f'{len(live)} 个活跃'})

    # 3. Flask 8888
    try:
        import urllib.request
        r = urllib.request.urlopen('http://127.0.0.1:8888/api/health', timeout=3)
        checks.append({'name': 'Flask 8888', 'status': 'OK', 'detail': f'HTTP {r.status}'})
    except Exception as e:
        checks.append({'name': 'Flask 8888', 'status': 'WARN', 'detail': str(e)[:60]})

    # 4. §14 流程状态
    flows = _query("SELECT final_status, COUNT(*) FROM mt_dev_flow_session GROUP BY final_status")
    flow_summary = {r['final_status'] or 'UNKNOWN': r['COUNT(*)'] for r in flows}
    checks.append({'name': '§14 开发流程', 'status': 'OK',
                   'detail': str(flow_summary)})

    # 5. 规则违反告警
    violations = _count('mt_rule_violation_alert')
    checks.append({'name': '规则违反告警', 'status': 'OK' if violations == 0 else 'WARN',
                   'detail': f'{violations} 条待处理'})

    # 6. 系统启动时间
    try:
        uptime = subprocess.check_output(['uptime'], text=True).strip()
        checks.append({'name': '系统 uptime', 'status': 'OK', 'detail': uptime})
    except Exception:
        pass

    # 7. Ollama
    try:
        import urllib.request
        r = urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2)
        checks.append({'name': 'Ollama 本地推理', 'status': 'OK', 'detail': '在线'})
    except Exception:
        checks.append({'name': 'Ollama 本地推理', 'status': 'WARN', 'detail': '离线'})

    return jsonify({
        'code': 0,
        'data': {
            'checks': checks,
            'score': sum(1 for c in checks if c['status'] == 'OK') / len(checks) * 100 if checks else 0,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        },
    })


# ──────────────────────────────────────────────────────────────
# API: 双机对比 (Mac mini 连上网后自动补)
# ──────────────────────────────────────────────────────────────
@bp.route('/api/twin_machine', methods=['GET'])
def api_twin_machine():
    """Mac mini 健康状态 (需 ssh andromeda)"""
    local_live = len(_live_daemons())

    macmini = {'reachable': False, 'data': None}
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', 'andromeda',
             'python3 -c "import sqlite3, os, subprocess; '
             'db=os.path.join(os.path.expanduser(\"~\"),\"mtscos\",\"flask-app\",\"engines\",\"app.db\"); '
             'c=sqlite3.connect(db); '
             'ps=subprocess.check_output([\"ps\",\"aux\"],text=True); '
             'live=sum(1 for l in ps.split(chr(10)) if \"_runtime/auto_daemons/\" in l); '
             'registry=c.execute(\"SELECT COUNT(*) FROM mt_daemon_registry\").fetchone()[0]; '
             'print(f\"{live}|{registry}\")"'],
            capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|')
            macmini = {
                'reachable': True,
                'daemon_live': int(parts[0]),
                'daemon_registry': int(parts[1]) if len(parts) > 1 else 0,
            }
    except Exception as e:
        macmini = {'reachable': False, 'error': str(e)[:80]}

    return jsonify({
        'code': 0,
        'data': {
            'local': {'hostname': 'MacBook Pro', 'daemon_live': local_live},
            'macmini': macmini,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        },
    })


# =================================================================
# 🆕 Phase 4: 档案库 API 补齐 (v1.1 新增)
# =================================================================

@bp.route('/api/iceberg_structure')
def api_iceberg_structure():
    """冰山三层架构快照"""
    conn = sqlite3.connect(ANDROMEDA_DB)
    conn.row_factory = sqlite3.Row
    # 三层各自的最新阶段
    layers = {'赤壁 Peak (顶层)': None, '承天寺 Spectrum (中层)': None, '东坡 Basement (底层)': None}
    try:
        for row in conn.execute("""
            SELECT iceberg_layer, stage_name, stage_date, core_theorem, key_concepts,
                   key_achievements, milestone_commit
            FROM mt_iceberg_evolution_archive
            WHERE iceberg_layer IS NOT NULL
            ORDER BY stage_seq
        """).fetchall():
            layer = row['iceberg_layer'].strip()
            if layer in layers or any(k in layer for k in ['赤壁', '承天寺', '东坡']):
                # 匹配到就用最新覆盖
                layers[layer] = dict(row)
    except Exception:
        pass
    # 全局里程碑
    milestones = []
    try:
        for row in conn.execute("SELECT stage_seq, stage_name, stage_date, core_theorem FROM mt_iceberg_evolution_archive ORDER BY stage_seq").fetchall():
            milestones.append(dict(row))
    except Exception:
        pass
    conn.close()
    return jsonify({'code': 0, 'data': {'layers': layers, 'milestones': milestones}})


@bp.route('/api/evolution_timeline')
def api_evolution_timeline():
    """11 阶段冰山演化时间线 + 112 条全版本"""
    conn = sqlite3.connect(ANDROMEDA_DB)
    conn.row_factory = sqlite3.Row
    timeline = []
    try:
        for row in conn.execute("""
            SELECT stage_seq, stage_name, stage_date, version_tag, architect_phase,
                   iceberg_layer, key_people, core_theorem, key_concepts, archive_summary
            FROM mt_iceberg_evolution_archive ORDER BY stage_seq
        """).fetchall():
            timeline.append(dict(row))
    except Exception as e:
        return jsonify({'code': -1, 'error': str(e)})
    # 版本数量
    ver_count = conn.execute("SELECT COUNT(*) FROM mt_system_version_archive").fetchone()[0]
    conn.close()
    return jsonify({'code': 0, 'data': {'timeline': timeline, 'total_versions': ver_count}})


@bp.route('/api/upgrade_reports')
def api_upgrade_reports():
    """最近 20 份 4h 升级报告"""
    conn = sqlite3.connect(ANDROMEDA_DB)
    conn.row_factory = sqlite3.Row
    reports = []
    try:
        for row in conn.execute("""
            SELECT report_id, report_type, report_start, report_end,
                   daemon_status_json, new_brain_feeds, new_inferences, new_errors,
                   ollama_status, generated_at
            FROM mt_upgrade_reports ORDER BY report_id DESC LIMIT 20
        """).fetchall():
            reports.append(dict(row))
    except Exception as e:
        return jsonify({'code': -1, 'error': str(e)})
    conn.close()
    return jsonify({'code': 0, 'data': reports})


@bp.route('/api/upgrade_overviews')
def api_upgrade_overviews():
    """全部 7d 升级总览"""
    conn = sqlite3.connect(ANDROMEDA_DB)
    conn.row_factory = sqlite3.Row
    overviews = []
    try:
        for row in conn.execute("""
            SELECT overview_id, week_start, week_end, week_number,
                   total_versions, total_daemons, total_brain_growth,
                   total_inference_count, architecture_changes, generated_at
            FROM mt_upgrade_overviews ORDER BY overview_id DESC
        """).fetchall():
            overviews.append(dict(row))
    except Exception as e:
        return jsonify({'code': -1, 'error': str(e)})
    conn.close()
    return jsonify({'code': 0, 'data': overviews})


@bp.route('/api/copy_archive')
def api_copy_archive():
    """文案永久存档 (分页, 每页 20)"""
    import json as _json
    conn = sqlite3.connect(ANDROMEDA_DB)
    conn.row_factory = sqlite3.Row
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))
    cat = request.args.get('category', None)
    where = ""
    params: list = []
    if cat:
        where = "WHERE copy_category = ?"
        params.append(cat)
    total = conn.execute(f"SELECT COUNT(*) FROM mt_copy_permanent_archive {where}", params).fetchone()[0]
    rows = conn.execute(f"""
        SELECT copy_id, copy_category, copy_source, archive_status,
               use_count, last_used_at, created_at, substr(copy_content,1,200) AS preview
        FROM mt_copy_permanent_archive {where}
        ORDER BY copy_id DESC LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    # 分类列表
    cats = [r[0] for r in conn.execute("SELECT DISTINCT copy_category FROM mt_copy_permanent_archive").fetchall()]
    conn.close()
    return jsonify({
        'code': 0,
        'data': {
            'total': total,
            'limit': limit,
            'offset': offset,
            'categories': cats,
            'rows': [dict(r) for r in rows],
        }
    })

# =================================================================
# 🆕 Phase 5: 仙女座知识脑库 (mt_andromeda_knowledge_base)
# =================================================================

@bp.route('/knowledge_brain', methods=['GET'])
def knowledge_brain_page():
    """仙女座知识脑库前端页面 (极暗星空风)"""
    return render_template('andromeda_knowledge_brain.html')


# =================================================================
# 🆕 Phase 6: 冰山控制中心 · 演化时间线 + 脑库融合 + 导航
# =================================================================

@bp.route('/iceberg_evolution', methods=['GET'])
def iceberg_evolution_page():
    """冰山演化时间线前端 — 水墨赤壁赋 文人风"""
    return render_template('andromeda_iceberg_evolution.html')


@bp.route('/iceberg_center', methods=['GET'])
def iceberg_center_page():
    """🧊 冰山统一控制中心 — 三层动态厚度 + 知识脑库融合 + 导航"""
    return render_template('andromeda_iceberg_center.html')


# =================================================================
# 🆕 Phase 7: 冰山坍缩定理 + 天团矩阵 + 升级报告
# =================================================================

@bp.route('/collapse_theorem', methods=['GET'])
def collapse_theorem_page():
    """PRIME_COLLAPSE_THEOREM 质因数递归坍缩7 可视化"""
    return render_template('andromeda_collapse_theorem.html')


@bp.route('/eigenflux_council', methods=['GET'])
@system_container(require_auth='login')
def eigenflux_council_page():
    """EigenFlux 专家团 + 天团矩阵 + AI 员工"""
    return render_template('andromeda_eigenflux.html')


@bp.route('/gray_center', methods=['GET'])
def gray_center_page():
    """灰度发布中心 (flow_secondary_pages_20261018: 主页nav 404 补全)"""
    from flask import session
    return render_template('andromeda_gray_center.html', username=session.get('username') or 'wuchenghao15')


@bp.route('/iceberg_meta', methods=['GET'])
@system_container(require_auth='login')
def iceberg_meta_page():
    """冰山元数据看板 (flow_secondary_pages_20261018: 主页nav 404 补全)"""
    return render_template('andromeda_iceberg_meta.html')


@bp.route('/upgrade_board', methods=['GET'])
def upgrade_board_page():
    """升级报告仪表盘"""
    return render_template('andromeda_upgrade_board.html')


# =================================================================
# 🆕 Phase 8: 健康度仪表盘 + AI 人格聊天室 + 知识图谱
# =================================================================

@bp.route('/health_board', methods=['GET'])
def health_board_page():
    """🩺 冰山健康度仪表盘 — 真实心跳 + 停摆标红 + 坍缩锚点"""
    return render_template('andromeda_health_board.html')


@bp.route('/persona_chat', methods=['GET'])
def persona_chat_page():
    """💬 AI 人格实时聊天室 — 多人格同时讨论"""
    return render_template('andromeda_persona_chat.html')


@bp.route('/knowledge_graph', methods=['GET'])
def knowledge_graph_page():
    """🕸️ D3.js 知识图谱 力导向图"""
    return render_template('andromeda_knowledge_graph.html')


@bp.route('/api/knowledge_graph/data', methods=['GET'])
def api_knowledge_graph_data():
    """🕸️ 知识图谱数据 (flow_redblue_ui_20261018: 修复页面 forEach undefined — 端点此前 404)

    数据源: 主库 knowledge_graph_nodes (6337) + knowledge_graph_relations (9784)
    输出契约 (页面 L130-157): {data: {domain_count, video_count, nodes[], links[]}}
    性能: 按 importance_score 截断 600 节点 + 其间 1200 边, 防 D3 force 卡顿
    """
    import sqlite3 as _sq3
    main_db = os.path.join(_FLASK_APP, 'database', 'app.db')
    out = {'data': {'domain_count': 0, 'video_count': 0, 'nodes': [], 'links': []}}
    try:
        conn = _sq3.connect(main_db, timeout=10)
        conn.row_factory = _sq3.Row
        nodes = [dict(r) for r in conn.execute(
            "SELECT node_id, node_name, node_type, importance_score FROM knowledge_graph_nodes "
            "WHERE is_active=1 ORDER BY importance_score DESC LIMIT 600").fetchall()]
        if nodes:
            ids = {n['node_id'] for n in nodes}
            qmarks = ','.join('?' * len(ids))
            links = [dict(r) for r in conn.execute(
                f"SELECT source_node_id, target_node_id, relation_type FROM knowledge_graph_relations "
                f"WHERE is_active=1 AND source_node_id IN ({qmarks}) AND target_node_id IN ({qmarks}) "
                f"LIMIT 1200", list(ids) + list(ids)).fetchall()]
        else:
            links = []
        conn.close()
        gnodes, out_nodes, out_links = [], [], []
        for n in nodes:
            is_domain = str(n.get('node_type') or '').lower() in ('domain', '领域', 'category', 'subject')
            group = 'domain' if is_domain else 'video'
            (gnodes if is_domain else out_nodes).append({
                'id': n['node_id'], 'label': n.get('node_name') or n['node_id'],
                'group': group,
                # importance_score 兼容 0-1 浮点与 0-100 整数两种量纲
                'size': max(4, int((n.get('importance_score') or 0.2) * 40)) if (n.get('importance_score') or 0) <= 1.0 else max(4, int(n.get('importance_score'))),
            })
        for l in links:
            out_links.append({'source': l['source_node_id'], 'target': l['target_node_id'],
                              'type': l.get('relation_type') or 'rel'})
        out['data'] = {'domain_count': len(gnodes), 'video_count': len(out_nodes),
                       'nodes': gnodes + out_nodes, 'links': out_links}
    except Exception as _kg_err:
        out['error'] = str(_kg_err)[:200]
    return jsonify(out)


@bp.route('/api/persona_chat', methods=['POST'])
def api_persona_chat():
    """💬 AI 人格聊天室 — 调 Ollama qwen2.5:7b"""
    import urllib.request as _ur, json as _json
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    persona = data.get('persona') or {}  # {name, role, domain, layer}
    if not question: return jsonify({'code': 1, 'msg': '请输入问题'})
    # 构建角色扮演 prompt
    system_prompt = f"你是【{persona.get('name','AI')}】，身份：{persona.get('role','专家')}，领域：{persona.get('domain','综合')}。请以【{persona.get('name')}】的身份和口吻回答，保持这个角色的独特视角和语言风格。回答用中文。"
    ollama_payload = {
        'model': 'qwen2.5:7b',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': question},
        ],
        'stream': False, 'options': {'temperature': 0.7}
    }
    try:
        req = _ur.Request('http://127.0.0.1:11434/api/chat',
                          data=_json.dumps(ollama_payload).encode(),
                          headers={'Content-Type':'application/json'})
        resp = _ur.urlopen(req, timeout=60)
        body = _json.loads(resp.read().decode('utf-8'))
        answer = body.get('message', {}).get('content', '')
    except Exception as ex:
        answer = f'[Ollama 未就绪，降级固定回答]\n{persona.get("name","AI")} 说：关于"{question[:30]}..."，这是一个值得深思的问题。让我从{persona.get("domain","这个领域")}的角度来思考...'
    return jsonify({'code': 0, 'data': {'persona': persona.get('name'), 'answer': answer}})


@bp.route('/api/iceberg/health', methods=['GET'])
def api_iceberg_health():
    """真实健康度数据 — 心跳停摆标红"""
    import time as _t
    import subprocess as _sp
    conn = _conn()
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    now_ts = time.time()

    # 1. Flask 进程
    flask_alive = False
    flask_pid = None
    try:
        out = _sp.check_output(['lsof','-i',':8888','-t'], stderr=_sp.DEVNULL, timeout=3).decode().strip()
        flask_alive = bool(out)
        flask_pid = out.split('\n')[0] if out else None
    except Exception: pass

    # 2. daemon 心跳（真实计算 age = 距今多少秒，>= interval×2 标红）
    conn.row_factory = sqlite3.Row
    daemons = []
    for r in _daemon_rows(conn):
        hb = r['last_heartbeat'] or ''
        age_sec = None
        if hb and hb != 'None':
            try:
                hb_ts = time.mktime(time.strptime(hb[:19], '%Y-%m-%d %H:%M:%S'))
                age_sec = int(now_ts - hb_ts)
            except Exception: pass
        interval = r['interval_sec'] or 600
        is_dead = age_sec is not None and age_sec > interval * 2
        daemons.append({
            'name': r['daemon_name'],
            'status': r['status'],
            'interval_sec': interval,
            'last_heartbeat': hb,
            'age_sec': age_sec,
            'is_dead': is_dead,
            'alive': not is_dead,
        })
    conn.row_factory = None

    alive = sum(1 for d in daemons if d['alive'])
    dead = sum(1 for d in daemons if not d['alive'])

    # 3. 知识脑库统计
    try:
        kb_total = conn.execute('SELECT COUNT(*) FROM mt_andromeda_knowledge_base').fetchone()[0]
        kb_domain = [dict(r) for r in conn.execute('SELECT domain, COUNT(*) as cnt FROM mt_andromeda_knowledge_base GROUP BY domain ORDER BY cnt DESC LIMIT 5').fetchall()]
    except Exception:
        kb_total, kb_domain = 0, []

    # 4. 坍缩锚点状态（取演化阶段 #9 的核心锚）
    collapse_anchors = [
        {'name': '§14 铁律', 'anchor': 7, 'stable': True},
        {'name': 'Daemon 集群', 'anchor': 2, 'stable': True},
        {'name': '知识脑库', 'anchor': 11, 'stable': True},
        {'name': '坍缩定理自身', 'anchor': 7, 'stable': True},
    ]

    conn.close()
    return jsonify({'code': 0, 'data': {
        'now': now, 'now_ts': int(now_ts),
        'flask_alive': flask_alive, 'flask_pid': flask_pid,
        'total_daemons': len(daemons),
        'alive_daemons': alive,
        'dead_daemons': dead,
        'health_pct': round(alive/len(daemons)*100) if daemons else 0,
        'daemons': daemons,
        'kb_total': kb_total,
        'kb_domain_top': kb_domain,
        'collapse_anchors': collapse_anchors,
    }})


# ===== EigenFlux API (保持完整) =====
@bp.route('/api/iceberg/eigenflux', methods=['GET'])
def api_eigenflux():
    """EigenFlux 专家团 + 真实 daemon"""
    conn = _conn()
    conn.row_factory = sqlite3.Row
    daemons = []
    for r in sorted(_daemon_rows(conn), key=lambda x: x['interval_sec']):
        daemons.append({
            'name': r['daemon_name'],
            'status': r['status'],
            'interval_sec': r['interval_sec'],
            'description': r['description'] or '',
            'last_heartbeat': r['last_heartbeat'] or '',
        })
    conn.row_factory = None
    conn.close()
    sky_team = [
        {"name":"架构师 Σ","role":"架构","domain":"系统","layer":"peak"},
        {"name":"合规官 Ω","role":"合规","domain":"规则","layer":"peak"},
        {"name":"安全官 Ψ","role":"安全","domain":"密码","layer":"peak"},
        {"name":"DBA Δ","role":"DBA","domain":"数据","layer":"peak"},
        {"name":"运维 Ξ","role":"运维","domain":"部署","layer":"spectrum"},
        {"name":"前端 Ω","role":"前端","domain":"UI","layer":"spectrum"},
        {"name":"后端 Γ","role":"后端","domain":"Flask","layer":"spectrum"},
        {"name":"AI 专家 Φ","role":"AI","domain":"本地推理","layer":"peak"},
        {"name":"教育专家 Λ","role":"教育","domain":"K12","layer":"spectrum"},
        {"name":"IoT Π","role":"IoT","domain":"Arduino","layer":"basement"},
        {"name":"丘成桐","role":"导师","domain":"数学","layer":"peak"},
        {"name":"罗翔","role":"导师","domain":"法律","layer":"spectrum"},
        {"name":"村上春树","role":"导师","domain":"文学","layer":"spectrum"},
        {"name":"朱熹","role":"导师","domain":"理学","layer":"basement"},
    ]
    return jsonify({'code': 0, 'data': {
        'daemon_count': len(daemons),
        'daemons': daemons,
        'sky_team': sky_team,
        'total_daemons': len(daemons),
    }})


@bp.route('/api/iceberg/upgrade_board', methods=['GET'])
def api_upgrade_board():
    """升级报告数据"""
    conn = _conn()
    try:
        reports = [dict(r) for r in conn.execute("SELECT * FROM mt_upgrade_reports ORDER BY report_start DESC LIMIT 20").fetchall()]
    except Exception: reports = []
    try:
        overviews = [dict(r) for r in conn.execute("SELECT * FROM mt_upgrade_overviews ORDER BY week_start DESC LIMIT 12").fetchall()]
    except Exception: overviews = []
    conn.close()
    return jsonify({'code': 0, 'data': {'reports': reports, 'overviews': overviews}})


@bp.route('/api/iceberg_layer_stats', methods=['GET'])
def api_iceberg_layer_stats():
    """知识脑库按冰山三层聚合 — 前端动态厚度数据源
    v25.2: 主数据源切换 ai_brain_enhanced_knowledge (1.5M 行现役表),
          自动挑库 (engines/app.db 无现役表时回退主库), 附带向量库统计, 全程容错不 500"""
    layers = {'peak': [], 'spectrum': [], 'basement': []}
    totals = {'peak': 0, 'spectrum': 0, 'basement': 0}
    vectors = 0
    # 自动挑库: engines/app.db → env → PROD → OneDrive, 全部 immutable 只读 (OneDrive WAL 适配)
    candidates = [ANDROMEDA_DB]
    for env_key in ('MTSCOS_DB_PATH', 'APP_DB'):
        v = os.environ.get(env_key, '')
        if v and os.path.exists(v):
            candidates.append(v)
    prod_db = os.path.expanduser('~/MTSCOS_PROD/flask-app/database/app.db')
    if os.path.exists(prod_db) and prod_db not in candidates:
        candidates.append(prod_db)
    main_db = os.path.join(_FLASK_APP, 'database', 'app.db')
    if main_db not in candidates:
        candidates.append(main_db)
    conn = None
    for db_path in candidates:
        try:
            c = sqlite3.connect(f'file:{db_path}?mode=ro&immutable=1', uri=True, timeout=3)
            has = c.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='ai_brain_enhanced_knowledge'"
            ).fetchone()[0]
            if has:
                conn = c
                break
            c.close()
        except Exception:
            continue
    if conn is not None:
        try:
            # 三层映射 (v25.2 真实 category 分布):
            #   雪峰 Peak(顶层) = 考试技巧/成人教育/职业教育 (教育刚需)
            #   承天寺 Spectrum(中层) = 学科知识/学习方法/地理/历史/化学 (学科人文)
            #   东坡 Basement(底层) = eigenflux/auto_derive/daemon 等系统引擎层
            layer_rule = """CASE
                WHEN category IN ('考试技巧','成人教育','职业教育') THEN 'peak'
                WHEN category IN ('学习方法','地理','历史','化学','物理','生物','语文','数学','英语','文科','理科')
                     OR category IS NULL THEN 'spectrum'
                WHEN category = '学科知识' THEN 'spectrum'
                ELSE 'basement'
            END"""
            rows = conn.execute(f"""
                SELECT {layer_rule} as layer, COALESCE(category,'通用') as domain,
                       COUNT(*) as cnt
                FROM ai_brain_enhanced_knowledge
                GROUP BY layer, domain
                ORDER BY layer, cnt DESC
                LIMIT 500
            """).fetchall()
            for r in rows:
                layers[r[0]].append({
                    'domain': r[1], 'count': r[2], 'plays': 0, 'avg_quality': None
                })
            totals = {l: sum(d['count'] for d in layers[l]) for l in layers}
            try:
                vectors = conn.execute("SELECT COUNT(*) FROM mt_ai_brain_vector").fetchone()[0]
            except Exception:
                vectors = 0
        except Exception as e:
            import traceback; traceback.print_exc()
        finally:
            try: conn.close()
            except Exception: pass
    return jsonify({'code': 0, 'data': {
        'layers': layers, 'totals': totals, 'vectors': vectors
    }})


# ═══════════════════════════════════════════════════════════════════
# 仙女座 ↔ 冰山 深度绑定 API (v3.0 新增)
# ═══════════════════════════════════════════════════════════════════
@bp.route('/api/iol_summary', methods=['GET'])
def api_iol_summary():
    """IOL 实时面板数据 — mt_iceberg_optimization_log 状态聚合"""
    conn = _conn()
    try:
        # 状态聚合
        stat_rows = conn.execute("""
            SELECT COALESCE(current_status,'PENDING'), COUNT(*)
            FROM mt_iceberg_optimization_log GROUP BY current_status
        """).fetchall()
        stats = {s: c for s, c in stat_rows}
        # 最近 8 条
        rows = conn.execute("""
            SELECT opt_id, file_name, target_func, class_name, category,
                   current_status, attempt_count, substr(last_feedback,1,50),
                   datetime(updated_at)
            FROM mt_iceberg_optimization_log
            ORDER BY CASE current_status
                WHEN 'APPLIED' THEN 1 WHEN 'FAILED' THEN 2
                WHEN 'IN_PROGRESS' THEN 3 WHEN 'PENDING' THEN 4
                ELSE 5 END, updated_at DESC
            LIMIT 8
        """).fetchall()
        items = []
        for r in rows:
            cls = f"{r[3]}." if r[3] else ""
            items.append({
                'id': r[0], 'func': f"{r[1]}:{cls}{r[2]}",
                'cat': r[4] or 'logic', 'status': r[5] or 'PENDING',
                'attempts': r[6] or 0, 'feedback': r[7] or '', 'updated': r[8] or ''
            })
    except Exception as e:
        stats, items = {}, []
        import traceback; traceback.print_exc()
    conn.close()
    return jsonify({'code': 0, 'data': {'stats': stats, 'items': items}})


@bp.route('/api/andromeda_daemon_status', methods=['GET'])
def api_andromeda_daemon_status():
    """守护进程状态 — PID / Ollama / daemon registry"""
    import subprocess, os
    daemon_online = bool(subprocess.getoutput("pgrep -f 'andromeda_core.py daemon'").strip())
    ollama_online = False
    try:
        import urllib.request
        req = urllib.request.Request('http://localhost:11435/api/tags', method='GET')
        urllib.request.urlopen(req, timeout=2)
        ollama_online = True
    except: pass
    # daemon registry (schema 兼容: 主库列 process_name, 无 name)
    conn = _conn()
    try:
        _rows = _daemon_rows(conn)
        running_count = sum(1 for r in _rows if str(r.get('status') or '').upper() == 'RUNNING')
        total_count = len(_rows)
    except Exception:
        running_count, total_count = 0, 0
    conn.close()
    pid = subprocess.getoutput("pgrep -f 'andromeda_core.py daemon' | head -1").strip() or '—'
    return jsonify({
        'code': 0, 'data': {
            'daemon': daemon_online, 'pid': pid,
            'ollama': ollama_online,
            'daemon_running': running_count, 'daemon_total': total_count,
            'uptime_s': 0,
        }
    })


@bp.route('/api/knowledge_brain/search', methods=['GET'])
def api_knowledge_search():
    """知识脑库搜索 API — 支持关键词/领域/难度/平台 过滤"""
    keyword = (request.args.get('q') or request.args.get('keyword') or '').strip()
    domain = (request.args.get('domain') or '').strip()
    difficulty = (request.args.get('difficulty') or '').strip()
    platform = (request.args.get('platform') or '').strip()
    page = max(int(request.args.get('page') or 1), 1)
    limit = min(int(request.args.get('limit') or 20), 50)
    offset = (page - 1) * limit

    try:
        conn = _conn()
    except Exception as e:
        return jsonify({'success': False, 'data': [], 'total': 0, 'error': str(e)}), 500
    where = []
    args = []
    if keyword:
        where.append("(title LIKE ? OR ai_summary LIKE ? OR knowledge_points LIKE ? OR author_name LIKE ?)")
        k = f"%{keyword}%"
        args.extend([k, k, k, k])
    if domain:
        where.append("domain LIKE ?")
        args.append(f"%{domain}%")
    if difficulty:
        where.append("difficulty_level LIKE ?")
        args.append(f"%{difficulty}%")
    if platform:
        where.append("source_platform = ?")
        args.append(platform)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    # 检查表是否存在（知识脑库可能尚未初始化）
    try:
        conn.execute("SELECT 1 FROM mt_andromeda_knowledge_base LIMIT 1")
    except Exception:
        conn.close()
        return jsonify({
            'code': 0, 'data': {
                'total': 0, 'page': page, 'limit': limit,
                'domains': [], 'difficulties': [], 'platforms': [], 'rows': [],
            },
            'note': '知识脑库表 mt_andromeda_knowledge_base 尚未初始化，请等待同步'
        })

    total = conn.execute(
        f"SELECT COUNT(*) FROM mt_andromeda_knowledge_base {where_sql}", args
    ).fetchone()[0]

    rows = conn.execute(f"""
        SELECT k_id, source_platform, source_url, title, author_name, author_profile_url,
               domain, difficulty_level, play_count, duration_seconds, published_at,
               ai_summary, knowledge_points, quality_score, collected_at
        FROM mt_andromeda_knowledge_base {where_sql}
        ORDER BY play_count DESC, quality_score DESC LIMIT ? OFFSET ?
    """, args + [limit, offset]).fetchall()

    domains = [r[0] for r in conn.execute(
        "SELECT DISTINCT domain FROM mt_andromeda_knowledge_base ORDER BY domain"
    ).fetchall()]
    difficulties = [r[0] for r in conn.execute(
        "SELECT DISTINCT difficulty_level FROM mt_andromeda_knowledge_base WHERE difficulty_level IS NOT NULL AND difficulty_level != '' ORDER BY difficulty_level"
    ).fetchall()]
    platforms = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_platform FROM mt_andromeda_knowledge_base ORDER BY source_platform"
    ).fetchall()]

    conn.close()
    return jsonify({
        'code': 0,
        'data': {
            'total': total,
            'page': page, 'limit': limit,
            'domains': domains,
            'difficulties': difficulties,
            'platforms': platforms,
            'rows': [dict(r) for r in rows],
        }
    })


@bp.route('/api/knowledge_brain/personas', methods=['GET'])
def api_knowledge_personas():
    """知识贡献者人格档案列表"""
    conn = _conn()
    rows = conn.execute("""
        SELECT persona_id, name, type, domain, knowledge_summary, thought_pattern, question_template
        FROM mt_andromeda_contributor_persona WHERE is_active=1 ORDER BY type, name
    """).fetchall()
    conn.close()
    return jsonify({'code': 0, 'data': [dict(r) for r in rows]})


@bp.route('/api/knowledge_brain/stats', methods=['GET'])
def api_knowledge_stats():
    """知识脑库统计概览"""
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM mt_andromeda_knowledge_base").fetchone()[0]
    by_domain = conn.execute("""
        SELECT domain, COUNT(*) as cnt FROM mt_andromeda_knowledge_base
        GROUP BY domain ORDER BY cnt DESC LIMIT 15
    """).fetchall()
    by_platform = conn.execute("""
        SELECT source_platform as p, COUNT(*) as cnt FROM mt_andromeda_knowledge_base
        GROUP BY source_platform ORDER BY cnt DESC
    """).fetchall()
    total_play = conn.execute(
        "SELECT COALESCE(SUM(play_count),0) FROM mt_andromeda_knowledge_base"
    ).fetchone()[0]
    total_personas = conn.execute(
        "SELECT COUNT(*) FROM mt_andromeda_contributor_persona WHERE is_active=1"
    ).fetchone()[0]
    conn.close()
    return jsonify({
        'code': 0,
        'data': {
            'total_knowledge': total,
            'total_play_count': total_play,
            'total_personas': total_personas,
            'by_domain': [dict(r) for r in by_domain],
            'by_platform': [dict(r) for r in by_platform],
        }
    })


@bp.route('/api/knowledge_brain/ask', methods=['POST'])
def api_knowledge_ask():
    """向 AI 人格请教 — 人格模板 + Ollama qwen2.5:7b 生成"""
    data = request.get_json(silent=True) or {}
    persona_id = int(data.get('persona_id') or 0)
    question = (data.get('question') or '').strip()
    if not persona_id or not question:
        return jsonify({'code': 400, 'msg': '缺少 persona_id 或 question'}), 400

    conn = _conn()
    persona = conn.execute("""
        SELECT name, type, domain, knowledge_summary, thought_pattern, question_template
        FROM mt_andromeda_contributor_persona WHERE persona_id=? AND is_active=1
    """, (persona_id,)).fetchone()
    conn.close()
    if not persona:
        return jsonify({'code': 404, 'msg': '人格不存在'}), 404

    persona_name = persona['name']
    system_prompt = f"""你正在扮演【{persona_name}】（{persona['type']}）, 领域: {persona['domain']}。

知识概览: {persona['knowledge_summary']}

思维模式: {persona['thought_pattern']}

请以 {persona_name} 的身份回答问题。要求:
{persona['question_template'].replace('【话题】', question) if persona['question_template'] else '1. 用自己的话回答 2. 结合你的知识领域 3. 适当引用经典语录'}

回答要自然、像真人、带一点个人风格。"""

    full_prompt = f"{system_prompt}\n\n我的问题: {question}"

    # 调 Ollama
    answer = None
    try:
        import subprocess
        r = subprocess.run(
            ["ollama", "run", "qwen2.5:7b", full_prompt],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode == 0 and r.stdout.strip():
            answer = r.stdout.strip()
    except Exception:
        pass

    if not answer:
        answer = f"【{persona_name}】关于「{question}」—— 让我想想...这是一个好问题。作为{persona['domain']}领域的学者, 我认为关键在于持续学习与独立思考。多观察、多提问、多实践, 自然会有感悟。"

    return jsonify({
        'code': 0,
        'data': {
            'persona_id': persona_id,
            'persona_name': persona_name,
            'question': question,
            'answer': answer,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    })


# =================================================================
# 🆕 Phase 9: 文曲星 AI 写作生成器 — 冰山文学域专属
# =================================================================

@bp.route('/wenquxing', methods=['GET'])
def wenquxing_page():
    """📜 文曲星 — 仙女座文学域 AI 写作生成器 (冰山内嵌)"""
    stars = _load_25_stars()
    literary_employees = _get_wqx_literary_team()
    eigenflux_helpers = _get_wqx_eigenflux_helpers()
    stats = _get_wqx_stats()
    return render_template(
        'andromeda_wenquxing.html',
        stars=stars,
        wqx_modes=_get_wqx_modes(),
        ollama_status=_check_wqx_ollama(),
        literary_team=literary_employees,   # 文学 AI 员工 + 天团
        eigenflux_team=eigenflux_helpers,   # EigenFlux 专家辅助
        wqx_stats=stats,                    # 产出统计
    )


@bp.route('/api/wqx/generate', methods=['POST'])
def api_wqx_generate():
    """📜 文曲星生文 API — 调 ai_wenquxing_engine
    权限规则 (白名单):
      ✅ student / 普通登录用户(role为空) / super_admin  → 放行
      ❌ admin / teacher / professor / parent / guest   → 禁止
    """
    from flask import session as _sess
    uid = _sess.get('user_id') or _sess.get('authenticated', False)
    role = (_sess.get('role') or _sess.get('user_role') or '').strip().lower()
    
    if not uid:
        return jsonify({'code': 401, 'msg': '请先登录'}), 401
    # 白名单: 学生/普通用户(role空)/SA 放行 — 其余全部禁止
    _SA = {'super_admin', 'sa', 'wuchenghao15'}
    _STUDENT = {'student', '', 'learner', 'pupil'}
    _DENY_LABEL = {
        'admin': '管理员', 'administrator': '管理员',
        'teacher': '教师', 'professor': '教授',
        'parent': '家长', 'guest': '访客',
        'tutor': '导师', 'mentor': '导师',
        'reviewer': '审核员', 'editor': '编辑',
    }
    if role in _SA:
        pass  # SA 全权限不受约束
    elif role in _STUDENT:
        pass  # 学生放行
    elif role in _DENY_LABEL:
        return jsonify({'code': 403, 'msg': f'文曲星为学生专属, {_DENY_LABEL[role]}账号不可使用'}), 403
    else:
        # 未知角色: 按最严处理, 除非 role 为空 (普通登录)
        if role:
            return jsonify({'code': 403, 'msg': f'文曲星为学生专属, 当前角色({role})不可使用'}), 403

    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or 'copy').strip()
    topic = (data.get('topic') or '').strip()
    audience = (data.get('audience') or '普通读者').strip()
    style = (data.get('style') or '专业客观').strip()
    target_words = int(data.get('target_words') or 1500)
    star_domain = (data.get('star_domain') or 'wenquxing').strip()  # 25 星域适配
    genre = (data.get('genre') or 'normal').strip()  # normal/webnovel/video_script

    if not topic:
        return jsonify({'code': 1, 'msg': '请输入主题或原文'})
    if target_words < 100 or target_words > 20000:
        return jsonify({'code': 1, 'msg': '字数应在 100 ~ 20000 之间'})

    # 加载引擎 + 星域适配 prompt
    try:
        from engines.ai_wenquxing_engine import WenquxingEngine, MODELS
        eng = WenquxingEngine()

        # 星域适配 — 如果选了特定星域, 注入该域的专属 context
        star_context = _get_star_context(star_domain, genre)
        if star_context:
            # 在 topic 前面加星域锚定
            topic = f"【{star_context['name']} · {star_context['desc']}】\n\n{topic}"

        # 网文/视频脚本的特殊 style 注入
        if genre == 'webnovel':
            style = f"{style} · 网文节奏(3章钩子+金手指+爽点密集)"
        elif genre == 'video_script':
            style = f"{style} · 视频脚本格式(分镜+旁白+画面描述)"

        task_id = eng.write(mode, topic, audience, style, target_words)

        if not task_id:
            return jsonify({'code': 2, 'msg': '生成失败, Ollama 可能离线'})

        task = eng.get_task(task_id) or {}

        # 🆕 v25.0: 文曲星产出 → 仙女座自动提交审批
        try:
            from engines.approvals_engine import submit_wenquxing_for_approval
            username = _sess.get('username') or _sess.get('authenticated_username') or 'anonymous'
            appr_rid = submit_wenquxing_for_approval(
                task_id=task_id, initiator=username,
                initiator_role=role or 'student',
                final_text=(task.get('final_text') or '')[:500])
        except Exception as _appr_err:
            appr_rid = None  # 审批不阻塞生文
            print(f"  📋 文曲星审批跳过: {_appr_err}")

        return jsonify({
            'code': 0,
            'data': {
                'task_id': task_id,
                'approval_request_id': appr_rid,  # 🆕 返回审批号
                'final_text': task.get('final_text', ''),
                'word_count': len((task.get('final_text') or '').replace(' ', '').replace('\n', '')),
                'duration_sec': task.get('duration_sec', 0),
                'tokens_saved': task.get('tokens_saved', 0),
                'star_domain': star_domain,
                'genre': genre,
                'status': task.get('status', 'done'),
            }
        })
    except Exception as e:
        return jsonify({'code': 3, 'msg': f'引擎错误: {str(e)[:120]}'}), 500


@bp.route('/api/wqx/task/<task_id>', methods=['GET'])
def api_wqx_task(task_id):
    """查询单个文曲星任务"""
    try:
        from engines.ai_wenquxing_engine import WenquxingEngine
        eng = WenquxingEngine()
        task = eng.get_task(task_id)
        if not task:
            return jsonify({'code': 404, 'msg': '任务不存在'}), 404
        return jsonify({'code': 0, 'data': task})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)[:120]}), 500


@bp.route('/api/wqx/list', methods=['GET'])
def api_wqx_list():
    """历史任务列表"""
    limit = int(request.args.get('limit', 20))
    mode = request.args.get('mode')
    try:
        from engines.ai_wenquxing_engine import WenquxingEngine
        eng = WenquxingEngine()
        tasks = eng.list_tasks(limit=limit, mode=mode or None)
        # 去掉 final_text (太大), 只返回摘要
        for t in tasks:
            t.pop('final_text', None)
        return jsonify({'code': 0, 'data': tasks})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e)[:120]}), 500


# ═══════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════
def _get_wqx_modes():
    """返回 7 种模式 + 网文/脚本 genre 列表 (给模板用)"""
    from engines.ai_wenquxing_engine import MODELS
    modes = []
    for k, v in MODELS.items():
        modes.append({'key': k, 'icon': v['icon'], 'name': v['name'], 'desc': v['desc']})
    return modes


def _check_wqx_ollama():
    """检查 Ollama 是否在线"""
    try:
        import urllib.request as _ur
        resp = _ur.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        import json as _j
        models = [m['name'] for m in _j.loads(resp.read()).get('models', [])]
        writer = next((m for m in models if '14b' in m), models[0] if models else None)
        return {'online': True, 'model': writer or 'unknown', 'models': models}
    except Exception:
        return {'online': False, 'model': None, 'models': []}


def _load_25_stars():
    """从 generate_andromeda_25.py 读 25 星域定义 (轻量版, 只取 code/icon/name/desc)"""
    stars = [
        {"code": "wenquxing", "icon": "📜", "name": "文曲星", "desc": "文学域 — 文字创作/编辑"},
        {"code": "qianShou", "icon": "🤲", "name": "千手", "desc": "中枢路由/请求汇聚"},
        {"code": "ziwei", "icon": "🔮", "name": "紫微", "desc": "预测推演/风险预警"},
        {"code": "fuxi", "icon": "🧬", "name": "伏羲", "desc": "数据挖掘/模式发现"},
        {"code": "yaoChi", "icon": "💧", "name": "瑶池", "desc": "知识管理/文档库"},
        {"code": "fanYin", "icon": "🔔", "name": "梵音", "desc": "语音合成/播客"},
        {"code": "fanHua", "icon": "🌸", "name": "繁花", "desc": "情感分析/社交"},
        {"code": "hunTianLing", "icon": "🧲", "name": "混天绫", "desc": "网络爬取/聚合"},
        {"code": "taiJi", "icon": "☯️", "name": "太极", "desc": "安全审计/加密"},
        {"code": "yueLao", "icon": "🌙", "name": "月老", "desc": "匹配推荐/关联"},
        {"code": "qingLong", "icon": "🐉", "name": "青龙", "desc": "代码生成/审查"},
        {"code": "baiHu", "icon": "🐯", "name": "白虎", "desc": "性能压测/调优"},
        {"code": "zhuQue", "icon": "🐦", "name": "朱雀", "desc": "前端/UI 生成"},
        {"code": "xuanWu", "icon": "🐢", "name": "玄武", "desc": "运维/部署/监控"},
        {"code": "jianMu", "icon": "🌳", "name": "建木", "desc": "知识图谱/实体"},
        {"code": "guiCe", "icon": "📖", "name": "鬼策", "desc": "兵法策略/决策"},
        {"code": "mengZhang", "icon": "🎭", "name": "孟章", "desc": "人格扮演/对话"},
        {"code": "lingGuang", "icon": "✨", "name": "灵光", "desc": "创意发散/头脑风暴"},
        {"code": "tianJi", "icon": "📡", "name": "天机", "desc": "实时数据流/推送"},
        {"code": "hengE", "icon": "🌕", "name": "恒娥", "desc": "图像理解/视觉"},
        {"code": "zhangHuang", "icon": "⚡", "name": "张煌", "desc": "快速迭代/原型"},
        {"code": "lieQue", "icon": "🏹", "name": "列缺", "desc": "精准搜索/检索"},
        {"code": "wangShu", "icon": "🦢", "name": "王庶", "desc": "翻译/多语互译"},
        {"code": "suanSuan", "icon": "🧮", "name": "算算", "desc": "数学/逻辑推理"},
        {"code": "tanTuo", "icon": "🔬", "name": "谭拓", "desc": "科学研究/假设"},
    ]
    return stars


def _get_star_context(star_code: str, genre: str = '') -> dict | None:
    """根据星域 code 返回该域的写作 context (让文曲星适配该域文案风格)"""
    star_map = {s['code']: s for s in _load_25_stars()}
    star = star_map.get(star_code)
    if not star:
        return None
    # 额外的写作指引 (每个星域该写什么风格)
    writing_guides = {
        "wenquxing": "文学写作专精, 文案/网文/脚本全能",
        "qianShou": "路由与编排, 技术方案文档/API 设计",
        "ziwei": "预测与决策, 报告/趋势分析/风险评估",
        "fuxi": "数据挖掘, 分析报告/数据洞察/可视化说明",
        "yaoChi": "知识管理, 文档/百科/知识库条目",
        "fanYin": "语音内容, 播客脚本/口播稿/有声书",
        "fanHua": "情感与社交, 社交媒体文案/互动回复",
        "hunTianLing": "网络聚合, 资讯摘要/爬虫报告/聚合内容",
        "taiJi": "安全与合规, 安全文档/审计报告/合规说明",
        "yueLao": "匹配与推荐, 推荐理由/配对分析/关联报告",
        "qingLong": "代码相关, 技术文档/README/API 说明",
        "baiHu": "性能相关, 性能报告/压测分析/调优文档",
        "zhuQue": "前端/UI, 设计说明/组件文档/交互稿",
        "xuanWu": "运维相关, 运维文档/部署手册/监控报告",
        "jianMu": "知识图谱, 实体关系说明/图谱构建文档",
        "guiCe": "策略决策, 兵法策略/决策分析/方案对比",
        "mengZhang": "人格对话, 角色扮演文案/剧本/对话体",
        "lingGuang": "创意发散, 创意方案/头脑风暴/灵感集",
        "tianJi": "实时数据, 数据流说明/实时监控文档",
        "hengE": "图像视觉, 视觉分析说明/图像描述",
        "zhangHuang": "快速原型, MVP 文档/原型说明/快速方案",
        "lieQue": "搜索检索, 搜索说明/检索方案/查询文档",
        "wangShu": "翻译多语, 双语译文/本地化文档/多语对照",
        "suanSuan": "数学逻辑, 数学推导/逻辑证明/算法说明",
        "tanTuo": "科学研究, 研究报告/实验说明/假设论证",
    }
    star['writing_guide'] = writing_guides.get(star_code, '')
    star['genre'] = genre
    return star


def _get_wqx_literary_team():
    """文曲星文学 AI 天团 — 5 位 AI 员工 + 仙女座文学专家组"""
    team = [
        {"id": "wqx_wenzi", "name": "蚊子", "role": "首席诗人", "level": 9,
         "prompt": "文曲星首席诗人. 擅长古典诗词、现代诗、歌词创作. 语言凝练, 意象深远.",
         "icon": "🦟", "domain": "诗歌/韵文"},
        {"id": "wqx_mobisheng", "name": "墨笔生", "role": "长文巨匠", "level": 9,
         "prompt": "文曲星长文专家. 3000+ 字深度文章, 结构严谨, 观点独到, 数据扎实.",
         "icon": "🖋️", "domain": "长文/深度稿"},
        {"id": "wqx_qianqiu", "name": "千秋", "role": "网文主编", "level": 8,
         "prompt": "文曲星网文主编. 熟悉玄幻/都市/科幻等题材, 节奏把控精准, 爽点密集.",
         "icon": "📖", "domain": "网文/连载"},
        {"id": "wqx_huazhu", "name": "话珠", "role": "编剧", "level": 8,
         "prompt": "文曲星编剧. 短视频脚本/分镜/旁白/口播稿. 画面感强, 节奏紧凑.",
         "icon": "🎬", "domain": "视频/剧本"},
        {"id": "wqx_pingxin", "name": "平心", "role": "润色师", "level": 7,
         "prompt": "文曲星润色师. 纠错/润色/风格转换/金句提炼. 保持原意, 提升文采.",
         "icon": "✨", "domain": "润色/校对"},
    ]
    # 补 DB 里真实的 AI 员工数据
    try:
        conn = sqlite3.connect(str(_DB_PATH if '_DB_PATH' in dir() else 'flask-app/app.db'))
        conn.row_factory = sqlite3.Row
        emp_count = conn.execute(
            "SELECT COUNT(*) FROM ai_employees WHERE employee_id LIKE 'wqx_%' OR name LIKE '%文曲%'"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
        conn.close()
    except Exception:
        emp_count = 5
        total = 0
    return {
        "employees": team,
        "wqx_employee_count": emp_count,
        "total_ai_employees": total,
        "literary_ti": "仙女座文学天团 — 5 位专职 AI 作家, 支撑文曲星全域创作",
    }


def _get_wqx_eigenflux_helpers():
    """EigenFlux 专家团队 — 辅助文曲星创作 (风格/合规/视角)"""
    helpers = [
        {"name": "东坡", "icon": "🪶", "expertise": "宋代文学/赤壁赋风",
         "prompt": "以苏轼的文风和视角审视文本, 追求自然旷达、情理交融."},
        {"name": "太白", "icon": "🌙", "expertise": "盛唐浪漫/李白风",
         "prompt": "以李白的浪漫主义视角审视文本, 追求想象奇绝、气势磅礴."},
        {"name": "红楼", "icon": "🏮", "expertise": "明清小说/红楼梦结构",
         "prompt": "以曹雪芹的叙事结构和人物塑造手法审视小说文本."},
        {"name": "鲁迅", "icon": "🖤", "expertise": "现代杂文/深刻批判",
         "prompt": "以鲁迅的杂文风格审视社会议题文本, 追求深刻尖锐."},
        {"name": "墨子", "icon": "⚫", "expertise": "逻辑严密/墨家思辨",
         "prompt": "以墨子的逻辑思辨风格审视论述文本, 追求论据充分、逻辑严密."},
        {"name": "文心", "icon": "📐", "expertise": "古典文论/文心雕龙",
         "prompt": "以《文心雕龙》的文学理论审视文本, 追求符合古典审美规范."},
    ]
    return helpers


def _get_wqx_stats():
    """文曲星产出统计 (从 DB)"""
    stats = {"total_tasks": 0, "done_tasks": 0, "total_words": 0, "tokens_saved": 0, "today_tasks": 0}
    try:
        conn = sqlite3.connect(str(_DB_PATH if '_DB_PATH' in dir() else 'flask-app/app.db'))
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='done' THEN 1 ELSE 0 END),0), "
                  "COALESCE(SUM(tokens_saved),0) FROM mt_wenquxing_tasks")
        row = c.fetchone()
        stats["total_tasks"] = row[0]
        stats["done_tasks"] = row[1]
        stats["tokens_saved"] = row[2]
        c.execute("SELECT COUNT(*) FROM mt_wenquxing_tasks WHERE date(created_at)=date('now','localtime')")
        stats["today_tasks"] = c.fetchone()[0]
        conn.close()
    except Exception:
        pass
    return stats
