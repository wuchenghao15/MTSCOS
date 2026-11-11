#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能日分类调度器 — Holiday Trigger Engine
============================================

替代旧的 Sat/Sun 硬触发, 对任意日期进行智能分类:

  ROLE_NORMAL_SATURDAY    → weekend_saturday_engine.py (大学习+模型升级)
  ROLE_NORMAL_SUNDAY     → weekend_sunday_engine.py (考试晋升)
  ROLE_HOLIDAY_EVE       → weekend_saturday_engine.py (长假前最后交易日 → 晨会准备+长假专项复盘)
  ROLE_HOLIDAY_FIRST_DAY → weekend_saturday_engine.py (长假第一天休市 → 模型校准+长假前最后交易日复盘)
  ROLE_HOLIDAY_LAST_DAY  → weekend_sunday_engine.py (长假最后一天 → 考试+准备开市晨会资料)
  ROLE_HOLIDAY_WEEKEND   → weekend_sunday_engine.py (长假中间的周末 → 合并考试)
  ROLE_WEEKDAY           → skip (正常交易日不触发)

A股节假日日历: 使用 holidays.country_holidays('CN') 动态获取国务院官方安排.
  支持 2026+ 年份, 自动识别: 长假 (≥3天连续休市), 调休补班日, 调休放假日.

CLI:
  python3 holiday_trigger_engine.py dry    # 干跑, 只打印分类结果
  python3 holiday_trigger_engine.py run    # 真跑, 执行对应引擎

FLOW_ID: flow_holiday_trigger_20261108_v2
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import sqlite3
import subprocess
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path

# ── holidays 库前置检查 ──
try:
    import holidays as _holidays_lib
    _HOLIDAYS_AVAILABLE = True
except ImportError:
    _HOLIDAYS_AVAILABLE = False
    print("[WARN] holidays 库未安装, 请先执行: pip3 install --break-system-packages holidays",
          file=sys.stderr)

# ── 路径解析 ──
_ENGINES_DIR = Path(__file__).resolve().parent
_FLASK_APP_DIR = _ENGINES_DIR.parent
_PROJECT_ROOT = _FLASK_APP_DIR.parent

try:
    from engines._common.db_resolver import get_app_db
    DB_PATH = get_app_db()
except Exception:
    DB_PATH = str(_FLASK_APP_DIR / "database" / "app.db")

FLOW_ID = "flow_holiday_trigger_20261108_v2"


# ══════════════════════════════════════════════════════════════════
# A 股日历 — 动态计算 (holidays 库)
# ══════════════════════════════════════════════════════════════════

