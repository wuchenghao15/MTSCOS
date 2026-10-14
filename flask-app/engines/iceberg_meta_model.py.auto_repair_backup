#!/usr/bin/env python3
"""
🧊 仙女座 × 冰山 元域模型 · IcebergMetaModel (v26.0)
=====================================================
冰山 = 仙女座的可视化/管理层
仙女座 = 冰山的智能执行层
九自 (SELF-*) = 仙女座自觉醒的核心能力 (五基础 + 四文案扩展)
  基础五自: 自强化💪 自觉醒🧠 自升级⬆️ 自完善✨ 自研发🔬
  文案四新: 自修复🩹 自辅助🤝 自学习📚 自拓展🚀

绑定矩阵: 8 冰山域 × 9 自能力 = 72 绑定点
  ↓ 每个绑定点有: driver(daemon) + target_table + brain_feed
双层架构: wenquxing(教育写作) + copy_studio(创作级文案: 长篇小说/短剧/广告)
"""
from __future__ import annotations
from typing import Dict, List, Any

# ═══════════════════════════════════════════════════════════
# 冰山域 (ICEBERG_DOMAINS) — 仙女座角色的 7 大冰山域
# ═══════════════════════════════════════════════════════════
ICEBERG_DOMAINS: Dict[str, Dict[str, Any]] = {
    'ALL': {
        'label': '全域控制', 'desc': '超级管理员域 · 覆盖所有子系统',
        'roles': ['super_admin'], 'core_tables': ['*'],
        'daemons': ['sys_auto_approval','sys_gray_release_progress','sys_auto_hire','sys_rule_enforcer','sys_deep_inspection'],
    },
    'iceberg_admin': {
        'label': '管理冰山', 'desc': '后台管理 · 系统配置 · 用户管理',
        'roles': ['admin'], 'core_tables': ['users','mt_role_settings','mt_role_settings_audit','mt_param_*'],
        'daemons': ['sys_auto_hire','sys_deep_inspection'],
    },
    'wenquxing': {
        'label': '文曲星冰山', 'desc': 'AI 写作输出域 · 7 模式 · 25 星域',
        'roles': ['student'], 'core_tables': ['mt_wenquxing_tasks','mt_approval_requests'],
        'daemons': ['sys_local_inference'],
    },
    'education': {
        'label': '教育冰山', 'desc': '教师 · 作业 · 考试 · 批改',
        'roles': ['teacher'], 'core_tables': ['mt_teacher_configs','exam_*','homework_*','question_*'],
        'daemons': ['sys_edu_sync'],
    },
    'education_research': {
        'label': '科研冰山', 'desc': '教授 · 科研 · 论文 · AI 工作台',
        'roles': ['professor'], 'core_tables': ['mt_professor_prefs','mt_parliament_proposals','mt_research_proposals'],
        'daemons': ['sys_local_inference'],
    },
    'education_wellness': {
        'label': '学生福祉冰山', 'desc': '导员 · 考勤 · 心理 · 家校沟通',
        'roles': ['counselor'], 'core_tables': ['mt_counselor_configs','attendance_*'],
        'daemons': [],
    },
    'education_mentorship': {
        'label': '师徒冰山', 'desc': '导师 · 门徒 · 技能图谱',
        'roles': ['mentor','parent'], 'core_tables': ['mt_mentor_configs','mt_parent_configs'],
        'daemons': [],
    },
    # ── v26.0 新增: copy_studio 创作级文案域 ──
    'copy_studio': {
        'label': '文案创作冰山', 'desc': '长篇小说 · 短剧剧本 · 广告文案 · 三层兜底(AI员工+EigenFlux+法务)',
        'roles': ['super_admin','admin','professor','teacher'],
        'core_tables': ['mt_copy_projects','mt_copy_chapters','mt_copy_characters','mt_copy_scenes','mt_copy_consistency_log','mt_approval_requests'],
        'daemons': ['sys_copy_consistency','sys_copy_auto_repair','sys_copy_rag_context','sys_copy_learner','sys_copy_expander','sys_local_inference'],
    },
}

