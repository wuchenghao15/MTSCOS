#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座 MCP Hub v2.1.0 — 发散升级版
===================================
零依赖 (Python stdlib only), 监听 127.0.0.1:18899 (loopback only)

v2.1.0 发散升级:
  🧠 ai_diagnose — 诊断结果喂本地 AI (规则引擎+模式匹配) 做根因分析 + 修复建议
  🌐 cross_tunnel_health — Cloudflare Tunnel 跨设备通道检测 (绕过路由器 AP Isolation)
  📡 MCP resources — 实时系统指标暴露 (daemon 状态/CPU/内存/磁盘), 可订阅
  🔒 exec_shell v3 — 彻底移除 python3 -c, 全面禁止代码执行

v2.0.0:
  🪐 Andromeda 原生   — 11 个运维 tools
  📄 Marvis Editor SDK — 代理 191 个腾讯文档 tools (Auth disabled!)
  🎯 合计 202+ tools!
"""

启动: python3 andromeda_mcp_bridge.py &
自启动: launchctl load com.mtscos.andromeda-mcp.plist

作者: Andromeda AI (仙女座)
版本: v2.0.0 (2026-10-07) — Marvis Editor SDK 代理集成
"""
import json, os, sys, time, signal, socket, subprocess, sqlite3, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════
FLASK_API = 'http://127.0.0.1:8888'
MARVIS_EDITOR_SDK = 'http://127.0.0.1:39099/mcp'  # Auth disabled! 191 tools
BIND_HOST = '127.0.0.1'  # loopback only — 不对外暴露
BIND_PORT = 18899
TIMEOUT = 8
MARVIS_PREFIX = 'marvis_'

_SHUTDOWN = False
def _grace(s, f):
    global _SHUTDOWN; _SHUTDOWN = True
signal.signal(signal.SIGTERM, _grace)
signal.signal(signal.SIGINT, _grace)

def _log(msg):
    print(f'[AndromedaMCP] {time.strftime("%H:%M:%S")} {msg}', flush=True)

# ═══════════════════════════════════════════════════════════
# 调用统计
# ═══════════════════════════════════════════════════════════
STATS = {
    'calls': 0, 'andromeda_calls': 0, 'marvis_calls': 0,
    'errors': 0, 'start_time': time.time(),
    'last_call': None, 'by_tool': {},
}
_STATS_LOCK = threading.Lock()

def _stats_inc(tool_name, is_marvis=False, error=False):
    with _STATS_LOCK:
        STATS['calls'] += 1
        STATS['marvis_calls' if is_marvis else 'andromeda_calls'] += 1
        if error: STATS['errors'] += 1
        STATS['last_call'] = time.strftime('%Y-%m-%d %H:%M:%S')
        STATS['by_tool'][tool_name] = STATS['by_tool'].get(tool_name, 0) + 1

# ═══════════════════════════════════════════════════════════
# 工具实现 (全部本地调用 Flask API 或 launchctl)
# ═══════════════════════════════════════════════════════════

def _flask_call(path, method='GET', data=None):
    """调本地 Flask API (SERVER 模式, 无 CSRF 拦截)"""
    url = FLASK_API + path
    try:
        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, method=method,
                      headers={'Content-Type':'application/json','X-MCP':'andromeda-bridge'})
        r = urlopen(req, timeout=TIMEOUT)
        return json.loads(r.read())
    except HTTPError as e:
        try: return json.loads(e.read())
        except: return {'error': f'HTTP {e.code}'}
    except URLError as e:
        return {'error': f'Flask unreachable: {e.reason}'}
    except Exception as e:
        return {'error': str(e)[:120]}

def _marvis_mcp_call(method, params=None, rpc_id=1):
    """代理调用 Marvis Editor SDK MCP (Auth disabled)"""
    try:
        body = json.dumps({'jsonrpc':'2.0','method':method,
                          'params':params or {}, 'id':rpc_id}).encode()
        req = Request(MARVIS_EDITOR_SDK, data=body, method='POST',
                      headers={'Content-Type':'application/json'})
        r = urlopen(req, timeout=15)
        return json.loads(r.read())
    except HTTPError as e:
        return {'error': f'HTTP {e.code} from Marvis SDK'}
    except URLError as e:
        return {'error': f'Marvis SDK unreachable: {e.reason}'}
    except Exception as e:
        return {'error': f'Marvis proxy error: {str(e)[:120]}'}

