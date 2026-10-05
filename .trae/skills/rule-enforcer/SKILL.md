---
name: "rule-enforcer"
alwaysApply: false
description: "§14 IRON_RULE 强制执行 + dev_activity_preflight 接线. Invoke when agent writes code without flow_id."
---
# §14 铁律强制执行

> 自动衍生引擎产出 · flow_id=auto_skill_deriver_v1_20260922 · 证据 12 条

## 解决什么问题
从 mt_iron_rule_violations / Flask log / dev_flow_events 聚类发现的高频问题模式.

## 已发现的坑 (来自真实证据)
| 1 | 证据: [VIOL:MT_IR_D1] Agent 直接改代码 (auth_routes.py + serv... | 见 mt_iron_rule_violations / Flask log |
| 2 | 证据: [VIOL:MT_IR_D2] Agent 状态跳步 STEP_1 → STEP_7，跳过 STEP... | 见 mt_iron_rule_violations / Flask log |
| 3 | 证据: [VIOL:MT_IR_D3] A 轮 4 方强制出席未满足: A组51人缺席, EigenFlux... | 见 mt_iron_rule_violations / Flask log |
| 4 | 证据: [VIOL:MT_IR_D4] STEP_4 孙文档会议记录员未参与, mt_dev_flow_ev... | 见 mt_iron_rule_violations / Flask log |
| 5 | 证据: [VIOL:MT_IR_D5] 验收不通过分支未走 loopback, mt_ai_brain_fe... | 见 mt_iron_rule_violations / Flask log |

## 预防模板
1. 写代码前查 mt_iron_rule_violations 是否已有同类违规
2. Flask 请求先过 dev_activity_preflight (before_request[0])
3. Schema 变更后重启 Flask 看启动警告

## 快速命令
```bash
# 查同类违规历史
cd flask-app && python3 -c "
import sqlite3; c=sqlite3.connect('engines/app.db')
rows=c.execute("SELECT * FROM mt_iron_rule_violations WHERE viol_context LIKE '%rule-enforcer%'").fetchall()
print(f'  同类违规: {len(rows)} 条')
"
```