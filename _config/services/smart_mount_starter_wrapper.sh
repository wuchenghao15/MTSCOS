#!/bin/bash
# ==============================================================
# launchd trigger wrapper (v2.1.0) - lives in ~/Library/LaunchAgents/
#
# PROBLEM (OneDrive TCC sandbox):
#   launchd as a system-level process does NOT inherit user's TCC
#   (Transparency, Consent, Control) privacy grants. The project lives
#   on OneDrive sync storage. Tests confirm BOTH:
#     - bash exec OneDrive内 .command  -> Operation not permitted
#     - python3 open(OneDrive内 .py)   -> Operation not permitted [Errno 1]
#   So neither bash-exec nor python-file-open works from launchd child.
#
#   Terminal.app (and Finder double-click) DO have Files & Folders ->
#   OneDrive grant, so they can read and execute anything in the
#   synced project folder.
#
# SOLUTION (v2.1.0 - Trae-independent):
#   This wrapper lives OUTSIDE OneDrive (in LaunchAgents dir, where
#   launchd can always execute bash). On RunAtLoad (user login) it:
#     1. PATH injection + python resolution
#     2. reap stale PID
#     3. if engine already running, exit 0 (no relaunch)
#     4. else open(1) -> Terminal.app -> .command -> daemon launcher
#        (daemon launcher 双fork + setsid -> engine ppid=1)
#
#   After daemon launcher fork, engine ppid=1 means Terminal.app
#   can be closed, Trae can be quit, even this wrapper's parent
#   bash can exit, engine still runs.
#
# Triple keepalive architecture after v2.1.0:
#   L1 engine built-in: 主循环异常捕获不死掉 + 子进程心跳 + 自动重启
#   L2 launchd (this) : RunAtLoad=true，登录时触发 open(1) 一次
#   L3 crontab patrol : 每分钟 check-keepalive，进程死亡自动恢复
# ==============================================================
set -u

PROJECT_ROOT="__PROJECT_ROOT__"
COMMAND_SCRIPT="$PROJECT_ROOT/start_smart_mount_daemon.command"
RUNTIME_DIR="$PROJECT_ROOT/_runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
PID_FILE="$PID_DIR/ai_smart_mount_engine.pid"
DAEMON_PID_FILE="$PID_DIR/ai_smart_mount_engine_daemon.pid"
SUPERVISOR_LOG="$LOG_DIR/smart_mount_supervisor.log"

mkdir -p "$LOG_DIR" "$PID_DIR" 2>/dev/null || true

STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
WHO="$(id -un 2>/dev/null || whoami || echo '?')"

echo "[L2-WRAPPER v2.1.0] $STAMP whoami=$WHO"
echo "[L2-WRAPPER] PROJECT_ROOT=$PROJECT_ROOT"
echo "[L2-WRAPPER] COMMAND_SCRIPT=$COMMAND_SCRIPT"
echo "[L2-WRAPPER] Trae-independent: open(1) -> Terminal.app -> .command -> daemon launcher (双fork)"

# ---- 1. PATH injection (in case Terminal.app inherits restrictive env) ----
_prepend_path() { case ":$PATH:" in *":$1:"*) :;; *) PATH="$1:$PATH";; esac; }
for _p in \
    "$HOME/.pyenv/shims" "$HOME/.pyenv/bin" \
    "$HOME/miniconda3/condabin" "$HOME/miniconda3/bin" \
    "$HOME/miniforge3/condabin" "$HOME/miniforge3/bin" \
    "$HOME/anaconda3/condabin" "$HOME/anaconda3/bin" \
    /opt/homebrew/bin /opt/homebrew/sbin \
    /usr/local/bin /usr/local/sbin; do
    [ -d "$_p" ] && _prepend_path "$_p"
done
export PATH
unset _prepend_path _p

# ---- 2. Check if engine already up (avoid double-start) ----
# 先用 pgrep 检测进程 (不依赖 OneDrive PID 文件, 不受 TCC 限制)
EP_PGREP="$(pgrep -f 'ai_smart_mount_engine.py' 2>/dev/null | head -1)"
if [ -n "${EP_PGREP:-}" ]; then
    echo "[L2-WRAPPER] engine already RUNNING (pgrep pid=$EP_PGREP) -> skip, exit 0"
    exit 0
fi
# 回退: 尝试读取 PID 文件 (OneDrive 内, 可能因 TCC 失败)
if [ -f "$PID_FILE" ]; then
    EP="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${EP:-}" ] && kill -0 "$EP" 2>/dev/null; then
        echo "[L2-WRAPPER] engine already RUNNING (pidfile pid=$EP) -> skip, exit 0"
        exit 0
    fi
    echo "[L2-WRAPPER] cleaned stale engine pid=$EP"
    rm -f "$PID_FILE" 2>/dev/null || true
fi
# Clean stale supervisor PID too
if [ -f "$DAEMON_PID_FILE" ]; then
    DP="$(cat "$DAEMON_PID_FILE" 2>/dev/null || true)"
    if [ -n "${DP:-}" ] && ! kill -0 "$DP" 2>/dev/null; then
        echo "[L2-WRAPPER] cleaned stale supervisor pid=$DP"
        rm -f "$DAEMON_PID_FILE" 2>/dev/null || true
    fi
fi

# ---- 3. Verify command file exists ----
if [ ! -f "$COMMAND_SCRIPT" ]; then
    echo "[L2-WRAPPER][FATAL] COMMAND_SCRIPT missing: $COMMAND_SCRIPT" >&2
    echo "[$STAMP] L2 command file missing" >>"$SUPERVISOR_LOG" 2>/dev/null || true
    exit 2
fi

# ---- 4. Trigger Finder-style double-click via open(1) ----
# open(1) routes through LaunchServices which chooses Terminal.app for
# .command files; Terminal has OneDrive TCC grant so python+DB
# operations on the synced volume succeed. The .command internally
# invokes daemon launcher which 双fork + setsid -> engine ppid=1,
# so Terminal.app can be closed without affecting engine.
echo "[L2-WRAPPER] invoking: open -a Terminal $COMMAND_SCRIPT"
if open -a Terminal "$COMMAND_SCRIPT" >/dev/null 2>&1; then
    echo "[L2-WRAPPER] open(1) dispatched OK -> Terminal will run .command, exit 0"
    exit 0
fi

# Fallback: try generic open (no -a Terminal)
echo "[L2-WRAPPER] open -a Terminal FAILED -> fallback generic open"
if open "$COMMAND_SCRIPT" >/dev/null 2>&1; then
    echo "[L2-WRAPPER] generic open(1) OK. exit 0"
    exit 0
fi

echo "[L2-WRAPPER][FATAL] both open(1) strategies FAILED. exit 1" >&2
echo "[$STAMP] launchd open-trigger FAILED (both -a Terminal + generic)" >>"$SUPERVISOR_LOG" 2>/dev/null || true
exit 1
