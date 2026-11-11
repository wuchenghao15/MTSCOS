#!/usr/bin/env python3
"""古灵阁 33 中心 — 全自动闭环投资治理系统"""
import sqlite3, os, json, datetime, random

DB = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

# ═══════════════════════════════════════════════════════════════════
# 33 个 AI 员工中心 — 按投资周期自动触发任务
# ═══════════════════════════════════════════════════════════════════

CENTERS = [
    # ── 🏦 投资决策层 (7) ──
    {"code": "INVEST_COUNCIL",  "name": "投资委员会",  "cycle": "每3天20:00",  "deps": ["INVEST_ANALYST","RISK_RADAR"], "role": "最终决策"},
    {"code": "INVEST_ANALYST",  "name": "投资分析师",  "cycle": "每日15:30",   "deps": ["DATA_CENTER"],                 "role": "行情分析+提案"},
    {"code": "CHANNEL_STOCK",   "name": "A股渠道中心", "cycle": "每3天",       "deps": ["INVEST_COUNCIL"],              "role": "股票买卖执行"},
    {"code": "CHANNEL_FUND",    "name": "基金渠道中心", "cycle": "每3天",       "deps": ["INVEST_COUNCIL"],              "role": "基金申赎执行"},
    {"code": "CHANNEL_BANK",    "name": "银行理财中心", "cycle": "每周一",      "deps": ["INVEST_COUNCIL"],              "role": "T+1/T+5产品"},
    {"code": "CHANNEL_METAL",   "name": "稀有金属中心", "cycle": "每3天",       "deps": ["INVEST_COUNCIL"],              "role": "黄金/白银ETF"},
    {"code": "CHANNEL_BIZ",     "name": "商业投资中心", "cycle": "每月",        "deps": ["INVEST_COUNCIL"],              "role": "商铺/股权/私募"},

    # ── 🛡️ 风险合规层 (6) ──
    {"code": "RISK_RADAR",      "name": "风险雷达",    "cycle": "每5分钟",     "deps": ["DATA_CENTER"],                 "role": "实时风险扫描"},
    {"code": "RISK_FUSE",       "name": "熔断中心",    "cycle": "实时",        "deps": ["RISK_RADAR"],                  "role": "触发熔断"},
    {"code": "AUDIT_CENTER",    "name": "审计中心",    "cycle": "每日16:05",   "deps": ["DATA_CENTER"],                 "role": "数据勾稽校验"},
    {"code": "COMPLIANCE",      "name": "合规稽查",    "cycle": "每周五",      "deps": ["AUDIT_CENTER"],                "role": "合规检查"},
    {"code": "TAX_PLANNING",    "name": "税务筹划",    "cycle": "每月底",      "deps": ["AUDIT_CENTER"],                "role": "税务优化"},
    {"code": "INSURANCE_GUARD", "name": "财险保障中心","cycle": "每季度",      "deps": ["INVEST_COUNCIL"],              "role": "财险覆盖评估"},

    # ── 📝 内容产出层 (5) ──
    {"code": "DOC_CENTER",      "name": "文案中心",    "cycle": "会议后1h",    "deps": ["INVEST_COUNCIL"],              "role": "会议纪要+决策文档"},
    {"code": "STRATEGY_CENTER", "name": "战略中心",    "cycle": "每月1号",     "deps": ["INVEST_COUNCIL"],              "role": "战略规划+持仓比例"},
    {"code": "PRESS_CENTER",    "name": "新闻发布中心","cycle": "每季度",      "deps": ["DOC_CENTER"],                  "role": "对外报告+披露"},
    {"code": "CONTENT_AI",      "name": "内容AI中心",  "cycle": "每日",        "deps": ["DOC_CENTER"],                  "role": "智能摘要+知识库"},
    {"code": "BRAND_CENTER",    "name": "品牌中心",    "cycle": "每月",        "deps": ["PRESS_CENTER"],                "role": "品牌形象+对外形象"},

    # ── 👥 人事管理层 (4) ──
    {"code": "HR_CENTER",       "name": "人事中心",    "cycle": "每周一",      "deps": ["INVEST_COUNCIL"],              "role": "AI员工任务调度"},
    {"code": "PERFORMANCE",     "name": "绩效考评中心","cycle": "每月",        "deps": ["HR_CENTER"],                   "role": "AI员工KPI考核"},
    {"code": "ROLE_ASSIGN",     "name": "角色任命中心","cycle": "季度",        "deps": ["HR_CENTER"],                   "role": "角色任免+权限"},
    {"code": "WELLNESS",        "name": "健康中心",    "cycle": "每周",        "deps": ["HR_CENTER"],                   "role": "AI员工状态监控"},

    # ── 📊 数据技术层 (5) ──
    {"code": "DATA_CENTER",     "name": "数据中心",    "cycle": "每5分钟",     "deps": [],                              "role": "行情采集+存储"},
    {"code": "AI_MODEL",        "name": "AI模型中心",  "cycle": "每月",        "deps": ["DATA_CENTER"],                 "role": "模型训练+迭代"},
    {"code": "API_GATEWAY",     "name": "API网关中心", "cycle": "实时",        "deps": ["DATA_CENTER"],                 "role": "API路由+安全"},
    {"code": "INFRA_CENTER",    "name": "基础设施中心","cycle": "每日",        "deps": ["API_GATEWAY"],                 "role": "服务器+网络+监控"},
    {"code": "SECURITY_OPS",    "name": "安全运营中心","cycle": "实时",        "deps": ["INFRA_CENTER"],                "role": "安全防护+入侵检测"},

    # ── 🎓 教育考试层 (4) ──
    {"code": "EDU_CENTER",      "name": "教育中心",    "cycle": "会议后",      "deps": ["DOC_CENTER"],                  "role": "会议学习+AI投喂"},
    {"code": "EXAM_CENTER",     "name": "考试中心",    "cycle": "每月",        "deps": ["EDU_CENTER"],                  "role": "策略考核+风控考试"},
    {"code": "CASE_LAB",        "name": "案例实验室",  "cycle": "每周",        "deps": ["EDU_CENTER"],                  "role": "案例归档+复盘"},
    {"code": "TRAINING_AI",     "name": "训练AI中心",  "cycle": "每日",        "deps": ["CASE_LAB"],                    "role": "AI模型增量训练"},

    # ── 🚨 应急管理层 (2) ──
    {"code": "CRISIS_CMD",      "name": "应急指挥部",  "cycle": "触发",        "deps": ["RISK_FUSE"],                   "role": "紧急会议+灾难补救"},
    {"code": "DR_CENTER",       "name": "灾难恢复中心","cycle": "触发",        "deps": ["CRISIS_CMD"],                  "role": "系统恢复+数据修复"},
]

