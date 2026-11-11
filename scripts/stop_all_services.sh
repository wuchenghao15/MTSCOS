#!/bin/bash

# 停止所有服务的脚本

# 设置工作目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}" || exit 1

PID_DIR="${PROJECT_DIR}/_runtime/pids"

stop_managed_process() {
    local name="$1"
    local pid_file="${PID_DIR}/${name}.pid"

    if [ ! -f "${pid_file}" ]; then
        log "未找到 ${name} PID文件"
        return 0
    fi

    local pid command expected
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ ! "${pid}" =~ ^[0-9]+$ ]] || ! kill -0 "${pid}" 2>/dev/null; then
        log "${name}未运行，清理残留PID文件"
        rm -f "${pid_file}"
        return 0
    fi

    command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
    case "${name}" in
        flask_app) expected="app.py" ;;
        service_manager) expected="service_manager" ;;
        *) expected="" ;;
    esac
    if [ -n "${expected}" ] && [[ "${command}" != *"${expected}"* ]]; then
        log "拒绝停止${name}: PID ${pid} 当前命令不匹配 (${command})"
        rm -f "${pid_file}"
        return 1
    fi

    log "停止${name}进程: ${pid}"
    kill -TERM "${pid}" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        kill -0 "${pid}" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
        log "${name}未响应，强制停止: ${pid}"
        kill -KILL "${pid}" 2>/dev/null || true
    else
        log "${name}已停止"
    fi
    rm -f "${pid_file}"
}

# 输出带时间戳的日志
log() {
    echo "[$(date +"%Y-%m-%d %H:%M:%S")] $1"
}

log "开始停止MTSCOS AI系统服务..."

log "停止Flask应用"
stop_managed_process "flask_app"

log "停止服务管理器"
stop_managed_process "service_manager"

# 清理进程ID文件
if [ -f "process_ids.log" ]; then
    rm process_ids.log
    log "清理进程ID文件"
fi

log "当前运行的服务："
ps aux | grep -E "(service_manager|app.py)" | grep -v grep

log "所有服务停止完成！"
