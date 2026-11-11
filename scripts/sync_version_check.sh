#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 📡 sync_version_check.sh  开发机 vs Mac mini 版本差异自动检测
# ─────────────────────────────────────────────────────────────
# 用法: bash scripts/sync_version_check.sh [--fix]
# 输出: 文件差异列表 + DB 行数差异 + VERSION 差异 + HTML diff
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SERVER_USER="${SERVER_USER:-wuchenghao}"
SERVER_HOST="${SERVER_HOST:-100.106.220.96}"
SERVER_BASE="${SERVER_BASE:-~/MTSCOS_AI_Project}"
SSH_CMD="ssh -o ConnectTimeout=8 ${SERVER_USER}@${SERVER_HOST}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# scripts/ 在 flask-app/scripts/ 下, PROJECT_ROOT 要再退一层
FLASK_APP_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$FLASK_APP_DIR")"
cd "$PROJECT_ROOT"

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; CYN='\033[0;36m'; RST='\033[0m'

echo "═══════════════════════════════════════════════════════════"
echo "  📡 MTSCOS AI 版本差异检测 (DEV ↔ Mac mini)"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════"

# ── 1. 快速连通性 ──
echo -e "\n${CYN}[1/5] 连通性检测${RST}"
if ! $SSH_CMD "echo ok" 2>/dev/null; then
  echo -e "  ${RED}❌ SSH 连接失败: ${SERVER_USER}@${SERVER_HOST}${RST}"
  exit 1
fi
echo -e "  ${GRN}✅ SSH OK${RST}"

# ── 2. VERSION + node_role 差异 ──
echo -e "\n${CYN}[2/5] VERSION / NODE_ROLE / Flask PID${RST}"
DEV_VER=$(cat flask-app/VERSION 2>/dev/null || echo "MISSING")
MAC_VER=$($SSH_CMD "cat ${SERVER_BASE}/flask-app/VERSION 2>/dev/null || echo MISSING")
# DEV NODE_ROLE: 开发机 hardcoded DEV (不依赖 import, 可能跑)
DEV_NR="DEV (hardcoded)"
# MAC NODE_ROLE: 从 plist 读 (权威源)
MAC_NR=$($SSH_CMD '/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:NODE_ROLE" $HOME/Library/LaunchAgents/com.mtscos.flask.plist 2>/dev/null || echo MISSING')
MAC_PID=$($SSH_CMD "pgrep -f modular_start || echo DOWN")

echo "  开发机 VERSION:   $DEV_VER  | NODE_ROLE: $DEV_NR"
echo "  Mac mini VERSION: $MAC_VER  | NODE_ROLE: $MAC_NR  | Flask PID: $MAC_PID"
[ "$DEV_VER" != "$MAC_VER" ] && echo -e "  ${RED}❌ VERSION 不一致!${RST}" || echo -e "  ${GRN}✅ VERSION 一致${RST}"
[ "$MAC_PID" = "DOWN" ] && echo -e "  ${RED}❌ Mac mini Flask 挂了!${RST}" || echo -e "  ${GRN}✅ Flask 运行中${RST}"

# ── 3. 关键文件 SHA256 对比 (快速, 不遍历 17439 文件) ──
echo -e "\n${CYN}[3/5] 关键文件 SHA256 差异${RST}"
KEY_FILES=(
  "VERSION"
  "templates/andromeda_iceberg_center.html"
  "templates/index.html"
  "templates/login.html"
  "routes/__init__.py"
  "routes/mobile_iceberg_routes.py"
  "engines/ai_smart_mount_engine.py"
  "engines/ai_local_inference_engine.py"
  "blueprints/chat_local_bp.py"
  "ai_engines/rules_engine/rule_interceptor.py"
)
DIFF_COUNT=0
for F in "${KEY_FILES[@]}"; do
  DSHA=$(shasum "flask-app/$F" 2>/dev/null | awk '{print $1}' | head -c 12)
  MSHA=$($SSH_CMD "shasum ${SERVER_BASE}/flask-app/$F 2>/dev/null | awk '{print \$1}' | head -c 12" 2>/dev/null)
  if [ "$DSHA" != "$MSHA" ]; then
    echo -e "  ${RED}❌ $F${RST}"
    echo -e "      dev=$DSHA  mac=$MSHA"
    DIFF_COUNT=$((DIFF_COUNT + 1))
  fi
done
echo -e "  差异文件: ${YEL}${DIFF_COUNT}${RST} / ${#KEY_FILES[@]} 关键文件"

# 额外: 文件总数
echo -n "  文件总数: "
DEV_T=$(find flask-app -type f ! -path '*/__pycache__/*' ! -name '*.db' ! -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' ')
MAC_T=$($SSH_CMD "find ${SERVER_BASE}/flask-app -type f ! -path '*/__pycache__/*' ! -name '*.db' ! -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' '" 2>/dev/null)
printf "dev=%s mac=%s  " "$DEV_T" "$MAC_T"
[ "$DEV_T" = "$MAC_T" ] && echo -e "${GRN}✅${RST}" || echo -e "${RED}❌${RST}"

