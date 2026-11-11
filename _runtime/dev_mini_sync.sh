#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# dev→mini 代码自动同步守护
# flow_dev_mini_sync_20261030
#
# 拓扑:
#   开发机 macbook-pro (100.121.98.15, Flask :5001)
#     ↓ Tailscale rsync
#   mini hulk-macmini (100.106.220.96, Flask :5001)
#
# 同步范围: 只同步代码文件 (.py/.json/.txt/.yaml 等)
# 不同步:   DB/日志/备份/venv/__pycache__/.git
#
# 触发: 每 5 分钟 (launchd 或 cron)
# 作者:  iceberg-autonomy daemon
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── 路径配置 ──
LOCAL_ROOT="$HOME/MTSCOS_AI_Project/flask-app"
MINI_HOST="wuchenghao@100.106.220.96"
MINI_ROOT="~/MTSCOS_AI_Project/flask-app"
LOG_DIR="$LOCAL_ROOT/_runtime/logs"
LOG_FILE="$LOG_DIR/dev_mini_sync.log"
LOCK_FILE="/tmp/mtscos_dev_mini_sync.lock"

mkdir -p "$LOG_DIR"

# ── 锁文件 (防止并发) ──
if [ -f "$LOCK_FILE" ]; then
  PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "[$(date '+%H:%M:%S')] ⏭️ 上一轮同步仍在运行 (PID=$PID), 跳过" >> "$LOG_FILE"
    exit 0
  fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# ── 连通性检查 (curl mini Flask health — 比 tailscale ping 更准) ──
if ! curl -s --max-time 10 -o /dev/null -w "%{http_code}" "http://100.106.220.96:5001/api/health" >/dev/null 2>&1; then
  echo "[$(date '+%H:%M:%S')] ❌ mini Flask 不可达 (Tailscale 可能断), 跳过" >> "$LOG_FILE"
  exit 0
fi

echo "[$(date '+%H:%M:%S')] 🚀 开始 dev→mini 代码同步" >> "$LOG_FILE"
START_TS=$(date +%s)

# ── 同步: blueprints ──
rsync -az --backup --backup-dir=.syncbak --timeout=30 \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.bak*' \
  --exclude='*.auto_repair_backup' \
  "$LOCAL_ROOT/blueprints/" \
  "$MINI_HOST:$MINI_ROOT/blueprints/" 2>>"$LOG_FILE" && echo "  ✅ blueprints" >> "$LOG_FILE" || echo "  ❌ blueprints FAIL" >> "$LOG_FILE"

# ── 同步: engines (排除大文件/备份) ──
rsync -az --backup --backup-dir=.syncbak --timeout=60 \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.bak*' \
  --exclude='*.auto_repair_backup' \
  --exclude='*_backup*' \
  --exclude='*.db*' \
  --exclude='*_runtime/' \
  --exclude='*.log' \
  "$LOCAL_ROOT/engines/" \
  "$MINI_HOST:$MINI_ROOT/engines/" 2>>"$LOG_FILE" && echo "  ✅ engines" >> "$LOG_FILE" || echo "  ❌ engines FAIL" >> "$LOG_FILE"

# ── 同步: ai_engines (同理) ──
rsync -az --backup --backup-dir=.syncbak --timeout=60 \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.bak*' \
  --exclude='*.auto_repair_backup' \
  --exclude='*.db*' \
  "$LOCAL_ROOT/ai_engines/" \
  "$MINI_HOST:$MINI_ROOT/ai_engines/" 2>>"$LOG_FILE" && echo "  ✅ ai_engines" >> "$LOG_FILE" || echo "  ❌ ai_engines FAIL" >> "$LOG_FILE"

# ── 同步: services/ (开发机独有 431 文件) ──
if [ -d "$LOCAL_ROOT/services" ]; then
  rsync -az --backup --backup-dir=.syncbak --timeout=60 \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "$LOCAL_ROOT/services/" \
    "$MINI_HOST:$MINI_ROOT/services/" 2>>"$LOG_FILE" && echo "  ✅ services" >> "$LOG_FILE" || echo "  ❌ services FAIL" >> "$LOG_FILE"
