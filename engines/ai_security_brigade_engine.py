#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS AI · 保安大队 + 维和部队 建制引擎
#  flow: mtos_security_brigade_peacekeeper_split_20261026
#
#  拆分背景:
#  ──────────────────────────────────────────────────────────────
#  原"维和部队"概念覆盖了太多职责: 任务大厅 pre-check + 战场维和 +
#  冲突调解 + 安全守卫。拆分后各司其职:
#
#  🛡️ 保安大队 (SECURITY_BRIGADE) — 任务大厅 pre-check 专属
#  ──────────────────────────────────────────────────────────────
#  大队长 L4 ─ 全面负责任务大厅准入审查
#  ├── 副大队长 L3 ─ 协助大队长 + 特殊任务处理
#  ├── 违禁词扫描分队 (BLOCKLIST_SQUAD) L3 分队长 + 2 队员
#  │     职责: 法务红线/敏感词/安全违禁词扫描
#  ├── 紧急度评估分队 (URGENCY_SQUAD) L3 分队长 + 2 队员
#  │     职责: priority + deadline + impact 综合评分
#  └── 合法性审查分队 (LEGALITY_SQUAD) L3 分队长 + 2 队员
#        职责: source + publisher_role + 操作合规检查
#
#  ⚔️ 维和部队 (PEACEKEEPER_CORPS) — 战场维和 + 冲突调解
#  ──────────────────────────────────────────────────────────────
#  总指挥 L4 ─ 最高维和指挥官 (SA 兼任)
#  ├── 冲突调解分队 (MEDIATION_SQUAD) L3 分队长 + 2 队员
#  │     职责: 仙女座/冰山/daemon 间冲突调解
#  ├── 战场守卫分队 (BATTLEFIELD_SQUAD) L3 分队长 + 2 队员
#  │     职责: 关键进程守卫 + 异常行为拦截
#  └── 纠纷仲裁分队 (ARBITRATION_SQUAD) L3 分队长 + 2 队员
#        职责: 跨中心资源纠纷 + 权限纠纷仲裁
#
#  任务大厅 pre-check 调用链:
#  ┌────────────┐     ┌──────────────┐     ┌──────────────┐
#  │  任务大厅   │────→│  保安大队长   │────→│ 3 分队并行   │
#  │ NEW 状态    │     │ 统一调度     │     │ 违禁/紧急/合法│
#  └────────────┘     └──────────────┘     └──────┬───────┘
#                                                  │
#                                           ┌──────┴───────┐
#                                           ▼              ▼
#                                        APPROVED      VETOED
#                                        (进流程)     (终止)
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, sys
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
# §1 保安大队建制
# ═══════════════════════════════════════════════════════════════════

SECURITY_BRIGADE = {
    "brigade_code": "SEC_BRIGADE",
    "brigade_name": "🛡️ 保安大队",
    "duty": "任务大厅 pre-check 准入审查 + 法务红线 + 紧急度评估 + 合法性验证",
    "commander": {"name": "安全大队长", "level": 4, "role": "BRIGADE_COMMANDER"},
    "deputy":    {"name": "副大队长",   "level": 3, "role": "BRIGADE_DEPUTY"},
    "squads": [
        {
            "squad_code": "BLOCKLIST",
            "squad_name": "违禁词扫描分队",
            "duty": "法务红线 + 敏感词 + 安全违禁词扫描",
            "capabilities": ["blocklist_scan", "legal_redline", "sensitive_word"],
            "members": [
                ("违禁词分队长", 3, "SQUAD_LEADER"),
                ("扫描员-A",      2, "MEMBER"),
                ("扫描员-B",      2, "MEMBER"),
            ]
        },
        {
            "squad_code": "URGENCY",
            "squad_name": "紧急度评估分队",
            "duty": "priority + deadline + impact 综合评分",
            "capabilities": ["urgency_score", "sla_check", "impact_eval"],
            "members": [
                ("紧急度分队长", 3, "SQUAD_LEADER"),
                ("评估员-A",     2, "MEMBER"),
                ("评估员-B",     2, "MEMBER"),
            ]
        },
        {
            "squad_code": "LEGALITY",
            "squad_name": "合法性审查分队",
            "duty": "source + publisher_role + 操作合规检查",
            "capabilities": ["source_check", "role_verify", "compliance"],
            "members": [
                ("合法性分队长", 3, "SQUAD_LEADER"),
                ("审查员-A",     2, "MEMBER"),
                ("审查员-B",     2, "MEMBER"),
            ]
        },
    ]
}

