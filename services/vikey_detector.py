#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VIKEY 硬件加密狗检测器
======================
桌面端：USB VIKEY 序列号 + 芯片ID 检测
移动端：生物指纹替代方案

支持：
  1. USB VIKEY 实时检测（序列号、芯片ID、PID/VID）
  2. VIKEY 白名单校验（只允许已注册的VIKEY）
  3. 移动端指纹生物识别（iOS TouchID/FaceID, Android Fingerprint）
  4. VIKEY 在线状态心跳（供 DualKeyAuthManager 调用）
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 常量 ──
# v24.2 fix: 从真实硬件 ioreg 抓值 (2026-09-30 LIVE 验证)
#   ioreg: idVendor=6535 (0x1987) idProduct=817 (0x0331)
#   USB Product Name=ViKeyPRO  Manufacturer=LiViKey
VIKEY_VID_PID = {"vid": "0x1987", "pid": "0x0331", "manufacturer": "LiViKey", "product": "ViKeyPRO"}
VIKEY_WHITELIST_PATH = Path(__file__).resolve().parent / "vikey_whitelist.json"
HEARTBEAT_INTERVAL_DEFAULT = 30  # 秒
# SZU100 深圳大学专用 U 盘硬件密钥（与 VIKEY 双因子认证用）
# 通过 USB 设备名/序列号包含关键字识别（不依赖 VID/PID，便于兼容不同批次）
SZU100_NAME_KEYWORDS = ("szu100", "szu-100", "szu_100", "szu 100", "shenzhen university 100", "szu专用")
SZU100_SERIAL_PREFIXES = ("SZU100", "SZU-100", "SZU_100")


@dataclass
class VikeyInfo:
    """VIKEY 检测结果"""
    found: bool = False
    serial: str = ""           # USB 序列号
    chip_id: str = ""          # 芯片唯一ID
    vid: str = ""
    pid: str = ""
    device_path: str = ""
    platform: str = ""         # desktop / mobile
    auth_method: str = ""      # usb / fingerprint
    fingerprint_hash: str = "" # 移动端指纹哈希
    detected_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found, "serial": self.serial, "chip_id": self.chip_id,
            "vid": self.vid, "pid": self.pid, "device_path": self.device_path,
            "platform": self.platform, "auth_method": self.auth_method,
            "fingerprint_hash": self.fingerprint_hash,
            "detected_at": self.detected_at,
        }

    @property
    def identity(self) -> str:
        """唯一标识 = serial + chip_id 的哈希"""
        raw = f"{self.serial}:{self.chip_id}:{self.fingerprint_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


