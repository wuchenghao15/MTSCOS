#!/usr/bin/env python3
"""
beautify_andromeda_pages.py — 5 个关键仙女座页面的主题覆盖注入
为每个页面追加 body.andromeda-theme 感知的覆盖 CSS (不替换原有样式)
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TEMPLATES = BASE_DIR / 'templates'

# 每个页面的主题覆盖 CSS (body.andromeda-theme 作用域)
PAGE_OVERRIDES = {

    'andromeda_hub.html': r"""
/* ═══════════════════════════════════════════════════════════════════
   ANDROMEDA HUB · 星云脉冲 Hero 覆盖 (叠加层, 不替换)
   ═══════════════════════════════════════════════════════════════════ */
body.andromeda-theme {
  background: var(--bg-app) !important;
  color: var(--text-primary) !important;
  background-image: var(--gradient-nebula) !important;
  min-height: 100dvh;
}
body.andromeda-theme::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: var(--constellation-grid);
  background-size: 80px 80px;
  opacity: 0.4;
  z-index: 0;
}
body.andromeda-theme > * { position: relative; z-index: 1; }
body.andromeda-theme h1 {
  font-family: var(--font-display);
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  font-size: 28px; margin-bottom: 8px;
  display: inline-flex; align-items: center; gap: 12px;
}
body.andromeda-theme .panel {
  background: var(--bg-card);
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  transition: border-color 0.3s, box-shadow 0.3s;
}
body.andromeda-theme .panel:hover {
  border-color: var(--border-hover);
  box-shadow: 0 0 20px var(--accent-glow);
}
body.andromeda-theme .panel h2 { color: var(--accent) !important; }
body.andromeda-theme .stat {
  border-bottom-color: rgba(0, 240, 255, 0.15);
  font-family: var(--font-body);
}
body.andromeda-theme .good { color: var(--accent-signal) !important; }
body.andromeda-theme .bad  { color: var(--danger) !important; }
body.andromeda-theme .warn { color: var(--warning) !important; }
body.andromeda-theme th { color: var(--text-secondary) !important; }
body.andromeda-theme .pill {
  background: rgba(0, 240, 255, 0.08);
  border-color: var(--border);
  color: var(--text-secondary);
}
body.andromeda-theme .pill.FAILED {
  border-color: var(--danger);
  color: var(--danger);
  box-shadow: 0 0 8px var(--danger-glow);
}
body.andromeda-theme .meta,
body.andromeda-theme .foot { color: var(--text-secondary); }

/* Hero pulse-ring 装饰 */
body.andromeda-theme h1::before {
  content: '✦';
  display: inline-block;
  color: var(--accent-nebula);
  font-size: 22px;
  animation: constellation-twinkle 3s ease-in-out infinite;
}
@keyframes constellation-twinkle {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.5; transform: scale(0.85); }
}
""",

    'andromeda_dashboard.html': r"""
/* ═══════════════════════════════════════════════════════════════════
   ANDROMEDA DASHBOARD · 星云网格 + 玻璃卡 + 神经闪烁进度
   ═══════════════════════════════════════════════════════════════════ */
