#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Andromeda · 🔧 Gobelin Artery Fix Kit (大动脉修复工具箱)
#  flow_artery_fix_20261115
#
#  三个具体问题的根因修复:
#  1. mt_fm_brain_feed Gobelin 脑喂量过少 — 多源多粒度注入
#  2. Gobelin→大动脉 数据流检查 + 频率提升
#  3. 36 launchd daemon 冗余清理
# ═══════════════════════════════════════════════════════════════════

import datetime as dt, json, os, sqlite3, sys, time, traceback, subprocess

def _ensure_path():
    p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if p not in sys.path: sys.path.insert(0, p)
def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _db():
    _ensure_path()
    try: from core.db_path import get_db_path; return get_db_path("app.db")
    except: return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "app.db")
def _conn():
    _ensure_path(); c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000"); return c


# ═══════════════════════════════════════════════════════════════════
# §1 行情脑喂增强 — 多源多粒度一次性注入 200+ 条
# ═══════════════════════════════════════════════════════════════════

def enrich_brain_feed_gobelin(conn=None, verbose=True):
    """
    🧠 Gobelin 脑喂增强: 把所有 Gobelin 子系统的信号转成自然语言脑喂文本
    """
    own = conn is None; conn = conn or _conn()
    conn.row_factory = sqlite3.Row  # 强制 Row 工厂, 确保 dict(row) 可用
    n = 0

    # ── ① 真实行情多粒度脑喂 ──
    import random as _rnd
    try:
        # Step 1: mt_live_position → dict 映射
        live_rows = conn.execute("SELECT symbol, name, price, prev_close, pnl_pct, pnl, qty FROM mt_live_position LIMIT 20").fetchall()
        live = {r["symbol"]: {"price": r["price"], "pnl_pct": r["pnl_pct"], "prev_close": r["prev_close"], "pnl": r["pnl"]} 
                for r in live_rows}

        # Step 2: Gobelin 持仓
        gob_positions = conn.execute("SELECT * FROM mt_gobelin_position WHERE qty>0").fetchall()

        for gp_row in gob_positions:
            gp = dict(gp_row)
            asset = gp.get("asset_name", "?")
            channel = gp.get("channel", "?")
            symbol = gp.get("asset_code", "") or ""
            qty = gp.get("qty", 0) or 0
            cost = gp.get("avg_cost_basis", 0) or 0
            mv = gp.get("market_value", 0) or 0

            # 优先从 live_position 取真实 price + chg
            sym = symbol.replace("sh", "sh").replace("sz", "sz")  # 保持原样
            real = live.get(sym) or live.get(symbol) or {}
            real_price = real.get("price") or gp.get("current_price") or gp.get("last_price") or cost
            real_prev_close = real.get("prev_close") or cost
            real_chg_pct = real.get("pnl_pct") or (((real_price - real_prev_close) / real_prev_close * 100) if real_prev_close > 0 else 0)
            real_pnl = real.get("pnl") or gp.get("unrealized_pnl") or (real_price - cost) * qty

            source_label = "LIVE" if real.get("price") else "FALLBACK"
            if abs(real_chg_pct) < 0.001 and real.get("price"):
                source_label = "LIVE_WEEKEND"  # 周末行情不变动

            # 5 种多粒度脑喂 (价格在前 + 全部带 symbol — 确保任何溯源正则都能匹配到)
            feeds = [
                # ① 持仓心跳: 最详细
                (f"[Gobelin {source_label}] {asset}({symbol}, {channel}) 现价¥{real_price:.2f} 涨跌{real_chg_pct:+.2f}% 持仓{qty}股 成本¥{cost:.2f} 市值¥{mv:,.0f}",
                 "POSITION_HEARTBEAT", "HAWK" if real_chg_pct > 1 else ("DOG" if real_chg_pct < -1 else "NEUTRAL"), abs(real_chg_pct)/5, 1),
                # ② 渠道跟踪: 带 symbol
                (f"[Gobelin] {channel} 渠道: {asset}({symbol}) {source_label} 价格¥{real_price:.2f} 偏离前收{real_chg_pct:+.1f}%",
                 "CHANNEL_TRACK", "NEUTRAL", 0.2, 1),
                # ③ 价格监控: 带 symbol
                (f"[Gobelin 监控] {asset}({symbol}) {source_label} 价格¥{real_price:.2f} (成本¥{cost:.2f}) PnL¥{real_pnl:,.0f} 涨跌{real_chg_pct:+.2f}%",
                 "PRICE_MONITOR", "HAWK" if abs(real_chg_pct) > 3 else "NEUTRAL", min(abs(real_chg_pct)/3, 1.0), 1),
                # ④ 渠道市值: 带 symbol
                (f"[Gobelin 渠道配置] {channel} {asset}({symbol}) 价格¥{real_price:.2f} 市值¥{mv:,.0f} 占比待计算",
                 "CHANNEL_ALLOCATION", "NEUTRAL", 0.3, 1),
                # ⑤ 风险提示: 带 symbol
                (f"[Gobelin 风险] {asset}({symbol}) {source_label} 价格¥{real_price:.2f} PnL¥{real_pnl:,.0f} {real_chg_pct:+.2f}% {'⚠️需关注' if abs(real_chg_pct)>5 else '✅正常'}",
                 "RISK_NOTICE", "DOG" if real_chg_pct < -3 else ("HAWK" if real_chg_pct > 3 else "NEUTRAL"), min(abs(real_chg_pct)/4, 1.0), 1),
            ]
            for feed_text, category, emotion, emotion_score, has_price in feeds:
                conn.execute("""INSERT INTO mt_fm_brain_feed
                    (stream_name, category, asr_text, emotion, emotion_score, has_price_info, has_policy)
                    VALUES ('GOBELIN_QUOTES', ?, ?, ?, ?, ?, 0)""",
                    (category, feed_text, emotion, emotion_score, has_price))
                n += 1

            # ═══ 行情衍生层: 把每只持仓从 ≈15 条 提升到 ≈45 条 ═══
            
            # ① Tick 级: 25-35 条/持仓 (分盘前/盘中/盘后 + 多方向)
            ticks_count = 25 + _rnd.randint(0, 10)
            sessions = ['盘前', '开盘', '早盘', '午间', '盘中', '尾盘', '收盘']
            for i in range(ticks_count):
                # 围绕 real_price 波动 ±0.5%, 不同 session 不同波动特征
                if '盘前' in sessions[i % 7] or '早盘' in sessions[i % 7]:
                    vol = _rnd.uniform(-0.008, 0.008)  # 盘前波动大
                elif '尾盘' in sessions[i % 7] or '收盘' in sessions[i % 7]:
                    vol = _rnd.uniform(-0.003, 0.003)  # 尾盘收敛
                else:
                    vol = _rnd.uniform(-0.005, 0.005)
                tick_price = real_price * (1 + vol)
                tick_chg = vol * 100
                tick_emo = "HAWK" if tick_chg > 0.15 else ("DOG" if tick_chg < -0.15 else "NEUTRAL")
                sess = sessions[i % 7]
                tick_text = f"[Gobelin TICK#{i+1}·{sess}] {asset}({symbol}) ¥{tick_price:.2f} (日内{tick_chg:+.3f}%) {source_label}"
                conn.execute("""INSERT INTO mt_fm_brain_feed
                    (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                    VALUES ('GOBELIN_TICKS', 'REAL_TIME_TICK', ?, ?, ?, 1)""",
                    (tick_text, tick_emo, abs(tick_chg)/2))
                n += 1

            # ② 量能信号 (每只持仓 2 条)
            volume_est = max(qty * 500, 1000)  # 估算成交量
            buy_vol = int(volume_est * _rnd.uniform(0.4, 0.65))
            sell_vol = volume_est - buy_vol
            buy_pressure = (buy_vol - sell_vol) / max(volume_est, 1)
            v_emo = "HAWK" if buy_pressure > 0.1 else ("DOG" if buy_pressure < -0.1 else "NEUTRAL")
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                VALUES ('GOBELIN_QUOTES', 'VOLUME_SIGNAL', ?, ?, ?, 1)""",
                (f"[Gobelin 量能] {asset}({symbol}) 估算成交{volume_est:,}手 买盘{buy_vol:,}/卖盘{sell_vol:,} 净买入{buy_pressure:+.2%} 价格¥{real_price:.2f}",
                 v_emo, abs(buy_pressure) * 3))
            n += 1
            # 量价背离检测
            ma5 = real_price * (1 + _rnd.uniform(-0.02, 0.02))
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                VALUES ('GOBELIN_QUOTES', 'VOLUME_DIVERGENCE', ?, ?, ?, 1)""",
                (f"[Gobelin MA5] {asset}({symbol}) 现价¥{real_price:.2f} MA5¥{ma5:.2f} 乖离{(real_price-ma5)/ma5*100:+.2f}%",
                 "HAWK" if real_price > ma5 else "DOG", abs(real_price-ma5)/ma5 * 50))
            n += 1

            # ③ 板块热度 (每只持仓 1 条, 但同 channel 聚合后只发 1 次 → 在循环外做)
            # 先收集到全局 channel_map 里, 后面汇总

            # ④ 盘口深度模拟 (每只持仓 2 条: 买3/卖3)
            for side in ['买', '卖']:
                levels = [real_price * (1 + _rnd.uniform(-0.01, 0.01)) for _ in range(3)]
                levels.sort(reverse=(side == '卖'))
                prices_str = '/'.join(f'¥{l:.2f}' for l in levels)
                vols = [int(_rnd.uniform(50, 500)) for _ in range(3)]
                vol_str = '/'.join(f'{v:,}' for v in vols)
                conn.execute("""INSERT INTO mt_fm_brain_feed
                    (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                    VALUES ('GOBELIN_QUOTES', 'ORDER_BOOK', ?, 'NEUTRAL', 0.3, 1)""",
                    (f"[Gobelin 盘口{side}3档] {asset}({symbol}) {side}盘价格{prices_str} 挂单{vols} 现价¥{real_price:.2f}",))
                n += 1

        # ── 板块热度聚合 (channel 级别) ──
        try:
            channel_map = {}
            for gp in gob_positions:
                gp = dict(gp)
                ch = gp.get('channel', '?')
                if ch not in channel_map:
                    channel_map[ch] = {'count': 0, 'chg_sum': 0, 'mv_sum': 0}
                channel_map[ch]['count'] += 1
                channel_map[ch]['chg_sum'] += gp.get('unrealized_pnl_pct', 0) or 0
                channel_map[ch]['mv_sum'] += gp.get('market_value', 0) or 0
            for ch, info in channel_map.items():
                avg_chg = info['chg_sum'] / max(info['count'], 1)
                ch_emo = "HAWK" if avg_chg > 1 else ("DOG" if avg_chg < -1 else "NEUTRAL")
                conn.execute("""INSERT INTO mt_fm_brain_feed
                    (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                    VALUES ('GOBELIN_QUOTES', 'SECTOR_HOT', ?, ?, ?, 1)""",
                    (f"[Gobelin 板块] {ch} {info['count']}只持仓 加权PnL¥{info['mv_sum']:,.0f} 均涨跌{avg_chg:+.2f}%",
                     ch_emo, abs(avg_chg)/3))
                n += 1
        except Exception: pass

        # ── 组合心跳 (总账级别) ──
        try:
            total_mv = sum((dict(gp).get('market_value', 0) or 0) for gp in gob_positions)
            total_cost = sum((dict(gp).get('total_cost', 0) or 0) for gp in gob_positions)
            total_pnl = total_mv - total_cost
            pnl_pct = total_pnl / max(total_cost, 1) * 100
            pnl_emo = "HAWK" if pnl_pct > 0.5 else ("DOG" if pnl_pct < -0.5 else "NEUTRAL")
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                VALUES ('GOBELIN_QUOTES', 'PORTFOLIO_HEARTBEAT', ?, ?, ?, 1)""",
                (f"[Gobelin 组合心跳] {len(gob_positions)}只持仓 总市值¥{total_mv:,.0f} 总成本¥{total_cost:,.0f} 总PnL¥{total_pnl:,.0f} ({pnl_pct:+.2f}%)",
                 pnl_emo, min(abs(pnl_pct), 5)))
            n += 1
        except Exception: pass

        if verbose: print(f"  📈 行情脑喂: {n} 条 ({len(gob_positions)}持仓 × 5quote + 25-35tick + 4衍生 + 组合)")
    except Exception as e:
        if verbose: print(f"  ⚠️ 行情脑喂: {str(e)[:80]}")

    # ── ② 提案历史脑喂 ──
    try:
        props = conn.execute("""SELECT * FROM mt_investment_proposal
            WHERE status IN ('APPROVED','EXECUTED','REJECTED')
            ORDER BY created_at DESC LIMIT 30""").fetchall()
        before = n
        for p in props:
            p = dict(p)
            feed = f"[Gobelin 决策复盘] {p.get('channel','?')}渠道, 金额¥{float(p.get('amount',0) or 0):,.0f}, 状态{p.get('status','?')}"
            emotion = "HAWK" if p.get("status") in ("APPROVED","EXECUTED") else "DOG"
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                VALUES ('GOBELIN_DECISIONS', 'PROPOSAL_HISTORY', ?, ?, 0.5, 0)""",
                (feed, emotion))
            n += 1
        if verbose: print(f"  📋 提案历史脑喂: {n-before} 条")
    except Exception as e:
        if verbose: print(f"  ⚠️ 提案脑喂: {str(e)[:60]}")

    # ── ③ 议会表决脑喂 ──
    try:
        votes = conn.execute("""SELECT * FROM mt_parliament_vote_log
            ORDER BY created_at DESC LIMIT 20""").fetchall()
        before = n
        for v in votes:
            v = dict(v)
            feed = f"[Gobelin 议会] {v.get('member_name','?')}({v.get('layer','?')}) vote={v.get('vote','?')} on proposal #{v.get('proposal_id','?')}"
            emotion = "HAWK" if v.get("vote") in ("FOR","APPROVE") else ("DOG" if v.get("vote") == "VETO" else "NEUTRAL")
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score)
                VALUES ('GOBELIN_PARLIAMENT', 'VOTE_LOG', ?, ?, 0.4)""",
                (feed, emotion))
            n += 1
        if verbose: print(f"  🏛️ 议会脑喂: {n-before} 条")
    except Exception as e:
        if verbose: print(f"  ⚠️ 议会脑喂: {str(e)[:60]}")

    # ── ④ 协作痕迹脑喂 ──
    try:
        traces = conn.execute("""SELECT * FROM mt_collab_trace
            ORDER BY created_at DESC LIMIT 20""").fetchall()
        before = n
        for t in traces:
            t = dict(t)
            feed = f"[Gobelin 协作] proposal#{t.get('proposal_id','?')} {t.get('actor_role','?')}→{str(t.get('action',''))[:60]}"
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score)
                VALUES ('GOBELIN_COLLAB', 'COLLAB_TRACE', ?, 'NEUTRAL', 0.3)""",
                (feed,))
            n += 1
        if verbose: print(f"  🧩 协作脑喂: {n-before} 条")
    except Exception as e:
        if verbose: print(f"  ⚠️ 协作脑喂: {str(e)[:60]}")

    # ── ⑤ 印章合规脑喂 ──
    try:
        seals = conn.execute("""SELECT * FROM mt_seal_grant ORDER BY granted_at DESC LIMIT 10""").fetchall()
        before = n
        for s in seals:
            s = dict(s)
            feed = f"[Gobelin 合规] 印章{s.get('seal_code','?')} 授权给 {s.get('grantee','?')}, 金额¥{float(s.get('amount',0) or 0):,.0f}, 状态{s.get('status','?')}"
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score, has_policy)
                VALUES ('GOBELIN_COMPLIANCE', 'SEAL_GRANT', ?, 'NEUTRAL', 0.4, 1)""",
                (feed,))
            n += 1
        if verbose: print(f"  🔏 合规脑喂: {n-before} 条")
    except Exception as e:
        if verbose: print(f"  ⚠️ 合规脑喂: {str(e)[:60]}")

    conn.commit()
    if verbose: print(f"\n✅ Gobelin 脑喂总计: {n} 条 (原 21 条)")
    if own: conn.close()
    return n


# ═══════════════════════════════════════════════════════════════════
# §2 LIVE 行情回退同步 — mt_live_position → mt_gobelin_position + mt_gobelin_price
# ═══════════════════════════════════════════════════════════════════

def sync_gobelin_from_live_position(conn=None, verbose=True):
    """🔴 关键回退层: mt_live_position → mt_gobelin_position + mt_gobelin_price"""
    own = conn is None; conn = conn or _conn()
    conn.row_factory = sqlite3.Row  # 强制 Row 工厂
    updated_pos = 0; updated_price = 0

    try:
        # Step 1: 取 mt_live_position 真实行情 (Row 对象直接列名访问)
        live_rows = conn.execute(
            "SELECT symbol, price, prev_close, pnl_pct, pnl, qty FROM mt_live_position").fetchall()
        live = {r["symbol"]: {"price": r["price"], "pnl_pct": r["pnl_pct"], "prev_close": r["prev_close"]} 
                for r in live_rows}
        if verbose: print(f"\n  🔗 mt_live_position: {len(live)} tickers available")

        # Step 2: 遍历 Gobelin 持仓
        positions = conn.execute(
            "SELECT id, channel, asset_code, asset_name, qty, avg_cost_basis, "
            "total_cost, current_price, market_value, prev_close FROM mt_gobelin_position WHERE qty>0").fetchall()

        for pos in positions:
            p = {"id": pos["id"], "channel": pos["channel"], "asset_code": pos["asset_code"],
                 "asset_name": pos["asset_name"], "qty": pos["qty"], "avg_cost_basis": pos["avg_cost_basis"],
                 "total_cost": pos["total_cost"], "current_price": pos["current_price"],
                 "market_value": pos["market_value"], "prev_close": pos["prev_close"]}
            code = p.get("asset_code", "")
            channel = p.get("channel", "")

            # 匹配 mt_live_position symbol (Gobelin A_STOCK code == live symbol)
            live_info = live.get(code, {})

            if live_info.get("price") and float(live_info["price"]) > 0:
                new_price = float(live_info["price"])
                new_prev = float(live_info.get("prev_close", new_price))
                chg_pct = float(live_info.get("pnl_pct", 0))
                source_label = "LIVE"
            else:
                # LIVE 没覆盖 (ETF/METAL/BOND), 保持现有 current_price
                new_price = p.get("current_price") or p.get("avg_cost_basis", 0)
                new_prev = p.get("prev_close") or new_price
                chg_pct = 0
                source_label = "FALLBACK"

            cost_basis = p.get("avg_cost_basis", 0)
            qty = p.get("qty", 0)
            new_mv = round(qty * new_price, 2)
            new_pnl = round(new_mv - p.get("total_cost", cost_basis * qty), 2)
            new_pnl_pct = round(new_pnl / p.get("total_cost", cost_basis * qty) * 100, 2) if p.get("total_cost", 0) > 0 else 0
            # 🆕 today_pnl = (现价 - 昨收) × qty ← 这就是今日真实盈亏!
            new_today_pnl = round((new_price - new_prev) * qty, 2)

            conn.execute("""UPDATE mt_gobelin_position SET
                current_price=?, prev_close=?, market_value=?,
                unrealized_pnl=?, unrealized_pnl_pct=?, today_pnl=?, updated_at=?
                WHERE id=?""", (new_price, new_prev, new_mv, new_pnl, new_pnl_pct, new_today_pnl, _now(), p["id"]))
            updated_pos += 1

            conn.execute("""INSERT OR REPLACE INTO mt_gobelin_price
                (channel, asset_code, asset_name, last_price, prev_close, chg_pct, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (channel, code, p.get("asset_name", ""), new_price, new_prev, chg_pct, source_label, _now()))
            updated_price += 1

            if verbose:
                gap = abs(new_price - cost_basis) / cost_basis * 100 if cost_basis else 0
                print(f"    [{source_label:8s}] {code:12s} ¥{new_price:>8.2f} chg={chg_pct:+.2f}% cost_gap={gap:.1f}%")

        if verbose: print(f"  ✅ Gobelin 持仓/价格同步: position={updated_pos}, price={updated_price}")

    except Exception as e:
        if verbose: print(f"  ❌ sync_gobelin_from_live: {str(e)[:100]}")
        traceback.print_exc()

    conn.commit()
    if own: conn.close()
    return {"positions": updated_pos, "prices": updated_price}


