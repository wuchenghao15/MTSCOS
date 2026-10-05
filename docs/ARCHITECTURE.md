# 🏗️ 系统架构

> MTSCOS AI · v25.5.0 · 2026-10-05

---

## 1. 分层架构总览

```
┌─────────────────────────────────────────────────────────┐
│  Layer 6 · 客户端 (Client)                               │
│  ┌──────────────────────┐  ┌────────────────────────┐   │
│  │ Android APK v25.5    │  │ PC 浏览器 (Element Plus) │   │
│  │ WebView · Material3  │  │ SPA · 38+ 页面            │   │
│  └──────────┬───────────┘  └───────────┬────────────┘   │
└─────────────┼──────────────────────────┼────────────────┘
              │ HTTPS / HTTP             │
┌─────────────┼──────────────────────────┼────────────────┐
│  Layer 5 · 公网穿透 (Tunnel)            │                │
│  ┌──────────▼──────────┐  ┌───────────▼────────────┐   │
│  │ Serveo SSH Tunnel   │  │ 局域网 WiFi 172.20.x.x │   │
│  │ https://xxx.serveo  │  │ http://IP:8888         │   │
│  └──────────┬──────────┘  └───────────┬────────────┘   │
└─────────────┼──────────────────────────┼────────────────┘
              └──────────┬───────────────┘
                         │ :8888
┌────────────────────────┼────────────────────────────────┐
│  Layer 4 · Flask 应用层  │                                │
│  ┌─────────────────────▼─────────────────────────────┐  │
│  │ server_real_db.py · Flask 3.1                       │  │
│  │ ├─ 583+ 路由 (/mobile/*, /iceberg/*, /api/*...)    │  │
│  │ ├─ 中间件: system_container, 防盗链, CSRF           │  │
│  │ ├─ 232 HTML 模板 (Element Plus / Material3)         │  │
│  │ └─ Blueprints: mobile_bp, auth_bp, iceberg_bp...   │  │
│  └────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│  Layer 3 · AI 引擎集群 (140+)                           │
│  ┌─────────────────────▼─────────────────────────────┐  │
│  │ smart_mount_engine (15 daemon 管理)                │  │
│  │ ├─ 🧠 local_inference · Ollama 零 token 推理       │  │
│  │ ├─ 🌌 eigenflux_network · 33,525+ AI 员工广播       │  │
│  │ ├─ 🛡️ rule_enforcer · §14 IRON_RULE 自动学习       │  │
│  │ ├─ 🔧 auto_repair · 巡检自动修复 99.8% 问题        │  │
│  │ ├─ 👥 auto_hire · AI 自动雇佣 + EigenFlux 邀请     │  │
│  │ ├─ 🔍 patrol_engine · 6 AI 源码巡逻队              │  │
│  │ ├─ 📖 edu_sync · 教辅 K12/高等/职业同步             │  │
│  │ ├─ 📦 arduino_engine · 19 教程 + 设备自动检测        │  │
│  │ ├─ ... 等 12 核心引擎 + 35+ 仙女座自演化模块         │  │
│  └────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│  Layer 2 · 本地推理 (macOS Metal iGPU)                   │
│  ┌─────────────────────▼─────────────────────────────┐  │
│  │ Ollama 11435                                       │  │
│  │ ├─ qwen2.5:14b 🥇 通用主力                         │  │
│  │ ├─ qwen2.5-coder:14b 🆕 代码主力                   │  │
│  │ ├─ nomic-embed-text 768 维嵌入                      │  │
│  │ └─ Metal iGPU · q8_0 KV cache · 24GB 共享内存       │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  🔄 三层降级链路:                                        │
│  本地 14b → 本地 7b → Volcengine ARK (133 云端模型)      │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  Layer 1 · SQLite 8 分片数据库 (4,819+ 表)                │
│                                                           │
│  L0 极密 ─── L1 机密 ─── L2 秘密 ─── L3-L7 业务/分析     │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ flask-app/database/app.db · WAL 模式 · busy_timeout │  │
│  │ ├─ 规则治理 3 表 (changelog/violation/integrity)    │  │
│  │ ├─ AI 员工 2 表 (ai_employees 10,827 + eigenflux)  │  │
│  │ ├─ AI 引擎运行日志 × N                              │  │
│  │ └─ 透明加解密 · §14 IRON_RULE 完整性扫描            │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 移动端架构 (v25.5)

```
┌─────────────────────────────────────────────┐
│  MTSCOS-AI-Mobile-v25.5.0-debug.apk          │
│  com.mtscos.mobile · minSdk 24 · targetSdk 34│
├─────────────────────────────────────────────┤
│                                             │
│  AndroidManifest.xml                        │
│  └─ MainActivity (launchMode=singleTop)     │
│      └─ WebView (android.webkit.WebView)   │
│          ├─ WebSettings                    │
│          │  ├─ setJavaScriptEnabled(true)  │
│          │  ├─ setDomStorageEnabled(true)   │
│          │  ├─ setDatabaseEnabled(true)    │
│          │  ├─ setMixedContentMode(MIXED)  │
│          │  └─ setUserAgentString(          │
│          │      "... MTSCOSMobileApp")      │
│          ├─ WebChromeClient (进度条)        │
│          ├─ WebViewClient                   │
│          │  └─ shouldOverrideUrlLoading    │
│          └─ loadUrl(URL)                    │
│                                             │
│  URL 来源 (优先级):                          │
│  ┌─────────────────────────────────────┐    │
│  │ 1. SharedPreferences (覆盖)         │    │
│  │    name: mtscos_prefs               │    │
│  │    key:  server_url                 │    │
│  │    ├─ 存在 → 用这个 (可动态改)      │    │
│  │    └─ 不存在 → 回退到 #2            │    │
│  │                                     │    │
│  │ 2. constructor 硬编码 (默认)         │    │
│  │    http://172.20.10.2:8888/iceberg   │    │
│  │    (iPhone 热点网关, 同 WiFi 可用)   │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 修改 APK URL (不用重打包)
```bash
# adb shell 直接写 SharedPreferences
adb shell run-as com.mtscos.mobile \
  sh -c 'echo "<?xml version=\"1.0\"?><map><string name=\"server_url\">https://NEW-URL.serveousercontent.com/mobile/login</string></map>" > shared_prefs/mtscos_prefs.xml'
```

