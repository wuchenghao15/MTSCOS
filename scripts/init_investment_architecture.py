#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  🏦 Gobelin Bank · 投资架构初始化脚本                                  ║
║                                                                        ║
║  Phase 1: 注入 7 渠道 LIVE 持仓 (¥500,000 组合)                        ║
║  Phase 2: 跑 VaultLedgerEngine 生成金库全套                            ║
║  Phase 3: PortfolioAllocator 目标比例配置                               ║
║  Phase 4: Dashboard 展示端对齐验证                                     ║
║                                                                        ║
║  运行: python3 scripts/init_investment_architecture.py                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, sys, random, time, json
from datetime import datetime, timedelta

# 确保项目根在 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.safe_sqlite import safe_conn, safe_exec, safe_execmany, safe_query, safe_query_one

DB = os.path.join(_ROOT, 'database', 'app.db')

# ──────────────────────────────────────────────────────────────────────
# 配置: 7 渠道 × 真实标的 × 合理初始价格
# ──────────────────────────────────────────────────────────────────────

TOTAL_PORTFOLIO = 500_000.0  # 总投资规模 ¥500,000
CASH_RESERVE = 100_000.0     # 活钱储备 ¥100,000

# 价格基准 (2025-2026 真实价近似, 后续随市场波动)
SEED_SYMBOLS = {
    # ── A 股持仓 (mt_live_position) ──
    'STOCK': [
        # (symbol, name, qty, avg_cost, price, prev_close)
        ('sh601318', '中国平安',   300, 50.50, 52.73, 51.80),
        ('sz000858', '五粮液',     100, 72.00, 74.70, 73.50),
        ('sh600036', '招商银行',   400, 42.00, 43.72, 43.10),
        ('sz002594', '比亚迪',     150, 78.00, 80.62, 79.30),
        ('sh600519', '贵州茅台',    10, 1650.00, 1688.00, 1670.00),
        ('sh601899', '紫金矿业',   500, 15.80, 16.25, 15.90),
        ('sz300750', '宁德时代',    80, 195.00, 201.50, 198.00),
    ],
    # ── 基金持仓 (mt_live_fund_position) ──
    'FUND': [
        # (fund_code, fund_name, price, qty)
        ('510300', '华泰柏瑞沪深300ETF',    4.150, 9638),
        ('511010', '国泰上证5年期国债ETF',   112.35, 177),
        ('518880', '华安黄金ETF',            5.680, 10563),
        ('159915', '易方达创业板ETF',        2.120, 8962),
    ],
    # ── 银行理财 (mt_live_bank_product) ──
    'BANK_PRODUCT': [
        # (product_code, product_name, bank, amount, expected_return)
        ('CMB-T1-001', '招银朝朝宝',        '招商银行', 30000, 2.10),
        ('ICBC-T1-005', '工行利添利',        '工商银行', 20000, 1.95),
        ('ABC-T5-002', '农行金钥匙·安心得利', '农业银行', 10000, 2.85),
    ],
    # ── 定期存款 (mt_live_term_deposit) ──
    'DEPOSIT': [
        # (deposit_code, bank, amount, rate, term_months)
        ('D-ICBC-12M-2601', '工商银行', 20000, 1.95, 12),
        ('D-CCB-12M-2603',  '建设银行', 15000, 2.10, 12),
        ('D-BOC-24M-2605',  '中国银行',  5000, 2.65, 24),
    ],
    # ── 贵金属 (mt_live_metal_position) ──
    'METAL': [
        # (metal_name, metal_type, price, qty, unit)
        ('黄金',   'GOLD',   585.00, 25.64, 'g'),
        ('白银',   'SILVER',   7.25, 413.79, 'g'),
        ('铂金',   'PLAT',  420.00,  23.81, 'g'),
    ],
    # ── 商业投资 (mt_live_business_inv) ──
    'BUSINESS': [
        # (inv_code, inv_name, inv_type, amount, equity_pct, expected_irr)
        ('PE-ANDR-2025A', '仙女座智能科技A轮',   '股权直投', 15000,  3.5, 18.0),
        ('VC-EDU-2025B',  'MTSCOS教育科技优先股', '可转债',   10000,  0.0, 12.0),
        ('RE-COMM-001',   '核心商圈写字楼REIT',  'REITs',     5000,  0.0,  6.5),
    ],
    # ── 保险 (mt_live_insurance) ──
    'INSURANCE': [
        # (policy_code, policy_name, insurer, premium, coverage, policy_type)
        ('PIC-INS-GA-001', '平安福2024重疾险', '平安人寿', 3800, 500000, '重疾险'),
        ('PIC-INS-DIV-002', '平安金生利分红险', '平安人寿', 3000,  50000, '分红险'),
        ('PIC-INS-MUT-003', '平安安心百万医疗', '平安健康',  800, 4000000, '医疗险'),
    ],
}