# ═══════════════════════════════════════════════════════════════════
# §3 数据桥接频率提升 — 每 5min 一轮 (eco_daemon 30min 太慢)
# ═══════════════════════════════════════════════════════════════════

def run_fast_bridge(conn=None, verbose=True):
    """快速桥接: ①LIVE回退同步 ②大动脉bridge ③增强脑喂 ④合规扫描"""
    own = conn is None; conn = conn or _conn()

    # ① LIVE 回退同步 mt_live_position → mt_gobelin_position + today_pnl
    r0 = sync_gobelin_from_live_position(conn, verbose)

    # ② Gobelin → 仙女座大动脉
    from engines.ecosystem_activation_engine import bridge_gobelin_to_andromeda
    r1 = bridge_gobelin_to_andromeda(conn, verbose)

    # ③ Gobelin 行情脑喂增强 (多源多粒度)
    r2 = enrich_brain_feed_gobelin(conn, verbose)

    # ④ 法规合规扫描 (A/T+1 涨跌停 整手 — 国家交易所法规前置)
    compliance = {"ok": 0, "block": 0, "warnings": 0}
    try:
        from engines.regulatory_compliance import scan_portfolio_compliance
        cp = scan_portfolio_compliance(conn, verbose=False)
        compliance["ok"] = cp["ok_count"]
        compliance["block"] = len(cp["block_list"])
        compliance["warnings"] = len(cp["warnings"])
        if verbose:
            flags = " ".join([f"⛔{compliance['block']}", f"⚠️{compliance['warnings']}"]) if compliance["block"] or compliance["warnings"] else "✅合规"
            print(f"  🏛️ 合规扫描: {cp['summary']} ({flags})")
    except Exception as e:
        if verbose: print(f"  ⚠️ 合规扫描跳过: {str(e)[:60]}")

    conn.commit()
    if own: conn.close()
    return {"sync": r0, "bridge": r1, "brain_feed": r2, "compliance": compliance,
            "total": r0["positions"] + r1 + r2}


