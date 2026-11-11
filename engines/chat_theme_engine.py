# -*- coding: utf-8 -*-
"""
聊天主题引擎 — 用户指令驱动个性化主题 (TOOLCHAT-003, flow_chat_theme_20261030)

闭环: 用户对聊天说"换成粉色" → set_theme 工具创建/绑定主题 → 按用户标签持久化
      → 该用户下次登录前端拉取 /api/user-theme 注入 CSS 变量 → 看到粉色
      → 其他用户无偏好记录 → 默认白色, 完全隔离无感知

存储: mt_user_preferences(user_id, pref_key, pref_value) — best-effort 建表, 锁竞争静默
主题: THEME_PRESETS 内置预设 + create_theme 动态创建(聊天提案), CSS 变量集对齐 local_chat.html :root
"""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = PROJECT_ROOT / "database" / "app.db"

# 内置预设 — 变量名对齐 local_chat.html :root
THEME_PRESETS = {
    "pink": {
        "label": "粉色", "--mtscos-primary": "#ec4899", "--mtscos-primary-soft": "#fdf2f8",
        "--mtscos-primary-ink": "#db2777", "--mtscos-accent": "#f472b6",
        "--bg": "#fdf2f8", "--surface": "#ffffff", "--surface-hover": "#fce7f3",
        "--panel": "#fff5fa", "--text": "#4a1130", "--text-secondary": "#9d6278",
        "--border": "#fbcfe8",
    },
    "dark": {
        "label": "深色", "--mtscos-primary": "#22d3ee", "--mtscos-primary-soft": "#164e63",
        "--mtscos-primary-ink": "#67e8f9", "--mtscos-accent": "#a78bfa",
        "--bg": "#0f172a", "--surface": "#1e293b", "--surface-hover": "#334155",
        "--panel": "#1e293b", "--text": "#e2e8f0", "--text-secondary": "#94a3b8",
        "--border": "#334155",
    },
    "ocean": {
        "label": "海洋", "--mtscos-primary": "#0ea5e9", "--mtscos-primary-soft": "#e0f2fe",
        "--mtscos-primary-ink": "#0369a1", "--mtscos-accent": "#14b8a6",
        "--bg": "#f0f9ff", "--surface": "#ffffff", "--surface-hover": "#e0f2fe",
        "--panel": "#f8fcff", "--text": "#0c4a6e", "--text-secondary": "#64748b",
        "--border": "#bae6fd",
    },
    "green": {
        "label": "绿色", "--mtscos-primary": "#10b981", "--mtscos-primary-soft": "#ecfdf5",
        "--mtscos-primary-ink": "#059669", "--mtscos-accent": "#84cc16",
        "--bg": "#f0fdf4", "--surface": "#ffffff", "--surface-hover": "#dcfce7",
        "--panel": "#f7fef9", "--text": "#14532d", "--text-secondary": "#6b7f6e",
        "--border": "#bbf7d0",
    },
    "sepia": {
        "label": "护眼米黄", "--mtscos-primary": "#b45309", "--mtscos-primary-soft": "#fef3c7",
        "--mtscos-primary-ink": "#92400e", "--mtscos-accent": "#d97706",
        "--bg": "#fdf6e3", "--surface": "#fffbeb", "--surface-hover": "#fde68a",
        "--panel": "#fdfaf0", "--text": "#44403c", "--text-secondary": "#78716c",
        "--border": "#e7d8b8",
    },
}


