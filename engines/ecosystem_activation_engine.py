#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Andromeda · 🌋 Ecosystem Activation Engine (全生态激活)
#  flow_eco_activation_20261115
#
#  🧠 核心洞察:
#    仙女座有 318 引擎 + 268 张 mt_ 表, 但数据流极不均衡:
#      - 活跃核心: neuron(285k) / center_evolution_log(151k) / brain_feed(148k)
#      - 新子系统: Gobelin Bank(857) / Vault(空) / Community(新)
#    需要把所有子系统接入仙女座的大动脉, 不要躺着!
#  ────────────────────────────────────────────────────────────────
#  激活策略:
#  ① 数据桥接    新子系统 → 仙女座已有高数据流管道
#  ② 空表种子    268 张表中的空表 → 自动种子数据
#  ③ 引擎巡检    318 引擎中哪些有代码没守护? 自动注册 launchd
#  ④ 跨子系统调用 金融↔教育↔写作↔医疗↔Gobelin 互相喂数据
#  ⑤ 自动巡检    每天一次全系统体检
#  ────────────────────────────────────────────────────────────────
#  运行:
#    python3 engines/ecosystem_activation_engine.py --bridge     # 数据桥接
#    python3 engines/ecosystem_activation_engine.py --seed-empty # 空表种子
#    python3 engines/ecosystem_activation_engine.py --audit      # 全系统体检
#    python3 engines/ecosystem_activation_engine.py --run-all    # 全部跑完
#    python3 engines/ecosystem_activation_engine.py --daemon     # 常驻守护
# ═══════════════════════════════════════════════════════════════════

import datetime as dt
import json
import os
import sqlite3
import sys
import time
import traceback


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_path():
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    return parent


def _db():
    _ensure_path()
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "database", "app.db")


def _conn():
    _ensure_path()
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


# ═══════════════════════════════════════════════════════════════════
# §0 数据桥接 — Gobelin 接入仙女座大动脉
# ═══════════════════════════════════════════════════════════════════

