#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Manager — 统一管理 3 大系统启停/健康/状态
====================================
替代分散的 launchd 管理, 提供统一入口

三大系统:
  ICEBERG   冰山    — 意识脉冲 + 阈值绑定 + 脑库投喂
  GOBELIN   古灵阁  — 信号产出 + 交易执行 + 每日 PnL
  ANDROMEDA 仙女座 — Autopilot + EigenFlux + 自我进化

健康检查维度:
  1. HTTP endpoint 可达性
  2. launchd process 运行状态
  3. DB 核心表行数 (判定活跃度)
  4. mt_daemon_registry 心跳新鲜度
  5. mt_collab_bus_events 最近活跃度
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ═══════════════════════════════════════════════════════════════════
# 路径 & DB
# ═══════════════════════════════════════════════════════════════════
_BASE = Path(__file__).resolve().parent.parent
_PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
_ONEDRIVE_DB = _BASE / "database" / "app.db"
_DB_ENV = os.environ.get('ANDROMEDA_DB') or os.environ.get('APP_DB')
if _DB_ENV and os.path.exists(_DB_ENV):
    DB_PATH = Path(_DB_ENV)
elif _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
    DB_PATH = _PROD_LOCAL
else:
    DB_PATH = _ONEDRIVE_DB


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════
# 三大系统定义
# ═══════════════════════════════════════════════════════════════════
SYSTEMS: Dict[str, Dict[str, Any]] = {
    "iceberg": {
        "name": "🧊 冰山 Iceberg",
        "full_name": "Iceberg Consciousness System",
        "health_endpoint": "/api/iceberg/health",
        "flask_port": 5001,
        "launchd_daemons": [
            # launchctl list 中的 label
            "com.mtscos.center-self-drive",     # 中心自驱 daemon
            "com.mtscos.andromeda-warden",     # Andromeda 守望 (冰山协作)
        ],
        "core_daemons": [
            # mt_daemon_registry.process_name
            "center-self-drive", "andromeda-warden", "autopilot",
        ],
        "core_engine": "engines/iceberg_consciousness.py",
        "heartbeat_tables": [
            "mt_iceberg_consciousness_runs",
            "mt_ai_brain_feed_log",
            "mt_center_knowledge_points",
        ],
        "key_metrics": [
            ("iceberg_pulse_24h",
             "SELECT COUNT(*) FROM mt_iceberg_consciousness_runs "
             "WHERE created_at >= datetime('now','-24 hours')"),
            ("brain_feed_24h",
             "SELECT COUNT(*) FROM mt_ai_brain_feed_log "
             "WHERE created_at >= datetime('now','-24 hours')"),
        ],
        "tables_count_query":
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'mt_iceberg%'",
        "color": "#3B82F6",
    },
    "gobelin": {
        "name": "💰 古灵阁 Gobelin",
        "full_name": "Gobelin Trading & Signal System",
        "health_endpoint": "/api/gobelin/status",
        "flask_port": 5001,
        "launchd_daemons": [
            "com.mtscos.stock-sandbox",
        ],
        "core_daemons": [
            "stock-sandbox", "fm-listener", "intel-gateway",
        ],
        "core_engine": "engines/gobelin_daily_pnl.py",
        "heartbeat_tables": [
            "mt_sandbox_signals",
            "mt_sandbox_trades",
            "mt_sandbox_snapshots",
        ],
        "key_metrics": [
            ("signals_24h",
             "SELECT COUNT(*) FROM mt_sandbox_signals "
             "WHERE created_at >= datetime('now','-24 hours')"),
            ("trades_24h",
             "SELECT COUNT(*) FROM mt_sandbox_trades "
             "WHERE created_at >= datetime('now','-24 hours')"),
        ],
        "tables_count_query":
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND (name LIKE 'mt_sandbox%' OR name LIKE 'mt_gobelin%')",
        "color": "#10B981",
    },
    "andromeda": {
        "name": "🌌 仙女座 Andromeda",
        "full_name": "Andromeda Autopilot & EigenFlux",
        "health_endpoint": "/api/eigenflux/health",
        "flask_port": 5001,
        "launchd_daemons": [
            "com.mtscos.autopilot",
            "com.mtscos.flask",
            "com.mtscos.auto-repair",
        ],
        "core_daemons": [
            "autopilot", "center-self-drive", "andromeda-warden",
            "auto-repair", "ai-eigenflux",
        ],
        "core_engine": "engines/andromeda_autopilot_v2.py",
        "heartbeat_tables": [
            "mt_center_evolution_log",
            "mt_center_knowledge_points",
            "mt_approval_requests",
        ],
        "key_metrics": [
            ("evolution_log_24h",
             "SELECT COUNT(*) FROM mt_center_evolution_log "
             "WHERE created_at >= datetime('now','-24 hours')"),
            ("knowledge_points_7d",
             "SELECT COUNT(*) FROM mt_center_knowledge_points "
             "WHERE created_at >= datetime('now','-7 days')"),
        ],
        "tables_count_query":
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'mt_center%'",
        "color": "#8B5CF6",
    },
}


