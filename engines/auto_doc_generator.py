#!/usr/bin/env python3
"""
自动文档生成器 AutoDocGenerator (v1.0)
========================================
Phase 1: SCAN     — AST parse engines/routes/blueprints + regex Flask routes + DB tables
Phase 2: HASH     — Compute stable SHA256 per section (iceberg/gobelin/andromeda)
Phase 3: COMPARE  — Compare with last run (stored in doc_manifest.json)
Phase 4: GENERATE — For changed sections only, regenerate into docs/ with markers
Phase 5: PERSIST  — Write manifest

CLI:
  python3 engines/auto_doc_generator.py [run|dry|force] [--system iceberg|gobelin|andromeda|all]
"""
from __future__ import annotations
import ast
import os
import re
import sys
import json
import hashlib
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

# ═══════════════════════════════════════════════════════════
# 常量与路径
# ═══════════════════════════════════════════════════════════

_DB_PATH = Path('/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db')
_FLASK_APP = Path(__file__).parent.parent
_REPO_ROOT = _FLASK_APP.parent  # MTSCOS_AI_Project
_DOCS_DIR = _FLASK_APP / 'docs'
_RUNTIME_DIR = _REPO_ROOT / '_runtime'
_MANIFEST_PATH = _RUNTIME_DIR / 'doc_manifest.json'

SYSTEM_MAP: Dict[str, Dict[str, Any]] = {
    'iceberg': {
        'label': '冰山 Iceberg',
        'patterns': [
            'iceberg', 'consciousness', 'pulse', 'threshold',
            'content_matrix', 'binding', 'five_self',
        ],
    },
    'gobelin': {
        'label': '古灵阁 Gobelin',
        'patterns': [
            'gobelin', 'shield', 'daily_pnl', 'sandbox',
            'trading', 'candidates', 'team', 'verdict',
        ],
    },
    'andromeda': {
        'label': '仙女座 Andromeda',
        'patterns': [
            'andromeda', 'autopilot', 'self_drive', 'eigenflux',
            'labor', 'collab', 'roundtable', 'neuron',
        ],
    },
}

MARKER_START = '<!-- AUTO-GENERATED-START:{section} -->'
MARKER_END = '<!-- AUTO-GENERATED-END:{section} -->'

# Flask 路由正则
ROUTE_PATTERNS = [
    # @bp.route('/path', methods=[...]) 或 @bp.route('/path')
    re.compile(r'@(\w+)\.route\s*\(\s*[\'\"]([^\'\"]+)[\'\"][^)]*\)', re.MULTILINE),
    # @bp.get('/path') / @bp.post('/path') ...
    re.compile(r'@(\w+)\.(get|post|put|delete|patch)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]', re.MULTILINE),
    # add_url_rule('/path', ...)
    re.compile(r'add_url_rule\s*\(\s*[\'\"]([^\'\"]+)[\'\"]', re.MULTILINE),
]


# ═══════════════════════════════════════════════════════════
# Phase 1: AST 扫描
# ═══════════════════════════════════════════════════════════

def _safe_read(path: Path) -> Optional[str]:
    """安全读取文件,处理编码/BOM"""
    for enc in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
    return None


def parse_python_file(path: Path) -> Optional[Dict[str, Any]]:
    """用 AST 解析单个 Python 文件"""
    source = _safe_read(path)
    if source is None:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None

    result = {
        'file': str(path.relative_to(_FLASK_APP)),
        'module_docstring': ast.get_docstring(tree) or '',
        'classes': [],
        'functions': [],
        'blueprints': [],  # (name, url_prefix)
    }

    for node in ast.walk(tree):
        # ── 类定义 ──
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        'name': item.name,
                        'args': _format_args(item),
                        'docstring': (ast.get_docstring(item) or '')[:120],
                        'async': isinstance(item, ast.AsyncFunctionDef),
                    })
            result['classes'].append({
                'name': node.name,
                'bases': [_get_name(b) for b in node.bases],
                'docstring': (ast.get_docstring(node) or '')[:200],
                'methods': methods,
                'async': any(isinstance(m, ast.AsyncFunctionDef) for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))),
            })

        # ── 顶层函数 ──
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(getattr(node, 'parent', None), ast.Module):
            result['functions'].append({
                'name': node.name,
                'args': _format_args(node),
                'docstring': (ast.get_docstring(node) or '')[:200],
                'async': isinstance(node, ast.AsyncFunctionDef),
            })

    # 手动提取顶层函数 (替代 parent hack)
    result['functions'] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result['functions'].append({
                'name': node.name,
                'args': _format_args(node),
                'docstring': (ast.get_docstring(node) or '')[:200],
                'async': isinstance(node, ast.AsyncFunctionDef),
            })

    # ── Flask Blueprint 检测 ──
    result['blueprints'] = _extract_blueprints(tree, source)

    return result


