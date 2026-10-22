#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTSCOS AI 本地聊天蓝图 — 仙女座发散思维引擎
=============================================
flow_id: CHAT_LOCAL_v22_10_20261008

功能:
  1. 本地 Ollama 大模型聊天 (qwen2.5-coder:14b / qwen2.5:7b)
  2. SSE 流式推送 (Server-Sent Events, 避开 RATE_IP_001 短轮询限流)
  3. 仙女座发散思维 prompt 增强 (冰山矩阵 + 认知画像适配)
  4. 动作记录 (每次 send/receive 永久化落库)
  5. 拐点记录 (对话方向突变/情绪转折/灵感爆发)
  6. 脑库投喂 (对话结束 → 经验蒸馏 → mt_ai_brain_feed_log)

权限: @system_container(require_auth='login') — 所有已注册用户
      guest 403, 登录即可用 (role=user/admin/super_admin 全部放行)

路由:
  GET  /local-chat          → 聊天页面 (templates/local_chat.html)
  POST /api/local-chat/send → 发送消息 + SSE 流式接收
  GET  /api/local-chat/history?session_id=xxx → 拉取历史
  POST /api/local-chat/session → 创建新会话
  GET  /api/local-chat/sessions → 我的会话列表
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from functools import wraps
from flask import Blueprint, Response, g, jsonify, request, session, stream_with_context
from app.db import DB_PATH, connect as _db  # flow_db_unify_chat_20261022 单一权威入口
_REWARD_KEY = os.environ.get('MTSCOS_REWARD_SEED', '[REDACTED]').encode()[:16]

def _crypto_mask(raw_bytes, key=_REWARD_KEY):
    """XOR + 时间盐混淆, 防直接读公式"""
    import hashlib
    salt = str(int(time.time()) % 1000).encode()
    masked = bytes(a ^ b ^ c for a, b, c in zip(raw_bytes, (key * 3)[:len(raw_bytes)], (salt * 3)[:len(raw_bytes)]))
    return hashlib.sha256(masked).hexdigest()[:32]

def _reward_formula_snapshot():
    """导出加密快照, 供前端/审计验证公式版本"""
    import hashlib
    raw = json.dumps({
        'version': 'v25.5',
        'breakthrough_per_turn': 50,
        'diverge_per_turn': 30,
        'question_per_turn': 20,
        'metaphor_per_turn': 20,
        'contradiction_per_turn': 20,
        'brain_feed_reward': 100,
        'max_daily_reward': 200,     # 每日奖励封顶 200 token (制约平衡)
        'cooldown_seconds': 60,      # 奖励冷却 60s, 防刷
        'balance_ratio_cap': 0.15,   # 奖励不得超过当前余额 15% (制约平衡)
    }, sort_keys=True).encode()
    return _crypto_mask(raw)

# ── 路径解析已上移到 app/db.py (flow_db_unify_chat_20261022) ──
# DB_PATH / _db() 全部从 app.db 导入 (见文件顶部)

chat_local_bp = Blueprint("chat_local_bp", __name__, template_folder=None)


# ════════════════════════════════════════════════════════════════
# 数据库层 (_db 已由 app.db.connect 别名)
# ════════════════════════════════════════════════════════════════


def _ensure_tables():
    """确保聊天相关表存在"""
    conn = _db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            title TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            message_count INTEGER DEFAULT 0,
            last_message TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            reasoning TEXT DEFAULT '',
            tokens INTEGER DEFAULT 0,
            model TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
        );

        CREATE TABLE IF NOT EXISTS chat_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('send','receive','stream','finish','inflection','new_session')),
            detail TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS chat_inflection_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            inflection_type TEXT NOT NULL CHECK(inflection_type IN ('diverge','converge','breakthrough','question','metaphor','contradiction')),
            trigger_text TEXT DEFAULT '',
            ai_response TEXT DEFAULT '',
            quality_score REAL DEFAULT 0.0,
            fed_to_brain INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_chat_msgs_session ON chat_messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_chat_actions_session ON chat_actions(session_id);
        CREATE INDEX IF NOT EXISTS idx_chat_infl_session ON chat_inflection_points(session_id);
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);

        /* ── Token 账户体系 (v25.5 完整版) ──
           三层计费: 模型倍率定价 + 原子预扣/实扣/退差 + 拐点/脑库奖励抵扣
           ledger type 扩展: daily_grant / consume / prehold / release / reward / brain_feed / admin_adjust */
        CREATE TABLE IF NOT EXISTS mt_user_token_accounts (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            balance INTEGER NOT NULL DEFAULT 0,
            last_grant_date TEXT DEFAULT '',
            total_granted INTEGER NOT NULL DEFAULT 0,
            total_consumed INTEGER NOT NULL DEFAULT 0,
            total_preheld INTEGER NOT NULL DEFAULT 0,    -- 当前预扣总额
            total_rewarded INTEGER NOT NULL DEFAULT 0,   -- 累计奖励抵扣
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS mt_user_token_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            change INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN (
                'daily_grant','consume','prehold','release',
                'reward','brain_feed','admin_adjust'
            )),
            session_id TEXT DEFAULT '',
            model TEXT DEFAULT '',
            detail TEXT DEFAULT '{}',
            balance_after INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_tok_ledger_user ON mt_user_token_ledger(user_id);
        CREATE INDEX IF NOT EXISTS idx_tok_ledger_time ON mt_user_token_ledger(created_at);
        CREATE INDEX IF NOT EXISTS idx_tok_ledger_session ON mt_user_token_ledger(session_id) WHERE session_id != '';

        /* ── 模型定价表 (v25.5) ── */
        CREATE TABLE IF NOT EXISTS mt_chat_model_pricing (
            model_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            model_weight REAL NOT NULL DEFAULT 1.0,  -- 倍率 (7b=1.0, 14b=2.0, coder=1.5)
            prompt_per_1k INTEGER NOT NULL DEFAULT 100,  -- 每 1000 prompt token 消耗
            completion_per_1k INTEGER NOT NULL DEFAULT 200, -- 每 1000 completion token 消耗 (生成更贵)
            is_active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        /* ── 日程助手 (flow_chat_all7_20261019): /日程 命令落库 ── */
        CREATE TABLE IF NOT EXISTS mt_chat_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            due_at TEXT DEFAULT '',
            session_id TEXT DEFAULT '',
            status TEXT DEFAULT 'open' CHECK(status IN ('open','done','cancelled')),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            done_at TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_chat_sched_user ON mt_chat_schedule(user_id);
        """)
        conn.commit()

        # ── 兼容旧表: 加新列 ──
        for col_def in [
            ("ALTER TABLE mt_user_token_accounts ADD COLUMN total_preheld INTEGER NOT NULL DEFAULT 0", "total_preheld"),
            ("ALTER TABLE mt_user_token_accounts ADD COLUMN total_rewarded INTEGER NOT NULL DEFAULT 0", "total_rewarded"),
            ("ALTER TABLE mt_user_token_ledger ADD COLUMN model TEXT DEFAULT ''", "model"),
            # flow_chat_all7_20261019: 置顶/标签
            ("ALTER TABLE chat_sessions ADD COLUMN pinned INTEGER DEFAULT 0", "pinned"),
            ("ALTER TABLE chat_sessions ADD COLUMN tags TEXT DEFAULT ''", "tags"),
        ]:
            try: conn.execute(col_def[0]); conn.commit()
            except Exception: pass

        # ── 模型定价种子数据 ──
        pricing_seeds = [
            ("qwen2.5:7b",       "仙女座 7B 发散思维",   1.0,  50, 100),
            ("qwen2.5:14b",      "仙女座 14B 深度推理",  2.0, 100, 200),
            ("qwen2.5-coder:7b", "仙女座 Coder 7B",     1.5,  75, 150),
            ("qwen2.5-coder:14b","仙女座 Coder 14B",    3.0, 150, 300),
            ("flux2-klein",      "Flux 图像生成",        5.0,   0, 500),
        ]
        for mid, name, w, pp, cc in pricing_seeds:
            conn.execute("""INSERT OR IGNORE INTO mt_chat_model_pricing
                          (model_id,display_name,model_weight,prompt_per_1k,completion_per_1k)
                          VALUES(?,?,?,?,?)""", (mid, name, w, pp, cc))
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"[CHAT-LOCAL] _ensure_tables error: {e}\n")
    finally:
        conn.close()


_ensure_tables()


# ════════════════════════════════════════════════════════════════
# 动作记录 + 拐点记录 + 脑库投喂
# ════════════════════════════════════════════════════════════════
def _record_action(session_id, user_id, action, detail=None):
    """动作记录 → chat_actions 表"""
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO chat_actions(session_id,user_id,action,detail) VALUES(?,?,?,?)",
            (session_id, user_id, action, json.dumps(detail or {}, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# Token 账户体系 (v25.2) — 强制登录消耗 + 每日赠送 10000
# SA (super_admin) 豁免: 不限量, 不扣费, 不拦截
# ════════════════════════════════════════════════════════════════
DAILY_FREE_TOKENS = 10000


def _ensure_daily_grant(user_id, username):
    """每日 lazy 赠送 + 余额查询 — 游客/注册用户分表
    游客 → mt_token_wallets (TEXT user_id, 一次性 10000)
    注册 → mt_user_token_accounts (INTEGER user_id, 每日赠送)
    返回 {'balance': int, 'granted_today': bool}"""
    today = datetime.now().strftime('%Y-%m-%d')
    conn = _db()
    try:
        is_guest = str(user_id).startswith('guest')
        if is_guest:
            # ── 游客: 查 mt_token_wallets (TEXT user_id) ──
            row = conn.execute(
                "SELECT balance, guest_free_grant FROM mt_token_wallets WHERE user_id=?",
                (user_id,)
            ).fetchone()
            if row is None:
                # 首次 → 建钱包 + 赠 10000
                dh = str(user_id).replace('guest_', '')[:16]
                _ensure_guest_wallet(dh, conn=conn)
                row = conn.execute(
                    "SELECT balance FROM mt_token_wallets WHERE user_id=?", (user_id,)
                ).fetchone()
            bal = row['balance'] if row else 0
            return {'balance': bal, 'granted_today': False}
        # ── 注册用户: 查 mt_user_token_accounts (INTEGER user_id) ──
        try:
            uid_int = int(user_id)
        except (ValueError, TypeError):
            # 不是数字 user_id 也回退 wallets
            row = conn.execute(
                "SELECT balance FROM mt_token_wallets WHERE user_id=?", (str(user_id),)
            ).fetchone()
            return {'balance': row['balance'] if row else 0, 'granted_today': False}
        row = conn.execute(
            "SELECT balance, last_grant_date FROM mt_user_token_accounts WHERE user_id=?",
            (uid_int,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO mt_user_token_accounts(user_id,username,balance,last_grant_date,total_granted) "
                "VALUES(?,?,?,?,?)",
                (uid_int, username or '', DAILY_FREE_TOKENS, today, DAILY_FREE_TOKENS)
            )
            conn.execute(
                "INSERT INTO mt_user_token_ledger(user_id,change,type,detail,balance_after) "
                "VALUES(?,?,?,?,?)",
                (uid_int, DAILY_FREE_TOKENS, 'daily_grant',
                 json.dumps({'reason': 'new_account_daily', 'date': today}, ensure_ascii=False),
                 DAILY_FREE_TOKENS)
            )
            conn.commit()
            return {'balance': DAILY_FREE_TOKENS, 'granted_today': True}
        if row['last_grant_date'] != today:
            new_balance = row['balance'] + DAILY_FREE_TOKENS
            conn.execute(
                "UPDATE mt_user_token_accounts SET balance=?, last_grant_date=?, total_granted=total_granted+?, "
                "updated_at=datetime('now','localtime') WHERE user_id=?",
                (new_balance, today, DAILY_FREE_TOKENS, uid_int)
            )
            conn.execute(
                "INSERT INTO mt_user_token_ledger(user_id,change,type,detail,balance_after) "
                "VALUES(?,?,?,?,?)",
                (uid_int, DAILY_FREE_TOKENS, 'daily_grant',
                 json.dumps({'reason': 'daily_free', 'date': today}, ensure_ascii=False),
                 new_balance)
            )
            conn.commit()
            return {'balance': new_balance, 'granted_today': True}
        return {'balance': row['balance'], 'granted_today': False}
    except Exception as e:
        sys.stderr.write(f"[CHAT-LOCAL] _ensure_daily_grant error: {e}\n")
        return {'balance': 0, 'granted_today': False}
        return {'balance': 0, 'granted_today': False}
    finally:
        conn.close()


def _get_balance(user_id):
    """查余额 (不做赠送, 只读) — 优先新表 mt_token_wallets"""
    try:
        conn = _db()
        # 🔧 flow_chat_guest_free_20261023: 优先查 mt_token_wallets (含游客 + 注册用户)
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_token_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE, username TEXT,
            is_guest INTEGER DEFAULT 0, guest_device_hash TEXT, balance INTEGER DEFAULT 0,
            frozen INTEGER DEFAULT 0, guest_free_grant INTEGER DEFAULT 0,
            guest_consumed INTEGER DEFAULT 0, expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')))""")
        wallet = conn.execute(
            "SELECT balance, frozen, is_guest, guest_free_grant, guest_consumed "
            "FROM mt_token_wallets WHERE user_id=?", (str(user_id),)
        ).fetchone()
        if wallet:
            bal = dict(wallet)
            free_grant = bal.get('guest_free_grant', 0) if bal.get('is_guest') else DAILY_FREE_TOKENS
            return {'balance': bal['balance'], 'frozen': bal.get('frozen', 0),
                    'total_granted': free_grant,
                    'total_consumed': bal.get('guest_consumed', 0),
                    'last_grant_date': '', 'daily_free': DAILY_FREE_TOKENS,
                    'is_guest': bool(bal.get('is_guest')),
                    'guest_free_grant': bal.get('guest_free_grant', 0)}
        # 老表 fallback (注册用户)
        row = conn.execute(
            "SELECT balance, total_granted, total_consumed, last_grant_date "
            "FROM mt_user_token_accounts WHERE user_id=?", (str(user_id),)
        ).fetchone()
        conn.close()
        if row:
            return {'balance': row['balance'], 'total_granted': row['total_granted'],
                    'total_consumed': row['total_consumed'], 'last_grant_date': row['last_grant_date'],
                    'daily_free': DAILY_FREE_TOKENS, 'is_guest': False}
        return {'balance': 0, 'total_granted': 0, 'total_consumed': 0,
                'last_grant_date': '', 'daily_free': DAILY_FREE_TOKENS, 'is_guest': False}
    except Exception:
        return {'balance': 0, 'total_granted': 0, 'total_consumed': 0,
                'last_grant_date': '', 'daily_free': DAILY_FREE_TOKENS, 'is_guest': False}


