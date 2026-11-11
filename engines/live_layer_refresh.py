#!/usr/bin/env python3
"""LIVE 层真实行情自动刷新 — 腾讯行情 API → mt_live_*"""
import urllib.request, sqlite3, os, datetime

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

# 腾讯行情 v_ 前缀 → sh600036/1 600036
_QT_KEY_PREFIX = 'v_'


def _qt_to_symbol(qt_code):
    """腾讯行情内部代码 → 我们的 symbol.
    sh600036 在腾讯数据里是 [2]=600036 (纯数字) + KEY=v_sh600036
    所以从 KEY 拿前缀: v_sh600036 → sh600036"""
    return qt_code  # KEY 里已经是 sh600036


def fetch_quotes(codes):
    """拉腾讯行情, 返回 {symbol: {name, price, change_pct, open, high, low, preclose}}"""
    url = 'https://qt.gtimg.cn/q=' + ','.join(codes)
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=8).read().decode('gbk', errors='replace')
    result = {}
    for line in resp.strip().split(';'):
        line = line.strip()
        if not line or '="' not in line: continue
        key, _, val = line.partition('="')
        val = val.rstrip('"')
        fp = val.split('~')
        if len(fp) < 35: continue
        # KEY: v_sh600036 → symbol: sh600036
        symbol = key.replace(_QT_KEY_PREFIX, '')
        result[symbol] = {
            'name': fp[1],
            'code': fp[2],
            'price': float(fp[3] or 0),
            'preclose': float(fp[4] or 0),
            'open': float(fp[5] or 0),
            'change': float(fp[31] or 0),
            'change_pct': float(fp[32] or 0),
            'high': float(fp[33] or 0),
            'low': float(fp[34] or 0),
            'timestamp': fp[30],
        }
    return result


def refresh_live_layer(dry_run=False):
    """刷新 mt_live_position + mt_live_account 实时价."""
    mode = "DRY-RUN" if dry_run else "APPLY"
    print("=" * 60)
    print(f"  📈 LIVE 层真实行情刷新 — {mode}")
    print("=" * 60)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1. 读 LIVE 持仓
    positions = conn.execute("SELECT * FROM mt_live_position ORDER BY id DESC").fetchall()
    if not positions:
        print("  ⚠️  mt_live_position 为空 — 先运行 live_layer_seed.py --apply")
        conn.close()
        return False

    codes = [p['symbol'] for p in positions]
    print(f"  持仓: {len(codes)} 只  {codes}")

    # 2. 拉行情
    quotes = fetch_quotes(codes)
    print(f"  行情: 拉到 {len(quotes)}/{len(codes)}")
    for code, q in quotes.items():
        print(f"    ✅ {code:12s} {q['name']:8s} price={q['price']:.2f} "
              f"change={q['change']:+.2f} ({q['change_pct']:+.2f}%)  [昨收={q['preclose']:.2f} 最高={q['high']:.2f} 最低={q['low']:.2f}]")

    # 3. 计算更新
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows_update = []
    total_mv = 0.0
    total_cost = 0.0
    total_pnl = 0.0

    for p in positions:
        code = p['symbol']
        qty = float(p['qty'])
        cost = float(p['avg_cost'])
        if code in quotes and quotes[code]['price'] > 0:
            price = quotes[code]['price']
            name = quotes[code]['name']
            preclose = quotes[code]['preclose']
        else:
            price = float(p['price'] or 0)
            name = p['name'] or ''
            preclose = float(p.get('prev_close') or 0)
        mv = round(price * qty, 2)
        pnl = round((price - cost) * qty, 2)
        pnl_pct = round((price - cost) / cost * 100, 2) if cost > 0 else 0
        # today_pnl = 今日涨跌 × 持仓 (不是累计 pnl!)
        today_pnl = round((price - preclose) * qty, 2) if preclose > 0 else 0
        total_mv += mv
        total_cost += cost * qty
        total_pnl += pnl
        rows_update.append((name, price, pnl, pnl_pct, preclose, today_pnl, now, code))

    print(f"\n  📊 预期更新:")
    print(f"    total_mv = {total_mv:.2f}")
    print(f"    total_cost = {total_cost:.2f}")
    print(f"    total_pnl = {total_pnl:+.2f}")

    if dry_run:
        print(f"\n  🧪 DRY-RUN: 未写入")
        conn.close()
        return True

    # 4. 写库
    conn.executemany("""
        UPDATE mt_live_position
        SET name=?, price=?, pnl=?, pnl_pct=?, prev_close=?, today_pnl=?, updated_at=?
        WHERE symbol=?
    """, rows_update)

    # 5. 更新 mt_live_account
    acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
    if acc:
        cash = float(acc['cash'] or acc['available'] or 0)
        initial = float(acc['initial_cash'] or 0)
        total_assets = round(cash + total_mv, 2)
        # pnl = total_assets - initial_cash (累计口径, 正确)
        # 不是 (price - cost)*qty 的未实现口径
        pnl_cumulative = round(total_assets - initial, 2) if initial > 0 else round(total_pnl, 2)
        conn.execute("""
            UPDATE mt_live_account
            SET total_assets=?, market_value=?, pnl=?, server_time=?, updated_at=?
            WHERE id=?
        """, (total_assets, round(total_mv, 2), pnl_cumulative, now, now, acc['id']))

    conn.commit()
    conn.close()

    print(f"\n  ✅ 刷新完成 @ {now}")
    if acc:
        print(f"  💼 mt_live_account: assets={total_assets:.2f}  cash={cash:.2f}  mv={total_mv:.2f}  pnl={pnl_cumulative:+.2f}  initial={initial:.2f}")
    return True


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    refresh_live_layer(dry_run=args.dry_run)
