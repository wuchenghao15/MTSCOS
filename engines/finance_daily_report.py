#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finance_daily_report.py — 古灵阁银行自动日报生成器
====================================================
收盘后运行 (15:35), 生成 JSON + 终端文本报告 + 写入 mt_center_knowledge_points.

用法:
    python3 engines/finance_daily_report.py                # 今日
    python3 engines/finance_daily_report.py 2026-11-07    # 指定日期
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('finance_daily_report')

RUNTIME_DIR = None  # 延迟初始化


def _resolve_db():
    candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'),
        os.path.join(os.getcwd(), 'database', 'app.db'),
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return candidates[0]


def _resolve_runtime():
    global RUNTIME_DIR
    if RUNTIME_DIR:
        return RUNTIME_DIR
    cands = [
        os.path.join(os.path.dirname(__file__), '..', '_runtime'),
        os.path.join(os.getcwd(), '_runtime'),
    ]
    for c in cands:
        os.makedirs(c, exist_ok=True)
        RUNTIME_DIR = os.path.abspath(c)
        return RUNTIME_DIR
    RUNTIME_DIR = os.path.abspath(cands[0])
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    return RUNTIME_DIR


class DailyReportGenerator:
    """自动日报生成器."""

    def __init__(self, db_path=None, report_date=None):
        self.db_path = db_path or _resolve_db()
        self.report_date = report_date or datetime.now().strftime('%Y-%m-%d')
        self.runtime_dir = _resolve_runtime()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Section 1: 总览 ────────────────────────────────

    def build_overview(self, conn) -> dict:
        """总览数据."""
        # 最新 snapshot 的总资产
        latest = conn.execute(
            "SELECT session_id, total_value, pnl_amount FROM mt_sandbox_snapshots "
            "ORDER BY snap_date DESC LIMIT 300"
        ).fetchall()

        total_assets = sum(float(r['total_value'] or 0) for r in latest)
        total_pnl = sum(float(r['pnl_amount'] or 0) for r in latest)
        today_pnl = sum(float(r['pnl_amount'] or 0) for r in latest
                        if r['session_id'] in [s['session_id'] for s in conn.execute(
                            "SELECT DISTINCT session_id FROM mt_sandbox_snapshots "
                            "WHERE snap_date=?", (self.report_date,)
                        ).fetchall()])

        # 今日交易数
        today_trades = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_trades WHERE trade_date=?", (self.report_date,)
        ).fetchone()[0]
        total_trades = conn.execute(
            "SELECT COUNT(*) FROM mt_sandbox_trades"
        ).fetchone()[0]

        # 活跃 session 数
        active_sessions = len(conn.execute(
            "SELECT DISTINCT session_id FROM mt_sandbox_snapshots WHERE snap_date=?",
            (self.report_date,)
        ).fetchall())
        total_sessions = len(conn.execute(
            "SELECT DISTINCT session_id FROM mt_sandbox_snapshots"
        ).fetchall())

        # 累计收益
        total_return_pct = 0.0
        sessions = conn.execute(
            "SELECT DISTINCT session_id FROM mt_sandbox_snapshots"
        ).fetchall()
        for s in sessions:
            sid = s['session_id']
            tv = conn.execute(
                "SELECT total_value FROM mt_sandbox_snapshots WHERE session_id=? "
                "ORDER BY snap_date ASC LIMIT 1", (sid,)
            ).fetchone()
            tv_end = conn.execute(
                "SELECT total_value FROM mt_sandbox_snapshots WHERE session_id=? "
                "ORDER BY snap_date DESC LIMIT 1", (sid,)
            ).fetchone()
            if tv and tv_end and float(tv['total_value'] or 0) > 0:
                total_return_pct += (float(tv_end['total_value']) / float(tv['total_value']) - 1)

        return {
            'total_assets': round(total_assets, 2),
            'today_pnl': round(today_pnl, 2),
            'total_pnl': round(total_pnl, 2),
            'today_pnl_pct': round(today_pnl / total_assets * 100, 4) if total_assets > 0 else 0,
            'cumulative_return_pct': round(total_return_pct * 100 / max(len(sessions), 1), 2),
            'today_trades': today_trades,
            'total_trades': total_trades,
            'active_sessions': active_sessions,
            'total_sessions': total_sessions,
        }

    # ── Section 2: 12 维稽查 ────────────────────────────

    def build_audit_section(self, conn) -> dict:
        """稽查 12 维度通过率."""
        today = self.report_date
        all_dims = conn.execute(
            "SELECT dimension, level, verdict FROM mt_vault_audit_log "
            "WHERE date(created_at)=? AND dimension NOT IN ('SUMMARY', 'INFO')",
            (today,)
        ).fetchall()

        # 收集所有 unique 维度
        dims_seen = {}
        for r in all_dims:
            dim = r['dimension']
            verdict = r['verdict'] or r['level'] or 'INFO'
            level = r['level'] or 'INFO'
            if dim not in dims_seen:
                dims_seen[dim] = {'PASS': 0, 'WARN': 0, 'FAIL': 0, 'INFO': 0}
            if verdict in dims_seen[dim]:
                dims_seen[dim][verdict] += 1
            elif level in dims_seen[dim]:
                dims_seen[dim][level] += 1

        # 如果今天没有, 取最新一次
        if not dims_seen:
            latest_sched = conn.execute(
                "SELECT audit_id FROM mt_vault_audit_log "
                "WHERE audit_type='SCHEDULED' AND dimension='SUMMARY' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if latest_sched:
                aid = latest_sched['audit_id']
                for r in conn.execute(
                    "SELECT dimension, level, verdict FROM mt_vault_audit_log "
                    "WHERE audit_id LIKE ? AND dimension NOT IN ('SUMMARY', 'INFO')",
                    (aid + '%',)
                ).fetchall():
                    dim = r['dimension']
                    verdict = r['verdict'] or r['level'] or 'INFO'
                    level = r['level'] or 'INFO'
                    if dim not in dims_seen:
                        dims_seen[dim] = {'PASS': 0, 'WARN': 0, 'FAIL': 0, 'INFO': 0}
                    if verdict in dims_seen[dim]:
                        dims_seen[dim][verdict] += 1
                    elif level in dims_seen[dim]:
                        dims_seen[dim][level] += 1

        # 计算通过率
        total_passed = sum(d.get('PASS', 0) for d in dims_seen.values())
        total_failed = sum(d.get('FAIL', 0) for d in dims_seen.values())
        total_warned = sum(d.get('WARN', 0) for d in dims_seen.values())
        total_checked = total_passed + total_failed + total_warned

        pass_rate = round(total_passed / total_checked * 100, 1) if total_checked > 0 else 100.0

        return {
            'date': today,
            'dimensions': dims_seen,
            'total_checked': total_checked,
            'total_passed': total_passed,
            'total_warned': total_warned,
            'total_failed': total_failed,
            'pass_rate': pass_rate,
        }

    # ── Section 3: 风控 TOP 5 ──────────────────────────

    def build_risk_top5(self, conn) -> dict:
        """风险最高 (CRITICAL/HIGH) 和最低 (LOW) 的 session."""
        risks = conn.execute(
            "SELECT * FROM mt_vault_risk_snapshot "
            "ORDER BY risk_score ASC LIMIT 10"
        ).fetchall()

        if not risks:
            return {'note': '暂无风控数据 (需先跑 RiskEngine)', 'high_risk': [], 'low_risk': []}

        all_rows = conn.execute(
            "SELECT * FROM mt_vault_risk_snapshot ORDER BY risk_score DESC"
        ).fetchall()

        high_risk = [dict(r) for r in reversed(all_rows[-5:])]  # 最低分 → 最高风险
        low_risk = [dict(r) for r in all_rows[:5]]  # 最高分 → 最低风险

        return {
            'high_risk': high_risk,
            'low_risk': low_risk,
        }

    # ── Section 4: 业绩归因 TOP 5 ───────────────────────

    def build_attribution_top5(self, conn) -> dict:
        """行业贡献 + TOP trade."""
        industries = conn.execute(
            "SELECT industry, SUM(value) as total_pnl FROM mt_vault_attribution "
            "WHERE attr_type='INDUSTRY' AND metric='contribution' "
            "GROUP BY industry ORDER BY total_pnl DESC"
        ).fetchall()

        top_trades = conn.execute(
            "SELECT session_id, symbol, industry, value, details FROM mt_vault_attribution "
            "WHERE attr_type='TRADE' AND metric='contribution' AND value IS NOT NULL "
            "ORDER BY value DESC LIMIT 5"
        ).fetchall()
        bottom_trades = conn.execute(
            "SELECT session_id, symbol, industry, value, details FROM mt_vault_attribution "
            "WHERE attr_type='TRADE' AND metric='contribution' AND value IS NOT NULL "
            "ORDER BY value ASC LIMIT 5"
        ).fetchall()

        return {
            'industries': [dict(r) for r in industries[:10]],
            'best_trades': [dict(r) for r in top_trades],
            'worst_trades': [dict(r) for r in bottom_trades],
        }

    # ── Section 5: 问题与建议 ──────────────────────────

    def build_issues(self, conn) -> dict:
        """熔断 session / 信号背离 / 需要关注的."""
        # FROZEN 的 portfolio
        frozen = conn.execute(
            "SELECT session_id, scenario, status, is_frozen, current_cash, initial_cash "
            "FROM mt_sandbox_portfolio WHERE is_frozen=1"
        ).fetchall()

        # 风控 CRITICAL session
        critical = conn.execute(
            "SELECT session_id, risk_score, risk_level, max_drawdown FROM mt_vault_risk_snapshot "
            "WHERE risk_level IN ('CRITICAL', 'HIGH') ORDER BY risk_score ASC"
        ).fetchall()

        # Audit WARN/FAIL (未解决)
        unresolved = conn.execute(
            "SELECT dimension, level, description, verdict FROM mt_vault_audit_log "
            "WHERE verdict IN ('WARN', 'FAIL') AND resolved=0 "
            "ORDER BY rowid DESC LIMIT 10"
        ).fetchall()

        return {
            'frozen_portfolios': [dict(r) for r in frozen],
            'critical_sessions': [dict(r) for r in critical],
            'unresolved_issues': [dict(r) for r in unresolved],
            'warnings': self._generate_warnings(frozen, critical, unresolved),
            'recommendations': self._generate_recommendations(frozen, critical),
        }

    def _generate_warnings(self, frozen, critical, unresolved):
        warns = []
        if frozen:
            warns.append(f"⚠️ {len(frozen)} 个 portfolio 已冻结/熔断")
        if critical:
            warns.append(f"🔴 {len(critical)} 个 session 风险等级 CRITICAL/HIGH")
        if unresolved:
            warns.append(f"🟡 {len(unresolved)} 条稽查 WARN/FAIL 未解决")
        return warns

    def _generate_recommendations(self, frozen, critical):
        recs = []
        if frozen:
            recs.append("检查已冻结 portfolio 的风险触发原因, 评估是否需要手动解冻")
        if critical:
            recs.append("对 CRITICAL session 进行风控干预, 考虑减仓或暂停交易")
        recs.append("关注低 VaR / 高夏普 session, 可作为资金迁移目标")
        recs.append("确保每日 15:40 定时风控 + 归因 + 报告全链路跑通")
        return recs

    # ── 综合组装 ────────────────────────────────────────

    def generate(self) -> dict:
        """生成完整日报."""
        conn = self._connect()
        try:
            overview = self.build_overview(conn)
            audit = self.build_audit_section(conn)
            risk = self.build_risk_top5(conn)
            attr = self.build_attribution_top5(conn)
            issues = self.build_issues(conn)
            # ── 10 大中心健康矩阵 (Orchestrator) ──
            health_matrix = self._build_health_matrix(conn)

            report = {
                'report_type': 'daily_bank_report',
                'report_date': self.report_date,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'arch': '古灵阁银行 (Gobelin Bank) + Andromeda 10-Center Orchestrator',
                'sections': {
                    'overview': overview,
                    'audit': audit,
                    'risk': risk,
                    'attribution': attr,
                    'issues': issues,
                    'health_matrix': health_matrix,
                },
                'health_score': self._compute_health_score(overview, audit, risk),
            }
            return report
        finally:
            conn.close()

    def _build_health_matrix(self, conn) -> dict:
        """调用 CenterOrchestrator 获取 10 中心健康矩阵."""
        try:
            from engines.center_orchestrator import CenterOrchestrator
            orch = CenterOrchestrator(self.db_path)
            hm = orch.cross_center_diagnose()
            return {
                'total_score': hm['total_score'],
                'overall_status': hm['overall_status'],
                'scores': hm['scores'],
                'bottlenecks': hm['bottlenecks'],
                'suggestions': hm['suggestions'],
            }
        except Exception as e:
            # Orchestrator 不可用时自己快速扫描
            scores = {}
            try:
                for center_table, check_sql in [
                    ('gobelin', "SELECT COUNT(*) FROM mt_vault_trades WHERE created_at >= datetime('now','-7 days')"),
                    ('audit', "SELECT COUNT(*) FROM mt_vault_audit_log WHERE created_at >= datetime('now','-3 days')"),
                    ('brainfeed', "SELECT COUNT(*) FROM mt_fm_brain_feed WHERE created_at >= datetime('now','-6 hours')"),
                    ('eventbus', "SELECT COUNT(*) FROM mt_collab_bus_events WHERE created_at >= datetime('now','-24 hours')"),
                ]:
                    cnt = conn.execute(check_sql).fetchone()[0]
                    scores[center_table] = min(100, cnt * 10) if cnt > 0 else 30
            except Exception:
                pass
            return {'total_score': sum(scores.values()) / max(len(scores), 1),
                    'overall_status': 'DEGRADED', 'scores': scores,
                    'bottlenecks': [], 'suggestions': [],
                    'note': f'orchestrator_fallback: {e}'}

    def _compute_health_score(self, overview, audit, risk):
        """计算综合健康评分 (0-100)."""
        score = 100.0

        # 稽查扣分
        pass_rate = audit.get('pass_rate', 100)
        if pass_rate < 100:
            score -= (100 - pass_rate) * 0.5

        # 风控扣分
        conn = self._connect()
        try:
            risks = conn.execute(
                "SELECT risk_level, COUNT(*) FROM mt_vault_risk_snapshot "
                "GROUP BY risk_level"
            ).fetchall()
            level_penalty = {'LOW': 0, 'MEDIUM': 5, 'HIGH': 15, 'CRITICAL': 30, 'UNKNOWN': 0}
            for r in risks:
                score -= level_penalty.get(r['risk_level'], 5) * r[1]
        finally:
            conn.close()

        # 收益加分
        cum_ret = overview.get('cumulative_return_pct', 0)
        if cum_ret > 0:
            score += min(cum_ret * 0.5, 10)

        return max(0.0, min(100.0, round(score, 1)))

    # ── 输出: JSON + 文本 ──────────────────────────────

    def write_files(self, report: dict) -> tuple:
        """写入 JSON + TXT 文件."""
        date_str = report['report_date']
        json_path = os.path.join(self.runtime_dir, f'bank_report_{date_str}.json')
        txt_path = os.path.join(self.runtime_dir, f'bank_report_{date_str}.txt')

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(self._format_text(report))

        return json_path, txt_path

    def _format_text(self, report: dict) -> str:
        o = report['sections']['overview']
        a = report['sections']['audit']
        r = report['sections']['risk']
        attr = report['sections']['attribution']
        i = report['sections']['issues']

        lines = []
        lines.append('')
        lines.append('╔══════════════════════════════════════════════════════════════════════════╗')
        lines.append('║                 🏦 古灵阁银行财务系统 · 自动日报                          ║')
        lines.append('╚══════════════════════════════════════════════════════════════════════════╝')
        lines.append('')
        lines.append(f'  📅 报告日期: {report["report_date"]}')
        lines.append(f'  🕐 生成时间: {report["generated_at"]}')
        lines.append(f'  🏥 综合健康: {report["health_score"]}/100')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  1️⃣ 总览 OVERVIEW')
        lines.append('━' * 72)
        lines.append(f'  总资产:          ¥{o["total_assets"]:,.2f}')
        lines.append(f'  今日盈亏:        ¥{o["today_pnl"]:+,.2f} ({o["today_pnl_pct"]:+.2f}%)')
        lines.append(f'  累计收益 (avg):  {o["cumulative_return_pct"]:+.2f}%')
        lines.append(f'  今日交易:        {o["today_trades"]} 笔')
        lines.append(f'  活跃 session:    {o["active_sessions"]}/{o["total_sessions"]}')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  2️⃣ 实时稽查 12 维度')
        lines.append('━' * 72)
        lines.append(f'  通过率: {a["pass_rate"]}%  ✅ {a["total_passed"]}  ⚠️ {a["total_warned"]}  ❌ {a["total_failed"]}')
        if a.get('dimensions'):
            for dim, counts in sorted(a['dimensions'].items()):
                tag = '✅' if counts.get('PASS', 0) > 0 else '⚠️'
                lines.append(f'    {tag} {dim:12s} PASS={counts.get("PASS",0)} WARN={counts.get("WARN",0)} FAIL={counts.get("FAIL",0)}')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  3️⃣ 风控指标 (风险 TOP ↓)')
        lines.append('━' * 72)
        hr = r.get('high_risk', [])
        if hr:
            lines.append('  🔴 高风险 SESSION:')
            for x in hr[:5]:
                lines.append(f'    {x["session_id"][:12]}  score={x["risk_score"]:.0f}  '
                             f'level={x["risk_level"]:8s}  VaR95={x["var_95"]:.2%}  '
                             f'Sharpe={x["sharpe"]:.2f}  MaxDD={x["max_drawdown"]:.2%}')
        lr = r.get('low_risk', [])
        if lr:
            lines.append('  🟢 健康 SESSION:')
            for x in lr[:5]:
                lines.append(f'    {x["session_id"][:12]}  score={x["risk_score"]:.0f}  '
                             f'level={x["risk_level"]:8s}  Sharpe={x["sharpe"]:.2f}  '
                             f'WinRate={x["win_rate"]:.1%}')
        if not hr and not lr:
            lines.append('  (暂无风控数据 — 请先运行 RiskEngine)')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  4️⃣ 业绩归因 TOP 5')
        lines.append('━' * 72)
        if attr.get('industries'):
            lines.append('  📊 行业贡献:')
            for ind in attr['industries'][:5]:
                sign = '🟢' if ind['total_pnl'] >= 0 else '🔴'
                lines.append(f'    {sign} {ind["industry"]:12s}  PnL={ind["total_pnl"]:+,.2f}')
        if attr.get('best_trades'):
            lines.append('  🏆 最佳 trade:')
            for t in attr['best_trades'][:3]:
                lines.append(f'    {t.get("symbol","")} ({t.get("industry","")})  +¥{t["value"]:,.2f}')
        if attr.get('worst_trades'):
            lines.append('  💀 最差 trade:')
            for t in attr['worst_trades'][:3]:
                lines.append(f'    {t.get("symbol","")} ({t.get("industry","")})  ¥{t["value"]:,.2f}')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  5️⃣ 问题与建议')
        lines.append('━' * 72)
        if i.get('warnings'):
            for w in i['warnings']:
                lines.append(f'  {w}')
        else:
            lines.append('  ✅ 当前无重大问题')
        lines.append('')
        lines.append('  💡 明日建议:')
        for rec in i.get('recommendations', []):
            lines.append(f'    • {rec}')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  6️⃣ 🏛️ Andromeda 10-Center 健康矩阵')
        lines.append('━' * 72)
        hm = report.get('sections', {}).get('health_matrix', {})
        if hm:
            status_emoji = {'OPTIMAL': '🟢', 'HEALTHY': '🟢', 'WARN': '🟡', 'CRITICAL': '🔴'}.get(
                hm.get('overall_status', 'UNKNOWN'), '⚪')
            lines.append(f'  总分: {hm.get("total_score",0):.1f}/100  '
                         f'状态: {status_emoji} {hm.get("overall_status","?")}')
            scores = hm.get('scores', {})
            if scores:
                lines.append('  各中心得分:')
                for ck, sc in sorted(scores.items(), key=lambda x: -x[1]):
                    tag = '🟢' if sc >= 75 else ('🟡' if sc >= 50 else '🔴')
                    lines.append(f'    {tag} {ck:14s} {sc:6.1f}/100')
            bn = hm.get('bottlenecks', [])
            if bn:
                lines.append('  ⚠️ 瓶颈:')
                for b in bn[:5]:
                    lines.append(f'    🔴 {b.get("cn_name",b.get("center","?"))} — {b.get("issue","?")}')
            sgs = hm.get('suggestions', [])
            if sgs:
                lines.append('  💡 改进建议:')
                for s in sgs[:3]:
                    lines.append(f'    • [{s.get("priority","?")}] {s.get("action","?")}')
        else:
            lines.append('  (Orchestrator 未可用 — 跳过)')
        lines.append('')
        lines.append('━' * 72)
        lines.append('  7️⃣ 系统信息')
        lines.append('━' * 72)
        lines.append(f'  引擎: RiskEngine v1.0 + AttributionEngine v1.0')
        lines.append(f'  数据快照: {self.report_date}')
        lines.append(f'  DB: {self.db_path}')
        lines.append('')
        lines.append('┌──────────────────────────────────────────────────────────────────────────┐')
        lines.append('│ 🏦 古灵阁 Gobelin Bank — 银行级财务系统                                  │')
        lines.append('│ 每日 15:40 自动生成 · 数据驱动 · 全链路可追溯                            │')
        lines.append('└──────────────────────────────────────────────────────────────────────────┘')

        return '\n'.join(lines)

    # ── 写入知识库 ─────────────────────────────────────

    def write_knowledge(self, report: dict):
        """摘要写入 mt_center_knowledge_points."""
        import uuid as _uuid
        conn = self._connect()
        try:
            kp_id = str(_uuid.uuid4())[:16]
            conn.execute("""
                INSERT OR REPLACE INTO mt_center_knowledge_points
                    (center_name, kp_type, knowledge_title, knowledge_body,
                     confidence, applied)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                'finance_bank',
                'daily_bank_report',
                f"古灵阁银行日报 {report['report_date']}",
                f"总资产=¥{report['sections']['overview']['total_assets']:,.0f} "
                f"今日PnL={report['sections']['overview']['today_pnl']:+,.0f} "
                f"健康分={report['health_score']}/100 "
                f"session={report['sections']['overview']['active_sessions']}/"
                f"{report['sections']['overview']['total_sessions']}",
                0.95,
                1,
            ))
            conn.commit()
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    report_date = sys.argv[1] if len(sys.argv) > 1 else None

    gen = DailyReportGenerator(report_date=report_date)
    print(f"\n📊 生成日报 {gen.report_date} ...")

    # 先确保 Risk + Attribution 数据存在
    try:
        from engines.finance_risk_engine import RiskEngine
        re = RiskEngine(gen.db_path)
        re.compute_all()
    except Exception as e:
        logger.warning(f"风控引擎未跑: {e}")

    try:
        from engines.finance_attribution import AttributionEngine
        ae = AttributionEngine(gen.db_path)
        ae.compute_all()
    except Exception as e:
        logger.warning(f"归因引擎未跑: {e}")

    report = gen.generate()
    json_path, txt_path = gen.write_files(report)
    gen.write_knowledge(report)

    print(f"\n✅ 日报已生成:")
    print(f"   📄 JSON: {json_path}")
    print(f"   📝 TXT:  {txt_path}")
    print(f"\n{open(txt_path, encoding='utf-8').read()}")


if __name__ == '__main__':
    main()
