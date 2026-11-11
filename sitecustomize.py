"""
╔══════════════════════════════════════════════════════════════════════╗
║  🛡️ sitecustomize.py — Python 进程启动时自动注入 SafeSqlite monkeypatch ║
║                                                                        ║
║  Python 启动时自动 import 这个文件 (如果在 sys.path 中).               ║
║  这样所有 daemon/Flask/Engine 不管是谁启动的, 都会自动:                 ║
║  1. sqlite3.connect() → 自动变成 autocommit + 短连接 + WAL             ║
║  2. 正确 PRAGMA (busy_timeout 短, synchronous=NORMAL)                  ║
║  3. 进程退出时所有未 close 的连接由 OS 自动回收                         ║
║                                                                        ║
║  零侵入: 不用改 25+ 个 ratio=0% 的文件                                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""
import sys
import os
import logging

# 先设置 logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('sitecustomize')

# 找到项目根目录 (这个文件在 flask-app/ 下)
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# 安装 monkeypatch
try:
    from core.safe_sqlite import install_sqlite3_monkeypatch
    install_sqlite3_monkeypatch(busy_timeout_ms=1500, timeout=3.0, autocommit=True)
    log.info('🛡️ SafeSqlite sitecustomize monkeypatch installed for PID=%d', os.getpid())
except Exception as e:
    # 不影响正常启动
    log.warning('SafeSqlite monkeypatch skipped: %s', e)
