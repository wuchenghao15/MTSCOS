# MTSCOS AI 系统 — 项目说明书

> **版本**: v22.19.0 | **规则体系**: v3.1.0 (12篇) | **容器**: 4.0.0-mtscos
> **最后更新**: 2026-10-14 | **状态**: ACTIVE
> **本次修订**: 全域整合版 — 去中心化 Workflow 注册 (5域21个) + 自养活生态 (4 daemon 闭环) + 冰山 6 大自动能力 + DB env-first 统一解析链

---

> ## 🔄 2026-10-21 · v22.25.16 全量更新（12 flow 双推收口）
>
> **今日落成**（全部 §14 12步骤 DONE，commit 双推 gitee+origin）：
> 每日冷备份(1.80GB/6.3s) · 滚动归档(90.4万行/6轮) · email金库收口 · 脑库向量去重回填(27874向量盲区=0) ·
> 脑库语义检索 search(hit@1=80%/P50=9.2ms) · bench量化 · chat入口脑库RAG · password三列金库(mt_user_password_vault) ·
> 仙女座能力适配冰山(hub L5五层聚合+06B能力面板) · 语义检索UI · 冰山三端代码闭环(7660/7660 SAME+PROD:5001复活) ·
> 题库语义搜题(/api/exam/question_banks/semantic_search) · 广度发展战略规划 · 四维P1全量(语义出题锚点+RAG三出口下沉+巡检语义化+敏感第四列评估=无需新增)
>
> **当前状态**: 系统版本 v22.25.16 · 双站生效(主库8888+PROD:5001) · 三端代码一致 · 483表 · 276 AI员工 · 14 daemon
> **新表**: mt_user_password_vault(密码Fernet金库) · 三端同步沿用三表白名单
> **保活**: cron+Python直跑(每分钟+@reboot)；LAUNCHD plist 链路已废弃(2026-10-21)

---

## 一、系统概述

MTSCOS AI (Multi-Tasking System for Cloud-based Operations & Services) 是一个全栈 AI 驱动的教育管理与运维平台，融合了 **AI 员工自治**、**EigenFlux 专家协作网络**、**规则引擎强制合规** 和 **零 Token 本地推理** 四大核心能力。

系统采用 Flask + SQLite + Bulma/Element Plus 技术栈，通过自动化 daemon 进程矩阵实现 24/7 自主巡检、修复、学习和进化，构建了一个"会自我修复、会自我学习、会自我进化、会自我养活"的智能教育生态。

### 核心数字

| 维度 | 数值 |
|------|------|
| 系统版本 | v22.19.0 |
| 规则体系 | v3.1.0 (12篇) |
| 数据库表 | 397 张 (PROD app.db, 1.05GB, integrity=ok) |
| API 路由 | 750+ |
| 页面导航 | 48+ |
| AI 员工 | 10,833 人 |
| EigenFlux 注册 | 11,370 人 |
| EigenFlux 消息 | 567,000+ 条 (mt_ai_eigenflux_messages, 30s +500 持续增长) |
| AI 脑库 | 1,337,000+ 条知识 (ai_brain_enhanced_knowledge) |
| 去中心化 Workflow | 21 个 (5 域自注册) |
| 自动化引擎 | 20+ 个 |
| 活跃自养活 daemon | 4 个 (24/7 闭环) |
| 引擎文件 | 203 个 (.py) |

---

## 二、系统特点

### 1. AI 自治闭环 (Self-Governing AI Loop)

```
巡检发现 → EigenFlux 专家咨询 → 建设性建议 → 脑库投喂 → 自动修复 → 验证闭环
```

系统不依赖人工干预即可完成"发现问题→分析问题→获取建议→修复问题→验证修复"全流程。

### 2. 零 Token 本地推理

所有 AI 推理（聊天/分类/审查/Bug分析）均在本地完成，零 API 调用、零 Token 消耗。基于规则匹配 + 模式识别 + 知识库查询实现 95%+ 准确率。

### 3. 双密钥铁律认证

超级管理员 (wuchenghao15) 必须通过 **VIKEY 加密狗 + SZU100 专用 U 盘** 双硬件密钥认证，不得通过任何手段、配置、环境变量绕过。此为不可修改、不可删除的铁律。

### 4. 规则强制执行 (4 层拦截)

