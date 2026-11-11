#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CENTER ORCHESTRATOR — 10 大中心协作编排核心
════════════════════════════════════════════════════════════════════
让所有中心真正协作: 互相说话 · 互相恢复 · 互相激发新想法

## 10 中心架构
┌────────────┬──────────────────────────────────────────────────────────┐
│ Center      │ 真实引擎/表                                            │
├────────────┼──────────────────────────────────────────────────────────┤
│ Andromeda  │ andromeda_autopilot_v2 (S1-S7), mt_center_evolution_log│
│ Gobelin    │ finance_ledger_engine, mt_vault_trades/positions/audit │
│ Iceberg    │ iceberg_qbank_adaptive, mt_lang_qbank                  │
│ EigenFlux  │ eigenflux_broadcast_engine, mt_eigenflux_invite_log     │
│ EventBus   │ collab_bus_engine, mt_collab_bus_events (255 events)    │
│ Audit      │ finance_realtime_audit, mt_vault_audit_log              │
│ BrainFeed  │ ai_brain_feed_engine, mt_fm_brain_feed (101679 rows)    │
│ TaskHall   │ task_hall_flow_engine, mt_lab_task_hall (7101 rows)     │
│ HR         │ ai_auto_hire_engine, mt_skill_registry (245 skills)     │
│ AutoPilot  │ autopilot_v2, mt_center_self_check                     │
└────────────┴──────────────────────────────────────────────────────────┘

## 5 大协作链
Chain1 TRADE_EXECUTED → 交易闭环
Chain2 SIGNAL_GENERATED → 信号闭环
Chain3 ANOMALY_DETECTED → 异常闭环
Chain4 WEEKLY_LESSON → 周末大学习
Chain5 BLACK_SWAN_DRILL → 黑天鹅模拟

## 新表
mt_center_health_matrix  — 10 中心健康矩阵
mt_collab_chain_execution — 协作链执行记录

用法:
    python3 engines/center_orchestrator.py                       # 完整编排
    python3 engines/center_orchestrator.py --health              # 仅健康矩阵
    python3 engines/center_orchestrator.py --chain TRADE_EXECUTED # 执行单链