def _get_name(node) -> str:
    """从 AST 节点获取简单名字 (兼容 3.8-3.14)"""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # ast.Str 在 3.12 已移除,兼容旧版本
    try:
        import sys as _sys
        if _sys.version_info < (3, 12) and isinstance(node, getattr(ast, 'Str', object)):
            return node.s
    except Exception:
        pass
    return ast.unparse(node) if hasattr(ast, 'unparse') else str(node)


def _is_ast_str(node) -> bool:
    """判断 AST 节点是否为字符串常量"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    try:
        if isinstance(node, getattr(ast, 'Str', type(None))):
            return True
    except Exception:
        pass
    return False


def _ast_str_value(node) -> Optional[str]:
    """从 AST 字符串节点取值"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    try:
        if isinstance(node, getattr(ast, 'Str', type(None))):
            return node.s
    except Exception:
        pass
    return None


def _format_args(func_node) -> str:
    """格式化函数签名"""
    args = []
    for a in func_node.args.args:
        args.append(a.arg)
    if func_node.args.vararg:
        args.append(f'*{func_node.args.vararg.arg}')
    if func_node.args.kwarg:
        args.append(f'**{func_node.args.kwarg.arg}')
    return ', '.join(args)


def _extract_blueprints(tree, source) -> List[Tuple[str, Optional[str]]]:
    """检测 Flask Blueprint 实例 + url_prefix"""
    bps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    if isinstance(call.func, ast.Name) and call.func.id == 'Blueprint':
                        # 变量名
                        bp_name = None
                        for tgt in node.targets:
                            if isinstance(tgt, ast.Name):
                                bp_name = tgt.id
                        # url_prefix
                        prefix = None
                        for kw in call.keywords:
                            if kw.arg == 'url_prefix':
                                v = _ast_str_value(kw.value)
                                if v is not None:
                                    prefix = v
                        if bp_name:
                            bps.append((bp_name, prefix))
                        break
    return bps


# ═══════════════════════════════════════════════════════════
# Phase 1b: Flask 路由正则提取
# ═══════════════════════════════════════════════════════════

def extract_flask_routes(path: Path) -> List[Dict[str, Any]]:
    """从文件中用正则提取所有 Flask 路由"""
    source = _safe_read(path)
    if source is None:
        return []

    routes = []
    seen = set()

    # Pattern 1: @bp.route('/path', methods=[...])
    for m in ROUTE_PATTERNS[0].finditer(source):
        bp, url = m.group(1), m.group(2)
        key = (bp, url)
        if key not in seen:
            seen.add(key)
            routes.append({
                'blueprint': bp,
                'url': url,
                'method': 'ANY',
                'file': str(path.relative_to(_FLASK_APP)),
            })

    # Pattern 2: @bp.get/post/...('/path')
    for m in ROUTE_PATTERNS[1].finditer(source):
        bp, method, url = m.group(1), m.group(2).upper(), m.group(3)
        key = (bp, url, method)
        if key not in seen:
            seen.add(key)
            routes.append({
                'blueprint': bp,
                'url': url,
                'method': method,
                'file': str(path.relative_to(_FLASK_APP)),
            })

    # Pattern 3: add_url_rule('/path', ...)
    for m in ROUTE_PATTERNS[2].finditer(source):
        url = m.group(1)
        key = ('add_url_rule', url)
        if key not in seen:
            seen.add(key)
            routes.append({
                'blueprint': '',
                'url': url,
                'method': 'ANY',
                'file': str(path.relative_to(_FLASK_APP)),
            })

    # 尝试找紧跟路由装饰器的函数名和 docstring
    for r in routes:
        func_name, doc = _find_route_handler(source, r['url'], r['file'])
        r['handler'] = func_name
        r['desc'] = doc

    return routes


def _find_route_handler(source: str, url: str, file_hint: str) -> Tuple[str, str]:
    """在路由行后面找函数定义和 docstring"""
    # 简化策略: 找 @...route... 或 @...get... 等后面的 def xxx
    escaped_url = re.escape(url).replace(r'\/', '/')
    # 匹配装饰器行 + 后续 def
    pattern = rf'@[\w\.]*route[\s\S]{{0,200}}{escaped_url}[\s\S]{{0,200}}?\n\s*(?:async\s+)?def\s+(\w+)'
    m = re.search(pattern, source)
    if not m:
        # 更宽松: 匹配带方法的装饰器
        pattern2 = rf'@\w+\.(?:get|post|put|delete|patch)\s*\(\s*[\'"]{escaped_url}[\'"][\s\S]{{0,100}}?\n\s*(?:async\s+)?def\s+(\w+)'
        m = re.search(pattern2, source)
    if m:
        func_name = m.group(1)
        # 找紧随其后的 docstring
        func_match = re.search(rf'def\s+{re.escape(func_name)}\s*\([^)]*\)\s*(?:->[^{{]*?)?\s*:\s*\n\s*"""([\s\S]*?)"""', source)
        doc = (func_match.group(1).strip()[:150] if func_match else '')
        return func_name, doc
    return '', ''


