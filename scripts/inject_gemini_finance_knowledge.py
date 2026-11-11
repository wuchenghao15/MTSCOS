#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古灵阁金融团队扩展 — 知识一键注入
==================================

向 mt_center_knowledge_points + mt_fm_brain_feed 写入 20 条知识点:
  · 创业板 vs 主板 差异 (注册制/20%涨跌/高成长高风险)
  · 十大创业板操盘心法 (量能优先/MACD零轴/题材龙头/趋势为王/止损纪律等)
  · 古灵阁金融团队新结构 (创业板突击队/量化套利组/B股外汇组/风控AI专员)
  · 金融数据本地优先原则 (加密分级/双备份/AI专员跟踪)

用法:
  python3 scripts/inject_gemini_finance_knowledge.py [--dry-run]

FLOW_ID: flow_gemini_inject_20261108
"""
from __future__ import annotations

import json
import sqlite3
import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径解析 ──
_FLASK_APP_DIR = Path(__file__).resolve().parent.parent

# DB 路径候选
_DB_CANDIDATES = [
    str(_FLASK_APP_DIR / "database" / "app.db"),
]


def _find_db() -> str:
    for c in _DB_CANDIDATES:
        if Path(c).exists():
            return c
    # fallback: 环境变量
    import os
    env = os.environ.get('MTSCOS_DB_PATH', '')
    if env and Path(env).exists():
        return env
    return _DB_CANDIDATES[0]


DB_PATH = _find_db()
FLOW_ID = "flow_gemini_inject_20261108"


# ══════════════════════════════════════════════════════════════════
# 知识点 (20 条)
# ══════════════════════════════════════════════════════════════════

KNOWLEDGE_POINTS = [
    # ── 板块 1: 创业板 vs 主板 差异 (6 条) ──
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板定位 — 创新型企业专属战场',
        'knowledge_body': '创业板 (300xxx) 定位创新型成长企业, 注册制上市, 无盈利硬性要求, 适合科技/新能源/生物医药等高成长赛道。与主板 (600xxx/000xxx) 的成熟蓝筹定位形成互补。',
        'confidence': 0.95,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板涨跌停 20% — 波动翻倍, 风险也翻倍',
        'knowledge_body': '创业板实行 20% 涨跌幅限制 (主板 10%), 且新股前 5 日无涨跌停限制。这意味着单日最大理论浮亏可达 20%~40%, 5% 硬止损在创业板必须更严格执行。',
        'confidence': 0.98,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板注册制 — 退市机制更严格',
        'knowledge_body': '注册制下创业板上市门槛降低, 但退市指标也更严格: 连续 20 日市值低于 3 亿/营收 1 亿/净资产为负, 且 ST 后 5 个交易日不改善直接退市。操盘必须规避"有退市风险"标的。',
        'confidence': 0.92,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板成分指数 — 399006 vs 科创 000688',
        'knowledge_body': '创业板指 (399006) 反映整体, 创 50 (399016) 精选龙头。科创板 (000688) 定位硬科技, 也 20% 涨跌, 但开户门槛 50 万+2 年交易经验。仙女座操盘系统统一纳入 cyb_kg = 创业板+科创板监控。',
        'confidence': 0.88,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板流动性 — 成交额低于主板',
        'knowledge_body': '创业板单票日均成交额中位数约为主板的 40%~60%。小盘股 (<100 亿) 流动性更差, 易出现"买不进卖不出"。仙女座风控: 创业板标的 20 日平均成交额 > 3 亿才纳入候选。',
        'confidence': 0.90,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板估值特征 — PE 普遍高于主板',
        'knowledge_body': '创业板整体 PE (TTM) 通常在 40~80 倍区间, 远高于主板的 15~25 倍。估值驱动因素是营收增速而非利润。估值锚定采用 PEG = PE / 营收增速, PEG < 1 被视为相对合理。',
        'confidence': 0.91,
    },

    # ── 板块 2: 十大创业板操盘心法 (8 条) ──
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法一: 量能优先 — 创业板资金为王',
        'knowledge_body': '创业板 20% 涨跌 + 低流动性 = 量能是第一指标。突破必须伴随成交量放大 (日量 > 5日均量 1.5 倍), 无量突破大概率假突破。缩量回调到 20 日线 + 放量止跌 = 最佳买点。',
        'confidence': 0.97,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法二: MACD 零轴 — 创业板趋势生命线',
        'knowledge_body': '创业板波动率大, MACD 在零轴上方 = 多头市场 (积极做多), 零轴下方 = 空头 (空仓或仅超短)。零轴金叉 + 量能放大 = 趋势启动信号。死叉 + 缩量 = 趋势衰竭, 准备离场。',
        'confidence': 0.94,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法三: 题材龙头 — 创业板最赚钱模式',
        'knowledge_body': '创业板跟随政策/题材炒作 (新能源/AI/创新药等)。龙头识别法: 板块内最先涨停 + 封板时间最长 + 换手率最高 + 机构席位上榜。龙头溢价通常 30%~80% 强于板块平均。',
        'confidence': 0.93,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法四: 趋势为王 — 不猜顶不抄底',
        'knowledge_body': '创业板趋势性强, 一旦启动容易走出翻倍行情。顺势策略: 20 日线多头排列 + MACD 零轴上方 → 持仓不动。逆势交易 (猜顶抄底) 在创业板死亡率高达 85%。',
        'confidence': 0.96,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法五: 止损纪律 — 20% 涨跌下的生存线',
        'knowledge_body': '创业板 20% 涨跌意味着单日可能亏 20%, 5% 硬止损必须升级: · 单票浮亏 3% 触发预警 · 5% 无条件止损 (主板是 5%, 创业板也 5% 但执行更严) · 跳空低开 > 8% 直接市价止损不挂限价',
        'confidence': 0.99,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法六: 分仓滚动 — 创业板仓位控制',
        'knowledge_body': '创业板单票仓位上限 15% (主板 20%), 总仓位上限 60% (主板 80%)。建仓分三档: 30%/30%/40%。加仓条件: 第一档 +5% 以上 + 量能配合。创业板禁止一次性满仓买入。',
        'confidence': 0.94,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法七: 龙虎榜跟踪 — 识别聪明钱',
        'knowledge_body': '创业板机构/游资动向通过龙虎榜可追踪。重点关注: 机构专用席位净买入 (看好基本面), 知名游资席位 (章盟主/葛卫东/赵老哥等) 活跃。连续 3 日机构净买入 = 高置信度信号。',
        'confidence': 0.89,
    },
    {
        'kp_type': 'market_knowledge',
        'center_name': 'gobelin_trading',
        'knowledge_title': '心法八: 北向资金 — 外资风向指标',
        'knowledge_body': '北向资金持续净流入创业板 = 外资看多成长风格。累计净流入 > 200 亿 + 创业板指站上 60 日线 = 加仓信号。北向连续 3 日净流出 > 50 亿 = 减仓防御。',
        'confidence': 0.87,
    },

    # ── 板块 3: 古灵阁金融团队新结构 (3 条) ──
    {
        'kp_type': 'finance_team_expansion',
        'center_name': 'gobelin_trading',
        'knowledge_title': '古灵阁金融团队扩展矩阵 — 4 个新小组',
        'knowledge_body': '仙女座操盘系统金融团队从原来十专家 (R-01~R-10) 扩展为: ①创业板突击队 (专职 300xxx/688xxx) ②量化套利组 (因子挖掘 + 高频信号) ③B股外汇组 (900xxx/200xxx + QDII) ④风控 AI 专员 (实时风险监控 + 自适应止损)。每组 2 人 + AI 搭档。',
        'confidence': 0.95,
    },
    {
        'kp_type': 'finance_team_expansion',
        'center_name': 'gobelin_trading',
        'knowledge_title': '创业板突击队 — 快进快出 20% 战场',
        'knowledge_body': '创业板突击队专职任务: 每日盘前扫描创业板/科创板涨停候选 (量能 + MACD + 题材匹配), 盘中实时监控, 盘后快速复盘。执行纪律: · 持仓周期 T+1~T+5 · 单日仓位上限 10% · 止损 3% 预警 / 5% 硬执行。',
        'confidence': 0.92,
    },
    {
        'kp_type': 'finance_team_expansion',
        'center_name': 'gobelin_trading',
        'knowledge_title': '量化套利组 + B股外汇组 — 双市场覆盖',
        'knowledge_body': '量化套利组: 统计套利 (同行业 A-H 溢价回归) + 因子择时 (动量/价值/波动三因子) + ETF 折溢价套利。B 股外汇组: 900xxx (沪 B, USD)/200xxx (深 B, HKD) 行情跟踪 + A-H 溢价率监控 + QDII 额度使用优化。',
        'confidence': 0.90,
    },

    # ── 板块 4: 金融数据本地优先原则 (3 条) ──
    {
        'kp_type': 'finance_team_expansion',
        'center_name': 'gobelin_trading',
        'knowledge_title': '金融数据加密分级 — L1/L2/L3 三级',
        'knowledge_body': '仙女座操盘系统数据安全加密分级: L1 (公开): 行情快照/板块热度, 明文存储; L2 (敏感): 持仓/交易记录/专家会诊, AES-256 加密; L3 (核心): VIKEY 密钥/硬件口令/资金密码, 内存态仅存, 不落盘。',
        'confidence': 0.97,
    },
    {
        'kp_type': 'finance_team_expansion',
        'center_name': 'gobelin_trading',
        'knowledge_title': '金融数据双备份 — WAL + 定时复制',
        'knowledge_body': '所有金融相关表 (mt_trade_log/mt_sandbox_portfolio/mt_center_knowledge_points/mt_center_evolution_log) 采用 SQLite WAL 模式实时备份, 每日凌晨 2:00 执行 .db → backup/ 目录硬链接复制, 每周日执行完整 VACUUM + 增量备份。保留最近 30 天。',
        'confidence': 0.96,
    },
    {
        'kp_type': 'finance_team_expansion',
        'center_name': 'gobelin_trading',
        'knowledge_title': 'AI 风控专员全程跟踪 — 写入即日志',
        'knowledge_body': '所有金融关键表 (持仓/下单/风控调整) 的写入必须同步记录到 mt_center_evolution_log, 包含: action (INSERT/UPDATE/DELETE) + actor (用户/daemon/AI) + timestamp + detail JSON。风控 AI 专员实时监控异常写入模式 (如 1 分钟内 10+ 次 UPDATE 同一持仓)。',
        'confidence': 0.98,
    },
]

assert len(KNOWLEDGE_POINTS) == 20, f"预期 20 条, 实际 {len(KNOWLEDGE_POINTS)}"


# ══════════════════════════════════════════════════════════════════
# mt_fm_brain_feed 注入内容 (简化版, 每条一条 feed)
# ══════════════════════════════════════════════════════════════════

BRAIN_FEEDS = [
    # stream_name='FINANCE_TEAM_EXPANSION', category='GOBELIN'
    {
        'stream_name': 'FINANCE_TEAM_EXPANSION',
        'category': 'GOBELIN',
        'asr_text': '[脑库·金融扩展] 创业板 vs 主板核心差异: 注册制 / 20%涨跌 / 无盈利要求 / 退市更严 / PE估值更高 / 流动性更弱。操盘策略必须差异化。',
        'trigger_keywords': '创业板,主板,20%涨跌,注册制',
        'emotion': '中性', 'emotion_score': 0.5,
        'has_price_info': 0, 'has_policy': 1,
    },
    {
        'stream_name': 'FINANCE_TEAM_EXPANSION',
        'category': 'GOBELIN',
        'asr_text': '[脑库·操盘心法] 创业板八大核心: 量能优先 > MACD零轴 > 题材龙头 > 趋势为王 > 止损纪律 > 分仓滚动 > 龙虎榜跟踪 > 北向资金风向。',
        'trigger_keywords': '操盘,创业板,心法,量能,MACD,止损',
        'emotion': '积极', 'emotion_score': 0.7,
        'has_price_info': 0, 'has_policy': 0,
    },
    {
        'stream_name': 'FINANCE_TEAM_EXPANSION',
        'category': 'GOBELIN',
        'asr_text': '[脑库·团队扩展] 古灵阁金融团队新增四小组: 创业板突击队 / 量化套利组 / B股外汇组 / 风控AI专员。每组 2 人 + AI 搭档, 24/7 覆盖多市场。',
        'trigger_keywords': '古灵阁,团队,突击队,量化,B股,风控',
        'emotion': '积极', 'emotion_score': 0.75,
        'has_price_info': 0, 'has_policy': 0,
    },
    {
        'stream_name': 'FINANCE_TEAM_EXPANSION',
        'category': 'SECURITY',
        'asr_text': '[脑库·安全架构] 金融数据三级加密: L1公开/L2敏感(AES-256)/L3核心(内存态)。WAL实时备份 + 每日硬链接复制 + 每周VACUUM。AI风控专员全程跟踪写入。',
        'trigger_keywords': '安全,加密,WAL,备份,AES,风控AI',
        'emotion': '中性', 'emotion_score': 0.6,
        'has_price_info': 0, 'has_policy': 1,
    },
    {
        'stream_name': 'FINANCE_TEAM_EXPANSION',
        'category': 'MARKET',
        'asr_text': '[脑库·B股市场] B股是被低估的独立市场: 沪B(900xxx,USD)/深B(200xxx,HKD)。A-H溢价持续, QDII额度紧俏, B股折价10~30%是常态。',
        'trigger_keywords': 'B股,900,200,USD,HKD,A-H溢价,QDII',
        'emotion': '积极', 'emotion_score': 0.65,
        'has_price_info': 1, 'has_policy': 1,
    },
]


# ══════════════════════════════════════════════════════════════════
# DB 操作
# ══════════════════════════════════════════════════════════════════

def _ensure_tables(conn: sqlite3.Connection) -> None:
    """确保目标表存在"""
    # mt_center_knowledge_points
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mt_center_knowledge_points (
            kp_id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_name TEXT,
            kp_type TEXT,
            source_table TEXT,
            source_row_id INTEGER,
            knowledge_title TEXT,
            knowledge_body TEXT,
            confidence REAL,
            applied INTEGER DEFAULT 0,
            applied_at TEXT,
            created_at TEXT
        )
    """)
    # mt_fm_brain_feed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mt_fm_brain_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_name TEXT,
            category TEXT,
            asr_text TEXT,
            trigger_keywords TEXT,
            emotion TEXT,
            emotion_score REAL,
            has_price_info INTEGER DEFAULT 0,
            has_policy INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)


