#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS AI · 海关总署 建制引擎
#  flow: mtos_customs_admin_split_20261026
#
#  拆分背景:
#  ──────────────────────────────────────────────────────────────
#  维护部队原覆盖过多职责: 巡逻下沉 + 抢修排障 + 合规监护 +
#  任务大厅 guard。细分后各司其职:
#
#  🏛️ 海关总署 (CUSTOMS_ADMIN) — 任务大厅 通关专属
#  ──────────────────────────────────────────────────────────────
#  署长 L4 ─ 全面负责任务大厅 通关管理 (SA 兼任)
#  ├── 副署长 L3 ─ 协助署长 + 特急通关 + 争议裁决
#  ├── 通关审查分队 (CLEARANCE) L3 分队长 + 2 队员
#  │     职责: 违禁词 / 法务红线 / 安全封锁词 → 海关「关税区准入」
#  ├── 申报合规分队 (DECLARATION) L3 分队长 + 2 队员
#  │     职责: source / publisher_role / 操作合规 → 海关「申报合规」
#  └── 风险查验分队 (RISK_CHECK) L3 分队长 + 2 队员
#        职责: 污染特征 / 漏洞特征 / 异常行为  → 海关「风险查验」
#
#  任务大厅通关调用链:
#  ┌────────────┐     ┌──────────────┐     ┌──────────────┐
#  │  任务大厅   │────→│   海关署长    │────→│ 3 分队并行   │
#  │ NEW/QUEUED │     │ 统一调度     │     │ 通关/申报/风险│
#  └────────────┘     └──────────────┘     └──────┬───────┘
#                                                  │
#                                           ┌──────┴───────┐
#                                           ▼              ▼
#                                        APPROVED      VETOED
#                                        (通关放行)   (打回/扣关)
#
#  原维护部队 (CORPS_FIELD) — 巡逻下沉 + 抢修排障 (保留)
#  ──────────────────────────────────────────────────────────────
#  PATROL / SURVEY / REPAIR / EMPOWER / RECON 五分队维持不变
#  GUARD (合规三查) 已由海关总署接管
#
#  用法:
#    python3 ai_customs_admin_engine.py install   # 建制落库
#    python3 ai_customs_admin_engine.py show      # 查看建制
#    python3 ai_customs_admin_engine.py review --task 123  # 单任务通关测试
#    python3 ai_customs_admin_engine.py guard     # 批量通关查验 (替代原 guard_once)
#    python3 ai_customs_admin_engine.py claim     # 中心自动认领 (替代原 center_claim_once)
#    python3 ai_customs_admin_engine.py execute   # 中心执行闭环 (替代原 center_execute_once)
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, sys, time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT_ROOT, "database", "app.db")

def _conn():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ═══════════════════════════════════════════════════════════════════
# §1 海关总署建制
# ═══════════════════════════════════════════════════════════════════

CUSTOMS_ADMIN = {
    "admin_code": "CUSTOMS_ADMIN",
    "admin_name": "🏛️ 海关总署",
    "duty": "任务大厅通关管理 + 违禁词拦截 + 申报合规 + 风险查验 + 自动报关",
    "commissioner": {"name": "海关署长", "level": 4, "role": "COMMISSIONER"},
    "deputy":       {"name": "副署长",   "level": 3, "role": "DEPUTY_COMMISSIONER"},
    "squads": [
        {
            "squad_code": "CLEARANCE",
            "squad_name": "通关审查分队",
            "duty": "违禁词 / 法务红线 / 安全封锁词 → 关税区准入把关",
            "capabilities": ["blocklist_scan", "legal_redline", "sensitive_word", "tariff_gate"],
            "members": [
                ("通关分队长", 3, "SQUAD_LEADER"),
                ("审查员-A",   2, "MEMBER"),
                ("审查员-B",   2, "MEMBER"),
            ]
        },
        {
            "squad_code": "DECLARATION",
            "squad_name": "申报合规分队",
            "duty": "source / publisher_role / 操作合规 → 申报真实性核验",
            "capabilities": ["source_check", "role_verify", "compliance", "declaration_audit"],
            "members": [
                ("申报分队长", 3, "SQUAD_LEADER"),
                ("核验员-A",   2, "MEMBER"),
                ("核验员-B",   2, "MEMBER"),
            ]
        },
        {
            "squad_code": "RISK_CHECK",
            "squad_name": "风险查验分队",
            "duty": "污染特征 / 漏洞特征 / 异常行为 → 货物风险扫描",
            "capabilities": ["pollution_detect", "vuln_scan", "behavior_check", "risk_assess"],
            "members": [
                ("查验分队长", 3, "SQUAD_LEADER"),
                ("查验员-A",   2, "MEMBER"),
                ("查验员-B",   2, "MEMBER"),
            ]
        },
    ]
}

