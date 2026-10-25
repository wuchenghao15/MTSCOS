# MTSCOS 法案: 五节点同步协作与共赢方针法案

| 元数据 | 值 |
|---|---|
| 法案编号 | BILL-20261025-NODESYNC |
| 类型 | 基础设施协作法案 |
| 类别 | 架构治理 / 存储与同步 / 中心协作 |
| 提案人 | super_admin_wuchenghao15 |
| 起草 | 立法委员会 × 基础设施中心 × AI 引擎中心 × 备份中心 |
| 表决 | EigenFlux 5人磋商 5/5 通过 |
| 状态 | ENACTED (颁布生效) |
| 颁布日 | 2026-10-25 |
| flow_id | flow_fnos_nas_integrate_20261025 |

---

## 第一章 总则 — 五节点定位

**第一条 (节点名录)** MTSCOS 生产协作网由五节点组成，各节点定位如下，任何人不得擅自变更节点角色：

| 节点 | LAN / Tailscale 地址 | 角色 | 核心职责 |
|---|---|---|---|
| hulk-macmini (mini) | 192.168.31.246 / 100.106.220.96 | **热层生产** | Flask :5001 主服务、主库写入、51 daemon 引擎、SA 双密钥认证 |
| hulk-server | 192.168.31.103/.104 / 100.100.244.47 | **算力容器** | Docker 容器化（巡检 daemon、只读查询、AI 推理）、mini 卸压分流 |
| hulk-nas-fnos (飞牛) | 192.168.31.57 :5593(SSH)/:5666(web) | **冷层存储** | 16TB /vol1：DB 快照冷备、历史归档外迁、滚动保留策略 |
| 开发机 (MacBook Pro) | 192.168.31.90 / 100.121.98.15 | **开发副本** | 代码开发调试、本地零 token 推理、本地库与生产库结构对齐 |
| mtos.site | Cloudflare Tunnel → mini | **公网入口** | 唯一公网门户，`/`+`/index` 渲染冰山主页 200 |

**第二条 (协作总方针)** 五节点关系为「分工协作、能力互补、数据有序流动、故障互为备份」，禁止任何节点各自为营、信息闭塞、闭门造车。

**第三条 (数据主权)** 主数据源唯一为 mini `flask-app/database/app.db`（热层写入）。其余节点仅持有只读副本或冷备快照，禁止反向写入主库。

## 第二章 代码同步协作 (Git / GitHub / Gitee)

**第四条 (三方托管)** 代码以 GitHub (`wuchenghao15/MTSCOS`) 为主仓、Gitee 为镜像仓，本地与 mini 为工作副本。

**第五条 (同步方向与顺序)** 代码流动只允许：`开发机/mini (commit) → GitHub (origin main) → Gitee (镜像) → mini (pull)`。跨节点直推必须经 GitHub 中转，禁止双向漂移。

**第六条 (§14 铁律挂钩)** 所有 commit 必须携带已注册且未 DONE 的 `flow_id`（pre-commit hook 强制），push 前 `mt_dev_flow_session.final_status` 必须 DONE（pre-push hook 强制）。无 flow 的代码不得入三方仓。

**第七条 (force push 约束)** force push 仅允许两种场景：① 历史重写（filter-repo）后镜像仓重建；② SA 终审批准的仓库修复。主仓 main 日常禁止 force push。

**第八条 (mini 拉取纪律)** mini 工作区有改动时 pull 前必须 `git stash → pull → stash pop`；冲突不得静默丢弃，必须人工裁决或回滚。

**第九条 (节点接入)** 新节点（如 hulk-server、飞牛 NAS）接入协作网必须：SSH 免密 key 部署 → mt_storage_nodes 注册 → 心跳接入 → 职责分配 → 审计备案，五步缺一不可。

## 第三章 存储与备份协作 (备份中心 × 飞牛 NAS)

**第十条 (冷热分层)** mini 仅保留热数据；历史归档（Archive/Backups）必须外迁 NAS `/vol1/mtscos_nas/cold_data/`；DB 快照存 NAS `/vol1/mtscos_nas/backup_db/`。

**第十一条 (快照三步法)** DB 冷层快照必须遵守：① mini 端 `PRAGMA wal_checkpoint(TRUNCATE)` 落盘 → ② rsync over SSH (端口 5593) 传输 → ③ NAS 端 VACUUM 瘦身。禁止在 mini 本地做全量 VACUUM INTO（35G+35G 空间爆炸教训）。

**第十二条 (滚动保留)** NAS 端 DB 快照滚动保留最近 7 份，超限自动清理；旧快照删除前必须确认最新一份 integrity_check 通过。

**第十三条 (备案强制)** 每次快照/外迁/告警必须写 `mt_backup_log`（NAS_COLD_SNAPSHOT / NAS_NODE_ALERT / CORPS_HANDOVER_FILING 等动作码），无备案的备份视为未发生。

**第十四条 (断连告警)** 任意节点连续 3 次探活失败必须触发 NAS_NODE_ALERT 告警备案；恢复后必须写 RECOVERY 记录。

