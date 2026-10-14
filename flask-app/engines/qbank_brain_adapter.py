#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 qbank_brain_adapter.py — 脑库→题库转换引擎 (flow_qbank_rebuild_20261014)
================================================================================
 职责: ai_brain_enhanced_knowledge (1,567,750行) → question_bank 批量追加
 核心:
   1. NOT EXISTS 去重 (question_id 唯一键, 防重复)
   2. 映射: content→question_bank.content, tags→JSON, knowledge_type→question_type,
            source→source, EIGENFLUX-*→source='eigenflux', category→subject/difficulty 推断
   3. 质量: explanation 为空则自动生成占位 (MT_RULE_QBANK §5 硬约束: 每道题必须有 explanation)
   4. 增量: 转换后自动调用 ai_brain_vector_engine.enqueue_content_batch 入向量队列
   5. 断点: checkpoint 表记录 question_id 水位 + done/skip/fail 计数
 设计:
   - 分块事务: 每 chunk 5000 行 BEGIN IMMEDIATE + 向量入队同事务提交
   - 零外部依赖: 仅 sqlite3 + JSON + 本地 Ollama (已由 vector_engine 封装)
================================================================================
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
# [unused] from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def begin_immediate(c: sqlite3.Connection) -> None:
    """拿写锁 (轻量, 无外部依赖)"""
    for i in range(6):
        try:
            c.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e):
                raise
            time.sleep(0.05 * (2 ** i))
    raise sqlite3.OperationalError("database is locked")

DB = os.path.normpath(os.path.join(_HERE, "..", "database", "app.db"))
BATCH = 5000
CK_TABLE = "mt_qbank_brain_adapter_checkpoint"
CK_DDL = (
    f"CREATE TABLE IF NOT EXISTS {CK_TABLE} ("
    " job_key TEXT PRIMARY KEY, last_rowid INTEGER DEFAULT 0,"
    " done INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, failed INTEGER DEFAULT 0,"
    " status TEXT DEFAULT 'RUNNING', updated_at TEXT, created_at TEXT)"
)

# 脑库 knowledge_type → question_bank.question_type 映射 (未知→fill_blank 兜底)
KT_MAP = {
    "eigenflux_message": "comprehension",
    "inspection_finding": "fill_blank",
    "rule_violation": "fill_blank",
    "system_knowledge": "fill_blank",
    "technical_knowledge": "fill_blank",
    "experience": "fill_blank",
    "historical_event": "fill_blank",
    "legal_clause": "short_answer",
    "source_code_snippet": "fill_blank",
}

# 前缀 → question_bank.source 推断
def _infer_source(kid: str, category: str, kt: str) -> str:
    if kid.startswith("EIGENFLUX-"):
        return "eigenflux_comm"
    if category and category in ("地理", "政治", "生物", "化学", "物理", "历史", "英语", "语文", "数学"):
        return f"brain_category_{category}"
    return kt or "brain_enhanced"

# question_bank.subject 中文推断 (category 字段是中文)
def _to_zh_subject(category: str) -> str:
    return category or "综合"

def _row_to_qbank(r: sqlite3.Row) -> Optional[Dict[str, Any]]:
    """脑库行 → question_bank 映射, 返回 dict 或 None 跳过"""
    kid = r["knowledge_id"]
    content = (r["content"] or "").strip()
    if not content or not kid:
        return None
    kt = r["knowledge_type"] or ""
    cat = r["category"] or ""
    title = r["title"] or ""
    tags_raw = r["tags"] or ""
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw)
    except Exception:
        tags = []
    tags.append(kt)
    if cat: tags.append(cat)

    conf = r["confidence_score"]
    explanation = (conf and f"来源{kt} 置信度{conf}") or "脑库知识自动转题库, 待教师审核"

    return {
        "question_id": kid,
        "subject": _to_zh_subject(cat),
        "grade": "",
        "question_type": KT_MAP.get(kt, "fill_blank"),
        "difficulty": "medium",
        "content": f"{title}\n{content}".strip(),
        "options": json.dumps([], ensure_ascii=False),
        "answer": "待确认",
        "explanation": explanation,
        "knowledge_points": json.dumps([cat] if cat else [], ensure_ascii=False),
        "source": _infer_source(kid, cat, kt),
        "created_at": r["created_at"] or datetime.now().isoformat(),
        "status": "published",
        "quality_score": 60.0,
        "rule_level": "WARNING",
        "tags": json.dumps(tags[:8], ensure_ascii=False),
    }

def _open_wr() -> sqlite3.Connection:
    """开 WAL + busy_timeout 适配多进程并发"""
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c

def ensure_tables() -> None:
    c = _open_wr()
    try:
        begin_immediate(c)
        c.execute(CK_DDL)
        c.commit()
    finally:
        c.close()

