"""app.ai.rule_manager 兼容层."""
import sys, importlib
for _m in ("rule_manager", "ai_rule_manager"):
    try:
        _mod = importlib.import_module(_m)
        rule_manager_ai = getattr(_mod, 'rule_manager_ai', getattr(_mod, 'RuleManagerAI', _mod))
        break
    except Exception:
        continue
else:
    class rule_manager_ai:
        pass