---

## 3. 仙女座十阶段自演化引擎 · Phase 4 衍生

> `engines/andromeda_auto_evolution.py` · **267.8s/cycle** · Ollama 11434 动态端口 · qwen2.5:14b + nomic-embed-text 768维

### 十阶段流水线（Cycle #66 首次 embedding 成功）

```
                 ┌──────────────┐
                 │ Stage 0      │
                 │ eigenflux_    │ 摄入 AI 员工讨论 → 脑库增量
                 │ ingest        │ checkpoint: eigenflux_last_msg_id
                 └──────┬───────┘
                        │
                 ┌──────────────┐
                 │ Stage 1      │
                 │ auto_detect   │ 脑库新增知识增量 (checkpoint 增量)
                 └──────┬───────┘
                        │ 10 条新条目 (batch_size=10)
                 ┌──────────────┐
                 │ Stage 2      │
                 │ auto_retrieve │ Ollama embed 768维 + 语义检索 top_k=10
                 └──────┬───────┘
                        │ ✅ 768 维向量首次成功 (之前 total_vectors=0)
                 ┌──────────────┐
                 │ Stage 3      │
                 │ auto_associate│ sim>0.55 → knowledge_graph_relations
                 └──────┬───────┘
                        │ 50 对关联
                 ┌──────────────┐
                 │ Stage 4      │
                 │ auto_derive 🥇│ qwen2.5:14b 推理 → 写 mt_derived_knowledge
                 └──────┬───────┘
                        │ 50 条衍生知识
                 ┌──────────────┐
                 │ Stage 4.5    │
                 │ AI discuss   │ AI 员工讨论衍生知识
                 └──────┬───────┘
                        │ 12 条讨论
                 ┌──────────────┐
                 │ Stage 5      │
                 │ reinforce    │ confidence_score / usage_count 强化
                 └──────┬───────┘
                        │ 1527 条强化
                 ┌──────────────┐
                 │ Stage 6      │
                 │ expand       │ AI 员工增强建议
                 └──────┬───────┘
                        │
                 ┌──────────────┐
                 │ Stage 7      │
                 │ optimize     │ 动态调阈值 + mt_evolution_runs 记录
                 └──────┬───────┘
                        │
          ══════════════╪══════════════════
          🆕 2026-10-05 新增 (十阶段)
          ══════════════╪══════════════════
                        │
                 ┌──────────────┐
                 │ Stage 8 🧠   │
                 │ gap_fill     │ auto_discover_gaps + auto_expand_knowledge
                 │ 自研拓展     │ 扫稀疏学科 → Ollama 补 KG 节点 + 增强知识
                 └──────┬───────┘
                        │
                 ┌──────────────┐
                 │ Stage 9 🔁   │
                 │ broadcast    │ iceberg_broadcast_derived
                 │ 冰山广播     │ 推给 5 AI 员工 → EigenFlux 讨论 → 摄入脑库 🌀
                 └──────┬───────┘
                        │
                 ┌──────────────┐
                 │ Stage 10 ⚡  │
                 │ phase_meta   │ auto_meta_phase_advance
                 │ Phase 升级   │ 8 级演化体系自动判定
                 └──────┬───────┘
                        │ 🎉 Phase 3(江山) → Phase 4(衍生) 自动升级!
                        ▼
                 ┌──────────────┐
                 │ 下一轮 cycle │
                 │ (自举闭环)    │ Stage 9 广播 → 下轮 Stage 0 摄入 → ... 🌀
                 └──────────────┘
```

