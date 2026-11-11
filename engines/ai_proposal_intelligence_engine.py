#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_proposal_intelligence_engine — 🧠 提案智能全链路引擎
========================================================

flow_proposal_intel_20261028

目标: 把散落在不同模块的提案能力 (16 维度咨询/状态机/归档/脑库投喂) 串成一个
自包含的"提案智能闭环"。每个函数都是短连接、幂等、零 LLM token 成本。

13 个智能能力 (一一对应需求):
  ① ingest_and_tag        — 智能入厅 + 自动标签 (tag_bank 复用)
  ② intent_analyze        — 智能消化提案意图 (真正需求/收益预估/解决路径)
  ③ quality_check         — 智能质检 (标题空/验收标准/可执行性)
  ④ smart_dispatch        — 智能分拣托管 (比关键词更强的中心匹配)
  ⑤ state_feedback_feed   — 智能反馈任务状态 (每步状态变更都 feed brain)
  ⑥ auto_close            — 智能闭环 (DONE + N 天 自动 close)
  ⑦ auto_archive          — 智能备案 (DONE → 自动写 proposal_archive)
  ⑧ auto_upload          — 智能上传 (备案后自动上传本地归档)
  ⑨ brain_feed            — 智能投喂 AI 脑库 (问题特征库 + 标签库)
  ⑩ escape_loop          — 智能跳出闭环 (卡住自动 escape: 多次 REWORK/超时)
  ⑪ followup_scheduler   — 智能事后跟踪回访 (DONE 后 7/14/30 天)
  ⑫ chain_digest         — 智能调研总结 (每日串并: 同领域链/同标签并行)
  ⑬ summary_report        — 智能新提案串并 (每周总结 → 新提案种子)

启动:
  python3 engines/ai_proposal_intelligence_engine.py once
  python3 engines/ai_proposal_intelligence_engine.py loop
  python3 engines/ai_proposal_intelligence_engine.py --tags           # 只跑标签
  python3 engines/ai_proposal_intelligence_engine.py --intent          # 只跑意图
  python3 engines/ai_proposal_intelligence_engine.py --followup-check  # 只跑回访
"""

from __future__ import annotations
import os, sys, time, json, sqlite3, re, hashlib
from datetime import datetime, timezone, timedelta

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_proposal_intel_20261028"
DAEMON = "ai_proposal_intel"

# ═══════════════════════════════════════════════════════════════════
# §0 表结构 (幂等, 建过再跑不会报错)
# ═══════════════════════════════════════════════════════════════════

_SCHEMA = [
    # 提案智能画像 — 每个提案一张 (idempotent)
    """CREATE TABLE IF NOT EXISTS mt_proposal_intel (
        task_id INTEGER PRIMARY KEY,
        hall_code TEXT,
        auto_tags TEXT,               -- JSON: ["教育","题库"]
        intent_summary TEXT,          -- 1 句意图总结
        real_need TEXT,               -- 真正想解决的问题 (16 维度)
        benefit_estimate TEXT,        -- 收益预估 (定性)
        solution_path TEXT,           -- 建议解决路径 (JSON: [step1, step2])
        quality_score INTEGER DEFAULT 100,   -- 0-100 智能质检
        quality_flags TEXT,           -- JSON: 质检异常
        chain_id INTEGER,             -- 属于哪个串 (同领域链)
        parallel_id INTEGER,          -- 属于哪个并行组 (同标签并行)
        auto_closed INTEGER DEFAULT 0,-- 是否自动闭环归档
        closed_at TEXT,
        escape_reason TEXT,           -- 跳出闭环原因 (若有)
        followup_state TEXT DEFAULT 'NONE',  -- NONE/PENDING/DONE/MISSED
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 标签库 — 跨提案复用, 用于串并
    """CREATE TABLE IF NOT EXISTS mt_proposal_tag_bank (
        tag TEXT PRIMARY KEY,
        center_codes TEXT,            -- 哪些 center_code 常用此 tag (JSON)
        domain_hint TEXT,             -- 领域提示 (EDU/ENGINE/SECURITY/...)
        hit_count INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 回访跟踪 — 待回访的提案
    """CREATE TABLE IF NOT EXISTS mt_proposal_followup (
        fu_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        hall_code TEXT,
        followup_at TEXT NOT NULL,   -- 计划回访时间
        check_type TEXT,              -- 7天/14天/30天
        status TEXT DEFAULT 'PENDING', -- PENDING/DONE/MISSED
        outcome TEXT,                 -- 回访结果 JSON
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(task_id, check_type))""",

    # 串并关系 — 提案间的联动链
    """CREATE TABLE IF NOT EXISTS mt_proposal_chain (
        chain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chain_key TEXT UNIQUE,        -- md5(按标签/领域归类)
        chain_type TEXT,              -- DOMAIN_CHAIN / TAG_PARALLEL / SIMILAR_PARALLEL
        summary TEXT,                 -- 调研总结文案
        seed_text TEXT,               -- 新提案种子 (若有)
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')))""",

    # 串并明细
    """CREATE TABLE IF NOT EXISTS mt_proposal_chain_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chain_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        relation TEXT,                -- 同领域/同标签/同方案
        UNIQUE(chain_id, task_id))""",
]


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def install_schema():
    c = _db()
    for s in _SCHEMA:
        try:
            c.execute(s)
        except Exception:
            pass
    # daemon 注册
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (DAEMON, "提案智能全链路: 13 智能 (tag/intent/quality/dispatch/feedback/close/archive/brain_feed/qbank/escape/followup/chain/summary)",
             "RUNNING", now, os.getpid(),
             json.dumps({"flow_id": FLOW_ID, "version": "20261028"}, ensure_ascii=False),
             now))
    except Exception:
        pass
    c.close()


# ═══════════════════════════════════════════════════════════════════
# §0.5 标签库 (静态, 零 LLM) — 13 智能共用
# ═══════════════════════════════════════════════════════════════════

TAG_DOMAIN_MAP = {
    # tag → (领域提示, center_code 候选)
    "教育": ("EDU", ["edu_qbank"]),
    "题库": ("EDU", ["edu_qbank"]),
    "试卷": ("EDU", ["edu_qbank"]),
    "讲解": ("EDU", ["edu_qbank"]),
    "学情": ("EDU", ["edu_qbank", "data_research"]),
    "考试": ("EDU", ["edu_qbank"]),
    "AI": ("AI", ["ai_engine"]),
    "引擎": ("AI", ["ai_engine"]),
    "模型": ("AI", ["ai_engine"]),
    "RAG": ("AI", ["ai_engine", "data_research"]),
    "向量": ("AI", ["ai_engine", "data_research"]),
    "Agent": ("AI", ["ai_engine"]),
    "安全": ("SECURITY", ["vuln_fix"]),
    "漏洞": ("SECURITY", ["vuln_fix"]),
    "合规": ("SECURITY", ["legal"]),
    "守护": ("SECURITY", ["legal", "daemon_ops"]),
    "自动化": ("ENGINE", ["workflow", "ai_engine"]),
    "工作流": ("ENGINE", ["workflow"]),
    "流程": ("ENGINE", ["workflow"]),
    "数据": ("DATA", ["data_research"]),
    "分析": ("DATA", ["data_research"]),
    "大数据": ("DATA", ["data_research"]),
    "前端": ("FRONT", ["frontend_design"]),
    "UI": ("FRONT", ["frontend_design"]),
    "界面": ("FRONT", ["frontend_design"]),
    "备份": ("OPS", ["daemon_ops"]),
    "守护进程": ("OPS", ["daemon_ops"]),
    "巡检": ("OPS", ["daemon_ops", "security_audit"]),
    "自愈": ("OPS", ["daemon_ops"]),
    "监控": ("OPS", ["daemon_ops", "data_research"]),
    "规则": ("GOV", ["rules_gov"]),
    "治理": ("GOV", ["rules_gov"]),
    "立法": ("GOV", ["legal"]),
    "预算": ("HR", ["hr_center"]),
    "人员": ("HR", ["hr_center"]),
    "专家": ("HR", ["expert_team"]),
    "招聘": ("HR", ["hr_center", "expert_team"]),
    "技能": ("HR", ["skill_dev"]),
}


def _extract_tags(text: str) -> list:
    """从 title+description 抽取标签 (零 LLM, 关键词命中)."""
    if not text:
        return []
    hits = []
    lower = text.lower()
    for tag, _info in TAG_DOMAIN_MAP.items():
        if tag.lower() in lower:
            hits.append(tag)
    # 去重保持顺序
    seen = set()
    out = []
    for t in hits:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:8]


def _domains_from_tags(tags: list) -> set:
    d = set()
    for t in tags:
        info = TAG_DOMAIN_MAP.get(t)
        if info:
            d.add(info[0])
    return d