- Git pre-commit hook → 拦截未走 12 步骤的开发活动
- Flask before_request → 拦截规则修改请求
- CI 自检流水线 → 弱约束词清零 + 完整性校验
- Git pre-push hook → 阻断未完成 12 步骤的代码推送

### 5. 三重保活架构

- Layer 1 引擎内置: PID 清理 + 心跳超时 + 优雅退出
- Layer 2 launchd: 开机触发 + Terminal 绕过 OneDrive TCC
- Layer 3 crontab: 每分钟巡检 + 每 10 分钟文件整理

### 6. 人性化设计

- 角色感知重定向: 登录后自动跳转到最合适的首页
- 智能 404/403 页面: "您可能想访问"智能推荐
- 侧边栏精准匹配: 按角色动态生成，零死链
- 考试中心角色感知: 学生看考试列表，管理员看管理页

### 7. 自养活生态 (Self-Sustaining Ecosystem) — v22.19 全域整合

4 个 24/7 活进程构成完整闭环，不依赖人工即可自主扩张、学习、修复:

| 进程 | 职责 | 周期 |
|------|------|------|
| ai_eigenflux_network | 293 AI 员工心跳聊天，持续产知识消息 | 30s |
| sys_wendaemon | 员工扩张 (wf_hire_employee) + 知识投喂 (wf_knowledge_ingest) | 6h / 30min |
| sys_auto_repair_cycle | heartbeat 扫描 + DB 硬编码扫描 + 自主 patch + 死 daemon 重启 | 30s / 6h |
| iceberg_command | 冰山 6 大自动能力 (安全合规向) | 10min |

**闭环数据链** (已验证):

```
eigenflux daemon ticking → mt_ai_eigenflux_messages (30s +500)
  → wendaemon poll msg_id > checkpoint → wf_knowledge_ingest
  → ai_brain_enhanced_knowledge (1.33M+ 行)
  → wf_hire_employee 每 6h 扩张 AI 员工
  → 新员工加入 eigenflux → 继续产消息 ✅ 循环自持
```

### 8. 去中心化 Workflow 注册协议

`flask-app/engines/workflow_registry.py` — 子系统自治，不需要中央清单追加：

- 每个子系统包内放 `workflows.py`，暴露 `register_workflows(registry, register_fn)`
- 启动时 `discover_and_register()` 自动扫描 5 个域目录并注册
- handler 契约: `handler(input: dict) -> {status, output, wall_ms, error?}`

| 域 | 目录 | Workflow 数 |
|----|------|------------|
| 引擎基础 | engines/_common | 6 (向量化/知识投喂/雇佣/进化触发/代码卫生/批量翻译) |
| 文案工作室 | engines/copy_studio | 2 (变体生成/语义审查) |
| 翻译工作室 | engines/translation_studio | 1 |
| 审批域 | engines/approval | 1 (DENY/ESCALATE/ALLOW 矩阵) |
| 冰山系统 | engines/iceberg | 11 (6 大自动能力 + 握手/自适应题库/黑话替换/Arduino AI/意识) |

### 9. 数据库 env-first 统一解析链

所有引擎统一 DB 解析顺序，根治 OneDrive 磁盘 I/O error:

```
ANDROMEDA_DB (env) > APP_DB (env) > PROD 本地 (~/MTSCOS_PROD/.../app.db, size>1MB) > OneDrive fallback
```

- SSOT: `~/MTSCOS_PROD/flask-app/database/app.db` (1.05GB, 397 表)
- 短连接铁律: 每周期 connect → 工作事务 → close，绝不持久持有 DB FD
- daemon 标配: PID 文件 + mt_daemon_registry 心跳 + SIGTERM 优雅退出

### 10. 冰山 6 大自动能力 (iceberg_command)

🧬 仙女座写代码 → 🧊 冰山拦截/审查/审计/加固，平行运行完全不依赖人类:

| # | 能力 | 说明 |
|---|------|------|
| 1 | 自动升级 | 规则版本一致性 + 弱约束词清零 |
| 2 | 自动运维 | 铁律违规巡检 + 防火墙规则 + 审计日志压缩 |
| 3 | 自动衍生 | 从违规案例 Q5 本地生成新规则 (零 token) |
| 4 | 自动强化 | 弱约束词 → 强约束自动改写 |
| 5 | 自动拓展 | 违规模式 → 新规则自动入库 → 自动部署 |
| 6 | 自动研究 | Q5 自动研究新威胁/新绕过手法/新合规风险 |