# ── 4. DB 行数差异 (只读, 不写入) ──
echo -e "\n${CYN}[4/5] 关键 DB 表行数差异 (engines/app.db)${RST}"
DB_TABLES="mt_daemon_registry mt_ai_smart_mount_processes mt_ai_employees mt_ai_local_inference_log mt_local_ai_token_savings mt_ai_eigenflux_network mt_evolution"
echo -e "  ${CYN} 表名                          开发机     Mac mini   差异${RST}"
echo -e "  ──────────────────────────────┬──────────┬──────────┬────────"
for T in $DB_TABLES; do
  DEV_C=$(sqlite3 engines/app.db "SELECT COUNT(*) FROM $T" 2>/dev/null || echo "?")
  MAC_C=$($SSH_CMD "sqlite3 ${SERVER_BASE}/flask-app/engines/app.db \"SELECT COUNT(*) FROM $T\"" 2>/dev/null || echo "?")
  if [ "$DEV_C" != "$MAC_C" ] && [ "$DEV_C" != "?" ] && [ "$MAC_C" != "?" ]; then
    DIFF=$((DEV_C - MAC_C))
    echo -e "  ${RED}$T${RST}     ${DEV_C}   ${MAC_C}   ${DIFF}"
  else
    echo "  $T     $DEV_C   $MAC_C   ✅"
  fi
done

# ── 5. HTML 内容 diff (本地 vs 公网) ──
echo -e "\n${CYN}[5/5] 前端页面内容 diff (localhost ↔ mtos.site)${RST}"
DEV_HTML=$(mktemp)
PUB_HTML=$(mktemp)
curl -s --max-time 10 "http://localhost:8888/andromeda/iceberg_center" > "$DEV_HTML"
curl -s --max-time 20 "https://www.mtos.site/andromeda/iceberg_center" > "$PUB_HTML"

clean() { sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:]+/TS/g; s/[0-9]{10,}/NUM/g; s/\?v=[a-zA-Z0-9_-]+/?v=V/g; s/nonce="[a-zA-Z0-9+=/]+"/nonce="X"/g'; }
HTML_DIFF=$(diff <(clean "$DEV_HTML") <(clean "$PUB_HTML") 2>/dev/null || true)

DEV_SIZE=$(wc -c < "$DEV_HTML" | tr -d ' ')
PUB_SIZE=$(wc -c < "$PUB_HTML" | tr -d ' ')
echo "  开发机 localhost: $DEV_SIZE bytes"
echo "  公网 mtos.site:   $PUB_SIZE bytes"

if [ -z "$HTML_DIFF" ]; then
  echo -e "  ${GRN}🎉🎉🎉 前端页面完全一致!${RST}"
else
  DIFF_LINES=$(echo "$HTML_DIFF" | wc -l | tr -d ' ')
  echo -e "  ${RED}❌ 前端页面有差异: ${DIFF_LINES} 行${RST}"
  echo "$HTML_DIFF" | head -10
fi

# ── 汇总 ──
echo ""
echo "═══════════════════════════════════════════════════════════"
# 兜底: 确保算术变量是纯数字
NEW_FILES=${NEW_FILES:-0}; UPDATE_FILES=${UPDATE_FILES:-0}; DELETE_FILES=${DELETE_FILES:-0}
NEW_FILES=$(echo "$NEW_FILES" | grep -oE '[0-9]+' | head -1)
UPDATE_FILES=$(echo "$UPDATE_FILES" | grep -oE '[0-9]+' | head -1)
DELETE_FILES=$(echo "$DELETE_FILES" | grep -oE '[0-9]+' | head -1)
NEW_FILES=${NEW_FILES:-0}; UPDATE_FILES=${UPDATE_FILES:-0}; DELETE_FILES=${DELETE_FILES:-0}
TOTAL_DIFF=$((NEW_FILES + UPDATE_FILES + DELETE_FILES))
if [ "$TOTAL_DIFF" -eq 0 ] && [ -z "$HTML_DIFF" ] && [ "$DEV_VER" = "$MAC_VER" ]; then
  echo -e "  ${GRN}✅✅✅ 开发机与 Mac mini 完全同步!${RST}"
  EXIT_CODE=0
else
  echo -e "  ${YEL}⚠️  检测到 ${TOTAL_DIFF} 个文件差异 + VERSION 状态需同步${RST}"
  echo -e "  修复命令: bash scripts/deploy_to_server.sh"
  EXIT_CODE=1
fi
echo "═══════════════════════════════════════════════════════════"
exit $EXIT_CODE