#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: MTSCOS AI 项目日志清理脚本
功能:
  - 扫描 logs/ 目录下所有 .log 文件
  - 超过 30 天的日志自动归档到 logs/archive/
  - 超过 100MB 的日志自动轮转 (保留最后 1000 行)
  - 清理空日志文件
  - 统计清理前后大小对比
  - 支持 --dry-run 参数 (只显示不执行)
用法:
  python3 log_cleanup.py            # 执行清理
  python3 log_cleanup.py --dry-run # 只显示不执行
创建日期: 2026-08-15
"""

import os
import sys
import shutil
from datetime import datetime

# 路径解析: 脚本位于 flask-app/scripts/tools/ 下, 向上两级到 flask-app 根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

LOGS_DIR = os.path.join(PROJECT_ROOT, 'logs')
ARCHIVE_DIR = os.path.join(LOGS_DIR, 'archive')

# 阈值配置
ARCHIVE_DAYS = 30              # 超过 30 天的日志归档
ROTATE_SIZE = 100 * 1024 * 1024  # 100MB 触发轮转
ROTATE_KEEP_LINES = 1000       # 轮转时保留最后 1000 行


def parse_args(argv):
    """解析命令行参数"""
    return {'dry_run': '--dry-run' in argv}


def human_size(size_bytes):
    """将字节大小转换为人类可读格式"""
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def get_file_mtime_days(path):
    """获取文件最后修改时间距今天的天数"""
    mtime = os.path.getmtime(path)
    return (datetime.now().timestamp() - mtime) / 86400


def scan_log_files():
    """扫描 logs/ 目录下所有顶层 .log 文件 (不递归 archive/)"""
    files = []
    if not os.path.isdir(LOGS_DIR):
        return files
    for name in os.listdir(LOGS_DIR):
        full = os.path.join(LOGS_DIR, name)
        if not os.path.isfile(full):
            continue
        if not name.endswith('.log'):
            continue
        files.append({
            'name': name,
            'path': full,
            'size': os.path.getsize(full),
            'mtime_days': get_file_mtime_days(full)
        })
    return files


def archive_file(file_info, dry_run):
    """归档日志文件到 logs/archive/ 目录, 文件名加时间戳防冲突"""
    # 使用文件 mtime 作为归档后缀, 便于追溯原始时间
    mtime_dt = datetime.fromtimestamp(os.path.getmtime(file_info['path']))
    ts = mtime_dt.strftime('%Y%m%d_%H%M%S')
    archive_name = f"{file_info['name']}.{ts}"
    archive_path = os.path.join(ARCHIVE_DIR, archive_name)
    # 极端情况下同名归档文件已存在, 加 .bak 后缀
    if os.path.exists(archive_path):
        archive_path = os.path.join(ARCHIVE_DIR, f"{archive_name}.bak")
    if dry_run:
        return {'action': 'archive', 'target': archive_path, 'dry_run': True}
    # 确保 archive 目录存在
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    shutil.move(file_info['path'], archive_path)
    return {'action': 'archive', 'target': archive_path, 'dry_run': False}


def rotate_file(file_info, dry_run):
    """轮转日志文件: 保留最后 ROTATE_KEEP_LINES 行, 其余丢弃"""
    try:
        # errors='ignore' 防止遇到非 UTF-8 字符时崩溃
        with open(file_info['path'], 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        return {'action': 'rotate', 'error': str(e), 'dry_run': dry_run}
    kept = lines[-ROTATE_KEEP_LINES:] if len(lines) > ROTATE_KEEP_LINES else lines
    if dry_run:
        return {
            'action': 'rotate',
            'original_lines': len(lines),
            'kept_lines': len(kept),
            'dry_run': True
        }
    # 写回保留的行 (覆盖原文件)
    with open(file_info['path'], 'w', encoding='utf-8') as f:
        f.writelines(kept)
    return {
        'action': 'rotate',
        'original_lines': len(lines),
        'kept_lines': len(kept),
        'dry_run': False
    }


def delete_empty(file_info, dry_run):
    """删除空日志文件"""
    if dry_run:
        return {'action': 'delete_empty', 'dry_run': True}
    os.remove(file_info['path'])
    return {'action': 'delete_empty', 'dry_run': False}


def process_file(file_info, dry_run):
    """对单个日志文件执行清理动作

    优先级 (单次只执行一种动作, 避免冲突):
      1. 空文件 -> 直接删除
      2. 大文件 (>100MB) -> 轮转 (保留尾部 1000 行, 写回后 mtime 更新, 不再归档)
      3. 老文件 (>30 天) -> 归档
    """
    if file_info['size'] == 0:
        return delete_empty(file_info, dry_run)
    if file_info['size'] > ROTATE_SIZE:
        return rotate_file(file_info, dry_run)
    if file_info['mtime_days'] > ARCHIVE_DAYS:
        return archive_file(file_info, dry_run)
    return None


def main():
    """主函数: 扫描日志 -> 执行清理 -> 输出统计"""
    args = parse_args(sys.argv[1:])
    dry_run = args['dry_run']

    print(f"=== 日志清理脚本 {'(dry-run 模式)' if dry_run else ''} ===")
    print(f"日志目录: {LOGS_DIR}")
    print(f"归档目录: {ARCHIVE_DIR}")
    print(f"配置: 归档 > {ARCHIVE_DAYS} 天, 轮转 > {ROTATE_SIZE // 1024 // 1024}MB (保留 {ROTATE_KEEP_LINES} 行)")
    print()

    if not os.path.isdir(LOGS_DIR):
        print(f"[错误] 日志目录不存在: {LOGS_DIR}")
        return 1

    files = scan_log_files()
    if not files:
        print("[信息] 未发现 .log 文件, 无需清理")
        return 0

    # 清理前统计
    total_before = sum(f['size'] for f in files)
    print(f"[清理前] 共 {len(files)} 个日志文件, 总大小: {human_size(total_before)}")
    print()

    # 逐文件执行清理动作
    actions = []
    for f in files:
        action = process_file(f, dry_run)
        if action:
            actions.append({'file': f['name'], 'size_before': f['size'], **action})

    # 清理后统计
    if dry_run:
        # dry-run 模式下未实际执行, 总大小不变
        total_after = total_before
        files_after = len(files)
        print(f"[dry-run] 计划执行 {len(actions)} 个动作:")
    else:
        files_after_list = scan_log_files()
        total_after = sum(f['size'] for f in files_after_list)
        files_after = len(files_after_list)

    print()
    print(f"[清理后] 共 {files_after} 个日志文件, 总大小: {human_size(total_after)}")
    freed = total_before - total_after
    print(f"[节省]   释放空间: {human_size(freed)}")

    # 动作详情
    print()
    print("=== 动作详情 ===")
    for a in actions:
        line = f"  - {a['file']}: {a['action']}"
        if a.get('target'):
            line += f" -> {a['target']}"
        if a.get('original_lines') is not None:
            line += f" (原 {a['original_lines']} 行 -> 保留 {a['kept_lines']} 行)"
        if a.get('error'):
            line += f" (错误: {a['error']})"
        line += ' [dry-run]' if a.get('dry_run') else ''
        print(line)

    print()
    print(f"总计: 执行 {len(actions)} 个动作, 释放 {human_size(freed)} 空间")
    return 0


if __name__ == '__main__':
    sys.exit(main())