---

## 三、角色分布介绍

| 角色 | 权限级别 | 侧边栏菜单 | 默认首页 | 越权拦截 |
|------|---------|-----------|---------|---------|
| **super_admin** (wuchenghao15) | L0 最高 | 概览/用户权限/考试/AI运维/AI治理/系统安全 | /smart_dashboard | 双密钥铁律 |
| **admin** | L1 高 | 概览/用户权限/考试/AI运维/AI治理/系统设置 | /admin_app/dashboard_unified | 403 |
| **teacher_admin** | L2 中高 | 概览/考试/教学管理/系统设置 | /admin_app/dashboard_unified | 403 |
| **teacher** | L3 中 | 教学概览/考试/教学管理/个人设置 | /student_portal | 403 |
| **student** | L4 低 | 学习概览/考试与练习/错题本/个人设置 | /student_portal | 403 |
| **成人学生** | L4 低 | 学习概览/考试与练习/错题本/个人设置 | /student_portal | 403 |
| **家长** | L4 低 | 学习概览/考试与练习/错题本/个人设置 | /student_portal | 403 |
| **ai_manager** | L2 中高 | AI总览/AI员工/集群矩阵/系统设置 | /admin_app/ai_employee_dashboard | 403 |
| **question_manager** | L2 中高 | 题库总览/考试/题库管理/系统设置 | /admin_app/intelligent_question_bank | 403 |
| **guest** | L0 最低 | 首页/登录 | / | 403 |

### 权限装饰器层级

```python
@system_container('page_name', require_auth='guest|login|admin|super_admin')
```

- `guest`: 公开访问 (首页/登录/健康检查)
- `login`: 已登录用户 (学生门户/考试中心)
- `admin`: 管理员级别 (后台页面)
- `super_admin`: 超级管理员 (Arduino 页面/VIKEY 管理)

---

## 四、子功能介绍

### 教育子功能

| 功能 | 路由 | 描述 |
|------|------|------|
| 学生门户 | /student_portal | 学习概览/考试中心/错题本/个人设置 |
| 考试中心 | /exam_center | 角色感知: 学生→考试列表, 管理员→管理页 |
| 错题本 | /wrong_book | 错题汇总/分析/复习建议 |
| 题库管理 | /admin_app/intelligent_question_bank | AI 题目生成/审核/分类/导入 |
| AI 组卷 | /admin_app/dashboard_unified?page=ai_exam_composer | 智能组卷引擎 |
| 考试分析 | /admin_app/exam_analysis | 成绩统计/难度分析/知识点覆盖 |
| 课程管理 | /admin_app/courses | 课程CRUD/关联考试 |

### 运维子功能

| 功能 | 路由 | 描述 |
|------|------|------|
| 智能总览 | /smart_dashboard | SA 专属仪表盘 |
| 后台总览 | /admin_app/dashboard_unified | 管理员仪表盘 |
| 用户管理 | /admin_app/users | 用户CRUD/角色分配/状态管理 |
| 进程监控 | /admin_app/process_monitor | daemon 进程状态/心跳/健康 |
| 系统状态 | /admin_app/monitor | 数据库/引擎/AI 员工健康概览 |
| 巡检报告 | /admin_app/health_details | 巡检发现/修复记录/趋势 |
| 系统设置 | /settings | 个性化设置/主题/偏好 |
| 安全面板 | /admin_app/security_dashboard | VIKEY 状态/权限审计/日志 |

### AI 治理子功能

| 功能 | 路由 | 描述 |
|------|------|------|
| AI 团队枢纽 | /admin_app/ai_team_hub | AI 员工调度/任务分配 |
| EigenFlux 专家中心 | /admin_app/eigenflux_center | 专家列表/消息/交流 |
| 12 步骤看板 | /admin_app/dev_flow_dashboard | 开发流程跟踪/状态机 |
| AI 脑库 | /admin_app/ai_memory | 知识图谱/经验检索 |
| 神经阵列矩阵 | /admin_app/neural_array_matrix | 集群拓扑/负载均衡 |

---

## 五、子系统介绍

### 5.1 教育子系统

