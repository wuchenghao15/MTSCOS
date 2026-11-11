#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gobelin 周末周六引擎 — 大学习 + 模型升级 + 数据校准 + 审计核算 + 报告 + 投喂 AI
================================================================================

6 阶段:
  S1 周复盘        mt_sandbox_trades/signals/snapshots → 统计 → mt_center_evolution_log(WEEKLY_REVIEW)
  S2 模型升级维护  mt_version_center/registry + mt_iceberg_threshold_configs
  S3 数据校准      mt_trade_log ↔ mt_sandbox_trades + portfolio.positions_json 重建 + signals 去重
  S4 审计核算      session total_value 重算 vs snapshots → mt_center_evolution_log(WEEKLY_AUDIT)
  S5 详细报告生成  JSON 报告 + mt_center_knowledge_points(kp_type='weekly_summary')
  S6 投喂 AI 脑库  mt_fm_brain_feed + mt_center_knowledge_digest

CLI:
  python3 weekend_saturday_engine.py dry    # 干跑, 只打印, 不写库
  python3 weekend_saturday_engine.py run    # 真跑, 写库

FLOW_ID: flow_gobelin_weekend_sat_20261108
"""
from __future__ import annotations

import os
import sys
import json
import math
import uuid
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 路径解析 ──
_ENGINES_DIR = Path(__file__).resolve().parent
_FLASK_APP_DIR = _ENGINES_DIR.parent
_PROJECT_ROOT = _FLASK_APP_DIR.parent

# 用 db_resolver 找到真实 DB
try:
    from engines._common.db_resolver import get_app_db
    DB_PATH = get_app_db()
except Exception:
    DB_PATH = str(_FLASK_APP_DIR / "database" / "app.db")

REPORT_DIR = _PROJECT_ROOT / "_runtime"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

FLOW_ID = "flow_gobelin_weekend_sat_20261108"
DRY_RUN = False  # 运行时 set

# ── 长假特殊模式 (由 holiday_trigger_engine.py 传入) ──
HOLIDAY_EVE = None      # 长假前最后交易日模式: 假期名称
HOLIDAY_FIRST = None    # 长假第一天休市模式: 假期名称
HOLIDAY_MID = None      # 长假中间工作日休市模式: 假期名称


# ══════════════════════════════════════════════════════════════════
# 辅助: DB 连接 (WAL 模式)
# ══════════════════════════════════════════════════════════════════
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _short_uuid() -> str:
    return uuid.uuid4().hex[:10]


def _exists_table(conn: sqlite3.Connection, table: str) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return r is not None


def _exec(conn: sqlite3.Connection, sql: str, params=(), desc: str = "") -> None:
    if DRY_RUN:
        print(f"  [DRY] {desc or sql[:80]}")
        return
    conn.execute(sql, params)


# ══════════════════════════════════════════════════════════════════
# S1. 周复盘 — 过去 5 交易日统计
# ══════════════════════════════════════════════════════════════════
def s1_weekly_review(conn: sqlite3.Connection) -> dict:
    print("=" * 60)
    print("S1. 周复盘 (过去 5 个交易日)")
    print("=" * 60)

    # 5 个交易日窗口
    today = datetime.now()
    # 简单取过去 14 天 (覆盖周末), 后续再过滤
    start_date = (today - timedelta(days=14)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    trades = conn.execute(
        "SELECT trade_id, session_id, trade_date, symbol, stock_name, action, shares, "
        "price, total_amount, strategy, signal_score FROM mt_sandbox_trades "
        "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
        (start_date, end_date),
    ).fetchall()

    signals = conn.execute(
        "SELECT signal_id, session_id, signal_date, symbol, strategy, signal_type, score "
        "FROM mt_sandbox_signals "
        "WHERE signal_date >= ? AND signal_date <= ?",
        (start_date, end_date),
    ).fetchall()

    snapshots = conn.execute(
        "SELECT snap_id, session_id, snap_date, total_value, cash_value, position_value, "
        "daily_return FROM mt_sandbox_snapshots "
        "WHERE snap_date >= ? AND snap_date <= ?",
        (start_date, end_date),
    ).fetchall()

    # ── 交易统计 ──
    trade_count = len(trades)
    closed_trades = [t for t in trades if t[5] == "SELL"]  # action=SELL 视为平仓
    win_count = 0
    loss_count = 0
    total_pnl = 0.0
    win_pnls = []
    loss_pnls = []
    max_consecutive_loss = 0
    cur_consecutive_loss = 0
    # 配对 BUY/SELL 计算盈亏
    open_positions = {}  # symbol -> {qty, avg_cost}
    pair_results = []
    for t in trades:
        tid, sid, tdate, sym, name, action, shares, price, amount, strat, score = t
        if action == "BUY":
            if sym not in open_positions:
                open_positions[sym] = {"qty": 0, "cost_sum": 0.0}
            op = open_positions[sym]
            new_qty = op["qty"] + shares
            op["cost_sum"] += price * shares
            op["avg_cost"] = op["cost_sum"] / new_qty if new_qty > 0 else 0
            op["qty"] = new_qty
        elif action == "SELL" and sym in open_positions:
            op = open_positions[sym]
            cost_basis = op["avg_cost"] * shares
            pnl = (price * shares) - cost_basis
            total_pnl += pnl
            pair_results.append({"symbol": sym, "pnl": pnl, "date": tdate, "strategy": strat})
            if pnl > 0:
                win_count += 1
                win_pnls.append(pnl)
                cur_consecutive_loss = 0
            else:
                loss_count += 1
                loss_pnls.append(pnl)
                cur_consecutive_loss += 1
                max_consecutive_loss = max(max_consecutive_loss, cur_consecutive_loss)
            op["qty"] -= shares
            if op["qty"] <= 0:
                open_positions.pop(sym, None)

    total_closed = win_count + loss_count
    win_rate = win_count / max(total_closed, 1)
    avg_win = sum(win_pnls) / max(len(win_pnls), 1) if win_pnls else 0
    avg_loss = sum(loss_pnls) / max(len(loss_pnls), 1) if loss_pnls else 0
    profit_factor = abs(avg_win * win_count / (avg_loss * loss_count)) if (avg_loss != 0 and loss_count > 0) else float("inf")

    # Sharpe — 用 snapshots daily_return
    returns = [s[6] for s in snapshots if s[6] is not None and s[6] != 0]
    if len(returns) >= 2:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 0.0001
        sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0
    else:
        sharpe = 0

    # ── 策略表现排名 ──
    strategy_stats: dict[str, dict] = {}
    for pr in pair_results:
        strat = pr["strategy"] or "UNKNOWN"
        s = strategy_stats.setdefault(strat, {"count": 0, "pnl": 0.0, "wins": 0})
        s["count"] += 1
        s["pnl"] += pr["pnl"]
        if pr["pnl"] > 0:
            s["wins"] += 1
    strategy_ranked = sorted(strategy_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)

    # ── 经验教训 ──
    lessons = {
        "profit_patterns": [],
        "failure_lessons": [],
    }
    if strategy_ranked:
        top_strat, top_stats = strategy_ranked[0]
        if top_stats["pnl"] > 0:
            lessons["profit_patterns"].append(
                f"策略 {top_strat} 贡献最大盈利: {top_stats['pnl']:.0f} 元 (胜率 {top_stats['wins']}/{top_stats['count']})"
            )
        bot_strat, bot_stats = strategy_ranked[-1]
        if bot_stats["pnl"] < 0:
            lessons["failure_lessons"].append(
                f"策略 {bot_strat} 亏损最多: {bot_stats['pnl']:.0f} 元"
            )
    if max_consecutive_loss >= 3:
        lessons["failure_lessons"].append(f"出现 {max_consecutive_loss} 次连亏, 需加强风控熔断")

    summary = {
        "week_range": f"{start_date} ~ {end_date}",
        "trade_count": trade_count,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_consecutive_loss": max_consecutive_loss,
        "sharpe": round(sharpe, 2),
        "snapshot_count": len(snapshots),
        "signal_count": len(signals),
        "top_strategy": strategy_ranked[0][0] if strategy_ranked else None,
        "bottom_strategy": strategy_ranked[-1][0] if len(strategy_ranked) > 1 else None,
        "lessons": lessons,
    }

    print(f"  交易总数  : {trade_count} (平仓 {total_closed})")
    print(f"  胜率      : {win_rate:.1%}")
    print(f"  盈亏比    : {profit_factor:.2f}")
    print(f"  总盈亏    : {total_pnl:.0f} 元")
    print(f"  最大连亏  : {max_consecutive_loss}")
    print(f"  Sharpe    : {sharpe:.2f}")
    print(f"  策略排名  : {[(s, round(v['pnl'],0)) for s,v in strategy_ranked]}")
    for l in lessons["profit_patterns"] + lessons["failure_lessons"]:
        print(f"    → {l}")

    # 写 mt_center_evolution_log(WEEKLY_REVIEW)
    _exec(
        conn,
        "INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
        ("gobelin_trading", "WEEKLY_REVIEW", json.dumps(summary, ensure_ascii=False)),
        desc="S1 写 WEEKLY_REVIEW evolution_log",
    )

    summary["_strategy_ranked_full"] = strategy_ranked
    return summary


# ══════════════════════════════════════════════════════════════════
# S2. 模型升级维护
# ══════════════════════════════════════════════════════════════════
def s2_model_upgrade(conn: sqlite3.Connection, s1_summary: dict) -> dict:
    print("\n" + "=" * 60)
    print("S2. 模型升级维护")
    print("=" * 60)

    upgrades_log = []
    threshold_updates = []

    # 用 S1 的策略表现 → 计算"IC"简化版 (信号 score vs 实际 pnl)
    # 这里我们从 S1 的 pair_results 策略排名推导
    strategy_ranked = s1_summary.get("_strategy_ranked_full", [])
    ic_map = {}
    for strat, stats in strategy_ranked:
        # IC 简化 = 胜率 * (pnl/|pnl| 符号) 归一化到 [-1,1]
        wr = stats["wins"] / max(stats["count"], 1)
        sign = 1 if stats["pnl"] >= 0 else -1
        ic = round(wr * sign, 3)
        ic_map[strat] = ic

    # 没有 pair_results 时 fallback: 用 signals 按策略 score 均值
    if not ic_map:
        rows = conn.execute(
            "SELECT strategy, AVG(score) FROM mt_sandbox_signals GROUP BY strategy"
        ).fetchall()
        for strat, avg_score in rows:
            ic_map[strat] = round(avg_score / 100, 3)

    print(f"  IC 系数 (策略 → 信息系数): {ic_map}")

    # bump version
    old_ver_row = conn.execute(
        "SELECT new_version FROM mt_version_center WHERE component='andromeda_core' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    old_ver = old_ver_row[0] if old_ver_row else "v0.1.0"
    # 简单 patch bump
    try:
        parts = old_ver.lstrip("v").split(".")
        patch = int(parts[-1]) + 1
        new_ver = f"v{parts[0]}.{parts[1] if len(parts)>1 else '0'}.{patch}"
    except Exception:
        new_ver = f"v{old_ver}-weekend"

    version_id = "VER-" + _short_uuid()
    _exec(
        conn,
        "INSERT INTO mt_version_center "
        "(version_id, component, old_version, new_version, bump_type, trigger_event, trigger_source, changelog) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            version_id,
            "andromeda_core",
            old_ver,
            new_ver,
            "PATCH",
            "WEEKEND_SATURDAY",
            "weekend_saturday_engine",
            f"周末模型升级: IC={json.dumps(ic_map, ensure_ascii=False)}",
        ),
        desc=f"S2 bump version {old_ver} → {new_ver}",
    )
    upgrades_log.append(f"andromeda_core {old_ver} → {new_ver}")

    # 更新 mt_iceberg_threshold_configs — 策略阈值
    for strat, ic in ic_map.items():
        thr_key = f"strategy_ic_threshold_{strat}"
        if ic > 0.05:
            new_val = 70  # 加权
            desc = f"策略 {strat} IC={ic} 正, 加权阈值 70"
        elif ic < 0:
            new_val = 30  # 降权
            desc = f"策略 {strat} IC={ic} 负, 降权阈值 30"
        else:
            continue
        # upsert
        existing = conn.execute(
            "SELECT id FROM mt_iceberg_threshold_configs WHERE threshold_key=?", (thr_key,)
        ).fetchone()
        if existing:
            _exec(
                conn,
                "UPDATE mt_iceberg_threshold_configs SET value=?, description=?, updated_at=?, updated_by=? WHERE id=?",
                (new_val, desc, _now(), "weekend_saturday_engine", existing[0]),
                desc=f"S2 UPDATE threshold {thr_key}",
            )
        else:
            _exec(
                conn,
                "INSERT INTO mt_iceberg_threshold_configs (threshold_key, value, description, updated_at, updated_by) "
                "VALUES (?,?,?,?,?)",
                (thr_key, new_val, desc, _now(), "weekend_saturday_engine"),
                desc=f"S2 INSERT threshold {thr_key}",
            )
        threshold_updates.append(thr_key)

    print(f"  version_center bump: {old_ver} → {new_ver} (id={version_id})")
    print(f"  iceberg_threshold 更新: {len(threshold_updates)} 项")

    return {
        "old_version": old_ver,
        "new_version": new_ver,
        "ic_map": ic_map,
        "threshold_updates": threshold_updates,
    }


# ══════════════════════════════════════════════════════════════════
# S3. 数据校准
# ══════════════════════════════════════════════════════════════════
def s3_data_calibration(conn: sqlite3.Connection) -> dict:
    print("\n" + "=" * 60)
    print("S3. 数据校准")
    print("=" * 60)

    result = {
        "trade_log_match": 0,
        "portfolio_rebuilt": 0,
        "signals_deduped": 0,
        "cash_diff_issues": [],
    }

    # ── 3.1 mt_trade_log ↔ mt_sandbox_trades row count ──
    sl_count = conn.execute("SELECT COUNT(*) FROM mt_sandbox_trades").fetchone()[0]
    tl_count = conn.execute("SELECT COUNT(*) FROM mt_trade_log").fetchone()[0]
    result["trade_log_match"] = abs(sl_count - tl_count)
    print(f"  sandbox_trades={sl_count}  trade_log={tl_count}  diff={result['trade_log_match']}")

    # ── 3.2 positions_json 重建 (逐 session 回放 trades) ──
    portfolios = conn.execute(
        "SELECT session_id, scenario, current_cash FROM mt_sandbox_portfolio"
    ).fetchall()

    for sid, scenario, current_cash in portfolios:
        # 回放该 session 的所有 BUY/SELL trade
        trades_sid = conn.execute(
            "SELECT action, symbol, shares, price FROM mt_sandbox_trades WHERE session_id=? ORDER BY trade_date, trade_time",
            (sid,),
        ).fetchall()
        positions: dict[str, dict] = {}
        trade_pnl = 0.0  # 用于 cash 推导
        for action, sym, shares, price in trades_sid:
            if action == "BUY":
                if sym not in positions:
                    positions[sym] = {"symbol": sym, "name": sym, "shares": 0, "cost_sum": 0.0}
                pos = positions[sym]
                pos["shares"] += shares
                pos["cost_sum"] += price * shares
            elif action == "SELL":
                trade_pnl += price * shares
                if sym in positions:
                    pos = positions[sym]
                    pos["shares"] -= shares
                    if pos["shares"] <= 0:
                        del positions[sym]

        # 计算持仓 JSON
        pos_list = []
        for sym, p in positions.items():
            if p["shares"] > 0:
                pos_list.append(
                    {
                        "symbol": sym,
                        "name": p["name"],
                        "shares": p["shares"],
                        "avg_cost": round(p["cost_sum"] / p["shares"], 4) if p["shares"] > 0 else 0,
                        "current_price": 0,  # 无实时行情, 保持 0
                    }
                )
        pos_json = json.dumps(pos_list, ensure_ascii=False)

        _exec(
            conn,
            "UPDATE mt_sandbox_portfolio SET positions_json=?, updated_at=? WHERE session_id=?",
            (pos_json, _now(), sid),
            desc=f"S3 重建 portfolio {sid} positions_json",
        )
        result["portfolio_rebuilt"] += 1

    print(f"  portfolio 重建: {result['portfolio_rebuilt']} 个 session")

    # ── 3.3 mt_sandbox_signals 去重 ──
    # 按 (session_id + signal_date + symbol + strategy) 保留 score 最高
    # 安全做法: 先查出每组 MAX(score) 对应的 signal_id, 然后删除不在此集中的
    dup_check = conn.execute(
        "SELECT COUNT(*) FROM mt_sandbox_signals WHERE signal_id NOT IN ("
        "  SELECT signal_id FROM ("
        "    SELECT signal_id, ROW_NUMBER() OVER "
        "    (PARTITION BY session_id, signal_date, symbol, strategy ORDER BY score DESC) as rn "
        "    FROM mt_sandbox_signals"
        "  ) WHERE rn=1"
        ")"
    ).fetchone()
    to_delete_count = dup_check[0] if dup_check else 0

    if to_delete_count > 0 and not DRY_RUN:
        # 分批删除, 避免子查询规模过大
        BATCH = 10000
        total_del = 0
        while True:
            dids = conn.execute(
                "SELECT signal_id FROM mt_sandbox_signals WHERE signal_id NOT IN ("
                "  SELECT signal_id FROM ("
                "    SELECT signal_id, ROW_NUMBER() OVER "
                "    (PARTITION BY session_id, signal_date, symbol, strategy ORDER BY score DESC) as rn "
                "    FROM mt_sandbox_signals"
                "  ) WHERE rn=1"
                ") LIMIT ?",
                (BATCH,),
            ).fetchall()
            if not dids:
                break
            conn.executemany(
                "DELETE FROM mt_sandbox_signals WHERE signal_id=?",
                [(r[0],) for r in dids],
            )
            total_del += len(dids)
            if len(dids) < BATCH:
                break
        result["signals_deduped"] = total_del
    else:
        result["signals_deduped"] = to_delete_count
    print(f"  signals 去重: {result['signals_deduped']} 条 (待删 {to_delete_count})")

    return result


# ══════════════════════════════════════════════════════════════════
# S4. 审计核算
# ══════════════════════════════════════════════════════════════════
def s4_audit(conn: sqlite3.Connection) -> dict:
    print("\n" + "=" * 60)
    print("S4. 审计核算")
    print("=" * 60)

    audit_findings = []

    # 每个 session 重算 total_value = cash + position (无实时价, 用 avg_cost 估值)
    portfolios = conn.execute(
        "SELECT session_id, current_cash, positions_json FROM mt_sandbox_portfolio"
    ).fetchall()

    for sid, cash, pos_json in portfolios:
        try:
            positions = json.loads(pos_json) if pos_json else []
        except Exception:
            positions = []
        pos_value = sum(p.get("shares", 0) * (p.get("current_price", 0) or p.get("avg_cost", 0)) for p in positions)
        recalc_total = cash + pos_value

        # 对比该 session 最新 snapshot
        snap = conn.execute(
            "SELECT total_value, cash_value, position_value FROM mt_sandbox_snapshots "
            "WHERE session_id=? ORDER BY snap_date DESC LIMIT 1",
            (sid,),
        ).fetchone()

        if snap:
            snap_total = snap[0]
            diff_pct = abs(recalc_total - snap_total) / max(abs(snap_total), 1) * 100
            if diff_pct > 0.5:
                finding = {
                    "session_id": sid,
                    "recalc_total": round(recalc_total, 2),
                    "snap_total": round(snap_total, 2),
                    "diff_pct": round(diff_pct, 2),
                    "issue": "snapshot vs portfolio mismatch",
                }
                audit_findings.append(finding)
                print(f"  ⚠️ {sid}: recalc={recalc_total:.0f} snap={snap_total:.0f} diff={diff_pct:.2f}%")

    print(f"  session 审计: {len(portfolios)} 个, 差异>0.5% = {len(audit_findings)}")

    # 写 mt_center_evolution_log(WEEKLY_AUDIT)
    _exec(
        conn,
        "INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
        (
            "gobelin_trading",
            "WEEKLY_AUDIT",
            json.dumps({"findings": audit_findings, "total_sessions": len(portfolios)}, ensure_ascii=False),
        ),
        desc="S4 写 WEEKLY_AUDIT evolution_log",
    )

    return {"findings": audit_findings, "total_sessions": len(portfolios)}


# ══════════════════════════════════════════════════════════════════
# S5. 详细报告生成
# ══════════════════════════════════════════════════════════════════
def s5_report(s1_summary: dict, s2_upgrades: dict, s3_calib: dict, s4_audit: dict) -> dict:
    print("\n" + "=" * 60)
    print("S5. 详细报告生成")
    print("=" * 60)

    # 推荐行动
    actions = []
    if s1_summary.get("max_consecutive_loss", 0) >= 3:
        actions.append("加强风控熔断阈值, 连亏 3 次触发暂停")
    if s4_audit.get("findings"):
        actions.append(f"修复 {len(s4_audit['findings'])} 个 session 的 portfolio/snapshot 差异")
    for strat, ic in s2_upgrades.get("ic_map", {}).items():
        if ic < 0:
            actions.append(f"重新审视策略 {strat}, 考虑暂时停用或调参")

    report = {
        "generated_at": _now(),
        "week_range": s1_summary.get("week_range", ""),
        "flow_id": FLOW_ID,
        "trades_summary": {
            "trade_count": s1_summary.get("trade_count"),
            "win_rate": s1_summary.get("win_rate"),
            "profit_factor": s1_summary.get("profit_factor"),
            "total_pnl": s1_summary.get("total_pnl"),
            "sharpe": s1_summary.get("sharpe"),
            "max_consecutive_loss": s1_summary.get("max_consecutive_loss"),
        },
        "strategy_performance": {
            k: {"count": v["count"], "pnl": v["pnl"], "wins": v["wins"], "ic": s2_upgrades.get("ic_map", {}).get(k)}
            for k, v in dict(s1_summary.get("_strategy_ranked_full", [])).items()
        },
        "lessons_learned": s1_summary.get("lessons", {}),
        "model_upgrades": s2_upgrades,
        "audit_findings": s4_audit,
        "data_calibration": s3_calib,
        "recommended_actions": actions,
    }

    date_str = datetime.now().strftime("%Y%m%d")
    report_path = REPORT_DIR / f"weekly_report_{date_str}.json"
    print(f"  报告写入: {report_path}")

    if not DRY_RUN:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    return report


def s5_write_knowledge_points(conn: sqlite3.Connection, report: dict) -> None:
    # 把报告摘要写入 mt_center_knowledge_points
    summary_text = (
        f"周复盘 {report['week_range']}: 交易 {report['trades_summary']['trade_count']} 次 "
        f"胜率 {report['trades_summary']['win_rate']:.0%} 盈亏比 {report['trades_summary']['profit_factor']} "
        f"总盈亏 {report['trades_summary']['total_pnl']:.0f} Sharpe {report['trades_summary']['sharpe']}. "
        f"Top策略: {report.get('strategy_performance', {}).get(list(report.get('strategy_performance', {}).keys())[0], {}).get('pnl', 0):.0f}"
        if report.get("strategy_performance") else ""
    )
    kp_title = f"周总结_{report.get('week_range', '')}"
    _exec(
        conn,
        "INSERT OR IGNORE INTO mt_center_knowledge_points "
        "(center_name, kp_type, knowledge_title, knowledge_body, confidence) "
        "VALUES (?,?,?,?,?)",
        (
            "gobelin_trading",
            "weekly_summary",
            kp_title,
            json.dumps(report, ensure_ascii=False)[:4000],
            0.8,
        ),
        desc="S5 写 knowledge_points weekly_summary",
    )


# ══════════════════════════════════════════════════════════════════
# S6. 投喂 AI 脑库
# ══════════════════════════════════════════════════════════════════
def s6_feed_brain(conn: sqlite3.Connection, report: dict) -> None:
    print("\n" + "=" * 60)
    print("S6. 投喂 AI 脑库")
    print("=" * 60)

    feed_entries = []
    lessons = report.get("lessons_learned", {})
    model_upg = report.get("model_upgrades", {})
    audit_findings = report.get("audit_findings", {})

    # 经验教训
    for item in lessons.get("profit_patterns", []):
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SATURDAY_LESSON",
                "category": "PROFIT_PATTERN",
                "asr_text": item,
                "trigger_keywords": "盈利模式,经验,复盘",
                "emotion": "HAWK",
                "emotion_score": 0.8,
                "has_price_info": 1,
                "has_policy": 0,
            }
        )
    for item in lessons.get("failure_lessons", []):
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SATURDAY_LESSON",
                "category": "FAILURE_LESSON",
                "asr_text": item,
                "trigger_keywords": "失败教训,风控,连亏",
                "emotion": "DOG",
                "emotion_score": -0.5,
                "has_price_info": 1,
                "has_policy": 0,
            }
        )

    # 模型变更
    if model_upg.get("ic_map"):
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SATURDAY_MODEL",
                "category": "MODEL_UPGRADE",
                "asr_text": f"模型升级 {model_upg.get('old_version')} → {model_upg.get('new_version')}, IC={model_upg.get('ic_map')}",
                "trigger_keywords": "模型升级,IC,策略权重",
                "emotion": "HAWK",
                "emotion_score": 0.7,
                "has_price_info": 0,
                "has_policy": 0,
            }
        )

    # 审计发现
    for f in audit_findings.get("findings", []):
        feed_entries.append(
            {
                "stream_name": "WEEKEND_SATURDAY_AUDIT",
                "category": "AUDIT_FINDING",
                "asr_text": f"审计发现 {f.get('session_id')}: diff={f.get('diff_pct')}%",
                "trigger_keywords": "审计,数据差异,portfolio",
                "emotion": "NEUTRAL",
                "emotion_score": 0.0,
                "has_price_info": 1,
                "has_policy": 0,
            }
        )

    print(f"  brain_feed 条目: {len(feed_entries)}")

    if feed_entries:
        cols = ", ".join(feed_entries[0].keys())
        qmarks = ", ".join(["?"] * len(feed_entries[0]))
        sql = f"INSERT INTO mt_fm_brain_feed ({cols}) VALUES ({qmarks})"
        if not DRY_RUN:
            conn.executemany(sql, [tuple(e.values()) for e in feed_entries])
        else:
            for e in feed_entries:
                print(f"  [DRY] brain_feed: {e['stream_name']} | {e['asr_text'][:60]}")

    # 触发 mt_center_knowledge_digest 生成
    digest_summary = f"周末总结 {report.get('week_range')}: {len(feed_entries)} 条脑库投喂"
    _exec(
        conn,
        "INSERT INTO mt_center_knowledge_digest (center_name, digest_type, digest_summary, kp_count) "
        "VALUES (?,?,?,?)",
        ("gobelin_trading", "weekly", digest_summary, len(feed_entries)),
        desc="S6 写 knowledge_digest weekly",
    )


# ══════════════════════════════════════════════════════════════════
# S7. 长假特殊模式 (由 holiday_trigger_engine 触发)
# ══════════════════════════════════════════════════════════════════
def s7_holiday_special(conn: sqlite3.Connection) -> dict | None:
    """长假前/长假中专项处理. 返回处理结果或 None (非长假模式)"""
    if not HOLIDAY_EVE and not HOLIDAY_FIRST and not HOLIDAY_MID:
        return None

    print("\n" + "=" * 60)
    print("S7. 长假特殊模式")
    print("=" * 60)

    result = {
        'holiday_eve': HOLIDAY_EVE,
        'holiday_first': HOLIDAY_FIRST,
        'holiday_mid': HOLIDAY_MID,
        'actions': [],
    }

    holiday_name = HOLIDAY_EVE or HOLIDAY_FIRST or HOLIDAY_MID or ''

    if HOLIDAY_EVE:
        # ── 长假前最后交易日 ──
        print(f"  🎯 ROLE_HOLIDAY_EVE: {holiday_name} 前最后交易日")

        # 1. 生成长假策略建议
        strategy_advice = [
            f"{holiday_name}长假在即, 建议: 现金比率提升至 30-40%, "
            f"锁定盈利仓位, 减少杠杆操作, 避免长假期间外围市场波动风险",
            f"若持有商品相关标的, 关注假期大宗商品走势与汇率变化",
            f"北向资金假期通常净流入减弱, 警惕节后开盘跳水风险",
        ]
        for advice in strategy_advice:
            print(f"    → {advice[:60]}...")

        # 2. 写入 mt_center_knowledge_points (kp_type='holiday_prep')
        _exec(
            conn,
            "INSERT OR IGNORE INTO mt_center_knowledge_points "
            "(center_name, kp_type, knowledge_title, knowledge_body, confidence) "
            "VALUES (?,?,?,?,?)",
            (
                "gobelin_trading",
                "holiday_prep",
                f"{holiday_name}_节前准备_{_now()[:10]}",
                json.dumps({
                    'holiday': holiday_name,
                    'mode': 'EVE',
                    'strategy_advice': strategy_advice,
                    'generated_at': _now(),
                }, ensure_ascii=False)[:4000],
                0.85,
            ),
            desc=f"S7 写 knowledge_points holiday_prep (EVE)",
        )

        # 3. 触发 mt_center_direction_pool 长假准备 direction
        _exec(
            conn,
            "INSERT OR IGNORE INTO mt_center_direction_pool "
            "(center_name, direction_title, seed, status, priority, auto_spawned) "
            "VALUES (?,?,?,?,?,?)",
            (
                "gobelin_trading",
                f"HOLIDAY_PREP_{holiday_name}",
                f"{holiday_name}长假前准备: 现金比率/仓位调整/对冲策略, 节前最后交易日专项复盘",
                "SEED",
                9,
                1,
            ),
            desc=f"S7 写 direction_pool holiday_prep",
        )

        result['actions'].append('holiday_eve_prep_generated')

        # 4. 投喂 AI 脑库
        feed_entry = {
            'stream_name': 'HOLIDAY_PREP',
            'category': 'HOLIDAY_EVE',
            'asr_text': f"{holiday_name}长假前最后交易日策略建议: " + "; ".join(strategy_advice[:2]),
            'trigger_keywords': f'{holiday_name},长假,节前准备,现金比率',
            'emotion': 'NEUTRAL',
            'emotion_score': 0.3,
            'has_price_info': 1,
            'has_policy': 0,
        }
        if not DRY_RUN:
            cols = ", ".join(feed_entry.keys())
            qmarks = ", ".join(["?"] * len(feed_entry))
            conn.execute(f"INSERT INTO mt_fm_brain_feed ({cols}) VALUES ({qmarks})", tuple(feed_entry.values()))
        result['actions'].append('brain_feed_injected')

    elif HOLIDAY_FIRST or HOLIDAY_MID:
        # ── 长假中间 (第一天或中间工作日) ──
        mode_label = 'FIRST_DAY' if HOLIDAY_FIRST else 'MID_HOLIDAY'
        print(f"  🎯 ROLE_HOLIDAY_{mode_label}: {holiday_name} 休市期间")

        # 1. 长假前最后交易日复盘 (取长假前最后交易日的 trading data)
        # 简化: 从 mt_center_evolution_log 取最近的 WEEKLY_REVIEW
        last_review = conn.execute(
            "SELECT detail, created_at FROM mt_center_evolution_log "
            "WHERE event='WEEKLY_REVIEW' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        review_summary = ''
        if last_review:
            try:
                rev = json.loads(last_review[0])
                review_summary = f"最后交易周: {rev.get('week_range','')}, 胜率 {rev.get('win_rate',0):.1%}, 总盈亏 {rev.get('total_pnl',0):.0f}"
            except Exception:
                review_summary = '(上次复盘数据解析失败)'

        print(f"    → 长假前最后复盘: {review_summary}")

        # 2. 模型校准 (标记需要在节后 run 的校准 task)
        calibration_plan = (
            f"{holiday_name}长假期间计划: 节后第一个交易日开盘前, "
            f"运行数据校准 S3 + 审计 S4, 确保长假期间 portfolio 数据一致性"
        )
        _exec(
            conn,
            "INSERT OR IGNORE INTO mt_center_knowledge_points "
            "(center_name, kp_type, knowledge_title, knowledge_body, confidence) "
            "VALUES (?,?,?,?,?)",
            (
                "gobelin_trading",
                "holiday_review",
                f"{holiday_name}_长假校准计划_{_now()[:10]}",
                json.dumps({
                    'holiday': holiday_name,
                    'mode': mode_label,
                    'pre_holiday_review': review_summary,
                    'calibration_plan': calibration_plan,
                    'generated_at': _now(),
                }, ensure_ascii=False)[:4000],
                0.8,
            ),
            desc=f"S7 写 knowledge_points holiday_review",
        )

        result['actions'].append('holiday_calibration_plan_created')

        # 3. 投喂 AI 脑库
        feed_entry = {
            'stream_name': 'HOLIDAY_REVIEW',
            'category': f'HOLIDAY_{mode_label}',
            'asr_text': f"{holiday_name}{'第一天' if HOLIDAY_FIRST else '中间'}休市, {review_summary}",
            'trigger_keywords': f'{holiday_name},长假,休市,模型校准',
            'emotion': 'NEUTRAL',
            'emotion_score': 0.0,
            'has_price_info': 1,
            'has_policy': 0,
        }
        if not DRY_RUN:
            cols = ", ".join(feed_entry.keys())
            qmarks = ", ".join(["?"] * len(feed_entry))
            conn.execute(f"INSERT INTO mt_fm_brain_feed ({cols}) VALUES ({qmarks})", tuple(feed_entry.values()))
        result['actions'].append('brain_feed_injected')

    print(f"  ✓ S7 完成, actions: {result['actions']}")
    return result


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════
def run_weekend_saturday(
    dry_run: bool = False,
    holiday_eve: str = None,
    holiday_first: str = None,
    holiday_mid: str = None,
) -> dict:
    """
    周六引擎主入口.

    Args:
        dry_run: 是否干跑
        holiday_eve: 长假前最后交易日模式 (假期名称)
        holiday_first: 长假第一天休市模式 (假期名称)
        holiday_mid: 长假中间工作日模式 (假期名称)
    """
    global DRY_RUN, HOLIDAY_EVE, HOLIDAY_FIRST, HOLIDAY_MID
    DRY_RUN = dry_run
    HOLIDAY_EVE = holiday_eve
    HOLIDAY_FIRST = holiday_first
    HOLIDAY_MID = holiday_mid

    holiday_mode_label = ""
    if HOLIDAY_EVE:
        holiday_mode_label = f" [HOLIDAY_EVE: {HOLIDAY_EVE}]"
    elif HOLIDAY_FIRST:
        holiday_mode_label = f" [HOLIDAY_FIRST: {HOLIDAY_FIRST}]"
    elif HOLIDAY_MID:
        holiday_mode_label = f" [HOLIDAY_MID: {HOLIDAY_MID}]"

    print(f"\n{'#'*60}")
    print(f"# Gobelin 周末周六引擎 — {'DRY RUN' if DRY_RUN else 'REAL RUN'}{holiday_mode_label}")
    print(f"# DB: {DB_PATH}")
    print(f"# 时间: {_now()}")
    print(f"{'#'*60}\n")

    conn = _connect()
    try:
        # 前置检查表
        for tbl in ["mt_sandbox_trades", "mt_sandbox_portfolio", "mt_sandbox_signals"]:
            if not _exists_table(conn, tbl):
                print(f"  ⚠️ 表不存在: {tbl}")

        # S1
        s1 = s1_weekly_review(conn)
        # S2
        s2 = s2_model_upgrade(conn, s1)
        # S3
        s3 = s3_data_calibration(conn)
        # S4
        s4 = s4_audit(conn)
        # S5
        report = s5_report(s1, s2, s3, s4)
        s5_write_knowledge_points(conn, report)
        # S6
        s6_feed_brain(conn, report)
        # S7 (长假特殊模式)
        s7 = s7_holiday_special(conn)

        print(f"\n{'#'*60}")
        print(f"# 周六引擎 {'DRY' if DRY_RUN else 'REAL'} 完成!{holiday_mode_label}")
        print(f"{'#'*60}\n")

        if DRY_RUN:
            conn.rollback()
        else:
            conn.commit()

        result = {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "report": report}
        if s7:
            result["s7"] = s7
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Gobelin 周末周六引擎')
    parser.add_argument('mode', nargs='?', default='run',
                        help='run 或 dry')
    parser.add_argument('--holiday-eve', default=None,
                        help='长假前最后交易日模式, 指定假期名称')
    parser.add_argument('--holiday-first', default=None,
                        help='长假第一天休市模式')
    parser.add_argument('--holiday-mid', default=None,
                        help='长假中间工作日休市模式')
    args = parser.parse_args()

    run_weekend_saturday(
        dry_run=(args.mode == 'dry'),
        holiday_eve=args.holiday_eve,
        holiday_first=args.holiday_first,
        holiday_mid=args.holiday_mid,
    )