# ═══════════════════════════════════════════════════════════
# DB 表扫描
# ═══════════════════════════════════════════════════════════

def scan_db_tables() -> List[Dict[str, Any]]:
    """扫描 app.db 中所有 mt_ 表"""
    if not _DB_PATH.exists():
        print(f'  [!] DB not found at {_DB_PATH}')
        return []

    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    except Exception as e:
        print(f'  [!] DB connect failed: {e}')
        return []

    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mt_%' ORDER BY name")
    table_names = [r[0] for r in cur.fetchall()]

    tables = []
    for tname in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{tname}"')
            row_count = cur.fetchone()[0]
        except sqlite3.Error:
            row_count = -1

        # 列信息
        cur.execute(f'PRAGMA table_info("{tname}")')
        cols = []
        for cinfo in cur.fetchall():
            # (cid, name, type, notnull, dflt_value, pk)
            cols.append({
                'cid': cinfo[0],
                'name': cinfo[1],
                'type': cinfo[2] or '',
                'notnull': bool(cinfo[3]),
                'pk': cinfo[5],
            })

        # FK 信息
        fks = []
        cur.execute(f'PRAGMA foreign_key_list("{tname}")')
        for fk in cur.fetchall():
            fks.append({
                'from_col': fk[3],
                'to_table': fk[2],
                'to_col': fk[4],
            })

        tables.append({
            'name': tname,
            'row_count': row_count,
            'columns': cols,
            'foreign_keys': fks,
        })

    conn.close()
    return tables


def classify_table(table_name: str) -> str:
    """根据表名关键词归类到系统"""
    name_lower = table_name.lower()
    for sys_key, info in SYSTEM_MAP.items():
        for pat in info['patterns']:
            if pat.lower() in name_lower:
                return sys_key
    # 默认归类: 通过中间关键词
    # center/consciousness/pulse/threshold → iceberg
    if any(k in name_lower for k in ['center', 'consciousness', 'pulse', 'threshold', 'iceberg', 'content', 'five_self', 'binding']):
        return 'iceberg'
    # shield/pnl/sandbox/trading → gobelin
    if any(k in name_lower for k in ['shield', 'pnl', 'sandbox', 'trading', 'gobelin', 'candidate', 'verdict']):
        return 'gobelin'
    # autopilot/eigenflux/collab/roundtable/neuron → andromeda
    if any(k in name_lower for k in ['autopilot', 'eigenflux', 'collab', 'roundtable', 'neuron', 'andromeda', 'self_drive', 'labor', 'wflow', 'approval', 'team_collab', 'proposal', 'investigation', 'hall']):
        return 'andromeda'
    # 默认放 andromeda (最大系统)
    return 'andromeda'


# ═══════════════════════════════════════════════════════════
# 文件发现
# ═══════════════════════════════════════════════════════════

def discover_python_files() -> List[Path]:
    """发现 flask-app 下所有需要扫描的 Python 文件"""
    roots = [
        _FLASK_APP / 'engines',
        _FLASK_APP / 'blueprints',
        _FLASK_APP / 'routes',
    ]
    files = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob('*.py'):
            # 跳过缓存、备份、auto_repair、inspect_bak 等
            name = p.name
            if any(skip in name for skip in [
                '__pycache__', '.bak', '.backup', '.syncbak', 'auto_repair_backup',
                '.inspect_bak', '.bak_', '_bak', '.orig',
            ]):
                continue
            # 跳过根目录顶层的非系统文件 (仅 engines/blueprints/routes 子树)
            files.append(p)
    return files


# ═══════════════════════════════════════════════════════════
# Phase 2: 系统级扫描与哈希
# ═══════════════════════════════════════════════════════════

def classify_file(file_path: Path) -> str:
    """根据文件名归类到系统"""
    name_lower = file_path.name.lower()
    rel_path = str(file_path.relative_to(_FLASK_APP)).lower()
    combined = name_lower + ' ' + rel_path

    for sys_key, info in SYSTEM_MAP.items():
        for pat in info['patterns']:
            if pat.lower() in combined:
                return sys_key
    # 额外规则
    if 'iceberg' in combined:
        return 'iceberg'
    if 'gobelin' in combined:
        return 'gobelin'
    if 'andromeda' in combined:
        return 'andromeda'
    if 'collab_bus' in combined or 'eigenflux' in combined:
        return 'andromeda'
    # 默认不归类 (可能是基础设施文件)
    return ''


