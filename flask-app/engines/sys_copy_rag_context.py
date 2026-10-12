#!/usr/bin/env python3
"""
🤝 sys_rag_context — copy_studio 自辅助 daemon (P3e)
====================================================
MVP 简化版 (P3): 不接 Ollama embedding, 不用向量数据库.
  用关键词提取 + 最近 3 章摘要拼接 → 注入 mt_copy_rag_inject_log.

后续 P4 可升级: Ollama embedding + 本地 FAISS/SQLite FTS5 向量索引.

每隔 120s 扫描所有 writing 状态项目:
  1. 读角色卡 → 提取关键词 (人名/地名/专有名词)
  2. 读最近 3 章正文 → 生成摘要 (首 500 字 + 关键词列表)
  3. 写入 mt_copy_rag_inject_log → 后续章节 AI 写作时 RAG 注入

对齐 sys_copy_consistency 模式
"""
from __future__ import annotations
import sqlite3, time, os, sys, signal, datetime, json, re, threading
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'database' / 'app.db'
LOG_DIR = ROOT.parent / '_runtime' / 'logs'
PID_DIR = ROOT.parent / '_runtime' / 'pids'
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'sys_copy_rag_context.log'
PID_FILE = PID_DIR / 'sys_copy_rag_context.pid'

INTERVAL = 120
# 单项目最多保留的 rag_inject 记录
MAX_INJECTS_PER_PROJECT = 200

_stop = threading.Event()
NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _log(msg: str):
    line = f"[{NOW_F()}] {msg}\n"
    with open(LOG_FILE, 'a', encoding='utf-8') as f: f.write(line)
    print(line.strip())


def _get_conn():
    c = sqlite3.connect(str(DB_PATH), timeout=30.0)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def _heartbeat_write():
    try:
        with open(PID_FILE, 'w') as f:
            f.write(f"{os.getpid()}\t{NOW_F()}\trunning")
    except Exception: pass


# ── 关键词提取 (无 embedding 的 MVP) ──

# 停用词 (简化版)
_STOPWORDS = set("""
的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这
他 她 它 我们 你们 他们 什么 怎么 为什么 因为 所以 但是 而且 或者 如果 虽然 然后 可是
the a an is are was were be been being have has had do does did will would shall should may might can could
""".split())

def _extract_keywords(text: str, top_n: int = 15) -> list:
    """中文分词简化版: 正则拆词 + 停用词过滤 + 频度排序."""
    if not text: return []
    # 切分: 中文连续 2-4 字作为候选 + 英文单词
    candidates = []
    # 英文单词
    for w in re.findall(r'[a-zA-Z]{2,}', text):
        if w.lower() not in _STOPWORDS:
            candidates.append(w.lower())
    # 中文: 滑动窗口 2/3/4 字
    for n in (2, 3, 4):
        for m in re.finditer(r'[\u4e00-\u9fff]{2,}', text):
            s = m.group()
            for i in range(len(s) - n + 1):
                candidates.append(s[i:i+n])
    counter = Counter(c for c in candidates if c not in _STOPWORDS and len(c) >= 2)
    return [w for w, _ in counter.most_common(top_n)]


def _chapter_summary(text: str, keywords: list) -> dict:
    """章节摘要: 首 500 字 + 关键词."""
    if not text: return {'head': '', 'keywords': keywords[:10]}
    # 按句号断
    sentences = re.split(r'(?<=[。！？!?])', text)
    head = ''.join(sentences[:5])[:500]
    return {'head': head, 'keywords': keywords[:10]}


def _char_card_entities(chars: list) -> dict:
    """角色卡实体: 名字 + 性格关键词."""
    entities = []
    for c in chars:
        if c.get('name'):
            entities.append({
                'name': c['name'],
                'role_type': c.get('role_type', 'supporting'),
                'personality_keywords': _extract_keywords(c.get('personality', '') + ' ' + c.get('backstory', ''), top_n=5),
            })
    return entities


# ── 主循环 ──

def _scan_project(project_id: str) -> int:
    """单项目扫描: 角色卡关键词 + 最近 3 章摘要 → 写 rag_inject_log."""
    with _get_conn() as c:
        project = c.execute("SELECT * FROM mt_copy_projects WHERE project_id=?", (project_id,)).fetchone()
        if not project: return 0
        # 角色卡
        chars = [dict(r) for r in c.execute(
            "SELECT * FROM mt_copy_characters WHERE project_id=?", (project_id,)).fetchall()]
        # 最近 3 章 (有内容)
        chapters = [dict(r) for r in c.execute(
            """SELECT * FROM mt_copy_chapters WHERE project_id=? AND content IS NOT NULL
               ORDER BY chapter_no DESC LIMIT 3""", (project_id,)).fetchall()]

    if not chapters and not chars: return 0

    # 角色实体
    entities = _char_card_entities(chars)

    # 章节摘要
    chapter_summaries = []
    for ch in reversed(chapters):  # 恢复正序
        kw = _extract_keywords(ch['content'] or '', top_n=12)
        chapter_summaries.append({
            'chapter_no': ch['chapter_no'],
            'title': ch['title'],
            **_chapter_summary(ch['content'] or '', kw),
        })

    inject_data = {
        'project_id': project_id,
        'genre': project['genre'],
        'entities': entities,
        'chapter_summaries': chapter_summaries,
        'generated_at': NOW_F(),
        'inject_version': 'v1_mvp_no_embedding',
    }

    # 估算 token (中文 ≈ 1.5 字/token, 英文 ≈ 4 字符/token)
    est_tokens = len(json.dumps(inject_data, ensure_ascii=False)) // 2

    try:
        with _get_conn() as c:
            # 清理老记录 (保留 MAX_INJECTS_PER_PROJECT)
            c.execute("""DELETE FROM mt_copy_rag_inject_log
                WHERE project_id=? AND inject_id IN (
                  SELECT inject_id FROM mt_copy_rag_inject_log
                  WHERE project_id=? ORDER BY created_at DESC LIMIT -1 OFFSET ?)""",
                (project_id, project_id, MAX_INJECTS_PER_PROJECT))
            c.execute(
                """INSERT INTO mt_copy_rag_inject_log
                (project_id, inject_type, inject_content, tokens_estimate, created_at)
                VALUES (?,?,?,?,?)""",
                (project_id, 'context_window',
                 json.dumps(inject_data, ensure_ascii=False),
                 est_tokens, NOW_F()))
            c.commit()
        return 1
    except Exception as e:
        _log(f"  write rag_inject_log failed: {e}"); return 0


def run_once():
    _log("🤝 rag_context round start")
    try:
        with _get_conn() as c:
            projects = [r['project_id'] for r in c.execute(
                "SELECT project_id FROM mt_copy_projects WHERE status IN ('writing','outlining','reviewing')").fetchall()]
    except Exception as e:
        _log(f"  load projects failed: {e}"); return

    total = len(projects)
    ok = 0
    for pid in projects:
        r = _scan_project(pid)
        ok += r

    _log(f"✅ round done: {ok}/{total} projects injected")
    _heartbeat_write()


def main():
    with open(PID_FILE, 'w') as f: f.write(str(os.getpid()))
    _log(f"🤝 sys_rag_context started (interval={INTERVAL}s, MVP no embedding)")
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    while not _stop.is_set():
        try: run_once()
        except Exception as e: _log(f"  FATAL: {e}")
        for _ in range(INTERVAL):
            if _stop.is_set(): break
            time.sleep(1)
    try: os.remove(PID_FILE)
    except: pass
    _log("🛑 stopped")


if __name__ == '__main__':
    if '--once' in sys.argv: run_once()
    else: main()