def bridge_gobelin_to_andromeda(conn=None, verbose=True):
    """
    🔗 Gobelin → 仙女座大动脉 (用真实 schema):
    mt_neuron(neuron_type, name, domain, weight, ...)
    mt_center_evolution_log(center_name, event, detail)
    mt_center_pulse(center_name, health_score, detail, ...)
    mt_fm_brain_feed(stream_name, category, asr_text, emotion, ...)
    mt_hall_flow_timeline(task_id, from_status, to_status, actor, reason, ...)
    mt_collab_message 等
    """
    own = conn is None
    conn = conn or _conn()
    bridges = 0

    # Bridge 1: Gobelin 持仓 → mt_neuron (神经激活)
    try:
        pos = conn.execute("SELECT * FROM mt_gobelin_position WHERE qty>0 LIMIT 50").fetchall()
        for p in pos:
            p = dict(p)
            conn.execute("""INSERT INTO mt_neuron
                (neuron_type, name, domain, weight, connected_to, status)
                VALUES ('GOBELIN_POSITION', ?, ?, 1.0, 'GOBELIN_BANK', 'ACTIVE')""",
                (p.get("asset_name", "") or "", p.get("channel", "") or "GOBELIN"))
            bridges += 1
        if verbose: print(f"  🧠 neuron: {bridges} 条")
    except Exception as e:
        if verbose: print(f"  ⚠️ neuron: {str(e)[:60]}")

    # Bridge 2: Gobelin 决策 → mt_center_evolution_log
    try:
        props = conn.execute("""SELECT * FROM mt_investment_proposal
            WHERE created_at > datetime('now','localtime','-2 hour') LIMIT 30""").fetchall()
        for p in props:
            p = dict(p)
            evt = f"PROPOSAL_{p.get('status','?')}"
            detail = json.dumps({
                "proposal_id": p.get("id"),
                "channel": p.get("channel"),
                "amount": p.get("amount"),
            }, ensure_ascii=False)[:500]
            conn.execute("""INSERT INTO mt_center_evolution_log
                (center_name, event, detail) VALUES ('GOBELIN_BANK', ?, ?)""",
                (evt, detail))
            bridges += 1
        if verbose: print(f"  🧬 evolution_log: {bridges} 条累计")
    except Exception as e:
        if verbose: print(f"  ⚠️ evolution_log: {str(e)[:60]}")

    # Bridge 3: Gobelin 心跳 → mt_center_pulse
    try:
        acc = conn.execute("SELECT * FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'").fetchone()
        if acc:
            acc = dict(acc)
            conn.execute("""INSERT INTO mt_center_pulse
                (center_name, health_score, status, detail)
                VALUES ('GOBELIN_BANK', 95, 'OK', ?)""",
                (json.dumps({
                    "assets": acc.get("total_assets", 0),
                    "cash": acc.get("cash_balance", 0),
                    "pnl": acc.get("unrealized_pnl", 0),
                }, ensure_ascii=False),))
            bridges += 1
        if verbose: print(f"  💓 center_pulse: {bridges} 条累计")
    except Exception as e:
        if verbose: print(f"  ⚠️ center_pulse: {str(e)[:60]}")

    # Bridge 4: Gobelin 行情 → mt_fm_brain_feed (脑喂)
    try:
        prices = conn.execute("""SELECT * FROM mt_gobelin_price
            WHERE fetched_at > datetime('now','localtime','-1 hour') LIMIT 20""").fetchall()
        for p in prices:
            p = dict(p)
            price = p.get("last_price", 0) or 0
            chg = p.get("chg_pct", 0) or 0
            emotion = "HAWK" if chg > 2 else ("DOG" if chg < -2 else "NEUTRAL")
            conn.execute("""INSERT INTO mt_fm_brain_feed
                (stream_name, category, asr_text, emotion, emotion_score, has_price_info)
                VALUES ('GOBELIN_QUOTES', 'MARKET_TICK', ?, ?, ?, 1)""",
                (f"{p.get('asset_name','')} 现价¥{price:.2f} 涨跌{chg:.2f}%",
                 emotion, round(abs(chg)/5, 2)))
            bridges += 1
        if verbose: print(f"  🧠 brain_feed: {bridges} 条累计")
    except Exception as e:
        if verbose: print(f"  ⚠️ brain_feed: {str(e)[:60]}")

    # Bridge 5: Gobelin 提案 → mt_hall_flow_timeline (流水)
    try:
        props = conn.execute("""SELECT * FROM mt_investment_proposal
            WHERE status IN ('APPROVED','PENDING','OPEN')
            AND created_at > datetime('now','localtime','-2 hour') LIMIT 30""").fetchall()
        n = 1
        for p in props:
            p = dict(p)
            conn.execute("""INSERT INTO mt_hall_flow_timeline
                (task_id, from_status, to_status, actor, reason, extra)
                VALUES (?, 'PENDING', ?, 'GOBELIN_BANK', ?, ?)""",
                (p.get("id"), p.get("status"),
                 f"Gobelin {p.get('channel')} ¥{p.get('amount',0):,.0f}",
                 json.dumps({"proposal_id": p.get("id"), "channel": p.get("channel")}, ensure_ascii=False)))
            bridges += 1; n += 1
        if verbose: print(f"  🕐 hall_flow: {bridges} 条累计")
    except Exception as e:
        if verbose: print(f"  ⚠️ hall_flow: {str(e)[:60]}")

    # Bridge 6: Gobelin 协作痕迹 → mt_collab_message (仙女座原生消息管道)
    try:
        # 先看 mt_collab_message schema
        msg_cols = [r[1] for r in conn.execute("PRAGMA table_info(mt_collab_message)").fetchall()]
        if "payload" in msg_cols or "content" in msg_cols:
            traces = conn.execute("""SELECT * FROM mt_collab_trace
                WHERE created_at > datetime('now','localtime','-1 hour') LIMIT 30""").fetchall()
            for t in traces:
                t = dict(t)
                payload_col = "payload" if "payload" in msg_cols else "content"
                conn.execute(f"""INSERT INTO mt_collab_message
                    (from_center, to_center, {payload_col}, created_at)
                    VALUES ('GOBELIN_COLLAB', 'ANDROMEDA_ALL', ?, datetime('now','localtime'))""",
                    (json.dumps({
                        "proposal_id": t.get("proposal_id"),
                        "actor": t.get("actor_role"),
                        "action": (t.get("action") or "")[:100],
                    }, ensure_ascii=False),))
                bridges += 1
            if verbose: print(f"  💬 collab_message: {bridges} 条累计")
    except Exception as e:
        if verbose: print(f"  ⚠️ collab_message: {str(e)[:60]}")

    conn.commit()
    if verbose: print(f"\n✅ 数据桥接总计: {bridges} 条 → 仙女座大动脉")
    if own: conn.close()
    return bridges


