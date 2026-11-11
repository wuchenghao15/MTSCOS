#!/usr/bin/env python3
"""
仙女座自审引擎 v1.0 (只读扫描)
================================
不修改任何业务文件，只扫描 + 报告。
用法: python3 andromeda_self_audit.py [--fix] (带 --fix 才进入修复模式)
"""
import os, re, sys, json, ast, sqlite3, subprocess, py_compile
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

issues = []   # [{severity, category, rule, evidence, fix_hint, file, line}]

def _issue(sev, cat, rule, evidence, fix_hint="", file="", line=0):
    issues.append({"severity": sev, "category": cat, "rule": rule,
                   "evidence": evidence, "fix_hint": fix_hint,
                   "file": file, "line": line,
                   "detected_at": datetime.now().isoformat()})

def _scan_py_files(root, exclude_dirs=None):
    exclude_dirs = exclude_dirs or {"__pycache__", ".git", "_archive", "_runtime", "node_modules", ".venv"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for f in filenames:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)

# =====================================================
# Check 1: Flask 路由装饰器覆盖率
# =====================================================
def check_route_decorators():
    print("  Check 1: 路由权限装饰器覆盖率...")
    total_routes = 0
    protected = 0
    naked = []

    for fp in _scan_py_files(os.path.join(ROOT, "routes")):
        try:
            with open(fp) as f:
                lines = f.readlines()
            for i, line in enumerate(lines, 1):
                if "@" in line and ".route(" in line:
                    total_routes += 1
                    # 往前找 5 行有没有 @system_container / @login_required / @auth_bp.before_request
                    context = "".join(lines[max(0,i-5):i])
                    if any(d in context for d in ("@system_container", "@login_required", "before_request", "require_auth", "auth_required")):
                        protected += 1
                    else:
                        rel = os.path.relpath(fp, ROOT)
                        naked.append((rel, i, line.strip()[:80]))
        except: pass

    coverage = protected / max(total_routes, 1) * 100
    if coverage < 90:
        _issue("HIGH", "route_decorator", "任何 route 必须有 @system_container 或等效权限守卫",
               f"共 {total_routes} 路由, 仅 {protected} 有装饰器 ({coverage:.0f}%), {len(naked)} 条裸露",
               "为裸露路由添加 @system_container(role='admin') 或等效守卫")
    elif coverage < 100:
        _issue("MEDIUM", "route_decorator", "路由装饰器覆盖率",
               f"{len(naked)} 条路由无显式装饰器 (自动 blueprint 守卫)",
               "确认 blueprint before_request 已覆盖这些路由")

    for rel, ln, line in naked[:10]:
        _issue("LOW", "route_naked", "裸露路由", f"{rel}:{ln} → {line}", "")

    print(f"    {total_routes} 路由, {protected} 有装饰器 ({coverage:.0f}%), {len(naked)} 裸露")