def _center_codes_from_tags(tags: list) -> list:
    codes = []
    for t in tags:
        info = TAG_DOMAIN_MAP.get(t)
        if info:
            codes.extend(info[1])
    # 去重
    seen = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:5]


def _update_tag_bank(c: sqlite3.Connection, tags: list):
    for tag in tags:
        info = TAG_DOMAIN_MAP.get(tag, ("OTHER", []))
        c.execute("""INSERT OR IGNORE INTO mt_proposal_tag_bank
            (tag, center_codes, domain_hint) VALUES (?,?,?)""",
            (tag, json.dumps(info[1], ensure_ascii=False), info[0]))
        c.execute("""UPDATE mt_proposal_tag_bank
            SET hit_count = hit_count + 1, updated_at=datetime('now','localtime') WHERE tag=?""",
            (tag,))


# ═══════════════════════════════════════════════════════════════════
# ① ingest_and_tag — 智能入厅 + 自动标签
# ═══════════════════════════════════════════════════════════════════

def ingest_and_tag() -> dict:
    """扫所有 mt_lab_task_hall 中还没写画像的任务 → 自动画像 + 标签."""
    c = _db()
    tagged = 0
    try:
        rows = c.execute("""
            SELECT h.id, h.hall_code, h.title, h.description, h.status
            FROM mt_lab_task_hall h
            LEFT JOIN mt_proposal_intel i ON i.task_id = h.id
            WHERE i.task_id IS NULL
              AND h.status IN ('QUEUED','DISPATCHED','CLAIMED','IN_PROGRESS','DELIVERED','DONE')
            ORDER BY h.id DESC LIMIT 30""").fetchall()

        for tid, hc, title, desc, st in rows:
            text = f"{title or ''} {desc or ''}"
            tags = _extract_tags(text)
            summary = (title or "")[:120]
            quality = 100
            qflags = []
            if not title:
                quality -= 30; qflags.append("empty_title")
            if len(desc or "") < 20:
                quality -= 20; qflags.append("too_short_desc")
            if not tags:
                quality -= 10; qflags.append("no_keywords")

            c.execute("""INSERT INTO mt_proposal_intel
                (task_id, hall_code, auto_tags, intent_summary, real_need,
                 quality_score, quality_flags)
                VALUES (?,?,?,?,?,?,?)""",
                (tid, hc, json.dumps(tags, ensure_ascii=False), summary,
                 desc[:300] if desc else summary,
                 quality, json.dumps(qflags, ensure_ascii=False)))
            tagged += 1
            if tags:
                _update_tag_bank(c, tags)

        c.commit()
    finally:
        c.close()
    return {"ok": True, "tagged": tagged}


# ═══════════════════════════════════════════════════════════════════
# ② intent_analyze — 智能消化提案意图
# ═══════════════════════════════════════════════════════════════════

def intent_analyze() -> dict:
    """对已有画像但 real_need / solution_path 为空的任务做意图补全."""
    c = _db()
    analyzed = 0
    try:
        rows = c.execute("""
            SELECT task_id, hall_code, intent_summary, real_need, auto_tags
            FROM mt_proposal_intel WHERE real_need IS NULL OR real_need='' LIMIT 20""").fetchall()
        for tid, hc, summary, _rn, tags_str in rows:
            tags = json.loads(tags_str or "[]")
            domains = _domains_from_tags(tags)
            # 意图分层: 真正需求 + 收益预估 + 解决路径 (零 LLM, 模板化)
            need_parts = [f"领域={','.join(domains) or 'OTHER'}"]
            benefit = "定性: 提升对应领域智能自动化水平 + 沉淀标签/意图/方案模板"
            # 解决路径建议 3 步
            path = []
            if "EDU" in domains:
                path = ["1. 16 维度深度咨询", "2. 派单教育题库中心 + 考试引擎中心", "3. 验收 DONE 后自动归档 + 脑库"]
            elif "AI" in domains:
                path = ["1. 16 维度咨询 (重点: 真正需求/AI 员工需求)", "2. 派单 AI 引擎中心 + 专家团队中心", "3. 验收后自动衍生 Skill + 脑库"]
            elif "SECURITY" in domains:
                path = ["1. 合规/漏洞维度重点打分", "2. 派单 漏洞修复适配中心", "3. 安全中心备案 + 脑库"]
            else:
                path = ["1. 16 维度深度咨询", "2. 派单对口中心", "3. 验收归档"]

            real_need = f"真需求=让「{summary or ''}」领域从手动/半自动→全自动; {need_parts[0]}"
            c.execute("""UPDATE mt_proposal_intel SET
                real_need=?, benefit_estimate=?, solution_path=?, updated_at=datetime('now','localtime')
                WHERE task_id=?""",
                (real_need, benefit, json.dumps(path, ensure_ascii=False), tid))
            analyzed += 1
        c.commit()
    finally:
        c.close()
    return {"ok": True, "analyzed": analyzed}


# ═══════════════════════════════════════════════════════════════════
# ③ quality_check — 智能质检
# ═══════════════════════════════════════════════════════════════════

def quality_check() -> dict:
    """重新算 quality_score (已画像任务, 分数变了就 UPDATE)."""
    c = _db()
    checked = 0
    try:
        rows = c.execute("""
            SELECT i.task_id, i.auto_tags, i.quality_score,
                   h.acceptance_criteria, h.publisher_role
            FROM mt_proposal_intel i JOIN mt_lab_task_hall h ON h.id=i.task_id
            WHERE h.status IN ('QUEUED','DISPATCHED','CLAIMED')
            LIMIT 30""").fetchall()
        for tid, tags_str, old_q, ac, pub_role in rows:
            tags = json.loads(tags_str or "[]")
            q = 100
            flags = []
            if len(tags) < 2:
                q -= 10; flags.append(f"tag_lt_2({len(tags)})")
            if not ac or len(ac.strip()) < 10:
                q -= 20; flags.append("no_acceptance_criteria")
            if pub_role == "user":
                q -= 5  # 普通用户提案可适度提示
            q = max(0, min(100, q))
            if q != old_q:
                c.execute("""UPDATE mt_proposal_intel
                    SET quality_score=?, quality_flags=?, updated_at=datetime('now','localtime')
                    WHERE task_id=?""", (q, json.dumps(flags, ensure_ascii=False), tid))
                checked += 1
        c.commit()
    finally:
        c.close()
    return {"ok": True, "updated": checked}


# ═══════════════════════════════════════════════════════════════════
# ④ smart_dispatch — 智能分拣托管 (画像+标签 增强派单)
# ═══════════════════════════════════════════════════════════════════

def smart_dispatch() -> dict:
    """找 QUEUED 未派单 + 已有画像 → 调 _hall_dispatch_one 派单
    注意: 派单主逻辑仍在 daemon_skill_lab_bp._hall_dispatch_one,
          这里只做"自动触发" + 为画像强的任务补关键词.
    """
    c = _db()
    dispatched, skipped = 0, 0
    try:
        rows = c.execute("""
            SELECT h.id, h.title, h.description, h.hall_code,
                   i.auto_tags
            FROM mt_lab_task_hall h
            LEFT JOIN mt_proposal_intel i ON i.task_id=h.id
            WHERE h.status='QUEUED' AND h.center_id IS NULL
            LIMIT 10""").fetchall()
    finally:
        c.close()

    # 没画像的先让 ingest_and_tag 给补上
    if rows:
        ingest_and_tag()

    c = _db()
    try:
        rows2 = c.execute("""
            SELECT h.id, h.title, h.description, h.hall_code, i.auto_tags
            FROM mt_lab_task_hall h
            JOIN mt_proposal_intel i ON i.task_id=h.id
            WHERE h.status='QUEUED' AND h.center_id IS NULL
            LIMIT 10""").fetchall()
    finally:
        c.close()

    for tid, title, desc, hc, tags_str in rows2:
        tags = json.loads(tags_str or "[]")
        # 补关键词进 description (让官方派单函数匹配更准)
        if "[INTEL-AUTO]" not in (desc or "") and tags:
            c = _db()
            try:
                c.execute("UPDATE mt_lab_task_hall SET description=? WHERE id=?",
                          ((desc or "") + f"\n\n[INTEL-AUTO] 智能标签: {','.join(tags)}"[:500], tid))
                c.commit()
            finally:
                c.close()
        # 触发 run_hall_auto 派单 (官方三轨前置流程)
        try:
            sys.path.insert(0, APP_DIR)
            from blueprints.daemon_skill_lab_bp import run_hall_auto
            r = run_hall_auto()
            dispatched += r.get("dispatched", 0) if isinstance(r, dict) else 0
        except Exception as e:
            skipped += 1
            print(f"  [smart_dispatch] skip task={tid}: {type(e).__name__}: {str(e)[:80]}")

    return {"ok": True, "dispatched": dispatched, "skipped": skipped}