def _conn(timeout: int = 6):
    conn = sqlite3.connect(str(DB), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_user_preferences(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, pref_key TEXT NOT NULL, pref_value TEXT,
            updated_at TEXT, UNIQUE(user_id, pref_key))""")
    except Exception:
        pass
    return conn


# ────────────────── 主题 CRUD ──────────────────

def create_theme(name: str, css_vars: dict, user_id: str = "") -> dict:
    """动态创建主题 (聊天提案): 存入 preferences 系统区 (user_id='__themes__')"""
    name = (name or "").strip().lower().replace(" ", "_")[:30]
    if not name or not isinstance(css_vars, dict) or not css_vars:
        return {"ok": False, "error": "主题名或变量为空"}
    if not all(str(k).startswith("--") for k in css_vars.keys()):
        bad = [k for k in css_vars if not str(k).startswith("--")][:3]
        return {"ok": False, "error": f"CSS 变量必须以 -- 开头: {bad}"}
    try:
        conn = _conn()
        conn.execute("""INSERT INTO mt_user_preferences(user_id,pref_key,pref_value,updated_at)
                        VALUES('__themes__', ?, ?, datetime('now','localtime'))
                        ON CONFLICT(user_id,pref_key) DO UPDATE SET pref_value=excluded.pref_value,
                        updated_at=datetime('now','localtime')""",
                     (f"theme_{name}", json.dumps(css_vars, ensure_ascii=False)))
        conn.commit()
        conn.close()
        return {"ok": True, "theme": name, "message": f"主题 [{name}] 已创建 (基于提案)"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def _resolve_theme(name: str):
    """预设优先, 回退查动态主题库"""
    if name in THEME_PRESETS:
        return dict(THEME_PRESETS[name])
    try:
        conn = _conn()
        row = conn.execute("SELECT pref_value FROM mt_user_preferences WHERE user_id='__themes__' AND pref_key=?",
                           (f"theme_{name}",)).fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def _canonical_theme(name: str):
    """把用户输入(中/英文/别名)规范化为预设或动态主题的 canonical 名"""
    name = (name or "").strip().lower().replace(" ", "_")
    if name in THEME_PRESETS:
        return name
    alias = {"粉": "pink", "桃": "pink", "深": "dark", "夜": "dark", "暗": "dark",
             "海": "ocean", "蓝": "ocean", "绿": "green", "米": "sepia", "护眼": "sepia",
             "黄": "sepia"}
    for zh, en in alias.items():
        if zh in name and en in THEME_PRESETS:
            return en
    return name  # 动态主题名原样返回


def set_user_theme(user_id: str, theme: str) -> dict:
    """绑定用户主题 — 按用户标签存储, 完全隔离"""
    user_id = (user_id or "").strip()
    raw = (theme or "").strip()
    theme = _canonical_theme(raw)
    if not user_id or user_id == "guest":
        return {"ok": False, "error": "需要登录后才能个性化主题"}
    vars_ = _resolve_theme(theme)
    if not vars_:
        # 未知主题名 → 按颜色名自动生成 (用户说'要紫色'/'橙色'之类)
        guess = _synthesize_theme(raw) or _synthesize_theme(theme)
        if not guess:
            return {"ok": False, "error": f"未知主题 '{raw}', 可用: {', '.join(THEME_PRESETS)} 或描述颜色让我创建"}
        create_theme(theme, guess, user_id)
        vars_ = guess
    try:
        conn = _conn()
        conn.execute("""INSERT INTO mt_user_preferences(user_id,pref_key,pref_value,updated_at)
                        VALUES(?,?,?,datetime('now','localtime'))
                        ON CONFLICT(user_id,pref_key) DO UPDATE SET pref_value=excluded.pref_value,
                        updated_at=datetime('now','localtime')""", (user_id, "theme", theme))
        conn.commit()
        conn.close()
        return {"ok": True, "theme": theme, "label": vars_.get("label", theme),
                "message": f"你的主题已设为 [{vars_.get('label', theme)}], 下次登录自动生效"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def get_user_theme(user_id: str) -> dict:
    """读取用户主题 (无记录 → 默认白, ok=False 表示用默认)"""
    try:
        conn = _conn()
        row = conn.execute("SELECT pref_value FROM mt_user_preferences WHERE user_id=? AND pref_key='theme'",
                           ((user_id or "").strip(),)).fetchone()
        conn.close()
        if row and row[0]:
            vars_ = _resolve_theme(row[0])
            if vars_:
                return {"ok": True, "theme": row[0], "css_vars": vars_}
    except Exception:
        pass
    return {"ok": False, "theme": "default", "css_vars": {}}


def reset_user_theme(user_id: str) -> dict:
    """恢复默认白色"""
    try:
        conn = _conn()
        conn.execute("DELETE FROM mt_user_preferences WHERE user_id=? AND pref_key='theme'", ((user_id or "").strip(),))
        conn.commit()
        conn.close()
        return {"ok": True, "message": "已恢复默认白色主题"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def _synthesize_theme(name: str):
    """按颜色关键词合成主题 (聊天提案的'临时主题'); 中文颜色名先映射内置预设"""
    alias = {"粉": "pink", "桃": "pink", "深": "dark", "夜": "dark", "暗": "dark",
             "海": "ocean", "蓝": "ocean", "绿": "green", "米": "sepia", "护眼": "sepia",
             "黄": "sepia", "橙": "orange", "紫": "purple", "红": "red", "青": "cyan"}
    for zh, en in alias.items():
        if zh in name and en in THEME_PRESETS:
            return dict(THEME_PRESETS[en])
    colors = {
        "橙": ("#f97316", "#fff7ed", "#ea580c"),
        "红": ("#ef4444", "#fef2f2", "#dc2626"),
        "紫": ("#8b5cf6", "#f5f3ff", "#7c3aed"),
        "青": ("#06b6d4", "#ecfeff", "#0891b2"),
        "black": ("#64748b", "#f1f5f9", "#475569"), "gray": ("#64748b", "#f1f5f9", "#475569"),
    }
    for kw, (primary, soft, ink) in colors.items():
        if kw in name:
            return {
                "label": name, "--mtscos-primary": primary, "--mtscos-primary-soft": soft,
                "--mtscos-primary-ink": ink, "--mtscos-accent": primary,
                "--bg": soft, "--surface": "#ffffff", "--surface-hover": soft,
                "--panel": "#ffffff", "--text": "#1e293b", "--text-secondary": "#64748b",
                "--border": primary + "44",
            }
    return None


def render_theme_css(user_id: str) -> str:
    """渲染该用户的 CSS 覆盖片段 (无偏好 → 空串=默认白)"""
    r = get_user_theme(user_id)
    if not r.get("ok"):
        return ""
    lines = [":root{"]
    for k, v in r["css_vars"].items():
        if k.startswith("--") and isinstance(v, str):
            lines.append(f"{k}:{v};")
    lines.append("}")
    return "".join(lines)


# ────────────────── 聊天工具注册 (set_theme/get_theme/reset_theme) ──────────────────

def tool_set_theme(theme: str = "") -> dict:
    """聊天工具: 换主题 (user_id 从 _tool_ctx 注入)"""
    return set_user_theme(_tool_ctx.get("user_id", ""), theme)


def tool_get_theme() -> dict:
    uid = _tool_ctx.get("user_id", "")
    r = get_user_theme(uid)
    if r.get("ok"):
        return {"ok": True, "theme": r["theme"], "message": f"当前主题: {r['theme']}"}
    return {"ok": True, "theme": "default", "message": "当前默认白色主题 (未个性化)"}


def tool_reset_theme() -> dict:
    return reset_user_theme(_tool_ctx.get("user_id", ""))


# 简易上下文: 聊天路由在调用 run_tool_loop 前设置 user_id
_tool_ctx = {}


def set_tool_context(user_id: str, session_id: str = ""):
    _tool_ctx.clear()
    _tool_ctx.update({"user_id": user_id, "session_id": session_id})


THEME_TOOLS = {
    "set_theme": (tool_set_theme, "更换用户主题(按用户持久化,只影响本人)。参数: theme(主题名或颜色,如 pink/粉色/紫色)"),
    "get_theme": (tool_get_theme, "查询当前用户主题。参数: 无"),
    "reset_theme": (tool_reset_theme, "恢复默认白色主题。参数: 无"),
}

THEME_INTENT = r"换(个)?主题|更换主题|主题.*(粉|深|暗|紫|橙|绿|蓝|红|黄|青|米|色)|改成.*(色|主题)|界面.*(色|主题)|夜间模式|深色模式|护眼"


def detect_theme_intent(text: str) -> bool:
    import re
    return bool(text and re.search(THEME_INTENT, text, re.I))


if __name__ == "__main__":
    print("[chat_theme] self-test")
    print(" preset:", len(THEME_PRESETS))
    print(" set:", set_user_theme("selftest_u1", "粉色")["ok"])
    print(" get:", get_user_theme("selftest_u1")["theme"])
    print(" other user default:", get_user_theme("selftest_u2")["ok"] is False)
    print(" css:", render_theme_css("selftest_u1")[:60])
    print(" reset:", reset_user_theme("selftest_u1")["ok"])
    print(" intent:", detect_theme_intent("帮我把主题换成粉色的"))