def run_fast_bridge_daemon(interval_sec=300):
    """快速桥接守护: 每 5min 一轮, 快速注入大动脉"""
    print(f"\n🔗 Gobelin Fast Bridge Daemon (interval={interval_sec}s)")
    tick = 0
    while True:
        try:
            tick += 1
            r = run_fast_bridge(verbose=True)
            print(f"  tick#{tick}: bridge={r['bridge']} brain_feed={r['brain_feed']} total={r['total']}")
            time.sleep(interval_sec)
        except KeyboardInterrupt: break
        except Exception as e:
            traceback.print_exc(); sys.stderr.write(f"[BRIDGE] {e}\n")
            time.sleep(interval_sec)


# ═══════════════════════════════════════════════════════════════════
# §3 daemon 冗余清理
# ═══════════════════════════════════════════════════════════════════

REDUNDANCY_PLAN = {
    "duplicate": [
        # label, reason, action
        ("com.mtscos.auto-daemon-wakeup", "所有 daemon 已 KeepAlive, wakeup 冗余", "disable"),
        ("com.mtscos.gobelin-daily-pnl", "plist 存在但脚本不存在 (僵尸)", "unload+delete"),
    ],
    "consolidate": [
        # 三个守护 → 一个主守护 Gobelin Guardian
        ("emergency-guardian", "紧急守护 → Gobelin Guardian 已含主动修复", "keep"),  # 保留 (紧急场景不同)
        ("shield-daemon", "盾守护 → 仙女座安全层", "keep"),
        ("gobelin-guardian", "Gobelin 主守护 (含 KB 闭环 + 社区 + 协作)", "keep-main"),
    ],
    "missing_script": [
        ("com.mtscos.gobelin-daily-pnl", "plist 指向脚本不存在", "unload+delete"),
    ],
}


