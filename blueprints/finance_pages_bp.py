#!/usr/bin/env python3
"""古灵阁多页面架构 — 总 Dashboard + 7 个渠道详情页 + 3 个治理层详情页

P0: 所有查询完全非阻塞 —— daemon 持有 SQLite 写锁时允许 graceful-degrade,
    让页面先能渲染 (空数据) 而不是 timeout 或 500.
"""
from flask import Blueprint, render_template, request, jsonify
import sqlite3, json, os, datetime

bp = Blueprint('finance_pages', __name__, url_prefix='/governance')
DB = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')

# 极短 timeout: 1s, busy_timeout 关闭 —— 被锁立即返回, 不阻塞请求
def _c():
    c = sqlite3.connect(DB, timeout=1)
    c.row_factory = sqlite3.Row
    try: c.execute('PRAGMA busy_timeout=0')  # 不等待, 立即返回
    except: pass
    return c

def _safe_query(conn, sql, args=()):
    """安全查询 — 任何错误返回空列表, 绝不阻塞"""
    try:
        return conn.execute(sql, args).fetchall()
    except Exception:
        return []

def _safe_query_one(conn, sql, args=()):
    """安全查询单行 — 任何错误返回 None"""
    try:
        return conn.execute(sql, args).fetchone()
    except Exception:
        return None

# 非阻塞建表 —— 被锁立即 pass, 下次请求再试
_INIT_SQL = [
    "CREATE TABLE IF NOT EXISTS mt_live_fund_position (id INTEGER PRIMARY KEY AUTOINCREMENT, fund_code TEXT, fund_name TEXT, price REAL DEFAULT 0, qty REAL DEFAULT 0, pnl REAL DEFAULT 0, today_pnl REAL DEFAULT 0, prev_close REAL DEFAULT 0, updated_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_live_bank_product (id INTEGER PRIMARY KEY AUTOINCREMENT, product_code TEXT, product_name TEXT, bank TEXT, amount REAL DEFAULT 0, expected_return REAL DEFAULT 0, term_type TEXT DEFAULT 'T+1', status TEXT DEFAULT 'ACTIVE', updated_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_live_term_deposit (id INTEGER PRIMARY KEY AUTOINCREMENT, deposit_code TEXT, bank TEXT, amount REAL DEFAULT 0, rate REAL DEFAULT 0, term_months INTEGER DEFAULT 12, maturity_date TEXT, status TEXT DEFAULT 'ACTIVE', updated_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_live_metal_position (id INTEGER PRIMARY KEY AUTOINCREMENT, metal_name TEXT, metal_type TEXT, price REAL DEFAULT 0, qty REAL DEFAULT 0, pnl REAL DEFAULT 0, today_pnl REAL DEFAULT 0, prev_close REAL DEFAULT 0, unit TEXT DEFAULT 'g', updated_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_live_business_inv (id INTEGER PRIMARY KEY AUTOINCREMENT, inv_code TEXT, inv_name TEXT, inv_type TEXT, amount REAL DEFAULT 0, equity_pct REAL DEFAULT 0, expected_irr REAL DEFAULT 0, status TEXT DEFAULT 'ACTIVE', updated_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_live_insurance (id INTEGER PRIMARY KEY AUTOINCREMENT, policy_code TEXT, policy_name TEXT, insurer TEXT, premium REAL DEFAULT 0, coverage REAL DEFAULT 0, policy_type TEXT, status TEXT DEFAULT 'ACTIVE', updated_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_center_registry (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT, description TEXT, layer TEXT DEFAULT 'L2', status TEXT DEFAULT 'ACTIVE', created_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_task_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, task_type TEXT, from_center TEXT, to_center TEXT, status TEXT DEFAULT 'PENDING', payload TEXT, created_at TEXT DEFAULT (datetime('now','localtime')), updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS mt_center_exec_log (id INTEGER PRIMARY KEY AUTOINCREMENT, center_code TEXT, action TEXT, detail TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_meeting_log (id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT UNIQUE, title TEXT, meeting_type TEXT, convener TEXT, recorder TEXT, status TEXT DEFAULT 'APPROVED', agenda TEXT, minutes TEXT, archive_path TEXT, recorded_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS mt_investment_proposal (id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_type TEXT, channel TEXT, proposer TEXT, amount REAL, target_price REAL, expected_return REAL, rationale TEXT, risk_assessment TEXT, status TEXT DEFAULT 'PENDING', created_at TEXT DEFAULT (datetime('now','localtime')), updated_at TEXT)",
]

def _ensure_tables():
    """非阻塞建表 —— 被锁立即跳过, 绝不阻塞请求"""
    try:
        c = sqlite3.connect(DB, timeout=1)
        try: c.execute('PRAGMA busy_timeout=0')
        except: pass
        for sql in _INIT_SQL:
            try: c.execute(sql)
            except: pass
        c.commit(); c.close()
    except Exception:
        pass  # 被锁就跳过

