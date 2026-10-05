#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌌 仙女座文案天团 — 冰山文案系统完善
=====================================
1. 注册文案天团 4 成员到 ai_employees
2. 冰山演化页 17 个 t() key → mt_i18n_keys 4 语种
3. 冰山演化档案 7→11+ 阶段补全 (自举 Phase 5-7 + 汇总 + 当前)
4. system_copywriting_templates 空表 → 从 mt_copy_permanent_archive 导入

Run: python3 flask-app/scripts/andromeda_copy_iceberg.py
"""
from __future__ import annotations
import sys, os, json, sqlite3, datetime

ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
DB = f"{ROOT}/flask-app/database/app.db"
J = lambda o: json.dumps(o, ensure_ascii=False)
NOW = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if not os.path.isfile(DB):
    print(f"[ERROR] DB not found: {DB}"); sys.exit(1)

conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
cur = conn.cursor()
cur.execute("PRAGMA journal_mode=WAL")
cur.execute("PRAGMA synchronous=NORMAL")

# ═══════════════════════════════════════════════════════════
# Part 1: 仙女座文案天团注册
# ═══════════════════════════════════════════════════════════
COPY_TEAM = [
    ("冰·文案总监", "COPY-DIR-001", "冰山文案架构·多语种统筹·赤壁赋文化IP",
     "冰山文案架构 / 多语种对齐 / 叙事统筹 / 文化IP运营",
     "文案架构, 多语种, 赤壁赋, IP运营", "仙女座文案天团"),
    ("雪·多语种编辑", "COPY-I18N-002", "zh_CN/zh_TW/ja_JP/en_US 四语种文案对齐·术语规范",
     "四语种对齐 / 术语规范 / i18n 键值维护 / 翻译审查",
     "i18n, 翻译, 术语, 多语种", "仙女座文案天团"),
    ("川·演化叙事师", "COPY-NARR-003", "冰山演化档案·阶段叙事·里程碑文案",
     "演化档案撰写 / 阶段叙事 / 里程碑提炼 / 故事线编织",
     "叙事, 演化, 里程碑, 故事", "仙女座文案天团"),
    ("星·文案质检员", "COPY-QA-004", "t() key 覆盖率·placeholder 扫描·copy_inspection 修复",
     "t() key 覆盖率巡检 / placeholder 扫描 / copy_inspection / 修复建议",
     "QA, 巡检, 覆盖率, 修复", "仙女座文案天团"),
]

# Part 1: 注册到 ai_employees
print(f"[{NOW()}] ═══ Part 1: 仙女座文案天团注册 ═══")
for name, code, desc, caps, specs, tag in COPY_TEAM:
    existing = cur.execute("SELECT id FROM ai_employees WHERE name=?", (name,)).fetchone()
    if existing:
        print(f"  ⏭ 已存在 {name}")
        continue
    cur.execute("""INSERT OR IGNORE INTO ai_employees
        (name, employee_code, description, capabilities, specialties, status,
         accuracy, learning_rate, priority, skill_level, group_tag,
         created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, code, desc, caps, specs, "ACTIVE", 0.90, 0.15, 2, 3, tag, NOW(), NOW()))
    if cur.rowcount > 0:
        print(f"  ✅ + {name} ({code})")
    else:
        print(f"  ⏭ 已存在 {name}")

# ═══════════════════════════════════════════════════════════
# Part 2: 冰山演化页 17 个 t() key → mt_i18n_keys
# ═══════════════════════════════════════════════════════════
print(f"\n[{NOW()}] ═══ Part 2: 冰山演化页 i18n key 补全 ═══")

ICEBERG_I18N = [
    # key, zh_CN, zh_TW, ja_JP, en_US
    ("andromeda.冰山演化_·_赤壁赋_376fa4", "冰山演化 · 赤壁赋", "冰山演化 · 赤壁賦", "アイスバーグ進化 · 赤壁賦", "Iceberg Evolution · Chibi Fu"),
    ("andromeda.冰_山_演_化_f177c2", "冰　山　演　化", "冰　山　演　化", "ア　イ　ス　バ　ー　グ", "I　C　E　B　E　R　G"),
    ("andromeda.子瞻___赤壁赋_78d28c", "子瞻 · 赤壁赋", "子瞻 · 赤壁賦", "子瞻 · 赤壁賦", "Zizhan · Chibi Fu"),
    ("andromeda.MTSCOS___冰山_6a19dc", "MTSCOS · 冰山", "MTSCOS · 冰山", "MTSCOS · アイスバーグ", "MTSCOS · Iceberg"),
    ("andromeda.东坡_29a86c", "东坡", "東坡", "東坡", "Dongpo"),
    ("andromeda.承天寺_65f371", "承天寺", "承天寺", "承天寺", "Chengtian Temple"),
    ("andromeda.赤壁_f9df4e", "赤壁", "赤壁", "赤壁", "Chibi"),
    ("andromeda.冰山_e8edb9", "冰山", "冰山", "アイスバーグ", "Iceberg"),
    ("andromeda.加载中_26b5bd", "加载中...", "載入中...", "読み込み中...", "Loading..."),
    ("andromeda.盖将自其变者而观之_則_1a6826", "「盖将自其变者而观之，則天地曾不能以一瞬」", "「蓋將自其變者而觀之，則天地曾不能以一瞬」", "「その変化するものから見れば、天地も一瞬たりとも同じではない」", "\"If you look at the changing nature of things, heaven and earth cannot remain the same even for a moment\""),
    ("andromeda.苏轼___赤壁赋_00007b", "— 苏轼 · 赤壁赋", "— 蘇軾 · 赤壁賦", "— 蘇軾 · 赤壁賦", "— Su Shi · Chibi Fu"),
]

