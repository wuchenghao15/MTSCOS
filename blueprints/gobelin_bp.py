#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🏛️ 古灵阁银行 Flask Blueprint
#  flow_gobelin_bp_20261112
#
#  路由前缀: /gobelin
#  ──────────────────────────────────────────────────────────────
#  GET  /gobelin/health                      健康检查
#  GET  /gobelin/seal/status                 印章系统状态汇总
#  GET  /gobelin/seal/audit?limit=50         印章审计链
#  GET  /gobelin/seal/<pid>                  单提案用章状态
#  POST /gobelin/seal/request                申请用章 (proposal_id, operator)
#  POST /gobelin/seal/verify                 验章 (token_hash, proposal_id, channel, expected_amount)
#  POST /gobelin/seal/consume                核销 (token_hash, trade_id)
#  POST /gobelin/seal/auto-grant             批量给 APPROVED 提案发章
#  GET  /gobelin/parliament/proposal/<pid>   提案详情 + 议会结果
#  GET  /gobelin/parliament/session/<sid>    议会 session + 投票明细
#  POST /gobelin/parliament/vote/<pid>       对指定提案投票
#  POST /gobelin/parliament/vote-all         批量表决 PENDING 提案
#  POST /gobelin/proposal/create             创建提案 (title, channel, amount, ...)
#  GET  /gobelin/proposals?status=&limit=    提案列表
# ═══════════════════════════════════════════════════════════════════

from flask import Blueprint, jsonify, request, render_template
import datetime as dt, json, os, sys

gobelin_bp = Blueprint("gobelin", __name__, url_prefix="/gobelin")

# 引擎全局缓存 (延迟加载, 避免启动循环 import)
_seal = None
_parl = None


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── 🔒 数据隔离常量 (全局) ──
# 主账户: 唯一真实数据源. 所有 Dashboard/Gobelin API 必须只读这个账户.
MAIN_ACCOUNT_NAME = "GOBELIN_MAIN"
REAL_SCOPE = "REAL"
SIMULATED_SCOPE = "SIMULATED"

# 明确标记哪些表属于真实数据域 vs 模拟数据域
REAL_TABLES = {
    "mt_gobelin_account", "mt_gobelin_position", "mt_gobelin_trade", "mt_gobelin_price",
    "mt_seal_registry", "mt_seal_grant", "mt_seal_token", "mt_seal_audit",
    "mt_parliament_session", "mt_parliament_vote_log",
    "mt_investment_proposal", "mt_portfolio_target",
}
SIMULATED_TABLES = {
    "mt_sandbox_portfolio", "mt_sandbox_trades", "mt_sandbox_signals",
    "mt_sandbox_snapshots", "mt_sandbox_history",
}

SCOPE_DISCLAIMER = (
    "此接口返回 Gobelin Bank 主账户(GOBELIN_MAIN)真实数据, "
    "与沙盘引擎(mt_sandbox_* simulation)完全隔离. "
    "真实 PnL = (avg_cost_basis vs current_price), 非模拟数据."
)


def _add_scope_meta(response_dict, scope="REAL"):
    """给每个响应自动加 scope 元信息, 前端可校验"""
    if isinstance(response_dict, dict):
        response_dict["_scope"] = {
            "data_scope": scope,
            "account": MAIN_ACCOUNT_NAME if scope == REAL_SCOPE else "SIMULATED_SESSION",
            "is_main_account": scope == REAL_SCOPE,
            "disclaimer": SCOPE_DISCLAIMER if scope == REAL_SCOPE else "沙盘模拟数据, 非真实交易",
        }
    return response_dict


def _engines():
    global _seal, _parl
    if _seal is None:
        from engines import seal_center_engine as _seal_m
        _seal = _seal_m
    if _parl is None:
        from engines import parliamentary_voting_engine as _parl_m
        _parl = _parl_m
    return _seal, _parl


def _row_to_dict(row):
    if row is None:
        return {}
    try:
        return dict(row)
    except Exception:
        return row