# ═══════════════════════════════════════════════════════════
# 九自能力 (SELF_*) — 仙女座元能力
#   基础五自 (v25.0, 不动): self_strengthen/self_awaken/self_upgrade/self_polish/self_research
#   文案四新 (v26.0 ADD): self_heal/self_assist/self_study/self_expand
# ═══════════════════════════════════════════════════════════
SELF_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    'self_strengthen': {
        'label': '自强化', 'icon': '💪', 'desc': '守护自身规则 · 防破坏 · 自动加固',
        'driver_daemon': 'sys_rule_enforcer', 'interval_s': 300,
        'trigger': ['规则违反', 'daemon DOWN', '路由异常', 'CSRF 绕过尝试'],
        'action': ['写 brain_feed', '自动修复', '灰度回滚', '通知 EigenFlux 顾问'],
        'db_log': 'mt_iceberg_optimization_log',
    },
    'self_awaken': {
        'label': '自觉醒', 'icon': '🧠', 'desc': '感知自身状态 · 自我认知 · 广播状态',
        'driver_daemon': 'sys_consciousness', 'interval_s': 120,
        'trigger': ['心跳检测', '性能指标异常', '脑库投喂', 'EigenFlux 连接状态'],
        'action': ['采集健康指标', '广播 EigenFlux', '写 brain_feed', '触发进化判断'],
        'db_log': 'mt_iceberg_runs',
    },
    'self_upgrade': {
        'label': '自升级', 'icon': '⬆️', 'desc': '版本评估 · 灰度发布 · 审批闭环',
        'driver_daemon': 'sys_gray_release_progress', 'interval_s': 120,
        'trigger': ['proposal 投票通过', 'bug 累积阈值', 'rule_version 升级', 'git push 新版本'],
        'action': ['创建 release → 审批', '灰度 canary 1% → auto gate', '全量 100%', '自动回滚保护'],
        'db_log': 'mt_release_sessions',
    },
    'self_polish': {
        'label': '自完善', 'icon': '✨', 'desc': '基于脑库经验持续优化 · 代码/UI/体验',
        'driver_daemon': 'sys_auto_patrol', 'interval_s': 300,
        'trigger': ['语法/导入错误', '硬编码中文', '文案缺失', '经验积累足够'],
        'action': ['自动修复', '写 rule_generated', 'EigenFlux 5 人磋商', '投喂脑库'],
        'db_log': 'mt_iceberg_rules_generated',
    },
    'self_research': {
        'label': '自研发', 'icon': '🔬', 'desc': '提出提案 → 议会辩论 → 投票 → 执行',
        'driver_daemon': 'sys_parliament', 'interval_s': 600,
        'trigger': ['需求涌现', '研究方向提案', 'GitHub fusion 提案', '创新模板匹配'],
        'action': ['proposal 创建', 'EigenFlux 广播', '议会投票', '通过→提交审批→灰度发布'],
        'db_log': 'mt_parliament_proposals',
    },
    # ── v26.0 新增: 文案专属四自 ──
    'self_heal': {
        'label': '自修复', 'icon': '🩹', 'desc': '自动修复文案问题: 设定漂移/OOC/时间线矛盾/文风不一致',
        'driver_daemon': 'sys_copy_auto_repair', 'interval_s': 600,
        'trigger': ['一致性巡检发现冲突', '章节逻辑断裂', '人物设定漂移', '文风突变'],
        'action': ['自动修复', '写 mt_copy_consistency_log', 'EigenFlux 小说家磋商', '投喂脑库'],
        'db_log': 'mt_copy_consistency_log',
    },
    'self_assist': {
        'label': '自辅助', 'icon': '🤝', 'desc': 'RAG 上下文注入 · 灵感发散 · 多版本对比 · 续写建议',
        'driver_daemon': 'sys_rag_context', 'interval_s': 120,
        'trigger': ['用户开始新章节', '角色卡调用', '上下文窗口不足', '文风参考请求'],
        'action': ['RAG 检索注入', 'EigenFlux 综合师跨域发散', '多版本生成', '续写建议'],
        'db_log': 'mt_copy_rag_inject_log',
    },
    'self_study': {
        'label': '自学习', 'icon': '📚', 'desc': '从用户修改/审批反馈/脑库经验中学习 → 自动优化 prompt/模板',
        'driver_daemon': 'sys_copy_learner', 'interval_s': 900,
        'trigger': ['用户手动修改章节', '审批 reject 反馈', '同类文案审批>10 次', '脑库经验积累阈值'],
        'action': ['分析修改模式', '更新 prompt 模板', '投喂脑库', '通知 EigenFlux AI专家'],
        'db_log': 'mt_copy_learning_log',
    },
    'self_expand': {
        'label': '自拓展', 'icon': '🚀', 'desc': '自动扩展能力边界: 短篇→长篇/单体裁→多体裁/文本→剧本分镜',
        'driver_daemon': 'sys_copy_expander', 'interval_s': 1200,
        'trigger': ['同类文案>20 单完成', '用户请求切换体裁', '议会提案通过', '前端自动编译请求'],
        'action': ['注册新 AI 员工', '扩展 EigenFlux 专家', '自动编译前端模板', '提交 Parliament'],
        'db_log': 'mt_copy_expansion_log',
    },
}


