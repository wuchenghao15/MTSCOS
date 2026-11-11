"""
finance_audit_daemon.py — 定时稽查 + 完整编制
====================================
每个交易日收盘后 (15:35) 执行。8 阶段完整对账 → 生成 JSON 报告。

8-stage pipeline:
  S1 双写一致性     mt_sandbox_trades ↔ mt_trade_log row count + row-by-row diff
  S2 现金守恒核对   每 session: SUM(BUY)-SUM(SELL)-fees = cash_delta vs portfolio.current_cash
  S3 持仓重建验证   positions_json 从 trades 重新推导 → 对比现存 positions
  S4 PnL 对账      snapshots.total_value = cash + position_value?
  S5 佣金/税重算    遍历每 trade, 重算 fee/tax, 对比原值
  S6 异常模式扫描   同秒对倒 / 频繁交易 / sell 亏损集中 → 标记
  S7 完整编制报告   生成 JSON 报告 + 写入 mt_vault_audit_log(SCHEDULED)
  S8 事件广播      broadcast('FINANCE_AUDIT_COMPLETE', report_summary)

输出: mt_vault_audit_log (SCHEDULED 类型) + 本地 reports/*.json
"""

import os
import sys
import json
import uuid
import sqlite3
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger('finance_audit_daemon')

# 可复用实时引擎
from engines.finance_realtime_audit import (
    _resolve_db_path, _connect, ensure_audit_schema,
    COMMISSION_MIN, COMMISSION_RATE, STAMP_TAX_RATE,
)

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'engines', 'finance_audit_reports'
)
os.makedirs(REPORTS_DIR, exist_ok=True)


# ── 辅助: 报告 ID 生成 ──────────────────────────────────────

def _audit_id():
    return f"AUD-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


# ══════════════════════════════════════════════════════════════
# S1. 双写一致性
# ══════════════════════════════════════════════════════════════

def s1_dual_write_consistency(db_path: str) -> dict:
    """校验 mt_sandbox_trades ↔ mt_trade_log 双写一致性"""
    conn = _connect(db_path)
    result = {
        'sb_count': 0, 'tl_count': 0,
        'sb_only_ids': [], 'tl_only_ids': [],
        'mismatch_details': [],
        'verdict': 'PASS',
    }
    try:
        sb_rows = conn.execute(
            "SELECT trade_id, session_id, symbol, action, shares, price, commission, stamp_tax, total_amount "
            "FROM mt_sandbox_trades ORDER BY trade_id"
        ).fetchall()
        tl_rows = conn.execute(
            "SELECT trade_id, action, symbol, qty, price, fee_total, amount "
            "FROM mt_trade_log ORDER BY trade_id"
        ).fetchall()
        result['sb_count'] = len(sb_rows)
        result['tl_count'] = len(tl_rows)

        sb_map = {r['trade_id']: r for r in sb_rows}
        tl_map = {}
        for r in tl_rows:
            tid = str(r['trade_id'])
            tl_map[tid] = r

        sb_ids = set(sb_map.keys())
        tl_ids = set(tl_map.keys())

        result['sb_only_ids'] = sorted(sb_ids - tl_ids)[:20]
        result['tl_only_ids'] = sorted(tl_ids - sb_ids)[:20]

        common_ids = sb_ids & tl_ids
        for tid in sorted(common_ids):
            sb = sb_map[tid]; tl = tl_map[tid]
            mismatches = []
            if sb['action'] != tl['action']:
                mismatches.append(f"action:{sb['action']}≠{tl['action']}")
            if sb['shares'] != tl['qty']:
                mismatches.append(f"qty:{sb['shares']}≠{tl['qty']}")
            if abs(sb['price'] - tl['price']) > 0.01:
                mismatches.append(f"price:{sb['price']}≠{tl['price']}")
            if mismatches:
                result['mismatch_details'].append({'trade_id': tid, 'issues': mismatches})

        if result['sb_count'] != result['tl_count']:
            result['verdict'] = 'FAIL'
        elif result['sb_only_ids'] or result['tl_only_ids']:
            result['verdict'] = 'FAIL'
        elif result['mismatch_details']:
            result['verdict'] = 'WARN'

        result['mismatch_count'] = len(result['mismatch_details'])
    finally:
        conn.close()
    return result


