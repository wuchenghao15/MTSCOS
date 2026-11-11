#!/usr/bin/env python3
"""mt代码审计守护引擎 — MTSCOS安全旅代码审计分队

职责:
  1. 遍历 flask-app/ 下 .py/.js/.html/.css/.sql 文件
  2. AST静态分析 (Python) — 检测 eval/exec/os.system/subprocess 等危险调用
  3. 多维度regex扫描 — 硬编码密钥、SQL注入模式、XSS、调试代码
  4. 批量持久化到 mt_code_audit_findings (UNIQUE防重复)
  5. 向 mt_lab_task_hall 自动派发 CRITICAL/HIGH 级别漏洞任务

由 hall-closure-loop §21 每6周期(30min) 调用 run_scan_once()
"""

import os
import re
import json
import ast
import sqlite3
import hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
BASE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SCAN_EXT = {'.py', '.js', '.html', '.css', '.sql', '.sh'}

# ---- Regex 规则 ----
REGEX_RULES = [
    # (规则ID, 描述, 类别, 严重度, 正则, 文件扩展名集)
    ('PY_EVAL', '使用eval函数', 'INJECTION', 'HIGH', re.compile(r'\beval\s*\(', re.I), {'.py'}),
    ('PY_EXEC', '使用exec函数', 'INJECTION', 'HIGH', re.compile(r'\bexec\s*\(', re.I), {'.py'}),
    ('PY_OS_SYSTEM', 'os.system命令执行', 'COMMAND_EXEC', 'CRITICAL', re.compile(r'os\.system\s*\(', re.I), {'.py'}),
    ('PY_SUBPROCESS', 'subprocess命令执行', 'COMMAND_EXEC', 'HIGH', re.compile(r'subprocess\.(Popen|call|check_output|check_call|run)\s*\(', re.I), {'.py'}),
    ('PY_PICKLE', 'pickle反序列化', 'INSECURE_DESER', 'CRITICAL', re.compile(r'pickle\.loads?\s*\(|cPickle\.loads?\s*\(', re.I), {'.py'}),
    ('PY_HARDCODE_PWD', '硬编码密码', 'HARDCODE_SECRET', 'HIGH', re.compile(r'password\s*=\s*["\'][^"\']{3,}["\']', re.I), {'.py'}),
    ('PY_HARDCODE_KEY', '硬编码API密钥', 'HARDCODE_SECRET', 'HIGH', re.compile(r'(api[_-]?key|secret[_-]?key|access[_-]?token)\s*=\s*["\'][A-Za-z0-9_\-]{10,}["\']', re.I), {'.py'}),
    ('PY_SQL_CONCAT', 'SQL字符串拼接(可能注入)', 'SQL_INJECTION', 'MEDIUM', re.compile(r'execute\s*\(\s*["\'].*%.*%["\']\s*%|execute\s*\(\s*f["\'].*\{.*\}.*["\']', re.I), {'.py'}),
    ('PY_DB_RAW', 'db.execute/connection.execute原生SQL', 'SQL_INJECTION', 'LOW', re.compile(r'(db|conn|connection|cursor)\.execute\s*\(\s*["\']', re.I), {'.py'}),
    ('PY_DEBUG_PRINT', '调试print语句', 'CODE_QUALITY', 'LOW', re.compile(r'\bprint\s*\(', re.I), {'.py'}),
    ('PY_DEBUG_MODE', 'Flask debug=True', 'CONFIG_SECURITY', 'MEDIUM', re.compile(r'debug\s*=\s*True', re.I), {'.py'}),
    ('PY_HOST_WILDCARD', 'host=0.0.0.0/host=*', 'CONFIG_SECURITY', 'MEDIUM', re.compile(r'host\s*=\s*["\']?(0\.0\.0\.0|\*|::)["\']?', re.I), {'.py'}),
    ('JS_EVAL', 'JS使用eval', 'INJECTION', 'HIGH', re.compile(r'\beval\s*\(', re.I), {'.js', '.html'}),
    ('JS_DOC_WRITE', 'document.write DOM注入', 'XSS', 'MEDIUM', re.compile(r'document\.write\s*\(', re.I), {'.js', '.html'}),
    ('JS_INNER_HTML', 'innerHTML直接赋值', 'XSS', 'MEDIUM', re.compile(r'\.innerHTML\s*=', re.I), {'.js'}),
    ('HTML_SCRIPT_TAG', 'HTML内联script', 'XSS', 'LOW', re.compile(r'<script(?![^>]*\bsrc=)[^>]*>', re.I), {'.html'}),
    ('CSS_URL_HTTP', 'CSS用http加载资源', 'HTTPS_MIX', 'LOW', re.compile(r'url\s*\(\s*["\']?http://', re.I), {'.css', '.html'}),
    ('GEN_TOKEN_BEARER', '源码中暴露Bearer token', 'HARDCODE_SECRET', 'HIGH', re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{20,}', re.I), {'.py', '.js', '.html'}),
]

# AST分析的危险调用列表
AST_DANGEROUS_CALLS = {
    'eval': ('PY_EVAL_AST', 'eval()函数调用', 'INJECTION', 'HIGH'),
    'exec': ('PY_EXEC_AST', 'exec()函数调用', 'INJECTION', 'HIGH'),
    'compile': ('PY_COMPILE_AST', 'compile()动态编译', 'INJECTION', 'MEDIUM'),
}
AST_DANGEROUS_ATTRS = {
    ('os', 'system'): ('PY_OS_SYSTEM_AST', 'os.system()命令执行', 'COMMAND_EXEC', 'CRITICAL'),
    ('os', 'popen'): ('PY_OS_POPEN_AST', 'os.popen()命令执行', 'COMMAND_EXEC', 'CRITICAL'),
    ('subprocess', 'Popen'): ('PY_SUBPROCESS_POPEN_AST', 'subprocess.Popen()', 'COMMAND_EXEC', 'CRITICAL'),
    ('subprocess', 'call'): ('PY_SUBPROCESS_CALL_AST', 'subprocess.call()', 'COMMAND_EXEC', 'HIGH'),
    ('subprocess', 'check_output'): ('PY_SUBPROCESS_CHECK_AST', 'subprocess.check_output()', 'COMMAND_EXEC', 'HIGH'),
    ('subprocess', 'run'): ('PY_SUBPROCESS_RUN_AST', 'subprocess.run()', 'COMMAND_EXEC', 'HIGH'),
    ('pickle', 'loads'): ('PY_PICKLE_LOADS_AST', 'pickle.loads()不安全反序列化', 'INSECURE_DESER', 'CRITICAL'),
    ('pickle', 'load'): ('PY_PICKLE_LOAD_AST', 'pickle.load()不安全反序列化', 'INSECURE_DESER', 'CRITICAL'),
    ('subprocess', 'run_shell'): ('PY_SHELL_RUN_AST', 'subprocess.run(shell=True)', 'COMMAND_EXEC', 'CRITICAL'),
}

# 严重度排序权重 (用于hall task priority)
SEV_TO_PRIORITY = {
    'CRITICAL': 'CRITICAL', 'HIGH': 'HIGH',
    'MEDIUM': 'NORMAL', 'LOW': 'LOW', 'INFO': 'LOW'
}
SEV_SCORE = {'CRITICAL': 10, 'HIGH': 8, 'MEDIUM': 5, 'LOW': 2, 'INFO': 1}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn


def _walk_files(root):
    """递归遍历目标目录，跳过 .git/__pycache__/node_modules/venv 等"""
    skip_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env', 'tmp', 'logs', '_runtime', 'static/node_modules'}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith('.')]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SCAN_EXT:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, BASE_ROOT)
                yield full, rel, ext


def _ast_scan_python(full_path):
    """对Python文件做AST分析，返回发现列表"""
    findings = []
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            src = f.read()
        tree = ast.parse(src, filename=full_path)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return findings

    rel_path = os.path.relpath(full_path, BASE_ROOT)

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node):
            # 直接调用: eval(...)
            if isinstance(node.func, ast.Name) and node.func.id in AST_DANGEROUS_CALLS:
                rid, desc, cat, sev = AST_DANGEROUS_CALLS[node.func.id]
                snippet = ast.get_source_segment(src, node) or ''
                findings.append({
                    'file_path': rel_path, 'file_ext': '.py', 'line_no': node.lineno,
                    'vuln_type': desc, 'category': cat, 'severity': sev,
                    'code_snippet': snippet[:200], 'fix_suggestion': _remediation(rid),
                    'scanner_rule': rid
                })
            # 方法调用: os.system(...), subprocess.Popen(...)
            elif isinstance(node.func, ast.Attribute):
                attr_name = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    mod = node.func.value.id
                    key = (mod, attr_name)
                    if key in AST_DANGEROUS_ATTRS:
                        rid, desc, cat, sev = AST_DANGEROUS_ATTRS[key]
                        snippet = ast.get_source_segment(src, node) or ''
                        findings.append({
                            'file_path': rel_path, 'file_ext': '.py', 'line_no': node.lineno,
                            'vuln_type': desc, 'category': cat, 'severity': sev,
                            'code_snippet': snippet[:200], 'fix_suggestion': _remediation(rid),
                            'scanner_rule': rid
                        })
                # subprocess.run(..., shell=True)
                if attr_name == 'run' or attr_name == 'Popen':
                    for kw in node.keywords:
                        if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            snippet = ast.get_source_segment(src, node) or ''
                            findings.append({
                                'file_path': rel_path, 'file_ext': '.py', 'line_no': node.lineno,
                                'vuln_type': f'subprocess.{attr_name}(shell=True)', 'category': 'COMMAND_EXEC',
                                'severity': 'CRITICAL', 'code_snippet': snippet[:200],
                                'fix_suggestion': _remediation('PY_SHELL_RUN_AST'),
                                'scanner_rule': 'PY_SHELL_RUN_AST'
                            })
            self.generic_visit(node)

    Visitor().visit(tree)
    return findings


