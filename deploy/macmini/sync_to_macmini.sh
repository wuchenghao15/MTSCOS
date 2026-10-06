#!/bin/bash
# ──────────────────────────────────────────────────────────────────
#  MTSCOS AI — MacBook Pro → Mac mini 本地副本同步脚本
#  解决: Mac mini Python 不能直接执行 OneDrive 同步目录的 .py 文件 (TCC 锁)
#  方案: rsync 到 ~/MTSCOS_AI_Project 本地副本 (绕过 TCC)
#  版本: v1.0 (2026-10-06)
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-wuchenghao@192.168.31.9}"
REMOTE_LOCAL="${REMOTE_LOCAL:-/Users/wuchenghao/MTSCOS_AI_Project}"
REMOTE_ONE="${REMOTE_ONE:-/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project}"

LOCAL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EXCLUDES=(
    --exclude='.git'
    --exclude='_runtime'           # 运行时产物 (logs, pids, 生成的 daemon 脚本)
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='flask-app/database/*.db-wal'
    --exclude='flask-app/database/*.db-shm'
    --exclude='flask-app/database/local_rag_vectors.db'
    --exclude='flask-app/database/ai.db'
    --exclude='flask-app/database/auth.db'
    --exclude='flask-app/database/maintenance_mirror.db'
    --exclude='flask-app/database/mtscos.db'
    --exclude='flask-app/database/mtscos_engine.db'
    --exclude='flask-app/database/question.db'
    --exclude='flask-app/database/system.db'
    --exclude='flask-app/database/admin.db'
    --exclude='flask-app/database/DB_BAK*'
    --exclude='flask-app/database/*.db.bak'
)

GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[✓]${NC} $*"; }

echo "╔═══════════════════════════════════════════════════╗"
echo "║  MTSCOS AI · MacBook → Mac mini rsync 同步          ║"
echo "╚═══════════════════════════════════════════════════╝"
echo "  源:  $LOCAL_ROOT"
echo "  目标: $REMOTE_HOST:$REMOTE_LOCAL"
echo ""

# 1) 先确保远端本地副本目录存在
log "确保远端 $REMOTE_LOCAL 存在..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 "$REMOTE_HOST" \
  "mkdir -p '$REMOTE_LOCAL'" 2>&1 || { echo "❌ SSH 失败"; exit 1; }

# 2) rsync flask-app/ (核心代码 + database)
log "rsync flask-app/ ..."
rsync -avz --delete "${EXCLUDES[@]}" \
    "$LOCAL_ROOT/flask-app/" \
    "${REMOTE_HOST}:${REMOTE_LOCAL}/flask-app/" 2>&1 | tail -5

# 3) rsync deploy/ (launchd plist + install 脚本)
log "rsync deploy/ ..."
rsync -avz --delete "${EXCLUDES[@]}" \
    "$LOCAL_ROOT/deploy/" \
    "${REMOTE_HOST}:${REMOTE_LOCAL}/deploy/" 2>&1 | tail -3

# 4) rsync 项目根关键文件
log "rsync 根关键文件 ..."
rsync -avz --delete --exclude='*.log' \
    "$LOCAL_ROOT/.trae/" \
    "${REMOTE_HOST}:${REMOTE_LOCAL}/.trae/" 2>&1 | tail -3

# 5) 验证远端关键文件
echo ""
log "远端验证..."
ssh -o StrictHostKeyChecking=no "$REMOTE_HOST" << SSHEOF 2>&1 | tail -10
python3 -c "
import os
PROJ = '$REMOTE_LOCAL'
checks = [
    'flask-app/app/node_role.py',
    'flask-app/routes/api_blueprint_registrar.py',
    'flask-app/engines/_common/db_resolver.py',
    'flask-app/modular_start.py',
    'deploy/macmini/com.mtscos.flask.plist',
]
for f in checks:
    p = os.path.join(PROJ, f)
    exists = '✅' if os.path.exists(p) else '❌'
    print(f'  {exists} {f}')
"
echo ""
echo "Flask DB: $(ls -lh '$REMOTE_LOCAL/flask-app/database/app.db' 2>/dev/null | awk '{print $5}' || echo '❌ app.db missing!')"
SSHEOF

echo ""
echo "✅ 同步完成. Mac mini 上重启: bash $REMOTE_LOCAL/deploy/macmini/install_launchd.sh"
