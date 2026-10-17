# 冰山系统 v22.2.0 → v23.0.0 大版本升级计划

## Context（为什么做）

近几轮已让仙女座从"视觉绑定"走到"数据绑定"并修复了自演化循环 19 天空转，但深度审计暴露出**四个阻断 v23 的真实缺口**：

1. **功能闭环断裂**：`andromeda_auto_loop` 投递的 `DAEMON_REPAIR` / `RESEARCH_DERIVE` 两类工作项**无消费者**——`collect_suggestions()` 白名单只有旧两类；STARTED/PROMOTED 研究提案没有执行器收口。
2. **状态机/数据结构债**：`collect_suggestions()` 写不存在的 `evaluated_at` 列每轮报错；`REPAIRING` 状态无回收路径（黑洞）；`rule_db.insert_rule_changelog()` 列名与真实表漂移（直接调必失败）；系统版本有三个读取源且 `_get_andromeda_state` 误把规则 changelog 版本当系统版本。
3. **部署互杀**：8888 被 4 个 launchd 代理争抢，`sync-keepalive` 每 30s 误杀健康实例（已通过删 wrapper 暂时止血，需正式收敛）。
4. **缺跨大版本守卫**：双机 rsync 不比较版本，违反《版本升级规则》§3.3。

实测：9 个 FAILED daemon = 6 个有 processes 行但进程已死（需走重启分支）+ 3 个无启动配方孤儿（只能 DEFER）；`mt_ai_suggestion_pool` 14 列、status CHECK 仅允许 `PENDING/EVALUATED/DEPLOYED/DEFERRED/REJECTED`。

**目标产出**：自演化双闭环真正跑通、版本回归单一 SSOT、8888 单主管、跨 major 同步受守卫；合规地发 **v23.0.0**。

## 关键决策（已与 SA 确认）

- **先做全部代码与开发机验证，`VERSION` 暂留 `v22.2.0`**；SA VIKEY 终审脚本 `v23_upgrade_finalize.py` 备好待命，VIKEY 在场时一键 finalize（改 VERSION + changelog 置位 + tag）。
- 跨 major 守卫加到 `_entry_wrappers/tri_sync.sh`，**顺手修正陈旧 host**：`192.168.31.9`/`~/mtscos` → `100.106.220.96`/`~/MTSCOS_AI_Project`。
- 节奏：**先开发机 → 再 Mac mini → 后公网**。

---

## 阶段 0 · 治理起草 + 迁移（AI 可做，不 bump VERSION）

**新增 `flask-app/scripts/migrations/v23_0_0_baseline.py`**（幂等，沿用项目 `CREATE TABLE IF NOT EXISTS` 约定，不引入 alembic）：
- 建标记表 `mt_schema_revisions(revision TEXT PRIMARY KEY, applied_at, note)`，已应用则整体跳过；每条 DDL 独立 try/except。
- `ALTER TABLE mt_ai_suggestion_pool ADD COLUMN evaluated_at TEXT`（PRAGMA 守卫列存在性，修复 L2335 报错）。
- 建 `mt_research_implementations(impl_id, prop_id, suggestion_id, artifact_type, artifact_path, status, attempts, error, flow_id, created_at, updated_at)`。
- 建 `system_versions`（列与 `get_version_info()` 的 SELECT 对齐）。
- 不改任何既有业务表。

**changelog 草稿落库**（直接按真实列 INSERT，绕开漂移的 `rule_db`）：`rule_id='SYSTEM_VERSION'`（不复用 `MT_RULE_VERSION`，那是规则文档自身版本）、`change_type='MAJOR'`、`from v22.2.0 → v23.0.0`、`action='SYSTEM_MAJOR_UPGRADE'`、`risk='high'`、`approved_by_7step=0`、`sa_final_decision=NULL`、`sa_vikey_verified=0`。
- `eigenflux_panel_json`：本地 Ollama（零 token）生成 5 人磋商（架构/合规/DBA/安全/运维），数组含 panel_id/role/vote/rationale/model/voted_at，头摘要含 quorum `>=4/5`、generated_by/at；AGREE≥4。
- `admin_approvers_json` **不编造**（单机单管理员现状），在 change_summary 记录例外。
- 插入前去重：同 rule_id+to_version 已存在则跳过。

