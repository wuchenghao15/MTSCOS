#!/bin/bash
# ──────────────────────────────────────────────────────────────────
#  MTSCOS AI — Mac mini 一键安装/更新所有 launchd plist
#  版本: v1.0 (2026-10-06)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

AG="$HOME/Library/LaunchAgents"
SRC="$(cd "$(dirname "$0")" && pwd)"

PLISTS=(
    "com.mtscos.flask.plist"
    "com.mtscos.smart_mount.plist"
)

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${RED}[!]${NC} $*"; }

echo "╔═══════════════════════════════════════════════════╗"
echo "║  MTSCOS AI · Mac mini launchd 一键安装              ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  源:   $SRC"
echo "  目标: $AG"
echo ""

mkdir -p "$AG"
cd "$AG"

# 1) 旧的先 bootout
log "bootout 所有 MTSCOS plist..."
for pl in com.mtscos.*.plist; do
    [ -f "$AG/$pl" ] || continue
    launchctl bootout "gui/$(id -u)" "$AG/$pl" 2>/dev/null && echo "  - $pl" || true
done
sleep 1

# 2) 复制新的
for pl in "${PLISTS[@]}"; do
    if [ -f "$SRC/$pl" ]; then
        cp "$SRC/$pl" "$AG/$pl"
        plutil -lint "$AG/$pl" >/dev/null 2>&1 && log "✅ $pl" || warn "❌ $pl (plist 无效)"
    else
        warn "❌ $pl 源文件不存在 ($SRC/$pl)"
    fi
done

# 3) 重启 cloudflared (可能外部管理, 只 bootout 不删)
launchctl bootout "gui/$(id -u)" "$AG/com.mtscos.cloudflared.plist" 2>/dev/null || true
sleep 0.5
[ -f "$AG/com.mtscos.cloudflared.plist" ] && launchctl bootstrap "gui/$(id -u)" "$AG/com.mtscos.cloudflared.plist" 2>&1 || true

# 4) andromeda & tunnel 是远端 Application Support 下的, 单独处理
for pl in com.mtscos.andromeda.plist com.mtscos.andromeda-tunnel.plist; do
    [ -f "$AG/$pl" ] || continue
    launchctl bootout "gui/$(id -u)" "$AG/$pl" 2>/dev/null || true
    sleep 0.5
    launchctl bootstrap "gui/$(id -u)" "$AG/$pl" 2>&1
done

# 5) 新的 flask + smart_mount
sleep 1
log "bootstrap 新 plist..."
for pl in "${PLISTS[@]}"; do
    [ -f "$AG/$pl" ] || continue
    launchctl bootstrap "gui/$(id -u)" "$AG/$pl" 2>&1
done

echo ""
sleep 5
echo "═══ 最终状态 ═══"
launchctl list | grep mtscos | sort
echo ""
echo "✅ 完成. 如果有 exit 非 0, 看对应 .err 日志"
echo "   查看: tail -30 /tmp/mtscos_*.err"