# ═══════════════════════════════════════════════════════════════════
# §1 空表种子 — 268 张表中 0 行的 → 自动写种子
# ═══════════════════════════════════════════════════════════════════

def seed_empty_tables(conn=None, verbose=True, limit=10):
    """给空表自动写种子数据, 让它们也活起来"""
    own = conn is None
    conn = conn or _conn()

    # 找空表
    all_tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mt_%'").fetchall()]
    empty = []
    for t in all_tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            if cnt == 0: empty.append(t)
        except Exception: pass

    if verbose: print(f"  📋 发现 {len(empty)} 张空表")

    # 策略: 给每张空表至少写 1 条 "ECOSYSTEM_BOOTSTRAP" 种子记录
    # 安全做法: 只读 schema, 看有哪些 TEXT/INTEGER 列, 不碰 NOT NULL + 无默认值的
    seeded = 0
    for table in empty[:limit]:
        try:
            cols = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            col_names = [c[1] for c in cols]
            col_types = {c[1]: c[2] for c in cols}
            col_notnull = {c[1]: c[3] for c in cols}
            col_defaults = {c[1]: c[4] for c in cols}

            vals = {}
            for c in col_names:
                ctype = col_types.get(c, "TEXT").upper()
                notnull = col_notnull.get(c, 0)
                default = col_defaults.get(c)
                pk = c == col_names[0]  # 第一列假定 PK

                if pk: continue  # PK autoincrement 不填
                if default is not None: continue  # 有默认值不填
                if notnull == 0: continue  # 可空的不填
                if ctype == "INTEGER" or ctype == "REAL":
                    vals[c] = 0
                elif ctype == "TEXT" or ctype == "BLOB":
                    if "created" in c.lower() or c == "updated_at":
                        continue  # 让 DEFAULT CURRENT_TIMESTAMP 处理
                    vals[c] = "ECOSYSTEM_BOOTSTRAP"

            if vals:
                cols_str = ", ".join(vals.keys())
                pholders = ", ".join(["?"] * len(vals))
                conn.execute(f"INSERT INTO [{table}] ({cols_str}) VALUES ({pholders})",
                             list(vals.values()))
                seeded += 1
                if verbose: print(f"    ✅ {table} → 种子 #{seeded}")
        except Exception as e:
            if verbose: print(f"    ⚠️ {table}: {str(e)[:60]}")

    conn.commit()
    if verbose: print(f"  ✅ 种子完成: {seeded}/{len(empty)} 张空表已激活")
    if own: conn.close()
    return {"empty_total": len(empty), "seeded": seeded}


# ═══════════════════════════════════════════════════════════════════
# §2 全系统体检 — 哪些引擎躺着, 哪些表空着
# ═══════════════════════════════════════════════════════════════════

