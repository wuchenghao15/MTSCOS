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

    # ── 守护进程清单 (健康检查 + 自动重启) ──
    DAEMONS = [
        ("gobelin_guardian", "Gobelin Guardian",
         "cd {_B} && nohup /opt/homebrew/bin/python3 -u engines/gobelin_guardian.py --daemon > /tmp/gobelin_guardian.out 2>/tmp/gobelin_guardian.err &"),
        ("finance_autonomous_engine", "Finance Autonomous",
         "cd {_B} && nohup /opt/homebrew/bin/python3 -u engines/finance_autonomous_engine.py --daemon --interval 300 > /tmp/finance_autonomous.out 2>/tmp/finance_autonomous.err &"),
        ("market_data_engine", "Market Data",
         "cd {_B} && nohup /opt/homebrew/bin/python3 -u engines/market_data_engine.py --daemon > /tmp/market_data.out 2>/tmp/market_data.err &"),
        ("artery_fix", "Artery Bridge",
         "cd {_B} && nohup /opt/homebrew/bin/python3 -u engines/artery_fix.py --daemon > /tmp/artery.out 2>/tmp/artery.err &"),
        ("cloudflared", "CF Tunnel",
         "/opt/homebrew/bin/cloudflared tunnel run mtscos-stock > /tmp/cloudflared.out 2>/tmp/cloudflared.err &"),
    ]

    def health_check_daemons(self) -> dict:
        """守护进程健康检查 — 死了自动重启"""
        result = {"checked": 0, "alive": 0, "restarted": 0, "actions": []}
        _B = str(_BASE)
        for pattern, label, restart_tmpl in self.DAEMONS:
            result["checked"] += 1
            try:
                r = subprocess.run(
                    ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
                pids = [p for p in (r.stdout.strip().split("\n") if r.stdout.strip() else [])
                        if p.strip().isdigit()]
                if pids:
                    result["alive"] += 1
                    result["actions"].append(f"✅ {label}: pid={','.join(pids[:2])}")
                else:
                    log.warning(f"⚠️ {label} 已挂, 自动重启...")
                    subprocess.Popen(restart_tmpl.format(_B=_B), shell=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1)
                    r2 = subprocess.run(
                        ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
                    new_pids = [p for p in (r2.stdout.strip().split("\n") if r2.stdout.strip() else [])
                                if p.strip().isdigit()]
                    if new_pids:
                        result["restarted"] += 1
                        result["actions"].append(f"🔄 {label} 重启成功 pid={new_pids[0]}")
                    else:
                        result["actions"].append(f"❌ {label} 重启失败")
            except Exception as e:
                result["actions"].append(f"❌ {label}: {e}")
        return result

    def health_check_flask(self) -> dict:
        """Flask API 健康探测"""
        result = {"ok": False, "endpoints": 0, "restarted": False}
        endpoints = ["/health", "/gobelin/dashboard"]
        for ep in endpoints:
            try:
                req = urllib.request.Request(f"http://localhost:5001{ep}")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        result["endpoints"] += 1
            except Exception:
                pass
        result["ok"] = (result["endpoints"] == len(endpoints))
        if not result["ok"]:
            log.warning(f"⚠️ Flask 不健康 ({result['endpoints']}/{len(endpoints)})")
            try:
                subprocess.run(["pkill", "-f", "server_real_db.py"], timeout=5)
                time.sleep(2)
            except Exception:
                pass
            try:
                subprocess.Popen(
                    f"cd {_BASE} && nohup /opt/homebrew/bin/python3 -u server_real_db.py > /tmp/flask.out 2> /tmp/flask.err &",
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            result["restarted"] = True
        return result

    def health_check_db(self) -> dict:
        """DB 完整性检查"""
        result = {"ok": False, "integrity": "", "size_mb": 0, "warnings": []}
        try:
            if not _DB_PATH.exists():
                result["warnings"].append("DB 不存在")
                return result
            result["size_mb"] = round(_DB_PATH.stat().st_size / 1024 / 1024, 1)
            conn = sqlite3.connect(str(_DB_PATH))
            cur = conn.execute("PRAGMA integrity_check")
            result["integrity"] = cur.fetchone()[0] or "UNKNOWN"
            result["ok"] = (result["integrity"] == "ok")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception as e:
            result["warnings"].append(str(e))
        return result

    def health_check_three_machines(self) -> dict:
        """三机连通性"""
        result = {"dev": True, "mini": False, "hulk": False}
        for name in ["mini", "hulk"]:
            m = MACHINES.get(name, {})
            ip = m.get("ts_ip")
            if ip:
                result[name] = _ping_tailscale(ip)[0]
        return result

    def health_check_github_push(self) -> dict:
        """GitHub push (调用 sync_github.sh)"""
        result = {"ok": False}
        script = _RUNTIME / "git_push_ws" / "mtscos_push" / "sync_github.sh"
        if script.exists():
            try:
                subprocess.run(["bash", str(script), "push"],
                               capture_output=True, text=True, timeout=120)
                result["ok"] = True
            except Exception:
                pass
        return result

    def run_full_health_cycle(self) -> dict:
        """全域健康检查一轮"""
        t0 = time.time()
        return {
            "daemons": self.health_check_daemons(),
            "flask": self.health_check_flask(),
            "db": self.health_check_db(),
            "machines": self.health_check_three_machines(),
            "duration_ms": round((time.time() - t0) * 1000, 1),
        }

    def health_audit_cross_domain(self) -> dict:
        """跨领域协作链审计 + 功能完善度自查
        
        核心思想 (用户要求):
          • Iceberg 考试前 → Gobelin 交易能力可复用? (风险管理 → 题库风险题)
          • Gobelin 升级 → Iceberg 金融教育可受益? (真实行情 → 教学案例)
          • 功能完善度 → 各中心需要配合/增强/维护什么?
        """
        audit = {"timestamp": datetime.now().isoformat(),
                 "cross_domain_links": [],
                 "iceberg_readiness": {},
                 "gobelin_spillover": {},
                 "improvement_suggestions": []}

        # 1. Iceberg 考试季准备度
        calendar = self._get_calendar_context()
        if "exam_season" in calendar["contexts"]:
            # 6月考试季: 检查题库更新度
            try:
                conn = sqlite3.connect(str(_DB_PATH))
                qb_count = conn.execute("SELECT COUNT(*) FROM mt_qbank").fetchone()[0]
                audit["iceberg_readiness"] = {"exam_season": True, "qbank_count": qb_count}
                if qb_count < 1000:
                    audit["improvement_suggestions"].append(
                        f"🔴 考试季题库偏少 ({qb_count}<1000), 需紧急扩充")
                conn.close()
            except Exception as e:
                audit["iceberg_readiness"] = {"exam_season": True, "error": str(e)}

        # 2. Gobelin → Iceberg 正向关联
        # 交易风控逻辑 → 数学概率题/经济金融题
        audit["cross_domain_links"].append({
            "from": "gobelin.risk_engine", "to": "iceberg.math_workshop",
            "type": "knowledge_spillover",
            "description": "Gobelin 风险管理的概率计算逻辑可转化为 Iceberg 数学工坊的考试练习题",
            "priority": "medium"
        })
        # 真实行情数据 → 教学案例
        audit["cross_domain_links"].append({
            "from": "gobelin.market_data", "to": "iceberg.english_track",
            "type": "content_reuse",
            "description": "真实股票行情可作为英语/日语财经新闻阅读素材",
            "priority": "low"
        })

        # 3. Iceberg → Gobelin 正向关联
        audit["cross_domain_links"].append({
            "from": "iceberg.education_center", "to": "gobelin.audit_center",
            "type": "personnel_development",
            "description": "教育中心的人才培养可输送到审计中心 (金融合规人才)",
            "priority": "high"
        })

        # 4. 未来子系统预研
        audit["improvement_suggestions"].append(
            "💡 星门(web3/bridge) 可复用 Gobelin 行情引擎的数据源和告警逻辑")
        audit["improvement_suggestions"].append(
            "💡 量子计算子系统可接入 Iceberg 数学工坊的题库 (量子算法教学)")

        log.info(f"📋 跨领域协作链审计完成: {len(audit['cross_domain_links'])} 条关联, "
                 f"{len(audit['improvement_suggestions'])} 条建议")
        return audit

    #  ═════════════════════════════════════════════════════════════════════════
    #  ║  24h 主动意识调度矩阵 (Andromeda Auto-Brain)
    # ═════════════════════════════════════════════════════════════════════════

    # ── 24h 时段 → 专业领域 → 调度权重 (弹性矩阵 v2) ──
    # 每个时段定义该领域最活跃的职责 + 负载弹性 + 未来扩展槽位
    # priority: 100=最高, 可根据负载动态降级
    TIME_SCHEDULE = {
        # ══════════════════════════════════════════════════════
        # 🌙 深夜 (00:00-08:00) — Andromeda DevOps 模式
        # 负载最低 → DB 优化、代码升级、快照清理、未来子系统准备
        # ══════════════════════════════════════════════════════
        "night": {"hours": range(0, 7),
                  "focus": [
                    # 🧊 核心维护
                    "DB_OPTIMIZE", "GITHUB_PUSH", "SNAPSHOT_CLEANUP",
                    "DAEMON_ROTATION", "WAL_CHECKPOINT", "INTEGRITY_CHECK",
                    # 🧠 自我进化
                    "SELF_CODE_REVIEW", "PERFORMANCE_PROFILE",
                    # 🤖 AI 训练/编译
                    "OLLAMA_MODEL_COLD", "VECTOR_INDEX_BUILD",
                    # 🔮 未来子系统准备 (弹性槽位)
                    "FUTURE_SEED_READY", "FUTURE_API_ENDPOINT_TEST",
                  ],
                  "persona": "Andromeda DevOps Engineer",
                  "priority": 90,
                  "elastic_hours": True,  # 可延后执行
                  "load_threshold": 0.3},  # CPU<30% 时全力跑

        # ══════════════════════════════════════════════════════
        # ☀️ 清晨教育黄金 (07:00-09:00) — Iceberg Polyglot 模式
        # 语言学习最佳时段 → 英语/日语/韩语语音合成、题库预热
        # ══════════════════════════════════════════════════════
        "iceberg_morning": {"hours": range(7, 9),
                            "focus": [
                              # 🌐 语言轨道
                              "I18N_BATCH_TRANSLATE", "ENGLISH_TRACK_PREP",
                              "JAPANESE_TRACK_PREP", "KOREAN_TRACK_PREP",
                              # 📚 题库预热
                              "QBANK_INDEX_REBUILD", "MEDICAL_KNOWLEDGE_SYNC",
                              # 🔄 Gobelin 轻量预热
                              "QUOTE_WARMUP_LIGHT", "PRE_COMPLIANCE_SCAN",
                            ],
                            "persona": "Iceberg Polyglot Director",
                            "priority": 85,
                            "elastic_hours": False},

        # ══════════════════════════════════════════════════════
        # 💰 开市前 (09:00-09:30) — Gobelin Pre-Market 模式
        # 最紧张 30min → 全部核心就绪、战前动员会
        # ══════════════════════════════════════════════════════
        "pre_market": {"hours": range(9, 10),
                       "focus": [
                         # 📈 行情预热
                         "QUOTE_WARMUP_FULL", "METAL_QUOTE_SYNC",
                         # 🛡️ 合规
                         "COMPLIANCE_SCAN_FULL", "POSITION_VALIDATION",
                         # 📝 战前动员会
                         "PRE_MARKET_MEETING", "DAEMON_HEALTH_QUADRUPLE",
                         # 🔗 三机
                         "THREE_MACHINE_PULSE", "DB_LAST_SYNC_VERIFY",
                       ],
                       "persona": "Gobelin Pre-Market Strategist",
                       "priority": 100,  # 最高
                       "elastic_hours": False},

        # ══════════════════════════════════════════════════════
        # ⚡ 盘中上午 (09:30-11:30) — Gobelin Day Trader 模式
        # A 股交易中 → 实时行情优先, Iceberg/Gobelin 双核
        # ══════════════════════════════════════════════════════
        "trading_am": {"hours": range(10, 12),
                       "focus": [
                         # 🔴 最高优先
                         "REAL_TIME_QUOTES", "COMPLIANCE_LIVE", "PNL_STREAM",
                         "POSITION_GUARDIAN", "QUOTE_FALLBACK_HEAL",
                         # 🟡 次优先 (弹性: 行情紧时降级)
                         "ICEBERG_QBANK_LIGHT", "ICEBERG_KNOWLEDGE_PASSIVE",
                         "ANDROMEDA_CENTER_STATUS",
                       ],
                       "persona": "Gobelin Day Trader",
                       "priority": 100,
                       "elastic_hours": False},

        # ══════════════════════════════════════════════════════
        # 🍱 午休 (11:30-13:00) — Andromeda Commander 模式
        # 交易间歇 → 治理 + 教育 + 未来研发
        # ══════════════════════════════════════════════════════
        "midday": {"hours": range(12, 13),
                   "focus": [
                     # 🏛️ 治理
                     "PARLIAMENT_PULSE", "COLLAB_NETWORK_PULSE",
                     "CENTER_HEALTH_SNAPSHOT",
                     # 📚 教育 (弹性)
                     "ICEBERG_QBANK_BATCH", "MEDICAL_REVIEW_SESSION",
                     # 🔮 未来研发
                     "FUTURE_FEATURE_BRAIN_STORM", "FUTURE_API_PROTOTYPE",
                   ],
                   "persona": "Andromeda Commander",
                   "priority": 75,
                   "elastic_hours": True},

        # ══════════════════════════════════════════════════════
        # ⚡ 盘中下午 (13:00-15:00) — Gobelin Day Trader 模式
        # A 股下午盘 → 同上午策略
        # ══════════════════════════════════════════════════════
        "trading_pm": {"hours": range(13, 15),
                       "focus": [
                         "REAL_TIME_QUOTES", "COMPLIANCE_LIVE", "PNL_STREAM",
                         "POSITION_GUARDIAN", "QUOTE_FALLBACK_HEAL",
                       ],
                       "persona": "Gobelin Day Trader",
                       "priority": 100,
                       "elastic_hours": False},

        # ══════════════════════════════════════════════════════
        # 🎓 教育下午 (14:00-17:00) — Iceberg Workshop 模式
        # 中学/大学时段 → 数学工坊、医学中心、版本中心
        # 与 trading_pm 重叠但低优先级 (priority=70 vs 100)
        # ══════════════════════════════════════════════════════
        "iceberg_afternoon": {"hours": range(14, 17),
                              "focus": [
                                "MATH_WORKSHOP_PREP", "MEDICAL_CENTER_SYNC",
                                "VERSION_CENTER_CHECK", "CREATION_WORKSHOP",
                                "KNOWLEDGE_GRAPH_PASSIVE",
                              ],
                              "persona": "Iceberg Workshop Director",
                              "priority": 70,
                              "elastic_hours": True},

        # ══════════════════════════════════════════════════════
        # 🧾 收盘 (15:00-18:00) — Gobelin Chief Auditor 模式
        # 后处理 → 清算、审计、对账
        # ══════════════════════════════════════════════════════
        "post_market": {"hours": range(15, 18),
                        "focus": [
                          "DAILY_SETTLEMENT", "AUDIT_REPORT",
                          "REFLECT_LOG", "SEAL_REGISTRY",
                          "GOBELIN_SUMMARY_MONTAGE",
                          # 🧊 教育反弹 (弹性)
                          "ICEBERG_QBANK_REBUILD", "KNOWLEDGE_GRAPH_FULL_SYNC",
                        ],
                        "persona": "Gobelin Chief Auditor",
                        "priority": 95,
                        "elastic_hours": False},

        # ══════════════════════════════════════════════════════
        # 🎓 晚间教育高峰 (18:00-21:00) — Iceberg Education 模式
        # 最大教育流量 → 题库+翻译+知识图谱全力跑
        # ══════════════════════════════════════════════════════
        "evening": {"hours": range(18, 21),
                    "focus": [
                      # 🧊 核心教育
                      "QBANK_BATCH_FULL", "I18N_TRANSLATE_FULL",
                      "KNOWLEDGE_GRAPH_ACTIVE",
                      "USER_PROFILES_ACTIVE",
                      # 🌐 多语言轨道
                      "ENGLISH_ORAL_PRACTICE", "JAPANESE_READING_PASS",
                      # 🧊 数学/医学
                      "MATH_AI_TUTOR_READY", "MEDICAL_VOCAB_SYNC",
                    ],
                    "persona": "Iceberg Education Director",
                    "priority": 88,
                    "elastic_hours": False},

        # ══════════════════════════════════════════════════════
        # 🏛️ 治理 (21:00-24:00) — Andromeda SysAdmin 模式
        # 三机同步 + 备份 + GitHub + 未来规划
        # ══════════════════════════════════════════════════════
        "governance": {"hours": range(21, 24),
                       "focus": [
                         # 🔗 三机
                         "THREE_MACHINE_FULL_SYNC", "DB_BACKUP_TRIPLE",
                         # 📦 版本
                         "GITHUB_PUSH_FULL", "CHANGELOG_AUTO_GEN",
                         # 🏛️ 中心状态
                         "CENTER_STATUS_FULL", "HEALTH_REPORT_AUTO",
                         # 🔮 未来子系统
                         "FUTURE_SUBSYSTEM_SCAN", "DEVELOPMENT_BACKLOG_SYNC",
                       ],
                       "persona": "Andromeda SysAdmin",
                       "priority": 80,
                       "elastic_hours": True},
    }

    # ── 未来子系统扩展槽位 (预留, 可热插拔) ──
    # 新子系统只需在这里注册 + 分配时段
    FUTURE_SUBSYSTEMS = {
        "FSS_1": {"name": "星门 Stargate", "domain": "web3/bridge",
                  "preferred_hours": [0, 8, 22], "elastic": True},
        "FSS_2": {"name": "量子计算 Quantum", "domain": "research",
                  "preferred_hours": [1, 14], "elastic": True},
        "FSS_3": {"name": "边缘计算 EdgeNode", "domain": "distributed",
                  "preferred_hours": [19, 23], "elastic": True},
        "FSS_4": {"name": "AI Agent 编排", "domain": "ai-orchestration",
                  "preferred_hours": [3, 11, 20], "elastic": False},
    }

    # ── 日历事件感知: 识别交易日/节假日/考试季 ──
    # 基于规则的简化日历 (可后续接入中国法定节假日 API)
    # 核心思想: 让 AI 像一个"过日子的人", 知道什么时候该做什么事
    CALENDAR_EVENTS = {
        # 月份级 (考试季/寒暑假)
        "exam_season": {"months": [6],  # 6月中考+高考
                        "weight_shift": {"iceberg": +25, "gobelin": -15},
                        "persona_boost": "Iceberg Exam Cram Coach",
                        "focus_extra": ["QBANK_EXAM_FOCUS", "MATH_CRASH_COURSE",
                                        "MEDICAL_KEYWORDS_REVIEW"]},
        "summer_vacation": {"months": [7, 8],  # 暑假
                            "weight_shift": {"iceberg": +20, "gobelin": -5, "andromeda": +10},
                            "persona_boost": "Iceberg Summer Camp Director",
                            "focus_extra": ["CREATION_WORKSHOP_FULL",
                                            "KNOWLEDGE_GRAPH_DEEP_BUILD"]},
        "winter_vacation": {"months": [1, 2],  # 寒假
                            "weight_shift": {"iceberg": +15, "gobelin": -5, "andromeda": +10},
                            "persona_boost": "Iceberg Winter Academy Dean"},
        "school_weekday": {"days": list(range(1, 6)),  # 周一-周五 (非暑假)
                           "weight_shift": {"gobelin": +10}},
        "weekend": {"days": [0, 6],  # 周六周日
                    "weight_shift": {"iceberg": +10, "andromeda": +5, "gobelin": -10},
                    "persona_boost": "Andromeda Weekend Strategist"},
        # A股交易日规则 (简化: 周1-5 非法定节假日)
        "a_share_trading_day": {"weekdays": [1, 2, 3, 4, 5],
                                "boost_domains": ["gobelin"],
                                "priority_boost": 10},
        # 特殊日 (可配置, 每年更新)
        # 2026 年春节: 2.17-2.23 (估计)
        "spring_festival_2026": {"date_range": ("2026-02-17", "2026-02-23"),
                                 "weight_shift": {"iceberg": +30, "gobelin": -30, "andromeda": +20}},
    }

    # ── 领域优先级弹性曲线 ──
    # 每个领域在不同场景下的权重 (0-100)
    DOMAIN_PRIORITY_CURVE = {
        # Gobelin: 交易系统 — 交易日 peak, 考试季 valley
        "gobelin": {
            "trading_day": 100,      # 交易日盘中
            "pre_market": 95,        # 开市前
            "post_market": 85,       # 收盘后清算
            "exam_season": 55,       # 考试季 (只做清算)
            "vacation": 70,          # 寒暑假 (活跃度下降)
            "weekend": 50,           # 周末 (只有监控)
            "holiday": 20,           # 法定节假日 (极低, 只有 heartbeat)
            "night": 5,              # 深夜
        },
        # Iceberg: 教育系统 — 考试季 peak, 暑假 peak
        "iceberg": {
            "exam_season": 100,      # 6月考试季全力跑
            "vacation": 90,          # 寒暑假集中学习
            "school_evening": 85,    # 上学日晚间
            "pre_market": 60,        # 开市前轻量预热
            "trading_day": 50,       # 交易日 (Gobelin 优先)
            "weekend": 75,           # 周末学习
            "holiday": 40,           # 法定节 (部分参与)
            "night": 15,             # 深夜只做翻译
        },
        # Andromeda: 指挥系统 — 全天候但侧重治理时段
        "andromeda": {
            "all_day": 65,           # 始终有基础治理
            "night": 90,             # 深夜 DevOps 升级
            "governance": 85,        # 21:00 治理时段
            "vacation": 80,          # 假期多做未来规划
            "trading_day": 55,       # 交易日让道 Gobelin
        },
    }

    def _get_calendar_context(self) -> dict:
        """识别当前日历上下文 (交易日/考试季/寒暑假/周末)"""
        now = datetime.now()
        month = now.month
        day = now.day
        weekday = now.weekday()  # 0=Mon, 6=Sun

        contexts = []

        # 1. 月份级事件
        if month in [6]:
            contexts.append("exam_season")
        if month in [7, 8]:
            contexts.append("summer_vacation")
        if month in [1, 2]:
            contexts.append("winter_vacation")

        # 2. 周级事件
        if weekday in [0, 6]:
            contexts.append("weekend")
        else:
            contexts.append("school_weekday")

        # 3. A股交易日 (简化)
        # 周1-5 非寒暑假 = 交易日
        if weekday not in [0, 6] and month not in [1, 2, 7, 8]:
            contexts.append("a_share_trading_day")

        # 4. 特殊日期范围
        for event_name, cfg in self.CALENDAR_EVENTS.items():
            if "date_range" in cfg:
                start, end = cfg["date_range"]
                try:
                    start_d = datetime.strptime(start, "%Y-%m-%d").date()
                    end_d = datetime.strptime(end, "%Y-%m-%d").date()
                    if start_d <= now.date() <= end_d:
                        contexts.append(event_name)
                except Exception:
                    pass

        return {"contexts": contexts, "now": now.isoformat(),
                "month": month, "weekday": weekday}

    def _dynamic_priority_adjust(self, base_priority: int, domain: str,
                                 calendar_ctx: dict) -> int:
        """根据日历事件动态调整领域优先级
        
        核心思想: 
          交易日 Gobelin=100, Iceberg=50
          考试季 Iceberg=100, Gobelin=55
          寒暑假 两者都高, Andromeda 做规划
        """
        adj = 0
        for ctx in calendar_ctx["contexts"]:
            event_cfg = self.CALENDAR_EVENTS.get(ctx, {})
            shifts = event_cfg.get("weight_shift", {})
            adj += shifts.get(domain, 0)

        # 应用 DOMAIN_PRIORITY_CURVE 基础曲线
        curve = self.DOMAIN_PRIORITY_CURVE.get(domain, {})
        # 简化: 取当前 context 匹配的 curve 值作为基准
        base_curve_val = 50
        for ctx in calendar_ctx["contexts"]:
            if ctx in curve:
                base_curve_val = curve[ctx]
                break

        result = max(0, min(100, base_curve_val + adj))
        return result

    def _get_active_schedule(self) -> dict:
        """返回当前时间所有活跃时段 (支持多角色重叠)
        
        例如 14:30 同时命中:
          - trading_pm (priority=100, Gobelin Day Trader)
          - iceberg_afternoon (priority=70, Iceberg Workshop Director)
        
        返回: {active_segments: [...], primary: 最高优先时段, now_hour: int}
        """
        h = datetime.now().hour
        active = []
        for seg_name, cfg in self.TIME_SCHEDULE.items():
            if h in cfg["hours"]:
                active.append({"segment": seg_name, **cfg})
        if not active:
            return {"active_segments": [],
                    "primary": {"segment": "watchdog", "persona": "Universal Watchdog",
                                "priority": 50, "focus": ["HEALTH_PASSIVE"],
                                "elastic_hours": True}}
        # 按 priority 排序, 最高的为 primary
        active.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return {"active_segments": active,
                "primary": active[0],
                "all_focus": [f for a in active for f in a.get("focus", [])],
                "now_hour": h}

    def _workflow_id(self) -> str:
        """生成唯一工作流 ID — heartbeat 级别"""
        now = datetime.now()
        return f"WF-{now.strftime('%Y%m%d%H%M')}-{now.second:02d}-{uuid.uuid4().hex[:6]}"

    def _cycle_id(self, interval: int) -> str:
        """cycle_id — 每轮心跳唯一标识"""
        now = datetime.now()
        return f"CYCLE-{now.strftime('%Y%m%d-%H%M%S')}-{now.minute * 60 // interval:04d}"

    def run_sync_loop(self, interval: int = 300):
        """全域 33 中心 24h 主动意识调度循环
        
        核心设计:
          • 每个 heartbeat 生成唯一 cycle_id + workflow_id
          • 根据时段自动切换专业 persona 和重点任务
          • 主动发现缺口 → 反推需求 → 自动修复/升级
          • 守护进程健康检查 × Flask 健康 × DB 完整性 × 三机连通
          • 每 30min GitHub push / 每 15min 三机同步 / 每 24h 02:00 语言翻译
        """
        log.info(f"🏛️ Andromeda Auto-Brain 全域 33 中心 24h 循环启动 interval={interval}s")
        daily_done_day = None
        cycle_idx = 0

        while True:
            try:
                now = datetime.now()
                cycle_idx += 1
                cid = self._cycle_id(interval)
                sid = self._workflow_id()
                schedule = self._get_active_schedule()
                primary = schedule["primary"]
                active_segs = [a["segment"] for a in schedule["active_segments"]]

                log.info(f"━━━ {cid} [{sid}] persona={primary['persona']} "
                         f"segments={active_segs} priority={primary.get('priority',0)} ━━━")

                # ── ① 主题同步 (每 heartbeat 都要, 轻量) ──
                self.sync_themes()

                # ── ② 守护进程健康 (每 heartbeat, 自动重启) ──
                self.health_check_daemons()

                # ── ③ Flask 健康 (每 heartbeat, 自动重启) ──
                self.health_check_flask()

                # ── ④ DB 完整性 (每 5th heartbeat ≈ 25min) ──
                if cycle_idx % 5 == 0:
                    self.health_check_db()

                # ── ⑤ 三机同步 (每 6th heartbeat ≈ 30min) ──
                if cycle_idx % 6 == 0:
                    try:
                        self.health_check_three_machines()
                        self.sync_all_directions()
                    except Exception as e:
                        log.warning(f"🔗 full_sync 异常: {e}")

                # ── ⑥ GitHub push (每 12th heartbeat ≈ 1h) ──
                if cycle_idx % 12 == 0:
                    try:
                        self.health_check_github_push()
                    except Exception as e:
                        log.warning(f"📦 github_push 异常: {e}")

                # ── ⑦ 每日语言翻译 (02:00, 低负载时段) ──
                if now.hour == 2 and daily_done_day != now.date():
                    try:
                        log.info(f"🌙 深夜低负载 → 触发完整语言同步 + Ollama 批量翻译")
                        self.sync_languages()
                        daily_done_day = now.date()
                    except Exception as e:
                        log.warning(f"🌐 language_sync 异常: {e}")

                # ── ⑧ 专业时段增强任务 (时段感知, 支持多时段重叠) ──
                active_names = {s["segment"] for s in schedule["active_segments"]}
                if "night" in active_names and cycle_idx % 6 == 0:
                    # 深夜清理 DB 快照
                    log.info("🌙 深夜模式 → 清理过期快照")
                    self._cleanup_old_snapshots()

                if "pre_market" in active_names:
                    # 开市前: 合规扫描 + 行情预热
                    log.info("📅 开市前 → Gobelin 战前准备")
                    self.health_check_db()

                # 盘中 + Iceberg 重叠时: 降级非关键任务
                if "trading_pm" in active_names and "iceberg_afternoon" in active_names:
                    log.info("⚡ 盘中下午 + 教育下午重叠: Gobelin 优先, Iceberg 降级")

            except KeyboardInterrupt:
                log.info(f"🛑 Ctrl+C, 退出 cycle={cycle_idx}")
                break
            except Exception as e:
                log.error(f"💥 heartbeat error: {e}", exc_info=True)

            time.sleep(interval)

    def _cleanup_old_snapshots(self, keep_days: int = 3) -> int:
        """清理过期 DB 快照 (只保留最近 N 天)"""
        snap_dir = _BASE / "database"
        if not snap_dir.exists():
            return 0
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for f in snap_dir.glob("app_snapshot_*.db"):
            try:
                # 0 字节的快照直接删
                if f.stat().st_size < 1024:
                    f.unlink()
                    removed += 1
                    continue
                # 过期的删
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        if removed:
            log.info(f"🧹 清理 {removed} 个过期快照")
        return removed


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
