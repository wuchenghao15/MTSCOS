#!/usr/bin/env python3
"""
japanese_api.py — 日语学习 Flask Blueprint v25.1

Endpoints:
  GET  /api/japanese/listening          List + filter (level, accent, profession)
  GET  /api/japanese/listening/<id>     Detail + audio_url + questions
  POST /api/japanese/listening/<id>/submit  Submit answer + record progress
  GET  /api/japanese/voice_profiles     All 10 speaker profiles
  GET  /api/japanese/vocabulary         List + filter (level)
  GET  /api/japanese/grammar            List + filter (level)
  GET  /api/japanese/reading            List + filter (level)
  GET  /api/japanese/cloud_engines      5 cloud engine registry

Author: Andromeda Sigma
"""
import os, json, uuid
from flask import Blueprint, jsonify, request, g

japanese_api = Blueprint("japanese_api", __name__)


def _db():
    """Use app.db (both local Mac mini and production)."""
    import sqlite3
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.environ.get("APP_DB", os.path.join(base, "engines", "app.db"))
    return sqlite3.connect(db_path, timeout=10)


def _row_to_dict(cursor, row):
    col_names = [d[0] for d in cursor.description]
    return dict(zip(col_names, row))


# ═══════════════════════════════════════════════════════════
# Listening Endpoints
# ═══════════════════════════════════════════════════════════

@japanese_api.route("/api/japanese/listening")
def list_listening():
    """List listening materials with filters."""
    level = request.args.get("level", "")   # N5-N1
    accent = request.args.get("accent", "")  # KANTO/KANSAI
    vp_id = request.args.get("voice_profile", "")
    limit = int(request.args.get("limit", "50"))
    
    c = _db()
    sql = ["SELECT listening_id, title, level, listening_type, accent, speaker_gender, speaker_age_group, speaker_profession, voice_profile_id, audio_path, questions_json, difficulty FROM jp_listening WHERE 1=1"]
    params = []
    
    if level:
        sql.append("AND level=?")
        params.append(level)
    if accent:
        sql.append("AND accent=?")
        params.append(accent)
    if vp_id:
        sql.append("AND voice_profile_id=?")
        params.append(vp_id)
    
    sql.append("ORDER BY difficulty ASC LIMIT ?")
    params.append(limit)
    
    rows = c.execute(" ".join(sql), params).fetchall()
    results = []
    for r in rows:
        d = _row_to_dict(c.execute("SELECT 1"), r) if False else None
        # Manual dict
        keys = ["listening_id", "title", "level", "listening_type", "accent", 
                "speaker_gender", "speaker_age_group", "speaker_profession",
                "voice_profile_id", "audio_path", "questions_json", "difficulty"]
        item = dict(zip(keys, r))
        if item.get("questions_json"):
            try:
                item["questions"] = json.loads(item["questions_json"])
            except:
                item["questions"] = []
        item.pop("questions_json", None)
        results.append(item)
    c.close()
    return jsonify({"status": "ok", "count": len(results), "data": results})


@japanese_api.route("/api/japanese/listening/<lid>")
def get_listening(lid):
    """Get single listening detail with transcript."""
    c = _db()
    row = c.execute("SELECT * FROM jp_listening WHERE listening_id=?", (lid,)).fetchone()
    if not row:
        c.close()
        return jsonify({"status": "not_found"}), 404
    cols = [d[0] for d in c.description]
    item = dict(zip(cols, row))
    for jf in ["questions_json", "tags_json"]:
        if item.get(jf):
            try: item[jf.replace("_json", "")] = json.loads(item[jf])
            except: pass
        item.pop(jf, None)
    
    # Attach voice profile
    vp = c.execute("SELECT * FROM mt_jp_voice_profiles WHERE vp_id=?", (item.get("voice_profile_id", ""),)).fetchone()
    if vp:
        vp_cols = [d[0] for d in c.description]
        item["voice_profile"] = dict(zip(vp_cols, vp))
    
    c.close()
    return jsonify({"status": "ok", "data": item})


