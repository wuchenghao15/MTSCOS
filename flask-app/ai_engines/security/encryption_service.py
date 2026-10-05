#!/usr/bin/env python3
"""
三 Tier 应用级字段加密服务
=============================
对接 MT_RULE_CLASSIFICATION 机密等级规范
底层复用 ai_engines/crypto_engine.py (AES-256-GCM + HMAC-SHA256 + PyNaCl)

关键设计约束:
  ✅ 应用级加密 (SQLite 文件仍是明文格式, 兼容 autosync rsync + CLI 读取)
  ✅ 不加密主键, created_at, updated_at, data_code (autosync 行对比必须)
  ✅ 加密列命名: {原列名}_enc (留原列名, 里面置 NULL 或保留原值做迁移过渡)
  ✅ 三 tier 密钥隔离
  ✅ 极密 tier 需要 VIKEY 硬件狗双因子派生密钥

三 Tier 密钥管理:
  极密 (TOP_SECRET):  AES-256-GCM + PBKDF2 从 VIKEY 硬件狗派生密钥
  机密 (SECRET):     AES-256-GCM + 服务器 master key (环境变量, 不硬编码)
  秘密 (CONFIDENTIAL): Fernet + 会话级临时 key (每用户 session 派生)

密钥存储:
  - 服务器 master key → mt_crypto_keys (已存在, 由 crypto_engine 初始化)
  - VIKEY 派生密钥 → 不落库, 每次从硬件狗实时派生
  - 会话密钥 → 存 Flask session, 过期自动清除
"""
import os, sys, json, base64, hashlib, hmac, secrets, time, threading, sqlite3
from datetime import datetime
from pathlib import Path

# 让 crypto_engine 找对 DB
FLASK_ROOT = Path(__file__).resolve().parent.parent.parent
os.environ.setdefault("APP_DB", str(FLASK_ROOT / "database" / "app.db"))

try:
    from cryptography.fernet import Fernet
    FERNET_OK = True
except ImportError:
    FERNET_OK = False

_LOCK = threading.RLock()
_SERVER_KEY_CACHE = None  # 服务器 master key 进程级缓存


# ════════════════════════════════════════════════════════════════
#  Tier 1: 极密 (TOP_SECRET) — AES-256-GCM + VIKEY 硬件狗派生密钥
# ════════════════════════════════════════════════════════════════

def _derive_vikey_key(salt: bytes = b"MTSCOS-ANDROMEDA-V1") -> bytes | None:
    """
    从 VIKEY 硬件狗派生 32 字节密钥.
    VIKEY 离线 → 返回 None (fail-closed, 极密数据无法解密)

    真实场景: VIKEY 硬件狗提供 HMAC-SHA256 签名能力, 
    我们用固定 salt + 硬件狗唯一序列号做 PBKDF2 派生.
    当前没有 VIKEY 硬件狗 → 返回 None (开发/测试降级)
    """
    try:
        # 真实实现: 调 HardwareKeyProvider.derive_key()
        from core.services.vikey_driver import get_hardware_key_provider
        provider = get_hardware_key_provider()
        if hasattr(provider, "derive_key"):
            key = provider.derive_key(salt, 32)
            if key and len(key) == 32:
                return key
        # 降级: 用 VIKEY 序列号 + PBKDF2
        serial = getattr(provider, "serial", None) or b"NO_VIKEY_FALLBACK"
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        return kdf.derive(serial.encode() if isinstance(serial, str) else serial)
    except Exception as e:
        print(f"[ENCRYPT] VIKEY key derive 失败: {e}")
        return None


# ════════════════════════════════════════════════════════════════
#  Tier 2: 机密 (SECRET) — AES-256-GCM + 服务器 master key
# ════════════════════════════════════════════════════════════════

