#!/usr/bin/env python3
"""A1b patch: ai_link_guard_engine 加 daemon registry 心跳 (原版完全没有心跳代码)."""
import py_compile

FP = '/Users/wuchenghao/MTSCOS_AI_Project/flask-app/engines/ai_link_guard_engine.py'
src = open(FP, encoding='utf-8').read()
if 'mt_daemon_registry' in src:
    print('已有心跳, 跳过')
    raise SystemExit(0)

HEARTBEAT_FUNC = '''

def _daemon_hb():
    """A1b patch (flow_unified_ops_20261024): 补 registry 心跳 — 原版完全没有."""
    try:
        conn = sqlite3.connect(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'database', 'app.db'), timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
            "pid=?, status='RUNNING' WHERE process_name='ai_link_guard_engine'")
        conn.commit()
        conn.close()
    except Exception:
        pass
'''

INJECT = (
    "                _daemon_hb()\n"
    "                time.sleep(a.loop)\n"
)

src = src.replace("                time.sleep(a.loop)\n", INJECT, 1)
# 心跳函数插到 main() 前
src = src.replace('\ndef main()', HEARTBEAT_FUNC + '\n\ndef main()', 1)
open(FP, 'w', encoding='utf-8').write(src)
py_compile.compile(FP, doraise=True)
print('link_guard PATCHED + compiled OK')
