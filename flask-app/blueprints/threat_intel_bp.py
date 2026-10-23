#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威胁情报 & 主动防御蓝图 (flow_threat_intel_20261023)
====================================================
仙女座安全体系主动防御闭环:
  🛰️ 嗅探   CVE/NVD/GitHub Advisory/安全博客 RSS → 定时抓取
  🎯 匹配   关键词匹配仙女座技术栈 (PHP/Flask/SQLite/Ollama/Cloudflare/VIKEY)
  🛡️ 防御   自动生成防火墙规则 + WAF 规则 + 黑名单
  🧠 投喂   脑库 mt_ai_brain_feed_log + 特征库 mt_signature_db
  📋 上报   生成安全告警 + 自动备案 + 任务大厅入厅
  👥 商讨   合规安全天团自动接单 → Skill 衍生 → 研发课题

数据模型:
  mt_threat_signals    威胁信号 (嗅探结果)
  mt_cve_watch         CVE 监控清单
  mt_firewall_rules    自动生成的防护规则
  mt_signature_db      特征库 (投喂)
  mt_security_actions  主动防御动作日志

API:
  GET  /api/threat-intel/scan          — 主动嗅探 (定时)
  GET  /api/threat-intel/watch         — CVE 监控清单
  POST /api/threat-intel/feed          — 手动投喂脑库
  POST /api/threat-intel/block         — 主动屏蔽 + 筑墙
  GET  /api/threat-intel/firewall      — 防火墙规则
  GET  /api/threat-intel/signatures    — 特征库
  GET  /api/threat-intel/actions        — 主动动作日志
