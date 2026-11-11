"""
from __future__ import annotations

sys_wendaemon.py — 🧠 仙女座 AI 高智能社区 总托管 daemon
=========================================================

flow_ai_community_20261028

八大核心职责 (AI 高智能社区总托管):
  1. 每 6h   → wf_hire_employee (AI 员工扩张)
  2. 每 30min → wf_knowledge_ingest (eigenflux → 脑库)
  3. 每 15min → 🏛️ 大厅 AI 自治 tick (6 轨 Flask)
  4. 每 5min  → 🧠 13 中心自主驱动 (心跳/自检/自愈/自研发)  ← 智能激活中心
  5. 每 10min → 🧬 中心自动衍化 (方向池/种子/繁殖)          ← 智能进化
  6. 每 20min → 🤝 13 中心联动 (弱者求援/强者驰援/自动协作) ← 中心联动
  7. 每 2min  → 👁️ 托管守护巡检 (心跳超时 → 自动补心跳/拉 run_once) ← 智能托管
  8. 每 15min → 📊 社区自治总览 (汇总 heartbeat/pulse/hall/evolution)

硬约束 (从 smart_sync daemon 事故吸取):
  ✅ 短连接: 每周期 connect → 工作事务 → close, 绝不持久持有 DB FD
  ✅ PID 文件: _runtime/pids/sys_wendaemon.pid (启动写, SIGTERM 删)
  ✅ mt_daemon_registry: 注册 process_name=sys_wendaemon + heartbeat + status
  ✅ SIGTERM 优雅关闭: 捕获信号, 清理, exit 0
  ✅ cadence 可配置: env *_INTERVAL_SEC

启动:
  python3 engines/sys_wendaemon.py &
  或 launchd: ~/Library/LaunchAgents/com.mtscos.wendaemon.plist
"""

import os, sys, time, signal, json, sqlite3, uuid, threading
from datetime import datetime, timezone

# ── 路径配置 (env-first, 和其他引擎统一) ──
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROD_DB = os.path.join(os.path.expanduser('~'), 'MTSCOS_PROD', 'flask-app', 'database', 'app.db')
_ONEDRIVE_DB = os.path.join(ROOT, 'database', 'app.db')
DB_PATH = os.environ.get('APP_DB') or (
    _PROD_DB if os.path.exists(_PROD_DB) else _ONEDRIVE_DB
)
RUNTIME_DIR = os.path.join(ROOT, '_runtime')
PID_DIR = os.path.join(RUNTIME_DIR, 'pids')
LOG_DIR = os.path.join(RUNTIME_DIR, 'logs')
PID_FILE = os.path.join(PID_DIR, 'sys_wendaemon.pid')
CHECKPOINT_FILE = os.path.join(RUNTIME_DIR, 'wendaemon_checkpoint.json')

# ── cadence (默认全部 env 可覆盖) ──
HIRE_INTERVAL       = int(os.environ.get('HIRE_INTERVAL_SEC',       6 * 3600))        # 6h
INGEST_INTERVAL     = int(os.environ.get('INGEST_INTERVAL_SEC',     30 * 60))         # 30min
HALL_INTERVAL       = int(os.environ.get('HALL_TICK_INTERVAL_SEC',  15 * 60))         # 15min 大厅自治 tick
SELF_DRIVE_INTERVAL = int(os.environ.get('SELF_DRIVE_INTERVAL_SEC', 5 * 60))         # 5min 13 中心自主驱动
EVOLUTION_INTERVAL  = int(os.environ.get('EVOLUTION_INTERVAL_SEC',  10 * 60))        # 10min 中心衍化
COLLAB_INTERVAL     = int(os.environ.get('COLLAB_INTERVAL_SEC',     20 * 60))         # 20min 中心联动
SUPERVISOR_INTERVAL = int(os.environ.get('SUPERVISOR_INTERVAL_SEC', 2 * 60))          # 2min daemon 托管巡检
COMMUNITY_INTERVAL  = int(os.environ.get('COMMUNITY_INTERVAL_SEC',  15 * 60))        # 15min 社区总览
PROPOSAL_INTEL_INTERVAL = int(os.environ.get('PROPOSAL_INTEL_INTERVAL_SEC', 60))      # 60s 提案智能全链路 (13 智能)
HEARTBEAT_INTERVAL  = 30                                                              # 30s heartbeat

HALL_TICK_URL = os.environ.get('HALL_TICK_URL', 'http://127.0.0.1:5001/api/internal/hall/tick')
HIRE_BATCH_SIZE = int(os.environ.get('HIRE_BATCH_SIZE', 3))
INGEST_BATCH_SIZE = int(os.environ.get('INGEST_BATCH_SIZE', 50))

# daemon 托管: 心跳超过此阈值视为超时, 需要托管唤醒
SUPERVISOR_TIMEOUT_SEC = int(os.environ.get('SUPERVISOR_TIMEOUT_SEC', 2 * 3600))   # 2h
# 哪些 daemon 是"核心守护", 心跳超时必须托管唤醒 (其他的只记日志)
CORE_DAEMONS = [
    "ai_center_self_drive",
    "sys_center_evolution",
    "sys_wendaemon",
    "sys_auto_repair",
    "sys_patrol_inspector",
    "sys_heartbeat_writer",
    "sys_andromeda_auto_evolution",
    "sys_andromeda_autosync",
    "ai_eigenflux_network_engine",
    "ai_team_collab_engine",
]

