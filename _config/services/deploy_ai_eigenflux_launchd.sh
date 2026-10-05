#!/bin/bash
# ==============================================================
# launchd plist + crontab dual-safe deploy tool v1.2.2 (macOS auto-start)
#   bash _config/services/deploy_ai_eigenflux_launchd.sh [install|uninstall|status]
#
# Triple anti-crash protection:
#   L1: engine built-in
#       - stale PID auto-clean / 3-heartbeat-timeout BROKEN + reconnect_count + auto-reconnect
#   L2: launchd (primary keepalive)
#       - RunAtLoad login-start + KeepAlive=true crash/exit auto-restart
#       - ThrottleInterval 10s anti-loop + foreground exec signal passthrough
#   L3: user-level crontab (fallback keepalive, every 1 min patrol)
#       - prevent "launchd reset to unloaded / admin manually unloaded without reload"
#       - check-keepalive rule: if launchd is managing = do nothing, else only restart if engine is down
# ==============================================================
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC_PLIST="$PROJECT_ROOT/_config/services/com.mtscos.ai-eigenflux.plist"
SRC_WRAPPER="$PROJECT_ROOT/_config/services/ai_eigenflux_starter_wrapper.sh"
DST_PLIST="$HOME/Library/LaunchAgents/com.mtscos.ai-eigenflux.plist"
DST_WRAPPER="$HOME/Library/LaunchAgents/com.mtscos.ai-eigenflux.starter.sh"
LABEL="com.mtscos.ai-eigenflux"
COMMAND="$PROJECT_ROOT/start_ai_eigenflux_daemon.command"
HOME_ABS="$HOME"
HOME_LA_ABS="$HOME/Library/LaunchAgents"
# crontab unique marker (avoid collision / duplicate)
CRON_MARK="#MTSCOS_AI_EIGENFLUX_KEEPALIVE_v1_2_0"
CRON_LINE="* * * * * \"$COMMAND\" check-keepalive >> \"$PROJECT_ROOT/_runtime/logs/ai_eigenflux_cron_check.log\" 2>&1 $CRON_MARK"
# macOS 13+ recommends bootstrap (LaunchAgents domain = gui/$UID)
LAUNCH_DOMAIN="gui/$(id -u)"

CMD="${1:-status}"

mkdir -p "$HOME/Library/LaunchAgents"
chmod 700 "$HOME/Library/LaunchAgents" 2>/dev/null || true

