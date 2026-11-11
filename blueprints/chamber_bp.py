#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ GOBELIN 会议厅 v2 — 日复盘专用
====================================
全新升级:
  ✅ 仙女座人性化转义 (_humanize 字典)
  ✅ 7 个独立子页面路由 (可跳转 + 可返回)
  ✅ 每个页面都有 ← 返回会议厅 + 🚪 退出登录
  ✅ 后端 _humanize() 把原始 DB 字段翻译成人话
"""
import os, sqlite3, json, time, hashlib
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, abort

chamber_bp = Blueprint('chamber_bp', __name__, url_prefix='/api/chamber')

# ═══ 仙女座人性化词典 ═══
# 原始 DB 字段 → 自然中文描述 (前端直接显示)

ROLE_HUMAN = {
    # 高层
    'super_admin': '👑 超级管理员',
    'admin': '👑 管理员',
    'ADMIN': '👑 管理员',
    'SYSTEM': '🤖 系统自动',
    'system': '🤖 系统自动',
    'auto': '🤖 自动引擎',
    'AUTO': '🤖 自动引擎',
    'user': '👤 普通用户',
    'wuchenghao15': '👤 吴成昊',
    'wuchenghao': '👤 吴成昊',
    
    # AI 会议层 (自动会议厅)
    'finance_committee': '🏛️ 金融委员会常委',
    'board': '👑 高层委员会',
    'roundtable': '🎯 圆桌会议',
    'trading_desk': '📈 操盘部',
    'ai_staff': '🧠 AI 员工 + 专家',
    'loss_rescue': '🚨 亏损挽救组',
    'professor_rotation': '👨‍🏫 教授/准驾轮岗',
    'DAILY_REVIEW': '📅 日复盘',
    
    # 引擎/系统角色
    'event_router': '🔀 事件路由器',
    'test_awakening': '🧪 测试觉醒',
    'test_student': '🎓 测试学员',
    'test_teacher': '👨‍🏫 测试教师',
    'student': '🎓 学员',
    'teacher': '👨‍🏫 教师',
    'hall_ingest': '🏛️ 大厅接入',
    'patrol': '🛡️ 巡逻队',
    'system_daemon': '👻 守护进程',
    'center_synergy_loop': '🔗 中心协同循环',
    'synergy_review': '🔗 协同复盘',
    'brainstorm_engine': '💡 头脑风暴引擎',
    'gap_scanner': '🔍 缺口扫描器',
    'neural_engine': '🧠 神经引擎',
    'backlog_intel': '📦 积压情报',
    'pulse_predictor': '💓 脉冲预测器',
    'evolution_driven': '🧬 演进驱动',
    'daemon_ai_synergy': '👻 AI 守护协同',
    'upgrade_gap_scan': '🔧 升级缺口扫描',
    'iceberg_proposal': '🧊 冰山提案',
    'iceberg_gap_scan': '🧊 冰山缺口扫描',
    'center_auto': '🏢 中心自主',
    'sandbox': '🏛️ 沙盘引擎',
    'sandbox_test': '🧪 沙盘测试',
    'SA_SYSTEM': '🛡️ SA 防御系统',
    'MONITOR': '👁️ 监控',
    'AI_COMMUNITY': '🤖 AI 社区',
    'center_synergy_loop': '🔗 中心协同循环',
    'COORDINATOR': '📋 协调员',
    'HR': '🧑‍💼 人力',
    'UNKNOWN': '❓ 未知',
    'None': '—',
}

VERDICT_HUMAN = {
    # 状态
    'QUEUED': '📥 排队中',
    'DISPATCHED': '📤 已分派',
    'CLAIMED': '📌 已领取',
    'IN_PROGRESS': '🔄 执行中',
    'PENDING': '⏳ 待处理',
    'UNDER_REVIEW': '🔍 评审中',
    'DRAFT': '📝 草稿',
    
    # 结案
    'DONE': '✅ 完成结案',
    'COMPLETED': '✅ 完成',
    'DONE_ABSORB': '✅ 结案吸收',
    'FEATURE_COMPLETE': '✅ 功能完成',
    'API_COMPLETE': '✅ API 完成',
    'CLOSURE': '✅ 闭环',
    'CLOSURE_MAIN': '✅ 主闭环',
    'AUTO_DONE': '🤖 自动结案',
    
    # 否决/驳回/失败
    'VETOED': '🛑 铁律否决',
    'REJECTED': '❌ 被驳回',
    'FAILED': '💔 失败',
    'CANCELLED': '🚫 已取消',
}

SEVERITY_HUMAN = {
    'CRITICAL': '🔴 紧急',
    'BLOCKED': '🔴 拦截',
    'ALERT': '🟠 预警',
    'WARN': '🟡 警告',
    'MEDIUM': '🟡 中等',
    'HIGH': '🟠 高风险',
    'LOW': '🟢 低风险',
    'INFO': '🔵 信息',
}

EVENT_HUMAN = {
    # 金盾/铁律
    'SHIELD_PERMISSION_BLOCK': '🛡️ 金盾拦截了一个危险操作 (铁律命中)',
    'SHIELD_PERMISSION_ALLOW': '✅ 金盾放行',
    'SHIELD_EVENT_SUMMARY': '📊 金盾事件汇总',
    'SHIELD_RETRO_VETO': '🔍 金盾事后否决',
    'IRON_BLOCKED': '🛑 铁律 8 条直接命中 — 禁止放行',
    'FORCE_GATE_NO_SUCH_HALL': '🚧 强制入厅门控拦截 — 没有对应的大厅任务',
    
    # 大厅治理
    'HALL_PROPOSAL_SUBMIT': '📝 新提案进入大厅',
    'HALL_PROPOSAL_NO_AUTH': '⚠️ 匿名提案被降级为普通用户',
    'HALL_PROPOSAL_APPROVED': '✅ 提案审批通过',
    'HALL_ANOMALY_AUDIT': '🔍 大厅异常审计',
    'HALL_ANOMALY_APPROVAL_BYPASS': '⚠️ 大厅异常审计 · 审批绕过',
    'HALL_ANOMALY_FAKE_DONE': '⚠️ 大厅异常审计 · 假结案',
    'HALL_ANOMALY_SPAM': '⚠️ 大厅异常审计 · 批量刷屏',
    'HALL_ANOMALY_SUSPICIOUS_ROLE': '⚠️ 大厅异常审计 · 可疑角色',
    'HALL_HEALTH_EXAM': '🏥 大厅健康体检',
    'HALL_RETRO_IRON_BLOCKED': '🔍 事后审计发现历史提案被铁律拦截',
    'HALL_RETRO_NEED_APPROVAL': '🔍 事后审计 · 待审批',
    'HALL_RETRO_PASSED': '🔍 事后审计 · 已通过',
    'HALL_RETRO_PASSED_HIGH': '🔍 事后审计 · 高优先级已通过',
    
    # 自动会议厅
    'AUTO_MEETING_TRIGGER': '🏛️ 自动会议厅触发',
    
    # 中心/引擎
    'CENTER_ACCESS_GET': '🏢 中心访问日志 (例行审计)',
    'CENTER_ACCESS_POST': '🏢 中心访问',
    'CENTER_ACTION_POST': '🏢 中心执行了一个动作',
    'CENTER_ACCESS': '🏢 中心访问',
    'ANDROMEDA_SESSION': '🧊 仙女座会话',
    
    # 协作总线
    'MARKET_ANOMALY': '📡 市场异动雷达',
    'CRITICAL_ALERT': '🚨 紧急预警',
    'VERSION_CHANGE': '🔄 版本变更通知',
    'SKILL_REPORT_READY': '📊 Skill 报告就绪',
    'SANDBOX_REVIEW': '🏛️ 沙盘复盘事件',
    'MEETING_SUMMARY': '🏛️ 会议厅决议广播',
    
    # 其他
    'HTTP_POST': '🌐 HTTP 请求',
    'CUSTOMS_CHECK': '🛃 海关检查',
    'COMFY_SUBMIT': '🎨 ComfyUI 提交',
    'INSIGHT': '💡 AI 洞察',
    'TEST': '🧪 测试事件',
}

CENTER_HUMAN = {
    'daemon_ops': '🛠️ 部署运维中心',
    'dev_flow': '💻 开发流程中心',
    'frontend_design': '🎨 前端设计中心',
    'trading_execution': '📈 交易执行中心',
    'data_research': '📊 数据研究中心',
    'security_audit': '🔒 安全审计中心',
    'legal': '⚖️ 法务合规中心',
    'rules_gov': '📜 规则治理中心',
    'vuln_fix': '🐛 漏洞修复中心',
    'upgrade_evolution': '🧬 升级演进中心',
    'skill_dev': '🧠 Skill 研发中心',
    'sync_center': '🌐 仙女座同步中心',
    'expert_team': '👨‍🔬 专家团队中心',
    'strategy_center': '🎯 战略中心',
    'supervision_brigade': '👮 监察大队',
    'backup': '💾 数据备份中心',
    'archive_hall': '📚 历史档案中心',
    'edu_qbank': '📝 教育题库中心',
    'hr_center': '🧑‍💼 人力调配中心',
    'medical': '🏥 健康体检中心',
    'language': '🌐 语言教学中心',
    'math': '📐 数学教学中心',
    'exam': '📝 考试自动中心',
    'disaster': '🚨 灾备恢复中心',
    'threat': '🕵️ 威胁情报中心',
    'collab': '🚌 协同总线中心',
    'whitehat': '🕵️ 白帽悬赏中心',
    'workflow': '⚙️ 工作流中心',
    'ai_engine': '🤖 AI 引擎中心',
    'comfy': '🎨 ComfyUI 图像中心',
    'marketing': '📣 营销中心',
    'sandbox_ops': '🏛️ 沙盘运营',
    'finance_committee': '🏛️ 金融委员会',
}

TASK_TYPE_HUMAN = {
    # 自动会议厅
    'AUTO_MEETING_SUMMARY': '🏛️ 自动会议厅 · 闭环总任务',
    'AUTO_MEETING_ACTION': '🏛️ 自动会议厅 · 执行人子任务',
    
    # 沙盘/交易
    'SANDBOX_REVIEW': '🏛️ 沙盘复盘提案',
    'MARKET_REVIEW': '📊 市场分析报告',
    'ANALYST_REPORT': '📊 分析师报告',
    'REPORT_REVIEW': '📊 报告复盘',
    
    # 原有类型
    'SECURITY': '🔒 安全类提案',
    'ANALYSIS': '📊 分析类提案',
    'OPERATION': '⚙️ 运营类提案',
    'MAINTENANCE': '🛠️ 维护类提案',
    'INNOVATION': '💡 创新类提案',
    'DEVELOPMENT': '💻 开发类提案',
    'TRADING': '📈 交易类提案',
    'GOVERNANCE': '⚖️ 治理类提案',
    'SYNERGY': '🔗 协同类提案',
    'HALL_CORE': '🏛️ 大厅核心提案',
    'ICEBERG': '🧊 冰山提案',
    
    # 引擎/系统
    'SECURITY_INCIDENT': '🔴 安全 incident',
    'SECURITY_ENGINE': '🔒 安全引擎',
    'BRIDGE_ENGINE': '🌉 桥接引擎',
    'LEGISLATION': '📜 立法提案',
    'HR_CENTER': '🧑‍💼 人力中心任务',
    'STRATEGY_CENTER': '🎯 战略中心任务',
    'DATA_CENTER': '📊 数据中心任务',
    'GOV_CENTER': '⚖️ 治理中心任务',
    'WFLOW_CENTER': '⚙️ 工作流中心任务',
    'EDU_CENTER': '📚 教育中心任务',
    'AUTO_GATEKEEPER': '🛡️ 自动门控',
    'GOVERNANCE_RULE': '📜 治理规则',
    'CONSTITUTIONAL_RULE': '📜 宪法规则',
    
    # 研发/修复
    'BUGFIX': '🐛 Bug 修复',
    'REFACTOR': '♻️ 重构',
    'MIGRATION': '🔀 迁移',
    'BUILD': '🔨 构建',
    'DEPLOY_SYNC': '🚀 部署同步',
    'FRONTEND_DEPLOY': '🎨 前端部署',
    'DATA_ARCHITECTURE': '📊 数据架构',
    'DATA_SECURITY': '🔒 数据安全',
    'DATA_RESTORE': '💾 数据恢复',
    'DATA_ARCHIVE': '💾 数据归档',
    
    # 系统修复
    'SYSTEM_FIX': '🔧 系统修复',
    'SYSTEM_ARCHITECTURE': '🏗️ 系统架构',
    'KEEPALIVE_SKILL': '💓 Flask 保活',
    'HULK_TUNNEL': '🌐 Hulk 隧道',
    'FLASK_HANG': '🔴 Flask 挂死修复',
    'BACKUP_LAYER_FAIL': '🔴 备份层故障',
    'DISASTER_RECOVERY': '🚨 灾备恢复',
    'SELF_HEAL': '💊 自愈',
    
    # 其他
    'PROPOSAL': '📝 提案',
    'ENHANCE': '💡 增强提案',
    'REVIEW': '🔍 评审',
    'OTHER': '📌 其他',
    'test': '🧪 测试',
    'TEST': '🧪 测试',
    'DEV': '💻 开发',
    'OPS': '⚙️ 运维',
    'EDU': '📚 教育',
    'INFRA': '🏗️ 基建',
    'ARCHITECTURE': '🏗️ 架构',
    'AI_RND': '🤖 AI 研发',
    'STRATEGY': '🎯 战略',
    'GOV': '⚖️ 治理',
    'DATA': '📊 数据',
    'GENERAL': '📌 通用',
}


def _humanize(value, table=None):
    """仙女座人性化转义 — 原始值 → 自然中文"""
    if value is None:
        return '—'
    
    s = str(value)
    if s in ('None', ''):
        return '—'
    
    if table == 'role' or table == 'publisher_role' or table == 'claim_owner_role':
        return ROLE_HUMAN.get(s, s)
    if table == 'verdict':
        return VERDICT_HUMAN.get(s, s)
    if table == 'severity':
        return SEVERITY_HUMAN.get(s, s)
    if table == 'event':
        return EVENT_HUMAN.get(s, s)
    if table == 'center' or table == 'center_code':
        return CENTER_HUMAN.get(s, s)
    if table == 'task_type':
        return TASK_TYPE_HUMAN.get(s, s)
    
    # 通用: 扫描所有词典
    for d in [ROLE_HUMAN, VERDICT_HUMAN, SEVERITY_HUMAN, EVENT_HUMAN, CENTER_HUMAN, TASK_TYPE_HUMAN]:
        if s in d:
            return d[s]
    
    return s[:60] if len(s) > 60 else s


def _humanize_row(row, human_fields):
    """对一行 dict 批量做人性化"""
    for field, table in human_fields.items():
        if field in row:
            row[field] = _humanize(row[field], table)
    return row

def _db():
    conn = sqlite3.connect(os.environ['APP_DB'], timeout=10)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


# ═══ 复盘数据聚合 (带人性化转义) ═══

def _today_range():
    now = datetime.now()
    return now.strftime('%Y-%m-%d 00:00:00'), now.strftime('%Y-%m-%d 23:59:59'), now


def _gen_report():
    """生成完整日复盘报告 (全部数据经过仙女座人性化转义)"""
    conn = _db()
    cur = conn.cursor()
    start, end, now = _today_range()
    
    report = {
        "date": now.strftime('%Y-%m-%d'),
        "report_time": now.strftime('%Y-%m-%d %H:%M:%S'),
        "auto_switch": "yes" if now.hour >= 15 else "no",
        "sections": {},
    }
    
    # 中心
    cur.execute("SELECT center_code, name, domain, status FROM mt_lab_centers ORDER BY center_code")
    centers = []
    for r in cur.fetchall():
        d = dict(r)
        d['center_code_human'] = _humanize(d['center_code'], 'center')
        centers.append(d)
    report["sections"]["centers"] = centers
    
    # ═══ 持仓 + 账户 (大收盘汇总) ═══
    positions = []
    total_cost = 0.0
    total_market_val = 0.0
    total_pnl = 0.0
    try:
        # 从 mt_trade_log 计算净持仓 (加权均价, 与 tick engine 一致)
        cur.execute("""SELECT symbol, action, qty, price, fill_price, name, created_at
                       FROM mt_trade_log WHERE trade_mode='sandbox' AND action IN ('BUY','SELL')
                       ORDER BY created_at""")
        all_trades = cur.fetchall()

        pos_map = {}   # symbol -> {'qty': int, 'avg_cost': float, 'name': str}
        for r in all_trades:
            sym, action, qty, price, fill_price, name, _ = r
            exec_price = fill_price if fill_price and fill_price > 0 else price
            if action == 'BUY':
                prev = pos_map.get(sym, {'qty': 0, 'avg_cost': 0.0, 'name': name or ''})
                new_qty = prev['qty'] + qty
                new_cost = (prev['avg_cost'] * prev['qty'] + exec_price * qty) / new_qty if new_qty > 0 else exec_price
                pos_map[sym] = {'qty': new_qty, 'avg_cost': new_cost, 'name': name or prev.get('name', '')}
            else:
                if sym in pos_map:
                    pos_map[sym]['qty'] -= qty
                    if pos_map[sym]['qty'] <= 0:
                        del pos_map[sym]

        # 为每个持仓查询买入/卖出明细
        for sym, info in pos_map.items():
            qty = info['qty']
            avg_cost = info['avg_cost']

            # 最近买入: price + time
            cur.execute("""SELECT COALESCE(fill_price, price) as p, name, created_at
                           FROM mt_trade_log
                           WHERE trade_mode='sandbox' AND action='BUY' AND symbol=?
                           ORDER BY created_at DESC LIMIT 1""", (sym,))
            lb = cur.fetchone()
            last_buy_price = round(lb['p'], 2) if lb else None
            last_buy_ts = lb['created_at'][:19].replace('T', ' ') if lb else None
            stock_name = (lb['name'] if lb and lb['name'] else info['name']) or sym

            # 最近卖出
            cur.execute("""SELECT COALESCE(fill_price, price) as p, created_at
                           FROM mt_trade_log
                           WHERE trade_mode='sandbox' AND action='SELL' AND symbol=?
                           ORDER BY created_at DESC LIMIT 1""", (sym,))
            ls = cur.fetchone()
            last_sell_price = round(ls['p'], 2) if ls else None
            last_sell_ts = ls['created_at'][:19].replace('T', ' ') if ls else None

            # 平均买价 / 平均卖价
            cur.execute("""SELECT
                AVG(CASE WHEN action='BUY' THEN COALESCE(fill_price, price) END) as avg_buy,
                AVG(CASE WHEN action='SELL' THEN COALESCE(fill_price, price) END) as avg_sell,
                SUM(CASE WHEN action='BUY' THEN COALESCE(fill_price, price)*qty END) /
                NULLIF(SUM(CASE WHEN action='BUY' THEN qty END),0) as wavg_buy,
                COUNT(CASE WHEN action='BUY' THEN 1 END) as buy_cnt,
                COUNT(CASE WHEN action='SELL' THEN 1 END) as sell_cnt
                FROM mt_trade_log WHERE trade_mode='sandbox' AND symbol=?""", (sym,))
            ag = cur.fetchone()
            avg_buy_price = round(ag['wavg_buy'], 2) if ag and ag['wavg_buy'] else None
            avg_sell_price = round(ag['avg_sell'], 2) if ag and ag['avg_sell'] else None
            buy_cnt = ag['buy_cnt'] if ag else 0
            sell_cnt = ag['sell_cnt'] if ag else 0

            # 当前价 (最后成交价)
            cur.execute("""SELECT COALESCE(fill_price, price) as p FROM mt_trade_log
                           WHERE trade_mode='sandbox' AND symbol=? ORDER BY created_at DESC LIMIT 1""", (sym,))
            lp = cur.fetchone()
            cur_price = round(lp['p'], 2) if lp else round(avg_cost, 2)

            market_val = round(cur_price * qty, 2)
            pnl_pct = round((cur_price - avg_cost) / avg_cost * 100, 2) if avg_cost > 0 else 0

            positions.append({
                "symbol": sym, "name": stock_name, "qty": qty,
                "avg_cost": round(avg_cost, 2), "price": cur_price,
                "market_val": market_val, "pnl_pct": pnl_pct,
                "last_buy_price": last_buy_price, "last_buy_ts": last_buy_ts,
                "last_sell_price": last_sell_price, "last_sell_ts": last_sell_ts,
                "avg_buy_price": avg_buy_price, "avg_sell_price": avg_sell_price,
                "buy_cnt": buy_cnt, "sell_cnt": sell_cnt,
            })
            total_cost += avg_cost * qty
            total_market_val += market_val
            total_pnl += (cur_price - avg_cost) * qty

        # 按持仓市值降序
        positions.sort(key=lambda x: x['market_val'], reverse=True)
        
        # 账户资金
        cur.execute("SELECT key, value FROM mt_trade_account_state")
        state = {r["key"]: r["value"] for r in cur.fetchall()}
        initial = float(state.get("initial_capital", 10000))
        monthly = float(state.get("monthly_profit", 0))
        cash = float(state.get("cash_balance", initial - total_cost))
        
        report["sections"]["持仓汇总"] = {
            "positions": positions,
            "position_count": len(positions),
            "total_cost": round(total_cost, 2),
            "total_market_val": round(total_market_val, 2),
            "cash_balance": round(cash, 2),
            "total_equity": round(cash + total_market_val, 2),
            "initial_capital": initial,
            "monthly_profit_pct": round((cash + total_market_val - initial) / initial * 100, 2),
        }
    except Exception:
        report["sections"]["持仓汇总"] = {"positions": [], "position_count": 0}
    
    # ═══ 5 个独立会议室数据 ═══
    # 1. 📺 多媒体会议室 (FM + 视频流)
    media_meetings = []
    try:
        cur.execute("""SELECT meeting_id, meeting_type, meeting_title, substr(conclusions,1,200) as c, triggered_at
            FROM mt_sandbox_meetings WHERE meeting_type='media_intake'
            ORDER BY rowid DESC LIMIT 10""")
        for r in cur.fetchall():
            media_meetings.append({"meeting_id": r["meeting_id"], "title": r["meeting_title"],
                                    "conclusions": json.loads(r["c"]) if r["c"] else [],
                                    "time": r["triggered_at"]})
    except Exception:
        pass
    report["sections"]["多媒体会议室"] = {"meetings": media_meetings}
    
    # 2. 🌍 国际形势会议室
    global_meetings = []
    try:
        cur.execute("""SELECT meeting_id, meeting_type, meeting_title, substr(conclusions,1,200) as c, triggered_at
            FROM mt_sandbox_meetings WHERE meeting_type IN ('board','brainstorm','finance_committee')
            ORDER BY rowid DESC LIMIT 10""")
        for r in cur.fetchall():
            global_meetings.append({"meeting_id": r["meeting_id"], "title": r["meeting_title"],
                                     "conclusions": json.loads(r["c"]) if r["c"] else [],
                                     "time": r["triggered_at"]})
    except Exception:
        pass
    report["sections"]["国际形势会议室"] = {"meetings": global_meetings}
    
    # 3. 💬 操盘经验分享会
    trade_meetings = []
    try:
        cur.execute("""SELECT meeting_id, meeting_type, meeting_title, substr(conclusions,1,200) as c, triggered_at
            FROM mt_sandbox_meetings WHERE meeting_type IN ('grassroots_quick_sync','trading_desk','roundtable','simulation_divergent')
            ORDER BY rowid DESC LIMIT 15""")
        for r in cur.fetchall():
            trade_meetings.append({"meeting_id": r["meeting_id"], "title": r["meeting_title"],
                                    "conclusions": json.loads(r["c"]) if r["c"] else [],
                                    "time": r["triggered_at"]})
    except Exception:
        pass
    report["sections"]["操盘经验分享会"] = {"meetings": trade_meetings}
    
    # 4. 🚨 异常及灾难应急会议室
    emergency_meetings = []
    try:
        cur.execute("""SELECT meeting_id, meeting_type, meeting_title, substr(conclusions,1,200) as c, triggered_at
            FROM mt_sandbox_meetings WHERE meeting_type IN ('loss_rescue')
            ORDER BY rowid DESC LIMIT 8""")
        for r in cur.fetchall():
            emergency_meetings.append({"meeting_id": r["meeting_id"], "title": r["meeting_title"],
                                        "conclusions": json.loads(r["c"]) if r["c"] else [],
                                        "time": r["triggered_at"]})
    except Exception:
        pass
    # + 今日高严重度金盾事件
    shield_crit = []
    try:
        cur.execute("""SELECT event_type_human, severity_human, target_force, created_at
            FROM (SELECT event_type_human, severity_human, target_force, created_at
                  FROM mt_shield_events WHERE date(created_at)=date('now','localtime') AND severity IN ('CRITICAL','BLOCKED'))""")
        for r in cur.fetchall():
            shield_crit.append({"event": r["event_type_human"], "severity": r["severity_human"],
                                "target": r["target_force"], "time": r["created_at"]})
    except Exception:
        pass
    report["sections"]["应急会议室"] = {"meetings": emergency_meetings, "shield_events": shield_crit}
    
    # AI 参与者
    cur.execute("""SELECT DISTINCT publisher, publisher_role, claim_owner_role 
        FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=? LIMIT 30""", (start, end))
    players = []
    for r in cur.fetchall():
        d = dict(r)
        d['publisher_role_human'] = _humanize(d['publisher_role'], 'role')
        d['claim_owner_role_human'] = _humanize(d['claim_owner_role'], 'role')
        players.append(d)
    report["sections"]["ai_players"] = players
    
    # 金盾事件
    cur.execute("""SELECT event_type, source_force, target_force, severity, created_at
        FROM mt_shield_events WHERE created_at>=? AND created_at<=?
        ORDER BY severity DESC, id DESC LIMIT 100""", (start, end))
    events = []
    for r in cur.fetchall():
        d = dict(r)
        d['event_type_human'] = _humanize(d['event_type'], 'event')
        d['severity_human'] = _humanize(d['severity'], 'severity')
        events.append(d)
    report["sections"]["events_today"] = events
    
    # 1. 经验共享
    cur.execute("SELECT COUNT(*) FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=?", (start, end))
    total_hall = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=? AND verdict='DONE'", (start, end))
    done_hall = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=? AND verdict='VETOED'", (start, end))
    veto_hall = cur.fetchone()[0]
    
    cur.execute("""SELECT task_type, publisher_role, COUNT(*) as cnt
        FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=?
        GROUP BY task_type, publisher_role ORDER BY cnt DESC LIMIT 20""", (start, end))
    breakdown = []
    for r in cur.fetchall():
        d = dict(r)
        d['task_type_human'] = _humanize(d['task_type'], 'task_type')
        d['publisher_role_human'] = _humanize(d['publisher_role'], 'role')
        breakdown.append(d)
    
    report["sections"]["经验共享"] = {
        "total_proposals": total_hall,
        "done": done_hall,
        "vetoed": veto_hall,
        "success_rate": f"{done_hall/total_hall*100:.1f}%" if total_hall else "0.0%",
        "breakdown": breakdown,
    }
    
    # 2. 失败案例
    cur.execute("""SELECT id, title, publisher_role, verdict, peacekeeper_decision,
               peacekeeper_reason, datetime(created_at) as created_at
        FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=?
          AND (verdict IN ('VETOED','REJECTED','FAILED') OR peacekeeper_decision IN ('VETOED','REJECTED'))
        ORDER BY id DESC LIMIT 20""", (start, end))
    failures = []
    for r in cur.fetchall():
        d = dict(r)
        d['publisher_role_human'] = _humanize(d['publisher_role'], 'role')
        d['verdict_human'] = _humanize(d['verdict'], 'verdict')
        d['peacekeeper_decision_human'] = _humanize(d['peacekeeper_decision'], 'verdict')
        failures.append(d)
    
    cur.execute("""SELECT event_type, source_force, target_force, severity, created_at
        FROM mt_shield_events WHERE created_at>=? AND created_at<=? AND severity IN ('BLOCKED','CRITICAL')
        ORDER BY id DESC LIMIT 20""", (start, end))
    blocked = []
    for r in cur.fetchall():
        d = dict(r)
        d['event_type_human'] = _humanize(d['event_type'], 'event')
        d['severity_human'] = _humanize(d['severity'], 'severity')
        blocked.append(d)
    
    report["sections"]["失败案例分析"] = {"hall_failures": failures, "shield_blocks": blocked}
    
    # 3. 紧急预案
    cur.execute("""SELECT event_type, source_force, target_force, severity, created_at
        FROM mt_shield_events WHERE created_at>=? AND created_at<=?
          AND (severity IN ('CRITICAL','BLOCKED') OR event_type LIKE '%EMERGENCY%')
        ORDER BY severity DESC LIMIT 20""", (start, end))
    emergencies = []
    for r in cur.fetchall():
        d = dict(r)
        d['event_type_human'] = _humanize(d['event_type'], 'event')
        d['severity_human'] = _humanize(d['severity'], 'severity')
        d['plan'] = _make_plan(d['event_type'])
        emergencies.append(d)
    report["sections"]["紧急事件预案"] = {"count": len(emergencies), "items": emergencies}
    
    # 4. 中心联动
    cur.execute("""SELECT publisher_role, publisher, COUNT(*) as cnt,
               GROUP_CONCAT(DISTINCT center_id) as centers_hit
        FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=? AND center_id IS NOT NULL
        GROUP BY publisher_role, publisher ORDER BY cnt DESC LIMIT 15""", (start, end))
    synergies = []
    for r in cur.fetchall():
        d = dict(r)
        d['publisher_role_human'] = _humanize(d['publisher_role'], 'role')
        centers_list = (d['centers_hit'] or '').split(',')
        d['centers_hit_human'] = '、'.join([_humanize(c.strip(), 'center') for c in centers_list if c.strip()])
        synergies.append(d)
    report["sections"]["中心联动分析"] = synergies
    
    # 5. 高层决策
    cur.execute("""SELECT id, title, publisher, publisher_role, verdict, progress,
               datetime(created_at) as created_at
        FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=?
          AND publisher_role IN ('super_admin','admin')
        ORDER BY id DESC LIMIT 15""", (start, end))
    decisions = []
    for r in cur.fetchall():
        d = dict(r)
        d['publisher_role_human'] = _humanize(d['publisher_role'], 'role')
        d['verdict_human'] = _humanize(d['verdict'], 'verdict')
        decisions.append(d)
    report["sections"]["高层决策"] = decisions
    
    # 6. 中层任务
    cur.execute("""SELECT id, title, claim_owner, claim_owner_role, verdict, center_id,
               datetime(claimed_at) as claimed_at
        FROM mt_lab_task_hall WHERE created_at>=? AND created_at<=?
          AND claim_owner_role NOT IN ('super_admin','admin') AND claim_owner IS NOT NULL
        ORDER BY id DESC LIMIT 15""", (start, end))
    mid_tasks = []
    for r in cur.fetchall():
        d = dict(r)
        d['claim_owner_role_human'] = _humanize(d['claim_owner_role'], 'role')
        d['verdict_human'] = _humanize(d['verdict'], 'verdict')
        d['center_id_human'] = _humanize(d['center_id'], 'center')
        mid_tasks.append(d)
    report["sections"]["中层任务"] = mid_tasks
    
    # 7. 基层贡献
    cur.execute("""SELECT publisher, COUNT(*) as cnt FROM mt_lab_task_hall
        WHERE created_at>=? AND created_at<=? AND publisher_role NOT IN ('super_admin','admin','system','auto','AUTO')
        GROUP BY publisher ORDER BY cnt DESC LIMIT 15""", (start, end))
    grassroots = []
    for r in cur.fetchall():
        d = dict(r)
        d['publisher_human'] = _humanize(d['publisher'], 'role')
        grassroots.append(d)
    
    cur.execute("""SELECT d.speaker, d.role, COUNT(*) as votes
        FROM mt_lab_deliberations d JOIN mt_lab_task_hall t ON d.assignment_id=t.id
        WHERE t.created_at>=? AND t.created_at<=?
        GROUP BY d.speaker, d.role ORDER BY votes DESC LIMIT 15""", (start, end))
    deliberators = []
    for r in cur.fetchall():
        d = dict(r)
        d['role_human'] = _humanize(d['role'], 'role')
        deliberators.append(d)
    
    report["sections"]["基层贡献"] = {
        "top_publishers": grassroots,
        "top_deliberators": deliberators,
    }
    
    conn.close()
    return report


def _make_plan(event_type):
    plans = {
        "SHIELD_PERMISSION_BLOCK": "🛑 立即复盘拦截原因 → 更新铁律规则 → 通知相关中心",
        "IRON_BLOCKED": "🛑 铁律拦截 → 禁止放行 → 纪律委员会介入 → 全中心通报",
        "HALL_RETRO_IRON_BLOCKED": "🔍 事后审计 → 标记 VETO → 归档备查",
        "CENTER_ACCESS_GET": "🔍 例行审计 → 记录 feed → 确认无异常",
    }
    for k, v in plans.items():
        if k in event_type:
            return v
    return "⚠️ 通用预案: 记录 → 通知 → 隔离 → 复盘 → 改进"


def _feed_brain(report):
    flow_id = f"CHAMBER-{report['date']}"
    conn = _db()
    cur = conn.cursor()
    
    e = report['sections']['经验共享']
    f = report['sections']['失败案例分析']
    em = report['sections']['紧急事件预案']
    
    summary = f"""🏛️ 会议厅日复盘 {report['date']}

