"""app.ai.question_generator 兼容层."""
import sys, importlib
for _m in ("question_generator", "ai_question_generator"):
    try:
        _mod = importlib.import_module(_m)
        question_generator = getattr(_mod, 'question_generator', _mod)
        break
    except Exception:
        continue
else:
    class question_generator:
        pass
