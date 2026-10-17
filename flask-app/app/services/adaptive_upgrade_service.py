"""app.services.adaptive_upgrade_service 兼容层."""
import importlib
for _m in ("ai_adaptive_upgrade_service", "adaptive_upgrade_service", "ai_adaptive_upgrade_service", "adaptive_upgrade_service"):
    try:
        _mod = importlib.import_module(_m)
        adaptive_upgrade_service = getattr(_mod, "adaptive_upgrade_service", getattr(_mod, "adaptive_upgrade_service", _mod))
        break
    except Exception:
        continue
else:
    class adaptive_upgrade_service:
        pass
