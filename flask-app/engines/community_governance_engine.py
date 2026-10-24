#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
社区治理引擎 (sys_community_governance)
========================================
flow_unified_ops_20261024 · Phase3 后续 (三委立法管线 + 仙女座星空 + 基础设施健康)

职责:
  1) committee_once  — 三委立法闭环: PENDING 提案表决(干部团) → PASSED 立案 →
                       条款生成 → 颁布法令, 全程 mt_committee_audit_log 留痕
  2) stars_expand_once — 仙女座星空扩容: 从 ai_employees 12069 人选领域明星
                         (心跳新鲜+修复战绩), 幂等补齐至 ~50 星
  3) health_once     — 基础设施健康采集: Flask 存活/DB 可写/CPU/MEM 真实采样
                       → andromeda_health_heartbeat (300s 一条)

用法:
  python3 community_governance_engine.py committee  # 立法管线单轮
  python3 community_governance_engine.py stars      # 星空扩容单轮
  python3 community_governance_engine.py health     # 健康采集单轮
  python3 community_governance_engine.py loop       # 守护循环 (300s)
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

import sqlite3

FA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(FA_DIR)
DAEMON_NAME = 'sys_community_governance'
POLL_SECS = int(os.environ.get('MTSCOS_GOVERN_POLL', '300'))
STAR_TARGET = 50
COMMITTEE_BATCH = 2      # 每轮最多立案+颁布的法案数 (防写风暴)
VOTER_COUNT = 9          # 常委表决团人数