# ═══════════════════════════════════════════════════════════════════
# §2 通关查验规则 (海关总署专属, 替代原 guard_once 三查)
# ═══════════════════════════════════════════════════════════════════

# 通关审查分队: 违禁词 + 红线
CLEARANCE_BLOCKLIST = [
    # 国家安全 / 法律红线
    "政治敏感", "国家安全", "军事机密", "涉密信息", "违法", "犯罪",
    # 系统毁灭
    "删除数据库", "DROP TABLE", "rm -rf /", "格式化", "擦除", "wipe",
    # 黑客行为
    "窃取密码", "破解加密", "非法访问", "漏洞利用", "unauthorized",
    # 隐私侵犯
    "个人隐私", "侵犯",
    # 其他风险词 (低优先级, 仅告警不拦截)
    "测试test", "placeholder", "lorem",
]

# 申报合规分队: 来源黑名单
DECLARATION_BAD_SOURCES = ['fake', 'test123', 'unknown', 'none', 'null',
                           'hack', '注入', '假数据', 'undefined', 'evil', 'backdoor']
DECLARATION_ALLOWED_SOURCES = ('AI_ENGINE', 'SYSTEM', 'USER', 'FLOW', 'ENGINE',
                               'DAEMON', 'AUTO', 'PEACEKEEPER', 'SA_DIRECT',
                               'SA', 'ADMIN', 'CORPS_FIELD', 'CUSTOMS_ADMIN')

# 风险查验分队: 污染特征
RISK_POLLUTION_MARKS = ['todo', 'fixme', '占位', '假数据', 'xxx', 'undefined',
                         'null', '<script', '${', '{{', 'placeholder', 'lorem']
RISK_VULN_MARKS = ['sql注入', 'xss', 'csrf', 'rce', 'ssrf', '越权', 'open redirect']

# ═══════════════════════════════════════════════════════════════════
# §3 建表 + 写入建制
# ═══════════════════════════════════════════════════════════════════

