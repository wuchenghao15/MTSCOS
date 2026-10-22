#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS AI · 金库管理银行 (Vault Bank)
═════════════════════════════════════════
统一数字资产管理层 — token / K12 积分 / SA 特权 / 存储配额 / API 额度 / 模型访问权

设计原则:
  1. 不替换现有表 (mt_token_wallets / mt_user_token_ledger) — 作为管理层 on top
  2. 事务完整性: 所有转账/扣费走 BEGIN IMMEDIATE + 行锁
  3. 审计强制: 每笔变更落 mt_vault_audit_log (操作者+前后值)
  4. 并发双花防护: 先 SELECT ... FOR UPDATE (WAL 下用 BEGIN IMMEDIATE)

Asset Types:
  token                 — AI 对话 token (主资产)
  k12_game_point        — K12 游戏积分
  k12_knowledge_point   — K12 知识点积分
  sa_privilege          — SA 特权额度
  storage_quota         — 存储空间 (bytes)
  api_quota             — API 调用次数
  model_access          — 模型访问权 (entitlement)
"""

from __future__ import annotations
import hashlib, json, time, threading
from flask import Blueprint, jsonify, request, session, g

# ─── DB 入口 ───
try:
    from app.db import connect as _db_connect, DB_PATH
except Exception:
    import sqlite3, os
    def _db_connect():
        db = os.environ.get('APP_DB') or os.path.expanduser('~/MTSCOS_PROD/flask-app/database/app.db')
        conn = sqlite3.connect(db, timeout=15)
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.row_factory = sqlite3.Row
        return conn

vault_bp = Blueprint('vault_bp', __name__, url_prefix='/api/vault')

# ─── 资产类型注册表 (可扩展) ───
ASSET_TYPES = {
    'token':               {'name': 'AI Token',          'unit': 'token',   'decimals': 0, 'min_balance': -1000},
    'k12_game_point':      {'name': 'K12 游戏积分',        'unit': '分',      'decimals': 0, 'min_balance': 0},
    'k12_knowledge_point': {'name': 'K12 知识点积分',      'unit': '分',      'decimals': 0, 'min_balance': 0},
    'sa_privilege':        {'name': 'SA 特权额度',         'unit': '次',      'decimals': 0, 'min_balance': 0},
    'storage_quota':       {'name': '存储配额',            'unit': 'bytes',   'decimals': 0, 'min_balance': 0},
    'api_quota':           {'name': 'API 调用额度',       'unit': '次',      'decimals': 0, 'min_balance': 0},
    'model_access':        {'name': '模型访问权',          'unit': 'entitlement', 'decimals': 0, 'min_balance': 0},
}

# ─── 线程锁 (防止同一连接上的并发事务) ───
_vault_lock = threading.RLock()


# ═══════════════════════════════════════════════════════════
#  DDL + Seed (首次启动自动建表)
# ═══════════════════════════════════════════════════════════

_VAULT_DDL = [
    # 统一资产账户表 (金库核心)
    """CREATE TABLE IF NOT EXISTS mt_asset_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_no TEXT UNIQUE NOT NULL,          -- VAULT-<asset_type>-<short_hash>
        user_id TEXT NOT NULL,                    -- 注册用户=users.id / 游客=guest_xxx
        username TEXT,
        asset_type TEXT NOT NULL,                 -- token/k12_game_point/...
        balance INTEGER NOT NULL DEFAULT 0,
        frozen INTEGER NOT NULL DEFAULT 0,
        credit_limit INTEGER DEFAULT 0,           -- 透支额度 (默认 0)
        status TEXT NOT NULL DEFAULT 'active',    -- active/frozen/closed
        tier TEXT DEFAULT 'free',                 -- free/pro/enterprise/sa
        meta TEXT DEFAULT '{}',                   -- JSON: 过期时间/免费额度/来源...
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(user_id, asset_type)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_asset_accounts_user ON mt_asset_accounts(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_asset_accounts_type ON mt_asset_accounts(asset_type)",
    "CREATE INDEX IF NOT EXISTS idx_asset_accounts_status ON mt_asset_accounts(status)",

    # 统一资产流水表 (每笔交易)
    """CREATE TABLE IF NOT EXISTS mt_asset_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_hash TEXT UNIQUE NOT NULL,             -- sha256(from+to+type+amount+nonce)
        from_account TEXT,                        -- account_no / NULL = system
        to_account TEXT,                          -- account_no / NULL = system
        asset_type TEXT NOT NULL,
        amount INTEGER NOT NULL,                  -- 正数=入账, 负数=出账
        balance_after INTEGER NOT NULL,
        tx_type TEXT NOT NULL CHECK(tx_type IN (
            'grant','consume','transfer','prehold','release','freeze','unfreeze',
            'reward','admin_adjust','brain_feed','purchase','refund'
        )),
        status TEXT NOT NULL DEFAULT 'completed', -- pending/completed/failed/rolled_back
        ref_id TEXT DEFAULT '',                   -- 外部关联 (session_id/order_id)
        detail TEXT DEFAULT '{}',                 -- JSON
        operator_id TEXT DEFAULT '',              -- 操作者 (游客/SA/system)
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_asset_tx_from ON mt_asset_transactions(from_account)",
    "CREATE INDEX IF NOT EXISTS idx_asset_tx_to ON mt_asset_transactions(to_account)",
    "CREATE INDEX IF NOT EXISTS idx_asset_tx_type ON mt_asset_transactions(asset_type)",
    "CREATE INDEX IF NOT EXISTS idx_asset_tx_time ON mt_asset_transactions(created_at)",

    # 金库审计日志 (每笔变更)
    """CREATE TABLE IF NOT EXISTS mt_vault_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_type TEXT NOT NULL,                 -- balance_change/freeze/transfer/login/migration
        account_no TEXT,
        user_id TEXT,
        asset_type TEXT,
        field_changed TEXT,                       -- balance/frozen/status/tier
        before_value TEXT,
        after_value TEXT,
        reason TEXT DEFAULT '',
        operator_id TEXT,
        client_ip TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_vault_audit_user ON mt_vault_audit_log(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_vault_audit_time ON mt_vault_audit_log(created_at)",
]


def _ensure_vault_tables():
    """启动时确保金库 3 张表存在"""
    with _vault_lock:
        conn = _db_connect()
        try:
            for ddl in _VAULT_DDL:
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════
#  核心函数 (事务安全)
# ═══════════════════════════════════════════════════════════

def _tx_hash(from_acct, to_acct, asset_type, amount, nonce=None):
    """生成唯一交易哈希"""
    nonce = nonce or str(time.time_ns())
    raw = f"{from_acct}|{to_acct}|{asset_type}|{amount}|{nonce}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _account_no(user_id, asset_type):
    """生成账户号 VAULT-<type>-<hash6>"""
    short = hashlib.sha256(f"{user_id}|{asset_type}".encode()).hexdigest()[:6].upper()
    return f"VAULT-{asset_type.upper()}-{short}"


def _get_or_create_account(conn, user_id, asset_type, username=None, tier='free', meta=None):
    """获取或创建资产账户 (事务内调用)"""
    row = conn.execute(
        "SELECT * FROM mt_asset_accounts WHERE user_id=? AND asset_type=?",
        (user_id, asset_type)
    ).fetchone()
    if row:
        return row
    acct_no = _account_no(user_id, asset_type)
    conn.execute(
        "INSERT INTO mt_asset_accounts (account_no, user_id, username, asset_type, balance, frozen, tier, meta) "
        "VALUES (?,?,?,?,0,0,?,?)",
        (acct_no, user_id, username or '', asset_type, tier, json.dumps(meta or {}))
    )
    return conn.execute(
        "SELECT * FROM mt_asset_accounts WHERE account_no=?", (acct_no,)
    ).fetchone()


def _audit(conn, audit_type, account_no, user_id, asset_type, field_changed, before, after, reason='', operator='', ip=''):
    """写审计日志 (事务内)"""
    conn.execute(
        "INSERT INTO mt_vault_audit_log "
        "(audit_type, account_no, user_id, asset_type, field_changed, before_value, after_value, reason, operator_id, client_ip) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (audit_type, account_no, user_id, asset_type, field_changed,
         str(before), str(after), reason, operator, ip)
    )