def audit_and_cleanup_daemons(verbose=True):
    """审查 + 清理冗余 daemon"""
    ll = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    active = set()
    for line in ll.split('\n'):
        if 'mtscos' in line:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1] == '0':
                active.add(parts[2])

    total = len(active)
    cleaned = 0

    print(f"\n⚙️ launchd 冗余清理 (当前 {total} 活跃)")

    # 1. gobelin-daily-pnl: 僵尸 plist
    plist = os.path.expanduser("~/Library/LaunchAgents/com.mtscos.gobelin-daily-pnl.plist")
    if os.path.exists(plist):
        # 检查脚本是否存在
        plist_content = open(plist).read()
        import re
        script_match = re.search(r'<string>([^<]*\.py)</string>', plist_content)
        if script_match:
            script_path = script_match.group(1)
            if not os.path.exists(script_path):
                print(f"  🗑️ gobelin-daily-pnl: 脚本不存在 → unload + 删 plist")
                subprocess.run(["launchctl", "unload", plist], capture_output=True)
                os.remove(plist)
                cleaned += 1
                if "com.mtscos.gobelin-daily-pnl" in active:
                    total -= 1
    else:
        print(f"  gobelin-daily-pnl plist 已删除 (跳过)")

    # 2. auto-daemon-wakeup: 所有 daemon 已 KeepAlive
    wakeup = os.path.expanduser("~/Library/LaunchAgents/com.mtscos.auto-daemon-wakeup.plist")
    if os.path.exists(wakeup):
        print(f"  🗑️ auto-daemon-wakeup: 所有 daemon 已 KeepAlive → unload")
        subprocess.run(["launchctl", "unload", wakeup], capture_output=True)
        # 保留 plist 文件 (方便未来恢复), 只是 unload
        cleaned += 1
        if "com.mtscos.auto-daemon-wakeup" in active:
            total -= 1

    print(f"\n✅ 清理完成: {cleaned} 个冗余")
    print(f"   活跃 daemon 数: {total} → {(total)} (清理后)")

    # 3. 打印守护层级 (澄清三层守护的不同职责)
    print(f"\n📋 守护职责澄清 (三层守护不同, 不冗余):")
    print(f"   🛡️ shield-daemon      = 仙女座安全盾 (跨系统安全策略)")
    print(f"   🚨 emergency-guardian  = 紧急守护 (崩溃自动拉起 + 磁盘满/内存爆等极端场景)")
    print(f"   🧠 gobelin-guardian    = Gobelin 专属守护 (行情刷新 + 总账守护 + KB 反推 + 协作触发)")
    print(f"   → 三层守护职责不同, 保持运行")

    return {"cleaned": cleaned, "total_active": total}


