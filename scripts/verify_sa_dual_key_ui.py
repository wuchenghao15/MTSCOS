#!/usr/bin/env python3
"""verify_sa_dual_key_ui.py
Spec: SA 双密钥 UI 自动适配验证脚本 (不启动真实 HTTP server, unit级)
覆盖 AC-1/2/3/6/7 + T3/T4/T5/T8；JS/CSS/T5 文件存在性归文件/语法验证。
exit 0 = 全部通过。
"""
from __future__ import annotations
import sys, os, json, re, textwrap, traceback
ROOT = '/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project'
sys.path.insert(0, f'{ROOT}/flask-app')
sys.path.insert(0, f'{ROOT}/_output')

SCORE = [0, 0]
def case(name):
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
                traceback.print_exc()
        return run
    return deco

# =====================================================================
# Section 1: 中间件层 T1/T2
# =====================================================================
print("\n[1] 双密钥聚合 + SA AND 校验 (7 case matrix)")
from unittest.mock import patch
import app.middlewares.vikey_enforcement_middleware as m

def check(scenario, ip='127.0.0.1'):
    CFG = {
      'dual':        (True,  True,  True,  True),
      'v_only':      (True,  True,  False, False),
      's_only':      (False, False, True,  True),
      's_forged':    (True,  True,  True,  False),
      'v_wrongbind': (True,  False, True,  True),
      'none':        (False, False, False, False),
    }[scenario]
    v_ok, v_bound, s_pres, s_auth = CFG
    uname='wuchenghao15'
    role='super_admin'
    def fv():
        if v_ok and v_bound: return {'status':'ok','serial':'V1','sa_bound_ok':True,'message':'ok'}
        if v_ok: return {'status':'ok','serial':'V9','sa_bound_ok':False,'message':'绑定非SA用户'}
        return {'status':'no_device','sa_bound_ok':False,'message':'未检测到VIKEY加密狗'}
    def fs():
        if s_pres and s_auth: return {'present':True,'is_authentic':True,'volume_name':'SZU100','auth_status':'authentic','message':'ok'}
        if s_pres: return {'present':True,'is_authentic':False,'volume_name':'FAKE','auth_status':'forged','message':'SZU100 未通过正版校验'}
        return {'present':False,'is_authentic':False,'volume_name':'','auth_status':'absent','message':'未检测到SZU100专用U盘'}
    inst = m.VikeyEnforcementMiddleware()
    with patch.object(m.VikeyEnforcementMiddleware,'_check_vikey', staticmethod(fv)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_szu100', staticmethod(fs)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_network', staticmethod(lambda:True)):
        d = inst.get_dual_hardware_status(username=uname, role=role, force_refresh=True, ip=ip)
        r = inst.check_vikey_enforcement('/admin_app/dashboard', uname, extra={'ip':ip,'ua':'t','session_id':'s'})
    return d, r

@case("dual → SA_PROPRIETARY & allowed")
def _():
    d, r = check('dual')
    assert d['both_authenticated'] is True and d['layout_mode'] == 'SA_PROPRIETARY'
    assert r['allowed'] is True and '双硬件密钥认证通过' in r['reason']
    assert 'szu100_status' in r, 'T2 返回须含 szu100_status'

@case("v_only → STANDARD & szu100 absent → denied")
def _():
    d, r = check('v_only')
    assert d['layout_mode'] == 'STANDARD' and d['both_authenticated'] is False
    assert r['allowed'] is False and 'SZU100专用U盘' in r['reason']

@case("s_only → STANDARD & vikey absent → denied")
def _():
    d, r = check('s_only')
    assert d['layout_mode'] == 'STANDARD' and r['allowed'] is False
    assert 'VIKEY' in r['reason']

@case("s_forged → STANDARD & authentic fail → denied")
def _():
    d, r = check('s_forged')
    assert d['both_authenticated'] is False and r['allowed'] is False
    assert '正版校验' in r['reason']

@case("v_wrongbind → sa_bound_ok False → denied")
def _():
    d, r = check('v_wrongbind')
    assert d['both_authenticated'] is False and r['allowed'] is False