def build_system_scan(system_key: str, all_files: List[Path], all_tables: List[Dict]) -> Dict[str, Any]:
    """构建单个系统的完整扫描结果"""
    files_info = []
    routes_info = []
    tables_info = []

    for f in all_files:
        sys_of_file = classify_file(f)
        if sys_of_file != system_key:
            continue
        info = parse_python_file(f)
        if info is None:
            continue
        files_info.append(info)
        # 同时提取路由
        routes = extract_flask_routes(f)
        # 将路由的 blueprint 归类到对应系统
        for r in routes:
            r_sys = _classify_blueprint(r['blueprint'])
            if r_sys == system_key or (not r_sys and system_key == 'andromeda'):
                routes_info.append(r)

    for t in all_tables:
        if classify_table(t['name']) == system_key:
            tables_info.append(t)

    return {
        'system': system_key,
        'files': files_info,
        'routes': routes_info,
        'tables': tables_info,
    }


def _classify_blueprint(bp_name: str) -> str:
    """根据蓝图名归类"""
    if not bp_name:
        return ''
    lower = bp_name.lower()
    for sys_key, info in SYSTEM_MAP.items():
        for pat in info['patterns']:
            if pat.lower() in lower:
                return sys_key
    if 'iceberg' in lower:
        return 'iceberg'
    if 'gobelin' in lower or 'shield' in lower:
        return 'gobelin'
    if 'andromeda' in lower or 'eigenflux' in lower or 'collab' in lower:
        return 'andromeda'
    return ''


