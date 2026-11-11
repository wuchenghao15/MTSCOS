#!/usr/bin/env python3
"""
patch_design_system.py — 批量注入 MTSCOS 统一设计系统
扫描 templates/*.html, 为所有包含 andromeda/gobelin 关键词但缺少 tokens.css 的页面
自动注入 CSS 链接 + body 主题 class

规则:
  1. 幂等 — 重复运行不会双倍注入
  2. 自动识别 — 按文件名/正文关键词匹配主题
  3. 安全 — 先 --dry-run 预览再应用

用法:
  python3 scripts/patch_design_system.py --dry-run    # 预览
  python3 scripts/patch_design_system.py               # 应用
"""

import os
import re
import sys
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / 'templates'

# 要注入的 CSS 块
CSS_LINKS_BLOCK = """<!-- MTSCOS Unified Design System -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/global_design_bridge.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/andromeda.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/gobelin.css') }}">"""

# 主题关键词 → class 映射 (同时匹配文件名和文件正文)
THEME_KEYWORDS = {
    'andromeda-theme': [
        'andromeda', '仙女座', 'nebula', '星云',
    ],
    'gobelin-theme': [
        'gobelin', '古灵阁', 'trading_console', '操盘',
    ],
}

# 要跳过的文件 (base 模板已经自己管理 CSS)
SKIP_FILES = {
    'base.html', 'base_unified.html', 'base_layout.html',
    'exception_base.html', 'user_info_bar.html', 'error.html',
    'login_required.html', 'logout.html', '401.html', '403.html',
    '404.html', '500.html', '423.html', '502.html', '503.html', '504.html',
    'terms.html', 'privacy.html', 'chat_login_guide.html',
}


def detect_theme_classes(filepath: Path, content: str) -> list:
    """根据文件名和内容判断应该附加哪些主题 class (排除已注入的 CSS 块避免误匹配)"""
    filename = filepath.name.lower()
    classes = set()

    # 从内容中剥离掉我们注入的 CSS 块, 避免 CSS 里的 'gobelin' 'andromeda' 干扰检测
    clean_content = content.replace(CSS_LINKS_BLOCK, '')
    # 也剥离掉 gobelin.css / andromeda.css 的 link 标签 (带 url_for 格式)
    clean_content = re.sub(r'<link\s+rel="stylesheet"\s+href="[^"]*(?:gobelin|andromeda)\.css"[^>]*>', '', clean_content, flags=re.IGNORECASE)

    for class_name, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw in filename or kw.lower() in clean_content.lower():
                classes.add(class_name)
                break

    return sorted(classes)


def has_css_block(content: str) -> bool:
    """检查是否已存在我们注入的 CSS 块 (精确匹配 tokens.css 链接 + MTSCOS 注释)"""
    return ('MTSCOS Unified Design System' in content or
            ("filename='css/tokens.css'" in content or
             'filename="css/tokens.css"' in content))


def inject_css_links(content: str) -> str:
    """在 </head> 前注入 CSS links (幂等)"""
    # 幂等检查 — 精确匹配我们注入的块
    if ('MTSCOS Unified Design System' in content or
        "filename='css/tokens.css'" in content or
        'filename="css/tokens.css"' in content):
        return content

    # 尝试找 </head> 标签
    head_close_match = re.search(r'</head>', content, re.IGNORECASE)
    if head_close_match:
        insert_pos = head_close_match.start()
        # 找到 head_close 前最后一个 <link...> 的位置，插在其后
        before_head = content[:insert_pos]
        # 找最后一个 </style> 或 <link>
        last_link = list(re.finditer(r'<link[^>]*>', before_head, re.IGNORECASE))
        last_style_close = list(re.finditer(r'</style>', before_head, re.IGNORECASE))

        if last_link:
            insert_pos = last_link[-1].end()
        elif last_style_close:
            insert_pos = last_style_close[-1].end()
        else:
            insert_pos = head_close_match.start()

        # 在最后一个 link/style 后换行插入
        before = content[:insert_pos]
        after = content[insert_pos:]
        return before + '\n' + CSS_LINKS_BLOCK + '\n' + after

    return content