def _pricing_for(model):
    """查模型定价: 返回 {model_weight, prompt_per_1k, completion_per_1k, display_name}"""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT model_weight, prompt_per_1k, completion_per_1k, display_name "
            "FROM mt_chat_model_pricing WHERE model_id=? AND is_active=1", (model,)
        ).fetchone()
        conn.close()
        if row:
            return {'model_weight': row['model_weight'],
                    'prompt_per_1k': row['prompt_per_1k'],
                    'completion_per_1k': row['completion_per_1k'],
                    'display_name': row['display_name']}
    except Exception:
        pass
    # 默认定价 (未知模型 → 1x 倍率)
    return {'model_weight': 1.0, 'prompt_per_1k': 50, 'completion_per_1k': 100, 'display_name': model}


def _estimate_cost(model, prompt_tokens, completion_tokens):
    """估算扣费 (模型定价 × 倍率 × token 数)"""
    p = _pricing_for(model)
    prompt_cost = int(prompt_tokens / 1000 * p['prompt_per_1k'] * p['model_weight'])
    completion_cost = int(completion_tokens / 1000 * p['completion_per_1k'] * p['model_weight'])
    # 至少 1 token 扣费 (防极微消耗免费)
    return {'prompt_cost': max(1, prompt_cost),
            'completion_cost': max(1, completion_cost),
            'total_cost': max(1, prompt_cost + completion_cost),
            'pricing': p}


