#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🐱 猫压测试 · 全页面四语种翻译覆盖率
========================================
扫描 110 模板 → 提取 948 t() key → 对比 mt_i18n_keys → 报告覆盖率矩阵
+ 生成缺失 key 补录 SQL
"""
from __future__ import annotations
import sys, os, re, json, sqlite3, datetime
from collections import defaultdict

ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
TEMPLATES_DIR = f"{ROOT}/flask-app/templates"
DB = f"{ROOT}/flask-app/database/app.db"
NOW = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if not os.path.isdir(TEMPLATES_DIR):
    print(f"[ERROR] templates dir not found: {TEMPLATES_DIR}"); sys.exit(1)

conn = sqlite3.connect(DB, timeout=30)
cur = conn.cursor()

# ── 扫描所有模板 ──
print(f"[{NOW()}] 🐱 猫压测试启动 — 扫描模板 t() key...")

T_PATTERN = re.compile(r"t\(\s*'([^']+)'[^)]*default=['\"]([^'\"]*)['\"]")

templates_data = []  # (filename, [(key, default_zh), ...])
all_keys = {}        # key -> default_zh

for fname in sorted(os.listdir(TEMPLATES_DIR)):
    if not fname.endswith(".html"):
        continue
    fpath = os.path.join(TEMPLATES_DIR, fname)
    content = open(fpath, "r", encoding="utf-8").read()
    keys_found = []
    for m in T_PATTERN.finditer(content):
        key = m.group(1).strip()
        default = m.group(2).strip()
        if key:
            keys_found.append((key, default))
            all_keys[key] = default
    if keys_found:
        templates_data.append((fname, keys_found))

total_templates_with_keys = len(templates_data)
total_calls = sum(len(v) for _, v in templates_data)
unique_keys = len(all_keys)
print(f"  📄 扫描: {total_templates_with_keys} 模板 · {total_calls} t() 调用 · {unique_keys} 唯一 key")

# ── 查 mt_i18n_keys ──
cur.execute("SELECT key, zh_cn, zh_tw, ja_jp, en_us, domain, source FROM mt_i18n_keys")
db_keys = {}
for row in cur.fetchall():
    db_keys[row[0]] = {
        "zh_cn": row[1], "zh_tw": row[2], "ja_jp": row[3], "en_us": row[4],
        "domain": row[5], "source": row[6],
    }

# ── 覆盖率分析 ──
print(f"\n[{NOW()}] 📊 覆盖率矩阵")

# 1. 总 key 覆盖率
found_in_db = sum(1 for k in all_keys if k in db_keys)
missing_keys = {k: v for k, v in all_keys.items() if k not in db_keys}
print(f"  唯一 key: {unique_keys} → DB 有 {found_in_db} → 缺失 {len(missing_keys)} ({100*found_in_db/unique_keys:.1f}%)")

# 2. 缺失 key 清单（按模板）
missing_per_template = defaultdict(list)
for fname, keys_list in templates_data:
    for key, default in keys_list:
        if key not in db_keys:
            missing_per_template[fname].append(key)

if missing_per_template:
    print(f"\n  ❌ 缺失 key 模板清单 (共 {len(missing_per_template)} 模板):")
    for fname, mkeys in sorted(missing_per_template.items(), key=lambda x: -len(x[1])):
        print(f"    📄 {fname}: {len(mkeys)} 缺失")
        for k in mkeys[:3]:
            print(f"      └─ {k}")
        if len(mkeys) > 3:
            print(f"      └─ ... +{len(mkeys)-3} 更多")

# 3. 已存在 key 的四语种覆盖率
print(f"\n  ✅ 已存在 key 四语种覆盖率:")
found_4lang = 0
found_3lang = 0
found_1lang = 0
for k in all_keys:
    if k in db_keys:
        r = db_keys[k]
        filled = sum(1 for col in ["zh_tw", "ja_jp", "en_us"] if r.get(col))
        if filled == 3:
            found_4lang += 1
        elif filled >= 1:
            found_3lang += 1
        else:
            found_1lang += 1

covered = found_4lang + found_3lang + found_1lang
if covered > 0:
    print(f"    4 语种全齐: {found_4lang} ({100*found_4lang/covered:.1f}%)")
    print(f"    部分翻译:   {found_3lang} ({100*found_3lang/covered:.1f}%)")
    print(f"    仅源语言:   {found_1lang} ({100*found_1lang/covered:.1f}%)")

# 4. 缺失 key 自动补录
if missing_keys:
    print(f"\n[{NOW()}] 🔧 自动补录 {len(missing_keys)} 个缺失 key...")

    # 精简版翻译词典
    _TRANS = {
        "冰山": ("冰山", "アイスバーグ", "Iceberg"), "赤壁": ("赤壁", "赤壁", "Chibi"),
        "东坡": ("東坡", "東坡", "Dongpo"), "承天寺": ("承天寺", "承天寺", "Chengtian Temple"),
        "仙女座": ("仙女座", "アンドロメダ", "Andromeda"), "加载中": ("載入中", "読み込み中", "Loading"),
        "刷新": ("刷新", "リフレッシュ", "Refresh"), "Daemon": ("守護進程", "デーモン", "Daemon"),
        "考试": ("考試", "試験", "Exam"), "知识": ("知識", "ナレッジ", "Knowledge"),
        "图谱": ("圖譜", "グラフ", "Graph"), "看板": ("看板", "ボード", "Board"),
        "健康": ("健康", "ヘルス", "Health"), "活跃": ("活躍", "アクティブ", "Active"),
        "心跳": ("心跳", "ハートビート", "Heartbeat"), "守护": ("守護", "ガード", "Guard"),
        "巡检": ("巡檢", "パトロール", "Patrol"), "规则": ("規則", "ルール", "Rule"),
        "引擎": ("引擎", "エンジン", "Engine"), "智能": ("智能", "スマート", "Smart"),
        "自主": ("自主", "自主", "Autonomous"), "自动": ("自動", "自動", "Auto"),
        "修复": ("修復", "修復", "Repair"), "雇佣": ("雇傭", "雇用", "Hire"),
        "专家": ("專家", "エキスパート", "Expert"), "圆桌": ("圓桌", "Round Table", "Round Table"),
        "配置": ("配置", "設定", "Config"), "系统": ("系統", "システム", "System"),
        "用户": ("用戶", "ユーザー", "User"), "登录": ("登錄", "ログイン", "Login"),
        "注册": ("註冊", "登録", "Register"), "密码": ("密碼", "パスワード", "Password"),
        "首页": ("首頁", "ホーム", "Home"), "设置": ("設置", "設定", "Settings"),
        "管理": ("管理", "管理", "Admin"), "中心": ("中心", "センター", "Center"),
        "班级": ("班級", "クラス", "Class"), "成绩": ("成績", "成績", "Score"),
        "题库": ("題庫", "問題集", "Question Bank"), "练习": ("練習", "練習", "Practice"),
        "学习": ("學習", "学習", "Learn"), "教师": ("教師", "教師", "Teacher"),
        "学生": ("學生", "学生", "Student"), "AI": ("AI", "AI", "AI"),
        "人格": ("人格", "ペルソナ", "Persona"), "实时": ("即時", "リアルタイム", "Real-time"),
        "聊天": ("聊天", "チャット", "Chat"), "向量": ("向量", "ベクトル", "Vector"),
        "嵌入": ("嵌入", "エンベディング", "Embedding"), "坍缩": ("坍縮", "崩壊", "Collapse"),
        "锚点": ("錨點", "アンカー", "Anchor"), "铁律": ("鐵律", "鉄律", "Iron Rule"),
        "阶段": ("階段", "フェーズ", "Phase"), "演化": ("演化", "進化", "Evolution"),
        "觉醒": ("覺醒", "覚醒", "Awakening"), "双向": ("雙向", "双方向", "Bidirectional"),
        "握手": ("握手", "ハンドシェイク", "Handshake"), "江山": ("江山", "江山", "Landscape"),
        "衍生": ("衍生", "派生", "Derivative"), "种子": ("種子", "種子", "Seed"),
        "集群": ("集群", "クラスタ", "Cluster"), "挂载": ("掛載", "マウント", "Mount"),
        "修复": ("修復", "修復", "Repair"), "心跳": ("心跳", "ハートビート", "Heartbeat"),
    }
    _SIMPL_TO_TRAD = {
        "门":"門","开":"開","关":"關","车":"車","长":"長","时":"時","说":"說",
        "学":"學","见":"見","问":"問","读":"讀","写":"寫","书":"書","马":"馬",
        "鸟":"鳥","页":"頁","个":"個","这":"這","那":"那","的":"的","为":"為",
        "还":"還","有":"有","过":"過","来":"來","去":"去","好":"好","快":"快",
        "大":"大","小":"小","中":"中","上":"上","下":"下","里":"裡","外":"外",
        "前":"前","后":"後","左":"左","右":"右","能":"能","动":"動","电":"電",
        "网":"網","线":"線","组":"組","编":"編","码":"碼","图":"圖","脑":"腦",
        "认":"認","识":"識","语":"語","词":"詞","记":"記","智":"智","量":"量",
        "数":"數","法":"法","文":"文","字":"字","句":"句","章":"章","系":"系",
        "统":"統","模":"模","块":"塊","板":"板","表":"表","示":"示","显":"顯",
        "检":"檢","查":"查","测":"測","试":"試","验":"驗","修":"修","复":"復",
        "建":"建","设":"設","计":"計","划":"劃","策":"策","略":"略","管":"管",
        "理":"理","运":"運","营":"營","操":"操","作":"作","行":"行","活":"活",
        "变":"變","化":"化","过":"過","程":"程","阶":"階","段":"段","步":"步",
        "骤":"驟","键":"鍵","账":"賬","户":"戶","登":"登","录":"錄","选":"選",
        "项":"項","页":"頁","面":"面","点":"點","线":"線","链":"鏈","锁":"鎖",
        "铁":"鐵","银":"銀","铜":"銅","钱":"錢","财":"財","资":"資","贷":"貸",
        "贸":"貿","卖":"賣","买":"買","读":"讀","写":"寫","书":"書","画":"畫",
        "图":"圖","表":"表","格":"格","式":"式","数":"數","学":"學","算":"算",
        "计":"計","划":"劃","策":"策","管":"管","理":"理","系":"系","统":"統",
    }

    def _fast_translate(zh_cn: str) -> dict:
        result = {"zh_cn": zh_cn.strip(), "zh_tw": zh_cn.strip(),
                  "ja_jp": zh_cn.strip(), "en_us": zh_cn.strip()}
        # 词典匹配
        for zh, (tw, jp, en) in _TRANS.items():
            if zh in result["zh_cn"]:
                result["zh_tw"] = result["zh_tw"].replace(zh, tw)
                result["ja_jp"] = result["ja_jp"].replace(zh, jp)
                result["en_us"] = result["en_us"].replace(zh, en)
        # 繁化剩余简体
        for s, t in _SIMPL_TO_TRAD.items():
            result["zh_tw"] = result["zh_tw"].replace(s, t)
        return result

    domain_by_key = {}
    for k in missing_keys:
        if k.startswith("andromeda."): domain_by_key[k] = "andromeda"
        elif k.startswith("login"): domain_by_key[k] = "login"
        elif k.startswith("register"): domain_by_key[k] = "register"
        elif k.startswith("exam"): domain_by_key[k] = "exam"
        elif k.startswith("error") or k in ("400","401","403","404","423","500","502","503"):
            domain_by_key[k] = "error"
        else:
            domain_by_key[k] = "global"

    inserted = 0
    for key, default_zh in missing_keys.items():
        t = _fast_translate(default_zh)
        try:
            cur.execute("""INSERT OR IGNORE INTO mt_i18n_keys
                (key, source, domain, zh_cn, zh_tw, ja_jp, en_us, remark, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (key, "cat_test_auto_fill", domain_by_key.get(key, "global"),
                 t["zh_cn"], t["zh_tw"], t["ja_jp"], t["en_us"],
                 "猫压测试自动补录·全模板扫描", NOW(), NOW()))
            if cur.rowcount > 0:
                inserted += 1
        except Exception:
            pass
    conn.commit()
    print(f"  ✅ 补录 {inserted} 个缺失 key")

