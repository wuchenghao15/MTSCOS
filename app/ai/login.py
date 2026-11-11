"""app.ai.login 兼容层."""
import sys, importlib
for _m in ("login_ai", "ai_login", "login"):
    try:
        _mod = importlib.import_module(_m)
        LoginAI = getattr(_mod, 'LoginAI', getattr(_mod, 'LoginAIClass', None))
        if LoginAI is None:
            LoginAI = getattr(_mod, 'login_ai', _mod)
        break
    except Exception:
        continue
else:
    class LoginAI:
        pass
