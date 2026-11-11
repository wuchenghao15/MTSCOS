# -*- coding: utf-8 -*-
"""
SA Prime 旗舰聊天系统 (TOOLCHAT-006, flow_sa_prime_20261030)

═══ 定位 ═══
给 SA (超级管理员) 的指挥官级聊天 — 涵盖小龙全部功能 + SA 增强:
  小龙功能全涵盖: 自适应聊天 / tool-use 18工具 / 个性化主题 / 用户数据空间 / 会话持久化 / token 认证
  SA 增强:
    1. 全模型池在线切换 (Ollama 本地全部模型)
    2. 工具直通 — 免意图识别, 18 工具全时可用
    3. 系统指挥官面板 — 大厅统计 / daemon 状态 / tick 手动触发
    4. 多会话管理 — 列表 / 切换 / 历史加载
    5. 工具审计仪表 — chat_tool_calls 实时
    6. SA 黑金主题 + 最高档上下文 (full: 120k/16384)

认证: 复用 _is_sa (role==super_admin / username==wuchenghao15 / 双密钥自动认证)
"""
import json
import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request, render_template, session, g

PROJECT_PKG = "flask-app"

sa_prime_bp = Blueprint('sa_prime_bp', __name__)


# ────────────── SA 门槛 (session 或 SA token 二选一) ──────────────

def _is_sa_user() -> bool:
    try:
        from blueprints.chat_local_bp import _is_sa
        return bool(_is_sa({'user_id': session.get('user_id'),
                            'username': session.get('username'),
                            'role': session.get('role', 'user')}))
    except Exception:
        return (session.get('role') == 'super_admin'
                or session.get('username') == 'wuchenghao15')


