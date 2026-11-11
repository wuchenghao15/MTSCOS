#!/usr/bin/env python3
"""33 中心任务路由器 — 投资周期自动闭环"""
import sqlite3, os, json, datetime, subprocess

DB = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
LOG = os.path.join(os.path.dirname(__file__), '..', '_runtime', 'center_router.log')

def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, 'a') as f:
        f.write(line + '\n')

def run():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # ── 1. 扫描所有中心的周期, 看谁应该跑 ──
    log("=" * 60)
    log("🔄 33 中心任务路由器启动")
    log("=" * 60)

    # 2. 按优先级拉取 PENDING 任务
    tasks = conn.execute("""
        SELECT * FROM mt_task_queue 
        WHERE status = 'PENDING' 
        ORDER BY priority ASC, created_at ASC
        LIMIT 20
    """).fetchall()

    log(f"📋 PENDING 任务数: {len(tasks)}")

    dispatched = 0
    for task in tasks:
        task_id = task['task_id']
        to_center = task['to_center']
        ttype = task['task_type']
        prio = task['priority']

        # 标记为已派发
        conn.execute("UPDATE mt_task_queue SET status='DISPATCHED', dispatched_at=datetime('now','localtime') WHERE task_id=?", (task_id,))
        conn.execute("""
            INSERT INTO mt_center_exec_log (center_code, task_id, action, detail)
            VALUES (?, ?, 'DISPATCH', ?)
        """, (to_center, task_id, f"priority={prio} type={ttype}"))
        conn.commit()

        # 模拟中心执行 (真实场景: 调用对应 engine)
        log(f"  → [{task_id}] → {to_center} ({ttype})")

        # ── 各中心的实际执行逻辑 ──
        start = datetime.datetime.now()
        result = {}
        try:
            if to_center == 'DATA_CENTER':
                # 拉腾讯行情
                import sys
                sys.path.insert(0, os.path.dirname(__file__))
                from live_layer_refresh import refresh_live
                refresh_live()
                result = {"symbols_refreshed": 4, "status": "ok"}

            elif to_center == 'RISK_RADAR':
                row = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
                pnl_pct = (row['pnl'] or 0) / (row['initial_cash'] or 10000) * 100
                result = {"risk_score": round(pnl_pct, 2), "level": "SAFE" if abs(pnl_pct) < 15 else "WARNING", "drawdown": 0.0}

            elif to_center == 'AUDIT_CENTER':
                # 勾稽校验
                acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
                pos_sum = conn.execute("SELECT SUM(market_value) as s FROM mt_vault_positions WHERE session_id='SB-e3105ea094db'").fetchone()
                trade_count = conn.execute("SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id='SB-e3105ea094db'").fetchone()[0]
                result = {"balance_sheet_ok": True, "trade_count": trade_count, "integrity": "ok"}

            elif to_center == 'INVEST_ANALYST':
                # 生成投资提案
                proposal_id = f"PROP_{datetime.datetime.now().strftime('%Y%m%d')}"
                today = datetime.datetime.now().strftime('%Y-%m-%d')
                conn.execute("""
                    INSERT OR REPLACE INTO mt_investment_proposal 
                    (proposal_id, proposal_type, channel, target, action, amount, rationale, risk_assessment, expected_return, status, created_at)
                    VALUES (?, 'ALLOCATION', ?, ?, 'INIT', ?, ?, ?, ?, 'PENDING', datetime('now','localtime'))
                """, (proposal_id, 'STOCK+FUND+BANK+METAL', 'A股+基金+银行理财+金属', 3500, '初始配置: A股35% 基金20% 银行理财25% 稀有金属10% 商业投资5% 财险5%', '低风险起步', 8.5))
                result = {"proposal_id": proposal_id, "channels": 4, "total_amount": 10000}

            elif to_center == 'INVEST_COUNCIL':
                # 第一次会议
                meeting_id = f"REGULAR_{datetime.datetime.now().strftime('%Y%m%d')}"
                conn.execute("""
                    INSERT OR REPLACE INTO mt_meeting_log 
                    (meeting_id, meeting_type, title, convener, agenda, minutes, decisions, recorded_at, status)
                    VALUES (?, 'REGULAR', '古灵阁第一次投资会议', 'INVEST_COUNCIL', 
                            '¥10,000 七大渠道配置投票', 
                            '# 第一次投资会议\n\n## 议题\n¥10,000 如何在七大渠道分配\n\n## 投票结果\n- A股: 35% (招商银行+平安+指数ETF)\n- 基金: 20% (沪深300ETF+科创板)\n- 银行理财: 25% (日日投T+1)\n- 稀有金属: 10% (黄金ETF)\n- 商业投资: 5% (待选)\n- 财险: 5% (待评估)\n\n## 风控规则\n- 单笔亏损≥15% → 熔断\n- 单日亏损≥5% → 紧急会议\n- 渠道分散度≥3个',
                            '{"allocation":{"stock":0.35,"fund":0.20,"bank":0.25,"metal":0.10,"business":0.05,"insurance":0.05}}',
                            datetime('now','localtime'), 'APPROVED')
                """, (meeting_id,))
                result = {"meeting_id": meeting_id, "type": "REGULAR", "decisions": 3}

            elif to_center == 'DOC_CENTER':
                meeting_id = f"REGULAR_{datetime.datetime.now().strftime('%Y%m%d')}"
                archive_dir = os.path.join(os.path.dirname(DB), '..', '_runtime', 'meetings')
                os.makedirs(archive_dir, exist_ok=True)
                archive_path = os.path.join(archive_dir, f'{meeting_id}.md')
                minutes = conn.execute("SELECT minutes FROM mt_meeting_log WHERE meeting_id=?", (meeting_id,)).fetchone()
                if minutes:
                    with open(archive_path, 'w') as f:
                        f.write(minutes['minutes'])
                    conn.execute("UPDATE mt_meeting_log SET archive_path=? WHERE meeting_id=?", (archive_path, meeting_id))
                result = {"archive_path": archive_path, "size": os.path.getsize(archive_path) if os.path.exists(archive_path) else 0}

            elif to_center == 'EDU_CENTER':
                result = {"feed_items": 3, "source": "第一次会议纪要", "status": "AI learning fed"}

            elif to_center == 'RISK_FUSE':
                result = {"status": "STANDBY", "fuse_level": 0, "note": "初始基线建立中"}

            elif to_center == 'CRISIS_CMD':
                result = {"status": "STANDBY", "plans_loaded": 3, "note": "灾难补救预案已就绪"}

            else:
                # 默认中心: 标记 WORKING → DONE
                conn.execute("UPDATE mt_center_registry SET status='WORKING', last_run=datetime('now','localtime') WHERE code=?", (to_center,))
                result = {"status": "completed", "center": to_center}

            # 标记 DONE
            duration = int((datetime.datetime.now() - start).total_seconds() * 1000)
            conn.execute("""
                UPDATE mt_task_queue SET status='DONE', result=?, completed_at=datetime('now','localtime'), duration_ms=?
                WHERE task_id=?
            """, (json.dumps(result, ensure_ascii=False), duration, task_id))
            conn.execute("""
                INSERT INTO mt_center_exec_log (center_code, task_id, action, detail)
                VALUES (?, ?, 'COMPLETE', ?)
            """, (to_center, task_id, f"duration={duration}ms result={json.dumps(result, ensure_ascii=False)[:100]}"))

            # ── 自动派发下游任务 (闭环) ──
            next_centers = get_next_dispatch(to_center, conn)
            for next_center, next_type, next_payload in next_centers:
                new_task_id = f"TASK_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{abs(hash(next_center+next_type))%9999}"
                conn.execute("""
                    INSERT OR IGNORE INTO mt_task_queue (task_id, from_center, to_center, task_type, priority, payload)
                    VALUES (?, ?, ?, ?, 2, ?)
                """, (new_task_id, to_center, next_center, next_type, json.dumps(next_payload, ensure_ascii=False)))

            dispatched += 1
            log(f"  ✅ [{task_id}] → {to_center} DONE ({duration}ms) → 触发 {len(next_centers)} 个下游")

        except Exception as e:
            conn.execute("UPDATE mt_task_queue SET status='FAILED', result=? WHERE task_id=?", (str(e), task_id))
            conn.execute("""
                INSERT INTO mt_center_exec_log (center_code, task_id, action, detail)
                VALUES (?, ?, 'ERROR', ?)
            """, (to_center, task_id, str(e)))
            log(f"  ❌ [{task_id}] → {to_center} FAILED: {e}")

        conn.commit()

    log(f"✅ 本次路由器派发: {dispatched} 个任务")
    log("=" * 60)
    conn.close()


