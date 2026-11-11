#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# hulk_nas_watch.sh — mini macOS 上 fnOS NAS (hulk-nas) 自动挂载守护
# flow_nas_mount_20261030 → 更新 2026-11-03: 多 IP 降级 (134/057/140 同一 host key)
#
# 前置: 用户需首次手动挂载 (凭据一次,存 Keychain):
#   mkdir -p ~/mnt/hulk-nas
#   mount_smbfs "//wuchenghao15@192.168.31.134" ~/mnt/hulk-nas
# 然后本脚本每 5min 检查: 挂载点活? NAS ping 通? 不通就重挂.
# ═══════════════════════════════════════════════════════════════════════

set -u

# fnOS NAS — 三 IP 同一 host key,同一台机器
NAS_HOSTS=("192.168.31.134" "192.168.31.57" "192.168.31.140")
MOUNT_POINT="${HOME}/mnt/hulk-nas"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="$LOG_DIR/mtscos_nas_watch.log"

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# 选第一个 ping 通的 IP
_pick_host() {
    for h in "${NAS_HOSTS[@]}"; do
        ping -c 1 -W 2 "$h" &>/dev/null && echo "$h" && return 0
    done
    echo "${NAS_HOSTS[0]}"   # 全不通返回默认
}

NAS_HOST="$(_pick_host)"
LAST_PING="${NAS_HOST}"

# 1. 挂载点活?
if mount | grep -q "smbfs.*$MOUNT_POINT"; then
    # 挂载着 → 再测 NAS ping
    if ping -c 1 -W 2 "$NAS_HOST" &>/dev/null; then
        exit 0   # 完全 OK
    fi
    # 挂载着但 NAS ping 不通 → 卸载
    log "⚠️ 挂载中但 NAS 不通 → 卸载 $MOUNT_POINT"
    umount "$MOUNT_POINT" 2>/dev/null || log "  umount 失败 (可能 busy)"
fi

# 2. NAS 可达?
if ! ping -c 1 -W 3 "$NAS_HOST" &>/dev/null; then
    log "❌ NAS $NAS_HOST 不可达 → 跳过本次"
    exit 0
fi

# 3. 尝试重挂载 (凭据存在 Keychain 就自动; 否则 skip 等用户手动)
log "🔄 尝试重挂载 → $MOUNT_POINT"
mkdir -p "$MOUNT_POINT"

# macOS mount_smbfs 会自动从 Keychain 取存过的凭据 (首次手动 mount_smbfs -o nosoftmount -o keychain ...)
# 这里只给 host + share + mountpoint, 让它自动找凭据
if mount_smbfs -o nosoftmount "//@${NAS_HOST}" "$MOUNT_POINT" 2>>"$LOG_FILE"; then
    log "✅ NAS 重挂载成功"
else
    log "❌ 重挂载失败 (需手动 mount_smbfs 保存凭据到 Keychain)"
fi