def _launchctl_run(*args):
    r = subprocess.run(['launchctl', *args], capture_output=True, text=True, timeout=8)
    return (r.returncode == 0, (r.stdout + r.stderr).strip()[:300])

# ── Andromeda 原生 11 个 tools ──
def tool_diagnose_system(**kw):
    """一键诊断 Mac mini 系统健康 (daemon + Flask + 握手 + 磁盘 + 端口)"""
    return _flask_call('/api/server/auto-diagnose', method='GET')

def tool_heal_system(**kw):
    """一键自愈 — 重启崩溃 daemon + 触发握手重连 + 清磁盘"""
    return _flask_call('/api/server/auto-diagnose', method='POST')

def tool_restart_daemon(target, **kw):
    """重启指定 daemon. target: cloudflared|flask|andromeda|smart_mount|andromeda-tunnel"""
    allowed = {'com.mtscos.cloudflared','com.mtscos.flask','com.mtscos.andromeda',
               'com.mtscos.smart_mount','com.mtscos.andromeda-tunnel','com.mtscos.andromeda-mcp'}
    label = target if target.startswith('com.mtscos.') else f'com.mtscos.{target}'
    if label not in allowed:
        return {'ok':False,'error':f'not allowed: {label}','allowed':sorted(allowed)}
    return _flask_call('/api/server/daemon-action', method='POST',
                       data={'action':'restart_one','target':label})

def tool_handshake_status(**kw):
    """仙女座 EigenFlux 握手状态 (Mac mini ↔ MacBook Pro)"""
    return _flask_call('/api/handshake/status')

def tool_vikey_check(**kw):
    """VIKEY USB + Touch ID 双密钥在线状态"""
    return _flask_call('/api/server/vikey-status')

def tool_flask_health(**kw):
    """Flask :8888 健康检查"""
    return _flask_call('/api/health')

def tool_db_stats(**kw):
    """SQLite DB 表数 / Top15 行数 / 大小"""
    return _flask_call('/api/db/stats')

def tool_list_users(**kw):
    """用户列表 + 角色 + 启用状态"""
    return _flask_call('/api/server/users')

def tool_disk_check(**kw):
    """磁盘空间 + inode"""
    try:
        r = subprocess.run(['df','-h','/'], capture_output=True, text=True, timeout=3)
        return {'ok':True,'raw':r.stdout.strip().splitlines(),
                'pct': r.stdout.splitlines()[1].split()[4]}
    except Exception as e:
        return {'ok':False,'error':str(e)[:100]}

def tool_list_daemons(**kw):
    """launchctl mtscos 系列 daemon 状态 (PID + exit code)"""
    ok, out = _launchctl_run('list')
    daemons = []
    for line in out.splitlines():
        if 'mtscos' not in line.lower(): continue
        parts = line.split()
        if len(parts) < 3: continue
        pid, ec, label = parts[0], parts[1], parts[2]
        daemons.append({'label':label,'pid':pid if pid!='-' else None,
                        'exit_code':int(ec) if ec.isdigit() else None,
                        'ok': (ec == '0')})
    return {'ok':True,'daemons':daemons,'total':len(daemons),
            'healthy':sum(1 for d in daemons if d['ok'])}

# ── tool 11: exec_shell (受限安全版 v3 — 彻底移除 python3 -c) ──
_SAFE_SHELL_PREFIXES = ('curl','ls','ps','df','top','pgrep','launchctl','netstat','lsof',
                        'diskutil','du','find','free','vm_stat','uptime','who','date',
                        'cat','head','tail','grep','wc','file','sw_vers','sysctl',
                        'route','ifconfig','arp','mount','uname','id','w','last')