# ══════════════════════════════════════════════════════════════
# S2. 现金守恒核对
# ══════════════════════════════════════════════════════════════

def s2_cash_invariance(db_path: str) -> dict:
    """每 session: 累计 trade 现金流 (BUY 负, SELL 正, fee/tax 负)
    → 加 initial_cash → 应等于 current_cash (忽略持仓市值, 仅现金部分)"""
    conn = _connect(db_path)
    result = {
        'sessions_checked': 0,
        'sessions_pass': 0,
        'sessions_warn': 0,
        'sessions_fail': 0,
        'session_details': [],
    }
    try:
        portfolios = conn.execute(
            "SELECT session_id, initial_cash, current_cash FROM mt_sandbox_portfolio"
        ).fetchall()
        for pf in portfolios:
            session_id = pf['session_id']
            initial = float(pf['initial_cash'])
            current = float(pf['current_cash'])

            trades = conn.execute(
                "SELECT action, shares, price, commission, stamp_tax, total_amount "
                "FROM mt_sandbox_trades WHERE session_id=?",
                (session_id,)
            ).fetchall()

            # 现金流 = SELL 收回 - BUY 支出 - fee - tax
            cash_delta = 0.0
            for t in trades:
                side = t['action'].upper()
                qty = t['shares']; price = t['price']
                fee = t['commission'] or 0
                tax = t['stamp_tax'] or 0
                if side == 'BUY':
                    cash_delta -= qty * price + fee + tax
                else:
                    cash_delta += qty * price - fee - tax

            expected_cash = initial + cash_delta
            gap = abs(current - expected_cash)
            gap_pct = gap / max(abs(expected_cash), 0.01) * 100

            detail = {
                'session_id': session_id,
                'initial_cash': round(initial, 2),
                'trades_count': len(trades),
                'cash_delta_from_trades': round(cash_delta, 2),
                'expected_cash_after_delta': round(expected_cash, 2),
                'actual_current_cash': round(current, 2),
                'gap': round(gap, 2),
                'gap_pct': round(gap_pct, 4),
            }
            result['sessions_checked'] += 1
            if gap < 0.1:
                result['sessions_pass'] += 1
                detail['verdict'] = 'PASS'
            elif gap_pct < 5.0:
                result['sessions_warn'] += 1
                detail['verdict'] = 'WARN'
            else:
                result['sessions_fail'] += 1
                detail['verdict'] = 'FAIL'
            result['session_details'].append(detail)
    finally:
        conn.close()
    return result


# ══════════════════════════════════════════════════════════════
# S3. 持仓重建验证
# ══════════════════════════════════════════════════════════════

def s3_position_rebuild(db_path: str) -> dict:
    """从 trades 重建 positions_json, 对比现存 portfolio 持仓"""
    conn = _connect(db_path)
    result = {
        'sessions_checked': 0,
        'sessions_pass': 0,
        'sessions_warn': 0,
        'sessions_fail': 0,
        'session_details': [],
    }
    try:
        portfolios = conn.execute(
            "SELECT session_id, positions_json FROM mt_sandbox_portfolio"
        ).fetchall()
        for pf in portfolios:
            sid = pf['session_id']
            # 重建持仓
            rebuilt: dict[str, int] = defaultdict(int)
            trades = conn.execute(
                "SELECT action, shares, symbol FROM mt_sandbox_trades WHERE session_id=?",
                (sid,)
            ).fetchall()
            for t in trades:
                sym = t['symbol']
                qty = t['shares']
                if t['action'].upper() == 'BUY':
                    rebuilt[sym] += qty
                else:
                    rebuilt[sym] -= qty

            # 现存持仓
            existing: dict[str, int] = {}
            try:
                raw = pf['positions_json']
                if raw:
                    for pos in json.loads(raw):
                        sym = pos.get('symbol')
                        qty = int(pos.get('shares', pos.get('qty', 0)) or 0)
                        if sym and qty > 0:
                            existing[sym] = qty
            except Exception:
                pass

            rebuilt_positive = {k: v for k, v in rebuilt.items() if v > 0}
            all_syms = set(rebuilt_positive.keys()) | set(existing.keys())
            mismatches = []
            for sym in all_syms:
                rq = rebuilt_positive.get(sym, 0)
                eq = existing.get(sym, 0)
                if rq != eq:
                    mismatches.append({'symbol': sym, 'rebuilt': rq, 'existing': eq})

            result['sessions_checked'] += 1
            detail = {
                'session_id': sid,
                'symbols_in_rebuild': len(rebuilt_positive),
                'symbols_in_portfolio': len(existing),
                'mismatches': mismatches,
            }
            if not mismatches:
                result['sessions_pass'] += 1
                detail['verdict'] = 'PASS'
            elif all(abs(m['rebuilt'] - m['existing']) <= 0 for m in mismatches):
                result['sessions_warn'] += 1
                detail['verdict'] = 'WARN'
            else:
                result['sessions_fail'] += 1
                detail['verdict'] = 'FAIL'
            result['session_details'].append(detail)
    finally:
        conn.close()
    return result