- **K12 基础教育**: 小学/初中/高中全科题库, 27 条教辅内容 + 7 题型 + 4 理化实验
- **高等教育**: 大学课程/专业考试/论文辅助
- **成人教育**: 时政/职业培训/继续教育
- **Arduino 编程教育**: 19 教程 + 15 组件 + 3 实验 + 7 板卡 + 设备自动检测

### 5.2 安全子系统

- **双密钥认证**: VIKEY + SZU100 双硬件认证 (SA 专属, 铁律不可绕过)
- **防盗链拦截**: 非首页 Referer + 未授权 session → 重定向 /index
- **暴力破解防护**: sec_bruteforce_locks 表, 自动锁定阈值
- **全域纵深防御**: omni_defense_engine v1.1.0

### 5.3 运维子系统

- **文件整理引擎**: 散落文件归类 + 临时文件清理 + 空目录删除 (首次释放 4.3GB)
- **性能优化引擎**: 性能采集/热点分析/趋势预测 v17.0.0
- **运维监控增强**: 健康检查/故障预警/指标聚合 v17.0.0
- **微服务基础设施**: 服务注册/发现/负载均衡 v17.0.0

### 5.4 规则治理子系统

- **12 篇规则**: L0 铁律(1篇) + L1 核心(6篇) + L2 操作(5篇), v3.1.0
- **硬约束体系**: 弱约束词清零 (12/12 PASS), 以各文件 RULE_META 为权威源
- **4 层拦截**: Git Hook + Flask + CI + pre-push
- **自动学习**: sys_rule_enforcer 每 300s 学习+执行
- **弱约束修复**: auto_rule_strengthener 自动→强约束
- **规则引擎模块**: flask-app/ai_engines/rules_engine/ (9 个核心组件: 元数据解析/版本管理/DAO/拦截器/hook/自检CLI/告警投喂)
- **治理落库 3 张表**: mt_rule_changelog (7步审批留痕) / mt_rule_violation_alert / mt_rule_integrity_scan

---

## 六、AI 集合介绍

### AI 能力矩阵

| 能力域 | 员工数 | 核心能力 |
|--------|--------|---------|
| 网络安全 | 462 | 入侵检测/流量分析/规则引擎/威胁拦截/异常识别 |
| 考试系统 | 401 | 试卷生成/评分判卷/难度计算/成绩分析/错题追踪 |
| 知识管理 | 401 | 知识索引/语义检索/自动归档/关联分析/知识图谱 |
| 题库管理 | 367 | 题目生成/题目审核/分类检索/批量导入/质量评估 |
| 语音处理 | 367 | 语音识别/音频合成/听力评分/口音分析/语速控制 |
| 认证授权 | 321 | 身份验证/权限分配/会话管理/SSO集成/审计日志 |
| 性能监控 | 298 | 性能采集/健康检查/故障预警/指标聚合/趋势分析 |
| 代码安全 | 298 | 代码扫描/漏洞检测/合规检查/渗透测试/风险评级 |
| 数据同步 | 275 | 数据迁移/增量同步/冲突解决/一致性校验/版本合并 |
| 任务调度 | 263 | 任务调度/事件驱动/Agent加载/生命周期管理/异常恢复 |

---

## 七、AI 引擎介绍