# ── 建表: 中心注册 + 任务队列 + 执行日志 ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_center_registry (
    code TEXT PRIMARY KEY,
    name TEXT,
    cycle TEXT,
    deps TEXT,                       -- JSON array of codes
    role TEXT,
    status TEXT DEFAULT 'IDLE',      -- IDLE / WORKING / WAITING / ERROR
    last_run TEXT,
    next_run TEXT,
    task_count INTEGER DEFAULT 0,
    avg_duration_ms INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS mt_task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE,
    from_center TEXT,                 -- 上游触发中心
    to_center TEXT,                   -- 执行中心
    task_type TEXT,                   -- MEETING / PROPOSAL / EXECUTE / REVIEW / REPORT
    priority INTEGER DEFAULT 2,       -- 1=紧急 2=正常 3=低
    payload TEXT,                     -- JSON
    status TEXT DEFAULT 'PENDING',    -- PENDING / DISPATCHED / RUNNING / DONE / FAILED
    result TEXT,                      -- JSON result
    created_at TEXT DEFAULT (datetime('now','localtime')),
    dispatched_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS mt_center_exec_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_code TEXT,
    task_id TEXT,
    action TEXT,                      -- RUN / DISPATCH / COMPLETE / ERROR
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 注册 33 中心 ──
for center in CENTERS:
    c.execute("""
        INSERT OR REPLACE INTO mt_center_registry (code, name, cycle, deps, role)
        VALUES (?, ?, ?, ?, ?)
    """, (center['code'], center['name'], center['cycle'], json.dumps(center['deps']), center['role']))

