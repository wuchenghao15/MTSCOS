---
name: "flask-sqlite-column"
alwaysApply: false
description: "多 SQLite DB 列名不兼容分层 SELECT 模板. Invoke when Flask logs no such column."
---
# 多 SQLite DB 列名不兼容兼容

> 自动衍生引擎产出 · flow_id=auto_skill_deriver_v1_20260922 · 证据 2 条

## 解决什么问题
从 mt_iron_rule_violations / Flask log / dev_flow_events 聚类发现的高频问题模式.

## 已发现的坑 (来自真实证据)
| 1 | 证据: 从system_rules读取沙盒配置失败: no such column: rule_code... | 见 mt_iron_rule_violations / Flask log |
| 2 | 证据: [认证] 加载用户失败: no such column: is_active... | 见 mt_iron_rule_violations / Flask log |

## 预防模板
1. 写代码前查 mt_iron_rule_violations 是否已有同类违规
2. Flask 请求先过 dev_activity_preflight (before_request[0])
3. Schema 变更后重启 Flask 看启动警告

## 快速命令
```bash
# 查同类违规历史
cd flask-app && python3 -c "
import sqlite3; c=sqlite3.connect('engines/app.db')
rows=c.execute("SELECT * FROM mt_iron_rule_violations WHERE viol_context LIKE '%flask-sqlite-column%'").fetchall()
print(f'  同类违规: {len(rows)} 条')
"
```