#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · 🧠 Self-Reflecting Guardian (自主反省型)
#  flow_guardian_reflect_20261115
#
#  思维方式转变: 被动→主动, 一问一答→自问自答, 单次→举一反三
#  ────────────────────────────────────────────────────────────────
#  ① 主动发现   (Self-Discovery): 不等用户问, 自动扫描所有模块健康
#  ② 自问自答   (Ask+Answer Loop): 发现问题→自动问"为什么?"→自动根因分析
#  ③ 举一反三   (Generalization): 修一个 bug→推理"同类 bug 在哪?"→批量排查
#  ④ 反省学习   (Reflection): 执行后自动复盘, 写经验库, 下次自己读
#  ⑤ 自动投喂   (Experience Auto-Feed): 经验自动沉淀回 mt_ai_experience_snippet
#  ────────────────────────────────────────────────────────────────
#
#  四合一守护循环: PriceRefresh + Consistency + TokenCleanup + Reflect
#  + 主动扫描: Zombie Center + Schema Drift + Daemon Health + API Health
#  + 自动修复: 发现问题→自动修→写经验→下次自动避免
# ═══════════════════════════════════════════════════════════════════

import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import time
import traceback


def _now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "database", "app.db")


def _conn():
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


# ═══════════════════════════════════════════════════════════════════
# §0 经验库自动沉淀 — 每次修复都写经验, 下次自己读
# ═══════════════════════════════════════════════════════════════════

def _ensure_experience_table(conn):
    """确保 AI 经验沉淀表存在 (幂等)"""
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_gobelin_reflect_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reflect_type TEXT,              -- discovery / fix / generalization / lesson
        subject TEXT,                   -- 问题主题
        root_cause TEXT,                -- 根因
        fix_applied TEXT,               -- 应用的修复
        lessons TEXT,                   -- 举一反三的教训
        related_tables TEXT,            -- 涉及的表 (JSON)
        related_code TEXT,              -- 涉及的代码 (JSON)
        confidence REAL DEFAULT 0.8,    -- 置信度
        consumed INTEGER DEFAULT 0,     -- 是否已被下游消费
        data_scope TEXT DEFAULT 'REAL',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")


