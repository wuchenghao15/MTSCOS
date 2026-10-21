#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双向增量同步 (Bidirectional Sync over SSH)
==========================================
flow_andromeda_sync_20261021 · 本机 ↔ Mac mini (Tailscale 100.106.220.96 / LAN 192.168.31.9)

设计:
  - 不依赖 Flask /api/sync (Mini 侧守护反复拉起, 路由注册不稳定)
  - SSH + 远端 python3 -c (base64 内联, 规避 zsh 多行/引号破坏)
  - 白名单表按主键对齐; 冲突以 updated_at 新者为准; 无 updated_at 则仅在缺失时补
  - WAL + busy_timeout, 分批 500

用法:
  python3 engines/bidirectional_sync.py --dry-run --tables mt_rule_changelog
  python3 engines/bidirectional_sync.py
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sqlite3
import subprocess
import time

_BASE = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB = os.path.join(os.path.dirname(_BASE), 'database', 'app.db')
REMOTE_HOST = os.environ.get('MTSCOS_SYNC_HOST', 'wuchenghao@100.106.220.96')
REMOTE_DB = os.environ.get('MTSCOS_SYNC_DB', '~/MTSCOS_AI_Project/flask-app/database/app.db')
BATCH = 500

SYNC_TABLES = [
    ('mt_andromeda_knowledge_base', 'k_id'), ('mt_daemon_registry', 'daemon_name'),
    ('mt_upgrade_reports', 'report_id'), ('mt_upgrade_overviews', 'overview_id'),
    ('mt_andromeda_contributor_persona', 'persona_id'), ('mt_iron_rule_violations', 'viol_id'),
    ('mt_iceberg_consciousness_runs', 'id'), ('mt_iceberg_consciousness_optimizations', 'id'),
    ('mt_iceberg_direction_registry', 'id'), ('mt_iceberg_new_direction_registry', 'id'),
    ('mt_iceberg_upgrade_execution', 'exec_id'), ('mt_iceberg_threshold_configs', 'id'),
    ('mt_iceberg_binding_override', 'id'), ('mt_iceberg_admin_audit', 'id'),
    ('mt_iceberg_evolution_archive', 'id'), ('mt_ai_employee_profiles', 'id'),
    ('mt_ai_employee_social_graph', 'id'), ('mt_ai_employee_consultations', 'id'),
    ('mt_ai_employee_contributions', 'id'), ('mt_ai_employee_empowerment_log', 'id'),
    ('mt_ai_brain_feed_log', 'feed_id'), ('mt_aurora_skills', 'id'),
    ('mt_rule_changelog', 'id'),
    ('mt_error_thinking_chain', 'chain_id'),  # 本机缺表, Mini 恢复后 --create-missing 复制 schema
    ('mt_pipeline_execution_log', 'exec_id'),
    ('mt_release_sessions', 'id'), ('mt_approval_requests', 'id'), ('mt_auto_empower_log', 'id'),
]

_HEAD = """
import sqlite3, json, sys, os
db = os.path.expanduser(__DB__)
table = __TABLE__
pk = __PK__
conn = sqlite3.connect(db, timeout=30)
conn.execute('PRAGMA busy_timeout=8000')
cur = conn.cursor()
def cols():
    try:
        return [c[1] for c in cur.execute('PRAGMA table_info(%s)' % table).fetchall()]
    except Exception:
        return []
def pkcol():
    try:
        for c in cur.execute('PRAGMA table_info(%s)' % table).fetchall():
            if c[5]:
                return c[1]
    except Exception:
        pass
    return None
def pktype(col):
    try:
        for c in cur.execute('PRAGMA table_info(%s)' % table).fetchall():
            if c[1] == col:
                return 'i' if 'INT' in (c[2] or '').upper() else 't'
    except Exception:
        pass
    return 'i'
"""

