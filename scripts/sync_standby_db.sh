#!/bin/bash
# flow_db_standby_sync_20261027: 每小时自动热同步 app_standby.db
# macOS 无 flock, 用 PID 文件防并发
set -euo pipefail

DB_DIR="/Users/wuchenghao/MTSCOS_AI_Project/flask-app/Database"
MAIN="$DB_DIR/app.db"
STANDBY="$DB_DIR/app_standby.db"
PIDF="/tmp/.mtscos_standby_sync.pid"
LOG="/Users/wuchenghao/MTSCOS_AI_Project/_runtime/logs/standby_sync.log"

mkdir -p "$(dirname "$LOG")"

# PID 文件并发防护
if [ -f "$PIDF" ]; then
  _old=$(cat "$PIDF" 2>/dev/null)
  if [ -n "$_old" ] && kill -0 "$_old" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SKIP: PID $_old 还在跑" >> "$LOG"
    exit 0
  fi
fi
echo $$ > "$PIDF"
trap "rm -f '$PIDF'" EXIT

if [ ! -f "$MAIN" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAIL: main db 不存在" >> "$LOG"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START: main_size=$(stat -f%z "$MAIN" 2>/dev/null)" >> "$LOG"
sqlite3 "$MAIN" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true

if sqlite3 "$MAIN" ".backup '$STANDBY'" 2>>"$LOG"; then
  main_rows=$(sqlite3 "$MAIN" "SELECT COUNT(*) FROM mt_lab_task_hall" 2>/dev/null || echo "?")
  sb_rows=$(sqlite3 "$STANDBY" "SELECT COUNT(*) FROM mt_lab_task_hall" 2>/dev/null || echo "?")
  sb_size=$(stat -f%z "$STANDBY" 2>/dev/null || echo "?")
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] OK: main_rows=$main_rows standby_rows=$sb_rows size=$sb_size" >> "$LOG"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAIL: .backup 出错" >> "$LOG"
  exit 2
fi
