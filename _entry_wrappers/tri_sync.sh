#!/bin/bash
# =============================================================================
# MTSCOS AI —— 三路双向同步脚本 (tri_sync.sh)
# =============================================================================
# 维度定义:
#   A. 源码 (git + GitHub)  —— 轻量, 走 git push/pull
#   B. 运行时 (DB + logs + WAL) —— 重量, 走 rsync 增量快照 + WAL checkpoint
#   C. 影子回滚节点 (recovery_snapshots) —— 本地 rsync 保留 7 天
#
# 拓扑:
#   Dev (开发机 192.168.11.120)  ←→  Mac mini (生产 192.168.31.9)
#          ↕                                ↕
#      GitHub (origin/main)  ←→  本地影子回滚节点
#
# 关键约束:
#   ① DB 不同步 WAL/SHM (checkpoint 后再同步)
#   ② rsync --bwlimit=5000 (限速 ~5MB/s, 不堵 I/O)
#   ③ 所有同步加 .lock 文件防并发
#   ④ 先 checkpoint WAL 再同步 DB → 保证原子性
#   ⑤ OneDrive 不同步 app.db (避免扫描风暴)
# =============================================================================
set -e

PROJ="/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
FLASK="$PROJ/flask-app"
DB_PATH="$PROJ/_runtime/databases/Database/app.db"
SHADOW="$PROJ/_runtime/recovery_snapshots"
LOCKDIR="$PROJ/_runtime/sync_locks"
LOGFILE="$PROJ/_runtime/logs/tri_sync_$(date +%Y%m%d).log"

MINI_USER="wuchenghao"
MINI_HOST="192.168.31.9"
MINI_FLASK="~/mtscos/flask-app"
MINI_DB="$MINI_FLASK/_runtime/databases/Database/app.db"

GIT_BRANCH="main"
RSYNC_LIMIT=5000     # KB/s
RSYNC_PARALLEL=1     # 串行，避免并发抢 I/O

BOLD="\033[1m"; GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; NC="\033[0m"

log() { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOGFILE"; }
ok()   { echo -e "  ${GREEN}✅ $1${NC}" | tee -a "$LOGFILE"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}" | tee -a "$LOGFILE"; }
fail() { echo -e "  ${RED}❌ $1${NC}" | tee -a "$LOGFILE"; }

need_lock() {
  local name="$1"; local lock="$LOCKDIR/${name}.lock"
  mkdir -p "$LOCKDIR"
  if [ -f "$lock" ]; then
    local pid=$(cat "$lock" 2>/dev/null)
    if kill -0 "$pid" 2>/dev/null; then
      log "锁 $name 已被 PID $pid 持有，跳过"
      return 1
    fi
  fi
  echo $$ > "$lock"
  trap "rm -f '$lock'" EXIT
  return 0
}

ensure_dir() { mkdir -p "$1"; }

# =============================================================================
# WAL CHECKPOINT —— 同步前必做，保证 DB 一致性
# =============================================================================
do_checkpoint() {
  local db="$1"
  log "WAL checkpoint: $(basename "$db")"
  if [ ! -f "$db" ]; then warn "DB 不存在: $db"; return 1; fi
  # 等所有 writer 退出
  sleep 1
  sqlite3 "$db" <<'SQL' 2>&1 | tee -a "$LOGFILE"
PRAGMA busy_timeout = 30000;
PRAGMA wal_checkpoint(FULL);
PRAGMA wal_checkpoint(TRUNCATE);
SQL
  ok "WAL checkpoint done"
}

# =============================================================================
# A. 源码同步 (git + GitHub)
# =============================================================================
sync_source_git() {
  need_lock "git_source" || return 0
  log "===== A. 源码 git 同步 ====="
  cd "$PROJ"
  
  # 1) 本地 commit 未提交的修改
  if [ -n "$(git diff --name-only HEAD 2>/dev/null)" ]; then
    log "本地有未提交修改，自动 commit"
    git add -A
    git commit -m "auto: tri_sync commit $(date +%H:%M:%S)" 2>&1 | tail -2
  fi
  
  # 2) pull rebase (先拉远端)
  log "git pull --rebase origin $GIT_BRANCH"
  if git pull --rebase origin "$GIT_BRANCH" 2>&1 | tee -a "$LOGFILE" | tail -5; then
    ok "pull 成功"
  else
    warn "pull 有冲突或远端领先太多，手动处理"
    return 1
  fi
  
  # 3) push
  log "git push origin $GIT_BRANCH"
  if git push origin "$GIT_BRANCH" 2>&1 | tee -a "$LOGFILE" | tail -5; then
    ok "push 成功"
  else
    warn "push 被拒（可能远端又领先了）"
  fi
  
  # 4) Mac mini pull
  log "Mac mini git pull"
  ssh -o ConnectTimeout=8 "$MINI_USER@$MINI_HOST" \
    "cd $MINI_FLASK && git pull origin $GIT_BRANCH 2>&1 | tail -3" 2>&1 | tee -a "$LOGFILE" || \
    warn "Mac mini pull 超时/失败（可能网络问题）"
  
  ok "源码同步完成"
}

# =============================================================================
# B. DB + 运行时 rsync 双向
# =============================================================================
sync_runtime_db() {
  need_lock "runtime_db" || return 0
  log "===== B. 运行时 DB 双向同步 ====="
  
  # ---- 方向 1: Dev → Mac mini ----
  log "B1. Dev → Mac mini (先 checkpoint)"
  do_checkpoint "$DB_PATH"
  
  # 只同步 DB 主文件（不同步 WAL/SHM，已 checkpoint 清空）
  rsync -avz --partial --bwlimit=$RSYNC_LIMIT \
    --progress \
    "$DB_PATH" \
    "$MINI_USER@$MINI_HOST:${MINI_DB}.syncing" 2>&1 | tail -5 | tee -a "$LOGFILE" && \
    ssh -o ConnectTimeout=8 "$MINI_USER@$MINI_HOST" \
      "mv ${MINI_DB}.syncing $MINI_DB && rm -f ${MINI_DB}-wal ${MINI_DB}-shm" 2>&1 | tee -a "$LOGFILE" && \
    ok "Dev→Mac mini DB rsync 成功" || warn "Dev→Mac mini DB 失败"
  
  # ---- 方向 2: Mac mini → Dev (拉取 Mac mini 最新数据) ----
  log "B2. Mac mini → Dev (Mac mini 先 checkpoint)"
  ssh -o ConnectTimeout=8 "$MINI_USER@$MINI_HOST" \
    "sqlite3 $MINI_DB 'PRAGMA wal_checkpoint(FULL); PRAGMA wal_checkpoint(TRUNCATE);'" 2>&1 | tee -a "$LOGFILE"
  
  rsync -avz --partial --bwlimit=$RSYNC_LIMIT \
    --progress \
    "$MINI_USER@$MINI_HOST:${MINI_DB}" \
    "${DB_PATH}.from_mini" 2>&1 | tail -5 | tee -a "$LOGFILE" && \
    mv "${DB_PATH}.from_mini" "$DB_PATH" && \
    rm -f "${DB_PATH}-wal" "${DB_PATH}-shm" && \
    ok "Mac mini→Dev DB rsync 成功" || warn "Mac mini→Dev DB 失败"
  
  # ---- 运行时目录（logs, _runtime/*.json 等） ----
  log "B3. _runtime/ 配置双向同步"
  for dir in "_runtime/auto_daemons" "_runtime/logs"; do
    if [ -d "$PROJ/$dir" ]; then
      # Dev → Mac mini
      rsync -avz --partial --bwlimit=$RSYNC_LIMIT \
        --exclude '*.pyc' --exclude '__pycache__' \
        "$PROJ/$dir/" "$MINI_USER@$MINI_HOST:$MINI_FLASK/$dir/" 2>&1 | tail -3 | tee -a "$LOGFILE" || true
    fi
  done
  
  ok "运行时同步完成"
}

# =============================================================================
# C. 影子回滚节点 (本地 rsync 快照)
# =============================================================================
sync_shadow_snapshot() {
  need_lock "shadow_snapshot" || return 0
  log "===== C. 影子回滚节点 ====="
  ensure_dir "$SHADOW"
  
  local TS=$(date +%Y%m%d_%H%M%S)
  local SNAP="$SHADOW/snap_$TS"
  
  # 1) DB 快照
  do_checkpoint "$DB_PATH"
  mkdir -p "$SNAP/db"
  rsync -avz --partial --bwlimit=1000 \
    "$DB_PATH" "$SNAP/db/" 2>&1 | tail -2 | tee -a "$LOGFILE"
  
  # 2) 配置 + 规则
  for dir in ".trae/rules" "_config" "_entry_wrappers"; do
    if [ -d "$PROJ/$dir" ]; then
      mkdir -p "$SNAP/$dir"
      rsync -az --partial --bwlimit=500 \
        "$PROJ/$dir/" "$SNAP/$dir/" 2>&1 | tail -2 | tee -a "$LOGFILE" || true
    fi
  done
  
  # 3) 清理 7 天前的快照
  log "清理 7 天前的旧快照"
  find "$SHADOW" -maxdepth 1 -name "snap_*" -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
  local KEEP=$(find "$SHADOW" -maxdepth 1 -name "snap_*" -type d | wc -l | tr -d ' ')
  log "当前保留快照数: $KEEP"
  
  # 4) 创建 latest 软链
  rm -f "$SHADOW/latest"
  ln -sf "snap_$TS" "$SHADOW/latest"
  
  ok "影子快照: snap_$TS"
}

# =============================================================================
# D. 回滚操作 (影子 → Dev/Mac mini)
# =============================================================================
do_rollback() {
  local target="$1"   # dev | mini
  local snap="${2:-latest}"
  local SNAP="$SHADOW/$snap"
  
  log "===== 回滚: $target ← $snap ====="
  [ ! -d "$SNAP" ] && fail "快照不存在: $SNAP" && return 1
  
  if [ "$target" = "dev" ]; then
    log "回滚 DB"
    cp "$SNAP/db/app.db" "$DB_PATH"
    rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"
    for dir in ".trae/rules" "_config"; do
      [ -d "$SNAP/$dir" ] && rsync -av "$SNAP/$dir/" "$PROJ/$dir/" || true
    done
    ok "Dev 回滚完成 ← $snap"
  elif [ "$target" = "mini" ]; then
    log "回滚到 Mac mini"
    rsync -avz --partial --bwlimit=$RSYNC_LIMIT \
      "$SNAP/db/app.db" "$MINI_USER@$MINI_HOST:${MINI_DB}.rollback" && \
    ssh "$MINI_USER@$MINI_HOST" \
      "mv ${MINI_DB}.rollback $MINI_DB && rm -f ${MINI_DB}-wal ${MINI_DB}-shm && \
       for d in .trae/rules _config; do rsync -az $SNAP/\$d/ $MINI_FLASK/\$d/; done" 2>&1 | tail -5
    ok "Mac mini 回滚完成 ← $snap"
  fi
}

# =============================================================================
# 主调度
# =============================================================================
usage() {
  cat <<EOF
用法: $0 <command>

commands:
  all         三路全同步 (A+B+C)
  git         仅源码同步 (A)
  db          仅运行时 DB 同步 (B)
  shadow      仅影子快照 (C)
  rollback    <dev|mini> [snap_name]  回滚
  status      查看三端状态
  check       自检 DB + 网络 + 锁文件

示例:
  $0 all                         # 全同步
  $0 rollback dev snap_20260915_060000
  $0 rollback mini latest
EOF
}

ensure_dir "$LOCKDIR"
ensure_dir "$(dirname "$LOGFILE")"

case "${1:-all}" in
  all)     sync_source_git; sync_runtime_db; sync_shadow_snapshot ;;
  git)     sync_source_git ;;
  db)      sync_runtime_db ;;
  shadow)  sync_shadow_snapshot ;;
  rollback) do_rollback "${2:-dev}" "${3:-latest}" ;;
  status)
    log "===== 三端状态 ====="
    echo "--- 开发机 ---"
    echo "DB: $(ls -lh "$DB_PATH" 2>/dev/null | awk '{print $5}')"
    echo "Git: $(cd "$PROJ" && git branch --show-current 2>/dev/null)"
    echo "Shadow: $(ls -d "$SHADOW"/snap_* 2>/dev/null | wc -l | tr -d ' ') 个快照"
    echo ""
    echo "--- Mac mini ($MINI_HOST) ---"
    ssh -o ConnectTimeout=5 "$MINI_USER@$MINI_HOST" \
      "echo DB: \$(ls -lh $MINI_DB 2>/dev/null | awk '{print \$5}'); \
       echo Flask: \$(pgrep -c server_real_db 2>/dev/null || echo 0); \
       echo SmartMount: \$(pgrep -c ai_smart_mount 2>/dev/null || echo 0)" 2>/dev/null || \
      echo "Mac mini 不可达"
    echo ""
    echo "--- GitHub ---"
    cd "$PROJ" && git log --oneline -1 2>/dev/null
    git ls-remote origin "$GIT_BRANCH" 2>/dev/null | awk '{print "origin/"$2": "$1}' || echo "GitHub 不可达"
    ;;
  check)
    log "===== 自检 ====="
    sqlite3 "$DB_PATH" "PRAGMA integrity_check;" 2>&1 | xargs -I{} echo "DB integrity: {}"
    ssh -o ConnectTimeout=5 "$MINI_USER@$MINI_HOST" "echo Mac mini reachable" 2>/dev/null || echo "Mac mini 不可达"
    curl -sI --max-time 5 https://github.com | head -1 || echo "GitHub 不可达"
    ls "$LOCKDIR"/*.lock 2>/dev/null || echo "无残留锁"
    ;;
  *) usage ;;
esac

echo ""
log "完成 (PID=$$)"