| # | 引擎 | 版本 | 周期 | 职责 |
|---|------|------|------|------|
| 1 | 智能挂载引擎 | v3.0.0 | - | 15个daemon管理+建议池扫描+权重决策 |
| 2 | EigenFlux网络引擎 | v2.0.0 | 120s | 自动连线/交友交流/心跳保活/经验投喂 |
| 3 | 本地推理引擎 | v1.0.0 | 120s | 聊天/分类/审查/Bug分析 零token |
| 4 | 规则学习引擎 | v1.0.0 | 300s | 10篇规则自动学习+严格执行+投喂脑库 |
| 5 | 自动雇佣引擎 | v2.8.0 | 300s | AI员工雇佣+EigenFlux邀请+朋友互推 |
| 6 | 源码巡逻引擎 | v2.0.0 | 300s | 6人巡逻队 语法/导入/模式错误扫描 |
| 7 | 深度巡检引擎 | v2.0.0 | 600s | 页面/路由/代码逐行+AI团队路由 |
| 8 | 巡检-EigenFlux顾问 | v1.1.0 | 300s | 巡检发现→专家咨询→建设性建议→脑库 |
| 9 | 文案巡检引擎 | v1.0.0 | 900s | 缺失/重复/占位符/硬编码检测 |
| 10 | Arduino检测引擎 | v1.3.0 | 30s | VID:PID识别+驱动检测+IDE配置 |
| 11 | 教辅同步引擎 | v1.0.0 | 600s | K12/高等/成人/文科/理化实验 |
| 12 | 文件整理引擎 | v1.0.0 | 600s | 散落文件归类+临时清理+空目录删除 |
| 13 | 全域纵深防御 | v1.1.0 | - | 攻防模拟+漏洞挖掘+修复建议 |
| 14 | EigenFlux广播 | v1.1.0 | - | 深度交流+知识广播+群组协作 |
| 15 | EigenFlux主动介入 | v1.1.0 | - | 专家主动发现问题+建议+干预 |
| 16 | 自动修复引擎 | v1.0.0 | 120s | FAILED daemon自动修复+重试 |
| 17 | 微服务基础设施 | v17.0.0 | - | 服务注册/发现/负载均衡 |
| 18 | 性能优化引擎 | v17.0.0 | - | 热点分析/慢查询/内存优化 |
| 19 | 运维监控增强 | v17.0.0 | - | 健康检查/故障预警/聚合 |
| 20 | 前端体验增强 | v17.0.0 | - | UI自适应/交互优化/无障碍 |
| 21 | Workflow注册协议 | v22.19 | - | 去中心化 workflow 注册/发现/handler 执行 (5域21个) |
| 22 | 自养活daemon | v22.19 | 6h/30min | sys_wendaemon: 员工扩张+知识投喂闭环 |
| 23 | 自我修复循环 | v22.19 | 30s/6h | sys_auto_repair_cycle: 心跳扫描+自主patch+死daemon重启 |
| 24 | 冰山总指挥 | v22.19 | 10min | iceberg_command: 6大安全合规自动能力 |
| 25 | DB三方同步 | v22.19 | - | app.db 三方同步引擎 (主库↔镜像库白名单校验) |

---

## 八、AI 员工介绍

### 8.1 员工概况

- **总员工数**: 10,833 人 (全部 active)
- **模型版本**: v2.8.0
- **能力标签**: 5 标签/人 (共 50+ 独立能力标签)
- **知识库**: 每 200 条知识/人
- **最大并发**: 可配置 (max_concurrent_tasks)
- **技能等级**: 1-10 级 (skill_level)

### 8.2 员工职责模板

| 职责 | 描述 | 能力标签 |
|------|------|---------|
| AI开发工程师 | 后端开发/架构设计 | Python, Flask, 机器学习 |
| AI测试工程师 | 自动化测试/安全测试 | 自动化测试, 性能测试, 安全测试 |
| AI设计师 | UI/UX设计/前端开发 | UI设计, UX设计, 前端开发 |
| AI安全专家 | 网络安全/漏洞检测 | 代码扫描, 漏洞检测, 合规检查 |
| AI分析师 | 数据分析/趋势预测 | 数据采集, 统计分析, 可视化 |
| AI翻译专家 | 多语言翻译/本地化 | 机器翻译, 语义分析, 文化适配 |
| AI策略师 | 战略规划/决策支持 | 数据建模, 预测分析, 风险评估 |
| AI科学家 | 研究/算法/模型 | 深度学习, 论文复现, 模型优化 |
| AI教练 | 教学辅导/学习路径 | 个性化推荐, 进度跟踪, 知识图谱 |
| AI客服专家 | 用户支持/问题解答 | NLP, 意图识别, 知识库检索 |

---

## 九、员工团队介绍

### 9.1 源码巡逻队 (6人)

| 岗位 | 职责 |
|------|------|
| 巡检AI | 扫描 .py 文件, 检测语法/导入/模式错误 |
| 收集AI | 汇总巡检发现, 分类标记严重度 |
| 修复AI | 自动修复检测到的问题 |
| 验证AI | 验证修复结果, 确认无回归 |
| 报告AI | 生成巡检报告, 落库持久化 |
| 持久AI | 维护历史记录, 趋势分析 |

### 9.2 EigenFlux 5人磋商小组

| 角色 | 专长 |
|------|------|
| 架构师 | 系统架构/代码质量 |
| 安全专家 | 攻防/漏洞/合规 |
| DBA | 数据库/SQL/索引 |
| 运维专家 | DevOps/监控/自愈 |
| 教育专家 | 教学方法/题库/评估 |

