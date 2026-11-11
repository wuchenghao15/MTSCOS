#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
移动端历史档案馆 — flow_mobile_archive_20261031
================================================
「网页版聊天系统和小龙 App 同宗不同源」原则在档案馆的延续:
  · 同宗: 档案数据统一走 /api/archive/* 单一后端 (blueprints/iceberg_archive_bp.py,
    跨库聚合 7 类历史档案); 本蓝图函数级复用 _overview/_timeline, 不另起数据链路
  · 不同源: 独立蓝图 / 独立移动端模板 / App 鉴权 (X-XL-Token → session 注入),
    与桌面档案馆 /andromeda/archive 互为跨端入口 (合并到历史档案相关中心)

路由:
  GET /xiaolong/archive             移动端档案馆页 (App 内, 登录可用)
  GET /xiaolong/archive/manual      档案馆使用说明书页 (公开, 下载中心配套)
  GET /api/xiaolong-archive/summary 档案墙摘要 (总数+最新墙+更时间戳, 30s 轮询)

人员配置 (flow_mobile_archive_20261031 · 完善中心人员配置):
  · mt_lab_centers 播种 archive_hall 历史档案中心 (幂等, 与 daemon_skill_lab_bp 双保险)
  · mt_center_committee_members: archive_hall 顾问委员会 5 席固定配齐
  · 全中心缺员补齐: 任一 ADV_{center_code} 委员会 <3 席时, 从该中心历史认领
    (mt_lab_assignments) 员工频次 Top3 补齐 主席/副主席/秘书长
"""
from __future__ import annotations

import os
import sqlite3

from flask import Blueprint, jsonify, render_template

from app.db import connect as _db
from blueprints.xiaolong_app_bp import _login_required
from blueprints.iceberg_archive_bp import KIND_LABELS, _overview, _timeline

FLOW_ID = 'flow_mobile_archive_20261031'
APP_VERSION = 'v22.25.43'
ARCHIVE_CENTER = ('archive_hall', '历史档案中心', '历史档案',
                  '档案,archive,归档,版本,演化,时间线,考证,检索,纪念馆,历史')

# 历史档案中心顾问委员会 (5 席) — 历史档案主题人物分身
_ARCHIVE_COMMITTEE = [
    ('馆长',   'ARCH-SGQ-001', '司马迁',   98, '纪传体通史, 究天人之际通古今之变, 档案总纂'),
    ('副馆长', 'ARCH-BG-002',  '班固',     94, '断代史, 汉书艺文志目录学, 档案分类'),
    ('档案管理员', 'ARCH-JXL-003', '刘歆', 92, '七略目录学, 古文经整理, 档案编目'),
    ('考据员', 'ARCH-JXL-004', '纪晓岚',   90, '四库全书总目提要, 版本校勘, 档案考证'),
    ('数字化专员', 'ARCH-WGW-005', '王国维', 89, '二重证据法, 甲骨金文释读, 档案数字化'),
]
# 通用补员岗位 (缺员中心的默认三席)
_BACKFILL_POSITIONS = ('主席', '副主席', '秘书长')


xla_bp = Blueprint('xiaolong_archive_bp', __name__)


# ────────────────────────── 中心人员配置 (幂等) ──────────────────────────
def _ensure_archive_center() -> None:
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO mt_lab_centers (center_code,name,domain,keywords) VALUES (?,?,?,?)",
                     ARCHIVE_CENTER)
        conn.commit()
    finally:
        conn.close()


def _center_id(conn: sqlite3.Connection, code: str):
    return conn.execute('SELECT id FROM mt_lab_centers WHERE center_code=?', (code,)).fetchone()


def _committee_count(conn: sqlite3.Connection, committee_id: str) -> int:
    r = conn.execute("SELECT count(*) FROM mt_center_committee_members WHERE committee_id=? AND status='ACTIVE'",
                     (committee_id,)).fetchone()
    return int(r[0]) if r else 0


def _seed_archive_committee(conn: sqlite3.Connection) -> int:
    """archive_hall 顾问委员会 5 席 (按 position 幂等)"""
    n = 0
    if not _center_id(conn, 'archive_hall'):
        return n
    for position, code, name, score, spec in _ARCHIVE_COMMITTEE:
        dup = conn.execute(
            "SELECT 1 FROM mt_center_committee_members WHERE committee_id=? AND position=? AND status='ACTIVE'",
            ('ADV_archive_hall', position)).fetchone()
        if dup:
            continue
        conn.execute("""INSERT INTO mt_center_committee_members
            (committee_id, committee_name, skill_id, position, ai_employee_code, ai_name, match_score, status)
            VALUES (?,?,?,?,?,?,?, 'ACTIVE')""",
            ('ADV_archive_hall', '历史档案中心顾问委员会', 'SKILL_ARCHIVE', position, code, name, score))
        n += 1
    return n


def _history_top_employees(conn: sqlite3.Connection, center_code: str, limit: int = 3) -> list:
    """从该中心历史认领记录中取出现频次最高的员工 (数据驱动, 贴中心领域)"""
    rows = conn.execute("""
        SELECT a.employee_names FROM mt_lab_assignments a
        JOIN mt_lab_centers c ON c.id=a.center_id
        WHERE c.center_code=? AND a.employee_names IS NOT NULL AND a.employee_names != '[]'
        ORDER BY a.id DESC LIMIT 200""", (center_code,)).fetchall()
    freq: dict = {}
    import json as _json
    for r in rows:
        try:
            for emp in _json.loads(r[0]):
                name = (emp.get('name') or '').strip()
                code = (emp.get('code') or '').strip()
                if not name:
                    continue
                k = (name, code)
                freq[k] = freq.get(k, 0) + 1
        except Exception:
            continue
    ranked = sorted(freq.items(), key=lambda kv: -kv[1])[:limit]
    return [{'name': k[0], 'code': k[1] or 'ARCH-BACKFILL', 'score': min(99, 60 + v)}
            for k, v in ranked]


def _backfill_committees(conn: sqlite3.Connection) -> int:
    """任一中心顾问委员会 <3 席 → 按历史认领频次 Top3 补齐 主席/副主席/秘书长 (幂等)"""
    centers = conn.execute("SELECT center_code, name FROM mt_lab_centers WHERE status='ACTIVE'").fetchall()
    n = 0
    for code, cname in centers:
        cid = f'ADV_{code}'
        have = conn.execute(
            "SELECT position FROM mt_center_committee_members WHERE committee_id=? AND status='ACTIVE'",
            (cid,)).fetchall()
        have_positions = {r[0] for r in have}
        if len(have_positions) >= 3:
            continue
        emps = _history_top_employees(conn, code, 3)
        if not emps:
            continue
        for i, position in enumerate(_BACKFILL_POSITIONS):
            if position in have_positions or i >= len(emps):
                continue
            dup = conn.execute(
                "SELECT 1 FROM mt_center_committee_members WHERE committee_id=? AND position=? AND status='ACTIVE'",
                (cid, position)).fetchone()
            if dup:
                continue
            e = emps[i]
            conn.execute("""INSERT INTO mt_center_committee_members
                (committee_id, committee_name, skill_id, position, ai_employee_code, ai_name, match_score, status)
                VALUES (?,?,?,?,?,?,?, 'ACTIVE')""",
                (cid, f'{cname}顾问委员会', 'SKILL_BACKFILL', position, e['code'], e['name'], e['score']))
            n += 1
    return n


def _init_staffing() -> dict:
    try:
        _ensure_archive_center()
        conn = _db()
        try:
            seeded = _seed_archive_committee(conn)
            backfilled = _backfill_committees(conn)
            conn.commit()
        finally:
            conn.close()
        return {'seeded_archive': seeded, 'backfilled': backfilled}
    except Exception as _e:
        return {'error': str(_e)}


_init_staffing()


# ────────────────────────── 路由 ──────────────────────────
@xla_bp.route('/xiaolong/archive', methods=['GET'])
@_login_required
def mobile_archive_page():
    return render_template('xiaolong_archive.html', app_version=APP_VERSION,
                           kinds=KIND_LABELS, flow_id=FLOW_ID)


@xla_bp.route('/xiaolong/archive/manual', methods=['GET'])
def archive_manual_page():
    """说明书页 — 公开可达 (下载中心配套引用), 移动端排版"""
    return render_template('xiaolong_archive_manual.html', app_version=APP_VERSION,
                           flow_id=FLOW_ID)


@xla_bp.route('/api/xiaolong-archive/summary', methods=['GET'])
def archive_wall_summary():
    """档案墙摘要: 总数 + 分类计数 + 最新 8 条墙 + 服务端时间戳 (30s 轮询锚点)"""
    ov = _overview()
    latest = _timeline('all', '', 8)
    return jsonify({
        'ok': True,
        'total': sum(ov[k] for k in ('version', 'evolution', 'flow', 'task', 'rule', 'upgrade', 'copy')),
        'overview': ov,
        'kinds': [{'kind': k, 'label': v, 'count': ov.get(k, 0)} for k, v in KIND_LABELS.items()],
        'wall': latest,
        'server_time': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'center': {'code': 'archive_hall', 'name': '历史档案中心'},
        'flow_id': FLOW_ID,
    })
