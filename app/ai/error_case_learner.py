"""app.ai.error_case_learner 兼容层."""
import importlib
try:
    _mod = importlib.import_module('error_case_learner')
    error_case_learner = getattr(_mod, 'error_case_learner', _mod)
except Exception:
    class error_case_learner: pass
