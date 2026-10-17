---
name: "dev-flow-step"
description: "§14 开发12步骤立项落库脚本 — 注册 flow_id + STEP_7_EXECUTE + STEP_12_DONE 自动化. Invoke when 要启动新开发任务、查当前 flow 状态、或把 STEP_7 落库 STEP_12_DONE。"
---

# §14 开发 12 步骤 自动化落库

## 当用户说
- "立项"、"注册 flow"、"STEP_7"、"STEP_12"
- "flow_id 命名"、"查一下哪些 flow 在跑"
- "把 flow 标记完成"、"落库 DONE"

## 12 步骤状态机

```
STEP_1_PROPOSAL → STEP_2_AUDIT → STEP_3_DECISION → STEP_4_PLAN
→ STEP_5_IMPLEMENT → STEP_6_TEST → STEP_7_EXECUTE（主写码步, 80% 时间）
→ STEP_8_SMOKE (Jinja parse + Flask client HTTP)
→ STEP_10_AUTO_TEST (1000 轮: 正常 400 + 异常 300 + 黑客 300, vuln=0)
→ STEP_12_DONE
```

## 快速立项脚本

```python
import sqlite3, json
from datetime import datetime
DB = "flask-app/database/app.db"
c = sqlite3.connect(DB, timeout=10)
NOW = datetime.now().isoformat()
FLOW_ID = "flow_{领域}_{日期}"  # e.g. flow_qbank_rebuild_20261014
c.execute("""
    INSERT OR REPLACE INTO mt_dev_flow_session
    (flow_id, proposal_title, proposal_summary, proposal_json,
     current_step, final_status, smart_upgrade_version, created_at, updated_at, created_by)
    VALUES (?, ?, ?, ?, 'STEP_7_EXECUTE', 'OPEN', 'v22.23.2', ?, ?, 'super_admin_wuchenghao15')
""", (FLOW_ID, "标题", "一句话说明", json.dumps({"scope":["..."]}, ensure_ascii=False), NOW, NOW))
c.commit()
print(f"flow={FLOW_ID} → STEP_7_EXECUTE / OPEN")
```

## STEP_12_DONE 落库脚本

```python
COMMIT = "abc1234"
c.execute("""
    UPDATE mt_dev_flow_session SET
        current_step='STEP_12_DONE', final_status='DONE',
        git_sync_commit_hash=?, git_sync_commit_subject=?, git_sync_status='SYNCED',
        test1000_total=X, test1000_pass=X, test1000_fail=0, test1000_vuln=0,
        acceptance_passed=1, updated_at=?
    WHERE flow_id=?
""", (COMMIT, "[flow_xxx STEP_7] 变更摘要", NOW, FLOW_ID))
```

## Events 写入

```python
for from_s, to_s, kind, payload in [...]:
    c.execute("""INSERT INTO mt_dev_flow_events
        (flow_id,from_step,to_step,event_kind,event_payload_json,triggered_by,triggered_at)
        VALUES (?,?,?,?,?,?,?)""",
        (FLOW_ID, from_s, to_s, kind, json.dumps(payload, ensure_ascii=False), 'AI', NOW))
c.commit()
```

## Commit msg 必须含 flow_id

```
[flow_qbank_rebuild_20261014 STEP_7] question_bank RENAME + TEXT 难度 + 索引
```

## Hook 拦截

- pre-commit: 校验 msg 含 `flow_id=`
- pre-push: 校验 `mt_dev_flow_session.final_status='DONE'`
- 非 DONE flow → 禁止 push
