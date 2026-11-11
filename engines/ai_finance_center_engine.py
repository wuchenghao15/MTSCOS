#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS AI · 💰 财务中心引擎 (第 15 中心)
#  flow_finance_center_20261026
#
#  职责 (与 14 中心 + 任务大厅 + AI 人员深度绑定):
#  ──────────────────────────────────────────────────────────────
#  1. Token 对账  — 充值订单 pending 对账 + 全系统 token 收支总账
#  2. 消耗审计    — mt_user_token_ledger 异常消耗扫描 (单笔>2000 / 日耗>8000)
#  3. 成本核算    — 任务大厅 DONE 任务 ↔ 中心 成本账单 (各中心赋能)
#  4. 绩效结算    — AI 员工完成任务 → 绩效 token 发放 (AI 人员赋能)
#  5. 定价管理    — mt_chat_model_pricing 扣费倍数 + 充值汇率 快照审计
#
#  CLI: install / report / audit / settle / pricing
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT_ROOT, "database", "app.db")

FINANCE_SKILL = "finance_budget"
FINANCE_CENTER = "财务中心"
RECHARGE_RATE = 100  # 1元 = 100 Token (与 chat_local_bp 保持同步)

# ── 建制: CFO + 4 科 ──
FINANCE_STAFF = [
    ("FIN-CMD-01",  "财务总监 (CFO)",   4, "COMMAND",    "中心指挥部", "DIRECTOR",
     ["finance_overall", "budget_approval", "final_decision"]),
    ("FIN-CMD-02",  "财务副总监",       3, "COMMAND",    "中心指挥部", "DEPUTY",
     ["assist_director", "report_review"]),
    ("FIN-REC-01",  "对账科长",         3, "RECONCILE",  "对账科", "LEADER",
     ["recharge_reconcile", "order_audit", "income_verify"]),
    ("FIN-REC-02",  "对账会计",         2, "RECONCILE",  "对账科", "MEMBER",
     ["recharge_reconcile", "daily_close"]),
    ("FIN-AUD-01",  "审计科长",         3, "AUDIT",      "审计科", "LEADER",
     ["ledger_audit", "anomaly_detect", "big_amount_review"]),
    ("FIN-AUD-02",  "审计员",           2, "AUDIT",      "审计科", "MEMBER",
     ["ledger_scan", "anomaly_report"]),
    ("FIN-CST-01",  "成本核算科长",     3, "COSTING",    "成本核算科", "LEADER",
     ["task_costing", "center_budget", "cost_report"]),
    ("FIN-CST-02",  "核算会计",         2, "COSTING",    "成本核算科", "MEMBER",
     ["task_costing", "center_statement"]),
    ("FIN-PRF-01",  "绩效结算科长",     3, "PAYROLL",    "绩效结算科", "LEADER",
     ["ai_payroll", "merit_token", "task_reward_settle"]),
    ("FIN-PRF-02",  "绩效结算员",       2, "PAYROLL",    "绩效结算科", "MEMBER",
     ["ai_payroll", "payout_log"]),
]

# 中心成本单价 (赋能各中心: 每个完成任务的基础预算)
CENTER_UNIT_BUDGET = {
    "人力资源中心": 800, "政务中心": 500, "学习中心": 600,
    "安全运维中心": 1000, "AI引擎中心": 1200, "法务合规中心": 900,
    "前端设计中心": 700, "后端开发中心": 1000, "Arduino物联网中心": 800,
    "教育题库中心": 600, "巡检守护中心": 500, "冰山仙女座中心": 1500,
    "防火墙治理中心": 1000, "任务大厅中心": 400, "财务中心": 300,
}

def _conn():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")  # daemon 高频写入防锁
    return conn

def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ═══════════════════════════════════════════════════════════════════
# §1 install — 建制表 + AI 员工注册 + 大厅 skill 注册
# ═══════════════════════════════════════════════════════════════════

