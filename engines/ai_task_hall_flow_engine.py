#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS AI · 任务大厅全流程引擎
#  flow: mtos_hall_peacekeeper_split_dispatch_20261026
#
#  完整状态机 (10 状态):
#  ──────────────────────────────────────────────────────────────
#  NEW ──→ PEACEKEEPER_REVIEW ──→ PEACEKEEPER_APPROVED
#    (新任务)    (维和部队介入)      (维和通过)
#                                        │
#                                        ▼
#                                  KEYWORD_SPLIT
#                                  (关键字智能拆分)
#                                        │
#                                        ▼
#                                  DISPATCHED
#                                  (发配到对应中心)
#                                        │
#                                        ▼
#                                  CLAIMED ──→ IN_PROGRESS
#                                  (中心接单)    (执行中)
#                                        │           │
#                                        │           ▼
#                                        │      DELIVERED
#                                        │      (上传完成, 待审)
#                                        │           │
#                                        │           ▼
#                                        │      UNDER_REVIEW
#                                        │      (审核机构审核)
#                                        │           │
#                                        │     ┌─────┴─────┐
#                                        ▼     ▼           ▼
#                                     DONE  REJECTED   BACK_TO_CENTER
#                                  (已审核 (驳回)      (打回修改)
#                                   已结案)
#
#  失败路径:
#  NEW → PEACEKEEPER_REVIEW → PEACEKEEPER_REJECTED → VETOED
#  CLAIMED → CANCELLED (中心放弃)
#  IN_PROGRESS → CANCELLED
#
#  审核机构路由:
#  CRITICAL → 董事会 (3 人审批) + 法务过滤
#  HIGH     → 主任 + 政委 (2 人审批) + 法务过滤
#  NORMAL   → 管理员 (1 人审批)
#  LOW      → 自动通过 (deliverable 合规即可)
#
#  维和部队三层过滤:
#  1. 关键字扫描 (违禁词/敏感词/法务红线)
#  2. 紧急度评估 (priority + deadline + impact)
#  3. 合法性检查 (source + source_id + publisher_role)
# ═══════════════════════════════════════════════════════════════════

import sqlite3, json, os, re, sys, time
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJECT_ROOT, "database", "app.db")

# ═══════════════════════════════════════════════════════════════════
#  §0 常量定义
# ═══════════════════════════════════════════════════════════════════

# 10 状态 + 2 终态 (VETOED / CANCELLED)
STATUS_NEW = "NEW"
STATUS_PEACEKEEPER_REVIEW = "PEACEKEEPER_REVIEW"
STATUS_PEACEKEEPER_APPROVED = "PEACEKEEPER_APPROVED"
STATUS_PEACEKEEPER_REJECTED = "PEACEKEEPER_REJECTED"
STATUS_KEYWORD_SPLIT = "KEYWORD_SPLIT"
STATUS_DISPATCHED = "DISPATCHED"
STATUS_CLAIMED = "CLAIMED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_DELIVERED = "DELIVERED"
# === 2026-11-07 新增: 盖章 / 审计 / 复核 三流程节点 ===
STATUS_STAMPED   = "STAMPED"     # 已盖章 (DELIVERED 的输出经印章管理中心盖章确认)
STATUS_AUDITED   = "AUDITED"     # 已审计 (监察大队/审计中心审计通过)
STATUS_REVIEWED  = "REVIEWED"    # 已复核 (仙女座/专家团队最终复核结论)
# ===
STATUS_UNDER_REVIEW = "UNDER_REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_DONE = "DONE"
STATUS_REJECTED = "REJECTED"
STATUS_BACK_TO_CENTER = "BACK_TO_CENTER"
STATUS_VETOED = "VETOED"
STATUS_CANCELLED = "CANCELLED"

# 合法状态流转图 (from → [to, to, ...])
# flow_hall_p0_fix_20261026: 状态机为唯一权威, 补齐闭环合法通道 —
#   QUEUED 入厅池 / 超时回收重派 / 人工验收·返工快速通道 / 进度上报自环
# flow_hall_seal_audit_review_20261107: 新增盖章→审计→复核三节点 —
#   DELIVERED 之后, 正式走 STAMPED → AUDITED → REVIEWED → UNDER_REVIEW
#   也保留快速通道: DELIVERED → AUDITED (跳盖章, 内部类) / REVIEWED (最紧急) / UNDER_REVIEW (兼容旧流)
LEGAL_TRANSITIONS = {
    None: {STATUS_NEW},                    # 首次创建
    "QUEUED": {STATUS_NEW, STATUS_DISPATCHED, STATUS_CANCELLED, STATUS_VETOED},  # 入厅池
    STATUS_NEW: {STATUS_PEACEKEEPER_REVIEW, STATUS_VETOED},
    STATUS_PEACEKEEPER_REVIEW: {STATUS_PEACEKEEPER_APPROVED, STATUS_PEACEKEEPER_REJECTED, STATUS_VETOED},
    STATUS_PEACEKEEPER_APPROVED: {STATUS_KEYWORD_SPLIT, STATUS_VETOED},
    STATUS_PEACEKEEPER_REJECTED: {STATUS_VETOED},
    STATUS_KEYWORD_SPLIT: {STATUS_DISPATCHED, STATUS_VETOED},
    STATUS_DISPATCHED: {STATUS_CLAIMED, STATUS_VETOED},
    STATUS_CLAIMED: {STATUS_IN_PROGRESS, STATUS_DISPATCHED, STATUS_CANCELLED, STATUS_VETOED},
    STATUS_IN_PROGRESS: {STATUS_DELIVERED, STATUS_DISPATCHED, STATUS_IN_PROGRESS, STATUS_CANCELLED, STATUS_VETOED},
    # === DELIVERED 新流 ===
    STATUS_DELIVERED: {
        STATUS_STAMPED,     # 正式: 盖章 (需要印章类型匹配)
        STATUS_AUDITED,     # 快速: 跳过盖章直达审计 (内部开发/小改类)
        STATUS_REVIEWED,    # 最快: 直达复核 (仙女座特批, 最紧急)
        STATUS_UNDER_REVIEW,# 兼容旧流
        STATUS_DONE,        # 人工验收快速结案
        STATUS_IN_PROGRESS, # 人工返工
        STATUS_VETOED,
    },
    # === 新增三节点 ===
    STATUS_STAMPED: {
        STATUS_AUDITED,     # 盖章通过 → 送审计
        STATUS_BACK_TO_CENTER, # 印章类型不对 / 盖章不合格 → 退回重新交付
        STATUS_VETOED,
    },
    STATUS_AUDITED: {
        STATUS_REVIEWED,    # 审计通过 → 送复核
        STATUS_BACK_TO_CENTER, # 审计发现问题 → 退回交付中心整改
        STATUS_VETOED,
    },
    STATUS_REVIEWED: {
        STATUS_UNDER_REVIEW, # 复核通过 → 进审核池 (人工投票)
        STATUS_APPROVED,     # 仙女座最终复核通过 → 直接结案 (绕过 UNDER_REVIEW)
        STATUS_BACK_TO_CENTER,
        STATUS_VETOED,
    },
    # === 原有节点 ===
    STATUS_UNDER_REVIEW: {STATUS_APPROVED, STATUS_REJECTED, STATUS_VETOED},
    STATUS_APPROVED: {STATUS_DONE},
    STATUS_REJECTED: {STATUS_BACK_TO_CENTER, STATUS_VETOED},
    STATUS_BACK_TO_CENTER: {STATUS_IN_PROGRESS, STATUS_CANCELLED},
    STATUS_DONE: set(),
    STATUS_VETOED: set(),
    STATUS_CANCELLED: set(),
}

