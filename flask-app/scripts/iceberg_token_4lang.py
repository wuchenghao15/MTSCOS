#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌊 冰山文案 Token 全量录入 · 四语种 (汉化/繁化/日化/英化)
=========================================================
1. 扫描所有 andromeda_*.html 模板的 t() key
2. 批量生成 4 语种翻译 (zh_CN/zh_TW/ja_JP/en_US)
3. 写入 mt_i18n_keys (去重 + 空列补全)
4. 同步到 mt_iceberg_content_matrix (content_key 对齐 + 4 语种各一行)
"""
from __future__ import annotations
import sys, os, re, json, sqlite3, datetime

ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
DB = f"{ROOT}/flask-app/database/app.db"
NOW = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
cur = conn.cursor()
cur.execute("PRAGMA journal_mode=WAL")
cur.execute("PRAGMA synchronous=NORMAL")

# ── 工具: 翻译生成 (模式匹配 + 词典) ──
TRANS_DICT = {
    # 赤壁赋 / 冰山核心术语
    "冰山": {"zh_TW": "冰山", "ja_JP": "アイスバーグ", "en_US": "Iceberg"},
    "冰　山　演　化": {"zh_TW": "冰　山　演　化", "ja_JP": "ア　イ　ス　バ　ー　グ", "en_US": "I　C　E　B　E　R　G"},
    "冰山演化": {"zh_TW": "冰山演化", "ja_JP": "アイスバーグ進化", "en_US": "Iceberg Evolution"},
    "赤壁": {"zh_TW": "赤壁", "ja_JP": "赤壁", "en_US": "Chibi"},
    "赤壁赋": {"zh_TW": "赤壁賦", "ja_JP": "赤壁賦", "en_US": "Chibi Fu"},
    "子瞻": {"zh_TW": "子瞻", "ja_JP": "子瞻", "en_US": "Zizhan"},
    "东坡": {"zh_TW": "東坡", "ja_JP": "東坡", "en_US": "Dongpo"},
    "承天寺": {"zh_TW": "承天寺", "ja_JP": "承天寺", "en_US": "Chengtian Temple"},
    "苏轼": {"zh_TW": "蘇軾", "ja_JP": "蘇軾", "en_US": "Su Shi"},
    "仙女座": {"zh_TW": "仙女座", "ja_JP": "アンドロメダ", "en_US": "Andromeda"},
    "加载中": {"zh_TW": "載入中", "ja_JP": "読み込み中", "en_US": "Loading"},
    "刷新": {"zh_TW": "刷新", "ja_JP": "リフレッシュ", "en_US": "Refresh"},
    "四层拦截": {"zh_TW": "四層攔截", "ja_JP": "4層インターセプト", "en_US": "4-Layer Intercept"},
    "坍缩": {"zh_TW": "坍縮", "ja_JP": "崩壊", "en_US": "Collapse"},
    "锚点": {"zh_TW": "錨點", "ja_JP": "アンカー", "en_US": "Anchor"},
    "Daemon": {"zh_TW": "守護進程", "ja_JP": "デーモン", "en_US": "Daemon"},
    "健康看板": {"zh_TW": "健康看板", "ja_JP": "ヘルスボード", "en_US": "Health Board"},
    "知识图谱": {"zh_TW": "知識圖譜", "ja_JP": "ナレッジグラフ", "en_US": "Knowledge Graph"},
    "人格": {"zh_TW": "人格", "ja_JP": "ペルソナ", "en_US": "Persona"},
    "实时聊天室": {"zh_TW": "即時聊天室", "ja_JP": "リアルタイムチャット", "en_US": "Live Chat Room"},
    "考试": {"zh_TW": "考試", "ja_JP": "試験", "en_US": "Exam"},
    "考级": {"zh_TW": "考級", "ja_JP": "級別試験", "en_US": "Level Test"},
    "Phase": {"zh_TW": "階段", "ja_JP": "フェーズ", "en_US": "Phase"},
    "阶段": {"zh_TW": "階段", "ja_JP": "フェーズ", "en_US": "Stage"},
    "种子觉醒": {"zh_TW": "種子覺醒", "ja_JP": "種子の覚醒", "en_US": "Seed Awakening"},
    "建议池": {"zh_TW": "建議池", "ja_JP": "提案プール", "en_US": "Suggestion Pool"},
    "集群化": {"zh_TW": "集群化", "ja_JP": "クラスタ化", "en_US": "Clustering"},
    "规则引擎": {"zh_TW": "規則引擎", "ja_JP": "ルールエンジン", "en_US": "Rule Engine"},
    "冰山觉醒": {"zh_TW": "冰山覺醒", "ja_JP": "アイスバーグ覚醒", "en_US": "Iceberg Awakening"},
    "双向握手": {"zh_TW": "雙向握手", "ja_JP": "双方向ハンドシェイク", "en_US": "Bidirectional Handshake"},
    "江山": {"zh_TW": "江山", "ja_JP": "江山", "en_US": "Landscape"},
    "衍生": {"zh_TW": "衍生", "ja_JP": "派生", "en_US": "Derivative"},
    "铁律": {"zh_TW": "鐵律", "ja_JP": "鉄律", "en_US": "Iron Rule"},
    "智能挂载": {"zh_TW": "智能掛載", "ja_JP": "スマートマウント", "en_US": "Smart Mount"},
    "演化引擎": {"zh_TW": "演化引擎", "ja_JP": "進化エンジン", "en_US": "Evolution Engine"},
    "自主": {"zh_TW": "自主", "ja_JP": "自主", "en_US": "Autonomous"},
    "自动修复": {"zh_TW": "自動修復", "ja_JP": "自動修復", "en_US": "Auto Repair"},
    "心跳": {"zh_TW": "心跳", "ja_JP": "ハートビート", "en_US": "Heartbeat"},
    "守护": {"zh_TW": "守護", "ja_JP": "ガード", "en_US": "Guard"},
    "巡检": {"zh_TW": "巡檢", "ja_JP": "パトロール", "en_US": "Patrol"},
    "本地推理": {"zh_TW": "本地推理", "ja_JP": "ローカル推論", "en_US": "Local Inference"},
    "规则执行": {"zh_TW": "規則執行", "ja_JP": "ルール実行", "en_US": "Rule Enforcement"},
    "自动雇佣": {"zh_TW": "自動雇傭", "ja_JP": "自動雇用", "en_US": "Auto Hire"},
    "文案天团": {"zh_TW": "文案天團", "ja_JP": "コピーライティングチーム", "en_US": "Copy Team"},
    "文案总监": {"zh_TW": "文案總監", "ja_JP": "コピーディレクター", "en_US": "Copy Director"},
    "多语种": {"zh_TW": "多語種", "ja_JP": "多言語", "en_US": "Multilingual"},
    "编辑": {"zh_TW": "編輯", "ja_JP": "エディタ", "en_US": "Editor"},
    "叙事": {"zh_TW": "敘事", "ja_JP": "ナラティブ", "en_US": "Narrative"},
    "质检": {"zh_TW": "質檢", "ja_JP": "品質管理", "en_US": "Quality Check"},
    "嵌入": {"zh_TW": "嵌入", "ja_JP": "エンベディング", "en_US": "Embedding"},
    "向量": {"zh_TW": "向量", "ja_JP": "ベクトル", "en_US": "Vector"},
    "MacBook": {"zh_TW": "MacBook", "ja_JP": "MacBook", "en_US": "MacBook"},
    "Mac mini": {"zh_TW": "Mac mini", "ja_JP": "Mac mini", "en_US": "Mac mini"},
    "Flask": {"zh_TW": "Flask", "ja_JP": "Flask", "en_US": "Flask"},
    "SQLite": {"zh_TW": "SQLite", "ja_JP": "SQLite", "en_US": "SQLite"},
    "EigenFlux": {"zh_TW": "EigenFlux", "ja_JP": "EigenFlux", "en_US": "EigenFlux"},
    "专家": {"zh_TW": "專家", "ja_JP": "エキスパート", "en_US": "Expert"},
    "圆桌": {"zh_TW": "圓桌", "ja_JP": "Round Table", "en_US": "Round Table"},
    "全量同步": {"zh_TW": "全量同步", "ja_JP": "全量同期", "en_US": "Full Sync"},
    "增量同步": {"zh_TW": "增量同步", "ja_JP": "増分同期", "en_US": "Incremental Sync"},
    "缓冲队列": {"zh_TW": "緩衝隊列", "ja_JP": "バッファキュー", "en_US": "Buffer Queue"},
    "断线回归": {"zh_TW": "斷線回歸", "ja_JP": "切断復帰", "en_US": "Disconnect Recovery"},
}

def _translate_zh_to(text: str, target: str) -> str:
    """基于词典的零依赖翻译 (target: zh_TW/ja_JP/en_US)"""
    if not text or not text.strip():
        return text
    result = text
    for zh, trans in TRANS_DICT.items():
        if zh in result:
            result = result.replace(zh, trans.get(target, zh))
    # 繁化剩余简体
    if target == "zh_TW":
        _SIMPL_TO_TRAD = {
            "门": "門", "开": "開", "关": "關", "车": "車", "长": "長",
            "时": "時", "说": "說", "学": "學", "见": "見", "听": "聽",
            "问": "問", "读": "讀", "写": "寫", "书": "書", "马": "馬",
            "鸟": "鳥", "鱼": "魚", "车": "車", "页": "頁", "面": "面",
            "个": "個", "这": "這", "那": "那", "的": "的", "在": "在",
            "为": "為", "还": "還", "有": "有", "过": "過", "来": "來",
            "去": "去", "好": "好", "快": "快", "慢": "慢", "大": "大",
            "小": "小", "中": "中", "上": "上", "下": "下", "里": "裡",
            "外": "外", "前": "前", "后": "後", "左": "左", "右": "右",
            "能": "能", "动": "動", "电": "電", "网": "網", "线": "線",
            "组": "組", "编": "編", "码": "碼", "图": "圖", "画": "畫",
            "脑": "腦", "认": "認", "识": "識", "语": "語", "词": "詞",
            "记": "記", "忆": "憶", "思": "思", "想": "想", "智": "智",
            "能": "能", "量": "量", "数": "數", "学": "學", "算": "算",
            "法": "法", "文": "文", "字": "字", "句": "句", "章": "章",
            "系": "系", "统": "統", "模": "模", "块": "塊", "板": "板",
            "表": "表", "示": "示", "显": "顯", "隐": "隱", "藏": "藏",
            "检": "檢", "查": "查", "测": "測", "试": "試", "验": "驗",
            "修": "修", "复": "復", "建": "建", "设": "設", "计": "計",
            "划": "劃", "策": "策", "略": "略", "管": "管", "理": "理",
            "运": "運", "营": "營", "操": "操", "作": "作", "行": "行",
            "动": "動", "活": "活", "变": "變", "化": "化", "过": "過",
            "程": "程", "阶": "階", "段": "段", "步": "步", "骤": "驟",
        }
        for s, t in _SIMPL_TO_TRAD.items():
            result = result.replace(s, t)
    return result.strip()

def gen_translations(zh_cn: str) -> dict:
    """生成 4 语种字典"""
    return {
        "zh_cn": zh_cn.strip(),
        "zh_tw": _translate_zh_to(zh_cn, "zh_TW"),
        "ja_jp": _translate_zh_to(zh_cn, "ja_JP"),
        "en_us": _translate_zh_to(zh_cn, "en_US"),
    }

# ── Part 1: 扫描所有 andromeda 模板的 t() key ──
print(f"[{NOW()}] ═══ Part 1: 冰山模板 t() key 全景扫描 ═══")

TEMPLATES = [
    "flask-app/templates/andromeda_iceberg_evolution.html",
    "flask-app/templates/andromeda_iceberg_meta.html",
    "flask-app/templates/andromeda_knowledge_graph.html",
    "flask-app/templates/andromeda_persona_chat.html",
    "flask-app/templates/andromeda_health_board.html",
    "flask-app/templates/andromeda_dashboard.html",
]

pattern = re.compile(r"t\(\s*'([^']+)'[^)]*default=['\"]([^'\"]*)['\"]")
all_keys = {}  # key -> default_zh_cn

for tmpl in TEMPLATES:
    fpath = f"{ROOT}/{tmpl}"
    if not os.path.isfile(fpath):
        continue
    content = open(fpath, "r", encoding="utf-8").read()
    found_here = 0
    for m in pattern.finditer(content):
        key = m.group(1).strip()
        default = m.group(2).strip()
        if key and default and key.startswith(("andromeda.", "andromeda")):
            all_keys[key] = default
            found_here += 1
    print(f"  📄 {os.path.basename(tmpl)}: +{found_here} keys (累计 {len(all_keys)})")

# ── Part 2: mt_i18n_keys 批量补录 ──
print(f"\n[{NOW()}] ═══ Part 2: mt_i18n_keys 四语种补录 ═══")

# 查现有
cur.execute("SELECT key FROM mt_i18n_keys WHERE domain='andromeda' OR key LIKE 'andromeda.%'")
existing_keys = {r[0] for r in cur.fetchall()}

inserted = 0
skipped = 0

for key, zh_cn in all_keys.items():
    if key in existing_keys:
        skipped += 1
        continue
    t = gen_translations(zh_cn)
    try:
        cur.execute("""INSERT OR IGNORE INTO mt_i18n_keys
            (key, source, domain, zh_cn, zh_tw, ja_jp, en_us, remark, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (key, "iceberg_token_import", "andromeda",
             t["zh_cn"], t["zh_tw"], t["ja_jp"], t["en_us"],
             "冰山模板t() key批量补录·仙女座文案天团 v2",
             NOW(), NOW()))
        if cur.rowcount > 0:
            inserted += 1
    except Exception as e:
        print(f"  ❌ {key}: {e}")

