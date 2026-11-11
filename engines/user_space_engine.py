# -*- coding: utf-8 -*-
"""
用户数据空间 + 泛化指令路由引擎 (TOOLCHAT-004, flow_user_space_20261030)

═══ 架构 ═══
1. 用户数据空间 (完全隔离):
   _runtime/user_spaces/{user_id}/
     preferences.json   偏好 (主题/参数/组别等所有修改记录)
     context.json       上下文摘要 (登录载入)
     files/             用户修改产生的文件副本
   user_id 白名单字符 [A-Za-z0-9_.-], 防路径穿越

2. 泛化动作路由 route_user_action(user_id, action, params):
   意图分类: theme / password / profile / group / params / file / unknown
   安全分级闸门:
     low    (主题/偏好/参数)     → 直接执行 + 记录 + 大厅备案
     medium (组别/资料)          → 执行 + 大厅备案 + 权限校验
     high   (密码/敏感字段)      → 不直接改! 生成审批单入厅, 审批后生效
   约束: 字段黑名单 / 值校验 / 权限抓取(mt_ai_employees 只读) / 大厅审批流(19中心支撑)

3. 登录载入 load_session_context(user_id):
   偏好 + CSS主题 + 最近动作历史 + 上下文摘要 → 前端一次性拉取
"""
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SPACES_ROOT = PROJECT_ROOT / "_runtime" / "user_spaces"
DB = PROJECT_ROOT / "database" / "app.db"

_UID_RE = re.compile(r"^[A-Za-z0-9_\.\-]{1,64}$")

# ──────────────── 字段约束 (泛化修改的规则规范) ────────────────
FIELD_RULES = {
    # key: (安全等级, 校验器, 说明)
    "theme":          ("low", lambda v: bool(str(v).strip()), "界面主题"),
    "nickname":       ("low", lambda v: 1 <= len(str(v)) <= 30, "昵称"),
    "language":       ("low", lambda v: str(v) in ("zh", "en", "ja"), "语言"),
    "notify_enabled": ("low", lambda v: isinstance(v, bool) or str(v) in ("0", "1", "true", "false"), "通知开关"),
    "daily_limit":    ("medium", lambda v: str(v).isdigit() and 0 <= int(v) <= 100000, "每日额度"),
    "group":          ("medium", lambda v: re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff\-]{1,20}", str(v)), "组别"),
    "department":     ("medium", lambda v: 1 <= len(str(v)) <= 20, "部门"),
    "role":           ("high", lambda v: str(v) in ("user", "admin", "sa"), "角色(需审批)"),
    "password":       ("high", lambda v: isinstance(v, str) and len(v) >= 6, "密码(需审批)"),
}
_DENY_KEYS = {"user_id", "is_admin", "balance", "token_wallet", "api_key", "secret", "salt"}  # 绝不放行


def space_path(user_id: str) -> Path:
    """用户数据空间路径 (白名单防穿越)"""
    uid = (user_id or "").strip()
    if not _UID_RE.fullmatch(uid):
        raise ValueError(f"非法 user_id: {uid!r}")
    p = SPACES_ROOT / uid
    p.mkdir(parents=True, exist_ok=True)
    (p / "files").mkdir(exist_ok=True)
    return p


# ──────────────── 偏好/上下文读写 (JSON 文件, 天然隔离) ────────────────

def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _write_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def save_pref(user_id: str, key: str, value, action: str = "", level: str = "low") -> dict:
    """保存偏好到用户专属文件夹 + 记动作历史"""
    try:
        sp = space_path(user_id)
        prefs = _read_json(sp / "preferences.json", {})
        prefs[key] = {"value": value, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      "via": action or "direct"}
        _write_json(sp / "preferences.json", prefs)
        hist = _read_json(sp / "context.json", {}).get("history", [])
        hist.insert(0, {"ts": datetime.now().strftime("%m-%d %H:%M"), "key": key,
                        "value": str(value)[:60], "level": level})
        _write_json(sp / "context.json", {"history": hist[:50]})
        return {"ok": True}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:150]}


def get_prefs(user_id: str) -> dict:
    try:
        return _read_json(space_path(user_id) / "preferences.json", {})
    except Exception:
        return {}