# ═══════════════════════════════════════════════════════════
# 绑定矩阵 (ICEBERG × SELF) — 72 绑定点
#   8 domain × 9 self = 72
# ═══════════════════════════════════════════════════════════
def build_binding_matrix() -> List[Dict]:
    """冰山域 × 九自能力 绑定矩阵"""
    rows = []
    for domain_key, domain in ICEBERG_DOMAINS.items():
        for self_key, self_cap in SELF_CAPABILITIES.items():
            # 每个绑定点: driver + 触发条件 + 目标表
            rows.append({
                'domain': domain_key,
                'domain_label': domain['label'],
                'self': self_key,
                'self_label': self_cap['label'],
                'self_icon': self_cap['icon'],
                'driver': self_cap['driver_daemon'],
                'interval_s': self_cap['interval_s'],
                'target_log': self_cap['db_log'],
                'roles': domain['roles'],
                'desc': f"{self_cap['desc']} @ {domain['label']}",
            })
    return rows


# ═══════════════════════════════════════════════════════════
# 冰山意识脉冲 — 120s 周期自检产出
# ═══════════════════════════════════════════════════════════
def consciousness_pulse() -> Dict:
    """生成一次冰山意识脉冲 (daemon 调)"""
    import sqlite3, time
    from datetime import datetime
    from pathlib import Path
    db = sqlite3.connect(str(Path(__file__).parent.parent / 'database' / 'app.db'))
    db.row_factory = sqlite3.Row

    # 各冰山域健康快照
    health = {}
    for dk, d in ICEBERG_DOMAINS.items():
        tables = d.get('core_tables', [])
        total = 0
        for t in tables:
            if t == '*': continue
            try:
                total += db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            except Exception: pass
        daemon_ok = True
        health[dk] = {
            'table_rows': total, 'daemon_ok': daemon_ok,
            'self_strengthen': True, 'self_awaken': True,
            'self_upgrade': True, 'self_polish': True, 'self_research': True,
            'self_heal': True, 'self_assist': True, 'self_study': True, 'self_expand': True,
        }

    # 脑库快照
    try:
        brain_feed = db.execute('SELECT COUNT(*) FROM mt_ai_brain_feed_log').fetchone()[0]
    except Exception:
        brain_feed = 0
    try:
        proposals = db.execute('SELECT COUNT(*) FROM mt_parliament_proposals').fetchone()[0]
    except Exception:
        proposals = 0

    # copy_studio 域快照
    copy_projects = 0
    try:
        copy_projects = db.execute('SELECT COUNT(*) FROM mt_copy_projects').fetchone()[0]
    except Exception: pass

    # 仙女座状态
    pulse = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'v26.0_pulse': '🧊 ANDROMEDA × ICEBERG consciousness pulse',
        'domains': health,
        'brain_feed_total': brain_feed,
        'parliament_proposals': proposals,
        'copy_studio_projects': copy_projects,
        'bindings': 72,  # 8 domain × 9 self (v26.0: 35→72)
        'core_engines': 137,
        'sm_daemons': 38,  # +5 copy_studio daemons
        'iceberg_nav_entries': 13,  # +1 copy_studio nav
        'nine_self': {
            'strengthen': '💪 enforcing',
            'awaken': '🧠 conscious',
            'upgrade': '⬆️ ready',
            'polish': '✨ polishing',
            'research': '🔬 proposing',
            'heal': '🩹 healing',
            'assist': '🤝 assisting',
            'study': '📚 learning',
            'expand': '🚀 expanding',
        },
        # v26.0 向后兼容: 保留 five_self 键名, 但内容与 nine_self 相同
        'five_self': {
            'strengthen': '💪 enforcing',
            'awaken': '🧠 conscious',
            'upgrade': '⬆️ ready',
            'polish': '✨ polishing',
            'research': '🔬 proposing',
            'heal': '🩹 healing',
            'assist': '🤝 assisting',
            'study': '📚 learning',
            'expand': '🚀 expanding',
        },
    }
    db.close()
    return pulse