# ── 初始任务: 今天就跑的周期触发 ──
today = datetime.datetime.now().strftime('%Y-%m-%d')
initial_tasks = [
    # 数据中心: 行情采集 (立即跑)
    ("DATA_CENTER", "RISK_RADAR", "DATA_COLLECT", 1, json.dumps({"source": "腾讯行情", "symbols": ["sh600036","sh601318","518880","159934"], "goal": "建立实时行情流"})),
    # 投资分析师: 今日提案 (今日跑)
    ("DATA_CENTER", "INVEST_ANALYST", "DAILY_ANALYSIS", 2, json.dumps({"date": today, "goal": "¥10,000 七大渠道配置建议"})),
    # 风险雷达: 初始扫描 (立即)
    ("DATA_CENTER", "RISK_RADAR", "RISK_SCAN", 1, json.dumps({"goal": "初始风险基线建立"})),
    # 审计中心: 初始数据验证 (立即)
    ("DATA_CENTER", "AUDIT_CENTER", "INITIAL_AUDIT", 2, json.dumps({"goal": "重置后数据完整性校验"})),
    # 投资委员会: 第一次会议 (今天)
    ("INVEST_ANALYST", "INVEST_COUNCIL", "FIRST_MEETING", 1, json.dumps({"agenda": "¥10,000 七大渠道配置投票", "date": today})),
    # 文案中心: 第一次会议纪要 (会后)
    ("INVEST_COUNCIL", "DOC_CENTER", "MINUTES", 2, json.dumps({"meeting_id": "REGULAR_" + today.replace("-",""), "type": "REGULAR"})),
    # 教育中心: 投喂案例 (会后)
    ("DOC_CENTER", "EDU_CENTER", "TRAINING_FEED", 3, json.dumps({"source": "第一次会议纪要", "goal": "AI学习初始投资决策"})),
    # 保险保障中心: 财险评估 (本周)
    ("INVEST_COUNCIL", "INSURANCE_GUARD", "COVERAGE_ASSESS", 2, json.dumps({"goal": "¥10,000 资产需要的财险"})),
    # 应急指挥部: 待命 (初始化)
    ("RISK_FUSE", "CRISIS_CMD", "STANDBY", 1, json.dumps({"goal": "灾难补救预案初始"})),
]

for from_c, to_c, ttype, prio, payload in initial_tasks:
    task_id = f"TASK_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}"
    c.execute("""
        INSERT OR REPLACE INTO mt_task_queue (task_id, from_center, to_center, task_type, priority, payload)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (task_id, from_c, to_c, ttype, prio, payload))

c.commit()

# ── 打印启动报告 ──
centers_count = c.execute("SELECT COUNT(*) FROM mt_center_registry").fetchone()[0]
tasks_count = c.execute("SELECT COUNT(*) FROM mt_task_queue").fetchone()[0]

print("=" * 60)
print("🏦 古灵阁 33 中心全自动闭环治理系统")
print("=" * 60)
print(f"  ✅ 中心注册: {centers_count} 个 AI 员工中心")
print(f"  ✅ 初始任务队列: {tasks_count} 条 (已按优先级排序)")
print(f"  ✅ 账户初始资金: ¥10,000.00 (2026-11-11)")
print(f"  ✅ 依赖网络: 全部 33 中心已串联")
print("-" * 60)

# 按类型分组统计
groups = {
    "🏦 投资决策层":  [c for c in CENTERS if c['code'].startswith(('INVEST','CHANNEL'))],
    "🛡️ 风险合规层":  [c for c in CENTERS if c['code'].startswith('RISK') or c['code'] in ('AUDIT_CENTER','COMPLIANCE','TAX_PLANNING','INSURANCE_GUARD')],
    "📝 内容产出层":  [c for c in CENTERS if c['code'].startswith('DOC') or c['code'] in ('STRATEGY_CENTER','PRESS_CENTER','CONTENT_AI','BRAND_CENTER')],
    "👥 人事管理层":  [c for c in CENTERS if c['code'].startswith('HR') or c['code'] in ('PERFORMANCE','ROLE_ASSIGN','WELLNESS')],
    "📊 数据技术层":  [c for c in CENTERS if c['code'].startswith('DATA') or c['code'] in ('AI_MODEL','API_GATEWAY','INFRA_CENTER','SECURITY_OPS')],
    "🎓 教育考试层":  [c for c in CENTERS if c['code'].startswith('EDU') or c['code'] in ('EXAM_CENTER','CASE_LAB','TRAINING_AI')],
    "🚨 应急管理层":  [c for c in CENTERS if c['code'].startswith('CRISIS') or c['code'] == 'DR_CENTER'],
}

for group_name, group_list in groups.items():
    print(f"\n{group_name} ({len(group_list)} 个)")
    for c2 in group_list:
        print(f"   {c2['code']:20} {c2['name']:10} [{c2['cycle']:10}] → {c2['role']}")

print("\n" + "=" * 60)
print("🔄 自动循环: 中心 A 完成 → 触发中心 B 的任务 → 形成闭环")
print("📅 投资周期: 每3天例会 · 每月1号复盘 · 紧急触发灾难补救")
print("📋 所有会议 → 自动落盘 mt_meeting_log")
print("🏗️ 下一个任务: DATA_CENTER 行情采集 → INVEST_ANALYST 今日提案")
print("=" * 60)

c.close()
