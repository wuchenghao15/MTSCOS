---
name: "j2-template-fix"
description: "Fixes Jinja templates where {{ t('i18n_key') }} got injected into CSS variable values, HTML tags, or scripts breaking render. Invoke when templates don't render、CSS variable names contain {{ t(、或翻译key污染 style block / <title> 标签 / font-family 值。"
---

# Jinja 模板翻译 Key 注入修复

## 根因
i18n 工具链把 `{{ t('key', default='中文') }}` 误插在 CSS 变量值、font-family 值、HTML tag 属性等非自然语言位置。

## 诊断脚本

```bash
cd flask-app/templates
# 扫描所有含 {{ t( 且紧邻 CSS/HTML 标记的可疑行
grep -rn '{{ t(' --include='*.html' | grep -E '(--[a-z-]+:|font-family|style=|<title|<button|<div|<span|background|color|border|text-align)' | head -20
```

## 典型破坏形态

| 破坏类型 | 示例 | 修复 |
|----------|------|------|
| CSS var 名被插爆 | `--ink-light:#2C5F7C;{{ t(...) }}ght:#2C5F7C` | 删除被破坏行，保留下方 clean `:root` |
| font-family 中断 | `'SF Pro',{{ t('东坡') }}Font` | 找模板里第二个完整 font-family 块 |
| HTML tag 断裂 | `<title>{{ t(...) }}控制台') }}</title>` | 清理为纯文本 `<title>超级管理员控制台</title>` |
| CSS 类名中插 | `.b{{ t('承天寺') }}{` | 找下方对应的 `.box, .panel, .card {` 或 `.block {` |
| CSS 属性值被插 | `color:var(--text-mu{{ t('赤壁') }};` | 用完整下方 clean 块替换整个 style 段 |

## 修复策略

**Step 1** 先 parse 检查（Jinja 错误 → 模板根本不能渲染）
```python
app.jinja_env.parse(open('template.html').read())  # 抛异常 = render 已爆
```

**Step 2** 定位被破坏的 style 块起始行号（第一个 `:root {`）
**Step 3** 扫描整个文件找第二个（或最后一个）完整无 `{{ t(` 污染的 `:root {` → 把两个 `:root {` 之间所有被破坏行全部删除
**Step 4** 检查 `<title>`, `<meta>`, `<body>` 等 HTML tag 是否也被插爆 → 替换为纯文本
**Step 5** Jinja 重新 parse + 跑 Flask smoke 确认 HTTP 200

## 安全网

- 修复前 cp 一份 `.bak_{ts}`
- `git diff` 只看模板文件
- 修复后立即跑 `flask-smoke-tester`（L1 路由注册 / L2 页面 HTTP / L3 API JSON）
