# 仙女座大数据模型调用与配置说明

> **双路路由**: 本地 Ollama (零 token) → 火山引擎 ARK 云端兜底
> **统一网关**: flask-app/ai_engines/local_ai_unified_gateway.py
> **双路引擎**: flask-app/ai_engines/ai_dual_route_engine.py
> **更新日期**: 2026-10-17

---

## 1. 架构概览

```
调用方 (业务代码 / 引擎 / daemon)
    │
    ▼
local_ai_unified_gateway (统一网关)
    │
    ├── ollama_chat()    ──→ 本地 Ollama :11434 (qwen2.5:7b, 零token)
    ├── ollama_generate() ──→ 本地 Ollama 流式
    ├── ollama_classify() ──→ 本地 Ollama 分类
    ├── ollama_review()   ──→ 本地 Ollama 审查
    ├── ollama_bug_analysis() → 本地 Ollama Bug 分析
    │
    ▼ (本地不可用时自动兜底)
ai_dual_route_engine
    │
    └── volcengine_engine ──→ Volcengine ARK API (消耗 token)
```

### 1.1 路由优先级

1. **本地 Ollama 可用** → 本地推理（零 token 消耗）
2. **本地 Ollama 不可用** → Volcengine ARK 云端兜底（消耗 token）
3. **云端也不可用** → 回退本地（若此时本地恢复）

---

## 2. 本地 Ollama 配置

### 2.1 端口与模型

| 项 | 开发机 (DEV) | 生产 (PROD) | Mac mini 节点 |
|----|-------------|-------------|--------------|
| 端口 | :11434 | :11435 | :11435 |
| 对话模型 | qwen2.5:7b | qwen2.5:7b | qwen2.5:14b |
| 代码模型 | qwen2.5:7b | qwen2.5:7b | qwen2.5-coder:14b |
| Embedding | nomic-embed-text | nomic-embed-text | nomic-embed-text |
| embedding_dim | 768 | 768 | 768 |

### 2.2 环境变量

```bash
# Ollama 主服务
export OLLAMA_HOST="0.0.0.0:11434"
export OLLAMA_MODELS="/Users/wuchenghao/.ollama/models"

# 统一网关
export LOCAL_AI_GATEWAY="http://127.0.0.1:11434"
export PREFERRED_MODEL="qwen2.5:7b"
```

### 2.3 拉起与健康检查

```bash
# 启动 Ollama (macOS)
ollama serve

# 健康检查
curl http://127.0.0.1:11434/api/tags

# 拉取模型
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull nomic-embed-text
```

### 2.4 本地推理 API

```python
# flask-app/ai_engines/ai_ollama_engine.py
from ai_engines.ai_ollama_engine import chat

resp = chat(
    prompt="你好",
    model="qwen2.5:7b",
    system_prompt="你是 MTSCOS AI 助手",
    temperature=0.7,
)
# 返回: {"response": "...", "model": "qwen2.5:7b", "tokens_used": 0, "latency_ms": 120}
```

### 2.5 双路路由调用

```python
# flask-app/ai_engines/ai_dual_route_engine.py
from ai_engines.ai_dual_route_engine import dual_chat

resp = dual_chat(
    prompt="帮我写个 Python 函数",
    model="qwen2.5:7b",
    prefer_local=True,          # True=本地优先 (默认)
    fallback_cloud=True,        # True=本地不可用时云端兜底 (默认)
)
# resp: {"route": "ollama", "response": "...", "tokens_used": 0}
#       {"route": "volcengine", "response": "...", "tokens_used": 120}
#       {"route": "none", "response": None, "tokens_used": 0}  # 全部不可用
```

---

## 3. Volcengine ARK 云端配置

### 3.1 环境变量

```bash
export ARK_API_KEY="ark-xxxxxxxxxxxxxxxxxxxx"
export ARK_API_URL="https://ark.cn-beijing.volces.com/api/v3"
export ARK_MODEL="doubao-pro-32k"   # 兜底模型
```

### 3.2 可用性检测

```python
# flask-app/ai_engines/ai_dual_route_engine.py
from ai_engines.ai_volcengine_engine import is_available

if is_available():
    print("Volcengine ARK online")
```

### 3.3 云端调用

```python
from ai_engines.ai_volcengine_engine import chat

resp = chat(
    prompt="复杂推理任务",
    model="doubao-pro-32k",
    api_key=os.environ["ARK_API_KEY"],
)
# tokens 消耗记录会自动写入 mt_local_ai_token_savings 汇总表
```

---

## 4. Embedding 向量

### 4.1 本地 Embedding (零 token)

```python
# flask-app/ai_engines/ai_vector_store.py
# EMBEDDING_FUNCTIONS = {"word": ..., "nomic": ...}

from ai_engines.ai_vector_store import EMBEDDING_FUNCTIONS

embed_fn = EMBEDDING_FUNCTIONS.get("nomic")
vector = embed_fn("MTSCOS AI 系统的冰山意识引擎说明")
# vector: list[float] 768维
```

### 4.2 脑库向量化

