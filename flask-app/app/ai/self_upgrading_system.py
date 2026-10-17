"""app.ai.self_upgrading_system 兼容层."""
import sys, importlib
for _m in ("ai_self_upgrading_system", "self_upgrading_system"):
    try:
        _mod = importlib.import_module(_m)
        if hasattr(_mod, 'AISelfUpgradingSystem'):
            AISelfUpgradingSystem = _mod.AISelfUpgradingSystem
            break
        elif hasattr(_mod, 'SelfUpgradingSystem'):
            AISelfUpgradingSystem = _mod.SelfUpgradingSystem
            break
    except Exception:
        continue
else:
    class AISelfUpgradingSystem:
        pass
