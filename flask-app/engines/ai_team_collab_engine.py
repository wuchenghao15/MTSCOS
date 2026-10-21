#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨团队协作总线 (Team Collaboration Bus)
========================================
flow_team_collab_20261022 · 任务中心自动分单 + 开发期实时沟通 + 知识共享

解决的问题:
  各天团/专家组/顾问各自为营、信息闭塞、闭门造车。
  任务一旦分派, 立刻开一个"协作频道", 把承办天团 + 协同天团 + 测试巡检天团
  + 战略顾问天团 + 知识脑库天团 + 领域专家 全部拉进来, 强制发声;
  沉默超阈值 → 告警催办; 有价值的建议/猜想跨频道广播并投喂脑库。

设计:
  - 零 token: 发言由本地规则模板生成(基于任务标题/领域/参与者), 不调 API
  - 复用现有体系: mt_lab_task_hall(任务大厅) / mt_team_registry(15天团)
    / mt_team_members(成员) / mt_ai_brain_feed_log(脑库投喂)
  - 只新增 3 张表: mt_collab_channel / mt_collab_message / mt_collab_participation

用法:
  python3 engines/ai_team_collab_engine.py --init      # 建表 + 回填在办任务频道
  python3 engines/ai_team_collab_engine.py --pulse     # 推进一轮交流
  python3 engines/ai_team_collab_engine.py --once      # init + pulse
  python3 engines/ai_team_collab_engine.py --status    # JSON 概览
  python3 engines/ai_team_collab_engine.py --loop 120  # 常驻
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime

FLOW_ID = 'flow_team_collab_20261022'
_FA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = (os.environ.get('MTSCOS_DB_PATH')
           or os.path.join(_FA, 'database', 'app.db'))

SILENCE_SECS = int(os.environ.get('MTSCOS_COLLAB_SILENCE', '1800'))
BROADCAST_LIMIT = 2

STRATEGY_TEAM = '🎯 战略顾问天团'
BRAIN_TEAM = '🧠 知识脑库天团'
QA_TEAM = '🧪 测试巡检天团'
ALWAYS = [STRATEGY_TEAM, BRAIN_TEAM]

DDL = [
    """CREATE TABLE IF NOT EXISTS mt_collab_channel (
    channel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hall_task_id INTEGER,
    title TEXT NOT NULL,
    domain TEXT,
    host_team TEXT,
    status TEXT DEFAULT 'ACTIVE',
    msg_count INTEGER DEFAULT 0,
    silent_alert_at TEXT,
    last_activity_at TEXT DEFAULT (datetime('now','localtime')),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    flow_id TEXT
)""",
    """CREATE TABLE IF NOT EXISTS mt_collab_message (
    msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    msg_type TEXT NOT NULL,
    content TEXT NOT NULL,
    ref_msg_id INTEGER,
    broadcast_from INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    flow_id TEXT
)""",
    """CREATE TABLE IF NOT EXISTS mt_collab_participation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    must_speak INTEGER DEFAULT 1,
    spoke_count INTEGER DEFAULT 0,
    last_spoke_at TEXT,
    silent_flag INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(channel_id, actor)
)""",
    "CREATE INDEX IF NOT EXISTS idx_collab_msg_ch ON mt_collab_message(channel_id, msg_id)",
    "CREATE INDEX IF NOT EXISTS idx_collab_ch_status ON mt_collab_channel(status, channel_id)",
]

_TEMPLATES = {
    'progress': [
        '{actor} 进度同步：{title} 当前推进到 {focus} 环节，已完成 {pct}%。',
        '{actor} 进展：{title} 的 {focus} 部分已打通，等待下游对齐。',
        '{actor} 状态：{title} 主体落地，正在回归验证 {focus}。',
    ],
    'question': [
        '{actor} 提问：{title} 的 {focus} 是否与 {peer} 的既有实现冲突？请确认口径。',
        '{actor} 疑问：{focus} 若复用现有模块，接口契约由谁定？建议 {peer} 明确。',
        '{actor} 澄清请求：{title} 在 {domain} 领域的验收标准是什么？需要可测量。',
    ],
    'suggestion': [
        '{actor} 建议：{title} 不要重造轮子，{focus} 可直接复用 {peer} 的现成能力。',
        '{actor} 建议：把 {focus} 抽成公共能力放进脑库，后续同类任务直接复用。',
        '{actor} 建议：{title} 增加一条自动校验，避免各团队各自理解的实现分叉。',
    ],
    'guess': [
        '{actor} 猜想：若 {focus} 继续按当前方案推进，{domain} 侧可能出现瓶颈，建议提前压测。',
        '{actor} 猜想：{title} 的真实瓶颈不在代码而在数据一致性，值得先做一次对账。',
        '{actor} 猜想：把 {focus} 拆成两段异步执行，能显著降低整机负载。',
    ],
    'risk': [
        '{actor} 风险提示：{title} 的 {focus} 缺少回滚方案，建议 {peer} 补一份。',
        '{actor} 风险提示：{domain} 相关改动会波及其他团队，需先广播变更。',
    ],
}

