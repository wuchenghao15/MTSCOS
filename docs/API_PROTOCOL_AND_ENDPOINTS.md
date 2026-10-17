# API 协议与接口总表

> **事实源**: flask-app/routes/*.py + flask-app/server_real_db.py + flask-app/ai_engines/rules_engine/classification_guard.py
> **更新日期**: 2026-10-17 | **版本**: v22.24.0 | **路由总数**: 135+

---

## 0. 协议基础

### 0.1 统一请求格式

| 元素 | 说明 |
|------|------|
| Base URL | `http://<host>:8888` (SERVER模式) / `/` (PROD域名 mtos.site) |
| Content-Type | 表单 `application/x-www-form-urlencoded` / JSON `application/json` |
| 认证 | Flask session cookie（登录后 `session['username']` + `session['role']`） |
| VIKEY 认证 | `session['_sa_override_from_vikey']` = True（SA + VIKEY 插入时注入，拔出即清除） |
| 版本协商 | Header `X-API-Version: v22.24.0`（可选，默认兼容） |

### 0.2 统一响应格式

```json
// 成功 (200)
{ "success": true, "data": { ... } }

// 业务错误 (4xx)
{ "success": false, "error_code": "CLASSIFIED_DENY_ROLE", "message": "..." }

// 服务器错误 (5xx) — 注意: 不得泄露内部实现细节
{ "success": false, "error_code": "INTERNAL_ERROR", "message": "service temporarily unavailable" }
```

### 0.3 HTTP 状态码

| 码 | 语义 | 典型场景 |
|----|------|---------|
| 200 OK | 成功 | 常规响应 |
| 201 Created | 创建成功 | POST 创建资源 |
| 400 Bad Request | 参数错误 | 必填字段缺失 / 格式错误 |
| 401 Unauthorized | 未认证 | 未登录访问需认证接口 |
| 403 Forbidden | 权限不足 | 角色不够 / VIKEY 未在线 / 机密等级拦截 |
| 404 Not Found | 不存在 | 资源不存在 / 路由不存在 |
| 429 Too Many Requests | 限流 | 注册接口 / 敏感接口限流触发 |
| 500 Internal Error | 服务器错误 | DB 连接 / 引擎异常 |

### 0.4 机密等级拦截 (v1.2.0 §B)

`classification_guard` before_request 拦截器对以下路径强制执行密级检查：

| 路径模式 | 密级 | 检查内容 | 失败处置 |
|---------|------|---------|---------|
| `/api/admin/*` | L0 极密 | SA 唯一用户 + VIKEY + SZU100 双硬件 | 403 + 销毁 SA 会话残留 |
| `/api/auth/vikey` | L0 极密 | VIKEY 状态完整性; 匿名 GET 放行（登录页轮询）; 匿名 POST fail-closed | 403 |
| `/api/user/container` | L1 机密 | admin+/security+ 角色 | 403 + 审计落库 |
| `/api/db/export/*` | L2 秘密 | 登录用户 | 403 + 导出日志 |
| `/api/classified/*` | 按注册表 | mt_classified_data.data_code → classification 映射 | 403 + 审计 |

**唯一判定入口**: `PermissionManager.can_access_classification()` (flask-app/ai_engines/rules_engine/perm_manager.py)
**禁止**: 按角色字符串自行判断; 403 响应不得泄露资源存在性/表名/字段名/密钥状态/内部错误详情

### 0.5 限流策略

| 接口 | 限制 | 实现 |
|------|------|------|
| `/api/auth/register` | 每 IP 每设备 10 次/分钟 | SQLite 持久层 mt_register_audit |
| `/api/auth/vikey` POST | 每 IP 60 次/分钟 | Flask-Limiter |
| `/api/classified/*` 写操作 | 每用户 30 次/分钟 | 会话级计数器 |

---

## 1. 认证与会话 `/api/auth`

### 1.1 登录 `POST /api/auth/login`

```
Request:  username, password, vikey_report(JSON), szu100_report(JSON)
Response: { success: true, data: { role, security_level, vikey: { present, is_super_admin }, szu100: { present, verified } } }
会话写入: session['username'], session['role'], session['_sa_override_from_vikey'](条件触发)
```

### 1.2 注册 `POST /api/auth/register`

```
Request:  username, password, confirm_password, email, phone, avatar, birthday, agreement_terms(bool)
Response: { success: true, data: { user_id, username, temp_password_masked } }
```

### 1.3 VIKEY 状态 `GET /api/auth/vikey`

```
Response: { success: true, data: { vikey: { present, is_super_admin, devices[] }, szu100: { present, verified }, security_level: 'full|partial|none' } }
```

### 1.4 注销 `GET /api/auth/logout`

### 1.5 双密钥诊断 `GET /api/diag/sa_dual` / `GET /api/diag/sa_dual/force_sa`

---

## 2. 用户与角色 `/api/user`, `/api/roles`

### 2.1 用户容器 `GET/POST /api/user/container` (L1 机密, 需要 admin+)

### 2.2 角色列表 `GET /api/roles` / `GET /api/roles/summary` / `GET /api/roles/<role_key>`

### 2.3 角色设置 `POST /api/roles/<role_key>/set` / `POST /api/roles/<role_key>/bulk` / `GET /api/roles/<role_key>/audit` / `POST /api/roles/sync`

### 2.4 主题偏好 `GET/POST /api/user/theme_preferences`

---

## 3. 服务器与系统 `/api/server`, `/api/system`, `/api/health`

| 方法 | 路径 | 说明 | 密级 |
|------|------|------|------|
| GET | `/api/health` | 健康探针 | 公开 |
| GET | `/api/system/ping` | 系统 ping | 公开 |
| POST | `/api/client/init` | 客户端初始化 | 公开 |
| POST | `/api/client/verify_keys` | 客户端密钥验证 | L1 |
| GET | `/api/server/vikey-status` | VIKEY 状态 | L1 |
| GET | `/api/server/users` | 用户列表 | L1 |
| POST | `/api/server/daemon-action` | daemon 启停 | L0 |
| POST/GET | `/api/server/auto-diagnose` | 自动诊断 | L0 |
| GET | `/api/server/mcp-status` | MCP 服务状态 | 公开 |
| GET | `/api/db/stats` | DB 统计 | L2 |
| GET | `/api/system/info` | 系统信息 | 公开 |
| GET | `/api/hardware/dual-status` | 双硬件状态 | L1 |

---

## 4. 开发流程 `/api/dev_flow` (§14 强制 12 步骤)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/dev_flow/create` | 立项注册 flow_id + proposal |
| POST | `/api/dev_flow/<flow_id>/advance` | 步骤推进 (STEP_X → STEP_Y) |
| POST | `/api/dev_flow/<flow_id>/version_upgrade` | 触发版本升级 |
| POST | `/api/dev_flow/<flow_id>/git_sync` | Git 同步落库 |
| POST | `/api/dev_flow/<flow_id>/test1000` | 触发 1000 轮测试 |
| GET | `/api/dev_flow/<flow_id>` | 查询 flow 状态 |
| GET | `/api/dev_flow/list` | 当前所有 flow 列表 |

**Commit msg 规范**: `[flow_xxx STEP_7] 变更摘要` — 必须含 flow_id, 否则 pre-commit hook 拒绝

---

## 5. 冰山系统 `/api/iceberg` (v25.0)

### 5.1 冰山元域 (iceberg_meta_routes.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/iceberg/pulse` | 意识脉冲只读快照 |
| POST | `/api/iceberg/pulse` | 手动触发意识脉冲 |
| GET | `/api/iceberg/domains` | 冰山域清单 |
| GET | `/api/iceberg/domains/<key>` | 单域详情 (含五自绑定) |
| GET | `/api/iceberg/self` | 五自能力清单 (strengthen/awaken/upgrade/polish/research) |
| GET | `/api/iceberg/matrix` | 35 绑定点矩阵 |
| GET | `/api/iceberg/runs` | 意识脉冲历史 |
| DELETE | `/api/iceberg/runs/<run_id>` | 删除意识脉冲 run |
| GET | `/api/iceberg/optimizations` | 意识引擎产出的优化建议 |
| GET | `/api/iceberg/daemons` | 五自相关 daemon 状态 |
| GET | `/api/iceberg/thresholds` | 当前阈值配置 |
| PUT | `/api/iceberg/thresholds` | 修改阈值 |
| POST | `/api/iceberg/bindings/<d>/<s>/toggle` | 启用/停用某域某自 |
| POST | `/api/iceberg/evolve/<self>` | 手动触发某自能力 |
| POST | `/api/iceberg/domain_health` | 手动覆盖某域健康分 |
| GET | `/api/iceberg/audit` | 管理操作审计日志 |

### 5.2 移动端冰山 (mobile_iceberg_routes.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/iceberg/mobile` | 移动端状态聚合 |
| GET | `/api/iceberg/new_directions` | 新方向注册 |
| GET | `/api/iceberg/daemon_status` | daemon 实时状态 |
| GET | `/api/iceberg/empower_mobile` | 赋能中心移动端 |
| GET | `/api/iceberg/ble/devices` | BLE 设备列表 |
| GET | `/api/iceberg/ble/gatt/<addr>` | BLE GATT 服务 |
| GET | `/api/iceberg/ble/arduino` | Arduino BLE 桥 |
| GET | `/api/iceberg/admin/daemons` | daemon 管理 |
| GET | `/api/iceberg/admin/health` | 健康分管理 |
| POST | `/api/iceberg/admin/actions` | 管理操作 |

### 5.3 冰山演化 (server_real_db.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/andromeda/state` | 仙女座状态 |
| GET | `/api/andromeda/stars` | 恒星表 |
| GET | `/api/andromeda/stars/<domain>` | 域下恒星 |
| GET | `/api/iceberg/health` | 冰山健康聚合 |
| GET | `/api/iceberg/eigenflux` | EigenFlux 专家集群 |
| GET | `/api/iceberg/upgrade_board` | 升级看板 |
| GET | `/api/iceberg_layer_stats` | 层级统计 |

---

## 6. NeuralHub AI 引擎 `/api/neuralhub` (server_real_db.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/neuralhub/call` | 调用 AI 模型 |
| GET/POST | `/api/neuralhub/routes` | 路由管理 |
| DELETE | `/api/neuralhub/routes/<task_name>` | 删除路由 |
| GET | `/api/neuralhub/stats` | NeuralHub 统计 |
| POST | `/api/neuralhub/arduino_compile_assist` | Arduino 编译辅助 |
| GET | `/api/neuralhub/evolution_logs` | 演化日志 |
| GET | `/api/neuralhub/prompt_versions` | Prompt 版本 |
| POST | `/api/neuralhub/rollback` | Prompt 回滚 |
| GET | `/api/neuralhub/models` | 可用模型列表 |
| POST | `/api/neuralhub/bootstrap` | 引导注册 |
| POST | `/api/neuralhub/route_register` | 路由注册 |
| GET | `/api/neuralhub/system_info` | 系统信息 |
| GET | `/api/neuralhub/api_docs` | API 文档 |
| GET | `/api/neuralhub/daemon_status` | daemon 状态 |
| GET | `/api/neuralhub/employee_distribution` | AI 员工分布 |
| POST | `/api/neuralhub/rebalance` | 重新平衡 |
| POST | `/api/neuralhub/self_upgrade_cycle` | 自升级周期 |
| GET | `/api/neuralhub/daemon_tick` | daemon tick |
| POST | `/api/neuralhub/edu_reform_feed` | 教改投喂 |
| GET | `/api/neuralhub/edu_reform_check` | 教改检查 |
| POST | `/api/neuralhub/knowledge_feed` | 知识投喂 |
| POST | `/api/neuralhub/bili_extract` | 哔哩哔哩提取 |
| GET | `/api/neuralhub/knowledge_inventory` | 知识清单 |

---

## 7. Arduino `/api/arduino` (arduino_session_routes.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/arduino/session/temp-login` | 临时登录 |
| GET | `/api/arduino/events/poll` | 事件轮询 |
| POST | `/api/arduino/events/ack` | 事件确认 |
| GET | `/api/arduino/session/load` | 会话加载 |
| POST | `/api/arduino/session/save` | 会话保存 |
| POST | `/api/arduino/session/trace` | 轨迹记录 |
| POST | `/api/arduino/session/end` | 会话结束 |
| GET | `/api/arduino/session/bind` | 会话绑定 |
| GET | `/api/arduino/session/redirect_target` | 重定向目标 |
| GET/POST | `/api/arduino/admin/setup` | Arduino 管理 |
| GET | `/api/arduino/events/repoll_now` | 立即重轮询 |
| POST | `/api/arduino/lock/register` | 锁注册 |
| POST | `/api/arduino/lock/release` | 锁释放 |
| POST | `/api/arduino/session/commit` | 会话提交 |
| GET | `/api/arduino/vault/list` | Vault 列表 |
| GET | `/api/arduino/vault/<vault_id>` | Vault 详情 |
| GET | `/api/arduino/admin/vault_usage` | Vault 使用统计 |
| POST | `/api/arduino/session/compile_upload` | 编译上传 |
| GET | `/api/arduino/auto_detect` | 自动检测 |

---

## 8. EigenFlux `/api/eigenflux` + 审批 `/api/approvals` + 知识脑库 `/api/knowledge_brain`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/eigenflux/center_stats` | 专家集群状态 |
| POST | `/api/approvals/submit` | 审批提交 |
| GET | `/api/approvals/<request_id>` | 审批详情 |
| POST | `/api/approvals/<request_id>/action` | 审批操作 |
| GET | `/api/approvals/pending` | 待审批列表 |
| GET | `/api/approvals/list` | 审批列表 |
| POST | `/api/approvals/wenquxing` | 温启星专项 |
| POST | `/api/approvals/auto` | 自动审批 |
| GET | `/api/approvals/preview` | 审批预览 |
| GET | `/api/knowledge_brain/search` | 知识搜索 |
| GET | `/api/knowledge_brain/personas` | Persona 列表 |
| GET | `/api/knowledge_brain/stats` | 脑库统计 |
| POST | `/api/knowledge_brain/ask` | AI 问答 |

---

## 9. 其他端点

| 前缀 | 文件 | 接口数 | 说明 |
|------|------|--------|------|
| `/api/console/*` | server_real_db.py | 2 | 控制台记录/周期执行 |
| `/api/container/*` | server_real_db.py | 2 | 容器心跳/状态 |
| `/api/theme/*` | server_real_db.py | 6 | 主题设置/重置/推荐/预设/日出日落 |
| `/api/translation_studio/*` | translation_studio_routes.py | 10 | 翻译工作台 (含发布到冰山) |
| `/api/galaxy/*` | galaxy_routes.py | 多 | 星系演化统计 |
| `/api/me` | role_registry.py | 1 | 当前用户信息 |
| `/api/homepage/stats` | server_real_db.py | 1 | 首页统计 |
| `/api/daemon_status` | andromeda_dashboard_routes.py | 1 | daemon 状态 |
| `/api/db_metrics` | andromeda_dashboard_routes.py | 1 | DB 指标 |
| `/api/system_health` | andromeda_dashboard_routes.py | 1 | 系统健康 |
| `/api/twin_machine` | andromeda_dashboard_routes.py | 1 | 孪生机器 |
| `/api/iceberg_structure` | andromeda_dashboard_routes.py | 1 | 冰山结构 |
| `/api/evolution_timeline` | andromeda_dashboard_routes.py | 1 | 演化时间线 |
| `/api/upgrade_reports` | andromeda_dashboard_routes.py | 1 | 升级报告 |
| `/api/upgrade_overviews` | andromeda_dashboard_routes.py | 1 | 升级概览 |
| `/api/copy_archive` | andromeda_dashboard_routes.py | 1 | 归档复制 |
| `/api/persona_chat` | andromeda_dashboard_routes.py | 1 | Persona 对话 |
| `/api/knowledge_graph/data` | andromeda_dashboard_routes.py | 1 | 知识图谱 |
| `/api/andromeda_daemon_status` | andromeda_dashboard_routes.py | 1 | andromeda daemon 状态 |
| `/api/iol_summary` | andromeda_dashboard_routes.py | 1 | IOL 摘要 |
| `/api/wqx/*` | andromeda_dashboard_routes.py | 3 | 温启星生成/查询/列表 |

---

## 10. 机密等级注册表 (mt_classified_data)

系统中受明确密级标注的资源（12 条注册记录，2026-10-17）：

| data_code | 分类 | 密级 | 典型归属 |
|-----------|------|------|---------|
| SA_VIKEY_SPEC | 极密 | L0 | VIKEY 配置导出 |
| SA_SZU100_SPEC | 极密 | L0 | SZU100 固件导出 |
| TS_VIKEY_SPEC | 极密 | L0 | VIKEY 特定规格 |
| EIGENFLUX_PRIV_KEY | 机密 | L1 | EigenFlux 通信私钥 |

> 注: 完整注册表可通过 `SELECT * FROM mt_classified_data` 查询; `classify_table()` 默认起底 L2_SECRET (§4 默认分类)

---

## 11. 错误码速查

| error_code | HTTP | 说明 |
|-----------|------|------|
| CLASSIFIED_DENY_UNAUTHENTICATED | 403 | 未登录访问受保护资源 |
| CLASSIFIED_DENY_UNKNOWN_ROLE | 403 | 角色不在已知集合 |
| CLASSIFIED_DENY_ROLE | 403 | 角色不够 (如 teacher 访问 L1) |
| CLASSIFIED_DENY_HARDWARE | 403 | SA 但 VIKEY/SZU100 硬件缺失 |
| CLASSIFIED_DENY_SESSION_INVALID | 403 | VIKEY 会话标志与身份不一致 |
| CLASSIFIED_DENY_UNCLASSIFIED | 403 | 无法识别密级 (fail-closed) |
| CLASSIFIED_DENY_COMPLIANCE_GATE | 403 | 合规门未打开 (classification_compliance<100%) |
| VIKEY_STATE_INTEGRITY | 403 | VIKEY 状态不完整 |
| VIKEY_VERIFY_NO_LOGIN | 403 | 匿名 POST /api/auth/vikey |

---

**flow_id**: flow_docs_sync_20261017 | **STEP_7_EXECUTE**