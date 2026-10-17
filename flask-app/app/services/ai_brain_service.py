"""app.services.ai_brain_service 兼容层."""
import sys, importlib
for _m in ("ai_brain_service", "ai_ai_brain_service", "ai_brain"):
    try:
        _mod = importlib.import_module(_m)
        ai_brain_service = getattr(_mod, 'ai_brain_service', _mod)
        break
    except Exception:
        continue
else:
    class ai_brain_service:
        pass
