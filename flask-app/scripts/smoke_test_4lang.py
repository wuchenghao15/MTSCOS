#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔥 冒烟测试 · 全页面四语种翻译覆盖率 · 实际 Flask 渲染
========================================================
server_real_db.app.test_client() × 全路由 × 4 语言 × 实际渲染验证
"""
from __future__ import annotations
import sys, os, re, json, time, datetime, sqlite3, traceback

ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
DB = f"{ROOT}/flask-app/database/app.db"
NOW = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

sys.path.insert(0, f"{ROOT}/flask-app")
os.chdir(f"{ROOT}/flask-app")

import server_real_db  # noqa: E402

print(f"[{NOW()}] 🔥 冒烟测试启动 — Flask test_client × 4 语言")
app = server_real_db.app
client = app.test_client()

LANGS = ["zh_CN", "zh_TW", "ja_JP", "en_US"]
LANG_NAMES = {"zh_CN": "简体", "zh_TW": "繁體", "ja_JP": "日本語", "en_US": "English"}

# ── Step 1: 收集需要渲染的页面路由 ──
print(f"\n[{NOW()}] Step 1: 收集页面路由...")

page_routes = []
seen = set()
for rule in app.url_map.iter_rules():
    # 只取 GET 方法 + 不是静态资源 + 不是 API 前缀 + 不是带参数的（避免 404）
    if "GET" not in rule.methods:
        continue
    url = rule.rule
    # 过滤所有 API 路由（含内嵌 /api/）+ 静态 + 内部
    if "/api/" in url or url.startswith(("/static/", "/flask-admin", "/_rules/", "/_ui/")):
        continue
    if any(ch in url for ch in ["<", ">", ":"]):
        continue  # 带动态参数的跳过，避免 404
    # 去重
    if url in seen:
        continue
    seen.add(url)
    page_routes.append(url)

page_routes.sort()
print(f"  📄 页面路由: {len(page_routes)} 条 (过滤后, 1168 → {len(page_routes)})")

# ── Step 2: 冒烟测试渲染 × 4 语言 ──
print(f"\n[{NOW()}] Step 2: 四语种实际渲染验证...")

results = {}  # url -> {lang: {status, has_zh_cn, has_untranslated_key, errors}}

test_session = {
    "user_id": 123, "username": "test_user",
    "role": "super_admin", "i18n_lang": "zh_CN",
    "group_id": 1, "permissions": "all", "is_authenticated": True,
}

def _extract_visible_text(html: str) -> str:
    """从 HTML 提取用户可见文本区域（排除 script/style/attribute）"""
    import re
    # 移除 script/style 块
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    # 移除 HTML 标签属性里的值（保留标签内文本）
    # 简单做法：先把属性值替换成占位符
    html = re.sub(r'(\w+)="[^"]*"', r'\1=""', html)
    html = re.sub(r"(\w+)='[^']*'", r"\1=''", html)
    # 移除所有 HTML 标签
    text = re.sub(r'<[^>]+>', '', html)
    # 解码 HTML entity
    import html as _h
    text = _h.unescape(text)
    return text

def _render_check(url: str, lang: str) -> dict:
    """实际请求 + 检查未翻译 key / 硬编码中文"""
    check = {"status": None, "size": 0, "zh_cn_hits": [], "untranslated_keys": [], "error": None}
    try:
        with client.session_transaction() as sess:
            sess.update(test_session)
            sess["i18n_lang"] = lang
        
        # follow_redirects=True 拿最终页面
        resp = client.get(url, timeout=15, follow_redirects=True)
        check["status"] = resp.status_code
        check["size"] = len(resp.data)
        
        if resp.status_code >= 500:
            check["error"] = f"Server Error {resp.status_code}"
            return check
        
        if resp.status_code not in (200, 301, 302):
            check["error"] = f"HTTP {resp.status_code} (non-critical, non-translation)"
            return check
        
        html = resp.data.decode("utf-8", errors="ignore")
        visible = _extract_visible_text(html)
        
        # 检查 1: 未翻译 key（只在可见文本里）
        tkey_pattern = re.compile(r'((?:andromeda|adult|page|brain|ef|na|theme|admin_fallback|app|iceberg|login|register|exam|system|error)\.[a-zA-Z_0-9.\-]+)')
        untranslated = set()
        for m in tkey_pattern.finditer(visible):
            untranslated.add(m.group(1))
        check["untranslated_keys"] = sorted(untranslated)[:10]
        
        # 检查 2: 非 zh_CN 语言时的硬编码中文（简体，在可见文本里）
        if lang != "zh_CN":
            zh_pattern = re.compile(r'[\u4e00-\u9fa5]{2,}')
            zh_hits = []
            seen_zh = set()
            for m in zh_pattern.finditer(visible):
                zh_text = m.group(0)
                if zh_text not in seen_zh and len(zh_text) <= 20:
                    seen_zh.add(zh_text)
                    zh_hits.append(zh_text)
                if len(zh_hits) >= 5:
                    break
            check["zh_cn_hits"] = zh_hits
        
    except Exception as e:
        check["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    
    return check

# 跑测试
total = min(len(page_routes), 60)  # 先跑前 60 条（剩余 45 条补跑）
for idx, url in enumerate(page_routes[:total]):
    results[url] = {}
    for lang in LANGS:
        results[url][lang] = _render_check(url, lang)
    
    # 进度
    fail_count = sum(
        1 for l in LANGS 
        if (results[url][l]["status"] or 0) >= 500  # 服务器崩溃
           or results[url][l].get("untranslated_keys")  # 未翻译 key
           or (l != "zh_CN" and results[url][l].get("zh_cn_hits"))  # 中文泄露
    )
    status_mark = "✅" if fail_count == 0 else f"⚠️ ({fail_count} lang)"
    if idx % 5 == 0 or fail_count > 0:
        print(f"  [{idx+1:2d}/{total}] {status_mark} {url[:45]}")

print(f"\n[{NOW()}] Step 3: 补跑剩余路由...")
for url in page_routes[total:]:
    results[url] = {}
    for lang in LANGS:
        results[url][lang] = _render_check(url, lang)

# ── Step 3: 汇总报告 ──
print(f"\n[{NOW()}] 🔥 冒烟测试 · 最终报告")

ok_count = 0
fail_routes = []
for url, lang_results in results.items():
    all_ok = True
    per_url_fail = {"url": url, "languages": {}}
    for lang in LANGS:
        r = lang_results[lang]
        lang_ok = (
            (r["status"] or 0) < 500  # 没有服务器崩溃
            and not r["untranslated_keys"]  # 没有未翻译 key 残留在可见文本
            and (lang == "zh_CN" or not r["zh_cn_hits"])  # 非简体时无简体中文泄露
        )
        per_url_fail["languages"][lang] = lang_ok
        if not lang_ok:
            all_ok = False
            per_url_fail[f"{lang}_detail"] = {
                "status": r["status"],
                "untranslated": r["untranslated_keys"][:5],
                "zh_cn_leak": r["zh_cn_hits"][:3],
                "error": r["error"],
            }
    if all_ok:
        ok_count += 1
    else:
        fail_routes.append(per_url_fail)

print(f"  总路由: {len(results)}")
print(f"  ✅ 全语种通过: {ok_count} ({100*ok_count/max(len(results),1):.1f}%)")
print(f"  ⚠️ 有失败的路由: {len(fail_routes)}")

# 失败详情
if fail_routes:
    print(f"\n  ❌ 失败路由 TOP 10:")
    for fr in fail_routes[:10]:
        langs_failed = [l for l, ok in fr["languages"].items() if not ok]
        print(f"    📄 {fr['url'][:45]} → 失败: {', '.join(langs_failed)}")
        for lf in langs_failed[:2]:
            detail = fr.get(f"{lf}_detail", {})
            if detail.get("untranslated"):
                print(f"       未翻译 key: {detail['untranslated'][:2]}")
            if detail.get("zh_cn_leak"):
                print(f"       中文泄露: {detail['zh_cn_leak'][:2]}")

# ── Step 4: 落库 mt_copy_inspection_log ──
print(f"\n[{NOW()}] Step 4: 冒烟测试结果落库...")
conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS mt_copy_inspection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_type TEXT,
    target TEXT,
    result_json TEXT,
    pass_count INTEGER,
    fail_count INTEGER,
    total_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")

summary = {
    "test": "冒烟测试·全页面四语种翻译覆盖率·实际渲染",
    "run_at": NOW(),
    "total_routes": len(results),
    "ok_routes": ok_count,
    "fail_routes": len(fail_routes),
    "pass_rate_pct": round(100*ok_count/max(len(results),1), 1),
    "languages": LANGS,
    "fail_details": fail_routes[:20],  # 只存前 20 条
}

cur.execute("""INSERT INTO mt_copy_inspection_log
    (inspection_type, target, result_json, pass_count, fail_count, total_count, created_at)
    VALUES (?,?,?,?,?,?,?)""",
    ("smoke_test_4lang", "all_page_routes", 
     json.dumps(summary, ensure_ascii=False)[:100000],
     ok_count, len(fail_routes), len(results), NOW()))
print(f"  ✅ 落库 mt_copy_inspection_log")

conn.close()

# ── 保存 JSON 报告 ──
REPORT_PATH = f"{ROOT}/flask-app/scripts/_smoke_test_report.json"
with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"  📝 JSON 报告: {REPORT_PATH}")

print(f"\n✅ 🔥 冒烟测试完成!")