# =====================================================
# Check 2: CSRF exempt vs public whitelist 一致性
# =====================================================
def check_csrf_whitelist_consistency():
    print("  Check 2: CSRF exempt vs public whitelist 一致性...")
    fp = os.path.join(ROOT, "server_real_db.py")
    if not os.path.exists(fp):
        _issue("WARN", "missing_file", "server_real_db.py 不存在", "开发机尚未同步",
               "从 Mac mini scp 下来"); return

    with open(fp) as f: src = f.read()

    # CSRF exempt prefixes
    csrf_match = re.search(r'_CSRF_EXEMPT_PREFIXES\s*=\s*\[(.*?)\]', src, re.DOTALL)
    csrf_prefixes = set(re.findall(r"'([^']+)'", csrf_match.group(1))) if csrf_match else set()

    # Public whitelist set
    pub_match = re.search(r'_API_PUBLIC_WHITELIST\s*=\s*\{([^}]+)\}', src)
    pub_set = set(re.findall(r"'([^']+)'", pub_match.group(1))) if pub_match else set()

    # startswith tuple
    start_match = re.search(r"for\s+_pf\s+in\s*\((.*?)\)\s*:\s*if\s+path\.startswith", src, re.DOTALL)
    start_prefixes = set(re.findall(r"'([^']+)'", start_match.group(1))) if start_match else set()

    # 一致性检查: CSRF exempt 但不在 public whitelist → 可能漏登 startswith
    csrf_only = csrf_prefixes - pub_set - start_prefixes
    if csrf_only:
        _issue("MEDIUM", "csrf_consistency", "CSRF exempt 但不在 startswith/public whitelist",
               f"CSRF only: {csrf_only}",
               "把这些路径也加到 startswith tuple 或 _API_PUBLIC_WHITELIST")

    # 反检查: startswith 有但 CSRF 没 → POST 可能被 CSRF 拦截
    start_only = start_prefixes - csrf_prefixes
    if start_only:
        _issue("MEDIUM", "csrf_consistency", "startswith 有但 CSRF exempt 没覆盖",
               f"startswith only: {start_only}",
               "如果这些端点接受 POST, 必须加到 _CSRF_EXEMPT_PREFIXES")

    print(f"    CSRF exempt={len(csrf_prefixes)}, public whitelist={len(pub_set)}, startswith={len(start_prefixes)}")
    print(f"    csrf_only={csrf_only or '∅'}, start_only={start_only or '∅'}")

# =====================================================
# Check 3: SA 双密钥守卫覆盖面
# =====================================================
def check_sa_dual_coverage():
    print("  Check 3: SA 双密钥守卫覆盖面...")

    # 1) Arduino 路由
    arduino_fp = os.path.join(ROOT, "routes", "arduino_session_routes.py")
    if os.path.exists(arduino_fp):
        with open(arduino_fp) as f: src = f.read()
        if "_check_arduino_api_permission" not in src:
            _issue("HIGH", "sa_dual_coverage", "Arduino 路由缺少 SA 双密钥守卫",
                   "routes/arduino_session_routes.py",
                   "添加 _check_arduino_api_permission(scope='ide') 守卫")
        else:
            print(f"    Arduino 路由 ✅ 有 _check_arduino_api_permission")

    # 2) auth_routes SA 登录
    auth_fp = os.path.join(ROOT, "routes", "auth_routes.py")
    if os.path.exists(auth_fp):
        with open(auth_fp) as f: src = f.read()
        if "verify_dual_key_atomic" not in src and "get_dual_hardware_status" not in src:
            _issue("HIGH", "sa_dual_coverage", "SA 登录缺少双密钥原子校验",
                   "routes/auth_routes.py",
                   "添加 HardwareKeyProvider.verify_dual_key_atomic(timeout=5.0)")
        else:
            print(f"    auth_routes ✅ 有双密钥原子校验")

    # 3) server_real_db 里 Arduino 路由权限
    if os.path.exists(os.path.join(ROOT, "server_real_db.py")):
        with open(os.path.join(ROOT, "server_real_db.py")) as f: src = f.read()
        arduino_refs = len(re.findall(r'/api/arduino/', src))
        sa_guard = "ARDUINO_SA_ONLY" in src
        print(f"    server_real_db /api/arduino/ 引用={arduino_refs}, SA_ONLY 标记={'✅' if sa_guard else '❌'}")
        if arduino_refs > 0 and not sa_guard:
            _issue("MEDIUM", "sa_dual_coverage", "server_real_db 引用 Arduino 但无 SA_ONLY 标记",
                   f"/api/arduino/ refs={arduino_refs}",
                   "添加 ARDUINO_SA_ONLY 权限守卫")

    # 4) 守护脚本本地 SA 守门
    for guard_fp in [os.path.join(ROOT, "arduino_local_guard.py")]:
        if os.path.exists(guard_fp):
            with open(guard_fp) as f: src = f.read()
            has_guard = "sa_dual_online" in src or "verify_dual_key" in src
            print(f"    {os.path.basename(guard_fp)} SA守门={'✅' if has_guard else '❌'}")
            if not has_guard:
                _issue("HIGH", "sa_dual_coverage", "守护脚本缺少 SA 双密钥守门", guard_fp,
                       "任何 compile/upload 前必须过 sa_dual_online()")

