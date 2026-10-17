---
name: "rule-integrity"
description: "规则完整性自检 + RULE_META 解析 + 弱约束词清零 + 9篇规则覆盖率扫描. Invoke when 用户查规则完整性、RULE_META 版本、弱约束词、§14 合规、或想跑一次 rule_integrity_scanner。"
---

# 规则治理与完整性自检

## 当用户说
- "规则完整性"、"RULE_META"、"弱约束词"
- "rule_integrity"、"覆盖率"、"§14 合规"
- "规则版本"、"v1.3.0"、"changelog"

## 权威文件

**规则目录**: `.trae/rules/` (12 篇 L0-L1-L2 规则)
**规则总索引**: `.trae/rules/00-规则总索引.md` (v3.1.0)
**代码引擎**: `flask-app/ai_engines/rules_engine/` (8 组件)
**daemon**: `sys_rule_enforcer` (周期 300s, 学习 9 篇规则 + 弱约束词扫描)

## RULE_META 格式（每篇规则文件头部）

```yaml
---
rule_id: MT_IRON_RULE_12STEPS / MT_RULE_DEV / ...
version: v1.3.0
status: ACTIVE / DEPRECATED / ARCHIVED
depends_on: [MT_RULE_GOVERNANCE, MT_RULE_PERM]
enforcement_level: L0 / L1 / L2
trigger_conditions: [commit, push, api_call, page_load]
---
```

## 快速自检脚本

```bash
cd flask-app && python3 ai_engines/rules_engine/rule_integrity_scanner.py scan \
  --rules-dir ../.trae/rules/ \
  --weak-words "应该|建议|可以|尽量|最好" \
  --report report.json
```

## 版本变更落库 (rule_changelog)

```sql
SELECT rule_id, to_version, change_type, change_summary, sa_final_decision, created_at
FROM mt_rule_changelog
ORDER BY created_at DESC LIMIT 10;
```

## 弱约束词清零 (auto_rule_strengthener)

daemon 自动把弱约束词（"应该"/"建议"/"可以"）替换成强约束词（"必须"/"禁止"/"强制"）。

## 9 篇规则版本快照

| RULE_ID | 文件 | 版本 |
|---------|------|------|
| MT_IRON_RULE_12STEPS | §14强制开发12步骤独立约束规则.md | v1.3.0 |
| MT_RULE_DEV | 开发规则.md | v1.2.0 |
| MT_RULE_DESIGN | 设计规范.md | v1.1.0 |
| MT_RULE_PERM | 用户权限.md | v1.2.0 |
| MT_RULE_AI_OPS | AI系统操作规范.md | v1.2.0 |
| MT_RULE_SYS_OPS | 系统操作规范.md | v1.3.0 |
| MT_RULE_PARAM | 系统参数数据规范与操作规范.md | v1.1.0 |
| MT_RULE_SRC_MOD | 源码修改准则参考与思路方案.md | v1.1.0 |
| MT_RULE_QBANK | 题库管理规范与准则.md | v1.1.0 |
| MT_RULE_VERSION | 版本升级规则.md | v1.0.0 |
| MT_RULE_GOVERNANCE | 规则治理与一致性规范.md | v1.0.0 |
| MT_RULE_CLASSIFICATION | 机密等级与访问控制规范.md | v1.0.0 |
