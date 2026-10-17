"""app.ai.enhanced_system 兼容层."""
import sys, importlib
for _m in ("enhanced_system", "ai_enhanced_system"):
    try:
        _mod = importlib.import_module(_m)
        enhanced_system = getattr(_mod, 'enhanced_system', _mod)
        break
    except Exception:
        continue
else:
    class enhanced_system:
        pass
