"""app.models.ai 兼容层 (SYS-NORM修复)."""

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
AIInstance = type('AIInstance', (_Stub,), {})
AICollection = type('AICollection', (_Stub,), {})
__all__ = ['AIInstance, AICollection'.replace(',', "',' ")]
