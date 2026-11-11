#!/bin/bash
# MTSCOS 自动文档生成器 — Weekly cron wrapper
# launchd plist: ~/Library/LaunchAgents/com.mtscos.doc-updater.plist
# 触发时间: 每周日 16:00 (周末引擎完成后)

set -eu

FLASK_APP="/Users/wuchenghao/MTSCOS_AI_Project/flask-app"
LOG_DIR="/Users/wuchenghao/MTSCOS_AI_Project/_runtime/logs"
LOG_FILE="${LOG_DIR}/auto_doc_updater_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

echo "===== MTSCOS AutoDoc Updater $(date) =====" | tee -a "$LOG_FILE"

cd "$FLASK_APP" || { echo "FATAL: cd failed"; exit 1; }

PYTHON_BIN="$(command -v python3 || echo /usr/bin/python3)"

# 运行文档生成器 (run 模式: hash-diff 驱动,无变更则 skip)
"$PYTHON_BIN" engines/auto_doc_generator.py run 2>&1 | tee -a "$LOG_FILE"
RC=$?

echo "===== Exit: $RC at $(date) =====" | tee -a "$LOG_FILE"

# 清理旧日志 (> 30 天)
find "$LOG_DIR" -name "auto_doc_updater_*.log" -mtime +30 -delete 2>/dev/null || true

exit $RC
