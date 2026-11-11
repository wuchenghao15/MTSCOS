#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据监控守护 — Data Monitor Daemon
多维数据健康扫描 + 异常检测 → 分级写入 → AI 自动接管

扫描维度:
  1. 🕐 DB 数据新鲜度 — 关键表最新时间戳超阈值
  2. 📉 API 返回量骤降 — 情报源返回条数 vs 历史基线
  3. 📊 数据漂移检测 — 行情分布 3σ 检测 (chg_pct / 成交量)
  4. 🔗 一致性校验 — 持仓 ↔ 行情 ↔ 订单三方数据对账
  5. 💾 DB 文件健康 — WAL 膨胀 / 锁冲突 / 表行数

异常分级: LOW → MEDIUM → HIGH → CRITICAL
AI 接管动作: backfill HTTP / 通知 Warden 重启 daemon / 标记熔断

用法:
  python3 data_monitor_daemon.py &
  launchctl bootstrap gui/$(id -u) com.mtscos.data-monitor.plist

环境变量:
  MTSCOS_DB_PATH        DB 路径
  DATA_SCAN_INTERVAL    主扫描间隔秒 (默认 30)
  INTEL_FLASK_URL       Flask 地址
  DRIFT_SAMPLE_MINUTES  分布漂移的采样窗口分钟 (默认 30)
"""
import os, sys, re, json, time, hashlib, threading, subprocess, sqlite3, logging, math, statistics
from datetime import datetime, timedelta
from pathlib import Path

# ═══ 日志 ═══
logging.basicConfig(
    level=logging.INFO,
    format="[DataMon][%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("datamon")

# ═══ 配置 ═══
_DB_PATH       = os.environ.get("MTSCOS_DB_PATH") or str(
    Path(__file__).resolve().parent.parent / "database" / "app.db"
)
_FLASK_URL     = os.environ.get("INTEL_FLASK_URL", "http://127.0.0.1:5001")
_INTERVAL_SEC  = int(os.environ.get("DATA_SCAN_INTERVAL", "30"))
_DRIFT_WINDOW  = int(os.environ.get("DRIFT_SAMPLE_MINUTES", "30"))

# ═══ DB 监控表配置 ═══
# 每张表的: key_label / db_table / 新鲜度列 / 最大允许新鲜度 (分钟) / 最小行数
_DB_TABLES = [
    {"label": "情报脑库",       "table": "mt_intel_brain_feed", "fresh_col": "created_at", "max_age_min": 5,  "min_rows": 50},
    {"label": "FM 脑库",        "table": "mt_fm_brain_feed",    "fresh_col": "created_at", "max_age_min": 15, "min_rows": 100},
    {"label": "交易流水",       "table": "mt_trade_log",         "fresh_col": "created_at", "max_age_min": 60, "min_rows": 0},
    {"label": "协作总线事件",   "table": "mt_collab_bus_events", "fresh_col": "created_at", "max_age_min": 10, "min_rows": 0},
    {"label": "屏幕监控事件",   "table": "mt_screen_events",     "fresh_col": "created_at", "max_age_min": 30, "min_rows": 0},
    {"label": "数据异常记录",   "table": "mt_data_anomalies",    "fresh_col": "created_at", "max_age_min": 0,  "min_rows": 0},
    {"label": "复盘会话",       "table": "mt_sandbox_review_sessions", "fresh_col": "created_at", "max_age_min": 1440, "min_rows": 0},
]

# ═══ API 源基线配置 (用于检测返回量骤降) ═══
_API_SOURCES = [
    {"name": "华尔街见闻", "table": "mt_intel_brain_feed", "src_filter": "%华尔街见闻%", "expected_min_per_hour": 40},
    {"name": "新浪财经",   "table": "mt_intel_brain_feed", "src_filter": "%新浪财经%",   "expected_min_per_hour": 30},
    {"name": "CCTV-2",     "table": "mt_intel_brain_feed", "src_filter": "%CCTV-2%",    "expected_min_per_hour": 20},
]

# ═══ 数据库表 ═══
_SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_data_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_type TEXT,          -- DB_STALE, API_DROP, DISTRIBUTION_DRIFT, INCONSISTENCY, DB_HEALTH
    target TEXT,                -- 哪个表/API/指标
    metric TEXT,                -- 具体指标
    expected REAL,              -- 预期值/基线
    actual REAL,                -- 实际值
    severity TEXT DEFAULT 'LOW',-- LOW, MEDIUM, HIGH, CRITICAL
    details TEXT,               -- JSON 详细信息
    resolved INTEGER DEFAULT 0,
    resolution TEXT,            -- 解决动作 (AI 自动接管了什么)
    created_at TEXT DEFAULT (datetime('now','localtime')),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_anomaly_time ON mt_data_anomalies(created_at);
CREATE INDEX IF NOT EXISTS idx_anomaly_type ON mt_data_anomalies(anomaly_type);
CREATE INDEX IF NOT EXISTS idx_anomaly_resolved ON mt_data_anomalies(resolved);
"""

