#!/usr/bin/env python3
"""
maintenance_pipeline — 统一维护升级管道
=======================================

所有维护/升级/部署/迁移动作必须通过此管道执行。
遵循 MT_IRON_RULE_12STEPS §12 + MT_RULE_CLASSIFICATION §4 + 仙女座 fail-closed。

管道流程 (5 段)
───────────────────────────────────────────────────────────────────
  1. PRE_CHECK   规则完整性扫描覆盖率检查 (risk=high/critical 要求 100%)
  2. CHANGELOG   写入 mt_rule_changelog 预审记录
  3. EXECUTE     执行真实维护函数体
  4. POST_AUDIT  UPDATE changelog 执行结果 + 触发 rule_enforcer 重扫
  5. VIOLATION   执行失败自动写 mt_iron_rule_violations

治理表真实列 (已校对 app.db):
  mt_rule_changelog        主键=changelog_id (INTEGER), pipeline_id (TEXT), execution_* 列 ✓
  mt_iron_rule_violations  主键=viol_id (TEXT), viol_rule/viol_stage, 时间戳 REAL (epoch)
  mt_rule_violation_alert  主键=alert_id (TEXT), alert_payload (TEXT), 时间戳 REAL
  mt_rule_integrity_scan   主键=scan_id (TEXT), score (REAL, 0-100) = 覆盖率
  mt_pipeline_execution_log 新建 ✓

使用示例:
  @maintenance_pipeline(action='seed', risk='medium', exempt_daemon=True)
  def seed_all(self): ...
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

# ── DB 路径 ──
_DB_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'database', 'app.db'))
if not os.path.exists(_DB_PATH):
    for p in [
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                     '_runtime', 'databases', 'Database', 'mtscos.db')),
    ]:
        if os.path.exists(p): _DB_PATH = p; break

# ── 风险 + 动作定义 ──
_RISK_LEVELS = {'low', 'medium', 'high', 'critical'}
_ACTION_MAP = {
    'seed':    ('初始数据填充', 'mt_*'),
    'deploy':  ('部署',          'mt_release_sessions'),
    'upgrade': ('版本升级',      'mt_release_sessions'),
    'rollback':('回滚',          'mt_release_sessions'),
    'migrate': ('迁移/结构变更', '*'),
    'patch':   ('热修/补丁',     '*'),
    'evolve':  ('进化/自研发',   'mt_iceberg_*'),
    'toggle':  ('开关/切换',     'mt_aurora_skills'),
    'pulse':   ('意识脉冲',     'mt_iceberg_consciousness_runs'),
    'audit':   ('审计/扫描',     'mt_rule_*'),
}


def _now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _now_epoch():
    return time.time()


def _get_conn():
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(conn):
    """确保管道自身表存在 (幂等)"""
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_pipeline_execution_log (
        exec_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pipeline_id TEXT NOT NULL,
        step TEXT NOT NULL,
        message TEXT,
        detail_json TEXT,
        duration_ms INTEGER,
        created_at TEXT DEFAULT (datetime('now')))""")
    conn.commit()


def _check_integrity(conn, risk: str) -> tuple[bool, str]:
    """PRE_CHECK: 查 mt_rule_integrity_scan.score (REAL 0-100)"""
    if risk == 'low':
        return True, 'low-risk: 跳过完整性扫描'
    try:
        row = conn.execute(
            "SELECT score, scan_type, status FROM mt_rule_integrity_scan "
            "ORDER BY scan_id DESC LIMIT 1").fetchone()
        if not row:
            return risk not in ('critical', 'high'), '无 integrity_scan 记录'
        cov = float(row['score']) if row['score'] is not None else 0
        threshold = {'critical': 100, 'high': 100, 'medium': 90, 'low': 0}[risk]
        if cov < threshold:
            return False, f'{risk} 要求 ≥{threshold}%, 当前 {cov}%'
        return True, f'integrity_scan OK: score={cov}%'
    except Exception as e:
        return risk not in ('critical', 'high'), f'integrity_scan 查询失败: {e}'


