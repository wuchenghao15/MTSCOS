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
# [unused] from .db import get_conn, ensure_schema, db_retry
from .policy import (GENRE_CONFIG, GENRE_NOVEL, GENRE_SCRIPT, GENRE_AD_COPY,
                     assess_risk, get_sla_hours, is_llm_safe_to_auto_pass)
from .generator import (ollama_call, generate_outline, write_chapter_text,
                        write_chapter_text_stream, polish_text,
                        OLLAMA_OK, OLLAMA_MODEL, pick_system)
from .versioning import SnapshotMixin
from . import (PROJECT_DRAFT, PROJECT_OUTLINING, PROJECT_WRITING,
               PROJECT_REVIEWING, PROJECT_APPROVED, PROJECT_ARCHIVED,
               CHAPTER_PENDING, CHAPTER_WRITING, CHAPTER_DONE, CHAPTER_POLISHED)
from .rag import search_chunks, upsert_chunks, format_chunks_for_prompt
# [unused] from .semanticaudit import audit_chapters

NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _new_id(prefix: str = 'copy') -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ApprovalService(SnapshotMixin):
    """copy_studio 门面. 继承 SnapshotMixin 获得章节版本快照能力."""

    def __init__(self, db_path: Optional[Path | str] = None):
        ensure_schema(db_path)
        self._db_path = str(Path(db_path)) if db_path else None

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
        """生成大纲, 落库 outline_json, 项目状态 → outlining. 角色自动落角色卡草稿."""
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
        # Step2: 大纲角色 → mt_copy_characters 草稿 (按名字去重, 不覆盖已有人设)
        try:
            self._sync_characters_from_outline(project_id, outline)
        except Exception as e:
            print(f"  [copy_studio] 角色草稿落库失败 (不阻断): {e}")
        return outline

    # ── 角色卡管理 (Step2) ──

    def _sync_characters_from_outline(self, project_id: str, outline: Dict) -> int:
        """大纲 characters → 角色卡草稿. 按名字去重, 已有角色不覆盖. 返回新增数."""
        chars = outline.get('characters') if isinstance(outline, dict) else None
        if not isinstance(chars, list):
            return 0
        added = 0
        with get_conn() as c:
            existing = {r['name'] for r in c.execute(
                "SELECT name FROM mt_copy_characters WHERE project_id=?", (project_id,)).fetchall()}
            for ch in chars:
                if not isinstance(ch, dict):
                    continue
                name = str(ch.get('name') or '').strip()
                if not name or name in existing:
                    continue
                existing.add(name)
                c.execute(
                    """INSERT INTO mt_copy_characters
                    (character_id, project_id, name, role_type, personality, backstory, goals, created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (_new_id('char'), project_id, name,
                     str(ch.get('role_type') or 'supporting'),
                     str(ch.get('personality') or ''),
                     str(ch.get('backstory') or ''),
                     str(ch.get('goal') or ch.get('goals') or ''), NOW_F()))
                added += 1
        return added

    def list_characters(self, project_id: str) -> List[Dict[str, Any]]:
        with get_conn() as c:
            rows = c.execute(
                "SELECT * FROM mt_copy_characters WHERE project_id=? ORDER BY created_at",
                (project_id,)).fetchall()
            return [dict(r) for r in rows]

    def create_character(self, project_id: str, name: str,
                         role_type: str = 'supporting', personality: str = '',
                         appearance: str = '', backstory: str = '', goals: str = '',
                         conflicts: str = '', relationships: str = '',
                         tags: str = '') -> Optional[Dict[str, Any]]:
        """新建角色卡. relationships/tags 接受逗号分隔字符串, 存 JSON."""
        if not name or not name.strip():
            return None
        cid = _new_id('char')
        with get_conn() as c:
            c.execute(
                """INSERT INTO mt_copy_characters
                (character_id, project_id, name, role_type, personality, appearance,
                 backstory, goals, conflicts, relationships_json, tags_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, project_id, name.strip(), role_type or 'supporting',
                 personality, appearance, backstory, goals, conflicts,
                 json.dumps([s.strip() for s in (relationships or '').split(',') if s.strip()], ensure_ascii=False),
                 json.dumps([s.strip() for s in (tags or '').split(',') if s.strip()], ensure_ascii=False),
                 NOW_F()))
        return self.get_character(cid)

    def get_character(self, character_id: str) -> Optional[Dict[str, Any]]:
        with get_conn() as c:
            row = c.execute("SELECT * FROM mt_copy_characters WHERE character_id=?",
                            (character_id,)).fetchone()
            return dict(row) if row else None

    _CHAR_FIELDS = {'name', 'role_type', 'personality', 'appearance', 'backstory',
                    'goals', 'conflicts', 'relationships_json', 'tags_json'}

    def update_character(self, character_id: str, **fields) -> Optional[Dict[str, Any]]:
        """更新角色卡 (白名单字段)."""
        sets, params = [], []
        for k, v in fields.items():
            if k in self._CHAR_FIELDS and v is not None:
                sets.append(f"{k}=?")
                params.append(str(v))
        if not sets:
            return self.get_character(character_id)
        params.append(character_id)
        with get_conn() as c:
            c.execute(f"UPDATE mt_copy_characters SET {', '.join(sets)} WHERE character_id=?",
                      tuple(params))
        return self.get_character(character_id)

    def delete_character(self, character_id: str) -> bool:
        with get_conn() as c:
            cur = c.execute("DELETE FROM mt_copy_characters WHERE character_id=?",
                            (character_id,))
            return cur.rowcount > 0

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

    def _prepare_chapter_context(self, project_id: str, chapter_id: Optional[str] = None,
                                 chapter_no: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """定位章节 + 收集 RAG 上下文 (write_chapter / write_chapter_stream 共用)."""
        p = self.get_project(project_id)
        if not p:
            return None
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

            # v26.0 Step4: Embedding RAG 跨章节检索 (降级友好, 任何异常都不阻断)
            rag_text = ''
            try:
                q_parts = [ch.get('title', ''), ch.get('summary', '')]
                q_parts += char_briefs[:3]
                if prev_texts:
                    q_parts.append((prev_texts[0] or '')[:100])
                q = ' '.join(p for p in q_parts if p).strip()
                if q and len(q) > 5:
                    chunks = search_chunks(q, project_id, limit=3,
                                           exclude_chapter_id=ch['chapter_id'])
                    rag_text = format_chunks_for_prompt(chunks)
            except Exception as e:
                print(f"  [copy_studio] RAG search fallback (不阻断): {e}")

        return {'project': p, 'chapter': ch, 'prev_texts': prev_texts,
                'char_briefs': char_briefs, 'style': style, 'rag_text': rag_text}

    def _save_written_chapter(self, project_id: str, ch: Dict, content: str,
                              duration: float, prev_texts: Optional[List[str]] = None,
                              char_briefs: Optional[List[str]] = None,
                              rag_text: str = '') -> Dict[str, Any]:
        """章节正文落库 + 项目字数汇总 + RAG 注入日志 + 写前快照旧版本 + 写后 chunk 入库.
        返回 result dict."""
        # v26.0 Step3: 写前快照旧版本 (首次写则 content 为空, take_snapshot 自动跳过)
        prev_version_no = self.take_snapshot(ch['chapter_id'], trigger_type='auto_write')
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
                     json.dumps({'prev_chapters': len(prev_texts or []),
                                 'characters': len(char_briefs or []),
                                 'rag_chunks_used': bool(rag_text)}, ensure_ascii=False),
                     actual_words // 4, NOW_F()))
            c.execute("COMMIT")
        # v26.0 Step4: 写后自动 chunk + embedding 入库 (任何异常不阻断)
        n_chunks = 0
        try:
            n_chunks = upsert_chunks(project_id, ch['chapter_id'], content)
        except Exception as e:
            print(f"  [copy_studio] upsert_chunks fallback (不阻断): {e}")
        return {
            'chapter_id': ch['chapter_id'],
            'content': content,
            'content_length': actual_words,
            'duration_sec': round(duration, 1),
            'prev_version_no': prev_version_no,  # None = 首次写 (无旧版本)
            'version_count_after': self.version_count(ch['chapter_id']),
            'rag_info': {
                'rag_chunks_used': bool(rag_text),
                'n_chunks_indexed': n_chunks,
            },
        }

    def write_chapter(self, project_id: str, chapter_id: Optional[str] = None,
                      chapter_no: Optional[int] = None) -> Optional[Dict]:
        """写单章正文 (Ollama 阻塞式调用)."""
        ctx = self._prepare_chapter_context(project_id, chapter_id, chapter_no)
        if not ctx:
            return None
        p, ch = ctx['project'], ctx['chapter']

        with get_conn() as c:
            c.execute("UPDATE mt_copy_chapters SET status=?, updated_at=? WHERE chapter_id=?",
                      (CHAPTER_WRITING, NOW_F(), ch['chapter_id']))

        start = time.time()
        content = write_chapter_text(
            genre=p['genre'],
            chapter_title=ch['title'] or '',
            chapter_summary=ch.get('summary') or '',
            target_words=ch['target_words'],
            context_chapter_texts=ctx['prev_texts'],
            character_briefs=ctx['char_briefs'],
            style_guide=ctx['style'],
            sub_genre=p.get('sub_genre') or '',
            rag_chunks_text=ctx.get('rag_text', ''),
        )
        duration = time.time() - start

        if content is None:
            with get_conn() as c:
                c.execute("UPDATE mt_copy_chapters SET status=?, updated_at=? WHERE chapter_id=?",
                          (CHAPTER_PENDING, NOW_F(), ch['chapter_id']))
            return None

        result = self._save_written_chapter(project_id, ch, content, duration,
                                            prev_texts=ctx['prev_texts'],
                                            char_briefs=ctx['char_briefs'],
                                            rag_text=ctx.get('rag_text', ''))
        result['ollama_ok'] = OLLAMA_OK
        result['model'] = OLLAMA_MODEL
        return result

    def write_chapter_stream(self, project_id: str, chapter_id: Optional[str] = None,
                             chapter_no: Optional[int] = None):
        """流式写单章正文. 返回事件 generator (yield {'type': 'chunk'|'done'|'error', ...});
        章节不存在返回 None. Ollama 离线或生成失败时 yield error 事件并回滚章节状态."""
        ctx = self._prepare_chapter_context(project_id, chapter_id, chapter_no)
        if not ctx:
            return None
        p, ch = ctx['project'], ctx['chapter']

        with get_conn() as c:
            c.execute("UPDATE mt_copy_chapters SET status=?, updated_at=? WHERE chapter_id=?",
                      (CHAPTER_WRITING, NOW_F(), ch['chapter_id']))

        def _gen():
            start = time.time()
            pieces: List[str] = []
            failed = False
            for piece in write_chapter_text_stream(
                    genre=p['genre'],
                    chapter_title=ch['title'] or '',
                    chapter_summary=ch.get('summary') or '',
                    target_words=ch['target_words'],
                    context_chapter_texts=ctx['prev_texts'],
                    character_briefs=ctx['char_briefs'],
                    style_guide=ctx['style'],
                    sub_genre=p.get('sub_genre') or '',
                    rag_chunks_text=ctx.get('rag_text', '')):
                if piece is None:
                    failed = True
                    break
                pieces.append(piece)
                yield {'type': 'chunk', 'text': piece}
            duration = time.time() - start
            content = ''.join(pieces)
            if failed or not content.strip():
                with get_conn() as c2:
                    c2.execute("UPDATE mt_copy_chapters SET status=?, updated_at=? WHERE chapter_id=?",
                               (CHAPTER_PENDING, NOW_F(), ch['chapter_id']))
                yield {'type': 'error', 'msg': 'Ollama 离线或生成失败'}
                return
            result = self._save_written_chapter(project_id, ch, content, duration,
                                                prev_texts=ctx['prev_texts'],
                                                char_briefs=ctx['char_briefs'],
                                                rag_text=ctx.get('rag_text', ''))
            result['ollama_ok'] = OLLAMA_OK
            result['model'] = OLLAMA_MODEL
            yield {'type': 'done', 'data': result}

        return _gen()

    def polish_chapter(self, chapter_id: str, style_hint: str = '') -> Optional[Dict]:
        """润色章节. 自动 polish_count++. 润色前对旧 content 拍版本快照."""
        with get_conn() as c:
            ch = c.execute("SELECT * FROM mt_copy_chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
            if not ch or not ch['content']:
                return None
            raw = polish_text(ch['content'], style_hint=style_hint)
            if raw is None:
                return None
            # v26.0 Step3: 润色前快照旧版本
            vno = self.take_snapshot(chapter_id, trigger_type='polish',
                                     note=style_hint or '')
            c.execute("UPDATE mt_copy_chapters SET content=?, polish_count=polish_count+1, status=?, updated_at=? WHERE chapter_id=?",
                      (raw, CHAPTER_POLISHED, NOW_F(), chapter_id))
        # v26.0 Step4: 润色后重新 chunk + embedding 入库
        try:
            upsert_chunks(ch['project_id'], chapter_id, raw)
        except Exception:
            pass
        return {'chapter_id': chapter_id, 'polished': True, 'version_no_before_polish': vno}

    # ── 自巡检 (自修复) ──

    def run_consistency_check(self, project_id: str, auto_fix: bool = False) -> List[Dict]:
        """语义一致性巡检 (5 规则): AI 腔 / 人称漂移 / 角色名漂移 / 标点 / 跨章重复.
        旧规则 (引号/超长段落) 保留 + 新版追加. 返回 issue 列表.
        auto_fix=True 时, 对可自动修复的规则 (AI 腔/半角标点) 生成 fix_content 草案.
        自动修复草案不直接覆盖正文, 仅供人类确认."""
        from .semanticaudit import audit_chapters as _audit
        issues = []
        with get_conn() as c:
            chapters = [dict(r) for r in c.execute(
                "SELECT * FROM mt_copy_chapters WHERE project_id=? AND content IS NOT NULL ORDER BY chapter_no",
                (project_id,)).fetchall()]
            char_names = [r['name'] for r in c.execute(
                "SELECT name FROM mt_copy_characters WHERE project_id=?", (project_id,)).fetchall()]

        for ch in chapters:
            text = ch['content'] or ''
            # ── 旧规则保留 ──
            if text.count('"') % 2 != 0 or text.count('"') % 2 != 0:
                issues.append({
                    'project_id': project_id, 'chapter_id': ch['chapter_id'],
                    'issue_type': 'dialogue_mark', 'severity': 'medium',
                    'description': f'对话引号奇数',
                    'suggestion': '成对补全缺失引号',
                })
            for para in text.split('\n'):
                if len(para) > 2000:
                    issues.append({
                        'project_id': project_id, 'chapter_id': ch['chapter_id'],
                        'issue_type': 'overlong_paragraph', 'severity': 'low',
                        'description': f'超长段落 {len(para)} 字',
                        'suggestion': '按语义断点拆成多段',
                    })
                    break

        # ── 新版语义巡检 (5 规则) ──
        smt_issues = _audit(chapters, char_names=char_names)
        for iss in smt_issues:
            iss['project_id'] = project_id
            iss.setdefault('suggestion', '')
            issues.append(iss)

        # ── 自动修复草案 (可选) ──
        if auto_fix:
            for iss in issues:
                fix = self._auto_fix_draft(iss, chapters)
                if fix:
                    iss['auto_fix_status'] = 'draft_ready'
                    iss['fixed_content'] = fix
                else:
                    iss['auto_fix_status'] = 'manual_needed'

        # 落库
        if issues:
            _ts = NOW_F()
            with get_conn() as c:
                c.executemany(
                    """INSERT INTO mt_copy_consistency_log
                    (project_id, chapter_id, issue_type, severity, description, suggestion,
                     auto_fix_status, fixed_content, created_at)
                    VALUES (:project_id, :chapter_id, :issue_type, :severity, :description,
                            :suggestion, :auto_fix_status, :fixed_content, :created_at)""",
                    [{**i, 'created_at': _ts,
                      'auto_fix_status': i.get('auto_fix_status', 'pending'),
                      'fixed_content': i.get('fixed_content'),
                      'suggestion': i.get('suggestion', '')} for i in issues])
                # 反查 log_id (executemany 无法直接拿到自增 id)
                rows = c.execute(
                    """SELECT log_id, issue_type, description FROM mt_copy_consistency_log
                       WHERE project_id=? AND created_at=?""", (project_id, _ts)).fetchall()
                id_map = {(dict(r)['issue_type'], dict(r)['description']): dict(r)['log_id'] for r in rows}
            for iss in issues:
                iss['log_id'] = id_map.get((iss.get('issue_type'), iss.get('description')))

        return issues

    def _auto_fix_draft(self, issue: Dict, chapters: List[Dict]) -> Optional[str]:
        """根据 issue 类型生成修复草案. 仅处理可安全自动替换的规则."""
        itype = issue.get('issue_type', '')
        cid = issue.get('chapter_id')
        ch = next((c for c in chapters if c['chapter_id'] == cid), None)
        if not ch or not ch.get('content'):
            return None
        text = ch['content']
        if itype == 'half_width_punct':
            # 半角 → 全角
            for h, zh in [(',', '，'), (';', '；'), (':', '：'), ('!', '！'),
                          ('?', '？'), ('(', '（'), (')', '）')]:
                text = text.replace(h, zh)
            return text if text != ch['content'] else None
        elif itype == 'excessive_punct':
            import re as _re
            text = _re.sub(r'[！!]{3,}', '！！', text)
            text = _re.sub(r'[？?]{3,}', '？？', text)
            return text if text != ch['content'] else None
        elif itype == 'dialogue_mark':
            # 只给草案: 打印当前引号统计, 不自动改
            return f"(引号修复需人工确认, 当前: 双引号{text.count(chr(34))} 个, 中文引{text.count(chr(201))+text.count(chr(202))} 个)"
        return None

    # ── auto_fix 闭环: 接受/拒绝草案 ──

    def apply_fix(self, log_id: int, accept: bool = True, manual_content: Optional[str] = None) -> Optional[Dict]:
        """接受或拒绝某条 auto_fix 草案.
        accept=True 时: 快照旧版 → 更新 chapter.content → 重新 upsert_chunks → log 标记 applied.
        accept=False 时: log 标记 rejected, 不动正文.
        manual_content 可覆盖草案 fixed_content (人工修订后接受)."""
        with get_conn() as c:
            row = c.execute(
                "SELECT * FROM mt_copy_consistency_log WHERE log_id=?", (log_id,)).fetchone()
            if not row:
                return None
            row = dict(row)
            if row.get('auto_fix_status') in ('applied', 'rejected'):
                return {'status': 'already_' + row['auto_fix_status'], 'log_id': log_id}
            if not accept:
                c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='rejected', fixed_content=NULL, updated_at=? WHERE log_id=?",
                          (NOW_F(), log_id))
                return {'status': 'rejected', 'log_id': log_id, 'issue_type': row['issue_type']}

            # accept=True
            cid = row['chapter_id']
            new_content = manual_content or row.get('fixed_content')
            if not new_content or not cid:
                c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='rejected', updated_at=? WHERE log_id=?",
                          (NOW_F(), log_id))
                return {'status': 'skipped_no_content', 'log_id': log_id}

            ch = c.execute("SELECT * FROM mt_copy_chapters WHERE chapter_id=?", (cid,)).fetchone()
            if not ch:
                return None
            # 快照旧版
            vno = self.take_snapshot(cid, trigger_type='apply_fix',
                                     note=f"auto_fix[{row['issue_type']}]: {row.get('description','')[:60]}")
            actual_words = len(new_content)
            c.execute("UPDATE mt_copy_chapters SET content=?, actual_words=?, updated_at=? WHERE chapter_id=?",
                      (new_content, actual_words, NOW_F(), cid))
            c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='applied', fixed_content=?, updated_at=? WHERE log_id=?",
                      (new_content, NOW_F(), log_id))
            # 同 chapter 同类 pending log 中, 只有 fixed_content 完全相同的才 auto-mark applied
            # (避免多段半角标点各有不同草案时被一次性全部吞掉)
            c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='applied', updated_at=? WHERE chapter_id=? AND issue_type=? AND auto_fix_status='pending' AND fixed_content=? AND log_id != ?",
                      (NOW_F(), cid, row['issue_type'], new_content, log_id))

        # 写后 chunk 重索引 (任何异常不阻断)
        try:
            upsert_chunks(row['project_id'], cid, new_content)
        except Exception:
            pass
        return {
            'status': 'applied', 'log_id': log_id, 'chapter_id': cid,
            'issue_type': row['issue_type'], 'old_version_no': vno,
            'actual_words': actual_words,
        }

    def apply_fix_batch(self, log_ids: List[int], accept: bool = True) -> List[Dict]:
        """批量接受/拒绝. 返回每条结果."""
        return [self.apply_fix(lid, accept=accept) for lid in log_ids]

    # ── 审批对接 ──

    def submit_for_approval(self, project_id: str, reason: str = '') -> Optional[str]:
        """提交 approval 中台. 提交前自动跑一致性巡检, 结果写入 reason. 返回 approval_id."""
        p = self.get_project(project_id)
        if not p:
            return None
        # ── 提交前自动跑一致性巡检 ──
        smt_issues = []
        try:
            smt_issues = self.run_consistency_check(project_id)
        except Exception:
            smt_issues = []
        if smt_issues:
            sev_count: Dict[str, int] = {}
            for iss in smt_issues:
                sev_count[iss.get('severity', 'info')] = sev_count.get(iss.get('severity', 'info'), 0) + 1
            summary = (f"\n\n【提交前一致性巡检】共 {len(smt_issues)} 个 issue: "
                       + ', '.join(f"{sev}={cnt}" for sev, cnt in sorted(sev_count.items())))
            top_types = {}
            for iss in smt_issues:
                top_types[iss.get('issue_type', '?')] = top_types.get(iss.get('issue_type', '?'), 0) + 1
            summary += "; 主要类型: " + ', '.join(f"{t}={n}" for t, n in sorted(top_types.items(), key=lambda x: -x[1])[:5])
            reason = (reason or '') + summary
        else:
            reason = (reason or '') + '\n\n【提交前一致性巡检】✅ 未发现问题'
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
