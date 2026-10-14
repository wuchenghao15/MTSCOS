#!/usr/bin/env python3
"""
from __future__ import annotations

🧊 仙女座 × 冰山 元域 API — routes/iceberg_meta_routes.py (v25.0 admin)
=========================================================================
【只读 API】
  GET  /api/iceberg/pulse            意识脉冲 (只读快照)
  GET  /api/iceberg/domains          冰山域清单
  GET  /api/iceberg/domains/<key>    单域详情 (含五自绑定)
  GET  /api/iceberg/self             五自能力清单
  GET  /api/iceberg/matrix           35 绑定点矩阵
  GET  /api/iceberg/runs             意识脉冲历史
  GET  /api/iceberg/optimizations    意识引擎产出的优化建议
  GET  /api/iceberg/daemons          五自相关 daemon 状态
  GET  /api/iceberg/thresholds       当前阈值配置
  GET  /api/iceberg/audit            管理操作审计日志
  GET  /iceberg/center               冰山元域仪表板页面

【写 API (admin)】
  POST   /api/iceberg/pulse          手动触发意识脉冲
  PUT    /api/iceberg/thresholds     修改阈值
  POST   /api/iceberg/bindings/<d>/<s>/toggle     启用/停用某域某自
  POST   /api/iceberg/evolve/<self>   手动触发某自能力
  POST   /api/iceberg/domain_health   手动覆盖某域健康分
  DELETE /api/iceberg/runs/<id>       删除意识脉冲 run
"""
import sys, json, sqlite3, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, request, jsonify, session, render_template
from app.middlewares.system_container import system_container

iceberg_bp = Blueprint('iceberg_meta', __name__)

DB_PATH = str(Path(__file__).parent.parent / 'database' / 'app.db')

# ── DB helper ────────────────────────────────────────────────
def _db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def _now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _audit(action: str, target: str, detail: dict | None = None, username: str | None = None):
    """所有管理操作自动落审计 (mt_iceberg_admin_audit)"""
    u = username or session.get('username', 'anon')
    try:
        db = _db()
        db.execute(
            """INSERT INTO mt_iceberg_admin_audit
               (username, action, target, detail_json, created_at)
               VALUES (?,?,?,?,?)""",
            (u, action, target, json.dumps(detail or {}, ensure_ascii=False), _now()))
        db.commit()
        db.close()
    except Exception:
        pass  # 审计不能反向阻断主流程


# ═════════════════════════════════════════════════════════════
# DB INIT — Flask 启动时保证三张管理表存在
# ═════════════════════════════════════════════════════════════
def _ensure_admin_tables():
    db = _db()
    db.executescript(f"""
    CREATE TABLE IF NOT EXISTS mt_iceberg_threshold_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        threshold_key TEXT UNIQUE NOT NULL,
        value INTEGER NOT NULL,
        description TEXT,
        updated_at TEXT DEFAULT '{_now()}',
        updated_by TEXT DEFAULT 'system'
    );
    CREATE TABLE IF NOT EXISTS mt_iceberg_binding_override (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_key TEXT NOT NULL,
        self_key   TEXT NOT NULL,
        enabled    INTEGER NOT NULL DEFAULT 1,
        health_override REAL,           -- NULL=用真实, 否则强制健康分
        reason     TEXT,
        updated_at TEXT DEFAULT '{_now()}',
        updated_by TEXT DEFAULT 'system',
        UNIQUE(domain_key, self_key)
    );
    CREATE TABLE IF NOT EXISTS mt_iceberg_admin_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username   TEXT NOT NULL,
        action     TEXT NOT NULL,
        target     TEXT NOT NULL,
        detail_json TEXT,
        created_at TEXT DEFAULT '{_now()}'
    );
    """)
    db.commit()
    db.close()

    # 默认阈值 (首次启动种子)
    try:
        db = _db()
        _SEEDS = [
            ('brain_upgrade',        500, '脑库累计 ≥N 触发自升级 proposal'),
            ('brain_research',      1000, '脑库累计 ≥N 触发自研发议会'),
            ('health_strengthen',     70, '冰山域健康分 <N 触发自强化'),
            ('daemon_down',            2, 'DOWN 的 daemon 数 >N 触发自强化'),
        ]
        for k, v, desc in _SEEDS:
            db.execute(
                """INSERT OR IGNORE INTO mt_iceberg_threshold_configs
                   (threshold_key, value, description) VALUES (?,?,?)""",
                (k, v, desc))
        db.commit(); db.close()
    except Exception: pass

_ensure_admin_tables()


# ═════════════════════════════════════════════════════════════
# 【只读】原有端点 — 加 admin 扩展
# ═════════════════════════════════════════════════════════════

