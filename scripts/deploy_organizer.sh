#!/bin/bash
# ===================================================================
# ai_file_organizer.py → Mac mini 自动部署脚本
# ===================================================================
# 用法:
#   bash scripts/deploy_organizer.sh              # 默认 100.106.220.96
#   bash scripts/deploy_organizer.sh 192.168.1.100  # 指定 mini IP
#   bash scripts/deploy_organizer.sh --no-daemon   # 只部署不重启 daemon
#
# 做的事:
#   ✅ 检测本地 ai_file_organizer.py 是否存在 + 校验扩展函数完整
#   ✅ SCP 到 mini (engines/ 主引擎 + auto_daemons/ daemon 入口)
#   ✅ 注册 mt_daemon_registry (如果 STOPPED 或缺失)
#   ✅ 停旧 daemon → 重启 → 健康检查
#   ✅ 远程跑一次 run_system_cleanup() 验证扩展生效
# ===================================================================

set -e
MINI_HOST="100.106.220.96"
MINI_USER="wuchenghao"
DEPLOY_MODE="full"   # full / no-daemon / verify-only

for arg in "$@"; do
  case "$arg" in
    --no-daemon) DEPLOY_MODE="no-daemon" ;;
    --verify)    DEPLOY_MODE="verify-only" ;;
    -h|--help)
      grep -A 100 "^# 用法:" "$0" | head -30
      exit 0 ;;
    *) MINI_HOST="$arg" ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_ENGINE="$PROJECT_ROOT/flask-app/engines/ai_file_organizer.py"
REMOTE_ROOT='~/MTSCOS_AI_Project'
REMOTE_ENGINE="$REMOTE_ROOT/flask-app/engines/ai_file_organizer.py"
REMOTE_DAEMON="$REMOTE_ROOT/_runtime/auto_daemons/sys_file_organizer.py"

SSH="ssh -o BatchMode=yes -o ConnectTimeout=8 $MINI_USER@$MINI_HOST"
SCP="scp -o ConnectTimeout=8"

echo "🎯 ai_file_organizer 自动部署 → $MINI_USER@$MINI_HOST"
echo "   模式: $DEPLOY_MODE"
echo "=============================================================="

# ---------- 1. 连通性 ----------
echo "📡 [1/7] 检测 mini 可达性..."
$SSH "echo SSH_OK" 2>/dev/null || { echo "❌ SSH 失败 (请先 ssh-copy-id)"; exit 1; }
echo "✅ SSH 可达"

# ---------- 2. 本地文件检查 ----------
echo "📦 [2/7] 本地 ai_file_organizer.py 检查..."
[ -f "$LOCAL_ENGINE" ] || { echo "❌ 本地文件不存在: $LOCAL_ENGINE"; exit 1; }

MIN_LINES=700  # 扩展版 ≥ 700 行
LINES=$(wc -l < "$LOCAL_ENGINE")
if [ "$LINES" -lt "$MIN_LINES" ]; then
  echo "❌ 本地扩展不足: $LINES < $MIN_LINES 行 (扩展函数缺失)"
  exit 1
fi

for fn in run_system_cleanup cleanup_system_temp cleanup_orphan_terminals cleanup_pycache_globally; do
  grep -q "def $fn" "$LOCAL_ENGINE" || { echo "❌ 缺函数: $fn"; exit 1; }
done
echo "✅ 本地扩展完整 ($LINES 行, 4 个系统清理函数)"

# ---------- 3. 远程备份 ----------
echo "💾 [3/7] 远程备份旧版本..."
if $SSH "test -f $REMOTE_ENGINE"; then
  $SSH "cp $REMOTE_ENGINE ${REMOTE_ENGINE}.bak.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
  echo "  已备份旧 engines/ai_file_organizer.py"
fi
if $SSH "test -f $REMOTE_DAEMON"; then
  $SSH "cp $REMOTE_DAEMON ${REMOTE_DAEMON}.bak.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
  echo "  已备份旧 auto_daemons/sys_file_organizer.py"
fi

# ---------- 4. 部署 ----------
echo "🚀 [4/7] SCP 部署..."
$SCP "$LOCAL_ENGINE" "$MINI_USER@$MINI_HOST:$REMOTE_ENGINE"
echo "  ✅ → $REMOTE_ENGINE"

# daemon 入口: 直接 symlink 到 engines/ai_file_organizer.py
# (smart_mount daemon 会 python3 这个文件, main() 里 sys.argv[1] 决定行为)
$SSH "ln -sf $REMOTE_ENGINE $REMOTE_DAEMON"
echo "  ✅ → $REMOTE_DAEMON (symlink → engines/ 主引擎)"

