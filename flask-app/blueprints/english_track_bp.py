#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英语考试赛道 Blueprint (flow_english_track_20261031)
页面:  GET  /english-tracks                       — 英语赛道主页
API:   GET  /api/english-track/overview           — 15 赛道总览 (题量/正确率/健康)
API:   GET  /api/english-track/questions          — ?track=雅思听力&limit=20 列题
API:   POST /api/english-track/expand            — {track?, count} 手动补题
"""
from flask import Blueprint, jsonify, request

english_track_bp = Blueprint("english_track_bp", __name__, template_folder=None)


def _engine():
    from engines.ai_english_track_engine import (
        TRACKS, track_overview, generate_questions, daemon_cycle, _FLOW,
    )
    return TRACKS, track_overview, generate_questions, daemon_cycle, _FLOW


@english_track_bp.route("/api/english-track/overview")
def api_overview():
    try:
        TRACKS, track_overview, _, _, FLOW = _engine()
        ov = track_overview()
        fams = {}
        for o in ov:
            fams.setdefault(o["family"], []).append(o)
        return jsonify({
            "ok": True,
            "flow": FLOW,
            "total_questions": sum(o["questions"] for o in ov),
            "total_tracks": len(TRACKS),
            "healthy_tracks": sum(1 for o in ov if o["healthy"]),
            "families": fams,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@english_track_bp.route("/api/english-track/questions")
def api_questions():
    try:
        _, _, _, _, _ = _engine()
        from engines.ai_english_track_engine import get_conn
        track = request.args.get("track", "雅思听力")
        limit = min(int(request.args.get("limit", 20)), 100)
        conn = get_conn()
        rows = conn.execute("""
            SELECT question_id, grade, difficulty, content, options, answer, explanation
            FROM question_bank WHERE subject='英语' AND grade=? AND status='published'
            ORDER BY RANDOM() LIMIT ?""", (track, limit)).fetchall()
        conn.close()
        return jsonify({"ok": True, "track": track, "count": len(rows),
                        "questions": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@english_track_bp.route("/api/english-track/expand", methods=["POST"])
def api_expand():
    try:
        TRACKS, _, generate_questions, daemon_cycle, _ = _engine()
        data = request.get_json(silent=True) or {}
        track = data.get("track", "")
        count = min(int(data.get("count", 10)), 60)
        if track:
            if track not in [t[0] for t in TRACKS]:
                return jsonify({"ok": False, "error": f"未知赛道: {track}"}), 400
            added, dup = generate_questions(track, count)
            return jsonify({"ok": True, "track": track, "added": added, "duplicates": dup})
        r = daemon_cycle()
        return jsonify({"ok": True, "mode": "daemon_cycle", **r})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@english_track_bp.route("/english-tracks")
def page_english_tracks():
    """英语赛道主页 — 返回 JSON 总览 (与 /exam-auto 同风格)"""
    return api_overview()
