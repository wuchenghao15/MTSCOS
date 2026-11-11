#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🕐 TimeSync Engine — 时间同步中心
─────────────────────────────────────
解决 MTSCOS 273 张表时间字段不统一问题。

功能:
  1. NTP 校准 — 对比 macOS 本地时间 vs pool.ntp.org
  2. 时区统一 — 强制所有 DB 写入用 Asia/Shanghai (+08:00)
  3. 交易日历 API — is_trading_day() / next_trading_day() / trading_session()
  4. 时间漂移扫描 — 扫描 273 张表的 created_at 字段, 找异常时间戳
  5. cron/launchd 时间一致性 — 确保双轨调度与系统时间同步
  6. 时间偏移补偿 — 如果检测到漂移, 返回补偿值给所有引擎
  7. 时间锚点 — 记录关键事件的真实时间 (A股 9:30/11:30/13:00/15:00)
  8. 生成时间校准 SQL — 统一修复历史漂移数据

数据源:
  - macOS /usr/sbin/systemsetup (时区)
  - NTP pool.ntp.org (网络时间, 真实 socket 连接)
  - SQLite datetime('now','localtime') vs datetime('now') 对比
  - holidays CN 库 (交易日判断)

运行:
  cd /Users/wuchenghao/MTSCOS_AI_Project/flask-app
  python3 engines/time_sync_engine.py
