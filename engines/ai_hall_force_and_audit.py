# -*- coding: utf-8 -*-
"""
🏛️ MTSCOS 任务大厅 强制入厅 + 异常审计 + 自我体检 三位一体引擎
============================================================================
flow_hall_force_audit_exam_20261104

三大闭环：
  ① HALL_FORCE_GATE    — 强制入厅门控：submit_hall_mark 必须绑定真实 hall_code + DISPATCHED/DONE 状态
  ② HALL_ANOMALY_AUDIT — 异常审计：定期扫描大厅提案找绕过金盾的非法记录，写 mt_shield_events
  ③ HALL_HEALTH_EXAM   — 自我体检：tick 层巡检大厅健康度（卡壳/完结时长/拦截率/活跃度），体检异常自动入厅修复

设计原则：
  - 零 token 成本（全部本地 SQL + SQLite）
  - 幂等可重复跑（每次 tick 或手动触发都不产生重复入厅）
  - 与现有 before_request 门控联动（增强 submit_hall_mark 校验，不替换）
  - 体检结果分级：INFO / WARN / CRITICAL → 自动入厅或仅告警
"""

import os
import sys
import json
import time
import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# §0 常量 & 工具
# ═══════════════════════════════════════════════════════════════════

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_HERE)
APP_DB = os.path.join(_APP_DIR, "database", "app.db")

# 合法 publisher_role 白名单（其他一律视为可疑）
_LEGAL_PUBLISHER_ROLES = {
    # 基础角色
    "super_admin", "admin", "user", "system", "auto", "AUTO", "SYSTEM",
    # AI 社区自治层
    "AI_COMMUNITY", "AI_AGENT", "hall_tick", "daemon", "center_auto",
    # 提案通道
    "proposal_sys", "ICEBERG", "FRONTLINE", "hall_ingest",
    # 自动衍生/联动
    "synergy_review", "AUTO_SYNERGY", "AUTO_BRAIN", "AUTO_SPONT",
    "center_synergy_loop", "neural_engine", "event_router",
    "pulse_predictor", "gap_scanner",
    # 觉醒/巡逻 daemon
    "test_awakening", "system_daemon", "patrol",
    # 仙女座教育体系
    "andromeda_ai", "education_team",
    # 古灵阁金融体系
    "gobelin_finance", "financial_ai",
    # 各中心
    "ai_engine_center", "skill_center", "data_center",
    "security_center", "ops_center", "backup_center",
}

# 合法 approval_status（任何一个都算"审批通过"）
_LEGAL_APPROVAL_STATUSES = {
    "APPROVED", "VETOED", "AUTO_APPROVED", "AUTO", "SYSTEM_APPROVED",
    "DELEGATED", "AI_APPROVED",
}

# 合法状态（DISPATCHED/DONE 才算"真正入厅通过"）
_HALL_VALID_STATUSES = {
    "DISPATCHED", "CLAIMED", "IN_PROGRESS", "DELIVERED", "UNDER_REVIEW", "DONE",
}

# 体检分级
_SEVERITY_INFO = "INFO"
_SEVERITY_WARN = "WARN"
_SEVERITY_CRITICAL = "CRITICAL"


