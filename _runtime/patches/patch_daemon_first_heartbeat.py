#!/usr/bin/env python3
"""A1 patch: daemon 启动后立即跳第一跳 (原版心跳在循环尾, 第一跳要等整个 CYCLE,
archive 6h — 造成'拉活后心跳不跳'假死观感). 在 time.sleep(_offset) 后插一次 _heartbeat().
"""
import re, sys

FILES = [
    '/Users/wuchenghao/MTSCOS_AI_Project/_runtime/auto_daemons/sys_archive_engine.py',
    '/Users/wuchenghao/MTSCOS_AI_Project/_runtime/auto_daemons/sys_crypto_key_rotate.py',
    '/Users/wuchenghao/MTSCOS_AI_Project/_runtime/auto_daemons/sys_wecom_meeting.py',
]
INJECT = (
    "    # A1 patch (flow_unified_ops_20261024): 启动立即跳第一跳 —\n"
    "    # 原版 _heartbeat 在循环尾, 第一跳要等整个 CYCLE (archive 6h), 造成假死观感\n"
    "    try:\n        _heartbeat()\n    except Exception:\n        pass\n"
)

for fp in FILES:
    src = open(fp, encoding='utf-8').read()
    if 'A1 patch' in src:
        print(f'{fp}: 已 patch, 跳过')
        continue
    m = re.search(r'( *)time\.sleep\(_offset\)\n', src)
    if not m:
        print(f'{fp}: 未找到 sleep(_offset), 跳过!')
        continue
    if 'def _heartbeat' not in src:
        print(f'{fp}: 无 _heartbeat 函数, 跳过!')
        continue
    patched = src[:m.end()] + INJECT + src[m.end():]
    open(fp, 'w', encoding='utf-8').write(patched)
    import py_compile
    py_compile.compile(fp, doraise=True)
    print(f'{fp}: PATCHED + compiled OK')