def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def _sa_token_auth() -> dict:
    """Bearer token 兜底: Authorization: Bearer <tok> → mt_app_token(app_name=sa_prime, role=super_admin)"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return {}
    tok = auth[7:].strip()
    if not tok:
        return {}
    try:
        conn = _db()
        row = conn.execute(
            "SELECT user_id, username, role FROM mt_app_token "
            "WHERE app_name='sa_prime' AND token_hash=? AND expires_at > datetime('now','localtime')",
            (_hash_token(tok),)).fetchone()
        conn.close()
        if row and row[2] == 'super_admin':
            return {'user_id': row[0], 'username': row[1], 'role': row[2]}
    except Exception:
        pass
    return {}


def _ensure_gov_tables(conn):
    """多租户 + 审计治理表 (TOOLCHAT-007, best-effort)"""
    for ddl in (
        """CREATE TABLE IF NOT EXISTS mt_tenants(
            tenant_id TEXT PRIMARY KEY, name TEXT, status TEXT DEFAULT 'active',
            created_by TEXT, created_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS mt_tenant_members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT, user_id TEXT, role TEXT DEFAULT 'member', joined_at TEXT,
            UNIQUE(tenant_id, user_id))""",
        """CREATE TABLE IF NOT EXISTS mt_sa_audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now','localtime')),
            actor TEXT, actor_role TEXT, tenant_id TEXT,
            action TEXT, target TEXT, detail TEXT, ip TEXT, via TEXT)""",
        """CREATE INDEX IF NOT EXISTS idx_sa_audit_ts ON mt_sa_audit_log(ts)""",
        """CREATE INDEX IF NOT EXISTS idx_sa_audit_actor ON mt_sa_audit_log(actor)""",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            pass


def _user_tenants(user_id: str) -> list:
    """用户所属租户列表"""
    try:
        conn = _db()
        rows = conn.execute("SELECT tenant_id FROM mt_tenant_members WHERE user_id=?",
                            (user_id,)).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _sa_audit(action: str, target: str = "", detail: str = "", tenant_id: str = ""):
    """审计落库 — SA Prime 全操作 (best-effort, 不阻塞主流程)"""
    try:
        sa = _current_sa()
        via = 'token' if request.headers.get('Authorization', '').startswith('Bearer ') else 'session'
        conn = _db()
        _ensure_gov_tables(conn)
        conn.execute("""INSERT INTO mt_sa_audit_log(actor,actor_role,tenant_id,action,target,detail,ip,via)
                        VALUES(?,?,?,?,?,?,?,?)""",
                     (sa.get('username') or sa.get('user_id') or 'anonymous',
                      sa.get('role', ''), tenant_id or '',
                      action, target[:80], detail[:300],
                      request.remote_addr or '', via))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _current_sa() -> dict:
    """session SA 优先, 回退 token SA; 都无 → {}"""
    if _is_sa_user() and session.get('user_id'):
        return {'user_id': str(session.get('user_id')),
                'username': session.get('username', 'SA'), 'role': 'super_admin'}
    return _sa_token_auth()


def sa_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _current_sa():
            _sa_audit('ACCESS_DENIED', request.path, '未认证访问 SA 资源')
            return jsonify({'success': False, 'error': 'SA 专属, 需超级管理员身份'}), 403
        result = fn(*args, **kwargs)
        # 写操作审计 (执行后落, 可携带端点内设置的 g._audit_tenant)
        if request.method in ('POST', 'PUT', 'DELETE'):
            _sa_audit(f'{request.method}:{fn.__name__}', request.path,
                      json.dumps(request.get_json(silent=True) or {}, ensure_ascii=False)[:260],
                      tenant_id=getattr(g, '_audit_tenant', ''))
        return result
    return wrapper


def _uid() -> str:
    sa = _current_sa()
    return (sa.get('user_id') or session.get('user_id') or 'sa').strip()


def _db(timeout: int = 10):
    from pathlib import Path
    db = Path(__file__).resolve().parent.parent / "database" / "app.db"
    conn = sqlite3.connect(str(db), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


# ────────────── 页面 ──────────────

@sa_prime_bp.route('/sa-prime')
def page_sa_prime():
    """SA 旗舰聊天页 (非 SA → 提示页)"""
    if not _is_sa_user():
        return render_template('sa_prime_denied.html'), 403
    return render_template('sa_prime.html',
                           username=session.get('username', 'SA'),
                           user_id=_uid())


# ────────────── 能力清单 ──────────────

@sa_prime_bp.route('/api/sa-prime/token', methods=['POST'])
def api_issue_token():
    """SA token 签发: super_admin 凭据 → 30 天 Bearer token (认证兜底, 与登录等效)"""
    d = request.get_json(silent=True) or {}
    username = (d.get('username') or '').strip()
    password = (d.get('password') or '').strip()
    if not username or not password:
        return jsonify({'success': False, 'error': 'username/password 必填'}), 400
    if username.lower() != 'wuchenghao15':
        return jsonify({'success': False, 'error': '仅超级管理员可签发 SA Prime token'}), 403
    try:
        conn = _db()
        row = conn.execute(
            "SELECT id, username, role, password_hash, is_active FROM users WHERE username=?",
            (username,)).fetchone()
        conn.close()
        if not row or not int(row[4] or 1):
            return jsonify({'success': False, 'error': '用户不存在或已停用'}), 403
        stored = row[3] or ''
        ok = False
        try:
            from server_real_db import _verify_password
            ok = _verify_password(password, stored)
        except Exception:
            from werkzeug.security import check_password_hash
            try:
                ok = check_password_hash(stored, password)
            except Exception:
                ok = False
        if not ok:
            return jsonify({'success': False, 'error': '凭据错误'}), 403
        tok = secrets.token_urlsafe(32)
        exp = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        conn = _db()
        conn.execute("""INSERT INTO mt_app_token(app_name,token_hash,device_id,user_id,username,role,expires_at)
                        VALUES('sa_prime',?,?,?,?,?,?)""",
                     (_hash_token(tok), (d.get('device_id') or '')[:40],
                      row[0], row[1], 'super_admin', exp))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'token': tok, 'expires_at': exp,
                        'user': {'user_id': row[0], 'username': row[1], 'role': 'super_admin'}})
    except Exception as ex:
        return jsonify({'success': False, 'error': str(ex)[:150]}), 500


@sa_prime_bp.route('/api/sa-prime/me')
@sa_required
def api_me():
    """SA 身份 + 能力总览"""
    tools = []
    try:
        from engines.chat_toolbox import TOOLS
        tools = [{'name': k, 'desc': v[1][:60], 'ready': v[0] is not None} for k, v in TOOLS.items()]
    except Exception:
        pass
    return jsonify({'success': True, 'user_id': _uid(),
                    'username': session.get('username', 'SA'),
                    'tier': 'full (120k ctx / 16384 out)',
                    'tenants': _user_tenants(_uid()),
                    'tools': tools,
                    'features': ['model_pool', 'tool_direct', 'commander_panel',
                                 'multi_session', 'audit_dashboard', 'theme_blackgold',
                                 'user_space', 'hall_lookup', 'patch_function']})


@sa_prime_bp.route('/api/sa-prime/models')
@sa_required
def api_models():
    """全模型池 (Ollama /api/tags)"""
    import urllib.request
    for host in ("127.0.0.1:11434", "100.121.98.15:11434"):
        try:
            r = urllib.request.urlopen(f"http://{host}/api/tags", timeout=6)
            data = json.loads(r.read())
            models = [{'name': m['name'], 'size_gb': round(m.get('size', 0) / 1e9, 1)}
                      for m in data.get('models', [])]
            return jsonify({'success': True, 'host': host, 'models': models})
        except Exception:
            continue
    return jsonify({'success': False, 'error': 'Ollama 不可达', 'models': []})


# ────────────── 核心聊天 (工具直通 + 模型切换) ──────────────

def _ensure_chat_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_sessions(
        session_id TEXT PRIMARY KEY, user_id TEXT, title TEXT,
        created_at TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
        content TEXT, created_at TEXT)""")