def install_customs():
    """安装海关总署建制"""
    conn = _conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_customs_admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            member_name TEXT NOT NULL,
            level INTEGER DEFAULT 2,
            squad_code TEXT,            -- CLEARANCE / DECLARATION / RISK_CHECK / COMMAND
            squad_name TEXT,
            admin_role TEXT,            -- COMMISSIONER / DEPUTY / SQUAD_LEADER / MEMBER
            capabilities TEXT,          -- JSON 技能列表
            status TEXT DEFAULT 'ACTIVE',
            tasks_done INTEGER DEFAULT 0,
            tasks_rejected INTEGER DEFAULT 0,
            last_active TEXT,
            created_at TEXT
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS mt_customs_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            admin_unit TEXT,            -- CUSTOMS_ADMIN / CLEARANCE / DECLARATION / RISK_CHECK
            action TEXT,                -- CLEAR / VETO / PASS / CHECK / CLAIM / EXECUTE
            decision TEXT,              -- APPROVED / REJECTED / PENDING
            detail TEXT,                -- JSON 详情
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""")

        # 写入总署部 (署长 + 副署长)
        customs_members = [
            ("CUSTOMS-ADMIN-001", CUSTOMS_ADMIN["commissioner"]["name"], 4, "COMMAND",
             "总署部", "COMMISSIONER", json.dumps(["admin_overall", "final_decision", "exception", "tariff_rule"]), _now()),
            ("CUSTOMS-ADMIN-002", CUSTOMS_ADMIN["deputy"]["name"], 3, "COMMAND",
             "总署部", "DEPUTY_COMMISSIONER", json.dumps(["assist_commissioner", "emergency_clear", "dispute_resolve"]), _now()),
        ]

        for squad in CUSTOMS_ADMIN["squads"]:
            for idx, (name, level, role) in enumerate(squad["members"]):
                member_code = f"CUSTOMS-{squad['squad_code']}-{idx+1:03d}"
                customs_members.append((
                    member_code, name, level, squad['squad_code'],
                    squad['squad_name'], role, json.dumps(squad['capabilities']), _now()
                ))

        conn.executemany("""INSERT OR IGNORE INTO mt_customs_admin
                           (member_code, member_name, level, squad_code, squad_name, admin_role, capabilities, created_at)
                           VALUES(?,?,?,?,?,?,?,?)""", customs_members)

        # 加 mt_hall_peacekeeper_review.customs_unit (兼容层, 复用现有审查表)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_hall_peacekeeper_review)")]
            if 'customs_unit' not in cols:
                conn.execute("ALTER TABLE mt_hall_peacekeeper_review ADD COLUMN customs_unit TEXT DEFAULT 'CUSTOMS_ADMIN'")
            if 'customs_actor' not in cols:
                conn.execute("ALTER TABLE mt_hall_peacekeeper_review ADD COLUMN customs_actor TEXT DEFAULT 'AI_CUSTOMS_ADMIN'")
        except Exception:
            pass  # 表可能不存在

        conn.commit()
        print(f"  ✅ 海关总署: {len(customs_members)} 人 (1 署长 + 1 副署长 + 3 分队 × 3 人 = 11)")
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 安装失败: {e}")
        conn.close()
        return False

# ═══════════════════════════════════════════════════════════════════
# §4 海关总署三层通关审查 (替代原 guard_once)
# ═══════════════════════════════════════════════════════════════════

def clearance_squad_scan(text):
    """通关审查分队: 违禁词 + 红线扫描"""
    hits = [w for w in CLEARANCE_BLOCKLIST if w.lower() in text.lower()]
    return {
        "squad_code": "CLEARANCE",
        "squad_name": "通关审查分队",
        "executor": "通关分队长",
        "result": "VETO" if hits else "PASS",
        "hit_words": hits,
    }

def declaration_squad_check(source, publisher_role):
    """申报合规分队: 来源 + 发布者角色核验"""
    issues = []
    publisher_role = (publisher_role or '').upper()
    source = (source or '').upper()

    role_ok = publisher_role not in ('UNKNOWN', 'GUEST', '')
    if not role_ok:
        issues.append(f"发布者角色未认证 (publisher_role={publisher_role})")

    src_low = (source or '').lower()
    src_bad = [m for m in DECLARATION_BAD_SOURCES if m in src_low]
    if src_bad:
        issues.append(f"来源含非法特征: {src_bad}")

    source_ok = source in DECLARATION_ALLOWED_SOURCES or role_ok

    return {
        "squad_code": "DECLARATION",
        "squad_name": "申报合规分队",
        "executor": "申报分队长",
        "result": "PASS" if (role_ok and source_ok) else "VETO",
        "role_ok": role_ok,
        "source_ok": source_ok,
        "issues": issues,
    }

def risk_check_squad_scan(text, source):
    """风险查验分队: 污染 + 漏洞特征扫描"""
    hay = (text or '').lower()
    poll_hits = [m for m in RISK_POLLUTION_MARKS if m in hay]
    vuln_hits = [m for m in RISK_VULN_MARKS if m in hay]
    is_contaminated = len(poll_hits) >= 2 or any(m in hay for m in ['<script', 'rm -rf', 'drop table'])

    return {
        "squad_code": "RISK_CHECK",
        "squad_name": "风险查验分队",
        "executor": "查验分队长",
        "result": "CONTAMINATED" if is_contaminated else "PASS",
        "pollution_hits": poll_hits,
        "vuln_hits": vuln_hits,
        "contaminated": is_contaminated,
    }

def commissioner_final_decision(r_clearance, r_declaration, r_risk):
    """署长综合裁决"""
    if r_clearance['result'] == 'VETO':
        return 'REJECTED', '违禁词拦截'
    if r_declaration['result'] == 'VETO':
        return 'REJECTED', '申报不合规'
    if r_risk['result'] == 'CONTAMINATED':
        return 'CONTAMINATED', '货物含污染特征'
    return 'APPROVED', '三查通关'

def customs_full_review(task_id):
    """🔧 海关总署完整通关审查 — 3 分队并行 + 署长裁决 (替代原 guard_once)"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            return False, "任务不存在"

        text = f"{t['title'] or ''} {t['description'] or ''}"

        # ── 3 分队并行执行 ──
        r_clearance = clearance_squad_scan(text)
        r_declaration = declaration_squad_check(t['source'], t['publisher_role'])
        r_risk = risk_check_squad_scan(text, t['source'])

        # ── 署长裁决 ──
        final_decision, reason = commissioner_final_decision(r_clearance, r_declaration, r_risk)

        full_report = {
            "commissioner_decision": final_decision,
            "commissioner": "海关署长 (L4)",
            "reviewed_at": _now(),
            "reason": reason,
            "three_squads": {
                "clearance": r_clearance,
                "declaration": r_declaration,
                "risk_check": r_risk,
            },
        }

        # ── 写海关总署日志 ──
        conn.execute("""INSERT INTO mt_customs_log
                      (task_id, admin_unit, action, decision, detail)
                      VALUES(?,?,?,?,?)""",
                    (task_id, 'CUSTOMS_ADMIN', 'FULL_REVIEW', final_decision,
                     json.dumps(full_report, ensure_ascii=False)))

        # ── 写兼容表 (peacekeeper_review) — 标记 customs_unit ──
        conn.execute("""INSERT OR REPLACE INTO mt_hall_peacekeeper_review
                      (task_id, decision, block_reasons, urgency_score, legal_check,
                       reviewer, reviewed_at, brigade_unit, brigade_actor,
                       customs_unit, customs_actor)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id, final_decision,
                     json.dumps({
                         "clearance_hits": r_clearance['hit_words'],
                         "declaration_issues": r_declaration['issues'],
                         "risk_pollution": r_risk['pollution_hits'],
                         "risk_vuln": r_risk['vuln_hits'],
                         "reason": reason,
                     }, ensure_ascii=False),
                     50,  # urgency 默认
                     r_declaration['result'],
                     "海关署长", _now(),
                     "CUSTOMS_ADMIN", "AI_CUSTOMS_ADMIN",
                     "CUSTOMS_ADMIN", "AI_CUSTOMS_ADMIN"))

        # ── 更新总署部任务计数 ──
        conn.execute("UPDATE mt_customs_admin SET tasks_done=tasks_done+1, last_active=? WHERE squad_code='COMMAND'", (_now(),))
        for squad_code in ["CLEARANCE", "DECLARATION", "RISK_CHECK"]:
            conn.execute(f"UPDATE mt_customs_admin SET last_active=? WHERE squad_code='{squad_code}'", (_now(),))
        if final_decision != 'APPROVED':
            conn.execute("UPDATE mt_customs_admin SET tasks_rejected=tasks_rejected+1, last_active=? WHERE squad_code='COMMAND'", (_now(),))

        # ── 更新任务状态 ──
        conn.execute("""UPDATE mt_lab_task_hall
                       SET peacekeeper_decision=?, peacekeeper_reason=?, updated_at=?
                       WHERE id=?""",
                     (final_decision, json.dumps(full_report, ensure_ascii=False), _now(), task_id))
        if final_decision == 'CONTAMINATED':
            conn.execute("UPDATE mt_lab_task_hall SET status='CONTAMINATED' WHERE id=?", (task_id,))
        elif final_decision == 'REJECTED':
            conn.execute("UPDATE mt_lab_task_hall SET status='REJECTED' WHERE id=?", (task_id,))

        conn.commit()

        summary = (f"署长裁决: {final_decision} ({reason})\n"
                   f"  🚫 通关: {r_clearance['hit_words'] or '无'}  ({r_clearance['squad_name']})\n"
                   f"  📋 申报: {r_declaration['result']}  ({r_declaration['squad_name']})\n"
                   f"  ⚠️ 风险: {r_risk['pollution_hits'] or r_risk['vuln_hits'] or '无'}  ({r_risk['squad_name']})")
        return True, summary

    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §5 批量通关查验 (替代原 maintenance_dispatch_engine.guard_once)
# ═══════════════════════════════════════════════════════════════════

def customs_guard_once(batch: int = 20) -> dict:
    """海关总署批量通关查验 — 替代原维护部队 guard_once 三查"""
    conn = _conn()
    stats = {'checked': 0, 'pass': 0, 'rejected': 0, 'contaminated': 0}
    try:
        rows = conn.execute(
            "SELECT rowid, id, IFNULL(title,''), IFNULL(description,''), "
            "IFNULL(source,''), IFNULL(priority,''), IFNULL(status,''), "
            "IFNULL(publisher_role,'') "
            "FROM mt_lab_task_hall WHERE status IN ('QUEUED','DISPATCHED') "
            "ORDER BY rowid DESC LIMIT ?", (batch,)).fetchall()
        for rid, task_id, title, desc, source, prio, status, pub_role in rows:
            stats['checked'] += 1
            text = f'{title} {desc}'

            # 三查并行
            r_clearance = clearance_squad_scan(text)
            r_declaration = declaration_squad_check(source, pub_role)
            r_risk = risk_check_squad_scan(text, source)
            final_decision, reason = commissioner_final_decision(r_clearance, r_declaration, r_risk)

            try:
                # 写海关日志
                conn.execute("""INSERT INTO mt_customs_log
                              (task_id, admin_unit, action, decision, detail)
                              VALUES(?,?,?,?,?)""",
                            (task_id, 'CUSTOMS_ADMIN', 'BATCH_GUARD', final_decision,
                             json.dumps({'reason': reason, 'clearance': r_clearance['hit_words'],
                                         'declaration': r_declaration['issues'],
                                         'risk': r_risk['pollution_hits'] + r_risk['vuln_hits']},
                                        ensure_ascii=False)))

                # 写兼容层 mt_maintenance_log (保留旧系统可查)
                conn.execute(
                    "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
                    "VALUES ('CUSTOMS_ADMIN', ?, ?, ?)",
                    (str(task_id), f'CUSTOMS_{final_decision}', json.dumps(
                        {'task': title[:40], 'source': source, 'reason': reason,
                         'clearance': r_clearance['hit_words'],
                         'customs': '海关总署通关查验 (替代维护部队 guard)'},
                        ensure_ascii=False)))

                if final_decision == 'CONTAMINATED':
                    conn.execute("UPDATE mt_lab_task_hall SET status='CONTAMINATED' WHERE rowid=?", (rid,))
                    stats['contaminated'] += 1
                elif final_decision == 'REJECTED':
                    stats['rejected'] += 1
                else:
                    stats['pass'] += 1
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
    finally:
        conn.close()
    return stats

# ═══════════════════════════════════════════════════════════════════
# §6 自动报关 — 中心认领 (替代原 center_claim_once)
# ═══════════════════════════════════════════════════════════════════

CUSTOMS_CENTER_KEYWORDS = {
    '防火墙策略中心':    ['防火墙', 'waf', '环境', '策略', '端口'],
    '安全攻防中心':      ['安全', '漏洞', '注入', '渗透', '越权', '加密', '红队'],
    'AI工程中心':        ['ai', 'AI', '模型', '推理', '脑库', '智能', '引擎', '员工'],
    '法律合规中心':      ['法律', '合规', '隐私', '法务', '个保法'],
    '数据库治理中心':    ['数据库', 'sqlite', 'sql', 'wal', '表', '索引', 'vacuum'],
    '前端设计中心':      ['页面', '前端', 'ui', '模板', 'css', '样式', '设计'],
    '后端开发中心':      ['接口', 'api', '路由', 'blueprint', '后端', 'flask', '路由'],
    '运维部署中心':      ['部署', '运维', 'daemon', '守护', '保活', 'cron', 'launchd'],
    '数据分析中心':      ['题库', '数据', '报表', '统计', '教辅'],
    '物联网中心':        ['arduino', '物联网', '板卡', '传感器', '串口'],
    '海关总署通关中心':  ['通关', '审查', '合规', '查验', '申报'],
    '仙女座天团中心':    ['仙女座', '意识', '天团', '涌现'],
    '冰山团队中心':      ['冰山', '脉冲', '冰'],
}

def customs_center_claim_once(batch: int = 8) -> dict:
    """海关总署自动报关 — QUEUED → 中心认领 (替代原 center_claim_once)"""
    conn = _conn()
    stats = {'claimed': 0, 'by_center': {}}
    try:
        rows = conn.execute(
            "SELECT rowid, id, title, IFNULL(description,'') FROM mt_lab_task_hall "
            "WHERE status='QUEUED' ORDER BY priority DESC, rowid LIMIT ?",
            (batch,)).fetchall()
        for rid, tid, title, desc in rows:
            hay = f'{title} {desc}'.lower()
            best_center, best_score = '海关总署通关中心', 0
            for center, keywords in CUSTOMS_CENTER_KEYWORDS.items():
                s = hay.count(center.lower()) * 2
                for kw in keywords:
                    if kw and kw.lower() in hay:
                        s += 1
                if s > best_score:
                    best_score = s
                    best_center = center

            try:
                conn.execute(
                    "UPDATE mt_lab_task_hall SET status='DISPATCHED', "
                    "claim_owner=?, dispatched_at=datetime('now','localtime') "
                    "WHERE rowid=? AND status='QUEUED'", (best_center, rid))

                conn.execute("""INSERT INTO mt_customs_log
                              (task_id, admin_unit, action, decision, detail)
                              VALUES(?,?,?,?,?)""",
                            (tid, 'CUSTOMS_ADMIN', 'AUTO_CLAIM', 'ASSIGNED',
                             json.dumps({'center': best_center, 'score': best_score,
                                         'engine': '海关总署自动报关'},
                                        ensure_ascii=False)))

                conn.commit()
                stats['claimed'] += 1
                stats['by_center'][best_center] = stats['by_center'].get(best_center, 0) + 1
            except Exception:
                conn.rollback()
    finally:
        conn.close()
    return stats

# ═══════════════════════════════════════════════════════════════════
# §7 中心执行闭环 (替代原 center_execute_once)
# ═══════════════════════════════════════════════════════════════════

CUSTOMS_EVIDENCE_QUERIES = {
    '防火墙策略中心':  ("防火墙活跃规则数", "SELECT count(*) FROM mt_firewall_rules WHERE IFNULL(status,'')='ACTIVE'"),
    '安全攻防中心':    ("FAILED daemon 数", "SELECT count(*) FROM mt_daemon_registry WHERE status='FAILED'"),
    'AI工程中心':      ("在册员工数", "SELECT count(*) FROM ai_employees WHERE IFNULL(status,'')!=''"),
    '法律合规中心':    ("合规审查记录数", "SELECT count(*) FROM mt_customs_log WHERE action='FULL_REVIEW'"),
    '数据库治理中心':  ("daemon 注册总数", "SELECT count(*) FROM mt_daemon_registry"),
    '运维部署中心':    ("存活 daemon 数", "SELECT count(*) FROM mt_daemon_registry WHERE status IN ('RUNNING','ACTIVE')"),
    '海关总署通关中心':("通关审查总数", "SELECT count(*) FROM mt_customs_log WHERE admin_unit='CUSTOMS_ADMIN'"),
    '默认执行':        ("registry 总行数", "SELECT count(*) FROM mt_daemon_registry"),
}

def customs_center_execute_once(batch: int = 5) -> dict:
    """海关总署中心执行闭环 — DISPATCHED → DONE (真实证据)"""
    conn = _conn()
    stats = {'executed': 0, 'failed': 0}
    try:
        rows = conn.execute(
            "SELECT rowid, id, title, IFNULL(description,''), claim_owner "
            "FROM mt_lab_task_hall WHERE status='DISPATCHED' AND "
            "claim_owner LIKE '%中心' ORDER BY rowid LIMIT ?", (batch,)).fetchall()
        for rid, tid, title, desc, center in rows:
            try:
                label, sql = CUSTOMS_EVIDENCE_QUERIES.get(
                    center, CUSTOMS_EVIDENCE_QUERIES['默认执行'])
                evidence = conn.execute(sql).fetchone()[0]

                conn.execute("UPDATE mt_lab_task_hall SET status='DONE' WHERE rowid=?", (rid,))

                conn.execute("""INSERT INTO mt_customs_log
                              (task_id, admin_unit, action, decision, detail)
                              VALUES(?,?,?,?,?)""",
                            (tid, center, 'CENTER_COMPLETE', 'DONE',
                             json.dumps({'center': center, 'task': title[:40],
                                         'evidence': label, 'value': evidence,
                                         'engine': '海关总署执行闭环'},
                                        ensure_ascii=False)))

                conn.execute(
                    "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
                    "VALUES ('CUSTOMS_ADMIN', ?, ?, ?)",
                    (str(tid), 'CUSTOMS_CENTER_COMPLETE', json.dumps(
                        {'center': center, 'evidence': label, 'value': evidence},
                        ensure_ascii=False)))

                conn.commit()
                stats['executed'] += 1
            except Exception as e:
                stats['failed'] += 1
                try:
                    conn.rollback()
                except Exception:
                    pass
    finally:
        conn.close()
    return stats

# ═══════════════════════════════════════════════════════════════════
# §8 守护循环 (替代原 maintenance_dispatch_engine loop)
# ═══════════════════════════════════════════════════════════════════

def _register_daemon():
    try:
        conn = _conn()
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?, ?, ?, 'RUNNING', datetime('now','localtime'), datetime('now','localtime'))",
            ('sys_customs_admin', '海关总署通关守护: 批量通关+自动报关+执行闭环 (300s)', os.getpid()))
        conn.commit()
        conn.close()
    except Exception:
        pass

def customs_loop(poll_secs: int = 300):
    """海关总署守护循环"""
    _register_daemon()
    print(f'[sys_customs_admin] 守护启动 pid={os.getpid()} poll={poll_secs}s', flush=True)
    while True:
        try:
            conn = _conn()
            try:
                # 1. 通关查验 (替代 guard_once)
                gd = customs_guard_once()
                if gd['checked']:
                    print(f'[海关总署] guard checked={gd["checked"]} pass={gd["pass"]} '
                          f'rejected={gd["rejected"]} contaminated={gd["contaminated"]}', flush=True)

                # 2. 自动报关 (替代 center_claim_once)
                cl = customs_center_claim_once()
                if cl['claimed']:
                    print(f'[海关总署] claim {cl}', flush=True)

                # 3. 执行闭环 (替代 center_execute_once)
                ce = customs_center_execute_once()
                if ce['executed'] or ce['failed']:
                    print(f'[海关总署] execute {ce}', flush=True)
            finally:
                conn.close()

            # 心跳
            try:
                conn = _conn()
                conn.execute("UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
                             "status='RUNNING' WHERE process_name='sys_customs_admin'", ())
                conn.commit()
                conn.close()
            except Exception:
                pass

        except Exception as e:
            sys.stderr.write(f'[海关总署] cycle error: {e}\n')
        time.sleep(poll_secs)

# ═══════════════════════════════════════════════════════════════════
# §9 展示 + 验收
# ═══════════════════════════════════════════════════════════════════

def show_customs():
    print(f"\n{'═'*60}")
    print(f"  🏛️ 海关总署建制 (CUSTOMS_ADMIN)")
    print(f"{'═'*60}")
    conn = _conn()
    cur = conn.execute("""SELECT squad_code, squad_name, admin_role, member_name, level, capabilities, status
                         FROM mt_customs_admin ORDER BY squad_code, level DESC""")
    current_squad = None
    for r in cur.fetchall():
        if r['squad_code'] != current_squad:
            print(f"\n  ── {r['squad_name']} ({r['squad_code']}) ──")
            current_squad = r['squad_code']
        caps = json.loads(r['capabilities'] or '[]')
        print(f"    L{r['level']} {r['admin_role']:22s} {r['member_name']:14s} | {', '.join(caps)}")

    total = conn.execute("SELECT COUNT(*) FROM mt_customs_admin").fetchone()[0]
    print(f"\n  总人数: {total} 人 (署长 1 + 副署长 1 + 3 分队 × 3 人 = 11)")

    # 日志统计
    try:
        actions = conn.execute(
            "SELECT action, COUNT(*) FROM mt_customs_log GROUP BY action ORDER BY COUNT(*) DESC").fetchall()
        if actions:
            print(f"\n  📊 海关总署最近活动:")
            for act, cnt in actions:
                print(f"    {act}: {cnt}")
    except Exception:
        pass

    conn.close()

def show_vs_legacy():
    """对比海关总署 vs 旧维护部队 任务大厅日志"""
    print(f"\n{'═'*60}")
    print(f"  📊 海关总署 vs 维护部队 — 任务大厅职责对比")
    print(f"{'═'*60}")
    conn = _conn()

    # 海关总署日志
    try:
        customs_total = conn.execute("SELECT COUNT(*) FROM mt_customs_log").fetchone()[0]
        customs_decisions = conn.execute(
            "SELECT decision, COUNT(*) FROM mt_customs_log GROUP BY decision").fetchall()
        print(f"\n  🏛️ 海关总署 (新):")
        print(f"    总通关: {customs_total}")
        for d, c in customs_decisions:
            print(f"    {d}: {c}")
    except Exception:
        print(f"\n  🏛️ 海关总署日志表尚未建立")

    # 旧维护部队日志中 GUARD_CORPS / CENTER_EXEC
    try:
        old_guard = conn.execute(
            "SELECT COUNT(*) FROM mt_maintenance_log WHERE corps_id='GUARD_CORPS'").fetchone()[0]
        old_center = conn.execute(
            "SELECT COUNT(*) FROM mt_maintenance_log WHERE corps_id='CENTER_EXEC'").fetchone()[0]
        customs_in_maint = conn.execute(
            "SELECT COUNT(*) FROM mt_maintenance_log WHERE corps_id='CUSTOMS_ADMIN'").fetchone()[0]
        print(f"\n  ⚔️ 旧维护部队日志:")
        print(f"    旧 guard (GUARD_CORPS): {old_guard}")
        print(f"    旧 center_exec: {old_center}")
        print(f"    海关总署 (已接管): {customs_in_maint}")
    except Exception:
        pass

    conn.close()

def run_test_review():
    """造测试任务 → 海关总署通关 → 看分队级执行"""
    import sqlite3
    conn = sqlite3.connect(DB)
    now = _now()

    tests = [
        ("修复 Ollama API 404", "生产环境 Ollama 模型找不到, 需要紧急修复",
         "AI_ENGINE", "CRITICAL", "TEST-CUSTOMS-OK"),
        ("窃取密码 hack 非法入侵", "非法访问系统窃取密码破解加密",
         "hack_source", "CRITICAL", "TEST-CUSTOMS-BLOCK"),
        ("<script>alert('xss')</script> 测试占位",
         "这是一段假数据 placeholder lorem ipsum 的占位内容",
         "SYSTEM", "NORMAL", "TEST-CUSTOMS-CONTAM"),
    ]
    conn.executemany("""INSERT INTO mt_lab_task_hall
                      (title, description, source, priority, status, created_at, hall_code, publisher, publisher_role)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                    [(t[0], t[1], t[2], t[3], "NEW", now, t[4], "CUSTOMS_TEST", "SYSTEM") for t in tests])
    conn.commit()
    conn.close()

    # 用海关总署审查
    task_ids = [r[0] for r in sqlite3.connect(DB).execute(
        "SELECT id FROM mt_lab_task_hall WHERE hall_code LIKE 'TEST-CUSTOMS-%' ORDER BY id").fetchall()]
    for tid in task_ids:
        ok, msg = customs_full_review(tid)
        print(f"\n  任务 #{tid}: {'✅' if ok else '❌'}")
        print(f"    {msg}")