def _regex_scan_file(full_path, rel_path, ext):
    """按行regex扫描单个文件"""
    findings = []
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return findings

    for line_no, line in enumerate(lines, 1):
        for rid, desc, cat, sev, pat, ext_set in REGEX_RULES:
            if ext not in ext_set:
                continue
            if pat.search(line):
                # 过滤: PY_DEBUG_PRINT 排除 logging/logger 前缀
                if rid == 'PY_DEBUG_PRINT':
                    low_line = line.lower()
                    if 'logging.' in low_line or 'logger.' in low_line:
                        continue
                findings.append({
                    'file_path': rel_path, 'file_ext': ext, 'line_no': line_no,
                    'vuln_type': desc, 'category': cat, 'severity': sev,
                    'code_snippet': line.rstrip()[:200],
                    'fix_suggestion': _remediation(rid),
                    'scanner_rule': rid
                })
    return findings


def _remediation(rule_id):
    """修复建议映射"""
    m = {
        'PY_EVAL': '用ast.literal_eval替代eval，或改用安全的JSON/YAML解析',
        'PY_EVAL_AST': '避免eval()，使用ast.literal_eval或明确的白名单映射',
        'PY_EXEC': '删除exec()调用，用安全的动态加载方案',
        'PY_EXEC_AST': '删除exec()调用，改用importlib等安全机制',
        'PY_COMPILE_AST': '避免动态compile，考虑代码重构',
        'PY_OS_SYSTEM': '改用subprocess.run(..., shell=False) + 参数列表',
        'PY_OS_SYSTEM_AST': '改用subprocess.run([...], shell=False)，禁止直接shell命令',
        'PY_OS_POPEN_AST': '删除os.popen，用subprocess并禁用shell',
        'PY_SUBPROCESS_POPEN_AST': 'subprocess.Popen必须shell=False，参数用列表传递',
        'PY_SUBPROCESS_CALL_AST': 'subprocess.call用列表参数，禁用shell=True',
        'PY_SUBPROCESS_CHECK_AST': 'subprocess.check_output用列表参数，禁用shell',
        'PY_SUBPROCESS_RUN_AST': 'subprocess.run用列表参数，禁用shell=True',
        'PY_SHELL_RUN_AST': '禁止shell=True，改用参数列表传递',
        'PY_SUBPROCESS': 'subprocess调用必须shell=False，参数用列表',
        'PY_PICKLE': '禁止pickle.loads处理不可信数据，改用JSON/msgpack',
        'PY_PICKLE_LOADS_AST': 'pickle.loads禁止处理外部输入，改用JSON',
        'PY_PICKLE_LOAD_AST': 'pickle.load禁止处理外部输入，改用JSON',
        'PY_HARDCODE_PWD': '用环境变量(os.environ.get)或密钥管理服务存储密码',
        'PY_HARDCODE_KEY': '密钥移入.env或Vault，禁止硬编码',
        'PY_SQL_CONCAT': '改用SQLAlchemy ORM或参数化查询 (?)',
        'PY_DB_RAW': '尽量用ORM，原生SQL必须参数化',
        'PY_DEBUG_PRINT': '删除print语句或改用logger模块',
        'PY_DEBUG_MODE': '生产环境debug=False',
        'PY_HOST_WILDCARD': 'host绑定到内网具体IP，不要0.0.0.0',
        'JS_EVAL': '避免eval，改用JSON.parse等安全方案',
        'JS_DOC_WRITE': '禁止document.write，用textContent安全赋值',
        'JS_INNER_HTML': '禁止innerHTML直接拼接用户输入，用textContent',
        'HTML_SCRIPT_TAG': '审查内联script，确保CSP允许或移除',
        'CSS_URL_HTTP': '改用https加载，避免混合内容警告',
        'GEN_TOKEN_BEARER': '从源码中移除token，用环境变量注入',
    }
    return m.get(rule_id, '请参考MTSCOS安全最佳实践进行修复')


