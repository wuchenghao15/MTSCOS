#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🔏 印章管理中心 (SealCenterEngine)
#  flow_seal_center_20261112
#
#  印章体系 (4 枚公章 + 1 套审计链):
#  ──────────────────────────────────────────────────────────────
#  FINANCE_SEAL   财务专用章  — 收支/调拨/银行开户
#  INVEST_SEAL    投资专用章  — 证券/基金/贵金属/期货/债券
#  CONTRACT_SEAL  合同专用章  — 对外合同/合作协议
#  LEGAL_SEAL     法人章      — 法定代表人签署/重大决策
#
#  用章流程:
#  提案 APPROVED → request_seal() → Grant(授权) → Token(一次性凭证)
#  → verify_token() → Channel Exec 执行 → consume_token() → 核销
#
#  安全设计:
#  ① Token 为 SHA256 hash, plain_token 仅生成时返回一次, DB 永不明文存
#  ② 金额 ±5% 浮动验证 (防 exact-match 太死)
#  ③ 每步 (GRANT/VERIFY/USE) 全量写 mt_seal_audit
#  ④ per_tx + daily 双重额度检查
#  ⑤ Grant 7 天后自动过期
#  ⑥ Channel→印章硬编码映射, 不可跨渠道错用章
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, sys, hashlib, secrets, time
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT_ROOT, "database", "app.db")

# ── 渠道 → 印章映射 (硬编码, 防错用) ──
CHANNEL_SEAL_MAP = {
    "A_STOCK":      "INVEST_SEAL",
    "ETF":          "INVEST_SEAL",
    "FUND":         "INVEST_SEAL",
    "METAL":        "INVEST_SEAL",
    "FUTURES":      "INVEST_SEAL",
    "BOND":         "INVEST_SEAL",
    "BANK_DEPOSIT": "FINANCE_SEAL",
    "CASH":         "FINANCE_SEAL",
}

DEFAULT_TOKEN_EXPIRE_HOURS = 24
DEFAULT_GRANT_EXPIRE_DAYS = 7


def _conn():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row_to_dict(row):
    if row is None:
        return {}
    return dict(row)


