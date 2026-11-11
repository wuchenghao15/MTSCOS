"""app.config 兼容层."""
import os
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent


class Config:
    """基础配置类."""
    SECRET_KEY = os.environ.get("SECRET_KEY", os.environ.get("MT_FLASK_SECRET_KEY", os.urandom(32).hex()))  # 🔒 P0 极密加固: 无默认硬编码
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "MT_MAIN_DB_PATH",
        f"sqlite:///{_BASE}/ai_engines/app.db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    JSON_AS_ASCII = False
    TEMPLATES_AUTO_RELOAD = True


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


_config_map = {"development": DevelopmentConfig, "production": ProductionConfig, "default": Config}


def load_config(name=None):
    """加载配置."""
    if name is None:
        name = os.environ.get("FLASK_ENV", "default")
    return _config_map.get(name, Config)