body.andromeda-theme {
  background: var(--bg-app) !important;
  background-image: var(--gradient-nebula),
                    var(--constellation-grid) !important;
  background-size: auto, 60px 60px;
  color: var(--text-primary) !important;
}
body.andromeda-theme .header {
  background: rgba(11, 18, 38, 0.75) !important;
  backdrop-filter: blur(20px) saturate(1.5);
  -webkit-backdrop-filter: blur(20px) saturate(1.5);
  border: 1px solid var(--border) !important;
}
body.andromeda-theme .header h1 {
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula)) !important;
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  font-family: var(--font-display);
}
body.andromeda-theme .stat-card {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  transition: border-color 0.3s, box-shadow 0.3s, transform 0.3s !important;
}
body.andromeda-theme .stat-card:hover {
  border-color: var(--border-hover) !important;
  box-shadow: 0 0 20px var(--accent-glow) !important;
  transform: translateY(-2px);
}
body.andromeda-theme .stat-card::before {
  background: linear-gradient(90deg, var(--accent), var(--accent-nebula)) !important;
}
body.andromeda-theme .stat-value { font-family: var(--font-display) !important; color: var(--text-primary) !important; }
body.andromeda-theme .stat-label { color: var(--text-muted) !important; }
body.andromeda-theme .stat-sub   { color: var(--text-secondary) !important; }
body.andromeda-theme .chart-card {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
}
body.andromeda-theme .chart-card h3 { color: var(--accent) !important; }
body.andromeda-theme .card, body.andromeda-theme .panel {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  color: var(--text-primary) !important;
}
body.andromeda-theme .card:hover, body.andromeda-theme .panel:hover {
  border-color: var(--border-hover) !important;
  box-shadow: 0 0 16px var(--accent-glow) !important;
}
body.andromeda-theme .title, body.andromeda-theme h1,
body.andromeda-theme h2, body.andromeda-theme h3 {
  color: var(--text-primary) !important;
}
body.andromeda-theme button, body.andromeda-theme .btn {
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula)) !important;
  color: var(--bg-app) !important;
  border: none !important;
  border-radius: var(--radius-md) !important;
  padding: 10px 24px !important;
  font-family: var(--font-heading) !important;
  font-weight: 700 !important;
  transition: all var(--duration-base) var(--ease-out) !important;
}
body.andromeda-theme button:hover, body.andromeda-theme .btn:hover {
  box-shadow: 0 0 20px var(--accent-glow), 0 0 40px var(--accent-nebula-glow) !important;
  transform: translateY(-2px);
}
body.andromeda-theme table {
  color: var(--text-primary) !important;
}
body.andromeda-theme th {
  background: rgba(0, 240, 255, 0.08) !important;
  color: var(--accent) !important;
  border-bottom-color: var(--border-hover) !important;
}
body.andromeda-theme td {
  color: var(--text-secondary) !important;
  border-bottom-color: rgba(0, 240, 255, 0.1) !important;
}
body.andromeda-theme a { color: var(--accent) !important; }
body.andromeda-theme a:hover { color: var(--accent-hover) !important; }

/* 神经闪烁 progress bar (覆盖 .bar-fill) */
body.andromeda-theme .bar-fill {
  background: linear-gradient(90deg, var(--accent-signal), var(--accent), var(--accent-nebula)) !important;
  background-size: 300% 100%;
  animation: neural-sparkle-flow 2s linear infinite;
}
@keyframes neural-sparkle-flow {
  0%   { background-position: 0% 50%; }
  100% { background-position: 300% 50%; }
}
""",

    'andromeda_stats.html': r"""
/* ═══════════════════════════════════════════════════════════════════
   ANDROMEDA STATS · 星座图表 (constellation-chart) + 星云覆盖
   ═══════════════════════════════════════════════════════════════════ */