_T_INFO = _HEAD + """
c = cols()
try:
    n = cur.execute('SELECT COUNT(*) FROM %s' % table).fetchone()[0]
except Exception:
    n = -1
_p = pkcol()
print(json.dumps({'ok': bool(c), 'cols': c, 'count': n, 'pkcol': _p,
                  'pktype': pktype(_p) if _p else 'i'}))
"""

_T_DDL = _HEAD + """
r = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
idx = [x[0] for x in cur.execute(
    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
    (table,)).fetchall()]
print(json.dumps({'ok': bool(r), 'ddl': r[0] if r else None, 'idx': idx}))
"""

_T_DUMP = _HEAD + """
after = __AFTER__
limit = __LIMIT__
mode = __MODE__
c = cols()
if not c:
    print(json.dumps({'ok': False, 'error': 'no table'}))
else:
    try:
        if mode == 'i':
            q = ('SELECT * FROM %s WHERE CAST(%s AS INTEGER) > ? '
                 'ORDER BY CAST(%s AS INTEGER) LIMIT ?' % (table, pk, pk))
        else:
            q = 'SELECT * FROM %s WHERE %s > ? ORDER BY %s LIMIT ?' % (table, pk, pk)
        rows = cur.execute(q, (after, limit)).fetchall()
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}))
        sys.exit(0)
    print(json.dumps({'ok': True, 'cols': c, 'rows': [list(r) for r in rows]}, ensure_ascii=False))
"""

_T_EXIST = _HEAD + """
keys = json.loads(sys.stdin.read() or '[]')
c = cols()
out = {}
if keys and c:
    has_u = 'updated_at' in c
    ph = ','.join(['?'] * len(keys))
    if has_u:
        q = 'SELECT %s, updated_at FROM %s WHERE %s IN (%s)' % (pk, table, pk, ph)
    else:
        q = 'SELECT %s FROM %s WHERE %s IN (%s)' % (pk, table, pk, ph)
    try:
        for r in cur.execute(q, keys):
            out[str(r[0])] = str(r[1]) if has_u else ''
    except Exception:
        out = {}
print(json.dumps(out))
"""

_T_UPSERT = _HEAD + """
d = json.loads(sys.stdin.read() or '{}')
c = cols()
use = [x for x in d.get('cols', []) if x in c]
if not use or not d.get('rows'):
    print(json.dumps({'ok': False, 'error': 'no common cols'}))
else:
    ph = ','.join(['?'] * len(use))
    sql = 'INSERT OR REPLACE INTO %s (%s) VALUES (%s)' % (table, ','.join(use), ph)
    ok = 0
    for r in d['rows']:
        try:
            cur.execute(sql, r)
            ok += 1
        except Exception:
            pass
    conn.commit()
    print(json.dumps({'ok': True, 'applied': ok}))
"""


def _remote(tpl: str, table: str, pk: str, after=0, stdin: str = None, mode: str = 'i') -> dict:
    code = (tpl.replace('__DB__', repr(REMOTE_DB)).replace('__TABLE__', repr(table))
              .replace('__PK__', repr(pk)).replace('__MODE__', repr(mode))
              .replace('__AFTER__', repr(after)).replace('__LIMIT__', str(BATCH)))
    b64 = base64.b64encode(code.encode('utf-8')).decode()
    cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
           REMOTE_HOST, f'python3 -c "import base64;exec(base64.b64decode(\'{b64}\').decode(\'utf-8\'))"']
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'ssh timeout'}
    out = (p.stdout or '').strip()
    if not out:
        return {'ok': False, 'error': f'empty stdout / stderr={p.stderr[:200]}'}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {'ok': False, 'error': f'bad json {out[:160]}'}


def _local_conn():
    c = sqlite3.connect(LOCAL_DB, timeout=30)
    c.execute('PRAGMA busy_timeout=8000')
    return c