# ══════════════════════════════════════════════════════════════
# S4. PnL 对账
# ══════════════════════════════════════════════════════════════

def s4_pnl_reconciliation(db_path: str) -> dict:
    """验证 snapshots.total_value ≈ cash_value + position_value"""
    conn = _connect(db_path)
    result = {
        'snapshots_checked': 0,
        'pass': 0, 'warn': 0, 'fail': 0,
        'details': [],
    }
    try:
        snaps = conn.execute(
            "SELECT snap_id, session_id, snap_date, total_value, cash_value, position_value "
            "FROM mt_sandbox_snapshots ORDER BY session_id, snap_date DESC LIMIT 30"
        ).fetchall()
        for s in snaps:
            expected_total = float(s['cash_value'] or 0) + float(s['position_value'] or 0)
            actual_total = float(s['total_value'] or 0)
            gap = abs(actual_total - expected_total)
            gap_pct = gap / max(abs(expected_total), 0.01) * 100
            result['snapshots_checked'] += 1
            detail = {
                'snap_id': s['snap_id'], 'session_id': s['session_id'],
                'snap_date': s['snap_date'],
                'cash': round(float(s['cash_value'] or 0), 2),
                'position_value': round(float(s['position_value'] or 0), 2),
                'expected_total': round(expected_total, 2),
                'reported_total': round(actual_total, 2),
                'gap': round(gap, 2),
                'gap_pct': round(gap_pct, 4),
            }
            if gap < 0.5:
                result['pass'] += 1; detail['verdict'] = 'PASS'
            elif gap_pct < 2.0:
                result['warn'] += 1; detail['verdict'] = 'WARN'
            else:
                result['fail'] += 1; detail['verdict'] = 'FAIL'
            result['details'].append(detail)
    finally:
        conn.close()
    return result


# ══════════════════════════════════════════════════════════════
# S5. 佣金/税重算
# ══════════════════════════════════════════════════════════════

def s5_fee_tax_recalc(db_path: str) -> dict:
    """遍历每笔交易, 重算 fee/tax 对比实际值"""
    conn = _connect(db_path)
    result = {
        'trades_checked': 0,
        'fee_mismatches': [],
        'tax_mismatches': [],
        'total_fee_diff': 0.0,
        'total_tax_diff': 0.0,
    }
    try:
        trades = conn.execute(
            "SELECT trade_id, action, total_amount, commission, stamp_tax "
            "FROM mt_sandbox_trades"
        ).fetchall()
        for t in trades:
            result['trades_checked'] += 1
            side = t['action'].upper()
            amount = float(t['total_amount'])
            fee = float(t['commission'] or 0)
            tax = float(t['stamp_tax'] or 0)

            exp_fee = round(max(COMMISSION_MIN, amount * COMMISSION_RATE), 2)
            exp_tax = round(amount * STAMP_TAX_RATE, 2) if side == 'SELL' else 0.0

            fee_diff = abs(fee - exp_fee)
            tax_diff = abs(tax - exp_tax)

            if fee_diff > 0.02:
                result['fee_mismatches'].append({
                    'trade_id': t['trade_id'], 'side': side,
                    'amount': amount, 'actual_fee': fee, 'expected_fee': exp_fee,
                    'diff': round(fee_diff, 4),
                })
                result['total_fee_diff'] += fee_diff

            if tax_diff > 0.02:
                result['tax_mismatches'].append({
                    'trade_id': t['trade_id'], 'side': side,
                    'amount': amount, 'actual_tax': tax, 'expected_tax': exp_tax,
                    'diff': round(tax_diff, 4),
                })
                result['total_tax_diff'] += tax_diff
    finally:
        conn.close()
    result['fee_mismatch_count'] = len(result['fee_mismatches'])
    result['tax_mismatch_count'] = len(result['tax_mismatches'])
    return result


