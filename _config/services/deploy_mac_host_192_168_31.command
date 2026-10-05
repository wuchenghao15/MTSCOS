#!/bin/bash
# ==============================================================
# deploy_mac_host_192_168_31.command  —  MTSCOS AI MAC主机一键部署
# Target Host: 192.168.31.186 (本机en0);  User Specified Alias: 192.168.31.242
# OneDrive TCC 绕过: 用 open -a Terminal 此 .command 而非直接双击Finder(双击也生效)
# 功能：
#   0) 配置chmod+x所有部署相关.command / .sh
#   1) 执行 deploy_mac_autoloader.py all (reap+params+whitelist+15daemon registry+bind-ip提示+deploy-record)
#   2) 启动 Flask HTTP server (server_real_db.py port 8888 ::) — 由 launchd plist守护；此处做一次冷启动探针
#   3) 启动 smart_mount_engine (start_smart_mount_daemon.command start-daemon)
#   4) 启动 eigenflux_network (start_ai_eigenflux_daemon.command start-daemon)
#   5) 加载 deploy_mac_autoloader.py --mode=daemon 后调用 ai_auto_hire_engine 与 ai_eigenflux_network
#   6) 输出访问 URL: http://<本机IP>:8888/  与  http://192.168.31.242:8888/ (若alias已绑)
# ==============================================================
set -u
set -o pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

RUNTIME_DIR="$PROJECT_ROOT/_runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

DEPLOY_LOG="$LOG_DIR/deploy_mac_host_192_168_31_$$.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [deploy.command START] pwd=$PROJECT_ROOT" | tee -a "$DEPLOY_LOG"

# ---- 1. 找 Python ----
PROJECT_ROOT_BASH="$PROJECT_ROOT"
is_real_python() {
    local p="$1"; [ -z "${p:-}" ] && return 1; [ -d "$p" ] && return 1; [ -x "$p" ] || return 1
    local sz; sz="$(stat -f '%z' "$p" 2>/dev/null || echo 0)"; [ "$sz" -lt 80 ] && return 1
    if [ "$sz" -lt 2048 ]; then
        local first2; first2="$(head -c 2 "$p" 2>/dev/null || true)"; [ "$first2" != "#!" ] && return 1
    fi
    "$p" --version >/dev/null 2>&1 || return 1; return 0
}
PY_BIN=""
for p in \
    "$PROJECT_ROOT_BASH/_runtime/.venv/bin/python3" "$PROJECT_ROOT_BASH/.venv/bin/python3" \
    "$HOME/.pyenv/shims/python3" "$HOME/miniconda3/bin/python3" "$HOME/miniforge3/bin/python3" \
    "$HOME/anaconda3/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    /Library/Developer/CommandLineTools/usr/bin/python3 /usr/bin/python3 python3; do
    if command -v "$p" >/dev/null 2>&1; then PYX="$(command -v "$p" 2>/dev/null || echo "$p")"
    elif [ -x "$p" ]; then PYX="$p"; else continue; fi
    if is_real_python "$PYX"; then PY_BIN="$PYX"; break; fi
done
if [ -z "${PY_BIN:-}" ]; then echo "[FATAL] cannot find python3 interpreter" | tee -a "$DEPLOY_LOG"; exit 3; fi
echo "[PY] $PY_BIN → $($PY_BIN --version 2>&1 | head -1)" | tee -a "$DEPLOY_LOG"

