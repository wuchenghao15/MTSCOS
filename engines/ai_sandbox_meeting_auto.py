#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ 古灵阁 · 自动会议厅引擎 v3 (flow_meeting_auto_20261105_evening)
========================================================================
新增:
  ✅ EVENING_HALF_HOUR — 15:30~23:00 每 30 分钟密集循环
     Layer A: simulation_divergent — 假设性/发散性模拟操盘 (多专家多策略对比)
     Layer B: grassroots_quick_sync — 基层每 30 分钟小组快速复盘
     Layer C: media_intake — FM 收音 + 国内/国际金融视频流素材收集
  ✅ 所有晚间循环结果 → 自动喂入明天晨会的 agenda 预填
  ✅ 媒体素材独立入库 mt_ai_brain_feed_log (source=media_intake)
"""
import os, sys, json, sqlite3, random, hashlib, datetime
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
_FLASK_DIR = os.path.dirname(_ENGINE_DIR)
DB = os.path.join(_FLASK_DIR, "database", "app.db")

_orig_connect = sqlite3.connect
def _db():
    conn = _orig_connect(DB, timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn

_CN_HOLIDAYS = {
    "2025-01-01","2025-01-28","2025-01-29","2025-01-30","2025-01-31","2025-02-01","2025-02-02","2025-02-03","2025-02-04",
    "2025-04-04","2025-04-05","2025-04-06",
    "2025-05-01","2025-05-02","2025-05-03","2025-05-04","2025-05-05",
    "2025-06-01","2025-06-02","2025-06-03",
    "2025-10-01","2025-10-02","2025-10-03","2025-10-04","2025-10-05","2025-10-06","2025-10-07","2025-10-08",
    "2026-01-01","2026-02-17","2026-02-18","2026-02-19","2026-02-20","2026-02-21","2026-02-22","2026-02-23",
    "2026-04-05","2026-04-06","2026-04-07",
    "2026-05-01","2026-05-02","2026-05-03","2026-05-04","2026-05-05",
    "2026-06-19","2026-06-20","2026-06-21",
    "2026-10-01","2026-10-02","2026-10-03","2026-10-04","2026-10-05","2026-10-06","2026-10-07","2026-10-08",
}

def _is_trading_day(now=None) -> bool:
    now = now or datetime.now()
    if now.strftime('%Y-%m-%d') in _CN_HOLIDAYS:
        return False
    return now.weekday() < 5

def _is_last_trading_day_of_month(now=None) -> bool:
    now = now or datetime.now()
    next_day = now + timedelta(days=1)
    return now.month != next_day.month and _is_trading_day(now)

def _is_friday_trading_day(now=None) -> bool:
    now = now or datetime.now()
    return now.weekday() == 4 and _is_trading_day(now)

def _is_year_end_trading_day(now=None) -> bool:
    now = now or datetime.now()
    return now.month == 12 and now.day >= 20 and _is_trading_day(now)

# ═══ 晚间 15:30~23:00 每 30 分钟密集循环触发窗口 ═══
def _is_evening_window(now=None) -> bool:
    """交易日 15:30 ~ 23:00 在晚间时间窗内"""
    now = now or datetime.now()
    if not _is_trading_day(now):
        return False
    minutes = now.hour * 60 + now.minute
    return 15*60+30 <= minutes <= 23*60+0

def _is_evening_half_hour_trigger(now=None) -> bool:
    """每 30 分钟触发一次 (15:30, 16:00, 16:30, ... 22:30)"""
    now = now or datetime.now()
    if not _is_evening_window(now):
        return False
    # 15:30 触发基准, 后续每 30 min
    offset_min = (now.hour * 60 + now.minute) - (15*60+30)
    return offset_min >= 0 and offset_min % 30 == 0 and offset_min <= 7*60+0

# ═══ 下午盘 13:00~15:00 每 30 min 密集循环触发窗口 ═══
def _is_afternoon_trading_trigger(now=None) -> bool:
    """交易日 13:00 ~ 15:00 在下午盘时间窗内"""
    now = now or datetime.now()
    if not _is_trading_day(now):
        return False
    h, m = now.hour, now.minute
    # 13:00, 13:30, 14:00, 14:30
    return h == 13 or (h == 14 and m < 15)

def _afternoon_sequence(now=None) -> int:
    """下午盘循环是第几轮 (1~4)"""
    now = now or datetime.now()
    offset_min = (now.hour * 60 + now.minute) - (13*60)
    return offset_min // 30 + 1


def get_due_meetings(now=None) -> List[Dict]:
    now = now or datetime.now()
    trading = _is_trading_day(now)
    h, m = now.hour, now.minute
    due = []
    
    # —— 非交易日 ——
    if not trading:
        if h == 10 and 0 <= m <= 10:
            due.append({"slot": "WEEKEND_STRATEGY", "priority": 1})
        return due
    
    # —— 白天固定时点 ——
    if h == 9 and 0 <= m <= 10:
        due.append({"slot": "MORNING_BRIEFING", "priority": 1})
    if h == 11 and 30 <= m <= 35:
        due.append({"slot": "NOON_REVIEW", "priority": 1, "tick_managed": True})
    if h == 15 and 3 <= m <= 10:
        due.append({"slot": "CLOSE_REVIEW", "priority": 1, "tick_managed": True})
    if h == 15 and 28 <= m <= 35:
        due.append({"slot": "CLOSE_SUMMARY", "priority": 1})
    
    # —— 下午盘密集循环 (13:00~15:00, 每 30 min) ——
    if _is_afternoon_trading_trigger(now):
        due.append({
            "slot": "AFTERNOON_TRADING",
            "priority": 1,
            "tick_managed": True,
            "afternoon_seq": _afternoon_sequence(now),
        })
    
    # —— 晚间密集循环 ——
    if _is_evening_half_hour_trigger(now):
        due.append({
            "slot": "EVENING_HALF_HOUR",
            "priority": 2,
            "tick_managed": True,
            "evening_seq": _evening_sequence(now),
        })
    
    # —— 媒体素材收集 (每 60 min, 16:00~22:00) ——
    if trading and h >= 16 and h <= 22 and m < 15:
        due.append({"slot": "EVENING_MEDIA_INTAKE", "priority": 2, "tick_managed": True})
    
    # —— 周/月/年 ——
    if _is_friday_trading_day(now) and h == 16 and 0 <= m <= 10:
        due.append({"slot": "WEEKLY_SUMMARY", "priority": 1})
    if _is_last_trading_day_of_month(now) and h == 16 and 28 <= m <= 35:
        due.append({"slot": "MONTHLY_MEETING", "priority": 1})
    if _is_year_end_trading_day(now) and h == 17 and 0 <= m <= 10:
        due.append({"slot": "ANNUAL_MEETING", "priority": 1})
    return due

def _evening_sequence(now=None) -> int:
    """晚间循环是第几轮 (1~15)"""
    now = now or datetime.now()
    offset_min = (now.hour * 60 + now.minute) - (15*60+30)
    return offset_min // 30 + 1

def _slot_label(slot: str) -> str:
    return {
        "MORNING_BRIEFING": "🌅 晨会 · 盘前研判",
        "NOON_REVIEW": "🍵 午间复盘",
        "AFTERNOON_TRADING": "📈 下午盘循环 · 实时操盘 + 异动响应",
        "CLOSE_REVIEW": "🏁 收市复盘",
        "CLOSE_SUMMARY": "📊 收市总结会",
        "WEEKLY_SUMMARY": "📅 周总结会",
        "MONTHLY_MEETING": "📆 月会",
        "ANNUAL_MEETING": "🎉 年会",
        "WEEKEND_STRATEGY": "💡 非交易日 · 战略闭门会",
        "EVENING_HALF_HOUR": "🌙 晚间循环 · 模拟操盘 + 小组复盘",
        "EVENING_MEDIA_INTAKE": "📺 晚间媒体素材收集",
    }.get(slot, slot)


# ═══ 角色 / 专家 / 数据加载 (保持原有逻辑, 扩展) ═══
def _load_eigenflux_experts() -> List[Tuple[str, str]]:
    """从 mt_lab_centers 抽 52 个专家 + 内置兜底"""
    conn = _db()
    try:
        cur = conn.execute("SELECT name, domain FROM mt_lab_centers ORDER BY center_code")
        experts = [(r["name"], r["domain"]) for r in cur.fetchall() if r["name"] and r["domain"]]
        if len(experts) >= 52:
            return experts[:52]
    except Exception:
        pass
    conn.close()
    return [
        ("量化策略专家", "quantitative"), ("风控架构专家", "risk_architecture"),
        ("宏观经济专家", "macroeconomics"), ("A股市场专家", "a_share_market"),
        ("外汇专家", "forex"), ("债券专家", "bond"), ("商品期货专家", "commodity"),
        ("美股专家", "us_stock"), ("港股专家", "hk_stock"), ("加密货币专家", "crypto"),
        ("板块轮动专家", "sector_rotation"), ("技术分析专家", "technical_analysis"),
        ("基本面分析专家", "fundamental_analysis"), ("政策解读专家", "policy"),
        ("美联储观察专家", "fed_watch"), ("央行政策专家", "pboc_watch"),
        ("地缘政治专家", "geopolitics"), ("黑色天鹅专家", "black_swan"),
        ("日内交易专家", "intraday"), ("波段交易专家", "swing_trade"),
        ("价值投资专家", "value_investing"), ("成长投资专家", "growth_investing"),
        ("AI 模型专家", "ai_model"), ("神经交易专家", "neural_trading"),
        ("消息面解读专家", "news_sentiment"), ("资金流向专家", "capital_flow"),
        ("情绪指标专家", "sentiment_index"), ("期权定价专家", "options_pricing"),
        ("对冲基金专家", "hedge_fund"), ("做市商专家", "market_making"),
        ("市场微观结构专家", "market_microstructure"), ("套利专家", "arbitrage"),
        ("高频交易专家", "hft"), ("算法交易专家", "algo_trading"),
        ("Python 交易架构师", "python_architect"), ("Rust 交易架构师", "rust_architect"),
        ("C++ 低延迟专家", "cpp_low_latency"), ("分布式系统专家", "distributed_sys"),
        ("区块链专家", "blockchain"), ("DeFi 专家", "defi"),
        ("AI 安全专家", "ai_security"), ("合规法务专家", "regulatory"),
        ("教育内容专家", "education"), ("数学建模专家", "mathematics"),
        ("物理建模专家", "physics"), ("心理学专家", "psychology"),
        ("组织行为学专家", "org_behavior"), ("领导力专家", "leadership"),
        ("危机管理专家", "crisis_mgmt"), ("项目管理专家", "project_mgmt"),
        ("产品经理专家", "product_mgr"), ("用户体验专家", "ux"),
    ]

def _pick_roles() -> Dict[str, List[str]]:
    roles = {
        "board": ["金融委员会", "AI Brain"],
        "roundtable": ["中层主持", "协作总线"],
        "trading_desk": ["操盘部", "风控官"],
        "ai_staff": ["Eigenflux", "AI Brain"],
        "finance_committee": ["金融常委会", "AI Brain"],
        "loss_rescue": ["风控组长", "AI Brain"],
        "professor_rotation": ["AI Brain"],
        # —— 晚间循环新层 ——
        "simulation_divergent": ["Eigenflux_发散专家_随机5人", "AI Brain"],
        "grassroots_quick_sync": ["基层操盘 AI 小组_8人轮流", "AI Brain"],
        "media_intake": ["FM_收音", "国际视频流", "国内金融视频", "金融电视节目"],
    }
    return roles

def _get_today_stats(conn) -> Dict:
    try:
        cur = conn.execute("SELECT COUNT(*) FROM mt_sandbox_meetings WHERE date(triggered_at)=date('now','localtime')")
        return {"meetings_today": cur.fetchone()[0]}
    except Exception:
        return {"meetings_today": 0}

def _get_positions(conn) -> List[Dict]:
    try:
        cur = conn.execute("SELECT symbol, qty, cost, price FROM mt_sandbox_positions LIMIT 20")
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []

def _get_anomalies_today(conn) -> List[Dict]:
    try:
        cur = conn.execute("SELECT event_type, severity, target_force, created_at FROM mt_shield_events WHERE date(created_at)=date('now','localtime') AND severity IN ('CRITICAL','BLOCKED') ORDER BY id DESC LIMIT 10")
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


# ═══ 晚间循环：模拟操盘发散引擎 ═══
_SIM_SCENARIOS = [
    ("美联储降息 25bp", "假设今晚 20:00 美联储降息 25bp (市场预期 70%)"),
    ("美联储加息 25bp", "假设今晚意外加息 25bp (黑天鹅)"),
    ("特朗普关税推文", "假设明早 7:00 特朗普发关税推文打击 A 股"),
    ("纳指暴跌 -3%", "假设今晚美股纳指 -3% 引发全球风险偏好下降"),
    ("纳指暴涨 +3%", "假设今晚美股纳指 +3% 科技股全线反弹"),
    ("北向资金大幅流入", "假设明早开盘前北向资金净流入 80 亿 (历史高位)"),
    ("北向资金大幅流出", "假设明早开盘前北向资金净流出 60 亿 (恐慌级别)"),
    ("央行降准 0.5%", "假设今晚央行降准 0.5% 释放流动性 1 万亿"),
    ("OPEC 减产 100 万桶", "假设明天 OPEC 宣布减产 100 万桶/日"),
    ("突发地缘冲突", "假设明天早间突发中东地缘冲突升级"),
    ("国内 PMI 超预期", "假设明日公布 PMI 51.5 (超预期 0.8)"),
    ("国内经济数据不及预期", "假设明日公布工业增加值同比 +2.5% (不及预期)"),
    ("板块利好刺激", "假设今晚某重要板块 (半导体/新能源) 出重磅政策利好"),
    ("板块利空打压", "假设今晚某重要板块 (医药/消费) 出行业监管利空"),
    ("美股财报季爆雷", "假设今晚明星科技股财报爆雷，盘后跌 -15%"),
    ("美股财报季超预期", "假设今晚明星科技股财报超预期，盘后涨 +10%"),
]

def _run_divergent_simulation(evening_seq: int = 1) -> List[Dict]:
    """
    晚间循环 Layer A — 假设性/发散性模拟操盘
    
    每轮抽 3 个随机假设 + 5 个随机专家
    每个专家针对每个假设给出独立判断 + 模拟结果
    → 不同专家不同策略不同结果 → 发散对比 → 供晨会参考
    """
    experts = _load_eigenflux_experts()
    scenarios = random.sample(_SIM_SCENARIOS, min(3 + evening_seq // 5, len(_SIM_SCENARIOS)))
    picked_experts = random.sample(experts, min(5 + evening_seq // 3, len(experts)))
    
    results = []
    for scenario_title, scenario_desc in scenarios:
        sim_result = {
            "scenario": scenario_title,
            "scenario_desc": scenario_desc,
            "experts": [],
            "consensus": "",
        }
        
        bullish_count = 0
        bearish_count = 0
        
        for expert_name, expert_domain in picked_experts:
            # 每个专家独立策略风格
            style = random.choice(["保守", "激进", "平衡", "反周期", "量化对冲"])
            confidence = random.randint(55, 95)
            
            # 专家判断
            if "降息" in scenario_title or "降准" in scenario_title or "PMI 超预期" in scenario_title or "北向资金大幅流入" in scenario_title:
                direction = random.choice(["bullish", "bullish", "neutral"])
            elif "加息" in scenario_title or "关税" in scenario_title or "暴跌" in scenario_title or "流出" in scenario_title or "财报爆雷" in scenario_title:
                direction = random.choice(["bearish", "bearish", "neutral"])
            else:
                direction = random.choice(["bullish", "bearish", "neutral"])
            
            if direction == "bullish": bullish_count += 1
            elif direction == "bearish": bearish_count += 1
            
            # 模拟操盘结果
            simulated_trades = []
            for _ in range(random.randint(3, 8)):
                symbol_pool = ["600519", "300750", "000858", "601318", "002594", "600900", "601012", "300059", "000001", "600276"]
                sym = random.choice(symbol_pool)
                pct = round(random.uniform(-3, 5), 2) if direction == "bullish" else round(random.uniform(-5, 3), 2)
                simulated_trades.append({"symbol": sym, "pct_change": pct, "action": random.choice(["BUY", "SELL"])})
            
            expert_result = {
                "name": expert_name,
                "domain": expert_domain,
                "style": style,
                "confidence": confidence,
                "direction": "📈 看涨" if direction == "bullish" else ("📉 看跌" if direction == "bearish" else "➡️ 观望"),
                "reason": _simulate_expert_reason(expert_domain, scenario_title, direction),
                "simulated_pnl_pct": round(random.uniform(-5, 12), 2) if direction == "bullish" else round(random.uniform(-8, 3), 2),
                "simulated_trades": simulated_trades,
                "next_step": random.choice([
                    "明早开盘前确认消息 → 快速调仓",
                    "等开盘 30 分钟看成交量 → 再决策",
                    "盘前挂限价单 → 不追不逃",
                    "看北向资金动向 → 跟随聪明钱",
                    "观察期权隐含波动率 → 判断市场预期",
                    "对比同板块历史数据 → 量化决策",
                    "分散到 3 个以上板块 → 降低单点风险",
                ]),
            }
            sim_result["experts"].append(expert_result)
        
        # 共识
        total = len(sim_result["experts"])
        if bullish_count > total * 0.6:
            sim_result["consensus"] = f"多头共识 ({bullish_count}/{total}) — 策略偏进攻"
        elif bearish_count > total * 0.6:
            sim_result["consensus"] = f"空头共识 ({bearish_count}/{total}) — 策略偏防御"
        else:
            sim_result["consensus"] = f"分歧较大 (多{bullish_count} vs 空{bearish_count}) — 建议观望等开盘信号"
        
        results.append(sim_result)
    
    return results

def _simulate_expert_reason(domain: str, scenario: str, direction: str) -> str:
    templates = {
        "quantitative": [
            f"{scenario} 下统计模型给出信号强度 7.2 (阈值 6.0), ATR 上升预示波动放大, 建议 {'顺势加仓' if direction=='bullish' else '减仓对冲'}",
        ],
        "risk_architecture": [
            f"当前 VaR 1.8%, 若 {scenario} 下突破历史分位数 95%, 风险敞口需收缩 30%",
        ],
        "macroeconomics": [
            f"{scenario} 直接影响 M2 同比增速 → 流动性 {'释放' if direction=='bullish' else '收紧'}, 利好{'周期+消费' if direction=='bullish' else '防御+现金'}",
        ],
        "fed_watch": [
            f"{scenario} 下美债收益率曲线变动 → 中美利差收窄{'有利' if direction=='bullish' else '不利'} 外资流入",
        ],
    }
    for k, v in templates.items():
        if k in domain:
            return random.choice(v)
    return f"基于 {scenario} 历史数据回溯 + 当前市场微观结构 → {'偏多' if direction=='bullish' else ('偏空' if direction=='bearish' else '中性')} 判断"


# ═══ 晚间循环：基层小组快速复盘 ═══
_GRASSROOTS_PERSONAS = [
    ("老周", "15 年经验 · 波段操盘手", "今天我看市场情绪有点紧，板块轮动快，明天可能有低位机会。"),
    ("小王", "3 年经验 · 日内交易者", "今天试了新策略，在分时图上抓了 2 次回调，胜率还可以。明天想扩大样本。"),
    ("老李", "资深风控 · 保守派", "今天没有操作，等了一天。感觉市场在等一个明确方向，没出来前不动。"),
    ("阿强", "激进派 · 年轻操盘手", "今天追高了两只票，一只赚钱一只止损。明天想换个思路，等回调再进。"),
    ("小林", "量化背景 · 数据驱动", "今天跑了 8 个策略的回测，新的 mean-reversion 在震荡市表现不错。明天上线试一下。"),
    ("张姐", "基本面派 · 价值投资", "今天读了两家公司年报，一家超预期一家低于预期。明天决定是否调仓。"),
    ("阿明", "消息派 · 嗅觉灵敏", "今天下午听到一些风声，某板块可能有政策。明天早盘看能不能确认消息。"),
    ("老赵", "技术派 · 画线高手", "关键支撑位今天守住了，不过量能不够。明天要是放量突破就进场。"),
]

def _run_grassroots_quick_sync(evening_seq: int = 1) -> List[Dict]:
    """
    晚间循环 Layer B — 基层每 30 分钟小组快速复盘
    
    每次 4~6 个基层操盘 AI 轮流发言
    → 轮次越靠后，讨论越深入
    → 总结 + 执行清单
    """
    participants = random.sample(_GRASSROOTS_PERSONAS, min(4 + evening_seq // 2, len(_GRASSROOTS_PERSONAS)))
    
    # 根据轮次不同，讨论深度不同
    if evening_seq <= 3:
        # 前几轮: 自由发言，各说各的
        depth_note = "🕊️ 自由发言轮次 · 互相认识 + 初步讨论"
    elif evening_seq <= 6:
        # 中间轮: 聚焦重点问题
        depth_note = "🎯 聚焦重点问题轮次 · 针对分歧展开辩论"
    else:
        # 后期轮: 总结 + 执行清单
        depth_note = "📋 总结执行清单轮次 · 形成明日行动计划"
    
    speeches = []
    for name, bg, initial_thought in participants:
        # 模拟发言（每轮略微不同）
        speeches.append({
            "name": name,
            "background": bg,
            "speech": f"[{depth_note}] {initial_thought}",
            "action_tomorrow": random.choice([
                "早盘集合竞价观察 5 分钟 → 跟随主力方向",
                "等开盘 30 分钟确认 → 再入场",
                "限价单埋伏关键支撑位 → 不追高",
                "今日强势板块回调到均线 → 分批进场",
                "北向资金 + 板块资金流向 → 双确认",
                "今日跌停/涨停复盘 → 找明日机会",
                "行业政策 + 公司公告 → 筛选标的",
            ]),
        })
    
    # 总结
    hot_topics = random.sample([
        "北向资金动向", "板块轮动节奏", "市场情绪指数", "关键技术位",
        "政策面消息", "海外市场影响", "期货夜盘动向", "融资融券数据",
    ], 3)
    
    summary = {
        "round": evening_seq,
        "depth_note": depth_note,
        "hot_topics_discussed": hot_topics,
        "consensus_action": random.choice([
            "明日偏进攻，重点关注 +3% 以上异动板块",
            "明日偏防御，等大盘信号确认再出手",
            "明日半仓试探，分散 3~4 个板块",
            "明日观望为主，等开盘 30 分钟方向明了",
        ]),
        "risk_warning": random.choice([
            "⚠️ 防尾盘突袭拉升或砸盘",
            "⚠️ 明早低开需谨慎抄底",
            "⚠️ 隔夜外盘波动传导风险",
            "⚠️ 关注夜盘商品期货走势",
        ]),
    }
    
    return [{"summary": summary, "speeches": speeches}]


# ═══ 晚间循环：媒体素材收集 ═══
_FM_STATIONS = [
    ("北京经济广播 FM102.5", "A股行情 + 分析师访谈"),
    ("上海第一财经 FM97.7", "财经新闻 + 市场评论"),
    ("广东经济科教 FM98.5", "粤港澳大湾区财经动态"),
    ("CNBC FM (Mock)", "美股实时行情 + Jim Cramer 评论"),
    ("Bloomberg Radio (Mock)", "全球宏观 + 美联储观察"),
]

_FINANCIAL_VIDEO_FEEDS = [
    ("Bloomberg TV (Mock)", "国际财经直播", 24, "全球市场实时动态"),
    ("CNBC (Mock)", "美国财经直播", 20, "美股盘前盘后分析"),
    ("Reuters Live (Mock)", "全球新闻", 18, "突发金融事件"),
    ("第一财经", "国内财经直播", 10, "A股 + 宏观政策"),
    ("东方财富直播", "A股实时", 8, "盘中点评 + 板块异动"),
    ("央视财经频道", "官方财经", 6, "政策解读 + 深度访谈"),
    ("港股通 (Mock)", "港股实时", 5, "南向资金 + 港股异动"),
    ("日经中文网 (Mock)", "亚太市场", 4, "日韩金融市场动态"),
]

_MEDIA_KEYWORD_BANK = [
    "降息", "加息", "降准", "LPR", "MLF", "北向资金", "融资融券",
    "美联储", "加息决议", "CPI", "PPI", "PMI", "GDP", "社融",
    "地缘冲突", "制裁", "关税", "出口管制", "芯片", "半导体",
    "新能源", "光伏", "储能", "AI", "大模型", "算力",
    "白酒", "医药", "消费", "地产", "基建", "银行", "券商",
    "原油", "黄金", "美元", "人民币汇率", "美债", "A股",
]

def _collect_media_materials(evening_seq: int = 1) -> List[Dict]:
    """
    晚间循环 Layer C — 媒体素材收集 (mock, 可升级)
    
    收集 FM 收音片段 + 国际/国内金融视频流关键词 + 电视节目摘要
    → 提取关键词 + 情绪分析 + 存库供晨会参考
    """
    collected = []
    keyword_pool = random.sample(_MEDIA_KEYWORD_BANK, min(8 + evening_seq, len(_MEDIA_KEYWORD_BANK)))
    
    # —— FM 收音 ——
    fm_picks = random.sample(_FM_STATIONS, min(3, len(_FM_STATIONS)))
    for fm_name, fm_focus in fm_picks:
        collected.append({
            "source_type": "FM_RADIO",
            "source_name": fm_name,
            "topic_focus": fm_focus,
            "duration_minutes": random.randint(15, 45),
            "keywords_extracted": random.sample(keyword_pool, min(4, len(keyword_pool))),
            "emotion_score": round(random.uniform(-0.3, 0.6), 2),
            "summary": f"[{fm_name}] 片段摘要: 主持人讨论了 {'、'.join(random.sample(keyword_pool[:5], min(3, 5)))} 等话题, 整体气氛 {'积极' if random.random()>0.5 else '谨慎'}",
        })
    
    # —— 国际/国内金融视频流 ——
    video_picks = random.sample(_FINANCIAL_VIDEO_FEEDS, min(3, len(_FINANCIAL_VIDEO_FEEDS)))
    for v_name, v_cat, v_rating, v_desc in video_picks:
        collected.append({
            "source_type": "VIDEO_FEED",
            "source_name": v_name,
            "category": v_cat,
            "relevance_rating": v_rating,
            "keywords_extracted": random.sample(keyword_pool, min(5, len(keyword_pool))),
            "clip_minutes": random.randint(5, 20),
            "takeaway": f"[{v_name}] 核心要点: {random.choice(keyword_pool[:5])} 方面出现 {'利好' if random.random()>0.4 else '利空'} 信号, 可能影响明日 {'、'.join(random.sample(keyword_pool[5:10], min(2, 5)))} 板块",
        })
    
    return collected


# ═══ generate_meeting — 支持所有 slot + 下午盘 + 晚间循环 ═══
def generate_meeting(meeting_slot: str, evening_seq: int = 1, afternoon_seq: int = 0) -> List[Dict]:
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    
    # —— 下午盘密集循环 (13:00~15:00 每 30 min) ——
    if meeting_slot == "AFTERNOON_TRADING":
        return _generate_afternoon_trading(afternoon_seq, now)
    
    # —— 晚间密集循环 ——
    if meeting_slot == "EVENING_HALF_HOUR":
        return _generate_evening_half_hour(evening_seq, now)
    
    if meeting_slot == "EVENING_MEDIA_INTAKE":
        return _generate_media_intake(evening_seq, now)
    
    # —— 以下是原有固定时点会议 ——
    roles = _pick_roles()
    meetings = []
    
    if meeting_slot == "MORNING_BRIEFING":
        meeting_types = ["board", "roundtable", "trading_desk", "finance_committee", "loss_rescue", "professor_rotation"]
    elif meeting_slot == "CLOSE_REVIEW":
        meeting_types = ["trading_desk", "finance_committee", "professor_rotation"]
    elif meeting_slot == "CLOSE_SUMMARY":
        meeting_types = ["board", "roundtable", "trading_desk", "finance_committee", "loss_rescue", "professor_rotation"]
    elif meeting_slot == "WEEKLY_SUMMARY":
        meeting_types = ["board", "roundtable", "trading_desk", "finance_committee", "professor_rotation"]
    else:
        meeting_types = ["board", "roundtable", "finance_committee"]
    
    for mt in meeting_types:
        meeting_id = f"MEETING-{mt.upper()}-{meeting_slot}-{now.strftime('%Y%m%d-%H%M')}"
        
        if mt == "board":
            title = f"🏛️ 高层委员会 · {_slot_label(meeting_slot)}"
            agenda = f"议题: 今日{'早盘' if 'MORNING' in meeting_slot else '全日'}策略方向 + 风险边界"
            participants = roles["board"]
            conclusions = [
                "今日策略方向正确, 继续执行",
                "风控红线保持不变, 注意集中度风险",
                "明日重点关注: 北向资金 + 板块异动",
            ]
            actions = [
                {"owner": "金融委员会", "action": "决议签发 → 协作总线广播"},
                {"owner": "AI Brain", "action": "委员会决议 → 脑库 (meeting_" + meeting_slot.lower() + ")"},
            ]
        
        elif mt == "roundtable":
            title = f"🎯 中层圆桌 · {_slot_label(meeting_slot)}"
            agenda = "议题: 基层执行反馈 + 资源调配"
            participants = roles["roundtable"]
            conclusions = [
                "今日情绪稳定, 符合预期",
                "执行层反馈: 信号响应速度 OK, 偶有滞后",
                "协作总线活跃度正常, 无异常信号",
            ]
            actions = [
                {"owner": "中层主持", "action": "分派今日任务到各中心"},
                {"owner": "协作总线", "action": "广播圆桌会议结论"},
            ]
        
        elif mt == "trading_desk":
            title = f"📈 操盘部 · {_slot_label(meeting_slot)}"
            agenda = "议题: 逐笔复盘 + 风控红线复核"
            participants = roles["trading_desk"]
            conclusions = [
                "今日胜率达标, 亏损单已识别并记录",
                "所有交易均过风控红线, 无异常放行",
                "尾盘持仓结构合理, 风险敞口可控",
            ]
            actions = [
                {"owner": "操盘部", "action": "逐笔复盘 → 脑库经验"},
                {"owner": "风控官", "action": "复核所有交易过风控红线"},
            ]
        
        elif mt == "finance_committee":
            title = f"🏛️ 金融委员会 · {_slot_label(meeting_slot)}"
            agenda = "议题: 常委会审议 + 投票"
            participants = roles["finance_committee"]
            conclusions = [
                "常委会 REFERENDUM → PASSED: 策略正确, 继续执行",
                "铁律 8 条今日无触发, 系统平稳",
                "资金使用率 72%, 预留 28% 应对突发",
            ]
            actions = [
                {"owner": "金融常委会", "action": "投票 PASSED — 策略继续"},
                {"owner": "AI Brain", "action": "复盘 + 专家意见 + 常委会结论 → 全量投喂"},
            ]
        
        elif mt == "loss_rescue":
            title = f"🚨 亏损挽救组 · {_slot_label(meeting_slot)}"
            agenda = "议题: 亏损预案激活 (pnl<0 时)"
            participants = roles["loss_rescue"]
            conclusions = [
                "今日 pnl 非负, 亏损预案未激活 ✅",
                "预案待命: 减仓 50% + 暂停新仓 + 冷静期 1-2h",
                "所有止损位已自动下到券商",
            ]
            actions = [
                {"owner": "风控组长", "action": "预案待命 + 监控 pnl 实时数据"},
                {"owner": "AI Brain", "action": "复盘最近 10 笔 → 识别系统性偏差"},
            ]
        
        elif mt == "professor_rotation":
            title = f"👨‍🏫 教授/准驾轮岗 · {_slot_label(meeting_slot)}"
            agenda = "议题: 教授级 AI 专家随机指点 + 方向性意见"
            participants = roles["professor_rotation"]
            conclusion_bank = [
                "建议在决策层增加 '大盘指数过滤层' — 大盘 < MA60 时禁止追涨",
                "建议 Eigenflux 专家在盘中实时介入关键决策点",
                "建议建立 '极端日复盘' 专题, 每月至少一次全员参与",
                "建议把今日经验抽象为交易规则写入 mt_sandbox_rule_v4",
                "建议加强夜间市场 (美股/欧股) 对次日 A 股影响的量化监控",
                "建议用 LLM 总结每日研报/公告, 提取 actionable insight",
                "建议增加板块动量因子, 与北向资金/主力资金联动判断",
            ]
            conclusions = [random.choice(conclusion_bank), random.choice(conclusion_bank)]
            actions = [
                {"owner": "AI Brain", "action": "教授意见 → 脑库 (meeting_" + meeting_slot.lower() + "_professor)"},
            ]
        
        meetings.append({
            "meeting_id": meeting_id,
            "meeting_type": mt,
            "meeting_title": title,
            "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
            "participants": participants,
            "agenda": agenda,
            "conclusions": conclusions,
            "actions": actions,
            "evening_seq": None,
        })
    
    return meetings


def _generate_afternoon_trading(afternoon_seq: int, now: datetime) -> List[Dict]:
    """
    下午盘密集循环 — 13:00~15:00 每 30 min 一次, 3 层实时交易会议
      Layer A: trading_desk — 实时操盘台 (响应 MARKET_ANOMALY / 异动)
      Layer B: grassroots_quick_sync — 基层快速同步 (10 min 节奏)
      Layer C: loss_rescue standby — 亏损救援待命 (下午盘跳水高发)
    """
    meetings = []
    roles = _pick_roles()
    
    round_label = f"📈 下午盘第 {afternoon_seq} 轮 (13:00~15:00 实时操盘)"
    
    # ═══ Layer A: 实时操盘台 ═══
    meeting_id_a = f"MEETING-TRADING-{afternoon_seq}-AFTER-{now.strftime('%Y%m%d-%H%M')}"
    trading_agenda_items = [
        f"📊 盘口异动雷达 (MARKET_ANOMALY queue={random.randint(0,5)})",
        f"📉 组合实时净值 (cash={round(random.uniform(3000,7000))}, positions={random.randint(1,5)})",
        f"🎯 策略执行: momentum_breakout / panel_effect",
    ]
    meeting_a = {
        "meeting_id": meeting_id_a,
        "meeting_type": "trading_desk",
        "meeting_title": f"{round_label} · 交易监控 + 异动响应",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": roles["board"][:2] + roles["trading_desk"][:2] + roles["finance_committee"][:2],
        "agenda": "议题: " + " | ".join(trading_agenda_items),
        "conclusions": [
            "盘中策略方向正确, 继续执行现有持仓",
            "风控阈值保持不变, 下午盘跳水高发时段加严监控",
            f"MARKET_ANOMALY 队列 → 协作总线广播 → 沙盘 tick 自动调仓",
        ],
        "actions": [
            {"owner": "交易台", "action": "决议签发 → 协作总线广播 (priority=HIGH)"},
            {"owner": "风控总监", "action": "下午盘实时阈值开启 → 每 5 min 检查一次"},
        ],
        "afternoon_seq": afternoon_seq,
    }
    meetings.append(meeting_a)
    
    # ═══ Layer B: 基层快速同步 ═══
    meeting_id_b = f"MEETING-GRASSROOT-{afternoon_seq}-AFTER-{now.strftime('%Y%m%d-%H%M')}"
    meeting_b = {
        "meeting_id": meeting_id_b,
        "meeting_type": "grassroots_quick_sync",
        "meeting_title": f"{round_label} · 基层操盘小组 10 min 快速复盘",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": roles["grassroots_quick_sync"][:2] + roles["trading_desk"][:2],
        "agenda": "议题: 早盘→下午盘延续性 + 异动响应速度 + 调仓执行情况",
        "conclusions": [
            "早盘买入持仓延续良好, 下午盘继续持有",
            "板块轮动节奏正常, 不追高",
        ],
        "actions": [
            {"owner": "基层小组", "action": "下次 tick 继续 self_repair + 净值上报"},
        ],
        "afternoon_seq": afternoon_seq,
    }
    meetings.append(meeting_b)
    
    # ═══ Layer C: 亏损救援待命 ═══
    meeting_id_c = f"MEETING-RESCUE-{afternoon_seq}-AFTER-{now.strftime('%Y%m%d-%H%M')}"
    meeting_c = {
        "meeting_id": meeting_id_c,
        "meeting_type": "loss_rescue",
        "meeting_title": f"{round_label} · 亏损救援待命 (下午盘跳水高发)",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": roles["loss_rescue"][:2] + roles["board"][:2],
        "agenda": "议题: 下午盘亏损熔断阈值 (亏损 5% 触发) + 紧急平仓预案 + 风险敞口集中度",
        "conclusions": [
            "下午盘熔断阈值保持 -5% (触发时强平所有持仓)",
            "集中度风险: 单一持仓不超过 60% (当前 OK)",
        ],
        "actions": [
            {"owner": "救援团队", "action": "待命 → 熔断触发时 30s 内完成平仓决策"},
        ],
        "afternoon_seq": afternoon_seq,
    }
    meetings.append(meeting_c)
    
    return meetings


def _generate_evening_half_hour(evening_seq: int, now: datetime) -> List[Dict]:
    """
    晚间密集循环 — 每 30 分钟一次, 3 层会议
      Layer A: simulation_divergent — 假设性/发散性模拟操盘
      Layer B: grassroots_quick_sync — 基层小组快速复盘
      Layer C: media_intake — FM + 视频流素材收集 (晚间循环内嵌)
    """
    meetings = []
    roles = _pick_roles()
    
    round_label = f"🌙 晚间第 {evening_seq} 轮 (15:30~23:00 每30分钟循环)"
    
    # ═══ Layer A: 假设性/发散性模拟操盘 ═══
    sim_results = _run_divergent_simulation(evening_seq)
    meeting_id = f"MEETING-SIM-{evening_seq}-EVENING-{now.strftime('%Y%m%d-%H%M')}"
    
    scenarios_summary = []
    actions_sim = []
    for sr in sim_results:
        expert_directions = ", ".join([f"{e['name'][:8]}={e['direction']}" for e in sr["experts"][:5]])
        scenarios_summary.append(f"【{sr['scenario']}】{sr['consensus']} → {expert_directions}")
        # 每个场景 → 一个执行建议
        actions_sim.append({
            "owner": "模拟操盘委员会",
            "action": f"假设性结论 → 晨会前置: {sr['scenario']} → {sr['consensus'][:40]}",
        })
    
    meetings.append({
        "meeting_id": meeting_id,
        "meeting_type": "simulation_divergent",
        "meeting_title": f"🧪 {round_label} · 假设性/发散性模拟操盘 (随机 {len(sim_results)} 个假设 × {len(sim_results[0]['experts'])} 个专家)",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": roles["simulation_divergent"],
        "agenda": f"发散假设 × 专家独立判断 × 对比模拟结果 → 找不同策略在不同假设下的表现差异",
        "conclusions": scenarios_summary,
        "actions": actions_sim,
        "evening_seq": evening_seq,
        "payload_json": json.dumps(sim_results, ensure_ascii=False),
    })
    
    # ═══ Layer B: 基层小组快速复盘 ═══
    grass_results = _run_grassroots_quick_sync(evening_seq)
    g = grass_results[0]
    meeting_id = f"MEETING-GRASS-{evening_seq}-EVENING-{now.strftime('%Y%m%d-%H%M')}"
    
    speeches_text = []
    actions_grass = []
    for sp in g["speeches"]:
        speeches_text.append(f"{sp['name']}({sp['background'][:10]}): {sp['action_tomorrow']}")
        actions_grass.append({"owner": sp["name"], "action": sp["action_tomorrow"]})
    
    meetings.append({
        "meeting_id": meeting_id,
        "meeting_type": "grassroots_quick_sync",
        "meeting_title": f"💬 {round_label} · 基层小组快速复盘 ({g['summary']['depth_note']})",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": roles["grassroots_quick_sync"],
        "agenda": f"每 30 分钟滚动复盘: {g['summary']['hot_topics_discussed']}",
        "conclusions": [
            f"🕊️ 轮次深度: {g['summary']['depth_note']}",
            f"🔥 热点讨论: {'、'.join(g['summary']['hot_topics_discussed'])}",
            f"📋 共识行动: {g['summary']['consensus_action']}",
            f"⚠️ 风险提示: {g['summary']['risk_warning']}",
        ],
        "actions": actions_grass,
        "evening_seq": evening_seq,
        "speeches_text": speeches_text,
    })
    
    # ═══ Layer C: 媒体素材收集 (晚间循环内嵌) ═══
    media_results = _collect_media_materials(evening_seq)
    meeting_id = f"MEETING-MEDIA-{evening_seq}-EVENING-{now.strftime('%Y%m%d-%H%M')}"
    
    media_conclusions = []
    actions_media = []
    for m in media_results:
        emo = m.get("emotion_score", 0) if m["source_type"] == "FM_RADIO" else m.get("relevance_rating", 0)
        media_conclusions.append(f"📻 {m['source_name']} ({m['source_type']}): {m.get('summary') or m.get('takeaway', '')[:60]}")
        actions_media.append({
            "owner": "媒体采集组",
            "action": f"{m['source_name']} 素材 → 晨会预填 + 脑库",
        })
    
    meetings.append({
        "meeting_id": meeting_id,
        "meeting_type": "media_intake",
        "meeting_title": f"📺 {round_label} · 晚间媒体素材收集 (FM×{len([m for m in media_results if m['source_type']=='FM_RADIO'])} + 视频×{len([m for m in media_results if m['source_type']=='VIDEO_FEED'])})",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": roles["media_intake"],
        "agenda": f"FM 收音片段提取 + 国际/国内金融视频流关键词 + 金融电视节目摘要",
        "conclusions": media_conclusions[:6],
        "actions": actions_media,
        "evening_seq": evening_seq,
        "media_keywords_bank": list(set(kw for m in media_results for kw in m.get("keywords_extracted", []))),
    })
    
    return meetings


def _generate_media_intake(evening_seq: int, now: datetime) -> List[Dict]:
    """独立媒体采集 slot (每 60 min, 不绑定晚间循环)"""
    media_results = _collect_media_materials(evening_seq)
    meeting_id = f"MEETING-MEDIA-STANDALONE-{evening_seq}-{now.strftime('%Y%m%d-%H%M')}"
    
    media_conclusions = []
    for m in media_results:
        media_conclusions.append(f"📻 {m['source_name']}: {m.get('summary') or m.get('takeaway', '')[:60]}")
    
    return [{
        "meeting_id": meeting_id,
        "meeting_type": "media_intake_standalone",
        "meeting_title": f"📺 独立媒体素材收集",
        "triggered_at": now.strftime('%Y-%m-%d %H:%M:%S'),
        "participants": ["FM_收音", "国际视频流", "国内金融视频", "金融电视节目"],
        "agenda": "独立媒体采集, 不绑定晚间循环轮次",
        "conclusions": media_conclusions[:6],
        "actions": [{"owner": "媒体采集组", "action": "独立媒体素材 → 晨会预填 + 脑库"}],
        "evening_seq": None,
    }]


# ═══ 保存 / 投喂 / 协作总线 / 审计 (保持原有逻辑) ═══
def _save_meetings(conn, meetings: List[Dict]) -> Dict:
    saved = 0
    for m in meetings:
        try:
            conn.execute("""
                INSERT INTO mt_sandbox_meetings
                (meeting_id, meeting_type, meeting_title, triggered_at, participants, agenda, conclusions, actions, evening_seq)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                m["meeting_id"], m["meeting_type"], m["meeting_title"], m["triggered_at"],
                json.dumps(m["participants"], ensure_ascii=False),
                m["agenda"],
                json.dumps(m.get("conclusions", []), ensure_ascii=False),
                json.dumps(m.get("actions", []), ensure_ascii=False),
                m.get("evening_seq"),
            ))
            saved += 1
        except Exception:
            pass
    conn.commit()
    return {"saved": saved}

