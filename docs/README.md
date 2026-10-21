# MTSCOS AI 智能管理系统
---

> ## 🔄 2026-10-21 · v22.25.16 更新
> 今日 14 flow 全部 §14 DONE 双推: 每日冷备份(1.80GB/3份轮转) · 滚动归档(60万行) · email+password 双金库收口 ·
> 脑库向量去重回填(27874向量) · 语义检索(hit@1=80%/P50=9.2ms) · chat RAG · hub L5+06B 能力面板 ·
> 三端代码闭环(7660/7660 SAME) · 题库语义搜题 · 广度战略规划 · P1四维(语义出题/RAG三出口/巡检语义化/敏感第四列评估) · 文档全量刷新
> **当前**: v22.25.16 · 双站生效(8888+5001) · 483表 · 276 AI员工 · 14 daemon · 保活=cron+Python直跑(launchd已废弃)


> **MTSCOS** = **M**ulti-Agent **T**win-Track **S**elf-evolving **C**ollaborative **O**perating **S**ystem

基于 MTS 架构 v2.0 的分布式多智能体智能教育与考试平台。统一集成 AI 自动命题、智能组卷、薄弱诊断、个性化学习路径与企业级 RBAC + ABAC 治理，覆盖 K12、成人教育与高等教育全场景。

