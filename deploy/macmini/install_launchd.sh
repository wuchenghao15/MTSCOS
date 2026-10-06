#!/bin/bash
# ──────────────────────────────────────────────────────────────────
#  MTSCOS AI — Mac mini Flask launchd 一键安装脚本
#  版本: v2.0 (2026-10-06)
#  目标主机: HULK-MACMINI 192.168.31.9 (SLAVE 节点)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

# 颜色输出
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log() { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# 路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.mtscos.flask.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_DST="$LAUNCH_AGENTS/com.mtscos.flask.plist"
PROJECT_LOCAL="$HOME/MTSCOS_AI_Project"
PROJECT_REMOTE="$HOME/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"

echo "╔═══════════════════════════════════════════════════════╗"
echo "║  MTSCOS AI · Mac mini Flask launchd 一键安装 v2.0     ║"
echo "╚═══════════════════════════════════════════════════════╝"

# ── 预检 ──────────────────────────────────────────────────────────
echo ""
echo "── 预检 ──"

# 1. macOS 版本 ≥ 13 (Ventura) 才有 launchctl bootstrap
MACOS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
[ "$MACOS_MAJOR" -ge 13 ] || warn "macOS < 13 — launchctl bootstrap 可能不可用 (将尝试 load)"

# 2. plist 源存在且 plutil 校验
[ -f "$PLIST_SRC" ] || err "找不到 plist: $PLIST_SRC"
plutil -lint "$PLIST_SRC" >/dev/null 2>&1 || err "plist 格式错误 (plutil 校验失败)"
log "plist 格式校验通过"

# 3. Python 3.9+ 可用 + flask 已装
PYTHON=$(which python3 2>/dev/null)
[ -n "$PYTHON" ] || err "python3 不在 PATH"
"$PYTHON" -c "import flask; print('  flask', flask.__version__)" 2>/dev/null || warn "flask 未装: pip3 install flask"
log "python3: $($PYTHON --version 2>&1)"

# 4. 本地副本存在 (绕过 OneDrive TCC)
if [ ! -f "$PROJECT_LOCAL/flask-app/modular_start.py" ]; then
  warn "本地副本不存在: $PROJECT_LOCAL"
  warn "正在从 OneDrive 同步到本地 (首次可能较慢)..."
  mkdir -p "$PROJECT_LOCAL"
  # 用 rsync (排除 .git, 只同步必要文件)
  rsync -a --exclude='.git' "$PROJECT_REMOTE/flask-app/" "$PROJECT_LOCAL/flask-app/" 2>/dev/null || \
    warn "rsync 失败, 请手动: rsync -a ~/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/ ~/MTSCOS_AI_Project/flask-app/"
fi
[ -f "$PROJECT_LOCAL/flask-app/modular_start.py" ] || err "modular_start.py 仍不存在 — 手动同步本地副本"
log "本地副本 OK: $PROJECT_LOCAL/flask-app"

# ── 安装 ──────────────────────────────────────────────────────────
echo ""
echo "── 安装 ──"

mkdir -p "$LAUNCH_AGENTS"

# backup old
if [ -f "$PLIST_DST" ]; then
  cp "$PLIST_DST" "$PLIST_DST.bak.$(date +%Y%m%d%H%M%S)"
  log "旧 plist 已 backup"
fi

# 拷贝新 plist
cp "$PLIST_SRC" "$PLIST_DST"
chmod 644 "$PLIST_DST"
log "plist 已拷贝到 $PLIST_DST"

# plutil 校验目标
plutil -lint "$PLIST_DST" >/dev/null 2>&1 || err "目标 plist 格式错误"

# 卸载旧进程 (ignore errors)
echo "  清理旧进程..."
launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
pkill -9 -f "modular_start.py" 2>/dev/null || true
sleep 2

# 加载新服务
echo "  加载 launchd 服务..."
if launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null; then
  log "launchctl bootstrap 成功"
else
  # 降级: 旧 load 方式
  launchctl load -w "$PLIST_DST" 2>/dev/null && log "launchctl load 成功" || \
    err "launchctl bootstrap/load 都失败 — 请在 Terminal.app 手动执行"
fi

# ── 验证 ──────────────────────────────────────────────────────────
echo ""
echo "── 验证 ──"
sleep 6  # 等 Flask 启动

# launchctl list
PID_STATUS=$(launchctl list 2>/dev/null | grep "com.mtscos.flask" || echo "")
if [ -n "$PID_STATUS" ]; then
  PID=$(echo "$PID_STATUS" | awk '{print $1}')
  EXIT=$(echo "$PID_STATUS" | awk '{print $2}')
  [ "$EXIT" = "0" ] && log "launchd PID=$PID exit=0 (正常运行)" || warn "launchd exit=$EXIT (KeepAlive 会自动重启)"
else
  err "launchd 没找到 com.mtscos.flask — 检查: launchctl list | grep flask"
fi

# LISTEN :8888
LISTEN_PID=$(lsof -i :8888 -sTCP:LISTEN -t 2>/dev/null | head -1)
[ -n "$LISTEN_PID" ] && log ":8888 LISTEN PID=$LISTEN_PID" || warn ":8888 未 LISTEN — 看日志: tail -20 /tmp/mtscos_flask.err"

# HTTP
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://127.0.0.1:8888/ 2>/dev/null)
[ "$HTTP_CODE" != "000" ] && log "HTTP $HTTP_CODE" || warn "HTTP 000 — Flask 还在启动中, 再等 5s 后 curl http://127.0.0.1:8888/"

echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  ✅ 安装完成                                           ║"
echo "║  launchctl list | grep flask     — 查看状态            ║"
echo "║  tail -f /tmp/mtscos_flask.err   — 实时日志            ║"
echo "║  $0 uninstall                    — 卸载                 ║"
echo "╚═══════════════════════════════════════════════════════╝"
