#!/bin/bash
# ==============================================================
# launchd trigger wrapper (v2.0.0) - lives in ~/Library/LaunchAgents/
#
# PROBLEM (why this wrapper exists):
#   launchd as a system-level process does NOT inherit user's TCC
#   (Transparency, Consent, Control) privacy grants. Specifically,
#   the project lives on OneDrive sync storage; launchd child processes
#   (bash, python) get:
#       shell-init: getcwd: Operation not permitted
#       python3: can't open file '...OneDrive...engine.py': [Errno 1] Operation not permitted
#       /bin/bash: start_ai_eigenflux_daemon.command: Operation not permitted
#
#   Terminal.app (and Finder double-click) DO have Files & Folders ->
#   OneDrive grant, so they can read and execute anything in the
#   synced project folder.
#
# SOLUTION:
#   This tiny wrapper lives OUTSIDE OneDrive (in LaunchAgents dir,
#   where launchd can always execute bash). On RunAtLoad (user login),
#   it uses macOS `open(1)` to double-click the start_...command file,
#   which routes through Terminal.app with full OneDrive permissions.
#   KeepAlive=false because `open` returns immediately and we do NOT
#   want launchd to thrash. The actual keepalive duty is handled by
#   L3 crontab per-minute patrol (which itself uses open-fallback).
#
# Triple keepalive architecture after this wrapper:
#   L1 engine built-in : stale PID cleanup + 3-heartbeat auto reconnect
#   L2 launchd (this) : one-shot trigger at user login via open(1)
#   L3 crontab patrol  : per-minute check-keepalive; if engine DOWN
#                        re-pull via open(1) fallback.
# ==============================================================
set -u

PROJECT_ROOT="__PROJECT_ROOT__"
COMMAND_FILE="$PROJECT_ROOT/start_ai_eigenflux_daemon.command"
LOG_DIR="$PROJECT_ROOT/_runtime/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true

STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
WHO="$(id -un 2>/dev/null || whoami || echo '?')"

echo "[L2-TRIGGER v2.0.0] $STAMP whoami=$WHO"
echo "[L2-TRIGGER] PROJECT_ROOT=$PROJECT_ROOT"
echo "[L2-TRIGGER] COMMAND_FILE=$COMMAND_FILE"
echo "[L2-TRIGGER] OneDrive TCC fix: routing start via open(1) -> Terminal.app"

# ---- Check if engine is already up (avoid double-start on login) ----
PID_FILE="$PROJECT_ROOT/_runtime/pids/ai_eigenflux_network_engine.pid"
OPEN_COOLDOWN_FILE="$PROJECT_ROOT/_runtime/pids/.ai_eigenflux_launchd_open_cooldown"
reap_stale() {
    if [ -f "$PID_FILE" ]; then
        P="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "${P:-}" ] && ! kill -0 "$P" 2>/dev/null; then
            echo "[L2-TRIGGER] cleaned stale pid=$P"
            rm -f "$PID_FILE" 2>/dev/null || true
        fi

        NOW_EPOCH="$(date +%s)"
        LAST_OPEN_EPOCH="$(cat "$OPEN_COOLDOWN_FILE" 2>/dev/null || echo 0)"
        if [[ "$LAST_OPEN_EPOCH" =~ ^[0-9]+$ ]] && [ $((NOW_EPOCH - LAST_OPEN_EPOCH)) -lt 600 ]; then
            echo "[L2-TRIGGER] Terminal fallback cooldown active -> skip open"
            exit 0
        fi
    fi
}
reap_stale
if [ -f "$PID_FILE" ]; then
    EP="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${EP:-}" ] && kill -0 "$EP" 2>/dev/null; then
        echo "[L2-TRIGGER] engine already RUNNING (pid=$EP) -> skip open, exit 0"
        exit 0
    fi
fi

# ---- Trigger Finder-style double-click of the command ----
# open(1) routes through LaunchServices which chooses Terminal.app
# for .command files; Terminal has OneDrive TCC grant so python+DB
# operations on the synced volume succeed.
if [ ! -f "$COMMAND_FILE" ]; then
    echo "[L2-TRIGGER][FATAL] COMMAND_FILE missing: $COMMAND_FILE" >&2
    exit 2
fi

# Avoid recursive open-loop (belt + suspenders): sentinel env var passed to open(1)
# Note: `open` ignores env vars of caller, but just in case we also write a 1-shot sentinel
GUARD_DIR="$PROJECT_ROOT/_runtime/pids"
mkdir -p "$GUARD_DIR" 2>/dev/null || true
OPEN_ONCE="$GUARD_DIR/.launchd_open_once_$$"
touch "$OPEN_ONCE"

echo "[L2-TRIGGER] invoking: open -a Terminal $COMMAND_FILE"
printf '%s\n' "$NOW_EPOCH" > "$OPEN_COOLDOWN_FILE" 2>/dev/null || true
if open -a Terminal "$COMMAND_FILE" >/dev/null 2>&1; then
    echo "[L2-TRIGGER] open(1) dispatched OK -> Terminal will execute start with cwd auth. exit 0 (KeepAlive=false, no relaunch by launchd)"
    # Cleanup sentinel after reasonable delay (in background)
    (sleep 30; rm -f "$OPEN_ONCE" 2>/dev/null || true) &
    disown 2>/dev/null || true
    exit 0
fi

echo "[L2-TRIGGER][FATAL] open -a Terminal FAILED" >&2
echo "[$STAMP] launchd open-trigger FAILED" >>"$LOG_DIR/ai_eigenflux_keepalive_patch.log" 2>/dev/null || true
exit 1
