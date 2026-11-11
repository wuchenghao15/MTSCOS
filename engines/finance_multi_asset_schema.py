#!/usr/bin/env python3
"""古灵阁 v3 — 多资产投资系统 数据库 Schema"""
import sqlite3, os

DB = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
c = sqlite3.connect(DB)

# ── 1. 银行理财产品 (日日投 T+1 / 周周投 T+5) ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_live_bank_product (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT UNIQUE,          -- e.g. ICBC_T1_001
    product_name TEXT,                 -- 工银日日盈
    product_type TEXT,                 -- DAILY_T1 / WEEKLY_T5 / TERM_3M / TERM_6M / TERM_1Y
    provider TEXT,                     -- 工行 / 招行 / 建行
    principal REAL,                    -- 投入本金
    annual_rate REAL,                  -- 预期年化收益率
    risk_level TEXT DEFAULT 'LOW',     -- LOW / MEDIUM / HIGH
    lock_days INTEGER DEFAULT 1,       -- 锁定期天数
    open_date TEXT,                    -- 购入日期
    maturity_date TEXT,                -- 到期日 (定期)
    status TEXT DEFAULT 'ACTIVE',      -- ACTIVE / MATURED / REDEEMED
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 2. 基金持仓 ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_live_fund_position (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code TEXT UNIQUE,             -- 005827 等
    fund_name TEXT,
    fund_type TEXT,                    -- ACTIVE / INDEX / ETF / QDII
    qty REAL,                          -- 份额
    avg_cost REAL,                     -- 均价
    price REAL,                        -- 最新净值
    prev_close REAL,                   -- 上日净值
    pnl REAL,                          -- 累计盈亏
    pnl_pct REAL,
    today_pnl REAL,
    update_time TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 3. 定期存款 ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_live_term_deposit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deposit_code TEXT UNIQUE,
    bank TEXT,
    amount REAL,                       -- 存入金额
    annual_rate REAL,
    term_months INTEGER,               -- 3 / 6 / 12
    open_date TEXT,
    maturity_date TEXT,
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 4. 商业投资 (商铺 / 股权 / 私募) ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_live_business_inv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inv_code TEXT UNIQUE,
    inv_name TEXT,
    inv_type TEXT,                     -- COMMERCIAL / EQUITY / PE / REAL_ESTATE
    amount REAL,
    expected_return REAL,              -- 预期年化
    lock_months INTEGER,
    entry_date TEXT,
    exit_date TEXT,
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 5. 商业保险 / 财险 ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_live_insurance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_code TEXT UNIQUE,
    policy_name TEXT,
    insurance_type TEXT,               -- PROPERTY / LIABILITY / LIFE / ENDOWMENT
    provider TEXT,
    premium REAL,                      -- 年交保费
    coverage REAL,                     -- 保额
    start_date TEXT,
    end_date TEXT,
    cash_value REAL,                   -- 现金价值 (分红险)
    status TEXT DEFAULT 'ACTIVE',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 6. 稀有金属 (黄金/白银 ETF) ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_live_metal_position (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT UNIQUE,                -- 518880 (黄金ETF) / 159934 (白银ETF)
    metal_name TEXT,
    qty REAL,
    avg_cost REAL,
    price REAL,
    prev_close REAL,
    pnl REAL,
    pnl_pct REAL,
    today_pnl REAL,
    update_time TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 7. 投资会议记录 (所有会议必须落盘) ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_meeting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT UNIQUE,            -- REGULAR_YYYYMMDD / CRISIS_YYYYMMDD_HHMM
    meeting_type TEXT,                 -- REGULAR / MONTHLY / CRISIS / STRATEGY
    title TEXT,
    convener TEXT,                     -- 召集人 (AI 员工名)
    attendants TEXT,                   -- 参会人 (JSON)
    agenda TEXT,                       -- 议程
    minutes TEXT,                      -- 会议纪要 (markdown)
    decisions TEXT,                    -- 决策 (JSON)
    action_items TEXT,                 -- 待办 (JSON)
    risk_flags TEXT,                   -- 风险标记 (JSON)
    disaster_plan TEXT,                -- 灾难补救方案 (仅 CRISIS)
    status TEXT DEFAULT 'DRAFT',       -- DRAFT / APPROVED / EXECUTED
    recorded_at TEXT DEFAULT (datetime('now','localtime')),
    archive_path TEXT                  -- 归档文件路径
);
""")

# ── 8. 投资组合快照 (每日总览) ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_portfolio_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snap_date TEXT UNIQUE,
    total_assets REAL,
    cash REAL,
    stock_mv REAL,
    fund_mv REAL,
    bank_product_mv REAL,
    term_deposit REAL,
    business_inv REAL,
    insurance_cash_value REAL,
    metal_mv REAL,
    total_pnl REAL,
    total_pnl_pct REAL,
    today_pnl REAL,
    channel_allocation TEXT,           -- JSON: {"stock":0.3,"fund":0.2,...}
    risk_score REAL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ── 9. 投资决策提案 (Finance Council 产出) ──
c.executescript("""
CREATE TABLE IF NOT EXISTS mt_investment_proposal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT UNIQUE,
    proposal_type TEXT,                -- ALLOCATION / BUY / SELL / SWITCH
    channel TEXT,                      -- STOCK / FUND / BANK_PRODUCT / ...
    target TEXT,                       -- 股票代码 / 基金代码 / 产品名
    action TEXT,                       -- BUY / SELL / HOLD / SWITCH
    amount REAL,                       -- 建议金额
    rationale TEXT,                    -- 决策理由
    risk_assessment TEXT,              -- 风险评估
    expected_return REAL,
    voting_result TEXT,                -- 投票结果 (JSON)
    status TEXT DEFAULT 'PENDING',     -- PENDING / APPROVED / REJECTED / EXECUTED
    created_at TEXT DEFAULT (datetime('now','localtime')),
    executed_at TEXT,
    executor TEXT
);
""")

# ── 索引 ──
c.executescript("""
CREATE INDEX IF NOT EXISTS idx_meeting_type ON mt_meeting_log(meeting_type);
CREATE INDEX IF NOT EXISTS idx_meeting_date ON mt_meeting_log(recorded_at);
CREATE INDEX IF NOT EXISTS idx_snapshot_date ON mt_portfolio_snapshot(snap_date);
CREATE INDEX IF NOT EXISTS idx_proposal_status ON mt_investment_proposal(status);
CREATE INDEX IF NOT EXISTS idx_bank_product_status ON mt_live_bank_product(status);
CREATE INDEX IF NOT EXISTS idx_term_deposit_maturity ON mt_live_term_deposit(maturity_date);
""")

c.commit()
c.close()
print("✅ 古灵阁 v3 多资产投资系统 — 9 张表 + 6 索引 创建完成")
print("   账户起始: ¥10,000 现金 · 0 持仓 · 2026-11-11")
print("   七大渠道: A股 / 基金 / 银行理财 / 定期存款 / 商业投资 / 财险 / 稀有金属")
print("   会议机制: 例会 3天 · 月度 1号 · 紧急 (亏损触发)")
print("   六大中心: 文案 / 人事 / 战略 / 新闻 / 教育 / 数据 / 考试")