_FOCUS_POOL = ['架构设计', '接口契约', '数据落库', '权限校验', '性能压测',
               '异常兜底', '前端交互', '自动化回归', '知识沉淀']
_PCT_POOL = [20, 35, 50, 65, 80, 95]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA busy_timeout=20000')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def init_tables() -> int:
    conn = _db()
    try:
        for sql in DDL:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()
    return len(DDL)


def _teams(conn) -> list:
    try:
        return [dict(r) for r in conn.execute(
            'SELECT team_name, skill_keywords FROM mt_team_registry')]
    except sqlite3.Error:
        return []


def match_teams(text: str, limit: int = 3) -> list:
    """按关键词命中数把任务分给最相关的天团"""
    conn = _db()
    try:
        teams = _teams(conn)
    finally:
        conn.close()
    low = (text or '').lower()
    scored = []
    for t in teams:
        kws = [k.strip().lower() for k in (t.get('skill_keywords') or '').split(',') if k.strip()]
        hit = sum(1 for k in kws if k in low)
        if hit:
            scored.append((hit, t['team_name']))
    scored.sort(reverse=True)
    picked = [n for _h, n in scored[:limit]]
    if not picked:
        picked = ['⚙️ 后端工程天团']
    return picked


def _experts(conn, host_team: str, limit: int = 1) -> list:
    try:
        rows = conn.execute(
            'SELECT member_name, capabilities FROM mt_team_members WHERE team_name=? LIMIT ?',
            (host_team, limit)).fetchall()
        return [r['member_name'] for r in rows if r['member_name']]
    except sqlite3.Error:
        return []


def open_channel(hall_task: dict) -> dict | None:
    """为一个任务大厅任务开协作频道, 拉齐多方参与者"""
    title = (hall_task.get('title') or '').strip()
    if not title:
        return None
    desc = hall_task.get('description') or ''
    task_id = hall_task.get('id')
    conn = _db()
    try:
        exist = conn.execute(
            'SELECT channel_id FROM mt_collab_channel WHERE hall_task_id=?', (task_id,)).fetchone()
        if exist:
            return {'channel_id': exist['channel_id'], 'existing': True}

        teams = match_teams(title + ' ' + desc, limit=3)
        host = teams[0]
        parts = [(t, 'team') for t in teams]
        for extra in (QA_TEAM,) + tuple(ALWAYS):
            if extra not in [p[0] for p in parts]:
                parts.append((extra, 'team'))
        for e in _experts(conn, host, 1):
            parts.append((e, 'expert'))
        parts.append(('仙女座天团联席会', 'swarm'))
        parts.append(('领域顾问组', 'advisor'))

        cur = conn.execute(
            'INSERT INTO mt_collab_channel (hall_task_id,title,domain,host_team,flow_id) '
            'VALUES (?,?,?,?,?)',
            (task_id, title, (hall_task.get('source') or '开发'),
             host, FLOW_ID))
        cid = cur.lastrowid
        for actor, atype in parts:
            conn.execute(
                'INSERT OR IGNORE INTO mt_collab_participation '
                '(channel_id,actor,actor_type,must_speak) VALUES (?,?,?,1)',
                (cid, actor, atype))
        conn.execute(
            "INSERT INTO mt_collab_message (channel_id,actor,actor_type,msg_type,content,flow_id) "
            "VALUES (?,?,?,?,?,?)",
            (cid, '任务中心', 'ai', 'progress',
             '任务已自动分单：承办 %s；协同 %s；参与方 %d 个。本频道要求各方实时同步进展、提问、建议与猜想。'
             % (host, '、'.join(teams[1:]) or '无', len(parts)), FLOW_ID))
        conn.execute(
            "UPDATE mt_collab_channel SET msg_count=1 WHERE channel_id=?", (cid,))
        conn.commit()
        return {'channel_id': cid, 'host': host, 'participants': len(parts)}
    finally:
        conn.close()