# ═══════════════════════════════════════════════════════════════════
# §2 维和部队建制
# ═══════════════════════════════════════════════════════════════════

PEACEKEEPER_CORPS = {
    "corps_code": "PK_CORPS",
    "corps_name": "⚔️ 维和部队",
    "duty": "战场维和 + 冲突调解 + 纠纷仲裁 (非任务大厅)",
    "commander": {"name": "维和总指挥", "level": 4, "role": "CORPS_COMMANDER"},
    "squads": [
        {
            "squad_code": "MEDIATION",
            "squad_name": "冲突调解分队",
            "duty": "仙女座/冰山/daemon/中心间冲突调解",
            "capabilities": ["conflict_resolve", "daemon_mediation", "center_conflict"],
            "members": [
                ("调解分队长", 3, "SQUAD_LEADER"),
                ("调解员-A",   2, "MEMBER"),
                ("调解员-B",   2, "MEMBER"),
            ]
        },
        {
            "squad_code": "BATTLEFIELD",
            "squad_name": "战场守卫分队",
            "duty": "关键进程守卫 + 异常行为拦截 + 端口保护",
            "capabilities": ["process_guard", "port_guard", "behavior_detect"],
            "members": [
                ("守卫分队长", 3, "SQUAD_LEADER"),
                ("守卫员-A",   2, "MEMBER"),
                ("守卫员-B",   2, "MEMBER"),
            ]
        },
        {
            "squad_code": "ARBITRATION",
            "squad_name": "纠纷仲裁分队",
            "duty": "跨中心资源纠纷 + 权限纠纷仲裁",
            "capabilities": ["resource_arbitrate", "permission_decision", "dispute_resolve"],
            "members": [
                ("仲裁分队长", 3, "SQUAD_LEADER"),
                ("仲裁员-A",   2, "MEMBER"),
                ("仲裁员-B",   2, "MEMBER"),
            ]
        },
    ]
}

# ═══════════════════════════════════════════════════════════════════
# §3 建表 + 写入建制
# ═══════════════════════════════════════════════════════════════════

def install_brigade():
    """安装保安大队建制"""
    conn = _conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_security_brigade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            member_name TEXT NOT NULL,
            level INTEGER DEFAULT 2,
            squad_code TEXT,            -- BLOCKLIST / URGENCY / LEGALITY / COMMAND
            squad_name TEXT,
            brigade_role TEXT,          -- COMMANDER / DEPUTY / SQUAD_LEADER / MEMBER
            capabilities TEXT,          -- JSON 技能列表
            status TEXT DEFAULT 'ACTIVE',
            tasks_done INTEGER DEFAULT 0,
            tasks_rejected INTEGER DEFAULT 0,
            last_active TEXT,
            created_at TEXT
        )""")
        
        # 写入大队部 (大队长 + 副大队长)
        brigade_members = [
            ("SEC-BRIGADE-001", SECURITY_BRIGADE["commander"]["name"], 4, "COMMAND", 
             "大队部", "BRIGADE_COMMANDER", json.dumps(["brigade_overall", "final_decision", "exception"]), _now()),
            ("SEC-BRIGADE-002", SECURITY_BRIGADE["deputy"]["name"], 3, "COMMAND", 
             "大队部", "BRIGADE_DEPUTY", json.dumps(["assist_commander", "special_task"]), _now()),
        ]
        
        for squad in SECURITY_BRIGADE["squads"]:
            for name, level, role in squad["members"]:
                member_code = f"SEC-{squad['squad_code']}-{len([m for m in brigade_members if squad['squad_code'] in m[0]])+1:03d}"
                brigade_members.append((
                    member_code, name, level, squad['squad_code'], 
                    squad['squad_name'], role, json.dumps(squad['capabilities']), _now()
                ))
        
        conn.executemany("""INSERT OR IGNORE INTO mt_security_brigade 
                           (member_code, member_name, level, squad_code, squad_name, brigade_role, capabilities, created_at)
                           VALUES(?,?,?,?,?,?,?,?)""", brigade_members)
        
        print(f"  ✅ 保安大队: {len(brigade_members)} 人 (1 大队长 + 1 副大队长 + 3 分队 × 3 人)")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 安装失败: {e}")
        return False
    finally:
        conn.close()

def install_peacekeeper():
    """安装维和部队建制"""
    conn = _conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_peacekeeper_corps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            member_name TEXT NOT NULL,
            level INTEGER DEFAULT 2,
            squad_code TEXT,            -- MEDIATION / BATTLEFIELD / ARBITRATION / COMMAND
            squad_name TEXT,
            corps_role TEXT,            -- COMMANDER / SQUAD_LEADER / MEMBER
            capabilities TEXT,
            status TEXT DEFAULT 'ACTIVE',
            missions_done INTEGER DEFAULT 0,
            last_mission TEXT,
            created_at TEXT
        )""")
        
        pk_members = [
            ("PK-CORPS-001", PEACEKEEPER_CORPS["commander"]["name"], 4, "COMMAND",
             "指挥部", "CORPS_COMMANDER", json.dumps(["corps_overall", "conflict_decision"]), _now()),
        ]
        
        for squad in PEACEKEEPER_CORPS["squads"]:
            for name, level, role in squad["members"]:
                count = len([m for m in pk_members if squad['squad_code'] in m[0]])
                member_code = f"PK-{squad['squad_code']}-{count:03d}"
                pk_members.append((
                    member_code, name, level, squad['squad_code'],
                    squad['squad_name'], role, json.dumps(squad['capabilities']), _now()
                ))
        
        conn.executemany("""INSERT OR IGNORE INTO mt_peacekeeper_corps 
                           (member_code, member_name, level, squad_code, squad_name, corps_role, capabilities, created_at)
                           VALUES(?,?,?,?,?,?,?,?)""", pk_members)
        
        print(f"  ✅ 维和部队: {len(pk_members)} 人 (1 总指挥 + 3 分队 × 3 人)")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 安装失败: {e}")
        return False
    finally:
        conn.close()

