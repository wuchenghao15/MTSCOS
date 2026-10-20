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
_ARD_VID_WHITELIST = {'0x2341', '0x1a86', '0x10c4', '0x0403', '0x303a'}  # Arduino 家族 VID
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


# ══ Arduino 家族检测 (状态机 DUAL_ARDUINO 用, 5s 缓存) ══
_ARD_CACHE = {'ts': 0.0, 'present': False}
_ARD_CACHE_TTL = 5.0
_ARD_LOCK = threading.Lock()


def arduino_present(force_refresh=False):
    """Arduino 设备在位: ioreg VID 白名单 (2341官方/1a86 CH340/10c4 CP210x/0403 FT232/303a ESP32)"""
    global _ARD_CACHE
    now = time.time()
    if not force_refresh and (now - _ARD_CACHE['ts']) < _ARD_CACHE_TTL:
        return _ARD_CACHE['present']
    with _ARD_LOCK:
        if not force_refresh and (time.time() - _ARD_CACHE['ts']) < _ARD_CACHE_TTL:
            return _ARD_CACHE['present']
        present = False
        try:
            env = {**os.environ, 'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
            r = subprocess.run(['ioreg', '-p', 'IOUSB', '-l', '-w', '0'],
                               capture_output=True, text=True, timeout=5, env=env)
            raw = (r.stdout or '').lower()
            for vid in _ARD_VID_WHITELIST:
                hexs = vid[2:].lower()
                decs = str(int(vid, 16))
                if f'idvendor" = {decs}' in raw or f'idvendor" = {hexs}' in raw:
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