📊 大厅: {e['total_proposals']} 条提案, 完成 {e['done']} ({e['success_rate']}), 铁律否决 {e['vetoed']}
❌ 失败: Hall {len(f['hall_failures'])} 条 + Shield 拦截 {len(f['shield_blocks'])} 次
🚨 紧急事件: {em['count']} 起
🔗 中心联动: {len(report['sections']['中心联动分析'])} 组
👑 高层决策: {len(report['sections']['高层决策'])} 条
📋 中层分派: {len(report['sections']['中层任务'])} 条
🏢 活跃中心: {len(report['sections']['centers'])} 个
🤖 AI 参与者: {len(report['sections']['ai_players'])} 种

flow_id: {flow_id}
"""
    
    cur.execute("""INSERT INTO mt_ai_brain_feed_log
        (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_at, fed_by)
        VALUES (?,?,?,?,?,datetime('now','localtime'),?)""",
        (flow_id, "chamber", "CHAMBER_DAILY_REVIEW",
         summary[:4000], json.dumps({"date": report['date']}, ensure_ascii=False)[:500],
         "chamber_bp"))
    
    cur.execute("""INSERT INTO mt_sandbox_meetings
        (meeting_type, meeting_title, triggered_at, participants, agenda, conclusions, actions)
        VALUES (?,?,?, ?, ?, ?, ?)""",
        ("DAILY_REVIEW", f"🏛️ 会议厅日复盘 {report['date']}",
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
         json.dumps([c['center_code'] for c in report['sections']['centers']], ensure_ascii=False),
         json.dumps(list(report['sections'].keys()), ensure_ascii=False),
         summary[:2000],
         json.dumps({"flow_id": flow_id}, ensure_ascii=False)))
    
    conn.commit()
    conn.close()
    return flow_id


# ═══ API 端点 ═══

@chamber_bp.route('/report', methods=['GET'])
def daily_report():
    report = _gen_report()
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mt_sandbox_meetings WHERE meeting_type='DAILY_REVIEW' AND meeting_title LIKE ?",
                (f"%{report['date']}%",))
    already = cur.fetchone()[0] > 0
    conn.close()
    flow_id = None if already else _feed_brain(report)
    report["archived"] = already
    report["flow_id"] = flow_id
    return jsonify({"ok": True, "report": report})


@chamber_bp.route('/meeting/archive', methods=['POST'])
def archive_meeting():
    report = _gen_report()
    return jsonify({"ok": True, "flow_id": _feed_brain(report), "date": report['date']})


# ═══ 会议厅前端页面 (7 个独立子页面 + 统一布局) ═══

CHAMBER_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--g:#ffd700;--bg:#0a0a1a;--bg2:#1a1a3a;--bg3:#2a2a5a;--txt:#e0e0ff;--dim:#8888aa;--red:#ff4444;--green:#44ff44;--blue:#4488ff}
body{background:var(--bg);color:var(--txt);font-family:-apple-system,"PingFang SC",sans-serif;min-height:100vh}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:18px 40px;background:linear-gradient(180deg,var(--bg2),var(--bg));border-bottom:2px solid var(--g)}
.topbar h1{font-size:22px;background:linear-gradient(90deg,var(--g),#ffed4a);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.topbar .meta{font-size:12px;color:var(--dim)}
.topbar .meta span{margin-left:14px;padding:4px 10px;background:var(--bg2);border-radius:8px}
.topbar .controls button{margin-left:8px;padding:7px 14px;background:var(--g);color:#000;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-size:13px}
.topbar .controls button.secondary{background:var(--bg3);color:var(--txt)}
.topbar .controls button.danger{background:rgba(255,68,68,0.2);color:#ff6666;border:1px solid #ff4444}

/* 侧边栏导航 (每个子页面都有) */
.layout{display:flex;min-height:calc(100vh - 62px)}
.sidebar{width:220px;background:var(--bg2);border-right:1px solid var(--bg3);padding:20px 0}
.sidebar a{display:block;padding:12px 24px;color:var(--dim);text-decoration:none;font-size:14px;border-left:3px solid transparent;transition:all .15s}
.sidebar a:hover{color:var(--txt);background:rgba(255,215,0,0.05)}
.sidebar a.active{color:var(--g);background:rgba(255,215,0,0.1);border-left-color:var(--g)}
.sidebar .back{display:block;padding:10px 24px;color:var(--g);text-decoration:none;font-size:13px;margin-bottom:16px;border-bottom:1px solid var(--bg3);padding-bottom:16px}
.sidebar .back:hover{text-decoration:underline}
.sidebar .back::before{content:"← ";font-size:14px}

.main{flex:1;padding:30px 40px;overflow-y:auto}
.panel{background:var(--bg2);border:1px solid var(--bg3);border-radius:16px;padding:24px;margin-bottom:20px}
.panel h3{font-size:17px;margin-bottom:14px;color:var(--g);display:flex;align-items:center;gap:8px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px}
.stat{background:var(--bg3);border-radius:12px;padding:16px;text-align:center}
.stat .num{font-size:26px;font-weight:700;color:var(--g)}
.stat .label{font-size:12px;color:var(--dim);margin-top:4px}
.stat.ok .num{color:var(--green)}
.stat.warn .num{color:var(--red)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:var(--bg3);color:var(--g);padding:10px;text-align:left;font-weight:500}
td{padding:10px;border-bottom:1px solid var(--bg3)}
tr:hover{background:rgba(255,215,0,0.04)}
.center-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.center-chip{background:var(--bg3);padding:10px;border-radius:10px;font-size:12px;border-left:3px solid var(--g)}
.center-chip small{color:var(--dim);display:block;margin-top:4px}
.plan-box{background:var(--bg3);padding:14px;border-radius:12px;margin-bottom:10px;border-left:4px solid var(--g)}
.plan-box .event{font-weight:600;margin-bottom:6px}
.plan-box .plan{color:var(--txt);font-size:13px}
.hour-banner{background:linear-gradient(90deg,rgba(255,215,0,0.15),rgba(255,100,100,0.08));border:1px solid var(--g);border-radius:12px;padding:16px;margin-bottom:20px;text-align:center}
.hour-banner .big{font-size:32px;font-weight:700;color:var(--g)}
.hour-banner .small{font-size:13px;color:var(--dim);margin-top:4px}
.loading{text-align:center;padding:60px;color:var(--dim)}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px}
.tag.admin{background:rgba(255,100,100,0.2);color:#ff6666}
.tag.vetoed{background:rgba(255,68,68,0.3);color:#ff6666}
.tag.done{background:rgba(68,255,68,0.2);color:#66ff66}
.tag.pending{background:rgba(255,200,68,0.2);color:#ffcc44}
"""

