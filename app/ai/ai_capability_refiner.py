"""app.ai.ai_capability_refiner 兼容层."""
import sys, importlib
for _m in ("ai_capability_refiner", "ai_ai_capability_refiner"):
    try:
        _mod = importlib.import_module(_m)
        ai_capability_refiner = getattr(_mod, 'ai_capability_refiner', _mod)
        break
    except Exception:
        continue
else:
    class ai_capability_refiner:
        pass