def inject(dry_run: bool = False) -> dict:
    """执行注入"""
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    _ensure_tables(conn)

    stats = {'kp_inserted': 0, 'feed_inserted': 0, 'errors': []}

    # ── 去重检查: 同 title 已存在则跳过 ──
    existing_titles = set()
    try:
        cur.execute(
            "SELECT knowledge_title FROM mt_center_knowledge_points "
            "WHERE center_name='gobelin_trading' AND kp_type IN ('finance_team_expansion','market_knowledge')"
        )
        existing_titles = {r[0] for r in cur.fetchall()}
    except Exception as e:
        stats['errors'].append(f'dedup check: {e}')

    # ── mt_center_knowledge_points 注入 ──
    for kp in KNOWLEDGE_POINTS:
        if kp['knowledge_title'] in existing_titles:
            print(f"  [SKIP] 已存在: {kp['knowledge_title'][:40]}...")
            continue

        if dry_run:
            stats['kp_inserted'] += 1
            print(f"  [DRY] kp_insert: {kp['knowledge_title'][:50]}")
            continue

        try:
            cur.execute(
                """INSERT INTO mt_center_knowledge_points
                   (center_name, kp_type, knowledge_title, knowledge_body, confidence, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    kp['center_name'],
                    kp['kp_type'],
                    kp['knowledge_title'],
                    kp['knowledge_body'],
                    kp['confidence'],
                    now,
                )
            )
            stats['kp_inserted'] += 1
            print(f"  [OK] kp_insert: {kp['knowledge_title'][:50]}")
        except Exception as e:
            stats['errors'].append(f"kp: {e}")
            print(f"  [ERR] kp: {e}")

    # ── mt_fm_brain_feed 注入 ──
    for feed in BRAIN_FEEDS:
        if dry_run:
            stats['feed_inserted'] += 1
            print(f"  [DRY] feed_insert: {feed['stream_name']} | {feed['asr_text'][:40]}...")
            continue

        try:
            cur.execute(
                """INSERT INTO mt_fm_brain_feed
                   (stream_name, category, asr_text, trigger_keywords, emotion, emotion_score,
                    has_price_info, has_policy, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    feed['stream_name'],
                    feed['category'],
                    feed['asr_text'],
                    feed['trigger_keywords'],
                    feed['emotion'],
                    feed['emotion_score'],
                    feed['has_price_info'],
                    feed['has_policy'],
                    now,
                )
            )
            stats['feed_inserted'] += 1
            print(f"  [OK] feed_insert: {feed['stream_name']} | {feed['category']}")
        except Exception as e:
            stats['errors'].append(f"feed: {e}")
            print(f"  [ERR] feed: {e}")

    # ── 写 evolution_log 记录 ──
    try:
        detail = json.dumps({
            'flow_id': FLOW_ID,
            'kp_total': len(KNOWLEDGE_POINTS),
            'kp_inserted': stats['kp_inserted'],
            'feed_total': len(BRAIN_FEEDS),
            'feed_inserted': stats['feed_inserted'],
            'dry_run': dry_run,
        }, ensure_ascii=False)
        cur.execute(
            "INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
            ('gobelin_trading', 'FINANCE_TEAM_EXPANSION_INJECT', detail)
        )
        print(f"\n✓ evolution_log 已记录 (flow={FLOW_ID})")
    except Exception as e:
        stats['errors'].append(f'evolution_log: {e}')

    conn.close()
    return stats


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='古灵阁金融团队知识一键注入')
    parser.add_argument('--dry-run', action='store_true', help='干跑, 不实际写入 DB')
    args = parser.parse_args()

    print(f"\n{'#'*60}")
    print(f"# 古灵阁金融团队扩展 — 知识注入")
    print(f"# DB: {DB_PATH}")
    print(f"# flow_id: {FLOW_ID}")
    print(f"# 模式: {'DRY-RUN' if args.dry_run else 'REAL'}")
    print(f"{'#'*60}")
    print(f"\n📚 mt_center_knowledge_points: {len(KNOWLEDGE_POINTS)} 条待注入")
    print(f"📡 mt_fm_brain_feed: {len(BRAIN_FEEDS)} 条待注入\n")

    stats = inject(dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"✅ 注入完成:")
    print(f"   · knowledge_points 插入: {stats['kp_inserted']}/{len(KNOWLEDGE_POINTS)}")
    print(f"   · brain_feed 插入:       {stats['feed_inserted']}/{len(BRAIN_FEEDS)}")
    if stats['errors']:
        print(f"   · 错误:                  {len(stats['errors'])}")
        for e in stats['errors'][:5]:
            print(f"     - {e}")
    print(f"{'='*60}\n")