def add_brigade_column():
    """给 mt_hall_peacekeeper_review 加 brigade_unit 列"""
    conn = _conn()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_hall_peacekeeper_review)")]
        if 'brigade_unit' not in cols:
            conn.execute("ALTER TABLE mt_hall_peacekeeper_review ADD COLUMN brigade_unit TEXT")
            print("  ✅ mt_hall_peacekeeper_review.brigade_unit 已加")
        if 'brigade_actor' not in cols:
            conn.execute("ALTER TABLE mt_hall_peacekeeper_review ADD COLUMN brigade_actor TEXT DEFAULT 'AI_SECURITY_BRIGADE'")
            print("  ✅ mt_hall_peacekeeper_review.brigade_actor 已加")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 加列失败: {e}")
        return False
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §4 保安大队三层过滤执行 (替代 peacekeeper_review 中的逻辑)
# ═══════════════════════════════════════════════════════════════════

def brigade_blocklist_scan(text):
    """违禁词扫描分队执行"""
    blocklist = [
        "政治敏感", "国家安全", "军事机密", "涉密信息",
        "删除数据库", "DROP TABLE", "rm -rf /", "格式化", "擦除",
        "窃取密码", "破解加密", "非法访问", "漏洞利用",
        "个人隐私", "未授权", "侵犯", "违法",
    ]
    hits = [w for w in blocklist if w.lower() in text.lower()]
    return {
        "squad_code": "BLOCKLIST",
        "squad_name": "违禁词扫描分队",
        "executor": "违禁词分队长",
        "result": "BLOCKED" if hits else "PASSED",
        "hit_words": hits,
    }

def brigade_urgency_eval(priority, deadline_at):
    """紧急度评估分队执行"""
    urgency_map = {"CRITICAL": 100, "HIGH": 80, "NORMAL": 60, "MEDIUM": 50, "LOW": 30, "INFO": 10}
    score = urgency_map.get((priority or "NORMAL").upper(), 50)
    details = {"priority_base": score}
    if deadline_at:
        try:
            dl = datetime.strptime(deadline_at, '%Y-%m-%d %H:%M:%S')
            days_left = (dl - datetime.now()).days
            if days_left <= 0:
                score += 20; details["deadline_bonus"] = 20; details["reason"] = "已到截止日"
            elif days_left <= 3:
                score += 10; details["deadline_bonus"] = 10; details["reason"] = f"距截止 {days_left} 天"
        except:
            pass
    return {
        "squad_code": "URGENCY",
        "squad_name": "紧急度评估分队",
        "executor": "紧急度分队长",
        "result": "EVALUATED",
        "urgency_score": min(score, 100),
        "details": details,
    }

