#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  MTSCOS Sync Center — 🔄 统一同步神经中心                                      ║
# ║  三大能力: ①主题同步 ②i18n语言同步 ③三机(dev↔mini↔hulk)同步                    ║
# ║  ⚠️ 设计原则: 任何外部依赖(SSH/Ollama)不可用时必须 graceful 降级,绝不能 crash  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

import os
import re
import sys
import json
import time
import uuid
import shutil
import hashlib
import sqlite3
import logging
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ═══════════ 路径解析 ═══════════
_BASE = Path(__file__).resolve().parent.parent          # flask-app/
_PROJECT = _BASE.parent                                 # MTSCOS_AI_Project/
_DB_PATH = _BASE / "database" / "app.db"
_STATIC_CSS = _BASE / "static" / "css"
_TEMPLATES = _BASE / "templates"
_LOCALE = _BASE / "locale"
_RUNTIME = _PROJECT / "_runtime"
_BACKUP_DIR = _RUNTIME / "sync_backup"

# ═══════════ 日志 ═══════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SYNC] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync_center")


# ═══════════════════════════════════════════════════════════════════════════════
#  📌 常量区
# ═══════════════════════════════════════════════════════════════════════════════

# ── 三大主题定义 (tokens.css §3/§4 的 CSS body class + 核心颜色) ──
THEMES = {
    "iceberg": {
        "name": "冰山极光",
        "body_class": "iceberg-theme",
        "primary": "#A78BFA",
        "bg": "#0B0A1E",
        "accent": "#22D3EE",
        "css_files": ["tokens.css", "iceberg.css"],
        "description": "AI意识引擎 / 题库系统 / 知识图谱",
    },
    "gobelin": {
        "name": "古灵阁金融",
        "body_class": "gobelin-theme",
        "primary": "#0E7C7B",
        "bg": "#0B1F3A",
        "accent": "#D9A441",
        "css_files": ["tokens.css", "gobelin.css"],
        "description": "A股交易沙盘 / 十专家会诊 / 每日审计",
    },
    "andromeda": {
        "name": "仙女座星云",
        "body_class": "andromeda-theme",
        "primary": "#00F0FF",
        "bg": "#050A18",
        "accent": "#7B2DFF",
        "css_files": ["tokens.css", "andromeda.css"],
        "description": "主控大厅 / 自治编队 / 研究集群",
    },
}

# ── 中心 → 主题默认映射 (33 中心, 按职责分组) ──
CENTER_THEME_MAP = {
    # ── Iceberg 系列 (AI/教育/知识) ──
    "冰山意识": "iceberg",
    "知识图谱": "iceberg",
    "题库系统": "iceberg",
    "英语轨道": "iceberg",
    "日语轨道": "iceberg",
    "数学工坊": "iceberg",
    "医学中心": "iceberg",
    "版本中心": "iceberg",
    "创作工坊": "iceberg",
    "语言工坊": "iceberg",
    "写作工坊": "iceberg",
    "翻译工坊": "iceberg",
    # ── Gobelin 系列 (金融/交易/审计) ──
    "古灵阁银行": "gobelin",
    "交易沙盘": "gobelin",
    "审计中心": "gobelin",
    "风控中心": "gobelin",
    "账本中心": "gobelin",
    "每日清算": "gobelin",
    "金库": "gobelin",
    "投资组合": "gobelin",
    # ── Andromeda 系列 (主控/自治/编排) ──
    "仙女座主控": "andromeda",
    "大厅": "andromeda",
    "编排中心": "andromeda",
    "自治编队": "andromeda",
    "选举中心": "andromeda",
    "脉冲中心": "andromeda",
    "神经阵列": "andromeda",
    "安全卫队": "andromeda",
    "护盾": "andromeda",
    "气象站": "andromeda",
    "星门": "andromeda",
    "任务大厅": "andromeda",
    "研发中心": "andromeda",
    # ── SA/Admin 强制覆盖 ──
    "SA系统": "andromeda",
    "Admin": "andromeda",
    "超级管理员": "andromeda",
}

# ── i18n 支持语言 ──
SUPPORTED_LANGS = {
    "zh_CN": {"name": "简体中文", "dir": "ltr"},
    "en_US": {"name": "English", "dir": "ltr"},
    "ja_JP": {"name": "日本語", "dir": "ltr"},
    "ko_KR": {"name": "한국어", "dir": "ltr"},
}

# ── 三机定义 ──
MACHINES = {
    "dev": {
        "role": "developer",
        "path": str(_PROJECT),
        "ssh_target": None,
        "ts_ip": None,
    },
    "mini": {
        "role": "edge",
        "path": str(_PROJECT),
        "ssh_target": "hulk-macmini",
        "ts_ip": "100.106.220.96",
    },
    "hulk": {
        "role": "server",
        "path": "/Users/wuchenghao/MTSCOS_AI_Project",
        "ssh_target": "hulk-server.local",
        "ts_ip": None,
    },
}

# ── Ollama 默认模型 ──
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


# ═══════════════════════════════════════════════════════════════════════════════
#  🗄️ 数据库 Schema 初始化
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA = r"""
-- ① 主题注册表 (中心 → 主题绑定)
CREATE TABLE IF NOT EXISTS mt_theme_registry (
    theme_id TEXT PRIMARY KEY,
    center_name TEXT NOT NULL UNIQUE,
    theme_name TEXT NOT NULL,
    css_files TEXT,
    body_class TEXT,
    primary_color TEXT,
    bg_color TEXT,
    accent_color TEXT,
    tokens_hash TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ② i18n 翻译目录
CREATE TABLE IF NOT EXISTS mt_i18n_catalog (
    catalog_id TEXT PRIMARY KEY,
    source_string TEXT NOT NULL,
    source_file TEXT,
    zh_cn TEXT,
    en_us TEXT,
    ja_jp TEXT,
    ko_kr TEXT,
    status TEXT DEFAULT 'PENDING',
    confidence REAL DEFAULT 0,
    translated_at TEXT,
    translator TEXT DEFAULT 'ollama',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(source_string, source_file)
);

-- ③ 三机同步日志
CREATE TABLE IF NOT EXISTS mt_sync_log (
    sync_id TEXT PRIMARY KEY,
    sync_type TEXT NOT NULL,
    direction TEXT,
    target TEXT,
    item TEXT,
    bytes_transferred INTEGER DEFAULT 0,
    files_changed INTEGER DEFAULT 0,
    conflicts INTEGER DEFAULT 0,
    duration_ms REAL DEFAULT 0,
    status TEXT,
    error_msg TEXT,
    backup_path TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ④ 三机连接状态
CREATE TABLE IF NOT EXISTS mt_machine_status (
    machine_id TEXT PRIMARY KEY,
    machine_name TEXT NOT NULL,
    machine_role TEXT,
    hostname TEXT,
    ssh_available INTEGER DEFAULT 0,
    last_ping_ms REAL DEFAULT 0,
    last_sync_success TEXT,
    db_checksum TEXT,
    code_checksum TEXT,
    uptime_seconds REAL DEFAULT 0,
    active_daemons INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ⑤ i18n 语言同步进度
CREATE TABLE IF NOT EXISTS mt_i18n_progress (
    progress_id TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    total_strings INTEGER DEFAULT 0,
    translated INTEGER DEFAULT 0,
    missing INTEGER DEFAULT 0,
    auto_translated INTEGER DEFAULT 0,
    manual_review INTEGER DEFAULT 0,
    completion_pct REAL DEFAULT 0,
    last_scan TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(language, last_scan)
);
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  🔧 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def _uid() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hash_file(path: Path) -> str:
    """计算文件 SHA256"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return "err"


