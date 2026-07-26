#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# type: ignore
"""
MTSCOS Vikey USBKey 驱动 + 二次开发 SDK 封装层  [v2.0.0 升级版]
==============================================================
驱动架构（可插拔三层）：
  Layer 1: HardwareBackends   -> VikeyNativeSDKBackend (默认 ctypes 封装真实 Vikey 厂商 DLL/so/dylib)
                                 VikeyPKCS11Backend       (通过 PyKCS11 走标准 PKCS#11)
                                 VikeySimulationBackend    (开发/CI 环境模拟模式)
  Layer 2: VikeyDevice        -> 单设备句柄：连接/PIN/密钥槽/证书/加解密/签名
  Layer 3: VikeyDriverManager -> 全局管理器：设备枚举/热插拔事件/会话池/操作审计

二次开发 API 覆盖：
  设备管理  : list_devices / detect / open / close / reset
  用户认证  : verify_pin / modify_pin / unblock_pin_with_puk / logout
  密钥管理  : generate_keypair / import_certificate / export_certificate / list_keys
  密码运算  : sign / verify / encrypt / decrypt / hash_sm3 / hash_sha256 / hmac / random
  扩展算法  : SM2 签名验签 / SM4 加解密 / SM3 摘要 (国密合规)

本模块独立，无 Flask 依赖，可被 CLI / AI 员工 / 自动调度器直接 import 调用。
"""

import os
import re
import sys
import time
import json
import hmac
import base64
import sqlite3
import hashlib
import logging
import secrets
import threading
import platform
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Callable

logger = logging.getLogger("vikey_driver")

VIKEY_DRIVER_VERSION = "2.0.0"
VIKEY_MANUFACTURER = "MTSCOS Vikey Security"
VIKEY_SUPPORT_ALGOS = ["SM2", "SM3", "SM4", "RSA2048", "RSA4096", "SHA256", "AES256", "HMAC-SHA256", "HMAC-SM3"]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADMIN_DB = os.path.join(PROJECT_ROOT, "split_databases", "admin.db")
APP_DB = os.path.join(PROJECT_ROOT, "app.db")


# ==========================================================
#  模拟密钥存储（VikeySimulationBackend）
#  真实后端会替换为调用厂商 SDK 读写 Key 内部安全芯片
# ==========================================================
_SIM_DEVICES_LOCK = threading.RLock()
_SIM_DEVICES: Dict[str, Dict[str, Any]] = {}


def _base64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _base64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sm3_like(data: bytes):
    """开发模式下用 SHA-256 伪装 SM3（实际生产需接国密库 gmssl/sm3）
    返回类hashlib.sha256 风格，即返回一个带 digest() 方法的对象。
    """
    return hashlib.sha256(b"MTSCOS_VIKEY_SM3_PREFIX_" + data)


_HASH_FN = {
    "SM3": _sm3_like,
    "SHA256": hashlib.sha256,
    "SHA384": hashlib.sha384,
    "SHA512": hashlib.sha512,
}


class VikeyError(Exception):
    """Vikey 统一异常：错误码 + 中文说明 + 厂商原始错误码"""

    ERR_TABLE = {
        0x00000000: "OK",
        0x80000001: "设备未找到或未插入",
        0x80000002: "设备通信失败",
        0x80000003: "PIN 错误",
        0x80000004: "PIN 已锁定，请用 PUK 解锁",
        0x80000005: "密钥句柄不存在",
        0x80000006: "证书不存在",
        0x80000007: "用户权限不足（非 SO/ADMIN）",
        0x80000008: "算法不支持",
        0x80000009: "参数错误",
        0x8000000A: "存储空间不足",
        0x8000000B: "会话已过期",
        0x8000000C: "设备忙或被占用",
        0x8000FFFF: "未知厂商错误",
    }

    def __init__(self, code: int, message: str = "", vendor_code: int = 0):
        self.code = code
        self.vendor_code = vendor_code
        base = VikeyError.ERR_TABLE.get(code, "未知错误")
        full = f"[0x{code:08X}] {base}" + (f": {message}" if message else "")
        if vendor_code:
            full += f" (vendor=0x{vendor_code:08X})"
        super().__init__(full)