SIDEBAR = """
<div class="sidebar">
  <a href="/GOBELIN/chamber" class="back">返回会议厅</a>

  <div style="padding:8px 24px 4px;color:var(--dim);font-size:11px;letter-spacing:1px;text-transform:uppercase">📊 交易复盘</div>
  <a href="/GOBELIN/chamber" class="{a_overview}">📊 总览大盘</a>
  <a href="/GOBELIN/chamber/failure" class="{a_failure}">❌ 失败案例</a>
  <a href="/GOBELIN/chamber/emergency" class="{a_emergency}">🚨 紧急预案</a>
  <a href="/GOBELIN/chamber/synergy" class="{a_synergy}">🔗 中心联动</a>
  <a href="/GOBELIN/chamber/decision" class="{a_decision}">👑 高层决策</a>
  <a href="/GOBELIN/chamber/task" class="{a_task}">📋 中层任务</a>
  <a href="/GOBELIN/chamber/grassroots" class="{a_grassroots}">🔥 基层贡献</a>
  <a href="/GOBELIN/chamber/positions" class="{a_positions}">💰 持仓明细</a>

  <div style="padding:16px 24px 4px;color:var(--dim);font-size:11px;letter-spacing:1px;text-transform:uppercase">🏛️ 独立会议室</div>
  <a href="/GOBELIN/chamber/media" class="{a_media}">📺 多媒体会议室</a>
  <a href="/GOBELIN/chamber/global" class="{a_global}">🌍 国际形势会议室</a>
  <a href="/GOBELIN/chamber/trade_share" class="{a_trade_share}">💬 操盘经验分享</a>
  <a href="/GOBELIN/chamber/emergency_hall" class="{a_emergency_hall}">🚨 应急会议室</a>

  <div style="padding:16px 24px 4px;color:var(--dim);font-size:11px;letter-spacing:1px;text-transform:uppercase">🎨 古灵阁 · 文创产业</div>
  <a href="/GOBELIN/stock" style="color:#4fc3f7">📈 沙盘交易大厅</a>
  <a href="/GOBELIN/live" style="color:#4fc3f7">💹 实盘交易中心</a>
  <a href="javascript:alert('📜 文曲星网文创作工作室\\n\\nAPI: /api/writing/*\\n测试: /GOBELIN/stock → 沙盘终端集成')" style="color:#ce93d8">📜 文曲星 · 网文创作</a>
  <a href="javascript:alert('🎬 青龙影视传媒视频制作系统\\n\\nAPI: /api/video/*\\n管线: 创意 → 分镜 → 画面 → 配音 → AI提示词')" style="color:#ff8a65">🎬 青龙影视传媒</a>
  <a href="javascript:alert('🎵 囚牛音乐工作室\\n\\nAPI: /api/music/*\\n管线: 情绪 → 歌词 → 旋律 → 配器 → Suno/Udio Prompt')" style="color:#81c784">🎵 囚牛音乐工作室</a>
</div>
"""