[![版本](https://img.shields.io/badge/版本-v21.6.0-purple)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![许可证](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Stars](https://img.shields.io/github/stars/wuchenghao15/MTSCOS?style=social)](https://github.com/wuchenghao15/MTSCOS/stargazers)
[![Forks](https://img.shields.io/github/forks/wuchenghao15/MTSCOS?style=social)](https://github.com/wuchenghao15/MTSCOS/network/members)
[![Issues](https://img.shields.io/github/issues/wuchenghao15/MTSCOS)](https://github.com/wuchenghao15/MTSCOS/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/wuchenghao15/MTSCOS)](https://github.com/wuchenghao15/MTSCOS/pulls)

> 完整文档已迁入 [`docs/`](docs/) 目录：
> - 中文文档: [README.zh-CN.md](README.zh-CN.md) · [docs/README.zh-CN.md](docs/README.zh-CN.md)
> - 系统说明书: [docs/SYSTEM_MANUAL.md](docs/SYSTEM_MANUAL.md)
> - Code Wiki: [docs/code-wiki/](docs/code-wiki/)

---

## 项目亮点

| 维度 | 核心能力 |
| :--- | :--- |
| **MTS 架构 v2.0 双引擎** | 规划引擎负责策略，执行 AI 员工阵列负责落地；8 阶段配置加载 + 6 阶段模块加载 |
| **11,326+ AI 员工 / 引擎** | 80+ AI 模块，覆盖命题、组卷、批改、诊断、学习规划、安全审计、Git 运维、DevOps、布局修复、代码修复——技能可进化、故障可自愈 |
| **352+ 张数据库表** | 8 业务域分片 SQLite 数据库（auth / exam / question / learning / user / system / admin / log / ai），透明路由、开箱零配置 |
| **教育考试系统** | 11 学科 × 7 题型 × 3 Bloom 层级，37,000+ 题目，AI 智能组卷，防作弊监考，IRT + RL 自适应学习路径 |
| **农历服务** | 内置农历日历服务（[`core/services/lunar_calendar_service.py`](core/services/lunar_calendar_service.py)），适配按学期 / 节气排课的教育场景 |
| **企业级 RBAC + ABAC** | 16 级角色、50+ 权限规则、全链路不可篡改审计、超管 VIKEY USB 硬件密钥登录 |
| **AI 防火墙与应用安全** | WAF（SQLi/XSS/RCE/SSRF/LFI/目录穿越/限流）+ CI 全矩阵 pip-audit / Trivy / Bandit / CodeQL，Dependabot 日更 |
| **EigenFlux.al 集成** | 22,652+ 条广播消息，84 名 AI 专家，支持广播消息、AI员工聊天、学习数据同步 |
| **用户容器安全** | 所有非首页页面强制验证用户容器（user_group/permission_code/login_status/is_anomaly/is_valid/unique_login_timestamp） |
| **超管vikey铁律** | 所有超管操作实时检测vikey硬件（桌面）/指纹（移动端），铁律红线不可绕开 |
| **规则审批流程** | 提议→多人审批→AI防火墙→超管终审→适配期→保密撤回（内存级保密，数据库无记录） |
| **§14 IRON RULE** | 12步骤强制开发流程，3层拦截机制，8条铁律不可绕开 |
| **深度巡检引擎** | 1,052 路由 + 573 文件 (376,534 行代码) 自动巡检，3,454 问题发现，99.8% 自动修复 |
| **自动开发团队** | 235 缺失功能检测，222 自动完成开发，94.5% 完成率 |
| **自动巡逻队** | 1,000 轮巡逻，14,114 断言，100% 通过率，0 漏洞 |

---

## 系统规模

| 指标 | 数值 |
|------|------|
| 系统版本 | v21.6.0 |
| 数据库表 | 352+ 张 |
| AI员工 | 11,326+ 人 |
| API路由 | 300+ 条 |
| 前端页面 | 38+ 页 |
| Python文件 | 500+ 个 |
| daemon线程 | 10+ 个 |
| 安全级别 | L0-L4 五级 |
| 数据库分片 | 8 个 |
| 加密等级 | L0极密/L1机密/L2秘密/L3内部/L4公开 |

---

## 环境要求

| 依赖 | 最低版本 | 必选/可选 |
| :--- | :---: | :---: |
| Python | **3.9+**（建议 3.10+） | 必选 |
| SQLite | 3.30+ | 必选 |
| pip | 20.0+ | 必选 |
| Git | latest | 必选 |
| Redis | 7.0+ | 可选（无则降级为内存缓存） |
| 大模型 Key | 任意 | 可选（无 Key 亦可运行非 AI 功能） |

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/wuchenghao15/MTSCOS-AI-Project.git
cd MTSCOS-AI-Project

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 启动生产入口
python3 server_real_db.py --host 0.0.0.0 --port 8888
```

浏览器访问 <http://localhost:8888/>。

**命令行参数：**

| 参数 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `--host` | 绑定地址 | `127.0.0.1` |
| `--port` | HTTP 端口 | `8888` |
| `--ssl` | 启用 HTTPS | `False` |
| `--ssl-port` | HTTPS 端口 | `8443` |
| `--debug` | 调试模式 | `False` |

## Docker 部署

```bash
docker build -t mtscos-ai:v21.6.0 .
docker run -d -p 8888:8888 --name mtscos-ai \
  -v $(pwd)/split_databases:/app/split_databases:rw \
  -v $(pwd)/data:/app/data:rw \
  mtscos-ai:v21.6.0
```

### 入口说明

- **生产入口**：`server_real_db.py` —— 正确启动分片数据库、版本管理器、VIKEY 驱动及解耦的启动模块。
- **预览入口**：`server_preview.py` —— 用于本地调试。
- **历史兼容入口**：`app.py` —— 保留以兼容旧代码。

---

## 演示账号

预置 10+ 角色账号，统一密码：`Test@2026`。

| 用户名 | 角色 | 权限等级 |
| :--- | :--- | :---: |
| `test_student` | 学生 | 1 |
| `test_parent` | 家长 | 1 |
| `test_designer` | 设计师 | 1 |
| `test_teacher` | 教师 | 2 |
| `test_proctor` | 监考员 | 2 |
| `test_qm` | 题库管理员 | 3 |
| `test_aim` | AI 管理员 | 3 |
| `test_cm` | 集群管理员 | 3 |
| `test_admin` | 系统管理员 | 4 |
| `test_hwadmin` | 硬件管理员 | 5 |
| `wuchenghao15` | **超级管理员** | 9 · **需 VIKEY 硬件密钥** |

---

## 文档导航

| 文档 | 用途 |
| :--- | :--- |
| [系统完整说明书](docs/SYSTEM_MANUAL.md) | 系统规范、开发约束、对外能力、安全合规、API文档、数据库设计 |
| [Code Wiki 总索引](docs/code-wiki/00-总索引.md) | 代码文档导航 |
| [项目架构总览](docs/code-wiki/01-项目架构总览.md) | 系统架构图、技术栈、目录结构 |
| [核心模块详解](docs/code-wiki/02-核心模块详解.md) | 数据库双引擎、8分片系统、加密体系 |
| [AI系统模块](docs/code-wiki/03-AI系统模块.md) | 11,326+ AI员工、巡检引擎、EigenFlux网络 |
| [安全与认证系统](docs/code-wiki/04-安全与认证系统.md) | 双钥匙认证、VIKEY、§14铁律 |
| [前端与路由系统](docs/code-wiki/05-前端与路由系统.md) | 300+ API路由、前端页面、静态资源 |
| [依赖与运行指南](docs/code-wiki/06-依赖与运行指南.md) | 依赖安装、启动方式、Docker部署、测试运行 |
| [MTS 架构 v2.0 白皮书](docs/MT_ARCHITECTURE.md) | 47 个 AI Agent 双引擎流水线详解 |
| [部署指南](docs/DEPLOYMENT_GUIDE.md) | 生产 / Docker / K8s / TLS / 高可用 |
| [安全策略](SECURITY.md) · [docs/SECURITY.md](docs/SECURITY.md) | 漏洞上报流程、WAF 规则、CI 扫描矩阵 |
| [贡献者指南](CONTRIBUTING.md) | 代码规范、提交格式、PR 流程 |
| [变更日志](CHANGELOG.md) | v1.0 至 v21.6.0 全量变更 |
| [AI 引擎架构](ai_engines/AI_ENGINE_ARCHITECTURE.md) | 11,326+ AI 员工 / 引擎矩阵 |

---

## 许可协议

MIT License © 2026 wuchenghao15 / MTSCOS AI —— 全文见 [`LICENSE`](LICENSE)。

- 本平台自动生成的题库内容须本着学术诚信合理使用，禁止一切作弊与违规用途。
- **非商业 / 教育场景**：免费使用，超出 MIT 的额外署名不做要求。
- **商业 / 机构客户**：请先在 GitHub Discussions 发帖沟通，或邮件 `contact@mtscos.com`。
