"""app.ai.error_case_collector 兼容层."""
import importlib
for _m in ("error_case_collector", "ai_error_case_collector"):
    try:
        _mod = importlib.import_module(_m)
        error_case_collector = getattr(_mod, "error_case_collector", _mod)
        break
    except Exception:
        continue
else:
    class error_case_collector:
        pass