def install():
    conn = _conn()
    try:
        # 1) 建制表
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_finance_center (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            member_name TEXT NOT NULL,
            level INTEGER DEFAULT 2,
            dept_code TEXT,
            dept_name TEXT,
            finance_role TEXT,
            capabilities TEXT,
            status TEXT DEFAULT 'ACTIVE',
            orders_audited INTEGER DEFAULT 0,
            tokens_settled INTEGER DEFAULT 0,
            last_active TEXT,
            created_at TEXT
        )""")
        for code, name, lvl, dept, dept_n, role, caps in FINANCE_STAFF:
            conn.execute("""INSERT OR IGNORE INTO mt_finance_center
                          (member_code,member_name,level,dept_code,dept_name,finance_role,capabilities,created_at)
                          VALUES(?,?,?,?,?,?,?,?)""",
                         (code, name, lvl, dept, dept_n, role, json.dumps(caps, ensure_ascii=False), _now()))

        # 2) AI 员工注册 (ai_employees 统一名册)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_employees)")]
        name_col = 'name' if 'name' in cols else ('employee_name' if 'employee_name' in cols else None)
        if name_col:
            role_col = 'role' if 'role' in cols else None
            comm_col = 'committee_role' if 'committee_role' in cols else None
            skill_col = None
            for cand in ('skill', 'skills', 'skill_id'):
                if cand in cols:
                    skill_col = cand; break
            lvl_col = 'level' if 'level' in cols else None
            stat_col = 'status' if 'status' in cols else None
            reg = 0
            for code, name, lvl, dept, dept_n, role, caps in FINANCE_STAFF:
                dup = conn.execute(f"SELECT 1 FROM ai_employees WHERE {name_col}=?", (f"{name}·财务中心",)).fetchone()
                if dup:
                    continue
                fields = {name_col: f"{name}·财务中心"}
                if role_col: fields[role_col] = FINANCE_CENTER
                if comm_col: fields[comm_col] = f"财务中心·{dept_n}"
                if skill_col: fields[skill_col] = FINANCE_SKILL
                if lvl_col: fields[lvl_col] = lvl
                if stat_col: fields[stat_col] = 'ACTIVE'
                q = f"INSERT INTO ai_employees ({','.join(fields)}) VALUES({','.join('?'*len(fields))})"
                conn.execute(q, list(fields.values()))
                reg += 1
            print(f"  ✅ ai_employees 注册财务中心 {reg} 人 (存量跳过)")

        # 3) 任务大厅 skill 包注册 (mt_task_hall_skills 若存在)
        try:
            conn.execute("""INSERT OR IGNORE INTO mt_task_hall_skills (skill_id, skill_name, center, description)
                          VALUES(?,?,?,?)""",
                         (FINANCE_SKILL, "财务预算技能包", FINANCE_CENTER,
                          "Token对账/消耗审计/任务成本核算/AI绩效结算/定价汇率管理"))
            print("  ✅ mt_task_hall_skills 注册 finance_budget")
        except Exception:
            pass

        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM mt_finance_center").fetchone()[0]
        print(f"  ✅ mt_finance_center 建制 {n} 人 (CFO 1 + 副总监 1 + 4 科各 2)")
    except Exception as e:
        conn.rollback()
        print(f"  ❌ install 失败: {e}")
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §2 report — Token 收支总账 + 充值对账 (对账科)
# ═══════════════════════════════════════════════════════════════════

def report():
    conn = _conn()
    try:
        print(f"\n{'═'*62}")
        print(f"  💰 财务中心 · Token 收支总账  ({_now()})")
        print(f"{'═'*62}")
        # 充值订单
        try:
            ro = conn.execute("""SELECT status, COUNT(*) c, COALESCE(SUM(amount_yuan),0) y,
                                COALESCE(SUM(tokens),0) t FROM mt_token_recharge_orders GROUP BY status""").fetchall()
            print("\n  [充值订单]")
            for r in ro:
                print(f"    {r['status']:10s} {r['c']:>4} 单  ¥{r['y']:<10.2f} = {r['t']:>8} T")
        except Exception:
            print("  [充值订单] 表未建 (懒建后可用)")
        # ledger 汇总
        led = conn.execute("""SELECT type, COUNT(*) c, COALESCE(SUM(change),0) s
                            FROM mt_user_token_ledger GROUP BY type ORDER BY s""").fetchall()
        print("\n  [ledger 收支汇总]")
        income = consume = 0
        for r in led:
            sign = '+' if r['s'] >= 0 else ''
            print(f"    {r['type']:14s} {r['c']:>6} 笔  {sign}{r['s']:>10} T")
            if r['s'] > 0: income += r['s']
            else: consume += -r['s']
        # 余额盘点 (双轨)
        try:
            w = conn.execute("SELECT COALESCE(SUM(balance),0) b, COUNT(*) c FROM mt_token_wallets").fetchone()
            print(f"\n  [余额盘点] wallets: {w['c']} 户 合计 {w['b']} T")
        except Exception: pass
        try:
            a = conn.execute("SELECT COALESCE(SUM(balance),0) b, COUNT(*) c FROM mt_user_token_accounts").fetchone()
            print(f"  [余额盘点] accounts: {a['c']} 户 合计 {a['b']} T")
        except Exception: pass
        print(f"\n  总收入 {income} T / 总消耗 {consume} T / 净流入 {income - consume} T")
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §3 audit — 消耗审计 (审计科): 大额/高频异常扫描
# ═══════════════════════════════════════════════════════════════════

def audit():
    conn = _conn()
    findings = []
    try:
        print(f"\n{'═'*62}\n  🔍 财务中心 · 消耗审计  ({_now()})\n{'═'*62}")
        # 大额单笔
        big = conn.execute("""SELECT user_id, type, change, session_id, created_at FROM mt_user_token_ledger
                            WHERE change < -2000 ORDER BY id DESC LIMIT 10""").fetchall()
        for r in big:
            findings.append(f"  🚨 大额消耗 {r['user_id']} {r['change']}T ({r['created_at']}, session={r['session_id']})")
        # 单用户日耗
        heavy = conn.execute("""SELECT user_id, DATE(created_at) d, SUM(change) s FROM mt_user_token_ledger
                              WHERE type='consume' AND created_at >= datetime('now','-7 day','localtime')
                              GROUP BY user_id, DATE(created_at) HAVING SUM(change) < -8000
                              ORDER BY s LIMIT 10""").fetchall()
        for r in heavy:
            findings.append(f"  🚨 日耗超标 {r['user_id']} @ {r['d']} 消耗 {-r['s']}T")
        # pending 充值单对账提醒
        try:
            pend = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(tokens),0) t FROM mt_token_recharge_orders WHERE status='pending'").fetchone()
            if pend['c']:
                findings.append(f"  ⏳ 待确认充值单 {pend['c']} 笔 (合计 {pend['t']}T) — 等待收款确认")
        except Exception: pass
        if findings:
            for f in findings: print(f)
        else:
            print("  ✅ 无异常: 无大额消耗 / 无日耗超标 / 无积压充值单")
        # 审计留痕
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_finance_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, findings INTEGER, detail TEXT, created_at TEXT)""")
        conn.execute("INSERT INTO mt_finance_audit_log (findings, detail, created_at) VALUES(?,?,?)",
                     (len(findings), json.dumps(findings, ensure_ascii=False), _now()))
        conn.commit()
        return findings
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §3b reconcile — 定时全量对账 (审计科; cron */10 调度)
# ═══════════════════════════════════════════════════════════════════