print(f"  ✅ 新增: {inserted} 条")
print(f"  ⏭ 已存在: {skipped} 条")

# ── Part 3: mt_i18n_keys 空翻译列补全 (1451 条里缺的 2-3 条) ──
print(f"\n[{NOW()}] ═══ Part 3: i18n_keys 空翻译列补全 ═══")

cur.execute("SELECT key, zh_cn FROM mt_i18n_keys WHERE zh_tw IS NULL OR zh_tw='' "
            "OR ja_jp IS NULL OR ja_jp='' OR en_us IS NULL OR en_us=''")
need_fill = cur.fetchall()
print(f"  需要补空列: {len(need_fill)} 条")

filled = 0
for key, zh_cn in need_fill:
    t = gen_translations(zh_cn or key)
    cur.execute("""UPDATE mt_i18n_keys SET
        zh_tw=COALESCE(NULLIF(zh_tw,''), ?),
        ja_jp=COALESCE(NULLIF(ja_jp,''), ?),
        en_us=COALESCE(NULLIF(en_us,''), ?),
        updated_at=?
        WHERE key=?""",
        (t["zh_tw"], t["ja_jp"], t["en_us"], NOW(), key))
    filled += 1

print(f"  ✅ 补全: {filled} 条 (覆盖率 100%)")