body.andromeda-theme {
  background: var(--bg-app) !important;
  background-image: var(--gradient-nebula),
                    var(--constellation-grid) !important;
  background-size: auto, 60px 60px;
  color: var(--text-primary) !important;
}
body.andromeda-theme > * { position: relative; z-index: 1; }
body.andromeda-theme .card {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  color: var(--text-primary) !important;
}
body.andromeda-theme .card h1,
body.andromeda-theme .card h2 {
  color: var(--accent) !important;
  font-family: var(--font-heading);
}
body.andromeda-theme h1 {
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  font-family: var(--font-display);
}
body.andromeda-theme .kpi {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
}
body.andromeda-theme .kpi .n {
  color: var(--accent) !important;
  font-family: var(--font-display);
  text-shadow: 0 0 10px var(--accent-glow);
}
body.andromeda-theme .kpi .l { color: var(--text-muted) !important; }
body.andromeda-theme .bar-track {
  background: rgba(0, 240, 255, 0.08) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
}
body.andromeda-theme .bar-fill {
  background: linear-gradient(90deg, var(--accent), var(--accent-nebula)) !important;
  border-radius: 4px !important;
  box-shadow: 0 0 10px var(--accent-glow);
}
body.andromeda-theme .bar-fill.c2 {
  background: linear-gradient(90deg, var(--accent-signal), var(--success)) !important;
  box-shadow: 0 0 10px var(--accent-signal-glow);
}
body.andromeda-theme .bar-label { color: var(--text-secondary) !important; }
body.andromeda-theme .chip {
  background: var(--bg-surface) !important;
  border-color: var(--border) !important;
  color: var(--text-secondary) !important;
  border-radius: var(--radius-full) !important;
  font-family: var(--font-heading);
  transition: all 0.2s;
}
body.andromeda-theme .chip:hover { border-color: var(--border-hover); color: var(--text-primary); }
body.andromeda-theme .chip.active {
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula)) !important;
  border-color: var(--accent) !important;
  color: var(--bg-app) !important;
  box-shadow: 0 0 10px var(--accent-glow);
}
body.andromeda-theme input.q {
  background: var(--bg-surface) !important;
  border-color: var(--border) !important;
  color: var(--text-primary) !important;
  border-radius: var(--radius-sm) !important;
}
body.andromeda-theme input.q:focus { border-color: var(--accent); outline: none; box-shadow: 0 0 8px var(--accent-glow); }
body.andromeda-theme table { color: var(--text-primary) !important; }
body.andromeda-theme th {
  background: rgba(0, 240, 255, 0.08) !important;
  color: var(--accent) !important;
  border-bottom-color: var(--border-hover) !important;
}
body.andromeda-theme td {
  color: var(--text-secondary) !important;
  border-bottom-color: rgba(0, 240, 255, 0.1) !important;
}
body.andromeda-theme tbody tr:hover { background: rgba(0, 240, 255, 0.05) !important; }
body.andromeda-theme button {
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula)) !important;
  border: none !important;
  border-radius: var(--radius-sm) !important;
  color: var(--bg-app) !important;
  font-weight: 700;
}
body.andromeda-theme button.ghost {
  background: transparent !important;
  border: 1px solid var(--accent) !important;
  color: var(--accent) !important;
}
body.andromeda-theme .badge { border-radius: var(--radius-sm) !important; font-family: var(--font-mono) !important; }
body.andromeda-theme .status-ok { color: var(--accent-signal) !important; }
body.andromeda-theme .status-bad { color: var(--danger) !important; }

/* 星座图表 */
.constellation-chart {
  position: relative;
}
body.andromeda-theme .constellation-chart svg,
body.andromeda-theme #cat-chart,
body.andromeda-theme #month-chart {
  filter: drop-shadow(0 0 8px var(--accent-glow));
}
""",

    'andromeda_health_board.html': r"""
/* ═══════════════════════════════════════════════════════════════════
   ANDROMEDA HEALTH BOARD · 实时脉冲健康指示器
   ═══════════════════════════════════════════════════════════════════ */
body.andromeda-theme {
  background: var(--bg-app) !important;
  background-image: var(--gradient-nebula),
                    var(--constellation-grid) !important;
  background-size: auto, 60px 60px;
  color: var(--text-primary) !important;
  overflow-x: hidden;
}
body.andromeda-theme .container { max-width: 1200px; margin: 0 auto; padding: 32px; }
body.andromeda-theme .hd-tag {
  color: var(--accent) !important;
  font-family: var(--font-mono);
  letter-spacing: 6px;
}
body.andromeda-theme .hd-title {
  background: linear-gradient(135deg, var(--accent-signal), var(--accent), var(--accent-nebula)) !important;
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  font-family: var(--font-display);
  letter-spacing: 4px;
}
body.andromeda-theme .clock { color: var(--text-muted) !important; font-family: var(--font-mono); }