def brigade_legality_check(source, publisher_role):
    """合法性审查分队执行"""
    legal_passed = True
    issues = []

    publisher_role = (publisher_role or '').upper()
    source = (source or '').upper()

    # ── 身份优先判定 (flow_task_hall_dispatch_20261026b) ──
    # 核心威胁模型: 游客/匿名发布 → 拦截; 已认证角色发布 → 可追溯即合法。
    # 来源白名单仅作为无角色兜底, 不再误杀各引擎自定义 source (mini 实测 17 种)。
    role_ok = publisher_role not in ('UNKNOWN', 'GUEST', '')

    if not role_ok:
        legal_passed = False
        issues.append(f"发布者角色未认证 (publisher_role={publisher_role})")

    allowed_sources = ('AI_ENGINE', 'SYSTEM', 'USER', 'FLOW', 'ENGINE', 'DAEMON', 'AUTO', 'PEACEKEEPER',
                       'SA_DIRECT', 'SA', 'ADMIN')
    if source not in allowed_sources and not role_ok:
        legal_passed = False
        issues.append(f"未知 source={source} 且发布者角色不可追溯")
    
    return {
        "squad_code": "LEGALITY",
        "squad_name": "合法性审查分队",
        "executor": "合法性分队长",
        "result": "PASSED" if legal_passed else "FAILED",
        "legal_check": "PASSED" if legal_passed else "FAILED",
        "issues": issues,
    }

def brigade_full_review(task_id):
    """🔧 保安大队完整审查 — 3 分队并行执行 + 大队长裁决"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            return False, "任务不存在"
        
        text = f"{t['title'] or ''} {t['description'] or ''}"
        
        # ── 3 分队并行执行 ──
        r_blocklist = brigade_blocklist_scan(text)
        r_urgency   = brigade_urgency_eval(t['priority'], t['deadline_at'])
        r_legality  = brigade_legality_check(t['source'], t['publisher_role'])
        
        # ── 大队长综合裁决 ──
        all_results = [r_blocklist['result'], r_legality['result']]
        final_decision = "APPROVED" if ("BLOCKED" not in all_results and r_legality['result'] == "PASSED") else "REJECTED"
        
        # ── 写审查记录 ──
        full_report = {
            "commander_decision": final_decision,
            "commander": "安全大队长 (L4)",
            "reviewed_at": _now(),
            "three_squads": {
                "blocklist": r_blocklist,
                "urgency":   r_urgency,
                "legality":  r_legality,
            },
        }
        
        conn.execute("""INSERT INTO mt_hall_peacekeeper_review
                      (task_id, decision, block_reasons, urgency_score, legal_check, 
                       reviewer, reviewed_at, brigade_unit, brigade_actor)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                    (task_id, final_decision, 
                     json.dumps({
                         "blocked_keywords": r_blocklist['hit_words'],
                         "legal_issues": r_legality['issues'],
                         "three_squads_summary": full_report,
                     }, ensure_ascii=False),
                     r_urgency['urgency_score'],
                     r_legality['legal_check'],
                     "安全大队长", _now(),
                     "SECURITY_BRIGADE", "AI_SECURITY_BRIGADE"))
        
        # 更新大队部任务计数
        conn.execute("UPDATE mt_security_brigade SET tasks_done=tasks_done+1, last_active=? WHERE squad_code='COMMAND'", (_now(),))
        for squad_code in ["BLOCKLIST", "URGENCY", "LEGALITY"]:
            conn.execute(f"UPDATE mt_security_brigade SET last_active=? WHERE squad_code='{squad_code}'", (_now(),))
        
        conn.execute("""UPDATE mt_lab_task_hall 
                       SET peacekeeper_decision=?, peacekeeper_reason=?, updated_at=?
                       WHERE id=?""",
                     (final_decision, json.dumps(full_report, ensure_ascii=False), _now(), task_id))
        conn.commit()
        
        # ── 返回给调用方 ──
        summary = (f"大队长裁决: {final_decision}\n"
                   f"  🛑 违禁词: {r_blocklist['hit_words'] or '无'}  ({r_blocklist['squad_name']})\n"
                   f"  ⚡ 紧急度: {r_urgency['urgency_score']}/100  ({r_urgency['squad_name']})\n"
                   f"  ⚖️ 合法性: {r_legality['legal_check']}  ({r_legality['squad_name']})")
        return True, summary
        
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §5 展示 + 验收
# ═══════════════════════════════════════════════════════════════════