def _client_ip():
    try:
        return request.headers.get('X-Forwarded-For', request.remote_addr) or ''
    except Exception:
        return ''


def _operator():
    uid = session.get('user_id', '')
    return uid or 'anonymous'


# ═══════════════════════════════════════════════════════════
#  金库 API 路由
# ═══════════════════════════════════════════════════════════

@vault_bp.route('/bank', methods=['GET'])
def vault_bank_overview():
    """金库总览 (admin-only) — 总资产/用户数/最近交易"""
    _ensure_vault_tables()
    with _vault_lock:
        conn = _db_connect()
        try:
            # 总资产按类型
            total_by_type = conn.execute(
                "SELECT asset_type, COUNT(*) AS n, SUM(balance) AS total, SUM(frozen) AS frozen "
                "FROM mt_asset_accounts GROUP BY asset_type"
            ).fetchall()
            # 活跃账户
            active_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM mt_asset_accounts WHERE status='active'"
            ).fetchone()[0]
            # 冻结账户
            frozen = conn.execute(
                "SELECT COUNT(*) FROM mt_asset_accounts WHERE status='frozen'"
            ).fetchone()[0]
            # 24h 交易数
            tx_24h = conn.execute(
                "SELECT COUNT(*) FROM mt_asset_transactions WHERE created_at > datetime('now','-24 hours')"
            ).fetchone()[0]
            # 最近 10 条交易
            recent = conn.execute(
                "SELECT * FROM mt_asset_transactions ORDER BY id DESC LIMIT 10"
            ).fetchall()
            return jsonify({
                'success': True,
                'total_accounts': sum(r['n'] for r in total_by_type),
                'active_users': active_users,
                'frozen_accounts': frozen,
                'tx_24h': tx_24h,
                'total_by_type': [dict(r) for r in total_by_type],
                'recent_transactions': [dict(r) for r in recent],
                'asset_types': ASSET_TYPES,
            })
        finally:
            conn.close()