def _local_meta(table: str):
    c = _local_conn()
    try:
        info = c.execute(f'PRAGMA table_info({table})').fetchall()
        cols = [r[1] for r in info]
        pk = next((r[1] for r in info if r[5]), None)
        types = {r[1]: (r[2] or '') for r in info}
        return cols, pk, types
    except Exception:
        return [], None, {}
    finally:
        c.close()


def _pk_mode(pk: str, types: dict) -> str:
    return 'i' if 'INT' in (types.get(pk) or '').upper() else 't'


def _resolve_pk(hint: str, lcols: list, ri: dict, rcols: list):
    for cand in (hint, ri.get('pkcol')):
        if cand and cand in lcols and cand in rcols:
            return cand
    for cand in (ri.get('pkcol'),):
        if cand and cand in rcols:
            return cand
    return None


def _dump_local(table: str, pk: str, after, mode: str = 'i') -> list:
    c = _local_conn()
    try:
        if mode == 'i':
            return c.execute(f'SELECT * FROM {table} WHERE CAST({pk} AS INTEGER) > ? '
                             f'ORDER BY CAST({pk} AS INTEGER) LIMIT ?', (after, BATCH)).fetchall()
        return c.execute(f'SELECT * FROM {table} WHERE {pk} > ? ORDER BY {pk} LIMIT ?',
                         (after, BATCH)).fetchall()
    finally:
        c.close()


def _next_cursor(cur, val, mode: str):
    if mode == 'i':
        try:
            return max(cur, int(val or 0))
        except Exception:
            return cur
    return max(cur, str(val or ''))


def pull_table(table: str, pk: str, dry: bool, create_missing: bool = False) -> dict:
    ri = _remote(_T_INFO, table, pk)
    if not ri.get('cols'):
        return {'skip': f"远端不可读: {ri.get('error', '')}"}
    lcols, _lpk, ltypes = _local_meta(table)
    created = False
    if not lcols:
        if not create_missing:
            return {'skip': '本机缺表 (加 --create-missing 复制远端 schema)'}
        d = _remote(_T_DDL, table, pk)
        if not d.get('ddl'):
            return {'skip': '远端无 DDL'}
        if dry:
            return {'would_create': True, 'remote_count': ri.get('count')}
        c = _local_conn()
        try:
            c.execute(d['ddl'])
            for s in d.get('idx') or []:
                try:
                    c.execute(s)
                except Exception:
                    pass
            c.commit()
        finally:
            c.close()
        lcols, _lpk, ltypes = _local_meta(table)
        created = True
        if not lcols:
            return {'error': '建表后仍不可读'}
    rpk = _resolve_pk(pk, lcols, ri, ri['cols'])
    if not rpk:
        return {'skip': '无可用主键'}
    pk = rpk
    mode = _pk_mode(pk, ltypes)
    use = [x for x in ri['cols'] if x in lcols]
    if not use:
        return {'skip': '无公共列'}
    idx = {c: i for i, c in enumerate(ri['cols'])}
    pki = idx.get(pk)
    sel = ','.join(use)
    applied, scanned, after = 0, 0, (0 if mode == 'i' else '')
    conn = _local_conn()
    try:
        while True:
            d = _remote(_T_DUMP, table, pk, after, mode=mode)
            if d.get('ok') is False and 'rows' not in d:
                return {'error': d.get('error')}
            rows = d.get('rows') or []
            if not rows:
                break
            for r in rows:
                scanned += 1
                if pki is not None:
                    after = _next_cursor(after, r[pki], mode)
                if pki is None:
                    continue
                exists = conn.execute(f'SELECT {sel} FROM {table} WHERE {pk}=?', (r[pki],)).fetchone()
                take = exists is None
                if not take and 'updated_at' in ri['cols']:
                    lv = str(exists[use.index('updated_at')] or '')
                    rv = str(r[idx['updated_at']] or '')
                    take = rv > lv
                if take:
                    if not dry:
                        conn.execute(
                            f"INSERT OR REPLACE INTO {table} ({sel}) VALUES ({','.join(['?'] * len(use))})",
                            [r[idx[c]] for c in use])
                    applied += 1
            if not dry:
                conn.commit()
            if len(rows) < BATCH:
                break
        out = {'scanned': scanned, 'applied': applied}
        if created:
            out['created'] = True
        return out
    except Exception as e:
        return {'error': str(e)[:200]}
    finally:
        conn.close()


