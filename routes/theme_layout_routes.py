"""
系统主题与框架排列排版研究中心 — Flask 路由 (页面 + API)

flow_id: flow_theme_center_20261018
version: v1.0.0
注册: routes/__init__.py → _modules 列表 ('theme_layout_routes', 'theme_layout_bp')

页面:
  GET  /theme-layout/center          → 研究中心主页

API:
  GET  /api/theme-layout/scan   → 模板硬编码颜色全量扫描 (逐文件命中/高频色值/总数)
  GET  /api/theme-layout/tokens → 设计 token 目录 (mtscos_design_tokens.css 解析分组)
  GET  /api/theme-layout/routes → 框架路由清单 (url_map 按前缀分组 = 框架排列实况)
"""
import os
import re
from collections import Counter

from flask import Blueprint, jsonify, render_template, current_app

from app.middlewares.system_container import system_container

theme_layout_bp = Blueprint('theme_layout', __name__)

_HEX_RE = re.compile(r'#[0-9a-fA-F]{3,8}\b')
_TOKEN_RE = re.compile(r'(--[\w-]+)\s*:\s*([^;]+);')

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_TEMPLATES_DIR = os.path.join(_BASE_DIR, 'templates')
_TOKENS_CSS = os.path.join(_BASE_DIR, 'static', 'css', 'mtscos_design_tokens.css')


def _iter_template_files():
    for root in (_TEMPLATES_DIR, os.path.join(_TEMPLATES_DIR, 'admin_app')):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if name.endswith('.html'):
                yield os.path.join(root, name)


@theme_layout_bp.route('/theme-layout/center', methods=['GET'])
@system_container(require_auth='login')
def theme_layout_center():
    return render_template('theme_layout_center.html')


@theme_layout_bp.route('/api/theme-layout/scan', methods=['GET'])
@system_container(require_auth='login')
def api_scan():
    """全量扫描模板硬编码颜色 — 每次调用实时重扫, 结果与磁盘一致."""
    files = []
    value_counter = Counter()
    total_hits = 0
    for path in _iter_template_files():
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except OSError:
            continue
        rel = os.path.relpath(path, _TEMPLATES_DIR)
        hits = _HEX_RE.findall(content)
        if hits:
            files.append({'file': rel, 'count': len(hits)})
            value_counter.update(h.lower() for h in hits)
            total_hits += len(hits)
    files.sort(key=lambda x: -x['count'])
    top_values = [{'hex': h, 'count': n} for h, n in value_counter.most_common(20)]
    return jsonify({
        'total_templates': sum(1 for _ in _iter_template_files()),
        'files_with_hex': len(files),
        'total_hits': total_hits,
        'top_files': files[:20],
        'top_values': top_values,
    })


@theme_layout_bp.route('/api/theme-layout/tokens', methods=['GET'])
@system_container(require_auth='login')
def api_tokens():
    """解析设计 token CSS → 按前缀分组 (--mtscos / --el / 其他)."""
    groups = {'mtscos': [], 'element': [], 'other': []}
    try:
        with open(_TOKENS_CSS, 'r', encoding='utf-8', errors='ignore') as f:
            for var, val in _TOKEN_RE.findall(f.read()):
                item = {'name': var, 'value': val.strip()}
                if var.startswith('--mtscos'):
                    groups['mtscos'].append(item)
                elif var.startswith('--el'):
                    groups['element'].append(item)
                else:
                    groups['other'].append(item)
    except OSError:
        pass
    return jsonify({
        'total': sum(len(v) for v in groups.values()),
        'groups': {k: {'count': len(v), 'items': v[:120]} for k, v in groups.items()},
    })


@theme_layout_bp.route('/api/theme-layout/routes', methods=['GET'])
@system_container(require_auth='login')
def api_routes():
    """框架排列实况: url_map 全量路由按首段前缀分组."""
    groups = {}
    for rule in current_app.url_map.iter_rules():
        path = rule.rule
        if path.startswith('/static'):
            continue
        seg = path.strip('/').split('/')[0] or '/'
        g = groups.setdefault(seg, {'prefix': '/' + seg if seg != '/' else '/', 'count': 0, 'samples': []})
        g['count'] += 1
        if len(g['samples']) < 8:
            methods = ','.join(sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')))
            g['samples'].append({'rule': path, 'endpoint': rule.endpoint, 'methods': methods})
    listing = sorted(groups.values(), key=lambda x: -x['count'])
    return jsonify({'total_groups': len(listing), 'total_routes': sum(g['count'] for g in listing), 'groups': listing})
