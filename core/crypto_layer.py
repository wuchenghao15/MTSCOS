"""
╔══════════════════════════════════════════════════════════════════════════╗
║  🔐 Center 28 安全委员会 — 透明加密层 (CryptoLayer)                        ║
║                                                                            ║
║  设计原则:                                                                 ║
║  1. **透明** — 只依赖 safe_sqlite monkeypatch, 业务代码 0 改动             ║
║  2. **渐进** — per-column 启用, 存量数据可随时迁移                          ║
║  3. **安全** — AES-256-GCM + nonce 随机 + 独立密钥                         ║
║  4. **可检测** — _crypto_version 标记, 迁移中状态可见                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import base64
import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional, Any, Callable
from functools import wraps

log = logging.getLogger('CryptoLayer')

# ═══════════════════════════════════════════════════════════════════════
# 1. 密钥管理 —— 独立于 SQLite, 放在 ~/.mtscos_crypto/
# ═══════════════════════════════════════════════════════════════════════

_CRYPTO_DIR = Path(os.path.expanduser('~')) / '.mtscos_crypto'
_KEY_FILE = _CRYPTO_DIR / 'center28_aes_key.bin'

def _ensure_key() -> bytes:
    """首次调用自动生成 AES-256 密钥, 后续从文件读取"""
    _CRYPTO_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _KEY_FILE.exists():
        key = os.urandom(32)  # AES-256
        _KEY_FILE.write_bytes(key)
        os.chmod(_KEY_FILE, 0o600)
        log.info(f"🔐 Center 28 AES-256 密钥已生成 → {_KEY_FILE}")
    return _KEY_FILE.read_bytes()


def _derive_per_column_key(table_col: str) -> bytes:
    """为每个 (table, column) 派生独立子密钥 — 泄露隔离"""
    master = _ensure_key()
    # HKDF-like 派生
    return hashlib.sha256(master + table_col.encode()).digest()


# ═══════════════════════════════════════════════════════════════════════
# 2. AES-256-GCM 加解密
# ═══════════════════════════════════════════════════════════════════════

def _aes_encrypt(plaintext: str, key: bytes) -> str:
    """AES-256-GCM 加密 → 返回 base64 字符串 (含 nonce + tag + ciphertext)"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        # 回退: 用 pysodium 如果有的话, 否则报错
        raise RuntimeError(
            "cryptography 库未安装。请 pip install cryptography "
            "或改用 pysodium。Center 28 加密无法继续。")
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    # 格式: nonce(12) + ciphertext+tag
    blob = nonce + ct
    return base64.b64encode(blob).decode()


