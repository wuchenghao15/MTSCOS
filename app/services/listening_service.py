#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
listening_service — 听力题持久化服务 (轻量兼容骨架)
---------------------------------------------------
模块由 ai_enterprise_api 间接依赖：
  app.api.ai_enterprise_api
    -> ai_engines.management.ai_employee_manager
       -> ai_engines.listening_question_employee
          -> from app.services.listening_service import listening_service

实现要点：
- 不做重量级依赖，确保 import 链打通；
- 所有 DB 操作走 core.db_path.get_db_path("app.db") 并使用列级 try/except，
  缺失表时自动建表；
- 返回结构保持字典稳定，避免上层 AttributeError。
"""

import os
import sys
import time
import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional

_LOCK = threading.Lock()

def _get_db():
    from core.db_path import get_db_path
    return get_db_path('app.db')

def _ensure_schema(conn):
    """懒创建表 —— 仅当缺失时执行，避免多次写。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listening_questions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            question_uid  TEXT UNIQUE,
            subject       TEXT,
            difficulty    TEXT,
            language      TEXT,
            audio_url     TEXT,
            transcript    TEXT,
            options_json  TEXT,
            answer        TEXT,
            explanation   TEXT,
            duration_sec  INTEGER DEFAULT 0,
            tags_json     TEXT,
            status        TEXT DEFAULT 'active',
            created_by    TEXT,
              created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


class ListeningService:
    """听力服务：CRUD 听力题，内存兜底 + SQLite 持久化。"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ---------- 内部辅助 ----------
    def _conn(self):
        db_path = _get_db()
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            _ensure_schema(conn)
        except Exception:
            pass
        return conn

    # ---------- 对外 CRUD ----------
    def add_listening_question(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """添加一道听力题，兼容任意字段字典。"""
        if not isinstance(data, dict):
            return {"success": False, "error": "data 必须是 dict"}
        uid = data.get("question_uid") or ("LQ-%d-%d" % (int(time.time()), os.getpid() % 10000))
        row = {
            "question_uid": uid,
            "subject": data.get("subject", ""),
            "difficulty": data.get("difficulty", "medium"),
            "language": data.get("language", "chinese"),
            "audio_url": data.get("audio_url", ""),
            "transcript": data.get("transcript", ""),
            "options_json": json.dumps(data.get("options", []), ensure_ascii=False),
            "answer": json.dumps(data.get("answer") or data.get("correct_answer") or "", ensure_ascii=False),
            "explanation": data.get("explanation", ""),
            "duration_sec": int(data.get("duration_sec") or 0),
            "tags_json": json.dumps(data.get("tags", []), ensure_ascii=False),
            "status": data.get("status", "active"),
            "created_by": data.get("created_by", "system"),
        }
        with _LOCK:
            self._cache[uid] = row
            try:
                with self._conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO listening_questions
                           (question_uid, subject, difficulty, language, audio_url, transcript,
                            options_json, answer, explanation, duration_sec, tags_json,
                            status, created_by)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (row["question_uid"], row["subject"], row["difficulty"],
                         row["language"], row["audio_url"], row["transcript"],
                         row["options_json"], row["answer"], row["explanation"],
                         row["duration_sec"], row["tags_json"],
                         row["status"], row["created_by"]),
                    )
                    conn.commit()
            except Exception:
                # DB 不可用时回退到仅内存缓存（保证调用方流程不中断）
                pass
        return {"success": True, "question_uid": uid, "data": row}

    def get_listening_question(self, question_uid: str) -> Optional[Dict[str, Any]]:
        with _LOCK:
            if question_uid in self._cache:
                return dict(self._cache[question_uid])
        try:
            with self._conn() as conn:
                r = conn.execute(
                    "SELECT * FROM listening_questions WHERE question_uid=?",
                    (question_uid,),
                ).fetchone()
                if r:
                    return {k: r[k] for k in r.keys()}
        except Exception:
            pass
        return None

    def list_listening_questions(self, subject=None, difficulty=None, limit=100, offset=0) -> List[Dict[str, Any]]:
        q = "SELECT * FROM listening_questions WHERE 1=1"
        args = []
        if subject:
            q += " AND subject=?"
            args.append(subject)
        if difficulty:
            q += " AND difficulty=?"
            args.append(difficulty)
        q += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args.extend([int(limit), int(offset)])
        try:
            with self._conn() as conn:
                rows = conn.execute(q, args).fetchall()
                return [{k: r[k] for k in r.keys()} for r in rows]
        except Exception:
            with _LOCK:
                return list(self._cache.values())[:limit]

    def search(self, keyword: str, limit=50) -> List[Dict[str, Any]]:
        rows = self.list_listening_questions(limit=max(500, limit))
        if not keyword:
            return rows[:limit]
        kw = keyword.lower()
        hits = []
        for r in rows:
            blob = (" ".join(str(v) for v in r.values())).lower()
            if kw in blob:
                hits.append(r)
                if len(hits) >= limit:
                    break
        return hits

    def delete(self, question_uid: str) -> bool:
        with _LOCK:
            self._cache.pop(question_uid, None)
            try:
                with self._conn() as conn:
                    conn.execute("DELETE FROM listening_questions WHERE question_uid=?", (question_uid,))
                    conn.commit()
            except Exception:
                pass
        return True

    def stats(self) -> Dict[str, Any]:
        total = 0
        try:
            with self._conn() as conn:
                total = conn.execute("SELECT COUNT(*) FROM listening_questions").fetchone()[0]
        except Exception:
            with _LOCK:
                total = len(self._cache)
        return {"total": total, "cached": len(self._cache)}


# 单例：兼容 "from app.services.listening_service import listening_service"
listening_service = ListeningService()

__all__ = ["listening_service", "ListeningService"]
