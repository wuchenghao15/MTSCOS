"""app.services.rule_management 兼容层."""
import importlib
for _m in ("ai_rule_management", "rule_management", "ai_rule_management_service", "rule_management_service"):
    try:
        _mod = importlib.import_module(_m)
        rule_management_service = getattr(_mod, "rule_management_service", getattr(_mod, "rule_management", _mod))
        break
    except Exception:
        continue
else:
    class rule_management_service:
        pass
