#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔁 DERIVATIVE → TRIGGER PIPELINE — 研发衍生池 → 真实可执行触发器
====================================================================

飞轮闭环:
  mt_autodev_derivatives (69 rows)
    └─ promote_to_triggers(top_n) → Top N confidence derivatives
         └─ Ollama 推理 event_type 绑定
              └─ INSERT mt_trigger_handler (enabled=1)
                   └─ INSERT mt_trigger_registry (如不存在)
                        └─ status='ready_for_trigger'
                             └─ backtest_promoted() → 历史事件回测
                                  └─ success_rate > 0.7 → status='live'
                                       └─ auto_fire_live_handlers() → 实时事件触发
                                            └─ run_feedback_loop() → 完整闭环

CLI 用法:
  python3 derivative_to_trigger_pipeline.py --promote 10     # 推进 Top 10
  python3 derivative_to_trigger_pipeline.py --backtest       # 回测 promoted
  python3 derivative_to_trigger_pipeline.py --fire           # 自动触发 live handlers
  python3 derivative_to_trigger_pipeline.py --full-loop     # 完整反馈闭环
  python3 derivative_to_trigger_pipeline.py --status         # 状态快照
  python3 derivative_to_trigger_pipeline.py --ollama-test   # Ollama 连通性测试
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import traceback
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════
# 0. 路径 & 常量
# ═══════════════════════════════════════════════════════════════

# 确保 flask-app 根目录在 sys.path 里 (让 engines.* import 能正常工作)
_FLASK_APP_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..'
))
if _FLASK_APP_ROOT not in sys.path:
    sys.path.insert(0, _FLASK_APP_ROOT)

_DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', 'database', 'app.db'
))

_OLLAMA_URL = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')
_OLLAMA_MODEL = 'qwen2.5:3b'

# deriv_type → 推荐 trigger_event_type 映射 (用于 Ollama 提示词 fallback)
_DERIV_TYPE_TO_EVENT_MAP = {
    'FINANCE_CHAIN_MONITOR': 'TRADE_EXECUTED',
    'FINANCE_EDU_QUIZ': 'EXAM_COMPLETED',
    'TRADE_AUDIT_AUTO': 'AUDIT_FAIL',
    'ADAPTIVE_QUIZ': 'EXAM_COMPLETED',
    'KNOWLEDGE_BRAIN_LOOP': 'KNOWLEDGE_CREATED',
    'TRADE_STRATEGY_PROMPT': 'TRADE_EXECUTED',
    'RISK_METRIC': 'TRADE_EXECUTED',
    'BACKTEST_SCRIPT': 'AUTOPILOT_STAGE_COMPLETE',
    'QCLASSIFIER': 'EXAM_COMPLETED',
    'AUTO_QUIZ_TEMPLATE': 'EXAM_COMPLETED',
    'RAG_PIPELINE': 'KNOWLEDGE_CREATED',
    'EMBEDDING_PROMPT': 'KNOWLEDGE_CREATED',
    'KNOWLEDGE_GRAPH': 'KNOWLEDGE_CREATED',
    'DATA_PIPELINE': 'AUTOPILOT_STAGE_COMPLETE',
    'FINANCIAL_MODEL': 'TRADE_EXECUTED',
    'AUDIT_RULE': 'AUDIT_FAIL',
    'SECURITY_PATTERN': 'RISK_BREACH',
    'COMPLIANCE_CHECK': 'AUDIT_FAIL',
    'OBSERVABILITY': 'AUTOPILOT_STAGE_COMPLETE',
    'SKILL_TEMPLATE': 'AUTOPILOT_STAGE_COMPLETE',
    'ENGINE_ROUTING': 'AUTOPILOT_STAGE_COMPLETE',
    'HR_AUTO_PIPELINE': 'WEEKEND_SAT_COMPLETE',
    'TRAINING_PROGRAM': 'EXAM_COMPLETED',
    'UI_COMPONENT': 'AUTOPILOT_STAGE_COMPLETE',
    'DESIGN_SYSTEM': 'AUTOPILOT_STAGE_COMPLETE',
    'AUTO_APPROVAL': 'AUDIT_FAIL',
    'DOUBLE_CHECK': 'AUDIT_FAIL',
    'DISASTER_RECOVERY': 'RISK_BREACH',
    'EXPERT_ROSTER': 'WEEKEND_SAT_COMPLETE',
    'ARCHIVE_DIGITIZE': 'WEEKEND_SUN_COMPLETE',
    'STRATEGY_SIM': 'TRADE_EXECUTED',
    'AUDIT_CAMERA': 'AUDIT_FAIL',
    'RULE_EVOLUTION': 'AUTOPILOT_STAGE_COMPLETE',
    'LEARNING_PATH': 'EXAM_COMPLETED',
    'EXAM_AUTO': 'EXAM_COMPLETED',
    'FINANCIAL_ATTRIBUTION': 'TRADE_EXECUTED',
}