本升级自身先建 §14 flow：`flow_v23_major_upgrade_<ts>`。

---

## 阶段 1 · 三个功能闭环 + 版本 SSOT（开发机，AI 可做）

### 1A. DAEMON_REPAIR — 权威主管对账（不扩建议池白名单）

在真实运行的 `engines/ai_smart_mount_engine.py`（4027 行版；根目录旧副本不动）新增 `reconcile_daemon_registry()`，挂在 `heartbeat_check()` 之后，每 5 分钟一轮，短事务 + 条件 UPDATE 租约（CAS）防竞争。对每个 registry 中 `FAILED/REPAIRING` 行按运行时 `os.kill(pid,0)` 动态分流：
- **A 存活且心跳新鲜** → registry 纠偏 RUNNING（写真 pid/心跳），建议项 PENDING→`DEPLOYED`（meta: state_corrected_alive）。
- **B 进程已死且 restart_count<5**（当前 6 个）→ 不自行 fork；把对应 `mt_ai_smart_mount_processes` 行置 STOPPED，使其被既有 `heartbeat_check` NON-RUN 重启分支捞起（唯一 Popen 仍走 `_start_subprocess`）；重启成功后下一轮回 A。
- **C 无 processes 行但在 SYSTEM_REQUIRED_DAEMONS 目录** → 走 `mount_system_required()` 配方拉起。
- **D 无行且不在目录**（当前 3 个孤儿）→ registry 回 FAILED + 退避 1800s，建议项 `DEFERRED`（reason=no_launch_recipe），**禁止盲拉**；重试 >5 次 DEFERRED（restart_budget_exhausted）。
- 消除 REPAIRING 黑洞：对 REPAIRING 持续 >10min 回收重判；L1497 的 AI 团队 `FAILED→REPAIRING` 批量翻转改为带租约/no-op，避免无租约翻转。
- 建议项状态仅用 CHECK 五值，审计细节进 `meta_json`，时间写 `deployed_at`。

### 1B. RESEARCH_DERIVE — 节流消费者（落在 andromeda_auto_loop.py）

新增 `_loop_consume_derivatives()`，挂进 `run_self_loop()` 的 `_safe(...)` 列表：
- 原子认领：`UPDATE ... SET status='EVALUATED', meta_json(lease_owner/lease_at/attempts) WHERE suggestion_id=(... source_type='RESEARCH_DERIVE' AND status='PENDING' AND priority<=3 ORDER BY priority,created_at LIMIT 1)`，rowcount 判抢到与否。
- 节流：距上次 derive 成功 <30min 跳过，单日 ≤8 条，每轮 ≤1 条；`document.hidden` 类的省资源原则对齐。
- 三重去重：`.trae/skills/<slug>` 已存在 / 衍生日志已有 / 同 prop_id implementation 已有 → REJECTED 或跳过。
- 复用 `engines/ai_skill_deriver_engine.py` 的 `derive_skill_via_local_ai()`(L132) 与 `write_and_validate_skill()`(L257，自带 frontmatter 校验) 产出 Skill 草案。
- 成功 → 写 `mt_research_implementations`(artifact_type=skill_draft) + 建议项 `DEPLOYED`；Ollama 离线等可重试错误保留 EVALUATED、attempts+1；≥3 次/无价值 → `DEFERRED`。
- skill_deriver 内部连第三个库 `engines/app.db`，消费者状态必须用本文件的 `database/app.db` 连接写回。全包 `_safe` 隔离。

### 1C. STARTED 研究提案收口（andromeda_research.py）

新增 `close_research_proposal(prop_id, artifact)`，由 1B 草案 DEPLOYED 成功后调用：
- 硬闸：仅 `sensitivity='routine'` 且 `dev_gate_flow_id` 非空自动收口；sensitive/major 不碰。
- 用 `mt_ir14_dev_flow.py` 的官方 `transition()` 按合法边逐边走 `STEP_1→…→FINAL_DONE`（参考已有 `AUTOFIX-DAEMON_DEAD-*` 自主走全链先例），每边填轻量自动字段；遇非法跳边(MT_IR_D2)不强推，置 SKIPPED 交人工。
- 到 FINAL_DONE → flow `final_status='DONE'` + 提案 `status='DONE'`；幂等。
- 历史 backlog：一次性子命令仅处理 `flow_id LIKE 'flow_research%'` 且提案已 DEPLOYED 的流，**不触碰其他 810 条 OPEN 流**。