class AShareCalendar:
    """A股交易日历: 使用 holidays 库动态识别长假/补班/调休."""

    HOLIDAY_KEYWORDS = ['春节', '国庆', '清明', '劳动节', '端午', '中秋', '元旦', '五一']

    def __init__(self, years: list[int] = None):
        if years is None:
            years = [2026, 2027]

        if not _HOLIDAYS_AVAILABLE:
            raise RuntimeError("holidays 库不可用, 无法构建 AShareCalendar")

        self._years = sorted(years)
        self._min_year, self._max_year = self._years[0], self._years[-1]

        # ── 1. 获取 CN 法定假日 ──
        self.cn = _holidays_lib.country_holidays('CN', years=self._years)

        # 所有法定假日集合 + 名称映射
        self.holiday_days: set[date] = set()
        self.holiday_names: dict[date, str] = {}
        for d, name in sorted(self.cn.items()):
            self.holiday_days.add(d)
            self.holiday_names[d] = name

        # ── 2. 从假日名称反推调休补班日 ──
        # holidays 库会把"休息日（由 YYYY-MM-DD 调休）"标记为假日,
        # 其中 YYYY-MM-DD 就是补班日 (周末但要上班).
        import re as _re
        self.makeup_workdays: set[date] = set()
        _makeup_pattern = _re.compile(r'由\s*(\d{4}-\d{2}-\d{2})\s*调休')
        for d, name in self.holiday_names.items():
            m = _makeup_pattern.search(name)
            if m:
                try:
                    makeup = datetime.strptime(m.group(1), '%Y-%m-%d').date()
                    self.makeup_workdays.add(makeup)
                except ValueError:
                    pass

        # ── 3. A 股休市日 = (周末 + 法定假日) − 补班日 ──
        self.close_days: set[date] = set()
        start_ordinal = date(self._min_year, 1, 1).toordinal()
        end_ordinal = date(self._max_year, 12, 31).toordinal()
        for ordinal in range(start_ordinal, end_ordinal + 1):
            day = date.fromordinal(ordinal)
            is_weekend = day.weekday() >= 5
            is_holiday = day in self.holiday_days
            is_makeup = day in self.makeup_workdays
            # 休市 = 周末或法定假日, 但补班日除外
            if (is_weekend or is_holiday) and not is_makeup:
                self.close_days.add(day)

        # ── 4. 长假识别: 连续 ≥3 天的 close_days ──
        self.long_holidays: list[dict] = []
        sorted_close = sorted(self.close_days)
        groups: list[list[date]] = []
        for d in sorted_close:
            if groups and (d - groups[-1][-1]).days <= 1:
                groups[-1].append(d)
            else:
                groups.append([d])

        for g in groups:
            if len(g) >= 3:
                names: set[str] = set()
                for d in g:
                    n = self.holiday_names.get(d, '')
                    for kw in self.HOLIDAY_KEYWORDS:
                        if kw in n:
                            names.add(kw)
                            break
                name = '/'.join(sorted(names)) if names else '长假'
                h = {
                    'name': name,
                    'start': g[0],
                    'end': g[-1],
                    'days': len(g),
                    '_close_group': list(g),
                }
                h['pre_last_trade'] = self._prev_trade_day(h['start'])
                h['post_first_trade'] = self._next_trade_day(h['end'])
                self.long_holidays.append(h)

        # 缓存: 节前/节后交易日 → 对应假期
        self._pre_trade_map: dict[date, dict] = {
            h['pre_last_trade']: h for h in self.long_holidays
        }
        self._post_trade_map: dict[date, dict] = {
            h['post_first_trade']: h for h in self.long_holidays
        }

    # ── 交易日判断 ──
    def _is_trade_day(self, d: date) -> bool:
        return d not in self.close_days

    def _prev_trade_day(self, d: date) -> date:
        prev = d - timedelta(days=1)
        max_back = 30
        for _ in range(max_back):
            if self._is_trade_day(prev):
                return prev
            prev -= timedelta(days=1)
        return prev  # fallback

    def _next_trade_day(self, d: date) -> date:
        post = d + timedelta(days=1)
        max_fwd = 30
        for _ in range(max_fwd):
            if self._is_trade_day(post):
                return post
            post += timedelta(days=1)
        return post

    # ── 分类主入口 ──
    def classify(self, date_str: str = None) -> dict:
        """
        对任意日期进行 A 股角色判定.

        Args:
            date_str: 'YYYY-MM-DD' 格式, None = 今天

        Returns:
            dict: {role, target_engine, ...}
        """
        if date_str:
            today = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            today = date.today()

        dow = today.weekday()
        weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][dow]

        is_makeup = today in self.makeup_workdays

        # 长假包含检查
        holiday_today: dict | None = None
        for h in self.long_holidays:
            if h['start'] <= today <= h['end']:
                holiday_today = h
                break

        # 节前/节后交易日检查
        holiday_eve = self._pre_trade_map.get(today)
        holiday_post = self._post_trade_map.get(today)

        # ── 核心判定 (优先级: 长假包含 > 节前/节后 > 补班 > 普通周末) ──
        role = 'ROLE_WEEKDAY'
        target_engine = None

        if holiday_today:
            # ═══ 长假内 ═══
            is_last = (today == holiday_today['end'])
            if dow >= 5:
                role = 'ROLE_HOLIDAY_WEEKEND'
                target_engine = 'sunday'
            elif is_last:
                role = 'ROLE_HOLIDAY_LAST_DAY'
                target_engine = 'sunday'
            elif today == holiday_today['start']:
                role = 'ROLE_HOLIDAY_FIRST_DAY'
                target_engine = 'saturday'
            else:
                role = 'ROLE_HOLIDAY_MID'
                target_engine = 'saturday'
        elif holiday_eve:
            # ═══ 节前最后交易日 (可能同时是补班日) ═══
            role = 'ROLE_HOLIDAY_EVE'
            target_engine = 'saturday'
        elif holiday_post:
            # ═══ 节后第一个交易日 (正常交易日, 不触发周末引擎) ═══
            role = 'ROLE_HOLIDAY_POST_FIRST'
            target_engine = None  # 正常交易日, skip
        elif is_makeup:
            # ═══ 普通补班日 (不是节前/节后) ═══
            role = 'ROLE_WEEKDAY_MAKEUP'
            target_engine = None
        elif dow == 5:
            role = 'ROLE_NORMAL_SATURDAY'
            target_engine = 'saturday'
        elif dow == 6:
            role = 'ROLE_NORMAL_SUNDAY'
            target_engine = 'sunday'

        return {
            'date': today.isoformat(),
            'weekday': weekday_name,
            'dow': dow,
            'role': role,
            'target_engine': target_engine,
            'holiday_today': holiday_today['name'] if holiday_today else None,
            'holiday_days': holiday_today['days'] if holiday_today else 0,
            'holiday_eve_of': holiday_eve['name'] if holiday_eve else None,
            'holiday_post_first_trade': holiday_post['name'] if holiday_post else None,
            'is_makeup_workday': is_makeup,
            # 兼容旧字段
            'is_holiday': holiday_today is not None,
        }

    def summary(self) -> str:
        """打印日历摘要 (调试用)"""
        lines = []
        lines.append(f"AShareCalendar ({self._min_year}-{self._max_year})")
        lines.append(f"  法定假日天数: {len(self.holiday_days)}")
        lines.append(f"  休市总天数:   {len(self.close_days)}")
        lines.append(f"  补班日天数:   {len(self.makeup_workdays)}")
        lines.append(f"  长假数量:     {len(self.long_holidays)}")
        for h in self.long_holidays:
            lines.append(f"    · {h['name']:8s} {h['start']} ~ {h['end']} ({h['days']}天)")
        return '\n'.join(lines)


