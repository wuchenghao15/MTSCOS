#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座 · 代码与文件卫生巡检引擎 — andromeda_code_hygiene_engine.py
====================================================================

§14 flow_id: FLOW-20261012094305-95584

在常驻 andromeda_auto_loop（约 5min/轮）中新增两类卫生检测：
  ① CODE 屎山代码检测（纯 AST + 少量正则，零 token）：
     超长函数 / 圈复杂度 / 深嵌套 / 长参数 / 上帝类 / 重复代码块 /
     注释掉的代码 / 裸 except / 吞异常 pass / TODO 密度 / 未用私有符号 /
     大文件 / 尾空白 / 缺末换行 / 未用 import，并并入 auto_sniff 3 条非重叠规则。
  ② FILE 零散未归类文件检测：
     根目录散落 / 目录职责错放 / 异常命名 / 临时文件 / 超大散落文件（含 git 维度）。

闭环：检测 → 稳定指纹幂等落库（行号漂移不重报）→ 状态生命周期
     OPEN/ACK/FIXED/IGNORED（整轮未再见自动 FIXED，回归自动重开）
     → HIGH 且重复出现才晋升 mt_ai_suggestion_pool（应用层判重，绝不刷库）
     → 投喂 AI 脑库。仅尾空白/缺末换行/未用 import 三类纯文本安全项自动修复。