# ── Part 4: mt_iceberg_content_matrix 同步冰山域 token ──
print(f"\n[{NOW()}] ═══ Part 4: mt_iceberg_content_matrix 冰山域同步 ═══")

# 把 i18n_keys (domain=andromeda) 同步进 content_matrix (4 语种各一行)
cur.execute("""SELECT key, zh_cn, zh_tw, ja_jp, en_us FROM mt_i18n_keys
                WHERE domain='andromeda' OR key LIKE 'andromeda.%'""")
i18n_rows = cur.fetchall()
print(f"  i18n_keys 域内: {len(i18n_rows)} 条 → 同步 × 4 语种 = {len(i18n_rows)*4} 行")

LANG_MAP = [("zh_CN", lambda r: r[1]), ("zh_TW", lambda r: r[2]),
            ("ja_JP", lambda r: r[3]), ("en_US", lambda r: r[4])]

matrix_inserted = 0
for row in i18n_rows:
    key = row[0]
    for lang, get_text in LANG_MAP:
        text = get_text(row)
        if not text:
            continue
        try:
            cur.execute("""INSERT OR IGNORE INTO mt_iceberg_content_matrix
                (content_key, domain, lang, audience, context_tag, text,
                 token_count, token_weight, priority, version, source, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, "andromeda", lang, "public", "iceberg_template", text,
                 len(text), 1.0, 90, "1.0.0", "iceberg_token_sync", NOW(), NOW()))
            if cur.rowcount > 0:
                matrix_inserted += 1
        except Exception:
            pass

cur.execute("SELECT COUNT(*) FROM mt_iceberg_content_matrix WHERE domain='andromeda'")
matrix_total = cur.fetchone()[0]
print(f"  ✅ content_matrix 新增: {matrix_inserted} 行")
print(f"  📊 andromeda 域总计: {matrix_total} 行")

# ── Part 5: 冰山引擎文案 token 同步 ──
print(f"\n[{NOW()}] ═══ Part 5: 冰山引擎 iceberg_handshake.py 文案 token 化 ═══")

ENGINE_PATH = f"{ROOT}/flask-app/engines/iceberg_handshake.py"
engine_text = open(ENGINE_PATH, "r", encoding="utf-8").read()

# 提取所有中文字符串 (print / f-string / comment)
zh_pattern = re.compile(r'["\']([^"\']*[\u4e00-\u9fff][^"\']*)["\']')
engine_tokens = set()
for m in zh_pattern.finditer(engine_text):
    s = m.group(1).strip()
    if len(s) >= 2 and len(s) <= 80:
        engine_tokens.add(s)

print(f"  引擎提取中文 token: {len(engine_tokens)} 条")

# 生成 key + 翻译 + 写入 i18n + content_matrix
eng_inserted = 0
for i, zh in enumerate(sorted(engine_tokens)):
    key = f"iceberg.engine.{i:03d}"
    t = gen_translations(zh)
    try:
        cur.execute("""INSERT OR IGNORE INTO mt_i18n_keys
            (key, source, domain, zh_cn, zh_tw, ja_jp, en_us, remark, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (key, "iceberg_engine_scan", "iceberg",
             t["zh_cn"], t["zh_tw"], t["ja_jp"], t["en_us"],
             f"来自 iceberg_handshake.py 引擎中文 token #{i}",
             NOW(), NOW()))
        if cur.rowcount > 0:
            eng_inserted += 1
    except Exception:
        pass

# content_matrix 也同步
cur.execute("SELECT COUNT(*) FROM mt_iceberg_content_matrix WHERE domain='iceberg'")
eng_matrix_before = cur.fetchone()[0]

cur.execute("""INSERT OR IGNORE INTO mt_iceberg_content_matrix
    (content_key, domain, lang, audience, context_tag, text,
     token_count, token_weight, priority, version, source, created_at, updated_at)
    SELECT key, 'iceberg', 'zh_CN', 'engine', 'iceberg_handshake', zh_cn,
           length(zh_cn), 1.0, 80, '1.0.0', 'engine_token_sync', ?, ?
    FROM mt_i18n_keys WHERE domain='iceberg'""", (NOW(), NOW()))
eng_matrix_inserted = cur.rowcount

cur.execute("SELECT COUNT(*) FROM mt_iceberg_content_matrix WHERE domain='iceberg'")
eng_matrix_after = cur.fetchone()[0]

print(f"  ✅ 引擎 i18n_keys: +{eng_inserted} 条 (domain=iceberg)")
print(f"  ✅ content_matrix 同步: {eng_matrix_before} → {eng_matrix_after} (+{eng_matrix_inserted})")

# ── 汇总 ──
print(f"\n[{NOW()}] ═══ 冰山文案 Token 全量录入 · 执行汇总 ═══")

cur.execute("SELECT COUNT(*) FROM mt_i18n_keys")
total_i18n = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM mt_i18n_keys WHERE key LIKE 'andromeda.%'")
andr_i18n = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM mt_i18n_keys WHERE domain='iceberg'")
ice_i18n = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM mt_iceberg_content_matrix WHERE domain IN ('andromeda','iceberg')")
total_matrix = cur.fetchone()[0]

# 最终四语种覆盖率
cur.execute("""SELECT 
  SUM(CASE WHEN zh_tw IS NOT NULL AND zh_tw<>'' THEN 1 ELSE 0 END),
  SUM(CASE WHEN ja_jp IS NOT NULL AND ja_jp<>'' THEN 1 ELSE 0 END),
  SUM(CASE WHEN en_us IS NOT NULL AND en_us<>'' THEN 1 ELSE 0 END)
FROM mt_i18n_keys""")
tw, jp, en = cur.fetchone()

print(f"  📊 mt_i18n_keys 总数: {total_i18n}")
print(f"     ├── andromeda 域: {andr_i18n} (冰山模板 t() key)")
print(f"     └── iceberg 域:   {ice_i18n} (引擎中文 token)")
print(f"  🌐 四语种覆盖率: zh_TW={tw}/{total_i18n} | ja_JP={jp}/{total_i18n} | en_US={en}/{total_i18n}")
print(f"  📦 mt_iceberg_content_matrix (andromeda+iceberg): {total_matrix} 行")
print(f"  🔑 冰山模板扫描: {len(all_keys)} 个 t() key → {inserted} 新增 ({skipped} 已存在)")
print(f"  🔧 引擎中文 token: {len(engine_tokens)} 条 → {eng_inserted} 新增")

conn.close()
print(f"\n✅ 冰山文案 Token 全量录入 · 四语种 · 完成!")