# 维和部队违禁词 (法务红线 + 敏感词) — flow_task_hall_peacekeeper_20261026
PEACEKEEPER_BLOCKLIST = [
    # 法务红线
    "政治敏感", "国家安全", "军事机密", "涉密信息",
    # 违规操作
    "删除数据库", "DROP TABLE", "rm -rf /", "格式化", "擦除",
    # 安全红线
    "窃取密码", "破解加密", "非法访问", "漏洞利用",
    # 法律合规
    "个人隐私", "未授权", "侵犯", "违法",
]

# 关键字 → 技能包/中心映射 (智能发配路由表)
KEYWORD_CENTER_ROUTES = [
    # 🧑‍💼 人力资源中心 (新增 20261026; 20261026b 移交培训/讲师给教育中心)
    (["招募", "hire", "雇佣", "招聘", "团队", "team", "组建", "委派", "assign",
      "专家", "教授", "expert", "professor", "hr",
      "human resource", "员工", "employee", "ai员工", "补充", "扩编", "补编",
      "maintenance", "corps", "部队", "squad", "营", "连", "军团",
      "委员会", "committee", "常委", "cadre"], "hr_people", "人力资源中心"),
    # 🏛️ 政务中心 (新增 20261026 — 人员统筹 + 统一指挥调度 + 召集开会 + 头脑风暴)
    (["政务", "统筹", "指挥", "调度", "coordinate", "dispatch", "unified", "command",
      "center_relation", "center", "跨中心", "跨团队", "协调", "政府", "govern",
      "flow", "整体", "统一派工", "统一指挥", "资源统筹",
      "召集", "开会", "meeting", "会议", "召集会议", "头脑风暴", "brainstorm",
      "经验分享", "分享", "share", "知识分享", "交流", "forum"], "gov_coordinate", "政务中心"),
    # 🎯 战略中心 (20261026 补注册 — 之前 mt_lab_centers 缺位 + 路由表缺失, 派发机制根因修复)
    (["战略", "strategy", "策略", "规划", "plan", "决策", "decision",
      "进化", "evolution", "方向", "direction", "路线图", "roadmap",
      "愿景", "vision", "战略中心", "战略规划", "系统进化", "进化调度",
      "五自", "strengthen", "awaken", "upgrade", "polish", "research",
      "意识脉冲", "consciousness", "self_evolve", "自我进化"],
     "strategy_strategize", "战略中心"),
    # 💰 财务中心 (新增 20261026 — 第15中心: Token对账/审计/成本核算/AI绩效/定价汇率)
    (["财务", "finance", "充值", "recharge", "Token", "token", "预算", "budget",
      "对账", "结算", "settle", "绩效", "payroll", "工资", "发钱", "报销",
      "成本", "cost", "定价", "汇率", "发票", "收付款", "会计", "出纳", "CFO"],
     "finance_budget", "财务中心"),
    (["安全", "漏洞", "修复", "补丁", "secure", "vuln", "fix"], "sec_ops", "安全运维中心"),
    (["AI", "模型", "推理", "训练", "ollama", "rag", "脑库"], "ai_engine", "AI引擎中心"),
    (["法律", "合规", "法务", "审计", "条例", "rule", "legal"], "legal_compliance", "法务合规中心"),
    (["前端", "UI", "页面", "css", "html", "vue", "element", "设计"], "frontend", "前端设计中心"),
    (["后端", "API", "flask", "路由", "endpoint", "数据库", "sqlite"], "backend", "后端开发中心"),
    (["Arduino", "IoT", "硬件", "传感器", "电路"], "iot_arduino", "Arduino物联网中心"),
    # 🎓 教育题库中心 (20261026 合并吸收原学习中心 — 用户指示: 学习中心=教育中心,
    #    教育中心承担 AI 再培训/入岗/换岗赋能/职称考试/课程/知识 等原学习中心全部职能)
    (["考试", "题库", "K12", "教辅", "题目", "education", "学习", "study",
      "培训", "training", "课程", "course", "入岗", "onboarding", "入职",
      "换岗", "再赋能", "reskill", "upskill", "新知识", "knowledge",
      "职称", "certification", "考级", "进修", "re-train", "ai培训", "技能提升",
      "备课", "教学", "讲解", "错题", "学情", "组卷",
      "月考", "模拟考", "摸底", "期末", "自主招生", "出题"],
     "education", "教育题库中心"),
    (["巡检", "daemon", "引擎", "守护", "自动"], "patrol", "巡检守护中心"),
    (["冰山", "仙女座", "andromeda", "iceberg", "进化", "意识"], "iceberg", "冰山仙女座中心"),
    (["防火墙", "规则", "端口", "域名", "绑定", "tunnel"], "firewall", "防火墙治理中心"),
    (["任务", "派遣", "dispatch", "合同", "外包"], "task_hall", "任务大厅中心"),
    # 💰 交易投资中心 (20261101: 仙女座沙盘推演/真实下单 → 走大厅派发链)
    (["交易", "投资", "下单", "trade", "order", "buy", "sell", "position", "持仓",
      "沙盘", "sandbox", "推演", "模拟下单", "paper trading", "模拟投资",
      "andromeda", "仙女座", "股票", "stock", "行情", "realtime",
      "sh300", "sz300", "上证", "科创板"], "trading_execution", "交易投资中心"),
]

