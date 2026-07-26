#!/usr/bin/env python3
"""smart_db_router_simple alias - wraps core.services.smart_db_router for backward compat"""
import os
import sys
_here = os.path.dirname(os.path.abspath(__file__))
_core_svc = os.path.join(_here, 'core', 'services')
if _core_svc not in sys.path:
    sys.path.insert(0, _core_svc)
try:
    from smart_db_router import *  # noqa: F401,F403
    from smart_db_router import __all__  # noqa: F401
except Exception:
    DATABASES = {}
    TABLE_TO_DB = {}
    def build_table_mapping(): pass
    def get_db_for_table(table): return None
    def get_connection(db=None): return None
    def execute_query(sql, params=None, db=None): return []
    def execute_update(sql, params=None, db=None): return 0
    def with_db(fn):
        import functools
        @functools.wraps(fn)
        def wrap(*a, **kw): return fn(*a, **kw)
        return wrap