def backfill(limit: int = 30) -> list:
    """把任务大厅在办任务全部开频道"""
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,title,description,source FROM mt_lab_task_hall "
            "WHERE status IN ('DISPATCHED','QUEUED','CLAIMED','IN_PROGRESS') "
            "ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
    out = []
    for t in rows:
        r = open_channel(t)
        if r:
            out.append(r)
    return out


def _render(msg_type: str, actor: str, task: dict, ctx: dict) -> str:
    tpls = _TEMPLATES.get(msg_type) or _TEMPLATES['progress']
    tpl = tpls[hash(actor + msg_type) % len(tpls)]
    return tpl.format(actor=actor, title=task.get('title') or '本任务',
                      domain=task.get('domain') or '研发',
                      focus=ctx['focus'], pct=ctx['pct'], peer=ctx['peer'],
                      ref=ctx['focus'])


def _broadcast(conn, src_cid: int, msg_id: int, msg_type: str, content: str,
               host: str) -> int:
    """把有价值的建议/猜想广播到**同领域**的其他频道, 防止闭门造车。
    只投同 domain 频道, 避免跨领域噪音刷屏。"""
    if msg_type not in ('suggestion', 'guess', 'risk'):
        return 0
    src = conn.execute('SELECT domain FROM mt_collab_channel WHERE channel_id=?',
                       (src_cid,)).fetchone()
    domain = (src['domain'] if src else '') or '开发'
    related = match_teams(content, limit=2)
    cands = {r['channel_id']: r for r in conn.execute(
        "SELECT channel_id,title,host_team FROM mt_collab_channel "
        "WHERE status='ACTIVE' AND channel_id!=? "
        "AND (IFNULL(domain,'开发')=? OR host_team IN (%s)) "
        "ORDER BY last_activity_at DESC LIMIT 20"
        % ','.join(['?'] * len(related)), (src_cid, domain, *related))}
    rows = list(cands.values())[:BROADCAST_LIMIT]
    sent = 0
    for r in rows:
        conn.execute(
            "INSERT INTO mt_collab_message "
            "(channel_id,actor,actor_type,msg_type,content,ref_msg_id,broadcast_from,flow_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (r['channel_id'], host + '(广播)', 'team', 'broadcast',
             '【跨频道共享】' + content, msg_id, src_cid, FLOW_ID))
        conn.execute(
            "UPDATE mt_collab_channel SET msg_count=msg_count+1, "
            "last_activity_at=datetime('now','localtime') WHERE channel_id=?",
            (r['channel_id'],))
        sent += 1
    return sent


def _feed_brain(conn, content: str, actor: str) -> None:
    try:
        conn.execute(
            "INSERT INTO mt_ai_brain_feed_log (flow_id,feed_target,payload_preview,fed_at,fed_by) "
            "VALUES (?,?,?,datetime('now','localtime'),?)",
            (FLOW_ID, 'team_collab', ('[%s] %s' % (actor, content))[:480], actor))
    except sqlite3.Error:
        pass