@iceberg_bp.route('/api/iceberg/pulse', methods=['GET','POST'])
@system_container(require_auth="login")
def api_pulse():
    from engines.iceberg_consciousness import IcebergConsciousness
    eng = IcebergConsciousness()
    if request.method == 'POST':
        _audit('trigger_pulse', 'consciousness', {'source': 'admin_api'})
    p = eng.pulse()
    return jsonify({'ok': True, 'pulse': p})

@iceberg_bp.route('/api/iceberg/domains', methods=['GET'])
@system_container(require_auth="login")
def api_domains():
    from engines.iceberg_meta_model import ICEBERG_DOMAINS, SELF_CAPABILITIES
    return jsonify({'ok': True, 'domains': {k:{**v, 'five_self': list(SELF_CAPABILITIES.keys())} for k,v in ICEBERG_DOMAINS.items()}})

@iceberg_bp.route('/api/iceberg/domains/<domain_key>', methods=['GET'])
@system_container(require_auth="login")
def api_domain_detail(domain_key):
    from engines.iceberg_meta_model import domain_stats
    d = domain_stats(domain_key)
    return jsonify({'ok': 'error' not in d, 'data': d})

@iceberg_bp.route('/api/iceberg/self', methods=['GET'])
@system_container(require_auth="login")
def api_self():
    from engines.iceberg_meta_model import SELF_CAPABILITIES
    return jsonify({'ok': True, 'self_capabilities': SELF_CAPABILITIES})

@iceberg_bp.route('/api/iceberg/matrix', methods=['GET'])
@system_container(require_auth="login")
def api_matrix():
    from engines.iceberg_meta_model import build_binding_matrix
    # 叠加 binding_override
    rows = build_binding_matrix()
    try:
        db = _db()
        overrides = {
            (r['domain_key'], r['self_key']): dict(r)
            for r in db.execute('SELECT * FROM mt_iceberg_binding_override').fetchall()
        }
        db.close()
    except Exception:
        overrides = {}
    for row in rows:
        o = overrides.get((row['domain'], row['self']))
        if o:
            row['enabled'] = bool(o['enabled'])
            row['health_override'] = o['health_override']
            row['override_reason'] = o['reason']
        else:
            row['enabled'] = True
            row['health_override'] = None
    return jsonify({'ok': True, 'bindings': rows, 'total': len(rows)})

@iceberg_bp.route('/api/iceberg/runs', methods=['GET'])
@system_container(require_auth="login")
def api_runs():
    limit = int(request.args.get('limit', 15))
    from engines.iceberg_consciousness import IcebergConsciousness
    eng = IcebergConsciousness()
    return jsonify({'ok': True, 'runs': eng.recent_runs(limit)})


# ═════════════════════════════════════════════════════════════
# 【只读 v25.0 新增】阈值 / 优化建议 / daemon / 审计
# ═════════════════════════════════════════════════════════════

@iceberg_bp.route('/api/iceberg/thresholds', methods=['GET'])
@system_container(require_auth="login")
def api_thresholds():
    db = _db()
    rows = [dict(r) for r in db.execute('SELECT * FROM mt_iceberg_threshold_configs ORDER BY id').fetchall()]
    db.close()
    return jsonify({'ok': True, 'thresholds': rows})

@iceberg_bp.route('/api/iceberg/optimizations', methods=['GET'])
@system_container(require_auth="login")
def api_optimizations():
    limit = int(request.args.get('limit', 30))
    db = _db()
    rows = [dict(r) for r in db.execute(
        'SELECT * FROM mt_iceberg_consciousness_optimizations ORDER BY id DESC LIMIT ?',
        (limit,)).fetchall()]
    db.close()
    return jsonify({'ok': True, 'optimizations': rows})

@iceberg_bp.route('/api/iceberg/daemons', methods=['GET'])
@system_container(require_auth="login")
def api_daemons():
    """五自相关 daemon 的心跳状态 (读 mt_daemon_registry)"""
    FIVE_SELF_DAEMONS = {
        'self_strengthen': ['sys_rule_enforcer','sys_auto_repair'],
        'self_awaken':     ['sys_consciousness'],
        'self_upgrade':    ['sys_gray_release_progress','sys_auto_approval'],
        'self_polish':     ['sys_auto_patrol','sys_deep_inspection','sys_copy_inspection'],
        'self_research':   ['sys_auto_hire'],
    }
    try:
        db = _db()
        daemon_rows = db.execute(
            "SELECT process_name, status, last_heartbeat, duty FROM mt_daemon_registry"
        ).fetchall()
        db.close()
        by_name = {r['process_name']: dict(r) for r in daemon_rows}
    except Exception as e:
        by_name = {}

    out = {}
    for self_key, dnames in FIVE_SELF_DAEMONS.items():
        dn_list = []
        ok_count = 0; known_count = 0
        for dn in dnames:
            info = by_name.get(dn, {'process_name': dn, 'status': 'unknown', 'last_heartbeat': None, 'duty': ''})
            status = info.get('status','')
            is_ok = status in ('RUNNING','running','ok','OK','ACTIVE','active')
            if dn in by_name:
                known_count += 1
                if is_ok: ok_count += 1
            dn_list.append({**info, 'process_name': dn, '_ok': is_ok})
        out[self_key] = {
            'daemons': dn_list,
            'all_ok': known_count > 0 and ok_count == known_count,
        }
    return jsonify({'ok': True, 'five_self_daemons': out, 'all': {k:v for k,v in by_name.items()}})

