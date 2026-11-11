#!/usr/bin/env python3
"""仙女座会议大厅蓝图 — 实时 AI × 会议室 × 会议

端点:
  GET /api/meetings/active     → 所有 ACTIVE 会议 + 出席 AI
  GET /api/meetings/all       → 全部会议 (含 ENDED)
  GET /api/meetings/<center>  → 指定中心/会议室的会议
  GET /api/meetings/ai/<name> → 某 AI 正在出席哪些会议
  GET /api/meetings/rooms     → 会议室全景 (房间墙)
"""
import os, json, sqlite3, datetime
from flask import Blueprint, jsonify, request

meeting_hall_bp = Blueprint('meeting_hall', __name__)

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'app.db')

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _conn():
    return sqlite3.connect(DB, timeout=15)

def _rooms(conn):
    """会议室全景 = mt_lab_centers (30 个) + mt_center_meetings 状态"""
    rooms = []
    cur = conn.cursor()
    centers = cur.execute(
        "SELECT center_code, name, domain, keywords, status FROM mt_lab_centers WHERE status='ACTIVE'"
    ).fetchall()
    for cc, name, domain, kws, st in centers:
        # 当前会议数
        active = cur.execute(
            "SELECT COUNT(*) FROM mt_center_meetings WHERE center_code=? AND status='ACTIVE'", (cc,)
        ).fetchone()[0]
        ended = cur.execute(
            "SELECT COUNT(*) FROM mt_center_meetings WHERE center_code=? AND status='ENDED'", (cc,)
        ).fetchone()[0]
        # 当前主持人
        host_row = cur.execute(
            "SELECT host_ai, meeting_title FROM mt_center_meetings WHERE center_code=? AND status='ACTIVE' LIMIT 1",
            (cc,)
        ).fetchone()
        host = host_row[0] if host_row else None
        title = host_row[1] if host_row else None
        # AI 出席数 (active 会议)
        attendees_cnt = 0
        if host_row:
            rows = cur.execute(
                "SELECT attendees FROM mt_center_meetings WHERE center_code=? AND status='ACTIVE'", (cc,)
            ).fetchall()
            for r in rows:
                try: attendees_cnt += len(json.loads(r[0] or '[]'))
                except: pass
        rooms.append({
            "center_code": cc, "name": name, "domain": domain,
            "keywords": [k.strip() for k in (kws or '').split(',') if k.strip()],
            "status": st,
            "active_meetings": active, "ended_meetings": ended,
            "current_host": host, "current_title": title,
            "attendees_cnt": attendees_cnt,
            "has_active": active > 0,
        })
    return rooms


def _meeting_row(row):
    """把 mt_center_meetings 行转成 API dict"""
    m_id, cc, cn, mt, title, host, attendees, agenda, status, started, heartbeat, ended, src = row
    try: att_list = json.loads(attendees) if attendees else []
    except: att_list = []
    # 计算持续时间
    dur = None
    if status == 'ACTIVE' and started:
        try:
            s = datetime.datetime.strptime(started[:19], "%Y-%m-%d %H:%M:%S")
            dur = int((datetime.datetime.now() - s).total_seconds() / 60)
        except: pass
    elif status == 'ENDED' and started and ended:
        try:
            s = datetime.datetime.strptime(started[:19], "%Y-%m-%d %H:%M:%S")
            e = datetime.datetime.strptime(ended[:19], "%Y-%m-%d %H:%M:%S")
            dur = int((e - s).total_seconds() / 60)
        except: pass
    return {
        "meeting_id": m_id, "center_code": cc, "center_name": cn,
        "meeting_type": mt, "title": title, "host_ai": host,
        "attendees": att_list, "attendees_cnt": len(att_list),
        "agenda": agenda, "status": status, "started_at": started,
        "last_heartbeat": heartbeat, "ended_at": ended,
        "source": src, "duration_min": dur,
    }


@meeting_hall_bp.route('/api/meetings/rooms')
def api_rooms():
    """会议室全景 (房间墙)"""
    conn = _conn()
    try:
        rooms = _rooms(conn)
        active_total = sum(1 for r in rooms if r['has_active'])
        return jsonify({
            "generated_at": _now(),
            "total_rooms": len(rooms),
            "rooms_with_active": active_total,
            "rooms": rooms,
        })
    finally: conn.close()


@meeting_hall_bp.route('/api/meetings/active')
def api_active():
    """所有 ACTIVE 会议 + 出席 AI"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT meeting_id, center_code, center_name, meeting_type, meeting_title, "
            "host_ai, attendees, agenda, status, started_at, last_heartbeat, ended_at, source "
            "FROM mt_center_meetings WHERE status='ACTIVE' ORDER BY started_at DESC"
        ).fetchall()
        meetings = [_meeting_row(r) for r in rows]
        # 聚合 AI 出席者
        all_ais = set()
        for m in meetings:
            all_ais.add(m['host_ai'])
            for a in m['attendees']: all_ais.add(a)
        return jsonify({
            "generated_at": _now(),
            "total_active": len(meetings),
            "total_rooms_with_meetings": len(set(m['center_code'] for m in meetings)),
            "unique_ais": len(all_ais),
            "meetings": meetings,
        })
    finally: conn.close()


@meeting_hall_bp.route('/api/meetings/all')
def api_all():
    """全部会议 (含 ENDED, 限 60)"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT meeting_id, center_code, center_name, meeting_type, meeting_title, "
            "host_ai, attendees, agenda, status, started_at, last_heartbeat, ended_at, source "
            "FROM mt_center_meetings ORDER BY started_at DESC LIMIT 60"
        ).fetchall()
        meetings = [_meeting_row(r) for r in rows]
        return jsonify({
            "generated_at": _now(),
            "total": len(meetings),
            "meetings": meetings,
        })
    finally: conn.close()


@meeting_hall_bp.route('/api/meetings/center/<center_code>')
def api_center(center_code):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT meeting_id, center_code, center_name, meeting_type, meeting_title, "
            "host_ai, attendees, agenda, status, started_at, last_heartbeat, ended_at, source "
            "FROM mt_center_meetings WHERE center_code=? ORDER BY started_at DESC LIMIT 20",
            (center_code,)
        ).fetchall()
        meetings = [_meeting_row(r) for r in rows]
        return jsonify({
            "generated_at": _now(), "center_code": center_code, "meetings": meetings,
        })
    finally: conn.close()


@meeting_hall_bp.route('/api/meetings/ai/<ai_name>')
def api_ai(ai_name):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT meeting_id, center_code, center_name, meeting_type, meeting_title, "
            "host_ai, attendees, agenda, status, started_at, last_heartbeat, ended_at, source "
            "FROM mt_center_meetings WHERE host_ai=? OR attendees LIKE ? "
            "ORDER BY started_at DESC LIMIT 20",
            (ai_name, f'%"{ai_name}"%')
        ).fetchall()
        meetings = [_meeting_row(r) for r in rows]
        return jsonify({
            "generated_at": _now(), "ai_name": ai_name, "meetings": meetings,
        })
    finally: conn.close()
