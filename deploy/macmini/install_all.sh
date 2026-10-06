#!/bin/bash
# ──────────────────────────────────────────────────────────────────
#  MTSCOS AI — Mac mini 一键重启所有 launchd plist
#  版本: v1.1 (2026-10-06)
#  用法: bash install_all.sh   (bootout + bootstrap + 等稳定 + 状态展示)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

AG="$HOME/Library/LaunchAgents"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; }

echo "╔═══════════════════════════════════════════════════╗"
echo "║  MTSCOS AI · Mac mini launchd 一键重启 v1.1          ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  LaunchAgents: $AG"
echo ""

cd "$AG"

# 1) bootout 所有 mtscos plist
log "bootout 所有 MTSCOS plist..."
ls "$AG"/com.mtscos.*.plist 2>/dev/null | while read pl; do
    name="$(basename "$pl")"
    launchctl bootout "gui/$(id -u)" "$pl" 2>/dev/null && echo "  - $name" || true
done
sleep 2

# 2) 杀残留端口 (防止 Address already in use)
log "清理残留端口..."
for port in 8888 9999; do
    for p in $(lsof -i ":$port" -t 2>/dev/null); do
        kill -9 "$p" 2>/dev/null && echo "  kill PID $p (port $port)"
    done
done
pkill -9 -f "modular_start.py\|server_real_db.py" 2>/dev/null || true
sleep 2

# 3) 清日志
log "清空运行时日志..."
for f in /tmp/mtscos_flask.err /tmp/mtscos_flask.log \
         /tmp/mtscos_smart_mount.err /tmp/mtscos_smart_mount.log; do
    [ -f "$f" ] && > "$f"
done

# 4) bootstrap 回来 (按优先级)
echo ""
log "bootstrap 所有 plist..."

for pl in com.mtscos.flask.plist \
          com.mtscos.smart_mount.plist \
          com.mtscos.andromeda.plist \
          com.mtscos.andromeda-tunnel.plist \
          com.mtscos.cloudflared.plist; do
    [ -f "$AG/$pl" ] || { warn "$pl 不存在"; continue; }
    launchctl bootstrap "gui/$(id -u)" "$AG/$pl" 2>&1 || true
done

echo ""
log "等待进程稳定 (12s)..."
sleep 12

# 5) 最终状态展示
echo ""
echo "═══════════════════════════════════════════════════"
echo "  最终 launchctl 状态"
echo "═══════════════════════════════════════════════════"

ok=0; bad=0
while IFS= read -r line; do
    exit_code=$(echo "$line" | awk '{print $2}')
    label=$(echo "$line" | awk '{print $3}')
    if [[ "$exit_code" == "0" ]]; then
        echo -e "  ${GREEN}✅${NC} $label  (exit 0)"
        ok=$((ok+1))
    else
        echo -e "  ${RED}❌${NC} $label  (exit $exit_code)"
        bad=$((bad+1))
    fi
done < <(launchctl list | grep mtscos | sort)

echo ""
echo "═══════════════════════════════════════════════════"
echo "  HTTP 健康检查"
echo "═══════════════════════════════════════════════════"

http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://127.0.0.1:8888/ 2>/dev/null || echo "000")
if [ "$http_code" = "000" ]; then
    fail "Flask HTTP: 未监听"
elif [ "$http_code" != "200" ] && [ "$http_code" != "302" ]; then
    warn "Flask HTTP: $http_code (预期 302)"
else
    echo -e "  ${GREEN}✅${NC} Flask HTTP: $http_code"
fi

echo ""
echo "═══════════════════════════════════════════════════"
if [ "$bad" -gt 0 ]; then
    echo -e "  ${RED}结果: $ok 正常 / $bad 异常${NC}"
    echo -e "  ${YELLOW}查看异常日志:${NC} tail -30 /tmp/mtscos_*.err"
else
    echo -e "  ${GREEN}结果: ✅ 全部 $ok 进程 exit 0${NC}"
fi
echo "═══════════════════════════════════════════════════"
