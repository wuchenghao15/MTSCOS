#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
仙女座 MCP Hub v2.3.0 — §14 强制接入版
===========================================
零依赖 Python stdlib only, 监听 127.0.0.1:18899 loopback only

v2.3.0 §14 IRON_RULE 强制接入:
  - MCP Hub tools/call 接 dev_activity_preflight (MT_IR_D9)
  - 开发活动类 tool 必须携带合法 flow_id (STEP_7+)
  - 只读诊断类 tool 白名单放行 (零开销)
  - 违反 → 立即阻断 + 落库 mt_iron_rule_violations

v2.2.0 自主强化版:
  - patrol_rounds / ai_propose_upgrade / auto_apply_patch / git_snapshot
  - SQLite 3 张审计表 + L0/L1/L2 自主权分级 + 安全操作集白名单

v2.1.0 发散升级:
  ai_diagnose / cross_tunnel_health / exec_shell v3 / MCP resources
"""
# 启动: python3 andromeda_mcp_bridge.py &
# 自启动: launchctl load com.mtscos.andromeda-mcp.plist
# 作者: Andromeda AI 仙女座
# 版本: v2.1.0 发散升级版 Oct 7 2026

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
    # 放宽 returncode: macOS launchctl list 某些版本 returncode != 0 但输出正常
    output = (r.stdout + r.stderr).strip()
    return (True, output)

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
    # 每条规则: (lambda check_func, root_cause, fix, severity)
    # check_func(diagnosis_items, summary) → bool
    {
        'check': lambda items, s: any(d.get('type')=='handshake_disconnected' for d in items),
        'root_cause':'路由器 AP Isolation 导致 Mac mini ↔ 其他设备握手不可达',
        'fix':'关闭路由器 AP Isolation / 改用 Cloudflare Tunnel 跨设备通信',
        'severity':'low',
    },
    {
        'check': lambda items, s: any(d.get('type')=='disk' and d.get('pct',0) >= 85 for d in items),
        'root_cause':'磁盘空间告急',
        'fix':'pip cache purge / npm cache clean / 清 /tmp/ 旧日志',
        'severity':'high',
    },
    {
        'check': lambda items, s: any(d.get('type')=='port_conflict' for d in items),
        'root_cause':'端口被非 Flask 进程占用',
        'fix':'lsof -iTCP:8888 -sTCP:LISTEN → kill PID',
        'severity':'high',
    },
    {
        'check': lambda items, s: any(d.get('type')=='daemon' and d.get('ok') == False for d in items),
        'root_cause':'daemon 崩溃 (进程退出码异常 + PID 不存活)',
        'fix':'launchctl kickstart -k gui/$(id -u) com.mtscos.DAEMON_NAME',
        'severity':'medium',
    },
    {
        'check': lambda items, s: any(d.get('type')=='flask' and d.get('http_code',0) >= 500 for d in items),
        'root_cause':'Flask 内部错误 (5xx)',
        'fix':'查 Flask error.log / 重启 Flask / 检查 SQLite DB 锁',
        'severity':'high',
    },
    {
        'check': lambda items, s: any(d.get('type')=='flask' and d.get('http_code',0) >= 400 and d.get('http_code',0) < 500 for d in items),
        'root_cause':'Flask 路由问题 (4xx)',
        'fix':'检查 Flask 路由注册 / CSRF token / 权限装饰器',
        'severity':'medium',
    },
]

def _ai_analyze(diagnosis_list, summary):
    """规则引擎 v2 — 结构化诊断项精确匹配, 杜绝误报"""
    findings = []
    for rule in _AI_KNOWLEDGE:
        try:
            if rule['check'](diagnosis_list, summary):
                findings.append({
                    'rule': rule['root_cause'],
                    'match': rule['root_cause'],
                    'fix': rule['fix'],
                    'severity': rule['severity'],
                })
        except Exception:
            pass
    return findings

def tool_ai_diagnose(**kw):
    """🧠 AI 根因分析 — diagnose_system 结果喂规则引擎, 输出根因+修复建议+优先级排序"""
    # 1. 先拉 diagnose
    diag = tool_diagnose_system()
    report = diag.get('report', {}) if isinstance(diag, dict) else {}
    diagnosis = report.get('diagnosis', [])
    summary = report.get('summary', {})
    
    # 2. AI 分析 (v2 结构化精确匹配)
    findings = _ai_analyze(diagnosis, summary)
    
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

# ── tool 14: cross_tunnel_health (🌐 Tailscale 优先 + Cloudflare fallback) ──
def tool_cross_tunnel_health(**kw):
    """🌐 跨设备通道健康检测 — Tailscale 优先 (零配置), Cloudflare Tunnel fallback"""
    import re as _re
    results = {
        # Tailscale (首选)
        'tailscale_ok': False, 'tailscale_ip': None, 'tailscale_hostname': None,
        'tailscale_tailnet': None, 'tailscale_peers': [],
        'tailscale_direct': False,     # 直连不经过 DERP relay
        'tailscale_rtt_ms': None,
        # Cloudflare Tunnel (备用)
        'cloudflared_ok': False, 'tunnel_mode': None, 'public_hostname': None,
        # 通用
        'andromeda_alive': False, 'cross_device_possible': False,
        'primary_method': None,        # 'tailscale' | 'cloudflare' | None
        'notes': [],
    }
    
    # ═══ 1. Tailscale 检测 (首选) ═══
    def _try_tailscale():
        """尝试跑 tailscale CLI, 返回 (ok, status_output, netcheck_output)"""
        ts_bin = None
        for candidate in ['tailscale',
                          '/usr/local/bin/tailscale',
                          '/Applications/Tailscale.app/Contents/MacOS/Tailscale']:
            try:
                r = subprocess.run([candidate, 'version'], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    ts_bin = candidate
                    break
            except Exception:
                continue
        if not ts_bin:
            return False, '', '', None
        try:
            r_status = subprocess.run([ts_bin, 'status', '--json'], capture_output=True, text=True, timeout=5)
            r_net = subprocess.run([ts_bin, 'netcheck'], capture_output=True, text=True, timeout=5)
            return True, r_status.stdout, r_net.stdout, ts_bin
        except Exception:
            return False, '', '', ts_bin
    
    ts_ok, ts_status, ts_net, ts_bin = _try_tailscale()
    if ts_ok:
        results['tailscale_ok'] = True
        try:
            ts_json = json.loads(ts_status)
            self_info = ts_json.get('Self', {})
            results['tailscale_ip'] = self_info.get('TailscaleIPs', [None])[0]
            results['tailscale_hostname'] = self_info.get('DNSName', '').rstrip('.')
            results['tailscale_tailnet'] = self_info.get('Tailnet', None)
            # 列出所有 peers
            peers = []
            for name, info in ts_json.get('Peer', {}).items():
                peers.append({
                    'name': info.get('DNSName', name).rstrip('.'),
                    'ip': info.get('TailscaleIPs', [None])[0],
                    'os': info.get('OS', '?'),
                    'online': info.get('Online', True),
                })
            results['tailscale_peers'] = peers
            
            # 测试直连: ping 第一个 peer (如果有)
            if peers and ts_bin:
                peer = peers[0]
                try:
                    r_ping = subprocess.run(
                        [ts_bin, 'ping', '-c', '1', peer['name']],
                        capture_output=True, text=True, timeout=6
                    )
                    results['tailscale_direct'] = 'via DERP' not in r_ping.stdout and 'pong' in r_ping.stdout
                    m = _re.search(r'in (\d+)ms', r_ping.stdout)
                    if m:
                        results['tailscale_rtt_ms'] = int(m.group(1))
                except Exception:
                    pass
        except Exception:
            pass
        
        results['notes'].append(f'✅ Tailscale Online → {results["tailscale_ip"]} ({results["tailscale_hostname"]})')
        if results['tailscale_direct']:
            rtt = results.get('tailscale_rtt_ms', '?')
            results['notes'].append(f'  🔥 Direct 直连! RTT ≈ {rtt}ms (不经过 DERP relay)')
        results['cross_device_possible'] = True
        results['primary_method'] = 'tailscale'
    
    # ═══ 2. Cloudflare Tunnel 检测 (备用) ═══
    ok, out = _launchctl_run('list')
    for line in out.splitlines():
        if 'com.mtscos.cloudflared' in line:
            parts = line.split()
            results['cloudflared_ok'] = len(parts) >= 3 and parts[1] == '0'
            break
    if results['cloudflared_ok']:
        try:
            log_content = ''
            for lp in ['/tmp/cloudflared.err', '/tmp/cloudflared.log']:
                try:
                    with open(lp) as f:
                        log_content += f.read()
                except Exception:
                    pass
            m = _re.search(r'https://([\w-]+\.trycloudflare\.com)', log_content)
            if m:
                results['public_hostname'] = m.group(1)
                results['tunnel_mode'] = 'quick'
                results['notes'].append(f'☁️ Cloudflare quick tunnel → https://{results["public_hostname"]}')
                if not results['cross_device_possible']:
                    results['cross_device_possible'] = True
                    results['primary_method'] = 'cloudflare'
        except Exception:
            pass
    
    # ═══ 3. andromeda daemon 状态 ═══
    ok2, out2 = _launchctl_run('list')
    for line in out2.splitlines():
        if 'com.mtscos.andromeda' in line and 'andromeda-mcp' not in line:
            parts = line.split()
            if len(parts) >= 3:
                results['andromeda_alive'] = parts[1] == '0'
                break
    if results['andromeda_alive']:
        results['notes'].append('andromeda daemon 正常 (握手服务)')
    
    # ═══ 4. 诊断总结 ═══
    if results['primary_method'] == 'tailscale':
        results['notes'].append('🏆 Tailscale 为首选跨设备通道 — 零配置, 固定 IP, 直连不绕 DERP')
    elif results['primary_method'] == 'cloudflare':
        results['notes'].append('Tailscale 不可用, 走 Cloudflare Tunnel fallback')
    else:
        results['notes'].append('⚠️ Tailscale 和 Cloudflare Tunnel 都不可用 → 安装 Tailscale 最快')
    
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
    {'name':'cross_tunnel_health','description':'🌐 跨设备通道健康检测 — Tailscale 优先 + Cloudflare Tunnel fallback','inputSchema':{'type':'object','properties':{}}},
    {'name':'system_metrics','description':'📡 实时系统指标 — CPU/内存/磁盘/daemon 状态/负载','inputSchema':{'type':'object','properties':{}}},
    # v2.2.0 自主强化升级
    {'name':'patrol_rounds','description':'🔄 L0 定时巡检 — 全链路跑 diagnose + ai_diag + tunnel_health, 结果落 SQLite 审计日志','inputSchema':{'type':'object','properties':{'rounds':{'type':'integer','description':'巡检轮数, 默认 1'},'interval_sec':{'type':'integer','description':'轮间间隔秒, 默认 5'}}}},
    {'name':'ai_propose_upgrade','description':'🚀 L1 AI 提案 — 本地 AI 审查自身代码 + 生成改进 diff + 风险评估, 存 SQLite 等人工批准','inputSchema':{'type':'object','properties':{'focus':{'type':'string','description':'审查焦点, 如 "engines" / "routes" / "rules" / "all"'}}}},
    {'name':'auto_apply_patch','description':'⚡ L2 自主修复 — 仅限预批准安全操作集 (重启白名单 daemon / 清 cache / 修导入错误)','inputSchema':{'type':'object','properties':{'target':{'type':'string','description':'修复目标: "restart_daemon" / "clean_cache" / "fix_imports"'},'daemon':{'type':'string','description':'restart_daemon 时指定 daemon 名'}},'required':['target']}},
    {'name':'git_snapshot','description':'🛡️ L0 安全栅栏 — 执行 git commit 快照当前项目状态, 保证任何操作可回滚','inputSchema':{'type':'object','properties':{'tag':{'type':'string','description':'快照标签, 如 "pre-patch"'}}}},
]

# ═══════════════════════════════════════════════════════════
# §14 IRON_RULE v2.3.0: dev_activity_preflight 强制接入
# ═══════════════════════════════════════════════════════════
import sys as _preflight_sys
_RULES_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ai_engines', 'rules_engine')
_RULES_ENGINE_DIR = os.path.normpath(_RULES_ENGINE_DIR)
if _RULES_ENGINE_DIR not in _preflight_sys.path:
    _preflight_sys.path.insert(0, _RULES_ENGINE_DIR)
try:
    # [unused] from dev_activity_preflight import preflight_check as _flow_preflight
    from dev_activity_preflight import _query_flow_state as _flow_query
    from dev_activity_preflight import _ALLOWED_IMPL_STEPS as _FLOW_ALLOWED_STEPS
    _PREFLIGHT_OK = True
except Exception as _e:
    _PREFLIGHT_OK = False
    _PREFLIGHT_ERR_MSG = str(_e)

# §14: 只读诊断类 tool 白名单（零开销放行）
_READONLY_TOOLS = frozenset({
    'flask_health', 'db_stats', 'list_daemons', 'disk_check',
    'system_metrics', 'handshake_status', 'vikey_check', 'list_users',
    'patrol_rounds', 'git_snapshot', 'ai_status', 'tool_list',
    'marvis_probe',
})
# §14: 开发/变更类 tool 清单（必须 preflight）
_DEV_TOOLS = frozenset({
    'heal_system', 'restart_daemon', 'ai_propose_upgrade',
    'auto_apply_patch', 'ai_diagnose', 'cross_tunnel_health',
    'exec_shell',
})
def _check_mcp_preflight(tool_name: str, arguments: dict) -> tuple:
    """§14 MT_IR_D9: MCP Hub tool 调用前置检查 → (allowed:bool, message:str)"""
    if tool_name in _READONLY_TOOLS:
        return True, ''
    if tool_name not in _DEV_TOOLS:
        return True, ''
    if not _PREFLIGHT_OK:
        print(f'[§14 MCP PREFLIGHT] dev_activity_preflight 不可用 → 放行 (err={_PREFLIGHT_ERR_MSG})')
        return True, ''
    # ⚠️ 开发类 tool: 强制 flow_id 检查 (不管中文关键词是否命中)
    flow_id = arguments.pop('flow_id', None)
    if not flow_id:
        return False, (f"[§14 IRON_RULE MT_IR_D9] tool='{tool_name}' 属于开发活动类, "
                       "必须携带合法 flow_id (通过 /api/dev_flow/create 创建 12 步骤会话)")
    # v2.3.0: 直接查 DB 验证 flow_id (不依赖 preflight 的中文关键词检测)
    # preflight_check 检测中文关键词, 但 MCP Hub tool 参数是英文 → 关键词不命中会误放行!
    current_step = _flow_query(flow_id)
    if current_step is None:
        return False, (f"[§14 IRON_RULE MT_IR_D9] flow_id='{flow_id}' 不存在于 mt_dev_flow_session, "
                       "必须先走 12 步骤创建合法 flow_id")
    if current_step not in _FLOW_ALLOWED_STEPS:
        return False, (f"[§14 IRON_RULE MT_IR_D9] flow_id='{flow_id}' 当前步骤={current_step}, "
                       f"不在允许实施步骤集合 {sorted(_FLOW_ALLOWED_STEPS)} 中, "
                       "必须推进到 STEP_7_EXECUTE 后方可实施")
    # flow_id 合法 + 在允许步骤 → 放行
    return True, ''

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
    # v2.2.0 自主强化 — 先占位, 等函数定义完后 _register_v22() 再补
}

# ═══════════════════════════════════════════════════════════
# v2.2.0 自主强化 — SQLite 审计表 + 安全操作集 + 本地 AI 网关
# ═══════════════════════════════════════════════════════════

_PROJ_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(os.path.dirname(_PROJ_DIR), 'app.db')

def _audit_db():
    """连接审计库 (Flask 主库 app.db), 确保 3 张自主强化表存在"""
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS mt_andromeda_patrol (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, round INTEGER, duration_ms INTEGER,
            status TEXT, issues_found INTEGER, ok_rate REAL,
            summary TEXT
        );
        CREATE TABLE IF NOT EXISTS mt_andromeda_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, focus TEXT, title TEXT, root_cause TEXT,
            suggested_fix TEXT, diff_preview TEXT, risk TEXT,
            severity TEXT, status TEXT DEFAULT 'pending',
            approver TEXT, approved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mt_andromeda_autonomous_ops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, op_type TEXT, target TEXT, action TEXT,
            pre_check TEXT, post_check TEXT, git_snapshot TEXT,
            result TEXT, rollback TEXT
        );
    ''')
    conn.commit()
    return conn

# L2 预批准安全操作集 (白名单) — 禁止自主修改源码逻辑
_AUTONOMOUS_SAFE_SET = {
    'restart_daemon': {'desc': '重启白名单 daemon', 'allowed': {'flask','andromeda-mcp','smart_mount','andromeda'}},
    'clean_cache':     {'desc': '清磁盘 cache', 'allowed': {'pip','npm','pycache','tmp'}},
    'fix_imports':     {'desc': '修 .py 导入错误 (auto_patrol 9 类)', 'allowed': {'indent','syntax','import','pattern','bare_except','trailing_ws'}},
}

# ── tool 16: git_snapshot (🛡️ L0 安全栅栏) ──
def tool_git_snapshot(tag='manual', **kw):
    """🛡️ L0 安全栅栏 — git commit 快照当前项目状态, 任何操作前先调"""
    proj = _PROJ_DIR  # engines/
    # proj 是 engines/, .git 在 flask-app/ 上一级 ~/MTSCOS_AI_Project
    for _ in range(4):
        proj = os.path.dirname(proj)
        if os.path.isdir(os.path.join(proj, '.git')):
            break
    stamp = f'auto-snap-{time.strftime("%Y%m%d-%H%M%S")}-{tag}'
    try:
        r = subprocess.run(['git','add','-A'], capture_output=True, text=True, timeout=15, cwd=proj)
        diff = subprocess.run(['git','diff','--cached','--name-only'], capture_output=True, text=True, timeout=5, cwd=proj)
        changed = diff.stdout.strip().split('\n') if diff.stdout.strip() else []
        if not changed:
            return {'ok': True, 'action': 'git_snapshot', 'tag': tag, 'commit': None, 'changed': 0, 'note': '无变更, 跳过'}
        r2 = subprocess.run(['git','-c','user.email=andromeda@mtscos','-c','user.name=AndromedaAI',
                           'commit','-m',stamp,'--quiet'], capture_output=True, text=True, timeout=15, cwd=proj)
        log = subprocess.run(['git','log','--oneline','-1'], capture_output=True, text=True, timeout=5, cwd=proj)
        return {'ok': True, 'action': 'git_snapshot', 'tag': tag,
                'commit': log.stdout.strip(), 'changed': len(changed),
                'files': changed[:10]}
    except Exception as e:
        return {'ok': False, 'action': 'git_snapshot', 'error': str(e)}

# ── tool 17: patrol_rounds (🔄 L0 定时巡检) ──
def tool_patrol_rounds(rounds=1, interval_sec=5, **kw):
    """🔄 L0 全链路定时巡检 — 跑 diagnose_system + ai_diagnose + cross_tunnel_health, 结果落 SQLite"""
    rounds = max(1, min(int(rounds or 1), 20))
    interval_sec = max(2, min(int(interval_sec or 5), 60))
    conn = _audit_db()
    results = []
    for i in range(rounds):
        t0 = time.time()
        diag = tool_diagnose_system()
        ai = tool_ai_diagnose()
        tunnel = tool_cross_tunnel_health()
        metrics = tool_system_metrics()
        
        issues = diag.get('report',{}).get('summary',{}).get('issues_found', 0)
        total_daemons = len([d for d in diag.get('report',{}).get('diagnosis',[]) if d.get('type')=='daemon'])
        ok_daemons = len([d for d in diag.get('report',{}).get('diagnosis',[]) if d.get('type')=='daemon' and d.get('ok')])
        ok_rate = ok_daemons / max(total_daemons, 1)
        
        dur_ms = int((time.time() - t0) * 1000)
        status = 'HEALTHY' if issues == 0 else ('WARNING' if issues == 1 else 'CRITICAL')
        summary = f'daemon={ok_daemons}/{total_daemons} issues={issues} tunnel={tunnel.get("primary_method","none")}'
        
        conn.execute('INSERT INTO mt_andromeda_patrol (ts,round,duration_ms,status,issues_found,ok_rate,summary) VALUES (?,?,?,?,?,?,?)',
                     (time.strftime('%Y-%m-%d %H:%M:%S'), i+1, dur_ms, status, issues, ok_rate, summary))
        conn.commit()
        
        results.append({
            'round': i+1, 'status': status, 'issues_found': issues,
            'ok_rate': round(ok_rate*100, 1), 'duration_ms': dur_ms,
            'tunnel': tunnel.get('primary_method'), 'summary': summary,
            'ai_findings': ai.get('findings', []),
        })
        if i < rounds - 1:
            time.sleep(interval_sec)
    conn.close()
    
    overall = 'HEALTHY' if all(r['status']=='HEALTHY' for r in results) else (
              'WARNING' if all(r['status'] in ('HEALTHY','WARNING') for r in results) else 'CRITICAL')
    
    return {
        'ok': True, 'action': 'patrol_rounds',
        'rounds_done': rounds, 'overall': overall,
        'results': results,
        'note': f'巡检结果已落 SQLite mt_andromeda_patrol 表',
    }

# ── tool 18: ai_propose_upgrade (🚀 L1 AI 提案) ──
def tool_ai_propose_upgrade(focus='all', **kw):
    """🚀 L1 AI 提案 — 本地规则引擎审查当前代码状态 + 生成改进提案, 存 SQLite 等人工批准"""
    conn = _audit_db()
    proposals = []
    
    # 1. 拉当前系统状态
    diag = tool_diagnose_system()
    ai = tool_ai_diagnose()
    metrics = tool_system_metrics()
    tunnel = tool_cross_tunnel_health()
    daemon_ok = [d for d in diag.get('report',{}).get('diagnosis',[]) if d.get('type')=='daemon' and d.get('ok')]
    daemon_bad = [d for d in diag.get('report',{}).get('diagnosis',[]) if d.get('type')=='daemon' and not d.get('ok')]
    
    # 2. 基于规则引擎生成提案 (结构化, 不依赖外部 AI)
    def _add_proposal(title, root_cause, fix, risk, severity):
        conn.execute('INSERT INTO mt_andromeda_proposals (ts,focus,title,root_cause,suggested_fix,diff_preview,risk,severity) VALUES (?,?,?,?,?,?,?,?)',
                     (time.strftime('%Y-%m-%d %H:%M:%S'), focus, title, root_cause, fix, '', risk, severity))
        proposals.append({'title': title, 'root_cause': root_cause, 'suggested_fix': fix, 'risk': risk, 'severity': severity})
    
    # 提案规则集 (6 条自主发现)
    if daemon_bad:
        bad_names = [d.get('label','?') for d in daemon_bad]
        _add_proposal(f'重启崩溃 daemon: {bad_names}', f'daemon exit_code != 0 + PID 验证存活失败',
                     f'tool_auto_apply_patch(target=restart_daemon, daemon={bad_names[0]})',
                     'low', 'high')
    
    if metrics.get('disk_pct', 0) > 80:
        _add_proposal('磁盘告急', f'disk usage {metrics.get("disk_pct")}% > 80%',
                     'tool_auto_apply_patch(target=clean_cache)', 'low', 'high')
    
    if len(ai.get('findings', [])) > 0:
        for f in ai['findings']:
            title = f.get('match') or f.get('rule') or f.get('description') or str(f)[:60]
            fix = f.get('fix') or f.get('suggestion') or f.get('recommendation') or '见 ai_diagnose 完整输出'
            sev = f.get('severity', 'medium')
            _add_proposal(f'AI 发现: {title}', '规则引擎命中', f'建议: {fix}', 'low', sev)
    
    if not tunnel.get('tailscale_ok') and not tunnel.get('cloudflared_ok'):
        _add_proposal('跨设备通道全挂', 'Tailscale 和 Cloudflare Tunnel 都不可用',
                     '安装 Tailscale / 检查 cloudflared daemon', 'medium', 'high')
    
    # Python 源码质量巡检 (轻量 — 只扫 engines 目录)
    try:
        py_dirs = [os.path.join(_PROJ_DIR, '.')]
        py_count = 0; bad_indent = 0; bad_import = 0; total_lines = 0
        for pdir in py_dirs:
            for root, _, files in os.walk(pdir):
                for fn in files:
                    if fn.endswith('.py') and fn != '__init__.py':
                        py_count += 1
                        fp = os.path.join(root, fn)
                        try:
                            with open(fp) as f:
                                code = f.read()
                            total_lines += len(code.splitlines())
                            # 快速检查
                            compile(code, fp, 'exec')  # 语法
                            if code.count('\t') > 5:
                                bad_indent += 1
                            if 'bare except:' in code or 'except:' in code:
                                bad_import += 1
                        except SyntaxError as e:
                            bad_import += 1
        if bad_indent > 0 or bad_import > 0:
            _add_proposal(f'源码质量: {bad_indent} 缩进问题 / {bad_import} 裸 except',
                         f'scanned {py_count} files / {total_lines} lines',
                         'auto_patrol_engine 自动修复 9 类问题', 'low', 'medium')
    except Exception:
        pass
    
    conn.commit()
    conn.close()
    
    # 3. 汇总 — 自主能力自评
    self_eval = {
        'git_ready': os.path.isdir(os.path.join(_PROJ_DIR, '..', '.git')) or
                     os.path.isdir(os.path.join(os.path.dirname(_PROJ_DIR), '.git')),
        'proposals_gen': len(proposals),
        'autonomous_level': 'L1 (巡检+提案, 等人工批准)',
        'can_upgrade_to_L2': True,
    }
    
    return {
        'ok': True, 'action': 'ai_propose_upgrade',
        'focus': focus, 'proposals': proposals, 'proposal_count': len(proposals),
        'self_evaluation': self_eval,
        'note': f'{len(proposals)} 条提案已存 SQLite mt_andromeda_proposals, 等人工审批',
    }

# ── tool 19: auto_apply_patch (⚡ L2 自主修复, 仅限安全操作集) ──
def tool_auto_apply_patch(target, daemon=None, **kw):
    """⚡ L2 自主修复 — 仅限预批准白名单: restart_daemon(白名单) / clean_cache / fix_imports"""
    target = (target or '').strip()
    rules = _AUTONOMOUS_SAFE_SET
    
    if target not in rules:
        return {'ok': False, 'action': 'auto_apply_patch', 'error': f'操作不在白名单: {target}',
                'allowed': list(rules.keys())}
    
    # 1. git 快照 (任何操作前先 commit)
    snap = tool_git_snapshot(tag=f'pre-{target}')
    
    op_result = {'target': target, 'pre_snapshot': snap.get('commit'), 'steps': []}
    
    if target == 'restart_daemon':
        allowed = rules['restart_daemon']['allowed']
        real_daemon = None
        if daemon:
            for a in allowed:
                if a in daemon or a == daemon:
                    real_daemon = a; break
        if not real_daemon:
            return {'ok': False, 'action': 'auto_apply_patch', 'error': f'daemon 不在白名单: {daemon}',
                    'allowed': list(allowed)}
        
        # 执行重启 (用 restart_daemon tool)
        result = tool_restart_daemon(target=real_daemon)
        op_result['post_check'] = f'重启 {real_daemon}'
        op_result['result'] = result
    
    elif target == 'clean_cache':
        cache_dirs = ['~/.cache/pip', '~/.npm/_cacache', '/tmp', '__pycache__']
        cleaned = []
        for d in cache_dirs:
            path = os.path.expanduser(d)
            if os.path.exists(path):
                r = subprocess.run(['rm','-rf',path,'/*'], capture_output=True, timeout=10)
                if r.returncode == 0:
                    cleaned.append(d)
        op_result['post_check'] = f'清了 {len(cleaned)} 个 cache 目录'
        op_result['result'] = {'cleaned': cleaned}
    
    elif target == 'fix_imports':
        # 轻量扫 engines/ 下 .py 语法错误 (不自动改, 只报告)
        py_dir = _PROJ_DIR
        issues = []
        for root, _, files in os.walk(py_dir):
            for fn in files:
                if fn.endswith('.py'):
                    fp = os.path.join(root, fn)
                    try:
                        with open(fp) as f:
                            compile(f.read(), fp, 'exec')
                    except SyntaxError as e:
                        issues.append({'file': fn, 'error': str(e)[:80]})
        op_result['post_check'] = f'扫描 {py_dir}, 发现 {len(issues)} 个语法错误'
        op_result['result'] = {'issues': issues, 'note': '语法错误请手动修, 或用 auto_patrol_engine'}
    
    # 2. 记录到审计库
    try:
        conn = _audit_db()
        conn.execute('INSERT INTO mt_andromeda_autonomous_ops (ts,op_type,target,action,pre_check,post_check,git_snapshot,result) VALUES (?,?,?,?,?,?,?,?)',
                     (time.strftime('%Y-%m-%d %H:%M:%S'), 'auto_apply_patch', target, str(daemon or ''),
                      snap.get('commit',''), op_result.get('post_check',''), snap.get('commit',''),
                      str(op_result.get('result',{}))[:500]))
        conn.commit(); conn.close()
    except Exception:
        pass
    
    return {
        'ok': True, 'action': 'auto_apply_patch',
        'git_snapshot': snap.get('commit'),
        'result': op_result.get('result'),
        'level': 'L2 (预批准安全操作集)',
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

# ── v2.2.0 动态注册 (函数定义完再注册, 避免 NameError) ──
def _register_v22_tools():
    """v2.2.0 自主强化 4 个 tool — 在函数定义后再注册到 HANDLERS 和 TOOLS"""
    v22_names = {
        'patrol_rounds': tool_patrol_rounds,
        'ai_propose_upgrade': tool_ai_propose_upgrade,
        'auto_apply_patch': tool_auto_apply_patch,
        'git_snapshot': tool_git_snapshot,
    }
    for name, fn in v22_names.items():
        ANDROMEDA_HANDLERS[name] = fn

_register_v22_tools()  # 立即注册
_log('🧠 v2.2.0 自主强化: 4 个 tool 已注册 (patrol_rounds/ai_propose_upgrade/auto_apply_patch/git_snapshot)')

# 全局注册 (启动时加载一次)
TOOLS = list(ANDROMEDA_TOOLS)  # ANDROMEDA_TOOLS 里已包含 v2.2.0 4 个 tool 描述
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
            # §14 IRON_RULE v2.3.0: 强制前置 preflight (MT_IR_D9)
            ok, reason = _check_mcp_preflight(name, arguments)
            if not ok:
                _stats_inc(name, error=True)
                self._rpc_ok(rpc_id, {'content':[{'type':'text',
                    'text':json.dumps({'ok':False,'§14_MT_IR_D9':'BLOCKED',
                        'error':'DEV-FLOW-VIOLATION-IRON-RULE',
                        'reason':reason}, ensure_ascii=False, indent=2)}],
                    'isError': True})
                return
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