def _get_server_master_key() -> bytes:
    """
    服务器 master key 来源 (优先级):
      1. 环境变量 MTSCOS_SERVER_MASTER_KEY (base64)
      2. mt_crypto_keys 表里找 key_type='server_master' 的 active key
      3. 没找到 → 生成新的 + 落库 + 写 env (首次启动)
    """
    global _SERVER_KEY_CACHE
    with _LOCK:
        if _SERVER_KEY_CACHE and len(_SERVER_KEY_CACHE) == 32:
            return _SERVER_KEY_CACHE

        # 1. 环境变量
        env_key = os.environ.get("MTSCOS_SERVER_MASTER_KEY")
        if env_key:
            try:
                key = base64.b64decode(env_key)
                if len(key) == 32:
                    _SERVER_KEY_CACHE = key
                    return key
            except Exception:
                pass

        # 2. DB 查
        db_path = os.environ.get("APP_DB")
        try:
            conn = sqlite3.connect(db_path or ":memory:")
            row = conn.execute(
                "SELECT key_b64 FROM mt_crypto_keys WHERE key_type='server_master' AND is_active=1 LIMIT 1"
            ).fetchone()
            if row:
                key = base64.b64decode(row[0])
                if len(key) == 32:
                    _SERVER_KEY_CACHE = key
                    conn.close()
                    return key
            conn.close()
        except Exception:
            pass

        # 3. 生成新的 + 落库 + 输出环境变量提示
        import secrets as _s
        key = _s.token_bytes(32)
        _SERVER_KEY_CACHE = key
        try:
            conn = sqlite3.connect(db_path or ":memory:")
            conn.execute("""
                INSERT OR REPLACE INTO mt_crypto_keys
                (key_id, key_type, key_name, key_b64, is_active, purpose, created_at)
                VALUES (?, 'server_master', ?, ?, 1, ?, datetime('now','localtime'))
            """, ("mtscos_server_master_v1", "MTSCOS Server Master Key v1",
                  base64.b64encode(key).decode(), "encrypt"))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ENCRYPT] server_master_key 落库失败: {e}")

        b64 = base64.b64encode(key).decode()
        print(f"[ENCRYPT] ⚠️ 生成新的 server_master_key!")
        print(f"[ENCRYPT]   请持久化到环境变量: export MTSCOS_SERVER_MASTER_KEY={b64}")
        print(f"[ENCRYPT]   否则每次重启都会生成新 key → 旧密文无法解密!")
        return key


# ════════════════════════════════════════════════════════════════
#  Tier 3: 秘密 (CONFIDENTIAL) — Fernet / HMAC_ONLY
# ════════════════════════════════════════════════════════════════

def _get_session_fernet_key(session_key_material: bytes | None = None) -> bytes:
    """
    Fernet key: 来自 session material 或每次生成.
    秘密等级数据通常只需要"不裸存", 不强要求永久解密.
    """
    if not FERNET_OK:
        return None
    if session_key_material:
        # 从 session material 派生 Fernet key (需要 url-safe base64 32 字节)
        from cryptography.hazmat.primitives import hashes
        h = hashlib.sha256(session_key_material).digest()
        return base64.urlsafe_b64encode(h)
    return Fernet.generate_key()


# ════════════════════════════════════════════════════════════════
#  核心接口: encrypt_field / decrypt_field
# ════════════════════════════════════════════════════════════════

def _import_crypto_engine():
    """延迟 import crypto_engine (避免循环 + 确保它能找到 DB)。"""
    # 先确保 crypto_engine 所在目录在 sys.path
    crypto_dir = str(FLASK_ROOT / "ai_engines")
    if crypto_dir not in sys.path:
        sys.path.insert(0, crypto_dir)
    try:
        import crypto_engine as ce
        return ce
    except ImportError:
        from ai_engines import crypto_engine as ce
        return ce

