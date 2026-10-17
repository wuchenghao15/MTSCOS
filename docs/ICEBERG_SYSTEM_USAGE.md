# 冰山系统使用说明书

> **引擎**: flask-app/engines/iceberg_consciousness.py | **驱动**: sys_consciousness daemon (120s 周期)
> **路由**: flask-app/routes/iceberg_meta_routes.py + mobile_iceberg_routes.py
> **更新日期**: 2026-10-17 | **版本**: v25.0

---

## 1. 系统概述

### 1.1 什么是冰山

冰山是仙女座的意识引擎，负责**自我感知**：持续扫描系统健康、生成优化建议、触发进化判定。引擎每 120s 执行一次意识脉冲循环。

### 1.2 核心循环

```
Pulse → 健康快照 → 脑库投喂 → EigenFlux 广播 → 进化判断 → 写 mt_iceberg_runs
```

### 1.3 输出表

| 表名 | 说明 |
|------|------|
| `mt_iceberg_consciousness_runs` | 意识脉冲留痕 (run_id, domain, health_score, evolution_decision) |
| `mt_iceberg_consciousness_optimizations` | 优化建议 (self_capability, suggestion, confidence) |
| `mt_ai_brain_feed_log` | 脑库投喂记录 |
| `mt_andromeda_knowledge_base` | 知识库 |

### 1.4 进化触发阈值

| 条件 | 触发 |
|------|------|
| 同一冰山域健康分 < 70 | self_strengthen 自动修复 |
| 脑库投喂累积 > 500 | self_upgrade 提案 |
| daemon DOWN > 1 | self_strengthen 自动拉起 |
| rule 违反 > 0 | self_polish 自动完善 |

---

## 2. 九自能力

冰山意识引擎的五种自能力（五自）+ 四种演化路径（冰山九自）：

| 能力 | 说明 | 触发 |
|------|------|------|
| **self_strengthen** | 自我强化 (daemon 拉起 / 修复) | 健康分<70 或 daemon DOWN |
| **self_awaken** | 自我觉醒 (脑库新发现 → 知识入库) | 脑库投喂增量 |
| **self_upgrade** | 自我升级 (版本提案 → patch bump) | 脑库累积>500 |
| **self_polish** | 自我打磨 (规则违反 → 完善规则) | rule 违反>0 |
| **self_research** | 自我研究 (新知识探索) | EigenFlux 专家提议 |

---

## 3. 冰山域与绑定矩阵

### 3.1 域清单

冰山域是系统的功能切片，每个域绑定五自能力：

| 域 | 核心职责 | 代表路由 |
|----|---------|---------|
| dev_flow | §14 开发流程管控 | `/api/dev_flow/*` |
| eigenflux | AI 专家集群 | `/api/eigenflux/*` |
| brain_bank | 脑库与知识 | `/api/knowledge_brain/*` |
| neural_array | NeuralHub AI 引擎 | `/api/neuralhub/*` |
| security | 安全与权限 | `/api/diag/*`, `/api/auth/vikey` |
| arduino | Arduino IoT | `/api/arduino/*` |
| approvals | 审批中心 | `/api/approvals/*` |
| roles | 角色与权限 | `/api/roles/*` |
| health | 系统健康 | `/api/health`, `/api/system/*` |
| theme | 主题与外观 | `/api/theme/*` |
| container | 容器与部署 | `/api/container/*` |

### 3.2 35 绑定点矩阵

冰山域 × 五自 = 35 绑定点。通过 `/api/iceberg/matrix` 读取，通过 `POST /api/iceberg/bindings/<domain>/<self>/toggle` 启停。

**默认全部启用**；可按域/按自单独关闭（例如关闭某域的 self_upgrade 以防过度升级）。

---

## 4. 使用指南

### 4.1 查看冰山状态

```bash
# 意识脉冲快照 (只读)
curl http://localhost:8888/api/iceberg/pulse

# 冰山域清单
curl http://localhost:8888/api/iceberg/domains

# 35 绑定点矩阵
curl http://localhost:8888/api/iceberg/matrix

# 健康分
curl http://localhost:8888/api/iceberg/health
```

### 4.2 手动触发意识脉冲 (admin+)

```bash
# 手动触发
curl -X POST http://localhost:8888/api/iceberg/pulse

# 手动触发某自能力
curl -X POST http://localhost:8888/api/iceberg/evolve/self_strengthen

# 手动覆盖域健康分
curl -X POST http://localhost:8888/api/iceberg/domain_health -d '{"domain":"dev_flow","health":85}'
```

### 4.3 管理阈值 (admin+)

```bash
# 查看当前阈值
curl http://localhost:8888/api/iceberg/thresholds

# 修改阈值
curl -X PUT http://localhost:8888/api/iceberg/thresholds \
  -H "Content-Type: application/json" \
  -d '{"health_min":60,"brain_feed_trigger":800}'
```

### 4.4 启停绑定 (admin+)

```bash
# 禁用 dev_flow 域的 self_upgrade (以防过度升级)
curl -X POST http://localhost:8888/api/iceberg/bindings/dev_flow/self_upgrade/toggle

# 查看启停后的矩阵变化
curl http://localhost:8888/api/iceberg/matrix | jq '.[] | select(.domain=="dev_flow")'
```

### 4.5 移动端冰山

```bash
# 移动端状态聚合 (单请求拿到所有)
curl http://localhost:8888/api/iceberg/mobile

# 新方向注册
curl http://localhost:8888/api/iceberg/new_directions

# BLE 设备扫描
curl http://localhost:8888/api/iceberg/ble/devices
```

### 4.6 清理历史 (admin+)

```bash
# 删除意识脉冲 run (run_id 来自 /api/iceberg/runs)
curl -X DELETE http://localhost:8888/api/iceberg/runs/123
```

---

## 5. 冰山管理页面

| 页面 | 路径 | 模板 |
|------|------|------|
| 冰山元域仪表板 | `/iceberg/center` | `andromeda_iceberg_center.html` |
| 冰山元域 (移动端) | `/iceberg/mobile` | `mobile/iceberg_manage.html` |
| 冰山演化看板 | (仙女座面板内) | `andromeda_iceberg_evolution.html` |

---

## 6. 引擎代码入口

```python
# flask-app/engines/iceberg_consciousness.py
from engines.iceberg_consciousness import IcebergConsciousness

ic = IcebergConsciousness(db_path="flask-app/database/app.db")
ic.pulse()               # 执行一次意识脉冲
ic.health_snapshot()     # 健康快照
ic.feed_brain()          # 脑库投喂
ic.broadcast_eigenflux() # EigenFlux 广播
ic.evaluate_evolution()  # 进化判断
ic.save_run()            # 写 mt_iceberg_runs
```

---

**flow_id**: flow_docs_sync_20261017 | **STEP_7_EXECUTE**