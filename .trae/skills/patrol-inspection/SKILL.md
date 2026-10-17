---
name: "patrol-inspection"
description: "源码巡逻队 (6人AI) + 深度巡检 (页面/路由/代码+AI团队路由) + 文案合规巡检. Invoke when 用户说 patrol/巡检、语法/导入/模式错误扫描、1000轮冒烟、文案缺失/重复/占位符、或代码审查。"
---

# 巡逻/深度/文案 三类巡检

## 当用户说
- "patrol"、"源码巡检"、"扫一下代码"
- "deep_inspection"、"页面巡检"、"路由巡检"
- "copy_inspection"、"文案合规"、"占位符"
- "1000 轮"、"冒烟"、"smoke test"

## 三套引擎

| 引擎 | 文件 | 周期 | 人数 | 扫描面 |
|------|------|------|------|--------|
| **源码巡逻** | `engines/auto_patrol_engine.py` | 300s | 6 人 (巡检/收集/修复/验证/报告/持久AI) | 语法/导入/模式错误 |
| **深度巡检** | `engines/deep_inspection_engine.py` | 600s | AI 团队 | 页面 HTML / Flask 路由 / 模板 render |
| **文案巡检** | `engines/copy_inspection_engine.py` | 900s | — | 缺失/重复/占位符/硬编码 |

## 快速触发

```bash
cd flask-app/engines
python3 auto_patrol_engine.py run --scope flask-app/ --level 3
python3 deep_inspection_engine.py page  --url /iceberg
python3 deep_inspection_engine.py route --name iceberg_bp
python3 copy_inspection_engine.py scan  --dir templates/
```

## 1000 轮冒烟 §14 要求

```bash
# L1 路由注册: 蓝图 import + url_prefix
# L2 页面 HTTP: Flask client GET → status 200
# L3 API JSON: 路由 GET → json.has_key('success')
python3 ai_smart_mount_engine.py patrol --smoke --rounds 1000
```

## 常见扫出的问题

| 类型 | 表现 | 修复 |
|------|------|------|
| `unused import` | 残留 `typing`/`dataclass` (PEP649 潜伏) | 删掉 |
| `SyntaxError` | Flask 蓝图循环 import | 拆到 engines/ 子包 |
| `route 404` | url_prefix 漏写 `/` | `/admin_app/` ✓ |
| 文案占位符 | `{{ t('xxx', default='') }}` 空 default | 补中文 |
| 硬编码色 | `#10B981 / #34D399 / #EF4444` | 走 `var(--success-color)` |