# ──────────────────────────────────────────────────────────────────────
# Phase 1.1: 清空旧数据 (幂等, 保留 mt_live_account 升级)
# ──────────────────────────────────────────────────────────────────────

def phase11_cleanup():
    print('\n🧹 Phase 1.1: 清理旧数据...')
    tables_to_clean = [
        'mt_live_position', 'mt_live_fund_position', 'mt_live_bank_product',
        'mt_live_term_deposit', 'mt_live_metal_position', 'mt_live_business_inv',
        'mt_live_insurance', 'mt_live_trade_log', 'mt_live_order',
    ]
    with safe_conn(DB) as conn:
        for t in tables_to_clean:
            try:
                conn.execute(f'DELETE FROM {t}')
            except Exception:
                pass
    print(f'   ✓ 清空 {len(tables_to_clean)} 张 LIVE 表')


# ──────────────────────────────────────────────────────────────────────
# Phase 1.2: 注入 A 股持仓 (mt_live_position)
# ──────────────────────────────────────────────────────────────────────

def phase12_stock():
    print('\n📈 Phase 1.2: A 股持仓注入...')
    rows = []
    for symbol, name, qty, avg_cost, price, prev_close in SEED_SYMBOLS['STOCK']:
        mv = qty * price
        cost = qty * avg_cost
        pnl = mv - cost
        pnl_pct = (price - avg_cost) / avg_cost * 100
        today_pnl = qty * (price - prev_close)
        rows.append((symbol, name, qty, avg_cost, price, pnl, pnl_pct, prev_close, today_pnl))

    safe_execmany(
        'INSERT INTO mt_live_position(symbol,name,qty,avg_cost,price,pnl,pnl_pct,prev_close,today_pnl) '
        'VALUES(?,?,?,?,?,?,?,?,?)', rows, DB
    )
    total_mv = sum(r[2] * r[4] for r in SEED_SYMBOLS['STOCK'])
    total_pnl = sum(r[2] * (r[4] - r[3]) for r in SEED_SYMBOLS['STOCK'])
    print(f'   ✓ {len(rows)} 只股票 | MV=¥{total_mv:,.0f} | PnL=¥{total_pnl:+,.0f}')
    return total_mv


# ──────────────────────────────────────────────────────────────────────
# Phase 1.3: 基金持仓 (mt_live_fund_position)
# ──────────────────────────────────────────────────────────────────────

def phase13_fund():
    print('\n📊 Phase 1.3: 基金持仓注入...')
    rows = []
    for code, name, price, qty in SEED_SYMBOLS['FUND']:
        prev_close = price * (1 + random.uniform(-0.02, 0.02))
        mv = qty * price
        today_pnl = qty * (price - prev_close)
        rows.append((code, name, price, qty, mv, today_pnl, prev_close))

    safe_execmany(
        'INSERT INTO mt_live_fund_position(fund_code,fund_name,price,qty,pnl,today_pnl,prev_close) '
        'VALUES(?,?,?,?,?,?,?)', rows, DB
    )
    total_mv = sum(r[5] for r in rows)  # r[5] = pnl? wait let me recalc
    total_mv = sum(q * p for _, _, p, q in SEED_SYMBOLS['FUND'])
    print(f'   ✓ {len(rows)} 只基金 | MV=¥{total_mv:,.0f}')
    return total_mv


# ──────────────────────────────────────────────────────────────────────
# Phase 1.4: 银行理财 + 定存 (mt_live_bank_product + mt_live_term_deposit)
# ──────────────────────────────────────────────────────────────────────