### 1D. 版本回归 SSOT

- `server_real_db.py` `get_version_info()`(L7652) 与 `_get_andromeda_state()`(L9851) 以 `core.version_source.get_system_version()` 为准；changelog 的 to_version 改存为独立字段 `rule_change_latest`，不再冒充系统版本。去掉 render 的 'v22.3.2'/'23.0.0' 字面兜底。
- `index.html` 版本处改为服务端传入的真实 VERSION。
- 修复 `ai_engines/rules_engine/rule_db.py`：DDL 与 `insert_rule_changelog()` 改真实列名（去 rule_file/change_diff/proposer/effective_at，补 action/target_table/risk/pre_check_passed/execution_*）；DB 解析把 `database/app.db` 提为第一优先。

---

## 阶段 2 · 首页/全站体验（克制 3 项，不加轮询/不引新色值）

1. 全站 `templates/base.html` 顶部状态条 `.hl-status` 内追加：系统版本（`d.version`）+ 待修复 `🔧N`（`evo_repair_pending>0` 红色）+ 衍生 `🧬M`；在既有 fetch 回调加约 10 行赋值。`admin_app/base.html` 同步补版本显示。
2. `index.html` 生态条在现有 6 徽章一排基础上增「待修复」徽章，`data-evo-field="evo_repair_pending"`（复用 andromeda-beautify.js 已有通用绑定，无新 JS）；闭环上线后该值自然归零。
3. 页脚版本号实时取 VERSION，与状态条一致。沿用既有 Andromeda/Element CSS 变量。

---

## 阶段 3 · SA 终审脚本待命（新增，不在此阶段执行）

**新增 `flask-app/scripts/ops/v23_upgrade_finalize.py`**（VIKEY 在场时由 SA 运行）：
1. 复用 `core.services.vikey_api.get_vikey_api().detect()` 实时探测绑定 wuchenghao15 的 VIKEY；无 VIKEY 立即 fail-closed 退出。
2. UPDATE changelog：`approved_by_7step=1, sa_final_decision='立即适配', sa_vikey_verified=1, pre_check_passed=1, execution_status='success', executed_at=now, pipeline_id=flow_id`。
3. 写 `mtscos_version_history`（列以执行时 PRAGMA 实测为准：version/major/minor/patch/release_channel/parent_change_id/change_summary/git_tag 等）。
4. 同一时刻写 `flask-app/VERSION=v23.0.0` → 读回校验（readback）→ 记录 git commit hash。
5. 提示 SA 执行单一升级提交（message 带 flow_id）与 `git tag -a v23.0.0`（一 tag 一 commit，V-03），再 push commit + tag。
6. 降级（VERSION 减小）触发 V-06：必须再次 VIKEY，脚本拒绝自动降级。

---

## 阶段 4 · 部署加固

### 4a. launchd 收敛（文件 AI 可改；launchctl 命令 SA 终端执行）
- 保留：`com.mtscos.flask8888.plist`（主）、`com.mtscos.phase_regression.plist`（900s 回归，不碰 8888）。
- 禁用：`com.mtscos.server8888.plist` → 重命名 `.disabled`（wrapper 已删，可回滚）。
- 改写 `com.mtscos.sync-keepalive.plist` 调用脚本：删除 `kill -9 $(lsof -ti :8888)` 与自行 nohup 拉起；健康失败只 `launchctl kickstart -k gui/$(id -u)/com.mtscos.flask8888` + 记日志。端口归属唯一。
- SA 执行 bootout/bootstrap/print 序列（计划执行时给出完整命令），验证：`launchctl list` 无 server8888、8888 单 LISTEN、health 200、观察 30min 无互杀。

