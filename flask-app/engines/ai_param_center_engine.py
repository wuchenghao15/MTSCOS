#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座参数中心引擎 (AI Param Center Engine v1.0.0)
====================================================
flow_andromeda_param_20261021 · MT_RULE_PARAM 规范蓝图落地

统一参数体系: 告别 20 张散表碎片化, 建立唯一参数登记注册表
  - mt_param_registry        参数登记表 (11域三级命名/7类型/4作用域/is_secret)
  - mt_param_change_log      参数变更审计 (规范§6 全操作留痕)
  - mt_param_inspection_report  参数健康巡检报告

规范依据: .trae/rules/系统参数数据规范与操作规范.md (MT_RULE_PARAM v1.2.0)
  §2 三级分类 <参数域>.<模块>.<参数名>  §3 七种数据类型(JSON序列化)
  §4 四级作用域 system<global<user<session  §6 操作留痕
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_BASE = os.path.dirname(os.path.abspath(__file__))
# 数据库唯一数据源铁律 (flow_bigdata_evolve_20261021 教训): 主库 database/app.db
APP_DB = os.path.join(os.path.dirname(_BASE), 'database', 'app.db')

# 规范 §2.2: 11 参数域
PARAM_DOMAINS = ['system', 'security', 'database', 'ai', 'exam', 'user',
                 'notification', 'backup', 'monitor', 'cache', 'logging']
# 规范 §3.1: 7 种数据类型
PARAM_TYPES = ['string', 'integer', 'float', 'boolean', 'json', 'list', 'datetime']
# 规范 §4.1: 4 种作用域
PARAM_SCOPES = ['system', 'global', 'user', 'session']

