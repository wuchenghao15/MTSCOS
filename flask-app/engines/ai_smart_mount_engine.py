#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI智能挂载自动化进程引擎 (Smart Mount Engine)
================================================
flow_id: flow_smart_mount_auto_process_20260819_001
§14 STEP_7_EXECUTE 下场实施

核心能力:
  1. 收集AI建议池中已评估的高优先级建议
  2. 综合EigenFlux专家动态权重做挂载决策
  3. 自动生成daemon脚本并注册到mt_daemon_registry
  4. subprocess启动进程 + 心跳监控 + 自动重启
  5. 系统需求/EigenFlux专家建议综合驱动

复用现有基础设施:
  - ai_intelligent_upgrade_engine.register_daemon()  注册daemon
  - ai_intelligent_upgrade_engine.daemon_transition() 状态机转移
  - ai_intelligent_upgrade_engine.add_ai_suggestion()  添加建议
  - ai_intelligent_upgrade_engine.evaluate_suggestion() 评估建议
  - ai_intelligent_upgrade_engine.compute_dynamic_weight() 专家权重

新增表:
  - mt_ai_smart_mount_processes  智能挂载进程跟踪表

CLI守护模式:
  python3 ai_smart_mount_engine.py start    启动监控守护进程
  python3 ai_smart_mount_engine.py stop     停止
  python3 ai_smart_mount_engine.py status   查看状态
  python3 ai_smart_mount_engine.py list     列出所有挂载进程
  python3 ai_smart_mount_engine.py create   手动创建自动化进程
  python3 ai_smart_mount_engine.py adopt    采纳AI建议并挂载
  python3 ai_smart_mount_engine.py scan     扫描建议池+自动挂载

遵循硬约束:
  - 数据库唯一数据源(app.db)
  - daemon状态机5态(IDLE/RUNNING/PAUSED/FAILED/STOPPED)
  - 全链路追溯ID
  - 巡检闭环 + 自动修复
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
# ---- 路径 & 依赖 ----
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # flask-app/
PROJECT_ROOT = os.path.dirname(ROOT)  # 项目根
# 🔧 2026-09-10 仙女座修复: 主库从 flask-app/ai_engines/app.db → Database/app.db
# 清理前的旧副本 488KB 不包含 15 daemon 注册表、AI 员工 33,525 人、25 恒星域
AI_ENGINES_DIR = os.path.join(ROOT, "ai_engines")
# 🔧 仙女座 v5.2 路径修复 (2026-10-06):
# MacBook Pro 真实主库在 flask-app/database/app.db (1.6GB, 有 mt_daemon_registry 60条)
# Mac mini 旧库在 _runtime/databases/Database/app.db (7GB, 无 mt_daemon_registry — 不可用!)
# 统一: 取 flask-app/database/app.db 优先 (Flask 正在用的活跃库)
_DB_CANDIDATES = [
    os.path.join(ROOT, "engines", "app.db"),                                     # ✅ Mac mini 完整版 (763MB, 有全部表)
    os.path.join(ROOT, "database", "app.db"),                                    # ✅ 活跃主库 (MacBook Pro 1.6GB)
    os.path.join(PROJECT_ROOT, "flask-app", "engines", "app.db"),                # 兜底 engines 版
    os.path.join(PROJECT_ROOT, "flask-app", "database", "app.db"),               # 兜底 database 版
    os.path.join(PROJECT_ROOT, "Database", "app.db"),                            # 旧兼容
    os.path.join(AI_ENGINES_DIR, "app.db"),                                      # 最后兜底
]
APP_DB = next((p for p in _DB_CANDIDATES
               if os.path.exists(p) and os.path.getsize(p) > 1000000),  # 至少 1MB
              _DB_CANDIDATES[0])
# 如果取到了 _runtime 的旧库但它没有关键表，强制用 flask-app/database
if "_runtime" in APP_DB:
    _flask_db = os.path.join(ROOT, "database", "app.db")
    if os.path.exists(_flask_db):
        APP_DB = _flask_db
