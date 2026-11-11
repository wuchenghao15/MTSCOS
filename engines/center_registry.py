#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ MTSCOS 30 Center Registry — 功能中心注册表
───────────────────────────────────────────────
将 MTSCOS 所有引擎 / 蓝图 / 数据表 组织成 30 个功能中心.

数据源:
  - engines/      ← 271 个 .py 引擎
  - blueprints/   ← 41 个 .py 蓝图
  - database/     ← 273 张 SQLite 表

用法:
  from engines.center_registry import CENTER_REGISTRY, auto_discover_centers
  stats = auto_discover_centers()  # 验证所有条目 + 补充遗漏
"""

import os
import re
import sqlite3
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════════════════
# 📂 路径 (相对于 flask-app 根目录)
# ═══════════════════════════════════════════════════════════════════════════

_FLASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINES_DIR = os.path.join(_FLASK_ROOT, "engines")
_BLUEPRINTS_DIR = os.path.join(_FLASK_ROOT, "blueprints")
_DB_PATH = os.path.join(_FLASK_ROOT, "database", "app.db")

# 排除模式: 备份 / 测试 / __init__ / CLI / 数据文件
_EXCLUDE_SUFFIX = (
    ".auto_repair_backup", ".bak", ".bak_p", ".bak2", ".bak3",
    ".bak_orderfix", ".deprecated", ".inspect_bak",
)
_EXCLUDE_PREFIX = ("test_", )
_EXCLUDE_FILENAMES = {
    "__init__.py", "compute_router_test.py", "verify_round8_engine.py",
    "generate_andromeda_25.py", "keepalive_engines.py", "dev_flow_cli.py",
    "dev_gate.py", "dev_gate.py.auto_repair_backup", "roundtable_orchestrator.py.inspect_bak",
}

# ═══════════════════════════════════════════════════════════════════════════
# 🏛️ 30 CENTER REGISTRY
# ═══════════════════════════════════════════════════════════════════════════
# 按真实文件前缀/命名模式分类.  条目名 = 文件名 (不含 .py)
# auto_discover_centers() 会验证每个条目的存在性并补充遗漏.

CENTER_REGISTRY = {

    # ─────────────────────────────────────────────────────────────────────
    # 🧠 仙女座星系 Andromeda Galaxy  (主控大脑, 8 中心)
    # ─────────────────────────────────────────────────────────────────────

    "andromeda_core": {
        "name": "仙女座核心",
        "role": "大脑指挥",
        "color": "#7B2DFF",
        "galaxy": "andromeda",
        "engines": [
            "andromeda_core", "andromeda_base", "andromeda_meta_cognition",
            "andromeda_bridge", "andromeda_mcp_bridge", "andromeda_research",
            "andromeda_status_page", "andromeda_notifier", "andromeda_code_hygiene_engine",
            "andromeda_prompt_learning_pipeline", "andromeda_society_engine",
            "andromeda_cluster_matrix", "andromeda_compute_elasticity",
            "andromeda_workflow_engine", "andromeda_upgrade", "andromeda_auto_evolution",
            "andromeda_auto_loop", "ai_center_consultation_engine",
            "ai_center_hall_hook_engine", "ai_center_relation_engine",
            "ai_center_remote_agent", "ai_center_self_drive_engine",
            "ai_strategy_center_engine", "ai_finance_center_engine",
            "ai_center_self_drive_engine", "aurora_skill_registry",
        ],
        "blueprints": [
            "andromeda_chat_bp", "andromeda_openai_bp", "andromeda_stats_bp",
        ],
        "tables": [
            "mt_center_evolution_log", "mt_version_center", "mt_skill_registry",
            "ai_cluster_config", "ai_cluster_employee", "ai_config_history",
            "ai_config_snapshot", "ai_employee_config", "ai_employees",
            "ai_extension_records", "chat_actions", "chat_inflection_points",
            "chat_messages", "chat_sessions",
        ],
    },

    "autopilot_v2": {
        "name": "自动驾驶",
        "role": "自主决策",
        "color": "#FF6B2D",
        "galaxy": "andromeda",
        "engines": [
            "andromeda_autopilot_v2", "ai_sandbox_tick_engine",
            "ai_sandbox_meeting_auto", "ai_equity_alert",
            "holiday_trigger_engine", "weekend_saturday_engine",
            "weekend_sunday_engine",
        ],
        "blueprints": [],
        "tables": [
            "mt_fm_brain_feed", "mt_center_self_check",
        ],
    },

    "event_bus": {
        "name": "协作总线",
        "role": "消息路由",
        "color": "#2DFFB3",
        "galaxy": "andromeda",
        "engines": [
            "event_bus_engine", "collab_bus_engine", "trigger_evolution_broadcast",
            "collab_bus_engine", "ai_team_collab_engine",
            "community_governance_engine", "roundtable_orchestrator",
        ],
        "blueprints": [
            "collab_bus_bp", "team_collab_bp",
        ],
        "tables": [
            "agent_registry", "agent_state",
        ],
    },

    "orchestrator": {
        "name": "编排中心",
        "role": "流水线串联",
        "color": "#2DB3FF",
        "galaxy": "andromeda",
        "engines": [
            "center_orchestrator", "workflow_engine", "workflow_registry",
            "sys_center_evolution", "sys_center_autonomous_learner",
        ],
        "blueprints": [],
        "tables": [],
    },

    "autodev": {
        "name": "自研发中心",
        "role": "AI 自动编程",
        "color": "#FF2DB3",
        "galaxy": "andromeda",
        "engines": [
            "autodev_engine", "auto_dev_team_engine", "auto_doc_generator",
            "dev_flow_cli", "dev_gate",
            "deploy_mac_autoloader", "frontend_enhancer",
        ],
        "blueprints": [],
        "tables": [],
    },

    "self_heal": {
        "name": "自治愈中心",
        "role": "自动修复",
        "color": "#FF2D5E",
        "galaxy": "andromeda",
        "engines": [
            "cross_self_heal", "andromeda_self_heal", "auto_repair_engine",
            "ai_auto_diagnose_and_fix_engine", "ai_disaster_recovery_engine",
            "sys_auto_repair_cycle", "sys_copy_auto_repair",
            "sys_wendaemon", "ai_suggested_repair_engine",
        ],
        "blueprints": [
            "disaster_recovery_bp",
        ],
        "tables": [],
    },

    "warden": {
        "name": "守护进程",
        "role": "健康监控",
        "color": "#FFD72D",
        "galaxy": "andromeda",
        "engines": [
            "andromeda_warden", "data_monitor_daemon", "ai_console_monitor",
            "fm_listener_daemon", "intel_gateway_daemon",
            "screen_monitor_daemon", "usb_hub_monitor",
            "mini_sync_watchdog", "mini_evolution_engine",
            "mac_mini_sync_engine", "smart_sync",
        ],
        "blueprints": [
            "system_health_bp",
        ],
        "tables": [
            "health_snapshots",
        ],
    },

    "goal_engine": {
        "name": "目标引擎",
        "role": "OKR / 目标追踪",
        "color": "#B32DFF",
        "galaxy": "andromeda",
        "engines": [
            "andromeda_goal_engine", "ai_org_growth_engine",
            "ai_hall_force_and_audit",
        ],
        "blueprints": [],
        "tables": [],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 💰 古灵阁金融 Gobelin Finance  (7 中心)
    # ─────────────────────────────────────────────────────────────────────

    "gobelin_core": {
        "name": "古灵阁核心",
        "role": "银行中枢",
        "color": "#D4A017",
        "galaxy": "gobelin",
        "engines": [
            "ai_finance_center_engine", "gobelin_daily_pnl", "auto_quant_adapter",
            "galaxy_db",
        ],
        "blueprints": [
            "gobelin_bp", "finance_bank_bp",
        ],
        "tables": [
            "mt_center_knowledge_points",
        ],
    },

    "gobelin_trading": {
        "name": "交易引擎",
        "role": "策略执行",
        "color": "#2DFF6B",
        "galaxy": "gobelin",
        "engines": [
            "ai_stock_sandbox_engine", "ai_sandbox_tick_engine",
            "simulation_sandbox_engine", "ai_equity_alert",
        ],
        "blueprints": [
            "stock_sandbox_bp", "sandbox_bp",
        ],
        "tables": [
            "daily_practice",
        ],
    },

    "gobelin_risk": {
        "name": "风控中心",
        "role": "风险评估",
        "color": "#FF4D2D",
        "galaxy": "gobelin",
        "engines": [
            "finance_risk_engine", "ai_iron_rule_guard",
            "ai_rule_learning_engine", "shield_daemon",
        ],
        "blueprints": [
            "gobelin_shield_bp",
        ],
        "tables": [],
    },

    "gobelin_ledger": {
        "name": "会计引擎",
        "role": "双账本",
        "color": "#FFAA2D",
        "galaxy": "gobelin",
        "engines": [
            "finance_ledger_engine",
        ],
        "blueprints": [],
        "tables": [],
    },

    "gobelin_audit": {
        "name": "稽查盾牌",
        "role": "合规审计",
        "color": "#FF6B2D",
        "galaxy": "gobelin",
        "engines": [
            "finance_audit_daemon", "finance_realtime_audit",
            "ai_hall_force_and_audit", "code_audit_daemon",
            "deep_inspection_engine",
        ],
        "blueprints": [
            "finance_audit_bp", "rule_committee_bp", "vault_bp",
        ],
        "tables": [
            "change_audit_log",
        ],
    },

    "gobelin_attribution": {
        "name": "业绩归因",
        "role": "收益分解",
        "color": "#FF882D",
        "galaxy": "gobelin",
        "engines": [
            "finance_attribution",
        ],
        "blueprints": [],
        "tables": [],
    },

    "gobelin_report": {
        "name": "日报中心",
        "role": "自动报告",
        "color": "#FFBB2D",
        "galaxy": "gobelin",
        "engines": [
            "finance_daily_report", "auto_doc_generator",
        ],
        "blueprints": [],
        "tables": [],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 🧊 冰山教育 Iceberg Education  (4 中心)
    # ─────────────────────────────────────────────────────────────────────

    "iceberg_qbank": {
        "name": "题库引擎",
        "role": "题目生成/检索",
        "color": "#2DFFFF",
        "galaxy": "iceberg",
        "engines": [
            "listening_qbank_build_v2", "listening_qbank_extend",
            "qbank_brain_adapter", "iceberg_qbank_adaptive",
            "ai_suggested_edu_bank_engine",
        ],
        "blueprints": [],
        "tables": [
            "crawled_questions", "generation_history",
        ],
    },

    "iceberg_content": {
        "name": "文案矩阵",
        "role": "内容意识",
        "color": "#2D88FF",
        "galaxy": "iceberg",
        "engines": [
            "iceberg_content_matrix", "iceberg_consciousness",
            "iceberg_meta_model", "iceberg_command",
            "iceberg_handshake", "iceberg_slang_substitution",
            "galaxy_content_engine", "domain_knowledge_seeder",
            "bulk_knowledge_injector",
        ],
        "blueprints": [
            "iceberg_archive_bp",
        ],
        "tables": [],
    },

    "iceberg_exam": {
        "name": "考试院",
        "role": "考试/评测",
        "color": "#4DAAFF",
        "galaxy": "iceberg",
        "engines": [
            "ai_exam_auto_engine", "ai_edu_learning_engine",
            "ai_edu_sync_engine", "ai_edu_thinking_engine",
            "edu_flywheel_engine", "edu_p1_smart_engine",
            "education_enhancer", "education_path_planner",
            "ai_medical_center_engine",
        ],
        "blueprints": [
            "exam_auto_daemon_bp", "medical_center_bp", "ai_edu_academy_bp",
        ],
        "tables": [
            "daily_practice", "exam_assignment", "exam_results",
            "exam_sessions", "test_results", "test_sessions",
            "test_recommendations", "topic_training_progress", "topic_training_topics",
            "wrong_book", "k12_admission_plans", "k12_evaluations",
            "k12_game_points", "k12_home_school_messages",
        ],
    },

    "iceberg_lang": {
        "name": "语言赛道",
        "role": "多语教学",
        "color": "#66BBFF",
        "galaxy": "iceberg",
        "engines": [
            "ai_english_track_engine", "ai_cnkr_track_engine",
            "ai_language_pedagogy_engine", "ai_language_org_alignment_engine",
            "ai_math_pedagogy_engine", "ai_math_models_engine",
            "i18n_engine", "ai_fanhua_engine", "ai_fanli_engine", "ai_fanyin_engine",
        ],
        "blueprints": [
            "english_track_bp", "cnkr_track_bp",
            "ai_language_pedagogy_bp", "ai_math_pedagogy_bp",
        ],
        "tables": [
            "jp_grammar", "jp_grammar_progress", "jp_kana_progress",
            "jp_listening", "jp_listening_records", "jp_reading",
            "jp_reading_records", "jp_vocabulary", "jp_vocabulary_progress",
            "jp_wordbook",
        ],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 🧠 脑库记忆 Brain Memory  (2 中心)
    # ─────────────────────────────────────────────────────────────────────

    "brain_feed": {
        "name": "脑库投喂",
        "role": "外部信号",
        "color": "#FF2DFF",
        "galaxy": "brain",
        "engines": [
            "ai_brain_feed_engine", "ai_brain_vector_engine",
            "brain_feeding_engine", "fm_listener_daemon",
            "galaxy_daemon",
        ],
        "blueprints": [],
        "tables": [
            "mt_fm_brain_feed",
        ],
    },

    "brain_knowledge": {
        "name": "知识聚合",
        "role": "知识中台",
        "color": "#CC2DFF",
        "galaxy": "brain",
        "engines": [
            "ai_knowledge_aggregator_engine", "bulk_knowledge_injector",
            "ai_archive_engine", "ai_archive_archaeology_engine",
            "ai_data_archive_engine",
        ],
        "blueprints": [
            "iceberg_archive_bp",
        ],
        "tables": [],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 🧬 因子特征 EigenFlux  (1 中心)
    # ─────────────────────────────────────────────────────────────────────

    "eigenflux": {
        "name": "特征流",
        "role": "动态专家雇佣",
        "color": "#00FF88",
        "galaxy": "eigenflux",
        "engines": [
            "ai_eigenflux_network_engine", "eigenflux_auto_vote",
            "eigenflux_broadcast_engine", "eigenflux_dynamic_invite",
            "eigenflux_proactive_engine", "ai_patrol_eigenflux_advisor_engine",
            "ai_feature_evolution_engine",
        ],
        "blueprints": [],
        "tables": [
            "eigenflux_experts", "expert_invitation_records",
        ],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 👥 人力技能 HR Skill  (1 中心)
    # ─────────────────────────────────────────────────────────────────────

    "hr_skill": {
        "name": "人力技能",
        "role": "招聘/技能挖掘",
        "color": "#FF882D",
        "galaxy": "hr",
        "engines": [
            "ai_hr_center_engine", "ai_skill_deriver_engine",
            "ai_auto_hire_engine", "ai_proposal_inquiry_engine",
            "ai_proposal_intelligence_engine",
            "proposal_scorer_engine",
        ],
        "blueprints": [],
        "tables": [],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 📋 任务大厅 Task Hall  (1 中心)
    # ─────────────────────────────────────────────────────────────────────

    "task_hall": {
        "name": "任务大厅",
        "role": "派单/审批",
        "color": "#2D88FF",
        "galaxy": "task",
        "engines": [
            "ai_task_hall_approval_engine", "ai_task_hall_flow_engine",
            "ai_task_hall_landing_engine", "approvals_engine",
            "sys_auto_approval_daemon", "sys_blockchain_engine",
            "ai_sa_veto_module", "aurora_skill_registry",
        ],
        "blueprints": [
            "rule_committee_bp", "sa_prime_bp", "sa_terminal_auth_bp",
        ],
        "tables": [
            "approval_requests",
        ],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 🛡️ 安全防护 Security Shield  (2 中心)
    # ─────────────────────────────────────────────────────────────────────

    "shield": {
        "name": "盾牌防护",
        "role": "实时防护",
        "color": "#FF2D5E",
        "galaxy": "security",
        "engines": [
            "shield_daemon", "shield_inject_middleware",
            "local_security_manifest", "security_enhancer",
            "sensitivity_classifier", "omni_defense_engine",
            "ai_security_brigade_engine", "ai_link_guard_engine",
        ],
        "blueprints": [
            "gobelin_shield_bp", "threat_intel_bp", "whitehat_hunt_bp",
        ],
        "tables": [
            "ai_firewall_rules",
        ],
    },

    "firewall": {
        "name": "防火墙",
        "role": "边界硬化",
        "color": "#B30000",
        "galaxy": "security",
        "engines": [
            "firewall_hardening_engine", "penetration_tester",
            "auto_sniff_engine", "auto_rule_strengthener",
            "ai_iron_rule_guard", "gray_release_engine",
        ],
        "blueprints": [
            "backup_webhook_bp",
        ],
        "tables": [
            "ai_firewall_rules",
        ],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 🎨 媒体创作 Media Creation  (3 中心)
    # ─────────────────────────────────────────────────────────────────────

    "gobelin_video": {
        "name": "视频创作",
        "role": "视频渲染",
        "color": "#FF2D88",
        "galaxy": "media",
        "engines": [
            "galaxy_video_renderer", "galaxy_jimeng_pipeline",
            "learn_jimeng_capcut", "galaxy_composition_engine",
        ],
        "blueprints": [
            "gobelin_video_bp",
        ],
        "tables": [],
    },

    "gobelin_music": {
        "name": "音乐创作",
        "role": "音乐生成",
        "color": "#882DFF",
        "galaxy": "media",
        "engines": [
            "galaxy_composition_engine",
        ],
        "blueprints": [
            "gobelin_music_bp",
        ],
        "tables": [],
    },

    "gobelin_writing": {
        "name": "写作中心",
        "role": "文案生产",
        "color": "#D4A017",
        "galaxy": "media",
        "engines": [
            "ai_writing_pipeline_engine", "literary_troupe_scriptwriter",
            "ai_fuyin_engine", "ai_ziwei_engine",
            "galaxy_mimicry_engine",
        ],
        "blueprints": [
            "gobelin_writing_bp",
        ],
        "tables": [],
    },

    # ─────────────────────────────────────────────────────────────────────
    # ⚙️ 基础设施 Infrastructure  (3 中心)
    # ─────────────────────────────────────────────────────────────────────

    "time_sync": {
        "name": "时间同步",
        "role": "时间守护者",
        "color": "#FFD72D",
        "galaxy": "infra",
        "engines": [
            "time_sync_engine",
        ],
        "blueprints": [],
        "tables": [
            "mt_time_sync_log",
        ],
    },

    "db_sync": {
        "name": "数据同步",
        "role": "DB 多活",
        "color": "#2DFFFF",
        "galaxy": "infra",
        "engines": [
            "db_triple_sync_engine", "bidirectional_sync",
            "smart_sync", "doc_sync_engine",
            "ai_data_center_engine", "ai_data_partition_engine",
            "ai_data_archive_engine", "ai_nas_storage_engine",
            "mac_mini_sync_engine",
        ],
        "blueprints": [],
        "tables": [],
    },

    "version": {
        "name": "版本中心",
        "role": "版本管理",
        "color": "#888888",
        "galaxy": "infra",
        "engines": [
            "ai_version_center_engine", "ai_backup_engine",
            "ai_backup_kernel", "ai_multi_layer_backup",
            "galaxy_db",
        ],
        "blueprints": [
            "backup_webhook_bp",
        ],
        "tables": [
            "mt_version_center",
        ],
    },

    # ─────────────────────────────────────────────────────────────────────
    # 🖥️ 计算路由 Compute Routing  (1 中心)
    # ─────────────────────────────────────────────────────────────────────

    "compute_router": {
        "name": "计算路由",
        "role": "AI 模型路由",
        "color": "#2DB3FF",
        "galaxy": "compute",
        "engines": [
            "compute_router", "galaxy_ai_model_router",
            "ai_local_inference_engine", "ai_neural_hub",
            "ai_neural_evolution_daemon",
        ],
        "blueprints": [
            "ai_engine",
        ],
        "tables": [
            "ai_model_call_logs", "ai_model_groups", "ai_models",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# 🔍 自动发现 & 验证函数
# ═══════════════════════════════════════════════════════════════════════════

def _list_engines():
    """列出 engines/ 目录下的有效 .py 文件名 (不含扩展名)"""
    result = []
    if not os.path.isdir(_ENGINES_DIR):
        return result
    for f in os.listdir(_ENGINES_DIR):
        # 排除子目录
        if os.path.isdir(os.path.join(_ENGINES_DIR, f)):
            continue
        if not f.endswith(".py"):
            continue
        if f in _EXCLUDE_FILENAMES:
            continue
        skip = False
        for suf in _EXCLUDE_SUFFIX:
            if f.endswith(suf) or suf in f:
                skip = True
                break
        for pre in _EXCLUDE_PREFIX:
            if f.startswith(pre):
                skip = True
                break
        if skip:
            continue
        name = f[:-3]  # 去掉 .py
        result.append(name)
    return sorted(set(result))


def _list_blueprints():
    """列出 blueprints/ 目录下的有效 .py 文件名"""
    result = []
    if not os.path.isdir(_BLUEPRINTS_DIR):
        return result
    for f in os.listdir(_BLUEPRINTS_DIR):
        if os.path.isdir(os.path.join(_BLUEPRINTS_DIR, f)):
            continue
        if not f.endswith(".py"):
            continue
        if f == "__init__.py":
            continue
        skip = False
        for suf in (".bak", ".bak."):
            if suf in f:
                skip = True
                break
        if skip:
            continue
        result.append(f[:-3])
    return sorted(set(result))


def _list_db_tables():
    """列出 SQLite DB 所有表"""
    if not os.path.isfile(_DB_PATH):
        return []
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        conn.close()
        return tables
    except Exception:
        return []


def _match_center_by_engine_name(engine_name):
    """根据引擎名称模糊匹配最合适的中心"""
    name_lower = engine_name.lower()

    # 关键词匹配 (按优先级排序)
    keyword_map = [
        ("andromeda", "andromeda_core"),
        ("gobelin", "gobelin_core"),
        ("finance", "gobelin_core"),
        ("stock_sandbox", "gobelin_trading"),
        ("stock", "gobelin_trading"),
        ("ledger", "gobelin_ledger"),
        ("audit", "gobelin_audit"),
        ("risk", "gobelin_risk"),
        ("attribution", "gobelin_attribution"),
        ("daily_report", "gobelin_report"),
        ("iceberg", "iceberg_content"),
        ("qbank", "iceberg_qbank"),
        ("exam", "iceberg_exam"),
        ("english_track", "iceberg_lang"),
        ("cnkr", "iceberg_lang"),
        ("math_pedagogy", "iceberg_lang"),
        ("language_pedagogy", "iceberg_lang"),
        ("brain_feed", "brain_feed"),
        ("brain_vector", "brain_feed"),
        ("knowledge_aggregator", "brain_knowledge"),
        ("archive", "brain_knowledge"),
        ("eigenflux", "eigenflux"),
        ("feature_evolution", "eigenflux"),
        ("patrol_eigenflux", "eigenflux"),
        ("hr_center", "hr_skill"),
        ("skill_deriver", "hr_skill"),
        ("auto_hire", "hr_skill"),
        ("proposal", "hr_skill"),
        ("task_hall", "task_hall"),
        ("approval", "task_hall"),
        ("auto_approval", "task_hall"),
        ("shield", "shield"),
        ("firewall", "firewall"),
        ("penetration", "firewall"),
        ("security", "shield"),
        ("threat", "shield"),
        ("video", "gobelin_video"),
        ("music", "gobelin_music"),
        ("writing", "gobelin_writing"),
        ("jimeng", "gobelin_video"),
        ("literary", "gobelin_writing"),
        ("time_sync", "time_sync"),
        ("db_triple_sync", "db_sync"),
        ("nas_storage", "db_sync"),
        ("data_center", "db_sync"),
        ("version_center", "version"),
        ("backup", "version"),
        ("compute_router", "compute_router"),
        ("model_router", "compute_router"),
        ("local_inference", "compute_router"),
        ("neural", "compute_router"),
        ("autopilot", "autopilot_v2"),
        ("sandbox_tick", "autopilot_v2"),
        ("event_bus", "event_bus"),
        ("collab_bus", "event_bus"),
        ("team_collab", "event_bus"),
        ("center_orchestrator", "orchestrator"),
        ("workflow", "orchestrator"),
        ("autodev", "autodev"),
        ("auto_dev_team", "autodev"),
        ("auto_doc", "autodev"),
        ("self_heal", "self_heal"),
        ("cross_self_heal", "self_heal"),
        ("auto_repair", "self_heal"),
        ("disaster", "self_heal"),
        ("warden", "warden"),
        ("data_monitor", "warden"),
        ("fm_listener", "warden"),
        ("screen_monitor", "warden"),
        ("daemon", "warden"),
        ("goal_engine", "goal_engine"),
        ("org_growth", "goal_engine"),
        ("huntianling", "goal_engine"),
    ]

    for keyword, center in keyword_map:
        if keyword in name_lower:
            return center

    # 默认归类
    if engine_name.startswith("ai_"):
        return "andromeda_core"
    if engine_name.startswith("sys_"):
        return "andromeda_core"

    return "andromeda_core"


def _match_center_by_table_name(table_name):
    """根据表名模糊匹配最合适的中心"""
    name_lower = table_name.lower()

    if name_lower.startswith("mt_time"):
        return "time_sync"
    if name_lower.startswith("mt_version"):
        return "version"
    if name_lower.startswith("mt_center"):
        return "andromeda_core"
    if name_lower.startswith("mt_skill"):
        return "hr_skill"
    if name_lower.startswith("mt_fm"):
        return "brain_feed"
    if name_lower.startswith("mt_ai_neural"):
        return "compute_router"

    if "exam" in name_lower:
        return "iceberg_exam"
    if "daily" in name_lower:
        return "iceberg_exam"
    if "user" in name_lower or "chat" in name_lower or "agent" in name_lower:
        return "andromeda_core"
    if "ai_model" in name_lower:
        return "compute_router"
    if "eigenflux" in name_lower or "expert" in name_lower:
        return "eigenflux"
    if "approval" in name_lower:
        return "task_hall"
    if "firewall" in name_lower:
        return "shield"
    if "health" in name_lower or "snapshot" in name_lower:
        return "warden"

    return "andromeda_core"


def _match_center_by_blueprint_name(bp_name):
    """根据蓝图名匹配中心"""
    name_lower = bp_name.lower()

    if "andromeda" in name_lower:
        return "andromeda_core"
    if "gobelin" in name_lower:
        if "video" in name_lower:
            return "gobelin_video"
        if "music" in name_lower:
            return "gobelin_music"
        if "writing" in name_lower:
            return "gobelin_writing"
        if "shield" in name_lower:
            return "shield"
        if "audit" in name_lower:
            return "gobelin_audit"
        if "bank" in name_lower:
            return "gobelin_core"
        return "gobelin_core"
    if "finance" in name_lower:
        if "audit" in name_lower:
            return "gobelin_audit"
        return "gobelin_core"
    if "iceberg" in name_lower:
        return "iceberg_content"
    if "exam" in name_lower:
        return "iceberg_exam"
    if "medical" in name_lower:
        return "iceberg_exam"
    if "english" in name_lower or "cnkr" in name_lower or "math" in name_lower or "language" in name_lower:
        return "iceberg_lang"
    if "collab" in name_lower or "team" in name_lower:
        return "event_bus"
    if "task" in name_lower or "approval" in name_lower or "rule" in name_lower or "vault" in name_lower:
        return "task_hall"
    if "shield" in name_lower or "threat" in name_lower or "whitehat" in name_lower:
        return "shield"
    if "stock" in name_lower or "sandbox" in name_lower:
        return "gobelin_trading"
    if "backup" in name_lower:
        return "version"
    if "disaster" in name_lower:
        return "self_heal"
    if "health" in name_lower:
        return "warden"

    return "andromeda_core"


# ─────────────────────────────────────────────────────────────────────────────
# 公开 API
# ─────────────────────────────────────────────────────────────────────────────

def auto_discover_centers(verbose=True) -> dict:
    """
    扫描 engines/ + blueprints/ + DB tables, 自动验证 + 补充 CENTER_REGISTRY.
    返回 {center_name: stats_dict}.

    同时将未注册的文件自动归入最合适的中心.
    """
    real_engines = set(_list_engines())
    real_blueprints = set(_list_blueprints())
    real_tables = set(_list_db_tables())

    # ── Phase 1: 验证已注册条目 ──
    if verbose:
        print("🔍 [CenterRegistry] 自动发现 + 验证")
        print(f"   engines/   : {len(real_engines)} 个有效文件")
        print(f"   blueprints/: {len(real_blueprints)} 个有效文件")
        print(f"   database   : {len(real_tables)} 张表")
        print()

    all_registered_engines = set()
    all_registered_blueprints = set()
    all_registered_tables = set()

    stats = {}

    for cname, cfg in CENTER_REGISTRY.items():
        engs = cfg.get("engines", [])
        bps = cfg.get("blueprints", [])
        tbls = cfg.get("tables", [])

        # 检查 engines 存在性
        valid_engs = []
        missing_engs = []
        for e in engs:
            if e in real_engines:
                valid_engs.append(e)
                all_registered_engines.add(e)
            else:
                missing_engs.append(e)

        # 去重
        valid_engs = list(dict.fromkeys(valid_engs))
        missing_engs = list(dict.fromkeys(missing_engs))

        # blueprints
        valid_bps = []
        missing_bps = []
        for b in bps:
            if b in real_blueprints:
                valid_bps.append(b)
                all_registered_blueprints.add(b)
            else:
                missing_bps.append(b)
        valid_bps = list(dict.fromkeys(valid_bps))
        missing_bps = list(dict.fromkeys(missing_bps))

        # tables
        valid_tbls = []
        missing_tbls = []
        for t in tbls:
            if t in real_tables:
                valid_tbls.append(t)
                all_registered_tables.add(t)
            else:
                missing_tbls.append(t)
        valid_tbls = list(dict.fromkeys(valid_tbls))
        missing_tbls = list(dict.fromkeys(missing_tbls))

        # 更新 cfg (只保留真实存在的)
        cfg["engines"] = valid_engs
        cfg["blueprints"] = valid_bps
        cfg["tables"] = valid_tbls

        stats[cname] = {
            "name": cfg.get("name", cname),
            "engines": len(valid_engs),
            "blueprints": len(valid_bps),
            "tables": len(valid_tbls),
            "missing_engines": len(missing_engs),
            "missing_blueprints": len(missing_bps),
            "missing_tables": len(missing_tbls),
            "missing_engine_list": missing_engs,
        }

        if verbose and (missing_engs or missing_bps):
            print(f"   ⚠️  {cname}: missing_eng={len(missing_engs)}  missing_bp={len(missing_bps)}")
            for me in missing_engs[:3]:
                print(f"      ! {me}")

    # ── Phase 2: 找未注册的 engines/blueprints/tables, 自动归入 ──
    unregistered_engines = real_engines - all_registered_engines
    unregistered_blueprints = real_blueprints - all_registered_blueprints
    unregistered_tables = real_tables - all_registered_tables

    if verbose and unregistered_engines:
        print(f"\n📎 未注册 engines: {len(unregistered_engines)} — 自动归入最近中心")

    for ue in sorted(unregistered_engines):
        target_center = _match_center_by_engine_name(ue)
        CENTER_REGISTRY.setdefault(target_center, {"engines": [], "blueprints": [], "tables": []})
        if ue not in CENTER_REGISTRY[target_center]["engines"]:
            CENTER_REGISTRY[target_center]["engines"].append(ue)
            all_registered_engines.add(ue)
            stats[target_center]["engines"] += 1
            if verbose:
                print(f"   → {ue}  →  {target_center}")

    if verbose and unregistered_blueprints:
        print(f"\n📎 未注册 blueprints: {len(unregistered_blueprints)} — 自动归入")

    for ub in sorted(unregistered_blueprints):
        target_center = _match_center_by_blueprint_name(ub)
        CENTER_REGISTRY.setdefault(target_center, {"engines": [], "blueprints": [], "tables": []})
        if ub not in CENTER_REGISTRY[target_center]["blueprints"]:
            CENTER_REGISTRY[target_center]["blueprints"].append(ub)
            all_registered_blueprints.add(ub)
            stats[target_center]["blueprints"] += 1
            if verbose:
                print(f"   → {ub}  →  {target_center}")

    if verbose and unregistered_tables:
        print(f"\n📎 未注册 tables: {len(unregistered_tables)} — 自动归入")

    for ut in sorted(unregistered_tables):
        target_center = _match_center_by_table_name(ut)
        CENTER_REGISTRY.setdefault(target_center, {"engines": [], "blueprints": [], "tables": []})
        if ut not in CENTER_REGISTRY[target_center]["tables"]:
            CENTER_REGISTRY[target_center]["tables"].append(ut)
            all_registered_tables.add(ut)
            stats[target_center]["tables"] += 1

    # ── Phase 3: 打印汇总 ──
    if verbose:
        print("\n" + "═" * 70)
        print(f"  🏛️  MTSCOS Center Registry Summary  ({len(CENTER_REGISTRY)} 中心)")
        print("═" * 70)
        total_e = total_b = total_t = 0
        for cname, cfg in CENTER_REGISTRY.items():
            engs = len(cfg.get("engines", []))
            bps = len(cfg.get("blueprints", []))
            tbls = len(cfg.get("tables", []))
            total_e += engs
            total_b += bps
            total_t += tbls
            color = cfg.get("color", "#AAAAAA")
            print(f"  {color} ● {cfg.get('name', cname):12s} ({cname:20s}): eng={engs:3d} bp={bps:2d} tbl={tbls:3d}")
        print("─" * 70)
        print(f"  {'TOTAL':12s} ({'ALL':20s}): eng={total_e:3d} bp={total_b:2d} tbl={total_t:3d}")
        print(f"  真实 engines: {len(real_engines)}   blueprints: {len(real_blueprints)}   tables: {len(real_tables)}")
        print("═" * 70)

    return stats


def get_center_for_engine(engine_name: str) -> str:
    """查询一个引擎属于哪个中心 (O(1))"""
    for cname, cfg in CENTER_REGISTRY.items():
        if engine_name in cfg.get("engines", []):
            return cname
    return _match_center_by_engine_name(engine_name)


def get_center_for_blueprint(bp_name: str) -> str:
    for cname, cfg in CENTER_REGISTRY.items():
        if bp_name in cfg.get("blueprints", []):
            return cname
    return _match_center_by_blueprint_name(bp_name)


def get_center_for_table(table_name: str) -> str:
    for cname, cfg in CENTER_REGISTRY.items():
        if table_name in cfg.get("tables", []):
            return cname
    return _match_center_by_table_name(table_name)


def list_center_engines(center_name: str) -> list:
    """列出一个中心的所有引擎"""
    return CENTER_REGISTRY.get(center_name, {}).get("engines", [])


def list_all_centers() -> list:
    """列出所有中心名"""
    return sorted(CENTER_REGISTRY.keys())


# ═══════════════════════════════════════════════════════════════════════════
# __main__
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    auto_discover_centers(verbose=True)
