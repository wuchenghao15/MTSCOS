#!/usr/bin/env python3
"""
beautify_gobelin.py — Gobelin trading_console.html 三项增强
  1. Price ticker — 涨跌行绿/红动画背景
  2. Portfolio cards — 玻璃+霓虹边框 + 实时脉冲点
  3. Expert verdict badges — 10 专家 BUY/SELL/HOLD 颜色发光
"""

import re
from pathlib import Path

FP = Path(__file__).parent.parent / 'templates' / 'trading_console.html'

GOBELIN_ENHANCE_CSS = r"""
/* ═══════════════════════════════════════════════════════════════════
   GOBELIN TRADING CONSOLE · 三项增强 (叠加层, 不替换)
   ═══════════════════════════════════════════════════════════════════ */

body.gobelin-theme {
  background: var(--bg-app) !important;
  background-image:
    radial-gradient(ellipse at 20% 0%, rgba(0, 212, 170, 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 100%, rgba(14, 124, 123, 0.06) 0%, transparent 50%) !important;
}

/* ─── 1. Price ticker 涨跌行 ─── */
body.gobelin-theme .chg-up { color: var(--accent-sell, #E63946) !important; }
body.gobelin-theme .chg-down { color: var(--accent, #0E7C7B) !important; }
body.gobelin-theme tr.ticker-up td,
body.gobelin-theme tr:has(.chg-up) td {
  background: rgba(230, 57, 70, 0.06) !important;
  animation: ticker-flash-up 0.6s ease-out;
}
body.gobelin-theme tr.ticker-down td,
body.gobelin-theme tr:has(.chg-down) td {
  background: rgba(14, 124, 123, 0.06) !important;
  animation: ticker-flash-down 0.6s ease-out;
}
@keyframes ticker-flash-up {
  0%   { background: rgba(230, 57, 70, 0.2) !important; }
  100% { background: rgba(230, 57, 70, 0.06) !important; }
}
@keyframes ticker-flash-down {
  0%   { background: rgba(14, 124, 123, 0.2) !important; }
  100% { background: rgba(14, 124, 123, 0.06) !important; }
}

/* 指数 tile 增强 */
body.gobelin-theme .index-tile {
  background: rgba(16, 42, 67, 0.75) !important;
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
  border: 2px solid rgba(14, 124, 123, 0.35) !important;
  border-radius: 8px !important;
  box-shadow: 3px 3px 0 rgba(0, 0, 0, 0.4),
              inset 0 1px 0 rgba(0, 212, 170, 0.08);
  transition: all 0.2s;
}
body.gobelin-theme .index-tile:hover {
  transform: translate(-1px, -1px);
  box-shadow: 5px 5px 0 rgba(0, 0, 0, 0.45),
              inset 0 1px 0 rgba(0, 212, 170, 0.15);
  border-color: var(--accent-hover) !important;
}
body.gobelin-theme .index-name { color: var(--text-secondary) !important; }
body.gobelin-theme .index-val { color: var(--text-primary) !important; font-family: var(--font-mono) !important; }
body.gobelin-theme .index-chg { font-family: var(--font-mono) !important; font-weight: 700 !important; }

/* ─── 2. Portfolio / Stat cards 玻璃+霓虹边框+脉冲点 ─── */
body.gobelin-theme .stat-card,
body.gobelin-theme .card {
  background: rgba(16, 42, 67, 0.82) !important;
  backdrop-filter: blur(14px) saturate(1.4);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  border: 2px solid rgba(14, 124, 123, 0.4) !important;
  border-radius: 8px !important;
  box-shadow: 3px 3px 0 rgba(0, 0, 0, 0.5),
              inset 0 1px 0 rgba(0, 212, 170, 0.1);
  transition: all 0.2s;
  position: relative;
}
body.gobelin-theme .stat-card::before,
body.gobelin-theme .card::before {
  content: '';
  position: absolute;
  top: -1px;
  right: -1px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent-signal, #39FF14);
  box-shadow: 0 0 8px var(--accent-signal-glow);
  animation: live-pulse-dot 2s ease-in-out infinite;
}
body.gobelin-theme .stat-card:hover,
body.gobelin-theme .card:hover {
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 rgba(0, 0, 0, 0.5),
              inset 0 1px 0 rgba(0, 212, 170, 0.18);
  border-color: var(--accent-hover) !important;
}
body.gobelin-theme .stat-label { color: var(--text-muted) !important; }
body.gobelin-theme .stat-value { color: var(--text-primary) !important; font-family: var(--font-mono) !important; }
body.gobelin-theme .stat-value.gold { color: var(--accent-gold, #D9A441) !important; text-shadow: 0 0 8px rgba(217, 164, 65, 0.3); }
body.gobelin-theme .stat-value.red { color: var(--accent-sell) !important; text-shadow: 0 0 8px var(--accent-sell-glow); }
body.gobelin-theme .stat-value.green { color: var(--accent) !important; text-shadow: 0 0 8px var(--accent-glow); }

@keyframes live-pulse-dot {
  0%, 100% { opacity: 1;   transform: scale(1); }
  50%      { opacity: 0.4; transform: scale(0.7); }
}

/* 侧边栏脉冲 */
body.gobelin-theme .side-item.active {
  border-left-color: var(--accent-gold, #D9A441) !important;
  background: rgba(217, 164, 65, 0.1) !important;
  box-shadow: inset 0 0 16px rgba(217, 164, 65, 0.08);
}

/* 顶部栏玻璃 */
body.gobelin-theme .topbar {
  background: rgba(16, 42, 67, 0.92) !important;
  backdrop-filter: blur(16px) saturate(1.5);
  -webkit-backdrop-filter: blur(16px) saturate(1.5);
  border-bottom-color: rgba(14, 124, 123, 0.4) !important;
}
body.gobelin-theme .topbar-title {
  color: var(--accent-gold, #D9A441) !important;
  text-shadow: 0 0 8px rgba(217, 164, 65, 0.3);
  font-family: var(--font-mono) !important;
}

/* AI 面板 */
body.gobelin-theme .ai-panel {
  background: rgba(16, 42, 67, 0.92) !important;
  border-left: 1px solid rgba(14, 124, 123, 0.3);
}
body.gobelin-theme .ai-panel-title { color: var(--accent-gold, #D9A441) !important; }

/* ─── 3. Expert Verdict Badges — 10 专家 BUY/SELL/HOLD 颜色发光 ─── */
.verdict-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 10px;
  font-family: var(--font-mono, 'SF Mono', monospace);
  font-weight: 700;
  letter-spacing: 1px;
  border-radius: 3px;
  border: 1px solid;
}
.verdict-buy {
  background: rgba(14, 124, 123, 0.15) !important;
  border-color: var(--accent, #0E7C7B) !important;
  color: var(--accent-hover, #00D4AA) !important;
  box-shadow: 0 0 6px var(--accent-glow);
  animation: verdict-glow-buy 2s ease-in-out infinite;
}
.verdict-sell {
  background: rgba(230, 57, 70, 0.15) !important;
  border-color: var(--accent-sell, #E63946) !important;
  color: #FF6B76 !important;
  box-shadow: 0 0 6px var(--accent-sell-glow);
  animation: verdict-glow-sell 1.5s ease-in-out infinite;
}
.verdict-hold {
  background: rgba(217, 164, 65, 0.15) !important;
  border-color: var(--accent-gold, #D9A441) !important;
  color: #E8B85A !important;
  box-shadow: 0 0 6px rgba(217, 164, 65, 0.3);
}
@keyframes verdict-glow-buy {
  0%, 100% { box-shadow: 0 0 6px var(--accent-glow); }
  50%      { box-shadow: 0 0 12px var(--accent-glow), 0 0 20px var(--accent-glow); }
}
@keyframes verdict-glow-sell {
  0%, 100% { box-shadow: 0 0 6px var(--accent-sell-glow); }
  50%      { box-shadow: 0 0 12px var(--accent-sell-glow), 0 0 20px var(--accent-sell-glow); }
}

/* agent-badge 增强 (十专家徽章) */
body.gobelin-theme .agent-badge {
  font-family: var(--font-mono, 'SF Mono', monospace);
  font-weight: 600;
  letter-spacing: 0.5px;
  border-radius: 4px !important;
  transition: all 0.2s;
}
body.gobelin-theme .agent-badge:hover {
  transform: translateY(-1px);
  box-shadow: 0 0 12px currentColor;
}
body.gobelin-theme .agent-r {
  background: rgba(52, 152, 219, 0.12) !important;
  border-color: rgba(52, 152, 219, 0.4) !important;
  color: #5DADE2 !important;
  box-shadow: 0 0 4px rgba(52, 152, 219, 0.2);
}
body.gobelin-theme .agent-s {
  background: rgba(155, 89, 182, 0.12) !important;
  border-color: rgba(155, 89, 182, 0.4) !important;
  color: #BB8FCE !important;
  box-shadow: 0 0 4px rgba(155, 89, 182, 0.2);
}
body.gobelin-theme .agent-k {
  background: rgba(230, 57, 70, 0.12) !important;
  border-color: rgba(230, 57, 70, 0.4) !important;
  color: #EF5A66 !important;
  box-shadow: 0 0 4px rgba(230, 57, 70, 0.2);
}
body.gobelin-theme .agent-e {
  background: rgba(14, 124, 123, 0.12) !important;
  border-color: rgba(14, 124, 123, 0.4) !important;
  color: var(--accent-hover, #00D4AA) !important;
  box-shadow: 0 0 4px var(--accent-glow);
}
body.gobelin-theme .agent-t {
  background: rgba(217, 164, 65, 0.12) !important;
  border-color: rgba(217, 164, 65, 0.4) !important;
  color: #E8B85A !important;
  box-shadow: 0 0 4px rgba(217, 164, 65, 0.2);
}

/* 风控按钮 */
body.gobelin-theme .btn {
  background: rgba(16, 42, 67, 0.85) !important;
  border: 1px solid rgba(14, 124, 123, 0.4) !important;
  border-radius: 4px !important;
  color: var(--text-primary) !important;
  font-family: var(--font-mono, 'SF Mono', monospace) !important;
  font-weight: 500 !important;
  transition: all 0.15s !important;
}
body.gobelin-theme .btn:hover {
  border-color: var(--accent-hover) !important;
  color: var(--accent-hover) !important;
  box-shadow: 0 0 8px var(--accent-glow);
}
body.gobelin-theme .btn-gold {
  background: linear-gradient(135deg, #D9A441, #B8892E) !important;
  border-color: #D9A441 !important;
  color: #041419 !important;
  font-weight: 700 !important;
  box-shadow: 2px 2px 0 rgba(0, 0, 0, 0.5),
              0 0 12px rgba(217, 164, 65, 0.3);
}
body.gobelin-theme .btn-gold:hover {
  box-shadow: 2px 2px 0 rgba(0, 0, 0, 0.5),
              0 0 20px rgba(217, 164, 65, 0.5);
  transform: translate(-1px, -1px);
}
body.gobelin-theme .btn-danger {
  border-color: var(--accent-sell) !important;
  color: var(--accent-sell) !important;
}
body.gobelin-theme .btn-danger:hover {
  background: var(--accent-sell) !important;
  color: white !important;
  box-shadow: 0 0 12px var(--accent-sell-glow);
}

/* 表格增强 */
body.gobelin-theme th {
  background: rgba(14, 124, 123, 0.08) !important;
  color: var(--accent-hover) !important;
  border-bottom: 2px solid var(--border-hover) !important;
}
body.gobelin-theme td {
  border-bottom-color: rgba(14, 124, 123, 0.12) !important;
  color: var(--text-primary) !important;
}
body.gobelin-theme tr:hover td { background: rgba(0, 212, 170, 0.04) !important; }
body.gobelin-theme .code-cell {
  color: var(--accent-gold, #D9A441) !important;
  font-weight: 600 !important;
  text-shadow: 0 0 4px rgba(217, 164, 65, 0.2);
}

/* 风险分数 */
body.gobelin-theme .risk-score {
  font-family: var(--font-mono, 'SF Mono', monospace) !important;
  font-weight: 700 !important;
  border-radius: 50% !important;
}
"""


def inject():
    content = FP.read_text(encoding='utf-8')
    marker = 'GOBELIN TRADING CONSOLE · 三项增强'
    if marker in content:
        print("⏭️  Gobelin 增强已存在, 跳过")
        return

    # 找最后一个 </style>
    style_closes = list(re.finditer(r'</style>', content, re.IGNORECASE))
    if not style_closes:
        print("❌ 找不到 </style> 标签")
        return

    last_close = style_closes[-1]
    new_block = f"\n\n<!-- GOBELIN TRADING CONSOLE ENHANCEMENTS — 三项叠加层 -->\n<style>\n{GOBELIN_ENHANCE_CSS}\n</style>\n"

    new_content = content[:last_close.end()] + new_block + content[last_close.end()]
    FP.write_text(new_content, encoding='utf-8')
    print("📝 Gobelin trading_console.html 三项增强已注入")


if __name__ == '__main__':
    inject()