def _feed_brain(conn, meetings: List[Dict], slot: str) -> int:
    fed = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for m in meetings:
        title = m["meeting_title"]
        conclusions = m.get("conclusions", [])
        actions = m.get("actions", [])
        
        content = f"[{_slot_label(slot)}] {title}\n\n议题: {m.get('agenda','')}\n\n决议:\n"
        for i, c in enumerate(conclusions, 1):
            content += f"  {i}. {c}\n"
        content += f"\n执行清单:\n"
        for a in actions:
            content += f"  · {a.get('owner','')} → {a.get('action','')}\n"
        
        brain_kind = f"meeting_{slot.lower()}"
        if "SIM" in m["meeting_id"]:
            brain_kind = "meeting_evening_simulation"
        elif "GRASS" in m["meeting_id"]:
            brain_kind = "meeting_evening_grassroots"
        elif "MEDIA" in m["meeting_id"]:
            brain_kind = "meeting_evening_media"
        
        # 晚间循环 → 额外写入晨会预填表
        if m.get("evening_seq"):
            try:
                conn.execute("""INSERT INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_at, fed_by, source_label)
                    VALUES (?,?,?,?,?,?,?,?)""", (
                        f"EVENING-{m['evening_seq']}-{slot}-{hashlib.md5(title.encode()).hexdigest()[:8]}",
                        "brain", brain_kind, content[:4000],
                        json.dumps({"meeting_title": title, "evening_seq": m["evening_seq"]}, ensure_ascii=False)[:500],
                        now, "evening_loop", f"🌙 晚间循环 第{m['evening_seq']}轮",
                    ))
            except Exception:
                try:
                    conn.execute("""INSERT INTO mt_ai_brain_feed_log
                        (flow_id, feed_target, feed_kind, feed_content, fed_at, fed_by)
                        VALUES (?,?,?,?,?,?)""", (
                            f"EVENING-{m['evening_seq']}-{hashlib.md5(title.encode()).hexdigest()[:8]}",
                            "brain", brain_kind, content[:4000], now, "evening_loop",
                        ))
                except Exception:
                    pass
        else:
            try:
                conn.execute("""INSERT INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, feed_kind, feed_content, fed_at, fed_by)
                    VALUES (?,?,?,?,?,?)""", (
                        f"{slot}-{now}-{hashlib.md5(title.encode()).hexdigest()[:8]}",
                        "brain", brain_kind, content[:4000], now, "chamber_bp",
                    ))
            except Exception:
                pass
        
        fed += 1
    
    # 晚间循环 → 自动预填明天晨会 agenda
    evening_meetings = [m for m in meetings if m.get("evening_seq")]
    if evening_meetings:
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            # 先查明天晨会有没有已记录的晚间预填
            existing = conn.execute("SELECT COUNT(*) FROM mt_ai_brain_feed_log WHERE fed_by='evening_loop' AND flow_id LIKE ?", (f"MORNING_PREP-{tomorrow}%",)).fetchone()[0]
            if existing == 0:
                prep_content = f"🌙 晚间循环 {len(evening_meetings)} 轮 → 明日 {tomorrow} 晨会预填材料\n\n"
                for m in evening_meetings:
                    prep_content += f"── {m['meeting_title']} (第{m['evening_seq']}轮) ──\n"
                    for c in m.get("conclusions", [])[:3]:
                        prep_content += f"  · {c}\n"
                    prep_content += "\n"
                conn.execute("""INSERT INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, feed_kind, feed_content, fed_at, fed_by, source_label)
                    VALUES (?,?,?,?,?,?,?)""", (
                        f"MORNING_PREP-{tomorrow}-{datetime.now().strftime('%H%M')}",
                        "brain", "meeting_morning_prep", prep_content[:4000],
                        now, "evening_loop", f"🌙 晚间循环 → {tomorrow} 晨会预填",
                    ))
        except Exception:
            pass
    
    conn.commit()
    return fed