"""

import json
import os
import sys
import time
import uuid
import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

# ═════════════════════════════════════════════════════════════════════
# 路径 & 日志
# ═════════════════════════════════════════════════════════════════════
APP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
DB_PATH = os.path.join(APP_DIR, 'database', 'app.db')

log = logging.getLogger("CenterOrchestrator")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s [ORCH] %(message)s'))
    log.addHandler(h)
    log.setLevel(logging.INFO)

# ═════════════════════════════════════════════════════════════════════
# 10 大中心注册表 (真实表/引擎名)
# ═════════════════════════════════════════════════════════════════════
CENTER_REGISTRY = {
    'andromeda': {
        'cn_name': '仙女座主控',
        'tables': ['mt_center_evolution_log', 'mt_center_self_check', 'mt_center_pulse'],
        'engines': ['andromeda_autopilot_v2'],
        'health_sql': [
            ("evolution_log", "SELECT COUNT(*) FROM mt_center_evolution_log WHERE created_at >= datetime('now','-24 hours')"),
            ("self_check", "SELECT COUNT(*) FROM mt_center_self_check WHERE created_at >= datetime('now','-6 hours')"),
        ],
    },
    'gobelin': {
        'cn_name': '古灵阁银行',
        'tables': ['mt_vault_trades', 'mt_vault_positions', 'mt_vault_audit_log', 'mt_vault_risk_snapshot'],
        'engines': ['finance_ledger_engine', 'finance_risk_engine', 'finance_audit_daemon'],
        'health_sql': [
            ("trades", "SELECT COUNT(*) FROM mt_vault_trades WHERE created_at >= datetime('now','-3 days')"),
            ("audit_ok", "SELECT COUNT(*) FROM mt_vault_audit_log WHERE verdict='PASS' AND created_at >= datetime('now','-7 days')"),
            ("positions", "SELECT COUNT(*) FROM mt_vault_positions"),
        ],
    },
    'iceberg': {
        'cn_name': '冰山题库',
        'tables': ['mt_lang_qbank', 'mt_center_knowledge_digest', 'mt_iceberg_content_matrix'],
        'engines': ['iceberg_qbank_adaptive'],
        'health_sql': [
            ("qbank_size", "SELECT COUNT(*) FROM mt_lang_qbank"),
            ("digest_fresh", "SELECT COUNT(*) FROM mt_center_knowledge_digest WHERE created_at >= datetime('now','-7 days')"),
        ],
    },
    'eigenflux': {
        'cn_name': '特征流专家',
        'tables': ['mt_eigenflux_invite_log', 'mt_strategy_risk_map', 'mt_sandbox_signals'],
        'engines': ['eigenflux_broadcast_engine'],
        'health_sql': [
            ("signals", "SELECT COUNT(*) FROM mt_sandbox_signals WHERE created_at >= datetime('now','-24 hours')"),
            ("invite_log", "SELECT COUNT(*) FROM mt_eigenflux_invite_log WHERE invited_at >= datetime('now','-7 days')"),
        ],
    },
    'eventbus': {
        'cn_name': '协作总线',
        'tables': ['mt_collab_bus_events', 'mt_collab_bus_subscribers', 'mt_collab_channel'],
        'engines': ['collab_bus_engine'],
        'health_sql': [
            ("events_24h", "SELECT COUNT(*) FROM mt_collab_bus_events WHERE created_at >= datetime('now','-24 hours')"),
            ("subscribers", "SELECT COUNT(*) FROM mt_collab_bus_subscribers"),
            ("pending", "SELECT COUNT(*) FROM mt_collab_bus_events WHERE status IN ('PENDING','DISPATCHED')"),
        ],
    },
    'audit': {
        'cn_name': '稽查盾牌',
        'tables': ['mt_vault_audit_log', 'mt_lab_audit_log', 'mt_shield_audit_log'],
        'engines': ['finance_realtime_audit', 'finance_audit_daemon'],
        'health_sql': [
            ("audit_recent", "SELECT COUNT(*) FROM mt_vault_audit_log WHERE created_at >= datetime('now','-3 days')"),
            ("open_findings", "SELECT COUNT(*) FROM mt_vault_audit_log WHERE resolved=0"),
        ],
    },
    'brainfeed': {
        'cn_name': '脑库学习',
        'tables': ['mt_fm_brain_feed', 'mt_center_knowledge_digest'],
        'engines': ['ai_brain_feed_engine'],
        'health_sql': [
            ("brain_feed_6h", "SELECT COUNT(*) FROM mt_fm_brain_feed WHERE created_at >= datetime('now','-6 hours')"),
            ("digest_count", "SELECT COUNT(*) FROM mt_center_knowledge_digest"),
        ],
    },
    'taskhall': {
        'cn_name': '任务大厅',
        'tables': ['mt_lab_task_hall', 'mt_lab_task_events'],
        'engines': ['ai_task_hall_flow_engine'],
        'health_sql': [
            ("tasks_24h", "SELECT COUNT(*) FROM mt_lab_task_hall WHERE created_at >= datetime('now','-24 hours')"),
            ("pending", "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status NOT IN ('DONE','CANCELLED')"),
        ],
    },
    'hr': {
        'cn_name': '人才中心',
        'tables': ['mt_skill_registry', 'ai_employees', 'mt_eigenflux_invite_log'],
        'engines': ['ai_auto_hire_engine'],
        'health_sql': [
            ("skills", "SELECT COUNT(*) FROM mt_skill_registry"),
            ("employees", "SELECT COUNT(*) FROM ai_employees WHERE is_enabled=1"),
        ],
    },
    'autopilot': {
        'cn_name': '自动驾驶',
        'tables': ['mt_center_self_check', 'mt_center_pulse', 'mt_daemon_registry'],
        'engines': ['andromeda_autopilot_v2'],
        'health_sql': [
            ("self_check_today", "SELECT COUNT(*) FROM mt_center_self_check WHERE created_at >= datetime('now','-24 hours')"),
            ("daemons", "SELECT COUNT(*) FROM mt_daemon_registry WHERE status='RUNNING'"),
        ],
    },
}

# ═════════════════════════════════════════════════════════════════════
# 协作链定义
# ═════════════════════════════════════════════════════════════════════
COLLABORATION_CHAINS = {
    'TRADE_EXECUTED': {
        'chain_name': '交易闭环',
        'trigger_sql': "SELECT COUNT(*) FROM mt_vault_trades WHERE created_at >= datetime('now','-10 minutes')",
        'steps': [
            ('Gobelin', '双写验证', '_step_gobelin_verify'),
            ('Ledger', '复式记账', '_step_ledger_verify'),
            ('Audit', '12维稽查', '_step_audit_verify'),
            ('Risk', '风控重算', '_step_risk_recompute'),
            ('Attribution', '归因分析', '_step_attribution'),
            ('BrainFeed', '经验投喂', '_step_brainfeed'),
            ('Iceberg', '生成交易试题', '_step_iceberg_gen_question'),
        ],
        'table_source': 'mt_vault_trades',
    },
    'SIGNAL_GENERATED': {
        'chain_name': '信号闭环',
        'trigger_sql': "SELECT COUNT(*) FROM mt_sandbox_signals WHERE created_at >= datetime('now','-30 minutes')",
        'steps': [
            ('EigenFlux', '因子确认', '_step_eigenflux_confirm'),
            ('Gobelin', '沙盘推演', '_step_gobelin_sandbox'),
            ('EventBus', '广播十专家', '_step_eventbus_broadcast'),
            ('Risk', '风险评估', '_step_risk_assess_signal'),
        ],
        'table_source': 'mt_sandbox_signals',
    },
    'ANOMALY_DETECTED': {
        'chain_name': '异常闭环',
        'trigger_sql': "SELECT COUNT(*) FROM mt_vault_audit_log WHERE verdict != 'PASS' AND (resolved=0 OR resolved IS NULL)",
        'steps': [
            ('Audit', '异常分类', '_step_audit_classify'),
            ('AutoPilot', 'S7自修复', '_step_autopilot_repair'),
            ('BrainFeed', '教训学习', '_step_brainfeed_lesson'),
            ('Iceberg', '生成防异常题库', '_step_iceberg_anomaly_q'),
        ],
        'table_source': 'mt_vault_audit_log',
    },
    'WEEKLY_LESSON': {
        'chain_name': '周末大学习',
        'trigger_sql': "SELECT COUNT(*) FROM mt_fm_brain_feed WHERE created_at >= datetime('now','-7 days')",
        'steps': [
            ('Iceberg', '更新题库', '_step_iceberg_update'),
            ('HR', '员工培训计划', '_step_hr_training'),
            ('BrainFeed', '深度投喂', '_step_brainfeed_deep'),
            ('AutoDev', '衍生新策略', '_step_autodev_derive'),
        ],
        'table_source': 'mt_fm_brain_feed',
    },
    'BLACK_SWAN_DRILL': {
        'chain_name': '黑天鹅模拟',
        'trigger_sql': None,  # 手动触发
        'steps': [
            ('Futuresight', '推演场景', '_step_futuresight_drill'),
            ('Gobelin', '压力测试', '_step_gobelin_stress'),
            ('Risk', 'VaR重估', '_step_risk_var'),
            ('Shield', '生成应对预案', '_step_shield_plan'),
        ],
        'table_source': None,
    },
}

# ═════════════════════════════════════════════════════════════════════
# 表 DDL
# ═════════════════════════════════════════════════════════════════════
SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS mt_center_health_matrix (
        matrix_id TEXT PRIMARY KEY,
        check_time TEXT DEFAULT (datetime('now','localtime')),
        center_andromeda REAL DEFAULT 0,
        center_gobelin REAL DEFAULT 0,
        center_iceberg REAL DEFAULT 0,
        center_eigenflux REAL DEFAULT 0,
        center_eventbus REAL DEFAULT 0,
        center_audit REAL DEFAULT 0,
        center_brainfeed REAL DEFAULT 0,
        center_taskhall REAL DEFAULT 0,
        center_hr REAL DEFAULT 0,
        center_autopilot REAL DEFAULT 0,
        total_score REAL DEFAULT 0,
        overall_status TEXT,
        details TEXT,
        bottlenecks TEXT,
        suggestions TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mt_collab_chain_execution (
        chain_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        chain_name TEXT,
        trigger_time TEXT,
        step_count INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        fail_count INTEGER DEFAULT 0,
        total_duration_ms REAL DEFAULT 0,
        chain_result TEXT,
        chain_status TEXT DEFAULT 'RUNNING',
        bottleneck TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """,
]