def reconcile():
    """🔍 定时全量对账 (与实时钩子 _reconcile_user_live 互补):
    1. 双轨全用户账实核对 (ledger 尾条 balance_after vs 当前余额)
    2. 充值单闭环 (paid 单必须有对应 admin_adjust 流水; pending>24h 提醒)
    3. 结果写 mt_finance_reconcile_log (scope=full_*)
    返回异常清单"""
    conn = _conn()
    anomalies = []
    try:
        print(f"\n{'═'*62}\n  🔍 财务中心 · 定时全量对账  ({_now()})\n{'═'*62}")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_finance_reconcile_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT, user_id TEXT, level TEXT, trigger TEXT,
            ledger_balance INTEGER, actual_balance INTEGER, diff INTEGER,
            detail TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))""")

        # 1) 双轨全用户账实核对
        checked = 0
        for table, label in (("mt_token_wallets", "wallets"), ("mt_user_token_accounts", "accounts")):
            for u in conn.execute(f"SELECT user_id, balance FROM {table}").fetchall():
                checked += 1
                last = conn.execute("SELECT balance_after FROM mt_user_token_ledger "
                                    "WHERE user_id=? ORDER BY id DESC LIMIT 1",
                                    (str(u['user_id']),)).fetchone()
                lb = last['balance_after'] if last else None
                if lb is None:
                    continue  # 纯授权户无流水, 跳过
                if lb != u['balance']:
                    anomalies.append({'scope': f'full_{label}', 'user_id': str(u['user_id']),
                                      'ledger_balance': lb, 'actual_balance': u['balance'],
                                      'diff': u['balance'] - lb})
                    print(f"  🚨 账实不符 [{label}] {u['user_id']}: ledger={lb} 实际={u['balance']} (diff={u['balance']-lb})")

        # 2) 充值单闭环
        rc_checked = 0
        try:
            for o in conn.execute("SELECT order_no, user_id, tokens, status FROM mt_token_recharge_orders "
                                  "WHERE status IN ('paid','pending')").fetchall():
                rc_checked += 1
                if o['status'] == 'paid':
                    led = conn.execute("SELECT 1 FROM mt_user_token_ledger WHERE user_id=? "
                                       "AND type='admin_adjust' AND detail LIKE ?",
                                       (o['user_id'], f'%{o["order_no"]}%')).fetchone()
                    if not led:
                        anomalies.append({'scope': 'full_recharge', 'user_id': o['user_id'],
                                          'ledger_balance': None, 'actual_balance': o['tokens'],
                                          'diff': None, 'order': o['order_no'],
                                          'msg': 'paid 充值单无对应 admin_adjust 流水'})
                        print(f"  🚨 充值单断链 {o['order_no']}: paid 但 ledger 无入账流水")
                else:  # pending
                    age_h = conn.execute("SELECT (julianday('now','localtime') - julianday(created_at))*24 a "
                                         "FROM mt_token_recharge_orders WHERE order_no=?",
                                         (o['order_no'],)).fetchone()['a']
                    if age_h and age_h > 24:
                        anomalies.append({'scope': 'full_recharge', 'user_id': o['user_id'],
                                          'ledger_balance': None, 'actual_balance': o['tokens'],
                                          'diff': None, 'order': o['order_no'],
                                          'msg': f'pending 超 {age_h:.0f}h 未确认'})
                        print(f"  ⏳ pending 充值单 {o['order_no']} 已 {age_h:.0f}h 未确认")
        except Exception:
            pass  # 充值表未建 (懒建)

        # 3) 留痕
        level = 'ANOMALY' if anomalies else 'OK'
        detail = json.dumps({'users_checked': checked, 'orders_checked': rc_checked,
                             'anomalies': anomalies}, ensure_ascii=False)
        conn.execute("""INSERT INTO mt_finance_reconcile_log
                      (scope,user_id,level,trigger,ledger_balance,actual_balance,diff,detail)
                      VALUES(?,?,?,?,?,?,?,?)""",
                     ('full_all', 'SYSTEM', level, 'cron_reconcile',
                      None, None, None, detail))
        conn.commit()
        print(f"\n  ✅ 全量对账完成: {checked} 用户 + {rc_checked} 充值单 → "
              f"{'🚨 ' + str(len(anomalies)) + ' 项异常' if anomalies else '全部一致 (OK)'}")
        print("  留痕: mt_finance_reconcile_log (scope=full_all)")
        return anomalies
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §4 settle — 成本核算 (核算科) + AI 绩效结算 (绩效科)
# ═══════════════════════════════════════════════════════════════════

def settle():
    conn = _conn()
    try:
        print(f"\n{'═'*62}\n  📊 财务中心 · 成本核算 + 绩效结算  ({_now()})\n{'═'*62}")
        # 1) 各中心成本账单 (DONE 任务 ↔ mt_lab_centers 权威名 ↔ 单位预算)
        try:
            rows = conn.execute("""SELECT h.center_id AS cid, c.name AS cname, COUNT(*) c
                                  FROM mt_lab_task_hall h
                                  LEFT JOIN mt_lab_centers c ON c.id = h.center_id
                                  WHERE h.status='DONE' AND h.center_id IS NOT NULL AND h.center_id != ''
                                  GROUP BY h.center_id""").fetchall()
            print("\n  [各中心成本账单 — DONE 任务 × 单位预算]")
            conn.execute("""CREATE TABLE IF NOT EXISTS mt_finance_center_cost (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                center TEXT, done_tasks INTEGER, unit_budget INTEGER, cost INTEGER,
                bill_date TEXT, created_at TEXT)""")
            total = 0
            for r in rows:
                cname = r['cname'] or f"center#{r['cid']}"
                unit = CENTER_UNIT_BUDGET.get(cname, 500)
                cost = r['c'] * unit
                total += cost
                conn.execute("""INSERT INTO mt_finance_center_cost
                              (center, done_tasks, unit_budget, cost, bill_date, created_at)
                              VALUES(?,?,?,?,?,?)""",
                             (cname, r['c'], unit, cost, datetime.now().strftime('%Y-%m-%d'), _now()))
                print(f"    {cname:14s} {r['c']:>3} 任务 × {unit} = {cost:>6} T")
            print(f"    {'合计':14s} {'':>7}{total:>8} T")
        except Exception as e:
            print(f"  [成本核算] 跳过: {e}")

        # 2) AI 员工绩效结算 — 完成 (DONE) 任务的执行者记绩效 token
        try:
            done = conn.execute("""SELECT h.id, h.assignment_id, COALESCE(c.name, '') AS cname
                                 FROM mt_lab_task_hall h
                                 LEFT JOIN mt_lab_centers c ON c.id = h.center_id
                                 WHERE h.status='DONE' AND h.assignment_id IS NOT NULL AND h.assignment_id != ''
                                   AND h.id NOT IN (SELECT task_id FROM mt_finance_payroll WHERE task_id IS NOT NULL)
                                 LIMIT 50""").fetchall()
        except Exception:
            done = []
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_finance_payroll (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, assignee TEXT, center TEXT,
            merit_tokens INTEGER, settled_at TEXT)""")
        paid = 0
        for t in done:
            assignee = t['assignment_id']
            center = t['cname'] or ''
            base = CENTER_UNIT_BUDGET.get(center, 500)
            merit = int(base * 0.3)  # 绩效 = 单位预算 30%
            conn.execute("""INSERT INTO mt_finance_payroll (task_id, assignee, center, merit_tokens, settled_at)
                          VALUES(?,?,?,?,?)""",
                         (t['id'], assignee, center, merit, _now()))
            # 直接给执行者钱包入账 (TEXT user_id 兜底轨)
            try:
                w = conn.execute("SELECT id, balance FROM mt_token_wallets WHERE user_id=?", (assignee,)).fetchone()
                if w:
                    conn.execute("UPDATE mt_token_wallets SET balance=balance+?, updated_at=? WHERE id=?",
                                 (merit, _now(), w['id']))
                    conn.execute("""INSERT INTO mt_user_token_ledger (user_id, change, type, detail, balance_after)
                                  VALUES(?,?,?,?,?)""",
                                 (assignee, merit, 'admin_adjust',
                                  json.dumps({'reason': 'ai_merit', 'task_id': t['id'],
                                              'center': center}, ensure_ascii=False),
                                  w['balance'] + merit))
            except Exception:
                pass
            paid += 1
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_finance_settle_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tasks_billed INTEGER, merit_paid INTEGER, created_at TEXT)""")
        conn.execute("INSERT INTO mt_finance_settle_log (tasks_billed, merit_paid, created_at) VALUES(?,?,?)",
                     (len(done), paid, _now()))
        conn.commit()
        print(f"\n  [AI 绩效结算] 本次结算 {paid} 笔 (绩效 = 中心单位预算 × 30%, 已入执行者钱包)")
        print("  ✅ 结算完成留痕: mt_finance_center_cost / mt_finance_payroll / mt_finance_settle_log")
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §5 pricing — 定价/汇率快照 (CFO 审计)
# ═══════════════════════════════════════════════════════════════════

def pricing():
    conn = _conn()
    try:
        print(f"\n{'═'*62}\n  💱 财务中心 · 定价/汇率快照  ({_now()})\n{'═'*62}")
        print(f"\n  充值汇率: 1元 = {RECHARGE_RATE} Token")
        try:
            rows = conn.execute("SELECT model_id, model_weight, prompt_per_1k, completion_per_1k "
                                "FROM mt_chat_model_pricing ORDER BY model_id").fetchall()
            print("\n  [模型扣费倍数]")
            for r in rows:
                print(f"    {r['model_id']:24s} weight={r['model_weight']:<6} prompt={r['prompt_per_1k']}/1k completion={r['completion_per_1k']}/1k")
        except Exception as e:
            print(f"  [定价表] {e}")
        print("\n  (定价/汇率变更须走任务大厅 → 财务中心 → CFO 审批)")
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="💰 财务中心引擎 (第15中心)")
    p.add_argument("action", choices=["install", "report", "audit", "reconcile", "settle", "pricing", "all"])
    args = p.parse_args()
    if args.action == "install":
        install()
    elif args.action == "report":
        report()
    elif args.action == "audit":
        audit()
    elif args.action == "reconcile":
        reconcile()
    elif args.action == "settle":
        settle()
    elif args.action == "pricing":
        pricing()
    elif args.action == "all":
        install(); report(); audit(); reconcile(); settle(); pricing()