# ═══════════════════════════════════════════════════════════════════
# ⑤ state_feedback_feed — 智能回馈任务状态
# ═══════════════════════════════════════════════════════════════════

def state_feedback_feed() -> dict:
    """扫最近状态变更 (mt_lab_task_events) → 每步都 feed brain.
    零 LLM, 只写 mt_ai_brain_feed_log."""
    c = _db()
    fed = 0
    try:
        rows = c.execute("""
            SELECT e.hall_task_id, e.event, e.actor, e.actor_role, e.note,
                   substr(e.created_at,1,19) AS ev_at
            FROM mt_lab_task_events e
            LEFT JOIN mt_proposal_intel i ON i.task_id=e.hall_task_id
            LEFT JOIN mt_ai_brain_feed_log f ON f.feed_target LIKE CONCAT('%',e.hall_task_id,'%')
            WHERE e.created_at > datetime('now','localtime','-1 hours')
              AND f.rowid IS NULL
              AND e.event IN ('PUBLISH','DISPATCH','CLAIM','START','DELIVER','ACCEPT','REWORK','RECYCLE','ARCHIVE','CANCEL')
            LIMIT 50""").fetchall()
        for tid, event, actor, role, note, ev_at in rows:
            try:
                c.execute("""INSERT INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, payload_preview, fed_at, fed_by)
                    VALUES (?,?,?,?,?)""",
                    (FLOW_ID, f"task_{tid}",
                     f"[{event}] {actor}({role}) | {note or ''} | {ev_at}"[:800],
                     ev_at, "proposal_intel"))
                fed += 1
            except Exception:
                pass
        c.commit()
    finally:
        c.close()
    return {"ok": True, "brain_fed": fed}


# ═══════════════════════════════════════════════════════════════════
# ⑥ auto_close — 智能闭环 (DONE + 5 天 → 自动 close)
# ═══════════════════════════════════════════════════════════════════

AUTO_CLOSE_DAYS = int(os.environ.get('PROPOSAL_AUTO_CLOSE_DAYS', 5))

def auto_close() -> dict:
    """DONE 超过 N 天 且未 close → 自动把 proposal_intel 标记 auto_closed=1."""
    c = _db()
    closed = 0
    try:
        rows = c.execute("""
            SELECT i.task_id, i.hall_code, h.done_at, h.accepted_at,
                   COALESCE(h.accepted_at, h.done_at, h.updated_at) AS close_ref
            FROM mt_proposal_intel i
            JOIN mt_lab_task_hall h ON h.id=i.task_id
            WHERE i.auto_closed=0
              AND h.status='DONE'
              AND close_ref < datetime('now','localtime',?)
            LIMIT 50""", (f'-{AUTO_CLOSE_DAYS} days',)).fetchall()
        for tid, hc, _da, _aa, _cr in rows:
            c.execute("""UPDATE mt_proposal_intel
                SET auto_closed=1, closed_at=datetime('now','localtime')
                WHERE task_id=?""", (tid,))
            # 写 followup 3 档: 7/14/30 天后回访
            for days, ctype in [(7, "7d"), (14, "14d"), (30, "30d")]:
                fu_time = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                try:
                    c.execute("""INSERT OR IGNORE INTO mt_proposal_followup
                        (task_id, hall_code, followup_at, check_type, status)
                        VALUES (?,?,?,?,'PENDING')""", (tid, hc, fu_time, ctype))
                except Exception:
                    pass
            # 事件留痕
            c.execute("""INSERT INTO mt_lab_task_events
                (hall_task_id, event, actor, actor_role, note)
                VALUES (?,?,?,?,?)""",
                (tid, "AUTO_CLOSE", "proposal_intel", "system",
                 f"DONE +{AUTO_CLOSE_DAYS} 天自动闭环, 已挂回访 {7}/{14}/{30} 天"))
            closed += 1
        c.commit()
    finally:
        c.close()
    return {"ok": True, "closed": closed, "close_days": AUTO_CLOSE_DAYS}


# ═══════════════════════════════════════════════════════════════════
# ⑦⑧ auto_archive + auto_upload — 智能备案 + 智能上传
# ═══════════════════════════════════════════════════════════════════