# 优先级 → 审核机构路由
PRIORITY_REVIEW_ROUTES = {
    "CRITICAL": ("董事会", 3, "董事局主席 + 独立董事 + 法务长"),
    "HIGH":     ("主任层", 2, "项目主任 + 政法委"),
    "NORMAL":   ("管理员", 1, "系统管理员"),
    "MEDIUM":   ("管理员", 1, "系统管理员"),
    "LOW":      ("自动审核", 0, "deliverable 自动合规检查"),
    "INFO":     ("自动审核", 0, "deliverable 自动合规检查"),
}

# ═══════════════════════════════════════════════════════════════════
# §1 数据库工具
# ═══════════════════════════════════════════════════════════════════

def _conn():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _migrate_status_machine():
    """🔧 flow_hall_status_migration_20261026: 给 mt_lab_task_hall 加流程跟踪列
    现有 status 只有 DONE/VETOED → 升级为 10 状态 + 跟踪列"""
    conn = _conn()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_lab_task_hall)")]
        
        new_cols = {
            'peacekeeper_decision': 'TEXT',      # 维和部队通过/驳回
            'peacekeeper_reason': 'TEXT',         # 维和部队驳回原因
            'split_keywords': 'TEXT',             # 关键字拆分结果 (JSON)
            'split_children': 'TEXT',             # 拆分后的子任务 ID 列表 (JSON)
            'review_level': 'TEXT',               # 审核等级 (CRITICAL/HIGH/NORMAL/LOW)
            'review_committee': 'TEXT',           # 审核机构名称
            'review_votes': 'INTEGER DEFAULT 0',  # 已投票数
            'review_required': 'INTEGER DEFAULT 1',# 需投票总数
            'review_decision': 'TEXT',            # 审核机构最终决定
            'flow_node': 'TEXT',                  # 当前流程节点 (冗余=status, 用于索引)
            'flow_history': 'TEXT',               # 完整流转历史 JSON [{ts, from, to, actor, reason}]
        }
        
        for col, typ in new_cols.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE mt_lab_task_hall ADD COLUMN {col} {typ}")
                print(f"  ✅ ADD COLUMN {col}")
        
        conn.commit()
        print("  ✅ 迁移完成")
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 迁移失败: {e}")
        return False
    finally:
        conn.close()

def _create_flow_tables():
    """创建任务大厅流程专用表"""
    conn = _conn()
    try:
        # 维和部队审查记录
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_hall_peacekeeper_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            decision TEXT NOT NULL,        -- APPROVED / REJECTED
            block_reasons TEXT,            -- 命中的违禁词/理由 JSON
            urgency_score INTEGER DEFAULT 0, -- 紧急度评分 0-100
            legal_check TEXT,              -- 合法性检查 PASSED / FAILED
            reviewer TEXT DEFAULT 'AI_PEACEKEEPER',
            reviewed_at TEXT
        )""")
        
        # 关键字拆分记录
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_hall_keyword_split (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            parent_task_id INTEGER,        -- 母任务 (拆分前)
            keywords TEXT,                 -- 命中的关键字列表 JSON
            skill_id TEXT,                 -- 分配的技能包
            center_name TEXT,              -- 目标中心
            split_type TEXT DEFAULT 'KEYWORD_ROUTE', -- KEYWORD_ROUTE / MANUAL / AUTO
            confidence REAL DEFAULT 0.0,   -- 置信度 0-1
            created_at TEXT
        )""")
        
        # 中心接单记录
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_hall_center_claim (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            center_id INTEGER,
            center_name TEXT,
            claim_owner TEXT,
            claim_role TEXT,
            claimed_at TEXT,
            started_at TEXT,
            delivered_at TEXT,
            deliverable TEXT,
            quality_score REAL DEFAULT 0.0
        )""")
        
        # 审核机构投票记录
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_hall_review_vote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            voter TEXT,
            voter_role TEXT,
            vote TEXT,
            comment TEXT,
            voted_at TEXT
        )""")
        
        # 流程历史时间线
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_hall_flow_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            actor TEXT,
            reason TEXT,
            extra TEXT,
            transition_at TEXT
        )""")
        
        conn.commit()
        print("  ✅ 5 张流程表创建完成")
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 创建失败: {e}")
        return False
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §2 状态流转核心
# ═══════════════════════════════════════════════════════════════════

def transition(task_id, to_status, actor="SYSTEM", reason="", extra=None):
    """安全状态流转 — 校验合法性 + 写历史 + 更新 task"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT status, flow_history FROM mt_lab_task_hall WHERE id=?", (task_id,))
        row = cur.fetchone()
        if not row:
            return False, "任务不存在"
        
        old_status = row[0]
        flow_history = json.loads(row[1]) if row[1] else []
        
        # 校验合法性
        allowed = LEGAL_TRANSITIONS.get(old_status, {})
        if to_status not in allowed and old_status != None:
            # 允许任何状态 → VETOED / CANCELLED (人类强操作)
            if to_status not in (STATUS_VETOED, STATUS_CANCELLED):
                return False, f"非法流转: {old_status} → {to_status}"
        
        # 写历史
        flow_history.append({
            "ts": _now(),
            "from": old_status,
            "to": to_status,
            "actor": actor,
            "reason": reason,
        })
        
        conn.execute("""UPDATE mt_lab_task_hall 
                       SET status=?, updated_at=?, flow_node=?, flow_history=?
                       WHERE id=?""", 
                     (to_status, _now(), to_status, json.dumps(flow_history, ensure_ascii=False), task_id))
        
        conn.execute("""INSERT INTO mt_hall_flow_timeline 
                      (task_id, from_status, to_status, actor, reason, extra, transition_at)
                      VALUES(?,?,?,?,?,?,datetime('now','localtime'))""",
                    (task_id, old_status, to_status, actor, reason, 
                     json.dumps(extra or {}, ensure_ascii=False)))
        
        conn.commit()
        return True, f"✅ {old_status} → {to_status}"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def transition_cas(task_id, expected_status, to_status, actor="SYSTEM", reason="", extra=None):
    """🔧 flow_hall_p0_fix_20261026: CAS 安全流转 — 并发唯一赢家 + 状态机合法性校验 + 完整留痕
    蓝图/daemon 所有状态写入的统一出口 (P0-2):
      - UPDATE ... WHERE id=? AND status=expected (抢单/开工/交付 并发安全)
      - to_status 必须在 LEGAL_TRANSITIONS[old] 内 (10 状态机唯一权威)
      - 同步写 flow_history + mt_hall_flow_timeline (完整追溯)
    返回: (won, old_status, new_status, title_or_info)  — 失败时第4位为 dict(status/claim_owner)
    """
    conn = _conn()
    try:
        row = conn.execute("SELECT status, title, flow_history, claim_owner FROM mt_lab_task_hall WHERE id=?",
                           (task_id,)).fetchone()
        if not row:
            return False, None, to_status, "任务不存在"
        old = row[0]
        if expected_status and old != expected_status:
            return False, old, old, {"status": old, "claim_owner": row[3]}
        allowed = LEGAL_TRANSITIONS.get(old, set())
        if to_status != old and to_status not in allowed \
                and to_status not in (STATUS_VETOED, STATUS_CANCELLED):   # 人类强操作逃生门
            return False, old, old, {"status": old, "claim_owner": row[3],
                                     "error": f"非法流转: {old} → {to_status}"}
        hist = json.loads(row[2]) if row[2] else []
        hist.append({"ts": _now(), "from": old, "to": to_status, "actor": actor, "reason": reason})
        sets = ["status=?", "updated_at=?", "flow_node=?", "flow_history=?"]
        args = [to_status, _now(), to_status, json.dumps(hist, ensure_ascii=False)]
        for col, val in (extra or {}).items():
            sets.append(f"{col}=?")
            args.append(val)
        args += [task_id, expected_status] if expected_status else [task_id]
        cur2 = conn.execute(f"UPDATE mt_lab_task_hall SET {', '.join(sets)} WHERE id=?"
                            + (" AND status=?" if expected_status else ""), args)
        if cur2.rowcount != 1:
            conn.rollback()
            return False, old, old, {"status": old, "claim_owner": row[3]}
        conn.execute("""INSERT INTO mt_hall_flow_timeline
                      (task_id, from_status, to_status, actor, reason, extra, transition_at)
                      VALUES(?,?,?,?,?,?,datetime('now','localtime'))""",
                     (task_id, old, to_status, actor, reason,
                      json.dumps(extra or {}, ensure_ascii=False)))
        conn.commit()
        # 🏁 flow_landing_20261027: 结案(DONE)真实落地钩子 — 落地验证 + 派生备份/研究单
        # (监察大队接管) + 备案留档; 懒加载, 异常不阻断结案
        if to_status == STATUS_DONE:
            try:
                from engines.ai_task_hall_landing_engine import finalize_done_landing
                finalize_done_landing(task_id)
            except Exception as _le:
                print(f'[LANDING] ⚠️ 结案落地钩子加载失败 task={task_id}: {_le}')
        return True, old, to_status, row[1] or f"#{task_id}"
    except Exception as e:
        conn.rollback()
        return False, None, None, str(e)
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §3 保安大队 Pre-Check (三层过滤, 已拆自原维和部队)
# ═══════════════════════════════════════════════════════════════════