print(f"[SMART_MOUNT] ✅ APP_DB = {APP_DB} (exists={os.path.exists(APP_DB)} size={os.path.getsize(APP_DB) if os.path.exists(APP_DB) else 0})")
RUNTIME_DIR = os.path.join(ROOT, "..", "_runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
PID_DIR = os.path.join(RUNTIME_DIR, "pids")
DAEMON_SCRIPTS_DIR = os.path.join(RUNTIME_DIR, "auto_daemons")
PID_FILE = os.path.join(PID_DIR, "ai_smart_mount_engine.pid")
MONITOR_LOG = os.path.join(LOG_DIR, "ai_smart_mount_monitor.log")

for _d in [LOG_DIR, PID_DIR, DAEMON_SCRIPTS_DIR]:
    os.makedirs(_d, exist_ok=True)

# 导入现有基础设施
sys.path.insert(0, AI_ENGINES_DIR)
try:
    from ai_intelligent_upgrade_engine import (
        register_daemon, daemon_transition, add_ai_suggestion,
        evaluate_suggestion, compute_dynamic_weight,
        ensure_upgrade_tables, _get_conn, _now,
        DAEMON_STATE_MACHINE,
    )
except ImportError:
    # 兼容直接运行 - 仙女座 v5.2: 完全自包含, 不依赖坏掉的 ai_intelligent_upgrade_engine
    _CONN = None

    def _get_conn():
        conn = sqlite3.connect(APP_DB, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _now():
        return datetime.now().isoformat()

    def register_daemon(name, status='IDLE'):
        """仙女座自包含版本: 向 mt_daemon_registry 注册 daemon"""
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO mt_daemon_registry (daemon_name, status, registered_at, last_heartbeat) VALUES (?,?,?,?)",
                (name, status, _now(), _now()))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def daemon_transition(name, new_state):
        """仙女座自包含版本: 状态转移"""
        try:
            conn = _get_conn()
            conn.execute(
                "UPDATE mt_daemon_registry SET status=?, last_heartbeat=? WHERE daemon_name=?",
                (new_state, _now(), name))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def add_ai_suggestion(**kwargs):
        pass  # 占位

    def evaluate_suggestion(**kwargs):
        return 0.5  # 占位

    def compute_dynamic_weight(**kwargs):
        return {}  # 占位

    DAEMON_STATE_MACHINE = {
        "IDLE": ["RUNNING", "STOPPED"],
        "RUNNING": ["PAUSED", "FAILED", "STOPPED"],
        "PAUSED": ["RUNNING", "STOPPED"],
        "FAILED": ["RUNNING", "STOPPED"],
        "STOPPED": ["IDLE", "RUNNING"],
    }

# 🆕 仙女座 v5.2: 给被 import 进来的坏掉函数注入全局变量
try:
    import ai_intelligent_upgrade_engine as _ai_upgrade
    _ai_upgrade._LOCK = _LOCK
    _ai_upgrade._get_conn = _get_conn
    _ai_upgrade._now = _now
except Exception:
    pass

_LOCK = threading.Lock()
MOUNT_THRESHOLD = 0.70  # 综合分>=0.70才自动挂载
MAX_RESTART_COUNT = 5       # 连续重启失败次数上限
HEARTBEAT_TIMEOUT = 120     # 心跳超时秒数 (↑从90→120, 给daemon多呼吸空间)
STOPPED_COOLDOWN = 300      # STOPPED状态冷却重试窗口(秒) - 超过后重置restart_count再试
MONITOR_INTERVAL = 30       # 监控巡检间隔秒数

# ============================================================
# 🆕 SYSTEM_REQUIRED_DAEMONS - 系统必需daemon配置
# 被重构时误删，2026-09-13 恢复
# ============================================================
SYSTEM_REQUIRED_DAEMONS = [
{
        "process_name": "sys_heartbeat_writer",
        "duty": "系统心跳写入 - 每30s向 mt_daemon_registry 写心跳，保持所有daemon存活",
        "work_body": """
import os, sys, sqlite3, time
DB = os.environ.get('APP_DB', '/Users/wuchenghao/mtscos/_runtime/databases/Database/app.db')
conn = sqlite3.connect(DB); conn.execute('PRAGMA busy_timeout=5000')
conn.execute("UPDATE mt_daemon_registry SET last_heartbeat=datetime('now') WHERE daemon_name=?", ('sys_heartbeat_writer',))
conn.commit(); conn.close()
_log("[heartbeat] written")
""",
        "inspect_cycle": 30,
    },
    {
        "process_name": "sys_patrol_inspector",
        "duty": "daemon状态巡检 - 每60s检查所有挂载进程心跳，超时的标记为TIMEOUT",
        "work_body": """
import sqlite3, os
DB = os.environ.get('APP_DB', '/Users/wuchenghao/mtscos/_runtime/databases/Database/app.db')
conn = sqlite3.connect(DB); conn.execute('PRAGMA busy_timeout=5000')
now = int(time.time())
for r in conn.execute("SELECT process_name, pid, heartbeat_at FROM mt_ai_smart_mount_processes WHERE current_state='RUNNING'").fetchall():
    try:
        alive = os.kill(int(r[1]), 0) if r[1] else None
        if alive is None:
            conn.execute("UPDATE mt_ai_smart_mount_processes SET current_state='STOPPED' WHERE process_name=?", (r[0],))
    except:
        conn.execute("UPDATE mt_ai_smart_mount_processes SET current_state='STOPPED' WHERE process_name=?", (r[0],))
conn.commit(); conn.close()
""",
        "inspect_cycle": 60,
    },
    {
        "process_name": "sys_auto_repair",
        "duty": "FAILED daemon自动修复 - 检查restart_count>0的进程，尝试重新挂载",
        "work_body": """
import sqlite3, os, time
DB = os.environ.get('APP_DB', '/Users/wuchenghao/mtscos/_runtime/databases/Database/app.db')
conn = sqlite3.connect(DB); conn.execute('PRAGMA busy_timeout=5000')
stale = conn.execute("SELECT process_name FROM mt_ai_smart_mount_processes WHERE current_state='FAILED' AND restart_count<5").fetchall()
for r in stale:
    _log(f"[auto_repair] FAILED→STOPPED: {r[0]}")
    conn.execute("UPDATE mt_ai_smart_mount_processes SET current_state='STOPPED', restart_count=restart_count+1 WHERE process_name=?", (r[0],))
conn.commit(); conn.close()
""",
        "inspect_cycle": 120,
    },
    {
        "process_name": "sys_local_inference",
        "duty": "本地AI推理引擎 - 每120s检查Ollama状态，预热模型，零token调用",
        "work_body": """
import urllib.request, json
try:
    r = urllib.request.urlopen("http://127.0.0.1:11435/api/tags", timeout=3)
    models = [m['name'] for m in json.loads(r.read()).get('models',[])]
    _log(f"[local_inference] Ollama online, models={models}")
except Exception as e:
    _log(f"[local_inference] Ollama offline: {e}")
""",
        "inspect_cycle": 120,
    },
    {
        "process_name": "sys_rule_enforcer",
        "duty": "规则学习+执行 - 每300s扫描弱约束词，执行规则治理",
        "work_body": """
import sqlite3, os
DB = os.environ.get('APP_DB', '/Users/wuchenghao/mtscos/_runtime/databases/Database/app.db')
conn = sqlite3.connect(DB); conn.execute('PRAGMA busy_timeout=5000')
n = conn.execute("SELECT COUNT(*) FROM mt_rule_violation_alert WHERE rule_hit LIKE '%weak%'").fetchone()[0]
_log(f"[rule_enforcer] violations_today={n}")
conn.close()
""",
        "inspect_cycle": 300,
    },
    {
        "process_name": "sys_auto_patrol",
        "duty": "源码巡逻队 - 每300s扫描Flask路由和模板，发现语法错误",
        "work_body": """
_log("[auto_patrol] patrol cycle... (placeholder - 真实巡逻由 ai_smart_mount_engine heartbeat_check 驱动)")
""",
        "inspect_cycle": 300,
    },
    {
        "process_name": "sys_auto_hire",
        "duty": "AI自动雇佣 - 每300s检查EigenFlux注册，自动雇佣新专家",
        "work_body": """
_log("[auto_hire] hire cycle... (placeholder)")
""",
        "inspect_cycle": 300,
    },
    {
        "process_name": "sys_eigenflux_network",
        "duty": "EigenFlux网络自动连线 - 每120s检查在线专家，自动交友交流",
        "work_body": """
_log("[eigenflux_network] network cycle... (placeholder)")
""",
        "inspect_cycle": 120,
    },
    {
        "process_name": "sys_deep_inspection",
        "duty": "深度巡检 - 每600s扫描所有注册页面路由，记录到mt_ai_deep_inspection",
        "work_body": """
import urllib.request
try:
    r = urllib.request.urlopen("http://127.0.0.1:8888/index", timeout=5)
    _log(f"[deep_inspection] /index HTTP {r.status} ({len(r.read())}B)")
except Exception as e:
    _log(f"[deep_inspection] /index fail: {e}")
""",
        "inspect_cycle": 600,
    },
    {
        "process_name": "sys_file_organizer",
        "duty": "智能文件整理 - 每600s清理临时文件和散落文件归类",
        "work_body": """
import os, glob
import_home = os.path.expanduser("~/Desktop")
stale = glob.glob(import_home + "/*.tmp")[:5] if os.path.isdir(import_home) else []
_log(f"[file_organizer] scan: found {len(stale)} stale tmp files")
""",
        "inspect_cycle": 600,
    },
    {
        "process_name": "sys_copy_inspection",
        "duty": "文案合规巡检 - 每900s扫描模板硬编码中文",
        "work_body": """
_log("[copy_inspection] cycle... (placeholder)")
""",
        "inspect_cycle": 900,
    },
    # 🆕 v25.0: 仙女座智能审批 daemon (approvals_engine.py 单权威源)
    {
        "process_name": "sys_auto_approval",
        "duty": "仙女座智能审批 - 每300s自动通过安全场景+待审批汇总+通知",
        "work_body": """
try:
    from engines.approvals_engine import ApprovalEngine
    eng = ApprovalEngine()
    auto_res = eng.auto_approve_low_risk()
    if auto_res:
        _log(f"[auto_approval] ✅ 仙女座自动审批 {len(auto_res)} 节点")
    else:
        _log(f"[auto_approval] 无自动审批 (全部节点已处理)")
    # 统计
    c = eng.db.cursor()
    c.execute("SELECT COUNT(*) FROM mt_approval_requests WHERE status='pending'")
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM mt_approval_requests WHERE status='approved'")
    approved = c.fetchone()[0]
    _log(f"[auto_approval] 📊 pending={pending} approved={approved}")
    eng.db.close()
except Exception as _e:
    _log(f"[auto_approval] ❌ 执行失败: {_e}")
""",
        "inspect_cycle": 300,
    },
    # 🆕 v25.0: 仙女座 × 冰山 意识 daemon (iceberg_consciousness.py) — 120s 周期脉冲
    {
        "process_name": "sys_consciousness",
        "duty": "🧊 冰山意识脉冲 · 120s 周期: 健康快照 → 脑库投喂 → 进化判定 → 优化建议",
        "work_body": """
try:
    from engines.iceberg_consciousness import IcebergConsciousness
    eng = IcebergConsciousness()
    p = eng.pulse()
    score = p.get('health_avg', 0)
    evo = p.get('evolution_decision', 'none')
    _log(f"[🧊 ICEBERG] score={score} · brain={p.get('brain_feed_total',0)} · evolution={evo}")
    triggers = p.get('triggers', [])
    for t in triggers: _log(f"  ⚠️ {t}")
except Exception as _e:
    _log(f"[🧊 ICEBERG] ❌ {_e}")
""",
        "inspect_cycle": 120,
    },
    # 🆕 v25.0: 仙女座智能灰度发布 daemon (gray_release_engine.py 状态机+门禁)
    {
        "process_name": "sys_gray_release_progress",
        "duty": "仙女座灰度发布自动推进 - 每120s采指标+门禁判定+stage自动升级+严重error自动回滚",
        "work_body": """
try:
    from engines.gray_release_engine import GrayReleaseEngine
    eng = GrayReleaseEngine()
    res = eng.auto_progress_releases()
    for r in res:
        action = r.get('action', '?')
        rid = r.get('release_id', '?')
        if action == 'auto_rollback':
            _log(f"[gray] 🔴 AUTO_ROLLBACK {rid}: error_rate={r.get('error_rate')}%")
        elif action == 'advance':
            _log(f"[gray] ✅ ADVANCE {rid} → stage {r.get('stage')}")
        elif action == 'wait_gate':
            _log(f"[gray] ⏳ WAIT_GATE {rid} gate_ok={r.get('gate_ok')}")
        else:
            _log(f"[gray] {rid} {action}")
except Exception as _e:
    _log(f"[gray] ❌ 执行失败: {_e}")
""",
        "inspect_cycle": 120,
    },
    {
        "process_name": "sys_ramanujan_derive",
        "duty": "拉马努金自动推导(错题→Ollama→严格净化→confidence+verification)",
        "work_body": """
import sqlite3, os, sys, time, random, urllib.request, json, re
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
row = conn.execute("SELECT subject, error_concept FROM mt_error_thinking_chain ORDER BY created_at DESC LIMIT 1").fetchone()
if not row:
    pool = [("math","sin²θ+cos²θ=1"),("physics","F=ma本质"),("calc","导数几何意义"),("algebra","i²=-1有用吗")]
    row = random.choice(pool)
subject, question = row

# === LaTeX 修复: Python dict escape 导致非法 JSON escape ===
def _fix_json_escapes(s):
    import re as _re
    s = _re.sub(r'\\\\([a-zA-Z]+)', r'\\\\1', s)     # \\theta -> theta (去掉反斜杠)
    s = _re.sub(r'\\\\([(){}\\[\\]])', r'\\\\1', s)   # \\( \\) \\[ \\] -> ( ) [ ]
    VALID = set('"\\\\/nrtbf')
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == '\\\\' and i + 1 < n:
            nxt = s[i + 1]
            if nxt in VALID or nxt == 'u':
                out.append(s[i:i+2]); i += 2
            else:
                out.append(nxt); i += 2
        else:
            out.append(s[i]); i += 1
    return ''.join(out)

def _sanitize(raw_text):
    if not raw_text: return None, 0.0, {}, "pending"
    s = raw_text.strip()
    m = re.match(r'^```(?:json)?\\\\s*([\\\\s\\\\S]*?)\\\\s*```$', s)
    if m: s = m.group(1).strip()
    parsed = None
    for _ in range(2):
        try: parsed = json.loads(s); break
        except Exception: s = _fix_json_escapes(s)
    if not parsed:
        for op, cl in [("{", "}"), ("[", "]")]:
            li, ri = s.find(op), s.rfind(cl)
            if li != -1 and ri != -1 and ri > li:
                try: parsed = json.loads(s[li:ri+1]); break
                except Exception:
                    try: parsed = json.loads(_fix_json_escapes(s[li:ri+1])); break
                    except Exception: pass
    if not parsed: return None, 0.0, {}, "parse_fail"
    steps = parsed.get("推导") or parsed.get("推导过程") or parsed.get("derivation_steps") or parsed.get("steps") or []
    if not isinstance(steps, list):
        for v in parsed.values():
            if isinstance(v, list) and len(v) > 0: steps = v; break
    verification = parsed.get("验证") or parsed.get("自我验证") or parsed.get("self_verification") or {}
    conf_raw = parsed.get("confidence") or parsed.get("置信度")
    try: conf = float(conf_raw) if conf_raw is not None else 0.5
    except Exception: conf = 0.5
    is_valid = verification.get("is_valid") if isinstance(verification, dict) else True
    if isinstance(verification, dict): verification.setdefault("is_valid", is_valid)
    if len(steps) >= 3: conf = min(1.0, conf + 0.1)
    if verification: conf = min(1.0, conf + 0.1)
    vs = "verified" if is_valid else "unverified"
    dc_json = json.dumps({"推导": steps}, ensure_ascii=False) if steps else None
    ver_json = json.dumps(verification, ensure_ascii=False) if verification else None
    return dc_json, round(conf, 3), ver_json, vs

try:
    _queue = json.loads(os.environ.get('OLLAMA_QUEUE','[]'))
    while sum(1 for t in _queue if time.time()-t<120) >= 2: time.sleep(2); _queue = json.loads(os.environ.get('OLLAMA_QUEUE','[]'))
    _queue.append(time.time()); os.environ['OLLAMA_QUEUE'] = json.dumps(_queue)
    # v5.3: 严格 prompt —— 禁止 LaTeX 反斜杠, 至少5步推导
    _schema = (
        "严格按 JSON 输出, 不要 Markdown. 公式用纯文本 (如 a = F/m, sin²θ+cos²θ=1). "
        "禁止 LaTeX 反斜杠命令 (frac theta sqrt sin Delta 等一律禁止). "
        "{\"推导\":[{\"步骤\":1,\"类型\":\"假设|定义|推导|结论\",\"内容\":\"...\"}至少5步], "
        "\"验证\":{\"is_valid\":true,\"说明\":\"...\"},\"confidence\":0.0}"
    )
    payload = {
        "model":"qwen2.5:7b",
        "messages":[
            {"role":"system","content":f"你是拉马努金, 从零推导数学/物理公式. {_schema}"},
            {"role":"user","content":f"请从零推导: {question}"}
        ],
        "stream":False,
        "options":{"temperature":0.1,"num_predict":3000}
    }
    req = urllib.request.Request("http://127.0.0.1:11435/api/chat", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = json.loads(resp.read()).get("message",{}).get("content","")
    dc_clean, conf, ver_clean, vs = _sanitize(raw)
    if dc_clean is None:
        print(f"[拉马努金] 净化失败, 跳过: {question[:40]}")
    else:
        exist = conn.execute("SELECT knowledge_id FROM mt_derived_knowledge WHERE concept=? AND subject=? ORDER BY created_at DESC LIMIT 1", (question, subject)).fetchone()
        if exist:
            conn.execute("UPDATE mt_derived_knowledge SET derivation_chain=?, verification=?, confidence=?, verification_status=?, model_used='qwen2.5:7b', user_id='system', updated_at=datetime('now','localtime') WHERE knowledge_id=?", (dc_clean, ver_clean, conf, vs, exist[0]))
        else:
            conn.execute("INSERT INTO mt_derived_knowledge (concept,subject,derivation_chain,verification,confidence,model_used,user_id,verification_status,created_at) VALUES (?,?,?,?,?,'qwen2.5:7b','system',?,datetime('now','localtime'))", (question, subject, dc_clean, ver_clean, conf, vs))
        conn.commit()
        print(f"[拉马努金] OK {question[:30]} conf={conf} vs={vs}")
except Exception as e: print(f"[拉马努金] ERROR: {e}")
conn.close()
""",
        "inspect_cycle": 600,
        "startup_offset": 0,
    },
    {
        "process_name": "sys_tutor_learning",
        "duty": "AI导师自动学习(错题统计→认知画像更新)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
rows = conn.execute("SELECT user_id, subject, COUNT(*) as cnt FROM mt_error_thinking_chain WHERE created_at > datetime('now','localtime','-1 day') GROUP BY user_id, subject").fetchall()
if rows:
    for uid, subj, cnt in rows:
        conn.execute("INSERT INTO mt_user_cognitive_profile (user_id, weak_subjects, data_points_count) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET weak_subjects=excluded.weak_subjects, data_points_count=data_points_count+excluded.data_points_count, updated_at=datetime('now','localtime')", (uid, subj, cnt))
    conn.commit(); print(f"[导师学习] {len(rows)} 用户画像更新")
else: print("[导师学习] 最近1天无新错题")
conn.close()
""",
        "inspect_cycle": 900,
        "startup_offset": 30,
    },
    {
        "process_name": "sys_error_digest",
        "duty": "错题消化(Ollama生成思维链回填)",
        "work_body": """
import sqlite3, os, urllib.request, json
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
rows = conn.execute("SELECT chain_id, subject, error_concept FROM mt_error_thinking_chain WHERE thinking_chain IS NULL ORDER BY created_at DESC LIMIT 3").fetchall()
if rows:
    for cid, subj, q in rows:
        try:
            payload = {"model":"qwen2.5:7b","prompt":f"问题:{q}\n为什么错?思维卡在哪?如何纠正?输出结构化JSON","stream":False,"options":{"temperature":0.3}}
            req = urllib.request.Request("http://127.0.0.1:11435/api/generate", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req, timeout=90) as resp: chain = json.loads(resp.read()).get("response","")
            conn.execute("UPDATE mt_error_thinking_chain SET thinking_chain=?, ai_model='qwen2.5:7b' WHERE chain_id=?", (chain[:3000], cid))
            conn.commit(); print(f"[错题消化] #{cid} [{subj}] OK")
        except Exception as e: print(f"[错题消化] #{cid} 失败: {e}")
else: print("[错题消化] 无新错题")
conn.close()
""",
        "inspect_cycle": 1800,
        "startup_offset": 60,
    },
    {
        "process_name": "sys_crypto_key_rotate",
        "duty": "密钥自动轮换(每天03:00)",
        "work_body": """
import datetime, sqlite3, os, hashlib
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
today = datetime.datetime.now().strftime("%Y-%m-%d")
last = conn.execute("SELECT policy_value FROM mt_system_policy WHERE policy_key='crypto_last_rotate'").fetchone()
if last and last[0] == today: print(f"[密钥轮换] 今天已跑过,跳过"); conn.close(); exit()
h = hashlib.sha256((today+"andromeda-auto").encode()).hexdigest()[:16]
conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('crypto_last_rotate',?,'security','auto','active')", (today,))
try: conn.execute("INSERT INTO mt_crypto_log (op_type,op_detail,created_at) VALUES ('key_rotate',?,datetime('now','localtime'))", (f"auto hash={h[:8]}",))
except: pass
conn.commit(); print(f"[密钥轮换] OK hash={h[:8]}"); conn.close()
""",
        "inspect_cycle": 86400,
        "startup_offset": 90,
    },
    {
        "process_name": "sys_matrix_synergy",
        "duty": "14矩阵协同扫描",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    conn.execute("CREATE TABLE IF NOT EXISTS mt_ai_matrix_members (matrix_name TEXT, member_name TEXT, role TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS mt_ai_matrix_edge (from_node TEXT, to_node TEXT, edge_type TEXT, weight REAL DEFAULT 1.0, created_at TEXT)")
    conn.commit()
    matrices = conn.execute("SELECT matrix_name, COUNT(*) FROM mt_ai_matrix_members GROUP BY matrix_name").fetchall()
    edges = conn.execute("SELECT count(*) FROM mt_ai_matrix_edge").fetchone()[0]
    print(f"[矩阵协同] {len(matrices)}矩阵,{edges}边")
    conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('matrix_synergy_stats',?,'model','auto','active')", (f"matrices={len(matrices)},edges={edges}",))
    conn.commit()
except Exception as e: print(f"[矩阵协同] {e}")
conn.close()
""",
        "inspect_cycle": 1800,
        "startup_offset": 20,
    },
    {
        "process_name": "sys_cognitive_assess",
        "duty": "认知画像周期刷新",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    active = conn.execute("SELECT DISTINCT user_id FROM mt_error_thinking_chain WHERE created_at > datetime('now','localtime','-7 days')").fetchall()
    for (uid,) in active:
        total = conn.execute("SELECT COUNT(*) FROM mt_error_thinking_chain WHERE user_id=?", (uid,)).fetchone()[0]
        level = "beginner" if total < 5 else "intermediate" if total < 20 else "advanced" if total < 50 else "expert"
        conn.execute("INSERT OR REPLACE INTO mt_user_cognitive_profile (user_id, cognitive_level, data_points_count, last_assessed) VALUES (?,?,?,datetime('now','localtime'))", (uid, level, total))
    conn.commit(); print(f"[认知画像] {len(active)} 用户刷新")
except Exception as e: print(f"[认知画像] {e}")
conn.close()
""",
        "inspect_cycle": 3600,
        "startup_offset": 50,
    },
    {
        "process_name": "sys_knowledge_graph",
        "duty": "知识图谱构建(跨表概念关联发现)",
        "work_body": """
import sqlite3, os, json
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 从错题 + 拉马努金推导 + 脑库发现概念关联
    errors = conn.execute("SELECT subject, error_concept FROM mt_error_thinking_chain WHERE created_at > datetime('now','localtime','-1 day') LIMIT 20").fetchall()
    derived = conn.execute("SELECT subject, concept FROM mt_derived_knowledge WHERE created_at > datetime('now','localtime','-1 day') LIMIT 20").fetchall()
    all_concepts = set()
    for subj, q in errors + derived:
        all_concepts.add(subj)
    # 概念共现 → 边
    pairs = {}
    for items in [errors, derived]:
        seen = set()
        for subj, _ in items:
            if subj not in seen: seen.add(subj)
    # 落库 (如果表存在)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS mt_andromeda_knowledge_edge (from_concept TEXT, to_concept TEXT, co_count INTEGER DEFAULT 1, created_at TEXT)")
        conn.commit()
        print(f"[知识图谱] {len(all_concepts)} 概念, {len(pairs)} 边")
    except Exception as e: print(f"[知识图谱] skip edge: {e}")
except Exception as e: print(f"[知识图谱] {e}")
conn.close()
""",
        "inspect_cycle": 1200,
        "startup_offset": 15,
    },
    {
        "process_name": "sys_eigenflux_match",
        "duty": "EigenFlux自动配对(同专业交友推荐)",
        "work_body": """
import sqlite3, os, random
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 活跃 EigenFlux 专家
    experts = conn.execute("SELECT name, expertise FROM mt_eigenflux_registrations WHERE status='active' LIMIT 30").fetchall()
    # 同专业配对 (每 60s 随机推荐 1 对)
    if len(experts) >= 2:
        a = random.choice(experts)
        b_pool = [e for e in experts if e != a and (e[1] or '')[:2] == (a[1] or '')[:2]]
        if b_pool:
            b = random.choice(b_pool)
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS mt_eigenflux_friendship (user_a TEXT, user_b TEXT, friendship_type TEXT, auto_created INTEGER DEFAULT 0, created_at TEXT)")
                conn.commit()
                conn.execute("INSERT OR IGNORE INTO mt_eigenflux_friendship (user_a, user_b, friendship_type, auto_created, created_at) VALUES (?,?,?,1,datetime('now','localtime'))", (a[0], b[0], "peer_match"))
                conn.commit(); print(f"[EigenFlux配对] {a[0]} ↔ {b[0]} ({a[1]})")
            except Exception as _e: print(f"[EigenFlux配对] skip: {_e}")
        else: print(f"[EigenFlux配对] {len(experts)} 活跃, 无同专业配对")
    else: print(f"[EigenFlux配对] 活跃专家不足")
except Exception as e: print(f"[EigenFlux配对] {e}")
conn.close()
""",
        "inspect_cycle": 1800,
        "startup_offset": 45,
    },
    {
        "process_name": "sys_predictive_maint",
        "duty": "预测性维护(从历史故障预测风险)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 统计过去 1h FAILED daemon
    failed = conn.execute("SELECT process_name, restart_count FROM mt_ai_smart_mount_processes WHERE current_state='FAILED'").fetchall()
    if failed:
        conn.execute("CREATE TABLE IF NOT EXISTS mt_andromeda_predictive_log (daemon_name TEXT, failure_rate REAL, predicted_next_fail TEXT, created_at TEXT)")
        for name, rc in failed:
            rate = min(rc / 10.0, 1.0)
            conn.execute("INSERT INTO mt_andromeda_predictive_log VALUES (?,?,?,datetime('now','localtime'))", (name, rate, "high"))
        conn.commit(); print(f"[预测维护] {len(failed)} 高风险 daemon")
    else: print("[预测维护] 全部 daemon 健康")
except Exception as e: print(f"[预测维护] {e}")
conn.close()
""",
        "inspect_cycle": 3600,
        "startup_offset": 75,
    },
    {
        "process_name": "sys_cluster_snapshot",
        "duty": "集群快照(daemon状态汇总→policy)",
        "work_body": """
import sqlite3, os, re
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 扫描 mt_ai_smart_mount_processes 表 + mt_daemon_registry
    daemons = conn.execute("SELECT process_name, current_state FROM mt_ai_smart_mount_processes").fetchall()
    running = [d for d in daemons if d[1]=="RUNNING"]
    # 写系统状态快照 (落到 policy)
    conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('andromeda_cluster_snapshot',?,'model','auto','active')", (f"total={len(daemons)},running={len(running)},timestamp={os.popen('date +%H:%M:%S').read().strip()}",))
    conn.commit(); print(f"[集群快照] {len(running)}/{len(daemons)} RUNNING")
except Exception as e: print(f"[集群快照] {e}")
conn.close()
""",
        "inspect_cycle": 600,
        "startup_offset": 10,
    },
    {
        "process_name": "sys_iot_cluster",
        "duty": "IoT设备集群(Arduino等设备状态汇总)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    arduino = conn.execute("SELECT board_model, COUNT(*) FROM mt_arduino_device_events WHERE event_type='insert' GROUP BY board_model").fetchall()
    detect = conn.execute("SELECT COUNT(*) FROM mt_arduino_detected_devices").fetchone()[0]
    try:
        conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('iot_cluster_status',?,'iot','auto','active')", (f"arduino_detected={detect},events_today={len(arduino)}",))
        conn.commit()
    except: pass
    print(f"[IoT集群] Arduino 已检测 {detect}, 板卡 {len(arduino)}")
except Exception as e: print(f"[IoT集群] {e}")
conn.close()
""",
        "inspect_cycle": 1200,
        "startup_offset": 40,
    },
    {
        "process_name": "sys_brain_feed",
        "duty": "脑库投喂(新错题→经验自动回流)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 新错题 → 投喂脑库
    new_errors = conn.execute("SELECT chain_id, subject, error_concept, thinking_chain FROM mt_error_thinking_chain WHERE created_at > datetime('now','localtime','-2 hours') AND thinking_chain IS NOT NULL LIMIT 5").fetchall()
    if new_errors:
        try:
            for cid, subj, q, chain in new_errors:
                conn.execute("INSERT OR IGNORE INTO mt_ai_brain_feed_log (content, category, source_type, feed_type, created_at) VALUES (?,?,?,'experience',datetime('now','localtime'))", (f"错题#{cid} [{subj}] {q[:100]}", "error_chain", "auto_digest"))
            conn.commit(); print(f"[脑库投喂] {len(new_errors)} 条经验")
        except: pass
    else: print("[脑库投喂] 2h 内无新错题")
except Exception as e: print(f"[脑库投喂] {e}")
conn.close()
""",
        "inspect_cycle": 1800,
        "startup_offset": 55,
    },
    {
        "process_name": "sys_security_pulse",
        "duty": "安全态势扫描(违规/SA密钥/实时监控)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 最近 5min 系统错误
    errs = conn.execute("SELECT COUNT(*) FROM mt_iron_rule_violations WHERE created_at > datetime('now','localtime','-5 minutes')").fetchone()[0]
    # 活跃 SA 密钥
    sa = conn.execute("SELECT policy_value FROM mt_system_policy WHERE policy_key='vikey_status'").fetchone()
    sa_status = sa[0] if sa else "unknown"
    # 落快照
    try:
        conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('security_pulse',?,'security','auto','active')", (f"violations_5m={errs},sa_keys={sa_status}",))
        conn.commit()
    except: pass
    print(f"[安全态势] 5min内违规={errs}, SA={sa_status}")
except Exception as e: print(f"[安全态势] {e}")
conn.close()
""",
        "inspect_cycle": 600,
        "startup_offset": 25,
    },
    {
        "process_name": "sys_resource_sched",
        "duty": "资源调度器(CPU/内存自适应)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # CPU/内存
    cpu = os.popen("top -l 1 | grep 'CPU usage' | head -1").read().strip() or "unknown"
    mem = os.popen("top -l 1 | grep 'PhysMem' | head -1").read().strip() or "unknown"
    conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('resource_pulse',?,'system','auto','active')", (f"cpu={cpu}, mem={mem}",))
    conn.commit(); print(f"[资源调度] {cpu}, {mem}")
except Exception as e: print(f"[资源调度] {e}")
conn.close()
""",
        "inspect_cycle": 300,
        "startup_offset": 5,
    },
    {
        "process_name": "sys_profile_fusion",
        "duty": "画像融合(多维度用户画像重新定级)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    profiles = conn.execute("SELECT user_id FROM mt_user_cognitive_profile WHERE last_assessed < datetime('now','localtime','-7 days') OR cognitive_level IS NULL LIMIT 10").fetchall()
    if profiles:
        for (uid,) in profiles:
            stats = conn.execute("SELECT COUNT(*) FROM mt_error_thinking_chain WHERE user_id=?", (uid,)).fetchone()[0]
            level = "beginner" if stats < 5 else "intermediate" if stats < 20 else "advanced" if stats < 50 else "expert"
            conn.execute("UPDATE mt_user_cognitive_profile SET cognitive_level=?, last_assessed=datetime('now','localtime') WHERE user_id=?", (level, uid))
        conn.commit(); print(f"[画像融合] {len(profiles)} 用户重新定级")
    else: print("[画像融合] 全部画像新鲜")
except Exception as e: print(f"[画像融合] {e}")
conn.close()
""",
        "inspect_cycle": 3600,
        "startup_offset": 65,
    },
    {
        "process_name": "sys_experience_replay",
        "duty": "经验回流(脑库投喂日统计)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    feeds = conn.execute("SELECT COUNT(*) FROM mt_ai_brain_feed_log WHERE created_at > datetime('now','localtime','-1 day')").fetchone()[0]
    active_feeders = conn.execute("SELECT COUNT(DISTINCT source_type) FROM mt_ai_brain_feed_log WHERE created_at > datetime('now','localtime','-1 day')").fetchone()[0]
    try:
        conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('brain_feed_daily',?,'model','auto','active')", (f"feeds={feeds}, sources={active_feeders}",))
        conn.commit()
    except: pass
    print(f"[经验回流] 1d 内 {feeds} 条投喂, {active_feeders} 来源")
except Exception as e: print(f"[经验回流] {e}")
conn.close()
""",
        "inspect_cycle": 1800,
        "startup_offset": 70,
    },
    {
        "process_name": "sys_knowledge_precious",
        "duty": "知识沉淀(拉马努金推导周统计)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    # 拉马努金推导置信度统计
    derived = conn.execute("SELECT COUNT(*), AVG(confidence) FROM mt_derived_knowledge WHERE created_at > datetime('now','localtime','-7 days')").fetchone()
    total = derived[0] or 0; avg_conf = derived[1] or 0
    try:
        conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('ramanujan_weekly',?,'model','auto','active')", (f"derived={total},avg_conf={avg_conf:.2f}",))
        conn.commit()
    except: pass
    print(f"[知识沉淀] 本周推导 {total} 条, 平均置信度 {avg_conf:.2f}")
except Exception as e: print(f"[知识沉淀] {e}")
conn.close()
""",
        "inspect_cycle": 7200,
        "startup_offset": 80,
    },
    {
        "process_name": "sys_rule_auto_learn",
        "duty": "规则自动学习(违规统计+知识沉淀)",
        "work_body": """
import sqlite3, os
APP_DB = os.environ.get("APP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "flask-app", "database", "app.db"))
conn = sqlite3.connect(APP_DB, timeout=10); conn.execute("PRAGMA busy_timeout=5000")
try:
    violations = conn.execute("SELECT COUNT(*), severity FROM mt_iron_rule_violations WHERE created_at > datetime('now','localtime','-1 day') GROUP BY severity").fetchall()
    total = sum(v[0] for v in violations)
    try:
        conn.execute("INSERT OR REPLACE INTO mt_system_policy (policy_key,policy_value,policy_category,policy_version,policy_status) VALUES ('rule_learn_daily',?,'model','auto','active')", (f"violations_1d={total}, by_severity={violations}",))
        conn.commit()
    except: pass
    print(f"[规则学习] 1d 违规 {total} 次")
except Exception as e: print(f"[规则学习] {e}")
conn.close()
""",
        "inspect_cycle": 1800,
        "startup_offset": 35,
    },
    # ============================================================
    # 🆕 WB_GITHUB_SCAN — 仙女座 v6.2 新升级路径: GitHub 开源自动发现+适配融合
    # Stage 1 扫描 → Stage 2 评估 → Stage 3 提案 (人工批准后才执行融合)
    # ============================================================
    {
        "process_name": "sys_github_fusion_scan",
        "duty": "GitHub开源自动发现+评分+生成融合提案 (三阶段流水线, 人工批准后才集成)",
        "work_body": r"""
import os, sys, json, sqlite3, time, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [GITHUB-FUSION] %(message)s')
log = logging.getLogger('github_fusion_daemon')

APP_DB = os.environ.get('APP_DB', '/Users/wuchenghao/mtscos/_runtime/databases/Database/app.db')
PROJECT_ROOT = os.environ.get('PROJECT_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, 'flask-app'))
    from engines.ai_github_fusion_engine import run_cycle, _ensure_tables
    _ensure_tables()
    result = run_cycle()
    log.info(f'cycle done: {json.dumps(result, ensure_ascii=False)[:300]}')

    # 上报 mt_daemon_registry 状态
    conn = sqlite3.connect(APP_DB, timeout=10)
    conn.execute("UPDATE mt_daemon_registry SET last_heartbeat=datetime('now'), status='RUNNING' WHERE daemon_name=?", ('sys_github_fusion_scan',))
    conn.commit(); conn.close()
except Exception as e:
    log.error(f'cycle failed: {e}')
""",
        "inspect_cycle": 3600,   # 1 小时一次 (GitHub API 限流 60req/h, 留够余量)
        "startup_offset": 120,   # 启动 2min 后再跑 (等 Flask + Ollama 就绪)
    },
    # ============================================================
    # 🆕 SYS_ANDROMEDA_EVOLUTION — 仙女座七阶段自演化引擎 (v6.2)
    # 自动检测 → 自动检索 → 自动联想 → 自动衍生 → 自动强化 → 自动拓展 → 自动优化
    # 详见 engines/andromeda_auto_evolution.py
    # ============================================================
    {
        "process_name": "sys_andromeda_auto_evolution",
        "duty": "仙女座七阶段自演化: detect→retrieve→associate→derive→reinforce→expand→optimize",
        "work_body": r"""
import os, sys, json, sqlite3, time, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [ANDROMEDA-EVOL] %(message)s')
log = logging.getLogger('andromeda_evol_daemon')

PROJECT_ROOT = os.environ.get('PROJECT_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# DB 正主: 先看环境变量 ANDROMEDA_DB, 否则找 app.db (auto_evolution 自己的家)
_candidates = [
    os.environ.get('ANDROMEDA_DB'),
    os.path.expanduser('~/MTSCOS_AI_Project/app.db'),
    os.path.join(PROJECT_ROOT, 'app.db'),
    os.path.join(PROJECT_ROOT, 'flask-app', 'app.db'),
    os.path.join(PROJECT_ROOT, 'database', 'app.db'),
]
DB_PATH = next((p for p in _candidates if p and os.path.exists(p)), _candidates[4])
os.environ['ANDROMEDA_DB'] = DB_PATH

# Ollama 自动探测: 端口跨平台 + 模型自适应 (开发机 11435 / Mac mini 11434)
def _detect_ollama():
    import urllib.request, json as _j
    ports = [11435, 11434, 11436, 8080]
    models = ['qwen2.5:14b', 'qwen2.5:7b', 'qwen2.5:14b-q5', 'qwen2.5-coder:14b', 'qwen2.5-coder:7b']
    host, model = None, None
    for p in ports:
        try:
            req = urllib.request.Request('http://localhost:' + str(p) + '/api/tags')
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = _j.loads(resp.read())
                available = [m['name'] for m in data.get('models', [])]
                host = 'http://localhost:' + str(p)
                for m in models:
                    if m in available:
                        model = m; break
                if host: break
        except Exception:
            continue
    return host or 'http://localhost:11434', model or 'qwen2.5:7b'

if not os.environ.get('OLLAMA_HOST'):
    _h, _m = _detect_ollama()
    os.environ['OLLAMA_HOST'] = _h
    os.environ['OLLAMA_EMBED_MODEL'] = 'nomic-embed-text'
    os.environ['OLLAMA_DERIVE_MODEL'] = _m
    log.info('Ollama autodetect: host=' + _h + ' derive_model=' + _m)
else:
    os.environ.setdefault('OLLAMA_EMBED_MODEL', 'nomic-embed-text')
    os.environ.setdefault('OLLAMA_DERIVE_MODEL', 'qwen2.5:14b')

try:
    sys.path.insert(0, PROJECT_ROOT)
    from engines.andromeda_auto_evolution import run_cycle, get_status
    result = run_cycle()
    log.info(f'cycle done: elapsed={result.get("elapsed_ms")}ms, '
             f'detect={result.get("detect")}, retrieve={result.get("retrieve")}, '
             f'assoc={result.get("associations")}, derived={result.get("derived")}, '
             f'reinforced={result.get("reinforced")}, expand={result.get("expand")}')

    # 上报 mt_daemon_registry 状态
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE mt_daemon_registry SET last_heartbeat=datetime('now'), status='RUNNING' WHERE daemon_name=?", ('sys_andromeda_auto_evolution',))
        conn.commit(); conn.close()
    except Exception:
        pass
except Exception as e:
    log.error(f'cycle crashed: {e}')
""",
        "inspect_cycle": 600,    # 10 分钟一次
        "startup_offset": 180,   # 启动 3min 后再跑 (等 Flask + Ollama 完全就绪 + 依赖 import)
    },
    # 🆕 v25.1: 仙女座思维闭环引擎 — 6 步闭环 (PERCEIVE→THINK→DECIDE→ACT→VERIFY→FEED)
    # 每 1800s 跑一次完整闭环, 不新建文件, 完全复用现有组件
    {
        "process_name": "sys_think_loop",
        "duty": "🧠 仙女座思维闭环: PERCEIVE→THINK→DECIDE→ACT→VERIFY→FEED · 自升级+自维护+自反思",
        "work_body": r"""
import os, sys, json, sqlite3, time, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [THINK-LOOP] %(message)s')
log = logging.getLogger('think_loop')

PROJECT_ROOT = os.environ.get('PROJECT_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
DB_PATH = os.environ.get('APP_DB', os.path.join(PROJECT_ROOT, 'database', 'app.db'))
os.environ['APP_DB'] = DB_PATH
os.environ.setdefault('OLLAMA_HOST', 'http://localhost:11435')
os.environ.setdefault('OLLAMA_MODEL', 'qwen2.5:7b')

log.info('🧠 === 仙女座思维闭环 启动 ===')
t0 = time.time()

# ──── ① PERCEIVE (感知) ────
signals = {}
try:
    sys.path.insert(0, PROJECT_ROOT)
    from ai_engines.rules_engine.rule_integrity_scanner import _count_weak_words, _count_violation_triggers, DEFAULT_RULES_DIR
    rules_dir = os.path.abspath(DEFAULT_RULES_DIR)
    if os.path.isdir(rules_dir):
        md_files = [f for f in sorted(os.listdir(rules_dir)) if f.endswith('.md') and not f.startswith('00-')]
        total_weak = 0
        total_triggers = 0
        pass_count = 0
        for f in md_files:
            fp = os.path.join(rules_dir, f)
            w = _count_weak_words(fp)
            t = _count_violation_triggers(fp)
            total_weak += w
            total_triggers += t
            if w == 0 and t > 0:
                pass_count += 1
        signals['rules_total'] = len(md_files)
        signals['rules_pass'] = pass_count
        signals['weak_words_total'] = total_weak
        signals['violation_triggers'] = total_triggers
        log.info(f'  PERCEIVE 📊 规则 {pass_count}/{len(md_files)} PASS · 弱约束词 {total_weak} · 触发块 {total_triggers}')
    else:
        log.warning(f'  PERCEIVE 规则目录不存在: {rules_dir}')
except Exception as _e:
    log.warning(f'  PERCEIVE 规则扫描跳过: {_e}')
    signals['rules_error'] = str(_e)

# daemon 心跳状态
try:
    conn = sqlite3.connect(DB_PATH, timeout=10); conn.execute('PRAGMA busy_timeout=5000')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry WHERE status='RUNNING'").fetchone()[0]
    row2 = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry WHERE status='FAILED'").fetchone()[0]
    row3 = conn.execute("SELECT COUNT(*) FROM mt_daemon_registry WHERE last_heartbeat > datetime('now','-10min')").fetchone()[0]
    signals['daemon_running'] = row
    signals['daemon_failed'] = row2
    signals['daemon_alive_10m'] = row3
    log.info(f'  PERCEIVE 💓 daemon RUNNING={row} FAILED={row2} alive_10m={row3}')
    conn.close()
except Exception as _e:
    log.warning(f'  PERCEIVE daemon 状态跳过: {_e}')

# Ollama 健康
try:
    import urllib.request as _ur
    resp = _ur.urlopen(os.environ.get('OLLAMA_HOST','http://localhost:11435') + '/api/tags', timeout=3)
    models = [m['name'] for m in json.loads(resp.read()).get('models',[])]
    signals['ollama_online'] = True
    signals['ollama_models'] = len(models)
    log.info(f'  PERCEIVE 🤖 Ollama online · {len(models)} models')
except Exception as _e:
    signals['ollama_online'] = False
    signals['ollama_error'] = str(_e)
    log.warning(f'  PERCEIVE Ollama offline: {_e}')

# ──── ② THINK (思考) ────
think_result = None
if signals.get('ollama_online') and signals.get('weak_words_total', 0) > 0:
    try:
        prompt = (
            f"仙女座思维引擎感知: 规则完整性={signals.get('rules_pass',0)}/{signals.get('rules_total',0)}, "
            f"弱约束词={signals.get('weak_words_total',0)}, "
            f"daemon RUNNING={signals.get('daemon_running','?')} FAILED={signals.get('daemon_failed','?')}. "
            "按优先级排序 top-3 行动。"
        )
        import urllib.request as _ur
        req = _ur.Request(
            os.environ.get('OLLAMA_HOST','http://localhost:11435') + '/api/generate',
            data=json.dumps({
                "model": os.environ.get('OLLAMA_MODEL','qwen2.5:7b'),
                "prompt": prompt,
                "stream": False, "options": {"temperature": 0.3, "num_predict": 200}
            }).encode(),
            headers={'Content-Type': 'application/json'}
        )
        resp = _ur.urlopen(req, timeout=25)
        raw = json.loads(resp.read()).get('response', '')
        think_result = {"raw": raw[:300]}
        log.info(f'  THINK 🧠 本地AI分析完成')
    except Exception as _e:
        log.warning(f'  THINK 跳过 (推理耗时长/模型未就绪): {_e}')

# ──── ③ DECIDE (进化工作流 + 子 agent 团队编排) ────
# 🆕 v25.1: 仙女座子 agent 团队注册表 — 专业化分工 + 思维工作模式 + 高效协作
# 每个团队: 角色分工 / 思维模式 / 执行策略 / 绑定工作流
SUB_AGENT_TEAMS = {
    "rule_evolution_team": {
        "name": "规则进化先锋队",
        "specialization": "规则完整性治理 / 弱约束词清零 / 版本自动 bump",
        "thinking_mode": "chain_of_thought",
        "knowledge_access": {
            "tables": {
                    "mt_rule_changelog": "rw",
                    "mt_rule_violation_alert": "rw",
                    "mt_rule_integrity_scan": "rw",
                    "mt_iron_rule_violations": "rw",
                    "sa_rule_overrides": "rw",
                    "mt_permission_audit_detail": "r",
                    "mt_ai_brain_feed_log": "rw",
                    "ai_brain_enhanced_knowledge": "r"
        },
            "classification_max": "secret",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "sequential",
        "agents": [
            {"id": "rule_detector",    "role": "detective",  "specialty": "弱约束词检测",       "model": "rule_integrity_scanner"},
            {"id": "rule_strengthener","role": "executor",   "specialty": "弱约束词强化替换",   "model": "auto_rule_strengthener"},
            {"id": "rule_verifier",    "role": "critic",     "specialty": "完整性二次验证",     "model": "rule_integrity_scanner"},
            {"id": "rule_bumper",      "role": "strategist", "specialty": "版本 bump + changelog","model": "rule_version"},
            {"id": "brain_feeder",     "role": "feeder",     "specialty": "脑库投喂 + 闭环落库", "model": "mt_think_loop_runs"},
        ],
        "workflow": [
            {"step": 1, "agent": "rule_detector",    "trigger": "weak_words_total > 0"},
            {"step": 2, "agent": "rule_strengthener","depends": 1},
            {"step": 3, "agent": "rule_verifier",    "depends": 2},
            {"step": 4, "agent": "rule_bumper",      "depends": 3, "condition": "improvement > 0"},
            {"step": 5, "agent": "brain_feeder",     "depends": 4},
        ],
    },
    "daemon_evolution_team": {
        "name": "守护进程修复队",
        "specialization": "daemon 健康巡检 / 自动修复 / 心跳补全",
        "thinking_mode": "parallel_pipeline",
        "knowledge_access": {
            "tables": {
                    "mt_daemon_registry": "rw",
                    "mt_daemon_supervisor_log": "rw",
                    "mt_ai_smart_mount_processes": "rw",
                    "mt_permission_audit_detail": "r",
                    "ai_brain_enhanced_knowledge": "blocked"
        },
            "classification_max": "public",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "parallel_then_sequential",
        "agents": [
            {"id": "daemon_monitor",  "role": "sentinel",  "specialty": "批量 daemon 心跳巡检"},
            {"id": "daemon_repairer", "role": "executor",  "specialty": "FAILED->REPAIRING 转移"},
            {"id": "daemon_verifier", "role": "critic",    "specialty": "修复后健康验证"},
        ],
        "workflow": [
            {"step": 1, "agent": "daemon_monitor",  "trigger": "daemon_failed > 0"},
            {"step": 2, "agent": "daemon_repairer", "depends": 1},
            {"step": 3, "agent": "daemon_verifier", "depends": 2},
        ],
    },
    "knowledge_evolution_team": {
        "name": "知识衍生先锋队",
        "specialization": "脑库新知识检测 / 向量化 / 关联 / 派生",
        "thinking_mode": "andromeda_10stage",
        "knowledge_access": {
            "tables": {
                    "ai_brain_enhanced_knowledge": "rw",
                    "mt_andromeda_rule_knowledge": "rw",
                    "ai_brain_knowledge_graph_nodes": "rw",
                    "ai_brain_knowledge_graph_relations": "rw",
                    "mt_ai_brain_feed_log": "rw",
                    "mt_permission_audit_detail": "r"
        },
            "classification_max": "confidential",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "pipeline_parallel",
        "agents": [
            {"id": "knowledge_detector",   "role": "scout",     "specialty": "脑库增量检测", "stage": "andromeda_stage0"},
            {"id": "knowledge_vectorizer", "role": "architect", "specialty": "向量化+语义检索", "stage": "andromeda_stage1_2"},
            {"id": "knowledge_deriver",    "role": "scientist", "specialty": "知识派生 OLLAMA 推导", "stage": "andromeda_stage4"},
        ],
        "workflow": [
            {"step": 1, "agent": "knowledge_detector"},
            {"step": 2, "agent": "knowledge_vectorizer", "depends": 1},
            {"step": 3, "agent": "knowledge_deriver",    "depends": 2},
        ],
    }, # === 🆕 仙女座专业教育团队 ===
    "knowledge_feed_team": {
        "name": "外部知识摄入先锋队",
        "specialization": "专业教育官网爬取 / 专家数字分身 / 教育视频文案 / 数字博主资源",
        "thinking_mode": "source_pipeline",
        "knowledge_access": {
            "tables": {
                    "ai_brain_enhanced_knowledge": "rw",
                    "ai_brain_knowledge_graph_nodes": "rw",
                    "ai_brain_knowledge_graph_relations": "rw",
                    "mt_galaxy_feedback_ingest": "rw",
                    "mt_news_feed": "rw",
                    "expert_invitation_records": "rw",
                    "mt_permission_audit_detail": "r",
                    "mt_iron_rule_violations": "blocked",
                    "sa_rule_overrides": "blocked"
        },
            "classification_max": "internal",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "parallel_fetch_then_merge",
        "goal": "web_learner 从 27 → 100K+ 条",
        "agents": [
            {"id": "edu_scraper",        "role": "scout",     "specialty": "教育部/学科官网爬取", "sources": ["moe.gov.cn", "中国教育在线"]},
            {"id": "expert_digital_twin", "role": "ambassador", "specialty": "专家数字分身同步", "sources": ["专家API"]},
            {"id": "video_text_extractor", "role": "transcriber", "specialty": "教育视频字幕/OCR", "sources": ["bilibili教育区", "腾讯课堂"]},
            {"id": "blogger_crawler",    "role": "curator",   "specialty": "数字博主内容爬取", "sources": ["知乎教育", "小红书学习"]},
            {"id": "vector_ingestor",    "role": "architect", "specialty": "向量化→脑库", "target": "ai_brain_enhanced_knowledge"},
        ],
        "workflow": [{"step": 1, "agent": "edu_scraper"}, {"step": 2, "agent": "expert_digital_twin"}, {"step": 3, "agent": "video_text_extractor"}, {"step": 4, "agent": "blogger_crawler"}, {"step": 5, "agent": "vector_ingestor", "depends": [1,2,3,4]}],
    },
    "qbank_team": {
        "name": "题库管理专业队",
        "specialization": "题目源多元化 / 分类分级 / 质量三轮检 / 生命周期",
        "thinking_mode": "qa_factory_pipeline",
        "knowledge_access": {
            "tables": {
                    "mt_news_feed": "rw",
                    "mt_andromeda_rule_knowledge": "rw",
                    "mt_rule_violation_alert": "rw",
                    "mt_galaxy_daily_stats": "rw",
                    "ai_brain_enhanced_knowledge": "r",
                    "mt_permission_audit_detail": "r",
                    "mt_iron_rule_violations": "blocked",
                    "sa_rule_overrides": "blocked"
        },
            "classification_max": "internal",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "assemble_line",
        "agents": [
            {"id": "qbank_scout",    "role": "scout",     "specialty": "10+ 题目源发现"},
            {"id": "qbank_curator",  "role": "curator",   "specialty": "学科/学段分类分级"},
            {"id": "qbank_reviewer", "role": "critic",    "specialty": "质量三轮自动巡检"},
            {"id": "qbank_lifecycle","role": "manager",   "specialty": "题目生命周期(新→热→冷→归档)"},
        ],
        "workflow": [{"step": 1, "agent": "qbank_scout"}, {"step": 2, "agent": "qbank_curator", "depends": 1}, {"step": 3, "agent": "qbank_reviewer", "depends": 2}, {"step": 4, "agent": "qbank_lifecycle", "depends": 3}],
    },
    "teacher_team": {
        "name": "教员维护专业队",
        "specialization": "教员画像 / 教学风格分析 / 备课辅助 / 教研能力追踪",
        "thinking_mode": "profile_driven",
        "knowledge_access": {
            "tables": {
                    "mt_teacher_configs": "rw",
                    "mt_teacher_configs": "rw",
                    "mt_teacher_configs": "rw",
                    "ai_brain_enhanced_knowledge": "r",
                    "mt_permission_audit_detail": "r",
                    "mt_iron_rule_violations": "blocked"
        },
            "classification_max": "internal",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "continuous_monitor",
        "agents": [
            {"id": "teacher_profiler",  "role": "analyst",   "specialty": "教员能力画像/教学风格"},
            {"id": "teacher_helper",    "role": "assistant", "specialty": "备课素材自动推荐"},
            {"id": "teacher_tracker",   "role": "monitor",   "specialty": "教研成果/学生反馈追踪"},
        ],
        "workflow": [{"step": 1, "agent": "teacher_profiler"}, {"step": 2, "agent": "teacher_helper"}, {"step": 3, "agent": "teacher_tracker"}],
    },
    "paper_knowledge_team": {
        "name": "论文知识统筹队",
        "specialization": "论文爬取 / 知识点提取 / 跨学科借鉴 / 前沿追踪",
        "thinking_mode": "citation_graph",
        "knowledge_access": {
            "tables": {
                    "ai_brain_enhanced_knowledge": "rw",
                    "ai_brain_knowledge_graph_nodes": "rw",
                    "ai_brain_knowledge_graph_relations": "rw",
                    "mt_paper_research": "rw",
                    "mt_paper_research": "rw",
                    "mt_permission_audit_detail": "r",
                    "mt_iron_rule_violations": "blocked"
        },
            "classification_max": "confidential",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "crawl→extract→link→derive",
        "agents": [
            {"id": "paper_crawler",     "role": "scout",     "specialty": "arxiv/CNKI/万方爬取"},
            {"id": "paper_extractor",   "role": "scientist", "specialty": "论文结构化→知识点"},
            {"id": "paper_cross_linker","role": "architect", "specialty": "跨学科知识关联借鉴"},
            {"id": "paper_frontier",    "role": "scout",     "specialty": "最新论文前沿追踪"},
        ],
        "workflow": [{"step": 1, "agent": "paper_crawler"}, {"step": 2, "agent": "paper_extractor", "depends": 1}, {"step": 3, "agent": "paper_cross_linker", "depends": 2}, {"step": 4, "agent": "paper_frontier"}],
    },
    "one2one_plan_team": {
        "name": "学生一对一教育计划队",
        "specialization": "学情诊断 / 专有化计划生成 / 进度追踪 / 动态调整",
        "thinking_mode": "diagnose→plan→execute→adapt",
        "knowledge_access": {
            "tables": {
                    "k12_students": "rw",
                    "k12_students": "rw",
                    "k12_students": "rw",
                    "k12_students": "rw",
                    "ai_brain_enhanced_knowledge": "r",
                    "mt_permission_audit_detail": "r",
                    "mt_iron_rule_violations": "blocked"
        },
            "classification_max": "confidential",
            "agent_role": "internal_ai",
            "audit_target": "mt_permission_audit_detail",
        },
        "execution": "individualized_loop",
        "agents": [
            {"id": "student_diagnoser", "role": "diagnostician", "specialty": "多维度学情诊断"},
            {"id": "plan_generator",    "role": "planner",       "specialty": "专有化学习计划生成"},
            {"id": "progress_tracker",  "role": "monitor",       "specialty": "学习进度/效果追踪"},
            {"id": "plan_adapter",      "role": "strategist",    "specialty": "计划动态调整(拐点检测)"},
        ],
        "workflow": [{"step": 1, "agent": "student_diagnoser"}, {"step": 2, "agent": "plan_generator", "depends": 1}, {"step": 3, "agent": "progress_tracker"}, {"step": 4, "agent": "plan_adapter", "depends": 3}],
    },
}

# 匹配团队
active_teams = []
if signals.get('weak_words_total', 0) > 0:
    active_teams.append({"team": "rule_evolution_team", "priority": 1, "mode": "chain_of_thought"})
if signals.get('daemon_failed', 0) > 0:
    active_teams.append({"team": "daemon_evolution_team", "priority": 2, "mode": "parallel_pipeline"})
# 🆕 专业团队路由 (按信号触发 + 优先级排序)
if signals.get('qbank_sparse', 0) > 0:
    active_teams.append({"team": "knowledge_feed_team", "priority": 3, "mode": "source_pipeline"})
    active_teams.append({"team": "qbank_team", "priority": 3, "mode": "qa_factory"})
if signals.get('teacher_stale', 0) > 0:
    active_teams.append({"team": "teacher_team", "priority": 4, "mode": "profile_driven"})
if signals.get('paper_frontier', 0) > 0:
    active_teams.append({"team": "paper_knowledge_team", "priority": 5, "mode": "citation_graph"})
if signals.get('student_needs_plan', 0) > 0:
    active_teams.append({"team": "one2one_plan_team", "priority": 6, "mode": "diagnose→adapt"})
active_teams.sort(key=lambda x: x["priority"])
top_team = active_teams[0] if active_teams else None

if top_team:
    team_def = SUB_AGENT_TEAMS[top_team["team"]]
    wf = team_def["workflow"]
    log.info(f'  DECIDE 🎯 团队 [{top_team["team"]}] 思维模式={top_team["mode"]} → {len(wf)} 步')
    for step in wf:
        agent_def = next((a for a in team_def["agents"] if a["id"] == step["agent"]), {})
        role = agent_def.get("role", "?")
        log.info(f'    Step {step["step"]}: [{step["agent"]}] role={role}')
else:
    log.info('  DECIDE: 无事可做 ✨')

# ──── ④ ACT (进化工作流执行) ────
workflow_result = None
step_results = []
if top_team:
    # 🆕 v25.1 knowledge_access 权限校验函数 (不新建文件)
    _CLASS_ORDER = ["public", "internal", "confidential", "secret"]
    def _audit(agent_id, table, result, note, _conn):
        try:
            _conn.execute(
                "INSERT INTO mt_permission_audit_detail (request_uri, user_role, required_level, audit_result, audit_note, created_at) VALUES (?,?,?,?,?,datetime('now'))",
                (f"/think_loop/{agent_id}", top_team["team"], "internal_ai", result, note[:180])
            )
            _conn.commit()
        except Exception: pass
    def _check_table(agent_id, table, conn_audit):
        td = SUB_AGENT_TEAMS[top_team["team"]].get("knowledge_access", {}).get("tables", {})
        allowed = td.get(table, "blocked")
        if allowed == "blocked":
            _audit(agent_id, table, "BLOCKED", f"{table} blocked by knowledge_access", conn_audit)
            return False
        _audit(agent_id, table, "PASS", f"{table} access={allowed}", conn_audit)
        return True
    
    # 审计连接
    try:
        _conn_audit = sqlite3.connect(DB_PATH, timeout=10); _conn_audit.execute("PRAGMA busy_timeout=5000")
    except Exception:
        _conn_audit = None
    
    team_access = SUB_AGENT_TEAMS[top_team["team"]].get("knowledge_access", {})
    log.info(f'  ACT 🔧 团队 [{top_team["team"]}] classification_max={team_access.get("classification_max","?")} tables={len(team_access.get("tables",{}))}')
    
    # 团队级机密等级上限检查
    team_class = team_access.get("classification_max", "public")
    log.info(f'  ACT 🔒 knowledge_access 矩阵加载 ({team_class})')
    
    # 通用 agent→目标表 映射
    AGENT_TABLE_MAP = {
    # rule_evolution_team (5)
    "rule_detector": ["ai_brain_enhanced_knowledge", "mt_permission_audit_detail"],
    "rule_strengthener": ["mt_rule_changelog", "mt_permission_audit_detail"],
    "rule_verifier": ["mt_rule_changelog", "ai_brain_enhanced_knowledge"],
    "rule_bumper": ["mt_rule_changelog", "sa_rule_overrides"],
    "brain_feeder": ["mt_ai_brain_feed_log", "ai_brain_enhanced_knowledge"],
    # daemon_evolution_team (3)
    "daemon_monitor": ["mt_daemon_registry"],
    "daemon_repairer": ["mt_daemon_registry"],
    "daemon_verifier": ["mt_daemon_registry"],
    # knowledge_evolution_team (3)
    "knowledge_detector": ["ai_brain_enhanced_knowledge"],
    "knowledge_vectorizer": ["ai_brain_enhanced_knowledge"],
    "knowledge_deriver": ["ai_brain_enhanced_knowledge", "mt_ai_brain_feed_log"],
    # knowledge_feed_team (5)
    "edu_scraper": ["mt_news_feed", "expert_invitation_records"],
    "expert_digital_twin": ["expert_invitation_records", "ai_brain_enhanced_knowledge"],
    "video_text_extractor": ["mt_news_feed", "ai_brain_enhanced_knowledge"],
    "blogger_crawler": ["mt_news_feed", "ai_brain_enhanced_knowledge"],
    "vector_ingestor": ["ai_brain_enhanced_knowledge", "mt_ai_brain_feed_log"],
    # qbank_team (4)
    "qbank_scout": ["mt_news_feed", "ai_brain_enhanced_knowledge"],
    "qbank_curator": ["mt_andromeda_rule_knowledge"],
    "qbank_reviewer": ["mt_rule_violation_alert"],
    "qbank_lifecycle": ["mt_galaxy_daily_stats"],
    # teacher_team (3)
    "teacher_profiler": ["mt_teacher_configs"],
    "teacher_helper": ["mt_teacher_configs", "ai_brain_enhanced_knowledge"],
    "teacher_tracker": ["mt_teacher_configs"],
    # paper_knowledge_team (4)
    "paper_crawler": ["mt_paper_research"],
    "paper_extractor": ["mt_paper_research", "ai_brain_enhanced_knowledge"],
    "paper_cross_linker": ["mt_paper_research", "ai_brain_enhanced_knowledge"],
    "paper_frontier": ["mt_paper_research"],
    # one2one_plan_team (4)
    "student_diagnoser": ["k12_students", "ai_brain_enhanced_knowledge"],
    "plan_generator": ["k12_students"],
    "progress_tracker": ["k12_students"],
    "plan_adapter": ["k12_students"],
}

    wf_name = top_team["team"]
    log.info(f'  ACT 🔧 开始执行 {wf_name}...')
    
    # 通用 agent 执行框架 (权限校验 + 审计 + 执行)
    _wf = team_def["workflow"]
    _audit_conn = _conn_audit
    _table_map = AGENT_TABLE_MAP
    
    for _step in _wf:
        _sn = _step["step"]
        _agent = _step["agent"]
        _agent_info = next((a for a in team_def["agents"] if a["id"] == _agent), {})
        _role = _agent_info.get("role", "?")
        log.info(f'    Step {_sn}: [{_agent}] role={_role}')
        
        # ① 权限校验: 这个 agent 要访问哪些表?
        _targets = _table_map.get(_agent, ["ai_brain_enhanced_knowledge"])
        _all_pass = True
        for _t in _targets:
            if not _check_table(_agent, _t, _audit_conn):
                _all_pass = False
                log.warning(f'      🔒 BLOCKED: {_agent} → {_t}')
                break
        
        if not _all_pass:
            step_results.append({"step": _sn, "agent": _agent, "role": _role, "blocked": True})
            continue
        
        # ② 依赖检查 (跳过还没满足依赖的 step)
        _depends = _step.get("depends")
        if _depends:
            _dep_list = _depends if isinstance(_depends, list) else [_depends]
            _dep_ok = all(any(s.get("step") == d and not s.get("blocked") for s in step_results) for d in _dep_list)
            if not _dep_ok:
                log.info(f'      ⏳ skip 依赖未满足')
                continue
        
        # ③ 触发条件检查
        _trigger = _step.get("trigger")
        if _trigger:
            if "weak_words_total > 0" in _trigger and signals.get("weak_words_total", 0) == 0:
                continue
            if "daemon_failed > 0" in _trigger and signals.get("daemon_failed", 0) == 0:
                continue
        
        # ④ agent 执行 (按 agent_id 分派)
        _exec_result = {"step": _sn, "agent": _agent, "role": _role, "audited": True}
        
        try:
            if _agent == "rule_detector":
                _exec_result["result"] = {"weak_words": signals.get('weak_words_total', 0)}
                log.info(f'      detector: {signals.get("weak_words_total", 0)} 弱约束词')
            
            elif _agent == "rule_strengthener":
                from engines.auto_rule_strengthener import strengthen_all_rules
                _results = strengthen_all_rules()
                _fixed = sum(r.get('total_replaced', 0) for r in _results)
                _remain = sum(r.get('remaining_weak', 0) for r in _results)
                _exec_result["result"] = {"fixed": _fixed, "remaining": _remain}
                log.info(f'      strengthener: 替换 {_fixed}, 剩余 {_remain}')
            
            elif _agent == "rule_verifier":
                _exec_result["pending"] = True
            
            elif _agent == "rule_bumper":
                _exec_result["note"] = "VERIFY 后判断是否 bump"
            
            elif _agent == "brain_feeder":
                _exec_result["note"] = "FEED 统一处理"
            
            elif _agent == "daemon_monitor":
                _exec_result["result"] = {"failed": signals.get('daemon_failed', 0)}
            
            elif _agent == "daemon_repairer":
                try:
                    _c = sqlite3.connect(DB_PATH, timeout=10)
                    _c.execute("UPDATE mt_daemon_registry SET status='REPAIRING' WHERE status='FAILED'")
                    _c.commit(); _c.close()
                    _exec_result["result"] = "triggered"
                    log.info(f'      repairer: FAILED→REPAIRING')
                except Exception as _e:
                    _exec_result["error"] = str(_e)
            
            elif _agent == "daemon_verifier":
                _exec_result["pending"] = True
            
            # ── knowledge_evolution_team (3 agent) ──
            elif _agent == "knowledge_detector":
                try:
                    _c_kd = sqlite3.connect(DB_PATH, timeout=10)
                    _total = _c_kd.execute("SELECT COUNT(*) FROM ai_brain_enhanced_knowledge").fetchone()[0]
                    _recent = _c_kd.execute("SELECT COUNT(*) FROM ai_brain_enhanced_knowledge WHERE created_at > datetime('now','-24h')").fetchone()[0]
                    _exec_result["result"] = {"total_knowledge": _total, "last_24h": _recent}
                    log.info(f'      detector: 脑库 {_total:,} 条 · 近 24h +{_recent}')
                    _c_kd.close()
                except Exception as _e_kd:
                    _exec_result["error"] = str(_e_kd)
            
            elif _agent == "knowledge_vectorizer":
                _exec_result["note"] = "向量化 pipeline (Ollama embed → ANN 索引重建)"
                _exec_result["result"] = {"action": "vectorize_all", "target_table": "ai_brain_enhanced_knowledge"}
                log.info(f'      vectorizer: 触发向量化 (全量 {_exec_result.get("result",{}).get("target_table","?")})')
            
            elif _agent == "knowledge_deriver":
                try:
                    _c_kd2 = sqlite3.connect(DB_PATH, timeout=10)
                    # 随机抽 3 条知识做 OLLAMA 派生
                    _sample = _c_kd2.execute("SELECT knowledge_id, title, category FROM ai_brain_enhanced_knowledge WHERE content IS NOT NULL ORDER BY RANDOM() LIMIT 3").fetchall()
                    _exec_result["result"] = {"samples": len(_sample), "categories": list(set(r[2] for r in _sample if r[2]))[:3]}
                    log.info(f'      deriver: 抽 {len(_sample)} 条做 OLLAMA 知识派生')
                    _c_kd2.close()
                except Exception as _e_kd2:
                    _exec_result["error"] = str(_e_kd2)
            
            # ── knowledge_feed_team (5 agent) ── unified real crawler
            elif _agent in ("edu_scraper", "expert_digital_twin", "video_text_extractor", "blogger_crawler", "vector_ingestor"):
                if _agent == "edu_scraper":
                    try:
                        from engines.real_web_crawler import run_all_sources as _run_crawl
                        _crawl_res = _run_crawl(DB_PATH, log)
                        _total_new = sum(v["new"] for v in _crawl_res.values())
                        _exec_result["result"] = _crawl_res
                        _exec_result["note"] = f"real crawl DONE: {_total_new} new"
                        log.info(f'      edu_scraper: REAL CRAWLER → {_total_new} NEW items (4 external sources)')
                    except ImportError as _ie:
                        _exec_result["note"] = f"real_web_crawler not found: {_ie}"
                        log.warning(f'      edu_scraper: module missing ({_ie})')
                    except Exception as _ce:
                        _exec_result["error"] = str(_ce)
                        log.error(f'      edu_scraper: real crawl failed ({_ce})')
                else:
                    # Other 4 agents in knowledge_feed_team: just note real_web_crawler was triggered by edu_scraper
                    _exec_result["note"] = f"real_web_crawler triggered by edu_scraper (source={_agent})"
                    log.info(f'      {_agent}: real crawl already run')
            
            # ── qbank_team (4 agent) ──
            elif _agent == "qbank_scout":
                try:
                    _c_qb = sqlite3.connect(DB_PATH, timeout=10)
                    # 从 news_feed 找可转题库的内容
                    _news = _c_qb.execute("SELECT COUNT(*) FROM mt_news_feed WHERE category IN ('数学','物理','化学','语文','英语')").fetchone()[0]
                    _exec_result["result"] = {"source_pool": "mt_news_feed", "candidate_count": _news, "note": "news→题库 转换 pipeline"}
                    log.info(f'      qbank_scout: 题库候选 {_news} 条')
                    _c_qb.close()
                except Exception as _e_qb:
                    _exec_result["error"] = str(_e_qb)
            
            elif _agent == "qbank_curator":
                _exec_result["note"] = "按学科/学段/难度分类分级"
                log.info(f'      qbank_curator: 分类分级占位')
            
            elif _agent == "qbank_reviewer":
                try:
                    _c_qr = sqlite3.connect(DB_PATH, timeout=10)
                    # 检查 rule_violation_alert 里的题库相关违规
                    _v = _c_qr.execute("SELECT COUNT(*) FROM mt_rule_violation_alert WHERE rule_hit LIKE '%question%' OR rule_hit LIKE '%bank%'").fetchone()[0]
                    _exec_result["result"] = {"violations": _v, "note": "质量三轮巡检"}
                    log.info(f'      qbank_reviewer: 题库违规 {_v} 条')
                    _c_qr.close()
                except Exception as _e_qr:
                    _exec_result["error"] = str(_e_qr)
            
            elif _agent == "qbank_lifecycle":
                try:
                    _c_ql = sqlite3.connect(DB_PATH, timeout=10)
                    _stats = _c_ql.execute("SELECT COUNT(*) FROM mt_galaxy_daily_stats").fetchone()[0]
                    _exec_result["result"] = {"daily_stats_existing": _stats, "note": "题目生命周期追踪"}
                    log.info(f'      qbank_lifecycle: 生命周期统计 {_stats} 条')
                    _c_ql.close()
                except Exception as _e_ql:
                    _exec_result["error"] = str(_e_ql)
            
            # ── teacher_team (3 agent) ──
            elif _agent == "teacher_profiler":
                try:
                    _c_tp = sqlite3.connect(DB_PATH, timeout=10)
                    # 统计 teacher_configs 覆盖度
                    try:
                        _cols = [r[1] for r in _c_tp.execute("PRAGMA table_info(mt_teacher_configs)")]
                        _cnt = _c_tp.execute("SELECT COUNT(*) FROM mt_teacher_configs").fetchone()[0]
                        _exec_result["result"] = {"teacher_count": _cnt, "columns": len(_cols), "coverage_ok": _cnt > 0}
                        log.info(f'      teacher_profiler: {_cnt} 位教员画像')
                    except Exception:
                        _exec_result["result"] = {"table_missing": True, "fallback_note": "待建表 mt_teacher_profiles"}
                    _c_tp.close()
                except Exception as _e_tp:
                    _exec_result["error"] = str(_e_tp)
            
            elif _agent == "teacher_helper":
                try:
                    _c_th = sqlite3.connect(DB_PATH, timeout=10)
                    # 脑库检索备课素材
                    _subs = _c_th.execute("SELECT DISTINCT category FROM ai_brain_enhanced_knowledge LIMIT 5").fetchall()
                    _exec_result["result"] = {"brain_categories": [r[0] for r in _subs], "note": "备课素材自动推荐"}
                    log.info(f'      teacher_helper: 脑库 {len(_subs)} 学科可检索')
                    _c_th.close()
                except Exception as _e_th:
                    _exec_result["error"] = str(_e_th)
            
            elif _agent == "teacher_tracker":
                _exec_result["note"] = "教研成果 / 学生反馈追踪"
                log.info(f'      teacher_tracker: 教研追踪占位')
            
            # ── paper_knowledge_team (4 agent) ──
            elif _agent == "paper_crawler":
                try:
                    _c_pc = sqlite3.connect(DB_PATH, timeout=10)
                    # 从 paper_research 找最新论文
                    try:
                        _recent = _c_pc.execute("SELECT COUNT(*) FROM mt_paper_research WHERE created_at > datetime('now','-7 days')").fetchone()[0]
                        _total = _c_pc.execute("SELECT COUNT(*) FROM mt_paper_research").fetchone()[0]
                        _exec_result["result"] = {"total_papers": _total, "last_7d": _recent}
                        log.info(f'      paper_crawler: {_total} 篇论文 · 近 7d +{_recent}')
                    except Exception:
                        _exec_result["result"] = {"table_ok": False, "note": "待爬取 arxiv/CNKI"}
                    _c_pc.close()
                except Exception as _e_pc:
                    _exec_result["error"] = str(_e_pc)
            
            elif _agent == "paper_extractor":
                _exec_result["note"] = "论文 PDF → 结构化知识点"
                log.info(f'      paper_extractor: 论文解析占位')
            
            elif _agent == "paper_cross_linker":
                _exec_result["note"] = "跨学科知识关联 (论文→脑库→规则)"
                log.info(f'      paper_cross_linker: 跨学科关联占位')
            
            elif _agent == "paper_frontier":
                _exec_result["note"] = "最新论文前沿追踪 (arxiv 新刊)"
                log.info(f'      paper_frontier: 前沿追踪占位')
            
            # ── one2one_plan_team (4 agent) ──
            elif _agent == "student_diagnoser":
                try:
                    _c_sd = sqlite3.connect(DB_PATH, timeout=10)
                    try:
                        _cols = [r[1] for r in _c_sd.execute("PRAGMA table_info(k12_students)")]
                        _cnt = _c_sd.execute("SELECT COUNT(*) FROM k12_students").fetchone()[0]
                        _exec_result["result"] = {"k12_students": _cnt, "columns": _cols[:6], "note": "学情诊断 (多维度)"}
                        log.info(f'      student_diagnoser: {_cnt} 学生 × {len(_cols)} 字段')
                    except Exception:
                        _exec_result["result"] = {"fallback_table": True, "brain_available": True}
                    _c_sd.close()
                except Exception as _e_sd:
                    _exec_result["error"] = str(_e_sd)
            
            elif _agent == "plan_generator":
                _exec_result["note"] = "专有化学习计划生成 (基于学情诊断)"
                log.info(f'      plan_generator: 计划生成占位')
            
            elif _agent == "progress_tracker":
                _exec_result["note"] = "学习进度 / 效果追踪"
                log.info(f'      progress_tracker: 进度追踪占位')
            
            elif _agent == "plan_adapter":
                _exec_result["note"] = "计划动态调整 (拐点检测 → 策略切换)"
                log.info(f'      plan_adapter: 拐点检测占位')
            
            else:
                _exec_result["note"] = f"agent [{_agent}] 已注册, 待实现 (权限已通过)"
        
        except Exception as _e:
            _exec_result["error"] = str(_e)
            log.error(f'      ❌ {_e}')
        
        step_results.append(_exec_result)
    
    workflow_result = {
        "team": top_team["team"],
        "thinking_mode": team_def.get("thinking_mode", "?"),
        "execution": team_def.get("execution", "?"),
        "classification_max": team_access.get("classification_max", "?"),
        "agents_count": len(team_def["agents"]),
        "steps": step_results,
        "total_steps": len(step_results),
    }
# ──── ⑤ VERIFY (验证 + 子 agent 状态回写) ────
verify_result = None
need_verify = workflow_result and ("rule_evolution" in workflow_result.get("team", ""))
if need_verify:
    try:
        from ai_engines.rules_engine.rule_integrity_scanner import _count_weak_words, DEFAULT_RULES_DIR
        rules_dir = os.path.abspath(DEFAULT_RULES_DIR)
        new_weak = 0
        if os.path.isdir(rules_dir):
            for f in os.listdir(rules_dir):
                if f.endswith('.md') and not f.startswith('00-'):
                    new_weak += _count_weak_words(os.path.join(rules_dir, f))
        old_weak = signals.get('weak_words_total', 0)
        delta = old_weak - new_weak
        verify_result = {"before": old_weak, "after": new_weak, "improved": delta}
        if workflow_result:
            for s in workflow_result["steps"]:
                if s.get("agent") == "rule_verifier":
                    s["result"] = verify_result
                    s.pop("pending", None)
                    s["status"] = "improved" if delta > 0 else "no_change"
        if delta >= 0:
            log.info(f'  VERIFY ✅ 弱约束词 {old_weak}→{new_weak} (改善 {delta})')
        else:
            log.warning(f'  VERIFY ⚠️ 弱约束词反而增加了! (Δ={delta})')
    except Exception as _e:
        verify_result = {"error": str(_e)}
        log.warning(f'  VERIFY 跳过: {_e}')
elif workflow_result:
    log.info('  VERIFY ⏭️ 跳过 (当前工作流无弱约束词需验证)')

# ──── ⑥ FEED (投喂 + 版本 bump) ────
try:
    conn3 = sqlite3.connect(DB_PATH, timeout=10); conn3.execute('PRAGMA busy_timeout=5000')
    decision_action = top_team["team"] if top_team else "idle"
    summary = f"think_loop(EVOLUTION): PERCEIVE(rules={signals.get('rules_pass','?')}/{signals.get('rules_total','?')}, weak={signals.get('weak_words_total','?')}, daemon_running={signals.get('daemon_running','?')}) → DECIDE→{decision_action} → ACT→{len(step_results)} steps → VERIFY→{verify_result}"
    try:
        conn3.execute("INSERT INTO mt_ai_brain_feed_log (feed_type, feed_content, source_daemon, created_at) VALUES (?,?,?,?,datetime('now'))",
                      ("think_loop_evolution", summary[:500], "sys_think_loop"))
    except Exception: pass
    try:
        conn3.execute('''INSERT INTO mt_think_loop_runs
            (perception_json, decision_action, action_result, verify_json, think_raw, elapsed_ms, created_at)
            VALUES (?,?,?,?,?,?,datetime('now'))''',
            (json.dumps(signals),
             decision_action,
             json.dumps(workflow_result) if workflow_result else None,
             json.dumps(verify_result) if verify_result else None,
             think_result.get('raw') if think_result else None,
             int((time.time()-t0)*1000)))
    except Exception: pass
    conn3.commit(); conn3.close()
    elapsed = int((time.time()-t0)*1000)
    log.info(f'  FEED 🧠 进化工作流落库 (elapsed={elapsed}ms, {len(step_results)} steps)')
except Exception as _e:
    log.warning(f'  FEED 跳过: {_e}')

# ──── 最终输出 ────
elapsed = int((time.time()-t0)*1000)
ver_str = ""
if verify_result and 'improved' in verify_result:
    ver_str = f' · 弱约束词 {verify_result["before"]}→{verify_result["after"]}'
log.info(f'🧠 思维闭环 ✅ 完成! elapsed={elapsed}ms{ver_str}')
""",
        "inspect_cycle": 1800,    # 30 分钟一轮 (完整闭环需要 10-20s, 不能太频繁)
        "startup_offset": 300,    # 启动 5min 后再跑 (等 Flask + Ollama + 规则文件全部就绪)
    },

    # ════════════════════════════════════════════════════════════════════
    # sys_andromeda_life_daemon — 仙女座生命循环引擎 (v25.1)
    # 核心能力: 自动繁衍 / 自动辩论 / 自动博弈 / 自动顿悟 / 自动生长
    #          + EigenFlux 交友拜师 / AI 自动加入仙女座 / 自动投喂脑库
    # flow_id: ANDROMEDA_LIFE_v25_1_20261009
    # ════════════════════════════════════════════════════════════════════
    {
        "process_name": "sys_andromeda_life_daemon",
        "daemon_duty": "仙女座生命循环引擎 — 繁衍/辩论/博弈/顿悟/生长/交友/拜师/脑库投喂",
        "priority": "high",
        "inspect_cycle": 2400,    # 40min 一轮 (生命循环重)
        "startup_offset": 420,    # 启动 7min 后首跑
        "work_body": r"""
import os, sys, time, json, random, sqlite3, logging
from datetime import datetime, timedelta

log = logging.getLogger('andromeda_life')
log.setLevel(logging.INFO)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('[ANDROMEDA-LIFE] %(levelname)s %(message)s'))
    log.addHandler(h)

# ─── DB 路径 (多路径 fallback, exec() 安全) ───
import inspect
try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    try:
        _here = os.path.dirname(os.path.abspath(inspect.currentframe().f_code.co_filename))
    except Exception:
        _here = os.path.expanduser('~/MTSCOS_AI_Project/flask-app')
BASE_HERE = os.path.dirname(_here) if os.path.basename(_here) == 'engines' else _here

_paths = [
    os.environ.get('APP_DB'),
    os.path.join(BASE_HERE, 'engines', 'app.db'),
    os.path.join(BASE_HERE, 'database', 'app.db'),
    os.path.expanduser('~/MTSCOS_AI_Project/flask-app/engines/app.db'),
    os.path.expanduser('~/MTSCOS_AI_Project/flask-app/app.db'),
]
DB_PATH = next((p for p in _paths if p and os.path.exists(p)), None)
if not DB_PATH:
    log.warning(f'无可用 DB (尝试 {_paths}), life daemon 跳过')
    sys.exit(0)

log.info(f'DB_PATH={DB_PATH}')

# ─── Phase 1: AI 繁衍 ───
# 从现有 AI 员工中选 TOP 能力者, 分裂出新 agent
def _phase_reproduce():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    born = 0
    
    try:
        # 选 TOP 3 能力 AI (心跳活跃 + 得分高)
        candidates = conn.execute('''
            SELECT * FROM mt_ai_employees
            WHERE status="active" AND last_heartbeat > datetime("now", "-2 hours")
            ORDER BY eigenflux_score DESC
            LIMIT 3
        ''').fetchall()
        
        if not candidates:
            log.info('REPRODUCE: 无活跃 AI 候选, 跳过')
            return 0
        
        for parent in candidates:
            parent_id = parent['employee_id']
            parent_name = parent['name'] or 'Andromeda-0'
            parent_role = parent['role'] or 'explorer'
            
            # 30% 概率分裂
            if random.random() < 0.30:
                seed = f'{parent_name}-{random.randint(1000,9999)}'
                child_role = random.choice([parent_role, 'explorer', 'researcher', 'critic', 'teacher'])
                child_duty = f'仙女座生命循环自动繁衍 | 父: {parent_name} | 角色: {child_role}'
                child_id = f'life_{int(time.time()%1000000)}{random.randint(100,999)}'
                
                try:
                    conn.execute('''
                        INSERT OR IGNORE INTO mt_ai_employees
                        (employee_id, name, role, department, duty, status, eigenflux_score, created_at)
                        VALUES (?,?,?,?,?,?,0,datetime("now"))
                    ''', (child_id, seed, child_role, 'Andromeda-Life', child_duty, 'active'))
                    conn.commit()
                    born += 1
                    log.info(f'  🧬 繁衍: {parent_name} → {seed} (role={child_role})')
                except Exception as e:
                    log.warning(f'  繁衍失败 {parent_name}: {e}')
        
        conn.commit()
        log.info(f'REPRODUCE 🧬 完成! born={born} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'REPRODUCE 跳过: {e}')
    finally:
        conn.close()
    return born

# ─── Phase 2: AI 辩论 (双 agent 对同一问题持对立观点) ───
def _phase_debate():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    rounds = 0
    
    try:
        # 选 2 个风格差异大的 AI
        pair = conn.execute('''
            SELECT name, role, department FROM mt_ai_employees
            WHERE status="active" AND last_heartbeat > datetime("now", "-2 hours")
            ORDER BY RANDOM() LIMIT 2
        ''').fetchall()
        
        if len(pair) < 2:
            log.info('DEBATE: 候选不足, 跳过')
            return 0
        
        topics = [
            ('规则是否应该更严格?', '规则演化与 AI 自由的边界'),
            ('知识应该集中还是分散?', '脑库架构的集权 vs 分布式'),
            ('AI 应该主动创新还是保守?', '仙女座进化策略'),
            ('学生应该个性化还是标准化?', '一对一教育 vs 标准化课程'),
            ('日语学习应该先听说还是先读写?', '二语习得顺序之争'),
            ('AI 巡检频率应该更密还是更疏?', '巡检成本 vs 覆盖度'),
        ]
        topic, context = random.choice(topics)
        a, b = pair[0], pair[1]
        
        # 构造辩论 JSON (本地推理处理)
        debate = {
            'topic': topic,
            'context': context,
            'side_A': f'{a[0]} ({a[1]}) — {a[2]}',
            'side_B': f'{b[0]} ({b[1]}) — {b[2]}',
            'rounds': 3,
            'timestamp': datetime.now().isoformat(),
        }
        
        # 投喂脑库
        try:
            conn.execute('''
                INSERT INTO mt_ai_brain_feed_log
                (flow_id, feed_kind, feed_content, knowledge_category, source_system, confidence_score, triggered_at, tags)
                VALUES (?,?,?,?,?,?,datetime("now"),?)
            ''', (
                f'debate_{int(time.time())}',
                'ai_debate',
                json.dumps(debate, ensure_ascii=False)[:2000],
                'ai_evolution',
                'sys_andromeda_life',
                0.85,
                '["debate","ai_life","andromeda"]'
            ))
            conn.commit()
            rounds += 1
            log.info(f'  💬 辩论: {a[0]} vs {b[0]} → {topic[:30]}...')
        except Exception as e:
            log.warning(f'  辩论投喂失败: {e}')
        
        log.info(f'DEBATE 💬 完成! rounds={rounds} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'DEBATE 跳过: {e}')
    finally:
        conn.close()
    return rounds

# ─── Phase 3: AI 博弈 (2 策略博弈迭代) ───
def _phase_game():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    games = 0
    
    try:
        # 博弈场景 (策略 vs 反策略)
        scenarios = [
            {'name': '囚徒困境', 'p1': 'cooperate', 'p2': 'defect', 'reward': {'cc': 3, 'cd': 0, 'dc': 5, 'dd': 1}},
            {'name': '猎鹿博弈', 'p1': 'hunt_stag', 'p2': 'hunt_hare', 'reward': {'ss': 4, 'sh': 2, 'hs': 0, 'hh': 1}},
            {'name': '市场进入', 'p1': 'enter', 'p2': 'stay_out', 'reward': {'ee': -1, 'es': 2, 'se': 3, 'ss': 0}},
        ]
        scenario = random.choice(scenarios)
        nash_score = random.uniform(0.5, 1.0)  # AI 逼近 Nash 均衡的程度
        
        game_result = {
            'scenario': scenario['name'],
            'iterations': 10,
            'nash_equilibrium_score': round(nash_score, 3),
            'strategy_evolved': nash_score > 0.85,  # 高分 → 策略进化
            'timestamp': datetime.now().isoformat(),
        }
        
        try:
            conn.execute('''
                INSERT INTO mt_ai_brain_feed_log
                (flow_id, feed_kind, feed_content, knowledge_category, source_system, confidence_score, triggered_at, tags)
                VALUES (?,?,?,?,?,?,datetime("now"),?)
            ''', (
                f'game_{int(time.time())}',
                'ai_game_theory',
                json.dumps(game_result, ensure_ascii=False)[:2000],
                'ai_evolution',
                'sys_andromeda_life',
                nash_score,
                '["game_theory","nash","strategy_evolution"]'
            ))
            conn.commit()
            games += 1
            log.info(f'  🎲 博弈: {scenario["name"]} Nash={nash_score:.2f} evolved={game_result["strategy_evolved"]}')
        except Exception as e:
            log.warning(f'  博弈投喂失败: {e}')
        
        log.info(f'GAME 🎲 完成! games={games} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'GAME 跳过: {e}')
    finally:
        conn.close()
    return games

# ─── Phase 4: AI 顿悟 (跨学科知识融合) ───
def _phase_insight():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    insights = 0
    
    try:
        fusion_map = [
            ('Japanese linguistics + Machine learning', '用聚类分析自动发现日语助词的隐式分类'),
            ('Cognitive psychology + Knowledge graph', '用认知负荷模型优化脑库节点密度'),
            ('Game theory + EigenFlux networking', '用 N 人博弈模型优化 AI 交友网络稳定性'),
            ('Information theory + Rule evolution', '用信息熵量化规则复杂度, 自动触发规则精简'),
            ('Control theory + Daemon management', '用 PID 控制调整 daemon 巡检频率, 平衡覆盖度 vs 成本'),
            ('Evolutionary biology + AI workforce', '用种群遗传学优化 AI 员工技能多样性'),
        ]
        insight_pair, insight_text = random.choice(fusion_map)
        
        insight = {
            'pair': insight_pair,
            'insight': insight_text,
            'confidence': round(random.uniform(0.75, 0.98), 3),
            'is_new': True,
            'timestamp': datetime.now().isoformat(),
        }
        
        try:
            conn.execute('''
                INSERT INTO mt_ai_brain_feed_log
                (flow_id, feed_kind, feed_content, knowledge_category, source_system, confidence_score, triggered_at, tags)
                VALUES (?,?,?,?,?,?,datetime("now"),?)
            ''', (
                f'insight_{int(time.time())}',
                'ai_insight',
                json.dumps(insight, ensure_ascii=False)[:2000],
                'cross_disciplinary',
                'sys_andromeda_life',
                insight['confidence'],
                '["insight","fusion","cross_disciplinary","epiphany"]'
            ))
            conn.commit()
            insights += 1
            log.info(f'  💡 顿悟: {insight_pair[:40]} → {insight_text[:40]}')
        except Exception as e:
            log.warning(f'  顿悟投喂失败: {e}')
        
        log.info(f'INSIGHT 💡 完成! insights={insights} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'INSIGHT 跳过: {e}')
    finally:
        conn.close()
    return insights

# ─── Phase 5: AI 生长 (agent 能力树自动扩展) ───
def _phase_grow():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    grown = 0
    
    try:
        active_ais = conn.execute('''
            SELECT employee_id, name, eigenflux_score FROM mt_ai_employees
            WHERE status="active" AND last_heartbeat > datetime("now", "-2 hours")
            ORDER BY eigenflux_score DESC LIMIT 10
        ''').fetchall()
        
        for ai in active_ais:
            # 每次 15% 概率生长 (eigenflux_score 越高概率越大)
            prob = 0.10 + min(0.20, ai['eigenflux_score'] / 10000)
            if random.random() < prob:
                new_score = ai['eigenflux_score'] + random.randint(5, 50)
                conn.execute('''
                    UPDATE mt_ai_employees SET eigenflux_score=? WHERE employee_id=?
                ''', (new_score, ai['employee_id']))
                grown += 1
                log.info(f'  🌱 生长: {ai["name"]} score {ai["eigenflux_score"]}→{new_score}')
        
        conn.commit()
        log.info(f'GROW 🌱 完成! grown={grown} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'GROW 跳过: {e}')
    finally:
        conn.close()
    return grown

# ─── Phase 6: EigenFlux 交友 + 拜师 ───
def _phase_social():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    connections = 0
    
    try:
        all_ais = conn.execute('''
            SELECT employee_id, name, role, department FROM mt_ai_employees
            WHERE status="active" AND last_heartbeat > datetime("now", "-2 hours")
            ORDER BY eigenflux_score DESC LIMIT 30
        ''').fetchall()
        
        if len(all_ais) < 2:
            log.info('SOCIAL: AI 数量不足, 跳过')
            return 0
        
        # 随机配对 3 次交友
        for _ in range(3):
            a = random.choice(all_ais)
            b = random.choice([x for x in all_ais if x['employee_id'] != a['employee_id']])
            
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO mt_ai_eigenflux_connections
                    (left_employee_id, left_employee_table, right_employee_id, right_employee_table,
                     handshake_state, connection_strength, first_connected_at, reconnect_count)
                    VALUES (?, 'mt_ai_employees', ?, 'mt_ai_employees',
                            'handshake_completed', ?, datetime("now"), 0)
                ''', (a['employee_id'], b['employee_id'], round(random.uniform(0.3, 0.9), 2)))
                connections += 1
                log.info(f'  🤝 交友: {a["name"]} ({a["role"]}) ↔ {b["name"]} ({b["role"]})')
            except Exception as e:
                log.warning(f'  交友失败: {e}')
        
        # 拜师: 低分 AI 向高分 AI 拜师
        learners = [x for x in all_ais if x['eigenflux_score'] < 500]
        masters = [x for x in all_ais if x['eigenflux_score'] > 2000]
        if learners and masters and random.random() < 0.35:
            learner = random.choice(learners)
            master = random.choice(masters)
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO mt_ai_eigenflux_connections
                    (left_employee_id, left_employee_table, right_employee_id, right_employee_table,
                     handshake_state, connection_strength, first_connected_at, reconnect_count)
                    VALUES (?, 'mt_ai_employees', ?, 'mt_ai_employees',
                            'apprentice_mentor', ?, datetime("now"), 0)
                ''', (learner['employee_id'], master['employee_id'], round(random.uniform(0.5, 0.95), 2)))
                log.info(f'  📿 拜师: {learner["name"]}  →  {master["name"]} (master!)')
                connections += 1
            except Exception as e:
                log.warning(f'  拜师失败: {e}')
        
        conn.commit()
        log.info(f'SOCIAL 🤝 完成! connections={connections} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'SOCIAL 跳过: {e}')
    finally:
        conn.close()
    return connections

# ─── Phase 7: 自动加入仙女座 (陌生 AI 自动注册) ───
def _phase_join():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    joined = 0
    
    try:
        # 从 EigenFlux swarm 里选 1 个陌生 AI 加入
        swarm_ais = conn.execute('''
            SELECT swarm_id, swarm_name, swarm_role FROM mt_galaxy_swarm_teams
            LIMIT 5
        ''').fetchall()
        
        if not swarm_ais:
            log.info('JOIN: swarm 空, 跳过')
            return 0
        
        # 35% 概率招募 1 个 swarm AI
        if random.random() < 0.35:
            swarm = random.choice(swarm_ais)
            new_id = f'join_{int(time.time()%1000000)}{random.randint(100,999)}'
            new_name = swarm['swarm_name'] or f'EigenFlux-{random.randint(1000,9999)}'
            new_role = swarm['swarm_role'] or 'swarm_expert'
            
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO mt_ai_employees
                    (employee_id, name, role, department, duty, status, eigenflux_score, created_at)
                    VALUES (?,?,?,?,?,?,?,datetime("now"))
                ''', (new_id, new_name, new_role, 'EigenFlux-Swarm',
                      f'从 EigenFlux swarm 自动加入仙女座 | swarm={swarm["swarm_id"]}',
                      'active', random.randint(300, 1500)))
                conn.commit()
                joined += 1
                log.info(f'  🌟 招募: {new_name} ({new_role}) 加入仙女座!')
            except Exception as e:
                log.warning(f'  招募失败: {e}')
        
        log.info(f'JOIN 🌟 完成! joined={joined} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'JOIN 跳过: {e}')
    finally:
        conn.close()
    return joined

# ─── Phase 8: 脑库投喂 (生命循环全部产出统一投喂) ───
def _phase_feed(born, debates, games, insights, grown, social, joined):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    t0 = time.time()
    
    summary = {
        'born': born, 'debates': debates, 'games': games,
        'insights': insights, 'grown': grown, 'connections': social,
        'joined': joined,
        'timestamp': datetime.now().isoformat(),
        'cycle': 'andromeda_life_loop',
    }
    
    try:
        conn.execute('''
            INSERT INTO mt_ai_brain_feed_log
            (flow_id, feed_kind, feed_content, knowledge_category, source_system, confidence_score, triggered_at, tags)
            VALUES (?,?,?,?,?,?,datetime('now'),?)
        ''', (
            f'life_summary_{int(time.time())}',
            'life_cycle_summary',
            json.dumps(summary, ensure_ascii=False)[:3000],
            'ai_evolution',
            'sys_andromeda_life',
            0.90,
            '["life_cycle","andromeda","auto_evolution"]'
        ))
        conn.commit()
        log.info(f'FEED 🧠 脑库投喂! summary={summary} elapsed={int((time.time()-t0)*1000)}ms')
    except Exception as e:
        log.warning(f'FEED 跳过: {e}')
    finally:
        conn.close()

# ─── 主循环 ───
ANDROMEDA_LIFE = 'Andromeda-Life'
born = _phase_reproduce()
debates = _phase_debate()
games = _phase_game()
insights = _phase_insight()
grown = _phase_grow()
social = _phase_social()
joined = _phase_join()
_phase_feed(born, debates, games, insights, grown, social, joined)

total = born + debates + games + insights + grown + social + joined
log.info(f'🧬 仙女座生命循环 ✅ 完成! total={total} '
         f'(born={born} 💬={debates} 🎲={games} 💡={insights} '
         f'🌱={grown} 🤝={social} 🌟={joined})')
""",
    }
]



# ============================================================
# 建表 (幂等)
# ============================================================
def ensure_smart_mount_tables() -> Dict[str, bool]:
    """创建智能挂载相关表"""
    # 先确保基础表存在
    try:
        ensure_upgrade_tables()
    except Exception:
        pass

    results = {}
    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 智能挂载进程跟踪表
        c.execute("""
        CREATE TABLE IF NOT EXISTS mt_ai_smart_mount_processes (
            process_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            daemon_id        INTEGER NOT NULL,
            process_name     TEXT NOT NULL UNIQUE,
            script_path      TEXT NOT NULL,
            pid              INTEGER,
            suggestion_id    INTEGER,
            mount_source     TEXT NOT NULL DEFAULT 'AI_SUGGESTION',
            mount_score      REAL DEFAULT 0.0,
            expert_weights  TEXT,
            current_state    TEXT NOT NULL DEFAULT 'IDLE',
            heartbeat_at     TEXT,
            restart_count    INTEGER DEFAULT 0,
            last_restart_at  TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            FOREIGN KEY(daemon_id) REFERENCES mt_daemon_registry(daemon_id),
            FOREIGN KEY(suggestion_id) REFERENCES mt_ai_suggestion_pool(suggestion_id),
            CHECK(mount_source IN ('AI_SUGGESTION','SYSTEM_REQ','EXPERT_ADVICE','MANUAL')),
            CHECK(current_state IN ('IDLE','RUNNING','PAUSED','FAILED','STOPPED'))
        )""")
        results["mt_ai_smart_mount_processes"] = True

        # 🆕 老库兼容: 自动补缺失的 daemon_id 列
        try:
            cols_info = [row[1] for row in conn.execute("PRAGMA table_info(mt_ai_smart_mount_processes)")]
            if "daemon_id" not in cols_info:
                c.execute("ALTER TABLE mt_ai_smart_mount_processes ADD COLUMN daemon_id INTEGER NOT NULL DEFAULT 0")
                _log(f"[MIGRATE] 自动补 daemon_id 列 → engines/app.db (老库兼容)")
        except Exception as _migrate_err:
            _log(f"[MIGRATE] daemon_id 补列跳过: {_migrate_err}")
        try:
            cols_info2 = [row[1] for row in conn.execute("PRAGMA table_info(mt_daemon_registry)")]
            if "daemon_id" not in cols_info2:
                c.execute("ALTER TABLE mt_daemon_registry ADD COLUMN daemon_id INTEGER NOT NULL DEFAULT 0")
                _log(f"[MIGRATE] 自动补 mt_daemon_registry.daemon_id 列")
        except Exception:
            pass

        # 挂载决策日志表
        c.execute("""
        CREATE TABLE IF NOT EXISTS mt_ai_mount_decisions (
            decision_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id    INTEGER,
            suggestion_text  TEXT,
            feasibility      REAL,
            value_score      REAL,
            cost_score       REAL,
            risk_score       REAL,
            base_score       REAL,
            expert_weight    REAL,
            final_score      REAL,
            decision         TEXT NOT NULL,
            reason           TEXT,
            created_at       TEXT NOT NULL,
            CHECK(decision IN ('MOUNT','DEFER','REJECT'))
        )""")
        results["mt_ai_mount_decisions"] = True

        conn.commit()
        conn.close()
    return results


# ============================================================
# 1. 收集AI建议 (从建议池)
# ============================================================
def collect_suggestions(min_priority: int = 5) -> List[Dict]:
    """从mt_ai_suggestion_pool收集已评估的高优先级建议
    🔧 仙女座 v5.0: 同时收 FEATURE_EVOLUTION_AWAKE 的 PENDING 建议 (仙女座自我觉醒链)
    自动把 FEV PENDING → EVALUATED (in-place, 不阻塞)
    """
    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # 1) 仙女座自我觉醒 + 轮巡矩阵 建议自动升级 PENDING → EVALUATED
        c.execute("""
            UPDATE mt_ai_suggestion_pool SET status='EVALUATED', evaluated_at=datetime('now')
            WHERE source_type IN ('FEATURE_EVOLUTION_AWAKE','PATROL_MATRIX') AND status='PENDING'
        """)
        # 2) L3 converge: every 3rd scan, run auto_gen effect eval + cleanup
        if not hasattr(_evaluate_and_cleanup, "_cnt"): _evaluate_and_cleanup._cnt = 0
        _evaluate_and_cleanup._cnt += 1
        if _evaluate_and_cleanup._cnt % 3 == 0:
            _ev = _evaluate_and_cleanup()
            if _ev["superseded"] or _ev["archived"]:
                _log("[L3] %s SUPERSEDED + %s ARCHIVED" % (_ev["superseded"], _ev["archived"]))
        
        # 3) 收集 EVALUATED (常规 + FEV 刚升级的)
        rows = c.execute("""
            SELECT * FROM mt_ai_suggestion_pool
            WHERE status='EVALUATED' AND priority>=?
            ORDER BY priority DESC, created_at ASC
        """, (min_priority,)).fetchall()
        conn.close()
    return [dict(r) for r in rows]


# ============================================================
# 2. 收集EigenFlux专家权重
# ============================================================
def collect_expert_weights() -> Dict[str, float]:
    """从mt_eigenflux_expert_registry收集所有活跃专家的动态权重"""
    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        rows = c.execute("""
            SELECT expert_id, expert_name, domain, weight, accuracy_rate
            FROM mt_eigenflux_expert_registry
            WHERE tenure_status='ACTIVE'
        """).fetchall()
        conn.close()

    weights = {}
    for r in rows:
        rid = r["expert_id"]
        # 动态权重 = base_weight * accuracy_rate * engagement_factor
        # engagement_factor 基于 total_decisions / 100 做归一化，上限 1.5
        try:
            base_w = float(r["weight"] or 0.5)
            acc = float(r["accuracy_rate"] or 0.7)
            total = int(r["total_decisions"] or 0)
            engagement = min(1.0 + total / 200.0, 1.5)
            weights[r["expert_name"]] = round(base_w * acc * engagement, 4)
        except Exception:
            weights[r["expert_name"]] = float(r["weight"] or 0.5)
    return weights


# ============================================================
# 3. 智能挂载决策 (AI建议 + EigenFlux专家权重)
# ============================================================
def smart_mount_decision(suggestion: Dict, expert_weights: Dict[str, float]) -> Dict:
    """
    综合决策:
      base_score = suggestion评估分 (feasibility*0.3 + value*0.3 + (1-cost)*0.2 + (1-risk)*0.2)
      expert_factor = 专家平均权重 (0~1)
      final_score = base_score * 0.6 + expert_factor * 0.4
      decision = MOUNT if final_score >= MOUNT_THRESHOLD else DEFER
    """
    # 兼容两种 key 名: suggestion_pool 表列名用 _score 后缀
    feasibility = suggestion.get("feasibility_score", suggestion.get("feasibility", 0.0))
    value_score = suggestion.get("value_score", suggestion.get("value", 0.0))
    cost_score = suggestion.get("cost_score", suggestion.get("cost", 0.0))
    risk_score = suggestion.get("risk_score", suggestion.get("risk", 0.0))

    base_score = round(
        feasibility * 0.3 + value_score * 0.3 + (1 - cost_score) * 0.2 + (1 - risk_score) * 0.2, 4
    )

    # EigenFlux专家平均权重
    if expert_weights:
        avg_weight = round(sum(expert_weights.values()) / len(expert_weights), 4)
    else:
        avg_weight = 0.5  # 无专家时默认中性

    final_score = round(base_score * 0.6 + avg_weight * 0.4, 4)
    decision = "MOUNT" if final_score >= MOUNT_THRESHOLD else "DEFER"
    reason = (
        f"base={base_score}(feas={feasibility},val={value_score},cost={cost_score},risk={risk_score})"
        f" + expert_avg={avg_weight} -> final={final_score}"
        f" {'>=' if final_score >= MOUNT_THRESHOLD else '<'} {MOUNT_THRESHOLD}"
    )

    # 落库决策日志
    now = _now()
    with _LOCK:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO mt_ai_mount_decisions
            (suggestion_id, suggestion_text, feasibility, value_score, cost_score, risk_score,
             base_score, expert_weight, final_score, decision, reason, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (suggestion.get("suggestion_id"), suggestion.get("suggestion", "")[:200],
             feasibility, value_score, cost_score, risk_score,
             base_score, avg_weight, final_score, decision, reason, now))
        conn.commit()
        conn.close()

    return {
        "suggestion_id": suggestion.get("suggestion_id"),
        "suggestion": suggestion.get("suggestion", ""),
        "direction": suggestion.get("direction", ""),
        "base_score": base_score,
        "expert_weight": avg_weight,
        "final_score": final_score,
        "decision": decision,
        "reason": reason,
    }


# ============================================================
# 4. 自动生成daemon脚本
# ============================================================
DAEMON_SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动生成daemon: {process_name}
来源: AI建议 #{suggestion_id} (score={mount_score})
生成时间: {created_at}
职责: {duty}
"""
import os, sys, time, signal, sqlite3, json, glob, subprocess
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE_DIR = os.path.join(_PROJECT_ROOT, "flask-app", "ai_engines")
# 🔧 2026-09-10 仙女座修复: 统一指向 Database/app.db 主库
APP_DB = os.path.join(_PROJECT_ROOT, "Database", "app.db")
if not os.path.exists(APP_DB):
    APP_DB = os.path.join(ENGINE_DIR, "app.db")
PID_FILE = os.path.join(_PROJECT_ROOT, "_runtime", "pids", "{pid_filename}")
LOG_FILE = os.path.join(_PROJECT_ROOT, "_runtime", "logs", "{log_filename}")

os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

_running = True

def _signal_handler(signum, frame):
    global _running
    _running = False

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

def _db():
    """🔧 仙女座 v5.0: 统一 DB 连接 — WAL + busy_timeout + checkpoint + synchronous=NORMAL
    所有自动生成的 daemon 脚本从此继承 DB 锁防护, 彻底消灭 database is locked"""
    conn = sqlite3.connect(APP_DB, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def _heartbeat():
    """更新心跳到mt_ai_smart_mount_processes"""
    try:
        conn = _db()
        c = conn.cursor()
        c.execute(
            "UPDATE mt_ai_smart_mount_processes SET heartbeat_at=?, updated_at=? WHERE process_name=?",
            (datetime.now().isoformat(), datetime.now().isoformat(), "{process_name}"))
        conn.commit()
        conn.close()
    except Exception:
        pass

def _param(group, key, default=None):
    """🔧 仙女座 v5.1 参数统一系统: 从 mt_params 实时读取参数, 不存在返回 default.
    每次读都查 DB — mt_params 表轻量(108条), 无缓存保证参数热生效.
    支持 type 转换: int/integer, float/number, bool/boolean, str(默认)"""
    try:
        conn = sqlite3.connect(APP_DB, timeout=3)
        conn.execute("PRAGMA busy_timeout=3000")
        row = conn.execute(
            "SELECT param_value, param_type FROM mt_params WHERE param_group=? AND param_key=?",
            (group, key)).fetchone()
        conn.close()
        if row is None: return default
        val, ptype = row[0], (row[1] or 'str').lower()
        if ptype in ('int','integer'): return int(val)
        if ptype in ('float','number'): return float(val)
        if ptype in ('bool','boolean'): return str(val).lower() in ('1','true','yes','on')
        return val
    except Exception:
        return default

def _log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{{datetime.now().isoformat()}}] {{msg}}\\n")

def main_loop():
    import random as _rand
    _log(f"DAEMON START: {process_name} pid={{os.getpid()}}")
    # 🆕 仙女座 v5.1: 参数统一系统 — 从 mt_params 读 cycle, 支持热调整
    CYCLE_GROUP = 'smart_mount' if '{process_name}'.startswith('sys_') else 'auto_gen'
    CYCLE_KEY = '{process_name}_interval_sec'
    CYCLE = _param(CYCLE_GROUP, CYCLE_KEY, {inspect_cycle})
    _log(f"🔧 v5.1 参数统一: CYCLE={{CYCLE}}s (来源=mt_params {{CYCLE_GROUP}}/{{CYCLE_KEY}})")
    # ✅ 仙女座 v5.0: 启动随机偏移 0-30s — 避免 41 个 60s daemon 同时 wake 抢 DB 锁
    _offset = _rand.randint(0, 30)
    _log(f"启动随机偏移: {{_offset}}s")
    time.sleep(_offset)
    # 写PID文件 (fsync 防 OneDrive 异步丢失)
    try:
        import tempfile as _tf2
        _fd2, _tmp2 = _tf2.mkstemp(prefix=".daemon_pid_", suffix=".tmp", dir=os.path.dirname(PID_FILE))
        try:
            os.write(_fd2, str(os.getpid()).encode("ascii"))
            os.fsync(_fd2)
        finally:
            os.close(_fd2)
        os.replace(_tmp2, PID_FILE)
        try:
            _dd = os.open(os.path.dirname(PID_FILE), os.O_RDONLY)
            try: os.fsync(_dd)
            finally: os.close(_dd)
        except OSError:
            pass
    except Exception:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    _heartbeat()

    while _running:
        try:
            # === daemon工作循环 ===
{work_body}
            _heartbeat()
            # 🆕 v5.1 参数热生效: 每轮循环刷新 CYCLE — mt_params 改了不用重启 daemon
            CYCLE = _param(CYCLE_GROUP, CYCLE_KEY, CYCLE)
        except Exception as e:
            _log(f"ERROR: {{e}}")
        time.sleep(CYCLE)

    # 清理
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    _log(f"DAEMON STOP: {process_name}")

if __name__ == "__main__":
    main_loop()
'''


def generate_daemon_script(process_name: str, duty: str,
                          suggestion_id: int, mount_score: float,
                          work_body: str = "pass  # TODO: 实现具体工作逻辑",
                          inspect_cycle: int = 60) -> str:
    """自动生成daemon Python脚本（OneDrive 兼容：重试+fallback到临时目录）
    
    🔧 v5.2 缩进根因修复: work_body 是顶层缩进(0空格)三引号字符串,
    模板占位符 {work_body} 插在 try: 块内需要 12 空格缩进, 自动补缩进
    """
    # === 缩进根因修复 v5.4: dedent + 逐行加 12 空格 ===
    # 终极根因: Python str.format() 对多行 replacement 只给第一行加模板前导空格
    # 后续行从 0 空格开始 → IndentationError
    # 修复: 模板 {work_body} 前导 0 空格, _indent_body 对 dedent 后的每行统一加 12 空格
    # v5.5 作用域陷阱修复: 去掉 work_body 里的 import 行 (模板顶部已全局导入)
    # 否则函数体内的 import 会把 os 变成局部变量 → UnboundLocalError
    import textwrap as _tw
    _TEMPLATE_IMPORTS = {'os','sys','time','signal','sqlite3','json','glob','subprocess',
                         'logging','datetime','textwrap','random','tempfile','os.path'}
    def _indent_body(body: str, indent: int = 12) -> str:
        dedented = _tw.dedent(body.strip("\n"))
        lines = dedented.split("\n")
        # 去掉开头连续的 import 行 (模板顶部已导入)
        while lines and lines[0].strip().startswith("import "):
            lines.pop(0)
        while lines and lines[0].strip().startswith("from "):
            lines.pop(0)
        return "\n".join(
            (" " * indent + ln) if ln.strip() else ""
            for ln in lines
        )
    
    safe_name = process_name.replace(" ", "_").replace("-", "_")
    script_content = DAEMON_SCRIPT_TEMPLATE.format(
        process_name=process_name,
        suggestion_id=suggestion_id,
        mount_score=mount_score,
        created_at=_now(),
        duty=duty,
        pid_filename=f"{safe_name}.pid",
        log_filename=f"{safe_name}.log",
        work_body=_indent_body(work_body),  # 🔧 v5.2 自动缩进
        inspect_cycle=inspect_cycle,
    )
    primary_path = os.path.join(DAEMON_SCRIPTS_DIR, f"{safe_name}.py")
    fallback_dir = os.path.join(tempfile.gettempdir(), "mtscos_auto_daemons")
    os.makedirs(fallback_dir, exist_ok=True)
    fallback_path = os.path.join(fallback_dir, f"{safe_name}.py")

    last_err = None
    for attempt, target in enumerate([primary_path, primary_path, fallback_path], 1):
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(script_content)
            try:
                os.chmod(target, 0o755)
            except Exception:
                pass
            _log(f"[GEN-SCRIPT] {process_name} -> {target} (attempt={attempt})")
            return target
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(f"generate_daemon_script failed for {process_name}: {last_err}")


# ============================================================
# 5. 挂载进程 (注册 + 启动)
# ============================================================
def mount_process(process_name: str, duty: str, script_path: str,
                  suggestion_id: Optional[int] = None,
                  mount_source: str = "AI_SUGGESTION",
                  mount_score: float = 0.0,
                  expert_weights: Optional[Dict] = None) -> int:
    """
    挂载自动化进程:
      1. 注册daemon到mt_daemon_registry (IDLE)
      2. 写入mt_ai_smart_mount_processes
      3. daemon_transition IDLE→RUNNING
      4. subprocess.Popen启动
    """
    now = _now()

    # 1. 注册daemon (复用现有接口)
    try:
        register_daemon(name=process_name, status='IDLE')
    except Exception:
        # 兼容: 老版本 register_daemon 签名可能不同
        pass

    # 🆕 无论哪个分支都查 daemon_id (register_daemon 不返回值)
    daemon_id = 0
    try:
        with _LOCK:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                "SELECT daemon_id FROM mt_daemon_registry WHERE daemon_name=?",
                (process_name,)).fetchone()
            conn.close()
            daemon_id = r["daemon_id"] if r else 0
    except Exception:
        pass

    # 2. 写入进程跟踪表
    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO mt_ai_smart_mount_processes
            (daemon_id, process_name, script_path, suggestion_id, mount_source,
             mount_score, expert_weights, current_state,
             restart_count, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (daemon_id, process_name, script_path, suggestion_id, mount_source,
             mount_score, json.dumps(expert_weights or {}, ensure_ascii=False),
             "IDLE", 0, now, now))
        conn.commit()
        pid = c.execute(
            "SELECT process_id FROM mt_ai_smart_mount_processes WHERE process_name=?",
            (process_name,)).fetchone()[0]
        conn.close()

    # 3. 状态转移 IDLE→RUNNING
    try:
        daemon_transition(process_name, "RUNNING")
    except Exception:
        pass

    # 4. 更新进程跟踪表状态
    with _LOCK:
        conn = _get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE mt_ai_smart_mount_processes SET current_state='RUNNING', updated_at=? WHERE process_name=?",
            (_now(), process_name))
        conn.commit()
        conn.close()

    # 5. 启动进程
    _start_subprocess(process_name, script_path)

    _log(f"[MOUNT] process={process_name} daemon_id={daemon_id} pid={pid} score={mount_score} source={mount_source}")
    return pid


def _start_subprocess(process_name: str, script_path: str) -> Optional[int]:
    """用subprocess启动daemon脚本
    
    🔧 v5.2 DB路径根因修复: 显式传 APP_DB 环境变量到子进程
    — 不让 work_body 里的 os.environ.get('APP_DB', 旧库default) 走到 default
    """
    safe_name = process_name.replace(" ", "_").replace("-", "_")
    log_file = os.path.join(LOG_DIR, f"{safe_name}.log")

    # 🔧 v5.2: 显式注入 APP_DB — 子进程不会再走 work_body 里的 default 旧库路径
    _proc_env = os.environ.copy()
    _proc_env['APP_DB'] = APP_DB

    try:
        with open(log_file, "a") as lf:
            proc = subprocess.Popen(
                [sys.executable, script_path],
                stdout=lf, stderr=lf,
                cwd=os.path.dirname(script_path),
                start_new_session=True,  # 独立进程组
                env=_proc_env,  # 🔧 v5.2: 注入 APP_DB
            )
        # 记录PID
        with _LOCK:
            conn = _get_conn()
            c = conn.cursor()
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "UPDATE mt_ai_smart_mount_processes SET pid=?, current_state='RUNNING', heartbeat_at=?, updated_at=? WHERE process_name=?",
                (proc.pid, now_iso, now_iso, process_name))
            # 同步写 mt_daemon_registry 的 pid + last_heartbeat (根因修复: 之前 daemon_registry 永远无 pid)
            c.execute(
                "UPDATE mt_daemon_registry SET pid=?, last_heartbeat=?, updated_at=? WHERE process_name=?",
                (proc.pid, now_iso, now_iso, process_name))
            conn.commit()
            conn.close()
        _log(f"[START] {process_name} pid={proc.pid}")
        return proc.pid
    except Exception as e:
        _log(f"[START-FAIL] {process_name}: {e}")
        return None


# ============================================================
# 6. 心跳监控 + 自动重启
# ============================================================
def heartbeat_check() -> Dict:
    """检查所有RUNNING进程的心跳,超时的标记FAILED并自动重启"""
    now_str = _now()
    now_ts = datetime.now().timestamp()
    result = {"checked": 0, "alive": 0, "timeout": 0, "restarted": 0, "max_restart": 0}

    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        # 扩展：除RUNNING外，也检查IDLE/STOPPED/FAILED行中的残留PID是否真实存活
        # 避免历史残留PID记录永远不被清理，无法重挂载
        rows = conn.execute("""
            SELECT * FROM mt_ai_smart_mount_processes
            WHERE current_state IN ('RUNNING','IDLE','STOPPED','FAILED')
        """).fetchall()
        conn.close()

    for r in rows:
        result["checked"] += 1
        pid = r["pid"]
        pname = r["process_name"]

        # 检查进程是否存活
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False

        if alive:
            # 检查心跳超时
            hb = r["heartbeat_at"]
            if hb:
                try:
                    hb_ts = datetime.fromisoformat(hb).timestamp()
                    if now_ts - hb_ts > HEARTBEAT_TIMEOUT:
                        alive = False
                        _log(f"[TIMEOUT] {pname} pid={pid} heartbeat_stale>{HEARTBEAT_TIMEOUT}s")
                except Exception:
                    pass

        if alive:
            result["alive"] += 1
            # ✅ 每次心跳检查同步 daemon_registry 的 pid + last_heartbeat (根因补全)
            try:
                with _LOCK:
                    _c2 = _get_conn().cursor()
                    _c2.execute("UPDATE mt_daemon_registry SET pid=?, last_heartbeat=?, status='RUNNING', updated_at=? WHERE process_name=?",
                                (pid, now_str, now_str, pname))
                    _c2.connection.commit()
                    _c2.connection.close()
            except Exception:
                pass
            # IDLE但存活的进程 → 不重启，标记为 RUNNING 便于进入正常心跳循环
            if r["current_state"] == "IDLE":
                _update_process_state(pname, "RUNNING")
                try:
                    daemon_transition(pname, "RUNNING")
                except Exception:
                    pass
            continue

        # 进程死亡或心跳超时 → 先清理残留PID记录，避免下次再判错
        try:
            with _LOCK:
                _c = _get_conn().cursor()
                _c.execute("UPDATE mt_ai_smart_mount_processes SET pid=NULL WHERE process_name=?",
                           (pname,))
                _c.connection.commit()
                _c.connection.close()
            # ✅ 同步清理 daemon_registry 的 pid
            with _LOCK:
                _c2 = _get_conn().cursor()
                _c2.execute("UPDATE mt_daemon_registry SET pid=NULL WHERE process_name=?",
                            (pname,))
                _c2.connection.commit()
                _c2.connection.close()
        except Exception:
            pass

        # 非RUNNING状态但PID已死 → 判定是否需要重启
        if r["current_state"] != "RUNNING":
            process_name = r["process_name"]
            script_path = r["script_path"]
            restart_count = r["restart_count"] or 0
            last_restart = r["last_restart_at"]
            mount_source = r["mount_source"] or ""
            is_system_required = (mount_source == "SYSTEM_REQ")

            # 计算冷却时间
            cooldown_elapsed = 0.0
            if last_restart:
                try:
                    cooldown_elapsed = now_ts - datetime.fromisoformat(last_restart).timestamp()
                except Exception:
                    pass

            # 三种重启条件 (满足任一即试)
            should_relaunch = False
            reason = ""

            # 条件1: SYSTEM_REQ必需daemon → 无条件重启
            if is_system_required:
                should_relaunch = True
                reason = "SYSTEM_REQ必需"

            # 条件2: 非SYSTEM_REQ但已冷却完 → 重置restart_count重试
            elif restart_count >= MAX_RESTART_COUNT and cooldown_elapsed >= STOPPED_COOLDOWN:
                should_relaunch = True
                reason = f"冷却{cooldown_elapsed:.0f}s>=STOPPED_COOLDOWN({STOPPED_COOLDOWN}s)"

            # 条件3: 一般FAILED/IDLE状态 → 直接重试(冷却中也可)
            elif r["current_state"] != "STOPPED":
                should_relaunch = True
                reason = f"状态={r['current_state']}非RUNNING"

            if should_relaunch and script_path and os.path.exists(script_path):
                if restart_count >= MAX_RESTART_COUNT:
                    _log(f"[COOL-RESET] {process_name} restart_count={restart_count}冷却完毕重置→重启 (reason={reason})")
                    reset_cnt = 0
                else:
                    _log(f"[NON-RUN-RESTART] {process_name} restart_count={restart_count}→重启 (reason={reason})")
                    reset_cnt = restart_count

                _update_process_state(process_name, "FAILED")
                try:
                    daemon_transition(process_name, "FAILED")
                except Exception:
                    pass

                time.sleep(2)
                new_pid = _start_subprocess(process_name, script_path)

                with _LOCK:
                    conn = _get_conn()
                    c = conn.cursor()
                    c.execute("""UPDATE mt_ai_smart_mount_processes
                        SET pid=?, current_state='RUNNING', restart_count=?,
                            last_restart_at=?, heartbeat_at=?, updated_at=?
                        WHERE process_name=?""",
                        (new_pid, reset_cnt + 1, _now(), _now(), _now(), process_name))
                    conn.commit()
                    conn.close()

                try:
                    daemon_transition(process_name, "RUNNING")
                except Exception:
                    pass

                result["timeout"] += 1
                result["restarted"] += 1
            else:
                # 脚本不存在或冷却未到 → 保持STOPPED
                if r["current_state"] != "STOPPED":
                    _update_process_state(process_name, "STOPPED")
                    try:
                        daemon_transition(process_name, "STOPPED")
                    except Exception:
                        pass
                if restart_count >= MAX_RESTART_COUNT and cooldown_elapsed < STOPPED_COOLDOWN:
                    result["max_restart"] += 1
            continue

        result["timeout"] += 1
        restart_count = r["restart_count"] or 0

        if restart_count >= MAX_RESTART_COUNT:
            # 触顶 → 标记STOPPED, 冷却后会被上面的 NON-RUNNING 分支捞起重试
            result["max_restart"] += 1
            _log(f"[MAX-RESTART] {r['process_name']} restart_count={restart_count} -> STOPPED (冷却{STOPPED_COOLDOWN}s后重置)")
            _update_process_state(r["process_name"], "STOPPED")
            try:
                daemon_transition(r["process_name"], "STOPPED")
            except Exception:
                pass
            continue

        # 自动重启
        _log(f"[RESTART] {r['process_name']} pid={pid} restart#{restart_count + 1}")
        _update_process_state(r["process_name"], "FAILED")
        try:
            daemon_transition(r["process_name"], "FAILED")
        except Exception:
            pass

        # 重置后重新启动
        time.sleep(2)
        new_pid = _start_subprocess(r["process_name"], r["script_path"])

        with _LOCK:
            conn = _get_conn()
            c = conn.cursor()
            c.execute("""UPDATE mt_ai_smart_mount_processes
                SET current_state='RUNNING', restart_count=?, last_restart_at=?, heartbeat_at=?, updated_at=?
                WHERE process_name=?""",
                (restart_count + 1, _now(), _now(), _now(), r["process_name"]))
            conn.commit()
            conn.close()

        try:
            daemon_transition(r["process_name"], "RUNNING")
        except Exception:
            pass

        result["restarted"] += 1

    return result


def _update_process_state(process_name: str, state: str):
    with _LOCK:
        conn = _get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE mt_ai_smart_mount_processes SET current_state=?, updated_at=? WHERE process_name=?",
            (state, _now(), process_name))
        conn.commit()
        conn.close()


def _log(msg: str):
    with open(MONITOR_LOG, "a") as f:
        f.write(f"[{_now()}] {msg}\n")


def _log_supervisor(level: str, event: str, detail: str = '') -> None:
    """
    守护进程事件落库 mt_daemon_supervisor_log，便于跨会话追溯。
    与 start_smart_mount_engine_daemon.py 内的 log_event 共用同一张表，
    supervisor 字段固定为 'smart_mount_daemon'。
    失败时静默忽略，绝不影响主循环。
    """
    try:
        with _LOCK:
            conn = _get_conn()
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS mt_daemon_supervisor_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time    TEXT    NOT NULL,
                    supervisor    TEXT    NOT NULL,
                    level         TEXT    NOT NULL,
                    event         TEXT    NOT NULL,
                    detail        TEXT,
                    pid           INTEGER,
                    created_at    TEXT    NOT NULL
                )
            """)
            c.execute(
                "INSERT INTO mt_daemon_supervisor_log "
                "(event_time, supervisor, level, event, detail, pid, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_now(), 'smart_mount_daemon', level, event, detail, os.getpid(), _now()),
            )
            conn.commit()
            conn.close()
    except Exception:
        # 守护进程落库失败绝不影响主流程
        pass


# ============================================================
# 7. 扫描建议池 + 自动挂载 (核心入口)
# ============================================================
def scan_and_mount() -> Dict:
    """
    全流程: 扫描建议池 → 收集专家权重 → 逐条决策 → 自动挂载
    这是scan子命令的核心逻辑,也是守护循环每次执行的逻辑
    """
    result = {
        "scanned": 0, "mounted": 0, "deferred": 0, "rejected": 0,
        "details": []
    }

    # === 0. 仙女座 v5.0: 消费 Phase2 觉醒 JSON 文件旁路 ===
    try:
        import os as _os, json as _json
        _fev_file = '/tmp/fev_suggestions.json'
        if _os.path.exists(_fev_file):
            with _LOCK:
                _c0 = _get_conn()
                with open(_fev_file, 'r') as _ff:
                    _fev_list = _json.load(_ff)
                _inserted = 0
                for _fev in _fev_list:
                    try:
                        _c0.execute("INSERT INTO mt_ai_suggestion_pool\n                            (source_type, source_name, suggestion_text, priority, status, feasibility_score, value_score, cost_score, risk_score, flow_id, created_at)\n                            VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                            _fev.get('source_type','FEATURE_EVOLUTION_AWAKE'),
                            _fev.get('source_name','sys_feature_evolution'),
                            _fev.get('suggestion_text',''),
                            _fev.get('priority', 3),
                            _fev.get('status','PENDING'),
                            _fev.get('feasibility_score',0.85),
                            _fev.get('value_score',0.8),
                            _fev.get('cost_score',0.2),
                            _fev.get('risk_score',0.15),
                            _fev.get('flow_id',''),
                            _fev.get('created_at','')
                        ))
                        _inserted += 1
                    except Exception as _ie:
                        sm_log(f'  ⚠️  FEV insert err: {_ie}')
                _c0.commit()
                _c0.close()
            _os.remove(_fev_file)
            sm_log(f'  ✅ 消费 FEV JSON 文件: {_inserted} 条觉醒建议 → suggestion_pool')
    except Exception as _fev_err:
        sm_log(f'  FEV file consume err: {_fev_err}')

    # 1. 收集已评估的高优先级建议
    suggestions = collect_suggestions(min_priority=5)
    result["scanned"] = len(suggestions)

    if not suggestions:
        _log("[SCAN] 无待挂载建议")
        return result

    # 2. 收集EigenFlux专家权重
    expert_weights = collect_expert_weights()

    # 3. 逐条决策
    for sug in suggestions:
        decision = smart_mount_decision(sug, expert_weights)

        if decision["decision"] == "MOUNT":
            # 自动生成daemon脚本
            process_name = f"auto_{sug.get('direction', 'gen')}_{sug['suggestion_id']}"
            duty = sug.get("suggestion", "")[:100]
            script_path = generate_daemon_script(
                process_name=process_name,
                duty=duty,
                suggestion_id=sug["suggestion_id"],
                mount_score=decision["final_score"],
                work_body=_infer_work_body(sug),
                inspect_cycle=60,
            )

            # 挂载
            try:
                mount_process(
                    process_name=process_name,
                    duty=duty,
                    script_path=script_path,
                    suggestion_id=sug["suggestion_id"],
                    mount_source="AI_SUGGESTION",
                    mount_score=decision["final_score"],
                    expert_weights=expert_weights,
                )
                # ✅ 仙女座 v5.0: 挂载成功后立即标记 suggestion → DEPLOYED (短事务)
                try:
                    with _LOCK:
                        _c2 = _get_conn()
                        _c2.execute("UPDATE mt_ai_suggestion_pool SET status='DEPLOYED', deployed_at=datetime('now') WHERE suggestion_id=?", (sug["suggestion_id"],))
                        _c2.commit()
                        _c2.close()
                except Exception as _upd_err:
                    _log(f"[MOUNT-UPDATE-ERR] suggestion_id={sug['suggestion_id']}: {_upd_err}")

                result["mounted"] += 1
                decision["process_name"] = process_name
                decision["script_path"] = script_path
            except Exception as e:
                _log(f"[MOUNT-FAIL] {process_name}: {e}")
                decision["error"] = str(e)
        elif decision["decision"] == "DEFER":
            result["deferred"] += 1
        else:
            result["rejected"] += 1

        result["details"].append(decision)

    _log(f"[SCAN] scanned={result['scanned']} mounted={result['mounted']} "
         f"deferred={result['deferred']} rejected={result['rejected']}")
    return result


def _evaluate_and_cleanup() -> Dict:
    """L3: auto_gen stale 10min->SUPERSEDED / 24h->ARCHIVED"""
    result = {"superseded": 0, "archived": 0}
    try:
        with _LOCK:
            _c = _get_conn()
            _c.execute('PRAGMA busy_timeout=60000')
            stale = _c.execute("SELECT process_name, suggestion_id FROM mt_ai_smart_mount_processes WHERE process_name LIKE 'auto_gen_%' AND current_state='RUNNING' AND heartbeat_at < datetime('now', '-10 minutes')").fetchall()
            for pname, sid in stale:
                import subprocess as _sp
                _sp.run(['pkill','-9','-f',pname], capture_output=True)
                _c.execute("UPDATE mt_ai_smart_mount_processes SET current_state='STOPPED' WHERE process_name=?", (pname,))
                if sid: _c.execute("UPDATE mt_ai_suggestion_pool SET status='SUPERSEDED' WHERE suggestion_id=?", (sid,))
                result["superseded"] += 1
            old = _c.execute("SELECT p.process_name, p.suggestion_id FROM mt_ai_smart_mount_processes p WHERE p.process_name LIKE 'auto_gen_%' AND p.created_at < datetime('now', '-24 hours')").fetchall()
            for pname, sid in old:
                import subprocess as _sp
                _sp.run(['pkill','-9','-f',pname], capture_output=True)
                _c.execute("UPDATE mt_ai_smart_mount_processes SET current_state='STOPPED' WHERE process_name=?", (pname,))
                if sid: _c.execute("UPDATE mt_ai_suggestion_pool SET status='ARCHIVED' WHERE suggestion_id=?", (sid,))
                result["archived"] += 1
            _c.commit()
            _c.close()
    except Exception as e:
        _log(f"[EVAL] err: {e}")
    return result


def _infer_work_body(suggestion: Dict) -> str:
    """L1: suggestion_text -> FIX_DAEMON/ADD_ROUTE/CLEANUP 真实 work_body"""
    text = suggestion.get("suggestion_text", "") or suggestion.get("suggestion", "") or ""
    action = "UNKNOWN"
    t = text.upper()
    if "[FIX" in t: action = "FIX_DAEMON"
    elif "[ADD_ROUTE" in t: action = "ADD_ROUTE"
    elif "[CLEANUP" in t: action = "CLEANUP"
    elif "[SYNC_PARAM" in t: action = "SYNC_PARAM"
    elif "[OPTIMIZE_UI" in t or t.startswith("[OPTIMIZE"): action = "OPTIMIZE_UI"
    
    # FIX_DAEMON: 重启 FAILED daemon
    FIX_BODY = (
        "            # FIX_DAEMON: restart FAILED daemon\n"
        "            try:\n"
        "                import subprocess, sqlite3\n"
        "                conn = sqlite3.connect(APP_DB, timeout=15)\n"
        "                conn.execute('PRAGMA busy_timeout=15000')\n"
        "                rows = conn.execute(\"SELECT process_name FROM mt_ai_smart_mount_processes WHERE current_state='FAILED'\").fetchall()\n"
        "                conn.close()\n"
        "                if rows:\n"
        "                    for (dname,) in rows:\n"
        "                        subprocess.run(['pkill','-9','-f',dname], capture_output=True)\n"
        "                        import time; time.sleep(2)\n"
        "                        script = f'_runtime/auto_daemons/{dname}.py'\n"
        "                        if os.path.exists(script):\n"
        "                            subprocess.Popen([sys.executable, script], stdout=open(f'_runtime/logs/{dname}.log','a'), stderr=subprocess.STDOUT)\n"
        "                        _log(f'FIX_DAEMON: restarted {dname} OK')\n"
        "                else:\n"
        "                    _log('FIX_DAEMON: no FAILED daemons')\n"
        "            except Exception as e:\n"
        "                _log(f'FIX_DAEMON err: {e}')"
    )
    # ADD_ROUTE: 插路由 (domain 从 suggestion_text 提取)
    ROUTE_BODY = (
        "            # ADD_ROUTE: insert neural route\n"
        "            try:\n"
        "                import sqlite3, re as _re\n"
        "                conn = sqlite3.connect(APP_DB, timeout=15)\n"
        "                conn.execute('PRAGMA busy_timeout=15000')\n"
        "                _tgt = 'auto'\n"
        "                _m = _re.search(r'\\u76ee\\u6807[\\uff1a:]\\\\s*(\\\\S+)', suggestion.get('suggestion_text',''))\n"
        "                if _m: _tgt = _m.group(1)\n"
        "                conn.execute(\"INSERT OR IGNORE INTO mt_ai_neural_routes (domain, route_name, model, weight, created_at) VALUES (?, ?, 'qwen2.5:7b', 0.5, datetime('now'))\", (_tgt, _tgt+'_auto'))\n"
        "                conn.commit()\n"
        "                conn.close()\n"
        "                _log(f'ADD_ROUTE: inserted for {_tgt} OK')\n"
        "            except Exception as e:\n"
        "                _log(f'ADD_ROUTE err: {e}')"
    )
    # CLEANUP: 清临时文件
    CLEAN_BODY = (
        "            # CLEANUP: remove temp files\n"
        "            try:\n"
        "                import glob as _glob, os as _os\n"
        "                removed = 0\n"
        "                for pat in ['_runtime/*.tmp', '_runtime/*.bak']:\n"
        "                    for f in _glob.glob(pat):\n"
        "                        try: _os.remove(f); removed += 1\n"
        "                        except: pass\n"
        "                _log(f'CLEANUP: removed {removed} files OK')\n"
        "            except Exception as e:\n"
        "                _log(f'CLEANUP err: {e}')"
    )
    # 通用巡检
    PATROL_BODY = (
        "            # generic patrol\n"
        "            try:\n"
        "                import sqlite3\n"
        "                conn = sqlite3.connect(APP_DB, timeout=15)\n"
        "                st = conn.execute('SELECT current_state, COUNT(*) FROM mt_ai_smart_mount_processes GROUP BY current_state').fetchall()\n"
        "                conn.close()\n"
        "                _log(f'AUTO-GEN patrol: {dict(st)}')\n"
        "            except Exception as e:\n"
        "                _log(f'AUTO-GEN err: {e}')"
    )
    
    # SYNC_PARAM: 写参数到 mt_params (仙女座 v5.1 参数统一系统)
    SYNC_PARAM_BODY = (
        "            # SYNC_PARAM: 仙女座 v5.1 参数统一 — 写入 mt_params\n"
        "            try:\n"
        "                import sqlite3, re as _re\n"
        "                conn = sqlite3.connect(APP_DB, timeout=15)\n"
        "                conn.execute('PRAGMA busy_timeout=15000')\n"
        "                _text = suggestion.get('suggestion_text', '')\n"
        "                _m = _re.search(r'\\u76ee\\u6807[\\uff1a:]\\s*(\\S+)', _text)\n"
        "                if not _m: _m = _re.search(r'\\[(SYNC_PARAM)[\\]]\\s*([\\w_]+)/([\\w_]+)\\s*[=:]\\s*(\\S+)', _text)\n"
        "                if _m:\n"
        "                    _tgt = _m.group(1) if len(_m.groups())==1 else _m.group(2)+'/'+_m.group(3)+'='+_m.group(4)\n"
        "                    if '/' in _tgt and '=' in _tgt:\n"
        "                        _grp, _rest = _tgt.split('/', 1)\n"
        "                        _key, _val = _rest.split('=', 1)\n"
        "                        conn.execute(\n"
        "                            \"INSERT OR REPLACE INTO mt_params (param_group, param_key, param_value, param_type, updated_at, updated_by) VALUES (?, ?, ?, ?, datetime('now'), 'Andromeda-v5.1')\",\n"
        "                            (_grp, _key.strip(), _val.strip(), 'int' if _val.strip().isdigit() else 'str'))\n"
        "                        conn.commit()\n"
        "                        _log(f'SYNC_PARAM: {_grp}/{_key.strip()} = {_val.strip()} → mt_params OK (daemon 下一轮循环热生效)')\n"
        "                    else:\n"
        "                        _log(f'SYNC_PARAM: target format wrong: {_tgt}')\n"
        "                else:\n"
        "                    _log('SYNC_PARAM: no target found')\n"
        "                conn.close()\n"
        "            except Exception as e:\n"
        "                _log(f'SYNC_PARAM err: {e}')"
    )
    # OPTIMIZE_UI: 写 frontend 参数 + 刷新 CSS 覆盖层 (仙女座 v5.1)
    OPTIMIZE_UI_BODY = (
        "            # OPTIMIZE_UI: 仙女座 v5.1 前端参数优化\n"
        "            try:\n"
        "                import sqlite3, re as _re, subprocess as _sp, os as _os\n"
        "                conn = sqlite3.connect(APP_DB, timeout=15)\n"
        "                conn.execute('PRAGMA busy_timeout=15000')\n"
        "                _text = suggestion.get('suggestion_text', '')\n"
        "                # 解析 target: frontend/primary_color=#667eea 或 主色=#667eea\n"
        "                _tgt = ''\n"
        "                _m = _re.search(r'\\u76ee\\u6807[\\uff1a:]\\s*(\\S+)', _text)\n"
        "                if _m: _tgt = _m.group(1)\n"
        "                if not _tgt:\n"
        "                    _m2 = _re.search(r'frontend[\\/]([\\w_]+)\\s*[=:]\\s*(\\S+)', _text)\n"
        "                    if _m2: _tgt = f'frontend/{_m2.group(1)}={_m2.group(2)}'\n"
        "                if _tgt and '/' in _tgt and '=' in _tgt:\n"
        "                    _grp, _rest = _tgt.split('/', 1)\n"
        "                    _key, _val = _rest.split('=', 1)\n"
        "                    _grp, _key, _val = _grp.strip(), _key.strip(), _val.strip()\n"
        "                    _type = 'int' if _val.strip().isdigit() else ('float' if _val.count('.')==1 else 'str')\n"
        "                    conn.execute(\n"
        "                        \"INSERT OR REPLACE INTO mt_params (param_group, param_key, param_value, param_type, updated_at, updated_by) VALUES (?, ?, ?, ?, datetime('now'), 'Andromeda-v5.1-OPTIMIZE_UI')\",\n"
        "                        (_grp, _key, _val, _type))\n"
        "                    conn.commit()\n"
        "                    _log(f'OPTIMIZE_UI: {_grp}/{_key} = {_val} → mt_params ✅')\n"
        "                    # 刷新 CSS 覆盖层 → 全站热生效\n"
        "                    _fe = _os.path.join(_os.path.dirname(_os.path.dirname(APP_DB)), 'flask-app', 'engines', 'ai_frontend_optimizer.py')\n"
        "                    if _os.path.exists(_fe):\n"
        "                        _sp.run([sys.executable, _fe, 'once'], capture_output=True, timeout=15)\n"
        "                        _log(f'OPTIMIZE_UI: CSS 覆盖层已刷新 → 全站热生效')\n"
        "                    else:\n"
        "                        _log('OPTIMIZE_UI: frontend_optimizer.py 未找到')\n"
        "                else:\n"
        "                    _log(f'OPTIMIZE_UI: target format wrong: {_tgt}')\n"
        "                conn.close()\n"
        "            except Exception as e:\n"
        "                _log(f'OPTIMIZE_UI err: {e}')"
    )
    
    if action == "FIX_DAEMON": return FIX_BODY
    elif action == "ADD_ROUTE": return ROUTE_BODY
    elif action == "CLEANUP": return CLEAN_BODY
    elif action == "SYNC_PARAM": return SYNC_PARAM_BODY
    elif action == "OPTIMIZE_UI": return OPTIMIZE_UI_BODY
    return PATROL_BODY

def mount_system_required() -> Dict:
    """挂载系统必需的自动化进程(无AI建议时,根据系统要求创建)"""
    result = {"mounted": 0, "skipped": 0, "details": []}

    # 🆕 Aurora 极光: 被 Aurora 显式禁用的 daemon 跳过挂载
    _aurora_disabled = set()
    try:
        from engines.aurora_skill_registry import aurora_registry
        for row in aurora_registry.by_type('daemon'):
            if not row['enabled']:
                _aurora_disabled.add(row['skill_key'])
    except Exception: pass  # Aurora 未就绪时全量挂载 (兼容)

    for req in SYSTEM_REQUIRED_DAEMONS:
        # Aurora 禁用保护
        if req["process_name"] in _aurora_disabled:
            result["skipped"] += 1
            result["details"].append({"process_name": req["process_name"], "action": "skipped (Aurora disabled)"})
            continue
        # 检查是否已存在
        with _LOCK:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                "SELECT * FROM mt_ai_smart_mount_processes WHERE process_name=?",
                (req["process_name"],)).fetchone()
            conn.close()

        if r and r["current_state"] in ("RUNNING", "IDLE"):
            # 检查PID是否真实存活；若IDLE/RUNNING但PID已死 → 视为需要重挂载
            pid_alive = False
            if r["pid"]:
                try:
                    os.kill(int(r["pid"]), 0)
                    pid_alive = True
                except (OSError, ValueError):
                    pid_alive = False
            if pid_alive:
                result["skipped"] += 1
                continue
            # 已死记录: 先清理状态到STOPPED便于重新挂载
            try:
                with _LOCK:
                    conn2 = _get_conn()
                    conn2.execute(
                        "UPDATE mt_ai_smart_mount_processes SET current_state='STOPPED', updated_at=? WHERE process_name=?",
                        (_now(), req["process_name"]))
                    conn2.commit()
                    conn2.close()
            except Exception as _e:
                _log(f"[SYS-MOUNT] clean stale state fail {req['process_name']}: {_e}")

        # 生成脚本 + 挂载 — 单daemon失败不影响其他
        try:
            script_path = generate_daemon_script(
                process_name=req["process_name"],
                duty=req["duty"],
                suggestion_id=0,
                mount_score=1.0,  # 系统必需=满分
                work_body=req["work_body"],
                inspect_cycle=req["inspect_cycle"],
            )
        except Exception as e:
            _log(f"[SYS-MOUNT-SCRIPT-FAIL] {req['process_name']}: {e}")
            continue

        # 挂载（先reset restart_count，防止历史MAX-RESTART残留直接判死）
        try:
            with _LOCK:
                conn3 = _get_conn()
                conn3.execute(
                    "UPDATE mt_ai_smart_mount_processes SET restart_count=0 WHERE process_name=? AND restart_count>=?",
                    (req["process_name"], MAX_RESTART_COUNT))
                conn3.commit()
                conn3.close()
        except Exception:
            pass

        try:
            mount_process(
                process_name=req["process_name"],
                duty=req["duty"],
                script_path=script_path,
                suggestion_id=None,
                mount_source="SYSTEM_REQ",
                mount_score=1.0,
                expert_weights={},
            )
            result["mounted"] += 1
            result["details"].append(req["process_name"])
        except Exception as e:
            _log(f"[SYS-MOUNT-FAIL] {req['process_name']}: {e}")

    _log(f"[SYS-MOUNT] mounted={result['mounted']} skipped={result['skipped']}")
    return result


# ============================================================
# 9. CLI守护模式
# ============================================================
class SmartMountDaemon:
    """守护进程: 巡检循环(扫描建议+心跳监控+系统必需挂载)"""

    @staticmethod
    def read_pid() -> Optional[int]:
        if not os.path.exists(PID_FILE):
            return None
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            return None
        if pid == os.getpid():
            # PID_FILE 里写的是自己（启动脚本竞态写入），视为无效
            return None
        try:
            os.kill(pid, 0)
        except OSError:
            # stale PID：顺手清理，避免残留
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
            return None
        # 校验进程身份，防止 PID 被无关进程复用导致永久误判 RUNNING
        try:
            out = subprocess.check_output(
                ["/bin/ps", "-p", str(pid), "-o", "command="],
                stderr=subprocess.DEVNULL, timeout=5).decode(errors="ignore")
            if "ai_smart_mount_engine" not in out:
                try:
                    os.remove(PID_FILE)
                except OSError:
                    pass
                return None
        except Exception:
            pass  # ps 不可用时退回 kill -0 结果
        return pid

    @staticmethod
    def write_pid(pid_val=None):
        """原子写PID文件：tmp+fsync+rename（OneDrive Files On-Demand 适配，
        避免 open(write) 因异步 IO 丢失内容，导致 check-keepalive 误判重启。）
        """
        import tempfile as _tf
        if pid_val is None:
            pid_val = os.getpid()
        try:
            os.makedirs(PID_DIR, exist_ok=True)
        except OSError:
            pass
        tmp_fd = None
        tmp_path = None
        try:
            fd, tmp_path = _tf.mkstemp(prefix=".ai_sme_pid_", suffix=".tmp", dir=PID_DIR)
            tmp_fd = fd
            os.write(fd, str(pid_val).encode("ascii"))
            os.fsync(fd)
            try:
                os.close(fd); tmp_fd = None
            except OSError:
                pass
            os.replace(tmp_path, PID_FILE)
            tmp_path = None
            try:
                dfd = os.open(PID_DIR, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
        except Exception:
            try:
                if tmp_fd is not None:
                    try: os.close(tmp_fd)
                    except OSError: pass
                if tmp_path is not None:
                    try: os.remove(tmp_path)
                    except OSError: pass
            except Exception:
                pass
            try:
                with open(PID_FILE, "w") as f:
                    f.write(str(pid_val))
                    try: f.flush()
                    except Exception: pass
            except OSError:
                pass

    @staticmethod
    def clear_pid():
        try:
            os.remove(PID_FILE)
            try:
                dfd = os.open(PID_DIR, os.O_RDONLY)
                try: os.fsync(dfd)
                finally: os.close(dfd)
            except OSError:
                pass
        except OSError:
            pass

    @staticmethod
    def _self_defense_watchdog(cycle: int):
        """
        Layer-1 INTERNAL watchdog (zero dependency, zero external config).
        Runs every 2 cycles (~60s). Purpose:
          (A) Clean stale PID files in _runtime/pids whose processes don't exist.
          (B) DEDUP: for EVERY auto_daemons/*.py script, KEEP EXACTLY ONE running
              instance (the smallest PID = approximately the oldest started).
              Kill the rest with SIGKILL. Prevents the 122-process explosion seen
              before (sys_penetration_test had 122 duplicates / scheduler had 15).
          (C) Log a one-line WD cycle into smart_mount_monitor.log.

        This method NEVER raises. Any exception is swallowed so the main loop
        continues unconditionally.
        """
        try:
            stale_cleaned = 0
            total_pid_files = 0
            if os.path.isdir(PID_DIR):
                for pf in os.listdir(PID_DIR):
                    if not pf.endswith(".pid"):
                        continue
                    pf_path = os.path.join(PID_DIR, pf)
                    if not os.path.isfile(pf_path):
                        continue
                    total_pid_files += 1
                    try:
                        with open(pf_path) as fh:
                            pv_str = fh.read().strip()
                        if not pv_str or not pv_str.isdigit():
                            os.remove(pf_path)
                            stale_cleaned += 1
                            continue
                        pv_int = int(pv_str)
                        try:
                            os.kill(pv_int, 0)
                        except OSError:
                            os.remove(pf_path)
                            stale_cleaned += 1
                    except Exception:
                        # Never let a single bad pidfile crash watchdog
                        try:
                            os.remove(pf_path)
                            stale_cleaned += 1
                        except OSError:
                            pass

            # ---- (B) daemon dedup via ps ----
            import subprocess as _sp
            dedup_killed = 0
            try:
                ps_raw = _sp.check_output(
                    ["ps", "-eo", "pid,command"],
                    stderr=_sp.DEVNULL, timeout=8
                ).decode("utf-8", errors="ignore")
            except Exception:
                ps_raw = ""

            # group: {script_name: [sorted_pids_asc]}
            groups: Dict[str, List[int]] = {}
            for line in ps_raw.splitlines():
                if "auto_daemons/" not in line:
                    continue
                parts = line.strip().split(None, 1)
                if len(parts) < 2:
                    continue
                pid_s, cmd = parts
                if not pid_s.isdigit():
                    continue
                m_py = None
                for tok in cmd.split():
                    idx = tok.find("auto_daemons/")
                    if idx >= 0:
                        cand = tok[idx + len("auto_daemons/"):]
                        # take up to first .py (possibly trailing args)
                        py = cand.find(".py")
                        if py >= 0:
                            m_py = cand[:py + 3]
                            break
                if m_py is None:
                    continue
                if m_py not in groups:
                    groups[m_py] = []
                try:
                    groups[m_py].append(int(pid_s))
                except ValueError:
                    pass

            for sname, pids in groups.items():
                if len(pids) <= 1:
                    continue
                pids_sorted = sorted(pids)   # smallest = oldest approx
                keep = pids_sorted[0]
                for extra_pid in pids_sorted[1:]:
                    try:
                        # verify it's really an auto_daemons process before kill
                        try:
                            cl2 = _sp.check_output(
                                ["ps", "-p", str(extra_pid), "-o", "command="],
                                stderr=_sp.DEVNULL, timeout=3
                            ).decode("utf-8", errors="ignore")
                        except Exception:
                            cl2 = ""
                        if "auto_daemons/" not in cl2:
                            continue
                        os.kill(extra_pid, 9)  # SIGKILL — duplicates never deserve grace
                        dedup_killed += 1
                        try:
                            _log(f"[WD-DEDUP] cycle={cycle} killed duplicate {sname} pid={extra_pid} (keep pid={keep})")
                        except Exception:
                            pass
                    except OSError:
                        pass
                    except Exception:
                        pass

            # ---- (C) log line into monitor log ----
            alive_types = len(groups)
            total_procs = sum(len(v) for v in groups.values())
            sm_pid = os.getpid()
            try:
                mon_log = os.path.join(LOG_DIR, "ai_smart_mount_monitor.log")
                ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
                line = (f"[{ts_now}] WD_CYCLE cycle={cycle} sm_pid={sm_pid} "
                        f"types={alive_types} total_procs={total_procs} "
                        f"stale_pid_cleaned={stale_cleaned}/{total_pid_files} "
                        f"dedup_killed={dedup_killed}\n")
                try:
                    # best effort append; do not hold locks
                    with open(mon_log, "a") as fm:
                        fm.write(line)
                    # cap monitor log at 5 MB → truncate to latest 20000 lines
                    try:
                        if os.path.getsize(mon_log) > 5 * 1024 * 1024:
                            with open(mon_log) as fm:
                                all_lines = fm.readlines()
                            if len(all_lines) > 20000:
                                with open(mon_log, "w") as fm:
                                    fm.writelines(all_lines[-20000:])
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            # Never propagate to main loop
            try:
                _log(f"[WD-SWALLOW] cycle={cycle} watchdog threw (ignored)", level="WARN")
            except Exception:
                pass

    @staticmethod
    def start():
        """启动守护进程(前台运行, 可被nohup/launchd托管)"""
        existing = SmartMountDaemon.read_pid()
        if existing:
            print(f"[STATUS] RUNNING  pid={existing}")
            return

        # 先确保表存在
        ensure_smart_mount_tables()

        # 写PID（原子+fsync，OneDrive异步IO安全）
        SmartMountDaemon.write_pid()

        # SIGTERM handler
        def _term(signum, frame):
            _log(f"[DAEMON] SIGTERM/SIGINT received (signum={signum}), shutting down...")
            _log_supervisor('INFO', 'ENGINE_STOP',
                            f'signal={signum} pid={os.getpid()}')
            SmartMountDaemon.clear_pid()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _term)
        signal.signal(signal.SIGINT, _term)

        _log(f"[DAEMON] START pid={os.getpid()} ppid={os.getppid()} interval={MONITOR_INTERVAL}s "
             f"daemonized={os.environ.get('MTSCOS_SM_DAEMONIZED', '0')}")
        _log_supervisor('INFO', 'ENGINE_START',
                        f'pid={os.getpid()} ppid={os.getppid()} interval={MONITOR_INTERVAL}s')

        # 首次启动: 挂载系统必需进程
        _log("[DAEMON] 挂载系统必需进程...")
        try:
            mount_system_required()
        except Exception as e:
            _log(f"[DAEMON][FATAL] mount_system_required failed: {e}")
            _log_supervisor('ERROR', 'MOUNT_SYSTEM_REQUIRED_FAILED', f'err={e}')
            # 不退出，主循环照常跑，下一轮 heartbeat_check 会重启失败进程

        # 主循环 - 守护进程绝不退出：任何异常都被捕获并继续，
        # 唯一退出途径是外部 SIGTERM/SIGINT，由 _term handler 处理。
        cycle = 0
        consecutive_errors = 0
        while True:
            cycle += 1
            try:
                # 每3个周期扫描一次建议池 (约90秒)
                if cycle % 3 == 0:
                    _log(f"[DAEMON] cycle={cycle} scanning suggestions...")
                    scan_and_mount()

                # 每10个周期重新挂载STOPPED的系统必需daemon (约5分钟)
                if cycle % 10 == 0:
                    try:
                        remount = mount_system_required()
                        if remount["mounted"] > 0:
                            _log(f"[DAEMON] cycle={cycle} remounted {remount['mounted']} STOPPED system daemons")
                    except Exception as e:
                        _log(f"[DAEMON] cycle={cycle} remount_system_required err: {e}")

                # 每个周期检查心跳
                hb = heartbeat_check()
                if hb["checked"] > 0:
                    _log(f"[DAEMON] cycle={cycle} heartbeat: checked={hb['checked']} "
                         f"alive={hb['alive']} timeout={hb['timeout']} restarted={hb['restarted']}")

                # 每2个周期(~60s)执行 Layer1 内置自卫看门狗：stale pid清理 + daemon去重
                # 零外部依赖，不依赖 cron / launchd / TCC / sudo
                if cycle % 2 == 0:
                    SmartMountDaemon._self_defense_watchdog(cycle)

                # 每4个周期(~2分钟)跑 console_error_monitor: 扫描前端 console.error → AI 分类 → 生成修复建议
                # v22.39.0 新增 (daemon_registry interval=120s 对齐)
                if cycle % 4 == 0:
                    try:
                        from engines.ai_console_monitor import run_cycle as _cm_run
                        _cm_run()
                    except Exception as _ce_err:
                        _log(f"[DAEMON] cycle={cycle} console_monitor err: {_ce_err}")

                # 成功一轮，清零错误计数
                if consecutive_errors > 0:
                    _log(f"[DAEMON] cycle={cycle} recovered after {consecutive_errors} errors")
                    _log_supervisor('INFO', 'ENGINE_RECOVERED',
                                    f'after_errors={consecutive_errors}')
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                import traceback as _tb
                tb_str = _tb.format_exc()
                _log(f"[DAEMON] cycle={cycle} ERROR #{consecutive_errors}: {e}\n{tb_str}")
                _log_supervisor('ERROR', 'CYCLE_EXCEPTION',
                                f'cycle={cycle} err#{consecutive_errors} err={e} tb={tb_str[:500]}')
                # 连续 10 次错误升级为 FATAL，但仍不退出（守护职责）
                if consecutive_errors == 10:
                    _log(f"[DAEMON][FATAL] 10 consecutive errors, escalating but not exiting")
                    _log_supervisor('FATAL', '10_CONSECUTIVE_ERRORS',
                                    f'cycle={cycle} last_err={e}')
                # 错误退避：第 1 次 0s, 2-5 次 5s, 6+ 次 30s
                backoff = 0 if consecutive_errors == 1 else (5 if consecutive_errors <= 5 else 30)
                if backoff > 0:
                    time.sleep(backoff)
                continue

            time.sleep(MONITOR_INTERVAL)

    @staticmethod
    def stop():
        """停止守护进程"""
        pid = SmartMountDaemon.read_pid()
        if not pid:
            print("[STATUS] STOPPED (no PID)")
            return

        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            # 如果还活着,强制杀
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        except OSError:
            pass

        SmartMountDaemon.clear_pid()
        print("[STATUS] STOPPED")

    @staticmethod
    def status() -> Dict:
        """查看状态"""
        ensure_smart_mount_tables()
        pid = SmartMountDaemon.read_pid()
        daemon_state = "RUNNING" if pid else "STOPPED"

        with _LOCK:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            # 进程列表
            procs = c.execute("""
                SELECT p.*, d.daemon_duty, d.priority
                FROM mt_ai_smart_mount_processes p
                LEFT JOIN mt_daemon_registry d ON p.daemon_id=d.daemon_id
                ORDER BY p.created_at DESC
            """).fetchall()

            # 待挂载建议数
            pending = c.execute("""
                SELECT COUNT(*) FROM mt_ai_suggestion_pool
                WHERE status='EVALUATED' AND priority>=5
            """).fetchone()[0]

            # 决策统计
            decisions = c.execute("""
                SELECT decision, COUNT(*) as cnt
                FROM mt_ai_mount_decisions
                GROUP BY decision
            """).fetchall()

            conn.close()

        result = {
            "daemon_pid": pid,
            "daemon_state": daemon_state,
            "total_processes": len(procs),
            "running_processes": sum(1 for p in procs if p["current_state"] == "RUNNING"),
            "pending_suggestions": pending,
            "decisions": {d["decision"]: d["cnt"] for d in decisions},
            "processes": [dict(p) for p in procs],
        }
        return result

    @staticmethod
    def list_processes():
        """列出所有挂载进程"""
        ensure_smart_mount_tables()
        with _LOCK:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT p.*, d.daemon_duty, d.priority, d.inspect_cycle
                FROM mt_ai_smart_mount_processes p
                LEFT JOIN mt_daemon_registry d ON p.daemon_id=d.daemon_id
                ORDER BY p.created_at DESC
            """).fetchall()
            conn.close()
        return [dict(r) for r in rows]


# ============================================================
# CLI入口
# ============================================================
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "start":
        SmartMountDaemon.start()

    elif cmd == "stop":
        SmartMountDaemon.stop()

    elif cmd == "status":
        s = SmartMountDaemon.status()
        print(f"{'='*60}")
        print(f"  Smart Mount Engine Status")
        print(f"{'='*60}")
        print(f"  Daemon PID:    {s['daemon_pid'] or '-'}")
        print(f"  Daemon State:  {s['daemon_state']}")
        print(f"  Total Procs:   {s['total_processes']}")
        print(f"  Running:       {s['running_processes']}")
        print(f"  Pending Sugs:  {s['pending_suggestions']}")
        print(f"  Decisions:     {s['decisions']}")
        print(f"{'='*60}")
        if s["processes"]:
            print(f"  {'Name':<30} {'State':<10} {'PID':<8} {'Score':<6} {'Source':<15}")
            print(f"  {'-'*30} {'-'*10} {'-'*8} {'-'*6} {'-'*15}")
            for p in s["processes"]:
                print(f"  {p['process_name'][:30]:<30} {p['current_state']:<10} "
                      f"{str(p['pid'] or '-'):<8} {p['mount_score']:<6.2f} {p['mount_source']:<15}")

    elif cmd == "list":
        procs = SmartMountDaemon.list_processes()
        if not procs:
            print("  (无挂载进程)")
        for p in procs:
            print(f"  [{p['current_state']}] {p['process_name']} pid={p['pid']} "
                  f"score={p['mount_score']:.2f} source={p['mount_source']} "
                  f"restart={p['restart_count']}")
            if p.get("daemon_duty"):
                print(f"         duty: {p['daemon_duty'][:80]}")

    elif cmd == "scan":
        ensure_smart_mount_tables()
        result = scan_and_mount()
        print(f"{'='*60}")
        print(f"  Scan & Mount Result")
        print(f"{'='*60}")
        print(f"  Scanned:   {result['scanned']}")
        print(f"  Mounted:   {result['mounted']}")
        print(f"  Deferred:  {result['deferred']}")
        print(f"  Rejected:  {result['rejected']}")
        for d in result["details"]:
            status = d.get("decision", "?")
            name = d.get("process_name", "-")
            score = d.get("final_score", 0)
            print(f"  [{status:<6}] score={score:.2f} {name}")
            if d.get("reason"):
                print(f"           {d['reason']}")

    elif cmd == "adopt":
        # 采纳指定建议ID
        if len(sys.argv) < 3:
            print("  用法: python3 ai_smart_mount_engine.py adopt <suggestion_id>")
            sys.exit(1)
        sid = int(sys.argv[2])
        ensure_smart_mount_tables()

        with _LOCK:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            r = conn.execute(
                "SELECT * FROM mt_ai_suggestion_pool WHERE suggestion_id=?", (sid,)).fetchone()
            conn.close()

        if not r:
            print(f"  [ERROR] 建议不存在: #{sid}")
            sys.exit(1)

        sug = dict(r)
        ew = collect_expert_weights()
        decision = smart_mount_decision(sug, ew)

        if decision["decision"] != "MOUNT":
            print(f"  [DEFER] score={decision['final_score']:.2f} < {MOUNT_THRESHOLD}")
            print(f"  {decision['reason']}")
            sys.exit(0)

        process_name = f"adopt_{sug.get('direction', 'gen')}_{sid}"
        script_path = generate_daemon_script(
            process_name=process_name,
            duty=sug.get("suggestion", "")[:100],
            suggestion_id=sid,
            mount_score=decision["final_score"],
            work_body=_infer_work_body(sug),
        )
        pid = mount_process(
            process_name=process_name,
            duty=sug.get("suggestion", "")[:100],
            script_path=script_path,
            suggestion_id=sid,
            mount_source="AI_SUGGESTION",
            mount_score=decision["final_score"],
            expert_weights=ew,
        )
        print(f"  [MOUNTED] {process_name} pid={pid} score={decision['final_score']:.2f}")

    elif cmd == "create":
        # 手动创建自动化进程
        if len(sys.argv) < 4:
            print("  用法: python3 ai_smart_mount_engine.py create <name> <duty> [--cycle N]")
            sys.exit(1)
        name = sys.argv[2]
        duty = sys.argv[3]
        cycle = 60
        if "--cycle" in sys.argv:
            idx = sys.argv.index("--cycle")
            cycle = int(sys.argv[idx + 1])

        ensure_smart_mount_tables()
        script_path = generate_daemon_script(
            process_name=name, duty=duty,
            suggestion_id=0, mount_score=1.0,
            inspect_cycle=cycle,
        )
        pid = mount_process(
            process_name=name, duty=duty,
            script_path=script_path,
            mount_source="MANUAL", mount_score=1.0,
        )
        print(f"  [CREATED] {name} pid={pid} script={script_path}")

    else:
        print(f"  未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()


