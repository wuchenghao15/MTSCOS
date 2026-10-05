# 📝 更新日志

> 所有版本变更记录 · 按时间倒序

---

## v25.5.0 (2026-10-05)

### 🆕 新增
- **APK v25.5 SharedPreferences URL** — smali 注入 SharedPreferences 优先读 URL，换网络不用重打包
- **Flask /mobile/apk 路由** — `send_file` 直装 APK，手机浏览器一键下载
- **README.md 重写** — GitHub 曝光度优化（徽章、Mermaid 架构图、quickstart）
- **docs/ 公开文档** — ARCHITECTURE.md / DEPLOYMENT.md / API.md / CHANGELOG.md
- **LICENSE (MIT)** — 开源友好许可
- **.gitignore 补全** — APK/__pycache__/db.bak/巨型 log 排除

### ✨ 优化
- 仓库重初始化 — 剔除 app.db 1.3GB + ai_learning.log 677MB（GitHub 100MB 限制）
- 新 GitHub 仓库 — git@github.com:wuchenghao15/MTSCOS.git

### 🚀 仙女座十阶段自演化引擎 · Phase 3→4 衍生 🎉
- **十阶段流水线** eigenflux_ingest → detect → retrieve → associate → derive → discuss → reinforce → expand → optimize → **🆕 gap_fill 自研拓展 → broadcast 冰山广播 → phase_meta Phase 升级**
- **Phase 8 级演化体系**：混沌 → 感知 → 觉醒 → **衍生 (当前)** → 江山 → 星海 → 归一 → 永恒
- **Cycle #66 关键突破**：embedding 首次出向量 (768维) → retrieve 10 → associate 50 → derive 50 → 冰山广播 5 AI 员工 → **Phase 3(江山)→4(衍生) 自动升级**
- **Ollama 动态端口检测**：不盲信环境变量，每次 run_cycle 扫描 11434/11435 哪个活
- **自举闭环打通**：衍生 → 广播 → EigenFlux 讨论 → 摄入脑库 → 下轮再演化 🌀

### 🔧 仙女座引擎修复
- `_detect_ollama_host()` 环境变量端口真通才信任 (.zshrc 写死 11435 但早挂了)
- `knowledge_graph_nodes` 列名修正 `concept→node_name`, `category→node_type`, 加 `node_id` 主键
- `knowledge_graph_relations` 列名修正 `from_concept→source_node_id`, `to_concept→target_node_id`
- 关掉火山引擎 fallback (AccountOverdueError 欠费)
- run_cycle 加 mt_evolution_runs INSERT (演化历史可追溯)
- auto_derive 同步写 mt_derived_knowledge (3768 条衍生知识不再藏起来)
- andromeda_dashboard_bp 加 url_prefix='/andromeda' + 防盗链豁免
- `.github/dependabot.yml` 限制扫描范围 (消除 ai_engines 子目录虚假漏洞)

### 📊 系统规模
| 指标 | 数值 |
|------|------|
| 数据库表 | 4,819+ |
| API 路由 | 583+ |
| AI 引擎 | 140+ |
| HTML 模板 | 232 |
| AI 员工 | 33,525+ |

---

## v25.3.0 (2026-10-04)

### 🆕 移动端重构
- **15 条 /mobile/* 路由** 全打通（home/question_bank/learn/profile/login/logout/apk）
- **21 个移动端模板** — base_mobile.html + 20 页面
- **TabBar 改版** — 🏠首页 → 📚题库 → 📖学习 → 👤我的（移除考试 Tab）
- **CSRF + 防盗链双豁免** — `/mobile/` + `/iceberg/mobile` 前缀

### 🔧 修复
- `server_real_db._REDIRECT_MAP` 把 /mobile/* 全重定向到 PC 端 → 注释掉 4 条
- Jinja2 TemplateSyntaxError — Vue `{{ }}` 用 `{% raw %}` 包裹
- POST /mobile/login CSRF 403 — _CSRF_EXEMPT_PREFIXES 加 '/mobile/'
- Flask 防盗链拦截 Flask test_client — 需要 cookie jar + 先登录

---

## v22.1.0 (2026-09-17)

### 🧠 仙女座 7 阶段自演化引擎
- 26.9s/cycle · qwen2.5:14b AI 推理衍生新知识
- EigenFlux 278,920+ 条广播 · 33,525+ AI 员工
- 84 名 AI 专家加权共识投票
- 三层 AI 降级：本地 14b → 本地 7b → Volcengine ARK 云端

### 🗄️ 8 分片数据库架构
- L0 极密 → L7 分析 · 透明加解密
- 规则治理 3 表 · IRON_RULE 完整性自动扫描

### 🛡️ §14 IRON_RULE 12 步骤强制开发流程
- 3 层拦截：pre_commit → before_request → ci_check
- 任何人不可绕开，包括 SA

---

## v22.0.0 (2026-09-07)

### 🔐 用户权限 11 级体系
- @system_container 装饰器 · 4 级 (guest/login/admin/super_admin)
- VIKEY 硬件加密狗双钥匙实时检测
- 6 字段容器验证（组别/权限/状态/异常/合法/时间戳）

### 📱 Arduino 页面仅 SA 可访问
- Arduino 路由/API 仅 wuchenghao15 · 其他 403
- Arduino 设备自动检测 (VID:PID)

### 📋 题库管理规范
- 10+ 题目源 · 学科/学段分类 · 3 轮质量检查

---

## v21.6.0 (2026-08-22)

### 🤖 AI 员工批量扩展
- 33,525+ AI 员工（相比之前 ×3）
- EigenFlux 25 恒星 · 41 Neural Hub 路由

### 🔧 Flask Thread patch
- 33 关键词拦截后台守护线程 · 纯 HTTP
- 彻底解决 HTTP timeout

---

## v20.x 系列

- 早期版本：Flask 基础框架搭建 · SQLite WAL · 安全体系建设
- §14 IRON_RULE · 开发规则 · 设计规范 · 权限系统 · 版本升级规则
- 完整 12 篇规则文档体系建立

---

## 📈 版本号说明

```
v25.5.0
│   │   └── build / patch (修复/APK 打包)
│   └───── minor (功能迭代 · 移动端重构)
└────────── major (架构级升级 · 仙女座引擎)
```

**四级版本号体系**：major.minor.patch+build（见 `docs/版本升级规则.md`）