def peacekeeper_review(task_id):
    """🔧 保安大队审查 — 调用 ai_security_brigade_engine.brigade_full_review
    已拆分自原维和部队, 维和部队保留战场维和/冲突调解职责"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT task_type, source, hall_code FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        
        # 🔧 SANDBOX shortcut: 仙女座沙盘任务 → 跳过违禁词扫描, 直接 APPROVED
        # 理由: 沙盘是受控环境, 输入来自 Flask sandbox API, 无外网提交;
        #       且交易投资中心是内部 AI 团队, 不需要违禁词/合法性审查
        if t and (t['task_type'] in ('SANDBOX_REVIEW', 'TRADING_EXECUTION')
                  or (t['hall_code'] or '').startswith('SANDBOX_')
                  or (t['source'] or '') in ('andromeda_sandbox', 'trading_bp')):
            conn.close()
            ok, msg = transition(task_id, STATUS_PEACEKEEPER_REVIEW, "AI_SECURITY_BRIGADE", "🛡️ SANDBOX_SHORTCUT: 跳过违禁词审查 (受控环境)")
            ok2, msg2 = transition(task_id, STATUS_PEACEKEEPER_APPROVED, "AI_SECURITY_BRIGADE",
                                   "🛡️ SANDBOX_SHORTCUT: 保安大队 APPROVED (受控环境)")
            return ok2, f"🛡️ SANDBOX_SHORTCUT → {msg2}"
    finally:
        conn.close()
    
    # ── 正常审查路径 (非 sandbox 任务) ──
    try:
        import importlib.util
        brigade_path = os.path.join(PROJECT_ROOT, "engines", "ai_security_brigade_engine.py")
        spec = importlib.util.spec_from_file_location("security_brigade", brigade_path)
        brigade = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(brigade)
    except Exception as e:
        return False, f"保安大队引擎加载失败: {e}"
    
    ok, msg = brigade.brigade_full_review(task_id)
    if not ok:
        return False, msg
    
    # 从 mt_hall_peacekeeper_review 读取保安大队的决策
    conn = _conn()
    try:
        cur = conn.execute("""SELECT decision FROM mt_hall_peacekeeper_review 
                            WHERE task_id=? ORDER BY id DESC LIMIT 1""", (task_id,))
        row = cur.fetchone()
        if not row:
            return False, "保安大队未写审查记录"
        final_decision = row[0]
        
        if final_decision == "APPROVED":
            transition(task_id, STATUS_PEACEKEEPER_REVIEW, "AI_SECURITY_BRIGADE", "保安大队介入, 3 分队并行审查")
            ok2, msg2 = transition(task_id, STATUS_PEACEKEEPER_APPROVED, "AI_SECURITY_BRIGADE", 
                                   "保安大队大队长裁决: APPROVED",
                                   {"brigade": "SECURITY_BRIGADE", "squads": ["BLOCKLIST", "URGENCY", "LEGALITY"]})
            return ok2, f"🛡️ 保安大队: {msg2}"
        else:
            transition(task_id, STATUS_PEACEKEEPER_REVIEW, "AI_SECURITY_BRIGADE", "保安大队介入, 发现违规")
            ok2, msg2 = transition(task_id, STATUS_PEACEKEEPER_REJECTED, "AI_SECURITY_BRIGADE",
                                   f"保安大队大队长裁决: REJECTED")
            transition(task_id, STATUS_VETOED, "AI_SECURITY_BRIGADE", "保安大队 VETOED")
            return ok2, f"🛡️ 保安大队 VETOED: 大队长裁决 REJECTED"
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §4 关键字智能拆分 + 中心智能发配
# ═══════════════════════════════════════════════════════════════════

def keyword_split_and_dispatch(task_id):
    """🔧 关键字智能拆分 + 发配到对应中心 (flow_task_hall_dispatch_20261026)"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            return False, "任务不存在"
        
        text = f"{t['title'] or ''} {t['description'] or ''}".lower()
        
        # ── 关键字匹配 ──
        best_match = None
        best_score = 0
        all_hits = []
        
        for keywords, skill_id, center_name in KEYWORD_CENTER_ROUTES:
            hits = [kw for kw in keywords if kw.lower() in text]
            if hits:
                all_hits.append({"keywords": hits, "skill_id": skill_id, "center": center_name})
                score = len(hits) * 10  # 每个关键字 10 分
                if score > best_score:
                    best_score = score
                    best_match = {"keywords": hits, "skill_id": skill_id, "center": center_name, "score": score}
        
        if not best_match:
            # 🔧 P2 flow_hall_p0_fix_20261026: 无匹配 → 未分配 (center_id=NULL), 等待人工/中心抢单
            #   严禁兜底到巡检守护中心 — 曾与 daemon 自动执行形成组合漏洞:
            #   无匹配任务被冒充巡检类 → 自动认领 → 占位交付 → 假 DONE
            best_match = {"keywords": [], "skill_id": "unassigned", "center": "未分配", "score": 0, "fallback": True}
        
        # ── 中心归属落地 (flow_task_hall_dispatch_20261026b: 派发必须真正落到中心) ──
        center_id = None
        try:
            c2 = conn.execute("""SELECT id FROM mt_lab_centers
                                WHERE name=? AND status='ACTIVE'
                                ORDER BY id DESC LIMIT 1""", (best_match['center'],)).fetchone()
            if c2:
                center_id = c2[0]
        except Exception:
            center_id = None

        # ── 写拆分记录 ──
        conn.execute("""INSERT INTO mt_hall_keyword_split
                      (task_id, parent_task_id, keywords, skill_id, center_name, 
                       split_type, confidence, created_at)
                      VALUES(?,?,?,?,?,?,?,?)""",
                    (task_id, task_id, 
                     json.dumps(best_match['keywords'], ensure_ascii=False),
                     best_match['skill_id'], best_match['center'],
                     "KEYWORD_ROUTE", best_match['score']/100.0, _now()))
        
        # 更新 task 列 (center_id + dispatched_at 一并落地, 派发可追溯)
        conn.execute("""UPDATE mt_lab_task_hall 
                       SET split_keywords=?, center_id=?, dispatched_at=?, updated_at=? WHERE id=?""",
                     (json.dumps(best_match, ensure_ascii=False), center_id, _now(), _now(), task_id))
        
        conn.commit()
        
        # ── 流转状态 ──
        ok1, msg1 = transition(task_id, STATUS_KEYWORD_SPLIT, "AI_DISPATCHER",
                              f"命中关键字={best_match['keywords']}",
                              best_match)
        ok2, msg2 = transition(task_id, STATUS_DISPATCHED, "AI_DISPATCHER",
                              f"发配到 {best_match['center']} (skill={best_match['skill_id']})",
                              best_match)
        
        return True, f"✅ 拆分→发配: {best_match['center']} (skill={best_match['skill_id']}, 命中={best_match['keywords']})"
        
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §5 审核机构按等级路由
# ═══════════════════════════════════════════════════════════════════

