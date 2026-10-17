"""app.ai 兼容层 — 不强制注册子模块, 让 Python 自然导入 .py 文件.
每个子模块文件 (automation.py, validator.py 等) 自行处理重导出.
缺失的类/函数用 stub 兜底."""
import sys, logging
from pathlib import Path
_BASE = Path(__file__).resolve().parent.parent.parent
_AI = _BASE / "ai_engines"
for _p in (str(_BASE), str(_AI)):
    if _p not in sys.path: sys.path.insert(0, _p)
logger = logging.getLogger("app.ai")


class _Stub:
    def __init__(self, name): self._n = name
    def __call__(self, *a, **kw): return None
    def __getattr__(self, k): return _Stub(f"{self._n}.{k}")


DeepSelfLearning = _Stub("DeepSelfLearning")
get_deep_self_learning = _Stub("get_deep_self_learning")