def push_table(table: str, pk: str, dry: bool) -> dict:
    ri = _remote(_T_INFO, table, pk)
    if not ri.get('cols'):
        return {'skip': f"远端不可读: {ri.get('error', '')}"}
    lcols, lpk, ltypes = _local_meta(table)
    if not lcols:
        return {'skip': '本机缺表 (先 pull --create-missing 建表)'}
    rpk = _resolve_pk(pk, lcols, ri, ri['cols'])
    if not rpk:
        return {'skip': '无可用主键'}
    pk = rpk
    mode = _pk_mode(pk, ltypes)
    use = [x for x in lcols if x in ri['cols']]
    if not use:
        return {'skip': '无公共列'}
    pki = lcols.index(pk)
    scanned, applied, after = 0, 0, (0 if mode == 'i' else '')
    while True:
        rows = _dump_local(table, pk, after, mode)
        if not rows:
            break
        keys = []
        for r in rows:
            scanned += 1
            after = _next_cursor(after, r[pki], mode)
            keys.append(r[pki])
        if dry:
            applied += len(rows)
        else:
            rex = _remote(_T_EXIST, table, pk, stdin=json.dumps(keys, ensure_ascii=False))
            if not isinstance(rex, dict):
                return {'error': 'exist query failed'}
            to_push = []
            for r in rows:
                key = str(r[pki])
                if key not in rex:
                    to_push.append(list(r))
                elif 'updated_at' in lcols and 'updated_at' in ri['cols'] and rex.get(key):
                    if str(r[lcols.index('updated_at')] or '') > str(rex[key]):
                        to_push.append(list(r))
            if to_push:
                res = _remote(_T_UPSERT, table, pk,
                              stdin=json.dumps({'cols': use, 'rows': to_push}, ensure_ascii=False))
                applied += int(res.get('applied') or 0)
        if len(rows) < BATCH:
            break
    return {'scanned': scanned, 'applied': applied}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--tables', default='')
    ap.add_argument('--create-missing', action='store_true',
                    help='本机缺表时复制远端 schema 建表 (DDL) 后再拉取')
    ap.add_argument('--direction', choices=['both', 'pull', 'push'], default='both')
    a = ap.parse_args()
    tables = SYNC_TABLES
    if a.tables:
        want = {t.strip() for t in a.tables.split(',') if t.strip()}
        tables = [t for t in SYNC_TABLES if t[0] in want]
    print(f"[sync] local={LOCAL_DB}")
    print(f"[sync] remote={REMOTE_HOST} tables={len(tables)} dry_run={a.dry_run}")
    results = []
    for i, (table, pk) in enumerate(tables, 1):
        t0 = time.time()
        row = {'table': table}
        if a.direction in ('both', 'pull'):
            row['pull'] = pull_table(table, pk, a.dry_run, a.create_missing)
        if a.direction in ('both', 'push'):
            row['push'] = push_table(table, pk, a.dry_run)
        row['seconds'] = round(time.time() - t0, 2)
        results.append(row)
        print(f"[{i}/{len(tables)}] {table} pull={row.get('pull')} push={row.get('push')} ({row['seconds']}s)")
    out = os.path.join(os.path.dirname(_BASE), '_runtime', 'logs', 'bidirectional_sync_last.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'dry_run': a.dry_run, 'tables': len(tables), 'results': results,
                   'finished_at': time.strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False, indent=1)
    errs = sum(1 for r in results for k in ('pull', 'push')
               if isinstance(r.get(k), dict) and r[k].get('error'))
    print(f"[sync] report → {out}  errors={errs}")


if __name__ == '__main__':
    main()