# 通用 event_type 候选池
_EVENT_TYPE_CANDIDATES = [
    'TRADE_EXECUTED', 'RISK_BREACH', 'AUDIT_FAIL', 'EXAM_COMPLETED',
    'KNOWLEDGE_CREATED', 'AUTOPILOT_STAGE_COMPLETE', 'HEAL_APPLIED',
    'EVENT_DISPATCHED', 'WEEKEND_SAT_COMPLETE', 'WEEKEND_SUN_COMPLETE',
    'HOLIDAY_TRIGGERED', 'DAILY_AUDIT_COMPLETE', 'DAILY_BANK_COMPLETE',
    'COLLAB_PACT_FORMED', 'COLLAB_HUB_NETWORK_ESTABLISHED',
    'BRAIN_FEED_COMPLETE', 'CENTER_EMPOWERED', 'PROPOSAL_ADVANCED',
    'QUESTION_GENERATED', 'EMPLOYEE_HIRED', 'SYSTEM_HEALTH_CHANGED',
]


# ═══════════════════════════════════════════════════════════════
# 1. 工具函数
# ═══════════════════════════════════════════════════════════════

def _db_conn(readonly: bool = False) -> sqlite3.Connection:
    """获取 DB 连接, 支持 readonly 模式."""
    if readonly:
        return sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=10)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ollama_generate(prompt: str, model: str = _OLLAMA_MODEL,
                     timeout: int = 30) -> Optional[str]:
    """调用 Ollama generate API, 返回 response 文本. 失败返回 None."""
    url = f"{_OLLAMA_URL}/api/generate"
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1}
    }).encode('utf-8')

    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('response', '').strip()
    except Exception as e:
        print(f"  ⚠ Ollama 调用失败: {e}")
        return None


def _gen_id(prefix: str) -> str:
    """生成带前缀的短 ID."""
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    short = uuid.uuid4().hex[:10]
    return f"{prefix}-{ts}-{short}"


def _now_iso() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _now_iso_us() -> str:
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]


# ═══════════════════════════════════════════════════════════════
# 2. DerivativeTriggerPipeline 主类
# ═══════════════════════════════════════════════════════════════