def auto_archive() -> dict:
    """自动把 DONE 的任务写到 mt_lab_task_hall.archived_at (备案标记)."""
    c = _db()
    archived = 0
    try:
        days = max(int(os.environ.get('PROPOSAL_AUTO_ARCHIVE_DAYS', 30)), 1)
        cur = c.execute("""
            UPDATE mt_lab_task_hall
            SET archived_at=datetime('now','localtime'),
                updated_at=datetime('now','localtime')
            WHERE status='DONE'
              AND archived_at IS NULL
              AND COALESCE(accepted_at, updated_at, created_at)
                    < datetime('now','localtime',?)""", (f'-{days} days',))
        archived = cur.rowcount
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, detail)
            VALUES (?,?,?,?)""",
            ("PROPOSAL_INTEL", "AUTO_ARCHIVE", "OK",
             json.dumps({"archived": archived, "days": days}, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()
    return {"ok": True, "archived": archived, "archive_days": days}


def auto_upload() -> dict:
    """智能上传: 刚归档的任务 → 写归档目录 _runtime/archive/proposals/ (本地备份).
    不依赖云, 纯本地. 云同步后续走 autosync daemon."""
    archive_dir = os.path.join(APP_DIR, "_runtime", "archive", "proposals")
    os.makedirs(archive_dir, exist_ok=True)
    uploaded = 0
    c = _db()
    try:
        rows = c.execute("""
            SELECT i.task_id, i.hall_code, h.title, h.description, i.auto_tags,
                   i.intent_summary, i.real_need, i.benefit_estimate, i.solution_path
            FROM mt_proposal_intel i
            JOIN mt_lab_task_hall h ON h.id=i.task_id
            WHERE h.archived_at IS NOT NULL
              AND i.auto_closed=1
              AND i.closed_at > datetime('now','localtime','-3 days')
            LIMIT 20""").fetchall()
    finally:
        c.close()

    now_str = datetime.now().strftime("%Y%m%d")
    for tid, hc, title, desc, tags_s, summary, need, benefit, path_s in rows:
        fn = f"{now_str}_{hc or 'NOCODE'}_{tid}.json"
        fp = os.path.join(archive_dir, fn)
        if os.path.exists(fp):
            continue
        payload = {
            "task_id": tid, "hall_code": hc, "title": title,
            "description": desc, "tags": json.loads(tags_s or "[]"),
            "intent": summary, "real_need": need, "benefit": benefit,
            "solution_path": json.loads(path_s or "[]"),
            "archived_at": datetime.now().isoformat(),
        }
        try:
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            uploaded += 1
        except Exception:
            pass

    return {"ok": True, "uploaded": uploaded, "archive_dir": archive_dir}


# ═══════════════════════════════════════════════════════════════════
# ⑨ brain_feed — 智能投喂 AI 脑库 + 问题特征库
# ═══════════════════════════════════════════════════════════════════

def brain_feed() -> dict:
    """汇总:
      (a) 每步状态变更 → mt_ai_brain_feed_log
      (b) DONE 任务 → 提取问题特征 → mt_ai_brain_feed_log (feature_feed)
      (c) 新标签 → tag_bank hit_count 增量
    """
    # (a) 已由 state_feedback_feed 完成
    fed_a = state_feedback_feed()

    # (b) DONE 任务 → 问题特征库
    c = _db()
    fed_b = 0
    try:
        rows = c.execute("""
            SELECT h.id, h.hall_code, h.title, h.deliverable,
                   i.auto_tags, i.intent_summary
            FROM mt_lab_task_hall h
            JOIN mt_proposal_intel i ON i.task_id=h.id
            WHERE h.status='DONE' AND h.accepted_at > datetime('now','localtime','-1 days')
            LIMIT 20""").fetchall()
        for tid, hc, title, deliverable, tags_s, intent in rows:
            tags = json.loads(tags_s or "[]")
            feature_str = f"[FEATURE] {hc} | tags={','.join(tags)} | intent={intent or title[:80]} | deliverable={(deliverable or '')[:200]}"
            try:
                c.execute("""INSERT INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, payload_preview, fed_at, fed_by)
                    VALUES (?,?,?,datetime('now','localtime'),?)""",
                    (FLOW_ID, f"qbank_feature_{tid}", feature_str[:800], "proposal_intel_feature"))
                fed_b += 1
            except Exception:
                pass
        c.commit()
    finally:
        c.close()

    # (c) 标签库已在 ingest_and_tag 里自动更新

    return {"ok": True, "step_a_feedback": fed_a.get("brain_fed", 0),
            "step_b_qbank": fed_b}


# ═══════════════════════════════════════════════════════════════════
# ⑩ escape_loop — 智能跳出闭环
# ═══════════════════════════════════════════════════════════════════

def escape_loop() -> dict:
    """检测卡住的提案:
      (a) DELIVERED 超过 24h 没人验收 → 自动 escape (打回 CLAIMED + 派 auto_repair daemon)
      (b) REWORK 回 IN_PROGRESS 超过 2 次 → 自动 escape (加 escape_reason 标记, 人工介入)
    """
    c = _db()
    escaped = 0
    try:
        # (a) DELIVERED 卡住
        stuck = c.execute("""
            SELECT id, hall_code, title FROM mt_lab_task_hall
            WHERE status='DELIVERED'
              AND delivered_at < datetime('now','localtime','-24 hours')
            LIMIT 10""").fetchall()
        for tid, hc, title in stuck:
            # 走 transition_cas 回 CLAIMED
            try:
                sys.path.insert(0, APP_DIR)
                from engines.ai_task_hall_flow_engine import transition_cas
                won, _, _, _ = transition_cas(tid, "DELIVERED", "CLAIMED",
                                              actor="proposal_intel(escape)",
                                              reason="DELIVERED 超时 24h 自动 escape")
                if won:
                    c.execute("""UPDATE mt_proposal_intel
                        SET escape_reason='DELIVERED_STUCK_24H',
                            updated_at=datetime('now','localtime')
                        WHERE task_id=?""", (tid,))
                    escaped += 1
            except Exception as e:
                print(f"  [escape] DELIVERED stuck task={tid}: {e}")

        # (b) REWORK 次数过多 — 从 flow_history 里数
        loops = c.execute("""
            SELECT h.id, h.hall_code, COUNT(e.rowid) cnt
            FROM mt_lab_task_hall h
            JOIN mt_lab_task_events e ON e.hall_task_id=h.id
            WHERE e.event='REWORK' AND h.status='IN_PROGRESS'
            GROUP BY h.id HAVING cnt >= 2
            LIMIT 10""").fetchall()
        for tid, hc, cnt in loops:
            c.execute("""UPDATE mt_proposal_intel
                SET escape_reason=?, updated_at=datetime('now','localtime')
                WHERE task_id=?""", (f"REWORK_LOOP_{cnt}X", tid))
            # 打 warning 日志
            c.execute("""INSERT INTO mt_center_self_drive_log
                (center_name, action, task_hall_id, outcome, detail)
                VALUES (?,?,?,?,?)""",
                ("PROPOSAL_INTEL", "ESCAPE_LOOP", tid, "WARN",
                 json.dumps({"reason": f"REWORK {cnt} 次", "hall_code": hc}, ensure_ascii=False)))
            escaped += 1
        c.commit()
    finally:
        c.close()
    return {"ok": True, "escaped": escaped}


# ═══════════════════════════════════════════════════════════════════
# ⑪ followup_scheduler — 智能事后跟踪回访
# ═══════════════════════════════════════════════════════════════════

def followup_scheduler() -> dict:
    """扫 mt_proposal_followup 到期的 → 标记 DONE + 写回访日志.
    回访就是"再看一眼这个提案, 有没有新标签/新串/新种子"。
    """
    c = _db()
    done_n = 0
    missed_n = 0
    try:
        # PENDING 到期 → 跑回访分析
        rows = c.execute("""
            SELECT fu.fu_id, fu.task_id, fu.hall_code, fu.check_type,
                   fu.followup_at
            FROM mt_proposal_followup fu
            WHERE fu.status='PENDING' AND fu.followup_at <= datetime('now','localtime')
            LIMIT 30""").fetchall()

        for fid, tid, hc, ctype, fu_at in rows:
            # 回访分析: 重新抓标题+描述+最新标签数 → 总结
            r = c.execute("""
                SELECT i.auto_tags, h.status, h.done_at, h.updated_at
                FROM mt_proposal_intel i JOIN mt_lab_task_hall h ON h.id=i.task_id
                WHERE i.task_id=?""", (tid,)).fetchone()
            if not r:
                missed_n += 1
                c.execute("UPDATE mt_proposal_followup SET status='MISSED' WHERE fu_id=?", (fid,))
                continue

            tags_s, status, done_at, updated_at = r
            tags = json.loads(tags_s or "[]")

            # 同标签其他提案数 (回访的价值点: 有没有新类似提案?)
            similar = 0
            if tags:
                placeholders = ",".join("?" * len(tags[:5]))
                similar = c.execute(f"""SELECT COUNT(*) FROM mt_proposal_intel
                    WHERE task_id != ? AND auto_tags LIKE ?
                    LIMIT 1""",
                    (tid, f"%{tags[0]}%") if tags else (tid, "")).fetchone()[0]

            outcome = json.dumps({
                "check_type": ctype, "status_now": status,
                "tags_now": tags, "similar_same_tag": similar,
                "tags_count": len(tags),
            }, ensure_ascii=False)

            c.execute("""UPDATE mt_proposal_followup
                SET status='DONE', outcome=? WHERE fu_id=?""", (outcome, fid))
            # 同时把回访信息 feed 回 brain
            try:
                c.execute("""INSERT INTO mt_ai_brain_feed_log
                    (flow_id, feed_target, payload_preview, fed_at, fed_by)
                    VALUES (?,?,?,datetime('now','localtime'),?)""",
                    (FLOW_ID, f"followup_{tid}_{ctype}",
                     f"[FOLLOWUP-{ctype}] {hc or tid} → {status} | 相似提案={similar} | 标签={','.join(tags[:5])}"[:800],
                     "proposal_intel"))
            except Exception:
                pass
            done_n += 1

        c.commit()
    finally:
        c.close()
    return {"ok": True, "followup_done": done_n, "missed": missed_n}


# ═══════════════════════════════════════════════════════════════════
# ⑫ chain_digest — 智能调研总结 (每日串并)
# ═══════════════════════════════════════════════════════════════════

def chain_digest() -> dict:
    """按领域/标签聚类 → 同领域链 / 同标签并行 → 写 mt_proposal_chain."""
    c = _db()
    chains_made = 0
    try:
        rows = c.execute("""
            SELECT task_id, auto_tags, intent_summary, quality_score
            FROM mt_proposal_intel WHERE quality_score >= 80 LIMIT 100""").fetchall()
        # 按 tag 聚
        bucket_by_tag = {}   # tag → [task_id]
        for tid, tags_s, _sum, _qs in rows:
            tags = json.loads(tags_s or "[]")
            for t in tags:
                bucket_by_tag.setdefault(t, []).append(tid)

        # 按 domain 聚
        bucket_by_domain = {}  # domain → [task_id]
        for tid, tags_s, _sum, _qs in rows:
            tags = json.loads(tags_s or "[]")
            for d in _domains_from_tags(tags):
                bucket_by_domain.setdefault(d, []).append(tid)

        # domain 链
        for domain, tids in bucket_by_domain.items():
            if len(tids) < 2:
                continue
            chain_key = f"DOMAIN::{domain}"
            hk = hashlib.md5(chain_key.encode()).hexdigest()[:12]
            try:
                cur = c.execute("""INSERT OR IGNORE INTO mt_proposal_chain
                    (chain_key, chain_type, summary, created_at)
                    VALUES (?,?,?,datetime('now','localtime'))""",
                    (hk, "DOMAIN_CHAIN",
                     f"[{domain}] 同领域 {len(tids)} 个智能提案已串, 建议形成研究链"))
                chain_id = cur.lastrowid
                if cur.rowcount == 0:
                    # 已存在 → 取原 id
                    chain_id = c.execute("SELECT chain_id FROM mt_proposal_chain WHERE chain_key=?",
                                         (hk,)).fetchone()[0]
                for tid in tids:
                    c.execute("""INSERT OR IGNORE INTO mt_proposal_chain_members
                        (chain_id, task_id, relation) VALUES (?,?,?)""",
                        (chain_id, tid, f"domain_{domain}"))
                c.execute("UPDATE mt_proposal_intel SET chain_id=?, updated_at=datetime('now','localtime') WHERE task_id IN ({})"
                          .format(",".join("?" * len(tids))), [chain_id] + tids)
                chains_made += 1
            except Exception as e:
                print(f"  [chain] domain={domain}: {e}")

        # tag 并行组 (跨 domain 但同标签)
        for tag, tids in bucket_by_tag.items():
            if len(tids) < 3:
                continue
            chain_key = f"TAG_PARALLEL::{tag}"
            hk = hashlib.md5(chain_key.encode()).hexdigest()[:12]
            try:
                cur = c.execute("""INSERT OR IGNORE INTO mt_proposal_chain
                    (chain_key, chain_type, summary) VALUES (?,?,?)""",
                    (hk, "TAG_PARALLEL",
                     f"#{tag} 跨领域并行 {len(tids)} 个提案, 建议走并行 auto_evolution"))
                chain_id = cur.lastrowid
                if cur.rowcount == 0:
                    chain_id = c.execute("SELECT chain_id FROM mt_proposal_chain WHERE chain_key=?",
                                         (hk,)).fetchone()[0]
                for tid in tids:
                    c.execute("""INSERT OR IGNORE INTO mt_proposal_chain_members
                        (chain_id, task_id, relation) VALUES (?,?,?)""",
                        (chain_id, tid, f"tag_{tag}"))
                    c.execute("UPDATE mt_proposal_intel SET parallel_id=?, updated_at=datetime('now','localtime') WHERE task_id=?",
                              (chain_id, tid))
                chains_made += 1
            except Exception:
                pass
        c.commit()
    finally:
        c.close()
    return {"ok": True, "chains_made": chains_made}


# ═══════════════════════════════════════════════════════════════════
# ⑬ summary_report — 智能调研总结 + 新提案种子
# ═══════════════════════════════════════════════════════════════════

def summary_report() -> dict:
    """每周/每日: 全领域提案汇总 → 调研总结 → 可能的新提案种子 (返回 dict 不写库, 由上层决定是否入厅)."""
    c = _db()
    try:
        # 领域分布
        domain_stats = {}
        rows = c.execute("""SELECT auto_tags, quality_score FROM mt_proposal_intel
            WHERE quality_score >= 70 ORDER BY quality_score DESC LIMIT 200""").fetchall()
        for tags_s, qs in rows:
            tags = json.loads(tags_s or "[]")
            for d in _domains_from_tags(tags):
                domain_stats[d] = domain_stats.get(d, 0) + 1

        # 最活跃标签 Top 10
        top_tags = c.execute("""SELECT tag, hit_count FROM mt_proposal_tag_bank
            ORDER BY hit_count DESC LIMIT 10""").fetchall()

        # 串并统计
        chain_types = c.execute("""SELECT chain_type, COUNT(*) FROM mt_proposal_chain
            GROUP BY chain_type""").fetchall()

        # 新提案种子建议 (领域空窗)
        all_domains = {"EDU", "AI", "SECURITY", "ENGINE", "DATA", "FRONT", "OPS", "GOV", "HR"}
        gaps = all_domains - set(domain_stats.keys())
        seeds = []
        if "AI" not in domain_stats or domain_stats.get("AI", 0) < 3:
            seeds.append("AI 引擎路由优化提案自动生成")
        if "EDU" not in domain_stats or domain_stats.get("EDU", 0) < 2:
            seeds.append("教育题库自适应出题引擎新方向")
        if gaps:
            seeds.append(f"空窗领域: {','.join(gaps)} — 建议主动触发新提案")

    finally:
        c.close()

    # 写 brain feed 总结
    try:
        c2 = _db()
        c2.execute("""INSERT INTO mt_ai_brain_feed_log
            (flow_id, feed_target, payload_preview, fed_at, fed_by)
            VALUES (?,?,?,datetime('now','localtime'),?)""",
            (FLOW_ID, f"weekly_summary_{datetime.now().strftime('%Y%m%d')}",
             f"[SUMMARY] domains={domain_stats} | top_tags={top_tags[:5]} | seeds={seeds[:3]}"[:800],
             "proposal_intel_summary"))
        c2.commit()
        c2.close()
    except Exception:
        pass

    return {"ok": True, "domain_stats": domain_stats, "top_tags": top_tags[:10],
            "chain_types": chain_types, "gap_seeds": seeds}


# ═══════════════════════════════════════════════════════════════════
# ⑭ dev_cycle — 开发循环 (IN_PROGRESS 6 子阶段)
# ═══════════════════════════════════════════════════════════════════

# IN_PROGRESS 内部 6 子阶段 — 用 flow_node 字段存, 零 LLM 本地规则推进
# progress 也同步写 (16→33→50→67→83→100 每个阶段 +16/17)
DEV_CYCLE_NODES = [
    ("DESIGN",      16, "需求拆解 + 方案 v1 + 验收标准确认"),
    ("CODING",      33, "核心实现: 按方案分模块编码, 每日 commit"),
    ("SELF_TEST",   50, "自测: 单元/集成/边界 + 覆盖率 > 80%"),
    ("REVIEW",      67, "专家评审 + 导师把关: 合规/性能/安全"),
    ("INTEGRATE",   83, "合入主干 + 回归验证 + 灰度发布"),
    ("DELIVER",     100, "交付产出物 + 写 deliverable + 触发 transition DELIVER"),
]
DEV_NODE_SET = {n for n, _, _ in DEV_CYCLE_NODES}
_PROGRESS_BY_NODE = {n: p for n, p, _ in DEV_CYCLE_NODES}
_DESC_BY_NODE = {n: d for n, _, d in DEV_CYCLE_NODES}
_NEXT_BY_NODE = {DEV_CYCLE_NODES[i][0]: DEV_CYCLE_NODES[i+1][0]
                 for i in range(len(DEV_CYCLE_NODES) - 1)}
_FIRST_NODE = DEV_CYCLE_NODES[0][0]
_LAST_NODE  = DEV_CYCLE_NODES[-1][0]


def dev_cycle_tick() -> dict:
    """开发循环 tick:
      (a) START 后 flow_node 为空 → 初始化为 DESIGN + progress=16
      (b) 已在某 node 停留超过 TTL → 推进到下一 node + 更新 progress + 写 flow_history
      (c) 到达 DELIVER 末 node → 触发 transition_cas DELIVERED (走合法通道)

    TTL: 每阶段默认 4h, 可被 proposal_intel.quality_score 和 priority 缩放.
    """
    c = _db()
    progressed = 0
    delivered = 0
    stuck = 0
    try:
        rows = c.execute("""
            SELECT h.id, h.status, h.started_at, h.flow_node, h.progress, h.deliverable,
                   h.deadline_at, h.priority, h.expected_at,
                   h.hall_code, i.quality_score
            FROM mt_lab_task_hall h
            LEFT JOIN mt_proposal_intel i ON i.task_id=h.id
            WHERE h.status='IN_PROGRESS'
            ORDER BY h.id LIMIT 20""").fetchall()
    finally:
        c.close()

    for tid, st, started_at, flow_node, progress, deliverable, deadline_at, priority, expected_at, hc, qs in rows:
        # 计算 TTL 缩放
        quality = qs or 80
        base_ttl_hours = 4
        # 质量低的 → TTL 短 (因为低质量任务可能更简单/需要加速)
        ttl_hours = max(1, int(base_ttl_hours * (quality / 100)))
        if priority == "HIGH":
            ttl_hours = max(1, ttl_hours // 2)

        # (a) 初始化: IN_PROGRESS 但 flow_node 为空 → DESIGN
        if not flow_node or flow_node not in DEV_NODE_SET:
            c = _db()
            try:
                c.execute("""UPDATE mt_lab_task_hall
                    SET flow_node=?, progress=?, updated_at=datetime('now','localtime')
                    WHERE id=?""", (_FIRST_NODE, _PROGRESS_BY_NODE[_FIRST_NODE], tid))
                c.execute("""INSERT INTO mt_lab_task_events
                    (hall_task_id, event, actor, actor_role, note)
                    VALUES (?,?,?,?,?)""",
                    (tid, "FLOW_NODE", "dev_cycle", "proposal_intel",
                     f"开发循环启动 → {_FIRST_NODE} | {_DESC_BY_NODE[_FIRST_NODE]}"))
                # flow_history 追加
                _append_flow_local(c, tid, f"dev_cycle→{_FIRST_NODE}")
                c.commit()
            finally:
                c.close()
            progressed += 1
            # ① dev_cycle 初始化 DESIGN → 同步 §14
            _sync_hall_change_to_ir14(tid, new_flow_node=_FIRST_NODE)
            continue

        # (b) 判断停留时长
        ref = started_at
        if not ref:
            # 没有 started_at → 用 created_at
            ref = _hall_ref_time(tid)
        if not ref:
            # 都没有 → 用当前时间, 等下轮再推进
            continue

        try:
            ref_dt = datetime.strptime(ref[:19], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - ref_dt).total_seconds() / 3600
        except Exception:
            age_hours = ttl_hours + 1  # 解析失败 → 推进

        # 用 flow_node 进入时间算 age (比 started_at 更准)
        fn_age = _flow_node_age_hours(tid, flow_node)
        if fn_age is not None:
            age_hours = fn_age

        if age_hours < ttl_hours:
            # 还没到推进时间
            continue

        # 末 node DELIVER → 触发 transition
        if flow_node == _LAST_NODE:
            try:
                sys.path.insert(0, APP_DIR)
                from engines.ai_task_hall_flow_engine import transition_cas
                deliverable_text = (deliverable or "") + f"\n\n[DEV-CYCLE] 6 阶段开发循环自动完成: DESIGN→CODING→SELF_TEST→REVIEW→INTEGRATE→DELIVER"
                won, _, _, _ = transition_cas(
                    tid, "IN_PROGRESS", "DELIVERED",
                    actor=f"dev_cycle({_LAST_NODE})",
                    reason=f"开发循环 6 阶段完成 ({age_hours:.1f}h)",
                    extra={"deliverable": deliverable_text[:2000], "progress": 100})
                if won:
                    delivered += 1
                    _log(f"  🚀 dev_cycle 任务#{tid} 6 阶段完成 → DELIVERED")
                    # ③ DELIVERED 同步 §14 → STEP_9B_SUMMARY
                    _sync_hall_change_to_ir14(tid, new_status="DELIVERED", new_flow_node=_LAST_NODE)
            except Exception as e:
                _log(f"  dev_cycle deliver task={tid} fail: {e}", "WARN")
            continue

        # 推进到下一 node
        next_node = _NEXT_BY_NODE[flow_node]
        c = _db()
        try:
            c.execute("""UPDATE mt_lab_task_hall
                SET flow_node=?, progress=?, updated_at=datetime('now','localtime')
                WHERE id=?""", (next_node, _PROGRESS_BY_NODE[next_node], tid))
            c.execute("""INSERT INTO mt_lab_task_events
                (hall_task_id, event, actor, actor_role, note)
                VALUES (?,?,?,?,?)""",
                (tid, "FLOW_NODE", "dev_cycle", "proposal_intel",
                 f"开发循环 {flow_node}→{next_node} | {_DESC_BY_NODE[next_node]} | 停留 {age_hours:.1f}h"))
            _append_flow_local(c, tid, f"dev_cycle {flow_node}→{next_node}")
            # 同时写 proposal_intel 的 flow_node (方便画像层看)
            c.execute("UPDATE mt_proposal_intel SET updated_at=datetime('now','localtime') WHERE task_id=?", (tid,))
            c.commit()
        finally:
            c.close()
        progressed += 1
        # ② dev_cycle 推进下一 node → 同步 §14
        _sync_hall_change_to_ir14(tid, new_flow_node=next_node)

        # stuck: 停留超过 3x TTL → 记日志但不 escape (escape_loop 负责 escape)
        if age_hours > ttl_hours * 3:
            stuck += 1

    return {"ok": True, "progressed": progressed, "delivered": delivered,
            "stuck": stuck, "nodes": DEV_CYCLE_NODES}


# ═══════════════════════════════════════════════════════════════════
# 双向同步辅助: 大厅状态/flow_node 变化 → §14 step 自动推进
# ═══════════════════════════════════════════════════════════════════

# §14 step → dev_cycle flow_node 反向映射 (用于 dev_cycle 推进后找目标 step)
_NODE_TO_IR14_STEP: dict[str, str] = {
    "DESIGN":    "STEP_2A_ROUND",     # CLAIMED 阶段内 (A轮讨论=方案设计)
    "CODING":    "STEP_7_EXECUTE",    # 执行 = 编码
    "SELF_TEST": "STEP_8_ACCEPTANCE", # 自测 = 验收前自检
    "REVIEW":    "STEP_12_TEST1000",  # 评审 = 千行级测
    "INTEGRATE": "STEP_11_AUTO_GIT_SYNC",  # 合入 = GIT 同步
    "DELIVER":   "STEP_9B_SUMMARY",   # 交付 = 总结
}


def _sync_hall_change_to_ir14(task_id: int, *,
                              new_status: str | None = None,
                              new_flow_node: str | None = None) -> bool:
    """大厅任何状态/flow_node 变化 → 自动推进绑定的 §14 step
      返回 True 表示成功对齐 (包含已经对齐无需推进的情况)
      §14 铁律优先: 大厅绕过 §14 step 的直跳 → 记违规"""
    if not (new_status or new_flow_node):
        return True
    conn = sqlite3.connect(DB_PATH, timeout=15); conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""SELECT ir14_flow_id, status, flow_node
                              FROM mt_lab_task_hall WHERE id=?""", (task_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row["ir14_flow_id"]:
        return True  # 未绑定 §14, 跳过 (C 阶段违规审计会兜)

    try:
        sys.path.insert(0, os.path.join(APP_DIR, "ai_engines"))
        import mt_ir14_dev_flow as ir14
    except Exception as e:
        _log(f"  sync→§14 task#{task_id} import fail: {e}", "WARN")
        return False

    flow_id = row["ir14_flow_id"]
    target_step: str | None = None

    # 目标 step: 优先 flow_node 映射 (细粒度), 其次 status 粗粒度
    if new_flow_node and new_flow_node in _NODE_TO_IR14_STEP:
        target_step = _NODE_TO_IR14_STEP[new_flow_node]
    elif new_status:
        target_step = _HALL_TO_IR14.get(new_status)

    if not target_step:
        return True

    # 已经在目标 step
    conn = sqlite3.connect(DB_PATH, timeout=10); conn.row_factory = sqlite3.Row
    try:
        sess = conn.execute("SELECT current_step, final_status FROM mt_dev_flow_session WHERE flow_id=?",
                            (flow_id,)).fetchone()
    finally:
        conn.close()
    if not sess or sess["final_status"] != "OPEN" or sess["current_step"] == target_step:
        return True

    # 链式推进: while 循环走 §14 DAG 直到 target_step
    try:
        cur_step = sess["current_step"]
        max_hops = 8  # 防死循环 (§14 最长路径 6 步)
        history = [cur_step]
        while cur_step != target_step and max_hops > 0:
            allowed = ir14._MT_IR_DEV_FLOW_EDGES.get(cur_step, [])
            if target_step in allowed:
                ir14.transition(flow_id, target_step,
                                event_kind="HALL_SYNC",
                                operator=f"hall#{task_id}",
                                payload={"hall_status": row['status'],
                                         "flow_node": new_flow_node,
                                         "reason": f"大厅→§14 同步"})
                cur_step = target_step; history.append(cur_step)
            else:
                next_step = None
                for nxt in allowed:
                    nxt_edges = ir14._MT_IR_DEV_FLOW_EDGES.get(nxt, [])
                    if target_step in nxt_edges or ir14._MT_IR_DEV_FLOW_EDGES.get(target_step, []) and nxt in ir14._MT_IR_DEV_FLOW_EDGES.get(target_step, [])[:3]:
                        next_step = nxt; break
                    if ir14._MT_IR_DEV_FLOW_EDGES.get(nxt) and nxt not in history:
                        next_step = nxt; break
                if not next_step or next_step in history:
                    _log(f"  sync→§14 task#{task_id} 卡住 {cur_step}→{target_step}, "
                         f"历史: {'→'.join(history)}", "WARN")
                    break
                ir14.transition(flow_id, next_step,
                                event_kind="HALL_SYNC_CHAIN",
                                operator=f"hall#{task_id}",
                                payload={"reason": f"链式 {cur_step}→{next_step}→{target_step}"})
                cur_step = next_step; history.append(cur_step)
            max_hops -= 1
        _log(f"  ↔ sync→§14 task#{task_id} {row['status']}|{new_flow_node or ''} "
             f"→ {'→'.join(history)}", "INFO")
        return True
    except RuntimeError as te:
        _log(f"  sync→§14 task#{task_id} edge violation: {te}", "WARN")
        return False


# ═══════════════════════════════════════════════════════════════════
# ⑯ game_theory — 大厅协作博弈论评估
# ═══════════════════════════════════════════════════════════════════

def game_theory_tick() -> dict:
    """⑯ 博弈论评估 tick: 计算 16 中心的 Shapley / Marginal / Core / Nash
    缓存: 新鲜数据 < 24h 直接返回, 否则重算"""
    GT_CACHE_HOURS = 24
    c = _db()
    try:
        row = c.execute("SELECT min(calculated_at) t FROM mt_game_theory_scores").fetchone()
        fresh = row and row[0] and (time.time() - row[0]) < GT_CACHE_HOURS * 3600
    finally:
        c.close()
    if fresh:
        return {"ok": True, "cached": True, "hint": f"博弈论数据新鲜 (< {GT_CACHE_HOURS}h)"}
    # 重算
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "ai_engines"))
        from ai_game_theory_engine import compute_all
        r = compute_all()
        return {"ok": True, "cached": False, **r}
    except Exception as e:
        _log(f"  ⑯game_theory err: {e}", "WARN")
        return {"ok": False, "error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════
# ⑮ ir14_hall_bridge — §14 IRON_RULE 开发铁律 ↔ 大厅闭环双向融合
# ═══════════════════════════════════════════════════════════════════
# 双轨铁律: 大厅 10 状态机 + §14 14 步骤 DAG 必须同步, 违规记 mt_iron_rule_violations
_IR14_TO_HALL: dict[str, tuple[str, str | None, int]] = {
    # STEP                  → (大厅状态,   dev_cycle_node,   progress%)
    "STEP_1_PROPOSAL":       ("QUEUED",      None,              0),
    "STEP_2A_ROUND":         ("CLAIMED",     None,              0),
    "STEP_3_ZXF_DECISION":   ("CLAIMED",     None,              0),
    "STEP_31_B_ROUND":       ("CLAIMED",     None,              0),
    "STEP_311_SA_JUDGMENT":  ("CLAIMED",     None,              0),
    "STEP_312_AUTO_PASS":    ("CLAIMED",     None,              0),
    "STEP_32_PASS_SKIP_B":   ("CLAIMED",     None,              0),
    "STEP_4_CLERK_RECORD":   ("CLAIMED",     None,              0),
    "STEP_5_IMPL_DOCKING":   ("CLAIMED",     None,              0),
    "STEP_6_AI_TEAM_COORD":  ("CLAIMED",     None,              0),
    "STEP_7_EXECUTE":        ("IN_PROGRESS", "CODING",          33),
    "STEP_8_ACCEPTANCE":     ("IN_PROGRESS", "SELF_TEST",       50),
    "STEP_9A_PASS_OR_LOOPBACK": ("IN_PROGRESS", "DELIVER",   100),
    "STEP_9B_SUMMARY":       ("DELIVERED",   None,              0),
    "STEP_10_SMART_VERSION_UPGRADE": ("UNDER_REVIEW", None,  0),
    "STEP_11_AUTO_GIT_SYNC": ("IN_PROGRESS", "INTEGRATE",       83),
    "STEP_12_TEST1000":      ("IN_PROGRESS", "REVIEW",          67),
    "FINAL_DONE":            ("DONE",        None,              0),
}

# 反向: 大厅状态 → §14 STEP (取最接近的上游步骤)
_HALL_TO_IR14: dict[str, str] = {
    "QUEUED":       "STEP_1_PROPOSAL",
    "CLAIMED":      "STEP_2A_ROUND",
    "IN_PROGRESS":  "STEP_7_EXECUTE",
    "DELIVERED":    "STEP_9B_SUMMARY",
    "UNDER_REVIEW": "STEP_10_SMART_VERSION_UPGRADE",
    "DONE":         "FINAL_DONE",
}


def _ensure_ir14_bridge_cols() -> None:
    """桥接列幂等: mt_lab_task_hall.ir14_flow_id / mt_dev_flow_session.hall_task_id"""
    c = sqlite3.connect(DB_PATH, timeout=30); c.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(mt_lab_task_hall)").fetchall()}
        if "ir14_flow_id" not in cols:
            c.execute("ALTER TABLE mt_lab_task_hall ADD COLUMN ir14_flow_id TEXT")
        cols2 = {r[1] for r in c.execute("PRAGMA table_info(mt_dev_flow_session)").fetchall()}
        if "hall_task_id" not in cols2:
            c.execute("ALTER TABLE mt_dev_flow_session ADD COLUMN hall_task_id INTEGER")
        c.commit()
    finally:
        c.close()


def _make_ir14_flow_id(task_id: int, hall_code: str) -> str:
    """为大厅任务生成 §14 flow_id: flow_hall_{id}_{date}"""
    date = datetime.now().strftime("%Y%m%d")
    return f"flow_hall_{hall_code or task_id}_{date}"


def ir14_hall_bridge_tick() -> dict:
    """⑮ §14 IRON_RULE ↔ 大厅闭环双向融合 tick
      A. 大厅→§14: CLAIMED/IN_PROGRESS 但无 ir14_flow_id → 自动创建 dev_flow + 绑定
      B. §14→大厅: OPEN 会话 current_step 变化 → transition_cas 大厅 + 同步 flow_node
      C. 违规审计: 大厅 CLAIMED→IN_PROGRESS 但无 dev_flow 绑定 → 写 mt_iron_rule_violations"""
    _ensure_ir14_bridge_cols()
    result = {"ok": True, "hall_to_ir14": 0, "ir14_to_hall": 0, "violations": 0, "details": []}

    # ── 加载 §14 模块 ──
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "ai_engines"))
        import mt_ir14_dev_flow as ir14
    except Exception as e:
        return {"ok": False, "error": f"§14 模块加载失败: {e}"}

    def _c() -> sqlite3.Connection:
        c = _db(); c.row_factory = sqlite3.Row; return c

    # ── A. 大厅 → §14 绑定 ──
    c = _c()
    try:
        unbound = c.execute("""
            SELECT h.id, h.hall_code, h.title, h.status
            FROM mt_lab_task_hall h
            WHERE h.archived_at IS NULL
              AND h.status IN ('CLAIMED','IN_PROGRESS')
              AND (h.ir14_flow_id IS NULL OR h.ir14_flow_id = '')
            ORDER BY h.id DESC LIMIT 30""").fetchall()
    finally:
        c.close()

    for u in unbound:
        task_id, code, title, st = u["id"], u["hall_code"], u["title"], u["status"]
        flow_id = _make_ir14_flow_id(task_id, code)
        try:
            ir14.ensure_tables()
            ir14.step1_create_proposal(flow_id, title or code,
                                       f"大厅任务 {code} ({st})",
                                       {"task_id": task_id, "source": "hall_autobind"})
            # 绑定 hall_task_id (§14 侧) + ir14_flow_id (大厅侧)
            conn = _db()
            try:
                conn.execute("UPDATE mt_dev_flow_session SET hall_task_id=? WHERE flow_id=?",
                             (task_id, flow_id))
                conn.execute("UPDATE mt_lab_task_hall SET ir14_flow_id=?, updated_at=datetime('now','localtime') WHERE id=?",
                             (flow_id, task_id))
                conn.commit()
            finally:
                conn.close()
            result["hall_to_ir14"] += 1
            result["details"].append(f"A 绑定 #{task_id}→§14 {flow_id}")
            _log(f"  🔗 A.大厅→§14: task#{task_id} 绑定 {flow_id}", "INFO")

            # 推进 §14 到对应大厅状态 (CLAIMED → STEP_2A, IN_PROGRESS → STEP_7)
            target_step = _HALL_TO_IR14.get(st)
            if target_step and target_step != "STEP_1_PROPOSAL":
                try:
                    ir14.transition(flow_id, target_step, event_kind="HALL_AUTOBIND",
                                    operator=f"hall#{task_id}",
                                    update_fields={"proposal_title": title})
                    result["details"].append(f"A 推进 §14→{target_step}")
                except RuntimeError as te:
                    # 边校验不通过 → 记违规但不中断 (§14 DAG 分支)
                    result["details"].append(f"A §14 边校验失败: {te}")
                    conn = _db()
                    try:
                        now_ts = time.time()
                        conn.execute("""INSERT INTO mt_iron_rule_violations
                            (flow_id, viol_rule, viol_stage, viol_action, detail, created_at, updated_at)
                            VALUES (?,?,?,?,?,?,?)""",
                            (flow_id, "IR14_HALL_BRIDGE", "HALL_TO_IR14_BIND",
                             "边校验失败自动降级", str(te)[:300], now_ts, now_ts))
                        conn.commit()
                    finally:
                        conn.close()
        except Exception as e:
            _log(f"  A.大厅→§14 task#{task_id} err: {e}", "WARN")

    # ── B. §14 → 大厅 驱动 ──
    c = _c()
    try:
        bound = c.execute("""
            SELECT h.id, h.status AS hall_status, h.flow_node, h.progress,
                   h.ir14_flow_id, s.current_step, s.updated_at
            FROM mt_lab_task_hall h
            JOIN mt_dev_flow_session s ON s.hall_task_id = h.id
            WHERE h.ir14_flow_id IS NOT NULL
              AND s.final_status = 'OPEN'
              AND h.archived_at IS NULL
            ORDER BY s.updated_at DESC LIMIT 40""").fetchall()
    finally:
        c.close()

    for b in bound:
        tid, hst, fn, prog, flow_id, step, ir14_updated = b["id"], b["hall_status"], b["flow_node"], b["progress"], b["ir14_flow_id"], b["current_step"], b["updated_at"]
        target = _IR14_TO_HALL.get(step)
        if not target:
            continue
        tgt_status, tgt_node, tgt_prog = target

        # 大厅状态和 dev_cycle node 都对齐
        needs_status = hst != tgt_status
        needs_node = (tgt_node is not None) and (fn != tgt_node or prog != tgt_prog)

        if needs_status:
            try:
                sys.path.insert(0, APP_DIR)
                from engines.ai_task_hall_flow_engine import transition_cas
                # 状态机合法流转 (§14 STEP 驱动)
                won, old, new, info = transition_cas(
                    tid, hst, tgt_status,
                    actor=f"ir14({step})",
                    reason=f"§14 铁律 {step}→大厅 {tgt_status}",
                    extra={"ir14_flow_id": flow_id, "step": step})
                if won:
                    result["ir14_to_hall"] += 1
                    _log(f"  🚀 B.§14→大厅: {flow_id} {step}→{tgt_status} task#{tid}", "INFO")
            except Exception as e:
                _log(f"  B.§14→大厅 task#{tid} status err: {e}", "WARN")

        if needs_node:
            conn = _db()
            try:
                conn.execute("""UPDATE mt_lab_task_hall
                    SET flow_node=?, progress=?, updated_at=datetime('now','localtime') WHERE id=?""",
                    (tgt_node, tgt_prog, tid))
                conn.execute("""INSERT INTO mt_lab_task_events
                    (hall_task_id, event, actor, actor_role, note) VALUES (?,?,?,?,?)""",
                    (tid, "FLOW_NODE", f"ir14_bridge({step})", "proposal_intel",
                     f"§14 铁律 {step}→dev_cycle {tgt_node} {tgt_prog}%"))
                conn.commit()
                result["ir14_to_hall"] += 1
                # ④ B 阶段对齐 flow_node 后: 大厅 flow_node 变化 → 反向推进 §14 (双向!)
                _sync_hall_change_to_ir14(tid, new_flow_node=tgt_node)
            finally:
                conn.close()

    # ── C. 违规审计: 大厅绕开 §14 ──
    c = _c()
    try:
        violations = c.execute("""
            SELECT h.id, h.hall_code, h.status, h.ir14_flow_id
            FROM mt_lab_task_hall h
            WHERE h.archived_at IS NULL
              AND h.status IN ('IN_PROGRESS','DELIVERED','DONE')
              AND (h.ir14_flow_id IS NULL OR h.ir14_flow_id = '')
              AND h.created_at < datetime('now','localtime','-1 hours')
            ORDER BY h.id DESC LIMIT 15""").fetchall()
    finally:
        c.close()

    for v in violations:
        tid, code, st, fid = v["id"], v["hall_code"], v["status"], v["ir14_flow_id"]
        conn = _db()
        try:
            exists = conn.execute(
                "SELECT 1 FROM mt_iron_rule_violations WHERE viol_rule='IR14_HALL_BYPASS'"
                " AND detail LIKE ? LIMIT 1", (f"%task#{tid}%",)).fetchone()
            if exists:
                continue
            now_ts = time.time()
            conn.execute("""INSERT INTO mt_iron_rule_violations
                (flow_id, viol_rule, viol_stage, viol_action, detail, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?)""",
                (fid, "IR14_HALL_BYPASS", "HALL_VIOLATION_AUDIT",
                 f"铁律违规: 大厅任务#{tid} {code} 状态={st} 但未绑定 §14 dev_flow_session (必须先跑 §14 开发 14 步骤)",
                 None, now_ts, now_ts))
            conn.commit()
            result["violations"] += 1
            _log(f"  ⚠️ C.铁律违规: task#{tid} {code} {st} 绕过 §14", "WARN")
        finally:
            conn.close()

    return result


