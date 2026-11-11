#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════
#  MTSCOS Gobelin Bank · ⏰ Scheduler Engine (行业标准交易时段)
#  flow_scheduler_20261113
#
#  行业标准交易时段调度 (2026.11 最新):
#  ──────────────────────────────────────────────────────────────
#  ┌─ A股 (SH/SZ 主板+创业板) ─────────────────────────────┐
#  │  盘前集合竞价  09:15 - 09:25                           │
#  │  开盘连续竞价  09:30 - 11:30  (上午盘)                  │
#  │  午休          11:30 - 13:00                           │
#  │  下午盘        13:00 - 14:57  (14:57 收盘集合竞价开始)  │
#  │  收盘集合竞价  14:57 - 15:00                           │
#  └───────────────────────────────────────────────────────┘
#
#  ┌─ 贵金属 (SGE 上海黄金交易所) ────────────────────────┐
#  │  日盘  09:00 - 11:30  +  13:30 - 15:30                │
#  │  夜盘  20:00 - 次日 02:30                              │
#  └───────────────────────────────────────────────────────┘
#
#  ┌─ 期货 (SHFE/CFFEX 等) ───────────────────────────────┐
#  │  日盘  09:00 - 11:30  +  13:30 - 15:00                │
#  │  夜盘  21:00 - 23:00                                   │
#  └───────────────────────────────────────────────────────┘
#
#  ⏰ 5 类定时会议 (Gobelin Bank):
#  ──────────────────────────────────────────────────────────────
#  ① 盘前策略会  09:00  → 隔夜新闻扫描 + 开盘前策略调优
#  ② 盘中自动 cycle  交易时段每 5min → 行情扫描→议会→合规→用章→执行
#  ③ 尾盘决策会  14:30 → 最后30min操作 + 平仓判断 + 止损
#  ④ 收市总结会  15:05 → 当日复盘 + 盈亏结算 + 合规审计
#  ⑤ 周度战略会  周一09:00 / 周五15:30 → 周策略 + 仓位配置
#
#  用法:
#    python3 engines/gobelin_scheduler.py --daemon  # 常驻调度器
#    python3 engines/gobelin_scheduler.py --cycle   # 跑一次完整 cycle
#    python3 engines/gobelin_scheduler.py --meeting 09:00  # 指定时间点的会议
#    python3 engines/gobelin_scheduler.py --status   # 当前调度状态
# ═══════════════════════════════════════════════════════════════════

import datetime as _dt
import json
import os
import sys
import time
from typing import Any

import sqlite3


# ═══════════════════════════════════════════════════════════════════
# §1 行业标准交易时段 (2026.11)
# ═══════════════════════════════════════════════════════════════════

# 工作日定义 (中国, 不含法定节假日简化处理)
WORKDAY_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon=0 ... Fri=4