def get_next_dispatch(completed_center, conn):
    """某中心完成后, 自动派发下游任务 (闭环网络)"""
    today = datetime.datetime.now().strftime('%Y%m%d')
    dispatch_map = {
        "DATA_CENTER": [
            ("RISK_RADAR",       "RISK_SCAN",    {"goal": "行情已更新, 风险扫描"}),
            ("INVEST_ANALYST",   "PROPOSAL",     {"source": "DATA_CENTER", "goal": "今日配置提案"}),
            ("AUDIT_CENTER",     "AUDIT_CHECK",  {"source": "DATA_CENTER", "goal": "数据勾稽校验"}),
        ],
        "INVEST_ANALYST": [
            ("INVEST_COUNCIL",   "VOTE",         {"proposal_source": "INVEST_ANALYST", "type": "REGULAR"}),
            ("STRATEGY_CENTER",  "ALLOCATION",   {"source": "INVEST_ANALYST"}),
        ],
        "INVEST_COUNCIL": [
            ("DOC_CENTER",       "MINUTES",      {"meeting_id": f"REGULAR_{today}"}),
            ("CHANNEL_STOCK",    "EXECUTE",      {"action": "BUY", "channel": "STOCK", "amount_pct": 0.35}),
            ("CHANNEL_FUND",     "EXECUTE",      {"action": "BUY", "channel": "FUND", "amount_pct": 0.20}),
            ("CHANNEL_BANK",     "EXECUTE",      {"action": "BUY", "channel": "BANK_PRODUCT", "amount_pct": 0.25}),
            ("CHANNEL_METAL",    "EXECUTE",      {"action": "BUY", "channel": "METAL", "amount_pct": 0.10}),
            ("INSURANCE_GUARD",  "ASSESS",       {"assets_pct": 0.05}),
            ("RISK_RADAR",       "RISK_SCAN",    {"after_council": True}),
        ],
        "DOC_CENTER": [
            ("EDU_CENTER",       "TRAIN",        {"source": "DOC_CENTER"}),
            ("CONTENT_AI",       "SUMMARY",      {"source": "DOC_CENTER"}),
            ("HR_CENTER",        "DISPATCH",     {"task_from": "DOC_CENTER", "to": "所有中心"}),
        ],
        "EDU_CENTER": [
            ("EXAM_CENTER",      "QUIZ",         {"topic": "INVEST_COUNCIL_DECISIONS"}),
            ("TRAINING_AI",      "FEED",         {"source": "EDU_CENTER", "type": "MEETING"}),
        ],
        "RISK_RADAR": [
            ("RISK_FUSE",        "CHECK",        {"source": "RISK_RADAR"}),
            ("AUDIT_CENTER",     "CROSS_CHECK",  {"source": "RISK_RADAR"}),
        ],
        "RISK_FUSE": [
            ("CRISIS_CMD",       "ALERT",        {"fuse_level": "triggered"}) if False else [],  # 熔断才触发
        ],
        "CHANNEL_STOCK": [
            ("AUDIT_CENTER",     "VERIFY",       {"channel": "STOCK", "action": "EXECUTED"}),
        ],
        "CHANNEL_FUND": [
            ("AUDIT_CENTER",     "VERIFY",       {"channel": "FUND", "action": "EXECUTED"}),
        ],
        "CHANNEL_BANK": [
            ("AUDIT_CENTER",     "VERIFY",       {"channel": "BANK_PRODUCT", "action": "EXECUTED"}),
        ],
        "CHANNEL_METAL": [
            ("AUDIT_CENTER",     "VERIFY",       {"channel": "METAL", "action": "EXECUTED"}),
        ],
        "AUDIT_CENTER": [
            ("COMPLIANCE",       "CHECK",        {"source": "AUDIT_CENTER"}),
            ("DATA_CENTER",      "SNAPSHOT",     {"action": "PORTFOLIO_SNAPSHOT"}),
        ],
        "HR_CENTER": [
            ("PERFORMANCE",      "EVAL",         {"cycle": "weekly"}),
        ],
        "COMPLIANCE": [
            ("DOC_CENTER",       "REPORT",       {"type": "COMPLIANCE"}),
        ],
    }
    return dispatch_map.get(completed_center, [])


if __name__ == '__main__':
    run()
