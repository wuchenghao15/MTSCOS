---
name: "iceberg-beautify"
description: "Beautifies iceberg/仙女座 pages: design token unification + translation-key CSS cleanup + admin hardcode color scan. Invoke when user asks to 美化冰山/仙女座页面、统一设计token、清翻译key注入、或修复 andromeda 模板 render 异常。"
---

# 冰山/仙女座 页面美化与统一

## 当用户说
- "美化冰山"、"仙女座页面美化"、"SA 页面美化"
- "统一设计 token"、"清硬编码颜色"
- "翻译 key 注入破坏 CSS"、"模板 render 异常"
- "让 AI 批量 beautify"

## 关键模板清单（active 不含 bak）

| 类型 | 模板 | 父级 |
|------|------|------|
| 冰山主页 | `andromeda_iceberg_center.html` | base_unified |
| 冰山演化 | `andromeda_iceberg_evolution.html` | base_unified |
| 冰山元域 | `andromeda_iceberg_meta.html` | 独立 HTML (暗主题) |
| 移动端 | `mobile/iceberg_manage.html` | 独立 HTML |
| SA 控制台 | `super_admin_dashboard.html` | 独立 HTML |
| admin base | `admin_app/base.html` | base_unified |

## 设计 Token 权威源

**CSS 文件**: `flask-app/static/assets/css/mtscos-design-system.css`
**变量前缀**: `--andromeda-*` (品牌主色) + `--primary/success/warning/danger/info-color` (语义色)

**禁硬编码色**（违反 MT_RULE_DESIGN）: `#10B981 / #34D399 / #EF4444 / #F87171 / #F59E0B / #FBBF24 / #6366F1 / #3B82F6`
替换：
- `#10B981,#34D399` → `var(--success-color),var(--andromeda-blue)`
- `#EF4444,#F87171` → `var(--danger-color),var(--andromeda-pink)`
- `#F59E0B,#FBBF24` → `var(--warning-color),var(--andromeda-gold)`

## 翻译 key 注入破坏 CSS 的根因

`{{ t('andromeda.冰　山　演　化_f177c2', default='冰　山　演　化') }}` 被误插入 CSS 变量值中间，导致：
```
--ink-light:#2C5F7C;{{ t(...) }}ght:#2C5F7C;  ← 变量名被插爆
font-family:'SF Pro',{{ t('东坡') }}Font,...  ← 字族字符串中断
```

**修复策略**: 找到 `:root {` 块中所有包含 `{{ t(` 且前面是 `--var-name:value` 的行 → 删除被破坏的整个块 → 保留下方 clean 的 `:root {` (通常模板里有 2 个 :root，第一个被破坏第二个完整)

## Jinja 语法冒烟（每改完模板跑）

```bash
cd flask-app && python3 << 'PYEOF'
import os, sys
sys.path.insert(0, '.')
from flask import Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
class _T:
    def __call__(self, key, default=None, *a, **kw): return default or key
app.jinja_env.globals['t'] = _T()

OK = FAIL = 0
for name in ['iceberg_center','iceberg_evolution','iceberg_meta','sa_dashboard','admin_base']:
    try:
        path = f"templates/{'mobile/' if 'iceberg' in name and 'meta' not in name else ''}{'andromeda_' if 'iceberg' in name and 'meta' not in name else ''}{name}.html"
        if 'meta' in name: path = 'templates/andromeda_iceberg_meta.html'
        if 'sa' in name: path = 'templates/super_admin_dashboard.html'
        if 'admin' in name: path = 'templates/admin_app/base.html'
        src = open(path).read()
        app.jinja_env.parse(src); print(f"  ✅ {name}"); OK += 1
    except Exception as e:
        print(f"  ❌ {name}: {e}"); FAIL += 1
print(f"\nJinja: {OK}/{OK+FAIL} PASS")
PYEOF
```

## 水墨风 vs 仙女座星系

- **iceberg_center**: 水墨 Token（`--ink-deep/light --snow --gold --seal-red`）— 保持
- **iceberg_meta**: 独立暗主题（仙女座深蓝紫渐变）— 保持
- **admin_app/base.html**: 仙女座星系主题（`--andromeda-purple/blue/pink/gold`）— 保持
- **super_admin_dashboard**: 用 `mtscos-design-system.css` — 保持，修损坏 tag 即可