# ═══════════════════════════════════════════════════════════════════
# SystemManager 核心类
# ═══════════════════════════════════════════════════════════════════
class SystemManager:
    """统一系统管理入口"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    # ── 辅助方法 ──────────────────────────────────────────
    def _launchctl_status(self, label: str) -> Dict[str, Any]:
        """查 launchd 里某个 label 的运行状态"""
        try:
            r = subprocess.run(
                ["launchctl", "list", label],
                capture_output=True, text=True, timeout=5
            )
            out = r.stdout.strip()
            if not out or r.returncode != 0:
                return {"running": False, "pid": None, "exit_code": r.returncode}
            # 输出第一行: PID  ExitCode  Label
            parts = out.split("\n")[0].split("\t")
            if len(parts) >= 3:
                pid = parts[0].strip()
                exit_code = parts[1].strip()
                return {
                    "running": pid != "-",
                    "pid": int(pid) if pid != "-" else None,
                    "exit_code": int(exit_code) if exit_code != "-" else None,
                }
            return {"running": True, "pid": None, "exit_code": None}
        except Exception as e:
            return {"running": False, "error": str(e)}

    def _daemon_registry_status(self, process_name: str) -> Optional[Dict[str, Any]]:
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT process_name, daemon_name, status, pid, last_heartbeat, interval_sec, restart_count, last_error "
                "FROM mt_daemon_registry WHERE process_name = ? OR daemon_name = ?",
                (process_name, process_name)
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception:
            return None

    def _check_http(self, port: int, path: str, timeout: float = 2.0) -> Dict[str, Any]:
        import urllib.request
        url = f"http://127.0.0.1:{port}{path}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
                return {"ok": True, "status": resp.status, "body_preview": body[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def _db_metric(self, sql: str) -> Optional[int]:
        try:
            conn = _get_conn()
            row = conn.execute(sql).fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    # ── health_check ──────────────────────────────────────
    def health_check(self, system: Optional[str] = None) -> Dict[str, Any]:
        """
        综合健康检查: HTTP + launchd process + DB 活跃度 + daemon_registry 心跳
        返回 dict per system
        """
        systems_to_check = {system: SYSTEMS[system]} if system and system in SYSTEMS else SYSTEMS

        result: Dict[str, Any] = {
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "systems": {},
        }

        for sys_key, sys_def in systems_to_check.items():
            entry: Dict[str, Any] = {
                "name": sys_def["name"],
                "daemons": [],
                "metrics": {},
                "http": None,
                "score": 0.0,
                "status": "UNKNOWN",
            }

            # 1. launchd 进程状态
            running_count = 0
            total_count = 0
            for label in sys_def.get("launchd_daemons", []):
                st = self._launchctl_status(label)
                total_count += 1
                if st.get("running"):
                    running_count += 1
                entry["daemons"].append({
                    "label": label,
                    **st,
                })

            # 2. daemon_registry 心跳
            now = datetime.now()
            for pname in sys_def.get("core_daemons", []):
                reg = self._daemon_registry_status(pname)
                if reg:
                    hb = reg.get("last_heartbeat") or ""
                    hb_fresh = False
                    if hb:
                        try:
                            hb_dt = datetime.strptime(hb[:19], "%Y-%m-%d %H:%M:%S")
                            hb_fresh = (now - hb_dt) < timedelta(minutes=10)
                        except Exception:
                            pass
                    reg["heartbeat_fresh"] = hb_fresh
                    entry.setdefault("registry_daemons", []).append(reg)

            # 3. DB 核心指标
            for metric_name, sql in sys_def.get("key_metrics", []):
                entry["metrics"][metric_name] = self._db_metric(sql)

            # 4. HTTP endpoint
            http = self._check_http(sys_def["flask_port"], sys_def["health_endpoint"])
            entry["http"] = http

            # 5. 评分 (0-100)
            score_components = []

            # 进程分 (40%)
            if total_count > 0:
                proc_score = (running_count / total_count) * 100
                score_components.append(("process", proc_score, 0.4))

            # 心跳分 (30%)
            reg_daemons = entry.get("registry_daemons", [])
            if reg_daemons:
                fresh = sum(1 for d in reg_daemons if d.get("heartbeat_fresh"))
                hb_score = (fresh / len(reg_daemons)) * 100
                score_components.append(("heartbeat", hb_score, 0.3))

            # HTTP 分 (20%)
            if http and http.get("ok"):
                score_components.append(("http", 100, 0.2))
            else:
                score_components.append(("http", 0, 0.2))

            # DB 活跃度分 (10%) — 有数据就算 OK
            metrics_with_data = sum(
                1 for v in entry["metrics"].values()
                if v is not None and v > 0
            )
            metrics_total = len(entry["metrics"]) or 1
            db_score = (metrics_with_data / metrics_total) * 100
            score_components.append(("db_activity", db_score, 0.1))

            final_score = sum(s * w for _, s, w in score_components)
            entry["score"] = round(final_score, 1)
            entry["score_breakdown"] = {
                name: round(s * w, 1) for name, s, w in score_components
            }

            if final_score >= 80:
                entry["status"] = "HEALTHY"
            elif final_score >= 50:
                entry["status"] = "DEGRADED"
            else:
                entry["status"] = "CRITICAL"

            result["systems"][sys_key] = entry

        return result

    # ── status_dashboard ──────────────────────────────────
    def status_dashboard(self) -> Dict[str, Any]:
        """
        聚合三系统单页仪表板:
        - 健康分
        - 活跃 daemon 数
        - 最近事件
        - DB 大小
        - 总线待处理
        """
        hc = self.health_check()
        systems = hc["systems"]

        # 全局统计
        total_score = sum(s["score"] for s in systems.values())
        system_count = len(systems)
        avg_score = round(total_score / max(system_count, 1), 1)

        # DB 文件大小
        db_size_mb = 0
        try:
            db_size_mb = round(self.db_path.stat().st_size / 1_000_000, 2)
        except Exception:
            pass

        # 事件总线最近活动
        recent_events = []
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT event_type, source, severity, created_at "
                "FROM mt_collab_bus_events ORDER BY rowid DESC LIMIT 15"
            ).fetchall()
            conn.close()
            recent_events = [dict(r) for r in rows]
        except Exception:
            pass

        # 总线总数
        bus_total = self._db_metric("SELECT COUNT(*) FROM mt_collab_bus_events") or 0
        bus_24h = self._db_metric(
            "SELECT COUNT(*) FROM mt_collab_bus_events "
            "WHERE created_at >= datetime('now','-24 hours')"
        ) or 0

        # 进程总数
        all_running_label = []
        for sys_key, sys_def in SYSTEMS.items():
            for label in sys_def.get("launchd_daemons", []):
                st = self._launchctl_status(label)
                if st.get("running"):
                    all_running_label.append({"system": sys_key, "label": label, **st})

        return {
            "dashboard_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_score": avg_score,
            "overall_status": (
                "HEALTHY" if avg_score >= 80
                else "DEGRADED" if avg_score >= 50
                else "CRITICAL"
            ),
            "db": {
                "path": str(self.db_path),
                "size_mb": db_size_mb,
            },
            "bus": {
                "total_events": bus_total,
                "events_24h": bus_24h,
                "recent_15": recent_events,
            },
            "systems": {
                k: {
                    "name": v["name"],
                    "score": v["score"],
                    "status": v["status"],
                    "daemons_running": sum(
                        1 for d in v["daemons"] if d.get("running")
                    ),
                    "daemons_total": len(v["daemons"]),
                    "http_ok": v["http"].get("ok") if v["http"] else None,
                }
                for k, v in systems.items()
            },
            "running_launchd_total": len(all_running_label),
            "running_launchd": all_running_label,
        }

    # ── start / stop ──────────────────────────────────────
    def start_system(self, system_key: str) -> Dict[str, Any]:
        if system_key not in SYSTEMS:
            return {"error": f"unknown system: {system_key}"}
        sys_def = SYSTEMS[system_key]
        results = []
        for label in sys_def.get("launchd_daemons", []):
            try:
                r = subprocess.run(
                    ["launchctl", "kickstart", "-k", label],
                    capture_output=True, text=True, timeout=10
                )
                results.append({
                    "label": label,
                    "kickstart": r.returncode == 0,
                    "msg": (r.stdout + r.stderr).strip()[:200],
                })
            except Exception as e:
                results.append({"label": label, "error": str(e)[:200]})
        return {"system": system_key, "kickstart_results": results}

    def stop_system(self, system_key: str) -> Dict[str, Any]:
        if system_key not in SYSTEMS:
            return {"error": f"unknown system: {system_key}"}
        sys_def = SYSTEMS[system_key]
        results = []
        for label in sys_def.get("launchd_daemons", []):
            try:
                r = subprocess.run(
                    ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                    capture_output=True, text=True, timeout=10
                )
                results.append({
                    "label": label,
                    "bootout": r.returncode == 0,
                    "msg": (r.stdout + r.stderr).strip()[:200],
                })
            except Exception as e:
                results.append({"label": label, "error": str(e)[:200]})
        return {"system": system_key, "bootout_results": results}

    # ── full_status (简洁 JSON) ───────────────────────────
    def full_status(self) -> Dict[str, Any]:
        hc = self.health_check()
        return {
            "at": hc["checked_at"],
            "systems": {
                k: {
                    "name": v["name"],
                    "status": v["status"],
                    "score": v["score"],
                    "daemons": len(v["daemons"]),
                    "http_ok": v["http"].get("ok") if v["http"] else False,
                }
                for k, v in hc["systems"].items()
            },
        }


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════
def _print_cli_help():
    print("""