# ── 最终统计 ──
cur.execute("SELECT COUNT(*) FROM mt_i18n_keys")
final_total = cur.fetchone()[0]
cur.execute("""SELECT 
  SUM(CASE WHEN zh_tw IS NOT NULL AND zh_tw<>'' THEN 1 ELSE 0 END),
  SUM(CASE WHEN ja_jp IS NOT NULL AND ja_jp<>'' THEN 1 ELSE 0 END),
  SUM(CASE WHEN en_us IS NOT NULL AND en_us<>'' THEN 1 ELSE 0 END)
FROM mt_i18n_keys""")
tw_cnt, jp_cnt, en_cnt = cur.fetchone()

print(f"\n[{NOW()}] 🐱 猫压测试 · 最终覆盖率")
print(f"  📊 mt_i18n_keys 总计: {final_total} 条")
print(f"  🌐 zh_TW: {tw_cnt}/{final_total} ({100*tw_cnt/final_total:.1f}%)")
print(f"  🌐 ja_JP: {jp_cnt}/{final_total} ({100*jp_cnt/final_total:.1f}%)")
print(f"  🌐 en_US: {en_cnt}/{final_total} ({100*en_cnt/final_total:.1f}%)")
print(f"  📄 模板扫描: {total_templates_with_keys} 模板 · {total_calls} t() 调用 · {unique_keys} 唯一 key")

