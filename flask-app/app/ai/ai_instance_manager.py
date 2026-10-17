"""app.ai.ai_instance_manager 兼容层."""
import importlib
for _m in ("ai_request_classifier", "ai_instance_manager"):
    try:
        _mod = importlib.import_module(_m)
        ai_instance_manager = getattr(_mod, "ai_instance_manager", _mod)
        break
    except Exception:
        continue
else:
    class ai_instance_manager:
        pass