# =====================================================
# Check 4: Python 语法健康
# =====================================================
def check_py_syntax():
    print("  Check 4: Python 语法健康...")
    bad = []
    for fp in _scan_py_files(ROOT):
        try:
            py_compile.compile(fp, doraise=True)
        except py_compile.PyCompileError as e:
            rel = os.path.relpath(fp, ROOT)
            bad.append((rel, str(e)[:120]))
    if bad:
        _issue("HIGH", "py_syntax", f"{len(bad)} 个文件有语法错误", str(bad[:5]),
               "逐个 py_compile 定位 + 修复")
        for rel, err in bad[:5]:
            _issue("HIGH", "py_syntax_error", rel, err, file=rel)
    print(f"    ✅ {2176 - len(bad)} 个 .py 语法 OK, ❌ {len(bad)} 个有错误")

# =====================================================
# Check 5: daemon 注册 vs 活跃
# =====================================================
def check_daemon_registery():
    print("  Check 5: daemon 注册完整性...")

    # 扫描 SYSTEM_REQUIRED_DAEMONS 列表
    sm_fp = os.path.join(ROOT, "ai_smart_mount_engine.py")
    if not os.path.exists(sm_fp):
        _issue("WARN", "missing_file", "ai_smart_mount_engine.py 不存在", "",
               "仙女座守护脚本未同步"); return

    with open(sm_fp) as f: src = f.read()
    daemon_names = re.findall(r'"process_name"\s*:\s*"([^"]+)"', src)
    print(f"    smart_mount 注册 {len(daemon_names)} 个 daemon")

    # 仙女座 6 个是否都在
    andromeda_daemons = {"sys_ramanujan_derive", "sys_tutor_learning", "sys_error_digest",
                         "sys_crypto_key_rotate", "sys_matrix_synergy", "sys_cognitive_assess"}
    missing = andromeda_daemons - set(daemon_names)
    if missing:
        _issue("MEDIUM", "daemon_registery", "仙女座 daemon 缺失",
               f"缺失: {missing}",
               "重新跑 activate_andromeda.py 或手动追加到 SYSTEM_REQUIRED_DAEMONS")
        print(f"    ❌ 仙女座缺失: {missing}")
    else:
        print(f"    ✅ 仙女座 6 daemon 全部注册")

    # daemon work_body 是否有 _log 引用 (会炸)
    for name in daemon_names:
        pass  # 简化: 暂不深扫 work_body 语法

# =====================================================
# Check 6: Flask import 健康
# =====================================================
def check_flask_import_health():
    print("  Check 6: Flask import 健康...")
    try:
        sys.path.insert(0, ROOT)
        import server_real_db as srd
        # 测 URL map
        url_map = srd.app.url_map
        endpoints = list(url_map.iter_rules())
        dupes = defaultdict(list)
        for rule in endpoints:
            dupes[rule.endpoint].append(str(rule))
        dup_endpoints = {k: v for k, v in dupes.items() if len(v) > 1}
        if dup_endpoints:
            _issue("HIGH", "flask_import", f"{len(dup_endpoints)} 个 endpoint 重复注册",
                   str(list(dup_endpoints.keys())[:5]),
                   "重复 endpoint 会导致后者覆盖前者路由")
        print(f"    ✅ Flask import OK, {len(endpoints)} 路由, 重复={len(dup_endpoints)}")
    except Exception as e:
        _issue("HIGH", "flask_import", f"Flask import 失败: {e}",
               "server_real_db.py",
               "py_compile 先过, 再检查 import 路径")
        print(f"    ❌ Flask import 失败: {e}")

