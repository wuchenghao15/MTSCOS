#!/usr/bin/env python3
"""冰山五循环补全 patch (flow_unified_ops_20261023):
sys_consciousness daemon 的 pulse 只出 RESEARCH 快照 — 六大业务循环
(upgrade/ops/derive/strengthen/expand/research) 停 11 天无人触发.
在 90s 看门狗 alarm 清零后插入 run_iceberg_cycle (1800s 节流), 不受看门狗限制.
"""
import py_compile

FP = '/Users/wuchenghao/MTSCOS_AI_Project/_runtime/auto_daemons/sys_consciousness.py'
src = open(FP, encoding='utf-8').read()
if 'run_iceberg_cycle' in src:
    print('已 patch, 跳过')
    raise SystemExit(0)

OLD = """            _heartbeat()
            _signal.alarm(0)
            # 🆕 v5.1 参数热生效"""
NEW = """            _heartbeat()
            _signal.alarm(0)
            # 🧊 五循环补全 (flow_unified_ops_20261023): 六大业务循环此前无人触发
            # (rules_generated 停 11 天) — 1800s 节流跑 run_iceberg_cycle,
            # 置于 alarm 清零后不受 90s 看门狗限制
            if time.time() - _globals().get('_last_iceberg_cycle', 0) > 1800:
                try:
                    sys.path.insert(0, '/Users/wuchenghao/MTSCOS_AI_Project/flask-app/engines')
                    from iceberg_command import run_iceberg_cycle
                    _cyc = run_iceberg_cycle()
                    _globals()['_last_iceberg_cycle'] = time.time()
                    _log('[🧊 CYCLE] 六大循环: ' + ','.join(
                        k for k, v in _cyc.items() if isinstance(v, dict) and 'error' not in v))
                except Exception as _ce:
                    _log(f'[🧊 CYCLE] ❌ {_ce}')
            # 🆕 v5.1 参数热生效"""
assert OLD in src, 'anchor not found'
src = src.replace(OLD, NEW, 1)

# _globals 辅助 + import time 兜底 (插到 main_loop 定义前)
HELPER = '''

def _globals():
    return globals()

'''
if 'def _globals' not in src:
    src = src.replace('\ndef main_loop', HELPER + '\ndef main_loop', 1)

open(FP, 'w', encoding='utf-8').write(src)
py_compile.compile(FP, doraise=True)
print('PATCHED + compiled OK')