def route_review_committee(task_id):
    """🔧 按任务等级路由到对应审核机构"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            return False, "任务不存在"
        
        priority = (t['priority'] or 'NORMAL').upper()
        route = PRIORITY_REVIEW_ROUTES.get(priority, PRIORITY_REVIEW_ROUTES['NORMAL'])
        committee, required, desc = route
        
        conn.execute("""UPDATE mt_lab_task_hall 
                       SET review_level=?, review_committee=?, review_required=?, updated_at=?
                       WHERE id=?""",
                     (priority, committee, required, _now(), task_id))
        conn.commit()
        
        ok, msg = transition(task_id, STATUS_UNDER_REVIEW, "AI_REVIEW_ROUTER",
                            f"路由到 {committee} (需 {required} 票, 描述: {desc})",
                            {"priority": priority, "committee": committee, "required": required})

        # 🔧 flow_hall_p0_fix_20261026: LOW/INFO (required=0) 自动审核终审 —
        #   真实交付物 → APPROVED → DONE (状态机内合规自动结案, 替代原 daemon 直跳 DONE)
        #   占位/空交付物 → REJECTED → BACK_TO_CENTER (假交付根治)
        if ok and required == 0:
            deliv = (t['deliverable'] or "").strip()
            if deliv and "auto-completed" not in deliv:
                conn.execute("""UPDATE mt_lab_task_hall
                               SET review_decision='APPROVED', approved_at=?, approved_by='AUTO_REVIEW',
                                   done_at=?, acceptance='AUTO_ACCEPT'
                               WHERE id=?""", (_now(), _now(), task_id))
                conn.commit()
                ok1, _ = transition(task_id, STATUS_APPROVED, "AUTO_REVIEW",
                                    "LOW/INFO 自动审核: 交付物合规", {"committee": committee})
                if ok1:
                    ok2, _ = transition(task_id, STATUS_DONE, "SYSTEM", "自动审核结案")
                    return ok2, "✅ 自动审核通过结案 (交付物合规)"
                return ok1, "自动审核流转异常"
            else:
                conn.execute("""UPDATE mt_lab_task_hall
                               SET review_decision='REJECTED', reject_reason=? 
                               WHERE id=?""", ("占位/空交付物, 自动审核驳回", task_id))
                conn.commit()
                ok1, _ = transition(task_id, STATUS_REJECTED, "AUTO_REVIEW",
                                    "LOW/INFO 自动审核: 交付物不合规 (占位/空)")
                if ok1:
                    transition(task_id, STATUS_BACK_TO_CENTER, "SYSTEM", "自动驳回, 打回中心重做")
                return ok1, "🚫 自动审核驳回 (占位/空交付物)"

        return ok, f"✅ 审核路由: {committee} (需 {required} 票)"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def review_vote(task_id, voter, vote, comment=""):
    """🔧 审核机构投票 — 累计到 required 票后自动出结论"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            return False, "任务不存在"
        if t['status'] != STATUS_UNDER_REVIEW:
            return False, f"当前状态 {t['status']} 不能投票"
        
        conn.execute("""INSERT INTO mt_hall_review_vote
                      (task_id, voter, voter_role, vote, comment, voted_at)
                      VALUES(?,?,?,?,?,?)""",
                    (task_id, voter, "COMMITTEE", vote, comment, _now()))
        
        # 统计已投票数
        cur.execute("""SELECT vote, COUNT(*) as cnt FROM mt_hall_review_vote 
                      WHERE task_id=? GROUP BY vote""", (task_id,))
        vote_counts = {r[0]: r[1] for r in cur.fetchall()}
        total_votes = sum(vote_counts.values())
        approve_count = vote_counts.get("APPROVE", 0)
        required = t['review_required'] or 1
        
        conn.execute("""UPDATE mt_lab_task_hall 
                       SET review_votes=?, updated_at=? WHERE id=?""",
                     (total_votes, _now(), task_id))
        conn.commit()
        
        # 自动审核 (required=0 表示 LOW/INFO 自动通过)
        # 🔧 P1-1 flow_hall_p0_fix_20261026: required==0 必须直接走 APPROVED 分支
        #   (原 0>=1 恒 False → 自动审核任务被误判 REJECTED 打回)
        if required == 0 or total_votes >= required:
            # 结论: 自动审核 或 超过半数 APPROVE → 通过, 否则驳回
            if required == 0 or approve_count >= (total_votes / 2 if total_votes > 0 else 1):
                conn.execute("UPDATE mt_lab_task_hall SET review_decision='APPROVED', approved_at=?, approved_by=? WHERE id=?",
                            (_now(), voter, task_id))
                conn.commit()
                transition(task_id, STATUS_APPROVED, "REVIEW_COMMITTEE",
                          f"投票: {approve_count}/{total_votes} APPROVE", vote_counts)
                ok, msg = transition(task_id, STATUS_DONE, "SYSTEM", "已审核已结案", {"vote_ratio": approve_count/total_votes if total_votes else 1.0})
                return True, f"✅ 结案! {approve_count}/{total_votes} 通过"
            else:
                conn.execute("UPDATE mt_lab_task_hall SET review_decision='REJECTED', reject_reason=?, updated_at=? WHERE id=?",
                            (comment, _now(), task_id))
                conn.commit()
                transition(task_id, STATUS_REJECTED, "REVIEW_COMMITTEE",
                          f"投票: {approve_count}/{total_votes} APPROVE 不足半数", vote_counts)
                # 自动打回中心
                ok, msg = transition(task_id, STATUS_BACK_TO_CENTER, "SYSTEM", "审核驳回, 打回中心修改")
                return True, f"🔄 驳回打回! {approve_count}/{total_votes} 未过半数"
        
        return True, f"⏳ 已投 {total_votes}/{required}, 继续等待"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §6 主引擎 — 定时扫描 + 自动推进