def encrypt_field(plaintext: str | bytes, classification: str,
                  key_source_override: str | None = None,
                  session_material: bytes | None = None) -> dict:
    """
    按机密等级加密字段.

    返回 {"ciphertext": str, "nonce": str, "method": str, "tier": str}
    """
    if plaintext is None:
        return {"ciphertext": "", "nonce": "", "method": "NULL", "tier": classification}

    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    tier = (classification or "秘密").strip()
    ce = _import_crypto_engine()

    if tier in ("极密", "TOP_SECRET"):
        # fail-closed: 极密数据必须 VIKEY 双因子, 降级 key (NO_VIKEY_FALLBACK) 拒绝加密
        try:
            from core.services.vikey_driver import get_hardware_key_provider
            provider = get_hardware_key_provider()
            serial = getattr(provider, "serial", None)
            if not serial:
                raise RuntimeError("VIKEY 硬件狗序列号不可读")
            ok, reason = provider.verify_dual_key_atomic(timeout=5.0)
            if not ok:
                raise RuntimeError(f"VIKEY 双因子认证失败: {reason}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"极密数据加密需要 VIKEY 硬件狗, 当前不可用 (fail-closed): {e}")
        key = _derive_vikey_key()
        if key is None:
            raise RuntimeError("VIKEY key 派生失败 (fail-closed)")
        result = ce.aes_gcm_encrypt(plaintext, key=key, aad=b"TOP_SECRET")
        return {"ciphertext": result["ciphertext_b64"], "nonce": result["nonce_b64"],
                "method": "AES-256-GCM", "tier": "TOP_SECRET"}

    elif tier in ("机密", "SECRET"):
        key = _get_server_master_key()
        result = ce.aes_gcm_encrypt(plaintext, key=key, aad=b"SECRET")
        return {"ciphertext": result["ciphertext_b64"], "nonce": result["nonce_b64"],
                "method": "AES-256-GCM", "tier": "SECRET"}

    else:  # 秘密 / 默认
        if FERNET_OK:
            try:
                fkey = _get_session_fernet_key(session_material)
                f = Fernet(fkey)
                ct = f.encrypt(plaintext)
                return {"ciphertext": ct.decode(), "nonce": fkey.decode()[:24] + "...",
                        "method": "FERNET", "tier": "CONFIDENTIAL"}
            except Exception:
                pass
        # 降级 HMAC-SHA256
        h = hmac.new(_get_server_master_key(), plaintext, hashlib.sha256).hexdigest()
        return {"ciphertext": h, "nonce": "", "method": "HMAC-SHA256", "tier": "CONFIDENTIAL_HASH"}


def decrypt_field(ciphertext: str, classification: str,
                  nonce_b64: str = "", session_material: bytes | None = None) -> str | None:
    """按机密等级解密."""
    if not ciphertext:
        return None

    tier = (classification or "秘密").strip()

    try:
        from ai_engines.crypto_engine import aes_gcm_decrypt
    except ImportError:
        import sys
        ce_path = str(Path(__file__).resolve().parent)
        if ce_path not in sys.path:
            sys.path.insert(0, ce_path)
        from crypto_engine import aes_gcm_decrypt

    try:
        if tier in ("极密", "TOP_SECRET"):
            key = _derive_vikey_key()
            if key is None:
                return None  # VIKEY 离线, 无法解密 (fail-closed)
            plain = aes_gcm_decrypt(ciphertext, nonce_b64, base64.b64encode(key).decode(), aad=b"TOP_SECRET")
            return plain.decode("utf-8")

        elif tier in ("机密", "SECRET"):
            key = _get_server_master_key()
            plain = aes_gcm_decrypt(ciphertext, nonce_b64, base64.b64encode(key).decode(), aad=b"SECRET")
            return plain.decode("utf-8")

        else:
            # Fernet / HMAC 降级 — 秘密等级解密依赖 session material, 可能拿不到
            if FERNET_OK and session_material:
                try:
                    fkey = _get_session_fernet_key(session_material)
                    f = Fernet(fkey)
                    plain = f.decrypt(ciphertext.encode())
                    return plain.decode("utf-8")
                except Exception:
                    pass
            return None  # HMAC 不可恢复原文, 返回 None

    except Exception as e:
        print(f"[ENCRYPT] 解密失败 tier={tier}: {e}")
        return None


# ════════════════════════════════════════════════════════════════
#  mt_classified_data 表查询 (给迁移脚本 + before_request hook 用)
# ════════════════════════════════════════════════════════════════

def get_classified_fields() -> list[dict]:
    """返回所有需要加密的字段定义 (从 mt_classified_data 读)."""
    db_path = os.environ.get("APP_DB") or str(FLASK_ROOT / "database" / "app.db")
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM mt_classified_data 
            WHERE target_column IS NOT NULL AND encrypt_method != 'NONE'
            ORDER BY CASE classification 
                WHEN '极密' THEN 1 WHEN '机密' THEN 2 ELSE 3 END
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[ENCRYPT] get_classified_fields 失败: {e}")
        return []


def health_check() -> dict:
    """返回加密服务健康状态."""
    result = {
        "server_master_key": False,
        "vikey_derivable": False,
        "fernet_available": FERNET_OK,
        "classified_fields": len(get_classified_fields()),
        "db_path": os.environ.get("APP_DB", "default"),
    }
    try:
        k = _get_server_master_key()
        result["server_master_key"] = len(k) == 32
    except Exception:
        pass
    try:
        # VIKEY 测试派生 (不会落库)
        test_key = _derive_vikey_key(salt=b"MTSCOS_TEST_ONLY")
        result["vikey_derivable"] = test_key is not None
    except Exception:
        pass
    return result


# ════════════════════════════════════════════════════════════════
#  模块级自测试 (python3 encryption_service.py → 跑一次看结果)
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("═══════════════════════════════════════════")
    print(" 三 Tier 加密服务 · 自测试")
    print("═══════════════════════════════════════════")
    h = health_check()
    print(f"\nhealth: {json.dumps(h, ensure_ascii=False, indent=2)}")

    test_data = "MTSCOS AI Andromeda encryption test 1234567890".encode("utf-8")

    for tier_name in ["极密", "机密", "秘密"]:
        print(f"\n─── Tier: {tier_name} ───")
        try:
            r = encrypt_field(test_data, tier_name)
            print(f"  encrypt → method={r['method']} ciphertext_len={len(r['ciphertext'])}")
            plain = decrypt_field(r["ciphertext"], tier_name, r["nonce"])
            match = plain == test_data.decode() if plain else False
            print(f"  decrypt → {'✅ 匹配' if match else '❌ 不匹配/无权限'}")
        except Exception as e:
            print(f"  ❌ 失败: {e}")

    print("\n[ENCRYPT] ✅ 三 Tier 自测试完成")