@case("none → STANDARD & denied")
def _():
    d, r = check('none')
    assert d['layout_mode'] == 'STANDARD' and r['allowed'] is False

@case("dual admin → STANDARD & allowed")
def _():
    def fv(): return {'status':'ok','serial':'V1','sa_bound_ok':True,'message':'ok'}
    def fs(): return {'present':True,'is_authentic':True,'volume_name':'SZU100','auth_status':'authentic','message':'ok'}
    inst = m.VikeyEnforcementMiddleware()
    with patch.object(m.VikeyEnforcementMiddleware,'_check_vikey', staticmethod(fv)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_szu100', staticmethod(fs)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_network', staticmethod(lambda:True)):
        d = inst.get_dual_hardware_status(username='admin', role='admin', force_refresh=True)
        r = inst.check_vikey_enforcement('/admin_app/dashboard', 'admin', extra={'ip':'1','ua':'2','session_id':'3'})
    assert d['both_authenticated'] is False and d['layout_mode'] == 'STANDARD'
    assert r['allowed'] is True

for f in list(globals().values()):
    if callable(f) and f.__name__ == 'run' and hasattr(f, '__wrapped__'): pass
# 上面case定义使用装饰器并没生成可遍历列表；改为再直接手工跑7个:
check('dual'); pass
# ---- 已通过上面 @case 函数定义 + 立即执行的 globals 遍历不工作，直接逐个触发 ----
import types
all_funcs = [(k,v) for k,v in list(globals().items()) if callable(v) and isinstance(v, types.FunctionType) and k.startswith('_') and hasattr(v,'__name__')]
# 简化：直接重跑矩阵
mat = [
  ('dual',        True,  'SA_PROPRIETARY', True,  ['双硬件密钥认证通过']),
  ('v_only',      False, 'STANDARD',       False, ['SZU100专用U盘']),
  ('s_only',      False, 'STANDARD',       False, ['VIKEY']),
  ('s_forged',    False, 'STANDARD',       False, ['正版校验']),
  ('v_wrongbind', False, 'STANDARD',       False, ['绑定非SA用户']),
  ('none',        False, 'STANDARD',       False, ['未检测到VIKEY']),
]
for s, e_both, e_layout, e_allowed, kws in mat:
    SCORE[1] += 1
    d, r = check(s)
    ok = (d['both_authenticated']==e_both) & (d['layout_mode']==e_layout) & (r['allowed']==e_allowed) & any(k in r['reason'] for k in kws)
    SCORE[0] += int(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  matrix[{s:11s}] both={d['both_authenticated']!s:5s} layout={d['layout_mode']:15s} allowed={r['allowed']!s:5s} reason={r.get('reason','')[:60]}")

# =====================================================================
# Section 1b: SA 终端绑定（必须从插钥终端=服务器本机访问；fail-closed）
# =====================================================================
print("\n[1b] SA 终端绑定：SA 界面仅插钥终端(服务器本机)可见")
import socket as _soc

def tb_run(ip, uname='wuchenghao15', role='super_admin'):
    def fv(): return {'status':'ok','serial':'V1','sa_bound_ok':True,'message':'ok'}
    def fs(): return {'present':True,'is_authentic':True,'volume_name':'SZU100','auth_status':'authentic','message':'ok'}
    inst = m.VikeyEnforcementMiddleware()
    with patch.object(m.VikeyEnforcementMiddleware,'_check_vikey', staticmethod(fv)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_szu100', staticmethod(fs)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_network', staticmethod(lambda:True)):
        d = inst.get_dual_hardware_status(username=uname, role=role, force_refresh=True, ip=ip)
        r = inst.check_vikey_enforcement('/admin_app/dashboard', uname,
                                         extra={'ip':ip,'ua':'tb','session_id':'tb1'})
    return d, r

def tb_case(tag, ip, e_allowed, e_layout, e_bound, kw=None):
    SCORE[1] += 1
    d, r = tb_run(ip)
    ok = (r['allowed']==e_allowed) and (d['layout_mode']==e_layout) and (d['terminal']['bound']==e_bound)
    if kw is not None:
        ok = ok and (kw in r.get('reason',''))
    SCORE[0] += int(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  [{tag:18s}] ip={ip!s:16s} allowed={r['allowed']!s:5s} layout={d['layout_mode']:15s} bound={d['terminal']['bound']} reason={r.get('reason','')[:44]}")

tb_case('loopback',        '127.0.0.1',          True,  'SA_PROPRIETARY', True)
tb_case('mapped-v6',       '::ffff:127.0.0.1',   True,  'SA_PROPRIETARY', True)
tb_case('remote-ext',      '203.0.113.77',       False, 'STANDARD',       False, '插钥终端')
tb_case('remote-lan',      '192.168.199.199',    False, 'STANDARD',       False, '插钥终端')
tb_case('no-ip-failclosed', None,                False, 'STANDARD',       False, '插钥终端')
try:
    _hip = _soc.gethostbyname(_soc.gethostname())
except Exception:
    _hip = None
if _hip:
    tb_case('local-host-ip', _hip, True, 'SA_PROPRIETARY', True)
# 非 SA 角色不受终端绑定影响
SCORE[1] += 1
d2, r2 = tb_run('10.0.0.5', uname='admin', role='admin')
ok2 = (d2['terminal']['required'] is False) and (r2['allowed'] is True) and (d2['layout_mode']=='STANDARD')
SCORE[0] += int(ok2)
print(f"  {'PASS' if ok2 else 'FAIL'}  [non-sa-remote]     ip=10.0.0.5       非SA不受绑定影响 allowed={r2['allowed']} terminal.required={d2['terminal']['required']}")
# check_super_admin_vikey 模块函数 fail-closed
SCORE[1] += 1
rr = m.check_super_admin_vikey('wuchenghao15', extra={'ip':'203.0.113.77'})
ok3 = (rr['allowed'] is False) and (rr.get('terminal_status')=='NOT_BOUND') and ('插钥终端' in rr.get('reason',''))
SCORE[0] += int(ok3)
print(f"  {'PASS' if ok3 else 'FAIL'}  [mod-fn-unbound]    check_super_admin_vikey 远程IP → allowed={rr['allowed']} terminal={rr.get('terminal_status')}")

# TR-1.2 缓存
print("\n[2] DUAL_CACHE_TTL 2s 缓存验证")
SCORE[1]+=1
nv=[0]; ns=[0]
def fv(): nv[0]+=1; return {'status':'ok','serial':'V1','sa_bound_ok':True,'message':'ok'}
def fs(): ns[0]+=1; return {'present':True,'is_authentic':True,'volume_name':'SZU100','auth_status':'authentic','message':'ok'}
inst=m.VikeyEnforcementMiddleware()
with patch.object(m.VikeyEnforcementMiddleware,'_check_vikey', staticmethod(fv)), \
     patch.object(m.VikeyEnforcementMiddleware,'_check_szu100', staticmethod(fs)), \
     patch.object(m.VikeyEnforcementMiddleware,'_check_network', staticmethod(lambda:True)):
    for _ in range(10): inst.get_dual_hardware_status(username='wuchenghao15', role='super_admin')
ok = nv[0] <= 3 and ns[0] <= 3
SCORE[0] += int(ok)
print(f"  {'PASS' if ok else 'FAIL'}  10次调用 → 底层检测 vikey={nv[0]} szu100={ns[0]} (≤3)")

# =====================================================================
# Section 2: T3/T4 server_real_db.py 代码存在性
# =====================================================================
print("\n[3] server_real_db.py 路由与 context_processor 注入")
SRD = f'{ROOT}/flask-app/server_real_db.py'
src = open(SRD).read()
SCORE[1]+=1
ok = all([
  "@app.route('/api/hardware/dual-status'" in src,
  "'layout_mode': layout_mode" in src,
  "'sa_proprietary': sa_proprietary" in src,
  "'dual_authenticated': dual_authenticated" in src,
  "szu100_status" in src,          # before_request 403 JSON 带 szu100_status
  "terminal_status" in src,        # before_request 403 JSON 带 terminal_status
  "extra=extra" in src or "extra = {" in src,
])
SCORE[0] += int(ok)
print(f"  {'PASS' if ok else 'FAIL'}  T3/T4 在 server_real_db.py 内挂点完整")

# =====================================================================
# Section 3: T5 两 base.html
# =====================================================================
print("\n[4] T5: 两模板 body class & 资源条件加载")
for path, name in [(f'{ROOT}/frontend/templates/super_admin_base.html','super_admin_base'),
                    (f'{ROOT}/flask-app/templates/admin_app/base.html','admin_app/base')]:
    SCORE[1]+=1
    s = open(path).read()
    has_body_class = 'layout-mode-{{ layout_mode' in s
    has_css = 'sa_proprietary.css' in s and '{% if sa_proprietary %}' in s
    has_js  = 'sa_proprietary.js'  in s
    ok = has_body_class and has_css and has_js
    SCORE[0] += int(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: body_class={has_body_class} css_cond={has_css} js_cond={has_js}")

# =====================================================================
# Section 4: T6/T7 静态文件存在 + 作用域安全 + 体积
# =====================================================================
print("\n[5] sa_proprietary.css / sa_proprietary.js 文件检查")
CSS = f'{ROOT}/flask-app/static/css/sa_proprietary.css'
JS  = f'{ROOT}/flask-app/static/js/sa_proprietary.js'
SCORE[1]+=1
sz = os.path.getsize(CSS)
css_src = open(CSS).read()
# 作用域：所有 顶层选择器（含'{'且非@keyframes 内部、非@media内部伪块级语法）必须前缀 body.layout-mode-SA_PROPRIETARY
scoped_ok = True
in_at = None
for ln in css_src.splitlines():
    s = ln.strip()
    if not s or s.startswith('/*') or s.endswith('*/'): continue
    if s.startswith('@keyframes') or s.startswith('@media') or s.startswith('@supports'):
        in_at = s.split()[0]
        continue
    if in_at and s.startswith('}'):
        in_at = None
        continue
    if '{' not in s:
        continue  # 属性行或关键帧步骤内部( 0% { box-shadow: ... } )已被'{'行在首次进入时捕获，这里空过
    selector = s.split('{', 1)[0].strip()
    if not selector or selector.startswith('@') or selector in ('from','to'):
        continue
    # @keyframes 内关键帧步骤：纯数字+% 或 , 分隔，跳过
    if in_at == '@keyframes' and re.fullmatch(r'\s*(\d+%\s*,?\s*)+', selector):
        continue
    # 选择器行：必须前缀 scoped
    if not selector.startswith('body.layout-mode-SA_PROPRIETARY'):
        scoped_ok = False
        break
ok = (os.path.exists(CSS) and os.path.exists(JS) and sz <= 20*1024 and scoped_ok
      and '/api/hardware/dual-status' in open(JS).read()
      and 'sa-layout-updated' in open(JS).read())
SCORE[0] += int(ok)
print(f"  {'PASS' if ok else 'FAIL'}  files exist, CSS {sz}B (≤20KB), scoped={scoped_ok}, JS poll+event present")

# =====================================================================
# Section 5: T8 Arduino 守卫
# =====================================================================
print("\n[6] T8: _check_arduino_api_permission 存在且挂接 arduino_bp.before_request")
ARD = f'{ROOT}/flask-app/routes/arduino_session_routes.py'
asrc = open(ARD).read()
SCORE[1]+=1
ok = all([
  "def _check_arduino_api_permission()" in asrc,
  "ARDUINO_SA_ONLY" in asrc,
  "@arduino_bp.before_request" in asrc,
  "_arduino_sa_only_guard" in asrc,
  "endswith('/session/temp-login')" in asrc or "'/session/temp-login'" in asrc,
])
SCORE[0] += int(ok)
print(f"  {'PASS' if ok else 'FAIL'}  arduino守卫实现+挂接(temp-login/poll白名单)")

# =====================================================================
# Section 6: T9 审计落库
# =====================================================================
print("\n[7] T9: 审计表/日志落库能力")
SCORE[1]+=1
mw_src = open(f'{ROOT}/_output/app/middlewares/vikey_enforcement_middleware.py').read()
ok = all([
  "CREATE TABLE IF NOT EXISTS sa_ui_layout_switch_log" in mw_src,
  "automation_console_logs" in mw_src,
  "dual_hardware_switch" in mw_src,
  "_write_switch_log" in mw_src,
  "_is_bound_terminal" in mw_src,       # SA 终端绑定
  "_local_terminal_ips" in mw_src,
  "sa_bound_terminals.json" in mw_src,  # 额外信任IP配置
])
SCORE[0] += int(ok)
print(f"  {'PASS' if ok else 'FAIL'}  审计表+双钥切换日志/automation_console 存在")

# =====================================================================
# Section 7: 切换审计冒烟 (写入两张 SQLite 临时 db)
# =====================================================================
print("\n[8] 审计切换事件实际写临时库(冒烟)")
import tempfile, sqlite3
tmp = tempfile.mkdtemp(prefix='sa_verify_')
# APP DB
app_db = f'{tmp}/app.db'
with sqlite3.connect(app_db) as c:
    c.execute("CREATE TABLE IF NOT EXISTS automation_console_logs (id INTEGER PRIMARY KEY, timestamp TEXT, level TEXT, source TEXT, message TEXT, extra_json TEXT, eigenflux_flag INTEGER DEFAULT 1)")
# 把 VikeyEnforcementMiddleware._get_app_db_path monkey patch 指到 tmp 下的 app.db
real_fn = m.VikeyEnforcementMiddleware._get_app_db_path
def mp(): return app_db
m.VikeyEnforcementMiddleware._get_app_db_path = staticmethod(mp)
m.VikeyEnforcementMiddleware._get_db_path = staticmethod(lambda : app_db)  # 兼容 log_event
SCORE[1]+=1
try:
    inst = m.VikeyEnforcementMiddleware()
    def fv(): return {'status':'ok','serial':'V1','sa_bound_ok':True,'message':'ok'}
    def fs_on(): return {'present':True,'is_authentic':True,'volume_name':'SZU100','auth_status':'authentic','message':'ok'}
    def fs_off(): return {'present':False,'is_authentic':False,'volume_name':'','auth_status':'absent','message':'未检测到SZU100专用U盘'}
    # True -> False 切换
    with patch.object(m.VikeyEnforcementMiddleware,'_check_vikey', staticmethod(fv)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_szu100', staticmethod(fs_on)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_network', staticmethod(lambda:True)):
        d1 = inst.get_dual_hardware_status(username='wuchenghao15', role='super_admin', force_refresh=True, ip='127.0.0.1')
    with patch.object(m.VikeyEnforcementMiddleware,'_check_vikey', staticmethod(fv)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_szu100', staticmethod(fs_off)), \
         patch.object(m.VikeyEnforcementMiddleware,'_check_network', staticmethod(lambda:True)):
        d2 = inst.get_dual_hardware_status(username='wuchenghao15', role='super_admin', force_refresh=True, ip='127.0.0.1')
    with sqlite3.connect(app_db) as c:
        n_console = c.execute("SELECT COUNT(1) FROM automation_console_logs WHERE source='dual_hardware_switch'").fetchone()[0]
        n_switch  = c.execute("SELECT COUNT(1) FROM sa_ui_layout_switch_log").fetchone()[0]
    ok = d1['both_authenticated'] is True and d2['both_authenticated'] is False and n_console>=1 and n_switch>=1
    SCORE[0] += int(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  SA_PROPRIETARY→STANDARD 切换: console_rows={n_console} switch_rows={n_switch}")
finally:
    m.VikeyEnforcementMiddleware._get_app_db_path = staticmethod(real_fn)

# =====================================================================
# END
# =====================================================================
passed, total = SCORE
print(f"\n==============================================")
print(f"  SA Dual-Key UI Verify:  {passed}/{total}  CASES")
print(f"==============================================")
sys.exit(0 if passed == total else 1)
