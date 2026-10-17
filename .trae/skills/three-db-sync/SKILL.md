---
name: "three-db-sync"
description: "Runs 三库白名单同步 + 一致性校验: 主库 app.db ↔ 镜像库（仅 mt_dev_flow_session/events/iron_rule_violations 三张表）. Invoke when user 查三库 sync、镜像库不一致、或想主动跑一次 verify。"
---

# 三库白名单同步与一致性校验

## 当用户说
- "三库同步"、"镜像库不一致"、"跑一下 sync"
- "verify"、"主库镜像库对一下"
- "哪些表入镜像"

## 三库位置

```
主库:   flask-app/database/app.db            (question_bank 1.57M + 全量数据)
镜像库: _runtime/databases/MIRROR/app.db      (白名单 3 张表)
三库同步由 ai_smart_mount_engine.py daemon 驱动
```

## 白名单（仅这 3 张表入镜像）

```sql
-- 1. flow session (所有 STEP 状态)
-- 2. flow events (步骤事件链)
-- 3. iron_rule_violations (§14 铁律违反, 不可删除)
```
**question_bank 不入镜像**（BLOB 量级无收益）

## 同步脚本

```bash
cd flask-app/engines
python3 ai_smart_mount_engine.py sync     --verify    --tables mt_dev_flow_session,mt_dev_flow_events,mt_iron_rule_violations
python3 ai_smart_mount_engine.py verify   --strict     --diff-limit 10
```

## 一致性校验 SQL

```sql
-- 表级行数一致
SELECT 'session' AS t, COUNT(*) FROM main.mt_dev_flow_session
UNION ALL
SELECT 'events', COUNT(*) FROM main.mt_dev_flow_events
UNION ALL
SELECT 'violations', COUNT(*) FROM main.mt_iron_rule_violations;
-- 对比镜像库相同查询

-- STEP_12_DONE 必须双库同时存在
SELECT flow_id FROM main.mt_dev_flow_session WHERE final_status='DONE'
EXCEPT
SELECT flow_id FROM mirror.mt_dev_flow_session WHERE final_status='DONE';
```

## 三库漂移常见根因

| 症状 | 根因 | 修复 |
|------|------|------|
| 镜像库缺行 | daemon 断挂 | 重启 smart_mount_engine → 自动补 |
| 主库被写入测试数据 | 本地调试残留 | `DELETE FROM mt_dev_flow_session WHERE flow_id LIKE '%test%'` |
| WAL 锁冲突 | Flask 持连接 | 等 Flask 关 / `PRAGMA wal_checkpoint(TRUNCATE)` |