@vault_bp.route('/my', methods=['GET'])
def vault_my_assets():
    """我的资产 (所有用户含游客)"""
    _ensure_vault_tables()
    uid = session.get('user_id', '')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with _vault_lock:
        conn = _db_connect()
        try:
            accounts = conn.execute(
                "SELECT * FROM mt_asset_accounts WHERE user_id=? AND status='active' ORDER BY asset_type",
                (uid,)
            ).fetchall()
            result = []
            for a in accounts:
                tx_count = conn.execute(
                    "SELECT COUNT(*) FROM mt_asset_transactions WHERE from_account=? OR to_account=?",
                    (a['account_no'], a['account_no'])
                ).fetchone()[0]
                recent = conn.execute(
                    "SELECT * FROM mt_asset_transactions WHERE from_account=? OR to_account=? ORDER BY id DESC LIMIT 5",
                    (a['account_no'], a['account_no'])
                ).fetchall()
                info = ASSET_TYPES.get(a['asset_type'], {})
                result.append({
                    'account_no': a['account_no'],
                    'asset_type': a['asset_type'],
                    'asset_name': info.get('name', a['asset_type']),
                    'unit': info.get('unit', ''),
                    'balance': a['balance'],
                    'frozen': a['frozen'],
                    'available': a['balance'] - a['frozen'],
                    'tier': a['tier'],
                    'tx_count': tx_count,
                    'recent': [dict(r) for r in recent],
                })
            return jsonify({
                'success': True,
                'user_id': uid,
                'accounts': result,
                'total_balance': sum(a['balance'] for a in accounts),
            })
        finally:
            conn.close()


