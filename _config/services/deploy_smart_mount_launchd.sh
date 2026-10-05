#!/bin/bash
# ==============================================================
# Deploy Smart Mount Engine launchd service (v2.1.0 Trae-independent)
# 用法:
#   bash deploy_smart_mount_launchd.sh install    安装launchd服务+crontab巡检
#   bash deploy_smart_mount_launchd.sh uninstall 卸载
#   bash deploy_smart_mount_launchd.sh status     查看状态
#
# ⚠️  重要: 本脚本需要写 ~/Library/LaunchAgents/，TRAE 内置沙盒会阻止。
#         请在 独立 Terminal.app (或 iTerm2) 中执行:
#           cd /Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project
#           bash _config/services/deploy_smart_mount_launchd.sh install
#
# v2.1.0 关键变更（OneDrive TCC fix）:
#   - 架构: launchd -> 本地盘 wrapper.sh (检测engine存活)
#              -> 若DOWN: open -a Terminal .command
#              -> .command 调 daemon launcher (双fork+setsid)
#              -> engine ppid=1 完全脱离 Trae/Terminal
#   - launchd KeepAlive=false: wrapper open(1) 后立即exit 0，
#     StartInterval=60 每60s巡检一次（替代 L3 crontab 保活主链路）
#   - 额外 crontab 巡检作为 L4 兜底（如launchd服务异常）
#   - crontab 调本地盘 wrapper（不直接调 OneDrive 内 .command）
# ==============================================================
set -u

# --- TRAE 沙盒检测 ---
# TRAE 沙盒环境下写 ~/Library/LaunchAgents 会被拦
_IN_TRAE=0
if [ -n "${TRAE_ENV:-}" ] || [ -n "${TRAE_PROJECT_ID:-}" ]; then
    _IN_TRAE=1
fi
_PARENT_COMM="$(ps -o comm= -p $PPID 2>/dev/null || echo '')"
if echo "$_PARENT_COMM" | grep -qi 'trae'; then
    _IN_TRAE=1
fi
if [ "$_IN_TRAE" -eq 1 ]; then
    _PR="$(cd "$(dirname "$0")/../.." && pwd)"
    echo ""
    echo "=============================================================="
    echo "  ⚠️  TRAE 沙盒环境检测到"
    echo "=============================================================="
    echo "  TRAE 内置沙盒禁止写入 ~/Library/LaunchAgents / crontab。"
    echo "  请在 独立的 Terminal.app 中执行以下命令完成部署:"
    echo ""
    echo "  cd '$_PR'"
    echo "  bash _config/services/deploy_smart_mount_launchd.sh install"
    echo ""
    echo "  部署完成后回来运行 bash $0 status 验证。"
    echo "=============================================================="
    exit 69
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WHO="$(id -un)"
WHO_HOME="$(eval echo ~$WHO)"
LABEL="com.mtscos.smart-mount"
SRC_PLIST="$PROJECT_ROOT/_config/services/com.mtscos.smart-mount.plist"
SRC_WRAPPER="$PROJECT_ROOT/_config/services/smart_mount_starter_wrapper.sh"
DST_PLIST="$WHO_HOME/Library/LaunchAgents/com.mtscos.smart-mount.plist"
DST_WRAPPER="$WHO_HOME/Library/LaunchAgents/com.mtscos.smart-mount.starter.sh"
COMMAND_SCRIPT="$PROJECT_ROOT/start_smart_mount_daemon.command"
DAEMON_LAUNCHER="$PROJECT_ROOT/_entry_wrappers/entrypoints/start_smart_mount_engine_daemon.py"
CRON_MARKER="# MTSCOS-SMART-MOUNT-KEEPALIVE"

echo "=================================================="
echo "  MTSCOS Smart Mount Engine - launchd Deploy v2.1.0"
echo "=================================================="
echo "  PROJECT_ROOT: $PROJECT_ROOT"
echo "  User:         $WHO"
echo "  Label:        $LABEL"
echo "=================================================="

# ---- 安全检查: 目标目录是否可写 ----
can_write_la() {
    local _tf="$WHO_HOME/Library/LaunchAgents/.mtscos_write_test_$$"
    if ( touch "$_tf" 2>/dev/null && rm -f "$_tf" 2>/dev/null ); then
        return 0
    fi
    return 1
}