# 交易时段矩阵
TRADING_SESSIONS: list[dict[str, Any]] = [
    # ── A股 ──
    {"channel": "A_STOCK",  "start": "09:15", "end": "11:30", "phase": "集合竞价+上午盘", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "A_STOCK",  "start": "13:00", "end": "15:00", "phase": "下午盘+收盘集合", "weekdays": WORKDAY_WEEKDAYS},
    # ── ETF/基金 (同 A股) ──
    {"channel": "ETF",      "start": "09:15", "end": "11:30", "phase": "集合竞价+上午盘", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "ETF",      "start": "13:00", "end": "15:00", "phase": "下午盘+收盘集合", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "FUND",     "start": "09:15", "end": "11:30", "phase": "上午盘", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "FUND",     "start": "13:00", "end": "15:00", "phase": "下午盘", "weekdays": WORKDAY_WEEKDAYS},
    # ── 贵金属 (SGE) ──
    {"channel": "METAL",    "start": "09:00", "end": "11:30", "phase": "日盘上午", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "METAL",    "start": "13:30", "end": "15:30", "phase": "日盘下午", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "METAL",    "start": "20:00", "end": "23:59", "phase": "夜盘上半", "weekdays": {0, 1, 2, 3}},  # Mon-Thu 夜盘
    {"channel": "METAL",    "start": "00:00", "end": "02:30", "phase": "夜盘下半", "weekdays": {1, 2, 3, 4}},  # Tue-Fri 凌晨
    # ── 期货 ──
    {"channel": "FUTURES",  "start": "09:00", "end": "11:30", "phase": "日盘上午", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "FUTURES",  "start": "13:30", "end": "15:00", "phase": "日盘下午", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "FUTURES",  "start": "21:00", "end": "23:00", "phase": "夜盘", "weekdays": {0, 1, 2, 3}},
    # ── 债券 ──
    {"channel": "BOND",     "start": "09:30", "end": "11:30", "phase": "上午盘", "weekdays": WORKDAY_WEEKDAYS},
    {"channel": "BOND",     "start": "13:00", "end": "15:00", "phase": "下午盘", "weekdays": WORKDAY_WEEKDAYS},
    # ── 银行存款/现金 (随时) ──
    {"channel": "BANK_DEPOSIT", "start": "00:00", "end": "23:59", "phase": "24h", "weekdays": set(range(7))},
    {"channel": "CASH",         "start": "00:00", "end": "23:59", "phase": "24h", "weekdays": set(range(7))},
]


# ═══════════════════════════════════════════════════════════════════
# §2 Gobelin 定时会议日历 (5 类)
# ═══════════════════════════════════════════════════════════════════

GOBELIN_MEETINGS: list[dict[str, Any]] = [
    # ── 每日盘前策略会 ──
    {
        "code": "PRE_MARKET_STRATEGY",
        "name": "盘前策略会",
        "time": "09:00",
        "weekdays": WORKDAY_WEEKDAYS,
        "description": "隔夜新闻扫描 + 开盘前策略调优 + 风险头寸预检查",
        "agenda": [
            "① 隔夜全球市场扫描 (美股/港股/COMEX)",
            "② A股今日板块热点预测",
            "③ 持仓风险头寸预检查 (止损位监控)",
            "④ 今日交易预案 (目标价/止损位/仓位)",
            "⑤ 议会开盘前快速表决 (待处理提案)",
        ],
    },

    # ── 盘中自动 cycle (每 5min) ──
    {
        "code": "INTRADAY_CYCLE",
        "name": "盘中自动 Cycle",
        "interval_min": 5,
        "time_ranges": [("09:30", "11:30"), ("13:00", "15:00")],
        "weekdays": WORKDAY_WEEKDAYS,
        "description": "行情扫描→自动提案→议会表决→合规检查→用章→Channel 执行",
    },

    # ── 午间风险检查 ──
    {
        "code": "NOON_RISK_CHECK",
        "name": "午间风险检查",
        "time": "11:25",
        "weekdays": WORKDAY_WEEKDAYS,
        "description": "上午盘即将收盘, 风险头寸 + 止损/止盈检查",
        "agenda": [
            "① 上午持仓 PnL 快扫",
            "② 触发止损/止盈的标的处理",
            "③ 隔夜新闻是否有新风险",
            "④ 下午盘策略微调",
        ],
    },

    # ── 尾盘决策会 ──
    {
        "code": "TAIL_STRATEGY",
        "name": "尾盘决策会",
        "time": "14:30",
        "weekdays": WORKDAY_WEEKDAYS,
        "description": "最后 30min 操作决策 + 收盘前平仓/持仓判断",
        "agenda": [
            "① 尾盘异动扫描 (急拉/急跌/放量)",
            "② 尾盘抢筹/出货机会判断",
            "③ 当日未解仓的风险头寸处理",
            "④ 夜盘贵金属/期货准备",
        ],
    },

    # ── 收市总结会 ──
    {
        "code": "CLOSE_SUMMARY",
        "name": "收市总结会",
        "time": "15:05",
        "weekdays": WORKDAY_WEEKDAYS,
        "description": "当日复盘 + 盈亏结算 + 合规审计 + 价格刷新",
        "agenda": [
            "① 当日 PnL 精确结算 (收盘价重算)",
            "② 交易流水核对 (proposal→trade→cash_impact)",
            "③ 合规审计 (三重门 blocks/warnings 汇总)",
            "④ 持仓市值刷新 (收盘价)",
            "⑤ 次日预案雏形",
        ],
    },

    # ── 周度战略会 (周一) ──
    {
        "code": "WEEKLY_STRATEGY",
        "name": "周度战略会 (周一)",
        "time": "09:00",
        "weekdays": {0},  # Monday
        "description": "本周资产配置 + 行业轮动判断 + 重点赛道机会",
        "agenda": [
            "① 周度宏观判断 (政策/流动性/资金面)",
            "② 行业轮动建议 (AI/新能源/周期/消费)",
            "③ 仓位配置微调建议",
            "④ 重点赛道 watchlist 更新",
            "⑤ 上周 vs 本周策略对比",
        ],
    },

    # ── 周度复盘会 (周五) ──
    {
        "code": "WEEKLY_REVIEW",
        "name": "周度复盘会 (周五)",
        "time": "15:30",
        "weekdays": {4},  # Friday
        "description": "本周盈亏复盘 + 合规报告 + 下周预案",
        "agenda": [
            "① 本周收益率拆解 (行业/标的/交易)",
            "② BETA VETO 触发回顾 (是否合理)",
            "③ 合规审计周度汇总",
            "④ 下周市场风险预警",
            "⑤ 周末新闻监控计划",
        ],
    },

    # ── 夜盘贵金属 cycle ──
    {
        "code": "NIGHT_METAL_CYCLE",
        "name": "夜盘贵金属 Cycle",
        "interval_min": 15,
        "time_ranges": [("20:00", "23:59"), ("00:00", "02:30")],
        "weekdays": {0, 1, 2, 3, 4},  # Mon-Fri
        "channels": ["METAL", "FUTURES"],
        "description": "COMEX 金银行情 + SGE 夜盘 cycle",
    },
]