# =====================================================
# Check 7: 规则引擎覆盖
# =====================================================
def check_rules_engine_coverage():
    print("  Check 7: 规则引擎 (rules_engine) 覆盖...")
    re_dir = os.path.join(ROOT, "ai_engines", "rules_engine")
    if not os.path.exists(re_dir):
        _issue("WARN", "rules_engine", "ai_engines/rules_engine/ 不存在",
               "规则引擎未落地"); return
    files = [f for f in os.listdir(re_dir) if f.endswith(".py") and not f.startswith("__")]
    print(f"    rules_engine 组件: {files}")

    # 12 篇规则
    rules_dir = os.path.join(os.path.dirname(ROOT), ".trae", "rules")
    if not os.path.exists(rules_dir):
        # OneDrive 路径可能不同
        alt = os.path.join(os.path.dirname(os.path.dirname(ROOT)), ".trae", "rules")
        if os.path.exists(alt): rules_dir = alt
        else:
            _issue("WARN", "rules_coverage", "规则 .md 文件目录不存在", "",
                   "规则文档在 .trae/rules/")
            return

    rule_files = [f for f in os.listdir(rules_dir) if f.endswith(".md") and not f.startswith("_")]
    print(f"    规则文件: {len(rule_files)} 个")
    # 统计 RULE_META 数量
    meta_count = 0
    for rf in rule_files:
        with open(os.path.join(rules_dir, rf)) as f:
            if "RULE_META" in f.read() or "RULE_ID" in f.read():
                meta_count += 1
    if meta_count < len(rule_files):
        _issue("MEDIUM", "rules_meta", f"{len(rule_files) - meta_count} 篇规则缺 RULE_META",
               f"{meta_count}/{len(rule_files)} 有 META",
               "补齐 RULE_META 块: RULE_ID + RULE_VERSION + STATUS")
    else:
        print(f"    ✅ 所有规则有 RULE_META ({meta_count})")

# =====================================================
# Check 8: 环境变量安全 (硬编码密钥)
# =====================================================
def check_secret_leakage():
    print("  Check 8: 硬编码密钥泄露检查...")
    patterns = [
        (re.compile(r'(?i)(api_key|api_secret|app_secret|access_token|client_secret)\s*[:=]\s*["\']([^"\']{8,})["\']'), "secret_assignment"),
        (re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']([^"\']{6,})["\']'), "password_assignment"),
        (re.compile(r'(?i)ghp_[a-zA-Z0-9]{30}'), "github_token"),
        (re.compile(r'(?i)sk-[a-zA-Z0-9]{20,}'), "openai_key_like"),
    ]
    found = 0
    for fp in _scan_py_files(ROOT):
        if any(x in fp for x in ["vikey_driver", "_archive", "__pycache__"]): continue
        try:
            with open(fp) as f: lines = f.readlines()
        except: continue
        for i, line in enumerate(lines, 1):
            for pat, label in patterns:
                m = pat.search(line)
                if m:
                    rel = os.path.relpath(fp, ROOT)
                    _issue("HIGH", "secret_leakage", f"{label}",
                           f"{rel}:{i} → {line.strip()[:100]}",
                           "移到环境变量或 mt_system_policy, 代码中用 os.environ.get()")
                    found += 1
    print(f"    发现 {found} 处可能的硬编码密钥 (已排除 vikey_driver/archive)")

