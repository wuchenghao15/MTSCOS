#!/usr/bin/env python3
"""
🚀 sys_copy_expander — copy_studio 自拓展 daemon (P3d)
======================================================
每隔 1200s (20min) 扫描 copy_studio 能力边界:
  1. 已完成项目数量阈值 (≥20) → 触发前端模板自动编译提案
  2. 体裁覆盖缺口 (某 genre 项目数=0) → 触发扩展该体裁能力提案
  3. 同类审批>10 次 → 触发 Parliament 提案, 自动写 mt_parliament_proposals stub

fail-safe: 不自动写 git / 不直接改源码 (那要走 §14),
  只写 mt_copy_expansion_log + mt_parliament_proposals, 等人工或 Parliament 审批.

对齐 sys_copy_consistency 模式
"""
from __future__ import annotations
import sqlite3, time, os, sys, signal, datetime, json, threading, uuid
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'database' / 'app.db'
LOG_DIR = ROOT.parent / '_runtime' / 'logs'
PID_DIR = ROOT.parent / '_runtime' / 'pids'
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'sys_copy_expander.log'
PID_FILE = PID_DIR / 'sys_copy_expander.pid'

INTERVAL = 1200
PROJECTS_THRESHOLD = 20   # ≥20 个已完成项目触发前端模板编译提案
APPROVALS_THRESHOLD = 10  # ≥10 次同类审批触发 Parliament 提案
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


def _check_project_volume() -> dict:
    """已完成项目数量 + 体裁分布."""
    try:
        with _get_conn() as c:
            total = c.execute("SELECT COUNT(*) FROM mt_copy_projects WHERE status IN ('approved','published')").fetchone()[0]
            by_genre = dict(Counter(
                r['genre'] for r in c.execute(
                    "SELECT genre FROM mt_copy_projects WHERE status IN ('approved','published')"
                ).fetchall()))
    except Exception as e:
        return {'error': str(e)}
    return {'total_completed': total, 'by_genre': by_genre, 'threshold': PROJECTS_THRESHOLD}


def _check_approval_volume() -> dict:
    """同类审批数量 → 高频 genre."""
    try:
        with _get_conn() as c:
            rows = [dict(r) for r in c.execute(
                """SELECT p.genre, COUNT(*) as cnt
                   FROM mt_approval_requests r
                   LEFT JOIN mt_copy_projects p ON p.project_id = r.subject_id
                   WHERE r.category='copy_studio' AND p.genre IS NOT NULL
                   GROUP BY p.genre HAVING cnt >= ?""",
                (APPROVALS_THRESHOLD,)).fetchall()]
    except Exception as e:
        return {'error': str(e)}
    return {'genres_over_threshold': rows, 'threshold': APPROVALS_THRESHOLD}


def _write_expansion_log(trigger: str, details: dict) -> str:
    """写 mt_copy_expansion_log (幂等 CREATE TABLE IF NOT EXISTS)."""
    log_id = f"exp_{uuid.uuid4().hex[:10]}"
    try:
        with _get_conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_copy_expansion_log (
                log_id TEXT PRIMARY KEY, trigger_type TEXT, details_json TEXT,
                parliament_proposal_id TEXT, created_at TEXT)""")
            c.execute(
                """INSERT INTO mt_copy_expansion_log (log_id, trigger_type, details_json, created_at)
                   VALUES (?,?,?,?)""",
                (log_id, trigger, json.dumps(details, ensure_ascii=False), NOW_F()))
            c.commit()
    except Exception as e:
        _log(f"  write expansion_log failed: {e}")
    return log_id


def _write_parliament_proposal(title: str, content: str) -> Optional[str]:
    """写 mt_parliament_proposals stub (不自动提交, 等 Parliament)."""
    pid = f"prop_{uuid.uuid4().hex[:12]}"
    try:
        with _get_conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_parliament_proposals (
                proposal_id TEXT PRIMARY KEY, title TEXT, content TEXT,
                author TEXT DEFAULT 'sys_copy_expander',
                status TEXT DEFAULT 'pending_vote',
                votes_for INTEGER DEFAULT 0, votes_against INTEGER DEFAULT 0,
                created_at TEXT)""")
            c.execute(
                """INSERT INTO mt_parliament_proposals
                   (proposal_id, title, content, author, status, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (pid, title, content, 'sys_copy_expander', 'pending_vote', NOW_F()))
            c.commit()
        _log(f"  🗳️ Parliament proposal: {pid}")
        return pid
    except Exception as e:
        _log(f"  write parliament failed: {e}")
        return None


def run_once():
    _log("🚀 copy_expander round start")
    proj = _check_project_volume()
    appr = _check_approval_volume()

    if 'error' in proj or 'error' in appr:
        _log(f"  data load failed: {proj.get('error') or appr.get('error')}")
        _heartbeat_write(); return

    triggered = 0

    # 触发条件 1: 项目数 ≥ 阈值 → 前端自动编译提案
    if proj['total_completed'] >= PROJECTS_THRESHOLD:
        _log(f"  trigger: {proj['total_completed']} completed ≥ {PROJECTS_THRESHOLD}")
        genres_complete = [g for g, n in proj['by_genre'].items() if n >= 3]
        genres_empty = [g for g in ('novel','script','ad_copy') if g not in proj['by_genre']]
        details = {
            'total_completed': proj['total_completed'],
            'genres_complete': genres_complete,
            'genres_empty': genres_empty,
        }
        lid = _write_expansion_log('volume_threshold', details)
        prop = _write_parliament_proposal(
            title=f'copy_studio 前端自动编译: {", ".join(genres_complete)} 专属模板',
            content=f"已完成 {proj['total_completed']} 个 copy_studio 项目, 其中 {genres_complete} 各 ≥3 单.\n"
                    f"建议: 为 {' '.join(genres_complete)} 各创建专属前端工作台模板.\n"
                    f"触发日志: {lid}")
        # 回写 parliament_proposal_id
        if prop:
            with _get_conn() as c:
                c.execute("UPDATE mt_copy_expansion_log SET parliament_proposal_id=? WHERE log_id=?",
                          (prop, lid)); c.commit()
        triggered += 1

    # 触发条件 2: 某 genre 审批 ≥ 阈值 → Parliament 提案
    if appr['genres_over_threshold']:
        for row in appr['genres_over_threshold']:
            _log(f"  trigger: genre={row['genre']} approvals={row['cnt']} ≥ {APPROVALS_THRESHOLD}")
            details = {'genre': row['genre'], 'approval_count': row['cnt']}
            lid = _write_expansion_log('approval_threshold', details)
            prop = _write_parliament_proposal(
                title=f'copy_studio {row["genre"]} 专属能力增强 (审批 {row["cnt"]} 次)',
                content=f"{row['genre']} 审批量达 {row['cnt']}, 建议该体裁专属 AI 员工 + 专属前端模板.\n"
                        f"触发日志: {lid}")
            if prop:
                with _get_conn() as c:
                    c.execute("UPDATE mt_copy_expansion_log SET parliament_proposal_id=? WHERE log_id=?",
                              (prop, lid)); c.commit()
            triggered += 1

    if not triggered:
        _log(f"  未触发 (completed={proj['total_completed']}, approvals_per_genre<{APPROVALS_THRESHOLD})")

    _log(f"✅ round done: triggered={triggered}")
    _heartbeat_write()


def main():
    with open(PID_FILE, 'w') as f: f.write(str(os.getpid()))
    _log(f"🚀 sys_copy_expander started (interval={INTERVAL}s)")
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