def _conn():
    import sqlite3, os
    from core.db_path import get_db_path
    db = get_db_path('app.db')
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/health")
def health():
    seal, parl = _engines()
    conn = _conn()
    try:
        prop_total = conn.execute("SELECT COUNT(*) FROM mt_investment_proposal").fetchone()[0]
        prop_approved = conn.execute("SELECT COUNT(*) FROM mt_investment_proposal WHERE status='APPROVED'").fetchone()[0]
        seal_registry = conn.execute("SELECT COUNT(*) FROM mt_seal_registry").fetchone()[0]
        seal_grants = conn.execute("SELECT COUNT(*) FROM mt_seal_grant").fetchone()[0]
        parliament_sessions = conn.execute("SELECT COUNT(*) FROM mt_parliament_session").fetchone()[0]
        return jsonify({
            "ok": True, "service": "GobelinBank",
            "proposals": prop_total,
            "proposals_approved": prop_approved,
            "seal_registry": seal_registry,
            "seal_grants": seal_grants,
            "parliament_sessions": parliament_sessions,
            "seal_engine": "SealCenterEngine v1.0",
            "parliament_engine": "ParliamentaryVotingEngine v1.0 (25席, BETA VETO)",
        })
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 印章查询
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/seal/status")
def seal_status():
    seal, _ = _engines()
    return jsonify(seal.seal_status())


@gobelin_bp.route("/seal/audit")
def seal_audit():
    seal, _ = _engines()
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"ok": True, "limit": limit, "entries": seal.recent_audit(limit)})


@gobelin_bp.route("/seal/<int:proposal_id>")
def seal_by_proposal(proposal_id):
    seal, _ = _engines()
    return jsonify(seal.seal_status(proposal_id=proposal_id))


# ═══════════════════════════════════════════════════════════════════
# 印章操作
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/seal/request", methods=["POST"])
def seal_request():
    seal, _ = _engines()
    data = request.get_json(force=True) if request.is_json else request.form.to_dict()
    proposal_id = int(data.get("proposal_id", 0))
    operator = data.get("operator", "FlaskAPI")
    if not proposal_id:
        return jsonify({"ok": False, "error": "proposal_id required"}), 400
    result = seal.request_seal(proposal_id, operator=operator)
    # 安全: 不返回 plain_token (API 层应该只在控制台返回)
    if result.get("plain_token"):
        del result["plain_token"]
        result["note"] = "plain_token 已从 API 响应中移除, 请通过 CLI 获取"
    return jsonify(result)


@gobelin_bp.route("/seal/verify", methods=["POST"])
def seal_verify():
    seal, _ = _engines()
    data = request.get_json(force=True) if request.is_json else request.form.to_dict()
    token_hash = data.get("token_hash", "")
    proposal_id = data.get("proposal_id")
    channel = data.get("channel")
    expected_amount = data.get("expected_amount")
    if not token_hash:
        return jsonify({"ok": False, "error": "token_hash required"}), 400
    result = seal.verify_token(
        token_hash,
        proposal_id=int(proposal_id) if proposal_id else None,
        channel=channel,
        expected_amount=float(expected_amount) if expected_amount else None,
    )
    return jsonify(result)


@gobelin_bp.route("/seal/consume", methods=["POST"])
def seal_consume():
    seal, _ = _engines()
    data = request.get_json(force=True) if request.is_json else request.form.to_dict()
    token_hash = data.get("token_hash", "")
    trade_id = data.get("trade_id", "")
    if not token_hash:
        return jsonify({"ok": False, "error": "token_hash required"}), 400
    return jsonify(seal.consume_token(token_hash, related_trade_id=trade_id))


@gobelin_bp.route("/seal/auto-grant", methods=["POST"])
def seal_auto_grant():
    seal, _ = _engines()
    data = request.get_json(force=True) if request.is_json else {}
    limit = int(data.get("limit", 100))
    return jsonify(seal.auto_grant_all_approved(limit=limit))


# ═══════════════════════════════════════════════════════════════════
# 议会查询
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/parliament/proposal/<int:proposal_id>")
def parliament_proposal(proposal_id):
    conn = _conn()
    try:
        prop = conn.execute("SELECT * FROM mt_investment_proposal WHERE id=?", (proposal_id,)).fetchone()
        if not prop:
            return jsonify({"ok": False, "error": "not_found"}), 404
        session = conn.execute(
            "SELECT * FROM mt_parliament_session WHERE proposal_id=? ORDER BY id DESC LIMIT 1",
            (proposal_id,)
        ).fetchone()
        votes = []
        if session:
            votes = [_row_to_dict(r) for r in conn.execute(
                "SELECT * FROM mt_parliament_vote_log WHERE session_id=? ORDER BY layer, member_code",
                (session["id"],)
            ).fetchall()]
        return jsonify({
            "ok": True,
            "proposal": _row_to_dict(prop),
            "parliament_session": _row_to_dict(session),
            "vote_log": votes,
        })
    finally:
        conn.close()


