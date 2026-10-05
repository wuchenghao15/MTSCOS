---
name: "flask-blueprint-path"
alwaysApply: false
description: "Flask Blueprint url_prefix + route 路径陷阱速查. Invoke when writing Flask Blueprint routes, debugging 404s."
---
# Flask Blueprint url_prefix + route 路径陷阱

> 自动衍生引擎产出 · flow_id=auto_skill_deriver_v1_20260922 · 证据 12 条

## 解决什么问题
从 mt_iron_rule_violations / Flask log / dev_flow_events 聚类发现的高频问题模式.

## 已发现的坑 (来自真实证据)
| 1 | 证据: ✓ Blueprint 注册完成: 新增 26 个, 跳过 0 个已注册, 失败 0 个... | 见 mt_iron_rule_violations / Flask log |
| 2 | 证据: [Routes] Blueprint 统一注册完成... | 见 mt_iron_rule_violations / Flask log |
| 3 | 证据: [AI-MATRIX] Blueprint ai_matrix_api 已注册: 7 个路由... | 见 mt_iron_rule_violations / Flask log |
| 4 | 证据: [AI-ROLES] Blueprint ai_roles_api 已注册: 4 路由... | 见 mt_iron_rule_violations / Flask log |
| 5 | 证据: [CRYPTO-API] Blueprint crypto_api 注册: 8 路由... | 见 mt_iron_rule_violations / Flask log |

## 预防模板
1. 写代码前查 mt_iron_rule_violations 是否已有同类违规
2. Flask 请求先过 dev_activity_preflight (before_request[0])
3. Schema 变更后重启 Flask 看启动警告

## 快速命令
```bash
# 查同类违规历史
cd flask-app && python3 -c "
import sqlite3; c=sqlite3.connect('engines/app.db')
rows=c.execute("SELECT * FROM mt_iron_rule_violations WHERE viol_context LIKE '%flask-blueprint-path%'").fetchall()
print(f'  同类违规: {len(rows)} 条')
"
```