# ---- cron tools (idempotent) ----
cron_read() {
    crontab -l 2>/dev/null || true
}
cron_has_line() {
    cron_read | grep -Fq "$CRON_MARK"
}
cron_append_line() {
    if cron_has_line; then
        echo "        crontab: already installed (dedup skipped add)"
        return 0
    fi
    local tmp
    tmp="$(mktemp)"
    { cron_read; echo "$CRON_LINE"; } > "$tmp"
    crontab "$tmp" || { echo "[FATAL] crontab write FAILED"; rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    echo "        crontab: installed 1-min patrol -> $PROJECT_ROOT/_runtime/logs/ai_eigenflux_cron_check.log"
}
cron_remove_line() {
    if ! cron_has_line; then
        echo "        crontab: no marker found (already cleaned)"
        return 0
    fi
    local tmp
    tmp="$(mktemp)"
    cron_read | grep -Fv "$CRON_MARK" > "$tmp"
    crontab "$tmp" || { echo "[WARN ] crontab cleanup FAILED (may need manual: crontab -e remove $CRON_MARK line)"; rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    echo "        crontab: marker removed"
}

# ---- launchctl backward-compatible wrapper ----
launchd_is_loaded() {
    launchctl list 2>/dev/null | grep -q "$LABEL"
}
launchd_do_unload() {
    launchctl bootout "$LAUNCH_DOMAIN/$LABEL" 2>/dev/null || true
    launchctl remove "$LABEL" 2>/dev/null || true
    launchctl unload "$DST_PLIST" 2>/dev/null || true
}
launchd_do_load() {
    if launchctl bootstrap "$LAUNCH_DOMAIN" "$DST_PLIST" 2>/dev/null; then
        return 0
    fi
    launchctl load "$DST_PLIST"
}

check_prerequisites() {
    local ok=0
    if [ ! -f "$SRC_PLIST" ]; then
        echo "[FATAL] $SRC_PLIST not found" >&2; ok=1
    fi
    if [ ! -f "$COMMAND" ]; then
        echo "[FATAL] $COMMAND not found" >&2; ok=1
    fi
    if [ ! -d "$PROJECT_ROOT/_runtime" ]; then
        echo "[WARN ] _runtime dir does not exist, will be created on first deploy"
    fi
    if [ "$(uname -s)" != "Darwin" ]; then
        echo "[FATAL] this script is for macOS only" >&2; ok=1
    fi
    if ! command -v crontab >/dev/null 2>&1; then
        echo "[FATAL] crontab not found (require standard macOS user shell)" >&2; ok=1
    fi
    [ "$ok" -ne 0 ] && exit 10
}

do_status() {
    echo "== deploy status for $LABEL (v1.2.2 Triple-Redundancy) =="
    echo
    echo "--- L2 launchd registry ---"
    if launchd_is_loaded; then
        launchctl list 2>/dev/null | grep "$LABEL" | awk '{printf "  PID   = %s\n  LastExit= %s\n  Label   = %s\n",$1,$2,$3}'
    else
        echo "  (not registered in launchd user-level LaunchAgents)"
    fi
    echo
    echo "--- installed plist ---"
    if [ -f "$DST_PLIST" ]; then
        local user
        user="$(stat -f '%Su:%Sg %Sp' "$DST_PLIST")"
        echo "  path : $DST_PLIST"
        echo "  perm : $user (must be 644 and owner=current user)"
        local miss
        miss=$(grep -cE "__PROJECT_ROOT__|__HOME_LA__|__HOME__" "$DST_PLIST" 2>/dev/null || true)
        if [ "$miss" -gt 0 ]; then
            echo "  !! WARN: ${miss} unreplaced placeholders remain, plist is INVALID!"
        else
            echo "  OK   : all placeholders replaced"
        fi
        echo "  syntax:  $(plutil -lint "$DST_PLIST" 2>&1 | head -1)"
    else
        echo "  (not deployed to $DST_PLIST yet)"
    fi
    echo
    echo "--- starter wrapper (OneDrive TCC sandbox fix) ---"
    if [ -f "$DST_WRAPPER" ]; then
        local wu wp
        wu="$(stat -f '%Su:%Sg %Sp' "$DST_WRAPPER" 2>/dev/null || echo "?")"
        echo "  path   : $DST_WRAPPER"
        echo "  perm   : $wu (should be 755)"
        local wmiss
        wmiss=$(grep -c "__PROJECT_ROOT__" "$DST_WRAPPER" 2>/dev/null || true)
        if [ "$wmiss" -gt 0 ]; then
            echo "  !! WARN: wrapper has ${wmiss} unreplaced __PROJECT_ROOT__ placeholders!"
        else
            echo "  OK     : placeholder replaced"
        fi
        bash -n "$DST_WRAPPER" 2>/dev/null && echo "  syntax : OK" || echo "  syntax : BROKEN"
    else
        echo "  (wrapper NOT installed -> launchd LastExit=126/127 expected)"
    fi
    echo
    echo "--- L3 crontab patrol ---"
    if cron_has_line; then
        echo "  INSTALLED: $(cron_read | grep -F "$CRON_MARK")"
    else
        echo "  (1-min patrol NOT installed; no L3 fallback when L2 launchd fails)"
    fi
    echo
    echo "--- L1 engine process ---"
    "$COMMAND" status 2>&1 | sed 's/^/  /' || true
    echo
    echo "--- dedicated logs ---"
    for f in \
        "$PROJECT_ROOT/_runtime/logs/ai_eigenflux_launchd.stdout.log" \
        "$PROJECT_ROOT/_runtime/logs/ai_eigenflux_launchd.stderr.log" \
        "$PROJECT_ROOT/_runtime/logs/ai_eigenflux_keepalive_patch.log" \
        "$PROJECT_ROOT/_runtime/logs/ai_eigenflux_cron_check.log"; do
        if [ -f "$f" ]; then
            local sz ts
            sz=$(stat -f '%z' "$f" 2>/dev/null || echo 0)
            ts=$(stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "$f" 2>/dev/null || echo "-")
            printf "  %-68s size=%-10s last=%s\n" "$f" "$sz" "$ts"
        else
            printf "  %-68s (not created yet)\n" "$f"
        fi
    done
}

case "$CMD" in
install)
    check_prerequisites
    echo "[1/10] stop existing engine (Finder/nohup/manual)..."
    "$COMMAND" stop >/dev/null 2>&1 || true
    echo "[2/10] ensure _runtime dirs + owner..."
    WHO="$(id -un)"
    for d in \
        "$PROJECT_ROOT/_runtime" \
        "$PROJECT_ROOT/_runtime/logs" \
        "$PROJECT_ROOT/_runtime/pids" \
        "$PROJECT_ROOT/_runtime/databases/Database"; do
        mkdir -p "$d"
        BAD=$(find "$d" -maxdepth 2 ! -user "$WHO" -print 2>/dev/null | head -n 5 || true)
        if [ -n "$BAD" ]; then
            echo "  [WARN] files/dirs below are not owned by $WHO, launchd may write-fail:"
            echo "$BAD" | sed 's/^/         /'
            echo "         suggest one-shot fix: sudo chown -R $WHO:staff $PROJECT_ROOT/_runtime"
        fi
    done
    # ---- Copy wrapper to LaunchAgents FIRST (OneDrive sandbox fix) ----
    echo "[3/10] deploy local starter wrapper -> $DST_WRAPPER (bypass OneDrive TCC sandbox)"
    if [ ! -f "$SRC_WRAPPER" ]; then
        echo "[FATAL] $SRC_WRAPPER not found"
        exit 10
    fi
    cp "$SRC_WRAPPER" "$DST_WRAPPER"
    # Replace placeholder in wrapper
    sed -i '' "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "$DST_WRAPPER"
    WMISS=$(grep -c "__PROJECT_ROOT__" "$DST_WRAPPER" 2>/dev/null || true)
    if [ "$WMISS" -gt 0 ]; then
        echo "[FATAL] wrapper still has ${WMISS} __PROJECT_ROOT__ placeholders"
        exit 11
    fi
    chmod 755 "$DST_WRAPPER"
    chown "$WHO:staff" "$DST_WRAPPER" 2>/dev/null || chown "$WHO" "$DST_WRAPPER"
    bash -n "$DST_WRAPPER" || { echo "[FATAL] wrapper syntax BAD"; exit 12; }
    echo "        wrapper copied: $DST_WRAPPER (755, owner=$WHO, syntax OK)"
    # ---- Render plist placeholders ----
    echo "[4/10] render plist placeholders -> $DST_PLIST"
    sed -e "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
        -e "s|__HOME_LA__|${HOME_LA_ABS}|g" \
        -e "s|__HOME__|${HOME_ABS}|g" \
        "$SRC_PLIST" > "$DST_PLIST"
    MISS=$(grep -cE "__PROJECT_ROOT__|__HOME_LA__|__HOME__" "$DST_PLIST" 2>/dev/null || true)
    if [ "$MISS" -gt 0 ]; then
        echo "[FATAL] plist still has ${MISS} unreplaced placeholders, ABORT"
        grep -nE "__PROJECT_ROOT__|__HOME_LA__|__HOME__" "$DST_PLIST" >&2
        exit 13
    fi
    echo "[5/10] enforce plist permission 644 & owner=$WHO:staff + plutil syntax"
    chmod 644 "$DST_PLIST"
    chown "$WHO:staff" "$DST_PLIST" 2>/dev/null || chown "$WHO" "$DST_PLIST"
    plutil -lint "$DST_PLIST" 2>&1 | sed 's/^/        /'
    if plutil -lint "$DST_PLIST" >/dev/null 2>&1; then
        echo "        syntax OK"
    else
        echo "[FATAL] plist syntax error (see plutil output above), ABORT"
        exit 14
    fi
    chmod +x "$COMMAND"
    echo "[6/10] launchctl bootout (ignore if not loaded) -> bootstrap"
    launchd_do_unload
    if ! launchd_do_load; then
        echo "[FATAL] launchctl bootstrap/load FAILED. common reasons:"
        echo "   1) plist owner != $WHO -> already fixed, re-check: ls -la $DST_PLIST"
        echo "   2) plist permission 755 -> must be 644, already fixed"
        echo "   3) machine never logged into LaunchAgents since reboot -> login to desktop once"
        echo "   4) try manual: launchctl bootstrap $LAUNCH_DOMAIN $DST_PLIST"
        exit 15
    fi
    echo "[7/10] launchctl kickstart $LABEL, wait 10s for verify (engine first-boot table build is slow)..."
    launchctl kickstart -k "$LAUNCH_DOMAIN/$LABEL" 2>/dev/null \
        || launchctl start "$LABEL" 2>/dev/null || true
    sleep 10
    echo "[8/10] install L3 crontab patrol (idempotent line, dedup marker=$CRON_MARK)"
    cron_append_line || exit 16
    echo "[9/10] L2+L3 installed, triple-domain verification..."
    sleep 3
    if launchd_is_loaded; then
        echo "        launchd REGISTERED: $(launchctl list 2>/dev/null | grep "$LABEL" | awk '{print "PID="$1" LastExit="$2}')"
    else
        echo "        ! launchd label not found; wait 10s then: bash $0 status re-check"
    fi
    echo
    if "$COMMAND" status >/dev/null 2>&1; then
        echo "        engine RUNNING (detail: $COMMAND status)"
    else
        echo "        ! engine NOT RUNNING yet; first table build may be slow; if still DOWN after 30s, check:"
        echo "          tail -n 100 $PROJECT_ROOT/_runtime/logs/ai_eigenflux_network_engine.err.log"
        echo "          tail -n 100 $PROJECT_ROOT/_runtime/logs/ai_eigenflux_launchd.stderr.log"
    fi
    if cron_has_line; then
        echo "        crontab L3 INSTALLED (once per minute patrol)"
    else
        echo "        ! crontab not written correctly (manual: crontab -l | grep MTSCOS_AI_EIGENFLUX confirm)"
    fi
    echo
    echo "[INSTALL OK v1.2.3] Triple keepalive ACTIVATED:"
    echo "   L1 engine: stale PID cleanup / 3-heartbeat BROKEN+reconnect auto-recover (built-in)"
    echo "   L2 launchd: login-start + KeepAlive=true + SIGTERM direct to python graceful stop"
    echo "   L3 crontab: per-minute check-keepalive fallback (when launchd unmanaged)"
    echo "   OneDrive TCC sandbox fix: wrapper in ~/Library/LaunchAgents/ + WorkingDirectory=HOME"
    echo "   After system reboot: auto-recovers once current user logs in."
    echo "   Management commands:"
    echo "     bash $0 status                  -> L1/L2/L3 full-view"
    echo "     bash $0 uninstall               -> clean uninstall launchd+crontab+stop daemon"
    echo "     $COMMAND logs 100               -> engine logs"
    echo "     tail -f $PROJECT_ROOT/_runtime/logs/ai_eigenflux_keepalive_patch.log  -> fallback audit"
    ;;

uninstall)
    echo "== Uninstall $LABEL (L2+L3 + wrapper) =="
    # first remove L3 (to prevent crontab from re-pulling while uninstalling)
    echo "[1/4] remove L3 crontab patrol..."
    cron_remove_line
    # then L2 launchd
    echo "[2/4] launchctl stop + bootout L2..."
    launchctl stop   "$LABEL" 2>/dev/null || true
    launchd_do_unload
    rm -f "$DST_PLIST"
    # also delete local wrapper (OneDrive sandbox workaround file)
    echo "[3/4] delete local starter wrapper..."
    if [ -f "$DST_WRAPPER" ]; then
        rm -f "$DST_WRAPPER"
        echo "        deleted: $DST_WRAPPER"
    else
        echo "        (wrapper not present, skip)"
    fi
    # stop engine (whether started manually, by nohup, or by launchd)
    echo "[4/4] stop engine..."
    "$COMMAND" stop 2>&1 | sed 's/^/  /' || true
    echo
    echo "[UNINSTALLED] optional: thoroughly clean logs (keep DB):"
    echo "              rm -f $PROJECT_ROOT/_runtime/logs/ai_eigenflux_launchd.*.log"
    echo "              rm -f $PROJECT_ROOT/_runtime/logs/ai_eigenflux_network_engine.*.log"
    echo "              rm -f $PROJECT_ROOT/_runtime/logs/ai_eigenflux_keepalive_patch.log"
    echo "              rm -f $PROJECT_ROOT/_runtime/logs/ai_eigenflux_cron_check.log"
    ;;

status)
    do_status
    ;;

*)
    echo "Usage: $0 [install|uninstall|status]"
    exit 1
    ;;
esac