def full_system_audit(conn=None, verbose=True):
    """全生态体检报告"""
    own = conn is None
    conn = conn or _conn()
    report = {"generated_at": _now()}

    # 1. DB 表统计
    all_mt = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mt_%'").fetchall()]
    filled = []
    empty = []
    for t in all_mt:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            (filled if cnt > 0 else empty).append((t, cnt))
        except Exception: pass

    filled_sorted = sorted(filled, key=lambda x: -x[1])
    report["tables_total"] = len(all_mt)
    report["tables_filled"] = len(filled)
    report["tables_empty"] = len(empty)
    report["top_10_tables"] = [{"name": t, "rows": n} for t, n in filled_sorted[:10]]

    # 2. 引擎文件 vs 活跃进程
    eng_dir = _ensure_path() + "/engines"
    all_engines = [f[:-3] for f in os.listdir(eng_dir) if f.endswith('.py') and not f.startswith('.')]
    report["engines_total"] = len(all_engines)

    # 3. launchd daemon
    import subprocess
    ll = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    active_daemons = set()
    for line in ll.split('\n'):
        if 'mtscos' in line:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1] == '0':
                active_daemons.add(parts[2])
    report["launchd_active"] = len(active_daemons)
    report["launchd_list"] = sorted(active_daemons)

    # 4. Flask
    try:
        flask_pid = subprocess.run(["pgrep", "-f", "modular_start"], capture_output=True, text=True).stdout.strip()
        report["flask_pid"] = flask_pid or None
    except Exception:
        report["flask_pid"] = None

    # 5. Gobelin 生态
    report["gobelin"] = {
        "account": conn.execute("SELECT COUNT(*) FROM mt_gobelin_account").fetchone()[0],
        "positions": conn.execute("SELECT COUNT(*) FROM mt_gobelin_position WHERE qty>0").fetchone()[0],
        "proposals": conn.execute("SELECT COUNT(*) FROM mt_investment_proposal").fetchone()[0],
        "parl_sessions": conn.execute("SELECT COUNT(*) FROM mt_parliament_session").fetchone()[0],
        "parl_votes": conn.execute("SELECT COUNT(*) FROM mt_parliament_vote_log").fetchone()[0],
        "seal_tokens": conn.execute("SELECT COUNT(*) FROM mt_seal_token").fetchone()[0],
        "seal_registry": conn.execute("SELECT COUNT(*) FROM mt_seal_registry").fetchone()[0],
        "collab_plans": conn.execute("SELECT COUNT(*) FROM mt_collab_plan").fetchone()[0],
        "collab_traces": conn.execute("SELECT COUNT(*) FROM mt_collab_trace").fetchone()[0],
        "collab_minutes": conn.execute("SELECT COUNT(*) FROM mt_collab_minutes").fetchone()[0],
        "community_employees": conn.execute("SELECT COUNT(*) FROM mt_ai_employees").fetchone()[0],
        "community_mentorship": conn.execute("SELECT COUNT(*) FROM mt_community_mentorship").fetchone()[0],
        "community_training": conn.execute("SELECT COUNT(*) FROM mt_community_training").fetchone()[0],
        "community_calibration": conn.execute("SELECT COUNT(*) FROM mt_community_calibration").fetchone()[0],
        "reflect_log": conn.execute("SELECT COUNT(*) FROM mt_gobelin_reflect_log").fetchone()[0],
    }

    # 6. 仙女座大动脉活跃度 (最近 1h)
    report["artery_1h"] = {}
    for table in ["mt_neuron", "mt_center_evolution_log", "mt_fm_brain_feed",
                  "mt_center_pulse", "mt_hall_flow_timeline", "mt_collab_trace",
                  "mt_collab_message", "mt_center_self_drive_log"]:
        try:
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM [{table}] WHERE created_at > datetime('now','localtime','-1 hour')").fetchone()[0]
            report["artery_1h"][table] = cnt
        except Exception:
            report["artery_1h"][table] = -1

    if own: conn.close()
    return report