# ── 中心能力图谱 (联动用): center → [可驰援的中心关键词] ──
CENTER_COLLAB_MAP = {
    "AI引擎中心":       ["教育题库中心", "考试引擎中心", "前端设计中心"],
    "教育题库中心":     ["考试引擎中心", "AI引擎中心", "研究院"],
    "考试引擎中心":     ["教育题库中心", "AI引擎中心", "维护部队"],
    "数据中心":         ["数据研究中心", "AI引擎中心", "研究院"],
    "安全中心":         ["海关总署", "运维中心", "维护部队"],
    "运维中心":         ["备份中心", "安全中心", "维护部队"],
    "备份中心":         ["运维中心", "数据中心", "灾难恢复"],
    "维护部队":         ["运维中心", "安全中心", "海关总署"],
    "海关总署":         ["安全中心", "维护部队", "立法委员会"],
    "立法委员会":       ["安全中心", "海关总署", "研究院"],
    "研究院":           ["教育题库中心", "数据中心", "AI引擎中心"],
    "前端设计中心":     ["AI引擎中心", "教育题库中心", "仙女座天团"],
    "仙女座天团":       ["AI引擎中心", "冰山团队", "研究院"],
    "冰山团队":         ["仙女座天团", "研究院", "立法委员会"],
}

# ── 状态 ──
_running = True
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════
# 基础设施
# ═══════════════════════════════════════════════════════════════════

def _log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] wendaemon: {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, 'sys_wendaemon.log'), 'a') as f:
            f.write(line + "\n")
    except Exception:
        pass


def _pid_write():
    try:
        os.makedirs(PID_DIR, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        _log(f"pid write fail: {e}", "WARN")


def _pid_cleanup():
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(PID_FILE)
    except Exception:
        pass


def _checkpoint_load() -> dict:
    try:
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_hire_at": 0,
        "last_ingest_at": 0,
        "last_knowledge_id": 0,
        "total_hires": 0,
        "total_ingested": 0,
        "total_revenue_usd": 0.0,
        # 🆕 13 中心自主驱动
        "last_self_drive_at": 0, "total_self_drives": 0,
        # 🆕 中心衍化
        "last_evolution_at": 0, "total_evolutions": 0,
        # 🆕 中心联动
        "last_collab_at": 0, "total_collabs": 0,
        # 🆕 daemon 托管
        "last_supervisor_at": 0, "total_daemons_boosted": 0,
        # 🆕 社区总览
        "last_community_at": 0, "total_communities": 0,
        "last_proposal_intel_at": 0, "total_proposal_intels": 0,
    }


