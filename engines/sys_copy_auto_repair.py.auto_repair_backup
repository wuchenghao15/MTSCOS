#!/usr/bin/env python3
"""
🩹 sys_copy_auto_repair — copy_studio 自修复 daemon (P3b)
========================================================
读 mt_copy_consistency_log WHERE auto_fix_status='pending'
→ 按 issue_type 分发到对应修复策略
  dialogue_mark      → 引号成对 (正则补齐)
  overlong_paragraph → 按句号/换行拆段
  character_ooc      → Ollama 提示角色名一致性 (fail-safe: 跳过)
→ 回写 mt_copy_consistency_log.fixed_content + auto_fix_status='fixed'

对齐 sys_copy_consistency.py 模式:
  短连接 + WAL + PID 心跳 + --once + SIGTERM
"""
from __future__ import annotations
import sqlite3, time, os, sys, signal, datetime, json, re, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'database' / 'app.db'
LOG_DIR = ROOT.parent / '_runtime' / 'logs'
PID_DIR = ROOT.parent / '_runtime' / 'pids'
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'sys_copy_auto_repair.log'
PID_FILE = PID_DIR / 'sys_copy_auto_repair.pid'

INTERVAL = 600
_stop = threading.Event()
NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Ollama 探测 (延迟 import)
def _ollama_ok() -> bool:
    try:
        import urllib.request as u
        u.urlopen(u.Request('http://127.0.0.1:11434/api/tags'), timeout=2)
        return True
    except Exception: return False


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


# ── 修复策略 (issue_type → 修复函数) ──

def _fix_dialogue_mark(chapter_content: str) -> Optional[str]:
    """引号成对: 奇数 → 追加一个匹配引号到末尾."""
    text = chapter_content or ''
    # 中文双引号
    cn_l = text.count('"'); cn_r = text.count('"')
    if cn_l != cn_r:
        diff = cn_l - cn_r
        if diff > 0: text += '"' * diff
        else: text = '"' * (-diff) + text
    # 英文双引号
    en = text.count('"')
    if en % 2 != 0: text += '"'
    return text


def _fix_overlong_paragraph(chapter_content: str) -> Optional[str]:
    """超长段落 → 按句号拆."""
    text = chapter_content or ''
    out = []
    for para in text.split('\n'):
        if len(para) > 2000:
            # 按中文句号拆
            sentences = re.split(r'(?<=[。！？!?])', para)
            out.append('\n'.join(s.strip() for s in sentences if s.strip()))
        else:
            out.append(para)
    return '\n'.join(out)


def _fix_character_ooc(chapter_content: str, char_name: str) -> Optional[str]:
    """角色 OOC → 简单策略: 跳过 (让 Ollama 后续润色处理).
    纯字符串修复做不到语义一致性, fail-safe 标注 skipped."""
    return None  # 交给 self_polished / Ollama 润色


FIX_STRATEGIES = {
    'dialogue_mark': _fix_dialogue_mark,
    'overlong_paragraph': _fix_overlong_paragraph,
    'character_ooc': _fix_character_ooc,
}


def run_once():
    """读 pending 行 → 分发修复 → 回写."""
    _log("🩹 auto_repair round start")
    repaired = 0
    skipped = 0

    try:
        with _get_conn() as c:
            pending = [dict(r) for r in c.execute(
                "SELECT * FROM mt_copy_consistency_log WHERE auto_fix_status='pending' LIMIT 100"
            ).fetchall()]
    except Exception as e:
        _log(f"  load pending failed: {e}"); return

    _log(f"  pending issues: {len(pending)}")

    for issue in pending:
        iid = issue['log_id']
        pid = issue['project_id']
        cid = issue['chapter_id']
        itype = issue['issue_type']
        desc = issue['description']

        # 读章节正文
        with _get_conn() as c:
            ch_row = c.execute("SELECT content FROM mt_copy_chapters WHERE chapter_id=?", (cid,)).fetchone()
        if not ch_row or not ch_row['content']:
            _log(f"  #{iid} chapter missing, skip"); skipped += 1; continue

        content = ch_row['content']
        fix_fn = FIX_STRATEGIES.get(itype)
        if not fix_fn:
            _log(f"  #{iid} no strategy for {itype}, skip"); skipped += 1
            with _get_conn() as c:
                c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='skipped' WHERE log_id=?", (iid,))
                c.commit()
            continue

        try:
            # character_ooc 特殊: 传角色名
            if itype == 'character_ooc':
                char_name = (desc.split('"')[1] if '"' in desc else '')
                new_content = fix_fn(content, char_name)
            else:
                new_content = fix_fn(content)

            if new_content is None or new_content == content:
                # 无变化 → 标记 skipped
                with _get_conn() as c:
                    c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='skipped' WHERE log_id=?", (iid,))
                    c.commit()
                _log(f"  #{iid} {itype} no change → skipped"); skipped += 1
                continue

            # 回写章节 + issue 状态
            with _get_conn() as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE mt_copy_chapters SET content=?, updated_at=? WHERE chapter_id=?",
                          (new_content, NOW_F(), cid))
                c.execute("UPDATE mt_copy_consistency_log SET fixed_content=?, auto_fix_status='fixed' WHERE log_id=?",
                          (desc, iid))
                c.execute("COMMIT")
            repaired += 1
            _log(f"  #{iid} {itype} ✅ repaired")

        except Exception as e:
            _log(f"  #{iid} repair failed: {e}")
            with _get_conn() as c:
                c.execute("UPDATE mt_copy_consistency_log SET auto_fix_status='failed' WHERE log_id=?", (iid,))
                c.commit()

    _log(f"✅ round done: repaired={repaired}, skipped={skipped}")
    _heartbeat_write()


def main():
    with open(PID_FILE, 'w') as f: f.write(str(os.getpid()))
    _log(f"🩹 sys_copy_auto_repair started (interval={INTERVAL}s)")
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
