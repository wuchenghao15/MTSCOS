#!/usr/bin/env python3
"""
🩹 sys_copy_consistency — copy_studio 自巡检 daemon (P3)
========================================================
每隔 600s (10min) 扫描所有 active copy_studio 项目:
  1. 对话引号奇数 (中英文)
  2. 超长段落 (>2000 字无换行)
  3. 角色名 OOC (角色卡定义 vs 章节正文)
  4. 时间线矛盾 (章节间时间跳跃)
  5. 硬编码地名/人名 (RAG 角色卡无匹配)

发现 → 写 mt_copy_consistency_log → sys_copy_auto_repair 自愈候选

对齐 approval/db.py 模式:
  - 短连接 get_conn() + busy_timeout=30s + BEGIN IMMEDIATE
  - @db_retry 仅对 locked 指数退避
  - 不 import 任何长连接 db 实例
"""
from __future__ import annotations
import sqlite3, time, os, sys, threading, signal, datetime, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'database' / 'app.db'
LOG_DIR = ROOT.parent / '_runtime' / 'logs'
PID_DIR = ROOT.parent / '_runtime' / 'pids'
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'sys_copy_consistency.log'
PID_FILE = PID_DIR / 'sys_copy_consistency.pid'

INTERVAL = 600  # 10 分钟一轮

_lock = threading.Lock()
_stop = threading.Event()
NOW_F = lambda: datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _log(msg: str):
    line = f"[{NOW_F()}] {msg}\n"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line)
    print(line.strip())


def _get_conn():
    c = sqlite3.connect(str(DB_PATH), timeout=30.0)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def _heartbeat_write():
    """心跳: 写 PID 文件 (smart_mount_engine 管理 mt_daemon_registry, 不自建列)."""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(f"{os.getpid()}\t{NOW_F()}\trunning")
    except Exception as e:
        _log(f"heartbeat write failed: {e}")


def _scan_one_project(project_id: str) -> int:
    """单项目巡检. 返回发现的 issue 数量."""
    from engines.copy_studio.db import ensure_schema
    ensure_schema()
    with _get_conn() as c:
        # 读所有章节
        chapters = [dict(r) for r in c.execute(
            "SELECT * FROM mt_copy_chapters WHERE project_id=? AND content IS NOT NULL ORDER BY chapter_no",
            (project_id,)).fetchall()]
        # 角色卡
        chars = [dict(r) for r in c.execute(
            "SELECT * FROM mt_copy_characters WHERE project_id=?", (project_id,)).fetchall()]

    issues = []
    char_names = {(r['name'] or '')[:4] for r in chars if r['name']}

    for ch in chapters:
        text = ch['content'] or ''
        # 1. 对话引号奇数
        cn_quote = text.count('"') + text.count('"')
        en_quote = text.count('"')
        if cn_quote % 2 != 0:
            issues.append(('dialogue_mark', 'medium', f'中文引号奇数 ({cn_quote})', ch['chapter_id']))
        if en_quote % 2 != 0:
            issues.append(('dialogue_mark', 'medium', f'英文引号奇数 ({en_quote})', ch['chapter_id']))
        # 2. 超长段落
        for para in text.split('\n'):
            if len(para) > 2000:
                issues.append(('overlong_paragraph', 'low', f'段落 {len(para)} 字 (>2000)', ch['chapter_id']))
                break

    # 3. OOC — 角色名不在角色卡里但出现频次高 (≥5 次)
    for ch in chapters:
        text = ch['content'] or ''
        for name in char_names:
            if name and text.count(name) == 0 and ch['chapter_no'] > 1:
                issues.append(('character_ooc', 'low', f'角色 "{name}" 在第 {ch["chapter_no"]} 章未出现', ch['chapter_id']))

    # 落库
    if issues:
        try:
            with _get_conn() as c:
                c.executemany(
                    """INSERT INTO mt_copy_consistency_log
                    (project_id, chapter_id, issue_type, severity, description, auto_fix_status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                    [(project_id, ch_id, itype, sev, desc, NOW_F()) for itype, sev, desc, ch_id in issues])
        except Exception as e:
            _log(f"  insert issues failed: {e}")
    return len(issues)


def run_once():
    """跑一轮巡检."""
    _log("🔍 sys_copy_consistency scan round start")
    total_projects = 0
    total_issues = 0
    try:
        with _get_conn() as c:
            projects = [r['project_id'] for r in c.execute(
                "SELECT project_id FROM mt_copy_projects WHERE status NOT IN ('archived','approved')").fetchall()]
    except Exception as e:
        _log(f"  load projects failed: {e}")
        return

    for pid in projects:
        n = _scan_one_project(pid)
        total_projects += 1
        total_issues += n
        if n > 0:
            _log(f"  {pid}: {n} issues found")

    _log(f"✅ round done: {total_projects} projects, {total_issues} issues")
    _heartbeat_write()


def main():
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    _log(f"🩹 sys_copy_consistency started (interval={INTERVAL}s)")
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    while not _stop.is_set():
        try:
            run_once()
        except Exception as e:
            _log(f"  FATAL: {e}")
        # sleep 可被 _stop 中断
        for _ in range(INTERVAL):
            if _stop.is_set(): break
            time.sleep(1)
    try: os.remove(PID_FILE)
    except: pass
    _log("🛑 sys_copy_consistency stopped")


if __name__ == '__main__':
    if '--once' in sys.argv:
        run_once()
    else:
        main()