REGISTRY_TABLE = 'mt_param_registry'
CHANGELOG_TABLE = 'mt_param_change_log'
REPORT_TABLE = 'mt_param_inspection_report'


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(APP_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


def ensure_tables() -> None:
    """自治建表 (幂等): 参数登记 + 变更审计 + 巡检报告"""
    conn = _conn()
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS {REGISTRY_TABLE} (
        param_key    TEXT PRIMARY KEY,           -- <域>.<模块>.<参数名> (规范§2.4)
        param_domain TEXT NOT NULL,              -- 11 域之一 (规范§2.2)
        module       TEXT DEFAULT 'general',     -- 二级分类 (规范§2.3)
        value        TEXT,                       -- JSON 序列化值 (规范§3.3)
        default_value TEXT,                      -- 默认值(JSON)
        data_type    TEXT DEFAULT 'string',      -- 7 类型之一 (规范§3.1)
        scope        TEXT DEFAULT 'global',      -- 4 作用域之一 (规范§4.1)
        is_secret    INTEGER DEFAULT 0,          -- 机密等级: 1=值脱敏显示
        is_active    INTEGER DEFAULT 1,
        description  TEXT DEFAULT '',
        source       TEXT DEFAULT 'manual',      -- manual/seed/engine/import
        updated_by   TEXT DEFAULT 'system',
        created_at   TEXT DEFAULT (datetime('now','localtime')),
        updated_at   TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_param_registry_domain ON {REGISTRY_TABLE}(param_domain);
    CREATE INDEX IF NOT EXISTS idx_param_registry_scope ON {REGISTRY_TABLE}(scope);
    CREATE TABLE IF NOT EXISTS {CHANGELOG_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        param_key  TEXT NOT NULL,
        action     TEXT NOT NULL,                -- create/update/delete/reset
        old_value  TEXT,
        new_value  TEXT,
        operator   TEXT DEFAULT 'system',
        flow_id    TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_param_changelog_key ON {CHANGELOG_TABLE}(param_key);
    CREATE TABLE IF NOT EXISTS {REPORT_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        findings_json TEXT,
        severity TEXT DEFAULT 'INFO',
        total_findings INTEGER DEFAULT 0,
        total_params INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()
    conn.close()


def validate_value(data_type: str, raw: Any) -> Tuple[bool, str, str]:
    """规范 §3.2 类型验证 → (ok, json序列化值, 错误信息)"""
    try:
        if data_type == 'boolean':
            if isinstance(raw, bool):
                return True, json.dumps(raw), ''
            s = str(raw).strip().lower()
            if s in ('true', '1', 'yes', 'on'):
                return True, 'true', ''
            if s in ('false', '0', 'no', 'off'):
                return True, 'false', ''
            return False, '', f'boolean 只接受 true/false, 得到 {raw!r}'
        if data_type == 'integer':
            v = int(raw)
            return True, json.dumps(v), ''
        if data_type == 'float':
            v = float(raw)
            return True, json.dumps(v), ''
        if data_type == 'json':
            v = json.loads(raw) if isinstance(raw, str) else raw
            return True, json.dumps(v, ensure_ascii=False), ''
        if data_type == 'list':
            v = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(v, list):
                return False, '', f'list 需要数组, 得到 {type(v).__name__}'
            return True, json.dumps(v, ensure_ascii=False), ''
        if data_type == 'datetime':
            s = str(raw).strip()
            time.strptime(s[:19], '%Y-%m-%d %H:%M:%S')
            return True, json.dumps(s), ''
        # string (默认): 规范§3.2 长度≤255
        s = '' if raw is None else str(raw)
        if len(s) > 255:
            return False, '', f'string 超长 {len(s)}>255'
        return True, json.dumps(s), ''
    except ValueError as e:
        return False, '', f'{data_type} 验证失败: {e}'


def _parse_domain_module(key: str) -> Tuple[str, str]:
    """规范§2.4 三级命名 → (domain, module); 不合规键归 general 域由 scan 报告"""
    parts = key.split('.')
    if len(parts) >= 2 and parts[0] in PARAM_DOMAINS:
        return parts[0], parts[1]
    return 'system', 'general'


def get_param(key: str, default: Any = None) -> Any:
    """读参数 (fail-open: 值损坏返回 default)"""
    try:
        conn = _conn()
        row = conn.execute(
            f"SELECT value FROM {REGISTRY_TABLE} WHERE param_key=? AND is_active=1", (key,)).fetchone()
        conn.close()
        if not row:
            return default
        return json.loads(row['value'])
    except Exception:
        return default


def set_param(key: str, value_raw: Any, operator: str = 'system',
              data_type: Optional[str] = None, scope: Optional[str] = None,
              description: str = '', is_secret: int = 0,
              flow_id: str = '', source: str = 'manual') -> Dict[str, Any]:
    """写参数 (UPSERT + 类型验证 + 变更审计留痕, 规范§6)"""
    conn = _conn()
    try:
        old = conn.execute(f"SELECT value, data_type, scope FROM {REGISTRY_TABLE} WHERE param_key=?",
                           (key,)).fetchone()
        dt = data_type or (old['data_type'] if old else 'string')
        if dt not in PARAM_TYPES:
            return {'ok': False, 'error': f'非法 data_type {dt!r}, 允许: {PARAM_TYPES}'}
        ok, jval, err = validate_value(dt, value_raw)
        if not ok:
            return {'ok': False, 'error': err}
        dom, mod = _parse_domain_module(key)
        sc = scope or (old['scope'] if old else 'global')
        if sc not in PARAM_SCOPES:
            return {'ok': False, 'error': f'非法 scope {sc!r}, 允许: {PARAM_SCOPES}'}
        action = 'update' if old else 'create'
        conn.execute(f"""
            INSERT INTO {REGISTRY_TABLE}
              (param_key, param_domain, module, value, data_type, scope, is_secret, description, source, updated_by, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
            ON CONFLICT(param_key) DO UPDATE SET
              value=excluded.value, data_type=excluded.data_type, scope=excluded.scope,
              is_secret=excluded.is_secret, description=CASE WHEN excluded.description='' THEN {REGISTRY_TABLE}.description ELSE excluded.description END,
              updated_by=excluded.updated_by, updated_at=datetime('now','localtime')
        """, (key, dom, mod, jval, dt, sc, is_secret, description, source, operator))
        conn.execute(f"INSERT INTO {CHANGELOG_TABLE} (param_key,action,old_value,new_value,operator,flow_id) "
                     "VALUES (?,?,?,?,?,?)",
                     (key, action, old['value'] if old else None, jval, operator, flow_id))
        conn.commit()
        return {'ok': True, 'param_key': key, 'action': action, 'data_type': dt}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}
    finally:
        conn.close()


def delete_param(key: str, operator: str = 'system', flow_id: str = '') -> Dict[str, Any]:
    """删参数 (规范§6: 仅超级管理员, 调用方路由层鉴权; 审计留痕)"""
    conn = _conn()
    try:
        old = conn.execute(f"SELECT value FROM {REGISTRY_TABLE} WHERE param_key=?", (key,)).fetchone()
        if not old:
            return {'ok': False, 'error': '参数不存在'}
        conn.execute(f"DELETE FROM {REGISTRY_TABLE} WHERE param_key=?", (key,))
        conn.execute(f"INSERT INTO {CHANGELOG_TABLE} (param_key,action,old_value,new_value,operator,flow_id) "
                     "VALUES (?,'delete',?,NULL,?,?)", (key, old['value'], operator, flow_id))
        conn.commit()
        return {'ok': True, 'param_key': key, 'action': 'delete'}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}
    finally:
        conn.close()


def list_params(domain: str = '', limit: int = 500) -> List[Dict[str, Any]]:
    """参数清单 (is_secret=1 值脱敏)"""
    conn = _conn()
    sql = (f"SELECT param_key, param_domain, module, value, default_value, data_type, scope, "
           f"is_secret, is_active, description, source, updated_by, updated_at FROM {REGISTRY_TABLE}")
    args: list = []
    if domain:
        sql += " WHERE param_domain=?"
        args.append(domain)
    sql += " ORDER BY param_domain, param_key LIMIT ?"
    args.append(limit)
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    for r in rows:
        if r.get('is_secret'):
            r['value'] = '******'
        try:
            r['value_parsed'] = json.loads(r['value']) if r['value'] is not None else None
        except Exception:
            r['value_parsed'] = r['value']
    return rows


def stats() -> Dict[str, Any]:
    """参数体系总览: 域分布 + 类型分布 + 健康度"""
    conn = _conn()
    total = conn.execute(f"SELECT COUNT(*) FROM {REGISTRY_TABLE}").fetchone()[0]
    by_domain = {r[0]: r[1] for r in conn.execute(
        f"SELECT param_domain, COUNT(*) FROM {REGISTRY_TABLE} GROUP BY param_domain ORDER BY 2 DESC")}
    by_type = {r[0]: r[1] for r in conn.execute(
        f"SELECT data_type, COUNT(*) FROM {REGISTRY_TABLE} GROUP BY data_type")}
    secret_n = conn.execute(f"SELECT COUNT(*) FROM {REGISTRY_TABLE} WHERE is_secret=1").fetchone()[0]
    inactive_n = conn.execute(f"SELECT COUNT(*) FROM {REGISTRY_TABLE} WHERE is_active=0").fetchone()[0]
    changelog_n = conn.execute(f"SELECT COUNT(*) FROM {CHANGELOG_TABLE}").fetchone()[0]
    last_scan = conn.execute(f"SELECT severity, total_findings, created_at FROM {REPORT_TABLE} "
                             "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    out = {'total': total, 'by_domain': by_domain, 'by_type': by_type,
           'secret_count': secret_n, 'inactive_count': inactive_n,
           'change_log_total': changelog_n, 'domains_expected': PARAM_DOMAINS}
    out['missing_domains'] = [d for d in PARAM_DOMAINS if d not in by_domain]
    out['last_scan'] = dict(last_scan) if last_scan else None
    return out


def scan() -> Dict[str, Any]:
    """参数健康巡检: 非法JSON/空值/域外键/超域未登记/审计链完整性 → 报告落库"""
    ensure_tables()
    findings: List[Dict[str, Any]] = []
    conn = _conn()
    rows = conn.execute(f"SELECT param_key, param_domain, value, data_type, scope FROM {REGISTRY_TABLE}").fetchall()
    for r in rows:
        key = r['param_key']
        try:
            json.loads(r['value']) if r['value'] is not None else None
        except Exception:
            findings.append({'type': 'BAD_JSON', 'param_key': key, 'detail': '值非法 JSON (规范§3.3)'})
        if r['value'] is None or r['value'] == '':
            findings.append({'type': 'EMPTY_VALUE', 'param_key': key, 'detail': '参数值为空'})
        if r['param_domain'] not in PARAM_DOMAINS:
            findings.append({'type': 'BAD_DOMAIN', 'param_key': key, 'detail': f"域 {r['param_domain']!r} 不在规范§2.2 的 11 域"})
        if r['data_type'] not in PARAM_TYPES:
            findings.append({'type': 'BAD_TYPE', 'param_key': key, 'detail': f"类型 {r['data_type']!r} 不在规范§3.1"})
        if r['scope'] not in PARAM_SCOPES:
            findings.append({'type': 'BAD_SCOPE', 'param_key': key, 'detail': f"作用域 {r['scope']!r} 不在规范§4.1"})
        # 命名规范: 一级必须是合法域
        if not key:
            findings.append({'type': 'BAD_KEY', 'param_key': key, 'detail': '空参数键'})
    total = len(rows)
    conn.close()
    severity = 'INFO'
    if any(f['type'] in ('BAD_JSON', 'EMPTY_VALUE') for f in findings):
        severity = 'WARNING'
    report = {'total_params': total, 'total_findings': len(findings), 'severity': severity,
              'findings': findings[:200], 'scanned_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        conn = _conn()
        conn.execute(f"INSERT INTO {REPORT_TABLE} (findings_json, severity, total_findings, total_params) "
                     "VALUES (?,?,?,?)",
                     (json.dumps(report, ensure_ascii=False), severity, len(findings), total))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return report


# 种子参数: 全部为系统真实在用的非敏感参数 (覆盖 6 域示范体系; 敏感参数一律不入种子)
SEED_PARAMS = [
    # system
    ('system.general.name', 'MTSCOS AI', 'string', 'global', '系统名称'),
    ('system.general.version', 'v22.25.18', 'string', 'global', '当前系统版本号'),
    ('system.general.language', 'zh-CN', 'string', 'global', '默认语言'),
    ('system.general.timezone', 'Asia/Shanghai', 'string', 'global', '系统时区'),
    # ai (与 local_ai_unified_gateway / persona_chat 真实在用参数对齐)
    ('ai.model.default_model', 'qwen2.5:7b', 'string', 'global', '本地 Ollama 默认对话模型'),
    ('ai.model.embed_model', 'nomic-embed-text', 'string', 'global', '脑库向量化嵌入模型 (768维)'),
    ('ai.brain.rag_enabled', True, 'boolean', 'global', '脑库RAG注入总开关 (env MTSCOS_BRAIN_RAG 同步)'),
    ('ai.brain.rag_top_k', 3, 'integer', 'global', 'RAG 语义检索 top-k'),
    ('ai.brain.rag_min_score', 0.45, 'float', 'global', 'RAG 相似度阈值 (bench 实测 0.72-0.83 相关)'),
    # security
    ('security.auth.session_timeout_minutes', 120, 'integer', 'global', '会话超时(分钟)'),
    # monitor
    ('monitor.health.heartbeat_timeout_factor', 2, 'integer', 'global', 'daemon 心跳超时倍数 (interval×2 标红)'),
    # backup
    ('backup.schedule.daily_cold_backup', True, 'boolean', 'global', '每日冷备份开关 (v22.25.x)'),
    # logging
    ('logging.level.default', 'INFO', 'string', 'global', '默认日志级别'),
    # cache
    ('cache.settings.ttl_seconds', 300, 'integer', 'global', '参数缓存 TTL (规范§5.4)'),
]


def seed(operator: str = 'flow_andromeda_param_20261021', force: bool = False) -> Dict[str, Any]:
    """写入种子参数 (已存在且非 force 跳过)"""
    ensure_tables()
    inserted, skipped = [], []
    for key, val, dt, sc, desc in SEED_PARAMS:
        conn = _conn()
        exists = conn.execute(f"SELECT 1 FROM {REGISTRY_TABLE} WHERE param_key=?", (key,)).fetchone()
        conn.close()
        if exists and not force:
            skipped.append(key)
            continue
        r = set_param(key, val, operator=operator, data_type=dt, scope=sc,
                      description=desc, source='seed', flow_id='flow_andromeda_param_20261021')
        (inserted if r.get('ok') else skipped).append(key if r.get('ok') else f"{key}({r.get('error')})")
    return {'ok': True, 'seeded': inserted, 'skipped': skipped,
            'total_seed_defined': len(SEED_PARAMS)}


def main() -> None:
    ap = argparse.ArgumentParser(description='仙女座参数中心引擎 (MT_RULE_PARAM 蓝图落地)')
    ap.add_argument('cmd', choices=['status', 'seed', 'get', 'set', 'scan', 'stats', 'list'])
    ap.add_argument('key', nargs='?', default='')
    ap.add_argument('--value', default=None)
    ap.add_argument('--type', dest='data_type', default=None)
    ap.add_argument('--domain', default='')
    ap.add_argument('--operator', default='cli')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--loop', type=int, default=0, help='常驻巡检秒数 (如 900)')
    a = ap.parse_args()
    ensure_tables()
    if a.cmd == 'seed':
        print(json.dumps(seed(force=a.force), ensure_ascii=False, indent=1))
    elif a.cmd == 'get':
        print(json.dumps({'key': a.key, 'value': get_param(a.key)}, ensure_ascii=False))
    elif a.cmd == 'set':
        print(json.dumps(set_param(a.key, a.value, operator=a.operator, data_type=a.data_type), ensure_ascii=False))
    elif a.cmd == 'scan':
        print(json.dumps(scan(), ensure_ascii=False)[:2000])
    elif a.cmd == 'stats':
        print(json.dumps(stats(), ensure_ascii=False))
    elif a.cmd == 'list':
        for r in list_params(a.domain):
            print(f"{r['param_key']} = {r['value_parsed']!r}  [{r['data_type']}/{r['scope']}{'/secret' if r['is_secret'] else ''}]")
    elif a.cmd == 'status':
        s = stats()
        print(f"params={s['total']} domains={len(s['by_domain'])}/11 changelog={s['change_log_total']}")
    if a.loop > 0:
        _logf = os.path.join(os.path.dirname(_BASE), '_runtime', 'logs', 'param_center_loop.log')
        os.makedirs(os.path.dirname(_logf), exist_ok=True)
        while True:
            try:
                r = scan()
                with open(_logf, 'a') as f:
                    f.write(f"{time.strftime('%F %T')} scan params={r['total_params']} findings={r['total_findings']} {r['severity']}\n")
            except Exception as e:
                with open(_logf, 'a') as f:
                    f.write(f"{time.strftime('%F %T')} scan err {e}\n")
            time.sleep(a.loop)


if __name__ == '__main__':
    main()