def _page_wrap(title, active_key, body_html, auto_switch="no", date_str=""):
    """统一页面包装: topbar + sidebar + body"""
    active_map = {k: ("active" if k == active_key else "") for k in
                  ['overview', 'failure', 'emergency', 'synergy', 'decision', 'task', 'grassroots',
                   'media', 'global', 'trade_share', 'emergency_hall', 'positions']}
    sidebar = SIDEBAR.format(**{f'a_{k}': v for k, v in active_map.items()})
    hour_banner = ""
    if auto_switch == "yes":
        hour_banner = '<div class="hour-banner"><div class="big">🌙 晚休市 · 复盘时间</div><div class="small">沙盘已自动切换到会议厅</div></div>'
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🏛️ 古灵阁 · {title}</title>
<style>{CHAMBER_CSS}</style>
</head>
<body>
<div class="topbar">
  <h1>🏛️ 古灵阁 · 会议厅</h1>
  <div class="meta">
    <span id="date">📅 {date_str}</span>
    <span>🏛️ 仙女座人性化转义</span>
  </div>
  <div class="controls">
    <button onclick="location.href='/GOBELIN/stock'">← 返回沙盘</button>
    <button class="secondary" onclick="location.href='/GOBELIN/text'">📖 网文创作</button>
    <button class="danger" onclick="logout()">🚪 退出登录</button>
  </div>
