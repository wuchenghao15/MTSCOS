#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vikey 官方 SDK 合规接入层 (flow_sa_hw_state_20261020)
=====================================================
官方三件套 ( _config/ViKey/ ):
  - Vikey.h     官方 C 头文件   → 官方参数 (设备类型/权限级别/错误码, 本模块启动时解析加载)
  - ViKey.Dll   官方 Windows 库 → 经官方 WS 桥协议访问 (ws://localhost:8189)
  - VikeyAPI.js 官方 JS API 层  → 官方方法契约: VikeyFind()/VikeyFindEx() → {code, count}

本模块把官方参数/方法/协议原样加载进系统:
  1. OFFICIAL_CONSTS ← 解析 VikeyAPI.js (VikeyType/VikeyError/权限级别 官方枚举)
  2. VikeyOfficialAPI.VikeyFind()/VikeyFindEx() ← 官方方法名+官方返回契约
  3. 官方协议帧: "255|ViKeyWebSocket|{FunctionType:...}" → WS 桥 (Win/mac 均先探桥)
  4. macOS 无 Dll: ioreg 实扫 (ViKeyPRO VID 0x1987/PID 0x0331) → 包装成官方格式回退

接入点: core/services/vikey_driver.py DarwinProvider.detect_vikey() 优先级0 调 official_present()
"""
import json
import logging
import os
import re
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# 官方 SDK 目录 (项目根/_config/ViKey)
_SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))) if os.path.basename(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))) != '_config' else '', '_config', 'ViKey')


def _sdk_file(name):
    for base in (os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), '_config', 'ViKey'),):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None


# ══ 1. 官方参数: 启动时解析 VikeyAPI.js 官方枚举 (解析失败 → 官方头文件硬编码镜像) ══
OFFICIAL_CONSTS = {
    'device_types': {
        'ViKeyAPP': 0x00, 'ViKeySTD': 0x01, 'ViKeyNET': 0x02, 'ViKeyPRO': 0x03,
        'ViKeyWEB': 0x04, 'ViKeyTIME': 0x05, 'ViKeyMultiFunctional': 0x0A,
        'ViKeyMultiFunctionalTime': 0x0B, 'ViKeyCloud': 0x0C, 'ViKeyMobile': 0x0D,
        'ViKeySecure': 0x0E, 'ViKeyInvalid': 0xFF,
    },
    'permission_levels': {'ViKeyNoLevel': 0, 'ViKeyUserLevel': 1, 'VikeyAdminLevel': 2},
    'error_codes': {
        'VIKEY_SUCCESS': 0x00000000, 'VIKEY_ERROR_NO_VIKEY': 0x80000001,
        'VIKEY_ERROR_NEED_FIND': 0x80000003, 'VIKEY_ERROR_CONNECTION': 0x8000000E,
        'VIKEY_ERROR_CATCH': 0x80000017, 'VIKEY_ERROR_UNKNOWN_ERROR': 0xFFFFFFFF,
    },
    'ws_bridge': {'host': 'localhost', 'port': 8189, 'magic': '255',
                  'channel': 'ViKeyWebSocket', 'timeout_s': 1.5},
    'source_files': {'vikey_h': None, 'vikeyapi_js': None, 'dll': None},
}


def _load_official_consts():
    """启动时解析官方 VikeyAPI.js 枚举 → 刷新 OFFICIAL_CONSTS (官方参数加载入系统)"""
    js = _sdk_file('VikeyAPI.js')
    hh = _sdk_file('Vikey.h')
    dll = _sdk_file('ViKey.Dll')
    OFFICIAL_CONSTS['source_files'] = {'vikey_h': hh, 'vikeyapi_js': js, 'dll': dll}
    if not js:
        return
    try:
        src = open(js, 'r', encoding='utf-8', errors='replace').read()
        # VikeyType 枚举
        m = re.search(r'VikeyType\s*=\s*\{([^}]+)\}', src)
        if m:
            types = {}
            for k, v in re.findall(r'(ViKey\w+)\s*:\s*(0x[0-9A-Fa-f]+|\d+)', m.group(1)):
                types[k] = int(v, 0)
            if types:
                OFFICIAL_CONSTS['device_types'] = types
        # VikeyError 枚举
        m = re.search(r'VikeyError\s*=\s*\{([^}]+)\}', src)
        if m:
            errs = {}
            for k, v in re.findall(r'(VIKEY_\w+)\s*:\s*(0x[0-9A-Fa-f]+)', m.group(1)):
                errs[k] = int(v, 16)
            if errs:
                OFFICIAL_CONSTS['error_codes'] = errs
        logger.info(f"[vikey_official] 官方参数加载: {len(OFFICIAL_CONSTS['device_types'])}设备类型 "
                    f"{len(OFFICIAL_CONSTS['error_codes'])}错误码 (源: VikeyAPI.js)")
    except Exception as e:
        logger.warning(f"[vikey_official] VikeyAPI.js 解析降级为镜像: {e}")


_load_official_consts()


# ══ 2/3. 官方方法 + 官方协议 (WS 桥优先, ioreg 官方格式回退) ══
# flow_usb_hub_20261020: 扩至全家族 — 官方(2341/2a03) + CH340/CH341(1a86) + CP210x(10c4)
#   + FT232(0403) + ESP32(303a) + PL2303(067b) + STM32 VCP(0483) + Atmel(03eb)
#   + Adafruit(239a) + SparkFun(1b4f) + Seeed(2886) — Hub 下挂克隆板常命中后段
_ARD_VID_WHITELIST = {'0x2341', '0x2a03', '0x1a86', '0x10c4', '0x0403', '0x303a',
                      '0x067b', '0x0483', '0x03eb', '0x239a', '0x1b4f', '0x2886'}
_VIKEY_VID = '0x1987'  # ViKeyPRO 实测官方 VID (PID 0x0331)


def _ws_bridge_find():
    """官方协议: ws://localhost:8189 帧 '255|ViKeyWebSocket|{FunctionType:VikeyFind}' → {code,count}"""
    try:
        import socket
        # WS 桥是纯 TCP 自定义帧协议 (255|ViKeyWebSocket|{json}), 用裸 socket 按官方帧发送
        cfg = OFFICIAL_CONSTS['ws_bridge']
        sock = socket.create_connection((cfg['host'], cfg['port']), timeout=cfg['timeout_s'])
        sock.settimeout(cfg['timeout_s'])
        frame = f"{cfg['magic']}|{cfg['channel']}|{json.dumps({'FunctionType': 'VikeyFind'})}"
        sock.sendall(frame.encode('utf-8'))
        buf = b''
        t0 = time.time()
        while time.time() - t0 < cfg['timeout_s']:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b'}' in buf:
                break
        sock.close()
        text = buf.decode('utf-8', errors='replace')
        # 官方响应帧: 255|ViKeyWebSocket|{...json...} → 提取 JSON
        m = re.search(r'\{.*\}', text, re.S)
        if not m:
            return None
        resp = json.loads(m.group(0))
        code = int(resp.get('code', resp.get('Code', -1)))
        count = int(resp.get('count', resp.get('Count', 0)))
        # 官方契约: code=VIKEY_SUCCESS(0) 且 count>0 → 在位
        if code == OFFICIAL_CONSTS['error_codes']['VIKEY_SUCCESS']:
            return {'code': code, 'count': count, 'via': 'official_ws_bridge',
                    'devices': resp.get('devices', [])}
        if code == OFFICIAL_CONSTS['error_codes']['VIKEY_ERROR_NO_VIKEY']:
            return {'code': code, 'count': 0, 'via': 'official_ws_bridge', 'devices': []}
        return None  # 其他官方错误码 → 交给回退链
    except Exception:
        return None  # 桥不在 (macOS 常态) → 静默回退


def _ioreg_official_find():
    """macOS 官方格式回退: ioreg 实扫 ViKeyPRO → 包装官方 VikeyFind() 契约 {code, count}"""
    try:
        env = {**os.environ, 'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
        r = subprocess.run(['ioreg', '-p', 'IOUSB', '-l', '-w', '0'],
                           capture_output=True, text=True, timeout=5, env=env)
        raw = (r.stdout or '').lower()
        vid_hex = _VIKEY_VID[2:].lower()          # 1987
        vid_dec = str(int(_VIKEY_VID, 16))        # 6535
        found = (('usb product name" = "vikey' in raw)
                 or (f'idvendor" = {vid_dec}' in raw)
                 or (f'idvendor" = {vid_hex}' in raw)
                 or (vid_hex in raw))
        return {'code': OFFICIAL_CONSTS['error_codes']['VIKEY_SUCCESS'] if found
                       else OFFICIAL_CONSTS['error_codes']['VIKEY_ERROR_NO_VIKEY'],
                'count': 1 if found else 0,
                'via': 'official_ioreg_fallback',
                'devices': [{'index': 0, 'type': 'ViKeyPRO', 'type_id': 0x03,
                             'vid': _VIKEY_VID, 'pid': '0x0331'}] if found else []}
    except Exception as e:
        logger.info(f"[vikey_official] ioreg 回退异常: {e}")
        return {'code': OFFICIAL_CONSTS['error_codes']['VIKEY_ERROR_CATCH'], 'count': 0,
                'via': 'error', 'devices': []}


def VikeyFind():
    """官方方法 VikeyFind(): 先探官方 WS 桥协议, 不在 → ioreg 官方格式回退. 返回官方契约 {code,count,via,devices}"""
    r = _ws_bridge_find()
    if r is not None:
        return r
    return _ioreg_official_find()


def VikeyFindEx():
    """官方方法 VikeyFindEx(): 扩展查找 — 与 VikeyFind 同源, 附带设备类型明细"""
    r = VikeyFind()
    r['ex'] = True
    return r


def official_present():
    """Provider 接入点: 官方链路在位判定 (code=VIKEY_SUCCESS 且 count>0)"""
    r = VikeyFind()
    return r.get('code') == OFFICIAL_CONSTS['error_codes']['VIKEY_SUCCESS'] and r.get('count', 0) > 0, r


# ══ 4. USB Hub 感知枚举 + 归因诊断 (flow_usb_hub_20261020) ══
# 背景: 开发机/服务器上 VIKEY + SZU100 + Arduino 均经 USB Hub 接入。
#   历史检测只做扁平 ioreg -p IOUSB 的 VID 全文匹配, 无法回答:
#     (a) 设备是直插机身口 还是 Hub 下挂; (b) 落在哪个 Hub 的哪个端口;
#     (c) Hub 供电是否够; (d) 期望设备缺失时到底卡在哪一层。
#   本段补齐: 层级树解析 + 端口/供电归因 + 串口节点回退 + 缺失设备诊断。
_USB_ENV = {**os.environ, 'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
_TOPOLOGY_CACHE = {'ts': 0.0, 'data': None}
_TOPOLOGY_TTL = 5.0
_TOPOLOGY_LOCK = threading.Lock()
# Shanzhai/clone Arduino 常见串口节点 (VID 非白名单时的回退证据)
_SERIAL_PORT_GLOBS = ('/dev/cu.usbmodem*', '/dev/cu.usbserial*',
                      '/dev/cu.wchusbserial*', '/dev/cu.SLAB_USBtoUART*')
_EXPECTED_DEVICES = (('VIKEY', '0x1987'), ('SZU100', '0x0305'))


def _ioreg_flat():
    """扁平枚举 (含 Hub 下挂设备), 返回小写全文 — 原检测路径保留"""
    r = subprocess.run(['ioreg', '-p', 'IOUSB', '-l', '-w', '0'],
                       capture_output=True, text=True, timeout=6, env=_USB_ENV)
    return (r.stdout or '').lower()


def _ioreg_tree_devices():
    """层级枚举: ioreg -r -c IOUSBHostDevice → [{name,vid,pid,loc,parent,product,vendor,
     ports,power_avail,power_req,is_hub,class}]; parent=父设备索引(区分 Hub 下挂 vs 直插)。
    ioreg 树形输出带 '| ' 缩进前缀, 属性行形如 '      | |   "idVendor" = 6535'"""
    try:
        r = subprocess.run(['ioreg', '-r', '-c', 'IOUSBHostDevice', '-l', '-w', '0'],
                           capture_output=True, text=True, timeout=8, env=_USB_ENV)
        text = r.stdout or ''
    except Exception as e:
        logger.info(f"[vikey_official] ioreg 层级枚举跳过: {e}")
        return []
    devs, stack = [], []
    for line in text.splitlines():
        # 名称可能含空格 (如 'on Flash@01230000') → 取到 '<class' 之前为止
        mc = re.search(r'\+-o\s+([^<]+?)\s*<|\|-o\s+([^<]+?)\s*<|\`-o\s+([^<]+?)\s*<', line)
        if mc:
            depth = mc.start()
            name = next(g for g in mc.groups() if g)
            stack = [s for s in stack if s[0] < depth]
            parent = stack[-1][1] if stack else None
            devs.append({'name': name, 'vid': None, 'pid': None, 'loc': None,
                         'parent': parent, 'product': '', 'vendor': '',
                         'ports': None, 'power_avail': None, 'power_req': None,
                         'class': None, 'is_hub': False})
            stack.append((depth, len(devs) - 1))
            continue
        a = re.match(r'^[\s|]*"([^"]+)"\s*=\s*(.*)$', line)
        if a and stack:
            d = devs[stack[-1][1]]
            k, v = a.group(1), a.group(2).strip().strip('"')
            if k == 'idVendor': d['vid'] = v
            elif k == 'idProduct': d['pid'] = v
            elif k == 'locationID': d['loc'] = v
            elif k == 'USB Product Name': d['product'] = v
            elif k == 'USB Vendor Name': d['vendor'] = v
            elif k == 'Ports': d['ports'] = v
            elif k == 'Current Available': d['power_avail'] = v
            elif k == 'Current Required': d['power_req'] = v
            elif k == 'bDeviceClass': d['class'] = v
    # 只保留真实 USB 设备 (有 idVendor), 过滤 IOUSBHostInterface/HID/存储子节点
    kept = [d for d in devs if d['vid']]
    remap = {}
    for i, d in enumerate(devs):
        if d['vid']:
            remap[i] = len(remap)
    out = []
    for i, d in enumerate(devs):
        if not d['vid']:
            continue
        d = dict(d)
        # parent 上溯到最近的"真实设备"祖先
        up, parent_idx = d['parent'], None
        while up is not None:
            if up in remap:
                parent_idx = remap[up]; break
            up = devs[up]['parent']
        d['parent'] = parent_idx
        _short = d['name'].split('@')[0].lower()
        d['is_hub'] = (str(d.get('class')) == '9') or _short.endswith('hub')
        out.append(d)
    return out


def _vid_match(vid, whitelist):
    if not vid:
        return False
    try:
        n = int(vid)
    except Exception:
        return False
    return ('0x%04x' % n) in whitelist


def usb_topology(force_refresh=False):
    """Hub 感知拓扑: {hubs, devices, serial_ports, behind_hub} — 5s 缓存"""
    global _TOPOLOGY_CACHE
    now = time.time()
    if not force_refresh and (now - _TOPOLOGY_CACHE['ts']) < _TOPOLOGY_TTL and _TOPOLOGY_CACHE['data']:
        return _TOPOLOGY_CACHE['data']
    with _TOPOLOGY_LOCK:
        if not force_refresh and (time.time() - _TOPOLOGY_CACHE['ts']) < _TOPOLOGY_TTL and _TOPOLOGY_CACHE['data']:
            return _TOPOLOGY_CACHE['data']
        devs = _ioreg_tree_devices()
        hubs, leaf, seen, seen2 = [], [], {}, {}
        for i, d in enumerate(devs):
            # 系统复合/接口节点 (AppleUSBNCMData/NCMData 等) 非独立物理设备 → 不进拓扑
            _nm = d['name'].split('@')[0]
            if d['is_hub'] or _nm.startswith('AppleUSB') or _nm.startswith('IOUSB') \
                    or _nm.startswith('AppleUserUSB') or _nm.startswith('AppleVendor'):
                if d['is_hub']:
                    item = {'name': d['name'].split('@')[0], 'product': d['product'] or d['name'].split('@')[0],
                            'vendor': d['vendor'],
                            'vid': (('0x%04x' % int(d['vid'])) if d['vid'] and d['vid'].isdigit() else d['vid']),
                            'pid': (('0x%04x' % int(d['pid'])) if d['pid'] and d['pid'].isdigit() else d['pid']),
                            'location': d['loc'], 'is_hub': True,
                            'ports': d['ports'], 'power_available': d['power_avail'],
                            'power_required': d['power_req'], 'on_hub': False}
                    hubs.append(item)
                continue
            item = {'name': d['name'].split('@')[0], 'product': d['product'] or d['name'].split('@')[0],
                    'vendor': d['vendor'],
                    'vid': (('0x%04x' % int(d['vid'])) if d['vid'] and d['vid'].isdigit() else d['vid']),
                    'pid': (('0x%04x' % int(d['pid'])) if d['pid'] and d['pid'].isdigit() else d['pid']),
                    'location': d['loc'], 'is_hub': False,
                    'ports': d['ports'], 'power_available': d['power_avail'],
                    'power_required': d['power_req']}
            # 归因最近的上游 Hub
            up, hop = d['parent'], 0
            hub_name = None
            while up is not None and hop < 6:
                p = devs[up]
                if p['is_hub']:
                    hub_name = p['name'].split('@')[0]; break
                up, hop = p['parent'], hop + 1
            item['on_hub'] = bool(hub_name)
            item['hub'] = hub_name
            item['direct'] = (hub_name is None)
            # ioreg -r 会按每个匹配对象重复打印子树 → 双键去重
            #   (a) (vid,pid,locationID); (b) (vid,pid,product) — 覆盖 locationID 缺失的副本
            key = (item['vid'], item['pid'], item['location'] or item['product'])
            key2 = (item['vid'], item['pid'], item['product'])
            prev = seen.get(key) or seen2.get(key2)
            if prev is not None:
                if (not prev.get('location') and item.get('location')) or (not prev.get('hub') and item.get('hub')):
                    i = leaf.index(prev)
                    merged = dict(prev)
                    merged.update({k: v for k, v in item.items() if v})
                    leaf[i] = merged
                    seen[key] = merged; seen2[key2] = merged
                continue
            seen[key] = item; seen2[key2] = item
            leaf.append(item)
        # Hub 去重 (同一物理 Hub 的 USB2/USB3 实例同名时保留有端口信息者)
        hseen, hub_u = {}, []
        for h in hubs:
            k = (h['vid'], h['pid'], h['name'])
            if k in hseen:
                if not hseen[k].get('ports') and h.get('ports'):
                    hub_u[hub_u.index(hseen[k])] = h; hseen[k] = h
                continue
            hseen[k] = h; hub_u.append(h)
        hubs = hub_u
        # Hub 自身的接口/复合节点会以同 vid:pid 混入设备列表 → 剔除
        _hubkey = {(h['vid'], h['pid']) for h in hubs}
        leaf = [x for x in leaf if (x['vid'], x['pid']) not in _hubkey]
        import glob as _glob
        serial = []
        for g in _SERIAL_PORT_GLOBS:
            serial += _glob.glob(g)
        data = {'hubs': hubs, 'devices': leaf, 'serial_ports': sorted(set(serial))}
        _TOPOLOGY_CACHE = {'ts': time.time(), 'data': data}
        return data


def _ioreg_hub_ports():
    """Hub 端口级诊断: 每个下游口是否有设备 / 连接事件数 / 过流数 / 枚举失败数。
    connect_count=0 → 该口从未发生电气连接 (线材/接触/未插入);
    connect_count>0 但无设备 → 连上了但枚举失败 (供电/驱动)。
    这是"Hub 下插了却不识别"的关键归因证据。"""
    try:
        r = subprocess.run(['ioreg', '-r', '-c', 'IOUSBHostDevice', '-l', '-w', '0'],
                           capture_output=True, text=True, timeout=8, env=_USB_ENV)
        text = r.stdout or ''
    except Exception:
        return []
    items, stack = [], []
    for line in text.splitlines():
        # 名称可能含空格 (如 'on Flash@01230000') → 取到 '<class' 之前为止
        mc = re.search(r'\+-o\s+([^<]+?)\s*<|\|-o\s+([^<]+?)\s*<|\`-o\s+([^<]+?)\s*<', line)
        if mc:
            depth = mc.start()
            name = next(g for g in mc.groups() if g)
            stack = [s for s in stack if s[0] < depth]
            parent = stack[-1][1] if stack else None
            items.append({'name': name, 'depth': depth, 'parent': parent,
                          'connect': None, 'overcurrent': None, 'enumfail': None})
            stack.append((depth, len(items) - 1))
            continue
        m = re.search(r'"port-statistics" = \{(.*)\}', line)
        if m and stack:
            blob = m.group(1)
            it = items[stack[-1][1]]
            for fld, pat in (('connect', 'kPortStatConnectCount'),
                             ('overcurrent', 'kPortStatOverCurrentCount'),
                             ('enumfail', 'kPortStatEnumerationFailureCount')):
                mm = re.search(pat + r'"=(\d+)', blob)
                if mm:
                    it[fld] = int(mm.group(1))
    ports = []
    for i, it in enumerate(items):
        if 'hubport' not in it['name'].lower():
            continue
        dev = None
        for c in items[i + 1:]:
            if c['depth'] <= it['depth']:
                break
            low = c['name'].lower()
            if '@' in c['name'] and not any(k in low for k in
                                            ('hubport', 'interface', 'composite', 'hid', 'nub', 'client')):
                dev = c['name'].split('@')[0]; break
        ports.append({'port': it['name'], 'hub': (items[it['parent']]['name'].split('@')[0]
                                                  if it['parent'] is not None else None),
                      'device': dev, 'connect_count': it['connect'],
                      'overcurrent_count': it['overcurrent'], 'enum_fail_count': it['enumfail']})
    return ports


def hub_diagnose():
    """Hub 归因诊断 (运维/UI 用): 期望设备在位情况 + Hub 端口/供电 + 缺失原因提示"""
    topo = usb_topology(force_refresh=True)
    whis = set(_ARD_VID_WHITELIST)
    found = {d['vid']: d for d in topo['devices']}
    expected = []
    for label, vid in _EXPECTED_DEVICES:
        d = found.get(vid)
        expected.append({'device': label, 'vid': vid, 'present': bool(d),
                         'on_hub': d.get('on_hub') if d else None,
                         'hub': d.get('hub') if d else None,
                         'location': d.get('location') if d else None})
    ard = [d for d in topo['devices'] if d['vid'] in whis]
    arduino_ok = bool(ard) or bool(topo['serial_ports'])
    expected.append({'device': 'ARDUINO', 'vid': '|'.join(sorted(whis)), 'present': arduino_ok,
                     'on_hub': (ard[0].get('on_hub') if ard else None),
                     'hub': (ard[0].get('hub') if ard else None),
                     'serial': topo['serial_ports']})
    missing_reasons = []
    for e in expected:
        if e['present']:
            continue
        tip = ('设备未出现在 USB 总线上: 检查供电/换机身直插口; '
               '若为 Arduino 克隆需安装 CH340/CP210x 驱动并使用数据线')
        missing_reasons.append({'device': e['device'], 'reason': 'not_enumerated', 'tip': tip})
    ports = _ioreg_hub_ports()
    idle_ports = [p for p in ports if not p['device'] and (p['connect_count'] or 0) == 0]
    failed_ports = [p for p in ports if not p['device'] and (p['connect_count'] or 0) > 0]
    return {'hubs': topo['hubs'], 'devices': topo['devices'],
            'ports': ports,
            'idle_ports': [p['port'] for p in idle_ports],
            'enumerated_but_failed_ports': [p['port'] for p in failed_ports],
            'serial_ports': topo['serial_ports'], 'expected': expected,
            'missing': missing_reasons,
            'hub_ports_used': {h['name']: h['ports'] for h in topo['hubs']}}


# ══ Arduino 家族检测 (状态机 DUAL_ARDUINO 用, 5s 缓存) ══
_ARD_CACHE = {'ts': 0.0, 'present': False}
_ARD_CACHE_TTL = 5.0
_ARD_LOCK = threading.Lock()


def arduino_present(force_refresh=False):
    """Arduino 在位: (a) ioreg VID 白名单 (扁平 -p IOUSB + 层级 -c IOUSBHostDevice,
    Hub 下挂均可命中); (b) 串口节点回退 (/dev/cu.*usb*) — 克隆板 VID 不在白名单时兜底"""
    global _ARD_CACHE
    now = time.time()
    if not force_refresh and (now - _ARD_CACHE['ts']) < _ARD_CACHE_TTL:
        return _ARD_CACHE['present']
    with _ARD_LOCK:
        if not force_refresh and (time.time() - _ARD_CACHE['ts']) < _ARD_CACHE_TTL:
            return _ARD_CACHE['present']
        present = False
        try:
            raw = _ioreg_flat()
            for vid in _ARD_VID_WHITELIST:
                hexs = vid[2:].lower()
                decs = str(int(vid, 16))
                if f'idvendor" = {decs}' in raw or f'idvendor" = {hexs}' in raw:
                    present = True
                    break
            if not present:
                # 层级枚举兜底 (个别固件在 -p IOUSB 平面不暴露 idVendor)
                for d in _ioreg_tree_devices():
                    if _vid_match(d.get('vid'), _ARD_VID_WHITELIST):
                        present = True
                        break
            if not present:
                import glob as _glob
                for g in _SERIAL_PORT_GLOBS:
                    if _glob.glob(g):
                        present = True
                        break
        except Exception as e:
            logger.info(f"[vikey_official] arduino 扫描跳过: {e}")
        _ARD_CACHE = {'ts': time.time(), 'present': present}
        return present


if __name__ == '__main__':
    print('官方参数:', json.dumps({k: (v if k != 'source_files' else v) for k, v in OFFICIAL_CONSTS.items()},
                                  ensure_ascii=False, indent=1)[:400])
    ok, detail = official_present()
    print('VikeyFind:', json.dumps(detail, ensure_ascii=False))
    print('official_present:', ok, '| arduino_present:', arduino_present())
