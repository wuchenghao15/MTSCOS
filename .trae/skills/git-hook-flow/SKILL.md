---
name: "git-hook-flow"
description: "§14 IRON_RULE pre-commit hook + commit flow_id 格式 + bypass-for-sa (需VIKEY在线). Invoke when commit 被拒、hook 说缺 flow_id、git push 被拦截、或需要 SA bypass。"
---

# §14 IRON_RULE Git Hook 强制执行

## 当用户说
- "commit 被拒"、"hook 报错"、"git push 被拦截"
- "缺 flow_id"、"pre-commit hook"
- "bypass-for-sa"、"怎么跳过 hook"

## Hook 4 层拦截架构

```
┌─ Git pre-commit ─┐  拦截未走7步审批的规则修改
│                   │  校验 mt_rule_changelog.approved_by_7step=1
│                   │  SA bypass: git commit --bypass-for-sa (VIKEY 在线)
└─ Flask before_req ─┐  拦截 /api/rules/*, /api/rule/*, /admin/rule
│                    │  返回 403 + 落库 mt_rule_violation_alert
└─ CI Check ─────┐  1000 轮测试 (正常400+异常300+黑客300)
│                │  9 篇规则覆盖率报告
└─ Git pre-push ──┐  校验 commit msg 含 flow_id
                   │  校验 mt_dev_flow_session.final_status='DONE'
                   │  未完成 12 步骤 → git push 拒绝
```

## Commit msg 强制格式

```
[flow_{领域}_{日期} STEP_N] 变更摘要

# 必须含 flow_id=flow_xxx_20261014
# 必须含 STEP_N (STEP_7_EXECUTE / STEP_12_DONE)
# 必须简短说明做了什么
```

## SA 紧急 Bypass（唯一合法绕过方式）

```bash
git commit --bypass-for-sa -m "hotfix"
# hook 会检查: VIKEY 在线 + SZU100 authentic + 本机 loopback
# 非 SA 一律报错，且会落库 mt_iron_rule_violations
```

## Hook 源码位置

**部署目标**: `.git/hooks/pre-commit`（2 个仓库：项目根 + flask-app）
**模板**: `flask-app/ai_engines/rules_engine/templates/pre-commit-rule-check.sh`
**引擎**: `flask-app/ai_engines/rules_engine/rule_pre_commit.py`

## 违反落库

```sql
SELECT id, flow_id, event_type, severity, description, timestamp
FROM mt_iron_rule_violations
ORDER BY timestamp DESC LIMIT 20;
```

## Hook 临时关闭（仅本地调试，commit 后立即重新开）

```bash
# 禁用 (⚠️ 临时! 仅限调试)
git config core.hooksPath /dev/null
# 恢复
git config --unset core.hooksPath
```