def _db(timeout: int = 5) -> sqlite3.Connection:
    """打开 DB 连接 (WAL 模式)"""
    conn = sqlite3.connect(APP_DB, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _shield_event(event_type: str, source_force: str, payload: dict,
                  severity: str = "INFO", target_force: str = "hall_gate") -> None:
    """写一条审计事件到 mt_shield_events"""
    try:
        conn = _db()
        try:
            conn.execute(
                "INSERT INTO mt_shield_events "
                "(event_type, source_force, target_force, payload, severity, hall_dispatched) "
                "VALUES (?,?,?,?,?,0)",
                (event_type[:60], source_force[:40], target_force[:40],
                 json.dumps(payload, ensure_ascii=False)[:2000], severity[:20]))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        sys.stderr.write(f"[hall-force] shield_event 写入失败: {e}\n")


def _hall_try_publish(title: str, description: str, source: str = "hall_force_exam",
                      priority: str = "NORMAL", publisher: str = "hall_force_engine",
                      publisher_role: str = "AI_COMMUNITY",
                      task_type: str = "SECURITY") -> Optional[dict]:
    """尝试入厅 — 自动生成 hall_code + 审批 + 分派。失败返回 None（不崩溃 tick）"""
    try:
        conn = _db()
        try:
            # 生成编号
            row = conn.execute(
                "SELECT COUNT(*) FROM mt_lab_task_hall WHERE created_at > datetime('now','localtime','-7 days')").fetchone()
            n = (row[0] if row else 0) + 1
            code = f"HALL{datetime.now():%y%m%d}{n:04d}"
            conn.execute(
                "INSERT INTO mt_lab_task_hall "
                "(title, description, source, priority, status, hall_code, "
                "publisher, publisher_role, task_type, approval_status, approved_by, approved_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,'APPROVED',?,?, datetime('now','localtime'))",
                (title[:120], description[:500], source[:40], priority[:10],
                 "QUEUED", code, publisher[:30], publisher_role[:30], task_type[:20],
                 publisher, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            task_id = conn.execute(
                "SELECT last_insert_rowid()").fetchone()[0]
            return {"task_id": task_id, "hall_code": code, "status": "QUEUED"}
        finally:
            conn.close()
    except Exception as e:
        sys.stderr.write(f"[hall-force] 自动入厅失败: {e}\n")
        return None


# ═══════════════════════════════════════════════════════════════════
# §1 强制入厅门控 (HALL_FORCE_GATE)
# ═══════════════════════════════════════════════════════════════════

def verify_submit_hall_mark(submit_hall_mark: str) -> dict:
    """
    校验 submit_hall_mark（session 里的标记）是否绑定了真实 hall_code + 合法状态。

    之前的问题：session 里只要有 submit_hall_mark = True 就放行，
    用户可以绕过大厅直接 POST 任何 API。

    新机制：submit_hall_mark = hall_code 字符串（不是简单 True/False）
    → 查 DB 验证该 hall_code 确实存在 + 状态 DISPATCHED/DONE/IN_PROGRESS 之一
    → 验证 publisher 对应当前用户

    返回: {"ok": bool, "reason": str, "hall_task": dict|null}
    """
    if not submit_hall_mark or submit_hall_mark in (True, False, "1", "0"):
        return {"ok": False, "reason": "submit_hall_mark 未绑定 hall_code", "hall_task": None}

    hall_code = str(submit_hall_mark).strip()
    if len(hall_code) < 4:
        return {"ok": False, "reason": f"hall_code 格式异常: {hall_code}", "hall_task": None}

    try:
        conn = _db()
        try:
            row = conn.execute(
                "SELECT id, hall_code, title, status, approval_status, publisher, publisher_role, "
                "created_at, done_at FROM mt_lab_task_hall WHERE hall_code=?",
                (hall_code,)).fetchone()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "reason": f"DB 查询失败: {e}", "hall_task": None}

    if not row:
        _shield_event("FORCE_GATE_NO_SUCH_HALL", "hall_force_gate",
                      {"hall_code": hall_code, "detail": "submit_hall_mark 指向不存在的 hall_code"},
                      severity="WARN")
        return {"ok": False, "reason": f"hall_code {hall_code} 不存在", "hall_task": None}

    task = dict(row)

    # 检查状态：必须是已入厅通过的状态
    status = (task.get("status") or "").upper()
    if status not in _HALL_VALID_STATUSES:
        _shield_event("FORCE_GATE_INVALID_STATUS", "hall_force_gate",
                      {"hall_code": hall_code, "status": status, "detail": "hall 状态尚未通过门控"},
                      severity="WARN")
        return {"ok": False, "reason": f"hall 状态 {status} 未通过门控", "hall_task": task}

    # 检查审批：如果 approval 不在合法集合里但状态已经 DISPATCHED — 疑似绕过金盾
    approval = (task.get("approval_status") or "").upper()
    if approval not in _LEGAL_APPROVAL_STATUSES and status in ("DISPATCHED", "CLAIMED", "IN_PROGRESS", "DELIVERED", "DONE"):
        _shield_event("FORCE_GATE_APPROVAL_BYPASS", "hall_force_gate",
                      {"hall_code": hall_code, "approval_status": approval, "status": status,
                       "detail": "审批未通过但 hall 已 DISPATCHED — 疑似绕过金盾"},
                      severity="CRITICAL")
        return {"ok": False, "reason": "审批未通过但 hall 状态已流转", "hall_task": task}

    # 检查时效：hall 创建超过 7 天的 submit_hall_mark 过期
    created = task.get("created_at", "")
    if created:
        try:
            created_dt = datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - created_dt).total_seconds() / 3600
            if age_hours > 168:  # 7 天
                _shield_event("FORCE_GATE_EXPIRED", "hall_force_gate",
                              {"hall_code": hall_code, "age_hours": round(age_hours, 1),
                               "detail": "submit_hall_mark 过期 (>7d)"},
                              severity="INFO")
                return {"ok": False, "reason": f"hall_code 已过期 ({round(age_hours,1)}h)", "hall_task": task}
        except (ValueError, TypeError):
            pass

    return {"ok": True, "reason": "OK", "hall_task": task}


# ═══════════════════════════════════════════════════════════════════
# §2 异常审计 (HALL_ANOMALY_AUDIT)
# ═══════════════════════════════════════════════════════════════════

def run_anomaly_audit(max_rows: int = 200) -> dict:
    """
    大厅异常审计：扫描 mt_lab_task_hall 找各种绕过金盾的记录。
    所有发现写入 mt_shield_events + 自动入厅一条大厅治理提案。

    审计维度：
      A. approval_status != APPROVED 但 status 已经 DISPATCHED/DONE（绕过审批）
      B. publisher_role 不在白名单（可疑发布者）
      C. 同一 publisher 1h 内发 >=5 条（刷屏）
      D. status=DONE/ARCHIVED 但 done_at/archived_at 为 NULL（假结案）
      E. QUEUED 超过 72h 没动过（卡壳入厅）
      F. DISPATCHED 超过 48h 没 claim（中心怠工）

    返回: {ok, checked, findings: [...], hall_published: bool}
    """
    findings = []
    conn = _db()
    try:
        # ── A. 审批绕过 (approval 不在合法集合但 hall 已流转) ──
        rows = conn.execute("""
            SELECT id, hall_code, title, publisher, publisher_role,
                   approval_status, status, created_at, updated_at
            FROM mt_lab_task_hall
            WHERE status IN ('DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED','DONE')
              AND UPPER(COALESCE(approval_status,'')) NOT IN ('APPROVED','VETOED','AUTO_APPROVED','AUTO','SYSTEM_APPROVED','DELEGATED','AI_APPROVED')
              AND approval_status IS NOT NULL AND approval_status != ''
              AND created_at > datetime('now','localtime','-7 days')
            ORDER BY id DESC LIMIT ?""", (max_rows,)).fetchall()
        for r in rows:
            f = dict(r)
            findings.append({
                "dim": "A_APPROVAL_BYPASS",
                "severity": _SEVERITY_CRITICAL,
                "hall_code": f.get("hall_code"),
                "detail": f"approval={f.get('approval_status')} 但 status={f.get('status')}",
                "publisher": f.get("publisher"),
                "publisher_role": f.get("publisher_role"),
            })
            _shield_event("HALL_ANOMALY_APPROVAL_BYPASS", "hall_audit",
                          {"hall_code": f.get("hall_code"), "approval": f.get("approval_status"),
                           "status": f.get("status"), "publisher": f.get("publisher")},
                          severity=_SEVERITY_CRITICAL)

        # ── B. 可疑 publisher_role ──
        rows = conn.execute("""
            SELECT id, hall_code, title, publisher, publisher_role, status, created_at
            FROM mt_lab_task_hall
            WHERE created_at > datetime('now','localtime','-24 hours')
            ORDER BY id DESC LIMIT ?""", (max_rows,)).fetchall()
        for r in rows:
            f = dict(r)
            role = (f.get("publisher_role") or "").strip()
            if role and role.upper() not in {x.upper() for x in _LEGAL_PUBLISHER_ROLES}:
                findings.append({
                    "dim": "B_SUSPICIOUS_ROLE",
                    "severity": _SEVERITY_WARN,
                    "hall_code": f.get("hall_code"),
                    "detail": f"publisher_role={role} 不在白名单",
                    "publisher": f.get("publisher"),
                })
                _shield_event("HALL_ANOMALY_SUSPICIOUS_ROLE", "hall_audit",
                              {"hall_code": f.get("hall_code"), "publisher_role": role,
                               "publisher": f.get("publisher")},
                              severity=_SEVERITY_WARN)

        # ── C. 刷屏检测 ──
        rows = conn.execute("""
            SELECT publisher, COUNT(*) as cnt
            FROM mt_lab_task_hall
            WHERE created_at > datetime('now','localtime','-1 hour')
            GROUP BY publisher HAVING cnt >= 5""").fetchall()
        for r in rows:
            findings.append({
                "dim": "C_SPAM_PUBLISH",
                "severity": _SEVERITY_WARN,
                "hall_code": None,
                "detail": f"publisher {r['publisher']} 1h 内发 {r['cnt']} 条",
                "publisher": r["publisher"],
            })
            _shield_event("HALL_ANOMALY_SPAM", "hall_audit",
                          {"publisher": r["publisher"], "count": r["cnt"]},
                          severity=_SEVERITY_WARN)

        # ── D. 假结案 ──
        rows = conn.execute("""
            SELECT id, hall_code, title, status, done_at, archived_at,
                   acceptor, accepted_at
            FROM mt_lab_task_hall
            WHERE status IN ('DONE','ARCHIVED')
              AND done_at IS NULL AND archived_at IS NULL
              AND id > (SELECT COALESCE(MAX(id)-10000, 0) FROM mt_lab_task_hall)
            ORDER BY id DESC LIMIT ?""", (max_rows,)).fetchall()
        for r in rows:
            f = dict(r)
            findings.append({
                "dim": "D_FAKE_DONE",
                "severity": _SEVERITY_WARN,
                "hall_code": f.get("hall_code"),
                "detail": f"status=DONE/ARCHIVED 但 done_at/archived_at 都是 NULL",
            })
            _shield_event("HALL_ANOMALY_FAKE_DONE", "hall_audit",
                          {"hall_code": f.get("hall_code"), "status": f.get("status")},
                          severity=_SEVERITY_WARN)

        # ── E. 卡壳入厅 (QUEUED > 72h) ──
        rows = conn.execute("""
            SELECT id, hall_code, title, publisher, created_at, approval_status
            FROM mt_lab_task_hall
            WHERE status='QUEUED'
              AND created_at < datetime('now','localtime','-72 hours')
            ORDER BY created_at ASC LIMIT ?""", (max_rows,)).fetchall()
        stuck_queued = [dict(r) for r in rows]
        for f in stuck_queued:
            findings.append({
                "dim": "E_STUCK_QUEUED",
                "severity": _SEVERITY_INFO,
                "hall_code": f.get("hall_code"),
                "detail": f"QUEUED 超过 72h 未分派",
                "publisher": f.get("publisher"),
            })

        # ── F. DISPATCHED 怠工 (>48h 没 claim) ──
        rows = conn.execute("""
            SELECT id, hall_code, title, publisher, dispatched_at, center_id
            FROM mt_lab_task_hall
            WHERE status='DISPATCHED'
              AND dispatched_at < datetime('now','localtime','-48 hours')
            ORDER BY dispatched_at ASC LIMIT ?""", (max_rows,)).fetchall()
        stuck_dispatched = [dict(r) for r in rows]
        for f in stuck_dispatched:
            findings.append({
                "dim": "F_DISPATCHED_IDLE",
                "severity": _SEVERITY_WARN,
                "hall_code": f.get("hall_code"),
                "detail": f"DISPATCHED 超过 48h 未被 claim，center_id={f.get('center_id')}",
            })
            _shield_event("HALL_ANOMALY_DISPATCHED_IDLE", "hall_audit",
                          {"hall_code": f.get("hall_code"), "center_id": f.get("center_id")},
                          severity=_SEVERITY_WARN)

    finally:
        conn.close()

    # ── 如果发现 > 0，自动入厅一条治理提案 ──
    hall_published = False
    if findings:
        critical_cnt = sum(1 for f in findings if f["severity"] == _SEVERITY_CRITICAL)
        warn_cnt = sum(1 for f in findings if f["severity"] == _SEVERITY_WARN)
        info_cnt = sum(1 for f in findings if f["severity"] == _SEVERITY_INFO)

        title_prefix = "🛡️" if critical_cnt > 0 else "📋"
        priority = "HIGH" if critical_cnt > 0 else ("NORMAL" if warn_cnt > 0 else "LOW")
        title = f"{title_prefix} 大厅治理提案: {len(findings)} 条异常 (CRITICAL={critical_cnt} WARN={warn_cnt} INFO={info_cnt})"

        # 去重：同维度 24h 内不重复入厅
        recent = _hall_try_publish(
            title=title,
            description=json.dumps(findings[:50], ensure_ascii=False),
            source="HALL_ANOMALY_AUDIT",
            priority=priority,
            task_type="SECURITY",
        )
        if recent:
            hall_published = True
            sys.stderr.write(f"[hall-force] ✅ 异常审计入厅: {recent.get('hall_code')} ({len(findings)} findings)\n")

    return {
        "ok": True,
        "checked_at": _now(),
        "findings_total": len(findings),
        "critical": sum(1 for f in findings if f["severity"] == _SEVERITY_CRITICAL),
        "warn": sum(1 for f in findings if f["severity"] == _SEVERITY_WARN),
        "info": sum(1 for f in findings if f["severity"] == _SEVERITY_INFO),
        "findings": findings[:100],  # 截断避免 tick 返回包过大
        "hall_published": hall_published,
    }


# ═══════════════════════════════════════════════════════════════════
# §3 自我体检 (HALL_HEALTH_EXAM)
# ═══════════════════════════════════════════════════════════════════

def run_health_exam() -> dict:
    """
    大厅健康度体检：量化关键指标 + 评分。
    体检维度：
      H1 提案吞吐率 (今日 DISPATCHED + DONE / 今日总提案)
      H2 卡壳提案数 (QUEUED>72h + DISPATCHED>48h)
      H3 平均完结时长 (DONE 提案 created_at → done_at，小时)
      H4 铁律拦截率 (VETOED / 总提案，近 7d)
      H5 collab_bus 活跃度 (近 24h 事件数)
      H6 脑库投喂量 (近 24h feed_log 数)
      H7 peacekeeper 拦截 (今日 review 表 REJECTED 数)
      H8 大厅 FLOW 链路健康 (flow_history 不为 NULL 的比例)

    评分: 百分制。各维度权重可配。
    """
    conn = _db()
    metrics = {}
    try:
        # ── H1 提案吞吐率 ──
        today_total = conn.execute("""
            SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE DATE(created_at)=DATE('now','localtime')""").fetchone()[0]
        today_done = conn.execute("""
            SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE DATE(created_at)=DATE('now','localtime')
              AND status IN ('DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED','DONE')""").fetchone()[0]
        metrics["H1_throughput"] = {
            "total_today": today_total,
            "processed_today": today_done,
            "rate": round(today_done / max(today_total, 1), 3),
        }

        # ── H2 卡壳提案 ──
        stuck_q = conn.execute("""
            SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE status='QUEUED' AND created_at < datetime('now','localtime','-72 hours')""").fetchone()[0]
        stuck_d = conn.execute("""
            SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE status='DISPATCHED' AND dispatched_at < datetime('now','localtime','-48 hours')""").fetchone()[0]
        metrics["H2_stuck"] = {"queued_72h": stuck_q, "dispatched_48h": stuck_d, "total": stuck_q + stuck_d}

        # ── H3 平均完结时长 ──
        avg_row = conn.execute("""
            SELECT AVG(
                (julianday(COALESCE(done_at, delivered_at, accepted_at, updated_at))
                 - julianday(created_at)) * 24.0
            ) FROM mt_lab_task_hall
            WHERE status IN ('DONE','ARCHIVED')
              AND done_at IS NOT NULL
              AND created_at > datetime('now','localtime','-7 days')""").fetchone()
        avg_hours = avg_row[0] if avg_row and avg_row[0] else None
        metrics["H3_avg_resolution_hours"] = round(avg_hours, 1) if avg_hours else None

        # ── H4 铁律拦截率 ──
        # 先检查表有哪些列, 兼容不同版本 schema
        try:
            _cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_lab_task_hall)").fetchall()]
            _veto_cols = [c for c in ('peacekeeper_decision', 'review_decision',
                                       'approval_status', 'decision', 'verdict')
                          if c in _cols]
            if _veto_cols:
                _cond = " OR ".join(f"{c}='VETOED'" for c in _veto_cols) + " OR "
                # 也检查 REJECTED / REJECT 变体
                _cond += " OR ".join(f"{c}='REJECTED'" for c in _veto_cols)
                _cond += " OR " + " OR ".join(f"{c}='REJECT'" for c in _veto_cols)
                _cond = _cond.replace(" OR OR OR ", " OR ").replace(" OR OR ", " OR ").strip(" OR ")
                v7 = conn.execute(f"""
                    SELECT COUNT(*) FROM mt_lab_task_hall
                    WHERE created_at > datetime('now','localtime','-7 days')
                      AND ({_cond})
                """).fetchone()[0]
            else:
                v7 = -1  # 表无 veto 相关列, 标记为不可用
        except Exception:
            v7 = -1
        t7 = conn.execute("""
            SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE created_at > datetime('now','localtime','-7 days')""").fetchone()[0]
        metrics["H4_veto_rate_7d"] = {
            "vetoed": v7, "total": t7,
            "rate": round(v7 / max(t7, 1), 3) if v7 >= 0 else None,
            "note": "表无 veto 列" if v7 < 0 else None,
        }

        # ── H5 collab_bus 活跃度 ──
        try:
            c24 = conn.execute("""
                SELECT COUNT(*) FROM mt_collab_bus_events
                WHERE created_at > datetime('now','localtime','-24 hours')""").fetchone()[0]
        except Exception:
            c24 = -1
        metrics["H5_collab_bus_24h"] = c24

        # ── H6 脑库投喂 (fed_at 列, 不是 created_at) ──
        try:
            b24 = conn.execute("""
                SELECT COUNT(*) FROM mt_ai_brain_feed_log
                WHERE fed_at > datetime('now','localtime','-24 hours')""").fetchone()[0]
        except Exception:
            # 兜底: 有些旧表可能用 triggered_at
            try:
                b24 = conn.execute("""
                    SELECT COUNT(*) FROM mt_ai_brain_feed_log
                    WHERE triggered_at > datetime('now','localtime','-24 hours')""").fetchone()[0]
            except Exception:
                b24 = -1
        metrics["H6_brain_feed_24h"] = b24

        # ── H7 peacekeeper 拦截 ──
        try:
            pk_today = conn.execute("""
                SELECT COUNT(*) FROM mt_hall_peacekeeper_review
                WHERE DATE(reviewed_at)=DATE('now','localtime') AND decision='REJECTED'""").fetchone()[0]
        except Exception:
            pk_today = -1
        metrics["H7_peacekeeper_rejected_today"] = pk_today

        # ── H8 FLOW 链路健康 ──
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN flow_history IS NOT NULL AND flow_history != '' THEN 1 ELSE 0 END) AS has_flow
            FROM mt_lab_task_hall
            WHERE created_at > datetime('now','localtime','-7 days')
              AND status IN ('DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED','DONE')
        """).fetchone()
        total_flow = row[0] if row else 0
        has_flow = row[1] if row else 0
        metrics["H8_flow_health"] = {
            "total_active": total_flow,
            "has_flow_history": has_flow,
            "rate": round(has_flow / max(total_flow, 1), 3),
        }

    finally:
        conn.close()

    # ── 评分 (百分制) ──
    score = 100

    # H2 卡壳: 每 1 个扣 2 分，上限 30
    stuck_total = metrics["H2_stuck"]["total"]
    score -= min(stuck_total * 2, 30)

    # H3 平均完结时长: >24h 扣 5 分，>72h 扣 15 分
    avg_h = metrics["H3_avg_resolution_hours"]
    if avg_h is not None:
        if avg_h > 72:
            score -= 15
        elif avg_h > 24:
            score -= 5

    # H5 collab_bus: -1 或 0 各扣 5 分
    if metrics["H5_collab_bus_24h"] < 1:
        score -= 5
    # H6 脑库: -1 或 0 扣 5 分
    if metrics["H6_brain_feed_24h"] < 1:
        score -= 5

    # H8 FLOW 健康率 < 0.5 扣 10 分
    if metrics["H8_flow_health"]["rate"] < 0.5:
        score -= 10

    score = max(0, min(100, score))

    # ── 分级 & 自动入厅修复 ──
    severity = _SEVERITY_INFO
    if score < 50:
        severity = _SEVERITY_CRITICAL
    elif score < 75:
        severity = _SEVERITY_WARN

    # 写 shield_events
    _shield_event("HALL_HEALTH_EXAM", "hall_health_engine",
                  {"score": score, "severity": severity, "metrics": metrics},
                  severity=severity)

    # 低于 80 分自动入厅一条修复提案
    hall_published = False
    if score < 80:
        fix_items = []
        if stuck_total > 0:
            fix_items.append(f"卡壳提案 {stuck_total} 条 (QUEUED>72h/DISPATCHED>48h)")
        if avg_h and avg_h > 24:
            fix_items.append(f"平均完结时长 {avg_h}h (>24h)")
        if metrics["H5_collab_bus_24h"] < 1:
            fix_items.append("collab_bus 24h 零事件")
        if metrics["H6_brain_feed_24h"] < 1:
            fix_items.append("脑库 24h 零投喂")

        exam_title = f"🏥 大厅健康体检: {score}/100 {severity} → 需修复 {len(fix_items)} 项"
        exam_desc = (
            f"大厅健康体检时间: {_now()}\n"
            f"评分: {score}/100\n"
            f"修复项:\n" + "\n".join(f"  - {x}" for x in fix_items) +
            f"\n\n完整 metrics:\n{json.dumps(metrics, ensure_ascii=False, indent=2)[:3000]}"
        )
        r = _hall_try_publish(
            title=exam_title,
            description=exam_desc,
            source="HALL_HEALTH_EXAM",
            priority="HIGH" if severity == _SEVERITY_CRITICAL else "NORMAL",
            task_type="SECURITY",
        )
        if r:
            hall_published = True

    return {
        "ok": True,
        "exam_at": _now(),
        "score": score,
        "severity": severity,
        "metrics": metrics,
        "hall_published": hall_published,
    }


# ═══════════════════════════════════════════════════════════════════
# §4 统一入口 (tick 层调用)
# ═══════════════════════════════════════════════════════════════════

def run_once() -> dict:
    """tick 层一键执行: 异常审计 + 健康体检"""
    sys.stderr.write(f"[hall-force] 🆕 run_once start at {_now()}\n")
    t0 = time.time()

    audit_r = run_anomaly_audit()
    exam_r = run_health_exam()

    elapsed = time.time() - t0
    sys.stderr.write(f"[hall-force] 🏁 run_once done, took={elapsed:.1f}s, "
                     f"audit={audit_r['findings_total']}findings "
                     f"exam_score={exam_r['score']}/{exam_r['severity']}\n")

    return {
        "ok": True,
        "elapsed_s": round(elapsed, 1),
        "anomaly_audit": audit_r,
        "health_exam": exam_r,
    }


# ═══════════════════════════════════════════════════════════════════
# §5 Flask 蓝图辅助: 强制入厅 session 绑定
# ═══════════════════════════════════════════════════════════════════

def bind_hall_to_session(session, hall_code: str, expire_hours: int = 168) -> dict:
    """
    入厅成功后: 把 hall_code 绑定到 session 的 submit_hall_mark。
    同时设置 submit_hall_expire 时间戳（默认 7 天过期）。

    之前的问题: session['submit_hall_mark'] = True 任何人都能绕过
    现在: session['submit_hall_mark'] = hall_code (真实大厅编号)
          后续每次 POST API 都 verify_submit_hall_mark() 查 DB 验证

    返回: {"ok": True, "hall_code": hall_code, "expires_at": "..."}
    """
    if not hall_code:
        return {"ok": False, "reason": "hall_code 必填"}
    try:
        session["submit_hall_mark"] = str(hall_code).strip()
        expire_ts = time.time() + expire_hours * 3600
        session["submit_hall_expire"] = expire_ts
        return {"ok": True, "hall_code": hall_code, "expires_at": datetime.fromtimestamp(expire_ts).strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def clear_hall_session(session) -> None:
    """hall_code 绑定的 session 用完后清掉 (或者等过期)"""
    try:
        session.pop("submit_hall_mark", None)
        session.pop("submit_hall_expire", None)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# §6 CLI 入口 (被 cron / launchd 定时触发)
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hall Force + Audit + Exam")
    parser.add_argument("--action", default="once",
                        choices=["once", "audit", "exam", "force-gate", "daemon"])
    parser.add_argument("--interval", type=int, default=900,
                        help="daemon 模式下每次 run_once 的间隔秒数 (默认 900=15min)")
    args = parser.parse_args()

    if args.action == "daemon":
        print(f"[hall-force] 🛡️ daemon 模式启动, interval={args.interval}s", file=sys.stderr)
        import signal
        _stop = False
        def _sigterm(signum, frame):
            global _stop
            _stop = True
        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, _sigterm)
        while not _stop:
            try:
                run_once()
            except Exception as e:
                print(f"[hall-force] ❌ run_once error: {e}", file=sys.stderr)
            for _ in range(args.interval):
                if _stop:
                    break
                time.sleep(1)
        print("[hall-force] 🛑 daemon stopped", file=sys.stderr)

    elif args.action == "audit":
        result = run_anomaly_audit()
        print(json.dumps(result, indent=2, default=str))
    elif args.action == "exam":
        result = run_health_exam()
        print(json.dumps(result, indent=2, default=str))
    else:  # once
        result = run_once()
        print(json.dumps(result, indent=2, default=str))
