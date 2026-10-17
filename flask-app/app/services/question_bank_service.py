"""app.services.question_bank_service 兼容层."""
import importlib
for _m in ("ai_question_bank_service", "question_bank_service", "ai_question_bank_service", "question_bank_service"):
    try:
        _mod = importlib.import_module(_m)
        question_bank_service = getattr(_mod, "question_bank_service", getattr(_mod, "question_bank_service", _mod))
        break
    except Exception:
        continue
else:
    class question_bank_service:
        pass