# ──────────────── 大厅备案 (19 中心支撑) ────────────────

def _hall_file_action(user_id: str, action: str, key: str, value: str, level: str) -> str:
    """修改动作大厅备案 ( best-effort )"""
    try:
        conn = sqlite3.connect(str(DB), timeout=8)
        conn.execute("PRAGMA busy_timeout=6000")
        code = f"UA-{datetime.now().strftime('%y%m%d%H%M%S')}-{abs(hash(user_id)) % 900 + 100}"
        conn.execute("""INSERT INTO mt_lab_task_hall(hall_code, title, description, status,
                        approval_status, source, created_at) VALUES(?,?,?,?, 'PENDING', ?, datetime('now','localtime'))""",
                     (code, f"[用户动作] {user_id} 修改 {key} ({level})",
                      f"action={action} key={key} value={str(value)[:100]} via=chat_tool",
                      "USER_ACTION"))
        conn.commit()
        conn.close()
        return code
    except Exception:
        return ""


def _check_permission(user_id: str) -> dict:
    """权限抓取: 用户存在于用户体系 (只读检查)"""
    try:
        conn = sqlite3.connect(str(DB), timeout=8)
        conn.execute("PRAGMA busy_timeout=6000")
        row = conn.execute("SELECT COUNT(*) FROM users WHERE user_id=? OR username=?",
                           (user_id, user_id)).fetchone()
        conn.close()
        return {"ok": True, "known_user": bool(row and row[0])}
    except Exception:
        pass
    return {"ok": True, "known_user": False}  # 未知用户也放行 low 动作, 空间隔离本身是安全边界


# ──────────────── 泛化动作路由 (核心闸门) ────────────────

def route_user_action(user_id: str, key: str, value, action: str = "modify_setting") -> dict:
    """
    泛化修改入口: 任意'改X'指令统一走这里
    规则: 黑名单拒绝 → 字段规则校验 → 安全分级 → 执行/审批 → 记录 → 大厅备案
    """
    uid = (user_id or "").strip()
    if not uid or uid == "guest":
        return {"ok": False, "error": "需要登录"}
    key = (key or "").strip().lower()
    if key in _DENY_KEYS:
        return {"ok": False, "error": f"字段 '{key}' 受保护, 禁止通过聊天修改"}
    rule = FIELD_RULES.get(key)
    level = rule[0] if rule else ("low" if key.startswith("ui_") or key.startswith("pref_") else "medium")
    if rule and not rule[1](value):
        return {"ok": False, "error": f"'{rule[2]}' 值校验失败: {str(value)[:40]}"}

    perm = _check_permission(uid)
    # 仅 medium (直接执行类) 要求已注册; high 不直接改任何东西, 审批单生成放行
    # (未注册用户改密码/初始化密码是合法场景, 身份校验在审批环节完成)
    if not perm.get("known_user") and level == "medium":
        return {"ok": False, "error": "未识别的用户, 修改组别/部门/额度需先完成注册"}

    # ── high: 生成审批单, 不直接改 ──
    if level == "high":
        code = _hall_file_action(uid, action, key, "***" if key == "password" else value, "high")
        return {"ok": True, "level": "high", "pending_approval": True,
                "approval_code": code,
                "message": f"'{key}' 属敏感修改, 已生成审批单 {code or '(大厅)'} , 审批通过后生效"}

    # ── low/medium: 直接执行 ──
    # theme 走主题引擎 (复用 TOOLCHAT-003)
    if key == "theme":
        from engines.chat_theme_engine import set_user_theme
        r = set_user_theme(uid, str(value))
        if not r.get("ok"):
            return r
        save_pref(uid, "theme", r.get("label") or value, action, "low")
        return {"ok": True, "level": "low", "applied": True, "message": r.get("message")}

    r = save_pref(uid, key, value, action, level)
    if not r.get("ok"):
        return r
    code = _hall_file_action(uid, action, key, value, level) if level == "medium" else ""
    return {"ok": True, "level": level, "applied": True,
            "hall_code": code or None,
            "message": f"'{key}' 已更新并保存到你的数据空间" + (f", 大厅备案 {code}" if code else "")}