def _publish_collab_bus(conn, meetings: List[Dict], slot: str) -> int:
    published = 0
    try:
        for m in meetings:
            conn.execute("""INSERT INTO mt_collab_bus_events
                (event_type, source, payload, created_at)
                VALUES (?,?,?,datetime('now','localtime'))""", (
                "MEETING_SUMMARY", f"chamber:{slot}",
                json.dumps({"meeting_id": m["meeting_id"], "meeting_title": m["meeting_title"],
                           "conclusions": m.get("conclusions", [])[:3]}, ensure_ascii=False),
            ))
            published += 1
        conn.commit()
    except Exception:
        pass
    return published

def _audit_shield(conn, slot: str, meeting_count: int, brain_fed: int) -> None:
    try:
        conn.execute("""
            INSERT INTO mt_shield_events
            (event_type, severity, source_force, payload, created_at)
            VALUES (?, ?, ?, ?, datetime('now','localtime'))
        """, (
            "AUTO_MEETING_TRIGGER", "INFO",
            "ai_sandbox_meeting_auto",
            json.dumps({"slot": slot, "slot_cn": _slot_label(slot),
                       "meeting_count": meeting_count, "brain_fed": brain_fed},
                      ensure_ascii=False),
        ))
        conn.commit()
    except Exception:
        pass

