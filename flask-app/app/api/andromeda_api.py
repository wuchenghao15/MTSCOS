"""
🌌 Andromeda-Alpha 仙女座自演化 API
======================================
统一提供仙女座自演化引擎 + 双向同步的实时状态给前端 dashboard.

路由:
  GET  /api/andromeda/stats         核心仪表盘数据 (cycle/derived/daemon/Mini 状态)
  GET  /api/andromeda/health        快速健康检查 (Mini ping + Ollama + daemon heartbeat)
  POST /api/andromeda/trigger       手动触发一轮演化 (异步后台跑)
  GET  /api/andromeda/sync_log      最近 10 条 autosync 同步日志
  GET  /api/andromeda/knowledge     Mini vs Dev 知识流对比

数据来源:
  - SQLite 单数据源 (database/app.db)
  - evolution_checkpoint.json (cycle 状态)
  - mt_daemon_registry (daemon heartbeat)
  - autosync_andromeda._RUNTIME (进程内状态)
"""

import os
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, request, session

andromeda_bp = Blueprint("andromeda", __name__, url_prefix="/api/andromeda")

# ─── 常量 ───
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 多 DB candidate (和 server_real_db._get_andromeda_state 对齐, 防数据库漂移)
_DB_CANDIDATES = [
    PROJECT_ROOT / "engines" / "app.db",   # Mac mini 完整 AI 表
    PROJECT_ROOT / "database" / "app.db",  # Flask 主库
    PROJECT_ROOT / "app.db",              # fallback
]
CHECKPOINT_PATH = PROJECT_ROOT / "ai_engines" / "_runtime" / "evolution_checkpoint.json"
DAEMON_NAMES = ("sys_andromeda_autosync", "sys_andromeda_auto_evolution")
# Ollama 多端口候选 (AirPlay Receiver 可能占 11434, 实测 11435 为主)
_OLLAMA_PORTS = (11435, 11434, 11436)


def _resolve_db_path() -> str:
    """找到第一个存在的 app.db."""
    for p in _DB_CANDIDATES:
        if p.exists():
            return str(p)
    return str(_DB_CANDIDATES[0])


# ════════════════════════════════════════════════════════════════
#  内部工具
# ════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _read_checkpoint() -> dict:
    """读 evolution checkpoint, 失败返回空 dict."""
    try:
        if CHECKPOINT_PATH.exists():
            with open(CHECKPOINT_PATH) as f:
                cp = json.load(f)
            return {
                "cycle_count": cp.get("cycle_count", 0),
                "total_derived": cp.get("total_derived", 0),
                "total_reinforced": cp.get("total_reinforced", 0),
                "last_knowledge_id": cp.get("last_knowledge_id"),
                "created_at": cp.get("created_at_checkpoint"),
            }
    except Exception:
        pass
    return {"cycle_count": 0, "total_derived": 0, "total_reinforced": 0}


