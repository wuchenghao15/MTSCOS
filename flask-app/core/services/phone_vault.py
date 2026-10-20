# -*- coding: utf-8 -*-
"""
用户手机号加密存储 (个保法 P2 整改: 敏感个人信息不得明文落库)
================================================================
设计原则:
  ① 明文永不落库: 只存 Fernet 密文 + HMAC-SHA256 指纹 (指纹供唯一性/查找, 不可逆)
  ② 密钥不落仓库: 默认读 MTSCOS_PHONE_KEY 环境变量, 否则落 _runtime/secrets/phone_vault.key (0600)
  ③ 展示一律脱敏: 138****8888
  ④ 幂等建表: mt_user_phone_vault(user_id / phone_enc / phone_fp / updated_at)

来源: flow_敏感_用户手机号加密存储_1790217583
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import stat
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
KEY_DIR = os.path.join(PROJECT_ROOT, "_runtime", "secrets")
KEY_FILE = os.path.join(KEY_DIR, "phone_vault.key")
PREFIX = "pv1:"
TABLE = "mt_user_phone_vault"


def _load_key() -> bytes:
    """读取密钥: 环境变量优先, 其次本地密钥文件 (不存在则生成)。"""
    env = os.environ.get("MTSCOS_PHONE_KEY", "").strip()
    if env:
        return env.encode()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            key = f.read().strip()
        if key:
            return key
    from cryptography.fernet import Fernet
    os.makedirs(KEY_DIR, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    return key


def normalize(phone: str) -> str:
    """去空格/横线, 保留数字与前导 +。"""
    s = re.sub(r"[\s\-()]", "", str(phone or "").strip())
    return s


def encrypt(phone: str) -> str:
    from cryptography.fernet import Fernet
    raw = normalize(phone)
    if not raw:
        return ""
    return PREFIX + Fernet(_load_key()).encrypt(raw.encode()).decode()


def decrypt(token: str) -> str:
    from cryptography.fernet import Fernet
    t = str(token or "")
    if not t.startswith(PREFIX):
        return ""
    try:
        return Fernet(_load_key()).decrypt(t[len(PREFIX):].encode()).decode()
    except Exception:
        return ""


def fingerprint(phone: str) -> str:
    """不可逆指纹: 供唯一性校验/查找, 相同号码同指纹。"""
    raw = normalize(phone)
    if not raw:
        return ""
    return hmac.new(_load_key(), raw.encode(), hashlib.sha256).hexdigest()


def mask(phone: str) -> str:
    """脱敏展示: 13812345678 → 138****5678; 非 11 位则保留首尾各 2 位。"""
    raw = normalize(phone)
    if not raw:
        return ""
    if len(raw) == 11:
        return f"{raw[:3]}****{raw[-4:]}"
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


def ensure_schema(db_path: str) -> None:
    c = sqlite3.connect(db_path, timeout=15)
    try:
        c.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            user_id     TEXT PRIMARY KEY,
            phone_enc   TEXT NOT NULL,
            phone_fp    TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )""")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_phone_vault_fp ON {TABLE}(phone_fp)")
        c.commit()
    finally:
        c.close()


def store_phone(db_path: str, user_id, phone: str) -> bool:
    """加密落库; 传空串表示解绑 (删除记录)。返回是否写入成功。"""
    ensure_schema(db_path)
    uid = str(user_id)
    c = sqlite3.connect(db_path, timeout=15)
    try:
        if not normalize(phone):
            c.execute(f"DELETE FROM {TABLE} WHERE user_id=?", (uid,))
            c.commit()
            return True
        import time
        c.execute(f"""INSERT INTO {TABLE} (user_id, phone_enc, phone_fp, updated_at)
                      VALUES (?,?,?,?)
                      ON CONFLICT(user_id) DO UPDATE SET
                        phone_enc=excluded.phone_enc,
                        phone_fp=excluded.phone_fp,
                        updated_at=excluded.updated_at""",
                  (uid, encrypt(phone), fingerprint(phone),
                   time.strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
        return True
    except Exception:
        return False
    finally:
        c.close()


def load_phone(db_path: str, user_id) -> str:
    """解密取回明文 (仅供本人鉴权后的展示/业务使用, 不得落日志)。"""
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=8)
        row = c.execute(f"SELECT phone_enc FROM {TABLE} WHERE user_id=?", (str(user_id),)).fetchone()
        c.close()
        return decrypt(row[0]) if row else ""
    except Exception:
        return ""


def masked_phone(db_path: str, user_id) -> str:
    return mask(load_phone(db_path, user_id))


def selftest() -> int:
    """自检: 加解密一致性 + 指纹稳定 + 脱敏 + 密文不含明文。"""
    import tempfile
    db = os.path.join(tempfile.mkdtemp(), "vault_selftest.db")
    ok = True
    sample = "13812345678"
    enc = encrypt(sample)
    ok &= decrypt(enc) == sample
    print(f"  encrypt/decrypt: {'OK' if decrypt(enc) == sample else 'FAIL'}")
    ok &= fingerprint(sample) == fingerprint("138 1234 5678")
    print(f"  fingerprint 归一: {'OK' if fingerprint(sample) == fingerprint('138 1234 5678') else 'FAIL'}")
    ok &= mask(sample) == "138****5678"
    print(f"  mask: {mask(sample)}")
    store_phone(db, 1, sample)
    ok &= load_phone(db, 1) == sample
    ok &= masked_phone(db, 1) == "138****5678"
    print(f"  db 存取: {'OK' if load_phone(db, 1) == sample else 'FAIL'}")
    with open(db, "rb") as f:
        blob = f.read()
    ok &= sample.encode() not in blob
    print(f"  明文不落库: {'OK' if sample.encode() not in blob else 'FAIL'}")
    ok &= store_phone(db, 1, "") and load_phone(db, 1) == ""
    print(f"  解绑删除: {'OK' if load_phone(db, 1) == '' else 'FAIL'}")
    print("✅ selftest PASS" if ok else "❌ selftest FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else 0)
