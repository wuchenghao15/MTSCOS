#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engines/xqshare_bridge.py — xqshare 券商接入脚手架
==================================================

功能:
  1. health_check: 测试 xqshare 端点连通性
  2. pull_live:    拉取真实持仓/资金 → 写入 mt_live_*
  3. setup_env:    打印需要设置的环境变量清单

用法:
  python3 engines/xqshare_bridge.py check                        # 健康检查
  python3 engines/xqshare_bridge.py pull                         # 拉取真实数据
  python3 engines/xqshare_bridge.py setup                        # 打印环境变量
  XQSHARE_ENDPOINT=http://192.168.1.100:9999 XQSHARE_TOKEN=xxx \
    python3 engines/xqshare_bridge.py pull

前置:
  pip install xqshare
  或 pip install qmt-bridge

⚠️ 此脚本只拉取(只读), 不会执行任何真实下单.
"""
import os, sys, json, sqlite3, datetime, argparse

DB = os.environ.get('APP_DB', os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'))

XQSHARE_ENDPOINT = os.environ.get('XQSHARE_ENDPOINT', 'http://127.0.0.1:9999')
XQSHARE_TOKEN     = os.environ.get('XQSHARE_TOKEN', '')


def check():
    """健康检查 — 尝试连接 xqshare / qmt-bridge."""
    print(f"🔍 券商后端健康检查")
    print(f"  endpoint: {XQSHARE_ENDPOINT}")
    print(f"  token:    {'*** (已设置)' if XQSHARE_TOKEN else '(未设置)'}")
    print()

    # ① xqshare
    try:
        import xqshare
        from xqshare import XtQuantRemote
        host = XQSHARE_ENDPOINT.replace('http://', '').replace('https://', '')
        if ':' in host:
            host, port = host.rsplit(':', 1)
        else:
            port = 9999
        remote = XtQuantRemote(host=host, port=int(port), token=XQSHARE_TOKEN)
        remote.ping()
        print(f"✅ xqshare 连接成功 @ {XQSHARE_ENDPOINT}")
        return ('xqshare', remote)
    except ImportError:
        print(f"⚠️  xqshare 未安装 (pip install xqshare)")
    except Exception as e:
        print(f"❌ xqshare 连接失败: {e}")

    # ② qmt-bridge
    try:
        from qmt_bridge import QMTClient
        client = QMTClient(endpoint=XQSHARE_ENDPOINT, token=XQSHARE_TOKEN)
        status = client.health_check()
        print(f"✅ qmt-bridge 连接成功 @ {XQSHARE_ENDPOINT}: {status}")
        return ('qmt-bridge', client)
    except ImportError:
        print(f"⚠️  qmt-bridge 未安装 (pip install qmt-bridge)")
    except Exception as e:
        print(f"❌ qmt-bridge 连接失败: {e}")

    print(f"\n❌ 无可用后端 — 需要先安装 xqshare 或 qmt-bridge")
    return None, None


def pull_live(backend_name, backend, account=None):
    """从券商拉取真实持仓/资金 → 写入 mt_live_*."""
    print(f"\n📥 从 {backend_name} 拉取真实持仓...")
    if not account:
        print("  ⚠️  需要 account 参数 (券商资金账号), 跳过持仓查询")
        return

    try:
        if backend_name == 'qmt-bridge':
            info = backend.query_asset(account) or {}
            positions = backend.query_positions(account) or []
        elif backend_name == 'xqshare':
            info = {
                'total_asset': float(getattr(backend.xttrader.query_stock_asset(account), 'total_asset', 0)),
                'cash': float(getattr(backend.xttrader.query_stock_asset(account), 'cash', 0)),
                'market_value': float(getattr(backend.xttrader.query_stock_asset(account), 'market_value', 0)),
            }
            positions = [
                {'stock_code': getattr(p, 'stock_code', ''),
                 'volume': int(getattr(p, 'volume', 0)),
                 'avg_cost': float(getattr(p, 'avg_cost', 0)),
                 'market_value': float(getattr(p, 'market_value', 0))}
                for p in (backend.xttrader.query_stock_positions(account) or [])
            ]
        else:
            print(f"  ❌ 未知后端: {backend_name}")
            return

        print(f"  账户资产: total={info.get('total_asset')}  cash={info.get('cash')}  mv={info.get('market_value')}")
        print(f"  持仓数:   {len(positions)}")
        for p in positions[:5]:
            print(f"    {p.get('stock_code','?')} qty={p.get('volume')} cost={p.get('avg_cost')} mv={p.get('market_value')}")

        # 写入 mt_live_*
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect(DB)

        # live_account
        conn.execute("DELETE FROM mt_live_account")
        conn.execute("""
            INSERT INTO mt_live_account
            (total_assets, available, market_value, cash, pnl, server_time, updated_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            float(info.get('total_asset', 0)),
            float(info.get('available', info.get('cash', 0))),
            float(info.get('market_value', 0)),
            float(info.get('cash', 0)),
            0.0,  # pnl 从历史交易算
            now, now,
        ))

        # live_position
        conn.execute("DELETE FROM mt_live_position")
        live_positions = []
        for p in positions:
            qty = int(p.get('volume', p.get('qty', 0)))
            if qty <= 0:
                continue
            code = p.get('stock_code', p.get('symbol', ''))
            cost = float(p.get('avg_cost', p.get('cost', 0)))
            mv = float(p.get('market_value', 0))
            price = mv / qty if qty > 0 else 0
            pnl = mv - cost * qty
            pnl_pct = pnl / (cost * qty) * 100 if cost > 0 else 0
            live_positions.append((code, '', qty, cost, price, round(pnl, 2), round(pnl_pct, 2), now))

        conn.executemany("""
            INSERT INTO mt_live_position
            (symbol, name, qty, avg_cost, price, pnl, pnl_pct, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, live_positions)
        conn.commit()

        acc = conn.execute("SELECT * FROM mt_live_account ORDER BY id DESC LIMIT 1").fetchone()
        pos_cnt = conn.execute("SELECT COUNT(*) FROM mt_live_position").fetchone()[0]
        conn.close()

        print(f"\n✅ 写入 mt_live_* 完成:")
        print(f"  mt_live_account:   assets={acc['total_assets']:.2f}  cash={acc['cash']:.2f}" if acc else "  mt_live_account: 无")
        print(f"  mt_live_position:  {pos_cnt} rows")
        print(f"\n🎉 stock.mtos.site 将自动展示真实数据 (LIVE 层)")

    except Exception as e:
        print(f"  ❌ 拉取失败: {e}")
        import traceback; traceback.print_exc()


def setup_env():
    """打印需要设置的环境变量."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║  📋 xqshare 接入环境变量准备                              ║
╚═══════════════════════════════════════════════════════════╝

# 1. 安装依赖 (Mac mini 上)
pip3 install xqshare          # xqshare 客户端
# 或
pip3 install qmt-bridge        # qmt-bridge HTTP 客户端

# 2. 设置环境变量 (写入 ~/.zshrc 或 /etc/profile)
export XQSHARE_ENDPOINT="http://192.168.x.x:9999"   # qmt-bridge / xqshare 服务端地址
export XQSHARE_TOKEN="your_token_here"                # 服务端 token

# 3. 健康检查
cd ~/MTSCOS_AI_Project/flask-app
python3 engines/xqshare_bridge.py check

# 4. 拉取真实数据 (需要券商资金账号)
python3 engines/xqshare_bridge.py pull --account "YOUR_ACCOUNT_ID"

# 5. Flask 会自动检测 LIVE 层有数据, 切换数据源
#    stock.mtos.site → 自动展示真实账户数据!
""")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='xqshare / qmt-bridge 接入脚手架')
    p.add_argument('action', nargs='?', default='check', choices=['check', 'pull', 'setup'])
    p.add_argument('--account', '-a', help='券商资金账号 (pull 需要)')
    args = p.parse_args()

    if args.action == 'setup':
        setup_env()
    elif args.action == 'check':
        backend_name, backend = check()
        if backend_name:
            print(f"\n💡 连接成功后可运行: python3 engines/xqshare_bridge.py pull --account YOUR_ACCOUNT")
    elif args.action == 'pull':
        backend_name, backend = check()
        if backend_name:
            pull_live(backend_name, backend, account=args.account)
        else:
            print("❌ 跳过拉取 — 后端连接失败, 先运行 check 或 setup")