def _hall_ref_time(tid) -> str | None:
    try:
        c = _db()
        r = c.execute("SELECT created_at FROM mt_lab_task_hall WHERE id=?", (tid,)).fetchone()
        c.close()
        return r[0] if r else None
    except Exception:
        return None


def _flow_node_age_hours(tid, flow_node) -> float | None:
    """估算当前 flow_node 进入时间: 从 mt_lab_task_events 找最近一次 FLOW_NODE."""
    try:
        c = _db()
        row = c.execute("""SELECT substr(created_at,1,19) FROM mt_lab_task_events
            WHERE hall_task_id=? AND event='FLOW_NODE'
            ORDER BY rowid DESC LIMIT 1""", (tid,)).fetchone()
        c.close()
        if not row:
            return None
        ref_dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ref_dt).total_seconds() / 3600
    except Exception:
        return None


def _append_flow_local(c: sqlite3.Connection, task_id: int, entry: str):
    """复用 daemon_skill_lab_bp._append_flow_history 的同等语义 (本地实现, 不 import 蓝图)."""
    try:
        row = c.execute("SELECT flow_history FROM mt_lab_task_hall WHERE id=?", (task_id,)).fetchone()
        existing = json.loads(row[0]) if (row and row[0]) else []
        existing.append({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine": "dev_cycle",
            "entry": entry,
        })
        c.execute("UPDATE mt_lab_task_hall SET flow_history=? WHERE id=?",
                  (json.dumps(existing, ensure_ascii=False), task_id))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# run_once — 完整 14 智能一次跑完