# ═══════════════════════════════════════════════════════════════════

def run_flow(limit=20):
    """🔧 主引擎入口 — 扫描各状态待推进任务, 自动流转"""
    print(f"\n{'═'*60}")
    print(f"  MTSCOS AI · 任务大厅流程引擎 (flow_hall_20261026)")
    print(f"  时间: {_now()}")
    print(f"{'═'*60}\n")
    
    # 1. 初始化: 迁移 + 建表
    _migrate_status_machine()
    _create_flow_tables()
    
    conn = _conn()
    stats = {"new_to_review": 0, "peacekeeper_pass": 0, "split_dispatch": 0, "dispatch_claim": 0, 
             "deliver_review": 0, "review_auto": 0, "error": 0}
    
    # 2. 推进链: NEW → PEACEKEEPER_REVIEW
    # 🔧 P0-3 flow_hall_p0_fix_20261026: 重分类排除非活跃/终局/外环状态 —
    #   QUEUED(入厅池,蓝图磋商通道) PENDING(待审批) ARCHIVED(已归档) FAILED/OVERDUE/REWORK(外环标记)
    #   不得被粗暴重置为 NEW 重启流程 (曾导致 QUEUED 池任务被劫持重走维和链)
    cur = conn.execute("""SELECT id FROM mt_lab_task_hall 
                         WHERE status IS NULL OR status NOT IN 
                         ('DONE','VETOED','CANCELLED','NEW','PEACEKEEPER_REVIEW',
                          'PEACEKEEPER_APPROVED','PEACEKEEPER_REJECTED','KEYWORD_SPLIT',
                          'DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED',
                          'UNDER_REVIEW','APPROVED','REJECTED','BACK_TO_CENTER',
                          'QUEUED','PENDING','ARCHIVED','FAILED','OVERDUE','REWORK')
                         LIMIT ?""", (limit,))
    unclassified = [r[0] for r in cur.fetchall()]
    
    # 把所有旧状态(DONE/VETOED以外)统一设为 NEW 进入新流程
    for tid in unclassified:
        conn.execute("UPDATE mt_lab_task_hall SET status='NEW', updated_at=? WHERE id=?", (_now(), tid))
    conn.commit()
    if unclassified:
        print(f"  ↻ 重分类 {len(unclassified)} 条旧状态为 NEW")
    
    # 3. 扫描各状态
    stages = [
        ("NEW", STATUS_NEW, peacekeeper_review, "维和部队介入"),
        ("PEACEKEEPER_REVIEW", STATUS_PEACEKEEPER_REVIEW, None, "等待维和审查 (由上游触发)"),
        ("PEACEKEEPER_APPROVED", STATUS_PEACEKEEPER_APPROVED, keyword_split_and_dispatch, "关键字拆分+发配"),
        ("PEACEKEEPER_REJECTED", STATUS_PEACEKEEPER_REJECTED, None, "驳回待处理"),
        ("KEYWORD_SPLIT", STATUS_KEYWORD_SPLIT, None, "等待发配 (由上游触发)"),
        ("DISPATCHED", STATUS_DISPATCHED, None, "等待中心接单 (人工)"),
        ("CLAIMED", STATUS_CLAIMED, None, "等待中心开始 (人工)"),
        ("IN_PROGRESS", STATUS_IN_PROGRESS, None, "等待中心交付 (人工)"),
        ("DELIVERED", STATUS_DELIVERED, route_review_committee, "路由审核机构"),
        ("UNDER_REVIEW", STATUS_UNDER_REVIEW, None, "等待审核投票"),
        ("BACK_TO_CENTER", STATUS_BACK_TO_CENTER, None, "等待中心重修改"),
    ]
    
    for label, st, auto_fn, desc in stages:
        cur.execute("SELECT id FROM mt_lab_task_hall WHERE status=? LIMIT ?", (st, limit))
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            print(f"\n  [{label}] {len(ids)} 条 — {desc}")
            for tid in ids:
                # sandbox 任务 shortcut: DISPATCHED/CLAIMED/IN_PROGRESS 自动执行
                sandbox = _is_sandbox_task(tid)
                effective_fn = auto_fn
                if sandbox and auto_fn is None:
                    if st == STATUS_DISPATCHED or st == STATUS_CLAIMED:
                        effective_fn = _sandbox_auto_claim
                    elif st == STATUS_IN_PROGRESS:
                        effective_fn = _sandbox_auto_deliver

                if effective_fn:
                    ok, msg = effective_fn(tid)
                    print(f"    id={tid}: {'✅' if ok else '❌'} {msg}")
                    if sandbox: stats.setdefault("sandbox_auto", 0); stats["sandbox_auto"] += 1
                    if ok and "维和" in desc: stats["peacekeeper_pass"] += 1
                    elif ok and "发配" in desc: stats["split_dispatch"] += 1
                    elif ok and "审核" in desc: stats["deliver_review"] += 1
                elif sandbox:
                    print(f"    id={tid}: ⏳ sandbox 等待上游触发")
                else:
                    print(f"    id={tid}: ⏳ 等待上游触发")
    
    conn.close()
    
    print(f"\n{'─'*60}")
    print(f"  统计: 维和通过={stats['peacekeeper_pass']} 发配={stats['split_dispatch']} 路由审核={stats['deliver_review']}")
    print(f"{'═'*60}\n")


