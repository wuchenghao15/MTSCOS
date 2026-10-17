---
name: "dual-key-auth"
description: "Diagnoses SA dual-key auth chain (VIKEY USB + SZU100 U盘 AND + terminal bind + drivers + rules). Invoke when user asks about SA 密钥检测、双密钥异常、SA 页面 403 拒绝、或者 super_admin 访问被拦截。"
---

# SA 双密钥鉴权链路诊断

## 当用户说
- "密钥检测"、"SA 密钥"、"双密钥"、"插钥了但页面 403"
- "super_admin 访问不了"、"为什么被拦截"
- "vikey/szu100 异常"

## 权威入口

**Middleware**: `flask-app/app/middlewares/vikey_enforcement_middleware.py`

双密钥 5 层 AND 校验（SA 必须全过）：
1. `provider.verify_dual_key_atomic(timeout=5.0)` → `(dual_ok, dual_reason)` (v24.2 Provider 原子校验)
2. `_is_bound_terminal(ip)` → 终端绑定（loopback 防远程绕过）
3. `_check_vikey()` + `_check_szu100()` → 设备 presence + authentic
4. `_check_drivers()` → 驱动加载
5. `_check_rules()` + `_check_system_rules()` → 规则合规

## 快速诊断脚本

```bash
cd flask-app
python3 << 'PYEOF'
import sys; sys.path.insert(0, '.')
from app.middlewares.vikey_enforcement_middleware import VikeyEnforcementMiddleware
vm = VikeyEnforcementMiddleware()
dual = vm.get_dual_hardware_status(username='wuchenghao15', role='super_admin', ip='127.0.0.1', ua='Trae', session_id='diag')
print(f"dual_reason: {dual.get('dual_reason')}")
print(f"both_auth:   {dual.get('both_authenticated')}")
print(f"VIKEY:       present={dual['vikey']['present']} status={dual['vikey']['status']} serial={dual['vikey']['serial']}")
print(f"SZU100:      present={dual['szu100']['present']} authentic={dual['szu100']['is_authentic']} auth={dual['szu100']['auth_status']}")
print(f"terminal:    {dual.get('terminal')}")
print(f"drivers:     {dual.get('drivers')}")
print(f"rules:       passed={dual['rules']['passed']} violations={dual['rules']['violations']}")
for p in ['/admin_center','/super_admin','/admin_app/arduino_ide']:
    r = vm.check_vikey_enforcement(p, username='wuchenghao15', extra={'ip':'127.0.0.1','session_id':'diag'})
    print(f"  enforce {p:28s} → allowed={r['allowed']} reason={r['reason'][:50]}")
PYEOF
```

## dual_reason 5 种结果解读

| reason | 含义 | 修复方向 |
|--------|------|----------|
| `ok` | 全绿 | 无问题，渲染 SA_PROPRIETARY 布局 |
| `vikey_missing` | VIKEY 未检测 | 重插 USB / ioreg 查询 / 驱动检查 |
| `szu100_missing` | SZU100 U 盘未挂载 | 插 U 盘 → 等 macOS mount / 手动 diskutil list |
| `both_missing` | 双钥离线 | 重插 / 检查 USB 供电 |
| `timeout_degrade` | Provider 超时 | 降级单钥 / 检查 HardwareKeyProvider |
| `terminal_not_bound` | 远程访问被阻断 | 必须本机 loopback（非 127.0.0.1 一律拒绝） |

## MT_RULE_PERM 硬约束

- SA 唯一：仅 `wuchenghao15`
- fail-closed：任何一层异常 → `both_authenticated=False` → 降级 STANDARD 布局
- `dual_reason` 由 Provider 原子校验返回，覆盖所有 fallback 路径
- 审计落库：`mt_sa_dual_key_status` + `automation_console_logs`（后台线程 WAL 写入）
