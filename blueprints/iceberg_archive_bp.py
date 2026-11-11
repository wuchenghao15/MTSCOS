#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冰山历史档案馆 — flow_archive_20261022
=====================================
跨库聚合 7 类历史档案, 统一时间线 + 检索 + 详情:

  ① version   系统版本档案   mt_system_version_archive   (engines/app.db, 112 条)
  ② evolution 冰山演化阶段   mt_iceberg_evolution_archive(engines 11 条 / 主库 7 条)
  ③ flow      §14 开发流程   mt_dev_flow_session         (主库)
  ④ task      任务大厅归档   mt_lab_task_hall            (主库, DONE/已归档)
  ⑤ rule      规则版本变更   mt_rule_changelog           (主库)
  ⑥ upgrade   升级报告       mt_upgrade_reports          (engines/app.db)
  ⑦ copy      文案永久存档   mt_copy_permanent_archive   (engines/app.db)

路由:
  GET /andromeda/archive            档案馆页面
  GET /api/archive/overview         各类档案计数
  GET /api/archive/timeline         统一时间线 (kind/page/size/q)
  GET /api/archive/detail           单条详情 (kind/id)
  GET /api/archive/search           跨档案检索
  GET /api/archive/stats            按年月分布
"""
from __future__ import annotations

import os
import sqlite3

from flask import Blueprint, jsonify, render_template, request

FLOW_ID = 'flow_archive_20261022'
APP_VERSION = 'v22.25.29'

_FA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_MAIN = os.environ.get('MTSCOS_DB_PATH') or os.path.join(_FA, 'database', 'app.db')
DB_ANDR = os.environ.get('MTSCOS_ANDR_DB') or os.path.join(_FA, 'engines', 'app.db')

archive_bp = Blueprint('iceberg_archive_bp', __name__)

KIND_LABELS = {
    'version': '版本档案', 'evolution': '演化阶段', 'flow': '开发流程',
    'task': '任务归档', 'rule': '规则变更', 'upgrade': '升级报告', 'copy': '文案存档',
}

_EMPTY_HINT = {
    'version': 'engines/app.db 未建 mt_system_version_archive',
    'evolution': 'engines/app.db 未建 mt_iceberg_evolution_archive',
    'flow': '主库未建 mt_dev_flow_session',
    'task': '主库未建 mt_lab_task_hall',
    'rule': '主库未建 mt_rule_changelog',
    'upgrade': 'engines/app.db 未建 mt_upgrade_reports',
    'copy': 'engines/app.db 未建 mt_copy_permanent_archive',
}


def _rows(db: str, sql: str, args=()) -> list:
    """安全查询: 库/表缺失一律返回空列表, 不让档案馆整体 500"""
    if not db or not os.path.exists(db):
        return []
    try:
        conn = sqlite3.connect(db, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA busy_timeout=8000')
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _count(db: str, table: str, where: str = '') -> int:
    r = _rows(db, f"SELECT count(*) n FROM {table} {where}")
    return int(r[0]['n']) if r else 0


def _has_table(db: str, table: str) -> bool:
    return bool(_rows(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


# ────────────────────────── 各档案抽取 ──────────────────────────
def _q_version(q: str, limit: int) -> list:
    if not _has_table(DB_ANDR, 'mt_system_version_archive'):
        return []
    sql = ("SELECT id, version_tag, commit_date, archived_at, commit_msg, changelog_summary,"
           " version_source, breaking_change, rollback_version FROM mt_system_version_archive")
    args = []
    if q:
        sql += " WHERE (version_tag LIKE ? OR changelog_summary LIKE ? OR commit_msg LIKE ?)"
        args = [f'%{q}%'] * 3
    sql += " ORDER BY COALESCE(commit_date, archived_at, '') DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(DB_ANDR, sql, args):
        out.append({
            'kind': 'version', 'id': r['id'],
            'date': (r['commit_date'] or r['archived_at'] or '')[:19],
            'title': r['version_tag'] or '',
            'subtitle': (r['commit_msg'] or r['version_source'] or '')[:120],
            'detail': (r['changelog_summary'] or '')[:400],
        })
    return out


def _q_evolution(q: str, limit: int) -> list:
    db = DB_ANDR if _has_table(DB_ANDR, 'mt_iceberg_evolution_archive') else DB_MAIN
    if not _has_table(db, 'mt_iceberg_evolution_archive'):
        return []
    sql = ("SELECT id, stage_seq, stage_name, stage_date, version_tag, core_theorem,"
           " iceberg_layer, archive_summary FROM mt_iceberg_evolution_archive")
    args = []
    if q:
        sql += " WHERE (stage_name LIKE ? OR core_theorem LIKE ? OR archive_summary LIKE ?)"
        args = [f'%{q}%'] * 3
    sql += " ORDER BY stage_seq DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(db, sql, args):
        out.append({
            'kind': 'evolution', 'id': r['id'],
            'date': (r['stage_date'] or '')[:19],
            'title': f'{r["stage_seq"] or "?"}. {r["stage_name"] or ""}',
            'subtitle': f'{r["version_tag"] or ""} · {r["iceberg_layer"] or ""}',
            'detail': (r['core_theorem'] or r['archive_summary'] or '')[:400],
        })
    return out


def _q_flow(q: str, limit: int) -> list:
    if not _has_table(DB_MAIN, 'mt_dev_flow_session'):
        return []
    sql = ("SELECT flow_id, proposal_title, proposal_summary, current_step, final_status,"
           " created_at, updated_at, smart_upgrade_version FROM mt_dev_flow_session")
    args = []
    if q:
        sql += " WHERE (proposal_title LIKE ? OR proposal_summary LIKE ? OR flow_id LIKE ?)"
        args = [f'%{q}%'] * 3
    sql += " ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(DB_MAIN, sql, args):
        out.append({
            'kind': 'flow', 'id': r['flow_id'],
            'date': (r['updated_at'] or r['created_at'] or '')[:19],
            'title': r['proposal_title'] or r['flow_id'],
            'subtitle': f'{r["flow_id"]} · {r["current_step"] or ""} / {r["final_status"] or ""}',
            'detail': (r['proposal_summary'] or '')[:400],
        })
    return out


def _q_task(q: str, limit: int) -> list:
    if not _has_table(DB_MAIN, 'mt_lab_task_hall'):
        return []
    sql = ("SELECT id, hall_code, title, description, status, deliverable, claim_owner,"
           " accepted_at, archived_at, delivered_at FROM mt_lab_task_hall"
           " WHERE (status IN ('DONE','ARCHIVED') OR archived_at IS NOT NULL)")
    args = []
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR deliverable LIKE ? OR hall_code LIKE ?)"
        args = [f'%{q}%'] * 4
    sql += " ORDER BY COALESCE(accepted_at, archived_at, delivered_at, '') DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(DB_MAIN, sql, args):
        out.append({
            'kind': 'task', 'id': r['id'],
            'date': (r['accepted_at'] or r['archived_at'] or r['delivered_at'] or '')[:19],
            'title': f'{r["hall_code"] or ("#" + str(r["id"]))} {r["title"] or ""}',
            'subtitle': f'{r["status"]} · {r["claim_owner"] or ""}',
            'detail': (r['deliverable'] or r['description'] or '')[:400],
        })
    return out


def _q_rule(q: str, limit: int) -> list:
    if not _has_table(DB_MAIN, 'mt_rule_changelog'):
        return []
    sql = ("SELECT changelog_id, rule_id, from_version, to_version, change_type, change_summary,"
           " sa_final_decision, created_at FROM mt_rule_changelog")
    args = []
    if q:
        sql += " WHERE (rule_id LIKE ? OR change_summary LIKE ?)"
        args = [f'%{q}%'] * 2
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(DB_MAIN, sql, args):
        out.append({
            'kind': 'rule', 'id': r['changelog_id'],
            'date': (r['created_at'] or '')[:19],
            'title': f'{r["rule_id"]} {r["from_version"] or "?"} → {r["to_version"] or "?"}',
            'subtitle': f'{r["change_type"] or ""} · {r["sa_final_decision"] or ""}',
            'detail': (r['change_summary'] or '')[:400],
        })
    return out


def _q_upgrade(q: str, limit: int) -> list:
    if not _has_table(DB_ANDR, 'mt_upgrade_reports'):
        return []
    sql = ("SELECT report_id, report_type, report_start, report_end, key_highlights, generated_at"
           " FROM mt_upgrade_reports")
    args = []
    if q:
        sql += " WHERE (key_highlights LIKE ? OR report_type LIKE ?)"
        args = [f'%{q}%'] * 2
    sql += " ORDER BY generated_at DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(DB_ANDR, sql, args):
        out.append({
            'kind': 'upgrade', 'id': r['report_id'],
            'date': (r['generated_at'] or '')[:19],
            'title': f'{r["report_type"] or "升级"} 报告',
            'subtitle': f'{r["report_start"] or ""} ~ {r["report_end"] or ""}',
            'detail': (r['key_highlights'] or '')[:400],
        })
    return out


def _q_copy(q: str, limit: int) -> list:
    if not _has_table(DB_ANDR, 'mt_copy_permanent_archive'):
        return []
    sql = ("SELECT copy_id, copy_category, copy_source, copy_content, archive_status, created_at"
           " FROM mt_copy_permanent_archive")
    args = []
    if q:
        sql += " WHERE (copy_content LIKE ? OR copy_category LIKE ?)"
        args = [f'%{q}%'] * 2
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _rows(DB_ANDR, sql, args):
        out.append({
            'kind': 'copy', 'id': r['copy_id'],
            'date': (r['created_at'] or '')[:19],
            'title': r['copy_category'] or '文案',
            'subtitle': f'{r["copy_source"] or ""} · {r["archive_status"] or ""}',
            'detail': (r['copy_content'] or '')[:400],
        })
    return out


_BUILDERS = {
    'version': _q_version, 'evolution': _q_evolution, 'flow': _q_flow,
    'task': _q_task, 'rule': _q_rule, 'upgrade': _q_upgrade, 'copy': _q_copy,
}


def _timeline(kind: str, q: str, limit: int) -> list:
    kinds = list(_BUILDERS) if kind in ('', 'all') else [kind]
    items = []
    for k in kinds:
        fn = _BUILDERS.get(k)
        if not fn:
            continue
        for it in fn(q, limit):
            it['kind_label'] = KIND_LABELS.get(k, k)
            items.append(it)
    items.sort(key=lambda x: x.get('date') or '', reverse=True)
    return items


def _overview() -> dict:
    evo_db = DB_ANDR if _has_table(DB_ANDR, 'mt_iceberg_evolution_archive') else DB_MAIN
    return {
        'version': _count(DB_ANDR, 'mt_system_version_archive'),
        'evolution': _count(evo_db, 'mt_iceberg_evolution_archive'),
        'flow': _count(DB_MAIN, 'mt_dev_flow_session'),
        'flow_done': _count(DB_MAIN, 'mt_dev_flow_session', "WHERE final_status='DONE'"),
        'task': _count(DB_MAIN, 'mt_lab_task_hall',
                       "WHERE status IN ('DONE','ARCHIVED') OR archived_at IS NOT NULL"),
        'rule': _count(DB_MAIN, 'mt_rule_changelog'),
        'upgrade': _count(DB_ANDR, 'mt_upgrade_reports'),
        'copy': _count(DB_ANDR, 'mt_copy_permanent_archive'),
    }


# ────────────────────────── 路由 ──────────────────────────
@archive_bp.route('/andromeda/archive', methods=['GET'])
def archive_page():
    return render_template('iceberg_archive.html',
                           app_version=APP_VERSION, kinds=KIND_LABELS)


@archive_bp.route('/api/archive/overview')
def archive_overview():
    ov = _overview()
    return jsonify({
        'ok': True, 'overview': ov, 'total': sum(ov[k] for k in
                                                 ('version', 'evolution', 'flow', 'task',
                                                  'rule', 'upgrade', 'copy')),
        'kinds': [{'kind': k, 'label': v, 'count': ov.get(k, 0)} for k, v in KIND_LABELS.items()],
        'db': {'main': DB_MAIN, 'andromeda': DB_ANDR},
    })


@archive_bp.route('/api/archive/timeline')
def archive_timeline():
    kind = (request.args.get('kind') or 'all').strip()
    if kind not in ('all', '') and kind not in KIND_LABELS:
        return jsonify({'ok': False, 'error': f'kind 须为 all/{"|".join(KIND_LABELS)}'}), 400
    q = (request.args.get('q') or '').strip()[:60]
    try:
        page = max(int(request.args.get('page', 1)), 1)
        size = min(max(int(request.args.get('size', 20)), 1), 100)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'page/size 须为整数'}), 400
    items = _timeline(kind, q, 500)
    start = (page - 1) * size
    page_items = items[start:start + size]
    return jsonify({'ok': True, 'kind': kind, 'q': q,
                    'total': len(items), 'page': page, 'size': size,
                    'items': page_items, 'has_more': start + size < len(items)})


@archive_bp.route('/api/archive/detail')
def archive_detail():
    kind = (request.args.get('kind') or '').strip()
    rid = request.args.get('id')
    if kind not in KIND_LABELS or not rid:
        return jsonify({'ok': False, 'error': '需 kind + id'}), 400
    if kind == 'version':
        rows = _rows(DB_ANDR, "SELECT * FROM mt_system_version_archive WHERE id=? OR version_tag=?",
                     (rid, rid))
    elif kind == 'evolution':
        db = DB_ANDR if _has_table(DB_ANDR, 'mt_iceberg_evolution_archive') else DB_MAIN
        rows = _rows(db, "SELECT * FROM mt_iceberg_evolution_archive WHERE id=? OR stage_seq=?",
                     (rid, rid))
    elif kind == 'flow':
        rows = _rows(DB_MAIN, "SELECT * FROM mt_dev_flow_session WHERE flow_id=?", (rid,))
    elif kind == 'task':
        rows = _rows(DB_MAIN, "SELECT * FROM mt_lab_task_hall WHERE id=? OR hall_code=?",
                     (rid, rid))
    elif kind == 'rule':
        rows = _rows(DB_MAIN, "SELECT * FROM mt_rule_changelog WHERE changelog_id=?", (rid,))
    elif kind == 'upgrade':
        rows = _rows(DB_ANDR, "SELECT * FROM mt_upgrade_reports WHERE report_id=?", (rid,))
    else:
        rows = _rows(DB_ANDR, "SELECT * FROM mt_copy_permanent_archive WHERE copy_id=?", (rid,))
    if not rows:
        return jsonify({'ok': False, 'error': '档案不存在', 'hint': _EMPTY_HINT.get(kind)}), 404
    return jsonify({'ok': True, 'kind': kind, 'kind_label': KIND_LABELS[kind], 'record': rows[0]})


@archive_bp.route('/api/archive/search')
def archive_search():
    q = (request.args.get('q') or '').strip()
    if len(q) < 1:
        return jsonify({'ok': False, 'error': 'q 不能为空'}), 400
    kind = (request.args.get('kind') or 'all').strip()
    limit = min(max(int(request.args.get('limit', 50) or 50), 1), 200)
    items = _timeline(kind, q, limit)
    return jsonify({'ok': True, 'q': q, 'kind': kind, 'total': len(items), 'items': items[:limit]})


@archive_bp.route('/api/archive/stats')
def archive_stats():
    items = _timeline('all', '', 500)
    by_year, by_kind = {}, {}
    for it in items:
        y = (it.get('date') or '')[:4] or 'unknown'
        by_year[y] = by_year.get(y, 0) + 1
        by_kind[it['kind']] = by_kind.get(it['kind'], 0) + 1
    return jsonify({'ok': True, 'by_year': dict(sorted(by_year.items(), reverse=True)),
                    'by_kind': by_kind, 'sampled': len(items)})