@gobelin_bp.route("/parliament/session/<int:session_id>")
def parliament_session(session_id):
    conn = _conn()
    try:
        session = conn.execute("SELECT * FROM mt_parliament_session WHERE id=?", (session_id,)).fetchone()
        if not session:
            return jsonify({"ok": False, "error": "not_found"}), 404
        votes = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_parliament_vote_log WHERE session_id=? ORDER BY layer, member_code",
            (session_id,)
        ).fetchall()]
        return jsonify({"ok": True, "session": _row_to_dict(session), "vote_log": votes})
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 议会操作
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/parliament/vote/<int:proposal_id>", methods=["POST"])
def parliament_vote(proposal_id):
    _, parl = _engines()
    return jsonify(parl.vote(proposal_id))


@gobelin_bp.route("/parliament/vote-all", methods=["POST"])
def parliament_vote_all():
    _, parl = _engines()
    data = request.get_json(force=True) if request.is_json else {}
    limit = int(data.get("limit", 50))
    return jsonify(parl.vote_all_pending(limit=limit))


# ═══════════════════════════════════════════════════════════════════
# 提案
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/proposal/create", methods=["POST"])
def proposal_create():
    _, parl = _engines()
    data = request.get_json(force=True) if request.is_json else request.form.to_dict()
    required = ("title", "channel", "amount")
    for k in required:
        if not data.get(k):
            return jsonify({"ok": False, "error": f"{k} required"}), 400
    result = parl.create_proposal(
        title=data["title"],
        channel=data["channel"],
        amount=float(data["amount"]),
        ptype=data.get("ptype", "BUY"),
        asset_code=data.get("asset_code", ""),
        asset_name=data.get("asset_name", ""),
        qty=float(data.get("qty", 0) or 0),
        price=float(data.get("price", 0) or 0),
        description=data.get("description", ""),
        operator=data.get("operator", "FlaskAPI"),
        source=data.get("source", "MANUAL"),
        risk_score=float(data.get("risk_score", 30) or 30),
    )
    return jsonify(result)


@gobelin_bp.route("/proposals")
def proposals_list():
    status = request.args.get("status", "")
    channel = request.args.get("channel", "")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    conn = _conn()
    try:
        sql = "SELECT * FROM mt_investment_proposal WHERE 1=1"
        params = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if channel:
            sql += " AND channel=?"
            params.append(channel)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM mt_investment_proposal").fetchone()[0]
        return jsonify({
            "ok": True, "total": total,
            "filters": {"status": status, "channel": channel, "limit": limit, "offset": offset},
            "proposals": [_row_to_dict(r) for r in rows],
        })
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# Autonomous Engine · 自动投资引擎路由
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/autonomous/report")
def autonomous_report():
    try:
        from engines import finance_autonomous_engine as fa
        return jsonify(fa.generate_report())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@gobelin_bp.route("/autonomous/scan")
