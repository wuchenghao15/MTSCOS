# -*- coding: utf-8 -*-
"""MTSCOS 工程冒烟测试集 (CHATOPS-002 #2) — 聊天工具链/引擎核心纯函数
run: python3 -m pytest tests/ -q   (聊天内: run_tests 工具直接跑)"""
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "engines"))

import chat_toolbox as tb


# ── 路径安全 ──

def test_safe_path_rejects_escape():
    assert tb._safe_path("../outside.py") is None
    assert tb._safe_path("") is None
    assert tb._safe_path(None) is None
    # 绝对路径被映射进项目内伪路径 (不逃逸, 但文件不存在 → 读工具自然拒绝)
    p = tb._safe_path("/etc/passwd")
    assert p is None or (p and str(p).startswith(str(tb.PROJECT_ROOT)))


def test_safe_path_rejects_sensitive():
    for p in ("database/app.db", ".env", "certs/server.key", "secrets.py"):
        assert tb._safe_path(p) is None, p


def test_safe_path_accepts_inbound():
    assert (tb.PROJECT_ROOT / "engines" / "chat_toolbox.py") == tb._safe_path("engines/chat_toolbox.py")


# ── git 写守卫 (#1) ──

def test_git_guard_rejects_bulk_add():
    assert tb._git_write_guard("git add -A")
    assert tb._git_write_guard("git add .")
    assert tb._git_write_guard("git add --all")


def test_git_guard_rejects_sensitive_and_escape():
    assert tb._git_write_guard("git add database/app.db")
    assert tb._git_write_guard("git add ../evil.py")


def test_git_guard_allows_file_add():
    assert tb._git_write_guard("git add engines/chat_toolbox.py") is None


def test_git_guard_commit_needs_toolchat_prefix():
    assert tb._git_write_guard('git commit -m "随便写"')
    assert tb._git_write_guard("git commit")            # 无 message
    assert tb._git_write_guard('git commit -a -m "TOOLCHAT: x"')   # 禁 -a
    assert tb._git_write_guard('git commit --amend -m "TOOLCHAT: x"') is not None
    assert tb._git_write_guard('git commit -m "TOOLCHAT: 修复白名单校验"') is None


def test_git_guard_rejects_push_reset():
    assert tb._git_write_guard("git push origin main")
    assert tb._git_write_guard("git reset --hard")
    assert tb._git_write_guard("git checkout -- .")


# ── check_html (#4) ──

def test_check_html_balanced():
    ok = tb.check_html("templates/local_chat.html")
    assert ok.get("ok") is True, ok.get("errors", ok)


def test_check_html_detects_unbalanced():
    bad = tb.PROJECT_ROOT / "_runtime" / "_tb_bad.html"
    bad.write_text("<div><span></div>", encoding="utf-8")
    try:
        r = tb.check_html("_runtime/_tb_bad.html")
        assert r["ok"] is False and r["error_count"] >= 1
    finally:
        bad.unlink(missing_ok=True)


def test_check_html_rejects_escape():
    assert tb.check_html("../x.html").get("ok") is False


# ── check_js (#4) ──

def test_check_js_syntax():
    js = tb.PROJECT_ROOT / "_runtime" / "_tb_ok.js"
    js.write_text("function add(a,b){return a+b}\nadd(1,2)", encoding="utf-8")
    try:
        assert tb.check_js("_runtime/_tb_ok.js")["ok"] is True
    finally:
        js.unlink(missing_ok=True)


def test_check_js_detects_syntax_error():
    js = tb.PROJECT_ROOT / "_runtime" / "_tb_bad.js"
    js.write_text("function ( {", encoding="utf-8")
    try:
        r = tb.check_js("_runtime/_tb_bad.js")
        assert r["ok"] is False
    finally:
        js.unlink(missing_ok=True)


# ── safe_exec 白名单 ──

def test_safe_exec_denies_dangerous():
    for cmd in ("rm -rf /", "sudo x", "curl http://evil.com", "git push origin main",
                "git reset --hard", "pip install requests"):
        r = tb.safe_exec(cmd)
        assert r["ok"] is False, cmd


def test_safe_exec_allows_readonly():
    r = tb.safe_exec("git log --oneline -1")
    assert r["ok"] is True and r["exit_code"] == 0


# ── doc_sync 版本快照 ──

def test_doc_sync_version_snapshot():
    import doc_sync_engine as ds
    r = ds.sync_version()
    assert r["sections"] >= 3          # 当前版本/注册/升级 至少三段
    assert (ds.VER).exists()


# ── 用户空间引擎 ──

def test_user_space_blacklist():
    import user_space_engine as us
    for field in ("api_key", "balance", "user_id", "token_wallet"):
        assert field in us._DENY_KEYS, field