### 4b. tri_sync.sh 跨 major 守卫 + host 修正
- 修正变量：`MINI_HOST=100.106.220.96`、`MINI_FLASK=~/MTSCOS_AI_Project/flask-app`（DB 路径按 Mac mini 实际 `engines/app.db` 复核）。
- 在变量定义后新增 `assert_version_compatible()`：读本地与远端 `flask-app/VERSION`，任一读不到 fail-closed；major 不同则 abort DB rsync（git 与本地 shadow 快照不加守卫——源码经 git 传播正是升级途径）；唯一逃生口 SA 设 `MTSCOS_ALLOW_MAJOR_SYNC=1`。在 `db/all` rsync 段开头调用，双向一次性挡住。

---

## 阶段 5 · 三端发布顺序

1. **开发机**：阶段 0-2 全部完成、VERSION 仍 v22.2.0 时单机验证通过。
2. **SA 终审**（VIKEY）：跑 finalize → v23.0.0 + tag + push。
3. **launchd 收敛**：SA 执行命令并观察 30min。
4. **Mac mini**：经 git 拉代码（守卫不拦 git）→ 跑同一 v23 迁移脚本 → VERSION 一致化（changelog 以主库为准，避免双写分叉）。
5. **公网**：health/state 外网核验；反向验证守卫（mini 仍 v22 时 `tri_sync.sh db` 必须 abort）；观察 24h：待修复归零、DERIVE 节流产出（≤8/日）、research flow 正常 DONE、无新增 MT_IR_D2。

## 端到端验证（开发机，不碰 launchctl）

```bash
# 语法
python3 -m py_compile engines/ai_smart_mount_engine.py engines/andromeda_auto_loop.py \
  engines/andromeda_research.py ai_engines/rules_engine/rule_db.py scripts/migrations/v23_0_0_baseline.py
# 迁移幂等(跑两次)
python3 scripts/migrations/v23_0_0_baseline.py
# 单跑一轮自演化, 确认各步 _safe 隔离不炸
python3 engines/andromeda_auto_loop.py
# 闭环结果
sqlite3 database/app.db "SELECT source_type,status,COUNT(*) FROM mt_ai_suggestion_pool
  WHERE source_type IN ('DAEMON_REPAIR','RESEARCH_DERIVE') GROUP BY 1,2;"
sqlite3 database/app.db "SELECT process_name,status FROM mt_daemon_registry WHERE status IN('FAILED','REPAIRING');"
# 版本/演化 API + 首页
curl -s http://127.0.0.1:8888/api/andromeda/state | python3 -m json.tool | grep -E 'version|evo_'
# 浏览器: 首页 7 徽章一排 + 待修复, 内页状态条版本号
```
预期：6 个真死 daemon 被重启回 RUNNING/建议 DEPLOYED，3 孤儿 DEFERRED；evaluated_at 报错消失；API 系统版本=VERSION 真实值、规则版本另列；DERIVE 节流产出草案。

## SA 专属动作（AI 不代做）

VIKEY 终审与三治理字段置位 · VERSION 落定提交与 v23.0.0 tag/push · 全部 launchctl 命令 · 跨 major 同步豁免 · 任何降级。

## 文件清单

修改：`flask-app/VERSION`(终审时) · `ai_engines/rules_engine/rule_db.py` · `engines/ai_smart_mount_engine.py` · `engines/andromeda_auto_loop.py` · `engines/andromeda_research.py` · `server_real_db.py` · `templates/index.html` · `templates/base.html` · `templates/admin_app/base.html` · `_entry_wrappers/tri_sync.sh` · `~/Library/LaunchAgents/com.mtscos.sync-keepalive.plist`(改) · `com.mtscos.server8888.plist`(改名 .disabled)

新增：`flask-app/scripts/migrations/v23_0_0_baseline.py` · `flask-app/scripts/ops/v23_upgrade_finalize.py`

## 风险与回滚

- 活库 2.3GB：迁移全部幂等 `IF NOT EXISTS`/PRAGMA 守卫，不做事务性 DDL，升级前留影子快照。
- 6 个真死 daemon 重启失败不影响主服务（建议项保留 PENDING 重试，超预算 DEFERRED）。
- 保留 `server8888.plist.disabled` 与升级前 DB 快照；回滚 = VERSION 回 v22（触发 V-06，须 SA VIKEY）+ plist 改回。
