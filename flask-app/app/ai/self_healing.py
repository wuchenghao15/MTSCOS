"""app.ai.self_healing 兼容层."""
import importlib
for _m in ("self_healing", "ai_self_healing"):
    try:
        _mod = importlib.import_module(_m)
        SelfHealingSystem = getattr(_mod, "SelfHealingSystem", getattr(_mod, "self_healing", _mod))
        self_healing = _mod
        break
    except Exception:
        continue
else:
    class SelfHealingSystem:
        pass
    self_healing = SelfHealingSystem()