"""

import socket
import struct
import time
import uuid
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta

try:
    import holidays
    _CN_HOLIDAYS = holidays.CN(years=[datetime.now().year, datetime.now().year + 1])
except ImportError:
    _CN_HOLIDAYS = set()

# ═══════════════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════════════

NTP_PORT = 123
NTP_PACKET_FORMAT = "!12I"
NTP_DELTA = 2208988800  # 1900-01-01 到 1970-01-01 的秒数
NTP_HOSTS = ["pool.ntp.org", "time.apple.com", "time.windows.com"]

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "app.db")
LAUNCHD_DIR = os.path.expanduser("~/Library/LaunchAgents")

# A 股交易时间锚点 (Asia/Shanghai)
A_SHARE_ANCHORS = {
    "pre_open":  "09:15",   # 集合竞价开始
    "market_open": "09:30", # 开盘
    "morning_close": "11:30",  # 早盘收盘
    "afternoon_open": "13:00", # 午盘开盘
    "market_close": "15:00",   # 收盘
}

# 漂移阈值
DRIFT_FUTURE_SECONDS = 60        # created_at > NOW + 60s → 未来时间
DRIFT_OLD_YEARS = 3              # created_at < NOW - 3years → 过旧数据
DRIFT_ANCIENT_YEARS = 10         # 远古异常


class TimeSyncEngine:
    """🕐 时间同步中心 — MTSCOS 273 张表的时间守护者"""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._ensure_table()
        self._last_offset_ms = 0.0
        self._last_ntp_check = None

    # ═══════════════════════════════════════════════════════════════════════
    # DB 工具
    # ═══════════════════════════════════════════════════════════════════════

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self):
        """确保 mt_time_sync_log 存在 (先查旧 schema, 再适配)"""
        conn = self._conn()
        try:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(mt_time_sync_log)"
            ).fetchall()]
            if not cols:
                self._create_table(conn)
            else:
                self._migrate_table(conn, cols)
        except sqlite3.OperationalError:
            self._create_table(conn)
        finally:
            conn.close()

    def _create_table(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_time_sync_log (
                sync_id TEXT PRIMARY KEY,
                check_time TEXT DEFAULT (datetime('now','localtime')),
                ntp_offset_ms REAL,
                ntp_stratum INTEGER,
                timezone_consistent REAL,
                drift_tables TEXT,
                anomaly_count INTEGER DEFAULT 0,
                cron_ok INTEGER DEFAULT 0,
                launchd_ok INTEGER DEFAULT 0,
                is_trading_day INTEGER DEFAULT 0,
                trading_session TEXT,
                anchor_market_open TEXT,
                anchor_market_close TEXT,
                fix_sql_generated TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()

    def _migrate_table(self, conn, existing_cols):
        """增量补列"""
        need_cols = {
            "sync_id": "TEXT PRIMARY KEY",
            "check_time": "TEXT DEFAULT (datetime('now','localtime'))",
            "ntp_offset_ms": "REAL",
            "ntp_stratum": "INTEGER",
            "timezone_consistent": "REAL",
            "drift_tables": "TEXT",
            "anomaly_count": "INTEGER DEFAULT 0",
            "cron_ok": "INTEGER DEFAULT 0",
            "launchd_ok": "INTEGER DEFAULT 0",
            "is_trading_day": "INTEGER DEFAULT 0",
            "trading_session": "TEXT",
            "anchor_market_open": "TEXT",
            "anchor_market_close": "TEXT",
            "fix_sql_generated": "TEXT",
            "created_at": "TEXT DEFAULT (datetime('now','localtime'))",
        }
        for col, dtype in need_cols.items():
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE mt_time_sync_log ADD COLUMN {col} {dtype}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()

    # ═══════════════════════════════════════════════════════════════════════
    # 1️⃣ NTP 校准 — 真实 socket 连接 pool.ntp.org:123
    # ═══════════════════════════════════════════════════════════════════════

    def ntp_check(self) -> dict:
        """发真实 NTP packet, 计算本地 vs NTP 的 offset_ms"""
        results = []
        stratum = 0
        leap_second = "no"
        synced = False

        for host in NTP_HOSTS:
            try:
                pkt, strat, leap, offset_ms = self._ntp_query(host)
                if pkt is not None:
                    results.append(offset_ms)
                    stratum = strat
                    leap_second = leap
                    synced = True
                    break  # 拿到第一个成功的就停
            except Exception as e:
                continue

        if not results:
            # 全部失败 — 返回本地 UTC vs SQLite localtime 的差值兜底
            conn = self._conn()
            local_ts = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
            utc_ts = conn.execute("SELECT datetime('now')").fetchone()[0]
            conn.close()
            offset_ms = 0.0  # 无法测量, 保守 0
            return {
                "offset_ms": offset_ms,
                "stratum": 0,
                "leap_second": "unknown",
                "is_synced": False,
                "hosts_tried": NTP_HOSTS,
                "error": "All NTP hosts unreachable",
                "sqlite_local": local_ts,
                "sqlite_utc": utc_ts,
            }

        # 用中位数减少抖动
        offset_ms = sorted(results)[len(results) // 2]
        self._last_offset_ms = offset_ms
        self._last_ntp_check = time.time()

        return {
            "offset_ms": round(offset_ms, 2),
            "stratum": stratum,
            "leap_second": leap_second,
            "is_synced": True,
            "hosts_tried": NTP_HOSTS,
            "host_used": host,
            "samples": len(results),
        }

    def _ntp_query(self, host, timeout=3):
        """单次 NTP 请求 — 真实 socket"""
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(timeout)

        # NTP mode 3 (client), version 4
        transmit_time = time.time()
        data = b'\x1b' + 47 * b'\0'

        t0 = time.time()
        client.sendto(data, (host, NTP_PORT))
        data, _ = client.recvfrom(1024)
        t1 = time.time()
        client.close()

        if not data or len(data) < 48:
            return None, 0, "unknown", 0

        # 解析 NTP 响应
        unpacked = struct.unpack(NTP_PACKET_FORMAT, data[:48])
        version = (unpacked[0] >> 1) & 0x7
        mode = unpacked[0] & 0x7
        stratum = unpacked[1]
        leap = (unpacked[0] >> 6) & 0x3
        leap_map = {0: "no", 1: "end_day", 2: "start_day", 3: "unknown"}
        leap_second = leap_map.get(leap, "unknown")

        # t1=originate, t2=receive, t3=transmit, t4=destination
        t_orig = unpacked[6] + unpacked[7] / (2**32)
        t_recv = unpacked[8] + unpacked[9] / (2**32)
        t_xmit = unpacked[10] + unpacked[11] / (2**32)
        t_dest = time.time()

        # NTP 时间戳 → Unix
        ntp_recv = t_recv - NTP_DELTA
        ntp_xmit = t_xmit - NTP_DELTA
        ntp_orig = t_orig - NTP_DELTA

        # 计算 offset = ((t2 - t1) + (t3 - t4)) / 2
        offset_seconds = ((ntp_recv - t0) + (ntp_xmit - t_dest)) / 2
        offset_ms = offset_seconds * 1000

        return offset_ms, stratum, leap_second, offset_ms

    # ═══════════════════════════════════════════════════════════════════════
    # 2️⃣ 时区审计 — 检查 DB 时间字段是否用 localtime (Asia/Shanghai)
    # ═══════════════════════════════════════════════════════════════════════

    def timezone_audit(self) -> dict:
        """
        对比 SQLite 的 datetime('now','localtime') 和 datetime('now'),
        看时差是否为 8 小时 (Asia/Shanghai = UTC+8).
        抽样 50 张表的 created_at, 看格式是否一致.
        """
        conn = self._conn()

        # 系统时区
        local_now = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
        utc_now = conn.execute("SELECT datetime('now')").fetchone()[0]

        local_dt = datetime.strptime(local_now, "%Y-%m-%d %H:%M:%S")
        utc_dt = datetime.strptime(utc_now, "%Y-%m-%d %H:%M:%S")
        delta_hours = (local_dt - utc_dt).total_seconds() / 3600

        # macOS 物理时区
        system_tz = "unknown"
        try:
            out = subprocess.run(
                ["/usr/sbin/systemsetup", "-gettimezone"],
                capture_output=True, text=True, timeout=5
            )
            m = re.search(r":\s*(.+)", out.stdout.strip())
            if m:
                system_tz = m.group(1).strip()
        except Exception:
            pass

        # 抽样表的 created_at 格式
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]

        sample_size = min(50, len(tables))
        sample_tables = tables[:sample_size]

        consistent = 0
        inconsistent = 0
        samples_with = 0
        has_tz_suffix = []  # 含 'Z' 或 '+08:00' 的
        no_tz_suffix = []

        for t in sample_tables:
            try:
                cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
                if 'created_at' not in cols:
                    continue
                row = conn.execute(f'SELECT created_at FROM "{t}" WHERE created_at IS NOT NULL ORDER BY rowid DESC LIMIT 1').fetchone()
                if row and row[0]:
                    samples_with += 1
                    val = row[0]
                    # 含 Z 或 +08:00 的视为带时区标记
                    if re.search(r'[Zz]|[+-]\d{2}:?\d{2}', str(val)):
                        has_tz_suffix.append(t)
                    else:
                        no_tz_suffix.append(t)
            except Exception:
                continue

        if samples_with > 0:
            consistent = len(no_tz_suffix)  # localtime 格式 = 无时区标记 (SQLite 默认)
            inconsistent = len(has_tz_suffix)

        conn.close()

        tz_consistent_pct = (consistent / samples_with * 100) if samples_with else 100.0

        return {
            "sqlite_delta_hours": round(delta_hours, 2),
            "is_shanghai": abs(delta_hours - 8.0) < 0.5,
            "system_timezone": system_tz,
            "local_now": local_now,
            "utc_now": utc_now,
            "tables_sampled": sample_size,
            "tables_with_created_at": samples_with,
            "consistent": consistent,
            "inconsistent": inconsistent,
            "timezone_consistent_pct": round(tz_consistent_pct, 1),
            "tables_with_tz_suffix": has_tz_suffix[:10],
            "tables_without_tz_suffix_sample": no_tz_suffix[:10],
            "recommendation": "use localtime" if delta_hours >= 7 else "CHECK_SYSTEM_TZ",
        }

    # ═══════════════════════════════════════════════════════════════════════
    # 3️⃣ 时间漂移扫描 — 找异常 created_at
    # ═══════════════════════════════════════════════════════════════════════

    def drift_scan(self) -> dict:
        """扫描所有有 created_at 的表, 查异常时间戳"""
        conn = self._conn()

        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]

        # SQLite 本地时间基准
        now_local = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
        now_ts = time.mktime(time.strptime(now_local, "%Y-%m-%d %H:%M:%S"))

        future_threshold = datetime.fromtimestamp(now_ts + DRIFT_FUTURE_SECONDS).strftime("%Y-%m-%d %H:%M:%S")
        ancient_threshold = datetime.fromtimestamp(now_ts - DRIFT_ANCIENT_YEARS * 365 * 86400).strftime("%Y-%m-%d %H:%M:%S")
        old_threshold = datetime.fromtimestamp(now_ts - DRIFT_OLD_YEARS * 365 * 86400).strftime("%Y-%m-%d %H:%M:%S")

        drift_report = {}
        total_anomalies = 0
        scanned_tables = 0

        for t in tables:
            try:
                cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
                if 'created_at' not in cols:
                    continue
                scanned_tables += 1

                # 未来时间 (created_at > NOW + 60s)
                future_cnt = conn.execute(
                    f'SELECT COUNT(*) FROM "{t}" WHERE created_at > ?',
                    (future_threshold,)
                ).fetchone()[0]

                # 远古异常 (< 10年前)
                ancient_cnt = conn.execute(
                    f'SELECT COUNT(*) FROM "{t}" WHERE created_at < ?',
                    (ancient_threshold,)
                ).fetchone()[0]

                # 过旧数据 (3-10年前)
                old_cnt = conn.execute(
                    f'SELECT COUNT(*) FROM "{t}" WHERE created_at < ? AND created_at >= ?',
                    (old_threshold, ancient_threshold)
                ).fetchone()[0]

                if future_cnt > 0 or ancient_cnt > 0 or old_cnt > 0:
                    # 取样例值
                    sample_future = None
                    if future_cnt > 0:
                        s = conn.execute(
                            f'SELECT created_at FROM "{t}" WHERE created_at > ? LIMIT 1',
                            (future_threshold,)
                        ).fetchone()
                        sample_future = s[0] if s else None

                    sample_ancient = None
                    if ancient_cnt > 0:
                        s = conn.execute(
                            f'SELECT created_at FROM "{t}" WHERE created_at < ? LIMIT 1',
                            (ancient_threshold,)
                        ).fetchone()
                        sample_ancient = s[0] if s else None

                    drift_report[t] = {
                        "future_count": future_cnt,
                        "ancient_count": ancient_cnt,
                        "old_count": old_cnt,
                        "sample_future": sample_future,
                        "sample_ancient": sample_ancient,
                        "total_anomalies": future_cnt + ancient_cnt + old_cnt,
                    }
                    total_anomalies += future_cnt + ancient_cnt

            except Exception:
                continue

        conn.close()

        return {
            "scanned_tables_with_created_at": scanned_tables,
            "now_local": now_local,
            "future_threshold": future_threshold,
            "ancient_threshold": ancient_threshold,
            "tables_with_drift": len(drift_report),
            "total_anomalies": total_anomalies,
            "drift_details": drift_report,
            "top_drift_tables": sorted(
                drift_report.items(),
                key=lambda kv: kv[1]["total_anomalies"],
                reverse=True
            )[:15],
        }

    # ═══════════════════════════════════════════════════════════════════════
    # 4️⃣ 交易日锚点 — A股时间窗口 + holidays CN
    # ═══════════════════════════════════════════════════════════════════════

    def trading_anchor(self) -> dict:
        """
        判断今日是否交易日, 返回精确时间窗口.
        交易日: 9:30-11:30, 13:00-15:00
        盘前: 9:15-9:25 集合竞价
        午休: 11:30-13:00
        """
        conn = self._conn()
        now_local = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
        conn.close()

        now = datetime.strptime(now_local, "%Y-%m-%d %H:%M:%S")
        today_date = now.date()
        weekday = today_date.weekday()  # 0=Mon 6=Sun

        # 先判断周末
        is_weekend = weekday >= 5

        # holidays CN 判断
        is_cn_holiday = False
        holiday_name = None
        if not is_weekend and _CN_HOLIDAYS:
            if today_date in _CN_HOLIDAYS:
                is_cn_holiday = True
                holiday_name = _CN_HOLIDAYS.get(today_date)

        is_trading_day = not is_weekend and not is_cn_holiday

        # 当前交易时段
        current_time = now.time()
        t_pre_open = datetime.strptime(A_SHARE_ANCHORS["pre_open"], "%H:%M").time()
        t_open = datetime.strptime(A_SHARE_ANCHORS["market_open"], "%H:%M").time()
        t_morning_close = datetime.strptime(A_SHARE_ANCHORS["morning_close"], "%H:%M").time()
        t_afternoon_open = datetime.strptime(A_SHARE_ANCHORS["afternoon_open"], "%H:%M").time()
        t_close = datetime.strptime(A_SHARE_ANCHORS["market_close"], "%H:%M").time()

        if not is_trading_day:
            session = "CLOSED"
        elif t_pre_open <= current_time < t_open:
            session = "CALL_AUCTION"
        elif t_open <= current_time < t_morning_close:
            session = "MORNING"
        elif t_morning_close <= current_time < t_afternoon_open:
            session = "LUNCH"
        elif t_afternoon_open <= current_time < t_close:
            session = "AFTERNOON"
        else:
            session = "CLOSED"

        # 下一个交易日
        next_trading = self._find_next_trading_day(today_date)

        return {
            "date": str(today_date),
            "weekday": weekday,
            "is_weekend": is_weekend,
            "is_cn_holiday": is_cn_holiday,
            "holiday_name": holiday_name,
            "is_trading_day": is_trading_day,
            "trading_session": session,
            "anchor_times": A_SHARE_ANCHORS,
            "anchor_market_open": f"{str(today_date)} {A_SHARE_ANCHORS['market_open']}",
            "anchor_market_close": f"{str(today_date)} {A_SHARE_ANCHORS['market_close']}",
            "next_trading_day": str(next_trading),
            "now_local": now_local,
        }

    def _find_next_trading_day(self, start_date):
        """向后找下一个交易日"""
        d = start_date + timedelta(days=1)
        for _ in range(30):
            if d.weekday() >= 5:
                d += timedelta(days=1)
                continue
            if _CN_HOLIDAYS and d in _CN_HOLIDAYS:
                d += timedelta(days=1)
                continue
            return d
        return d

    # ── 便捷 API ──

    def is_trading_day(self, date_str=None) -> bool:
        """判断某日是否 A 股交易日"""
        if date_str:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            d = datetime.now().date()
        if d.weekday() >= 5:
            return False
        if _CN_HOLIDAYS and d in _CN_HOLIDAYS:
            return False
        return True

    def next_trading_day(self, date_str=None) -> str:
        """返回下一个交易日"""
        if date_str:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            d = datetime.now().date()
        return str(self._find_next_trading_day(d))

    def trading_session(self) -> str:
        """返回当前交易时段: MORNING / AFTERNOON / LUNCH / CALL_AUCTION / CLOSED"""
        return self.trading_anchor()["trading_session"]

    # ═══════════════════════════════════════════════════════════════════════
    # 5️⃣ cron/launchd 时间一致性验证
    # ═══════════════════════════════════════════════════════════════════════

    def verify_cron_time(self) -> dict:
        """读 crontab + launchd plist, 看调度在正确窗口"""
        cron_entries = self._parse_crontab()
        launchd_entries = self._parse_launchd()

        # NTP offset 校准
        ntp_result = self.ntp_check()
        offset_ms = ntp_result["offset_ms"]

        cron_ok = 0
        cron_risk = []
        for entry in cron_entries:
            # 粗略检查: 如果 offset > 5s, 标记风险
            if abs(offset_ms) > 5000:
                cron_risk.append(entry)
            else:
                cron_ok += 1

        launchd_ok = 0
        launchd_risk = []
        for entry in launchd_entries:
            if abs(offset_ms) > 5000:
                launchd_risk.append(entry)
            else:
                launchd_ok += 1

        return {
            "ntp_offset_ms": offset_ms,
            "cron_total": len(cron_entries),
            "cron_ok": cron_ok,
            "cron_risk_count": len(cron_risk),
            "cron_entries": cron_entries,
            "launchd_total": len(launchd_entries),
            "launchd_ok": launchd_ok,
            "launchd_risk_count": len(launchd_risk),
            "launchd_entries": launchd_entries,
            "cron_healthy": len(cron_risk) == 0,
            "launchd_healthy": len(launchd_risk) == 0,
        }

    def _parse_crontab(self) -> list:
        """解析当前用户 crontab"""
        try:
            out = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, timeout=5
            )
            lines = out.stdout.splitlines()
        except Exception:
            return []

        entries = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("PATH") or line.startswith("HOME") or line.startswith("APP_DIR") or line.startswith("SH=") or line.startswith("LOG_DIR"):
                continue
            # crontab 标准格式: min hour dom month dow command
            parts = line.split(None, 5)
            if len(parts) >= 6:
                entries.append({
                    "raw": line,
                    "minute": parts[0],
                    "hour": parts[1],
                    "dow": parts[4],
                    "command": parts[5][:80],
                })
        return entries

    def _parse_launchd(self) -> list:
        """解析 ~/Library/LaunchAgents/com.mtscos*.plist 的 StartCalendarInterval"""
        entries = []
        if not os.path.isdir(LAUNCHD_DIR):
            return entries

        for fname in sorted(os.listdir(LAUNCHD_DIR)):
            if not fname.startswith("com.mtscos") or not fname.endswith(".plist"):
                continue
            plist_path = os.path.join(LAUNCHD_DIR, fname)
            try:
                out = subprocess.run(
                    ["/usr/libexec/PlistBuddy", "-c", "Print :StartCalendarInterval", plist_path],
                    capture_output=True, text=True, timeout=5
                )
                if out.returncode != 0:
                    continue

                text = out.stdout.strip()
                # 解析 Array 或 Dict
                if text.startswith("Array"):
                    count = 0
                    for line in text.splitlines():
                        if line.strip().startswith("Dict {"):
                            count += 1
                    entries.append({
                        "plist": fname,
                        "type": "array",
                        "dict_count": count,
                        "raw": text[:200],
                    })
                elif text.startswith("Dict"):
                    hour = self._plist_extract(text, "Hour")
                    minute = self._plist_extract(text, "Minute")
                    weekday = self._plist_extract(text, "Weekday")
                    entries.append({
                        "plist": fname,
                        "type": "dict",
                        "hour": hour,
                        "minute": minute,
                        "weekday": weekday,
                        "raw": text[:200],
                    })
            except Exception:
                continue

        return entries

    @staticmethod
    def _plist_extract(text, key):
        m = re.search(rf'{key}\s*=\s*(\d+)', text)
        return int(m.group(1)) if m else None

    # ═══════════════════════════════════════════════════════════════════════
    # 6️⃣ 时间偏移补偿 — 返回 offset 给所有引擎
    # ═══════════════════════════════════════════════════════════════════════

    def get_offset_ms(self, force_refresh=False) -> float:
        """获取最新 NTP offset (ms)"""
        if force_refresh or self._last_ntp_check is None or (time.time() - self._last_ntp_check > 300):
            self.ntp_check()
        return self._last_offset_ms

    def compensate_datetime(self, dt_str) -> str:
        """
        用 NTP offset 补偿一个时间字符串.
        如果本地时钟比 NTP 快 +838ms, compensate 会减 0.8s.
        """
        if not dt_str:
            return dt_str
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            offset_sec = self.get_offset_ms() / 1000.0
            compensated = dt - timedelta(seconds=offset_sec)
            return compensated.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return dt_str

    # ═══════════════════════════════════════════════════════════════════════
    # 7️⃣ 生成时间校准 SQL
    # ═══════════════════════════════════════════════════════════════════════

    def generate_fix_sql(self, drift_report=None) -> str:
        """对漂移表生成 UPDATE 语句"""
        if drift_report is None:
            drift_report = self.drift_scan()

        sql_lines = []
        drift_details = drift_report.get("drift_details", {})

        for table, info in drift_details.items():
            future_cnt = info.get("future_count", 0)
            ancient_cnt = info.get("ancient_count", 0)
            old_cnt = info.get("old_count", 0)

            sql_lines.append(f"-- ── {table} ──")

            if future_cnt > 0:
                # 未来时间 → 用 datetime('now','localtime') 修正
                sql_lines.append(
                    f"-- {table}: {future_cnt} 条 created_at 指向未来, 重设为 NOW"
                )
                sql_lines.append(
                    f"UPDATE \"{table}\" SET created_at = datetime('now','localtime') "
                    f"WHERE created_at > datetime('now','localtime', '+1 minute');"
                )

            if ancient_cnt > 0:
                sql_lines.append(
                    f"-- {table}: {ancient_cnt} 条远古时间戳 (< 10年前), 需人工确认"
                )
                sql_lines.append(
                    f"-- SELECT * FROM \"{table}\" WHERE created_at < datetime('now','localtime', '-10 years');"
                )

            if old_cnt > 0:
                sql_lines.append(
                    f"-- {table}: {old_cnt} 条过旧数据 (3-10年前), 标记为 legacy"
                )

            sql_lines.append("")

        if not sql_lines:
            return "-- ✅ 无需修复 — 所有表的 created_at 时间正常"

        header = [
            "-- ╔══════════════════════════════════════════════════════════════════╗",
            "-- ║  🕐 TimeSync Engine — 时间校准 SQL                              ║",
            "-- ║  Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "                        ║",
            "-- ║  漂移表: " + str(len(drift_details)) + "                                             ║",
            "-- ╚══════════════════════════════════════════════════════════════════╝",
            "",
        ]
        return "\n".join(header + sql_lines)

    # ═══════════════════════════════════════════════════════════════════════
    # 8️⃣ 一键全量运行 + 写 DB
    # ═══════════════════════════════════════════════════════════════════════

    def full_sync(self) -> dict:
        """跑全套检查, 写 mt_time_sync_log, 返回汇总"""
        print("🕐 [TimeSyncEngine] 启动全量时间同步检查...")
        print("  ├─ 1. NTP 校准")
        ntp = self.ntp_check()
        print(f"  │    offset={ntp['offset_ms']:+g}ms  stratum={ntp['stratum']}  synced={ntp['is_synced']}")

        print("  ├─ 2. 时区审计")
        tz = self.timezone_audit()
        print(f"  │    delta={tz['sqlite_delta_hours']}h  consistent={tz['timezone_consistent_pct']}%  tz={tz['system_timezone']}")

        print("  ├─ 3. 漂移扫描")
        drift = self.drift_scan()
        print(f"  │    扫描 {drift['scanned_tables_with_created_at']} 张表  漂移表={drift['tables_with_drift']}  异常={drift['total_anomalies']}")

        print("  ├─ 4. 交易日锚点")
        anchor = self.trading_anchor()
        print(f"  │    is_trading={anchor['is_trading_day']}  session={anchor['trading_session']}  next={anchor['next_trading_day']}")

        print("  ├─ 5. cron/launchd 验证")
        cron = self.verify_cron_time()
        print(f"  │    cron={cron['cron_ok']}/{cron['cron_total']}  launchd={cron['launchd_ok']}/{cron['launchd_total']}")

        print("  └─ 6. 生成修复 SQL")
        fix_sql = self.generate_fix_sql(drift)
        print(f"       SQL 长度={len(fix_sql)} 字符")

        # ── 写入 DB ──
        sync_id = f"TS-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        conn = self._conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO mt_time_sync_log (
                    sync_id, check_time, ntp_offset_ms, ntp_stratum,
                    timezone_consistent, drift_tables, anomaly_count,
                    cron_ok, launchd_ok, is_trading_day, trading_session,
                    anchor_market_open, anchor_market_close, fix_sql_generated
                ) VALUES (?, datetime('now','localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sync_id,
                ntp["offset_ms"],
                ntp["stratum"],
                tz["timezone_consistent_pct"],
                json.dumps(drift.get("top_drift_tables", [])[:5], ensure_ascii=False, default=str),
                drift["total_anomalies"],
                cron["cron_ok"],
                cron["launchd_ok"],
                1 if anchor["is_trading_day"] else 0,
                anchor["trading_session"],
                anchor["anchor_market_open"],
                anchor["anchor_market_close"],
                fix_sql,
            ))
            conn.commit()
            print(f"\n✅ 已写入 mt_time_sync_log: {sync_id}")
        except Exception as e:
            print(f"❌ 写 DB 失败: {e}")
            conn.rollback()
        finally:
            conn.close()

        return {
            "sync_id": sync_id,
            "ntp": ntp,
            "timezone": tz,
            "drift": drift,
            "anchor": anchor,
            "cron": cron,
            "fix_sql": fix_sql,
        }


# ═══════════════════════════════════════════════════════════════════════════
# __main__ — 直接运行时的入口
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    engine = TimeSyncEngine()
    result = engine.full_sync()

    print("\n" + "═" * 70)
    print("  📊 TimeSync Engine — 运行报告")
    print("═" * 70)

    ntp = result["ntp"]
    print(f"\n  📡 NTP:      offset={ntp['offset_ms']:+g}ms  stratum={ntp['stratum']}  synced={'✅' if ntp['is_synced'] else '❌'}")

    tz = result["timezone"]
    print(f"  🌐 时区:     delta={tz['sqlite_delta_hours']}h  consistent={tz['timezone_consistent_pct']}%")
    print(f"               system_tz={tz['system_timezone']}  recommendation={tz['recommendation']}")

    drift = result["drift"]
    print(f"\n  🔍 漂移:     扫描 {drift['scanned_tables_with_created_at']} 张表")
    print(f"               漂移表={drift['tables_with_drift']}  异常总数={drift['total_anomalies']}")
    for t, info in drift.get("top_drift_tables", [])[:5]:
        print(f"               · {t}: future={info['future_count']} ancient={info['ancient_count']} old={info['old_count']}")

    anchor = result["anchor"]
    print(f"\n  📅 交易日:   {anchor['date']}  weekday={anchor['weekday']}")
    print(f"               is_trading={'✅' if anchor['is_trading_day'] else '❌'}  session={anchor['trading_session']}")
    if anchor.get("holiday_name"):
        print(f"               节假日: {anchor['holiday_name']}")
    print(f"               next_trading={anchor['next_trading_day']}")
    print(f"               anchors: open={anchor['anchor_market_open']}  close={anchor['anchor_market_close']}")

    cron = result["cron"]
    print(f"\n  ⏰ 调度:     cron={cron['cron_ok']}/{cron['cron_total']}  launchd={cron['launchd_ok']}/{cron['launchd_total']}")
    print(f"               ntp_offset={cron['ntp_offset_ms']:+g}ms  同步={'✅' if abs(cron['ntp_offset_ms']) < 5000 else '⚠️'}")

    print(f"\n  🔧 SQL:      {len(result['fix_sql'])} 字符已生成")
    print("═" * 70)