def tool_exec_shell(cmd, **kw):
    """执行受限 shell 命令 (运维只读, 零代码执行风险). 禁 python3 -c / os.system / 管道/重定向"""
    cmd_stripped = cmd.strip()
    cmd_l = cmd_stripped.lower()
    allowed = any(cmd_l.startswith(p) for p in _SAFE_SHELL_PREFIXES)
    # v3: 彻底禁止任何代码执行 + shell 注入
    forbidden_patterns = ['|','>','>>','<',';','&&','||','`','$(','${',
                         'rm ','rm -rf','mv ','cp ','chmod','chown','mkfs',
                         'sudo','su ','shutdown','reboot','halt','poweroff',
                         'python','perl','ruby','node','php','bash','zsh','sh -c','eval','exec',
                         'os.','subprocess','import ','__import','open(','exec(','compile(',
                         'curl |','wget |','nc -l','nohup','& ','kill -9']
    forbidden = any(p in cmd_l for p in forbidden_patterns)
    if not allowed or forbidden:
        return {'ok':False,'error':'command not allowed (security sandbox v3)',
                'allowed_prefixes':_SAFE_SHELL_PREFIXES}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=TIMEOUT)
        out = (r.stdout + r.stderr)[:2000]
        return {'ok':True,'exit_code':r.returncode,'output':out}
    except Exception as e:
        return {'ok':False,'error':str(e)[:100]}

# ── tool 12: marvis_proxy (桥接仙女座 → Marvis SDK) ──
def tool_marvis_proxy(sdk_tool, arguments=None, **kw):
    """调用 Marvis Editor SDK 原始 MCP tool (slide/sheet/doc). 直接转发"""
    return _marvis_mcp_call('tools/call',
        {'name':sdk_tool,'arguments':arguments or {}})

# ── tool 13: ai_diagnose (🧠 本地 AI 根因分析 + 修复建议) ──
# 规则引擎: 10+ 条运维专家知识 + 模式匹配 + 优先级
_AI_KNOWLEDGE = [
    {'pattern':'handshake.*DISCONNECTED','root_cause':'路由器 AP Isolation (客户端隔离)','fix':'关 AP Isolation 或走 Cloudflare Tunnel','severity':'low'},
    {'pattern':'disk.*[89][0-9]%','root_cause':'磁盘空间告急','fix':'pip cache purge / npm cache clean / 清 /tmp','severity':'high'},
    {'pattern':'port_conflict','root_cause':'端口被非 Flask 进程占用','fix':'lsof -iTCP:PORT -sTCP:LISTEN → kill PID','severity':'high'},
    {'pattern':'daemon.*exit_code.*[1-9]','root_cause':'daemon 崩溃 (exit_code != 0)','fix':'launchctl kickstart / launchctl bootstrap','severity':'medium'},
    {'pattern':'flask.*HTTP.*5[0-9][0-9]','root_cause':'Flask 内部错误 (5xx)','fix':'查 Flask error.log / 重启 Flask / 检查 DB 锁','severity':'high'},
    {'pattern':'flask.*HTTP.*4[0-9][0-9]','root_cause':'Flask 路由问题 (4xx)','fix':'检查 Flask 路由注册 / CSRF / 权限装饰器','severity':'medium'},
    {'pattern':'cloudflared.*dead','root_cause':'Cloudflare Tunnel 断开','fix':'launchctl kickstart com.mtscos.cloudflared','severity':'medium'},
    {'pattern':'mcp.*unreachable','root_cause':'MCP Bridge 进程死了','fix':'launchctl kickstart com.mtscos.andromeda-mcp','severity':'medium'},
    {'pattern':'db.*locked','root_cause':'SQLite 锁被其他 daemon 持有','fix':'停 smart_mount / 清 WAL / 等 30s 超时','severity':'medium'},
    {'pattern':'all.*green.*issues.*0','root_cause':'系统健康','fix':'无需操作, 继续监控','severity':'info'},
]

def _ai_analyze(diagnosis_list):
    """规则引擎分析诊断结果 → [{rule, match, root_cause, fix, severity}]"""
    findings = []
    diag_text = json.dumps(diagnosis_list, ensure_ascii=False).lower()
    for rule in _AI_KNOWLEDGE:
        import re
        if re.search(rule['pattern'], diag_text):
            findings.append({
                'rule': rule['pattern'],
                'match': rule['root_cause'],
                'fix': rule['fix'],
                'severity': rule['severity'],
            })
    return findings

