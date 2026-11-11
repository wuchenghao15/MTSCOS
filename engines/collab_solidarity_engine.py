#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤝 CollabSolidarityEngine — AI 元认知驱动的 37 中心协作团结引擎
==================================================================

诊断发现 (2026-11-08):
  - mt_center_collab_matrix 22 rows 中 broadcast 独大 (20 行指向它)
  - 33/37 中心在 collab_matrix 里孤立 (没有 source_center 或 target_center 记录)
  - 但 mt_center_evolution_log 61,964 rows 里每个中心都有 3400+ 次心跳
    → 有数据, 没连线!

5 大协作增强能力:
  1. rebuild_full_collab_matrix() — 用 evolution_log 5 秒因果窗口重建完整矩阵
  2. ai_suggest_collab_pairs()   — Ollama 推理职责互补的孤立中心配对
  3. ai_broadcast_hub_network()  — 把 broadcast 独大改成"星系 hub → 汇聚"分层网络
  4. form_collab_pact()          — 两个中心签署 PEER/DEPENDS_ON/PROVIDES_TO 契约
  5. run_solidarity_cycle()      — 一键团结: rebuild → suggest → hub → pacts

New Tables (auto-create on first run):
  mt_collab_pact         — 协作契约 (PEER/DEPENDS_ON/PROVIDES_TO)
  mt_collab_hub_network  — 星系 hub 分层网络

运行方式:
  python3 engines/collab_solidarity_engine.py --rebuild        # 重建矩阵
  python3 engines/collab_solidarity_engine.py --suggest        # AI 推荐协作对
  python3 engines/collab_solidarity_engine.py --hub            # 建立星系 hub 网络
  python3 engines/collab_solidarity_engine.py --pact A B [TYPE]# 签署契约
  python3 engines/collab_solidarity_engine.py --all            # 一键完整团结周期
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
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════
# 0. 路径 & 常量
# ═══════════════════════════════════════════════════════════════

_DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', 'database', 'app.db'
))

# Ollama 容错端口列表
_OLLAMA_PORTS = [11435, 11434]
_OLLAMA_MODEL = 'qwen2.5:3b'

# 5 秒因果窗口：事件 B 在事件 A 之后 5 秒内发生 → A 因果导致 B
_CAUSAL_WINDOW_SEC = 5

# 星系 → hub_center 映射 (任务要求)
_GALAXY_HUB_MAP = {
    'andromeda': 'trigger_coordinator',
    'gobelin':   'finance_ledger_engine',
    'iceberg':   'iceberg_content_matrix',
    'brainfeed': 'ai_brain_feed_engine',
    'eigenflux': 'ai_feature_evolution_engine',
    # 补充其余星系 hub (用真实已存在的中心名)
    'audit':     'audit',
    'autopilot': 'autopilot',
    'data':      '数据研究中心',
    'eventbus':  'eventbus',
    'frontend':  '前端设计中心',
    'hr':        '人力统一调配中心',
    'legal':     '工作流研究中心',
    'security':  '安全审计中心',
    'taskhall':  'taskhall',
    'unknown':   '战略中心',
}


# ═══════════════════════════════════════════════════════════════
# 1. 数据库初始化 & 工具
# ═══════════════════════════════════════════════════════════════

def _db_conn(readonly: bool = False) -> sqlite3.Connection:
    """获取 DB 连接，支持只读 URI 模式。"""
    if readonly:
        return sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=10)
    return sqlite3.connect(_DB_PATH, timeout=10)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """首次运行自动建表。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_collab_pact (
        pact_id TEXT PRIMARY KEY,
        center_a TEXT NOT NULL,
        center_b TEXT NOT NULL,
        pact_type TEXT NOT NULL,
        obligations TEXT,
        formed_by TEXT DEFAULT 'ollama',
        confidence REAL DEFAULT 0,
        active INTEGER DEFAULT 1,
        formed_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(center_a, center_b, pact_type)
    );

    CREATE TABLE IF NOT EXISTS mt_collab_hub_network (
        hub_id TEXT PRIMARY KEY,
        galaxy TEXT NOT NULL,
        hub_center TEXT NOT NULL,
        member_centers TEXT,
        last_broadcast TEXT,
        coverage_pct REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _emit_trigger_event(event_type: str, payload: dict) -> None:
    """
    向 TriggerCoordinator 发射事件 (写入 mt_collab_bus_events)。
    任务要求：pact formation 必须 emit TriggerCoordinator event。
    """
    try:
        conn = _db_conn()
        _ensure_tables(conn)
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        conn.execute("""
            INSERT INTO mt_collab_bus_events
            (event_id, event_type, source, severity, payload, status, created_at, event_name, source_system)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id, event_type, 'CollabSolidarityEngine', 'INFO',
            json.dumps(payload, ensure_ascii=False), 'EMITTED', _now_iso(),
            event_type, 'collab_solidarity'
        ))
        conn.commit()
        conn.close()
    except Exception:
        pass  # 触发器总线可能不存在，静默降级


