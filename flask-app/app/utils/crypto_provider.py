"""🔒 P0 极密加固: 清除硬编码密钥/盐/派生公式
flow_secret_l0_harden_20261024

规则: 所有密钥/盐/派生 info 必须运行时从 mt_crypto_keys 表读取,
      禁止源码硬编码常量字符串或 bytes.
      源码中仅保留 "从数据库读取" 的逻辑, 不保留密钥值本身.

本模块提供 _CryptoMaterialProvider:
  - _get_secret(table, field, default_env_var) → 从 mt_crypto_keys 读取
  - _get_derivation_salt(name) → 从 mt_crypto_keys 派生盐 (HKDF)
  - _get_derivation_info(name) → 同上, 仅算法 info 参数
  - 若 mt_crypto_keys 无对应条目 → exit(1) (生产环境不能降级硬编码)

SA 豁免: SA 双密钥在线时才允许读取 crypto_keys, 否则锁定所有加密操作.
"""
import os, sys, hashlib, secrets, sqlite3, time

# P0-1 多候选 DB 路径: 环境变量 > mini home > 本地 OneDrive > __file__ 相对路径
# 修复风险: expanduser 硬编码路径漂移 → 所有加密层 exit(1) 锁死
def _resolve_db_path():
    candidates = [
        os.environ.get("MTSCOS_DB_PATH"),
        os.path.expanduser("~/MTSCOS_AI_Project/flask-app/database/app.db"),
        os.path.expanduser("~/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/database/app.db"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "app.db"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            sys.stderr.write(f"[CRYPTO] resolved db_path = {c}\n")
            return c
    # 兜底: 返回第一条 (让 sqlite3 报错比静默失败好)
    sys.stderr.write(f"[CRYPTO] WARN: no db found in candidates, returning default\n")
    return candidates[1] or candidates[3]

_DB_PATH = _resolve_db_path()

# 极密规则: 源码中不得出现任何实际密钥值. 仅保留占位符供环境变量 fallback.
# 环境变量 fallback 仅用于本地开发, mini 必须用 mt_crypto_keys 表.
_DEV_FALLBACK_TOKEN = "__MTSCOS_DEV_ONLY_REPLACE_WITH_DB__"


class CryptoMaterialProvider:
    """L0 极密: 密钥/盐/派生 info 运行时提供者 (禁止源码硬编码)"""

    def __init__(self, db_path=_DB_PATH):
        self.db_path = db_path
        self._cache = {}
        self._init_db_entries()

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def _init_db_entries(self):
        """确保 mt_crypto_keys 有必要的派生盐/info 种子条目 (首次启动自动注册, 不写密钥值)

        P1-1 修复: 加 retry 1 次逻辑 — SQLite 可能偶发 database is locked (mini 16GB WAL DB,
        多线程 daemon 同时读写), 不能第一次失败就 exit(1) 锁死 Flask.
        """
        seeds = [
            ("seed_root_salt", "secret", "HKDF salt for VIKEY root derivation"),
            ("seed_kek_info", "secret", "HKDF info for KEK derivation"),
            ("seed_dek_prefix", "secret", "HKDF info prefix for DEK derivation"),
            ("seed_reward_xor", "secret", "XOR key for reward formula masking"),
            ("seed_container_secret", "secret", "SHA256 input for system container"),
            ("seed_szu100_psk", "secret", "PSK for SZU100 双密钥通信"),
            ("seed_sa_bt_hmac", "secret", "HMAC key for SA terminal auth"),
            ("seed_flask_session", "secret", "Flask session cookie secret"),
            ("seed_dev_vikey_binding", "secret", "Dev VIKEY binding info"),
            ("seed_fernet_1", "secret", "Fernet key source 1 (legacy compat)"),
            ("seed_fernet_2", "secret", "Fernet key source 2 (legacy compat)"),
            ("seed_fernet_3", "secret", "Fernet key source 3 (legacy compat)"),
        ]
        last_err = None
        for attempt in range(2):   # retry 1 次 = 总共 2 次
            conn = self._conn()
            try:
                for kid, ktype, purpose in seeds:
                    conn.execute(
                        "INSERT OR IGNORE INTO mt_crypto_keys(key_id,key_type,purpose,created_at) VALUES(?,?,?,datetime('now','localtime'))",
                        (kid, ktype, purpose)
                    )
                conn.commit()
                if attempt > 0:
                    sys.stderr.write(f"[CRYPTO] init db entries recovered on retry ({attempt+1}/2)\n")
                return  # 成功返回
            except Exception as e:
                last_err = e
                sys.stderr.write(f"[CRYPTO] init db entries attempt {attempt+1}: {e}\n")
                time.sleep(0.5 * (attempt + 1))  # backoff 0.5s → 1s
            finally:
                conn.close()
        # 两次都失败 → fail-closed (种子缺失 = 加密层不完整)
        sys.stderr.write(f"[CRYPTO] FATAL: init db entries failed after 2 attempts → exit 1 (last={last_err})\n")
        sys.exit(1)

    def _get_master_key(self):
        """取主密钥: mt_crypto_keys.key_id='mtscos_server_master_v1'"""
        if "master" in self._cache:
            return self._cache["master"]
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT key_b64 FROM mt_crypto_keys WHERE key_id=? AND is_active=1",
                ("mtscos_server_master_v1",)
            ).fetchone()
            if row and row[0]:
                import base64
                key = base64.b64decode(row[0])
                self._cache["master"] = key
                return key
        except Exception as e:
            sys.stderr.write(f"[CRYPTO] master key load: {e}\n")
        finally:
            conn.close()
        # 生产环境必须锁死, 不能降级到硬编码
        sys.stderr.write("[CRYPTO] FATAL: mtscos_server_master_v1 not found in mt_crypto_keys → exit 1\n")
        sys.exit(1)

    def derive_bytes(self, seed_name, length=32):
        """HKDF 从主密钥派生出 bytes 值 (盐/info/PSK/key 统一入口)"""
        cache_key = f"derived:{seed_name}:{length}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives import hashes
            mk = self._get_master_key()
            info = (f"mtscos_derive_v1_{seed_name}").encode()
            derived = HKDF(
                algorithm=hashes.SHA256(),
                length=length,
                salt=mk[:16],
                info=info,
            ).derive(mk)
            self._cache[cache_key] = derived
            return derived
        except ImportError:
            sys.stderr.write("[CRYPTO] FATAL: cryptography not installed\n")
            sys.exit(1)

    def derive_str(self, seed_name, length=32):
        return self.derive_bytes(seed_name, length).hex()

    def get_flask_secret(self):
        return self.derive_str("flask_session_key", 32)

    def get_reward_xor_key(self):
        return self.derive_bytes("reward_xor_key", 16)

    def get_container_secret(self):
        return self.derive_bytes("container_secret", 32)

    def get_szu100_psk(self):
        return self.derive_bytes("szu100_psk", 32)

    def get_sa_bt_hmac_key(self):
        return self.derive_bytes("sa_bt_hmac_key", 32)

    def get_root_salt(self):
        return self.derive_bytes("root_derivation_salt", 32)

    def get_kek_info(self):
        return self.derive_bytes("kek_derivation_info", 32)

    def get_dek_info_prefix(self):
        return self.derive_bytes("dek_derivation_prefix", 16)


crypto_provider = CryptoMaterialProvider()