def inject_body_class(content: str, theme_classes: list) -> str:
    """在 <body> 上注入主题 class (幂等)"""
    if not theme_classes:
        return content

    body_match = re.search(r'<body([^>]*)>', content, re.IGNORECASE)
    if not body_match:
        return content

    existing_attrs = body_match.group(1)
    body_tag_start = body_match.start()
    body_tag_end = body_match.end()

    # 检查现有 class
    class_match = re.search(r'class\s*=\s*["\']([^"\']*)["\']', existing_attrs, re.IGNORECASE)
    if class_match:
        existing_classes = class_match.group(1).split()
        new_classes = existing_classes[:]
        changed = False
        for tc in theme_classes:
            if tc not in new_classes:
                new_classes.append(tc)
                changed = True

        if not changed:
            return content  # 已全部存在

        new_class_str = ' '.join(new_classes)
        new_attrs = existing_attrs[:class_match.start()] + f'class="{new_class_str}"' + existing_attrs[class_match.end():]
    else:
        # 没有 class 属性 → 加一个
        new_attrs = existing_attrs + f' class="{" ".join(theme_classes)}"'

    new_body_tag = '<body' + new_attrs + '>'
    return content[:body_tag_start] + new_body_tag + content[body_tag_end:]


def process_file(filepath: Path, dry_run: bool) -> dict:
    """处理单个文件, 返回变更摘要"""
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        return {'file': filepath.name, 'error': str(e)}

    original = content
    changes = []

    # 1. 检测主题
    theme_classes = detect_theme_classes(filepath, content)
    if theme_classes:
        changes.append(f'主题: +{"+".join(theme_classes)}')

    # 2. 注入 CSS (仅当有主题匹配时)
    if theme_classes and not has_css_block(content):
        new_content = inject_css_links(content)
        if new_content != content:
            content = new_content
            changes.append('注入 CSS links')

    # 3. 注入 body class
    if theme_classes:
        new_content = inject_body_class(content, theme_classes)
        if new_content != content:
            content = new_content
            changes.append(f'body class: +{"+".join(theme_classes)}')

    # 写入
    if content != original:
        if not dry_run:
            filepath.write_text(content, encoding='utf-8')
        return {
            'file': filepath.name,
            'changes': changes,
            'written': not dry_run,
        }
    return None


def main():
    parser = argparse.ArgumentParser(description='批量注入 MTSCOS 统一设计系统')
    parser.add_argument('--dry-run', action='store_true', help='预览模式, 不写入文件')
    args = parser.parse_args()

    html_files = sorted(TEMPLATES_DIR.rglob('*.html'))
    total = len(html_files)
    patched = 0
    skipped = 0
    errors = 0

    # 找出所有 andromeda/gobelin 相关文件 (文件名 + 正文双重匹配)
    related = []
    for f in html_files:
        if f.name in SKIP_FILES or f.parent.name in ('admin_app', '_partials', 'macros'):
            continue
        try:
            content = f.read_text(encoding='utf-8')
        except Exception:
            continue
        # 使用 detect_theme_classes 来判断 (它会自动清理掉 CSS 注入块避免误匹配)
        theme_classes = detect_theme_classes(f, content)
        if theme_classes:
            related.append(f)

    print(f"📂 扫描范围: {total} 个 HTML 文件 (其中 {len(related)} 个匹配 andromeda/gobelin 关键词)")
    print(f"🔧 模式: {'DRY-RUN 预览' if args.dry_run else '实际写入'}")
    print("=" * 70)

    for filepath in related:
        result = process_file(filepath, args.dry_run)
        if result is None:
            skipped += 1
            continue
        if 'error' in result:
            print(f"  ❌ {result['file']}: {result['error']}")
            errors += 1
        else:
            status = '📝' if not args.dry_run else '🔍'
            print(f"  {status} {result['file']}")
            for ch in result['changes']:
                print(f"      ↳ {ch}")
            patched += 1

    print("=" * 70)
    print(f"✅ 完成: {patched} 个文件 {'将被修改' if args.dry_run else '已修改'}, {skipped} 个跳过, {errors} 个错误")


if __name__ == '__main__':
    main()