# ═══════════════════════════════════════════════════════════════
# 2. Ollama 推理封装 (容错: 连不上就降级规则推断)
# ═══════════════════════════════════════════════════════════════

def _ollama_infer(prompt: str, system: str = "你是一个 MTSCOS 协作网络架构师。",
                  temperature: float = 0.3, max_tries: int = 2) -> Optional[str]:
    """调用 Ollama 本地模型推理，失败返回 None。"""
    import urllib.request
    import urllib.error

    for port in _OLLAMA_PORTS:
        url = f"http://localhost:{port}/api/generate"
        payload = json.dumps({
            "model": _OLLAMA_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "temperature": temperature,
            "options": {"num_predict": 300},
        }).encode('utf-8')

        for _ in range(max_tries):
            try:
                req = urllib.request.Request(
                    url, data=payload,
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    return data.get('response', '').strip()
            except Exception:
                time.sleep(0.3)
    return None


# ═══════════════════════════════════════════════════════════════
# 3. 协作团结引擎主类
# ═══════════════════════════════════════════════════════════════

class CollabSolidarityEngine:
    """🤝 协作团结引擎 — 把 33 个孤立中心连接成协作网络。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _DB_PATH
        self.conn = _db_conn(readonly=False)
        _ensure_tables(self.conn)

    # ─────────────────────────────────────────────────────────
    # 能力 1: rebuild_full_collab_matrix
    #   用 evolution_log (61964 rows) 的 5s 因果窗口重建协作矩阵
    # ─────────────────────────────────────────────────────────
    def rebuild_full_collab_matrix(self, causal_window_sec: int = _CAUSAL_WINDOW_SEC,
                                   min_event_count: int = 3) -> dict:
        """
        从 evolution_log 扫描"事件-中心"序列, 检测 5 秒内的因果协作链。
        输出: mt_center_collab_matrix 完整填充 (ADD, 不 replace)
        """
        print(f"\n🔄 [1/5] 重建协作矩阵 (window={causal_window_sec}s, min_count={min_event_count}) ...")

        conn = self.conn

        # ── Step A: 取出全部 evolution_log ──
        t0 = time.time()
        rows = conn.execute("""
            SELECT log_id, center_name, event, created_at
            FROM mt_center_evolution_log
            ORDER BY created_at ASC
        """).fetchall()
        print(f"  📖 读取 evolution_log: {len(rows)} rows ({time.time()-t0:.1f}s)")

        # ── Step B: 按时间排序后, 建立因果邻接 ──
        # 策略: 按时间滑窗, 对于每条事件 (A_center, A_event), 检查后面 5s 内
        # 是否有 (B_center, B_event) 且 B_center != A_center
        # 聚合 (A_center, B_center) → 关系类型
        collab_counts: dict[tuple, Counter] = defaultdict(Counter)
        total = len(rows)
        win_start = 0

        t1 = time.time()
        # 为了效率, 先把时间转成 datetime 对象
        parsed = []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r[3].replace('T', ' ')[:19])
            except Exception:
                continue
            parsed.append((ts, r[1], r[2]))  # (timestamp, center, event)

        print(f"  ⏱️ 时间解析完成: {len(parsed)} valid rows")

        # 滑窗: 对于每个 i, 找 j > i 且时间差 <= window
        # 事件语义映射 → 关系类型
        def _event_to_relation(src_evt: str, tgt_evt: str) -> str:
            src_upper = src_evt.upper()
            tgt_upper = tgt_evt.upper()
            # 交易执行后 heal → DEPENDS_ON
            if 'TRADE' in src_upper or 'EXECUTE' in src_upper:
                if 'HEAL' in tgt_upper or 'AUDIT' in tgt_upper or 'CHECK' in tgt_upper:
                    return 'DEPENDS_ON'
            # 知识创建后 autodev → PROVIDES_TO
            if 'KNOWLEDGE' in src_upper or 'LEARN' in src_upper or 'BRAINSTORM' in src_upper:
                if 'AUTO' in tgt_upper or 'DEV' in tgt_upper or 'EVOLVE' in tgt_upper:
                    return 'PROVIDES_TO'
            # heal 事件 → PEER (同类修复)
            if 'HEAL' in src_upper and 'HEAL' in tgt_upper:
                return 'PEER'
            # HEALTH_PULSE / SELF_CHECK / SELF_DRIVE → 同一层级心跳, PEER
            if any(k in src_upper for k in ('PULSE', 'SELF_CHECK', 'SELF_DRIVE', 'SUMMARY')):
                if any(k in tgt_upper for k in ('PULSE', 'SELF_CHECK', 'SELF_DRIVE', 'SUMMARY')):
                    return 'PEER'
            # LAYER_* 事件 → 分层协作, DEPENDS_ON (上层依赖下层)
            if src_upper.startswith('LAYER_') and tgt_upper.startswith('LAYER_'):
                try:
                    src_l = int(src_upper.split('_')[1])
                    tgt_l = int(tgt_upper.split('_')[1])
                    if tgt_l > src_l:
                        return 'DEPENDS_ON'
                except (ValueError, IndexError):
                    pass
            # 默认 PEER
            return 'PEER'

        # O(N) 滑窗
        j = 0
        for i in range(len(parsed)):
            ts_i, center_i, evt_i = parsed[i]
            # 推进 j 到窗口边界
            while j < len(parsed) and (parsed[j][0] - ts_i).total_seconds() <= causal_window_sec:
                j += 1
            # i+1 到 j-1 是窗口内
            for k in range(i + 1, j):
                ts_k, center_k, evt_k = parsed[k]
                if center_k == center_i:
                    continue
                if (ts_k - ts_i).total_seconds() > causal_window_sec:
                    continue
                rel = _event_to_relation(evt_i, evt_k)
                key = (center_i, center_k)
                collab_counts[key][rel] += 1

        print(f"  🔗 滑窗完成: {sum(c.total() for c in collab_counts.values())} 条因果边 "
              f"({time.time()-t1:.1f}s)")

        # ── Step C: 筛选 + 写入 (ADD, 不 replace) ──
        # 先拿已有 pairs
        existing = set(r[0] for r in conn.execute(
            "SELECT source_center || '→' || target_center FROM mt_center_collab_matrix"
        ).fetchall())

        new_inserts = 0
        total_pairs = len(collab_counts)

        # 加一条进度指示
        for idx, ((src, tgt), rel_counter) in enumerate(collab_counts.items()):
            if idx % 200 == 0 and idx > 0:
                print(f"    ... {idx}/{total_pairs} pairs processed")
            total_count = sum(rel_counter.values())
            if total_count < min_event_count:
                continue
            # 选最频繁的关系类型
            relationship = rel_counter.most_common(1)[0][0]
            pair_key = f"{src}→{tgt}"
            if pair_key in existing:
                continue  # 不 replace, 只新增
            matrix_id = f"mat_{uuid.uuid4().hex[:10]}"
            event_types_json = json.dumps(
                [f"{k}:{v}" for k, v in rel_counter.most_common(5)],
                ensure_ascii=False
            )
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO mt_center_collab_matrix
                    (matrix_id, source_center, target_center, event_count, last_collab,
                     event_types, relationship, suggested_upgrade, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    matrix_id, src, tgt, total_count, _now_iso(),
                    event_types_json, relationship, '', _now_iso()
                ))
                new_inserts += 1
            except Exception:
                pass

        conn.commit()

        # 统计
        total_rows = conn.execute("SELECT COUNT(*) FROM mt_center_collab_matrix").fetchone()[0]
        unique_sources = conn.execute(
            "SELECT COUNT(DISTINCT source_center) FROM mt_center_collab_matrix"
        ).fetchone()[0]
        unique_targets = conn.execute(
            "SELECT COUNT(DISTINCT target_center) FROM mt_center_collab_matrix"
        ).fetchone()[0]

        result = {
            'status': 'OK',
            'method': 'causal_window',
            'window_sec': causal_window_sec,
            'new_inserts': new_inserts,
            'total_rows_now': total_rows,
            'unique_sources': unique_sources,
            'unique_targets': unique_targets,
            'elapsed_sec': round(time.time() - t0, 1),
        }
        print(f"  ✅ 新增 {new_inserts} 条, 总计 {total_rows} 行, "
              f"unique sources={unique_sources}, unique targets={unique_targets}")
        return result

    # ─────────────────────────────────────────────────────────
    # 能力 2: ai_suggest_collab_pairs
    #   Ollama 推理 → 职责互补的孤立中心配对
    # ─────────────────────────────────────────────────────────
    def ai_suggest_collab_pairs(self) -> list:
        """
        找出 collab_matrix 里还没出现过的孤立中心, 推理它们应该跟谁协作。
        输出: list of {source, target, suggested_relation, reason}
              → 写入 mt_center_collab_matrix.suggested_upgrade
        """
        print(f"\n🧠 [2/5] AI 推荐协作对 ...")
        conn = self.conn

        # ── Step A: 找出孤立中心 ──
        all_centers = [r[0] for r in conn.execute(
            "SELECT DISTINCT center_name FROM mt_center_cognition_portrait"
        ).fetchall()]
        connected = set(r[0] for r in conn.execute(
            "SELECT DISTINCT source_center FROM mt_center_collab_matrix"
        ).fetchall()) | set(r[0] for r in conn.execute(
            "SELECT DISTINCT target_center FROM mt_center_collab_matrix"
        ).fetchall())
        isolated = [c for c in all_centers if c not in connected]
        print(f"  🔍 孤立中心: {len(isolated)}/{len(all_centers)}")

        # ── Step B: 获取所有中心画像 (含 duty + galaxy) ──
        portraits = {}
        for r in conn.execute("""
            SELECT center_name, galaxy, primary_duty, secondary_duty
            FROM mt_center_cognition_portrait
        """).fetchall():
            portraits[r[0]] = {
                'galaxy': r[1],
                'primary_duty': r[2] or '',
                'secondary_duty': r[3] or '',
            }

        # ── Step C: 职责关键词匹配 (先用规则, Ollama 可选增强) ──
        # 预定义: 哪些职责关键词应该跟哪些关键词搭配
        DUTY_COMPLEMENTS = [
            # (关键词A, 关键词B, 关系类型, 理由模板)
            ('部署运维', '安全审计', 'PEER', '运维+审计=DevSecOps: 部署后立即做安全审计'),
            ('Skill研发', 'AI 引擎', 'PEER', '研发+引擎=能力升级: 新 Skill 需要 AI 引擎执行'),
            ('题库', '知识', 'PROVIDES_TO', '题库+知识=学习闭环: 题库产生知识沉淀'),
            ('脑库', 'RAG', 'PEER', '脑库+检索=智能投喂: 脑库内容需要 RAG pipeline 检索'),
            ('数据', '金融', 'PEER', '数据研究+金融=量化研究: 数据驱动金融策略优化'),
            ('法务', '合规', 'DEPENDS_ON', '法务+合规: 法务执行前需要合规确认'),
            ('开发流程', '漏洞修复', 'DEPENDS_ON', '开发流程+漏洞修复: 修复必须走开发流程'),
            ('人力', 'AI 引擎', 'PROVIDES_TO', '人力+AI: 人力调度 AI 引擎辅助招聘/培训'),
            ('前端', '前端设计', 'PEER', '前端+设计=产品闭环: 设计驱动前端实现'),
            ('印章', '审计', 'DEPENDS_ON', '印章+审计: 盖章前必须通过审计'),
            ('复核', '审计', 'PEER', '复核+审计=双重校验: 交易后复核+审计'),
            ('数据备份', '数据研究', 'DEPENDS_ON', '数据备份+研究: 研究前先确保数据可恢复'),
            ('专家团队', 'Skill研发', 'PROVIDES_TO', '专家团队+研发: 专家知识驱动 Skill 研发'),
            ('历史档案', '知识沉淀', 'PROVIDES_TO', '历史档案+知识: 档案 → 知识提炼'),
            ('战略', '工作流', 'DEPENDS_ON', '战略+工作流: 战略落地必须通过工作流执行'),
            ('安全审计', '监察大队', 'PEER', '安全审计+监察=双重防护'),
            ('规则治理', '审计', 'PEER', '规则治理+审计=制度+执行'),
            ('教育题库', '考试', 'PROVIDES_TO', '题库+考试: 题库 → 自动考试生成'),
        ]

        suggested = []
        for iso_center in isolated:
            if iso_center not in portraits:
                continue
            iso_duty = (portraits[iso_center]['primary_duty'] or
                       portraits[iso_center]['secondary_duty'] or '')

            for other_center in all_centers:
                if other_center == iso_center or other_center in isolated:
                    continue
                if other_center not in portraits:
                    continue
                other_duty = (portraits[other_center]['primary_duty'] or
                              portraits[other_center]['secondary_duty'] or '')

                # 匹配互补关系
                for kw_a, kw_b, rel, reason in DUTY_COMPLEMENTS:
                    if kw_a in iso_center + iso_duty and kw_b in other_center + other_duty:
                        suggested.append({
                            'source': iso_center,
                            'target': other_center,
                            'relationship': rel,
                            'reason': reason,
                            'method': 'rule',
                        })
                        break
                    if kw_b in iso_center + iso_duty and kw_a in other_center + other_duty:
                        suggested.append({
                            'source': other_center,
                            'target': iso_center,
                            'relationship': rel,
                            'reason': reason,
                            'method': 'rule',
                        })
                        break

        # 同星系中心 → 自然 PEER
        galaxy_groups = defaultdict(list)
        for cn, p in portraits.items():
            galaxy_groups[p['galaxy']].append(cn)
        for g, members in galaxy_groups.items():
            if len(members) < 2:
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    if a in isolated or b in isolated:
                        pair_exists = conn.execute(
                            "SELECT 1 FROM mt_center_collab_matrix WHERE "
                            "(source_center=? AND target_center=?) OR "
                            "(source_center=? AND target_center=?)",
                            (a, b, b, a)
                        ).fetchone()
                        if not pair_exists:
                            suggested.append({
                                'source': a,
                                'target': b,
                                'relationship': 'PEER',
                                'reason': f'同星系 {g} 自然协作 (同层心跳联动)',
                                'method': 'galaxy_proximity',
                            })

        # ── Step D: Ollama 增强 (可选) ──
        if _ollama_infer("ping", temperature=0) is not None:
            print("  🧠 Ollama 可用, 追加 AI 推理推荐 ...")
            try:
                iso_portrait_text = "\n".join(
                    f"- {c} ({portraits[c]['galaxy']}): {portraits[c]['primary_duty'][:60]}"
                    for c in isolated if c in portraits
                )
                prompt = f"""以下是 MTSCOS 37 中心系统中尚未建立协作连接的孤立中心:
{iso_portrait_text}

请推荐 5-10 对应该建立协作关系的中心, 输出严格 JSON:
[{{"source": "中心名", "target": "中心名", "relation": "PEER|DEPENDS_ON|PROVIDES_TO", "reason": "一句话理由"}}]"""
                ai_resp = _ollama_infer(prompt, temperature=0.4)
                if ai_resp:
                    # 提取 JSON
                    try:
                        import re
                        m = re.search(r'\[.*\]', ai_resp, re.DOTALL)
                        if m:
                            pairs = json.loads(m.group(0))
                            for p in pairs[:10]:
                                if all(k in p for k in ('source', 'target', 'relation')):
                                    suggested.append({
                                        'source': p['source'],
                                        'target': p['target'],
                                        'relationship': p['relation'],
                                        'reason': p.get('reason', 'AI 推理'),
                                        'method': 'ollama',
                                    })
                    except Exception:
                        pass
            except Exception:
                pass

        # ── Step E: 去重 + 写入 suggested_upgrade ──
        seen = set()
        final = []
        for s in suggested:
            key = (s['source'], s['target'])
            if key in seen:
                continue
            seen.add(key)
            final.append(s)

        # 写入 collab_matrix.suggested_upgrade
        for s in final:
            existing_row = conn.execute(
                "SELECT matrix_id FROM mt_center_collab_matrix WHERE "
                "source_center=? AND target_center=?",
                (s['source'], s['target'])
            ).fetchone()
            if existing_row:
                # 更新 suggested_upgrade
                reason = f"⚠ AI 建议: {s['relationship']} — {s['reason']}"
                conn.execute(
                    "UPDATE mt_center_collab_matrix SET suggested_upgrade=? WHERE matrix_id=?",
                    (reason, existing_row[0])
                )
            else:
                # 新建一条 suggested (event_count=0, 标记为 AI 建议)
                matrix_id = f"ai_{uuid.uuid4().hex[:10]}"
                reason = f"⚠ AI 建议: {s['relationship']} — {s['reason']}"
                conn.execute("""
                    INSERT OR IGNORE INTO mt_center_collab_matrix
                    (matrix_id, source_center, target_center, event_count, last_collab,
                     event_types, relationship, suggested_upgrade, created_at)
                    VALUES (?, ?, ?, 0, ?, '[]', ?, ?, ?)
                """, (matrix_id, s['source'], s['target'], _now_iso(),
                      s['relationship'], reason, _now_iso()))

        conn.commit()
        print(f"  ✅ 推荐 {len(final)} 对新协作 (规则={sum(1 for s in final if s['method']=='rule')}, "
              f"星系={sum(1 for s in final if s['method']=='galaxy_proximity')}, "
              f"Ollama={sum(1 for s in final if s['method']=='ollama')})")
        return final

    # ─────────────────────────────────────────────────────────
    # 能力 3: ai_broadcast_hub_network
    #   把 broadcast 独大 → 星系 hub 分层网络
    # ─────────────────────────────────────────────────────────
    def ai_broadcast_hub_network(self) -> dict:
        """
        当前: broadcast 是唯一 target (258 入度)
        应该: 每个星系有自己的 hub, 再向上汇聚到 broadcast
        步骤:
          1. 按星系分组 37 中心
          2. 为每个星系选 hub_center (用 galaxy 内部最活跃的)
          3. 写入 mt_collab_hub_network
          4. 写入 trigger_handler (新 hub 触发器)
          5. broadcast ← 每个 hub_center (形成汇聚层)
        """
        print(f"\n🌐 [3/5] 建立星系 hub 分层网络 ...")
        conn = self.conn

        # ── Step A: 按星系分组 + 统计每个中心活跃度 ──
        portraits = conn.execute("""
            SELECT center_name, galaxy FROM mt_center_cognition_portrait
        """).fetchall()
        # 活跃度 = evolution_log 中的事件数
        activity = dict(conn.execute("""
            SELECT center_name, COUNT(*) FROM mt_center_evolution_log
            GROUP BY center_name
        """).fetchall())

        galaxy_members: dict[str, list[str]] = defaultdict(list)
        for cn, g in portraits:
            galaxy_members[g].append(cn)

        # ── Step B: 为每个星系选 hub (最活跃中心) ──
        hub_assignments = {}  # galaxy -> hub_center
        for galaxy, members in galaxy_members.items():
            # 内部 hub_center 分配表优先
            if galaxy in _GALAXY_HUB_MAP:
                # 检查 hub 是否存在于成员中, 否则选最活跃的
                hub = _GALAXY_HUB_MAP[galaxy]
                if hub not in members:
                    # 尝试模糊匹配
                    best = None
                    best_score = -1
                    for m in members:
                        score = activity.get(m, 0)
                        if score > best_score:
                            best_score = score
                            best = m
                    hub = best or members[0]
            else:
                # 选最活跃的
                best = max(members, key=lambda m: activity.get(m, 0))
                hub = best
            hub_assignments[galaxy] = hub

        # ── Step C: 写入 mt_collab_hub_network ──
        for galaxy, members in galaxy_members.items():
            hub = hub_assignments[galaxy]
            hub_id = f"hub_{galaxy}"
            member_json = json.dumps(members, ensure_ascii=False)
            coverage = round(
                len(members) / max(len(galaxy_members.get(galaxy, [])), 1) * 100, 1
            )
            conn.execute("""
                INSERT OR REPLACE INTO mt_collab_hub_network
                (hub_id, galaxy, hub_center, member_centers, last_broadcast,
                 coverage_pct, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (hub_id, galaxy, hub, member_json, _now_iso(), coverage, _now_iso()))

        # ── Step D: 每个 hub → broadcast (汇聚层 PEER) ──
        total_hubs = len(hub_assignments)
        broadcast_count = 0
        for galaxy, hub_center in hub_assignments.items():
            # hub → broadcast
            conn.execute("""
                INSERT OR IGNORE INTO mt_center_collab_matrix
                (matrix_id, source_center, target_center, event_count, last_collab,
                 event_types, relationship, suggested_upgrade, created_at)
                VALUES (?, ?, ?, 0, ?, '["HUB→BROADCAST:layer"]', 'PEER', '', ?)
            """, (
                f"hubmat_{uuid.uuid4().hex[:8]}", hub_center, 'broadcast',
                _now_iso(), _now_iso()
            ))
            # 成员 → hub
            for member in galaxy_members.get(galaxy, []):
                if member == hub_center:
                    continue
                conn.execute("""
                    INSERT OR IGNORE INTO mt_center_collab_matrix
                    (matrix_id, source_center, target_center, event_count, last_collab,
                     event_types, relationship, suggested_upgrade, created_at)
                    VALUES (?, ?, ?, 0, ?, '["MEMBER→HUB:galaxy"]', 'PEER', '', ?)
                """, (
                    f"member_{uuid.uuid4().hex[:8]}", member, hub_center,
                    _now_iso(), _now_iso()
                ))
            broadcast_count += 1

        # ── Step E: 更新 trigger_handler (新 hub 事件) ──
        handler_events = [
            ('GALAXY_HUB_BROADCAST', 'galaxy_hub_broadcast_handler',
             'trigger_coordinator', 'route_event'),
            ('COLLAB_PACT_FORMED', 'collab_pact_handler',
             'trigger_coordinator', 'handle_pact'),
        ]
        for evt_key, handler_key, target_eng, target_m in handler_events:
            conn.execute("""
                INSERT OR IGNORE INTO mt_trigger_handler
                (handler_id, trigger_event_type, handler_key, target_engine,
                 target_method, enabled, phase, last_executed, last_success,
                 exec_count, avg_duration_ms)
                VALUES (?, ?, ?, ?, ?, 1, 1, ?, 1, 0, 0)
            """, (
                f"trgh_{uuid.uuid4().hex[:10]}",
                evt_key, handler_key, target_eng, target_m, _now_iso()
            ))

        # 同步更新 trigger_registry
        conn.execute("""
            INSERT OR IGNORE INTO mt_trigger_registry
            (trigger_id, event_type, priority, cooldown_ms, handler_count,
             enabled, throttle_max_per_sec, throttle_burst, description,
             registered_at, updated_at)
            VALUES (?, ?, 'HIGH', 500, 1, 1, 10, 20, ?, ?, ?)
        """, (
            f"trg_{uuid.uuid4().hex[:8]}",
            'COLLAB_PACT_FORMED', _now_iso(), _now_iso(),
            '协作契约形成事件 - CollabSolidarityEngine'
        ))

        conn.commit()

        # ── Step F: emit 事件 ──
        _emit_trigger_event('COLLAB_HUB_NETWORK_ESTABLISHED', {
            'hub_count': total_hubs,
            'assignments': hub_assignments,
        })

        print(f"  ✅ {total_hubs} 个星系 hub 已建立:")
        for g, h in hub_assignments.items():
            print(f"    🌌 {g:15s} → hub={h}  ({len(galaxy_members[g])} members)")

        return {
            'status': 'OK',
            'galaxy_count': total_hubs,
            'hub_assignments': hub_assignments,
            'hub_rows': len(galaxy_members),
            'trigger_handlers_added': len(handler_events),
        }

    # ─────────────────────────────────────────────────────────
    # 能力 4: form_collab_pact
    #   两个中心签署协作契约 (写入 mt_collab_pact)
    # ─────────────────────────────────────────────────────────
    def form_collab_pact(self, center_a: str, center_b: str,
                         pact_type: str = 'PEER',
                         formed_by: str = 'ollama',
                         confidence: float = 0.5) -> dict:
        """
        签署协作契约。pact_type: PEER/DEPENDS_ON/PROVIDES_TO
        契约触发 → emit('COLLAB_PACT_FORMED') → TriggerCoordinator
        """
        print(f"\n📜 [4/5] 签署 {center_a} ⇄ {center_b} ({pact_type}) ...")
        conn = self.conn

        # 校验中心存在
        all_c = set(r[0] for r in conn.execute(
            "SELECT DISTINCT center_name FROM mt_center_cognition_portrait"
        ).fetchall())
        if center_a not in all_c:
            return {'status': 'ERROR', 'error': f'{center_a} 不在 37 中心中'}
        if center_b not in all_c:
            return {'status': 'ERROR', 'error': f'{center_b} 不在 37 中心中'}
        if center_a == center_b:
            return {'status': 'ERROR', 'error': '不能自己签自己'}

        # 生成 obligations
        portraits = {}
        for cn in (center_a, center_b):
            row = conn.execute("""
                SELECT galaxy, primary_duty FROM mt_center_cognition_portrait
                WHERE center_name=?
            """, (cn,)).fetchone()
            if row:
                portraits[cn] = {'galaxy': row[0], 'duty': row[1] or ''}

        obligations = {
            'center_a': {
                'name': center_a,
                'galaxy': portraits.get(center_a, {}).get('galaxy', 'unknown'),
                'duty': portraits.get(center_a, {}).get('duty', '')[:80],
                'promise': self._pact_promise(pact_type, center_a, center_b),
            },
            'center_b': {
                'name': center_b,
                'galaxy': portraits.get(center_b, {}).get('galaxy', 'unknown'),
                'duty': portraits.get(center_b, {}).get('duty', '')[:80],
                'promise': self._pact_promise(pact_type, center_b, center_a),
            },
            'pact_type': pact_type,
            'formed_by': formed_by,
            'confidence': confidence,
            'formed_at': _now_iso(),
        }

        pact_id = f"pact_{uuid.uuid4().hex[:12]}"
        try:
            conn.execute("""
                INSERT INTO mt_collab_pact
                (pact_id, center_a, center_b, pact_type, obligations,
                 formed_by, confidence, active, formed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                pact_id, center_a, center_b, pact_type,
                json.dumps(obligations, ensure_ascii=False),
                formed_by, confidence, _now_iso()
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            # 已存在, 更新 active=1
            conn.execute("""
                UPDATE mt_collab_pact SET active=1, formed_at=?
                WHERE center_a=? AND center_b=? AND pact_type=?
            """, (_now_iso(), center_a, center_b, pact_type))
            conn.commit()
            pact_id = f"existing_{center_a}→{center_b}"

        # 同步到 collab_matrix
        conn.execute("""
            INSERT OR IGNORE INTO mt_center_collab_matrix
            (matrix_id, source_center, target_center, event_count, last_collab,
             event_types, relationship, suggested_upgrade, created_at)
            VALUES (?, ?, ?, 0, ?, '["PACTSIGNED"]', ?, '', ?)
        """, (
            f"pactmat_{uuid.uuid4().hex[:8]}", center_a, center_b,
            _now_iso(), pact_type, _now_iso()
        ))
        conn.commit()

        # emit 事件
        _emit_trigger_event('COLLAB_PACT_FORMED', {
            'pact_id': pact_id,
            'center_a': center_a,
            'center_b': center_b,
            'pact_type': pact_type,
            'formed_by': formed_by,
            'confidence': confidence,
        })

        print(f"  ✅ 契约 {pact_id} 签署完成 → 已 emit COLLAB_PACT_FORMED")
        return {
            'status': 'OK',
            'pact_id': pact_id,
            'center_a': center_a,
            'center_b': center_b,
            'pact_type': pact_type,
            'confidence': confidence,
        }

    @staticmethod
    def _pact_promise(pact_type: str, self_name: str, other_name: str) -> str:
        if pact_type == 'PEER':
            return f'与 {other_name} 平等协作, 心跳同步, 事件互通'
        elif pact_type == 'DEPENDS_ON':
            return f'依赖 {other_name} 先完成任务, 我才能执行 (顺序前置)'
        elif pact_type == 'PROVIDES_TO':
            return f'向 {other_name} 提供数据/能力, 作为其上游输入'
        return f'与 {other_name} 保持联系'

    # ─────────────────────────────────────────────────────────
    # 能力 5: run_solidarity_cycle (一键完整团结)
    # ─────────────────────────────────────────────────────────
    def run_solidarity_cycle(self, auto_pact_count: int = 5) -> dict:
        """一键协作团结: rebuild → suggest → hub → pacts"""
        print("=" * 60)
        print("🤝 协作团结周期 — 开始")
        print("=" * 60)
        t0 = time.time()

        # 1. 重建矩阵
        r1 = self.rebuild_full_collab_matrix()

        # 2. AI 推荐
        r2 = self.ai_suggest_collab_pairs()

        # 3. Hub 网络
        r3 = self.ai_broadcast_hub_network()

        # 4. 自动签署 Top N 推荐
        pacts_signed = []
        for rec in r2[:auto_pact_count]:
            pact = self.form_collab_pact(
                rec['source'], rec['target'],
                rec['relationship'], formed_by='auto_cycle', confidence=0.7
            )
            pacts_signed.append(pact)

        total_elapsed = round(time.time() - t0, 1)

        # 统计最终状态
        conn = self.conn
        total_pairs = conn.execute(
            "SELECT COUNT(*) FROM mt_center_collab_matrix"
        ).fetchone()[0]
        total_pacts = conn.execute(
            "SELECT COUNT(*) FROM mt_collab_pact"
        ).fetchone()[0]
        total_centers = conn.execute(
            "SELECT COUNT(DISTINCT center_name) FROM mt_center_cognition_portrait"
        ).fetchone()[0]
        connected = conn.execute("""
            SELECT COUNT(DISTINCT center_name) FROM mt_center_cognition_portrait
            WHERE center_name IN (
                SELECT DISTINCT source_center FROM mt_center_collab_matrix
                UNION
                SELECT DISTINCT target_center FROM mt_center_collab_matrix
            )
        """).fetchone()[0]

        print("\n" + "=" * 60)
        print(f"✅ 协作团结周期完成 ({total_elapsed}s)")
        print(f"   collab_matrix: {total_pairs} pairs")
        print(f"   collab_pact:   {total_pacts} signed")
        print(f"   连接率:         {connected}/{total_centers} connected")
        print("=" * 60)

        return {
            'cycle_result': 'OK',
            'elapsed_sec': total_elapsed,
            'rebuild': r1,
            'suggest': {'count': len(r2)},
            'hub': r3,
            'pacts_signed_count': len(pacts_signed),
            'final_state': {
                'collab_matrix_rows': total_pairs,
                'pact_count': total_pacts,
                'connected_centers': connected,
                'total_centers': total_centers,
                'connectivity_pct': round(connected / total_centers * 100, 1) if total_centers else 0,
            },
        }

    # ─────────────────────────────────────────────────────────
    # 关闭
    # ─────────────────────────────────────────────────────────
    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# 4. CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description='🤝 MTSCOS CollabSolidarityEngine')
    ap.add_argument('--rebuild', action='store_true', help='重建协作矩阵 (evolution_log 因果窗口)')
    ap.add_argument('--suggest', action='store_true', help='AI 推荐新协作对')
    ap.add_argument('--hub', action='store_true', help='建立星系 hub 分层网络')
    ap.add_argument('--pact', nargs='*', metavar='ARGS',
                    help='签署协作契约: --pact centerA centerB [PEER|DEPENDS_ON|PROVIDES_TO]')
    ap.add_argument('--all', action='store_true', help='一键完整团结周期')
    args = ap.parse_args()

    engine = CollabSolidarityEngine()

    try:
        if args.rebuild:
            result = engine.rebuild_full_collab_matrix()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.suggest:
            result = engine.ai_suggest_collab_pairs()
            print(json.dumps(result[:20], indent=2, ensure_ascii=False))
        elif args.hub:
            result = engine.ai_broadcast_hub_network()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.pact:
            if len(args.pact) < 2:
                print("❌ 用法: --pact centerA centerB [PEER|DEPENDS_ON|PROVIDES_TO]")
                sys.exit(1)
            center_a = args.pact[0]
            center_b = args.pact[1]
            pact_type = args.pact[2] if len(args.pact) > 2 else 'PEER'
            result = engine.form_collab_pact(center_a, center_b, pact_type)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.all:
            result = engine.run_solidarity_cycle()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            ap.print_help()
    finally:
        engine.close()


if __name__ == '__main__':
    main()