</div>
<div class="layout">
  {sidebar}
  <div class="main">
    {hour_banner}
    {body_html}
  </div>
</div>
<script>
function logout(){{
  if(!confirm('确认退出登录?'))return;
  fetch('/api/auth/logout').then(()=>location.href='/login');
}}
</script>
</body></html>"""


def _format_table(headers, rows):
    """通用表格生成器"""
    header_html = '<tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>'
    body_html = ''
    for row in rows:
        body_html += '<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>'
    return f'<table><thead>{header_html}</thead><tbody>{body_html}</tbody></table>'


def render_page(page_key):
    """统一页面渲染 — page_key: overview/failure/emergency/synergy/decision/task/grassroots"""
    report = _gen_report()
    s = report['sections']
    
    # 后端直接生成中文 HTML (全部人性化转义后)
    if page_key == 'overview':
        e = s['经验共享']
        stats_html = f"""
        <div class="stats">
          <div class="stat"><div class="num">{e['total_proposals']}</div><div class="label">📝 今日大厅提案</div></div>
          <div class="stat ok"><div class="num">{e['done']}</div><div class="label">✅ 完成结案</div></div>
          <div class="stat warn"><div class="num">{e['vetoed']}</div><div class="label">🛑 铁律否决</div></div>
          <div class="stat"><div class="num">{e['success_rate']}</div><div class="label">📈 成功率</div></div>
          <div class="stat"><div class="num">{len(s['centers'])}</div><div class="label">🏢 活跃中心</div></div>
          <div class="stat"><div class="num">{len(s['ai_players'])}</div><div class="label">🤖 AI 参与方</div></div>
          <div class="stat"><div class="num">{len(s['events_today'])}</div><div class="label">📡 今日金盾事件</div></div>
        </div>"""
        
        centers_html = '<div class="center-grid">' + ''.join(
            f'<div class="center-chip">{c.get("center_code_human", c["center_code"])}<small>{c.get("name") or c.get("domain") or ""}</small></div>'
            for c in s['centers']) + '</div>'
        
        # 事件表
        events_rows = []
        for ev in s['events_today'][:30]:
            events_rows.append([
                ev.get('severity_human', ev.get('severity', '')),
                ev.get('event_type_human', ev.get('event_type', '')),
                ev.get('source_force', '-') or '-',
                (ev.get('target_force', '') or '')[:50],
                (ev.get('created_at', '') or '')[:16],
            ])
        events_html = _format_table(['严重度', '事件类型', '来源', '目标', '时间'], events_rows)
        
        # AI 参与者表
        player_rows = []
        for p in s['ai_players']:
            player_rows.append([
                p.get('publisher_human', '') or p.get('publisher', '') or '-',
                p.get('publisher_role_human', p.get('publisher_role', '')),
                p.get('claim_owner_role_human', p.get('claim_owner_role', '')),
            ])
        players_html = _format_table(['发布者', '角色', '分派给'], player_rows)
        
        body = f"""
        <div class="panel"><h3>📊 今日复盘总览 (仙女座人性化解读)</h3>{stats_html}</div>
        <div class="panel"><h3>💰 大收盘持仓汇总</h3>{_render_positions(s)}</div>
        <div class="panel"><h3>🏢 {len(s['centers'])} 个活跃中心</h3>{centers_html}</div>
        <div class="panel"><h3>🤖 {len(s['ai_players'])} 位 AI/角色参与操盘</h3>{players_html}</div>
        <div class="panel"><h3>📡 今日金盾事件 ({len(s['events_today'])})</h3>{events_html}</div>"""
    
    elif page_key == 'media':
        body = _render_meeting_room(s, '多媒体会议室', '📺', 'media_intake')
    
    elif page_key == 'global':
        body = _render_meeting_room(s, '国际形势会议室', '🌍', 'board/brainstorm/finance_committee')
    
    elif page_key == 'trade_share':
        body = _render_meeting_room(s, '操盘经验分享会', '💬', 'grassroots/trading_desk/roundtable/simulation')
    
    elif page_key == 'emergency_hall':
        body = _render_emergency_hall(s)
    
    elif page_key == 'positions':
        body = f'<div class="panel"><h3>💰 大收盘持仓汇总 · 完整</h3>{_render_positions(s, full=True)}</div>'
    
    elif page_key == 'failure':
        f = s['失败案例分析']
        hall_rows = []
        for h in f['hall_failures']:
            hall_rows.append([
                f"#{h['id']}",
                (h.get('title') or '')[:50],
                h.get('publisher_role_human', h.get('publisher_role', '')),
                h.get('verdict_human', h.get('verdict', '')) or h.get('peacekeeper_decision_human', ''),
                (h.get('peacekeeper_reason') or '')[:50] or '-',
                (h.get('created_at') or '')[:16],
            ])
        hall_html = _format_table(['#', '标题', '发布者', '状态', '原因', '时间'], hall_rows)
        
        block_rows = []
        for b in f['shield_blocks']:
            block_rows.append([
                b.get('severity_human', ''),
                b.get('event_type_human', b.get('event_type', '')),
                b.get('source_force', '-') or '-',
                (b.get('target_force', '') or '')[:60],
                (b.get('created_at') or '')[:16],
            ])
        block_html = _format_table(['严重度', '事件', '来源', '目标', '时间'], block_rows)
        
        body = f"""
        <div class="panel"><h3>❌ 大厅失败案例 ({len(f['hall_failures'])})</h3>{hall_html}</div>
        <div class="panel"><h3>🛡️ 金盾铁律拦截 ({len(f['shield_blocks'])})</h3>{block_html}</div>"""
    
    elif page_key == 'emergency':
        em = s['紧急事件预案']
        plan_html = ''
        for ev in em['items']:
            plan_html += f"""
            <div class="plan-box">
              <div class="event">⚠️ {ev.get('severity_human', ev.get('severity', ''))} · {ev.get('event_type_human', ev.get('event_type', ''))}</div>
              <div class="plan">📋 预案: {ev.get('plan', '通用预案')}</div>
            </div>"""
        if em['count'] == 0:
            plan_html = '<p style="color:var(--dim);text-align:center;padding:30px">✅ 今日无紧急事件, 沙盘运行平稳</p>'
        
        body = f"""
        <div class="panel"><h3>🚨 紧急事件预案 ({em['count']}) — 自动生成处置方案</h3>{plan_html}</div>"""
    
    elif page_key == 'synergy':
        rows = []
        for d in s['中心联动分析']:
            rows.append([
                d.get('publisher_role_human', d.get('publisher_role', '')),
                d.get('publisher', '-') or '-',
                str(d['cnt']),
                d.get('centers_hit_human', d.get('centers_hit', '-')) or '-',
            ])
        body = f"""
        <div class="panel"><h3>🔗 今日中心联动 ({len(s['中心联动分析'])} 组协同)</h3>
          {_format_table(['发布角色', '发布者', '次数', '涉及中心'], rows)}
        </div>"""
    
    elif page_key == 'decision':
        rows = []
        for d in s['高层决策']:
            rows.append([
                f"#{d['id']}",
                (d.get('title') or '')[:50],
                f"<span class='tag admin'>{d.get('publisher_role_human', d.get('publisher',''))}</span>",
                d.get('verdict_human', d.get('verdict', '')),
                (d.get('created_at') or '')[:16],
            ])
        body = f"""
        <div class="panel"><h3>👑 高层决策 ({len(s['高层决策'])}) — admin/super_admin 布置的任务</h3>
          {_format_table(['#', '标题', '决策者', '状态', '时间'], rows)}
        </div>"""
    
    elif page_key == 'task':
        rows = []
        for t in s['中层任务']:
            rows.append([
                f"#{t['id']}",
                (t.get('title') or '')[:45],
                t.get('claim_owner', '-') or '-',
                t.get('claim_owner_role_human', t.get('claim_owner_role', '')),
                t.get('center_id_human', t.get('center_id', '')) or '-',
                t.get('verdict_human', t.get('verdict', '')),
            ])
        body = f"""
        <div class="panel"><h3>📋 中层分派任务 ({len(s['中层任务'])}) — 非 SA 的 claim 任务</h3>
          {_format_table(['#', '标题', '分派给', '角色', '中心', '状态'], rows)}
        </div>"""
    
    elif page_key == 'grassroots':
        g = s['基层贡献']
        pub_html = '<div class="stats">' + ''.join(
            f'<div class="stat"><div class="num">{p["cnt"]}</div><div class="label">{p.get("publisher_human", p.get("publisher",""))}</div></div>'
            for p in g['top_publishers']) + '</div>'
        
        deli_rows = []
        for d in g['top_deliberators']:
            deli_rows.append([
                d.get('speaker', '-') or '-',
                d.get('role_human', d.get('role', '')),
                str(d['votes']),
            ])
        
        body = f"""
        <div class="panel"><h3>🔥 Top 基层操盘贡献者 ({len(g['top_publishers'])} 位)</h3>{pub_html}</div>
        <div class="panel"><h3>💬 Top 议事参与者 ({len(g['top_deliberators'])} 位)</h3>
          {_format_table(['发言人', '角色', '发言数'], deli_rows)}
        </div>"""
    
    title_map = {
        'overview': '📊 总览大盘',
        'failure': '❌ 失败案例',
        'emergency': '🚨 紧急预案',
        'synergy': '🔗 中心联动',
        'decision': '👑 高层决策',
        'task': '📋 中层任务',
        'grassroots': '🔥 基层贡献',
        'media': '📺 多媒体会议室',
        'global': '🌍 国际形势会议室',
        'trade_share': '💬 操盘经验分享会',
        'emergency_hall': '🚨 异常及灾难应急会议室',
        'positions': '💰 大收盘持仓汇总',
    }
    return _page_wrap(title_map[page_key], page_key, body, report['auto_switch'], report['date'])


# ═══ 新增渲染函数: 持仓 + 会议室 ═══

def _render_positions(s, full=False) -> str:
    """大收盘持仓汇总卡片"""
    pos = s.get('持仓汇总', {})
    if not pos or pos.get('position_count', 0) == 0:
        return '<p style="color:var(--dim);text-align:center;padding:20px">📭 当前空仓 (初始资金 10,000 · 本月 +0.00%)</p>'
    
    p = pos['positions']

    def _fmt_price(v):
        return f"¥{v}" if v is not None else "—"

    def _fmt_time(v):
        return (v or "—")[:16] if v else "—"

    if full:
        # 完整表: 所有字段
        rows = [[
            x['symbol'],
            x.get('name', ''),
            x['qty'],
            f"¥{x['avg_cost']}",
            f"¥{x['price']}",
            f"¥{x['market_val']}",
            f"{'🟢' if x['pnl_pct']>=0 else '🔴'} {x['pnl_pct']:+.2f}%",
            _fmt_price(x.get('last_buy_price')),
            _fmt_time(x.get('last_buy_ts')),
            _fmt_price(x.get('last_sell_price')),
            _fmt_time(x.get('last_sell_ts')),
            _fmt_price(x.get('avg_buy_price')),
            _fmt_price(x.get('avg_sell_price')),
            f"{x.get('buy_cnt',0)}/{x.get('sell_cnt',0)}",
        ] for x in p]
        headers = ['代码', '名称', '持仓', '成本价', '现价', '市值', '盈亏',
                   '最近买价', '买入时间', '最近卖价', '卖出时间',
                   '均买价', '均卖价', '买/卖次数']
    else:
        # 简报: 核心字段 + 最近买/卖
        rows = [[
            x['symbol'],
            x.get('name', ''),
            x['qty'],
            f"¥{x['avg_cost']}",
            f"¥{x['price']}",
            f"¥{x['market_val']}",
            f"{'🟢' if x['pnl_pct']>=0 else '🔴'} {x['pnl_pct']:+.2f}%",
            _fmt_price(x.get('last_buy_price')),
            _fmt_time(x.get('last_buy_ts')),
            _fmt_price(x.get('last_sell_price')),
            _fmt_time(x.get('last_sell_ts')),
        ] for x in p]
        headers = ['代码', '名称', '持仓', '成本价', '现价', '市值', '盈亏',
                   '最近买价', '买入时间', '最近卖价', '卖出时间']

    stat_row = f"""
    <div class="stats">
      <div class="stat"><div class="num">{pos['position_count']}</div><div class="label">持仓只数</div></div>
      <div class="stat"><div class="num">¥{pos['total_cost']:,.0f}</div><div class="label">持仓成本</div></div>
      <div class="stat"><div class="num">¥{pos['total_market_val']:,.0f}</div><div class="label">持仓市值</div></div>
      <div class="stat"><div class="num">¥{pos['cash_balance']:,.0f}</div><div class="label">现金余额</div></div>
      <div class="stat ok"><div class="num">¥{pos['total_equity']:,.0f}</div><div class="label">总权益</div></div>
      <div class="stat {'ok' if pos['monthly_profit_pct']>=0 else 'warn'}">
        <div class="num">{pos['monthly_profit_pct']:+.2f}%</div><div class="label">本月收益</div>
      </div>
    </div>"""
    return stat_row + _format_table(headers, rows)

def _render_meeting_room(s, room_name: str, icon: str, source_types: str) -> str:
    """通用会议室页面渲染"""
    # 根据 room_name 从 report 里取对应数据
    key_map = {'多媒体会议室': '多媒体会议室', '国际形势会议室': '国际形势会议室',
               '操盘经验分享会': '操盘经验分享会'}
    section = key_map.get(room_name, room_name)
    data = s.get(section, {})
    meetings = data.get('meetings', [])
    
    if not meetings:
        return f'<p style="color:var(--dim);text-align:center;padding:30px">🫥 {room_name} 暂无会议记录<br>等晚间循环 tick 驱动自动生成</p>'
    
    cards = []
    for m in meetings:
        con_html = ''
        for c in m.get('conclusions', [])[:4]:
            con_html += f'<li>{c}</li>'
        cards.append(f"""
        <div class="panel" style="border-left:3px solid var(--g)">
          <div style="display:flex;justify-content:space-between">
            <b>{icon} {m['title']}</b>
            <small style="color:var(--dim)">{m['time']}</small>
          </div>
          <ul style="margin-top:10px;color:var(--txt);line-height:1.7">{con_html}</ul>
        </div>""")
    
    return f"""
    <div class="panel"><h3>{icon} {room_name} · 最近 {len(meetings)} 场会议 (来源: {source_types})</h3>
      {''.join(cards)}
    </div>"""

def _render_emergency_hall(s) -> str:
    """异常及灾难应急会议室"""
    em = s.get('应急会议室', {})
    mtgs = em.get('meetings', [])
    shield = em.get('shield_events', [])
    
    parts = []
    
    # 亏损挽救会议
    if mtgs:
        cards = ''
        for m in mtgs:
            con_html = ''.join(f'<li>{c}</li>' for c in m.get('conclusions', [])[:3])
            cards += f"""
            <div style="background:#2a1a1a;border-left:3px solid var(--red);padding:14px;border-radius:10px;margin-bottom:10px">
              <b>🚨 {m['title']}</b> <small style="color:var(--dim)">{m['time']}</small>
              <ul style="margin-top:8px">{con_html}</ul>
            </div>"""
        parts.append(f'<div class="panel"><h3>🚨 亏损挽救层 · 最近 {len(mtgs)} 场</h3>{cards}</div>')
    else:
        parts.append('<div class="panel"><h3>🚨 亏损挽救层</h3><p style="color:var(--dim)">✅ 今日无亏损预案激活</p></div>')
    
    # 今日高严重度金盾事件
    if shield:
        rows = [[e['severity'], e['event'], e['target'] or '-', e['time'][:16]] for e in shield]
        parts.append(f'<div class="panel"><h3>🛡️ 今日高严重度金盾事件 ({len(shield)})</h3>{_format_table(["严重度","事件","目标","时间"], rows)}</div>')
    else:
        parts.append('<div class="panel"><h3>🛡️ 今日高严重度金盾事件</h3><p style="color:var(--dim)">✅ 无 CRITICAL/BLOCKED 事件</p></div>')
    
    return ''.join(parts)
