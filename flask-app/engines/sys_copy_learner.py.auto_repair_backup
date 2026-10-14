#!/usr/bin/env python3
"""
📚 sys_copy_learner — copy_studio 自学习 daemon (P3c)
====================================================
每隔 900s (15min) 分析 copy_studio 审批反馈:
  1. 读 mt_copy_consistency_log 累计问题 → 识别高频 issue_type
  2. 分析哪些 project 最常触发哪类问题 → 写 mt_copy_learning_log
  3. 输出结构化学习结果: 建议修改哪个 prompt 模板

fail-safe: 不直接改 generator.py 源码 (那要走 §14),
  而是把学习结果写 mt_copy_learning_log, 供 Parliament 提案或人工审查使用.

对齐 sys_copy_consistency 模式: 短连接 + PID + --once + SIGTERM
"""
from __future__ import annotations
import sqlite3, time, os, sys, signal, datetime, json, threading
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'database' / 'app.db'
LOG_DIR = ROOT.parent / '_runtime' / 'logs'
PID_DIR = ROOT.parent / '_runtime' / 'pids'
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'sys_copy_learner.log'
PID_FILE = PID_DIR / 'sys_copy_learner.pid'

INTERVAL = 900
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


# ── 学习分析 ──

def _analyze_consistency_patterns() -> dict:
    """分析一致性巡检问题分布."""
    try:
        with _get_conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT issue_type, severity, auto_fix_status FROM mt_copy_consistency_log").fetchall()]
    except Exception:
        return {}
    if not rows: return {}

    type_counter = Counter(r['issue_type'] for r in rows)
    sev_counter = Counter(r['severity'] for r in rows)
    status_counter = Counter(r['auto_fix_status'] for r in rows)

    return {
        'total_issues': len(rows),
        'issue_type_distribution': dict(type_counter),
        'severity_distribution': dict(sev_counter),
        'fix_rate': status_counter.get('fixed', 0),
        'skip_rate': status_counter.get('skipped', 0),
        'top_issue': type_counter.most_common(1)[0][0] if type_counter else None,
    }


def _analyze_approval_feedback() -> dict:
    """分析 copy_studio 审批结果分布."""
    try:
        with _get_conn() as c:
            rows = [dict(r) for r in c.execute(
                """SELECT r.status, r.risk_level, r.initiator_role,
                          p.genre, p.sub_genre, p.current_words, p.target_words
                   FROM mt_approval_requests r
                   LEFT JOIN mt_copy_projects p ON p.project_id = r.subject_id
                   WHERE r.category='copy_studio'""").fetchall()]
    except Exception:
        return {}
    if not rows: return {}

    status_counter = Counter(r['status'] for r in rows)
    genre_counter = Counter(r['genre'] for r in rows if r.get('genre'))

    return {
        'total_approvals': len(rows),
        'status_distribution': dict(status_counter),
        'genre_distribution': dict(genre_counter),
        'approval_rate': round(status_counter.get('approved', 0) / max(1, len(rows)), 2),
    }


def _suggestions(patterns: dict, feedback: dict) -> list:
    """基于分析结果生成 prompt 模板修改建议 (不直接改源码)."""
    suggestions = []
    top_issue = patterns.get('top_issue')
    if top_issue:
        suggestions.append({
            'area': 'generator.py',
            'template': 'write_chapter_text',
            'suggestion': f"高频 issue_type={top_issue}: 考虑在 write_chapter prompt 增加明确的「中文引号成对使用」「长段落主动按句号拆分」指令",
            'confidence': 0.75,
        })
    approval_rate = feedback.get('approval_rate', 0)
    if approval_rate and approval_rate < 0.8 and feedback.get('total_approvals', 0) >= 3:
        suggestions.append({
            'area': 'approval policy.py',
            'template': 'assess_risk',
            'suggestion': f"审批通过率 {approval_rate*100:.0f}% 偏低: 考虑降低 copy_studio 特定 genre 的 default risk_level",
            'confidence': 0.6,
        })
    return suggestions


def run_once():
    _log("📚 copy_learner round start")
    patterns = _analyze_consistency_patterns()
    feedback = _analyze_approval_feedback()
    suggestions = _suggestions(patterns, feedback)

    if not patterns and not feedback:
        _log("  无学习数据 (consistency_log=0, approvals=0)"); _heartbeat_write(); return

    _log(f"  consistency: total={patterns.get('total_issues',0)}, top={patterns.get('top_issue','N/A')}")
    _log(f"  approvals: total={feedback.get('total_approvals',0)}, rate={feedback.get('approval_rate',0)}")
    _log(f"  suggestions: {len(suggestions)}")

    # 写学习日志
    try:
        with _get_conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS mt_copy_learning_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patterns_json TEXT, feedback_json TEXT, suggestions_json TEXT,
                created_at TEXT)""")
            c.execute(
                """INSERT INTO mt_copy_learning_log
                (patterns_json, feedback_json, suggestions_json, created_at)
                VALUES (?,?,?,?)""",
                (json.dumps(patterns, ensure_ascii=False),
                 json.dumps(feedback, ensure_ascii=False),
                 json.dumps(suggestions, ensure_ascii=False),
                 NOW_F()))
            c.commit()
        _log(f"✅ learning_log written")
    except Exception as e:
        _log(f"  write log failed: {e}")

    _heartbeat_write()


def main():
    with open(PID_FILE, 'w') as f: f.write(str(os.getpid()))
    _log(f"📚 sys_copy_learner started (interval={INTERVAL}s)")
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