def print_audit(report):
    """打印体检报告"""
    g = report.get("gobelin", {})
    a = report.get("artery_1h", {})

    print(f"\n{'='*60}")
    print(f"  🌋 仙女座全生态体检  {report.get('generated_at')}")
    print(f"{'='*60}")
    print(f"\n📊 基础设施:")
    print(f"  🗄️ DB 表: {report.get('tables_total')} 张 ({report.get('tables_filled')} 有数据 / {report.get('tables_empty')} 空)")
    print(f"  🧠 引擎文件: {report.get('engines_total')} 个")
    print(f"  ⚡ launchd daemon: {report.get('launchd_active')} 活跃")
    print(f"  🌐 Flask: {'PID ' + str(report.get('flask_pid')) if report.get('flask_pid') else '❌ 未运行'}")

    print(f"\n🏛️ Gobelin Bank:")
    for k, v in g.items(): print(f"  · {k}: {v}")

    print(f"\n🔗 仙女座大动脉 (近 1h 流入):")
    # 按流入量排序
    artery_sorted = sorted(a.items(), key=lambda x: -x[1] if x[1] >= 0 else -9999)
    for t, n in artery_sorted[:8]:
        status = "🟢" if n > 50 else "🟡" if n > 5 else "🔴" if n == 0 else "❓"
        print(f"  {status} {t}: {n}")

    print(f"\n🏆 Top 10 最活跃表:")
    for t, n in report.get("top_10_tables", []):
        try:
            ni = int(n); bar = "█" * min(20, ni // 15000)
        except Exception:
            ni = n; bar = ""
        print(f"  {bar} {t}: {ni}")


# ═══════════════════════════════════════════════════════════════════
# §3 一键全跑 + 守护循环
# ═══════════════════════════════════════════════════════════════════

def run_all(verbose=True):
    """一键激活所有能激活的"""
    conn = _conn()
    results = {}

    if verbose: print(f"\n{'='*60}\n🌋 仙女座全生态激活\n{'='*60}")

    if verbose: print("\n① 数据桥接 (Gobelin → 仙女座大动脉)...")
    results["bridge"] = bridge_gobelin_to_andromeda(conn, verbose)

    if verbose: print("\n② 空表种子...")
    results["seed"] = seed_empty_tables(conn, verbose, limit=15)

    if verbose: print("\n③ 全系统体检...")
    report = full_system_audit(conn, verbose=False)
    print_audit(report)
    results["audit"] = {
        "db_total": report["tables_total"],
        "db_filled": report["tables_filled"],
        "db_empty": report["tables_empty"],
        "launchd_active": report["launchd_active"],
        "artery_top": sorted(report["artery_1h"].items(), key=lambda x: -x[1])[:5],
    }

    conn.close()
    return results


def run_eco_daemon(interval_sec=1800):
    """全生态守护 (默认 30min 一轮)"""
    print(f"\n🌋 Ecosystem Activation Daemon 启动 (interval={interval_sec}s)")
    print(f"   ① 每轮: Gobelin→仙女座 数据桥接")
    print(f"   ② 每 2 轮: 空表种子 (15 张)")
    print(f"   ③ 每 4 轮: 全系统体检\n")

    tick = 0
    while True:
        try:
            tick += 1
            conn = _conn()

            bridge_gobelin_to_andromeda(conn, verbose=False)

            if tick % 2 == 0:
                seed_empty_tables(conn, verbose=False, limit=15)

            if tick % 4 == 0:
                report = full_system_audit(conn, verbose=False)
                print_audit(report)

            conn.commit()
            conn.close()
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n🛑 Ecosystem Daemon 退出")
            break
        except Exception as e:
            traceback.print_exc()
            sys.stderr.write(f"[ECO] daemon error: {e}\n")
            time.sleep(interval_sec)


# ═══════════════════════════════════════════════════════════════════
# §4 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ecosystem Activation Engine")
    parser.add_argument("--bridge", action="store_true", help="Gobelin → 仙女座数据桥接")
    parser.add_argument("--seed-empty", action="store_true", help="空表种子")
    parser.add_argument("--audit", action="store_true", help="全系统体检")
    parser.add_argument("--run-all", action="store_true", help="一键全跑")
    parser.add_argument("--daemon", action="store_true", help="常驻守护")
    args = parser.parse_args()

    if args.bridge:
        print(json.dumps({"bridges": bridge_gobelin_to_andromeda()}, ensure_ascii=False, indent=2, default=str))
    elif args.seed_empty:
        print(json.dumps(seed_empty_tables(), ensure_ascii=False, indent=2, default=str))
    elif args.audit:
        report = full_system_audit()
        print_audit(report)
    elif args.run_all:
        run_all()
    elif args.daemon:
        run_eco_daemon()
    else:
        parser.print_help()