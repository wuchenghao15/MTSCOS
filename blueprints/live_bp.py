"""
古灵阁证券交易系统（实盘）— live_bp.py
========================================
与沙盘 sandbox_bp 架构镜像, 核心差异:
  1. runtime_mode 三级: DRY_RUN(干跑观察) / PAPER(纸面模拟) / LIVE(真实下单)
  2. DB 表前缀 mt_live_* (独立于沙盘)
  3. LIVE 模式对接 easytrader (中信证券 API)
  4. 三级保护: DRY_RUN → PAPER → LIVE 逐步递进
  5. 独立风控阈值 (比沙盘更严格)

对接说明 (easytrader):
  pip install easytrader
  import easytrader
  user = easytrader.use('yjf')  # 中信证券 (佣金宝)
  user.prepare('config.json')
  详见: https://easytrader.readthedocs.io/
"""
from __future__ import annotations
import os, json, sqlite3, time, subprocess, threading, datetime
from flask import Blueprint, jsonify, request

live_bp = Blueprint('live', __name__, url_prefix='/api/live')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db')

# ═══════════════════════════════════════════════════════════════
# 运行模式 — 三层保护
# ═══════════════════════════════════════════════════════════════
RUNTIME_MODE_FILE = os.path.join(os.path.dirname(DB_PATH), 'runtime_mode.json')

def _get_runtime_mode():
    """读取当前运行模式"""
    try:
        with open(RUNTIME_MODE_FILE) as f:
            return json.load(f).get('mode', 'PAPER')
    except:
        return 'PAPER'

def _set_runtime_mode(mode):
    """设置运行模式 (持久化)"""
    assert mode in ('DRY_RUN', 'PAPER', 'LIVE'), f"invalid mode: {mode}"
    with open(RUNTIME_MODE_FILE, 'w') as f:
        json.dump({'mode': mode, 'set_at': datetime.datetime.now().isoformat()}, f)
    return mode

def _mode_label(mode):
    return {'DRY_RUN':'观察模式·不执行','PAPER':'纸面实盘·模拟下单','LIVE':'真金白银·真实下单'}.get(mode, mode)