# ---- install ----
do_install() {
    echo "[PRE] 检查 ~/Library/LaunchAgents 是否可写..."
    if ! can_write_la; then
        echo "[FATAL] ~/Library/LaunchAgents 不可写。请在 独立Terminal.app 中执行本脚本。"
        exit 8
    fi
    echo "    OK"

    echo "[1/9] 检查源文件..."
    for f in "$SRC_PLIST" "$SRC_WRAPPER" "$COMMAND_SCRIPT" "$DAEMON_LAUNCHER"; do
        if [ ! -f "$f" ]; then
            echo "[FATAL] $f not found"
            exit 10
        fi
    done
    chmod 755 "$COMMAND_SCRIPT" 2>/dev/null || true
    chmod 755 "$DAEMON_LAUNCHER" 2>/dev/null || true
    echo "    OK: all source files exist"

    echo "[2/9] 复制 wrapper(v2.1.0) 到 LaunchAgents (本地盘)..."
    mkdir -p "$WHO_HOME/Library/LaunchAgents" 2>/dev/null || true
    # 先删旧文件避免 OneDrive ACL 污染
    rm -f "$DST_WRAPPER" 2>/dev/null || true
    cp "$SRC_WRAPPER" "$DST_WRAPPER" || { echo "[FATAL] cp wrapper FAIL"; exit 11; }
    sed -i '' "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "$DST_WRAPPER"
    WMISS=$(grep -c "__PROJECT_ROOT__" "$DST_WRAPPER" 2>/dev/null || echo 0)
    if [ "$WMISS" -gt 0 ]; then
        echo "[FATAL] wrapper still has ${WMISS} placeholders"
        exit 12
    fi
    chmod 755 "$DST_WRAPPER"
    bash -n "$DST_WRAPPER" || { echo "[FATAL] wrapper syntax BAD"; exit 13; }
    echo "    OK: wrapper deployed to $DST_WRAPPER"

    echo "[3/9] 复制 plist(v2.1.0) 到 LaunchAgents..."
    rm -f "$DST_PLIST" 2>/dev/null || true
    cp "$SRC_PLIST" "$DST_PLIST" || { echo "[FATAL] cp plist FAIL"; exit 14; }
    sed -i '' "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "$DST_PLIST"
    sed -i '' "s|__HOME__|${WHO_HOME}|g" "$DST_PLIST"
    sed -i '' "s|__HOME_LA__|${WHO_HOME}/Library/LaunchAgents|g" "$DST_PLIST"
    PMISS=$(grep -c "__" "$DST_PLIST" 2>/dev/null || echo 0)
    if [ "$PMISS" -gt 0 ]; then
        echo "[WARN] plist has ${PMISS} placeholders remaining (check)"
    fi
    chmod 644 "$DST_PLIST"
    plutil -lint "$DST_PLIST" >/dev/null 2>&1 || { echo "[FATAL] plist syntax BAD"; exit 15; }
    echo "    OK: plist deployed to $DST_PLIST"

    echo "[4/9] 卸载旧的 launchd 服务(如有)..."
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
    launchctl unload "$DST_PLIST" 2>/dev/null || true
    launchctl remove "$LABEL" 2>/dev/null || true
    sleep 1
    echo "    OK"

    echo "[5/9] 加载 launchd 服务 (RunAtLoad=true, KeepAlive=false, StartInterval=60)..."
    LAUNCH_ERR=""
    LAUNCH_ERR="$(launchctl bootstrap "gui/$UID" "$DST_PLIST" 2>&1)"
    LRC=$?
    if [ $LRC -ne 0 ]; then
        echo "    [WARN] bootstrap failed ($LRC): $LAUNCH_ERR"
        echo "    -> fallback: launchctl load"
        LAUNCH_ERR="$(launchctl load "$DST_PLIST" 2>&1)"
        LRC=$?
        [ $LRC -ne 0 ] && echo "    [WARN] load also failed: $LAUNCH_ERR (需要logout+login)"
    fi
    echo "    OK (bootstrap rc=$LRC)"

    echo "[6/9] 添加 crontab 兜底巡检 (每分钟，调本地盘 wrapper)..."
    # crontab 调 ~/Library/LaunchAgents/...starter.sh (本地盘，绕TCC)
    # 若 launchd StartInterval 工作正常，则 crontab 永远命中 engine_running 直接exit
    CRON_CMD="* * * * * /bin/bash \"$DST_WRAPPER\" >>\"$PROJECT_ROOT/_runtime/logs/smart_mount_cron.log\" 2>&1 $CRON_MARKER"
    CRON_ORG_MARKER="# MTSCOS-FILE-ORGANIZER"
    CRON_ORG_CMD="*/10 * * * * cd \"$PROJECT_ROOT\" && /usr/bin/python3 flask-app/engines/ai_file_organizer.py organize >> \"$PROJECT_ROOT/_runtime/logs/ai_file_organizer_cron.log\" 2>&1 $CRON_ORG_MARKER"
    EXISTING="$(crontab -l 2>/dev/null || true)"
    NEED_ADD=0
    if ! echo "$EXISTING" | grep -q "$CRON_MARKER"; then
        NEED_ADD=1
    fi
    if ! echo "$EXISTING" | grep -q "$CRON_ORG_MARKER"; then
        NEED_ADD=1
    fi
    if [ "$NEED_ADD" -eq 1 ]; then
        NEW_CRON="$EXISTING"
        if ! echo "$NEW_CRON" | grep -q "$CRON_MARKER"; then
            NEW_CRON="$(echo "$NEW_CRON"; echo "$CRON_MARKER"; echo "$CRON_CMD")"
        fi
        if ! echo "$NEW_CRON" | grep -q "$CRON_ORG_MARKER"; then
            NEW_CRON="$(echo "$NEW_CRON"; echo "$CRON_ORG_MARKER"; echo "$CRON_ORG_CMD")"
        fi
        if echo "$NEW_CRON" | crontab - 2>/dev/null; then
            echo "    OK: crontab entries installed"
        else
            echo "    [WARN] crontab install failed (需要 Full Disk Access 权限)"
            echo "         可选手动: crontab -e  添加以下2行:"
            echo "         $CRON_MARKER"
            echo "         $CRON_CMD"
            echo "         $CRON_ORG_MARKER"
            echo "         $CRON_ORG_CMD"
        fi
    else
        echo "    crontab 已有 keepalive + organizer entries (跳过)"
    fi

    echo "[7/9] kickstart 服务，立刻触发一次..."
    KS_ERR=""
    KS_ERR="$(launchctl kickstart -k "gui/$UID/$LABEL" 2>&1)" || \
        KS_ERR="$(launchctl start "$LABEL" 2>&1)" || true
    echo "    OK (kickstart rc=$?)"

    echo "[8/9] 验证 launchd 服务登记..."
    sleep 4
    LSTATUS="$(launchctl list "$LABEL" 2>/dev/null || true)"
    if [ -n "$LSTATUS" ]; then
        echo "    launchctl list:"
        echo "$LSTATUS" | sed 's/^/      /'
    else
        echo "    [WARN] launchd label not found (可能需要 logout+login 后生效)"
    fi

    echo "[9/9] 等待 engine 进程拉起并检查 ppid=1..."
    PID_FILE="$PROJECT_ROOT/_runtime/pids/ai_smart_mount_engine.pid"
    found=0
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        sleep 2
        if [ -f "$PID_FILE" ]; then
            PID="$(cat "$PID_FILE" 2>/dev/null || true)"
            if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
                PPID_VAL="$(ps -o ppid= -p "$PID" 2>/dev/null | tr -d ' ')"
                echo ""
                echo "    ✅ Smart Mount Engine RUNNING (pid=$PID, ppid=$PPID_VAL)"
                if [ "$PPID_VAL" = "1" ]; then
                    echo "    ✅✅ ppid=1 -> 已脱离 Trae/Terminal/launchd 进程树"
                else
                    echo "    ⚠️  ppid=$PPID_VAL 非1 (可能 engine 正在初始化二次fork，等1分钟再查)"
                fi
                found=1
                break
            fi
        fi
        printf "."
    done
    [ "$found" -eq 0 ] && echo "" && echo "    [INFO] 30s 内未检测到 PID (wrapper 可能已 open -a Terminal，Terminal 正在弹对话框)"
    echo ""
    echo "    如 engine 未启动，手动执行 1 次即可:"
    echo "      bash $COMMAND_SCRIPT start-daemon"

    echo
    echo "=================================================="
    echo "  Install Complete! v2.1.0 Trae-independent"
    echo "=================================================="
    echo "  L1 engine 内置:   主循环异常捕获不死掉+子进程心跳监控"
    echo "  L2 launchd:       $LABEL (RunAtLoad=true, StartInterval=60s巡检)"
    echo "  L3 wrapper:       $DST_WRAPPER (本地盘, open -a Terminal绕TCC)"
    echo "  L4 crontab:       每分钟兜底巡检(如 launchd 异常)"
    echo "  daemon launcher:  $DAEMON_LAUNCHER (双fork+setsid -> ppid=1)"
    echo "  daemons:          15 auto processes"
    echo "  手动启动:         bash $COMMAND_SCRIPT start-daemon"
    echo "  查看状态:         bash $0 status"
    echo "  监督日志:         tail -f $PROJECT_ROOT/_runtime/logs/smart_mount_supervisor.log"
    echo "=================================================="
}

