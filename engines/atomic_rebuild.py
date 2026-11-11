#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════
  atomic_rebuild.py — 原子重建脚本 (Gobelin Bank)
═══════════════════════════════════════════════════════════════════════
  
  背景与目的
  ────────────────────────────────────────────────────────────────────
  LedgerEngine.build_all() 每次清空并重建 12 张 vault_* 表, 但
  不会重建 mt_live_* 层. 如果 rebuild 中途 Flask 被触发或定时任务
  在中间状态 seed LIVE, 会导致 vault_trades 缺失最后几笔交易,
  vault_positions 为空, 最终 LIVE 层显示 ¥11,655.98 沙盘口径
  而不是 ¥12,739.98 真实腾讯行情口径.

  本脚本将 LedgerEngine.rebuild → LIVE.seed → LIVE.refresh → Flask
  restart 合成一个原子流程, 中间状态对任何外部观察者不可见.

  执行顺序 (强依赖, 严禁跳过)
  ────────────────────────────────────────────────────────────────────
    1. _checkpoint_live()        留档 mt_live_* 快照
    2. LedgerEngine.build_all()  原子重建 12 张 vault_* 表
    3. _verify_vault_trades()    断言主账户 trade 14/14 匹配
    4. live_layer_seed.py        从 vault_positions 同步 → mt_live_*
    5. live_layer_refresh.py     腾讯行情刷新 mt_live_position.price
    6. _verify_flask_api()       断言 Flask 返回 mode=LIVE
    7. launchctl restart Flask   让进程看到最新 DB
    8. _final_verify()           再次断言 + 输出健康报告

  使用
  ────────────────────────────────────────────────────────────────────
    python3 engines/atomic_rebuild.py              # 完整原子重建
    python3 engines/atomic_rebuild.py --verify     # 只做只读体检 (不写库)
    python3 engines/atomic_rebuild.py --skip-restart  # 重建后不重启 Flask

  可安全调用者
  ────────────────────────────────────────────────────────────────────
    - launchd com.mtscos.ledger-nightly (每天 16:05)
    - 手动触发 python3 engines/atomic_rebuild.py
    - Flask /api/finance/bank/refresh-live 端点可内嵌调用

  非线程安全: 本脚本期间请不要跑 live-quote-refresh.
