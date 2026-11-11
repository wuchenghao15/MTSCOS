"""app.models.question 兼容层."""
class _Stub:
    def __init__(self, *a, **kw):
        for k,v in kw.items(): setattr(self, k, v)
    def save(self): return self
    def to_dict(self): return {}
    @classmethod
    def query(cls, *a, **kw): return []
    @classmethod
    def get(cls, *a, **kw): return None

Question = type("Question", (_Stub,), {})
QuestionType = type("QuestionType", (_Stub,), {})
QuestionManager = type("QuestionManager", (_Stub,), {})
question_manager = QuestionManager()
