---
name: "vikey-szu100"
description: "Checks VIKEY USB加密狗 + SZU100 U盘 hardware drivers 加载 + mount + serial. Invoke when SA 设备不被识别、驱动 crash、macOS ioreg 查不到、或双钥 offline 需定位硬件层。"
---

# VIKEY + SZU100 硬件驱动层诊断

## 当用户说
- "vikey 不识别"、"szu100 挂了"、"驱动加载失败"
- "ioreg 查不到"、"diskutil list 没有 U 盘"
- "双钥 offline 但确实插了"

## 硬件检测入口

**统一 Provider**: `core.services.vikey_driver.get_hardware_key_provider()`
- `provider.detect_vikey()` → bool
- `provider.detect_szu100()` → bool
- `provider.verify_dual_key_atomic(timeout=5.0)` → `(bool, reason)` — threading.Lock + 双线程 AND

### VIKEY ioreg 层（本机 terminal 跑）

```bash
# 查 USB VID:PID
ioreg -p IOUSB -w0 | grep -i "vikey\|0x1A2B\|1a2b"
# 串行号
ioreg -p IOService -w0 | grep -i "serial.*vikey\|VIDKEY"
# macOS 系统信息
system_profiler SPUSBDataType | grep -A2 Vikey
```

### SZU100 mount 层

```bash
# 查 U 盘挂载
diskutil list | grep -i "SZU\|usb\|external"
# 查卷标
ls /Volumes/ | grep -i "szu\|mtscos"
# 正版校验（必须 authentic=True 才通过 AND）
python3 -c "
from core.services.szu100_driver import detect_szu100
info = detect_szu100() or {}
print(f'present={info.get(\"present\")} authentic={info.get(\"is_authentic\")} volume={info.get(\"devices\",[{}])[0].get(\"volume_name\",\"\")}')
"
```

## 驱动加载检查

```bash
python3 << 'PYEOF'
from app.middlewares.vikey_enforcement_middleware import VikeyEnforcementMiddleware
d = VikeyEnforcementMiddleware._check_drivers()
print(f"VIKEY driver:  loaded={d['vikey_driver']['loaded']}  ver={d['vikey_driver']['version']}")
print(f"SZU100 driver: loaded={d['szu100_driver']['loaded']} ver={d['szu100_driver']['version']}")
print(f"all_loaded:    {d['all_loaded']}")
PYEOF
```

## 终端绑定（防远程绕过）

SA 必须从**本机 loopback + hostname 解析出的 IP** 访问（`127.0.0.1`, `::1`, `localhost`）。可通过 `_config/security/sa_bound_terminals.json` 手动追加信任 IP。

## 常见根因

| 症状 | 根因 | 修复 |
|------|------|------|
| VIKEY detect=False | USB 供电不足 / 重插 | 换口 / 直连 |
| SZU100 authentic=False | 改名 U 盘冒充 | 必须正版（volume_name + 哈希校验） |
| drivers not loaded | PATH 未含驱动 | `vikey_driver` 环境 `get_hardware_key_provider()` fallback 补 |
| terminal_not_bound | 远程 SSH / 另一台 Mac | 必须本机访问 |
| Provider timeout | USB 枚举慢 | `provider.verify_dual_key_atomic(timeout=10.0)` 放宽 |