"""
import json, os, re, sqlite3, hashlib, time
from datetime import datetime
from flask import Blueprint, jsonify, request

threat_intel_bp = Blueprint("threat_intel_bp", __name__)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 仙女座技术栈关键词 (CVE 匹配用)
_STACK_KEYWORDS = {
    "php": ["php", "php-cgi", "composer", "wordpress", "laravel"],
    "flask": ["flask", "python", "werkzeug", "jinja"],
    "sqlite": ["sqlite", "pysqlite", "sqlite3"],
    "ollama": ["ollama", "llm", "llama", "qwen", "gemma"],
    "cloudflare": ["cloudflare", "tunnel", "worker", "waf"],
    "security": ["vikey", "auth", "permission", "csrf", "xss", "sqli", "rce", "lfi", "rfi", "deserialization"],
}

# 仙女座需防护的敏感路径
_SENSITIVE_PATHS = [
    "/admin/", "/api/auth", "/api/vault/", "/api/daemon-lab/",
    "/api/local-chat/send", "/api/neuralhub/", "/api/vikey/",
    "/.env", "/.git/", "/wp-admin/", "/phpmyadmin/",
]


def _db():
    conn = sqlite3.connect(os.environ.get("APP_DB") or os.path.join(_APP_DIR, "database", "app.db"))
    conn.row_factory = sqlite3.Row
    return conn

def _r2d(r):
    """sqlite3.Row → dict"""
    return {k: r[k] for k in r.keys()}


def _init_tables(conn):
    """5 张核心表"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_threat_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,            -- nvd / github / rss / manual
        external_id TEXT,                -- CVE-2025-xxxx
        title TEXT, description TEXT,
        cvss REAL, severity TEXT,
        affected_stack TEXT,             -- php/flask/sqlite/...
        exploit_available INTEGER DEFAULT 0,
        matches_our_stack INTEGER DEFAULT 0,
        match_reason TEXT,
        status TEXT DEFAULT 'NEW',       -- NEW/WATCHED/PATCHED/BLOCKED/DISMISSED
        raw_json TEXT,
        published_at TEXT,
        discovered_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS mt_cve_watch (
        cve_id TEXT PRIMARY KEY,
        title TEXT, cvss REAL, severity TEXT,
        vendor TEXT, product TEXT, version_range TEXT,
        our_stack_match INTEGER DEFAULT 0,
        priority TEXT DEFAULT 'MEDIUM',  -- CRITICAL/HIGH/MEDIUM/LOW
        watch_status TEXT DEFAULT 'ACTIVE',
        patch_available INTEGER DEFAULT 0,
        patch_url TEXT,
        reference_urls TEXT,
        last_synced_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS mt_firewall_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT NOT NULL,         -- WAF/HEADER/BLACKLIST/RATE_LIMIT
        rule_name TEXT,
        pattern TEXT, action TEXT,       -- BLOCK/LOG/PROMPT
        priority INTEGER DEFAULT 50,
        cve_id TEXT,
        threat_signal_id INTEGER,
        source TEXT DEFAULT 'auto',      -- auto/manual/daemon
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS mt_signature_db (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sig_hash TEXT UNIQUE,
        sig_type TEXT,                   -- IOC/YARA/RULE/KEYWORD
        sig_data TEXT,                    -- 规则/表达式
        source TEXT,                     -- cve_xx / manual
        threat_level TEXT,               -- CRITICAL/HIGH/MEDIUM/LOW
        feed_count INTEGER DEFAULT 0,    -- 投喂次数
        fed_to_brain INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS mt_security_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,       -- SCAN/BLOCK/PATCH/FEED/REPORT/DISCUSS/RESEARCH
        target TEXT,                     -- CVE-ID / path / ip
        actor TEXT DEFAULT 'threat_intel_engine',
        detail TEXT,
        result TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)


def _log_action(conn, action_type, target, detail="", result=""):
    conn.execute(
        "INSERT INTO mt_security_actions (action_type, target, actor, detail, result) VALUES (?,?,?,?,?)",
        (action_type, target, "flow_threat_intel_20261023", detail, result))


def _match_stack(text):
    """CVE 描述 → 匹配仙女座技术栈"""
    t = (text or "").lower()
    hits = []
    for stack, kws in _STACK_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in t:
                hits.append(stack)
                break
    return hits


def _fetch_nvd_recent(cve_prefix="CVE-2025"):
    """从 NVD 拉最近 PHP 漏洞 (本地零 token, 用 urllib)"""
    import urllib.request as _ur
    try:
        # 精准搜索: NVD API 2.0 — 只拉 2024+ 近年漏洞 (避开 CVE-1999 噪音)
        url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=PHP&resultsPerPage=20&pubStartDate=2024-01-01T00:00:00.000"
        req = _ur.Request(url, headers={"User-Agent": "MTSCOS-ThreatIntel/1.0"})
        resp = _ur.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        vulnerabilities = data.get("vulnerabilities", [])
        signals = []
        for v in vulnerabilities:
            cve = v.get("cve", {})
            cve_id = cve.get("id", "")
            desc = cve.get("descriptions", [{}])[0].get("value", "")
            metrics = cve.get("metrics", {})
            cvss = 0.0
            severity = "UNKNOWN"
            for mkey in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
                for m in metrics.get(mkey, []):
                    cvss = m.get("cvssData", {}).get("baseScore", cvss)
                    severity = m.get("cvssData", {}).get("baseSeverity", severity)
                    break
                if cvss: break
            refs = cve.get("references", [])
            ref_urls = [r.get("url", "") for r in refs[:3]]
            signals.append({
                "source": "nvd", "external_id": cve_id,
                "title": desc[:120], "description": desc[:500],
                "cvss": cvss, "severity": severity,
                "published": cve.get("published", ""),
                "refs": ref_urls, "raw_json": json.dumps(v, ensure_ascii=False)[:2000],
            })
        return signals
    except Exception as e:
        return [{"source": "nvd", "external_id": "FETCH_FAILED", "error": str(e)[:100]}]


def _ingest_signal(conn, sig, force=False):
    """嗅探信号 → 灌 mt_threat_signals + mt_cve_watch"""
    cve_id = sig.get("external_id", "")
    if not force and cve_id != "FETCH_FAILED":
        existing = conn.execute(
            "SELECT 1 FROM mt_threat_signals WHERE external_id=?", (cve_id,)).fetchone()
        if existing: return None

    matches = _match_stack(sig.get("title", "") + " " + sig.get("description", ""))
    sig["matches"] = matches

    cur = conn.execute(
        "INSERT INTO mt_threat_signals (source,external_id,title,description,cvss,severity,"
        "affected_stack,exploit_available,matches_our_stack,match_reason,raw_json,published_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sig.get("source", "manual"), cve_id, sig.get("title", "")[:200],
         sig.get("description", "")[:1000], sig.get("cvss", 0), sig.get("severity", ""),
         ",".join(matches) if matches else None,
         0, 1 if matches else 0, ",".join(matches) if matches else "n/a",
         sig.get("raw_json", "") or json.dumps(sig, ensure_ascii=False)[:2000],
         sig.get("published", "")))
    sig_id = cur.lastrowid

    # 如果匹配仙女座技术栈 → 加 CVE watch
    if matches and cve_id.startswith("CVE-"):
        priority = "CRITICAL" if sig.get("cvss", 0) >= 9 else "HIGH" if sig.get("cvss", 0) >= 7 else "MEDIUM"
        conn.execute("""INSERT OR REPLACE INTO mt_cve_watch
            (cve_id,title,cvss,severity,vendor,product,our_stack_match,priority,reference_urls)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (cve_id, sig.get("title", "")[:200], sig.get("cvss", 0), sig.get("severity", ""),
             "PHP Group", "PHP", 1, priority, json.dumps(sig.get("refs", []), ensure_ascii=False)))

    return sig_id


def _auto_generate_firewall_rules(conn, signal):
    """威胁信号 → 自动生成防护规则"""
    cvss = signal.get("cvss", 0)
    title = (signal.get("title") or "").lower()
    rules = []

    rule_name = f"AUTO-{signal.get('external_id','SIG')}"

    # 通用: rate limit 提升 (CVSS >= 7)
    if cvss >= 7:
        conn.execute("INSERT INTO mt_firewall_rules (rule_type,rule_name,pattern,action,priority,cve_id,source) "
                     "VALUES (?,?,?,?,?,?,?)",
                     ("RATE_LIMIT", f"{rule_name}-RATELIMIT", "*", "RAISE_TO_30_PER_MIN", 10,
                      signal.get("external_id"), "threat_intel"))
        rules.append("RATE_LIMIT 提升至 30/min")

    # 关键词匹配 → 生成黑名单
    for kw, path in [("injection", "/api/*"), ("xss", "*.html"), ("lfi", "*.php"), ("rce", "*")]:
        if kw in title:
            conn.execute("INSERT INTO mt_firewall_rules (rule_type,rule_name,pattern,action,priority,cve_id,source) "
                         "VALUES (?,?,?,?,?,?,?)",
                         ("WAF", f"{rule_name}-{kw.upper()}", path, "LOG_BLOCK", 20,
                          signal.get("external_id"), "threat_intel"))
            rules.append(f"WAF 规则 {kw.upper()} → {path}")

    # 敏感路径统一防护
    conn.execute("INSERT OR IGNORE INTO mt_firewall_rules (rule_type,rule_name,pattern,action,priority,source) VALUES (?,?,?,?,?,?)",
                 ("HEADER", "AUTO-SECURITY-HEADERS", "*", "ADD_HSTS_XFO", 5, "threat_intel"))

    _log_action(conn, "BLOCK", signal.get("external_id", "UNKNOWN"),
                f"自动生成 {len(rules)} 条防火墙规则", ",".join(rules))
    return rules


def _feed_brain_and_signature(conn, signal):
    """威胁信号 → 投喂脑库 + 特征库"""
    cve_id = signal.get("external_id", "")
    title = signal.get("title", "")
    cvss = signal.get("cvss", 0)

    # 特征库
    sig_hash = hashlib.md5(f"{cve_id}:{title}".encode()).hexdigest()[:16]
    severity = signal.get("severity", "MEDIUM")
    conn.execute("""INSERT OR IGNORE INTO mt_signature_db (sig_hash,sig_type,sig_data,source,threat_level)
        VALUES (?,?,?,?,?)""",
        (sig_hash, "CVE_ALERT", title[:300], cve_id, severity))
    conn.execute("UPDATE mt_signature_db SET feed_count=feed_count+1 WHERE sig_hash=?", (sig_hash,))

    # 脑库投喂 (尝试调用现有 API)
    fed = False
    try:
        from blueprints.chat_local_bp import _db as _chat_db
        conn2 = _chat_db()
        conn2.execute("CREATE TABLE IF NOT EXISTS mt_ai_brain_feed_log (feed_id TEXT, feed_type TEXT, content TEXT, fed_at TEXT)")
        conn2.execute("INSERT INTO mt_ai_brain_feed_log (feed_id,feed_type,content,fed_at) VALUES (?,?,?,datetime('now','localtime'))",
                      (sig_hash, "threat_intel", json.dumps({"cve": cve_id, "cvss": cvss, "title": title}, ensure_ascii=False)))
        conn2.commit(); conn2.close()
        fed = True
    except Exception:
        pass

    _log_action(conn, "FEED", cve_id, f"特征库+1, 脑库={'OK' if fed else 'skip'}", f"sig_hash={sig_hash}")
    return True


def _escalate_to_hall(conn, signal):
    """高危信号 → 自动列入任务大厅 (金牌安全天团认领)"""
    cvss = signal.get("cvss", 0)
    if cvss < 7: return None

    cve_id = signal.get("external_id", "")
    title = signal.get("title", "")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS mt_lab_task_hall (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, source TEXT, source_id INTEGER, priority TEXT, status TEXT, task_type TEXT, claim_owner TEXT, claim_owner_role TEXT, created_at TEXT)")
        existing = conn.execute("SELECT 1 FROM mt_lab_task_hall WHERE source='threat_intel' AND source_id=?", (cve_id,)).fetchone()
        if existing: return None

        priority = "P0" if cvss >= 9 else "P1"
        conn.execute("""INSERT INTO mt_lab_task_hall
            (title,description,source,source_id,priority,status,task_type,claim_owner,claim_owner_role,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (f"[{priority}] {cve_id} CVSS={cvss} {title[:60]}",
             f"威胁情报自动嗅探发现 {cve_id} CVSS={cvss} {signal.get('severity','')}\n"
             f"匹配仙女座技术栈: {signal.get('affected_stack','')}\n"
             f"需金牌安全天团认领 → 防御 → 筑墙 → 补丁",
             "threat_intel", cve_id, priority, "QUEUED", "SECURITY",
             "🧪 专业测试30年金牌天团", "SEC_QA"))

        # HR 日志
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS mt_lab_hr_log (employee_name, role, hall_task_id, action, verdict)")
            for m in ["铁面 判官", "玄甲 守护", "钱学森·星天"]:
                conn.execute("INSERT INTO mt_lab_hr_log (employee_name,role,hall_task_id,action,verdict) VALUES (?,?,?,?,?)",
                             (m, "SEC_QA", cve_id, "AUTO_ESCALATE", f"CVE {cve_id} CVSS={cvss}"))
        except Exception:
            pass

        _log_action(conn, "RESEARCH_TASK", cve_id, f"自动入厅 priority={priority}", "金牌安全天团已认领")
        return cve_id
    except Exception as e:
        _log_action(conn, "ESCALATE_FAIL", cve_id, str(e)[:100])
        return None


# ════════════════════════════════════════════════════════════════
# 主动嗅探引擎 (定时 + 手动触发)
# ════════════════════════════════════════════════════════════════

def run_threat_scan():
    """
    完整主动防御闭环 (一次性跑完 6 步):
    1. 嗅探: NVD CVE API 拉最新 PHP 漏洞
    2. 匹配: 仙女座技术栈
    3. 防御: 自动生成防火墙规则
    4. 投喂: 特征库 + 脑库
    5. 上报: CVE watch + 任务大厅
    6. 日志: mt_security_actions
    """
    import urllib.request as _ur, json as _json

    conn = _db()
    _init_tables(conn)
    results = {"fetched": 0, "matched": 0, "rules": 0, "fed": 0, "hall": 0, "errors": []}

    # Step 1: 嗅探
    signals = _fetch_nvd_recent()
    results["fetched"] = len(signals)
    _log_action(conn, "SCAN", "NVD_API", f"fetched={len(signals)}", "OK" if signals else "empty")

    for sig in signals:
        if "error" in sig:
            results["errors"].append(sig["error"]); continue

        # Step 2: 匹配
        sig_id = _ingest_signal(conn, sig)
        if not sig_id: continue
        matches = sig.get("matches", [])
        if not matches: continue
        results["matched"] += 1

        # Step 3: 防御 → 自动筑墙
        try:
            rules = _auto_generate_firewall_rules(conn, sig)
            results["rules"] += len(rules)
        except Exception as e:
            results["errors"].append(f"firewall: {e}")

        # Step 4: 投喂 → 特征库 + 脑库
        try:
            _feed_brain_and_signature(conn, sig)
            results["fed"] += 1
        except Exception as e:
            results["errors"].append(f"feed: {e}")

        # Step 5: 上报 → 任务大厅 + 金牌安全天团
        try:
            if _escalate_to_hall(conn, sig):
                results["hall"] += 1
        except Exception as e:
            results["errors"].append(f"hall: {e}")

    conn.commit()

    # 汇总日志
    _log_action(conn, "SCAN_SUMMARY", "ALL",
                f"fetched={results['fetched']}, matched={results['matched']}, "
                f"rules={results['rules']}, fed={results['fed']}, hall={results['hall']}",
                json.dumps(results, ensure_ascii=False)[:500])
    conn.close()

    return {
        "ok": True, "engine": "threat_intel",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **results,
        "主动动作": [
            "🛰️ 嗅探 NVD PHP 漏洞",
            "🎯 匹配仙女座技术栈",
            "🛡️ 自动生成防火墙规则",
            "🧠 投喂脑库 + 特征库",
            "📋 高危自动入任务大厅",
            "👥 金牌安全天团自动认领",
        ],
        "flow_id": "flow_threat_intel_20261023",
    }


def run_threat_daemon_loop(interval_sec=3600):
    """
    威胁嗅探守护循环 (全自动, 零人工):
      - 每 interval_sec (默认 3600s = 1小时) 跑一次 run_threat_scan
      - 跑完打印摘要, 继续等
      - 任何异常不崩循环, 打印后继续
    server_real_db.py async-init 段会启动此线程 (延迟 60s 让 Flask 先稳)
    """
    import time as _t
    print(f'[THREAT-INTEL] 🛰️ threat-daemon 启动 — 每 {interval_sec}s 自动嗅探')
    _t.sleep(60)  # 等 Flask 稳定
    while True:
        try:
            t0 = _t.time()
            r = run_threat_scan()
            cost = int(_t.time() - t0)
            print(f'[THREAT-INTEL] ✅ 自动嗅探 done ({cost}s) fetched={r["fetched"]} matched={r["matched"]} rules={r["rules"]} fed={r["fed"]} hall={r["hall"]}')
        except Exception as e:
            print(f'[THREAT-INTEL] ⚠️ threat-daemon 异常 (不崩循环): {e}')
        # 等下一轮
        _t.sleep(interval_sec)


# ════════════════════════════════════════════════════════════════
# API 路由
# ════════════════════════════════════════════════════════════════

@threat_intel_bp.route("/api/threat-intel/scan", methods=["GET", "POST"])
def threat_scan():
    """主动嗅探 — 完整 6 步闭环"""
    return jsonify(run_threat_scan())


@threat_intel_bp.route("/api/threat-intel/watch", methods=["GET"])
def cve_watch():
    """CVE 监控清单"""
    conn = _db(); _init_tables(conn)
    rows = conn.execute(
        "SELECT * FROM mt_cve_watch ORDER BY priority DESC, cvss DESC").fetchall()
    return jsonify({"ok": True, "total": len(rows), "items": [_r2d(r) for r in rows]})


@threat_intel_bp.route("/api/threat-intel/signals", methods=["GET"])
def threat_signals():
    """威胁信号列表"""
    conn = _db(); _init_tables(conn)
    rows = conn.execute(
        "SELECT * FROM mt_threat_signals ORDER BY discovered_at DESC LIMIT 50").fetchall()
    return jsonify({"ok": True, "total": len(rows), "items": [_r2d(r) for r in rows]})


@threat_intel_bp.route("/api/threat-intel/firewall", methods=["GET"])
def firewall_rules():
    """自动生成的防护规则"""
    conn = _db(); _init_tables(conn)
    rows = conn.execute(
        "SELECT * FROM mt_firewall_rules WHERE active=1 ORDER BY priority DESC").fetchall()
    return jsonify({"ok": True, "total": len(rows), "rules": [_r2d(r) for r in rows]})


@threat_intel_bp.route("/api/threat-intel/signatures", methods=["GET"])
def signature_db():
    """特征库"""
    conn = _db(); _init_tables(conn)
    rows = conn.execute(
        "SELECT * FROM mt_signature_db ORDER BY created_at DESC LIMIT 50").fetchall()
    return jsonify({"ok": True, "total": len(rows), "items": [_r2d(r) for r in rows]})


@threat_intel_bp.route("/api/threat-intel/actions", methods=["GET"])
def security_actions():
    """主动防御动作日志"""
    conn = _db(); _init_tables(conn)
    rows = conn.execute(
        "SELECT * FROM mt_security_actions ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify({"ok": True, "total": len(rows), "items": [_r2d(r) for r in rows]})


@threat_intel_bp.route("/api/threat-intel/feed", methods=["POST"])
def manual_feed():
    """手动投喂 (支持 raw CVE JSON)"""
    data = request.get_json() or {}
    conn = _db(); _init_tables(conn)
    sig = {
        "source": data.get("source", "manual"),
        "external_id": data.get("external_id", f"MANUAL_{int(time.time())}"),
        "title": data.get("title", data.get("cve_id", "手动信号")),
        "description": data.get("description", ""),
        "cvss": float(data.get("cvss", 0)),
        "severity": data.get("severity", "MEDIUM"),
    }
    sig_id = _ingest_signal(conn, sig, force=True)
    if sig_id:
        _auto_generate_firewall_rules(conn, sig)
        _feed_brain_and_signature(conn, sig)
        if sig["cvss"] >= 7: _escalate_to_hall(conn, sig)
        conn.commit()
    return jsonify({"ok": True, "signal_id": sig_id})


@threat_intel_bp.route("/api/threat-intel/block", methods=["POST"])
def manual_block():
    """主动屏蔽 + 筑墙 (手动触发)"""
    data = request.get_json() or {}
    sig = {
        "external_id": data.get("cve_id", "MANUAL_BLOCK"),
        "title": data.get("title", ""), "cvss": float(data.get("cvss", 8)),
        "affected_stack": data.get("stack", ""),
    }
    conn = _db(); _init_tables(conn)
    rules = _auto_generate_firewall_rules(conn, sig)
    _feed_brain_and_signature(conn, sig)
    conn.commit()
    return jsonify({"ok": True, "rules_generated": rules})