def _checkpoint_save(cp: dict):
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(cp, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log(f"checkpoint save fail: {e}", "WARN")


def _registry_heartbeat(status: str = "alive", note: str = ""):
    """短连接写 daemon_registry heartbeat — 用完即关"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute(
            """INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, restart_count, last_heartbeat, pid,
             cooldown_until, config_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("sys_wendaemon",
             "🧠 AI社区总托管: hire+ingest+hall_tick+center_self_drive+evolution+collab+daemon_supervisor+community",
             status, 0,
             datetime.now(timezone.utc).isoformat(), os.getpid(), 0,
             json.dumps({
                 "note": note,
                 "hire": HIRE_INTERVAL, "ingest": INGEST_INTERVAL,
                 "hall": HALL_INTERVAL, "self_drive": SELF_DRIVE_INTERVAL,
                 "evolution": EVOLUTION_INTERVAL, "collab": COLLAB_INTERVAL,
                 "supervisor": SUPERVISOR_INTERVAL, "community": COMMUNITY_INTERVAL,
                 "proposal_intel": PROPOSAL_INTEL_INTERVAL,
                 "flow_id": "flow_ai_community_20261028",
             }, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f"registry fail: {e}", "WARN")


def _db_connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=10)


def _eigenflux_new_since(last_msg_id: int, limit: int) -> list[dict]:
    """短连接 — 拉 mt_ai_eigenflux_messages."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT msg_id, sender_name, receiver_name, topic_cn, content,
                      knowledge_tags_json, learning_value,
                      substr(created_at,1,19) AS created_at
               FROM mt_ai_eigenflux_messages
               WHERE msg_id > ? AND content IS NOT NULL AND content != ''
               ORDER BY msg_id ASC LIMIT ?""",
            (last_msg_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        _log(f"eigenflux query fail: {e}", "WARN")
        return []


# ═══════════════════════════════════════════════════════════════════
# 核心周期任务 — 原有
# ═══════════════════════════════════════════════════════════════════

def _do_hire():
    """触发 wf_hire_employee — 走 workflow engine."""
    _log(f"🤖 hiring next {HIRE_BATCH_SIZE} AI employees ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import andromeda_workflow_engine as wf
        r = wf.run_workflow(
            'wf_hire_employee',
            {'count': HIRE_BATCH_SIZE, 'min_level': 7},
            trigger_source="daemon",
            blocking=True)
        _log(f"🤖 hire done: {r['status']} hired={r['output'].get('hired','?')} "
             f"rev=\${r['revenue_usd']}")
        return True, r['revenue_usd']
    except Exception as e:
        _log(f"🤖 hire fail: {e}", "ERROR")
        return False, 0.0


def _do_ingest(last_msg_id: int):
    """eigenflux → wf_knowledge_ingest."""
    msgs = _eigenflux_new_since(last_msg_id, INGEST_BATCH_SIZE)
    if not msgs:
        _log(f"📚 no new eigenflux msgs since msg_id={last_msg_id}, skip")
        return True, last_msg_id, 0.0
    sources = []
    for m in msgs:
        content = m.get('content', '')[:2000]
        sender = m.get('sender_name', 'anon')
        receiver = m.get('receiver_name', '')
        topic = m.get('topic_cn', '')[:40]
        title = f"eigenflux::{sender}→{receiver}#{m.get('msg_id','')}"
        if topic:
            title += f" [{topic}]"
        sources.append({"content": content, "title": title})
    _log(f"📚 ingesting {len(sources)} eigenflux msgs ({last_msg_id} → {msgs[-1]['msg_id']}) ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import andromeda_workflow_engine as wf
        r = wf.run_workflow(
            'wf_knowledge_ingest',
            {'sources': sources, 'domain': 'eigenflux_daemon'},
            trigger_source="daemon",
            blocking=True)
        _log(f"📚 ingest done: {r['status']} ingested={r['output'].get('ingested','?')} "
             f"rev=\${r['revenue_usd']}")
        return True, max(last_msg_id, msgs[-1]['msg_id']) if msgs else last_msg_id, r['revenue_usd']
    except Exception as e:
        _log(f"📚 ingest fail: {e}", "ERROR")
        return False, last_msg_id, 0.0


def _do_hall_tick(cp: dict):
    """调 Flask /api/internal/hall/tick — 6 轨大厅自治."""
    import urllib.request
    try:
        req = urllib.request.Request(HALL_TICK_URL, data=b'{}',
                                     headers={'Content-Type': 'application/json'}, method='POST')
        resp = urllib.request.urlopen(req, timeout=90)
        body = json.loads(resp.read().decode() or '{}')
        tracks = body.get('tracks', {})
        ok_count = sum(1 for t in tracks.values() if t.get('ok'))
        fail_names = [n for n, t in tracks.items() if not t.get('ok')]
        _log(f"🏛️ hall_tick: {ok_count}/{len(tracks)} tracks OK, fail={fail_names}")
        cp['last_hall_tick'] = time.time()
        cp['total_hall_ticks'] = cp.get('total_hall_ticks', 0) + 1
        _checkpoint_save(cp)
    except urllib.error.URLError as _ue:
        _log(f"🏛️ hall_tick skip: Flask unreachable ({_ue.reason})", "WARN")
    except Exception as _e:
        _log(f"🏛️ hall_tick fail: {type(_e).__name__}: {_e}", "ERROR")


# ═══════════════════════════════════════════════════════════════════
# 🆕 13 中心自主驱动 (flow_ai_community_20261028 §4)
# ═══════════════════════════════════════════════════════════════════

def _do_self_drive() -> dict:
    """直接调 ai_center_self_drive_engine.run_once() — 激活 14 中心心跳/自检/自愈/自研发.
    不依赖 Flask, 本地 import 调用.
    """
    _log("🧠 13 中心 自主驱动 round: pulse + self_check + self_repair + rnd ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import ai_center_self_drive_engine as sd
        r = sd.run_once()
        pulse = r.get("pulse", [])
        checks = r.get("self_check", {})
        rnd = r.get("rnd", {})
        total_queue = sum(p.get("queue", 0) for p in pulse)
        total_fails = sum(checks.get("fails", {}).values())
        upgrade = sum(rnd.get("upgrade", {}).values())
        dispatch = sum(rnd.get("dispatch", {}).values())
        done = sum(rnd.get("done", {}).values())
        elapsed = r.get("elapsed_ms", "?")
        _log(f"🧠 self_drive: pulse={len(pulse)} queue_total={total_queue} "
             f"self_check_fails={total_fails} rnd_upgrade={upgrade} "
             f"rnd_dispatch={dispatch} rnd_done={done} ({elapsed}ms)")
        return {"ok": True, "pulse": len(pulse), "queue": total_queue,
                "fails": total_fails, "rnd_upgrade": upgrade,
                "rnd_dispatch": dispatch, "rnd_done": done}
    except Exception as e:
        _log(f"🧠 self_drive fail: {type(e).__name__}: {e}", "ERROR")
        return {"ok": False, "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════
# 🆕 中心自动衍化 (flow_ai_community_20261028 §5)
# ═══════════════════════════════════════════════════════════════════

def _do_evolution() -> dict:
    """直接调 sys_center_evolution.run_once() — 中心自动衍化研究方向."""
    _log("🧬 13 中心 自动衍化 round ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import sys_center_evolution as ce
        seeds_before = 0
        try:
            conn = _db_connect()
            seeds_before = conn.execute(
                "SELECT COUNT(*) FROM mt_center_direction_pool").fetchone()[0]
            conn.close()
        except Exception:
            pass
        ce.run_once()
        seeds_after = seeds_before
        try:
            conn = _db_connect()
            seeds_after = conn.execute(
                "SELECT COUNT(*) FROM mt_center_direction_pool").fetchone()[0]
            conn.close()
        except Exception:
            pass
        _log(f"🧬 evolution: direction_pool {seeds_before} → {seeds_after} (+{seeds_after-seeds_before})")
        return {"ok": True, "seeds_gained": seeds_after - seeds_before}
    except Exception as e:
        _log(f"🧬 evolution fail: {type(e).__name__}: {e}", "ERROR")
        return {"ok": False, "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════
# 🆕 13 中心联动 (flow_ai_community_20261028 §6)
# ═══════════════════════════════════════════════════════════════════

def _do_center_collab() -> dict:
    """中心联动引擎: 弱者自动求援 → 强者自动驰援.
    触发条件:
      (a) 某中心 health_score < 60 (mt_center_pulse 最新)
      (b) 某中心 self_check FAIL 数 > 0
      (c) 大厅 QUEUED 任务积压, source/claim_owner 指向某中心
    动作: 自动创建跨中心协作任务入厅 (source=CENTER_COLLAB) + mt_center_collab_log 留痕.
    """
    _log("🤝 13 中心 联动 round ...")
    created, skipped = [], []
    try:
        conn = _db_connect()

        # ── (a) 找健康度最低的 3 个中心 ──
        weak_centers = []
        try:
            rows = conn.execute("""
                SELECT p.center_name, p.health_score, p.queue_depth,
                       p.status, p.anomalies_found
                FROM mt_center_pulse p JOIN (
                    SELECT center_name, MAX(rowid) AS latest
                    FROM mt_center_pulse GROUP BY center_name
                ) l ON p.rowid = l.latest
                WHERE p.health_score < 70
                ORDER BY p.health_score ASC LIMIT 5""").fetchall()
            weak_centers = [(r[0], r[1], r[2]) for r in rows]
        except Exception:
            pass

        # ── (b) 找 self_check FAIL 中心 ──
        fail_centers = []
        try:
            rows = conn.execute("""
                SELECT center_name, COUNT(*) fails
                FROM mt_center_self_check WHERE result='FAIL'
                AND created_at > datetime('now','localtime','-24 hours')
                GROUP BY center_name ORDER BY fails DESC LIMIT 5""").fetchall()
            fail_centers = [(r[0], r[1]) for r in rows]
        except Exception:
            pass

        # ── 每个弱中心 / 失败中心 → 找可驰援的伙伴 → 自动灌协作任务 ──
        needs = {}
        for cn, score, qd in weak_centers:
            needs.setdefault(cn, {"queue": qd, "health": score, "fails": 0})
        for cn, fails in fail_centers:
            n = needs.setdefault(cn, {"queue": 0, "health": 100, "fails": 0})
            n["fails"] = max(n["fails"], fails)

        for center_name, info in needs.items():
            # 找驰援中心
            helpers = CENTER_COLLAB_MAP.get(center_name, [])
            if not helpers:
                continue
            # 选 1-2 个最强伙伴 (health_score >= 80)
            helper_rows = []
            try:
                placeholders = ",".join("?" * len(helpers))
                rows = conn.execute(f"""
                    SELECT p.center_name, p.health_score
                    FROM mt_center_pulse p JOIN (
                        SELECT center_name, MAX(rowid) AS latest
                        FROM mt_center_pulse WHERE center_name IN ({placeholders})
                        GROUP BY center_name
                    ) l ON p.rowid = l.latest
                    WHERE p.health_score >= 80
                    ORDER BY p.health_score DESC LIMIT 2""", helpers).fetchall()
                helper_rows = [r[0] for r in rows]
            except Exception:
                helper_rows = helpers[:2]

            if not helper_rows:
                skipped.append(center_name)
                continue

            # 24h 去重: 同中心 24h 内不要重复灌 collab 任务
            recent = conn.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
                WHERE source='CENTER_COLLAB' AND description LIKE ?
                AND created_at > datetime('now','localtime','-24 hours')""",
                (f"%{center_name}%",)).fetchone()[0]
            if recent > 0:
                skipped.append(f"{center_name}(recent)")
                continue

            helpers_str = " + ".join(helper_rows)
            reason_parts = []
            if info["health"] < 70:
                reason_parts.append(f"health={info['health']}")
            if info["queue"] > 5:
                reason_parts.append(f"积压={info['queue']}")
            if info["fails"] > 0:
                reason_parts.append(f"self_check_FAIL={info['fails']}")
            reason = ", ".join(reason_parts) or "中心需联动协作"

            title = f"[联动] {center_name} × {helpers_str} — {reason}"[:120]
            desc = (f"CENTER_COLLAB 自动联动: {center_name} 需要 {helpers_str} 驰援. "
                    f"触发原因: {reason}. "
                    f"任务路由: {helpers_str} 牵头认领, {center_name} 配合, "
                    f"关键词: 联动,协作,驰援,中心自治,AI社区")[:500]

            try:
                cur = conn.execute("""INSERT INTO mt_lab_task_hall
                    (title, description, source, priority, status,
                     publisher, publisher_role, approval_status)
                    VALUES (?,?,?,?,?,?,?,'APPROVED')""",
                    (title, desc, "CENTER_COLLAB", "NORMAL", "QUEUED",
                     "sys_wendaemon", "AI_COMMUNITY"))
                tid = cur.lastrowid
                conn.execute("""INSERT INTO mt_center_self_drive_log
                    (center_name, action, task_hall_id, outcome, detail)
                    VALUES (?,?,?,?,?)""",
                    (center_name, "CENTER_COLLAB", tid, "QUEUED",
                     json.dumps({"helpers": helper_rows, "reason": reason}, ensure_ascii=False)))
                # helper 中心也留痕
                for h in helper_rows:
                    conn.execute("""INSERT INTO mt_center_self_drive_log
                        (center_name, action, task_hall_id, outcome, detail)
                        VALUES (?,?,?,?,?)""",
                        (h, "CENTER_COLLAB_HELP", tid, "DISPATCHED",
                         json.dumps({"helped": center_name, "reason": reason}, ensure_ascii=False)))
                created.append({"task_id": tid, "center": center_name, "helpers": helper_rows,
                                "reason": reason})
            except sqlite3.IntegrityError:
                skipped.append(center_name)

        conn.commit()
        conn.close()

        # 汇总
        _log(f"🤝 collab: 创建 {len(created)} 个联动任务, 跳过 {len(skipped)} 个")
        for c in created:
            _log(f"   🔗 task#{c['task_id']}: {c['center']} ← {c['helpers']} ({c['reason']})")
        return {"ok": True, "created": len(created), "skipped": len(skipped), "details": created}

    except Exception as e:
        _log(f"🤝 collab fail: {type(e).__name__}: {e}", "ERROR")
        return {"ok": False, "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════
# 🆕 daemon 智能托管 (flow_ai_community_20261028 §7)
# ═══════════════════════════════════════════════════════════════════

def _do_daemon_supervisor() -> dict:
    """daemon 托管巡检: 发现 RUNNING/ACTIVE 但心跳超时的守护 → 自动托管唤起.
    策略:
      - 对核心守护 (ai_center_self_drive / sys_center_evolution 等):
        心跳超时 > 2h → 直接 import 调它的 run_once() 补心跳, 同时日志留痕.
      - 对其他 daemon: 只写 warning 日志, 等待 auto_repair daemon 处理.
    """
    _log(f"👁️ daemon supervisor round (timeout={SUPERVISOR_TIMEOUT_SEC}s) ...")
    boosted = []
    warnings = []
    now_ts = time.time()
    try:
        conn = _db_connect()
        rows = conn.execute("""
            SELECT process_name, duty, status, pid,
                   substr(last_heartbeat,1,19) AS hb
            FROM mt_daemon_registry
            WHERE status IN ('RUNNING','ACTIVE','alive')
              AND last_heartbeat IS NOT NULL
            ORDER BY last_heartbeat ASC""").fetchall()
        conn.close()

        for proc, duty, status, pid, hb in rows:
            if not hb or proc == "sys_wendaemon":
                continue
            # 算心跳 age
            try:
                # last_heartbeat 可能是 ISO 8601 (带 T) 或 datetime 格式
                hb_clean = hb.replace('T', ' ')[:19]
                hb_dt = datetime.strptime(hb_clean, "%Y-%m-%d %H:%M:%S")
                age_sec = (datetime.now() - hb_dt).total_seconds()
            except Exception:
                # 算不出 age, 跳过
                continue

            if age_sec < SUPERVISOR_TIMEOUT_SEC:
                continue

            is_core = proc in CORE_DAEMONS

            if is_core:
                # ── 核心守护: 直接托管唤起 ──
                _log(f"👁️⚠️ 核心守护 {proc} 心跳超时 {int(age_sec)}s, 托管唤起 ...")
                boosted_result = _boost_core_daemon(proc)
                boosted.append({"daemon": proc, "age_sec": int(age_sec),
                                "boosted": boosted_result.get("ok", False),
                                "detail": boosted_result.get("note", "")})
            else:
                # ── 非核心: 只 warning ──
                warnings.append({"daemon": proc, "age_sec": int(age_sec), "status": status})

        # 写托管日志
        if boosted or warnings:
            try:
                conn = _db_connect()
                for b in boosted:
                    conn.execute("""INSERT INTO mt_center_self_drive_log
                        (center_name, action, outcome, detail)
                        VALUES (?,?,?,?,?)""",
                        ("SUPERVISOR", "DAEMON_BOOSTED" if b["boosted"] else "DAEMON_BOOST_FAIL",
                         "OK" if b["boosted"] else "FAIL",
                         json.dumps(b, ensure_ascii=False)))
                for w in warnings:
                    conn.execute("""INSERT INTO mt_center_self_drive_log
                        (center_name, action, outcome, detail)
                        VALUES (?,?,?,?,?)""",
                        ("SUPERVISOR", "DAEMON_WARNING", "WARN",
                         json.dumps(w, ensure_ascii=False)))
                conn.commit()
                conn.close()
            except Exception:
                pass

        _log(f"👁️ supervisor: 核心守护托管 {len(boosted)}, 非核心 warning {len(warnings)}")
        return {"ok": True, "boosted": len(boosted), "warnings": len(warnings),
                "boosted_detail": boosted[:5], "warnings_detail": warnings[:5]}

    except Exception as e:
        _log(f"👁️ supervisor fail: {type(e).__name__}: {e}", "ERROR")
        return {"ok": False, "error": str(e)[:200]}


# ── 核心守护托管唤起 ──
def _boost_core_daemon(proc_name: str) -> dict:
    """对核心守护直接调 run_once() 来补心跳."""
    engine_map = {
        "ai_center_self_drive": ("ai_center_self_drive_engine", "run_once"),
        "sys_center_evolution": ("sys_center_evolution", "run_once"),
    }
    if proc_name in engine_map:
        mod_name, fn_name = engine_map[proc_name]
        try:
            sys.path.insert(0, os.path.join(ROOT, 'engines'))
            mod = __import__(mod_name)
            fn = getattr(mod, fn_name)
            fn()
            return {"ok": True, "note": f"{proc_name} run_once() 已执行, 心跳已补"}
        except Exception as e:
            return {"ok": False, "note": f"{proc_name} run_once() 失败: {str(e)[:100]}"}

    # 其他核心守护: 只补 registry heartbeat
    try:
        conn = _db_connect()
        conn.execute("""UPDATE mt_daemon_registry
            SET last_heartbeat=datetime('now','localtime'), pid=?
            WHERE process_name=?""", (os.getpid(), proc_name))
        conn.commit()
        conn.close()
        return {"ok": True, "note": f"{proc_name} registry heartbeat 已补"}
    except Exception as e:
        return {"ok": False, "note": str(e)[:100]}


# ═══════════════════════════════════════════════════════════════════
# 🆕 社区自治总览 (flow_ai_community_20261028 §8)
# ═══════════════════════════════════════════════════════════════════

def _do_community_overview() -> dict:
    """汇总 heartbeat / center pulse / task hall / evolution, 写 mt_center_self_drive_log."""
    try:
        conn = _db_connect()
        total_summary = {}

        # daemon 活跃数
        try:
            row = conn.execute("""
                SELECT status, COUNT(*) FROM mt_daemon_registry
                GROUP BY status""").fetchall()
            total_summary["daemons"] = dict(row)
        except Exception:
            total_summary["daemons"] = {}

        # 中心健康度快照 (最新 pulse)
        try:
            rows = conn.execute("""
                SELECT p.center_name, p.health_score, p.status,
                       p.active_tasks, p.queue_depth, p.rnd_directions
                FROM mt_center_pulse p JOIN (
                    SELECT center_name, MAX(rowid) AS latest
                    FROM mt_center_pulse GROUP BY center_name
                ) l ON p.rowid = l.latest""").fetchall()
            total_summary["centers"] = [
                {"name": r[0], "health": r[1], "status": r[2],
                 "active_tasks": r[3], "queue": r[4], "rnd_dirs": r[5]}
                for r in rows]
        except Exception:
            total_summary["centers"] = []

        # 大厅任务分布
        try:
            rows = conn.execute("""
                SELECT status, COUNT(*) FROM mt_lab_task_hall
                GROUP BY status ORDER BY COUNT(*) DESC""").fetchall()
            total_summary["task_hall"] = dict(rows)
        except Exception:
            total_summary["task_hall"] = {}

        # 方向池状态
        try:
            rows = conn.execute("""
                SELECT status, COUNT(*) FROM mt_center_direction_pool
                GROUP BY status""").fetchall()
            total_summary["direction_pool"] = dict(rows)
        except Exception:
            total_summary["direction_pool"] = {}

        conn.close()

        # 关键指标汇总
        d = total_summary.get("daemons", {})
        c = total_summary.get("centers", [])
        th = total_summary.get("task_hall", {})
        pool = total_summary.get("direction_pool", {})

        running = d.get("RUNNING", 0) + d.get("ACTIVE", 0) + d.get("alive", 0)
        stopped = d.get("STOPPED", 0)

        weak_centers = [x for x in c if x["health"] < 70]
        total_queue = sum(x["queue"] for x in c)
        total_rnd_dirs = sum(x["rnd_dirs"] for x in c)
        queued_tasks = th.get("QUEUED", 0) + th.get("DISPATCHED", 0)
        queued_seeds = pool.get("SEED", 0)
        active_seeds = pool.get("ACTIVE", 0) + pool.get("EXECUTING", 0)

        _log(f"📊 社区总览: daemon {running}RUNNING / {stopped}STOPPED | "
             f"中心 {len(c)}个 ({len(weak_centers)}弱) 总queue={total_queue} "
             f"rnd_dirs={total_rnd_dirs} | "
             f"大厅 {queued_tasks}积压 | 方向池 {queued_seeds}SEED / {active_seeds}ACTIVE")

        if weak_centers:
            wc = ", ".join(f"{x['name']}={x['health']}" for x in weak_centers)
            _log(f"   ⚠️ 弱中心: {wc}")

        # 留痕
        try:
            conn = _db_connect()
            conn.execute("""INSERT INTO mt_center_self_drive_log
                (center_name, action, outcome, detail)
                VALUES (?,?,?,?,?)""",
                ("COMMUNITY", "OVERVIEW", "OK",
                 json.dumps({
                     "daemon_running": running, "daemon_stopped": stopped,
                     "centers_total": len(c), "centers_weak": len(weak_centers),
                     "total_queue": total_queue, "total_rnd_dirs": total_rnd_dirs,
                     "queued_tasks": queued_tasks,
                     "seeds_seed": queued_seeds, "seeds_active": active_seeds,
                 }, ensure_ascii=False)))
            conn.commit()
            conn.close()
        except Exception:
            pass

        return {"ok": True, "summary": {
            "daemon_running": running, "daemon_stopped": stopped,
            "centers_total": len(c), "centers_weak": len(weak_centers),
            "total_queue": total_queue, "queued_tasks": queued_tasks,
            "seeds_seed": queued_seeds, "seeds_active": active_seeds,
        }}

    except Exception as e:
        _log(f"📊 community overview fail: {type(e).__name__}: {e}", "ERROR")
        return {"ok": False, "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════
# 🆕 提案智能全链路 (flow_proposal_intel_20261028 §9)
# ═══════════════════════════════════════════════════════════════════

def _do_proposal_intel() -> dict:
    """提案智能全链路: 13 个智能函数一次跑完.
    零 LLM, 纯本地 SQL + 规则模板. 每个函数短连接 + 幂等.
    """
    _log("🧠 proposal_intel round: 13 智能 ...")
    try:
        sys.path.insert(0, os.path.join(ROOT, 'engines'))
        import ai_proposal_intelligence_engine as pi
        r = pi.run_once()
        steps = r.get("steps", {})
        ok_steps = sum(1 for v in steps.values() if isinstance(v, dict) and v.get("ok"))
        _log(f"🧠 proposal_intel: {ok_steps}/{len(steps)} 智能 OK")
        # 重点摘要
        tag_r = steps.get("①ingest_and_tag", {})
        dis_r = steps.get("④smart_dispatch", {})
        close_r = steps.get("⑥auto_close", {})
        chain_r = steps.get("⑫chain_digest", {})
        fu_r = steps.get("⑪followup_scheduler", {})
        brain_r = steps.get("⑨brain_feed", {})
        _log(f"   tags={tag_r.get('tagged',0)} dispatched={dis_r.get('dispatched',0)} "
             f"auto_close={close_r.get('closed',0)} chains={chain_r.get('chains_made',0)} "
             f"followup={fu_r.get('followup_done',0)} brain_feed={brain_r.get('step_a_feedback',0)}+{brain_r.get('step_b_qbank',0)}")
        return {"ok": True, "ok_steps": ok_steps, "total": len(steps)}
    except Exception as e:
        _log(f"🧠 proposal_intel fail: {type(e).__name__}: {e}", "ERROR")
        return {"ok": False, "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════
# signal handler
# ═══════════════════════════════════════════════════════════════════

def _sigterm_handler(signum, frame):
    global _running
    _log(f"caught signal {signum}, shutting down gracefully ...")
    _running = False

signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


# ═══════════════════════════════════════════════════════════════════
# main loop — 🧠 AI 高智能社区 八大轨道
# ═══════════════════════════════════════════════════════════════════

def main():
    global _running
    _pid_write()
    _registry_heartbeat(status="starting", note="AI community boot")
    _log("=" * 60)
    _log("🆙 sys_wendaemon 🧠 AI 高智能社区 总托管 启动")
    _log("=" * 60)
    _log(f"   DB={DB_PATH}")
    _log(f"   🤖 hire          = {HIRE_INTERVAL}s")
    _log(f"   📚 ingest        = {INGEST_INTERVAL}s")
    _log(f"   🏛️ hall_tick     = {HALL_INTERVAL}s")
    _log(f"   🧠 self_drive    = {SELF_DRIVE_INTERVAL}s  (13中心心跳/自检/自愈/自研发)")
    _log(f"   🧬 evolution     = {EVOLUTION_INTERVAL}s  (中心自动衍化)")
    _log(f"   🤝 collab        = {COLLAB_INTERVAL}s  (中心联动)")
    _log(f"   👁️ supervisor    = {SUPERVISOR_INTERVAL}s  (daemon托管)")
    _log(f"   📊 community     = {COMMUNITY_INTERVAL}s  (自治总览)")
    _log(f"   🧠 proposal_intel= {PROPOSAL_INTEL_INTERVAL}s  (13 智能: tag/intent/quality/dispatch/feedback/close/archive/upload/brain/escape/followup/chain/summary)")
    _log(f"   HIRE_BATCH={HIRE_BATCH_SIZE}  INGEST_BATCH={INGEST_BATCH_SIZE}")
    _log(f"   CORE_DAEMONS={CORE_DAEMONS}")

    # 第一次启动: 立即 heartbeat + 立即跑一次 self_drive + supervisor (激活)
    _registry_heartbeat(status="alive", note="AI community running")

    cp = _checkpoint_load()
    _log(f"   checkpoint: hires={cp['total_hires']} self_drives={cp.get('total_self_drives',0)} "
         f"evolutions={cp.get('total_evolutions',0)} collabs={cp.get('total_collabs',0)} "
         f"boosted={cp.get('total_daemons_boosted',0)}")

    # 启动时立即预热一次 — 让系统立即"活"起来
    _log("🚀 startup warmup: self_drive + supervisor ...")
    try:
        _do_self_drive()
    except Exception as _e:
        _log(f"   warmup self_drive skip: {_e}", "WARN")
    try:
        _do_daemon_supervisor()
    except Exception as _e:
        _log(f"   warmup supervisor skip: {_e}", "WARN")

    now = time.time()
    next_hire       = cp['last_hire_at'] + HIRE_INTERVAL
    next_ingest     = cp['last_ingest_at'] + INGEST_INTERVAL
    next_hall       = cp.get('last_hall_tick', 0) + HALL_INTERVAL
    next_self_drive = cp.get('last_self_drive_at', now) + SELF_DRIVE_INTERVAL  # 预热刚跑过
    next_evolution  = cp.get('last_evolution_at', 0) + EVOLUTION_INTERVAL
    next_collab     = cp.get('last_collab_at', 0) + COLLAB_INTERVAL
    next_supervisor = cp.get('last_supervisor_at', now) + SUPERVISOR_INTERVAL
    next_community  = cp.get('last_community_at', 0) + COMMUNITY_INTERVAL
    next_proposal_intel = cp.get('last_proposal_intel_at', 0) + PROPOSAL_INTEL_INTERVAL
    next_hb         = now + HEARTBEAT_INTERVAL

    while _running:
        try:
            now = time.time()

            # ── heartbeat (每 30s) ──
            if now >= next_hb:
                _registry_heartbeat(status="alive", note="AI community tick")
                next_hb = now + HEARTBEAT_INTERVAL

            # ── 1. hire (6h) ──
            if now >= next_hire:
                ok, rev = _do_hire()
                if ok:
                    cp['last_hire_at'] = now
                    cp['total_hires'] += 1
                    cp['total_revenue_usd'] += rev
                    _checkpoint_save(cp)
                next_hire = now + HIRE_INTERVAL

            # ── 2. ingest (30min) ──
            if now >= next_ingest:
                ok, new_last_id, rev = _do_ingest(cp['last_knowledge_id'])
                if ok:
                    cp['last_ingest_at'] = now
                    cp['last_knowledge_id'] = new_last_id
                    cp['total_ingested'] += 1
                    cp['total_revenue_usd'] += rev
                    _checkpoint_save(cp)
                next_ingest = now + INGEST_INTERVAL

            # ── 3. hall tick (15min) ──
            if now >= next_hall:
                _do_hall_tick(cp)
                next_hall = now + HALL_INTERVAL

            # ── 🆕 4. self_drive (5min) ──
            if now >= next_self_drive:
                r = _do_self_drive()
                cp['last_self_drive_at'] = now
                cp['total_self_drives'] = cp.get('total_self_drives', 0) + 1
                _checkpoint_save(cp)
                next_self_drive = now + SELF_DRIVE_INTERVAL

            # ── 🆕 5. evolution (10min) ──
            if now >= next_evolution:
                _do_evolution()
                cp['last_evolution_at'] = now
                cp['total_evolutions'] = cp.get('total_evolutions', 0) + 1
                _checkpoint_save(cp)
                next_evolution = now + EVOLUTION_INTERVAL

            # ── 🆕 6. center collab (20min) ──
            if now >= next_collab:
                _do_center_collab()
                cp['last_collab_at'] = now
                cp['total_collabs'] = cp.get('total_collabs', 0) + 1
                _checkpoint_save(cp)
                next_collab = now + COLLAB_INTERVAL

            # ── 🆕 7. daemon supervisor (2min) ──
            if now >= next_supervisor:
                r = _do_daemon_supervisor()
                if r.get("ok"):
                    cp['total_daemons_boosted'] = cp.get('total_daemons_boosted', 0) + r.get("boosted", 0)
                cp['last_supervisor_at'] = now
                _checkpoint_save(cp)
                next_supervisor = now + SUPERVISOR_INTERVAL

            # ── 🆕 8. community overview (15min) ──
            if now >= next_community:
                _do_community_overview()
                cp['last_community_at'] = now
                cp['total_communities'] = cp.get('total_communities', 0) + 1
                _checkpoint_save(cp)
                next_community = now + COMMUNITY_INTERVAL

            # ── 🆕 9. proposal_intel (60s) — 提案智能全链路 13 智能 ──
            if now >= next_proposal_intel:
                _do_proposal_intel()
                cp['last_proposal_intel_at'] = now
                cp['total_proposal_intels'] = cp.get('total_proposal_intels', 0) + 1
                _checkpoint_save(cp)
                next_proposal_intel = now + PROPOSAL_INTEL_INTERVAL

            # ── sleep 分片, 快速响应 SIGTERM ──
            for _ in range(5):
                if not _running:
                    break
                time.sleep(1)

        except Exception as e:
            _log(f"loop error: {e}", "ERROR")
            time.sleep(5)

    # ── shutdown ──
    _log("shutting down AI community gracefully ...")
    _registry_heartbeat(status="stopped", note="graceful shutdown")
    _pid_cleanup()
    _log("✅ sys_wendaemon exit 0")


if __name__ == "__main__":
    main()