设计约束：
  - 全量明细覆盖 server_real_db.py 等超大文件，但按 chunk 跨 tick 分批（预算硬上限）。
  - 排除 venv/site-packages、ai_engines/*_fusion 外部融合源码、auto_gen/__pycache__ 等。
  - 落库 database/app.db（演化权威库）；OneDrive 大库用 busy_timeout，短事务。
  - 不移动文件、不重构业务代码、不 git commit/tag、不 launchctl、不碰 VERSION/.env。

CLI:
  python3 andromeda_code_hygiene_engine.py dry-run [--limit N] [--scope andromeda|all]
  python3 andromeda_code_hygiene_engine.py code [--full]   # 跑一个 chunk（--full 跑到本 sweep 完成）
  python3 andromeda_code_hygiene_engine.py files           # 跑一轮文件卫生
  python3 andromeda_code_hygiene_engine.py fix             # 仅安全项自动修
  python3 andromeda_code_hygiene_engine.py promote         # HIGH 晋升建议池
  python3 andromeda_code_hygiene_engine.py archive         # 归档历史 sniff 噪音(幂等)
  python3 andromeda_code_hygiene_engine.py status
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────────────────
ENGINES_DIR = Path(__file__).resolve().parent          # flask-app/engines
BASE = ENGINES_DIR.parent                              # flask-app
PROJECT_ROOT = BASE.parent                             # 项目根
DB_PATH = BASE / "database" / "app.db"

# 复用同目录 auto_sniff_engine 的现成行级规则（避免重复造）
if str(ENGINES_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINES_DIR))
try:
    import auto_sniff_engine as _sniff  # noqa: E402
    HAS_SNIFF = True
except Exception:
    HAS_SNIFF = False

# ── 节流与预算（被 andromeda_auto_loop 每 tick 调用）────────────────
HYG_CODE_GAP_SEC = 3600        # 代码完整 sweep 间隔 ≥60min
HYG_FILE_GAP_SEC = 1800        # 文件卫生间隔 ≥30min
BUDGET_FILES_PER_CHUNK = 120   # 单 chunk 最多扫描文件数
BUDGET_SEC_PER_CHUNK = 90      # 单 chunk 最多耗时
AUTO_FIX_PER_LOOP = 10
AUTO_FIX_SAFE = True
HYG_AI_ENABLED = False
PROMOTE_PER_LOOP = 3
PROMOTE_DAILY_MAX = 10
ENGINE_FLOW_ID = "andromeda_code_hygiene_v1"
SOURCE_NAME = "andromeda_code_hygiene"

# ── 屎山阈值 ────────────────────────────────────────────────────────
TH_FILE_LINES = 800           # FILE_TOO_LARGE
LARGE_FILE_LINE = 2000        # 超大文件：DUP 每文件最多取 400 个最大函数体
TH_FUNC_LINES = 80            # FUNC_TOO_LONG
TH_CYCLO = 15                 # CYCLO_COMPLEX
TH_NEST = 5                   # NEST_DEPTH
TH_ARGS = 7                   # ARG_COUNT
TH_CLASS_METHODS = 25         # GOD_CLASS 方法数
TH_CLASS_LINES = 400          # GOD_CLASS 类体行数
DUP_MIN_LINES = 8             # 连续 ≥8 归一化行相同
DUP_MAX_FUNCS_PER_LARGE_FILE = 400
TH_COMMENT_RUN = 12           # 连续注释行
TH_TODO_PER_100 = 3           # TODO 密度

FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_CONTROL = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
            ast.Try, ast.ExceptHandler)
_BUILTINS = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
_COMMON_MODS = {'os', 'sys', 'json', 're', 'time', 'datetime', 'hashlib', 'sqlite3',
                'threading', 'logging', 'random', 'collections', 'functools', 'pathlib',
                'typing', 'dataclasses', 'uuid', 'base64', 'hmac', 'secrets', 'ast',
                'traceback', 'abc', 'subprocess', 'signal', 'shutil', 'tempfile'}

# ── 扫描作用域（相对 flask-app；ai_engines 取白名单子目录，排除 *_fusion）──
AIENGINE_SUBDIR_OK = {'management', 'rules_engine', 'brain', 'learning',
                      'security', 'monitoring'}
EXCLUDE_PATH_PARTS = {'venv', '.venv', 'site-packages', '__pycache__', 'node_modules',
                      '.git', 'backups', '_migration_backups', '_migration_reports'}


def _is_excluded(rel_posix: str) -> bool:
    parts = rel_posix.split('/')
    for p in parts:
        if p in EXCLUDE_PATH_PARTS:
            return True
        if p.startswith('auto_gen_') or p.startswith('_migration'):
            return True
    if parts and parts[0] == 'ai_engines':
        # ai_engines 直接层 py 放行；子目录仅白名单，其余（*_fusion 等）排除
        if len(parts) >= 2 and parts[1] not in AIENGINE_SUBDIR_OK:
            return True
    return False


def list_code_files(scope: str = "all") -> list[str]:
    """返回排序后的待扫 .py（相对 flask-app 的 POSIX 路径）。scope=andromeda 仅仙女座。"""
    out: set[str] = set()
    roots: list[Path] = []
    if scope == "andromeda":
        for p in ENGINES_DIR.glob("andromeda_*.py"):
            out.add(p.relative_to(BASE).as_posix())
        for p in ENGINES_DIR.glob("auto_*.py"):
            out.add(p.relative_to(BASE).as_posix())
        return sorted(out)

    dir_roots = ['engines', 'ai_engines', 'routes', 'app', 'core', 'services', 'scripts']
    for d in dir_roots:
        rp = BASE / d
        if rp.is_dir():
            roots.append(rp)
    for rp in roots:
        for f in rp.rglob('*.py'):
            rel = f.relative_to(BASE).as_posix()
            if not _is_excluded(rel):
                out.add(rel)
    for f in BASE.glob('*.py'):
        out.add(f.relative_to(BASE).as_posix())
    return sorted(out)


# ── 文件卫生常量（与 ai_file_organizer 的 ROOT_KEEP_* 对齐，本地复制以免 import 副作用）──
ROOT_KEEP_FILES = {
    "README.md", "requirements.txt", "package.json", ".gitignore",
    "sync_github.sh", "sync_github_fast.sh", "start_ai_eigenflux_daemon.command",
    "start_smart_mount_daemon.command",
}
ROOT_KEEP_DIRS = {
    "flask-app", "static", "templates", "docs", "_config", "_runtime",
    ".trae", ".git", "node_modules", "tests", "venv", ".venv",
    "__pycache__", "logs", "pids",
}
# 额外豁免（运行时/同步/系统），不参与 ROOT_LOOSE 报警
ROOT_EXTRA_SKIP = {
    "cache", "keys", "certs", "uploads", "_git_shadow_backups", "_git_quarantine",
    ".vscode", ".github", ".idea", ".rules", ".claude", "HTML", "Database",
    "Database_Backups", "split_databases", "repo", "Manifests",
}
# 根目录标准仓库元数据/构建文件（放根目录是惯例，不算散落）
_VCS_ALLOW_EXACT = {
    "license", "license.txt", "licence", "notice", "authors", "makefile",
    "dockerfile", ".gitattributes", ".gitmodules", ".gitmessage", ".editorconfig",
    ".dockerignore", ".mailmap", ".python-version", ".flake8", ".coveragerc",
    "tox.ini", "setup.py", "setup.cfg", "pyproject.toml", "manifest.in",
    "pytest.ini", "requirements.txt", "package.json", "package-lock.json",
    "docker-compose.yml", "docker-compose.yaml", ".env.example",
}
_VCS_ALLOW_PREFIX = ("readme", "changelog", "code_of_conduct", "contributing",
                     "funding", "security", "release_notes", "license",
                     "apk_readme", ".env.")
# 代码目录下的资源类子目录：不做后缀职责校验
RESOURCE_DIRS = {"templates", "migrations", "migration", "data", "assets",
                 "fixtures", "docs", "snapshots", "static", "resources",
                 "locale", "locales", "conf", "configs", "templates_backup",
                 "instance", "samples", "example", "examples"}
_BACKUP_EXT = {".bak", ".backup", ".tmp", ".orig", ".swp", ".old"}
TEMP_NAME_RE = re.compile(r'(^~.*|.*\.(tmp|swp|bak|backup|orig|old|pyc|DS_Store)$)', re.IGNORECASE)
BAD_NAME_RE = re.compile(r'[一-鿿]|\s|_{2,}')

# 目录 → 允许扩展名（依据 .trae/rules/开发规则.md 目录职责）
DIR_ALLOW_EXT = {
    'engines': {'.py'},
    'ai_engines': {'.py'},
    'routes': {'.py'},
    'core': {'.py'},
    'services': {'.py'},
    'app': {'.py'},
    'templates': {'.html', '.jinja', '.jinja2', '.txt'},
    'scripts': {'.py', '.sh', '.sql', '.json', '.md'},
}
STATIC_EXT = {'.css', '.js', '.mjs', '.png', '.jpg', '.jpeg', '.gif', '.svg',
              '.webp', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map', '.json'}
BIG_LOOSE_BYTES = 20 * 1024 * 1024


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rel_project(abs_path: Path) -> str:
    try:
        return abs_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return abs_path.as_posix()


# ════════════════════════════════════════════════════════════════════
# 建表
# ════════════════════════════════════════════════════════════════════
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def ensure_tables() -> None:
    c = _conn()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mt_hygiene_findings (
          finding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
          fingerprint   TEXT NOT NULL UNIQUE,
          category      TEXT NOT NULL CHECK(category IN ('CODE','FILE')),
          rule_id       TEXT NOT NULL,
          severity      TEXT NOT NULL CHECK(severity IN ('CRITICAL','HIGH','MED','LOW','INFO')),
          file_path     TEXT NOT NULL,
          line          INTEGER DEFAULT 0,
          symbol        TEXT,
          metric_value  REAL,
          threshold_val REAL,
          status        TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN','ACK','FIXED','IGNORED')),
          seen_count    INTEGER DEFAULT 1,
          first_seen_at TEXT NOT NULL,
          last_seen_at  TEXT NOT NULL,
          last_sweep_id TEXT,
          auto_fixed    INTEGER DEFAULT 0,
          meta_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hyg_status ON mt_hygiene_findings(status,severity);
        CREATE INDEX IF NOT EXISTS idx_hyg_rule   ON mt_hygiene_findings(rule_id);
        CREATE INDEX IF NOT EXISTS idx_hyg_file   ON mt_hygiene_findings(file_path);

        CREATE TABLE IF NOT EXISTS mt_hygiene_runs (
          run_id TEXT PRIMARY KEY, kind TEXT, sweep_id TEXT,
          started_at TEXT, finished_at TEXT, duration_s REAL,
          scanned INTEGER DEFAULT 0, new_open INTEGER DEFAULT 0,
          still_open INTEGER DEFAULT 0, auto_closed INTEGER DEFAULT 0,
          auto_fixed INTEGER DEFAULT 0, promoted INTEGER DEFAULT 0,
          chunk INTEGER DEFAULT 0, phase TEXT, note TEXT
        );

        CREATE TABLE IF NOT EXISTS mt_hygiene_scan_state (
          kind TEXT PRIMARY KEY, phase TEXT, sweep_id TEXT,
          cursor_idx INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
          sweep_started_at TEXT, updated_at TEXT
        );
        """)
        c.commit()
    finally:
        c.close()


# ════════════════════════════════════════════════════════════════════
# AST 屎山分析
# ════════════════════════════════════════════════════════════════════
def _norm_tokens(text: str, n: int = 8) -> str:
    s = re.sub(r'#.*', '', text)
    s = re.sub(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')', 'DOC', s)
    s = re.sub(r'("[^"\n]*"|\'[^\'\n]*\')', 'S', s)
    s = re.sub(r'\b\d+\.?\d*\b', 'N', s)
    toks = re.findall(r'[A-Za-z_]\w*|[^\sA-Za-z_]', s)
    return ''.join(toks[:n])


def _walk_skip_nested(node: ast.AST):
    """遍历子树但不进入嵌套函数（保证函数指标归属正确）。"""
    stack = [node]
    while stack:
        x = stack.pop()
        yield x
        for ch in ast.iter_child_nodes(x):
            if isinstance(ch, FUNC_NODES) and ch is not node:
                continue
            stack.append(ch)


def _cyclomatic(fn: ast.AST) -> int:
    n = 1
    for x in _walk_skip_nested(fn):
        if isinstance(x, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                          ast.AsyncWith, ast.ExceptHandler, ast.Assert)):
            n += 1
        elif isinstance(x, ast.BoolOp):
            n += max(0, len(x.values) - 1)
        elif isinstance(x, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            n += sum(len(gen.ifs) for gen in x.generators)
        elif hasattr(ast, 'match_case') and isinstance(x, ast.match_case):
            n += 1
    return n


def _nest_depth(node: ast.AST) -> int:
    best = 0
    stack = [(node, 0)]
    while stack:
        x, d = stack.pop()
        for ch in ast.iter_child_nodes(x):
            if isinstance(ch, FUNC_NODES):
                continue
            nd = d + 1 if isinstance(ch, _CONTROL) else d
            if nd > best:
                best = nd
            stack.append((ch, nd))
    return best


def _arg_count(fn) -> int:
    a = fn.args
    n = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    if a.vararg:
        n += 1
    if a.kwarg:
        n += 1
    return n


def _sev_rank(s: str) -> int:
    return {'CRITICAL': 0, 'HIGH': 1, 'MED': 2, 'LOW': 3, 'INFO': 4}.get(s, 9)


def _mk(rule_id, sev, rel, line, symbol, metric, threshold, ctx, meta=None):
    return dict(rule_id=rule_id, severity=sev, file=rel, line=int(line or 0),
                symbol=symbol or '', metric=metric, threshold=threshold,
                ctx=ctx or '', meta=meta or {})


def analyze_code_file(rel: str, abs_path: Path, dup_index: dict, dup_pairs: set):
    """分析单个 .py，返回 findings 列表；dup_index/dup_pairs 为跨文件重复块倒排（原地累积）。"""
    out: list[dict] = []
    try:
        source = abs_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return out
    if not source.strip():
        return out
    lines = source.split('\n')
    nlines = len(lines)

    if nlines > TH_FILE_LINES:
        out.append(_mk('FILE_TOO_LARGE', 'MED', rel, 1, '', nlines, TH_FILE_LINES, 'file'))

    # ── 文件级安全项（供自动修复）──
    tw = [i + 1 for i, ln in enumerate(lines) if ln != ln.rstrip() and ln.strip()]
    if tw:
        out.append(_mk('TRAILING_WHITESPACE', 'LOW', rel, tw[0], '', len(tw), 1, 'trailing_ws'))
    if source and not source.endswith('\n'):
        out.append(_mk('MISSING_NEWLINE', 'LOW', rel, nlines, '', 1, 1, 'missing_nl'))

    # ── 注释掉的代码块 ──
    run_start, run_len, code_like, reported_comment = None, 0, 0, 0
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith('#'):
            if run_len == 0:
                run_start = i
            run_len += 1
            body = s.lstrip('#').strip()
            if re.search(r'(=|import |def |return |self\.|[():]|:\s*$|,\s*$)', body):
                code_like += 1
        else:
            if run_len >= TH_COMMENT_RUN and code_like / max(1, run_len) >= 0.6 and reported_comment < 2:
                # ctx 用文件内出现序号而非起始行: 上方插行不导致指纹漂移
                out.append(_mk('COMMENTED_CODE', 'LOW', rel, run_start, '', run_len,
                               TH_COMMENT_RUN, f'commentrun_{reported_comment + 1}'))
                reported_comment += 1
            run_start, run_len, code_like = None, 0, 0
    if run_len >= TH_COMMENT_RUN and code_like / max(1, run_len) >= 0.6 and reported_comment < 2:
        out.append(_mk('COMMENTED_CODE', 'LOW', rel, run_start, '', run_len,
                       TH_COMMENT_RUN, f'commentrun_{reported_comment + 1}'))

    # ── TODO 密度 ──
    todo_n = len(re.findall(r'\b(TODO|FIXME|HACK|XXX)\b[:\s]', source, re.IGNORECASE))
    if todo_n > TH_TODO_PER_100 * (nlines / 100.0):
        m = re.search(r'(TODO|FIXME|HACK|XXX)', source, re.IGNORECASE)
        ln = source[:m.start()].count('\n') + 1 if m else 1
        out.append(_mk('TODO_DENSITY', 'LOW', rel, ln, '', todo_n,
                       TH_TODO_PER_100 * (nlines / 100.0), 'tododensity'))

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=rel)
    except SyntaxError:
        return out  # 语法错误归 auto_patrol（py_compile）

    # ── 未用 import（单行才报，安全自动修复前提）──
    imported: dict[str, tuple] = {}
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                nm = a.asname or a.name.split('.')[0]
                imported[nm] = (getattr(node, 'lineno', 1), getattr(node, 'end_lineno', node.lineno), a.name)
        elif isinstance(node, ast.ImportFrom):
            if getattr(node, 'module', '') == '__future__':
                continue
            for a in node.names:
                if a.name == '*':
                    continue
                nm = a.asname or a.name
                imported[nm] = (getattr(node, 'lineno', 1), getattr(node, 'end_lineno', node.lineno), a.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            cur = node
            while isinstance(cur, ast.Attribute):
                cur = cur.value
            if isinstance(cur, ast.Name):
                used.add(cur.id)
    unused_reported = 0
    for nm, (ln, end_ln, orig) in imported.items():
        if nm in used or nm in _BUILTINS or nm in _COMMON_MODS or end_ln and end_ln > ln:
            continue
        if unused_reported >= 5:
            break
        out.append(_mk('UNUSED_IMPORT', 'LOW', rel, ln, nm, 1, 1, 'unused_' + nm))
        unused_reported += 1

    # ── 未用私有符号（INFO，保守）──
    all_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            all_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            all_names.add(node.attr)

    # ── 函数 / 类指标（带类栈遍历）──
    func_specs = []   # (node, class_name)

    def _visit(node, cls_stack):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.ClassDef):
                methods = [b for b in ch.body if isinstance(b, FUNC_NODES)]
                cls_lines = (getattr(ch, 'end_lineno', ch.lineno) or ch.lineno) - ch.lineno + 1
                if len(methods) >= TH_CLASS_METHODS or cls_lines >= TH_CLASS_LINES:
                    seg = ast.get_source_segment(source, ch) or ''
                    out.append(_mk('GOD_CLASS', 'HIGH', rel, ch.lineno, ch.name,
                                   len(methods), TH_CLASS_METHODS, _norm_tokens(seg),
                                   {'class_lines': cls_lines}))
                _visit(ch, cls_stack + [ch.name])
            elif isinstance(ch, FUNC_NODES):
                func_specs.append((ch, cls_stack[-1] if cls_stack else ''))
                _visit(ch, cls_stack)  # 嵌套函数也统计，但 cls 栈不变
            else:
                _visit(ch, cls_stack)

    _visit(tree, [])

    # DUP 参与函数（超大文件取最大的 400 个）
    dup_candidates = []
    for fn, cls in func_specs:
        end = getattr(fn, 'end_lineno', fn.lineno) or fn.lineno
        flen = end - fn.lineno + 1
        qname = (cls + '.' if cls else '') + fn.name
        # 长函数
        if flen > TH_FUNC_LINES:
            seg = ast.get_source_segment(source, fn) or ''
            out.append(_mk('FUNC_TOO_LONG', 'MED', rel, fn.lineno, qname, flen,
                           TH_FUNC_LINES, _norm_tokens(seg)))
        cyc = _cyclomatic(fn)
        if cyc > TH_CYCLO:
            # ctx 不含行号: qname 唯一标识函数, 函数上方插行不重报
            out.append(_mk('CYCLO_COMPLEX', 'HIGH', rel, fn.lineno, qname, cyc,
                           TH_CYCLO, f'cyc_{qname}'))
        depth = _nest_depth(fn)
        if depth > TH_NEST:
            out.append(_mk('NEST_DEPTH', 'MED', rel, fn.lineno, qname, depth,
                           TH_NEST, f'nest_{qname}'))
        ac = _arg_count(fn)
        if ac > TH_ARGS:
            out.append(_mk('ARG_COUNT', 'MED', rel, fn.lineno, qname, ac,
                           TH_ARGS, f'args_{qname}'))
        # 异常处理: 同一函数可能有多个 except, ctx 用函数内出现序号 (AST 顺序稳定)
        # 而非行号, 行漂移不重报、同函数多处仍可区分
        bare_occ = swallow_occ = 0
        for x in _walk_skip_nested(fn):
            if isinstance(x, ast.ExceptHandler):
                if x.type is None:
                    bare_occ += 1
                    out.append(_mk('BARE_EXCEPT', 'LOW', rel,
                                   getattr(x, 'lineno', fn.lineno), qname, 1, 1,
                                   f'bare_{qname}_{bare_occ}'))
                body = x.body
                trivial = body and all(
                    (isinstance(b, ast.Pass) or
                     (isinstance(b, ast.Expr) and isinstance(getattr(b, 'value', None), ast.Constant)
                      and b.value.value in (Ellipsis, None)))
                    for b in body)
                if trivial:
                    # 仅 pass/.../docstring 常量、且无 raise
                    if not any(isinstance(b, ast.Raise) for b in body):
                        swallow_occ += 1
                        out.append(_mk('SWALLOW_PASS', 'MED', rel,
                                       getattr(x, 'lineno', fn.lineno), qname, 1, 1,
                                       f'swallow_{qname}_{swallow_occ}'))
        # 未用私有
        nm = fn.name
        if nm.startswith('_') and not nm.startswith('__') and nm not in all_names:
            out.append(_mk('UNUSED_PRIVATE', 'INFO', rel, fn.lineno, qname, 1, 1,
                           'privfn_' + nm))
        dup_candidates.append((flen, fn, qname))

    # 模块级/类级未用私有的类
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith('_') and \
                not node.name.startswith('__') and node.name not in all_names:
            out.append(_mk('UNUSED_PRIVATE', 'INFO', rel, node.lineno, node.name, 1, 1,
                           'privcls_' + node.name))

    # ── 重复代码块（8-gram 归一化行，跨文件单遍倒排）──
    try:
        if nlines > LARGE_FILE_LINE:
            dup_candidates.sort(key=lambda t: -t[0])
            dup_candidates = dup_candidates[:DUP_MAX_FUNCS_PER_LARGE_FILE]
        for flen, fn, qname in dup_candidates:
            body_nodes = fn.body
            if not body_nodes:
                continue
            b_start = body_nodes[0].lineno
            b_end = max((getattr(x, 'end_lineno', x.lineno) or x.lineno)
                        for x in ast.walk(fn))
            code_rows = []
            for li in range(b_start - 1, min(b_end, nlines)):
                raw = lines[li]
                s = re.sub(r'#.*', '', raw)
                s = re.sub(r'("[^"\n]*"|\'[^\'\n]*\')', 'S', s)
                s = re.sub(r'\b\d+\.?\d*\b', 'N', s)
                s = re.sub(r'\s+', '', s)
                if s:
                    code_rows.append((li + 1, s))
            if len(code_rows) < DUP_MIN_LINES:
                continue
            seen_win = set()
            for i in range(0, len(code_rows) - DUP_MIN_LINES + 1):
                win = [r[1] for r in code_rows[i:i + DUP_MIN_LINES]]
                h = hashlib.sha1('\n'.join(win).encode('utf-8')).hexdigest()
                if h in seen_win:
                    continue
                seen_win.add(h)
                here = (rel, qname)
                if h in dup_index:
                    other = dup_index[h]
                    if other[0] != rel or other[1] != qname:
                        pair = '||'.join(sorted([f'{other[0]}::{other[1]}',
                                                 f'{rel}::{qname}']))
                        if pair not in dup_pairs:
                            dup_pairs.add(pair)
                            out.append(_mk('DUP_BLOCK', 'HIGH', rel, code_rows[i][0], qname,
                                           DUP_MIN_LINES, DUP_MIN_LINES, 'dup_' + pair[:60],
                                           {'duplicate_of': f'{other[0]}::{other[1]}'}))
                else:
                    dup_index[h] = here
    except Exception:
        pass

    # ── 并入 auto_sniff 的 3 条非重叠行级规则 ──
    if HAS_SNIFF:
        try:
            for fn_sniff, rid, ctx_mode in (
                (_sniff.sniff_endpoint_duplicate, 'SNIFF_ENDPOINT_DUP', 'func'),
                (_sniff.sniff_missing_import, 'SNIFF_MISSING_IMPORT', 'symbol'),
                (_sniff.sniff_legacy_kwargs, 'SNIFF_LEGACY_KWARGS', 'text'),
            ):
                for r in fn_sniff(abs_path, lines):
                    sev = 'MED' if r.get('severity') == 'MEDIUM' else r.get('severity', 'LOW')
                    sym = r.get('func_name') or r.get('symbol') or ''
                    if ctx_mode == 'func':
                        ctx = 'routes_' + (sym or str(r.get('line')))
                    elif ctx_mode == 'symbol':
                        ctx = 'missing_' + (sym or '')
                    else:
                        ctx = 'legacy_' + re.sub(r'\s+', '', r.get('detail', ''))[:30]
                    out.append(_mk(rid, sev, rel, r.get('line', 1), sym, 1, 1, ctx,
                                   {'detail': r.get('detail', '')[:200]}))
        except Exception:
            pass

    out.sort(key=lambda f: (_sev_rank(f['severity']), f['file'], f['line']))
    return out


# ════════════════════════════════════════════════════════════════════
# 文件卫生
# ════════════════════════════════════════════════════════════════════
def _git_tracked() -> set[str]:
    try:
        p = subprocess.run(['git', 'ls-files', '--cached'], cwd=str(PROJECT_ROOT),
                           capture_output=True, text=True, timeout=15)
        if p.returncode == 0:
            return set(x for x in p.stdout.split('\n') if x)
    except Exception:
        pass
    return set()


def scan_file_health(tracked: set[str] | None = None):
    """一轮文件卫生（轻量、全量），返回 findings 列表。"""
    if tracked is None:
        tracked = _git_tracked()
    out: list[dict] = []

    def _tracked_bump(rel):
        return rel in tracked

    def add(rule_id, sev0, abs_path: Path, line, metric, thr, ctx, is_tracked=None):
        rel = _rel_project(abs_path)
        sev = sev0
        if is_tracked is True:
            sev = {('MED',): 'HIGH'}.get((sev0,), sev0)
        elif is_tracked is False:
            if sev0 == 'MED':
                sev = 'LOW'
        out.append(_mk(rule_id, sev, rel, line, '', metric, thr, ctx,
                       {'tracked': 1 if is_tracked else 0}))

    # 1) 项目根一层散落
    try:
        for entry in sorted(os.listdir(PROJECT_ROOT)):
            full = PROJECT_ROOT / entry
            rel = _rel_project(full)
            if entry.startswith('.') or entry in ROOT_KEEP_DIRS or entry in ROOT_KEEP_FILES:
                continue
            if entry in ROOT_EXTRA_SKIP:
                continue
            low = entry.lower()
            if low in _VCS_ALLOW_EXACT or low.startswith(_VCS_ALLOW_PREFIX):
                continue
            is_dir = os.path.isdir(full)
            is_tr = _tracked_bump(rel)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if TEMP_NAME_RE.match(entry) or entry == '.DS_Store':
                add('TEMP_LIKE', 'LOW', full, 1, 0, 0, 'temp_' + entry.lower(), is_tr)
                continue
            if not is_dir and st.st_size > BIG_LOOSE_BYTES:
                add('BIG_LOOSE_FILE', 'INFO', full, 1, st.st_size, BIG_LOOSE_BYTES,
                    'big_' + entry.lower(), is_tr)
            if BAD_NAME_RE.search(entry):
                add('BAD_NAME', 'LOW', full, 1, 0, 0, 'name_' + entry.lower()[:40], is_tr)
            add('ROOT_LOOSE', 'MED', full, 1, 0, 0,
                ('dir_' if is_dir else 'file_') + entry.lower()[:60], is_tr)
    except Exception:
        pass

    # 2) flask-app 标准目录职责错放
    for dirname, allow in DIR_ALLOW_EXT.items():
        d = BASE / dirname
        if not d.is_dir():
            continue
        for f in d.rglob('*'):
            if not f.is_file():
                continue
            rel = f.relative_to(BASE).as_posix()
            if _is_excluded(rel):
                continue
            sub_parts = rel.split('/')[1:]          # 去掉顶层目录名
            if any(p in RESOURCE_DIRS for p in sub_parts[:-1]):
                continue                            # 资源子目录不做后缀职责校验
            ext = f.suffix.lower()
            if not ext:
                continue                            # 无扩展名(可执行/特殊配置)不判错放
            tr = _tracked_bump(_rel_project(f))
            if ext in _BACKUP_EXT:
                add('TEMP_LIKE', 'LOW', f, 1, 0, 0, 'temp_' + f.name.lower()[:40], tr)
                continue
            if ext not in allow:
                add('DIR_MISPLACE', 'MED', f, 1, 0, 0,
                    f'misplace_{dirname}_{ext}', tr)
                if BAD_NAME_RE.search(f.name):
                    add('BAD_NAME', 'LOW', f, 1, 0, 0,
                        'name_' + f.name.lower()[:40], tr)
    sd = BASE / 'static'
    if sd.is_dir():
        for f in sd.rglob('*'):
            if not f.is_file():
                continue
            rel = f.relative_to(BASE).as_posix()
            if _is_excluded(rel):
                continue
            ext = f.suffix.lower()
            if ext and ext not in STATIC_EXT:
                tr = _tracked_bump(_rel_project(f))
                add('DIR_MISPLACE', 'MED', f, 1, 0, 0,
                    f'misplace_static_{ext}', tr)

    # 3) flask-app 根层临时文件（浅层）
    for f in BASE.glob('*'):
        if f.is_file() and (TEMP_NAME_RE.match(f.name) or f.name == '.DS_Store'):
            add('TEMP_LIKE', 'LOW', f, 1, 0, 0, 'temp_' + f.name.lower(),
                _tracked_bump(_rel_project(f)))

    out.sort(key=lambda x: (_sev_rank(x['severity']), x['file']))
    return out


# ════════════════════════════════════════════════════════════════════
# 指纹 + 落库
# ════════════════════════════════════════════════════════════════════
def _fingerprint(category: str, f: dict) -> str:
    raw = '|'.join([category, f['rule_id'], f['file'], f.get('symbol', ''),
                    str(f.get('ctx', ''))[:80]])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]


def upsert_findings(findings: list[dict], category: str, sweep_id: str):
    """幂等落库。返回 (new_open, still_open)。"""
    if not findings:
        return 0, 0
    ts = _now()
    new_n = still_n = 0
    c = _conn()
    try:
        for f in findings:
            fp = _fingerprint(category, f)
            row = c.execute("SELECT finding_id,status FROM mt_hygiene_findings WHERE fingerprint=?",
                            (fp,)).fetchone()
            meta = dict(f.get('meta') or {})
            if row is None:
                c.execute("""INSERT INTO mt_hygiene_findings
                  (fingerprint,category,rule_id,severity,file_path,line,symbol,
                   metric_value,threshold_val,status,seen_count,first_seen_at,last_seen_at,
                   last_sweep_id,auto_fixed,meta_json)
                  VALUES(?,?,?,?,?,?,?,?,?,'OPEN',1,?,?,?,0,?)""",
                          (fp, category, f['rule_id'], f['severity'], f['file'], f['line'],
                           f.get('symbol'), f.get('metric'), f.get('threshold'),
                           ts, ts, sweep_id, json.dumps(meta, ensure_ascii=False)))
                new_n += 1
            else:
                fid, status = row
                reopen = 1 if status == 'FIXED' else 0
                c.execute("""UPDATE mt_hygiene_findings
                  SET seen_count=seen_count+1,last_seen_at=?,line=?,metric_value=?,
                      last_sweep_id=?, meta_json=?,
                      status=CASE WHEN status='FIXED' THEN 'OPEN' ELSE status END
                  WHERE finding_id=?""",
                          (ts, f['line'], f.get('metric'), sweep_id,
                           json.dumps(meta, ensure_ascii=False), fid))
                if reopen:
                    new_n += 1
                else:
                    still_n += 1
        c.commit()
    finally:
        c.close()
    return new_n, still_n


def close_stale(sweep_id: str, category: str) -> int:
    c = _conn()
    try:
        cur = c.execute("""UPDATE mt_hygiene_findings
            SET status='FIXED'
            WHERE category=? AND status IN('OPEN','ACK')
              AND (last_sweep_id IS NULL OR last_sweep_id!=?)""",
                        (category, sweep_id))
        c.commit()
        return cur.rowcount or 0
    finally:
        c.close()


# ════════════════════════════════════════════════════════════════════
# sweep 状态机（跨 tick 分批）
# ════════════════════════════════════════════════════════════════════
# 常驻 auto_loop 同进程跨 chunk 累积的 DUP 倒排
_RAM = {'sweep_id': None, 'dup_index': {}, 'dup_pairs': set()}


def _get_state(kind: str):
    c = _conn()
    try:
        return c.execute("SELECT phase,sweep_id,cursor_idx,total,sweep_started_at FROM "
                         "mt_hygiene_scan_state WHERE kind=?", (kind,)).fetchone()
    finally:
        c.close()


def _set_state(kind, phase, sweep_id, idx, total, started):
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_hygiene_scan_state(kind,phase,sweep_id,cursor_idx,total,sweep_started_at,updated_at)
          VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(kind) DO UPDATE SET phase=excluded.phase,sweep_id=excluded.sweep_id,
            cursor_idx=excluded.cursor_idx,total=excluded.total,sweep_started_at=excluded.sweep_started_at,
            updated_at=excluded.updated_at""",
                  (kind, phase, sweep_id, idx, total, started, _now()))
        c.commit()
    finally:
        c.close()


def _last_done_ts(kind: str):
    c = _conn()
    try:
        r = c.execute("SELECT finished_at FROM mt_hygiene_runs WHERE kind=? AND phase='done' "
                      "ORDER BY finished_at DESC LIMIT 1", (kind,)).fetchone()
        return r[0] if r else None
    finally:
        c.close()


def _write_run(run_id, kind, sweep_id, started, finished, dur, scanned, new, still,
               closed, fixed, promoted, chunk, phase, note=''):
    c = _conn()
    try:
        c.execute("""INSERT INTO mt_hygiene_runs(run_id,kind,sweep_id,started_at,finished_at,duration_s,
            scanned,new_open,still_open,auto_closed,auto_fixed,promoted,chunk,phase,note)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET finished_at=excluded.finished_at,duration_s=excluded.duration_s,
            scanned=excluded.scanned,new_open=excluded.new_open,still_open=excluded.still_open,
            auto_closed=excluded.auto_closed,auto_fixed=excluded.auto_fixed,promoted=excluded.promoted,
            chunk=excluded.chunk,phase=excluded.phase,note=excluded.note""",
                  (run_id, kind, sweep_id, started, finished, dur, scanned, new, still,
                   closed, fixed, promoted, chunk, phase, note))
        c.commit()
    finally:
        c.close()


def scan_code_chunk(force_new: bool = False):
    """跑一个代码扫描 chunk。返回结果 dict（phase=running/done/skipped）。"""
    ensure_tables()
    st = _get_state('code')
    files = list_code_files('all')
    total = len(files)
    t0 = time.time()

    if st and st[0] == 'running':
        sweep_id, idx, started = st[1], st[2] or 0, st[4]
        if _RAM['sweep_id'] != sweep_id:      # 进程重启：本 sweep DUP 索引重建（保守跳过该 sweep 的 DUP）
            _RAM['sweep_id'] = sweep_id
            _RAM['dup_index'] = {}
            _RAM['dup_pairs'] = set()
    else:
        if not force_new:
            last = _last_done_ts('code')
            if last:
                try:
                    age = time.time() - datetime.strptime(last, '%Y-%m-%d %H:%M:%S').timestamp()
                    if age < HYG_CODE_GAP_SEC:
                        return dict(skipped=True, phase='skipped', reason='gap',
                                    gap_left=int(HYG_CODE_GAP_SEC - age), scanned=0)
                except Exception:
                    pass
        sweep_id = 'SWEEP-CODE-' + datetime.now().strftime('%Y%m%d%H%M%S')
        idx = 0
        started = _now()
        _set_state('code', 'running', sweep_id, 0, total, started)
        _RAM['sweep_id'] = sweep_id
        _RAM['dup_index'] = {}
        _RAM['dup_pairs'] = set()

    run_id = sweep_id
    scanned = new_n = still_n = 0
    write_err = None
    deadline = t0 + BUDGET_SEC_PER_CHUNK
    while idx < total and scanned < BUDGET_FILES_PER_CHUNK and time.time() < deadline:
        rel = files[idx]
        abs_path = BASE / rel
        try:
            fs = analyze_code_file(rel, abs_path, _RAM['dup_index'], _RAM['dup_pairs'])
            a, b = upsert_findings(fs, 'CODE', sweep_id)
        except Exception as e:
            # OneDrive 大库 + 多守护并发, 写锁碰撞瞬时常见: 等 5s 原地重试一次。
            # 仍失败则游标停在该文件不前移 (下 tick 续扫), 且本轮禁止关单/修复/晋升,
            # 杜绝"没扫到→close_stale 误关"。
            msg = str(e)[:120]
            time.sleep(5)
            try:
                fs = analyze_code_file(rel, abs_path, _RAM['dup_index'], _RAM['dup_pairs'])
                a, b = upsert_findings(fs, 'CODE', sweep_id)
            except Exception as e2:
                print(f'[hygiene] write-park {rel}: {msg} | retry: {str(e2)[:120]}')
                write_err = msg
                break
        idx += 1
        new_n += a
        still_n += b
        scanned += 1

    finished_this = idx >= total and write_err is None
    _set_state('code', 'done' if finished_this else 'running', sweep_id, idx, total, started)

    # 汇总本 run（upsert 同一 run_id，累计计数取本轮新值的近似：用 runs 旧值累加）
    closed = fixed = promoted = 0
    phase = 'running'
    note = ''
    if finished_this:
        phase = 'done'
        closed = close_stale(sweep_id, 'CODE')
        if AUTO_FIX_SAFE:
            fixed = autofix_safe(AUTO_FIX_PER_LOOP)
        promoted = promote_high_to_pool(PROMOTE_PER_LOOP)
        note = 'sweep_complete'
        _feed('summary_success',
              f'代码卫生 sweep {sweep_id} 完成: 新发现 {new_n}, 仍存 {still_n}, '
              f'自动关闭 {closed}, 安全修复 {fixed}, 晋升 {promoted}')
    elif write_err:
        note = 'write_error_park'
    dur = round(time.time() - t0, 2)
    # 读取已累计 run 值并相加
    prev_scanned = prev_new = prev_still = 0
    c = _conn()
    try:
        r = c.execute("SELECT scanned,new_open,still_open,chunk FROM mt_hygiene_runs WHERE run_id=?",
                      (run_id,)).fetchone()
        if r:
            prev_scanned, prev_new, prev_still, _ = r
    finally:
        c.close()
    _write_run(run_id, 'code', sweep_id, started, _now() if finished_this else None, dur,
               prev_scanned + scanned, prev_new + new_n, prev_still + still_n,
               closed, fixed, promoted, (r[3] + 1) if r else 1, phase, note)
    return dict(skipped=False, phase=phase, sweep_id=sweep_id, scanned=scanned,
                new=new_n, open=still_n, cursor=idx, total=total,
                closed=closed, fixed=fixed, promoted=promoted,
                parked=bool(write_err))


def scan_file_round(force: bool = False):
    """一轮文件卫生（轻量，到点才跑）。"""
    ensure_tables()
    if not force:
        last = _last_done_ts('files')
        if last:
            try:
                age = time.time() - datetime.strptime(last, '%Y-%m-%d %H:%M:%S').timestamp()
                if age < HYG_FILE_GAP_SEC:
                    return dict(skipped=True, phase='skipped', reason='gap',
                                gap_left=int(HYG_FILE_GAP_SEC - age))
            except Exception:
                pass
    sweep_id = 'SWEEP-FILE-' + datetime.now().strftime('%Y%m%d%H%M%S')
    t0 = time.time()
    tracked = _git_tracked()
    fs = scan_file_health(tracked)
    new_n, still_n = upsert_findings(fs, 'FILE', sweep_id)
    closed = close_stale(sweep_id, 'FILE')
    dur = round(time.time() - t0, 2)
    _write_run(sweep_id, 'files', sweep_id, _now(), _now(), dur, 1, new_n, still_n,
               closed, 0, 0, 1, 'done', 'file_round')
    return dict(skipped=False, phase='done', sweep_id=sweep_id, findings=len(fs),
                new=new_n, open=still_n, closed=closed)


# ════════════════════════════════════════════════════════════════════
# 安全项自动修（仅尾空白/缺末换行/未用 import）
# ════════════════════════════════════════════════════════════════════
SAFE_RULES = ('TRAILING_WHITESPACE', 'MISSING_NEWLINE', 'UNUSED_IMPORT')


def _apply_fix(abs_path: Path, rule_id: str, line: int, symbol: str):
    import py_compile
    src = abs_path.read_text(encoding='utf-8', errors='replace')
    lines = src.split('\n')
    if rule_id == 'TRAILING_WHITESPACE':
        new = '\n'.join((ln.rstrip() if ln.strip() else ln) for ln in lines)
        if src.endswith('\n'):
            new += '\n'
    elif rule_id == 'MISSING_NEWLINE':
        new = src if src.endswith('\n') else src + '\n'
    elif rule_id == 'UNUSED_IMPORT':
        idx = line - 1
        if idx < 0 or idx >= len(lines):
            return False
        cur = lines[idx]
        if not re.match(r'\s*(import|from)\s', cur) or (cur.rstrip().endswith('(')):
            return False  # 多行括号导入不动
        indent = cur[:len(cur) - len(cur.lstrip())]
        lines[idx] = f'{indent}# [hygiene-auto] {cur.lstrip()}'
        new = '\n'.join(lines)
        if src.endswith('\n'):
            new += '\n'
    else:
        return False
    if new == src:
        return False
    tmp = abs_path.with_name(abs_path.name + '.hygiene.tmp')
    tmp.write_text(new, encoding='utf-8')
    try:
        py_compile.compile(str(tmp), doraise=True)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    os.replace(str(tmp), str(abs_path))
    return True


def autofix_safe(limit: int = AUTO_FIX_PER_LOOP) -> int:
    c = _conn()
    fixed = 0
    try:
        rows = c.execute("""SELECT finding_id,file_path,line,symbol,rule_id FROM mt_hygiene_findings
            WHERE category='CODE' AND status='OPEN' AND rule_id IN (?,?,?)
            ORDER BY severity, finding_id LIMIT ?""",
                         (*SAFE_RULES, limit)).fetchall()
    finally:
        c.close()
    for fid, fpath, line, symbol, rule_id in rows:
        abs_path = PROJECT_ROOT / fpath
        if not abs_path.exists() or abs_path.name == 'VERSION':
            continue
        try:
            ok = _apply_fix(abs_path, rule_id, line or 0, symbol or '')
        except Exception:
            ok = False
        c = _conn()
        try:
            if ok:
                c.execute("UPDATE mt_hygiene_findings SET status='FIXED',auto_fixed=1 WHERE finding_id=?",
                          (fid,))
                c.commit()
                fixed += 1
                _feed('summary_success', f'安全自动修复 {rule_id} {fpath}:{line}')
        finally:
            c.close()
    return fixed


# ════════════════════════════════════════════════════════════════════
# HIGH 晋升建议池（应用层判重 + 限额，绝不刷库）
# ════════════════════════════════════════════════════════════════════
def promote_high_to_pool(per_loop: int = PROMOTE_PER_LOOP) -> int:
    c = _conn()
    promoted = 0
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        n_today = c.execute("SELECT COUNT(*) FROM mt_ai_suggestion_pool WHERE source_name=? "
                            "AND created_at>=?", (SOURCE_NAME, today + ' 00:00:00')).fetchone()[0]
        if n_today >= PROMOTE_DAILY_MAX:
            return 0
        rows = c.execute("""SELECT finding_id,fingerprint,rule_id,file_path,line,symbol,
                metric_value,threshold_val,seen_count,COALESCE(meta_json,'{}')
            FROM mt_hygiene_findings
            WHERE category='CODE' AND severity='HIGH' AND status='OPEN' AND seen_count>=2
              AND COALESCE(json_extract(meta_json,'$.promoted'),0)=0
            ORDER BY seen_count DESC, finding_id LIMIT ?""", (per_loop,)).fetchall()
        for (fid, fp, rid, fpath, line, symbol, metric, thr, seen, meta_s) in rows:
            if n_today + promoted >= PROMOTE_DAILY_MAX:
                break
            flow_id = 'hygiene_' + fp[:12]
            dup = c.execute("SELECT 1 FROM mt_ai_suggestion_pool WHERE flow_id=? LIMIT 1",
                            (flow_id,)).fetchone()
            if dup:
                c.execute("UPDATE mt_hygiene_findings SET meta_json=json_set(COALESCE(meta_json,'{}'),'$.promoted',1) WHERE finding_id=?", (fid,))
                continue
            body = (f"## 屎山代码 {rid}\n\n**文件**: {fpath}:{line}\n**符号**: {symbol}\n"
                    f"**指标**: {metric} (阈值 {thr})\n**命中轮次**: {seen}\n\n"
                    f"建议: 该符号已连续命中 HIGH 卫生阈值，请评估重构（拆分/降复杂度/消重复）。")
            c.execute("""INSERT INTO mt_ai_suggestion_pool
              (source_type,source_name,suggestion_text,priority,status,feasibility_score,
               value_score,cost_score,risk_score,flow_id,meta_json,created_at)
              VALUES('CODE_HYGIENE',?,?,8,'PENDING',0.6,0.8,0.4,0.2,?,?,?)""",
                      (SOURCE_NAME, body, flow_id,
                       json.dumps({'rule_id': rid, 'file': fpath, 'line': line,
                                   'symbol': symbol, 'source': SOURCE_NAME}, ensure_ascii=False),
                       _now()))
            c.execute("UPDATE mt_hygiene_findings SET meta_json=json_set(COALESCE(meta_json,'{}'),'$.promoted',1) WHERE finding_id=?", (fid,))
            promoted += 1
        c.commit()
    finally:
        c.close()
    return promoted


# ════════════════════════════════════════════════════════════════════
# 脑库投喂 + 历史归档
# ════════════════════════════════════════════════════════════════════
def _feed(kind: str, content: str):
    try:
        ai_dir = str(BASE / 'ai_engines')
        if ai_dir not in sys.path:
            sys.path.insert(0, ai_dir)
        from mt_ir14_dev_flow import feed_brain
        feed_brain(ENGINE_FLOW_ID, kind, content)
    except Exception:
        pass


def archive_legacy_sniff() -> int:
    """把 auto_sniff_engine 历史 EVALUATED 噪音幂等归档为 DEFERRED（不删库）。"""
    c = _conn()
    try:
        cur = c.execute("""UPDATE mt_ai_suggestion_pool
            SET status='DEFERRED',
                meta_json=json_set(COALESCE(meta_json,'{}'),'$.archived_reason','sniff_dedup_legacy_20261012')
            WHERE source_name='auto_sniff_engine' AND status='EVALUATED'""")
        c.commit()
        return cur.rowcount or 0
    finally:
        c.close()


# ════════════════════════════════════════════════════════════════════
# auto_loop 接入点（每 tick 调用，内部自带节流）
# ════════════════════════════════════════════════════════════════════
def loop_code_tick() -> dict:
    try:
        return scan_code_chunk(force_new=False)
    except Exception as e:
        return dict(skipped=False, phase='error', error=str(e)[:200])


def loop_file_tick() -> dict:
    try:
        return scan_file_round(force=False)
    except Exception as e:
        return dict(skipped=False, phase='error', error=str(e)[:200])


def status() -> dict:
    c = _conn()
    try:
        by_status = {f'{cat}/{st}': n for cat, st, n in c.execute(
            "SELECT category,status,COUNT(*) FROM mt_hygiene_findings GROUP BY category,status").fetchall()}
        top_rules = c.execute("""SELECT rule_id,COUNT(*) n FROM mt_hygiene_findings
            WHERE status IN('OPEN','ACK') GROUP BY rule_id ORDER BY n DESC LIMIT 12""").fetchall()
        runs = c.execute("""SELECT kind,phase,started_at,finished_at,scanned,new_open,auto_closed,auto_fixed,promoted
            FROM mt_hygiene_runs ORDER BY started_at DESC LIMIT 8""").fetchall()
        return dict(by_status=by_status,
                    top_open_rules=[(r, n) for r, n in top_rules],
                    recent_runs=runs)
    finally:
        c.close()


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════
def _dry_run(limit: int, scope: str):
    files = list_code_files(scope)
    if limit:
        files = files[:limit]
    dup_index, dup_pairs = {}, set()
    print(f'[dry-run] scope={scope} files={len(files)} (不写库)')
    total = 0
    for rel in files:
        fs = analyze_code_file(rel, BASE / rel, dup_index, dup_pairs)
        if fs:
            total += len(fs)
            print(f'\n■ {rel}  ({len(fs)} 项)')
            for f in fs[:12]:
                print(f"  [{f['severity']:4s}] {f['rule_id']:18s} L{f['line']:<6} "
                      f"{f['symbol'][:30]:30s} metric={f['metric']}")
    print(f'\n[dry-run] 合计 {total} 项；文件卫生示例(前20):')
    for f in scan_file_health()[:20]:
        print(f"  [{f['severity']:4s}] {f['rule_id']:14s} {f['file']}")


def main():
    import argparse
    p = argparse.ArgumentParser(description='仙女座代码与文件卫生巡检引擎')
    p.add_argument('cmd', nargs='?', default='status',
                   choices=['dry-run', 'code', 'files', 'fix', 'promote', 'archive', 'status'])
    p.add_argument('--full', action='store_true', help='code: 循环跑到本 sweep 完成')
    p.add_argument('--limit', type=int, default=40)
    p.add_argument('--scope', default='all', choices=['all', 'andromeda'])
    args = p.parse_args()

    if args.cmd == 'dry-run':
        _dry_run(args.limit, args.scope)
    elif args.cmd == 'code':
        ensure_tables()
        while True:
            r = scan_code_chunk()
            print(json.dumps(r, ensure_ascii=False))
            if not args.full or r.get('phase') in ('done', 'skipped', 'error'):
                break
    elif args.cmd == 'files':
        ensure_tables()
        print(json.dumps(scan_file_round(force=True), ensure_ascii=False))
    elif args.cmd == 'fix':
        ensure_tables()
        print('auto_fixed =', autofix_safe(AUTO_FIX_PER_LOOP))
    elif args.cmd == 'promote':
        ensure_tables()
        print('promoted =', promote_high_to_pool(PROMOTE_PER_LOOP))
    elif args.cmd == 'archive':
        ensure_tables()
        print('archived =', archive_legacy_sniff())
    else:
        ensure_tables()
        print(json.dumps(status(), ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