def pulse(batch: int = 3) -> dict:
    """推进一轮交流: 优先让最沉默的成员发声"""
    conn = _db()
    stats = {'channels': 0, 'messages': 0, 'broadcast': 0, 'alerts': 0, 'silent': 0}
    try:
        chans = [dict(r) for r in conn.execute(
            "SELECT * FROM mt_collab_channel WHERE status='ACTIVE' "
            "ORDER BY last_activity_at DESC LIMIT 20")]
        for ch in chans:
            cid = ch['channel_id']
            stats['channels'] += 1
            parts = [dict(r) for r in conn.execute(
                'SELECT * FROM mt_collab_participation WHERE channel_id=? '
                'ORDER BY spoke_count ASC, last_spoke_at ASC', (cid,))]
            if not parts:
                continue
            ctx = {
                'focus': _FOCUS_POOL[(cid + stats['messages']) % len(_FOCUS_POOL)],
                'pct': _PCT_POOL[(cid * 3 + stats['messages']) % len(_PCT_POOL)],
                'peer': parts[(stats['messages'] + 1) % len(parts)]['actor'],
            }
            for p in parts[:batch]:
                if p['actor_type'] == 'advisor':
                    mtype = 'risk'
                elif p['actor_type'] == 'swarm':
                    mtype = 'guess'
                elif p['actor_type'] == 'expert':
                    mtype = 'suggestion'
                elif p['spoke_count'] == 0:
                    mtype = 'question'
                else:
                    mtype = ('progress', 'suggestion', 'guess')[p['spoke_count'] % 3]
                content = _render(mtype, p['actor'], ch, ctx)
                cur = conn.execute(
                    "INSERT INTO mt_collab_message "
                    "(channel_id,actor,actor_type,msg_type,content,flow_id) VALUES (?,?,?,?,?,?)",
                    (cid, p['actor'], p['actor_type'], mtype, content, FLOW_ID))
                mid = cur.lastrowid
                conn.execute(
                    "UPDATE mt_collab_participation SET spoke_count=spoke_count+1, "
                    "last_spoke_at=datetime('now','localtime'), silent_flag=0, "
                    "updated_at=datetime('now','localtime') WHERE id=?", (p['id'],))
                stats['messages'] += 1
                stats['broadcast'] += _broadcast(conn, cid, mid, mtype, content,
                                                 ch['host_team'] or '协作总线')
                _feed_brain(conn, content, p['actor'])

            # 沉默检测 (基线取 max(频道创建时间, 上次发言))
            silent = conn.execute(
                "SELECT p.actor FROM mt_collab_participation p "
                "JOIN mt_collab_channel c ON c.channel_id=p.channel_id "
                "WHERE p.channel_id=? AND p.must_speak=1 AND c.created_at < "
                "datetime('now','localtime', ?) AND (p.last_spoke_at IS NULL OR "
                "p.last_spoke_at < datetime('now','localtime', ?))",
                (cid, '-%d seconds' % SILENCE_SECS, '-%d seconds' % SILENCE_SECS)).fetchall()
            if silent:
                stats['silent'] += len(silent)
                names = '、'.join(r['actor'] for r in silent)
                conn.execute(
                    "INSERT INTO mt_collab_message "
                    "(channel_id,actor,actor_type,msg_type,content,flow_id) "
                    "VALUES (?,?,?,?,?,?)",
                    (cid, '协作总线', 'ai', 'alert',
                     '沉默告警：%s 已超过 %d 秒未发声，请立即同步进展/提问/建议，禁止闭门造车。'
                     % (names, SILENCE_SECS), FLOW_ID))
                conn.execute(
                    "UPDATE mt_collab_channel SET silent_alert_at=datetime('now','localtime') "
                    "WHERE channel_id=?", (cid,))
                conn.execute(
                    "UPDATE mt_collab_participation SET silent_flag=1 WHERE channel_id=? "
                    "AND (last_spoke_at IS NULL OR last_spoke_at < datetime('now','localtime', ?))",
                    (cid, '-%d seconds' % SILENCE_SECS))
                stats['alerts'] += 1

            conn.execute(
                "UPDATE mt_collab_channel SET msg_count=msg_count+?, "
                "last_activity_at=datetime('now','localtime'), "
                "updated_at=datetime('now','localtime') WHERE channel_id=?",
                (min(batch, len(parts)), cid))
        conn.commit()
    finally:
        conn.close()
    return stats


def status() -> dict:
    conn = _db()
    try:
        ch = conn.execute("SELECT COUNT(*) FROM mt_collab_channel WHERE status='ACTIVE'").fetchone()[0]
        msg = conn.execute('SELECT COUNT(*) FROM mt_collab_message').fetchone()[0]
        part = conn.execute('SELECT COUNT(*) FROM mt_collab_participation').fetchone()[0]
        silent = conn.execute(
            'SELECT COUNT(*) FROM mt_collab_participation WHERE silent_flag=1').fetchone()[0]
        by_type = {r[0]: r[1] for r in conn.execute(
            'SELECT msg_type, COUNT(*) FROM mt_collab_message GROUP BY msg_type')}
        return {'active_channels': ch, 'messages': msg, 'participants': part,
                'silent': silent, 'by_type': by_type, 'db': DB_PATH}
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true')
    ap.add_argument('--pulse', action='store_true')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--loop', type=int, default=0)
    a = ap.parse_args()

    init_tables()
    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if a.init or a.once:
        print(json.dumps({'opened': backfill()}, ensure_ascii=False)[:600])
    if a.pulse or a.once:
        print(json.dumps({'pulse': pulse()}, ensure_ascii=False))
    if a.loop:
        while True:
            try:
                backfill()
                pulse()
            except Exception as e:
                print('[collab] ERR %s' % e, flush=True)
            time.sleep(a.loop)
    return 0


if __name__ == '__main__':
    print('[%s] team collab bus ready db=%s' % (
        datetime.now().strftime('%H:%M:%S'), DB_PATH))
    raise SystemExit(main())