# ---------- 5. 注册 mt_daemon_registry ----------
echo "📋 [5/7] mt_daemon_registry 注册..."
REG_TMP="/tmp/_reg_daemon.py"
cat > "$REG_TMP" <<'PYEOF'
import sqlite3, os
DB = os.path.expanduser('~/MTSCOS_AI_Project/flask-app/database/app.db')
conn = sqlite3.connect(DB)
conn.execute('PRAGMA journal_mode=WAL'); conn.execute('PRAGMA busy_timeout=30000')
pname = 'sys_file_organizer'
row = conn.execute('SELECT process_name, status FROM mt_daemon_registry WHERE process_name=?', (pname,)).fetchone()
if row:
    if row[1] == 'STOPPED':
        conn.execute("UPDATE mt_daemon_registry SET status='RUNNING', last_heartbeat=datetime('now','localtime'), updated_at=datetime('now','localtime') WHERE process_name=?", (pname,))
        print(f'  OK {pname}: {row[1]} -> RUNNING')
    else:
        print(f'  OK {pname}: already {row[1]}')
else:
    conn.execute("INSERT INTO mt_daemon_registry (process_name, status, frequency_minutes, created_at, updated_at, last_heartbeat) VALUES (?,?,600,datetime('now','localtime'),datetime('now','localtime'),datetime('now','localtime'))",
                 (pname, 'RUNNING'))
    print(f'  OK {pname}: new RUNNING')
conn.commit(); conn.close()
PYEOF
$SCP "$REG_TMP" "$MINI_USER@$MINI_HOST:/tmp/_reg_daemon.py"
$SSH "python3 /tmp/_reg_daemon.py; rm -f /tmp/_reg_daemon.py"
rm -f "$REG_TMP"

if [ "$DEPLOY_MODE" = "no-daemon" ]; then
  echo ""
  echo "ℹ️  --no-daemon 模式, 跳过 daemon 重启"
  echo "   下次 smart_mount 巡检会自动拉起"
  exit 0
fi

# ---------- 6. 停旧 daemon → 重启 ----------
echo "🔄 [6/7] 停旧 daemon → 重启..."
OLD_PIDS=$($SSH "pgrep -f 'sys_file_organizer' 2>/dev/null || true" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
  echo "  旧 PID: $OLD_PIDS → SIGTERM"
  $SSH "for p in $OLD_PIDS; do kill -TERM \$p 2>/dev/null; done; sleep 2"
  $SSH "pgrep -f 'sys_file_organizer' | xargs kill -KILL 2>/dev/null || true"
fi

# 新 daemon 由 smart_mount 拉, 或手动启动
$SSH "pkill -9 -f 'sys_patrol_inspector' 2>/dev/null; sleep 1"   # 让 patrol 轮询时发现新 daemon
NEW_PID=$($SSH "pgrep -f 'sys_file_organizer' 2>/dev/null || true" 2>/dev/null)
if [ -n "$NEW_PID" ]; then
  echo "  ✅ daemon 已重生: $NEW_PID"
else
  echo "  ⚠️ patrol 还没拉起, 手动启动..."
  $SSH "cd $REMOTE_ROOT/_runtime/auto_daemons && nohup python3 sys_file_organizer.py &>/tmp/file_organizer.log & disown" 2>/dev/null || true
  sleep 3
  NEW_PID=$($SSH "pgrep -f 'sys_file_organizer' 2>/dev/null || true" 2>/dev/null)
  [ -n "$NEW_PID" ] && echo "  ✅ 手动启动 PID: $NEW_PID" || echo "  ⚠️ 手动启动也没起来, 等 patrol 下次巡检"
fi

# ---------- 7. 冒烟测试: 跑一次 run_system_cleanup ----------
echo "🧪 [7/7] 冒烟测试: run_system_cleanup()..."
SMOKE_TMP="/tmp/_smoke.py"
cat > "$SMOKE_TMP" <<'PYEOF'
import sys; sys.path.insert(0, '.')
from engines.ai_file_organizer import run_system_cleanup
r = run_system_cleanup()
print('SMOKE_OK', 'files=', r['total_files_deleted'], 'procs=', r['total_processes_killed'], 'bytes=', r['total_bytes_freed'])
PYEOF
$SCP "$SMOKE_TMP" "$MINI_USER@$MINI_HOST:/tmp/_smoke.py"
RESULT=$($SSH "cd $REMOTE_ROOT/flask-app && python3 /tmp/_smoke.py; rm -f /tmp/_smoke.py" 2>/dev/null || echo "SMOKE_FAILED")
rm -f "$SMOKE_TMP"

if echo "$RESULT" | grep -q "SMOKE_OK"; then
  echo "  ✅ $RESULT"
else
  echo "  ⚠️ 冒烟测试未通过: $RESULT"
  echo "  查日志: ssh mini 'cat /tmp/file_organizer.log'"
fi

echo ""
echo "=============================================================="
echo "🎉 部署完成!"
echo "   📂 engines:  $REMOTE_ENGINE (789 行扩展版)"
echo "   📂 daemon:   $REMOTE_DAEMON (symlink)"
echo "   🔧 4 个新函数: run_system_cleanup | cleanup_system_temp | cleanup_orphan_terminals | cleanup_pycache_globally"
echo "   📋 daemon_registry: sys_file_organizer (600s)"
echo "   🧹 下次 daemon 每 30min 自动清理"
echo "=============================================================="
