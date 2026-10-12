#!/usr/bin/env python3
"""
📝 copy_studio — service (v26.0)
=================================
门面层. 串联 db + policy + generator.
审批对接: approval 中台 (通过 engines.approval 包).
"""
from __future__ import annotations
import json, uuid, time, datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from .db import get_conn, ensure_schema, db_retry
from .policy import (GENRE_CONFIG, GENRE_NOVEL, GENRE_SCRIPT, GENRE_AD_COPY,
                     assess_risk, get_sla_hours, is_llm_safe_to_auto_pass)
from .generator import (ollama_call, generate_outline, write_chapter_text, polish_text,
                        OLLAMA_OK, OLLAMA_MODEL, pick_system)
from . import (PROJECT_DRAFT, PROJECT_OUTLINING, PROJECT_WRITING,
               PROJECT_REVIEWING, PROJECT_APPROVED, PROJECT_ARCHIVED,
               CHAPTER_PENDING, CHAPTER_WRITING, CHAPTER_DONE, CHAPTER_POLISHED)

NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _new_id(prefix: str = 'copy') -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ApprovalService:
    """copy_studio 门面."""

    def __init__(self, db_path: Optional[Path | str] = None):
        ensure_schema(db_path)
        self._db_path = str(Path(db_path) if db_path else None)

    # ── 项目管理 ──

    def create_project(self, title: str, genre: str = GENRE_NOVEL,
                       sub_genre: str = '', target_words: int = 50000,
                       initiator: str = 'wuchenghao15', initiator_role: str = 'super_admin',
                       user_intent: str = '', style_guide: str = '') -> Dict[str, Any]:
        """创建项目. 返回项目 dict."""
        cfg = GENRE_CONFIG.get(genre, GENRE_CONFIG[GENRE_NOVEL])
        rid = _new_id('copy')
        risk = assess_risk(genre, target_words, initiator_role)
        now = NOW_F()
        with get_conn() as c:
            c.execute("BEGIN")
            c.execute(
                """INSERT INTO mt_copy_projects
                (project_id, title, genre, sub_genre, target_words, current_words,
                 status, initiator, initiator_role, risk_level, outline_json,
                 style_guide_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, title, genre, sub_genre or cfg.get('sub_genres', [''])[0],
                 target_words, 0, PROJECT_DRAFT, initiator, initiator_role, risk,
                 json.dumps({'user_intent': user_intent}, ensure_ascii=False),
                 json.dumps({'guide': style_guide}, ensure_ascii=False),
                 now, now))
            c.execute("COMMIT")
        return self.get_project(rid)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with get_conn() as c:
            row = c.execute(
                "SELECT * FROM mt_copy_projects WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                return None
            p = dict(row)
            # 章节统计
            ch = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(actual_words),0) FROM mt_copy_chapters WHERE project_id=?",
                (project_id,)).fetchone()
            p['total_chapters'] = ch[0]
            p['total_words'] = ch[1]
            # 角色数
            chars = c.execute(
                "SELECT COUNT(*) FROM mt_copy_characters WHERE project_id=?", (project_id,)).fetchone()[0]
            p['character_count'] = chars
            return p

    def list_projects(self, initiator: Optional[str] = None,
                      genre: Optional[str] = None,
                      status: Optional[str] = None,
                      limit: int = 50) -> List[Dict[str, Any]]:
        where, params = [], []
        if initiator:
            where.append("initiator=?"); params.append(initiator)
        if genre:
            where.append("genre=?"); params.append(genre)
        if status:
            where.append("status=?"); params.append(status)
        q = f"SELECT * FROM mt_copy_projects {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with get_conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]

    def update_project_status(self, project_id: str, status: str) -> None:
        with get_conn() as c:
            c.execute("UPDATE mt_copy_projects SET status=?, updated_at=? WHERE project_id=?",
                      (status, NOW_F(), project_id))

    # ── 大纲生成 ──

    def generate_outline(self, project_id: str) -> Optional[Dict]:
        """生成大纲, 落库 outline_json, 项目状态 → outlining."""
        p = self.get_project(project_id)
        if not p:
            return None
        outline = generate_outline(
            genre=p['genre'], title=p['title'], sub_genre=p.get('sub_genre', ''),
            target_words=p['target_words'],
            user_intent=json.loads(p.get('outline_json') or '{}').get('user_intent', ''))
        if outline is None:
            return None
        with get_conn() as c:
            c.execute("BEGIN")
            c.execute(
                "UPDATE mt_copy_projects SET outline_json=?, status=?, updated_at=? WHERE project_id=?",
                (json.dumps(outline, ensure_ascii=False), PROJECT_OUTLINING, NOW_F(), project_id))
            c.execute("COMMIT")
        return outline

    # ── 章节管理 ──

    def add_chapter(self, project_id: str, chapter_no: int, title: str = '',
                    summary: str = '', chapter_type: str = 'chapter',
                    target_words: int = 3000) -> Optional[str]:
        """添加章节条目. 返回 chapter_id."""
        cid = _new_id('chap')
        with get_conn() as c:
            c.execute(
                """INSERT INTO mt_copy_chapters
                (chapter_id, project_id, chapter_no, title, chapter_type, target_words, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (cid, project_id, chapter_no, title or f'第{chapter_no}章', chapter_type,
                 target_words, CHAPTER_PENDING, NOW_F(), NOW_F()))
        return cid

    def list_chapters(self, project_id: str) -> List[Dict[str, Any]]:
        with get_conn() as c:
            rows = c.execute(
                "SELECT * FROM mt_copy_chapters WHERE project_id=? ORDER BY chapter_no",
                (project_id,)).fetchall()
            return [dict(r) for r in rows]

    def write_chapter(self, project_id: str, chapter_id: Optional[str] = None,
                      chapter_no: Optional[int] = None) -> Optional[Dict]:
        """写单章正文 (Ollama 调用)."""
        p = self.get_project(project_id)
        if not p:
            return None
        # 定位章节
        with get_conn() as c:
            if chapter_id:
                ch_row = c.execute("SELECT * FROM mt_copy_chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
            elif chapter_no is not None:
                ch_row = c.execute(
                    "SELECT * FROM mt_copy_chapters WHERE project_id=? AND chapter_no=?",
                    (project_id, chapter_no)).fetchone()
            else:
                return None
            if not ch_row:
                return None
            ch = dict(ch_row)

            # RAG 上下文: 最近 3 章正文
            prev_texts = [dict(r)['content'] or '' for r in c.execute(
                "SELECT content FROM mt_copy_chapters WHERE project_id=? AND chapter_no<? AND content IS NOT NULL ORDER BY chapter_no DESC LIMIT 3",
                (project_id, ch['chapter_no'])).fetchall()]

            # 角色卡: 所有角色的简要
            chars = c.execute(
                "SELECT name, role_type, personality FROM mt_copy_characters WHERE project_id=?",
                (project_id,)).fetchall()
            char_briefs = [f"{r['name']}({r['role_type']}): {r['personality'] or ''}" for r in chars]

            style = json.loads(p.get('style_guide_json') or '{}').get('guide', '')

        # 调用 Ollama
        with get_conn() as c:
            c.execute("UPDATE mt_copy_chapters SET status=?, updated_at=? WHERE chapter_id=?",
                      (CHAPTER_WRITING, NOW_F(), ch['chapter_id']))

        start = time.time()
        content = write_chapter_text(
            genre=p['genre'],
            chapter_title=ch['title'] or '',
            chapter_summary=ch.get('summary') or '',
            target_words=ch['target_words'],
            context_chapter_texts=prev_texts,
            character_briefs=char_briefs,
            style_guide=style,
        )
        duration = time.time() - start

        if content is None:
            with get_conn() as c:
                c.execute("UPDATE mt_copy_chapters SET status=?, updated_at=? WHERE chapter_id=?",
                          (CHAPTER_PENDING, NOW_F(), ch['chapter_id']))
            return None

        actual_words = len(content)
        with get_conn() as c:
            c.execute("BEGIN")
            c.execute(
                """UPDATE mt_copy_chapters SET
                   content=?, actual_words=?, status=?, updated_at=?
                   WHERE chapter_id=?""",
                (content, actual_words, CHAPTER_DONE, NOW_F(), ch['chapter_id']))
            c.execute(
                "UPDATE mt_copy_projects SET current_words=COALESCE((SELECT SUM(actual_words) FROM mt_copy_chapters WHERE project_id=?),0), updated_at=?",
                (project_id, NOW_F()))
            # 写 RAG 注入日志
            if prev_texts or char_briefs:
                c.execute(
                    """INSERT INTO mt_copy_rag_inject_log
                    (project_id, chapter_id, inject_type, inject_content, tokens_estimate, created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (project_id, ch['chapter_id'], 'chapter_context',
                     json.dumps({'prev_chapters': len(prev_texts), 'characters': len(char_briefs)}, ensure_ascii=False),
                     (len(content)) // 4, NOW_F()))
            c.execute("COMMIT")

        return {
            'chapter_id': ch['chapter_id'],
            'content': content,
            'content_length': actual_words,
            'duration_sec': round(duration, 1),
            'ollama_ok': OLLAMA_OK,
            'model': OLLAMA_MODEL,
        }

    def polish_chapter(self, chapter_id: str, style_hint: str = '') -> Optional[Dict]:
        """润色章节. 自动 polish_count++."""
        with get_conn() as c:
            ch = c.execute("SELECT * FROM mt_copy_chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
            if not ch or not ch['content']:
                return None
            raw = polish_text(ch['content'], style_hint=style_hint)
            if raw is None:
                return None
            c.execute("UPDATE mt_copy_chapters SET content=?, polish_count=polish_count+1, status=?, updated_at=? WHERE chapter_id=?",
                      (raw, CHAPTER_POLISHED, NOW_F(), chapter_id))
        return {'chapter_id': chapter_id, 'polished': True}

    # ── 自巡检 (自修复) ──

    def run_consistency_check(self, project_id: str) -> List[Dict]:
        """简单规则巡检: 超长段落/对话引号不匹配/角色名前后不一致.
        复杂语义一致性留 P3 daemon. 返回发现的 issue 列表."""
        issues = []
        with get_conn() as c:
            chapters = [dict(r) for r in c.execute(
                "SELECT * FROM mt_copy_chapters WHERE project_id=? AND content IS NOT NULL ORDER BY chapter_no",
                (project_id,)).fetchall()]
            # 角色名 (取前 5 个字符)
            char_names = {r['name'][:4] for r in c.execute(
                "SELECT name FROM mt_copy_characters WHERE project_id=?", (project_id,)).fetchall()}

        for ch in chapters:
            text = ch['content'] or ''
            # 对话引号不匹配
            if text.count('"') % 2 != 0 or text.count('"') % 2 != 0:
                issues.append({
                    'project_id': project_id, 'chapter_id': ch['chapter_id'],
                    'issue_type': 'dialogue_mark', 'severity': 'medium',
                    'description': f'对话引号奇数 (双引号:{text.count(chr(34))}, 中文引号:{text.count(chr(201))+text.count(chr(202))})',
                })
            # 超长段落 (>2000 字无换行)
            for para in text.split('\n'):
                if len(para) > 2000:
                    issues.append({
                        'project_id': project_id, 'chapter_id': ch['chapter_id'],
                        'issue_type': 'overlong_paragraph', 'severity': 'low',
                        'description': f'超长段落 {len(para)} 字 (>2000)',
                    })
                    break

        # 落库
        if issues:
            with get_conn() as c:
                c.executemany(
                    """INSERT INTO mt_copy_consistency_log
                    (project_id, chapter_id, issue_type, severity, description, created_at)
                    VALUES (:project_id, :chapter_id, :issue_type, :severity, :description, :created_at)""",
                    [{**i, 'created_at': NOW_F()} for i in issues])

        return issues

    # ── 审批对接 ──

    def submit_for_approval(self, project_id: str, reason: str = '') -> Optional[str]:
        """提交 approval 中台. 返回 approval_id."""
        p = self.get_project(project_id)
        if not p:
            return None
        try:
            from engines.approval import ApprovalService as _ApprSvc, ensure_schema as _ensure
            _ensure()
            svc = _ApprSvc()
            aid = svc.submit(
                category='copy_studio',
                subject_id=project_id,
                title=f"{p['title']} ({GENRE_CONFIG.get(p['genre'],{}).get('label','文案')})",
                initiator=p['initiator'],
                initiator_role=p['initiator_role'],
                risk_level=p['risk_level'],
                sla_hours=get_sla_hours(p['risk_level']),
                reason=reason,
                genre=p['genre'],
                target_words=p['target_words'],
                current_words=p.get('current_words', 0),
            )
        except ImportError:
            return None

        with get_conn() as c:
            c.execute("UPDATE mt_copy_projects SET approval_id=?, status=?, updated_at=? WHERE project_id=?",
                      (aid, PROJECT_REVIEWING, NOW_F(), project_id))
        return aid

    # ── 统计 ──

    def stats(self) -> Dict[str, Any]:
        with get_conn() as c:
            total = c.execute("SELECT COUNT(*) FROM mt_copy_projects").fetchone()[0]
            by_genre = {r[0]: r[1] for r in c.execute(
                "SELECT genre, COUNT(*) FROM mt_copy_projects GROUP BY genre").fetchall()}
            by_status = {r[0]: r[1] for r in c.execute(
                "SELECT status, COUNT(*) FROM mt_copy_projects GROUP BY status").fetchall()}
            total_words = c.execute(
                "SELECT COALESCE(SUM(current_words),0) FROM mt_copy_projects").fetchone()[0]
            consistency_issues = c.execute(
                "SELECT COUNT(*) FROM mt_copy_consistency_log").fetchone()[0]
        return {
            'ollama_ok': OLLAMA_OK, 'ollama_model': OLLAMA_MODEL,
            'projects_total': total, 'by_genre': by_genre, 'by_status': by_status,
            'total_words_written': total_words, 'consistency_issues': consistency_issues,
        }