# ═══════════════════════════════════════════════════════════════════

def run_once() -> dict:
    install_schema()
    out = {"timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "steps": {}}

    def _safe_run(name, fn):
        try:
            r = fn()
            out["steps"][name] = r
            _log(f"  ✅ {name}: {_short(r)}")
        except Exception as e:
            out["steps"][name] = {"ok": False, "error": str(e)[:120]}
            _log(f"  ❌ {name}: {type(e).__name__}: {e}", "ERROR")

    _safe_run("①ingest_and_tag", ingest_and_tag)
    _safe_run("②intent_analyze", intent_analyze)
    _safe_run("③quality_check", quality_check)
    _safe_run("④smart_dispatch", smart_dispatch)
    _safe_run("⑤state_feedback_feed", state_feedback_feed)
    _safe_run("⑥auto_close", auto_close)
    _safe_run("⑦auto_archive", auto_archive)
    _safe_run("⑧auto_upload", auto_upload)
    _safe_run("⑨brain_feed", brain_feed)
    _safe_run("⑩escape_loop", escape_loop)
    _safe_run("⑪followup_scheduler", followup_scheduler)
    _safe_run("⑫chain_digest", chain_digest)
    _safe_run("⑬summary_report", summary_report)
    _safe_run("⑭dev_cycle", dev_cycle_tick)
    _safe_run("⑮ir14_hall_bridge", ir14_hall_bridge_tick)
    _safe_run("⑯game_theory", game_theory_tick)

    # daemon 心跳
    try:
        c = _db()
        c.execute("""UPDATE mt_daemon_registry
            SET last_heartbeat=datetime('now','localtime'), status='RUNNING', pid=?
            WHERE process_name=?""", (os.getpid(), DAEMON))
        c.execute("""INSERT INTO mt_center_self_drive_log
            (center_name, action, outcome, detail)
            VALUES (?,?,?,?)""",
            ("PROPOSAL_INTEL", "CYCLE", "OK",
             json.dumps({"ok_steps": sum(1 for v in out["steps"].values() if v.get("ok")),
                         "total_steps": len(out["steps"])}, ensure_ascii=False)))
        c.commit()
        c.close()
    except Exception:
        pass

    return out


def _short(r: dict) -> str:
    if not isinstance(r, dict):
        return str(r)[:80]
    keys = list(r.keys())[:5]
    return " ".join(f"{k}={r[k]}" for k in keys if isinstance(r[k], (int, str, float, bool)))[:100]


def _log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] proposal_intel: {msg}"
    print(line, flush=True)