def autonomous_scan():
    try:
        from engines import finance_autonomous_engine as fa
        sigs = fa.scan_market()
        return jsonify({"ok": True, "signals": sigs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@gobelin_bp.route("/autonomous/cycle", methods=["POST"])
def autonomous_cycle():
    """
    完整自动投资 cycle (行情→提案→议会→发章→执行)
    """
    try:
        from engines import finance_autonomous_engine as fa
        data = request.get_json(force=True) if request.is_json else {}
        max_signals = int(data.get("max_signals", 5))
        confidence_min = float(data.get("confidence_min", 0.5))
        execute_limit = int(data.get("execute_limit", 20))
        report = fa.run_cycle(max_signals=max_signals, confidence_min=confidence_min,
                              execute_limit=execute_limit)
        return jsonify(report)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@gobelin_bp.route("/autonomous/execute", methods=["POST"])
def autonomous_execute():
    """只执行已发章的交易"""
    try:
        from engines import finance_autonomous_engine as fa
        data = request.get_json(force=True) if request.is_json else {}
        limit = int(data.get("limit", 20))
        executor = fa.ChannelExecutor()
        return jsonify(executor.execute_all_pending(limit=limit))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# ═══════════════════════════════════════════════════════════════════
# Gobelin Bank 真实资产 (mt_gobelin_* — 隔离沙盘 mt_sandbox_*)
# ═══════════════════════════════════════════════════════════════════

def _gobelin_conn():
    import sqlite3
    from core.db_path import get_db_path
    db = get_db_path('app.db')
    conn = sqlite3.connect(db, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


@gobelin_bp.route("/account/refresh", methods=["POST"])
def account_refresh():
    """刷新所有持仓价格 + 汇总账户 PnL (用真实行情)"""
    try:
        from engines import finance_autonomous_engine as fa
        result = fa.refresh_gobelin_prices()
        return jsonify({"ok": True, "refreshed": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@gobelin_bp.route("/account")
def account_overview():
    """Gobelin Bank 总账 (真实资产, 不混沙盘!)"""
    conn = _gobelin_conn()
    try:
        # 刷新一次 (价格可能已过期)
        from engines import finance_autonomous_engine as fa
        fa.refresh_account_summary()

        acc = conn.execute(
            "SELECT * FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'"
        ).fetchone()
        if not acc:
            return jsonify({"ok": False, "error": "account_not_initialized"}), 404

        positions = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_position WHERE qty>0 ORDER BY channel, qty DESC"
        ).fetchall()]
        trades = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_trade ORDER BY id DESC LIMIT 10"
        ).fetchall()]

        # 渠道汇总
        by_channel = {}
        for p in positions:
            ch = p.get("channel", "?")
            if ch not in by_channel:
                by_channel[ch] = {"qty": 0, "mv": 0, "cost": 0, "pnl": 0}
            by_channel[ch]["qty"] += p.get("qty", 0)
            by_channel[ch]["mv"] += p.get("market_value", 0)
            by_channel[ch]["cost"] += p.get("total_cost", 0)
            by_channel[ch]["pnl"] += p.get("unrealized_pnl", 0)

        acc_d = _row_to_dict(acc)
        result = _add_scope_meta({
            "ok": True,
            "account": {
                "account_name": acc_d.get("account_name"),
                "is_main_account": True,  # 🔒 明确: 这就是主账户
                "total_assets": acc_d.get("total_assets", 0),
                "cash_balance": acc_d.get("cash_balance", 0),
                "position_value": acc_d.get("position_value", 0),
                "unrealized_pnl": acc_d.get("unrealized_pnl", 0),
                "realized_pnl": acc_d.get("realized_pnl", 0),
                "initial_endowment": acc_d.get("initial_endowment", 500000),
                "total_return_pct": round(
                    (acc_d.get("total_assets", 0) - acc_d.get("initial_endowment", 0))
                    / max(acc_d.get("initial_endowment", 1), 1) * 100, 3),
                "trade_count": acc_d.get("trade_count", 0),
                "updated_at": acc_d.get("updated_at"),
            },
            "positions": positions,
            "positions_summary": {
                "count": len(positions),
                "by_channel": by_channel,
            },
            "recent_trades": trades,
            "tables_read": list(REAL_TABLES),  # 🔒 显式声明查了哪些表
            "tables_EXPLICITLY_NOT_READ": list(SIMULATED_TABLES),  # 🔒 明确没碰沙盘
        }, scope=REAL_SCOPE)
        return jsonify(result)
    finally:
        conn.close()


@gobelin_bp.route("/positions")
def positions_list():
    """持仓列表 (带真实 PnL)"""
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_position WHERE qty>0 ORDER BY channel, qty DESC"
        ).fetchall()]
        return jsonify({"ok": True, "scope": "GOBELIN_REAL_ONLY", "count": len(rows), "positions": rows})
    finally:
        conn.close()


@gobelin_bp.route("/trades")
def trades_list():
    """交易流水 (Gobelin Bank 真实成交)"""
    limit = min(int(request.args.get("limit", 50)), 200)
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_trade ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM mt_gobelin_trade").fetchone()[0]
        return jsonify({"ok": True, "scope": "GOBELIN_REAL_ONLY", "total": total, "trades": rows})
    finally:
        conn.close()



