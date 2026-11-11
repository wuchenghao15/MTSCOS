"""app.ai.ai_training_monitor 兼容层."""
import importlib
for _m in ("ai_training_monitor", "ai_ai_training_monitor"):
    try:
        _mod = importlib.import_module(_m)
        ai_training_monitor = getattr(_mod, 'ai_training_monitor', _mod)
        break
    except Exception:
        continue
else:
    class ai_training_monitor:
        pass
