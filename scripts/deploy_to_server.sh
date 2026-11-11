#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 🚀 deploy_to_server.sh  一键部署 开发机 → Mac mini
# ─────────────────────────────────────────────────────────────
# 流程: 数据备份 → Flask 停 → __pycache__ 清 → rsync --delete
#        → Flask reload → HTTP 等待 → 字节级 diff 验证
# ─────────────────────────────────────────────────────────────
# 用法: bash scripts/deploy_to_server.sh [--skip-backup]
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SERVER_USER="${SERVER_USER:-wuchenghao}"
SERVER_HOST="${SERVER_HOST:-100.106.220.96}"
SERVER_BASE="${SERVER_BASE:-~/MTSCOS_AI_Project}"
SSH_CMD="ssh -o ConnectTimeout=10 ${SERVER_USER}@${SERVER_HOST}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# scripts/ 在 flask-app/scripts/ 下, 所以 PROJECT_ROOT 要再退一层
FLASK_APP_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$FLASK_APP_DIR")"
cd "$FLASK_APP_DIR"

BACKUP_DIR="${FLASK_APP_DIR}/_deploy_backup_$(date +%Y%m%d_%H%M%S)"
SKIP_BACKUP=false
for ARG in "$@"; do [ "$ARG" = "--skip-backup" ] && SKIP_BACKUP=true; done

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; CYN='\033[0;36m'; RST='\033[0m'

echo "═══════════════════════════════════════════════════════════"
echo "  🚀 MTSCOS AI 一键部署 (DEV → Mac mini)"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════"

# ── 0. 确认连通性 ──
echo -e "\n${CYN}[0/7] 连通性${RST}"
$SSH_CMD "echo ok" > /dev/null 2>&1 || { echo -e "  ${RED}❌ SSH 连接失败${RST}"; exit 1; }
echo -e "  ${GRN}✅ SSH OK → ${SERVER_USER}@${SERVER_HOST}${RST}"

# ── 1. 数据保护 (AI 衍生数据不能丢!) ──
if [ "$SKIP_BACKUP" = false ]; then
  echo -e "\n${CYN}[1/7] 数据保护 → 开发机备份${RST}"
  mkdir -p "$BACKUP_DIR"
  mkdir -p "${BACKUP_DIR}/engines" "${BACKUP_DIR}/database" "${BACKUP_DIR}/runtime"
  rsync -avz --progress \
    "${SERVER_USER}@${SERVER_HOST}:${SERVER_BASE}/flask-app/engines/app.db" \
    "${BACKUP_DIR}/engines/app.db" 2>&1 | tail -2
  rsync -avz \
    "${SERVER_USER}@${SERVER_HOST}:${SERVER_BASE}/flask-app/database/" \
    "${BACKUP_DIR}/database/" 2>&1 | tail -2
  rsync -avz \
    "${SERVER_USER}@${SERVER_HOST}:${SERVER_BASE}/flask-app/ai_engines/_runtime/" \
    "${BACKUP_DIR}/runtime/" 2>&1 | tail -2
  echo -e "  ${GRN}✅ 已备份到: ${BACKUP_DIR}${RST}"
else
  echo -e "\n${YEL}[1/7] 跳过数据备份 (--skip-backup)${RST}"
fi

# ── 2. 停 Mac mini Flask ──
echo -e "\n${CYN}[2/7] 停 Mac mini Flask${RST}"
$SSH_CMD 'export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin
  pkill -9 -f modular_start 2>/dev/null || true
  sleep 2
  cd '"${SERVER_BASE}"'/flask-app
  find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  find . -name "*.pyc" -delete 2>/dev/null || true
  rm -rf instance/ 2>/dev/null || true
  echo "✅ Flask 已停 + pycache 已清"
' 2>&1 | tail -3