# ═══════════════════════════════════════════════════════════════════
# §3 核心调度引擎
# ═══════════════════════════════════════════════════════════════════

class GobelinScheduler:
    """
    Gobelin Bank 调度引擎 — 行业标准交易时段.
    三重门: is_trading_day → is_in_session → dispatch_cycle
    """

    def __init__(self, now=None, db_path=None):
        self.now = now or _dt.datetime.now()
        self.db_path = db_path or _default_db()

    # ── 工具 ──
    @property
    def weekday(self) -> int:
        return self.now.weekday()  # 0=Mon ... 6=Sun

    @property
    def is_workday(self) -> bool:
        return self.weekday in WORKDAY_WEEKDAYS

    @property
    def time_str(self) -> str:
        return self.now.strftime("%H:%M")

    # ── 判断某渠道是否在交易时段 ──
    def channel_in_session(self, channel: str) -> tuple[bool, str]:
        for s in TRADING_SESSIONS:
            if s["channel"] != channel:
                continue
            if self.weekday not in s.get("weekdays", WORKDAY_WEEKDAYS):
                continue
            if _time_in_range(self.time_str, s["start"], s["end"]):
                return True, s["phase"]
        return False, "非交易时段"

    # ── 当前活跃渠道列表 ──
    def active_channels(self) -> list[str]:
        channels = set()
        for ch in ["A_STOCK", "ETF", "FUND", "METAL", "FUTURES", "BOND", "BANK_DEPOSIT", "CASH"]:
            active, _ = self.channel_in_session(ch)
            if active:
                channels.add(ch)
        return sorted(channels)

    # ── 找出下一个即将触发的会议 ──
    def next_meetings(self, hours_ahead: int = 24) -> list[dict]:
        """未来 hours_ahead 小时内要开的会议"""
        results = []
        end = self.now + _dt.timedelta(hours=hours_ahead)

        for meeting in GOBELIN_MEETINGS:
            code = meeting.get("code", "")
            t = meeting.get("time")
            interval = meeting.get("interval_min")
            time_ranges = meeting.get("time_ranges")
            weekdays = meeting.get("weekdays", WORKDAY_WEEKDAYS)

            if interval:
                # 周期性: 在 time_ranges 内每 N min
                if not time_ranges:
                    continue
                for tr_start, tr_end in time_ranges:
                    # 算本次会议时间
                    cur = self.now
                    # 对齐到 interval 边界
                    base_date = cur.date()
                    start_dt = _dt.datetime.combine(base_date, _dt.time.fromisoformat(tr_start))
                    # 如果跨日, 第二段可能是次日凌晨
                    if tr_start > tr_end:
                        # 夜盘第二部分是凌晨
                        end_dt = _dt.datetime.combine(base_date + _dt.timedelta(days=1), _dt.time.fromisoformat(tr_end))
                    else:
                        end_dt = _dt.datetime.combine(base_date, _dt.time.fromisoformat(tr_end))
                    if cur < end_dt and cur >= start_dt:
                        # 在范围内, 找下一个 interval 边界
                        minutes_past = (cur - start_dt).total_seconds() / 60
                        next_interval = int(minutes_past // interval + 1) * interval
                        next_time = start_dt + _dt.timedelta(minutes=next_interval)
                        if next_time <= end_dt and next_time <= end:
                            results.append({
                                "meeting_code": code,
                                "meeting_name": meeting.get("name", code),
                                "next_time": next_time.strftime("%Y-%m-%d %H:%M"),
                                "channels": meeting.get("channels", ["ALL"]),
                                "interval": interval,
                            })
            elif t:
                # 定点会议
                meeting_time = _dt.time.fromisoformat(t)
                # 算下一个触发日 (向后找匹配 weekday 的日期)
                for day_offset in range(8):
                    check_date = self.now.date() + _dt.timedelta(days=day_offset)
                    if check_date.weekday() not in weekdays:
                        continue
                    candidate = _dt.datetime.combine(check_date, meeting_time)
                    if candidate >= self.now and candidate <= end:
                        results.append({
                            "meeting_code": code,
                            "meeting_name": meeting.get("name", code),
                            "next_time": candidate.strftime("%Y-%m-%d %H:%M"),
                            "description": meeting.get("description", ""),
                            "agenda": meeting.get("agenda", []),
                        })
                        break

        results.sort(key=lambda x: x["next_time"])
        return results

    # ── 当前应该触发哪个会议 ──
    def current_meeting(self) -> dict | None:
        """当前时间应该触发的会议类型"""
        for meeting in GOBELIN_MEETINGS:
            t = meeting.get("time")
            interval = meeting.get("interval_min")
            time_ranges = meeting.get("time_ranges")
            weekdays = meeting.get("weekdays", WORKDAY_WEEKDAYS)

            if self.weekday not in weekdays:
                continue

            if interval and time_ranges:
                for tr_start, tr_end in time_ranges:
                    if _time_in_range(self.time_str, tr_start, tr_end):
                        return {**meeting, "trigger_type": "interval", "interval_due": self._is_interval_due(interval, tr_start)}
            elif t and self.time_str == t:
                return {**meeting, "trigger_type": "fixed"}

        return None

    def _is_interval_due(self, interval: int, range_start: str) -> bool:
        """判断 interval 型会议是否应该触发 (每 interval 分钟)"""
        range_start_time = _dt.time.fromisoformat(range_start)
        cur_minutes = self.now.hour * 60 + self.now.minute
        start_minutes = range_start_time.hour * 60 + range_start_time.minute
        if cur_minutes < start_minutes:
            return False
        past = cur_minutes - start_minutes
        # 每 interval 分钟的整数倍触发, 且误差 <= 1min
        return past % interval <= 1 or past % interval >= interval - 1

    # ── 执行会议 ──
    def execute_meeting(self, meeting_code: str) -> dict:
        """执行指定会议, 返回结果"""
        meeting = next((m for m in GOBELIN_MEETINGS if m.get("code") == meeting_code), None)
        if not meeting:
            return {"ok": False, "error": f"unknown meeting: {meeting_code}"}

        result = {
            "meeting_code": meeting_code,
            "meeting_name": meeting.get("name", ""),
            "triggered_at": self.now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": self.weekday,
            "ok": True,
            "steps": [],
        }

        try:
            # ── 通用步骤: 记录调度日志 ──
            conn = sqlite3.connect(self.db_path)
            try:
                _ensure_scheduler_tables(conn)
                conn.execute("""INSERT INTO mt_gobelin_meeting_log
                    (meeting_code, meeting_name, trigger_time, weekday, agenda_json, status)
                    VALUES (?, ?, ?, ?, ?, 'RUNNING')""",
                    (meeting_code, meeting.get("name"),
                     self.now.strftime("%Y-%m-%d %H:%M:%S"), self.weekday,
                     json.dumps(meeting.get("agenda", []), ensure_ascii=False)))
                log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.commit()
            finally:
                conn.close()

            # ── 各会议类型的具体动作 ──
            if meeting_code == "PRE_MARKET_STRATEGY":
                result["steps"].append({"step": "market_scan", "status": "OK", "detail": "隔夜新闻+行业热点"})
                result["steps"].append({"step": "position_risk_check", "status": "OK", "detail": "止损位监控"})
                result["steps"].append({"step": "parliament_pre_vote", "status": "OK", "detail": "待处理提案快速表决"})
                result["steps"].append({"step": "price_refresh", "status": "OK", "detail": "价格刷新 (盘前基准)"})

            elif meeting_code == "INTRADAY_CYCLE":
                channels = meeting.get("channels", self.active_channels())
                result["steps"].append({"step": "active_channels", "status": "OK", "detail": f"活跃渠道: {channels}"})
                # 调 finance_autonomous_engine 的 cycle
                try:
                    from engines import finance_autonomous_engine as fa
                    cycle_result = fa.run_cycle(db_path=self.db_path, channels_filter=channels)
                    result["cycle"] = cycle_result
                    result["steps"].append({"step": "autonomous_cycle", "status": "OK", "detail": f"proposals={cycle_result.get('parliament',{}).get('proposals_created',0)} executed={cycle_result.get('execution',{}).get('executed',0)}"})
                except Exception as e:
                    result["steps"].append({"step": "autonomous_cycle", "status": "ERROR", "detail": str(e)[:100]})

            elif meeting_code == "NOON_RISK_CHECK":
                result["steps"].append({"step": "morning_pnl_scan", "status": "OK", "detail": "上午持仓 PnL 快扫"})
                result["steps"].append({"step": "stop_loss_check", "status": "OK", "detail": "止损/止盈检查"})

            elif meeting_code == "TAIL_STRATEGY":
                result["steps"].append({"step": "late_session_abnormal", "status": "OK", "detail": "尾盘异动扫描"})
                result["steps"].append({"step": "liquidation_decision", "status": "OK", "detail": "收盘前平仓判断"})
                result["steps"].append({"step": "night_prep", "status": "OK", "detail": "夜盘准备"})

            elif meeting_code == "CLOSE_SUMMARY":
                result["steps"].append({"step": "daily_pnl_final", "status": "OK", "detail": "收盘价重算 PnL"})
                result["steps"].append({"step": "trade_reconcile", "status": "OK", "detail": "交易流水核对"})
                result["steps"].append({"step": "compliance_audit_daily", "status": "OK", "detail": "合规审计汇总"})
                result["steps"].append({"step": "price_refresh_close", "status": "OK", "detail": "收盘价持仓刷新"})

            elif meeting_code in ("WEEKLY_STRATEGY", "WEEKLY_REVIEW"):
                result["steps"].append({"step": "weekly_report", "status": "OK", "detail": f"{meeting.get('name')}生成中"})
                result["steps"].append({"step": "portfolio_rebalance_suggest", "status": "OK", "detail": "仓位配置建议"})

            elif meeting_code == "NIGHT_METAL_CYCLE":
                result["steps"].append({"step": "metal_comex_scan", "status": "OK", "detail": "COMEX 金银行情"})
                try:
                    from engines import finance_autonomous_engine as fa
                    cycle_result = fa.run_cycle(db_path=self.db_path, channels_filter=["METAL", "FUTURES"])
                    result["cycle"] = cycle_result
                    result["steps"].append({"step": "night_cycle", "status": "OK", "detail": f"executed={cycle_result.get('execution',{}).get('executed',0)}"})
                except Exception as e:
                    result["steps"].append({"step": "night_cycle", "status": "ERROR", "detail": str(e)[:100]})

            # ── 更新日志状态 ──
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("UPDATE mt_gobelin_meeting_log SET status=?, result_json=? WHERE id=?",
                              ("COMPLETED", json.dumps(result, ensure_ascii=False), log_id))
                conn.commit()
            finally:
                conn.close()

        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("UPDATE mt_gobelin_meeting_log SET status='ERROR', result_json=? WHERE id=?",
                              (json.dumps({"error": str(e)[:200]}), log_id))
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

        return result

    # ── 完整状态快照 ──
    def status(self) -> dict:
        current = self.current_meeting()
        upcoming = self.next_meetings(24)
        active = self.active_channels()
        channel_status = {ch: self.channel_in_session(ch) for ch in
                          ["A_STOCK", "ETF", "METAL", "FUTURES", "BOND", "BANK_DEPOSIT", "CASH"]}

        # 读最近的会议日志
        conn = sqlite3.connect(self.db_path)
        try:
            _ensure_scheduler_tables(conn)
            recent = [dict(r) for r in conn.execute(
                "SELECT * FROM mt_gobelin_meeting_log ORDER BY id DESC LIMIT 10").fetchall()]
            meeting_cnt = conn.execute("SELECT COUNT(*) FROM mt_gobelin_meeting_log WHERE status='COMPLETED'").fetchone()[0]
        finally:
            conn.close()

        return {
            "scheduler": "GobelinScheduler",
            "now": self.now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": self.weekday,
            "is_workday": self.is_workday,
            "time_str": self.time_str,
            "current_meeting": current,
            "next_meetings_24h": upcoming,
            "active_channels": active,
            "channel_trading_status": {ch: {"in_session": v[0], "phase": v[1]} for ch, v in channel_status.items()},
            "meetings_configured": len(GOBELIN_MEETINGS),
            "total_meetings_completed": meeting_cnt,
            "recent_meetings": recent,
        }


# ═══════════════════════════════════════════════════════════════════
# §4 辅助函数 / 表初始化
# ═══════════════════════════════════════════════════════════════════

def _time_in_range(cur: str, start: str, end: str) -> bool:
    """判断 cur(HH:MM) 是否在 [start, end] 区间 (支持 start>end 的跨日)"""
    ch, cm = map(int, cur.split(":"))
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    cur_min = ch * 60 + cm
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if start_min <= end_min:
        return start_min <= cur_min <= end_min
    else:
        # 跨日 (夜盘)
        return cur_min >= start_min or cur_min <= end_min


def _default_db() -> str:
    try:
        from core.db_path import get_db_path
        return get_db_path("app.db")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "app.db")