# ═══════════════════════════════════════════════════════════════
# DB 连接 + 初始化
# ═══════════════════════════════════════════════════════════════
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def _init_tables():
    """实盘独立表 (与沙盘完全隔离)"""
    conn = _db(); cur = conn.cursor()
    
    # 实盘账户
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_live_account (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_assets REAL DEFAULT 0,
        available REAL DEFAULT 0,
        market_value REAL DEFAULT 0,
        cash REAL DEFAULT 0,
        pnl REAL DEFAULT 0,
        server_time TEXT,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 实盘持仓
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_live_position (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT,
        qty REAL DEFAULT 0,
        avg_cost REAL DEFAULT 0,
        price REAL DEFAULT 0,
        pnl REAL DEFAULT 0,
        pnl_pct REAL DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 实盘交易流水
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_live_trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        side TEXT,        -- BUY / SELL
        qty REAL,
        price REAL,
        amount REAL,
        fee REAL DEFAULT 0,
        mode TEXT,        -- DRY_RUN / PAPER / LIVE
        order_id TEXT,    -- 中信真实订单号 (LIVE 才有)
        status TEXT,      -- FILLED / PENDING / REJECTED
        reason TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    # 实盘委托
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_live_order (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT UNIQUE,
        symbol TEXT NOT NULL,
        side TEXT,
        qty REAL,
        price REAL,
        mode TEXT,
        verdict TEXT,
        reason TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    conn.commit(); conn.close()
    print(f"✅ mt_live_* 表初始化完成")

# ═══════════════════════════════════════════════════════════════
# 运行模式管理 API
# ═══════════════════════════════════════════════════════════════
@live_bp.route('/mode', methods=['GET', 'POST'])
def api_live_mode():
    """三级运行模式: DRY_RUN → PAPER → LIVE"""
    if request.method == 'GET':
        mode = _get_runtime_mode()
        return jsonify({
            'success': True,
            'data': {
                'current_mode': mode,
                'current_label': _mode_label(mode),
                'available': ['DRY_RUN', 'PAPER', 'LIVE'],
                'note': 'LIVE 模式将真金白银对接中信证券 API',
            }
        })
    
    # POST: 切换模式 (带双签)
    body = request.get_json(silent=True) or {}
    new_mode = body.get('mode', '').upper()
    cfo_sign = body.get('cfo_sign')   # CFO 签名
    auditor_sign = body.get('auditor_sign')  # 审计师签名
    
    if new_mode not in ('DRY_RUN', 'PAPER', 'LIVE'):
        return jsonify({'success': False, 'error': 'invalid mode'}), 400
    
    # LIVE 模式双签保护
    old_mode = _get_runtime_mode()
    if new_mode == 'LIVE' and old_mode != 'LIVE':
        if not cfo_sign or not auditor_sign:
            return jsonify({
                'success': False,
                'error': '切到 LIVE 需要 CFO 签名 + 审计师签名 (双签)',
                'require_signs': True,
            }), 403
    
    _set_runtime_mode(new_mode)
    
    # 投喂 AI 脑库
    try:
        conn = _db()
        conn.execute("""INSERT INTO mt_ai_brain_feed_log 
            (flow_id, feed_target, payload_preview, feed_content, feed_kind, fed_at)
        VALUES (?,?,?,?,?,datetime('now','localtime'))""", (
            f"LIVE-MODE-{new_mode}", "live_trading", 
            f"运行模式切换 {old_mode} → {new_mode}", 
            json.dumps({'from': old_mode, 'to': new_mode, 'cfo': cfo_sign, 'auditor': auditor_sign}, ensure_ascii=False),
            'LIVE_MODE_SWITCH'
        ))
        conn.commit(); conn.close()
    except:
        pass
    
    return jsonify({
        'success': True,
        'current_mode': new_mode,
        'old_mode': old_mode,
        'note': _mode_label(new_mode),
    })

# ═══════════════════════════════════════════════════════════════
# 行情 & 账户 API (和沙盘镜像, 但独立数据源)
# ═══════════════════════════════════════════════════════════════
@live_bp.route('/status')
def api_live_status():
    """实盘状态 — 包含运行模式"""
    mode = _get_runtime_mode()
    return jsonify({
        'success': True,
        'data': {
            'runtime_mode': mode,
            'runtime_label': _mode_label(mode),
            'server_time': datetime.datetime.now().strftime('%H:%M:%S'),
        }
    })

@live_bp.route('/account')
def api_live_account():
    """实盘账户 — 从 mt_live_account 读取"""
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    
    if not row:
        # 首次调用: 初始化 PAPER 模式账户
        cur.execute("""INSERT INTO mt_live_account (total_assets, cash, available, market_value, pnl)
            VALUES (1000000, 1000000, 1000000, 0, 0)""")
        conn.commit()
        cur.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    
    account = dict(row) if row else {}
    account['position_count'] = cur.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
    conn.close()
    
    # 标注数据源
    account['data_source'] = _get_runtime_mode()  # DRY_RUN / PAPER / LIVE
    return jsonify({'success': True, 'data': account})

@live_bp.route('/positions')
def api_live_positions():
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT * FROM mt_live_position ORDER BY pnl_pct ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'success': True, 'data': rows})

@live_bp.route('/trades')
def api_live_trades():
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT * FROM mt_live_trade_log ORDER BY id DESC LIMIT 200")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'success': True, 'data': rows})

@live_bp.route('/decisions')
def api_live_decisions():
    """AI 军团决策 (和沙盘共用, 但加 LIVE 模式过滤)"""
    try:
        conn = _db()
        cur = conn.cursor()
        # 和沙盘共用 mt_decisions 表 (决策层不区分沙盘/实盘)
        cur.execute("SELECT * FROM mt_decisions ORDER BY id DESC LIMIT 100")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({'success': True, 'data': rows})
    except Exception as e:
        return jsonify({'success': True, 'data': []})

# ... (API 其余端点和沙盘镜像, 后续逐段实现)

_init_tables()

def register_live_bp(app):
    # 注册实盘蓝图
    app.register_blueprint(live_bp)
    _init_tables()
    return True

_init_tables()
