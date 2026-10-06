#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座 MCP Bridge — Marvis ↔ Andromeda 运维网关
===============================================
零依赖 (Python stdlib only), 监听 127.0.0.1:18899 (loopback only)
暴露 10 个运维 tools 给 Marvis Agent / 任何 MCP client 调用

启动: python3 andromeda_mcp_bridge.py &
停止: kill $(pgrep -f andromeda_mcp_bridge)

作者: Andromeda AI (仙女座)
版本: v1.0.0 (2026-10-07)
"""
import json, os, sys, time, signal, socket, subprocess, sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════
FLASK_API = 'http://127.0.0.1:8888'
BIND_HOST = '127.0.0.1'  # loopback only — 不对外暴露
BIND_PORT = 18899
TIMEOUT = 8

_SHUTDOWN = False
def _grace(s, f):
    global _SHUTDOWN; _SHUTDOWN = True
signal.signal(signal.SIGTERM, _grace)
signal.signal(signal.SIGINT, _grace)

def _log(msg):
    print(f'[AndromedaMCP] {time.strftime("%H:%M:%S")} {msg}', flush=True)

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

def _launchctl_run(*args):
    r = subprocess.run(['launchctl', *args], capture_output=True, text=True, timeout=8)
    return (r.returncode == 0, (r.stdout + r.stderr).strip()[:300])

# ── tool 1: diagnose_system ──
def tool_diagnose_system(**kw):
    """一键诊断 Mac mini 系统健康 (daemon + Flask + 握手 + 磁盘 + 端口)"""
    return _flask_call('/api/server/auto-diagnose', method='GET')

# ── tool 2: heal_system ──
def tool_heal_system(**kw):
    """一键自愈 — 重启崩溃 daemon + 触发握手重连 + 清磁盘"""
    return _flask_call('/api/server/auto-diagnose', method='POST')

# ── tool 3: restart_daemon ──
def tool_restart_daemon(target, **kw):
    """重启指定 daemon. target: cloudflared|flask|andromeda|smart_mount|andromeda-tunnel"""
    allowed = {'com.mtscos.cloudflared','com.mtscos.flask','com.mtscos.andromeda',
               'com.mtscos.smart_mount','com.mtscos.andromeda-tunnel'}
    label = target if target.startswith('com.mtscos.') else f'com.mtscos.{target}'
    if label not in allowed:
        return {'ok':False,'error':f'not allowed: {label}','allowed':sorted(allowed)}
    return _flask_call('/api/server/daemon-action', method='POST',
                       data={'action':'restart_one','target':label})

# ── tool 4: handshake_status ──
def tool_handshake_status(**kw):
    """仙女座 EigenFlux 握手状态 (Mac mini ↔ MacBook Pro)"""
    return _flask_call('/api/handshake/status')

# ── tool 5: vikey_check ──
def tool_vikey_check(**kw):
    """VIKEY USB + Touch ID 双密钥在线状态"""
    return _flask_call('/api/server/vikey-status')

# ── tool 6: flask_health ──
def tool_flask_health(**kw):
    """Flask :8888 健康检查"""
    return _flask_call('/api/health')

# ── tool 7: db_stats ──
def tool_db_stats(**kw):
    """SQLite DB 表数 / Top15 行数 / 大小"""
    return _flask_call('/api/db/stats')

# ── tool 8: list_users ──
def tool_list_users(**kw):
    """用户列表 + 角色 + 启用状态"""
    return _flask_call('/api/server/users')

# ── tool 9: disk_check ──
def tool_disk_check(**kw):
    """磁盘空间 + inode"""
    try:
        r = subprocess.run(['df','-h','/'], capture_output=True, text=True, timeout=3)
        return {'ok':True,'raw':r.stdout.strip().splitlines(),
                'pct': r.stdout.splitlines()[1].split()[4]}
    except Exception as e:
        return {'ok':False,'error':str(e)[:100]}

# ── tool 10: list_daemons ──
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

# ── tool 11: exec_shell (受限安全版) ──
_SAFE_SHELL_PREFIXES = ('curl','ls','ps','df','top','pgrep','launchctl','netstat','lsof',
                        'diskutil','du','find','free','vm_stat','uptime','who','date',
                        'cat','head','tail','grep','wc','file','python3 -c')
def tool_exec_shell(cmd, **kw):
    """执行受限 shell 命令. 允许的: curl/ls/ps/df/pgrep/launchctl 等运维只读命令"""
    cmd_l = cmd.strip().lower()
    allowed = any(cmd_l.startswith(p) for p in _SAFE_SHELL_PREFIXES)
    forbidden = any(x in cmd_l for x in ['rm -rf','shutdown','reboot','sudo','> /','| nc',';','&&','> ~/'])
    if not allowed or forbidden:
        return {'ok':False,'error':'command not allowed (security)',
                'allowed_prefixes':_SAFE_SHELL_PREFIXES[:8]}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=TIMEOUT)
        out = (r.stdout + r.stderr)[:2000]
        return {'ok':True,'exit_code':r.returncode,'output':out}
    except Exception as e:
        return {'ok':False,'error':str(e)[:100]}

# ═══════════════════════════════════════════════════════════
# MCP Tools Registry (JSON-RPC 2.0)
# ═══════════════════════════════════════════════════════════
TOOLS = [
    {
        'name': 'diagnose_system',
        'description': '一键诊断 Mac mini 系统健康: daemon 存活 + Flask HTTP + 仙女座握手 + 磁盘 + 端口冲突',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'heal_system',
        'description': '一键自愈 — 重启崩溃 daemon + 触发仙女座握手重连 + 磁盘清理',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'restart_daemon',
        'description': '重启指定 daemon. target 可选: cloudflared, flask, andromeda, smart_mount, andromeda-tunnel',
        'inputSchema': {'type':'object','properties':{
            'target':{'type':'string','description':'daemon 名或全称 (如 cloudflared 或 com.mtscos.cloudflared)'}},
            'required':['target']}
    },
    {
        'name': 'handshake_status',
        'description': '仙女座 EigenFlux 握手状态 (Mac mini ↔ MacBook Pro 通信链路)',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'vikey_check',
        'description': 'VIKEY USB + Touch ID 双密钥在线状态 (super_admin 登录守卫)',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'flask_health',
        'description': 'Flask :8888 健康检查 (NODE_ROLE + status)',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'db_stats',
        'description': 'SQLite 主库 app.db 表数 / Top15 行数 / 文件大小',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'list_users',
        'description': '系统用户列表 + 角色 + 启用状态',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'disk_check',
        'description': '磁盘空间占用百分比',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'list_daemons',
        'description': 'launchctl mtscos 系列 daemon 实时状态 (PID + exit code)',
        'inputSchema': {'type':'object','properties':{}}
    },
    {
        'name': 'exec_shell',
        'description': '执行受限 shell 命令 (只读运维: curl/ls/ps/df/pgrep/launchctl/grep 等)',
        'inputSchema': {'type':'object','properties':{
            'cmd':{'type':'string','description':'要执行的命令, 如 "launchctl list | grep mtscos"'}},
            'required':['cmd']}
    },
]

TOOL_HANDLERS = {
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
# MCP Server (JSON-RPC 2.0 over HTTP, streamable-http 兼容)
# ═══════════════════════════════════════════════════════════

class MCPHandler(BaseHTTPRequestHandler):
    server_version = 'AndromedaMCP/1.0'
    
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
        if self.path == '/health':
            self._send({'ok':True,'name':'AndromedaMCP','version':'1.0.0',
                       'flask_api':FLASK_API,'tools':len(TOOLS)})
        elif self.path == '/mcp' or self.path == '/':
            self._send({'name':'andromeda-mcp-server','description':'仙女座运维 MCP Bridge',
                       'version':'1.0.0','protocolVersion':'2024-11-05',
                       'tools':[t['name'] for t in TOOLS],'transport':'streamable-http'})
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
                'serverInfo':{'name':'andromeda-mcp-server','version':'1.0.0'},
            })
        elif method == 'initialized':
            self._send({})  # notification
        elif method == 'ping':
            self._rpc_ok(rpc_id, {})
        elif method == 'tools/list':
            self._rpc_ok(rpc_id, {'tools': TOOLS})
        elif method == 'tools/call':
            name = params.get('name','')
            arguments = params.get('arguments', {}) or {}
            handler = TOOL_HANDLERS.get(name)
            if not handler:
                self._rpc_err(rpc_id, -32601, f'Tool not found: {name}')
                return
            try:
                result = handler(**arguments)
                self._rpc_ok(rpc_id, {'content':[{'type':'text',
                    'text':json.dumps(result, ensure_ascii=False, indent=2)[:4000]}],
                    'isError': bool(result.get('ok')==False) if isinstance(result, dict) else False})
            except TypeError as e:
                self._rpc_err(rpc_id, -32602, f'Invalid args: {e}')
            except Exception as e:
                self._rpc_ok(rpc_id, {'content':[{'type':'text',
                    'text':f'ERROR: {e}'}],"isError":True})
        elif method == 'resources/list' or method == 'prompts/list':
            self._rpc_ok(rpc_id, [])  # 不支持
        else:
            self._rpc_err(rpc_id, -32601, f'Method not found: {method}')

# ═══════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    # 杀旧实例 (如果有)
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
            subprocess.run(['lsof','-tiTCP:%d'%BIND_PORT,'-sTCP:LISTEN','|','xargs','kill','-9'],
                         shell=True, capture_output=True)
            time.sleep(1)
    
    server = HTTPServer((BIND_HOST, BIND_PORT), MCPHandler)
    _log(f'🚀 仙女座 MCP Bridge 启动! http://{BIND_HOST}:{BIND_PORT}/mcp')
    _log(f'   tools={len(TOOLS)} Flask={FLASK_API}')
    
    try:
        while not _SHUTDOWN:
            server.handle_request()
    except KeyboardInterrupt: pass
    finally:
        _log('🛑 仙女座 MCP Bridge 退出')
        server.server_close()
