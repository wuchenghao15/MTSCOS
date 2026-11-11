#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engines/live_layer_seed.py — 初始化 mock 真实交易层 (LIVE-*)
===========================================================

把 SB-e3105ea094db (沙盘主账户) 的持仓/资金/交易同步到 mt_live_* 表.
Gobelin Bank 仪表盘自动发现 LIVE 层有数据后优先展示.

用法:
  python3 engines/live_layer_seed.py            # dry-run (不写入)
  python3 engines/live_layer_seed.py --apply    # 实际写入
  python3 engines/live_layer_seed.py --apply --primary SB-90d73faf4b9e  # 指定沙盘 session

⚠️ 安全: 默认只 dry-run, 必须显式 --apply 才写库.
"""

import sys, os, json, argparse, sqlite3, datetime

DB_PATH = os.environ.get('APP_DB', os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'))

# 沙盘主账户 (默认)
DEFAULT_PRIMARY = os.environ.get('GOBELIN_PRIMARY_SESSION_ID', 'SB-e3105ea094db')


def seed(account_session, dry_run=True):
    """把沙盘 session 的数据同步到 mt_live_* 表."""
    mode = "DRY-RUN (不写入)" if dry_run else "APPLY (实际写入)"
    print(f"\n{'═'*60}")
    print(f"  LIVE 层初始化 — {mode}")
    print(f"  沙盘来源: {account_session}")
    print(f"  数据库:   {DB_PATH}")
    print(f"{'═'*60}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── 1. 数据源验证 ──
    sb_trades = conn.execute(
        "SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id=?", (account_session,)
    ).fetchone()[0]
    if sb_trades == 0:
        print(f"❌ 沙盘 session {account_session} 没有交易数据")
        return False

    # 最新快照
    snap = conn.execute(
        "SELECT total_value, position_value, cash_value, pnl_amount "
        "FROM mt_sandbox_snapshots WHERE session_id=? ORDER BY snap_date DESC LIMIT 1",
        (account_session,)
    ).fetchone()

    # 持仓 (vault_positions, 已经 refresh_last_prices)
    positions = conn.execute(
        "SELECT symbol, total_cost, market_value, last_price, qty, avg_cost "
        "FROM mt_vault_positions WHERE session_id=?",
        (account_session,)
    ).fetchall()

    # 交易记录 (vault_trades)
    trades = conn.execute(
        "SELECT trade_date, action, symbol, shares, price, gross_amount, commission, stamp_tax "
        "FROM mt_vault_trades WHERE session_id=? ORDER BY trade_date",
        (account_session,)
    ).fetchall()

    # 读取 portfolio 的 initial_cash (修复 pf undefined)
    pf = conn.execute(
        "SELECT initial_cash FROM mt_sandbox_portfolio WHERE session_id=?",
        (account_session,)
    ).fetchone() or {'initial_cash': 10000}

    # live 层当前状态
    live_positions_count = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
    live_trades_count = conn.execute("SELECT COUNT(*) FROM mt_live_trade_log").fetchone()[0]

    print(f"\n📊 沙盘来源数据:")
    print(f"  sandbox_trades:  {sb_trades} 笔")
    print(f"  vault_positions: {len(positions)} 只持仓")
    if snap:
        print(f"  snapshot:        total={snap['total_value']:.2f}  pos={snap['position_value']:.2f}  cash={snap['cash_value']:.2f}  pnl={snap['pnl_amount']:.2f}")
    print(f"\n🗃️  LIVE 层当前状态:")
    print(f"  mt_live_position: {live_positions_count}")
    print(f"  mt_live_trade_log: {live_trades_count}")

    # ── 2. 准备数据 ──
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # live_account — 汇总
    initial_cash = float(pf['initial_cash'] or 10000)
    total_assets = float(snap['total_value']) if snap else 0
    live_account = {
        'total_assets': total_assets,
        'available': float(snap['cash_value']) if snap else 0,
        'market_value': float(snap['position_value']) if snap else 0,
        'cash': float(snap['cash_value']) if snap else 0,
        'pnl': round(total_assets - initial_cash, 2),  # 累计口径
        'initial_cash': initial_cash,
        'server_time': now,
    }

    # live_positions — 持仓明细
    live_positions = []
    for p in positions:
        qty = int(p['qty'])
        cost = float(p['avg_cost'])
        price = float(p['last_price'])
        pnl = (price - cost) * qty
        pnl_pct = (price - cost) / cost * 100 if cost > 0 else 0
        live_positions.append({
            'symbol': p['symbol'],
            'name': '',   # 可以从 mt_sandbox_stock_meta 或腾讯行情补
            'qty': qty,
            'avg_cost': cost,
            'price': price,
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
        })

    # live_trade_log — 交易流水
    live_trades = []
    for t in trades:
        live_trades.append({
            'symbol': t['symbol'],
            'side': t['action'],  # BUY/SELL
            'qty': float(t['shares']),
            'price': float(t['price']),
            'amount': float(t['gross_amount']),
            'fee': float((t['commission'] or 0) + (t['stamp_tax'] or 0)),
            'mode': 'SANDBOX_SYNC',
            'order_id': '',
            'status': 'DONE',
            'reason': f'sync from {account_session}',
            'created_at': t['trade_date'],
        })

    print(f"\n📋 准备写入 mt_live_account:")
    print(f"  total_assets={live_account['total_assets']:.2f}  cash={live_account['cash']:.2f}  mv={live_account['market_value']:.2f}  pnl={live_account['pnl']:+.2f}")
    print(f"\n📋 准备写入 mt_live_position ({len(live_positions)} rows):")
    for p in live_positions:
        print(f"  {p['symbol']:12s} qty={p['qty']} cost={p['avg_cost']:.2f} price={p['price']:.2f} pnl={p['pnl']:+.2f}({p['pnl_pct']:+.1f}%)")
    print(f"\n📋 准备写入 mt_live_trade_log ({len(live_trades)} rows)")

    # ── 3. 执行 ──
    if dry_run:
        print(f"\n🧪 DRY-RUN: 未写入任何数据. 加 --apply 参数执行.")
        conn.close()
        return True

    print(f"\n🗑️  清空 mt_live_* 旧数据...")
    conn.execute("DELETE FROM mt_live_account")
    conn.execute("DELETE FROM mt_live_position")
    conn.execute("DELETE FROM mt_live_trade_log")
    conn.execute("DELETE FROM mt_live_order")

    print(f"💾 写入 mt_live_account...")
    conn.execute("""
        INSERT INTO mt_live_account
        (total_assets, available, market_value, cash, pnl, initial_cash, server_time, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        live_account['total_assets'], live_account['available'],
        live_account['market_value'], live_account['cash'],
        live_account['pnl'], live_account['initial_cash'],
        live_account['server_time'], now,
    ))

    print(f"💾 写入 mt_live_position ({len(live_positions)} rows)...")
    conn.executemany("""
        INSERT INTO mt_live_position (symbol, name, qty, avg_cost, price, pnl, pnl_pct, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, [(p['symbol'], p['name'], p['qty'], p['avg_cost'], p['price'],
           p['pnl'], p['pnl_pct'], now) for p in live_positions])

    print(f"💾 写入 mt_live_trade_log ({len(live_trades)} rows)...")
    conn.executemany("""
        INSERT INTO mt_live_trade_log
        (symbol, side, qty, price, amount, fee, mode, order_id, status, reason, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [(t['symbol'], t['side'], t['qty'], t['price'], t['amount'],
           t['fee'], t['mode'], t['order_id'], t['status'], t['reason'], t['created_at'])
           for t in live_trades])

    conn.commit()

    # 验证
    cnt_pos = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
    cnt_trades = conn.execute("SELECT COUNT(*) FROM mt_live_trade_log").fetchone()[0]
    acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()

    print(f"\n✅ 写入完成!")
    print(f"  mt_live_account:   1 row  assets={acc['total_assets']:.2f}  cash={acc['cash']:.2f}  pnl={acc['pnl']:+.2f}" if acc else "  mt_live_account: 无")
    print(f"  mt_live_position:  {cnt_pos} rows")
    print(f"  mt_live_trade_log: {cnt_trades} rows")

    conn.close()
    return True


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='初始化 mock LIVE 交易层')
    p.add_argument('--apply', action='store_true', help='实际写入 (默认 dry-run)')
    p.add_argument('--primary', default=DEFAULT_PRIMARY, help='沙盘主 session_id')
    args = p.parse_args()

    ok = seed(args.primary, dry_run=not args.apply)
    sys.exit(0 if ok else 1)