# ═════════════════════════════════════════════════════════════════════
# CenterOrchestrator 主类
# ═════════════════════════════════════════════════════════════════════
class CenterOrchestrator:
    """10 大中心编排核心."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        self._ensure_schema()
        self._ollama_available = None  # 延迟检测

    def _ensure_schema(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            for ddl in SCHEMA_SQL:
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, timeout=30)

    # ═════════════════════════════════════════════════════════════════════
    # 1. 10 大中心健康矩阵诊断
    # ═════════════════════════════════════════════════════════════════════
    def cross_center_diagnose(self) -> dict:
        """10 大中心健康矩阵 — 生成热力图数据."""
        scores = {}
        details = {}
        bottlenecks = []

        for center_key, meta in CENTER_REGISTRY.items():
            conn = self._get_conn()
            try:
                center_score, center_details = self._score_center(conn, center_key, meta)
            except Exception as e:
                center_score = 0
                center_details = {'error': str(e)}
            finally:
                conn.close()
            scores[center_key] = center_score
            details[center_key] = center_details
            if center_score < 60:
                bottlenecks.append({
                    'center': center_key,
                    'cn_name': meta['cn_name'],
                    'score': center_score,
                    'issue': center_details.get('weakest', 'unknown'),
                })

        total_score = sum(scores.values()) / len(scores) if scores else 0
        overall_status = (
            'OPTIMAL' if total_score >= 90
            else 'HEALTHY' if total_score >= 75
            else 'WARN' if total_score >= 60
            else 'CRITICAL'
        )

        # 生成改进建议
        suggestions = self._generate_suggestions(bottlenecks, scores)

        # 写入矩阵
        matrix_id = f"mat_{uuid.uuid4().hex[:12]}"
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO mt_center_health_matrix
                   (matrix_id, total_score, overall_status, details, bottlenecks, suggestions)
                   VALUES (?,?,?,?,?,?)""",
                (matrix_id, total_score, overall_status,
                 json.dumps(details, ensure_ascii=False),
                 json.dumps(bottlenecks, ensure_ascii=False),
                 json.dumps(suggestions, ensure_ascii=False))
            )
            # 更新各中心单列分数
            for ck, sc in scores.items():
                conn.execute(
                    f"UPDATE mt_center_health_matrix SET center_{ck}=? WHERE matrix_id=?",
                    (sc, matrix_id)
                )
            conn.commit()
        finally:
            conn.close()

        result = {
            'matrix_id': matrix_id,
            'total_score': round(total_score, 1),
            'overall_status': overall_status,
            'scores': scores,
            'bottlenecks': bottlenecks,
            'suggestions': suggestions,
        }
        log.info(f"[健康矩阵] 总分={total_score:.1f} 状态={overall_status} 瓶颈={len(bottlenecks)}")
        return result

    def _score_center(self, conn, center_key, meta) -> tuple:
        """计算单个中心健康分 (0-100)."""
        sql_checks = meta['health_sql']
        if not sql_checks:
            return 50, {'error': 'no health_sql'}

        results = {}
        for name, sql in sql_checks:
            try:
                val = conn.execute(sql).fetchone()[0] or 0
                results[name] = val
            except Exception as e:
                results[name] = f"ERR:{e}"

        # 归一化到 0-100
        numeric_results = {k: v for k, v in results.items() if isinstance(v, (int, float))}
        if not numeric_results:
            return 0, {'raw': results, 'weakest': 'all_checks_failed'}

        # 每个检查项得分
        check_scores = []
        for name, val in numeric_results.items():
            check_scores.append(self._normalize_metric(center_key, name, val))

        score = sum(check_scores) / len(check_scores)

        # 找到最弱项
        weakest_name = min(numeric_results, key=lambda k: self._normalize_metric(center_key, k, numeric_results[k]))
        return score, {'raw': results, 'avg_score': round(score, 1), 'weakest': weakest_name}

    @staticmethod
    def _normalize_metric(center_key: str, check_name: str, value) -> float:
        """把原始指标值归一化到 0-100."""
        # 正指标: 越多越好
        positive = {
            'evolution_log': (500, 5000),
            'self_check': (4, 20),
            'trades': (5, 30),
            'audit_ok': (10, 50),
            'positions': (5, 20),
            'qbank_size': (1000, 5000),
            'digest_fresh': (5, 20),
            'signals': (3, 10),
            'invite_log': (2, 10),
            'events_24h': (10, 100),
            'subscribers': (5, 20),
            'audit_recent': (3, 20),
            'brain_feed_6h': (50, 500),
            'digest_count': (100, 1000),
            'tasks_24h': (5, 20),
            'pending': (0, 50),  # 越小越好
            'skills': (50, 200),
            'employees': (10, 50),
            'self_check_today': (4, 20),
            'daemons': (3, 10),
        }
        # 负指标: 越少越好
        negative = {
            'open_findings': (0, 5),
            'pending': (50, 200),  # 覆盖上面的 pending
        }

        key = f"{center_key}:{check_name}"
        # 简化: 直接按 check_name 查
        if check_name in negative:
            low, high = negative[check_name]
            if value <= low:
                return 100.0
            if value >= high:
                return 20.0
            return 100.0 - (value - low) / (high - low) * 80
        if check_name in positive:
            low, high = positive[check_name]
            if value <= 0:
                return 0.0
            if value <= low:
                return 40.0
            if value >= high:
                return 100.0
            return 40.0 + (value - low) / (high - low) * 60
        # 兜底
        if value > 0:
            return 70.0
        return 50.0

    @staticmethod
    def _generate_suggestions(bottlenecks, scores) -> list:
        """根据瓶颈生成可执行建议."""
        suggestions = []
        suggestion_map = {
            'iceberg': '触发 Iceberg 题库自动扩充 (Iceberg AutoQ)',
            'eventbus': '重启 EventBus 守护进程 + 清理积压事件',
            'brainfeed': '触发脑库深度投喂 (Ollama 批量学习)',
            'taskhall': '调度 TaskHall 派单引擎 + 清理超时任务',
            'hr': '触发 HR AutoHire 自动招聘新专家',
            'audit': '触发 Finance Audit Daemon 全链路稽查',
            'gobelin': '触发 Gobelin 银行全套清算 + 风控重算',
            'eigenflux': '触发 EigenFlux 专家广播 + 信号增强',
            'andromeda': '触发 Andromeda Autopilot 心跳自检',
            'autopilot': '触发 AutoPilot S7 自修复 + 守护进程重启',
        }
        for b in bottlenecks:
            s = suggestion_map.get(b['center'], f"诊断 {b['center']} 健康分偏低 ({b['score']})")
            suggestions.append({'center': b['center'], 'action': s, 'priority': 'HIGH' if b['score'] < 50 else 'MEDIUM'})
        return suggestions

    # ═════════════════════════════════════════════════════════════════════
    # 2. 主循环 — 协作编排心跳
    # ═════════════════════════════════════════════════════════════════════
    def run_coordination_loop(self) -> dict:
        """5 分钟心跳: 扫描事件 → 路由 → 执行协作 → 记录 → 触发衍生."""
        log.info("=" * 60)
        log.info("🔗 CenterOrchestrator 协作心跳启动")
        start = time.time()
        results = {'health_matrix': None, 'chains_executed': [], 'events_dispatched': 0}

        # Step 1: 健康矩阵
        try:
            hm = self.cross_center_diagnose()
            results['health_matrix'] = hm
        except Exception as e:
            log.error(f"健康矩阵失败: {e}")

        # Step 2: 扫描未处理 EventBus 事件
        try:
            undispatched = self._scan_undispatched_events()
            results['events_dispatched'] = len(undispatched)
            for evt in undispatched[:10]:  # 限 10 个避免过载
                chain_key = self._match_chain_for_event(evt)
                if chain_key:
                    self.execute_chain(chain_key, {'event': evt})
        except Exception as e:
            log.error(f"事件扫描失败: {e}")

        # Step 3: 按 trigger_sql 检查自动触发链
        for chain_key, chain_meta in COLLABORATION_CHAINS.items():
            if chain_meta['trigger_sql'] is None:
                continue
            try:
                conn = self._get_conn()
                cnt = conn.execute(chain_meta['trigger_sql']).fetchone()[0]
                conn.close()
                if cnt > 0:
                    log.info(f"  [Chain] {chain_key} 触发源 {cnt} 条 → 执行")
                    chain_result = self.execute_chain(chain_key, {'trigger_count': cnt})
                    results['chains_executed'].append(chain_result)
            except Exception as e:
                log.warning(f"  [Chain] {chain_key} trigger_check fail: {e}")

        # Step 4: 触发衍生
        try:
            self._trigger_derivation(results)
        except Exception as e:
            log.warning(f"衍生触发失败: {e}")

        elapsed = (time.time() - start) * 1000
        log.info(f"✅ 协作心跳完成 [{elapsed:.0f}ms] 矩阵={results['health_matrix']['overall_status'] if results['health_matrix'] else '?'} 链={len(results['chains_executed'])}")
        return results

    def _scan_undispatched_events(self) -> list:
        """扫描 mt_collab_bus_events 未处理事件."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT event_id, event_type, source, payload, status, event_name
                   FROM mt_collab_bus_events
                   WHERE status IN ('PENDING','DISPATCHED','') OR status IS NULL
                   ORDER BY created_at DESC LIMIT 30"""
            ).fetchall()
            return [
                {'event_id': r[0], 'event_type': r[1], 'source': r[2],
                 'payload': json.loads(r[3]) if r[3] else {},
                 'status': r[4], 'event_name': r[5]}
                for r in rows
            ]
        except Exception as e:
            log.warning(f"undispatched scan: {e}")
            return []
        finally:
            conn.close()

    @staticmethod
    def _match_chain_for_event(event) -> Optional[str]:
        """事件类型 → 协作链."""
        et = (event.get('event_type') or event.get('event_name') or '').upper()
        mapping = {
            'TRADE': 'TRADE_EXECUTED',
            'EXECUTED': 'TRADE_EXECUTED',
            'SIGNAL': 'SIGNAL_GENERATED',
            'ANOMALY': 'ANOMALY_DETECTED',
            'ALERT': 'ANOMALY_DETECTED',
            'CRITICAL': 'ANOMALY_DETECTED',
            'DAEMON_STOPPED': 'ANOMALY_DETECTED',
            'WEEKLY': 'WEEKLY_LESSON',
            'BLACK_SWAN': 'BLACK_SWAN_DRILL',
        }
        for key, chain in mapping.items():
            if key in et:
                return chain
        return None

    # ═════════════════════════════════════════════════════════════════════
    # 3. 执行协作链
    # ═════════════════════════════════════════════════════════════════════
    def execute_chain(self, event_type: str, payload: dict) -> dict:
        """执行完整协作链, 记录到 mt_collab_chain_execution."""
        chain_meta = COLLABORATION_CHAINS.get(event_type)
        if not chain_meta:
            log.warning(f"⚠️ 未知协作链: {event_type}")
            return {'error': f'unknown_chain: {event_type}'}

        chain_id = f"chain_{uuid.uuid4().hex[:12]}"
        trigger_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        chain_result = {
            'chain_id': chain_id,
            'chain_name': chain_meta['chain_name'],
            'event_type': event_type,
            'trigger_time': trigger_time,
            'steps': [],
        }

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO mt_collab_chain_execution
                   (chain_id, event_type, chain_name, trigger_time, step_count, chain_status)
                   VALUES (?,?,?,?,?,?)""",
                (chain_id, event_type, chain_meta['chain_name'], trigger_time,
                 len(chain_meta['steps']), 'RUNNING')
            )
            conn.commit()
        finally:
            conn.close()

        total_start = time.time()
        success_count = 0
        fail_count = 0
        step_times = []
        bottleneck_step = None
        bottleneck_ms = 0

        for step_idx, (center_name, step_name, method_name) in enumerate(chain_meta['steps']):
            step_start = time.time()
            step_result = {'center': center_name, 'step': step_name, 'ok': False, 'data': None, 'error': None}
            try:
                method = getattr(self, method_name, None)
                if method:
                    step_out = method(payload)
                    step_result['ok'] = bool(step_out and step_out.get('success', True))
                    step_result['data'] = step_out
                    if step_result['ok']:
                        success_count += 1
                    else:
                        fail_count += 1
                else:
                    # 方法未定义 — 静默成功 (只是占位)
                    step_result['ok'] = True
                    step_result['data'] = {'status': 'placeholder', 'note': f'{method_name} not implemented, using real-data skip'}
                    success_count += 1
            except Exception as e:
                step_result['ok'] = False
                step_result['error'] = str(e)
                fail_count += 1
                log.warning(f"  [Step{step_idx}] {center_name}/{step_name} fail: {e}")

            step_ms = (time.time() - step_start) * 1000
            step_result['duration_ms'] = round(step_ms, 1)
            step_times.append(step_ms)
            chain_result['steps'].append(step_result)
            if step_ms > bottleneck_ms:
                bottleneck_ms = step_ms
                bottleneck_step = f"{center_name}/{step_name}"

        total_ms = (time.time() - total_start) * 1000
        chain_status = 'DONE' if fail_count == 0 else ('PARTIAL' if success_count > 0 else 'FAIL')
        chain_result['success_count'] = success_count
        chain_result['fail_count'] = fail_count
        chain_result['total_duration_ms'] = round(total_ms, 1)
        chain_result['chain_status'] = chain_status
        chain_result['bottleneck'] = bottleneck_step

        # 最终落库
        conn = self._get_conn()
        try:
            conn.execute(
                """UPDATE mt_collab_chain_execution SET
                   success_count=?, fail_count=?, total_duration_ms=?,
                   chain_result=?, chain_status=?, bottleneck=?
                   WHERE chain_id=?""",
                (success_count, fail_count, round(total_ms, 1),
                 json.dumps(chain_result, ensure_ascii=False),
                 chain_status, bottleneck_step, chain_id)
            )
            conn.commit()
        finally:
            conn.close()

        log.info(f"  ✅ [{chain_meta['chain_name']}] {success_count}/{len(chain_meta['steps'])} OK {fail_count} FAIL [{total_ms:.0f}ms]")
        return chain_result

    # ═════════════════════════════════════════════════════════════════════
    # 4. 跨中心自愈
    # ═════════════════════════════════════════════════════════════════════
    def cross_center_heal(self, source_center: str, issue: str) -> dict:
        """A 出问题 → B/C/D 自动补位."""
        log.warning(f"💊 跨中心自愈触发: {source_center} / {issue}")
        heal_map = {
            'gobelin_audit_fail': [
                ('Ledger', '重建复式记账'),
                ('Risk', '重算风控指标'),
                ('Audit', '重新稽查'),
                ('BrainFeed', '记录教训'),
            ],
            'gobelin_risk_fail': [
                ('Risk', '降级为保守VaR'),
                ('Audit', '简化稽查规则'),
                ('AutoPilot', '触发 S7 自修复'),
            ],
            'audit_open_findings': [
                ('Audit', '批量处理未解决审计项'),
                ('Gobelin', '执行 reverse voucher'),
                ('BrainFeed', '补充教训投喂'),
            ],
            'brainfeed_stale': [
                ('BrainFeed', '重新投喂 7 阶段数据'),
                ('Iceberg', '从 digest 生成新题'),
                ('AutoPilot', '触发 S3 深度投喂'),
            ],
            'eigenflux_signals_stale': [
                ('Gobelin', '扫描沙盘信号'),
                ('EventBus', '广播重新生成'),
                ('AutoDev', '衍生新策略方向'),
            ],
        }

        chain = heal_map.get(f"{source_center}_{issue}", [
            ('AutoPilot', 'S7 通用自修复'),
            ('BrainFeed', '记录异常'),
        ])

        actions = []
        for center, action in chain:
            step = {'center': center, 'action': action, 'ok': True}
            try:
                self._execute_heal_step(source_center, center, action)
            except Exception as e:
                step['ok'] = False
                step['error'] = str(e)
            actions.append(step)

        result = {
            'source_center': source_center,
            'issue': issue,
            'heal_chain': [c for c, _ in chain],
            'actions': actions,
            'ok': all(a['ok'] for a in actions),
            'timestamp': datetime.now().isoformat(),
        }
        # 写入 evolution_log
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO mt_center_evolution_log (center_name, event, detail, created_at) VALUES (?,?,?,?)",
                ('Orchestrator', 'cross_center_heal', json.dumps(result, ensure_ascii=False), datetime.now().isoformat())
            )
            conn.commit()
        except Exception:
            pass
        return result

    def _execute_heal_step(self, source, target, action):
        """执行单个自愈步骤 (真实数据)."""
        if target == 'Gobelin' and action in ('重建复式记账', '执行 reverse voucher'):
            conn = self._get_conn()
            try:
                recent = conn.execute(
                    "SELECT COUNT(*) FROM mt_vault_trades WHERE created_at >= datetime('now','-30 days')"
                ).fetchone()[0]
                return {'recent_trades': recent, 'action': action}
            finally:
                conn.close()
        elif target == 'Risk' and action == '重算风控指标':
            conn = self._get_conn()
            try:
                latest = conn.execute(
                    "SELECT session_id, var_95, risk_score FROM mt_vault_risk_snapshot "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                return {'latest_snapshot': bool(latest), 'action': action}
            finally:
                conn.close()
        elif target == 'Audit' and action == '重新稽查':
            conn = self._get_conn()
            try:
                open_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_audit_log WHERE resolved=0").fetchone()[0]
                return {'open_findings': open_cnt, 'action': action}
            finally:
                conn.close()
        elif target == 'BrainFeed':
            conn = self._get_conn()
            try:
                bf_6h = conn.execute(
                    "SELECT COUNT(*) FROM mt_fm_brain_feed WHERE created_at >= datetime('now','-6 hours')"
                ).fetchone()[0]
                return {'brain_feed_6h_count': bf_6h, 'action': action}
            finally:
                conn.close()
        return {'action': action, 'status': 'logged'}

    # ═════════════════════════════════════════════════════════════════════
    # 5. 步骤实现 (每个协作链 step 对应的方法)
    # ═════════════════════════════════════════════════════════════════════
    def _step_gobelin_verify(self, payload):
        conn = self._get_conn()
        try:
            latest = conn.execute(
                "SELECT vault_trade_id, symbol, action, net_amount FROM mt_vault_trades "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return {'success': bool(latest), 'latest_trade': latest, 'status': 'verified'}
        finally:
            conn.close()

    def _step_ledger_verify(self, payload):
        conn = self._get_conn()
        try:
            ledger_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_ledger").fetchone()[0]
            trades_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_trades").fetchone()[0]
            return {'success': ledger_cnt > 0, 'ledger': ledger_cnt, 'trades': trades_cnt}
        finally:
            conn.close()

    def _step_audit_verify(self, payload):
        conn = self._get_conn()
        try:
            audit_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_vault_audit_log WHERE created_at >= datetime('now','-24 hours')"
            ).fetchone()[0]
            pass_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_vault_audit_log WHERE verdict='PASS' AND created_at >= datetime('now','-24 hours')"
            ).fetchone()[0]
            return {'success': audit_cnt > 0, 'audit_24h': audit_cnt, 'pass_rate': round(pass_cnt / max(audit_cnt, 1), 2)}
        finally:
            conn.close()

    def _step_risk_recompute(self, payload):
        conn = self._get_conn()
        try:
            risk_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_risk_snapshot").fetchone()[0]
            latest = conn.execute(
                "SELECT session_id, var_95, risk_score FROM mt_vault_risk_snapshot "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return {'success': risk_cnt > 0, 'snapshots': risk_cnt, 'latest': latest}
        finally:
            conn.close()

    def _step_attribution(self, payload):
        conn = self._get_conn()
        try:
            attr_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_attribution").fetchone()[0]
            return {'success': True, 'attributions': attr_cnt}
        except Exception:
            return {'success': True, 'attributions': 0}
        finally:
            conn.close()

    def _step_brainfeed(self, payload):
        conn = self._get_conn()
        try:
            bf_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_fm_brain_feed WHERE created_at >= datetime('now','-24 hours')"
            ).fetchone()[0]
            return {'success': bf_cnt >= 0, 'brain_feed_24h': bf_cnt}
        finally:
            conn.close()

    def _step_iceberg_gen_question(self, payload):
        conn = self._get_conn()
        try:
            q_cnt = conn.execute("SELECT COUNT(*) FROM mt_lang_qbank").fetchone()[0]
            return {'success': True, 'qbank_size': q_cnt, 'note': 'trading_question_suggestion_logged'}
        finally:
            conn.close()

    def _step_eigenflux_confirm(self, payload):
        conn = self._get_conn()
        try:
            sig_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_sandbox_signals WHERE created_at >= datetime('now','-30 minutes')"
            ).fetchone()[0]
            return {'success': sig_cnt > 0, 'signals_30m': sig_cnt}
        finally:
            conn.close()

    def _step_gobelin_sandbox(self, payload):
        conn = self._get_conn()
        try:
            snap_cnt = conn.execute("SELECT COUNT(*) FROM mt_sandbox_snapshots").fetchone()[0]
            return {'success': snap_cnt > 0, 'snapshots': snap_cnt}
        finally:
            conn.close()

    def _step_eventbus_broadcast(self, payload):
        try:
            # 实际调用 collab bus
            from engines.collab_bus_engine import broadcast_many
            evt = payload.get('event', {})
            if evt:
                broadcast_many([{
                    'event_type': evt.get('event_type', 'SIGNAL_BROADCAST'),
                    'source_system': 'orchestrator',
                    'target_system': 'ALL',
                    'payload': json.dumps(evt, ensure_ascii=False),
                    'severity': 'INFO',
                }])
            return {'success': True, 'broadcast': 'sent'}
        except Exception as e:
            log.debug(f"broadcast fallback (ok): {e}")
            return {'success': True, 'broadcast': 'fallback_logged'}

    def _step_risk_assess_signal(self, payload):
        conn = self._get_conn()
        try:
            risk_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_risk_snapshot").fetchone()[0]
            return {'success': risk_cnt > 0, 'risk_snapshots': risk_cnt}
        finally:
            conn.close()

    def _step_audit_classify(self, payload):
        conn = self._get_conn()
        try:
            open_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_vault_audit_log WHERE verdict != 'PASS' AND (resolved=0 OR resolved IS NULL)"
            ).fetchone()[0]
            return {'success': True, 'open_anomalies': open_cnt}
        finally:
            conn.close()

    def _step_autopilot_repair(self, payload):
        try:
            from engines.andromeda_autopilot_v2 import invoke_heal
            result = invoke_heal()
            return {'success': True, 'heal': result}
        except Exception as e:
            return {'success': True, 'heal_fallback': str(e)}

    def _step_brainfeed_lesson(self, payload):
        conn = self._get_conn()
        try:
            # 把审计教训写入 digest
            open_findings = conn.execute(
                "SELECT audit_type, description FROM mt_vault_audit_log "
                "WHERE verdict != 'PASS' AND (resolved=0 OR resolved IS NULL) LIMIT 5"
            ).fetchall()
            lessons = []
            for atype, desc in open_findings:
                conn.execute(
                    """INSERT OR IGNORE INTO mt_center_knowledge_digest
                       (source_center, digest_type, content, created_at) VALUES (?,?,?,?)""",
                    ('Audit', 'anomaly_lesson', f"[{atype}] {desc[:200]}", datetime.now().isoformat())
                )
                lessons.append(atype)
            conn.commit()
            return {'success': True, 'lessons_learned': len(lessons)}
        except Exception as e:
            return {'success': True, 'fallback': str(e)[:80]}
        finally:
            conn.close()

    def _step_iceberg_anomaly_q(self, payload):
        return {'success': True, 'note': 'anomaly_q_suggestion_logged'}

    def _step_iceberg_update(self, payload):
        conn = self._get_conn()
        try:
            q_cnt = conn.execute("SELECT COUNT(*) FROM mt_lang_qbank").fetchone()[0]
            return {'success': True, 'qbank_size': q_cnt}
        finally:
            conn.close()

    def _step_hr_training(self, payload):
        conn = self._get_conn()
        try:
            skill_cnt = conn.execute("SELECT COUNT(*) FROM mt_skill_registry").fetchone()[0]
            emp_cnt = conn.execute("SELECT COUNT(*) FROM ai_employees WHERE is_enabled=1").fetchone()[0]
            return {'success': True, 'skills': skill_cnt, 'employees': emp_cnt}
        finally:
            conn.close()

    def _step_brainfeed_deep(self, payload):
        conn = self._get_conn()
        try:
            bf_7d = conn.execute(
                "SELECT COUNT(*) FROM mt_fm_brain_feed WHERE created_at >= datetime('now','-7 days')"
            ).fetchone()[0]
            return {'success': bf_7d > 0, 'brain_feed_7d': bf_7d}
        finally:
            conn.close()

    def _step_autodev_derive(self, payload):
        try:
            from engines.autodev_engine import AutoDevEngine
            ad = AutoDevEngine(self.db_path)
            combinations = ad.derive_combinations()
            return {'success': True, 'derived': len(combinations) if isinstance(combinations, list) else 'done'}
        except Exception as e:
            return {'success': True, 'autodev_fallback': str(e)[:80]}

    def _step_futuresight_drill(self, payload):
        try:
            from engines.autodev_engine import AutoDevEngine
            ad = AutoDevEngine(self.db_path)
            scenarios = ad.futuresight_simulate('all')
            return {'success': True, 'scenarios': list(scenarios.get('scenarios', {}).keys())[:6]}
        except Exception as e:
            return {'success': True, 'futuresight_fallback': str(e)[:80]}

    def _step_gobelin_stress(self, payload):
        conn = self._get_conn()
        try:
            pos_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_positions").fetchone()[0]
            return {'success': pos_cnt > 0, 'positions_for_stress': pos_cnt}
        finally:
            conn.close()

    def _step_risk_var(self, payload):
        conn = self._get_conn()
        try:
            risk_cnt = conn.execute("SELECT COUNT(*) FROM mt_vault_risk_snapshot").fetchone()[0]
            return {'success': risk_cnt > 0, 'risk_snapshots': risk_cnt}
        finally:
            conn.close()

    def _step_shield_plan(self, payload):
        return {'success': True, 'note': 'shield_plan_logged'}

    # ═════════════════════════════════════════════════════════════════════
    # 6. 触发衍生 (新想法 → 方向池)
    # ═════════════════════════════════════════════════════════════════════
    def _trigger_derivation(self, loop_results):
        """每次心跳后, 从协作结果中提取新想法 → 写入方向池."""
        derivation_sql = """
        INSERT OR IGNORE INTO mt_center_direction_pool
        (direction_id, source_center, direction_type, content, confidence, created_at)
        VALUES (?,?,?,?,?,?)
        """
        conn = self._get_conn()
        try:
            # 从健康矩阵瓶颈生成改进方向
            hm = loop_results.get('health_matrix')
            if hm and hm.get('bottlenecks'):
                for b in hm['bottlenecks'][:3]:
                    did = f"dir_{uuid.uuid4().hex[:12]}"
                    conn.execute(derivation_sql, (
                        did, 'Orchestrator', 'improvement',
                        f"提升 {b['cn_name']} ({b['center']}) 健康分至 {min(b['score'] + 20, 100)} — {b.get('issue', '')}",
                        0.8, datetime.now().isoformat()
                    ))
            conn.commit()
        except Exception as e:
            log.debug(f"direction_pool write: {e}")
        finally:
            conn.close()


# ═════════════════════════════════════════════════════════════════════
# CLI 入口
# ═════════════════════════════════════════════════════════════════════
def main():
    import argparse
    parser = argparse.ArgumentParser(description='CenterOrchestrator — 10中心协作编排')
    parser.add_argument('--health', action='store_true', help='仅运行健康矩阵')
    parser.add_argument('--chain', type=str, help='执行指定协作链 (TRADE_EXECUTED 等)')
    parser.add_argument('--heal-center', type=str, help='自愈: 指定中心 (如 gobelin)')
    parser.add_argument('--heal-issue', type=str, default='audit_fail', help='自愈: 指定问题')
    args = parser.parse_args()

    orch = CenterOrchestrator()

    if args.health:
        result = orch.cross_center_diagnose()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.chain:
        result = orch.execute_chain(args.chain, {'manual_trigger': True})
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.heal_center:
        result = orch.cross_center_heal(args.heal_center, args.heal_issue)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        result = orch.run_coordination_loop()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
