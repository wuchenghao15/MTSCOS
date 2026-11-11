#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途: MTSCOS AI 项目数据库备份与恢复工具
功能:
  backup  - 复制 app.db 到 backups/ 目录, 文件名带时间戳, 自动清理超过 30 天的旧备份
  restore - 从备份文件恢复数据库 (需指定 --file), 恢复前自动创建当前数据库的快照
  list    - 列出所有备份文件及大小
所有操作记录到 backups/backup_log.json
用法:
  python3 backup_restore.py backup
  python3 backup_restore.py restore --file <备份文件路径>
  python3 backup_restore.py list
创建日期: 2026-08-15
"""

import os
import sys
import json
import shutil
import argparse
from datetime import datetime, timedelta

# 路径解析: 脚本位于 flask-app/scripts/tools/ 下, 向上两级到 flask-app 根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

DB_PATH = os.path.join(PROJECT_ROOT, 'app.db')
BACKUP_DIR = os.path.join(PROJECT_ROOT, 'backups')
LOG_FILE = os.path.join(BACKUP_DIR, 'backup_log.json')

# 旧备份清理阈值
OLD_BACKUP_DAYS = 30


def human_size(size_bytes):
    """将字节大小转换为人类可读格式"""
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def ensure_backup_dir():
    """确保备份目录存在"""
    if not os.path.isdir(BACKUP_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)


def append_log(entry):
    """追加一条操作日志到 backup_log.json

    日志结构: [{timestamp, action, ...}, ...]
    若日志文件损坏则重建, 不影响主流程
    """
    ensure_backup_dir()
    log = []
    if os.path.isfile(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                log = json.load(f)
                if not isinstance(log, list):
                    log = []
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    try:
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[警告] 写入日志文件失败: {e}")


def list_backups():
    """列出 backups/ 目录下所有备份文件 (按修改时间倒序)"""
    ensure_backup_dir()
    backups = []
    for name in os.listdir(BACKUP_DIR):
        full = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(full):
            continue
        # 跳过日志文件本身, 它不是备份
        if name == 'backup_log.json':
            continue
        stat = os.stat(full)
        backups.append({
            'name': name,
            'path': full,
            'size': stat.st_size,
            'size_human': human_size(stat.st_size),
            'mtime': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    backups.sort(key=lambda x: x['mtime'], reverse=True)
    return backups


def clean_old_backups():
    """清理超过 OLD_BACKUP_DAYS 天的旧备份文件 (跳过日志文件)"""
    threshold = datetime.now() - timedelta(days=OLD_BACKUP_DAYS)
    removed = []
    for name in os.listdir(BACKUP_DIR):
        full = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(full):
            continue
        if name == 'backup_log.json':
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(full))
        if mtime < threshold:
            try:
                os.remove(full)
                removed.append({'name': name, 'mtime': mtime.isoformat()})
            except OSError as e:
                print(f"[警告] 删除旧备份失败 {name}: {e}")
    return removed


def cmd_backup():
    """执行备份: app.db -> backups/app_YYYYMMDD_HHMMSS.db"""
    ensure_backup_dir()
    if not os.path.isfile(DB_PATH):
        print(f"[错误] 数据库文件不存在: {DB_PATH}")
        return 2

    # 生成带时间戳的备份文件名
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"app_{ts}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    # 极端情况下秒级冲突, 加 _1 后缀
    if os.path.exists(backup_path):
        backup_path = os.path.join(BACKUP_DIR, f"app_{ts}_1.db")

    print(f"[备份] {DB_PATH} -> {backup_path}")
    try:
        # copy2 保留元数据 (mtime 等)
        shutil.copy2(DB_PATH, backup_path)
    except Exception as e:
        print(f"[错误] 备份失败: {e}")
        return 2

    backup_size = os.path.getsize(backup_path)
    print(f"[完成] 备份大小: {human_size(backup_size)}")

    # 清理旧备份
    removed = clean_old_backups()
    if removed:
        print(f"[清理] 移除 {len(removed)} 个超过 {OLD_BACKUP_DAYS} 天的旧备份:")
        for r in removed:
            print(f"  - {r['name']} (mtime: {r['mtime']})")
    else:
        print(f"[清理] 无超过 {OLD_BACKUP_DAYS} 天的旧备份需要清理")

    # 记录日志
    append_log({
        'timestamp': datetime.now().isoformat(),
        'action': 'backup',
        'source': DB_PATH,
        'target': backup_path,
        'size': backup_size,
        'size_human': human_size(backup_size),
        'old_backups_removed': removed
    })
    print(f"[日志] 操作已记录到 {LOG_FILE}")
    return 0


def cmd_restore(file_path):
    """执行恢复: 备份文件 -> app.db (恢复前自动创建当前数据库快照)"""
    ensure_backup_dir()

    # 验证备份文件
    if not file_path or not os.path.isfile(file_path):
        print(f"[错误] 备份文件不存在: {file_path}")
        return 2

    # 恢复前自动创建当前数据库的快照 (前提: 当前数据库存在)
    snapshot_path = None
    if os.path.isfile(DB_PATH):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        snapshot_name = f"pre_restore_snapshot_{ts}.db"
        snapshot_path = os.path.join(BACKUP_DIR, snapshot_name)
        print(f"[快照] 恢复前创建当前数据库快照: {snapshot_path}")
        try:
            shutil.copy2(DB_PATH, snapshot_path)
        except Exception as e:
            print(f"[警告] 创建快照失败: {e}, 继续恢复...")
            snapshot_path = None
    else:
        print("[信息] 当前数据库不存在, 跳过快照创建")

    # 执行恢复
    print(f"[恢复] {file_path} -> {DB_PATH}")
    try:
        shutil.copy2(file_path, DB_PATH)
    except Exception as e:
        print(f"[错误] 恢复失败: {e}")
        return 2

    print(f"[完成] 数据库已恢复")

    # 记录日志
    append_log({
        'timestamp': datetime.now().isoformat(),
        'action': 'restore',
        'source': file_path,
        'target': DB_PATH,
        'pre_restore_snapshot': snapshot_path
    })
    print(f"[日志] 操作已记录到 {LOG_FILE}")
    return 0


def cmd_list():
    """列出所有备份文件及大小"""
    backups = list_backups()
    if not backups:
        print(f"[信息] 备份目录 {BACKUP_DIR} 中没有备份文件")
        return 0

    total_size = sum(b['size'] for b in backups)
    print(f"=== 备份文件列表 ({len(backups)} 个, 总计 {human_size(total_size)}) ===")
    print(f"{'序号':<6}{'文件名':<50}{'大小':<15}{'修改时间'}")
    print("-" * 100)
    for i, b in enumerate(backups, 1):
        print(f"{i:<6}{b['name']:<50}{b['size_human']:<15}{b['mtime']}")
    return 0


def main():
    """主函数: 解析命令行参数并分发到对应子命令"""
    parser = argparse.ArgumentParser(
        description='MTSCOS AI 项目数据库备份与恢复工具'
    )
    sub = parser.add_subparsers(dest='command', help='子命令')
    sub.add_parser('backup', help='备份数据库到 backups/')
    p_restore = sub.add_parser('restore', help='从备份恢复数据库')
    p_restore.add_argument('--file', required=True, help='备份文件路径')
    sub.add_parser('list', help='列出所有备份文件')

    args = parser.parse_args()

    if args.command == 'backup':
        return cmd_backup()
    elif args.command == 'restore':
        return cmd_restore(args.file)
    elif args.command == 'list':
        return cmd_list()
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