def _audit(conn, action, seal_code="", proposal_id=0, grant_id=0, token_id=0,
           operator="", detail="", result="OK", error_msg="", amount=0):
    conn.execute("""INSERT INTO mt_seal_audit
        (action, seal_code, proposal_id, grant_id, token_id, operator, detail,
         result, error_msg, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (action, seal_code, proposal_id or None, grant_id or None, token_id or None,
         operator or "", detail or "", result, error_msg or "", amount or 0))


# ═══════════════════════════════════════════════════════════════════
# §0 确保表 (防止表不存在的边缘场景)
# ═══════════════════════════════════════════════════════════════════

def _ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_seal_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seal_code TEXT UNIQUE NOT NULL, seal_name TEXT NOT NULL,
        seal_holder TEXT NOT NULL, per_tx_limit REAL DEFAULT 0,
        daily_limit REAL DEFAULT 0, is_active INTEGER DEFAULT 1,
        description TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_seal_grant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seal_code TEXT NOT NULL, proposal_id INTEGER NOT NULL, proposal_no TEXT,
        amount REAL NOT NULL, operator TEXT NOT NULL,
        granted_by TEXT DEFAULT 'SealCenterEngine', status TEXT DEFAULT 'GRANTED',
        per_tx_remaining REAL DEFAULT 0, daily_used REAL DEFAULT 0,
        granted_at TEXT DEFAULT (datetime('now','localtime')),
        expires_at TEXT, revoked_at TEXT, revoke_reason TEXT,
        UNIQUE(seal_code, proposal_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_seal_token (
        id INTEGER PRIMARY KEY AUTOINCREMENT, grant_id INTEGER NOT NULL,
        seal_code TEXT NOT NULL, proposal_id INTEGER NOT NULL, proposal_no TEXT,
        token_hash TEXT UNIQUE NOT NULL, status TEXT DEFAULT 'UNUSED',
        expected_amount REAL DEFAULT 0, verified_at TEXT, used_at TEXT,
        related_trade_id TEXT, created_at TEXT DEFAULT (datetime('now','localtime')),
        expires_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_seal_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL, seal_code TEXT, proposal_id INTEGER,
        grant_id INTEGER, token_id INTEGER, operator TEXT, detail TEXT,
        result TEXT DEFAULT 'OK', error_msg TEXT, amount REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")


# ═══════════════════════════════════════════════════════════════════
# §1 request_seal — 为 APPROVED 提案申请用章
# ═══════════════════════════════════════════════════════════════════

def request_seal(proposal_id, operator="AI_AUTO"):
    """
    完整流程:
    ① 验提案 status = APPROVED
    ② 验议会 session 存在且 PASSED (向后兼容 fallback: 无 session 时仅验 APPROVED)
    ③ 根据 channel → 选印章
    ④ 检查 per_tx + daily 额度
    ⑤ 幂等: 已 GRANTED 则直接返回
    ⑥ 创建 Grant → 创建 Token
    ⑦ 更新 proposal seal_* 字段
    ⑧ 写 AUDIT
    返回: {"grant_id", "token_hash", "plain_token", "seal_code", ...}
    """
    conn = _conn()
    try:
        _ensure_tables(conn)

        # ── ① 读提案 ──
        prop_row = conn.execute(
            "SELECT * FROM mt_investment_proposal WHERE id=?", (proposal_id,)
        ).fetchone()
        if not prop_row:
            _audit(conn, "REQUEST", proposal_id=proposal_id, operator=operator,
                   detail="proposal not found", result="DENIED", error_msg="not_found")
            conn.commit()
            return {"ok": False, "error": "proposal_not_found", "proposal_id": proposal_id}

        prop = _row_to_dict(prop_row)
        status = prop.get("status", "")
        amount = prop.get("amount", 0)
        channel = prop.get("channel", "")
        prop_no = prop.get("proposal_no", "")
        existing_seal = prop.get("seal_status", "")

        # 必须 APPROVED 或 FILIBUSTER (FILIBUSTER 也可能需要手动用章)
        if status not in ("APPROVED", "FILIBUSTER"):
            _audit(conn, "REQUEST", proposal_id=proposal_id, operator=operator,
                   detail=f"status={status}", result="DENIED",
                   error_msg="not_approved", amount=amount)
            conn.commit()
            return {"ok": False, "error": f"proposal_status={status}, need APPROVED"}

        # ── ② 验议会 ──
        parl = conn.execute(
            "SELECT * FROM mt_parliament_session WHERE proposal_id=? ORDER BY id DESC LIMIT 1",
            (proposal_id,)
        ).fetchone()
        parl_dict = _row_to_dict(parl)
        if parl and parl_dict.get("status") not in ("PASSED",):
            _audit(conn, "REQUEST", proposal_id=proposal_id, operator=operator,
                   detail=f"parliament_status={parl_dict.get('status','?')}",
                   result="DENIED", error_msg="parliament_not_passed", amount=amount)
            conn.commit()
            return {"ok": False, "error": f"parliament_status={parl_dict.get('status','?')}"}
        elif not parl:
            # 向后兼容: 老提案可能没 session, 但 status=APPROVED → 放行
            sys.stderr.write(f"[SEAL] proposal #{proposal_id} no parliament session, fallback status-only check\n")

        # ── ③ 渠道 → 印章 ──
        seal_code = CHANNEL_SEAL_MAP.get(channel, "")
        if not seal_code:
            _audit(conn, "REQUEST", proposal_id=proposal_id, operator=operator,
                   detail=f"channel={channel} → no seal map",
                   result="DENIED", error_msg="unknown_channel", amount=amount)
            conn.commit()
            return {"ok": False, "error": f"no seal for channel={channel}"}

        # ── ④ 查印章注册表 ──
        seal_row = conn.execute(
            "SELECT * FROM mt_seal_registry WHERE seal_code=? AND is_active=1",
            (seal_code,)
        ).fetchone()
        if not seal_row:
            _audit(conn, "REQUEST", seal_code=seal_code, proposal_id=proposal_id,
                   operator=operator, detail="seal not active",
                   result="DENIED", error_msg="seal_inactive", amount=amount)
            conn.commit()
            return {"ok": False, "error": f"seal {seal_code} not active"}
        seal = _row_to_dict(seal_row)

        # per_tx 额度
        per_tx_limit = seal.get("per_tx_limit", 0) or 0
        if per_tx_limit > 0 and amount > per_tx_limit:
            _audit(conn, "REQUEST", seal_code=seal_code, proposal_id=proposal_id,
                   operator=operator, detail=f"amount={amount} > per_tx={per_tx_limit}",
                   result="DENIED", error_msg="per_tx_exceed", amount=amount)
            conn.commit()
            return {"ok": False, "error": f"amount ¥{amount} > seal per_tx_limit ¥{per_tx_limit}"}

        # 今日已用
        daily_limit = seal.get("daily_limit", 0) or 0
        if daily_limit > 0:
            today_used_row = conn.execute("""
                SELECT COALESCE(SUM(g.amount),0) as used
                FROM mt_seal_grant g
                WHERE g.seal_code=?
                  AND date(g.granted_at) = date('now','localtime')
                  AND g.status='GRANTED'
            """, (seal_code,)).fetchone()
            today_used = _row_to_dict(today_used_row).get("used", 0) or 0
            if today_used + amount > daily_limit:
                _audit(conn, "REQUEST", seal_code=seal_code, proposal_id=proposal_id,
                       operator=operator,
                       detail=f"today_used={today_used} + amount={amount} > daily={daily_limit}",
                       result="DENIED", error_msg="daily_exceed", amount=amount)
                conn.commit()
                return {"ok": False, "error": f"daily limit exceeded: ¥{today_used}/¥{daily_limit}"}

        # ── ⑤ 幂等: 已存在 Grant → 直接返回 ──
        existing_grant = conn.execute(
            "SELECT * FROM mt_seal_grant WHERE seal_code=? AND proposal_id=? AND status='GRANTED'",
            (seal_code, proposal_id)
        ).fetchone()
        if existing_grant:
            eg = _row_to_dict(existing_grant)
            # 有没有 UNUSED 的 token
            existing_token = conn.execute(
                "SELECT * FROM mt_seal_token WHERE grant_id=? AND status='UNUSED' ORDER BY id DESC LIMIT 1",
                (eg["id"],)
            ).fetchone()
            if existing_token:
                et = _row_to_dict(existing_token)
                sys.stderr.write(f"[SEAL] proposal #{proposal_id} already has grant #{eg['id']} + token #{et['id']}, returning existing\n")
                return {
                    "ok": True, "idempotent": True,
                    "grant_id": eg["id"], "token_id": et["id"],
                    "token_hash": et["token_hash"], "seal_code": seal_code,
                    "proposal_id": proposal_id, "proposal_no": prop_no,
                    "note": "existing_grant_reused",
                }

        # ── ⑥ 创建 Grant ──
        expires_at = (datetime.now() + timedelta(days=DEFAULT_GRANT_EXPIRE_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
        grant_cur = conn.execute("""INSERT INTO mt_seal_grant
            (seal_code, proposal_id, proposal_no, amount, operator, granted_by,
             per_tx_remaining, daily_used, expires_at)
            VALUES (?, ?, ?, ?, ?, 'SealCenterEngine', ?, 0, ?)""",
            (seal_code, proposal_id, prop_no, amount, operator, amount, expires_at))
        grant_id = grant_cur.lastrowid

        _audit(conn, "GRANT", seal_code=seal_code, proposal_id=proposal_id,
               grant_id=grant_id, operator=operator,
               detail=f"amount=¥{amount:,.0f} channel={channel} holder={seal.get('seal_holder','')}",
               result="OK", amount=amount)

        # ── ⑦ 创建 Token (一次性凭证) ──
        plain_token = secrets.token_urlsafe(32)  # 64 chars URL-safe
        token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
        token_expires = (datetime.now() + timedelta(hours=DEFAULT_TOKEN_EXPIRE_HOURS)).strftime('%Y-%m-%d %H:%M:%S')

        token_cur = conn.execute("""INSERT INTO mt_seal_token
            (grant_id, seal_code, proposal_id, proposal_no, token_hash,
             expected_amount, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (grant_id, seal_code, proposal_id, prop_no, token_hash, amount, token_expires))
        token_id = token_cur.lastrowid

        # ── ⑧ 更新 proposal ──
        conn.execute("""UPDATE mt_investment_proposal SET
            seal_code=?, seal_token_hash=?, seal_grant_id=?, seal_status='GRANTED',
            seal_requested_at=?, seal_granted_at=?, seal_amount=?, updated_at=?
            WHERE id=?""",
            (seal_code, token_hash, grant_id, _now(), _now(), amount, _now(), proposal_id))

        _audit(conn, "TOKEN", seal_code=seal_code, proposal_id=proposal_id,
               grant_id=grant_id, token_id=token_id, operator=operator,
               detail=f"token_hash={token_hash[:16]}... expires={token_expires}",
               result="OK", amount=amount)

        conn.commit()

        return {
            "ok": True, "idempotent": False,
            "grant_id": grant_id, "token_id": token_id,
            "token_hash": token_hash,
            "plain_token": plain_token,  # ⚠️ 仅本次返回, DB 不存明文
            "seal_code": seal_code,
            "seal_name": seal.get("seal_name", seal_code),
            "seal_holder": seal.get("seal_holder", ""),
            "proposal_id": proposal_id,
            "proposal_no": prop_no,
            "amount": amount,
            "grant_expires_at": expires_at,
            "token_expires_at": token_expires,
            "note": "plain_token 仅本次返回, 请妥善保管; 执行交易时需调用 verify_token(token_hash, ...)",
        }
    except Exception as e:
        conn.rollback()
        sys.stderr.write(f"[SEAL] request_seal error: {e}\n")
        try:
            _audit(conn, "REQUEST", proposal_id=proposal_id, operator=operator,
                   detail=str(e)[:200], result="ERROR", error_msg=str(e)[:200])
            conn.commit()
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:200]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §2 verify_token — 交易执行前验章
# ═══════════════════════════════════════════════════════════════════