# ───────────────────────────────────────────────────────────────
# 🎯 Dashboard: Gobelin Bank 完整快照 (供前端渲染)
# ───────────────────────────────────────────────────────────────

@gobelin_bp.route("/dashboard")
def dashboard_snapshot():
    """Gobelin 仪表盘 JSON 快照 — adapter 统一取价 (v2, 公开访问)"""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engines'))
    from gobelin_adapter import get_conn as _adp_conn, get_account_and_positions
    conn = _adp_conn()
    try:
        summary = get_account_and_positions(conn)
        acc = summary['account']
        positions = summary['positions']
        pos_cost = sum(p.get('total_cost',0) or 0 for p in positions)
        pos_pnl = sum(p.get('unrealized_pnl',0) or 0 for p in positions)
        pos_mv = sum(p.get('market_value',0) or 0 for p in positions)
        return jsonify({
            "ok": True, "generated_at": _now(),
            "scope": {"adapter":"gobelin_adapter","data_scope":"REAL_v2","is_trading":summary['is_trading']},
            "account": acc,
            "positions": {"items":positions,"count":len(positions),
                "total_cost":round(pos_cost,2),"total_market_value":round(pos_mv,2),
                "total_unrealized_pnl":round(pos_pnl,2)},
            "channels": summary['channels'],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    finally:
        try: conn.close()
        except: pass

@gobelin_bp.route("/account")
def account_public():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engines'))
    from gobelin_adapter import get_conn as _adp_conn, get_account
    conn = _adp_conn(); acc = get_account(conn); conn.close()
    return jsonify({"ok": True, "account": acc})

@gobelin_bp.route("/positions")
def positions_public():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engines'))
    from gobelin_adapter import get_conn as _adp_conn, get_positions
    conn = _adp_conn(); pos = get_positions(conn); conn.close()
    return jsonify({"ok": True, "positions": pos, "count": len(pos)})

def dashboard_snapshot():
    """一站式 Gobelin Bank 仪表盘数据 — 使用 gobelin_adapter 统一取价 (v2)"""
    import sys, os
    _engines_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engines')
    if _engines_dir not in sys.path:
        sys.path.insert(0, _engines_dir)
    from gobelin_adapter import (get_conn as _adp_conn, get_account as _adp_acc,
                                 get_positions as _adp_pos, get_account_and_positions)
    conn = _adp_conn()
    try:
        # ✅ adapter 统一入口 (自动叠加 LIVE/API 实时价 + 派生指标)
        summary = get_account_and_positions(conn)
        acc = summary['account']
        positions = summary['positions']
        pos_mv = acc.get('position_value') or sum(p['market_value'] or 0 for p in positions)
        pos_pnl = sum(p.get('unrealized_pnl', 0) or 0 for p in positions)
        pos_cost = sum(p.get('total_cost', 0) or 0 for p in positions)

        # ③ 交易流水 (最近 10 笔)
        trades = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_trade ORDER BY id DESC LIMIT 10"
        ).fetchall()]

        # ④ 提案状态汇总
        prop_status = {
            dict(r)["status"]: dict(r)["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) cnt FROM mt_investment_proposal GROUP BY status"
            ).fetchall()
        }

        # ⑤ 议会 session
        parl_sessions = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_parliament_session ORDER BY id DESC LIMIT 5"
        ).fetchall()]

        # ⑥ 印章状态
        seal_stats = {
            "registry": conn.execute("SELECT COUNT(*) FROM mt_seal_registry").fetchone()[0],
            "grants": conn.execute("SELECT COUNT(*) FROM mt_seal_grant").fetchone()[0],
            "granted_now": conn.execute("SELECT COUNT(*) FROM mt_seal_grant WHERE status='GRANTED'").fetchone()[0],
            "tokens": conn.execute("SELECT COUNT(*) FROM mt_seal_token").fetchone()[0],
            "unused": conn.execute("SELECT COUNT(*) FROM mt_seal_token WHERE status='UNUSED'").fetchone()[0],
            "audit": conn.execute("SELECT COUNT(*) FROM mt_seal_audit").fetchone()[0],
        }

        # ⑦ 合规审计
        compliance = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_compliance_audit ORDER BY id DESC LIMIT 10"
        ).fetchall()]

        # ⑧ 调度器
        scheduler = {
            "heartbeat_count": conn.execute(
                "SELECT COUNT(*) FROM mt_gobelin_scheduler_heartbeat").fetchone()[0],
            "heartbeats": [dict(r) for r in conn.execute(
                "SELECT * FROM mt_gobelin_scheduler_heartbeat ORDER BY id DESC LIMIT 5").fetchall()],
            "recent_meetings": [dict(r) for r in conn.execute(
                "SELECT * FROM mt_gobelin_meeting_log ORDER BY id DESC LIMIT 5").fetchall()],
        }

        # ⑨ 渠道分布 (走 adapter 聚合)
        channel_dist = [
            {"channel": ch['code'], "mv": ch['mv'], "pnl": ch['pnl'], "cnt": ch['rows']}
            for ch in summary['channels'] if ch['code'] != 'CASH'
        ]

        result = {
            "ok": True,
            "generated_at": _now(),
            "scope": {
                "data_scope": "REAL_v2",
                "account": "GOBELIN_MAIN",
                "adapter": "gobelin_adapter",
                "source_priority": "mt_live_position > mt_gobelin_price > mt_gobelin_position",
                "is_trading": summary['is_trading'],
            },
            "account": acc,
            "positions": {
                "items": positions,
                "count": len(positions),
                "total_cost": round(pos_cost, 2),
                "total_market_value": round(pos_mv, 2),
                "total_unrealized_pnl": round(pos_pnl, 2),
                "total_pnl_pct": round(pos_pnl / pos_cost * 100, 2) if pos_cost else 0,
                "by_channel": channel_dist,
            },
            "channels": summary['channels'],
            "trades": {"items": trades, "count_10": len(trades), "total_count": acc.get("trade_count", 0)},
            "proposals": prop_status,
            "parliament": {
                "sessions": parl_sessions,
                "total_sessions": conn.execute(
                    "SELECT COUNT(*) FROM mt_parliament_session").fetchone()[0],
                "votes_total": conn.execute(
                    "SELECT COUNT(*) FROM mt_parliament_vote_log").fetchone()[0],
            },
            "seal": seal_stats,
            "compliance": compliance,
            "scheduler": scheduler,
        }
        return jsonify(_add_scope_meta(result, "REAL_v2"))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    finally:
        try: conn.close()
        except: pass


