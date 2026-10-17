"""app.ai.question_bank_ai 兼容层."""
import importlib
for _m in ("ai_question_maintenance", "question_bank_ai"):
    try:
        _mod = importlib.import_module(_m)
        question_bank_ai_assistant = getattr(_mod, "question_bank_ai_assistant", _mod)
        ListeningLanguage = getattr(_mod, "ListeningLanguage", type("ListeningLanguage",(),{}))
        ListeningAccent = getattr(_mod, "ListeningAccent", type("ListeningAccent",(),{}))
        ListeningVoice = getattr(_mod, "ListeningVoice", type("ListeningVoice",(),{}))
        break
    except Exception:
        continue
else:
    class question_bank_ai_assistant: pass
    class ListeningLanguage: pass
    class ListeningAccent: pass
    class ListeningVoice: pass
class ListeningDifficulty: pass
class ListeningTest: pass
class ListeningExercise: pass
class ListeningScenario: pass
class ListeningQuestionType: pass
class ListeningTopic: pass