def save_user_file(user_id: str, filename: str, content: str) -> dict:
    """用户修改产生的文件 → 存进用户专属 files/"""
    fn = (filename or "").strip()
    if not _UID_RE.fullmatch(user_id or "") or not re.fullmatch(r"[\w.\-\u4e00-\u9fff]{1,60}", fn):
        return {"ok": False, "error": "非法 user_id 或文件名"}
    try:
        p = space_path(user_id) / "files" / fn
        if p.suffix == ".py":
            compile(content, fn, "exec")
        p.write_text(content)
        return {"ok": True, "path": f"user_spaces/{user_id}/files/{fn}"}
    except SyntaxError as ex:
        return {"ok": False, "error": f".py 语法错误: line {ex.lineno}"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:150]}


# ──────────────── 登录载入 (全量上下文包) ────────────────

def load_session_context(user_id: str) -> dict:
    """登录后一次性载入: 偏好 + 主题CSS + 动作历史 + 聊天上下文摘要"""
    uid = (user_id or "").strip()
    out = {"ok": True, "user_id": uid, "theme": "default", "css": "",
           "preferences": {}, "history": [], "chat_digest": ""}
    if not _UID_RE.fullmatch(uid):
        return out
    try:
        from engines.chat_theme_engine import get_user_theme, render_theme_css
        th = get_user_theme(uid)
        out.update({"theme": th.get("theme", "default"),
                    "css": render_theme_css(uid)})
    except Exception:
        pass
    try:
        sp = space_path(uid)
        prefs = _read_json(sp / "preferences.json", {})
        out["preferences"] = {k: v.get("value") for k, v in prefs.items()}
        out["history"] = _read_json(sp / "context.json", {}).get("history", [])[:10]
        # 最近聊天摘要 (chat_sessions 只读)
        try:
            conn = sqlite3.connect(str(DB), timeout=8)
            conn.execute("PRAGMA busy_timeout=6000")
            row = conn.execute("""SELECT c.session_id, COUNT(m.id) FROM chat_sessions c
                                  LEFT JOIN chat_messages m ON m.session_id=c.session_id
                                  WHERE c.user_id=? GROUP BY c.session_id
                                  ORDER BY c.updated_at DESC LIMIT 1""", (uid,)).fetchone()
            conn.close()
            if row:
                out["chat_digest"] = f"最近会话 {row[0][:8]}… 共 {row[1]} 条消息"
        except Exception:
            pass
    except Exception:
        pass
    return out


# ──────────────── 聊天工具 ────────────────

def tool_modify_setting(key: str = "", value="") -> dict:
    from engines.chat_theme_engine import _tool_ctx  # 同一上下文注入点 (run_tool_loop 已设置 user_id)
    return route_user_action(_tool_ctx.get("user_id", ""), key, value)


def tool_get_my_context() -> dict:
    from engines.chat_theme_engine import _tool_ctx
    r = load_session_context(_tool_ctx.get("user_id", ""))
    return {"ok": True, "theme": r.get("theme"), "preferences": r.get("preferences"),
            "recent_changes": [h["key"] + "=" + h["value"] for h in r.get("history", [])[:5]],
            "chat_digest": r.get("chat_digest")}


USER_ACTION_TOOLS = {
    "modify_setting": (tool_modify_setting,
                       "泛化修改设置(昵称/语言/额度/组别/部门/主题等; 密码角色走审批)。参数: key(字段名), value(新值)"),
    "get_my_context": (tool_get_my_context, "查询我的全部设置/最近修改/聊天上下文。参数: 无"),
}


if __name__ == "__main__":
    print("[user_space] self-test")
    print(" theme:", route_user_action("selftest_u1", "theme", "粉色")["ok"])
    print(" nickname:", route_user_action("selftest_u1", "nickname", "小明")["ok"])
    print(" deny:", route_user_action("selftest_u1", "api_key", "hack")["ok"] is False)
    print(" password->approval:", route_user_action("selftest_u1", "password", "abc12345").get("pending_approval"))
    print(" file:", save_user_file("selftest_u1", "note.md", "# hi")["ok"])
    ctx = load_session_context("selftest_u1")
    print(" load:", ctx["theme"], list(ctx["preferences"]), len(ctx["history"]))
    print(" other isolated:", get_prefs("other_u") == {})
