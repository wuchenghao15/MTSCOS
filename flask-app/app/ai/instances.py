"""app.ai.instances 兼容层."""
import sys, importlib
for _m in ("ai_instance_manager", "ai_request_classifier", "instances"):
    try:
        _mod = importlib.import_module(_m)
        ai_instance_manager = getattr(_mod, 'ai_instance_manager', _mod)
        break
    except Exception:
        continue
else:
    class ai_instance_manager:
        pass