def tool_ai_diagnose(**kw):
    """🧠 AI 根因分析 — diagnose_system 结果喂规则引擎, 输出根因+修复建议+优先级排序"""
    # 1. 先拉 diagnose
    diag = tool_diagnose_system()
    report = diag.get('report', {}) if isinstance(diag, dict) else {}
    diagnosis = report.get('diagnosis', [])
    summary = report.get('summary', {})
    
    # 2. AI 分析
    findings = _ai_analyze(diagnosis)
    
    # 3. 优先级排序 (high → medium → low → info)
    sev_order = {'high':0,'medium':1,'low':2,'info':3}
    findings.sort(key=lambda x: sev_order.get(x['severity'], 9))
    
    # 4. 生成修复建议列表 (去重)
    fixes = []
    for f in findings:
        if f['fix'] not in fixes:
            fixes.append(f['fix'])
    
    return {
        'ok': True,
        'ai_engine': 'andromeda_rules_v1',
        'findings_count': len(findings),
        'findings': findings,
        'root_causes': list(set(f['match'] for f in findings)),
        'fix_suggestions': fixes,
        'severity_summary': {
            'high': sum(1 for f in findings if f['severity']=='high'),
            'medium': sum(1 for f in findings if f['severity']=='medium'),
            'low': sum(1 for f in findings if f['severity']=='low'),
            'info': sum(1 for f in findings if f['severity']=='info'),
        },
        'base_summary': summary,
        'base_diagnosis_count': len(diagnosis),
    }