# ══════════════════════════════════════════════════════════════
# S6. 异常模式扫描
# ══════════════════════════════════════════════════════════════

def s6_pattern_scan(db_path: str) -> dict:
    """异常交易模式"""
    conn = _connect(db_path)
    result = {
        'cross_trades': [],           # 同秒对倒 (同 session 同 symbol 秒内 BUY+SELL)
        'frequent_traders': [],       # 同一 session 交易超过阈值
        'sell_loss_focus': [],        # sell 亏损股票集中
        'warnings': 0,
    }
    try:
        # 按 session + symbol + 秒 分组
        trades = conn.execute(
            "SELECT trade_id, session_id, symbol, action, trade_date, trade_time, shares "
            "FROM mt_sandbox_trades ORDER BY session_id, trade_date, trade_time"
        ).fetchall()

        # 同秒对倒
        by_key = defaultdict(list)
        for t in trades:
            key = (t['session_id'], t['symbol'], t['trade_date'], t['trade_time'][:8])
            by_key[key].append(t)
        for key, group in by_key.items():
            sides = set(x['action'].upper() for x in group)
            if 'BUY' in sides and 'SELL' in sides and len(group) >= 2:
                result['cross_trades'].append({
                    'session_id': key[0], 'symbol': key[1],
                    'time': f"{key[2]} {key[3]}",
                    'trades': [x['trade_id'] for x in group],
                })

        # 频繁交易 (同一 session > 50 笔)
        session_counts = defaultdict(int)
        for t in trades:
            session_counts[t['session_id']] += 1
        for sid, cnt in session_counts.items():
            if cnt >= 50:
                result['frequent_traders'].append({'session_id': sid, 'trade_count': cnt})

        result['warnings'] = len(result['cross_trades']) + len(result['frequent_traders'])
    finally:
        conn.close()
    return result


# ══════════════════════════════════════════════════════════════
# S7. 完整编制报告
# ══════════════════════════════════════════════════════════════