@japanese_api.route("/api/japanese/listening/<lid>/submit", methods=["POST"])
def submit_listening_answer(lid):
    """Submit answer and record progress."""
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or str(g.get("user_id", "anonymous"))
    selected = data.get("answer")
    score = data.get("score", 0)
    accuracy = data.get("accuracy", 0)
    
    c = _db()
    c.execute("""
        INSERT INTO jp_listening_records (user_id, listening_id, level, score, accuracy, submitted_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (user_id, lid, data.get("level", ""), score, accuracy))
    c.commit()
    c.close()
    return jsonify({"status": "ok", "recorded": True})


# ═══════════════════════════════════════════════════════════
# Voice Profile Endpoint
# ═══════════════════════════════════════════════════════════

@japanese_api.route("/api/japanese/voice_profiles")
def list_voice_profiles():
    """All 10 speaker characters."""
    c = _db()
    rows = c.execute("SELECT * FROM mt_jp_voice_profiles ORDER BY accent, age_group").fetchall()
    cols = [d[0] for d in c.description]
    results = [dict(zip(cols, r)) for r in rows]
    
    # Count listening per profile
    for item in results:
        n = c.execute("SELECT COUNT(*) FROM jp_listening WHERE voice_profile_id=?", (item["vp_id"],)).fetchone()[0]
        item["listening_count"] = n
    c.close()
    return jsonify({"status": "ok", "count": len(results), "data": results})


# ═══════════════════════════════════════════════════════════
# Vocabulary / Grammar / Reading
# ═══════════════════════════════════════════════════════════

@japanese_api.route("/api/japanese/vocabulary")
def list_vocabulary():
    level = request.args.get("level", "")
    limit = int(request.args.get("limit", "100"))
    c = _db()
    sql = "SELECT word_id, word, kana, kanji, romanji, meaning_cn, level, example_jp, example_cn FROM jp_vocabulary"
    params = []
    if level:
        sql += " WHERE level=?"
        params.append(level)
    sql += " ORDER BY level, word_id LIMIT ?"
    params.append(limit)
    rows = c.execute(sql, params).fetchall()
    cols = [d[0] for d in c.description]
    c.close()
    return jsonify({"status": "ok", "count": len(rows), "data": [dict(zip(cols, r)) for r in rows]})


@japanese_api.route("/api/japanese/grammar")
def list_grammar():
    level = request.args.get("level", "")
    limit = int(request.args.get("limit", "100"))
    c = _db()
    sql = "SELECT grammar_id, title, pattern, meaning_cn, grammar_type, level, explanation, example_jp, example_cn FROM jp_grammar"
    params = []
    if level:
        sql += " WHERE level=?"
        params.append(level)
    sql += " ORDER BY level, grammar_id LIMIT ?"
    params.append(limit)
    rows = c.execute(sql, params).fetchall()
    cols = [d[0] for d in c.description]
    c.close()
    return jsonify({"status": "ok", "count": len(rows), "data": [dict(zip(cols, r)) for r in rows]})


@japanese_api.route("/api/japanese/reading")
def list_reading():
    level = request.args.get("level", "")
    limit = int(request.args.get("limit", "50"))
    c = _db()
    sql = "SELECT reading_id, title, level, reading_type, content_jp, content_cn FROM jp_reading"
    params = []
    if level:
        sql += " WHERE level=?"
        params.append(level)
    sql += " ORDER BY level LIMIT ?"
    params.append(limit)
    rows = c.execute(sql, params).fetchall()
    cols = [d[0] for d in c.description]
    c.close()
    return jsonify({"status": "ok", "count": len(rows), "data": [dict(zip(cols, r)) for r in rows]})


# ═══════════════════════════════════════════════════════════
# Cloud Engine Registry (5 AI engines)
# ═══════════════════════════════════════════════════════════

@japanese_api.route("/api/japanese/cloud_engines")
def list_cloud_engines():
    c = _db()
    rows = c.execute("SELECT * FROM mt_ai_cloud_engine_registry ORDER BY priority").fetchall()
    cols = [d[0] for d in c.description]
    results = []
    for r in rows:
        item = dict(zip(cols, r))
        for jf in ["capability_tags", "fallback_detail"]:
            if item.get(jf):
                try: item[jf.replace("_tags", "").replace("_detail", "")] = json.loads(item[jf])
                except: pass
        results.append(item)
    c.close()
    return jsonify({"status": "ok", "count": len(results), "data": results})