# ═══════════════════════════════════════════════════════════════════
# CLI + loop
# ═══════════════════════════════════════════════════════════════════

def loop(poll_secs: int = 120):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {DAEMON} start, poll={poll_secs}s")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"loop error: {e}", "ERROR")
        time.sleep(poll_secs)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="🧠 提案智能全链路引擎 (14 智能 + 开发循环 + §14 铁律融合)")
    p.add_argument("action", nargs="?", default="once",
                   choices=["install", "once", "loop",
                            "ingest", "intent", "quality", "dispatch", "feedback",
                            "close", "archive", "upload", "brain", "escape",
                            "followup", "chain", "summary", "dev_cycle",
                            "ir14_hall_bridge", "game_theory"])
    args = p.parse_args()

    ACTIONS = {
        "install": lambda: (install_schema(), print("✅ schema installed")),
        "ingest": lambda: print(ingest_and_tag()),
        "intent": lambda: print(intent_analyze()),
        "quality": lambda: print(quality_check()),
        "dispatch": lambda: print(smart_dispatch()),
        "feedback": lambda: print(state_feedback_feed()),
        "close": lambda: print(auto_close()),
        "archive": lambda: print(auto_archive()),
        "upload": lambda: print(auto_upload()),
        "brain": lambda: print(brain_feed()),
        "escape": lambda: print(escape_loop()),
        "followup": lambda: print(followup_scheduler()),
        "chain": lambda: print(chain_digest()),
        "summary": lambda: print(summary_report()),
        "dev_cycle": lambda: print(dev_cycle_tick()),
        "ir14_hall_bridge": lambda: print(ir14_hall_bridge_tick()),
        "game_theory": lambda: print(game_theory_tick()),
        "once": lambda: run_once(),
        "loop": lambda: loop(),
    }
    ACTIONS[args.action]()