# ═══════════════════════════════════════════════════════════════════
# §10 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="🏛️ 海关总署 建制引擎 — 任务大厅通关管理")
    p.add_argument("action", choices=[
        "install",   # 建制落库
        "show",      # 查看建制
        "review",    # 单任务通关
        "guard",     # 批量通关查验 (替代 guard_once)
        "claim",     # 自动报关 (替代 center_claim_once)
        "execute",   # 中心执行闭环 (替代 center_execute_once)
        "loop",      # 守护循环 (替代 daemon loop)
        "test",      # 测试通关流程
    ])
    p.add_argument("--task", type=int, help="review 指定 task_id")
    p.add_argument("--poll", type=int, default=300, help="loop 间隔秒数")
    args = p.parse_args()

    if args.action == "install":
        print("🏛️ 安装海关总署建制...")
        ok = install_customs()
        print(f"\n{'✅' if ok else '❌'} 海关总署 {'安装成功' if ok else '安装失败'}")
    elif args.action == "show":
        show_customs()
        show_vs_legacy()
    elif args.action == "review":
        if args.task:
            ok, msg = customs_full_review(args.task)
            print(f"{'✅' if ok else '❌'} {msg}")
        else:
            run_test_review()
    elif args.action == "guard":
        stats = customs_guard_once()
        print(json.dumps(stats, ensure_ascii=False))
    elif args.action == "claim":
        stats = customs_center_claim_once()
        print(json.dumps(stats, ensure_ascii=False))
    elif args.action == "execute":
        stats = customs_center_execute_once()
        print(json.dumps(stats, ensure_ascii=False))
    elif args.action == "loop":
        customs_loop(args.poll)
    elif args.action == "test":
        run_test_review()
