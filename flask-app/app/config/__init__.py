"""app.config 包 — 兼容层补充 (SYS-NORM修复)."""
import os
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "mtscos-dev-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("MT_MAIN_DB_PATH", f"sqlite:///{_BASE}/ai_engines/app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    JSON_AS_ASCII = False

    def get(self, key, default=None):
        # 兼容类本身调用: Config.get('K', default) → 实例.get('K', default)
        if not isinstance(key, str):
            return default
        return getattr(self, key, default)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


def load_config(name=None):
    if name is None:
        name = os.environ.get("FLASK_ENV", "default")
    _map = {"development": DevelopmentConfig, "production": ProductionConfig, "default": Config}
    return _map.get(name, Config)
