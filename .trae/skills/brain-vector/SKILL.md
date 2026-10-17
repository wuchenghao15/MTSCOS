---
name: "brain-vector"
description: "AI脑库向量化引擎 (本地 Ollama embed 768维零token + drain 批量 api/embed + checkpoint 续传) + qbank_brain_adapter 脑库→题库批量转换. Invoke when 用户查向量 drain、checkpoint 续传、embed 速度调优、或想把脑库 1.567M 行灌进题库。"
---

# AI 脑库向量化 + 脑库→题库转换

## 当用户说
- "向量 drain"、"checkpoint 续传"、"embed 速度"
- "脑库→题库"、"adapt"、"全量转换"
- "mt_ai_brain_vector"、"mt_brain_vector_queue"

## 权威入口

**向量引擎**: `flask-app/engines/ai_brain_vector_engine.py` (daemon 周期触发)
**转换引擎**: `flask-app/engines/qbank_brain_adapter.py`
**Ollama**: `http://127.0.0.1:11434` nomic-embed-text:latest dim=768

## 当前规模

```sql
SELECT COUNT(*) FROM mt_ai_brain_enhanced_knowledge;  -- 脑库 1,567,750
SELECT COUNT(*) FROM mt_brain_vector_queue WHERE status='DONE';
SELECT COUNT(*) FROM mt_brain_vector_queue WHERE status='PENDING';
SELECT COUNT(*) FROM mt_ai_brain_vector;  -- 已入向量表
SELECT COUNT(*) FROM question_bank;        -- 题库 1,577,330
```

## 批量 embed (44× 加速)

```python
# 旧: 单条 /api/embeddings → 3.2 条/s (串行 + HTTP 开销)
# 新: /api/embed input: [str1, str2, ...] → 141 条/s
# drain 用 executemany 批入队 → 5000/chunk

# Ollama API 端点 (Ollama 0.5+)
POST http://127.0.0.1:11434/api/embed
{"model":"nomic-embed-text","input":["text1","text2",...]}
→ {"embeddings":[[dim=768],[dim=768],...]}
```

## CLI

```bash
# 向量 drain (后台跑, 每 6s +1000, 141条/s)
cd flask-app/engines
nohup python3 ai_brain_vector_engine.py drain > /tmp/vector_drain.log 2>&1 &
tail -f /tmp/vector_drain.log

# 脑库→题库 adapt
python3 qbank_brain_adapter.py adapt --prefix EIGENFLUX- --chunk 5000 --limit 50000
python3 qbank_brain_adapter.py adapt --chunk 5000   # 全量 (checkpoint 续传)
python3 qbank_brain_adapter.py status
python3 qbank_brain_adapter.py verify
python3 qbank_brain_adapter.py rebalance --easy-pct 0.20 --medium-pct 0.30
```

## checkpoint 表

```sql
SELECT * FROM mt_brain_vector_checkpoint ORDER BY id DESC LIMIT 5;
SELECT * FROM mt_qbank_brain_adapter_checkpoint WHERE job_key='default';
```

## Fail-closed 硬约束

- Ollama 不可达 → 中止不烧数据 (queue 保留 PENDING)
- queue attempts ≥ 5 → 熔断 FAILED
- INSERT OR IGNORE 天然去重 (旧 NOT EXISTS 反连接卡死 0.5 小时)
- `_queue_item.content[:2000]` 限长 → SQLite VARCHAR 不爆
