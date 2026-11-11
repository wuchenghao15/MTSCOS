# -*- coding: utf-8 -*-
"""
备份中心 Webhook 触发蓝图 (flow_backup_webhook_20261025)
=========================================================
GitHub/Gitee push → 签名验证 → 后台触发 ai_backup_kernel.run_once()

安全设计:
  1. GitHub: X-Hub-Signature-256 = HMAC-SHA256(secret_key, request_body)
  2. Gitee:  X-Gitee-Token      = 与配置密码严格相等
  3. 签名验证失败 → 403 + 落库 mt_backup_webhook_log
  4. 速率限制: 同一 source 10min 内最多 1 次 (kernel 单次 2-5min, 防重试风暴)
  5. kernel 以 subprocess.Popen 后台启动 → 立即返回 200 (webhook 超时 10-30s)
  6. 落库 mt_backup_webhook_log: run_id / source / sha / actor / ok / 耗时

路由:
  POST /api/backup/webhook/github  → GitHub push webhook
  POST /api/backup/webhook/gitee   → Gitee push webhook
  GET  /api/backup/webhook/health  → 健康检查 (public)
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import time
import uuid
from flask import Blueprint, request, jsonify

backup_webhook_bp = Blueprint("backup_webhook", __name__, url_prefix="/api/backup/webhook")

# ═══════════════════════════════════════════════════════════
# 配置 (优先环境变量, 次选 DB, 最后 fallback 默认)
# ═══════════════════════════════════════════════════════════

def _db_path():
    """mini Flask DB 路径"""
    # server_real_db.py 用的就是这个路径
    return os.path.join(os.path.dirname(__file__), "..", "database", "app.db")

def _cfg():
    """读 webhook 配置 (从 DB, 第一次自动生成)"""
    db = _db_path()
    c = sqlite3.connect(db, timeout=10, isolation_level=None)
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    try:
        row = c.execute(
            "SELECT cfg_key, cfg_value FROM mt_backup_webhook_cfg WHERE cfg_key IN "
            "('github_secret','gitee_token','rate_limit_sec','min_interval_sec')"
        ).fetchall()
        d = {r[0]: r[1] for r in row}
    except Exception:
        d = {}

    # 自动生成 + 落库
    if "github_secret" not in d or not d["github_secret"]:
        d["github_secret"] = os.environ.get("GITHUB_WEBHOOK_SECRET") or secrets.token_hex(32)
        try: c.execute("INSERT OR IGNORE INTO mt_backup_webhook_cfg (cfg_key,cfg_value) VALUES (?,?)",
                       ("github_secret", d["github_secret"]))
        except Exception: pass
    if "gitee_token" not in d or not d["gitee_token"]:
        d["gitee_token"] = os.environ.get("GITEE_WEBHOOK_TOKEN") or secrets.token_hex(24)
        try: c.execute("INSERT OR IGNORE INTO mt_backup_webhook_cfg (cfg_key,cfg_value) VALUES (?,?)",
                       ("gitee_token", d["gitee_token"]))
        except Exception: pass
    if "rate_limit_sec" not in d:
        d["rate_limit_sec"] = "600"  # 10min
        try: c.execute("INSERT OR IGNORE INTO mt_backup_webhook_cfg (cfg_key,cfg_value) VALUES (?,?)",
                       ("rate_limit_sec", d["rate_limit_sec"]))
        except Exception: pass
    if "min_interval_sec" not in d:
        d["min_interval_sec"] = "300"  # 5min
        try: c.execute("INSERT OR IGNORE INTO mt_backup_webhook_cfg (cfg_key,cfg_value) VALUES (?,?)",
                       ("min_interval_sec", d["min_interval_sec"]))
        except Exception: pass
    c.commit()
    c.close()
    return d


def _ensure_tables():
    """建表 (幂等, 第一次 Flask 启动时跑)"""
    db = _db_path()
    c = sqlite3.connect(db, timeout=10, isolation_level=None)
    c.execute("PRAGMA busy_timeout=5000")
    c.executescript("""
        CREATE TABLE IF NOT EXISTS mt_backup_webhook_log (
            run_id          TEXT PRIMARY KEY,
            source          TEXT NOT NULL,
            action          TEXT,
            actor           TEXT,
            commit_sha      TEXT,
            ref             TEXT,
            payload_size    INTEGER DEFAULT 0,
            signature_ok    INTEGER DEFAULT 0,
            rate_limited    INTEGER DEFAULT 0,
            kernel_pid      INTEGER DEFAULT 0,
            kernel_ok       INTEGER DEFAULT 0,
            kernel_ms       INTEGER DEFAULT 0,
            detail          TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS mt_backup_webhook_cfg (
            cfg_key   TEXT PRIMARY KEY,
            cfg_value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS mt_backup_webhook_throttle (
            source     TEXT PRIMARY KEY,
            last_run_at INTEGER DEFAULT 0,
            last_run_id TEXT
        );
    """)
    c.commit()
    c.close()


def _throttle(source: str, interval_sec: int) -> tuple[bool, int]:
    """返回 (是否应节流, 剩余等待秒)"""
    db = _db_path()
    c = sqlite3.connect(db, timeout=10, isolation_level=None)
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    try:
        row = c.execute("SELECT last_run_at FROM mt_backup_webhook_throttle WHERE source=?",
                        (source,)).fetchone()
        now = int(time.time())
        if row and (now - row[0]) < interval_sec:
            wait = interval_sec - (now - row[0])
            c.close()
            return True, wait
        c.execute(
            "INSERT INTO mt_backup_webhook_throttle (source, last_run_at) VALUES (?,?) "
            "ON CONFLICT(source) DO UPDATE SET last_run_at=excluded.last_run_at",
            (source, now))
        c.commit()
    except Exception as e:
        c.close()
        # DB 挂了 → 不节流 (fail-open, 但 kernel 自身有 DONE 锁, 不会并发)
        return False, 0
    c.close()
    return False, 0


def _hmac_verify(raw_body: bytes, header_sig: str, secret: str) -> bool:
    """GitHub HMAC-SHA256 签名验证"""
    if not header_sig or not header_sig.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = header_sig[7:]  # 去掉 "sha256=" 前缀
    # 常量时间比较, 防时序攻击
    return hmac.compare_digest(expected, provided)


def _spawn_kernel(source: str, commit_sha: str = "", actor: str = "") -> dict:
    """后台启动 ai_backup_kernel, 立即返回 run_id + pid"""
    run_id = "BKH-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8])

    # kernel 文件路径 (相对 flask-app 目录)
    kernel_path = os.path.join(os.path.dirname(__file__), "..", "engines", "ai_backup_kernel.py")
    engine_dir = os.path.dirname(kernel_path)

    try:
        proc = subprocess.Popen(
            ["python3", kernel_path, "once"],
            cwd=os.path.dirname(engine_dir),  # flask-app 目录
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # 脱离 Flask 进程组, 防 Flask 退出被带死
        )
        pid = proc.pid
    except Exception as e:
        return {"run_id": run_id, "pid": 0, "ok": False, "error": str(e)[:80]}

    # 落库 (立即, 不等 kernel 完成)
    db = _db_path()
    c = sqlite3.connect(db, timeout=10, isolation_level=None)
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.execute("""INSERT INTO mt_backup_webhook_log
        (run_id, source, action, actor, commit_sha, kernel_pid, detail, signature_ok, rate_limited)
        VALUES (?,?,?,?,?,?,?,1,0)""",
        (run_id, source, "push", actor[:64] if actor else "", commit_sha[:12] if commit_sha else "",
         pid, f"webhook触发 background spawn pid={pid}"))
    c.commit()
    c.close()

    return {"run_id": run_id, "pid": pid, "ok": True}


# ═══════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════

@backup_webhook_bp.route("/health", methods=["GET"])
def webhook_health():
    """公开健康检查 (Cloudflare Tunnel/监控用)"""
    _ensure_tables()
    # 读最新 run
    db = _db_path()
    c = sqlite3.connect(db, timeout=5)
    try:
        last = c.execute(
            "SELECT run_id, source, kernel_ok, kernel_ms, created_at "
            "FROM mt_backup_webhook_log ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    except Exception:
        last = None
    c.close()
    return jsonify({
        "ok": True,
        "service": "backup_webhook",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": last and {
            "run_id": last[0], "source": last[1],
            "kernel_ok": bool(last[2]) if last[2] is not None else None,
            "kernel_ms": last[3], "created_at": last[4]
        } or None
    })


@backup_webhook_bp.route("/github", methods=["POST"])
def webhook_github():
    """GitHub push webhook → 触发备份 kernel"""
    _ensure_tables()
    cfg = _cfg()
    raw = request.get_data() or b""
    header_sig = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}

    # 签名验证
    secret = cfg.get("github_secret", "")
    sig_ok = _hmac_verify(raw, header_sig, secret)
    if not sig_ok:
        _log_fail("github", "SIGNATURE_MISMATCH", payload)
        return jsonify({"ok": False, "error": "signature mismatch"}), 403

    # 只处理 push 事件
    if event != "push":
        return jsonify({"ok": True, "skipped": True, "reason": f"event={event} (not push)"}), 200

    # 速率限制
    interval = int(cfg.get("min_interval_sec", "300"))
    throttled, wait = _throttle("github", interval)
    if throttled:
        _log_throttle("github", wait, payload)
        return jsonify({"ok": True, "throttled": True, "wait_sec": wait}), 200

    # 提取 commit 信息
    ref = payload.get("ref", "")
    commits = payload.get("commits", [])
    commit_sha = commits[-1].get("id", "") if commits else ""
    head_sha = payload.get("after", "")
    sha = commit_sha or head_sha or ""
    pusher = payload.get("pusher", {}).get("name", "") or payload.get("sender", {}).get("login", "")

    # 触发 kernel (后台)
    r = _spawn_kernel("github", sha, pusher)
    if not r["ok"]:
        return jsonify({"ok": False, "error": r["error"]}), 500

    return jsonify({
        "ok": True,
        "run_id": r["run_id"],
        "kernel_pid": r["pid"],
        "source": "github",
        "commit_sha": sha,
        "actor": pusher,
        "ref": ref,
        "note": "kernel spawned in background; webhook returns immediately per 10-30s timeout"
    }), 200


@backup_webhook_bp.route("/gitee", methods=["POST"])
def webhook_gitee():
    """Gitee push webhook → 触发备份 kernel"""
    _ensure_tables()
    cfg = _cfg()
    raw = request.get_data() or b""
    token = request.headers.get("X-Gitee-Token", "") or request.headers.get("X-Webhook-Token", "")
    event = request.headers.get("X-Gitee-Event", "") or request.args.get("event", "")
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}

    # 鉴权: X-Gitee-Token 严格相等
    expected = cfg.get("gitee_token", "")
    if not expected or not token or token != expected:
        _log_fail("gitee", "TOKEN_MISMATCH", payload)
        return jsonify({"ok": False, "error": "token mismatch"}), 403

    # 只处理 push (Gitee 叫 "push_hooks" 或 "push")
    if event not in ("push", "push_hooks"):
        return jsonify({"ok": True, "skipped": True, "reason": f"event={event}"}), 200

    # 速率限制
    interval = int(cfg.get("min_interval_sec", "300"))
    throttled, wait = _throttle("gitee", interval)
    if throttled:
        _log_throttle("gitee", wait, payload)
        return jsonify({"ok": True, "throttled": True, "wait_sec": wait}), 200

    # 提取信息
    ref = payload.get("ref", "") or payload.get("ref_name", "")
    commits = payload.get("commits", [])
    commit_sha = commits[-1].get("id", "") if commits else ""
    head_sha = payload.get("head_commit", {}).get("id", "") if isinstance(payload.get("head_commit"), dict) else ""
    sha = commit_sha or head_sha or ""
    pusher = payload.get("sender", {}).get("login", "") or payload.get("user_name", "")

    # 触发 kernel (后台)
    r = _spawn_kernel("gitee", sha, pusher)
    if not r["ok"]:
        return jsonify({"ok": False, "error": r["error"]}), 500

    return jsonify({
        "ok": True,
        "run_id": r["run_id"],
        "kernel_pid": r["pid"],
        "source": "gitee",
        "commit_sha": sha,
        "actor": pusher,
        "ref": ref,
        "note": "kernel spawned in background"
    }), 200


# ═══════════════════════════════════════════════════════════
# 辅助函数 (失败/节流落库)
# ═══════════════════════════════════════════════════════════

def _log_fail(source: str, reason: str, payload: dict):
    try:
        db = _db_path()
        c = sqlite3.connect(db, timeout=5, isolation_level=None)
        c.execute("""INSERT INTO mt_backup_webhook_log
            (run_id, source, detail, signature_ok, rate_limited)
            VALUES (?,?,?,0,0)""",
            ("FAIL-%s-%d" % (source, int(time.time())), source, reason))
        c.commit()
        c.close()
    except Exception:
        pass


def _log_throttle(source: str, wait: int, payload: dict):
    try:
        db = _db_path()
        c = sqlite3.connect(db, timeout=5, isolation_level=None)
        c.execute("""INSERT INTO mt_backup_webhook_log
            (run_id, source, detail, signature_ok, rate_limited)
            VALUES (?,?,?,1,1)""",
            ("THROTTLE-%s-%d" % (source, int(time.time())), source, f"wait={wait}s"))
        c.commit()
        c.close()
    except Exception:
        pass


print("[BACKUP-WEBHOOK] ✅ backup_webhook_bp 已加载 "
      "(routes: /github /gitee /health; "
      "签名验证+速率限制+后台kernel触发)")
