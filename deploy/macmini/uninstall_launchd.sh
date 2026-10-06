#!/bin/bash
# ──────────────────────────────────────────────────────────────────
#  MTSCOS AI — Mac mini Flask launchd 一键卸载脚本
#  版本: v2.0 (2026-10-06)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH_AGENTS/com.mtscos.flask.plist"

echo "╔═══════════════════════════════════════════════════════╗"
echo "║  MTSCOS AI · Mac mini Flask launchd 卸载               ║"
echo "╚═══════════════════════════════════════════════════════╝"

# 1. 卸载 launchd
if launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null; then
  echo "  [✓] launchctl bootout 成功"
elif launchctl unload -w "$PLIST" 2>/dev/null; then
  echo "  [✓] launchctl unload 成功"
else
  echo "  [!] launchctl 卸载失败 (服务可能已卸载)"
fi

# 2. kill 残留进程
pkill -9 -f "modular_start.py" 2>/dev/null && echo "  [✓] 残留 Flask 已 kill" || echo "  [!] 无残留 Flask"

# 3. 端口清理
sleep 1
for p in $(lsof -i :8888 -t 2>/dev/null); do
  kill -9 "$p" 2>/dev/null && echo "  [✓] 端口 8888 占用进程已 kill: $p"
done || true

# 4. 备份 plist
if [ -f "$PLIST" ]; then
  cp "$PLIST" "$PLIST.bak.$(date +%Y%m%d%H%M%S)"
  rm -f "$PLIST"
  echo "  [✓] plist 已备份并删除"
else
  echo "  [!] plist 不存在: $PLIST"
fi

echo ""
echo "✅ 卸载完成. 重新安装: deploy/macmini/install_launchd.sh"