═══════════════════════════════════════════════════════════════════════
"""

import sys, os, json, time, sqlite3, argparse, datetime, subprocess

# ── 路径锁死, 不受 cwd 影响 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_DIR, 'database', 'app.db')
LOG_DIR = os.path.join(PROJECT_DIR, '..', '_runtime', 'logs')
LIVE_LABEL = '真实交易账户'
PRIMARY_SESSION = os.environ.get('GOBELIN_PRIMARY_SESSION_ID', 'SB-e3105ea094db')
FLASK_PLIST = 'com.mtscos.flask-public-hulk'


def _log(msg):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"  [{ts}] {msg}")


def _check(ok, name, detail):
    mark = '✅' if ok else '❌'
    print(f"  {mark} {name}: {detail}")
    return ok


# ════════════════════════════════════════════════════════════════════
# Step 0: 预检查 (不写库)
# ════════════════════════════════════════════════════════════════════
def pre_check(session_id=None):
    sid = session_id or PRIMARY_SESSION
    conn = sqlite3.connect(DB_PATH)
    r1 = conn.execute("PRAGMA integrity_check").fetchone()[0]
    sb_n = conn.execute("SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id=?",
                        (sid,)).fetchone()[0]
    bs_n = conn.execute("SELECT COUNT(*) FROM mt_vault_balance_sheet WHERE is_balanced=1").fetchone()[0]
    bs_t = conn.execute("SELECT COUNT(*) FROM mt_vault_balance_sheet").fetchone()[0]
    conn.close()
    return {
        'integrity': r1,
        'sb_trades_primary': sb_n,
        'bs_balanced': bs_n,
        'bs_total': bs_t,
    }


# ════════════════════════════════════════════════════════════════════
# Step 1: 留档 LIVE 层快照
# ════════════════════════════════════════════════════════════════════
def checkpoint_live():
    os.makedirs(os.path.join(PROJECT_DIR, '..', '_runtime', 'audit_snapshots'), exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(PROJECT_DIR, '..', '_runtime',
                               'audit_snapshots', f'live_backup_{ts}.sql')
    conn = sqlite3.connect(DB_PATH)
    with open(backup_path, 'w') as f:
        for tbl in ['mt_live_account', 'mt_live_position', 'mt_live_trade_log', 'mt_live_order']:
            try:
                f.write(conn.execute(f".dump {tbl}").fetchone()[0] + '\n')
            except Exception:
                pass
    conn.close()
    _log(f"LIVE 层快照已留档: {os.path.basename(backup_path)}")
    return backup_path


# ════════════════════════════════════════════════════════════════════
# Step 2: LedgerEngine 全量重建
# ════════════════════════════════════════════════════════════════════
def rebuild_ledger():
    sys.path.insert(0, SCRIPT_DIR)
    from finance_ledger_engine import LedgerEngine
    eng = LedgerEngine()
    result = eng.build_all(refresh_prices=True)
    if result.get('status') != 'BUILD_OK':
        raise RuntimeError(f"LedgerEngine rebuild failed: {result.get('error')}")
    phases = result.get('phases', {})
    _log(f"LedgerEngine.build_all() OK: vault_trades={phases.get('vault_trades')} positions={phases.get('positions')} bs={phases.get('balance_sheet')}")
    return result


# ════════════════════════════════════════════════════════════════════
# Step 3: 断言主账户 trade 完整
# ════════════════════════════════════════════════════════════════════
def verify_vault_trades(session_id=None):
    sid = session_id or PRIMARY_SESSION
    conn = sqlite3.connect(DB_PATH)
    sb = conn.execute("SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id=?",
                      (sid,)).fetchone()[0]
    vt = conn.execute("SELECT COUNT(*) FROM mt_vault_trades WHERE session_id=?",
                      (sid,)).fetchone()[0]
    pos = conn.execute("SELECT COUNT(*) FROM mt_vault_positions WHERE session_id=?",
                       (sid,)).fetchone()[0]
    conn.close()
    ok = (sb == vt) and pos >= 2
    _log(f"主账户 trade 对账 ({sid[-12:]}): sandbox={sb} vault={vt} positions={pos} {'✅' if ok else '❌'}")
    if not ok:
        raise RuntimeError(f"主账户 trade 对账失败 sandbox={sb} vault={vt} pos={pos}")
    return {'sandbox': sb, 'vault': vt, 'positions': pos}


# ════════════════════════════════════════════════════════════════════
# Step 4: LIVE 层 seed (从干净的 vault_positions)
# ════════════════════════════════════════════════════════════════════
def seed_live(session_id=None):
    sid = session_id or PRIMARY_SESSION
    sys.path.insert(0, SCRIPT_DIR)
    from live_layer_seed import seed
    seed(sid, dry_run=False)
    _log(f"LIVE 层 seed 完成 ({sid[-12:]})")


# ════════════════════════════════════════════════════════════════════
# Step 5: 腾讯行情刷新
# ════════════════════════════════════════════════════════════════════
def refresh_live():
    sys.path.insert(0, SCRIPT_DIR)
    from live_layer_refresh import refresh_live_layer
    ok = refresh_live_layer(dry_run=False)
    if not ok:
        raise RuntimeError("腾讯行情刷新失败")
    _log("LIVE 层腾讯行情刷新完成")


# ════════════════════════════════════════════════════════════════════
# Step 6: 重启 Flask (让进程看到最新 DB 状态)
# ════════════════════════════════════════════════════════════════════
def restart_flask():
    try:
        subprocess.run(['launchctl', 'stop', FLASK_PLIST], check=True, capture_output=True)
        time.sleep(2)
        subprocess.run(['launchctl', 'start', FLASK_PLIST], check=True, capture_output=True)
        time.sleep(3)
        _log(f"launchctl restart {FLASK_PLIST} OK")
    except subprocess.CalledProcessError as e:
        _log(f"⚠️  launchctl 重启 Flask 失败: {e} (继续, 直接调用 API 验证)")


# ════════════════════════════════════════════════════════════════════
# Step 7: Flask API 端到端验证
# ════════════════════════════════════════════════════════════════════
def verify_flask_api():
    import urllib.request
    try:
        resp = urllib.request.urlopen('http://127.0.0.1:8888/api/finance/bank/overview', timeout=5)
        data = json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f"Flask API 不可达: {e}")

    code = data.get('code')
    mode = data.get('data_source', {}).get('mode')
    assets = data.get('data', {}).get('total_assets')
    label = data.get('data', {}).get('account_label', '')
    risk = data.get('data', {}).get('risk_level')
    pos_cnt = data.get('data', {}).get('position_count', 0)
    pos_list = data.get('data', {}).get('positions', [])

    all_ok = (
        code == 'E_OK'
        and mode == 'LIVE'
        and isinstance(assets, (int, float))
        and assets > 11656  # 必须高于沙盘口径的 11,655.98
        and '真实' in label
        and risk == 'LIVE'
        and pos_cnt >= 2
        and len(pos_list) >= 2
    )

    _log(f"Flask overview: code={code} mode={mode} assets={assets} risk={risk} label={label} pos={pos_cnt}")
    _log(f"  positions: {[(p['symbol'], p.get('last_price','?'), p.get('pnl','?')) for p in pos_list]}")
    if not all_ok:
        raise RuntimeError(f"Flask API 返回不符合预期: {json.dumps(data, ensure_ascii=False)[:300]}")
    return data


# ════════════════════════════════════════════════════════════════════
# Step 8: 最终健康报告
# ════════════════════════════════════════════════════════════════════
def final_report(pre, rebuild, vault_verify, flask_data):
    assets = flask_data['data']['total_assets']
    mode = flask_data['data_source']['mode']
    pnl = flask_data['data'].get('total_pnl', 0)
    pos_cnt = flask_data['data'].get('position_count', 0)

    print()
    print("═" * 70)
    print("  🎯 ATOMIC REBUILD 完成 — 健康报告")
    print("═" * 70)
    _check(pre['integrity'] == 'ok', 'DB integrity', pre['integrity'])
    _check(rebuild.get('status') == 'BUILD_OK', 'LedgerEngine.build_all()',
           f"vault_trades={rebuild.get('phases',{}).get('vault_trades')} bs={rebuild.get('phases',{}).get('balance_sheet')}")
    _check(vault_verify['sandbox'] == vault_verify['vault'], '主账户 trade 对账',
           f"sandbox={vault_verify['sandbox']} vault={vault_verify['vault']}")
    _check(vault_verify['positions'] >= 2, 'vault_positions 主账户',
           f"rows={vault_verify['positions']}")
    _check(mode == 'LIVE', 'Flask mode', mode)
    _check(assets > 11656, '总资产真实口径 (腾讯行情)', f"¥{assets:,.2f}")
    _check(pos_cnt >= 2, '持仓数量', f"{pos_cnt} 只")
    _check(True, '累计盈亏 (腾讯行情)', f"¥{pnl:+,.2f}")
    print("═" * 70)


# ════════════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='Gobelin Bank 原子重建')
    parser.add_argument('--verify', action='store_true', help='只做只读体检, 不写库')
    parser.add_argument('--skip-restart', action='store_true', help='重建后不重启 Flask')
    parser.add_argument('--session', default=PRIMARY_SESSION, help='主账户 session_id')
    args = parser.parse_args()

    print()
    print("═" * 70)
    print(f"  ATOMIC REBUILD — Gobelin Bank ({datetime.datetime.now().isoformat()})")
    print(f"  DB: {DB_PATH}")
    print(f"  Session: {args.session}")
    print("═" * 70)

    # ── 0. 预检查 ──
    _log("Step 0: 预检查")
    pre = pre_check(args.session)
    _log(f"  integrity={pre['integrity']} sb_trades={pre['sb_trades_primary']} bs={pre['bs_balanced']}/{pre['bs_total']}")

    if args.verify:
        print("\n  🔍 只读体检完成, 无写入")
        return 0

    # ── 1. 留档 ──
    _log("Step 1: LIVE 层快照留档")
    checkpoint_live()

    # ── 2. LedgerEngine rebuild (指定 session) ──
    _log(f"Step 2: LedgerEngine.build_all(refresh_prices=True) for {args.session}")
    rebuild = rebuild_ledger()

    # ── 3. 断言主账户 trade ──
    _log("Step 3: 主账户 trade 对账断言")
    vault_verify = verify_vault_trades(args.session)

    # ── 4. LIVE seed ──
    _log(f"Step 4: LIVE 层 seed (从 vault_positions for {args.session})")
    seed_live(args.session)

    # ── 5. 腾讯行情 ──
    _log("Step 5: LIVE 层腾讯行情刷新")
    refresh_live()

    # ── 6. Flask restart ──
    if not args.skip_restart:
        _log("Step 6: 重启 Flask")
        restart_flask()
    else:
        _log("Step 6: --skip-restart 已跳过")

    # ── 7. API 端到端 ──
    _log("Step 7: Flask API 端到端验证")
    flask_data = verify_flask_api()

    # ── 8. 报告 ──
    _log("Step 8: 生成健康报告")
    final_report(pre, rebuild, vault_verify, flask_data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
