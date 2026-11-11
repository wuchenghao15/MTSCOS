"""app.ai.automation 兼容层."""
import sys, importlib
for _m in ("ai_automation_manager", "ai_automation", "automation_manager"):
    try:
        _mod = importlib.import_module(_m)
        ai_automation_manager = _mod
        break
    except Exception:
        continue
else:
    class ai_automation_manager:
        pass