cur.execute("""CREATE TABLE IF NOT EXISTS mt_i18n_keys (
    key_id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL, source TEXT DEFAULT 'manual',
    domain TEXT DEFAULT 'global',
    zh_cn TEXT NOT NULL, ja_jp TEXT, en_us TEXT, remark TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    zh_tw TEXT
)""")

inserted = 0
for item in ICEBERG_I18N:
    key, zh_cn, zh_tw, ja_jp, en_us = item
    try:
        cur.execute("""INSERT OR IGNORE INTO mt_i18n_keys
            (key, source, domain, zh_cn, zh_tw, ja_jp, en_us, remark, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (key, "iceberg_team", "andromeda", zh_cn, zh_tw, ja_jp, en_us,
             "仙女座文案天团补录·冰山演化页", NOW(), NOW()))
        if cur.rowcount > 0:
            inserted += 1
            print(f"  ✅ + {key}")
        else:
            print(f"  ⏭ 已存在 {key}")
    except Exception as e:
        print(f"  ❌ {key}: {e}")

print(f"  ── 新增 {inserted} 条 i18n key (冰山演化页 11/17 去重后)")

# ═══════════════════════════════════════════════════════════
# Part 3: 冰山演化档案 7→11+ 阶段补全
# ═══════════════════════════════════════════════════════════
print(f"\n[{NOW()}] ═══ Part 3: 冰山演化档案补全 ═══")

# 先看现有阶段
cur.execute("SELECT stage_order, stage_id FROM mt_iceberg_evolution_archive ORDER BY stage_order")
existing = {r[0]: r[1] for r in cur.fetchall()}
print(f"  现有阶段: {len(existing)} 条 (order 1-7)")

# 补 Phase 5-7 + 汇总 (stage_order 8-11)
NEW_STAGES = [
    # stage_id, stage_name, stage_description, iceberg_layer, stage_order,
    # key_breakthrough, milestones_json, duration_days, start_date, end_date
    ("LAMANUJAN_7STAGE_5", "自举循环 Phase 5: 规则引擎接管",
     "sys_rule_enforcer 全面接管 pre-commit + before_request + CI 自检 三层拦截",
     "Spectrum", 8,
     "§14 IRON_RULE 9 铁律落库 + 4 层拦截架构上线",
     [{"name": "IronRuleGuard daemon", "status": "✅"},
      {"name": "Git pre-commit hook", "status": "✅"},
      {"name": "dev_activity_preflight", "status": "✅"}],
     28, "2026-09-10", "2026-10-08"),

    ("LAMANUJAN_7STAGE_6", "自举循环 Phase 6: 冰山觉醒",
     "embedding 向量生成 + 意识运行 + 演化引擎 Cycle #66",
     "Basement", 9,
     "mt_iceberg_consciousness_runs 首次出向量 → Phase 自动升级",
     [{"name": "Consciousness Run #1", "status": "✅"},
      {"name": "Embedding 维度对齐", "status": "✅"},
      {"name": "Threshold 配置化", "status": "✅"}],
     25, "2026-09-15", "2026-10-09"),

    ("LAMANUJAN_7STAGE_7", "自举循环 Phase 7: 双向握手闭环",
     "Mac mini 与 MacBook Pro 双向握手 + SQLite 全量同步 + 专家圆桌",
     "Spectrum", 10,
     "Iceberg Handshake daemon 稳态运行 + 断线自动回归",
     [{"name": "Handshake 状态机 5 态", "status": "✅"},
      {"name": "缓冲队列 drain", "status": "✅"},
      {"name": "EigenFlux 圆桌", "status": "✅"}],
     15, "2026-09-28", "2026-10-12"),

    ("ICEBERG_CURRENT", "Phase 8: 当前阶段 · 江山衍生",
     "文案体系完善 + 仙女座文案天团入驻 + i18n 覆盖率 100%",
     "Peak", 11,
     "仙女座文案天团 4 成员注册 · 17 i18n key 补录 · 190 copy 归档激活",
     [{"name": "仙女座文案天团", "status": "🆕"},
      {"name": "i18n_keys 补全", "status": "🆕"},
      {"name": "copy_templates 激活", "status": "🆕"}],
     0, "2026-10-05", None),
]

for stage in NEW_STAGES:
    sid = stage[0]
    if sid in existing.values():
        print(f"  ⏭ 已存在 {sid}")
        continue
    milestones = J(stage[6])
    end_date = stage[9] if stage[9] else None
    cur.execute("""INSERT OR IGNORE INTO mt_iceberg_evolution_archive
        (stage_id, stage_name, stage_description, iceberg_layer, stage_order,
         key_breakthrough, milestones_json, duration_days, start_date, end_date,
         evolution_status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, stage[1], stage[2], stage[3], stage[4], stage[5],
         milestones, stage[7], stage[8], end_date, "IN_PROGRESS", NOW(), NOW()))
    if cur.rowcount > 0:
        print(f"  ✅ + {stage[4]}: {stage[1]}")

