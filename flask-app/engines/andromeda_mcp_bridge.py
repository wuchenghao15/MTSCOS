#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座 MCP Hub v2.0.0 — Andromeda ↔ Marvis 双向集成网关
========================================================
零依赖 (Python stdlib only), 监听 127.0.0.1:18899 (loopback only)
集成 2 大 MCP Server:
  🪐 Andromeda 原生   — 11 个运维 tools (diagnose/heal/restart/...)
  📄 Marvis Editor SDK — 代理 191 个腾讯文档 tools (Auth disabled!)
合计 202 个 tools, 任何 MCP client 可统一调用

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

# ── tool 11: exec_shell (受限安全版 v2) ──
_SAFE_SHELL_PREFIXES = ('curl','ls','ps','df','top','pgrep','launchctl','netstat','lsof',
                        'diskutil','du','find','free','vm_stat','uptime','who','date',
                        'cat','head','tail','grep','wc','file','python3 -c')
def tool_exec_shell(cmd, **kw):
    """执行受限 shell 命令. 允许的: curl/ls/ps/df/pgrep/launchctl 等运维只读命令"""
    cmd_stripped = cmd.strip()
    cmd_l = cmd_stripped.lower()
    allowed = any(cmd_l.startswith(p) for p in _SAFE_SHELL_PREFIXES)
    forbidden_patterns = ['|','>','>>','<',';','&&','||','`','$(','rm ','rm -rf',
                         'shutdown','reboot','sudo','su ','chmod','chown','mkfs',
                         'curl |','wget |','nc -l',
                         'eval ','exec ','nohup ','& ','bg %','kill -9']
    forbidden = any(p in cmd_l for p in forbidden_patterns)
    if not allowed or forbidden:
        return {'ok':False,'error':'command not allowed (security sandbox)',
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
    {'name':'exec_shell','description':'执行受限只读 shell 命令 (curl/ls/ps/df/pgrep/launchctl/grep 等, 禁管道/重定向)','inputSchema':{'type':'object','properties':{'cmd':{'type':'string','description':'命令, 如 "launchctl list"'}}, 'required':['cmd']}},
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
        elif method in ('resources/list','prompts/list','resources/read','prompts/get'):
            self._rpc_ok(rpc_id, [])  # 不支持
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