def phase14_bank():
    print('\n🏦 Phase 1.4: 银行理财 + 定存注入...')

    prod_rows = [(c, n, b, a, r) for c, n, b, a, r in SEED_SYMBOLS['BANK_PRODUCT']]
    safe_execmany(
        'INSERT INTO mt_live_bank_product(product_code,product_name,bank,amount,expected_return) '
        'VALUES(?,?,?,?,?)', prod_rows, DB
    )

    dep_rows = []
    now = datetime.now()
    for code, bank, amt, rate, months in SEED_SYMBOLS['DEPOSIT']:
        maturity = (now + timedelta(days=int(months * 30))).strftime('%Y-%m-%d')
        dep_rows.append((code, bank, amt, rate, months, maturity))
    safe_execmany(
        'INSERT INTO mt_live_term_deposit(deposit_code,bank,amount,rate,term_months,maturity_date) '
        'VALUES(?,?,?,?,?,?)', dep_rows, DB
    )

    total_product = sum(r[3] for r in prod_rows)
    total_deposit = sum(r[2] for r in dep_rows)
    print(f'   ✓ 理财 {len(prod_rows)} 只 ¥{total_product:,.0f} | 定存 {len(dep_rows)} 笔 ¥{total_deposit:,.0f}')
    return total_product + total_deposit


# ──────────────────────────────────────────────────────────────────────
# Phase 1.5: 贵金属 (mt_live_metal_position)
# ──────────────────────────────────────────────────────────────────────

def phase15_metal():
    print('\n🥇 Phase 1.5: 贵金属持仓注入...')
    rows = []
    for name, mtype, price, qty, unit in SEED_SYMBOLS['METAL']:
        prev_close = price * (1 + random.uniform(-0.015, 0.015))
        mv = qty * price
        today_pnl = qty * (price - prev_close)
        rows.append((name, mtype, price, qty, mv, today_pnl, prev_close, unit))

    safe_execmany(
        'INSERT INTO mt_live_metal_position(metal_name,metal_type,price,qty,pnl,today_pnl,prev_close,unit) '
        'VALUES(?,?,?,?,?,?,?,?)', rows, DB
    )
    total_mv = sum(q * p for _, _, p, q, _ in SEED_SYMBOLS['METAL'])
    print(f'   ✓ {len(rows)} 种贵金属 | MV=¥{total_mv:,.0f}')
    return total_mv


# ──────────────────────────────────────────────────────────────────────
# Phase 1.6: 商业投资 + 保险
# ──────────────────────────────────────────────────────────────────────

def phase16_business_insurance():
    print('\n💼 Phase 1.6: 商业投资 + 保险注入...')

    bus_rows = [(c, n, t, a, e, i) for c, n, t, a, e, i in SEED_SYMBOLS['BUSINESS']]
    safe_execmany(
        'INSERT INTO mt_live_business_inv(inv_code,inv_name,inv_type,amount,equity_pct,expected_irr) '
        'VALUES(?,?,?,?,?,?)', bus_rows, DB
    )

    ins_rows = [(c, n, i, p, cov, t) for c, n, i, p, cov, t in SEED_SYMBOLS['INSURANCE']]
    safe_execmany(
        'INSERT INTO mt_live_insurance(policy_code,policy_name,insurer,premium,coverage,policy_type) '
        'VALUES(?,?,?,?,?,?)', ins_rows, DB
    )

    total_bus = sum(r[3] for r in bus_rows)
    total_ins = sum(r[3] for r in ins_rows)
    print(f'   ✓ 商业投资 {len(bus_rows)} 项 ¥{total_bus:,.0f} | 保险 {len(ins_rows)} 份 ¥{total_ins:,.0f}')
    return total_bus + total_ins


# ──────────────────────────────────────────────────────────────────────
# Phase 1.7: 汇总 + 更新 mt_live_account (总账)
# ──────────────────────────────────────────────────────────────────────

def phase17_account(stock_mv, fund_mv, bank_mv, metal_mv, busins_mv):
    print('\n🏦 Phase 1.7: 更新总账 mt_live_account...')

    total_inv = stock_mv + fund_mv + bank_mv + metal_mv + busins_mv
    cash = CASH_RESERVE
    total_assets = total_inv + cash
    # 计算总 PnL (简化: 从各持仓的 pnl 聚合)
    with safe_conn(DB) as conn:
        stock_pnl = conn.execute('SELECT COALESCE(SUM(pnl),0) FROM mt_live_position').fetchone()[0]
        fund_pnl = conn.execute('SELECT COALESCE(SUM(pnl),0) FROM mt_live_fund_position').fetchone()[0]
        metal_pnl = conn.execute('SELECT COALESCE(SUM(pnl),0) FROM mt_live_metal_position').fetchone()[0]
    total_pnl = stock_pnl + fund_pnl + metal_pnl

    safe_exec('DELETE FROM mt_live_account', (), DB)
    safe_exec(
        'INSERT INTO mt_live_account(total_assets,available,market_value,cash,pnl,server_time,initial_cash) '
        'VALUES(?,?,?,?,?,?,?)',
        (total_assets, cash, total_inv, cash, total_pnl, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), total_assets),
        DB
    )
    print(f'   ✓ 总资产 ¥{total_assets:,.0f} | 投资 ¥{total_inv:,.0f} | 现金 ¥{cash:,.0f} | PnL ¥{total_pnl:+,.0f}')
    return total_assets, total_inv, cash


