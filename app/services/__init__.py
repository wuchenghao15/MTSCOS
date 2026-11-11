"""app.services 兼容层 — 重导出到 ai_engines + stub."""
import importlib, sys, logging, types
from pathlib import Path
_BASE = Path(__file__).resolve().parent.parent.parent
_AI = _BASE / "ai_engines"
for _p in (str(_BASE), str(_AI)):
    if _p not in sys.path: sys.path.insert(0, _p)
logger = logging.getLogger("app.services")

_SERVICE_MAP = {
    "adaptive_upgrade_service": "ai_adaptive_learning_engine",
    "ai_brain_service": "ai_brain_feed_engine",
    "enhanced_ai_service": "enhanced_ai_service",
    "question_bank_service": "ai_question_bank_service",
    "rule_management": "smart_ai_rule_management",
}


class _Stub:
    def __init__(self, name): self._n = name
    def __call__(self, *a, **kw): return None
    def __getattr__(self, k): return _Stub(f"{self._n}.{k}")


for _sub, _ai in _SERVICE_MAP.items():
    try:
        _mod = importlib.import_module(_ai)
        sys.modules[f"app.services.{_sub}"] = _mod
    except Exception as _e:
        _stub = types.ModuleType(f"app.services.{_sub}")
        # 提供同名变量
        _stub_var = _Stub(_sub)
        setattr(_stub, _sub, _stub_var)
        sys.modules[f"app.services.{_sub}"] = _stub
        logger.debug(f"app.services.{_sub} → stub ({_e})")

# top-level 函数 stub
def get_system_version_service():
    return _Stub("system_version_service")
def get_javascript_optimization_service():
    return _Stub("js_optimization_service")