CHANNEL_CONFIG = {
    'stock':    {'title': '📈 A股股票',          'table': 'mt_live_position',        'pnl_col': 'pnl',   'today_col': 'today_pnl', 'price_col': 'price',   'qty_col': 'qty',   'name_col': 'name'},
    'fund':     {'title': '📊 基金',             'table': 'mt_live_fund_position',   'pnl_col': 'pnl',   'today_col': 'today_pnl', 'price_col': 'price',   'qty_col': 'qty',   'name_col': 'fund_name'},
    'bank':     {'title': '🏦 银行理财 (T+1/T+5)', 'table': 'mt_live_bank_product', 'pnl_col': None,    'today_col': None,         'price_col': None,      'qty_col': None,    'name_col': 'product_name'},
    'deposit':  {'title': '📅 定期存款',         'table': 'mt_live_term_deposit',    'pnl_col': None,    'today_col': None,         'price_col': None,      'qty_col': None,    'name_col': 'bank'},
    'metal':    {'title': '🥇 稀有金属 (黄金/白银)', 'table': 'mt_live_metal_position','pnl_col': 'pnl', 'today_col': 'today_pnl',  'price_col': 'price',   'qty_col': 'qty',   'name_col': 'metal_name'},
    'business': {'title': '🏢 商业投资 (私募/股权)', 'table': 'mt_live_business_inv','pnl_col': None,    'today_col': None,         'price_col': None,      'qty_col': None,    'name_col': 'inv_name'},
    'insurance':{'title': '🛡️ 财险/分红险',      'table': 'mt_live_insurance',       'pnl_col': None,    'today_col': None,         'price_col': None,      'qty_col': None,    'name_col': 'policy_name'},
}

# ── 渠道详情页 ──
# ⚠️ v26.11 已由 server_real_db.py 的 Gobelin 版本接管 (含 etf/bond 等 7 渠道)
# 此处注释掉避免路由冲突 (finance_pages_bp 旧版 CHANNEL_CONFIG 无 etf/bond)
# @bp.route('/channel/<channel_code>')
def _channel_detail_DISABLED(channel_code):
    _ensure_tables()
    cfg = CHANNEL_CONFIG.get(channel_code)
    if not cfg:
        return "404 channel", 404
    conn = _c()
    rows = _safe_query(conn, f"SELECT * FROM {cfg['table']} ORDER BY rowid")
    acc = _safe_query_one(conn, "SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1")

    today_pnl = 0; prev_pnl = 0; total_pnl = 0; mv = 0
    for r in rows:
        if cfg['today_col']:
            try: today_pnl += float(r['today_pnl'] or 0)
            except: pass
        if cfg['pnl_col']:
            try: total_pnl += float(r['pnl'] or 0)
            except: pass
        if cfg['price_col'] and cfg['qty_col']:
            try: mv += float(r['price'] or 0) * float(r['qty'] or 0)
            except: pass

    all_meetings = _safe_query(conn, "SELECT * FROM mt_meeting_log ORDER BY recorded_at DESC LIMIT 5")
    proposals = _safe_query(conn, "SELECT * FROM mt_investment_proposal ORDER BY created_at DESC LIMIT 5")
    exec_log = _safe_query(conn, "SELECT * FROM mt_center_exec_log ORDER BY created_at DESC LIMIT 15")
    conn.close()

    return render_template('channel_detail.html',
        cfg=cfg, rows=rows, acc=acc,
        today_pnl=today_pnl, prev_pnl=prev_pnl, total_pnl=total_pnl, mv=mv,
        meetings=all_meetings, all_meetings=all_meetings,
        proposals=proposals, exec_log=exec_log,
        channel_code=channel_code,
    )

# ── 33 中心详情页 ──
@bp.route('/centers')
def centers_detail():
    _ensure_tables()
    conn = _c()
    centers = _safe_query(conn, "SELECT * FROM mt_center_registry ORDER BY code")
    tasks = _safe_query(conn, "SELECT * FROM mt_task_queue ORDER BY created_at DESC LIMIT 50")
    execs = _safe_query(conn, "SELECT * FROM mt_center_exec_log ORDER BY created_at DESC LIMIT 100")
    conn.close()
    return render_template('centers_detail.html', centers=centers, tasks=tasks, execs=execs)

# ── 会议中心 ──
@bp.route('/meetings')
def meetings_detail():
    _ensure_tables()
    conn = _c()
    meetings = _safe_query(conn, "SELECT * FROM mt_meeting_log ORDER BY recorded_at DESC")
    conn.close()
    return render_template('meetings_detail.html', meetings=meetings)

# ── 投资提案中心 ──
@bp.route('/proposals')
def proposals_detail():
    _ensure_tables()
    conn = _c()
    proposals = _safe_query(conn, "SELECT * FROM mt_investment_proposal ORDER BY created_at DESC")
    conn.close()
    return render_template('proposals_detail.html', proposals=proposals)