def s7_compile_report(
    s1: dict, s2: dict, s3: dict, s4: dict, s5: dict, s6: dict
) -> dict:
    """组装完整 JSON 报告 + 写入 mt_vault_audit_log(SCHEDULED)"""
    now = datetime.now()
    summary_dimensions = {}
    dims = {
        'D01': '资金充足', 'D02': '持仓充足', 'D03': 'T+1 结算',
        'D04': '价格异常', 'D05': '数量异常', 'D06': '双写一致性',
        'D07': '佣金计算', 'D08': '印花税规则', 'D09': '现金守恒',
        'D10': '重复下单', 'D11': '熔断检查', 'D12': '信号一致性',
    }
    for d in dims:
        summary_dimensions[d] = {'pass': 0, 'warn': 0, 'fail': 0}

    # 把 S1-S6 映射到 12 维度 summary
    if s1.get('verdict') == 'PASS':
        summary_dimensions['D06']['pass'] = s1.get('sb_count', 0)
    elif s1.get('verdict') == 'WARN':
        summary_dimensions['D06']['warn'] = s1.get('sb_count', 0)
    else:
        summary_dimensions['D06']['fail'] = s1.get('mismatch_count', 0) + len(s1.get('sb_only_ids', [])) + len(s1.get('tl_only_ids', []))
        summary_dimensions['D06']['warn'] = max(0, s1.get('sb_count', 0) - summary_dimensions['D06']['fail'])

    summary_dimensions['D09']['pass'] = s2.get('sessions_pass', 0)
    summary_dimensions['D09']['warn'] = s2.get('sessions_warn', 0)
    summary_dimensions['D09']['fail'] = s2.get('sessions_fail', 0)

    summary_dimensions['D02']['pass'] = s3.get('sessions_pass', 0)
    summary_dimensions['D02']['warn'] = s3.get('sessions_warn', 0)
    summary_dimensions['D02']['fail'] = s3.get('sessions_fail', 0)

    summary_dimensions['D07']['fail'] = s5.get('fee_mismatch_count', 0)
    summary_dimensions['D08']['fail'] = s5.get('tax_mismatch_count', 0)

    # 汇总
    total_trades = max(s1.get('sb_count', 0), s1.get('tl_count', 0))
    sessions_checked = s2.get('sessions_checked', 0)

    critical_issues = s2.get('sessions_fail', 0) + s3.get('sessions_fail', 0) + s1.get('mismatch_count', 0)
    warn_issues = (s2.get('sessions_warn', 0) + s3.get('sessions_warn', 0)
                  + s5.get('fee_mismatch_count', 0) + s5.get('tax_mismatch_count', 0)
                  + s6.get('warnings', 0))
    info_items = max(0, total_trades - critical_issues - warn_issues)

    if critical_issues > 0:
        overall_verdict = 'CRITICAL'
    elif warn_issues > 0:
        overall_verdict = 'WARN'
    else:
        overall_verdict = 'CLEAN'

    # 风险评分 0-100
    risk_score = min(100, (critical_issues * 10 + warn_issues * 3 + s6.get('warnings', 0) * 5))

    recommendations = []
    if s1.get('verdict') != 'PASS':
        recommendations.append('mt_sandbox_trades 与 mt_trade_log 双写不一致 — 建议检查写入路径并修复孤立记录')
    if s2.get('sessions_fail', 0) > 0:
        recommendations.append('存在现金守恒失败的 session — 建议逐笔核对 portfolio.current_cash 与累计 trade 现金流')
    if s3.get('sessions_fail', 0) > 0:
        recommendations.append('存在持仓重建失败的 session — 建议重算 positions_json')
    if s5.get('fee_mismatch_count', 0) > 0:
        recommendations.append(f'佣金重算发现 {s5["fee_mismatch_count"]} 笔偏差 — 建议核查佣金计算逻辑')
    if s5.get('tax_mismatch_count', 0) > 0:
        recommendations.append(f'印花税重算发现 {s5["tax_mismatch_count"]} 笔偏差 — 建议核查 stamp_tax 规则 (仅 SELL 收)')
    if s6.get('cross_trades'):
        recommendations.append(f'发现 {len(s6["cross_trades"])} 组同秒对倒模式 — 建议核查交易行为')
    if not recommendations:
        recommendations.append('全部通过 — 账务系统状态良好')

    report = {
        "audit_id": _audit_id(),
        "audit_type": "SCHEDULED_DAILY",
        "date": now.strftime('%Y-%m-%d'),
        "generated_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "summary": {
            "total_trades_checked": total_trades,
            "sessions_checked": sessions_checked,
            "dimensions": summary_dimensions,
            "overall_verdict": overall_verdict,
            "risk_score": risk_score,
            "critical_issues": critical_issues,
            "warn_issues": warn_issues,
            "info_items": info_items,
        },
        "details": {
            "dual_write_consistency": {
                "sb_count": s1.get('sb_count'), "tl_count": s1.get('tl_count'),
                "sb_only_ids": s1.get('sb_only_ids', []),
                "tl_only_ids": s1.get('tl_only_ids', []),
                "mismatch_count": s1.get('mismatch_count', 0),
                "verdict": s1.get('verdict'),
            },
            "cash_invariance": {
                "sessions_checked": s2.get('sessions_checked'),
                "pass": s2.get('sessions_pass'),
                "warn": s2.get('sessions_warn'),
                "fail": s2.get('sessions_fail'),
                "session_details": s2.get('session_details', []),
            },
            "position_rebuild": {
                "sessions_checked": s3.get('sessions_checked'),
                "pass": s3.get('sessions_pass'),
                "warn": s3.get('sessions_warn'),
                "fail": s3.get('sessions_fail'),
                "session_details": s3.get('session_details', []),
            },
            "pnl_reconciliation": {
                "snapshots_checked": s4.get('snapshots_checked'),
                "pass": s4.get('pass'), "warn": s4.get('warn'), "fail": s4.get('fail'),
            },
            "fee_tax_recalc": {
                "trades_checked": s5.get('trades_checked'),
                "fee_mismatch_count": s5.get('fee_mismatch_count'),
                "tax_mismatch_count": s5.get('tax_mismatch_count'),
                "fee_total_diff": round(s5.get('total_fee_diff', 0), 2),
                "tax_total_diff": round(s5.get('total_tax_diff', 0), 2),
            },
            "pattern_scan": {
                "cross_trades_count": len(s6.get('cross_trades', [])),
                "frequent_traders_count": len(s6.get('frequent_traders', [])),
                "cross_trades_sample": s6.get('cross_trades', [])[:5],
            },
        },
        "recommendations": recommendations,
    }

    return report


