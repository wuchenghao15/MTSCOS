#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# dev_hulk_sync.sh — dev 开发机 → hulk-server (HP DL360) 代码同步
# flow_dev_hulk_sync_20261030 (CHATOPS-002 延伸 HULK-SYNC)
#
# 拓扑:
#   开发机 macbook-pro (100.121.98.15, Flask :5001)
#     ↓ Tailscale rsync
#   hulk-server (100.100.244.47, Ubuntu 24.04)
#
# 触发: launchd com.mtscos.dev-hulk-sync 每 30min
# 前置: hulk-server 必须 mkfs 重装 (inode 100% 满), 先写好等待
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

LOCAL_ROOT="$HOME/MTSCOS_AI_Project/flask-app"
HULK_USER="wuchenghao15"
HULK_HOST="hulk-server"
HULK_IP="100.100.244.47"
HULK_REMOTE_ROOT='${HOME}/MTSCOS_AI_Project/flask-app'   # 远程机器上展开 (单引号防本机 bash 展开)
HULK_ABS_ROOT="/home/${HULK_USER}/MTSCOS_AI_Project/flask-app"  # rsync 用绝对路径更安全
LOG_DIR="$LOCAL_ROOT/_runtime/logs"
LOG_FILE="$LOG_DIR/dev_hulk_sync.log"
LOCK_FILE="/tmp/mtscos_dev_hulk_sync.lock"

mkdir -p "$LOG_DIR"

# ── 锁 ──
if [ -f "$LOCK_FILE" ]; then
  PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "[$(date '+%H:%M:%S')] ⏭️ 上一轮仍在运行, 跳过" >> "$LOG_FILE"
    exit 0
  fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# ── hulk 可达? (Tailscale ping + SSH) ──
if ! tailscale ping -c 1 "$HULK_IP" &>/dev/null; then
  echo "[$(date '+%H:%M:%S')] ❌ hulk-server 不可达 (Tailscale), 跳过" >> "$LOG_FILE"
  exit 0
fi
if ! ssh -4 -o ConnectTimeout=6 -o BatchMode=yes "$HULK_USER@$HULK_IP" 'hostname' &>/dev/null; then
  echo "[$(date '+%H:%M:%S')] ❌ hulk-server SSH 不通, 跳过" >> "$LOG_FILE"
  exit 0
fi

# ── hulk inode 健康度 (IUse% ≥ 95% 就跳过) ──
# Ubuntu df -i 列: Filesystem Inodes IUsed IFree IUse% Mounted on → IUse% 在第 5 列
IUSE_PCT=$(ssh -4 "$HULK_USER@$HULK_IP" 'df -i / | tail -1' | awk '{print $5}' | tr -d '%')
if [ "$IUSE_PCT" -ge 95 ] 2>/dev/null; then
  echo "[$(date '+%H:%M:%S')] ❌ hulk inode 占用 ${IUSE_PCT}% → 跳过 (必须 mkfs 重装)" >> "$LOG_FILE"
  exit 0
fi
FREE_INODE=$(ssh -4 "$HULK_USER@$HULK_IP" 'df -i / | tail -1' | awk '{print $4}')

# ── hulk 上确保目录存在 ──
ssh -4 "$HULK_USER@$HULK_IP" "mkdir -p $HULK_ABS_ROOT" 2>/dev/null || {
  echo "[$(date '+%H:%M:%S')] ❌ hulk 目录创建失败 → 跳过" >> "$LOG_FILE"
  exit 0
}

echo "[$(date '+%H:%M:%S')] 🚀 dev→hulk 同步开始 (inode=${IUSE_PCT}%)" >> "$LOG_FILE"
START_TS=$(date +%s)

RSYNC_COMMON="-az --backup --backup-dir=.syncbak --timeout=30 --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.bak*' --exclude='*.auto_repair_backup'"

# blueprints
rsync $RSYNC_COMMON "$LOCAL_ROOT/blueprints/" "$HULK_USER@$HULK_IP:$HULK_ABS_ROOT/blueprints/" 2>>"$LOG_FILE" && echo "  ✅ blueprints" >> "$LOG_FILE" || echo "  ❌ blueprints FAIL" >> "$LOG_FILE"

# engines
rsync $RSYNC_COMMON "$LOCAL_ROOT/engines/" "$HULK_USER@$HULK_IP:$HULK_ABS_ROOT/engines/" 2>>"$LOG_FILE" && echo "  ✅ engines" >> "$LOG_FILE" || echo "  ❌ engines FAIL" >> "$LOG_FILE"

# ai_engines / services / scripts / core
for d in ai_engines services scripts core; do
  [ -d "$LOCAL_ROOT/$d" ] || continue
  rsync $RSYNC_COMMON "$LOCAL_ROOT/$d/" "$HULK_USER@$HULK_IP:$HULK_ABS_ROOT/$d/" 2>>"$LOG_FILE" && echo "  ✅ $d" >> "$LOG_FILE" || echo "  ❌ $d FAIL" >> "$LOG_FILE"
done

# 根目录关键文件
ROOT_FILES=()
for f in modular_start.py server_real_db.py ai_agents.py requirements.txt; do
  [ -f "$LOCAL_ROOT/$f" ] && ROOT_FILES+=("$LOCAL_ROOT/$f")
done
if [ ${#ROOT_FILES[@]} -gt 0 ]; then
  rsync $RSYNC_COMMON "${ROOT_FILES[@]}" "$HULK_USER@$HULK_IP:$HULK_ABS_ROOT/" 2>>"$LOG_FILE" && echo "  ✅ 根目录 (${#ROOT_FILES[@]} 文件)" >> "$LOG_FILE"
fi

END_TS=$(date +%s); ELAPSED=$((END_TS - START_TS))

# ── 远端 py_compile 冒烟 (CHATOPS-002 #3 同款机制) ──
# 用单引号包裹远程命令块, $f 在远程 bash 展开
SMOKE=$(ssh -4 -o ConnectTimeout=10 "$HULK_USER@$HULK_IP" \
  'cd /home/'"$HULK_USER"'/MTSCOS_AI_Project/flask-app && for f in engines/*.py blueprints/*.py server_real_db.py 2>/dev/null; do python3 -m py_compile "$f" 2>/dev/null || echo "$f"; done; echo SMOKE_DONE' \
  2>>"$LOG_FILE" || true)
BAD=$(echo "$SMOKE" | { grep -v SMOKE_DONE | head -10 || true; })

if echo "$SMOKE" | grep -q SMOKE_DONE; then
  if [ -n "$BAD" ]; then
    echo "[$(date '+%H:%M:%S')] ⚠️ hulk 远端校验失败: $BAD → 回滚" >> "$LOG_FILE"
    ssh -4 "$HULK_USER@$HULK_IP" "cd $HULK_ROOT && [ -d .syncbak ] && rsync -a .syncbak/ ./" 2>/dev/null || true
    echo "[$(date '+%H:%M:%S')] ✅ 已回滚" >> "$LOG_FILE"
  else
    echo "[$(date '+%H:%M:%S')] ✅ hulk 远端 py_compile 冒烟通过 (SMOKE_DONE)" >> "$LOG_FILE"
  fi
else
  echo "[$(date '+%H:%M:%S')] ⚠️ hulk 远端冒烟未返回哨兵 → 本次不判定" >> "$LOG_FILE"
fi

echo "[$(date '+%H:%M:%S')] ✅ dev→hulk 同步完成, 耗时 ${ELAPSED}s" >> "$LOG_FILE"

# ── 日志轮转 ──
if [ "$(wc -l < "$LOG_FILE")" -gt 1000 ]; then
  tail -500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exit 0
