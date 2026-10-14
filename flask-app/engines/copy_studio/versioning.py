#!/usr/bin/env python3
"""
📝 copy_studio — versioning (v26.0 Step3)
========================================
SnapshotMixin: 章节版本快照 / 列表 / 回滚的可复用基类.
可被 ApprovalService / 其他中台门面继承 (approval 中台将来也能接).

Hook 位置:
  - _save_written_chapter 覆盖 content 前 → take_snapshot('auto_write')
  - polish_chapter 覆盖 content 前        → take_snapshot('polish')
  - restore_version 回滚时                → 先对当前版本 take_snapshot('manual_restore') 防丢
"""
from __future__ import annotations
import uuid, datetime
from typing import List, Dict, Any, Optional

_NOW = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
_NEW_ID = lambda prefix: f"{prefix}_{uuid.uuid4().hex[:12]}"


class SnapshotMixin:
    """章节版本快照能力. 混入依赖: 子类已 self._db_path (str|None) + get_conn (模块级函数)."""

    def _conn(self):
        from .db import get_conn
        return get_conn(getattr(self, '_db_path', None))

    # ── 快照核心 ──

    def take_snapshot(self, chapter_id: str, trigger_type: str = 'auto',
                      ai_worker_role: str = '', note: str = '') -> Optional[int]:
        """对章节当前 content 拍快照. content 为空 (从未写过) 时跳过. 返回 version_no 或 None."""
        with self._conn() as c:
            ch = c.execute("SELECT content, actual_words, ai_worker_role FROM mt_copy_chapters WHERE chapter_id=?",
                           (chapter_id,)).fetchone()
            if not ch or not (ch['content'] or '').strip():
                return None
            # 查下一个 version_no
            row = c.execute(
                "SELECT COALESCE(MAX(version_no),0)+1 FROM mt_copy_chapter_versions WHERE chapter_id=?",
                (chapter_id,)).fetchone()
            vno = row[0] if row else 1
            ver_id = _NEW_ID('ver')
            c.execute(
                """INSERT INTO mt_copy_chapter_versions
                (version_id, chapter_id, version_no, content, actual_words,
                 trigger_type, ai_worker_role, note, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (ver_id, chapter_id, vno, ch['content'], ch['actual_words'] or 0,
                 trigger_type, ai_worker_role or ch['ai_worker_role'] or '', note, _NOW()))
        return vno

    # ── 查询 ──

    def list_versions(self, chapter_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT version_id, version_no, actual_words, trigger_type,
                          ai_worker_role, note, created_at
                   FROM mt_copy_chapter_versions
                   WHERE chapter_id=? ORDER BY version_no DESC LIMIT ?""",
                (chapter_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute(
                """SELECT v.*, ch.chapter_id, ch.title, ch.project_id
                   FROM mt_copy_chapter_versions v
                   JOIN mt_copy_chapters ch ON ch.chapter_id = v.chapter_id
                   WHERE v.version_id=?""",
                (version_id,)).fetchone()
            return dict(row) if row else None

    # ── 回滚 ──

    def restore_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """将章节 content 回滚到指定版本. 回滚前自动对当前 content 再拍一张 'manual_restore' 快照."""
        ver = self.get_version(version_id)
        if not ver:
            return None
        chapter_id = ver['chapter_id']
        # 先保护当前版本
        self.take_snapshot(chapter_id, trigger_type='manual_restore',
                           note=f"回滚前自动备份 → v{ver['version_no']}")
        with self._conn() as c:
            c.execute(
                """UPDATE mt_copy_chapters SET
                   content=?, actual_words=?, status='done', updated_at=?
                   WHERE chapter_id=?""",
                (ver['content'], ver['actual_words'], _NOW(), chapter_id))
        return {
            'chapter_id': chapter_id,
            'restored_from_version': ver['version_no'],
            'restored_from_version_id': version_id,
            'actual_words': ver['actual_words'],
        }

    # ── 辅助: 章节版本总数 ──

    def version_count(self, chapter_id: str) -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM mt_copy_chapter_versions WHERE chapter_id=?",
                (chapter_id,)).fetchone()[0]