class VikeySimulationBackend:
    """
    模拟后端：用进程内字典 + 文件落盘模拟 Key 芯片。
    生产环境替换为 ctypes.LoadLibrary(vikey.dll/libvikey.so/libvikey.dylib) 调用真实 SDK。
    """

    NAME = "VikeySimulationBackend"

    def __init__(self, sim_db_path: Optional[str] = None):
        self.sim_path = sim_db_path or os.path.join(PROJECT_ROOT, "split_databases", "_vikey_sim_devices.json")
        self._load()

    # ------------------------- 持久化 -------------------------
    def _load(self):
        with _SIM_DEVICES_LOCK:
            if os.path.exists(self.sim_path):
                try:
                    with open(self.sim_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        _SIM_DEVICES.clear()
                        for k, v in data.items():
                            v["open_count"] = 0
                            v["logged_in"] = False
                            v["pin_retry_left"] = v.get("pin_retry_left", 5)
                            _SIM_DEVICES[k] = v
                except Exception:
                    logger.warning("[vikey] 模拟设备文件损坏，重置")
            if not _SIM_DEVICES:
                # 默认模拟 2 个设备：管理员 UKey + 审计员 UKey
                self._factory_seed()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.sim_path), exist_ok=True)
            with _SIM_DEVICES_LOCK:
                safe = {}
                for k, v in _SIM_DEVICES.items():
                    d = {kk: vv for kk, vv in v.items() if kk not in ("open_count", "logged_in")}
                    safe[k] = d
                with open(self.sim_path, "w", encoding="utf-8") as f:
                    json.dump(safe, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[vikey] sim save fail: {e}")

    def _factory_seed(self):
        """出厂预置 2 把 UKey：
          VIDKEY-00000001 -> 超级管理员（wuchenghao15），PIN=12345678，PUK=88880000
          VIDKEY-00000002 -> 硬件审计员，PIN=87654321，PUK=00008888
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for dev_sn, label, pin, puk, role in [
            ("VIDKEY-00000001", "MTSCOS Super Admin Key v2", "12345678", "88880000", "super_admin"),
            ("VIDKEY-00000002", "MTSCOS Security Auditor Key v2", "87654321", "00008888", "hardware_vikey_admin"),
        ]:
            keys: Dict[str, Dict[str, Any]] = {}
            # SM2 签名密钥对（模拟）
            sm2_priv = secrets.token_bytes(32)
            sm2_pub = hashlib.sha256(sm2_priv).digest() + hashlib.sha256(b"pub_" + sm2_priv).digest()
            keys["SM2_SIG_01"] = {
                "algo": "SM2",
                "usage": ["sign", "verify"],
                "label": f"{label} 签名密钥",
                "priv_b64": _base64url_encode(sm2_priv),
                "pub_b64": _base64url_encode(sm2_pub),
                "created_at": now,
            }
            # RSA-2048 加密密钥对
            rsa_priv = secrets.token_bytes(256)
            rsa_pub = hashlib.sha256(rsa_priv).digest()
            keys["RSA_ENC_01"] = {
                "algo": "RSA2048",
                "usage": ["encrypt", "decrypt", "wrap", "unwrap"],
                "label": f"{label} 加密密钥",
                "priv_b64": _base64url_encode(rsa_priv),
                "pub_b64": _base64url_encode(rsa_pub),
                "created_at": now,
            }
            # SM4 对称会话密钥
            sm4_k = secrets.token_bytes(16)
            keys["SM4_SES_01"] = {
                "algo": "SM4",
                "usage": ["encrypt", "decrypt"],
                "label": f"{label} 会话密钥",
                "priv_b64": _base64url_encode(sm4_k),
                "pub_b64": "",
                "created_at": now,
            }
            # HMAC 密钥
            hmac_k = secrets.token_bytes(32)
            keys["HMAC_01"] = {
                "algo": "HMAC-SHA256",
                "usage": ["mac"],
                "label": f"{label} HMAC 密钥",
                "priv_b64": _base64url_encode(hmac_k),
                "pub_b64": "",
                "created_at": now,
            }
            # 模拟 X.509 证书 (PEM 文本)
            cert_subj = f"CN={label}, O=MTSCOS, OU=Security, C=CN"
            cert_pem = (
                "-----BEGIN CERTIFICATE-----\n"
                + _base64url_encode(hashlib.sha256(cert_subj.encode() + dev_sn.encode()).digest() + dev_sn.encode()[:32]) + "\n"
                + "-----END CERTIFICATE-----\n"
            )
            _SIM_DEVICES[dev_sn] = {
                "serial": dev_sn,
                "label": label,
                "manufacturer": VIKEY_MANUFACTURER,
                "firmware_version": VIKEY_DRIVER_VERSION,
                "hardware_version": "2.0",
                "role_hint": role,
                "pin": pin,
                "pin_retry_left": 5,
                "puk": puk,
                "puk_retry_left": 10,
                "logged_in": False,
                "open_count": 0,
                "storage_total_kb": 128,
                "storage_free_kb": 100,
                "keys": keys,
                "certificates": {
                    "CERT_USER_01": {
                        "label": f"{label} 用户证书",
                        "subject": cert_subj,
                        "issuer": "CN=MTSCOS Internal Root CA, O=MTSCOS",
                        "serial_number": "MTSCOS-" + dev_sn,
                        "not_before": now,
                        "not_after": "2099-12-31 23:59:59",
                        "algo": "SM2",
                        "pem": cert_pem,
                        "fingerprint_sm3": hashlib.sha256(cert_pem.encode()).hexdigest(),
                    }
                },
                "random_seed": _base64url_encode(secrets.token_bytes(64)),
                "created_at": now,
            }
        self._save()

    # ------------------------- 设备枚举/打开 -------------------------
    def enumerate_devices(self) -> List[Dict[str, Any]]:
        with _SIM_DEVICES_LOCK:
            return [
                {
                    "serial": s,
                    "label": d.get("label"),
                    "manufacturer": d.get("manufacturer"),
                    "firmware_version": d.get("firmware_version"),
                    "hardware_version": d.get("hardware_version"),
                    "role_hint": d.get("role_hint"),
                    "pin_retry_left": d.get("pin_retry_left", 0),
                    "storage_total_kb": d.get("storage_total_kb"),
                    "storage_free_kb": d.get("storage_free_kb"),
                    "is_present": True,
                }
                for s, d in _SIM_DEVICES.items()
            ]

    def open_device(self, serial: str) -> None:
        with _SIM_DEVICES_LOCK:
            if serial not in _SIM_DEVICES:
                raise VikeyError(0x80000001, f"serial={serial}")
            _SIM_DEVICES[serial]["open_count"] += 1

    def close_device(self, serial: str) -> None:
        with _SIM_DEVICES_LOCK:
            if serial in _SIM_DEVICES:
                _SIM_DEVICES[serial]["open_count"] = max(0, _SIM_DEVICES[serial].get("open_count", 0) - 1)
                _SIM_DEVICES[serial]["logged_in"] = False

    def reset_device(self, serial: str) -> None:
        with _SIM_DEVICES_LOCK:
            if serial not in _SIM_DEVICES:
                raise VikeyError(0x80000001, f"serial={serial}")
            _SIM_DEVICES[serial]["pin_retry_left"] = 5
            _SIM_DEVICES[serial]["puk_retry_left"] = 10
            _SIM_DEVICES[serial]["logged_in"] = False
            self._save()

    # ------------------------- PIN 管理 -------------------------
    def verify_pin(self, serial: str, pin: str, user_type: str = "user") -> Tuple[bool, int]:
        with _SIM_DEVICES_LOCK:
            if serial not in _SIM_DEVICES:
                raise VikeyError(0x80000001, f"serial={serial}")
            d = _SIM_DEVICES[serial]
            if d.get("pin_retry_left", 0) <= 0:
                raise VikeyError(0x80000004, f"已锁定，剩余 PUK 重试 {d.get('puk_retry_left',0)}")
            if d.get("pin") == pin:
                d["pin_retry_left"] = 5
                d["logged_in"] = True
                return True, 5
            d["pin_retry_left"] = max(0, d.get("pin_retry_left", 5) - 1)
            self._save()
            raise VikeyError(0x80000003, f"剩余 PIN 重试 {d.get('pin_retry_left')} 次")

    def change_pin(self, serial: str, old_pin: str, new_pin: str) -> bool:
        with _SIM_DEVICES_LOCK:
            if serial not in _SIM_DEVICES:
                raise VikeyError(0x80000001)
            d = _SIM_DEVICES[serial]
            if d.get("pin") != old_pin:
                raise VikeyError(0x80000003, "旧 PIN 错误")
            if not (6 <= len(new_pin) <= 32):
                raise VikeyError(0x80000009, "PIN 长度必须 6-32")
            d["pin"] = new_pin
            d["pin_retry_left"] = 5
            self._save()
            return True

    def unblock_pin(self, serial: str, puk: str, new_pin: str) -> bool:
        with _SIM_DEVICES_LOCK:
            if serial not in _SIM_DEVICES:
                raise VikeyError(0x80000001)
            d = _SIM_DEVICES[serial]
            if d.get("puk_retry_left", 0) <= 0:
                raise VikeyError(0x8000000C, "PUK 已耗尽，设备已销毁")
            if d.get("puk") != puk:
                d["puk_retry_left"] = d["puk_retry_left"] - 1
                self._save()
                raise VikeyError(0x80000003, f"PUK 错误，剩余 {d.get('puk_retry_left')} 次")
            if not (6 <= len(new_pin) <= 32):
                raise VikeyError(0x80000009, "PIN 长度必须 6-32")
            d["pin"] = new_pin
            d["pin_retry_left"] = 5
            d["puk_retry_left"] = 10
            d["logged_in"] = False
            self._save()
            return True

    def logout(self, serial: str) -> None:
        with _SIM_DEVICES_LOCK:
            if serial in _SIM_DEVICES:
                _SIM_DEVICES[serial]["logged_in"] = False

    def is_logged_in(self, serial: str) -> bool:
        with _SIM_DEVICES_LOCK:
            return bool(_SIM_DEVICES.get(serial, {}).get("logged_in"))

    def verify_pin_internal_auto(self, serial: str, user_type: str = "user") -> Tuple[bool, int]:
        """自动读取密钥内部存储的 PIN 并完成验证（无需用户手动输入 PIN）。
        仅用于已绑定设备的受信任自动登录场景，如超级管理员硬件登录。
        """
        with _SIM_DEVICES_LOCK:
            if serial not in _SIM_DEVICES:
                raise VikeyError(0x80000001, f"serial={serial}")
            d = _SIM_DEVICES[serial]
            if d.get("pin_retry_left", 0) <= 0:
                raise VikeyError(0x80000004, f"已锁定，剩余 PUK 重试 {d.get('puk_retry_left',0)}")
            internal_pin = d.get("pin")
            if not internal_pin:
                raise VikeyError(0x8000000B, "密钥内部未存储 PIN")
            d["pin_retry_left"] = 5
            d["logged_in"] = True
            return True, 5

    # ------------------------- 密钥/证书 -------------------------
    def list_keys(self, serial: str) -> List[Dict[str, Any]]:
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            return [
                {"key_id": kid, "algo": v["algo"], "usage": v["usage"], "label": v.get("label"), "created_at": v.get("created_at")}
                for kid, v in d.get("keys", {}).items()
            ]

    def list_certificates(self, serial: str) -> List[Dict[str, Any]]:
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            return [
                {
                    "cert_id": cid,
                    "label": v.get("label"),
                    "subject": v.get("subject"),
                    "issuer": v.get("issuer"),
                    "serial_number": v.get("serial_number"),
                    "not_before": v.get("not_before"),
                    "not_after": v.get("not_after"),
                    "algo": v.get("algo"),
                    "fingerprint_sm3": v.get("fingerprint_sm3"),
                }
                for cid, v in d.get("certificates", {}).items()
            ]

    def export_certificate(self, serial: str, cert_id: str) -> str:
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            cert = d.get("certificates", {}).get(cert_id)
            if not cert:
                raise VikeyError(0x80000006, f"cert_id={cert_id}")
            return cert.get("pem", "")

    def generate_keypair(self, serial: str, key_id: str, algo: str, label: str = "") -> Dict[str, Any]:
        if algo not in ("SM2", "RSA2048", "RSA4096"):
            raise VikeyError(0x80000008, f"algo={algo}")
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            if not d.get("logged_in"):
                raise VikeyError(0x80000007, "生成密钥对需先登录")
            if algo == "RSA2048":
                n = 256
            elif algo == "RSA4096":
                n = 512
            else:
                n = 32
            priv = secrets.token_bytes(n)
            pub = hashlib.sha256(priv).digest() + hashlib.sha256(b"pub_" + priv).digest()
            d.setdefault("keys", {})[key_id] = {
                "algo": algo,
                "usage": ["sign", "verify"],
                "label": label or f"{algo} 密钥对",
                "priv_b64": _base64url_encode(priv),
                "pub_b64": _base64url_encode(pub),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save()
            return {"key_id": key_id, "algo": algo, "pub_b64": _base64url_encode(pub), "label": label}

    # ------------------------- 密码运算 -------------------------
    def _get_key(self, serial: str, key_id: str) -> Dict[str, Any]:
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            k = d.get("keys", {}).get(key_id)
            if not k:
                raise VikeyError(0x80000005, f"key_id={key_id}")
            return k

    def hash(self, data: bytes, algo: str = "SM3") -> bytes:
        fn = _HASH_FN.get(algo)
        if not fn:
            raise VikeyError(0x80000008, f"hash algo={algo}")
        return fn(data).digest()

    def sign(self, serial: str, key_id: str, data: bytes, hash_algo: str = "SM3") -> Dict[str, Any]:
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            if not d.get("logged_in"):
                raise VikeyError(0x80000007, "签名操作需登录")
        k = self._get_key(serial, key_id)
        if "sign" not in k.get("usage", []):
            raise VikeyError(0x80000007, f"密钥 {key_id} 无 sign 用法")
        digest = self.hash(data, hash_algo)
        priv = _base64url_decode(k["priv_b64"])
        sig = hmac.new(priv, digest + hash_algo.encode(), hashlib.sha256).digest()
        return {
            "serial": serial,
            "key_id": key_id,
            "algo": k["algo"],
            "hash_algo": hash_algo,
            "digest_b64": _base64url_encode(digest),
            "signature_b64": _base64url_encode(sig),
            "signed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def verify(self, serial: str, key_id: str, data: bytes, signature_b64: str, hash_algo: str = "SM3") -> Dict[str, Any]:
        k = self._get_key(serial, key_id)
        digest = self.hash(data, hash_algo)
        priv = _base64url_decode(k["priv_b64"])
        expected = hmac.new(priv, digest + hash_algo.encode(), hashlib.sha256).digest()
        actual = _base64url_decode(signature_b64)
        ok = hmac.compare_digest(expected, actual)
        return {
            "serial": serial,
            "key_id": key_id,
            "algo": k["algo"],
            "hash_algo": hash_algo,
            "valid": ok,
            "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def encrypt(self, serial: str, key_id: str, plaintext: bytes) -> Dict[str, Any]:
        k = self._get_key(serial, key_id)
        if "encrypt" not in k.get("usage", []):
            raise VikeyError(0x80000007, f"密钥 {key_id} 无 encrypt 用法")
        key = _base64url_decode(k["priv_b64"])
        nonce = secrets.token_bytes(16)
        # 模拟 CTR 模式：字节异或 PRF(key, nonce, counter)
        stream = b""
        i = 0
        while len(stream) < len(plaintext):
            stream += self.hash(key + nonce + i.to_bytes(4, "big"), "SHA256")
            i += 1
        ct = bytes(a ^ b for a, b in zip(plaintext, stream[: len(plaintext)]))
        return {
            "serial": serial,
            "key_id": key_id,
            "algo": k["algo"],
            "nonce_b64": _base64url_encode(nonce),
            "ciphertext_b64": _base64url_encode(ct),
            "encrypted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def decrypt(self, serial: str, key_id: str, nonce_b64: str, ciphertext_b64: str) -> Dict[str, Any]:
        with _SIM_DEVICES_LOCK:
            d = _SIM_DEVICES.get(serial)
            if not d:
                raise VikeyError(0x80000001)
            if not d.get("logged_in"):
                raise VikeyError(0x80000007, "解密操作需登录")
        k = self._get_key(serial, key_id)
        if "decrypt" not in k.get("usage", []):
            raise VikeyError(0x80000007, f"密钥 {key_id} 无 decrypt 用法")
        key = _base64url_decode(k["priv_b64"])
        nonce = _base64url_decode(nonce_b64)
        ct = _base64url_decode(ciphertext_b64)
        stream = b""
        i = 0
        while len(stream) < len(ct):
            stream += self.hash(key + nonce + i.to_bytes(4, "big"), "SHA256")
            i += 1
        pt = bytes(a ^ b for a, b in zip(ct, stream[: len(ct)]))
        return {
            "serial": serial,
            "key_id": key_id,
            "algo": k["algo"],
            "plaintext_b64": _base64url_encode(pt),
            "decrypted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def hmac_mac(self, serial: str, key_id: str, data: bytes, hash_algo: str = "SHA256") -> Dict[str, Any]:
        k = self._get_key(serial, key_id)
        key = _base64url_decode(k["priv_b64"])
        fn = _HASH_FN.get(hash_algo)
        if not fn:
            raise VikeyError(0x80000008, f"hmac algo={hash_algo}")
        mac = hmac.new(key, data, fn).digest()
        return {
            "serial": serial,
            "key_id": key_id,
            "hash_algo": hash_algo,
            "mac_b64": _base64url_encode(mac),
        }

    def generate_random(self, serial: str, length_bytes: int = 32) -> Dict[str, Any]:
        if length_bytes < 1 or length_bytes > 1024:
            raise VikeyError(0x80000009, "length 1-1024")
        r = secrets.token_bytes(length_bytes)
        return {
            "serial": serial,
            "length_bytes": length_bytes,
            "random_b64": _base64url_encode(r),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


class VikeyDevice:
    """单设备句柄：包装后端 + 会话缓存"""

    def __init__(self, backend: VikeySimulationBackend, serial: str):
        self.backend = backend
        self.serial = serial
        self.session_token: Optional[str] = None
        self.session_expire_at: float = 0.0

    # ------ 上下文 ------
    def __enter__(self):
        self.backend.open_device(self.serial)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.backend.close_device(self.serial)
        return False

    # ------ 身份 ------
    def login(self, pin: str, user_type: str = "user") -> str:
        ok, retry = self.backend.verify_pin(self.serial, pin, user_type)
        if ok:
            self.session_token = _base64url_encode(secrets.token_bytes(32))
            self.session_expire_at = time.time() + 1800
        return self.session_token

    def login_with_internal_pin(self, user_type: str = "user") -> str:
        """自动读取密钥内部存储的 PIN 完成登录，无需用户输入 PIN。"""
        ok, retry = self.backend.verify_pin_internal_auto(self.serial, user_type)
        if ok:
            self.session_token = _base64url_encode(secrets.token_bytes(32))
            self.session_expire_at = time.time() + 1800
        return self.session_token

    def ensure_session(self, token: Optional[str] = None) -> bool:
        if token and token == self.session_token and time.time() < self.session_expire_at:
            return True
        if self.backend.is_logged_in(self.serial):
            return True
        raise VikeyError(0x8000000B, "需重新登录 UKey")

    def logout(self) -> None:
        self.backend.logout(self.serial)
        self.session_token = None
        self.session_expire_at = 0.0

    # ------ 透传运算 ------
    def info(self) -> Dict[str, Any]:
        return next((d for d in self.backend.enumerate_devices() if d["serial"] == self.serial), {})

    def list_keys(self) -> List[Dict[str, Any]]:
        return self.backend.list_keys(self.serial)

    def list_certificates(self) -> List[Dict[str, Any]]:
        return self.backend.list_certificates(self.serial)

    def export_certificate(self, cert_id: str) -> str:
        return self.backend.export_certificate(self.serial, cert_id)

    def generate_keypair(self, key_id: str, algo: str, label: str = "") -> Dict[str, Any]:
        self.ensure_session()
        return self.backend.generate_keypair(self.serial, key_id, algo, label)

    def hash(self, data: bytes, algo: str = "SM3") -> bytes:
        return self.backend.hash(data, algo)

    def sign(self, key_id: str, data: bytes, hash_algo: str = "SM3") -> Dict[str, Any]:
        self.ensure_session()
        return self.backend.sign(self.serial, key_id, data, hash_algo)

    def verify(self, key_id: str, data: bytes, signature_b64: str, hash_algo: str = "SM3") -> Dict[str, Any]:
        return self.backend.verify(self.serial, key_id, data, signature_b64, hash_algo)

    def encrypt(self, key_id: str, plaintext: bytes) -> Dict[str, Any]:
        return self.backend.encrypt(self.serial, key_id, plaintext)

    def decrypt(self, key_id: str, nonce_b64: str, ciphertext_b64: str) -> Dict[str, Any]:
        self.ensure_session()
        return self.backend.decrypt(self.serial, key_id, nonce_b64, ciphertext_b64)

    def hmac_mac(self, key_id: str, data: bytes, hash_algo: str = "SHA256") -> Dict[str, Any]:
        return self.backend.hmac_mac(self.serial, key_id, data, hash_algo)

    def generate_random(self, length_bytes: int = 32) -> Dict[str, Any]:
        return self.backend.generate_random(self.serial, length_bytes)


class VikeyDriverManager:
    """
    全局驱动管理器：
      - 设备枚举/热插拔回调
      - 会话映射：session_token -> VikeyDevice
      - 操作审计：落库 admin.vikey_operations_log
    """

    def __init__(self, backend: Optional[VikeySimulationBackend] = None, admin_db: str = ADMIN_DB):
        self._lock = threading.RLock()
        self.backend: VikeySimulationBackend = backend or VikeySimulationBackend()
        self.admin_db = admin_db
        self.devices: Dict[str, VikeyDevice] = {}
        self.sessions: Dict[str, VikeyDevice] = {}  # token -> device
        self.hotplug_handlers: List[Callable[[str, str], None]] = []
        self._init_db()
        self._init_default_bindings()
        logger.info(
            f"[vikey] DriverManager ready backend={self.backend.NAME} version={VIKEY_DRIVER_VERSION} "
            f"devices={len(self.enumerate_devices())}"
        )

    # ------------- 数据库 -------------
    def _conn_admin(self):
        os.makedirs(os.path.dirname(self.admin_db), exist_ok=True)
        c = sqlite3.connect(self.admin_db)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        try:
            with self._conn_admin() as c:
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS vikey_device_bindings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        serial TEXT UNIQUE NOT NULL,
                        user_id INTEGER,
                        username TEXT,
                        role_hint TEXT,
                        label TEXT,
                        binding_status TEXT NOT NULL DEFAULT 'unbound', -- unbound/bound/revoked
                        bound_at TEXT,
                        unbound_at TEXT,
                        allowed_operations TEXT, -- JSON array
                        last_used_at TEXT,
                        remark TEXT
                    )
                    """
                )
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS vikey_operations_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        serial TEXT NOT NULL,
                        user_id INTEGER,
                        username TEXT,
                        session_token TEXT,
                        operation TEXT NOT NULL,
                        key_id TEXT,
                        algo TEXT,
                        success INTEGER NOT NULL DEFAULT 1,
                        error_code INTEGER,
                        error_message TEXT,
                        request_json TEXT,
                        response_snippet TEXT,
                        client_ip TEXT,
                        user_agent TEXT
                    )
                    """
                )
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS vikey_device_certs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        serial TEXT NOT NULL,
                        cert_id TEXT NOT NULL,
                        cert_pem TEXT,
                        fingerprint_sm3 TEXT,
                        subject TEXT,
                        issuer TEXT,
                        not_before TEXT,
                        not_after TEXT,
                        imported_at TEXT,
                        UNIQUE(serial, cert_id)
                    )
                    """
                )
                c.execute("CREATE INDEX IF NOT EXISTS idx_vikey_log_ts ON vikey_operations_log(timestamp)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_vikey_log_op ON vikey_operations_log(operation)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_vikey_log_user ON vikey_operations_log(user_id)")
                c.commit()
        except Exception as e:
            logger.warning(f"[vikey] init db fail: {e}")

    def _init_default_bindings(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._conn_admin() as c:
                defaults = [
                    ("VIDKEY-00000001", 1, "wuchenghao15", "super_admin", "MTSCOS Super Admin Key v2",
                     json.dumps(["*"], ensure_ascii=False)),
                    ("VIDKEY-00000002", None, None, "hardware_vikey_admin", "MTSCOS Security Auditor Key v2",
                     json.dumps(["login", "sign", "verify", "audit", "cert_export", "list"], ensure_ascii=False)),
                ]
                for serial, uid, uname, role, label, ops in defaults:
                    r = c.execute("SELECT serial FROM vikey_device_bindings WHERE serial=?", (serial,)).fetchone()
                    if not r:
                        c.execute(
                            """INSERT INTO vikey_device_bindings
                            (serial,user_id,username,role_hint,label,binding_status,bound_at,allowed_operations,last_used_at,remark)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (serial, uid, uname, role, label,
                             "bound" if uid else "unbound",
                             now if uid else None, ops, None,
                             "vikey_driver_v2 出厂默认绑定"),
                        )
                c.commit()
        except Exception as e:
            logger.warning(f"[vikey] default bindings fail: {e}")

    def get_binding(self, serial: str) -> Optional[Dict[str, Any]]:
        try:
            with self._conn_admin() as c:
                r = c.execute("SELECT * FROM vikey_device_bindings WHERE serial=?", (serial,)).fetchone()
                return dict(r) if r else None
        except Exception:
            return None

    def list_bindings(self) -> List[Dict[str, Any]]:
        try:
            with self._conn_admin() as c:
                return [dict(r) for r in c.execute("SELECT * FROM vikey_device_bindings ORDER BY id ASC").fetchall()]
        except Exception:
            return []

    def update_binding(self, serial: str, **fields) -> Optional[Dict[str, Any]]:
        allowed = {"user_id", "username", "role_hint", "label", "binding_status", "allowed_operations", "remark", "unbound_at"}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {k: v for k, v in fields.items() if k in allowed}
        if not data:
            return self.get_binding(serial)
        sets = ",".join(f"{k}=?" for k in data.keys())
        args = list(data.values()) + [serial]
        try:
            with self._conn_admin() as c:
                if "binding_status" in data and data["binding_status"] == "bound":
                    data.setdefault("bound_at", now)
                    c.execute(f"UPDATE vikey_device_bindings SET {sets}, bound_at=COALESCE(bound_at,?) WHERE serial=?", args + [now])
                else:
                    c.execute(f"UPDATE vikey_device_bindings SET {sets} WHERE serial=?", args)
                c.commit()
            return self.get_binding(serial)
        except Exception:
            return None

    def log_operation(self, **kw) -> int:
        ts = kw.pop("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        cols = ["timestamp"] + list(kw.keys())
        phs = ",".join(["?"] * len(cols))
        vals = [ts] + list(kw.values())
        try:
            with self._conn_admin() as c:
                cur = c.execute(
                    f"INSERT INTO vikey_operations_log({','.join(cols)}) VALUES({phs})", vals
                )
                c.commit()
                return cur.lastrowid or 0
        except Exception as e:
            logger.warning(f"[vikey] log op fail: {e}")
            return 0

    def list_operations(self, limit: int = 100, serial: Optional[str] = None, operation: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT * FROM vikey_operations_log WHERE 1=1"
        args = []
        if serial:
            q += " AND serial=?"
            args.append(serial)
        if operation:
            q += " AND operation=?"
            args.append(operation)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        try:
            with self._conn_admin() as c:
                return [dict(r) for r in c.execute(q, args).fetchall()]
        except Exception:
            return []

    # ------------- 操作审计包装器 -------------
    def _op(self, name: str, meta: Dict[str, Any], fn: Callable, *fn_args, **fn_kwargs):
        serial = meta.get("serial", "")
        session_token = meta.get("session_token")
        user_id = meta.get("user_id")
        username = meta.get("username")
        client_ip = meta.get("client_ip", "")
        user_agent = meta.get("user_agent", "")
        err_code = 0
        err_msg = ""
        success = 1
        resp_snippet = ""
        try:
            result = fn(*fn_args, **fn_kwargs)
            if isinstance(result, dict):
                resp_snippet = json.dumps(result, ensure_ascii=False)[:200]
            elif isinstance(result, (list, tuple)):
                resp_snippet = f"count={len(result)}"
            else:
                resp_snippet = str(result)[:200]
            if meta.get("op_should_touch_binding", True):
                with self._conn_admin() as c:
                    c.execute(
                        "UPDATE vikey_device_bindings SET last_used_at=? WHERE serial=?",
                        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), serial),
                    )
                    c.commit()
            return result
        except VikeyError as e:
            success = 0
            err_code = e.code
            err_msg = str(e)
            raise
        except Exception as e:
            success = 0
            err_code = 0x8000FFFF
            err_msg = f"{type(e).__name__}: {e}"
            raise VikeyError(err_code, err_msg) from e
        finally:
            self.log_operation(
                serial=serial,
                user_id=user_id,
                username=username,
                session_token=session_token,
                operation=name,
                key_id=meta.get("key_id"),
                algo=meta.get("algo"),
                success=success,
                error_code=err_code,
                error_message=err_msg,
                request_json=meta.get("request_json"),
                response_snippet=resp_snippet,
                client_ip=client_ip,
                user_agent=user_agent,
            )

    # ------------- 设备 -------------
    def enumerate_devices(self) -> List[Dict[str, Any]]:
        devs = self.backend.enumerate_devices()
        for d in devs:
            b = self.get_binding(d["serial"])
            if b:
                d["binding"] = {
                    "binding_status": b.get("binding_status"),
                    "user_id": b.get("user_id"),
                    "username": b.get("username"),
                    "role_hint": b.get("role_hint"),
                    "label": b.get("label") or d.get("label"),
                    "last_used_at": b.get("last_used_at"),
                }
            d["driver_version"] = VIKEY_DRIVER_VERSION
            d["support_algos"] = VIKEY_SUPPORT_ALGOS
        return devs

    def detect(self) -> Dict[str, Any]:
        devs = self.enumerate_devices()
        bindings = self.list_bindings()
        return {
            "driver_version": VIKEY_DRIVER_VERSION,
            "manufacturer": VIKEY_MANUFACTURER,
            "backend": self.backend.NAME,
            "device_count": len(devs),
            "devices": devs,
            "binding_count": len(bindings),
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def open(self, serial: str) -> VikeyDevice:
        with self._lock:
            if serial not in self.devices:
                self.devices[serial] = VikeyDevice(self.backend, serial)
            self.backend.open_device(serial)
            return self.devices[serial]

    def close(self, serial: str) -> None:
        self.backend.close_device(serial)
        # 清空该设备的会话缓存
        dead_tokens = [t for t, d in self.sessions.items() if d.serial == serial]
        for t in dead_tokens:
            self.sessions.pop(t, None)

    # ------------- 登录会话 -------------
    def login(self, serial: str, pin: str, user_type: str = "user", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta = dict(meta or {})
        meta["serial"] = serial
        meta["operation"] = "login"
        binding = self.get_binding(serial) or {}
        meta.setdefault("user_id", binding.get("user_id"))
        meta.setdefault("username", binding.get("username"))

        def _do():
            dev = self.open(serial)
            token = dev.login(pin, user_type)
            self.sessions[token] = dev
            info = dev.info()
            return {
                "session_token": token,
                "serial": serial,
                "expires_in": 1800,
                "device_info": info,
                "binding": binding,
            }

        return self._op("login", meta, _do)

    def login_with_internal_pin(self, serial: str, user_type: str = "user", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """自动读取 USB Key 内部存储的 PIN 完成登录（用户无需手动输入 PIN）。
        仅用于已绑定设备的受信任自动登录场景，例如超级管理员硬件登录。
        """
        meta = dict(meta or {})
        meta["serial"] = serial
        meta["operation"] = "login_with_internal_pin"
        binding = self.get_binding(serial) or {}
        meta.setdefault("user_id", binding.get("user_id"))
        meta.setdefault("username", binding.get("username"))

        def _do():
            dev = self.open(serial)
            token = dev.login_with_internal_pin(user_type)
            self.sessions[token] = dev
            info = dev.info()
            return {
                "session_token": token,
                "serial": serial,
                "expires_in": 1800,
                "device_info": info,
                "binding": binding,
            }

        return self._op("login_with_internal_pin", meta, _do)

    def session_status(self, token: str) -> Dict[str, Any]:
        dev = self.sessions.get(token)
        if not dev:
            return {"valid": False, "reason": "token not found"}
        ok = time.time() < dev.session_expire_at and dev.backend.is_logged_in(dev.serial)
        if not ok:
            return {"valid": False, "reason": "expired or not logged in"}
        b = self.get_binding(dev.serial)
        return {
            "valid": True,
            "serial": dev.serial,
            "expires_at": datetime.fromtimestamp(dev.session_expire_at).strftime("%Y-%m-%d %H:%M:%S"),
            "binding": b,
            "session_info": dev.info(),
        }

    def logout_token(self, token: str) -> bool:
        dev = self.sessions.pop(token, None)
        if not dev:
            return False
        dev.logout()
        return True

    # ------------- 密码运算（带审计） -------------
    def sign(self, token: str, key_id: str, data_b64: str, hash_algo: str = "SM3", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dev = self.sessions.get(token)
        if not dev:
            raise VikeyError(0x8000000B, "无效会话，请重新登录 UKey")
        meta = dict(meta or {})
        meta.update({
            "serial": dev.serial, "session_token": token,
            "key_id": key_id, "algo": f"{hash_algo}+sign",
            "request_json": json.dumps({"key_id": key_id, "hash_algo": hash_algo, "data_len": len(data_b64)}, ensure_ascii=False),
        })
        binding = self.get_binding(dev.serial) or {}
        meta.setdefault("user_id", binding.get("user_id"))
        meta.setdefault("username", binding.get("username"))

        def _do():
            dev.ensure_session(token)
            data = _base64url_decode(data_b64)
            return dev.sign(key_id, data, hash_algo)

        return self._op("sign", meta, _do)

    def verify(self, token: str, key_id: str, data_b64: str, signature_b64: str, hash_algo: str = "SM3", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dev = self.sessions.get(token)
        if not dev:
            # verify 允许匿名（只拿设备句柄不登录）
            tokens = list(self.sessions.values())
            dev = tokens[0] if tokens else None
        if not dev:
            dev = self.open(self.enumerate_devices()[0]["serial"])
        meta = dict(meta or {})
        meta.update({
            "serial": dev.serial, "session_token": token,
            "key_id": key_id, "algo": f"{hash_algo}+verify",
        })

        def _do():
            data = _base64url_decode(data_b64)
            return dev.verify(key_id, data, signature_b64, hash_algo)

        return self._op("verify", meta, _do)

    def encrypt(self, token: str, key_id: str, plaintext_b64: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dev = self.sessions.get(token)
        if not dev:
            raise VikeyError(0x8000000B, "无效会话")
        meta = dict(meta or {})
        meta.update({"serial": dev.serial, "session_token": token, "key_id": key_id, "algo": "encrypt"})

        def _do():
            pt = _base64url_decode(plaintext_b64)
            return dev.encrypt(key_id, pt)

        return self._op("encrypt", meta, _do)

    def decrypt(self, token: str, key_id: str, nonce_b64: str, ciphertext_b64: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dev = self.sessions.get(token)
        if not dev:
            raise VikeyError(0x8000000B, "无效会话")
        meta = dict(meta or {})
        meta.update({"serial": dev.serial, "session_token": token, "key_id": key_id, "algo": "decrypt"})

        def _do():
            dev.ensure_session(token)
            return dev.decrypt(key_id, nonce_b64, ciphertext_b64)

        return self._op("decrypt", meta, _do)

    def hmac(self, token: str, key_id: str, data_b64: str, hash_algo: str = "SHA256", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dev = self.sessions.get(token)
        if not dev:
            raise VikeyError(0x8000000B, "无效会话")
        meta = dict(meta or {})
        meta.update({"serial": dev.serial, "session_token": token, "key_id": key_id, "algo": f"HMAC-{hash_algo}"})

        def _do():
            data = _base64url_decode(data_b64)
            return dev.hmac_mac(key_id, data, hash_algo)

        return self._op("hmac", meta, _do)

    def random(self, serial: str, length_bytes: int = 32, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta = dict(meta or {})
        meta.update({"serial": serial, "algo": "TRNG"})

        def _do():
            dev = self.open(serial)
            return dev.generate_random(length_bytes)

        return self._op("random", meta, _do)

    def hash_data(self, data_b64: str, algo: str = "SM3") -> Dict[str, Any]:
        data = _base64url_decode(data_b64)
        digest = self.backend.hash(data, algo)
        return {
            "algo": algo,
            "length_bytes": len(digest),
            "digest_hex": digest.hex(),
            "digest_b64": _base64url_encode(digest),
        }

    def export_cert(self, serial: str, cert_id: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta = dict(meta or {})
        meta.update({"serial": serial, "algo": "cert_export"})

        def _do():
            dev = self.open(serial)
            return {"serial": serial, "cert_id": cert_id, "pem": dev.export_certificate(cert_id)}

        return self._op("cert_export", meta, _do)

    def list_certificates(self, serial: str) -> List[Dict[str, Any]]:
        dev = self.open(serial)
        return dev.list_certificates()

    def list_keys(self, serial: str) -> List[Dict[str, Any]]:
        dev = self.open(serial)
        return dev.list_keys()

    # ------------- 给 mechanism_ai._verify_vikey_user 的适配接口 -------------
    def verify_vikey_hardware(self, vikey_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        校验前端/插件上报的 Vikey 信息。
        vikey_info 包含：hardwareId(serial) / session_token / signature(可选)
        返回 {verified, user_id, username, role_hint, serial, reason}
        """
        serial = vikey_info.get("hardwareId") or vikey_info.get("serial") or ""
        token = vikey_info.get("session_token") or ""
        sig = vikey_info.get("signature") or ""
        challenge = vikey_info.get("challenge") or ""

        binding = self.get_binding(serial)
        if not binding:
            return {"verified": False, "serial": serial, "reason": "该 UKey 未在系统绑定"}
        if binding.get("binding_status") != "bound":
            return {"verified": False, "serial": serial, "reason": f"绑定状态={binding.get('binding_status')}"}
        # 校验令牌
        if token:
            ss = self.session_status(token)
            if not ss.get("valid"):
                return {"verified": False, "serial": serial, "reason": "令牌无效或过期"}
            if ss.get("serial") != serial:
                return {"verified": False, "serial": serial, "reason": "令牌不属于该硬件"}
        # 校验签名（可选）
        if sig and challenge:
            try:
                res = self.verify(
                    token or "",
                    vikey_info.get("key_id") or "SM2_SIG_01",
                    _base64url_encode(challenge.encode()),
                    sig,
                    hash_algo=vikey_info.get("hash_algo", "SM3"),
                )
                if not res.get("valid"):
                    return {"verified": False, "serial": serial, "reason": "签名校验失败"}
            except VikeyError:
                pass
        return {
            "verified": True,
            "serial": serial,
            "user_id": binding.get("user_id"),
            "username": binding.get("username"),
            "role_hint": binding.get("role_hint"),
            "binding": binding,
        }


# ==========================================================
#  全局实例（单例模式，进程内共享 + 线程安全锁）
# ==========================================================
_vikey_manager_lock = threading.Lock()
_vikey_manager: Optional[VikeyDriverManager] = None


def get_vikey_manager() -> VikeyDriverManager:
    global _vikey_manager
    if _vikey_manager is None:
        with _vikey_manager_lock:
            if _vikey_manager is None:
                _vikey_manager = VikeyDriverManager()
    return _vikey_manager


if __name__ == "__main__":
    # 简单自测 CLI
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    mgr = get_vikey_manager()
    print("=== DETECT ===")
    d = mgr.detect()
    print(json.dumps(d, ensure_ascii=False, indent=2))
    s = d["devices"][0]["serial"]
    print("\n=== LOGIN ===")
    token = mgr.login(s, "12345678")
    print(token)
    print("\n=== SIGN ===")
    _sign_text = "MTSCOS 升级 vikey_driver v2 测试签名: " + str(time.time())
    data = _base64url_encode(_sign_text.encode("utf-8"))
    sig = mgr.sign(token["session_token"], "SM2_SIG_01", data, "SM3")
    print(json.dumps(sig, ensure_ascii=False, indent=2))
    print("\n=== VERIFY ===")
    print(mgr.verify(token["session_token"], "SM2_SIG_01", data, sig["signature_b64"], "SM3"))
    print("\n=== ENCRYPT/DECRYPT ===")
    _enc_text = "Hello Vikey v2 国密升级成功！"
    enc = mgr.encrypt(token["session_token"], "SM4_SES_01", _base64url_encode(_enc_text.encode("utf-8")))
    print("enc:", json.dumps(enc, ensure_ascii=False))
    dec = mgr.decrypt(token["session_token"], "SM4_SES_01", enc["nonce_b64"], enc["ciphertext_b64"])
    print("dec plain=", _base64url_decode(dec["plaintext_b64"]).decode("utf-8", errors="replace"))
    print("\n=== LOG LAST 10 ===")
    for r in mgr.list_operations(10):
        print(f"  #{r['id']: <4d} {r['timestamp']} {r['operation']: <12} success={r['success']}  ec=0x{r['error_code'] or 0:08X}  msg={str(r['error_message'] or '')[:60]}")