# 严重度 → 漏洞修复适配中心任务模板
SEV_TO_FLOW_NODE = {
    'CRITICAL': '漏洞修复适配中心·即时阻断',
    'HIGH': '漏洞修复适配中心·高优先',
    'MEDIUM': '漏洞修复适配中心·常规',
    'LOW': '安全审计中心·记录',
    'INFO': '安全审计中心·记录',
}


def run_scan_once(root=None, dispatch=True):
    """主入口 — 全量扫描 + 入库 + 可选自动入厅
    
    Args:
        root: 扫描根目录，默认 flask-app/
        dispatch: 是否自动将CRITICAL/HIGH漏洞派发到mt_lab_task_hall
    Returns:
        dict  扫描会话摘要
    """
    root = root or BASE_ROOT
    session_id = f"CA-{hashlib.sha256(f'{_now()}-{root}'.encode()).hexdigest()[:10].upper()}"
    all_findings = []
    scanned_files = 0
    py_count = 0

    # 更新扫描状态
    try:
        conn = _get_db()
        conn.execute("INSERT OR REPLACE INTO mt_hygiene_scan_state(kind, phase, sweep_id, cursor_idx, total, sweep_started_at, updated_at) "
                     "VALUES('CODE_AUDIT','SCANNING',?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
                     (session_id, 0, 0))
        conn.commit()
    except Exception as e:
        print(f"[code_audit] 更新扫描状态失败: {e}")

    # 遍历扫描
    for full, rel, ext in _walk_files(root):
        scanned_files += 1
        if ext == '.py':
            py_count += 1
            # AST扫描 + regex扫描
            all_findings.extend(_ast_scan_python(full))
            all_findings.extend(_regex_scan_file(full, rel, ext))
        else:
            all_findings.extend(_regex_scan_file(full, rel, ext))

    # 去重 (AST和regex可能重复发现同一问题)
    seen = set()
    deduped = []
    for f in all_findings:
        key = (f['file_path'], f['line_no'], f['vuln_type'])
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    # 批量持久化 (用INSERT OR REPLACE的UNIQUE约束)
    inserted = 0
    reopened = 0
    try:
        conn = _get_db()
        cur = conn.cursor()
        for f in deduped:
            # 先看是否存在
            cur.execute(
                "SELECT finding_id, status, seen_count FROM mt_code_audit_findings "
                "WHERE file_path=? AND line_no=? AND vuln_type=? AND scanner_rule=?",
                (f['file_path'], f['line_no'], f['vuln_type'], f['scanner_rule']))
            row = cur.fetchone()
            if row:
                fid, st, cnt = row
                if st in ('CLOSED', 'FIXED'):
                    # 重现 — 重新打开
                    cur.execute(
                        "UPDATE mt_code_audit_findings SET status='OPEN', last_seen=datetime('now','localtime'), seen_count=seen_count+1 "
                        "WHERE finding_id=?", (fid,))
                    reopened += 1
                else:
                    cur.execute(
                        "UPDATE mt_code_audit_findings SET last_seen=datetime('now','localtime'), seen_count=seen_count+1 "
                        "WHERE finding_id=?", (fid,))
            else:
                cur.execute(
                    "INSERT INTO mt_code_audit_findings(file_path,file_ext,line_no,vuln_type,category,severity,"
                    "code_snippet,fix_suggestion,scanner_rule,scan_session_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (f['file_path'], f['file_ext'], f['line_no'], f['vuln_type'], f['category'],
                     f['severity'], f['code_snippet'], f['fix_suggestion'], f['scanner_rule'], session_id))
                inserted += 1
        conn.commit()
    except Exception as e:
        print(f"[code_audit] 持久化失败: {e}")
        return {'error': str(e)}

    # 统计
    try:
        conn = _get_db()
        summary = conn.execute(
            "SELECT severity, COUNT(*) FROM mt_code_audit_findings GROUP BY severity ORDER BY "
            "CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 4 ELSE 5 END"
        ).fetchall()
    except Exception:
        summary = []

    # 更新扫描状态到DONE
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO mt_hygiene_scan_state(kind, phase, sweep_id, cursor_idx, total, sweep_started_at, updated_at) "
            "VALUES('CODE_AUDIT','DONE',?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
            (session_id, len(deduped), scanned_files))
        conn.commit()
    except Exception:
        pass

    # —— 自动派发 CRITICAL/HIGH 漏洞到 mt_lab_task_hall ——
    dispatched = 0
    if dispatch:
        try:
            conn = _get_db()
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA recursive_triggers=ON")

            # 获取未派发的 CRITICAL/HIGH (hall_task_id IS NULL 或 status 非 DISPATCHED 且已存在hall_task_id已完结)
            rows = conn.execute(
                "SELECT finding_id, file_path, line_no, vuln_type, severity, fix_suggestion "
                "FROM mt_code_audit_findings "
                "WHERE severity IN ('CRITICAL','HIGH') AND status NOT IN ('FIXED','CLOSED','WIP') "
                "AND (hall_task_id IS NULL OR hall_task_id NOT IN (SELECT id FROM mt_lab_task_hall WHERE status IN ('DONE','DELIVERED','CLOSED'))) "
                "ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 ELSE 1 END, severity"
            ).fetchall()

            for r in rows:
                fid = r['finding_id']
                hall_code = f"CODE_AUDIT_{r['severity']}_{fid}"
                flow_node = SEV_TO_FLOW_NODE[r['severity']]
                priority = SEV_TO_PRIORITY[r['severity']]

                # 检查是否已存在相同hall_code的任务
                exist = conn.execute(
                    "SELECT id FROM mt_lab_task_hall WHERE hall_code=?", (hall_code,)).fetchone()
                if exist:
                    conn.commit()
                    continue

                title = f"[代码审计·{r['severity']}] {r['vuln_type']} — {r['file_path']}:L{r['line_no']}"
                description = (
                    f"文件: {r['file_path']}:{r['line_no']}\n"
                    f"漏洞类型: {r['vuln_type']}\n"
                    f"严重度: {r['severity']}\n"
                    f"修复建议: {r['fix_suggestion']}\n"
                    f"来源: code_audit_daemon session={session_id}"
                )

                conn.execute(
                    "INSERT INTO mt_lab_task_hall(title,description,source,priority,status,hall_code,publisher,publisher_role,flow_node,acceptance_criteria) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (title, description, 'code_audit_daemon', priority, 'DISPATCHED',
                     hall_code, '代码审计守护', 'SEC-CODE-AUDIT-005',
                     flow_node, '漏洞已修复且代码审计守护复扫为PASS'))
                conn.commit()

                # 回写hall_task_id
                task = conn.execute(
                    "SELECT id FROM mt_lab_task_hall WHERE hall_code=?", (hall_code,)).fetchone()
                if task:
                    conn.execute(
                        "UPDATE mt_code_audit_findings SET hall_task_id=?, status='DISPATCHED' WHERE finding_id=?",
                        (task['id'], fid))
                    dispatched += 1
                conn.commit()

        except Exception as e:
            print(f"[code_audit] 自动派发失败: {e}")

    result = {
        'session_id': session_id,
        'scanned_files': scanned_files,
        'py_files': py_count,
        'total_findings': len(deduped),
        'inserted_new': inserted,
        'reopened': reopened,
        'dispatched_to_hall': dispatched,
        'severity_summary': [dict(r) for r in summary],
        'scan_roots': [root],
    }
    print(f"[code_audit] {session_id} 完成 | 文件:{scanned_files} 新增:{inserted} 重开:{reopened} 入厅:{dispatched} | "
          f"严重度: {[dict(r) for r in summary]}")
    return result


def quick_scan(target_file):
    """快速扫描单文件 (用于hall-closure修复后的验证)"""
    full = os.path.abspath(target_file)
    if not os.path.exists(full):
        return {'error': f'文件不存在: {full}'}
    ext = os.path.splitext(full)[1].lower()
    rel = os.path.relpath(full, BASE_ROOT)
    findings = []
    if ext == '.py':
        findings.extend(_ast_scan_python(full))
    findings.extend(_regex_scan_file(full, rel, ext))
    return {'file': rel, 'findings': findings, 'count': len(findings)}


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        r = quick_scan(sys.argv[1])
    else:
        r = run_scan_once()
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
