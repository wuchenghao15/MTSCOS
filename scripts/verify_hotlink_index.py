#!/usr/bin/env python3
"""verify_hotlink_index.py
Spec: 防盗链拦截 + /index 路由 验证脚本（不导入 server_real_db，AST 提取纯函数做单元矩阵）
  Part A: 源码挂点断言（/index 路由、before_request 守卫、审计落库、重定向目标）
  Part B: _mt_hotlink_decision 纯函数三矩阵（正常/异常/黑客）
  Part C: live HTTP 验证（默认开启，MTSCOS_SKIP_LIVE=1 跳过；需服务已运行于 127.0.0.1:8888）
exit 0 = 全部通过。
"""
from __future__ import annotations
import ast, os, sys
import urllib.request, urllib.error

ROOT = '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project'
SRC = f'{ROOT}/flask-app/server_real_db.py'
SCORE = [0, 0]


def case(name):
    """装饰即执行（按定义顺序逐个跑）。"""
    def deco(fn):
        def run():
            SCORE[1] += 1
            try:
                fn()
                SCORE[0] += 1
                print(f"  PASS  {name}")
            except AssertionError as e:
                print(f"  FAIL  {name}  :: {e}")
            except Exception as e:
                print(f"  ERROR {name}  :: {type(e).__name__}: {e}")
        run()
        return run
    return deco


src = open(SRC, encoding='utf-8').read()

# =====================================================================
# Part A: 源码挂点断言
# =====================================================================
print("\n[A] 源码挂点断言")


@case("A1 /index 路由与首页同视图（@app.route('/index') 紧邻 homepage 装饰器）")
def _():
    assert "@app.route('/index')" in src, "缺少 /index 路由"
    i = src.index("@app.route('/index')")
    seg = src[i:i + 200]
    assert "@system_container('homepage'" in seg, '/index 未挂 system_container 容器装饰器'
    assert src.index("@app.route('/')") < i, "主路由 / 应在 /index 之前"


@case("A2 _mt_hotlink_guard 已注册为 before_request 且位置在 session_loader 之后")
def _():
    assert '@app.before_request\ndef _mt_hotlink_guard():' in src, '守卫未注册 before_request'
    assert src.index('def _mt_sys_container_session_loader') < src.index('def _mt_hotlink_guard'), \
        '守卫必须在 session_loader 之后（依赖 _current_safe_user）'
    assert src.index('def _mt_hotlink_guard') < src.index('def _mt_vikey_lock_check'), \
        '守卫应在 VIKEY 锁之前（guest 热链优先重定向首页）'


@case("A3 判定核心为纯函数 + 白名单 + 解析器齐备")
def _():
    for name in ('_mt_hotlink_decision', '_mt_hotlink_parse_netloc',
                 '_MT_HOTLINK_WHITELIST_PATHS', '_MT_HOTLINK_WHITELIST_PREFIXES',
                 '_MT_HOTLINK_OWN_HOSTS'):
        assert f'def {name}' in src or f'{name} =' in src, f'缺少 {name}'
    wl = src[src.index('_MT_HOTLINK_WHITELIST_PATHS'):src.index('_MT_HOTLINK_WHITELIST_PATHS') + 400]
    assert "'/index'" in wl, '白名单必须含 /index'


@case("A4 阻断落库 automation_console_logs + 重定向目标 /index?from=hotlink_blocked")
def _():
    i = src.index('def _mt_hotlink_audit')
    assert "INSERT INTO automation_console_logs" in src[i:i + 1200], '审计未落库 automation_console_logs'
    assert "redirect('/index?from=hotlink_blocked'" in src, '重定向目标不符规则'
    assert "'HOTLINK_BLOCKED'" in src, '缺少 403 错误码 HOTLINK_BLOCKED'


# =====================================================================
# Part B: AST 提取纯函数 → 三矩阵
# =====================================================================
print("\n[B] _mt_hotlink_decision 纯函数矩阵（正常/异常/黑客）")