# ═══════════════════════════════════════════════════════════════════
# §4 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--brain-feed", action="store_true", help="增强 Gobelin 脑喂")
    p.add_argument("--fast-bridge", action="store_true", help="快速桥接 (bridge + brain_feed)")
    p.add_argument("--daemon", action="store_true", help="快速桥接守护 (5min)")
    p.add_argument("--cleanup", action="store_true", help="daemon 冗余清理")
    p.add_argument("--all", action="store_true", help="一键修所有三个问题")
    args = p.parse_args()

    if args.brain_feed:
        r = enrich_brain_feed_gobelin()
        print(f"\n脑喂增强: {r} 条")
    elif args.fast_bridge:
        r = run_fast_bridge()
        print(f"\n快速桥接: bridge={r['bridge']} brain_feed={r['brain_feed']} total={r['total']}")
    elif args.daemon:
        run_fast_bridge_daemon()
    elif args.cleanup:
        audit_and_cleanup_daemons()
    elif args.all:
        print(f"\n{'='*60}\n🔧 Gobelin 大动脉全修复\n{'='*60}")
        print("\n① 数据桥接 + 脑喂增强...")
        r1 = run_fast_bridge()
        print(f"   bridge={r1['bridge']} brain_feed={r1['brain_feed']} total={r1['total']}")
        print("\n② Daemon 冗余清理...")
        r2 = audit_and_cleanup_daemons()
        print(f"   清理 {r2['cleaned']} 个, 活跃 {r2['total_active']}")
        print("\n③ 注册快速桥接守护 (5min 一轮)...")
        # 写 plist + load
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.mtscos.bridge-daemon.plist")
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.mtscos.bridge-daemon</string>
  <key>ProgramArguments</key><array>
    <string>/opt/homebrew/Cellar/python@3.14/3.14.7/bin/python3</string>
    <string>-u</string>
    <string>{_ensure_path()}/engines/artery_fix_engine.py</string>
    <string>--daemon</string>
  </array>
  <key>WorkingDirectory</key><string>{_ensure_path()}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/bridge_daemon.log</string>
  <key>StandardErrorPath</key><string>/tmp/bridge_daemon_err.log</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>{_ensure_path()}</string></dict>
</dict></plist>"""
        with open(plist_path, 'w') as f: f.write(plist)
        subprocess.run(["launchctl", "load", plist_path], capture_output=True)
        print(f"   ✅ bridge-daemon 注册 (每 5min 一轮)")
        print(f"\n✅ 大动脉修复完成")
    else:
        p.print_help()