def _log(conn, pid: str, step: str, msg: str, detail=None, dur=0):
    try:
        conn.execute(
            "INSERT INTO mt_pipeline_execution_log "
            "(pipeline_id, step, message, detail_json, duration_ms) "
            "VALUES (?,?,?,?,?)",
            (pid, step, msg,
             json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
             dur))
        conn.commit()
    except Exception: pass


def _write_violation(conn, pid: str, action: str, risk: str, func_qn: str, err: str):
    """写 mt_iron_rule_violations (列名: viol_id TEXT, viol_rule, viol_stage...)"""
    try:
        viol_id = f'pipeline_fail_{uuid.uuid4().hex[:8]}'
        conn.execute(
            "INSERT INTO mt_iron_rule_violations "
            "(viol_id, viol_rule, viol_stage, viol_action, viol_payload, viol_handler, viol_blocked, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?)",
            (viol_id, 'MT_PIPELINE_MAINT', action, risk,
             json.dumps({'pipeline_id': pid, 'func': func_qn, 'error': err[:500]},
                        ensure_ascii=False),
             'maintenance_pipeline', _now_epoch(), _now_epoch()))
        conn.commit()
    except Exception: pass


def _write_alert(conn, pid: str, action: str, risk: str, func_qn: str, status: str):
    """写 mt_rule_violation_alert (列名: alert_id TEXT, alert_type, alert_payload TEXT REAL)"""
    try:
        alert_id = f'pipeline_alert_{uuid.uuid4().hex[:8]}'
        conn.execute(
            "INSERT INTO mt_rule_violation_alert "
            "(alert_id, viol_id, alert_type, alert_target, alert_status, alert_payload, severity, description, created_at, alert_sent_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (alert_id, pid, 'pipeline_maintenance', func_qn, status,
             json.dumps({'pipeline_id': pid, 'action': action, 'risk': risk,
                         'func': func_qn, 'status': status}, ensure_ascii=False),
             'HIGH' if status == 'failed' else 'INFO',
             f'管道 {action}@{risk} → {status}', _now_epoch(), _now_epoch()))
        conn.commit()
    except Exception: pass


