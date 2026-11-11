#!/usr/bin/env python3
"""verify_external_terminal_access.py
=================================================================================
外部终端访问权限与系统功能全面验证脚本
=================================================================================
四段式验证（对应 §14 flow_external_terminal_check_*）：
  [A] 部署断言：vikey_enforcement_middleware 运行位文件存在 + 与 _output 正本 SHA256 一致
  [B] 判定核心矩阵：importlib 加载运行位中间件(终端绑定) + AST 提取防盗链纯函数
  [C] live HTTP（127.0.0.1:8888）：防盗链三分类 + dual-status 结构化 + 日志零新增报错
  [D] 外部终端 IP 模拟（可选）：sudo 可用时 lo0 alias 192.168.31.200 → remote_addr 非插钥终端矩阵

退出码 0 = 全部 PASS（D 段 SKIP 不影响）。
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project'
MW_SRC = f'{ROOT}/_output/app/middlewares/vikey_enforcement_middleware.py'
MW_RUN = f'{ROOT}/flask-app/app/middlewares/vikey_enforcement_middleware.py'
SRC_FILE = f'{ROOT}/flask-app/server_real_db.py'
LOG_FILE = f'{ROOT}/_runtime/logs/sys_flask_server.log'
BASE = 'http://127.0.0.1:8888'
EXT_IP = '192.168.31.200'          # 模拟外部终端的 lo0 别名
SRV_LAN = 'http://192.168.31.186:8888'

RESULTS = []


def case(name):
    def deco(fn):
        try:                                   # 装饰即执行（保持段落顺序）
            fn()
            RESULTS.append((name, True, ''))
            print(f'  PASS  {name}')
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
            print(f'  FAIL  {name} :: {e}')
        except Exception as e:
            RESULTS.append((name, False, f'{type(e).__name__}: {e}'))
            print(f'  FAIL  {name} :: {type(e).__name__}: {e}')
        return fn
    return deco


def http(path, referer=None, method='GET', timeout=10, interface=None, base=None):
    cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}|%{redirect_url}',
           '--max-time', str(timeout)]
    if referer:
        cmd += ['-H', f'Referer: {referer}']
    if interface:
        cmd += ['--interface', interface]
    cmd.append((base or BASE) + path)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    body_code, _, loc = r.stdout.strip().partition('|')
    return int(body_code or 0), loc


def log_line_count():
    try:
        with open(LOG_FILE, 'rb') as f:
            return sum(1 for _ in f)
    except Exception:
        return -1


def new_bad_log_lines(before_n):
    """读取日志第 before_n 行之后的内容，返回含 VIKEY 中间件加载失败错误的行数。"""
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            tail = list(f.readlines())[before_n:]
        return sum(1 for ln in tail if "No module named 'app.middlewares.vikey_enforcement_middleware'" in ln)
    except Exception:
        return -1


# ============================================================
# [A] 部署断言
# ============================================================
print('\n[A] 部署断言 — vikey_enforcement_middleware 运行位')


@case('A1 运行位文件存在 flask-app/app/middlewares/vikey_enforcement_middleware.py')
def _():
    assert os.path.isfile(MW_RUN), f'运行位文件缺失: {MW_RUN}'


@case('A2 运行位与 _output 正本 SHA256 一致（单一真源同步）')
def _():
    h = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
    assert h(MW_RUN) == h(MW_SRC), 'SHA256 不一致：运行位与正本已漂移'


@case('A3 运行位 importlib 加载成功 + _config/主库路径解析正确')
def _():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location('mt_vikey_mw_verify_ext', MW_RUN)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, 'vikey_enforcement'), 'vikey_enforcement 单例缺失'
    vk = mod.vikey_enforcement
    assert os.path.isfile(mod._SA_BOUND_CONFIG_PATH), f'配置解析错误: {mod._SA_BOUND_CONFIG_PATH}'
    assert os.path.isfile(vk._get_app_db_path()), f'主库解析错误: {vk._get_app_db_path()}'
    globals()['_MW_MOD'] = mod


@case('A4 server_real_db.py 三处 import 路径在运行位下可达（app.middlewares 包解析）')
def _():
    src = open(SRC_FILE, encoding='utf-8').read()
    n = src.count('from app.middlewares.vikey_enforcement_middleware import')
    assert n >= 3, f'server_real_db import 点数异常: {n}'
    assert os.path.isfile(f'{ROOT}/flask-app/app/__init__.py'), 'flask-app/app 包 __init__ 缺失'
    assert os.path.isfile(f'{ROOT}/flask-app/app/middlewares/__init__.py'), 'middlewares 包 __init__ 缺失'


# ============================================================
# [B] 判定核心矩阵（非 live，确定性）
# ============================================================
print('\n[B] 判定核心矩阵 — 终端绑定 + 防盗链纯函数')


@case('B1 终端绑定：插钥终端 IP 全部 bound（loopback/hostname解析IP）')
def _():
    mod = globals()['_MW_MOD']
    vk = mod.vikey_enforcement
    real = vk._local_terminal_ips()          # 真实调用一次（填缓存）
    lan = sorted(x for x in real if x not in ('127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1'))
    checks = {'127.0.0.1': True, '::1': True}
    if lan:
        checks[lan[0]] = True                # 如 192.168.31.186
    for ip, exp in checks.items():
        got = vk._is_bound_terminal(ip)
        assert got == exp, f'{ip} 期望{exp} 实际{got}'


@case('B2 终端绑定：外部终端 IP 一律 not bound + fail-closed')
def _():
    mod = globals()['_MW_MOD']
    f = mod.vikey_enforcement._is_bound_terminal
    for ip in ('192.168.31.242', '192.168.31.59', '10.0.0.5', '', None, '   '):
        assert f(ip) is False, f'{ip!r} 应 not bound'


@case('B3 终端绑定：::ffff: 映射归一化 + 大小写 + strip 防伪造/防误判')
def _():
    mod = globals()['_MW_MOD']
    f = mod.vikey_enforcement._is_bound_terminal
    assert f('::ffff:127.0.0.1') is True, '::ffff:127.0.0.1 应归一化为本机'
    assert f('::FFFF:127.0.0.1') is True, '大写映射前缀应归一化'
    assert f(' 127.0.0.1 ') is True, '空白应 strip'


@case('B4 防盗链纯函数 AST 提取成功（1:1 真源）')
def _():
    import ast
    src = open(SRC_FILE, encoding='utf-8').read()
    tree = ast.parse(src)
    taken, consts = [], ('_MT_HOTLINK_WHITELIST_PATHS', '_MT_HOTLINK_WHITELIST_PREFIXES',
                         '_MT_HOTLINK_OWN_HOSTS', '_STATIC_EXT_TUPLE')
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in consts:
                    taken.append(ast.get_source_segment(src, node))
        if isinstance(node, ast.FunctionDef) and node.name in (
                '_is_static_request', '_mt_hotlink_parse_netloc', '_mt_hotlink_decision'):
            taken.append(ast.get_source_segment(src, node))
    assert len(taken) >= 7, f'AST 提取不全: {len(taken)}'
    env = {}
    exec(compile('\n\n'.join(taken), '<hl>', 'exec'), env)
    globals()['_HL'] = env['_mt_hotlink_decision']


@case('B5 防盗链：外站Referer 页面redirect/API 403/静态403 三分类')
def _():
    d = globals()['_HL']
    kw = dict(method='GET', referer='http://evil.com/', request_host='127.0.0.1:8888', logged_in=False)
    assert d(path='/settings', **kw)[0] == 'redirect'
    assert d(path='/api/users', **kw)[0] == 'forbid'
    assert d(path='/static/js/x.js', **kw)[0] == 'forbid'
    assert d(path='/', **kw)[0] == 'allow'
    assert d(path='/index', **kw)[0] == 'allow'


# ============================================================
# [C] live HTTP（127.0.0.1:8888）
# ============================================================
print('\n[C] live HTTP — 防盗链/中间件生效/容器引导')


@case('C1 GET / 与 /index guest 无Referer → 200')
def _():
    for p in ('/', '/index'):
        st, loc = http(p)
        assert st == 200, f'{p} 期望200 实际{st} loc={loc}'


@case('C2 GET /settings guest 外站Referer → 302 → /index?from=hotlink_blocked')
def _():
    st, loc = http('/settings', referer='http://evil.com/')
    assert st == 302 and '/index?from=hotlink_blocked' in (loc or ''), f'{st} loc={loc}'


@case('C3 GET /api/hardware/dual-status guest → 401 结构化JSON（中间件加载修复直接证据）')
def _():
    st, _ = http('/api/hardware/dual-status')
    assert st == 401, f'期望401(未登录结构化) 实际{st}（若500=中间件仍加载失败）'


@case('C4 GET /static/* guest 外站Referer → 403')
def _():
    st, _ = http('/static/js/sa_proprietary.js', referer='http://leech.site/')
    assert st == 403, f'期望403 实际{st}'


@case('C5 GET /admin_app/dashboard guest → 容器引导302/403（非500）')
def _():
    st, loc = http('/admin_app/dashboard')
    assert st in (200, 302, 403), f'期望容器引导(200/302/403) 实际{st}'


@case('C6 本轮请求日志零新增 "No module named vikey_enforcement_middleware"')
def _():
    before = log_line_count()
    http('/'); http('/admin_app/dashboard'); http('/api/hardware/dual-status')
    time.sleep(0.6)
    bad = new_bad_log_lines(before)
    assert bad == 0, f'仍出现 {bad} 条中间件加载失败（修复未生效或未重启）'


# ============================================================
# [D] 外部终端 IP 模拟（可选：需要 sudo 配置 lo0 alias）
# ============================================================
print('\n[D] 外部终端 IP 模拟 — remote_addr=192.168.31.200（非插钥终端）')

_sudo_ok = subprocess.run('sudo -n true', shell=True, capture_output=True).returncode == 0
if not _sudo_ok:
    print('  SKIP  D段（sudo 免密不可用；终端绑定逻辑已由 B 段矩阵覆盖）')
else:
    subprocess.run(f'sudo -n ifconfig lo0 alias {EXT_IP}/32', shell=True, capture_output=True)

    @case('D1 外部终端IP访问首页 → 200（防盗链与源IP无关，公开入口）')
    def _():
        st, loc = http('/', base=SRV_LAN, interface=EXT_IP)
        assert st == 200, f'期望200 实际{st}'

    @case('D2 外部终端IP + 外站Referer 访问页面 → 302 /index?from=hotlink_blocked')
    def _():
        st, loc = http('/settings', referer='http://evil.com/', base=SRV_LAN, interface=EXT_IP)
        assert st == 302 and '/index?from=hotlink_blocked' in (loc or ''), f'{st} loc={loc}'

    @case('D3 外部终端IP 未登录访问 /admin_app/dashboard → 容器引导（非放行进SA界面）')
    def _():
        st, loc = http('/admin_app/dashboard', base=SRV_LAN, interface=EXT_IP)
        assert st in (302, 403), f'期望302/403 实际{st}'

    subprocess.run(f'sudo -n ifconfig lo0 -alias {EXT_IP}', shell=True, capture_output=True)


# ============================================================
# 汇总
# ============================================================
total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
skipped = total - passed
failed = [n for n, ok, _ in RESULTS if not ok]
print('\n' + '=' * 70)
print(f'  External-Terminal Access Verify:  {passed}/{total} CASES'
      + (f'  (FAILED: {failed})' if failed else ''))
print('=' * 70)
sys.exit(0 if not failed else 1)