# ──────────────────────────────────────────────────────────────────────
# Phase 2: 跑 VaultLedgerEngine (ledger → journal → positions → balance_sheet)
# ──────────────────────────────────────────────────────────────────────

def phase2_vault():
    print('\n📒 Phase 2: VaultLedgerEngine 金库全套生成...')
    try:
        from engines.finance_ledger_engine import LedgerEngine
        eng = LedgerEngine(DB)
        eng._ensure_tables()

        # phase1: 从 mt_vault_trades 生成 (我们的交易在 mt_live_trade_log, 需要转换)
        # 简化: 直接 build_all 让 engine 从现有 vault 表聚合
        result = eng.build_all(refresh_prices=True)

        print(f'   ✓ LedgerEngine.build_all(): {result.get("status", "?")}')
        for k, v in result.items():
            if isinstance(v, (int, float)) and v != 0:
                print(f'      {k}: {v}')
    except ImportError as e:
        print(f'   ⚠ LedgerEngine import 失败: {e}')
        print('   → 手动跑 phase...')
        _phase2_manual()
    except Exception as e:
        print(f'   ⚠ LedgerEngine 运行失败: {e}')
        _phase2_manual()


def _phase2_manual():
    """LedgerEngine 不可用时的手动回退"""
    with safe_conn(DB) as conn:
        # vault_positions: 从 mt_live_position 映射
        try:
            conn.execute('DELETE FROM mt_vault_positions')
            conn.execute("""
                INSERT INTO mt_vault_positions(symbol, stock_name, qty, cost, market_value, pnl, pnl_pct, position_date)
                SELECT symbol, name, qty, avg_cost * qty AS cost, price * qty AS market_value,
                       (price - avg_cost) * qty AS pnl,
                       ROUND((price - avg_cost) / avg_cost * 100, 2) AS pnl_pct,
                       date('now','localtime')
                FROM mt_live_position WHERE qty > 0
            """)
            positions = conn.execute('SELECT COUNT(*) FROM mt_vault_positions').fetchone()[0]
            print(f'   ✓ 手动生成 mt_vault_positions: {positions} 条')
        except Exception as e:
            print(f'   mt_vault_positions: {e}')

        # vault_balance_sheet: 资产负债表快照
        try:
            conn.execute('DELETE FROM mt_vault_balance_sheet')
            la = conn.execute('SELECT * FROM mt_live_account LIMIT 1').fetchone()
            if la:
                conn.execute("""
                    INSERT INTO mt_vault_balance_sheet
                    (report_date, total_assets, total_liabilities, net_equity,
                     cash, market_value, fixed_assets, intangible_assets)
                    VALUES (date('now','localtime'), ?, 0, ?, ?, ?, 0, 0)
                """, (la['total_assets'], la['total_assets'], la['cash'], la['market_value']))
                print(f'   ✓ 手动生成 mt_vault_balance_sheet: total=¥{la["total_assets"]:,.0f}')
        except Exception as e:
            print(f'   mt_vault_balance_sheet: {e}')


# ──────────────────────────────────────────────────────────────────────
# Phase 3: PortfolioAllocator — 目标比例配置
# ──────────────────────────────────────────────────────────────────────