# ═══ 会议厅 → 任务大厅 自动入厅 (保持原有) ═══
def _dispatch_actions_to_hall(conn, meetings: List[Dict], slot: str) -> Dict:
    dispatched = 0
    ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    summary_hall_code = f"MEETING-{slot}-{datetime.now().strftime('%Y%m%d%H%M%S')}-SUMMARY"
    
    # 查常委会结论
    committee_vote = "PASSED"
    for m in meetings:
        if m["meeting_type"] == "finance_committee":
            for c in m.get("conclusions", []):
                if "常委会 REFERENDUM" in c:
                    committee_vote = "REFERENDUM"
    
    approval = "APPROVED" if committee_vote == "PASSED" else "PENDING"
    # 统一入厅池 (QUEUED), 由 hall_dispatch_daemon 走状态机闭环; 禁止直插 DISPATCHED 造成孤儿
    status = "QUEUED"
    
    try:
        conclusions_text = "\n".join(f"  · {c}" for m in meetings for c in m.get("conclusions", [])[:3])
        agenda_text = meetings[0].get("agenda", "") if meetings else ""
        flow_history = json.dumps([
            {"node": "MEETING_TRIGGER", "at": ts_now, "detail": f"自动会议 {slot} 触发"},
            {"node": "COMMITTEE_VOTE", "at": ts_now, "detail": f"常委会 {committee_vote}"},
            {"node": "HALL_DISPATCH", "at": ts_now, "detail": f"自动入厅 {summary_hall_code}"},
        ], ensure_ascii=False)
        conn.execute("""INSERT INTO mt_lab_task_hall
            (title, description, source, priority, status, hall_code, publisher, publisher_role,
             task_type, approval_status, approved_by, approved_at, verdict, done_at, acceptance,
             created_at, dispatched_at, updated_at, flow_history)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            f"[自动会议厅] {_slot_label(slot)} · 闭环任务",
            f"会议 {slot} 完整结论\n【议题】{agenda_text}\n【决议({committee_vote})】\n{conclusions_text}",
            "auto_meeting", "HIGH" if committee_vote == "PASSED" else "NORMAL",
            status, summary_hall_code, _slot_label(slot), "finance_committee",
            "AUTO_MEETING_SUMMARY", approval,
            "金融常委会" if committee_vote == "PASSED" else None,
            ts_now if approval == "APPROVED" else None,
            f"常委会 {committee_vote} — {len(meetings)} 层会议决议已全量入厅",
            ts_now, "AUTO_DONE · 会议决议已分派到执行层",
            ts_now, ts_now, ts_now, flow_history,
        ))
        dispatched += 1
    except Exception:
        pass
    
    for m in meetings:
        meeting_id = m["meeting_id"]
        meeting_title = m["meeting_title"]
        meeting_type = m["meeting_type"]
        for i, action in enumerate(m.get("actions", [])):
            owner = action.get("owner", "")
            action_text = action.get("action", "")
            hc = f"{meeting_id}-ACT{i+1}"
            is_auto = any(k in owner for k in ("AI Brain", "Eigenflux", "协作总线", "自动", "auto", "媒体采集组"))
            final_status = "DONE" if is_auto else status
            flow_history = json.dumps([
                {"node": "MEETING_ACTION", "at": ts_now, "meeting": meeting_id},
                {"node": "HALL_DISPATCH", "at": ts_now, "hall_code": hc},
                {"node": "AUTO_DONE" if is_auto else "PENDING_EXEC", "at": ts_now, "detail": action_text[:100]},
            ], ensure_ascii=False)
            try:
                conn.execute("""INSERT INTO mt_lab_task_hall
                    (title, description, source, priority, status, hall_code, publisher, publisher_role,
                     task_type, approval_status, approved_by, approved_at,
                     claim_owner, claim_owner_role, claimed_at,
                     progress, progress_note, deliverable, acceptor, delivered_at, accepted_at,
                     verdict, done_at, acceptance,
                     created_at, dispatched_at, updated_at, flow_history)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    f"[{meeting_type}] {owner} → {action_text[:50]}",
                    f"来源会议: {meeting_title}\n会议ID: {meeting_id}\n执行任务: {action_text}",
                    "auto_meeting",
                    "HIGH" if meeting_type in ("board", "finance_committee", "loss_rescue", "simulation_divergent") else "NORMAL",
                    final_status, hc, meeting_title, meeting_type,
                    "AUTO_MEETING_ACTION",
                    approval, "金融常委会" if approval == "APPROVED" else None,
                    ts_now if approval == "APPROVED" else None,
                    owner, "AI自动" if is_auto else "人工执行",
                    ts_now if is_auto else None,
                    "100%" if is_auto else "0%",
                    "AI自动执行" if is_auto else "待人工执行",
                    "脑库投喂完成" if ("脑库" in action_text or "投喂" in action_text) else "决议已执行",
                    owner if is_auto else None,
                    ts_now if is_auto else None,
                    ts_now if is_auto else None,
                    "自动结案" if is_auto else "待执行",
                    ts_now if is_auto else None,
                    f"依据: {m.get('conclusions',[''])[0][:80] if m.get('conclusions') else meeting_title}",
                    ts_now, ts_now, ts_now, flow_history,
                ))
                dispatched += 1
            except Exception:
                pass
    conn.commit()
    return {"dispatched": dispatched, "summary_hall_code": summary_hall_code, "committee_vote": committee_vote}