# ---- 2. 权限chmod ----
chmod +x start_smart_mount_daemon.command start_ai_eigenflux_daemon.command 2>/dev/null || true
chmod +x "$PROJECT_ROOT_BASH/_entry_wrappers/entrypoints"/*.py 2>/dev/null || true
chmod +x "$PROJECT_ROOT_BASH/flask-app/engines/deploy_mac_autoloader.py" 2>/dev/null || true
chmod +x ~/Library/LaunchAgents/*.sh 2>/dev/null || true
chmod 644 ~/Library/LaunchAgents/*.plist 2>/dev/null || true

# ---- 3. 本机所有IP探测 ----
LOCAL_IPS="$(ifconfig | grep 'inet ' | awk '{print $2}' | tr '\n' ' ')"
echo "[HOST] 本机IPs: $LOCAL_IPS" | tee -a "$DEPLOY_LOG"
TARGET_IP_USER="192.168.31.242"
echo "[HOST] 用户指定IP(alias目标): $TARGET_IP_USER" | tee -a "$DEPLOY_LOG"
SERVER_PORT="${MTSCOS_SERVER_PORT:-8888}"
BIND_HOST="${MTSCOS_BIND_HOST:-::}"

# ---- 4. 运行部署加载器 (参数/daemon/白名单/bind-ip/deploy-record) ----
echo "=== [STEP 1/5] deploy_mac_autoloader.py all ===" | tee -a "$DEPLOY_LOG"
"$PY_BIN" "$PROJECT_ROOT_BASH/flask-app/engines/deploy_mac_autoloader.py" all --host-ip "$TARGET_IP_USER" 2>&1 | tee -a "$DEPLOY_LOG"
STEP1_RC=${PIPESTATUS[0]}
echo "[STEP1 RC=$STEP1_RC]" | tee -a "$DEPLOY_LOG"

# ---- 5. 启动 smart_mount_engine daemon (管理15个AI后台) ----
echo "=== [STEP 2/5] 启动 Smart Mount Engine ===" | tee -a "$DEPLOY_LOG"
if [ -x ./start_smart_mount_daemon.command ]; then
    bash ./start_smart_mount_daemon.command stop 2>&1 | tee -a "$DEPLOY_LOG" || true
    sleep 2
    bash ./start_smart_mount_daemon.command start-daemon 2>&1 | tee -a "$DEPLOY_LOG"
    STEP2_RC=$?
else
    echo "[WARN] start_smart_mount_daemon.command 缺失或不可执行，尝试用python直接跑ai_smart_mount_engine.py" | tee -a "$DEPLOY_LOG"
    nohup "$PY_BIN" "$PROJECT_ROOT_BASH/flask-app/engines/ai_smart_mount_engine.py" > "$LOG_DIR/smart_mount_engine_fallback.log" 2>&1 &
    echo $! > "$PID_DIR/ai_smart_mount_engine_fallback.pid"
    STEP2_RC=0
fi
echo "[STEP2 RC=$STEP2_RC]" | tee -a "$DEPLOY_LOG"
sleep 2

# ---- 6. 启动 ai_eigenflux daemon ----
echo "=== [STEP 3/5] 启动 EigenFlux Network Daemon ===" | tee -a "$DEPLOY_LOG"
if [ -x ./start_ai_eigenflux_daemon.command ]; then
    bash ./start_ai_eigenflux_daemon.command stop 2>&1 | tee -a "$DEPLOY_LOG" || true
    sleep 2
    bash ./start_ai_eigenflux_daemon.command start-daemon 2>&1 | tee -a "$DEPLOY_LOG"
    STEP3_RC=$?
else
    echo "[WARN] start_ai_eigenflux_daemon.command 不可执行，fallback直接跑ai_eigenflux_network_engine.py" | tee -a "$DEPLOY_LOG"
    nohup "$PY_BIN" "$PROJECT_ROOT_BASH/flask-app/engines/ai_eigenflux_network_engine.py" > "$LOG_DIR/eigenflux_network_fallback.log" 2>&1 &
    echo $! > "$PID_DIR/ai_eigenflux_network_fallback.pid"
    STEP3_RC=0
fi
echo "[STEP3 RC=$STEP3_RC]" | tee -a "$DEPLOY_LOG"

# ---- 7. 启动 Flask HTTP server (server_real_db.py) 后台nohup ----
echo "=== [STEP 4/5] Flask HTTP server server_real_db.py bind=$BIND_HOST port=$SERVER_PORT ===" | tee -a "$DEPLOY_LOG"
SRV_PY="$PROJECT_ROOT_BASH/flask-app/server_real_db.py"
if [ ! -f "$SRV_PY" ]; then
    echo "[FATAL] server_real_db.py NOT FOUND: $SRV_PY" | tee -a "$DEPLOY_LOG"; exit 4
fi
# 杀掉已存在的8888 (排除ControlCenter=5000)
OLD_PIDS=""
OLD_PIDS="$(lsof -nP -iTCP:$SERVER_PORT -sTCP:LISTEN -t 2>/dev/null || true)"
if [ -n "$OLD_PIDS" ]; then
    for op in $OLD_PIDS; do
        if [ "$(ps -o comm= -p "$op" 2>/dev/null || true)" != "ControlCenter" ]; then
            echo "[WARN] 杀死旧进程pid=$op 占用:$SERVER_PORT" | tee -a "$DEPLOY_LOG"
            kill "$op" 2>/dev/null; sleep 1; kill -9 "$op" 2>/dev/null || true
        fi
    done
fi
export MTSCOS_SKIP_EF_STARTUP_SCAN="${MTSCOS_SKIP_EF_STARTUP_SCAN:-1}"   # 启动时跳过EF静态20类健康扫描（防止60s阻塞HTTP），稍后线程自动执行
nohup "$PY_BIN" "$SRV_PY" > "$LOG_DIR/flask_server_8888.log" 2>&1 &
FLASK_PID=$!
echo "$FLASK_PID" > "$PID_DIR/flask_server_${SERVER_PORT}.pid"
echo "[FLASK] server_real_db.py 已启动 PID=$FLASK_PID  日志=$LOG_DIR/flask_server_8888.log" | tee -a "$DEPLOY_LOG"
sleep 6
# HTTP探针
HTTP_OK=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if kill -0 "$FLASK_PID" 2>/dev/null; then true; else echo "[FLASK] 进程PID=$FLASK_PID 已退出，检查日志:"; tail -n 40 "$LOG_DIR/flask_server_8888.log"; break; fi
    for url in "http://127.0.0.1:$SERVER_PORT/api/security/status" "http://192.168.31.186:$SERVER_PORT/api/security/status"; do
        CODE="$(curl -sS --connect-timeout 3 --max-time 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
        echo "[HTTP $i] $url → $CODE" | tee -a "$DEPLOY_LOG"
        if [ "$CODE" = "200" ] || [ "$CODE" = "302" ] || [ "$CODE" = "401" ] || [ "$CODE" = "403" ]; then HTTP_OK=1; break 2; fi
    done
    sleep 2
done
STEP4_RC=0; [ $HTTP_OK -ne 1 ] && STEP4_RC=50
echo "[STEP4 RC=$STEP4_RC HTTP_OK=$HTTP_OK]" | tee -a "$DEPLOY_LOG"

# ---- 8. AI员工加载: ai_auto_hire / eigenflux_network ----
echo "=== [STEP 5/5] AI员工全量 + EigenFlux专家自动雇佣/互邀 ===" | tee -a "$DEPLOY_LOG"
(
  # 双引擎分别 run_once，避免阻塞nohup主终端
  cd "$PROJECT_ROOT_BASH/flask-app/engines"
  echo "[Hire] ai_auto_hire_engine.py ensure-and-hire-batch (2轮)" | tee -a "$DEPLOY_LOG"
  "$PY_BIN" -c "
import sys,os; sys.path.insert(0, os.getcwd())
try:
    import ai_auto_hire_engine as h
    for round_n in (1,2):
        try:
            r = h.run_once(max_new=500, verbose=True) if hasattr(h,'run_once') else (print('module_has_no_run_once, doing import-only warmup'),'ok')
            print('[AI HIRE round=%s] %s'%(round_n,r))
        except Exception as e:
            import traceback; print('HIRE round=%s EXC=%s\n%s'%(round_n, e, traceback.format_exc()))
except Exception as e:
    import traceback; print('HIRE import EXC=%s\n%s'%(e, traceback.format_exc()))
sys.exit(0)
" 2>&1 | tee -a "$DEPLOY_LOG"
  echo "[EF] ai_eigenflux_network_engine.py connect-friends rounds" | tee -a "$DEPLOY_LOG"
  "$PY_BIN" -c "
import sys,os; sys.path.insert(0, os.getcwd())
try:
    import ai_eigenflux_network_engine as n
    for round_n in (1,2):
        try:
            r = n.run_once(max_new=500, verbose=True) if hasattr(n,'run_once') else (print('module_has_no_run_once, import-only warmup'),'ok')
            print('[EF NET round=%s] %s'%(round_n,r))
        except Exception as e:
            import traceback; print('EF NET round=%s EXC=%s\n%s'%(round_n,e, traceback.format_exc()))
except Exception as e:
    import traceback; print('EF NET import EXC=%s\n%s'%(e, traceback.format_exc()))
sys.exit(0)
" 2>&1 | tee -a "$DEPLOY_LOG"
)
STEP5_RC=$?

# ---- 9. 访问 URL 汇总 ----
echo "" | tee -a "$DEPLOY_LOG"
echo "========================================================" | tee -a "$DEPLOY_LOG"
echo " 🟢  MTSCOS AI MAC主机部署完成   🟢"                | tee -a "$DEPLOY_LOG"
echo "========================================================" | tee -a "$DEPLOY_LOG"
echo " 本机 HTTP (Loopback)        → http://127.0.0.1:$SERVER_PORT/" | tee -a "$DEPLOY_LOG"
echo " 本机 HTTP (LAN=en0)         → http://192.168.31.186:$SERVER_PORT/" | tee -a "$DEPLOY_LOG"
if ifconfig en0 2>/dev/null | grep -q "inet $TARGET_IP_USER "; then
  echo " 用户请求 alias IP         → http://$TARGET_IP_USER:$SERVER_PORT/   🟢已绑定" | tee -a "$DEPLOY_LOG"
else
  echo " 用户请求 alias IP         → http://$TARGET_IP_USER:$SERVER_PORT/   ⚠️ 需手动绑定:  sudo ifconfig en0 alias $TARGET_IP_USER 255.255.255.0" | tee -a "$DEPLOY_LOG"
fi
echo " 杨安AI安全仪表盘            → http://192.168.31.186:$SERVER_PORT/api/security/dashboard (需admin登录)" | tee -a "$DEPLOY_LOG"
echo " 安全探针                   → http://192.168.31.186:$SERVER_PORT/api/security/status" | tee -a "$DEPLOY_LOG"
echo " Smart Mount Engine PID文件  → $PID_DIR/ai_smart_mount_engine_daemon.pid" | tee -a "$DEPLOY_LOG"
echo " EigenFlux Network PID文件   → $PID_DIR/ai_eigenflux_network.pid" | tee -a "$DEPLOY_LOG"
echo " Flask 进程 PID              → $FLASK_PID" | tee -a "$DEPLOY_LOG"
echo " 详细部署日志                → $DEPLOY_LOG" | tee -a "$DEPLOY_LOG"
echo "========================================================" | tee -a "$DEPLOY_LOG"
echo ""
exit 0