@sa_prime_bp.route('/api/sa-prime/chat', methods=['POST'])
@sa_required
def api_chat():
    """
    SA 核心聊天: tools 强制开启 (免意图识别) + 模型任选 + 多轮历史
    body: {message, session_id?, model?, history?}
    """
    d = request.get_json(silent=True) or {}
    msg = (d.get('message') or '').strip()
    if not msg:
        return jsonify({'success': False, 'error': 'message 为空'}), 400
    sid = (d.get('session_id') or '').strip() or f"sap_{datetime.now().strftime('%Y%m%d%H%M%S')}_{_uid()[:8]}"
    model = (d.get('model') or 'qwen2.5:14b-q5_K_M').strip()

    # 会话 + 历史 (chat_sessions 13列结构, 与小龙共享 — 显式列名)
    conn = _db()
    _ensure_chat_tables(conn)
    row = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
    if not row:
        conn.execute("""INSERT INTO chat_sessions(session_id,user_id,username,title,created_at,updated_at,message_count)
                        VALUES(?,?,?,?,datetime('now','localtime'),datetime('now','localtime'),0)""",
                     (sid, _uid(), session.get('username', 'SA'), msg[:40]))
        conn.commit()
    history = [{'role': r, 'content': c} for r, c in
               conn.execute("SELECT role, content FROM chat_messages WHERE session_id=? "
                            "ORDER BY id DESC LIMIT 12", (sid,)).fetchall()][::-1]
    conn.close()

    # 工具直通: SA 免意图识别, 强制走 run_tool_loop
    try:
        from engines.chat_toolbox import run_tool_loop
        r = run_tool_loop(model=model, system_prompt='你是 MTSCOS SA 指挥官助手, 全能力可用。',
                          user_text=msg, history=history, session_id=sid, user_id=_uid(),
                          host='127.0.0.1:11434', num_predict=16384)
        reply = r['answer']
        if r['tool_calls']:
            tl = "\n".join(f"🔧 {t['tool']}({'/'.join(str(v)[:36] for v in (t['args'] or {}).values())}) "
                           f"→ {'✅' if t['ok'] else '❌'} {t['summary'][:60]}"
                           for t in r['tool_calls'])
            reply = f"{tl}\n\n{reply}"
        tool_log = r['tool_calls']
        rounds = r['rounds']
    except Exception as ex:
        reply, tool_log, rounds = f"⚠️ 工具链故障: {str(ex)[:150]}", [], 0

    # 持久化 (chat_messages 15列结构, 显式列名)
    try:
        conn = _db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO chat_messages(session_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
                     (sid, _uid(), 'user', msg, now))
        conn.execute("INSERT INTO chat_messages(session_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
                     (sid, _uid(), 'assistant', reply, now))
        conn.execute("""UPDATE chat_sessions SET updated_at=?,
                        message_count=(SELECT COUNT(*) FROM chat_messages WHERE session_id=?),
                        last_message=? WHERE session_id=?""", (now, sid, reply[:80], sid))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return jsonify({'success': True, 'session_id': sid, 'reply': reply,
                    'model': model, 'tool_mode': True,
                    'tool_calls': tool_log, 'rounds': rounds,
                    'tenant': (_user_tenants(_uid()) or [''])[0]})


# ────────────── 多会话管理 ──────────────