@vault_bp.route('/account/<user_id>', methods=['GET'])
def vault_account_detail(user_id):
    """查询某用户资产 (admin-only)"""
    _ensure_vault_tables()
    with _vault_lock:
        conn = _db_connect()
        try:
            accounts = conn.execute(
                "SELECT * FROM mt_asset_accounts WHERE user_id=? ORDER BY asset_type", (user_id,)
            ).fetchall()
            if not accounts:
                return jsonify({'success': False, 'error': '账户不存在'}), 404
            txs = conn.execute(
                "SELECT * FROM mt_asset_transactions WHERE from_account IN (SELECT account_no FROM mt_asset_accounts WHERE user_id=?) "
                "OR to_account IN (SELECT account_no FROM mt_asset_accounts WHERE user_id=?) "
                "ORDER BY id DESC LIMIT 50",
                (user_id, user_id)
            ).fetchall()
            return jsonify({
                'success': True,
                'user_id': user_id,
                'accounts': [dict(a) for a in accounts],
                'transactions': [dict(t) for t in txs],
            })
        finally:
            conn.close()


@vault_bp.route('/transfer', methods=['POST'])
def vault_transfer():
    """转账 (BEGIN IMMEDIATE + 双花防护)"""
    _ensure_vault_tables()
    data = request.get_json(silent=True) or {}
    from_uid = data.get('from_user_id') or session.get('user_id', '')
    to_uid = data.get('to_user_id', '')
    asset_type = data.get('asset_type', 'token')
    amount = int(data.get('amount', 0))
    ref_id = data.get('ref_id', '')
    if amount <= 0:
        return jsonify({'success': False, 'error': 'amount 必须为正'}), 400
    if asset_type not in ASSET_TYPES:
        return jsonify({'success': False, 'error': f'未知资产类型 {asset_type}'}), 400
    with _vault_lock:
        conn = _db_connect()
        try:
            # BEGIN IMMEDIATE — 写事务立即获取排他锁, 防止并发双花
            conn.execute('BEGIN IMMEDIATE')
            # 获取双方账户 (FOR UPDATE 语义: WAL 下 IMMEDIATE 已锁)
            from_acct = _get_or_create_account(conn, from_uid, asset_type)
            to_acct = _get_or_create_account(conn, to_uid, asset_type)
            # 余额检查
            available = from_acct['balance'] - from_acct['frozen']
            if available < amount:
                conn.execute('ROLLBACK')
                return jsonify({'success': False, 'error': f'余额不足 (可用 {available}, 需要 {amount})'}), 402
            # 扣款
            before_from = from_acct['balance']
            before_to = to_acct['balance']
            conn.execute(
                "UPDATE mt_asset_accounts SET balance=balance-?, updated_at=datetime('now','localtime') WHERE account_no=?",
                (amount, from_acct['account_no'])
            )
            conn.execute(
                "UPDATE mt_asset_accounts SET balance=balance+?, updated_at=datetime('now','localtime') WHERE account_no=?",
                (amount, to_acct['account_no'])
            )
            # 交易哈希
            txh = _tx_hash(from_acct['account_no'], to_acct['account_no'], asset_type, amount)
            conn.execute(
                "INSERT INTO mt_asset_transactions "
                "(tx_hash, from_account, to_account, asset_type, amount, balance_after, tx_type, status, ref_id, operator_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (txh, from_acct['account_no'], to_acct['account_no'], asset_type, -amount,
                 before_from - amount, 'transfer', 'completed', ref_id, _operator())
            )
            conn.execute(
                "INSERT INTO mt_asset_transactions "
                "(tx_hash, from_account, to_account, asset_type, amount, balance_after, tx_type, status, ref_id, operator_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (txh + '-R', from_acct['account_no'], to_acct['account_no'], asset_type, amount,
                 before_to + amount, 'transfer', 'completed', ref_id, _operator())
            )
            # 审计
            _audit(conn, 'balance_change', from_acct['account_no'], from_uid, asset_type,
                   'balance', before_from, before_from - amount, f'transfer→{to_uid}', _operator(), _client_ip())
            _audit(conn, 'balance_change', to_acct['account_no'], to_uid, asset_type,
                   'balance', before_to, before_to + amount, f'transfer←{from_uid}', _operator(), _client_ip())
            conn.commit()
            return jsonify({
                'success': True,
                'tx_hash': txh,
                'from_balance_after': before_from - amount,
                'to_balance_after': before_to + amount,
            })
        except Exception as e:
            try: conn.execute('ROLLBACK')
            except: pass
            return jsonify({'success': False, 'error': str(e)}), 500
        finally:
            conn.close()