```
源: mt_ai_brain_feed_log (脑库投喂)
→ nomic-embed-text (768维, 零token)
→ 向量存储 (flask-app/ai_engines/ai_vector_store.py)
→ drain 批量 api/embed + checkpoint 续传
```

### 4.3 支持的嵌入方法

| key | 引擎 | 维度 | token |
|-----|------|------|-------|
| `word` | Word2Vec (本地) | 可变 | 零 |
| `nomic` | Ollama nomic-embed-text | 768 | 零 |
| `openai` | OpenAI Embedding API | 1536 | 消耗 |

---

## 5. NeuralHub API 调用

### 5.1 统一入口 `/api/neuralhub/call`

```bash
curl -X POST http://localhost:8888/api/neuralhub/call \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b",
    "prompt": "分析这段代码的问题",
    "system": "你是代码审查专家",
    "prefer_local": true,
    "fallback_cloud": true
  }'
```

### 5.2 NeuralHub 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/neuralhub/routes` | 路由管理 |
| GET | `/api/neuralhub/models` | 可用模型 |
| GET | `/api/neuralhub/stats` | 调用统计 |
| POST | `/api/neuralhub/route_register` | 注册新路由 |
| DELETE | `/api/neuralhub/routes/<task_name>` | 删除路由 |
| GET | `/api/neuralhub/api_docs` | API 文档 |
| POST | `/api/neuralhub/self_upgrade_cycle` | 自升级周期 |

---

## 6. Mac mini 独立计算节点

### 6.1 拓扑

```
DEV 开发机 (MTSCOS_AI_Project)
  │
  ├── Flask :5000 (DEV 模式)
  └── Ollama :11435 (本地 qwen2.5:7b)

PROD 生产 (MTSCOS_PROD)
  │
  ├── Flask :5001 (SERVER 模式, 绑定 mtos.site)
  └── Ollama :11435 (与 DEV 共用端口)

Mac mini 计算节点
  │
  ├── Ollama :11435 (qwen2.5:14b + qwen2.5-coder:14b)
  └── mini_evolution_engine (独立计算进程)
```

### 6.2 mini_evolution_engine

```python
# flask-app/engines/mini_evolution_engine.py
# Mac mini 作为独立计算节点, 利用本地 Ollama
# 首次启动延迟 2 分钟（让 Flask + Ollama 先就绪）
```

---

## 7. 七位神将引擎

仙女座七大领域引擎，均优先本地 Ollama：

| 引擎 | 文件 | 说明 |
|------|------|------|
| 苍穹引擎 | `ai_cangjie_engine.py` | 仓颉造字 — 内容生成 |
| 云中引擎 | `ai_guanzhong_engine.py` | 关中天 — 知识整合 |
| 后羿引擎 | `ai_houyi_engine.py` | 后羿射日 — 精确命中 |
| 哪吒引擎 | `ai_nezha_engine.py` | 哪吒控魂 — 情感处理 |
| 神农引擎 | `ai_shennong_engine.py` | 神农百草 — 诊断修复 |
| 太公引擎 | `ai_taigong_engine.py` | 太公钓鱼 — 策略引擎 |
| 探路精灵 | `mini_evolution_engine.py` | Mac mini 独立计算 |

### 统一调用模式

```python
# 七位神将都支持双路路由 + 本地优先
# 示例 (后羿引擎)
from engines.ai_houyi_engine import HouyiEngine
eng = HouyiEngine()
resp = eng.execute(task="命中某类问题的根因", context={...})
# 内部自动: 优先 Ollama → 不可用则 Volcengine ARK
```

---

## 8. Token 消耗监控

### 8.1 记录表

| 表 | 说明 |
|----|------|
| `mt_local_ai_inference_log` | 每次推理记录 + tokens_saved |
| `mt_local_ai_token_savings` | 日汇总 token 节省 |

### 8.2 零 token 统计

```sql
SELECT SUM(tokens_saved) FROM mt_local_ai_token_savings;
SELECT DATE(created_at) as day, SUM(tokens_saved) as saved
FROM mt_local_ai_token_savings GROUP BY day ORDER BY day DESC LIMIT 30;
```

### 8.3 本地可用时云端兜底的 token 消耗规则

- **prefer_local=True, fallback_cloud=False**: 仅本地可用时返回; 本地不可用返回 None (零 token, 可能失败)
- **prefer_local=True, fallback_cloud=True** (默认): 本地 → 云端兜底 (可能消耗 token)
- **prefer_local=False**: 直接云端 (必然消耗 token)

---

## 9. 敏感数据保护

**禁止**将以下内容发送到外部 AI / 第三方服务：
- VIKEY 原始信息
- SZU100 固件
- EigenFlux 通信私钥
- mt_classified_data 中标注的 L0/L1 数据

**双路引擎会在调用前检查**：若输入包含 L0/L1 内容，仅走本地 Ollama（零 token + 不泄漏），禁止路由到 Volcengine ARK。

---

**flow_id**: flow_docs_sync_20261017 | **STEP_7_EXECUTE**