---
name: exam-auto
description: 考试自动引擎 (flow_exam_auto_20261020) — 按真实时间自动获取摸底/自主招生/月考/模拟/期末测试题(自由行或专有), 自动分析+入题库(含结题讲解), 任务大厅自动认领(教育题库中心), 对应团队自动学习+自动备课, 企微播报+全量审计。Invoke when 用户要自动获取考试题、自动入题库、自动备课、考试季自动出题, 或查考试引擎状态。
---

# 考试自动引擎 (exam-auto)

## 解决的核心问题
真实时间驱动的考试题自动化闭环: 时间日历判定 → 真实题源取题 → 分析去重 → 入
`question_bank`(含结题讲解) → 任务大厅自动认领 → 对应团队自动学习 → 自动备课方案落库。

## 引擎位置
- 引擎: `flask-app/engines/ai_exam_auto_engine.py`
- API: `POST /api/ai-edu/exam-auto/run` · `GET /api/ai-edu/exam-auto/status`
- 后台: 管理中心 → 「📅 考试自动引擎」卡片

## 真实时间考试日历 (EXAM_WINDOWS)
| 考试类型 | 时间窗口 | 专有题源 (真实表) |
|---|---|---|
| 摸底测试 | 2/20-3/10 · 8/25-9/15 | adult_education_questions (成人高考/国开) |
| 自主招生测试 | 3/1-4/14 | professional_exam_questions (考研/公务员) |
| 模拟测试 | 4/15-6/10 | professional_exam_questions (考研/四六级) |
| 期末测试 | 6/11-7/10 · 12/25-12/31 | adult_education_questions 全部 |
| 月考测试 | 每月 20日-月末 | adult_education_questions (自考/网教) |
| 自由行专项 | 全年兜底 | mt_exam_questions_pool + question_bank 轮换 |

## 硬约束 (铁律)
- **数据库唯一数据源**: 只从真实题源表取题, 无真实答案的题拒收 (`_PLACEHOLDER_ANSWERS` 过滤), 禁止假数据
- **去重**: md5(content) 双重校验 (question_content_hashes + 本批集合)
- **零token**: 结题讲解规则模板生成; 本地 Ollama 增强备课摘要仅显式 `use_local=True` 时启用
- **全量审计**: EXAM_AUTO_RUN / EXAM_AUTO_CLAIM 落 mt_lab_audit_log + logs/center_audit.log
- **自动认领**: 大厅任务 description 必含教育题库中心关键词, 由 run_hall_auto 分配+5席磋商

## 使用
```bash
python3 engines/ai_exam_auto_engine.py calendar   # 查看真实时间窗口
python3 engines/ai_exam_auto_engine.py run        # 执行一轮全链路
python3 engines/ai_exam_auto_engine.py status     # 批次状态+备课计划
```
API 调用: `POST /api/ai-edu/exam-auto/run` body `{"local": false}`

## 产出表
- `mt_exam_auto_log` — 每次批次 (取/入/重/模式/题号)
- `mt_exam_prep_plans` — 自动备课方案 (markdown: 题情分析/教学安排/结题讲解要点)
- `question_bank` source='exam_auto' — 入库题 (tags=考试类型, 含结题讲解)
- `mt_edu_learning_log` — 团队学习完成档案 (COMPLETED + 知识沉淀)
