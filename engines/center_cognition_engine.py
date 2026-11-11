#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 CENTER COGNITION ENGINE — AI 元认知引擎反向赋能 33 中心
让每个中心获得:
  ① 职责画像   → 这个中心应该做什么
  ② 能力边界   → 这个中心能做什么 / 不能做什么 (防止越权)
  ③ 协作矩阵   → 这个中心跟谁协作 / 谁依赖谁
  ④ AI 路由    → AI 推荐: 这个中心现在该调用哪个引擎/技能
  ⑤ 专属经验   → 从历史行为中提炼的该中心专属经验

数据来源 (全部真实, 无 mock):
  - mt_center_evolution_log (61176 rows) → 中心行为历史
  - mt_center_health_matrix (112 rows) → 10 中心实时健康
  - mt_collab_bus_events (582 rows) → 跨中心协作频率
  - mt_trigger_handler (33 handlers) → 触发器 → 中心绑定
  - mt_trigger_registry (13 events) → 事件类型
  - mt_ai_capability_registry (400 capabilities) → AI 能力目录
  - mt_ai_experience_snippet (140 experiences) → 经验库
  - Ollama qwen2.5:3b → 推理增强 (职责画像生成 + 边界推理)
"""

import sqlite3
import json
import os
import time
import uuid
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import Counter, defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [COG] %(message)s',
)
log = logging.getLogger("center_cognition")

# ═══════════════════════════════════════════════════════════════
# DDL — 4 张新表
# ═══════════════════════════════════════════════════════════════
DDL_TABLES = [
    """CREATE TABLE IF NOT EXISTS mt_center_cognition_portrait (
        portrait_id TEXT PRIMARY KEY,
        center_name TEXT NOT NULL UNIQUE,
        galaxy TEXT,
        primary_duty TEXT,
        secondary_duty TEXT,
        boundaries TEXT,
        ai_route TEXT,
        event_distribution TEXT,
        collab_frequency TEXT,
        health_score REAL DEFAULT 0,
        ollama_generated INTEGER DEFAULT 1,
        generated_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS mt_center_collab_matrix (
        matrix_id TEXT PRIMARY KEY,
        source_center TEXT NOT NULL,
        target_center TEXT NOT NULL,
        event_count INTEGER DEFAULT 0,
        last_collab TEXT,
        event_types TEXT,
        relationship TEXT,
        suggested_upgrade TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(source_center, target_center)
    )""",
    """CREATE TABLE IF NOT EXISTS mt_center_boundary (
        boundary_id TEXT PRIMARY KEY,
        center_name TEXT NOT NULL UNIQUE,
        can_do TEXT,
        cannot_do TEXT,
        recent_violations INTEGER DEFAULT 0,
        last_violation TEXT,
        ollama_reasoning TEXT,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE IF NOT EXISTS mt_center_experience (
        exp_id TEXT PRIMARY KEY,
        center_name TEXT NOT NULL,
        exp_type TEXT NOT NULL,
        summary TEXT,
        lesson TEXT,
        confidence REAL DEFAULT 0,
        source_events TEXT,
        applicable_engines TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""",
]


# ═══════════════════════════════════════════════════════════════
# 星系分组 + 中心职责 (AI 元认知引擎 seed, 后续由 Ollama 推理扩展)
# ═══════════════════════════════════════════════════════════════
CENTER_ROLES = {
    # ── 星系: andromeda 主控星系 ──
    'andromeda': {
        'galaxy': '主控星系',
        'cn_name': '仙女座主控',
        'centers': ['部署运维中心', 'CrossSelfHeal', 'SYSTEM', 'StrategyCenter'],
        'primary_duty': '总控调度·自演化·跨中心协调',
        'secondary_duty': '脑库投喂·触发器协调·自愈',
        'core_engines': ['andromeda_autopilot_v2', 'trigger_coordinator',
                         'center_orchestrator', 'event_bus_engine', 'cross_self_heal'],
        'allowed_event_patterns': ['HEALTH_PULSE', 'SELF_CHECK_SUMMARY',
                                    'SELF_DRIVE_RECAP', 'DIRECTION_GROWTH',
                                    'HEAL_', 'AUTOPILOT_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: gobelin 金融星系 ──
    'gobelin': {
        'galaxy': '金融星系',
        'cn_name': '哥布林金融',
        'centers': ['gobelin_trading', '审计中心', '复核中心', '印章管理中心', '数据备份中心'],
        'primary_duty': '交易·风控·稽查·记账·印章',
        'secondary_duty': 'PnL·归因·日报·备份',
        'core_engines': ['finance_ledger_engine', 'finance_risk_engine',
                         'finance_realtime_audit', 'finance_audit_daemon',
                         'finance_attribution', 'finance_daily_report'],
        'allowed_event_patterns': ['TRADE_', 'RISK_', 'AUDIT_', 'LEDGER_',
                                    'DAILY_', 'GOBELIN_'],
        'forbidden_galaxies': ['education'],
    },
    # ── 星系: iceberg 教育星系 ──
    'iceberg': {
        'galaxy': '教育星系',
        'cn_name': '冰山题库',
        'centers': ['教育题库中心'],
        'primary_duty': '题库·考试·AI员工培养',
        'secondary_duty': '语言·技能培训',
        'core_engines': ['iceberg_content_matrix', 'ai_exam_auto_engine',
                         'ai_language_pedagogy_engine', 'ai_math_pedagogy_engine'],
        'allowed_event_patterns': ['EXAM_', 'QBANK_', 'EDU_', 'LEARN_',
                                    'HEAL_ICEBERG_'],
        'forbidden_galaxies': ['finance'],
    },
    # ── 星系: brain 记忆星系 ──
    'brain': {
        'galaxy': '记忆星系',
        'cn_name': '脑库记忆',
        'centers': ['AI 引擎中心', '历史档案中心'],
        'primary_duty': '脑库·知识沉淀·信息收集',
        'secondary_duty': '引擎档案·知识归档',
        'core_engines': ['ai_brain_feed_engine', 'brain_feeding_engine',
                         'fm_listener_daemon', 'ai_archive_engine',
                         'ai_archive_archaeology_engine'],
        'allowed_event_patterns': ['BRAIN_', 'KNOWLEDGE_', 'FEED_', 'ARCHIVE_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: eigenflux 特征流星系 ──
    'eigenflux': {
        'galaxy': '特征流星系',
        'cn_name': '特征流专家',
        'centers': [],
        'primary_duty': '因子挖掘·特征工程',
        'secondary_duty': '专家广播·信号增强',
        'core_engines': ['ai_feature_evolution_engine', 'eigenflux_broadcast_engine'],
        'allowed_event_patterns': ['EIGENFLUX_', 'FEATURE_', 'SIGNAL_',
                                    'HEAL_EIGENFLUX_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: eventbus 协作总线星系 ──
    'eventbus': {
        'galaxy': '协作总线星系',
        'cn_name': '协作总线',
        'centers': [],
        'primary_duty': '事件总线·消息路由·订阅管理',
        'secondary_duty': '积压清理·广播健康',
        'core_engines': ['collab_bus_engine', 'event_bus_engine',
                         'trigger_coordinator'],
        'allowed_event_patterns': ['EVENT_', 'BUS_', 'DISPATCH_',
                                    'HEAL_EVENTBUS_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: taskhall 任务星系 ──
    'taskhall': {
        'galaxy': '任务星系',
        'cn_name': '任务大厅',
        'centers': ['战略中心'],
        'primary_duty': '任务派发·调度·战略',
        'secondary_duty': '自动委派·任务大厅',
        'core_engines': ['hall_dispatch', 'ai_task_hall_approval_engine',
                         'ai_task_hall_flow_engine', 'ai_task_hall_landing_engine',
                         'ai_strategy_center_engine'],
        'allowed_event_patterns': ['TASK_', 'HALL_', 'DISPATCH_', 'DIRECTION_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: infra 基建星系 ──
    'infra': {
        'galaxy': '基建星系',
        'cn_name': '基建同步',
        'centers': ['仙女座同步中心'],
        'primary_duty': '时间同步·DB同步·版本管理',
        'secondary_duty': '多活同步·数据一致性',
        'core_engines': ['time_sync_engine', 'db_triple_sync_engine',
                         'sync_center', 'mac_mini_sync_engine'],
        'allowed_event_patterns': ['SYNC_', 'TIME_', 'DB_', 'VERSION_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: security 安全星系 ──
    'security': {
        'galaxy': '安全星系',
        'cn_name': '安全防护',
        'centers': ['安全审计中心', '监察大队', '规则治理中心'],
        'primary_duty': '防护·防火墙·审计·监察·治理',
        'secondary_duty': '规则强化·漏洞修复',
        'core_engines': ['shield_daemon', 'firewall_hardening_engine',
                         'security_enhancer', 'ai_iron_rule_guard',
                         'ai_rule_learning_engine'],
        'allowed_event_patterns': ['SECURITY_', 'SHIELD_', 'FIREWALL_',
                                    'RULE_', 'COMPLIANCE_', 'AUDIT_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: hr 人力星系 ──
    'hr': {
        'galaxy': '人力星系',
        'cn_name': '人事人力',
        'centers': ['人事人力中心', '人力统一调配中心', 'Skill研发中心',
                    '专家团队中心', 'AI 引擎中心'],
        'primary_duty': 'HR·员工·技能·专家团队',
        'secondary_duty': '自动雇佣·能力发现',
        'core_engines': ['ai_auto_hire_engine', 'ai_hr_center_engine',
                         'ai_org_growth_engine', 'ai_center_consultation_engine'],
        'allowed_event_patterns': ['HR_', 'HIRE_', 'EMPLOYEE_', 'SKILL_',
                                    'TEAM_', 'WEEKLY_TRAINING_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: legal 法务星系 ──
    'legal': {
        'galaxy': '法务星系',
        'cn_name': '法务合规',
        'centers': ['法务合规中心', '漏洞修复适配中心', '工作流研究中心',
                    '开发流程中心'],
        'primary_duty': '法务·合规·漏洞修复·流程治理',
        'secondary_duty': '工作流编排·规则执行',
        'core_engines': ['ai_customs_admin_engine', 'ai_legislation_engine',
                         'ai_sandbox_meeting_auto', 'workflow_engine'],
        'allowed_event_patterns': ['LEGAL_', 'COMPLIANCE_', 'RULE_', 'WORKFLOW_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: data 数据星系 ──
    'data': {
        'galaxy': '数据星系',
        'cn_name': '数据研究',
        'centers': ['数据研究中心', '数据备份中心'],
        'primary_duty': '数据研究·数据分析·备份恢复',
        'secondary_duty': '洞察生成·知识提炼',
        'core_engines': ['ai_data_center_engine', 'ai_archive_engine',
                         'backup_manager', 'ai_data_pipeline'],
        'allowed_event_patterns': ['DATA_', 'ANALYSIS_', 'BACKUP_', 'ARCHIVE_'],
        'forbidden_galaxies': [],
    },
    # ── 星系: frontend 前端星系 ──
    'frontend': {
        'galaxy': '前端星系',
        'cn_name': '前端设计',
        'centers': ['前端设计中心'],
        'primary_duty': '前端设计·页面优化',
        'secondary_duty': 'UI/UX 提升',
        'core_engines': ['ai_frontend_optimizer', 'chat_theme_engine'],
        'allowed_event_patterns': ['FRONTEND_', 'UI_', 'UX_', 'DESIGN_'],
        'forbidden_galaxies': [],
    },
}


# ═══════════════════════════════════════════════════════════════
# HEALTH MATRIX COLUMN 映射 (health_matrix 是宽表)
# ═══════════════════════════════════════════════════════════════
HEALTH_COLUMN_MAP = {
    'andromeda': 'center_andromeda',
    'gobelin':   'center_gobelin',
    'iceberg':   'center_iceberg',
    'eigenflux': 'center_eigenflux',
    'eventbus':  'center_eventbus',
    'audit':     'center_audit',
    'brainfeed': 'center_brainfeed',
    'taskhall':  'center_taskhall',
    'hr':        'center_hr',
    'autopilot': 'center_autopilot',
}

# 星系 ↔ health matrix key 的反向映射
GALAXY_TO_HEALTH_KEY = {}
for _hk, _col in HEALTH_COLUMN_MAP.items():
    # _hk 就是健康矩阵 key
    GALAXY_TO_HEALTH_KEY[_hk] = _hk

# 星系 ↔ evolution_log 中心名映射
GALAXY_TO_CENTER_NAME = {
    'andromeda': ['部署运维中心', 'CrossSelfHeal', 'SYSTEM'],
    'gobelin':   ['gobelin_trading', '审计中心', '复核中心', '印章管理中心', '数据备份中心'],
    'iceberg':   ['教育题库中心'],
    'security':  ['安全审计中心', '监察大队', '规则治理中心'],
    'hr':        ['人事人力中心', '人力统一调配中心', 'Skill研发中心', '专家团队中心', 'AI 引擎中心'],
    'legal':     ['法务合规中心', '漏洞修复适配中心', '工作流研究中心', '开发流程中心'],
    'data':      ['数据研究中心'],
    'frontend':  ['前端设计中心'],
}

# 反向: evolution_log.center_name → 星系
CENTER_NAME_TO_GALAXY = {}
for _gal, _names in GALAXY_TO_CENTER_NAME.items():
    for _n in _names:
        CENTER_NAME_TO_GALAXY[_n] = _gal


class CenterCognitionEngine:
    """🧠 中心元认知引擎 — AI 反向赋能 33 中心"""

    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "qwen2.5:3b"
    OLLAMA_TIMEOUT = 30  # seconds

    def __init__(self, db_path=None):
        self.db_path = os.path.abspath(db_path or os.path.join(
            os.path.dirname(__file__), '..', 'database', 'app.db'
        ))
        self.ollama_available = self._check_ollama()
        log.info(f"[CenterCognition] DB={self.db_path}, Ollama={'ON' if self.ollama_available else 'OFF'}")
        self._ensure_tables()

    # ═══════════ DB 基础设施 ═══════════
    def _conn(self, readonly=False):
        if readonly:
            return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        return sqlite3.connect(self.db_path)

    def _ensure_tables(self):
        conn = self._conn()
        try:
            for ddl in DDL_TABLES:
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()

    def _check_ollama(self):
        try:
            req = urllib.request.Request(
                self.OLLAMA_URL,
                data=json.dumps({
                    "model": self.OLLAMA_MODEL,
                    "prompt": "ping",
                    "stream": False,
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=self.OLLAMA_TIMEOUT) as resp:
                body = json.loads(resp.read())
                return 'response' in body
        except Exception as e:
            log.info(f"[CenterCognition] Ollama not reachable: {e}")
            return False

    def _ollama_generate(self, prompt):
        """调用 Ollama qwen2.5:3b 生成文本"""
        if not self.ollama_available:
            return None
        try:
            req = urllib.request.Request(
                self.OLLAMA_URL,
                data=json.dumps({
                    "model": self.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 500},
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=self.OLLAMA_TIMEOUT) as resp:
                body = json.loads(resp.read())
                return body.get('response', '')
        except Exception as e:
            log.warning(f"[CenterCognition] Ollama generate error: {e}")
            return None

    @staticmethod
    def _sid(prefix='id'):
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    # ═══════════════════════════════════════════════════════════════
    # ① 中心职责画像 Portrait Generation
    # ═══════════════════════════════════════════════════════════════
    def _get_center_stats(self, center_name, days=7):
        """从 evolution_log 取该中心最近 N 天行为统计"""
        conn = self._conn(readonly=True)
        try:
            # 事件类型分布
            _since_days = f'-{days} days'
            rows = conn.execute(f"""
                SELECT event, COUNT(*) as cnt
                FROM mt_center_evolution_log
                WHERE center_name = ?
                  AND created_at >= datetime('now', ?)
                GROUP BY event
                ORDER BY cnt DESC
                LIMIT 20
            """, (center_name, _since_days)).fetchall()
            event_dist = [{"event": r[0], "count": r[1]} for r in rows]

            # 总事件数
            total = conn.execute(f"""
                SELECT COUNT(*) FROM mt_center_evolution_log
                WHERE center_name = ?
                  AND created_at >= datetime('now', ?)
            """, (center_name, _since_days)).fetchone()[0]

            # 健康分 (按星系归属)
            health_score = 0.0
            galaxy = CENTER_NAME_TO_GALAXY.get(center_name)
            if galaxy:
                hk = GALAXY_TO_HEALTH_KEY.get(galaxy)
                if hk and hk in HEALTH_COLUMN_MAP:
                    col = HEALTH_COLUMN_MAP[hk]
                    row = conn.execute(f"""
                        SELECT {col} FROM mt_center_health_matrix
                        ORDER BY created_at DESC LIMIT 1
                    """).fetchone()
                    if row:
                        health_score = row[0] or 0.0

            # 该中心绑定的 trigger handlers
            trigger_rows = conn.execute("""
                SELECT trigger_event_type, target_engine, target_method,
                       exec_count, avg_duration_ms
                FROM mt_trigger_handler
                WHERE target_engine LIKE ? OR target_method LIKE ?
                LIMIT 10
            """, (f'%{center_name}%', f'%{center_name}%')).fetchall()
            triggers = [{
                "event": r[0], "engine": r[1], "method": r[2],
                "exec_count": r[3], "avg_ms": r[4],
            } for r in trigger_rows]

            # 协作频率 (source)
            collab_src = conn.execute("""
                SELECT target_system, event_type, COUNT(*) as cnt
                FROM mt_collab_bus_events
                WHERE source LIKE ?
                GROUP BY target_system, event_type
                ORDER BY cnt DESC LIMIT 10
            """, (f'%{center_name}%',)).fetchall()
            collab_frequency = [{
                "target": r[0] or 'broadcast', "event_type": r[1], "count": r[2],
            } for r in collab_src]

            return {
                "center_name": center_name,
                "galaxy": galaxy or "unknown",
                "total_events_7d": total,
                "event_distribution": event_dist,
                "health_score": health_score,
                "triggers": triggers,
                "collab_frequency": collab_frequency,
            }
        finally:
            conn.close()

    def generate_portrait_ollama(self, center_name, stats):
        """Ollama 推理中心职责画像"""
        if not self.ollama_available:
            return None
        galaxy = stats.get('galaxy', 'unknown')
        events = [e['event'] for e in stats.get('event_distribution', [])[:10]]
        triggers = [t['event'] for t in stats.get('triggers', [])[:5]]

        prompt = f"""你是 AI 元认知引擎, 正在为 MTSCOS 的中心系统生成职责画像。
请用简洁中文输出 JSON (不要 markdown, 不要解释, 只要 JSON):

中心名称: {center_name}
所属星系: {galaxy}
7天内事件总数: {stats.get('total_events_7d', 0)}
事件类型 Top10: {events}
绑定触发器: {triggers}
健康分: {stats.get('health_score', 0)}

请生成:
{{
  "primary_duty": "一句话核心职责",
  "secondary_duty": "一句话次要职责",
  "boundaries": {{
    "can_do": ["能做的事情1", "能做的事情2"],
    "cannot_do": ["不能做的事情1", "不能做的事情2"]
  }},
  "ai_route": {{
    "recommended_engines": ["推荐调用的引擎名"],
    "warning": "警告 (如有)"
  }}
}}"""
        raw = self._ollama_generate(prompt)
        if not raw:
            return None
        # 尝试解析 JSON
        try:
            # 去掉可能的 markdown 代码块
            cleaned = raw.strip()
            if cleaned.startswith('```'):
                cleaned = cleaned.split('\n', 1)[-1].rsplit('```', 1)[0]
            return json.loads(cleaned)
        except Exception:
            log.debug(f"Ollama portrait raw parse failed for {center_name}: {raw[:100]}")
            return None

    def _seed_portrait_from_roles(self, center_name, galaxy, stats):
        """从 CENTER_ROLES 字典 seed 一个画像 (无 Ollama 时 fallback)"""
        role = CENTER_ROLES.get(galaxy, {})
        return {
            "primary_duty": role.get('primary_duty', f'{center_name} 核心职责'),
            "secondary_duty": role.get('secondary_duty', ''),
            "boundaries": {
                "can_do": role.get('core_engines', []),
                "cannot_do": [g for g in role.get('forbidden_galaxies', [])],
            },
            "ai_route": {
                "recommended_engines": role.get('core_engines', []),
                "warning": "基础画像, 建议用 Ollama 增强",
            },
        }

    def generate_all_portraits(self, use_ollama=True):
        """为所有已知中心生成 AI 职责画像"""
        conn = self._conn()
        try:
            # 获取所有已知中心 (evolution_log 里出现过的)
            all_center_rows = conn.execute(
                "SELECT DISTINCT center_name FROM mt_center_evolution_log ORDER BY center_name"
            ).fetchall()
            all_centers = [r[0] for r in all_center_rows]
            # 同时加上 health_matrix 里的 10 个星系 key
            all_centers += list(HEALTH_COLUMN_MAP.keys())
            # 去重保留顺序
            seen = set()
            unique_centers = []
            for c in all_centers:
                if c not in seen:
                    seen.add(c)
                    unique_centers.append(c)

            results = {}
            for center_name in unique_centers:
                galaxy = CENTER_NAME_TO_GALAXY.get(center_name) or \
                         (center_name if center_name in HEALTH_COLUMN_MAP else 'unknown')
                stats = self._get_center_stats(center_name)

                portrait = None
                if use_ollama and self.ollama_available:
                    portrait = self.generate_portrait_ollama(center_name, stats)

                if not portrait:
                    portrait = self._seed_portrait_from_roles(center_name, galaxy, stats)

                # 写入 portrait 表 (upsert)
                self._upsert_portrait(conn, center_name, galaxy, portrait, stats,
                                      ollama_generated=1 if portrait and use_ollama else 0)

                results[center_name] = {
                    "galaxy": galaxy,
                    "primary_duty": portrait.get('primary_duty', ''),
                    "health_score": stats.get('health_score', 0),
                }

            conn.commit()
            log.info(f"[CenterCognition] Generated {len(results)} center portraits")
            return results
        finally:
            conn.close()

    def _upsert_portrait(self, conn, center_name, galaxy, portrait, stats, ollama_generated=0):
        conn.execute("""
            INSERT INTO mt_center_cognition_portrait
                (portrait_id, center_name, galaxy, primary_duty, secondary_duty,
                 boundaries, ai_route, event_distribution, collab_frequency,
                 health_score, ollama_generated, generated_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))
            ON CONFLICT(center_name) DO UPDATE SET
                galaxy=excluded.galaxy,
                primary_duty=excluded.primary_duty,
                secondary_duty=excluded.secondary_duty,
                boundaries=excluded.boundaries,
                ai_route=excluded.ai_route,
                event_distribution=excluded.event_distribution,
                collab_frequency=excluded.collab_frequency,
                health_score=excluded.health_score,
                ollama_generated=excluded.ollama_generated,
                updated_at=datetime('now','localtime')
        """, (
            self._sid('port'),
            center_name,
            galaxy,
            portrait.get('primary_duty', ''),
            portrait.get('secondary_duty', ''),
            json.dumps(portrait.get('boundaries', {}), ensure_ascii=False),
            json.dumps(portrait.get('ai_route', {}), ensure_ascii=False),
            json.dumps(stats.get('event_distribution', []), ensure_ascii=False),
            json.dumps(stats.get('collab_frequency', []), ensure_ascii=False),
            stats.get('health_score', 0),
            ollama_generated,
        ))

    # ═══════════════════════════════════════════════════════════════
    # ② 跨中心协作矩阵 Collaboration Matrix
    # ═══════════════════════════════════════════════════════════════
    def build_collaboration_matrix(self, days=7):
        """扫描 collab_bus_events 构建协作热力图"""
        conn = self._conn()
        try:
            # 清空旧矩阵
            conn.execute("DELETE FROM mt_center_collab_matrix")

            # 扫描 collab_bus_events
            collab_rows = conn.execute("""
                SELECT source, source_system, target_system, event_type,
                       status, COUNT(*) as cnt, MAX(created_at) as last_ts
                FROM mt_collab_bus_events
                WHERE created_at >= datetime('now', ?)
                GROUP BY source, source_system, target_system
                ORDER BY cnt DESC
            """, (f'-{days} days',)).fetchall()

            matrix = {}
            # 先统计每个 source→target 的事件
            for r in collab_rows:
                source, src_sys, target_sys, evt_type, status, cnt, last_ts = r
                src_key = source or src_sys or 'unknown'
                tgt_key = target_sys or 'broadcast'
                pair = (src_key, tgt_key)

                # 只取有意义的 source (过滤 manual_test, self_test 等)
                if src_key in ('manual_test', 'self_test'):
                    continue

                if pair not in matrix:
                    matrix[pair] = {
                        "source": src_key,
                        "target": tgt_key,
                        "event_count": 0,
                        "event_types": Counter(),
                        "last_collab": last_ts,
                    }
                matrix[pair]["event_count"] += cnt
                if evt_type:
                    matrix[pair]["event_types"][evt_type] += 1
                if last_ts and (not matrix[pair]["last_collab"] or last_ts > matrix[pair]["last_collab"]):
                    matrix[pair]["last_collab"] = last_ts

            # 识别 relationship (谁依赖谁)
            # 入度高 = hub, 出度高 = source
            in_degree = Counter()
            out_degree = Counter()
            for (s, t), d in matrix.items():
                out_degree[s] += d["event_count"]
                if t != 'broadcast':
                    in_degree[t] += d["event_count"]

            # 写回 DB
            for (s, t), d in matrix.items():
                in_c = in_degree.get(t, 0)
                out_c = out_degree.get(s, 0)
                if in_c > out_c * 2:
                    rel = "DEPENDS_ON"    # target 比 source 活跃很多, source 依赖 target
                elif out_c > in_c * 2:
                    rel = "PROVIDES_TO"   # source 主动发起
                else:
                    rel = "PEER"

                # AI 建议 (简单规则)
                suggestion = ""
                if d["event_count"] > 100:
                    suggestion = "✅ 高频协作, 考虑建立专属事件通道"
                elif d["event_count"] < 3:
                    suggestion = "⚠ 低频协作, 检查是否应该增加"

                conn.execute("""
                    INSERT OR REPLACE INTO mt_center_collab_matrix
                        (matrix_id, source_center, target_center, event_count,
                         last_collab, event_types, relationship, suggested_upgrade)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    self._sid('mtrx'),
                    s, t,
                    d["event_count"],
                    d["last_collab"],
                    json.dumps(dict(d["event_types"]), ensure_ascii=False),
                    rel,
                    suggestion,
                ))

            conn.commit()
            log.info(f"[CenterCognition] Collab matrix built: {len(matrix)} pairs")

            # 返回 summary
            return {
                "total_pairs": len(matrix),
                "top_hubs": in_degree.most_common(5),
                "top_sources": out_degree.most_common(5),
                "low_freq": sum(1 for d in matrix.values() if d["event_count"] < 3),
            }
        finally:
            conn.close()

    def suggest_collaboration_upgrades(self):
        """AI 推荐协作提升点"""
        conn = self._conn(readonly=True)
        try:
            # 检查低频协作
            low_freq = conn.execute("""
                SELECT source_center, target_center, event_count
                FROM mt_center_collab_matrix
                WHERE event_count < 5
                ORDER BY event_count ASC
                LIMIT 10
            """).fetchall()
            # 检查高频过载
            overload = conn.execute("""
                SELECT target_center, SUM(event_count) as total_in
                FROM mt_center_collab_matrix
                GROUP BY target_center
                ORDER BY total_in DESC LIMIT 5
            """).fetchall()

            suggestions = []
            for r in low_freq:
                suggestions.append({
                    "type": "LOW_FREQ",
                    "source": r[0],
                    "target": r[1],
                    "count": r[2],
                    "action": f"考虑增加 {r[0]} → {r[1]} 协作频率",
                })
            for r in overload:
                suggestions.append({
                    "type": "OVERLOAD",
                    "target": r[0],
                    "total_in": r[1],
                    "action": f"{r[0]} 入站事件 {r[1]}, 考虑分流或扩容",
                })
            return suggestions
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # ③ 能力边界 Center Boundary (防止越权)
    # ═══════════════════════════════════════════════════════════════
    def compute_boundaries(self):
        """为每个中心计算能力边界"""
        conn = self._conn()
        try:
            # 先清空
            conn.execute("DELETE FROM mt_center_boundary")

            # 获取所有已知中心
            centers = conn.execute(
                "SELECT DISTINCT center_name FROM mt_center_evolution_log"
            ).fetchall()
            centers = [c[0] for c in centers]

            # 加上 health matrix 里的星系
            for hk in HEALTH_COLUMN_MAP:
                if hk not in centers:
                    centers.append(hk)

            all_boundaries = {}
            for center_name in centers:
                galaxy = CENTER_NAME_TO_GALAXY.get(center_name) or \
                         (center_name if center_name in HEALTH_COLUMN_MAP else 'unknown')

                # 从 evolution_log 推断能做什么 (行为历史)
                behavior_rows = conn.execute("""
                    SELECT event, COUNT(*) as cnt
                    FROM mt_center_evolution_log
                    WHERE center_name = ?
                    GROUP BY event
                    ORDER BY cnt DESC LIMIT 15
                """, (center_name,)).fetchall()
                known_events = [r[0] for r in behavior_rows]

                # from trigger handler
                trigger_rows = conn.execute("""
                    SELECT DISTINCT target_engine, trigger_event_type
                    FROM mt_trigger_handler
                    WHERE target_engine LIKE ?
                """, (f'%{center_name}%',)).fetchall()
                known_engines = list(set([r[0] for r in trigger_rows]))

                # 从 galaxy role 推断允许/禁止
                role = CENTER_ROLES.get(galaxy, {})
                can_do = list(set(known_events + known_engines + role.get('core_engines', [])))
                forbidden_patterns = []
                for fb_gal in role.get('forbidden_galaxies', []):
                    fb_role = CENTER_ROLES.get(fb_gal, {})
                    forbidden_patterns += fb_role.get('allowed_event_patterns', [])
                if not forbidden_patterns:
                    forbidden_patterns = [
                        'TRADE_', 'RISK_', 'LEDGER_', 'AUDIT_',    # gobelin 专属
                        'EXAM_', 'QBANK_',                         # iceberg 专属
                    ] if galaxy not in ('gobelin', 'audit') else []

                # 检测越权行为
                violations = self._scan_scope_violations(conn, center_name, forbidden_patterns)

                # Ollama 推理边界 (可选)
                ollama_reasoning = None
                if self.ollama_available:
                    prompt = f"""中心 {center_name} 属于星系 {galaxy}.
能做的事件: {known_events[:10]}
关联引擎: {known_engines[:5]}
禁止模式: {forbidden_patterns[:5]}
请输出一句话 (20字以内) 说明该中心的能力边界推理: """
                    ollama_reasoning = self._ollama_generate(prompt)

                # 写入
                recent_violations = len(violations) if violations else 0
                last_violation = violations[-1][1] if violations else None

                conn.execute("""
                    INSERT INTO mt_center_boundary
                        (boundary_id, center_name, can_do, cannot_do,
                         recent_violations, last_violation, ollama_reasoning)
                    VALUES (?,?,?,?,?,?,?)
                """, (
                    self._sid('bnd'),
                    center_name,
                    json.dumps(can_do[:20], ensure_ascii=False),
                    json.dumps(forbidden_patterns[:10], ensure_ascii=False),
                    recent_violations,
                    last_violation,
                    ollama_reasoning or '',
                ))
                all_boundaries[center_name] = {
                    "galaxy": galaxy,
                    "can_do_count": len(can_do),
                    "cannot_do_count": len(forbidden_patterns),
                    "violations": recent_violations,
                }

            conn.commit()
            log.info(f"[CenterCognition] Boundaries computed: {len(all_boundaries)} centers")
            return all_boundaries
        finally:
            conn.close()

    def _scan_scope_violations(self, conn, center_name, forbidden_patterns):
        """扫描该中心是否有越权 (执行了禁止的事件模式)"""
        violations = []
        if not forbidden_patterns:
            return violations
        rows = conn.execute("""
            SELECT event, created_at FROM mt_center_evolution_log
            WHERE center_name = ?
            ORDER BY created_at DESC LIMIT 200
        """, (center_name,)).fetchall()
        for evt, ts in rows:
            for pat in forbidden_patterns:
                if pat.endswith('_') and evt.startswith(pat[:-1]):
                    violations.append((evt, ts))
                elif not pat.endswith('_') and pat in evt:
                    violations.append((evt, ts))
                    break
        return violations[-5:]  # 只返回最近 5 个

    def detect_scope_violations(self):
        """检查全系统最近越权情况"""
        conn = self._conn(readonly=True)
        try:
            rows = conn.execute("""
                SELECT center_name, recent_violations, last_violation
                FROM mt_center_boundary
                WHERE recent_violations > 0
                ORDER BY recent_violations DESC
            """).fetchall()
            return [{
                "center": r[0], "violations": r[1], "last": r[2],
            } for r in rows]
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # ④ AI ROUTE — 为中心推荐引擎/技能
    # ═══════════════════════════════════════════════════════════════
    def ai_route_for_center(self, center_name, task=None):
        """为指定中心推荐 AI 路由"""
        conn = self._conn(readonly=True)
        try:
            # 取画像 + 边界
            portrait = conn.execute("""
                SELECT galaxy, ai_route, boundaries FROM mt_center_cognition_portrait
                WHERE center_name = ?
            """, (center_name,)).fetchone()

            if not portrait:
                return {"status": "no_portrait", "center": center_name}

            galaxy = portrait[0]
            ai_route = json.loads(portrait[1] or '{}')
            boundaries = json.loads(portrait[2] or '{}')

            # 取该中心的 trigger handlers (可用引擎)
            handlers = conn.execute("""
                SELECT DISTINCT target_engine, target_method, exec_count, avg_duration_ms
                FROM mt_trigger_handler
                WHERE trigger_event_type IN (
                    SELECT trigger_event_type FROM mt_trigger_handler
                    WHERE target_engine LIKE ?
                )
                LIMIT 15
            """, (f'%{center_name}%',)).fetchall()

            # 取 AI capability registry 里匹配的
            capabilities = conn.execute("""
                SELECT capability_name, health_score, success_rate, usage_count
                FROM mt_ai_capability_registry
                WHERE enabled=1
                  AND (description LIKE ? OR capability_name LIKE ?)
                ORDER BY health_score DESC LIMIT 10
            """, (f'%{galaxy}%', f'%{center_name}%')).fetchall()

            # 组装推荐
            recommended = ai_route.get('recommended_engines', [])
            if not recommended:
                role = CENTER_ROLES.get(galaxy, {})
                recommended = role.get('core_engines', [])

            if task and self.ollama_available:
                # Ollama 针对特定 task 优化路由
                prompt = f"""中心 {center_name} (星系 {galaxy}) 现在要执行任务: {task}
可用引擎: {recommended[:10]}
历史 handler: {[h[0] for h in handlers[:5]]}
请推荐 TOP 3 引擎 (JSON array): """
                ollama_r = self._ollama_generate(prompt)
                if ollama_r:
                    try:
                        cleaned = ollama_r.strip()
                        if cleaned.startswith('```'):
                            cleaned = cleaned.split('\n',1)[-1].rsplit('```',1)[0]
                        task_specific = json.loads(cleaned)
                        if isinstance(task_specific, list):
                            recommended = list(task_specific) + recommended
                    except Exception:
                        pass

            # 去重 + 过滤空
            seen = set()
            final_rec = []
            for e in recommended:
                if e and e not in seen:
                    seen.add(e)
                    final_rec.append(e)

            return {
                "center": center_name,
                "galaxy": galaxy,
                "task": task,
                "recommended_engines": final_rec[:10],
                "warning": ai_route.get('warning', ''),
                "boundary_can_do": boundaries.get('can_do', []),
                "boundary_cannot_do": boundaries.get('cannot_do', []),
                "historical_handlers": [{
                    "engine": h[0], "method": h[1],
                    "exec_count": h[2], "avg_ms": h[3],
                } for h in handlers],
                "matching_capabilities": [{
                    "name": c[0], "health": c[1],
                    "success_rate": c[2], "usage": c[3],
                } for c in capabilities],
            }
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # ⑤ CENTER EXPERIENCE — 从历史行为提炼经验
    # ═══════════════════════════════════════════════════════════════
    def distill_center_experience(self, center_name):
        """提炼该中心专属经验"""
        conn = self._conn()
        try:
            # 清空该中心旧经验
            conn.execute("DELETE FROM mt_center_experience WHERE center_name=?", (center_name,))

            experiences = []

            # 成功模式: 该中心稳定执行的事件
            stable_events = conn.execute("""
                SELECT event, COUNT(*) as cnt
                FROM mt_center_evolution_log
                WHERE center_name = ?
                GROUP BY event
                HAVING cnt > 100
                ORDER BY cnt DESC LIMIT 5
            """, (center_name,)).fetchall()
            for evt, cnt in stable_events:
                experiences.append({
                    "center_name": center_name,
                    "exp_type": "SUCCESS_PATTERN",
                    "summary": f"{center_name} 执行 {evt} 稳定 {cnt} 次",
                    "lesson": f"{evt} 是 {center_name} 的核心能力, 可复用",
                    "confidence": min(0.95, cnt / 1000),
                    "source_events": json.dumps([evt], ensure_ascii=False),
                    "applicable_engines": json.dumps(
                        [r[0] for r in conn.execute("""
                            SELECT DISTINCT target_engine FROM mt_trigger_handler
                            WHERE trigger_event_type LIKE ?
                        """, (f'%{evt[:10]}%',)).fetchall()[:3]],
                        ensure_ascii=False,
                    ),
                })

            # 健康矩阵短板 → 建议经验
            galaxy = CENTER_NAME_TO_GALAXY.get(center_name) or \
                     (center_name if center_name in HEALTH_COLUMN_MAP else None)
            if galaxy and galaxy in HEALTH_COLUMN_MAP:
                col = HEALTH_COLUMN_MAP[galaxy]
                row = conn.execute(
                    f"SELECT {col} FROM mt_center_health_matrix ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if row and row[0] and row[0] < 70:
                    experiences.append({
                        "center_name": center_name,
                        "exp_type": "PERF_ISSUE",
                        "summary": f"{center_name} 健康分 {row[0]:.1f} (短板)",
                        "lesson": f"建议触发对应自愈 / 增强动作",
                        "confidence": 0.8,
                        "source_events": "[]",
                        "applicable_engines": json.dumps(
                            CENTER_ROLES.get(galaxy, {}).get('core_engines', [])[:3],
                            ensure_ascii=False,
                        ),
                    })

            # 触发器经验: 高 exec_count + 低 avg_duration = 高效 handler
            efficient_handlers = conn.execute("""
                SELECT handler_key, target_engine, trigger_event_type,
                       exec_count, avg_duration_ms
                FROM mt_trigger_handler
                WHERE enabled=1
                  AND exec_count > 50
                  AND avg_duration_ms < 500
                ORDER BY avg_duration_ms ASC
                LIMIT 5
            """).fetchall()
            for hk, eng, evt, cnt, ms in efficient_handlers:
                # 只关联到 matching center
                if center_name in eng or CENTER_NAME_TO_GALAXY.get(center_name, '') in eng:
                    experiences.append({
                        "center_name": center_name,
                        "exp_type": "PERF",
                        "summary": f"{eng} 处理 {evt}: {cnt}次, 平均{ms:.0f}ms",
                        "lesson": f"{eng} 是高效 handler, 建议复用",
                        "confidence": 0.85,
                        "source_events": json.dumps([evt], ensure_ascii=False),
                        "applicable_engines": json.dumps([eng], ensure_ascii=False),
                    })

            # 写入
            for exp in experiences:
                conn.execute("""
                    INSERT INTO mt_center_experience
                        (exp_id, center_name, exp_type, summary, lesson,
                         confidence, source_events, applicable_engines)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    self._sid('exp'),
                    exp["center_name"], exp["exp_type"], exp["summary"],
                    exp["lesson"], exp["confidence"], exp["source_events"],
                    exp["applicable_engines"],
                ))

            conn.commit()
            log.info(f"[CenterCognition] {center_name}: {len(experiences)} experiences distilled")

            return {
                "center": center_name,
                "count": len(experiences),
                "types": list(set([e["exp_type"] for e in experiences])),
            }
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # MAIN: EMPOWER ALL
    # ═══════════════════════════════════════════════════════════════
    def empower_all_centers(self):
        """一键赋能所有中心 — 完整运行 ①→⑤"""
        t0 = time.time()
        log.info("=" * 60)
        log.info("🧠 CENTER COGNITION ENGINE — EMPOWER ALL CENTERS")
        log.info("=" * 60)

        result = {
            "timestamp": datetime.now().isoformat(),
            "ollama_available": self.ollama_available,
            "portraits": {},
            "collab": {},
            "boundaries": {},
            "routes": {},
            "experiences": {},
            "duration_ms": 0,
        }

        # ① 画像
        log.info("[1/5] Generating portraits...")
        result["portraits"] = self.generate_all_portraits(use_ollama=True)

        # ② 协作矩阵
        log.info("[2/5] Building collaboration matrix...")
        result["collab"] = self.build_collaboration_matrix(days=7)

        # ③ 边界
        log.info("[3/5] Computing boundaries...")
        result["boundaries"] = self.compute_boundaries()

        # ④ + ⑤ 路由 & 经验 (对每个画像中心)
        conn = self._conn(readonly=True)
        try:
            portrait_centers = [r[0] for r in conn.execute(
                "SELECT center_name FROM mt_center_cognition_portrait ORDER BY health_score ASC"
            ).fetchall()]
        finally:
            conn.close()

        for i, center in enumerate(portrait_centers):
            log.info(f"[4/5] AI route + experience for {center} ({i+1}/{len(portrait_centers)})...")
            try:
                result["routes"][center] = self.ai_route_for_center(center)
            except Exception as e:
                result["routes"][center] = {"error": str(e)}
            try:
                result["experiences"][center] = self.distill_center_experience(center)
            except Exception as e:
                result["experiences"][center] = {"error": str(e)}

        result["duration_ms"] = int((time.time() - t0) * 1000)
        log.info(f"✅ EMPOWER ALL DONE — {result['duration_ms']}ms")
        log.info(f"   Portraits: {len(result['portraits'])} centers")
        log.info(f"   Collab pairs: {result['collab'].get('total_pairs', 0)}")
        log.info(f"   Boundaries: {len(result['boundaries'])} centers")
        log.info(f"   Routes: {len(result['routes'])} centers")
        log.info(f"   Experiences: {sum(v.get('count', 0) for v in result['experiences'].values())} entries")

        return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════
def main():
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else None
    cmd = sys.argv[2] if len(sys.argv) > 2 else 'empower'
    cce = CenterCognitionEngine(db)

    if cmd == 'empower':
        result = cce.empower_all_centers()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:2000])
    elif cmd == 'portraits':
        r = cce.generate_all_portraits()
        print(f"Generated {len(r)} portraits")
    elif cmd == 'collab':
        r = cce.build_collaboration_matrix()
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif cmd == 'boundaries':
        r = cce.compute_boundaries()
        print(f"Computed {len(r)} boundaries")
    elif cmd == 'route':
        target = sys.argv[3] if len(sys.argv) > 3 else 'gobelin'
        task = sys.argv[4] if len(sys.argv) > 4 else None
        print(json.dumps(cce.ai_route_for_center(target, task), ensure_ascii=False, indent=2))
    elif cmd == 'experience':
        target = sys.argv[3] if len(sys.argv) > 3 else 'gobelin_trading'
        print(json.dumps(cce.distill_center_experience(target), ensure_ascii=False, indent=2))
    elif cmd == 'violations':
        print(json.dumps(cce.detect_scope_violations(), ensure_ascii=False, indent=2))
    else:
        print("Usage: center_cognition_engine.py [db_path] [empower|portraits|collab|boundaries|route <name>|experience <name>|violations]")


if __name__ == "__main__":
    main()
