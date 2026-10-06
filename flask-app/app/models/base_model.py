"""app.models.base_model 兼容层 (SYS-NORM修复)."""

class _Stub:
    __tablename__ = None
    table_name = None
    primary_key = 'id'
    columns = {}

    def __init__(self, *a, **kw):
        for k,v in kw.items(): setattr(self, k, v)
    def save(self): return self
    def to_dict(self): return {k:v for k,v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def create_table(cls, *a, **kw): return True
    @classmethod
    def drop_table(cls, *a, **kw): return True
    @classmethod
    def create_tables(cls, *a, **kw): return True
    @classmethod
    def get_or_none(cls, *a, **kw): return None
    @classmethod
    def get_by_id(cls, *a, **kw): return None
    @classmethod
    def get_all(cls, *a, **kw): return []
    @classmethod
    def select(cls, *a, **kw): return []
    @classmethod
    def insert(cls, *a, **kw): return None
    @classmethod
    def update(cls, *a, **kw): return None
    @classmethod
    def delete(cls, *a, **kw): return None
    @classmethod
    def query(cls, *a, **kw): return []
    @classmethod
    def get(cls, *a, **kw): return None
    @classmethod
    def all(cls): return []
BaseModel = type('BaseModel', (_Stub,), {})
__all__ = ['BaseModel'.replace(',', "',' ")]