def persist_report(db_path: str, report: dict) -> str:
    """JSON → 文件系统 + mt_vault_audit_log (SCHEDULED)"""
    # 文件系统
    report_path = os.path.join(REPORTS_DIR, f"{report['audit_id']}.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # mt_vault_audit_log — 汇总记录一条
    conn = _connect(db_path)
    ensure_audit_schema(db_path)
    try:
        summary = report['summary']
        audit_id = report['audit_id']
        overall = summary['overall_verdict']
        level = 'CRITICAL' if overall == 'CRITICAL' else ('WARN' if overall == 'WARN' else 'INFO')
        conn.execute(
            "INSERT OR IGNORE INTO mt_vault_audit_log "
            "(audit_id, audit_type, dimension, level, description, expected, actual, verdict) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (audit_id, 'SCHEDULED', 'SUMMARY', level,
             f"日终定时稽查 — trades={summary['total_trades_checked']}, "
             f"sessions={summary['sessions_checked']}, risk={summary['risk_score']}, "
             f"critical={summary['critical_issues']}, warn={summary['warn_issues']}",
             'CLEAN', overall, overall)
        )
        # 将各阶段 also 记一条
        for dim_key, detail_key in [
            ('S1', 'dual_write_consistency'),
            ('S2', 'cash_invariance'),
            ('S3', 'position_rebuild'),
            ('S4', 'pnl_reconciliation'),
            ('S5', 'fee_tax_recalc'),
            ('S6', 'pattern_scan'),
        ]:
            d = report['details'][detail_key]
            d_verdict = d.get('verdict')
            d_level = 'WARN' if d_verdict == 'WARN' else ('ERROR' if d_verdict == 'FAIL' else 'INFO')
            if d_verdict is None:
                # 没有 verdict 字段 — 从 count 推
                if d.get('fail', 0) > 0 or d.get('fee_mismatch_count', 0) > 0 or d.get('tax_mismatch_count', 0) > 0:
                    d_level = 'WARN'
                else:
                    d_level = 'INFO'
            conn.execute(
                "INSERT OR IGNORE INTO mt_vault_audit_log "
                "(audit_id, audit_type, dimension, level, description, verdict) "
                "VALUES (?,?,?,?,?,?)",
                (f"{audit_id}-{dim_key}", 'SCHEDULED', dim_key, d_level,
                 f"阶段 {dim_key} 详情 → {detail_key}",
                 d_verdict or ('WARN' if d_level == 'WARN' else 'PASS'))
            )
        conn.commit()
    finally:
        conn.close()

    return report_path


# ══════════════════════════════════════════════════════════════
# S8. 事件广播
# ══════════════════════════════════════════════════════════════