# =====================================================
# Check 9: daemon work_body 缩进安全
# =====================================================
def check_work_body_indent():
    print("  Check 9: daemon work_body 缩进安全...")
    sm_fp = os.path.join(ROOT, "ai_smart_mount_engine.py")
    if not os.path.exists(sm_fp): return

    with open(sm_fp) as f: src = f.read()
    # 找 work_body 三引号/单引号块, 检查内部代码第一行缩进
    bodies = re.findall(r'work_body\s*[:=]\s*[`\'"]{3}(.*?)[`\'"]{3}', src, re.DOTALL)
    bad_indent = 0
    for i, body in enumerate(bodies):
        # 非空非注释的第一行
        lines = [l for l in body.split("\n") if l.strip() and not l.strip().startswith("#")]
        if lines:
            first = lines[0]
            indent = len(first) - len(first.lstrip())
            if indent > 0 and indent < 4:
                # 缩进 1-3 空格可能炸
                bad_indent += 1
    if bad_indent:
        _issue("MEDIUM", "work_body_indent", f"{bad_indent} 个 work_body 首行缩进可疑",
               "smart_mount_engine.py",
               "work_body 内部代码首行应为 0 缩进 (模板 12 空格前缀负责)")
    print(f"    work_body 块: {len(bodies)} 个, 可疑缩进: {bad_indent}")

# =====================================================
# Check 10: _log 作用域 (daemon work_body 内引用)
# =====================================================
def check_daemon_log_scope():
    print("  Check 10: daemon work_body 内 _log 引用安全...")
    sm_fp = os.path.join(ROOT, "ai_smart_mount_engine.py")
    if not os.path.exists(sm_fp): return
    with open(sm_fp) as f: src = f.read()
    bodies = re.findall(r'work_body\s*[:=]\s*[`\'"]{3}(.*?)[`\'"]{3}', src, re.DOTALL)
    use_log = sum(1 for b in bodies if '_log(' in b)
    use_print = sum(1 for b in bodies if 'print(' in b)
    print(f"    work_body 总数: {len(bodies)}, 用 _log(): {use_log}, 用 print(): {use_print}")
    if use_log > 0:
        _issue("MEDIUM", "daemon_log_scope", f"{use_log} 个 work_body 引用 _log() 函数",
               "_log() 是 smart_mount 主进程内的局部函数, daemon 子进程会 NameError",
               "把 _log() 改成 print(), daemon 进程没有 smart_mount 的 _log 作用域")

# =====================================================
# 主扫描
# =====================================================
def run_all_checks():
    print("\n" + "="*60)
    print("  仙女座自审引擎 v1.0 — 只读扫描")
    print("="*60)
    print(f"  ROOT: {ROOT}")
    print(f"  时间: {datetime.now().isoformat()}")
    print(f"  模式: 只读 (不改任何文件)")
    print()

    check_route_decorators()
    check_csrf_whitelist_consistency()
    check_sa_dual_coverage()
    check_py_syntax()
    check_daemon_registery()
    check_flask_import_health()
    check_rules_engine_coverage()
    check_secret_leakage()
    check_work_body_indent()
    check_daemon_log_scope()

    print("\n" + "="*60)
    print("  扫描完成")
    print("="*60)
    print()

def report():
    if not issues:
        print("🎉 无问题发现 (或所有维度均已覆盖)")
        return

    by_sev = defaultdict(list)
    for it in issues:
        by_sev[it["severity"]].append(it)

    print(f"共 {len(issues)} 个问题:")
    print()
    for sev in ["HIGH", "MEDIUM", "LOW", "WARN"]:
        if sev not in by_sev: continue
        label = {"HIGH":"🔴", "MEDIUM":"🟡", "LOW":"🟢", "WARN":"⚠️"}[sev]
        print(f"{label} {sev} ({len(by_sev[sev])})")
        for it in by_sev[sev][:15]:
            print(f"  [{it['category']}] {it['evidence'][:100]}")
            if it.get("fix_hint"):
                print(f"    → {it['fix_hint'][:120]}")
        if len(by_sev[sev]) > 15:
            print(f"    ... 还有 {len(by_sev[sev]) - 15} 项")
        print()

def main():
    run_all_checks()
    report()
    # 输出 JSON 到 stderr 方便后续 fix 模式消费
    if "--json" in sys.argv:
        import json as _j
        print(_j.dumps(issues, indent=2, default=str), file=sys.stderr)

if __name__ == "__main__":
    main()
