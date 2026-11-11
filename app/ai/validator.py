"""app.ai.validator 兼容层."""
import sys, importlib
for _m in ("validator_ai", "ai_validator", "validator"):
    try:
        _mod = importlib.import_module(_m)
        validator_ai = getattr(_mod, 'validator_ai', _mod)
        break
    except Exception:
        continue
else:
    class validator_ai:
        pass
