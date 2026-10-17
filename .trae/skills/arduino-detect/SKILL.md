---
name: "arduino-detect"
description: "Detects Arduino device VID:PID via ioreg/macos, 适配驱动, 检查权限(仅 wuchenghao15), sync 19教程+15组件+3实验+7板卡. Invoke when user 查 Arduino 设备、驱动适配、教程同步、或 Arduino IDE 不识别板卡。"
---

# Arduino 设备检测与驱动适配

## 当用户说
- "查 Arduino 设备"、"Arduino 不识别"、"板卡选哪个"
- "驱动装了吗"、"VID:PID 是什么"
- "同步 Arduino 教程"、"Arduino IDE 打不开"

## 设备检测入口

**引擎**: `flask-app/engines/ai_arduino_detect_engine.py` (daemon `sys_arduino_detect`, 周期 30s)
**检测方法**: macOS `ioreg` 递归枚举 IOService 树，匹配 USB 父节点

```bash
# 终端直接查
ioreg -p IOUSB -w0 -r -l 2>/dev/null | grep -E "idVendor|idProduct|USB Vendor" | head -10
# 已知 VID:PID
#   UNO R3:    1a86:7523 (CH340), 2341:0001
#   Nano:      2341:000D
#   ESP32:     10C4:EA60 (CP210x)
#   Leonardo:  2341:0036
```

## 同步数据库

```sql
SELECT * FROM mt_arduino_boards LIMIT 10;       -- 7 板卡
SELECT * FROM mt_arduino_tutorials LIMIT 10;    -- 19 教程
SELECT * FROM mt_arduino_components LIMIT 10;   -- 15 组件
SELECT * FROM mt_arduino_experiments LIMIT 10;  -- 3 实验
SELECT COUNT(*) FROM mt_arduino_detected_devices; -- 当前已检测
```

## 权限

Arduino 页面 **仅 wuchenghao15 可访问**（`SA 专用路径白名单`）：
- `/admin_app/arduino_ide`
- `/admin_app/arduino_*`
其他角色一律 403（`sa_arduino_guard.py` middleware + 双密钥 + 终端绑定）

## 同步命令

```bash
cd flask-app/engines && python3 ai_arduino_engine.py sync  --force  --limit 20
python3 ai_arduino_detect_engine.py scan  --json
```

## 常见根因

| 症状 | 根因 | 修复 |
|------|------|------|
| 板卡 IDE 不识别 | 驱动未装 (CH340 / CP210x / FTDI) | 装 `CH340_driver` / `CP210x VCP` / 卸载旧 FTDI |
| USB 端口找不到 | macOS SPP 权限 | System Settings → Privacy → Full Disk 给 Arduino IDE |
| 权限 403 | 非 SA / 无双钥 | 必须 wuchenghao15 + VIKEY+SZU100 + 本机 |
| daemon 未运行 | smart_mount 挂掉 | `ai_smart_mount_engine.py health` |
