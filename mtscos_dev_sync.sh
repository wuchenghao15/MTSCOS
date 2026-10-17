#!/bin/bash
# ──────────────────────────────────────────────────────────────
# mtscos_dev_sync.sh — 开发机: OneDrive 编辑 → 服务器运行
# =============================================================
# v23.0.0 资源架构 (flow_resource_arch_20261017):
#   - Flask 只在服务器运行 (NODE_ROLE=SERVER), 开发机全线下线
#   - 开发机: 编辑 OneDrive 源码 + Ollama 本地推理 (算力共同承担)
#   - 服务器: Flask 服务唯一运行点 + 单独运行兜底
#   - 本机 PROD 仅作 rsync 备份节点 (DB 保留)
#
# 用法:
#   ./mtscos_dev_sync.sh              # 同步 + 服务器 pull/重启 + 双端健康检查
#   ./mtscos_dev_sync.sh --no-restart # 只同步 (本机PROD备份), 不动服务器
# ──────────────────────────────────────────────────────────────
set -e

ONEDRIVE_APP="/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app"
PROD_APP="/Users/wuchenghao/MTSCOS_PROD/flask-app"
SERVER_HOST="hulk-macmini"
SERVER_APP="~/MTSCOS_AI_Project/flask-app"
LOG="/tmp/mtscos_sync.log"

echo "==========================================" | tee -a $LOG
echo "[SYNC] $(date '+%Y-%m-%d %H:%M:%S')" | tee -a $LOG
echo "==========================================" | tee -a $LOG

# 1) rsync: OneDrive → PROD
echo "[SYNC] rsync OneDrive → PROD ..." | tee -a $LOG
rsync -avz --delete --timeout=5 --ignore-errors \
  --exclude='database/' --exclude='data/snapshots/' --exclude='data/databases/' \
  --exclude='venv/' --exclude='.venv*/' \
  --exclude='__pycache__/' --exclude='.git_disabled/' --exclude='.github/' --exclude='.git/' \
  --exclude='_archive/' --exclude='_deploy_backup_*/' --exclude='_git_shadow_backups/' --exclude='_runtime/' \
  --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude='*.log' --exclude='*.tar.gz' --exclude='*.zip' \
  "$ONEDRIVE_APP/" "$PROD_APP/" 2>&1 | tee -a $LOG | tail -3
echo "[SYNC] ✅ 同步完成" | tee -a $LOG

# 2) 本机 Flask 彻底下线 (资源架构: Flask 只在服务器运行, 含 launchd 拉回防护)
echo "[SYNC] 本机 Flask 下线检查 ..." | tee -a $LOG
for i in 1 2 3; do
  pkill -9 -f "modular_start.py" 2>/dev/null || true
  pkill -9 -f "python3.*8888" 2>/dev/null || true
  sleep 1
  if ! lsof -i :8888 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    echo "[SYNC] ✅ 本机 8888 无监听 — Flask 已全线下线" | tee -a $LOG
    break
  fi
  echo "  等待本机端口释放 $i..."
done

if [ "$1" == "--no-restart" ]; then
  echo "[SYNC] --no-restart: 只完成本机 PROD 备份同步, 服务器不动" | tee -a $LOG
  exit 0
fi

# 3) 服务器: git pull → 重启 Flask (NODE_ROLE=SERVER)
SERVER_IP=$(ssh -G $SERVER_HOST 2>/dev/null | awk '/^hostname /{print $2}')
echo "[SYNC] 服务器 $SERVER_HOST($SERVER_IP): pull + 重启 ..." | tee -a $LOG
ssh -o ConnectTimeout=15 -o BatchMode=yes $SERVER_HOST "
  cd ~/MTSCOS_AI_Project && git pull origin main 2>&1 | tail -2
  pkill -9 -f modular_start.py 2>/dev/null || true; sleep 1
  cd $SERVER_APP
  export NODE_ROLE=SERVER VIKEY_BACKEND=sim
  nohup /usr/bin/python3 -u modular_start.py >> /tmp/flask_launchd.log 2>&1 &
  disown
" && echo "[SYNC] ✅ 服务器重启指令已下发" | tee -a $LOG

# 4) 双端健康检查 (经 Tailscale 从开发机探测 — 真实跨机链路)
echo "[SYNC] 健康检查 (等待服务器 Flask 启动)..." | tee -a $LOG
OK=0
CODE="000"
for i in $(seq 1 15); do
  sleep 3
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://$SERVER_IP:8888/ 2>/dev/null)
  if [ "$CODE" == "200" ]; then
    echo "[SYNC] ✅ 服务器 Flask 就绪 (attempt $i, GET / → $CODE)" | tee -a $LOG
    OK=1
    break
  fi
done

if [ $OK -eq 0 ]; then
  echo "[SYNC] ❌ 服务器 Flask 启动超时 — 排查: ssh $SERVER_HOST 'tail -30 /tmp/flask_launchd.log'" | tee -a $LOG
  exit 1
fi

GUARD=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://$SERVER_IP:8888/api/admin/ 2>/dev/null)
echo "[SYNC] 健康报告:" | tee -a $LOG
echo "  GET /            → $CODE (期望 200)" | tee -a $LOG
echo "  GET /api/admin/  → $GUARD (期望 403 — fail-closed 密级拦截器)" | tee -a $LOG
echo "  服务器 git       → $(ssh -o ConnectTimeout=10 -o BatchMode=yes $SERVER_HOST 'cd ~/MTSCOS_AI_Project && git log --oneline -1')" | tee -a $LOG

echo "" | tee -a $LOG
echo "[SYNC] ✅ 完成 — Flask 仅运行于服务器 (资源架构 v23.0.0)" | tee -a $LOG
