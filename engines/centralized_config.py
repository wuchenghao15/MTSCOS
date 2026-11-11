#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralized Config — 解决 os.environ 分散问题
====================================
所有 26+ ENV 变量 + DB 配置表 → 统一 get(key, default) 入口

优先级 (从高到低):
  1. 进程内 _cache (5min TTL)
  2. agent_registry.config_json / mt_iceberg_threshold_configs 等 DB 表
  3. os.environ
  4. .env file
  5. default 参数

提供便捷方法:
  - get_ollama()    → Ollama 三件套配置
  - get_db()        → 主 DB 路径
  - get_daemon_status(name) → 查询 mt_daemon_registry
  - list_all()      → 列出所有已知 key + value + source
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════════
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROD_LOCAL = Path.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"


def _resolve_db_path(db_path: Optional[str | Path] = None) -> Path:
    if db_path:
        return Path(db_path)
    _DB_ENV = os.environ.get('ANDROMEDA_DB') or os.environ.get('APP_DB')
    if _DB_ENV and os.path.exists(_DB_ENV):
        return Path(_DB_ENV)
    if _PROD_LOCAL.exists() and _PROD_LOCAL.stat().st_size > 1_000_000:
        return _PROD_LOCAL
    return _PROJECT_ROOT / "database" / "app.db"


def _resolve_env_file(env_file: Optional[str | Path] = None) -> Path:
    if env_file:
        return Path(env_file)
    return _PROJECT_ROOT / ".env"