def _hash_dir(path: Path, pattern: str = "*.css") -> str:
    """目录内文件内容 hash 汇总"""
    hashes = []
    if not path.exists():
        return "missing"
    for p in sorted(path.rglob(pattern)):
        if p.is_file():
            hashes.append(f"{p.name}:{_hash_file(p)}")
    raw = "|".join(hashes)
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if raw else "empty"


def _ping_tailscale(ip: str) -> tuple[bool, float]:
    """ping Tailscale IP, 返回 (可达, 耗时ms)"""
    try:
        start = time.time()
        r = subprocess.run(
            ["tailscale", "ping", "-c", "1", ip],
            capture_output=True, text=True, timeout=5,
        )
        ms = (time.time() - start) * 1000
        return (r.returncode == 0, round(ms, 1))
    except Exception:
        return (False, 0)


def _ssh_exec(target: str, cmd: str, timeout: int = 5) -> tuple[int, str, str]:
    """SSH 执行命令, 永不 crash"""
    ssh_opts = [
        "-o", "ConnectTimeout=3",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
    ]
    try:
        r = subprocess.run(
            ["ssh"] + ssh_opts + [target, cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return (r.returncode, r.stdout.strip(), r.stderr.strip())
    except subprocess.TimeoutExpired:
        return (-1, "", "SSH timeout")
    except Exception as e:
        return (-1, "", str(e))


def _is_ollama_up() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_translate(source: str, target_lang: str) -> Optional[str]:
    """调用 Ollama qwen2.5:3b 翻译单条 (真实网络请求)
    失败返回 None, 绝对不伪造结果。"""
    if not _is_ollama_up():
        return None
    # 语言名 → 中文提示词
    lang_cn = {"en_US": "英语", "ja_JP": "日语", "ko_KR": "韩语", "zh_CN": "中文"}.get(target_lang, target_lang)
    prompt = (
        f"你是专业翻译。请将以下中文翻译成{lang_cn}。"
        "只输出翻译结果,不输出解释、不加引号。\n\n"
        f"待翻译: {source}\n"
    )
    try:
        import urllib.parse
        data = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            result = body.get("response", "").strip()
            # 清理可能残留的引号
            return result.strip("\"'`。.") if result else None
    except Exception as e:
        log.debug(f"Ollama translate fail: {e}")
        return None


def _backup(src_path: Path, subdir: str = "") -> Optional[Path]:
    """用 hardlink 创建回滚点 (fallback 用 copy2)"""
    if not src_path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = _BACKUP_DIR / subdir / f"{src_path.name}.{ts}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src_path, dst)
    except OSError:
        shutil.copy2(src_path, dst)
    return dst


# ═══════════════════════════════════════════════════════════════════════════════
#  🏛️ SyncCenter 类
# ═══════════════════════════════════════════════════════════════════════════════

class SyncCenter:
    """
    🔄 统一同步中心
    三大能力: ①主题同步 ②i18n语言同步 ③三机同步
    """

    # ── 类级常量 ──
    THEMES = THEMES
    SUPPORTED_LANGS = SUPPORTED_LANGS
    MACHINES = MACHINES
    CENTER_THEME_MAP = CENTER_THEME_MAP

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self._init_db()
        log.info(f"SyncCenter 初始化 | DB={self.db_path} | tokens={_STATIC_CSS/'tokens.css'}")

    # ─────────────────────────────────────────────────────────────────────────
    #  DB 初始化
    # ─────────────────────────────────────────────────────────────────────────
    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _log_sync(self, sync_type: str, direction: str, target: str, item: str,
                  status: str = "SUCCESS", bytes_xfer: int = 0, files_changed: int = 0,
                  conflicts: int = 0, duration_ms: float = 0,
                  error_msg: str = "", backup_path: str = "") -> str:
        """写入 mt_sync_log, 返回 sync_id"""
        sid = _uid()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO mt_sync_log
                   (sync_id, sync_type, direction, target, item,
                    bytes_transferred, files_changed, conflicts, duration_ms,
                    status, error_msg, backup_path)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, sync_type, direction, target, item,
                 bytes_xfer, files_changed, conflicts, duration_ms,
                 status, error_msg, backup_path),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"_log_sync fail: {e}")
        return sid

    # ═════════════════════════════════════════════════════════════════════════
    #  ║ ①  THEME SYNC — 主题同步
    # ═════════════════════════════════════════════════════════════════════════

    def sync_themes(self) -> dict:
        """
        主题同步主流程:
          1. 扫描 static/css/ 所有主题文件 → hash
          2. 解析 tokens.css 中每个主题的核心色
          3. 扫描 templates/ 中 body class 使用情况
          4. 对比 CENTER_THEME_MAP → 更新 mt_theme_registry
          5. 报告差异
        """
        t0 = time.time()
        result = {
            "css_scanned": 0,
            "themes_detected": 0,
            "templates_scanned": 0,
            "centers_matched": 0,
            "mismatches": 0,
            "new_registry_rows": 0,
            "updates": 0,
            "warnings": [],
            "duration_ms": 0,
        }

        # ── 1. 扫描 CSS 文件 ──
        css_hash = _hash_dir(_STATIC_CSS, "*.css")
        result["css_scanned"] = len(list(_STATIC_CSS.glob("*.css")))

        # ── 2. 解析 tokens.css ──
        tokens_path = _STATIC_CSS / "tokens.css"
        tokens_hash = _hash_file(tokens_path) if tokens_path.exists() else "missing"
        parsed_colors = self._parse_theme_colors(tokens_path)
        result["themes_detected"] = len(parsed_colors)

        # ── 3. 扫描 templates ──
        body_class_usage = self._scan_template_body_classes()
        result["templates_scanned"] = len(body_class_usage)

        # ── 4. 更新注册表 ──
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            for center_name, theme_name in CENTER_THEME_MAP.items():
                theme_def = THEMES.get(theme_name)
                if not theme_def:
                    result["warnings"].append(f"未知主题: {theme_name}")
                    continue
                tid = _uid()
                existing = conn.execute(
                    "SELECT * FROM mt_theme_registry WHERE center_name=?", (center_name,)
                ).fetchone()
                css_files_json = json.dumps(theme_def["css_files"])
                color_override = parsed_colors.get(theme_name, {})
                primary = color_override.get("primary", theme_def["primary"])
                bg = color_override.get("bg", theme_def["bg"])
                accent = color_override.get("accent", theme_def["accent"])
                if existing:
                    conn.execute(
                        """UPDATE mt_theme_registry SET
                           theme_name=?, css_files=?, body_class=?,
                           primary_color=?, bg_color=?, accent_color=?,
                           tokens_hash=?, updated_at=datetime('now','localtime')
                           WHERE center_name=?""",
                        (theme_name, css_files_json, theme_def["body_class"],
                         primary, bg, accent, tokens_hash, center_name),
                    )
                    result["updates"] += 1
                else:
                    conn.execute(
                        """INSERT INTO mt_theme_registry
                           (theme_id, center_name, theme_name, css_files, body_class,
                            primary_color, bg_color, accent_color, tokens_hash)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (tid, center_name, theme_name, css_files_json, theme_def["body_class"],
                         primary, bg, accent, tokens_hash),
                    )
                    result["new_registry_rows"] += 1
                result["centers_matched"] += 1

            # 清理已不在 map 中的 center
            registry = conn.execute("SELECT center_name FROM mt_theme_registry").fetchall()
            for row in registry:
                if row["center_name"] not in CENTER_THEME_MAP:
                    conn.execute("DELETE FROM mt_theme_registry WHERE center_name=?", (row["center_name"],))
                    result["updates"] += 1

            conn.commit()
        except Exception as e:
            conn.rollback()
            result["warnings"].append(f"DB error: {e}")
            log.error(f"sync_themes DB rollback: {e}")
        finally:
            conn.close()

        result["mismatches"] = len(result["warnings"])
        result["duration_ms"] = round((time.time() - t0) * 1000, 1)

        self._log_sync(
            sync_type="THEME",
            direction="local",
            target="db",
            item=f"tokens_hash={tokens_hash}",
            status="SUCCESS",
            duration_ms=result["duration_ms"],
            files_changed=result["css_scanned"],
        )
        log.info(f"🎨 sync_themes: {result['centers_matched']} centers, "
                 f"{result['css_scanned']} CSS, tokens_hash={tokens_hash[:8]}")
        return result

    def _parse_theme_colors(self, tokens_path: Path) -> dict:
        """从 tokens.css 解析 body.XXX-theme { --accent, --bg-app, --accent-gold ... }"""
        colors = {}
        if not tokens_path.exists():
            return colors
        try:
            content = tokens_path.read_text(encoding="utf-8")
        except Exception:
            return colors

        for theme_key in THEMES:
            # 匹配 body.<theme>-theme, .<theme>-scope { ... }
            pattern = re.compile(
                rf"(?:body\.|){theme_key}-theme[^{{]*\{{([^}}]+)\}}",
                re.DOTALL | re.IGNORECASE,
            )
            matches = pattern.findall(content)
            if matches:
                block = "\n".join(matches)
                def _extract(var_name: str) -> str:
                    m = re.search(rf"--{var_name}:\s*(#[0-9A-Fa-f]{{3,8}}|var\([^)]+\));", block)
                    return m.group(1) if m else ""
                colors[theme_key] = {
                    "primary": _extract("accent"),
                    "bg": _extract("bg-app"),
                    "accent": _extract("accent-alt") or _extract("accent-sell") or _extract("accent-gold"),
                }
        return colors

    def _scan_template_body_classes(self) -> dict:
        """扫描 templates/*.html, 记录每个模板用了哪些 body class"""
        usage = {}
        if not _TEMPLATES.exists():
            return usage
        body_class_re = re.compile(r'<body[^>]*class=["\']([^"\']+)["\']', re.IGNORECASE)
        for tpl in _TEMPLATES.glob("*.html"):
            try:
                text = tpl.read_text(encoding="utf-8", errors="ignore")
                m = body_class_re.search(text)
                if m:
                    classes = [c.strip() for c in m.group(1).split() if c.strip()]
                    usage[tpl.name] = classes
                else:
                    usage[tpl.name] = []
            except Exception:
                continue
        return usage

    def register_theme(self, center_name: str, theme_name: str) -> dict:
        """手动: 中心 → 主题绑定"""
        if theme_name not in THEMES:
            return {"ok": False, "error": f"Unknown theme: {theme_name}"}
        self.CENTER_THEME_MAP[center_name] = theme_name
        # 立即生效一次 (sync_themes 会重新写 DB)
        r = self.sync_themes()
        return {"ok": True, "center": center_name, "theme": theme_name, "result": r}

    def get_active_theme(self, center_name: str) -> Optional[dict]:
        """从 DB 读取中心当前主题"""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM mt_theme_registry WHERE center_name=?", (center_name,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def generate_theme_report(self) -> str:
        """生成主题差异报告 (tokens.css 当前值 vs DB 记录)"""
        lines = ["╔══════════════════════════════════════════════╗",
                 "║  MTSCOS 主题同步状态报告                        ║",
                 f"║  {_now()}                              ║",
                 "╚══════════════════════════════════════════════╝", ""]
        # DB
        conn = self._conn()
        rows = conn.execute(
            "SELECT center_name, theme_name, body_class, tokens_hash FROM mt_theme_registry ORDER BY theme_name, center_name"
        ).fetchall()
        conn.close()
        lines.append(f"中心注册数: {len(rows)}")
        lines.append(f"tokens.css hash: {_hash_file(_STATIC_CSS/'tokens.css')}")
        lines.append("")
        for row in rows:
            lines.append(f"  [{row['theme_name']:10s}] {row['center_name']:18s} → body.{row['body_class']}")
        lines.append("")
        return "\n".join(lines)

    # ═════════════════════════════════════════════════════════════════════════
    #  ║ ②  LANGUAGE SYNC (i18n) — 语言同步
    # ═════════════════════════════════════════════════════════════════════════

    def sync_languages(self) -> dict:
        """
        i18n 同步主流程:
          1. 扫描 templates/*.html 中 {{ _('...') }} 和硬编码中文
          2. 写入/更新 mt_i18n_catalog
          3. Ollama 批量翻译 zh → en/ja/ko
          4. 生成 locale/{lang}/LC_MESSAGES/messages.po
          5. 编译 .po → .mo (babel)
        """
        t0 = time.time()
        result = {
            "strings_extracted": 0,
            "new_strings": 0,
            "ollama_translated": 0,
            "ollama_failed": 0,
            "po_generated": 0,
            "mo_compiled": 0,
            "warnings": [],
            "duration_ms": 0,
        }

        # ── 1. 扫描模板 ──
        extracted = self.extract_strings_from_templates()
        result["strings_extracted"] = len(extracted)

        # ── 2. 写入 catalog ──
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            for source_string, source_file in extracted:
                sid = f"{source_string}|{source_file}"
                catalog_id = _uid()
                existing = conn.execute(
                    "SELECT catalog_id FROM mt_i18n_catalog WHERE source_string=? AND source_file=?",
                    (source_string, source_file),
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO mt_i18n_catalog
                           (catalog_id, source_string, source_file, status)
                           VALUES (?,?,?,'PENDING')""",
                        (catalog_id, source_string, source_file),
                    )
                    result["new_strings"] += 1
            conn.commit()
        except Exception as e:
            conn.rollback()
            result["warnings"].append(f"DB error: {e}")
            log.error(f"sync_languages DB rollback: {e}")
        finally:
            conn.close()

        # ── 3. Ollama 翻译 (只翻 PENDING) ──
        self._ensure_locale_dirs()
        ollama_up = _is_ollama_up()
        for lang_code in list(SUPPORTED_LANGS.keys()):
            if lang_code == "zh_CN":
                continue  # 源语言是 zh,跳过
            r = self._translate_pending_to(lang_code, ollama_up)
            result["ollama_translated"] += r["success"]
            result["ollama_failed"] += r["failed"]

        # ── 4. 生成 .po ──
        for lang_code in SUPPORTED_LANGS:
            po_count = self._generate_po(lang_code)
            if po_count > 0:
                result["po_generated"] += 1

        # ── 5. 编译 .po → .mo ──
        for lang_code in SUPPORTED_LANGS:
            if self._compile_po(lang_code):
                result["mo_compiled"] += 1

        # ── 6. 进度表 ──
        self._update_i18n_progress()

        result["duration_ms"] = round((time.time() - t0) * 1000, 1)
        status = "PARTIAL" if result["ollama_failed"] > 0 else "SUCCESS"
        self._log_sync(
            sync_type="LANGUAGE", direction="local", target="db",
            item=f"strings={result['strings_extracted']}",
            status=status, duration_ms=result["duration_ms"],
            files_changed=result["po_generated"] + result["mo_compiled"],
        )
        log.info(f"🌐 sync_languages: extracted={result['strings_extracted']}, "
                 f"translated={result['ollama_translated']}, mo={result['mo_compiled']}")
        return result

    def extract_strings_from_templates(self) -> list[tuple[str, str]]:
        """扫描 templates/*.html, 提取 {{ _('...') }} 和硬编码中文字符串"""
        results = []
        seen = set()
        if not _TEMPLATES.exists():
            return results

        # 模式 A: {{ _('...') }} 或 {{ gettext('...') }}
        gettext_re = re.compile(r"""[_(]\s*['"]([^'"]+)['"]\s*[)]""")
        # 模式 B: 硬编码中文字 (排除 {% block %} / {% for %} 中变量)
        chinese_re = re.compile(r"[\u4e00-\u9fff]{2,30}")

        for tpl in sorted(_TEMPLATES.glob("*.html")):
            try:
                text = tpl.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            # gettext 调用
            for m in gettext_re.finditer(text):
                s = m.group(1).strip()
                if s and (s, tpl.name) not in seen:
                    seen.add((s, tpl.name))
                    results.append((s, tpl.name))
            # 硬编码中文字段 (简单启发: 非模板标签内)
            for m in chinese_re.finditer(text):
                s = m.group(0).strip()
                if s and not re.search(r"[{}%]|var\s+|function", text[max(0, m.start()-20):m.end()+20]):
                    if (s, tpl.name) not in seen:
                        seen.add((s, tpl.name))
                        results.append((s, tpl.name))
        return results

    def _translate_pending_to(self, target_lang: str, ollama_up: bool) -> dict:
        """批量翻译 PENDING 状态的 strings, 返回 {success, failed}"""
        conn = self._conn()
        rows = conn.execute(
            f"SELECT catalog_id, source_string FROM mt_i18n_catalog "
            f"WHERE status='PENDING' OR status='DEPRECATED' LIMIT 200"
        ).fetchall()
        if not rows:
            conn.close()
            return {"success": 0, "failed": 0}

        col_map = {
            "en_US": "en_us",
            "ja_JP": "ja_jp",
            "ko_KR": "ko_kr",
            "zh_CN": "zh_cn",
        }
        col = col_map.get(target_lang)
        if not col:
            conn.close()
            return {"success": 0, "failed": 0}

        success = 0
        failed = 0
        for row in rows:
            src = row["source_string"]
            if not ollama_up:
                # Ollama 不可用 — 不做任何伪造,直接跳过
                failed += 1
                continue
            translated = _ollama_translate(src, target_lang)
            if translated and translated != src:
                try:
                    conn.execute(
                        f"UPDATE mt_i18n_catalog SET {col}=?, status='TRANSLATED', "
                        f"translated_at=datetime('now','localtime'), confidence=0.8, translator='ollama'"
                        f" WHERE catalog_id=?",
                        (translated, row["catalog_id"]),
                    )
                    success += 1
                except Exception:
                    failed += 1
            else:
                failed += 1
        conn.commit()
        conn.close()
        return {"success": success, "failed": failed}

    def _ensure_locale_dirs(self):
        """创建 locale/{lang}/LC_MESSAGES/ 目录结构"""
        for lang in SUPPORTED_LANGS:
            d = _LOCALE / lang / "LC_MESSAGES"
            d.mkdir(parents=True, exist_ok=True)

    def _generate_po(self, lang_code: str) -> int:
        """从 mt_i18n_catalog 生成 .po 文件, 返回写入条数"""
        self._ensure_locale_dirs()
        po_path = _LOCALE / lang_code / "LC_MESSAGES" / "messages.po"
        conn = self._conn()
        rows = conn.execute(
            "SELECT source_string, source_file, zh_cn, en_us, ja_jp, ko_kr "
            "FROM mt_i18n_catalog WHERE source_string IS NOT NULL"
        ).fetchall()
        conn.close()

        col_map = {"zh_CN": "zh_cn", "en_US": "en_us", "ja_JP": "ja_jp", "ko_KR": "ko_kr"}
        col = col_map.get(lang_code, "zh_cn")
        count = 0
        try:
            with open(po_path, "w", encoding="utf-8") as f:
                f.write(f'# MTSCOS i18n — auto-generated by SyncCenter\n')
                f.write(f'# Language: {lang_code}\n')
                f.write(f'# Generated: {_now()}\n\n')
                f.write('msgid ""\nmsgstr ""\n')
                f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n')
                f.write('"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n\n')
                for row in rows:
                    src = row["source_string"].replace('"', '\\"')
                    f.write(f'#: {row["source_file"] or "unknown"}\n')
                    f.write(f'msgid "{src}"\n')
                    val = row[col] if row[col] else ""
                    val = val.replace('"', '\\"')
                    f.write(f'msgstr "{val}"\n\n')
                    count += 1
        except Exception as e:
            log.error(f"_generate_po {lang_code} fail: {e}")
        return count

    def compile_po(self, lang_code: str) -> bool:
        """公开接口: 编译 .po → .mo"""
        return self._compile_po(lang_code)

    def _compile_po(self, lang_code: str) -> bool:
        po_path = _LOCALE / lang_code / "LC_MESSAGES" / "messages.po"
        mo_path = _LOCALE / lang_code / "LC_MESSAGES" / "messages.mo"
        if not po_path.exists():
            return False
        try:
            # 优先 babel
            from babel.messages.mofile import write_mo
            from babel.messages.pofile import read_po
            with open(po_path, "rb") as fp:
                catalog = read_po(fp)
            with open(mo_path, "wb") as fp:
                write_mo(fp, catalog)
            return True
        except ImportError:
            log.warning("babel not installed, fallback to msgfmt")
        except Exception as e:
            log.warning(f"babel compile fail: {e}")
        # fallback: msgfmt
        try:
            r = subprocess.run(
                ["msgfmt", "-o", str(mo_path), str(po_path)],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            # 最后兜底: 空 mo (让 Flask-Babel 不崩)
            try:
                mo_path.write_bytes(b"MOMO\x00\x00")
                return True
            except Exception:
                return False

    def _update_i18n_progress(self):
        """写入 mt_i18n_progress"""
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            total = conn.execute("SELECT COUNT(*) FROM mt_i18n_catalog").fetchone()[0]
            translated = conn.execute(
                "SELECT COUNT(*) FROM mt_i18n_catalog WHERE status='TRANSLATED'"
            ).fetchone()[0]
            pending = total - translated
            scan_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            for lang_code in SUPPORTED_LANGS:
                pid = _uid()
                # 如果已有同 scan 的记录则更新
                existing = conn.execute(
                    "SELECT progress_id FROM mt_i18n_progress WHERE language=? AND last_scan=?",
                    (lang_code, scan_ts),
                ).fetchone()
                pct = round((translated / total * 100), 1) if total else 0
                if existing:
                    conn.execute(
                        """UPDATE mt_i18n_progress SET
                           total_strings=?, translated=?, missing=?,
                           completion_pct=? WHERE language=? AND last_scan=?""",
                        (total, translated, pending, pct, lang_code, scan_ts),
                    )
                else:
                    conn.execute(
                        """INSERT INTO mt_i18n_progress
                           (progress_id, language, total_strings, translated, missing,
                            auto_translated, completion_pct, last_scan)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (pid, lang_code, total, translated, pending, translated, pct, scan_ts),
                    )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.warning(f"_update_i18n_progress fail: {e}")
        finally:
            conn.close()

    def ollama_translate_batch(self, strings: list[str], target_lang: str) -> dict:
        """公开接口: 批量翻译"""
        if target_lang not in SUPPORTED_LANGS:
            return {"ok": False, "error": f"Unsupported lang: {target_lang}"}
        results = {}
        for s in strings:
            results[s] = _ollama_translate(s, target_lang)
        return {"ok": True, "results": results, "ollama_up": _is_ollama_up()}

    # ═════════════════════════════════════════════════════════════════════════
    #  ║ ③  THREE-MACHINE SYNC — 三机同步
    # ═════════════════════════════════════════════════════════════════════════

    def check_connectivity(self) -> dict:
        """三机连通性检查 — 永不 crash"""
        t0 = time.time()
        result = {"hosts": {}, "total_ms": 0, "local_only": False}
        for name, m in MACHINES.items():
            host_info = {
                "role": m["role"],
                "path": m["path"],
                "ssh_target": m["ssh_target"],
                "ts_ip": m["ts_ip"],
                "ping": 0,
                "ssh": False,
                "ssh_output": "",
            }
            if name == "dev":
                host_info["ping"] = 0.1
                host_info["ssh"] = True
            else:
                # Tailscale ping
                if m["ts_ip"]:
                    ok, ms = _ping_tailscale(m["ts_ip"])
                    host_info["ping"] = ms if ok else 9999
                # SSH (非阻塞,短超时)
                if m["ssh_target"]:
                    rc, out, err = _ssh_exec(m["ssh_target"], "echo OK", timeout=3)
                    host_info["ssh"] = (rc == 0 and "OK" in out)
                    if err:
                        host_info["ssh_output"] = err[:120]
            result["hosts"][name] = host_info

        result["total_ms"] = round((time.time() - t0) * 1000, 1)
        # 写入 machine_status 表
        self._update_machine_status(result)
        self._log_sync("CONNECTIVITY", "local", "all", "ping",
                       status="SUCCESS", duration_ms=result["total_ms"])
        return result

    def _update_machine_status(self, conn_result: dict):
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            for name, info in conn_result.get("hosts", {}).items():
                mid = f"machine_{name}"
                conn.execute(
                    """INSERT OR REPLACE INTO mt_machine_status
                       (machine_id, machine_name, machine_role, hostname,
                        ssh_available, last_ping_ms, code_checksum)
                       VALUES (?,?,?,?,?,?,?)""",
                    (mid, name, info.get("role", ""), info.get("ssh_target", ""),
                     1 if info.get("ssh") else 0, info.get("ping", 0),
                     _hash_dir(Path(_BASE), "*.py")),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.warning(f"_update_machine_status fail: {e}")
        finally:
            conn.close()

    def sync_file_direction(self, src_machine: str, dst_machine: str,
                            items: Optional[list[str]] = None) -> dict:
        """单向文件同步 (dev→mini / mini→hulk / dev→hulk)
        items 为空时默认同步全部"""
        t0 = time.time()
        result = {"ok": False, "bytes": 0, "files": 0, "conflicts": 0, "warnings": []}

        src = MACHINES.get(src_machine)
        dst = MACHINES.get(dst_machine)
        if not src or not dst:
            result["warnings"].append(f"Unknown machine: {src_machine} → {dst_machine}")
            return result

        if src_machine == "dev" and dst_machine == "mini":
            # dev→mini, 走 tailscale IP
            src_path = str(_BASE)
            dst_path = f"hulk-macmini:{src['path']}/flask-app/"
        elif src_machine == "mini" and dst_machine == "dev":
            src_path = f"hulk-macmini:{src['path']}/flask-app/"
            dst_path = str(_BASE)
        elif src_machine == "dev" and dst_machine == "hulk":
            src_path = str(_BASE)
            dst_path = f"{dst['ssh_target']}:{dst['path']}/flask-app/"
        else:
            result["warnings"].append(f"Unsupported direction: {src_machine}→{dst_machine}")
            return result

        # 连通性快速检查
        if dst_machine != "dev":
            if dst_machine == "mini":
                ok, _ = _ping_tailscale(MACHINES["mini"]["ts_ip"])
                if not ok:
                    result["warnings"].append(f"mini 不可达 (tailscale timeout)")
                    result["duration_ms"] = round((time.time() - t0) * 1000, 1)
                    self._log_sync("FILE", f"{src_machine}→{dst_machine}", dst_machine,
                                   "rsync", status="SKIPPED",
                                   error_msg="tailscale ping fail",
                                   duration_ms=result["duration_ms"])
                    return result
            elif dst_machine == "hulk":
                rc, _, _ = _ssh_exec(dst["ssh_target"], "echo OK", timeout=3)
                if rc != 0:
                    result["warnings"].append(f"hulk SSH 不可用 (rc={rc})")
                    result["duration_ms"] = round((time.time() - t0) * 1000, 1)
                    self._log_sync("FILE", f"{src_machine}→{dst_machine}", dst_machine,
                                   "rsync", status="SKIPPED",
                                   error_msg="ssh fail",
                                   duration_ms=result["duration_ms"])
                    return result

        # 执行 rsync
        rsync_opts = [
            "rsync", "-avz", "--partial",
            "--exclude", ".git/",
            "--exclude", "__pycache__/",
            "--exclude", "*.pyc",
            "--exclude", "database/app.db*",  # DB 单独同步
        ]
        if items:
            # 指定同步特定目录
            rsync_opts.extend(items)
        else:
            # 全量 (除 DB)
            rsync_opts.extend([
                "--exclude", ".syncbak/",
                "--exclude", "ai_engines/.syncbak/",
                "--exclude", "engines/.syncbak/",
            ])
        rsync_opts.extend([src_path, dst_path])

        try:
            proc = subprocess.run(
                rsync_opts, capture_output=True, text=True, timeout=600,
            )
            if proc.returncode == 0:
                result["ok"] = True
                # 解析输出统计
                for line in proc.stderr.split("\n"):
                    if "bytes sent" in line.lower() or "total size" in line.lower():
                        result["warnings"].append(line.strip())
                result["files"] = proc.stderr.count("\n") if proc.stderr else 0
            else:
                result["warnings"].append(f"rsync EC={proc.returncode}: {proc.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            result["warnings"].append("rsync timeout (10min)")
        except Exception as e:
            result["warnings"].append(f"rsync exception: {e}")

        result["duration_ms"] = round((time.time() - t0) * 1000, 1)
        status = "SUCCESS" if result["ok"] else ("PARTIAL" if result["files"] > 0 else "FAIL")
        self._log_sync(
            sync_type="FILE",
            direction=f"{src_machine}→{dst_machine}",
            target=dst_machine,
            item=f"rsync {' '.join(items) if items else 'full'}",
            status=status,
            files_changed=result["files"],
            duration_ms=result["duration_ms"],
            error_msg="; ".join(result["warnings"][:3]) if result["warnings"] else "",
        )
        log.info(f"📤 sync_file {src_machine}→{dst_machine}: ok={result['ok']}, "
                 f"files≈{result['files']}, {result['duration_ms']:.0f}ms")
        return result

    def sync_db(self, src_machine: str = "dev", dst_machine: str = "mini") -> dict:
        """DB 同步 (WAL checkpoint → 传输 → verify)
        默认方向 dev→mini (开发推到边缘)"""
        t0 = time.time()
        result = {"ok": False, "bytes": 0, "duration_ms": 0, "warnings": []}

        # WAL checkpoint (在源端)
        src_db_path = _DB_PATH
        if src_machine == "dev":
            try:
                conn = sqlite3.connect(str(src_db_path))
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.close()
            except Exception as e:
                result["warnings"].append(f"WAL checkpoint fail: {e}")

        # 源端 MD5
        src_md5 = _hash_file(src_db_path)

        if dst_machine == "mini":
            ok, _ = _ping_tailscale(MACHINES["mini"]["ts_ip"])
            if not ok:
                result["warnings"].append("mini 不可达")
                self._log_sync("DB", f"{src_machine}→mini", "mini", "app.db",
                               status="SKIPPED", error_msg="tailscale ping fail",
                               duration_ms=round((time.time()-t0)*1000,1))
                result["duration_ms"] = round((time.time() - t0) * 1000, 1)
                return result
            # rsync DB
            rsync_opts = [
                "rsync", "-avz", "--partial",
                str(src_db_path),
                f"hulk-macmini:{MACHINES['mini']['path']}/flask-app/database/app.db",
            ]
            try:
                proc = subprocess.run(rsync_opts, capture_output=True, text=True, timeout=120)
                result["ok"] = proc.returncode == 0
                result["bytes"] = src_db_path.stat().st_size if src_db_path.exists() else 0
            except Exception as e:
                result["warnings"].append(str(e))

        elif dst_machine == "hulk":
            hulk = MACHINES.get("hulk")
            rc, _, _ = _ssh_exec(hulk["ssh_target"], "echo OK", timeout=3)
            if rc != 0:
                result["warnings"].append("hulk SSH 不可用")
            else:
                rsync_opts = [
                    "rsync", "-avz", "--partial", "-e",
                    "ssh -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=5",
                    str(src_db_path),
                    f"{hulk['ssh_target']}:{hulk['path']}/flask-app/database/app.db",
                ]
                try:
                    proc = subprocess.run(rsync_opts, capture_output=True, text=True, timeout=120)
                    result["ok"] = proc.returncode == 0
                    result["bytes"] = src_db_path.stat().st_size if src_db_path.exists() else 0
                except Exception as e:
                    result["warnings"].append(str(e))
        elif dst_machine == "dev":
            # mini→dev: 从 mini 拉
            ok, _ = _ping_tailscale(MACHINES["mini"]["ts_ip"])
            if not ok:
                result["warnings"].append("mini 不可达")
            else:
                # 先 WAL checkpoint (通过 SSH 在 mini 上)
                _ssh_exec("hulk-macmini",
                          f"python3 -c \"import sqlite3; c=sqlite3.connect('{MACHINES['mini']['path']}/flask-app/database/app.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()\"",
                          timeout=15)
                rsync_opts = [
                    "rsync", "-avz", "--partial",
                    f"hulk-macmini:{MACHINES['mini']['path']}/flask-app/database/app.db",
                    str(src_db_path),
                ]
                try:
                    proc = subprocess.run(rsync_opts, capture_output=True, text=True, timeout=120)
                    result["ok"] = proc.returncode == 0
                    result["bytes"] = src_db_path.stat().st_size if src_db_path.exists() else 0
                except Exception as e:
                    result["warnings"].append(str(e))
        else:
            result["warnings"].append(f"Unknown dst: {dst_machine}")

        result["duration_ms"] = round((time.time() - t0) * 1000, 1)
        status = "SUCCESS" if result["ok"] else "FAIL"
        self._log_sync(
            sync_type="DB",
            direction=f"{src_machine}→{dst_machine}",
            target=dst_machine,
            item="app.db",
            status=status,
            bytes_xfer=result["bytes"],
            duration_ms=result["duration_ms"],
            error_msg="; ".join(result["warnings"][:3]) if result["warnings"] else "",
        )
        log.info(f"💾 sync_db {src_machine}→{dst_machine}: ok={result['ok']}, "
                 f"bytes={result['bytes']}, {result['duration_ms']:.0f}ms")
        return result

    def sync_crontab(self, src_machine: str = "dev", dst_machine: str = "mini") -> dict:
        """crontab 同步"""
        t0 = time.time()
        result = {"ok": False, "warnings": []}
        # 只支持 dev→远端
        if src_machine != "dev":
            result["warnings"].append("Only dev→remote supported")
            return result

        crontab_conf = _RUNTIME / "crontab.mtscos.conf"
        if not crontab_conf.exists():
            result["warnings"].append(f"{crontab_conf} not found")
            return result

        if dst_machine == "mini":
            ok, _ = _ping_tailscale(MACHINES["mini"]["ts_ip"])
            if not ok:
                result["warnings"].append("mini 不可达")
            else:
                # scp 然后 crontab 导入
                rc, _, _ = subprocess.run(
                    ["scp", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
                     str(crontab_conf),
                     f"hulk-macmini:{MACHINES['mini']['path']}/_runtime/crontab.mtscos.conf"],
                    capture_output=True, text=True, timeout=15,
                )
                if rc == 0:
                    rc2, out, err = _ssh_exec(
                        "hulk-macmini",
                        f"crontab {MACHINES['mini']['path']}/_runtime/crontab.mtscos.conf",
                        timeout=10,
                    )
                    result["ok"] = (rc2 == 0)
                    if err:
                        result["warnings"].append(err[:120])
        elif dst_machine == "hulk":
            rc, _, _ = _ssh_exec(MACHINES["hulk"]["ssh_target"], "echo OK", timeout=3)
            if rc != 0:
                result["warnings"].append("hulk SSH 不可用")
            else:
                proc = subprocess.run(
                    ["scp", str(crontab_conf),
                     f"{MACHINES['hulk']['ssh_target']}:{MACHINES['hulk']['path']}/_runtime/crontab.mtscos.conf"],
                    capture_output=True, text=True, timeout=15,
                )
                if proc.returncode == 0:
                    rc2, _, err2 = _ssh_exec(
                        MACHINES["hulk"]["ssh_target"],
                        f"crontab {MACHINES['hulk']['path']}/_runtime/crontab.mtscos.conf",
                        timeout=10,
                    )
                    result["ok"] = (rc2 == 0)

        result["duration_ms"] = round((time.time() - t0) * 1000, 1)
        self._log_sync("CRONTAB", f"{src_machine}→{dst_machine}", dst_machine,
                       "crontab.mtscos.conf",
                       status="SUCCESS" if result["ok"] else "FAIL",
                       duration_ms=result["duration_ms"],
                       error_msg="; ".join(result["warnings"][:3]) if result["warnings"] else "")
        return result

    def sync_all_directions(self) -> dict:
        """完整三机同步 — dev→mini (代码+DB+crontab), mini→dev (DB only)"""
        t0 = time.time()
        result = {
            "connectivity": {},
            "dev→mini": {"file": {}, "db": {}, "crontab": {}},
            "mini→dev": {"db": {}},
            "summary": {"ok": 0, "fail": 0, "skip": 0},
        }
        # 先探测
        conn = self.check_connectivity()
        result["connectivity"] = conn["hosts"]

        # dev→mini 代码
        r = self.sync_file_direction("dev", "mini")
        result["dev→mini"]["file"] = {"ok": r["ok"], "warnings": r["warnings"][:3]}
        # dev→mini DB
        r = self.sync_db("dev", "mini")
        result["dev→mini"]["db"] = {"ok": r["ok"], "warnings": r["warnings"][:3]}
        # dev→mini crontab
        r = self.sync_crontab("dev", "mini")
        result["dev→mini"]["crontab"] = {"ok": r["ok"], "warnings": r["warnings"][:3]}
        # mini→dev DB
        r = self.sync_db("mini", "dev")
        result["mini→dev"]["db"] = {"ok": r["ok"], "warnings": r["warnings"][:3]}

        # dev→hulk (best-effort, hulk 经常离线)
        result["dev→hulk"] = {"file": {}, "db": {}}
        hulk_conn = conn["hosts"].get("hulk", {})
        if hulk_conn.get("ssh"):
            r = self.sync_file_direction("dev", "hulk")
            result["dev→hulk"]["file"] = {"ok": r["ok"], "warnings": r["warnings"][:3]}
            r = self.sync_db("dev", "hulk")
            result["dev→hulk"]["db"] = {"ok": r["ok"], "warnings": r["warnings"][:3]}
        else:
            result["dev→hulk"]["file"] = {"ok": False, "warnings": ["hulk offline, skipped"]}
            result["dev→hulk"]["db"] = {"ok": False, "warnings": ["hulk offline, skipped"]}
            result["summary"]["skip"] += 2

        result["duration_ms"] = round((time.time() - t0) * 1000, 1)
        self._log_sync("FULL_SYNC", "chain", "all", "3-machine",
                       status="SUCCESS", duration_ms=result["duration_ms"])
        log.info(f"🔗 sync_all_directions 完成 in {result['duration_ms']:.0f}ms")
        return result

    def conflict_resolve(self, file_path: str, v1_ts: float, v2_ts: float) -> str:
        """冲突解决: 时间戳优先"""
        if v1_ts > v2_ts:
            return "v1_wins"
        elif v2_ts > v1_ts:
            return "v2_wins"
        return "equal"

    def rollback_point(self, subdir: str = "manual") -> str:
        """创建回滚点 (hardlink)"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = _BACKUP_DIR / subdir / ts
        dst.mkdir(parents=True, exist_ok=True)
        count = 0
        for p in _STATIC_CSS.glob("*.css"):
            try:
                shutil.copy2(p, dst / p.name)
                count += 1
            except Exception:
                pass
        for p in (_RUNTIME / "cron_entry.sh", _RUNTIME / "crontab.mtscos.conf"):
            if p.exists():
                try:
                    shutil.copy2(p, dst / p.name)
                    count += 1
                except Exception:
                    pass
        if _DB_PATH.exists():
            try:
                shutil.copy2(_DB_PATH, dst / "app.db")
                count += 1
            except Exception:
                pass
        log.info(f"📸 rollback_point: {dst} ({count} files)")
        self._log_sync("ROLLBACK", "local", "backup", str(dst),
                       status="SUCCESS", files_changed=count,
                       backup_path=str(dst))
        return str(dst)

    # ═════════════════════════════════════════════════════════════════════════
    #  ║  MAIN ENTRY
    # ═════════════════════════════════════════════════════════════════════════

    def run_all(self) -> dict:
        """一键完整同步: themes → languages → machines"""
        t0 = time.time()
        return {
            "themes": self.sync_themes(),
            "languages": self.sync_languages(),
            "machines": self.sync_all_directions(),
            "total_duration_ms": round((time.time() - t0) * 1000, 1),
        }

    def run_sync_loop(self, interval: int = 300):
        """5 分钟心跳: themes + languages(每日) + machines(按需)"""
        log.info(f"SyncCenter 心跳循环启动 interval={interval}s")
        daily_done_day = None
        while True:
            try:
                now = datetime.now()
                log.info(f"=== heartbeat {now.strftime('%H:%M:%S')} ===")
                # 每心跳: 主题
                self.sync_themes()
                # 每天 02:00 做一次完整语言同步 (Ollama 翻译耗资源)
                if now.hour == 2 and (daily_done_day != now.date()):
                    self.sync_languages()
                    daily_done_day = now.date()
                # 每 3 个心跳做一次三机同步
                if (now.minute // 15) % 3 == 0:
                    self.sync_all_directions()
            except KeyboardInterrupt:
                log.info("Ctrl+C, 退出")
                break
            except Exception as e:
                log.error(f"heartbeat error: {e}")
            time.sleep(interval)


# ═══════════════════════════════════════════════════════════════════════════════
#  🚀 CLI 入口
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Usage:
      python3 engines/sync_center.py --action themes|languages|machines|all|report|rollback|heartbeat
    """
    import argparse
    parser = argparse.ArgumentParser(description="MTSCOS Sync Center")
    parser.add_argument("--action", default="all",
                        choices=["themes", "languages", "machines", "all", "report",
                                 "rollback", "heartbeat", "connectivity", "db_sync"])
    parser.add_argument("--db", default=None, help="DB path override")
    parser.add_argument("--interval", type=int, default=300, help="heartbeat interval (s)")
    args = parser.parse_args()

    sc = SyncCenter(args.db)
    a = args.action

    if a == "themes":
        print(json.dumps(sc.sync_themes(), indent=2, ensure_ascii=False))
    elif a == "languages":
        print(json.dumps(sc.sync_languages(), indent=2, ensure_ascii=False))
    elif a == "machines":
        print(json.dumps(sc.sync_all_directions(), indent=2, ensure_ascii=False))
    elif a == "connectivity":
        print(json.dumps(sc.check_connectivity(), indent=2, ensure_ascii=False))
    elif a == "db_sync":
        print(json.dumps(sc.sync_db(), indent=2, ensure_ascii=False))
    elif a == "report":
        print(sc.generate_theme_report())
    elif a == "rollback":
        print(sc.rollback_point())
    elif a == "heartbeat":
        sc.run_sync_loop(args.interval)
    elif a == "all":
        print(json.dumps(sc.run_all(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
