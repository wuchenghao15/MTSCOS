#!/usr/bin/env python3
"""古灵阁治理层 API — 33 中心 / 任务队列 / 会议 / 提案 / 多资产配置"""
from flask import Blueprint, request, jsonify
import sqlite3, json, os, datetime

bp = Blueprint('finance_governance', __name__, url_prefix='/api/finance/governance')
DB = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')

def _connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def _ok(data):
    return jsonify({"code": "E_OK", "success": True, "data": data})
def _err(msg):
    return jsonify({"code": "E_ERR", "success": False, "error": msg})

# ─────────────────────────────────────────────────────────────────────
# 1. 七大资产渠道总览 /portfolio/allocation
# ─────────────────────────────────────────────────────────────────────
@bp.get('/portfolio/allocation')
def api_allocation():
    """七大渠道资产配置总览"""
    try:
        conn = _connect()
        acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
        total = float(acc['total_assets'] or 10000) if acc else 10000
        cash = float(acc['cash'] or 10000) if acc else 10000

        channels = []

        # A股 (Row 用 dict() 安全访问, 避免 KeyError)
        rows = conn.execute("SELECT * FROM mt_live_position").fetchall()
        mv = sum(float(d.get('price',0)) * float(d.get('qty',0)) for d in (dict(r) for r in rows))
        pnl = sum(float(d.get('pnl',0)) for d in (dict(r) for r in rows))
        channels.append({"code": "STOCK", "name": "A股股票", "icon": "📈", "mv": round(mv,2), "pnl": round(pnl,2), "rows": len(rows), "pct": round(mv/total*100,1) if total else 0})

        # 基金
        rows = conn.execute("SELECT * FROM mt_live_fund_position").fetchall()
        mv = sum(float(r['price'] or 0)*float(r['qty'] or 0) for r in rows)
        channels.append({"code": "FUND", "name": "基金", "icon": "📊", "mv": round(mv,2), "pnl": 0, "rows": len(rows), "pct": round(mv/total*100,1) if total else 0})

        # 银行理财
        rows = conn.execute("SELECT * FROM mt_live_bank_product").fetchall()
        principal = sum(float(d.get('amount',0)) for d in (dict(r) for r in rows))
        channels.append({"code": "BANK_PRODUCT", "name": "银行理财(T+1/T+5)", "icon": "🏦", "mv": round(principal,2), "pnl": 0, "rows": len(rows), "pct": round(principal/total*100,1) if total else 0})

        # 定期存款
        rows = conn.execute("SELECT * FROM mt_live_term_deposit WHERE status='ACTIVE'").fetchall()
        amt = sum(float(r['amount'] or 0) for r in rows)
        channels.append({"code": "TERM_DEPOSIT", "name": "定期存款", "icon": "📅", "mv": round(amt,2), "pnl": 0, "rows": len(rows), "pct": round(amt/total*100,1) if total else 0})

        # 商业投资
        rows = conn.execute("SELECT * FROM mt_live_business_inv WHERE status='ACTIVE'").fetchall()
        amt = sum(float(r['amount'] or 0) for r in rows)
        channels.append({"code": "BUSINESS", "name": "商业投资(私募/股权)", "icon": "🏢", "mv": round(amt,2), "pnl": 0, "rows": len(rows), "pct": round(amt/total*100,1) if total else 0})

        # 商业保险
        rows = conn.execute("SELECT * FROM mt_live_insurance WHERE status='ACTIVE'").fetchall()
        cash_value = sum(float(d.get('premium',0)) for d in (dict(r) for r in rows))
        channels.append({"code": "INSURANCE", "name": "财险/分红险", "icon": "🛡️", "mv": round(cash_value,2), "pnl": 0, "rows": len(rows), "pct": round(cash_value/total*100,1) if total else 0})

        # 稀有金属
        rows = conn.execute("SELECT * FROM mt_live_metal_position").fetchall()
        mv = sum(float(r['price'] or 0)*float(r['qty'] or 0) for r in rows)
        channels.append({"code": "METAL", "name": "稀有金属(黄金/白银)", "icon": "🥇", "mv": round(mv,2), "pnl": 0, "rows": len(rows), "pct": round(mv/total*100,1) if total else 0})

        # 现金
        channels.append({"code": "CASH", "name": "可用现金", "icon": "💵", "mv": round(cash,2), "pnl": 0, "rows": 0, "pct": round(cash/total*100,1) if total else 0})

        conn.close()
        return _ok({
            "total_assets": round(total,2),
            "cash": round(cash,2),
            "channels": channels,
            "date": datetime.datetime.now().strftime('%Y-%m-%d'),
            "target_allocation": {
                "STOCK": 0.35, "FUND": 0.20, "BANK_PRODUCT": 0.25,
                "METAL": 0.10, "BUSINESS": 0.05, "INSURANCE": 0.05
            }
        })
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────
# 2. 33 中心状态 /centers/status
# ─────────────────────────────────────────────────────────────────────
@bp.get('/centers/status')
def api_centers_status():
    """33 中心实时状态"""
    try:
        conn = _connect()
        centers = conn.execute("SELECT * FROM mt_center_registry ORDER BY code").fetchall()

        # 统计执行日志
        execs = conn.execute("""
            SELECT center_code, action, COUNT(*) as cnt
            FROM mt_center_exec_log
            GROUP BY center_code, action
        """).fetchall()
        exec_map = {}
        for e in execs:
            exec_map.setdefault(e['center_code'], {})[e['action']] = e['cnt']

        # 任务统计
        tasks = conn.execute("""
            SELECT to_center, status, COUNT(*) as cnt
            FROM mt_task_queue GROUP BY to_center, status
        """).fetchall()
        task_map = {}
        for t in tasks:
            task_map.setdefault(t['to_center'], {})[t['status']] = t['cnt']

        # 分组
        groups = {
            "🏦 投资决策层": ["INVEST_COUNCIL","INVEST_ANALYST","CHANNEL_STOCK","CHANNEL_FUND","CHANNEL_BANK","CHANNEL_METAL","CHANNEL_BIZ"],
            "🛡️ 风险合规层": ["RISK_RADAR","RISK_FUSE","AUDIT_CENTER","COMPLIANCE","TAX_PLANNING","INSURANCE_GUARD"],
            "📝 内容产出层": ["DOC_CENTER","STRATEGY_CENTER","PRESS_CENTER","CONTENT_AI","BRAND_CENTER"],
            "👥 人事管理层": ["HR_CENTER","PERFORMANCE","ROLE_ASSIGN","WELLNESS"],
            "📊 数据技术层": ["DATA_CENTER","AI_MODEL","API_GATEWAY","INFRA_CENTER","SECURITY_OPS"],
            "🎓 教育考试层": ["EDU_CENTER","EXAM_CENTER","CASE_LAB","TRAINING_AI"],
            "🚨 应急管理层": ["CRISIS_CMD","DR_CENTER"],
        }

        result = []
        for group_name, codes in groups.items():
            group_centers = []
            for c in centers:
                if c['code'] not in codes:
                    continue
                grp_exec = exec_map.get(c['code'], {})
                grp_task = task_map.get(c['code'], {})
                group_centers.append({
                    "code": c['code'],
                    "name": c['name'],
                    "cycle": c['cycle'],
                    "role": c['role'],
                    "status": c['status'],
                    "last_run": c['last_run'],
                    "dispatch_count": grp_exec.get('DISPATCH', 0),
                    "complete_count": grp_exec.get('COMPLETE', 0),
                    "error_count": grp_exec.get('ERROR', 0),
                    "pending_tasks": grp_task.get('PENDING', 0),
                    "done_tasks": grp_task.get('DONE', 0),
                })
            result.append({"group": group_name, "centers": group_centers})

        conn.close()
        return _ok({"groups": result, "total": len(centers), "date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────
# 3. 任务队列 /tasks/queue
# ─────────────────────────────────────────────────────────────────────
@bp.get('/tasks/queue')
def api_tasks_queue():
    """任务队列实时状态"""
    try:
        conn = _connect()
        status_filter = request.args.get('status', '')
        query = "SELECT * FROM mt_task_queue"
        params = []
        if status_filter:
            query += " WHERE status=?"
            params.append(status_filter)
        query += " ORDER BY priority ASC, created_at DESC LIMIT 50"

        rows = conn.execute(query, params).fetchall()
        all_status = conn.execute("SELECT status, COUNT(*) as cnt FROM mt_task_queue GROUP BY status").fetchall()

        tasks = []
        for r in rows:
            tasks.append({
                "task_id": r['task_id'],
                "from": r['from_center'],
                "to": r['to_center'],
                "type": r['task_type'],
                "priority": r['priority'],
                "status": r['status'],
                "created_at": r['created_at'],
                "completed_at": r['completed_at'],
                "duration_ms": r['duration_ms'],
            })

        conn.close()
        return _ok({
            "tasks": tasks,
            "status_counts": {s['status']: s['cnt'] for s in all_status},
            "total": sum(s['cnt'] for s in all_status),
        })
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────
# 4. 会议日志 /meetings
# ─────────────────────────────────────────────────────────────────────
@bp.get('/meetings')
def api_meetings():
    """所有会议日志"""
    try:
        conn = _connect()
        mtg_id = request.args.get('meeting_id', '')
        if mtg_id:
            row = conn.execute("SELECT * FROM mt_meeting_log WHERE meeting_id=?", (mtg_id,)).fetchone()
            conn.close()
            if not row:
                return _err("meeting not found")
            m = dict(row)
            for k in ['attendants','decisions','action_items','risk_flags']:
                if m.get(k):
                    try: m[k] = json.loads(m[k])
                    except: pass
            return _ok(m)

        rows = conn.execute("SELECT * FROM mt_meeting_log ORDER BY recorded_at DESC LIMIT 20").fetchall()
        conn.close()
        return _ok({
            "meetings": [dict(r) for r in rows],
            "total": len(rows),
        })
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────
# 5. 投资提案 /proposals
# ─────────────────────────────────────────────────────────────────────
@bp.get('/proposals')
def api_proposals():
    """投资提案列表"""
    try:
        conn = _connect()
        rows = conn.execute("SELECT * FROM mt_investment_proposal ORDER BY created_at DESC LIMIT 20").fetchall()
        conn.close()
        return _ok({
            "proposals": [dict(r) for r in rows],
            "total": len(rows),
        })
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────
# 6. 投资组合快照 /portfolio/snapshots
# ─────────────────────────────────────────────────────────────────────
@bp.get('/portfolio/snapshots')
def api_snapshots():
    """每日组合快照时间轴"""
    try:
        conn = _connect()
        rows = conn.execute("SELECT * FROM mt_portfolio_snapshot ORDER BY snap_date DESC LIMIT 30").fetchall()
        conn.close()
        return _ok({
            "snapshots": [dict(r) for r in rows],
            "total": len(rows),
        })
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────
# 7. 中心执行日志 /centers/exec-log
# ─────────────────────────────────────────────────────────────────────
@bp.get('/centers/exec-log')
def api_exec_log():
    """中心执行日志"""
    try:
        conn = _connect()
        code = request.args.get('center_code', '')
        query = "SELECT * FROM mt_center_exec_log"
        params = []
        if code:
            query += " WHERE center_code=?"
            params.append(code)
        query += " ORDER BY created_at DESC LIMIT 100"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return _ok({"logs": [dict(r) for r in rows]})
    except Exception as e:
        return _err(str(e))
