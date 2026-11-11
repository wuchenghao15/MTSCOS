[AI 引擎中心 — 2026-10-30 更新]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 本地推理栈 (Ollama) — 主库
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 qwen2.5:14b-q5    10GB Q5_K_M → 数据血缘/SQL 生成/多源融合
 qwen2.5-coder:14b 8.5GB Q4_K_M → DSL 编译/daemon 代码扫描
 qwen2.5-coder:7b  4.4GB Q4_K_M → Skill.md 自动生成
 qwen2.5:7b        4.4GB Q4_K_M → 通用推理/状态机收敛
 qwen2.5:3b        1.8GB Q4_K_M → 轻量推理/高频调用
 nomic-embed-text  261MB F16   → 向量嵌入
 x/flux2-klein:4b  5.4GB       → 前端 UI 合成

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 AI 员工中心 (mt_ai_employees) — 50 ACTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 表字段: employee_id / name / role / department / status (ACTIVE/STOPPED/RETIRED) / eigenflux_score / created_at / updated_at
 角色域: 安全/运维/AI引擎/前端/数据/后端/产品/教育/法务/人力/战略
 调度: tick 第 13 轨 ai_spawn — 自动孵化新员工 / 停用闲置员工
 区块链神经元: AI_EMPLOYEE 类型, fire_count>0 时权重×1.02↑, 2h 不 fire×0.999↓
 EigenFlux 网络: 多专家辩论架构 (架构专家/安全专家/开发专家/产品专家/教育专家)
 EigenFlux-架构专家 63574+ 条辩论记录 (mt_lab_deliberations)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Ollama 集群配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 主库: 127.0.0.1:11434 (localhost)
 集群探测: os.environ.get('MTSCOS_AI_CLUSTERS') → comma-separated list
 弹性路由: galaxy_ai_model_router.py — 按模型选节点 (coder→哪个节点有 coder)
 chat 自适应: chat_local_bp.py — 30s 缓存探测, 远端可达优先 (详见 engines/README.txt)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 核心引擎功能说明 (ai_engines/ 目录)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ── 本地推理层 ── (零 token, Ollama HTTP)
 ai_local_inference_engine.py  — Flask 内部推理 API /api/infer
 ai_local_rag.py               — 本地 RAG 管道 (向量嵌入 → 检索 → 生成)
 ai_ollama_engine.py           — Ollama 客户端 (chat/completions, 带超时重试)
 ollama_client.py              — 低级别连接管理 (host/port/model 健康检查)

 ── 协作/协同 ⭐ ── (大厅自治闭环核心)
 ai_center_collab_engine.py    — 跨中心协作: open_collab_task / handoff / join_channel
   挂点: tick 第 18 轨 center_collab + learner Step 9 dispatch_outputs
   数据: mt_collab_channel (3242+) / mt_collab_message (60000+)
 ai_team_collab_engine.py      — 团队内协作 (小组→大厅)
 ai_collaboration_network.py   — 协作网络拓扑 (中心→中心图)
 eigenflux_proactive_engine.py — EigenFlux 主动提案引擎
 eigenflux_broadcast_engine.py — EigenFlux 广播 (新 KP → collab 消息)

 ── 自学习/自升级 ── (learner 消费的能力)
 self_learning_system.py       — 自学习: DONE→KP→方向池→新 exec→新 DONE
 ai_intelligent_upgrade_engine.py — 智能升级: 引擎版本演进决策
 auto_upgrade_system.py        — 自动升级: daemon/engine 版本自动提升
 auto_learning_upgrade.py      — 学习升级: 从历史 DONE 学习升级路径

 ── 业务 Agent ── (大厅任务认领执行者)
 ai_code_generator_agent.py    — 代码生成 (daemon→Skill)
 ai_code_review.py             — PR 代码审查
 ai_devops_agent.py            — 部署流水线自动扩容
 ai_vulnerability_scanner.py   — CVE 影响自动分析
 ai_data_analyzer.py           — 多源融合 / SQL 生成
 ai_hr_agent.py                — AI 员工画像 / 技能缺口发现
 ai_requirement_analyzer.py    — 需求拆解 → Hall PROPOSAL

 ── 监控/运维 ── (自驱闭环保障)
 ai_anomaly_detector.py        — 异常检测 (健康分 < 70 自动告警)
 diagnostics_repair_employee.py — 诊断修复员工 (daemon 停了自动拉起)

 ── _fusion/ 第三方库 (只读, 不修改) ──
 _SimpleMem_fusion/           — 简单记忆 (memory techniques)
 _Hyper-Extract_fusion/        — 超提取 (语义提取)
 _m_flow_fusion/               — M-Flow 管道 (并行工作流)
 _semantica_fusion/            — 语义分析 (Semantica)
 _neo4j-python-pandas-py2neo-v3_fusion/ — Neo4j 图查询

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 大厅自治闭环 (ai_center_collab_engine)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 协作模式: JOINT (联合认领) / HANDOFF (接力转办) / PEER_REVIEW (交叉评审)
 协同引擎: mt_collab_channel 3242+ / mt_collab_message 60000+
 R&D 协同映射:
   工作流研究 × AI引擎 × Skill研发 × 仙女座 × 数据研究
   数据研究   × AI引擎 × 安全审计 × 数据备份 × 仙女座
   Skill研发  × AI引擎 × 工作流 × 仙女座 × 前端设计
   人力统一   × AI引擎 × Skill研发 × 仙女座
   战略中心   × AI引擎 × 工作流 × 监察大队
   升级演进   × 战略中心 × 工作流 × 人力统一

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 聊天系统自适应 (chat_local_bp.py)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 算力分档 (30s 缓存探测):
   🟢 full      — Tailscale/LAN 集群在线 → 12 万字符 / 16384 ctx / 2048 predict
   🟡 degraded  — 仅本机 + loadavg>1.5  → 4.8 万字符 / 8192 ctx / 1024 predict
   🟠 minimal   — 仅本机轻负载            → 2.4 万字符 / 4096 ctx / 512 predict