@sa_prime_bp.route('/api/sa-prime/sessions')
@sa_required
def api_sessions():
    conn = _db()
    _ensure_chat_tables(conn)
    rows = conn.execute("""SELECT s.session_id, s.title, s.updated_at,
                           (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.session_id)
                           FROM chat_sessions s WHERE s.user_id=?
                           ORDER BY s.updated_at DESC LIMIT 30""", (_uid(),)).fetchall()
    conn.close()
    return jsonify({'success': True, 'sessions': [
        {'session_id': r[0], 'title': r[1] or '(未命名)', 'updated_at': r[2], 'msgs': r[3]}
        for r in rows]})


@sa_prime_bp.route('/api/sa-prime/session/<sid>')
@sa_required
def api_session_detail(sid):
    conn = _db()
    rows = conn.execute("SELECT role, content, created_at FROM chat_messages "
                        "WHERE session_id=? ORDER BY id ASC LIMIT 200", (sid,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'session_id': sid, 'messages': [
        {'role': r[0], 'content': r[1], 'at': r[2]} for r in rows]})


# ────────────── 多租户管理 (TOOLCHAT-007) ──────────────

@sa_prime_bp.route('/api/sa-prime/tenants', methods=['GET'])
@sa_required
def api_tenants_list():
    """SA 跨租户总览; 携带成员数与审计计数"""
    try:
        conn = _db()
        _ensure_gov_tables(conn)
        rows = conn.execute("""SELECT t.tenant_id, t.name, t.status, t.created_at,
                               (SELECT COUNT(*) FROM mt_tenant_members m WHERE m.tenant_id=t.tenant_id),
                               (SELECT COUNT(*) FROM mt_sa_audit_log a WHERE a.tenant_id=t.tenant_id)
                               FROM mt_tenants t ORDER BY t.created_at DESC""").fetchall()
        conn.close()
        return jsonify({'success': True, 'tenants': [
            {'tenant_id': r[0], 'name': r[1], 'status': r[2], 'created_at': r[3],
             'members': r[4], 'audit_events': r[5]} for r in rows]})
    except Exception as ex:
        return jsonify({'success': False, 'error': str(ex)[:150]})


@sa_prime_bp.route('/api/sa-prime/tenants', methods=['POST'])
@sa_required
def api_tenants_create():
    """创建租户: {name}"""
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name or len(name) > 40:
        return jsonify({'success': False, 'error': '租户名必填(≤40字)'}), 400
    import secrets as _sec
    tid = f"t_{_sec.token_hex(4)}"
    try:
        conn = _db()
        _ensure_gov_tables(conn)
        conn.execute("INSERT INTO mt_tenants(tenant_id,name,created_by) VALUES(?,?,?)",
                     (tid, name, _uid()))
        conn.commit()
        conn.close()
        _sa_audit('TENANT_CREATE', tid, f'租户 [{name}] 创建', tenant_id=tid)
        return jsonify({'success': True, 'tenant_id': tid, 'name': name,
                        'message': f'租户 [{name}] 已创建 ({tid})'})
    except Exception as ex:
        return jsonify({'success': False, 'error': str(ex)[:150]})


@sa_prime_bp.route('/api/sa-prime/tenants/<tid>/members', methods=['POST'])
@sa_required
def api_tenant_add_member(tid):
    """挂成员: {user_id, role?} — 校验租户存在与用户存在"""
    d = request.get_json(silent=True) or {}
    uid = (d.get('user_id') or '').strip()
    role = (d.get('role') or 'member').strip()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id 必填'}), 400
    try:
        conn = _db()
        _ensure_gov_tables(conn)
        if not conn.execute("SELECT 1 FROM mt_tenants WHERE tenant_id=?", (tid,)).fetchone():
            conn.close()
            return jsonify({'success': False, 'error': f'租户 {tid} 不存在'}), 404
        if not conn.execute("SELECT 1 FROM users WHERE user_id=? OR username=?", (uid, uid)).fetchone():
            conn.close()
            return jsonify({'success': False, 'error': f'用户 {uid} 不存在'}), 404
        conn.execute("""INSERT INTO mt_tenant_members(tenant_id,user_id,role,joined_at)
                        VALUES(?,?,?,datetime('now','localtime'))
                        ON CONFLICT(tenant_id,user_id) DO UPDATE SET role=excluded.role""", (tid, uid, role))
        conn.commit()
        conn.close()
        _sa_audit('TENANT_MEMBER_ADD', tid, f'{uid} → {role}', tenant_id=tid)
        return jsonify({'success': True, 'message': f'{uid} 已挂到租户 {tid} ({role})'})
    except Exception as ex:
        return jsonify({'success': False, 'error': str(ex)[:150]})