tree = ast.parse(src)
_ns = {}
taken = []
for node in tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in (
                    '_MT_HOTLINK_WHITELIST_PATHS', '_MT_HOTLINK_WHITELIST_PREFIXES',
                    '_MT_HOTLINK_OWN_HOSTS', '_STATIC_EXT_TUPLE'):
                taken.append(ast.get_source_segment(src, node))
    if isinstance(node, ast.FunctionDef) and node.name in (
            '_is_static_request', '_mt_hotlink_parse_netloc', '_mt_hotlink_decision'):
        taken.append(ast.get_source_segment(src, node))
assert len(taken) >= 6, f'AST 提取不全: {len(taken)}'
exec(compile('\n\n'.join(taken), '<extract>', 'exec'), _ns)
_decide = _ns['_mt_hotlink_decision']

OWN = '127.0.0.1:8888'


def d(path, referer, logged_in=False, method='GET', host=OWN):
    return _decide(path=path, method=method, referer=referer,
                   request_host=host, logged_in=logged_in)


@case("B1 正常矩阵：白名单/本站Referer/无Referer API与静态/已登录/OPTIONS")
def _():
    assert d('/', 'http://evil.com/')[0] == 'allow'                                # 首页白名单
    assert d('/index', 'http://evil.com/')[0] == 'allow'                           # /index 白名单
    assert d('/auth/login', 'http://evil.com/')[0] == 'allow'                      # auth 白名单
    assert d('/settings', f'http://{OWN}/')[1] == 'same-site'                      # 本站Referer
    assert d('/admin_app/dashboard', 'http://localhost:8888/')[1] == 'same-site'   # localhost等价
    assert d('/api/health', '')[1] == 'whitelist'                                  # 健康检查白名单
    assert d('/api/hardware/dual-status', '')[1] == 'no-referer-nonpage'           # 无Referer API放行
    assert d('/static/css/a.css', '')[1] == 'whitelist'                            # 本站静态白名单
    assert d('/downloads/x.pdf', '')[1] == 'no-referer-nonpage'                    # 无Referer静态放行
    assert d('/settings', 'http://evil.com/', logged_in=True)[1] == 'authorized'   # 已登录放行
    assert d('/settings', 'http://evil.com/', method='OPTIONS')[1] == 'safe-method'
    assert d('/favicon.ico', '')[0] == 'allow'
    assert d('/robots.txt', '')[0] == 'allow'


@case("B2 异常矩阵：guest 外站Referer → 页面redirect / API与静态forbid；无Referer页面redirect")
def _():
    assert d('/settings', 'http://evil.com/') == ('redirect', 'foreign-referer-page')
    assert d('/admin_app/dashboard', 'https://blog.someone.cn/x') == ('redirect', 'foreign-referer-page')
    assert d('/api/hardware/dual-status', 'http://evil.com/') == ('forbid', 'foreign-referer-api')
    assert d('/static/css/a.css', 'http://evil.com/') == ('forbid', 'foreign-referer-static')
    assert d('/settings', '') == ('redirect', 'no-referer-page')
    assert d('/settings', None) == ('redirect', 'no-referer-page')


@case("B3 黑客矩阵：伪造Referer主机名/端口/IPv6/userinfo/大小写绕过全数拦截")
def _():
    # 伪造本站主机名后缀/端口混淆/userinfo 绕过
    assert d('/settings', 'http://127.0.0.1:8888.evil.com/')[0] == 'redirect'
    assert d('/api/x', 'http://127.0.0.1:8888@evil.com/')[0] == 'forbid'
    assert d('/static/a.css', 'http://127.0.0.1.8888.evil.com/')[0] == 'forbid'
    assert d('/api/x', 'http://localhost:8888.evil.com/')[0] == 'forbid'
    # 本站主机 + 异端口（另一服务）→ 非本站
    assert d('/settings', 'http://127.0.0.1:9999/')[0] == 'redirect'
    # 畸形端口（非纯数字）→ 不信任
    assert d('/settings', 'http://127.0.0.1:88a8/')[0] == 'redirect'
    # 大小写混淆 → 仍识别为本站
    assert d('/settings', f'HTTP://{OWN.upper()}/')[1] == 'same-site'
    # IPv6 回环等价（同为本机 loopback）
    assert d('/settings', 'http://[::1]:8888/', host='[::1]:8888')[1] == 'same-site'
    assert d('/settings', 'http://[::1]:8888/')[1] == 'same-site'
    # 非 loopback IPv6 → 外站
    assert d('/settings', 'http://[::2]:8888/')[0] == 'redirect'