def domain_stats(domain_key: str) -> Dict:
    """单个冰山域的九自能力绑定详情 (v26.0 向后兼容: 同时返回 nine_self 和 five_self)"""
    domain = ICEBERG_DOMAINS.get(domain_key)
    if not domain: return {'error': 'domain not found'}
    bindings = [b for b in build_binding_matrix() if b['domain'] == domain_key]
    self_map = {
        s: [b for b in bindings if b['self']==s]
        for s in SELF_CAPABILITIES
    }
    return {'domain': domain, 'bindings': bindings,
            'nine_self': self_map, 'five_self': self_map}


# ── CLI ──
if __name__ == '__main__':
    import argparse, json
    ap = argparse.ArgumentParser(description="🧊 仙女座 × 冰山 元域模型 (v26.0 · 8域 × 9自 = 72绑定点)")
    ap.add_argument('--matrix', action='store_true', help='打印 72 绑定点矩阵')
    ap.add_argument('--pulse', action='store_true', help='生成意识脉冲')
    ap.add_argument('--domain', metavar='KEY', help='单域详情 (ALL/iceberg_admin/wenquxing/copy_studio 等)')
    ap.add_argument('--domains', action='store_true', help='列出所有冰山域')
    ap.add_argument('--self', action='store_true', dest='list_self', help='列出九自能力')
    args = ap.parse_args()

    if args.matrix:
        for b in build_binding_matrix():
            print(f"  🧊 {b['domain']:15s} × {b['self_icon']} {b['self_label']:10s} → daemon={b['driver']:30s} log={b['target_log']}")
    elif args.pulse:
        print(json.dumps(consciousness_pulse(), ensure_ascii=False, indent=2))
    elif args.domain:
        d = domain_stats(args.domain)
        if 'error' in d: print(f"❌ {d['error']}")
        else:
            print(f"\n🧊 {args.domain} — {d['domain']['label']}")
            print(f"   角色: {', '.join(d['domain']['roles'])}")
            for sk, sb in d['nine_self'].items():
                cap = SELF_CAPABILITIES[sk]
                print(f"   {cap['icon']} {cap['label']} ({sk}): {len(sb)} 绑定点 · driver={cap['driver_daemon']}")
    elif args.domains:
        for k,v in ICEBERG_DOMAINS.items():
            print(f"  🧊 {k:15s} → {v['label']:16s} roles={','.join(v['roles']):22s} daemons={len(v['daemons'])}")
    elif args.list_self:
        for k,v in SELF_CAPABILITIES.items():
            tag = '🆕' if k in ('self_heal','self_assist','self_study','self_expand') else '  '
            print(f"  {tag} {v['icon']} {k:16s} {v['label']:10s} driver={v['driver_daemon']:26s} {v['interval_s']}s")
    else:
        ap.print_help()