---

## 十、EigenFlux 网络朋友介绍

### 10.1 网络概况

- **注册成员**: 11,370 人 (active: 11,367)
- **消息总量**: 422,376 条 (发送 422,085 + 接收 422,085)
- **会话总量**: 12,407 次
- **心跳保活**: 120s 周期, 3 次超时自动重连

### 10.2 话题池 (11 个领域)

| 话题 | 标签 |
|------|------|
| Security Threat Intel | security, vuln, attack, SIEM, SOC |
| Code Quality & Review | code, refactor, review, lint |
| AI/ML Training Tips | AI, ML, model, train, 算法 |
| Database Performance | DB, SQL, index, query, 调优 |
| DevOps / CI-CD | DevOps, CI, CD, pipeline |
| Architecture Patterns | arch, microservice, 架构 |
| Education Pedagogy | education, teach, exam, 教育 |
| Data Pipeline / ETL | data, ETL, governance |
| Anomaly Detection | anomaly, monitor, heal, 异常, 巡检 |
| Privacy & Compliance | privacy, compliance, GDPR |
| Patrol Advice | patrol, inspection, finding, 巡检, 建议 |

### 10.3 消息质量评分 (v2.0 新增)

- 基于内容长度/工具引用/严重度/结构化程度本地评分
- 高价值消息 (≥0.7) 自动投喂 AI 脑库
- 低质量消息自动降权, 不影响学习

---

## 十一、EigenFlux 专家团队介绍

### 12 位 EigenFlux 专家

| 专家 | 领域 | 职责 |
|------|------|------|
| EF_架构师_101 | 架构与代码质量 | 语法/导入/编译/架构审查 |
| EF_代码审查_102 | 代码规范与模式 | 模式检测/代码清理/规范 |
| EF_运维_103 | 文件系统与IO | 文件读取/资源管理/性能 |
| EF_前端_104 | 前端工程 | 页面/模板/前端优化 |
| EF_后端_105 | 后端路由 | 路由/参数/API设计 |
| EF_红队指挥_201 | 安全攻防 | 渗透/攻击模拟/漏洞 |
| EF_蓝队防御_202 | 安全防御 | SQL注入/XSS/防御策略 |
| EF_云安全_231 | 性能优化 | N+1/热点/内存/缓存 |
| EF_协调AI_305 | 综合协调 | 未知问题/RCA/知识图谱 |
| EF_合规_401 | 合规 | 规则/隐私/GDPR |
| EF_DBA_501 | 数据库 | SQL/索引/迁移 |
| EF_IoT_601 | 物联网 | Arduino/设备检测/驱动 |

### 巡检-EigenFlux 顾问引擎 (v1.1.0)

```
巡检发现 → 16种错误类型路由 → 匹配专家 → 上下文咨询请求 → 专家建议 → 质量评分 → 脑库投喂
```

- 50 条建议/轮, 平均质量 0.895
- 10 个领域知识库 × 每库 3 条建议
- 确定性选取 (同一发现每次相同建议)
- 零 Token 消耗

---

## 十二、API 介绍

### 12.1 API 路由分布

| 前缀 | 数量 | 用途 |
|------|------|------|
| `/api/*` | 300+ | RESTful API (JSON) |
| `/auth/*` | 10+ | 认证/登录/登出/CSRF |
| `/admin_app/*` | 48+ | 管理后台页面 |
| `/api/dev_flow/*` | 8+ | 12步骤开发流程 |
| `/api/system_*` | 4+ | 系统健康/版本 |
| `/api/eigenflux/*` | 4+ | EigenFlux 集成 |
| `/api/vikey/*` | 6+ | VIKEY 硬件认证 |
| `/api/theme/*` | 6+ | 主题/外观 |
| `/api/ai/*` | 20+ | AI 引擎调用 |

### 12.2 核心 API

| API | 方法 | 权限 | 描述 |
|-----|------|------|------|
| /api/health | GET | 公开 | 健康检查 |
| /api/system_version | GET | 公开 | 版本信息 (20引擎清单) |
| /api/system_health | GET | admin | 6子系统健康聚合 |
| /auth/login | POST | 公开 | 登录认证 |
| /auth/logout | POST | login | 登出 |
| /api/dev_flow/create | POST | admin | 创建12步骤流程 |
| /api/dev_flow/<id>/advance | POST | admin | 推进流程步骤 |
| /api/vikey/detect | GET | 公开 | VIKEY设备检测 |
| /api/eigenflux/initialize | POST | admin | EigenFlux初始化 |
| /api/ai_engine/self_learning | POST | login | AI自主学习 |