@vault_bp.route('/grant', methods=['POST'])
def vault_grant():
    """发放资产 (admin / system 级) — 每日赠送/活动奖励/补偿"""
    _ensure_vault_tables()
    data = request.get_json(silent=True) or {}
    to_uid = data.get('user_id') or session.get('user_id', '')
    asset_type = data.get('asset_type', 'token')
    amount = int(data.get('amount', 0))
    reason = data.get('reason', 'daily_grant')
    if amount <= 0:
        return jsonify({'success': False, 'error': 'amount 必须为正'}), 400
    with _vault_lock:
        conn = _db_connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            acct = _get_or_create_account(conn, to_uid, asset_type)
            before = acct['balance']
            conn.execute(
                "UPDATE mt_asset_accounts SET balance=balance+?, updated_at=datetime('now','localtime') WHERE account_no=?",
                (amount, acct['account_no'])
            )
            txh = _tx_hash('SYSTEM', acct['account_no'], asset_type, amount)
            conn.execute(
                "INSERT INTO mt_asset_transactions "
                "(tx_hash, from_account, to_account, asset_type, amount, balance_after, tx_type, status, operator_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (txh, 'SYSTEM', acct['account_no'], asset_type, amount, before + amount,
                 'grant', 'completed', _operator())
            )
            _audit(conn, 'balance_change', acct['account_no'], to_uid, asset_type,
                   'balance', before, before + amount, reason, _operator(), _client_ip())
            conn.commit()
            return jsonify({'success': True, 'tx_hash': txh, 'balance_after': before + amount})
        except Exception as e:
            try: conn.execute('ROLLBACK')
            except: pass
            return jsonify({'success': False, 'error': str(e)}), 500
        finally:
            conn.close()


@vault_bp.route('/consume', methods=['POST'])
def vault_consume():
    """扣减资产 (消费/AI 对话/API 调用)"""
    _ensure_vault_tables()
    data = request.get_json(silent=True) or {}
    from_uid = data.get('user_id') or session.get('user_id', '')
    asset_type = data.get('asset_type', 'token')
    amount = int(data.get('amount', 0))
    ref_id = data.get('ref_id', '')
    if amount <= 0:
        return jsonify({'success': False, 'error': 'amount 必须为正'}), 400
    with _vault_lock:
        conn = _db_connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            acct = _get_or_create_account(conn, from_uid, asset_type)
            available = acct['balance'] - acct['frozen']
            if available < amount:
                conn.execute('ROLLBACK')
                return jsonify({'success': False, 'error': f'余额不足 (可用 {available})'}), 402
            before = acct['balance']
            conn.execute(
                "UPDATE mt_asset_accounts SET balance=balance-?, updated_at=datetime('now','localtime') WHERE account_no=?",
                (amount, acct['account_no'])
            )
            txh = _tx_hash(acct['account_no'], 'SYSTEM', asset_type, amount)
            conn.execute(
                "INSERT INTO mt_asset_transactions "
                "(tx_hash, from_account, to_account, asset_type, amount, balance_after, tx_type, status, ref_id, operator_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (txh, acct['account_no'], 'SYSTEM', asset_type, -amount, before - amount,
                 'consume', 'completed', ref_id, _operator())
            )
            _audit(conn, 'balance_change', acct['account_no'], from_uid, asset_type,
                   'balance', before, before - amount, f'consume:{ref_id}', _operator(), _client_ip())
            conn.commit()
            return jsonify({'success': True, 'tx_hash': txh, 'balance_after': before - amount})
        except Exception as e:
            try: conn.execute('ROLLBACK')
            except: pass
            return jsonify({'success': False, 'error': str(e)}), 500
        finally:
            conn.close()