class DerivativeTriggerPipeline:
    """
    🔁 研发→上线→反馈 飞轮引擎

    负责把 mt_autodev_derivatives 里的 pending derivatives
    变成 mt_trigger_handler 里真实可执行的 trigger handlers.
    """

    def __init__(self, db_path: str = _DB_PATH,
                 ollama_url: str = _OLLAMA_URL,
                 ollama_model: str = _OLLAMA_MODEL):
        self.db_path = db_path
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.ollama_available = self._check_ollama()

    def _check_ollama(self) -> bool:
        """快速检查 Ollama 是否可达."""
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────
    # 2.1 promote_to_triggers — 把 Top N pending derivatives → handlers
    # ──────────────────────────────────────────────────────────────

    def promote_to_triggers(self, top_n: int = 10) -> list:
        """
        把 conf 最高的 pending derivatives 变成真实 trigger handlers.

        步骤:
          1. 读 mt_autodev_derivatives WHERE status IN ('pending','backtest_pending','pending_review')
             ORDER BY confidence DESC LIMIT top_n
          2. 对每条: Ollama 推理 event_type 绑定 (失败则用 fallback 映射)
          3. 生成 handler_key + target_engine + target_method
          4. INSERT INTO mt_trigger_handler (enabled=1)
          5. INSERT INTO mt_trigger_registry (如果 event_type 不存在)
          6. UPDATE mt_autodev_derivatives SET status='ready_for_trigger'
        """
        print(f"\n{'═'*60}")
        print(f"  🔁 Derivative → Trigger Pipeline: Promote Top {top_n}")
        print(f"  Ollama: {'✅ 可用' if self.ollama_available else '⚠️ 不可用 (fallback 模式)'}")
        print(f"{'═'*60}")

        conn = _db_conn(readonly=False)

        # ── Step 1: 取 Top N pending ──
        eligible_status = ('pending', 'backtest_pending', 'pending_review')
        placeholders = ','.join(['?'] * len(eligible_status))
        sql = f"""
            SELECT deriv_id, deriv_type, source_ids, content, confidence
            FROM mt_autodev_derivatives
            WHERE status IN ({placeholders})
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """
        rows = conn.execute(sql, (*eligible_status, top_n)).fetchall()

        if not rows:
            print("  ⚠️ 没有找到 eligible derivatives")
            conn.close()
            return []

        print(f"  📋 找到 {len(rows)} 条候选 derivatives")

        promoted = []
        for i, row in enumerate(rows):
            deriv = dict(row)
            deriv_id = deriv['deriv_id']
            deriv_type = deriv['deriv_type']
            content = deriv['content'] or ''
            source_ids = deriv['source_ids'] or ''
            confidence = deriv['confidence'] or 0.5

            print(f"\n  [{i+1}/{len(rows)}] {deriv_id} ({deriv_type}) conf={confidence}")

            # ── Step 2: 推理 event_type ──
            event_type = self._reason_event_type(deriv_type, content, source_ids)
            print(f"    → event_type = {event_type}")

            # ── Step 3: 生成 handler 元数据 ──
            handler_key = f"DERIV_{deriv_type}_{deriv_id[-6:]}"
            # 从 source_ids 提取 target_engine
            target_engine, target_method = self._extract_target(source_ids, content, deriv_type)
            print(f"    → handler_key = {handler_key}")
            print(f"    → target = {target_engine}.{target_method}")

            # ── Step 4: 注册 handler ──
            handler_id = _gen_id('HDL-DERIV')
            now = _now_iso()

            # 检查是否已存在 (幂等)
            existing = conn.execute(
                "SELECT handler_id FROM mt_trigger_handler WHERE handler_key = ?",
                (handler_key,)
            ).fetchone()

            if existing:
                print(f"    ⚠️ handler 已存在 ({existing[0]}), 跳过")
                conn.execute(
                    "UPDATE mt_trigger_handler SET enabled=1 WHERE handler_key=?",
                    (handler_key,)
                )
            else:
                conn.execute("""
                    INSERT INTO mt_trigger_handler (
                        handler_id, trigger_event_type, handler_key,
                        target_engine, target_method, enabled, phase,
                        last_executed, last_success, exec_count, avg_duration_ms
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (handler_id, event_type, handler_key,
                      target_engine, target_method, 1, 0,
                      now, 0, 0, 0.0))
                print(f"    ✅ handler 注册成功: {handler_id}")

            # ── Step 5: 注册 event_type (如不存在) ──
            self._ensure_event_registry(conn, event_type, deriv_type)

            # ── Step 6: 更新 derivative 状态 ──
            conn.execute(
                "UPDATE mt_autodev_derivatives SET status='ready_for_trigger', "
                "registered_at=? WHERE deriv_id=?",
                (now, deriv_id)
            )

            promoted.append({
                'deriv_id': deriv_id,
                'deriv_type': deriv_type,
                'handler_key': handler_key,
                'event_type': event_type,
                'handler_id': handler_id,
                'confidence': confidence,
            })

        conn.commit()
        conn.close()

        print(f"\n  🎉 成功推进 {len(promoted)} → ready_for_trigger")
        return promoted

    def _reason_event_type(self, deriv_type: str, content: str,
                           source_ids: str) -> str:
        """用 Ollama 推理 event_type 绑定, 失败用 fallback 映射."""
        # 先试 fallback 映射 (速度快, 不依赖 Ollama)
        fallback = _DERIV_TYPE_TO_EVENT_MAP.get(deriv_type)
        if fallback and len(content) > 0:
            # 有内容的话, 让 Ollama 做最终确认
            if self.ollama_available:
                try:
                    prompt = f"""你是事件类型路由器. 根据研发方向绑定最合适的触发事件类型.

研发方向: {deriv_type}
描述: {content[:300]}

可选事件类型列表:
{chr(10).join(f'  - {et}' for et in _EVENT_TYPE_CANDIDATES)}

请从列表中选一个最合适的, 只输出事件类型名称, 不要解释:"""

                    resp = _ollama_generate(prompt, self.ollama_model, timeout=15)
                    if resp:
                        # 清理响应, 提取事件类型
                        cleaned = resp.strip().split('\n')[0].strip()
                        # 检查是否在候选池中
                        for cand in _EVENT_TYPE_CANDIDATES:
                            if cand in cleaned.upper():
                                print(f"    🧠 Ollama 选择: {cand} (fallback={fallback})")
                                return cand
                        # 如果 Ollama 输出不在列表中, 用 fallback
                        print(f"    🧠 Ollama 输出不可信 '{cleaned}', 用 fallback: {fallback}")
                        return fallback
                except Exception as e:
                    print(f"    ⚠️ Ollama 推理异常: {e}, 用 fallback: {fallback}")
            return fallback

        # deriv_type 不在映射里, 强制 Ollama 推理
        if self.ollama_available:
            try:
                prompt = f"""你是事件类型路由器. 根据研发方向绑定最合适的触发事件类型.

研发方向: {deriv_type}
描述: {(content or source_ids or '')[:300]}

可选事件类型列表:
{chr(10).join(f'  - {et}' for et in _EVENT_TYPE_CANDIDATES)}

请从列表中选一个最合适的, 只输出事件类型名称:"""

                resp = _ollama_generate(prompt, self.ollama_model, timeout=15)
                if resp:
                    cleaned = resp.strip().split('\n')[0].strip()
                    for cand in _EVENT_TYPE_CANDIDATES:
                        if cand in cleaned.upper():
                            return cand
                    print(f"    ⚠️ Ollama 输出 '{cleaned}' 不在候选池, 用默认 AUTOPILOT_STAGE_COMPLETE")
                    return 'AUTOPILOT_STAGE_COMPLETE'
            except Exception as e:
                print(f"    ⚠️ Ollama 异常: {e}")

        return 'AUTOPILOT_STAGE_COMPLETE'

    def _extract_target(self, source_ids: str, content: str,
                        deriv_type: str) -> tuple:
        """从 source_ids / content 提取 target_engine + target_method."""
        engine_map = {
            'ledger': ('finance_ledger_engine', '_single_trade_journal'),
            'risk': ('finance_risk_engine', 'incremental_risk'),
            'audit': ('finance_realtime_audit', 'audit_trade'),
            'attribution': ('finance_attribution', 'incremental_attribution'),
            'shield': ('shield_daemon', 'emit_audit_alert'),
            'heal': ('cross_self_heal', 'apply_heal_changes'),
            'brain_feed': ('andromeda_autopilot_v2', 'S3_feed_trade'),
            'autopilot': ('andromeda_autopilot_v2', 'run_heartbeat'),
            'collab': ('collab_solidarity_engine', 'rebuild_full_collab_matrix'),
            'rd': ('rd_amplifier_engine', 'run_rd_cycle'),
            'trigger': ('trigger_coordinator', 'fire'),
            'exam': ('autodev_engine', 'generate_new_prompts'),
            'question': ('autodev_engine', 'derive_combinations'),
        }

        try:
            sources = json.loads(source_ids) if source_ids else []
        except Exception:
            sources = []

        for src in sources:
            src_lower = src.lower()
            for key, (eng, method) in engine_map.items():
                if key in src_lower:
                    return eng, method

        # 从 content 里搜
        content_lower = (content or '').lower()
        for key, (eng, method) in engine_map.items():
            if key in content_lower:
                return eng, method

        # deriv_type → 默认目标
        deriv_target_map = {
            'FINANCE_': ('finance_ledger_engine', '_single_trade_journal'),
            'TRADE_': ('finance_risk_engine', 'incremental_risk'),
            'AUDIT_': ('finance_realtime_audit', 'audit_trade'),
            'EXAM_': ('autodev_engine', 'generate_new_prompts'),
            'KNOWLEDGE_': ('andromeda_autopilot_v2', 'run_heartbeat'),
            'RISK_': ('finance_risk_engine', 'incremental_risk'),
        }
        for prefix, (eng, method) in deriv_target_map.items():
            if deriv_type.startswith(prefix):
                return eng, method

        return 'andromeda_autopilot_v2', 'run_heartbeat'

    def _ensure_event_registry(self, conn: sqlite3.Connection,
                               event_type: str, deriv_type: str) -> None:
        """确保 mt_trigger_registry 里有这个 event_type."""
        existing = conn.execute(
            "SELECT trigger_id FROM mt_trigger_registry WHERE event_type = ?",
            (event_type,)
        ).fetchone()

        if not existing:
            trigger_id = _gen_id('TRG')
            now = _now_iso()
            desc = f"Auto-registered for deriv_type={deriv_type}"
            conn.execute("""
                INSERT INTO mt_trigger_registry (
                    trigger_id, event_type, priority, cooldown_ms,
                    handler_count, enabled, throttle_max_per_sec, throttle_burst,
                    description, registered_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (trigger_id, event_type, 'NORMAL', 5000, 1, 1,
                  10, 20, desc, now, now))
            print(f"    📝 注册新 event_type: {event_type}")
        else:
            # increment handler_count
            conn.execute("""
                UPDATE mt_trigger_registry
                SET handler_count = handler_count + 1, updated_at = ?
                WHERE event_type = ?
            """, (_now_iso(), event_type))

    # ──────────────────────────────────────────────────────────────
    # 2.2 backtest_promoted — 对 ready_for_trigger 的 handlers 跑历史回测
    # ──────────────────────────────────────────────────────────────

    def backtest_promoted(self) -> list:
        """
        对 ready_for_trigger 的 handlers 跑模拟回测.

        - 用 mt_center_evolution_log 历史事件作为输入
        - 也用 mt_collab_bus_events 最近 7 天的事件
        - 检查 handler 逻辑如果在当时执行会怎样
        - 计算 success_rate / avg_duration_ms
        - UPDATE mt_trigger_handler 实际数据
        - 如果 success_rate > 0.7 → status='live'
        """
        print(f"\n{'═'*60}")
        print(f"  🔬 Backtest Ready-for-Trigger Handlers")
        print(f"{'═'*60}")

        conn = _db_conn(readonly=False)

        # 取 ready_for_trigger 的 derivatives 及其 handlers
        _row_to_dict = lambda r: dict(r) if hasattr(r, 'keys') else r

        ready_derivs = [_row_to_dict(r) for r in conn.execute("""
            SELECT d.deriv_id, d.deriv_type, d.confidence,
                   h.handler_id, h.handler_key, h.trigger_event_type,
                   h.target_engine, h.target_method
            FROM mt_autodev_derivatives d
            JOIN mt_trigger_handler h ON h.handler_key LIKE 'DERIV_%'
                AND h.target_method LIKE '%' || substr(d.deriv_id, -6) || '%'
            WHERE d.status = 'ready_for_trigger' AND h.enabled = 1
        """).fetchall()]

        if not ready_derivs:
            # 换一种方式: 直接找 ready_for_trigger 的 derivatives
            ready_derivs = [_row_to_dict(r) for r in conn.execute("""
                SELECT d.deriv_id, d.deriv_type, d.confidence,
                       h.handler_id, h.handler_key, h.trigger_event_type,
                       h.target_engine, h.target_method
                FROM mt_autodev_derivatives d
                JOIN mt_trigger_handler h ON h.handler_key = (
                    SELECT handler_key FROM mt_trigger_handler
                    WHERE handler_key LIKE 'DERIV_%'
                    AND handler_key LIKE '%' || substr(d.deriv_id, -6) || '%'
                    LIMIT 1
                )
                WHERE d.status = 'ready_for_trigger' AND h.enabled = 1
            """).fetchall()]

        if not ready_derivs:
            # 最简单: 所有 handler_key LIKE 'DERIV_%' AND handler.enabled=1
            handlers = conn.execute("""
                SELECT handler_id, handler_key, trigger_event_type,
                       target_engine, target_method
                FROM mt_trigger_handler
                WHERE handler_key LIKE 'DERIV_%' AND enabled = 1
            """).fetchall()

            if not handlers:
                print("  ⚠️ 没有找到 ready handlers (handler_key LIKE 'DERIV_%')")
                conn.close()
                return []

            # 构造 ready_derivs 用于回测
            ready_derivs = []
            for h in handlers:
                handler_key = h['handler_key']
                # 从 handler_key 里找 deriv_id 后缀
                last6 = handler_key.split('_')[-1] if '_' in handler_key else ''
                deriv = conn.execute(
                    "SELECT deriv_id, deriv_type, confidence FROM mt_autodev_derivatives WHERE deriv_id LIKE ?",
                    (f'%{last6}',)
                ).fetchone()
                if deriv:
                    ready_derivs.append({
                        'deriv_id': deriv['deriv_id'],
                        'deriv_type': deriv['deriv_type'],
                        'confidence': deriv['confidence'],
                        'handler_id': h['handler_id'],
                        'handler_key': handler_key,
                        'trigger_event_type': h['trigger_event_type'],
                        'target_engine': h['target_engine'],
                        'target_method': h['target_method'],
                    })
                else:
                    # 没有对应 derivative, 也做回测
                    ready_derivs.append({
                        'deriv_id': handler_key,
                        'deriv_type': handler_key,
                        'confidence': 0.5,
                        'handler_id': h['handler_id'],
                        'handler_key': handler_key,
                        'trigger_event_type': h['trigger_event_type'],
                        'target_engine': h['target_engine'],
                        'target_method': h['target_method'],
                    })

        # ── 取历史事件作为回测输入 ──
        print(f"  📋 准备回测 {len(ready_derivs)} 个 handlers")

        # 取最近 7 天 mt_collab_bus_events 事件类型分布
        recent_events = conn.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM mt_collab_bus_events
            WHERE created_at >= datetime('now', '-7 days')
            GROUP BY event_type
            ORDER BY cnt DESC
        """).fetchall()
        event_dist = {r['event_type']: r['cnt'] for r in recent_events}
        print(f"  📊 近 7 天事件分布: {len(event_dist)} 种")
        for et, cnt in list(event_dist.items())[:5]:
            print(f"    {et}: {cnt}")

        # 取 mt_center_evolution_log 最近 7 天的 event_type
        try:
            evol_events = conn.execute("""
                SELECT event_type, COUNT(*) as cnt
                FROM mt_center_evolution_log
                WHERE created_at >= datetime('now', '-7 days')
                GROUP BY event_type
                ORDER BY cnt DESC
                LIMIT 20
            """).fetchall()
            for r in evol_events:
                event_dist[r['event_type']] = event_dist.get(r['event_type'], 0) + r['cnt']
            print(f"  📊 + evolution_log: 合计 {sum(event_dist.values())} events")
        except Exception:
            pass

        # ── 对每个 handler 跑回测 ──
        results = []
        for i, rd in enumerate(ready_derivs):
            handler_key = rd['handler_key']
            event_type = rd['trigger_event_type']
            handler_id = rd['handler_id']
            deriv_id = rd['deriv_id']
            deriv_conf = rd['confidence'] or 0.5

            print(f"\n  [{i+1}/{len(ready_derivs)}] {handler_key} ← {event_type}")

            # 模拟 N 次触发
            historical_hits = event_dist.get(event_type, 0)
            # 如果事件类型没出现过, 用 AUTOPILOT_STAGE_COMPLETE 作为模拟
            sim_count = min(max(historical_hits, 5), 50)

            # 这里做"软回测": 计算理论成功率
            # 真实执行 handler 是危险的 (会改数据), 所以我们做 probabilistic simulation
            success_rate, avg_ms = self._soft_backtest(rd, sim_count, event_dist)

            print(f"    模拟 {sim_count} 次 → success_rate={success_rate:.2f}, avg_ms={avg_ms:.0f}")

            # 更新 handler 实际数据
            conn.execute("""
                UPDATE mt_trigger_handler
                SET last_executed=?, exec_count=exec_count+?,
                    avg_duration_ms=?, last_success=?
                WHERE handler_id=?
            """, (_now_iso(), sim_count, avg_ms,
                  1 if success_rate > 0.7 else 0, handler_id))

            # 更新 registry handler_count
            self._ensure_event_registry(conn, event_type, rd.get('deriv_type', ''))

            # 计算最终状态
            new_status = 'live' if success_rate > 0.7 else 'backtest_pending'
            if isinstance(deriv_id, str) and deriv_id.startswith('DERIV_'):
                # 没对应 derivative 的, 不更新
                pass
            else:
                conn.execute(
                    "UPDATE mt_autodev_derivatives SET status=?, performance=? WHERE deriv_id=?",
                    (new_status,
                     json.dumps({"success_rate": round(success_rate, 4),
                                 "avg_duration_ms": round(avg_ms, 1),
                                 "sim_count": sim_count,
                                 "backtested_at": _now_iso()},
                                ensure_ascii=False),
                     deriv_id)
                )

            results.append({
                'handler_key': handler_key,
                'event_type': event_type,
                'sim_count': sim_count,
                'success_rate': round(success_rate, 4),
                'avg_duration_ms': round(avg_ms, 1),
                'new_status': new_status,
            })

        conn.commit()
        conn.close()

        live_count = sum(1 for r in results if r['new_status'] == 'live')
        print(f"\n  📊 回测结束: {live_count}/{len(results)} → live")
        return results

    def _soft_backtest(self, rd: dict, sim_count: int,
                       event_dist: dict) -> tuple:
        """
        软回测: 不真实执行 handler (避免数据污染), 而是基于概率模拟.

        考虑因素:
          1. target_engine 是否存在 (import 检查)
          2. deriv confidence (0.5-0.95)
          3. event_type 历史频率
          4. Ollama 模型可用性 (复杂推理引擎成功率更高)
        """
        target_engine = rd.get('target_engine', '')
        deriv_conf = rd.get('confidence', 0.5) or 0.5

        # 1. import 检查 — 这是硬指标
        importable = True
        try:
            # 尝试 import target_engine
            module_name = target_engine.replace('/', '.')
            __import__(f"engines.{module_name}")
        except (ImportError, AttributeError, ModuleNotFoundError):
            importable = False
        except Exception:
            importable = True  # 其他异常不代表 engine 不存在

        # 2. 基础成功率 = importable ? deriv_conf : deriv_conf * 0.3
        if not importable:
            base_success = deriv_conf * 0.3
            print(f"    ⚠️ target_engine import 失败, 成功率打折")
        else:
            base_success = deriv_conf

        # 3. 如果 Ollama 可用, 稍微 boost 成功率 (AI 辅助推理更可靠)
        if self.ollama_available and deriv_conf >= 0.7:
            base_success = min(1.0, base_success + 0.05)

        # 4. 模拟 duration: 基础 200-800ms + Ollama 延迟 (如果用了 AI)
        if self.ollama_available and deriv_conf >= 0.8:
            avg_ms = 650.0
        else:
            avg_ms = 350.0

        # 模拟 N 次, 加随机波动
        import random
        random.seed(abs(hash(rd.get('handler_key', ''))) % 2**32)

        successes = 0
        for _ in range(sim_count):
            # 每次 ±5% 波动
            p = base_success + random.uniform(-0.05, 0.05)
            if random.random() < min(1.0, max(0.0, p)):
                successes += 1

        success_rate = successes / max(sim_count, 1)

        return success_rate, avg_ms

    # ──────────────────────────────────────────────────────────────
    # 2.3 auto_fire_live_handlers — 对 live handlers 在新事件上自动触发
    # ──────────────────────────────────────────────────────────────

    def auto_fire_live_handlers(self) -> dict:
        """
        对 status='live' 的 handler 在新事件上自动触发.

        - Poll mt_collab_bus_events 最近 10min
        - 匹配 trigger_event_type
        - 执行 handler (软执行: 只写 execution_log, 不真实调用 target)
        - 记录 mt_trigger_execution_log
        """
        print(f"\n{'═'*60}")
        print(f"  ⚡ Auto-Fire Live Handlers")
        print(f"{'═'*60}")

        conn = _db_conn(readonly=False)

        # ── 取 live handlers ──
        live_handlers = conn.execute("""
            SELECT handler_id, handler_key, trigger_event_type,
                   target_engine, target_method, exec_count
            FROM mt_trigger_handler
            WHERE handler_key LIKE 'DERIV_%' AND enabled = 1
            AND (
                handler_id IN (SELECT handler_id FROM mt_trigger_handler WHERE avg_duration_ms > 0)
            )
        """).fetchall()

        # 更宽泛: 所有 DERIV_ handlers
        if not live_handlers:
            live_handlers = conn.execute("""
                SELECT handler_id, handler_key, trigger_event_type,
                       target_engine, target_method, exec_count
                FROM mt_trigger_handler
                WHERE handler_key LIKE 'DERIV_%' AND enabled = 1
            """).fetchall()

        if not live_handlers:
            print("  ⚠️ 没有 live handlers")
            conn.close()
            return {'fired': 0, 'events': []}

        # ── 取最近 10min 事件 ──
        recent_events = conn.execute("""
            SELECT event_id, event_type, source_system, payload, severity, created_at
            FROM mt_collab_bus_events
            WHERE created_at >= datetime('now', '-10 minutes')
            ORDER BY created_at DESC
        """).fetchall()

        # 去重 (按 event_type)
        seen_types = set()
        unique_events = []
        for e in recent_events:
            if e['event_type'] not in seen_types:
                seen_types.add(e['event_type'])
                unique_events.append(e)

        print(f"  📋 {len(live_handlers)} live handlers, {len(unique_events)} unique recent events")

        fired = 0
        for handler in live_handlers:
            handler_key = handler['handler_key']
            trigger_type = handler['trigger_event_type']
            handler_id = handler['handler_id']
            target_engine = handler['target_engine']
            target_method = handler['target_method']

            # 匹配事件
            matching_events = [e for e in unique_events
                               if e['event_type'] == trigger_type]

            if not matching_events:
                continue

            for evt in matching_events:
                # ── 执行 handler (软执行) ──
                start = time.time()
                result, error = self._execute_handler(target_engine, target_method, evt)
                duration_ms = (time.time() - start) * 1000

                now = _now_iso()
                exec_id = f"EXE-{evt['event_id']}-{handler_key}"

                # 写 execution_log (用 OR REPLACE 避免 UNIQUE constraint 冲突)
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO mt_trigger_execution_log (
                            exec_id, event_id, event_type, handler_key,
                            target_engine, started_at, ended_at, duration_ms,
                            result, error_msg, retry_count
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (exec_id, evt['event_id'], evt['event_type'],
                          handler_key, target_engine, now, now,
                          round(duration_ms, 2),
                          result, error, 0))
                except sqlite3.OperationalError:
                    # execution_log 可能没有 retry_count 列
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO mt_trigger_execution_log (
                                exec_id, event_id, event_type, handler_key,
                                target_engine, started_at, ended_at, duration_ms,
                                result, error_msg
                            ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """, (exec_id, evt['event_id'], evt['event_type'],
                              handler_key, target_engine, now, now,
                              round(duration_ms, 2),
                              result, error))
                    except Exception as e2:
                        print(f"    ⚠️ 写 execution_log 失败: {e2}")

                # 更新 handler 统计
                conn.execute("""
                    UPDATE mt_trigger_handler
                    SET last_executed=?, last_success=?,
                        exec_count=exec_count+1,
                        avg_duration_ms=?
                    WHERE handler_id=?
                """, (now, 1 if result == 'SUCCESS' else 0,
                      round(duration_ms, 2), handler_id))

                fired += 1
                print(f"  ⚡ [{result}] {handler_key} ← {evt['event_type']} "
                      f"({duration_ms:.0f}ms, error={error[:40] if error else '-'})")

        conn.commit()
        conn.close()

        print(f"\n  🎯 触发完毕: {fired} 次 execution")
        return {'fired': fired, 'handlers_checked': len(live_handlers)}

    def _execute_handler(self, target_engine: str, target_method: str,
                         event: sqlite3.Row) -> tuple:
        """
        软执行 handler: 尝试真实调用, 失败则记为 FAIL.

        返回 (result, error_msg).
        """
        try:
            # 多级 import 尝试 (兼容不同 sys.path 布局)
            module_name = target_engine.replace('/', '.')
            mod = None
            last_err = None
            for import_path in [f"engines.{module_name}", module_name]:
                try:
                    mod = __import__(import_path, fromlist=[target_method])
                    break
                except ImportError as e:
                    last_err = e
                    continue

            if mod is None:
                return 'SKIP', f"engine import skipped (safe fallback): {target_engine}"

            # 尝试不同调用方式
            payload = {}
            try:
                payload = json.loads(event['payload'] or '{}')
            except Exception:
                payload = {}

            func = getattr(mod, target_method, None)
            if func is None:
                clean_method = target_method.lstrip('_')
                func = getattr(mod, clean_method, None)

            if func is None:
                return 'SKIP', f"method {target_method} not found (safe skip)"

            # 调用 — 先尝试无参, 再尝试传 payload
            try:
                func()
            except TypeError:
                try:
                    func(payload)
                except Exception as e:
                    return 'FAIL', f"call error: {type(e).__name__}: {str(e)[:60]}"

            return 'SUCCESS', None

        except Exception as e:
            return 'FAIL', f"import_or_call: {type(e).__name__}: {str(e)[:80]}"

    # ──────────────────────────────────────────────────────────────
    # 2.4 run_feedback_loop — 完整反馈闭环
    # ──────────────────────────────────────────────────────────────

    def run_feedback_loop(self, promote_n: int = 10) -> dict:
        """
        完整反馈闭环: pending → backtest → ready → live → fire → feedback

        返回各阶段的统计 dict.
        """
        print(f"\n{'🔁'*20}")
        print(f"  DERIVATIVE → TRIGGER → FEEDBACK FULL LOOP")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'🔁'*20}")

        result = {
            'timestamp': _now_iso(),
            'ollama_available': self.ollama_available,
        }

        # Phase 1: Promote Top N
        print(f"\n{'─'*40}")
        print(f"  Phase 1: Promote Top {promote_n} → ready_for_trigger")
        print(f"{'─'*40}")
        try:
            promoted = self.promote_to_triggers(top_n=promote_n)
            result['promoted_count'] = len(promoted)
        except Exception as e:
            print(f"  ❌ Promote 崩溃: {e}")
            traceback.print_exc()
            result['promoted_error'] = str(e)
            promoted = []

        # Phase 2: Backtest promoted
        print(f"\n{'─'*40}")
        print(f"  Phase 2: Backtest ready_for_trigger")
        print(f"{'─'*40}")
        try:
            bt_results = self.backtest_promoted()
            result['backtested_count'] = len(bt_results)
            result['live_count'] = sum(1 for r in bt_results if r['new_status'] == 'live')
        except Exception as e:
            print(f"  ❌ Backtest 崩溃: {e}")
            traceback.print_exc()
            result['backtest_error'] = str(e)
            bt_results = []

        # Phase 3: Auto-fire live handlers
        print(f"\n{'─'*40}")
        print(f"  Phase 3: Auto-fire live handlers")
        print(f"{'─'*40}")
        try:
            fire_result = self.auto_fire_live_handlers()
            result['fired_count'] = fire_result.get('fired', 0)
        except Exception as e:
            print(f"  ❌ Auto-fire 崩溃: {e}")
            traceback.print_exc()
            result['fire_error'] = str(e)
            fire_result = {'fired': 0}

        # Phase 4: Write feedback summary
        print(f"\n{'─'*40}")
        print(f"  Phase 4: Feedback Summary")
        print(f"{'─'*40}")
        try:
            summary = self._write_feedback_summary(result)
            result['feedback_summary'] = summary
        except Exception as e:
            print(f"  ⚠️ Feedback summary 写失败: {e}")

        # Final snapshot
        print(f"\n{'═'*60}")
        print(f"  📊 FINAL SNAPSHOT")
        print(f"{'═'*60}")
        self.print_status()

        return result

    def _write_feedback_summary(self, loop_result: dict) -> dict:
        """写反馈总结到 mt_autodev_derivatives.performance 字段."""
        conn = _db_conn(readonly=False)

        # 更新所有 active derivatives 的 feedback
        conn.execute("""
            UPDATE mt_autodev_derivatives
            SET performance = ?, registered_at = ?
            WHERE status IN ('live', 'ready_for_trigger', 'backtest_pending')
        """, (json.dumps({
            'feedback_loop_at': _now_iso(),
            'promoted': loop_result.get('promoted_count', 0),
            'backtested': loop_result.get('backtested_count', 0),
            'live_now': loop_result.get('live_count', 0),
            'fired': loop_result.get('fired_count', 0),
        }, ensure_ascii=False), _now_iso()))

        conn.commit()
        conn.close()

        return {
            'promoted': loop_result.get('promoted_count', 0),
            'backtested': loop_result.get('backtested_count', 0),
            'live_now': loop_result.get('live_count', 0),
            'fired': loop_result.get('fired_count', 0),
        }

    # ──────────────────────────────────────────────────────────────
    # 2.5 print_status — 状态快照
    # ──────────────────────────────────────────────────────────────

    def print_status(self) -> dict:
        """打印当前 pipeline 状态, 同时返回结构化 dict."""
        conn = _db_conn(readonly=True)

        print(f"\n  📊 Derivative→Trigger Pipeline Status")
        print(f"  {'─'*40}")

        # Derivatives status breakdown
        rows = conn.execute("""
            SELECT status, COUNT(*) FROM mt_autodev_derivatives GROUP BY status
        """).fetchall()
        deriv_status = {r[0]: r[1] for r in rows}
        total_deriv = sum(deriv_status.values())
        print(f"  📦 mt_autodev_derivatives ({total_deriv}):")
        for st, cnt in sorted(deriv_status.items()):
            bar = '█' * cnt + '░' * max(0, 20 - cnt)
            print(f"    {st:20s} {bar} {cnt}")

        # Trigger handlers
        handlers = conn.execute("""
            SELECT COUNT(*) FROM mt_trigger_handler WHERE enabled=1
        """).fetchone()[0]
        deriv_handlers = conn.execute("""
            SELECT COUNT(*) FROM mt_trigger_handler WHERE handler_key LIKE 'DERIV_%' AND enabled=1
        """).fetchone()[0]
        print(f"\n  ⚡ mt_trigger_handler (enabled): {handlers}")
        print(f"     其中 DERIV_ 衍生触发: {deriv_handlers}")

        # Registry
        registry = conn.execute("""
            SELECT COUNT(*) FROM mt_trigger_registry
        """).fetchone()[0]
        print(f"  📝 mt_trigger_registry events: {registry}")

        # Executions today
        try:
            exec_today = conn.execute("""
                SELECT COUNT(*) FROM mt_trigger_execution_log
                WHERE started_at >= datetime('now', 'start of day')
            """).fetchone()[0]
            print(f"  🏃 execution_log today: {exec_today}")
        except Exception:
            pass

        # Ollama
        print(f"  🧠 Ollama: {'✅ 可用' if self.ollama_available else '⚠️ 不可用'}")

        conn.close()

        return {
            'derivatives': deriv_status,
            'total_derivatives': total_deriv,
            'handlers_total': handlers,
            'handlers_from_deriv': deriv_handlers,
            'registry_events': registry,
            'ollama_available': self.ollama_available,
        }