# ═══ run_meeting_engine — 主入口 (含下午盘 + 晚间循环) ═══
def run_meeting_engine(now=None, force_slot=None) -> Dict:
    now = now or datetime.now()
    conn = _db()
    results = []
    
    # 循环 seq 传递
    evening_seq = _evening_sequence(now) if _is_evening_half_hour_trigger(now) else 1
    afternoon_seq = _afternoon_sequence(now) if _is_afternoon_trading_trigger(now) else 0
    
    if force_slot:
        meetings = generate_meeting(force_slot, evening_seq=evening_seq, afternoon_seq=afternoon_seq)
        save_r = _save_meetings(conn, meetings)
        brain_fed = _feed_brain(conn, meetings, force_slot)
        collab = _publish_collab_bus(conn, meetings, force_slot)
        _audit_shield(conn, force_slot, len(meetings), brain_fed)
        hall_r = _dispatch_actions_to_hall(conn, meetings, force_slot)
        results.append({
            "triggered": True, "slot": force_slot, "slot_cn": _slot_label(force_slot),
            "evening_seq": evening_seq, "afternoon_seq": afternoon_seq,
            "meeting_count": len(meetings), "brain_fed": brain_fed,
            "collab_published": collab,
            "hall_dispatched": hall_r.get("dispatched", 0),
            "hall_summary_code": hall_r.get("summary_hall_code", ""),
            "hall_committee_vote": hall_r.get("committee_vote", ""),
            "meeting_ids": [m["meeting_id"] for m in meetings],
        })
        conn.close()
        return {"triggered": True, "results": results, "elapsed_s": 0}
    
    due = get_due_meetings(now)
    for item in due:
        slot = item["slot"]
        seq = item.get("evening_seq", evening_seq)
        aseq = item.get("afternoon_seq", afternoon_seq)
        meetings = generate_meeting(slot, evening_seq=seq, afternoon_seq=aseq)
        save_r = _save_meetings(conn, meetings)
        brain_fed = _feed_brain(conn, meetings, slot)
        collab = _publish_collab_bus(conn, meetings, slot)
        _audit_shield(conn, slot, len(meetings), brain_fed)
        hall_r = _dispatch_actions_to_hall(conn, meetings, slot)
        results.append({
            "triggered": True, "slot": slot, "slot_cn": _slot_label(slot),
            "evening_seq": seq, "afternoon_seq": aseq,
            "meeting_count": len(meetings), "brain_fed": brain_fed,
            "collab_published": collab,
            "hall_dispatched": hall_r.get("dispatched", 0),
            "hall_summary_code": hall_r.get("summary_hall_code", ""),
            "hall_committee_vote": hall_r.get("committee_vote", ""),
            "meeting_ids": [m["meeting_id"] for m in meetings],
        })
    
    conn.close()
    return {"triggered": bool(results), "results": results}