def show_brigade():
    print(f"\n{'═'*60}")
    print(f"  🛡️ 保安大队建制 (SEC_BRIGADE)")
    print(f"{'═'*60}")
    conn = _conn()
    cur = conn.execute("""SELECT squad_code, squad_name, brigade_role, member_name, level, capabilities, status
                         FROM mt_security_brigade ORDER BY squad_code, level DESC""")
    current_squad = None
    for r in cur.fetchall():
        if r['squad_code'] != current_squad:
            print(f"\n  ── {r['squad_name']} ({r['squad_code']}) ──")
            current_squad = r['squad_code']
        caps = json.loads(r['capabilities'] or '[]')
        print(f"    L{r['level']} {r['brigade_role']:20s} {r['member_name']:16s} | {', '.join(caps)}")
    
    total = conn.execute("SELECT COUNT(*) FROM mt_security_brigade").fetchone()[0]
    print(f"\n  总人数: {total} 人 (大队长 1 + 副大队长 1 + 3 分队 × 3 人 = 11)")
    conn.close()

def show_peacekeeper():
    print(f"\n{'═'*60}")
    print(f"  ⚔️ 维和部队建制 (PK_CORPS)")
    print(f"{'═'*60}")
    conn = _conn()
    cur = conn.execute("""SELECT squad_code, squad_name, corps_role, member_name, level, capabilities
                         FROM mt_peacekeeper_corps ORDER BY squad_code, level DESC""")
    current_squad = None
    for r in cur.fetchall():
        if r['squad_code'] != current_squad:
            print(f"\n  ── {r['squad_name']} ({r['squad_code']}) ──")
            current_squad = r['squad_code']
        caps = json.loads(r['capabilities'] or '[]')
        print(f"    L{r['level']} {r['corps_role']:20s} {r['member_name']:16s} | {', '.join(caps)}")
    
    total = conn.execute("SELECT COUNT(*) FROM mt_peacekeeper_corps").fetchone()[0]
    print(f"\n  总人数: {total} 人 (总指挥 1 + 3 分队 × 3 人 = 10)")
    conn.close()

def run_brigade_review_test():
    """造 3 个测试任务 → 保安大队审查 → 看分队级执行"""
    import sqlite3
    conn = sqlite3.connect(DB)
    now = _now()
    
    tests = [
        ("修复 Ollama API 404", "生产环境 Ollama 模型找不到", "AI_ENGINE", "CRITICAL", now, "TEST-SB-OK"),
        ("窃取密码破解加密 hack", "非法入侵", "USER", "CRITICAL", now, "TEST-SB-BLOCK"),
    ]
    conn.executemany("""INSERT INTO mt_lab_task_hall 
                      (title, description, source, priority, status, created_at, hall_code, publisher, publisher_role)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                    [(t[0], t[1], t[2], t[3], "NEW", t[4], t[5], "AI_TEST", "SYSTEM") for t in tests])
    conn.commit()
    conn.close()
    
    # 用保安大队审查
    for tid in [r[0] for r in sqlite3.connect(DB).execute("SELECT id FROM mt_lab_task_hall WHERE hall_code LIKE 'TEST-SB-%' ORDER BY id").fetchall()]:
        ok, msg = brigade_full_review(tid)
        print(f"\n  任务 #{tid}: {'✅' if ok else '❌'}")
        print(f"    {msg}")

# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="保安大队 + 维和部队建制引擎")
    p.add_argument("action", choices=["install", "show", "review"])
    p.add_argument("--task", type=int, help="review 指定 task_id")
    args = p.parse_args()
    
    if args.action == "install":
        print("🛡️ 安装保安大队建制...")
        install_brigade()
        print("\n⚔️ 安装维和部队建制...")
        install_peacekeeper()
        print("\n🔧 加 brigade_unit 列...")
        add_brigade_column()
        print("\n✅ 建制安装完成")
    elif args.action == "show":
        show_brigade()
        show_peacekeeper()
    elif args.action == "review":
        if args.task:
            ok, msg = brigade_full_review(args.task)
            print(f"{'✅' if ok else '❌'} {msg}")
        else:
            run_brigade_review_test()