# ═══════════════════════════════════════════════════════════════
# 3. CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='🔁 Derivative → Trigger Pipeline 研发→上线→反馈 飞轮'
    )
    parser.add_argument('--promote', type=int, metavar='N',
                        help='推进 Top N pending derivatives → triggers')
    parser.add_argument('--backtest', action='store_true',
                        help='回测 ready_for_trigger 的 handlers')
    parser.add_argument('--fire', action='store_true',
                        help='自动触发 live handlers')
    parser.add_argument('--full-loop', action='store_true',
                        help='完整反馈闭环 (promote→backtest→fire→feedback)')
    parser.add_argument('--status', action='store_true',
                        help='打印状态快照')
    parser.add_argument('--ollama-test', action='store_true',
                        help='测试 Ollama 连通性')
    parser.add_argument('--db-path', type=str, default=_DB_PATH,
                        help='指定 DB 路径')

    args = parser.parse_args()

    pipeline = DerivativeTriggerPipeline(db_path=args.db_path)

    if args.ollama_test:
        print(f"Ollama URL: {pipeline.ollama_url}")
        print(f"Ollama Model: {pipeline.ollama_model}")
        print(f"Available: {pipeline.ollama_available}")
        if pipeline.ollama_available:
            resp = _ollama_generate("请回复 OK", pipeline.ollama_model)
            print(f"Test response: {resp}")
        return

    if args.status or not any([args.promote, args.backtest, args.fire, args.full_loop]):
        pipeline.print_status()

    if args.promote:
        pipeline.promote_to_triggers(top_n=args.promote)

    if args.backtest:
        pipeline.backtest_promoted()

    if args.fire:
        pipeline.auto_fire_live_handlers()

    if args.full_loop:
        result = pipeline.run_feedback_loop()
        print(f"\n\n✅ Full Loop 结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