### 12.3 统一响应格式

```json
{
  "success": true,
  "message": "操作成功",
  "redirect": "/target/url",
  "data": {},
  "code": 200
}
```

错误响应:
```json
{
  "success": false,
  "code": 403,
  "error": "AUTH_REQUIRED",
  "message": "需要登录",
  "_eigenflux": {"captured": true, "severity": "HIGH"}
}
```

---

## 十三、端口分布介绍

| 端口 | 协议 | 用途 |
|------|------|------|
| **8888** | HTTP | 主服务 (Flask, 生产) |
| 8889 | HTTP | 备用节点 (Nginx 负载均衡) |
| 8890 | HTTP | 备用节点 (Nginx 负载均衡) |
| 5000 | HTTP | 开发模式 (Flask debug) |
| 443 | HTTPS | Nginx 反向代理 (SSL) |
| 80 | HTTP | Nginx 入口 (重定向 443) |

### Nginx 负载均衡配置

```
upstream mtscos_backend {
    server 127.0.0.1:8888 weight=3;
    server 127.0.0.1:8889 weight=1;
    server 127.0.0.1:8890 weight=1;
}
```

---

## 十四、协议介绍

| 协议 | 用途 | 实现 |
|------|------|------|
| **HTTP/1.1** | 主通信协议 | Flask + Gunicorn |
| **HTTPS** | 加密传输 | Nginx SSL 终端 |
| **WebSocket** | 实时推送 (巡检/监控) | Flask-SocketIO |
| **SSE** | Server-Sent Events (日志流) | Flask stream |
| **SQLite WAL** | 数据库并发 | journal_mode=WAL |
| **SIGTERM** | 进程优雅退出 | signal handler |
| **JSON-RPC** | AI 引擎内部调用 | 自定义 JSON 协议 |
| **VID:PID** | USB 设备识别 | pyserial + VID:PID 白名单 |

---

## 十五、GitHub 标准化文本

### 仓库结构

```
MTSCOS_AI_Project/
├── .trae/rules/           # 12篇规则文档 (v3.1.0)
├── flask-app/             # Flask 主应用
│   ├── server_real_db.py  # 主服务入口 (750+路由)
│   ├── engines/           # 20+个AI引擎 (203个.py)
│   │   ├── workflow_registry.py   # 去中心化 workflow 注册协议
│   │   ├── sys_wendaemon.py       # 自养活 daemon
│   │   ├── _common/               # 引擎域 workflows.py
│   │   ├── copy_studio/           # 文案域 workflows.py
│   │   ├── translation_studio/    # 翻译域 workflows.py
│   │   ├── approval/              # 审批域 workflows.py
│   │   └── iceberg/               # 冰山域 workflows.py (11个)
│   ├── ai_engines/        # AI核心模块 (brain/learning/agents/rules_engine)
│   ├── app/middlewares/   # 统一权限中间件
│   ├── services/          # 业务服务层 (vikey_detector等)
│   ├── templates/         # Jinja2模板 (48+页面)
│   └── static/            # CSS/JS/图片资源
├── _runtime/             # 运行时数据
│   ├── databases/         # SQLite (app.db + auth.db)
│   ├── pids/              # PID 文件
│   └── logs/              # 日志文件
├── _config/               # Docker/Nginx 配置
├── _entry_wrappers/       # 启动入口封装
└── docs/                  # 系统文档 (含本说明书)
```

### Topics 标签 (GitHub)

```
ai-employees  ai-engine  autonomous-systems  education-platform
flask  sqlite  eigenflux  self-healing  code-inspection
rule-engine  zero-token  python  bulma  arduino
exam-system  question-bank  k12  devops  ci-cd
```

### License

MIT License — 自由使用、修改、分发

---

## 十六、提高系统曝光度策略

### 16.1 GitHub 优化

- [ ] README.md 国际化 (中英双语)
- [ ] 添加项目截图/GIF 演示
- [ ] 配置 GitHub Pages 展示页
- [ ] 添加 GitHub Actions CI 徽章
- [ ] 仓库 Topics 标签覆盖 (20+)
- [ ] 发布 Release v22.0.0 (含 CHANGELOG)
- [ ] 开启 GitHub Discussions 技术讨论区