# ── 全局单例 (首次使用时构建) ──
_CALENDAR: AShareCalendar | None = None


def get_calendar() -> AShareCalendar:
    global _CALENDAR
    if _CALENDAR is None:
        _CALENDAR = AShareCalendar([2026, 2027])
    return _CALENDAR


# ══════════════════════════════════════════════════════════════════
# 对外兼容 API (保留旧函数名)
# ══════════════════════════════════════════════════════════════════

def classify_day(date_str: str = None) -> dict:
    """兼容旧代码: 等同于 get_calendar().classify()"""
    return get_calendar().classify(date_str)


# ══════════════════════════════════════════════════════════════════
# DB 日志写入
# ══════════════════════════════════════════════════════════════════

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _log_trigger(ctx: dict) -> None:
    """写入 mt_center_evolution_log 记录本次触发决策"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO mt_center_evolution_log "
            "(center_name, event, detail) VALUES (?,?,?)",
            (
                "gobelin_trading",
                "HOLIDAY_TRIGGER",
                json.dumps({
                    'flow_id': FLOW_ID,
                    'date': ctx.get('date'),
                    'role': ctx.get('role'),
                    'target_engine': ctx.get('target_engine'),
                    'holiday_today': ctx.get('holiday_today'),
                    'holiday_eve_of': ctx.get('holiday_eve_of'),
                    'is_makeup': ctx.get('is_makeup_workday'),
                    'dow': ctx.get('dow'),
                    'weekday': ctx.get('weekday'),
                }, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

def run_smart_trigger(dry_run: bool = False) -> dict:
    """智能调度主函数"""
    if not _HOLIDAYS_AVAILABLE:
        print("[FATAL] holidays 库不可用, 无法执行")
        sys.exit(1)

    cal = get_calendar()
    ctx = cal.classify()

    print(f"\n{'#'*60}")
    print(f"# Holiday Trigger Engine — {'DRY RUN' if dry_run else 'REAL RUN'}")
    print(f"# DB: {DB_PATH}")
    print(f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"# holidays lib: v{_holidays_lib.__version__ if _HOLIDAYS_AVAILABLE else 'N/A'}")
    print(f"{'#'*60}")
    print(f"\n📅 日历摘要:")
    print(cal.summary())
    print(f"\n📅 日期分类结果:")
    print(json.dumps(ctx, ensure_ascii=False, indent=2))

    if ctx['target_engine'] is None:
        reason_map = {
            'ROLE_WEEKDAY': '正常交易日, 跳过',
            'ROLE_WEEKDAY_MAKEUP': '补班日 (周末但要上班), 跳过',
        }
        reason = reason_map.get(ctx['role'], '跳过')
        print(f"\n⏭️  今天是 {ctx['weekday']} ({ctx['date']}), {reason}")
        return ctx

    engine = ctx['target_engine']
    role = ctx['role']
    print(f"\n🎯 ROLE={role} → 执行 weekend_{engine}_engine.py")

    # 写入 DB 日志
    if not dry_run:
        _log_trigger(ctx)
        print(f"  ✓ 已记录 HOLIDAY_TRIGGER 到 evolution_log")

    if dry_run:
        print(f"\n🔍 DRY-RUN: 会执行 weekend_{engine}_engine.py (role={role})")
        print(f"  额外参数: {_build_extra_args(ctx)}")
        return ctx

    # ── 构建额外参数 ──
    extra_args = _build_extra_args(ctx)

    # ── 执行对应引擎 ──
    engine_path = os.path.join(_ENGINES_DIR, f'weekend_{engine}_engine.py')

    cmd = [sys.executable, engine_path, 'run'] + extra_args
    print(f"\n🚀 执行: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_ENGINES_DIR),
        timeout=600,  # 10 分钟超时
    )

    print(f"\n{'='*60}")
    print(f"📤 引擎 stdout (最后 800 字符):")
    stdout_tail = result.stdout[-800:] if result.stdout else '(no stdout)'
    print(stdout_tail)

    if result.stderr:
        print(f"\n⚠️ 引擎 stderr (最后 300 字符):")
        print(result.stderr[-300:])

    print(f"\n✅ 引擎退出码: {result.returncode}")
    print(f"{'='*60}\n")

    ctx['engine_returncode'] = result.returncode
    ctx['engine_stdout_tail'] = stdout_tail[:200]

    return ctx


def _build_extra_args(ctx: dict) -> list[str]:
    """根据 role 构建传递给子引擎的额外 CLI 参数"""
    extra_args = []
    role = ctx.get('role', '')

    if role == 'ROLE_HOLIDAY_EVE':
        extra_args = ['--holiday-eve', ctx.get('holiday_eve_of') or 'unknown']
    elif role in ('ROLE_HOLIDAY_FIRST_DAY', 'ROLE_HOLIDAY_MID'):
        extra_args = ['--holiday-first', ctx.get('holiday_today') or 'unknown']
    elif role == 'ROLE_HOLIDAY_LAST_DAY':
        hname = ctx.get('holiday_today') or 'unknown'
        post_trade = ctx.get('holiday_post_first_trade') or ''
        extra_args = ['--holiday-last', hname, '--post-trade', post_trade]
    elif role == 'ROLE_HOLIDAY_WEEKEND':
        extra_args = ['--holiday-weekend', ctx.get('holiday_today') or 'unknown']

    return extra_args


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='智能日分类调度器 (holidays 库驱动)')
    parser.add_argument('mode', nargs='?', default='run',
                        help='run 或 dry')
    parser.add_argument('--date', default=None,
                        help='手动指定日期 (YYYY-MM-DD), 默认今天')
    parser.add_argument('--summary', action='store_true',
                        help='只打印日历摘要, 不分类')
    args = parser.parse_args()

    if args.summary:
        cal = get_calendar()
        print(cal.summary())
        sys.exit(0)

    if args.date:
        ctx = classify_day(args.date)
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
    else:
        dry = args.mode == 'dry'
        run_smart_trigger(dry_run=dry)
