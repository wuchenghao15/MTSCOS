"""
══════════════════════════════════════════════════════════════════════════╗
║  🛡️ sitecustomize — Python 启动时自动加载                                ║
║                                                                            ║
║  位置: flask-app/ 根目录 (需要 PYTHONPATH=flask-app 才会被 site.py 找到)   ║
║  主 patch 已由 homebrew sitecustomize 执行 (sys.path[2], 最先加载)        ║
║  本文件做幂等补 + CryptoLayer 二次加固                                      ║
║                                                                            ║
║  三层保障:                                                                  ║
║  ① homebrew sitecustomize.py (sys.path[2]) — 全局 patch sqlite3.connect   ║
║  ② user site-packages/sitecustomize.py (sys.path[4]) — 幂等补             ║
║  ③ flask-app/sitecustomize.py (本文件) — CryptoLayer 二次加固              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import sys
import os
import logging

log = logging.getLogger('sitecustomize')

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# ═══════════════════════════════════════════════════════════════════════
# 1. SafeSqlite 幂等补 —— 如果 homebrew sitecustomize 还没 patch, 这里补
# ═══════════════════════════════════════════════════════════════════════
try:
    import sqlite3 as _sqlite3_mod
    if not getattr(_sqlite3_mod, '_mtscos_v2_patched', False):
        # homebrew sitecustomize 没生效 (可能 Python 版本不同或路径差异)
        _orig_connect = _sqlite3_mod.connect

        def _mtscos_fallback_connect(*args, **kwargs):
            kwargs.setdefault('timeout', 30)
            conn = _orig_connect(*args, **kwargs)
            try:
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=30000')
                conn.execute('PRAGMA synchronous=NORMAL')
                conn.row_factory = _sqlite3_mod.Row
            except Exception:
                pass
            return conn

        _sqlite3_mod.connect = _mtscos_fallback_connect
        _sqlite3_mod._mtscos_v2_patched = True
        _sqlite3_mod._mtscos_orig_connect = _orig_connect
        log.info(f"🛡️  SafeSqlite fallback patch (PID={os.getpid()})")
except Exception as e:
    print(f"⚠️ SafeSqlite patch 失败: {e}")

# ═══════════════════════════════════════════════════════════════════════
# 2. CryptoLayer — 透明加密 (Center 28)
# ═══════════════════════════════════════════════════════════════════════
try:
    from core.safe_sqlite import safe_connect
    from core.crypto_layer import _CryptoWrapper, ENCRYPTED_COLUMNS

    # 检查是否已被 homebrew sitecustomize patch 过
    _orig_safe = safe_connect
    # 简单标记: 检查 safe_connect 是不是已经 wrapper 过
    if not getattr(safe_connect, '_crypto_wrapped', False):
        def _wrapped_safe_connect(*args, **kwargs):
            conn = _orig_safe(*args, **kwargs)
            return _CryptoWrapper(conn)
        _wrapped_safe_connect._crypto_wrapped = True

        import core.safe_sqlite as _safe_mod
        _safe_mod.safe_connect = _wrapped_safe_connect

        log.info(f"🔐 Center 28 CryptoLayer → "
                 f"{len(ENCRYPTED_COLUMNS)} 表, "
                 f"{sum(len(v) for v in ENCRYPTED_COLUMNS.values())} 列")
except Exception as e:
    print(f"⚠️ CryptoLayer (可忽略): {e}")