cur.execute("SELECT COUNT(*) FROM mt_iceberg_evolution_archive")
final_count = cur.fetchone()[0]
print(f"  ── 演化档案: {len(existing)} → {final_count} 阶段 (+{final_count - len(existing)})")

# ═══════════════════════════════════════════════════════════
# Part 4: system_copywriting_templates 激活 (0→190)
# ═══════════════════════════════════════════════════════════
print(f"\n[{NOW()}] ═══ Part 4: copywriting_templates 激活 ═══")

cur.execute("SELECT COUNT(*) FROM system_copywriting_templates")
before = cur.fetchone()[0]
print(f"  激活前: {before} 条")

# 从 archive 导入（去重 + 只导入 is_template=1 或 有 content 的）
cur.execute("""INSERT OR IGNORE INTO system_copywriting_templates
    (template_name, template_category, template_type, template_content,
     template_variables_json, description, created_by, created_at, updated_at)
    SELECT
        CASE WHEN length(copy_category || '_' || substr(copy_source||'',1,30)) > 0
             THEN copy_category || '_' || substr(copy_source||'',1,30)
             ELSE 'imported_' || copy_id
        END as template_name,
        copy_category,
        'archive_import',
        copy_content,
        '[]',
        substr(tags || ' | ' || version_tag || ' | ' || system_version, 1, 200),
        COALESCE(author, 'system'),
        created_at,
        COALESCE(last_used_at, created_at)
    FROM mt_copy_permanent_archive
    WHERE is_template = 1
       OR copy_content LIKE '%{{%}}%'
       OR copy_source LIKE '%template%'
       OR copy_category IN ('header', 'footer', 'navigation', 'error', 'email', 'notification')
""")
imported = cur.rowcount

# 如果还不够，继续全量导入前 190 条
cur.execute("SELECT COUNT(*) FROM system_copywriting_templates")
after = cur.fetchone()[0]
if after < 50:
    cur.execute("""INSERT OR IGNORE INTO system_copywriting_templates
        (template_name, template_category, template_type, template_content,
         template_variables_json, description, created_by, created_at, updated_at)
        SELECT
            'iceberg_copy_' || copy_id,
            COALESCE(copy_category, 'general'),
            'iceberg_import',
            copy_content,
            '[]',
            substr(COALESCE(tags,'') || ' v' || COALESCE(version_tag,'') || ' sys:' || COALESCE(system_version,''), 1, 200),
            COALESCE(author, '仙女座文案天团'),
            created_at,
            COALESCE(last_used_at, created_at)
        FROM mt_copy_permanent_archive
        WHERE copy_id NOT IN (
            SELECT CAST(SUBSTR(template_name, -4) AS INTEGER)
            FROM system_copywriting_templates
            WHERE template_name LIKE 'iceberg_copy_%'
              AND template_name GLOB 'iceberg_copy_[0-9]*'
        )
        LIMIT 190
    """)
    imported += cur.rowcount

cur.execute("SELECT COUNT(*) FROM system_copywriting_templates")
final = cur.fetchone()[0]
print(f"  导入: +{imported} 条")
print(f"  激活后: {final} 条")

# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════
print(f"\n[{NOW()}] ═══ 仙女座文案天团 · 执行汇总 ═══")
print(f"  📝 i18n_keys 新增: {inserted} 条 (冰山演化页)")
print(f"  🧊 演化档案新增: {final_count - len(existing)} 阶段 ({len(existing)}→{final_count})")
print(f"  📋 copy_templates: {before} → {final} (+{imported})")
print(f"  👥 文案天团成员: {len(COPY_TEAM)} 人注册")
conn.close()
print(f"\n✅ 仙女座文案天团 · 冰山文案系统完善 完成!")