@sa_prime_bp.route('/api/sa-prime/tenants/<tid>/members', methods=['GET'])
@sa_required
def api_tenant_members(tid):
    conn = _db()
    rows = conn.execute("""SELECT user_id, role, joined_at FROM mt_tenant_members
                           WHERE tenant_id=? ORDER BY joined_at DESC""", (tid,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'tenant_id': tid,
                    'members': [{'user_id': r[0], 'role': r[1], 'joined_at': r[2]} for r in rows]})


# ────────────── 指挥官面板 ──────────────

@sa_prime_bp.route('/api/sa-prime/system')
@sa_required
def api_system():
    """大厅统计 + daemon 状态 + 区块链 + 方向池"""
    out = {'success': True}
    try:
        conn = _db()
        out['hall'] = dict(conn.execute(
            "SELECT status, COUNT(*) FROM mt_lab_task_hall GROUP BY status").fetchall())
        out['kp_types'] = dict(conn.execute(
            "SELECT kp_type, COUNT(*) FROM mt_center_knowledge_points GROUP BY kp_type").fetchall())
        out['directions'] = dict(conn.execute(
            "SELECT status, COUNT(*) FROM mt_center_direction_pool GROUP BY status").fetchall())
        try:
            out['blockchain'] = conn.execute("SELECT COUNT(*) FROM mt_blockchain").fetchone()[0]
        except Exception:
            out['blockchain'] = 0
        conn.close()
    except Exception as ex:
        out['hall_error'] = str(ex)[:100]
    # daemon 状态 (进程探测)
    import subprocess
    try:
        r = subprocess.run(['bash', '-c',
                            "ps aux | grep -E 'python.*(daemon|engine)' | grep -v grep | wc -l"],
                           capture_output=True, text=True, timeout=8)
        out['daemon_procs'] = int(r.stdout.strip() or 0)
    except Exception:
        out['daemon_procs'] = -1
    try:
        r2 = subprocess.run(['bash', '-c', "curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:5001/"],
                            capture_output=True, text=True, timeout=10)
        out['flask_http'] = r2.stdout.strip()
    except Exception:
        out['flask_http'] = '?'
    return jsonify(out)