**第十五条 (空间红线)** 任意节点磁盘使用率 ≥ 90% 触发预警并启动清理/外迁；≥ 95% 禁止产生新的大文件写入（含 VACUUM/快照）。

## 第四章 任务大厅与 13 中心协作

**第十六条 (中心挂钩义务)** 全部 13 中心必须挂钩任务大厅：自动监听 QUEUED 新任务 → 按领域关键词 + 人力能力自动认领对口任务 → 完成后自动结案。禁止中心不认领、错认领、认领不结案。

**第十七条 (认领归属)** 任务认领以领域关键词匹配为准（如教育类→教育题库中心、AI 引擎类→AI 引擎中心、前端美观类→前端设计中心、立法类→立法委员会）。关键词撞车时以专属领域词优先。

**第十八条 (结案四件套)** 任务结案必须完成：① deliverable 结构化产出（研究方法/实测数据/发现/必须）→ ② 上报 AI 脑库（mt_ai_brain_feed_log, feed_target=center_hall_hook:中心名）→ ③ 备份中心备案 → ④ mt_center_hook_log 留痕（幂等去重）。四件套缺一视为未结案。

**第十九条 (跨团队协作频道)** 每个研究方向自动开通跨团队协作频道（📚 频道，主持团队为对口中心），共享知识、想法、必须及猜想。

**第二十条 (研究院下沉)** 研究院必须定时 + 随机下沉一线主动发现缺口、进化方向、bug 与不足，自动回灌任务大厅，禁止成为功能孤岛。

**第二十一条 (维护部队定位)** 维护部队仅负责任务合法性、完整性、无污染源校验保护，不承担任务大厅执行者角色；任务由各中心自动认领并执行。

## 第五章 AI 推理与算力协作 (mini × hulk-server)

**第二十二条 (算力分工)** 2vCPU 以上的重算力任务（容器化巡检、只读查询、AI 推理）优先由 hulk-server Docker 承担；mini 专注 Flask 服务与 daemon 调度。

**第二十三条 (容器化规范)** hulk-server 容器必须：`--restart unless-stopped` + 命名前缀 `mtscos-` + 日志 max-size 5m 滚动 + 数据挂载 /opt/mtscos/。

**第二十四条 (AI 推理零 token 原则)** 本地推理（Ollama）优先跑在 hulk-server（:11434），mini 与各中心 daemon 远程调用；网络知识仅作辅助补充。能本地解决的不调外部 API。

**第二十五条 (Tailscale 组网)** 全部节点必须接入 Tailscale tailnet（mini=100.106.220.96, hulk-server=100.100.244.47, 开发机=100.121.98.15），跨网访问一律走 tailnet IP，SSH key 免密优先，禁止明文密码落盘脚本。

## 第六章 约束与罚则

**第二十六条 (禁令清单)**
- 禁止绕过 §14 IRON_RULE 12步骤开发任何节点协作代码
- 禁止在节点间私建未备案的数据通道
- 禁止删除/覆盖 NAS 冷层快照（滚动清理器除外）
- 禁止 mini 满盘时强行 VACUUM INTO 本地
- 禁止向主库反向写入只读副本数据
- 禁止密码明文写入代码/日志/临时脚本（expect 密码段用后即删）

**第二十七条 (违反处理)** 违反本法案 → 写 `mt_iron_rule_violations`（不可删除）→ 投喂 EigenFlux 磋商 → 上报 SA 终审。

**第二十八条 (生效与修订)** 本法案自颁布即生效。修订须经 7 步审批 + EigenFlux 表决 + SA 终审，与《规则治理与一致性规范》同源治理。

---

**附: 五节点协作链路图**

```
                ┌──────────────────────────────────────────────┐
                │              mtos.site (公网入口)              │
                │         Cloudflare Tunnel → mini :5001        │
                └───────────────────────┬──────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │                       hulk-macmini (热层生产)                   │
        │        Flask :5001 + 主库写入 + 51 daemon + SA 双密钥           │
        └───┬──────────────────┬───────────────────────┬────────────────┘
            │ rsync over SSH    │ Docker 算力分流        │ git push/pull
            │ (checkpoint→冷备)  │ (巡检/只读/Ollama)     │ (§14 flow_id)
   ┌────────▼────────┐   ┌──────▼──────────┐     ┌──────▼──────────┐
   │ hulk-nas-fnos   │   │ hulk-server      │     │ GitHub (主仓)    │
   │ 16TB /vol1      │   │ 100.100.244.47   │     │  → Gitee (镜像)  │
   │ 冷层快照+归档    │   │ mtscos-patrol    │     └──────┬──────────┘
   │ 滚动保留 7 份    │   │ datasette 只读   │            │ pull
   └─────────────────┘   │ mtscos-ollama    │     ┌──────▼──────────┐
                         └──────────────────┘     │ 开发机 (开发副本) │
                                                  └─────────────────┘
        任务大厅 ⇄ 13 中心 (自动认领→结案→脑库→备份备案)
```
