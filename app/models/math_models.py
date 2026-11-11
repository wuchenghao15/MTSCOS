"""app.models.math_models 兼容层 (SYS-NORM修复)."""

class _Stub:
    def __init__(self, *a, **kw):
        for k,v in kw.items(): setattr(self, k, v)
    def save(self): return self
    def to_dict(self): return {k:v for k,v in self.__dict__.items() if not k.startswith('_')}
    @classmethod
    def query(cls, *a, **kw): return []
    @classmethod
    def get(cls, *a, **kw): return None
    @classmethod
    def all(cls): return []
MathProblem = type('MathProblem', (_Stub,), {})
MATH_CATEGORIES = type('MATH_CATEGORIES', (_Stub,), {})
__all__ = ['MathProblem, MATH_CATEGORIES'.replace(',', "',' ")]
