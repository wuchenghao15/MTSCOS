"""app.utils 兼容层."""
import importlib, sys, logging, os, sqlite3
from pathlib import Path
_BASE = Path(__file__).resolve().parent.parent.parent
_AI = _BASE / "ai_engines"
for _p in (str(_BASE), str(_AI)):
    if _p not in sys.path: sys.path.insert(0, _p)


class _DbManager:
    """db_manager stub."""
    def __init__(self):
        self._db = os.environ.get("MT_MAIN_DB_PATH", str(_AI / "app.db"))
    def get_connection(self):
        return sqlite3.connect(self._db, timeout=15)
    def execute(self, sql, args=()):
        conn = sqlite3.connect(self._db, timeout=15)
        try:
            cur = conn.execute(sql, args)
            conn.commit()
            return cur.fetchall()
        finally:
            conn.close()
    def query(self, sql, args=()):
        return self.execute(sql, args)


db_manager = _DbManager()

# logger 兼容
logger = logging.getLogger("app")

# security_utils stub
class _SecurityUtils:
    def hash_password(self, p): import hashlib; return hashlib.sha256(p.encode()).hexdigest()
    def verify_password(self, p, h): return self.hash_password(p) == h
    def generate_token(self, l=32):
        import secrets; return secrets.token_hex(l)

security_utils = _SecurityUtils()
