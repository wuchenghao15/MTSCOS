#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地优先安全架构 — Local Security Manifest
============================================

定义仙女座操盘系统金融数据安全架构四大支柱:

  §1 加密分级 L1/L2/L3 — 覆盖所有 mt_* 核心表
  §2 备份策略 — WAL + 定时硬链接复制 + VACUUM 周期
  §3 AI 专员全程跟踪 — 关键表写入强制进 evolution_log
  §4 专门通道不可截流 — Flask blueprint 内部通道保护

这是 **数据安全架构定义文件** (declarative), 不直接执行加密/备份,
而是被 security_engineer_employee / backup_manager / flask blueprints 引用.

FLOW_ID: flow_security_manifest_20261108
"""
from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ══════════════════════════════════════════════════════════════════
# §1 加密分级 — 覆盖所有 mt_* 表
# ══════════════════════════════════════════════════════════════════

class EncryptionLevel:
    """加密等级常量"""
    L1_PUBLIC = 'L1'          # 公开级: 明文存储
    L2_SENSITIVE = 'L2'       # 敏感级: AES-256 加密落盘
    L3_CORE = 'L3'            # 核心级: 内存态仅存, 不落盘


# 核心金融/团队/协同表 → 加密分级
# 格式: table_name -> (level, reason)
MT_TABLE_ENCRYPTION = {
    # ── L3 核心级 (内存态, 不落盘) ──
    # 目前无直接表, L3 数据通过进程内 AES-GCM session key 处理
    # 示例: VIKEY 硬件密钥状态、实时资金密码等

    # ── L2 敏感级 (AES-256 加密落盘) ──
    'mt_trade_log': (EncryptionLevel.L2_SENSITIVE, '交易记录含持仓方向+金额'),
    'mt_sandbox_portfolio': (EncryptionLevel.L2_SENSITIVE, '沙盘持仓含完整仓位信息'),
    'mt_sandbox_portfolio_bak_20261107': (EncryptionLevel.L2_SENSITIVE, '沙盘持仓备份同主表'),
    'mt_center_knowledge_points': (EncryptionLevel.L2_SENSITIVE, '操盘知识含策略意图'),
    'mt_center_evolution_log': (EncryptionLevel.L2_SENSITIVE, '系统进化日志含内部事件详情'),
    'mt_sa_dual_key_status': (EncryptionLevel.L2_SENSITIVE, '硬件密钥状态含 VIKEY/SZU100 指纹'),
    'mt_crypto_keys': (EncryptionLevel.L2_SENSITIVE, '加密密钥索引表'),

    # ── L1 公开级 (明文存储, 可跨节点同步) ──
    'mt_center_direction_pool': (EncryptionLevel.L1_PUBLIC, '策略方向池公开可读'),
    'mt_center_direction_execution': (EncryptionLevel.L1_PUBLIC, '方向执行记录'),
    'mt_center_pulse': (EncryptionLevel.L1_PUBLIC, '系统心跳'),
    'mt_center_self_check': (EncryptionLevel.L1_PUBLIC, '自检记录'),
    'mt_fm_brain_feed': (EncryptionLevel.L1_PUBLIC, '情报脑库流可公开展示'),
    'mt_market_radar_cache': (EncryptionLevel.L1_PUBLIC, '市场雷达缓存'),
    'mt_sandbox_signals': (EncryptionLevel.L1_PUBLIC, '沙盘信号公开复盘'),
    'mt_sandbox_snapshots': (EncryptionLevel.L1_PUBLIC, '沙盘快照公开'),
    'mt_andromeda_knowledge_base': (EncryptionLevel.L1_PUBLIC, '仙女座知识库公开'),
    'mt_andromeda_workflow_runs': (EncryptionLevel.L1_PUBLIC, '工作流运行记录公开'),
    'mt_eng_tracks': (EncryptionLevel.L1_PUBLIC, '引擎运行轨迹公开'),
    'mt_cnkr_tracks': (EncryptionLevel.L1_PUBLIC, 'CNKR 轨道公开'),
    'mt_consensus': (EncryptionLevel.L1_PUBLIC, '共识结果公开'),
    'mt_collab_bus_events': (EncryptionLevel.L1_PUBLIC, '协同总线事件公开'),
    'mt_collab_channel': (EncryptionLevel.L1_PUBLIC, '协同频道公开'),
    'mt_collab_message': (EncryptionLevel.L1_PUBLIC, '协同消息公开'),
    'mt_collab_participation': (EncryptionLevel.L1_PUBLIC, '协同参与公开'),
    'mt_neuron': (EncryptionLevel.L1_PUBLIC, '神经元参数公开'),
    'mt_team_members': (EncryptionLevel.L1_PUBLIC, '团队成员公开'),
    'mt_team_registry': (EncryptionLevel.L1_PUBLIC, '团队注册表公开'),
    'mt_eng_track_log': (EncryptionLevel.L1_PUBLIC, '引擎轨迹日志公开'),
    'mt_cnkr_track_log': (EncryptionLevel.L1_PUBLIC, 'CNKR 轨迹日志公开'),
    'mt_daemon_registry': (EncryptionLevel.L1_PUBLIC, 'daemon 注册表公开'),
    'mt_lab_task_hall': (EncryptionLevel.L1_PUBLIC, '任务大厅公开协作'),
    'mt_hall_flow_timeline': (EncryptionLevel.L1_PUBLIC, '大厅流程公开'),
}


# ── 快速查询函数 ──
def get_table_encryption(table_name: str) -> tuple[str, str]:
    """查表的加密分级 + 原因. 未登记的默认为 L1"""
    return MT_TABLE_ENCRYPTION.get(table_name, (EncryptionLevel.L1_PUBLIC, '未登记, 默认 L1'))


def list_by_level(level: str) -> list[tuple[str, str]]:
    """按加密等级列出表"""
    return [(t, reason) for t, (lvl, reason) in MT_TABLE_ENCRYPTION.items() if lvl == level]


# ══════════════════════════════════════════════════════════════════
# §2 备份策略 — 三重保障
# ══════════════════════════════════════════════════════════════════

class BackupStrategy:
    """备份策略常量"""
    WAL = 'WAL'                    # SQLite WAL 模式实时备份
    PERIODIC_COPY = 'PERIODIC_COPY'  # 定时 .db 硬链接复制
    VACUUM_CYCLE = 'VACUUM_CYCLE'    # 周期性 VACUUM + 全量备份
    INCREMENTAL = 'INCREMENTAL'      # WAL 增量导出


# 备份配置
BACKUP_CONFIG = {
    # 所有表默认启用 WAL (SQLite journal_mode=WAL)
    'default_wal': True,

    # 备份目录
    'backup_dir': '~/mtscos_backup/',

    # 定时硬链接复制: 每天凌晨 2:00
    'periodic_copy': {
        'enabled': True,
        'schedule': '0 2 * * *',          # cron: 每天 02:00
        'method': 'hardlink',              # 硬链接, 节省空间
        'keep_days': 30,
    },

    # VACUUM + 全量备份: 每周日凌晨 3:00
    'vacuum_cycle': {
        'enabled': True,
        'schedule': '0 3 * * 0',          # cron: 每周日 03:00
        'vacuum': True,                     # 先 VACUUM 再复制
        'keep_weeks': 8,
    },

    # 需要额外增量备份的关键表
    'incremental_tables': [
        'mt_trade_log',
        'mt_sandbox_portfolio',
        'mt_center_knowledge_points',
        'mt_center_evolution_log',
    ],
    'incremental_interval_hours': 6,  # 每 6 小时一次增量 WAL 导出
}


def get_backup_strategy(table_name: str) -> dict:
    """获取某表的完整备份策略"""
    base = {'wal': BackupStrategy.WAL}

    # L2 敏感级 + 增量
    enc_level, _ = get_table_encryption(table_name)
    if enc_level == EncryptionLevel.L2_SENSITIVE:
        base['incremental'] = BackupStrategy.INCREMENTAL

    if table_name in BACKUP_CONFIG['incremental_tables']:
        base['incremental'] = BackupStrategy.INCREMENTAL

    return base


# ══════════════════════════════════════════════════════════════════
# §3 AI 专员全程跟踪 — 关键表写入强制进 evolution_log
# ══════════════════════════════════════════════════════════════════

# 这些表的 INSERT/UPDATE/DELETE 必须同步写入 mt_center_evolution_log
# 格式: table_name -> event_prefix
WRITE_AUDIT_TABLES = {
    # 金融交易类
    'mt_trade_log': 'TRADE_EXECUTE',
    'mt_sandbox_portfolio': 'PORTFOLIO_CHANGE',
    'mt_sandbox_trades': 'SANDBOX_EXECUTE',
    'mt_sandbox_signals': 'SANDBOX_SIGNAL',
    'mt_sandbox_snapshots': 'SANDBOX_SNAPSHOT',

    # 策略/风控类
    'mt_center_knowledge_points': 'KNOWLEDGE_UPDATE',
    'mt_center_knowledge_digest': 'KNOWLEDGE_DIGEST',
    'mt_center_direction_pool': 'DIRECTION_POOL',
    'mt_center_direction_execution': 'DIRECTION_EXECUTE',
    'mt_strategy_risk_map': 'RISK_MAP',

    # 协同/团队类
    'mt_lab_task_hall': 'HALL_TASK',
    'mt_lab_collab': 'LAB_COLLAB',
    'mt_lab_hr_log': 'HR_LOG',
    'mt_ai_auto_hire_log': 'HIRE_LOG',

    # 加密/安全类
    'mt_crypto_keys': 'CRYPTO_KEY',
    'mt_sa_dual_key_status': 'DUAL_KEY',
    'mt_security_actions': 'SECURITY_ACTION',

    # 系统类
    'mt_center_evolution_log': 'EVOLUTION',  # 自循环, 不强制
    'mt_center_self_check': 'SELF_CHECK',
    'mt_daemon_registry': 'DAEMON',
}


def should_audit_write(table_name: str) -> bool:
    """查表是否需要写入审计"""
    return table_name in WRITE_AUDIT_TABLES and table_name != 'mt_center_evolution_log'


def build_audit_detail(table_name: str, action: str, row_data: dict,
                       actor: str = 'unknown', extra: str = '') -> str:
    """构建审计详情 JSON"""
    detail = {
        'table': table_name,
        'action': action,          # INSERT / UPDATE / DELETE
        'actor': actor,            # user / daemon / AI / flask
        'ts': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'flow_id': 'flow_security_manifest_20261108',
        'extra': extra,
    }
    # 限制 data 大小, 避免 evolution_log 爆炸
    data = json.dumps(row_data, ensure_ascii=False, default=str)
    detail['row_data_b64'] = data[:500]  # 截断
    return json.dumps(detail, ensure_ascii=False)


def audit_write_to_db(db_path: str, table_name: str, action: str,
                      row_data: dict, actor: str = 'unknown',
                      center_name: str = 'gobelin_trading',
                      extra: str = '') -> bool:
    """执行审计写入 (直接操作 DB) — 供 AI 专员 / flask blueprint 调用"""
    if not should_audit_write(table_name):
        return False

    event_prefix = WRITE_AUDIT_TABLES.get(table_name, 'AUDIT_WRITE')
    detail = build_audit_detail(table_name, action, row_data, actor, extra)

    try:
        conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
            (center_name, f"{event_prefix}_{action}", detail)
        )
        conn.close()
        return True
    except Exception as e:
        print(f"[audit_write] err: {e}", flush=True)
        return False


# ══════════════════════════════════════════════════════════════════
# §4 专门通道不可截流 — Flask blueprint 内部通道保护
# ══════════════════════════════════════════════════════════════════

# 内部通道 header 名称 + 期望值
INTERNAL_CHANNEL_HEADER = 'X-MTSCOS-SECRET-CHANNEL'
INTERNAL_CHANNEL_VALUE = 'andromeda-internal-v1-gobelin'

# 需要保护的 blueprint url_prefix
PROTECTED_BLUEPRINTS = [
    '/sa/trading/',           # 仙女座操盘系统 (三重锁)
    '/sa/ai/',                # AI 服务内部通道
    '/sa/security/',          # 安全通道
    '/internal/',             # 内部调度
]


def require_internal_header(request) -> tuple[bool, str]:
    """
    Flask before_request 检查: 内部通道必须携带 X-MTSCOS-SECRET-CHANNEL header.
    返回 (ok, reason). ok=False 表示应该返回 403.
    """
    path = request.path or ''
    is_protected = any(path.startswith(p) for p in PROTECTED_BLUEPRINTS)

    if not is_protected:
        return True, 'public route'

    channel = request.headers.get(INTERNAL_CHANNEL_HEADER, '')
    if channel != INTERNAL_CHANNEL_VALUE:
        return False, f'missing {INTERNAL_CHANNEL_HEADER} header'

    return True, 'ok'


def require_ip_whitelist(request, allowed_ips: set[str]) -> bool:
    """IP 白名单检查"""
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    return client_ip in allowed_ips or client_ip.startswith('127.') or client_ip.startswith('10.')


# ══════════════════════════════════════════════════════════════════
# Manifest 摘要 (供 Flask / CLI 打印)
# ══════════════════════════════════════════════════════════════════

def manifest_summary() -> str:
    """打印完整安全 manifest 摘要"""
    lines = [
        "═" * 60,
        "  本地优先安全架构 — Local Security Manifest",
        "═" * 60,
        f"\n§1 加密分级: 共 {len(MT_TABLE_ENCRYPTION)} 张表",
    ]

    for level in [EncryptionLevel.L3_CORE, EncryptionLevel.L2_SENSITIVE, EncryptionLevel.L1_PUBLIC]:
        tables = list_by_level(level)
        if tables:
            lines.append(f"  {level} ({'核心级' if level == 'L3' else '敏感级' if level == 'L2' else '公开级'}):")
            for t, reason in tables:
                lines.append(f"    · {t:45s} → {reason}")

    lines.append(f"\n§2 备份策略:")
    for key, val in BACKUP_CONFIG.items():
        if isinstance(val, dict):
            lines.append(f"  {key}: {json.dumps(val, ensure_ascii=False)[:120]}")
        elif isinstance(val, list):
            lines.append(f"  {key}: {len(val)} 张表")
        else:
            lines.append(f"  {key}: {val}")

    lines.append(f"\n§3 AI 专员全程跟踪: {len(WRITE_AUDIT_TABLES)} 张表强制写 evolution_log")
    for t, evt in WRITE_AUDIT_TABLES.items():
        lines.append(f"    · {t:45s} → event={evt}_INSERT/UPDATE/DELETE")

    lines.append(f"\n§4 专门通道不可截流:")
    lines.append(f"  header: {INTERNAL_CHANNEL_HEADER}: {INTERNAL_CHANNEL_VALUE}")
    lines.append(f"  protected prefixes:")
    for bp in PROTECTED_BLUEPRINTS:
        lines.append(f"    · {bp}")

    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='本地优先安全架构 — Manifest 查看器')
    parser.add_argument('--action', default='summary',
                        choices=['summary', 'test-audit', 'test-encryption'],
                        help='summary / test-audit / test-encryption')
    parser.add_argument('--table', default='', help='指定表名')
    args = parser.parse_args()

    if args.action == 'summary':
        print(manifest_summary())

    elif args.action == 'test-encryption':
        if args.table:
            lvl, reason = get_table_encryption(args.table)
            print(f"[{args.table}] → {lvl} ({reason})")
            print(f"  backup: {get_backup_strategy(args.table)}")
        else:
            print("请指定 --table <表名>")

    elif args.action == 'test-audit':
        # 测试 audit_write_to_db
        db_path = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
        test_data = {'test_key': 'test_value', 'amount': 100.0}
        ok = audit_write_to_db(
            db_path, 'mt_trade_log', 'INSERT', test_data,
            actor='security_manifest_cli',
            extra='test_audit_manifest'
        )
        print(f"audit_write → {'OK' if ok else 'FAIL'}")
        if not ok:
            print(f"  注: mt_center_evolution_log 表需要存在")
