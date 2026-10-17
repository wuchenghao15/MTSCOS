---
name: "smart-mount"
description: "Manages 15 smart_mount daemons: health check, restart, force-repair, EigenFlux weight decision. Invoke when 用户查 daemon 状态、smart_mount 挂了、daemon auto-repair、或想 run patrol/auto_hire/deep_inspection。"
---

# 智能挂载 smart_mount 引擎

## 当用户说
- "smart_mount 状态"、"daemon 挂了"、"重启 daemon"
- "15 个 daemon 巡检"、"auto-repair"、"force-repair"
- "patrol"、"auto-hire"、"deep-inspection"、"copy-inspection"

## 权威入口

**引擎**: `flask-app/engines/ai_smart_mount_engine.py`
**daemon 注册表**: `mt_daemon_registry`（15 进程，auto_repair 周期 120s）

### 15 daemon 清单

| # | 进程名 | 来源 | 周期 | 职责 |
|---|--------|------|------|------|
| 1 | sys_heartbeat_writer | SYSTEM_REQ | 30s | 心跳写入 |
| 2 | sys_patrol_inspector | SYSTEM_REQ | 60s | daemon 状态巡检 |
| 3 | auto_方向1_调度中枢 | AI_SUGGESTION | 60s | AI 强制要求自动挂载 |
| 4 | sys_arduino_detect | SYSTEM_REQ | 30s | Arduino 检测 |
| 5 | sys_eigenflux_network | SYSTEM_REQ | 120s | EigenFlux 心跳 |
| 6 | sys_auto_repair | SYSTEM_REQ | 120s | FAILED daemon 自动修复 |
| 7 | sys_local_inference | SYSTEM_REQ | 120s | 本地 AI 推理 |
| 8 | sys_rule_enforcer | SYSTEM_REQ | 300s | 规则学习+严格执行 |
| 9 | sys_auto_patrol | SYSTEM_REQ | 300s | 源码巡逻队 |
| 10 | sys_auto_hire | SYSTEM_REQ | 300s | AI 自动雇佣 |
| 11 | sys_arduino_sync | SYSTEM_REQ | 600s | Arduino 同步 |
| 12 | sys_deep_inspection | SYSTEM_REQ | 600s | 深度巡检 |
| 13 | sys_edu_sync | SYSTEM_REQ | 600s | 教辅同步 |
| 14 | sys_file_organizer | SYSTEM_REQ | 600s | 智能文件整理 |
| 15 | sys_copy_inspection | SYSTEM_REQ | 900s | 文案合规巡检 |

## 巡检命令

```bash
cd flask-app/engines
python3 ai_smart_mount_engine.py health       # 15 daemon 全量状态
python3 ai_smart_mount_engine.py restart --name sys_auto_patrol
python3 ai_smart_mount_engine.py repair --force --name sys_xxx
python3 ai_smart_mount_engine.py patrol       # 强制跑一次巡检
```

## 健康查询 SQL

```sql
SELECT name, status, last_heartbeat, uptime_seconds, cpu_pct, mem_mb
FROM mt_daemon_registry
ORDER BY name;
```

## 常见故障

| 症状 | 根因 | 修复 |
|------|------|------|
| status=FAILED | 进程 crash / 端口占用 | `repair --force` 自动重拉 |
| 长时间 stale (> 3×周期) | watchdog 未触发 | 手动 restart |
| CPU 飙高 | local_inference 循环 | kill + 降 `--chunk` |
| 新增 daemon 未出现 | 未在 smart_mount 注册 | 写 `mt_daemon_registry` INSERT + 重启引擎 |