# ═══ 历史基线 (用于统计异常检测) ═══
_baseline_cache = {}   # {api_name: {"counts": [c1, c2, ...], "last_update": ts}}
_anomaly_cooldown = {} # {(type, target): last_record_ts} — 同一异常冷却


def _get_db():
    return sqlite3.connect(_DB_PATH, timeout=5, check_same_thread=False)


def _ensure_schema():
    try:
        conn = _get_db()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("DB schema err: %s", e)


# ═══ 异常记录与冷却 ═══
def _record_anomaly(anom_type: str, target: str, metric: str,
                    expected: float, actual: float, severity: str,
                    details: str = "", resolution: str = "") -> int | None:
    """写入数据异常 (带冷却: 同一 target+type 10min 内不重复写)"""
    global _anomaly_cooldown
    key = (anom_type, target)
    now = time.time()
    if now - _anomaly_cooldown.get(key, 0) < 600:  # 10min 冷却
        return None
    _anomaly_cooldown[key] = now

    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO mt_data_anomalies
               (anomaly_type, target, metric, expected, actual, severity, details, resolution)
               VALUES (?,?,?,?,?,?,?,?)""",
            (anom_type, target, metric, expected, actual, severity, details[:2000], resolution),
        )
        conn.commit()
        eid = cur.lastrowid
        cur.close()
        conn.close()
        icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(severity, "⚪")
        log.warning("%s [%s] target=%s metric=%s expected=%.2f actual=%.2f — %s",
                     icon, anom_type, target, metric, expected, actual, details[:200])
        # 返回 dict (而不是 int), 供后续 .get("severity") 使用
        return {"id": eid, "severity": severity, "anomaly_type": anom_type,
                "target": target, "metric": metric, "actual": actual, "expected": expected}
    except Exception as e:
        log.error("anomaly record err: %s", e)
        return None


def _resolve_anomalies(target: str = "", anom_type: str = ""):
    """标记已解决"""
    try:
        conn = _get_db()
        q = "UPDATE mt_data_anomalies SET resolved=1, resolved_at=datetime('now','localtime'), resolution=? WHERE resolved=0"
        params = ["auto-resolved"]
        if target:
            q += " AND target=?"
            params.append(target)
        if anom_type:
            q += " AND anomaly_type=?"
            params.append(anom_type)
        conn.execute(q, params)
        conn.commit()
        conn.close()
    except Exception:
        pass


# ═══ 扫描器 1: DB 表新鲜度 ═══
def _scan_freshness() -> list:
    """扫描所有关键表的最新时间戳"""
    anomalies = []
    try:
        conn = _get_db()
        now = datetime.now()
        for tcfg in _DB_TABLES:
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*), MAX({tcfg['fresh_col']}) FROM {tcfg['table']}")
                row = cur.fetchone()
                cnt = row[0] or 0
                last_ts = row[1]

                # 行数不足 → LOW 级
                if cnt < tcfg["min_rows"]:
                    anomalies.append(_record_anomaly(
                        "DB_STALE", tcfg["table"], "row_count",
                        tcfg["min_rows"], cnt, "LOW",
                        f"{tcfg['label']} 行数不足 ({cnt} < {tcfg['min_rows']})",
                    ))

                # 新鲜度超阈值
                if last_ts and tcfg["max_age_min"] > 0:
                    try:
                        dt = datetime.strptime(str(last_ts)[:19], "%Y-%m-%d %H:%M:%S")
                        age_min = (now - dt).total_seconds() / 60
                        # 根据超阈值幅度分级
                        if age_min > tcfg["max_age_min"] * 3:
                            sev = "CRITICAL"
                        elif age_min > tcfg["max_age_min"] * 2:
                            sev = "HIGH"
                        elif age_min > tcfg["max_age_min"]:
                            sev = "MEDIUM"
                        else:
                            sev = "LOW"

                        if sev != "LOW" or age_min > tcfg["max_age_min"] * 1.5:
                            anomalies.append(_record_anomaly(
                                "DB_STALE", tcfg["table"], "freshness_age_min",
                                float(tcfg["max_age_min"]), age_min, sev,
                                f"{tcfg['label']} 数据过期 {age_min:.1f}min > 阈值 {tcfg['max_age_min']}min",
                            ))
                        elif age_min > tcfg["max_age_min"]:
                            # 轻微超阈值 (MEDIUM 以下) 也记录但不紧急
                            anomalies.append(_record_anomaly(
                                "DB_STALE", tcfg["table"], "freshness_age_min",
                                float(tcfg["max_age_min"]), age_min, "MEDIUM",
                                f"{tcfg['label']} 数据过期 {age_min:.1f}min",
                            ))
                    except Exception:
                        pass
                elif not last_ts and tcfg["max_age_min"] > 0:
                    anomalies.append(_record_anomaly(
                        "DB_STALE", tcfg["table"], "no_data",
                        1.0, 0.0, "MEDIUM",
                        f"{tcfg['label']} 表无任何数据",
                    ))
                cur.close()
            except Exception as e:
                log.debug("freshness scan %s err: %s", tcfg["table"], e)
        conn.close()
    except Exception as e:
        log.error("freshness scan err: %s", e)
    return anomalies


# ═══ 扫描器 2: API 返回量骤降 ═══
def _scan_api_volume() -> list:
    """对比各 API 源近 1 小时的返回量 vs 历史基线"""
    anomalies = []
    now = time.time()
    try:
        conn = _get_db()
        for src in _API_SOURCES:
            try:
                cur = conn.cursor()
                # 近 1 小时的条数
                cur.execute(
                    f"SELECT COUNT(*) FROM {src['table']} "
                    f"WHERE source LIKE ? AND created_at > datetime('now','localtime','-60 minutes')",
                    (src["src_filter"],)
                )
                count_1h = cur.fetchone()[0] or 0

                # 更新基线 (滑动窗口)
                baseline = _baseline_cache.setdefault(src["name"], {"counts": [], "last": 0})
                baseline["counts"].append(count_1h)
                baseline["counts"] = baseline["counts"][-6:]  # 留最近 6 个样本 (6h)
                baseline["last"] = now

                if len(baseline["counts"]) >= 3:
                    mean = statistics.mean(baseline["counts"][:-1])  # 用之前的算基线
                    std  = statistics.stdev(baseline["counts"][:-1]) if len(baseline["counts"]) >= 4 else mean * 0.3
                    expected = max(mean, src["expected_min_per_hour"])

                    # 如果当前量只有期望的 30% 以下 → 骤降
                    if count_1h < expected * 0.3 and expected > 10:
                        # 检查是 API 整体挂了还是只是小时流量低
                        sev = "CRITICAL" if count_1h == 0 else "HIGH"
                        anomalies.append(_record_anomaly(
                            "API_DROP", src["name"], "items_per_hour",
                            expected, count_1h, sev,
                            f"{src['name']} 近 1h 返回 {count_1h} 条 (基线 {expected:.0f})",
                            resolution="建议重启情报网关该数据源 / 触发 backfill",
                        ))
                    # 完全断流
                    elif count_1h == 0 and expected > 20:
                        anomalies.append(_record_anomaly(
                            "API_DROP", src["name"], "items_per_hour",
                            expected, 0, "CRITICAL",
                            f"{src['name']} 完全断流 (近 1h 0 条)",
                            resolution="触发情报网关重启",
                        ))
                cur.close()
            except Exception as e:
                log.debug("api volume scan %s err: %s", src["name"], e)
        conn.close()
    except Exception as e:
        log.error("api volume scan err: %s", e)
    return anomalies


# ═══ 扫描器 3: 数据漂移检测 (行情分布 3σ) ═══
_chg_pct_history = []     # 历史 chg_pct 样本
_volume_history = []      # 历史成交量样本
_DRIFT_MAX_SAMPLES = 200  # 最多保留这么多样本


def _update_price_history():
    """从行情雷达更新历史样本 (每次扫描都尝试)"""
    global _chg_pct_history, _volume_history
    try:
        from engines.ai_sandbox_tick_engine import _load_realtime
        rt = _load_realtime()
        for sym, v in rt.items():
            chg = v.get("chg_pct", 0)
            vol = v.get("volume", 0)
            if isinstance(chg, (int, float)):
                _chg_pct_history.append(chg)
            if isinstance(vol, (int, float)) and vol > 0:
                _volume_history.append(float(vol))
        # 截断
        _chg_pct_history = _chg_pct_history[-_DRIFT_MAX_SAMPLES:]
        _volume_history = _volume_history[-_DRIFT_MAX_SAMPLES:]
    except Exception:
        pass


def _scan_distribution_drift() -> list:
    """检测行情分布是否偏离 3σ"""
    anomalies = []
    global _chg_pct_history, _volume_history

    # 更新样本
    _update_price_history()

    if len(_chg_pct_history) >= 20:
        mean_pct = statistics.mean(_chg_pct_history)
        std_pct  = statistics.stdev(_chg_pct_history) or 0.01
        # 取最近 10 只的均值, 看是否偏离历史
        recent_10 = _chg_pct_history[-10:]
        recent_mean = statistics.mean(recent_10)
        z = abs(recent_mean - mean_pct) / std_pct if std_pct > 0 else 0

        if z > 3.0:
            anomalies.append(_record_anomaly(
                "DISTRIBUTION_DRIFT", "market_chg_pct", "z_score",
                0.0, z, "HIGH",
                f"行情涨跌幅分布 3σ 偏离 (z={z:.2f}) 历史 μ={mean_pct:.2f} σ={std_pct:.2f} 近10均值={recent_mean:.2f}",
            ))
            # 清除部分历史让它重新收敛, 避免一直漂移记录
            _chg_pct_history = _chg_pct_history[-10:]

    if len(_volume_history) >= 20:
        mean_vol = statistics.mean(_volume_history)
        try:
            log_vols = [math.log(v) for v in _volume_history if v > 0]
            if len(log_vols) >= 10:
                mean_log = statistics.mean(log_vols)
                std_log  = statistics.stdev(log_vols) or 0.1
                recent_5 = log_vols[-5:]
                z_vol = abs(statistics.mean(recent_5) - mean_log) / std_log if std_log > 0 else 0
                if z_vol > 2.5:
                    anomalies.append(_record_anomaly(
                        "DISTRIBUTION_DRIFT", "market_volume", "log_z_score",
                        0.0, z_vol, "MEDIUM",
                        f"成交量分布 2.5σ 偏离 (z={z_vol:.2f}) 可能缩量/放量异动",
                    ))
        except Exception:
            pass

    return anomalies


# ═══ 扫描器 4: 三方一致性校验 ═══
def _scan_consistency() -> list:
    """持仓 ↔ 行情 ↔ 订单 对账"""
    anomalies = []
    try:
        from engines.ai_sandbox_tick_engine import _load_positions, _load_realtime
        positions = _load_positions() or {}
        rt = _load_realtime() or {}

        # 持仓代码必须在行情中有价格
        missing_prices = [sym for sym in positions if sym not in rt or rt.get(sym, {}).get("price", 0) <= 0]
        if missing_prices:
            anomalies.append(_record_anomaly(
                "INCONSISTENCY", "positions_vs_market", "missing_price_count",
                0, float(len(missing_prices)), "MEDIUM",
                f"持仓中有 {len(missing_prices)} 只股票在行情中无有效价格: {missing_prices[:5]}",
            ))

        # 现金 + 持仓市值 ≈ 总本金 (允许 5% 浮动)
        total_cost = sum(p["avg_cost"] * p["qty"] for p in positions.values())
        pos_value  = sum(rt.get(sym, {}).get("price", p["avg_cost"]) * p["qty"] for sym, p in positions.items())
        cash = 10000.0 - total_cost  # 简化
        total_assets = cash + pos_value
        if abs(total_assets - 10000) / 10000 > 0.05 and len(positions) > 0:
            anomalies.append(_record_anomaly(
                "INCONSISTENCY", "portfolio_vs_cash", "total_assets_deviation",
                10000.0, total_assets, "MEDIUM",
                f"总资产偏离本金 {(total_assets - 10000):.2f} (偏离 {(total_assets - 10000)/100:.2f}%)",
            ))

    except Exception as e:
        log.debug("consistency scan err: %s", e)
    return anomalies


# ═══ 扫描器 5: DB 文件健康 ═══
def _scan_db_health() -> list:
    """SQLite 文件大小 / WAL / 锁"""
    anomalies = []
    try:
        db_path = Path(_DB_PATH)
        if not db_path.exists():
            anomalies.append(_record_anomaly(
                "DB_HEALTH", _DB_PATH, "file_missing",
                1.0, 0.0, "CRITICAL",
                "DB 文件不存在!",
            ))
            return anomalies

        size_mb = db_path.stat().st_size / (1024 * 1024)

        # WAL 膨胀
        wal_path = db_path.with_suffix(db_path.suffix + "-wal")
        if wal_path.exists():
            wal_mb = wal_path.stat().st_size / (1024 * 1024)
            if wal_mb > 10:  # WAL 超过 10MB
                anomalies.append(_record_anomaly(
                    "DB_HEALTH", "WAL", "wal_size_mb",
                    5.0, wal_mb, "MEDIUM",
                    f"SQLite WAL 文件膨胀 {wal_mb:.1f}MB (>10MB), 建议 checkpoint",
                    resolution="可执行 PRAGMA wal_checkpoint(TRUNCATE)",
                ))

        # 主文件超过 500MB 警告
        if size_mb > 500:
            anomalies.append(_record_anomaly(
                "DB_HEALTH", str(db_path.name), "size_mb",
                300.0, size_mb, "LOW",
                f"DB 主文件 {size_mb:.0f}MB (超过 300MB 阈值), 建议归档清理旧数据",
            ))

        # 连接测试
        try:
            conn = sqlite3.connect(_DB_PATH, timeout=1)
            conn.execute("SELECT 1")
            conn.close()
        except Exception as e:
            anomalies.append(_record_anomaly(
                "DB_HEALTH", str(db_path.name), "connection_test",
                1.0, 0.0, "CRITICAL",
                f"DB 连接失败: {e}",
                resolution="检查是否有锁冲突 / 磁盘满 / 权限",
            ))

    except Exception as e:
        log.debug("db health scan err: %s", e)
    return anomalies


# ═══ 扫描器 6: 网络连通性 ═══
def _scan_network() -> list:
    """关键 API 源的网络连通性"""
    anomalies = []
    targets = [
        ("华尔街见闻", "https://api-one-wscn.awtmt.com"),
        ("新浪财经",   "https://feed.mix.sina.com.cn"),
        ("CCTV-2",     "http://genglei.8866.org:9901"),
    ]
    for name, url in targets:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=5)
            # 只要能连上就算通 (m3u8 可能不会返回 200)
        except Exception as e:
            msg = str(e)[:100]
            anomalies.append(_record_anomaly(
                "NETWORK", name, "connectivity",
                1.0, 0.0, "HIGH",
                f"{name} API 网络不通: {msg}",
                resolution="检查 DNS / 代理 / VPN / 源站故障",
            ))
    return anomalies


# ═══ AI 自动接管 ═══
def _ai_takeover(new_anomalies: list):
    """AI 自动处理异常 — 分级动作"""
    if not new_anomalies:
        return
    if not isinstance(new_anomalies, list):
        new_anomalies = []

    for ev in new_anomalies:
        if ev is None:
            continue
        sev = (ev.get("severity") if isinstance(ev, dict) else "LOW") or "LOW"
        atype = (ev.get("anomaly_type") if isinstance(ev, dict) else "") or ""
        target = (ev.get("target") if isinstance(ev, dict) else "") or ""

        try:
            import urllib.request

            # 自动动作
            action_taken = ""
            if atype == "API_DROP" and sev in ("CRITICAL", "HIGH"):
                # 触发 backfill
                try:
                    req = urllib.request.Request(
                        f"{_FLASK_URL}/api/sandbox/intel/recent?limit=5",
                        headers={"User-Agent": "MTSCOS-DataMon"},
                    )
                    urllib.request.urlopen(req, timeout=5)
                    action_taken = "triggered intel backfill"
                except Exception:
                    pass

            elif atype == "DB_STALE" and sev == "CRITICAL":
                # 通知 Warden 重启对应 daemon
                # 通过 Flask 端点让 Warden 执行自愈
                try:
                    payload = json.dumps({
                        "agent": "data_monitor",
                        "action": "warden_heal",
                        "reason": f"DB_STALE CRITICAL: {target}",
                        "target": target,
                    }, ensure_ascii=False)
                    req = urllib.request.Request(
                        f"{_FLASK_URL}/api/sandbox/ai-dispatch",
                        data=payload.encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=5)
                    action_taken = "notified warden"
                except Exception:
                    pass

            elif atype == "NETWORK" and sev == "HIGH":
                action_taken = "logged; requires human check"

            log.info("🤖 AI 接管 [%s] %s → %s", sev, target, action_taken or "no auto action needed")

        except Exception as e:
            log.warning("AI takeover err: %s", e)


# ═══ 主循环 ═══
class DataMonitor:
    def __init__(self):
        self.running = False
        self.cycle = 0
        self._last_network_scan = 0
        self._last_drift_scan = 0

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()
        log.info("🚀 DataMonitor 启动 (interval=%ds)", _INTERVAL_SEC)

    def _loop(self):
        _ensure_schema()
        while self.running:
            self.cycle += 1
            try:
                self._cycle_once()
            except Exception as e:
                log.error("cycle err: %s", e)
            time.sleep(_INTERVAL_SEC)

    def _cycle_once(self):
        t0 = time.time()
        all_anomalies = []
        now = time.time()

        # 每次都扫
        all_anomalies.extend(_scan_freshness())

        # 每 2 轮扫 API 量
        if self.cycle % 2 == 0:
            all_anomalies.extend(_scan_api_volume())

        # 每 4 轮扫一致性 + DB 健康
        if self.cycle % 4 == 0:
            all_anomalies.extend(_scan_consistency())
            all_anomalies.extend(_scan_db_health())

        # 每 6 轮扫漂移 + 网络
        if self.cycle % 6 == 0:
            all_anomalies.extend(_scan_distribution_drift())
            all_anomalies.extend(_scan_network())

        # AI 自动接管 (有异常且至少 HIGH 级才触发)
        critical = [a for a in all_anomalies
                    if a is not None and (a.get("severity") == "CRITICAL"
                                          or (a.get("severity") == "HIGH" and self.cycle % 2 == 0))]
        if critical:
            _ai_takeover(critical)

        # 汇总日志
        elapsed = time.time() - t0
        critical_cnt = sum(1 for a in all_anomalies if a and a.get("severity") == "CRITICAL")
        high_cnt     = sum(1 for a in all_anomalies if a and a.get("severity") == "HIGH")
        med_cnt      = sum(1 for a in all_anomalies if a and a.get("severity") == "MEDIUM")
        if critical_cnt or high_cnt or med_cnt:
            log.warning("📊 #%d anomalies: C=%d H=%d M=%d (%.1fs)",
                         self.cycle, critical_cnt, high_cnt, med_cnt, elapsed)
        else:
            log.info("📊 #%d all clear (%.1fs)", self.cycle, elapsed)

    def health_check(self) -> dict:
        return {
            "running": self.running,
            "cycle": self.cycle,
            "interval_sec": _INTERVAL_SEC,
            "db_path": _DB_PATH,
            "baseline_count": len(_baseline_cache),
            "drift_history_samples": len(_chg_pct_history),
        }


def run():
    monitor = DataMonitor()
    monitor.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.running = False
        log.info("DataMonitor stopped")


if __name__ == "__main__":
    run()