# ── 3. rsync --delete 全量覆盖 ──
echo -e "\n${CYN}[3/7] rsync --delete 全量同步 flask-app/${RST}"
RSYNC_START=$(date +%s)
rsync -avz --delete \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.pyo' \
  --exclude='*.db' --exclude='*.db-journal' --exclude='*.db-wal' --exclude='*.db-shm' \
  --exclude='engines/app.db' --exclude='engines/app.db-journal' \
  --exclude='_runtime/' --exclude='modular_start.pid' --exclude='.git/' \
  --exclude='.git_disabled/' --exclude='_archive/' --exclude='Database_Backups/' \
  --exclude='artifacts/' --exclude='data/' \
  "." "${SERVER_USER}@${SERVER_HOST}:${SERVER_BASE}/flask-app/" 2>&1 | tail -15
RSYNC_END=$(date +%s)
RSYNC_TIME=$((RSYNC_END - RSYNC_START))
echo -e "  ${GRN}✅ rsync exit=0 (耗时 ${RSYNC_TIME}s)${RST}"

# ── 4. Flask reload ──
echo -e "\n${CYN}[4/7] Mac mini Flask reload${RST}"
$SSH_CMD 'export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin
  UID=$(id -u)
  LABEL=$(/usr/libexec/PlistBuddy -c "Print :Label" ~/Library/LaunchAgents/com.mtscos.flask.plist)
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  sleep 2
  launchctl bootstrap "gui/$UID" ~/Library/LaunchAgents/com.mtscos.flask.plist
  launchctl enable "gui/$UID/$LABEL"
  echo "✅ launchctl bootup 完成"
' 2>&1 | tail -3

# ── 5. HTTP 等待 (最多 45s) ──
echo -e "\n${CYN}[5/7] 等待 Flask HTTP 就绪${RST}"
READY=false
for I in $(seq 1 15); do
  sleep 3
  STATUS=$($SSH_CMD "curl -s -o /dev/null -w '%{http_code}' http://localhost:8888/andromeda/iceberg_center" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    READY=true
    echo -e "  ${GRN}✅ Flask 就绪! (${I}×3s = $((I*3))s)${RST}"
    break
  fi
done
if [ "$READY" = false ]; then
  echo -e "  ${RED}❌ Flask 45s 内没就绪! 请手动检查${RST}"
  exit 1
fi

# ── 6. 公网 URL 等待 (CF Tunnel) ──
echo -e "\n${CYN}[6/7] 等待 Cloudflare Tunnel${RST}"
for I in $(seq 1 6); do
  sleep 3
  PUB_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "https://www.mtos.site/andromeda/iceberg_center" 2>/dev/null || echo "000")
  if [ "$PUB_STATUS" = "200" ]; then
    echo -e "  ${GRN}✅ 公网 OK (${I}×3s = $((I*3))s)${RST}"
    break
  fi
done

# ── 7. 字节级 diff 验证 ──
echo -e "\n${CYN}[7/7] 两端 HTML 字节级 diff 验证${RST}"
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

# 关键元素计数核对
ALL_MATCH=true
for LABEL in "守护矩阵 v" "七层防线" "ICEBERG GUARD"; do
  D=$(grep -c "$LABEL" "$DEV_HTML" 2>/dev/null || echo 0)
  P=$(grep -c "$LABEL" "$PUB_HTML" 2>/dev/null || echo 0)
  if [ "$D" = "$P" ]; then
    echo -e "  ${GRN}✅${RST} $LABEL: dev=$D pub=$P"
  else
    echo -e "  ${RED}❌${RST} $LABEL: dev=$D pub=$P"
    ALL_MATCH=false
  fi
done

echo ""
echo "═══════════════════════════════════════════════════════════"
if [ -z "$HTML_DIFF" ] && [ "$ALL_MATCH" = true ]; then
  echo -e "  ${GRN}🎉🎉🎉 部署完成! 开发机 ↔ Mac mini 完全一致!${RST}"
  echo -e "  数据备份: ${BACKUP_DIR}"
  EXIT_CODE=0
else
  echo -e "  ${YEL}⚠️  部署后仍有差异, 请检查${RST}"
  [ -n "$HTML_DIFF" ] && echo "  HTML diff lines: $(echo "$HTML_DIFF" | wc -l | tr -d ' ')"
  EXIT_CODE=1
fi
echo "═══════════════════════════════════════════════════════════"
exit $EXIT_CODE