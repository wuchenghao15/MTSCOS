# MTSCOS AI 智能考试系统

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Flask Version](https://img.shields.io/badge/flask-2.0%2B-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v17.10.0-orange.svg)](docs/CHANGELOG.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Documentation](https://img.shields.io/badge/docs-complete-green.svg)](SYSTEM_DOC.md)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/wuchenghao15/MTSCOS-AI-Project/actions)
[![Code Quality](https://img.shields.io/badge/code-quality-high-blue.svg)](SECURITY.md)
[![Community](https://img.shields.io/badge/community-active-blue.svg)](https://github.com/wuchenghao15/MTSCOS-AI-Project/discussions)

> 版本: v17.10.0 (Project Structure Refactor & AI Collaboration Enhancement)
> 更新日期: 2026-07-25

[English](README_EN.md) | 中文

MTSCOS AI 是一个基于 Flask 框架开发的分布式智能考试管理平台，提供完整的题库系统、考试管理、学习分析、AI智能引擎等功能，支持成人教育和K12全科目。

---

## 📋 目录

- [🌟 核心特性](#-核心特性)
- [📁 项目结构](#-项目结构)
- [🚀 快速开始](#-快速开始)
  - [原生部署](#原生部署)
  - [Docker部署](#docker部署)
  - [快速Docker部署](#快速docker部署)
- [📡 API接口](#-api接口)
- [📊 数据库架构](#-数据库架构)
- [🌐 管理后台页面](#-管理后台页面)
- [📈 功能使用流程](#-功能使用流程)
- [🧪 测试账号](#-测试账号)
- [🤝 贡献指南](#-贡献指南)
- [📄 许可证](#-许可证)
- [📞 联系方式](#-联系方式)

---

## 🌟 核心特性

### 🏗️ 架构特性
- **模块化启动系统**：8阶段配置加载 + 6阶段功能模块加载
- **分布式数据库架构**：20+ 独立数据库，智能路由
- **AI智能引擎矩阵**：41+ AI员工，6+ AI Agent，590+ 检索模型
- **响应式前端布局**：支持桌面端和移动端，适配手机客户端

### 📚 题库系统
- **37,000+ 题目**：覆盖成人教育和K12全科目（语文、数学、英语、物理、化学、生物、历史、地理、政治、科学、日语）
- **7种题型**：单选题、多选题、判断题、填空题、简答题、论述题、听力题
- **智能出题**：基于知识点/难度/题型批量出题
- **AI题目生成器**：从文本内容自动生成考试题目

### 🎓 教育综合管理
- **教学大纲管理**：大纲创建、章节管理、知识点管理、课程标准管理、版本控制（支持K12和成人教育）
- **题库与大纲同步**：题目与知识点映射、批量映射、考试与大纲同步、基于知识点和大纲智能生成题目与考试
- **学习与大纲追踪**：学生学习进度追踪、知识点掌握度记录、章节进度更新、学习建议生成、评估报告
- **教育综合API**：教学大纲CRUD、题库同步、学习追踪的RESTful API接口

### 🔐 权限管理
- **16+ 角色**：guest→student→parent→designer→teacher→exam_proctor→question_manager→ai_manager→cluster_manager→admin→hardware_admin
- **细粒度权限**：50+权限规则覆盖，6级访问控制
- **审计日志**：完整操作记录、实时审计
- **权限矩阵**：支持自定义权限规则配置

### 🤖 AI集群与模型库
- **15+ AI模型**：GPT-4、Claude-3、Qwen、Llama-3、Gemini、DeepSeek等
- **性能监控**：延迟、吞吐量、准确率指标
- **动态扩展**：节点自动扩展、负载均衡
- **多模型配置**：支持模型切换和版本管理

### ✨ AI智能功能
- **AI题目生成器**：从文本内容自动生成考试题目，支持6种题型、11个科目、3级难度，自动保存到题库
- **AI学习路径推荐**：分析学生错题数据，生成个性化学习路径，包含薄弱分析和知识图谱
- **AI试卷自动组卷**：根据科目、难度、题型智能组卷，自动计算分数分布和考试时长，知识覆盖率分析，质量评分
- **AI智能答疑**：学生在线提问，AI自动解答，支持多科目、多题型，会话管理，知识库搜索
- **智能错题本**：自动收集错题，艾宾浩斯遗忘曲线复习，薄弱知识点分析，掌握程度追踪
- **学生成绩分析仪表盘**：多维度数据可视化分析，成绩分布直方图、各科平均分雷达图、学习时间趋势图、错题率分析
- **智能学习助手**：个性化学习推荐、智能作业辅导、学习效果分析

### 🔐 安全防护
- **企业级防火墙**：10+安全规则（SQL注入/XSS/命令注入/SSRF/文件包含/路径遍历/敏感文件/暴力破解/扫描器防护/API限流）
- **AI安全建议**：智能分析安全漏洞，生成优化建议和实施步骤
- **安全漏洞管理系统**：漏洞特征库（9种漏洞类型、17种检测特征、13种修复方案）、攻击模拟引擎（SQL注入/XSS模拟）、代码安全扫描器（13条检测规则）、AI闭环学习（安全知识自动同步到脑库）
- **代码安全扫描**：自动扫描Python/HTML代码，检测eval代码注入、命令注入、路径遍历、硬编码密钥等漏洞，扫描结果入库管理

### 🚀 自我维护能力
- **自动修复引擎**：8种修复能力（表结构修复/配置校正/缓存清理/连接池重建/配置回滚/数据恢复/索引重建/权限修复）
- **预防式维护**：8项维护内容，预测准确率100%
- **系统健康诊断**：8项核心检查（数据库/API响应/内存/CPU/磁盘/网络/缓存/错误日志）

### 🌐 端口与集群管理
- **21个端口配置**：HTTP/HTTPS、API、WebSocket、数据库等
- **端口管理**：扫描、分配、预留、释放、自动修复
- **负载均衡**：轮询、最小连接数、加权轮询、IP哈希
- **健康检查**：心跳检测、自动故障转移、节点状态监控

### 📊 系统监控
- **实时监控**：CPU、内存、磁盘、网络
- **慢查询检测**：自动识别和优化慢查询
- **性能分析**：索引建议、查询统计
- **性能监控API**：提供系统状态和性能指标接口

### 🚀 自动化运维
- **Git自动同步**：变更检测、自动提交、推送
- **每日健康检查**：数据库清理、日志清理、备份
- **自动升级**：版本检测、灰度发布、健康检查回滚
- **版本管理**：系统历史版本记录、自动更新说明文档

---

## 📁 项目结构

```
MTSCOS-AI-Project/
├── app.py                      # 应用入口
├── version_manager.py          # 版本管理器
├── scheduler_control.py        # 调度引擎控制（含看门狗守护进程）
├── auto_scheduler.py           # 自动调度器
├── requirements.txt            # Python依赖
├── Dockerfile                  # Docker构建配置
├── docker-compose.yml          # Docker Compose完整配置
├── docker-compose.quick.yml    # 快速Docker部署配置
├── CHANGELOG.md                # 变更日志
├── SYSTEM_DOC.md               # 系统说明书
├── DEPLOYMENT_GUIDE.md         # 部署指南
├── SECURITY.md                 # 安全文档
├── CONTRIBUTING.md             # 贡献指南
├── CODE_OF_CONDUCT.md          # 行为准则
├── LICENSE                     # 许可证
├── ai_engines/                 # AI引擎模块 (20+核心引擎)
│   ├── ai_cluster_manager.py   # AI集群管理
│   ├── ai_employee_manager.py  # AI员工管理
│   ├── ai_question_bank.py     # 题库生成引擎
│   └── ...
├── app/                        # 应用模块
│   ├── routes/                 # 路由模块 (API蓝图)
│   ├── services/               # 服务模块
│   ├── models/                 # 数据模型
│   ├── api/                    # API蓝图模块
│   ├── utils/                  # 工具模块
│   ├── middlewares/            # 中间件
│   └── __init__.py             # 应用初始化
├── templates/                  # HTML模板 (100+个)
├── static/                     # Flask静态文件
├── data/                       # 数据目录
├── logs/                       # 日志目录
└── .github/                    # GitHub配置
    ├── workflows/              # CI/CD工作流
    └── ISSUE_TEMPLATE/         # 问题模板
```

---

## 🚀 快速开始

### 环境要求
- Python 3.9+
- SQLite 3.30+
- Redis 7.0+（可选，系统支持内存缓存降级）
- Git
- pip 20.0+

---

### 原生部署（推荐）

```bash
# 克隆仓库
git clone https://github.com/wuchenghao15/MTSCOS-AI-Project.git
cd MTSCOS-AI-Project

# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python app.py --port 8888
```

**启动参数**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --port | 服务端口 | 8888 |
| --host | 绑定地址 | 0.0.0.0 |
| --debug | 调试模式 | False |
| --ssl | 启用SSL | False |
| --ssl-port | SSL端口 | 8443 |

---

### Docker部署

**完整部署（含Redis）**

```bash
# 克隆仓库
git clone https://github.com/wuchenghao15/MTSCOS-AI-Project.git
cd MTSCOS-AI-Project

# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f
```

**快速部署（仅应用）**

```bash
# 快速启动（无Redis依赖）
docker-compose -f docker-compose.quick.yml up -d

# 查看日志
docker-compose -f docker-compose.quick.yml logs -f
```

**Docker部署对比**

| 特性 | docker-compose.yml | docker-compose.quick.yml |
|------|-------------------|------------------------|
| Redis | ✅ 包含 | ❌ 不包含 |
| AI自学习 | ✅ 启用 | ❌ 禁用 |
| Git自动同步 | ✅ 启用 | ❌ 禁用 |
| 自动备份 | ✅ 启用 | ❌ 禁用 |
| 部署速度 | 较慢（需构建） | 较快（直接运行） |
| 适用场景 | 生产环境 | 开发/测试环境 |

---

### 访问地址
- 系统首页: http://localhost:8888/
- 登录页面: http://localhost:8888/login
- 管理后台: http://localhost:8888/admin_app/login
- 增强管理器仪表板: http://localhost:8888/enhancement
- AI学习仪表盘: http://localhost:8888/ai_learning_dashboard

---

## 📡 API接口

### 认证接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/auth/login | POST | 用户登录 |
| /api/auth/logout | POST | 用户登出 |
| /api/auth/check | GET | 检查登录状态 |

### 系统管理接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/system/status | GET | 获取系统状态 |
| /api/system/configs | GET | 获取系统配置 |
| /api/system/modules | GET | 获取模块状态 |
| /api/system/version | GET | 获取系统版本 |

### AI题目生成接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/ai/generate-questions | POST | 从文本生成题目 |
| /api/ai/generate-questions/save | POST | 保存生成的题目 |
| /api/ai/generate-questions/stats | GET | 获取生成统计 |
| /api/ai/detect-subject | POST | 自动检测科目 |
| /api/ai/extract-key-points | POST | 提取关键点 |

### AI学习路径接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/ai/study-path/generate | POST | 生成学习路径 |
| /api/ai/study-path/analyze | POST | 分析薄弱环节 |
| /api/ai/study-path/knowledge-graph | GET | 获取知识图谱 |
| /api/ai/study-path/progress | POST | 获取学习进度 |

### AI学习助手接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/learning_assistant/recommendations | GET | 获取学习推荐 |
| /api/learning_assistant/generate_recommendations | POST | 生成学习推荐 |
| /api/learning_assistant/homework/analyze | POST | 分析作业答案 |
| /api/learning_assistant/report | GET | 获取学习报告 |

### AI试卷组卷接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/ai/exam-compose | POST | 自动组卷 |
| /api/ai/exam-compose/preview | POST | 预览试卷 |
| /api/ai/exam-compose/save | POST | 保存试卷 |
| /api/ai/exam-compose/statistics | GET | 获取组卷统计 |

### 增强管理器接口
| 接口 | 方法 | 说明 |
|------|------|------|
| /api/enhancement/status | GET | 增强管理器总览状态 |
| /api/enhancement/database/health | GET | 数据库健康检查 |
| /api/enhancement/cluster/monitor | GET | 集群状态监控 |
| /api/enhancement/system/resources | GET | 系统资源多维度监控 |
| /api/enhancement/git/sync | POST | Git一键同步 |

---

## 📊 数据库架构

### 主要数据库
| 数据库 | 用途 | 核心表 |
|--------|------|--------|
| auth.db | 认证和用户管理 | users, roles, permissions, sessions |
| exam.db | 考试管理 | exams, exam_questions, exam_results |
| question.db | 题库管理 | questions, ai_generated_questions |
| learning.db | 学习系统 | learning_records, study_paths, knowledge_points |
| system.db | 系统配置 | configs, versions, logs |
| ai.db | AI引擎数据 | ai_models, ai_clusters, ai_results |
| admin.db | 管理后台 | admin_users, admin_logs |
| log.db | 日志系统 | system_logs, audit_logs, error_logs |
| api_management.db | API管理 | api_endpoints, api_stats |
| routes_management.db | 路由管理 | routes, route_stats |

---

## 🌐 管理后台页面

| 页面路由 | 说明 | 权限要求 |
|---------|------|---------|
| /admin_app/login | 管理员登录 | 所有角色 |
| /admin/ai-question-generator | AI题目生成器 | admin |
| /admin/ai-study-path | AI学习路径推荐 | admin |
| /admin/ai-exam-composer | AI试卷组卷 | admin |
| /admin/student-analytics | 学生成绩分析仪表盘 | admin |
| /admin/question-bank | 题库管理 | question_manager |
| /admin/ai-cluster | AI集群管理 | ai_manager |
| /admin/cluster-management | 集群管理 | cluster_manager |
| /enhancement | 增强管理器仪表板 | admin |

---

## 📈 功能使用流程

### AI题目生成流程
1. 输入文本内容 → 系统自动检测科目 → 提取关键点 → 生成题目 → 保存到题库

### AI学习路径推荐流程
1. 分析学生错题数据 → 识别薄弱环节 → 生成个性化学习路径 → 跟踪学习进度

### AI试卷组卷流程
1. 设置科目/题型/难度 → 智能选题 → 分析知识覆盖率 → 预览试卷 → 保存试卷

### 学生成绩分析流程
1. 选择科目/班级/时间范围 → 加载统计数据 → 可视化展示 → 导出分析报告

### 智能学习助手流程
1. 获取学习推荐 → 完成推荐学习 → 提交作业 → AI分析作业 → 生成学习报告

---

## 🧪 测试账号

系统已预置11个测试账号，供开发者和测试人员使用：

| 用户名 | 角色 | 权限等级 |
|--------|------|---------|
| `test_student` | 学生 | 1 |
| `test_parent` | 家长 | 1 |
| `test_designer` | 设计师 | 1 |
| `test_teacher` | 教师 | 2 |
| `test_proctor` | 监考员 | 2 |
| `test_qm` | 题库管理员 | 3 |
| `test_aim` | AI管理员 | 3 |
| `test_cm` | 集群管理员 | 3 |
| `test_admin` | 系统管理员 | 4 |
| `test_hwadmin` | 硬件管理员 | 5 |

**统一密码**: `Test@2026`

---

## 🤝 贡献指南

欢迎加入 MTSCOS AI 项目！无论是代码贡献、文档完善、Bug报告还是功能建议，我们都非常欢迎。

### 代码规范

项目遵循以下规范文档，所有贡献必须严格遵守：

- [设计规范](../.trae/rules/设计规范.md) - 统一UI设计标准和视觉风格
- [开发规则](../.trae/rules/开发规则.md) - 统一开发标准和代码规范

### 分支管理策略

| 分支 | 用途 |
|------|------|
| `main` | 主分支，生产环境代码 |
| `develop` | 开发分支，集成所有功能 |
| `feature/xxx` | 功能分支，开发新功能 |
| `bugfix/xxx` | Bug修复分支 |
| `hotfix/xxx` | 紧急修复分支 |

### 提交信息规范

```
<类型>(<范围>): <描述>

<详细说明>
```

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug修复 |
| `docs` | 文档更新 |
| `style` | 样式修改 |
| `refactor` | 代码重构 |
| `test` | 测试代码 |
| `chore` | 构建/工具更新 |

### 开发环境搭建

1. **克隆仓库**
```bash
git clone https://github.com/wuchenghao15/MTSCOS-AI-Project.git
cd MTSCOS-AI-Project
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **启动开发服务器**
```bash
python app.py --port 8888
```

4. **运行测试**
```bash
python -m pytest
```

### 提交PR流程

1. **Fork仓库** - 在GitHub上Fork本仓库到自己的账户
2. **创建分支** - 基于 `develop` 分支创建新分支
3. **开发功能** - 实现功能或修复Bug，遵循代码规范
4. **提交代码** - 使用规范的提交信息
5. **推送分支** - 推送到自己的Fork仓库
6. **创建PR** - 在GitHub上创建Pull Request到 `develop` 分支
7. **代码审查** - 等待项目维护者审查
8. **合并分支** - PR通过审查后合并到 `develop`

---

## 📄 许可证

MIT License

---

## 📞 联系方式

- 项目地址: https://github.com/wuchenghao15/MTSCOS-AI-Project
- 系统文档: [SYSTEM_DOC.md](SYSTEM_DOC.md)
- 部署指南: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- 版本历史: [CHANGELOG.md](CHANGELOG.md)

---

**MTSCOS AI** - 让考试更智能，让学习更高效 🚀

⭐ 如果这个项目对你有帮助，请给个Star！
