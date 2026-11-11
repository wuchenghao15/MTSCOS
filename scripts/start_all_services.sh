#!/bin/bash

# 启动所有服务的脚本

# 设置工作目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}" || exit 1

RUNTIME_DIR="${PROJECT_DIR}/_runtime"
PID_DIR="${RUNTIME_DIR}/pids"
mkdir -p "${PID_DIR}"
START_LOCK_DIR="${RUNTIME_DIR}/.start_all_services.lock"

if ! mkdir "${START_LOCK_DIR}" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 启动脚本已在运行，跳过本次调用"
    exit 0
fi
trap 'rm -rf "${START_LOCK_DIR}"' EXIT INT TERM
printf '%s\n' "$$" > "${START_LOCK_DIR}/pid"

start_managed_process() {
    local name="$1"
    local pid_file="${PID_DIR}/${name}.pid"
    local log_file="$2"
    shift 2

    if [ -f "${pid_file}" ]; then
        local existing_pid
        existing_pid="$(cat "${pid_file}" 2>/dev/null || true)"
        if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
            local existing_command expected
            existing_command="$(ps -p "${existing_pid}" -o command= 2>/dev/null || true)"
            case "${name}" in
                flask_app) expected="app.py" ;;
                service_manager) expected="service_manager" ;;
                *) expected="" ;;
            esac
            if [ -z "${expected}" ] || [[ "${existing_command}" == *"${expected}"* ]]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${name} 已运行 (PID: ${existing_pid})，跳过重复启动"
                return 0
            fi
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${name} PID文件指向其他进程，清理残留文件"
        fi
        rm -f "${pid_file}"
    fi

    nohup "$@" > "${log_file}" 2>&1 &
    local pid=$!
    echo "${pid}" > "${pid_file}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${name} 已启动 (PID: ${pid})"
}

# 输出带时间戳的日志
log() {
    echo "[$(date +"%Y-%m-%d %H:%M:%S")] $1"
}

log "开始启动MTSCOS AI系统服务..."

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    log "错误: Python 3 未安装"
    exit 1
fi

# 检查是否有虚拟环境
if [ -d "venv" ]; then
    log "使用虚拟环境"
    VENV_ACTIVATE="venv/bin/activate"
else
    log "未找到虚拟环境，使用系统Python"
    VENV_ACTIVATE=""
fi

# 启动服务管理脚本
log "启动服务管理脚本"
if [ -n "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
    start_managed_process "service_manager" "service_manager.log" python3 -m app.services.service_manager
else
    start_managed_process "service_manager" "service_manager.log" python3 -m app.services.service_manager
fi

# 等待服务管理器启动
sleep 3

# 启动Flask应用
log "启动Flask应用"
if [ -n "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
    start_managed_process "flask_app" "flask_app.log" python3 app.py
else
    start_managed_process "flask_app" "flask_app.log" python3 app.py
fi

# 记录进程ID
log "记录进程ID"
{
    for pid_file in "${PID_DIR}"/*.pid; do
        [ -f "${pid_file}" ] || continue
        printf '%s %s\n' "$(basename "${pid_file}" .pid)" "$(cat "${pid_file}")"
    done
} > "${PROJECT_DIR}/process_ids.log"

log "所有服务启动完成！"
log "服务日志："
log "- 服务管理器: service_manager.log"
log "- Flask应用: flask_app.log"
log "- 进程ID: process_ids.log"

# 显示当前运行的服务
log "当前运行的服务："
ps aux | grep -E "(service_manager|app.py)" | grep -v grep