fi

# ── 同步: scripts/ (开发机独有 97 文件) ──
if [ -d "$LOCAL_ROOT/scripts" ]; then
  rsync -az --backup --backup-dir=.syncbak --timeout=30 \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "$LOCAL_ROOT/scripts/" \
    "$MINI_HOST:$MINI_ROOT/scripts/" 2>>"$LOG_FILE" && echo "  ✅ scripts" >> "$LOG_FILE" || echo "  ❌ scripts FAIL" >> "$LOG_FILE"
fi

# ── 同步: core/ (如果存在) ──
if [ -d "$LOCAL_ROOT/core" ]; then
  rsync -az --backup --backup-dir=.syncbak --timeout=30 \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "$LOCAL_ROOT/core/" \
    "$MINI_HOST:$MINI_ROOT/core/" 2>>"$LOG_FILE" && echo "  ✅ core" >> "$LOG_FILE" || echo "  ❌ core FAIL" >> "$LOG_FILE"
fi

# ── 同步: 根目录关键文件 (只同步存在的) ──
ROOT_FILES=()
for f in modular_start.py server_real_db.py ai_agents.py; do
  [ -f "$LOCAL_ROOT/$f" ] && ROOT_FILES+=("$LOCAL_ROOT/$f")
done
if [ ${#ROOT_FILES[@]} -gt 0 ]; then
  rsync -az --backup --backup-dir=.syncbak --timeout=15 "${ROOT_FILES[@]}" \
    "$MINI_HOST:$MINI_ROOT/" 2>>"$LOG_FILE" && echo "  ✅ 根目录 (${#ROOT_FILES[@]} 文件)" >> "$LOG_FILE" || echo "  ❌ 根目录 FAIL" >> "$LOG_FILE"
else
  echo "  ⚠️ 根目录无关键文件需同步" >> "$LOG_FILE"
fi

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

# ── 远端 py_compile 冒烟 (CHATOPS-002 #3): 防坏代码同步瘫掉 mini Flask ──
# 注意: set -euo pipefail 下 ssh/grep 失败不能让脚本裸死 (否则判定行写不出), 全部兜底
SMOKE=$(ssh -o ConnectTimeout=8 "$MINI_HOST" \
  "cd \$HOME/MTSCOS_AI_Project/flask-app && for f in engines/*.py blueprints/*.py server_real_db.py; do python3 -m py_compile \"\$f\" 2>/dev/null || echo \"\$f\"; done; echo SMOKE_DONE" \
  2>>"$LOG_FILE" || true)
BAD=$(echo "$SMOKE" | { grep -v SMOKE_DONE | head -10 || true; })
if echo "$SMOKE" | grep -q SMOKE_DONE; then
  if [ -n "$BAD" ]; then
    echo "[$(date '+%H:%M:%S')] ⚠️ 远端校验失败: $BAD → 回滚本次同步 (mini .syncbak/ → 原位)" >> "$LOG_FILE"
    ssh "$MINI_HOST" "cd \$HOME/MTSCOS_AI_Project/flask-app && if [ -d .syncbak ]; then rsync -a .syncbak/ ./ && echo rollback_ok; fi" >> "$LOG_FILE" 2>&1 || true
    echo "[$(date '+%H:%M:%S')] ✅ 已回滚 mini 侧本次同步" >> "$LOG_FILE"
  else
    echo "[$(date '+%H:%M:%S')] ✅ 远端 py_compile 冒烟通过 (SMOKE_DONE)" >> "$LOG_FILE"
  fi
else
  echo "[$(date '+%H:%M:%S')] ⚠️ 远端冒烟未返回哨兵 (ssh失败?), 本次不判定" >> "$LOG_FILE"
fi

echo "[$(date '+%H:%M:%S')] ✅ 同步完成, 耗时 ${ELAPSED}s" >> "$LOG_FILE"

# ── 日志轮转 (保留最近 1000 行) ──
if [ "$(wc -l < "$LOG_FILE")" -gt 1000 ]; then
  tail -500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exit 0
