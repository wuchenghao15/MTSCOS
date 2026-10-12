# 冰山系统统一审批中台全面重构方案

> 日期：2026-10-12 ｜ 发起人：苏晓晓（SA wuchenghao15）｜ flow：按 P1–P5 分批走 §14

## 1. Context（为什么做）

冰山现有审批能力由 [approvals_engine.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/engines/approvals_engine.py)（风险分级+审批链）承载，实测存在四类硬伤：

1. **越权**：[approvals_routes.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/routes/approvals_routes.py) 8 个端点全部无 `@system_container`；引擎 `action()` 不校验审批人角色，任何登录用户甚至 anonymous 可批准/驳回任意单；`/api/approvals/auto` 无鉴权即可触发自动审批。
2. **流程死锁**：super_admin 发起的 medium release 因上级链返回 None **不生成人工节点**；AI 预审节点对非白名单类目无人处理；工作台模板 `andromeda_approval_center.html` 不存在（页面 500）。25 单 pending 堆积 10 天。
3. **多套并行/断裂**：`approvals`/`approval_timeline`/`approval_subjects_snapshot`（0 行无引用）、`approval_requests`（0 行）、`mt_approval_*`（在用）三套表；规则 7 步审批硬编码在 [server_real_db.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/server_real_db.py#L9344-L9640) 且适配层 [rule_approval.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/app/services/rule_approval.py) 是空 stub（签名不匹配、提案表不存在，6 个 `/_rules/proposals*` 端点走到服务层即 500）；灰度发布审批 approved 后**无回调**，发布不会启动（[gray_release_engine.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/engines/gray_release_engine.py#L184-L204) 断裂）。
4. **能力缺失**：无会签/或签、委托、抄送、撤回、超时催办/升级、语义预审、统计看板；引擎持实例级长连接（OneDrive 大库锁源）；daemon 逻辑两处重复（独立脚本 + smart_mount 内联 work_body）。

**目标**：重构为统一审批中台——一套三表扩展模型、配置化审批链、强鉴权状态机、本地 LLM 语义预审、SLA 催办升级、业务回调收编、Element Plus 工作台。

**SA 已拍板**：① 全面重构；② LLM 预审接本地 Ollama（零 token，敏感类目强制人工）；③ 存量 25 单三管齐下（规则分流 + SA 清单终审 + 陈旧归档留痕）。

## 2. 已核实的存量事实（归档决策证据）

- 23 单 release pending（2026-10-02，wuchenghao15，risk=medium，current_node=0，仅 initiate+ai_review 两节点且全 NULL）：**21 单在 `mt_release_sessions` 中主体已不存在；另 2 单对应主体已 full/rolled_back 终态**（且终态 release 行挂的 approval_id 是另外两单）→ 23 单全部满足陈旧无效判定。
- 2 单演示孤儿单：`appr_bee9086e14fe`(homework/medium/teacher_demo)、`appr_d5545f4c359d`(course_content/high/professor_demo)，**节点数=0** → 不自动关，进 SA 清单二选一（continue 补链 / expire 归档）。
- 全库审批相关表 20 张，`upgrade_approval_records` 等 0 引用。

## 3. 架构：引擎逻辑迁入 `engines/approval/` 包，旧文件降级 shim

| 新文件 | 职责 |
|---|---|
| `engines/approval/db.py` | 短连接上下文（busy_timeout=30s、`BEGIN IMMEDIATE`、`@db_retry` 仅重试 locked）、`ensure_schema()` 进程内一次性迁移 |
| `engines/approval/policy.py` | 唯一配置源：风险规则、链模板、`ROLE_CHAIN`（修 SA 上级=None）、SLA、LLM 自动/人工矩阵 |
| `engines/approval/chains.py` | assess_risk / build_nodes（mode/quorum/指定人/vikey 节点/自审回避）/ backfill_chain |
| `engines/approval/authz.py` | `can_act(user,req,node,act)` 鉴权矩阵 |
| `engines/approval/state_machine.py` | 单事务流转、以 actions 流水为计票唯一权威、current_node 重算 |
| `engines/approval/service.py` | `ApprovalService`：submit/action/delegate/withdraw/cc/list_*/get/stats/reconcile |
| `engines/approval/llm_review.py` | 本地 Ollama 语义预审 |
| `engines/approval/callbacks.py` | `"module:func"` 字符串回调注册表（防循环导入）、失败重试 |
| `engines/approval/tick.py` | `run_tick()` daemon 五阶段 |
| `engines/approval/reconcile.py` | 存量单处置 |

[approvals_engine.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/engines/approvals_engine.py) 保留为薄 shim：重导出 `assess_risk/build_approval_nodes/submit_wenquxing_for_approval/run_daemon_tick` 与 `ApprovalEngine(db_path=...)` 门面（**保留 test_engines.py 的临时库传参**），现有调用点（gray_release L187、dashboard_routes L1134、smart_mount work_body、CLI）零改动。

## 4. 数据模型（三表 ALTER 加列 + 3 张新表，不建第四套主表）

- **mt_approval_requests 加列**：`title/mode(single|countersign|or_sign)/priority/cc_json/due_at/remind_count/escalate_count/delegate_chain_json/llm_review_json/callback_key/callback_status/callback_attempts/withdraw_reason/withdrawn_by/withdrawn_at/expired_at/flow_id/schema_v2`。status 扩展 `pending/approved/rejected/withdrawn/expired`。
- **mt_approval_nodes 加列**：`status`(新权威：pending/approved/rejected/skipped/delegated/ai_passed，旧 `action` 列双写镜像)、`mode/quorum/approvers_json/approved_by_json/rejected_by/activated_at/due_at/remind_count/escalate_level/delegated_to/vikey_required/llm_verdict/llm_detail_json/llm_retries/backfill_flag`。
- **mt_approval_actions 加列**：`detail_json/vikey_verified`；action 词表扩 `delegate/withdraw/expire/ai_review/auto_pass/escalate/system_close/cc`。
- **新表**：`mt_approval_delegations`（委托规则：委托人/受托人/类目/角色/时间窗/enabled）、`mt_approval_reminders`（催办/升级/过期事件流水，去重限次用）、`mt_approval_callback_log`（回调可重试可审计）；另建 `mt_rule_proposals`（规则提案领域表，P4）。
- **迁移**：逐列 PRAGMA 探测 + 缺失才 ADD COLUMN（常量默认值，SQLite 限制内），只做加法，连续执行幂等；存量 28 行自动获默认值，`schema_v2=0` 标识老链。低峰执行，迁移前文件级备份。

## 5. 鉴权矩阵与状态机（authz.py）

- 每个动作校验：请求存在且 pending → 节点是当前待决节点 → 审批人身份匹配（node.approver_role 角色 / approvers_json 指定 / 有效委托受托人 / SA 对 admin 级以下节点）→ **actor≠initiator 自审回避**。
- **会签 countersign**：distinct 审批人计票达 quorum 才过，同人不重复计票（查 actions 去重），任一 reject 默认一票否决；**或签 or_sign**：任一 approve 即过，reject 不阻断他人。
- SA 终审节点 `vikey_required=1`：仅 wuchenghao15，**服务端调 `get_vikey_api().detect()` 核验**，不信客户端传参（复用 server_real_db L9516-9529 同款）。
- 单 SA 现实约束：SA 自发 critical 单，admin 会签节点须非发起人管理员；无其他管理员时挂起标红，不自动放行（`allow_sa_self_with_vikey=False` 配置兜底）。
- 撤回：仅发起人；rule_change/permission_change/daemon_change 已有任一人工通过后禁撤。
- 所有流转在一个 `BEGIN IMMEDIATE` 事务：插 actions → 更新节点（status/action 双写）→ 重算首个 pending 节点为 current_node 并设 activated_at/due_at → 终态更新 requests；**回调在事务提交后执行**，失败只落 callback_log 不回滚。删除现 L369-387 把 None 当通过的脆弱判定。

## 6. LLM 语义预审（llm_review.py，零 token）

- daemon 异步执行（submit 不同步，避免挂请求）；直接 urllib POST `http://localhost:11435/api/chat`，model `qwen2.5:14b-q5`，timeout 45s，temperature 0.2；先 GET `/api/tags`（3s）探活。
- 强制 JSON 输出 `{verdict: pass|reject|manual, risk, reasons[], summary}`；解析失败/超时/探活失败/格式漂移一律 `manual` 转人工，**绝不自动拒绝、绝不阻断**。
- 代码侧二次强制（不信模型）：`rule_change/permission_change/daemon_change/release` 且 high/critical → 无论模型结论强制 manual；仅 `wenquxing/parent_feedback/homework/course_content/exam` 的 low/medium 且 verdict=pass 自动过；自动终局驳回只允许 wenquxing/parent_feedback 的 low。
- 结论落节点 llm_* 列 + actions(ai_review, actor=`andromeda:llm`)，记录 model/耗时/tokens；每轮最多处理 2 个最老节点（预算 ~100s），重试限 3 次。

## 7. daemon：单一 tick()，五阶段

`sys_auto_approval_daemon.run_cycle()` 与 smart_mount work_body 都收敛为调 `run_tick()`：
1. **auto**（≤10s）：确定性自动审批（initiate / auto_pass / 学生文曲星 teacher 确认），收窄后不含 LLM；
2. **llm**（≤100s）：≤2 个 ai_review 节点；
3. **sla**（≤30s）：补算 due_at → 催办（复用 [andromeda_notifier.py](file:///Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/engines/andromeda_notifier.py)，给其 `notify()` 加可选 `target_user`，默认行为不变）→ 升级（**不插节点**，approvers_json 追加上级/SA、escalate_level+1）→ 过期；
4. **callback**（≤20s）：失败回调退避重试（<3 次）；
5. **stats**（≤5s）。

SLA 策略（policy 可配）：low 24h/催 8h×2/72h 过期；medium 12h/4h×2/48h；high 6h/2h×3/24h；critical 2h/1h×3/**只升级不过期**。`rule_change/permission_change/daemon_change/release` 永久 expire_protected（只催办升级；本次 23 单由人工 reconcile 关闭而非 tick）。

> 部署注意：work_body 仅在 daemon 重挂载时由 `generate_daemon_script()` 重新落盘，P3 上线后需让 sys_auto_approval 重挂一次（停进程/清 PID，smart_mount 下轮自动重生成）；过渡期 shim 保留旧方法不会炸。

## 8. 业务收编

- **release（P4）**：create_release 传 `callback_key='gray_release'` 与真实角色；新增 `on_approval_final(req,event)`：approved 且主体 draft/approving → 抽出现 `approve_and_start()` 主体启动 canary 1%；rejected/expired → 主体置 closed（主体缺失幂等 skipped）。
- **规则 7 步（P4）**：rule_approval.py 落地为适配层，新建 `mt_rule_proposals`，严格按现端点调用签名与 URL/返回形状实现：提议 → **admin 会签 quorum=2**（两名不同管理员）→ AI 复审（LLM 只建议强制 manual，EigenFlux 意见同落）→ **SA + VIKEY 终审**。终审回调里回写 `mt_rule_changelog`：`approved_by_7step=1`、`sa_final_decision`、`sa_vikey_verified=1`、`admin_approvers_json`、`eigenflux_panel_json`，并执行现 L9550-9590 的规则回写/激活。server_real_db 6 端点仅瘦身（保留装饰器/URL/VIKEY 核验），`/_rules/bypass_approve` 本期不动。
- **§14**：审批单透传 flow_id，终态/异常/升级事件调 `feed_brain()` 镜像投喂；**绝不创建/推进 mt_dev_flow_session**。
- **upgrade（P5）**：auto_upgrade_system 提审 `category='upgrade'` + `callback_key='system_upgrade'`，回调 resume 挂起升级，替代 0 引用的 upgrade_approval_records。
- **permission（P5）**：权限变更改为先提审批（critical/保护类/必人工），approved 回调内才真正写库，禁止先改后批。

## 9. 路由与前端

- 全部端点补 `@system_container`，视图统一用 `g.current_user`（替换 anonymous 兜底）；新增：`/cc`、`/delegations`(GET/POST/DELETE)、`/withdraw`、`/delegate`、`/llm`(GET/POST retry)、`/stats/summary`、`/stats/trend`、`/admin/batch`(SA+vikey)、`/admin/expire`；`/auto` 从无鉴权收为 admin；`/list` 改服务端分页过滤（非 admin 强制本人范围）；详情按发起人/相关人/抄送人/admin 做可见性。
- 新建 `templates/andromeda_approval_center.html`（参照 andromeda_gray_center.html：Vue3 + element-plus + echarts CDN，颜色只用设计 Token CSS 变量），Tab：待我审批 / 我发起的 / 抄送我的 / 委托设置 / 统计看板(admin) / SA 终审与归档(SA)。详情 drawer：el-steps 节点时间线（会签显示 n/quorum、AI 意见卡：verdict+理由+模型/token/耗时）、同意/驳回(必填意见)/委托/撤回、催办升级记录。JS 拆 `static/js/approvals/`：api/todo_list/detail_drawer/delegation_panel/stats_dashboard/sa_batch。
- 占位页 approval_management.html 加跳转链接不删。

## 10. 存量 25 单处置（reconcile CLI，P1）

`python -m engines.approval reconcile --dry-run / --apply --confirm`（带 flow_id，先 .backup）：
- 23 release → `expired`（原因 subject_missing×21 / subject_terminal×2），未决节点 skipped，actions 写 `expire`（actor=`system:reconcile_20261012`，detail 带判定依据），只写不删；
- 2 孤儿演示单 → 保留 pending 进 SA 工作台清单，SA 选 `continue`（backfill_chain 补节点，backfill_flag=1）或 `expire`。

## 11. 分期实施（每批独立 flow_id，过 pre-commit）

| 批次 | 内容 | 验收 |
|---|---|---|
| **P1** | approval 包骨架、短连接、幂等迁移、policy/chains/authz/state_machine/service、shim、reconcile CLI | 迁移二次幂等；28 行不丢；test_engines 临时库全绿；dry-run 清单=23+2 与事实一致；apply 后 23=expired 留痕、2 单保留 |
| **P2** | 路由鉴权化+新端点+可见性+工作台（待办/发起/详情/动作/委托基础） | 未登录 401/越权 403；自审被拒；会签/或签/委托 E2E；页面无 500；旧调用方不受影响 |
| **P3** | llm_review、tick 五阶段、daemon/work_body 收敛、notifier、SLA | ollama 在线每轮≤2 单；停 ollama 全 fail-safe manual；改 due_at 到过去验证 remind→escalate；保护类目不过期；重挂载生效 |
| **P4** | 回调注册表、release 串 canary、rule_approval 适配层 + mt_rule_proposals + 6 端点瘦身 + changelog 回写 | release 终审自动 canary；规则单 2 管理员会签→AI 建议→SA+vikey 走通；changelog 五字段齐全；旧 URL/返回兼容 |
| **P5** | upgrade/permission 接入、统计看板、委托 UI、死表 RENAME 观察一版后 DROP | 升级挂起/恢复闭环；权限先批后写；看板数与手查 SQL 一致；死表移除全仓冒烟无引用 |

依赖：P1 为前提；P2/P3 可并行；P4 依赖 P1 回调与 P2 SA 链路；P5 依赖 P4。

## 12. 端到端验证

- 单测：engines/test_engines.py 扩展——风险分级 8 条原断言不回归 + 会签计票/一票否决/或签/委托/自审回避/越权矩阵/LLM 强制 manual（mock urllib）。
- 隔离库：临时库造单跑 submit→各节点 action→approved→回调全链；并发双击同节点不重复计票。
- 路由冒烟：flask-smoke-tester L1 注册/L2 302 登录/L3 JSON/L4 业务流程；未登录、错角色、自审、伪造 vikey 四组负例。
- daemon：手动改 due_at 历史值触发催办/升级；关停 ollama 验证 fail-safe；锁竞争（并发 tick）验证重试与 parked。
- 页面：浏览器走 SA 终审 23+2 单、管理员会签规则提案、学生文曲星自动审批、统计看板。
- 每批带 `[FLOW-...]` 提交；VERSION 不随本任务改动。

## 13. 三大风险与对策

1. **会签/状态两级一致性**：所有流转单事务 + actions 流水唯一计票权威 + current_node 由"首个 pending 节点"重算（不增量猜测）；旧 action 列只双写镜像，新逻辑只读 status。
2. **LLM 假自动/fail-safe**：异步 daemon 跑、硬限流每轮 2 单、敏感类目代码侧强制 manual、任何异常转人工。
3. **规则收编审计失真/回调时序**：适配层严格复刻现签名与 URL；vikey 只信服务端 detect；回调事务提交后执行、失败入表重试、主体缺失幂等；changelog 回写放规则回调内断言。