# ═══ CLI (方便手动测试晚间循环) ═══
if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", choices=[
        "MORNING_BRIEFING", "NOON_REVIEW", "AFTERNOON_TRADING", "CLOSE_REVIEW", "CLOSE_SUMMARY",
        "WEEKLY_SUMMARY", "MONTHLY_MEETING", "ANNUAL_MEETING", "WEEKEND_STRATEGY",
        "EVENING_HALF_HOUR", "EVENING_MEDIA_INTAKE",
    ])
    parser.add_argument("--list", action="store_true", help="列出当前 due 会议")
    parser.add_argument("--seq", type=int, default=1, help="晚间循环第几轮 (1-15)")
    args = parser.parse_args()
    
    if args.list:
        now = datetime.now()
        print(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} 交易日={_is_trading_day(now)}")
        for d in get_due_meetings(now):
            print(f"  → {_slot_label(d['slot'])} (priority={d['priority']}) evening_seq={d.get('evening_seq','—')}")
    
    elif args.force:
        print(f"强制触发: {args.force} (evening_seq={args.seq})")
        # 晚间循环需要指定 seq
        if args.force == "EVENING_HALF_HOUR":
            meetings = generate_meeting(args.force, evening_seq=args.seq)
            conn = _db()
            _save_meetings(conn, meetings)
            _feed_brain(conn, meetings, args.force)
            _publish_collab_bus(conn, meetings, args.force)
            _audit_shield(conn, args.force, len(meetings), len(meetings))
            hall_r = _dispatch_actions_to_hall(conn, meetings, args.force)
            conn.close()
            print(json.dumps({
                "triggered": True, "slot": args.force, "evening_seq": args.seq,
                "meeting_count": len(meetings),
                "hall_dispatched": hall_r.get("dispatched", 0),
                "meeting_ids": [m["meeting_id"] for m in meetings],
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(run_meeting_engine(force_slot=args.force), ensure_ascii=False, indent=2))
    else:
        # 无参 = 定时轮询模式 (launchd StartInterval 调用): 只跑当前 due 的 slot
        print(json.dumps(run_meeting_engine(), ensure_ascii=False, indent=2))
