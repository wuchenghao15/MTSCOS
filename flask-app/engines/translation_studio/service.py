#!/usr/bin/env python3
"""
🌐 translation_studio — service (v26.0)
=======================================
门面层. 串联 db + pipeline + copy_studio 对接.

核心场景:
  A. 独立翻译: user 直接上传文本, 选方向 → 翻译任务
  B. 文案配套: copy_studio 项目完成 → translate_and_publish → 四国翻译版本
"""
from __future__ import annotations
import json, uuid, time, datetime, hashlib, sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List

from . import (ensure_schema, get_conn, db_retry, NOW_F, DB_PATH,
               FOUR_LANGS, LANG_LABELS, valid_direction,
               QUALITY_STANDARD, QUALITY_PREMIUM, DEFAULT_GLOSSARY)
from .pipeline import (translate_full, split_into_segments, llm_call, OLLAMA_OK, OLLAMA_MODEL)


def _new_id(prefix: str = 'trans') -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()[:16]


class TranslationService:
    """四国翻译门面."""

    def __init__(self):
        ensure_schema()

    # ── 任务管理 ──

    def create_task(self, source_text: str, source_lang: str, target_lang: str,
                    quality: str = QUALITY_STANDARD,
                    source_project_id: Optional[str] = None,
                    custom_glossary: Optional[Dict[str, str]] = None,
                    initiator: str = 'wuchenghao15') -> Dict[str, Any]:
        """创建翻译任务 (不立即翻译, 用 run_task 执行)."""
        if not valid_direction(source_lang, target_lang):
            return {'error': f'Invalid direction {source_lang}→{target_lang}'}
        tid = _new_id('trans')
        now = NOW_F()
        with get_conn() as c:
            c.execute(
                """INSERT INTO mt_trans_tasks
                (task_id, source_lang, target_lang, source_text, source_project_id,
                 quality, glossary_json, status, initiator, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, source_lang, target_lang, source_text, source_project_id,
                 quality, json.dumps(custom_glossary or {}, ensure_ascii=False),
                 'pending', initiator, now, now))
        return {'task_id': tid, 'status': 'pending',
                'source_lang': source_lang, 'target_lang': target_lang,
                'source_len': len(source_text)}

    def run_task(self, task_id: str) -> Dict[str, Any]:
        """执行翻译任务 (带缓存检查)."""
        with get_conn() as c:
            task = c.execute("SELECT * FROM mt_trans_tasks WHERE task_id=?", (task_id,)).fetchone()
            if not task: return {'error': 'task not found'}
            t = dict(task)

        src, tgt = t['source_lang'], t['target_lang']
        text = t['source_text'] or ''
        if not text: return {'error': 'empty source'}

        # 检查缓存
        h = _text_hash(text)
        with get_conn() as c:
            cached = c.execute(
                """SELECT target_text, token_count FROM mt_trans_cache
                   WHERE source_hash=? AND source_lang=? AND target_lang=?""",
                (h, src, tgt)).fetchone()
        if cached:
            with get_conn() as c:
                c.execute("UPDATE mt_trans_tasks SET target_text=?, status='done', quality_score=1.0, updated_at=? WHERE task_id=?",
                          (cached['target_text'], NOW_F(), task_id))
            return {'task_id': task_id, 'status': 'done', 'cached': True, 'target_text': cached['target_text']}

        # 标记 running
        with get_conn() as c:
            c.execute("UPDATE mt_trans_tasks SET status='running', updated_at=? WHERE task_id=?", (NOW_F(), task_id))

        # 加载术语
        glossary = json.loads(t.get('glossary_json') or '{}')
        if not glossary:
            glossary = DEFAULT_GLOSSARY.get(f"{src}→{tgt}", {})

        result = translate_full(text, src, tgt,
                                quality=t['quality'] or QUALITY_STANDARD,
                                custom_glossary=glossary)

        # 写 segments
        segs = split_into_segments(text)
        translated_segs = result.get('translated', '').split('\n\n')
        with get_conn() as c:
            for i, seg in enumerate(segs):
                tgt_seg = translated_segs[i] if i < len(translated_segs) else ''
                c.execute(
                    """INSERT INTO mt_trans_segments
                    (seg_id, task_id, seg_no, source_segment, target_segment, created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (_new_id('seg'), task_id, i, seg, tgt_seg, NOW_F()))

            if result.get('error_segments'):
                c.execute("UPDATE mt_trans_tasks SET status='partial', error_msg=?, updated_at=? WHERE task_id=?",
                          (f"failed_segs={result['error_segments']}", NOW_F(), task_id))
            else:
                c.execute("UPDATE mt_trans_tasks SET target_text=?, status='done', updated_at=? WHERE task_id=?",
                          (result['translated'], NOW_F(), task_id))

            # 写缓存 (精品才缓存, 标准避免污染)
            if t['quality'] == QUALITY_PREMIUM and result['translated']:
                c.execute(
                    """INSERT OR REPLACE INTO mt_trans_cache
                    (cache_key, source_hash, source_lang, target_lang, target_text, token_count, created_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (_new_id('cache'), h, src, tgt, result['translated'],
                     len(result['translated']) // 4, NOW_F()))

        result['task_id'] = task_id
        result['status'] = 'partial' if result.get('error_segments') else 'done'
        return result

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with get_conn() as c:
            row = c.execute("SELECT * FROM mt_trans_tasks WHERE task_id=?", (task_id,)).fetchone()
            if not row: return None
            t = dict(row)
            t['source_segments'] = [dict(r) for r in c.execute(
                "SELECT seg_no, source_segment, target_segment FROM mt_trans_segments WHERE task_id=? ORDER BY seg_no",
                (task_id,)).fetchall()]
            return t

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with get_conn() as c:
            sql = "SELECT * FROM mt_trans_tasks"
            params = []
            if status:
                sql += " WHERE status=?"; params.append(status)
            sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    # ── copy_studio 配套: 发布后翻译到四国 ──

    def translate_copy_project(self, project_id: str,
                               target_langs: Optional[List[str]] = None,
                               quality: str = QUALITY_STANDARD) -> Dict[str, Any]:
        """copy_studio 项目完成后, 自动翻到多个目标语言."""
        if target_langs is None:
            target_langs = [l for l in FOUR_LANGS if l != 'zh']
        results = {}
        for tgt in target_langs:
            r = self.translate_copy_project_single(project_id, tgt, quality)
            results[tgt] = r
        return {'project_id': project_id, 'translations': results, 'langs': target_langs}

    def translate_copy_project_single(self, project_id: str, target_lang: str,
                                      quality: str = QUALITY_STANDARD) -> Dict[str, Any]:
        """翻单个 copy_studio 项目到 target_lang."""
        # 从 copy_studio 加载正文
        try:
            with get_conn() as c:
                title_row = c.execute("SELECT title FROM mt_copy_projects WHERE project_id=?",
                                      (project_id,)).fetchone()
                if not title_row: return {'error': f'copy_studio project {project_id} not found'}
                title = title_row['title']
                chapters = [dict(r) for r in c.execute(
                    """SELECT title, content FROM mt_copy_chapters
                       WHERE project_id=? AND content IS NOT NULL
                       ORDER BY chapter_no""", (project_id,)).fetchall()]
        except Exception as e:
            return {'error': f'load copy_studio failed: {e}'}

        full_text = f"# {title}\n\n" + '\n\n'.join(
            f"## {ch['title']}\n\n{ch['content']}" for ch in chapters)

        # 先翻标题
        src_lang = 'zh'  # copy_studio 默认中文
        title_r = translate_full(title, src_lang, target_lang, quality=QUALITY_PREMIUM)
        translated_title = title_r.get('translated', title)

        # 创建任务
        r = self.create_task(source_text=full_text, source_lang=src_lang,
                             target_lang=target_lang, quality=quality,
                             source_project_id=project_id)
        if 'error' in r: return r

        # 执行翻译
        result = self.run_task(r['task_id'])
        result['translated_title'] = translated_title
        result['project_id'] = project_id
        return result

    # ── 术语表管理 ──

    def add_glossary(self, src_lang: str, tgt_lang: str,
                     source_term: str, target_term: str,
                     domain: str = 'general') -> bool:
        try:
            with get_conn() as c:
                c.execute(
                    """INSERT OR REPLACE INTO mt_trans_glossary
                    (src_lang, tgt_lang, source_term, target_term, domain, created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (src_lang, tgt_lang, source_term, target_term, domain, NOW_F()))
                c.commit()
            return True
        except Exception: return False

    def list_glossary(self, src_lang: Optional[str] = None,
                      tgt_lang: Optional[str] = None) -> List[Dict]:
        with get_conn() as c:
            sql = "SELECT * FROM mt_trans_glossary WHERE 1=1"
            params = []
            if src_lang: sql += " AND src_lang=?"; params.append(src_lang)
            if tgt_lang: sql += " AND tgt_lang=?"; params.append(tgt_lang)
            sql += " ORDER BY src_lang, tgt_lang, domain, source_term"
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    # ── 统计 ──

    def stats(self) -> Dict[str, Any]:
        with get_conn() as c:
            total = c.execute("SELECT COUNT(*) FROM mt_trans_tasks").fetchone()[0]
            done = c.execute("SELECT COUNT(*) FROM mt_trans_tasks WHERE status='done'").fetchone()[0]
            partial = c.execute("SELECT COUNT(*) FROM mt_trans_tasks WHERE status='partial'").fetchone()[0]
            running = c.execute("SELECT COUNT(*) FROM mt_trans_tasks WHERE status='running'").fetchone()[0]
            by_dir = [dict(r) for r in c.execute(
                """SELECT source_lang, target_lang, COUNT(*) as cnt
                   FROM mt_trans_tasks GROUP BY source_lang, target_lang""").fetchall()]
            glossary_count = c.execute("SELECT COUNT(*) FROM mt_trans_glossary").fetchone()[0]
            cache_count = c.execute("SELECT COUNT(*) FROM mt_trans_cache").fetchone()[0]
        return {
            'total_tasks': total, 'done': done, 'partial': partial, 'running': running,
            'by_direction': by_dir,
            'glossary_terms': glossary_count,
            'cache_entries': cache_count,
            'ollama_ok': OLLAMA_OK,
            'ollama_model': OLLAMA_MODEL[:50] if OLLAMA_MODEL else '',
            'four_langs': FOUR_LANGS,
            'lang_labels': {k: {**v, 'code': k} for k, v in LANG_LABELS.items()},
        }