### Phase 8 级演化体系

```
Phase 1 混沌 ─── 初始状态, 只有静态知识
Phase 2 感知 ─── 检测新知识变化, basic detect
Phase 3 觉醒 ─── embedding 工作, retrieve + associate
Phase 4 衍生 ─── LLM 稳定衍生 (total_derived>1000 + 本轮 derived>0) 🎯 当前
Phase 5 江山 ─── KG 节点≥10K + 关系≥20K
Phase 6 星海 ─── AI 员工≥500 active + EigenFlux≥100K 消息
Phase 7 归一 ─── 跨域衍生知识≥5000
Phase 8 永恒 ─── 自主演化闭环稳定 30 天
```

### 关键配置 (checkpoint)

```json
{
  "evolution_phase": 4,
  "evolution_phase_name": "衍生",
  "cycle_count": 66,
  "total_vectors": 0,
  "total_derived": 3818,
  "total_associations": 7834,
  "total_reinforced": 34501,
  "similarity_threshold": 0.55,
  "reinforce_threshold": 0.8,
  "batch_size": 50,
  "eigenflux_last_msg_id": 3200,
  "eigenflux_total_ingested": 3200
}
```

### DB 表

| 表 | 用途 |
|----|------|
| `mt_evolution_runs` | 每轮演化耗时/产出/suggestions JSON |
| `mt_evolution_log` | 演化 action/severity/status |
| `mt_derived_knowledge` | Stage 4 结构化衍生知识 |
| `ai_brain_enhanced_knowledge` | 脑库增强知识 (含 auto_derive 产出) |
| `knowledge_graph_nodes` | KG 节点 (Stage 3/8 写入) |
| `knowledge_graph_relations` | KG 关系 |
| `mt_evolution_suggestions` | 演化智能建议 |
| `mt_ai_eigenflux_messages` | EigenFlux 消息 (Stage 0 摄入源) |

### 自举闭环核心代码路径

```
auto_derive → 写 mt_derived_knowledge + ai_brain_enhanced_knowledge
            → 反向驱动 eigenflux_comm_messages (message_type=DERIVED_KNOWLEDGE)
            → Stage 9 broadcast 推给 5 AI 员工
            → EigenFlux 讨论产生新消息
            → 下轮 Stage 0 eigenflux_ingest 摄入
            → Stage 1 detect → Stage 2 retrieve → ...
            → 🌀 循环!
```

---

## 4. 数据库 8 分片

```
┌───────────────────────────────────────────────────┐
│              SQLite WAL · app.db                    │
│                                                     │
│  L0 极密 ──────────────────────────────────────    │
│  ├─ 用户密码哈希 (bcrypt)                           │
│  ├─ VIKEY 硬件指纹                                  │
│  └─ 仅 SA (wuchenghao15) 7 要素认证                 │
│                                                     │
│  L1 机密 ──────────────────────────────────────    │
│  ├─ AI 员工密钥                                     │
│  ├─ EigenFlux 私有通讯                              │
│  └─ 3 层 IRON_RULE 拦截日志                         │
│                                                     │
│  L2 秘密 ──────────────────────────────────────    │
│  ├─ 业务数据 (考试/题库/学习)                       │
│  ├─ 操作审计日志                                     │
│  └─ 透明加解密                                       │
│                                                     │
│  L3-L7 公开/分析 ──────────────────────────────     │
│  ├─ 公开配置                                         │
│  ├─ 教育资源索引                                     │
│  └─ 统计分析                                         │
└───────────────────────────────────────────────────┘
```

---

## 5. 安全纵深防御

```
┌─ Layer 0 · IRON_RULE (最高优先级 · 不可绕开) ──┐
│ §14 强制开发 12 步骤 · Git Hook 3 层拦截         │
│ dev_activity_preflight → pre_commit → before_req │
│ 任何人无 bypass，包括 SA                          │
└──────────────────────────────────────────────────┘
                         │
┌─ Layer 1 · 权限系统 ──────────────────────────┐
│ 11 级角色权限 · @system_container 装饰器         │
│ guest → login → admin → super_admin             │
│ VIKEY 硬件加密狗实时检测                          │
└──────────────────────────────────────────────────┘
                         │
┌─ Layer 2 · 中间件拦截 ─────────────────────────┐
│ system_container 6 字段验证                      │
│ 防盗链: 非首页 Referer + 未授权 → 重定向 /index   │
│ CSRF + XSS 防护                                  │
└──────────────────────────────────────────────────┘
                         │
┌─ Layer 3 · 数据安全 ───────────────────────────┐
│ WAL 模式 + busy_timeout 防并发                   │
│ 透明加解密 (L0 极密 bcrypt)                      │
│ §14 IRON_RULE 完整性自动扫描                      │
└──────────────────────────────────────────────────┘
```