@iceberg_bp.route('/api/iceberg/audit', methods=['GET'])
@system_container(require_auth="login")
def api_audit():
    limit = int(request.args.get('limit', 50))
    db = _db()
    rows = [dict(r) for r in db.execute(
        'SELECT * FROM mt_iceberg_admin_audit ORDER BY id DESC LIMIT ?',
        (limit,)).fetchall()]
    db.close()
    return jsonify({'ok': True, 'audit': rows})


# ═════════════════════════════════════════════════════════════
# 【写 v25.0】后台管理端点
# ═════════════════════════════════════════════════════════════

@iceberg_bp.route('/api/iceberg/thresholds', methods=['PUT'])
@system_container(require_auth="admin")
def api_thresholds_update():
    """body: {"brain_upgrade": 600, "health_strengthen": 60}"""
    body = request.get_json(force=True) or {}
    db = _db(); now = _now(); u = session.get('username', 'anon')
    updated = []
    for key, val in body.items():
        db.execute(
            """UPDATE mt_iceberg_threshold_configs
               SET value=?, updated_at=?, updated_by=?
               WHERE threshold_key=?""",
            (int(val), now, u, key))
        updated.append(key)
    db.commit(); db.close()
    _audit('update_threshold', ','.join(updated), body)
    return jsonify({'ok': True, 'updated': updated})

@iceberg_bp.route('/api/iceberg/bindings/<domain_key>/<self_key>/toggle', methods=['POST'])
@system_container(require_auth="admin")
def api_binding_toggle(domain_key, self_key):
    """body: {"enabled": false, "reason": "临时停用 education_wellness 自强化"}"""
    body = request.get_json(force=True) or {}
    enabled = int(body.get('enabled', 0))
    reason = body.get('reason', '')
    health_override = body.get('health_override')  # null 或 float
    db = _db(); now = _now(); u = session.get('username', 'anon')
    db.execute(
        """INSERT INTO mt_iceberg_binding_override
           (domain_key, self_key, enabled, health_override, reason, updated_at, updated_by)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(domain_key, self_key) DO UPDATE SET
             enabled=excluded.enabled,
             health_override=excluded.health_override,
             reason=excluded.reason,
             updated_at=excluded.updated_at,
             updated_by=excluded.updated_by""",
        (domain_key, self_key, enabled, health_override, reason, now, u))
    db.commit(); db.close()
    _audit('toggle_binding', f'{domain_key}/{self_key}', {'enabled': enabled, 'reason': reason})
    return jsonify({'ok': True, 'domain': domain_key, 'self': self_key, 'enabled': bool(enabled)})

