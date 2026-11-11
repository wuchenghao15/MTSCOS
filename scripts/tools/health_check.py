#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: MTSCOS AI 项目健康检查脚本
功能:
  - 检查数据库连接和表数量
  - 检查关键目录是否存在 (ai_engines/, services/, routes/, templates/)
  - 检查磁盘空间 (根目录剩余空间)
  - 检查 Python 进程数量
  - 检查日志文件大小 (超过 100MB 告警)
  - 输出 JSON 格式健康报告
退出码: 0=健康, 1=告警, 2=严重
创建日期: 2026-08-15
"""

import os
import sys
import json
import sqlite3
import shutil
import subprocess
from datetime import datetime

# 路径解析: 脚本位于 flask-app/scripts/tools/ 下, 向上两级到 flask-app 根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

# 关键配置
DB_PATH = os.path.join(PROJECT_ROOT, 'app.db')
LOGS_DIR = os.path.join(PROJECT_ROOT, 'logs')

# 关键目录 (相对于 PROJECT_ROOT)
# critical: 缺失视为严重问题; optional: 缺失视为告警
CRITICAL_DIRS = ['ai_engines', 'services']
OPTIONAL_DIRS = ['routes', 'templates']

# 告警阈值
LOG_WARN_SIZE = 100 * 1024 * 1024  # 100MB
DISK_WARN_GB = 5    # 剩余空间 < 5GB 告警
DISK_CRIT_GB = 1    # 剩余空间 < 1GB 严重
PROC_WARN_COUNT = 100  # Python 进程数 > 100 告警


def check_database():
    """检查数据库连接和表数量"""
    result = {
        'status': 'ok',
        'path': DB_PATH,
        'exists': os.path.exists(DB_PATH),
        'table_count': 0,
        'error': None
    }
    if not result['exists']:
        result['status'] = 'critical'
        result['error'] = '数据库文件不存在'
        return result
    try:
        # 只读方式连接, 不影响正在运行的服务
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        result['table_count'] = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        result['status'] = 'critical'
        result['error'] = f'数据库连接失败: {e}'
    return result


def check_directories():
    """检查关键目录是否存在"""
    result = {'critical': {}, 'optional': {}}
    for d in CRITICAL_DIRS:
        path = os.path.join(PROJECT_ROOT, d)
        result['critical'][d] = {
            'path': path,
            'exists': os.path.isdir(path)
        }
    for d in OPTIONAL_DIRS:
        path = os.path.join(PROJECT_ROOT, d)
        result['optional'][d] = {
            'path': path,
            'exists': os.path.isdir(path)
        }
    return result


def check_disk_space():
    """检查根目录磁盘剩余空间"""
    result = {
        'status': 'ok',
        'total': 0,
        'used': 0,
        'free': 0,
        'free_gb': 0.0,
        'error': None
    }
    try:
        usage = shutil.disk_usage('/')
        result['total'] = usage.total
        result['used'] = usage.used
        result['free'] = usage.free
        result['free_gb'] = round(usage.free / (1024 ** 3), 2)
        if result['free_gb'] < DISK_CRIT_GB:
            result['status'] = 'critical'
        elif result['free_gb'] < DISK_WARN_GB:
            result['status'] = 'warning'
    except Exception as e:
        result['status'] = 'critical'
        result['error'] = f'磁盘空间检查失败: {e}'
    return result


def check_python_processes():
    """检查 Python 进程数量 (跨平台兼容 macOS / Linux)"""
    result = {
        'status': 'ok',
        'count': 0,
        'error': None
    }
    try:
        # 使用 ps 命令列出所有进程, 在 Python 中过滤
        proc = subprocess.run(
            ['ps', 'aux'],
            capture_output=True, text=True, timeout=10
        )
        count = 0
        # 跳过表头, 逐行统计包含 python 关键字的进程
        for line in proc.stdout.splitlines()[1:]:
            if 'python' in line.lower():
                count += 1
        result['count'] = count
        if count > PROC_WARN_COUNT:
            result['status'] = 'warning'
    except Exception as e:
        result['status'] = 'warning'
        result['error'] = f'进程检查失败: {e}'
    return result


def check_log_files():
    """检查日志文件大小 (超过 100MB 告警)"""
    result = {
        'status': 'ok',
        'log_dir': LOGS_DIR,
        'log_dir_exists': os.path.isdir(LOGS_DIR),
        'files': [],
        'oversize_count': 0,
        'error': None
    }
    if not result['log_dir_exists']:
        result['status'] = 'warning'
        result['error'] = '日志目录不存在'
        return result
    try:
        # 仅扫描顶层 .log 文件, 不递归 archive/ 子目录
        for name in os.listdir(LOGS_DIR):
            full = os.path.join(LOGS_DIR, name)
            if not os.path.isfile(full):
                continue
            if not name.endswith('.log'):
                continue
            size = os.path.getsize(full)
            f_info = {
                'name': name,
                'path': full,
                'size': size,
                'size_mb': round(size / (1024 * 1024), 2),
                'oversize': size > LOG_WARN_SIZE
            }
            if f_info['oversize']:
                result['oversize_count'] += 1
            result['files'].append(f_info)
        if result['oversize_count'] > 0:
            result['status'] = 'warning'
    except Exception as e:
        result['status'] = 'warning'
        result['error'] = f'日志检查失败: {e}'
    return result


def main():
    """主函数: 执行所有检查并输出 JSON 健康报告"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'project_root': PROJECT_ROOT,
        'checks': {}
    }

    # 依次执行各项检查
    report['checks']['database'] = check_database()
    report['checks']['directories'] = check_directories()
    report['checks']['disk_space'] = check_disk_space()
    report['checks']['python_processes'] = check_python_processes()
    report['checks']['log_files'] = check_log_files()

    # 计算总体退出码: 0=健康, 1=告警, 2=严重
    exit_code = 0

    # 严重条件: 数据库连接失败 / 关键目录缺失 / 磁盘空间严重不足
    if report['checks']['database']['status'] == 'critical':
        exit_code = max(exit_code, 2)
    if any(not d['exists'] for d in report['checks']['directories']['critical'].values()):
        exit_code = max(exit_code, 2)
    if report['checks']['disk_space']['status'] == 'critical':
        exit_code = max(exit_code, 2)

    # 告警条件: 数据库告警 / 磁盘空间告警 / 进程过多 / 日志过大 / 可选目录缺失
    if exit_code < 1:
        if report['checks']['database'].get('status') == 'warning':
            exit_code = 1
        if report['checks']['disk_space']['status'] == 'warning':
            exit_code = 1
        if report['checks']['python_processes']['status'] == 'warning':
            exit_code = 1
        if report['checks']['log_files']['status'] == 'warning':
            exit_code = 1
        if any(not d['exists'] for d in report['checks']['directories']['optional'].values()):
            exit_code = 1

    status_map = {0: 'healthy', 1: 'warning', 2: 'critical'}
    report['overall_status'] = status_map[exit_code]
    report['exit_code'] = exit_code

    # 输出 JSON 格式报告
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