def _is_sandbox_task(task_id):
    """判断任务是否走 sandbox 自动执行链"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT task_type, hall_code, source FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            return False
        return (t[0] in ('SANDBOX_REVIEW', 'TRADING_EXECUTION')
                or (t[1] or '').startswith('SANDBOX_')
                or (t[2] or '') in ('andromeda_sandbox', 'trading_bp'))
    finally:
        conn.close()


def _sandbox_auto_claim(task_id):
    """DISPATCHED → CLAIMED (自动认领 + IN_PROGRESS 开始执行)"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT hall_code, center_id FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        center_id = t['center_id'] if t else None
        conn.close()
    except Exception:
        conn.close()
        center_id = None

    ok1, msg1 = transition(task_id, STATUS_CLAIMED, "TRADING_CENTER_AUTO",
                            f"交易投资中心自动认领 sandbox 任务",
                            {"center_id": center_id})
    ok2, msg2 = transition(task_id, STATUS_IN_PROGRESS, "TRADING_CENTER_AUTO",
                            "交易投资中心自动开始执行 sandbox 推演")
    return ok2, f"✅ 自动认领→执行 (center_id={center_id})"


def _sandbox_auto_deliver(task_id):
    """IN_PROGRESS → DELIVERED → UNDER_REVIEW (自动交付 + 路由审核)"""
    # 生成 deliverable (沙盘推演结论 JSON)
    conn = _conn()
    try:
        cur = conn.execute("SELECT hall_code, title FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        hall_code = (t['hall_code'] or '') if t else ''
        deliverable = json.dumps({
            "sandbox_execution": {
                "hall_code": hall_code,
                "execution_mode": "AUTO_BY_TRADING_CENTER",
                "actor": "交易投资中心 (auto)",
                "auto": True,
            }
        }, ensure_ascii=False)
        conn.execute("UPDATE mt_lab_task_hall SET deliverable=?, updated_at=? WHERE id=?",
                     (deliverable, _now(), task_id))
        conn.commit()
    finally:
        conn.close()

    ok1, msg1 = transition(task_id, STATUS_DELIVERED, "TRADING_CENTER_AUTO",
                            "交易投资中心自动交付: 沙盘推演完成, 进入审核")
    ok2, msg2 = transition(task_id, STATUS_UNDER_REVIEW, "REVIEW_ROUTER",
                            "沙盘任务 → LOW 级, 自动审核放行")
    # sandbox 任务 priority=80 → NORMAL 审核等级, 但用 auto 快速通道
    ok3, msg3 = transition(task_id, STATUS_APPROVED, "REVIEW_COMMITTEE",
                            "LOW 优先级 → 自动审核通过 (deliverable 合规)")
    ok4, msg4 = transition(task_id, STATUS_DONE, "SYSTEM_AUTO",
                            "交易投资中心 sandbox 任务自动结案 DONE ✅")
    return ok4, f"✅ 自动交付→审核→结案"


def show_flow(task_id):
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t:
            print(f"❌ 任务 {task_id} 不存在")
            return
        
        print(f"\n{'═'*60}")
        print(f"  任务 #{task_id}: {t['title'] or '(无标题)'}")
        print(f"  状态: {t['status']}  |  优先级: {t['priority']}")
        print(f"  来源: {t['source']}/{t['source_id']}  |  发布: {t['publisher']}")
        print(f"{'═'*60}")
        
        history = json.loads(t['flow_history'] or '[]')
        if history:
            print(f"\n  📜 流转历史 ({len(history)} 步):")
            for i, step in enumerate(history):
                print(f"    {i+1:>2}. [{step['ts']}] {step['from']} → {step['to']}  ({step['actor']})")
                if step.get('reason'):
                    print(f"       └─ {step['reason']}")
        else:
            print(f"\n  📜 无流转历史 (旧数据未迁移)")
        
        # 查关联表
        for tbl, label in [("mt_hall_peacekeeper_review", "🛡️ 维和部队"),
                           ("mt_hall_keyword_split", "🔑 关键字拆分"),
                           ("mt_hall_review_vote", "🗳️ 审核投票")]:
            cur.execute(f"SELECT * FROM {tbl} WHERE task_id=? ORDER BY id DESC LIMIT 5", (task_id,))
            rows = cur.fetchall()
            if rows:
                print(f"\n  {label} ({len(rows)} 条):")
                for r in rows:
                    print(f"    #{r['id']} {dict(r)}")
        
        print()
    finally:
        conn.close()

def show_stats():
    """任务大厅全景统计"""
    conn = _conn()
    try:
        print(f"\n{'═'*60}")
        print(f"  MTSCOS AI · 任务大厅全景")
        print(f"  时间: {_now()}")
        print(f"{'═'*60}")
        
        cur = conn.execute("SELECT status, COUNT(*) FROM mt_lab_task_hall GROUP BY status ORDER BY COUNT(*) DESC")
        rows = cur.fetchall()
        total = sum(r[1] for r in rows)
        
        print(f"\n  总任务数: {total}")
        print(f"\n  📊 状态分布 (10 状态机):")
        emoji_map = {
            "NEW": "🆕", "PEACEKEEPER_REVIEW": "🛡️", "PEACEKEEPER_APPROVED": "✅",
            "PEACEKEEPER_REJECTED": "❌", "KEYWORD_SPLIT": "🔑", "DISPATCHED": "📤",
            "CLAIMED": "🤝", "IN_PROGRESS": "⚙️", "DELIVERED": "📦",
            "UNDER_REVIEW": "🔍", "APPROVED": "🎯", "DONE": "🏁",
            "REJECTED": "❌", "BACK_TO_CENTER": "🔄", "VETOED": "🚫", "CANCELLED": "🛑",
        }
        for st, cnt in rows:
            emoji = emoji_map.get(st, "❓")
            pct = cnt/total*100 if total else 0
            print(f"    {emoji} {st:25s} {cnt:>5} 条  ({pct:5.1f}%)")
        
        # 各流程表记录数
        for tbl, label in [("mt_hall_peacekeeper_review", "🛡️ 维和记录"),
                           ("mt_hall_keyword_split", "🔑 拆分记录"),
                           ("mt_hall_review_vote", "🗳️ 投票记录"),
                           ("mt_hall_flow_timeline", "📜 流转历史")]:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            cnt = cur.fetchone()[0]
            print(f"    {label:20s} {cnt:>5} 条")
        
        print()
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════
# §8 人力资源中心 (🧑‍💼 AI员工招募 + 专家委派 + 团队组建)
# ═══════════════════════════════════════════════════════════════════

def match_candidates(task_id, top_n=5):
    """🧑‍💼 人力资源: 根据任务技能需求匹配 AI 员工候选人
    查 ai_employees 表按 skill_tags / role / committee_role 匹配"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (task_id,))
        t = cur.fetchone()
        if not t: return False, "任务不存在"
        
        text = f"{t['title'] or ''} {t['description'] or ''}".lower()
        
        # 从任务关键字推断所需技能
        needed_skills = []
        for keywords, skill_id, center in KEYWORD_CENTER_ROUTES:
            if any(kw.lower() in text for kw in keywords):
                needed_skills.append(skill_id)
        
        # 查 ai_employees 匹配候选人
        skill_col = None
        for col in ("skill_tags", "specialty", "expertise", "role"):
            try:
                conn.execute(f"SELECT {col} FROM ai_employees LIMIT 1")
                skill_col = col
                break
            except: continue
        
        if not skill_col:
            return False, "ai_employees 无技能列"
        
        candidates = []
        cur = conn.execute(f"SELECT id, name, {skill_col}, level, committee_role, role FROM ai_employees WHERE status='ACTIVE' LIMIT 500")
        for emp in cur.fetchall():
            emp_text = f"{emp['name'] or ''} {emp[skill_col] or ''} {emp['committee_role'] or ''} {emp['role'] or ''}".lower()
            score = sum(1 for sk in needed_skills if sk.lower() in emp_text) * 20 + (emp['level'] or 0) * 5
            if score > 0:
                candidates.append({"id": emp['id'], "name": emp['name'], "level": emp['level'],
                                   "role": emp['role'], "score": score, "skills": needed_skills})
        
        candidates.sort(key=lambda x: -x['score'])
        top = candidates[:top_n]
        
        # 写 HR 推荐到任务
        conn.execute("UPDATE mt_lab_task_hall SET hr_candidates=?, updated_at=? WHERE id=?",
                    (json.dumps(top, ensure_ascii=False), _now(), task_id))
        conn.commit()
        
        if top:
            names = [f"{c['name']}(L{c['level']},score={c['score']})" for c in top]
            return True, f"🧑‍💼 推荐候选人: {', '.join(names)}"
        return True, "🧑‍💼 无匹配候选人"
    finally:
        conn.close()

def form_expert_team(task_id, min_members=3):
    """🧑‍💼 人力资源: 组建专家团队 — 教授 + 讲师 + AI员工 搭配"""
    conn = _conn()
    try:
        cur = conn.execute("SELECT hr_candidates FROM mt_lab_task_hall WHERE id=?", (task_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return False, "无候选人数据, 先跑 match_candidates"
        
        candidates = json.loads(row[0])
        if len(candidates) < min_members:
            return False, f"候选人不足 {min_members} 人 (只有 {len(candidates)})"
        
        # 团队组建: Top 候选人 → 团队成员
        team = {
            "team_leader": candidates[0]["name"],
            "members": [c["name"] for c in candidates[1:min_members]],
            "total": min(len(candidates), min_members),
            "formed_at": _now(),
            "task_id": task_id,
        }
        
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_hall_hr_team (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            team_json TEXT,
            status TEXT DEFAULT 'FORMED',
            created_at TEXT
        )""")
        conn.execute("INSERT INTO mt_hall_hr_team (task_id, team_json, status, created_at) VALUES(?,?,?,?)",
                    (task_id, json.dumps(team, ensure_ascii=False), "FORMED", _now()))
        
        conn.execute("UPDATE mt_lab_task_hall SET hr_team=?, updated_at=? WHERE id=?",
                    (json.dumps(team, ensure_ascii=False), _now(), task_id))
        conn.commit()
        
        return True, f"✅ 团队组建完成: Leader={team['team_leader']} + {len(team['members'])} 名成员"
    finally:
        conn.close()