def _read_db_counts() -> dict:
    """一次 SQL 拿 7 表行数 + 最新时间戳."""
    result = {}
    try:
        conn = sqlite3.connect(_resolve_db_path(), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.cursor()

        queries = [
            ("eigenflux_comm_messages", "SELECT COUNT(*), substr(MAX(created_at),1,16) FROM eigenflux_comm_messages"),
            ("eigenflux_comm_sessions", "SELECT COUNT(*) FROM eigenflux_comm_sessions"),
            ("ai_brain_enhanced_knowledge", "SELECT COUNT(*), substr(MAX(created_at),1,16) FROM ai_brain_enhanced_knowledge"),
            ("knowledge_graph_nodes", "SELECT COUNT(*) FROM knowledge_graph_nodes"),
            ("knowledge_graph_relations", "SELECT COUNT(*) FROM knowledge_graph_relations"),
            ("mt_andromeda_employee_registry", "SELECT COUNT(*) FROM mt_andromeda_employee_registry"),
            ("mt_ai_self_evolution_log", "SELECT COUNT(*), substr(MAX(created_at),1,16) FROM mt_ai_self_evolution_log"),
        ]
        for name, sql in queries:
            row = cur.execute(sql).fetchone()
            result[name] = {"count": row[0], "latest": row[1] if len(row) > 1 else None}

        # daemon heartbeat
        placeholders = ",".join("?" * len(DAEMON_NAMES))
        db_versions = DAEMON_NAMES
        hb_rows = cur.execute(
            f"SELECT daemon_name, last_heartbeat, status, restart_count FROM mt_daemon_registry "
            f"WHERE daemon_name IN ({placeholders})",
            db_versions
        ).fetchall()
        for name, hb, status, restart in hb_rows:
            result[f"daemon_{name}"] = {
                "heartbeat": hb,
                "status": status,
                "restart_count": restart or 0,
                "is_alive": _is_daemon_alive(hb),
            }

        conn.close()
    except Exception as e:
        result["_error"] = str(e)
    return result


def _is_daemon_alive(hb_str: Optional[str], grace_minutes: int = 60) -> bool:
    """daemon 最后心跳 grace_minutes 内算活.
    兼容 ISO (2026-10-10T20:02:26) 和 SPACE (2026-10-10 20:02:26) 两种格式.
    默认 60min 宽限 (daemon 有冷启动/冷启动延迟).
    
    🔧 2026-10-13: smart_mount 写本地时间 (datetime.now() 无 UTC),
    daemon heartbeat 混用 UTC/本地写入 → 先按本地解析, 失败再按 UTC 试.
    """
    if not hb_str:
        return False
    try:
        raw = hb_str[:19]
        fmt = "%Y-%m-%dT%H:%M:%S" if "T" in raw else "%Y-%m-%d %H:%M:%S"
        # 先按"本地时间"解析 (smart_mount 写 datetime.now() 不带 tz)
        ts = datetime.strptime(raw, fmt).timestamp()
        age = time.time() - ts
        if age < 0:
            # 负数 = 可能是真 UTC 时间 (DB 写 UTC 但本地+8h) → 按 UTC 再解一次
            ts_utc = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
            age = time.time() - ts_utc
        return age < grace_minutes * 60
    except Exception:
        return False


# ─── Mini 服务器地址 ───
# 多地址候选 + env var 可配置, 防止网络漂移
_MINI_ADDR_ENV = os.environ.get('MTSCOS_MINI_ADDR', '')  # 🔧 可配置
_MINI_ADDRS = [
    _MINI_ADDR_ENV,                                         # 1. env var 优先
    'hulk-macmini',                                         # 2. Tailscale MagicDNS (最稳)
    '100.106.220.96',                                       # 3. Tailscale IP (2026-10-13)
    '192.168.31.9',                                         # 4. 旧局域网 IP (已失效, 兜底)
]


def _mini_ping() -> dict:
    """轻量 ping Mac mini, 不超过 2s. 多地址 fallback (Tailscale 优先)."""
    result = {"alive": False, "latency_ms": None, "addr": None}
    try:
        import subprocess
        for addr in _MINI_ADDRS:
            if not addr: continue
            try:
                r = subprocess.run(
                    ["ping", "-c", "1", "-W", "2000", addr],
                    capture_output=True, text=True, timeout=4
                )
                if r.returncode == 0:
                    result["alive"] = True
                    result["addr"] = addr
                    for line in r.stdout.split("\n"):
                        if "time=" in line:
                            try:
                                result["latency_ms"] = round(
                                    float(line.split("time=")[1].split(" ")[0]), 1
                                )
                            except Exception:
                                pass
                            break
                    break
            except Exception:
                continue
    except Exception:
        pass
    return result


def _ollama_check() -> dict:
    """3s 超时检查 Ollama, 多端口探测 (AirPlay 可能占 11434)."""
    result = {"alive": False, "models": 0}
    try:
        import urllib.request
        for port in _OLLAMA_PORTS:
            try:
                req = urllib.request.Request(f"http://localhost:{port}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode())
                    result["alive"] = True
                    result["models"] = len(data.get("models", []))
                    result["port"] = port
                    break
            except Exception:
                continue
    except Exception:
        pass
    return result


# ════════════════════════════════════════════════════════════════
#  API Endpoints
# ════════════════════════════════════════════════════════════════

@andromeda_bp.route("/stats", methods=["GET"])
def api_andromeda_stats():
    """核心仪表盘数据 — 所有 4 个 dashboard 页面都用这个."""
    t0 = time.time()
    checkpoint = _read_checkpoint()
    db = _read_db_counts()
    mini = _mini_ping()
    ollama = _ollama_check()

    # 计算 "这轮 cycle 衍生率"
    derived_per_cycle = checkpoint["total_derived"] / max(checkpoint["cycle_count"], 1)

    payload = {
        "success": True,
        "generated_at": _now_iso(),
        "elapsed_ms": round((time.time() - t0) * 1000),

        # ── 演化状态 ──
        "evolution": {
            "cycle_count": checkpoint["cycle_count"],
            "total_derived": checkpoint["total_derived"],
            "total_reinforced": checkpoint["total_reinforced"],
            "derived_per_cycle": round(derived_per_cycle, 1),
            "last_knowledge_id": checkpoint["last_knowledge_id"],
            "checkpoint_created_at": checkpoint["created_at"],
        },

        # ── 数据库 7 表 ──
        "db_tables": {
            "eigenflux_messages": db.get("eigenflux_comm_messages", {}),
            "eigenflux_sessions": db.get("eigenflux_comm_sessions", {}),
            "brain_enhanced": db.get("ai_brain_enhanced_knowledge", {}),
            "graph_nodes": db.get("knowledge_graph_nodes", {}),
            "graph_relations": db.get("knowledge_graph_relations", {}),
            "employee_registry": db.get("mt_andromeda_employee_registry", {}),
            "evolution_log": db.get("mt_ai_self_evolution_log", {}),
        },

        # ── daemon 心跳 ──
        "daemons": {
            "autosync": db.get("daemon_sys_andromeda_autosync", {"is_alive": False}),
            "evolution": db.get("daemon_sys_andromeda_auto_evolution", {"is_alive": False}),
        },

        # ── 基础设施 ──
        "infra": {
            "mini": mini,
            "ollama": ollama,
        },

        # ── Arduino 自动探测 (轻量安全, 不返回敏感数据) ──
        "arduino": _arduino_light_status(),

        # ── SA 双密钥状态 (轻量, 仅 bool 字段) ──
        "sa_dual_key": _sa_dual_key_light_status(),

        # ── 迷你状态判断 ──
        "andromeda_status": _compute_andromeda_status(db, mini, ollama, checkpoint),
    }
    return jsonify(payload)


def _arduino_light_status() -> dict:
    """Arduino 轻量状态 — 公共安全, 无敏感数据."""
    out = {"connected": False, "device_count": 0, "devices": [], "last_check": None}
    try:
        import subprocess, platform
        sys = platform.system()
        found = []
        if sys == "Darwin":
            r = subprocess.run(["ls", "/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*"],
                               capture_output=True, text=True, timeout=2)
            for line in (r.stdout or "").strip().split("\n"):
                if line.strip():
                    dev = os.path.basename(line.strip())
                    found.append({"port": dev, "vid_pid": "—"})
        elif sys == "Linux":
            r = subprocess.run(["find", "/dev", "-maxdepth", "1", "-name", "ttyUSB*", "-o", "-name", "ttyACM*"],
                               capture_output=True, text=True, timeout=2)
            for line in (r.stdout or "").strip().split("\n"):
                if line.strip():
                    found.append({"port": os.path.basename(line.strip()), "vid_pid": "—"})
        out["connected"] = len(found) > 0
        out["device_count"] = len(found)
        out["devices"] = found[:5]
        out["last_check"] = _now_iso()
    except Exception:
        out["connected"] = False
    return out


def _sa_dual_key_light_status() -> dict:
    """SA 双密钥轻量状态 — 公共安全, 仅 bool 字段, 不暴露 serial/token."""
    out = {"vikey_online": False, "fingerprint_ready": False, "sa_session_active": False, "note": ""}
    try:
        # 1. VIKEY 硬件探测 (不查 serial)
        try:
            from core.services.vikey_driver import get_hardware_key_provider
            hkp = get_hardware_key_provider()
            out["vikey_online"] = bool(hkp and hkp.is_connected())
        except Exception:
            # fallback: 看 /dev 设备
            import subprocess, platform
            sys = platform.system()
            if sys == "Darwin":
                r = subprocess.run(["ls", "/dev/cu.usbmodem*"], capture_output=True, text=True, timeout=2)
                out["vikey_online"] = bool((r.stdout or "").strip())
    except Exception:
        pass
    try:
        # 2. Fingerprint/WebAuthn 可用性 (浏览器端能力, 服务端只标记"已启用")
        conn = sqlite3.connect(_resolve_db_path(), timeout=2)
        row = conn.execute(
            "SELECT COUNT(*) FROM mt_perm_assignment WHERE role_code='super_admin'"
        ).fetchone()
        out["fingerprint_ready"] = bool(row and row[0] > 0)
        conn.close()
    except Exception:
        pass
    # 3. SA session 是否在线 (仅公共安全判断: server_real_db 已有 session 表)
    try:
        conn = sqlite3.connect(_resolve_db_path(), timeout=2)
        # mt_permission_audit_detail / login_logs 都行, 只要看到 sa 近期活跃
        row = conn.execute(
            "SELECT username FROM login_logs WHERE username LIKE '%wuchenghao%' AND success=1 ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        out["sa_session_active"] = bool(row)
        conn.close()
    except Exception:
        pass
    return out


def _compute_andromeda_status(db: dict, mini: dict, ollama: dict, cp: dict) -> dict:
    """综合仙女座系统健康状态."""
    issues = []

    if not mini["alive"]:
        issues.append({"level": "warn", "msg": "Mac mini 离线 — 双向同步暂停"})
    if not ollama["alive"]:
        issues.append({"level": "fail", "msg": "Ollama 离线 — 演化暂停"})
    autosync_hb = db.get("daemon_sys_andromeda_autosync", {})
    if not autosync_hb.get("is_alive"):
        issues.append({"level": "warn", "msg": f"autosync daemon 心跳过期 ({autosync_hb.get('heartbeat')})"})
    evol_hb = db.get("daemon_sys_andromeda_auto_evolution", {})
    if not evol_hb.get("is_alive"):
        issues.append({"level": "warn", "msg": f"evolution daemon 心跳过期 ({evol_hb.get('heartbeat')})"})

    if len(issues) == 0:
        health = "green"
        label = "仙女座 · 全速运行"
    elif any(i["level"] == "fail" for i in issues):
        health = "red"
        label = "仙女座 · 需要修复"
    else:
        health = "yellow"
        label = "仙女座 · 轻微退化"

    return {
        "health": health,
        "label": label,
        "issues": issues,
        "score": 100 - len(issues) * 25,  # 0-100
    }


@andromeda_bp.route("/health", methods=["GET"])
def api_andromeda_health():
    """快速健康检查 (给前端 badge 轮询用).
    
    健康度分层:
    - ok: Ollama (核心推理引擎) 在线 → 系统可对外提供 AI 能力
    - daemon_*: 辅助 daemon 心跳状态 (独立字段, 不阻塞 ok)
    - mini_alive: Mini 同步辅助 (可选, fail-soft)
    """
    mini = _mini_ping()
    ollama = _ollama_check()

    # 读 daemon 心跳只查最少字段
    db_alive = {}
    try:
        conn = sqlite3.connect(_resolve_db_path(), timeout=3)
        cur = conn.cursor()
        for name in DAEMON_NAMES:
            row = cur.execute(
                "SELECT last_heartbeat FROM mt_daemon_registry WHERE daemon_name=?",
                (name,)
            ).fetchone()
            db_alive[name] = _is_daemon_alive(row[0] if row else None)
        conn.close()
    except Exception:
        pass

    # all_ok: 仅 Ollama (核心推理) → 系统可对外服务
    # daemon 心跳作为辅助信息独立展示, 不阻塞整体健康度
    all_ok = ollama["alive"]
    all_daemons_alive = all(db_alive.values())

    return jsonify({
        "ok": all_ok,
        "mini_alive": mini["alive"],
        "ollama_alive": ollama["alive"],
        "ollama_port": ollama.get("port"),
        "daemon_autosync_alive": db_alive.get("sys_andromeda_autosync", False),
        "daemon_evolution_alive": db_alive.get("sys_andromeda_auto_evolution", False),
        "all_daemons_alive": all_daemons_alive,
        "generated_at": _now_iso(),
    })


@andromeda_bp.route("/trigger", methods=["POST"])
def api_andromeda_trigger():
    """手动触发一轮演化 (后台异步跑, 不阻塞)."""
    try:
        import threading

        reason = request.args.get("reason", "manual_dashboard_trigger")

        def _run_in_bg():
            try:
                from engines.andromeda_auto_evolution import run_cycle
                run_cycle()
            except Exception as e:
                print(f"[ANDROMEDA] 手动演化异常: {e}")

        t = threading.Thread(target=_run_in_bg, name=f"andromeda_trigger_{int(time.time())}", daemon=True)
        t.start()

        return jsonify({
            "success": True,
            "msg": f"演化已触发 (reason={reason})",
            "thread_started": True,
            "estimated_s": 120,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


@andromeda_bp.route("/sync_log", methods=["GET"])
def api_andromeda_sync_log():
    """最近 15 条 autosync 日志."""
    try:
        log_path = Path.home() / "Library" / "Application Support" / "MTSCOS AI" / "autosync.log"
        if not log_path.exists():
            return jsonify({"success": True, "logs": []})

        lines = log_path.read_text(errors="ignore").split("\n")
        # 只取 info/warn/error 行, 去掉重复 header
        relevant = [
            ln.strip() for ln in lines
            if any(tag in ln for tag in [
                "[info]", "[warn]", "[error]", "==========",
                "Phase A:", "Phase B:", "DB skip-done", "同步完成", "开始双向同步"
            ]) and ln.strip()
        ]
        return jsonify({
            "success": True,
            "logs": relevant[-15:],
            "total_lines": len(lines),
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


@andromeda_bp.route("/knowledge", methods=["GET"])
def api_andromeda_knowledge():
    """Mini vs Dev 知识量对比 (近 24h 增量)."""
    try:
        conn = sqlite3.connect(_resolve_db_path(), timeout=5)
        cur = conn.cursor()

        # Dev 侧自己有多少
        queries = {
            "messages_total": "SELECT COUNT(*) FROM eigenflux_comm_messages",
            "messages_24h": "SELECT COUNT(*) FROM eigenflux_comm_messages WHERE created_at > datetime('now','-1 day')",
            "brain_total": "SELECT COUNT(*) FROM ai_brain_enhanced_knowledge",
            "brain_24h": "SELECT COUNT(*) FROM ai_brain_enhanced_knowledge WHERE created_at > datetime('now','-1 day')",
            "graph_nodes": "SELECT COUNT(*) FROM knowledge_graph_nodes",
            "graph_relations": "SELECT COUNT(*) FROM knowledge_graph_relations",
            "cycle": "SELECT cycle_count FROM ai_engines_runtime_checkpoint",
        }
        result = {}
        for k, sql in queries.items():
            try:
                result[k] = cur.execute(sql).fetchone()[0]
            except Exception:
                result[k] = None

        # 读 checkpoint
        cp = _read_checkpoint()
        result["cycle_count"] = cp["cycle_count"]
        result["derived"] = cp["total_derived"]
        result["reinforced"] = cp["total_reinforced"]

        conn.close()

        # Mini 侧 — 可以直接 rsync 远端 DB 比, 但成本高
        # 这里只返回 Dev 侧快照, Mini 数据靠 autosync 补
        return jsonify({
            "success": True,
            "dev_snapshot": result,
            "note": "Mini 侧数据等下轮 autosync 同步后自动合并, 当前为 Dev 侧快照",
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


# ════════════════════════════════════════════════════════════════
#  GET /api/andromeda/teams  —  仙女座 AI 天团全景
# ════════════════════════════════════════════════════════════════
@andromeda_bp.route('/teams', methods=['GET'])
def api_andromeda_teams():
    """
    返回全部 15 个天团 + 成员, 用于首页 SVG 银河 + roster 面板渲染
    数据来源: mt_team_registry + mt_team_members
    """
    try:
        import sqlite3 as _sql
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'database/app.db')
        conn = _sql.connect(db_path)
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        # 取天团注册表
        cur.execute("""
            SELECT team_id, team_name, member_count, skill_keywords, color_tag, auto_formed_at
            FROM mt_team_registry
            ORDER BY member_count DESC
        """)
        registry = [dict(r) for r in cur.fetchall()]

        # 取各团成员 (每团限前 8 个核心成员)
        teams = []
        for reg in registry:
            cur.execute("""
                SELECT member_name, skill_level, source, capabilities
                FROM mt_team_members
                WHERE team_name = ?
                ORDER BY
                    CASE UPPER(skill_level)
                        WHEN 'NATIONAL_GRAND_MASTER' THEN 0
                        WHEN 'GRAND_MASTER' THEN 1
                        WHEN 'ARCHITECT' THEN 2
                        WHEN 'UI_MASTER' THEN 3
                        WHEN 'COMPLIANCE' THEN 4
                        WHEN 'DBA' THEN 5
                        WHEN 'AUTO_EVOLUTION' THEN 6
                        ELSE 50
                    END,
                    member_name
                LIMIT 8
            """, (reg['team_name'],))
            members = [dict(r) for r in cur.fetchall()]

            # 核心专家标签
            core_mask = ['GRAND_MASTER','UI_MASTER','ARCHITECT','COMPLIANCE','DBA','AUTO_EVOLUTION',
                        'SYSTEM_ENGINEERING_PIONEER','SECURITY']
            has_core = any(m['skill_level'] in core_mask for m in members)

            teams.append({
                "team_id": reg['team_id'],
                "team_name": reg['team_name'],
                "member_count": reg['member_count'],
                "color": reg['color_tag'] or "#95A5A6",
                "skill_keywords": reg['skill_keywords'] or '',
                "has_core_expert": has_core,
                "core_members": members,
            })

        conn.close()

        # 为 SVG 计算: 总成员 / 技术团人数 / 文化团人数
        tech_names = {"🎨 前端艺术天团","🏛️ 架构天团","⚙️ 后端工程天团","🗄️ DBA 天团",
                    "🤖 AI 引擎天团","⚖️ 合规安全天团","🧪 测试巡检天团","📚 题库教育天团",
                    "🛠️ DevOps 天团","🧠 知识脑库天团","💬 产品交互天团","🔧 运维修复天团"}
        total = sum(t['member_count'] for t in teams)
        tech_total = sum(t['member_count'] for t in teams if t['team_name'] in tech_names)
        cult_total = total - tech_total

        return jsonify({
            "success": True,
            "total_members": total,
            "total_teams": len(teams),
            "tech_members": tech_total,
            "culture_members": cult_total,
            "teams": teams,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


# ════════════════════════════════════════════════════════════════
#  GET /api/andromeda/employees  —  AI 员工全景 (已雇佣)
# ════════════════════════════════════════════════════════════════
@andromeda_bp.route('/employees', methods=['GET'])
def api_andromeda_employees():
    """返回 ai_employees + mtscos_ai_employees 全景 + 来源分布"""
    try:
        import sqlite3 as _sql
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'database/app.db')
        conn = _sql.connect(db_path)
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        # 总数 + 来源分布 (从 mt_ai_auto_hire_log 看 source)
        cur.execute("SELECT COUNT(*) FROM ai_employees")
        total_ai = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM mtscos_ai_employees")
        total_mtscos = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM eigenflux_registrations")
        total_reg = cur.fetchone()[0]

        # 来源分布
        source_dist = {}
        try:
            cur.execute("""
                SELECT source, COUNT(*) as cnt
                FROM mt_ai_auto_hire_log
                GROUP BY source ORDER BY cnt DESC
            """)
            for r in cur.fetchall():
                source_dist[r[0]] = r[1]
        except Exception:
            pass

        # 最近 20 个 AI 员工 (带 EigenFlux 注册状态)
        recent = []
        cur.execute("""
            SELECT a.name, a.description, a.status, a.specialties,
                   a.created_at, a.model_version,
                   r.registration_status as ef_status
            FROM ai_employees a
            LEFT JOIN eigenflux_registrations r ON r.employee_name = a.name
            ORDER BY a.created_at DESC
            LIMIT 20
        """)
        for r in cur.fetchall():
            recent.append(dict(r))

        # EigenFlux 待邀请
        pending_invite = 0
        try:
            cur.execute("""
                SELECT COUNT(*) FROM eigenflux_registrations
                WHERE registration_status = 'pending_invite'
            """)
            pending_invite = cur.fetchone()[0]
        except Exception:
            pass

        conn.close()
        return jsonify({
            "success": True,
            "totals": {
                "ai_employees": total_ai,
                "mtscos_ai_employees": total_mtscos,
                "eigenflux_registrations": total_reg,
                "pending_eigenflux_invite": pending_invite,
            },
            "source_distribution": source_dist,
            "recent": recent,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


# ════════════════════════════════════════════════════════════════
#  GET /api/andromeda/andromeda_pool  —  仙女座员工库 (33,602)
# ════════════════════════════════════════════════════════════════
@andromeda_bp.route('/andromeda_pool', methods=['GET'])
def api_andromeda_pool():
    """仙女座员工库统计 + 高等级样本 (用于 SA dashboard 浏览/筛选)"""
    try:
        import sqlite3 as _sql
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'database/app.db')
        conn = _sql.connect(db_path)
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        # 总量
        cur.execute("SELECT COUNT(*) FROM mt_andromeda_employee_registry")
        total = cur.fetchone()[0]

        # level 分布
        level_dist = {}
        cur.execute("SELECT level, COUNT(*) FROM mt_andromeda_employee_registry GROUP BY level ORDER BY level")
        for r in cur.fetchall():
            level_dist[f"L{r[0]}"] = r[1]

        # employee_source 分布
        source_dist = {}
        cur.execute("SELECT employee_source, COUNT(*) FROM mt_andromeda_employee_registry GROUP BY employee_source ORDER BY COUNT(*) DESC LIMIT 10")
        for r in cur.fetchall():
            source_dist[r[0]] = r[1]

        # 已桥接 vs 未桥接 (level >= 7)
        cur.execute("SELECT COUNT(*) FROM mt_andromeda_employee_registry WHERE level >= 7")
        high_level = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM mt_ai_auto_hire_log
            WHERE source = 'ANDROMEDA_REGISTRY'
        """)
        bridged = cur.fetchone()[0]

        # 高等级样本 (level >= 8, 前 15)
        samples = []
        cur.execute("""
            SELECT employee_id, name, employee_type, level,
                   employee_source, neuralhub_task, route_priority, enabled
            FROM mt_andromeda_employee_registry
            WHERE level >= 8 AND enabled = 1
            ORDER BY level DESC, call_count DESC
            LIMIT 15
        """)
        for r in cur.fetchall():
            samples.append(dict(r))

        conn.close()
        return jsonify({
            "success": True,
            "total_registry": total,
            "level_distribution": level_dist,
            "source_distribution": source_dist,
            "high_level_total": high_level,
            "already_bridged": bridged,
            "available_to_bridge": high_level - bridged,
            "high_level_samples": samples,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


# ════════════════════════════════════════════════════════════════
#  POST /api/andromeda/hire  —  触发仙女座桥接 + auto_hire + EigenFlux 邀请
# ════════════════════════════════════════════════════════════════
@andromeda_bp.route('/hire', methods=['POST'])
def api_andromeda_hire():
    """SA 手动触发一轮: 仙女座桥接 → auto_hire → EigenFlux 邀请"""
    try:
        import threading

        payload = request.get_json(silent=True) or {}
        max_andromeda = int(payload.get("max_andromeda", 30))
        min_level = int(payload.get("min_level", 7))

        def _run_in_bg():
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "engines"))
                from ai_auto_hire_engine import (
                    andromeda_hiring_bridge, auto_hire_employees,
                    auto_invite_experts, run_hire_cycle, _log,
                )
                _log("[API_HIRE] 触发手动一轮 hire")
                result = run_hire_cycle()
                _log(f"[API_HIRE] 完成 andromeda={result.get('andromeda_bridge', {}).get('bridged', 0)} "
                     f"hire={result.get('hire_employees', {}).get('hired', 0)} "
                     f"invite={result.get('invite_experts', {}).get('invited', 0)}")
            except Exception as e:
                print(f"[ANDROMEDA HIRE] 后台执行失败: {e}")

        t = threading.Thread(target=_run_in_bg, name=f"andromeda_hire_{int(time.time())}", daemon=True)
        t.start()

        return jsonify({
            "success": True,
            "msg": "Hire 已触发 (仙女座桥接 + auto_hire + EigenFlux 邀请)",
            "thread_started": True,
            "params": {"max_andromeda": max_andromeda, "min_level": min_level},
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


# ════════════════════════════════════════════════════════════════
#  GET /api/andromeda/eigenflux_pending  —  EigenFlux 待邀请队列
# ════════════════════════════════════════════════════════════════
@andromeda_bp.route('/eigenflux_pending', methods=['GET'])
def api_andromeda_eigenflux_pending():
    """eigenflux_registrations 中状态为 pending_invite / inactive 的, 需 EigenFlux 引擎拉取"""
    try:
        import sqlite3 as _sql
        from flask import current_app
        db_path = current_app.config.get('DATABASE', 'database/app.db')
        conn = _sql.connect(db_path)
        conn.row_factory = _sql.Row
        cur = conn.cursor()

        # 状态分布
        try:
            cur.execute("""
                SELECT registration_status, COUNT(*) FROM eigenflux_registrations
                GROUP BY registration_status ORDER BY COUNT(*) DESC
            """)
            status_dist = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            status_dist = {}

        # pending_invite 前 20
        pending = []
        try:
            cur.execute("""
                SELECT employee_id, employee_name, employee_type,
                       registration_status, created_at, last_heartbeat
                FROM eigenflux_registrations
                WHERE registration_status IN ('pending_invite', 'inactive', 'unknown')
                ORDER BY created_at DESC LIMIT 20
            """)
            for r in cur.fetchall():
                pending.append(dict(r))
        except Exception:
            pass

        # EigenFlux 网络引擎最近活动 (mt_ai_eigenflux_messages)
        recent_msgs = 0
        try:
            cur.execute("""
                SELECT COUNT(*) FROM mt_ai_eigenflux_messages
                WHERE created_at >= datetime('now', '-1 hour')
            """)
            recent_msgs = cur.fetchone()[0]
        except Exception:
            pass

        conn.close()
        return jsonify({
            "success": True,
            "status_distribution": status_dist,
            "pending_list": pending,
            "recent_eigenflux_messages_1h": recent_msgs,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


# ════════════════════════════════════════════════════════════════
#  v22.17.0 邀请流程增强 (flow_id=flow_sa_ai_invite_enhance_20261013)
#  GET  /api/andromeda/invite/status       邀请状态跟踪
#  POST /api/andromeda/invite/batch        批量邀请
#  POST /api/andromeda/invite/retry        邀请重试
#  GET  /api/andromeda/invite/mutual_stats 好友互推统计
# ════════════════════════════════════════════════════════════════

def _invite_db_conn():
    """邀请增强端点统一 DB 连接 (主库 database/app.db)
    注: PROJECT_ROOT = flask-app 目录 (见文件头 L33)"""
    from flask import current_app
    db_path = current_app.config.get("DATABASE", "database/app.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(str(PROJECT_ROOT), db_path)
        if not os.path.exists(db_path):
            db_path = os.path.join(str(PROJECT_ROOT), "database", "app.db")
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@andromeda_bp.route('/invite/status', methods=['GET'])
def api_invite_status():
    """邀请状态跟踪: invite_log 状态/来源分布 + 重试历史 + pending 明细"""
    try:
        conn = _invite_db_conn()
        cur = conn.cursor()

        status_dist = {}
        try:
            cur.execute("SELECT invite_status, COUNT(*) FROM mt_eigenflux_invite_log GROUP BY 1")
            status_dist = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            pass

        source_dist = {}
        try:
            cur.execute("SELECT invite_source, COUNT(*) FROM mt_eigenflux_invite_log GROUP BY 1")
            source_dist = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            pass

        recent = []
        try:
            cur.execute("""
                SELECT invite_id, expert_name, expert_domain, invite_source,
                       invite_status, COALESCE(retry_count, 0) AS retry_count,
                       last_retry_at, invited_at
                FROM mt_eigenflux_invite_log
                ORDER BY invited_at DESC LIMIT 20
            """)
            recent = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        pending_count = 0
        try:
            cur.execute("SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='pending_invite'")
            pending_count = cur.fetchone()[0]
        except Exception:
            pass

        retry_summary = {}
        try:
            cur.execute("""
                SELECT COALESCE(retry_count, 0) AS rc, COUNT(*)
                FROM mt_eigenflux_invite_log GROUP BY rc ORDER BY rc
            """)
            retry_summary = {str(r[0]): r[1] for r in cur.fetchall()}
        except Exception:
            pass

        conn.close()
        return jsonify({
            "success": True,
            "status_distribution": status_dist,
            "source_distribution": source_dist,
            "retry_summary": retry_summary,
            "pending_invite_count": pending_count,
            "recent_invites": recent,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


@andromeda_bp.route('/invite/batch', methods=['POST'])
def api_invite_batch():
    """批量邀请: {count, domain, source} — 同步执行 (纯 INSERT, 秒级)"""
    try:
        payload = request.get_json(silent=True) or {}
        count = payload.get("count", 5)
        domain = payload.get("domain")
        source = payload.get("source", "SA_BATCH_INVITE")

        sys.path.insert(0, os.path.join(str(PROJECT_ROOT), "engines"))
        from ai_auto_hire_engine import batch_invite
        result = batch_invite(count=count, domain=domain, source=source)

        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


@andromeda_bp.route('/invite/retry', methods=['POST'])
def api_invite_retry():
    """邀请重试: {max_retry} — 非 ACCEPTED 且未达上限的重发一轮"""
    try:
        payload = request.get_json(silent=True) or {}
        max_retry = payload.get("max_retry", 3)

        sys.path.insert(0, os.path.join(str(PROJECT_ROOT), "engines"))
        from ai_auto_hire_engine import retry_pending_invites
        result = retry_pending_invites(max_retry=max_retry)

        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500


@andromeda_bp.route('/invite/mutual_stats', methods=['GET'])
def api_invite_mutual_stats():
    """好友互推统计: 基于 mt_ai_eigenflux_connections 二度好友推荐数据"""
    try:
        conn = _invite_db_conn()
        cur = conn.cursor()

        total = connected = 0
        try:
            cur.execute("SELECT COUNT(*) FROM mt_ai_eigenflux_connections")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mt_ai_eigenflux_connections WHERE handshake_state='CONNECTED'")
            connected = cur.fetchone()[0]
        except Exception:
            pass

        relation_dist = {}
        try:
            cur.execute("SELECT relation_level, COUNT(*) FROM mt_ai_eigenflux_connections GROUP BY 1")
            relation_dist = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            pass

        friend_recommended = 0
        try:
            cur.execute("""
                SELECT COUNT(*) FROM mt_ai_eigenflux_connections
                WHERE shared_topics_json LIKE '%friend_recommendation%'
            """)
            friend_recommended = cur.fetchone()[0]
        except Exception:
            pass

        recent_24h = 0
        try:
            cur.execute("""
                SELECT COUNT(*) FROM mt_ai_eigenflux_connections
                WHERE created_at >= datetime('now', '-1 day')
            """)
            recent_24h = cur.fetchone()[0]
        except Exception:
            pass

        avg_strength = 0.0
        try:
            cur.execute("SELECT AVG(strength) FROM mt_ai_eigenflux_connections WHERE handshake_state='CONNECTED'")
            v = cur.fetchone()[0]
            avg_strength = round(float(v), 3) if v is not None else 0.0
        except Exception:
            pass

        conn.close()
        return jsonify({
            "success": True,
            "total_connections": total,
            "connected": connected,
            "relation_level_distribution": relation_dist,
            "friend_recommended": friend_recommended,
            "friend_recommendation_ratio": round(friend_recommended / total, 3) if total else 0.0,
            "new_connections_24h": recent_24h,
            "avg_connected_strength": avg_strength,
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500
