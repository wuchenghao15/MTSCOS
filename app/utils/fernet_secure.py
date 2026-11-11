#!/usr/bin/env python3
"""
MTSCOS Fernet 敏感字段加密模块

用法:
    from app.utils.fernet_secure import fencrypt, fdecrypt, is_encrypted, get_fernet

设计决策:
    - Fernet key 存 ~/.mtscos_fernet_key, chmod 600
    - 首次调用自动生成, 需迁移的明文数据先用 fencrypt() 加
    - 加密后值以 "ft:" 前缀标识, 方便检测
    - 无 key 时 fallback 到原值 (兼容迁移中的混合态)
"""
import os
import base64
from cryptography.fernet import Fernet, InvalidToken

_FERNET_KEY_PATH = os.path.expanduser("~/.mtscos_fernet_key")
_PREFIX = b"ft:"

_f = None


def _load_or_create_key() -> bytes:
    """加载或生成 Fernet key"""
    global _f
    if _f is not None:
        return _f

    if os.path.exists(_FERNET_KEY_PATH):
        with open(_FERNET_KEY_PATH, "rb") as f:
            key = f.read().strip()
    else:
        # 首次生成
        key = Fernet.generate_key()
        tmp_path = _FERNET_KEY_PATH + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, key)
        os.close(fd)
        os.replace(tmp_path, _FERNET_KEY_PATH)
        # 确保权限
        os.chmod(_FERNET_KEY_PATH, 0o600)

    _f = Fernet(key)
    return key


def get_fernet() -> Fernet:
    """获取 Fernet 实例"""
    _load_or_create_key()
    return _f


def fencrypt(plaintext: str) -> str:
    """加密字符串, 返回 'ft:...' 前缀的密文"""
    if plaintext is None:
        return plaintext
    if isinstance(plaintext, bytes):
        plaintext = plaintext.decode("utf-8", errors="replace")
    # 已是密文直接返回
    if plaintext.startswith("ft:"):
        return plaintext
    token = get_fernet().encrypt(plaintext.encode("utf-8"))
    return (_PREFIX + token).decode("ascii")


def fdecrypt(ciphertext: str) -> str:
    """解密 'ft:...' 密文, 非密文原样返回"""
    if ciphertext is None:
        return ciphertext
    if isinstance(ciphertext, bytes):
        ciphertext = ciphertext.decode("utf-8", errors="replace")
    if not ciphertext.startswith("ft:"):
        # 不是密文, 原样返回 (兼容明文)
        return ciphertext
    try:
        token = ciphertext[len("ft:"):].encode("ascii")
        return get_fernet().decrypt(token, ttl=None).decode("utf-8")
    except InvalidToken:
        # key 不匹配或数据损坏, 返回原值 + 记录
        return f"[DECRYPT_FAILED:{ciphertext[:20]}...]"


def is_encrypted(val: str) -> bool:
    """检测是否已加密"""
    if val is None:
        return False
    return isinstance(val, str) and val.startswith("ft:")