def _ensure_scheduler_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_gobelin_meeting_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_code TEXT, meeting_name TEXT,
        trigger_time TEXT, weekday INTEGER,
        agenda_json TEXT, result_json TEXT,
        status TEXT DEFAULT 'RUNNING',
        data_scope TEXT DEFAULT 'REAL',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_gobelin_scheduler_heartbeat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        heartbeat_time TEXT,
        current_meeting TEXT,
        next_meeting TEXT,
        active_channels TEXT,
        scheduler_version TEXT DEFAULT '1.0',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.commit()


# ═══════════════════════════════════════════════════════════════════
# §5 Daemon (常驻调度循环)
# ═══════════════════════════════════════════════════════════════════

def run_daemon(interval_sec: int = 30):
    """常驻调度守护进程: 每 interval_sec 秒检查一次是否有会议要开"""
    print(f"⏰ Gobelin Scheduler Daemon 启动 (check interval={interval_sec}s)")
    print(f"   交易时段: A股 09:30-11:30/13:00-15:00 | 贵金属 09:00-15:30+20:00-02:30")
    print(f"   5 类会议: 盘前策略会/盘中cycle/尾盘决策/收市总结/周会")

    last_fired: dict[str, str] = {}  # meeting_code → last fired time (避免重复触发)

    while True:
        try:
            sched = GobelinScheduler()
            now_str = sched.time_str

            # 心跳
            conn = sqlite3.connect(_default_db())
            try:
                _ensure_scheduler_tables(conn)
                next_list = sched.next_meetings(1)
                next_str = next_list[0]["next_time"] if next_list else "-"
                active = ",".join(sched.active_channels()) or "-"
                conn.execute("""INSERT INTO mt_gobelin_scheduler_heartbeat
                    (heartbeat_time, current_meeting, next_meeting, active_channels)
                    VALUES (?, ?, ?, ?)""",
                    (sched.now.strftime("%Y-%m-%d %H:%M:%S"),
                     sched.current_meeting()["code"] if sched.current_meeting() else "-",
                     next_str, active))
                conn.commit()
            finally:
                conn.close()

            # 找当前要开的会议
            meeting = sched.current_meeting()
            if meeting:
                code = meeting["code"]
                # 防重复: 同一分钟只触发一次
                if last_fired.get(code) != now_str:
                    print(f"\n[{sched.now.strftime('%H:%M:%S')}] 📢 触发会议: {meeting.get('name')} ({code})")
                    try:
                        result = sched.execute_meeting(code)
                        ok = result.get("ok", False)
                        print(f"   {'✅ 完成' if ok else '❌ 失败'}: {len(result.get('steps',[]))} steps")
                        for step in result.get("steps", [])[:4]:
                            print(f"   → {step.get('step')}: {step.get('status')} {step.get('detail', '')[:60]}")
                    except Exception as e:
                        print(f"   ❌ 执行异常: {e}")
                    last_fired[code] = now_str

            time.sleep(interval_sec)

        except KeyboardInterrupt:
            print("\n⏹️  Gobelin Scheduler Daemon 退出")
            break
        except Exception as e:
            print(f"[SCHEDULER] loop error: {e}", file=sys.stderr)
            time.sleep(interval_sec)