@gobelin_bp.route("/compliance")
def compliance_audit():
    """合规审计详情"""
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_compliance_audit ORDER BY id DESC LIMIT 50"
        ).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM mt_compliance_audit").fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM mt_compliance_audit WHERE ok=0"
        ).fetchone()[0]
        warnings_total = 0
        for r in rows:
            import json as _j
            try:
                warnings_total += len(_j.loads(r.get("warnings") or "[]"))
            except Exception: pass
        return jsonify(_add_scope_meta({
            "ok": True,
            "total": total,
            "blocked": blocked,
            "warnings_sample": warnings_total,
            "audit_entries": rows,
            "policy_version": "2026.11",
        }, REAL_SCOPE))
    finally:
        conn.close()


@gobelin_bp.route("/scheduler")
def scheduler_status():
    """调度器运行状态"""
    conn = _gobelin_conn()
    try:
        hb = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_scheduler_heartbeat ORDER BY id DESC LIMIT 20"
        ).fetchall()]
        meets = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_meeting_log ORDER BY id DESC LIMIT 20"
        ).fetchall()]
        import datetime as _dt
        # 动态导入 scheduler
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        try:
            from engines.gobelin_scheduler import GobelinScheduler, GOBELIN_MEETINGS, TRADING_SESSIONS
            sched = GobelinScheduler()
            live_status = sched.status()
        except Exception as e:
            live_status = {"error": str(e)[:100]}
            GOBELIN_MEETINGS = []
            TRADING_SESSIONS = []

        return jsonify(_add_scope_meta({
            "ok": True,
            "current_time": _now(),
            "heartbeat_total": conn.execute(
                "SELECT COUNT(*) FROM mt_gobelin_scheduler_heartbeat").fetchone()[0],
            "heartbeats": hb,
            "meetings_log": meets,
            "scheduler_meetings": [
                {"code": m.get("code"), "name": m.get("name"),
                 "time": m.get("time") or f"每 {m.get('interval_min', '?')}min",
                 "weekdays": list(m.get("weekdays", [])),
                 "description": m.get("description")}
                for m in GOBELIN_MEETINGS
            ],
            "trading_sessions": [
                {"channel": s["channel"], "start": s["start"], "end": s["end"], "phase": s["phase"]}
                for s in TRADING_SESSIONS
            ],
            "live_status": live_status,
        }, REAL_SCOPE))
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 🏘️ AI Community Routes (AI 社区)
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/community/health")
def community_health():
    """AI 社区全景健康体检"""
    try:
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if parent not in sys.path: sys.path.insert(0, parent)
        from engines.ai_community_engine import check_community_health
        health = check_community_health()
        health["generated_at"] = _now()
        return jsonify(_add_scope_meta(health))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@gobelin_bp.route("/community/employees")