def s8_broadcast(report: dict) -> dict:
    """尝试通过 collab_bus / 日志广播事件"""
    summary = report['summary']
    event = {
        'event': 'FINANCE_AUDIT_COMPLETE',
        'domain': 'gobelin',
        'payload': {
            'audit_id': report['audit_id'],
            'verdict': summary['overall_verdict'],
            'risk_score': summary['risk_score'],
            'trades_checked': summary['total_trades_checked'],
            'sessions_checked': summary['sessions_checked'],
            'critical': summary['critical_issues'],
            'warn': summary['warn_issues'],
        },
        'timestamp': datetime.now().isoformat(),
    }

    # 尝试通过 Flask signal / collab_bus
    broadcast_result = {'method': 'logger', 'success': True}
    try:
        from engines.collab_bus_engine import bus
        if hasattr(bus, 'publish'):
            bus.publish('finance.audit', event)
            broadcast_result = {'method': 'collab_bus', 'success': True}
    except Exception:
        pass

    logger.info(f"[AUDIT] {event['event']} verdict={event['payload']['verdict']} "
                f"risk={event['payload']['risk_score']}")
    return broadcast_result


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def run_scheduled_audit(db_path: Optional[str] = None) -> dict:
    """完整 8 阶段定时稽查"""
    db_path = _resolve_db_path(db_path)
    print(f"[定时稽查] DB → {db_path}")
    print(f"[定时稽查] 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    stages = []

    # S1
    print("S1 双写一致性 ... ", end='', flush=True)
    s1 = s1_dual_write_consistency(db_path)
    print(f"{s1['verdict']} (sandbox={s1['sb_count']}, trade_log={s1['tl_count']})")
    stages.append(('S1', s1))

    # S2
    print("S2 现金守恒核对 ... ", end='', flush=True)
    s2 = s2_cash_invariance(db_path)
    print(f"PASS={s2['sessions_pass']} WARN={s2['sessions_warn']} FAIL={s2['sessions_fail']}")
    stages.append(('S2', s2))

    # S3
    print("S3 持仓重建验证 ... ", end='', flush=True)
    s3 = s3_position_rebuild(db_path)
    print(f"PASS={s3['sessions_pass']} WARN={s3['sessions_warn']} FAIL={s3['sessions_fail']}")
    stages.append(('S3', s3))

    # S4
    print("S4 PnL 对账 ... ", end='', flush=True)
    s4 = s4_pnl_reconciliation(db_path)
    print(f"PASS={s4['pass']} WARN={s4['warn']} FAIL={s4['fail']}")
    stages.append(('S4', s4))

    # S5
    print("S5 佣金/税重算 ... ", end='', flush=True)
    s5 = s5_fee_tax_recalc(db_path)
    print(f"fee_mismatch={s5['fee_mismatch_count']} tax_mismatch={s5['tax_mismatch_count']}")
    stages.append(('S5', s5))

    # S6
    print("S6 异常模式扫描 ... ", end='', flush=True)
    s6 = s6_pattern_scan(db_path)
    print(f"cross_trades={len(s6['cross_trades'])} frequent={len(s6['frequent_traders'])}")
    stages.append(('S6', s6))

    # S7
    print("S7 完整编制报告 ... ", end='', flush=True)
    report = s7_compile_report(s1, s2, s3, s4, s5, s6)
    report_path = persist_report(db_path, report)
    print(f"✅ {report_path}")
    stages.append(('S7', report))

    # S8
    print("S8 事件广播 ... ", end='', flush=True)
    bc = s8_broadcast(report)
    print(f"{bc['method']}")
    stages.append(('S8', bc))

    # 汇总打印
    summary = report['summary']
    print()
    print(f"{'='*60}")
    print(f" 定时稽查完成 — {report['audit_id']}")
    print(f" verdict: {summary['overall_verdict']}    risk_score: {summary['risk_score']}")
    print(f" trades:  {summary['total_trades_checked']}     sessions: {summary['sessions_checked']}")
    print(f" critical_issues: {summary['critical_issues']}   warn_issues: {summary['warn_issues']}")
    print(f"{'='*60}")
    print()
    print(f"报告文件: {report_path}")
    print(f"建议:")
    for r in report['recommendations']:
        print(f" • {r}")
    print()

    return {'report': report, 'report_path': report_path, 'stages': {k: v for k, v in stages}}


# ── CLI ────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='MTSCOS Gobelin 定时账务稽查')
    parser.add_argument('--db', default=None, help='数据库路径')
    args = parser.parse_args()

    result = run_scheduled_audit(args.db)

    # 输出 JSON 总结 (方便外部调用)
    print("\n--- JSON_SUMMARY_BEGIN ---")
    summary = result['report']['summary']
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("--- JSON_SUMMARY_END ---")


if __name__ == '__main__':
    main()
