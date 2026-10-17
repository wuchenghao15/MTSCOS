---
name: "eigenflux-network"
description: "Runs EigenFlux AI expert network 巡检: 注册+心跳+好友交流+脑库投喂. Invoke when user 查 EigenFlux 状态、AI 员工连不上、心跳没反应、或想跑一次网络巡检。"
---

# EigenFlux AI 专家网络巡检

## 当用户说
- "EigenFlux 状态"、"AI 员工连了多少"
- "心跳"、"EigenFlux 巡检"、"朋友交流"
- "AI 脑库投喂"

## 引擎

**入口**: `flask-app/engines/ai_eigenflux_network_engine.py` (daemon `sys_eigenflux_network`, 周期 120s)
**注册表**: `mt_eigenflux_registrations` + `mtscos_ai_employees`

```sql
SELECT COUNT(*) FROM mtscos_ai_employees;           -- AI 员工总数
SELECT COUNT(*) FROM mt_eigenflux_registrations;     -- EigenFlux 注册数
SELECT * FROM mt_eigenflux_registrations ORDER BY last_heartbeat DESC LIMIT 20;
SELECT COUNT(*) FROM mt_ai_brain_feed_log;          -- 脑库投喂总数
```

## 巡检命令

```bash
cd flask-app/engines
python3 ai_eigenflux_network_engine.py status
python3 ai_eigenflux_network_engine.py patrol   --heartbeat --feed
python3 ai_eigenflux_network_engine.py friends  --limit 20
```

## 心跳没反应根因

| 现象 | 根因 | 修复 |
|------|------|------|
| last_heartbeat > 5min | daemon 挂了 | `ai_smart_mount_engine.py health` → 重启 |
| registration absent | 未注册 | `ai_auto_hire_engine.py hire --count 10` |
| network blocked | 出网断 | 检查代理 / HTTPS 出口 |
| brain_feed_log 空 | 投喂闭环未跑 | daemon 重启 → 自动投喂 |

## 当前规模（v22.23.0）

```
mtscos_ai_employees: 10,840 人
mt_eigenflux_registrations: 11,347 人 (AI员工+EigenFlux专家)
EigenFlux 专家: 12 人 (架构/合规/安全/DBA/运维/前后端/AI/数据/教育/IoT + 2)
```