def compute_system_hash(scan_result: Dict[str, Any]) -> str:
    """计算系统扫描结果的 SHA256

    注意: DB row_count 不纳入 hash (活系统数据变化不应触发文档重生)
    只用稳定的 schema + 文件 AST + 路由正则结果。
    """
    # 构建稳定快照 (排除 row_count)
    stable_tables = []
    for t in scan_result.get('tables', []):
        stable_tables.append({
            'name': t['name'],
            'columns': [{'name': c['name'], 'type': c['type'], 'pk': c['pk']} for c in t['columns']],
            'foreign_keys': t['foreign_keys'],
        })

    stable_files = []
    for f in scan_result.get('files', []):
        stable_files.append({
            'file': f['file'],
            'module_docstring': f['module_docstring'][:200],
            'classes': [{'name': c['name'], 'bases': c['bases'], 'methods': [m['name'] for m in c['methods'][:5]]} for c in f['classes']],
            'functions': [{'name': func['name'], 'args': func['args']} for func in f['functions'][:100]],
        })

    stable_routes = [
        {'blueprint': r.get('blueprint',''), 'url': r.get('url',''), 'method': r.get('method','')}
        for r in scan_result.get('routes', [])
    ]

    stable_payload = {
        'system': scan_result.get('system'),
        'tables': stable_tables,
        'files': stable_files,
        'routes': stable_routes,
    }

    payload = json.dumps(stable_payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# ═══════════════════════════════════════════════════════════
# Phase 4: 文档生成
# ═══════════════════════════════════════════════════════════

def generate_system_doc(system_key: str, scan_result: Dict[str, Any], system_hash: str) -> str:
    """生成单个系统的完整 markdown 文档"""
    label = SYSTEM_MAP[system_key]['label']
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    files = scan_result['files']
    routes = scan_result['routes']
    tables = scan_result['tables']

    # 1. 概述
    overview = _gen_overview(system_key, files)

    # 2. ASCII 架构图
    arch = _gen_arch_diagram(system_key, files, tables, routes)

    # 3. API 端点表
    api = _gen_api_table(routes)

    # 4. 数据库表文档
    tables_md = _gen_tables_doc(tables)

    # 5. 引擎函数清单
    functions_md = _gen_functions_doc(files)

    # 6. 依赖关系
    deps = _gen_deps(system_key, scan_result)

    src_paths = _collect_source_paths(system_key)

    return f"""# {label} 系统说明

> 自动生成时间: {now_str}
> 系统哈希: {system_hash[:16]}... (变更时更新)
> 源码路径: {', '.join(src_paths)}

## 1. 系统概述
{MARKER_START.format(section='overview')}
{overview}
{MARKER_END.format(section='overview')}

## 2. 架构图 (ASCII)
{MARKER_START.format(section='arch')}
{arch}
{MARKER_END.format(section='arch')}

## 3. API 端点
{MARKER_START.format(section='api')}
{api}
{MARKER_END.format(section='api')}

## 4. 数据库表
{MARKER_START.format(section='tables')}
{tables_md}
{MARKER_END.format(section='tables')}

## 5. 引擎函数清单
{MARKER_START.format(section='functions')}
{functions_md}
{MARKER_END.format(section='functions')}

## 6. 依赖关系
{MARKER_START.format(section='deps')}
{deps}
{MARKER_END.format(section='deps')}
"""


def _collect_source_paths(system_key: str) -> List[str]:
    """收集源码路径"""
    paths = []
    for root in ['engines', 'routes', 'blueprints']:
        d = _FLASK_APP / root
        if d.exists():
            matches = []
            for p in d.rglob(f'{system_key}*.py'):
                matches.append(str(p.relative_to(_FLASK_APP)))
            # 还有包含子串的
            for p in d.rglob('*.py'):
                if system_key in p.name.lower() and p.name.startswith(system_key):
                    rel = str(p.relative_to(_FLASK_APP))
                    if rel not in matches:
                        matches.append(rel)
            paths.extend(matches)
    if not paths:
        paths = [f'engines/{system_key}*.py', f'routes/{system_key}*.py', f'blueprints/{system_key}*.py']
    return paths[:5]


def _gen_overview(system_key: str, files: List[Dict]) -> str:
    """系统概述"""
    label = SYSTEM_MAP[system_key]['label']
    docstrings = [f['module_docstring'] for f in files if f.get('module_docstring')]
    if docstrings:
        # 用最长的 docstring 作为主描述
        main_doc = max(docstrings, key=len)[:400]
        lines = main_doc.strip().split('\n')
        # 取前 15 行
        overview_text = '\n'.join(lines[:15])
    else:
        overview_text = f'{label} 系统 — 核心引擎集合,负责特定领域的业务逻辑与自动化。'

    class_count = sum(len(f.get('classes', [])) for f in files)
    func_count = sum(len(f.get('functions', [])) for f in files)
    return f"{overview_text}\n\n**模块数**: {len(files)} | **类**: {class_count} | **顶层函数**: {func_count}"


def _gen_arch_diagram(system_key: str, files: List[Dict], tables: List[Dict], routes: List[Dict]) -> str:
    """生成 ASCII 架构图"""
    lines = []

    # 收集入口
    entrypoints = sorted(set(f"{r.get('method','')} {r.get('url','')}" for r in routes[:8]))

    # 收集核心引擎
    engines = []
    for f in files[:10]:
        for cls in f.get('classes', []):
            methods_short = ', '.join(m['name'] for m in cls.get('methods', [])[:3])
            engines.append((cls['name'], f'{cls["name"]}({methods_short})'))

    # 收集表
    table_names = [t['name'] for t in tables[:6]]

    # 绘制
    lines.append(f'  ╔══════════════════════════════════════════════════════════╗')
    lines.append(f'  ║  {SYSTEM_MAP[system_key]["label"]:<48}║')
    lines.append(f'  ╠══════════════════════════════════════════════════════════╣')
    lines.append(f'  ║                                                          ║')

    # 入口
    if entrypoints:
        lines.append(f'  ║  ┌─ 入口 API ──────────────────────────────────────────┐  ║')
        for ep in entrypoints[:5]:
            lines.append(f'  ║  │  {ep[:54]:<54}│  ║')
        lines.append(f'  ║  └─────────────────────────────────────────────────────┘  ║')
        lines.append(f'  ║                          │                               ║')
        lines.append(f'  ║                          ▼                               ║')

    # 引擎
    if engines:
        lines.append(f'  ║  ┌─ 核心引擎 ──────────────────────────────────────────┐  ║')
        for ename, edesc in engines[:5]:
            lines.append(f'  ║  │  {ename:<54}│  ║')
        lines.append(f'  ║  └─────────────────────────────────────────────────────┘  ║')
        lines.append(f'  ║                          │                               ║')
        lines.append(f'  ║                          ▼                               ║')

    # DB 表
    if table_names:
        lines.append(f'  ║  ┌─ 数据库表 ──────────────────────────────────────────┐  ║')
        for tname in table_names[:6]:
            lines.append(f'  ║  │  {tname[:54]:<54}│  ║')
        lines.append(f'  ║  └─────────────────────────────────────────────────────┘  ║')

    lines.append(f'  ║                                                          ║')
    lines.append(f'  ╚══════════════════════════════════════════════════════════╝')
    return '\n'.join(lines)


def _gen_api_table(routes: List[Dict]) -> str:
    """生成 API 端点表格"""
    if not routes:
        return '_暂无 API 端点记录_'

    # 按蓝图+URL 排序去重
    seen = set()
    unique = []
    for r in sorted(routes, key=lambda x: (x.get('blueprint',''), x.get('url',''))):
        key = (r.get('blueprint',''), r.get('url',''))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    rows = ['| 蓝图 | 方法 | URL | 处理函数 | 说明 |', '|------|------|-----|----------|------|']
    for r in unique[:80]:
        bp = r.get('blueprint', '')[:12]
        method = r.get('method', '')[:6]
        url = r.get('url', '')[:40]
        handler = r.get('handler', '')[:20]
        desc = r.get('desc', '')[:40].replace('|', '/').replace('\n', ' ')
        rows.append(f'| {bp} | {method} | {url} | {handler} | {desc} |')

    if len(unique) > 80:
        rows.append(f'\n_（共 {len(unique)} 个端点,仅展示前 80 个）_')
    return '\n'.join(rows)


def _gen_tables_doc(tables: List[Dict]) -> str:
    """生成数据库表文档"""
    if not tables:
        return '_此系统暂无 mt_ 前缀数据库表_'

    sections = []
    for t in sorted(tables, key=lambda x: x['name']):
        col_rows = ['| 列 | 类型 | PK | 可空 |', '|----|------|:--:|:----:|']
        for col in t['columns'][:20]:
            pk_mark = '✓' if col.get('pk') else ''
            nullable = '是' if not col.get('notnull') else '否'
            col_rows.append(f'| {col["name"][:24]} | {col["type"][:10]} | {pk_mark} | {nullable} |')

        fk_lines = ''
        if t['foreign_keys']:
            fk_rows = ['\n**外键:**', '| 本地列 | → 目标表 | 目标列 |', '|--------|---------|--------|']
            for fk in t['foreign_keys'][:10]:
                fk_rows.append(f'| {fk["from_col"]} | {fk["to_table"]} | {fk["to_col"]} |')
            fk_lines = '\n'.join(fk_rows)

        sections.append(f"### {t['name']} ({t['row_count']:,} 行)\n" + '\n'.join(col_rows) + fk_lines)

    return '\n\n'.join(sections)


def _gen_functions_doc(files: List[Dict]) -> str:
    """生成引擎函数清单"""
    if not files:
        return '_未扫描到引擎模块_'

    rows = ['| 文件 | 类/函数 | 类型 | 参数 | 说明 |', '|------|---------|------|------|------|']

    for f in sorted(files, key=lambda x: x['file']):
        fname = f['file'].split('/')[-1]  # 简化文件名显示

        for cls in f.get('classes', []):
            rows.append(
                f'| {fname[:24]} | **class {cls["name"][:24]}** | 类 | | {(cls.get("docstring") or "")[:40]} |'
            )
            for m in cls.get('methods', [])[:15]:
                async_mark = 'async ' if m.get('async') else ''
                rows.append(
                    f'| | ↳ {async_mark}def {m["name"][:24]} | 方法 | {m.get("args","")[:30]} | {(m.get("docstring") or "")[:40]} |'
                )

        for func in f.get('functions', []):
            async_mark = 'async ' if func.get('async') else ''
            rows.append(
                f'| {fname[:24]} | {async_mark}def {func["name"][:24]} | 函数 | {func.get("args","")[:30]} | {(func.get("docstring") or "")[:40]} |'
            )

    return '\n'.join(rows)


def _gen_deps(system_key: str, scan_result: Dict[str, Any]) -> str:
    """生成依赖关系说明"""
    deps_map = {
        'iceberg': [
            '冰山 ← 古灵阁 (通过 mt_collab_bus_events 接收交易裁决广播)',
            '冰山 → 仙女座 (触发 autopilot_v2 S5 广播,驱动仙女座进化)',
            '冰山 ← 仙女座 (andromeda_workflow_engine 的自我修正回写)',
            '冰山 → mt_iceberg_consciousness_runs (意识脉冲留痕)',
            '冰山 → mt_ai_brain_feed_log (脑库投喂)',
        ],
        'gobelin': [
            '古灵阁 ← 冰山 (通过 collab_bus 接收阈值异常警报)',
            '古灵阁 → 冰山 (交易裁决结果广播给五自系统)',
            '古灵阁 → mt_collab_bus_events (团队协作总线事件)',
            '古灵阁 → mt_sandbox_tick_log (沙盘心跳)',
            '古灵阁 ← mt_asset_transactions (资产流水)',
        ],
        'andromeda': [
            '仙女座 ← 冰山 (接收意识脉冲作为进化触发器)',
            '仙女座 → 冰山 (自我修正能力驱动冰山阈值自动调节)',
            '仙女座 ← 古灵阁 (collab_bus 协作总线消息)',
            '仙女座 → mt_collab_bus_events (发布协作事件)',
            '仙女座 → mt_andromeda_workflow_runs (工作流执行记录)',
            '仙女座 ← mt_collab_bus_subscribers (订阅协作总线)',
        ],
    }
    deps = deps_map.get(system_key, ['—'])
    file_count = len(scan_result.get('files', []))
    table_count = len(scan_result.get('tables', []))
    route_count = len(scan_result.get('routes', []))
    extra = f"\n**扫描统计**: {file_count} 模块 | {table_count} 表 | {route_count} 路由"

    return '\n'.join(f'- {d}' for d in deps) + extra


# ═══════════════════════════════════════════════════════════
# Marker-based 文档替换
# ═══════════════════════════════════════════════════════════

def replace_section(content: str, section_id: str, new_content: str) -> str:
    """在文档中替换指定 marker 之间的内容,保留手写部分"""
    start = MARKER_START.format(section=section_id)
    end = MARKER_END.format(section=section_id)

    if start in content and end in content:
        pattern = re.escape(start) + r'.*?' + re.escape(end)
        replacement = start + '\n' + new_content.rstrip() + '\n' + end
        return re.sub(pattern, replacement, content, flags=re.DOTALL)
    else:
        # 没有 marker → 追加新 section (首次创建文件时不会走到这里,但安全处理)
        return content + f'\n\n## {section_id}\n{start}\n{new_content}\n{end}\n'


# ═══════════════════════════════════════════════════════════
# README + API_REFERENCE 生成
# ═══════════════════════════════════════════════════════════

def generate_readme(system_hashes: Dict[str, str], last_run: str) -> str:
    """生成 docs/README.md"""
    links = []
    for sk in SYSTEM_MAP:
        label = SYSTEM_MAP[sk]['label']
        h = system_hashes.get(sk, '')[:16]
        links.append(f'- [{label}]({sk}.md) — hash `{h}...`')

    return f"""# MTSCOS 自动文档索引

> 自动生成时间: {last_run}
> 扫描范围: `flask-app/engines/*`, `flask-app/blueprints/*`, `flask-app/routes/*`, `flask-app/database/app.db`

## 系统文档

{chr(10).join(links)}

## API 总览

- [全部 Flask 端点 API_REFERENCE.md](API_REFERENCE.md)

## 变更机制

- 使用 SHA256 哈希检测变更,未变更系统跳过生成
- 所有生成内容包裹在 `<!-- AUTO-GENERATED-START:xxx -->` / `<!-- AUTO-GENERATED-END:xxx -->` marker 中
- marker 之外的手写内容永久保留

## 运行

```bash
# 首次全量生成
python3 engines/auto_doc_generator.py force

# 后续按需更新
python3 engines/auto_doc_generator.py run

# 预演 (不写文件)
python3 engines/auto_doc_generator.py dry
```
"""


def generate_api_reference(all_scans: Dict[str, Dict]) -> str:
    """生成 docs/API_REFERENCE.md — 所有 Flask 端点"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 按蓝图前缀分组
    all_routes = []
    for sys_key, scan in all_scans.items():
        for r in scan.get('routes', []):
            r['_system'] = sys_key
            all_routes.append(r)

    # 额外: 从根目录顶层文件也提取路由
    for top_file in list(_FLASK_APP.glob('*.py'))[:20]:
        routes = extract_flask_routes(top_file)
        for r in routes:
            r['_system'] = 'top-level'
            all_routes.append(r)

    # 按蓝图前缀分组
    by_bp = defaultdict(list)
    for r in all_routes:
        bp = r.get('blueprint', 'app') or 'app'
        by_bp[bp].append(r)

    sections = []
    total = 0

    for bp, routes in sorted(by_bp.items()):
        # 去重
        seen = set()
        unique = []
        for r in sorted(routes, key=lambda x: (x.get('method',''), x.get('url',''))):
            key = (r.get('url',''), r.get('method',''))
            if key not in seen:
                seen.add(key)
                unique.append(r)

        total += len(unique)
        section = [f"## Blueprint: `{bp}`", '',
                   '| 方法 | URL | 处理函数 | 所属系统 |',
                   '|------|-----|----------|----------|']
        for r in unique:
            method = r.get('method', 'ANY')[:6]
            url = r.get('url', '')[:50]
            handler = r.get('handler', '')[:24]
            sys_label = SYSTEM_MAP.get(r.get('_system',''), {}).get('label', r.get('_system',''))[:16]
            section.append(f'| {method} | {url} | {handler} | {sys_label} |')
        section.append(f'\n_{len(unique)} 个端点_')
        sections.append('\n'.join(section))

    header = f"""# MTSCOS Flask API 总览

> 自动生成时间: {now_str}
> 共 **{total}** 个端点,按 Blueprint 分组

"""
    return header + '\n\n'.join(sections)


# ═══════════════════════════════════════════════════════════
# Phase 3-5: Manifest 管理
# ═══════════════════════════════════════════════════════════

def load_manifest() -> Dict:
    """加载上次运行的 manifest"""
    if _MANIFEST_PATH.exists():
        try:
            return json.loads(_MANIFEST_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_manifest(manifest: Dict) -> None:
    """保存 manifest"""
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

class AutoDocGenerator:
    def __init__(self, db_path: Path = _DB_PATH, repo_root: Path = _REPO_ROOT):
        self.db_path = db_path
        self.repo_root = repo_root
        self.docs_dir = _FLASK_APP / 'docs'

    def run(self, dry_run: bool = False, force: bool = False, system: str = 'all') -> None:
        """主运行流程"""
        print(f'\n{"="*60}')
        print(f' AutoDocGenerator — {"DRY RUN" if dry_run else "RUN"} {"(FORCE)" if force else ""}')
        print(f' Target DB: {self.db_path}')
        print(f' Docs Dir:  {self.docs_dir}')
        print(f' Manifest:  {_MANIFEST_PATH}')
        print(f'{"="*60}\n')

        # ── Phase 1: 扫描 ──
        print('[Phase 1] SCAN — 发现文件与解析...')
        all_py_files = discover_python_files()
        print(f'  Python files: {len(all_py_files)}')

        all_tables = scan_db_tables()
        print(f'  DB mt_ tables: {len(all_tables)}')

        systems_to_run = list(SYSTEM_MAP.keys()) if system == 'all' else [system]

        all_scans = {}
        for sk in systems_to_run:
            scan = build_system_scan(sk, all_py_files, all_tables)
            all_scans[sk] = scan
            h = compute_system_hash(scan)
            print(f'  [{SYSTEM_MAP[sk]["label"]}] files={len(scan["files"])} routes={len(scan["routes"])} tables={len(scan["tables"])} hash={h[:16]}...')

        # ── Phase 2-3: 哈希比较 ──
        print(f'\n[Phase 2-3] HASH & COMPARE...')
        old_manifest = load_manifest()
        new_manifest = {
            'generated_at': datetime.now().isoformat(),
            'systems': {},
        }

        changed_systems = []
        for sk in systems_to_run:
            current_hash = compute_system_hash(all_scans[sk])
            old_hash = old_manifest.get('systems', {}).get(sk, {}).get('hash', '')
            new_manifest['systems'][sk] = {
                'hash': current_hash,
                'files': len(all_scans[sk]['files']),
                'routes': len(all_scans[sk]['routes']),
                'tables': len(all_scans[sk]['tables']),
            }

            if force or not old_hash or old_hash != current_hash:
                status = 'FORCE' if force else ('NEW' if not old_hash else 'CHANGED')
                print(f'  [{sk}] {status} (old={old_hash[:16]} new={current_hash[:16]})')
                changed_systems.append(sk)
            else:
                print(f'  [{sk}] UNCHANGED — SKIP')

        if not changed_systems:
            print(f'\n✅ 所有系统无变更,跳过生成')
            print(f'\n[Phase 5] Persist manifest only...')
            save_manifest(new_manifest)
            return

        # ── Phase 4: 生成文档 ──
        print(f'\n[Phase 4] GENERATE — 生成 {len(changed_systems)} 个系统文档...')
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        for sk in changed_systems:
            scan = all_scans[sk]
            current_hash = compute_system_hash(scan)
            doc_content = generate_system_doc(sk, scan, current_hash)
            doc_path = self.docs_dir / f'{sk}.md'

            if dry_run:
                print(f'  [DRY] Would write {doc_path} ({len(doc_content)} chars)')
            else:
                doc_path.write_text(doc_content, encoding='utf-8')
                lines = doc_content.count('\n') + 1
                print(f'  ✏️  Written {doc_path} ({lines} lines)')

        # 额外生成 README 和 API_REFERENCE (总是写入,含 marker)
        print(f'\n[Phase 4b] Generating README.md + API_REFERENCE.md...')
        system_hashes = {sk: compute_system_hash(s) for sk, s in all_scans.items()}
        last_run = datetime.now().strftime('%Y-%m-%d %H:%M')

        readme_content = generate_readme(system_hashes, last_run)
        api_ref_content = generate_api_reference(all_scans)

        if dry_run:
            print(f'  [DRY] Would write README.md + API_REFERENCE.md')
        else:
            (self.docs_dir / 'README.md').write_text(readme_content, encoding='utf-8')
            (self.docs_dir / 'API_REFERENCE.md').write_text(api_ref_content, encoding='utf-8')
            print(f'  ✏️  Written README.md + API_REFERENCE.md')

        # ── Phase 5: 持久化 ──
        print(f'\n[Phase 5] PERSIST — 写入 manifest...')
        if not dry_run:
            save_manifest(new_manifest)
            print(f'  ✏️  Written {_MANIFEST_PATH}')
        else:
            print(f'  [DRY] Would write {_MANIFEST_PATH}')

        print(f'\n✅ 完成! 变更系统: {changed_systems}')


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='MTSCOS 自动文档生成器')
    p.add_argument('mode', nargs='?', default='run', choices=['run', 'dry', 'force'],
                   help='run=正常(diff), dry=预演(不写文件), force=强制全量')
    p.add_argument('--system', choices=['iceberg', 'gobelin', 'andromeda', 'all'], default='all',
                   help='目标系统 (默认 all)')
    args = p.parse_args()

    generator = AutoDocGenerator(_DB_PATH, _REPO_ROOT)

    if args.mode == 'dry':
        generator.run(dry_run=True, system=args.system)
    elif args.mode == 'force':
        generator.run(force=True, system=args.system)
    else:
        generator.run(system=args.system)
