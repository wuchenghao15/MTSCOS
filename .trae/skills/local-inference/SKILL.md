---
name: "local-inference"
description: "本地 AI 推理引擎 (零token): chat/classify/review/bug_analysis, Ollama nomic-embed-text dim=768, local_ai_unified_gateway. Invoke when 用户要本地 AI 对话、思考、生成代码、审查、自动修代码(ai act 加强版)、只读运维操作。"
---

# 本地 AI 推理零 token 引擎

## 当用户说
- "本地 AI"、"零 token"、"不要调 API"
- "ai 命令"、"local_ai"、"本地推理"
- "ai act"、"ai fix"、"ai code review"

## 权威入口

**网关**: `flask-app/ai_engines/local_ai_unified_gateway.py`
**Ollama**: `http://127.0.0.1:11434` (nomic-embed-text:latest, dim=768)
**环境变量覆盖**:
- `MTSCOS_OLLAMA_EMBED_URL`
- `MTSCOS_OLLAMA_EMBED_MODEL`

## CLI 命令（用户终端直接跑）

```bash
# 统一入口
ai chat "你好仙女座"           # 本地 Ollama chat
ai think "题库怎么重建"         # 思考 (zero token)
ai code "写一个 Flask 蓝图"    # 生成代码
ai code_review flask-app/      # 代码审查
ai fix --flow_id flow_xxx_20261014  # ai act 加强版 code_fix
ai act --commit                  # 只读运维: 同步/状态/AI员工/巡检
ai status                       # 看 Ollama + token_savings
```

## Token 节省查询

```sql
SELECT * FROM mt_local_ai_token_savings ORDER BY date DESC LIMIT 10;
SELECT SUM(tokens_saved) FROM mt_local_ai_token_inference_log;
```

## Ollama 健康检查

```bash
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]"
# 看 embed 模型
curl -s http://127.0.0.1:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"hi"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'dim={len(d[\"embedding\"])}')"
```

## 零 token 铁律 (MT_RULE_DEV)

- 能本地解决的不调外部 API
- fail-closed：Ollama 不可达 → 中止不烧数据
- 禁止在 Flask 引擎里直接 `requests.post` 到外部 LLM