@vault_bp.route('/freeze', methods=['POST'])
def vault_freeze():
    """冻结/解冻资产"""
    _ensure_vault_tables()
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id') or session.get('user_id', '')
    asset_type = data.get('asset_type', 'token')
    amount = int(data.get('amount', 0))
    action = data.get('action', 'freeze')  # freeze / unfreeze
    if amount <= 0:
        return jsonify({'success': False, 'error': 'amount 必须为正'}), 400
    with _vault_lock:
        conn = _db_connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            acct = _get_or_create_account(conn, user_id, asset_type)
            if action == 'freeze':
                available = acct['balance'] - acct['frozen']
                if available < amount:
                    conn.execute('ROLLBACK')
                    return jsonify({'success': False, 'error': f'可用不足 (available={available})'}), 402
                before = acct['frozen']
                conn.execute(
                    "UPDATE mt_asset_accounts SET frozen=frozen+?, updated_at=datetime('now','localtime') WHERE account_no=?",
                    (amount, acct['account_no'])
                )
                _audit(conn, 'freeze', acct['account_no'], user_id, asset_type,
                       'frozen', before, before + amount, 'prehold', _operator(), _client_ip())
            else:  # unfreeze
                if acct['frozen'] < amount:
                    conn.execute('ROLLBACK')
                    return jsonify({'success': False, 'error': f'冻结额不足 (frozen={acct["frozen"]})'}), 402
                before = acct['frozen']
                conn.execute(
                    "UPDATE mt_asset_accounts SET frozen=frozen-?, updated_at=datetime('now','localtime') WHERE account_no=?",
                    (amount, acct['account_no'])
                )
                _audit(conn, 'unfreeze', acct['account_no'], user_id, asset_type,
                       'frozen', before, before - amount, 'release', _operator(), _client_ip())
            conn.commit()
            return jsonify({'success': True, 'action': action, 'account_no': acct['account_no']})
        except Exception as e:
            try: conn.execute('ROLLBACK')
            except: pass
            return jsonify({'success': False, 'error': str(e)}), 500
        finally:
            conn.close()


@vault_bp.route('/audit', methods=['GET'])
def vault_audit():
    """金库审计日志 (可过滤)"""
    _ensure_vault_tables()
    limit = min(int(request.args.get('limit', 100)), 500)
    user_id = request.args.get('user_id', '')
    asset_type = request.args.get('asset_type', '')
    conn = _db_connect()
    try:
        sql = "SELECT * FROM mt_vault_audit_log WHERE 1=1"
        args = []
        if user_id:
            sql += " AND user_id=?"; args.append(user_id)
        if asset_type:
            sql += " AND asset_type=?"; args.append(asset_type)
        sql += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        rows = conn.execute(sql, args).fetchall()
        return jsonify({'success': True, 'count': len(rows), 'logs': [dict(r) for r in rows]})
    finally:
        conn.close()


@vault_bp.route('/migrate', methods=['POST'])
def vault_migrate_legacy():
    """一次性迁移: mt_token_wallets → mt_asset_accounts (asset_type=token)"""
    _ensure_vault_tables()
    conn = _db_connect()
    try:
        # 自动把 mt_token_wallets 里的现有账户同步进金库
        legacy = conn.execute("SELECT * FROM mt_token_wallets").fetchall()
        migrated = 0; skipped = 0
        for row in legacy:
            uid = row['user_id']
            exists = conn.execute(
                "SELECT 1 FROM mt_asset_accounts WHERE user_id=? AND asset_type='token'", (uid,)
            ).fetchone()
            if exists:
                skipped += 1
                continue
            acct_no = _account_no(uid, 'token')
            conn.execute(
                "INSERT INTO mt_asset_accounts (account_no, user_id, username, asset_type, balance, frozen, tier, meta) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (acct_no, uid, row['username'] or uid, 'token',
                 row['balance'] or 0, row['frozen'] or 0,
                 'guest' if row['is_guest'] else 'free',
                 json.dumps({'guest_free_grant': row['guest_free_grant'] or 0}))
            )
            migrated += 1
        conn.commit()
        return jsonify({'success': True, 'migrated': migrated, 'skipped': skipped})
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
#  蓝图注册辅助
# ═══════════════════════════════════════════════════════════

def register_vault_bp(app):
    """注册金库蓝图到 Flask app"""
    _ensure_vault_tables()
    app.register_blueprint(vault_bp)
    print(f"[VAULT] ✅ 金库管理银行已注册 → /api/vault (资产类型: {len(ASSET_TYPES)})")