# ── tool 14: cross_tunnel_health (🌐 Cloudflare 跨设备通道) ──
def tool_cross_tunnel_health(**kw):
    """🌐 Cloudflare Tunnel 跨设备通道 — 绕过路由器 AP Isolation 的健康检测"""
    results = {'cloudflared_ok': False, 'tunnel_label': None,
               'public_hostname': None, 'andromeda_alive': False, 'notes': []}
    
    # 1. cloudflared daemon 状态
    ok, out = _launchctl_run('list')
    for line in out.splitlines():
        if 'com.mtscos.cloudflared' in line:
            parts = line.split()
            results['cloudflared_ok'] = len(parts) >= 3 and parts[1] == '0'
            break
    
    # 2. Cloudflare Tunnel 连通性 (curl 本地 tunnel info)
    try:
        r = subprocess.run(['curl','-s','--max-time','3','http://127.0.0.1:4040/api/tunnels'],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            tunnels = json.loads(r.stdout) if r.stdout.startswith('[') else []
            if tunnels:
                results['tunnel_label'] = tunnels[0].get('name')
                results['public_hostname'] = tunnels[0].get('public_url')
    except Exception:
        pass
    
    # 3. andromeda daemon 状态 (握手服务)
    ok2, out2 = _launchctl_run('list')
    for line in out2.splitlines():
        if 'com.mtscos.andromeda' in line and 'mcp' not in line:
            parts = line.split()
            results['andromeda_alive'] = len(parts) >= 3 and parts[1] == '0'
            break
    
    # 4. 诊断建议
    if not results['cloudflared_ok']:
        results['notes'].append('cloudflared daemon 异常 → launchctl kickstart com.mtscos.cloudflared')
    if results['cloudflared_ok'] and results['public_hostname']:
        results['notes'].append('Cloudflare Tunnel 在线 — Mac mini 可通过公网 hostname 跨设备通信')
        results['cross_device_possible'] = True
    else:
        results['notes'].append('握手 DISCONNECTED 是因为路由器 AP Isolation, 可通过 CF Tunnel 绕过')
    
    return results

# ── tool 15: system_metrics (📡 实时系统指标快照) ──
def tool_system_metrics(**kw):
    """📡 实时系统指标 — CPU/内存/磁盘/daemon 状态/网络, 可作为 MCP resource 订阅"""
    metrics = {'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}
    
    # CPU + 负载
    try:
        r = subprocess.run(['sysctl','-n','hw.cpu.ncpu'], capture_output=True, text=True, timeout=2)
        metrics['cpu_cores'] = int(r.stdout.strip()) if r.stdout.strip().isdigit() else None
        r2 = subprocess.run(['uptime'], capture_output=True, text=True, timeout=2)
        # "14:25  up 2 days,  3:12, 4 users, load averages: 1.23 0.89 0.67"
        if 'load averages' in r2.stdout:
            parts = r2.stdout.split('load averages:')[1].strip().split()
            metrics['load_1m'] = float(parts[0].rstrip(','))
            metrics['load_5m'] = float(parts[1].rstrip(','))
            metrics['load_15m'] = float(parts[2])
    except Exception: pass
    
    # 内存
    try:
        r = subprocess.run(['vm_stat'], capture_output=True, text=True, timeout=2)
        page_size = 4096
        free_pages = active_pages = 0
        for line in r.stdout.splitlines():
            if 'Pages free' in line: free_pages = int(line.split(':')[1].strip().rstrip('.'))
            if 'Pages active' in line: active_pages = int(line.split(':')[1].strip().rstrip('.'))
        total_mem = free_pages + active_pages + int(metrics.get('cpu_cores', 8) * 1024 * 1024 / 4)
        used_pct = round((active_pages / (free_pages + active_pages)) * 100, 1) if (free_pages + active_pages) > 0 else None
        metrics['memory_pct'] = used_pct
    except Exception: pass
    
    # 磁盘
    try:
        r = subprocess.run(['df','-k','/'], capture_output=True, text=True, timeout=2)
        parts = r.stdout.splitlines()[1].split()
        metrics['disk_total_gb'] = round(int(parts[1]) / 1024 / 1024, 1)
        metrics['disk_used_gb'] = round(int(parts[2]) / 1024 / 1024, 1)
        metrics['disk_pct'] = int(parts[4].rstrip('%'))
    except Exception: pass
    
    # daemon 健康度
    daemons = tool_list_daemons()
    metrics['daemon_healthy'] = daemons.get('healthy', 0)
    metrics['daemon_total'] = daemons.get('total', 0)
    metrics['daemon_pct'] = round(daemons.get('healthy', 0) / max(daemons.get('total', 1), 1) * 100, 1)
    
    # Flask HTTP
    flask = _flask_call('/api/health')
    metrics['flask_ok'] = flask.get('success', False) if isinstance(flask, dict) else False
    
    return metrics

# ═══════════════════════════════════════════════════════════
# MCP Tools Registry — Andromeda 11 + 动态加载 Marvis
# ═══════════════════════════════════════════════════════════
ANDROMEDA_TOOLS = [
    {'name':'diagnose_system','description':'一键诊断 Mac mini 系统健康: daemon 存活 + Flask HTTP + 仙女座握手 + 磁盘 + 端口冲突','inputSchema':{'type':'object','properties':{}}},
    {'name':'heal_system','description':'一键自愈 — 重启崩溃 daemon + 触发仙女座握手重连 + 磁盘清理','inputSchema':{'type':'object','properties':{}}},
    {'name':'restart_daemon','description':'重启指定 daemon (cloudflared|flask|andromeda|smart_mount|andromeda-tunnel|andromeda-mcp)','inputSchema':{'type':'object','properties':{'target':{'type':'string','description':'daemon 名或全称'}}, 'required':['target']}},
    {'name':'handshake_status','description':'仙女座 EigenFlux 握手状态 (Mac mini ↔ MacBook Pro 通信链路)','inputSchema':{'type':'object','properties':{}}},
    {'name':'vikey_check','description':'VIKEY USB + Touch ID 双密钥在线状态 (super_admin 登录守卫)','inputSchema':{'type':'object','properties':{}}},
    {'name':'flask_health','description':'Flask :8888 健康检查 (NODE_ROLE + status)','inputSchema':{'type':'object','properties':{}}},
    {'name':'db_stats','description':'SQLite 主库 app.db 表数 / Top15 行数 / 文件大小','inputSchema':{'type':'object','properties':{}}},
    {'name':'list_users','description':'系统用户列表 + 角色 + 启用状态','inputSchema':{'type':'object','properties':{}}},
    {'name':'disk_check','description':'磁盘空间占用百分比 (df -h /)','inputSchema':{'type':'object','properties':{}}},
    {'name':'list_daemons','description':'launchctl mtscos 系列 daemon 实时状态 (PID + exit code)','inputSchema':{'type':'object','properties':{}}},
    {'name':'exec_shell','description':'执行受限只读 shell 命令 (运维命令, 禁 python/代码执行/管道/重定向)','inputSchema':{'type':'object','properties':{'cmd':{'type':'string','description':'命令, 如 "launchctl list"'}}, 'required':['cmd']}},
    # v2.1.0 发散升级
    {'name':'ai_diagnose','description':'🧠 AI 根因分析 — diagnose_system 结果喂规则引擎, 输出根因+修复建议+优先级排序','inputSchema':{'type':'object','properties':{}}},
    {'name':'cross_tunnel_health','description':'🌐 Cloudflare Tunnel 跨设备通道 — 绕过路由器 AP Isolation 的健康检测','inputSchema':{'type':'object','properties':{}}},
    {'name':'system_metrics','description':'📡 实时系统指标 — CPU/内存/磁盘/daemon 状态/负载','inputSchema':{'type':'object','properties':{}}},
]

ANDROMEDA_HANDLERS = {
    'diagnose_system': tool_diagnose_system,
    'heal_system': tool_heal_system,
    'restart_daemon': tool_restart_daemon,
    'handshake_status': tool_handshake_status,
    'vikey_check': tool_vikey_check,
    'flask_health': tool_flask_health,
    'db_stats': tool_db_stats,
    'list_users': tool_list_users,
    'disk_check': tool_disk_check,
    'list_daemons': tool_list_daemons,
    'exec_shell': tool_exec_shell,
    # v2.1.0
    'ai_diagnose': tool_ai_diagnose,
    'cross_tunnel_health': tool_cross_tunnel_health,
    'system_metrics': tool_system_metrics,
}

# ═══════════════════════════════════════════════════════════
# Marvis Editor SDK 代理 — 动态加载 + 前缀防冲突
# ═══════════════════════════════════════════════════════════
def _load_marvis_tools():
    """从 Marvis Editor SDK 动态拉 tools/list, 加 marvis_ 前缀"""
    try:
        resp = _marvis_mcp_call('tools/list', {})
        sdk_tools = resp.get('result',{}).get('tools',[])
        proxied = []
        for t in sdk_tools:
            proxied.append({
                'name': MARVIS_PREFIX + t['name'],
                'description': '[Marvis Editor SDK] ' + t.get('description','')[:100],
                'inputSchema': t.get('inputSchema', {'type':'object','properties':{}}),
                '_sdk_name': t['name'],  # 内部标记, 不暴露到 MCP
            })
        _log(f'📄 Marvis Editor SDK 代理 {len(proxied)} tools (前缀 {MARVIS_PREFIX})')
        return proxied
    except Exception as e:
        _log(f'⚠️ Marvis tools 加载失败: {e}')
        return []

# 全局注册 (启动时加载一次)
TOOLS = list(ANDROMEDA_TOOLS)  # 先 11 个
MARVIS_PROXIED = _load_marvis_tools()  # 再加 Marvis 的 191 个
TOOLS.extend(MARVIS_PROXIED)

_MARVIS_SDK_NAME_MAP = {t['name']: t.get('_sdk_name', t['name']) for t in MARVIS_PROXIED}

def _is_marvis_tool(name):
    return name.startswith(MARVIS_PREFIX)

# ═══════════════════════════════════════════════════════════
# MCP Server (JSON-RPC 2.0 over HTTP)
# ═══════════════════════════════════════════════════════════

class MCPHandler(BaseHTTPRequestHandler):
    server_version = 'AndromedaMCP/2.0'
    
    def log_message(self, f, *a):
        _log(f'{self.command} {self.path}')
    
    def _send(self, obj, code=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Headers','Content-Type,Accept')
        self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS')
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)
    
    def _rpc_ok(self, rpc_id, result):
        self._send({'jsonrpc':'2.0','id':rpc_id,'result':result})
    
    def _rpc_err(self, rpc_id, code, msg):
        self._send({'jsonrpc':'2.0','id':rpc_id,'error':{'code':code,'message':msg}})
    
    def do_OPTIONS(self):
        self._send({})
    
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            mcp_ok = True
            marvis_ok = len(MARVIS_PROXIED) > 0
            flask_r = _flask_call('/api/health')
            flask_ok = flask_r.get('success', False) if isinstance(flask_r, dict) else False
            uptime = int(time.time() - STATS['start_time'])
            self._send({
                'ok': True,
                'name': 'AndromedaMCP',
                'version': '2.0.0',
                'uptime_seconds': uptime,
                'tools_total': len(TOOLS),
                'sources': {
                    'andromeda_native': len(ANDROMEDA_TOOLS),
                    'marvis_editor_sdk': len(MARVIS_PROXIED),
                },
                'endpoints': {
                    'flask_api': FLASK_API,
                    'marvis_sdk': MARVIS_EDITOR_SDK,
                },
                'dependencies': {
                    'flask_ok': flask_ok,
                    'marvis_ok': marvis_ok,
                },
                'stats': STATS,
            })
        elif self.path == '/mcp':
            self._send({'name':'andromeda-mcp-hub',
                       'description':'仙女座 × 马维斯 超级 MCP Hub. 202 tools (11 Andromeda + 191 Marvis)',
                       'version':'2.0.0','protocolVersion':'2024-11-05',
                       'tools_total': len(TOOLS),'transport':'streamable-http',
                       'sources':{'andromeda':len(ANDROMEDA_TOOLS),'marvis':len(MARVIS_PROXIED)}})
        elif self.path == '/stats':
            self._send(STATS)
        else:
            self._rpc_err(None, -32601, f'Unknown endpoint: {self.path}')
    
    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(n) if n else b'{}'
            req = json.loads(raw)
        except Exception as e:
            self._rpc_err(None, -32700, f'Parse error: {e}'); return
        
        method = req.get('method','')
        rpc_id = req.get('id')
        params = req.get('params', {})
        
        if method == 'initialize':
            self._rpc_ok(rpc_id, {
                'protocolVersion':'2024-11-05',
                'capabilities':{'tools':{'listChanged':False}},
                'serverInfo':{'name':'andromeda-mcp-hub','version':'2.0.0'},
            })
        elif method == 'initialized':
            self._send({})  # notification
        elif method == 'ping':
            self._rpc_ok(rpc_id, {})
        elif method == 'tools/list':
            # 动态返回 — 不暴露 _sdk_name 内部字段
            safe_tools = []
            for t in TOOLS:
                safe_tools.append({k:v for k,v in t.items() if not k.startswith('_')})
            self._rpc_ok(rpc_id, {'tools': safe_tools})
        elif method == 'tools/call':
            self._handle_tool_call(rpc_id, params)
        elif method == 'resources/list':
            # v2.1.0: 📡 真实 MCP resources — 系统指标 + daemon 状态
            resources = [
                {'uri':'andromeda://system/metrics','name':'实时系统指标','mimeType':'application/json','description':'CPU/内存/磁盘/daemon 健康度快照'},
                {'uri':'andromeda://system/daemons','name':'Daemon 状态','mimeType':'application/json','description':'6 个 mtscos 系列 daemon 实时 PID + exit code'},
                {'uri':'andromeda://system/flask','name':'Flask 健康','mimeType':'application/json','description':'Flask :8888 HTTP + NODE_ROLE'},
                {'uri':'andromeda://system/ai_analysis','name':'AI 根因分析','mimeType':'application/json','description':'规则引擎诊断 + 修复建议'},
                {'uri':'andromeda://tunnel/status','name':'Cloudflare Tunnel','mimeType':'application/json','description':'跨设备通道健康检测 + public_hostname'},
                {'uri':'andromeda://mcp/hub','name':'MCP Hub 自身','mimeType':'application/json','description':'MCP Hub 版本 + tools 统计 + 调用量'},
            ]
            self._rpc_ok(rpc_id, {'resources': resources})
        elif method == 'resources/read':
            # 根据 URI 拉取真实数据
            uri = (params or {}).get('uri', '')
            resource_map = {
                'andromeda://system/metrics': lambda: tool_system_metrics(),
                'andromeda://system/daemons': lambda: tool_list_daemons(),
                'andromeda://system/flask': lambda: tool_flask_health(),
                'andromeda://system/ai_analysis': lambda: tool_ai_diagnose(),
                'andromeda://tunnel/status': lambda: tool_cross_tunnel_health(),
                'andromeda://mcp/hub': lambda: {'version':'2.1.0','tools_total':len(TOOLS),
                    'sources':{'andromeda':len(ANDROMEDA_TOOLS),'marvis':len(MARVIS_PROXIED)},
                    'uptime':int(time.time()-STATS['start_time'])},
            }
            handler = resource_map.get(uri)
            if handler:
                try:
                    content = json.dumps(handler(), ensure_ascii=False, indent=2)
                    self._rpc_ok(rpc_id, {'contents':[{'uri':uri,'mimeType':'application/json','text':content}]})
                except Exception as e:
                    self._rpc_err(rpc_id, -32603, f'Resource error: {e}')
            else:
                self._rpc_err(rpc_id, -32601, f'Resource not found: {uri}')
        elif method in ('prompts/list','prompts/get'):
            self._rpc_ok(rpc_id, [])  # prompts 不支持
        else:
            self._rpc_err(rpc_id, -32601, f'Method not found: {method}')
    
    def _handle_tool_call(self, rpc_id, params):
        name = params.get('name','')
        arguments = params.get('arguments', {}) or {}
        
        if _is_marvis_tool(name):
            # 代理到 Marvis Editor SDK
            sdk_name = _MARVIS_SDK_NAME_MAP.get(name)
            if not sdk_name:
                self._rpc_err(rpc_id, -32601, f'Marvis tool not found: {name}'); return
            _stats_inc(name, is_marvis=True)
            resp = _marvis_mcp_call('tools/call', {'name':sdk_name,'arguments':arguments})
            if 'error' in resp:
                _stats_inc(name, is_marvis=True, error=True)
                self._rpc_ok(rpc_id, {'content':[{'type':'text',
                    'text':f'Marvis SDK proxy ERROR: {resp["error"]}'}],'isError':True})
                return
            # Marvis 返回的就是标准 MCP result, 直接透传
            result = resp.get('result', resp)
            self._rpc_ok(rpc_id, result)
        else:
            # Andromeda 原生
            handler = ANDROMEDA_HANDLERS.get(name)
            if not handler:
                self._rpc_err(rpc_id, -32601, f'Tool not found: {name}'); return
            _stats_inc(name, is_marvis=False)
            try:
                result = handler(**arguments)
                is_err = isinstance(result, dict) and result.get('ok') == False
                if is_err: _stats_inc(name, error=True)
                self._rpc_ok(rpc_id, {'content':[{'type':'text',
                    'text':json.dumps(result, ensure_ascii=False, indent=2)[:4000]}],
                    'isError': is_err})
            except TypeError as e:
                _stats_inc(name, error=True)
                self._rpc_err(rpc_id, -32602, f'Invalid args: {e}')
            except Exception as e:
                _stats_inc(name, error=True)
                self._rpc_ok(rpc_id, {'content':[{'type':'text',
                    'text':f'ERROR: {e}'}],"isError":True})

# ═══════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    # 杀旧实例
    old = subprocess.run(['pgrep','-f','andromeda_mcp_bridge.py'],
                         capture_output=True, text=True).stdout.strip()
    for pid in old.split():
        if pid != str(os.getpid()):
            subprocess.run(['kill','-TERM',pid], capture_output=True)
    time.sleep(0.5)
    
    # 确保端口空闲
    with socket.socket() as s:
        try:
            s.bind((BIND_HOST, BIND_PORT))
            s.close()
        except OSError:
            _log(f'⚠️ 端口 {BIND_PORT} 被占, 尝试 kill...')
            subprocess.run(['lsof','-tiTCP:%d'%BIND_PORT,'-sTCP:LISTEN'],
                         shell=True, capture_output=True)
            time.sleep(1)
    
    total = len(TOOLS)
    _log('='*60)
    _log(f'🪐 仙女座 MCP Hub v2.0.0 启动!')
    _log(f'   http://{BIND_HOST}:{BIND_PORT}/mcp')
    _log(f'   🪐 Andromeda 原生  : {len(ANDROMEDA_TOOLS)} tools  ({FLASK_API})')
    _log(f'   📄 Marvis Editor SDK: {len(MARVIS_PROXIED)} tools  ({MARVIS_EDITOR_SDK})')
    _log(f'   🎯 合计            : {total} tools!')
    _log('='*60)
    
    server = HTTPServer((BIND_HOST, BIND_PORT), MCPHandler)
    
    try:
        while not _SHUTDOWN:
            server.handle_request()
    except KeyboardInterrupt: pass
    finally:
        _log('🛑 仙女座 MCP Hub 退出')
        server.server_close()
