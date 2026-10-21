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


def ensure_schema(db_path: str, table: str = "") -> None:
    """幂等建表 (flow_vault_20261021 泛化): table 可指定 phone/email 各自 vault 表。"""
    t = table or TABLE
    c = sqlite3.connect(db_path, timeout=15)
    try:
        c.execute(f"""CREATE TABLE IF NOT EXISTS {t} (
            user_id     TEXT PRIMARY KEY,
            phone_enc   TEXT NOT NULL,
            phone_fp    TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )""")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_fp ON {t}(phone_fp)")
        c.commit()
    finally:
        c.close()


def store_field(db_path: str, vault_table: str, user_id, value: str) -> bool:
    """通用加密落库 (flow_vault_20261021 泛化): 表名参数化, phone/email 各自 vault 表。"""
    ensure_schema(db_path, vault_table)
    uid = str(user_id)
    c = sqlite3.connect(db_path, timeout=15)
    try:
        if not normalize(value):
            c.execute(f"DELETE FROM {vault_table} WHERE user_id=?", (uid,))
            c.commit()
            return True
        import time
        c.execute(f"""INSERT INTO {vault_table} (user_id, phone_enc, phone_fp, updated_at)
                      VALUES (?,?,?,?)
                      ON CONFLICT(user_id) DO UPDATE SET
                        phone_enc=excluded.phone_enc,
                        phone_fp=excluded.phone_fp,
                        updated_at=excluded.updated_at""",
                  (uid, encrypt(value), fingerprint(value),
                   time.strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
        return True
    except Exception:
        return False
    finally:
        c.close()


def load_field(db_path: str, vault_table: str, user_id) -> str:
    """通用解密读取 (仅限本人鉴权后的业务使用, 不得落日志)。"""
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=8)
        row = c.execute(f"SELECT phone_enc FROM {vault_table} WHERE user_id=?", (str(user_id),)).fetchone()
        c.close()
        return decrypt(row[0]) if row else ""
    except Exception:
        return ""


def store_phone(db_path: str, user_id, phone: str) -> bool:
    """加密落库; 传空串表示解绑 (删除记录)。返回是否写入成功。"""
    return store_field(db_path, TABLE, user_id, phone)


def load_phone(db_path: str, user_id) -> str:
    """解密取回明文 (仅供本人鉴权后的展示/业务使用, 不得落日志)。"""
    return load_field(db_path, TABLE, user_id)


EMAIL_TABLE = "mt_user_email_vault"


def migrate_users_email(db_path: str) -> int:
    """存量迁移: users.email 明文 → mt_user_email_vault, 迁移后清空明文列。
    (flow_vault_20261021, 个保法 P2 — 实测存量仅 5 条)"""
    ensure_schema(db_path, EMAIL_TABLE)
    c = sqlite3.connect(db_path, timeout=15)
    n = 0
    try:
        rows = c.execute("SELECT id, email FROM users "
                         "WHERE email IS NOT NULL AND email<>'' AND email NOT LIKE 'pv1:%'").fetchall()
        ok_uids = []
        for uid, email in rows:
            # 注意: store_field 开独立连接写库, 外层连接须保持只读直到收集完,
            # 否则未提交 UPDATE 的写锁会让后续 INSERT 锁等待失败 (实测 5 条只迁 1 条)
            if store_field(db_path, EMAIL_TABLE, uid, email):
                ok_uids.append(uid)
        for uid in ok_uids:
            # users.email 有 UNIQUE 约束, 不能多行同置 '' → 每行唯一墓碑 pv1:uid:{uid}
            c.execute("UPDATE users SET email=?, email_enc='' WHERE id=?", (f"pv1:uid:{uid}", uid))
        c.commit()
        n = len(ok_uids)
        print(f"[migrate] users.email → {EMAIL_TABLE}: 迁移 {n} 条, 明文列已清空")
    except Exception as _e:
        print(f"[migrate] err: {_e}")
    finally:
        c.close()
    return n


def masked_phone(db_path: str, user_id) -> str:
    return mask(load_phone(db_path, user_id))


PASSWORD_TABLE = "mt_user_password_vault"


def migrate_users_password(db_path: str) -> int:
    """存量迁移: users.password/password_hash/password_hash_enc 哈希 → mt_user_password_vault.
    (flow_password_vault_20261021 — password 三列存的本身是哈希, 金库存其 Fernet 密文)
    零丢失红线: 逐行「金库写入+回读对账」全部通过后才清该行原列;
    任一行失败则该行原列保留 (走旧读取路径, 保证可登录)。"""
    ensure_schema(db_path, PASSWORD_TABLE)
    c = sqlite3.connect(db_path, timeout=30)
    n = 0
    try:
        cols = [x[1] for x in c.execute("PRAGMA table_info(users)")]
        sel = [x for x in ("id", "password", "password_hash", "password_hash_enc") if x in cols]
        if "id" not in sel:
            print("[migrate-pw] users 表无 id 列, 跳过")
            return 0
        rows = c.execute(f"SELECT {','.join(sel)} FROM users").fetchall()
        # 阶段一: 全部入金库 + 回读对账 (外层连接保持只读, 避免写锁互锁)
        clear_rows = []
        for row in rows:
            d = dict(zip(sel, row))
            uid = d.get("id")
            canonical = (d.get("password") or d.get("password_hash")
                         or d.get("password_hash_enc") or "").strip()
            if not canonical or canonical.startswith("pv1:"):
                continue  # 空值或已收口
            if store_field(db_path, PASSWORD_TABLE, uid, canonical) and \
                    load_field(db_path, PASSWORD_TABLE, uid) == canonical:
                clear_rows.append(uid)
            else:
                print(f"[migrate-pw] uid={uid} 金库回读对账失败, 原列保留 (零丢失)")
        # 阶段二: 对账通过的行才清原列 (无 UNIQUE 约束, 直接置空串)
        clear_sets = ",".join(f"{x}=''" for x in
                              ("password", "password_hash", "password_hash_enc") if x in cols)
        for uid in clear_rows:
            c.execute(f"UPDATE users SET {clear_sets} WHERE id=?", (uid,))
        c.commit()
        n = len(clear_rows)
        print(f"[migrate-pw] users.password三列 → {PASSWORD_TABLE}: 迁移 {n}/{len(rows)} 条, 已清列且对账通过")
    except Exception as _e:
        print(f"[migrate-pw] err: {_e}")
    finally:
        c.close()
    return n


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