def maintenance_pipeline(
    action: str = 'deploy',
    risk: str = 'medium',
    operator: str = 'andromeda',
    exempt_daemon: bool = False,
    require_sa: bool = False,
) -> Callable:
    """统一维护升级管道装饰器

    Args:
        action:     seed/deploy/upgrade/rollback/migrate/patch/evolve/toggle/pulse/audit
        risk:       low/medium/high/critical
        operator:   操作者 (andromeda/super_admin/daemon)
        exempt_daemon: True=daemon 循环豁免完整性扫描 (risk 强制降 low)
        require_sa: True=必须 SA VIKEY 二次确认 (hook 留给 Flask 层拦截)
    """
    if action not in _ACTION_MAP:
        raise ValueError(f"action 必须在 {list(_ACTION_MAP.keys())}")
    if risk not in _RISK_LEVELS:
        raise ValueError(f"risk 必须在 {list(_RISK_LEVELS)}")

    action_desc, target_table = _ACTION_MAP[action]

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            pid = f'pipeline_{uuid.uuid4().hex[:12]}'
            started = time.monotonic()
            conn = _get_conn()
            _ensure_tables(conn)

            # ── 1. PRE_CHECK ──
            eff_risk = 'low' if exempt_daemon else risk
            pre_ok, pre_msg = _check_integrity(conn, eff_risk)
            _log(conn, pid, 'PRE_CHECK', pre_msg,
                 detail={'risk_effective': eff_risk, 'exempt_daemon': exempt_daemon})
            if not pre_ok:
                _log(conn, pid, 'BLOCKED', f'fail-closed: {pre_msg}',
                     dur=int((time.monotonic()-started)*1000))
                _write_alert(conn, pid, action, risk, fn.__qualname__, 'blocked')
                conn.close()
                raise PermissionError(f"[PIPELINE BLOCKED] {fn.__qualname__}: {pre_msg}")

            # ── 2. CHANGELOG 预审 (changelog_id INTEGER, pipeline_id TEXT) ──
            cl_id = None
            try:
                cur = conn.execute(
                    "INSERT INTO mt_rule_changelog "
                    "(rule_id, change_type, pipeline_id, action, target_table, risk, "
                    "pre_check_passed, execution_status, approved_by_7step, created_at) "
                    "VALUES (?,?,?,?,?,?,1,'pending',0,datetime('now'))",
                    ('PIPELINE_MAINT', action, pid, action_desc, target_table, eff_risk))
                cl_id = cur.lastrowid
                _log(conn, pid, 'CHANGELOG', f'#{cl_id} 预审写入', detail={'changelog_id': cl_id})
                conn.commit()
            except Exception as e:
                _log(conn, pid, 'CHANGELOG_ERR', str(e))
                conn.commit()

            # ── 3. EXECUTE ──
            try:
                _log(conn, pid, 'EXECUTE', f'调用 {fn.__qualname__}',
                     detail={'args_cnt': len(args), 'kwargs': list(kwargs.keys())})
                result = fn(*args, **kwargs)
                dur_ms = int((time.monotonic() - started) * 1000)
                _log(conn, pid, 'EXECUTE_OK', '成功',
                     detail={'result_type': type(result).__name__}, dur=dur_ms)
                exec_status = 'success'
                exec_err = None
            except Exception as e:
                dur_ms = int((time.monotonic() - started) * 1000)
                _log(conn, pid, 'EXECUTE_FAIL', f'{type(e).__name__}: {str(e)[:200]}',
                     detail={'traceback': traceback.format_exc()[:600]}, dur=dur_ms)
                exec_status = 'failed'
                exec_err = f"{type(e).__name__}: {str(e)[:400]}"
                result = None

            # ── 4. POST_AUDIT (UPDATE changelog) ──
            if cl_id:
                conn.execute(
                    "UPDATE mt_rule_changelog SET "
                    "execution_status=?, execution_error=?, executed_at=datetime('now'), "
                    "approved_by_7step=? WHERE changelog_id=?",
                    (exec_status, exec_err, 1 if exec_status == 'success' else 0, cl_id))
                conn.commit()
            _log(conn, pid, 'POST_AUDIT', f'#{cl_id} 更新 status={exec_status}')

            # ── 5. VIOLATION + ALERT ──
            if exec_status == 'failed':
                _write_violation(conn, pid, action, risk, fn.__qualname__, exec_err or '')
                _log(conn, pid, 'VIOLATION', 'mt_iron_rule_violations 已写入')
            _write_alert(conn, pid, action, risk, fn.__qualname__, exec_status)

            conn.close()

            if exec_status == 'failed':
                raise RuntimeError(f"[PIPELINE FAIL] {fn.__qualname__}: {exec_err}")
            return result
        return wrapper
    return decorator


# ── 查询 API ──
def get_pipeline_status(pipeline_id: str) -> Dict:
    """查询单个管道执行状态"""
    conn = _get_conn()
    try:
        cl = conn.execute(
            "SELECT * FROM mt_rule_changelog WHERE pipeline_id=?", (pipeline_id,)).fetchone()
        logs = conn.execute(
            "SELECT * FROM mt_pipeline_execution_log WHERE pipeline_id=? ORDER BY exec_id",
            (pipeline_id,)).fetchall()
        return {
            'changelog': dict(cl) if cl else None,
            'logs': [dict(l) for l in logs],
        }
    finally: conn.close()


def list_recent_pipelines(limit: int = 20) -> list:
    """列出最近管道执行"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mt_rule_changelog WHERE pipeline_id IS NOT NULL "
            "ORDER BY changelog_id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally: conn.close()