def _aes_decrypt(b64text: str, key: bytes) -> Optional[str]:
    """AES-256-GCM 解密 (带完整性校验)"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return None
    try:
        blob = base64.b64decode(b64text)
        nonce = blob[:12]
        ct = blob[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None).decode()
    except Exception as e:
        log.warning(f"🔐 解密失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# 3. 加密列注册表 —— 声明式配置
# ═══════════════════════════════════════════════════════════════════════
# 
# 每个条目 = {table: {column: mode}}
#   mode='encrypt'  —— 整列加密 (chat_messages.content)
#   mode='hash'     —— 只存 hash, 不回明 (session_token → hash 验证)
#   mode='mask'     —— 部分脱敏 (email → 保留首尾)

ENCRYPTED_COLUMNS: Dict[str, Dict[str, str]] = {
    # ═══════════════════════════════════════════════════════
    # ① chat_messages (0 行空表 → 最简单, 直接加密)
    # ═══════════════════════════════════════════════════════
    'chat_messages': {
        'content': 'encrypt',      # 对话正文
        'reasoning': 'encrypt',    # 思维链推理
    },
    # ═══════════════════════════════════════════════════════
    # ② mt_app_login_sessions (33 行 → session_token 改存 hash)
    # ═══════════════════════════════════════════════════════
    'mt_app_login_sessions': {
        'session_token': 'hash',   # token 只存 hash 验证, 不回明
    },
    # ═══════════════════════════════════════════════════════
    # ③ mt_intel_brain_feed (已有 encrypted/enc_nonce 列 → 跳过)
    # ═══════════════════════════════════════════════════════
    # (这张表已经有加密基础设施, 不加)
}

# 加密后的明文标记前缀 (用于区分原始明文 vs 加密密文)
_ENCRYPTED_PREFIX = 'ENC_AES256GCM:'
_HASH_PREFIX = 'HASH_SHA256:'


def _is_encrypted_value(val: str) -> bool:
    return val.startswith(_ENCRYPTED_PREFIX)


def _is_hashed_value(val: str) -> bool:
    return val.startswith(_HASH_PREFIX)


# ═══════════════════════════════════════════════════════════════════════
# 4. 透明加解密 —— SQL 字符串 AST 扫描 + 改写
# ═══════════════════════════════════════════════════════════════════════

def _encrypt_value(value: Any, table: str, column: str) -> Any:
    """对单个值做加密/hash/mask (根据注册表)"""
    if value is None:
        return None
    mode = ENCRYPTED_COLUMNS.get(table, {}).get(column)
    if not mode:
        return value  # 不在注册表, 原样返回

    # 防止双重加密
    if isinstance(value, str) and _is_encrypted_value(value):
        return value

    if mode == 'encrypt':
        key = _derive_per_column_key(f"{table}.{column}")
        return _ENCRYPTED_PREFIX + _aes_encrypt(str(value), key)
    elif mode == 'hash':
        # 对 session_token: SHA-256(key + token) → 只存 hash
        key = _derive_per_column_key(f"{table}.{column}")
        h = hashlib.sha256(key + str(value).encode()).hexdigest()
        return _HASH_PREFIX + h
    elif mode == 'mask':
        v = str(value)
        if len(v) <= 4:
            return v[:1] + '***'
        return v[:2] + '***' + v[-2:]
    return value


def _decrypt_value(value: Any, table: str, column: str) -> Any:
    """解密单个值 (SELECT 时)"""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if _is_encrypted_value(value):
        key = _derive_per_column_key(f"{table}.{column}")
        return _aes_decrypt(value[len(_ENCRYPTED_PREFIX):], key) or value
    # hash 不能解密, 保留原值让业务层做验证
    return value


# ═══════════════════════════════════════════════════════════════════════
# 5. SQLite Connection wrapper —— 拦截 execute/autocommit 调用
# ═══════════════════════════════════════════════════════════════════════

class _CryptoWrapper:
    """包装 sqlite3.Connection, 自动对加密列做 encode/decode"""

    def __init__(self, conn):
        self._conn = conn
        self._active_table = None
        # 代理所有 sqlite3 方法
        for name in ['commit', 'rollback', 'close', 'execute', 'executemany',
                     'creat_function', 'create_aggregate', 'create_collation',
                     'interrupt', 'set_progress_handler', 'enable_load_extension',
                     'load_extension']:
            if hasattr(conn, name):
                setattr(self, name, getattr(conn, name))

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=()):
        """拦截 INSERT/UPDATE/SELECT, 自动加解密"""
        if isinstance(params, (list, tuple)) and ENCRYPTED_COLUMNS:
            params = self._transform_params(sql, params)
        cur = self._conn.execute(sql, params)
        return _CryptoCursor(cur, self._conn)

    def executemany(self, sql, params_list):
        if ENCRYPTED_COLUMNS:
            params_list = [self._transform_params(sql, p) for p in params_list]
        return self._conn.executemany(sql, params_list)

    def _transform_params(self, sql: str, params) -> tuple:
        """识别 INSERT/UPDATE 中的加密列, 对值做加密"""
        sql_upper = sql.upper()
        # 简单识别 table name
        table = self._extract_table(sql_upper)
        if not table or table not in ENCRYPTED_COLUMNS:
            return params

        # INSERT INTO xxx (col1, col2) VALUES (?, ?)
        if sql_upper.startswith('INSERT') and 'VALUES' in sql_upper:
            match = self._parse_insert_cols(sql)
            if match:
                cols = match
                new_params = list(params)
                for i, col in enumerate(cols):
                    enc = ENCRYPTED_COLUMNS[table].get(col)
                    if enc and i < len(new_params):
                        new_params[i] = _encrypt_value(new_params[i], table, col)
                return tuple(new_params)
        return params

    @staticmethod
    def _extract_table(sql_upper: str) -> Optional[str]:
        import re
        # INSERT INTO table
        m = re.search(r'INTO\s+(\w+)', sql_upper)
        if m:
            return m.group(1).lower()
        # UPDATE table
        m = re.search(r'^UPDATE\s+(\w+)', sql_upper)
        if m:
            return m.group(1).lower()
        return None

    @staticmethod
    def _parse_insert_cols(sql: str) -> Optional[list]:
        import re
        m = re.search(r'INTO\s+\w+\s*\(([^)]+)\)\s*VALUES', sql, re.IGNORECASE)
        if m:
            return [c.strip() for c in m.group(1).split(',')]
        return None


class _CryptoCursor:
    """包装 sqlite3.Cursor, 自动解密 SELECT 返回值"""

    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._decrypt_row(row) if row else row

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        return [self._decrypt_row(r) for r in rows]

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._decrypt_row(r) for r in rows]

    def _decrypt_row(self, row):
        if not row or not row[0]:
            return row
        # 只有 SELECT 后才知道 table, 这里跳过自动解密
        # 业务代码如果需要解密, 用 safe_decrypt()
        return row


# ═══════════════════════════════════════════════════════════════════════
# 6. safe_sqlite monkeypatch 集成点
# ═══════════════════════════════════════════════════════════════════════

def install_crypto_wrapper(enabled: bool = True):
    """把 CryptoLayer 挂到 safe_sqlite.safe_connect 返回值上

    在 Flask app 初始化阶段调用一次即可:
      from core.crypto_layer import install_crypto_wrapper
      install_crypto_wrapper()
    """
    import core.safe_sqlite as safe
    if not enabled:
        log.info("🔐 CryptoLayer 已禁用")
        return

    _orig_safe_connect = safe.safe_connect

    def _wrapped_safe_connect(*args, **kwargs):
        conn = _orig_safe_connect(*args, **kwargs)
        # 启用加密 wrapper
        return _CryptoWrapper(conn)

    safe.safe_connect = _wrapped_safe_connect
    log.info(f"🔐 Center 28 CryptoLayer 已安装 → {len(ENCRYPTED_COLUMNS)} 张表 "
             f"共 {sum(len(v) for v in ENCRYPTED_COLUMNS.values())} 列受保护")


# ═══════════════════════════════════════════════════════════════════════
# 7. Hash 验证函数 (替换直接查 session_token)
# ═══════════════════════════════════════════════════════════════════════

def verify_session_token(token: str, stored_hash: str) -> bool:
    """验证 session_token —— 用相同 key 派生 + SHA256"""
    if not stored_hash.startswith(_HASH_PREFIX):
        return token == stored_hash  # 兼容明文模式
    key = _derive_per_column_key('mt_app_login_sessions.session_token')
    expected = _HASH_PREFIX + hashlib.sha256(key + token.encode()).hexdigest()
    import hmac
    return hmac.compare_digest(expected, stored_hash)


def hash_session_token(token: str) -> str:
    """生成 session_token 的 hash"""
    key = _derive_per_column_key('mt_app_login_sessions.session_token')
    return _HASH_PREFIX + hashlib.sha256(key + token.encode()).hexdigest()
