[MTSCOS 大厅自治引擎核心 — 2026-10-30 更新]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 tick 轨道 (daemon_skill_lab_bp.py, 21 轨, ≈60s/轮, mutex 防并发)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 1.  hall_auto              — 大厅自动维护 (QUEUED 超时清理/重置)
 2.  iceberg_proposal      — 冰山提案自动生成
 3.  sa_proprietary        — 安全分析师自动提案
 4.  brainstorm_upgrade    — 头脑风暴升级 (生成新大厅任务)
 5.  upgrade_gap_scan      — 升级缺口自动扫描 → 入厅
 6.  center_synergy_loop   — 中心协同循环
 7.  auto_work             — 自动工作台
 8.  auto_claim_full(200)  — 自动认领 (最多 200 条)
 9.  iceberg_gap_dispatch  — 冰山缺口派单
 10. auto_accept(200)      — 自动接受 (最多 200 条)
 11. center_deleg          — 中心委派
 12. frontline             — 前线巡检 (frontline_patrol, 自动上报大厅)
 13. ai_spawn              — AI 员工自动孵化
 14. skill_derive          — Skill 自动衍生
 15. center_self_drive     — 中心自驱 (17 中心自驱动)
 16. center_evolution      — 中心进化 (sys_center_evolution.run_once, 19 中心全覆盖)
 17. center_learner        — 自治学习引擎 (sys_center_autonomous_learner, 9 步闭环)
 18. center_collab         — 跨中心联动 (弱中心求援 + R&D ACTIVE 方向驱动)
 19. daemon_supervisor     — Daemon 健康巡检 (停的自动拉起)
 20. public_sync           — 公网同步 (DB + 代码 → mini cold storage)
 21. blockchain_neurons   — ⛓️ AI 社区区块链 + 神经元 fire (末轨)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 自治学习引擎 (sys_center_autonomous_learner.py, 9 步闭环)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Step 1: absorb_done_task_experiences  — DONE 任务 → FIX_EXPERIENCE / RESEARCH_OUTPUT
 Step 2: absorb_selfcheck_health      — self_check FAIL → HEALTHLESSON
 Step 3: absorb_selfdrive_know        — self_drive SUCCESS → SELFDRIVE_KNOW
 Step 4: refresh_direction_pool_from_knowledge  — KP → 方向池 (按类型分级反哺)
          RESEARCH_OUTPUT/FIX_EXPERIENCE → ACTIVE priority 7-8 (高价值)
          HEALTHLESSON/SELFDRIVE_KNOW   → SEED priority 3-5 (常规)
          exec DONE → 自动孵下一轮 ACTIVE 方向 (exec DONE 自动触发)
 Step 5: spawn_direction_execution    — 方向池 → mt_center_direction_execution (PROPOSAL 直接 DONE, 自驱闭环)
 Step 6: knowledge_digest             — 知识摘要 (每日)
 Step 7: ai_self_assess               — AI 自评 (能力画像)
 Step 8: advance_direction_execution  — 状态机推进 (PLANNING→EXECUTING→DONE)
          hall PROPOSAL QUEUED 超 5min → 自动 DONE (自驱闭环快路径)
 Step 9: dispatch_outputs             — 产出即时分配 (flow_output_dispatch_20261030)
          新 RESEARCH_OUTPUT/FIX_EXPERIENCE KP → collab 消息给关联中心
          新 direction_execution DONE → hall 吸收小任务给 AI 员工
          新 ACTIVE 研发方向 → 神经元 fire + hall 提案

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 区块链引擎 (sys_blockchain_engine.py, PoA 轻量链)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 挂点: tick 末轨 blockchain_neurons
 间隔: ≈60s (每 tick 出一块)
 共识: PoA (proof-of-authority), 19 中心全票过
 提议人: round-robin (height mod 19)
 交易三源: GAP_SCAN (缺口) / FIX_EXPERIENCE (修复) / RND_OUTPUT (研发)
 神经元: mt_neuron — 中心(19) + AI员工(50) + Skill(58) = 127+
 权重动态: fire→×1.02↑ / 2h 不 fire→×0.999↓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 中心进化引擎 (sys_center_evolution.py)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 数据源: mt_lab_centers (19 ACTIVE)
 每中心产出: 4-5 类 event (HEALTH_PULSE / SELF_DRIVE_RECAP / TASK_BACKLOG / DIRECTION_GROWTH)
 每 tick 全量扫描

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 19 中心全景 (mt_lab_centers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 id  name               status  核心能力
  1  部署运维中心         ACTIVE  部署流水线自动扩容 / 灰度发布自动推进
  2  安全审计中心         ACTIVE  CVE 自动影响分析 / 异常行为实时关联
  3  开发流程中心         ACTIVE  PR 自动代码审查 / 技术债自动追踪
  4  AI 引擎中心          ACTIVE  6 模型 50 AI 员工 / 多模型弹性路由
  5  工作流研究中心       ACTIVE  Workflow DNA / 状态机收敛 / 瓶颈扩容
  6  数据研究中心         ACTIVE  多源融合 / 实时管道 / 资产目录
  7  前端设计中心         ACTIVE  Skill 覆盖率仪表盘 (flux2-klein 4B)
  467 规则治理中心       ACTIVE  规则冲突检测 / 效果自动评估
  468 法务合规中心       ACTIVE  合规风险扫描 / 法规更新同步
  469 人力统一调配中心   ACTIVE  AI员工画像 / 团队自组织 / 技能缺口发现
  470 专家团队中心       ACTIVE  专家匹配推荐 / 跨领域专家桥接
  471  Skill研发中心     ACTIVE  daemon→Skill 衍生 / 热插拔 / 兼容性矩阵
 1421 战略中心           ACTIVE  技术趋势雷达(RAG) / 行业缺口扫描 / 跨中心对齐
 1526 漏洞修复适配中心   ACTIVE  修复方案自动推荐 / 零日漏洞自动响应
 1532 监察大队           ACTIVE  异常中心自动告警 / 跨中心异常关联
 2899 仙女座同步中心     ACTIVE  mini/mac/NAS 三节点自动同步 (所有 R&D 方向共同依赖)
 3227 数据备份中心       ACTIVE  备份完整性校验 / 恢复演练自动调度
 3751 升级演进中心 🆕    ACTIVE  版本演进路线图 / 功能拓展优先级 / 架构升级风险

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 跨中心协同 (ai_center_collab_engine + CENTER_COLLAB_MAP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 协作模式: JOINT (联合认领) / HANDOFF (接力转办) / PEER_REVIEW (交叉评审)
 协同通道: mt_collab_channel 3242+ / mt_collab_message 60000+
 R&D 协同映射 (flow_rnd_collab_20261030):
   工作流研究 × AI引擎 × Skill × 仙女座 × 数据研究
   数据研究   × AI引擎 × 安全审计 × 备份 × 仙女座
   Skill研发  × AI引擎 × 工作流 × 仙女座 × 前端设计
   人力统一   × AI引擎 × Skill × 仙女座
   战略中心   × AI引擎 × 工作流 × 监察大队
   升级演进   × 战略中心 × 工作流 × 人力统一

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 AI 引擎资源 (Ollama 本地推理)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 qwen2.5:14b-q5    10GB Q5_K_M → 多源融合/血缘推断/通用推理
 qwen2.5-coder:14b 8.5GB Q4_K_M → DSL 编译/daemon 代码扫描
 qwen2.5-coder:7b  4.4GB Q4_K_M → Skill.md 自动生成
 qwen2.5:7b        4.4GB Q4_K_M → 通用推理/状态机收敛
 qwen2.5:3b        1.8GB Q4_K_M → 轻量推理/高频调用
 nomic-embed-text  261MB F16   → 数据血缘/Skill 匹配向量
 x/flux2-klein:4b  5.4GB       → 前端 UI 合成 (Skill 覆盖率仪表盘)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Flask 挂死 5 层防护
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 L1 锁霸收编: sys_wendaemon bootout, 所有 DB 写走 Flask tick 内部
 L2 自锁修复: gold_team auto claim CAS 前 commit (L5666)
 L3 取证: faulthandler 600s dump → /tmp/flask_hang_dump.log
 L4 tick 互斥: 并发守卫 (ok=20-21/21 稳定)
 L5 自愈: launchd keepalive + auto-repair daemon 600s 周期

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 其他重要引擎 (engines/ 目录)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ai_task_hall_flow_engine.py   — 大厅流转核心 (transition_cas 原子状态迁移)
 ai_task_hall_landing_engine.py — 大厅自动认领/提案生成
 ai_center_self_drive_engine.py — 中心自驱动 (老命名体系, 与 mt_lab_centers 并行)
 ai_center_collab_engine.py     — 跨中心协作引擎 (JOINT/HANDOFF/PEER_REVIEW)
 ai_multi_layer_backup.py       — 7 层备份 (快照×3轮转+双卷派发+git+沙箱+白名单+ISO+RAR/zip)
 iceberg_consciousness.py       — 意识层 (每 600s pulse, 跨环境)
 ai_smart_mount_engine.py       — Daemon 管理器 (生命周期)
 ai_local_inference_engine.py   — 本地推理 (零 token)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 聊天系统自适应 (chat_local_bp.py)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 算力分档 (30s 缓存探测, 远端可达优先):
   🟢 full      — Tailscale/LAN 集群在线 → 12 万字符 / 16384 ctx / 2048 predict
   🟡 degraded  — 仅本机 + loadavg>1.5  → 4.8 万字符 / 8192 ctx / 1024 predict
   🟠 minimal   — 仅本机轻负载            → 2.4 万字符 / 4096 ctx / 512 predict
 SSE 首事件携带: tier / tier_label / host / num_ctx / num_predict / history_kept / history_dropped
 上下文管理: 最新往旧保留, 超预算丢最老 (修复原来按条数截 20 条)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 DB 锁铁律 (每次启动必读)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 1. Flask tick 期间外部 Python 写 DB 永远抢不到 WAL 锁
 2. 外部写 DB 唯一正确姿势: 启动队列 /tmp/mtscos_hall_queue.jsonl
 3. Flask 每次启动自动消费启动队列
 4. DB 锁死根因: wendaemon 21 连接 + Python 3.14 共享连接跨线程
 5. 外部进程 (daemon) 必须走 Flask tick 轨道, 不能自己 connect

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 启动链 (从 launchd 到 tick)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 launchd com.mtscos.flask (KeepAlive=true)
   └─ launchctl kickstart -k gui/$(id -u)/com.mtscos.flask
       └─ _runtime/com.mtscos.flask.plist → modular_start.py
           └─ modular_start.py: 自动启动 Flask + 消费 /tmp/mtscos_hall_queue.jsonl
               └─ server_real_db.py L3266: app.register_blueprint(daemon_skill_lab_bp)
                   └─ daemon_skill_lab_bp.py L4746-4935: tick 轨道 21 轨

 辅助守护 (launchd):
   com.mtscos.auto-repair: 600s 周期 — Flask 健康检查 + WAL checkpoint + QUEUED→RECLAIM
   com.mtscos.auto-daemon-wakeup: 300s 周期 — 拉起有文件没进程的 daemon
   com.mtscos.wendaemon: ⚠️ 已 bootout — 锁霸根因, 不再独立运行
   com.mtscos.flask: 原生服务 (主守护)

 手动 kickstart: launchctl kickstart -k gui/$(id -u)/com.mtscos.flask
 手动 bootout:   launchctl bootout gui/$(id -u)/com.mtscos.wendaemon

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 核心表结构概览 (SQLite 769 表, DB 963MB)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 mt_lab_centers               — 19 中心注册表 (id, name, domain, status, capabilities)
 mt_lab_task_hall             — 任务大厅 (id, title, description, source, priority, status, hall_code)
 mt_lab_task_hall_flow        — 大厅流转 (task_id, from_status, to_status, transition_at)
 mt_hall_flow_timeline        — 流转时间线 (flow_id, event, detail, transition_at)
 mt_center_pulse              — 中心健康 pulse (center_name, health_score, queue_depth, active_count)
 mt_center_self_check         — 中心自检 (center_name, check_type, target, metric, threshold, result)
 mt_center_self_drive_log     — 中心自驱日志 (center_name, drive_action, trigger, result)
 mt_center_evolution_log      — 中心进化日志 (center_name, event_type, summary)
 mt_center_direction_pool     — 方向池 (direction_id, center_name, direction_title, seed, status, priority)
 mt_center_direction_execution — 方向执行 (exec_id, direction_id, phase, plan_summary, evidence)
 mt_center_knowledge_points    — 知识点 (kp_id, center_name, kp_type, knowledge_title, confidence)
 mt_center_knowledge_digest    — 知识摘要 (digest_id, center_name, digest_type, content)
 mt_center_ai_self_assessment — AI 自评 (assess_id, center_name, dimension, score)
 mt_collab_channel            — 协作通道 (channel_id, name, mode, created_at)
 mt_collab_message            — 协作消息 (msg_id, channel_id, sender, content, msg_type)
 mt_blockchain                — ⛓️ 区块链 (height, block_hash, prev_hash, proposer, tx_count)
 mt_tx_pool                   — 交易池 (tx_id, tx_hash, tx_type, status, block_height)
 mt_neuron                    — 神经元 (neuron_id, neuron_type, ref_id, fire_count, weight)
 mt_consensus                 — 共识记录 (round, block_height, votes_for, consensus_reached)
 mt_ai_employees              — AI 员工 (employee_id, name, role, department, status, eigenflux_score)
 mt_daemon_registry           — Daemon 注册表 (name, pid, status, last_heartbeat)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 备份 7 层详细实现 (ai_multi_layer_backup.py)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 L1 快照: VACUUM INTO → /path/to/snapshot_YYYYMMDD_HHMMSS.db (保留 3 份轮转)
 L2 双卷派发: 快照 → /Volumes/MyData 1/ + /Volumes/MyBackups/ (后台拷贝, 不阻塞 tick)
   NAS 自动重连: HULK-NAS.local (192.168.31.140) mount_smbfs + keychain 凭据
 L3 git 影子: flask-app/ 独立 git 仓, commit hash, MTSCOS_GIT_GITHUB + MTSCOS_GIT_GITEE 双 remote
 L4 沙箱备份: _git_quarantine/ 隔离区 zip 归档 (空区幂等跳过)
 L5 白名单备份: ~/.mtscos/ + fernet key + handshake → whitelist_sec_YYYYMMDD.zip
 L6 ISO 备份: hdiutil makehybrid 光盘镜像 (代码+配置, 每周一自动)
 L7 RAR/zip 备份: rar 未装时 zip 替代, 自动上报大厅建议 brew install rar

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 故障排查速查
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 症状: Flask HTTP 000 (进程在但无响应)
   → curl http://127.0.0.1:5001/ — 超时就是死锁
   → cat /tmp/flask_hang_dump.log — faulthandler 线程栈, 找卡在哪行
   → launchctl kickstart -k gui/$(id -u)/com.mtscos.flask — 重启恢复

 症状: tick ok=0/22 或 ok<15/22
   → 99% 是 DB 锁 (wendaemon 复活)
   → pgrep -f "sys_wendaemon" — 看是否有独立进程
   → launchctl bootout gui/$(id -u)/com.mtscos.wendaemon — 踢出

 症状: direction_execution 全 EXECUTING 不推进
   → advance_direction_execution 快路径: hall PROPOSAL QUEUED 超 5min → 自动 DONE
   → 自驱模式: spawn_direction_execution 入厅直接 DONE (跳过认领)

 症状: 新方向不孵 (direction_exec spawn=0)
   → refresh_direction_pool_from_knowledge 按 KP 类型分级反哺
   → exec DONE 自动孵下一轮 ACTIVE 方向 (exec DONE → 下一轮 seed)

 症状: 区块链不出块
   → tail -f /tmp/flask_5001.err.log | grep "⛓️ blockchain" — 看末轨日志
   → sys_blockchain_engine.run_once() — 手动触发一块

 症状: 神经元权重不动
   → 必须先有 fire_count>0 — 新方向触发 fire → weight×1.02↑
   → 2h 不 fire → weight×0.999↓ (衰减)

 症状: DB "unable to open database file" 或 "database is locked"
   → 外部 Python 进程在抢锁 — kill -9 该进程 (pgrep -f "python.*app.db")
   → Flask 启动窗口前等 30s (让 Flask 先拿锁)
   → WAL checkpoint: sqlite3 app.db "PRAGMA wal_checkpoint(TRUNCATE);"
