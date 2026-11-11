#!/bin/bash
# mini_dev_sync.sh - dev→mini 单向 rsync (mini 是跳板, 每 10min)
set -euo pipefail
LOG_DIR="$(dirname "$0")/logs"; mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/mini_dev_sync.log"

DEV_ROOT="/Users/wuchenghao/MTSCOS_AI_Project/flask-app"
MINI_HOST="100.106.220.96"
MINI_USER="wuchenghao"
MINI_ROOT="$HOME/MTSCOS_AI_Project/flask-app"

echo "[$(date '+%H:%M:%S')] mini-dev-sync start" >> "$LOG"
if ! tailscale ping -c 1 "$MINI_HOST" &>/dev/null; then
  echo "  skip: mini unreachable" >> "$LOG"; exit 0
fi
rsync -az --delete \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='database/' \
  "$DEV_ROOT"/ "$MINI_USER@$MINI_HOST:$MINI_ROOT/" \
  2>> "$LOG" && echo "  rsync OK" >> "$LOG" || echo "  rsync FAIL $?" >> "$LOG"
exit 0