# ═══════════════════════════════════════════════════════════════════
# ConfigCenter 核心类
# ═══════════════════════════════════════════════════════════════════
class ConfigCenter:
    """统一配置中心 — DB > os.environ > .env > default"""

    _instance: Optional[ConfigCenter] = None
    _lock = threading.Lock()

    # 默认值表 (按 key → (default, 描述, 分组))
    DEFAULTS: Dict[str, Tuple[Any, str, str]] = {
        # ── Ollama ──
        "OLLAMA_BASE":       ("http://127.0.0.1:11434", "Ollama API base URL", "ollama"),
        "OLLAMA_MODEL":      ("qwen2.5:3b",             "默认对话模型",       "ollama"),
        "OLLAMA_EMBED_MODEL":("nomic-embed-text:latest","Embedding 模型",     "ollama"),
        "OLLAMA_VISION_MODEL":("llava:latest",          "视觉模型",           "ollama"),

        # ── DB ──
        "MT_MAIN_DB_PATH":   ("database/app.db",        "主 DB 相对路径",     "db"),
        "DATABASE_URI":      ("sqlite:///data/app.db",  "SQLAlchemy URI",     "db"),
        "DATABASE_TYPE":     ("sqlite",                 "DB 类型",            "db"),

        # ── Server ──
        "SERVER_HOST":       ("0.0.0.0",                "服务监听地址",       "server"),
        "SERVER_PORT":       ("8888",                   "服务端口",           "server"),
        "FLASK_PORT":        ("5001",                   "Flask 端口(备用)",   "server"),
        "HTTPS_ENABLED":     ("false",                  "HTTPS 开关",         "server"),
        "FLASK_APP":         ("app.py",                 "Flask app 文件名",   "server"),
        "FLASK_ENV":         ("production",             "Flask 环境",         "server"),

        # ── Redis ──
        "REDIS_HOST":        ("127.0.0.1",              "Redis host",         "redis"),
        "REDIS_PORT":        ("6379",                   "Redis port",         "redis"),
        "REDIS_DB":          ("0",                      "Redis DB num",       "redis"),

        # ── Security ──
        "SECRET_KEY":        ("mtscos-dev-change-me",   "Flask SECRET_KEY",   "security"),
        "SESSION_TIMEOUT":   ("3600",                   "会话超时秒数",       "security"),
        "MAX_LOGIN_ATTEMPTS":("5",                      "最大登录重试",       "security"),

        # ── Logging ──
        "LOG_LEVEL":         ("INFO",                   "日志级别",           "logging"),
        "LOG_FILE":          ("logs/app.log",           "日志文件路径",       "logging"),

        # ── MTSCOS 内部 ──
        "MTSCOS_ENV":        ("production",             "MTSCOS 环境",        "mtscos"),
        "MTSCOS_REGION":     ("cn",                     "区域",               "mtscos"),
        "MTSCOS_VERSION":    ("25.11.0",                "版本号",             "mtscos"),
        "ICEBERG_HEALTH_THRESHOLD": ("70",           "冰山健康阈值",       "mtscos"),
        "GOBELIN_RISK_LIMIT": ("0.05",                  "古灵阁风险限额",     "mtscos"),
        "AUTOPILOT_CYCLE_SEC": ("300",                  "Autopilot 周期秒",   "mtscos"),
    }

    def __init__(self,
                 db_path: Optional[str | Path] = None,
                 env_file: Optional[str | Path] = None,
                 cache_ttl: int = 300):  # 5min TTL
        self.db_path = _resolve_db_path(db_path)
        self.env_file = _resolve_env_file(env_file)
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}  # key → (value, expires_at)
        self._cache_lock = threading.Lock()
        self._env_vars: Dict[str, str] = self._parse_env_file()
        self._conn: Optional[sqlite3.Connection] = None

    @classmethod
    def instance(cls, db_path: Optional[str | Path] = None) -> ConfigCenter:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
            return cls._instance

    # ── env file 解析 ────────────────────────────────────
    def _parse_env_file(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        try:
            if self.env_file.exists():
                for raw in self.env_file.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip()
                    # 去掉引号
                    if (val.startswith('"') and val.endswith('"')) or \
                       (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    out[key] = val
        except Exception as e:
            print(f"[ConfigCenter] parse .env failed: {e}")
        return out

    # ── DB 查询 ──────────────────────────────────────────
    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), timeout=10)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _query_db_config(self, key: str) -> Optional[Tuple[Any, str]]:
        """从 DB 多表查找配置值. 返回 (value, source) 或 None"""
        try:
            conn = self._get_conn()

            # 1. agent_registry — 某些 agent 配置
            try:
                rows = conn.execute(
                    "SELECT config_json FROM agent_registry WHERE name = ? AND status='active' "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (key,)
                ).fetchall()
                for r in rows:
                    try:
                        cfg = json.loads(r["config_json"] or "{}")
                        if key in cfg:
                            return (cfg[key], "DB:agent_registry")
                    except Exception:
                        pass
            except Exception:
                pass

            # 2. mt_iceberg_threshold_configs — 冰山阈值
            try:
                row = conn.execute(
                    "SELECT value FROM mt_iceberg_threshold_configs WHERE threshold_key = ?",
                    (key,)
                ).fetchone()
                if row:
                    return (row["value"], "DB:mt_iceberg_threshold_configs")
            except Exception:
                pass

            # 3. ai_cluster_config — 集群级配置
            try:
                row = conn.execute(
                    "SELECT config_value FROM ai_cluster_config WHERE config_key = ? LIMIT 1",
                    (key,)
                ).fetchone()
                if row:
                    return (row["config_value"], "DB:ai_cluster_config")
            except Exception:
                pass

            # 4. ai_employee_config
            try:
                row = conn.execute(
                    "SELECT config_value FROM ai_employee_config WHERE config_key = ? LIMIT 1",
                    (key,)
                ).fetchone()
                if row:
                    return (row["config_value"], "DB:ai_employee_config")
            except Exception:
                pass

            # 5. mt_wecom_config (如果是 wecom 相关 key)
            if "WECOM" in key.upper():
                try:
                    row = conn.execute(
                        "SELECT config_value FROM mt_wecom_config WHERE config_key = ? LIMIT 1",
                        (key,)
                    ).fetchone()
                    if row:
                        return (row["config_value"], "DB:mt_wecom_config")
                except Exception:
                    pass

        except Exception as e:
            print(f"[ConfigCenter] DB query error: {e}")
        return None

    # ── 主 get ───────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值. 优先级: cache → DB → os.environ → .env → default
        """
        now = time.time()

        # 1. Cache
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached[1] > now:
                return cached[0]

        # 2. DB
        db_val = self._query_db_config(key)
        if db_val is not None:
            val = db_val[0]
            with self._cache_lock:
                self._cache[key] = (val, now + self.cache_ttl)
            return val

        # 3. os.environ
        if key in os.environ:
            val = os.environ[key]
            with self._cache_lock:
                self._cache[key] = (val, now + self.cache_ttl)
            return val

        # 4. .env file
        if key in self._env_vars:
            val = self._env_vars[key]
            with self._cache_lock:
                self._cache[key] = (val, now + self.cache_ttl)
            return val

        # 5. DEFAULTS 表
        if key in self.DEFAULTS:
            val = self.DEFAULTS[key][0]
            return val

        # 6. 函数参数 default
        return default

    def get_with_source(self, key: str, default: Any = None) -> Tuple[Any, str]:
        """获取 (value, source)"""
        now = time.time()

        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached[1] > now:
                return (cached[0], "cache")

        db_val = self._query_db_config(key)
        if db_val is not None:
            with self._cache_lock:
                self._cache[key] = (db_val[0], now + self.cache_ttl)
            return db_val

        if key in os.environ:
            val = os.environ[key]
            with self._cache_lock:
                self._cache[key] = (val, now + self.cache_ttl)
            return (val, "os.environ")

        if key in self._env_vars:
            val = self._env_vars[key]
            with self._cache_lock:
                self._cache[key] = (val, now + self.cache_ttl)
            return (val, ".env")

        if key in self.DEFAULTS:
            return (self.DEFAULTS[key][0], "builtin_default")

        return (default, "argument_default")

    # ── 便捷 getter ──────────────────────────────────────
    def get_ollama(self) -> Dict[str, str]:
        return {
            "base":        self.get("OLLAMA_BASE", "http://127.0.0.1:11434"),
            "model":       self.get("OLLAMA_MODEL", "qwen2.5:3b"),
            "embed_model": self.get("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"),
            "vision_model":self.get("OLLAMA_VISION_MODEL", "llava:latest"),
        }

    def get_db(self) -> str:
        return str(self.db_path)

    def get_server(self) -> Dict[str, str]:
        return {
            "host": self.get("SERVER_HOST", "0.0.0.0"),
            "port": self.get("SERVER_PORT", "8888"),
            "flask_port": self.get("FLASK_PORT", "5001"),
            "https": self.get("HTTPS_ENABLED", "false"),
        }

    def get_daemon_status(self, daemon_name: str) -> Dict[str, Any]:
        """查询 mt_daemon_registry 中某个 daemon 的状态"""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT process_name, daemon_name, status, pid, last_heartbeat, "
                "interval_sec, restart_count, last_error "
                "FROM mt_daemon_registry "
                "WHERE process_name = ? OR daemon_name = ?",
                (daemon_name, daemon_name)
            ).fetchone()
            if row:
                return dict(row)
        except Exception as e:
            return {"error": str(e)}
        return {"error": "not_found", "daemon": daemon_name}

    def list_daemons(self) -> List[Dict[str, Any]]:
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT process_name, daemon_name, status, pid, last_heartbeat, interval_sec "
                "FROM mt_daemon_registry ORDER BY status, process_name"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            return [{"error": str(e)}]

    # ── list_all ──────────────────────────────────────────
    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """列出所有已知配置 key + value + source"""
        result: Dict[str, Dict[str, Any]] = {}
        # 1. 内置 defaults
        for k, (default_val, desc, group) in self.DEFAULTS.items():
            val, source = self.get_with_source(k, default_val)
            result[k] = {
                "value": val,
                "source": source,
                "description": desc,
                "group": group,
            }
        # 2. .env 文件中发现但 DEFAULTS 里没有的
        for k, v in self._env_vars.items():
            if k not in result:
                result[k] = {
                    "value": v,
                    "source": ".env",
                    "description": "",
                    "group": "unknown",
                }
        # 3. os.environ 里发现但 .env/DEFAULTS 里没有的 (白名单过滤密钥)
        _sensitive_keys = {"SECRET_KEY", "PASSWORD", "TOKEN", "KEY", "CERT"}
        for k, v in os.environ.items():
            if k in result:
                # os.environ 优先级更高, 标记覆盖
                if result[k]["source"] != "os.environ":
                    val, src = self.get_with_source(k)
                    if src == "os.environ":
                        result[k] = {**result[k], "value": val, "source": "os.environ"}
                continue
            # 跳过显然非配置的
            if k.startswith("_") or "PATH" in k or k in {"PWD", "HOME", "USER", "SHELL", "TERM"}:
                continue
            # 敏感 key 只显示 [SET]
            is_sensitive = any(s in k.upper() for s in _sensitive_keys)
            display_val = "[SET]" if is_sensitive else v
            result[k] = {
                "value": display_val,
                "source": "os.environ",
                "description": "",
                "group": "os_only",
            }
        return result

    def invalidate_cache(self, key: Optional[str] = None):
        with self._cache_lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════
_default_cc: Optional[ConfigCenter] = None


def _dcc() -> ConfigCenter:
    global _default_cc
    if _default_cc is None:
        _default_cc = ConfigCenter()
    return _default_cc


def get(key: str, default: Any = None) -> Any:
    return _dcc().get(key, default)


def get_ollama() -> Dict[str, str]:
    return _dcc().get_ollama()


def get_db() -> str:
    return _dcc().get_db()


def list_all() -> Dict[str, Dict[str, Any]]:
    return _dcc().list_all()


# ═══════════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  Centralized Config — 自测")
    print("=" * 60)

    cc = ConfigCenter()

    ollama = cc.get_ollama()
    print(f"\n[Ollama] {json.dumps(ollama, indent=2, ensure_ascii=False)}")

    db_path = cc.get_db()
    print(f"[DB] path: {db_path}")

    server = cc.get_server()
    print(f"[Server] {json.dumps(server, indent=2)}")

    print(f"\n[daemon count] {len(cc.list_daemons())} 个 daemon 在 mt_daemon_registry")

    all_cfg = cc.list_all()
    print(f"\n[list_all] 共 {len(all_cfg)} 个配置 key")

    # 按 group 聚合
    groups: Dict[str, List[str]] = {}
    for k, v in all_cfg.items():
        g = v.get("group", "?")
        groups.setdefault(g, []).append(k)
    print(f"\n分组:")
    for g, keys in sorted(groups.items()):
        print(f"  {g:15s}: {len(keys):3d} 个 — {', '.join(sorted(keys)[:6])}{'...' if len(keys) > 6 else ''}")

    # 抽查几个 key 的 source
    print(f"\n抽查 sources:")
    for k in ["OLLAMA_BASE", "SERVER_PORT", "LOG_LEVEL", "FLASK_ENV", "DATABASE_TYPE"]:
        v, src = cc.get_with_source(k)
        print(f"  {k:25s} = {str(v)[:40]:40s} (source: {src})")

    print("\n✅ Centralized Config OK")