# =====================================================================
# Part C: live HTTP（服务运行时验证真实行为）
# =====================================================================
BASE = 'http://127.0.0.1:8888'
SKIP_LIVE = os.environ.get('MTSCOS_SKIP_LIVE', '0') == '1'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http(path, referer=None):
    req = urllib.request.Request(BASE + path, method='GET')
    req.add_header('User-Agent', 'MTSCOS-Verify/1.0')
    if referer is not None:
        req.add_header('Referer', referer)
    try:
        resp = urllib.request.build_opener(_NoRedirect()).open(req, timeout=25)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b''
        return e.code, dict(e.headers), body


if not SKIP_LIVE:
    print("\n[C] live HTTP 验证（127.0.0.1:8888）")

    @case("C1 GET /index → 200（guest 无Referer）")
    def _():
        st, _, _ = http('/index')
        assert st == 200, f'/index 期望200 实际{st}'

    @case("C2 GET / 外站Referer guest → 200（首页白名单）")
    def _():
        st, _, _ = http('/', referer='http://evil.com/')
        assert st == 200, f'/ 期望200 实际{st}'

    @case("C3 GET /settings 外站Referer guest → 302 → /index?from=hotlink_blocked")
    def _():
        st, hd, _ = http('/settings', referer='http://evil.com/')
        assert st == 302, f'期望302 实际{st}'
        assert '/index?from=hotlink_blocked' in (hd.get('Location') or ''), hd.get('Location')

    @case("C4 GET /settings 无Referer guest → 302 → /index?from=hotlink_blocked")
    def _():
        st, hd, _ = http('/settings')
        assert st == 302, f'期望302 实际{st}'
        assert '/index?from=hotlink_blocked' in (hd.get('Location') or ''), hd.get('Location')

    @case("C5 GET /api/* 外站Referer guest → 403 HOTLINK_BLOCKED")
    def _():
        st, _, body = http('/api/hardware/dual-status', referer='http://evil.com/')
        assert st == 403, f'期望403 实际{st}'
        assert b'HOTLINK_BLOCKED' in body, '403 响应体缺少 HOTLINK_BLOCKED 错误码'

    @case("C6 GET /static/* 外站Referer guest → 403")
    def _():
        st, _, _ = http('/static/css/sa_proprietary.css', referer='http://evil.com/')
        assert st == 403, f'期望403 实际{st}'

    @case("C7 GET /auth/login 外站Referer guest → 防盗链放行，落到既有容器引导（302→/ 或 200）")
    def _():
        st, hd, _ = http('/auth/login', referer='http://evil.com/')
        loc = hd.get('Location') or ''
        assert st == 200 or (st == 302 and loc == '/'), \
            f'期望200或既有引导302→/，实际{st} loc={loc}'  # 防盗链不放行会是302→/index?from=hotlink_blocked
        assert 'hotlink_blocked' not in loc, f'auth白名单被防盗链误拦: {loc}'
else:
    print("\n[C] live HTTP 已通过 MTSCOS_SKIP_LIVE=1 跳过")

# =====================================================================
# END
# =====================================================================
passed, total = SCORE
print(f"\n==============================================")
print(f"  Hotlink+Index Verify:  {passed}/{total}  CASES")
print(f"==============================================")
sys.exit(0 if passed == total else 1)
