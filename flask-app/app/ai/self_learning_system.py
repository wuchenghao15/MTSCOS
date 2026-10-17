"""app.ai.self_learning_system 兼容层."""
import sys, importlib
for _m in ("self_learning_system", "ai_self_learning", "ai_self_learning_system"):
    try:
        _mod = importlib.import_module(_m)
        if hasattr(_mod, 'self_learning_system'):
            self_learning_system = _mod.self_learning_system
        else:
            self_learning_system = _mod
        break
    except Exception:
        continue
else:
    class self_learning_system:
        pass