# ---- uninstall ----
do_uninstall() {
    echo "[1/5] 停止 launchd 服务..."
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
    launchctl unload "$DST_PLIST" 2>/dev/null || true
    launchctl remove "$LABEL" 2>/dev/null || true
    echo "    OK"

    echo "[2/5] 停止 engine 进程..."
    PID_FILE="$PROJECT_ROOT/_runtime/pids/ai_smart_mount_engine.pid"
    DAEMON_PID_FILE="$PROJECT_ROOT/_runtime/pids/ai_smart_mount_engine_daemon.pid"
    for pf in "$PID_FILE" "$DAEMON_PID_FILE"; do
        if [ -f "$pf" ]; then
            PID="$(cat "$pf" 2>/dev/null || true)"
            if [ -n "${PID:-}" ]; then
                kill -TERM "$PID" 2>/dev/null || true
                sleep 2
                kill -KILL "$PID" 2>/dev/null || true
            fi
            rm -f "$pf" 2>/dev/null || true
        fi
    done
    # 清理由 pgrep 找到的残留进程
    PIDS="$(pgrep -f 'ai_smart_mount_engine.py' 2>/dev/null || true)"
    [ -n "$PIDS" ] && kill -TERM $PIDS 2>/dev/null || true
    sleep 1
    PIDS2="$(pgrep -f 'ai_smart_mount_engine.py' 2>/dev/null || true)"
    [ -n "$PIDS2" ] && kill -KILL $PIDS2 2>/dev/null || true
    echo "    OK"

    echo "[3/5] 删除 LaunchAgents 文件..."
    rm -f "$DST_PLIST" 2>/dev/null || true
    rm -f "$DST_WRAPPER" 2>/dev/null || true
    if [ -f "$DST_PLIST" ] || [ -f "$DST_WRAPPER" ]; then
        echo "    [WARN] 删除失败 (TRAE 沙盒?)，请手动删除:"
        echo "      rm -f $DST_PLIST $DST_WRAPPER"
    fi
    echo "    OK"

    echo "[4/5] 清理 crontab (keepalive + file-organizer)..."
    EXISTING="$(crontab -l 2>/dev/null || true)"
    NEW_CRON="$(echo "$EXISTING" | \
        grep -v "$CRON_MARKER" | \
        grep -v "MTSCOS-SMART-MOUNT-KEEPALIVE" | \
        grep -v "MTSCOS-FILE-ORGANIZER" 2>/dev/null || true)"
    if echo "$NEW_CRON" | crontab - 2>/dev/null; then
        echo "    OK"
    else
        echo "    [WARN] crontab 清理失败 (TRAE 沙盒?)，请手动 crontab -e 删除 MTSCOS 条目"
    fi

    echo "[5/5] 验证..."
    LSTATUS="$(launchctl list "$LABEL" 2>/dev/null || true)"
    [ -n "$LSTATUS" ] && echo "    [WARN] launchd label 仍存在: $LSTATUS" || echo "    launchd 已卸载"
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null && echo "    [WARN] 进程仍在运行 pid=$PID" || echo "    engine 进程已停止"

    echo
    echo "  Uninstall Complete!"
}

