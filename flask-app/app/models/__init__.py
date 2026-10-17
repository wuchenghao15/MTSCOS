"""app.models 兼容层 — 提供轻量 model stub."""
import logging, types
logger = logging.getLogger("app.models")


class _ModelStub:
    """通用 model stub: 支持 __init__/属性访问/类方法."""
    def __init__(self, *a, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
    def save(self):
        return self
    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
    @classmethod
    def query(cls, *a, **kw):
        return []
    @classmethod
    def get(cls, *a, **kw):
        return None
    @classmethod
    def all(cls):
        return []


# 具体 model 类
AIInstance = type("AIInstance", (_ModelStub,), {})
AICollection = type("AICollection", (_ModelStub,), {})
AIBrainKnowledge = type("AIBrainKnowledge", (_ModelStub,), {})
AIBrainActivity = type("AIBrainActivity", (_ModelStub,), {})
AIRule = type("AIRule", (_ModelStub,), {})
Backup = type("Backup", (_ModelStub,), {})
BaseModel = _ModelStub
EnhancedAIEmployee = type("EnhancedAIEmployee", (_ModelStub,), {})
LogEntry = type("LogEntry", (_ModelStub,), {})
MathProblem = type("MathProblem", (_ModelStub,), {})
MATH_CATEGORIES = {}
Rule = type("Rule", (_ModelStub,), {})
User = type("User", (_ModelStub,), {})
UserSnapshot = type("UserSnapshot", (_ModelStub,), {})
