#!/usr/bin/env python3
"""
🤖 AI 员工赋能 — Flask 路由 routes/empowerment_routes.py (v1.0 + 权限)
所有端点加 @system_container 权限保护 · 防盗链 · 登录态强制
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, request, jsonify, render_template, session
from app.middlewares.system_container import system_container

emp_bp = Blueprint('empowerment', __name__)

def _eng():
    from engines.ai_empowerment_engine import AIEmpowermentEngine
    return AIEmpowermentEngine()

# ═══ 页面级: guest 可看 (但登录态才进得去 · @system_container guest 要求登录态) ═══
@emp_bp.route('/empower/center', methods=['GET'])
@system_container(require_auth='guest')
def empower_center():
    return render_template('andromeda_empowerment_center.html',
                          username=session.get('username','wuchenghao15'))

# ═══ API: login 可读写 (consult/contribute 需要身份, 至少登录) ═══
@emp_bp.route('/api/empower/status', methods=['GET'])
@system_container(require_auth='login')
def api_status():
    return jsonify({'ok': True, **_eng().status()})

@emp_bp.route('/api/empower/profiles', methods=['GET'])
@system_container(require_auth='login')
def api_profiles():
    eng = _eng(); db = eng._conn()
    cap_type = request.args.get('domain')
    limit = int(request.args.get('limit', 500))
    if cap_type:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM mt_ai_employee_profiles WHERE domain=? ORDER BY seniority_years DESC LIMIT ?",
            (cap_type, limit)).fetchall()]
    else:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM mt_ai_employee_profiles ORDER BY seniority_years DESC LIMIT ?",
            (limit,)).fetchall()]
    db.close()
    return jsonify({'ok': True, 'total': len(rows), 'profiles': rows})

@emp_bp.route('/api/empower/profiles/<emp_id>', methods=['GET'])
@system_container(require_auth='login')
def api_profile_detail(emp_id):
    eng = _eng(); db = eng._conn()
    row = db.execute("SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?", (emp_id,)).fetchone()
    if not row: db.close(); return jsonify({'ok': False, 'error': 'not found'}), 404
    data = dict(row)
    if data.get('master_id'):
        m = db.execute("SELECT name, seniority_years FROM mt_ai_employee_profiles WHERE employee_id=?",
                       (data['master_id'],)).fetchone()
        data['master'] = dict(m) if m else None
    data['follows'] = [dict(r) for r in db.execute(
        "SELECT target, relation FROM mt_ai_employee_social_graph WHERE actor=? AND relation IN ('FOLLOW','FRIEND')",
        (emp_id,)).fetchall()]
    data['contributions'] = [dict(r) for r in db.execute(
        "SELECT * FROM mt_ai_employee_contributions WHERE employee_id=? ORDER BY created_at DESC LIMIT 10",
        (emp_id,)).fetchall()]
    data['consultations'] = [dict(r) for r in db.execute(
        "SELECT * FROM mt_ai_employee_consultations WHERE asker=? ORDER BY created_at DESC LIMIT 10",
        (emp_id,)).fetchall()]
    db.close()
    return jsonify({'ok': True, 'profile': data})

@emp_bp.route('/api/empower/profiles/<emp_id>/feed', methods=['GET'])
@system_container(require_auth='login')
def api_feed(emp_id):
    limit = int(request.args.get('limit', 20))
    return jsonify(_eng().feed(emp_id, limit))

# consult/contribute 写入型: admin 才允许 (保护 AI 员工行为不被匿名污染)
@emp_bp.route('/api/empower/profiles/<emp_id>/consult', methods=['POST'])
@system_container(require_auth='admin')
def api_consult(emp_id):
    body = request.get_json(force=True) or {}
    question = body.get('question', '')
    advisor = body.get('advisor_id')
    if not question: return jsonify({'ok': False, 'error': 'need question'}), 400
    # 审计: 谁触发的
    _audit('consult', emp_id, {'question': question[:50], 'username': session.get('username')})
    return jsonify(_eng().consult(emp_id, question, advisor))

@emp_bp.route('/api/empower/profiles/<emp_id>/contribute', methods=['POST'])
@system_container(require_auth='admin')
def api_contribute(emp_id):
    body = request.get_json(force=True) or {}
    _audit('contribute', emp_id, {'type': body.get('type'), 'username': session.get('username')})
    return jsonify(_eng().contribute(emp_id,
        body.get('type','作品'), body.get('title',''), body.get('content',''),
        float(body.get('impact',1.0)), body.get('audience','朋友圈'),
        body.get('tags')))

@emp_bp.route('/api/empower/social', methods=['GET'])
@system_container(require_auth='login')
def api_social():
    eng = _eng(); db = eng._conn()
    relation = request.args.get('relation')
    sql = "SELECT * FROM mt_ai_employee_social_graph"
    params: list = []
    if relation: sql += " WHERE relation=?"; params.append(relation)
    rows = [dict(r) for r in db.execute(sql + " LIMIT 500", params).fetchall()]
    db.close()
    return jsonify({'ok': True, 'edges': rows})

# seed 破坏性: super_admin 才允许
@emp_bp.route('/api/empower/seed', methods=['POST'])
@system_container(require_auth='super_admin')
def api_seed():
    eng = _eng()
    p = eng.seed_profiles()
    s = eng.seed_social_graph()
    _audit('seed', 'all', {'profiles': p.get('inserted'), 'social': s.get('inserted')})
    return jsonify({'ok': True, 'profiles': p, 'social': s})


# ═══════════════════════════════════════════════════
# 🆕 管理 API (admin+)
# ═══════════════════════════════════════════════════

# 编辑员工档案 (资历/绝技/domain/标签)
@emp_bp.route('/api/empower/profiles/<emp_id>', methods=['PUT'])
@system_container(require_auth='admin')
def api_edit_profile(emp_id):
    body = request.get_json(force=True) or {}
    db = _eng()._conn()
    # 先查存在
    row = db.execute('SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?', (emp_id,)).fetchone()
    if not row: db.close(); return jsonify({'ok': False, 'error': 'not found'}), 404
    # 可编辑字段 (白名单)
    allowed = {'seniority_years', 'domain', 'unique_skill', 'tag', 'group_tag'}
    sets = []; vals = []
    for k in allowed:
        if k in body:
            sets.append(f'{k}=?')
            vals.append(body[k])
    if not sets:
        db.close()
        return jsonify({'ok': False, 'error': 'no editable fields (allowed: seniority_years, domain, unique_skill, tag, group_tag)'}), 400
    vals.append(emp_id)
    db.execute(f"UPDATE mt_ai_employee_profiles SET {','.join(sets)} WHERE employee_id=?", vals)
    db.commit()
    _audit('edit_profile', emp_id, {k: body[k] for k in allowed if k in body})
    # 返回更新后的
    new_row = dict(db.execute('SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?', (emp_id,)).fetchone())
    db.close()
    return jsonify({'ok': True, 'profile': new_row})

# 手动绑定/更换师傅
@emp_bp.route('/api/empower/profiles/<emp_id>/bind_master', methods=['POST'])
@system_container(require_auth='admin')
def api_bind_master(emp_id):
    body = request.get_json(force=True) or {}
    master_id = body.get('master_id')
    db = _eng()._conn()
    emp = db.execute('SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?', (emp_id,)).fetchone()
    if not emp: db.close(); return jsonify({'ok': False, 'error': 'employee not found'}), 404
    if master_id:
        m = db.execute('SELECT * FROM mt_ai_employee_profiles WHERE employee_id=?', (master_id,)).fetchone()
        if not m: db.close(); return jsonify({'ok': False, 'error': 'master not found'}), 404
        # 不能自己当自己师傅
        if master_id == emp_id: db.close(); return jsonify({'ok': False, 'error': 'cannot be own master'}), 400
    db.execute('UPDATE mt_ai_employee_profiles SET master_id=? WHERE employee_id=?', (master_id, emp_id))
    db.execute("DELETE FROM mt_ai_employee_social_graph WHERE actor=? AND relation='MENTOR'", (emp_id,))
    db.execute("DELETE FROM mt_ai_employee_social_graph WHERE target=? AND relation='MENTEE'", (emp_id,))
    if master_id:
        db.execute("INSERT INTO mt_ai_employee_social_graph (actor,target,relation,since) VALUES (?,?,?,datetime('now'))",
                   (emp_id, master_id, 'MENTOR'))
        db.execute("INSERT OR IGNORE INTO mt_ai_employee_social_graph (actor,target,relation,since) VALUES (?,?,?,datetime('now'))",
                   (master_id, emp_id, 'MENTEE'))
    db.commit()
    _audit('bind_master', emp_id, {'master_id': master_id})
    db.close()
    return jsonify({'ok': True, 'master_id': master_id})

# 批量触发: 全员发光发热 (daemon 驱动)
@emp_bp.route('/api/empower/batch/contribute', methods=['POST'])
@system_container(require_auth='admin')
def api_batch_contribute():
    body = request.get_json(force=True) or {}
    limit = int(body.get('limit', 50))
    eng = _eng()
    r = eng.batch_contribute(limit=limit)
    _audit('batch_contribute', 'all', {'limit': limit, 'contributed': r.get('count')})
    return jsonify({'ok': True, **r})

# 批量触发: 全员自主请教
@emp_bp.route('/api/empower/batch/consult', methods=['POST'])
@system_container(require_auth='admin')
def api_batch_consult():
    body = request.get_json(force=True) or {}
    limit = int(body.get('limit', 30))
    eng = _eng()
    r = eng.batch_consult(limit=limit)
    _audit('batch_consult', 'all', {'limit': limit, 'consulted': r.get('count')})
    return jsonify({'ok': True, **r})

# 查询赋能审计日志
@emp_bp.route('/api/empower/audit', methods=['GET'])
@system_container(require_auth='login')
def api_audit():
    limit = int(request.args.get('limit', 100))
    db = _eng()._conn()
    rows = [dict(r) for r in db.execute(
        'SELECT * FROM mt_ai_employee_empowerment_log ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()]
    db.close()
    return jsonify({'ok': True, 'total': len(rows), 'logs': rows})


# ── 审计 helper ──
def _audit(action: str, target: str, detail: dict):
    try:
        import sqlite3; from datetime import datetime
        db = sqlite3.connect(str(Path(__file__).parent.parent / 'database' / 'app.db'))
        db.execute("""INSERT INTO mt_ai_employee_empowerment_log
            (employee_id, action, detail, created_at) VALUES (?,?,?,?)""",
            (f"admin:{session.get('username','anon')}", action, json.dumps(detail,ensure_ascii=False),
             datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        db.commit(); db.close()
    except Exception: pass