# ---- status ----
do_status() {
    echo "=== launchd (v2.1.0 Trae-independent) ==="
    LSTATUS="$(launchctl list "$LABEL" 2>/dev/null || true)"
    if [ -n "$LSTATUS" ]; then
        echo "$LSTATUS" | sed 's/^/  /'
    else
        echo "  NOT LOADED (运行 bash $0 install 或 logout+login)"
    fi
    echo
    echo "=== 进程 ==="
    PID_FILE="$PROJECT_ROOT/_runtime/pids/ai_smart_mount_engine.pid"
    DAEMON_PID_FILE="$PROJECT_ROOT/_runtime/pids/ai_smart_mount_engine_daemon.pid"
    EP_PGREP="$(pgrep -f 'ai_smart_mount_engine.py' 2>/dev/null | head -1 || true)"
    if [ -f "$DAEMON_PID_FILE" ]; then
        DP="$(cat "$DAEMON_PID_FILE" 2>/dev/null || true)"
        if [ -n "${DP:-}" ] && kill -0 "$DP" 2>/dev/null; then
            echo "  supervisor: RUNNING (pid=$DP)"
        else
            echo "  supervisor: STOPPED (stale pid=$DP)"
        fi
    else
        if [ -n "${EP_PGREP:-}" ]; then
            echo "  supervisor: (engine 直接运行, 无独立supervisor)"
        else
            echo "  supervisor: STOPPED (no PID file)"
        fi
    fi
    if [ -f "$PID_FILE" ]; then
        PID="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
            PPID_VAL="$(ps -o ppid= -p "$PID" 2>/dev/null | tr -d ' ')"
            echo "  engine:    RUNNING (pid=$PID, ppid=$PPID_VAL)"
            if [ "$PPID_VAL" = "1" ]; then
                echo "  ✅ ppid=1 已完全脱离 Trae/Terminal/launchd 进程树"
            else
                echo "  ⚠️  ppid=$PPID_VAL 仍在某进程树下（非守护模式）"
            fi
        else
            echo "  engine:    STOPPED (stale PID=$PID)"
        fi
    elif [ -n "${EP_PGREP:-}" ]; then
        PPID_VAL="$(ps -o ppid= -p "$EP_PGREP" 2>/dev/null | tr -d ' ')"
        echo "  engine:    RUNNING (pgrep pid=$EP_PGREP, ppid=$PPID_VAL)"
        [ "$PPID_VAL" = "1" ] && echo "  ✅ ppid=1" || echo "  ⚠️  ppid=$PPID_VAL"
    else
        echo "  engine:    STOPPED (no PID file + pgrep empty)"
    fi
    echo
    echo "=== crontab ==="
    crontab -l 2>/dev/null | grep -E "MTSCOS-SMART-MOUNT|MTSCOS-FILE-ORGANIZER" || echo "  (not installed)"
    echo
    echo "=== 部署文件 ==="
    [ -f "$DST_PLIST" ] && echo "  plist:   $DST_PLIST (OK)" || echo "  plist:   MISSING"
    [ -f "$DST_WRAPPER" ] && echo "  wrapper: $DST_WRAPPER (OK, $(wc -l < "$DST_WRAPPER") lines)" || echo "  wrapper: MISSING"
    [ -f "$DAEMON_LAUNCHER" ] && echo "  launcher:$DAEMON_LAUNCHER (OK)" || echo "  launcher:MISSING"
    echo
    echo "=== 最近 10 条监督日志 ==="
    SLOG="$PROJECT_ROOT/_runtime/logs/smart_mount_supervisor.log"
    if [ -f "$SLOG" ]; then
        tail -10 "$SLOG" | sed 's/^/  /'
    else
        echo "  (no supervisor log yet)"
    fi
    echo
    echo "=== launchd 最近 stdout/stderr (wrapper 输出) ==="
    LOUT="$PROJECT_ROOT/_runtime/logs/smart_mount_launchd.stdout.log"
    LERR="$PROJECT_ROOT/_runtime/logs/smart_mount_launchd.stderr.log"
    if [ -f "$LOUT" ]; then
        echo "  stdout (tail 5):"
        tail -5 "$LOUT" | sed 's/^/    /'
    else
        echo "  stdout: (no log)"
    fi
    if [ -f "$LERR" ]; then
        echo "  stderr (tail 5):"
        tail -5 "$LERR" | sed 's/^/    /'
    else
        echo "  stderr: (no log)"
    fi
}

# ---- main ----
case "${1:-status}" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
    status)    do_status ;;
    *)         echo "用法: bash $0 {install|uninstall|status}"; exit 1 ;;
esac