body.andromeda-theme .kpi {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
}
body.andromeda-theme .kpi .v {
  font-family: var(--font-display);
  color: var(--text-primary);
}
body.andromeda-theme .kpi.ok   { border-color: rgba(57, 255, 20, 0.4) !important; box-shadow: inset 0 0 20px rgba(57, 255, 20, 0.05); }
body.andromeda-theme .kpi.warn { border-color: rgba(255, 179, 71, 0.4) !important; box-shadow: inset 0 0 20px rgba(255, 179, 71, 0.05); }
body.andromeda-theme .kpi.bad  { border-color: rgba(255, 56, 96, 0.4) !important; box-shadow: inset 0 0 20px rgba(255, 56, 96, 0.05); }

body.andromeda-theme .section-title { color: var(--accent) !important; font-family: var(--font-heading); letter-spacing: 2px; }

body.andromeda-theme .daemon-row {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  transition: all 0.3s;
}
body.andromeda-theme .daemon-row.alive { border-color: rgba(57, 255, 20, 0.35) !important; background: rgba(57, 255, 20, 0.05) !important; }
body.andromeda-theme .daemon-row.dead  { border-color: rgba(255, 56, 96, 0.35) !important; background: rgba(255, 56, 96, 0.05) !important; }
body.andromeda-theme .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
body.andromeda-theme .dot.alive {
  background: var(--accent-signal);
  box-shadow: 0 0 8px var(--accent-signal-glow), 0 0 16px var(--accent-signal-glow);
  animation: health-pulse-ring 2s ease-out infinite;
}
body.andromeda-theme .dot.dead {
  background: var(--danger);
  box-shadow: 0 0 8px var(--danger-glow);
  animation: health-pulse-flicker 1.5s ease-in-out infinite;
}
@keyframes health-pulse-ring {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.3); }
}
@keyframes health-pulse-flicker {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.4; }
}
body.andromeda-theme .d-name { color: var(--text-primary) !important; font-family: var(--font-heading); }
body.andromeda-theme .d-age,
body.andromeda-theme .d-interval { color: var(--text-muted) !important; font-family: var(--font-mono); }

body.andromeda-theme .anchor {
  background: var(--bg-surface) !important;
  border: 1px solid rgba(123, 45, 255, 0.4) !important;
  border-radius: var(--radius-md) !important;
  transition: all 0.3s;
}
body.andromeda-theme .anchor:hover {
  border-color: var(--accent-nebula);
  box-shadow: 0 0 16px var(--accent-nebula-glow);
  transform: translateY(-2px);
}
body.andromeda-theme .card, body.andromeda-theme .panel {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  color: var(--text-primary) !important;
}

