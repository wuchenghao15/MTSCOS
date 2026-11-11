#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚨 紧急权益对比触发 + 四象限根因诊断引擎
==========================================
当今日总权益 < 昨日权益 × (1-阈值) → 自动触发紧急会议 + 四象限诊断

诊断框架 (4 象限):
  Q1: 长期持仓占用总权益 (long-term holding tie-up)
      → 持仓天数 > 5 天 且 浮亏 > 3% 且 成本占总权益 > 20%
  Q2: 突发事件股价异常波动 (sudden price anomaly)
      → 今日跌幅 > 3% 且 不是大盘整体下跌
  Q3: 高层决议失误 (high-level decision mistake)
      → 对比最近 3 天高层会议结论 vs 实际走势 (反向验证)
  Q4: AI 脑库经验不足 (AI brain experience gap)
      → mt_ai_brain_feed_log 搜索相似场景数量 + 近 3 天亏损笔数
"""
import sqlite3, os, json, sys, random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ── 配置 ──
EQUITY_DROP_THRESHOLD = -0.03  # 权益相对昨日跌 > 3% 触发紧急会议
LONG_TERM_DAYS = 5             # 持仓 > 5 天 → 长期
ANOMALY_DROP_PCT = -3.0         # 单日跌幅 > 3% → 异常
BRAIN_GAP_SIMILAR_MIN = 3       # 相似场景 < 3 条 → 脑库经验不足

DB = os.environ.get('APP_DB', os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "app.db"))
if not os.path.isabs(DB):
    DB = os.path.abspath(DB)


# ═══════════════════════════════════════════════════
#  1. 昨日权益快照管理
# ═══════════════════════════════════════════════════

def _db():
    return sqlite3.connect(DB, timeout=15)

def save_daily_snapshot() -> Optional[Dict]:
    """盘后保存今日权益快照 → mt_trade_account_state.daily_snapshots_json"""
    c = _db()
    now = datetime.now()
    date_key = now.strftime('%Y-%m-%d')
    
    # 从 chamber_bp 对齐的逻辑计算今日权益
    cash_balance = 10000.0
    initial_capital = 10000.0
    positions = []
    
    # 拉所有交易 → 加权均价 (和 tick engine 完全一致)
    rows = c.execute("""SELECT symbol, action, qty, price
        FROM mt_trade_log WHERE source='sandbox_adapter' OR source='sandbox'
        ORDER BY created_at ASC""").fetchall()
    _pos, _cost_map = {}, {}
    for sym, action, qty, price in rows:
        qty, price = float(qty), float(price)
        if action == 'BUY':
            _pos[sym] = _pos.get(sym, 0) + qty
            prev_cost, prev_qty = _cost_map.get(sym, (0.0, 0))
            new_qty = prev_qty + qty
            _cost_map[sym] = ((prev_cost * prev_qty + price * qty) / new_qty if new_qty else 0, new_qty)
        else:
            _pos[sym] = _pos.get(sym, 0) - qty
    total_cost_basis = 0.0
    for sym, qty in _pos.items():
        if qty > 0:
            avg = _cost_map.get(sym, (0, 0))[0]
            positions.append({'symbol': sym, 'qty': qty, 'avg_cost': avg, 'cost': qty * avg})
            total_cost_basis += qty * avg
    
    # 账户状态 — 现金 + 持仓 + 银行卡额外资金
    initial_capital = 10000.0
    cash_balance = 10000.0
    bank_account_balance = 0.0  # 银行卡额外未入市资金 (用户手动维护, 默认为 0)
    for row in c.execute("SELECT state_key, state_value FROM mt_trade_account_state").fetchall():
        k, v = row[0], row[1]
        if k == 'initial_capital': initial_capital = float(v)
        elif k == 'cash_balance': cash_balance = float(v)
        elif k == 'bank_account_balance': bank_account_balance = float(v)
    
    total_equity = round(cash_balance + bank_account_balance + total_cost_basis, 2)
    # 口径: 总权益 = 证券账户现金 + 银行卡未入市资金 + 持仓市值(成本基)
    total_pct = round((total_equity - initial_capital) / initial_capital * 100, 2)
    
    # 保存快照
    snap = {
        'date': date_key, 'equity': total_equity, 'cash': round(cash_balance, 2),
        'cost_basis': round(total_cost_basis, 2), 'positions': positions,
        'position_count': len(positions), 'pct': total_pct, 'saved_at': now.strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    # 更新 mt_trade_account_state
    c.execute("UPDATE mt_trade_account_state SET state_value=?, updated_at=? WHERE state_key=?",
              (str(total_equity), now.strftime('%Y-%m-%d %H:%M:%S'), f'equity_{date_key}'))
    c.execute("INSERT OR REPLACE INTO mt_trade_account_state (state_key, state_value, updated_at) VALUES (?,?,?)",
              (f'equity_{date_key}', str(total_equity), now.strftime('%Y-%m-%d %H:%M:%S')))
    c.commit()
    c.close()
    
    print(f"📸 权益快照已保存 {date_key}: ¥{total_equity} ({total_pct:+.2f}%)")
    return snap


# ═══════════════════════════════════════════════════
#  2. 四象限根因诊断引擎
# ═══════════════════════════════════════════════════

def diagnose_four_quadrants(yesterday_snap: Dict, today_snap: Dict) -> Dict:
    """四象限根因诊断 → {'Q1':..., 'Q2':..., 'Q3':..., 'Q4':..., 'summary':..., 'primary_cause':...}"""
    c = _db()
    now = datetime.now()
    
    today_date = today_snap.get('date', now.strftime('%Y-%m-%d'))
    equity_change = today_snap['equity'] - yesterday_snap['equity']
    equity_pct_change = equity_change / yesterday_snap['equity'] * 100 if yesterday_snap['equity'] else 0
    
    diagnosis = {
        'triggered_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'yesterday_equity': yesterday_snap['equity'],
        'today_equity': today_snap['equity'],
        'equity_change': round(equity_change, 2),
        'equity_pct_change': round(equity_pct_change, 2),
        'quadrants': {},
        'summary': '',
        'primary_cause': '',
    }
    
    # ── Q1: 长期持仓占用总权益 ──
    q1_findings = []
    try:
        for p in today_snap.get('positions', []):
            sym = p['symbol']
            # 找最早一次买入
            first_buy = c.execute("""SELECT MIN(DATE(created_at)) FROM mt_trade_log
                WHERE symbol=? AND action='BUY'""", (sym,)).fetchone()[0]
            if first_buy:
                days_held = (now - datetime.strptime(first_buy, '%Y-%m-%d')).days
                cost_pct = p['cost'] / today_snap['equity'] * 100 if today_snap['equity'] else 0
                if days_held >= LONG_TERM_DAYS and cost_pct >= 20:
                    q1_findings.append({
                        'symbol': sym, 'days_held': days_held,
                        'cost_pct_equity': round(cost_pct, 1),
                        'avg_cost': p['avg_cost'], 'qty': p['qty'],
                        'severity': '🔴' if days_held >= 10 else '🟡',
                    })
    except Exception:
        pass
    diagnosis['quadrants']['Q1'] = {
        'label': '📦 长期持仓占用总权益',
        'findings': q1_findings,
        'count': len(q1_findings),
        'verdict': f"{'⚠️ 发现 '+str(len(q1_findings))+' 只超期持仓' if q1_findings else '✅ 无超期持仓占用问题'}",
    }
    
    # ── Q2: 突发事件股价异常波动 ──
    q2_findings = []
    try:
        # 查今日交易的买入价 vs 最近收盘价 (找异常)
        recent_prices = {}
        for row in c.execute("""SELECT symbol, action, price, DATE(created_at) as d
            FROM mt_trade_log WHERE DATE(created_at) >= DATE('now','localtime','-2 days')
            ORDER BY created_at DESC""").fetchall():
            sym, action, price, d = row
            if sym not in recent_prices:
                recent_prices[sym] = []
            recent_prices[sym].append({'action': action, 'price': float(price), 'date': d})
        
        for sym, trades in recent_prices.items():
            if len(trades) >= 2:
                today_trades = [t for t in trades if t['date'] == today_date]
                prev_trades = [t for t in trades if t['date'] < today_date]
                if today_trades and prev_trades:
                    prev_avg = sum(t['price'] for t in prev_trades) / len(prev_trades)
                    today_avg = sum(t['price'] for t in today_trades) / len(today_trades)
                    change_pct = (today_avg - prev_avg) / prev_avg * 100
                    if change_pct <= ANOMALY_DROP_PCT:
                        q2_findings.append({
                            'symbol': sym, 'prev_avg': round(prev_avg, 2),
                            'today_avg': round(today_avg, 2),
                            'change_pct': round(change_pct, 2),
                            'severity': '🔴' if change_pct <= -5 else '🟡',
                        })
    except Exception:
        pass
    diagnosis['quadrants']['Q2'] = {
        'label': '📉 突发事件股价异常波动',
        'findings': q2_findings,
        'count': len(q2_findings),
        'verdict': f"{'⚠️ 发现 '+str(len(q2_findings))+' 只股价异动' if q2_findings else '✅ 无异常股价波动'}",
    }
    
    # ── Q3: 高层决议失误 (反向验证) ──
    q3_findings = []
    try:
        recent_boards = c.execute("""SELECT meeting_id, meeting_title, meeting_type, conclusions,
            datetime(triggered_at) as ts FROM mt_sandbox_meetings
            WHERE meeting_type IN ('board','finance_committee','CLOSE_SUMMARY','CLOSE_REVIEW','EVENING_HALF_HOUR')
              AND triggered_at >= datetime('now','localtime','-3 days')
            ORDER BY triggered_at DESC LIMIT 5""").fetchall()
        for m in recent_boards:
            conclusions = (m['conclusions'] or '')[:200]
            # 简单反向验证: 结论含"乐观"/"加仓"/"继续" 但实际权益下跌
            bull_words = ['继续', '加仓', '乐观', '跑赢', '正确', '胜率达标', '方向正确']
            bear_result = equity_change < 0
            if any(w in conclusions for w in bull_words) and bear_result:
                q3_findings.append({
                    'meeting': m['meeting_title'], 'ts': m['ts'],
                    'suspected': '结论偏乐观但实际权益下跌',
                    'conclusion_snippet': conclusions[:120],
                    'severity': '🟠',
                })
    except Exception:
        pass
    diagnosis['quadrants']['Q3'] = {
        'label': '👑 高层决议失误',
        'findings': q3_findings,
        'count': len(q3_findings),
        'verdict': f"{'⚠️ '+str(len(q3_findings))+' 个结论需反向验证' if q3_findings else '✅ 高层决议无明显失误'}",
    }
    
    # ── Q4: AI 脑库经验不足 ──
    q4_findings = []
    try:
        # 近 3 天亏损交易笔数
        losing_trades = c.execute("""SELECT COUNT(*) FROM mt_trade_log
            WHERE DATE(created_at) >= DATE('now','localtime','-3 days') AND action='SELL'
              AND fill_price > price""").fetchone()[0]
        
        # 相似场景脑库条数
        scenarios_searched = [
            f"权益下跌 {abs(equity_pct_change):.0f}%", f"持仓 {today_snap['position_count']} 只",
        ]
        brain_hits = 0
        for kw in scenarios_searched:
            hits = c.execute("SELECT COUNT(*) FROM mt_ai_brain_feed_log WHERE feed_content LIKE ?",
                             (f'%{kw}%',)).fetchone()[0]
            brain_hits += hits
        
        if brain_hits < BRAIN_GAP_SIMILAR_MIN * 2:
            q4_findings.append({
                'metric': '相似场景脑库条数',
                'value': brain_hits, 'threshold': BRAIN_GAP_SIMILAR_MIN * 2,
                'note': f'近 3 天卖出亏损 {losing_trades} 笔',
                'severity': '🟡',
            })
        # 晚间循环是否触发过 (近期)
        recent_evening = c.execute("""SELECT COUNT(*) FROM mt_sandbox_meetings
            WHERE meeting_type='EVENING_HALF_HOUR' AND triggered_at >= datetime('now','localtime','-1 days')
        """).fetchone()[0]
        if recent_evening == 0:
            q4_findings.append({
                'metric': '晚间循环', 'value': 0,
                'note': '近 24h 未触发 EVENING_HALF_HOUR — tick engine 未接入',
                'severity': '🔴',
            })
    except Exception:
        pass
    diagnosis['quadrants']['Q4'] = {
        'label': '🧠 AI 脑库经验不足',
        'findings': q4_findings,
        'count': len(q4_findings),
        'verdict': f"{'⚠️ '+str(len(q4_findings))+' 个脑库问题' if q4_findings else '✅ 脑库经验充足'}",
    }
    
    # ── 主因判定 ──
    counts = {f'Q{i}': diagnosis['quadrants'][f'Q{i}']['count'] for i in range(1, 5)}
    primary = max(counts, key=lambda k: counts[k])
    primary_label = diagnosis['quadrants'][primary]['label']
    total_issues = sum(counts.values())
    
    diagnosis['primary_cause'] = f"{primary_label} ({counts[primary]} 条发现)"
    diagnosis['total_issues'] = total_issues
    diagnosis['summary'] = (
        f"📉 权益从 ¥{yesterday_snap['equity']} 跌至 ¥{today_snap['equity']} "
        f"({equity_pct_change:+.2f}%) — 四象限共发现 {total_issues} 条问题。\n"
        f"🎯 主因: {diagnosis['primary_cause']}\n\n"
        + '\n'.join(f"  ✅ {diagnosis['quadrants'][f'Q{i}']['verdict']}" for i in range(1, 5))
    )
    
    c.close()
    return diagnosis


# ═══════════════════════════════════════════════════
#  3. 紧急会议触发入口
# ═══════════════════════════════════════════════════

def run_equity_alert_check() -> Dict:
    """检查今日权益 vs 昨日 → 如跌 > 3% 触发紧急会议"""
    c = _db()
    now = datetime.now()
    
    # 读取昨日快照
    yesterday_date = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    y_val = c.execute("SELECT state_value FROM mt_trade_account_state WHERE state_key=?",
                      (f'equity_{yesterday_date}',)).fetchone()
    if not y_val:
        # 没昨日快照 → 用 initial_capital 作为参考 (首次)
        base = c.execute("SELECT state_value FROM mt_trade_account_state WHERE state_key='initial_capital'").fetchone()
        yesterday_equity = float(base[0]) if base else 10000.0
        y_snap = {'equity': yesterday_equity, 'date': yesterday_date}
    else:
        yesterday_equity = float(y_val[0])
        y_snap = {'equity': yesterday_equity, 'date': yesterday_date}
    
    # 计算今日权益 (和 save_daily_snapshot 一致的逻辑)
    cash_balance = 10000.0
    rows = c.execute("SELECT state_value FROM mt_trade_account_state WHERE state_key='cash_balance'").fetchone()
    if rows: cash_balance = float(rows[0])
    
    # 加权均价持仓
    trows = c.execute("""SELECT symbol, name, action, qty, price
        FROM mt_trade_log WHERE source='sandbox_adapter' OR source='sandbox'
        ORDER BY created_at ASC""").fetchall()
    _pos, _cost_map, _name_map = {}, {}, {}
    for sym, name, action, qty, price in trows:
        qty, price = float(qty), float(price)
        _name_map[sym] = name
        if action == 'BUY':
            _pos[sym] = _pos.get(sym, 0) + qty
            pc, pq = _cost_map.get(sym, (0.0, 0))
            nq = pq + qty
            _cost_map[sym] = ((pc * pq + price * qty) / nq if nq else 0, nq)
        else:
            _pos[sym] = _pos.get(sym, 0) - qty
    positions = []
    cost_basis = 0.0
    for sym, qty in sorted(_pos.items()):
        if qty > 0:
            avg = _cost_map.get(sym, (0, 0))[0]
            cost_basis += qty * avg
            positions.append({'symbol': sym, 'name': _name_map.get(sym, ''),
                             'qty': round(qty, 2), 'avg_cost': round(avg, 4), 'cost': round(qty * avg, 2)})
    
    # 计算今日权益 — 多口径合并
    bank_account_balance = 0.0
    rows2 = c.execute("SELECT state_value FROM mt_trade_account_state WHERE state_key='bank_account_balance'").fetchone()
    if rows2: bank_account_balance = float(rows2[0])
    
    today_equity = round(cash_balance + bank_account_balance + cost_basis, 2)
    # 口径: 总权益 = 证券账户现金 + 银行卡未入市 + 持仓市值(成本基)
    equity_pct = (today_equity - yesterday_equity) / yesterday_equity * 100
    
    c.close()
    
    print(f"\n{'='*55}")
    print(f"🚨 权益对比检查 @ {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  昨日权益: ¥{yesterday_equity:,.2f}")
    print(f"  今日权益: ¥{today_equity:,.2f}")
    print(f"  变化: ¥{today_equity-yesterday_equity:,.2f} ({equity_pct:+.2f}%)")
    print(f"  阈值: {EQUITY_DROP_THRESHOLD*100:.0f}%")
    
    triggered = equity_pct <= EQUITY_DROP_THRESHOLD * 100
    
    if not triggered:
        print(f"  ✅ 未触发紧急会议 (跌幅 {abs(equity_pct):.2f}% < 阈值 {abs(EQUITY_DROP_THRESHOLD)*100:.0f}%)")
        return {'triggered': False, 'equity_pct': equity_pct}
    
    # ── 触发紧急会议 ──
    print(f"  🔴 触发紧急会议! 所有团队就位 → 四象限根因分析")
    
    today_snap = {'equity': today_equity, 'date': now.strftime('%Y-%m-%d'),
                  'positions': positions, 'position_count': len(positions),
                  'cash': cash_balance, 'cost_basis': round(cost_basis, 2)}
    
    # 诊断
    diagnosis = diagnose_four_quadrants(y_snap, today_snap)
    print(f"\n{diagnosis['summary']}")
    
    # 生成紧急会议 → DB
    _save_emergency_meeting(diagnosis, yesterday_equity, today_equity, equity_pct)
    
    return {
        'triggered': True, 'equity_pct': equity_pct,
        'diagnosis': diagnosis,
    }


# ═══════════════════════════════════════════════════
#  4. 写紧急会议 + 大厅 + 脑库
# ═══════════════════════════════════════════════════

def _save_emergency_meeting(diagnosis, yesterday_eq, today_eq, pct):
    c = _db()
    now = datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S')
    short = f"EQUITY-ALERT-{now.strftime('%Y%m%d-%H%M')}"
    
    # Q1-Q4 详情 → 会议结论
    conclusions = [f"📉 权益从 ¥{yesterday_eq} → ¥{today_eq} ({pct:+.2f}%) — 触发阈值"]
    for i in range(1, 5):
        q = diagnosis['quadrants'][f'Q{i}']
        line = f"Q{i} {q['label']}: {q['verdict']}"
        for f in q['findings'][:3]:
            if isinstance(f, dict):
                line += f"\n   · {f.get('symbol', f.get('metric', ''))} {f.get('days_held', f.get('change_pct', f.get('value', '')))}"
        conclusions.append(line)
    conclusions.append(f"🎯 主因: {diagnosis['primary_cause']}")
    
    # 紧急会议 1: loss_rescue (传统亏损挽救)
    meeting_loss = {
        "meeting_id": f"MEETING-RESCUE-{short}",
        "session_id": short, "meeting_type": "loss_rescue",
        "meeting_title": f"🚨 紧急 · 权益跌破阈值 ({pct:+.2f}%)",
        "triggered_at": ts,
        "participants": ["🏛️ 金融委员会", "👑 CEO", "🛡️ 金盾安全总监", "📈 操盘首席官 CTO",
                        "💰 风控首席官 CRO", "🧠 AI 脑库总管", "📊 数据中心总监"],
        "agenda": f"🚨 紧急权益对比触发 @ {ts}\n{diagnosis['summary']}",
        "conclusions": conclusions,
        "actions": [
            {"owner": "操盘首席官 CTO", "action": "立即执行诊断根因 — 见四象限 Q1-Q4"},
            {"owner": "风控首席官 CRO", "action": f"临时降仓 20% — 权益波动保护"},
            {"owner": "AI 脑库总管", "action": f"紧急投喂诊断结果 → 脑库 emergency_equity_{short[-8:]}"},
            {"owner": "金融委员会", "action": "1h 内出处置方案 → 大厅 dispatch"},
        ],
        "evening_seq": 99,
    }
    
    # 紧急会议 2: 四象限诊断报告会 (新类型 equity_alert)
    meeting_alert = {
        "meeting_id": f"MEETING-EQ-{short}",
        "session_id": short, "meeting_type": "equity_alert",
        "meeting_title": f"🔴 权益紧急诊断 · 四象限根因分析 ({pct:+.2f}%)",
        "triggered_at": ts,
        "participants": ["📊 数据分析师", "🧠 AI 脑库总管", "👨‍🔬 Eigenflux 52 专家会诊"],
        "agenda": f"四象限诊断报告\n{diagnosis['summary']}",
        "conclusions": conclusions,
        "actions": [
            {"owner": "chamber_bp", "action": "自动聚合到 /GOBELIN/chamber/emergency-hall"},
            {"owner": "finance_committee", "action": "30min 内确认主因"},
        ],
        "evening_seq": 99,
    }
    
    meetings = [meeting_loss, meeting_alert]
    
    for m in meetings:
        try:
            has_es = 'evening_seq' in m
            if has_es:
                c.execute("""INSERT OR REPLACE INTO mt_sandbox_meetings
                    (meeting_id, session_id, meeting_type, meeting_title,
                     triggered_at, participants, agenda, conclusions, actions, evening_seq)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (m["meeting_id"], m["session_id"], m["meeting_type"], m["meeting_title"],
                     m["triggered_at"], json.dumps(m["participants"], ensure_ascii=False),
                     m["agenda"], "\n".join(m["conclusions"]),
                     json.dumps(m["actions"], ensure_ascii=False), m["evening_seq"]))
            else:
                c.execute("""INSERT OR REPLACE INTO mt_sandbox_meetings
                    (meeting_id, session_id, meeting_type, meeting_title,
                     triggered_at, participants, agenda, conclusions, actions)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (m["meeting_id"], m["session_id"], m["meeting_type"], m["meeting_title"],
                     m["triggered_at"], json.dumps(m["participants"], ensure_ascii=False),
                     m["agenda"], "\n".join(m["conclusions"]),
                     json.dumps(m["actions"], ensure_ascii=False)))
        except Exception as e:
            print(f"  save meeting err: {e}")
    
    # 脑库投喂
    brain_summary = f"""🚨 权益紧急诊断 {now.strftime('%Y-%m-%d %H:%M')}

昨日权益: ¥{yesterday_eq}
今日权益: ¥{today_eq}
变化: {pct:+.2f}% 🔴 触发阈值 {abs(EQUITY_DROP_THRESHOLD)*100:.0f}%

四象限诊断:
{diagnosis['summary']}

处置: loss_rescue + equity_alert 会议已触发
"""
    c.execute("""INSERT INTO mt_ai_brain_feed_log
        (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_at, fed_by)
        VALUES (?,?,?,?,?,?,?)""",
        (f"EQ-ALERT-{now.strftime('%Y%m%d-%H%M')}", "finance_alert", "EQUITY_EMERGENCY",
         brain_summary[:4000], json.dumps(diagnosis, ensure_ascii=False)[:1000],
         ts, "equity_alert_engine"))
    
    # 大厅 task
    c.execute("""INSERT INTO mt_lab_task_hall
        (title, description, source, source_id, priority, status, center_id,
         publisher, publisher_role, verdict, created_at, task_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"🚨 紧急 · 权益 {pct:+.2f}% 四象限根因诊断",
         f"昨日 ¥{yesterday_eq} → 今日 ¥{today_eq} ({pct:+.2f}%) 触发阈值\n"
         f"主因: {diagnosis['primary_cause']}\n" +
         '\n'.join(f"Q{i}: {diagnosis['quadrants'][f'Q{i}']['verdict']}" for i in range(1,5)) +
         f"\n会议: {meeting_loss['meeting_id']} + {meeting_alert['meeting_id']}",
         "equity_alert_engine", f"EQ-{now.strftime('%Y%m%d-%H%M')}", 99, "DISPATCHED", "finance_committee",
         "equity_alert", "auto", "DISPATCHED", ts, "AUDIT"))
    
    c.commit()
    c.close()
    
    # 输出日志
    print(f"\n  ✅ loss_rescue 会议 → mt_sandbox_meetings #{meeting_loss['meeting_id']}")
    print(f"  ✅ equity_alert 会议 → mt_sandbox_meetings #{meeting_alert['meeting_id']}")
    print(f"  ✅ 脑库投喂 flow_id=EQ-ALERT-{now.strftime('%Y%m%d-%H%M')}")
    print(f"  ✅ 大厅 task → mt_lab_task_hall")
    print(f"{'='*55}\n")


# ═══════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', '-c', action='store_true', help='检查权益对比 (主入口)')
    ap.add_argument('--snapshot', '-s', action='store_true', help='仅保存今日快照')
    ap.add_argument('--threshold', '-t', type=float, help='覆盖阈值 (默认 -0.03 = -3%)')
    args = ap.parse_args()
    
    if args.threshold is not None:
        EQUITY_DROP_THRESHOLD = args.threshold
    
    if args.snapshot:
        save_daily_snapshot()
    elif args.check:
        run_equity_alert_check()
    else:
        # 默认: 先检查再快照
        run_equity_alert_check()
        save_daily_snapshot()