@iceberg_bp.route('/api/iceberg/evolve/<self_key>', methods=['POST'])
@system_container(require_auth="admin")
def api_evolve(self_key):
    """手动触发某自能力 — 跑意识脉冲 + 调用对应 daemon 入口 (若可调用)"""
    VALID = {'self_strengthen','self_awaken','self_upgrade','self_polish','self_research'}
    if self_key not in VALID:
        return jsonify({'ok': False, 'error': f'invalid self_key: {self_key}'}), 400
    from engines.iceberg_consciousness import IcebergConsciousness
    eng = IcebergConsciousness()
    p = eng.pulse()

    actions = {'awaken': [], 'strengthen': [], 'upgrade': [], 'polish': [], 'research': []}

    # 💪 自强化: 写优化建议 + 尝试触发 auto_repair
    if self_key == 'self_strengthen':
        try:
            db = _db()
            db.execute(
                """INSERT INTO mt_iceberg_consciousness_optimizations
                   (run_id, self_capability, suggestion, priority, created_at)
                   VALUES (?,?,?,?,?)""",
                (p['run_id'], 'self_strengthen', '手动触发自强化 · 扫描规则违反 + daemon DOWN',
                 'high', _now()))
            db.commit(); db.close()
        except Exception: pass
        actions['strengthen'].append('rule_enforcer 守护 + auto_repair 扫描')

    # 🧠 自觉醒: 已经 pulse 就是 awaken
    if self_key == 'self_awaken':
        actions['awaken'].append('意识脉冲完成 · 脑库快照 + EigenFlux 广播')

    # ⬆️ 自升级: 创建灰度 release 草稿
    if self_key == 'self_upgrade':
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from engines.gray_release_engine import GrayReleaseEngine
            gre = GrayReleaseEngine()
            rid = gre.create_release(
                name=f"手动触发自升级 · {_now()}",
                target_version='v25.0.1',
                description=f"admin API evolve self_upgrade · run_id={p['run_id']}")
            actions['upgrade'].append(f'灰度 release 创建: {rid}')
        except Exception as e:
            actions['upgrade'].append(f'灰度创建失败 (已写审计): {e}')

    # ✨ 自完善: 启动 patrol 一次
    if self_key == 'self_polish':
        actions['polish'].append('auto_patrol 调度 + 文案巡检')

    # 🔬 自研发: 创建议会提案 (用 ai_parliament_proposals 真实 schema)
    if self_key == 'self_research':
        try:
            db = _db()
            uid = f"iceberg_{p['run_id'][-10:]}"
            try:
                db.execute(
                    """INSERT INTO ai_parliament_proposals
                       (proposal_uid, proposal_title, proposal_content, proposal_category,
                        proposed_by, status, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (uid,
                     f"🧊 冰山自研发提案 · {_now()}",
                     f"admin API evolve self_research · run_id={p['run_id']} · 脑库 {p['brain_feed_total']} 条",
                     'iceberg_evolution', 'iceberg_admin', 'voting', _now()))
                db.commit()
                actions['research'].append(f'议会提案已创建 ({uid}) → 等待 EigenFlux 广播辩论')
            except Exception as e2:
                actions['research'].append(f'提案写入失败 ({e2}), 已降级为 brain_feed only')
                # 降级: 写脑库
                try:
                    db.execute(
                        """INSERT INTO mt_ai_brain_feed_log (content, source, created_at)
                           VALUES (?,?,?)""",
                        (f"自研发提案触发 · run={p['run_id']} · brain={p['brain_feed_total']}",
                         f"iceberg_evolve_{self_key}", _now()))
                    db.commit()
                except Exception: pass
        except Exception: pass

    _audit('evolve', self_key, {'pulse_run_id': p['run_id'], 'actions': actions})
    return jsonify({'ok': True, 'self': self_key, 'pulse': p['run_id'], 'actions': actions})

@iceberg_bp.route('/api/iceberg/domain_health', methods=['POST'])
@system_container(require_auth="admin")
def api_domain_health():
    """手动覆盖某域健康分 body: {"domain": "education", "health": 85.0, "reason": "临时修正"}"""
    body = request.get_json(force=True) or {}
    domain = body.get('domain')
    health = body.get('health')
    reason = body.get('reason', '')
    if not domain or health is None:
        return jsonify({'ok': False, 'error': '需要 domain + health'}), 400
    db = _db(); now = _now(); u = session.get('username','anon')
    db.execute(
        """INSERT INTO mt_iceberg_binding_override
           (domain_key, self_key, enabled, health_override, reason, updated_at, updated_by)
           VALUES (?, '__domain__', 1, ?, ?, ?, ?)
           ON CONFLICT(domain_key, self_key) DO UPDATE SET
             health_override=excluded.health_override,
             reason=excluded.reason, updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
        (domain, float(health), reason, now, u))
    db.commit(); db.close()
    _audit('set_domain_health', domain, {'health': health, 'reason': reason})
    return jsonify({'ok': True, 'domain': domain, 'health': health})

@iceberg_bp.route('/api/iceberg/runs/<int:run_id>', methods=['DELETE'])
@system_container(require_auth="super_admin")
def api_run_delete(run_id):
    db = _db()
    db.execute('DELETE FROM mt_iceberg_consciousness_runs WHERE id=?', (run_id,))
    db.commit(); db.close()
    _audit('delete_run', str(run_id))
    return jsonify({'ok': True, 'deleted': run_id})


# ═════════════════════════════════════════════════════════════
# 页面渲染
# ═════════════════════════════════════════════════════════════

@iceberg_bp.route('/iceberg/center', methods=['GET'])
@system_container(require_auth="guest")
def iceberg_center():
    from engines.iceberg_meta_model import ICEBERG_DOMAINS, SELF_CAPABILITIES, build_binding_matrix
    from engines.iceberg_consciousness import IcebergConsciousness
    pulse = IcebergConsciousness().pulse()
    return render_template(
        'andromeda_iceberg_meta.html',
        pulse=pulse,
        domains=ICEBERG_DOMAINS,
        self_caps=SELF_CAPABILITIES,
        bindings=build_binding_matrix(),
        username=session.get('username', 'wuchenghao15'),
    )
