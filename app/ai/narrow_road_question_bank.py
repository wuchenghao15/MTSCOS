"""app.ai.narrow_road_question_bank 兼容层."""
import importlib
for _m in ("narrow_road_question_bank", "ai_narrow_road_question_bank"):
    try:
        _mod = importlib.import_module(_m)
        narrow_road_question_bank = getattr(_mod, 'narrow_road_question_bank', _mod)
        break
    except Exception:
        continue
else:
    class narrow_road_question_bank:
        pass