System Manager CLI — 三系统统一管理

用法:
  system_manager.py list                    列出所有已知系统
  system_manager.py health [--system NAME]  健康检查 (iceberg/gobelin/andromeda/all)
  system_manager.py dashboard               完整仪表板 JSON
  system_manager.py status [--system NAME] 简洁状态
  system_manager.py start --system NAME     启动某系统所有 daemon
  system_manager.py stop  --system NAME     停止某系统所有 daemon
""")


def main():
    if len(sys.argv) < 2:
        _print_cli_help()
        return

    parser = argparse.ArgumentParser(prog="system_manager", add_help=False)
    parser.add_argument("action", nargs="?", default="list")
    parser.add_argument("--system", default="all")
    parser.add_argument("--format", default="json", choices=["json", "text"])
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        _print_cli_help()
        return

    mgr = SystemManager()

    if args.action == "list":
        print("=" * 60)
        print("  MTSCOS 三系统 — 架构总览")
        print("=" * 60)
        for k, v in SYSTEMS.items():
            print(f"\n  [{k.upper()}] {v['name']}")
            print(f"    核心引擎: {v['core_engine']}")
            print(f"    LaunchD:  {len(v['launchd_daemons'])} 个")
            print(f"    注册表:   {len(v['core_daemons'])} 个")
            print(f"    HTTP:     {v['health_endpoint']} (port {v['flask_port']})")

    elif args.action == "health":
        target = None if args.system == "all" else args.system
        result = mgr.health_check(target)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "dashboard":
        result = mgr.status_dashboard()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "status":
        target = None if args.system == "all" else args.system
        result = mgr.health_check(target)
        # 精简显示
        for k, v in result["systems"].items():
            icons = {"HEALTHY": "🟢", "DEGRADED": "🟡", "CRITICAL": "🔴", "UNKNOWN": "⚪"}
            icon = icons.get(v["status"], "⚪")
            print(f"  {icon} {v['name']:30s}  score={v['score']:5.1f}  {v['status']}")

    elif args.action == "start":
        if args.system == "all":
            for k in SYSTEMS:
                print(json.dumps(mgr.start_system(k), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(mgr.start_system(args.system), indent=2, ensure_ascii=False))

    elif args.action == "stop":
        if args.system == "all":
            for k in SYSTEMS:
                print(json.dumps(mgr.stop_system(k), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(mgr.stop_system(args.system), indent=2, ensure_ascii=False))

    else:
        _print_cli_help()


if __name__ == "__main__":
    main()