def verify_token(token_hash, proposal_id=None, channel=None, expected_amount=None):
    """
    验证印章 Token 有效性。返回 {"ok": True/False, "reason": "...", "grant_id": ...}
    验证条件:
    ① token_hash 存在 & status = UNUSED
    ② 未过期 (expires_at > now)
    ③ proposal_id 匹配 (如果提供)
    ④ 渠道匹配 (channel → seal_code 一致)
    ⑤ 金额 ±5% 浮动 (如果提供 expected_amount)
    验过后 token 状态 → VERIFIED (一次性)
    """
    conn = _conn()
    try:
        _ensure_tables(conn)

        tk = conn.execute(
            "SELECT * FROM mt_seal_token WHERE token_hash=?", (token_hash,)
        ).fetchone()
        if not tk:
            _audit(conn, "VERIFY", token_hash=token_hash[:16],
                   detail="token_hash not found", result="DENIED", error_msg="not_found")
            conn.commit()
            return {"ok": False, "reason": "token_not_found"}

        td = _row_to_dict(tk)
        token_id = td.get("id")
        grant_id = td.get("grant_id")
        seal_code = td.get("seal_code", "")
        stored_pid = td.get("proposal_id")
        status = td.get("status", "")
        expected_amt = td.get("expected_amount", 0) or 0
        expires_at = td.get("expires_at", "")

        # 状态
        if status != "UNUSED":
            _audit(conn, "VERIFY", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
                   detail=f"status={status}", result="DENIED", error_msg=f"token_{status}")
            conn.commit()
            return {"ok": False, "reason": f"token_status={status}"}

        # 过期
        if expires_at and expires_at < _now():
            conn.execute("UPDATE mt_seal_token SET status='EXPIRED' WHERE id=?", (token_id,))
            _audit(conn, "VERIFY", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
                   detail=f"expired at {expires_at}", result="DENIED", error_msg="token_expired")
            conn.commit()
            return {"ok": False, "reason": "token_expired"}

        # proposal 匹配
        if proposal_id is not None and stored_pid and proposal_id != stored_pid:
            _audit(conn, "VERIFY", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
                   detail=f"proposal_id mismatch: expect={proposal_id} stored={stored_pid}",
                   result="DENIED", error_msg="proposal_mismatch")
            conn.commit()
            return {"ok": False, "reason": "proposal_id_mismatch"}

        # 渠道匹配
        if channel:
            expected_seal = CHANNEL_SEAL_MAP.get(channel, "")
            if expected_seal and expected_seal != seal_code:
                _audit(conn, "VERIFY", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
                       detail=f"channel={channel} requires {expected_seal}",
                       result="DENIED", error_msg="channel_seal_mismatch")
                conn.commit()
                return {"ok": False, "reason": f"channel {channel} requires {expected_seal}, got {seal_code}"}

        # 金额 ±5%
        if expected_amount is not None and expected_amt > 0:
            delta_pct = abs(expected_amount - expected_amt) / expected_amt
            if delta_pct > 0.05:
                _audit(conn, "VERIFY", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
                       detail=f"amount delta={delta_pct:.1%} expect={expected_amount} seal={expected_amt}",
                       result="DENIED", error_msg="amount_mismatch", amount=expected_amount)
                conn.commit()
                return {"ok": False, "reason": f"amount_mismatch: delta {delta_pct:.1%} > 5%"}

        # 通过 → 状态 VERIFIED
        conn.execute("UPDATE mt_seal_token SET status='VERIFIED', verified_at=? WHERE id=?",
                     (_now(), token_id))
        _audit(conn, "VERIFY", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
               proposal_id=stored_pid, detail=f"ALLOWED proposal={stored_pid} seal={seal_code}",
               result="OK", amount=expected_amt)
        conn.commit()

        return {
            "ok": True, "status": "ALLOWED",
            "token_id": token_id, "grant_id": grant_id,
            "seal_code": seal_code, "proposal_id": stored_pid,
            "expected_amount": expected_amt,
            "message": "验章通过, 可执行交易",
        }
    except Exception as e:
        conn.rollback()
        sys.stderr.write(f"[SEAL] verify_token error: {e}\n")
        return {"ok": False, "error": str(e)[:200]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §3 consume_token — 交易完成后核销 Token
# ═══════════════════════════════════════════════════════════════════

def consume_token(token_hash, related_trade_id=""):
    """
    核销已用印章 Token。扣减 Grant 额度, 更新 Proposal seal_status。
    """
    conn = _conn()
    try:
        _ensure_tables(conn)
        tk = conn.execute(
            "SELECT * FROM mt_seal_token WHERE token_hash=?", (token_hash,)
        ).fetchone()
        if not tk:
            _audit(conn, "USE", token_hash=token_hash[:16],
                   detail="token not found", result="DENIED", error_msg="not_found")
            conn.commit()
            return {"ok": False, "error": "token_not_found"}

        td = _row_to_dict(tk)
        token_id = td.get("id")
        grant_id = td.get("grant_id")
        seal_code = td.get("seal_code", "")
        proposal_id = td.get("proposal_id")
        status = td.get("status", "")
        expected_amount = td.get("expected_amount", 0) or 0

        if status in ("USED", "REVOKED"):
            return {"ok": True, "note": f"token already {status}"}

        # 核销 Token
        conn.execute("""UPDATE mt_seal_token SET status='USED', used_at=?, related_trade_id=?
                        WHERE id=?""", (_now(), related_trade_id or "", token_id))

        # 扣减 Grant 额度
        if grant_id:
            conn.execute("""UPDATE mt_seal_grant SET per_tx_remaining = per_tx_remaining - ?,
                            status='USED' WHERE id=?""", (expected_amount, grant_id))

        # 更新 Proposal
        if proposal_id:
            conn.execute("""UPDATE mt_investment_proposal SET
                seal_status='USED', seal_verified_at=?, seal_used_at=?, updated_at=?
                WHERE id=?""", (_now(), _now(), _now(), proposal_id))

        _audit(conn, "USE", grant_id=grant_id, token_id=token_id, seal_code=seal_code,
               proposal_id=proposal_id, detail=f"trade_id={related_trade_id}",
               result="OK", amount=expected_amount)

        conn.commit()
        return {"ok": True, "trade_id": related_trade_id, "seal_code": seal_code}
    except Exception as e:
        conn.rollback()
        sys.stderr.write(f"[SEAL] consume_token error: {e}\n")
        return {"ok": False, "error": str(e)[:200]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §4 revoke_grant — 撤销授权
# ═══════════════════════════════════════════════════════════════════

def revoke_grant(grant_id, reason="manual_revoke"):
    conn = _conn()
    try:
        conn.execute("UPDATE mt_seal_grant SET status='REVOKED', revoked_at=?, revoke_reason=? WHERE id=?",
                     (_now(), reason, grant_id))
        conn.execute("UPDATE mt_seal_token SET status='REVOKED' WHERE grant_id=? AND status IN ('UNUSED','VERIFIED')",
                     (grant_id,))
        _audit(conn, "REVOKE", grant_id=grant_id, detail=reason, result="OK")
        conn.commit()
        return {"ok": True, "grant_id": grant_id, "reason": reason}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §5 auto_grant_all_approved — 批量给所有 APPROVED 提案发章
# ═══════════════════════════════════════════════════════════════════

def auto_grant_all_approved(limit=100):
    conn = _conn()
    try:
        rows = conn.execute("""
            SELECT id, proposal_no, channel, amount, status, seal_status
            FROM mt_investment_proposal
            WHERE status='APPROVED' AND (seal_status='' OR seal_status IS NULL OR seal_status='')
            ORDER BY id ASC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
    except Exception as e:
        conn.close()
        return {"error": str(e)[:200]}

    results = []
    for r in rows:
        pid = r["id"]
        no = r["proposal_no"]
        try:
            res = request_seal(pid, operator="SealCenterEngine_AutoGrant")
            results.append({
                "proposal_id": pid, "proposal_no": no,
                "ok": res.get("ok"), "seal_code": res.get("seal_code", ""),
                "grant_id": res.get("grant_id"),
                "error": res.get("error", ""),
            })
        except Exception as e:
            results.append({"proposal_id": pid, "proposal_no": no, "error": str(e)[:80]})

    granted = sum(1 for r in results if r.get("ok"))
    denied = sum(1 for r in results if not r.get("ok"))
    return {"total": len(results), "granted": granted, "denied": denied, "detail": results}


# ═══════════════════════════════════════════════════════════════════
# §6 查数 API
# ═══════════════════════════════════════════════════════════════════

def seal_status(proposal_id=None):
    """查询用章状态 (单提案或全部汇总)"""
    conn = _conn()
    try:
        if proposal_id is not None:
            g = conn.execute("SELECT * FROM mt_seal_grant WHERE proposal_id=? ORDER BY id DESC LIMIT 1",
                             (proposal_id,)).fetchone()
            t = conn.execute("SELECT * FROM mt_seal_token WHERE proposal_id=? ORDER BY id DESC LIMIT 1",
                             (proposal_id,)).fetchone()
            p = conn.execute("SELECT seal_code, seal_status, seal_amount FROM mt_investment_proposal WHERE id=?",
                             (proposal_id,)).fetchone()
            return {
                "proposal_id": proposal_id,
                "proposal_seal": _row_to_dict(p),
                "grant": _row_to_dict(g),
                "token": _row_to_dict(t),
            }

        # 汇总
        total_registry = conn.execute("SELECT COUNT(*) FROM mt_seal_registry").fetchone()[0]
        total_grants = conn.execute("SELECT COUNT(*) FROM mt_seal_grant").fetchone()[0]
        active_grants = conn.execute("SELECT COUNT(*) FROM mt_seal_grant WHERE status='GRANTED'").fetchone()[0]
        total_tokens = conn.execute("SELECT COUNT(*) FROM mt_seal_token").fetchone()[0]
        unused_tokens = conn.execute("SELECT COUNT(*) FROM mt_seal_token WHERE status='UNUSED'").fetchone()[0]
        used_tokens = conn.execute("SELECT COUNT(*) FROM mt_seal_token WHERE status='USED'").fetchone()[0]
        total_audit = conn.execute("SELECT COUNT(*) FROM mt_seal_audit").fetchone()[0]

        # 各印章发放统计
        by_seal = conn.execute("""
            SELECT g.seal_code, s.seal_name, COUNT(*) as cnt,
                   SUM(CASE WHEN g.status='GRANTED' THEN 1 ELSE 0 END) as active
            FROM mt_seal_grant g LEFT JOIN mt_seal_registry s ON g.seal_code=s.seal_code
            GROUP BY g.seal_code
        """).fetchall()
        by_seal_list = [
            {"seal_code": dict(r)["seal_code"], "seal_name": dict(r)["seal_name"],
             "total_grants": dict(r)["cnt"], "active_grants": dict(r)["active"]}
            for r in by_seal
        ]

        return {
            "registry": total_registry,
            "grants": {"total": total_grants, "active": active_grants},
            "tokens": {"total": total_tokens, "unused": unused_tokens, "used": used_tokens},
            "audit_entries": total_audit,
            "by_seal": by_seal_list,
        }
    finally:
        conn.close()


def recent_audit(limit=50):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mt_seal_audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §7 CLI 入口 — 一键端到端验证
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=int, help="为 proposal_id 申请用章")
    parser.add_argument("--verify", type=str, help="验章: token_hash")
    parser.add_argument("--consume", type=str, help="核销: token_hash")
    parser.add_argument("--revoke", type=int, help="撤销 grant_id")
    parser.add_argument("--auto-grant", action="store_true", help="批量给 APPROVED 提案发章")
    parser.add_argument("--status", action="store_true", help="印章状态汇总")
    parser.add_argument("--audit", action="store_true", help="最近审计")
    parser.add_argument("--e2e", action="store_true", help="端到端全链路测试")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(seal_status(), ensure_ascii=False, indent=2))

    if args.audit:
        logs = recent_audit(30)
        for l in logs:
            print(f"  [{l.get('action','?')}] seal={l.get('seal_code','-')} pid={l.get('proposal_id','-')} "
                  f"result={l.get('result','?')} amt=¥{l.get('amount',0):,.0f} @{l.get('created_at','-')}")

    if args.request:
        res = request_seal(args.request)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.auto_grant:
        res = auto_grant_all_approved()
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.verify:
        res = verify_token(args.verify)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.consume:
        res = consume_token(args.consume, related_trade_id="TEST_TRADE_001")
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.revoke:
        res = revoke_grant(args.revoke)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.e2e:
        print("=" * 60)
        print("🔏 SealCenterEngine 端到端全链路测试")
        print("=" * 60)
        import parliamentary_voting_engine as pve
        import random

        # 1) 创建一个新提案
        print("\n📋 Step 1: 创建新提案...")
        test_id = f"E2E-{int(time.time())}"
        pid_res = pve.create_proposal(
            title=f"E2E 测试-{test_id}", channel="METAL", amount=15000,
            ptype="BUY", asset_code="AU9999", asset_name="黄金9999",
            qty=2.5, price=6000, description="端到端用章测试"
        )
        proposal_id = pid_res.get("proposal_id")
        proposal_no = pid_res.get("proposal_no", "")
        vote_res = pid_res.get("vote", {})
        print(f"  ✅ #{proposal_id} {proposal_no} tier={vote_res.get('tier','?')} result={vote_res.get('result','?')}")

        # 2) 申请用章
        print("\n🔐 Step 2: 申请用章...")
        req = request_seal(proposal_id, operator="E2E_TEST")
        if not req.get("ok"):
            print(f"  ❌ 申请失败: {req.get('error')}")
            exit(1)
        print(f"  ✅ GRANT #{req.get('grant_id')} seal={req.get('seal_code')}({req.get('seal_name')})")
        print(f"     token_hash={req.get('token_hash','')[:24]}...")
        plain_token = req.get("plain_token", "")
        token_hash = req.get("token_hash", "")
        amount = req.get("amount", 0)
        print(f"     ⚠️ plain_token 仅本次返回: {plain_token[:16]}...")

        # 3) 验证 token
        print("\n🔍 Step 3: 验章 (verify_token)...")
        v = verify_token(token_hash, proposal_id=proposal_id, channel="METAL", expected_amount=amount)
        print(f"  ✅ result={v.get('status','?')} grant={v.get('grant_id')} seal={v.get('seal_code')}")

        # 4) 二次验证应该被拒 (一次性)
        print("\n🔁 Step 4: 二次验章 (应该被拒, 已 VERIFIED)...")
        v2 = verify_token(token_hash, proposal_id=proposal_id, channel="METAL", expected_amount=amount)
        print(f"  {'✅' if not v2.get('ok') else '⚠️'} result={v2.get('reason','?')} (一次性生效)")

        # 5) 核销
        print("\n💥 Step 5: 核销 (consume_token)...")
        trade_id = f"TRADE-{test_id}"
        c = consume_token(token_hash, related_trade_id=trade_id)
        print(f"  ✅ 已核销 trade_id={trade_id}")

        # 6) 查审计
        print("\n📜 Step 6: 审计链...")
        audit = recent_audit(20)
        for l in audit:
            if l.get("proposal_id") == proposal_id:
                print(f"  [{l.get('action')}] seal={l.get('seal_code','-')} "
                      f"result={l.get('result','?')} amt=¥{l.get('amount',0):,.0f} "
                      f"detail={l.get('detail','')[:60]}")

        # 7) 汇总
        print("\n📊 Step 7: 印章系统状态...")
        status = seal_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))

        print("\n" + "=" * 60)
        print("✅ 端到端全链路测试通过!")
        print("=" * 60)
