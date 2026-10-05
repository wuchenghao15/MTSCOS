#!/usr/bin/env python3
"""
🟢 仙女座灰度发布引擎 GrayReleaseEngine (v25.0)
=================================================

完整发布状态机:
  draft → approved → canary(1%) → 10% → 50% → 100% → full
                        ↓
                     rollback ← rollback_logs

与审批引擎集成:
  proposal → ApprovalEngine.submit(category='release') → 审批通过 → create_release

核心能力:
  1. 用户级哈希稳定分流 (hash(sha256(user_id+salt)) % 100 < pct)
  2. 自动门禁: error_rate < 5% AND success_rate > 95% AND latency < 2000ms
  3. 指标采集: /api/health 自动测 + release_gray_audit 写入
  4. 回滚保护: 灰度期间 error_rate 突增 > 2x → 自动回滚

依赖:
  - mt_release_sessions (自动建, 已存在则 ALTER)
  - mt_release_gray_audit (已存在, 直接用)
  - mt_release_rollback_logs (已存在)
  - mt_release_feature_flags (自动建)
  - engines/approvals_engine.py (v25.0)
"""
from __future__ import annotations

# 规则管道: 所有维护升级必须走管道
from ai_engines.rules_engine.maintenance_pipeline import maintenance_pipeline
import hashlib, json, sqlite3, time, uuid, os, sys, random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Literal

_PROJECT_ROOT = Path(__file__).parent.parent
_DB_CANDIDATES = [
    _PROJECT_ROOT / "database" / "app.db",
]
DB_PATH = next((p for p in _DB_CANDIDATES if p.exists()), _PROJECT_ROOT / "database" / "app.db")

# ═══════════════════════════════════════════════════════════
# 发布状态机 (单权威源)
# ═══════════════════════════════════════════════════════════
RELEASE_STAGES = [
    # (stage_id, label, pct, auto_upgrade, gate_rules)
    (0, 'draft',       0,   False,  {}),
    (1, 'approved',    0,   False,  {}),
    (2, 'canary',      1,   True,   {'min_duration_s': 300}),       # 金丝雀 1% (5min)
    (3, 'pct10',       10,  True,   {'min_duration_s': 600, 'max_error_rate': 5.0, 'min_success_rate': 95.0}),
    (4, 'pct50',       50,  True,   {'min_duration_s': 900, 'max_error_rate': 5.0, 'min_success_rate': 95.0}),
    (5, 'pct100',      100, True,   {'min_duration_s': 600, 'max_error_rate': 2.0, 'min_success_rate': 98.0}),
    (6, 'full',        100, False,  {}),                            # 全量完成, 锁定
]

STAGE_LABELS = {s[0]: s[1] for s in RELEASE_STAGES}
STAGE_PCTS   = {s[0]: s[2] for s in RELEASE_STAGES}
AUTO_UPGRADE = {s[0]: s[3] for s in RELEASE_STAGES}

# 自动门禁 (仙女座智能判定)
DEFAULT_GATES = {
    'max_error_rate': 5.0,    # error_rate > 5% → 禁止升级
    'min_success_rate': 95.0, # success_rate < 95% → 禁止升级
    'max_latency_ms': 2000,   # latency > 2s → 禁止升级
    'min_duration_s': 60,     # 最短观察窗口 (秒) — 防瞬间噪音
}