def hr_dispatch_bundle(task_id):
    """🧑‍💼 人力资源: 一键发配包 — 匹配候选人 + 组建团队 + 写推荐到任务"""
    ok1, msg1 = match_candidates(task_id)
    if ok1:
        ok2, msg2 = form_expert_team(task_id)
        return ok2, f"{msg1} → {msg2}"
    return ok1, msg1

# ═══════════════════════════════════════════════════════════════════
# §7 CLI 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="任务大厅全流程引擎")
    p.add_argument("action", choices=["run", "show", "stats", "migrate", "hr"])
    p.add_argument("--task", type=int, help="任务 ID (show/hr 用)")
    p.add_argument("--limit", type=int, default=20, help="每阶段扫描上限")
    p.add_argument("--top", type=int, default=5, help="HR 推荐候选人数")
    args = p.parse_args()
    
    if args.action == "run":
        run_flow(args.limit)
    elif args.action == "show":
        show_flow(args.task)
    elif args.action == "stats":
        show_stats()
    elif args.action == "migrate":
        _migrate_status_machine()
        _create_flow_tables()
        print("✅ 迁移完成")
    elif args.action == "hr":
        if not args.task:
            print("❌ 需要 --task <id>")
        else:
            ok, msg = hr_dispatch_bundle(args.task)
            print(f"{'✅' if ok else '❌'} {msg}")
