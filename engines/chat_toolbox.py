# -*- coding: utf-8 -*-
"""
聊天工具箱 — 聊天即开发 (TOOLCHAT-001, flow_chat_toolbox_20261030)

给聊天通道接入沙箱工具层, 使聊天具备真实开发能力:
  查代码 (safe_grep) → 读文件 (safe_read_file) → 改代码 (safe_write_file)
  → 验证 (py_compile) → 跑测试 (run_tests) → 汇报

安全设计:
  - 路径白名单: 只能操作 PROJECT_ROOT (flask-app/) 内文件, 禁 .db/.env/密钥
  - 命令白名单: safe_exec 只放行 pytest/py_compile/git 只读/ollama list/ls
  - 写保护: 写前自动备份 → 写后 py_compile 验证 → 失败自动回滚
  - 审计: 每次调用写 chat_tool_calls 表 (best-effort, 锁竞争时静默跳过)

tool-use 协议: qwen2.5 原生 <tool_call> 文本协议 (无需 Ollama tools API)
  模型输出 <tool_call>{"name":..., "arguments":{...}}</tool_call>
  → Flask 执行 → <tool_result> 回填 → 循环 ≤ TOOL_MAX_ROUNDS 轮
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent      # flask-app/
BACKUP_DIR = PROJECT_ROOT / "_runtime" / "backups" / "chat_tools"
AUDIT_DB = PROJECT_ROOT / "database" / "app.db"

TOOL_MAX_ROUNDS = 6
MAX_READ_LINES = 2000
MAX_OUTPUT_CHARS = 8000
EXEC_TIMEOUT = 20
GREP_TIMEOUT = 15

_READ_DENY = re.compile(r"\.db$|\.db-|\.db\.|\.env$|secret|password|credential|\.pem$|\.key$", re.I)
_EXEC_WHITELIST = [
    r"^pytest(\s|$)", r"^python3?\s+-m\s+py_compile\b", r"^python3?\s+-m\s+pytest\b",
    r"^git\s+status$", r"^git\s+diff\b", r"^git\s+log\b", r"^git\s+show\b",
    r"^ollama\s+list$", r"^ls\b", r"^node\s+--check\b",
]

def _git_write_guard(cmd: str):
    """git 写操作守卫 (TOOLCHAT 固化版本用): 逐参数校验, 不走白名单正则
    返回 None=放行, str=拒绝原因"""
    parts = cmd.split()
    sub = parts[1] if len(parts) > 1 else ""
    if sub == "add":
        # 只允许 flask-app 内相对路径, 禁 .db/.env/secret; 显式禁 -A/-A./. (全量暂存)
        for a in parts[2:]:
            if a in ("-A", "-A.", ".", "./", "-u", "--all"):
                return f"git add 拒绝全量暂存参数 '{a}' (必须逐文件)"
            if a.startswith("-"):
                continue
            if _READ_DENY.search(a):
                return f"git add 拒绝敏感文件: {a}"
            if _safe_path(a) is None:
                return f"git add 拒绝越界路径: {a}"
        return None
    if sub == "commit":
        # 必须 -m "TOOLCHAT: ..." 且禁 -a/--amend/--no-verify
        if re.search(r"\s(-a|--amend|--no-verify)\b", cmd):
            return "git commit 拒绝 -a/--amend/--no-verify"
        m = re.search(r'-m\s+"(TOOLCHAT:[^"]{5,150})"', cmd)
        if not m:
            return 'git commit 必须 -m "TOOLCHAT: 说明" (5-150字符)'
        return None
    return f"git {sub} 不在受控写操作集 (仅 add/commit)"

# ────────────────────────── 路径安全 ──────────────────────────

def _safe_path(rel: str):
    """把相对路径解析到 PROJECT_ROOT 内, 越界/危险文件返回 None"""
    if not rel or not isinstance(rel, str):
        return None
    rel = rel.strip().lstrip("/")
    if _READ_DENY.search(rel):
        return None
    p = (PROJECT_ROOT / rel).resolve()
    try:
        p.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None
    return p


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[截断, 原始 {len(text)} 字符]"


# ────────────────────────── 审计 ──────────────────────────

def _audit(tool: str, args: dict, summary: str, ok: bool,
           session_id: str = "", user_id: str = "", ms: int = 0):
    """best-effort 审计: 锁竞争时静默跳过, 不影响聊天主链路"""
    try:
        conn = sqlite3.connect(str(AUDIT_DB), timeout=5)
        conn.execute("PRAGMA busy_timeout=4000")
        conn.execute("""CREATE TABLE IF NOT EXISTS chat_tool_calls(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, user_id TEXT, tool TEXT, args_json TEXT,
            ok INTEGER, result_summary TEXT, duration_ms INTEGER, created_at TEXT)""")
        conn.execute(
            "INSERT INTO chat_tool_calls(session_id,user_id,tool,args_json,ok,result_summary,duration_ms,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (session_id, str(user_id), tool, json.dumps(args, ensure_ascii=False)[:500],
             1 if ok else 0, str(summary)[:300], ms,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ────────────────────────── 六大工具 ──────────────────────────

def safe_read_file(path: str, start: int = 1, end: int = None) -> dict:
    """读文件 (行号区间可选), 白名单内, ≤2000 行"""
    t0 = time.time()
    p = _safe_path(path)
    if not p or not p.is_file():
        _audit("safe_read_file", {"path": path}, "not_found_or_denied", False)
        return {"ok": False, "error": f"文件不存在或被禁止读取: {path}"}
    try:
        lines = p.read_text(errors="replace").splitlines()
        s = max(1, int(start or 1))
        e = min(len(lines), int(end or s + MAX_READ_LINES - 1))
        if e - s + 1 > MAX_READ_LINES:
            e = s + MAX_READ_LINES - 1
        body = "\n".join(f"{i+1}\t{lines[i]}" for i in range(s - 1, e))
        out = {"ok": True, "path": path, "total_lines": len(lines),
               "content": _clip(body or "(空文件)")}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("safe_read_file", {"path": path, "start": start}, f"lines {s}-{e}", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def safe_list_dir(path: str = ".") -> dict:
    """列目录 (白名单内), 返回名称+大小+类型"""
    t0 = time.time()
    p = _safe_path(path)
    if not p or not p.is_dir():
        _audit("safe_list_dir", {"path": path}, "not_found_or_denied", False)
        return {"ok": False, "error": f"目录不存在或被禁止: {path}"}
    try:
        items = []
        for child in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:200]:
            try:
                sz = child.stat().st_size if child.is_file() else None
            except Exception:
                sz = None
            items.append({"name": child.name, "dir": child.is_dir(), "size": sz})
        out = {"ok": True, "path": path, "items": items}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("safe_list_dir", {"path": path}, f"{len(items)} items", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def safe_grep(pattern: str, glob: str = "*.py", path: str = ".") -> dict:
    """精确搜索 (rg 优先, 回退 grep), 15s 超时"""
    t0 = time.time()
    base = _safe_path(path)
    if not base or not pattern or not isinstance(pattern, str) or len(pattern) > 200:
        _audit("safe_grep", {"pattern": pattern}, "denied", False)
        return {"ok": False, "error": "路径被禁止或 pattern 非法 (≤200 字符)"}
    if not re.fullmatch(r"[\w*.\-]+", glob or ""):
        glob = "*.py"
    try:
        r = None
        try:
            r = subprocess.run(["rg", "-n", "--no-heading", "-g", glob, "-m", "50", "-e", pattern, "."],
                               cwd=str(base), capture_output=True, text=True, timeout=GREP_TIMEOUT)
        except (FileNotFoundError, OSError):
            r = None  # rg 未安装 → 回退 grep
        if r is None or r.returncode not in (0, 1):
            r = subprocess.run(["grep", "-rn", "--include=" + glob, "-m", "50", "-E", pattern, "."],
                               cwd=str(base), capture_output=True, text=True, timeout=GREP_TIMEOUT)
        hits = [l for l in (r.stdout or "").splitlines() if l.strip()][:100]
        out = {"ok": True, "pattern": pattern, "path": path, "count": len(hits),
               "hits": _clip("\n".join(hits) or "(无匹配)")}
    except subprocess.TimeoutExpired:
        out = {"ok": False, "error": f"搜索超时 (>{GREP_TIMEOUT}s), 请缩小范围"}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("safe_grep", {"pattern": pattern, "glob": glob}, f"{out.get('count', 0)} hits", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def safe_write_file(path: str, content: str) -> dict:
    """写文件: 备份 → 写入 → .py 自动 py_compile 验证 → 失败回滚"""
    t0 = time.time()
    p = _safe_path(path)
    if not p:
        _audit("safe_write_file", {"path": path}, "denied", False)
        return {"ok": False, "error": f"路径被禁止 (仅限 {PROJECT_ROOT.name}/ 内, 禁 .db/.env/密钥)"}
    if not isinstance(content, str) or not content.strip():
        return {"ok": False, "error": "content 为空"}
    if len(content) > 300_000:
        return {"ok": False, "error": f"内容过大 ({len(content)} 字符, 上限 30 万)"}
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        existed = p.exists()
        if existed:
            (BACKUP_DIR / f"{p.name}.{stamp}.bak").write_text(p.read_text(errors="replace"))
            p.write_text(content)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        # .py 语法验证, 失败回滚
        if p.suffix == ".py":
            chk = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                                 capture_output=True, text=True, timeout=15)
            if chk.returncode != 0:
                if existed:
                    p.write_text((BACKUP_DIR / f"{p.name}.{stamp}.bak").read_text())
                    err = f"py_compile 失败已回滚: {chk.stderr[:300]}"
                else:
                    p.unlink()
                    err = f"py_compile 失败已删除新文件: {chk.stderr[:300]}"
                _audit("safe_write_file", {"path": path}, err, False, ms=int((time.time() - t0) * 1000))
                return {"ok": False, "error": err}
        out = {"ok": True, "path": path, "bytes": len(content.encode()),
               "action": "updated" if existed else "created",
               "backup": f"_runtime/backups/chat_tools/{p.name}.{stamp}.bak" if existed else None,
               "message": "写入成功, .py 已通过语法验证" if p.suffix == ".py" else "写入成功"}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("safe_write_file", {"path": path}, out.get("message") or out.get("error", ""), out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def safe_exec(cmd: str) -> dict:
    """命令执行 (白名单 + 20s 超时): pytest / py_compile / git 只读 / ollama list / ls"""
    t0 = time.time()
    cmd = (cmd or "").strip()
    if not cmd or len(cmd) > 300:
        return {"ok": False, "error": "命令为空或超长 (≤300 字符)"}
    if not any(re.match(rx, cmd) for rx in _EXEC_WHITELIST):
        # git 受控写操作: 走专用守卫 (逐参数校验, 独立于白名单)
        if cmd.startswith("git "):
            deny = _git_write_guard(cmd)
            if deny:
                _audit("safe_exec", {"cmd": cmd}, f"git_guard_denied: {deny}", False)
                return {"ok": False, "error": f"[git守卫] {deny}"}
            _audit("safe_exec", {"cmd": cmd}, "git_write_guarded", True)
        else:
            _audit("safe_exec", {"cmd": cmd}, "whitelist_denied", False)
            return {"ok": False, "error": "命令不在白名单 (允许: pytest / python -m py_compile / git status|diff|log|show / git add|commit(受控守卫) / ollama list / ls / node --check)"}
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT),
                           capture_output=True, text=True, timeout=EXEC_TIMEOUT)
        out_text = ((r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr.strip() else "")).strip()
        out = {"ok": True, "cmd": cmd, "exit_code": r.returncode,
               "output": _clip(out_text or "(无输出)")}
    except subprocess.TimeoutExpired:
        out = {"ok": False, "error": f"命令超时 (>{EXEC_TIMEOUT}s)"}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("safe_exec", {"cmd": cmd}, f"exit={out.get('exit_code', '?')}", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def check_html(path: str) -> dict:
    """HTML 模板结构校验 (html.parser 标签配对/嵌套平衡), 编译能力覆盖 HTML"""
    t0 = time.time()
    p = _safe_path(path)
    if not p or not p.is_file():
        return {"ok": False, "error": f"文件不存在或越界: {path}"}
    from html.parser import HTMLParser

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}
    class Balance(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack, self.errors = [], []
        def handle_starttag(self, tag, attrs):
            if tag not in VOID:
                self.stack.append((tag, self.getpos()[0]))
        def handle_endtag(self, tag):
            if tag in VOID:
                return
            if self.stack and self.stack[-1][0] == tag:
                self.stack.pop()
            else:
                found = next((i for i in range(len(self.stack) - 1, -1, -1)
                              if self.stack[i][0] == tag), None)
                if found is None:
                    self.errors.append(f"L{self.getpos()[0]} </{tag}> 无配对开始标签")
                else:
                    self.errors.append(
                        f"L{self.getpos()[0]} </{tag}> 交叉嵌套 (未闭: "
                        + ", ".join(f"{t}@L{ln}" for t, ln in self.stack[found + 1:]) + ")")
                    del self.stack[found:]

    try:
        src = p.read_text(encoding="utf-8", errors="replace")
        # Flask 模板: 先剥离 Jinja2 定界符再解析 (标签内/外的 {% %}/{{ }} 都换成空格,
        # 用注释会在标签内部产生 body<!--jinja-- 之类的伪 tag 名)
        src = re.sub(r"\{%.*?%\}", " ", src, flags=re.S)
        src = re.sub(r"\{\{.*?\}\}", " ", src, flags=re.S)
        parser = Balance()
        parser.feed(src)
        parser.close()
        for tag, ln in parser.stack:
            parser.errors.append(f"开始标签 <{tag}>@L{ln} 未闭合")
        out = {"ok": len(parser.errors) == 0, "file": path, "errors": parser.errors[:20],
               "error_count": len(parser.errors)}
        if out["ok"]:
            out["message"] = "HTML 结构平衡 PASS"
        _audit("check_html", {"path": path}, f"errors={out['error_count']}", out["ok"],
               ms=int((time.time() - t0) * 1000))
        return out
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def check_js(path: str) -> dict:
    """JS 语法校验 (node --check), 编译能力覆盖 JavaScript"""
    t0 = time.time()
    p = _safe_path(path)
    if not p or not p.is_file():
        return {"ok": False, "error": f"文件不存在或越界: {path}"}
    if p.suffix.lower() not in (".js", ".mjs", ".cjs"):
        return {"ok": False, "error": f"非 JS 文件: {p.suffix} (仅 .js/.mjs/.cjs)"}
    try:
        r = subprocess.run(["node", "--check", str(p)], capture_output=True,
                           text=True, timeout=15)
        out = {"ok": r.returncode == 0, "file": path,
               "output": _clip(((r.stderr or r.stdout) or "(语法 OK)").strip())}
        _audit("check_js", {"path": path}, f"exit={r.returncode}", out["ok"],
               ms=int((time.time() - t0) * 1000))
        return out
    except FileNotFoundError:
        return {"ok": False, "error": "node 不可用 (未安装)"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def run_tests(path: str = "") -> dict:
    """跑 pytest (摘要模式), 无测试目录时给出说明"""
    t0 = time.time()
    target = path or "tests"
    base = _safe_path(target) if target != "tests" else PROJECT_ROOT / "tests"
    if base and base.is_file() and base.suffix == ".py":
        base = base.parent
    if not base or not base.is_dir():
        return {"ok": False, "error": f"测试路径不存在: {target}"}
    # pytest 在 .venv_tests (Flask 主 python 无 pytest, PEP 668 不可 --user)
    py = PROJECT_ROOT / ".venv_tests" / "bin" / "python"
    if not py.exists():
        py = Path(sys.executable)
    try:
        r = subprocess.run([str(py), "-m", "pytest", "-x", "-q", "--tb=line", str(base)],
                           cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120)
        tail = "\n".join((r.stdout or "").splitlines()[-20:])
        out = {"ok": True, "exit_code": r.returncode, "summary": _clip(tail or "(无输出)"),
               "passed": r.returncode == 0}
    except subprocess.TimeoutExpired:
        out = {"ok": False, "error": "测试超时 (>120s)"}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("run_tests", {"path": target}, f"exit={out.get('exit_code', '?')}", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


# ────────────────────────── 仙女座桥接工具 (TOOLCHAT-002) ──────────────────────────

def knowledge_search(query: str, top_k: int = 3) -> dict:
    """仙女座知识库语义检索 (rag_search / local_vectors 向量库)"""
    t0 = time.time()
    try:
        from engines.andromeda_core import rag_search
        hits = rag_search(query, top_k=min(int(top_k or 3), 5))
        out = {"ok": True, "count": len(hits),
               "results": [{"score": round(h[0], 3), "file": h[1], "text": h[2][:400]} for h in hits]}
    except Exception as ex:
        out = {"ok": False, "error": f"知识库不可用: {str(ex)[:150]}"}
    _audit("knowledge_search", {"query": query}, f"{out.get('count', 0)} hits", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def patch_function(filepath: str, func_name: str, new_code: str, class_name: str = "") -> dict:
    """函数级精准修补 (andromeda_core extract/patch_func_code) — 只替换目标函数, 不动文件其余部分"""
    t0 = time.time()
    p = _safe_path(filepath)
    if not p or not p.is_file():
        return {"ok": False, "error": f"文件不存在或被禁止: {filepath}"}
    if not isinstance(new_code, str) or "def " not in new_code:
        return {"ok": False, "error": "new_code 必须包含完整函数定义 (def ...)"}
    # 先编译验证代码本身
    try:
        compile(new_code, filepath, "exec")
    except SyntaxError as ex:
        return {"ok": False, "error": f"新函数语法错误: line {ex.lineno}: {ex.msg}"}
    try:
        from engines.andromeda_core import patch_func_code
        ok = patch_func_code(p, func_name, new_code, class_name or None)
        if not ok:
            out = {"ok": False, "error": f"未找到函数 {func_name}" + (f" (类 {class_name})" if class_name else "")}
        else:
            # 整体文件再验证
            chk = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                                 capture_output=True, text=True, timeout=15)
            out = {"ok": chk.returncode == 0,
                   "message": f"函数 {func_name} 已修补, 整文件编译{'通过' if chk.returncode == 0 else '失败'}",
                   "file": filepath}
            if chk.returncode != 0:
                out["error"] = f"整文件编译失败: {chk.stderr[:250]}"
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("patch_function", {"filepath": filepath, "func": func_name}, out.get("message") or out.get("error", ""), out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def gen_code(system: str, user: str) -> dict:
    """代码生成 (andromeda_core.ollama_code / qwen2.5-coder)"""
    t0 = time.time()
    try:
        from engines.andromeda_core import ollama_code
        code, meta = ollama_code(system or "你是资深 Python 工程师", user, timeout=120)
        out = {"ok": bool(code), "code": _clip(code or "", 6000), "meta": str(meta)[:100]}
    except Exception as ex:
        out = {"ok": False, "error": str(ex)[:200]}
    _audit("gen_code", {"user": user[:80]}, f"{len(out.get('code', ''))} chars", out.get("ok"), ms=int((time.time() - t0) * 1000))
    return out


def check_code(code: str, file_label: str = "chat_snippet") -> dict:
    """编译验证代码片段 (andromeda_core.verify_code → py_compile)"""
    try:
        from engines.andromeda_core import verify_code
        r = verify_code(code, file_label or "chat_snippet")
        passed = str(r.get("py_compile", "FAIL")).upper() == "PASS" if isinstance(r, dict) else bool(r)
        return {"ok": passed, "detail": str(r)[:300]}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def create_fix_task(target: str, gap: str) -> dict:
    """修复任务自动入厅 (andromeda_core.auto_create_autofix_flow) — 开发动作大厅备案"""
    try:
        from engines.andromeda_core import auto_create_autofix_flow
        flow_id = auto_create_autofix_flow(target or "chat_tool_patch", gap or "聊天工具链修补")
        return {"ok": bool(flow_id), "flow_id": flow_id,
                "message": f"修复流程已入厅: {flow_id}" if flow_id else "入厅失败"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def hall_lookup(hall_code: str = "") -> dict:
    """大厅任务状态查询 (读 DB, 只读安全)"""
    try:
        conn = sqlite3.connect(str(AUDIT_DB), timeout=8)
        conn.execute("PRAGMA busy_timeout=6000")
        if hall_code:
            rows = conn.execute(
                "SELECT id, hall_code, title, status, approval_status, source "
                "FROM mt_lab_task_hall WHERE hall_code LIKE ? ORDER BY id DESC LIMIT 5",
                (f"%{hall_code}%",)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, hall_code, title, status, approval_status, source "
                "FROM mt_lab_task_hall WHERE status NOT IN ('DONE','ARCHIVED') "
                "ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        return {"ok": True, "count": len(rows),
                "tasks": [{"id": r[0], "code": r[1], "title": (r[2] or "")[:80],
                           "status": r[3], "approval": r[4], "source": r[5]} for r in rows]}
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:200]}


def rebuild_knowledge_index(max_files: int = 40) -> dict:
    """
    重建仙女座知识库索引 (TOOLCHAT-005 补全):
    扫描 engines/blueprints py 文件 → 按函数/类切块 → nomic embedding → 写 local_vectors
    rag_search 从此有数据可检索
    """
    t0 = time.time()
    import base64
    import numpy as np
    from engines.andromeda_core import RAG_DB, ollama_embedding
    chunks = []
    for sub in ("engines", "blueprints", "."):
        d = PROJECT_ROOT / sub
        files = sorted(d.glob("*.py")) if d.is_dir() else []
        for f in files[:max_files]:
            try:
                src = f.read_text(errors="replace")
            except Exception:
                continue
            # 按顶层 def/class 切块
            blocks, cur, header = [], [], f"#[{f.name}] "
            for line in src.splitlines():
                if (line.startswith("def ") or line.startswith("class ")) and cur:
                    blocks.append(header + "\n".join(cur))
                    cur = [line]
                else:
                    cur.append(line)
                if len(cur) > 120:
                    blocks.append(header + "\n".join(cur))
                    cur = []
            if cur:
                blocks.append(header + "\n".join(cur))
            chunks += [(f.name, b[:2000]) for b in blocks if 30 < len(b) < 3000]
    chunks = chunks[:300]
    if not chunks:
        return {"ok": False, "error": "未找到可索引代码块"}
    RAG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RAG_DB), timeout=15)
    conn.execute("""CREATE TABLE IF NOT EXISTS local_vectors(
        source_file TEXT, chunk_text TEXT, vector TEXT)""")
    conn.execute("DELETE FROM local_vectors")
    ok_n, fail = 0, 0
    for fname, text in chunks:
        try:
            emb = np.array(ollama_embedding(text), dtype=np.float32)
            conn.execute("INSERT INTO local_vectors VALUES(?,?,?)",
                         (fname, text, base64.b64encode(emb.tobytes()).decode()))
            ok_n += 1
        except Exception:
            fail += 1
    conn.commit()
    conn.close()
    out = {"ok": ok_n > 0, "indexed": ok_n, "failed": fail, "files": max_files,
           "message": f"知识库索引完成: {ok_n} 块 (来自 engines+blueprints)"}
    _audit("rebuild_knowledge_index", {}, f"{ok_n} chunks", out["ok"], ms=int((time.time() - t0) * 1000))
    return out


# ────────────────────────── 项目上下文分析 (TOOLCHAT-002) ──────────────────────────

_CTX_CACHE = {"ts": 0.0, "pack": ""}


def build_dev_context(max_chars: int = 2500) -> str:
    """
    项目上下文包: 模块地图 + 大厅进行中任务 + 最近修复经验
    300s 缓存; 拼进 tool loop 的 system prompt, 让模型开发前先懂项目
    """
    if time.time() - _CTX_CACHE["ts"] < 300 and _CTX_CACHE["pack"]:
        return _CTX_CACHE["pack"]
    parts = ["[项目上下文] MTSCOS = Flask 大厅自治系统 (flask-app/)"]
    try:
        # 1. 模块地图
        for sub, label in (("engines", "引擎层"), ("blueprints", "路由层")):
            d = PROJECT_ROOT / sub
            if d.is_dir():
                mods = sorted(f.stem for f in d.glob("*.py"))[:18]
                parts.append(f"{label}({sub}/): " + ", ".join(mods))
        # 2. 大厅进行中任务 (top 5)
        try:
            conn = sqlite3.connect(str(AUDIT_DB), timeout=8)
            conn.execute("PRAGMA busy_timeout=6000")
            tasks = conn.execute(
                "SELECT hall_code, status FROM mt_lab_task_hall "
                "WHERE status NOT IN ('DONE','ARCHIVED') ORDER BY id DESC LIMIT 5").fetchall()
            conn.close()
            if tasks:
                parts.append("大厅进行中: " + "; ".join(f"{c}({s})" for c, s in tasks))
        except Exception:
            pass
        # 3. 最近修复经验 (FIX_EXPERIENCE 知识点)
        try:
            conn = sqlite3.connect(str(AUDIT_DB), timeout=8)
            conn.execute("PRAGMA busy_timeout=6000")
            kps = conn.execute(
                "SELECT title FROM mt_center_knowledge_points "
                "WHERE kp_type='FIX_EXPERIENCE' ORDER BY id DESC LIMIT 5").fetchall()
            conn.close()
            if kps:
                parts.append("最近修复经验: " + "; ".join((r[0] or "")[:50] for r in kps))
        except Exception:
            pass
    except Exception:
        pass
    pack = "\n".join(p for p in parts if p)[:max_chars]
    _CTX_CACHE.update({"ts": time.time(), "pack": pack})
    return pack



TOOLS = {
    "safe_read_file": (safe_read_file, "读代码文件。参数: path(必填,flask-app内相对路径), start(起始行,默认1), end(结束行)"),
    "safe_list_dir": (safe_list_dir, "列目录。参数: path(默认项目根)"),
    "safe_grep": (safe_grep, "按正则/关键字精确搜索代码。参数: pattern(必填), glob(文件通配,默认*.py), path(搜索起始目录,默认.)"),
    "safe_write_file": (safe_write_file, "写文件(新建或整文件覆盖, 自动备份+py_compile验证+失败回滚)。参数: path(必填), content(完整文件内容,必填)"),
    "safe_exec": (safe_exec, "执行白名单命令(pytest/py_compile/git只读/ollama list/ls)。参数: cmd(必填)"),
    "run_tests": (run_tests, "跑 pytest 测试。参数: path(默认tests)"),
    "knowledge_search": (knowledge_search, "仙女座知识库语义检索(项目经验/文档/历史修复)。参数: query(必填), top_k(默认3)"),
    "patch_function": (patch_function, "函数级精准修补(只替换目标函数, 自动编译验证)。参数: filepath(必填), func_name(必填), new_code(完整新函数定义,必填), class_name(可选)"),
    "gen_code": (gen_code, "调 qwen2.5-coder 生成代码。参数: system(角色设定), user(需求描述,必填)"),
    "check_code": (check_code, "编译验证代码片段。参数: code(必填), file_label(可选)"),
    "check_html": (check_html, "HTML 模板结构校验(标签配对/嵌套平衡)。参数: path(flask-app内相对路径)"),
    "check_js": (check_js, "JS 语法校验(node --check)。参数: path(.js/.mjs/.cjs)"),
    "create_fix_task": (create_fix_task, "修复任务自动入厅备案。参数: target(目标模块), gap(问题描述)"),
    "hall_lookup": (hall_lookup, "查询大厅任务状态。参数: hall_code(可选,空则列进行中任务)"),
    "rebuild_knowledge_index": (rebuild_knowledge_index, "重建知识库索引(代码语义检索用,知识库为空时先跑这个)。参数: 无"),
    "set_theme": (None, "更换用户界面主题(按用户持久化,只影响本人)。参数: theme(主题名或颜色: pink/粉色/dark/深色/紫色等)"),
    "get_theme": (None, "查询当前用户主题。参数: 无"),
    "reset_theme": (None, "恢复默认白色主题。参数: 无"),
    "modify_setting": (None, "泛化修改用户设置(昵称/语言/额度/组别/部门/主题等; 密码角色等敏感项自动走审批单)。参数: key(字段名), value(新值)"),
    "get_my_context": (None, "查询我的全部设置/最近修改历史/聊天上下文摘要。参数: 无"),
}

_TOOL_PROMPT = (
    "\n\n[开发工具能力] 你可以调用以下工具完成真实开发任务 (查代码/读文件/改代码/跑测试):\n"
    + "\n".join(f"- {k}: {v[1]}" for k, v in TOOLS.items())
    + "\n\n调用规则: 需要工具时, 只输出一行 <tool_call>{\"name\":\"工具名\",\"arguments\":{...}}</tool_call>, 不要输出其他内容。"
      "定位代码必须先用 safe_grep 搜索 (不要猜文件路径), 拿到文件行号后再 safe_read_file 阅读。"
      "修改已有函数优先用 patch_function (精准安全), 新建文件才用 safe_write_file。"
      "完成修补后如属 bug 修复, 用 create_fix_task 自动入厅备案。"
      "需要项目经验/历史修复方案时用 knowledge_search。"
      "收到 <tool_result> 后继续思考; 若还需工具则再输出 tool_call, 否则给出最终中文回答。"
      "禁止编造工具结果和文件路径。写文件时 content 必须是完整文件内容。"
)


# ────────────────────────── 意图识别 ──────────────────────────

_INTENT_PATTERNS = re.compile(
    r"查(一下)?(代码|文件|函数|报错|bug|错误|日志)|搜(索)?(代码|文件|函数)|"
    r"在哪(个)?(文件|函数|位置)|帮我?修|修复|补全|加一?个?功能|实现|重构|"
    r"写一?个?(函数|脚本|接口|页面|模块)|跑(一下)?测试|执行.*命令|看看.*(代码|文件|日志|报错)|"
    r"grep|文件里|代码里|函数里"
    r"|换(个)?主题|更换主题|主题.*(色|模式)|改成.*(色|主题)|界面.*(色|主题)|夜间模式|深色模式|护眼"
    r"|修改(我的|一下)?(密码|昵称|资料|组别|部门|设置|参数|额度|语言)|更改(密码|昵称|设置|组别)"
    r"|改(个)?密码|改昵称|设置昵称|我的(设置|资料|上下文|修改记录|偏好)",
    re.I)


def detect_tool_intent(text: str) -> bool:
    """检测开发/主题意图 → 决定是否走工具循环"""
    if not text:
        return False
    if _INTENT_PATTERNS.search(text):
        return True
    try:
        from engines.chat_theme_engine import detect_theme_intent
        return detect_theme_intent(text)
    except Exception:
        return False


# ────────────────────────── tool-use 主循环 ──────────────────────────

def _ollama_chat(host: str, model: str, messages: list,
                 num_ctx: int = None, num_predict: int = None, timeout: int = 180,
                 stream_cb=None) -> str:
    """直连 Ollama /api/chat (多轮), 返回 assistant 文本
    stream_cb(delta) 非 None 时走流式, 逐段回调增量 (TOOLCHAT-008)"""
    options = {}
    if num_ctx:
        options["num_ctx"] = num_ctx
    if num_predict:
        options["num_predict"] = num_predict
    body = {"model": model, "messages": messages, "stream": bool(stream_cb)}
    if options:
        body["options"] = options
    req = urllib.request.Request(
        f"http://{host}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    if not stream_cb:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        return data.get("message", {}).get("content", "")
    # 流式 NDJSON
    resp = urllib.request.urlopen(req, timeout=timeout)
    full = []
    for line in resp:
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except Exception:
            continue
        delta = (chunk.get("message") or {}).get("content", "")
        if delta:
            full.append(delta)
            try:
                stream_cb(delta)
            except Exception:
                pass
        if chunk.get("done"):
            break
    return "".join(full)


_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
_CALL_OPEN_RE = re.compile(r"<tool_call>\s*(\{.*)", re.S)   # 容忍未闭合标签


def _parse_tool_call(reply: str):
    """从模型输出解析 tool_call JSON; 支持未闭合标签 + 代码围栏; 失败返回 None"""
    if not reply:
        return None
    text = reply.replace("```json", "").replace("```", "")
    m = _CALL_RE.search(text) or _CALL_OPEN_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    # 括号平衡扫描: 截取第一个完整 JSON 对象
    depth, end_idx = 0, -1
    in_str = False
    esc = False
    for i, ch in enumerate(raw):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    if end_idx > 0:
        raw = raw[:end_idx + 1]
    try:
        call = json.loads(raw)
        if isinstance(call, dict) and call.get("name"):
            return call
    except Exception:
        pass
    return None


def run_tool_loop(model: str, system_prompt: str, user_text: str,
                  history: list = None, session_id: str = "", user_id: str = "",
                  host: str = "127.0.0.1:11434",
                  num_ctx: int = None, num_predict: int = None,
                  max_rounds: int = TOOL_MAX_ROUNDS,
                  with_context: bool = True,
                  on_event=None) -> dict:
    """
    tool-use 主循环:
      用户消息 → 模型 <tool_call> → 执行 → <tool_result> 回填 → … → 最终回答
    with_context=True 时注入项目上下文包 (模块地图+大厅任务+修复经验, TOOLCHAT-002)
    on_event(ev) 非None时推送事件流 (TOOLCHAT-008):
      round / delta(临时,该轮出工具则前端清空) / tool_start / tool_done
    返回: {answer, tool_calls:[{tool,args,ok,summary}], rounds}
    """
    t0 = time.time()
    # 主题 + 用户动作工具懒绑定 + 用户上下文注入 (TOOLCHAT-003/004)
    try:
        from engines import chat_theme_engine as _cte
        if TOOLS.get("set_theme") and TOOLS["set_theme"][0] is None:
            for k, fn in (("set_theme", _cte.tool_set_theme), ("get_theme", _cte.tool_get_theme), ("reset_theme", _cte.tool_reset_theme)):
                TOOLS[k] = (fn, TOOLS[k][1])
        _cte.set_tool_context(user_id=user_id, session_id=session_id)
    except Exception:
        pass
    try:
        from engines import user_space_engine as _use
        if TOOLS.get("modify_setting") and TOOLS["modify_setting"][0] is None:
            for k, fn in (("modify_setting", _use.tool_modify_setting), ("get_my_context", _use.tool_get_my_context)):
                TOOLS[k] = (fn, TOOLS[k][1])
    except Exception:
        pass
    sys_full = system_prompt or ""
    if with_context:
        try:
            ctx = build_dev_context()
            if ctx:
                sys_full = sys_full + "\n" + ctx
        except Exception:
            pass
    messages = [{"role": "system", "content": sys_full + _TOOL_PROMPT}]
    messages += [{"role": m["role"], "content": m["content"]} for m in (history or [])
                 if m.get("role") in ("user", "assistant") and m.get("content")]
    messages.append({"role": "user", "content": user_text})

    tool_log = []
    answer = ""

    def _ev(ev):
        try:
            if on_event:
                on_event(ev)
        except Exception:
            pass

    for rnd in range(1, max_rounds + 1):
        _ev({"type": "round", "round": rnd})
        try:
            reply = _ollama_chat(host, model, messages,
                                 num_ctx=num_ctx, num_predict=num_predict,
                                 stream_cb=(lambda d: _ev({"type": "delta", "text": d})) if on_event else None)
        except Exception as ex:
            answer = f"⚠️ 推理引擎暂时不可用 ({host}): {str(ex)[:120]}"
            break
        call = _parse_tool_call(reply)
        if call is None:
            answer = (reply or "").strip() or "(模型无回复)"
            break
        try:
            name = call.get("name", "")
            args = call.get("arguments", {}) or {}
        except Exception:
            name, args = "", {}
        _ev({"type": "tool_start", "tool": name})
        entry = TOOLS.get(name)
        fn = entry[0] if entry else None
        if not fn:
            result = {"ok": False, "error": f"未知工具 {name}, 可用: {', '.join(TOOLS)}"}
        else:
            try:
                result = fn(**args) if isinstance(args, dict) else {"ok": False, "error": "参数必须是对象"}
            except TypeError as ex:
                result = {"ok": False, "error": f"参数错误: {str(ex)[:150]}"}
        summary = str(result.get("error") or result.get("message") or
                      result.get("summary") or result.get("count") or "done")[:120]
        tool_log.append({"tool": name, "args": args, "ok": result.get("ok"), "summary": summary})
        _ev({"type": "tool_done", "tool": name, "ok": result.get("ok"), "summary": summary})
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user",
                         "content": "<tool_result>\n" + json.dumps(result, ensure_ascii=False)[:MAX_OUTPUT_CHARS] + "\n</tool_result>\n请继续 (还需工具则输出 tool_call, 否则给出最终回答)"})
    else:
        answer = answer or "已达工具调用轮次上限, 请缩小问题范围后重试。已执行: " + ", ".join(t["tool"] for t in tool_log)

    return {"answer": answer, "tool_calls": tool_log,
            "rounds": len(tool_log) + (1 if answer else 0),
            "duration_ms": int((time.time() - t0) * 1000)}


if __name__ == "__main__":
    # 自检: 语法 + 工具冒烟
    print("[chat_toolbox] self-test")
    print(" read:", safe_read_file("modular_start.py", 1, 3)["ok"])
    print(" list:", safe_list_dir("engines")["ok"])
    print(" grep:", safe_grep("def ollama_chat", path="engines")["ok"])
    print(" exec deny:", safe_exec("rm -rf /")["ok"] is False)
    print(" intent:", detect_tool_intent("帮我修一下登录 bug"))