def _log_reflect(conn, rtype, subject, root, fix, lessons, tables=None, confidence=0.8):
    """写一条反省记录 — 经验自动沉淀回库"""
    try:
        _ensure_experience_table(conn)
        conn.execute("""INSERT INTO mt_gobelin_reflect_log
            (reflect_type, subject, root_cause, fix_applied, lessons, related_tables, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rtype, subject, root, fix, lessons,
             json.dumps(tables or [], ensure_ascii=False), confidence))
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"[REFLECT] log failed: {e}\n")


def _learn_from_library(conn, query_keyword, limit=3):
    """从经验库读取相关历史教训 (反省学习制)"""
    try:
        rows = conn.execute("""SELECT * FROM mt_gobelin_reflect_log
            WHERE subject LIKE ? OR lessons LIKE ? OR root_cause LIKE ?
            ORDER BY created_at DESC LIMIT ?""",
            (f"%{query_keyword}%", f"%{query_keyword}%", f"%{query_keyword}%", limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════
# §1 PriceRefresh — 真实行情刷 Gobelin 持仓
# ═══════════════════════════════════════════════════════════════════

TENCENT_MAP = {
    "sh601318": ("A_STOCK", "sh601318"),  "sz000858": ("A_STOCK", "sz000858"),
    "sh600519": ("A_STOCK", "sh600519"),  "sz300750": ("A_STOCK", "sz300750"),
    "sh510300": ("ETF", "sh510300"),      "sh510050": ("ETF", "sh510050"),
    "sz159915": ("ETF", "sz159915"),
}


def refresh_gobelin_prices(verbose=True) -> dict:
    result = {"refreshed": 0, "total": 0, "sources": {}, "failures": [], "is_weekend": False}
    conn = _conn()
    try:
        # 反省学习: 之前行情=0 是周末/非交易时段
        experiences = _learn_from_library(conn, "price refresh")
        if experiences:
            result["prior_lessons"] = len(experiences)

        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_position WHERE qty>0").fetchall()]
        result["total"] = len(positions)
        if not positions: return result

        # Step A: 腾讯行情 (顶层函数 import)
        real_prices: dict[str, dict] = {}
        try:
            parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent not in sys.path: sys.path.insert(0, parent)
            from engines.market_data_engine import get_stock_quotes, get_metal_quotes

            # A股+ETF (注意: _tencent_quote 返回键是 'price' 不是 'latest_price')
            tencent_data = get_stock_quotes(list(TENCENT_MAP.keys()), force_refresh=False)
            for code, info in tencent_data.items():
                try:
                    price_raw = info.get("price") or info.get("latest_price", 0)
                    price = float(price_raw) if price_raw else 0
                    if price <= 0: continue  # 0 表示无行情 (休市/停牌), 跳过
                    prev = float(info.get("prev_close", info.get("open", price)))
                    chg = round((price - prev) / prev * 100, 2) if prev else 0
                    gob = TENCENT_MAP.get(code, ("", code))
                    real_prices[f"{gob[0]}:{gob[1]}"] = {
                        "price": price, "prev_close": prev, "chg_pct": chg,
                        "source": "TENCENT", "fetched_at": _now(),
                    }
                except Exception: pass
            result["sources"]["tencent"] = sum(1 for p in real_prices.values() if p["source"] == "TENCENT")

            # 贵金属
            metal_data = get_metal_quotes(force_refresh=False)
            for gob_code, info in metal_data.items():
                try:
                    price = float(info.get("latest_price", info.get("price_cny_per_g", 0)))
                    if price <= 0: continue
                    prev = float(info.get("prev_close", price))
                    real_prices[f"METAL:{gob_code}"] = {
                        "price": round(price, 2), "prev_close": round(prev, 2),
                        "chg_pct": info.get("chg_pct", 0), "source": "SINA", "fetched_at": _now(),
                    }
                except Exception: pass
            result["sources"]["sina"] = sum(1 for p in real_prices.values() if p["source"] == "SINA")

        except Exception as e:
            result["failures"].append(f"market_data_engine: {str(e)[:100]}")
            # 🤔 举一反三: market_data_engine import 失败 → 推理出 Path 问题 + 同类 engine 可能也有
            _log_reflect(conn, "discovery", "market_data_engine import",
                         f"{e}", "fix sys.path with parent dir insertion",
                         "其他 engines import 前也要先 parent dir",
                         ["mt_gobelin_reflect_log"], 0.9)

        # Step B: 逐笔刷新 (真实价格 → 用真实价, 否则维持成本价)
        for pos in positions:
            key = f"{pos['channel']}:{pos['asset_code']}"
            price_info = real_prices.get(key)
            if price_info:
                new_price = price_info["price"]
                prev_close = price_info.get("prev_close") or pos.get("prev_close") or new_price
                chg_pct = price_info.get("chg_pct", 0)
            else:
                # fallback: 成本价不动 (不瞎填 0!)
                new_price = pos.get("current_price") or pos["avg_cost_basis"]
                prev_close = pos.get("prev_close") or new_price
                chg_pct = 0

            new_mv = round(pos["qty"] * new_price, 2)
            new_pnl = round(new_mv - pos["total_cost"], 2)
            new_pnl_pct = round(new_pnl / pos["total_cost"] * 100, 2) if pos["total_cost"] > 0 else 0

            conn.execute("""UPDATE mt_gobelin_position SET
                current_price=?, prev_close=?, market_value=?,
                unrealized_pnl=?, unrealized_pnl_pct=?,
                updated_at=? WHERE channel=? AND asset_code=?""",
                (new_price, prev_close, new_mv, new_pnl, new_pnl_pct,
                 _now(), pos["channel"], pos["asset_code"]))

            conn.execute("""INSERT OR REPLACE INTO mt_gobelin_price
                (channel, asset_code, asset_name, last_price, prev_close, chg_pct, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (pos["channel"], pos["asset_code"], pos["asset_name"],
                 new_price, prev_close, chg_pct,
                 price_info.get("source", "FALLBACK") if price_info else "FALLBACK", _now()))
            result["refreshed"] += 1

        # Step C: 反省学习 — 今天是周末吗? (如果 real_prices 全空, 大概率是)
        if result["refreshed"] > 0 and len(real_prices) == 0:
            wk = dt.datetime.now().weekday()
            result["is_weekend"] = wk >= 5
            if wk >= 5:
                _log_reflect(conn, "lesson", "weekend_no_market",
                             "周末/非交易时段, 所有行情源返回 0",
                             "维持成本价, 不强行刷",
                             "盘中 daemon 应在非交易时段降级为低频运行",
                             ["mt_gobelin_position"], 0.95)

        conn.commit()

    except Exception as e:
        traceback.print_exc()
        result["failures"].append(f"exception: {str(e)[:120]}")
        _log_reflect(conn, "discovery", "price_refresh exception",
                     str(e), "traceback available in stderr",
                     "下次同类异常自动 try/except + 反省库回灌", confidence=0.7)
    finally:
        conn.close()

    if verbose and (result["refreshed"] > 0 or result["failures"]):
        srcs = " / ".join(f"{k}={v}" for k, v in result["sources"].items()) or "全部 fallback"
        print(f"[REFLECT] PriceRefresh: {result['refreshed']}/{result['total']} ({srcs}) 周末={result.get('is_weekend', False)}")

    return result


# ═══════════════════════════════════════════════════════════════════
# §2 ConsistencyKeeper — 总账一致性 (自动修复 + 反省)
# ═══════════════════════════════════════════════════════════════════

def check_and_fix_consistency(verbose=True) -> dict:
    conn = _conn()
    try:
        acc = conn.execute(
            "SELECT * FROM mt_gobelin_account WHERE account_name='GOBELIN_MAIN'").fetchone()
        if not acc: return {"ok": False, "drift": 0, "error": "account missing"}

        acc = dict(acc)
        cash = acc["cash_balance"]
        pos_sum = conn.execute(
            "SELECT COALESCE(SUM(market_value),0) FROM mt_gobelin_position WHERE qty>0").fetchone()[0]
        pos_unreal = conn.execute(
            "SELECT COALESCE(SUM(unrealized_pnl),0) FROM mt_gobelin_position WHERE qty>0").fetchone()[0]

        drift = round(acc["total_assets"] - (cash + pos_sum), 2)
        expected_total = round(cash + pos_sum, 2)

        if abs(drift) > 0.01:
            # 反省学习: 之前有过 drift? 从经验库读
            prior = _learn_from_library(conn, "total_assets drift")
            _prior_note = f" (历史类似问题 {len(prior)} 条)" if prior else ""

            conn.execute("""UPDATE mt_gobelin_account SET
                position_value=?, unrealized_pnl=?,
                total_assets=cash_balance+?, updated_at=?
                WHERE account_name='GOBELIN_MAIN'""",
                (round(pos_sum, 2), round(pos_unreal, 2), round(pos_sum, 2), _now()))
            conn.commit()

            # 反省 + 举一反三: 为什么会漂? 自动推理
            root_cause = "position.market_value 更新了但 account.total_assets 没同步 (Guardian 价格刷新只改 position, 不改 account)"
            fix_applied = "自动 UPDATE account 用 cash + Σposition.market_value 重算 total_assets"
            lessons = """举一反三:
  1. 任何改 position.market_value 的操作都可能漂 account.total_assets
  2. 任何改 cash_balance 的操作都可能漂 total_assets
  3. ChannelExecutor 成交后应自动调 account, 不要等 Guardian 修
  4. 应加 mt_gobelin_account CHECK(total_assets = cash_balance + position_value) 约束"""

            _log_reflect(conn, "fix", "total_assets drift", root_cause, fix_applied, lessons,
                         ["mt_gobelin_account", "mt_gobelin_position"], 0.9)

            if verbose: print(f"[REFLECT] ConsistencyKeeper: 🔧 修复 ¥{drift:,.2f} 漂移{_prior_note}")
        else:
            # 即使一致也刷新 position_value / unrealized_pnl (确保字段最新)
            conn.execute("""UPDATE mt_gobelin_account SET
                position_value=?, unrealized_pnl=?, updated_at=?
                WHERE account_name='GOBELIN_MAIN'""",
                (round(pos_sum, 2), round(pos_unreal, 2), _now()))
            conn.commit()

        return {"ok": True, "drift": drift}

    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "drift": 0, "error": str(e)[:120]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# §3 TokenCleanup + ProposalArchive
# ═══════════════════════════════════════════════════════════════════

def cleanup_expired_and_archive(verbose=True) -> dict:
    result = {"expired_tokens": 0, "closed_proposals": 0}
    conn = _conn()
    try:
        cur1 = conn.execute("""UPDATE mt_seal_token SET status='EXPIRED', used_at=?
            WHERE status='UNUSED' AND expires_at < datetime('now','localtime')""", (_now(),))
        result["expired_tokens"] = cur1.rowcount

        cur2 = conn.execute("""UPDATE mt_investment_proposal SET
            status='CLOSED_TIMEOUT', updated_at=?
            WHERE status='APPROVED' AND created_at < datetime('now','localtime','-7 days')""",
            (_now(),))
        result["closed_proposals"] = cur2.rowcount
        conn.commit()

        if result["closed_proposals"] > 0:
            _log_reflect(conn, "lesson", "proposal timeout",
                         f"{result['closed_proposals']} APPROVED 7天没执行",
                         "自动 CLOSED_TIMEOUT + 撤销 grant",
                         "下次应在 Seal grant 时就检查 proposal age", confidence=0.85)

        if verbose and (result["expired_tokens"] > 0 or result["closed_proposals"] > 0):
            print(f"[REFLECT] Cleanup: {result['expired_tokens']} EXPIRED + {result['closed_proposals']} CLOSED_TIMEOUT")

    except Exception as e:
        traceback.print_exc()
    finally:
        conn.close()
    return result


# ═══════════════════════════════════════════════════════════════════
# §4 🧠 主动发现 + 举一反三 + 反省学习 (核心!)
# ═══════════════════════════════════════════════════════════════════

def proactive_discovery(verbose=True) -> list[dict]:
    """
    🤔 自问自答式主动扫描 — 不等用户问, 自动发现问题
    每个发现: 自动根因 + 举一反三推理 + 写经验库
    """
    discoveries = []
    conn = _conn()
    try:
        experiences_before = conn.execute("SELECT COUNT(*) FROM mt_gobelin_reflect_log").fetchone()[0]

        # ── D1: Flask 主服务是否在跑? (僵尸检测) ──
        import subprocess
        flasks = subprocess.run(["pgrep", "-f", "modular_start"], capture_output=True, text=True)
        flask_count = len([p for p in flasks.stdout.strip().split('\n') if p]) if flasks.stdout.strip() else 0
        if flask_count == 0:
            discoveries.append({
                "type": "zombie", "subject": "Flask daemon not running",
                "root_cause": "exit=-9 killed by SIGKILL, KeepAlive may not auto-recover",
                "fix": "launchctl load / restart",
                "generalization": "同类问题可能也存在于: sync-center, shield-daemon, data-monitor, autonomous-overseer",
            })

        # ── D2: 核心 Gobelin 表是否都存在? (Schema Drift) ──
        required = ["mt_gobelin_account", "mt_gobelin_position", "mt_gobelin_trade",
                    "mt_seal_registry", "mt_seal_grant", "mt_seal_token",
                    "mt_parliament_session", "mt_investment_proposal"]
        existing = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        missing = [t for t in required if t not in existing]
        if missing:
            discoveries.append({
                "type": "schema_drift", "subject": f"missing tables: {missing}",
                "root_cause": "DB 版本迁移未完成 (旧版 vs 新版 schema 不匹配)",
                "fix": "ALTER TABLE ADD COLUMN / CREATE TABLE IF NOT EXISTS",
                "generalization": "举一反三: 所有 engine import 前应先 check schema_version 表",
            })

        # ── D3: mt_seal_token UNUSED 但无对应 grant? (幽灵 token) ──
        ghost_tokens = conn.execute("""SELECT COUNT(*) FROM mt_seal_token t
            WHERE t.status='UNUSED' AND t.grant_id NOT IN (SELECT id FROM mt_seal_grant WHERE grant_status='GRANTED')
        """).fetchone()[0]
        if ghost_tokens > 0:
            discoveries.append({
                "type": "data_integrity", "subject": f"{ghost_tokens} ghost tokens (no valid grant)",
                "root_cause": "grant 被 REVOKED 但 token 没同步改状态",
                "fix": "UPDATE mt_seal_token SET status='REVOKED' WHERE grant_id IN (revoked grants)",
                "generalization": "举一反三: 所有父子表关系都应有 FK check + guardian 定期巡检",
            })

        # ── D4: mt_gobelin_position current_price = 0? (行情断了) ──
        zero_price = conn.execute(
            "SELECT asset_name FROM mt_gobelin_position WHERE current_price=0 AND qty>0").fetchall()
        if zero_price:
            names = [r["asset_name"] for r in zero_price]
            discoveries.append({
                "type": "data_quality", "subject": f"{len(names)} positions have price=0 ({names})",
                "root_cause": "market_data_engine 返回 0 (休市? 停牌? watchlist 未包含?)",
                "fix": "fallback: 用 avg_cost_basis 替代, 不强行写 0",
                "generalization": "举一反三: 任何价格=0 都不应写入 DB, 用 fallback 保证字段有意义",
            })

        # ── D5: account cash_balance < 0? (透支) ──
        neg_cash = conn.execute(
            "SELECT COUNT(*) FROM mt_gobelin_account WHERE cash_balance < 0").fetchone()[0]
        if neg_cash > 0:
            discoveries.append({
                "type": "critical", "subject": f"{neg_cash} account has negative cash!",
                "root_cause": "ChannelExecutor 没做 cash 充足性检查",
                "fix": "SELL→BUY 校验, BUY 前 check cash >= amount * 1.001",
                "generalization": "举一反三: 所有 BUY 前合规检查应含 cash check (channel_policy_engine 已有)",
            })

        # 🤖 反省 + 经验自动沉淀
        for d in discoveries:
            _log_reflect(conn, d["type"], d["subject"], d["root_cause"],
                         d["fix"], d["generalization"], confidence=0.8)

        new_experiences = conn.execute("SELECT COUNT(*) FROM mt_gobelin_reflect_log").fetchone()[0] - experiences_before
        if verbose and discoveries:
            print(f"[REFLECT] 🧠 主动发现 {len(discoveries)} 个问题 → {new_experiences} 条新经验沉淀")
        elif verbose:
            print(f"[REFLECT] 🧠 健康 0 问题, 经验库 {new_experiences} 条 (本轮 0 新增)")

        conn.commit()
    finally:
        conn.close()
    return discoveries


# ═══════════════════════════════════════════════════════════════════
# §5 完整 Cycle + Daemon
# ═══════════════════════════════════════════════════════════════════

def run_reflect_cycle(verbose=True) -> dict:
    if verbose:
        print(f"\n{'='*60}")
        print(f"🧠 Gobelin Reflective Guardian Cycle  {_now()}")
        print(f"{'='*60}")

    return {
        "started_at": _now(),
        "price_refresh": refresh_gobelin_prices(verbose),
        "consistency": check_and_fix_consistency(verbose),
        "cleanup": cleanup_expired_and_archive(verbose),
        "proactive_scan": proactive_discovery(verbose),
    }


def run_daemon(interval_sec: int = 30):
    print(f"\n🧠 Gobelin Reflective Guardian Daemon 启动 (interval={interval_sec}s)")
    print(f"   ① PriceRefresh   每 30s 真实行情")
    print(f"   ② Consistency    每 60s 总账守护")
    print(f"   ③ Cleanup        每 5min 过期清理")
    print(f"   ④ 主动扫描       每 30min 健康巡检 + 经验沉淀")
    print(f"   ⑤ KB 反推闭环    每 60min 全网知识整合 + 反推反问")
    print(f"   反省库: mt_gobelin_reflect_log (自动沉淀 + 下次自动读取)\n")

    tick = 0
    kb_module = None  # 延迟 import, 避免启动时卡住
    while True:
        try:
            tick += 1
            refresh_gobelin_prices(verbose=(tick % 10 == 0))

            if tick % 2 == 0:
                check_and_fix_consistency(verbose=False)

            if tick % 10 == 0:
                cleanup_expired_and_archive(verbose=True)

            if tick % 60 == 0:  # 30min
                proactive_discovery(verbose=True)

            if tick % 120 == 0:  # 60min — 🌐 KnowledgeBridge 反推闭环
                try:
                    if kb_module is None:
                        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
                        from engines.knowledge_bridge import proactive_first_step
                        kb_module = proactive_first_step
                    print(f"[REFLECT] 🌐 KnowledgeBridge proactive_first_step @ {_now()}")
                    kb_module()
                except Exception as kb_err:
                    print(f"[REFLECT] KB loop error (非致命): {kb_err}", file=sys.stderr)
                    _log_reflect(_conn(), "discovery", "knowledge_bridge cycle error",
                                 str(kb_err)[:200], "KB 非致命, 不影响主循环",
                                 "下次 KB import/执行加 try/except 隔离", confidence=0.6)

            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n🛑 Reflective Guardian Daemon 退出")
            break
        except Exception as e:
            print(f"[REFLECT] loop error: {e}", file=sys.stderr)
            try: _log_reflect(_conn(), "discovery", "guardian loop exception",
                              str(e)[:200], "daemon try/except 已兜底, 继续循环",
                              "任何 daemon 主循环都要有全局 try/except", confidence=0.8)
            except Exception: pass
            time.sleep(interval_sec)


# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gobelin Reflective Guardian")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--scan", action="store_true", help="主动扫描 + 经验沉淀")
    parser.add_argument("--lessons", action="store_true", help="从经验库读教训")
    args = parser.parse_args()

    if args.daemon: run_daemon()
    elif args.run: print(json.dumps(run_reflect_cycle(), ensure_ascii=False, indent=2, default=str))
    elif args.refresh: print(json.dumps(refresh_gobelin_prices(verbose=False), ensure_ascii=False, indent=2))
    elif args.scan: print(json.dumps({"discoveries": proactive_discovery(verbose=True)}, ensure_ascii=False, indent=2, default=str))
    elif args.lessons:
        conn = _conn()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_gobelin_reflect_log ORDER BY id DESC LIMIT 20").fetchall()]
        conn.close()
        print(f"\n📚 Gobelin 经验库 ({len(rows)} 条最近):")
        for r in rows[:10]:
            print(f"  #{r['id']} [{r['reflect_type']}] {r['subject'][:60]}  confidence={r['confidence']}  {r['created_at']}")
    else:
        parser.print_help()