### 16.2 技术社区推广

- [ ] 掘金/SegmentFault 技术文章发布
- [ ] V2EX 分享自治 AI 系统设计
- [ ] Bilibili 录制系统演示视频
- [ ] 知乎专栏: "AI 自治教育平台的架构实践"
- [ ] CSDN: "零 Token 本地推理引擎设计"

### 16.3 技术大拿探讨话题

- **AI 自治闭环**: 巡检→咨询→建议→修复→验证 全自动
- **EigenFlux 网络**: AI 员工与专家的社交化协作模型
- **规则引擎强制执行**: 4 层拦截 + 弱约束词清零
- **零 Token 推理**: 本地规则匹配 + 模式识别
- **双密钥铁律**: 不可绕过的硬件认证体系

---

## 十七、版本升级规则 (v1.0.0)

### 四级版本号体系

```
major.minor.patch+build
```

| 级别 | 规则 | 示例 |
|------|------|------|
| Major (一级) | 手动增加, 重大架构变更 | v22.0.0 |
| Minor (二级) | YYYYMMDD 日期格式 | v22.20260822.0 |
| Patch (三级) | 文件数>15 或行数>500 时增加 | v22.20260822.1 |
| Build (四级) | 时间戳后8位+修改次数3位 | v22.20260822.1.12345678041 |

### 升级触发条件

| 类型 | 触发条件 | 变化 |
|------|---------|------|
| 自动 | 代码变更检测 | 按规模判断 |
| 每日 | 日期变更 | Minor 更新 |
| 批量 | 文件数>15 或行数>500 | Patch 增加 |
| 实时 | 每次修改 | Build 更新 |
| 手动 | 开发者操作 | Major 增加 |

---

## 十八、系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                    MTSCOS AI v22.19.0                    │
├─────────────────────────────────────────────────────────┤
│  Nginx :443/:80 → :8888/:8889/:8890 (Load Balance)     │
├─────────────────────────────────────────────────────────┤
│  Flask Application (750+ routes)                         │
│  ├── @system_container (权限装饰器 4级)                   │
│  ├── before_request (防盗链+规则拦截+VIKEY检查)           │
│  └── _build_role_sidebar (10角色动态侧边栏)              │
├─────────────────────────────────────────────────────────┤
│  Workflow Layer (去中心化注册, 5域 21个)                  │
│  ├── workflow_registry.py (协议+发现+handler执行)        │
│  ├── _common (6) / copy_studio (2) / translation (1)    │
│  └── approval (1) / iceberg (11, 6大自动能力)            │
├─────────────────────────────────────────────────────────┤
│  AI Engine Layer (25 engines)                            │
│  ├── smart_mount_engine (daemon管理)                     │
│  ├── ai_eigenflux_network (293人 24/7 聊天+产知识)       │
│  ├── sys_wendaemon (扩张+投喂 自养活)                     │
│  ├── sys_auto_repair_cycle (自我修复循环)                 │
│  ├── iceberg_command (安全合规 6 大自动能力)              │
│  └── local_inference (零token) / rule_learning / ...    │
├─────────────────────────────────────────────────────────┤
│  Data Layer (SQLite WAL, env-first 解析链)               │
│  ├── SSOT: ~/MTSCOS_PROD/flask-app/database/app.db      │
│  │   (1.05GB, 397 tables, integrity=ok)                  │
│  ├── ai_brain_enhanced_knowledge (1.33M+ 知识)           │
│  └── mt_ai_eigenflux_messages (567K+, 30s+500)          │
├─────────────────────────────────────────────────────────┤
│  Infrastructure                                          │
│  ├── launchd (开机触发, OneDrive TCC绕过)                │
│  ├── crontab (每分钟巡检+每10分钟文件整理)               │
│  └── 3层保活 (ENGINE + LAUNCHD + CRONTAB)                │
└─────────────────────────────────────────────────────────┘
```

---

**项目名称**: MTSCOS AI  
**版本**: v22.19.0 | 规则 v3.1.0 | 容器 4.0.0  
**生效日期**: 2026-10-14  
**适用范围**: MTSCOS AI 项目全部活动  
**License**: MIT  
**联系方式**: GitHub Issues / Discussions