class VikeyWhitelist:
    """VIKEY 白名单管理"""

    def __init__(self, path: Path = VIKEY_WHITELIST_PATH):
        self.path = path
        self._entries: Dict[str, Dict] = {}  # identity -> {serial, chip_id, owner, registered_at}
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                if isinstance(data, dict):
                    self._entries = data
            except Exception:
                self._entries = {}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self._entries, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    def register(self, info: VikeyInfo, owner: str = "wuchenghao15") -> bool:
        ident = info.identity
        with self._lock:
            self._entries[ident] = {
                "serial": info.serial,
                "chip_id": info.chip_id,
                "fingerprint_hash": info.fingerprint_hash,
                "owner": owner,
                "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save()
        return True

    def is_authorized(self, info: VikeyInfo) -> bool:
        ident = info.identity
        with self._lock:
            return ident in self._entries

    def list_all(self) -> List[Dict]:
        with self._lock:
            return list(self._entries.values())

    def remove(self, identity: str) -> bool:
        with self._lock:
            if identity in self._entries:
                del self._entries[identity]
                self._save()
                return True
            return False


class VikeyDetector:
    """
    VIKEY 硬件检测器
    ──────────────────
    桌面端：检测 USB VIKEY 加密狗
    移动端：生物指纹替代
    """

    def __init__(self):
        # 安全获取 OS 名称，防止 platform 模块被某处 import 污染导致 AttributeError
        try:
            import importlib as _il
            _plat = _il.import_module('platform')
            self.system = _plat.system().lower() if hasattr(_plat, 'system') else 'unknown'
        except Exception:
            import sys as _sys
            sp = _sys.platform.lower()
            self.system = 'darwin' if sp == 'darwin' else ('windows' if sp.startswith('win') else ('linux' if sp.startswith('linux') else 'unknown'))
        self.is_mobile = self._detect_mobile()
        self.whitelist = VikeyWhitelist()
        self._last_info: Optional[VikeyInfo] = None
        self._last_check_ts: float = 0.0
        self._lock = threading.RLock()
        # 模拟模式（开发/测试环境无真实VIKEY时）
        self._sim_vikey: Optional[str] = None

    def _detect_mobile(self) -> bool:
        """检测是否移动端"""
        # 简单判断：检查是否有 iOS/Android 环境变量或特征
        if os.environ.get("MOBILE_PLATFORM"):
            return True
        if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ:
            return True
        return False

    # ── 模拟模式（开发/测试） ──

    def simulate_vikey(self, serial: str, chip_id: str = "") -> None:
        """模拟插入VIKEY（开发/测试用）"""
        self._sim_vikey = serial
        self._sim_chip_id = chip_id or hashlib.md5(serial.encode()).hexdigest()[:16]
        # 清除缓存，确保立即生效
        self._last_info = None
        self._last_check_ts = 0.0

    def simulate_remove(self) -> None:
        """模拟拔出VIKEY"""
        self._sim_vikey = None
        # 清除缓存，确保立即生效
        self._last_info = None
        self._last_check_ts = 0.0

    # ── 桌面端 USB 检测 ──

    def _detect_usb_macos(self) -> Optional[VikeyInfo]:
        """macOS: 通过 system_profiler / ioreg 检测 USB 设备"""
        try:
            result = subprocess.run(
                ["system_profiler", "SPUSBDataType", "-json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            # 递归搜索 USB 树
            return self._search_usb_tree(data)
        except Exception:
            return None

    def _search_usb_tree(self, data: Dict, depth: int = 0) -> Optional[VikeyInfo]:
        """递归搜索 USB 树中的 VIKEY 设备"""
        if depth > 10:
            return None
        items = data.get("_items", []) if isinstance(data, dict) else []
        for item in items:
            vid = str(item.get("vendor_id", "")).lower()
            pid = str(item.get("product_id", "")).lower()
            serial = str(item.get("_name", ""))
            # 匹配 VIKEY VID/PID
            if VIKEY_VID_PID["vid"] in vid and VIKEY_VID_PID["pid"] in pid:
                return VikeyInfo(
                    found=True,
                    serial=serial or f"VIKEY_{item.get('location_id', 'unknown')}",
                    chip_id=hashlib.md5(serial.encode()).hexdigest()[:16] if serial else "",
                    vid=vid, pid=pid,
                    device_path=item.get("location_id", ""),
                    platform="desktop",
                    auth_method="usb",
                    detected_at=time.time(),
                )
            # 递归子项
            child = self._search_usb_tree(item, depth + 1)
            if child:
                return child
        return None

    def _detect_usb_windows(self) -> Optional[VikeyInfo]:
        """Windows: 通过 WMI / PowerShell 检测 USB 设备"""
        try:
            ps_cmd = (
                "Get-PnpDevice | Where-Object {$_.Class -eq 'USB'} | "
                "Select-Object InstanceId, FriendlyName | ConvertTo-Json"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
            devices = json.loads(result.stdout)
            if not isinstance(devices, list):
                devices = [devices]
            for dev in devices:
                inst = str(dev.get("InstanceId", ""))
                if VIKEY_VID_PID["vid"] in inst.lower():
                    return VikeyInfo(
                        found=True,
                        serial=dev.get("FriendlyName", "VIKEY_USB"),
                        chip_id=hashlib.md5(inst.encode()).hexdigest()[:16],
                        vid=VIKEY_VID_PID["vid"], pid=VIKEY_VID_PID["pid"],
                        device_path=inst,
                        platform="desktop", auth_method="usb",
                        detected_at=time.time(),
                    )
        except Exception:
            pass
        return None

    def _detect_usb_linux(self) -> Optional[VikeyInfo]:
        """Linux: 通过 lsusb 检测 USB 设备"""
        try:
            result = subprocess.run(
                ["lsusb", "-v"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
            output = result.stdout
            # 搜索 VIKEY VID:PID
            pattern = re.compile(
                r"iSerial\s+(\d+)\s+(.+)|idVendor\s+.+\s(" + VIKEY_VID_PID["vid"] + r")",
                re.IGNORECASE,
            )
            lines = output.split("\n")
            for i, line in enumerate(lines):
                if VIKEY_VID_PID["vid"] in line.lower() and VIKEY_VID_PID["pid"] in line.lower():
                    # 找到匹配的设备，搜索附近的 iSerial
                    serial = ""
                    for j in range(i, min(i + 20, len(lines))):
                        m = re.match(r"\s*iSerial\s+\d+\s+(.+)", lines[j])
                        if m:
                            serial = m.group(1).strip()
                            break
                    return VikeyInfo(
                        found=True,
                        serial=serial or "VIKEY_LINUX",
                        chip_id=hashlib.md5(serial.encode()).hexdigest()[:16] if serial else "",
                        vid=VIKEY_VID_PID["vid"], pid=VIKEY_VID_PID["pid"],
                        device_path=f"/dev/bus/usb/",
                        platform="desktop", auth_method="usb",
                        detected_at=time.time(),
                    )
        except Exception:
            pass
        return None

    # ── SZU100 专用 U 盘检测（与 VIKEY 构成双因子） ──
    # 通过卷标/设备名包含关键字识别，不依赖 VID/PID（兼容不同批次）

    def _detect_szu100_macos(self) -> bool:
        """macOS：检查 /Volumes/ 下是否存在 SZU100 命名卷，并用 diskutil 兜底"""
        # 1) /Volumes/ 目录扫描（最快，已挂载的卷）
        try:
            if os.path.isdir("/Volumes"):
                for vol in os.listdir("/Volumes"):
                    vol_l = (vol or "").lower()
                    if any(kw in vol_l for kw in SZU100_NAME_KEYWORDS):
                        return True
        except Exception:
            pass
        # 2) diskutil list -plist（含未挂载卷，递归扫描 VolumeName）
        try:
            import plistlib
            result = subprocess.run(
                ["diskutil", "list", "-plist"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                try:
                    data = plistlib.loads(result.stdout.encode("utf-8"))
                except Exception:
                    data = plistlib.loads(result.stdout)
                def _scan_node(node) -> bool:
                    if isinstance(node, dict):
                        vol = str(node.get("VolumeName", "") or "")
                        if vol and any(kw in vol.lower() for kw in SZU100_NAME_KEYWORDS):
                            return True
                        # 兼容部分设备用 Content / DeviceIdentifier 字段暴露名称
                        for fld in ("Content", "DeviceIdentifier", "_name"):
                            v = str(node.get(fld, "") or "")
                            if v and any(kw in v.lower() for kw in SZU100_NAME_KEYWORDS):
                                return True
                        for child in (node.get("Partitions") or []):
                            if _scan_node(child):
                                return True
                    elif isinstance(node, list):
                        for item in node:
                            if _scan_node(item):
                                return True
                    return False
                if _scan_node(data):
                    return True
        except Exception:
            pass
        return False

    def _detect_szu100_windows(self) -> bool:
        """Windows：通过 PowerShell 查询卷标（FileSystemLabel）"""
        try:
            # Get-Volume 列出所有卷，FileSystemLabel 即卷标
            ps_cmd = (
                "Get-Volume | Select-Object DriveLetter, FileSystemLabel | "
                "ConvertTo-Json"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                try:
                    devices = json.loads(result.stdout)
                except Exception:
                    devices = []
                if not isinstance(devices, list):
                    devices = [devices]
                for dev in devices:
                    label = str(dev.get("FileSystemLabel", "") or "")
                    if label and any(kw in label.lower() for kw in SZU100_NAME_KEYWORDS):
                        return True
        except Exception:
            pass
        # 兜底：WMI 查询 Win32_LogicalDisk VolumeName
        try:
            ps_cmd = (
                "Get-CimInstance Win32_LogicalDisk | "
                "Select-Object DeviceID, VolumeName | ConvertTo-Json"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                devices = json.loads(result.stdout)
                if not isinstance(devices, list):
                    devices = [devices]
                for dev in devices:
                    vn = str(dev.get("VolumeName", "") or "")
                    if vn and any(kw in vn.lower() for kw in SZU100_NAME_KEYWORDS):
                        return True
        except Exception:
            pass
        return False

    def _detect_szu100_linux(self) -> bool:
        """Linux：扫描 /media、/mnt，并用 lsblk 兜底"""
        # 1) 已挂载点扫描
        for base in ("/media", "/mnt"):
            try:
                if os.path.isdir(base):
                    for entry in os.listdir(base):
                        # /media/<user>/<volume> 或 /media/<volume>
                        full = os.path.join(base, entry)
                        entry_l = (entry or "").lower()
                        if any(kw in entry_l for kw in SZU100_NAME_KEYWORDS):
                            return True
                        if os.path.isdir(full):
                            for sub in os.listdir(full):
                                sub_l = (sub or "").lower()
                                if any(kw in sub_l for kw in SZU100_NAME_KEYWORDS):
                                    return True
            except Exception:
                pass
        # 2) lsblk -J -o LABEL（含未挂载卷的 LABEL）
        try:
            result = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,LABEL"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                def _scan(node) -> bool:
                    if isinstance(node, dict):
                        label = str(node.get("label", "") or "")
                        if label and any(kw in label.lower() for kw in SZU100_NAME_KEYWORDS):
                            return True
                        for child in (node.get("children") or []):
                            if _scan(child):
                                return True
                    elif isinstance(node, list):
                        for item in node:
                            if _scan(item):
                                return True
                    return False
                if _scan(data.get("blockdevices")):
                    return True
        except Exception:
            pass
        return False

    def _detect_szu100(self) -> bool:
        """SZU100 专用 U 盘是否插入（统一入口，按平台分发）"""
        try:
            if self.system == "darwin":
                return self._detect_szu100_macos()
            if self.system == "windows":
                return self._detect_szu100_windows()
            if self.system == "linux":
                return self._detect_szu100_linux()
        except Exception:
            pass
        return False

    def is_szu100_connected(self) -> bool:
        """SZU100 专用 U 盘是否插入（公开接口，带 5s 缓存对齐 VIKEY 检测）"""
        # 复用 detect() 的缓存窗口避免每次都调系统命令
        # 但 SZU100 与 VIKEY 是不同设备，单独维护一个轻量缓存
        now = time.time()
        with self._lock:
            ts = getattr(self, "_szu100_last_ts", 0.0)
            cached = getattr(self, "_szu100_last_val", None)
            if cached is not None and (now - ts) < 5.0:
                return cached
            val = self._detect_szu100()
            self._szu100_last_ts = now
            self._szu100_last_val = val
            return val

    # ── 移动端指纹检测 ──

    def _detect_mobile_fingerprint(self) -> Optional[VikeyInfo]:
        """移动端：生物指纹替代方案"""
        # 移动端通过 WebView/JSBridge 传递指纹认证结果
        # 这里检测环境变量中是否有指纹认证令牌
        fp_token = os.environ.get("VIKEY_FP_TOKEN", "")
        fp_hash = os.environ.get("VIKEY_FP_HASH", "")
        if fp_token and fp_hash:
            return VikeyInfo(
                found=True,
                serial=f"FP_{fp_token[:16]}",
                chip_id=fp_hash[:16],
                vid="FP", pid="FP",
                device_path="biometric://fingerprint",
                platform="mobile",
                auth_method="fingerprint",
                fingerprint_hash=fp_hash,
                detected_at=time.time(),
            )
        return None

    # ── 公开接口 ──

    def detect(self) -> VikeyInfo:
        """检测 VIKEY（一次检测，带缓存5秒）"""
        with self._lock:
            now = time.time()
            if self._last_info and (now - self._last_check_ts) < 5.0:
                return self._last_info

            info: Optional[VikeyInfo] = None

            # 优先检查模拟模式
            if self._sim_vikey:
                info = VikeyInfo(
                    found=True,
                    serial=self._sim_vikey,
                    chip_id=getattr(self, "_sim_chip_id", ""),
                    vid="SIM", pid="SIM",
                    device_path="simulated://vikey",
                    platform="desktop",
                    auth_method="usb",
                    detected_at=now,
                )

            # 移动端
            if not info and self.is_mobile:
                info = self._detect_mobile_fingerprint()

            # 桌面端 USB
            if not info:
                if self.system == "darwin":
                    info = self._detect_usb_macos()
                elif self.system == "windows":
                    info = self._detect_usb_windows()
                elif self.system == "linux":
                    info = self._detect_usb_linux()

            if not info:
                info = VikeyInfo(found=False, platform="desktop" if not self.is_mobile else "mobile")

            self._last_info = info
            self._last_check_ts = now
            return info

    def is_online(self) -> bool:
        """VIKEY 是否在线"""
        return self.detect().found

    def get_identity(self) -> Optional[str]:
        """获取 VIKEY 唯一标识（在线时）"""
        info = self.detect()
        return info.identity if info.found else None

    def is_authorized(self) -> bool:
        """VIKEY 是否在线且在白名单中"""
        info = self.detect()
        if not info.found:
            return False
        return self.whitelist.is_authorized(info)

    def register_current(self, owner: str = "wuchenghao15") -> bool:
        """注册当前检测到的 VIKEY 到白名单"""
        info = self.detect()
        if not info.found:
            return False
        return self.whitelist.register(info, owner)

    def wait_for_vikey(self, timeout: float = 30.0, interval: float = 1.0) -> bool:
        """等待 VIKEY 插入（阻塞，超时返回 False）"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_online():
                return True
            time.sleep(interval)
        return False


# ── 单例 ──
_detector_instance: Optional[VikeyDetector] = None
_detector_lock = threading.Lock()


def get_detector() -> VikeyDetector:
    global _detector_instance
    if _detector_instance is None:
        with _detector_lock:
            if _detector_instance is None:
                _detector_instance = VikeyDetector()
    return _detector_instance


if __name__ == "__main__":
    det = get_detector()
    print("=== VIKEY Detector 自检 ===")
    print(f"  系统: {det.system}")
    print(f"  移动端: {det.is_mobile}")
    info = det.detect()
    print(f"  检测结果: {info.to_dict()}")
    print(f"  在线: {det.is_online()}")
    print(f"  白名单: {det.whitelist.list_all()}")