def phase3_portfolio_targets():
    print('\n🎯 Phase 3: PortfolioAllocator 目标比例配置...')

    TARGETS = [
        # channel_code, channel_name, target_pct, min_pct, max_pct
        ('CASH',        '现金储备',     20.0, 15.0, 30.0),
        ('STOCK',       'A 股',         30.0, 20.0, 40.0),
        ('FUND',        '基金',         16.0, 10.0, 22.0),
        ('BANK',        '银行理财',     12.0,  8.0, 18.0),
        ('DEPOSIT',     '定期存款',      8.0,  5.0, 12.0),
        ('METAL',       '贵金属',       6.0,  3.0, 10.0),
        ('BUSINESS',    '商业投资',     6.0,  3.0, 10.0),
        ('INSURANCE',   '保险对冲',     2.0,  1.0,  4.0),
    ]

    # 存入一张新表 (如果不存在)
    safe_exec(
        """CREATE TABLE IF NOT EXISTS mt_portfolio_target (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_code TEXT UNIQUE,
            channel_name TEXT,
            target_pct REAL DEFAULT 0,
            min_pct REAL DEFAULT 0,
            max_pct REAL DEFAULT 100,
            current_pct REAL DEFAULT 0,
            last_rebalanced TEXT,
            status TEXT DEFAULT 'ACTIVE'
        )""", (), DB
    )

    with safe_conn(DB) as conn:
        for code, name, t, lo, hi in TARGETS:
            conn.execute(
                'INSERT OR REPLACE INTO mt_portfolio_target(channel_code,channel_name,target_pct,min_pct,max_pct) '
                'VALUES(?,?,?,?,?)', (code, name, t, lo, hi)
            )
        total = conn.execute('SELECT COUNT(*) FROM mt_portfolio_target').fetchone()[0]

    print(f'   ✓ {total} 渠道目标比例已配置')
    for code, name, t, lo, hi in TARGETS:
        print(f'      {code:10s} {name:10s} → target={t:5.1f}% range=[{lo:.0f}%, {hi:.0f}%]')


# ──────────────────────────────────────────────────────────────────────
# Phase 4: Dashboard 端到端验证
# ──────────────────────────────────────────────────────────────────────

def phase4_verify():
    print('\n✅ Phase 4: 端到端验证...')
    import urllib.request

    checks = [
        ('GET', 'http://localhost:8888/api/finance/governance/portfolio/allocation'),
        ('GET', 'http://localhost:8888/api/finance/governance/centers/status'),
        ('GET', 'http://localhost:8888/api/finance/governance/proposals'),
        ('GET', 'http://localhost:8888/api/finance/governance/centers/exec-log'),
        ('GET', 'http://localhost:8888/dashboard'),
    ]

    for method, url in checks:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = resp.status
                body = resp.read().decode()[:200]
                ok = '✅' if code == 200 else '❌'
                print(f'   {ok} {url.split("/")[-1]:25s} HTTP {code}')
        except Exception as e:
            print(f'   ❌ {url.split("/")[-1]:25s} ERR: {e}')

    # DB 数据计数
    print('\n📊 DB 数据盘点:')
    for t in ['mt_live_account', 'mt_live_position', 'mt_live_fund_position',
              'mt_live_bank_product', 'mt_live_term_deposit', 'mt_live_metal_position',
              'mt_live_business_inv', 'mt_live_insurance',
              'mt_portfolio_target',
              'mt_center_registry', 'mt_investment_proposal', 'mt_task_queue',
              'mt_vault_positions', 'mt_vault_balance_sheet']:
        try:
            cnt = safe_query_one(f'SELECT COUNT(*) as c FROM {t}')['c']
            print(f'      {t:30s} → {cnt}')
        except Exception as e:
            print(f'      {t:30s} → ERR: {e}')


# ──────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────

def main():
    print('=' * 70)
    print('🏦 Gobelin Bank · 投资架构全链路初始化')
    print('=' * 70)
    print(f'  DB: {DB}')
    print(f'  总资产目标: ¥{TOTAL_PORTFOLIO:,.0f}')
    print(f'  现金储备:   ¥{CASH_RESERVE:,.0f}')
    print(f'  投资总额:   ¥{TOTAL_PORTFOLIO - CASH_RESERVE:,.0f}')

    phase11_cleanup()
    stock_mv = phase12_stock()
    fund_mv = phase13_fund()
    bank_mv = phase14_bank()
    metal_mv = phase15_metal()
    busins_mv = phase16_business_insurance()
    total, inv, cash = phase17_account(stock_mv, fund_mv, bank_mv, metal_mv, busins_mv)
    phase2_vault()
    phase3_portfolio_targets()
    phase4_verify()

    print('\n' + '=' * 70)
    print('🎉 投资架构全链路初始化完成!')
    print('=' * 70)


if __name__ == '__main__':
    main()