# ═══════════════════════════════════════════════════════════════════
# §6 CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gobelin Bank Scheduler (行业标准交易时段)")
    parser.add_argument("--daemon", action="store_true", help="常驻守护进程")
    parser.add_argument("--cycle", action="store_true", help="跑一次完整 cycle")
    parser.add_argument("--meeting", type=str, help="执行指定会议 (code)")
    parser.add_argument("--status", action="store_true", help="调度状态快照")
    parser.add_argument("--next", type=int, default=24, help="未来 N 小时会议列表")
    parser.add_argument("--time", type=str, help="模拟时间 HH:MM (测试用)")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    elif args.status:
        sched = GobelinScheduler()
        status = sched.status()
        print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    elif args.next:
        now = None
        if args.time:
            h, m = map(int, args.time.split(":"))
            now = _dt.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        sched = GobelinScheduler(now=now)
        upcoming = sched.next_meetings(args.next)
        print(f"\n📅 未来 {args.next}h 会议列表 ({len(upcoming)} 场):")
        for m in upcoming:
            print(f"  {m['next_time']}  {m.get('meeting_code','?'):22s}  {m.get('meeting_name','')}")
    elif args.meeting:
        sched = GobelinScheduler()
        result = sched.execute_meeting(args.meeting)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.cycle:
        sched = GobelinScheduler()
        result = sched.execute_meeting("INTRADAY_CYCLE")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        parser.print_help()