/* 实时信号条 */
body.andromeda-theme .signal-bar {
  height: 6px; border-radius: 3px;
  background: rgba(0, 240, 255, 0.08);
  overflow: hidden;
}
body.andromeda-theme .signal-bar-fill {
  height: 100%; border-radius: inherit;
  background: linear-gradient(90deg, var(--accent-signal), var(--accent), var(--accent-nebula));
  background-size: 200% 100%;
  animation: signal-bar-flow 3s linear infinite;
}
@keyframes signal-bar-flow {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
""",

    'index.html': r"""
/* ═══════════════════════════════════════════════════════════════════
   INDEX (主 landing) · 动画星云 Hero + CTA
   ═══════════════════════════════════════════════════════════════════ */
body.andromeda-theme {
  background: var(--bg-app) !important;
  background-image: var(--gradient-nebula),
                    var(--constellation-grid) !important;
  background-size: auto, 80px 80px;
  color: var(--text-primary) !important;
  min-height: 100dvh;
}
body.andromeda-theme > * { position: relative; z-index: 1; }

body.andromeda-theme a { color: var(--accent); transition: color 0.2s; }
body.andromeda-theme a:hover { color: var(--accent-hover); }
body.andromeda-theme button {
  background: linear-gradient(135deg, var(--accent), var(--accent-nebula)) !important;
  color: var(--bg-app) !important;
  border: none !important;
  border-radius: var(--radius-md) !important;
  padding: 12px 32px !important;
  font-family: var(--font-heading) !important;
  font-weight: 700 !important;
  cursor: pointer;
  transition: all var(--duration-base) var(--ease-out);
}
body.andromeda-theme button:hover {
  box-shadow: 0 0 24px var(--accent-glow), 0 0 48px var(--accent-nebula-glow);
  transform: translateY(-2px);
}
body.andromeda-theme h1, body.andromeda-theme h2, body.andromeda-theme h3 {
  color: var(--text-primary);
}
body.andromeda-theme h1 {
  font-family: var(--font-display);
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-nebula) 50%, var(--accent-signal) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  letter-spacing: 0.05em;
}
body.andromeda-theme .card,
body.andromeda-theme [class*="card"],
body.andromeda-theme [class*="panel"] {
  background: var(--bg-card) !important;
  backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-md)) saturate(1.4);
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  color: var(--text-primary);
  transition: border-color 0.3s, box-shadow 0.3s, transform 0.3s;
}
body.andromeda-theme .card:hover,
body.andromeda-theme [class*="card"]:hover,
body.andromeda-theme [class*="panel"]:hover {
  border-color: var(--border-hover) !important;
  box-shadow: 0 0 20px var(--accent-glow) !important;
  transform: translateY(-2px);
}
body.andromeda-theme table { color: var(--text-primary); }
body.andromeda-theme th { color: var(--accent); background: rgba(0, 240, 255, 0.08); }
body.andromeda-theme td { color: var(--text-secondary); }
body.andromeda-theme input,
body.andromeda-theme textarea,
body.andromeda-theme select {
  background: var(--bg-surface);
  border-color: var(--border);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
}
body.andromeda-theme input:focus,
body.andromeda-theme textarea:focus,
body.andromeda-theme select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 8px var(--accent-glow);
  outline: none;
}

/* Hero 装饰 */
body.andromeda-theme .hero::before,
body.andromeda-theme [class*="hero"]::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--gradient-nebula);
  opacity: 0.5;
  pointer-events: none;
}
body.andromeda-theme .pulse,
body.andromeda-theme [class*="pulse"] {
  animation: constellation-twinkle 3s ease-in-out infinite;
}
@keyframes constellation-twinkle {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.5; transform: scale(0.85); }
}
""",
}


def inject_overrides(filepath: Path, css_override: str) -> bool:
    """在最后一个 </style> 前注入主题覆盖 (幂等)"""
    content = filepath.read_text(encoding='utf-8')
    marker = 'ANDROMEDA THEME OVERRIDES'
    if marker in content:
        return False  # 已注入过 (幂等)

    # 找最后一个 </style> 标签后插入新的 style 块
    style_closes = list(re.finditer(r'</style>', content, re.IGNORECASE))
    if style_closes:
        # 在最后一个 </style> 之后插入 (避免嵌套在 Jinja block 里)
        last_close = style_closes[-1]
        insert_pos = last_close.end()

        # 构建新 style 块 —— 放在 </style> 之后, 不会有 Jinja block 问题
        new_block = f"\n\n<!-- ANDROMEDA THEME OVERRIDES — 星云脉冲主题 (叠加层, 不替换原有样式) -->\n<style>\n{css_override}\n</style>\n"

        new_content = content[:insert_pos] + new_block + content[insert_pos:]
        filepath.write_text(new_content, encoding='utf-8')
        return True

    return False


def main():
    for fname, css in PAGE_OVERRIDES.items():
        fp = TEMPLATES / fname
        if not fp.exists():
            print(f"⚠️  {fname} 不存在, 跳过")
            continue
        changed = inject_overrides(fp, css)
        status = "📝 已注入" if changed else "⏭️  已存在, 跳过"
        print(f"  {status} — {fname}")


if __name__ == '__main__':
    main()