def _prehold(user_id, session_id, estimated_cost, model):
    """原子预扣: 游客→mt_token_wallets, 注册→mt_user_token_accounts
    返回 {'ok': bool, 'balance': int, 'held_id': ledger_id}"""
    conn = _db()
    try:
        is_guest = str(user_id).startswith('guest')
        conn.execute("BEGIN IMMEDIATE")
        if is_guest:
            row = conn.execute(
                "SELECT balance, frozen FROM mt_token_wallets WHERE user_id=?", (user_id,)
            ).fetchone()
            bal = row['balance'] if row else 0
            frozen = row['frozen'] if row else 0
            available = bal - frozen
            if row is None or available < estimated_cost:
                conn.rollback()
                return {'ok': False, 'balance': bal, 'held_id': None}
            conn.execute(
                "UPDATE mt_token_wallets SET frozen=frozen+?, updated_at=datetime('now','localtime') "
                "WHERE user_id=?", (estimated_cost, user_id)
            )
        else:
            row = conn.execute(
                "SELECT balance, frozen FROM mt_user_token_accounts WHERE user_id=?", (user_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return {'ok': False, 'balance': 0, 'held_id': None}
            frozen = row['frozen'] if 'frozen' in row.keys() else 0
            bal = row['balance']
            if bal < estimated_cost:
                conn.rollback()
                return {'ok': False, 'balance': bal, 'held_id': None}
            conn.execute(
                "UPDATE mt_user_token_accounts SET balance=balance-?, frozen=frozen+?, "
                "updated_at=datetime('now','localtime') WHERE user_id=?",
                (estimated_cost, estimated_cost, user_id)
            )
        # ledger 记录 (user_id TEXT 现在兼容 guest_xxx)
        new_balance = bal - estimated_cost
        cur = conn.execute(
            "INSERT INTO mt_user_token_ledger(user_id,change,type,session_id,model,detail,balance_after) "
            "VALUES(?,?,?,?,?,?,?)",
            (str(user_id), -estimated_cost, 'prehold', session_id or '', model or '',
             json.dumps({'estimated': estimated_cost}, ensure_ascii=False), new_balance)
        )
        held_id = cur.lastrowid
        conn.commit()
        return {'ok': True, 'balance': new_balance, 'held_id': held_id, 'held_amount': estimated_cost}
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        sys.stderr.write(f"[CHAT-LOCAL] _prehold error: {e}\n")
        return {'ok': False, 'balance': 0, 'held_id': None}
    finally:
        conn.close()


def _finalize(user_id, session_id, model, prompt_tokens, completion_tokens, prehold_result,
              inflections=None, brain_fed=False):
    """三阶段结算: 实扣真实用量 + 退差 + 拐点/脑库奖励
    游客→mt_token_wallets (简单版), 注册→mt_user_token_accounts (完整版)"""
    uid_str = str(user_id)
    is_guest = uid_str.startswith('guest')
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        prehold_amount = (prehold_result or {}).get('held_amount', 0)

        # 2) 实扣真实用量
        cost = _estimate_cost(model, prompt_tokens, completion_tokens)
        real_cost = cost['total_cost']
        if is_guest:
            row = conn.execute(
                "SELECT balance, frozen FROM mt_token_wallets WHERE user_id=?", (uid_str,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return {'balance': 0, 'net_cost': 0, 'reward': 0, 'refund': prehold_amount}
            actual_deduct = min(real_cost, row['balance'])
            new_balance = row['balance'] - actual_deduct
            # 释放 frozen + 更新 balance
            conn.execute(
                "UPDATE mt_token_wallets SET balance=?, frozen=MAX(0,frozen-?) WHERE user_id=?",
                (new_balance, prehold_amount, uid_str)
            )
        else:
            row = conn.execute(
                "SELECT balance FROM mt_user_token_accounts WHERE user_id=?", (user_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return {'balance': 0, 'net_cost': 0, 'reward': 0, 'refund': prehold_amount}
            actual_deduct = min(real_cost, row['balance'])
            new_balance = row['balance'] - actual_deduct
            conn.execute(
                "UPDATE mt_user_token_accounts SET balance=?, frozen=MAX(0,frozen-?), "
                "total_consumed=total_consumed+?, updated_at=datetime('now','localtime') WHERE user_id=?",
                (new_balance, prehold_amount, actual_deduct, user_id)
            )
        # ledger
        conn.execute(
            "INSERT INTO mt_user_token_ledger(user_id,change,type,session_id,model,detail,balance_after) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid_str, -actual_deduct, 'consume', session_id or '', model or '',
             json.dumps({'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                         'model_weight': cost['pricing']['model_weight']}, ensure_ascii=False),
             new_balance)
        )

        # 3) 退差 (预扣 - 实扣 = 多扣了退回去)
        refund = prehold_amount - actual_deduct
        if refund > 0:
            new_balance += refund
            if is_guest:
                conn.execute(
                    "UPDATE mt_token_wallets SET balance=balance+? WHERE user_id=?",
                    (refund, uid_str)
                )
            else:
                conn.execute(
                    "UPDATE mt_user_token_accounts SET balance=balance+? WHERE user_id=?",
                    (refund, user_id)
                )
            conn.execute(
                "INSERT INTO mt_user_token_ledger(user_id,change,type,session_id,model,detail,balance_after) "
                "VALUES(?,?,?,?,?,?,?)",
                (uid_str, refund, 'release', session_id or '', model or '',
                 json.dumps({'reason': 'prehold_over_actual', 'prehold': prehold_amount, 'actual': actual_deduct},
                            ensure_ascii=False), new_balance)
            )

        # 4) 奖励 (游客简化: 不扣每日 200 封顶, 直接加余额)
        reward = 0
        if not is_guest:
            balance_now = new_balance
            reward_info = _calc_reward(user_id, balance_now, inflections=inflections, brain_fed=brain_fed)
            reward = reward_info.get('reward', 0)
        elif brain_fed or (inflections and len(inflections) > 0):
            # 游客: 脑库投喂 + 拐点 → 5~20 token 奖励
            reward = 10 + (5 if inflections else 0)
        if reward > 0:
            new_balance += reward
            if is_guest:
                conn.execute(
                    "UPDATE mt_token_wallets SET balance=balance+? WHERE user_id=?",
                    (reward, uid_str)
                )
            else:
                conn.execute(
                    "UPDATE mt_user_token_accounts SET balance=balance+?, total_rewarded=total_rewarded+? "
                    "WHERE user_id=?", (reward, reward, user_id)
                )
            conn.execute(
                "INSERT INTO mt_user_token_ledger(user_id,change,type,session_id,model,detail,balance_after) "
                "VALUES(?,?,?,?,?,?,?)",
                (uid_str, reward, 'reward', session_id or '', model or '',
                 json.dumps({'inflections': inflections or [], 'brain_fed': brain_fed}, ensure_ascii=False),
                 new_balance)
            )

        conn.commit()
        return {
            'balance': new_balance, 'net_cost': actual_deduct,
            'reward': reward, 'refund': refund
        }
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        sys.stderr.write(f"[CHAT-LOCAL] _finalize error: {e}\n")
        return {'balance': 0, 'net_cost': 0, 'reward': 0, 'refund': 0}
    finally:
        conn.close()


def _detect_inflections(session_id, user_id, user_text, ai_text):
    """拐点检测 — 识别发散思维/灵感爆发/矛盾碰撞"""
    INFLECTION_RULES = [
        ('diverge', ['如果', '假设', '想象', '倘若', '万一', '不妨', '试想']),
        ('breakthrough', ['原来如此', '恍然大悟', '灵光', '豁然开朗', '顿悟', '突破']),
        ('question', ['为什么', '怎么会', '难道', '究竟', '到底']),
        ('metaphor', ['就像', '好比', '仿佛', '如同', '类似于', '比如']),
        ('contradiction', ['但是', '不过', '然而', '但实际上', '可是']),
    ]
    points = []
    text = (user_text or '') + ' ' + (ai_text or '')
    for itype, keywords in INFLECTION_RULES:
        for kw in keywords:
            if kw in text:
                points.append({
                    'inflection_type': itype,
                    'trigger_text': kw,
                    'ai_response': (ai_text or '')[:500],
                    'quality_score': 0.6 if itype in ('breakthrough', 'diverge') else 0.4,
                })
                break  # 每种类型只记一次
    if points:
        try:
            conn = _db()
            for p in points:
                conn.execute(
                    "INSERT INTO chat_inflection_points(session_id,user_id,inflection_type,trigger_text,ai_response,quality_score) VALUES(?,?,?,?,?,?)",
                    (session_id, user_id, p['inflection_type'], p['trigger_text'], p['ai_response'], p['quality_score'])
                )
            conn.commit()
            conn.close()
        except Exception:
            pass
    return points


def _feed_brain(session_id, user_id, username, user_text, ai_text, inflection_points):
    """脑库投喂 — 对话经验蒸馏 → mt_ai_brain_feed_log"""
    try:
        # 尝试调 BrainFeedingEngine
        from engines.brain_feeding_engine import BrainFeedingEngine
        bf = BrainFeedingEngine()
        bf.feed({
            'source': 'local_chat',
            'session_id': session_id,
            'user_id': user_id,
            'username': username,
            'content': f"用户({username}): {user_text[:500]}\nAI回复: {ai_text[:500]}",
            'inflections': len(inflection_points),
            'quality': 0.7 if inflection_points else 0.5,
        })
    except Exception:
        # Fallback: 直接写 mt_ai_brain_feed_log（如果表存在）
        try:
            conn = _db()
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%brain%feed%'").fetchall()]
            if tables:
                conn.execute(
                    f"INSERT INTO {tables[0]}(source, content, created_at) VALUES(?,?,datetime('now','localtime'))",
                    ('local_chat', f"user={username}: {user_text[:200]} | ai: {ai_text[:200]}")
                )
                conn.commit()
            conn.close()
        except Exception:
            pass


# ╔═══════════════════════════════════════════════════════════════
# ║ flow_chat_guest_free_20261023: 异步关键词+拐点抽取 → 隐私保护
# ║ 零 token, 本地词典 + TF-IDF 简化, 不调任何外部 LLM
# ║ 落库 mt_brain_feed_keywords → 后续投喂 AI 脑库
# ╚═══════════════════════════════════════════════════════════════

# 领域关键词词典 (可热扩展)
_DOMAIN_KEYWORDS = {
    'tech': ['代码', '函数', '类', 'API', 'Flask', 'Python', 'SQL', '接口', 'bug', '错误',
             '部署', 'Docker', '数据库', '路由', '蓝图', '线程', '异步', 'token', '模型'],
    'education': ['学习', '考试', '题目', '学生', '老师', '课程', '作业', '分数', '知识点'],
    'idea': ['灵感', '想法', '思路', '方案', '创意', '建议', '改进', '优化', '重构'],
    'problem': ['问题', '错误', '失败', '崩溃', '报错', '解决', '调试', '排查', '根因'],
    'ai': ['AI', '大模型', 'LLM', 'Ollama', '向量', 'RAG', 'embedding', '推理', 'token', '上下文'],
}

# 拐点触发词 (与 _detect_inflections 对齐)
_INFLECTION_TRIGGERS = {
    'diverge': ['如果', '假设', '想象', '倘若', '万一', '不妨', '试想'],
    'breakthrough': ['原来如此', '恍然大悟', '灵光', '豁然开朗', '顿悟', '突破'],
    'decision': ['决定', '选择', '定了', '就这么办', '不再', '换成', '改成'],
    'contradiction': ['但是', '不过', '然而', '但实际上', '可是'],
}

# 停用词 (过滤)
_STOPWORDS = set('的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 什么 怎么 为 吗 吧 呢 啊 哦 哈 嗯 呀 啦 嘛 哎 哟'.split())


def _extract_and_save_keywords(session_id, user_id, user_text, ai_text, inflection_points=None):
    """异步钩子: 消息落库后抽关键词+拐点 → mt_brain_feed_keywords → 后续投喂脑库
    
    零 token, 纯本地词典 + 高频 n-gram, 不调 LLM. 隐私友好.
    幂等: 同一 session_id 不重复抽 (避免多线程重复写).
    """
    try:
        conn = _db()
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_brain_feed_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, session_id TEXT,
            user_id TEXT, keyword TEXT, weight REAL DEFAULT 1.0,
            is_inflection INTEGER DEFAULT 0, category TEXT,
            extracted_at TEXT DEFAULT (datetime('now','localtime')))""")
        
        # 幂等检查 — 同一 session 已抽过就跳过
        existing = conn.execute(
            "SELECT COUNT(1) FROM mt_brain_feed_keywords WHERE session_id=?",
            (session_id or '',)
        ).fetchone()[0]
        if existing > 0:
            conn.close()
            return
        
        text = ((user_text or '') + ' ' + (ai_text or '')).strip()
        if not text or len(text) < 4:
            conn.close()
            return

        keywords_found = {}  # keyword → (weight, category, is_inflection)
        
        # ── 1) 领域词典匹配 ──
        text_lower = text.lower()
        for category, kws in _DOMAIN_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in text_lower:
                    keywords_found[kw] = (keywords_found.get(kw, (0, category, 0))[0] + 1.2, category, 0)
        
        # ── 2) 拐点触发词 (来自 _detect_inflections 结果 + 额外扫描) ──
        if inflection_points:
            for p in inflection_points:
                trigger = p.get('trigger_text', '') if isinstance(p, dict) else ''
                itype = p.get('inflection_type', 'inflection') if isinstance(p, dict) else 'inflection'
                if trigger:
                    keywords_found[trigger] = (0.9, itype, 1)
        # 额外 decision 拐点 (用户说"定了" / "不再" / "改成")
        for itype, triggers in _INFLECTION_TRIGGERS.items():
            for trig in triggers:
                if trig in text:
                    keywords_found[trig] = (keywords_found.get(trig, (1.0, itype, 0))[0], itype, 1)
        
        # ── 3) 简易 n-gram (高频 2-3 字组合) ──
        from collections import Counter
        # 简单中文分词: 按标点切 → 2-gram sliding
        import re as _re
        clean = _re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
        chars = [c for c in clean if c.strip() and c.strip() not in _STOPWORDS]
        # 2-gram
        bigrams = [''.join(chars[i:i+2]) for i in range(len(chars)-1) if ''.join(chars[i:i+2]).strip()]
        trigrams = [''.join(chars[i:i+3]) for i in range(len(chars)-2) if ''.join(chars[i:i+3]).strip()]
        freq = Counter(bigrams + trigrams)
        for gram, cnt in freq.most_common(15):
            if cnt >= 2 and len(gram) >= 2:
                keywords_found[gram] = (keywords_found.get(gram, (0, 'ngram', 0))[0] + cnt * 0.3, 'ngram', 0)
        
        # ── 4) 写库 (取权重前 20) ──
        sorted_kws = sorted(keywords_found.items(), key=lambda x: -x[1][0])[:20]
        written = 0
        for kw, (weight, category, is_inflection) in sorted_kws:
            if not kw.strip(): continue
            conn.execute(
                "INSERT INTO mt_brain_feed_keywords(session_id,user_id,keyword,weight,is_inflection,category) VALUES(?,?,?,?,?,?)",
                (session_id or '', str(user_id or ''), kw.strip(), round(weight, 2), is_inflection, category)
            )
            written += 1
        
        # 同步给 mt_ai_brain_feed_log (让 _feed_brain 的 fallback 能看到)
        if written > 0:
            try:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%brain%feed%'"
                ).fetchall()]
                if tables:
                    top_kw = ';'.join(k for k, _ in sorted_kws[:5])
                    conn.execute(
                        f"INSERT INTO {tables[0]}(source, content, inflections, quality, keywords_extracted) VALUES(?,?,?,?,?)",
                        ('keyword_hook', f"[{user_id}] top5:{top_kw}, total:{written}",
                         len([k for k,(_,_,inf) in sorted_kws if inf]), 0.7, written)
                    )
            except Exception:
                pass
        
        conn.commit()
        conn.close()
        # 日志 (debug, 生产可关)
        import logging
        logging.getLogger(__name__).debug(
            f"[KEYWORD-HOOK] session={session_id} user={user_id} → {written} keywords "
            f"(inflections={sum(1 for _,(_,_,i) in sorted_kws if i)})"
        )
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# 上下文管理: 50MB 提示 / 128MB 自动压缩 + 脑库投喂
# ════════════════════════════════════════════════════════════════
CONTEXT_WARN_MB = 50.0
CONTEXT_COMPRESS_MB = 128.0
KEEP_RECENT_TURNS = 20


def _check_and_manage_context(session_id, user_id, username):
    """
    检查 session 上下文大小, 超过阈值触发 warning 或自动压缩.
    返回 dict: {warning/compressed/size_mb/size_mb_before/size_mb_after/archived_count}
    自动压缩策略: 老消息投喂脑库后, 从后续 prompt 构建的 context 里截断 (DB 不删).
    """
    status = {'warning': False, 'compressed': False, 'size_mb': 0}
    try:
        conn = _db()
        cur = conn.execute(
            "SELECT SUM(LENGTH(content)) FROM chat_messages WHERE session_id=? AND role IN ('user','assistant')",
            (session_id,)
        )
        row = cur.fetchone()
        total_bytes = row[0] or 0
        conn.close()
    except Exception:
        return status

    size_mb = total_bytes / (1024 * 1024)
    status['size_mb'] = round(size_mb, 2)

    if size_mb < CONTEXT_WARN_MB:
        return status

    # ≥ 50MB → 提示
    status['warning'] = True

    if size_mb < CONTEXT_COMPRESS_MB:
        return status

    # ≥ 128MB → 自动压缩
    try:
        conn = _db()
        # 1. 取全部消息按序
        rows = conn.execute(
            "SELECT id, role, content FROM chat_messages WHERE session_id=? AND role IN ('user','assistant') ORDER BY created_at ASC, id ASC",
            (session_id,)
        ).fetchall()
        conn.close()
    except Exception:
        return status

    total_msgs = len(rows)
    if total_msgs <= KEEP_RECENT_TURNS * 2:
        return status  # 太少不值得压缩

    # 2. 切分: 保留最近 KEEP_RECENT_TURNS*2 条 (一轮对话=user+assistant)
    keep_count = KEEP_RECENT_TURNS * 2
    archived = rows[:-keep_count]
    kept = rows[-keep_count:]

    archived_bytes = sum(len(r['content'] or '') for r in archived)
    kept_bytes = sum(len(r['content'] or '') for r in kept)

    # 3. 老消息投喂脑库 (异步)
    def _async_fed():
        try:
            conn2 = _db()
            # 脑库摘要: 老消息压缩成摘要条目
            archive_text = f"[上下文压缩归档] session={session_id} 原{size_mb:.1f}MB → 保留最近 {KEEP_RECENT_TURNS} 轮\n"
            for r in archived[-30:]:  # 最多喂 30 条老消息到脑库
                snippet = (r['content'] or '')[:300]
                archive_text += f"  {r['role']}: {snippet}\n"
            conn2.execute(
                "INSERT OR IGNORE INTO mt_ai_brain_sources(source,content,created_at) VALUES(?,?,datetime('now','localtime'))",
                ('local_chat_context_archive', archive_text[:2000])
            )
            conn2.commit()
            conn2.close()
        except Exception:
            pass

    import threading
    threading.Thread(target=_async_fed, daemon=True).start()

    status['compressed'] = True
    status['size_mb_before'] = round(size_mb, 2)
    status['size_mb_after'] = round(kept_bytes / (1024 * 1024), 2)
    status['archived_count'] = len(archived)

    return status


def _auto_title_first_msg(text):
    """自动生成对话 title: 取首条用户消息前 20 字, 去换行截断"""
    if not text:
        return "未命名对话"
    t = text.replace('\n', ' ').strip()
    if len(t) > 20:
        t = t[:19] + '…'
    return t


# ════════════════════════════════════════════════════════════════
# 仙女座发散思维 prompt 增强
# ════════════════════════════════════════════════════════════════
def _build_divergent_prompt(user_text, username, cognitive_profile=None, history=None, page_context=None):
    """
    仙女座发散思维 prompt 增强层
    基于: 冰山矩阵 + 认知画像 + 对话历史 → 增强 system prompt
    """
    # 1. 基础角色
    system = """你是仙女座星系AI助手，具备发散思维引擎 (Divergent Thinking Engine)。
你的思考流程:
  1. 先快速分析用户问题的本质 (what)
  2. 从多个角度发散 (why 因果 / how 方法 / what_if 假设 / analogy 隐喻)
  3. 选出最有洞察力的 2-3 个角度深入
  4. 用结构化方式输出 (emoji + 小标题 + 简明要点)

核心原则:
  - 不停留在表面, 追问一层
  - 用类比/隐喻让抽象概念具象
  - 对"假设性"问题大胆想象 (what if)
  - 对"矛盾/反直觉"现象给出合理解释
  - 用中文回答, 语气亲切专业"""

    # 2. 认知画像适配
    cp = cognitive_profile or {}
    style = cp.get('learning_style', 'visual')
    level = cp.get('cognitive_level', 'intermediate')
    role = cp.get('role', 'student')

    STYLE_HINTS = {
        'visual': '视觉型学习者偏好: 用 emoji/列表/结构化呈现, 避免长段文字',
        'auditory': '听觉型学习者偏好: 口语化, 对话感强, 可多设问引导思考',
        'kinesthetic': '动手型学习者偏好: 给可操作步骤/小实验/实践建议',
        'reading': '阅读型学习者偏好: 深入分析, 分层次展开, 引用概念',
    }
    LEVEL_HINTS = {
        'beginner': '入门水平: 先给概念定义, 用简单类比',
        'intermediate': '中级水平: 可以讲原理, 给示例代码/公式',
        'advanced': '高级水平: 深入推导, 讨论边界case, 给拓展方向',
    }

    extra = f"\n\n当前用户 {username} ({role}):\n  学习风格={style} → {STYLE_HINTS.get(style, '')}\n  认知水平={level} → {LEVEL_HINTS.get(level, '')}"
    system += extra

    # 2.5 页面上下文携带 (flow_chat_all7_20261019): 助手感知用户当前所在冰山页面
    if page_context:
        system += f"\n\n📍 用户当前所在页面上下文: {page_context}\n(用户从该页面发起对话, 回答时可结合此上下文; 若与问题无关则忽略)"

    # 3. 发散触发 — 如果用户问题含"假设/如果/想象/万一", 强化发散模式
    DIVERGE_KEYWORDS = ['如果', '假设', '想象', '倘若', '万一', '不妨', '试想', 'what if', '假如']
    if any(kw in user_text.lower() for kw in DIVERGE_KEYWORDS):
        system += """

⚠️ 发散思维强化模式:
用户问题含假设/想象类关键词 → 请大胆发散, 给出 3-5 个不同可能性,
每个可能性标注 "可能性1/2/3", 最后给出你认为最有价值的那个方向。
回答末尾必须追加一段「🔮 发散角」: 列出 2-3 个帮用户继续发散的追问,
每行以 "- 🔭 " 开头, 例如 "- 🔭 如果时间倒流十年, 这个结论还成立吗?" """

    return system


# v25.5: Ollama host 自动发现 — mini 本地没装时 fallback 到开发机 Tailscale
_OLLAMA_FALLBACKS = ["http://127.0.0.1:11434", "http://100.121.98.15:11434", "http://192.168.11.242:11434"]
def _resolve_ollama_host():
    """优先 env var, 否则探测 fallback 列表 (mini→开发机 Tailscale)"""
    env = os.environ.get("OLLAMA_HOST", "").strip()
    if env: return env
    import urllib.request as _ur
    for h in _OLLAMA_FALLBACKS:
        try:
            _ur.urlopen(_ur.Request(f"{h}/api/tags"), timeout=2)
            return h
        except Exception:
            continue
    return _OLLAMA_FALLBACKS[0]

def _ollama_available():
    """Check if Ollama is reachable (mini 自动 fallback 到开发机)."""
    try:
        import urllib.request as _ur
        host = _resolve_ollama_host()
        resp = _ur.urlopen(_ur.Request(f"{host}/api/tags"), timeout=3)
        return resp.status == 200
    except Exception:
        return False


# flow_chat_all7_20261019: 视觉模型探测 (多模态图片理解)
_VISION_MODEL_PATTERNS = ('llava', 'qwen2.5vl', 'qwen2-vl', 'qwen3-vl', 'minicpm-v', 'moondream', 'bakllava')

def _detect_vision_model():
    """从 Ollama /api/tags 探测已安装的视觉模型, 无则返回 None (优雅降级)"""
    try:
        import urllib.request as _ur
        host = os.environ.get("OLLAMA_HOST", "").strip() or _resolve_ollama_host()
        resp = _ur.urlopen(_ur.Request(f"{host}/api/tags"), timeout=3)
        names = [m.get('name', '') for m in json.loads(resp.read().decode()).get('models', [])]
        for n in names:
            if any(p in n.lower() for p in _VISION_MODEL_PATTERNS):
                return n
    except Exception:
        pass
    return None


def _fallback_local_reply(user_text, username):
    """
    v25.1: Fallback reply when Ollama not available (Mac mini scenario).
    Uses Andromeda divergent thinking template (冰山矩阵) — no external deps.
    Generates 2-3 perspective angles on the user's topic.
    """
    topic = (user_text or "").strip()[:80]
    angles = [
        f"【第1视角 — 冰山表层】'{topic}' 这个问题，从日常经验层面看...",
        f"【第2视角 — 认知中层】深入分析的话，'{topic}' 背后隐藏的假设是...",
        f"【第3视角 — 元认知层】换个角度：为什么我们会在意 '{topic}' 这个问题本身？",
    ]
    reply = f"你好 {username}！(本地推理降级模式 · 发散思维引擎)\n\n"
    reply += f"关于「{topic}」，仙女座从 3 个角度展开：\n\n"
    for a in angles:
        reply += a + "\n\n"
    reply += f"当前 Mac mini 未安装 Ollama · 回答由仙女座发散思维模板生成。\n"
    reply += f"安装 Ollama (brew install ollama) 后自动切换 qwen2.5 原生推理。"
    return reply


def _call_ollama_stream(user_text, system_prompt, username, images=None, model_override=None):
    """
    v25.1: Stream from Ollama /api/chat. Auto-detect available.
    Falls back to _fallback_local_reply when Ollama unreachable.
    flow_chat_all7_20261019: images (base64 list) → 多模态视觉理解;
    model_override → 视觉模型名 (仅带图消息传入)
    """
    import urllib.request as _ur

    if not _ollama_available():
        yield f"data: [thinking]\n\n"
        fallback_text = _fallback_local_reply(user_text, username)
        # Stream fallback text token-by-token for consistent UX
        for ch in fallback_text:
            yield f"data: {json.dumps({'token': ch}, ensure_ascii=False)}\n\n"
        yield f"data: [done] {json.dumps({'model': 'andromeda_fallback', 'duration_ms': 50, 'prompt_eval_count': len(user_text), 'eval_count': len(fallback_text)}, ensure_ascii=False)}\n\n"
        return

    yield f"data: [thinking]\n\n"

    try:
        host = os.environ.get("OLLAMA_HOST", "").strip() or _resolve_ollama_host()
        model = model_override or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        user_msg = {"role": "user", "content": user_text}
        if images:
            user_msg["images"] = images  # base64 列表, 视觉模型多模态输入
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                user_msg,
            ],
            "stream": True,
            "options": {"temperature": 0.85, "top_p": 0.92, "num_predict": 1024}
        }).encode()

        req = _ur.Request(f"{host}/api/chat", data=body, headers={"Content-Type": "application/json"})
        resp = _ur.urlopen(req, timeout=180)

        for line in resp:
            line = line.decode().strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                token = msg.get("content", "")
                if token:
                    yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
                if chunk.get("done"):
                    total_dur = chunk.get("total_duration", 0)
                    yield f"data: [done] {json.dumps({'model': model, 'duration_ms': total_dur//1000000 if total_dur else 0, 'prompt_eval_count': chunk.get('prompt_eval_count', 0), 'eval_count': chunk.get('eval_count', 0)}, ensure_ascii=False)}\n\n"
                    break
            except json.JSONDecodeError:
                continue
    except Exception as e:
        yield f"data: [error] {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"


# ╔═══════════════════════════════════════════════════════════════
# ║ flow_chat_guest_free_20261023: 游客 1 万免费 token 权限体系
# ║ 注册用户 → 正常扣费 mt_token_wallets.balance ← mt_user_token_ledger
# ║ 游客     → device_hash 身份 + 10000 免费额度 (30天过期)
# ║          未登录不 401 → 自动建 guest session
# ╚═══════════════════════════════════════════════════════════════

def _device_hash(req=None):
    """游客唯一身份 = sha256(IP|UA) 前 16 位 — 无需注册, 浏览器换指纹变人"""
    r = req or request
    ip = r.remote_addr or '0.0.0.0'
    ua = (r.headers.get('User-Agent') or 'unknown')[:80]
    raw = f"{ip}|{ua}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def _ensure_guest_wallet(device_hash, db=None):
    """确保游客钱包存在: is_guest=1, guest_free_grant=10000, balance=10000"""
    db = db or _db()
    row = db.execute("SELECT * FROM mt_token_wallets WHERE user_id=?", (f"guest_{device_hash}",)).fetchone()
    if row:
        # 已存在, 补 balance 兜底
        db.execute("UPDATE mt_token_wallets SET updated_at=datetime('now','localtime') WHERE user_id=?", (f"guest_{device_hash}",))
        db.commit()
        return dict(row)
    # 新建游客钱包
    db.execute("""INSERT INTO mt_token_wallets(user_id, username, is_guest, guest_device_hash,
                    balance, guest_free_grant, expires_at)
                  VALUES(?,?,1,?,?,10000, datetime('now','localtime','+30 days'))""",
               (f"guest_{device_hash}", f"Guest_{device_hash[:8]}", device_hash, 10000))
    db.commit()
    row = db.execute("SELECT * FROM mt_token_wallets WHERE user_id=?", (f"guest_{device_hash}",)).fetchone()
    return dict(row) if row else None

def _login_required(fn):
    """🔧 游客友好版本 — 未登录自动建 guest 身份 + 1 万免费 token, 不 401"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        uid = session.get('user_id')
        if not uid or str(uid).startswith('guest'):
            # ── 未登录 → 自动创建 guest 身份 ──
            dh = session.get('device_hash') or _device_hash()
            session['device_hash'] = dh
            session['user_id'] = f"guest_{dh}"
            session['username'] = f"Guest_{dh[:8]}"
            session['role'] = 'guest'
            # 确保钱包
            try:
                _ensure_guest_wallet(dh)
            except Exception as e:
                current_app.logger.warning(f"[guest] wallet init fail: {e}")
        return fn(*args, **kwargs)
    return wrapper


def _get_user():
    return {
        'user_id': session.get('user_id'),
        'username': session.get('username'),
        'role': session.get('role', 'user'),
    }


def _chat_login_guide(next_path: str):
    """聊天系统首次进入引导页 (flow_chat_login_guide_20261022)

    替代此前的硬 302: 首次访问 /local-chat、/ai 的游客先看到引导卡片 —
    说明「登录后进入聊天 / 小龙账号仅可聊天 / 其他功能需网页端申请」三步,
    并提供登录表单(登录成功回跳 next_path)、注册入口、开通申请入口。"""
    from flask import render_template
    return render_template('chat_login_guide.html', next_url=next_path)


def _is_sa(u=None):
    """SA 豁免判定 (v25.5) — 三条件 OR:
    1. role == 'super_admin' (session 角色)
    2. username == 'wuchenghao15' (§1.1 规范: 超级管理员唯一)
    3. 双密钥硬件在线 — VikeyEnforcementMiddleware.sim 模式自动通过
       (v25.5: 已插双密钥 → 自动认证为 SA session, 无需手动登录)"""
    u = u or _get_user()
    if u.get('role') == 'super_admin' or u.get('username') == 'wuchenghao15':
        return True
    # SA 双密钥在线自动认证
    try:
        from app.middlewares.vikey_enforcement_middleware import VikeyEnforcementMiddleware
        result = VikeyEnforcementMiddleware.check_sa_redirect(
            username=u.get('username', ''),
            role=u.get('role', ''),
            ip=request.remote_addr if request else None,
        )
        if result.get('vikey_online'):
            # 已插双密钥 → 自动写入 SA session
            session['user_id'] = session.get('user_id') or 5
            session['username'] = 'wuchenghao15'
            session['role'] = 'super_admin'
            session['vikey_auth_token'] = result.get('auth_token', '')
            u = _get_user()
            return True
    except Exception:
        pass
    return False


def _calc_reward(user_id, balance, inflections=None, brain_fed=False):
    """制约平衡奖励公式 (v25.5)

    三大约束:
    ① 每日封顶 max_daily=200 (防刷)
    ② 单次不超过余额 15% (防套利, 余额 1000 最多奖 150)
    ③ 拐点奖励 + 脑库奖励 合并计算, 冷却 60s

    公式:
    reward = min(拐点奖励合计, balance×0.15) + brain_feed×100
    reward = min(reward, 200 - 今日已奖)
    reward = reward if 距上次奖励 > 60s else 0

    Returns: {'reward': int, 'breakdown': dict, 'capped': bool, 'formula_hash': str}
    """
    import hashlib

    # 1) 拐点基础奖励 (v25.5 按质量分 × 基数)
    base = {'breakthrough': 50, 'diverge': 30, 'question': 20, 'metaphor': 20, 'contradiction': 20}
    inflection_reward = 0
    inflection_breakdown = {}
    if inflections:
        for p in inflections:
            itype = p.get('inflection_type', '')
            score = p.get('quality_score', 0.5)
            r = int(base.get(itype, 10) * max(0.5, score))
            inflection_reward += r
            inflection_breakdown[itype] = inflection_breakdown.get(itype, 0) + r

    # 2) 脑库投喂奖励 (100 token, 上限)
    brain_reward = 100 if brain_fed else 0

    # 3) 制约平衡: 单次不超余额 15%
    max_per_turn = max(20, int(balance * 0.15))
    turn_reward = min(inflection_reward + brain_reward, max_per_turn)

    # 4) 制约平衡: 每日封顶 200
    try:
        conn = _db()
        row = conn.execute(
            "SELECT coalesce(sum(change),0) FROM mt_user_token_ledger "
            "WHERE user_id=? AND type IN ('reward','brain_feed') AND date(created_at)=date('now','localtime')",
            (user_id,)
        ).fetchone()
        daily_already = row[0] if row else 0
        conn.close()
    except Exception:
        daily_already = 0
    max_daily = 200
    remaining = max(0, max_daily - daily_already)
    if remaining <= 0:
        return {'reward': 0, 'breakdown': {}, 'capped': True, 'formula_hash': _reward_formula_snapshot()}
    final_reward = min(turn_reward, remaining)
    capped = final_reward < (inflection_reward + brain_reward)

    # 5) 冷却检查 (60s)
    try:
        conn = _db()
        last = conn.execute(
            "SELECT created_at FROM mt_user_token_ledger "
            "WHERE user_id=? AND type IN ('reward','brain_feed') "
            "ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        conn.close()
        if last:
            from datetime import datetime as _dt
            last_ts = _dt.fromisoformat(last[0])
            if (datetime.now() - last_ts).total_seconds() < 60:
                return {'reward': 0, 'breakdown': inflection_breakdown, 'capped': False,
                        'cooldown': True, 'formula_hash': _reward_formula_snapshot()}
    except Exception:
        pass

    return {
        'reward': final_reward,
        'breakdown': {**inflection_breakdown, 'brain_feed': brain_reward},
        'capped': capped,
        'formula_hash': _reward_formula_snapshot(),
        'daily_remaining': remaining - final_reward,
    }


def _get_cognitive_profile(user_id, username):
    """查认知画像 — 适配 caopw 问题里发现的双关联模式"""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT username, cognitive_level, learning_style, role, iceberg_layer, "
            "focus_subjects, pace_setting, ai_tutor_type "
            "FROM mt_user_cognitive_profile WHERE user_id=? OR username=? LIMIT 1",
            (str(user_id), username or '')
        ).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════
# 异常检测、急救、告警投喂与 §14 12步骤自动立项 (v25.5)
# ════════════════════════════════════════════════════════════════
_heal_last_run = 0
_HEAL_INTERVAL = 60  # 每 60s 巡检一次

# 未登录访问计数 (5 分钟窗口, 超过阈值触发安全告警)
_unauth_window = []   # [(ts, path, ip), ...]
_UNAUTH_WINDOW_SEC = 300
_UNAUTH_THRESHOLD = 10  # 5 分钟内 > 10 次 → HIGH 安全告警

# 规则违反映射: 5 条异常 → rule_id + violation_code + severity + EigenFlux 专家团队
_HEAL_RULE_MAP = {
    'orphan_prehold': {
        'rule_id': 'MT_RULE_DEV', 'violation_code': 'CHAT-HEAL-ORPHAN-PREHOLD',
        'severity': 'MEDIUM', 'experts': ['DBA', '运维'],
        'title': '聊天原子结算完整性 — 残留 prehold 清理',
    },
    'balance_drift': {
        'rule_id': 'MT_RULE_SYS_OPS', 'violation_code': 'CHAT-HEAL-BALANCE-DRIFT',
        'severity': 'HIGH', 'experts': ['DBA', '安全', '架构'],
        'title': '聊天 token 账本一致性 — balance 连续性扶正',
    },
    'ledger_check': {
        'rule_id': 'MT_IRON_RULE_12STEPS', 'violation_code': 'CHAT-HEAL-LEDGER-SCHEMA',
        'severity': 'CRITICAL', 'experts': ['架构', '合规'],
        'title': '聊天总账 schema 完整性 — CHECK 约束扩展',
    },
    'ollama': {
        'rule_id': 'MT_RULE_AI_OPS', 'violation_code': 'CHAT-HEAL-OLLAMA-OFFLINE',
        'severity': 'HIGH', 'experts': ['AI', '运维'],
        'title': '本地 AI 引擎健康 — Ollama 离线恢复',
    },
    'unauth_access': {
        'rule_id': 'MT_RULE_PERM', 'violation_code': 'CHAT-HEAL-UNAUTH-ACCESS',
        'severity': 'HIGH', 'experts': ['安全', '架构', '合规'],
        'title': '聊天强制登录 — 未登录/guest/异常 session 访问拦截',
    },
}


def _ensure_alert_tables(conn):
    """确保告警链路 3 张表存在 (IF NOT EXISTS, 幂等)"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_eigenflux_consultation (
        consult_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id       TEXT,
        violation_code TEXT,
        expert_role   TEXT,
        flow_id       TEXT,
        detail        TEXT,
        status        TEXT DEFAULT 'PENDING',
        created_at    TEXT
    );
    CREATE TABLE IF NOT EXISTS mt_chat_heal_flow_binding (
        binding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        heal_type     TEXT,
        flow_id       TEXT,
        alert_id      TEXT,
        bound_at      REAL
    );
    """)


def _heal_alert_and_flow(conn, anomalies):
    """4 条异常中非 OK 的 → 告警投喂 + §14 12步骤自动立项 + AI 机团队认领

    链路:
    anomaly → mt_rule_violation_alert (alert_id)
           → mt_eigenflux_consultation (N 人专家团队)
           → mt_ai_brain_feed_log (脑库投喂)
           → mt_dev_flow_session (STEP_1_PROPOSAL 立项)
           → mt_chat_heal_flow_binding (heal_type ↔ flow_id 绑定, 防重复)
           → AI 机团队 sys_auto_hire / EigenFlux 专家团队 async 认领
    """
    import uuid as _uuid
    _ensure_alert_tables(conn)
    ts = time.time()
    iso_now = datetime.utcnow().isoformat()
    triggered = []

    for heal_type, ok, result, detail in anomalies:
        if ok:
            continue  # 仅非 OK 触发
        meta = _HEAL_RULE_MAP[heal_type]

        # ── 绑定表去重: 24h 内同一 heal_type 不重复立项 ──
        existing = conn.execute(
            "SELECT flow_id FROM mt_chat_heal_flow_binding WHERE heal_type=? AND bound_at > ? ORDER BY bound_at DESC LIMIT 1",
            (heal_type, ts - 86400)
        ).fetchone()
        if existing:
            sys.stderr.write(f"[CHAT-HEAL] type={heal_type} action=skip result=already bound to flow {existing['flow_id']} (24h)\n")
            continue

        # ── 1) 写 mt_rule_violation_alert ──
        alert_id = f"CHAT-HEAL-{heal_type}-{int(ts)}"
        violation_code = meta['violation_code']
        try:
            conn.execute(
                "INSERT OR IGNORE INTO mt_rule_violation_alert "
                "(alert_id, viol_id, alert_type, alert_target, alert_status, alert_payload, alert_sent_at, created_at, "
                "violation_code, severity, description, evidence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (alert_id, alert_id, 'chat_heal_anomaly', heal_type, 'TRIGGERED',
                 json.dumps({'heal_type': heal_type, 'result': result, 'detail': detail}, ensure_ascii=False),
                 ts, ts, violation_code, meta['severity'], meta['title'], detail or result)
            )
        except Exception:
            # rule_db.py 版本的 violation_alert 字段可能不同, 降级写最小集
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO mt_rule_violation_alert "
                    "(alert_id, violation_code, severity, description, evidence) VALUES(?,?,?,?,?)",
                    (alert_id, violation_code, meta['severity'], meta['title'], detail or result)
                )
            except Exception as e2:
                sys.stderr.write(f"[CHAT-HEAL] ❌ violation_alert write fail: {e2}\n")

        # ── 2) 写 mt_eigenflux_consultation (N 人专家团队) ──
        for role in meta['experts']:
            try:
                conn.execute(
                    "INSERT INTO mt_eigenflux_consultation "
                    "(rule_id, violation_code, expert_role, flow_id, detail, status, created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (meta['rule_id'], violation_code, role, '',
                     json.dumps({'heal_type': heal_type, 'severity': meta['severity'],
                                 'title': meta['title'], 'result': result}, ensure_ascii=False),
                     'PENDING', iso_now)
                )
            except Exception:
                pass  # 降级

        # ── 3) 写 mt_ai_brain_feed_log (脑库投喂) ──
        try:
            conn.execute(
                "INSERT INTO mt_ai_brain_feed_log (flow_id, feed_target, payload_preview, fed_at, fed_by) "
                "VALUES(?,?,?,?,?)",
                (alert_id, 'anomaly_heal',
                 json.dumps({'heal_type': heal_type, 'severity': meta['severity'],
                             'rule_id': meta['rule_id'], 'result': result}, ensure_ascii=False)[:200],
                 iso_now, 'CHAT-HEAL-v25.5')
            )
        except Exception:
            pass

        # ── 4) 自动立项 mt_dev_flow_session (STEP_1_PROPOSAL) ──
        flow_id = f"CHAT-HEAL-{heal_type.upper()}-{int(ts)}-{_uuid.uuid4().hex[:6]}"
        proposal = {
            'heal_type': heal_type, 'rule_id': meta['rule_id'],
            'violation_code': violation_code, 'severity': meta['severity'],
            'triggered_by': 'CHAT-HEAL before_request heal scan',
            'alert_id': alert_id, 'experts': meta['experts'],
        }
        try:
            conn.execute(
                "INSERT OR IGNORE INTO mt_dev_flow_session "
                "(flow_id, proposal_title, proposal_summary, proposal_json, current_step, "
                "created_by, created_at, updated_at, final_status) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (flow_id, meta['title'], result[:200],
                 json.dumps(proposal, ensure_ascii=False), 'STEP_1_PROPOSAL',
                 'CHAT-HEAL-v25.5', iso_now, iso_now, 'RUNNING')
            )
        except Exception as e3:
            sys.stderr.write(f"[CHAT-HEAL] ❌ dev_flow_session write fail: {e3}\n")

        # ── 5) 写绑定表 (防重复) ──
        conn.execute(
            "INSERT INTO mt_chat_heal_flow_binding (heal_type, flow_id, alert_id, bound_at) VALUES(?,?,?,?)",
            (heal_type, flow_id, alert_id, ts)
        )

        triggered.append((heal_type, flow_id, alert_id, meta['experts']))
        sys.stderr.write(
            f"[CHAT-HEAL] type={heal_type} action=alert+flow result=立项{flow_id} experts={meta['experts']} severity={meta['severity']}\n"
        )

    conn.commit()
    return triggered


def _heal_scan_and_fix():
    """5 条异常态检测 + 自动扶正 + 非 OK 触发 EigenFlux 告警 + §14 12步骤立项

    日志格式:
    [CHAT-HEAL] type=<类型> action=<scan|cleanup|repair|verify|ping|alert+flow|skip> result=<结果>
    """
    global _heal_last_run, _unauth_window
    now = time.time()
    if now - _heal_last_run < _HEAL_INTERVAL:
        return
    _heal_last_run = now

    anomalies = []  # [(heal_type, ok, result_str, detail_str)]

    try:
        conn = _db()
        logs = []

        # ── 日志 1: 残留 prehold 清理 ──
        orphans = conn.execute(
            "SELECT user_id, username, balance, total_preheld FROM mt_user_token_accounts WHERE total_preheld > 0"
        ).fetchall()
        if orphans:
            fixed_tokens = sum(r['total_preheld'] for r in orphans)
            for r in orphans:
                uid, bal, held = r['user_id'], r['balance'], r['total_preheld']
                conn.execute("UPDATE mt_user_token_accounts SET balance=balance-total_preheld, total_preheld=0 WHERE user_id=?", (uid,))
                conn.execute(
                    "INSERT INTO mt_user_token_ledger(user_id,change,type,detail,balance_after) VALUES(?,?,?,?,?)",
                    (uid, -held, 'release',
                     json.dumps({'reason': 'orphan_prehold_cleanup', 'fixed': True}, ensure_ascii=False),
                     bal - held)
                )
            conn.commit()
            msg = f"cleanup {len(orphans)} users fixed, restored {fixed_tokens} tokens"
            logs.append(f"[CHAT-HEAL] type=orphan_prehold action={msg}")
            anomalies.append(('orphan_prehold', False, msg, f'{len(orphans)} users, max_held={max(r["total_preheld"] for r in orphans)}'))
        else:
            logs.append(f"[CHAT-HEAL] type=orphan_prehold action=scan result=ok (0)")
            anomalies.append(('orphan_prehold', True, 'ok', ''))

        # ── 日志 2: balance 连续性修复 ──
        bad = []
        for row in conn.execute("SELECT user_id, username, balance, total_granted, total_consumed, total_rewarded FROM mt_user_token_accounts"):
            uid = row['user_id']
            if uid == 5: continue  # SA 豁免
            bal, granted, consumed, rewarded = row['balance'], row['total_granted'], row['total_consumed'], row['total_rewarded']
            expected = granted - consumed + rewarded
            drift = bal - expected
            if abs(drift) > 100:
                bad.append((uid, row['username'], bal, expected, drift))
        if bad:
            for uid, uname, bal, exp, drift in bad:
                conn.execute("UPDATE mt_user_token_accounts SET balance=? WHERE user_id=?", (exp, uid))
                conn.execute(
                    "INSERT INTO mt_user_token_ledger(user_id,change,type,detail,balance_after) VALUES(?,?,?,?,?)",
                    (uid, exp - bal, 'admin_adjust',
                     json.dumps({'reason': 'balance_consistency_heal', 'drift': drift, 'fixed': True}, ensure_ascii=False),
                     exp)
                )
            conn.commit()
            msg = f"repair {len(bad)} users fixed, max_drift={max(abs(r[4]) for r in bad)}"
            logs.append(f"[CHAT-HEAL] type=balance_drift action={msg}")
            anomalies.append(('balance_drift', False, msg,
                              ', '.join(f'{uname} drift={drift}' for _, uname, _, _, drift in bad[:5])))
        else:
            logs.append(f"[CHAT-HEAL] type=balance_drift action=scan result=ok (all continuous)")
            anomalies.append(('balance_drift', True, 'ok', ''))

        # ── 日志 3: ledger CHECK 约束检查 ──
        try:
            conn.execute("SELECT * FROM mt_user_token_ledger WHERE type IN ('prehold','release','reward','brain_feed') LIMIT 1")
            logs.append(f"[CHAT-HEAL] type=ledger_check action=verify result=ok (CHECK extended to 7 types)")
            anomalies.append(('ledger_check', True, 'ok', ''))
        except Exception as e:
            msg = f"FAIL needs_rebuild ({e})"
            logs.append(f"[CHAT-HEAL] type=ledger_check action=repair result={msg}")
            anomalies.append(('ledger_check', False, msg, str(e)))

        # ── 日志 4: Ollama 离线降级 ──
        try:
            import urllib.request
            urllib.request.urlopen(_resolve_ollama_host() + '/api/tags', timeout=3)
            logs.append(f"[CHAT-HEAL] type=ollama action=ping result=online")
            anomalies.append(('ollama', True, 'ok', ''))
        except Exception as e:
            msg = f"offline ({type(e).__name__}: {e})"
            logs.append(f"[CHAT-HEAL] type=ollama action=ping result={msg} ⚠️ 聊天将失败")
            anomalies.append(('ollama', False, msg, str(e)))

        # ── 日志 5: 未登录访问异常检测 (安全) ──
        # 清理过期窗口 + 统计
        _unauth_window[:] = [e for e in _unauth_window if now - e[0] < _UNAUTH_WINDOW_SEC]
        window_count = len(_unauth_window)
        window_paths = {}
        for ts, path, ip in _unauth_window:
            window_paths[path] = window_paths.get(path, 0) + 1
        if window_count > _UNAUTH_THRESHOLD:
            msg = f"detected {window_count} unauth accesses in {_UNAUTH_WINDOW_SEC}s (threshold={_UNAUTH_THRESHOLD})"
            top_paths = sorted(window_paths.items(), key=lambda x: -x[1])[:5]
            logs.append(f"[CHAT-HEAL] type=unauth_access action=alert result={msg} top_paths={top_paths}")
            anomalies.append(('unauth_access', False, msg, f'top_paths={top_paths}, recent_ips={list(set(e[2] for e in _unauth_window[-5:]))}'))
            _unauth_window.clear()  # 触发一次后清空窗口防重复
        elif window_count > 0:
            msg = f"ok ({window_count} in window, threshold={_UNAUTH_THRESHOLD})"
            logs.append(f"[CHAT-HEAL] type=unauth_access action=scan result={msg}")
            anomalies.append(('unauth_access', True, 'ok', ''))
        else:
            logs.append(f"[CHAT-HEAL] type=unauth_access action=scan result=ok (0)")
            anomalies.append(('unauth_access', True, 'ok', ''))

        # ── 非 OK → 告警投喂 + §14 12步骤立项 ──
        non_ok = [a for a in anomalies if not a[1]]
        if non_ok:
            triggered = _heal_alert_and_flow(conn, anomalies)
            for heal_type, flow_id, alert_id, experts in triggered:
                sys.stderr.write(
                    f"[CHAT-HEAL] ✅ type={heal_type} → EigenFlux experts={experts} 立项 {flow_id}\n"
                )

        # 输出 5 条到 stderr (Flask 日志)
        for l in logs:
            sys.stderr.write(l + "\n")
            sys.stderr.flush()

    except Exception as e:
        sys.stderr.write(f"[CHAT-HEAL] ❌ exception: {e}\n")
    finally:
        try: conn.close()
        except Exception: pass


# ── before_request hook: 实时未登录访问计数 + 触发 heal ──
@chat_local_bp.before_request
def _heal_before_request():
    """每次聊天路由请求:
    1) 未登录访问 → 实时计数 (5 分钟窗口, > 10 次触发安全告警)
    2) 60s 间隔 heal 巡检"""
    global _unauth_window
    try:
        uid = session.get('user_id')
        is_guest = (not uid or uid == 'guest')
        if is_guest:
            # 未登录访问 → 计数
            path = request.path
            ip = request.remote_addr or '?'
            _unauth_window.append((time.time(), path, ip))
            # 超过阈值 → 立即触发 heal (不等 60s 间隔)
            if len(_unauth_window) > _UNAUTH_THRESHOLD:
                sys.stderr.write(
                    f"[CHAT-HEAL] ⚠️ unauth_access burst: {len(_unauth_window)} hits → immediate alert\n"
                )
                _heal_scan_and_fix()
    except Exception:
        pass
    # 60s 间隔巡检
    _heal_scan_and_fix()


# ════════════════════════════════════════════════════════════════
# 路由
# ════════════════════════════════════════════════════════════════

@chat_local_bp.route('/local-chat', methods=['GET'])
def local_chat_page():
    """聊天页面 — 已登录正常进; 未登录自动建 guest wallet (10000 免费 token)
    flow_chat_guest_free_20261023: 不再强制登录引导, 游客也能直接聊"""
    from flask import render_template
    _uid = session.get('user_id')
    embed = request.args.get('embed') == '1'
    if not _uid or str(_uid).startswith('guest'):
        # 🔧 游客: 自动建 guest session + wallet (不跳引导页)
        dh = session.get('device_hash') or _device_hash()
        session['device_hash'] = dh
        guest_uid = f"guest_{dh}"
        session['user_id'] = guest_uid
        session['username'] = f"Guest_{dh[:8]}"
        session['role'] = 'guest'
        _ensure_guest_wallet(dh)
        bal = _get_balance(guest_uid)
        return render_template('local_chat.html', embed=embed,
            is_guest=True, username=f"Guest_{dh[:8]}",
            token_balance=bal['balance'], token_frozen=bal.get('frozen', 0))
    # 已登录
    u = _get_user()
    _ensure_daily_grant(u['user_id'], u['username'])
    bal = _get_balance(u['user_id'])
    return render_template('local_chat.html', embed=embed,
        is_guest=False, username=u.get('username', '用户'),
        token_balance=bal['balance'], token_frozen=bal.get('frozen', 0),
        is_sa=_is_sa(u))


@chat_local_bp.route('/ai', methods=['GET'])
def ai_entry():
    """🌐 mtos.site/ai — 公网聊天入口 (flow_chat_guest_free_20261023: 游客 1 万免费)"""
    from flask import render_template
    uid = session.get('user_id')
    embed = request.args.get('embed') == '1'
    if not uid or str(uid).startswith('guest'):
        dh = session.get('device_hash') or _device_hash()
        session['device_hash'] = dh
        session['user_id'] = f"guest_{dh}"
        session['username'] = f"Guest_{dh[:8]}"
        session['role'] = 'guest'
        _ensure_guest_wallet(dh)
        bal = _get_balance(f"guest_{dh}")
        return render_template('local_chat.html', embed=embed,
            is_guest=True, username=f"Guest_{dh[:8]}",
            token_balance=bal['balance'], token_frozen=bal.get('frozen', 0))
    u = _get_user()
    _ensure_daily_grant(u['user_id'], u['username'])
    bal = _get_balance(u['user_id'])
    return render_template('local_chat.html', embed=embed,
        is_guest=False, username=u.get('username', '用户'),
        token_balance=bal['balance'], token_frozen=bal.get('frozen', 0),
        is_sa=_is_sa(u))


@chat_local_bp.route('/ai/', methods=['GET'])
def ai_entry_slash():
    from flask import redirect
    return redirect('/ai', code=301)


# ════════════════════════════════════════════════════════════════
# flow_chat_embed_20261019: 冰山全局聊天助手注入
# ════════════════════════════════════════════════════════════════
# 单点全局注入 (after_app_request) — 覆盖冰山系统所有 text/html 页面,
# 包括独立模板 (不继承 base.html 的页面), 无需逐个修改 base 模板。
# 悬浮球 → 抽屉面板 → iframe 懒加载 /local-chat?embed=1 紧凑模式。
_MTCA_EXCLUDE_PREFIXES = ('/local-chat', '/ai', '/auth/login', '/api/')

_MTCA_WIDGET_SNIPPET = """
<!-- flow_chat_embed_20261019: 冰山全局聊天助手 (悬浮球+抽屉面板) -->
<!-- flow_chat_preload_20261019: 预加载登录状态容器 (徽标+hover预热+sid直达) -->
<div id="mtca-root">
  <button id="mtca-ball" aria-label="打开仙女座聊天助手" title="仙女座聊天助手">🧠<span id="mtca-badge"></span></button>
  <div id="mtca-panel" hidden>
    <div class="mtca-bar">
      <span class="mtca-dot"></span>
      <span class="mtca-title">仙女座聊天助手</span>
      <span class="mtca-user" id="mtca-username"></span>
      <a class="mtca-act" href="/local-chat" target="_blank" title="全屏打开">⤢</a>
      <button class="mtca-act" id="mtca-close" title="收起 (Esc)">✕</button>
    </div>
    <iframe id="mtca-frame" title="仙女座聊天助手面板" data-src="/local-chat?embed=1"></iframe>
  </div>
</div>
<style id="mtca-style">
  #mtca-root{position:fixed;right:22px;bottom:22px;z-index:2147483000;font-family:-apple-system,"SF Pro","PingFang SC","Helvetica Neue",sans-serif}
  #mtca-ball{position:relative;width:56px;height:56px;border-radius:50%;border:none;cursor:pointer;font-size:26px;line-height:1;background:linear-gradient(135deg,#06b6d4,#a855f7);color:#fff;box-shadow:0 6px 24px rgba(6,182,212,.45),0 2px 8px rgba(0,0,0,.3);transition:transform .18s ease,box-shadow .18s ease}
  #mtca-ball:hover{transform:scale(1.08);box-shadow:0 8px 30px rgba(168,85,247,.55)}
  #mtca-ball:active{transform:scale(.96)}
  #mtca-badge{position:absolute;top:-3px;right:-3px;width:20px;height:20px;border-radius:50%;font-size:11px;font-weight:700;line-height:16px;display:none;align-items:center;justify-content:center;border:2px solid rgba(11,10,30,.9)}
  #mtca-badge.in{display:flex;background:linear-gradient(135deg,#6ee7b7,#06b6d4);color:#04283a}
  #mtca-badge.out{display:flex;background:#f87171;color:#fff}
  #mtca-panel{position:fixed;right:12px;bottom:90px;width:min(430px,calc(100vw - 24px));height:min(640px,calc(100vh - 110px));display:flex;flex-direction:column;background:#0B0A1E;border:1px solid rgba(6,182,212,.35);border-radius:16px;overflow:hidden;box-shadow:0 18px 60px rgba(0,0,0,.55),0 0 0 1px rgba(168,85,247,.12)}
  #mtca-panel[hidden]{display:none}
  .mtca-bar{flex-shrink:0;display:flex;align-items:center;gap:8px;padding:10px 12px;background:rgba(6,182,212,.08);border-bottom:1px solid rgba(6,182,212,.25)}
  .mtca-dot{width:8px;height:8px;border-radius:50%;background:#6ee7b7;box-shadow:0 0 6px #6ee7b7}
  .mtca-title{flex:1;min-width:0;font-size:13px;font-weight:600;color:#f8fafc;letter-spacing:.5px}
  .mtca-user{font-size:11px;color:#6ee7b7;flex-shrink:0;max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .mtca-act{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:26px;border-radius:8px;cursor:pointer;border:1px solid rgba(255,255,255,.14);background:transparent;color:rgba(248,250,252,.7);font-size:12px;text-decoration:none;transition:all .15s}
  .mtca-act:hover{color:#06b6d4;border-color:#06b6d4}
  #mtca-frame{flex:1;min-height:0;width:100%;border:none;background:#0B0A1E}
  @media (max-width:520px){
    #mtca-root{right:14px;bottom:14px}
    #mtca-panel{right:8px;bottom:84px;width:calc(100vw - 16px);height:calc(100vh - 100px)}
  }
</style>
<script id="mtca-script">
(function(){
  var ball=document.getElementById('mtca-ball'),panel=document.getElementById('mtca-panel'),frame=document.getElementById('mtca-frame');
  var badge=document.getElementById('mtca-badge'),uname=document.getElementById('mtca-username');
  var st=null,warmed=false;
  /* flow_chat_preload_20261019: 页面加载即预取登录状态容器 */
  function preload(){
    try{
      fetch('/api/local-chat/widget-state',{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(d){
        if(!d||!d.success)return; st=d;
        if(d.logged_in){
          badge.textContent=(d.username||'?').charAt(0).toUpperCase();
          badge.className='in';
          uname.textContent=d.is_sa?(d.username+'·SA'):d.username;
          ball.title='仙女座聊天助手 · '+d.username+' (余额 '+d.token_balance+')';
          if(d.latest_session_id){
            frame.setAttribute('data-src','/local-chat?embed=1&sid='+encodeURIComponent(d.latest_session_id));
          }
          ball.addEventListener('mouseenter',warm); /* hover 预热 */
        }else{
          badge.textContent='🔒'; badge.className='out';
          ball.title='仙女座聊天助手 · 未登录';
        }
      }).catch(function(){});
    }catch(e){}
  }
  function warm(){
    if(warmed||!st||!st.logged_in)return;
    warmed=true; frame.src=frame.getAttribute('data-src'); /* 静默预热 */
  }
  function postCtx(){
    /* flow_chat_all7_20261019 F4: 把当前页面上下文推给聊天助手 */
    try{
      frame.contentWindow.postMessage({type:'mtscos-page-ctx',path:location.pathname,title:document.title},'*');
    }catch(e){}
  }
  function open(){
    panel.hidden=false;
    if(!frame.src)frame.src=frame.getAttribute('data-src'); /* 首次加载后会话跨页保持 */
    ball.style.display='none';
    postCtx();
  }
  function close(){panel.hidden=true;ball.style.display='';}
  ball.addEventListener('click',open);
  document.getElementById('mtca-close').addEventListener('click',close);
  frame.addEventListener('load',postCtx);
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!panel.hidden)close();});
  preload();
})();
</script>
"""


@chat_local_bp.after_app_request
def _inject_chat_assistant(response):
    """冰山全局聊天助手 — 所有 text/html 200 页面 </body> 前注入悬浮球.

    跳过: 非200/非HTML / 聊天页自身(/local-chat,/ai) / 登录页 / API/SSE / 未登录。
    注入失败静默降级, 不影响原响应 (fail-open 仅装饰性内容)。"""
    try:
        if response.status_code != 200 or response.mimetype != 'text/html':
            return response
        path = request.path or ''
        if path.startswith(_MTCA_EXCLUDE_PREFIXES):
            return response
        uid = session.get('user_id')
        if not uid or uid == 'guest':
            return response
        body = response.get_data(as_text=True)
        if '</body>' not in body:
            return response
        head, _, tail = body.rpartition('</body>')
        response.set_data(head + _MTCA_WIDGET_SNIPPET + '</body>' + tail)
    except Exception:
        pass
    return response


@chat_local_bp.route('/api/local-chat/session', methods=['POST'])
@_login_required
def create_session():
    """创建新会话 (支持 auto_title: 传入 first_message 自动命名)"""
    u = _get_user()
    sid = str(uuid.uuid4())
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data = request.get_json(silent=True) or {}
    user_title = (data.get('title') or '').strip()
    user_emoji = (data.get('title_emoji') or '💬').strip()[:2]
    first_msg = data.get('first_message') or ''

    title = user_title or (
        _auto_title_first_msg(first_msg) if first_msg else f"{u['username']}的新对话"
    )
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO chat_sessions(session_id,user_id,username,title,title_emoji,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (sid, u['user_id'], u['username'], title, user_emoji, now, now)
        )
        conn.commit()
        conn.close()
        _record_action(sid, u['user_id'], 'new_session', {'username': u['username'], 'auto_title': not bool(user_title)})
        return jsonify({'success': True, 'session_id': sid, 'title': title, 'title_emoji': user_emoji, 'created_at': now})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/session/<sid>/title', methods=['PUT'])
@_login_required
def update_session_title(sid):
    """修改会话 title 或 emoji (画笔 icon)"""
    u = _get_user()
    data = request.get_json(silent=True) or {}
    new_title = (data.get('title') or '').strip() or None
    new_emoji = (data.get('title_emoji') or '').strip()[:2] or None
    try:
        conn = _db()
        # 权限校验: 只能改自己的 session
        owner = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (sid,)
        ).fetchone()
        if not owner or owner['user_id'] != u['user_id']:
            conn.close()
            return jsonify({'success': False, 'error': '无权修改'}), 403

        fields, values = [], []
        if new_title:
            fields.append('title=?')
            values.append(new_title)
        if new_emoji:
            fields.append('title_emoji=?')
            values.append(new_emoji)
        if not fields:
            conn.close()
            return jsonify({'success': False, 'error': '无修改项'}), 400
        fields.append("updated_at=datetime('now','localtime')")
        values.append(sid)
        conn.execute(f"UPDATE chat_sessions SET {','.join(fields)} WHERE session_id=?", values)
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'title': new_title, 'title_emoji': new_emoji})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ════════════════════════════════════════════════════════════════
# 置顶/标签 + 日程助手 (flow_chat_all7_20261019)
# ════════════════════════════════════════════════════════════════
@chat_local_bp.route('/api/local-chat/widget-state', methods=['GET'])
def widget_state():
    """悬浮球预加载登录状态容器 — 查 mt_token_wallets (含游客)"""
    try:
        uid = session.get('user_id')
        if not uid:
            return jsonify({'success': True, 'logged_in': False})
        is_guest = str(uid).startswith('guest_')
        username = session.get('username') or ('Guest' if is_guest else '用户')
        conn = _db()
        # 🔧 flow_chat_guest_free_20261023: 优先 mt_token_wallets (含游客)
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_token_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE, username TEXT,
            is_guest INTEGER DEFAULT 0, guest_device_hash TEXT, balance INTEGER DEFAULT 0,
            frozen INTEGER DEFAULT 0, guest_free_grant INTEGER DEFAULT 0,
            guest_consumed INTEGER DEFAULT 0, expires_at TEXT, created_at TEXT, updated_at TEXT)""")
        bal_row = conn.execute(
            "SELECT balance, frozen, is_guest, guest_free_grant FROM mt_token_wallets WHERE user_id=?",
            (str(uid),)).fetchone()
        balance = bal_row['balance'] if bal_row else 0
        frozen = bal_row['frozen'] if bal_row else 0
        wallet_is_guest = bool(bal_row['is_guest']) if bal_row else is_guest
        latest = conn.execute(
            "SELECT session_id, title FROM chat_sessions WHERE user_id=? "
            "ORDER BY COALESCE(pinned,0) DESC, updated_at DESC LIMIT 1", (str(uid),)).fetchone()
        conn.close()
        return jsonify({
            'success': True, 'logged_in': True,
            'username': username,
            'is_guest': wallet_is_guest,
            'token_balance': balance,
            'token_frozen': frozen,
            'guest_free_grant': bal_row['guest_free_grant'] if bal_row else 0,
            'is_sa': (not wallet_is_guest) and _is_sa({'username': username}),
            'latest_session_id': latest['session_id'] if latest else None,
            'latest_session_title': latest['title'] if latest else None,
            'vision_ready': _detect_vision_model() is not None,
        })
    except Exception as e:
        return jsonify({'success': False, 'logged_in': False, 'error': str(e)})


@chat_local_bp.route('/api/local-chat/session/<sid>/pin', methods=['PUT'])
@_login_required
def toggle_session_pin(sid):
    """会话置顶切换 (仅本人/SA)"""
    u = _get_user()
    try:
        conn = _db()
        row = conn.execute("SELECT user_id, COALESCE(pinned,0) AS pinned FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
        if not row or (row['user_id'] != u['user_id'] and not _is_sa(u)):
            conn.close()
            return jsonify({'success': False, 'error': '无权操作'}), 403
        new_val = 0 if row['pinned'] else 1
        conn.execute("UPDATE chat_sessions SET pinned=?, updated_at=datetime('now','localtime') WHERE session_id=?", (new_val, sid))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'pinned': new_val})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/session/<sid>/tags', methods=['PUT'])
@_login_required
def set_session_tags(sid):
    """会话标签 (逗号分隔字符串, 仅本人/SA)"""
    u = _get_user()
    data = request.get_json(silent=True) or {}
    tags = (data.get('tags') or '').strip()[:120]
    try:
        conn = _db()
        row = conn.execute("SELECT user_id FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()
        if not row or (row['user_id'] != u['user_id'] and not _is_sa(u)):
            conn.close()
            return jsonify({'success': False, 'error': '无权操作'}), 403
        conn.execute("UPDATE chat_sessions SET tags=?, updated_at=datetime('now','localtime') WHERE session_id=?", (tags, sid))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'tags': tags})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _parse_schedule_text(raw):
    """解析 '/日程 [今天|明天|后天] [HH:MM或X点X分] 事项' → (title, due_at)
    日期缺省=今天; 时间缺省=仅日期。返回 title=None 表示无法解析。"""
    body = re.sub(r'^/日程\s*', '', (raw or '').strip())
    if not body:
        return None, ''
    day_map = {'今天': 0, '明天': 1, '后天': 2}
    due_day = None
    m = re.match(r'^(今天|明天|后天)\s*', body)
    if m:
        due_day = day_map[m.group(1)]
        body = body[m.end():]
    hm = None
    m2 = re.match(r'^(\d{1,2})[:：](\d{1,2})\s*', body) or re.match(r'^(\d{1,2})点(?:(\d{1,2})分?)?\s*', body)
    if m2:
        h, mi = int(m2.group(1)), int(m2.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            hm = f"{h:02d}:{mi:02d}"
            body = body[m2.end():]
    title = body.strip()
    if not title:
        return None, ''
    due_at = ''
    if due_day is not None or hm:
        from datetime import timedelta
        base = datetime.now() + timedelta(days=due_day or 0)
        due_at = base.strftime('%Y-%m-%d') + (f' {hm}' if hm else '')
    return title, due_at


@chat_local_bp.route('/api/local-chat/schedule', methods=['POST'])
@_login_required
def schedule_create():
    """日程助手: /日程 命令入口 — 解析自然时间并落库, 可选同步进会话消息流"""
    u = _get_user()
    data = request.get_json(silent=True) or {}
    raw = (data.get('text') or '').strip()
    sid = (data.get('session_id') or '').strip()
    title, due_at = _parse_schedule_text(raw)
    if not title:
        return jsonify({'success': False, 'error': 'bad_format',
                        'message': '格式: /日程 [今天|明天|后天] [14:30] 事项\n例: /日程 明天14:30 与导师开会'}), 400
    try:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO mt_chat_schedule(user_id,username,title,due_at,session_id) VALUES(?,?,?,?,?)",
            (u['user_id'], u['username'], title, due_at, sid))
        sched_id = cur.lastrowid
        reply = ''
        if sid:
            reply = (f"📅 日程已创建 #{sched_id}\n\n📌 {title}\n🕐 {due_at or '未定时间 (待办)'}\n\n"
                     f"用 /日程 查看, 或点 header 📅 管理全部日程。")
            _save_message(sid, u['user_id'], 'user', raw)
            _save_message(sid, u['user_id'], 'assistant', reply)
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': sched_id, 'title': title, 'due_at': due_at, 'reply': reply if sid else ''})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/schedule', methods=['GET'])
@_login_required
def schedule_list():
    """我的日程列表 (未完成在前, 按到期排序)"""
    u = _get_user()
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT id, title, due_at, status, created_at FROM mt_chat_schedule "
            "WHERE user_id=? ORDER BY status='done', CASE WHEN due_at='' THEN 1 ELSE 0 END, due_at, id DESC LIMIT 100",
            (u['user_id'],)).fetchall()
        conn.close()
        return jsonify({'success': True, 'count': len(rows), 'schedules': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/schedule/<int:sched_id>/done', methods=['PUT'])
@_login_required
def schedule_done(sched_id):
    """标记日程完成"""
    u = _get_user()
    try:
        conn = _db()
        row = conn.execute("SELECT user_id FROM mt_chat_schedule WHERE id=?", (sched_id,)).fetchone()
        if not row or (row['user_id'] != u['user_id'] and not _is_sa(u)):
            conn.close()
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        conn.execute("UPDATE mt_chat_schedule SET status='done', done_at=datetime('now','localtime') WHERE id=?", (sched_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': sched_id, 'status': 'done'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/session/<sid>', methods=['DELETE'])
@_login_required
def delete_session(sid):
    """删除会话: 级联清 messages/actions/inflection_points, 记录删除动作 (flow_chat_enhance_20261019)"""
    u = _get_user()
    try:
        conn = _db()
        owner = conn.execute(
            "SELECT user_id, username FROM chat_sessions WHERE session_id=?", (sid,)
        ).fetchone()
        if not owner or (owner['user_id'] != u['user_id'] and not _is_sa(u)):
            conn.close()
            return jsonify({'success': False, 'error': '无权删除'}), 403
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM chat_actions WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM chat_inflection_points WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (sid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'deleted': sid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/session/<sid>/inflections', methods=['GET'])
@_login_required
def session_inflections(sid):
    """会话拐点明细 — 发散思维 v2 拐点面板数据源 (flow_diverge_v2_20261019)"""
    u = _get_user()
    try:
        conn = _db()
        owner = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (sid,)
        ).fetchone()
        if not owner or (owner['user_id'] != u['user_id'] and not _is_sa(u)):
            conn.close()
            return jsonify({'success': False, 'error': '无权查看'}), 403
        rows = conn.execute(
            "SELECT inflection_type, trigger_text, quality_score, created_at "
            "FROM chat_inflection_points WHERE session_id=? ORDER BY id DESC LIMIT 100",
            (sid,)).fetchall()
        conn.close()
        return jsonify({'success': True, 'count': len(rows), 'inflections': [
            {'type': r['inflection_type'], 'trigger': r['trigger_text'],
             'quality': r['quality_score'], 'at': r['created_at']} for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ════════════════════════════════════════════════════════════════
# 拐点全局统计 + Sparks 认知画像个性化 (flow_full_enhance_20261019)
# ════════════════════════════════════════════════════════════════

@chat_local_bp.route('/inflection-stats', methods=['GET'])
@_login_required
def inflection_stats_page():
    """拐点全局统计页 — 跨会话趋势 + 发散度聚合 (登录即可用, SA 可切全部)"""
    from flask import render_template
    u = _get_user()
    return render_template('inflection_stats.html', is_sa=_is_sa(u), username=u['username'])


@chat_local_bp.route('/api/local-chat/inflection-stats', methods=['GET'])
@_login_required
def inflection_stats_api():
    """跨会话拐点全局统计 — 按类型/日趋势/Top会话/质量聚合

    权限: 默认仅本人数据; ?scope=all 且 SA → 全部用户数据, 其他用户 403"""
    u = _get_user()
    scope_all = (request.args.get('scope') == 'all')
    if scope_all and not _is_sa(u):
        return jsonify({'success': False, 'error': 'perm_denied', 'message': '仅 SA 可查看全部'}), 403
    where = '1=1' if scope_all else 'user_id=?'
    params = [] if scope_all else [u['user_id']]
    try:
        conn = _db()
        totals = conn.execute(
            f"SELECT COUNT(*) total, "
            f"COUNT(DISTINCT session_id) sessions, "
            f"ROUND(AVG(quality_score),2) avg_quality, "
            f"SUM(CASE WHEN inflection_type='diverge' THEN 1 ELSE 0 END) diverge_cnt, "
            f"SUM(CASE WHEN fed_to_brain=1 THEN 1 ELSE 0 END) fed_cnt "
            f"FROM chat_inflection_points WHERE {where}", params).fetchone()
        by_type = conn.execute(
            f"SELECT inflection_type, COUNT(*) cnt, ROUND(AVG(quality_score),2) avg_q "
            f"FROM chat_inflection_points WHERE {where} "
            f"GROUP BY inflection_type ORDER BY cnt DESC", params).fetchall()
        daily = conn.execute(
            f"SELECT date(created_at) d, COUNT(*) cnt FROM chat_inflection_points "
            f"WHERE {where} AND created_at >= datetime('now','localtime','-13 days') "
            f"GROUP BY date(created_at) ORDER BY d", params).fetchall()
        top_sessions = conn.execute(
            f"SELECT i.session_id, s.title, s.title_emoji, COUNT(*) cnt, MAX(i.created_at) last_at "
            f"FROM chat_inflection_points i LEFT JOIN chat_sessions s ON s.session_id=i.session_id "
            f"WHERE {where.replace('user_id', 'i.user_id')} "
            f"GROUP BY i.session_id ORDER BY cnt DESC LIMIT 10", params).fetchall()
        conn.close()
        total = totals['total'] or 0
        diverge_cnt = totals['diverge_cnt'] or 0
        return jsonify({
            'success': True,
            'scope': 'all' if scope_all else 'self',
            'is_sa': _is_sa(u),
            'totals': {
                'total': total,
                'sessions': totals['sessions'] or 0,
                'avg_quality': totals['avg_quality'] or 0,
                'diverge_ratio': round(diverge_cnt / total, 3) if total else 0,
                'fed_cnt': totals['fed_cnt'] or 0,
            },
            'by_type': [{'type': r['inflection_type'], 'cnt': r['cnt'], 'avg_q': r['avg_q']} for r in by_type],
            'daily': [{'d': r['d'], 'cnt': r['cnt']} for r in daily],
            'top_sessions': [{'session_id': r['session_id'], 'title': r['title'] or '(已删除会话)',
                              'title_emoji': r['title_emoji'] or '💬', 'cnt': r['cnt'],
                              'last_at': r['last_at']} for r in top_sessions],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Sparks 个性化映射 — 学习风格 → 第1条; 认知水平 → 第2条; 学科 → 第3条隐喻
_SPARK_STYLE_MAP = [
    ('视觉|visual', '🖼️ 画一张图解释', '用一张文字示意图或流程图的形式重新解释你刚才的回答'),
    ('听觉|口语|auditory', '🗣️ 换个说法讲给我听', '用更口语化的方式把刚才的回答重新讲一遍'),
    ('动手|实践|操作|kinesthetic', '🛠️ 给我一个动手练习', '针对刚才的内容给我设计一个可以马上动手做的小练习'),
    ('阅读|reading', '📖 再深入展开讲讲', '把刚才回答里最关键的一点展开成更详细的分析'),
]
_SPARK_LEVEL_MAP = [
    ('入门|初学|零基础|beginner', '🧒 用最简单的话再讲一遍', '假设我是完全的初学者, 用最通俗的语言重新解释刚才的回答'),
    ('高级|专家|深度|advanced', '🎓 边界与反例', '这个结论的适用边界是什么? 有没有反例或容易被误用的场景?'),
]
_SPARK_DEFAULTS = [
    {'label': '🔄 换个视角再答', 'prompt': '换个全新的视角重新回答我刚才的问题'},
    {'label': '🪞 反过来会怎样', 'prompt': '如果把我刚才问题的结论反过来, 什么情况下反而成立?'},
    {'label': '🌈 用一个隐喻解释', 'prompt': '用一个生活中的隐喻或类比重新解释你刚才的回答'},
]


@chat_local_bp.route('/api/local-chat/sparks', methods=['GET'])
@_login_required
def personalized_sparks():
    """认知画像个性化发散追问 — 读 mt_user_cognitive_profile 按 style/level/学科动态生成

    无画像/查询失败 → 返回与前端固定版一致的 3 条默认追问 (前端亦有同款回退)"""
    u = _get_user()
    sparks = list(_SPARK_DEFAULTS)
    profile_used = False
    try:
        profile = _get_cognitive_profile(u['user_id'], u['username'])
        if profile:
            profile_used = True
            style = (profile.get('learning_style') or '').strip()
            level = (profile.get('cognitive_level') or '').strip()
            subject = (profile.get('focus_subjects') or '').strip()
            if style:
                for pat, label, prompt in _SPARK_STYLE_MAP:
                    if re.search(pat, style, re.I):
                        sparks[0] = {'label': label, 'prompt': prompt}
                        break
            if level:
                for pat, label, prompt in _SPARK_LEVEL_MAP:
                    if re.search(pat, level, re.I):
                        sparks[1] = {'label': label, 'prompt': prompt}
                        break
                else:
                    if re.search('中级|进阶|intermediate', level, re.I):
                        pass  # 中级保持默认
            if subject and len(subject) <= 12:
                sparks[2] = {'label': f'🌈 用{subject}的隐喻解释',
                             'prompt': f'用一个{subject}领域里的隐喻或类比重新解释你刚才的回答'}
    except Exception:
        profile_used = False
    return jsonify({'success': True, 'profile_used': profile_used, 'sparks': sparks})


@chat_local_bp.route('/api/local-chat/sessions', methods=['GET'])
@_login_required
def list_sessions():
    """我的会话列表 (置顶优先)"""
    u = _get_user()
    try:
        conn = _db()
        # v22.25.27: 跨库列兼容 — 旧库缺 title_emoji/pinned/tags, 缺失列给默认值
        _cols = {r[1] for r in conn.execute('PRAGMA table_info(chat_sessions)')}
        _emoji = 's.title_emoji' if 'title_emoji' in _cols else "'' AS title_emoji"
        _pinned = 'COALESCE(s.pinned,0)' if 'pinned' in _cols else '0'
        _tags = "COALESCE(s.tags,'')" if 'tags' in _cols else "''"
        # flow_chat_upgrade5_20261022: 会话级未读 (TH-20261022-0001)
        # 依据 chat_read_state.last_read_id 统计「比我上次已读更新」的消息条数,
        # 该表由 andromeda_chat_bp._ensure 懒建; 旧库未建时降级 unread=0 不报错。
        _has_read = False
        try:
            _has_read = bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_read_state'").fetchone())
        except sqlite3.Error:
            _has_read = False
        if _has_read:
            _unread = (
                "(SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.session_id"
                " AND COALESCE(m.deleted,0)=0 AND COALESCE(m.role,'')<>'system'"
                " AND m.id > COALESCE((SELECT r.last_read_id FROM chat_read_state r"
                "   WHERE r.session_id=s.session_id AND r.user_id=?),0))")
        else:
            _unread = '0'
        rows = conn.execute(
            f"SELECT s.session_id, s.title, {_emoji}, s.message_count, s.last_message, s.created_at, s.updated_at, "
            f"{_pinned} AS pinned, {_tags} AS tags, "
            f"{_unread} AS unread "
            "FROM chat_sessions s "
            "WHERE s.user_id=? "
            "ORDER BY pinned DESC, s.updated_at DESC LIMIT 50",
            ((u['user_id'],) if _has_read else ()) + (u['user_id'],)
        ).fetchall()
        conn.close()
        return jsonify({'success': True, 'sessions': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/balance', methods=['GET'])
@_login_required
def token_balance():
    """我的 token 余额 + 最近流水 — 游客/注册用户通用"""
    uid = session.get('user_id', '')
    is_guest = str(uid).startswith('guest')
    username = session.get('username', 'Guest' if is_guest else '用户')
    sa_exempt = False
    # 注册用户才查 SA + 每日赠送
    if not is_guest:
        try:
            u = _get_user()
            sa_exempt = _is_sa(u)
            if not sa_exempt:
                _ensure_daily_grant(u['user_id'], u.get('username', '用户'))
        except Exception:
            pass
    bal = _get_balance(uid)
    bal['granted_today'] = False  # 游客不参与每日赠送
    bal['sa_exempt'] = sa_exempt
    bal['is_guest'] = is_guest
    if sa_exempt:
        bal['message'] = 'SA 豁免模式: 不限用量, 不消耗 token'
    # 最近 20 条流水 (游客可能没有)
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT change, type, session_id, detail, balance_after, created_at "
            "FROM mt_user_token_ledger WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (str(uid),)
        ).fetchall()
        conn.close()
        bal['ledger'] = [dict(r) for r in rows]
    except Exception:
        bal['ledger'] = []
    return jsonify({'success': True, **bal})


@chat_local_bp.route('/api/local-chat/admin-adjust', methods=['POST'])
@_login_required
def token_admin_adjust():
    """SA 专属: 给指定用户调整 token 额度 (admin_adjust ledger)
    body: {username: str, amount: int(+充/-扣), reason: str}"""
    u = _get_user()
    if not _is_sa(u):
        return jsonify({'success': False, 'error': 'forbidden',
                        'message': '仅超级管理员 (SA) 可执行额度调整'}), 403
    data = request.get_json() if request.is_json else {}
    target_name = (data.get('username') or '').strip()
    try:
        amount = int(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'bad_amount'}), 400
    reason = (data.get('reason') or '').strip()[:200]
    if not target_name or amount == 0:
        return jsonify({'success': False, 'error': 'bad_params',
                        'required': {'username': 'str', 'amount': 'int(+充/-扣)'}}), 400

    conn = _db()
    try:
        trow = conn.execute(
            "SELECT id, username FROM users WHERE username=?", (target_name,)
        ).fetchone()
        if trow is None:
            return jsonify({'success': False, 'error': 'user_not_found',
                            'username': target_name}), 404
        target_id = trow['id']
        today = datetime.now().strftime('%Y-%m-%d')
        acc = conn.execute(
            "SELECT balance FROM mt_user_token_accounts WHERE user_id=?", (target_id,)
        ).fetchone()
        if acc is None:
            # 目标账户不存在: 先建户 (零赠送) 再调整
            conn.execute(
                "INSERT INTO mt_user_token_accounts(user_id,username,balance,last_grant_date) "
                "VALUES(?,?,0,'')", (target_id, target_name))
            old_balance = 0
        else:
            old_balance = acc['balance']
        new_balance = max(0, old_balance + amount)  # 不可扣为负
        real_change = new_balance - old_balance
        conn.execute(
            "UPDATE mt_user_token_accounts SET balance=?, updated_at=datetime('now','localtime') "
            "WHERE user_id=?", (new_balance, target_id))
        conn.execute(
            "INSERT INTO mt_user_token_ledger(user_id,change,type,session_id,detail,balance_after) "
            "VALUES(?,?,?,?,?,?)",
            (target_id, real_change, 'admin_adjust', '',
             json.dumps({'by_sa': u['username'], 'reason': reason}, ensure_ascii=False),
             new_balance))
        conn.commit()
        return jsonify({'success': True, 'username': target_name,
                        'change': real_change, 'balance': new_balance,
                        'by': u['username']})
    except Exception as e:
        sys.stderr.write(f"[CHAT-LOCAL] admin_adjust error: {e}\n")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()


@chat_local_bp.route('/api/local-chat/history', methods=['GET'])
@_login_required
def get_history():
    """拉取会话历史"""
    u = _get_user()
    sid = request.args.get('session_id', '')
    if not sid:
        return jsonify({'success': False, 'error': 'missing session_id'}), 400
    try:
        conn = _db()
        # 权限检查: 本人 / SA
        row = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (sid,)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        if not (row['user_id'] == u['user_id'] or _is_sa(u)):
            conn.close()
            return jsonify({'success': False, 'error': 'forbidden'}), 403
        # flow_chat_upgrade5_20261022: 历史分页 (TH-20261022-0002)
        # limit: 取最近 N 条 (0/缺省 = 全量, 兼容旧前端)
        # before_id: 加载更早 (游标向左);  after_id: 增量拉新 (断线补拉)
        try:
            limit = int(request.args.get('limit') or 0)
        except (TypeError, ValueError):
            limit = 0
        limit = max(0, min(limit, 500))
        try:
            before_id = int(request.args.get('before_id') or 0)
            after_id = int(request.args.get('after_id') or 0)
        except (TypeError, ValueError):
            before_id = after_id = 0
        total = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id=?",
                             (sid,)).fetchone()[0]
        sql = ("SELECT id, role, content, reasoning, tokens, model, created_at "
               "FROM chat_messages WHERE session_id=?")
        params = [sid]
        if before_id > 0:
            sql += " AND id<?"
            params.append(before_id)
        if after_id > 0:
            sql += " AND id>?"
            params.append(after_id)
        if limit:
            rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(sql + " ORDER BY id ASC", params).fetchall()
        msgs = [dict(m) for m in rows]
        min_id = msgs[0]['id'] if msgs else 0
        max_id = msgs[-1]['id'] if msgs else 0
        has_more = False
        if limit and before_id > 0 and min_id:
            has_more = bool(conn.execute(
                "SELECT 1 FROM chat_messages WHERE session_id=? AND id<? LIMIT 1",
                (sid, min_id)).fetchone())
        elif limit and not before_id and not after_id and min_id:
            # 首屏: 是否还有更早消息 (供「加载更早」按钮)
            has_more = total > len(msgs)
        conn.close()
        return jsonify({'success': True, 'messages': msgs, 'total': total,
                        'min_id': min_id, 'max_id': max_id, 'has_more': has_more})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_local_bp.route('/api/local-chat/send', methods=['POST'])
@_login_required
def send_message():
    """
    发送消息 + SSE 流式接收 AI 回复 (v25.5 完整结算)
    三阶段: 预扣入口 → 生成中 → 实扣+退差+奖励结算
    """
    u = _get_user()
    data = request.get_json() if request.is_json else {}
    sid = data.get('session_id', '')
    user_text = (data.get('message') or '').strip()

    if not user_text:
        return jsonify({'success': False, 'error': 'empty_message'}), 400

    # ── 选择模型: 前端传 → 用前端; 否则读 OLLAMA_MODEL env; 再后备 qwen2.5:14b ──
    model = data.get('model') or os.environ.get('OLLAMA_MODEL') or 'qwen2.5:14b'

    # ── flow_chat_all7_20261019: 多模态图片 + 页面上下文携带 ──
    image_data_url = (data.get('image') or '').strip()
    page_context = (data.get('page_context') or '').strip()[:600]
    image_b64 = None
    if image_data_url:
        if not image_data_url.startswith('data:image/') or ';base64,' not in image_data_url:
            return jsonify({'success': False, 'error': 'bad_image', 'message': '仅支持 data:image/*;base64 格式'}), 400
        image_b64 = image_data_url.split(';base64,', 1)[1]
        if len(image_b64) > 6_000_000:  # ≈4.5MB 原图
            return jsonify({'success': False, 'error': 'image_too_large', 'message': '图片过大 (上限约 4.5MB)'}), 413
        vision_model = _detect_vision_model()
        if not vision_model:
            return jsonify({'success': False, 'error': 'no_vision_model',
                            'message': '服务器暂无视觉模型 (llava/qwen2.5vl/moondream 均可), 请联系 SA 执行: ollama pull qwen2.5vl:3b'}), 503
        model = vision_model

    # ── Token 计费 v25.5: 每日赠送 + 预扣拦截 ──
    sa_exempt = _is_sa(u)
    prehold_result = None
    estimated_cost = 0
    if not sa_exempt:
        grant = _ensure_daily_grant(u['user_id'], u['username'])
        # 预估: 按 prompt≈user_text×1.5 近似 + completion 预设 200
        est_prompt = max(50, int(len(user_text) * 1.5) + 200)  # +200 留给 system prompt
        est_completion = 300  # 预设 300 completion token
        est = _estimate_cost(model, est_prompt, est_completion)
        estimated_cost = est['total_cost']
        # 实时预估拦截 (余额 < 预估 → 402)
        if grant['balance'] < estimated_cost:
            return jsonify({
                'success': False, 'error': 'tokens_insufficient',
                'message': f'余额 {grant["balance"]} token, 预估需要 {estimated_cost} token (含模型倍率 {est["pricing"]["model_weight"]}x)',
                'balance': grant['balance'], 'estimated_cost': estimated_cost,
                'pricing': est['pricing'], 'daily_free': DAILY_FREE_TOKENS
            }), 402
        # 原子预扣
        prehold_result = _prehold(u['user_id'], sid, estimated_cost, model)
        if not prehold_result.get('ok'):
            return jsonify({
                'success': False, 'error': 'prehold_failed',
                'message': f'并发竞争: 余额不足, 请重试',
                'balance': prehold_result.get('balance', 0)
            }), 409  # 409 Conflict

    # 确保会话存在
    if not sid:
        sid = str(uuid.uuid4())
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = _db()
        conn.execute(
            "INSERT INTO chat_sessions(session_id,user_id,username,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (sid, u['user_id'], u['username'], f"{u['username']}的对话", now, now)
        )
        conn.commit()
        conn.close()
        _record_action(sid, u['user_id'], 'new_session')

    # 认知画像
    cp = _get_cognitive_profile(u['user_id'], u['username'])
    system_prompt = _build_divergent_prompt(user_text, u['username'], cp, page_context=page_context)

    # 保存用户消息 (flow_chat_all7: 带图消息落附件标记)
    _save_message(sid, u['user_id'], 'user', user_text + ('\n\n📎 [图片]' if image_b64 else ''))
    _record_action(sid, u['user_id'], 'send', {'text_len': len(user_text), 'model': model})

    # ── 上下文管理 ──
    ctx_status = _check_and_manage_context(sid, u['user_id'], u['username'])

    # 生成 SSE 流
    def generate():
        full_response = []
        usage = {'prompt_tokens': 0, 'completion_tokens': 0}
        t0 = time.time()
        brain_fed = False

        # 先 yield 预扣事件
        if prehold_result and prehold_result.get('ok'):
            yield f"data: [prehold] {json.dumps({'held': prehold_result['held_amount'], 'balance': prehold_result['balance'], 'model': model, 'model_weight': _pricing_for(model)['model_weight']}, ensure_ascii=False)}\n\n"

        if ctx_status.get('warning'):
            warn_msg = f"上下文已达 {ctx_status['size_mb']:.1f}MB, 建议手动压缩"
            yield f"data: [context_warning] {json.dumps({'size_mb': ctx_status['size_mb'], 'threshold_mb': 50, 'message': warn_msg}, ensure_ascii=False)}\n\n"
        if ctx_status.get('compressed'):
            before_mb = ctx_status.get('size_mb_before', 0)
            after_mb = ctx_status.get('size_mb_after', 0)
            arch_cnt = ctx_status.get('archived_count', 0)
            comp_msg = f"自动压缩: {before_mb:.1f}MB → {after_mb:.1f}MB, {arch_cnt} 条老消息已投喂脑库归档"
            yield f"data: [context_compressed] {json.dumps({'size_mb_before': before_mb, 'size_mb_after': after_mb, 'archived_messages': arch_cnt, 'fed_to_brain': True, 'message': comp_msg}, ensure_ascii=False)}\n\n"
            brain_fed = True

        try:
            for chunk in _call_ollama_stream(user_text, system_prompt, u['username'],
                                             images=[image_b64] if image_b64 else None,
                                             model_override=model if image_b64 else None):
                yield chunk
                if chunk.startswith('data:'):
                    payload = chunk[5:].strip()
                    if payload.startswith('['):
                        if payload.startswith('[done]'):
                            try:
                                d = json.loads(payload[6:])
                                usage['prompt_tokens'] = int(d.get('prompt_eval_count', 0) or 0)
                                usage['completion_tokens'] = int(d.get('eval_count', 0) or 0)
                            except Exception:
                                pass
                        continue
                    try:
                        d = json.loads(payload)
                        if 'token' in d:
                            full_response.append(d['token'])
                    except Exception:
                        pass
        except GeneratorExit:
            usage['completion_tokens'] = len(''.join(full_response))
            pass
        except Exception as e:
            yield f"data: [error] {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        full_ai_text = ''.join(full_response)
        duration_ms = int((time.time() - t0) * 1000)

        # 字符数兜底
        if usage['prompt_tokens'] <= 0:
            usage['prompt_tokens'] = len(user_text) + len(system_prompt)
        if usage['completion_tokens'] <= 0:
            usage['completion_tokens'] = len(full_ai_text)

        # 拐点检测 (前置, 用于结算奖励)
        inflections = _detect_inflections(sid, u['user_id'], user_text, full_ai_text)
        if inflections:
            for p in inflections:
                _record_action(sid, u['user_id'], 'inflection', p)

        # 发散思维 v2 (flow_diverge_v2_20261019): 拐点事件回传前端 → 计数徽标+面板
        try:
            yield f"data: [inflections] {json.dumps({'count': len(inflections), 'items': [{'type': p.get('inflection_type',''), 'trigger': (p.get('trigger_text') or '')[:60]} for p in inflections]}, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        # ── 三阶段结算 ──
        if sa_exempt:
            # SA 豁免: 只上报用量, 不扣费不限量
            try:
                yield f"data: [billing] {json.dumps({'prompt_tokens': usage['prompt_tokens'], 'completion_tokens': usage['completion_tokens'], 'model': model, 'model_weight': _pricing_for(model)['model_weight'], 'deducted': 0, 'balance': None, 'exempt': True, 'role': 'super_admin', 'reward': 0}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
        else:
            # 脑库投喂 (异步, 标记 brain_fed 用于结算)
            try:
                import threading
                def do_brain():
                    nonlocal brain_fed
                    try:
                        # 1) 关键词+拐点抽取 (零 token, 本地关键词词典)
                        _extract_and_save_keywords(sid, u['user_id'], user_text, full_ai_text, inflections)
                        # 2) 真正投喂 AI 脑库
                        _feed_brain(sid, u['user_id'], u['username'], user_text, full_ai_text, inflections)
                        brain_fed = True
                    except Exception:
                        pass
                threading.Thread(target=do_brain, daemon=True).start()
            except Exception:
                pass

            # 最终结算 (同步, 脑库投喂奖励在下一次结算时补记; 本次只结算已知拐点)
            settle = _finalize(u['user_id'], sid, model,
                               usage['prompt_tokens'], usage['completion_tokens'],
                               prehold_result, inflections=inflections, brain_fed=brain_fed)
            try:
                yield f"data: [billing] {json.dumps({'prompt_tokens': usage['prompt_tokens'], 'completion_tokens': usage['completion_tokens'], 'model': model, 'model_weight': _pricing_for(model)['model_weight'], 'deducted': settle['net_cost'], 'preheld': settle.get('prehold', 0), 'refunded': settle.get('refund', 0), 'reward': settle.get('reward', 0), 'balance': settle['balance']}, ensure_ascii=False)}\n\n"
            except Exception:
                pass

        # 保存 AI 消息
        _save_message(sid, u['user_id'], 'assistant', full_ai_text,
                      tokens=usage['completion_tokens'], model=model, duration_ms=duration_ms)
        _update_session(sid, full_ai_text[:100])

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})


# ── 内部辅助 ──────────────────────────────────────────────────────
def _save_message(session_id, user_id, role, content, reasoning='', tokens=0, model='', duration_ms=0):
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO chat_messages(session_id,user_id,role,content,reasoning,tokens,model,duration_ms) VALUES(?,?,?,?,?,?,?,?)",
            (session_id, user_id, role, content, reasoning, tokens, model, duration_ms)
        )
        # 更新会话计数
        conn.execute(
            "UPDATE chat_sessions SET message_count = message_count + 1, last_message=?, updated_at=datetime('now','localtime') WHERE session_id=?",
            (content[:100], session_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _update_session(session_id, last_msg):
    try:
        conn = _db()
        conn.execute(
            "UPDATE chat_sessions SET last_message=?, updated_at=datetime('now','localtime') WHERE session_id=?",
            (last_msg, session_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