def _connect():
    env = os.environ.get('MTSCOS_DB')
    path = env if (env and os.path.exists(env)) else os.path.join(
        FA_DIR, 'database', 'app.db')
    conn = sqlite3.connect(path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _now() -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


# ============================================================
# 1) 三委立法管线
# ============================================================
def _vote_decision(cadre_focus: str, prop_type: str, prop_category: str,
                   prop_priority: int) -> str:
    """程序性表决: 干部 focus_area 与提案相关性强 → 倾向 FOR;
    确定性伪随机 (proposal 维度 hash) 保证可复现不漂移."""
    hay = f'{prop_type} {prop_category}'.lower()
    related = 1 if (cadre_focus and cadre_focus.lower()[:2] in hay) else 0
    h = int(hashlib.md5(f'{cadre_focus}{prop_type}{prop_priority}'.encode()).hexdigest(), 16)
    if related or h % 100 < 78:
        return 'FOR'
    return 'AGAINST' if h % 100 < 90 else 'ABSTAIN'


def committee_once(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'voted': 0, 'bill_created': 0, 'articled': 0, 'enacted': 0, 'failed': 0}
    try:
        # —— 阶段1: PENDING 提案表决 (干部团 9 人) ——
        pend = conn.execute(
            "SELECT proposal_id, title, type, IFNULL(category,''), priority "
            "FROM mt_committee_proposals WHERE status='PENDING' LIMIT 1").fetchall()
        for pid, title, ptype, pcat, prio in pend:
            try:
                cadres = conn.execute(
                    "SELECT employee_name, IFNULL(position,''), "
                    "IFNULL(focus_area,'') FROM mt_committee_cadres "
                    "WHERE status='ACTIVE' ORDER BY id LIMIT ?",
                    (VOTER_COUNT,)).fetchall()
                if not cadres:
                    stats['failed'] += 1
                    continue
                for_c = re_j = ab_c = 0
                for cname, cpos, cfocus in cadres:
                    v = _vote_decision(cfocus, ptype, pcat, prio)
                    conn.execute(
                        "INSERT INTO mt_committee_votes (bill_id, voter_name, "
                        "voter_role, vote, comment) VALUES (?,?,?,?,?)",
                        (pid, cname, cpos, v,
                         f'程序性表决 立法委/常务委 联席 (focus={cfocus[:16]})'))
                    if v == 'FOR':
                        for_c += 1
                    elif v == 'AGAINST':
                        re_j += 1
                    else:
                        ab_c += 1
                passed = for_c >= (VOTER_COUNT * 2 // 3 + 1)
                conn.execute(
                    "UPDATE mt_committee_proposals SET status=? WHERE proposal_id=?",
                    ('PASSED' if passed else 'REJECTED', pid))
                conn.execute(
                    "INSERT INTO mt_committee_audit_log (action, bill_id, actor, detail) "
                    "VALUES (?,?,?,?)",
                    ('VOTE', pid, 'sys_community_governance', json.dumps(
                        {'title': title, 'for': for_c, 'against': re_j,
                         'abstain': ab_c, 'result': 'PASSED' if passed else 'REJECTED'},
                        ensure_ascii=False)))
                conn.commit()
                stats['voted'] += 1
            except Exception as e:
                stats['failed'] += 1
                sys.stderr.write(f'[GOVERN] vote {pid} err: {e}\n')

        # —— 阶段2: PASSED 且未立案 → 建法案 ——
        rows = conn.execute(
            "SELECT proposal_id, title, type, IFNULL(category,''), proposer "
            "FROM mt_committee_proposals WHERE status='PASSED' AND "
            "IFNULL(bill_id,'')='' LIMIT ?", (COMMITTEE_BATCH,)).fetchall()
        for pid, title, ptype, pcat, proposer in rows:
            try:
                bid = f'BILL_{hashlib.md5(pid.encode()).hexdigest()[:10]}'
                conn.execute(
                    "INSERT OR IGNORE INTO mt_committee_bills (bill_id, title, type, "
                    "category, current_status, proposer, sponsor, description, "
                    "vote_count, approve_count) VALUES (?,?,?,?, 'VOTED', ?, ?, ?, 9, ?)",
                    (bid, title, ptype, pcat, proposer or '三委联席',
                     'sys_community_governance', f'源提案 {pid}: {title}', 7))
                conn.execute(
                    "UPDATE mt_committee_proposals SET bill_id=? WHERE proposal_id=?",
                    (bid, pid))
                conn.execute(
                    "INSERT INTO mt_committee_audit_log (action, bill_id, actor, detail) "
                    "VALUES (?,?,?,?)",
                    ('BILL_CREATE', bid, 'sys_community_governance', f'立案: {title}'))
                conn.commit()
                stats['bill_created'] += 1
            except Exception as e:
                stats['failed'] += 1
                sys.stderr.write(f'[GOVERN] bill {pid} err: {e}\n')

        # —— 阶段3: VOTED 法案 → 条款 ——
        rows = conn.execute(
            "SELECT bill_id, title, type, IFNULL(category,'') FROM mt_committee_bills "
            "WHERE current_status='VOTED' LIMIT ?", (COMMITTEE_BATCH,)).fetchall()
        for bid, title, btype, bcat in rows:
            try:
                exists = conn.execute(
                    "SELECT count(*) FROM mt_committee_articles WHERE bill_id=?",
                    (bid,)).fetchone()[0]
                if not exists:
                    articles = [
                        (1, '', f'为规范{bcat or "相关领域"}业务, 依据三委联席表决结果, 制定本{btype}类办法《{title}》。',
                         '明确立法目的与依据'),
                        (2, '', f'本办法适用于 MTSCOS AI 系统内{bcat or "相关领域"}全部 AI 员工、引擎与子系统; '
                         f'与现行规则冲突的, 以本办法为准。', '界定适用范围'),
                        (3, '', f'本办法自颁布之日起施行, 由三委负责解释; 施行中发现重大缺陷的, '
                         f'按立法程序修订或废除。', '施行与解释'),
                    ]
                    for no, _old, new, reason in articles:
                        conn.execute(
                            "INSERT INTO mt_committee_articles (bill_id, article_no, "
                            "old_text, new_text, reason) VALUES (?,?,?,?,?)",
                            (bid, no, _old, new, reason))
                conn.execute(
                    "UPDATE mt_committee_bills SET current_status='ARTICLED', updated_at=? "
                    "WHERE bill_id=?", (_now(), bid))
                conn.execute(
                    "INSERT INTO mt_committee_audit_log (action, bill_id, actor, detail) "
                    "VALUES (?,?,?,?)",
                    ('ARTICLE', bid, 'sys_community_governance', '条款生成 (3条骨架)'))
                conn.commit()
                stats['articled'] += 1
            except Exception as e:
                stats['failed'] += 1
                sys.stderr.write(f'[GOVERN] article {bid} err: {e}\n')

        # —— 阶段4: ARTICLED 法案 → 颁布 ——
        rows = conn.execute(
            "SELECT bill_id, title, type, IFNULL(category,'') FROM mt_committee_bills "
            "WHERE current_status='ARTICLED' LIMIT ?", (COMMITTEE_BATCH,)).fetchall()
        for bid, title, btype, bcat in rows:
            try:
                seq = conn.execute(
                    "SELECT count(*) FROM mt_committee_decrees").fetchone()[0] + 1
                arts = conn.execute(
                    "SELECT article_no, new_text FROM mt_committee_articles "
                    "WHERE bill_id=? ORDER BY article_no", (bid,)).fetchall()
                full_text = '\n'.join(f'第{no}条 {txt}' for no, txt in arts) or title
                conn.execute(
                    "INSERT OR IGNORE INTO mt_committee_decrees (bill_id, decree_no, "
                    "title, type, category, text, effective_date, status) "
                    "VALUES (?,?,?,?,?,?,?,'ACTIVE')",
                    (bid, f'DCR_{seq:04d}', title, btype, bcat, full_text,
                     _now()[:10]))
                conn.execute(
                    "UPDATE mt_committee_bills SET current_status='ENACTED', "
                    "applied_at=? WHERE bill_id=?", (_now(), bid))
                conn.execute(
                    "INSERT INTO mt_committee_audit_log (action, bill_id, actor, detail) "
                    "VALUES (?,?,?,?)",
                    ('ENACT', bid, 'sys_community_governance',
                     f'颁布 DCR_{seq:04d}: {title}'))
                conn.commit()
                stats['enacted'] += 1
            except Exception as e:
                stats['failed'] += 1
                sys.stderr.write(f'[GOVERN] enact {bid} err: {e}\n')
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 2) 仙女座星空扩容 (幂等)
# ============================================================
STAR_COLORS = ['#F59E0B', '#3B82F6', '#10B981', '#8B5CF6', '#EF4444',
               '#06B6D4', '#F97316', '#EC4899', '#84CC16', '#6366F1']
STAR_EMOJIS = ['⭐', '🌟', '✨', '💫', '🔆']


def stars_expand_once(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    stats = {'before': 0, 'added': 0}
    try:
        stats['before'] = conn.execute(
            "SELECT count(*) FROM mt_andromeda_stars").fetchone()[0]
        if stats['before'] >= STAR_TARGET:
            return stats
        existing = {r[0] for r in conn.execute(
            "SELECT star_name FROM mt_andromeda_stars").fetchall()}
        # 候选: 活跃员工, 心跳最新优先, 修复战绩加权
        cands = conn.execute(
            "SELECT name, IFNULL(specialties,''), IFNULL(group_tag,''), "
            "IFNULL(title,''), IFNULL(grade,'') FROM ai_employees "
            "WHERE LOWER(IFNULL(status,'active'))='active' "
            "AND IFNULL(name,'')!='' "
            "ORDER BY IFNULL(last_heartbeat,'') DESC, IFNULL(successful_fixes,0) DESC "
            "LIMIT 400").fetchall()
        for name, spec, gtag, title, grade in cands:
            if stats['before'] + stats['added'] >= STAR_TARGET:
                break
            if name in existing:
                continue
            domain = (gtag or spec or '综合').split('/')[0].split('、')[0][:12] or '综合'
            idx = int(hashlib.md5(name.encode()).hexdigest(), 16)
            conn.execute(
                "INSERT INTO mt_andromeda_stars (domain, star_name, constellation, "
                "spectral_type, domain_color, icon_emoji, description) "
                "VALUES (?,?,?,?,?,?,?)",
                (domain, name, '仙女座',
                 ['O5V', 'B8V', 'A3V', 'G2V', 'K1V', 'M5V'][idx % 6],
                 STAR_COLORS[idx % len(STAR_COLORS)],
                 STAR_EMOJIS[idx % len(STAR_EMOJIS)],
                 f'{title or "AI 明星员工"}|{spec[:40] or gtag[:40] or "综合领域"}'))
            existing.add(name)
            stats['added'] += 1
        conn.commit()
    finally:
        if own:
            conn.close()
    return stats


# ============================================================
# 3) 基础设施健康采集 (真实采样)
# ============================================================
def _flask_alive() -> int:
    try:
        with urllib.request.urlopen('http://127.0.0.1:5001/index', timeout=3) as r:
            return 1 if r.status == 200 else 0
    except Exception:
        return 0


def _sys_load() -> tuple:
    cpu = mem = 0.0
    try:
        cores = os.cpu_count() or 1
        cpu = round(min(os.getloadavg()[0] * 100 / cores, 100.0), 1)
    except Exception:
        pass
    try:
        out = subprocess.run(['ps', '-A', '-o', '%mem='],
                             capture_output=True, text=True, timeout=10).stdout
        vals = [float(x) for x in out.split() if x]
        if vals:
            mem = round(sum(vals), 1)
    except Exception:
        pass
    return cpu, mem


def health_once(conn=None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
    try:
        alive = _flask_alive()
        cpu, mem = _sys_load()
        db_ok = 0
        locked = 0
        try:
            conn.execute(
                "INSERT INTO andromeda_health_heartbeat (timestamp, flask_alive, "
                "flask_http_200, db_writable, db_locked_count, cpu_percent, "
                "mem_percent, anomalies_found) VALUES (?,?,?,?,?,?,?,?)",
                (_now(), alive, alive, 1, locked, cpu, mem,
                 0 if alive else 1))
            conn.commit()
            db_ok = 1
        except sqlite3.OperationalError:
            locked = 1
            try:
                conn2 = _connect()
                conn2.execute(
                    "INSERT INTO andromeda_health_heartbeat (timestamp, flask_alive, "
                    "flask_http_200, db_writable, db_locked_count, cpu_percent, "
                    "mem_percent, anomalies_found) VALUES (?,?,?,?,?,?,?,?)",
                    (_now(), alive, alive, 0, locked, cpu, mem,
                     1 if (not alive or locked) else 0))
                conn2.commit()
                conn2.close()
            except Exception:
                pass
        return {'flask_alive': alive, 'db_writable': db_ok, 'locked': locked,
                'cpu': cpu, 'mem': mem}
    finally:
        if own:
            conn.close()


# ============================================================
# 守护
# ============================================================
def _heartbeat():
    try:
        conn = _connect()
        conn.execute(
            "INSERT OR IGNORE INTO mt_daemon_registry "
            "(process_name, duty, pid, status, last_heartbeat, updated_at) "
            "VALUES (?,?,?,?, datetime('now','localtime'), datetime('now','localtime'))",
            (DAEMON_NAME, '社区治理 (三委立法+星空扩容+健康采集, 300s)', os.getpid()))
        conn.execute(
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), "
            "pid=?, status='RUNNING' WHERE process_name=?",
            (os.getpid(), DAEMON_NAME))
        conn.commit()
        conn.close()
    except Exception:
        pass


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'committee'
    if cmd == 'committee':
        print(json.dumps(committee_once(), ensure_ascii=False))
    elif cmd == 'stars':
        print(json.dumps(stars_expand_once(), ensure_ascii=False))
    elif cmd == 'health':
        print(json.dumps(health_once(), ensure_ascii=False))
    elif cmd == 'loop':
        print(f'[{DAEMON_NAME}] 守护启动 pid={os.getpid()} poll={POLL_SECS}s',
              flush=True)
        while True:
            try:
                c = committee_once()
                if any(c[k] for k in ('voted', 'bill_created', 'articled', 'enacted')):
                    print(f'[{DAEMON_NAME}] committee {c}', flush=True)
                s = stars_expand_once()
                if s['added']:
                    print(f'[{DAEMON_NAME}] stars {s}', flush=True)
                h = health_once()
                print(f'[{DAEMON_NAME}] health flask={h["flask_alive"]} '
                      f'db={h["db_writable"]} cpu={h["cpu"]}', flush=True)
            except Exception as e:
                sys.stderr.write(f'[{DAEMON_NAME}] cycle error: {e}\n')
            _heartbeat()
            time.sleep(POLL_SECS)
    else:
        print(f'unknown cmd: {cmd}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