def community_employees():
    """Gobelin Bank AI 员工列表 (含师徒/岗位/能力)"""
    conn = _gobelin_conn()
    try:
        gobelin_emps = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_ai_employees WHERE source='GOBELIN_COMMUNITY' ORDER BY level DESC").fetchall()]
        mentorships = {r["mentee_id"]: _row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_community_mentorship WHERE status='ACTIVE'").fetchall()}
        skills = {}
        for r in conn.execute("SELECT * FROM mt_community_skill_snapshot").fetchall():
            sk = _row_to_dict(r)
            skills.setdefault(sk["employee_id"], []).append(sk)

        for emp in gobelin_emps:
            emp["mentorship"] = mentorships.get(emp["employee_id"])
            emp["skill_snapshots"] = skills.get(emp["employee_id"], [])

        return jsonify(_add_scope_meta({
            "ok": True, "count": len(gobelin_emps), "items": gobelin_emps,
            "generated_at": _now(),
        }))
    finally:
        conn.close()


@gobelin_bp.route("/community/roles")
def community_roles():
    """Gobelin Bank 岗位图谱"""
    conn = _gobelin_conn()
    try:
        roles = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_community_gobelin_roles ORDER BY tier, role_code").fetchall()]
        perms = {}
        for r in conn.execute("SELECT * FROM mt_community_permission").fetchall():
            p = _row_to_dict(r)
            perms.setdefault(p["role"], []).append(p)
        caps = {}
        for r in conn.execute("SELECT * FROM mt_community_capability").fetchall():
            c = _row_to_dict(r)
            caps.setdefault(c["role"], []).append(c)

        for role in roles:
            role["permissions"] = perms.get(role["role_code"], [])
            role["capabilities"] = caps.get(role["role_code"], [])

        return jsonify(_add_scope_meta({
            "ok": True, "count": len(roles), "items": roles,
            "generated_at": _now(),
        }))
    finally:
        conn.close()


@gobelin_bp.route("/community/training")
def community_training():
    """培训进度 (最近 50 条)"""
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_community_training ORDER BY id DESC LIMIT 50").fetchall()]
        summary = {
            "total": conn.execute("SELECT COUNT(*) FROM mt_community_training").fetchone()[0],
            "passed": conn.execute(
                "SELECT COUNT(*) FROM mt_community_training WHERE status='PASSED'").fetchone()[0],
            "avg_score": round(conn.execute(
                "SELECT AVG(score) FROM mt_community_training WHERE score>0").fetchone()[0] or 0, 1),
        }
        return jsonify(_add_scope_meta({
            "ok": True, "summary": summary, "recent": rows, "generated_at": _now(),
        }))
    finally:
        conn.close()


@gobelin_bp.route("/community/calibrations")
def community_calibrations():
    """反推校正记录 (最近 50 条)"""
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_community_calibration ORDER BY id DESC LIMIT 50").fetchall()]
        return jsonify(_add_scope_meta({
            "ok": True, "items": rows, "generated_at": _now(),
        }))
    finally:
        conn.close()


@gobelin_bp.route("/community/bootstrap", methods=["POST"])
def community_bootstrap():
    """触发社区一键初始化"""
    try:
        parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if parent not in sys.path: sys.path.insert(0, parent)
        from engines.ai_community_engine import bootstrap_community
        health = bootstrap_community(verbose=False)
        return jsonify(_add_scope_meta({"ok": True, "health": health, "generated_at": _now()}))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# ═══════════════════════════════════════════════════════════════════
# 🧩 Proposal Collaboration Routes (提案智能协作)
# ═══════════════════════════════════════════════════════════════════

def _collab_engines():
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    from engines import proposal_collab_engine as _ce
    return _ce


@gobelin_bp.route("/collab/proposal/<int:proposal_id>")
def collab_proposal(proposal_id):
    """查看提案协作方案 + 痕迹 + 纪要"""
    ce = _collab_engines()
    conn = _gobelin_conn()
    try:
        trace = ce.trace_proposal(proposal_id, conn)
        trace["generated_at"] = _now()
        return jsonify(_add_scope_meta(trace))
    finally:
        conn.close()


@gobelin_bp.route("/collab/analyze/<int:proposal_id>", methods=["POST"])
def collab_analyze(proposal_id):
    """触发提案智能分析"""
    ce = _collab_engines()
    conn = _gobelin_conn()
    try:
        result = ce.analyze_proposal(proposal_id, conn, verbose=False)
        return jsonify(_add_scope_meta(result))
    finally:
        conn.close()


@gobelin_bp.route("/collab/dispatch/<int:proposal_id>", methods=["POST"])
def collab_dispatch(proposal_id):
    """触发派单"""
    ce = _collab_engines()
    conn = _gobelin_conn()
    try:
        result = ce.dispatch_proposal(proposal_id, conn, verbose=False)
        return jsonify(_add_scope_meta(result))
    finally:
        conn.close()


@gobelin_bp.route("/collab/run-pending", methods=["POST"])
def collab_run_pending():
    """批量处理 PENDING 提案"""
    ce = _collab_engines()
    conn = _gobelin_conn()
    try:
        result = ce.run_pending_proposals(limit=20, conn=conn, verbose=False)
        return jsonify(_add_scope_meta(result))
    finally:
        conn.close()


@gobelin_bp.route("/collab/traces")
def collab_traces():
    """最近 50 条协作痕迹"""
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_collab_trace ORDER BY id DESC LIMIT 50").fetchall()]
        return jsonify(_add_scope_meta({"ok": True, "items": rows, "generated_at": _now()}))
    finally:
        conn.close()


@gobelin_bp.route("/collab/growth")
def collab_growth():
    """AI 成长追踪"""
    conn = _gobelin_conn()
    try:
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM mt_collab_growth ORDER BY id DESC").fetchall()]
        return jsonify(_add_scope_meta({"ok": True, "items": rows, "generated_at": _now()}))
    finally:
        conn.close()


@gobelin_bp.route("/collab/minutes/<int:plan_id>")
def collab_minutes(plan_id):
    """协作纪要 Markdown"""
    conn = _gobelin_conn()
    try:
        row = conn.execute(
            "SELECT * FROM mt_collab_minutes WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"minutes for plan {plan_id} not found"}), 404
        m = _row_to_dict(row)
        minutes_md = m.get("minutes_markdown", "")
        # 如果客户端要 Markdown 原文 (text/plain)
        accept = request.headers.get("Accept", "")
        if "text/markdown" in accept or "text/plain" in accept:
            from flask import Response
            return Response(minutes_md, mimetype="text/markdown; charset=utf-8")
        return jsonify(_add_scope_meta({"ok": True, "plan_id": plan_id,
                                        "markdown": minutes_md, "generated_at": _now()}))
    finally:
        conn.close()


def register_gobelin_bp(app):
    """
    在 Flask app 上注册 Gobelin Bank Blueprint。
    被 server_real_db 的 ensure_app_ready() 或 modular_start.py 调用。
    """
    app.register_blueprint(gobelin_bp)
    sys.stderr.write("[GOBELIN] ✅ Gobelin Bank Blueprint 已注册 → /gobelin\n")
    return app


# ═══════════════════════════════════════════════════════════════════
# 🌐 HTML 视图路由 (浏览器直接访问)
# ═══════════════════════════════════════════════════════════════════

@gobelin_bp.route("/view")
def gobelin_view():
    """HTML 仪表盘 (浏览器直接看)"""
    return render_template("gobelin_dashboard.html")