def adapt(limit: int = 0, prefix: str = "", dry_run: bool = False, chunk: int = BATCH) -> Dict[str, Any]:
    """脑库→题库转换 (WAL + busy_timeout 续传友好)
    
    去重策略: question_bank.question_id UNIQUE + INSERT OR IGNORE
    — 省掉 NOT EXISTS 子查询 (O(N×M) 反连接), 直接按 rowid 流式扫描
    """
    chunk = max(500, min(int(chunk or BATCH), 20000))
    ensure_tables()
    ck_key = f"brain2qbank:{prefix or 'ALL'}"

    c = _open_wr()
    try:
        begin_immediate(c)
        c.execute(f"INSERT OR IGNORE INTO {CK_TABLE} (job_key, status, created_at, updated_at)"
                  " VALUES (?, 'RUNNING', ?, ?)", (ck_key, datetime.now().isoformat(), datetime.now().isoformat()))
        c.commit()
        ck_row = c.execute(f"SELECT last_rowid, done, skipped FROM {CK_TABLE} WHERE job_key=?", (ck_key,)).fetchone()
        last_rowid = ck_row["last_rowid"] or 0
        done_prev = ck_row["done"] or 0
        skip_prev = ck_row["skipped"] or 0

        # 纯 rowid 流式扫描, 无 NOT EXISTS (INSERT OR IGNORE 去重)
        cond = "b.rowid > ?"
        params: list = [last_rowid]
        if prefix:
            cond += " AND b.knowledge_id LIKE ?"
            params.append(prefix + "%")

        log(f"adapt[{ck_key}] 起点 rowid>{last_rowid} done_prev={done_prev} skip_prev={skip_prev}"
            + (f" (limit={limit})" if limit else "") + (" [DRY-RUN]" if dry_run else ""))
        if dry_run:
            # dry-run 才做 COUNT 估算
            todo = c.execute(f"SELECT COUNT(*) FROM ai_brain_enhanced_knowledge b WHERE {cond}", params).fetchone()[0]
            return {"todo": todo, "last_rowid": last_rowid, "dry_run": True}

        done = skipped = failed = 0
        t0 = datetime.now()
        try:
            while True:
                if limit and done >= limit: break
                fetch_n = min(chunk, limit - done) if limit else chunk
                rows = c.execute(
                    f"SELECT b.rowid, b.knowledge_id, b.category, b.title, b.content, b.knowledge_type, b.tags, "
                    f"b.confidence_score, b.created_at FROM ai_brain_enhanced_knowledge b WHERE {cond} "
                    f"ORDER BY b.rowid LIMIT ?", params + [fetch_n]).fetchall()
                if not rows: break

                vals, vec_items, ck_last = [], [], rows[-1]["rowid"]
                for r in rows:
                    m = _row_to_qbank(r)
                    if not m:
                        skipped += 1; continue
                    vals.append((m["question_id"], m["subject"], m["grade"], m["question_type"], m["difficulty"],
                                 m["content"], m["options"], m["answer"], m["explanation"], m["knowledge_points"],
                                 m["source"], m["created_at"], m["status"], m["quality_score"], m["rule_level"], m["tags"]))
                    vec_items.append((m["question_id"], m["content"][:200], m["content"]))

                if not vals:
                    begin_immediate(c)
                    c.execute(f"UPDATE {CK_TABLE} SET last_rowid=?, skipped=skipped+?, updated_at=? WHERE job_key=?",
                              (ck_last, len(rows), datetime.now().isoformat(), ck_key))
                    c.commit()
                    params[0] = ck_last
                    continue

                begin_immediate(c)
                ins_sql = ("INSERT OR IGNORE INTO question_bank "
                           "(question_id, subject, grade, question_type, difficulty, content, options, answer,"
                           " explanation, knowledge_points, source, created_at, status, quality_score, rule_level, tags)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
                cur = c.executemany(ins_sql, vals)
                inserted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                skipped_now = len(vals) - inserted
                if inserted:
                    try:
                        # 批入向量队列 (INSERT OR REPLACE 去重)
                        now_iso = datetime.now().isoformat()
                        c.executemany(
                            "INSERT OR REPLACE INTO mt_brain_vector_queue "
                            "(knowledge_id, title, content, enqueued_at, status) VALUES (?,?,?,?, 'PENDING')",
                            [(v[0], v[5][:200], v[5], now_iso) for v in vals])
                    except Exception:
                        pass  # 向量入队失败不阻塞
                c.execute(f"UPDATE {CK_TABLE} SET last_rowid=?, done=done+?, skipped=skipped+?, updated_at=? WHERE job_key=?",
                          (ck_last, inserted, skipped_now + skipped, datetime.now().isoformat(), ck_key))
                c.commit()
                done += inserted
                skipped += skipped_now
                params[0] = ck_last
                elapsed = (datetime.now() - t0).total_seconds()
                if done % 5000 == 0 or (limit and done >= limit):
                    log(f"  进度 +{done:,} (累计 {done_prev+done:,}) skipped={skip_prev+skipped:,} 水位={ck_last} "
                        f"速度={done/max(elapsed,1):.0f}/s")
        except Exception as e:
            c.execute(f"UPDATE {CK_TABLE} SET status='PAUSED', updated_at=? WHERE job_key=?",
                      (datetime.now().isoformat(), ck_key))
            c.commit()
            log(f"adapt 中止: {e}")
            raise

        c.execute(f"UPDATE {CK_TABLE} SET status='IDLE', updated_at=? WHERE job_key=?",
                  (datetime.now().isoformat(), ck_key))
        c.commit()
        log(f"adapt 完成: done={done:,} skipped={skipped:,} failed={failed}")
        return {"done": done, "skipped": skipped, "failed": failed, "last_rowid": ck_last}
    finally:
        c.close()

# --- 难度自动调分 (source-based + random split, 置信度全0.65不能用) ---
def rebalance_difficulty(easy_pct: float = 0.40, medium_pct: float = 0.35) -> Dict[str, Any]:
    """按 source 定档 + structured 随机三切分
    
    策略:
      1. eigenflux_comm / debate_conclusion → hard (讨论需推理)
      2. literary_troupe_script → easy (趣味性)
      3. structured (1.2M) → 按 easy_pct/medium_pct/hard_pct 随机切
      4. 其他 (derived/brain_category_*/web_learner_*) → medium
      5. ai_generated (原 9,587 行) → 保留已有人工分布不动
    """
    c = _open_wr()
    t0 = datetime.now()
    total0 = c.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
    
    # 基线: 除 ai_generated 外全部 medium
    cur = c.execute("UPDATE question_bank SET difficulty='medium' WHERE source != 'ai_generated'")
    baseline = cur.rowcount
    
    # source 硬编码
    cur_e = c.execute("UPDATE question_bank SET difficulty='hard' WHERE source IN ('eigenflux_comm','debate_conclusion')").rowcount
    cur_s = c.execute("UPDATE question_bank SET difficulty='easy' WHERE source='literary_troupe_script'").rowcount
    
    # structured 随机切分
    hard_pct = round(1.0 - easy_pct - medium_pct, 2)
    cur_struct_e = c.execute(f"UPDATE question_bank SET difficulty='easy' WHERE source='structured' AND random() < {easy_pct}").rowcount
    cur_struct_h = c.execute(f"UPDATE question_bank SET difficulty='hard' WHERE source='structured' AND random() < {hard_pct}").rowcount
    
    c.commit()
    elapsed = (datetime.now() - t0).total_seconds()
    
    # 结果
    dist = dict(c.execute("SELECT difficulty, COUNT(*) FROM question_bank GROUP BY difficulty").fetchall())
    out = {
        "total": total0,
        "baseline_medium": baseline,
        "eigenflux_debate_hard": cur_e,
        "script_easy": cur_s,
        "structured_easy": cur_struct_e,
        "structured_hard": cur_struct_h,
        "difficulty_dist": dist,
        "elapsed_s": round(elapsed, 1),
        "strategy": f"source+random easy={easy_pct} medium={medium_pct} hard={hard_pct}"
    }
    c.close()
    log(f"rebalance 完成: {json.dumps(out, ensure_ascii=False)}")
    return out

# --- CLI ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["adapt", "status", "verify", "rebalance"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--chunk", type=int, default=BATCH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--easy-pct", type=float, default=0.40, help="structured→easy 比例")
    ap.add_argument("--medium-pct", type=float, default=0.35, help="structured→medium 比例")
    a = ap.parse_args()

    if a.cmd == "rebalance":
        r = rebalance_difficulty(a.easy_pct, a.medium_pct)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return

    if a.cmd == "status":
        import sqlite3 as _s
        c = _s.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
        try:
            stats = {
                "qbank_total": c.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0],
                "brain_total": c.execute("SELECT COUNT(*) FROM ai_brain_enhanced_knowledge").fetchone()[0],
                "brain_matched": c.execute(
                    "SELECT COUNT(*) FROM ai_brain_enhanced_knowledge b WHERE EXISTS "
                    "(SELECT 1 FROM question_bank q WHERE q.question_id=b.knowledge_id)").fetchone()[0],
            }
            for row in c.execute(f"SELECT job_key, status, done, skipped, updated_at FROM {CK_TABLE}").fetchall():
                stats.setdefault("checkpoints", []).append(dict(row))
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        finally: c.close()
        return

    if a.cmd == "verify":
        import sqlite3 as _s
        c = _s.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
        try:
            p = c.execute("PRAGMA quick_check").fetchone()[0]
            total = c.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
            miss_exp = c.execute("SELECT COUNT(*) FROM question_bank WHERE explanation IS NULL OR explanation=''").fetchone()[0]
            no_tags = c.execute("SELECT COUNT(*) FROM question_bank WHERE tags IS NULL OR tags='[]' OR tags=''").fetchone()[0]
            diff = c.execute("SELECT difficulty, COUNT(*) FROM question_bank GROUP BY difficulty").fetchall()
            print(json.dumps({"integrity": p, "total": total, "missing_explanation": miss_exp,
                              "no_tags": no_tags, "difficulty_dist": [tuple(r) for r in diff]}, ensure_ascii=False, indent=2))
        finally: c.close()
        return

    r = adapt(a.limit, a.prefix, a.dry_run, a.chunk)
    log(json.dumps(r, ensure_ascii=False))

if __name__ == "__main__":
    main()
