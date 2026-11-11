"""app.version 兼容层.

系统版本号统一从单一权威源 core.version_source(flask-app/VERSION 文件)派生,
不再硬编码, 避免与 version_service / version_manager / system_upgrade_engine
等多处版本常量漂移。运行时展示权威为 system_versions 表, 二者由升级流程同步。
"""


def _load_version_info():
    try:
        from core.version_source import get_version_info
        return get_version_info()
    except Exception:
        pass
    try:
        import os as _os
        import sys as _sys
        # app/version.py → 上两级为 flask-app 根(含 VERSION 与 core/)
        _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from core.version_source import get_version_info
        return get_version_info()
    except Exception:
        return {'major': 22, 'minor': 2, 'patch': 0, 'tag': 'release', 'version': 'v22.2.0'}


_info = _load_version_info()

VERSION = _info.get('version') or 'v22.2.0'
VERSION_INFO = {
    'major': _info.get('major', 22),
    'minor': _info.get('minor', 2),
    'patch': _info.get('patch', 0),
    'tag': _info.get('tag', 'release'),
}


def get_version_info():
    return VERSION_INFO


def get_latest_version():
    return VERSION
