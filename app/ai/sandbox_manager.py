"""app.ai.sandbox_manager 兼容层."""
import sys, importlib
for _m in ("sandbox_manager", "ai_sandbox_manager"):
    try:
        _mod = importlib.import_module(_m)
        sandbox_manager = getattr(_mod, 'sandbox_manager', _mod)
        break
    except Exception:
        continue
else:
    class sandbox_manager:
        pass