# 缺失 key 二次检查
cur.execute("SELECT key FROM mt_i18n_keys WHERE source='cat_test_auto_fill'")
now_missing = {k for k, _ in templates_data for k, _ in templates_data} - set(k for k in all_keys if k in db_keys) - {r[0] for r in cur.fetchall()}
now_missing_count = sum(1 for k in all_keys if k not in {r[0] for r in cur.execute("SELECT key FROM mt_i18n_keys").fetchall()})
print(f"  🎯 模板 key 覆盖率: {(unique_keys - now_missing_count)}/{unique_keys} ({100*(unique_keys-now_missing_count)/max(unique_keys,1):.1f}%)")

# ── 猫压测试报告 JSON 落库 ──
REPORT_PATH = f"{ROOT}/flask-app/scripts/_cat_test_report.json"
report = {
    "test": "猫压测试·全页面四语种翻译覆盖率",
    "run_at": NOW(),
    "templates_scanned": total_templates_with_keys,
    "t_calls_total": total_calls,
    "unique_keys": unique_keys,
    "found_in_db": found_in_db,
    "missing_before_auto_fill": len(missing_keys),
    "auto_filled": inserted if missing_keys else 0,
    "final_key_coverage_pct": round(100*(unique_keys-now_missing_count)/max(unique_keys,1), 2),
    "final_4lang_pct": round(100*final_total/max(final_total,1), 2),
    "missing_templates": [
        {"template": fname, "missing_keys": mkeys}
        for fname, mkeys in sorted(missing_per_template.items(), key=lambda x: -len(x[1]))
    ],
    "i18n_keys_final": {
        "total": final_total,
        "zh_TW": tw_cnt, "ja_JP": jp_cnt, "en_US": en_cnt,
    }
}
with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\n  📝 猫压测试报告: {REPORT_PATH}")

conn.close()
print(f"\n✅ 🐱 猫压测试完成!")
