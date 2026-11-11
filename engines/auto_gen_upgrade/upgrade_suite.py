# -*- coding: utf-8 -*-
"""
andromeda_upgrade_suite.py — 冰山/知识/仙女座 三域升级套件 (auto_gen_upgrade)
由 smart_mount UPGRADE daemon 自动产出 (flow: bulk_andromeda_upgrade_20261014)
版本: v22.21.0-upgrade-suite | 日期: 2026-10-14

三域功能:
  A. iceberg_domain()   — 冰山 8 引擎升级状态快照 + 升级项落库
  B. knowledge_domain() — 知识库增量统计 (brain_knowledge/KG/eigenflux)
  C. andromeda_domain() — 仙女座子系统健康 (daemon/建议池/KG节点边)
  main: 三域各跑一次 → mt_upgrade_suite_log (engines/app.db) 短事务落库
"""
import os
import sqlite3
import datetime

APP_DB = os.environ.get(
    'APP_DB',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app.db'))
MAIN_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    'flask-app', 'database', 'app.db')

ICEBERG_ENGINES = [
    'iceberg_meta_model.py', 'iceberg_content_matrix.py',
    'iceberg_consciousness.py', 'iceberg_handshake.py',
    'iceberg_slang_substitution.py', 'iceberg_arduino_ai.py',
    'iceberg_qbank_adaptive.py', 'iceberg_command.py',
]
ANDROMEDA_ENGINES = [
    'andromeda_core.py', 'andromeda_base.py', 'andromeda_auto_loop.py',
    'andromeda_auto_evolution.py', 'andromeda_cluster_matrix.py',
    'andromeda_research.py', 'andromeda_self_heal.py',
    'andromeda_code_hygiene_engine.py',
]
KNOWLEDGE_ENGINES = [
    'brain_feeding_engine.py', 'ai_knowledge_aggregator_engine.py',
    'ai_self_learning_engine.py',
]


def _conn(db, timeout=15):
    c = sqlite3.connect(db, timeout=timeout)
    c.execute('PRAGMA busy_timeout=15000')
    return c


def _engine_snapshot(names):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    for n in names:
        p = os.path.join(base, n)
        if os.path.exists(p):
            st = os.stat(p)
            out.append((n, st.st_size, datetime.datetime.fromtimestamp(
                st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')))
        else:
            out.append((n, -1, 'MISSING'))
    return out


def iceberg_domain():
    """冰山 8 引擎升级快照"""
    snap = _engine_snapshot(ICEBERG_ENGINES)
    ok = sum(1 for _, size, _ in snap if size > 0)
    return {'domain': 'iceberg', 'engines_total': len(snap),
            'engines_ok': ok, 'snapshot': snap}


def knowledge_domain():
    """知识库增量统计 (只读主库, 表容错)"""
    stats = {}
    try:
        c = _conn(MAIN_DB)
        for tbl, key in [('mt_ai_brain_feed_log', 'brain_feed_rows'),
                         ('mt_ai_eigenflux_messages', 'eigenflux_msgs'),
                         ('brain_knowledge', 'brain_knowledge'),
                         ('graph_nodes', 'kg_nodes'),
                         ('graph_relations', 'kg_edges')]:
            try:
                stats[key] = c.execute(
                    'SELECT COUNT(*) FROM ' + tbl).fetchone()[0]
            except Exception:
                stats[key] = -1
        c.close()
    except Exception as e:
        stats['error'] = str(e)
    stats['knowledge_engines'] = len(KNOWLEDGE_ENGINES)
    return {'domain': 'knowledge', 'stats': stats}


def andromeda_domain():
    """仙女座子系统健康 (engines/app.db)"""
    stats = {'daemon_states': {}, 'suggestions': {}}
    try:
        c = _conn(APP_DB)
        for st, n in c.execute(
                'SELECT current_state, COUNT(*) FROM mt_ai_smart_mount_processes'
                ' GROUP BY current_state').fetchall():
            stats['daemon_states'][st] = n
        try:
            for st, n in c.execute(
                    'SELECT status, COUNT(*) FROM mt_ai_suggestion_pool'
                    ' GROUP BY status LIMIT 8').fetchall():
                stats['suggestions'][st] = n
        except Exception:
            pass
        c.close()
    except Exception as e:
        stats['error'] = str(e)
    stats['subsystem_engines'] = len(ANDROMEDA_ENGINES)
    return {'domain': 'andromeda', 'stats': stats}


def _ensure_log_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS mt_upgrade_suite_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at TEXT DEFAULT (datetime('now')),
        suite_version TEXT DEFAULT 'v22.21.0-upgrade-suite',
        domain TEXT, payload_json TEXT)''')


def run_suite():
    """三域各跑一次 + 短事务落库"""
    results = [iceberg_domain(), knowledge_domain(), andromeda_domain()]
    import json
    try:
        c = _conn(APP_DB)
        _ensure_log_table(c)
        for r in results:
            c.execute('INSERT INTO mt_upgrade_suite_log (domain, payload_json)'
                      ' VALUES (?,?)', (r['domain'], json.dumps(
                          r, ensure_ascii=False, default=str)))
        c.commit()
        c.close()
    except Exception as e:
        results.append({'domain': 'log_error', 'error': str(e)})
    return results


if __name__ == '__main__':
    for r in run_suite():
        line = '[%s] ' % r.get('domain', '?')
        if 'engines_total' in r:
            line += 'engines %d/%d ok' % (r['engines_ok'], r['engines_total'])
        elif 'stats' in r:
            line += str(r['stats'])[:160]
        print(line)