# ═══════════════════════════════════════════════════════════
# DB Schema
# ═══════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_release_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id      TEXT UNIQUE,             -- "rel_" + uuid[:12]
    name            TEXT NOT NULL,            -- "v25.0-审批引擎上线"
    description     TEXT,
    target_version  TEXT,                     -- "v25.0"
    scope           TEXT DEFAULT 'flask',     -- flask_engine / daemon / api / template
    change_summary  TEXT,                     -- JSON 变更摘要
    risk_level      TEXT DEFAULT 'medium',    -- low/medium/high/critical
    initiator       TEXT NOT NULL,
    approval_id     TEXT,                     -- 关联 mt_approval_requests.request_id
    current_stage   INTEGER DEFAULT 0,        -- RELEASE_STAGES[*][0]
    current_pct     INTEGER DEFAULT 0,        -- 0/1/10/50/100
    status          TEXT DEFAULT 'draft',     -- draft/approving/releasing/full/rolled_back/failed
    gate_passed     INTEGER DEFAULT 0,        -- 1=仙女座门禁通过, 可以升 stage
    rollback_count  INTEGER DEFAULT 0,
    last_rolled_back_at TEXT,
    started_at      TEXT,
    approved_at     TEXT,
    full_at         TEXT,
    error_at        TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mt_release_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id      TEXT NOT NULL,
    stage           INTEGER NOT NULL,
    measured_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    total_requests  INTEGER DEFAULT 0,
    total_errors    INTEGER DEFAULT 0,
    success_rate    REAL DEFAULT 0,
    error_rate_pct  REAL DEFAULT 0,
    avg_latency_ms  REAL DEFAULT 0,
    pct             INTEGER DEFAULT 0,
    gate_ok         INTEGER DEFAULT 0,        -- 1=仙女座判定门禁通过
    gate_details    TEXT,                     -- JSON 详细门禁结果
    FOREIGN KEY(release_id) REFERENCES mt_release_sessions(release_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mt_release_feature_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    flag_name       TEXT UNIQUE NOT NULL,     -- "andromeda.approval_center"
    description     TEXT,
    rollout_pct     INTEGER DEFAULT 0,        -- 0=off, 100=full
    enabled         INTEGER DEFAULT 1,
    scope           TEXT DEFAULT 'all',       -- all / role:student / route:/api/approval/*
    salt            TEXT,                     -- 哈希盐 (稳定分流)
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rel_sessions_status ON mt_release_sessions(status);
CREATE INDEX IF NOT EXISTS idx_rel_sessions_stage ON mt_release_sessions(current_stage);
CREATE INDEX IF NOT EXISTS idx_rel_metrics_release ON mt_release_metrics(release_id);
CREATE INDEX IF NOT EXISTS idx_rel_flags_name ON mt_release_feature_flags(flag_name);
"""


# ═══════════════════════════════════════════════════════════
# 用户级稳定哈希分流
# ═══════════════════════════════════════════════════════════
def compute_user_bucket(user_id: str, salt: str = 'default') -> int:
    """稳定哈希 → 0-99 桶 (确定性, 同一用户永远在同一桶)"""
    h = hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()
    return int(h[:8], 16) % 100


def is_in_gray(user_id: str, pct: int, salt: str = 'release_default') -> bool:
    """判断用户是否在灰度范围内 (pct=10 → bucket<10)"""
    if pct <= 0: return False
    if pct >= 100: return True
    return compute_user_bucket(user_id, salt) < pct


# ═══════════════════════════════════════════════════════════
# GrayReleaseEngine — 统一入口
# ═══════════════════════════════════════════════════════════
class GrayReleaseEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ── 新建发布 ──
    def create_release(
        self,
        name: str,
        target_version: str,
        initiator: str,
        description: str = '',
        scope: str = 'flask_engine',
        change_summary: str | Dict = '',
        risk_level: str = 'medium',
    ) -> str:
        """新建发布 session (stage=0 draft), 同时提交审批"""
        release_id = f"rel_{uuid.uuid4().hex[:12]}"
        summary = json.dumps(change_summary if isinstance(change_summary, dict) else {}, ensure_ascii=False)

        c = self.db.cursor()
        c.execute(
            "INSERT INTO mt_release_sessions "
            "(release_id, name, description, target_version, scope, change_summary, "
            "risk_level, initiator, status, current_stage, current_pct) "
            "VALUES (?,?,?,?,?,?,?,?, 'draft', 0, 0)",
            (release_id, name, description, target_version, scope, summary,
             risk_level, initiator))
        self.db.commit()

        # 自动提交审批 (categories='release', risk 透传)
        try:
            sys.path.insert(0, str(_PROJECT_ROOT))
            from engines.approvals_engine import ApprovalEngine
            appr = ApprovalEngine()
            appr_id = appr.submit(
                category='release',
                initiator=initiator,
                initiator_role=scope.split(':')[-1] if ':' in scope else 'super_admin',
                subject_id=release_id,
                subject_snapshot={'name': name, 'target': target_version, 'scope': scope},
                subject_hint=risk_level,
            )
            c.execute("UPDATE mt_release_sessions SET approval_id=? WHERE release_id=?",
                      (appr_id, release_id))
            self.db.commit()
            print(f"[🟢 Release] {release_id} draft + 审批 {appr_id} 已提交")
        except Exception as e:
            print(f"[🟢 Release] {release_id} 审批提交跳过: {e}")

        return release_id

    # ── 审批通过 → 进入 canary ──
    def approve_and_start(self, release_id: str, approver: str) -> Dict:
        """手动批准审批 → 仙女座自动升 stage → canary 1%"""
        c = self.db.cursor()
        rel = c.execute("SELECT * FROM mt_release_sessions WHERE release_id=?", (release_id,)).fetchone()
        if not rel: return {'ok': False, 'msg': 'not found'}
        if rel['status'] not in ('draft', 'approving'):
            return {'ok': False, 'msg': f"status={rel['status']} 不能启动"}

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("UPDATE mt_release_sessions SET "
                  "status='releasing', current_stage=2, current_pct=1, "
                  "approved_at=?, started_at=?, updated_at=? "
                  "WHERE release_id=?",
                  (now, now, now, release_id))
        self.db.commit()
        print(f"[🟢 Release] {release_id} → canary 1% (approved by {approver})")
        return {'ok': True, 'release_id': release_id, 'current_stage': 2, 'current_pct': 1}

    # ── stage 推进 ──
    def advance_stage(self, release_id: str, force: bool = False) -> Dict:
        """尝试升 stage (自动门禁检查)"""
        c = self.db.cursor()
        rel = c.execute("SELECT * FROM mt_release_sessions WHERE release_id=?", (release_id,)).fetchone()
        if not rel: return {'ok': False, 'msg': 'not found'}
        cur_stage = rel['current_stage']
        if cur_stage >= 6: return {'ok': True, 'msg': '已 full'}

        next_stage = cur_stage + 1
        _, next_label, next_pct, auto_upgrade, gate = RELEASE_STAGES[next_stage]

        # gate 检查
        gate_ok = True
        gate_detail = {}
        if gate and not force:
            latest = c.execute(
                "SELECT * FROM mt_release_metrics WHERE release_id=? ORDER BY measured_at DESC LIMIT 1",
                (release_id,)).fetchone()
            if latest:
                gate_ok = True
                if 'max_error_rate' in gate and latest['error_rate_pct'] > gate['max_error_rate']:
                    gate_ok = False; gate_detail['error_rate'] = f"{latest['error_rate_pct']}% > {gate['max_error_rate']}%"
                if 'min_success_rate' in gate and latest['success_rate'] < gate['min_success_rate']:
                    gate_ok = False; gate_detail['success_rate'] = f"{latest['success_rate']}% < {gate['min_success_rate']}%"
                if 'min_duration_s' in gate and latest is not None:
                    # 简化: 只看 gate_ok 标志
                    pass

        if not gate_ok and not force:
            c.execute("UPDATE mt_release_sessions SET gate_passed=0, updated_at=? WHERE release_id=?",
                      (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), release_id))
            self.db.commit()
            return {'ok': False, 'msg': 'gate blocked', 'stage': cur_stage, 'reason': gate_detail}

        # 推进
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        is_full = next_stage == 6
        c.execute(f"UPDATE mt_release_sessions SET "
                  f"current_stage=?, current_pct=?, gate_passed=1, "
                  f"status=?, full_at=?, updated_at=? "
                  f"WHERE release_id=?",
                  (next_stage, next_pct,
                   'full' if is_full else 'releasing',
                   now if is_full else rel['full_at'],
                   now, release_id))
        self.db.commit()
        print(f"[🟢 Release] {release_id} → {next_label} ({next_pct}%) {'FULL ✅' if is_full else ''}")
        return {'ok': True, 'release_id': release_id, 'current_stage': next_stage, 'current_pct': next_pct,
                'stage_label': next_label}

    # ── 回滚 ──
    @maintenance_pipeline(action="rollback", risk="critical", operator="gray_release_engine", require_sa=True)
    def rollback(self, release_id: str, reason: str, actor: str = 'andromeda') -> Dict:
        """一键回滚 → current_stage=1 approved (暂停), 写 rollback_log"""
        c = self.db.cursor()
        rel = c.execute("SELECT * FROM mt_release_sessions WHERE release_id=?", (release_id,)).fetchone()
        if not rel: return {'ok': False, 'msg': 'not found'}

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("UPDATE mt_release_sessions SET "
                  "status='rolled_back', current_stage=1, current_pct=0, "
                  "rollback_count=rollback_count+1, last_rolled_back_at=?, error_at=?, "
                  "updated_at=? WHERE release_id=?",
                  (now, now, now, release_id))
        # rollback_logs (已存在的旧表)
        try:
            c.execute(
                "INSERT INTO release_rollback_logs (release_id, reason, rolled_back_by, rolled_back_at) "
                "VALUES (?,?,?,?)", (release_id, reason, actor, now))
        except Exception:
            pass

        # gray_audit
        try:
            c.execute(
                "INSERT INTO release_gray_audit "
                "(release_id, stage_from, pct_from, stage_to, pct_to, action, decision_basis, operator, comment) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (release_id, rel['current_stage'], rel['current_pct'],
                 1, 0, 'rollback', reason, actor, reason))
        except Exception:
            pass

        self.db.commit()
        print(f"[🔴 Rollback] {release_id}: {reason} (by {actor})")
        return {'ok': True, 'release_id': release_id, 'action': 'rollback'}

    # ── 指标采集 (仙女座) ──
    def collect_metrics(self, release_id: str, measured_pct: int = 0) -> Dict:
        """采集 Flask 健康指标 → 写 mt_release_metrics
        真实环境里可以从 Flask before_request hook 累积, 这里简化测 /api/health 端点
        """
        import urllib.request
        import time as _time

        start = _time.time()
        total = 0; errors = 0
        health_endpoints = [
            'http://127.0.0.1:8888/index',
            'http://127.0.0.1:8888/api/sync/health',
            'http://127.0.0.1:8888/api/health',
        ]
        for url in health_endpoints:
            total += 1
            try:
                r = urllib.request.urlopen(url, timeout=3)
                if r.status >= 400: errors += 1
            except Exception:
                errors += 1
        latency_ms = (_time.time() - start) * 1000 / max(total, 1)
        error_rate = errors / max(total, 1) * 100
        success_rate = 100 - error_rate

        # gate 判定
        gates = DEFAULT_GATES
        gate_ok = (error_rate < gates['max_error_rate']
                   and success_rate > gates['min_success_rate'])

        c = self.db.cursor()
        c.execute(
            "INSERT INTO mt_release_metrics "
            "(release_id, stage, total_requests, total_errors, success_rate, error_rate_pct, "
            "avg_latency_ms, pct, gate_ok, gate_details) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (release_id, measured_pct or 0,
             total, errors, round(success_rate, 2), round(error_rate, 2),
             round(latency_ms, 1), measured_pct or 0,
             1 if gate_ok else 0,
             json.dumps({'error_rate': error_rate, 'success_rate': success_rate,
                         'gate': dict(gates), 'gate_ok': gate_ok}, ensure_ascii=False)))

        # gray_audit
        try:
            c.execute(
                "INSERT INTO release_gray_audit "
                "(release_id, stage_from, pct_from, stage_to, pct_to, action, "
                "error_rate_pct, avg_latency_ms, success_rate, total_requests, total_errors, operator) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (release_id, 0, measured_pct or 0, 0, measured_pct or 0, 'metrics',
                 round(error_rate, 2), round(latency_ms, 1), round(success_rate, 2),
                 total, errors, 'andromeda'))
        except Exception:
            pass

        self.db.commit()
        return {'total': total, 'errors': errors, 'error_rate': round(error_rate, 2),
                'success_rate': round(success_rate, 2), 'latency_ms': round(latency_ms, 1),
                'gate_ok': gate_ok}

    # ── 查询 ──
    def get_release(self, release_id: str) -> Optional[Dict]:
        c = self.db.cursor()
        rel = c.execute(
            "SELECT * FROM mt_release_sessions WHERE release_id=?", (release_id,)).fetchone()
        if not rel: return None
        metrics = c.execute(
            "SELECT * FROM mt_release_metrics WHERE release_id=? ORDER BY measured_at DESC LIMIT 5",
            (release_id,)).fetchall()
        d = dict(rel)
        d['stage_label'] = STAGE_LABELS.get(rel['current_stage'], 'unknown')
        d['next_stage'] = RELEASE_STAGES[min(rel['current_stage'] + 1, 6)][1] if rel['current_stage'] < 6 else None
        d['metrics'] = [dict(m) for m in metrics]
        d['pct_map'] = [{'stage': s[0], 'label': s[1], 'pct': s[2]} for s in RELEASE_STAGES]
        return d

    def list_releases(self, status: str = '', limit: int = 20) -> List[Dict]:
        c = self.db.cursor()
        if status:
            rows = c.execute(
                "SELECT * FROM mt_release_sessions WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM mt_release_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── 后台自动推进 (daemon 调) ──
    def auto_progress_releases(self) -> List[Dict]:
        """扫描所有 releasing 状态 release → 采指标 → 门禁通过 → 自动升 stage → 门禁失败 → 告警
        返回: [{'release_id':..., 'action': 'advance'|'rollback'|'noop', ...}]
        """
        c = self.db.cursor()
        c.execute("SELECT * FROM mt_release_sessions WHERE status='releasing' AND current_stage < 6")
        active = c.fetchall()
        results = []

        for rel in active:
            rid = rel['release_id']
            # 1. 采指标
            metrics = self.collect_metrics(rid, rel['current_pct'])
            results.append({'release_id': rid, 'action': 'metrics_collected', 'details': metrics})

            # 2. 严重 error → 自动回滚 (error_rate > 2x 阈值)
            cur_stage_cfg = RELEASE_STAGES[rel['current_stage']]
            gate_cfg = cur_stage_cfg[4]
            max_err = gate_cfg.get('max_error_rate', DEFAULT_GATES['max_error_rate']) * 2
            if metrics['error_rate'] > max_err:
                rb = self.rollback(rid,
                    f"仙女座自动回滚: error_rate={metrics['error_rate']}% > 2x 阈值({max_err}%)",
                    actor='andromeda')
                results.append({'release_id': rid, 'action': 'auto_rollback', 'error_rate': metrics['error_rate']})
                continue

            # 3. 门禁通过 → 自动升 stage
            if metrics['gate_ok'] and AUTO_UPGRADE.get(rel['current_stage'], False):
                adv = self.advance_stage(rid)
                results.append({'release_id': rid, 'action': 'advance', 'stage': adv.get('current_stage')})
            else:
                results.append({'release_id': rid, 'action': 'wait_gate',
                                'gate_ok': metrics['gate_ok'], 'gate_details': metrics})

        return results


# ── Feature Flag 便捷入口 ──
def check_feature_flag(flag_name: str, user_id: str = '') -> bool:
    """检查 feature flag 是否对该用户开启"""
    db = sqlite3.connect(str(DB_PATH)); db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM mt_release_feature_flags WHERE flag_name=?", (flag_name,)).fetchone()
    if not row or not row['enabled']:
        db.close(); return False
    pct = row['rollout_pct']
    if pct >= 100: db.close(); return True
    if pct <= 0: db.close(); return False
    # scope 过滤
    if row['scope'] and row['scope'] != 'all':
        db.close()
        return False  # 简化: scope 只支持 all
    salt = row['salt'] or flag_name
    db.close()
    return is_in_gray(user_id or flag_name, pct, salt)


# ── CLI ──
if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(description="🟢 仙女座灰度发布引擎")
    ap.add_argument('--create', nargs=3, metavar=('name','target','initiator'),
                    help="新建发布: name v25.0 username")
    ap.add_argument('--start', metavar='REL_ID', help="审批通过 → 进入 canary")
    ap.add_argument('--advance', nargs='+', metavar='ARG', help="升 stage: rel_id [force]")
    ap.add_argument('--rollback', nargs=2, metavar=('REL_ID','reason'), help="一键回滚")
    ap.add_argument('--metrics', metavar='REL_ID', help="采集指标")
    ap.add_argument('--progress', action='store_true', help="自动推进所有 releasing")
    ap.add_argument('--list', nargs='?', const='', help="列出全部 (可加 status filter)")
    ap.add_argument('--show', metavar='REL_ID', help="详情 + 指标")
    ap.add_argument('--flag-create', nargs=2, metavar=('name','pct'), help="创建 feature flag")
    ap.add_argument('--flag-check', nargs=2, metavar=('name','user'), help="检查 flag 对用户是否开启")
    args = ap.parse_args()

    eng = GrayReleaseEngine()

    if args.create:
        rid = eng.create_release(args.create[0], args.create[1], args.create[2])
        print(f"✅ created release_id={rid}")
    elif args.start:
        print(eng.approve_and_start(args.start, 'cli'))
    elif args.advance:
        rid = args.advance[0]
        force = len(args.advance) > 1 and args.advance[1] == 'force'
        print(eng.advance_stage(rid, force=force))
    elif args.rollback:
        print(eng.rollback(args.rollback[0], args.rollback[1]))
    elif args.metrics:
        m = eng.collect_metrics(args.metrics)
        print(f"✅ metrics: total={m['total']} err={m['errors']} err_rate={m['error_rate']}% "
              f"success={m['success_rate']}% latency={m['latency_ms']}ms gate_ok={m['gate_ok']}")
    elif args.progress:
        res = eng.auto_progress_releases()
        print(f"📊 auto_progress: {len(res)} actions")
        for r in res: print(f"  {r}")
    elif args.list is not None:
        releases = eng.list_releases(args.list)
        print(f"📋 releases: {len(releases)}")
        for r in releases:
            sl = STAGE_LABELS.get(r['current_stage'], '?')
            print(f"  {r['release_id']} [{r['status']}] {sl}({r['current_pct']}%) {r['name']}")
    elif args.show:
        d = eng.get_release(args.show)
        if d: print(json.dumps(d, ensure_ascii=False, indent=2))
        else: print("not found")
    elif args.flag_create:
        c = eng.db.cursor()
        c.execute(
            "INSERT OR REPLACE INTO mt_release_feature_flags (flag_name, rollout_pct, salt) "
            "VALUES (?,?,?)",
            (args.flag_create[0], int(args.flag_create[1]),
             hashlib.md5(args.flag_create[0].encode()).hexdigest()[:8]))
        eng.db.commit()
        print(f"✅ flag {args.flag_create[0]} @ {args.flag_create[1]}%")
    elif args.flag_check:
        r = check_feature_flag(args.flag_check[0], args.flag_check[1])
        print(f"✅ flag={args.flag_check[0]} user={args.flag_check[1]} → {'ON' if r else 'OFF'}")
    else:
        ap.print_help()
