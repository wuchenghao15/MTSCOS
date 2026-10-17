---
name: "qbank-inspection"
description: "MT_RULE_QBANK §12 11项题库质量巡检 (格式/完整性/重复/标签/分类/难度/来源/时效/答案/解析/合规) + rebalance_difficulty CLI. Invoke when 查题库质量、解释空、标签空、答案重复、难度分错、或想跑一次 1000 轮题库巡检。"
---

# MT_RULE_QBANK §12 题库 11 项巡检

## 当用户说
- "题库质量"、"解释空"、"标签空"、"答案重复"
- "难度分错了"、"检查 11 项"、"MT_RULE_QBANK"
- "rebalance difficulty"、"题库巡检"

## 题库当前快照

```sql
SELECT COUNT(*) FROM question_bank;
-- 全量 1,577,330 行 (9,587 手录 + 1,567,742 脑库转换)
SELECT difficulty, COUNT(*) FROM question_bank GROUP BY difficulty;
-- easy 309K (19.6%) | medium 312K (19.8%) | hard 956K (60.6%)
SELECT source, COUNT(*) FROM question_bank GROUP BY source;
-- structured 1,226K | eigenflux_comm 339K | ai_generated 9.6K
SELECT COUNT(*) FROM question_bank WHERE explanation IS NULL OR explanation='';
SELECT COUNT(*) FROM question_bank WHERE tags IS NULL OR tags='[]' OR tags='';
SELECT COUNT(*) FROM question_bank WHERE answer IS NULL OR answer='';
```

## §12 11 项巡检项

| # | 巡检项 | 硬约束 | 违反处理 |
|---|--------|--------|----------|
| 1 | 格式合法性 | JSON 可解析 / TEXT 长度 ≤ 5000 | 自动修 / 打标 |
| 2 | 完整性 | 每题必须有 explanation | 占位符填充 |
| 3 | 重复检测 | question_id UNIQUE / content 相似度 | 合并 / 去重 |
| 4 | 标签 | ≥ 3 个有效标签 | 自动回填 ["学科","题型","难度"] |
| 5 | 学科分类 | 9 大类 (语文/数学/英语/物理/化学/生物/历史/地理/政治) | 强制分类 |
| 6 | 难度分布 | easy 20% / medium 30% / hard 50% | rebalance |
| 7 | 题目源 | 44 种合法 source_type | 白名单外打标 |
| 8 | 时效 | 过期自动归档 (过期时间由 source_type 定义) | 归档 |
| 9 | 答案存在 | answer 非空 + correct_answer 双写 | 补默认 |
| 10 | 解析存在 | explanation 非空 | 占位符 |
| 11 | 合规 | 敏感词 / 机密等级 | fail-closed 拒绝入正式库 |

## rebalance CLI

```bash
cd flask-app/engines
python3 qbank_brain_adapter.py rebalance --easy-pct 0.20 --medium-pct 0.30 --chunk 50000
python3 qbank_brain_adapter.py verify   --limit 1000
python3 qbank_brain_adapter.py status   # checkpoint 续传
python3 qbank_brain_adapter.py adapt    # 脑库→题库批量转换
```

## 辅助表一致性

```sql
-- question_id 是 TEXT 类型（匹配 question_bank.question_id）
SELECT 'map', COUNT(*) FROM question_knowledge_map
UNION ALL SELECT 'hash', COUNT(*) FROM question_content_hashes
UNION ALL SELECT 'calib', COUNT(*) FROM question_difficulty_calibration
UNION ALL SELECT 'maintenance', COUNT(*) FROM ai_maintenance_questions;

-- orphan 检查 (辅助表 question_id 无对应 question_bank)
SELECT COUNT(*) FROM question_knowledge_map m
WHERE NOT EXISTS (SELECT 1 FROM question_bank q WHERE q.question_id = m.question_id);
```