@sa_prime_bp.route('/api/sa-prime/tick', methods=['POST'])
@sa_required
def api_tick():
    """SA 特权: 手动触发大厅 tick"""
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:5001/api/internal/hall/tick",
            data=json.dumps({'daemon': 'sa_prime_manual',
                             'reason': f'SA {_uid()} 手动触发'}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        resp = urllib.request.urlopen(req, timeout=150)
        return jsonify({'success': True, 'http': resp.status})
    except Exception as ex:
        return jsonify({'success': False, 'error': str(ex)[:150]})


@sa_prime_bp.route('/api/sa-prime/audit')
@sa_required
def api_audit():
    """审计仪表: 工具调用(chat_tool_calls) + SA操作流(mt_sa_audit_log), 支持过滤"""
    tenant = (request.args.get('tenant') or '').strip()
    actor = (request.args.get('actor') or '').strip()
    action = (request.args.get('action') or '').strip()
    try:
        conn = _db()
        _ensure_gov_tables(conn)
        # SA 操作审计流
        cond, params = ["1=1"], []
        if tenant:
            cond.append("tenant_id=?"); params.append(tenant)
        if actor:
            cond.append("actor=?"); params.append(actor)
        if action:
            cond.append("action LIKE ?"); params.append(f"%{action}%")
        ops = conn.execute(f"""SELECT ts, actor, actor_role, tenant_id, action, target, detail, ip, via
                               FROM mt_sa_audit_log WHERE {' AND '.join(cond)}
                               ORDER BY id DESC LIMIT 50""", params).fetchall()
        total_ops = conn.execute(f"SELECT COUNT(*) FROM mt_sa_audit_log WHERE {' AND '.join(cond)}",
                                 params).fetchone()[0]
        # 工具调用 (保留旧仪表)
        rows = conn.execute("""SELECT tool, ok, substr(result_summary,1,80), duration_ms, created_at
                               FROM chat_tool_calls ORDER BY id DESC LIMIT 20""").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM chat_tool_calls").fetchone()[0]
        conn.close()
        return jsonify({'success': True, 'total': total, 'recent': [
            {'tool': r[0], 'ok': bool(r[1]), 'summary': r[2], 'ms': r[3], 'at': r[4]}
            for r in rows],
            'ops_total': total_ops, 'ops': [
            {'ts': r[0], 'actor': r[1], 'role': r[2], 'tenant': r[3], 'action': r[4],
             'target': r[5], 'detail': r[6], 'ip': r[7], 'via': r[8]} for r in ops]})
    except Exception as ex:
        return jsonify({'success': False, 'error': str(ex)[:150], 'recent': [], 'ops': []})


# ────────────── SSE 流式聊天 (TOOLCHAT-008) ──────────────

@sa_prime_bp.route('/api/sa-prime/chat/stream', methods=['POST'])
@sa_required
def api_chat_stream():
    """SA 流式聊天: SSE round/delta/tool_start/tool_done/done
    delta 临时输出 — 该轮触发工具时前端收到 tool_start 清空缓冲"""
    d = request.get_json(silent=True) or {}
    msg = (d.get('message') or '').strip()
    if not msg:
        return jsonify({'success': False, 'error': 'message 为空'}), 400
    sid = (d.get('session_id') or '').strip() or f"sap_{datetime.now().strftime('%Y%m%d%H%M%S')}_{_uid()[:8]}"
    model = (d.get('model') or 'qwen2.5:14b-q5_K_M').strip()
    # SSE 生成器在请求上下文外执行 — 身份在此解析, 闭包传值
    sa = _current_sa()
    stream_uid = sa.get('user_id') or 'sa'
    stream_username = sa.get('username', 'SA')

    def gen():
        import queue
        import threading
        q = queue.Queue()

        # 会话 + 历史
        try:
            conn = _db()
            row = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
            if not row:
                conn.execute("""INSERT INTO chat_sessions(session_id,user_id,username,title,created_at,updated_at,message_count)
                                VALUES(?,?,?,?,datetime('now','localtime'),datetime('now','localtime'),0)""",
                             (sid, stream_uid, stream_username, msg[:40]))
                conn.commit()
            history = [{'role': r, 'content': c} for r, c in
                       conn.execute("SELECT role, content FROM chat_messages WHERE session_id=? "
                                    "ORDER BY id DESC LIMIT 12", (sid,)).fetchall()][::-1]
            conn.close()
        except Exception:
            history = []

        def worker():
            try:
                from engines.chat_toolbox import run_tool_loop
                r = run_tool_loop(model=model, system_prompt='你是 MTSCOS SA 指挥官助手, 全能力可用。',
                                  user_text=msg, history=history, session_id=sid, user_id=stream_uid,
                                  host='127.0.0.1:11434', num_predict=16384,
                                  on_event=lambda ev: q.put(ev))
                q.put({'type': '_result', 'r': r})
            except Exception as ex:
                q.put({'type': '_result', 'r': {'answer': f'⚠️ {str(ex)[:120]}', 'tool_calls': [], 'rounds': 0}})

        threading.Thread(target=worker, daemon=True).start()
        yield f"data: {json.dumps({'type': 'session', 'session_id': sid, 'model': model})}\n\n"
        result = None
        while True:
            try:
                ev = q.get(timeout=900)
            except Exception:
                yield f"data: {json.dumps({'type': 'error', 'error': '超时'})}\n\n"
                break
            if ev.get('type') == '_result':
                result = ev['r']
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

        if result is None:
            return
        answer = result.get('answer', '')
        if result.get('tool_calls'):
            tl = "\n".join(f"🔧 {t['tool']} → {'✅' if t['ok'] else '❌'} {t['summary'][:60]}"
                           for t in result['tool_calls'])
            answer = f"{tl}\n\n{answer}"
        # 持久化 (先于 done, 拿 assistant 消息 id 供反馈)
        msg_id = None
        try:
            conn = _db()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("INSERT INTO chat_messages(session_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
                         (sid, stream_uid, 'user', msg, now))
            cur = conn.execute("INSERT INTO chat_messages(session_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
                               (sid, stream_uid, 'assistant', answer, now))
            msg_id = cur.lastrowid
            conn.execute("""UPDATE chat_sessions SET updated_at=?,
                            message_count=(SELECT COUNT(*) FROM chat_messages WHERE session_id=?),
                            last_message=? WHERE session_id=?""", (now, sid, answer[:80], sid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        yield f"data: {json.dumps({'type': 'done', 'answer': answer, 'session_id': sid, 'rounds': result.get('rounds', 0), 'message_id': msg_id}, ensure_ascii=False)}\n\n"

    from flask import Response
    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
